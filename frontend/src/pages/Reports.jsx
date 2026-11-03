// Reports — timeline operativa de Rendi (V3: tabs Día/Semana/Mes/Año).
// ════════════════════════════════════════════════════════════════════════════
// Estructura:
//   1. Header compacto (eyebrow + título + broker selector)
//   2. PerformanceCalendar — KPI strip + heatmap anual de meses
//   3. PeriodTabs: Día / Semana / Mes / Año
//   4. Lista de períodos: en curso arriba + históricos abajo, cards expandibles
//
// Decisión: replace MonthlyTable+desglose-semanal por tabs limpias estilo Braja.
// Cada tab fetcha N períodos hacia atrás y los renderiza como cards consistentes.

import { useState, useMemo, useEffect, Fragment } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import EmptyState from '../components/EmptyState'
import { Loader2, FileText, AlertTriangle, ChevronDown, ChevronUp, ArrowRight } from 'lucide-react'
import useReportsTimeline from '../hooks/useReportsTimeline'
import useReportYears from '../hooks/useReportYears'
import BrokerSelector from '../components/reports/BrokerSelector'
import MonthCard from '../components/reports/MonthCard'
import PerformanceCalendar from '../components/reports/PerformanceCalendar'
import WeeklyStrip from '../components/reports/WeeklyStrip'
import AnalyzeButton from '../components/ai/AnalyzeButton'
import LockedSection from '../components/plan/LockedSection'
import ExportCsvButton from '../components/plan/ExportCsvButton'
import { usePlanFeatures } from '../hooks/usePlanFeatures'
import { api } from '../utils/api'
import ModoRendimiento from '../components/ModoRendimiento'
import { useCurrency } from '../contexts/CurrencyContext'
import { useModoRendimiento } from '../contexts/ModoRendimientoContext'
import { PesosDelPeriodoProvider, usePesosDelPeriodo } from '../hooks/usePesosDelPeriodo'
import { hoyISO, fechaISO } from '../utils/fecha'
import { claveSemanaISO } from '../utils/semanas'
import { pctVar, pctColor, pctVarSign, ppVarFino, montoColor, montoEsCero } from '../utils/format'
import { OCULTO } from '../contexts/PrivacyContext'
import { taparMontosEnTodo } from '../utils/ocultarSaldos'

// ─── Helpers de fecha / keys ─────────────────────────────────────────────────

function todayIso() {
  return hoyISO()
}

function isoWeekKey(d = new Date()) {
  // La cuenta vive en utils/semanas (y tiene tests). Acá estaba escrita a mano,
  // y era la única copia hasta que la tira semanal necesitó la misma semana:
  // dos copias de "qué semana es hoy" es exactamente como empiezan las pantallas
  // que muestran dos números distintos del mismo período.
  return claveSemanaISO(fechaISO(d))
}

