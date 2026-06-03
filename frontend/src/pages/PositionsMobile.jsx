// PositionsMobile — lista densa agrupada por broker (Sprint M1 + broker grouping).
// ═══════════════════════════════════════════════════════════════════════════
// Pares con la vista desktop: positions agrupadas por broker, cash al final
// de cada sección. Filtro por broker (Todos | cada uno) y botón "+ agregar".
//
// UX por sección:
//   ┌─ COCOS · ARS · $1,247 total
//   │  MSFT  44 · ARS    +3.5%    $638
//   │  AMZN  313 · ARS   +27.6%   $605
//   │  ...
//   │  ARS · Cash         —        $947   ← cash siempre al final
//   └─
//
// Filtro: tap en chip "Cocos" filtra a ese broker. "Todos" muestra todo.
// Botón "+" violeta abre modal de agregar broker (mismo flow que desktop).

import { useEffect, useMemo, useState, lazy, Suspense, memo } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { ArrowDownUp, Search, Repeat, Star, Check, Briefcase, Sparkles, Plus, Pencil, Trash2, X, TrendingDown, ArrowUpRight, ArrowDownLeft, Download, Wallet, ChevronDown } from 'lucide-react'
import AnalysisDrawer from '../components/ai/AnalysisDrawer'
import AssetLogo from '../components/AssetLogo'
import EmptyState from '../components/EmptyState'
import SwipeRow from '../components/mobile/SwipeRow'
import Modal from '../components/Modal'
import UpgradeModal from '../components/plan/UpgradeModal'
// AddPositionFlow es un chunk pesado (~600 tickers de CRYPTO/STOCKS_US/CEDEARs/
// ETFs/INDICES/AR_LIDER/AR_GENERAL/BONDS_*). Lazy-load para que el primer
// render de /cartera no espere a parsearlo — solo cuando el user abre el flow.
const AddPositionFlow = lazy(() => import('../components/AddPositionFlow'))
import { PositionFormModal, SellModal, EMPTY_POS, today } from './Positions'
import PlazosFijosGroup from '../components/PlazosFijosGroup'
import PfFormModal from '../components/PfFormModal'
import { useToast } from '../components/Toast'
import { api } from '../utils/api'
import { fmtUsd, ars, pctSigned, colorClass } from '../utils/format'
import { priceSymbol, fciLabel } from '../utils/valuation'
import { useCurrency } from '../contexts/CurrencyContext'
import { track } from '../utils/track'
import { notifyWatchlistChanged } from '../utils/watchlistEvents'
import { refreshPlanFeatures } from '../hooks/usePlanFeatures'

const SORT_OPTIONS = [
  { id: 'value',  label: 'Valor' },
  { id: 'pnl',    label: 'P&L %' },
  { id: 'alpha',  label: 'A-Z' },
]

const ALL_FILTER = '__all__'

// Paleta para distinguir brokers visualmente en la vista agrupada. Usamos
// los data accents del design system Rendi (no neón, no decorativo —
// función de identificación, no de jerarquía).
//
// La asignación es DETERMINÍSTICA por el nombre del broker (hash) — así
// "Schwab" siempre cae al mismo color entre re-renders y entre sesiones,
// y dos brokers con nombres distintos no compiten por el mismo color
// salvo colisión de hash.
const BROKER_PALETTE = [
  { dot: 'bg-data-violet', text: 'text-data-violet', bg: 'bg-data-violet/[0.10]', border: 'border-data-violet/30', ring: 'ring-data-violet/40' },
  { dot: 'bg-data-cyan',   text: 'text-data-cyan',   bg: 'bg-data-cyan/[0.10]',   border: 'border-data-cyan/30',   ring: 'ring-data-cyan/40' },
  { dot: 'bg-data-blue',   text: 'text-data-blue',   bg: 'bg-data-blue/[0.10]',   border: 'border-data-blue/30',   ring: 'ring-data-blue/40' },
  { dot: 'bg-data-amber',  text: 'text-data-amber',  bg: 'bg-data-amber/[0.10]',  border: 'border-data-amber/30',  ring: 'ring-data-amber/40' },
  { dot: 'bg-rendi-pos',   text: 'text-rendi-pos',   bg: 'bg-rendi-pos/[0.10]',   border: 'border-rendi-pos/30',   ring: 'ring-rendi-pos/40' },
]

function brokerColor(name) {
  if (!name) return BROKER_PALETTE[0]
  // djb2-ish hash — estable, sin Math.random, cero deps
  let h = 5381
  for (let i = 0; i < name.length; i++) h = ((h << 5) + h + name.charCodeAt(i)) | 0
  return BROKER_PALETTE[Math.abs(h) % BROKER_PALETTE.length]
}

