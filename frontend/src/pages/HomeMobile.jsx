// HomeMobile — Home mobile (Sprint M1, item 01 del audit).
// ═══════════════════════════════════════════════════════════════════════════
// PRINCIPIO: paridad de features con desktop. Mismo contenido, distinto
// orden y layout. La filosofía mobile (chequeo rápido) se manifiesta en
// el ORDEN priorizado (lo importante arriba) — no en recortar features.
//
// Orden:
//   1. Hero balance (USD) + delta + sparkline 30d
//   2. KPI strip 2-col (P&L día · P&L mes · capital aportado · mejor activo)
//   3. "Hoy en tu cartera" — PersonalLayer (movimientos del día relevantes)
//   4. Heatmap S&P
//   5. Movers del día (top gainers + losers)
//   6. Watchlist
//   7. Noticias + Eventos (apilados, no en grid 2-col)

import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, TrendingUp, TrendingDown, Eye, EyeOff } from 'lucide-react'
import MiniSparkline from '../components/MiniSparkline'
import FlashValue from '../components/FlashValue'
import Skeleton from '../components/Skeleton'
import BenchmarksLine from '../components/BenchmarksLine'
import PersonalLayer from '../components/home/PersonalLayer'
import Heatmap from '../components/home/Heatmap'
import MoversRail from '../components/home/MoversRail'
import Watchlist from '../components/home/Watchlist'
import NewsPreview from '../components/home/NewsPreview'
import EventsPreview from '../components/home/EventsPreview'
import OnboardingChecklist from '../components/home/OnboardingChecklist'
import Eyebrow from '../components/Eyebrow'
import AnalyzeButton from '../components/ai/AnalyzeButton'
import AskAIAbout from '../components/ai/AskAIAbout'
import { api } from '../utils/api'
import { usePrivacy } from '../contexts/PrivacyContext'
import { computeBrokerValue, priceSymbol, isArUsdBroker, costInPesos, costInUsd, usdLotValue, isFciSym, trustMktValue, buildPriceSymbols } from '../utils/valuation'
import { isCrypto, cryptoBrokerFactor } from '../utils/crypto'
import { usePfRollup, pfUsd } from '../hooks/usePfRollup'
import { computeDailyPnl, computeReturnDelta, buildPortfolioValueSeries } from '../utils/evolution'
import { fmtUsd, fmtArs, ars, pctSigned, colorClass } from '../utils/format'
import { useCurrency, pickFinancialRate } from '../contexts/CurrencyContext'

