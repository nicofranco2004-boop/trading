/**
 * computeBrokerValue
 * ─────────────────
 * Single source of truth for portfolio valuation.
 *
 * Modelo de moneda base (post FX-phantom fix)
 * ───────────────────────────────────────────
 * Cada broker tiene una moneda funcional definida por su `currency`:
 *   • ARS broker  → moneda base = ARS. El usuario piensa en pesos.
 *   • USDT broker → moneda base = USD. El usuario piensa en dólares.
 *
 * Para brokers ARS, la conversión ARS→USD se hace SIEMPRE al blue actual,
 * tanto para `value` como para `invested`. Eso elimina el "FX phantom":
 * si tenés 1.5M ARS quietos y el blue se mueve, tu valor en USD cambia,
 * pero también tu costo en USD — el P&L en USD reportado solo refleja el
 * rendimiento real del activo (no la fluctuación cambiaria).
 *
 * Si querés materializar una compra/venta de USD adentro de un broker ARS,
 * usá el endpoint /api/conversions: debita ARS del padre y acredita USD a
 * un sub-broker `<Padre> · USD`. Los USD ya viven en moneda dura y rinden
 * solo por movimiento de mercado.
 *
 * Notas
 * ─────
 * • `p.tc_compra` queda como dato informativo (se mantiene para backwards
 *   compat y para la columna "TC Compra" en Positions). NO se usa más para
 *   calcular cost basis USD.
 * • `realCost = p.invested + p.commissions` sigue siendo el costo económico
 *   en moneda nativa del broker.
 * • Si no hay precio live, value = cost (P&L = 0 para esa posición).
 *
 * @param {Array}  allPositions  Full positions array from GET /api/positions
 * @param {Object} prices        { [symbol]: number|null } — from GET /api/prices
 * @param {Object} broker        { name: string, currency: 'ARS'|'USDT' }
 * @param {number} tcBlue        Current ARS/USD blue-dollar rate
 *
 * @returns {{
 *   value:    number,   // Total USD value (open positions + cash).
 *   invested: number,   // USD cost basis (ARS broker: realCost / blue actual).
 *   valueArs: number,   // Total ARS value. Meaningful only for ARS brokers.
 *   invArs:   number,   // ARS invested (Σ realCost). Meaningful only for ARS brokers.
 *   pnlUsd:   number,   // value − invested  (also == pnlForGlobal contribution).
 *   pnlArs:   number,   // valueArs − invArs. Meaningful only for ARS brokers.
 * }}
 *
 * Derived values callers commonly need
 * ─────────────────────────────────────
 * • Global P&L contribution  → result.pnlUsd   (same for both ARS and USD brokers)
 * • Amount to store in monthly_entries.pnl_unrealized:
 *     ARS broker → result.pnlArs / tcBlue
 *     USD broker → result.pnlUsd
 */
/**
 * priceSymbol — símbolo con el que se pide/busca el precio de un asset.
 *
 * Los FCI (prefijo 'FCI:') se piden tal cual: el backend los resuelve desde la
 * tabla fci_prices (valor de cuotaparte), no pasan por yfinance. El resto de
 * los activos en un broker ARS llevan el sufijo .BA (BCBA via yfinance).
 *
 * @param {string} asset  Símbolo crudo de la posición (p.asset)
 * @param {boolean} isARS Si el broker es ARS
 * @returns {string}
 */
export function priceSymbol(asset, isARS) {
  if ((asset || '').startsWith('FCI:')) return asset
  return isARS ? `${asset}.BA` : asset
}

/**
 * fciLabel — nombre legible para un símbolo FCI ('FCI:FIMA-PREMIUM-A').
 *
 * Prettifica el slug sin necesidad de pegar al catálogo: saca el prefijo,
 * separa la clase (última letra/dígito) y title-casea, con un par de fixes
 * para siglas y acentos. Para no-FCI devuelve el símbolo tal cual.
 *   'FCI:FIMA-PREMIUM-A'        → 'FIMA Premium · A'
 *   'FCI:FIMA-MIX-DOLARES-B'    → 'FIMA Mix Dólares · B'
 *   'FCI:1822-RAICES-AHORRO-PESOS' → '1822 Raices Ahorro Pesos'
 */
export function fciLabel(asset) {
  if (!asset || !asset.startsWith('FCI:')) return asset
  const parts = asset.slice(4).split('-')
  let cls = null
  if (parts.length > 1 && /^[A-Z0-9]$/.test(parts[parts.length - 1])) {
    cls = parts.pop()
  }
  const SIGLAS = { FIMA: 'FIMA', PB: 'PB', FBA: 'FBA', QM: 'QM', ON: 'ON', CER: 'CER' }
  const FIX = { DOLARES: 'Dólares', MEGAQM: 'MegaQM' }
  const titled = parts
    .map(w => SIGLAS[w] || FIX[w] || (w ? w.charAt(0) + w.slice(1).toLowerCase() : w))
    .join(' ')
  return cls ? `${titled} · ${cls}` : titled
}

export function computeBrokerValue(allPositions, prices, broker, tcBlue) {
  const bpos = allPositions.filter(p => p.broker === broker.name)
  let value = 0, invested = 0
  let valueArs = 0, invArs = 0

  for (const p of bpos) {
    // Cost basis económica = lo que pagaste por el activo + comisiones de compra.
    // Las comisiones SÍ son costo real — afectan el cap inicial y el P&L.
    // Para cash o legacy data sin commissions, p.commissions es 0 o null.
    const comm = p.commissions || 0
    const realCost = (p.invested || 0) + comm

    if (broker.currency === 'ARS') {
      invArs += realCost  // costo en pesos (moneda base del broker)

      if (p.is_cash) {
        const cashArs = p.invested || 0  // cash no tiene commissions
        const cashUsd = cashArs / tcBlue
        valueArs  += cashArs
        value     += cashUsd
        invested  += cashUsd  // cash en pesos: invested USD = value USD (no FX gain)
      } else {
        // FX-phantom fix: cost basis USD se calcula al blue actual, no al
        // tc_compra histórico. Así, value y invested se mueven juntos cuando
        // el blue cambia y solo aparece P&L cuando el activo realmente rinde.
        const invUsd = realCost / tcBlue
        invested += invUsd

        const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true)]
        if (priceArs != null) {
          const mktArs = priceArs * (p.quantity || 0)
          valueArs += mktArs
          value    += mktArs / tcBlue
        } else {
          // No price — show cost as value; P&L stays 0 for this position.
          valueArs += realCost
          value    += invUsd
        }
      }
    } else {
      // USD broker
      if (p.is_cash) {
        value    += p.invested || 0
        invested += p.invested || 0
      } else {
        invested += realCost

        const price = p.price_override ?? prices[p.asset]
        if (price != null) {
          value += price * (p.quantity || 0)
        } else {
          // No price — show cost as value; P&L stays 0 for this position.
          value += realCost
        }
      }
    }
  }

  return {
    value,
    invested,
    valueArs,
    invArs,
    pnlUsd: value - invested,
    pnlArs: valueArs - invArs,
  }
}
