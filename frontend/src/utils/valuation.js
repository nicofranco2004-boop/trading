import { isCrypto, cryptoBrokerFactor } from './crypto'

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
export function priceSymbol(asset, isARS, assetType) {
  if ((asset || '').startsWith('FCI:')) return asset
  // CEDEARs son instrumentos de BYMA: se valúan por su precio LOCAL (.BA), nunca
  // por la acción US del mismo ticker — aunque vivan en un broker USD (compra
  // dólar-MEP). Sin esto, 'MELI' se preciaría como la acción (~US$2.400) en vez
  // del CEDEAR (~US$14). Ver computeBrokerValue (rama USD) para la conversión.
  if (assetType === 'CEDEAR' && !(asset || '').endsWith('.BA')) return `${asset}.BA`
  if (isARS) return `${asset}.BA`
  // Acción US: yfinance cotiza las CLASES con guión ('BRK-B', 'BF-B'). El import de
  // brokers US (Schwab/IBKR) puede guardar 'BRK B' (espacio) o 'BRK.B' (punto) →
  // ninguno cotiza en yfinance. Normalizamos a guión para pedir/buscar el precio
  // (se usa como request Y como key de lookup, así que queda consistente; el label
  // de la posición sigue mostrando el símbolo crudo).
  return (asset || '').replace(/[\s.]+/g, '-')
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

/**
 * isArUsdBroker — ¿es un sub-broker USD de un broker AR (ej. "Cocos · USD")?
 * Todo lo que vive ahí es un instrumento de BYMA (CEDEAR o acción argentina)
 * comprado por dólar-MEP, así que se valúa por su precio LOCAL .BA ÷ MEP, NO por
 * el ticker US (PAMP/YPFD no tienen acción US; un CEDEAR vale 15-100× menos que
 * la acción). Convención de nombre del sibling: "<Padre> · USD" (· = U+00B7).
 */
export function isArUsdBroker(brokerName) {
  return /·\s*USD$/.test(brokerName || '')
}

/**
 * costInPesos — ¿el COSTO de este lote está en pesos?
 *
 * La moneda del costo se decide por el LOTE (positions.currency), no por la
 * cuenta. Un CEDEAR / acción AR comprado en PESOS queda marcado currency='ARS'
 * aunque viva en una cuenta dólar (cargado a mano o mal ruteado). Su costo va a
 * USD por el dólar-MEP — NO se cuenta como dólares (eso inflaba el "Invertido"
 * ~MEP×). USD/USDT o sin marcar → se respeta el comportamiento USD actual.
 * El VALOR de mercado ya se convierte aparte (.BA ÷ MEP), por eso solo el costo
 * quedaba mal.
 */
export function costInPesos(p) {
  // La cripto se valúa SIEMPRE en USD/spot (nunca por el MEP), aunque por error
  // tenga currency='ARS' → la excluimos para no dividir un costo cripto por el MEP
  // (y evitar doble conversión). Solo aplica a CEDEAR/acción AR/bono en pesos.
  return (p?.currency || '').toUpperCase() === 'ARS' && !isCrypto(p?.asset)
}

/**
 * pesoLotUsd — valuación USD de UN lote en PESOS (currency='ARS') que vive donde
 * sea (típicamente una cuenta USD por carga/ruteo). Costo Y valor van a USD por el
 * dólar-MEP (tcCedear) usando el precio LOCAL .BA, igual que un CEDEAR en un broker
 * AR — NO se cuenta el costo en pesos como dólares. Sin precio, el valor cae al
 * costo-USD (P&L 0). Helper compartido para que TODOS los consumidores (totales,
 * filas, detalle, Dashboard, Insights/IA, Renta Fija) conviertan igual.
 * Usar solo cuando costInPesos(p) es true.
 */
export function pesoLotUsd(p, prices, tcCedear) {
  const investedUsd = ((p.invested || 0) + (p.commissions || 0)) / tcCedear
  const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true, p.asset_type)]
  const valueUsd = priceArs != null ? (priceArs * (p.quantity || 0)) / tcCedear : investedUsd
  return { investedUsd, valueUsd, priceUsd: priceArs != null ? priceArs / tcCedear : null }
}

