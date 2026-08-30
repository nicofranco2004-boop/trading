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

import { useEffect, useMemo, useState, useRef, useCallback, lazy, Suspense, memo } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { ArrowDownUp, Search, Repeat, Star, Check, Briefcase, Sparkles, Plus, Pencil, Trash2, X, TrendingDown, TrendingUp, ArrowUpRight, ArrowDownLeft, Download, Wallet, ChevronDown, ChevronUp, ArrowRight, Layers as LayersIcon } from 'lucide-react'
import AnalysisDrawer from '../components/ai/AnalysisDrawer'
import AssetLogo from '../components/AssetLogo'
import FlashValue from '../components/FlashValue'
import EmptyState from '../components/EmptyState'
import BottomSheet from '../components/mobile/BottomSheet'
import Modal from '../components/Modal'
import UpgradeModal from '../components/plan/UpgradeModal'
// AddPositionFlow es un chunk pesado (~600 tickers de CRYPTO/STOCKS_US/CEDEARs/
// ETFs/INDICES/AR_LIDER/AR_GENERAL/BONDS_*). Lazy-load para que el primer
// render de /cartera no espere a parsearlo — solo cuando el user abre el flow.
const AddPositionFlow = lazy(() => import('../components/AddPositionFlow'))
import { PositionFormModal, SellModal, EMPTY_POS, today } from './Positions'
import PlazosFijosGroup from '../components/PlazosFijosGroup'
import RentaFijaSections from '../components/RentaFijaSections'
import { isFixedIncome } from '../utils/sections'
import PfFormModal from '../components/PfFormModal'
import SplitRatioBanner from '../components/SplitRatioBanner'
import { useToast } from '../components/Toast'
import { api } from '../utils/api'
import { fmtUsd, ars, pctSigned, colorClass } from '../utils/format'
import { priceSymbol, fciLabel, isArUsdBroker, costInPesos, costInUsd, pesoLotUsd, usdLotValue, isFciSym, trustMktValue, buildPriceSymbols, costBasisRate, cashAssetLabel, setBrokersRegistry, avgCostUsdPerUnit } from '../utils/valuation'
import { isBondPosition } from '../utils/tickers'
import TcMissingBadge from '../components/TcMissingBadge'
import { isCrypto, cryptoBrokerFactor } from '../utils/crypto'
import { useCurrency, pickFinancialRate } from '../contexts/CurrencyContext'
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

// Flag "este browser ya sabe que las columnas de la cartera se deslizan".
// Mismo patrón que utils/positionsDiscovered (`rendi_positions_discovered`) y
// que `rendi_ai_discovered`: valor '1', lectura defensiva porque en navegación
// privada `localStorage` puede tirar al leerlo, no sólo al escribirlo.
//
// ⚠️ AuthContext borra TODOS los `rendi_*` al logout salvo su PRESERVE list
// (hoy: `rendi_theme` y `rendi_ai_discovered`). Esta clave NO está ahí a
// propósito: si vuelve el aviso después de un logout+login, el costo es una
// línea de texto que se apaga al primer deslizamiento. Se decidió no tocar la
// lista de una decisión de seguridad por algo tan barato.
const PISTA_SCROLL_KEY = 'rendi_cartera_scroll_descubierto'

function yaDescubrioElScrollLateral() {
  try {
    return localStorage.getItem(PISTA_SCROLL_KEY) === '1'
  } catch {
    return false
  }
}

