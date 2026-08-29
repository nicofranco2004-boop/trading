import { isCrypto, cryptoBrokerFactor } from './crypto'
import { ARG_STOCK_TICKERS, CEDEAR_TICKERS, cedearEspecieBase } from './tickers'

/**
 * isArStock — ¿es una acción argentina (panel líder/general)? Clasificador puro.
 *
 * OJO: NO se usa para elegir .BA-vs-ADR (eso lo decide el PADRE: currency del broker /
 * isArUsdBroker, espejo de _byma en el backend). Antes forzaba .BA incondicionalmente
 * en priceSymbol/computeBrokerValue → una acción AR con ADR de mismo símbolo (GGAL,
 * BMA) en un broker USD extranjero (Schwab) se preciaba por su .BA local ÷ MEP (o
 * quedaba en "—"), cuando ahí es el ADR NYSE en USD. Se dejó como clasificador porque
 * puede ser útil (exposición AR), pero el ruteo de precio ya no depende de él.
 */
export function isArStock(asset) {
  return ARG_STOCK_TICKERS.has((asset || '').toUpperCase().replace(/\.BA$/, ''))
}

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
  // Acción argentina (GGAL, BMA, YPFD, PAMP…): a diferencia del CEDEAR, NO se fuerza
  // .BA — la decisión la toma el PADRE (isARS), igual que _byma en el backend
  // (byma_broker_names: currency + parent_broker_id). Padre ARS / sub-broker AR·USD →
  // .BA (línea de abajo). Padre USD real (Schwab, sin padre AR) → ticker pelado: el ADR
  // NYSE cuando el símbolo coincide (GGAL/BMA) o el ticker US. Forzar .BA acá preciaba
  // el ADR de Schwab por su .BA local ÷ MEP (o lo dejaba en "—" por key mismatch con
  // calcUSDT, que lee prices[asset] pelado).
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

// Registro de brokers (id/name → broker), poblado por setBrokersRegistry cuando
// la app carga /brokers. Permite decidir "sub-broker USD de padre AR" por
// parent_broker_id (ROBUSTO al rename) y no solo por el sufijo del nombre.
let _brokersByName = new Map()
let _brokersById = new Map()
export function setBrokersRegistry(brokers) {
  _brokersByName = new Map((brokers || []).filter(b => b && b.name).map(b => [b.name, b]))
  _brokersById = new Map((brokers || []).filter(b => b && b.id != null).map(b => [b.id, b]))
}

/**
 * isArUsdBroker — ¿es un sub-broker en dólares de un broker ARGENTINO (ej.
 * "Cocos · USD")? Todo lo que vive ahí es un instrumento de BYMA (CEDEAR o acción
 * argentina) comprado por dólar-MEP, así que se valúa por su precio LOCAL .BA ÷
 * MEP, NO por el ticker US (un CEDEAR vale 15-100× menos que la acción).
 *
 * PARENT-AWARE: si el broker está en el registro, se decide por parent_broker_id
 * (su padre es ARS y él no) → robusto aunque el usuario renombre el sub-broker y
 * pierda el sufijo "· USD". Fallback al sufijo del nombre si el registro no está
 * poblado o el broker es desconocido (datos viejos / carga temprana).
 */
/**
 * brokerCurrencyLabel — la moneda que se le MUESTRA al usuario.
 *
 * `brokers.currency` guarda 'USDT' como centinela INTERNO de "bucket dólar", para
 * unificar cripto y tradfi en el motor (así lo documenta `_ensure_usd_sibling` en
 * el backend: "el currency field es plumbing interno"). Pero en un sub-broker
 * dólar de un broker argentino —"Cocos · USD", comprado por dólar-MEP— lo que hay
 * son DÓLARES REALES, no Tether: mostrar "Cocos · USD (USDT)" es un error de
 * etiqueta y confunde.
 *
 * En un exchange (Binance) el USDT sí es lo que el usuario tiene, así que ahí no
 * se toca. El discriminador es el mismo que `isArUsdBroker`: moneda ≠ ARS con
 * padre ARS.
 *
 * Es SOLO presentación — no cambia `brokers.currency` ni la valuación.
 */
export function brokerCurrencyLabel(broker, brokers) {
  const ccy = (broker?.currency || '').toUpperCase()
  if (ccy !== 'USDT') return broker?.currency
  const parent = (brokers || []).find(b => b.id === broker?.parent_broker_id)
  if (parent && (parent.currency || '').toUpperCase() === 'ARS') return 'USD'
  // Fallback por nombre para datos viejos sin parent_broker_id (mismo criterio
  // que el fallback de isArUsdBroker).
  if (!broker?.parent_broker_id && /·\s*USD$/.test(broker?.name || '')) return 'USD'
  return broker?.currency
}

