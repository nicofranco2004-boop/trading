// useFichaDelActivo — los datos y las cuentas de la ficha de un activo, en UN
// lugar: tus lotes y operaciones de ese activo, lo que valen (la matriz de
// valuación por lote), qué parte de tu plata es y lo que le llega al gráfico
// técnico (LecturaTecnica). Lo usan la ficha (/activo/:ticker, AssetDetail.jsx)
// y la pestaña «Gráfico» de Análisis técnico (GraficoTecnico.jsx): el gráfico
// de la pestaña tiene que mostrar tu precio, tus compras y «Desde que lo tenés»
// con la MISMA cuenta que la ficha, no con una copia (Nico, 30/10).
// ════════════════════════════════════════════════════════════════════════════
// Salió de AssetDetail.jsx sin cambiar una cuenta: la prueba
// pages/AssetDetail.antesYDespues.test.jsx compara lo que la ficha le pasa al
// gráfico y todo su texto con fotos sacadas ANTES de mudarlo.
//
// Si lo pedís con otro nombre y lo tenés (GGAL.BA y tu lote se llama GGAL), no
// carga: devuelve `otroNombre` y cada pantalla decide (la ficha cambia de
// dirección; la pestaña cambia de activo).

import { useEffect, useMemo, useState } from 'react'
import { api } from '../utils/api'
import { isBymaHolding, lotMissingPurchaseRate, priceSymbol, isArUsdBroker, costInPesos, costInUsd, cryptoCostInUsd, cryptoUsdLotValue, usdLotValue, isFciSym, trustMktValue, costBasisRate, setBrokersRegistry, valuationPriceKey } from '../utils/valuation'
import { isCrypto, cryptoBrokerFactor } from '../utils/crypto'
import { miradaSinTenencia, mismoPapel } from '../utils/buscadorRapido'
import { esAccionLocal } from '../utils/accionLocal'
import { useUltimoPedido } from './useUltimoPedido'
import { useCurrency, pickFinancialRate } from '../contexts/CurrencyContext'
import { operacionesEnUsd } from '../utils/assetPnl'

// ─── Matriz de valuación por lote (reusa la lógica de PositionDetailMobile) ──
// Costo económico del lote, en SU moneda = lo pagado + las comisiones de compra.
// Es la definición de la casa: la usan computeBrokerValue (valuation.js:486), las
// filas del desktop, usdLotValue, pesoLotUsd y el backend (persister.py:747).
// El CASH no lleva comisión y por eso sigue con `invested`. Lo usan `valueLot` y
// el costo en pesos de la lectura técnica: una sola cuenta para los dos.
function costoDelLote(p) {
  return (p.invested || 0) + (p.commissions || 0)
}