// ─── Guard anti-distorsión ───────────────────────────────────────────────────
// Un precio de mercado JAMÁS debe inflar una posición muy por encima de su costo.
// Casos reales: un bono cotizado "per 100 face" multiplicado por el nominal
// (×100), o una colisión de ticker (un CEDEAR/bono priceado como la acción US).
// Si el valor de mercado se va absurdamente lejos del costo, NO confiamos en el
// precio y caemos a costo (mismo efecto que "sin precio"). Así un ticker que no
// conocemos bien nunca distorsiona la cartera ($5.000 → $100.000).
//
// Solo capeamos divergencias ABSURDAS — las ganancias y pérdidas reales pasan:
//   • Renta fija (bonos/ONs/letras): cotiza cerca de la par, no multibaggea →
//     banda estrecha [0.02×, 4×]. Atrapa el ×100 y las colisiones.
//   • Acciones/CEDEARs/cripto: permiten multibaggers reales → cap generoso ×50
//     (un ×50 casi siempre es bug de pricing, no un 50-bagger).
// price_override (precio puesto a mano por el usuario) siempre se respeta.
const _FIXED_INCOME_TYPES = new Set(['BOND', 'BONO', 'ON', 'LETRA', 'LECAP'])
export function isFixedIncome(assetType) {
  return _FIXED_INCOME_TYPES.has((assetType || '').toUpperCase())
}
// ¿Confiar en el valor de mercado de una posición, o caer a costo?
//   • Sin override: banda anti-distorsión — renta fija [0.02×, 4×] (cotiza cerca
//     de par, no multibaggea), resto [0.002×, 50×] (permite multibaggers reales).
//   • Con override manual (`hasOverride`): se respeta… SALVO en renta fija, donde
//     un override absurdo igual se clampea. Caso real: una ON sin precio live con
//     un precio manual cargado en convención per-100 (97 en vez de 0,97) → valor
//     ×100 (+9775%). Un bono no puede valer ~100× su costo → no lo confiamos.
export function trustMktValue(mktValue, realCost, assetType, hasOverride = false) {
  if (!(realCost > 0) || !(mktValue > 0)) return true  // sin costo no hay con qué comparar
  const fixed = isFixedIncome(assetType)
  if (hasOverride && !fixed) return true  // override de NO-renta-fija: se respeta
  const mult = mktValue / realCost
  return fixed ? (mult <= 4 && mult >= 0.02) : (mult <= 50 && mult >= 0.002)
}