function monthKey(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function yearKey(d = new Date()) {
  return String(d.getFullYear())
}

function addDays(iso, n) {
  const d = new Date(iso + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

function addWeeks(weekKey, n) {
  // weekKey: "YYYY-Wnn" → restamos n*7 días a un día representativo (lunes)
  const [y, w] = weekKey.split('-W').map(Number)
  // ISO week 1 = semana del primer jueves del año
  const jan4 = new Date(Date.UTC(y, 0, 4))
  const monday = new Date(jan4)
  monday.setUTCDate(jan4.getUTCDate() - ((jan4.getUTCDay() + 6) % 7))
  monday.setUTCDate(monday.getUTCDate() + (w - 1 + n) * 7)
  return isoWeekKey(monday)
}

function addMonths(monthK, n) {
  const [y, m] = monthK.split('-').map(Number)
  const total = y * 12 + (m - 1) + n
  const ny = Math.floor(total / 12)
  const nm = (total % 12) + 1
  return `${ny}-${String(nm).padStart(2, '0')}`
}

// ─── Hook: data por tab ──────────────────────────────────────────────────────
//
// Devuelve la lista de períodos del tab activo, con el `current` primero y
// los históricos abajo. Estrategia por tab:
//   - month: usa useReportsTimeline (que ya devuelve 12 meses con metrics+narrative)
//   - week:  aplana children de los meses del timeline (semanas embedded)
//   - day:   fetches puntuales a /api/reports/period/day/{key} (últimos 7 días)
//   - year:  fetches puntuales a /api/reports/period/year/{key} (años visibles)

function usePeriodItems(tab, broker, timelineData, modo, moneda) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false

    // Reset items y error al cambiar tab/broker — evita ver data stale
    // mientras carga la nueva. (Mes mantiene su lista hasta resetear con
    // nueva data porque viene sync del hook timeline).
    if (tab !== 'month') {
      setItems([])
    }
    setError(null)

    async function load() {
      if (tab === 'month') {
        const all = []
        for (const g of timelineData.yearGroups || []) {
          for (const m of g.months) all.push(m)
        }
        if (!cancelled) setItems(all)
        return
      }

      let endpoint = null
      if (tab === 'week')      endpoint = `/reports/period/week/${isoWeekKey()}`
      else if (tab === 'day')  endpoint = `/reports/period/day/${todayIso()}`
      else if (tab === 'year') endpoint = `/reports/period/year/${new Date().getFullYear()}`
      if (!endpoint) return

      setLoading(true)
      try {
        const result = await api.get(
          `${endpoint}?broker=${encodeURIComponent(broker)}`
          + `&modo=${encodeURIComponent(modo)}&moneda=${encodeURIComponent(moneda)}`,
          { signal: controller.signal },
        )
        if (cancelled) return
        setItems(result ? [result] : [])
      } catch (ex) {
        if (cancelled || ex.name === 'AbortError') return
        // Distinguir "sin data" (404/empty) de "error de red".
        // Mensaje genérico — el user puede retry.
        setError(ex?.message || 'No pudimos cargar el período. Reintentá en un momento.')
        setItems([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true; controller.abort() }
  }, [tab, broker, modo, moneda, timelineData.yearGroups])

  return { items, loading, error }
}

// ─── Reports root ────────────────────────────────────────────────────────────

export default function Reports() {
  const [broker, setBroker] = useState('global')
  // El MISMO par de controles que Métricas y Dashboard, con el mismo motor
  // detrás: la moneda la manda el selector global (vive en el shell) y el modo
  // es el guardado de toda la app (ModoRendimientoContext), igual que en Dashboard.
  const { currency } = useCurrency()
  const moneda = currency === 'ARS' ? 'ars' : 'usd'
  const [modoRend, setModoRend] = useModoRendimiento()
  // 36 meses, no 12: el calendario dibuja una banda por AÑO, y con 12 meses los
  // años anteriores salían con la mitad de las celdas vacías — que además era lo
  // que el total paralelo del calendario tomaba como "+0%".
  const timelineData = useReportsTimeline(broker, 36, modoRend, moneda)
  // El rendimiento por año, del motor canónico. Una sola fuente para el número
  // del año: el calendario, la pestaña Año y el inicio leen de acá.
  const yearsData = useReportYears(broker, modoRend, moneda)
  // El período puede venir pedido por la URL (`?periodo=week`), que es como el
  // Dashboard manda a alguien directo a la tira semanal. Se lee UNA vez, para
  // arrancar: después manda el estado local, así el usuario puede cambiar de
  // solapa sin que la URL se lo revierta. Un valor que no exista cae en 'month'.
  const [searchParams, setSearchParams] = useSearchParams()
  const periodoPedido = searchParams.get('periodo')
  const [tab, setTab] = useState(
    TAB_IDS.includes(periodoPedido) ? periodoPedido : 'month',
  )
  // El interruptor "Todo / Sólo abiertas" de la tira semanal vive ACÁ y no
  // adentro de la tira: al cambiar de moneda esta pantalla esconde el bloque
  // entero mientras recarga, la tira se desmonta y un estado propio se
  // perdería — el usuario elegía "Sólo abiertas", tocaba Pesos y volvía a
  // "Todo" sin haber pedido nada.
  const [modoTira, setModoTira] = useState('todo')
  const [expandedKey, setExpandedKey] = useState(null)
  const plan = usePlanFeatures()

  const { items, loading: loadingItems, error: itemsError } =
    usePeriodItems(tab, broker, timelineData, modoRend, moneda)

  // El `?periodo=` es una ORDEN DE APERTURA, no un estado: se consume al entrar
  // y se borra de la dirección. Si se queda pegado, cada vez que esta pantalla
  // se vuelve a montar —volver de otra solapa, un paso atrás del navegador—
  // vuelve a forzar la solapa Semana y le pisa al usuario la que había elegido.
  useEffect(() => {
    if (!periodoPedido) return
    const resto = new URLSearchParams(searchParams)
    resto.delete('periodo')
    setSearchParams(resto, { replace: true })
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  // Reset expanded key cuando cambia el tab
  useEffect(() => { setExpandedKey(null) }, [tab])

  return (
    // Los montos de todas las tarjetas, en la moneda en que se mira y cada uno
    // al dólar de su fecha (utils/periodoEnPesos.js).
    <PesosDelPeriodoProvider broker={broker}>
    <div className="page-shell-wide">
      <PageHeader
        eyebrow="Reportes / Performance"
        title="Performance histórica"
        action={
          <div className="flex items-center gap-2 flex-wrap">
            <AnalyzeButton
              screen="reports"
              params={{ tab }}
              subtitle={`Performance · ${LABELS[tab]}`}
            />
            <ExportCsvButton resource="monthly" label="Exportar mensual" source="reports_header" variant="compact" />
            <ModoRendimiento valor={modoRend} onChange={setModoRend} />
            <BrokerSelector value={broker} onChange={setBroker} />
          </div>
        }
      />

      {timelineData.error && (
        <div className="mb-4 flex items-start gap-2 px-3 py-2 rounded-sm bg-rendi-neg/10 border border-rendi-neg/20 text-rendi-neg text-sm">
          <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          <span>{timelineData.error}</span>
        </div>
      )}

      {timelineData.loading && (
        <div className="p-10 text-center text-ink-3">
          <Loader2 size={20} className="animate-spin mx-auto mb-2" aria-hidden="true" />
          <p className="text-sm">Armando tu timeline…</p>
        </div>
      )}

      {!timelineData.loading && !timelineData.error && !timelineData.hasAnyData && (
        <EmptyState
          icon={<FileText size={20} />}
          title="Todavía no hay reportes"
          description="El primer reporte se genera al cerrar tu primer mes con actividad. Si recién importaste tu CSV, esperá al cambio de mes — te avisamos cuando esté listo."
          action={
            <Link
              to="/config"
              className="inline-flex items-center gap-1.5 text-sm bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 px-4 py-2 rounded-sm transition-colors"
            >
              Importar mi historial
              <ArrowRight size={13} strokeWidth={1.75} />
            </Link>
          }
        />
      )}

      {!timelineData.loading && !timelineData.error && timelineData.hasAnyData && (
        <>
          <PerformanceCalendar
            yearGroups={timelineData.yearGroups}
            years={yearsData.years}
            yearsLoading={yearsData.loading}
            historicos={yearsData.historicos}
            rankingPorAnio={timelineData.rankingPorAnio}
          />

          {plan.can('reportes.historicos') ? (
            <>
              <PeriodTabs value={tab} onChange={setTab} />
              {itemsError && (
                <div className="mb-3 flex items-start gap-2 px-3 py-2 rounded-sm bg-rendi-neg/10 border border-rendi-neg/20 text-rendi-neg text-xs">
                  <AlertTriangle size={13} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
                  <span>{itemsError}</span>
                </div>
              )}
              {tab === 'week' && (
                <WeeklyStrip
                  yearGroups={timelineData.yearGroups}
                  broker={broker}
                  modo={modoTira}
                  onModo={setModoTira}
                />
              )}
              {tab === 'month' ? (
                <MonthDisclosure
                  items={items}
                  loading={loadingItems}
                  broker={broker}
                  expandedKey={expandedKey}
                  onToggle={(key) => setExpandedKey(prev => prev === key ? null : key)}
                />
              ) : (
                <CurrentPeriodView
                  period={items[0]}
                  loading={loadingItems}
                  tab={tab}
                  broker={broker}
                />
              )}
            </>
          ) : (
            <ReportsFreeTeaser yearGroups={timelineData.yearGroups} />
          )}
        </>
      )}
    </div>
    </PesosDelPeriodoProvider>
  )
}

// ─── Free teaser ─────────────────────────────────────────────────────────────

function ReportsFreeTeaser({ yearGroups }) {
  const { lastMonth, totalHidden } = useMemo(() => {
    const all = []
    for (const g of yearGroups) {
      for (const m of g.months) {
        if (m && m.is_relevant) all.push({ year: g.year, month: m })
      }
    }
    all.sort((a, b) => (b.month.period_start || '').localeCompare(a.month.period_start || ''))
    return { lastMonth: all[0] || null, totalHidden: Math.max(0, all.length - 1) }
  }, [yearGroups])

  if (!lastMonth) return null

  return (
    <div className="space-y-3">
      <div className="border border-line rounded-xl bg-bg-1 overflow-hidden">
        <header className="flex items-center justify-between px-4 py-2.5 border-b border-line">
          <div className="flex items-center gap-2">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-rendi-pos" aria-hidden="true" />
            <span className="text-[12.5px] text-ink-0 font-medium">Tu último mes</span>
          </div>
          <span className="text-[12.5px] text-ink-2 font-medium">Vista previa Free</span>
        </header>
        <MonthCard month={lastMonth.month} defaultExpanded={true} />
      </div>

      {totalHidden > 0 && (
        <LockedSection.Placeholder
          feature="reportes.historicos"
          title={`Tenés ${totalHidden} ${totalHidden === 1 ? 'mes' : 'meses'} más en tu historial`}
          description="Reportes históricos completos, comparativas mes a mes, descarga PDF y vista anual. Disponible en Rendi Pro."
          source="reports_historicos"
        />
      )}
    </div>
  )
}

// ─── Period tabs ─────────────────────────────────────────────────────────────

// Los ids de las solapas viven en UNA lista: la usan las pestañas para
// dibujarse y la raíz para validar el `?periodo=` que puede venir de afuera.
// Separadas, un id nuevo entraría en un lado y no en el otro.
const TAB_IDS = ['day', 'week', 'month', 'year']

const LABELS = {
  day:   'Día',
  week:  'Semana',
  month: 'Mes',
  year:  'Año',
}

function PeriodTabs({ value, onChange }) {
  const tabs = TAB_IDS
  return (
    <div className="flex items-center gap-2 mb-4">
      <span className="text-[12.5px] text-ink-2 mr-1 font-medium">Período</span>
      <div className="inline-flex bg-bg-2 border border-line rounded-sm p-0.5">
        {tabs.map(t => (
          <button
            key={t}
            onClick={() => onChange(t)}
            className={`px-3.5 py-1.5 text-xs font-mono uppercase tracking-label rounded-sm transition-colors ${
              value === t ? 'bg-bg-3 text-ink-0' : 'text-ink-2 hover:text-ink-0'
            }`}
          >
            {LABELS[t]}
          </button>
        ))}
      </div>
    </div>
  )
}

// ─── Lista de períodos ───────────────────────────────────────────────────────

function PeriodList({ items, loading, expandedKey, onToggle }) {
  if (loading && items.length === 0) {
    return (
      <div className="p-10 text-center text-ink-3">
        <Loader2 size={18} className="animate-spin mx-auto mb-2" aria-hidden="true" />
        <p className="text-sm">Cargando…</p>
      </div>
    )
  }

  if (!items || items.length === 0) {
    return (
      <div className="p-10 text-center text-ink-3 border border-line/40 rounded bg-bg-1/40">
        <p className="text-sm">No hay datos para este período todavía.</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {items.map(period => (
        <PeriodRow
          key={period.period_key}
          period={period}
          expanded={expandedKey === period.period_key}
          onToggle={() => onToggle(period.period_key)}
        />
      ))}
    </div>
  )
}

// MonthDisclosure — mes en curso con la vista rica + "Ver más meses" que revela
// los meses anteriores del MISMO año (enero → 1, diciembre → 12). No salta al
// año anterior (eso es el tab Año). Reemplaza el muro de todos los meses.
function MonthDisclosure({ items, loading, broker, expandedKey, onToggle }) {
  const [showMore, setShowMore] = useState(false)
  if (loading && (!items || items.length === 0)) {
    return (
      <div className="p-10 text-center text-ink-3">
        <Loader2 size={18} className="animate-spin mx-auto mb-2" aria-hidden="true" />
        <p className="text-sm">Cargando…</p>
      </div>
    )
  }
  if (!items || items.length === 0) {
    return (
      <div className="p-10 text-center text-ink-3 border border-line/40 rounded bg-bg-1/40">
        <p className="text-sm">No hay datos para este período todavía.</p>
      </div>
    )
  }
  const current = items.find(x => x.is_current) || items.find(x => x.is_relevant) || items[0]
  const currentYear = (current?.period_key || '').slice(0, 4)
  // Todos los meses TRANSCURRIDOS del año en curso (relevantes o no) — enero → 1,
  // diciembre → 12. Los flat se ven como "sin actividad". Excluye futuros y actual.
  const priors = items
    .filter(x => x !== current
      && (x.period_key || '').startsWith(currentYear)
      && (x.period_key || '') < (current?.period_key || ''))
    .sort((a, b) => (a.period_key < b.period_key ? 1 : -1))

  return (
    <div className="space-y-4">
      <CurrentPeriodView period={current} loading={false} tab="month" broker={broker} />
      {priors.length > 0 && (
        <div className="space-y-2">
          <button
            onClick={() => setShowMore(v => !v)}
            className="w-full text-center text-[12.5px] text-data-violet bg-data-violet/5 border border-dashed border-data-violet/30 rounded-md py-2 transition-colors hover:bg-data-violet/10 font-medium"
          >
            {showMore ? '▴ Ocultar meses anteriores' : `▾ Ver más meses · ${priors.length} de ${currentYear}`}
          </button>
          {showMore && (
            <PeriodList items={priors} loading={false} expandedKey={expandedKey} onToggle={onToggle} />
          )}
        </div>
      )}
    </div>
  )
}

// Exportada para el test de la fila (Reports.periodRow.render.test.jsx).
export function PeriodRow({ period, expanded, onToggle }) {
  const empty = !period.is_relevant && !period.is_current
  // AUDIT D-1: sin base comparable el backend no publica el resultado del
  // período (start salía de la cadena contable y end del mercado). Ni el % ni
  // el monto: los dos eran el mismo número mal.
  const noBasis = period?.metrics?.basis_incomparable === true
  const pct = noBasis ? null : period?.metrics?.delta_pct
  const usd = noBasis ? null : period?.metrics?.delta_usd
  // El monto, al dólar del cierre del período (utils/periodoEnPesos.js).
  const pesos = usePesosDelPeriodo()
  // «Ocultar saldos»: los montos de esta tarjeta, tapados (los % no).
  const plata = (v, m, o) => (pesos.oculto ? OCULTO : plataRaw(v, m, o))
  // Y los textos que arma el servidor con montos adentro (la narración del
  // período: «perdiste US$ 528 sobre un capital de US$ 123.081»).
  if (pesos.oculto) period = taparMontosEnTodo(period)
  const usdVista = usd == null ? null : pesos.enVista(period).resultado
  // Uno o dos decimales según el tamaño, y el color del número que se ve.
  const decs = pct != null && Math.abs(pct) >= 10 ? 1 : 2
  const tono = pct == null ? 'text-ink-3' : pctColor(pct, decs)
  // El monto lleva el color de SU signo: en Pesos puede ser otro que el del % (un día o una semana
  // tiene el % en dólares), y un monto positivo en rojo contradice al resto de la fila.
  const tonoMonto = montoColor(usdVista)
  const pctUsd = pct != null && pesos.pctEnDolares(period)

  return (
    <div className={`border rounded bg-bg-1/60 overflow-hidden transition-colors ${
      expanded ? 'border-data-violet/30' : 'border-line hover:border-line-3'
    }`}>
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 flex items-center justify-between gap-4 text-left"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="font-medium text-ink-0 text-sm min-w-[110px]">
            {period.period_label}
          </span>
          {period.is_current && (
            <span className="text-[12.5px] text-rendi-pos border border-rendi-pos/30 bg-rendi-pos/10 px-1.5 py-0.5 rounded-sm font-medium">
              En curso
            </span>
          )}
          {!empty && period.headline && (
            <span className="text-xs text-ink-3 truncate hidden md:inline">
              {period.headline}
            </span>
          )}
          {empty && (
            <span className="text-[12.5px] text-ink-2 font-medium">
              Sin actividad
            </span>
          )}
        </div>

        <div className="flex items-center gap-4 flex-shrink-0">
          {pct != null && (
            <span className={`text-sm font-mono font-semibold tabular whitespace-nowrap ${tono}`}
              title={pctUsd ? 'Porcentaje en dólares' : undefined}>
              {pctVar(pct, decs)}
              {pctUsd && <span className="ml-1 text-[11px] font-normal text-ink-3">en US$</span>}
            </span>
          )}
          {usd != null && (
            <span className={`text-xs font-mono tabular ${tonoMonto} hidden sm:inline`}>
              {plata(usdVista, pesos.moneda, { signed: true })}
            </span>
          )}
          {expanded
            ? <ChevronUp size={14} strokeWidth={1.75} className="text-ink-3" />
            : <ChevronDown size={14} strokeWidth={1.75} className="text-ink-3" />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-line/40 bg-bg-0">
          <MonthCard period={period} defaultExpanded={true} />
        </div>
      )}
    </div>
  )
}

// ─── CurrentPeriodView — vista del período en curso con KPIs ricos ──────────
//
// Usado en tabs Día y Mes. Reemplaza la lista clickeable por un solo card
// expandido con un KPI strip arriba y el MonthCard completo abajo.

// Exportada para el test del color del P&L del período (Reports.periodRow.render.test.jsx).
export function CurrentPeriodView({ period, loading, tab, broker = 'global' }) {
  // ARRIBA de los dos `return` de abajo: este componente se monta con
  // loading=true (Reports.jsx:285 le pasa `loadingItems`), así que un useState
  // después del return temprano renderiza 0 hooks primero y 1 después —
  // "Rendered more hooks than during the previous render", pantalla rota.
  const [showTech, setShowTech] = useState(false)
  // Los montos en la moneda en que se mira, cada uno al dólar de su fecha.
  const pesos = usePesosDelPeriodo()
  // «Ocultar saldos»: los montos de esta tarjeta, tapados (los % no).
  const plata = (v, m, o) => (pesos.oculto ? OCULTO : plataRaw(v, m, o))
  // Y los textos que arma el servidor con montos adentro (la narración del
  // período: «perdiste US$ 528 sobre un capital de US$ 123.081»).
  if (pesos.oculto) period = taparMontosEnTodo(period)
  if (loading) {
    return (
      <div className="p-10 text-center text-ink-3">
        <Loader2 size={18} className="animate-spin mx-auto mb-2" aria-hidden="true" />
        <p className="text-sm">Armando el período…</p>
      </div>
    )
  }
  if (!period) {
    return (
      <div className="p-10 text-center text-ink-3 border border-line/40 rounded bg-bg-1/40">
        <p className="text-sm">No hay datos para el período en curso.</p>
      </div>
    )
  }

  const m = period.metrics || {}
  const snap = period.portfolio_snapshot || {}
  const v = pesos.enVista(period)
  const mon = pesos.moneda
  const fin = period.period_end || hoyISO()
  // AUDIT D-1: ver PeriodRow. Con base incomparable no hay resultado del período
  // que mostrar — publicar "US$ 0" sería afirmar que no pasó nada, que es tan
  // falso como el −US$127.486 que mostraba antes.
  const noBasis = m.basis_incomparable === true
  const pct = noBasis ? null : m.delta_pct
  const usd = noBasis ? null : m.delta_usd
  // Con % None (día/semana per-broker, base incompleta) la polaridad sale del
  // SIGNO del número que se ve — antes (pct ?? 0) >= 0 pintaba VERDE una pérdida realized.
  // «Que se ve» es el de la vista: en Pesos el resultado puede tener otro signo que los dólares
  // del servidor (una venta con pérdida en dólares y ganancia en pesos), y un +$1.500 en rojo
  // contradice a «P&L realizado» en verde de la misma franja.
  const isPos = pct != null ? pct >= 0 : ((usd == null ? null : v.resultado) ?? 0) >= 0
  // Sin base no hay signo que pintar: un "—" en verde sugiere un período bueno.
  // El % lleva el color del número QUE SE VE (lo que se escribe «0,00%» va neutro, como en la fila y la tarjeta).
  const colorClass = noBasis ? 'text-ink-3' : (pct != null ? pctColor(pct, 2) : (isPos ? 'text-rendi-pos' : 'text-rendi-neg'))
  // El monto lleva el color de SU signo y el % el del suyo: en Pesos el % de un día o una semana sigue en
  // dólares y puede tener otro signo que el monto (la cartera cae 0,2 % en dólares, el dólar sube: en
  // pesos ganó). Con el mismo color los dos se leían como una sola cuenta. El % se rotula.
  const colorMonto = noBasis || usd == null ? 'text-ink-3' : montoColor(v.resultado)
  const pctUsdHeader = pct != null && pesos.pctEnDolares(period)

  // Detección de "período flat" — sin movimientos, sin trades.
  // En ese caso no mostramos P&L del período (sería engañoso "+US$ 0"),
  // sino que pivot a KPIs estáticos del portfolio actual.
  // AUDIT D-1: `!noBasis &&` es imprescindible. El guard deja delta_usd en 0, así
  // que un mes sin trades ni flujos caía en isFlat → el pill decía "Sin
  // movimientos", se escondía el KPI con su "falta el cierre del arranque" y,
  // peor, se escondían el headline y la narrativa que EXPLICAN por qué no hay
  // número. El fix se anulaba a sí mismo y afirmaba que no pasó nada.
  const isFlat = !noBasis && (
    (m.delta_usd === 0 || m.delta_usd == null) &&
    (m.trades_count === 0 || m.trades_count == null) &&
    !m.deposits && !m.withdrawals
  )

  // KPIs del strip — incluye métricas estáticas del portfolio (cap actual,
  // aportado, # posiciones, # brokers) además del P&L del período.
  const kpis = []

  // Capital actual: snapshot total si lo tenemos, sino end_value del período.
  // end_value 0 = no-dato (día/semana per-broker no valúa capital) → '—', no
  // "US$ 0" al lado de "Posiciones: N" (parecía cuenta vaciada).
  const _endVal = m.end_value > 0 ? m.end_value : null
  const capitalNow = snap.latest_value != null ? snap.latest_value : _endVal
  const capitalNowVista = snap.latest_value != null ? pesos.deHoy(snap.latest_value)
    : (_endVal != null ? v.cierre : null)
  kpis.push({
    label: 'Capital actual',
    value: capitalNowVista != null ? plata(capitalNowVista, mon) : '—',
    sub: snap.latest_date ? `Al ${formatDateShort(snap.latest_date)}` : null,
  })

  // P&L del período (solo si NO es flat — sino confunde con "+US$ 0")
  if (!isFlat) {
    const periodLabel = tab === 'day' ? 'del día'
    : tab === 'week' ? 'de la semana'
    : tab === 'year' ? 'del año'
    : 'del mes'
    kpis.push({
      label: `P&L ${periodLabel}`,
      value: usd != null ? plata(v.resultado, mon, { signed: true }) : '—',
      sub: pct != null ? `${pctVar(pct, 2)}${pesos.pctEnDolares(period) ? ' en dólares' : ''}`
        : noBasis ? 'falta el cierre del arranque' : null,
      // El color es el del monto que se ve; el % puede estar en otra moneda (día y semana en Pesos).
      // (Un resultado que se escribe «0» va neutro, como en las filas: ver `montoColor`.)
      tone: noBasis ? undefined : (usd == null || v.resultado == null ? (isPos ? 'pos' : 'neg')
        : (montoEsCero(v.resultado) ? undefined : (v.resultado >= 0 ? 'pos' : 'neg'))),
    })
  }

  if (m.realized_pnl != null && (m.realized_pnl !== 0 || m.trades_count > 0)) {
    kpis.push({
      label: 'P&L realizado',
      value: plata(v.realizado, mon, { signed: true }),
      sub: m.trades_count != null ? `${m.trades_count} op${m.trades_count !== 1 ? 's' : ''} cerrada${m.trades_count !== 1 ? 's' : ''}` : 'operaciones cerradas',
      // En Pesos, lo que no tiene pesos de verdad (dividendos en dólares, ventas en dólares)
      // se dice en pantalla: el resto del número es el de las ventas en pesos, igual al broker.
      nota: v.realizadoNota || null,
      // El color sigue el número que se ve: en Pesos el realizado puede tener otro signo que en dólares.
      tone: montoEsCero(v.realizado ?? m.realized_pnl) ? undefined : ((v.realizado ?? m.realized_pnl) >= 0 ? 'pos' : 'neg'),
    })
  }

  // Lo que se muestra y su color salen del NÚMERO QUE SE VE (en Pesos es `resultado − realizado`, con
  // otro signo posible que los dólares del servidor, y el servidor deja 0 en todo mes cerrado).
  const noRealVisto = v.noRealizado ?? m.unrealized_pnl
  if (!isFlat && noRealVisto != null && Math.abs(noRealVisto) >= (mon === 'ARS' ? 0.5 : 0.005)) {
    kpis.push({
      label: 'P&L no realizado',
      value: plata(v.noRealizado ?? noRealVisto, mon, { signed: true }),
      sub: 'mark-to-market',
      tone: noRealVisto >= 0 ? 'pos' : 'neg',
    })
  }

  // Win rate cuando hay trades
  if (m.trades_count > 0 && m.win_rate != null) {
    kpis.push({
      label: 'Win rate',
      value: `${m.win_rate.toFixed(0).replace('.', ',')}%`,
      sub: `${m.win_count || 0} ganadas · ${m.loss_count || 0} perdidas`,
      tone: m.win_rate >= 50 ? 'pos' : 'neg',
    })
  }

  // Capital aportado neto (cumulative) — solo en tab Año.
  // El sub-label aclara que el % es sobre lo aportado (NO TWRR), para evitar
  // confusión con el delta_pct del período que sí neutraliza flujos.
  if (tab === 'year' && snap.cum_deposited != null && snap.cum_deposited > 0) {
    // En pesos, los pesos que se pusieron: el mismo acumulado que el "Capital
    // aportado" del Dashboard (utils/capitalAportado.js), cortado al cierre del
    // período. Si esa cuenta no explica los dólares del servidor, se muestra en
    // dólares en vez de inventar pesos.
    const apVista = pesos.aportadoHasta(fin, snap.cum_deposited)
    const [apMon, apVal, capVal] = apVista != null
      ? [mon, apVista, capitalNowVista]
      : ['USD', snap.cum_deposited, capitalNow]
    kpis.push({
      label: 'Capital aportado',
      value: plata(apVal, apMon),
      // ⚠️ NO CUANDO NO HAY BASE. Este cociente compara el capital de HOY contra
      // lo aportado, así que da un "retorno" enorme cuando la cartera arrancó con
      // posiciones que nunca entraron como aporte — justo lo que
      // `basis_incomparable` señala. Se veía en la misma tarjeta que dice "Año sin
      // base para medir el rendimiento": al lado del "—" del P&L, un
      // "+1565.9%". Uno de los dos está mintiendo, y es éste.
      sub: (capVal != null && !noBasis)
        ? `Retorno sobre aportes: ${capVal > apVal ? '+' : '−'}${(Math.abs((capVal - apVal) / apVal) * 100).toFixed(1).replace('.', ',')}%`
        : 'depósitos netos',
      tone: (capVal != null && !noBasis)
        ? (capVal >= apVal ? 'pos' : 'neg')
        : undefined,
    })
  }

  // # posiciones abiertas
  if (snap.positions_count != null && snap.positions_count > 0) {
    kpis.push({
      label: 'Posiciones',
      value: String(snap.positions_count),
      // El "en N brokers" cuenta TODAS las cuentas del usuario, no las del
      // reporte: la query del backend no aplica el filtro de broker a
      // propósito (con filtro diría "en 1 broker" siempre — cierto e inútil).
      // Así que sólo tiene sentido en la cartera global; con un broker
      // elegido, el sub-label contradecía al filtro que está arriba.
      sub: (broker === 'global' && snap.brokers_count > 0)
        ? `en ${snap.brokers_count} broker${snap.brokers_count !== 1 ? 's' : ''}`
        : null,
    })
  }

  // Variación vs último cierre — USD arriba (más relevante para retail),
  // % + fecha del snapshot anterior en el subtítulo.
  if (snap.delta_1d) {
    const d = snap.delta_1d
    const pctStr = `${pctVar(d.pct, 2)}`
    const fechaStr = d.prev_date ? ` · vs ${formatDateShort(d.prev_date)}` : ''
    kpis.push({
      label: 'Δ último cierre',
      value: plata(pesos.deHoy(d.usd), mon, { signed: true }),
      sub: pctStr + fechaStr,
      tone: d.pct >= 0 ? 'pos' : 'neg',
    })
  }

  // Variación 7 y 30 días — USD arriba, % + fecha del cierre contra el que mide
  // en el subtítulo, igual que "Δ último cierre".
  //
  // ⚠️ LA FECHA NO ES DECORACIÓN. El backend toma el último cierre ANTERIOR a
  // la ventana por viejo que sea: con el cron cortado dos meses, "Δ 30 días"
  // medía noventa y el rótulo no lo decía. Qué hacer con un arranque así (no
  // publicar, o publicar diciendo desde cuándo) es una decisión pendiente para
  // el chip del Dashboard; mientras tanto, el número dice contra qué fecha mide.
  for (const [clave, label] of [['delta_7d', 'Δ 7 días'], ['delta_30d', 'Δ 30 días']]) {
    const d = snap[clave]
    if (!d) continue
    const fechaStr = d.prev_date ? ` · vs ${formatDateShort(d.prev_date)}` : ''
    kpis.push({
      label,
      value: plata(pesos.deHoy(d.usd), mon, { signed: true }),
      sub: `${pctVar(d.pct, 2)}` + fechaStr,
      tone: d.pct >= 0 ? 'pos' : 'neg',
    })
  }

  // YTD — rendimiento del año en curso (solo en tab Año)
  if (tab === 'year' && snap.ytd) {
    const MESES_FULL = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic']
    const partial = snap.ytd.is_partial_year && snap.ytd.since_month
    const label = partial
      ? `Desde ${MESES_FULL[snap.ytd.since_month - 1]} ${snap.ytd.since_year}`
      : `YTD ${snap.ytd.since_year}`
    kpis.push({
      label,
      value: `${pctVar(snap.ytd.pct, 2)}`,
      sub: plata(pesos.deHoy(snap.ytd.usd), mon, { signed: true }),
      // El color del número que se ve (pctVarSign): −0,004 se escribe "0,00%".
      tone: pctVarSign(snap.ytd.pct, 2) > 0 ? 'pos' : pctVarSign(snap.ytd.pct, 2) < 0 ? 'neg' : null,
    })
  }

  // Última operación cerrada
  if (snap.last_op && snap.last_op.pnl_usd != null) {
    const op = snap.last_op
    // En Pesos, el resultado en pesos exacto de la venta (el MISMO número que Operaciones),
    // no el resultado en dólares × el dólar de la fecha. El color sale del número que se ve.
    const monto = (pesos.moneda === 'ARS' && op.resultado_ars != null)
      ? op.resultado_ars
      : pesos.deFecha(op.pnl_usd, op.date)
    kpis.push({
      label: 'Última op cerrada',
      value: `${op.asset} ${plata(monto, mon, { signed: true })}`,
      sub: formatDateShort(op.date),
      tone: monto >= 0 ? 'pos' : 'neg',
    })
  }

  // Top holding
  if (snap.top_holdings && snap.top_holdings.length > 0) {
    const t = snap.top_holdings[0]
    kpis.push({
      label: 'Top holding',
      value: t.asset,
      sub: t.broker || null,
    })
  }

  // vs S&P 500 (solo si aplica — mes tiene benchmark)
  if (m.vs_sp500_pct != null) {
    const vs = m.vs_sp500_pct
    kpis.push({
      label: 'vs S&P 500',
      // ppVarFino: −0,04 → "−0,04 pp" (antes "−0,0pp" junto a "por debajo").
      value: ppVarFino(vs, 1),
      // Un empate (0,0 pp) no es "por encima" en verde.
      sub: vs > 0 ? 'por encima' : vs < 0 ? 'por debajo' : 'igual',
      tone: vs > 0 ? 'pos' : vs < 0 ? 'neg' : null,
    })
  }

  // Flujos netos
  if ((m.deposits || m.withdrawals) && (m.deposits + m.withdrawals) > 0) {
    const net = (v.depositos || 0) - (v.retiros || 0)
    kpis.push({
      label: 'Flujos netos',
      value: plata(net, mon, { signed: true }),
      sub: `Aportes ${plata(v.depositos || 0, mon)}`,
    })
  }

  // ── Reparto en grupos: hero (3-4) + Trading + Cartera + detalle técnico ──
  // En vez de un strip plano de ~16 chips iguales, separamos las dos narrativas.
  const pick = (pred) => kpis.find(pred)
  const isPnlPeriodo = (k) => k.label.startsWith('P&L ') && !/realizado/i.test(k.label)
  const heroList = [
    pick(k => k.label === 'Capital actual'),
    pick(isPnlPeriodo),
    pick(k => k.label === 'P&L realizado'),
    pick(k => k.label.startsWith('YTD') || k.label.startsWith('Desde '))
      || pick(k => k.label === 'Capital aportado')
      || pick(k => k.label === 'P&L no realizado')
      || pick(k => k.label === 'Flujos netos'),
  ].filter(Boolean)
  const heroLabels = new Set(heroList.map(k => k.label))
  const tradingList = kpis.filter(k => ['Win rate', 'Última op cerrada'].includes(k.label))
  const carteraList = kpis.filter(k =>
    ['P&L no realizado', 'Posiciones', 'Top holding', 'vs S&P 500', 'Flujos netos', 'Capital aportado'].includes(k.label)
    && !heroLabels.has(k.label))
  const tecnicoList = kpis.filter(k => k.label.startsWith('Δ ') || ['Valor inicio', 'Valor cierre'].includes(k.label))

  // Movers MtM (mejor/peor holding) + mejor/peor operación (highlights realizados)
  const movers = period.movers || []
  const bestMover = movers.find(x => x.kind === 'best')
  const worstMover = movers.find(x => x.kind === 'worst')
  const bestOp = (period.highlights || []).find(h => h.kind === 'best_op')
  const worstOp = (period.highlights || []).find(h => h.kind === 'worst_op')
  const narrativeText = period.narrative || period.subheadline || null

  return (
    <div className="space-y-4">
      {/* Header del período */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3 flex-wrap">
          <h3 className="text-lg font-semibold text-ink-0 tracking-tight">{period.period_label}</h3>
          {period.is_current && (
            <span className="text-[12.5px] text-rendi-pos border border-rendi-pos/30 bg-rendi-pos/10 px-1.5 py-0.5 rounded-sm font-medium">
              En curso
            </span>
          )}
          {isFlat && (
            <span className="text-[12.5px] text-ink-3 border border-line/60 px-1.5 py-0.5 rounded-sm font-medium">
              Sin movimientos
            </span>
          )}
        </div>
        {!isFlat && (
          <div className="flex items-baseline gap-2">
            <span className={`text-2xl font-mono font-semibold tabular whitespace-nowrap ${colorClass}`}
              title={pctUsdHeader ? 'Porcentaje en dólares' : undefined}>
              {pct != null ? `${pctVar(pct, 2)}` : '—'}
              {pctUsdHeader && <span className="ml-1 text-xs font-normal text-ink-3">en US$</span>}
            </span>
            <span className={`text-sm font-mono tabular ${colorMonto}`}>
              {usd != null ? plata(v.resultado, mon, { signed: true }) : ''}
            </span>
          </div>
        )}
      </div>

      {isFlat && (
        <div className="border border-line/40 bg-bg-1/40 rounded px-4 py-3 text-xs text-ink-2 leading-relaxed">
          {(m.trades_count === 0 || m.trades_count == null)
            ? `Sin operaciones cerradas en ${tab === 'day' ? 'el día' : tab === 'week' ? 'la semana' : tab === 'year' ? 'el año' : 'el período'}. `
            : 'Sin variación en el valor de la cartera. '}
          Esperando próxima actualización (snapshot diario al cierre del mercado o al
          registrar una operación).
        </div>
      )}

      {broker !== 'global' && (
        <div className="border border-line/40 bg-bg-1/30 rounded px-4 py-2 text-[11px] text-ink-3 leading-relaxed">
          Vista filtrada por broker — algunos KPIs históricos (Δ vs cierres, YTD,
          última op de otros brokers) solo están disponibles en vista global.
        </div>
      )}

      {/* Narrativa — qué pasó, arriba de los números */}
      {!isFlat && (period.headline || narrativeText) && (
        <div className="border border-rendi-accent/25 rounded-lg bg-bg-1 p-4">
          {period.headline && <p className="text-sm font-medium text-ink-0 leading-snug">{period.headline}</p>}
          {narrativeText && <p className="text-xs text-ink-2 leading-relaxed mt-1.5">{narrativeText}</p>}
        </div>
      )}

      {/* Hero — 3-4 números que responden las preguntas reales */}
      {heroList.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {heroList.map((k, i) => (
            <div key={i} className="border border-line rounded-lg bg-bg-1 px-4 py-3">
              <div className="text-[12.5px] text-ink-2 mb-1.5 font-medium">{k.label}</div>
              <div className={`text-xl font-semibold tabular ${
                k.tone === 'pos' ? 'text-rendi-pos' : k.tone === 'neg' ? 'text-rendi-neg' : 'text-ink-0'
              }`}>{k.value}</div>
              {k.sub && <div className="text-[10px] font-mono text-ink-3 mt-1 truncate" title={k.sub}>{k.sub}</div>}
              {k.nota && <div className="text-[10.5px] text-ink-3 mt-0.5 leading-snug">{k.nota}</div>}
            </div>
          ))}
        </div>
      )}

      {/* Segundo nivel — dos narrativas separadas: Trading vs Cartera */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <div className="border border-line rounded-lg bg-bg-1 p-4">
          <div className="text-[12.5px] text-data-violet mb-2 font-medium">Trading · cómo operaste</div>
          {(bestOp || worstOp || tradingList.length > 0) ? (
            <div>
              {tradingList.filter(k => k.label === 'Win rate').map((k, i) => (
                <KVRow key={`wr${i}`} label="Win rate" value={k.value} sub={k.sub} tone={k.tone} />
              ))}
              <KVRow label="Ops cerradas" value={String(m.trades_count ?? 0)} />
              {bestOp && <KVRow label="Mejor op" value={bestOp.value_label} sub={bestOp.context ? formatDateShort(bestOp.context) : null} tone="pos" />}
              {worstOp && <KVRow label="Peor op" value={worstOp.value_label} sub={worstOp.context ? formatDateShort(worstOp.context) : null} tone="neg" />}
              {tradingList.filter(k => k.label === 'Última op cerrada').map((k, i) => (
                <KVRow key={`uo${i}`} label="Última cerrada" value={k.value} sub={k.sub} tone={k.tone} />
              ))}
            </div>
          ) : (
            <div className="text-xs text-ink-3 py-3">Sin operaciones cerradas en el período.</div>
          )}
        </div>
        <div className="border border-line rounded-lg bg-bg-1 p-4">
          <div className="text-[12.5px] text-rendi-accent mb-2 font-medium">Cartera · qué movió tu plata</div>
          <div>
            {bestMover && (
              <KVRow label={bestMover.delta_usd >= 0 ? 'Mejor activo' : 'Menor caída'}
                value={`${bestMover.asset} ${plata(pesos.alCierre(bestMover.delta_usd, period.period_end, period.is_current), mon, { signed: true })}`}
                sub={bestMover.delta_pct != null ? `${pctVar(bestMover.delta_pct, 1)}` : null}
                tone={bestMover.delta_usd >= 0 ? 'pos' : 'neg'} />
            )}
            {worstMover && (
              <KVRow label={worstMover.delta_usd < 0 ? 'Peor pérdida' : 'Menor suba'}
                value={`${worstMover.asset} ${plata(pesos.alCierre(worstMover.delta_usd, period.period_end, period.is_current), mon, { signed: true })}`}
                sub={worstMover.delta_pct != null ? `${pctVar(worstMover.delta_pct, 1)}` : null}
                tone={worstMover.delta_usd < 0 ? 'neg' : 'pos'} />
            )}
            {!bestMover && !worstMover && !period.movers_available && (
              <div className="text-[11px] text-ink-3 py-2 leading-relaxed">
                Mejor/peor activo por variación: <span className="text-ink-2">se empieza a medir desde hoy</span> (necesita la foto diaria por activo).
              </div>
            )}
            {carteraList.map((k, i) => <KVRow key={`c${i}`} label={k.label} value={k.value} sub={k.sub} tone={k.tone} />)}
          </div>
        </div>
      </div>

      {/* Detalle técnico — colapsado (deltas, valores, insights, breakdown) */}
      <div className="border border-line rounded-lg bg-bg-1 overflow-hidden">
        <button onClick={() => setShowTech(v => !v)} className="w-full px-4 py-2.5 flex items-center justify-between text-left">
          <span className="text-[12.5px] text-ink-2 font-medium">Ver detalle técnico</span>
          {showTech ? <ChevronUp size={14} strokeWidth={1.75} className="text-ink-3" /> : <ChevronDown size={14} strokeWidth={1.75} className="text-ink-3" />}
        </button>
        {showTech && (
          <div className="border-t border-line/40">
            {tecnicoList.length > 0 && (
              <div className="grid grid-cols-2 md:grid-cols-3 divide-x divide-y md:divide-y-0 divide-line/40">
                {tecnicoList.map((k, i) => (
                  <div key={i} className="px-4 py-3 min-w-0">
                    <div className="text-[12.5px] text-ink-2 mb-1.5 font-medium">{k.label}</div>
                    <div className={`text-sm font-medium tabular truncate ${
                      k.tone === 'pos' ? 'text-rendi-pos' : k.tone === 'neg' ? 'text-rendi-neg' : 'text-ink-0'
                    }`}>{k.value}</div>
                    {k.sub && <div className="text-[10px] font-mono text-ink-3 mt-1 truncate">{k.sub}</div>}
                    {k.nota && <div className="text-[10.5px] text-ink-3 mt-0.5 leading-snug">{k.nota}</div>}
                  </div>
                ))}
              </div>
            )}
            <MonthCard period={period} defaultExpanded={true} />
          </div>
        )}
      </div>
    </div>
  )
}

// KVRow — fila etiqueta/valor para las columnas Trading / Cartera.
function KVRow({ label, value, sub, tone }) {
  const c = tone === 'pos' ? 'text-rendi-pos' : tone === 'neg' ? 'text-rendi-neg' : 'text-ink-0'
  return (
    <div className="flex items-baseline justify-between gap-3 py-2 border-b border-line/30 last:border-b-0">
      <span className="text-xs text-ink-2 flex-shrink-0">{label}</span>
      <span className="text-right min-w-0">
        <span className={`text-xs font-mono tabular ${c}`}>{value}</span>
        {sub && <span className="block text-[10px] font-mono text-ink-3">{sub}</span>}
      </span>
    </div>
  )
}

// Un monto YA en `moneda` ('USD' | 'ARS'), con el formato de esta pantalla
// ("+US$ 1.234" / "+$ 1.234.567"): el número no se convierte acá.
function plataRaw(v, moneda, { signed = false } = {}) {
  if (v == null || !Number.isFinite(v)) return '—'
  const signo = signed ? (v >= 0 ? '+' : '−') : (v < 0 ? '−' : '')
  return `${signo}${moneda === 'ARS' ? '$' : 'US$'} ${fmtNum(Math.abs(v))}`
}

// Formato compacto de números — agrupador es-AR con punto.
function fmtNum(n) {
  return Math.round(n).toLocaleString('es-AR', { maximumFractionDigits: 0 })
}

function formatDateShort(iso) {
  const d = new Date(iso + 'T00:00:00')
  const MES = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic']
  return `${d.getDate()} ${MES[d.getMonth()]}`
}