// Devuelve { valueUsd, investedUsd, pnlUsd, priceLocal } para UN lote.
function valueLot(p, { brokers, prices, tcValuacion, tcCedear, tcCripto, costBasis = 'today' }) {
  const broker = brokers.find(b => b.name === p.broker)
  const isAR = broker?.currency === 'ARS'
  const qty = p.quantity || 0
  const cashInvested = p.invested || 0
  if (p.is_cash) {
    const v = isAR ? cashInvested / tcValuacion : cashInvested
    return { valueUsd: v, investedUsd: v, pnlUsd: 0, priceLocal: null }
  }
  const invested = costoDelLote(p)
  // Lote en PESOS (currency='ARS') en una cuenta USD → estilo-ARS por el MEP
  // (tcCedear): costo Y valor a USD por el mismo rate, no el costo en pesos como dólares.
  if (costInPesos(p) && !isAR) {
    const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true, p.asset_type)]
    // Costo DISPLAY (modo 'purchase' → tc_compra); guardCost = costo a hoy, denominador
    // del guard (mode-independent, así 'purchase' no afloja el filtro anti-distorsión).
    const investedUsd = invested / costBasisRate(p, tcCedear, costBasis)
    const guardCost = invested / tcCedear
    const priceLocal = priceArs != null ? priceArs / tcCedear : null
    const mkt = priceLocal != null ? priceLocal * qty : investedUsd
    const valueUsd = trustMktValue(mkt, guardCost, p.asset_type, p.price_override != null) ? mkt : investedUsd
    return { valueUsd, investedUsd, pnlUsd: valueUsd - investedUsd, priceLocal }
  }
  // Espejo de costInPesos: lote de COSTO EN DÓLARES (bono/ON/FCI-USD, o CEDEAR
  // comprado en dólar-MEP → currency='USD') que vive en un broker ARS (Balanz).
  // El costo YA está en USD (sin ÷MEP); el valor va por el tipo de instrumento
  // (usdLotValue). Sin esto, la rama isAR de abajo dividía el costo USD por el
  // blue → la ficha del activo colapsaba (~1/MEP).
  if (costInUsd(p) && isAR) {
    const { investedUsd, valueUsd, priceUsd } = usdLotValue(p, prices, tcCedear)
    return { valueUsd, investedUsd, pnlUsd: valueUsd - investedUsd, priceLocal: priceUsd }
  }
  // Lo mismo para la CRIPTO comprada en dólares (costInUsd la excluye): sin esto
  // caía en la rama isAR de abajo y la ficha mostraba el costo ÷ dólar (~0).
  if (cryptoCostInUsd(p) && isAR) {
    const { investedUsd, valueUsd, priceUsd } = cryptoUsdLotValue(p, prices, { cedearRate: tcCedear, tcCripto, isExchange: !!broker?.is_exchange })
    return { valueUsd, investedUsd, pnlUsd: valueUsd - investedUsd, priceLocal: priceUsd }
  }
  if (isAR) {
    const priceLocal = p.price_override ?? prices[priceSymbol(p.asset, true)]
    const investedUsd = invested / costBasisRate(p, tcValuacion, costBasis)   // display (modo)
    const guardCost = invested / tcValuacion                                  // hoy (guard)
    const mkt = priceLocal != null ? (priceLocal * qty) / tcValuacion : investedUsd
    const valueUsd = trustMktValue(mkt, guardCost, p.asset_type, p.price_override != null) ? mkt : investedUsd
    return { valueUsd, investedUsd, pnlUsd: valueUsd - investedUsd, priceLocal }
  }
  if ((p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker)) && !isFciSym(p.asset) && p.price_override == null && !isCrypto(p.asset)) {
    const priceArs = prices[priceSymbol(p.asset, true, p.asset_type)]
    const priceLocal = priceArs != null ? priceArs / tcCedear : null
    const mkt = priceLocal != null ? priceLocal * qty : invested
    const valueUsd = trustMktValue(mkt, invested, p.asset_type, p.price_override != null) ? mkt : invested
    return { valueUsd, investedUsd: invested, pnlUsd: valueUsd - invested, priceLocal }
  }
  // Cripto en broker AR (no exchange) se valúa al dólar MEP; en exchange queda a spot.
  // El factor multiplica valor Y costo por igual → el P&L% no cambia.
  const f = cryptoBrokerFactor(p.asset, !!broker?.is_exchange, p.price_override != null, tcCripto, tcCedear, broker?.currency)
  // Misma key que pide symbolFor. Antes leía prices[p.asset] CRUDO: un
  // class-share (BRK.B se pide como 'BRK-B') nunca matcheaba y el lote quedaba
  // congelado al costo con P&L 0. El fallback a la cruda cubre el last-known
  // del cron y los payloads legacy, igual que el motor canónico.
  const priceLocal = p.price_override ?? prices[valuationPriceKey(p, isAR)] ?? prices[p.asset]
  const investedUsd = invested * f
  const mkt = (priceLocal != null ? priceLocal * qty : invested) * f
  const valueUsd = trustMktValue(mkt, investedUsd, p.asset_type, p.price_override != null) ? mkt : investedUsd
  return { valueUsd, investedUsd, pnlUsd: valueUsd - investedUsd, priceLocal }
}

// Lo que pagaste en PESOS por tus lotes abiertos ({ invertido, cantidad }), para
// la lectura técnica en pesos. Sólo si TODO lo compraste en pesos: un lote
// pagado en dólares no tiene un costo en pesos que sea verdad.
function costoEnPesos(lots) {
  const abiertos = lots.filter(p => !p.is_cash && Number(p.quantity) > 0)
  if (!abiertos.length || !abiertos.every(costInPesos)) return null
  return {
    invertido: abiertos.reduce((s, p) => s + costoDelLote(p), 0),
    cantidad: abiertos.reduce((s, p) => s + Number(p.quantity), 0),
  }
}

