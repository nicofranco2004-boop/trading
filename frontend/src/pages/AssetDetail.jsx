// AssetDetail — ficha completa de un activo (/activo/:ticker).
// ═══════════════════════════════════════════════════════════════════════════
// LA ficha de un activo, lo tengas o no: la abren la Cartera, los buscadores,
// el mapa de calor, los movers, la watchlist y los eventos (urlDeActivo).
// Si NO lo tenés: el último precio y la variación del día, el análisis técnico
// (LecturaTecnica, sin tu precio ni tus compras), agregarlo a la watchlist y
// el análisis fundamental de la empresa. Antes eso era un modal aparte con un
// gráfico chico de 30 días (AssetQuickView): ahora es una sola pantalla.
//
// Drill-down pedido en el design audit (#1): al clickear un activo en la cartera
// se abre TODO sobre ese ticker, agregando lotes de todos los brokers:
//   • Hero: valor actual + P&L total (USD + %)
//   • Chart 30d
//   • Stats: P&L realizado de toda la vida, win rate, veces operado, costo prom
//   • Lotes abiertos (orden FIFO: más viejo primero = el que se vende primero)
//   • Historial de operaciones (cada trade con su P&L realizado, win/loss)
//   • Análisis fundamental de la empresa (si es acción/CEDEAR), al final
//
// Responsive: una sola página sirve desktop y mobile (max-w centrado en desktop,
// full-width en mobile). Reusa la matriz de valuación de PositionDetailMobile.

import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft, TrendingUp, TrendingDown, Calendar, Star, Check,
} from 'lucide-react'
import AssetLogo from '../components/AssetLogo'
import LecturaTecnica from '../components/asset/LecturaTecnica'
import AnalyzeView from '../components/fundamentals/AnalyzeView'
import LiquidezByma from '../components/asset/LiquidezByma'
import SeccionFicha from '../components/asset/SeccionFicha'
import Panel from '../components/Panel'
import TesisDelActivo from '../components/tesis/TesisDelActivo'
import { useTesis } from '../hooks/useDiario'
import { tesisVigente } from '../utils/diarioOperaciones'
import Segmento from '../components/asset/Segmento'
import Skeleton from '../components/Skeleton'
import { api } from '../utils/api'
import { pctSigned, colorClass, pctTxt, LOCALE } from '../utils/format'
import { isBymaHolding, lotMissingPurchaseRate, priceSymbol, fciLabel, isArUsdBroker, costInPesos, costInUsd, cryptoCostInUsd, cryptoUsdLotValue, usdLotValue, isFciSym, trustMktValue, costBasisRate, setBrokersRegistry, valuationPriceKey } from '../utils/valuation'
import { isCrypto, cryptoBrokerFactor } from '../utils/crypto'
import { empresaDeTenencias, empresaDeTicker, urlDeActivo, miradaSinTenencia, mismoPapel } from '../utils/buscadorRapido'
// ¿Es una acción argentina? Una regla (utils/accionLocal.js) para la ficha, la
// Cartera y las alertas: leen el mismo activo con la misma marca `local`.
import { esAccionLocal } from '../utils/accionLocal'
import { useUltimoPedido } from '../hooks/useUltimoPedido'
import { monedaDe } from '../components/home/Watchlist'
import { notifyWatchlistChanged } from '../utils/watchlistEvents'
import AskAIAbout from '../components/ai/AskAIAbout'
import { ChipDelActivo } from '../components/FueraDeHorario'
import { useCurrency, pickFinancialRate } from '../contexts/CurrencyContext'
import { operacionesEnUsd } from '../utils/assetPnl'
import { esCobro } from '../utils/tradeStats'

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

