// Operations — la pantalla de actividad: trades cerrados y movimientos.
// ════════════════════════════════════════════════════════════════════════════
// UN dueño de datos, DOS ramas de render. Hasta la Fase 3 esto era un fork por
// viewport: un `if (isMobile)` que devolvía `<OperationsMobile />`, un archivo
// de 661 líneas que reimplementaba filtros, agrupación y renderers. El fork no
// duplicaba sólo la vista — duplicaba los números, y por eso hubo que dedicar
// una fase entera a reconciliarlos antes de poder borrarlo.
//
// Ahora: un `useIsMobile()`, un `load()`, un set de filtros, un cálculo de KPIs,
// y dos ramas que sólo eligen CÓMO se dibuja lo mismo. Los renderers viven en
// components/operations/ y no tienen estado de datos.
//
// R6: las ramas se escriben `{isMobile && <A/>}` / `{!isMobile && <B/>}`, nunca
// con ternario — el guard congela `fork_ternario` en 0. Modelo: Config.jsx:779.

import { useEffect, useMemo, useState } from 'react'
import { Plus, Search, X, SlidersHorizontal, Filter } from 'lucide-react'
import Modal from '../components/Modal'
import TickerSearch from '../components/TickerSearch'
import DateInput from '../components/DateInput'
import { fmtUsd as fmtUsdRaw, colorClass } from '../utils/format'
import { track } from '../utils/track'
import { useMoneyFormat, fmtConvertedRaw } from '../contexts/CurrencyContext'
import { useHistoricalMoney } from '../hooks/useHistoricalMoney'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import EmptyState from '../components/EmptyState'
import InfoTooltip from '../components/InfoTooltip'
import InsightLine from '../components/InsightLine'
import BottomSheet from '../components/mobile/BottomSheet'
import { api } from '../utils/api'
import { useIsMobile } from '../hooks/useIsMobile'
import AnalyzeButton from '../components/ai/AnalyzeButton'
import ExportCsvButton from '../components/plan/ExportCsvButton'
import { useToast } from '../components/Toast'
import { computeTradeStats } from '../utils/tradeStats'
import { opPnlUsd } from '../utils/assetPnl'
import TradesTable, { PAGE_SIZE } from '../components/operations/TradesTable'
import TradesFeed from '../components/operations/TradesFeed'
import MovementsTable, { MOV_PAGE_SIZE } from '../components/operations/MovementsTable'
import MovementsFeed from '../components/operations/MovementsFeed'
import {
  MOVEMENT_TYPES, GROUP_OPTIONS, buildGroups, buildPeriodOptions, enPeriodo,
} from '../components/operations/shared'

// pnl_usd arranca como string vacío (no 0) para que el form distinga
// "no completado" de "0 USD" — sin esto, el user que quiere cargar un trade
// rápido SÓLO con P&L (sin precios) y deja el campo en blanco, termina
// guardando 0 sin darse cuenta porque el value=0 era el default y "parece
// completado". Lo manejamos abajo en save(): vacío → null al backend.
const EMPTY = { date: new Date().toISOString().slice(0, 10), broker: '', asset: '', op_type: '', entry_price: '', exit_price: '', quantity: '', pnl_usd: '', pnl_pct: '', commissions: '' }

const RESULT_OPTIONS = [
  { id: 'all',    label: 'Todas' },
  { id: 'wins',   label: 'Ganadoras' },
  { id: 'losses', label: 'Perdedoras' },
]

// Los defaults de los filtros, en UN solo lugar: estado inicial, contador de
// filtros activos y los botones de reset se derivan de acá.
const FILTROS_INICIALES = { asset: '', broker: 'all', result: 'all', period: 'all' }