// Símbolo de precio que necesita un lote (para fetchear el set correcto).
// Delega en `valuationPriceKey`, que es LA key con la que la valuación lee — su
// docstring existe justamente para este bug. La versión anterior le faltaba la
// excepción de la cripto: en un sub-broker "· USD" pedía BTC.BA mientras la
// valuación lee el spot (prices[BTC]) → el lote caía a costo.
function symbolFor(p, brokers) {
  const isAR = brokers.find(b => b.name === p.broker)?.currency === 'ARS'
  return valuationPriceKey(p, isAR)
}

// Un FCI no tiene serie de precios: se valúa por el NAV del día. Sirve para no
// pedir un gráfico que la API no puede devolver.
const esFci = (sym) => String(sym || '').toUpperCase().startsWith('FCI:')

// ¿Este lote u operación tuyo es el activo que pediste con otro nombre? El
// mapa del Merval y el buscador mandan GGAL.BA y tu lote se llama GGAL; el del
// S&P manda BRK-B y lo tenés como BRK.B o como el CEDEAR BRKB. Pedido con
// ".BA" (BYMA), sólo cuenta lo que tenés en BYMA: tu ADR de GGAL en Schwab, o
// Adecoagro (AGRO) cuando pediste Agrometal (AGRO.BA), son otra cosa.
function esElMismo(pedido, x) {
  if (!x || x.is_cash || mismoPapel(x.asset) !== mismoPapel(pedido)) return false
  return !pedido.endsWith('.BA') || isBymaHolding(x)
}