export default function HomeMobile() {
  // Fase A (2026-05-31): currency global via context — sincroniza con Dashboard.
  // Fase B: además publicamos tcBlue al context para que Reports / charts
  // puedan leer sin re-fetchear /dolar.
  const { currency, toggle: toggleCurrency, setTcBlue: publishTcBlue, valuationDollar } = useCurrency()
  const { hidden, toggle: togglePrivacy } = usePrivacy()
  const [positions, setPositions] = useState([])
  const [monthly, setMonthly] = useState([])
  const [brokers, setBrokers] = useState([])
  const [dolar, setDolar] = useState(null)
  const [prices, setPrices] = useState({})
  const [snapshots, setSnapshots] = useState([])
  const [bench, setBench] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => { loadAll() }, [])

  async function loadAll() {
    try {
      const [pos, mon, bkrs, dol, snaps] = await Promise.all([
        api.get('/positions').catch(() => []),
        api.get('/monthly').catch(() => []),
        api.get('/brokers').catch(() => []),
        api.get('/dolar').catch(() => null),
        api.get('/snapshots?days=30').catch(() => []),
      ])
      setPositions(pos || [])
      setMonthly(mon || [])
      setBrokers(bkrs || [])
      setDolar(dol)
      setSnapshots(snaps || [])
      await loadPrices(pos, bkrs)
    } finally {
      setLoading(false)
    }

    // /benchmarks aparte del critical path:
    // hace 3 fetches externos (yfinance ^SP500TR + argentinadatos inflación + blue)
    // sin timeout total — en cache miss puede tardar 20-45s. Bloquearlo en el
    // Promise.all retrasa loadPrices() + setLoading(false), generando que se vea
    // "Cargando…" hasta que termine. Fire-and-forget: la BenchmarksCard aparece
    // con tiles "—" mientras carga, y se actualiza cuando llega.
    api.get('/benchmarks').then(setBench).catch(() => {})
  }

  async function loadPrices(pos, bkrs) {
    if (!pos?.length || !bkrs?.length) return
    // Símbolos por el helper canónico (espejo de computeBrokerValue) — misma
    // lista que Dashboard/Positions/PositionsMobile. Suma sobre la versión previa:
    // la cripto en un sub-broker AR '· USD' se pide SPOT (antes se pedía BTC.BA
    // y la valuación lee prices[BTC] → caía a costo). Ver buildPriceSymbols.
    const all = buildPriceSymbols(pos, bkrs).join(',')
    if (!all) return
    try { setPrices(await api.get(`/prices?symbols=${all}`)) } catch { /* silent */ }
  }

  const tcBlue = pickFinancialRate(dolar, valuationDollar) || 1415
  const tcCedear = pickFinancialRate(dolar, valuationDollar) || tcBlue  // dólar financiero p/ CEDEARs
  const tcCripto = dolar?.cripto?.venta  // dólar cripto (~spot+5%) p/ cripto en broker AR
  const pf = pfUsd(usePfRollup(), tcBlue)  // plazos fijos → USD (suma al total mostrado)

  // Fase B: publicamos tcBlue al CurrencyContext (sin reemplazar el local;
  // el componente sigue usando `tcBlue` para sus propios memos).
  useEffect(() => {
    if (tcBlue > 0) publishTcBlue(tcBlue)
  }, [tcBlue, publishTcBlue])

  const totals = useMemo(() => {
    const bt = brokers.map(b => ({ ...b, ...computeBrokerValue(positions, prices, b, tcBlue, tcCedear, tcCripto) }))
    const totalValue = bt.reduce((s, b) => s + b.value, 0)
    const totalCost = bt.reduce((s, b) => s + b.invested, 0)
    const totalPnl = totalValue - totalCost
    const pct = totalCost > 0 ? totalPnl / totalCost : 0
    return { totalValue, totalCost, totalPnl, pct }
  }, [positions, prices, brokers, tcBlue, tcCedear, tcCripto])

  // Total valuado SIEMPRE al MEP, SOLO para comparar contra snapshots (P&L Día /
  // P&L Mes / sparkline). Los snapshots viven en MEP por diseño; si el riel del
  // user es CCL, comparar el live-CCL contra un snapshot-MEP fabrica la brecha
  // CCL/MEP como "ganancia del día" fantasma. El riel gobierna solo el DISPLAY
  // (hero = totals); las comparaciones van ancladas al mismo sabor que la serie.
  // Con riel MEP (default) tcMep === tcCedear → mismo número, cero cambio.
  const tcMep = pickFinancialRate(dolar, 'mep') || tcBlue
  const totalsMep = useMemo(() => {
    if (tcMep === tcCedear) return null  // riel MEP: reusar totals (evita doble cálculo)
    const bt = brokers.map(b => ({ ...b, ...computeBrokerValue(positions, prices, b, tcMep, tcMep, tcCripto) }))
    return { totalValue: bt.reduce((s, b) => s + b.value, 0) }
  }, [positions, prices, brokers, tcMep, tcCedear, tcCripto])
  const compareValue = totalsMep ? totalsMep.totalValue : totals.totalValue

  // Capital aportado = baseline + flujos. Misma fórmula que compute_net_deposited
  // del backend → comparable 1:1 con snapshot.net_deposited (ambos en USD).
  const aportado = useMemo(() => {
    const sorted = monthly
      .filter(m => m.broker === 'global')
      .sort((a, b) => (a.year !== b.year ? a.year - b.year : a.month - b.month))
    const baseline = sorted[0]?.capital_inicio || 0
    const flows = sorted.reduce((s, m) => s + (m.deposits || 0) - (m.withdrawals || 0), 0)
    return baseline + flows
  }, [monthly])

  // Serie 30d desde snapshots + punto LIVE de hoy — base para sparkline + delta.
  // buildPortfolioValueSeries (mismo helper que la curva del Dashboard):
  //  · appendea el valor VIVO como punto de hoy → el "Hoy" del sparkline es el
  //    mismo número que el hero (antes era el cierre de ayer: dos "hoy" distintos
  //    en la misma pantalla).
  //  · filtra por VENTANA DE FECHAS real con anchor (GET /snapshots?days=30 es
  //    LIMIT de filas, no de días — con huecos del cron devolvía 40-60 días).
  // El delta del período va AJUSTADO POR FLUJOS: Δ(value − net_deposited), igual
  // que periodChange del Dashboard. Antes era Δtotal_value crudo → un depósito de
  // $5.000 se mostraba como "+$5.000 (+52%) en 30 días" de ganancia fantasma.
  const series30d = useMemo(() => {
    if (!snapshots?.length) return null
    const live = compareValue > 0 ? compareValue : null
    const points = buildPortfolioValueSeries(snapshots, 30, live, live != null ? aportado : null)
    if (!points || points.length < 2) return null
    const first = points[0]
    const last = points[points.length - 1]
    const deltaUsd = (last.valueUsd - last.netDeposited) - (first.valueUsd - first.netDeposited)
    const deltaPct = first.valueUsd > 0 ? deltaUsd / first.valueUsd : 0
    return {
      values: points.map(p => p.valueUsd),
      first: first.valueUsd,
      last: last.valueUsd,
      deltaUsd,
      deltaPct,
      positive: deltaUsd >= 0,
    }
  }, [snapshots, compareValue, aportado])

  // KPIs: P&L mes (month-to-date desde snapshots) + delta vs día anterior
  const kpis = useMemo(() => {
    // P&L Mes = Δ(Total Return) desde el cierre del mes pasado, MtM y ajustado
    // por flujos — MISMO cálculo que "Este mes" del Dashboard (computeReturnDelta
    // con sinceDate=1° del mes). ANTES leía pnl_realized+pnl_unrealized del último
    // monthly_entries: como los meses cerrados quedan a COSTO, ese pnl_unrealized
    // es el acumulado DE TODA LA VIDA (y encima solo lo sincroniza el Dashboard
    // desktop → stale en mobile-only). Cartera que ganó $8.000 en 2 años con un
    // julio de +$300 mostraba "P&L Mes +$8.000" (26× el real).
    // Guard compareValue > 0: hasta que los precios live no llegaron, el valor
    // puede estar incompleto y la variación mostraría una pérdida falsa.
    const d = new Date()
    const monthStart = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
    const monthDelta = compareValue > 0
      ? computeReturnDelta(snapshots, { liveValue: compareValue, liveNetDeposited: aportado, sinceDate: monthStart })
      : null
    const pnlMonth = monthDelta?.usd ?? null
    // P&L del día = Δ(Total Return) entre la cartera live de hoy y el cierre
    // anterior, EXCLUYENDO depósitos/retiros. El cálculo viejo (Δtotal_value)
    // contaminaba el dato: un retiro de $110 se mostraba como "P&L día −$110"
    // aunque no hubiera pérdida. Ver computeDailyPnl en utils/evolution.js.
    // compareValue = total al MEP (mismo sabor que los snapshots, ver totalsMep).
    const daily = compareValue > 0
      ? computeDailyPnl(snapshots, {
          liveValue: compareValue,
          liveNetDeposited: aportado,
        })
      : null
    const pnlDay = daily?.usd ?? null
    // Mejor activo hoy = mayor change_pct del día (necesitaría /prices con change — usamos % del PnL no real por ahora)
    let bestAsset = null
    let bestPct = -Infinity
    const exchangeBrokers = new Set((brokers || []).filter(b => b.is_exchange).map(b => b.name))
    const arsBrokerSet = new Set((brokers || []).filter(b => b.currency === 'ARS').map(b => b.name))
    for (const p of positions) {
      if (p.is_cash || !p.invested) continue
      const isAR = arsBrokerSet.has(p.broker)
      // Valuación CONSISTENTE con la Cartera (calcUSDT): un CEDEAR o cualquier
      // instrumento en un sub-broker '· USD' se valúa por su precio LOCAL .BA ÷ MEP,
      // NO por el ticker US. Antes usaba prices[p.asset] (Visa US ~$300 vs CEDEAR ~$19)
      // → valor inflado ~16× y P&L% disparado (V daba +160.658% en vez de +7%).
      let px
      if (isAR && costInUsd(p)) {
        // Espejo de costInPesos: lote de COSTO EN DÓLARES (bono/ON/FCI-USD, o CEDEAR
        // comprado en dólar-MEP → currency='USD') en un broker ARS (Balanz). El precio
        // por-unidad ya sale en USD de usdLotValue (CEDEAR/acción-AR por .BA÷MEP, resto
        // por NAV/precio USD nativo). Sin esto caía al else (prices[US]=null) → se
        // salteaba del ranking (o, con costo tratado como pesos, %/valor rotos). Gateado
        // a broker ARS: una acción US genuina en broker USD NO entra (usdLotValue le
        // armaría 'AAPL.BA', inexistente) → cae al else que sí usa prices[US] correcto.
        px = usdLotValue(p, prices, tcCedear).priceUsd
      } else if ((p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker)) && !isCrypto(p.asset) && !isFciSym(p.asset) && p.price_override == null) {
        const priceArs = prices[priceSymbol(p.asset, true, p.asset_type)]
        px = priceArs != null ? priceArs / tcCedear : null
      } else {
        // Key normalizada primero (BRK.B → 'BRK-B', la que el fetch pide), fallback
        // a la cruda. CEDEAR solo llega acá con override (la rama .BA lo captura).
        px = p.price_override ?? prices[priceSymbol(p.asset, false, p.asset_type)] ?? prices[p.asset]
      }
      if (px == null) continue
      // Cripto en broker AR (no exchange, sin override) se valúa al dólar cripto:
      // escalamos value e invested por el mismo factor → el % queda invariante.
      const f = cryptoBrokerFactor(p.asset, exchangeBrokers.has(p.broker), p.price_override != null, tcCripto, tcCedear)
      const mkt = px * (p.quantity || 0) * f
      // Cost basis = invested + comisiones (igual que la Cartera). Sin las comisiones
      // el % se dispara cuando son parte grande del costo.
      const realCost = (p.invested || 0) + (p.commissions || 0)
      // costInPesos (CEDEAR/activo comprado en pesos en cuenta USD): el costo está en
      // ARS → a USD por el MEP, igual que px. El resto ya está en USD → escala por el
      // factor cripto. Sin esto, mkt(USD) vs invested(ARS) rompía el ratio del guard
      // y clampeaba de más los CEDEARs en pesos (mostraba 0% en vez de su ganancia).
      // costInUsd en broker ARS: costo YA en USD (sin ÷ ni factor). costInPesos: pesos
      // → USD por el MEP. Resto: escala por el factor cripto (1 para lo no-cripto-de-
      // broker) — la acción US en broker USD cae acá y realCost*1 ya está en USD.
      const invested = isAR && costInUsd(p) ? realCost : costInPesos(p) ? realCost / tcCedear : realCost * f
      if (!(invested > 0)) continue
      // Clamp anti-distorsión (igual que computeBrokerValue): un bono per-100 leído
      // como per-1 infla el valor ×100 → pct fantasma. mkt e invested quedan en las
      // MISMAS unidades (USD), así que trustMktValue compara el ratio. Si no se
      // confía, cae a costo → P&L 0 para esta posición.
      const value = trustMktValue(mkt, invested, p.asset_type, p.price_override != null) ? mkt : invested
      const pct = (value - invested) / invested
      if (pct > bestPct) {
        bestPct = pct
        bestAsset = { symbol: p.asset, pct }
      }
    }
    // "Mejor activo" es el de MAYOR rendimiento: si el mejor está en negativo, ningún
    // activo está en verde → no tiene sentido rotularlo "mejor" con un % rojo (ej. el
    // -87,5% absurdo de un bono con costo aún sin recomputar). Mostramos '—'.
    if (bestAsset && bestPct <= 0) bestAsset = null
    return { pnlMonth, pnlMonthMeta: monthDelta, pnlDay, pnlDayMeta: daily, aportado, bestAsset }
  }, [snapshots, positions, prices, compareValue, aportado, brokers, tcCripto, tcCedear])

  if (loading) {
    return (
      <div className="px-4 py-6 space-y-5" aria-busy="true" aria-live="polite">
        <div className="space-y-2">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-12 w-48" />
          <Skeleton className="h-4 w-40" />
        </div>
        <Skeleton className="h-16 w-full rounded-lg" />
        <div className="grid grid-cols-3 gap-3">
          {[0, 1, 2].map(i => <Skeleton key={i} className="h-16 rounded-lg" />)}
        </div>
      </div>
    )
  }

  return (
    <div className="pb-8">
      {/* ── 0. Onboarding checklist (mobile) ────────────────────────────
          Solo visible si el user no completó todos los items. Padding
          horizontal matchea el resto de la home mobile. */}
      <div className="px-4 pt-4">
        <OnboardingChecklist />
      </div>

      {/* ── 1. Hero balance ─────────────────────────────────────────── */}
      <section className="px-4 pt-5 pb-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className="text-[12.5px] text-ink-2 font-medium">
              Tu cartera
            </div>
            <button
              onClick={togglePrivacy}
              className="text-ink-3 hover:text-ink-0 active:text-ink-0 transition-colors"
              title={hidden ? 'Mostrar saldos' : 'Ocultar saldos'}
            >
              {hidden ? <EyeOff size={13} /> : <Eye size={13} />}
            </button>
          </div>
          {/* Botón primario de análisis del portfolio — siempre visible
              y prominente (no es hover-reveal porque mobile). */}
          <AnalyzeButton
            screen="home"
            subtitle="El mercado y tu cartera hoy"
            label="Analizar"
          />
        </div>
        {totals.pct != null && (
          <div className={`text-[12px] tabular mb-1.5 ${colorClass(totals.pct)} font-medium`}>
            {pctSigned(totals.pct)} histórico
          </div>
        )}

        {/* Balance grande — toggle USD/ARS al tap del badge.
            Fase A: sincronizado con Dashboard via CurrencyContext. */}
        <div className="text-5xl font-medium tabular tracking-tight text-ink-0 leading-none mb-3">
          {hidden
            ? <span className="opacity-40 tracking-[0.2em] select-none">••••••</span>
            : <FlashValue value={totals.totalValue + pf.valueUsd}>
                {currency === 'ARS'
                  ? `$${fmtNumber((totals.totalValue + pf.valueUsd) * tcBlue)}`
                  : `$${fmtNumber(totals.totalValue + pf.valueUsd)}`}
              </FlashValue>}
          <button
            onClick={toggleCurrency}
            className="text-base text-ink-3 ml-1.5 font-normal hover:text-ink-1 active:text-ink-0 transition-colors"
            title={`Cambiar a ${currency === 'USD' ? 'ARS' : 'USD'}`}
          >
            {currency}
          </button>
        </div>

        {/* Sparkline 30d con delta del MISMO período (no histórico) */}
        {series30d ? (
          <div className="bg-bg-1 border border-line/40 rounded-lg p-3">
            <div className="flex items-baseline justify-between mb-1.5">
              <div className="flex items-center gap-1.5">
                <span className="text-[12.5px] text-ink-2 font-medium">
                  Últimos 30 días
                </span>
                <span className={`inline-flex items-center gap-0.5 text-xs font-medium tabular ${series30d.positive ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                  {series30d.positive
                    ? <TrendingUp size={11} strokeWidth={1.75} />
                    : <TrendingDown size={11} strokeWidth={1.75} />}
                  {pctSigned(series30d.deltaPct)}
                </span>
              </div>
              <span className={`text-xs font-mono tabular ${series30d.positive ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                {hidden ? '••••••' : `${series30d.positive ? '+' : '−'}$${fmtNumber(Math.abs(currency === 'ARS' ? series30d.deltaUsd * tcBlue : series30d.deltaUsd))}`}
              </span>
            </div>
            <div className="h-12 -mx-1">
              <MiniSparkline
                data={series30d.values}
                positive={series30d.positive}
                width={400}
                height={48}
              />
            </div>
            <div className="flex items-baseline justify-between mt-1.5 text-[10px] font-mono text-ink-3">
              <span className="tabular">Hace 30d · {hidden ? '••••••' : `$${fmtNumber(currency === 'ARS' ? series30d.first * tcBlue : series30d.first)}`}</span>
              <span className="tabular">Hoy · {hidden ? '••••••' : `$${fmtNumber(currency === 'ARS' ? series30d.last * tcBlue : series30d.last)}`}</span>
            </div>
          </div>
        ) : (
          <div className="bg-bg-1 border border-line/40 rounded-lg p-3 text-center text-[11px] text-ink-3">
            Cargá tus snapshots diarios para ver la evolución 30d.
          </div>
        )}
      </section>

      {/* ── 2. KPI strip 2x2 ────────────────────────────────────────── */}
      <section className="px-4 mb-5">
        <div className="grid grid-cols-2 border border-line/60 rounded-lg overflow-hidden bg-bg-1">
          <KpiCell
            label={kpis.pnlDayMeta && kpis.pnlDayMeta.dayDiff > 1 ? `P&L ${kpis.pnlDayMeta.dayDiff}d` : 'P&L Día'}
            value={hidden ? '••••••' : (kpis.pnlDay != null ? `${kpis.pnlDay >= 0 ? '+' : '−'}$${fmtNumber(Math.abs(currency === 'ARS' ? kpis.pnlDay * tcBlue : kpis.pnlDay))}` : '—')}
            sub={kpis.pnlDay != null && kpis.pnlDayMeta ? pctSigned(kpis.pnlDayMeta.pct) : null}
            subTone={kpis.pnlDay != null ? (kpis.pnlDay >= 0 ? 'pos' : 'neg') : null}
            tone={kpis.pnlDay != null ? (kpis.pnlDay >= 0 ? 'pos' : 'neg') : null}
            bordered
          />
          <KpiCell
            label="P&L Mes"
            value={hidden ? '••••••' : (kpis.pnlMonth != null ? `${kpis.pnlMonth >= 0 ? '+' : '−'}$${fmtNumber(Math.abs(currency === 'ARS' ? kpis.pnlMonth * tcBlue : kpis.pnlMonth))}` : '—')}
            sub={kpis.pnlMonth != null && kpis.pnlMonthMeta ? pctSigned(kpis.pnlMonthMeta.pct) : null}
            subTone={kpis.pnlMonth != null ? (kpis.pnlMonth >= 0 ? 'pos' : 'neg') : null}
            tone={kpis.pnlMonth != null ? (kpis.pnlMonth >= 0 ? 'pos' : 'neg') : null}
            bordered
            leftBorder
          />
          <KpiCell
            label="Capital aportado"
            value={hidden ? '••••••' : (kpis.aportado > 0 ? `$${fmtNumber(currency === 'ARS' ? kpis.aportado * tcBlue : kpis.aportado)}` : '—')}
            sub={`${currency} neto`}
            topBorder
          />
          <KpiCell
            label="Mejor activo"
            value={kpis.bestAsset ? kpis.bestAsset.symbol : '—'}
            sub={kpis.bestAsset ? pctSigned(kpis.bestAsset.pct) : null}
            subTone={kpis.bestAsset?.pct >= 0 ? 'pos' : 'neg'}
            topBorder
            leftBorder
          />
        </div>
      </section>

      {/* ── 2.5. Headline benchmarks ───────────────────────────────
          1 línea con S&P + dólar quieto. Detalle completo en /insights.
          Liviano para no saturar la primera screen mobile. */}
      {totals.totalValue > 0 && (
        <section className="px-4 mb-5">
          <BenchmarksLine
            monthly={monthly}
            bench={bench}
            totalPortfolio={totals.totalValue}
          />
        </section>
      )}

      {/* ── 3. Hoy en tu cartera ───────────────────────────────────── */}
      <section className="px-4 mb-5">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-[12.5px] text-ink-2 font-medium">
            Hoy en tu cartera
          </h2>
          <Link
            to="/posiciones"
            className="text-[12.5px] text-ink-2 hover:text-ink-0 inline-flex items-center gap-1 font-medium"
          >
            Ver todas <ArrowRight size={11} strokeWidth={1.75} />
          </Link>
        </div>
        <PersonalLayer />
      </section>

      {/* ── 4. Heatmap S&P ─────────────────────────────────────────── */}
      <section className="px-4 mb-5">
        <h2 className="text-[12.5px] text-ink-2 mb-2 font-medium">
          S&P 500 hoy
        </h2>
        <Heatmap defaultMarket="sp500" />
      </section>

      {/* ── 5. Movers del día ──────────────────────────────────────── */}
      <section className="px-4 mb-5">
        <h2 className="text-[12.5px] text-ink-2 mb-2 font-medium">
          Movers del día
        </h2>
        <MoversRail market="sp500" />
      </section>

      {/* ── 6. Watchlist ───────────────────────────────────────────── */}
      <section className="px-4 mb-5">
        <Watchlist />
      </section>

      {/* ── 7. Noticias + Eventos (apilados en mobile) ─────────────── */}
      <section className="px-4 mb-5">
        <AskAIAbout topic="news" subtitle="Tus noticias del período">
          <NewsPreview />
        </AskAIAbout>
      </section>
      <section className="px-4">
        <AskAIAbout topic="events" subtitle="Tus eventos próximos">
          <EventsPreview />
        </AskAIAbout>
      </section>
    </div>
  )
}

// ─── KpiCell mobile ───────────────────────────────────────────────────────

function KpiCell({ label, value, sub, tone, subTone, bordered, leftBorder, topBorder }) {
  const valueColor =
    tone === 'pos' ? 'text-rendi-pos'
    : tone === 'neg' ? 'text-rendi-neg'
    : 'text-ink-0'
  const subColor =
    subTone === 'pos' ? 'text-rendi-pos'
    : subTone === 'neg' ? 'text-rendi-neg'
    : 'text-ink-3'
  return (
    <div className={`px-3 py-3 ${leftBorder ? 'border-l border-line/40' : ''} ${topBorder ? 'border-t border-line/40' : ''}`}>
      <div className="text-[12.5px] text-ink-2 mb-1.5 leading-none font-medium">
        {label}
      </div>
      <div className={`text-base font-medium tabular leading-none ${valueColor}`}>
        {value}
      </div>
      {sub && (
        <div className={`text-[10px] font-mono tabular mt-1 leading-none ${subColor}`}>
          {sub}
        </div>
      )}
    </div>
  )
}

function fmtNumber(n) {
  if (n == null || isNaN(n)) return '—'
  return Math.round(n).toLocaleString('en-US')
}