export default function PositionsMobile() {
  // Fase A (2026-05-31): currency global via context — sincroniza con Dashboard/HomeMobile.
  const { currency, toggle: toggleCurrency, setTcBlue: publishTcBlue, valuationDollar, costBasis } = useCurrency()
  const navigate = useNavigate()
  const location = useLocation()
  const toast = useToast()
  // ?action=sell (FAB) que llega antes de que carguen las posiciones → lo dejamos
  // pendiente y lo disparamos cuando termina de cargar (la venta necesita la lista).
  const pendingSellRef = useRef(false)
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
  // Vista agregada por ticker (paridad con desktop). Por defecto se ve UNA card
  // por ticker (posición agregada de todos los lotes). Se puede expandir a los
  // lotes individuales por ticker (tap en la card → expandedTickers) o global
  // con el toggle "Ver lotes" (showAllLots).
  const [expandedTickers, setExpandedTickers] = useState(() => new Set())
  const [showAllLots, setShowAllLots] = useState(false)
  function toggleTicker(key) {
    setExpandedTickers(prev => {
      const n = new Set(prev)
      n.has(key) ? n.delete(key) : n.add(key)
      return n
    })
  }
  // ¿Ya descubrió que las columnas se deslizan? Ver PistaDeScroll para el
  // porqué. Vive acá arriba y no en la tabla porque el aviso lo muestra UNA
  // sola (la primera) y lo apaga CUALQUIERA: si el estado viviera en cada
  // scroller, deslizar el de Balanz no apagaría el aviso del de Cocos.
  const [pistaScrollVisible, setPistaScrollVisible] = useState(() => !yaDescubrioElScrollLateral())
  // El ref corta las escrituras repetidas: `onScroll` dispara decenas de veces
  // por gesto y sin esto cada una pegaría en localStorage.
  const scrollYaDescubierto = useRef(false)
  const marcarScrollDescubierto = useCallback(() => {
    if (scrollYaDescubierto.current) return
    scrollYaDescubierto.current = true
    try { localStorage.setItem(PISTA_SCROLL_KEY, '1') } catch { /* navegación privada */ }
    setPistaScrollVisible(false)
  }, [])
  // Sheet "Ver y ordenar": se lleva el sort, el filtro por broker y "Ver lotes".
  // El toggle "Detalle USD" ya no está: cantidad y precio promedio, que era lo
  // que revelaba, ahora son columnas fijas de la tabla. El equivalente en USD
  // del P&L lo da el toggle global USD|ARS del header. Antes eran cuatro
  // controles pegados al header y sumaban
  // 235px de cromo pegajoso antes de la primera posición. Mismo patrón que el
  // sheet de filtros de Movimientos.
  const [viewSheet, setViewSheet] = useState(false)
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

  // Handler reusable de "Registrar venta". Usado por el FAB (?action=sell) y el
  // ActionsSheet. 0 tenencias → aviso; 1 → abre el SellModal directo; varias →
  // la lista de abajo, con un hint para que el user toque la que quiere vender.
  function openSellFlow(source) {
    track('position_sell_started', { source: source || 'unknown' })
    const sellable = positions.filter(p => !p.is_cash)
    if (sellable.length === 0) {
      toast.push('No tenés posiciones para vender. Agregá una primero.', { type: 'info' })
      return
    }
    if (sellable.length === 1) {
      openSell(sellable[0])
      return
    }
    toast.push('Tocá la posición que querés vender en la lista.', { type: 'info' })
  }

  // ─── Handlers de acciones por posición ──────────────────────────────────
  // Estos callbacks se pasan a PositionRow (memoizado) para que pueda
  // gatillar la acción correspondiente desde el swipe sheet.

  function openSell(p) {
    if (p.is_cash) return
    const broker = brokers.find(b => b.name === p.broker)
    const isARS = broker?.currency === 'ARS'
    // CEDEAR / sub-broker "· USD" / lote costInPesos: el instrumento es de BYMA y
    // se cotiza por su .BA (ARS). El exit_price va en la moneda del broker, así que
    // para un broker USD se presetea el .BA ÷ dólar-MEP (USD), consistente con cómo
    // se valúa. Para ARS se usa el .BA tal cual (ya está en pesos). La CRIPTO se
    // excluye del ruteo .BA: se sugiere el spot (× premium dólar-cripto si es un
    // broker AR no-exchange, igual que la valuación de la fila) — antes leía
    // prices['BTC.BA'] (key que ya no se fetchea) → prefillaba el COSTO stale y
    // una venta confirmada sin editar registraba P&L incorrecto.
    const local = !isCrypto(p.asset) && (p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker) || costInPesos(p))
    let price
    if (local && !isARS) {
      const priceArs = prices[priceSymbol(p.asset, true, p.asset_type)]
      price = priceArs != null ? priceArs / tcCedear : undefined
    } else if (isCrypto(p.asset)) {
      const spot = prices[p.asset]
      const f = cryptoBrokerFactor(p.asset, exchangeBrokerSet.has(p.broker), false, tcCripto, tcCedear)
      price = spot != null ? spot * f : undefined
    } else {
      price = prices[priceSymbol(p.asset, isARS, p.asset_type)]
    }
    // Guard anti-distorsión: si el precio de mercado es absurdo (bono per-100
    // leído per-1 → ×100) no lo sugerimos como precio de venta — caemos al costo
    // (buy_price). price y buy_price están en la MISMA moneda (per-unidad) → el
    // ratio que compara trustMktValue es válido.
    const priceOk = price != null && trustMktValue(price, p.buy_price, p.asset_type, false)
    const suggested = (priceOk ? price : p.buy_price) ?? p.buy_price ?? ''
    setSellForm({
      broker: p.broker,
      asset: p.asset,
      currency: broker?.currency || 'USDT',
      quantity: '',
      exit_price: suggested ? +(+suggested).toFixed(4) : '',
      tc_venta: isARS ? +(pickFinancialRate(dolar, valuationDollar) || 1415).toFixed(2) : '',
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
        // `tc_blue` es el TC con el que el depósito en pesos se asienta en
        // monthly_entries (que vive en USD) — o sea, el CAPITAL APORTADO, que es
        // el denominador del rendimiento. Mobile no lo mandaba: `CashFlowIn` no
        // valida campos de más, así que el `currency` que sí mandábamos se
        // ignoraba en silencio y `tc_blue` caía a su default DURO de 1415. Todo
        // depósito en pesos hecho desde el celular quedaba asentado a un dólar
        // inventado, y el aportado salía torcido en la proporción del desvío.
        // Desktop (Positions.jsx) siempre mandó el real; esto los empareja.
        tc_blue: tcBlue,
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

  // ?action=new / ?action=sell (FAB) → abrir el flow automáticamente. Limpiamos
  // el query param para que un reload posterior no re-abra el modal.
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const action = params.get('action')
    if (action === 'new') {
      openNewPositionFlow('mobile_fab')
      navigate('/posiciones', { replace: true })
    } else if (action === 'sell') {
      navigate('/posiciones', { replace: true })
      // La venta necesita la lista de posiciones (carga async): si ya cargó la
      // disparamos directo; si no, queda pendiente y la dispara el effect de abajo.
      if (!loading) openSellFlow('mobile_fab')
      else pendingSellRef.current = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search, brokers.length])

  // Dispara la venta pendiente del FAB cuando terminan de cargar las posiciones.
  useEffect(() => {
    if (!loading && pendingSellRef.current) {
      pendingSellRef.current = false
      openSellFlow('mobile_fab')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading])

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
      // El registry de brokers ES un input de la valuación: sin él,
      // isArUsdBroker cae a un fallback por NOMBRE (/·\s*USD$/) y un
      // sub-broker AR renombrado se precia por su ADR US en vez del .BA local
      // (~10× en GGAL/BMA), o queda congelado al costo si no tiene ADR. Acá no
      // se llamaba nunca: sus dos únicos llamadores eran Positions.jsx (código
      // muerto en mobile, corta antes en el fork) y useMonthlyData (sólo se
      // alcanza entrando al Dashboard). O sea que el número de esta pantalla
      // dependía de si el usuario había pasado antes por otra.
      setBrokersRegistry(bkrs || [])
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
    // Símbolos por el helper canónico (espejo de computeBrokerValue). ANTES esta
    // versión no pedía el .BA de los lotes costInPesos (ARS en broker USD, ej.
    // IOL sin sibling) → pesoLotUsd no encontraba la key y la fila caía a costo
    // (P&L 0, Var. día "—") SOLO en mobile — desktop sí lo pedía. También fixea
    // la cripto en '· USD' (se pedía BTC.BA; la valuación lee spot). El mismo
    // set alimenta /prices/prev-close → la Var. día del .BA compara .BA vs .BA.
    const all = buildPriceSymbols(pos, bkrs).join(',')
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

  const tcBlue = pickFinancialRate(dolar, valuationDollar) || 1415
  const tcCedear = pickFinancialRate(dolar, valuationDollar) || tcBlue  // dólar financiero p/ CEDEARs
  const tcCripto = dolar?.cripto?.venta  // dólar cripto (~spot+5%) p/ cripto en broker AR

  // Fase B: publish tcBlue al CurrencyContext (mismo pattern que Dashboard/HomeMobile)
  useEffect(() => {
    if (tcBlue > 0) publishTcBlue(tcBlue)
  }, [tcBlue, publishTcBlue])

  const arsBrokerSet = useMemo(
    () => new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name)),
    [brokers]
  )

  // Brokers que son EXCHANGE (Binance, Ripio…): la cripto adentro queda a spot.
  // En un broker NO-exchange (Cocos, Balanz…) la cripto se valúa al dólar cripto
  // (~spot+5%) para igualar al broker AR. cryptoBrokerFactor encapsula la regla.
  const exchangeBrokerSet = useMemo(
    () => new Set((brokers || []).filter(b => b.is_exchange).map(b => b.name)),
    [brokers]
  )

  // Enriquecemos cada posición con su valor USD y P&L %.
  // Para cash: NO computamos P/L (cash es cash, no tiene "variación").
  const enriched = useMemo(() => {
    return positions.map(p => {
      const isAR = arsBrokerSet.has(p.broker)
      const qty = p.quantity || 0
      const cashInvested = p.invested || 0
      // Costo económico = lo pagado + comisiones de compra. Es la definición de la
      // casa (computeBrokerValue, las filas del desktop, usdLotValue, pesoLotUsd y
      // el backend en persister.py:747); este archivo era el último que no la
      // seguía, y por eso la MISMA posición mostraba distinto P&L% en el celular
      // que en la computadora. El CASH no lleva comisión: usa `cashInvested`.
      const invested = cashInvested + (p.commissions || 0)
      // Costo en USD por moneda del LOTE, no de la cuenta: lote de COSTO EN DÓLARES
      // (currency='USD') EN BROKER ARS → tal cual, sin ÷blue (bono/ON/FCI-USD, CEDEAR-
      // MEP de Balanz); ARS broker → blue; lote en PESOS (currency='ARS') alojado en
      // cuenta USD → MEP (tcCedear); USD-nativo (incluida la acción US en broker USD)
      // → tal cual (última rama). Es también el fallback de valor cuando no hay precio.
      // Costo a HOY (mode-independent): base del guard anti-distorsión, del fallback
      // de valor sin precio, y de las magnitudes en PESOS de un broker ARS (el P&L y
      // el % en pesos NO dependen del "dólar de compra"). El costo DISPLAY en USD del
      // modo 'purchase' se calcula aparte abajo (investedUsdDisplay), solo para las
      // figuras en dólares. Así el modo nunca toca el valor ni las cifras en pesos.
      let investedUsd = isAR && costInUsd(p) ? invested
        : isAR ? invested / tcBlue
        : costInPesos(p) ? invested / tcCedear
        : invested
      let valueUsd = 0
      let priceLocal = null
      // ¿confiamos en el precio de mercado? false cuando el guard anti-distorsión
      // (trustMktValue) lo rechaza (bono per-100 leído per-1 → ×100) o no hay precio.
      // Gatea la Var.día de abajo: si el valor cayó a costo, no emitimos variación.
      let priceTrusted = false
      if (p.is_cash) {
        valueUsd = isAR ? cashInvested / tcBlue : cashInvested
        return {
          ...p, valueUsd, priceLocal: null, pnlUsd: null, pnlPct: null,
          // El efectivo TIENE costo, y es su propio valor. La casa lo dice
          // explícito en valuation.js (`investedUsd: cashUsd` con el comentario
          // "cash en pesos: invested USD = value USD (no FX gain)"), pero esta
          // rama no devolvía el campo: quedaba `undefined`. Mientras nadie lo
          // sumaba no se notaba; al agregar el pie TOTAL por broker, el efectivo
          // aportaba su valor y CERO costo, y el P&L del broker salía inflado
          // exactamente en el saldo en efectivo — medido: +$1.250 en Schwab,
          // que es su caja al dólar.
          investedUsd: valueUsd, investedUsdToday: valueUsd,
          pnlLocal: null, dayVarLocal: null, dayVarUsd: null, dayVarPct: null, isAR,
        }
      } else if (isAR && costInUsd(p)) {
        // Espejo de costInPesos: lote de COSTO EN DÓLARES (bono/ON/FCI-USD, o CEDEAR
        // comprado en dólar-MEP → currency='USD') que vive en un broker ARS (Balanz
        // importa cada pata en su moneda). El costo YA está en USD (investedUsd de
        // arriba, sin ÷blue); el VALOR va por el tipo de instrumento (usdLotValue:
        // CEDEAR/acción-AR por .BA÷MEP, resto por precio USD nativo). Sin esto, la
        // rama isAR de abajo dividía el costo USD por el blue → la fila colapsaba.
        // Gateado a broker ARS: una acción US genuina en broker USD NO entra acá
        // (usdLotValue le armaría 'AAPL.BA', inexistente) → cae al else que usa prices[US].
        const u = usdLotValue(p, prices, tcCedear)
        priceLocal = u.priceUsd
        // usdLotValue ya clampea: si no confía en el precio, valueUsd cae a su
        // investedUsd (con commissions). priceTrusted = hubo precio Y no fue clampeado.
        priceTrusted = u.priceUsd != null && u.valueUsd !== u.investedUsd
        // Value del helper; costo = investedUsd local (que ahora YA incluye las
        // comisiones, igual que usdLotValue) → sin precio confiable, P&L exacto 0.
        valueUsd = priceTrusted ? u.valueUsd : investedUsd
      } else if (isAR) {
        priceLocal = p.price_override ?? prices[priceSymbol(p.asset, true)]
        // Guard anti-distorsión: un precio absurdo (p.ej. bono per-100 leído per-1
        // → ×100) cae a costo. mkt y cost comparados en las MISMAS unidades (USD).
        if (priceLocal) {
          const mkt = (priceLocal * qty) / tcBlue
          priceTrusted = trustMktValue(mkt, investedUsd, p.asset_type, p.price_override != null)
          valueUsd = priceTrusted ? mkt : investedUsd
        }
        else valueUsd = investedUsd
      } else if ((p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker)) && !isCrypto(p.asset) && !isFciSym(p.asset) && p.price_override == null) {
        // Instrumento BYMA en broker USD (CEDEAR o acción AR como PAMP/YPFD en un
        // sub-broker "· USD"): precio LOCAL .BA (ARS) → USD via MEP, no el ticker
        // US. priceLocal queda en USD. El FCI-USD NO entra (su precio es el NAV en
        // USD → va al else, sin ÷MEP; si no, un FCI ruteado a "· USD" colapsaría).
        const priceArs = prices[priceSymbol(p.asset, true, p.asset_type)]
        priceLocal = priceArs != null ? priceArs / tcCedear : null
        if (priceLocal != null) {
          const mkt = priceLocal * qty
          priceTrusted = trustMktValue(mkt, investedUsd, p.asset_type, p.price_override != null)
          valueUsd = priceTrusted ? mkt : investedUsd
        }
        else valueUsd = investedUsd
      } else if (costInPesos(p)) {
        // Lote en PESOS (currency='ARS') NO-CEDEAR en cuenta USD (acción AR/bono
        // comprado en pesos): el VALOR va por su precio LOCAL .BA ÷ tcCedear, NO
        // por el ticker US. El costo (investedUsd) ya quedó en MEP arriba. f=1.
        const u = pesoLotUsd(p, prices, tcCedear)
        priceLocal = u.priceUsd
        // Sin precio → fallback al investedUsd local (con comisiones, igual que
        // pesoLotUsd) para que el P&L quede exactamente 0.
        // Guard: pesoLotUsd no clampea; envolvemos su salida acá (mkt vs invested USD).
        priceTrusted = u.priceUsd != null
          && trustMktValue(u.valueUsd, investedUsd, p.asset_type, p.price_override != null)
        valueUsd = priceTrusted ? u.valueUsd : investedUsd
      } else {
        // Key normalizada primero (BRK.B → 'BRK-B', la que el fetch pide), fallback
        // a la cruda. CEDEAR solo llega acá con override (la rama .BA lo captura).
        priceLocal = p.price_override ?? prices[priceSymbol(p.asset, false, p.asset_type)] ?? prices[p.asset]
        if (priceLocal) {
          const mkt = priceLocal * qty
          priceTrusted = trustMktValue(mkt, investedUsd, p.asset_type, p.price_override != null)
          valueUsd = priceTrusted ? mkt : investedUsd
        }
        else valueUsd = investedUsd
      }
      // Cripto en un broker NO-exchange (Cocos/Balanz…) se valúa al dólar cripto
      // (~spot+5%), no al spot, para igualar al broker AR. El factor escala valor
      // Y costo por igual ⇒ el P&L% queda intacto. Para todo lo demás (no-cripto,
      // exchanges, override, sin tasa) f=1 y nada cambia.
      // OJO — broker AR (isAR): la rama .BA de arriba YA trae el premium (el precio
      // '<c>.BA' viene en spot×cripto y se divide por el MEP ⇒ spot×cripto/MEP).
      // Aplicar el factor de nuevo acá lo DUPLICARÍA (spot×cripto²/MEP²). El factor
      // SOLO corre en las ramas que valúan al spot-USD por símbolo bare: cripto en
      // exchange (f=1) o en sub-broker '· USD' (f=cripto/MEP). Espejo EXACTO de
      // computeBrokerValue / PositionDetailMobile, que nunca aplican factor en ARS.
      const isExch = exchangeBrokerSet.has(p.broker)
      const f = isAR ? 1 : cryptoBrokerFactor(p.asset, isExch, p.price_override != null, tcCripto, tcCedear)
      if (f !== 1) { valueUsd *= f; investedUsd *= f }
      // Costo DISPLAY en USD del modo elegido: en 'purchase' los lotes en pesos van al
      // tc_compra del lote (los USD que realmente puso). Solo para lotes CON precio
      // confiable: sin cotización el P&L es 0 en cualquier vista → no inventamos
      // "pérdida por devaluación" sobre algo que no cotiza. f escala igual que
      // investedUsd. En 'today' investedUsdDisplay === investedUsd (byte-idéntico).
      const investedUsdDisplay = !priceTrusted ? investedUsd
        : (isAR && costInUsd(p)) ? invested * f
        : isAR ? (invested / costBasisRate(p, tcBlue, costBasis)) * f
        : costInPesos(p) ? (invested / costBasisRate(p, tcCedear, costBasis)) * f
        : invested * f
      // Regla del modo: las cifras en PESOS de un broker ARS son NATIVAS (el peso no
      // tiene "dólar de compra") → se derivan del costo de HOY (investedUsd). Las
      // cifras en USD reflejan el modo (investedUsdDisplay). En un broker USD el P&L
      // principal ES en USD → refleja el modo directamente.
      const pnlUsd = valueUsd - investedUsdDisplay        // P&L USD (refleja el modo)
      const pnlUsdToday = valueUsd - investedUsd          // P&L USD a hoy (base de las cifras en pesos)
      const pnlPct = isAR
        ? (investedUsd > 0 ? pnlUsdToday / investedUsd : 0)            // % en pesos, nativo
        : (investedUsdDisplay > 0 ? pnlUsd / investedUsdDisplay : 0)   // % en USD, refleja el modo
      // P&L en la moneda local del broker: ARS → P&L en pesos NATIVO; USD → P&L USD del modo.
      const pnlLocal = isAR ? pnlUsdToday * tcBlue : pnlUsd

      // ─── Variación diaria de mercado (precio hoy vs cierre anterior) ────────
      // Montos en la MISMA moneda local que el precio: ARS para .BA, USD resto.
      // Saltamos precios manuales (price_override no comparte fuente con el
      // cierre de mercado → comparación inválida). Cash ya retornó arriba.
      let dayVarLocal = null, dayVarUsd = null, dayVarPct = null
      // priceTrusted: si el guard rechazó el precio (valor cayó a costo), no
      // emitimos Var.día — sería una variación sobre un precio no confiable.
      if (!p.price_override && priceLocal != null && priceTrusted) {
        // costInPesos: el lote se valúa por su .BA÷MEP (pesoLotUsd) → la Var. día
        // usa el MISMO símbolo .BA para el cierre previo. ANTES caía al lookup
        // prevClose[p.asset] = el ADR US: GGAL local a 6,65 USD comparado contra
        // el cierre del ADR (~64 USD) daba "−90%" fantasma (aplica a GGAL/BMA/
        // SUPV/CEPU/LOMA/TGS, tickers que coinciden con su ADR). La cripto se
        // EXCLUYE del ruteo .BA (se valúa spot → prev spot, prevClose[p.asset]).
        const cedearUsd = !isAR && !isCrypto(p.asset) && (p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker) || costInPesos(p))
        // Lote de COSTO EN USD en broker ARS (rama isAR && costInUsd): priceLocal ya
        // está en USD (usdLotValue). El símbolo del cierre previo es el mismo que valúa
        // (priceSymbol(...,true,...) → '.BA' o 'FCI:'). Si es '.BA', el prevClose viene
        // en ARS → hay que pasarlo a USD (÷MEP) igual que el CEDEAR-USD; si no (FCI/
        // nativo USD), ya está en USD. Sin esto, priceLocal(USD) − prev(ARS) daba ~-100%.
        const usdInArBroker = isAR && costInUsd(p)
        const usdSymBA = usdInArBroker && priceSymbol(p.asset, true, p.asset_type).endsWith('.BA')
        const prevRaw = prevClose[(isAR || cedearUsd) ? priceSymbol(p.asset, true, p.asset_type) : p.asset]
        // priceLocal del CEDEAR-USD (o del lote USD-en-broker-ARS priceado por .BA) ya
        // está en USD; el cierre previo viene en ARS (.BA) → lo pasamos a USD ÷MEP.
        const prev = ((cedearUsd || usdSymBA) && prevRaw != null) ? prevRaw / tcCedear : prevRaw
        if (prev != null && prev > 0) {
          const perUnit = priceLocal - prev
          // Mismo factor cripto que el valor: el monto absoluto de var. día queda
          // coherente con el valor mostrado. El % (perUnit/prev) es invariante.
          if (usdInArBroker) {
            // Lote USD en broker ARS: perUnit ya está en USD (priceLocal y prev en USD).
            // dayVarUsd en USD; dayVarLocal en ARS al MISMO rate que la agregación
            // (curLocalValue = valueUsd × tcBlue) → el % agregado cierra aunque tcBlue y
            // tcCedear difirieran (hoy son el mismo pickFinancialRate, pero robusto).
            dayVarUsd = perUnit * qty
            dayVarLocal = dayVarUsd * tcBlue
          } else {
            dayVarLocal = perUnit * qty * f
            dayVarUsd = isAR ? dayVarLocal / tcBlue : dayVarLocal
          }
          dayVarPct = perUnit / prev
        }
      }
      return {
        // investedUsd expuesto = el DISPLAY (refleja el modo) para consumidores como
        // RentaFijaSections; investedUsdToday se carga aparte para la derivación de las
        // cifras en pesos al re-agregar por ticker.
        ...p, valueUsd, investedUsd: investedUsdDisplay, investedUsdToday: investedUsd,
        priceLocal, pnlUsd, pnlUsdToday, pnlPct, pnlLocal,
        // priceTrusted sube a la fila: sin cotización el valor ES el costo y el
        // P&L es 0 por construcción. La card lo dice ("al costo" / "sin
        // cotización") en vez de publicar un 0 que se lee como "no ganaste".
        priceTrusted,
        dayVarLocal, dayVarUsd, dayVarPct, isAR,
        // Columna "Precio prom.": ESPEJO del desktop, no una segunda definición.
        // Positions.jsx:1864 (broker ARS) y :2106-2109 (broker USD) rutean por
        // `avgCostUsdPerUnit`, que respeta el tc_compra del lote en modo
        // 'purchase'. La rama USD conserva el atajo `buy_price` cuando NINGÚN
        // lote tiene el costo en pesos — ahí el promedio ya está en dólares y
        // rutearlo no cambia nada; con costo en pesos, en cambio, tomar
        // `buy_price` crudo lo inflaría ~1500×.
        avgPriceUsd: avgPriceUsdDe(p, isAR, tcBlue, tcCedear, costBasis),
      }
    })
  }, [positions, prices, prevClose, arsBrokerSet, exchangeBrokerSet, tcBlue, tcCedear, tcCripto, costBasis])

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

  // ─── Agregación por ticker (paridad con la vista desktop) ────────────────
  // Junta los lotes (compras) del mismo (broker, asset) en UNA fila agregada:
  // cantidad total, precio compra promedio ponderado, P&L total y valor total.
  // Lote único: devolvemos la fila REAL tal cual (NO sintética) para que
  // editar/eliminar sigan operando sobre la posición real. Cash: nunca se
  // agrega (no tiene lotes ni P&L). El P&L no realizado de una posición abierta
  // = valor − costo, independiente del orden de lotes, así que sumar los lotes
  // abiertos da el costo correcto.
  function aggregateMobile(rows) {
    const cash = rows.filter(p => p.is_cash)
    const noCash = rows.filter(p => !p.is_cash)
    const byKey = new Map()
    for (const p of noCash) {
      const key = `${p.broker}:${p.asset}`
      if (!byKey.has(key)) byKey.set(key, [])
      byKey.get(key).push(p)
    }
    const out = []
    for (const [, lots] of byKey) {
      if (lots.length === 1) {
        // Una sola compra → la fila real (editar/eliminar siguen andando).
        out.push(lots[0])
        continue
      }
      const isAR = lots[0].isAR
      const totalQty = lots.reduce((s, x) => s + (x.quantity || 0), 0)
      const totalInv = lots.reduce((s, x) => s + (x.invested || 0), 0)
      const valueUsd = lots.reduce((s, x) => s + (x.valueUsd || 0), 0)
      // Reusa el costo USD ya resuelto por lote (costo por moneda del LOTE, no de la
      // cuenta) en vez de recomputarlo por broker. investedUsd = DISPLAY (modo);
      // investedUsdToday = a hoy, base de las cifras en pesos (nativas). Misma regla
      // que el memo por-lote: pesos de un broker ARS nativos, USD reflejan el modo.
      const investedUsd = lots.reduce((s, x) => s + (x.investedUsd || 0), 0)
      const investedUsdToday = lots.reduce((s, x) => s + (x.investedUsdToday ?? x.investedUsd ?? 0), 0)
      const pnlUsd = valueUsd - investedUsd
      const pnlUsdToday = valueUsd - investedUsdToday
      const pnlPct = isAR
        ? (investedUsdToday > 0 ? pnlUsdToday / investedUsdToday : 0)
        : (investedUsd > 0 ? pnlUsd / investedUsd : 0)
      const pnlLocal = isAR ? pnlUsdToday * tcBlue : pnlUsd
      // Var. día agregada: solo si algún lote la tiene (símbolo con cierre
      // anterior). Sumamos los montos de los lotes que la tienen; el % se
      // recalcula sobre el valor de mercado de ayer (valor hoy − var. día).
      const hasDay = lots.some(x => x.dayVarLocal != null)
      const dayVarLocal = hasDay ? lots.reduce((s, x) => s + (x.dayVarLocal || 0), 0) : null
      const dayVarUsd = hasDay ? lots.reduce((s, x) => s + (x.dayVarUsd || 0), 0) : null
      const curLocalValue = isAR ? valueUsd * tcBlue : valueUsd
      const dayVarPct = (hasDay && curLocalValue - (dayVarLocal || 0) > 0)
        ? dayVarLocal / (curLocalValue - dayVarLocal)
        : null
      out.push({
        ...lots[0],
        id: `agg:${lots[0].broker}:${lots[0].asset}`,
        quantity: totalQty,
        invested: totalInv,
        buy_price: totalQty > 0 ? totalInv / totalQty : null,
        price_override: null,
        valueUsd, investedUsd, investedUsdToday, pnlUsd, pnlUsdToday, pnlPct, pnlLocal,
        // El agregado se marca "sin cotización" sólo si NINGÚN lote tiene precio.
        // Con 2 de 3 lotes priceados el total es mayormente de mercado y decir
        // "sin cotización" mentiría al revés.
        priceTrusted: lots.some(x => x.priceTrusted),
        dayVarLocal, dayVarUsd, dayVarPct,
        _isAgg: true, _lotCount: lots.length, _lots: lots,
        // El promedio del AGREGADO se recalcula sobre todos los lotes. El
        // `...lots[0]` de arriba traía el del primer lote, que es el precio de
        // una sola compra y no el promedio del ticker.
        avgPriceUsd: avgPriceUsdDe({ ...lots[0], quantity: totalQty, _lots: lots }, isAR, tcBlue, tcCedear, costBasis),
      })
    }
    return [...out, ...cash]
  }

  // Aplana las filas agregadas a filas de lista: la fila del ticker + (si el
  // agregado está expandido) cada lote individual marcado con _isLot. La
  // expansión es por ticker (expandedTickers) o global (showAllLots).
  function flattenMobile(aggRows) {
    const out = []
    for (const p of aggRows) {
      const exp = showAllLots || expandedTickers.has(`t:${p.broker}:${p.asset}`)
      out.push(p._isAgg ? { ...p, _expanded: exp } : p)
      if (p._isAgg && exp) for (const lot of p._lots) out.push({ ...lot, _isLot: true })
    }
    return out
  }

  // Agrupación por broker (solo cuando filterBroker = ALL).
  // Cada grupo: { broker: brokerObj, positions: [...], totalUsd }
  const grouped = useMemo(() => {
    if (brokerFilter !== ALL_FILTER) return null
    const map = new Map()
    for (const p of filteredByBroker) {
      if (isFixedIncome(p)) continue   // renta fija → zona "Renta Fija" (abajo)
      const b = brokers.find(x => x.name === p.broker)
      if (!map.has(p.broker)) {
        map.set(p.broker, { broker: b || { name: p.broker, currency: 'USDT' }, positions: [], totalUsd: 0 })
      }
      const g = map.get(p.broker)
      g.positions.push(p)
      g.totalUsd += (p.valueUsd || 0)
    }
    // Agregar por ticker (1 fila por activo), ordenar (cash al final) y aplanar
    // a filas de lista (incluyendo lotes si el ticker está expandido). g.totalUsd
    // se computó sobre los lotes crudos, así que el total del broker no cambia.
    const groups = Array.from(map.values())
    for (const g of groups) {
      const agg = aggregateMobile(g.positions)
      agg.sort(comparePositions)
      g.positions = flattenMobile(agg)
    }
    groups.sort((a, b) => b.totalUsd - a.totalUsd)
    return groups
  }, [filteredByBroker, brokerFilter, brokers, sortBy, expandedTickers, showAllLots, tcBlue])

  // Lista plana cuando hay filtro de broker activo
  const flatList = useMemo(() => {
    if (brokerFilter === ALL_FILTER) return null
    const agg = aggregateMobile([...filteredByBroker])
    agg.sort(comparePositions)
    return flattenMobile(agg)
  }, [filteredByBroker, brokerFilter, sortBy, expandedTickers, showAllLots, tcBlue])

  // Totales del pie para la vista filtrada (que es un solo broker). Mismo
  // filtro anti-doble-conteo que BrokerSection: la fila agregada Y sus lotes
  // conviven en la lista cuando el ticker está expandido.
  const pieFiltrado = useMemo(() => {
    if (!flatList) return null
    const filas = flatList.filter(p => !p._isLot)
    const valorUsd = filas.reduce((s, p) => s + (p.valueUsd || 0), 0)
    const enPesos = currency === 'ARS'
    const invertidoUsd = filas.reduce(
      (s, p) => s + (enPesos ? (p.investedUsdToday ?? p.investedUsd ?? 0) : (p.investedUsd || 0)), 0)
    return {
      valorUsd, invertidoUsd,
      pnlUsd: valorUsd - invertidoUsd,
      pnlPct: invertidoUsd > 0 ? (valorUsd - invertidoUsd) / invertidoUsd : 0,
    }
  }, [flatList, currency])

  const total = enriched.reduce((s, p) => s + (p.valueUsd || 0), 0)
  const pfValueUsd = (pfTotals.USD?.valor || 0) + (pfTotals.ARS?.valor || 0) / tcBlue  // PF → USD para el total
  const pfInvestedUsd = (pfTotals.USD?.capital || 0) + (pfTotals.ARS?.capital || 0) / tcBlue

  // ─── El P&L no realizado del hero ───────────────────────────────────────
  // Espejo del desktop (Positions.jsx:1377-1398). Se deriva SUMANDO lo mismo
  // que publica cada fila —`investedUsd` / `investedUsdToday`— en vez de
  // recalcularlo por otro camino: así el número de arriba cierra con lo que se
  // lee abajo. Sumar `enriched` (no `grouped`) es a propósito: incluye la renta
  // fija, que vive en su propia zona, igual que el total.
  const invertidoUsd = enriched.reduce((s, p) => s + (p.investedUsd || 0), 0) + pfInvestedUsd
  const invertidoHoyUsd = enriched.reduce((s, p) => s + (p.investedUsdToday ?? p.investedUsd ?? 0), 0) + pfInvestedUsd
  // En pesos las cifras son mode-INDEPENDENT, como en el desktop: el peso no
  // tiene "dólar de compra", así que el invertido y el P&L en ARS no cambian
  // con el modo de costo. Es la misma regla que ya aplica la fila
  // (`pnlUsdToday × tcBlue`), y por eso el hero cierra con la suma de las filas.
  const heroInvertido = currency === 'ARS' ? invertidoHoyUsd * tcBlue : invertidoUsd
  const heroValor = currency === 'ARS' ? (total + pfValueUsd) * tcBlue : (total + pfValueUsd)
  const heroPnl = heroValor - heroInvertido
  const heroPct = heroInvertido > 0 ? heroPnl / heroInvertido : 0
  // Contador de posiciones reales (lotes), independiente de la vista
  // agregada/expandida — `flatList`/`grouped` ahora tienen filas sintéticas y
  // de lote que harían fluctuar el número al expandir/colapsar.
  const visibleCount = filteredByBroker.length

  // Los defaults de la vista, en UN solo lugar: el contador del botón y el
  // "Restablecer" del sheet se derivan de acá, no de literales sueltos.
  const VISTA_INICIAL = { sortBy: 'value', brokerFilter: ALL_FILTER, showAllLots: false }
  const vistaActual = { sortBy, brokerFilter, showAllLots }
  const ajustesActivos = Object.keys(VISTA_INICIAL)
    .filter(k => vistaActual[k] !== VISTA_INICIAL[k]).length
  // El hero baja un escalón de tipografía cuando el número no entra: 48px sirve
  // para "$41.417" pero no para "$58.977.218". Se mide por largo del string, que
  // es lo que determina el ancho con dígitos tabulares.
  const heroTexto = '$' + Math.round(currency === 'ARS' ? (total + pfValueUsd) * tcBlue : (total + pfValueUsd))
    .toLocaleString(currency === 'ARS' ? 'es-AR' : 'en-US')
  const heroClass = heroTexto.length >= 13 ? 'text-3xl' : heroTexto.length >= 10 ? 'text-4xl' : 'text-5xl'

  function restablecerVista() {
    setSortBy(VISTA_INICIAL.sortBy)
    setBrokerFilter(VISTA_INICIAL.brokerFilter)
    setShowAllLots(VISTA_INICIAL.showAllLots)
  }
  // El toggle "Detalle" solo aporta en brokers ARS (revela el equivalente USD).
  // Si el user no tiene ningún broker en pesos, no mostramos el botón.
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
      <header className="sticky top-[88px] z-20 bg-bg-0/95 backdrop-blur-md border-b border-line/40 px-4 py-3">
        {/* Fila 1 — el número por el que se entra a la pantalla, con su toggle al
            lado. Estaba en text-xl (el tamaño de un título de sección) y el
            toggle era el código de moneda en text-ink-3, sin borde: el dueño lo
            reportó como "falta el toggle", o sea que como control era invisible.
            El tamaño baja un escalón cuando el número es largo — en pesos son 8
            dígitos y a 48px no entran en 375px. */}
        <div className="flex items-center gap-3 mb-2.5">
          <div className={`${heroClass} font-medium tabular text-ink-0 leading-none tracking-tight min-w-0 truncate`}>
            <FlashValue value={total + pfValueUsd}>{heroTexto}</FlashValue>
          </div>
          <div className="ml-auto flex items-center gap-2 flex-shrink-0">
            {pricesLoading && (
              <span
                className="w-1.5 h-1.5 rounded-full bg-data-violet animate-pulse"
                title="Actualizando precios live"
                aria-label="Actualizando precios"
              />
            )}
            <div className="inline-flex bg-bg-2 border border-line/60 rounded p-0.5" role="group" aria-label="Moneda">
              {['USD', 'ARS'].map(c => (
                <button
                  key={c}
                  type="button"
                  onClick={() => { if (currency !== c) toggleCurrency() }}
                  aria-pressed={currency === c}
                  className={`px-2.5 py-1 text-xs font-medium rounded transition-colors ${
                    currency === c ? 'bg-bg-3 text-ink-0' : 'text-ink-3 hover:text-ink-1'
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* El P&L NO REALIZADO, que el desktop tiene en su hero y acá faltaba: el
            número por el que se entra a la pantalla no decía si vas ganando.
            Mismo par de chips que el desktop (Positions.jsx:1528-1545), en una
            línea de 12px para no devolverle cromo a un header del que venimos
            sacando. */}
        <div className="flex items-center gap-1.5 flex-wrap mb-2.5 text-[12px]">
          <span
            className={`inline-flex items-center gap-1 font-medium tabular rounded-full px-2 py-0.5 ${heroPnl >= 0 ? 'bg-rendi-pos/10 text-rendi-pos' : 'bg-rendi-neg/10 text-rendi-neg'}`}
            title="P&L no realizado"
          >
            {heroPnl >= 0
              ? <TrendingUp size={12} strokeWidth={1.75} aria-hidden="true" />
              : <TrendingDown size={12} strokeWidth={1.75} aria-hidden="true" />}
            {montoCard(heroPnl, currency, { signed: true })}
            <span className="opacity-80">· {pctSigned(heroPct)}</span>
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 bg-bg-2 text-ink-2 tabular">
            <span className="text-ink-3">Invertido</span>{montoCard(heroInvertido, currency)}
          </span>
        </div>

        {/* Fila 2 — búsqueda + los dos accesos. "Ver y ordenar" abre el sheet con
            el sort, el filtro por broker y los toggles; antes eran cuatro
            controles pegados al header. */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1 min-w-0">
            <Search size={13} strokeWidth={1.75} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar…"
              className="w-full bg-bg-2 border border-line/40 rounded pl-8 pr-3 py-2 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-rendi-accent/40"
            />
          </div>
          <button
            type="button"
            onClick={() => setViewSheet(true)}
            aria-label="Ver y ordenar"
            className="relative flex-shrink-0 inline-flex items-center justify-center w-9 h-9 rounded bg-bg-2 border border-line/60 text-ink-2 hover:text-ink-0 hover:bg-bg-3 transition-colors"
          >
            <ArrowDownUp size={14} strokeWidth={1.75} />
            {ajustesActivos > 0 && (
              <span className="absolute -top-1 -right-1 min-w-[15px] h-[15px] px-1 rounded-full bg-rendi-accent text-bg-0 text-[9px] font-semibold tabular flex items-center justify-center">
                {ajustesActivos}
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={() => setActionsSheet(true)}
            aria-label="Acciones rápidas"
            className="flex-shrink-0 inline-flex items-center justify-center w-9 h-9 rounded bg-data-violet hover:bg-data-violet/90 text-white transition-colors shadow-sm press"
          >
            <Plus size={16} strokeWidth={2.5} />
          </button>
        </div>
      </header>

      {/* CEDEARs con cambio de ratio (split) sin ajustar → pérdida fantasma. */}
      <div className="px-4 pt-3">
        <SplitRatioBanner onAdjusted={loadAll} />
      </div>

      {/* Los ajustes de vista viven en un sheet, así que la lista tiene que
          DECIR cuáles están puestos y ofrecer la salida sin volver a abrirlo —
          mismo requisito que se aplicó en Movimientos. */}
      {ajustesActivos > 0 && (
        <div className="mx-4 mt-3 flex items-center justify-between gap-2 rounded border border-line/60 bg-bg-1 px-3 py-2">
          <span className="text-[12.5px] text-ink-2 min-w-0 truncate">
            {[
              brokerFilter !== ALL_FILTER && brokerFilter,
              sortBy !== 'value' && `orden: ${SORT_OPTIONS.find(o => o.id === sortBy)?.label}`,
              showAllLots && 'por lote',
            ].filter(Boolean).join(' · ')}
          </span>
          <button
            type="button"
            onClick={restablecerVista}
            className="flex-shrink-0 text-[12.5px] text-data-blue hover:text-rendi-accent font-medium"
          >
            Quitar
          </button>
        </div>
      )}

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
            {grouped?.map((g, i) => (
              <BrokerSection
                key={g.broker.name}
                conPista={i === 0 && pistaScrollVisible}
                onDeslizar={marcarScrollDescubierto}
                broker={g.broker}
                positions={g.positions}
                totalUsd={g.totalUsd}
                displayCurrency={currency}
                tcBlue={tcBlue}
                onEdit={() => setEditingBroker({ ...g.broker })}
                onDelete={() => deleteBrokerAction(g.broker)}
                onSellPosition={openSell}
                onCashFlowPosition={openCashFlow}
                onEditPosition={openEditPosition}
                onDeletePosition={deletePosition}
                onToggleTicker={toggleTicker}
              />
            ))}
          </div>
          <div className="px-4 pb-2">
            <RentaFijaSections positions={enriched}
              valuePos={p => ({ valueUsd: p.valueUsd, investedUsd: p.investedUsd, pnlUsd: p.pnlUsd,
                // % en USD (refleja el modo), consistente con el $ de la fila y el
                // total de sección; NO el % nativo en pesos (p.pnlPct) que en 'purchase'
                // contradiría el $ USD. Espeja el desktop (valuePos re-computa pnlUsd/invUsd).
                pnlPct: p.investedUsd > 0 ? p.pnlUsd / p.investedUsd : 0 })}
              brokers={brokers} displayCurrency={currency} tcBlue={tcBlue} onChanged={loadAll} />
            <PlazosFijosGroup reloadKey={pfReloadKey} onAdd={() => setPfFormOpen(true)} onTotals={setPfTotals} brokers={brokers} onChange={loadAll} />
          </div>
        </>
      ) : (
        // Vista filtrada — lista plana del broker seleccionado
        <>
          <PositionsTable
            conPista={pistaScrollVisible}
            onDeslizar={marcarScrollDescubierto}
            pie={pieFiltrado && <PieDelBroker {...pieFiltrado} moneda={currency} tcBlue={tcBlue} />}
          >
            {flatList?.map(p => (
              <PositionRow
                key={p._isLot
                  ? `${p.broker}:${p.asset}:${p.id}`
                  : (p._isAgg ? `agg:${p.broker}:${p.asset}` : `${p.broker}:${p.asset}:${p.id || p.entry_date}`)}
                p={p}
                displayCurrency={currency}
                tcBlue={tcBlue}
                onSell={openSell}
                onCashFlow={openCashFlow}
                onEditPos={openEditPosition}
                onDeletePos={deletePosition}
                onToggleTicker={toggleTicker}
              />
            ))}
          </PositionsTable>
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
            // MAN-01: sin brokers, en vez de un dead-end ("creá desde Config")
            // ofrecemos crear el primero acá mismo (cierra el flow + abre el alta).
            onCreateBroker={() => { setAddModal(null); setShowAddBroker(true) }}
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
          onSaved={() => { setPfFormOpen(false); setPfReloadKey(k => k + 1); loadAll() }}
          brokers={brokers}
        />
      )}
      {addModal === 'add' && (
        <PositionFormModal
          mode="add"
          form={addForm}
          setForm={setAddForm}
          brokers={brokers}
          selectedBrokerCurrency={brokers.find(b => b.name === addForm.broker)?.currency ?? 'USDT'}
          tcBlue={pickFinancialRate(dolar, valuationDollar) || 1415}
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
          tcBlue={pickFinancialRate(dolar, valuationDollar) || 1415}
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
          tcBlue={pickFinancialRate(dolar, valuationDollar) || 1415}
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
      {/* Sheet "Ver y ordenar" — se lleva el sort, el filtro por broker y los
          dos toggles. Antes vivían pegados al header y eran la mitad del cromo. */}
      <BottomSheet
        open={viewSheet}
        onClose={() => setViewSheet(false)}
        eyebrow="Cartera"
        title="Ver y ordenar"
      >
        <div className="p-4 space-y-5">
          <OpcionesVista
            label="Ordenar por"
            options={SORT_OPTIONS}
            value={sortBy}
            onChange={setSortBy}
          />
          <OpcionesVista
            label="Broker"
            options={[{ id: ALL_FILTER, label: 'Todos' }, ...brokers.map(b => ({ id: b.name, label: b.name }))]}
            value={brokerFilter}
            onChange={setBrokerFilter}
          />
          <div>
            <div className="text-[12.5px] text-ink-2 mb-2 font-medium">Detalle</div>
            <div className="space-y-2">
              <FilaToggle
                label="Ver lotes"
                hint="Desglosa cada compra en vez de una card por ticker."
                active={showAllLots}
                onToggle={() => setShowAllLots(v => !v)}
              />
            </div>
          </div>
          <div className="pt-2 flex items-center gap-2">
            <button
              onClick={restablecerVista}
              className="flex-1 text-xs text-ink-2 hover:text-ink-0 border border-line/60 hover:bg-bg-2/60 rounded py-2.5 transition-colors font-medium"
            >
              Restablecer
            </button>
            <button
              onClick={() => setViewSheet(false)}
              className="flex-1 text-xs bg-rendi-pos/10 text-rendi-pos border border-rendi-pos/30 hover:bg-rendi-pos/15 rounded py-2.5 transition-colors font-medium"
            >
              Listo
            </button>
          </div>
        </div>
      </BottomSheet>

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
            setActionsSheet(false)
            openSellFlow('mobile_actions_sheet')
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
        <span className={`text-[9px] px-1 py-px rounded-sm ${
          active ? 'bg-bg-0/15 text-bg-0' : 'bg-bg-3 text-ink-3'
        }`}>
          {currency}
        </span>
      )}
    </button>
  )
}

// ─── Controles del sheet "Ver y ordenar" ────────────────────────────────────

function OpcionesVista({ label, options, value, onChange }) {
  return (
    <div>
      <div className="text-[12.5px] text-ink-2 mb-2 font-medium">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        {options.map(o => (
          <button
            key={o.id}
            onClick={() => onChange(o.id)}
            className={`text-xs px-3 py-1.5 rounded border transition-colors ${
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

function FilaToggle({ label, hint, active, onToggle }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={active}
      className={`w-full flex items-center justify-between gap-3 text-left rounded border px-3 py-2.5 transition-colors ${
        active ? 'bg-rendi-accent/10 border-rendi-accent/40' : 'bg-bg-2 border-line/60 hover:bg-bg-3'
      }`}
    >
      <span className="min-w-0">
        <span className={`block text-xs font-medium ${active ? 'text-rendi-accent' : 'text-ink-1'}`}>{label}</span>
        <span className="block text-[11px] text-ink-3 mt-0.5 leading-snug">{hint}</span>
      </span>
      <span className={`flex-shrink-0 w-9 h-5 rounded-full p-0.5 transition-colors ${active ? 'bg-rendi-accent/40' : 'bg-bg-3'}`}>
        <span className={`block w-4 h-4 rounded-full bg-ink-0 transition-transform ${active ? 'translate-x-4' : ''}`} />
      </span>
    </button>
  )
}

// ─── BrokerSection ─────────────────────────────────────────────────────────
// Header con nombre del broker + currency + valor total + acciones edit/delete.
// Debajo, las positions del broker (cash siempre al final).

const BrokerSection = memo(function BrokerSection({
  broker, positions, totalUsd, displayCurrency = 'USD', tcBlue = 1, conPista = false, onDeslizar,
  onEdit, onDelete,
  onSellPosition, onCashFlowPosition, onEditPosition, onDeletePosition, onToggleTicker,
}) {
  // Color asignado por nombre — estable entre re-renders. Antes el header
  // de cada broker era casi invisible (text-[11px] mono sobre bg-0). Ahora
  // cada sección tiene identidad visual clara: avatar circular con la
  // inicial, nombre en text-sm semibold, currency chip coloreado, y bg
  // sutil del color del broker.
  // ─── Los totales del pie ────────────────────────────────────────────────
  // ⚠️ Se suma SÓLO sobre las filas que NO son lote. `flattenMobile` mete la
  // fila AGREGADA de un ticker y, si está expandida, además cada uno de sus
  // lotes: sumar `positions` entero contaría dos veces lo mismo y el total
  // cambiaría al abrir y cerrar los lotes. Con este filtro hay exactamente una
  // entrada por ticker, expandido o no.
  const filasQueSuman = positions.filter(p => !p._isLot)
  const totValorUsd = filasQueSuman.reduce((s, p) => s + (p.valueUsd || 0), 0)
  // Igual que la fila y que el hero: en dólares el invertido refleja el modo de
  // costo; en pesos va el de HOY, porque el peso no tiene "dólar de compra".
  const enPesos = displayCurrency === 'ARS'
  const totInvertidoUsd = filasQueSuman.reduce(
    (s, p) => s + (enPesos ? (p.investedUsdToday ?? p.investedUsd ?? 0) : (p.investedUsd || 0)), 0)
  const totPnlUsd = totValorUsd - totInvertidoUsd
  const totPnlPct = totInvertidoUsd > 0 ? totPnlUsd / totInvertidoUsd : 0

  const color = brokerColor(broker.name)
  const initial = (broker.name || '?').charAt(0).toUpperCase()

  return (
    <section className="mt-3 first:mt-0">
      {/* Sticky header con identidad visual del broker. Sin backdrop-blur
          (es caro en mobile durante scroll). Usamos bg-bg-1 sólido (elevated
          surface) + border-y del color del broker para que el tinte venga
          del borde, el avatar y el texto — no del background semi-trans. */}
      {/* Separador, ya no sticky. Con la card por posición, dos capas pegadas
          (header + broker) se comían 285px de los 812 de un iPhone. */}
      <div className={`px-4 py-2.5 flex items-center justify-between gap-2 border-b ${color.border}`}>
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
            <span className={`text-[12.5px] px-1.5 py-0.5 rounded-sm ${color.bg} ${color.text} border ${color.border} flex-shrink-0 font-medium`}>
              {broker.currency}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <span className="text-sm font-semibold tabular text-ink-0">
            {montoCard(displayCurrency === 'ARS' ? totalUsd * tcBlue : totalUsd, displayCurrency)}
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
      <PositionsTable
        conPista={conPista}
        onDeslizar={onDeslizar}
        pie={
          <PieDelBroker
            valorUsd={totValorUsd}
            invertidoUsd={totInvertidoUsd}
            pnlUsd={totPnlUsd}
            pnlPct={totPnlPct}
            moneda={displayCurrency}
            tcBlue={tcBlue}
          />
        }
      >
        {positions.map(p => (
          <PositionRow
            key={p._isLot
              ? `${p.broker}:${p.asset}:${p.id}`
              : (p._isAgg ? `agg:${p.broker}:${p.asset}` : `${p.broker}:${p.asset}:${p.id || p.entry_date}`)}
            p={p}
            displayCurrency={displayCurrency}
            tcBlue={tcBlue}
            onSell={onSellPosition}
            onCashFlow={onCashFlowPosition}
            onEditPos={onEditPosition}
            onDeletePos={onDeletePosition}
            onToggleTicker={onToggleTicker}
          />
        ))}
      </PositionsTable>
    </section>
  )
})

// ─── Geometría de la tabla ────────────────────────────────────────────────
// Patrón Schwab: el símbolo queda ANCLADO a la izquierda y las columnas de
// valores se deslizan por debajo.
//
// ⚠️ FLEX, NO GRID. Con `display:grid` el bloque contenedor de un grid item es
// su PROPIA CELDA, así que `position:sticky` sólo puede pegarse dentro de esos
// 118px y después el ancla se va con el scroll. Con flex el bloque contenedor
// es la fila entera y el ancla se queda de punta a punta.
//
// ⚠️ Y NINGÚN ancestro de la fila puede tener `overflow:hidden` ni `transform`:
// cualquiera de los dos crea un nuevo bloque contenedor y el ancla vuelve a
// escaparse. MEDIDO en el prototipo: envolviendo la fila como lo hacía
// `SwipeRow` (un `overflow-hidden` + un `translateX`), con la tabla scrolleada
// al máximo el ancla pasa de quedarse en 0px a irse a −396px, o sea se va
// entera de pantalla. Por eso las filas ya NO van envueltas en SwipeRow y las
// acciones se abren con pulsación larga (ver PositionRow).
//
// Que las columnas escondidas se DESCUBRAN no es gratis: lo resuelve
// `PistaDeScroll`, un aviso de una sola vez debajo del primer scroller. Ver
// ahí por qué no alcanza con dejar asomar la próxima columna.
const ANCHO_ANCLA = 118
const ANCHO_COL = 108

// El orden es el del desktop (Valor · P&L · Var. día) y después lo que hasta
// ahora escondía el toggle "Detalle USD", que por eso desaparece del sheet.
const COLUMNAS = [
  { id: 'value', label: 'Valor' },
  { id: 'pnl', label: 'P&L' },
  { id: 'day', label: 'Hoy' },
  { id: 'qty', label: 'Cantidad' },
  { id: 'avg', label: 'Precio prom.' },
]

// Celda de valores: 108px, alineada a la derecha, hasta dos renglones (monto
// arriba, % abajo). A 108px los montos entran SIN abreviar — ése era el único
// motivo de existir de `compactAmount`/`compactValue`, que ya no están.
function Celda({ children }) {
  return (
    <div
      className="flex-none flex flex-col justify-center items-end px-2.5 text-right"
      style={{ width: ANCHO_COL, scrollSnapAlign: 'end' }}
    >
      {children}
    </div>
  )
}

const LINEA_1 = 'text-[14px] font-medium tabular leading-[1.15]'
const LINEA_2 = 'text-[11px] tabular leading-[1.15] mt-[3px]'

// Un guión cuando la columna no aplica (efectivo, o sin cotización previa).
function Vacio() {
  return <div className={`${LINEA_1} text-ink-3`}>—</div>
}

// La pista de descubrimiento. A 375px se ven el ancla + Valor + P&L, y quedan
// escondidas Hoy, Cantidad y Precio prom. — 307px de tabla a la derecha.
//
// POR QUÉ HACE FALTA UNA PISTA EXPLÍCITA. El recurso normal para anunciar un
// scroll horizontal es dejar asomar la punta de la próxima columna: la de
// Netflix, la del App Store, la del propio Schwab. Acá NO sirve, y se midió:
// de la columna "Hoy" asoman 17px, pero como las celdas van alineadas a la
// DERECHA el contenido se apoya contra el borde lejano y quedan 0px de texto
// visibles en las 5 filas medidas. O sea que el asomo existe y está vacío: se
// lee como "la tabla termina acá", que es exactamente lo contrario de lo que
// tendría que sugerir. La sombra del ancla tampoco alcanza sola sobre #07090C.
//
// Se muestra UNA VEZ y en el PRIMER scroller nada más (hay uno por broker;
// repetirlo ~10 veces sería volver a llenar de cromo la pantalla que venimos
// despejando). Se apaga apenas el usuario desliza CUALQUIER tabla, y no vuelve.
//
// Y sólo si HAY algo escondido de verdad — ver `usaDesbordeHorizontal`: los
// 307px de arriba son a 375px, pero esta pantalla llega hasta 767px y ahí la
// tabla entra entera.
function PistaDeScroll() {
  return (
    <p className="flex items-center justify-end gap-1.5 px-4 pt-2 text-[11px] text-ink-3">
      Deslizá para ver más columnas
      <ArrowRight size={12} strokeWidth={1.75} aria-hidden="true" />
    </p>
  )
}

// ─── El pie TOTAL de cada broker ──────────────────────────────────────────
// Lo que el desktop pone en su <tfoot> (Positions.jsx:2020-2046) más los chips
// del encabezado del broker: invertido, valor y P&L en monto Y porcentaje.
//
// NO es una fila de la tabla, y eso fue una corrección: primero lo hice con la
// geometría de las columnas, y en pesos "Invertido $27.330.405" se pasaba 5px
// del ancla de 118px. Un número recortado es un número que miente. Acá va a lo
// ancho de la pantalla, fuera del scroller, así que se lee entero y sin
// deslizar — que es justo el problema que este pie viene a resolver.
//
// Dos renglones para que entre en 375px con cifras en pesos de 8 dígitos.
function PieDelBroker({ valorUsd, invertidoUsd, pnlUsd, pnlPct, moneda, tcBlue }) {
  const aMoneda = n => (n == null ? null : moneda === 'ARS' ? n * tcBlue : n)
  const pnl = aMoneda(pnlUsd)
  return (
    <div className="px-4 py-2.5 bg-bg-1 border-t border-line-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold text-ink-2 tracking-wide">TOTAL</span>
        <span
          className={`inline-flex items-baseline gap-1.5 font-medium tabular rounded-full px-2 py-0.5 text-[12.5px] ${pnl >= 0 ? 'bg-rendi-pos/10 text-rendi-pos' : 'bg-rendi-neg/10 text-rendi-neg'}`}
          title="P&L no realizado"
        >
          {montoCard(pnl, moneda, { signed: true })}
          <span className="text-[11px] opacity-80">{pctSigned(pnlPct)}</span>
        </span>
      </div>
      <div className="flex items-baseline gap-3 mt-1 text-[11.5px] tabular">
        <span className="text-ink-3">
          Invertido <span className="text-ink-1">{montoCard(aMoneda(invertidoUsd), moneda)}</span>
        </span>
        <span className="text-ink-3">
          Valor <span className="text-ink-1">{montoCard(aMoneda(valorUsd), moneda)}</span>
        </span>
      </div>
    </div>
  )
}

// `conPista` la enciende sólo el primer scroller de la pantalla; `onDeslizar`
// avisa al padre que el gesto ya se descubrió. El umbral de 4px es para que un
// sub-píxel del rebote de `scroll-snap` no cuente como haber deslizado.
const PX_PARA_CONTAR_COMO_DESLIZADO = 4

// EL MISMO umbral decide si la pista se MUESTRA. No es simetría cosmética: es
// lo que vuelve inalcanzable el estado "pista indestructible". `useIsMobile`
// corta en 767px, pero la tabla mide fijo 658px, así que arriba de ~690px de
// viewport ya no desborda — y ahí el aviso decía "deslizá" con las cinco
// columnas a la vista, `onScroll` no podía dispararse nunca, el flag no se
// escribía y volvía en cada recarga, para siempre. Medido en la app a 744px
// (iPad mini vertical, y un Plus/Galaxy en horizontal anda por 736-740):
// clientWidth 712 = scrollWidth 712, scrollLeft máximo alcanzable 0.
// Atando las dos condiciones a la misma medida, si no se puede apagar tampoco
// se muestra.
function usaDesbordeHorizontal(ref, activo) {
  const [desborda, setDesborda] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!activo || !el) { setDesborda(false); return }
    const medir = () => setDesborda(el.scrollWidth - el.clientWidth > PX_PARA_CONTAR_COMO_DESLIZADO)
    medir()
    // Rotar el teléfono o achicar la ventana cambia la respuesta. Sin
    // ResizeObserver (jsdom en los tests) queda la medición del montaje.
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(medir)
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref, activo])
  return desborda
}

function PositionsTable({ children, pie = null, conPista = false, onDeslizar }) {
  const scroller = useRef(null)
  const hayColumnasEscondidas = usaDesbordeHorizontal(scroller, conPista)
  return (
    <>
    <div
      ref={scroller}
      className="overflow-x-auto overscroll-x-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      style={{ scrollSnapType: 'x proximity', WebkitOverflowScrolling: 'touch' }}
      onScroll={e => {
        if (e.currentTarget.scrollLeft > PX_PARA_CONTAR_COMO_DESLIZADO) onDeslizar?.()
      }}
    >
      <div className="w-max min-w-full">
        {/* Encabezado: scrollea CON el contenido, como en Schwab. Fijarlo arriba
            sumaría otra capa sticky a una pantalla de la que venimos sacando
            cromo. */}
        <div className="flex items-stretch w-max border-b border-line-2">
          <div
            className="sticky left-0 z-[2] flex-none bg-bg-0 flex items-end gap-2 pb-1.5 pr-2 text-[9.5px] text-ink-3"
            style={{ width: ANCHO_ANCLA }}
          >
            <span className="w-[3px] flex-none" aria-hidden="true" />
            <span>Activo</span>
          </div>
          {COLUMNAS.map(c => (
            <div
              key={c.id}
              className="flex-none flex items-end justify-end px-2.5 pb-1.5 text-[9.5px] text-ink-3"
              style={{ width: ANCHO_COL, scrollSnapAlign: 'end' }}
            >
              {c.label}
            </div>
          ))}
        </div>
        {children}
      </div>
    </div>
    {conPista && hayColumnasEscondidas && <PistaDeScroll />}
    {pie}
    </>
  )
}

// ─── Row ──────────────────────────────────────────────────────────────────
// Una fila de 72px: el ancla de 118px (barrita de color + logo + ticker +
// "broker · N lotes") y las cinco columnas de 108px que se deslizan.
//
// 72px es el intermedio: entran 7 posiciones en pantalla con el ticker a 13,5px
// y su contexto a 10px. La card anterior medía 164px y entraban dos.
//
// La barrita de color es la dirección del DÍA — verde, roja, o apagada cuando
// no hay cotización. Se lee sin leer.
//
// ACCIONES: antes se revelaban swipeando a la izquierda (SwipeRow). El swipe
// horizontal ahora es del scroll de columnas, y además el wrapper de SwipeRow
// rompía el `position:sticky` del ancla (ver la nota de geometría arriba). Las
// mismas acciones, sin perder ninguna, se abren con PULSACIÓN LARGA sobre la
// fila. El tap corto sigue navegando al detalle, como antes.
//
// Componente MEMOIZADO — props (p + callbacks) son estables entre renders
// porque los callbacks se definen en el padre con closure sobre el state.

// Pulsación larga que no pelea con el scroll: si el dedo se mueve más de 8px
// (está deslizando columnas) o se levanta antes, no dispara.
const MS_PULSACION = 450
const TOLERANCIA_PX = 8

const PositionRow = memo(function PositionRow({ p, displayCurrency = 'USD', tcBlue = 1, onSell, onCashFlow, onEditPos, onDeletePos, onToggleTicker }) {

  // El MONTO del P&L sigue al toggle global, como el desktop
  // (Positions.jsx:979: `const basePnl = isARS ? c.pnlArs : c.pnl`). Antes iba
  // en la moneda del BROKER (`pnlLocal`), así que con el toggle en pesos un
  // broker USD seguía mostrando dólares.
  // El PORCENTAJE no se toca: sigue siendo `p.pnlPct`, el retorno NOMINAL EN
  // PESOS para posiciones ARS, igual que el desktop. Es decisión del dueño.
  const pnlDisplay = displayCurrency === 'ARS' ? p.pnlUsdToday * tcBlue : p.pnlUsd
  const [aiOpen, setAiOpen] = useState(false)
  const [accionesAbiertas, setAccionesAbiertas] = useState(false)
  // Propio: `navigate` vive en PositionsMobile y este componente es hermano,
  // no hijo — sin este hook, tocar la fila tiraba ReferenceError y el detalle
  // mobile era inalcanzable.
  const navigate = useNavigate()

  const actions = p._isAgg
    ? [
        // Fila agregada (resumen multi-lote, sintética): Analizar + Vender +
        // "Editar lotes". Editar/Eliminar son POR LOTE (operan sobre una
        // posición real); "Editar lotes" despliega los lotes de este ticker
        // para que cada uno se edite/elimine desde su propia pulsación.
        {
          id: 'ai',
          label: 'Analizar',
          icon: Sparkles,
          tone: 'accent',
          onClick: () => {
            track('mobile_row_action', { code: 'analyze', asset: p.asset })
            setAiOpen(true)
          },
        },
        onSell && {
          id: 'sell',
          label: 'Vender',
          icon: TrendingDown,
          tone: 'neg',
          onClick: () => {
            track('mobile_row_action', { code: 'sell', asset: p.asset })
            onSell(p)
          },
        },
        onToggleTicker && {
          id: 'edit',
          label: p._expanded ? 'Ocultar lotes' : 'Editar lotes',
          icon: p._expanded ? ChevronUp : Pencil,
          tone: 'accent',
          onClick: () => {
            track('mobile_row_action', { code: p._expanded ? 'collapse_lots' : 'edit_expand', asset: p.asset })
            onToggleTicker(`t:${p.broker}:${p.asset}`)
          },
        },
      ].filter(Boolean)
    : p.is_cash
    ? [
        // Posición cash → depositar / retirar
        onCashFlow && {
          id: 'deposit',
          label: 'Depositar',
          icon: ArrowDownLeft,
          tone: 'pos',
          onClick: () => {
            track('mobile_row_action', { code: 'cash_deposit', broker: p.broker })
            onCashFlow(p, 'deposit')
          },
        },
        onCashFlow && {
          id: 'withdraw',
          label: 'Retirar',
          icon: ArrowUpRight,
          tone: 'warn',
          onClick: () => {
            track('mobile_row_action', { code: 'cash_withdraw', broker: p.broker })
            onCashFlow(p, 'withdraw')
          },
        },
        onEditPos && {
          id: 'edit',
          label: 'Editar',
          icon: Pencil,
          tone: 'accent',
          onClick: () => {
            track('mobile_row_action', { code: 'edit_cash', broker: p.broker })
            onEditPos(p)
          },
        },
        onDeletePos && {
          id: 'delete',
          label: 'Eliminar',
          icon: Trash2,
          tone: 'neg',
          onClick: () => {
            track('mobile_row_action', { code: 'delete_cash', broker: p.broker })
            onDeletePos(p)
          },
        },
      ].filter(Boolean)
    : [
        {
          id: 'ai',
          label: 'Analizar',
          icon: Sparkles,
          tone: 'accent',
          onClick: () => {
            track('mobile_row_action', { code: 'analyze', asset: p.asset })
            setAiOpen(true)
          },
        },
        onSell && {
          id: 'sell',
          label: 'Vender',
          icon: TrendingDown,
          tone: 'neg',
          onClick: () => {
            track('mobile_row_action', { code: 'sell', asset: p.asset })
            onSell(p)
          },
        },
        onEditPos && {
          id: 'edit',
          label: 'Editar',
          icon: Pencil,
          tone: 'accent',
          onClick: () => {
            track('mobile_row_action', { code: 'edit', asset: p.asset })
            onEditPos(p)
          },
        },
        onDeletePos && {
          id: 'delete',
          label: 'Eliminar',
          icon: Trash2,
          tone: 'neg',
          onClick: () => {
            track('mobile_row_action', { code: 'delete', asset: p.asset })
            onDeletePos(p)
          },
        },
      ].filter(Boolean)

  const irAlDetalle = (p._isLot || p.is_cash)
    ? () => navigate(p.id ? `/posiciones/${p.id}` : '/posiciones')
    : () => navigate(`/activo/${encodeURIComponent(p.asset)}`)

  // — Pulsación larga —
  const temporizador = useRef(null)
  const origen = useRef([0, 0])
  const yaDisparo = useRef(false)
  function cancelar() {
    if (temporizador.current) { clearTimeout(temporizador.current); temporizador.current = null }
  }
  function alPresionar(e) {
    if (!actions.length) return
    yaDisparo.current = false
    origen.current = [e.clientX, e.clientY]
    cancelar()
    temporizador.current = setTimeout(() => {
      yaDisparo.current = true
      setAccionesAbiertas(true)
    }, MS_PULSACION)
  }
  function alMover(e) {
    // Si el dedo se movió, está deslizando las columnas (o scrolleando la
    // lista): no es una pulsación.
    if (Math.abs(e.clientX - origen.current[0]) > TOLERANCIA_PX
      || Math.abs(e.clientY - origen.current[1]) > TOLERANCIA_PX) cancelar()
  }
  function alSoltar() { cancelar() }
  function alTocar() {
    // El click que sigue a una pulsación larga NO debe navegar además de abrir
    // las acciones.
    if (yaDisparo.current) { yaDisparo.current = false; return }
    irAlDetalle()
  }

  // La barrita: dirección del día. Apagada si no hay cotización (o es efectivo),
  // que es distinto de "no se movió".
  const barra = (p.is_cash || p.dayVarPct == null) ? 'bg-line-2'
    : p.dayVarPct > 0 ? 'bg-rendi-pos'
    : p.dayVarPct < 0 ? 'bg-rendi-neg'
    : 'bg-line-2'

  const valorDisp = displayCurrency === 'ARS' ? p.valueUsd * tcBlue : p.valueUsd
  const dayDisp = p.dayVarUsd == null ? null
    : displayCurrency === 'ARS' ? p.dayVarUsd * tcBlue : p.dayVarUsd
  const avgDisp = p.avgPriceUsd == null ? null
    : displayCurrency === 'ARS' ? p.avgPriceUsd * tcBlue : p.avgPriceUsd

  // La línea de contexto del ancla. Para un LOTE va la fecha de compra, que es
  // lo único que lo distingue de sus hermanos. Se corta la fecha a mano en vez
  // de parsearla: `entry_date` llega a veces con 'T' y a veces con espacio.
  const fecha = String(p.entry_date || '').slice(0, 10).split('-').reverse().join('/')
  const contexto = p.is_cash ? 'Efectivo'
    : p._isAgg ? `${p.broker} · ${p._lotCount} lotes`
    : p._isLot ? `${p.broker} · ${fecha || 'lote'}`
    : p.broker

  return (
    <>
    <div
      role="button"
      tabIndex={0}
      onClick={alTocar}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); irAlDetalle() } }}
      onPointerDown={alPresionar}
      onPointerMove={alMover}
      onPointerUp={alSoltar}
      onPointerCancel={alSoltar}
      onContextMenu={e => e.preventDefault()}
      className={`group flex items-stretch w-max min-h-[72px] border-b border-line/70 cursor-pointer active:bg-bg-1 ${p._isLot ? 'opacity-80' : ''}`}
      style={{ touchAction: 'pan-x pan-y' }}
    >
      {/* El ancla. `bg-bg-0` OPACO a propósito: es lo que tapa las columnas que
          pasan por debajo. La sombra del borde derecho es la señal de que hay
          contenido escondido. */}
      <div
        className="sticky left-0 z-[2] flex-none bg-bg-0 group-active:bg-bg-1 flex items-center gap-2 pr-2 [box-shadow:8px_0_10px_-8px_rgba(0,0,0,0.85)]"
        style={{ width: ANCHO_ANCLA }}
      >
        <span className={`w-[3px] self-stretch flex-none rounded-r ${barra}`} aria-hidden="true" />
        <AssetLogo asset={p.asset} isCash={!!p.is_cash} size={p._isLot ? 22 : 26} />
        <div className="min-w-0">
          <div className="text-[13.5px] font-semibold text-ink-0 leading-[1.15] truncate">
            {/* cashAssetLabel: el efectivo del sub-broker dólar de un broker AR se
                guarda como 'USDT' (centinela interno) pero son dólares reales. */}
            {p.is_cash ? cashAssetLabel(p) : fciLabel(p.asset)}
          </div>
          <div className="text-[10px] text-ink-3 leading-[1.15] mt-[2px] truncate">{contexto}</div>
        </div>
      </div>

      {/* Valor */}
      <Celda>
        <div className={`${LINEA_1} text-ink-0`}>
          <FlashValue value={p.valueUsd}>{montoCard(valorDisp, displayCurrency)}</FlashValue>
        </div>
        {!p.is_cash && !p.priceTrusted && (
          <div className={`${LINEA_2} text-ink-3`}>al costo</div>
        )}
      </Celda>

      {/* P&L — el monto y el % se colorean por SEPARADO. No es cosmético: para
          una posición ARS el % es el retorno NOMINAL EN PESOS y el monto sigue
          al toggle, así que pueden tener signos distintos (AL30: −$44 en USD,
          +0,4% en pesos). Pintarlos del mismo color haría pasar uno de los dos
          por lo que no es. */}
      <Celda>
        {p.is_cash ? <Vacio /> : !p.priceTrusted ? (
          /* Sin cotización el valor ES el costo y el P&L es 0 por construcción.
             Publicar "+0,0%" se lee como "no ganaste" cuando lo que pasa es
             "no sé cuánto vale". */
          <div className={`${LINEA_2} text-ink-3`}>sin cotización</div>
        ) : (
          <>
            <div className={`${LINEA_1} ${colorClass(pnlDisplay)}`}>
              {montoCard(pnlDisplay, displayCurrency, { signed: true })}
            </div>
            <div className={`${LINEA_2} ${colorClass(p.pnlPct)}`}>{pctSigned(p.pnlPct)}</div>
          </>
        )}
      </Celda>

      {/* Hoy */}
      <Celda>
        {(p.is_cash || p.dayVarPct == null || dayDisp == null) ? <Vacio /> : (
          <>
            <div className={`${LINEA_1} ${colorClass(dayDisp)}`}>
              {montoCard(dayDisp, displayCurrency, { signed: true })}
            </div>
            <div className={`${LINEA_2} ${colorClass(p.dayVarPct)}`}>{pctSigned(p.dayVarPct)}</div>
          </>
        )}
      </Celda>

      {/* Cantidad */}
      <Celda>
        {p.is_cash ? <Vacio /> : (
          <>
            <div className={`${LINEA_1} text-ink-0`}>{formatQty(p.quantity)}</div>
            <div className={`${LINEA_2} text-ink-3`}>{unidadDe(p)}</div>
          </>
        )}
      </Celda>

      {/* Precio prom. */}
      <Celda>
        {(p.is_cash || avgDisp == null) ? <Vacio /> : (
          <div className={`${LINEA_1} text-ink-0`}>{precioCard(avgDisp, displayCurrency)}</div>
        )}
      </Celda>
    </div>

    {/* Las acciones de la fila, por pulsación larga. Son las MISMAS que revelaba
        el swipe: no se perdió ninguna. */}
    {accionesAbiertas && (
      <BottomSheet
        open
        onClose={() => setAccionesAbiertas(false)}
        title={p.is_cash ? cashAssetLabel(p) : fciLabel(p.asset)}
        eyebrow={contexto}
      >
        <div className="px-4 pb-4 space-y-1">
          {actions.map(a => {
            const Icon = a.icon
            return (
              <button
                key={a.id}
                type="button"
                onClick={() => { setAccionesAbiertas(false); a.onClick() }}
                className={`w-full flex items-center gap-3 px-3 py-3 rounded text-[15px] font-medium text-left active:bg-bg-2 transition-colors ${TONO_ACCION[a.tone] || 'text-ink-0'}`}
              >
                {Icon && <Icon size={17} strokeWidth={1.75} />}
                {a.label}
              </button>
            )
          })}
        </div>
      </BottomSheet>
    )}

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