export function useFichaDelActivo(asset) {
  const { valuationDollar, costBasis } = useCurrency()

  const [positions, setPositions] = useState([])
  const [brokers, setBrokers] = useState([])
  const [prices, setPrices] = useState({})
  const [dolar, setDolar] = useState(null)
  const [operations, setOperations] = useState([])
  // Qué parte de tu plata es este papel, para «Cuánto se mueve»: la cuenta del
  // servidor (senales_semana.peso), la misma de Tu lista y de Señales.
  const [pesoEnCartera, setPesoEnCartera] = useState(null)
  const [loading, setLoading] = useState(true)
  // Sólo si no lo tenés: el último precio, el cierre anterior y si está en tu watchlist.
  const [cotizacion, setCotizacion] = useState(null)
  // Sólo la última carga escribe: si cambiás de activo (⌘K) mientras ésta
  // carga, una respuesta vieja te mandaba a OTRA ficha o mostraba el precio y
  // la estrella del activo anterior (auditoría 22/10).
  const nuevoPedido = useUltimoPedido()
  // Lo tenés con otro nombre (ver arriba): la pantalla decide qué hacer.
  const [otroNombre, setOtroNombre] = useState(null)

  useEffect(() => { loadAll() /* eslint-disable-next-line */ }, [asset])

  async function loadAll() {
    const vigente = nuevoPedido()
    setLoading(true)
    setCotizacion(null)
    setOtroNombre(null)
    let redirige = false
    try {
      const [pos, bkrs, dol, ops, enCartera] = await Promise.all([
        api.get('/positions').catch(() => []),
        api.get('/brokers').catch(() => []),
        api.get('/dolar').catch(() => null),
        api.get('/operations').catch(() => []),
        // Qué parte de tu plata es este papel: la cuenta del servidor, la misma
        // de Tu lista y de Señales (senales_semana.peso).
        api.get(`/tecnico/${encodeURIComponent(asset)}/peso`).catch(() => null),
      ])
      if (!vigente()) return
      // Sin el registry, isArUsdBroker cae al fallback por NOMBRE y esta ficha
      // rutea el precio al ADR US en vez del .BA local (~10× en GGAL/BMA). Va
      // antes de buscar tu lote con otro nombre: esElMismo mira el mercado.
      setBrokersRegistry(bkrs || [])
      const todas = pos || []
      const misOps = operacionesEnUsd(ops)
      const myLots = todas.filter(p => (p.asset || '').toUpperCase() === asset)
      if (!myLots.length && !misOps.some(o => (o.asset || '').toUpperCase() === asset)) {
        // Llegaste por GGAL.BA y lo tenés como GGAL: a TU activo, con su
        // nombre (la ficha cambia de dirección, la pestaña cambia de activo).
        // Sigue «cargando» hasta que la pantalla pida el otro nombre.
        const mismo = [...todas, ...misOps].find(x => esElMismo(asset, x))
        if (mismo && (mismo.asset || '').toUpperCase() !== asset) {
          redirige = true
          setOtroNombre(mismo.asset)
          return
        }
      }
      setPesoEnCartera(enCartera?.peso ?? null)
      setPositions(myLots)
      setBrokers(bkrs || [])
      setDolar(dol)
      // En dólares desde el borde (un cupón en pesos guarda pesos en `pnl_usd`).
      const opsDelActivo = misOps.filter(o => (o.asset || '').toUpperCase() === asset)
      setOperations(opsDelActivo)
      // Fetchar todos los símbolos de precio que necesitan los lotes
      const syms = [...new Set(myLots.map(p => symbolFor(p, bkrs || [])).filter(Boolean))]
      if (syms.length) {
        try {
          const p = await api.get(`/prices?symbols=${syms.join(',')}`)
          if (vigente()) setPrices(p)
        } catch { /* silent */ }
      }
      if (!myLots.length && !opsDelActivo.length) {
        const { simboloPrecio } = miradaSinTenencia(asset)
        const q = encodeURIComponent(simboloPrecio)
        const [precio, previo, wl] = await Promise.all([
          api.get(`/prices?symbols=${q}`).catch(() => ({})),
          api.get(`/prices/prev-close?symbols=${q}`).catch(() => ({})),
          api.get('/watchlist').catch(() => ({ items: [] })),
        ])
        if (!vigente()) return
        setCotizacion({
          simbolo: simboloPrecio,
          precio: precio?.[simboloPrecio] ?? null,
          previo: previo?.[simboloPrecio] ?? null,
          // El que está en la lista con el MISMO instrumento que cotiza la
          // ficha (GGAL.BA, no el ADR GGAL; BTC o BTC-USD), para quitar ése.
          enWatchlist: (wl?.items || []).map(i => (i.symbol || '').toUpperCase())
            .find(s => s === simboloPrecio || s.replace(/-(USD|USDT|USDC)$/, '') === simboloPrecio) || null,
        })
      }
    } finally {
      if (!redirige && vigente()) setLoading(false)
    }
  }

  const tcValuacion = pickFinancialRate(dolar, valuationDollar) || 1415
  const tcCedear = pickFinancialRate(dolar, valuationDollar) || tcValuacion
  const tcCripto = dolar?.cripto?.venta

  // ── Agregados ──────────────────────────────────────────────────────────
  const agg = useMemo(() => {
    const openLots = positions.filter(p => !p.is_cash)
    let valueUsd = 0, investedUsd = 0, qty = 0
    const lots = openLots.map(p => {
      const v = valueLot(p, { brokers, prices, tcValuacion, tcCedear, tcCripto, costBasis })
      valueUsd += v.valueUsd; investedUsd += v.investedUsd; qty += (p.quantity || 0)
      return { ...p, ...v }
    }).sort((a, b) => (a.entry_date || '').localeCompare(b.entry_date || '')) // FIFO: viejo primero
    const pnlUsd = valueUsd - investedUsd
    const pnlPct = investedUsd > 0 ? pnlUsd / investedUsd : null
    const avgCostUsd = qty > 0 ? investedUsd / qty : null

    // Para la LÍNEA de tu precio en el gráfico técnico: siempre al dólar del
    // día de cada compra, sea cual sea la preferencia de arriba. Con "dólar de
    // hoy" el costo en pesos se divide por el dólar actual y el resultado es, en
    // el fondo, la ganancia en PESOS: dibujada en dólares, la línea quedaba ~30 %
    // abajo de donde compraste (auditoría 22/10). Si a algún lote le falta el
    // dólar de compra, no se dibuja (`lineaSinTc`) en vez de dibujarla corrida.
    let investedCompra = 0
    let lineaSinTc = false
    for (const p of openLots) {
      investedCompra += valueLot(p, { brokers, prices, tcValuacion, tcCedear, tcCripto, costBasis: 'purchase' }).investedUsd
      const enArs = brokers.find(b => b.name === p.broker)?.currency === 'ARS'
      if (lotMissingPurchaseRate(p, 'purchase', enArs)) lineaSinTc = true
    }
    const pnlPctCompra = investedCompra > 0 && !lineaSinTc ? valueUsd / investedCompra - 1 : null

    // Operaciones cerradas (tienen pnl_usd) → stats de operatoria
    const closed = operations.filter(o => o.pnl_usd != null)
    const realizedTotal = closed.reduce((s, o) => s + (o.pnl_usd || 0), 0)
    const wins = closed.filter(o => o.pnl_usd > 0).length
    const losses = closed.filter(o => o.pnl_usd < 0).length
    const winRate = (wins + losses) > 0 ? Math.round((wins / (wins + losses)) * 100) : null
    const best = closed.reduce((m, o) => (m == null || o.pnl_usd > m.pnl_usd ? o : m), null)
    const worst = closed.reduce((m, o) => (m == null || o.pnl_usd < m.pnl_usd ? o : m), null)

    return {
      lots, valueUsd, investedUsd, qty, pnlUsd, pnlPct, avgCostUsd, pnlPctCompra, lineaSinTc,
      realizedTotal, wins, losses, winRate, best, worst,
      tradesCount: closed.length,
      brokerCount: new Set(openLots.map(p => p.broker)).size,
    }
  }, [positions, operations, brokers, prices, tcValuacion, tcCedear, tcCripto, costBasis])

  // Lo tenés si tenés lotes o lo operaste (vendido entero cuenta).
  const tenes = positions.length > 0 || operations.length > 0
  // Lo que no tenés no tiene lotes que digan su mercado: decide el ticker. Si
  // lo vendiste todo, deciden tus operaciones (tienen broker): sin esto, tu
  // GGAL de IOL vendido se graficaba con el ADR de Nueva York (10 acciones).
  const libre = miradaSinTenencia(asset)
  const accionLocal = !tenes ? libre.accionLocal
    : esAccionLocal(asset, agg.lots.length ? agg.lots : operations)

  // Lo que le llega al gráfico técnico (LecturaTecnica), sin `titulo` ni `key`,
  // que pone cada pantalla. null: un fondo (FCI) no tiene serie de precios.
  const grafico = useMemo(() => {
    if (esFci(asset) || (agg.lots.length > 0 && esFci(symbolFor(agg.lots[0], brokers)))) return null
    return {
      asset,
      symbolMiniChart: agg.lots.length > 0 ? symbolFor(agg.lots[0], brokers) : tenes ? null : libre.simboloPrecio,
      lotes: positions,
      operaciones: operations,
      pnlPctUsd: agg.lots.length > 0 ? agg.pnlPct : null,
      pnlPctLinea: agg.lots.length > 0 ? agg.pnlPctCompra : null,
      lineaSinTc: agg.lineaSinTc,
      referencia: agg.lots.length > 0 ? {
        simbolo: symbolFor(agg.lots[0], brokers),
        precio: agg.lots[0].price_override ?? prices[symbolFor(agg.lots[0], brokers)] ?? null,
      } : null,
      costoPesos: costoEnPesos(agg.lots),
      accionLocal,
      // «En tu cartera» de «Cuánto se mueve»: lo que vale hoy lo tuyo (y el
      // dólar de la pantalla, para decirlo en pesos) y qué parte de tu plata es.
      tenencia: agg.lots.length > 0 && agg.valueUsd > 0 ? { valorUsd: agg.valueUsd, tc: tcValuacion } : null,
      pesoEnCartera,
    }
  }, [asset, agg, brokers, prices, positions, operations, tenes, libre.simboloPrecio, accionLocal, tcValuacion, pesoEnCartera])

  return {
    loading, otroNombre, positions, brokers, prices, operations, pesoEnCartera,
    cotizacion, setCotizacion, tcValuacion, tcCedear, tcCripto, agg, tenes, libre, accionLocal, grafico,
  }
}

// Para la ficha: ¿es un fondo (FCI)? (la liquidez de BYMA no aplica).
export { esFci }