/**
 * cashAssetLabel — el nombre que se muestra en una fila de EFECTIVO.
 *
 * `/api/cash/flow` crea la posición cash del sub-broker dólar con asset 'USDT'
 * (mismo centinela interno que `brokers.currency`). En "Cocos · USD" eso son
 * dólares reales, no Tether. Se corrige en el display —y no en el dato— para que
 * también se vea bien en las cuentas que YA tienen esa fila creada, sin migración.
 */
export function cashAssetLabel(p) {
  if (!p?.is_cash) return p?.asset
  if ((p.asset || '').toUpperCase() !== 'USDT') return p.asset
  return isArUsdBroker(p.broker) ? 'USD' : p.asset
}

export function isArUsdBroker(brokerName) {
  const b = _brokersByName.get(brokerName)
  if (b) {
    if ((b.currency || '').toUpperCase() !== 'ARS') {
      const parent = _brokersById.get(b.parent_broker_id)
      if (parent && (parent.currency || '').toUpperCase() === 'ARS') return true
    }
    return false   // en el registro y NO es sub de un padre AR
  }
  return /·\s*USD$/.test(brokerName || '')   // fallback por nombre
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
 * holdingHasReliableFundamentals — ¿esta tenencia tiene fundamentals CONFIABLES en
 * yfinance por su símbolo? Gatea qué holdings se pueden analizar (Calidad de
 * cartera). Espeja el ruteo .BA de la valuación (mismo 'useBA': broker ARS,
 * sub-broker '· USD' dólar-MEP, o lote de costo en pesos).
 *
 * En contexto BYMA/AR, SOLO un CEDEAR reconocido mapea a una empresa US real por su
 * MISMO símbolo. Una acción argentina local (GGAL, TXAR), una especie dólar-MEP
 * (ej. 'SID' = 'SI' en dólares) o un ticker desconocido NO tienen ADR de igual
 * símbolo → yfinance devolvería una empresa yanqui homónima al azar (SID→Companhia
 * Siderúrgica Nacional, SI→Shoulder Innovations) y un análisis de negocio/precio
 * del activo EQUIVOCADO — dos "empresas" con veredictos opuestos para el MISMO
 * holding. En un broker US real el ticker SÍ es el símbolo US → confiable.
 *
 * @param {Object} p                    posición
 * @param {Set<string>} arsBrokerNames  nombres de brokers con currency==='ARS'
 * @returns {boolean}
 */
export function holdingHasReliableFundamentals(p, arsBrokerNames) {
  const onBA = arsBrokerNames.has(p?.broker) || isArUsdBroker(p?.broker) || costInPesos(p)
  if (!onBA) return true                         // broker US real → el símbolo ES el ticker US
  return CEDEAR_TICKERS.has(cedearEspecieBase(p?.asset))   // BYMA → CEDEAR reconocido (con alias de especie)
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
/**
 * costBasisRate — el dólar con el que se convierte el COSTO (invested) de un lote
 * en pesos a USD, según el modo elegido por el usuario ("Costo en dólares"):
 *   • 'today'    (default) → el rate actual (MEP/blue): modelo FX-neutral, costo y
 *     valor al mismo dólar → el P&L USD refleja solo el rendimiento del activo.
 *   • 'purchase' → el tc_compra del lote (los dólares que realmente puso): incluye
 *     la devaluación. Fallback al rate de hoy si el lote no tiene tc_compra (>0) →
 *     nunca divide por cero ni colapsa el lote. SOLO afecta el COSTO, nunca el valor.
 */
export function costBasisRate(p, currentRate, costBasis = 'purchase') {
  // El default del PARÁMETRO acompaña al del contexto. Cuando eran distintos
  // ('today' acá, contexto aparte) cualquier caller que se olvidara de pasar
  // `costBasis` volvía al dólar de hoy en silencio — el mismo bug que reportó el
  // usuario de ALUA, pero sin nada en pantalla que lo delatara.
  return (costBasis === 'purchase' && p?.tc_compra > 0) ? p.tc_compra : currentRate
}

/**
 * lotMissingPurchaseRate — en modo 'purchase', ¿este lote NO tiene tc_compra
 * registrado y por eso cae silenciosamente al dólar de hoy? (compras previas al
 * fix del importador, o lotes cripto/USD donde no se estampa). Sirve para marcar
 * la celda con un badge "TC?" y no dar a entender que ya refleja la devaluación.
 *
 * Solo aplica a lotes cuyo COSTO efectivamente se rutea por costBasisRate (los de
 * costo USD/cripto no usan tc_compra → el badge mentiría). El costo está en pesos
 * cuando: costInPesos (lote ARS en cualquier broker) O es un lote nativo de un
 * broker ARS que no es de costo USD (isArsBroker && !costInUsd). Por eso hace falta
 * el contexto del broker: un lote de moneda sin marcar en un broker USD NO se rutea.
 * Solo en modo 'purchase'; en 'today' siempre es false.
 */
export function lotMissingPurchaseRate(p, costBasis = 'today', isArsBroker = false) {
  if (costBasis !== 'purchase') return false
  if (p?.is_cash) return false
  if (isCrypto(p?.asset)) return false
  const costIsPesos = costInPesos(p) || (isArsBroker && !costInUsd(p))
  if (!costIsPesos) return false
  return !(p?.tc_compra > 0)
}

export function pesoLotUsd(p, prices, tcCedear, costBasis = 'today') {
  const investedUsd = ((p.invested || 0) + (p.commissions || 0)) / costBasisRate(p, tcCedear, costBasis)
  const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true, p.asset_type)]
  // el VALOR siempre va a HOY (tcCedear) en ambos modos — no aplicar costBasisRate acá
  const valueUsd = priceArs != null ? (priceArs * (p.quantity || 0)) / tcCedear : investedUsd
  return { investedUsd, valueUsd, priceUsd: priceArs != null ? priceArs / tcCedear : null }
}