// El tono ya no pinta un botón de fondo entero (como en el swipe) sino el texto
// y el ícono de una fila del sheet.
const TONO_ACCION = {
  pos: 'text-rendi-pos',
  neg: 'text-rendi-neg',
  warn: 'text-rendi-warn',
  accent: 'text-ink-0',
  neutral: 'text-ink-0',
}

// Monto de card: sin abreviar y SIN el código de moneda. El código lo dice el
// segmentado del header y la línea del valor; repetirlo en cada chip es lo que
// hacía que "+$1.794.240 ARS" no entrara y se cortara en "+$1.794.240 A…".
function montoCard(n, currency, { signed = false } = {}) {
  if (n == null || isNaN(n)) return '—'
  const isArs = String(currency).toUpperCase() === 'ARS'
  const abs = Math.abs(n)
  const body = abs.toLocaleString(isArs ? 'es-AR' : 'en-US', { maximumFractionDigits: 0 })
  const sign = signed ? (n > 0 ? '+' : n < 0 ? '−' : '') : (n < 0 ? '−' : '')
  return `${sign}$${body}`
}

function formatQty(q) {
  if (q == null || isNaN(q)) return '—'
  if (Math.abs(q) >= 1000) return Math.round(q).toLocaleString('en-US')
  if (Math.abs(q) >= 1) return q.toFixed(2).replace(/\.00$/, '')
  return q.toFixed(4)
}