// «Ordenar por» (Nico, 28/10): técnico primero (el de entrada) o fundamental
// primero. Se recuerda para la próxima ficha que abras, en este navegador; si
// el almacenamiento está bloqueado (modo privado), técnico primero.
const CLAVE_ORDEN = 'rendi_ficha_orden'
function ordenGuardado() {
  try { return localStorage.getItem(CLAVE_ORDEN) === 'fundamental' ? 'fundamental' : 'tecnico' } catch { return 'tecnico' }
}
function guardarOrden(o) {
  try { localStorage.setItem(CLAVE_ORDEN, o) } catch { /* sin almacenamiento */ }
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

export default function AssetDetail() {
  const { ticker } = useParams()
  const navigate = useNavigate()
  const asset = (ticker || '').toUpperCase()
  const { valuationDollar, costBasis } = useCurrency()

  const [positions, setPositions] = useState([])
  const [brokers, setBrokers] = useState([])
  const [prices, setPrices] = useState({})
  const [dolar, setDolar] = useState(null)
  const [operations, setOperations] = useState([])
  // Tu tesis de este activo (la misma de Movimientos). Arriba de los return.
  const tesis = useTesis()
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
  const [orden, setOrden] = useState(ordenGuardado)
  // Si la empresa trajo fundamentales ({ ticker, hay }, lo avisa AnalyzeView al
  // cargar): el «Ordenar por» sólo aparece si hay un fundamental que poner arriba.
  const [fundamental, setFundamental] = useState(null)
  const alSaberSiHay = useCallback((ticker, hay) => setFundamental({ ticker, hay }), [])
  function elegirOrden(o) {
    setOrden(o)
    guardarOrden(o)
  }

  useEffect(() => { loadAll() /* eslint-disable-next-line */ }, [asset])

  async function loadAll() {
    const vigente = nuevoPedido()
    setLoading(true)
    setCotizacion(null)
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
        // Llegaste por GGAL.BA y lo tenés como GGAL: a TU ficha, con su nombre.
        const mismo = [...todas, ...misOps].find(x => esElMismo(asset, x))
        if (mismo && (mismo.asset || '').toUpperCase() !== asset) {
          redirige = true
          navigate(urlDeActivo(mismo.asset), { replace: true })
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

  // La empresa de este activo en "Análisis fundamental", con la misma regla que
  // el buscador (empresaDeTenencias): mira en qué mercado está cada lote, no
  // sólo el ticker. Sin lotes abiertos, deciden las operaciones (tienen broker).
  const tenes = positions.length > 0 || operations.length > 0
  const empresa = tenes
    ? empresaDeTenencias(positions.length ? positions : operations, brokers)
    : empresaDeTicker(asset)
  const name = fciLabel(asset)
  // Lo que no tenés no tiene lotes que digan su mercado: decide el ticker. Si
  // lo vendiste todo, deciden tus operaciones (tienen broker): sin esto, tu
  // GGAL de IOL vendido se graficaba con el ADR de Nueva York (10 acciones).
  const libre = miradaSinTenencia(asset)
  const accionLocal = !tenes ? libre.accionLocal
    : esAccionLocal(asset, agg.lots.length ? agg.lots : operations)
  // El papel en BYMA, para la liquidez: un CEDEAR o una acción argentina. Si lo
  // tenés, lo dicen tus lotes (o tus operaciones, si lo vendiste); si no, el
  // ticker (X.BA, o una acción argentina conocida). AAPL en Schwab no: no se
  // opera en BYMA. Bonos y fondos tampoco (el servidor no los lista).
  const papelByma = esFci(asset) ? null
    : !tenes ? ((asset.endsWith('.BA') || libre.accionLocal) ? asset.replace(/\.BA$/, '') : null)
      : (agg.lots.length ? agg.lots : operations).some(p => isBymaHolding(p)) ? asset.replace(/\.BA$/, '') : null

  const sabido = empresa && fundamental?.ticker === empresa.ticker ? fundamental.hay : null
  const ordenar = sabido ? { valor: orden, alElegir: elegirOrden } : null
  // Fundamental arriba sólo si hay una empresa que puede tenerlo. Mientras carga
  // se da por hecho que sí (si no, el técnico saltaría abajo al llegar); si
  // resulta que no (un ETF), vuelve al orden de siempre. Sin empresa (una
  // cripto) nunca se da vuelta: quedaría tu operatoria arriba del técnico.
  const fundamentalArriba = orden === 'fundamental' && !!empresa && sabido !== false

  if (loading) {
    return (
      <div className="page-shell-wide py-4 space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-20 w-full max-w-md rounded-lg" />
        <Skeleton className="h-40 w-full rounded-lg" />
      </div>
    )
  }

  return (
    // Todo el ancho de la página (Nico, 24/10: con `max-w-3xl` el gráfico quedaba
    // chico y con mucho negro alrededor). En el celular, el mismo ancho que antes.
    <div className="page-shell-wide py-2 sm:py-4">
      <BackBar onBack={() => navigate(-1)} asset={asset} name={name} brokerCount={agg.brokerCount} ordenar={ordenar} />

      {/* Lo que no tenés: el precio de hoy y la watchlist, en vez de tu resultado. */}
      {!tenes && (
        <HeroSinTenencia cotizacion={cotizacion}
          alCambiarWatchlist={(enWatchlist) => setCotizacion(c => ({ ...c, enWatchlist }))} />
      )}

      {/* Hero: valor + P&L total */}
      {tenes && <AskAIAbout topic="position" params={{ asset }} subtitle={`${name} · todos los lotes`}>
        <section className="mb-5">
          <div className="text-[12.5px] text-ink-2 mb-1.5 font-medium">
            Valor actual {agg.brokerCount > 1 && `· ${agg.brokerCount} brokers`}
          </div>
          <div className="text-4xl font-medium tabular tracking-tight text-ink-0 leading-none">
            ${Math.round(agg.valueUsd).toLocaleString('es-AR')}
            <span className="text-base text-ink-3 ml-1.5 font-normal">USD</span>
          </div>
          {agg.pnlPct != null && (
            <div className={`flex items-center gap-2 mt-3 text-sm font-medium tabular ${colorClass(agg.pnlPct)}`}>
              {agg.pnlPct >= 0 ? <TrendingUp size={13} strokeWidth={1.75} /> : <TrendingDown size={13} strokeWidth={1.75} />}
              <span>{agg.pnlUsd >= 0 ? '+' : '−'}${Math.abs(Math.round(agg.pnlUsd)).toLocaleString('es-AR')}</span>
              <span className="text-ink-3 font-mono text-xs">·</span>
              <span>{pctSigned(agg.pnlPct)}</span>
              <span className="text-ink-3 text-xs ml-1">no realizado</span>
            </div>
          )}
          {/* Pre/post de Wall Street: anticipo, no sumado al valor de arriba. */}
          <ChipDelActivo lotes={positions} brokers={brokers} prices={prices}
            tcValuacion={tcValuacion} tcCedear={tcCedear} tcCripto={tcCripto} className="mt-3 text-[12.5px]" />
        </section>
      </AskAIAbout>}

      {/* Chart 30d — solo para símbolos que la serie histórica sabe servir.
          Los FCI se valúan por su NAV diario (tabla fci_prices, un valor por
          fondo) y no tienen serie: yfinance no los cotiza y /api/prices/history
          rechaza el símbolo por el gate _SYMBOL_RE (los dos puntos de 'FCI:').
          Antes igual se pedía y la tarjeta mostraba el error crudo del backend
          en rojo ("Símbolo inválido: …"), que además filtraba el símbolo interno
          y le hacía creer al usuario que su fondo estaba mal cargado. */}
      {/* Lectura técnica (medias, RSI, tus compras y tu precio). Si el activo
          todavía no tiene velas guardadas, adentro cae al gráfico de 30 días. */}
      {/* Tres secciones separadas, cada una con su título (Nico, 24/10):
          técnico → tu operatoria → fundamental. Con «Fundamental primero» la
          lista se da vuelta y tu operatoria queda siempre en el medio. Van con
          `key`: React las MUEVE sin desarmarlas, así cambiar el orden no vuelve
          a pedir el gráfico ni el fundamental. */}
      {enOrden(fundamentalArriba, [
      !esFci(asset) && !(agg.lots.length > 0 && esFci(symbolFor(agg.lots[0], brokers))) && (
        <SeccionFicha key="tecnico" titulo="Análisis técnico">
        <LecturaTecnica
          titulo={null}
          key={`${asset}|${accionLocal}`}
          asset={asset}
          symbolMiniChart={agg.lots.length > 0 ? symbolFor(agg.lots[0], brokers) : tenes ? null : libre.simboloPrecio}
          lotes={positions}
          operaciones={operations}
          pnlPctUsd={agg.lots.length > 0 ? agg.pnlPct : null}
          pnlPctLinea={agg.lots.length > 0 ? agg.pnlPctCompra : null}
          lineaSinTc={agg.lineaSinTc}
          referencia={agg.lots.length > 0 ? {
            simbolo: symbolFor(agg.lots[0], brokers),
            precio: agg.lots[0].price_override ?? prices[symbolFor(agg.lots[0], brokers)] ?? null,
          } : null}
          costoPesos={costoEnPesos(agg.lots)}
          accionLocal={accionLocal}
          // «En tu cartera» de «Cuánto se mueve»: lo que vale hoy lo tuyo (y el
          // dólar de la pantalla, para decirlo en pesos) y qué parte de tu plata es.
          tenencia={agg.lots.length > 0 && agg.valueUsd > 0 ? { valorUsd: agg.valueUsd, tc: tcValuacion } : null}
          pesoEnCartera={pesoEnCartera}
        />

        {/* Cuánto se opera en BYMA y cuánto cuesta entrar y salir (CEDEARs y
            acciones argentinas): el gráfico de un CEDEAR mira Nueva York. */}
        {papelByma && <LiquidezByma papel={papelByma} />}
        </SeccionFicha>
      ),

      // Lo tuyo: tu tesis y tu operatoria (tus lotes y tu historial), juntas en
      // UN lugar del orden: con «Fundamental primero» siguen las dos en el medio.
      <Fragment key="tuya">
        {/* Tu tesis: por qué lo compraste, la tendencia de ese día y la de hoy, y
            «Recordarme revisarla». Va si lo tenés o si escribiste una (la ficha
            de un activo que vendiste todo la sigue mostrando). */}
        {(agg.lots.length > 0 || tesisVigente(tesis.items, asset)) && tesis.estado !== 'error' && (
          <section className="mb-5" aria-label={`Tu tesis de ${asset}`}>
            <div className="text-[12.5px] text-ink-2 mb-2 font-medium">Tu tesis</div>
            <Panel padding="md">
              {/* `key`: pasar de la ficha de AAPL a la de NVDA no deja a la vista
                  lo que estabas escribiendo para AAPL. */}
              <TesisDelActivo key={asset} asset={asset} local={esAccionLocal(asset, agg.lots)} tesis={tesis} />
            </Panel>
          </section>
        )}

        {tenes && <SeccionFicha titulo={`Tu operatoria en ${asset}`}>
      <section className="mb-5" aria-label="Resumen de tu operatoria">
        {/* Con ancho, las cajitas se reparten todo el renglón (3 o 6, según si
            vendiste algo): con 6 columnas fijas, 3 cajitas dejaban medio vacío. */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-2">
          <StatCell label="Costo promedio" value={agg.avgCostUsd != null ? `$${agg.avgCostUsd.toFixed(2).replace('.', ',')}` : '—'} sub="por unidad (USD)" />
          <StatCell label="Cantidad" value={agg.qty ? formatQty(agg.qty) : '—'} sub={`${agg.lots.length} lote${agg.lots.length !== 1 ? 's' : ''} abierto${agg.lots.length !== 1 ? 's' : ''}`} />
          <StatCell label="Invertido" value={`$${Math.round(agg.investedUsd).toLocaleString('es-AR')}`} sub="costo total (USD)" />
          {agg.tradesCount > 0 && (
            <>
              <StatCell
                label="P&L realizado"
                value={`${agg.realizedTotal >= 0 ? '+' : '−'}$${Math.abs(Math.round(agg.realizedTotal)).toLocaleString('es-AR')}`}
                sub={`${agg.tradesCount} op${agg.tradesCount !== 1 ? 's' : ''} cerrada${agg.tradesCount !== 1 ? 's' : ''}`}
                tone={agg.realizedTotal}
              />
              {agg.winRate != null && (
                <StatCell label="Win rate" value={`${pctTxt(agg.winRate)}`} sub={`${agg.wins} ganadas · ${agg.losses} perdidas`} tone={agg.winRate >= 50 ? 1 : -1} />
              )}
              {agg.best && (
                <StatCell label="Mejor trade" value={`${agg.best.pnl_usd >= 0 ? '+' : '−'}$${Math.abs(Math.round(agg.best.pnl_usd)).toLocaleString('es-AR')}`} sub={agg.best.date || ''} tone={agg.best.pnl_usd} />
              )}
            </>
          )}
        </div>
      </section>

      {/* Lotes e historial, uno al lado del otro cuando hay ancho y están los
          dos (uno solo ocupa todo el renglón). */}
      <div className={agg.lots.length > 0 && operations.length > 0 ? 'xl:grid xl:grid-cols-2 xl:gap-4 xl:items-start' : ''}>
      {/* Lotes abiertos (FIFO) */}
      {agg.lots.length > 0 && (
        <section className="mb-5">
          <div className="flex items-center justify-between mb-2">
            <div className="text-[12.5px] text-ink-2 font-medium">Lotes abiertos · orden FIFO</div>
            <div className="text-[10px] font-mono text-ink-3">el más viejo se vende primero</div>
          </div>
          <div className="bg-bg-1 border border-line/60 rounded-lg overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[12px] text-ink-3 border-b border-line/40 font-medium">
                  <th scope="col" className="text-left font-normal px-3 py-2">Fecha</th>
                  <th scope="col" className="text-left font-normal px-3 py-2 hidden sm:table-cell">Broker</th>
                  <th scope="col" className="text-right font-normal px-3 py-2">Cantidad</th>
                  <th scope="col" className="text-right font-normal px-3 py-2">Costo</th>
                  <th scope="col" className="text-right font-normal px-3 py-2">P&L</th>
                </tr>
              </thead>
              <tbody>
                {agg.lots.map((lot, i) => {
                  const lotPct = lot.investedUsd > 0 ? lot.pnlUsd / lot.investedUsd : null
                  return (
                    <tr key={lot.id ?? i} className={i > 0 ? 'border-t border-line/30' : ''}>
                      <td className="px-3 py-2.5 text-ink-1">{lot.entry_date || '—'}{i === 0 && <span className="ml-1.5 text-[12.5px] text-rendi-warn font-medium">próximo</span>}</td>
                      <td className="px-3 py-2.5 text-ink-3 text-xs hidden sm:table-cell">{lot.broker}</td>
                      <td className="px-3 py-2.5 text-right tabular text-ink-1">{formatQty(lot.quantity)}</td>
                      <td className="px-3 py-2.5 text-right tabular text-ink-3">${Math.round(lot.investedUsd).toLocaleString('es-AR')}</td>
                      <td className={`px-3 py-2.5 text-right tabular font-medium ${colorClass(lotPct)}`}>
                        {lot.pnlUsd >= 0 ? '+' : '−'}${Math.abs(Math.round(lot.pnlUsd)).toLocaleString('es-AR')}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Historial de operaciones */}
      {operations.length > 0 && (
        <AskAIAbout topic="position.lots" params={{ asset }} subtitle={`Historial · ${name}`}>
          <section className="mb-5">
            <div className="text-[12.5px] text-ink-2 mb-2 font-medium">Historial · {operations.length} operacion{operations.length !== 1 ? 'es' : ''}</div>
            <ul className="bg-bg-1 border border-line/60 rounded-lg overflow-hidden">
              {operations.map((op, i) => {
                const isClosed = op.pnl_usd != null
                const win = isClosed && op.pnl_usd >= 0
                return (
                  <li key={op.id ?? i} className={`flex items-center gap-3 px-3 py-2.5 ${i > 0 ? 'border-t border-line/30' : ''}`}>
                    <Calendar size={11} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-ink-1 leading-none">
                        {op.date} · <span className="text-ink-3">{op.op_type || 'op'}</span>
                        <span className="text-ink-3 hidden sm:inline"> · {op.broker}</span>
                      </div>
                      {op.quantity != null && !esCobro(op.op_type) && (
                        <div className="text-[10px] font-mono text-ink-3 leading-none mt-1">{formatQty(op.quantity)} u.</div>
                      )}
                    </div>
                    {isClosed && (
                      <span className={`text-[12.5px] px-1.5 py-0.5 rounded-sm border ${win ? 'text-rendi-pos border-rendi-pos/30 bg-rendi-pos/10' : 'text-rendi-neg border-rendi-neg/30 bg-rendi-neg/10'} font-medium`}>
                        {win ? 'ganada' : 'perdida'}
                      </span>
                    )}
                    {isClosed && (
                      <div className={`text-sm font-medium tabular leading-none w-20 text-right ${colorClass(op.pnl_usd)}`}>
                        {op.pnl_usd >= 0 ? '+' : '−'}${Math.abs(Math.round(op.pnl_usd)).toLocaleString('es-AR')}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </section>
        </AskAIAbout>
      )}
      </div>
      </SeccionFicha>}
      </Fragment>,

      // Análisis fundamental de la empresa, de entrada al final: técnico → lo
      // tuyo (operatoria, lotes, historial) → fundamental, para no tener que
      // pasar todo el fundamental para llegar a tus lotes (Nico, 23/10). Es la
      // MISMA vista de "Análisis fundamental" (AnalyzeView), sin buscador ni
      // resumen con IA; para compararla con otras, el link lleva ahí. Sin
      // empresa (cripto, ETF, bono, fondo) no aparece.
      empresa && <AnalyzeView key="fundamental" ticker={empresa.ticker} enFicha irACalidad={empresa.ir} alSaberSiHay={alSaberSiHay} />,
      ])}
    </div>
  )
}

// ─── helpers ──────────────────────────────────────────────────────────────

// Las secciones de la ficha en el orden elegido: al revés pone el fundamental
// arriba y el técnico abajo, con lo tuyo siempre en el medio.
function enOrden(alReves, secciones) {
  return alReves ? [...secciones].reverse() : secciones
}

// El arriba de la ficha de un activo que no tenés: su último precio (en pesos
// si cotiza en BYMA, en dólares si no), cuánto se movió hoy y la estrella de
// la watchlist (lo que hacía el modal AssetQuickView, que ya no existe).
function HeroSinTenencia({ cotizacion, alCambiarWatchlist }) {
  const [guardando, setGuardando] = useState(false)
  const [error, setError] = useState(null)
  const precio = cotizacion?.precio
  const variacion = precio != null && cotizacion?.previo > 0 ? precio / cotizacion.previo - 1 : null
  // La estrella guarda el MISMO símbolo que cotiza la ficha (GGAL.BA, AGRO.BA):
  // guardaba el de la dirección, y "AGRO" en la watchlist es Adecoagro, otra
  // empresa en dólares (auditoría 22/10).
  const simbolo = cotizacion?.simbolo
  const enWatchlist = cotizacion?.enWatchlist || null
  const enPesos = monedaDe(simbolo) === '$'
  async function alternar() {
    if (guardando || !simbolo) return
    setGuardando(true)
    setError(null)
    try {
      if (enWatchlist) {
        await api.delete(`/watchlist/${encodeURIComponent(enWatchlist)}`)
        notifyWatchlistChanged({ symbol: enWatchlist, removed: true })
        alCambiarWatchlist(null)
      } else {
        await api.post('/watchlist', { symbol: simbolo })
        notifyWatchlistChanged({ symbol: simbolo, added: true })
        alCambiarWatchlist(simbolo)
      }
    } catch (ex) {
      // Se dice en la pantalla (antes sólo en la consola): la lista llena, o un
      // símbolo que la watchlist no acepta (BRK-B).
      setError(ex?.status === 400 && ex?.message ? ex.message : 'No se pudo cambiar la watchlist. Probá de nuevo.')
    } finally {
      setGuardando(false)
    }
  }
  return (
    <section className="mb-5">
      <div className="text-[12.5px] text-ink-2 mb-1.5 font-medium">Último precio</div>
      <div className="text-4xl font-medium tabular tracking-tight text-ink-0 leading-none">
        {precio != null ? `$${precio.toLocaleString(LOCALE, precio >= 1000
          ? { maximumFractionDigits: 0 }
          : precio >= 1 ? { minimumFractionDigits: 2, maximumFractionDigits: 2 } : { maximumSignificantDigits: 4 })}` : '—'}
        <span className="text-base text-ink-3 ml-1.5 font-normal">{enPesos ? 'pesos' : 'USD'}</span>
      </div>
      {variacion != null && (
        <div className={`flex items-center gap-1.5 mt-3 text-sm font-medium tabular ${colorClass(variacion)}`}>
          {variacion >= 0 ? <TrendingUp size={13} strokeWidth={1.75} /> : <TrendingDown size={13} strokeWidth={1.75} />}
          <span>{pctSigned(variacion)}</span>
          <span className="text-ink-3 text-xs ml-1 font-normal">contra el cierre anterior</span>
        </div>
      )}
      <button
        type="button"
        onClick={alternar}
        disabled={guardando || !cotizacion}
        aria-pressed={!!enWatchlist}
        className={`mt-4 inline-flex items-center gap-1.5 min-h-10 px-3 rounded-lg border text-[13px] transition-colors disabled:opacity-50 ${
          enWatchlist
            ? 'border-rendi-warn/30 bg-rendi-warn/10 text-rendi-warn hover:bg-rendi-warn/15'
            : 'border-line bg-bg-2 text-ink-1 hover:bg-bg-3'
        }`}
      >
        {enWatchlist
          ? <><Check size={13} strokeWidth={2} /> En la watchlist</>
          : <><Star size={13} strokeWidth={1.75} /> Agregar a la watchlist</>}
      </button>
      {error && <p role="alert" className="text-[12.5px] text-rendi-neg mt-2">{error}</p>}
    </section>
  )
}

// `ordenar`: { valor, alElegir } para el «Ordenar por», o null si el activo no
// tiene fundamental (cripto, ETF, bono): ahí no hay nada que ordenar. En la
// compu va al lado del nombre (no contra el borde derecho: ahí flota la burbuja
// de Mervall-E y lo tapaba); en el celular, en su propio renglón abajo.
function BackBar({ onBack, asset, name, brokerCount, ordenar }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 mb-5">
      <button type="button" onClick={onBack} aria-label="Volver" className="text-ink-2 hover:text-ink-0 -ml-2 rounded-sm hover:bg-bg-2 transition-colors flex items-center justify-center min-w-[44px] min-h-[44px]">
        <ArrowLeft size={18} strokeWidth={1.75} />
      </button>
      <AssetLogo asset={asset} size={32} />
      <div className="min-w-0">
        <div className="text-base font-semibold text-ink-0 leading-tight truncate">{name}</div>
        <div className="text-[12.5px] text-ink-3 leading-none mt-0.5 font-medium">
          {asset}{brokerCount > 1 ? ` · ${brokerCount} brokers` : ''}
        </div>
      </div>
      {ordenar && (
        <div className="w-full sm:w-auto sm:ml-4 flex items-center gap-2">
          <span className="text-[12.5px] text-ink-3 font-medium whitespace-nowrap">Ordenar por</span>
          <Segmento etiqueta="Ordenar la ficha" valor={ordenar.valor} alElegir={ordenar.alElegir} estirar
            opciones={[['tecnico', 'Técnico primero'], ['fundamental', 'Fundamental primero']]} />
        </div>
      )}
    </div>
  )
}

function StatCell({ label, value, sub, tone }) {
  const toneCls = tone == null ? 'text-ink-0' : colorClass(tone)
  return (
    <div className="bg-bg-1 border border-line/60 rounded-lg px-3 py-2.5 min-w-0">
      <div className="text-[12px] text-ink-3 mb-1 font-medium">{label}</div>
      <div className={`text-base font-medium tabular truncate ${toneCls}`}>{value}</div>
      {sub && <div className="text-[10px] text-ink-3 mt-0.5 truncate" title={sub}>{sub}</div>}
    </div>
  )
}

function formatQty(q) {
  if (q == null || isNaN(q)) return '—'
  if (Math.abs(q) >= 1000) return Math.round(q).toLocaleString('es-AR')
  if (Math.abs(q) >= 1) return q.toLocaleString(LOCALE, { maximumFractionDigits: 2 })
  return q.toFixed(4).replace('.', ',')
}