/** isFciSym — ¿es un símbolo de FCI del catálogo ('FCI:<slug>')? Su precio es el
 *  valor de cuotaparte (NAV) en su moneda nativa, NO un .BA en pesos. */
export function isFciSym(asset) {
  return (asset || '').startsWith('FCI:')
}

/**
 * costInUsd — ¿el COSTO de este lote está en DÓLARES? Espejo de costInPesos.
 *
 * La moneda del costo la decide el LOTE (positions.currency), no la cuenta. Un
 * bono/ON/FCI-USD o un CEDEAR comprado en dólar-MEP queda currency='USD' aunque
 * viva en un broker ARS (Balanz importa cada pata en su moneda). Su costo YA está
 * en USD → NO se divide por el MEP (eso lo colapsaba ~1/MEP y el guard descartaba
 * el precio real). La cripto se excluye: se valúa al spot, no por este camino.
 */
export function costInUsd(p) {
  const c = (p?.currency || '').toUpperCase()
  return (c === 'USD' || c === 'USDT') && !isCrypto(p?.asset)
}

/**
 * usdLotValue — valuación USD de UN lote de COSTO en dólares (costInUsd true) que
 * vive en un broker ARS. Costo YA en USD (sin ÷MEP). El VALOR va por el TIPO de
 * instrumento: CEDEAR/acción-AR por su precio LOCAL .BA ÷ dólar-MEP (cedearRate);
 * bono/ON/FCI/US por su precio USD nativo (sin ÷MEP). El guard compara en unidades
 * consistentes (mktUsd vs invUsd). Sin precio confiable → valor al costo (P&L 0).
 * Helper compartido para que TODOS los consumidores conviertan igual (espejo de
 * pesoLotUsd). Usar solo cuando costInUsd(p) es true.
 */
export function usdLotValue(p, prices, cedearRate) {
  const investedUsd = (p.invested || 0) + (p.commissions || 0)   // costo YA en USD
  const sym = priceSymbol(p.asset, true, p.asset_type)
  const priceIsArs = sym.endsWith('.BA')                         // .BA = ARS ; FCI:/US = USD
  const price = p.price_override ?? prices[sym]
  const raw = price != null ? price * (p.quantity || 0) : null
  const mktUsd = raw != null ? (priceIsArs ? raw / cedearRate : raw) : null
  const trust = mktUsd != null &&
    trustMktValue(mktUsd, investedUsd, p.asset_type, p.price_override != null)
  return {
    investedUsd,
    valueUsd: trust ? mktUsd : investedUsd,
    priceUsd: price != null ? (priceIsArs ? price / cedearRate : price) : null,
  }
}

/**
 * valueEquityLot — valuación USD de UN lote de EQUITY o CEDEAR (no cripto, no cash).
 * Espeja las patas no-cripto de valueLot (pages/AssetDetail) para que la lista
 * holding-first de "Calidad de cartera" valúe IGUAL que la ficha del activo.
 * Usar solo con posiciones equity/CEDEAR (la cripto/cash van por otra matriz).
 */