export default function Operations() {
  const isMobile = useIsMobile()
  // tab: 'trades' = operaciones cerradas con KPIs de P&L
  //      'all'    = historial unificado (trades + depósitos + retiros + …)
  // Un solo estado para las dos anchuras. El default sigue siendo por anchura
  // (la tabla abre en 'all', el feed en 'trades'), pero ahora se persiste igual
  // en las dos: antes el feed lo perdía en cada visita.
  // El default por anchura sale de `isMobile`, NUNCA de una medición de ancho
  // propia: el breakpoint tiene un solo dueño (useIsMobile) y el guard lo
  // verifica archivo por archivo. `useIsMobile` resuelve sincrónico en el primer
  // render, así que el inicializador perezoso lee el valor correcto.
  const [tab, setTab] = useState(() => localStorage.getItem('rendi_operations_tab') || (isMobile ? 'trades' : 'all'))
  useEffect(() => { localStorage.setItem('rendi_operations_tab', tab) }, [tab])
  // P&L realizado con el toggle global ARS/USD, SIEMPRE a FX histórico:
  // cada trade se convierte con el suyo (op.fx_to_usd stampeado > lookup por
  // op.date > tcBlue actual) y los agregados (KPIs, headers de grupo) suman los
  // valores YA convertidos — convert-then-sum, ver `sumConvertedAt`.
  // Antes los agregados usaban tcBlue de HOY: un grupo de un solo trade mostraba
  // un número distinto al de su propia fila (reporte real +$147.007 vs +$135.444).
  // `money` sigue para montos sin fecha propia (ej. header de columna).
  const money = useMoneyFormat()
  const histMoney = useHistoricalMoney()
  const fmtUsd = (v) => money.fmtMoney(v, { signed: false })

  const [ops, setOps] = useState([])
  // El feed tenía su propio gate de carga y lo perdió al unificar: sin él, la
  // rama angosta pinta "0 ops / +US$0,00" y un "sin resultados" que le echa la
  // culpa a los filtros mientras el fetch todavía viaja. La tabla nunca lo tuvo
  // (muestra su EmptyState de cartera vacía) y se deja como estaba.
  const [loadingOps, setLoadingOps] = useState(true)
  const [brokers, setBrokers] = useState([])
  const toast = useToast()
  // Borrados en curso: deshabilita el tacho mientras corre. Sin esto el doble-click
  // mandaba dos DELETE y el 2do terminaba en un error después de un borrado exitoso.
  const [busyDel, setBusyDel] = useState({})
  const [modal, setModal] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [filterAsset, setFilterAsset] = useState(FILTROS_INICIALES.asset)
  const [filterBroker, setFilterBroker] = useState(FILTROS_INICIALES.broker)
  const [filterResult, setFilterResult] = useState(FILTROS_INICIALES.result)
  // UN eje temporal. Antes eran dos que no se solapaban: la tabla tenía años
  // ('2026', '2025', …) y el feed ventanas relativas ('30d', '90d', '1y').
  // Sumarlos habría dejado combinaciones imposibles (año 2024 + últimos 30 días
  // = vacío garantizado). Nadie pierde nada: la tabla gana las ventanas y el
  // feed gana los años.
  const [period, setPeriod] = useState(FILTROS_INICIALES.period)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [page, setPage] = useState(0)
  // Agrupación del tab "Solo P/L". La tabla abre en 'asset' (1 fila por activo,
  // reduce ruido) y persiste la elección; el feed no tiene control de agrupado y
  // va siempre por día. Estado PROPIO de este tab — no se comparte con
  // MovementsView (que tiene su 'rendi_movements_group').
  const [groupBy, setGroupBy] = useState(() => localStorage.getItem('rendi_trades_group') || 'asset')
  useEffect(() => { localStorage.setItem('rendi_trades_group', groupBy) }, [groupBy])
  // Grupos expandidos (Set de keys). Click en la fila-resumen togglea su detalle.
  const [expandedGroups, setExpandedGroups] = useState(() => new Set())
  function toggleGroup(key) {
    setExpandedGroups(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  useEffect(() => {
    load()
    api.get('/brokers').then(b => setBrokers(b))
  }, [])

  async function load() {
    try {
      // `pnl_usd` de un cupón/amortización en un broker en pesos guarda PESOS (ver
      // utils/assetPnl.js). Se normaliza acá, en el borde, y no en el endpoint: el
      // formulario de edición vuelve a escribir `pnl_usd`, así que conserva el nativo
      // en `pnl_usd_native`. Sin esto un cupón de $370.524 era el "Mejor trade
      // US$370.524" (medido, usuario real 2026-08).
      const rows = await api.get('/operations')
      setOps((rows || []).map(o => ({ ...o, pnl_usd_native: o.pnl_usd, pnl_usd: opPnlUsd(o) })))
    }
    finally { setLoadingOps(false) }
  }
  function openAdd() {
    setForm({ ...EMPTY, broker: brokers[0]?.name ?? '' })
    setModal('add')
  }
  function openEdit(op) {
    // pnl_usd: si la op vino con null, lo mostramos como '' (no como "null"
    // string). Si es 0 deliberado, queda 0 visible en el input.
    setForm({
      ...op,
      entry_price: op.entry_price ?? '',
      exit_price: op.exit_price ?? '',
      quantity: op.quantity ?? '',
      pnl_usd: (op.pnl_usd_native ?? op.pnl_usd) ?? '',
      pnl_pct: op.pnl_pct ?? '',
      commissions: op.commissions ?? '',
      // El backend decide por la foto de reverso guardada en el alta, no por
      // este campo; acá es sólo para que el check se vea en el estado correcto.
      kind: esOpDeFuturos(op) ? 'futures' : null,
    })
    setModal('edit')
  }

  async function save() {
    const body = {
      ...form,
      entry_price: form.entry_price !== '' ? +form.entry_price : null,
      exit_price: form.exit_price !== '' ? +form.exit_price : null,
      quantity: form.quantity !== '' ? +form.quantity : null,
      // P&L USD: si el user lo deja vacío, mandamos null (no 0) — eso
      // significa "no registré la ganancia/pérdida". Backend distingue
      // null vs 0 explícito (un trade flat sí puede tener pnl_usd=0).
      pnl_usd: form.pnl_usd !== '' && form.pnl_usd !== null ? +form.pnl_usd : null,
      pnl_pct: form.pnl_pct !== '' ? +form.pnl_pct : null,
      commissions: form.commissions !== '' ? +form.commissions : 0,
      // 'futures' hace que el backend ACREDITE el P&L al efectivo del broker.
      // Sólo se manda cuando el usuario lo tildó: cualquier otra operación
      // conserva el comportamiento de siempre (registra P&L y no toca la plata).
      kind: form.kind === 'futures' ? 'futures' : null,
    }
    if (modal === 'edit') await api.put(`/operations/${form.id}`, body)
    else {
      await api.post('/operations', body)
      track('operation_added', {
        mode: body.op_type,
        only_pnl: body.entry_price == null && body.pnl_usd != null,
        broker: body.broker,
      })
    }
    setModal(null)
    load()
  }

  // Ofrece DESHACER de verdad. Cada borrado devuelve un `undo_token`; antes se
  // tiraba a la basura, así que el "podés deshacerlo" del confirm era mentira.
  function offerUndo(res, undoBase, msg) {
    const token = res?.undo_token
    if (!token) { toast.push(msg, { type: 'success' }); return }
    toast.push(msg, {
      type: 'success',
      duration: 12000,
      actionLabel: 'Deshacer',
      onAction: async () => {
        try {
          await api.post(`${undoBase}/${token}`)
          await load()
          toast.push('Listo, lo restauramos.', { type: 'success' })
        } catch (ex) {
          toast.push(ex?.message || 'No se pudo deshacer.', { type: 'error', duration: 8000 })
        }
      },
    })
  }

  // Firma única de borrado en las dos ramas: recibe el OBJETO. La tabla
  // pasaba `op.id` y el feed `op`; al compartir renderer hubo que elegir una.
  async function del(op) {
    const id = op?.id ?? op
    if (!confirm('¿Eliminar esta operación?\n\nSe recalculan tu P&L, rendimiento, métricas y la curva de evolución. La operación deja de contar en todos los cálculos.')) return
    setBusyDel(b => ({ ...b, [`op-${id}`]: true }))
    try {
      const res = await api.delete(`/operations/${id}`)
      await load()
      offerUndo(res, '/operations/undo', 'Operación borrada.')
    } catch (ex) {
      // El backend bloquea con mensaje claro los casos que aún no soporta
      // (manuales, bonos, activos con data manual mezclada).
      toast.push(ex?.message || 'No se pudo borrar la operación.', { type: 'error', duration: 8000 })
    } finally {
      setBusyDel(b => { const n = { ...b }; delete n[`op-${id}`]; return n })
    }
  }

  // Borrar TODO el historial de un activo (compras + ventas + renta fija, todos los
  // brokers). Alto blast radius → confirmación explícita que nombra el activo.
  // NO promete un número: `g.count` sale del grupo FILTRADO y solo cuenta ventas, así
  // que mentía. El total real lo devuelve el backend y lo mostramos después.
  async function delGroup(g) {
    const asset = g.key
    if (!confirm(
      `¿Borrar TODO el historial de ${asset}?\n\n` +
      `Se borran TODAS sus operaciones (compras, ventas y, si es un bono, sus cupones ` +
      `y amortizaciones) en TODOS tus brokers — no solo las que estás viendo ahora. ` +
      `${asset} deja de contar en tu P&L, rendimiento, métricas y la curva de evolución. ` +
      `Se recalcula todo. Vas a poder deshacerlo.`
    )) return
    setBusyDel(b => ({ ...b, [`grp-${asset}`]: true }))
    try {
      const res = await api.delete(`/assets/history?asset=${encodeURIComponent(asset)}`)
      await load()
      const n = res?.count
      offerUndo(res, '/assets/undo',
        `${asset} borrado${n ? ` (${n} ${n === 1 ? 'operación' : 'operaciones'})` : ''}.`)
    } catch (ex) {
      toast.push(ex?.message || 'No se pudo borrar el activo.', { type: 'error', duration: 8000 })
    } finally {
      setBusyDel(b => { const n = { ...b }; delete n[`grp-${asset}`]; return n })
    }
  }

  // KPIs sobre todas las ops, no las filtradas.
  // P&L Realizado: convert-then-sum (cada trade a SU FX histórico). Sumar los USD
  // y convertir el total al dólar de hoy re-expresaba ganancias viejas al MEP
  // actual — mismo bug que el header de grupo. `totalPnl` (USD crudo) se mantiene
  // solo para el TONO (color), que no debe depender del FX.
  const totalPnlDisp = useMemo(
    () => histMoney.sumConvertedAt(ops, o => (o.pnl_usd || 0)),
    [ops, histMoney.currency, histMoney.fxKey],
  )
  // Win rate: UNA definición, la del backend (utils/tradeStats). Acá se contaban
  // dividendos e intereses como ganadores y se dividía por ops.length (compras
  // incluidas), así que el mismo usuario veía 93% acá, 100% en mobile y 85% en
  // sus reportes. Ahora las tres dicen lo mismo.
  const { trades, wins, losses, winRate } = useMemo(() => computeTradeStats(ops), [ops])
  // Mejor trade: guardamos la OP entera (no el escalar) para formatearla con SU FX
  // histórico. El máximo se elige sobre el valor que se VA A MOSTRAR: en pesos el
  // ranking puede diferir del ranking en USD (un trade viejo con dólar barato
  // rinde menos pesos que uno nuevo con el mismo USD) → si eligiéramos por USD, el
  // "Mejor trade" podía quedar por debajo de una fila visible de la tabla.
  // El viejo `Math.max(..., o.pnl_usd || 0)` además mapeaba null→0 y con todas las
  // ops en pérdida mostraba "$0" (un trade inexistente).
  const bestTradeOp = useMemo(() => {
    let best = null, bestVal = -Infinity
    for (const o of ops) {
      if (o.pnl_usd == null || !Number.isFinite(o.pnl_usd)) continue
      const v = histMoney.convertedValue(o.pnl_usd, {
        stampedFx: o.fx_to_usd, rowCurrency: o.currency, dateIso: o.date,
      })
      if (v != null && v > bestVal) { bestVal = v; best = o }
    }
    return best
  }, [ops, histMoney.currency, histMoney.fxKey])

  // Patrones derivados de las operaciones — observaciones escaneables arriba de
  // la tabla. Cálculo inline (diagnostics.js espera el objeto `data` completo
  // del portfolio + rotación por severidad — overkill para 1-2 líneas fijas).
  const patterns = useMemo(() => {
    if (ops.length < 3) return []
    const out = []

    // (1) Activo más operado (cualquier op_type). Solo si hay líder claro.
    const countByAsset = {}
    for (const o of ops) {
      const a = (o.asset || '').trim()
      if (!a) continue
      countByAsset[a] = (countByAsset[a] || 0) + 1
    }
    const ranked = Object.entries(countByAsset).sort((a, b) => b[1] - a[1])
    if (ranked.length > 0 && ranked[0][1] >= 3 && (ranked.length === 1 || ranked[0][1] > ranked[1][1])) {
      out.push({ key: 'most_traded', asset: ranked[0][0], count: ranked[0][1] })
    }

    // (2) Racha ganadora más larga (cronológica, pnl_usd > 0 consecutivos).
    const chron = [...ops]
      .filter(o => o.date && o.pnl_usd != null)
      .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
    let best = 0, cur = 0
    for (const o of chron) {
      if (o.pnl_usd > 0) { cur++; if (cur > best) best = cur }
      else cur = 0
    }
    if (best >= 3) out.push({ key: 'win_streak', streak: best })

    return out
  }, [ops])
  const periodOptions = useMemo(() => buildPeriodOptions(ops), [ops])

  const filteredOps = useMemo(() => {
    const q = filterAsset.trim().toUpperCase()
    return ops.filter(o => {
      if (q && !(o.asset || '').toUpperCase().includes(q)) return false
      if (filterBroker !== 'all' && o.broker !== filterBroker) return false
      if (filterResult === 'wins' && !(o.pnl_usd > 0)) return false
      if (filterResult === 'losses' && !(o.pnl_usd < 0)) return false
      if (!enPeriodo(o.date, period)) return false
      return true
    })
  }, [ops, filterAsset, filterBroker, filterResult, period])

  const filtrosActuales = { asset: filterAsset, broker: filterBroker, result: filterResult, period }
  const filtersActiveCount = Object.keys(FILTROS_INICIALES)
    .filter(k => filtrosActuales[k] !== FILTROS_INICIALES[k]).length
  const filtersActive = filtersActiveCount > 0

  function restablecerFiltros() {
    setFilterAsset(FILTROS_INICIALES.asset)
    setFilterBroker(FILTROS_INICIALES.broker)
    setFilterResult(FILTROS_INICIALES.result)
    setPeriod(FILTROS_INICIALES.period)
  }

  // Reset a página 0 cuando cambian los filtros, el modo de agrupado, o el
  // dataset cambia de tamaño.
  useEffect(() => {
    setPage(0)
  }, [filterAsset, filterBroker, filterResult, period, groupBy, ops.length])

  // El feed no tiene control de agrupado: va siempre por día. No es un ternario
  // de RENDER (lo que R6 prohíbe), es el valor efectivo del modo.
  const groupByEfectivo = isMobile ? 'day' : groupBy
  const grouped = groupByEfectivo !== 'none'

  // Grupos sobre lo YA filtrado (filtramos y después agrupamos). `buildGroups`
  // es el mismo motor para la tabla y el feed desde la Fase 3.
  const groups = useMemo(
    () => (grouped ? buildGroups(filteredOps, groupByEfectivo) : []),
    [filteredOps, groupByEfectivo, grouped]
  )

  // Paginación SOLO en modo 'none' (lista plana), y por eso sólo en la tabla:
  // el feed nunca sale de 'day'. En modo agrupado mostramos todos los grupos.
  const totalPages = Math.max(1, Math.ceil(filteredOps.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages - 1)
  const pagedOps = useMemo(
    () => filteredOps.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE),
    [filteredOps, currentPage]
  )

  // R6: dos ramas, nunca un ternario de JSX. Esto es un ternario de VALOR.
  const shellClass = isMobile ? 'pb-8' : 'page-shell-wide'

  return (
    <div className={shellClass}>
      {!isMobile && (
        <PageHeader
          eyebrow="Tu actividad"
          title="Operaciones"
          subtitle={tab === 'trades'
            ? 'Historial de trades cerrados con P&L realizado.'
            : 'Todos los movimientos: trades, depósitos, retiros, dividendos y comisiones.'}
          action={
            <div className="flex items-center gap-2 flex-wrap">
              <AnalyzeButton screen="operations" subtitle="Tu historial completo" />
              <ExportCsvButton resource="operations" source="operations_header" variant="compact" />
              <button
                onClick={openAdd}
                className="inline-flex items-center gap-1.5 text-xs bg-data-violet/10 text-data-violet hover:bg-data-violet/15 border border-data-violet/30 px-3 py-1.5 rounded-sm transition-colors font-medium"
              >
                <Plus size={12} strokeWidth={2} /> Nueva operación
              </button>
            </div>
          }
        />
      )}

      {/* Tab switcher: Todos los movimientos vs solo Trades — mismo diseño
          que /posiciones y /analisis (filled pills + violet en activa). */}
      {!isMobile && (
        <div className="inline-flex flex-wrap gap-2 mb-5">
          <button
            onClick={() => setTab('all')}
            className={`inline-flex items-center gap-2 px-4 py-2.5 text-sm font-semibold rounded-md border transition-all ${
              tab === 'all'
                ? 'bg-data-violet/15 text-data-violet border-data-violet/40 shadow-sm'
                : 'bg-bg-1 text-ink-2 border-line hover:text-ink-0 hover:border-line-2 hover:bg-bg-2'
            }`}
          >
            Todos los movimientos
          </button>
          <button
            onClick={() => setTab('trades')}
            className={`inline-flex items-center gap-2 px-4 py-2.5 text-sm font-semibold rounded-md border transition-all ${
              tab === 'trades'
                ? 'bg-data-violet/15 text-data-violet border-data-violet/40 shadow-sm'
                : 'bg-bg-1 text-ink-2 border-line hover:text-ink-0 hover:border-line-2 hover:bg-bg-2'
            }`}
          >
            Solo P/L
          </button>
        </div>
      )}
      {isMobile && (
        <div className="px-4 pt-3">
          <div className="flex w-full rounded-sm border border-line/60 bg-bg-1 p-0.5 text-xs font-medium">
            <button
              onClick={() => setTab('trades')}
              className={`flex-1 py-1.5 rounded-sm transition-colors ${tab === 'trades' ? 'bg-bg-3 text-ink-0' : 'text-ink-3'}`}
            >
              Trades
            </button>
            <button
              onClick={() => setTab('all')}
              className={`flex-1 py-1.5 rounded-sm transition-colors ${tab === 'all' ? 'bg-bg-3 text-ink-0' : 'text-ink-3'}`}
            >
              Movimientos
            </button>
          </div>
        </div>
      )}

      {/* `onChanged` llega en LAS DOS anchuras: borrar un movimiento recalcula
          las operaciones del tab "Solo P/L", cuyos datos viven acá. Antes el
          feed lo montaba sin el prop y borrar en el celular no refrescaba nada. */}
      {tab === 'all' && <MovementsView onChanged={load} isMobile={isMobile} />}

      {tab === 'trades' && (
      <>
      {/* KPI strip denso */}
      {!isMobile && (
        <div className="border border-line rounded-xl bg-bg-1 flex flex-wrap mb-4">
          <KpiCell
            first
            label="P&L Realizado"
            value={fmtConvertedRaw(totalPnlDisp, histMoney.currency, { decimals: 2 })}
            tone={totalPnlDisp >= 0 ? 'pos' : 'neg'}
            sub="acumulado histórico"
          />
          {/* Sin trades cerrados no hay win rate: la celda se OCULTA. Antes
              mostraba "0%" en rojo, que le inventaba un fracaso al que sólo
              cobró dividendos o todavía no vendió nada. */}
          {winRate != null && (
            <KpiCell
              label="Win rate"
              value={`${(winRate * 100).toFixed(0)}%`}
              tone={winRate >= 0.5 ? 'pos' : 'neg'}
              sub={`${wins} ganadoras · ${losses} perdedoras · ${trades} cerradas`}
            />
          )}
          <KpiCell
            label="Operaciones"
            value={ops.length.toLocaleString('es-AR')}
            sub="total cerradas"
          />
          <KpiCell
            label="Mejor trade"
            value={bestTradeOp
              ? histMoney.fmtMoneyAt(bestTradeOp.pnl_usd, {
                  stampedFx: bestTradeOp.fx_to_usd, rowCurrency: bestTradeOp.currency,
                  dateIso: bestTradeOp.date, decimals: 2,
                })
              : '—'}
            tone={bestTradeOp && bestTradeOp.pnl_usd > 0 ? 'pos' : null}
            sub="P&L individual"
          />
        </div>
      )}

      {/* Header sticky con KPIs + filtros. El `top-[88px]` está calibrado a la
          altura del MobileTopBar, por eso vive acá y no adentro del feed. */}
      {isMobile && !loadingOps && (
        <header className="sticky top-[88px] z-20 bg-bg-0/95 backdrop-blur-md border-b border-line/40 px-4 pt-3 pb-3">
          <div className="flex items-baseline justify-between mb-3">
            <div>
              <div className="text-[12.5px] text-ink-2 leading-none mb-1 font-medium">
                P&L acumulado · {ops.length} ops
              </div>
              <div className={`text-xl font-medium tabular leading-none ${colorClass(totalPnlDisp)}`}>
                {fmtConvertedRaw(totalPnlDisp, histMoney.currency, { signed: true, decimals: 2 })}
              </div>
            </div>
            {winRate != null && (
              <div className="text-right">
                <div className="text-[12.5px] text-ink-2 leading-none mb-1 font-medium">
                  Win rate
                </div>
                <div className="text-xl font-medium tabular text-ink-0 leading-none">
                  {(winRate * 100).toFixed(0)}%
                </div>
                <div className="text-[10px] tabular text-ink-3 leading-none mt-1">
                  <span className="text-rendi-pos">{wins}W</span> · <span className="text-rendi-neg">{losses}L</span> · {trades} cerradas
                </div>
              </div>
            )}
          </div>

          <button
            onClick={() => setFiltersOpen(true)}
            className="w-full inline-flex items-center justify-between gap-2 bg-bg-2 border border-line/60 rounded-sm px-3 py-1.5 text-xs text-ink-2 hover:text-ink-0 hover:bg-bg-3 transition-colors"
          >
            <span className="flex items-center gap-1.5">
              <Filter size={11} strokeWidth={1.75} />
              Filtros
              {filtersActiveCount > 0 && (
                <span className="ml-1 px-1.5 py-0.5 rounded-sm bg-rendi-accent/20 text-rendi-accent text-[10px] tabular">
                  {filtersActiveCount}
                </span>
              )}
            </span>
            <span className="text-[12.5px] text-ink-2 font-medium">
              {periodOptions.find(p => p.id === period)?.label}
              {filterBroker !== 'all' && ` · ${filterBroker}`}
              {filterResult !== 'all' && ` · ${RESULT_OPTIONS.find(r => r.id === filterResult)?.label}`}
            </span>
          </button>

          {/* Los KPIs de arriba miden TODAS las ops; el feed de abajo, las
              filtradas. Sin este renglón no hay forma de ver que son dos
              universos — la tabla lo resuelve con su paginador. */}
          {ops.length > 0 && (
            <div className="mt-2 text-[12.5px] text-ink-3 tabular">
              {filteredOps.length} de {ops.length} operaciones
            </div>
          )}
        </header>
      )}

      {/* Strip de patrones — observaciones derivadas de las operaciones. */}
      {!isMobile && patterns.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-4">
          {patterns.map(p => (
            <InsightLine key={p.key} tone="neutral">
              {p.key === 'most_traded' && (
                <>
                  Operaste <strong className="font-semibold text-ink-0">{p.asset}</strong>{' '}
                  <strong className="font-semibold text-ink-0">{p.count} veces</strong> — más que cualquier otro activo.
                </>
              )}
              {p.key === 'win_streak' && (
                <>
                  Tu racha más larga: <strong className="font-semibold text-ink-0">{p.streak} ganadoras seguidas</strong>.
                </>
              )}
            </InsightLine>
          ))}
        </div>
      )}

      {/* Filtros — collapsable, abren con botón */}
      {!isMobile && ops.length > 0 && (
        <div className="mb-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setFiltersOpen(o => !o)}
                className={`inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-caps px-2.5 py-1.5 rounded-sm border transition-colors ${
                  filtersActive
                    ? 'border-rendi-pos/30 bg-rendi-pos/10 text-rendi-pos'
                    : 'border-line bg-bg-2 text-ink-2 hover:text-ink-0 hover:bg-bg-3'
                }`}
                aria-expanded={filtersOpen}
              >
                <SlidersHorizontal size={11} strokeWidth={2} aria-hidden="true" />
                Filtros
                {filtersActive && (
                  <span className="ml-1 inline-flex items-center justify-center min-w-[14px] h-[14px] px-1 text-[9px] rounded-sm bg-rendi-pos/20 text-rendi-pos tabular">
                    {filtersActiveCount}
                  </span>
                )}
              </button>
              {filtersActive && (
                <button
                  onClick={restablecerFiltros}
                  className="inline-flex items-center gap-1 text-[12.5px] text-ink-2 hover:text-ink-0 px-2 py-1 rounded-sm hover:bg-bg-2 transition-colors font-medium"
                >
                  <X size={11} strokeWidth={1.75} /> Limpiar
                </button>
              )}
            </div>
            <span className="text-[12.5px] text-ink-2 tabular font-medium">
              {filteredOps.length} de {ops.length}
            </span>
          </div>
          {filtersOpen && (
            <Panel padding="sm" className="mt-2">
              <div className="flex flex-wrap items-center gap-3">
                <div className="relative flex-1 min-w-[220px]">
                  <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3 pointer-events-none" strokeWidth={1.75} />
                  <input
                    value={filterAsset}
                    onChange={e => setFilterAsset(e.target.value)}
                    placeholder="Buscar activo (BTC, GGAL…)"
                    className="w-full bg-bg-2 border border-line rounded-sm pl-8 pr-3 py-1.5 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2"
                  />
                </div>
                <FilterPill label="Broker" value={filterBroker} onChange={setFilterBroker}
                  options={[{ id: 'all', label: 'Todos' }, ...brokers.map(b => ({ id: b.name, label: b.name }))]} />
                <FilterPill label="Resultado" value={filterResult} onChange={setFilterResult}
                  options={[{ id: 'all', label: 'Todos' }, { id: 'wins', label: 'Ganadoras' }, { id: 'losses', label: 'Perdedoras' }]} />
                <FilterPill label="Período" value={period} onChange={setPeriod} options={periodOptions} />
                <FilterPill label="Agrupar" value={groupBy} onChange={setGroupBy} options={GROUP_OPTIONS} />
              </div>
            </Panel>
          )}
        </div>
      )}

      {!isMobile && (
        <TradesTable
          ops={ops}
          filteredOps={filteredOps}
          pagedOps={pagedOps}
          groups={groups}
          grouped={grouped}
          groupBy={groupByEfectivo}
          histMoney={histMoney}
          expandedGroups={expandedGroups}
          onToggleGroup={toggleGroup}
          onEdit={openEdit}
          onDelete={del}
          onDeleteGroup={delGroup}
          busyDel={busyDel}
          onAdd={openAdd}
          page={currentPage}
          totalPages={totalPages}
          onPage={setPage}
        />
      )}

      {isMobile && loadingOps && (
        <div className="px-4 py-8 text-center text-ink-3 text-sm" aria-live="polite">
          Cargando operaciones…
        </div>
      )}
      {isMobile && !loadingOps && groups.length === 0 && (
        <div className="px-4 py-10">
          <EmptyState
            title="Sin operaciones en este filtro"
            description="Cambiá el período o limpiá los filtros para ver más."
            action={
              filtersActiveCount > 0 && (
                <button
                  onClick={restablecerFiltros}
                  className="text-xs text-data-blue hover:text-rendi-accent font-medium"
                >
                  Limpiar filtros
                </button>
              )
            }
          />
        </div>
      )}
      {isMobile && !loadingOps && groups.length > 0 && (
        <TradesFeed groups={groups} histMoney={histMoney} onDelete={del} />
      )}

      {/* Sheet de filtros — sólo la rama angosta. */}
      {isMobile && (
        <BottomSheet
          open={filtersOpen}
          onClose={() => setFiltersOpen(false)}
          eyebrow="Filtros"
          title="Refinar operaciones"
        >
          <div className="p-4 space-y-5">
            <FilterGroup label="Período" options={periodOptions} value={period} onChange={setPeriod} />
            <FilterGroup label="Resultado" options={RESULT_OPTIONS} value={filterResult} onChange={setFilterResult} />
            <FilterGroup
              label="Broker"
              options={[{ id: 'all', label: 'Todos' }, ...brokers.map(b => ({ id: b.name, label: b.name }))]}
              value={filterBroker}
              onChange={setFilterBroker}
            />

            <div className="pt-2 flex items-center gap-2">
              <button
                onClick={restablecerFiltros}
                className="flex-1 text-xs text-ink-2 hover:text-ink-0 border border-line/60 hover:bg-bg-2/60 rounded-sm py-2 transition-colors font-medium"
              >
                Restablecer
              </button>
              <button
                onClick={() => setFiltersOpen(false)}
                className="flex-1 text-xs bg-rendi-pos/10 text-rendi-pos border border-rendi-pos/30 hover:bg-rendi-pos/15 rounded-sm py-2 transition-colors font-medium"
              >
                Aplicar
              </button>
            </div>
          </div>
        </BottomSheet>
      )}

      {/* Alta/edición: sólo la rama ancha (el feed no tiene botón que lo abra). */}
      {!isMobile && modal && (
        <OpFormModal
          mode={modal}
          form={form}
          setForm={setForm}
          brokers={brokers}
          onSave={save}
          onClose={() => setModal(null)}
        />
      )}
      </>
      )}
    </div>
  )
}

// ─── Subcomponentes ──────────────────────────────────────────────────────────

// Chips de filtro del sheet mobile.
function FilterGroup({ label, options, value, onChange }) {
  return (
    <div>
      <div className="text-[12.5px] text-ink-2 mb-2 font-medium">
        {label}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {options.map(o => (
          <button
            key={o.id}
            onClick={() => onChange(o.id)}
            className={`text-xs px-3 py-1.5 rounded-sm border transition-colors ${
              value === o.id
                ? 'bg-rendi-accent/15 text-rendi-accent border-rendi-accent/40'
                : 'bg-bg-2 text-ink-2 border-line/60 hover:bg-bg-3 hover:text-ink-0'
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}
function KpiCell({ label, value, sub, tone, first }) {
  const valueColor =
    tone === 'pos' ? 'text-rendi-pos' :
    tone === 'neg' ? 'text-rendi-neg' :
    'text-ink-0'
  return (
    <div className={`px-4 py-3 flex-1 min-w-[140px] ${first ? '' : 'border-l border-line/50'}`}>
      <div className="text-[12.5px] text-ink-2 leading-none font-medium">{label}</div>
      <div className={`mt-2 font-medium tabular num leading-none text-2xl tracking-tight ${valueColor}`}>{value}</div>
      <div className="text-[12.5px] text-ink-2 mt-1.5 leading-none truncate font-medium">{sub}</div>
    </div>
  )
}

function FilterPill({ label, value, onChange, options }) {
  return (
    <label className="inline-flex items-center gap-1.5 text-xs">
      <span className="text-[12.5px] text-ink-2 font-medium">{label}</span>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="bg-bg-2 border border-line rounded-sm px-2 py-1 text-xs text-ink-1 font-mono focus:outline-none focus:border-ink-2"
      >
        {options.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    </label>
  )
}
// ¿Esta operación acreditó efectivo al crearse? El backend lo estampa en
// `undo_meta_json` (src='manual_futures') porque la fila sola no permite
// distinguir el camino. La API lo devuelve crudo, así que se parsea acá.
function esOpDeFuturos(op) {
  try {
    return JSON.parse(op?.undo_meta_json || '{}')?.src === 'manual_futures'
  } catch {
    return false
  }
}

// ─── Modal ───────────────────────────────────────────────────────────────────

function OpFormModal({ mode, form, setForm, brokers, onSave, onClose }) {
  const esFuturos = form.kind === 'futures'
  const inputClass = 'w-full bg-bg-2 border border-line rounded-sm px-2.5 py-1.5 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2'
  const labelClass = 'block text-[12.5px] text-ink-2 mb-1 font-medium'
  return (
    <Modal title={mode === 'edit' ? 'Editar operación' : 'Nueva operación'} onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelClass}>Fecha</label>
            <DateInput value={form.date} onChange={v => setForm(f => ({ ...f, date: v }))} />
          </div>
          <div>
            <label className={labelClass}>Broker</label>
            {brokers.length > 0 ? (
              <select value={form.broker} onChange={e => setForm(f => ({ ...f, broker: e.target.value }))} className={inputClass}>
                {brokers.map(b => <option key={b.id} value={b.name}>{b.name}</option>)}
              </select>
            ) : (
              <input value={form.broker} onChange={e => setForm(f => ({ ...f, broker: e.target.value }))} className={inputClass} />
            )}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelClass}>Activo</label>
            <TickerSearch
              value={form.asset}
              onChange={v => setForm(f => ({ ...f, asset: v }))}
              currency={brokers.find(b => b.name === form.broker)?.currency || 'USDT'}
            />
          </div>
          <div>
            <label className={labelClass}>Tipo</label>
            <input value={form.op_type} onChange={e => setForm(f => ({ ...f, op_type: e.target.value }))} className={inputClass} placeholder="LONG, SHORT, Futuros…" />
          </div>
        </div>
        {!esFuturos && (
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className={labelClass}>P. Entrada</label>
            <input type="number" step="any" value={form.entry_price} onChange={e => setForm(f => ({ ...f, entry_price: e.target.value }))} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>P. Salida</label>
            <input type="number" step="any" value={form.exit_price} onChange={e => setForm(f => ({ ...f, exit_price: e.target.value }))} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>Cantidad</label>
            <input type="number" step="any" value={form.quantity} onChange={e => setForm(f => ({ ...f, quantity: e.target.value }))} className={inputClass} />
          </div>
        </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelClass}>P&L (USD)</label>
            <input
              type="number"
              step="any"
              value={form.pnl_usd}
              onChange={e => setForm(f => ({ ...f, pnl_usd: e.target.value }))}
              className={inputClass}
              placeholder="Ej: 150 o -80"
            />
          </div>
          <div>
            <label className={labelClass}>Comisiones</label>
            <input type="number" step="any" value={form.commissions} onChange={e => setForm(f => ({ ...f, commissions: e.target.value }))} className={inputClass} placeholder="0" />
          </div>
        </div>
        {/* FUTUROS. Va explícito y no deducido del campo "Tipo" (que es texto
            libre): esto MUEVE PLATA, y no puede depender de cómo se escribió una
            palabra. Un usuario cerró un futuro con +47 USDT, no encontró dónde
            cargarlo y registró solo el P&L — le quedó el efectivo 47 dólares corto. */}
        <div className="flex items-start gap-2.5 rounded-sm border border-line bg-bg-1 px-3 py-2.5">
          <input
            id="op-es-futuros"
            type="checkbox"
            checked={esFuturos}
            onChange={e => {
              const on = e.target.checked
              setForm(f => ({
                ...f,
                kind: on ? 'futures' : null,
                // el tipo es sólo la etiqueta que se ve en la tabla
                op_type: on && !f.op_type ? 'Futuros' : f.op_type,
                // precios y cantidad no aplican a un resultado de futuros
                ...(on ? { entry_price: '', exit_price: '', quantity: '' } : {}),
              }))
            }}
            className="mt-0.5 accent-data-violet cursor-pointer"
          />
          <div className="text-[12.5px] leading-tight flex-1 min-w-0">
            <div className="flex items-center gap-1.5">
              <label htmlFor="op-es-futuros" className="font-semibold text-ink-0 cursor-pointer">
                Resultado de futuros
              </label>
              {/* Fuera del <label> a propósito: adentro, el click en el (?) toggleaba
                  el check en vez de abrir la explicación. */}
              {/* side="top": el cuerpo del modal tiene overflow-y auto y termina
                  justo debajo de este bloque — abriendo hacia abajo se recortaban
                  las últimas líneas (medido: el tooltip llegaba a 865 y el
                  contenedor cortaba en 764). */}
              <InfoTooltip label="Cómo impacta en tus números" align="left" side="top">
                <p className="font-semibold text-ink-0">Sube tu capital como GANANCIA.</p>
                <p>
                  El resultado entra al efectivo del broker, así que el total de tu
                  cartera sube (o baja) por ese monto.
                </p>
                <p>
                  Ese mismo monto se cuenta como <strong>ganancia</strong>: suma al
                  P&L realizado del mes y del broker.
                </p>
                <p className="text-ink-3">
                  No suma al capital aportado — esa plata no la pusiste, la ganaste.
                  Por eso mejora tu rendimiento, en vez de dejarlo igual como haría
                  cargarlo de depósito.
                </p>
              </InfoTooltip>
            </div>
            <p className="text-ink-2 font-medium">
              Suma el P&L al efectivo del broker, porque esa plata ya está en tu cuenta.
              No cuenta como capital aportado.
            </p>
          </div>
        </div>

        <p className="text-[12.5px] text-ink-2 leading-tight font-medium">
          Atajo: si solo querés registrar la ganancia/pérdida (sin precios ni cantidad), completá únicamente P&L USD.
        </p>
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-[12.5px] text-ink-3 hover:text-ink-0 px-3 py-1.5 transition-colors font-medium">
            Cancelar
          </button>
          <button onClick={onSave} className="text-[12.5px] bg-rendi-pos/10 text-rendi-pos hover:bg-rendi-pos/15 border border-rendi-pos/30 px-3 py-1.5 rounded-sm transition-colors font-medium">
            Guardar
          </button>
        </div>
      </div>
    </Modal>
  )
}


// ═══════════════════════════════════════════════════════════════════════════
// MOVEMENTS VIEW — historial unificado (trades + cash flows + dividendos + ...)
// ═══════════════════════════════════════════════════════════════════════════
// Consume /api/movements (endpoint que junta operations + import_normalized_tx
// + monthly_entries en una lista cronológica). Filtros por tipo y broker.
// KPIs adaptativos según el filtro de tipo seleccionado.
//
// Sources del backend:
//   • 'manual' → operations / positions cargadas a mano (editables, pero
//     desde acá NO editamos — el user va a /operaciones?tab=trades)
//   • 'import' → vinieron de un CSV (read-only)
//   • 'monthly' → depósitos/retiros agregados mensualmente en /mensual

// ─── Movimientos ─────────────────────────────────────────────────────────────
// `onChanged` = el load() del padre. Borrar acá cambia también las operaciones del
// tab 'Solo P/L', cuyos datos viven en el padre y se cargan una sola vez al montar:
// sin avisarle, la operación borrada seguía visible ahí (y en sus KPIs) hasta recargar.
// Desde la Fase 3 el prop llega en LAS DOS anchuras (el feed lo montaba sin él).
function MovementsView({ onChanged, isMobile }) {
  // Fase B: formatter atado al toggle global ARS/USD. Lo bajamos a
  // computeMovementKpis y a los renderers vía props para evitar shadow.
  // Phase C audit fix H1: el HM (historical money) se usa en cada fila
  // individual (cada movimiento tiene su date). El P&L de los headers de grupo
  // también va por HM (convert-then-sum) para que coincida con sus filas. Los
  // KPIs de montos (totales / promedios) siguen con `money`.
  const money = useMoneyFormat()
  const histMoney = useHistoricalMoney()
  const fmtUsd = (v) => money.fmtMoney(v, { signed: false })
  const [movements, setMovements] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filterType, setFilterType] = useState('all')
  const [filterBroker, setFilterBroker] = useState('all')
  const [filterYear, setFilterYear] = useState('all')
  const [page, setPage] = useState(0)
  // Agrupación de la lista. 'asset' por defecto (reduce ruido). Persistido en
  // localStorage para respetar la preferencia del user entre sesiones. El feed
  // no tiene control de agrupado: va siempre por día.
  const [groupBy, setGroupBy] = useState(() => localStorage.getItem('rendi_movements_group') || 'asset')
  useEffect(() => { localStorage.setItem('rendi_movements_group', groupBy) }, [groupBy])
  // Grupos expandidos (Set de keys). Mismo patrón que expandedTickers en
  // Positions: click en la fila-resumen togglea el despliegue de sus filas.
  const [expandedGroups, setExpandedGroups] = useState(() => new Set())
  function toggleGroup(key) {
    setExpandedGroups(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  const [deletingId, setDeletingId] = useState(null)
  const [busyGroup, setBusyGroup] = useState({})
  const toast = useToast()
  // Borrar TODO el historial de un activo desde acá, sin tener que entrar al activo.
  // Mismo endpoint (y misma cascada) que el tacho de grupo de "Solo P/L".
  async function delGroup(g) {
    const asset = g.key
    if (!confirm(
      `¿Borrar TODO el historial de ${asset}?\n\n` +
      `Se borran TODAS sus operaciones (compras, ventas y, si es un bono, sus cupones ` +
      `y amortizaciones) en TODOS tus brokers — no solo las que estás viendo ahora. ` +
      `${asset} deja de contar en tu P&L, rendimiento, métricas y la curva de evolución. ` +
      `Se recalcula todo. Vas a poder deshacerlo.`
    )) return
    setBusyGroup(b => ({ ...b, [asset]: true }))
    try {
      const res = await api.delete(`/assets/history?asset=${encodeURIComponent(asset)}`)
      await load()
      onChanged?.()
      const n = res?.count
      const msg = `${asset} borrado${n ? ` (${n} ${n === 1 ? 'operación' : 'operaciones'})` : ''}.`
      if (res?.undo_token) {
        toast.push(msg, {
          type: 'success', duration: 12000, actionLabel: 'Deshacer',
          onAction: async () => {
            try {
              await api.post(`/assets/undo/${res.undo_token}`)
              await load()
              onChanged?.()
              toast.push('Listo, lo restauramos.', { type: 'success' })
            } catch (ex) {
              toast.push(ex?.message || 'No se pudo deshacer.', { type: 'error', duration: 8000 })
            }
          },
        })
      } else {
        toast.push(msg, { type: 'success' })
      }
    } catch (ex) {
      toast.push(ex?.message || 'No se pudo borrar el activo.', { type: 'error', duration: 8000 })
    } finally {
      setBusyGroup(b => { const n = { ...b }; delete n[asset]; return n })
    }
  }

  async function load() {
    setLoading(true)
    try {
      setMovements(await api.get('/movements') || [])
      setError(null)
    } catch (ex) {
      setError(ex?.message || 'No pudimos cargar los movimientos.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  // Borrado de UN movimiento (cash-flows) con cascada backend. Confirma → borra →
  // refetch de /movements. Los KPIs de la página se recomputan solos; el gráfico
  // del dashboard/evolución se corrige al navegar/recargar (lo lee del backend).
  async function handleDelete(m) {
    const label = { DEPOSIT: 'depósito', WITHDRAW: 'retiro', DIVIDEND: 'dividendo', INTEREST: 'interés', FEE: 'comisión', IMPUESTO: 'impuesto', BUY: 'compra', SELL: 'venta' }[m.type] || 'movimiento'
    const isTrade = m.type === 'BUY' || m.type === 'SELL'
    const asset = isTrade && m.asset ? ` de ${m.asset}` : ''
    // Al FX de SU fecha, el MISMO que muestra la fila que se está por borrar. Si
    // el diálogo dijera un número y la fila otro, el usuario no sabría cuál está
    // borrando. Lo tenía el feed y se perdió al unificar los dos handlers; la
    // tabla venía con `fmtUsd` (dólar de hoy), o sea contradecía a sus propias
    // filas desde antes. Ahora las dos ramas dicen lo mismo que su fila.
    const monto = m.amount_usd
      ? ` (${histMoney.fmtMoneyAt(m.amount_usd, { stampedFx: m.fx_to_usd, rowCurrency: m.currency, dateIso: m.date, decimals: 2 })})`
      : ''
    // Cierre a costo de una foto de tenencia: NO es una venta, y sacarlo REABRE la
    // posición con su costo original. Si le decimos "borrar" el usuario cree que
    // pierde el activo — es exactamente al revés.
    if (m.transfer_out) {
      if (!window.confirm(
        `¿Reabrir ${m.asset || 'la posición'}?\n\n` +
        `Esta fila no es una venta tuya: la generó una foto de tenencia para cerrar ` +
        `${m.asset || 'el activo'} porque la foto no lo listaba. Al sacarla, la posición ` +
        `vuelve a tu cartera con su costo original.\n\n` +
        `No se toca el efectivo (ese cierre no movió plata). Vas a poder deshacerlo.`
      )) return
    } else {
      const efecto = isTrade
        ? 'Se recalcula todo: cartera, P&L, rendimiento, capital aportado y la evolución. Deja de contar en todos los cálculos.'
        : 'Se recalculan tu cartera, el capital aportado y la evolución. La operación deja de contar en todos los cálculos.'
      if (!window.confirm(`¿Borrar ${label}${asset}${monto}?\n\n${efecto}`)) return
    }
    const okMsg = m.transfer_out
      ? `${m.asset || 'La posición'} volvió a tu cartera.`
      : `Se borró la ${label}${asset}.`
    setDeletingId(m.id)
    try {
      const res = await api.delete(`/movements/${encodeURIComponent(m.id)}`)
      await load()
      onChanged?.()
      // Los trades devuelven token de deshacer (cascada reversible). Los cash-flows
      // todavía no: ahí solo confirmamos, sin prometer nada que no exista.
      const token = res?.undo_token
      if (token) {
        const base = m.type === 'BUY' || m.type === 'SELL' ? '/operations/undo' : null
        if (base) {
          toast.push(okMsg, {
            type: 'success', duration: 12000, actionLabel: 'Deshacer',
            onAction: async () => {
              try {
                await api.post(`${base}/${token}`)
                await load()
                onChanged?.()
                toast.push(m.transfer_out ? 'Listo, volvimos atrás: el cierre está de nuevo.'
                                          : 'Listo, lo restauramos.', { type: 'success' })
              } catch (ex) {
                toast.push(ex?.message || 'No se pudo deshacer.', { type: 'error', duration: 8000 })
              }
            },
          })
          return
        }
      }
      toast.push(okMsg, { type: 'success' })
    } catch (ex) {
      toast.push(ex?.message || 'No se pudo borrar el movimiento.', { type: 'error', duration: 8000 })
    } finally {
      setDeletingId(null)
    }
  }

  // Reset página al cambiar filtros o el modo de agrupación.
  useEffect(() => { setPage(0) }, [filterType, filterBroker, filterYear, groupBy])

  const filtered = useMemo(() => {
    return movements.filter(m => {
      if (filterType !== 'all' && m.type !== filterType) return false
      if (filterBroker !== 'all' && m.broker !== filterBroker) return false
      if (filterYear !== 'all' && !(m.date || '').startsWith(filterYear)) return false
      return true
    })
  }, [movements, filterType, filterBroker, filterYear])

  // KPIs adaptativos según filtro. fmtUsd se pasa explícito para que
  // computeMovementKpis no dependa del scope module-level (que ya quedó
  // aliased a fmtUsdRaw — desconectado del toggle global).
  // Comisiones TOTALES del scope broker/año (SIN filtrar por tipo, para que
  // clickear el chip COMISIONES no cambie el número): FEE explícitos (amount_usd)
  // + comisión EMBEBIDA en cada trade (fees_usd — Balanz la trae dentro del
  // Importe). Antes la card sumaba solo los FEE explícitos → subcontaba fuerte
  // (santi veía US$24 en vez de ~US$527).
  //
  // Espeja /api/insights/commissions — y desde 2026-09-04 eso es literal: aquel
  // endpoint suma ESTAS MISMAS filas (`_build_movements`) con este criterio, en
  // vez de correr su propia query. Antes el comentario lo afirmaba pero era
  // falso: el endpoint sólo veía lo importado y a quien cargaba a mano le
  // mostraba ~0 mientras esta card mostraba el total real.
  //
  // Se sigue sumando acá (y no se consume el endpoint) porque este número
  // respeta los filtros de broker/año, que el endpoint no conoce. Si tocás el
  // criterio, tocá los dos: hay un test que los compara
  // (test_monto_venta_ars.py::MetricasYMovimientosCoinciden).
  const commTotalUsd = useMemo(() => {
    const scoped = movements.filter(m =>
      (filterBroker === 'all' || m.broker === filterBroker) &&
      (filterYear === 'all' || (m.date || '').startsWith(filterYear)))
    const loose = scoped.reduce((s, m) => m.type === 'FEE' ? s + (m.amount_usd || 0) : s, 0)
    const embedded = scoped.reduce((s, m) =>
      (m.type !== 'FEE' && m.type !== 'IMPUESTO') ? s + (m.fees_usd || 0) : s, 0)
    return loose + embedded
  }, [movements, filterBroker, filterYear])

  const kpis = useMemo(() => computeMovementKpis(filtered, filterType, fmtUsd, commTotalUsd), [filtered, filterType, fmtUsd, commTotalUsd])

  const brokersAvailable = useMemo(() => {
    const set = new Set(movements.map(m => m.broker).filter(Boolean))
    return [...set].sort()
  }, [movements])

  const yearsAvailable = useMemo(() => {
    const set = new Set(movements.map(m => (m.date || '').slice(0, 4)).filter(Boolean))
    return [...set].sort().reverse()
  }, [movements])

  // El feed va siempre por día; la tabla respeta su pill "Agrupar".
  const groupByEfectivo = isMobile ? 'day' : groupBy
  const grouped = groupByEfectivo !== 'none'

  // Grupos por día / activo / mes (sobre lo YA filtrado — filtramos y después
  // agrupamos, como pide el spec). Vacío en modo 'none'.
  const groups = useMemo(
    () => (grouped ? buildGroups(filtered, groupByEfectivo) : []),
    [filtered, groupByEfectivo, grouped]
  )

  // DECISIÓN PAGINACIÓN: la paginación con MOV_PAGE_SIZE aplica SOLO en modo
  // 'none' (lista plana). En modo agrupado mostramos TODOS los grupos sin
  // paginar — los grupos suelen ser pocos (1 por activo o 1 por mes) y paginar
  // sobre grupos partiría la tabla-resumen de forma confusa. Las filas de
  // detalle dentro de cada grupo tampoco se paginan (se ven al expandir).
  const totalPages = Math.max(1, Math.ceil(filtered.length / MOV_PAGE_SIZE))
  const currentPage = Math.min(page, totalPages - 1)
  const pageRows = grouped
    ? filtered
    : filtered.slice(currentPage * MOV_PAGE_SIZE, (currentPage + 1) * MOV_PAGE_SIZE)

  if (loading) {
    return <div className="text-center py-10 text-ink-3 text-sm" aria-live="polite">Cargando movimientos…</div>
  }
  if (error) {
    return <div className="border border-rendi-neg/30 bg-rendi-neg/[0.06] rounded p-4 text-sm text-rendi-neg">{error}</div>
  }

  return (
    <>
      {/* KPI strip adaptativo */}
      {!isMobile && (
        <div className="border border-line rounded-xl bg-bg-1 flex flex-wrap mb-4">
          {kpis.map((k, i) => (
            <KpiCell key={k.label} first={i === 0} label={k.label} value={k.value} sub={k.sub} tone={k.tone} />
          ))}
        </div>
      )}

      {/* Selector de tipo (pills) — escaneable */}
      {!isMobile && (
        <div className="flex items-center gap-1.5 flex-wrap mb-3">
          {MOVEMENT_TYPES.map(t => {
            const Icon = t.icon
            const count = t.id === 'all' ? movements.length : movements.filter(m => m.type === t.id).length
            if (t.id !== 'all' && count === 0) return null
            const active = filterType === t.id
            return (
              <button
                key={t.id}
                onClick={() => setFilterType(t.id)}
                className={`inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-caps px-2.5 py-1.5 rounded-sm border transition-colors ${
                  active
                    ? 'border-data-violet/40 bg-data-violet/10 text-data-violet'
                    : 'border-line bg-bg-2 text-ink-2 hover:text-ink-0 hover:bg-bg-3'
                }`}
              >
                <Icon size={11} strokeWidth={2} aria-hidden="true" />
                {t.label}
                <span className="ml-1 tabular text-[10px] opacity-70">{count}</span>
              </button>
            )
          })}
        </div>
      )}

      {/* Filtros secundarios (broker, año) + pill Agrupar */}
      {!isMobile && (
        <div className="flex items-center gap-2 flex-wrap mb-3">
          {brokersAvailable.length > 1 && (
            <select
              value={filterBroker}
              onChange={e => setFilterBroker(e.target.value)}
              className="text-[12.5px] bg-bg-2 border border-line rounded-sm px-2.5 py-1.5 text-ink-2 font-medium"
            >
              <option value="all">Todos los brokers</option>
              {brokersAvailable.map(b => <option key={b} value={b}>{b}</option>)}
            </select>
          )}
          {yearsAvailable.length > 1 && (
            <select
              value={filterYear}
              onChange={e => setFilterYear(e.target.value)}
              className="text-[12.5px] bg-bg-2 border border-line rounded-sm px-2.5 py-1.5 text-ink-2 font-medium"
            >
              <option value="all">Todos los años</option>
              {yearsAvailable.map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          )}
          <FilterPill label="Agrupar" value={groupBy} onChange={setGroupBy} options={GROUP_OPTIONS} />
          <span className="text-[11px] text-ink-3 font-mono">
            {filtered.length === movements.length
              ? `${movements.length} movimientos`
              : `${filtered.length} de ${movements.length}`}
          </span>
        </div>
      )}

      {!isMobile && (
        <MovementsTable
          movements={movements}
          filtered={filtered}
          pageRows={pageRows}
          groups={groups}
          grouped={grouped}
          groupBy={groupByEfectivo}
          histMoney={histMoney}
          currency={money.currency}
          expandedGroups={expandedGroups}
          onToggleGroup={toggleGroup}
          onDelete={handleDelete}
          onDeleteGroup={delGroup}
          deletingId={deletingId}
          busyGroup={busyGroup}
          page={currentPage}
          totalPages={totalPages}
          onPage={setPage}
        />
      )}

      {/* El guard mira `groups`, no `movements`: la rama angosta no renderiza los
          filtros de esta vista, así que un filtro puesto en la tabla (tipo /
          broker / año) llega hasta acá. Mirando `movements` el feed pintaba un
          <ul> vacío, sin decir por qué. */}
      {isMobile && movements.length === 0 && (
        <div className="px-4 py-10">
          <EmptyState title="Sin movimientos" description="Acá van tus depósitos, retiros, dividendos, intereses y comisiones." />
        </div>
      )}
      {isMobile && movements.length > 0 && filtered.length < movements.length && (
        <div className="flex items-center justify-between gap-2 px-4 py-2 text-[12.5px] text-ink-3 border-b border-line/30">
          <span className="tabular">{filtered.length} de {movements.length} movimientos</span>
          <button
            onClick={() => { setFilterType('all'); setFilterBroker('all'); setFilterYear('all') }}
            className="text-data-blue hover:text-rendi-accent font-medium"
          >
            Limpiar filtros
          </button>
        </div>
      )}
      {isMobile && movements.length > 0 && groups.length === 0 && (
        <div className="px-4 py-10">
          <EmptyState title="No hay movimientos" description="No se encontraron movimientos con los filtros aplicados." />
        </div>
      )}
      {isMobile && groups.length > 0 && (
        <MovementsFeed
          groups={groups}
          histMoney={histMoney}
          onDelete={handleDelete}
          deletingId={deletingId}
        />
      )}
    </>
  )
}
// Compute KPI strip dinámico. Cada filtro de tipo tiene su set propio de
// métricas relevantes.
//
// SEMÁNTICA "Aportado Neto" (vista all):
// El KPI principal cuando el user mira "Todos los movimientos" es el NETO
// (deposits − withdrawals), no el bruto de cada lado. Razón:
//   • Algunos brokers clasifican P2P trades como DEPOSIT en el CSV. Un user
//     que hace flips (compra USDT con ARS + venta inmediata por ARS) genera
//     $X en deposits Y $X en withdrawals — el bruto infla 2× sin que cambie
//     el capital aportado. El NETO refleja capital nuevo real.
//   • Coincide exactamente con "Capital Aportado" del Dashboard, evitando
//     que el user vea dos números distintos en pantallas distintas.
// El bruto sigue accesible filtrando por DEPÓSITOS o RETIROS individualmente
// (en esa vista mostramos bruto + promedio, que es lo que tiene sentido ahí).
function computeMovementKpis(rows, filterType, fmtUsd, commTotalUsd = 0) {
  const sumByType = (t) => rows.filter(r => r.type === t).reduce((s, r) => s + (r.amount_usd || 0), 0)
  const countByType = (t) => rows.filter(r => r.type === t).length

  if (filterType === 'DEPOSIT' || filterType === 'WITHDRAW') {
    const t = filterType
    const total = sumByType(t)
    const count = countByType(t)
    return [
      {
        label: `Total ${t === 'DEPOSIT' ? 'depositado' : 'retirado'}`,
        value: fmtUsd(total),
        tone: t === 'DEPOSIT' ? 'pos' : 'neg',
        sub: `${count} eventos · bruto histórico`,
      },
      {
        label: 'Promedio',
        value: count > 0 ? fmtUsd(total / count) : '—',
        sub: 'por evento',
      },
    ]
  }
  if (filterType === 'DIVIDEND' || filterType === 'INTEREST') {
    return [
      { label: `Total ${filterType === 'DIVIDEND' ? 'dividendos' : 'intereses'}`, value: fmtUsd(sumByType(filterType)), tone: 'pos', sub: `${countByType(filterType)} pagos` },
    ]
  }
  if (filterType === 'FEE') {
    return [
      { label: 'Total comisiones', value: fmtUsd(commTotalUsd), tone: commTotalUsd > 0 ? 'neg' : null, sub: `${countByType('FEE')} explícitas + embebidas en trades` },
    ]
  }

  // Vista "Todos" o por trade type — KPI principal es el NETO
  const dep = sumByType('DEPOSIT')
  const wit = sumByType('WITHDRAW')
  const neto = dep - wit
  const depCount = countByType('DEPOSIT')
  const witCount = countByType('WITHDRAW')
  const dividendos = sumByType('DIVIDEND') + sumByType('INTEREST')
  const comisiones = commTotalUsd  // FEE explícitos + embebidas en trades (no solo los FEE sueltos)
  return [
    {
      label: 'Aportado neto',
      value: fmtUsd(neto),
      tone: neto > 0 ? 'pos' : neto < 0 ? 'neg' : null,
      sub: `${depCount} depósitos · ${witCount} retiros`,
    },
    { label: 'Cobrado',    value: fmtUsd(dividendos), tone: dividendos > 0 ? 'pos' : null, sub: 'dividendos + intereses' },
    { label: 'Comisiones', value: fmtUsd(comisiones), tone: comisiones > 0 ? 'neg' : null, sub: 'fees totales (incl. embebidas)' },
  ]
}