export function computeBrokerValue(allPositions, prices, broker, tcBlue, cedearRate = tcBlue, tcCripto = null) {
  const bpos = allPositions.filter(p => p.broker === broker.name)
  const arUsd = isArUsdBroker(broker.name)
  let value = 0, invested = 0
  let valueArs = 0, invArs = 0

  for (const p of bpos) {
    // Cost basis económica = lo que pagaste por el activo + comisiones de compra.
    // Las comisiones SÍ son costo real — afectan el cap inicial y el P&L.
    // Para cash o legacy data sin commissions, p.commissions es 0 o null.
    const comm = p.commissions || 0
    const realCost = (p.invested || 0) + comm

    // Lote en PESOS (currency='ARS') alojado en una cuenta USD (CEDEAR/acción AR
    // cargado en dólares o mal ruteado): se valúa estilo-ARS — costo Y valor a USD
    // por el dólar-MEP (cedearRate), igual que en un broker AR. Sin esto el costo
    // en pesos se contaba como dólares (invertido inflado ~MEP×) y el guard de
    // confianza comparaba USD vs pesos (rechazaba el precio e inflaba el valor).
    if (!p.is_cash && broker.currency !== 'ARS' && costInPesos(p)) {
      const invUsd = realCost / cedearRate
      invArs   += realCost
      invested += invUsd
      const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true, p.asset_type)]
      const mktArs = priceArs != null ? priceArs * (p.quantity || 0) : null
      const trustArs = mktArs != null &&
        trustMktValue(mktArs, realCost, p.asset_type, p.price_override != null)
      if (trustArs) { valueArs += mktArs;   value += mktArs / cedearRate }
      else          { valueArs += realCost; value += invUsd }
      continue
    }

    if (broker.currency === 'ARS') {
      invArs += realCost  // costo en pesos (moneda base del broker)

      if (p.is_cash) {
        const cashArs = p.invested || 0  // cash no tiene commissions
        const cashUsd = cashArs / tcBlue
        valueArs  += cashArs
        value     += cashUsd
        invested  += cashUsd  // cash en pesos: invested USD = value USD (no FX gain)
      } else {
        // Holdings (CEDEARs / acciones AR / bonos) → a USD por el dólar-MEP
        // (cedearRate), que es el dólar al que REALMENTE salís de la inversión y
        // el que muestra el broker. El blue es para el CASH, no para las tenencias.
        // Antes valuábamos acá al blue y el total quedaba ~2% por debajo del broker.
        // FX-phantom fix: invested y value usan el MISMO rate (MEP), así se mueven
        // juntos y solo aparece P&L cuando el activo realmente rinde.
        const invUsd = realCost / cedearRate
        invested += invUsd

        const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true)]
        const mktArs = priceArs != null ? priceArs * (p.quantity || 0) : null
        const trustArs = mktArs != null &&
          trustMktValue(mktArs, realCost, p.asset_type, p.price_override != null)
        if (trustArs) {
          valueArs += mktArs
          value    += mktArs / cedearRate
        } else {
          // Sin precio confiable — mostramos costo; P&L 0 para esta posición.
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
        // Premium dólar-cripto: la cripto de un BROKER (no exchange) se valúa al
        // dólar MEP que muestra el broker. Factor a COSTO Y valor → P&L% invariante.
        // 1 para CEDEAR/acciones/exchange/override/sin-rate.
        const f = cryptoBrokerFactor(p.asset, broker.is_exchange, p.price_override != null, tcCripto, cedearRate)
        invested += realCost * f

        if ((p.asset_type === 'CEDEAR' || arUsd) && !isCrypto(p.asset) && p.price_override == null) {
          // Instrumento de BYMA en broker USD: CEDEAR, o cualquier cosa en un
          // sub-broker AR "· USD" (acciones argentinas como PAMP/YPFD incluidas,
          // que NO tienen acción US). Se valúa por su precio LOCAL .BA (ARS) ÷ MEP
          // (cedearRate = dólar-MEP), que es lo que muestra el broker. NO por el
          // ticker US. La cripto NUNCA entra acá (no es .BA) → va a la rama spot.
          const priceArs = prices[priceSymbol(p.asset, true, p.asset_type)]
          const mktUsd = priceArs != null ? (priceArs * (p.quantity || 0)) / cedearRate : null
          value += (mktUsd != null && trustMktValue(mktUsd, realCost, p.asset_type))
            ? mktUsd : realCost
        } else {
          const price = p.price_override ?? prices[p.asset]
          const mkt = price != null ? price * (p.quantity || 0) : null
          const trust = mkt != null &&
            trustMktValue(mkt, realCost, p.asset_type, p.price_override != null)
          // Sin precio confiable — mostramos costo; P&L 0 para esta posición.
          // El factor cripto (1 para todo lo no-cripto-de-broker) escala valor.
          value += (trust ? mkt : realCost) * f
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

// ─── Plazos fijos ─────────────────────────────────────────────────────────────
// Valuación determinística (modalidad "al vencimiento"). No usa precios de
// mercado: el interés se devenga según rate_type.
//   • TNA (nominal)  → interés simple:    i = tasa × días/365
//   • TEA (efectiva) → interés compuesto: i = (1 + tasa)^(días/365) − 1
// `tasa` es fracción anual (0.19 = 19%).

function _pfDate(x) {
  if (x instanceof Date) return x
  if (typeof x === 'string') {
    const [y, m, d] = x.split('-').map(Number)
    return new Date(y, (m || 1) - 1, d || 1)
  }
  return new Date()
}

// Tasa del período según convención. dias = tramo a valuar.
function _pfPeriodRate(tasa, dias, isTea) {
  if (dias <= 0 || tasa <= 0) return 0
  return isTea ? Math.pow(1 + tasa, dias / 365) - 1 : tasa * dias / 365
}

/**
 * computePf — valúa un plazo fijo a una fecha dada.
 *
 * @param {Object} pf  { capital, tasa, rate_type, fecha_inicio, plazo_dias }
 * @param {Date|string} [asOf]  fecha de referencia (default hoy)
 * @returns {{
 *   tasaPeriodo:number, interes:number, valorVencimiento:number,
 *   diasTranscurridos:number, diasRestantes:number, vencido:boolean,
 *   devengadoHoy:number, valorHoy:number, tnaEquiv:number, teaEquiv:number
 * }}
 */
export function computePf(pf, asOf) {
  const C = +pf.capital || 0
  const r = +pf.tasa || 0
  const P = +pf.plazo_dias || 0
  const isTea = String(pf.rate_type || 'TNA').toUpperCase() === 'TEA'
  const periodic = String(pf.modalidad || 'vencimiento') === 'periodico'
  const f = +pf.pago_frecuencia_meses || 0   // meses entre capitalizaciones

  // Días transcurridos, clampeados a [0, P].
  const dRaw = Math.floor((_pfDate(asOf) - _pfDate(pf.fecha_inicio)) / 86400000)
  const diasTranscurridos = Math.max(0, Math.min(dRaw, P))
  const diasRestantes = Math.max(0, P - diasTranscurridos)
  const vencido = P > 0 && diasTranscurridos >= P

  let valorVencimiento, valorHoy, tnaEquiv = r, teaEquiv = r
  if (periodic && f > 0) {
    // Capitalización periódica: el interés se reinvierte cada `f` meses → compone.
    const periodDays = (f / 12) * 365
    const iPer = isTea ? Math.pow(1 + r, f / 12) - 1 : r * (f / 12)
    const factor = (d) => Math.pow(1 + iPer, d / periodDays)
    valorVencimiento = C * factor(P)
    valorHoy = C * factor(diasTranscurridos)
    tnaEquiv = iPer * (12 / f)                    // nominal anual
    teaEquiv = Math.pow(1 + iPer, 12 / f) - 1     // efectiva anual (compuesta)
  } else {
    // Al vencimiento: interés simple (TNA) o compuesto al plazo (TEA).
    valorVencimiento = C * (1 + _pfPeriodRate(r, P, isTea))
    valorHoy = C * (1 + _pfPeriodRate(r, diasTranscurridos, isTea))
    if (P > 0) {
      const tp = C > 0 ? valorVencimiento / C - 1 : 0
      if (isTea) tnaEquiv = (tp * 365) / P
      else teaEquiv = Math.pow(1 + tp, 365 / P) - 1
    }
  }

  const interes = valorVencimiento - C
  const devengadoHoy = valorHoy - C
  const tasaPeriodo = C > 0 ? valorVencimiento / C - 1 : 0

  return {
    tasaPeriodo, interes, valorVencimiento,
    diasTranscurridos, diasRestantes, vencido,
    devengadoHoy, valorHoy, tnaEquiv, teaEquiv,
  }
}