export function valueEquityLot(p, broker, prices, tcBlue, cedearRate = tcBlue, costBasis = 'today') {
  const qty = p.quantity || 0
  const invested = p.invested || 0
  const isAR = broker?.currency === 'ARS'
  // investedUsd = costo DISPLAY (puede ir al tc_compra en modo 'purchase').
  // guardCost   = costo SIEMPRE a hoy (mode-independent): es el denominador del
  //   guard anti-distorsión y la base del fallback sin precio. Espeja a
  //   computeBrokerValue, que guardea contra el costo nativo (nunca el ruteado):
  //   si el guard usara el investedUsd inflado por tc_compra, un precio basura
  //   (bono per-100 ×100) que a hoy se rechaza podría colarse en modo 'purchase'.
  //   En modo 'today' guardCost === investedUsd → byte-idéntico.
  let valueUsd, investedUsd, guardCost
  if (costInPesos(p) && !isAR) {
    const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true, p.asset_type)]
    investedUsd = invested / costBasisRate(p, cedearRate, costBasis)
    guardCost = invested / cedearRate
    valueUsd = priceArs != null ? (priceArs / cedearRate) * qty : investedUsd
  } else if (costInUsd(p) && isAR) {
    // Espejo: lote de costo USD en un broker ARS (bono/ON/FCI-USD, CEDEAR-MEP) →
    // costo YA en USD (sin ÷MEP), valor por tipo (usdLotValue). Sin esto, la rama
    // isAR de abajo dividía el costo USD por el blue → la fila colapsaba a ~0.
    // El costo ya está en USD reales → el modo no lo toca (guardCost = investedUsd).
    const u = usdLotValue(p, prices, cedearRate)
    investedUsd = u.investedUsd
    guardCost = u.investedUsd
    valueUsd = u.valueUsd
  } else if (isAR) {
    const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true)]
    investedUsd = invested / costBasisRate(p, tcBlue, costBasis)
    guardCost = invested / tcBlue
    valueUsd = priceArs != null ? (priceArs * qty) / tcBlue : investedUsd
  } else if ((p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker)) && !isFciSym(p.asset) && p.price_override == null) {
    // .BA÷MEP decidido por el PADRE (isArUsdBroker/currency), NO por isArStock: una
    // acción AR en un broker USD extranjero real (Schwab) es su ADR NYSE en USD, no
    // el .BA local. Espeja _byma del backend. (isAR/costInPesos cubren el caso AR.)
    const priceArs = prices[priceSymbol(p.asset, true, p.asset_type)]
    investedUsd = invested   // costo ya en USD (broker USD) → el modo no aplica
    guardCost = invested
    valueUsd = priceArs != null ? (priceArs / cedearRate) * qty : invested
  } else {
    const priceUsd = p.price_override ?? prices[priceSymbol(p.asset, false, p.asset_type)]
    investedUsd = invested
    guardCost = invested
    valueUsd = priceUsd != null ? priceUsd * qty : invested
  }
  if (!trustMktValue(valueUsd, guardCost, p.asset_type, p.price_override != null)) {
    valueUsd = investedUsd
  }
  return { valueUsd, investedUsd, pnlUsd: valueUsd - investedUsd }
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

/**
 * valuationPriceKey — la key de `prices` con la que la VALUACIÓN va a leer esta
 * posición. Espejo EXACTO de computeBrokerValue:
 *   · broker ARS → priceSymbol(asset, true) (.BA / FCI: as-is) — holdings L384
 *     y usdLotValue leen la misma key.
 *   · broker USD: cripto → key spot (prices[asset], NUNCA .BA — la valuación la
 *     excluye de la rama BYMA); costInPesos o sub-broker AR '· USD' → .BA;
 *     resto → ticker US (el CEDEAR resuelve .BA vía assetType en priceSymbol).
 * Usarla para PEDIR los símbolos (/prices, /prices/prev-close) y para chequear
 * cobertura: si el fetch pide una key distinta de la que la valuación lee, la
 * posición cae a costo EN SILENCIO (P&L 0, Var. día "—") — es la causa raíz de
 * "el mismo lote vale distinto en mobile que en desktop".
 */
export function valuationPriceKey(p, isArsBroker) {
  if (p.is_cash) return null
  if (isArsBroker) return priceSymbol(p.asset, true, p.asset_type)
  if (isCrypto(p.asset)) return priceSymbol(p.asset, false, p.asset_type)
  if (isArUsdBroker(p.broker) || costInPesos(p)) return priceSymbol(p.asset, true, p.asset_type)
  return priceSymbol(p.asset, false, p.asset_type)
}