export default function PositionsMobile() {
  // Fase A (2026-05-31): currency global via context — sincroniza con Dashboard/HomeMobile.
  const { currency, toggle: toggleCurrency, setTcBlue: publishTcBlue } = useCurrency()
  const navigate = useNavigate()
  const location = useLocation()
  const [positions, setPositions] = useState([])
  const [brokers, setBrokers] = useState([])
  const [prices, setPrices] = useState({})
  // Cierre del día hábil anterior por símbolo (mismo shape que /prices) para la
  // columna "Var. día". Endpoint aparte y best-effort: si falla, las celdas
  // muestran "—" sin romper el resto de la vista.
  const [prevClose, setPrevClose] = useState({})
  const [dolar, setDolar] = useState(null)
  const [loading, setLoading] = useState(true)
  // Loading separado para precios live — la página se muestra apenas
  // tenemos positions/brokers (con cost basis), pero los precios cargan en
  // background. pricesLoading=true muestra un indicador chiquito mientras
  // yfinance responde, así el user sabe que los % y valores se van a
  // actualizar en segundos.
  const [pricesLoading, setPricesLoading] = useState(false)
  const [sortBy, setSortBy] = useState('value')
  const [query, setQuery] = useState('')
  const [brokerFilter, setBrokerFilter] = useState(ALL_FILTER)
  // "Detalle" (paridad con desktop): en brokers ARS revela el equivalente en
  // USD de la variación diaria y del P&L, que por defecto van en pesos.
  const [showDetail, setShowDetail] = useState(false)
  // Bottom sheet con las 4 acciones rápidas: Registrar compra, Registrar
  // venta, Cash, Exportar CSV. Antes el botón "+ Nueva" solo abría el
  // add-flow; ahora pone parity con el desktop que tiene los 4 atajos.
  const [actionsSheet, setActionsSheet] = useState(false)
  // Modales de gestión de broker (mismo flow que el desktop BrokerManager)
  const [showAddBroker, setShowAddBroker] = useState(false)
  const [editingBroker, setEditingBroker] = useState(null)
  const [newBroker, setNewBroker] = useState({ name: '', currency: 'USDT' })
  const [brokerUpgrade, setBrokerUpgrade] = useState(null)
  // Modales unificados del flow de gestión de posiciones.
  //
  //   addModal = null         → ningún modal abierto
  //              'add-flow'   → picker de tipo de activo + ticker search (Nueva pos)
  //              'add'        → form completo, modo nueva posición
  //              'edit'       → form completo, modo edición
  //              'sell'       → modal de venta con FIFO preview
  //              'cashflow'   → depositar / retirar (solo cash positions)
  const [addModal, setAddModal] = useState(null)
  const [pfFormOpen, setPfFormOpen] = useState(false)
  const [pfReloadKey, setPfReloadKey] = useState(0)
  const [pfTotals, setPfTotals] = useState({})
  const [addForm, setAddForm] = useState(EMPTY_POS)
  // Venta FIFO: reusa el SellModal de desktop (form shape compartido).
  const [sellForm, setSellForm] = useState({
    broker: '', asset: '', currency: 'USDT', quantity: '', exit_price: '',
    tc_venta: '', date: '', commissions: '',
  })
  // Depósito / retiro de cash. direction: 'deposit' | 'withdraw'.
  const [cashFlowForm, setCashFlowForm] = useState({
    broker: '', currency: 'USDT', direction: 'deposit', amount: '', available: 0,
  })

  useEffect(() => { loadAll() }, [])

  // Handler reusable para abrir el flow de Nueva Posición. Usado por:
  //   1. El useEffect del query ?action=new (FAB del MobileTabBar)
  //   2. El botón "+ Nueva" del header de la página
  function openNewPositionFlow(source) {
    track('position_add_started', { source: source || 'unknown' })
    // Sin broker default: el paso 1 del flow lo elige (salvo que se preseleccione).
    setAddForm({
      ...EMPTY_POS,
      broker: '',
      entry_date: today(),
    })
    setAddModal('add-flow')
  }

  // ─── Handlers de acciones por posición ──────────────────────────────────
  // Estos callbacks se pasan a PositionRow (memoizado) para que pueda
  // gatillar la acción correspondiente desde el swipe sheet.

  function openSell(p) {
    if (p.is_cash) return
    const broker = brokers.find(b => b.name === p.broker)
    const isARS = broker?.currency === 'ARS'
    const price = prices[priceSymbol(p.asset, isARS)]
    const suggested = price ?? p.buy_price ?? ''
    setSellForm({
      broker: p.broker,
      asset: p.asset,
      currency: broker?.currency || 'USDT',
      quantity: '',
      exit_price: suggested ? +(+suggested).toFixed(4) : '',
      tc_venta: isARS ? +(dolar?.blue?.venta || 1415).toFixed(2) : '',
      date: today(),
      commissions: '',
    })
    setAddModal('sell')
  }

  async function confirmSell() {
    const body = {
      broker: sellForm.broker,
      asset: sellForm.asset,
      quantity: +sellForm.quantity,
      exit_price: +sellForm.exit_price,
      date: sellForm.date,
      commissions: sellForm.commissions !== '' ? +sellForm.commissions : 0,
      ...(sellForm.currency === 'ARS' && sellForm.tc_venta ? { tc_venta: +sellForm.tc_venta } : {}),
    }
    if (!body.quantity || body.quantity <= 0) {
      return alert('La cantidad ingresada no es válida.')
    }
    if (body.exit_price == null || body.exit_price < 0) {
      return alert('El precio ingresado no es válido.')
    }
    try {
      await api.post('/positions/sell', body)
      track('position_sold', { asset: sellForm.asset, broker: sellForm.broker })
      setAddModal(null)
      await loadAll()
    } catch (ex) {
      alert('No se pudo registrar la venta: ' + (ex?.message || 'Error'))
    }
  }

  function openCashFlow(p, direction) {
    const broker = brokers.find(b => b.name === p.broker)
    setCashFlowForm({
      broker: p.broker,
      currency: broker?.currency || 'USDT',
      direction,
      amount: '',
      available: p.invested || p.quantity || 0,
    })
    setAddModal('cashflow')
  }

  async function confirmCashFlow() {
    const amount = +cashFlowForm.amount
    if (!amount || amount <= 0) return alert('Ingresá un monto válido.')
    if (cashFlowForm.direction === 'withdraw' && amount > cashFlowForm.available + 0.001) {
      return alert(`Saldo insuficiente. Disponible: ${cashFlowForm.available.toFixed(2)} ${cashFlowForm.currency}.`)
    }
    try {
      await api.post('/cash/flow', {
        broker_name: cashFlowForm.broker,
        direction: cashFlowForm.direction,
        amount,
        currency: cashFlowForm.currency,
      })
      track('cash_flow_recorded', {
        broker: cashFlowForm.broker,
        direction: cashFlowForm.direction,
      })
      setAddModal(null)
      await loadAll()
    } catch (ex) {
      alert(`No se pudo registrar el ${cashFlowForm.direction === 'deposit' ? 'depósito' : 'retiro'}: ${ex?.message || 'Error'}`)
    }
  }

  function openEditPosition(p) {
    setAddForm({
      ...p,
      is_cash: !!p.is_cash,
      buy_price: p.buy_price ?? '',
      quantity: p.quantity ?? '',
      invested: p.invested ?? '',
      tc_compra: p.tc_compra ?? '',
      commissions: p.commissions ?? '',
      notes: p.notes ?? '',
      entry_date: p.entry_date ?? '',
    })
    setAddModal('edit')
  }

  async function saveEditPosition() {
    const body = {
      ...addForm,
      buy_price:   addForm.buy_price   !== '' ? +addForm.buy_price   : null,
      quantity:    addForm.quantity    !== '' ? +addForm.quantity    : null,
      invested:    addForm.invested    !== '' ? +addForm.invested    : null,
      tc_compra:   addForm.tc_compra   !== '' ? +addForm.tc_compra   : null,
      commissions: addForm.commissions !== '' ? +addForm.commissions : 0,
      entry_date:  addForm.entry_date  || null,
    }
    try {
      await api.put(`/positions/${addForm.id}`, body)
      setAddModal(null)
      setAddForm(EMPTY_POS)
      await loadAll()
    } catch (ex) {
      alert('No pudimos guardar los cambios. ' + (ex?.message || 'Probá de nuevo.'))
    }
  }

  async function deletePosition(p) {
    if (!confirm(`¿Eliminar la posición ${p.asset} en ${p.broker}? La acción no se puede deshacer.`)) return
    try {
      await api.delete(`/positions/${p.id}`)
      track('position_deleted', { asset: p.asset, broker: p.broker })
      await loadAll()
    } catch (ex) {
      alert('No se pudo eliminar la posición: ' + (ex?.message || 'Error'))
    }
  }

  // ?action=new → abrir el flow automáticamente. Limpiamos el query param
  // para que un reload posterior no re-abra el modal.
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    if (params.get('action') === 'new') {
      openNewPositionFlow('mobile_fab')
      navigate('/posiciones', { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search, brokers.length])

  async function loadAll() {
    try {
      // 1. Fetchear positions / brokers / dolar en paralelo. Esto es rápido
      //    (queries locales en SQLite + 1 API call al blue). Tras esto ya
      //    podemos mostrar la cartera al user con cost basis values —
      //    NO esperamos los precios live de yfinance.
      const [pos, bkrs, dol] = await Promise.all([
        api.get('/positions').catch(() => []),
        api.get('/brokers').catch(() => []),
        api.get('/dolar').catch(() => null),
      ])
      setPositions(pos || [])
      setBrokers(bkrs || [])
      setDolar(dol)
      setLoading(false)  // ← Mostrar la página AHORA con cost basis

      // 2. Fetchear precios en background. yfinance puede tardar 5-10s para
      //    muchos símbolos — no queremos bloquear la primera pintada. Cuando
      //    los precios lleguen, el state actualiza y las filas re-renderean
      //    con valores live (memo permite que solo se re-pinten las filas
      //    cuyos precios cambian).
      setPricesLoading(true)
      loadPrices(pos || [], bkrs || []).finally(() => setPricesLoading(false))
    } catch (ex) {
      // Si falla la carga base (positions/brokers), igual sacamos el loading
      // para no quedarnos en skeleton infinito.
      setLoading(false)
    }
  }

  async function loadPrices(pos, bkrs) {
    const arsBrokers = new Set(bkrs.filter(b => b.currency === 'ARS').map(b => b.name))
    const usdtBrokers = new Set(bkrs.filter(b => b.currency !== 'ARS').map(b => b.name))
    const arsSyms = [...new Set(pos.filter(p => arsBrokers.has(p.broker) && !p.is_cash).map(p => priceSymbol(p.asset, true)))]
    const usdtSyms = [...new Set(pos.filter(p => usdtBrokers.has(p.broker) && !p.is_cash && p.asset !== 'USDT').map(p => p.asset))]
    const all = [...arsSyms, ...usdtSyms].join(',')
    if (!all) return
    try { setPrices(await api.get(`/prices?symbols=${all}`)) } catch { /* silent */ }
    // Prev-close para "Var. día" — best-effort, no bloquea ni rompe si falla.
    try { setPrevClose(await api.get(`/prices/prev-close?symbols=${all}`)) } catch { /* silent */ }
  }

  async function addBroker(e) {
    e.preventDefault()
    if (!newBroker.name.trim()) return
    try {
      await api.post('/brokers', { name: newBroker.name.trim(), currency: newBroker.currency })
      setNewBroker({ name: '', currency: 'USDT' })
      setShowAddBroker(false)
      await loadAll()
      refreshPlanFeatures()
    } catch (ex) {
      if (ex?.status === 403 && ex?.payload?.detail?.upgrade) {
        const detail = ex.payload.detail
        track('feature_blocked_clicked', { feature: 'brokers.create', source: 'positions_mobile' })
        setBrokerUpgrade({
          message: detail.error || 'El plan Free permite 1 broker.',
          benefits: detail.upgrade?.benefits,
        })
        return
      }
      alert('No pudimos agregar el broker. Probá de nuevo.')
    }
  }

  async function saveEditBroker(e) {
    e.preventDefault()
    if (!editingBroker.name.trim()) return
    await api.put(`/brokers/${editingBroker.id}`, { name: editingBroker.name.trim(), currency: editingBroker.currency })
    setEditingBroker(null)
    await loadAll()
  }

  async function deleteBrokerAction(b) {
    // Fase 5: doble confirmación cuando el broker tiene data. Mismo flow que
    // BrokerManager.jsx (mantengo duplicación porque el mobile tiene su
    // propio path; cuando se unifique en Fase 8 esto se centraliza).
    try {
      await api.delete(`/brokers/${b.id}`)
    } catch (ex) {
      const detail = ex?.payload?.detail
      if (ex?.status !== 409 || !detail?.counts) {
        alert(`No se pudo eliminar: ${ex?.message || 'error desconocido'}`)
        return
      }
      const c = detail.counts
      const parts = []
      if (c.positions > 0) parts.push(`${c.positions} ${c.positions === 1 ? 'posición' : 'posiciones'}`)
      if (c.operations > 0) parts.push(`${c.operations} ${c.operations === 1 ? 'operación' : 'operaciones'}`)
      if (c.monthly_entries > 0) parts.push(`${c.monthly_entries} ${c.monthly_entries === 1 ? 'entrada mensual' : 'entradas mensuales'}`)
      if (c.import_batches > 0) parts.push(`${c.import_batches} ${c.import_batches === 1 ? 'import' : 'imports'}`)
      const siblingWarning = detail.sibling
        ? `\n\n⚠️ ATENCIÓN: este broker es PADRE de "${detail.sibling.name}" (${detail.sibling.currency}). Al borrar el padre, el sibling también se eliminará.`
        : ''
      const msg = `El broker "${b.name}" tiene data:\n\n  • ${parts.join('\n  • ')}${siblingWarning}\n\n¿Borrar TODO? Esta acción no se puede deshacer.`
      if (!confirm(msg)) return
      try {
        await api.delete(`/brokers/${b.id}?force=true`)
      } catch (ex2) {
        alert(`Error al borrar: ${ex2?.message || 'desconocido'}`)
        return
      }
    }
    if (brokerFilter === b.name) setBrokerFilter(ALL_FILTER)
    await loadAll()
    refreshPlanFeatures()
  }

  const tcBlue = dolar?.blue?.venta || 1415

  // Fase B: publish tcBlue al CurrencyContext (mismo pattern que Dashboard/HomeMobile)
  useEffect(() => {
    if (tcBlue > 0) publishTcBlue(tcBlue)
  }, [tcBlue, publishTcBlue])

  const arsBrokerSet = useMemo(
    () => new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name)),
    [brokers]
  )

  // Enriquecemos cada posición con su valor USD y P&L %.
  // Para cash: NO computamos P/L (cash es cash, no tiene "variación").
  const enriched = useMemo(() => {
    return positions.map(p => {
      const isAR = arsBrokerSet.has(p.broker)
      const qty = p.quantity || 0
      const invested = p.invested || 0
      let valueUsd = 0
      let priceLocal = null
      if (p.is_cash) {
        valueUsd = isAR ? invested / tcBlue : invested
        return {
          ...p, valueUsd, priceLocal: null, pnlUsd: null, pnlPct: null,
          pnlLocal: null, dayVarLocal: null, dayVarUsd: null, dayVarPct: null, isAR,
        }
      } else if (isAR) {
        priceLocal = p.price_override ?? prices[priceSymbol(p.asset, true)]
        if (priceLocal) valueUsd = (priceLocal * qty) / tcBlue
        else valueUsd = invested / tcBlue
      } else {
        priceLocal = p.price_override ?? prices[p.asset]
        if (priceLocal) valueUsd = priceLocal * qty
        else valueUsd = invested
      }
      const investedUsd = isAR ? invested / tcBlue : invested
      const pnlUsd = valueUsd - investedUsd
      const pnlPct = investedUsd > 0 ? pnlUsd / investedUsd : 0
      // P&L en la moneda local del broker (ARS para brokers en pesos, USD resto).
      const pnlLocal = isAR ? pnlUsd * tcBlue : pnlUsd

      // ─── Variación diaria de mercado (precio hoy vs cierre anterior) ────────
      // Montos en la MISMA moneda local que el precio: ARS para .BA, USD resto.
      // Saltamos precios manuales (price_override no comparte fuente con el
      // cierre de mercado → comparación inválida). Cash ya retornó arriba.
      let dayVarLocal = null, dayVarUsd = null, dayVarPct = null
      if (!p.price_override && priceLocal != null) {
        const prev = prevClose[isAR ? priceSymbol(p.asset, true) : p.asset]
        if (prev != null && prev > 0) {
          const perUnit = priceLocal - prev
          dayVarLocal = perUnit * qty
          dayVarUsd = isAR ? dayVarLocal / tcBlue : dayVarLocal
          dayVarPct = perUnit / prev
        }
      }
      return {
        ...p, valueUsd, priceLocal, pnlUsd, pnlPct, pnlLocal,
        dayVarLocal, dayVarUsd, dayVarPct, isAR,
      }
    })
  }, [positions, prices, prevClose, arsBrokerSet, tcBlue])

  // Filtro de búsqueda libre (asset o broker name)
  const filteredBySearch = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return enriched
    return enriched.filter(p =>
      (p.asset || '').toLowerCase().includes(q) ||
      (p.broker || '').toLowerCase().includes(q)
    )
  }, [enriched, query])

  // Filtro de broker (chip seleccionado)
  const filteredByBroker = useMemo(() => {
    if (brokerFilter === ALL_FILTER) return filteredBySearch
    return filteredBySearch.filter(p => p.broker === brokerFilter)
  }, [filteredBySearch, brokerFilter])

  // Comparador interno por sort criterion (cash siempre al final)
  function comparePositions(a, b) {
    // Cash al final
    if (a.is_cash && !b.is_cash) return 1
    if (!a.is_cash && b.is_cash) return -1
    switch (sortBy) {
      case 'pnl':   return (b.pnlPct || 0) - (a.pnlPct || 0)
      case 'alpha': return (a.asset || '').localeCompare(b.asset || '')
      case 'value':
      default:      return (b.valueUsd || 0) - (a.valueUsd || 0)
    }
  }

  // Agrupación por broker (solo cuando filterBroker = ALL).
  // Cada grupo: { broker: brokerObj, positions: [...], totalUsd }
  const grouped = useMemo(() => {
    if (brokerFilter !== ALL_FILTER) return null
    const map = new Map()
    for (const p of filteredByBroker) {
      const b = brokers.find(x => x.name === p.broker)
      if (!map.has(p.broker)) {
        map.set(p.broker, { broker: b || { name: p.broker, currency: 'USDT' }, positions: [], totalUsd: 0 })
      }
      const g = map.get(p.broker)
      g.positions.push(p)
      g.totalUsd += (p.valueUsd || 0)
    }
    // Ordenar positions internas (cash al final) + grupos por totalUsd desc
    const groups = Array.from(map.values())
    for (const g of groups) g.positions.sort(comparePositions)
    groups.sort((a, b) => b.totalUsd - a.totalUsd)
    return groups
  }, [filteredByBroker, brokerFilter, brokers, sortBy])

  // Lista plana cuando hay filtro de broker activo
  const flatList = useMemo(() => {
    if (brokerFilter === ALL_FILTER) return null
    return [...filteredByBroker].sort(comparePositions)
  }, [filteredByBroker, brokerFilter, sortBy])

  const total = enriched.reduce((s, p) => s + (p.valueUsd || 0), 0)
  const pfValueUsd = (pfTotals.USD?.valor || 0) + (pfTotals.ARS?.valor || 0) / tcBlue  // PF → USD para el total
  const visibleCount = brokerFilter === ALL_FILTER
    ? filteredByBroker.length
    : (flatList?.length || 0)
  // El toggle "Detalle" solo aporta en brokers ARS (revela el equivalente USD).
  // Si el user no tiene ningún broker en pesos, no mostramos el botón.
  const hasArs = brokers.some(b => b.currency === 'ARS')
  // Moneda del broker seleccionado (encabezado de columnas en vista filtrada).
  // En "Todos", cada sección define la suya.
  const selectedCurrency = brokerFilter === ALL_FILTER
    ? null
    : (brokers.find(b => b.name === brokerFilter)?.currency || 'USDT')

  if (loading) {
    // Skeleton mínimo en lugar de texto plano — el user ve inmediatamente
    // que la página está cargando contenido (perceived performance), no
    // un mensaje genérico que parpadea.
    return (
      <div className="px-4 py-6 space-y-3" aria-live="polite" aria-busy="true">
        <div className="h-7 w-40 bg-bg-2 rounded-sm animate-pulse" />
        <div className="h-9 w-full bg-bg-2 rounded-sm animate-pulse" />
        <div className="space-y-2 pt-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-14 w-full bg-bg-1 rounded-sm animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="pb-8">
      {/* Header con total + sort */}
      <header className="sticky top-[88px] z-20 bg-bg-0/95 backdrop-blur-md border-b border-line/40 px-4 pt-3 pb-2">
        <div className="flex items-baseline justify-between mb-2 gap-2">
          <div className="min-w-0">
            <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 leading-none mb-1">
              Cartera total
            </div>
            <div className="text-xl font-medium tabular text-ink-0 leading-none">
              ${Math.round(currency === 'ARS' ? (total + pfValueUsd) * tcBlue : (total + pfValueUsd)).toLocaleString(currency === 'ARS' ? 'es-AR' : 'en-US')}
              <button
                onClick={toggleCurrency}
                className="text-xs text-ink-3 ml-1 font-normal hover:text-ink-1 active:text-ink-0 transition-colors"
                title={`Cambiar a ${currency === 'USD' ? 'ARS' : 'USD'}`}
              >
                {currency}
              </button>
            </div>
          </div>
          {/* Acciones derechas: count + botón rápido para agregar posición.
              El FAB central del MobileTabBar sigue funcionando, pero tener un
              entry point DENTRO de Cartera baja la fricción para el user que
              ya está en esta página. */}
          <div className="flex items-center gap-2 flex-shrink-0">
            {/* Mientras yfinance responde, mostramos un dot pulsante que
                indica que los valores se van a actualizar — el user entiende
                que lo que ve ahora es cost basis y los % live están llegando. */}
            {pricesLoading && (
              <span
                className="w-1.5 h-1.5 rounded-full bg-data-violet animate-pulse"
                title="Actualizando precios live"
                aria-label="Actualizando precios"
              />
            )}
            <span className="text-[11px] font-mono uppercase tracking-caps text-ink-2">
              {visibleCount} pos
            </span>
            <button
              type="button"
              onClick={() => setActionsSheet(true)}
              className="inline-flex items-center gap-1 text-xs font-medium bg-data-violet hover:bg-data-violet/90 text-white rounded-md px-3 py-2 transition-colors whitespace-nowrap shadow-sm"
              aria-label="Acciones rápidas"
            >
              <Plus size={13} strokeWidth={2.5} />
              Acciones
              <ChevronDown size={11} strokeWidth={2} aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* Search input compacto. Padding interno aumentado de py-1.5 → py-2.5
            para no sentir el input apretado contra los chips de abajo. */}
        <div className="relative mb-3.5">
          <Search size={13} strokeWidth={1.75} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar ticker o broker…"
            className="w-full bg-bg-2 border border-line/40 rounded-md pl-8 pr-3 py-2.5 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-rendi-accent/40"
          />
        </div>

        {/* Filtro de broker — chips horizontales scrollables. Margen extra
            inferior para separar del sort segmented. */}
        <div className="-mx-4 px-4 mb-3.5 overflow-x-auto no-scrollbar">
          <div className="inline-flex gap-2 pb-0.5">
            <BrokerFilterChip
              active={brokerFilter === ALL_FILTER}
              onClick={() => setBrokerFilter(ALL_FILTER)}
              label="Todos"
            />
            {brokers.map(b => (
              <BrokerFilterChip
                key={b.id}
                active={brokerFilter === b.name}
                onClick={() => setBrokerFilter(b.name)}
                label={b.name}
                currency={b.currency}
              />
            ))}
            <button
              type="button"
              onClick={() => setShowAddBroker(true)}
              className="inline-flex items-center gap-1 text-[11px] font-medium bg-data-violet/10 hover:bg-data-violet/15 text-data-violet border border-dashed border-data-violet/40 rounded-md px-3 py-2 whitespace-nowrap transition-colors"
            >
              <Plus size={11} strokeWidth={2} />
              Agregar broker
            </button>
          </div>
        </div>

        {/* Sort segmented + toggle "Detalle" (este último solo si hay broker
            ARS, que es donde aporta: revela el equivalente USD de var. día y P&L). */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ArrowDownUp size={12} strokeWidth={1.75} className="text-ink-3" />
            <div className="inline-flex bg-bg-2 p-1 rounded-md">
              {SORT_OPTIONS.map(o => (
                <button
                  key={o.id}
                  onClick={() => setSortBy(o.id)}
                  className={`px-2.5 py-1 text-[10px] font-mono uppercase tracking-caps rounded transition-colors ${
                    sortBy === o.id ? 'bg-bg-3 text-ink-0' : 'text-ink-3 hover:text-ink-1'
                  }`}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>
          {hasArs && (
            <button
              type="button"
              onClick={() => setShowDetail(v => !v)}
              aria-pressed={showDetail}
              className={`px-2.5 py-1.5 text-[10px] font-mono uppercase tracking-caps rounded-md transition-colors ${
                showDetail ? 'bg-bg-3 text-ink-0' : 'bg-bg-2 text-ink-3 hover:text-ink-1'
              }`}
              title="Mostrar el equivalente en USD de la variación diaria y el P&L en brokers ARS"
            >
              Detalle USD
            </button>
          )}
        </div>
      </header>

      {/* Lista */}
      {visibleCount === 0 ? (
        <div className="px-4">
          <EmptyState
            icon={<Briefcase size={18} strokeWidth={1.5} />}
            eyebrow="Cartera vacía"
            title={query ? 'Sin coincidencias' : (brokerFilter !== ALL_FILTER ? `Sin posiciones en ${brokerFilter}` : 'No tenés posiciones cargadas')}
            description={
              query
                ? 'Probá con otro ticker, broker o limpiá la búsqueda.'
                : 'Cargá tus tenencias actuales con el botón [+] del medio o desde "Más → Importaciones".'
            }
          />
        </div>
      ) : brokerFilter === ALL_FILTER ? (
        // Vista agrupada por broker
        <>
          <div className="divide-y divide-line/20">
            {grouped?.map(g => (
              <BrokerSection
                key={g.broker.name}
                broker={g.broker}
                positions={g.positions}
                totalUsd={g.totalUsd}
                showDetail={showDetail}
                displayCurrency={currency}
                tcBlue={tcBlue}
                onEdit={() => setEditingBroker({ ...g.broker })}
                onDelete={() => deleteBrokerAction(g.broker)}
                onSellPosition={openSell}
                onCashFlowPosition={openCashFlow}
                onEditPosition={openEditPosition}
                onDeletePosition={deletePosition}
              />
            ))}
          </div>
          <div className="px-4 pb-2">
            <PlazosFijosGroup reloadKey={pfReloadKey} onAdd={() => setPfFormOpen(true)} onTotals={setPfTotals} />
          </div>
        </>
      ) : (
        // Vista filtrada — lista plana del broker seleccionado
        <>
          <ColumnHeader currency={selectedCurrency} totalCurrency={currency} />
          <ul className="divide-y divide-line/30">
            {flatList?.map(p => (
              <PositionRow
                key={`${p.broker}:${p.asset}:${p.id || p.entry_date}`}
                p={p}
                showDetail={showDetail}
                displayCurrency={currency}
                tcBlue={tcBlue}
                onSell={openSell}
                onCashFlow={openCashFlow}
                onEditPos={openEditPosition}
                onDeletePos={deletePosition}
              />
            ))}
          </ul>
        </>
      )}

      {/* Modal: agregar broker */}
      {showAddBroker && (
        <Modal title="Agregar broker" onClose={() => setShowAddBroker(false)}>
          <form onSubmit={addBroker} className="space-y-3">
            <div>
              <label className="block text-xs text-ink-3 mb-1">Nombre del broker</label>
              <input
                value={newBroker.name}
                onChange={e => setNewBroker(b => ({ ...b, name: e.target.value }))}
                placeholder="Ej.: Binance, Cocos, IOL, IBKR…"
                className="w-full bg-bg-2 border border-line rounded-sm px-3 py-2 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2"
                autoFocus
              />
            </div>
            <div>
              <label className="block text-xs text-ink-3 mb-1">Tipo de moneda</label>
              <select
                value={newBroker.currency}
                onChange={e => setNewBroker(b => ({ ...b, currency: e.target.value }))}
                className="w-full bg-bg-2 border border-line rounded-sm px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-ink-2"
              >
                <option value="USDT">USDT — Exchange crypto (Binance, Bybit, etc.)</option>
                <option value="USD">USD — Broker en dólares (IBKR, Schwab, etc.)</option>
                <option value="ARS">ARS — Broker en pesos (Cocos, IOL, Balanz)</option>
              </select>
              <p className="text-[10px] text-ink-3 mt-1 leading-relaxed">
                Brokers ARS se convierten al blue para el valor total en USD.
              </p>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowAddBroker(false)}
                className="text-xs text-ink-3 hover:text-ink-0 px-3 py-2 transition-colors"
              >
                Cancelar
              </button>
              <button
                type="submit"
                className="inline-flex items-center gap-1.5 text-xs bg-data-violet/10 text-data-violet border border-data-violet/30 hover:bg-data-violet/15 px-4 py-2 rounded-sm transition-colors"
              >
                <Plus size={12} strokeWidth={2} /> Agregar
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* Modal: editar broker */}
      {editingBroker && (
        <Modal title={`Editar "${editingBroker.name}"`} onClose={() => setEditingBroker(null)}>
          <form onSubmit={saveEditBroker} className="space-y-3">
            <div>
              <label className="block text-xs text-ink-3 mb-1">Nombre del broker</label>
              <input
                value={editingBroker.name}
                onChange={e => setEditingBroker(eb => ({ ...eb, name: e.target.value }))}
                className="w-full bg-bg-2 border border-line rounded-sm px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-ink-2"
                autoFocus
              />
            </div>
            <div>
              <label className="block text-xs text-ink-3 mb-1">Tipo de moneda</label>
              <select
                value={editingBroker.currency}
                onChange={e => setEditingBroker(eb => ({ ...eb, currency: e.target.value }))}
                className="w-full bg-bg-2 border border-line rounded-sm px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-ink-2"
              >
                <option value="USDT">USDT</option>
                <option value="USD">USD</option>
                <option value="ARS">ARS</option>
              </select>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setEditingBroker(null)}
                className="text-xs text-ink-3 hover:text-ink-0 px-3 py-2 transition-colors"
              >
                Cancelar
              </button>
              <button
                type="submit"
                className="text-xs bg-rendi-pos/10 text-rendi-pos border border-rendi-pos/30 hover:bg-rendi-pos/15 px-4 py-2 rounded-sm transition-colors"
              >
                Guardar
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* Modal de upgrade cuando intenta agregar broker n°2 en Free */}
      {brokerUpgrade && (
        <UpgradeModal
          title="Pasate a Rendi Pro para más brokers"
          message={brokerUpgrade.message}
          feature="brokers.create"
          source="positions_mobile"
          benefits={brokerUpgrade.benefits}
          onClose={() => setBrokerUpgrade(null)}
        />
      )}

      {/* Flow de Nueva Posición — gatillado por el FAB del MobileTabBar.
          Step 1: AddPositionFlow muestra picker de tipo de activo + ticker search.
          Step 2: tras seleccionar ticker, cerramos el flow y abrimos
                  PositionFormModal con el asset preseteado.

          AddPositionFlow se lazy-loadea para no bloquear el primer render
          de /cartera con ~600 tickers parseados. Mientras carga el chunk,
          mostramos un placeholder neutro (no flicker). */}
      {addModal === 'add-flow' && (
        <Suspense fallback={
          <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center">
            <div className="text-ink-2 text-sm">Cargando…</div>
          </div>
        }>
          <AddPositionFlow
            onClose={() => setAddModal(null)}
            brokers={brokers}
            initialBroker={addForm.broker || null}
            onPlazoFijo={() => { setAddModal(null); setPfFormOpen(true) }}
            onAssetSelected={({ asset, broker }) => {
              setAddForm(f => ({ ...f, asset, broker: broker || f.broker }))
              setAddModal('add')
            }}
          />
        </Suspense>
      )}
      {pfFormOpen && (
        <PfFormModal
          onClose={() => setPfFormOpen(false)}
          onSaved={() => { setPfFormOpen(false); setPfReloadKey(k => k + 1) }}
        />
      )}
      {addModal === 'add' && (
        <PositionFormModal
          mode="add"
          form={addForm}
          setForm={setAddForm}
          brokers={brokers}
          selectedBrokerCurrency={brokers.find(b => b.name === addForm.broker)?.currency ?? 'USDT'}
          tcBlue={dolar?.blue?.venta || 1415}
          onClose={() => setAddModal(null)}
          onSave={saveNewPosition}
          onChangeAsset={() => {
            setAddForm(f => ({ ...f, asset: '' }))
            setAddModal('add-flow')
          }}
        />
      )}

      {/* Edit posición — mismo PositionFormModal, mode='edit' */}
      {addModal === 'edit' && (
        <PositionFormModal
          mode="edit"
          form={addForm}
          setForm={setAddForm}
          brokers={brokers}
          selectedBrokerCurrency={brokers.find(b => b.name === addForm.broker)?.currency ?? 'USDT'}
          tcBlue={dolar?.blue?.venta || 1415}
          onClose={() => setAddModal(null)}
          onSave={saveEditPosition}
        />
      )}

      {/* Vender posición — SellModal de Positions.jsx con preview FIFO */}
      {addModal === 'sell' && (
        <SellModal
          form={sellForm}
          setForm={setSellForm}
          positions={positions}
          tcBlue={dolar?.blue?.venta || 1415}
          onClose={() => setAddModal(null)}
          onConfirm={confirmSell}
        />
      )}

      {/* Depositar / Retirar — modal simple para posiciones cash */}
      {addModal === 'cashflow' && (
        <Modal
          title={`${cashFlowForm.direction === 'deposit' ? 'Depositar en' : 'Retirar de'} ${cashFlowForm.broker}`}
          onClose={() => setAddModal(null)}
        >
          <div className="space-y-4">
            <p className="text-sm text-ink-2 leading-snug">
              {cashFlowForm.direction === 'deposit'
                ? 'Se acreditará al cash del broker y se registrará como aporte del mes en curso.'
                : 'Se debitará del cash del broker y se registrará como retiro del mes en curso.'}
            </p>
            {cashFlowForm.direction === 'withdraw' && (
              <p className="text-xs text-ink-3">
                Disponible: <span className="font-medium text-ink-1">
                  {cashFlowForm.available.toFixed(2)} {cashFlowForm.currency}
                </span>
              </p>
            )}
            <div>
              <label className="block text-xs text-ink-3 mb-1">
                Monto ({cashFlowForm.currency})
              </label>
              <input
                type="number"
                step="any"
                inputMode="decimal"
                autoFocus
                value={cashFlowForm.amount}
                onChange={e => setCashFlowForm(f => ({ ...f, amount: e.target.value }))}
                placeholder="0"
                className="w-full bg-bg-2 border border-line-2 rounded-md px-3 py-2 text-sm text-ink-0 focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60 transition"
              />
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setAddModal(null)}
                className="px-4 py-2 text-sm text-ink-3 hover:text-ink-0"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={confirmCashFlow}
                disabled={!+cashFlowForm.amount}
                className={`px-4 py-2 text-sm rounded-md font-medium text-white disabled:opacity-40 disabled:cursor-not-allowed transition ${
                  cashFlowForm.direction === 'deposit'
                    ? 'bg-rendi-pos hover:bg-rendi-pos/90'
                    : 'bg-data-amber hover:bg-data-amber/90'
                }`}
              >
                Confirmar {cashFlowForm.direction === 'deposit' ? 'depósito' : 'retiro'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* ─── Bottom sheet de acciones rápidas (header "Acciones") ─────────
          Paridad con los 4 CTAs del header del desktop. Cada item:
            1. Cierra el sheet
            2. Dispara su handler (open* o export)
          Para venta/cash, los handlers usan el selector inline del modal
          existente cuando hay múltiples opciones disponibles. */}
      {actionsSheet && (
        <ActionsSheet
          onClose={() => setActionsSheet(false)}
          positions={positions}
          brokers={brokers}
          onBuy={() => {
            setActionsSheet(false)
            openNewPositionFlow('mobile_actions_sheet')
          }}
          onSell={() => {
            const sellable = positions.filter(p => !p.is_cash)
            setActionsSheet(false)
            if (sellable.length === 0) {
              toast?.show?.('No tenés posiciones para vender. Agregá una primero.', { variant: 'info' })
              return
            }
            if (sellable.length === 1) {
              openSell(sellable[0])
              return
            }
            // >1: dejamos al user elegir desde la lista. Hacemos scroll
            // simple a la lista + toast con el hint.
            toast?.show?.('Tocá la posición que querés vender en la lista de abajo.', { variant: 'info' })
          }}
          onCash={() => {
            setActionsSheet(false)
            const firstBroker = brokers[0]
            if (!firstBroker) {
              toast?.show?.('Primero agregá un broker.', { variant: 'info' })
              return
            }
            // Buscamos cash position del primer broker; si no existe creamos
            // el form con available=0 para que el user pueda depositar.
            const cashPos = positions.find(p => p.broker === firstBroker.name && p.is_cash)
            if (cashPos) {
              openCashFlow(cashPos, 'deposit')
            } else {
              // Cash inicial: el form requiere un objeto position-like
              openCashFlow(
                { broker: firstBroker.name, asset: firstBroker.currency, is_cash: true, invested: 0 },
                'deposit'
              )
            }
          }}
        />
      )}
    </div>
  )

  // Save de Nueva Posición desde mobile — misma normalización que desktop
  // Positions.save(). La declaramos como inner function porque accede al state
  // del componente padre via closure.
  async function saveNewPosition() {
    const body = {
      ...addForm,
      buy_price:   addForm.buy_price   !== '' ? +addForm.buy_price   : null,
      quantity:    addForm.quantity    !== '' ? +addForm.quantity    : null,
      invested:    addForm.invested    !== '' ? +addForm.invested    : null,
      tc_compra:   addForm.tc_compra   !== '' ? +addForm.tc_compra   : null,
      commissions: addForm.commissions !== '' ? +addForm.commissions : 0,
      entry_date:  addForm.entry_date  || null,
    }
    try {
      await api.post('/positions', body)
      track('position_add_completed', { source: 'mobile_fab', asset: addForm.asset })
      setAddModal(null)
      setAddForm(EMPTY_POS)
      await loadAll()
    } catch (ex) {
      console.error('Save position error:', ex)
      alert('No pudimos guardar la posición. ' + (ex?.message || 'Probá de nuevo.'))
    }
  }
}

// ─── BrokerFilterChip ──────────────────────────────────────────────────────

function BrokerFilterChip({ active, onClick, label, currency }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 text-[11px] font-medium rounded-sm px-2.5 py-1.5 whitespace-nowrap transition-colors ${
        active
          ? 'bg-ink-0 text-bg-0 border border-ink-0'
          : 'bg-bg-2 border border-line/50 text-ink-1 hover:bg-bg-3'
      }`}
    >
      {label}
      {currency && (
        <span className={`text-[9px] font-mono uppercase tracking-caps px-1 py-px rounded-sm ${
          active ? 'bg-bg-0/15 text-bg-0' : 'bg-bg-3 text-ink-3'
        }`}>
          {currency}
        </span>
      )}
    </button>
  )
}

// ─── ColumnHeader ────────────────────────────────────────────────────────────
// Fila de rótulos para que cada columna "diga" qué muestra (antes no había
// labels y no se entendía qué era cada número). Currency-aware: en ARS la
// var. día y el P&L van en pesos; el total respeta el toggle global ARS/USD.
// El grid-template debe coincidir EXACTO con el de PositionRow para alinear.
function ColumnHeader({ currency, totalCurrency = 'USD' }) {
  const code = String(currency || '').toUpperCase() === 'ARS' ? 'ARS' : 'USD'
  const totalCode = String(totalCurrency || '').toUpperCase() === 'ARS' ? 'ARS' : 'USD'
  const numCls = 'flex flex-col items-end text-[9px] font-mono uppercase tracking-caps text-ink-3 leading-tight'
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_56px_64px_76px] gap-1.5 items-end px-3 py-1.5 bg-bg-1/50 border-b border-line/20">
      <span className="text-[9px] font-mono uppercase tracking-caps text-ink-3 self-end">Activo</span>
      <span className={numCls}><span>Var. día</span><span className="text-ink-3/60">{code}</span></span>
      <span className={numCls}><span>{'P&L'}</span><span className="text-ink-3/60">{code}</span></span>
      <span className={numCls}><span>Total</span><span className="text-ink-3/60">{totalCode}</span></span>
    </div>
  )
}

// ─── BrokerSection ─────────────────────────────────────────────────────────
// Header con nombre del broker + currency + valor total + acciones edit/delete.
// Debajo, las positions del broker (cash siempre al final).

const BrokerSection = memo(function BrokerSection({
  broker, positions, totalUsd, showDetail, displayCurrency = 'USD', tcBlue = 1,
  onEdit, onDelete,
  onSellPosition, onCashFlowPosition, onEditPosition, onDeletePosition,
}) {
  // Color asignado por nombre — estable entre re-renders. Antes el header
  // de cada broker era casi invisible (text-[11px] mono sobre bg-0). Ahora
  // cada sección tiene identidad visual clara: avatar circular con la
  // inicial, nombre en text-sm semibold, currency chip coloreado, y bg
  // sutil del color del broker.
  const color = brokerColor(broker.name)
  const initial = (broker.name || '?').charAt(0).toUpperCase()

  return (
    <section className="mt-3 first:mt-0">
      {/* Sticky header con identidad visual del broker. Sin backdrop-blur
          (es caro en mobile durante scroll). Usamos bg-bg-1 sólido (elevated
          surface) + border-y del color del broker para que el tinte venga
          del borde, el avatar y el texto — no del background semi-trans. */}
      <div className={`sticky top-[252px] z-10 px-3 py-2.5 flex items-center justify-between gap-2 bg-bg-1 border-y ${color.border}`}>
        <div className="flex items-center gap-2.5 min-w-0">
          {/* Avatar circular con la inicial del broker */}
          <span
            className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold tabular flex-shrink-0 ${color.text} ${color.bg} border ${color.border}`}
            aria-hidden="true"
          >
            {initial}
          </span>
          <div className="flex items-baseline gap-2 min-w-0">
            <span className={`text-sm font-semibold ${color.text} truncate`}>
              {broker.name}
            </span>
            <span className={`text-[9px] font-mono uppercase tracking-caps px-1.5 py-0.5 rounded-sm ${color.bg} ${color.text} border ${color.border} flex-shrink-0`}>
              {broker.currency}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <span className="text-sm font-semibold tabular text-ink-0">
            {compactValue(displayCurrency === 'ARS' ? totalUsd * tcBlue : totalUsd, displayCurrency)}
            <span className="text-[9px] font-mono uppercase tracking-caps text-ink-3 ml-1">
              {displayCurrency}
            </span>
          </span>
          <button
            type="button"
            onClick={onEdit}
            className="p-1.5 rounded-sm text-ink-3 hover:text-ink-0 hover:bg-bg-2 transition-colors"
            aria-label={`Editar ${broker.name}`}
          >
            <Pencil size={12} strokeWidth={1.75} />
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="p-1.5 rounded-sm text-ink-3 hover:text-rendi-neg hover:bg-bg-2 transition-colors"
            aria-label={`Eliminar ${broker.name}`}
          >
            <Trash2 size={12} strokeWidth={1.75} />
          </button>
        </div>
      </div>
      <ColumnHeader currency={broker.currency} totalCurrency={displayCurrency} />
      <ul className="divide-y divide-line/20">
        {positions.map(p => (
          <PositionRow
            key={`${p.broker}:${p.asset}:${p.id || p.entry_date}`}
            p={p}
            showDetail={showDetail}
            displayCurrency={displayCurrency}
            tcBlue={tcBlue}
            onSell={onSellPosition}
            onCashFlow={onCashFlowPosition}
            onEditPos={onEditPosition}
            onDeletePos={onDeletePosition}
          />
        ))}
      </ul>
    </section>
  )
})

// ─── Row ──────────────────────────────────────────────────────────────────
// Layout en 3 columnas para aprovechar el ancho:
//   [avatar]  TICKER · broker        P/L USD       $value USD
//             qty · CUR              +X.X%         USD
// Cash: NO muestra P/L (no tiene sentido la variación %). Solo value.
//
// Swipe izquierda revela acciones contextuales:
//   • No-cash: Analizar / Vender (FIFO) / Editar / Eliminar
//   • Cash:    Depositar / Retirar / Editar / Eliminar
//
// Las acciones gatillan callbacks del padre — el padre maneja los modales
// (SellModal, CashFlowModal, PositionFormModal). Esto evita que la fila
// arme su propio state y mantiene un único punto de truth.
//
// Componente MEMOIZADO — props (p + callbacks) son estables entre renders
// porque los callbacks se definen en el padre con closure sobre el state.
// Esto corta los re-render de la fila cada vez que prices cambia.

const PositionRow = memo(function PositionRow({ p, showDetail, displayCurrency = 'USD', tcBlue = 1, onSell, onCashFlow, onEditPos, onDeletePos }) {
  const cur = p.isAR ? 'ARS' : 'USD'
  const [aiOpen, setAiOpen] = useState(false)

  const actions = p.is_cash
    ? [
        // Posición cash → depositar / retirar
        onCashFlow && {
          id: 'deposit',
          label: 'Depositar',
          icon: ArrowDownLeft,
          tone: 'pos',
          onClick: () => {
            track('mobile_swipe_action', { code: 'cash_deposit', broker: p.broker })
            onCashFlow(p, 'deposit')
          },
        },
        onCashFlow && {
          id: 'withdraw',
          label: 'Retirar',
          icon: ArrowUpRight,
          tone: 'warn',
          onClick: () => {
            track('mobile_swipe_action', { code: 'cash_withdraw', broker: p.broker })
            onCashFlow(p, 'withdraw')
          },
        },
        onEditPos && {
          id: 'edit',
          label: 'Editar',
          icon: Pencil,
          tone: 'accent',
          onClick: () => {
            track('mobile_swipe_action', { code: 'edit_cash', broker: p.broker })
            onEditPos(p)
          },
        },
        onDeletePos && {
          id: 'delete',
          label: 'Eliminar',
          icon: Trash2,
          tone: 'neg',
          onClick: () => {
            track('mobile_swipe_action', { code: 'delete_cash', broker: p.broker })
            onDeletePos(p)
          },
        },
      ].filter(Boolean)
    : [
        // Posición normal (acción / bono / cripto) → analizar / vender / editar / eliminar
        {
          id: 'ai',
          label: 'Analizar',
          icon: Sparkles,
          tone: 'accent',
          onClick: () => {
            track('mobile_swipe_action', { code: 'analyze', asset: p.asset })
            setAiOpen(true)
          },
        },
        onSell && {
          id: 'sell',
          label: 'Vender',
          icon: TrendingDown,
          tone: 'neg',
          onClick: () => {
            track('mobile_swipe_action', { code: 'sell', asset: p.asset })
            onSell(p)
          },
        },
        onEditPos && {
          id: 'edit',
          label: 'Editar',
          icon: Pencil,
          tone: 'accent',
          onClick: () => {
            track('mobile_swipe_action', { code: 'edit', asset: p.asset })
            onEditPos(p)
          },
        },
        onDeletePos && {
          id: 'delete',
          label: 'Eliminar',
          icon: Trash2,
          tone: 'neg',
          onClick: () => {
            track('mobile_swipe_action', { code: 'delete', asset: p.asset })
            onDeletePos(p)
          },
        },
      ].filter(Boolean)

  return (
    <>
    <SwipeRow
      actions={actions}
      onTap={() => navigate(p.id ? `/posiciones/${p.id}` : '/posiciones')}
      rowId={`${p.broker}:${p.asset}:${p.id || ''}`}
    >
      <div
        className="grid grid-cols-[minmax(0,1fr)_56px_64px_76px] gap-1.5 items-center px-3 py-3 hover:bg-bg-2/30 active:bg-bg-3 transition-colors cursor-pointer"
      >
      {/* Col 1 — Activo: logo + ticker + (cantidad · moneda) */}
      <div className="flex items-center gap-2 min-w-0">
        <AssetLogo asset={p.asset} isCash={!!p.is_cash} size={28} />
        <div className="min-w-0">
          <div className="text-[13px] font-semibold text-ink-0 leading-none truncate">
            {fciLabel(p.asset)}
          </div>
          <div className="text-[10px] font-mono text-ink-3 leading-none mt-1 truncate">
            {p.is_cash ? 'Cash' : `${formatQty(p.quantity)} · ${cur}`}
          </div>
        </div>
      </div>

      {/* Col 2 — Var. día: variación de mercado (precio hoy vs cierre anterior) */}
      <div className="text-right min-w-0">
        {p.is_cash || p.dayVarLocal == null ? (
          <span className="text-[11px] text-ink-3" title="Sin cierre anterior disponible para este símbolo">—</span>
        ) : (
          <>
            <div className={`text-[13px] font-medium tabular leading-none ${colorClass(p.dayVarLocal)}`}>
              {compactAmount(p.dayVarLocal, cur)}
            </div>
            <div className={`text-[10px] font-mono tabular leading-none mt-1 ${colorClass(p.dayVarPct)}`}>
              {pctSigned(p.dayVarPct)}
            </div>
            {showDetail && p.isAR && p.dayVarUsd != null && (
              <div className="text-[9px] font-mono tabular leading-none mt-1 text-ink-3">
                {compactAmount(p.dayVarUsd, 'USD')}
              </div>
            )}
          </>
        )}
      </div>

      {/* Col 3 — P&L total (moneda del broker; USD revelado con "Detalle") */}
      <div className="text-right min-w-0">
        {p.is_cash || p.pnlLocal == null ? (
          <span className="text-[11px] text-ink-3">—</span>
        ) : (
          <>
            <div className={`text-[13px] font-medium tabular leading-none ${colorClass(p.pnlLocal)}`}>
              {compactAmount(p.pnlLocal, cur)}
            </div>
            <div className={`text-[10px] font-mono tabular leading-none mt-1 ${colorClass(p.pnlPct)}`}>
              {pctSigned(p.pnlPct)}
            </div>
            {showDetail && p.isAR && p.pnlUsd != null && (
              <div className="text-[9px] font-mono tabular leading-none mt-1 text-ink-3">
                {compactAmount(p.pnlUsd, 'USD')}
              </div>
            )}
          </>
        )}
      </div>

      {/* Col 4 — Total: valor actual; respeta el toggle global USD/ARS.
          En ARS los montos son grandes — usamos compactValue (k/M) para
          que no se rompa la columna. */}
      <div className="text-right min-w-0">
        <div className="text-[13px] font-medium tabular text-ink-0 leading-none">
          {compactValue(displayCurrency === 'ARS' ? p.valueUsd * tcBlue : p.valueUsd, displayCurrency)}
        </div>
        <div className="text-[9px] font-mono uppercase tracking-caps text-ink-2 leading-none mt-1">
          {displayCurrency}
        </div>
      </div>
      </div>
    </SwipeRow>
    {aiOpen && (
      <AnalysisDrawer
        open
        onClose={() => setAiOpen(false)}
        screen="position"
        params={{ asset: p.asset, broker: p.broker }}
        title="Análisis"
        subtitle={`${fciLabel(p.asset)} · ${p.broker}`}
      />
    )}
    </>
  )
})

function formatQty(q) {
  if (q == null || isNaN(q)) return '—'
  if (Math.abs(q) >= 1000) return Math.round(q).toLocaleString('en-US')
  if (Math.abs(q) >= 1) return q.toFixed(2).replace(/\.00$/, '')
  return q.toFixed(4)
}

// Monto compacto para las celdas estrechas de la tabla mobile. En ARS los
// montos son grandes (6-7 dígitos) y romperían el layout → se abrevian (k/M) y
// van SIN símbolo (en AR "$" se lee como pesos, ambiguo acá; la columna ya está
// rotulada "ARS"). USD va con "$" y separador de miles. Signo pegado al número.
function compactAmount(n, currency) {
  if (n == null || isNaN(n)) return '—'
  const sign = n > 0 ? '+' : n < 0 ? '−' : ''
  const abs = Math.abs(n)
  if (String(currency).toUpperCase() === 'ARS') {
    let body
    if (abs >= 1e6) body = (abs / 1e6).toFixed(abs >= 1e7 ? 0 : 1) + 'M'
    else if (abs >= 1e4) body = Math.round(abs / 1e3) + 'k'
    else if (abs >= 1e3) body = (abs / 1e3).toFixed(1) + 'k'
    else body = Math.round(abs).toLocaleString('es-AR')
    return `${sign}${body}`
  }
  return `${sign}$${Math.round(abs).toLocaleString('en-US')}`
}

// Total compacto (sin signo, siempre positivo) para la columna Total que es
// la más angosta. Misma lógica de abreviación que compactAmount pero sin
// prefijo y SIN '+'/'−'. Usado por Cartera total y por la columna Total de
// cada PositionRow cuando el toggle global está en ARS.
function compactValue(n, currency) {
  if (n == null || isNaN(n)) return '—'
  const abs = Math.abs(Math.round(n))
  if (String(currency).toUpperCase() === 'ARS') {
    if (abs >= 1e6) return '$' + (abs / 1e6).toFixed(abs >= 1e7 ? 0 : 1) + 'M'
    if (abs >= 1e4) return '$' + Math.round(abs / 1e3) + 'k'
    if (abs >= 1e3) return '$' + (abs / 1e3).toFixed(1) + 'k'
    return '$' + abs.toLocaleString('es-AR')
  }
  return '$' + abs.toLocaleString('en-US')
}


// ─── ActionsSheet ───────────────────────────────────────────────────────────
// Bottom sheet con los 4 atajos del header desktop. Se monta condicionalmente
// desde el render principal. Cada item dispara el handler que le corresponde
// y luego se cierra. Para Exportar CSV usa el endpoint /api/export/positions.csv
// con feature-gate de Plus/Pro (mismo que ExportCsvButton).
function ActionsSheet({ onClose, positions, brokers, onBuy, onSell, onCash }) {
  // Para Exportar CSV reusamos la lógica de ExportCsvButton inline (no podemos
  // usar el componente directamente porque queremos integrar el flow del
  // sheet). Mismo behavior: blob download + filename amistoso + fallback
  // upgrade modal si el user es Free.
  const [exporting, setExporting] = useState(false)
  const [showUpgrade, setShowUpgrade] = useState(false)
  // usePlanFeatures vive en el outer (hooks pueden romper si los importamos
  // acá doble). Para mantener el componente simple, no chequeamos pre-flight
  // — el backend responde 403 si Free y caemos al upgrade modal.

  async function handleExport() {
    if (exporting) return
    track('export_csv_downloaded', { resource: 'positions', source: 'mobile_actions_sheet' })
    setExporting(true)
    try {
      const blob = await api.getBlob('/export/positions.csv')
      const filename = `rendi_posiciones_${new Date().toISOString().slice(0, 10)}.csv`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      onClose()
    } catch (ex) {
      if (ex?.status === 403 && ex?.payload?.detail?.upgrade) {
        track('feature_blocked_clicked', { feature: 'export.csv', source: 'mobile_actions_sheet' })
        setShowUpgrade(true)
      } else {
        console.error('Export CSV failed:', ex)
        alert('No pudimos generar el CSV. Probá de nuevo.')
      }
    } finally {
      setExporting(false)
    }
  }

  const sellableCount = positions.filter(p => !p.is_cash).length
  const brokerCount = brokers.length

  const items = [
    {
      id: 'buy',
      icon: <Plus size={20} strokeWidth={2} />,
      label: 'Registrar compra',
      sub: 'Nueva posición en algún broker',
      onClick: onBuy,
      primary: true,
    },
    {
      id: 'sell',
      icon: <TrendingDown size={20} strokeWidth={2} />,
      label: 'Registrar venta',
      sub: sellableCount === 0
        ? 'Sin posiciones para vender todavía'
        : sellableCount === 1
          ? 'Vender tu única posición'
          : `Elegir entre ${sellableCount} posiciones`,
      onClick: onSell,
      disabled: sellableCount === 0,
    },
    {
      id: 'cash',
      icon: <Wallet size={20} strokeWidth={2} />,
      label: 'Cash · depósito / retiro',
      sub: brokerCount === 0 ? 'Agregá un broker primero' : 'Modificar saldo en alguno de tus brokers',
      onClick: onCash,
      disabled: brokerCount === 0,
    },
    {
      id: 'export',
      icon: <Download size={20} strokeWidth={2} />,
      label: exporting ? 'Exportando…' : 'Exportar CSV',
      sub: 'Bajá todas tus posiciones para tu contador',
      onClick: handleExport,
      disabled: exporting,
    },
  ]

  return (
    <>
      <div
        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-end"
        onClick={onClose}
      >
        <div
          onClick={(e) => e.stopPropagation()}
          className="w-full bg-bg-1 border-t border-line rounded-t-2xl px-4 pt-4 pb-8 max-h-[85vh] overflow-y-auto"
        >
          {/* Handle visual estilo bottom sheet iOS */}
          <div className="w-10 h-1 bg-ink-3/40 rounded-full mx-auto mb-4" aria-hidden="true" />

          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-ink-0">Acciones rápidas</h2>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-ink-3 hover:text-ink-0 hover:bg-bg-2 transition-colors"
              aria-label="Cerrar"
            >
              <X size={16} strokeWidth={2} />
            </button>
          </div>

          <div className="space-y-2">
            {items.map((it) => (
              <button
                key={it.id}
                type="button"
                disabled={it.disabled}
                onClick={it.onClick}
                className={`w-full flex items-center gap-3 px-4 py-3.5 rounded-lg border transition-colors ${
                  it.disabled
                    ? 'border-line/40 bg-bg-2/50 opacity-60 cursor-not-allowed'
                    : it.primary
                      ? 'border-data-violet/50 bg-data-violet/10 hover:bg-data-violet/20 active:bg-data-violet/25'
                      : 'border-line bg-bg-2 hover:bg-bg-3 active:bg-bg-3'
                }`}
              >
                <span className={`flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center ${
                  it.primary ? 'bg-data-violet/20 text-data-violet' : 'bg-bg-3 text-ink-1'
                }`}>
                  {it.icon}
                </span>
                <div className="flex-1 text-left min-w-0">
                  <p className={`text-sm font-medium ${it.primary ? 'text-data-violet' : 'text-ink-0'}`}>
                    {it.label}
                  </p>
                  <p className="text-xs text-ink-3 mt-0.5">{it.sub}</p>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      {showUpgrade && (
        <UpgradeModal
          feature="export.csv"
          onClose={() => setShowUpgrade(false)}
        />
      )}
    </>
  )
}