// El PRECIO sí lleva decimales: `montoCard` redondea a entero (sirve para un
// valor de cartera, no para un precio unitario — un CEDEAR a US$14,37 se
// mostraría "US$14").
function precioCard(n, currency) {
  if (n == null || isNaN(n)) return '—'
  const isArs = String(currency).toUpperCase() === 'ARS'
  const abs = Math.abs(n)
  // Precios chicos (cripto, un bono per-1) necesitan más resolución que una
  // acción; sin esto una posición a US$0,0043 se lee "$0,00".
  const dec = abs >= 1000 ? 0 : abs >= 1 ? 2 : 4
  const body = abs.toLocaleString(isArs ? 'es-AR' : 'en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec })
  return `${n < 0 ? '−' : ''}$${body}`
}

// La unidad en la que se cuenta la posición. Un FCI tiene cuotapartes y un bono
// valor nominal; llamarlos "unidades" a los tres es lo que hacía la fila vieja.
function unidadDe(p) {
  if (isFciSym(p.asset)) return 'cuotapartes'
  if (isBondPosition(p)) return 'nominales'
  return 'unidades'
}

// Precio promedio en USD — ESPEJO del desktop (Positions.jsx:1864 y :2106-2109).
// Vive a nivel de módulo porque lo necesitan DOS lugares con el mismo criterio:
// el memo por-lote y la fila agregada por ticker (que promedia sobre `_lots`,
// no sobre el primer lote).
function avgPriceUsdDe(p, isAR, tcBlue, tcCedear, costBasis) {
  if (!p || p.is_cash || !(p.quantity > 0)) return null
  if (isAR) return avgCostUsdPerUnit(p, tcBlue, costBasis, true)
  const lotes = (p._lots && p._lots.length) ? p._lots : [p]
  if (lotes.some(l => costInPesos(l))) return avgCostUsdPerUnit(p, tcCedear, costBasis, false)
  return p.buy_price ?? (p.invested ? p.invested / p.quantity : null)
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