/**
 * buildPriceSymbols — lista canónica de símbolos a pedir a /prices para valuar
 * `positions`. ÚNICA fuente para armar el fetch: cada pantalla que lo
 * re-implementaba tenía un agujero distinto (Dashboard pedía tickers crudos →
 * CEDEARs en cuenta USD a costo; PositionsMobile no pedía .BA para costInPesos;
 * Home/Positions pedían BTC.BA para cripto en '· USD' que la valuación lee spot).
 */
export function buildPriceSymbols(positions, brokers) {
  const arsBrokers = new Set((brokers || []).filter(b => b.currency === 'ARS').map(b => b.name))
  const known = new Set((brokers || []).map(b => b.name))
  const syms = new Set()
  for (const p of positions || []) {
    if (p.is_cash || p.asset === 'USDT' || !known.has(p.broker)) continue
    const k = valuationPriceKey(p, arsBrokers.has(p.broker))
    if (k) syms.add(k)
  }
  return [...syms]
}

/**
 * valuePositionLot — LA valuación de UN lote. Función pura.
 *
 * Es el cuerpo del loop de `computeBrokerValue` extraído tal cual: mismas seis
 * ramas, mismo orden, misma aritmética. `computeBrokerValue` pasó a ser su suma
 * y nada más.
 *
 * POR QUÉ EXISTE: había CINCO implementaciones de la valuación por lote
 * (computeBrokerValue, valueEquityLot, AssetDetail.valueLot,
 * PositionDetailMobile y PositionsMobile) y ninguna era "la buena a la que
 * volver" — el desktop tampoco usa el motor canónico para sus filas, sólo para
 * tres totales. Esta es la que va a serlo. Todavía NO la consume nadie más:
 * migrar a los cinco lectores sólo es delta 0 después de alinear los
 * comportamientos que hoy difieren (comisiones, modo 'purchase').
 *
 * EL ORDEN DE LAS RAMAS IMPORTA y es el de siempre:
 *   1. cash                       (las ramas 2 y 3 lo excluyen con !p.is_cash)
 *   2. costInPesos(p) && !isAR    — lote en pesos alojado en cuenta USD
 *   3. costInUsd(p) && isAR       — lote de costo USD alojado en broker ARS
 *   4. isAR nativo                — CEDEAR/acción AR/bono en broker ARS
 *   5. (CEDEAR || arUsd) en broker USD, sin cripto/FCI/override → .BA ÷ MEP
 *   6. else                       — USD nativo (+ factor cripto)
 *
 * @param {object} p   posición (un lote)
 * @param {object} ctx { broker, prices, tcBlue, tcCedear, tcCripto, costBasis }
 * @returns {{
 *   valueUsd: number, investedUsd: number, investedUsdDisplay: number,
 *   guardCost: number|null, priceLocal: number|null, priceTrusted: boolean|null,
 *   pnlUsd: number, pnlPct: number|null, valueArs: number, invArs: number
 * }}
 *
 * SOBRE TRES CAMPOS QUE LOS LECTORES SE ARMAN A MANO Y NOMBRAN DISTINTO:
 *   · `guardCost` es el `realCost` EXACTO que este lote le pasa a
 *     `trustMktValue`, en la moneda en la que esa rama compara (PESOS en las
 *     ramas AR, USD en las demás). No es "el costo en dólares": mezclar las dos
 *     cosas es lo que hacía que el guard comparara USD contra pesos.
 *   · `investedUsdDisplay` es el costo en USD al rate del MODO (tc_compra en
 *     'purchase'). Acá coincide siempre con `investedUsd` — se expone con su
 *     nombre porque en AssetDetail:49-50 y PositionDetailMobile:141 ese número
 *     y el del guard son dos variables distintas, y confundirlos afloja el
 *     filtro anti-distorsión en modo 'purchase'.
 *   · `priceLocal` es el precio por unidad TAL CUAL SALE de `prices`: en la
 *     moneda del símbolo con el que se lo leyó (.BA → ARS; ticker US y FCI: →
 *     USD). Ojo: AssetDetail y PositionDetailMobile llaman `priceLocal` a ese
 *     número YA dividido por el MEP en algunas ramas. Acá no se convierte nada.
 *   `priceTrusted` es null cuando no hubo precio que juzgar (cash, o sin dato).
 */
export function valuePositionLot(p, ctx = {}) {
  const { broker, prices = {}, tcBlue, tcCedear, tcCripto = null, costBasis = 'today' } = ctx
  const cedearRate = tcCedear ?? tcBlue
  const isAR = broker?.currency === 'ARS'
  const arUsd = isArUsdBroker(broker?.name)

  // Cost basis económica = lo que pagaste por el activo + comisiones de compra.
  // Las comisiones SÍ son costo real — afectan el cap inicial y el P&L.
  // Para cash o legacy data sin commissions, p.commissions es 0 o null.
  const comm = p.commissions || 0
  const realCost = (p.invested || 0) + comm

  const salida = (o) => ({
    valueUsd: o.valueUsd,
    investedUsd: o.investedUsd,
    investedUsdDisplay: o.investedUsdDisplay ?? o.investedUsd,
    guardCost: o.guardCost ?? null,
    priceLocal: o.priceLocal ?? null,
    priceTrusted: o.priceTrusted ?? null,
    valueArs: o.valueArs,
    invArs: o.invArs,
    pnlUsd: o.valueUsd - o.investedUsd,
    pnlPct: o.investedUsd > 0 ? (o.valueUsd - o.investedUsd) / o.investedUsd : null,
  })

  // ── 2. Lote en PESOS (currency='ARS') alojado en una cuenta USD (CEDEAR/acción
  // AR cargado en dólares o mal ruteado): se valúa estilo-ARS — costo Y valor a
  // USD por el dólar-MEP (cedearRate), igual que en un broker AR. Sin esto el
  // costo en pesos se contaba como dólares (invertido inflado ~MEP×) y el guard
  // de confianza comparaba USD vs pesos (rechazaba el precio e inflaba el valor).
  if (!p.is_cash && !isAR && costInPesos(p)) {
    const invUsd = realCost / costBasisRate(p, cedearRate, costBasis)
    const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true, p.asset_type)]
    const mktArs = priceArs != null ? priceArs * (p.quantity || 0) : null
    const trustArs = mktArs != null &&
      trustMktValue(mktArs, realCost, p.asset_type, p.price_override != null)
    return salida({
      investedUsd: invUsd,
      invArs: realCost,
      valueUsd: trustArs ? mktArs / cedearRate : invUsd,
      valueArs: trustArs ? mktArs : realCost,
      guardCost: realCost,
      priceLocal: priceArs ?? null,
      priceTrusted: mktArs != null ? trustArs : null,
    })
  }

  // ── 3. Espejo del anterior: lote de COSTO EN DÓLARES (bono/ON/FCI-USD, o CEDEAR
  // comprado en dólar-MEP → currency='USD') alojado en un broker ARS (Balanz).
  // El costo YA está en USD → NO se divide por el MEP; el valor va por el tipo de
  // instrumento (usdLotValue: CEDEAR/acción-AR por .BA÷MEP, resto por precio USD).
  // Sin esto, el path ARS dividía el costo USD por el MEP y el guard descartaba el
  // precio real → la tenencia dólar colapsaba (~1/MEP). El equivalente en pesos
  // (×cedearRate) alimenta el total ARS para que el invariante siga cerrando.
  if (!p.is_cash && isAR && costInUsd(p)) {
    const { investedUsd, valueUsd } = usdLotValue(p, prices, cedearRate)
    // Metadata del guard: espeja lo que usdLotValue decide adentro. Los NÚMEROS
    // salen de usdLotValue, no de acá — esto sólo reproduce la decisión.
    const sym = priceSymbol(p.asset, true, p.asset_type)
    const rawPrice = p.price_override ?? prices[sym]
    const mktUsd = rawPrice != null
      ? (sym.endsWith('.BA') ? (rawPrice * (p.quantity || 0)) / cedearRate : rawPrice * (p.quantity || 0))
      : null
    return salida({
      investedUsd,
      valueUsd,
      invArs: investedUsd * cedearRate,
      valueArs: valueUsd * cedearRate,
      guardCost: investedUsd,
      priceLocal: rawPrice ?? null,
      priceTrusted: mktUsd != null
        ? trustMktValue(mktUsd, investedUsd, p.asset_type, p.price_override != null)
        : null,
    })
  }

  if (isAR) {
    // invArs = costo en pesos (moneda base del broker). Se computa para cash y
    // no-cash por igual, como en el original.
    if (p.is_cash) {
      // ── 1. Cash en broker ARS.
      // Unificación FX (espeja el backend behavioral._position_value_usd): el
      // cash en pesos → USD por el dólar-MEP (cedearRate), IGUAL que las
      // tenencias. Es el dólar al que dolarizás la plata quieta EN el broker
      // (comprás un bono, salís en USD), no el blue de la calle. Antes iba al
      // blue y quedaba inconsistente con los holdings y con el backend.
      const cashArs = p.invested || 0  // cash no tiene commissions
      const cashUsd = cashArs / cedearRate
      return salida({
        investedUsd: cashUsd,  // cash en pesos: invested USD = value USD (no FX gain)
        valueUsd: cashUsd,
        invArs: realCost,
        valueArs: cashArs,
      })
    }
    // ── 4. Holdings (CEDEARs / acciones AR / bonos) → a USD por el dólar-MEP
    // (cedearRate), que es el dólar al que REALMENTE salís de la inversión y
    // el que muestra el broker. Cash y holdings usan el MISMO rate (MEP).
    // Antes valuábamos acá al blue y el total quedaba ~2% por debajo del broker.
    // FX-phantom fix: invested y value usan el MISMO rate (MEP), así se mueven
    // juntos y solo aparece P&L cuando el activo realmente rinde. En modo
    // 'purchase' el COSTO va al tc_compra del lote (dólares reales invertidos);
    // el valor sigue a cedearRate → el P&L absorbe la devaluación.
    const invUsd = realCost / costBasisRate(p, cedearRate, costBasis)
    // Sin asset_type a propósito: con isARS=true `priceSymbol` ignora el tipo
    // (FCI: sale as-is y todo lo demás recibe .BA), así que la key es la MISMA
    // que pide el fetch. Verificado leyendo priceSymbol rama por rama.
    const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true)]
    const mktArs = priceArs != null ? priceArs * (p.quantity || 0) : null
    const trustArs = mktArs != null &&
      trustMktValue(mktArs, realCost, p.asset_type, p.price_override != null)
    return salida({
      investedUsd: invUsd,
      invArs: realCost,
      // Sin precio confiable — mostramos costo; P&L 0 para esta posición.
      valueUsd: trustArs ? mktArs / cedearRate : invUsd,
      valueArs: trustArs ? mktArs : realCost,
      guardCost: realCost,
      priceLocal: priceArs ?? null,
      priceTrusted: mktArs != null ? trustArs : null,
    })
  }

  // ── Broker USD. invArs/valueArs quedan en 0: el total en pesos de un broker
  // USD no se acumula (es el comportamiento de siempre).
  if (p.is_cash) {
    // ── 1. Cash en broker USD.
    const v = p.invested || 0
    return salida({ investedUsd: v, valueUsd: v, invArs: 0, valueArs: 0 })
  }

  // Premium dólar-cripto: la cripto de un BROKER (no exchange) se valúa al
  // dólar MEP que muestra el broker. Factor a COSTO Y valor → P&L% invariante.
  // 1 para CEDEAR/acciones/exchange/override/sin-rate.
  const f = cryptoBrokerFactor(p.asset, broker?.is_exchange, p.price_override != null, tcCripto, cedearRate)
  const investedUsd = realCost * f

  if ((p.asset_type === 'CEDEAR' || arUsd) && !isCrypto(p.asset) && !isFciSym(p.asset) && p.price_override == null) {
    // ── 5. Instrumento de BYMA en broker USD: CEDEAR, o cualquier cosa en un
    // sub-broker AR "· USD" (acciones argentinas como PAMP/YPFD incluidas,
    // que NO tienen acción US). Se valúa por su precio LOCAL .BA (ARS) ÷ MEP
    // (cedearRate = dólar-MEP), que es lo que muestra el broker. NO por el
    // ticker US. La cripto NUNCA entra acá (no es .BA) → va a la rama spot.
    // La decisión la toma el PADRE (arUsd/CEDEAR), NO isArStock: una acción AR
    // en un broker USD extranjero real (Schwab, no arUsd) es su ADR NYSE en USD
    // (GGAL/BMA), no el .BA local. Espeja _byma del backend (byma_broker_names).
    // El FCI-USD tampoco: su precio es el NAV en USD (va al else, sin ÷MEP);
    // sin excluirlo, un FCI ruteado a "· USD" se dividía por el MEP → al costo.
    const priceArs = prices[priceSymbol(p.asset, true, p.asset_type)]
    const mktUsd = priceArs != null ? (priceArs * (p.quantity || 0)) / cedearRate : null
    const trust = mktUsd != null && trustMktValue(mktUsd, realCost, p.asset_type)
    // Sin `* f` a propósito: esta rama excluye la cripto, así que f siempre es 1.
    return salida({
      investedUsd,
      valueUsd: trust ? mktUsd : realCost,
      invArs: 0,
      valueArs: 0,
      guardCost: realCost,
      priceLocal: priceArs ?? null,
      priceTrusted: mktUsd != null ? trust : null,
    })
  }

  // ── 6. USD nativo. Key normalizada primero (BRK.B/BRK B → 'BRK-B', la key que
  // el fetch pide y el backend devuelve), fallback a la cruda (last-known del
  // cron y payloads legacy). Sin esto, un class-share con punto se fetcheaba
  // como 'BRK-B' pero se leía 'BRK.B' → caía a costo con el precio en memoria.
  // Un CEDEAR solo llega acá CON override (la rama .BA lo captura antes) → la
  // cadena corta en el override y el .BA de priceSymbol no se lee.
  const price = p.price_override ?? prices[priceSymbol(p.asset, false, p.asset_type)] ?? prices[p.asset]
  const mkt = price != null ? price * (p.quantity || 0) : null
  const trust = mkt != null &&
    trustMktValue(mkt, realCost, p.asset_type, p.price_override != null)
  // Sin precio confiable — mostramos costo; P&L 0 para esta posición.
  // El factor cripto (1 para todo lo no-cripto-de-broker) escala valor.
  return salida({
    investedUsd,
    valueUsd: (trust ? mkt : realCost) * f,
    invArs: 0,
    valueArs: 0,
    guardCost: realCost,
    priceLocal: price ?? null,
    priceTrusted: mkt != null ? trust : null,
  })
}

/**
 * computeBrokerValue — la SUMA de valuePositionLot sobre los lotes del broker.
 * Toda la lógica por lote vive en valuePositionLot; acá no queda ninguna rama.
 */
export function computeBrokerValue(allPositions, prices, broker, tcBlue, cedearRate = tcBlue, tcCripto = null, costBasis = 'today') {
  const bpos = allPositions.filter(p => p.broker === broker.name)
  const ctx = { broker, prices, tcBlue, tcCedear: cedearRate, tcCripto, costBasis }
  let value = 0, invested = 0
  let valueArs = 0, invArs = 0

  for (const p of bpos) {
    const r = valuePositionLot(p, ctx)
    value    += r.valueUsd
    invested += r.investedUsd
    valueArs += r.valueArs
    invArs   += r.invArs
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

/**
 * avgCostUsdPerUnit — costo promedio POR UNIDAD en USD, ruteado por el modo
 * "Costo en dólares" ('today' | 'purchase').
 *
 * Es la columna "Precio prom." de Cartera cuando la vista está en dólares.
 * ANTES esa celda hacía `invested / quantity / dólarDeHoy`: ignoraba el
 * `tc_compra` del lote Y el toggle (devolvía el mismo número en los dos modos).
 * Reporte real de un usuario: cargó su compra con TC 1448,6 y veía USD 14,23
 * (= costo ÷ dólar de hoy 1523) en vez de 14,96.
 *
 * Reglas:
 *  · Multi-lote (`p._lots`): suma POR LOTE, cada uno a SU tc_compra, y divide por
 *    la cantidad total → promedio ponderado e INDEPENDIENTE del orden. Nunca usar
 *    el `tc_compra` del agregado: es el del PRIMER lote.
 *  · Un lote cuyo costo YA está en dólares no se divide (CEDEAR comprado a MEP o
 *    bono/FCI USD dentro de un broker ARS) — dividirlo lo colapsaba ~1500×.
 *  · SIN comisiones, igual que la columna en pesos, para que ambas vistas midan
 *    lo mismo. En modo 'today' el resultado es idéntico al cálculo previo.
 *
 * @param p            posición o agregado (con `_lots` si es multi-lote)
 * @param rate         dólar de hoy del riel que corresponda (MEP/blue)
 * @param costBasis    'today' | 'purchase'
 * @param isArsBroker  ¿la posición vive en un broker en pesos?
 * @returns number|null — null si es cash, no hay cantidad o no hay costo.
 */
export function avgCostUsdPerUnit(p, rate, costBasis = 'today', isArsBroker = false) {
  const qty = p?.quantity || 0
  if (!p || p.is_cash || qty <= 0) return null
  const lots = (p._lots && p._lots.length) ? p._lots : [p]
  let cost = 0
  for (const l of lots) {
    const inv = l?.invested || 0
    if (!inv) continue
    // Mismo criterio de "el costo está en pesos" que lotMissingPurchaseRate.
    const costIsPesos = isArsBroker ? !costInUsd(l) : costInPesos(l)
    cost += costIsPesos ? inv / costBasisRate(l, rate, costBasis) : inv
  }
  return cost > 0 ? cost / qty : null
}
