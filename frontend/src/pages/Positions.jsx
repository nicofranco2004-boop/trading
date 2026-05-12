import { useEffect, useMemo, useState, useRef, Fragment } from 'react'
import { Plus, Pencil, Trash2, DollarSign, ArrowDownCircle, ArrowUpCircle, ChevronDown, ChevronUp, Wallet, ShoppingCart, TrendingUp, TrendingDown, Coins, Layers as LayersIcon } from 'lucide-react'
import ActionMenu from '../components/ActionMenu'
import Modal from '../components/Modal'
import TickerSearch from '../components/TickerSearch'
import DateInput from '../components/DateInput'
import StatCard from '../components/StatCard'
import { useToast } from '../components/Toast'
import AssetLogo from '../components/AssetLogo'
import AddPositionFlow from '../components/AddPositionFlow'
import BondCashflowModal from '../components/BondCashflowModal'
import PendingCashflowsBanner from '../components/PendingCashflowsBanner'
import { isBondTicker } from '../utils/tickers'
import { detectPendingCashflows } from '../utils/pendingCashflows'
import { getBondMeta, formatBondType, formatCouponFreq, formatCouponLabel, formatCouponTooltip } from '../utils/bondMeta'
import {
  generateSchedule,
  getRemainingPayments,
  estimateYieldDetailed,
  nextPaymentForPosition,
} from '../utils/bondSchedule'
import { usd, ars, pct, fmtUsd, fmtArs, pctSigned, colorClass } from '../utils/format'
import { api } from '../utils/api'
import { computeBrokerValue } from '../utils/valuation'
import PageHeader from '../components/PageHeader'
import EmptyState from '../components/EmptyState'

const REFRESH_MS = 90_000

const today = () => new Date().toISOString().slice(0, 10)

const EMPTY_POS = {
  broker: '', asset: '', is_cash: false,
  buy_price: '', quantity: '', invested: '', tc_compra: '', commissions: '', notes: '',
  entry_date: '',
}

const BROKER_COLORS = [
  { text: 'text-blue-500 dark:text-blue-400', bg: 'bg-blue-600/20', hover: 'hover:bg-blue-600/30' },
  { text: 'text-violet-500 dark:text-violet-400', bg: 'bg-violet-600/20', hover: 'hover:bg-violet-600/30' },
  { text: 'text-emerald-500 dark:text-emerald-400', bg: 'bg-emerald-600/20', hover: 'hover:bg-emerald-600/30' },
  { text: 'text-amber-500 dark:text-amber-400', bg: 'bg-amber-600/20', hover: 'hover:bg-amber-600/30' },
  { text: 'text-cyan-500 dark:text-cyan-400', bg: 'bg-cyan-600/20', hover: 'hover:bg-cyan-600/30' },
]

export default function Positions() {
  const [positions, setPositions] = useState([])
  const [prices, setPrices] = useState({})
  const [config, setConfig] = useState({ tc_mep: 1415, tc_blue: 1415 })
  const [dolar, setDolar] = useState(null)
  const [brokers, setBrokers] = useState([])
  const [snapshots, setSnapshots] = useState([])
  const toast = useToast()
  const [modal, setModal] = useState(null)
  const [form, setForm] = useState(EMPTY_POS)
  const [sellForm, setSellForm] = useState({ broker: '', asset: '', currency: 'USDT', quantity: '', exit_price: '', tc_venta: '', date: '', commissions: '' })
  const [cashFlowForm, setCashFlowForm] = useState({ broker: '', currency: 'USDT', direction: 'deposit', amount: '', available: 0 })
  const [convertForm, setConvertForm] = useState({
    direction: 'ars_to_usd',  // 'ars_to_usd' | 'usd_to_ars'
    from_broker: '',
    available: 0,
    kind: 'MEP',
    ars_amount: '',
    usd_amount: '',
    tc: '',
    date: today(),
  })
  const [lastUpdated, setLastUpdated] = useState(null)
  // Per-broker "show detail" state. Default = collapsed (clean view).
  // Stored as a Set of broker names; flipping a name toggles its detail mode.
  const [detailBrokers, setDetailBrokers] = useState(() => new Set())
  // Estado del modal de cobranza de bonos. null = cerrado; {flowType, broker, brokerCurrency, asset} = abierto.
  const [bondCashflow, setBondCashflow] = useState(null)
  // Posiciones de bono expandidas inline (mostrar meta + historial cobranzas).
  // Keyeado por `${broker}:${asset}` para que múltiples bonos puedan estar abiertos.
  const [expandedBonds, setExpandedBonds] = useState(() => new Set())
  // Listado plano de ops Cupón/Amortización (cobranzas de bonos). Se carga
  // de /operations al montar y se refresca con loadAll() después de un INSERT.
  // Lo agrupamos por `${broker}:${asset}` vía useMemo en `bondCashflowsByKey`.
  const [bondOps, setBondOps] = useState([])
  // Phase 3C: serie diaria de CER, fetcheada lazy cuando el user expande un
  // bono CER. Cache shared para todos los bonos CER (la serie es la misma).
  // null = no se intentó fetch; {} = se intentó pero vino vacío (graceful);
  // dict no-vacío = serie disponible.
  const [cerSeries, setCerSeries] = useState(null)
  const [cerStale, setCerStale] = useState(false)
  // Phase 3E: skips de cobranzas teóricas (pagos del cronograma que el user
  // marcó como "no aplica"). Persistido en backend; lo cargamos al mount.
  const [bondSkips, setBondSkips] = useState([])
  const latestRef = useRef({})

  // TC blue/MEP derivados — se declaran ACÁ (arriba de los useMemo que los
  // consumen vía closure/deps) para evitar ReferenceError por temporal dead
  // zone si JS evalúa el array de deps antes de la declaración de `const`.
  const tcBlue = dolar?.blue?.venta || config.tc_blue || 1415
  const tcMep = dolar?.mep?.venta || config.tc_mep || 1415

  // Carga la serie CER del backend (idempotente — sólo la primera llamada
  // dispara fetch real, las siguientes son cache hit en `cerSeries`).
  async function ensureCerSeries() {
    if (cerSeries !== null) return cerSeries
    try {
      const res = await api.get('/bond-indices/CER')
      setCerSeries(res.series || {})
      setCerStale(!!res.stale)
      return res.series || {}
    } catch {
      setCerSeries({})
      setCerStale(true)
      return {}
    }
  }

  function toggleBondExpand(p) {
    const key = `${p.broker}:${p.asset}`
    setExpandedBonds(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
    // Si es CER y la serie aún no se trajo, traerla async (no bloqueante).
    const meta = getBondMeta(p.asset)
    if (meta?.type === 'cer') ensureCerSeries()
  }

  function openBondCashflow(p, flowType) {
    const broker = brokers.find(b => b.name === p.broker)
    setBondCashflow({
      flowType,
      broker: p.broker,
      brokerCurrency: broker?.currency || 'USDT',
      asset: p.asset,
      // Phase 3D: pasamos la posición para que el modal pueda pre-llenar la
      // fecha + monto estimado del próximo pago según el cronograma.
      position: p,
    })
  }

  // Phase 3E — Inbox de cobranzas pendientes (detección + acciones)
  // ────────────────────────────────────────────────────────────────────────
  // Compara cronograma teórico vs operations vs skips para listar pagos
  // pendientes de confirmar. Usa los mismos bondOps + bondSkips ya cargados.
  const pendingCashflows = useMemo(() => {
    return detectPendingCashflows(positions, bondOps, bondSkips)
  }, [positions, bondOps, bondSkips])

  // Click "Confirmar" en un item del inbox → abre BondCashflowModal con la
  // posición correspondiente. El modal usa nextPaymentForPosition para
  // pre-llenar fecha + monto (ya implementado en Phase 3D — Nivel 1).
  function confirmPendingCashflow(item) {
    const flowType = item.kind === 'amortizacion' ? 'amortization' : 'coupon'
    openBondCashflow(item.position, flowType)
  }

  // Click "Saltar" en un item → POST /bonds/cashflow/skip + actualiza state.
  async function skipPendingCashflow(item) {
    try {
      await api.post('/bonds/cashflow/skip', {
        broker: item.broker,
        asset: item.asset,
        date: item.date,
        reason: null,  // futuro: prompt al user "¿por qué?" (default, vendido, etc.)
      })
      // Actualizar state local sin re-fetch (más responsive)
      setBondSkips(prev => [...prev, {
        broker: item.broker, asset: item.asset, date: item.date, reason: null,
        created_at: new Date().toISOString(),
      }])
      toast.push(`${item.asset} · pago del ${item.date} saltado`, { type: 'success' })
    } catch (e) {
      toast.push(`No se pudo saltar: ${e.message}`, { type: 'error' })
    }
  }

  // Tras registrar un cupón/amortización: recargar positions (cash actualizado)
  // + refrescar el listado de cobranzas para el bond expandable.
  async function onBondCashflowSuccess() {
    setBondCashflow(null)
    await loadAll()
  }

  function toggleDetail(brokerName) {
    setDetailBrokers(prev => {
      const next = new Set(prev)
      next.has(brokerName) ? next.delete(brokerName) : next.add(brokerName)
      return next
    })
  }

  useEffect(() => {
    loadAll()
    const id = setInterval(() => {
      const { pos, cfg, bkrs } = latestRef.current
      if (pos) fetchPrices(pos, cfg, bkrs)
      api.get('/dolar').then(setDolar).catch(() => {})
    }, REFRESH_MS)
    return () => clearInterval(id)
  }, [])

  async function loadAll() {
    try {
      const [pos, cfg, bkrs, dol, snaps, ops, skips] = await Promise.all([
        api.get('/positions'),
        api.get('/config'),
        api.get('/brokers'),
        api.get('/dolar').catch(() => null),
        api.get('/snapshots?days=30').catch(() => []),
        api.get('/operations').catch(() => []),
        api.get('/bonds/cashflow/skips').catch(() => []),
      ])
      setPositions(pos)
      setConfig(cfg)
      setBrokers(bkrs)
      setDolar(dol)
      setSnapshots(snaps || [])
      setBondOps((ops || []).filter(o => o.op_type === 'Cupón' || o.op_type === 'Amortización'))
      setBondSkips(skips || [])
      latestRef.current = { pos, cfg, bkrs }
      await fetchPrices(pos, cfg, bkrs)
    } catch (e) {
      console.error('Positions loadAll error:', e)
    }
  }

  // Índice por `${broker}:${asset}` con totales y lista cronológica de cobranzas.
  // Phase 3D: distinguimos DOS conceptos críticos por op (especialmente amorts):
  //
  //   • TOTAL (cash recibido): lo que efectivamente entró al broker. Es lo
  //     que el user "cobró". Cupones + amortizaciones se suman acá.
  //
  //   • PNL CONTRIBUTION (aporte al P&L): la ganancia REAL que ese flujo
  //     aporta al P&L del bono. Para cupones = total (100% es ganancia).
  //     Para amorts = total − cost_basis_consumed (sólo la ganancia
  //     realizada, no la devolución de capital).
  //
  //   Ejemplo (AL30 comprado a 70):
  //     Amort de USD 76.92 → cost_basis_consumed=53.84, gain=23.08.
  //     → "Ya cobraste" suma 76.92 (cash). "P&L con cupones" suma 23.08.
  //
  //   También: conversión a USD canónico vía fx_to_usd o fallback al blue.
  const bondCashflowsByKey = useMemo(() => {
    const map = new Map()
    for (const op of bondOps) {
      const key = `${op.broker}:${op.asset}`
      if (!map.has(key)) map.set(key, {
        ops: [],
        coupons: 0, amortizations: 0, total: 0,    // cash neto recibido
        couponsUsd: 0, amortizationsUsd: 0, totalUsd: 0,
        pnlContribution: 0,                         // aporte al P&L
        pnlContributionUsd: 0,
        hasLegacyOps: false,
        currency: op.currency || null,
      })
      const entry = map.get(key)
      entry.ops.push(op)
      const amt = +op.pnl_usd || 0
      entry.total += amt

      // Conversión a USD: fx_to_usd stampado en op (Phase 3D), o fallback.
      let fx = op.fx_to_usd
      if (fx == null || fx <= 0) {
        entry.hasLegacyOps = true
        if (op.currency === 'ARS' || (op.currency == null && amt > 1000)) {
          fx = 1 / (tcBlue || 1)
        } else {
          fx = 1.0
        }
      }
      const amtUsd = amt * fx
      entry.totalUsd += amtUsd

      // Aporte al P&L: cupones = 100%; amorts = sólo la ganancia realizada.
      let pnlContrib = amt
      if (op.op_type === 'Amortización') {
        const cbConsumed = op.cost_basis_consumed
        if (cbConsumed != null && cbConsumed >= 0) {
          pnlContrib = amt - cbConsumed  // puede ser negativo si compró premium
        } else {
          // Op legacy sin cost_basis_consumed stampado. Sin la info, no
          // podemos calcular la ganancia → conservativo: asume 0 (toda la
          // amort es devolución de capital).
          pnlContrib = 0
          entry.hasLegacyOps = true
        }
      }
      entry.pnlContribution += pnlContrib
      entry.pnlContributionUsd += pnlContrib * fx

      if (op.op_type === 'Cupón') {
        entry.coupons += amt
        entry.couponsUsd += amtUsd
      } else {
        entry.amortizations += amt
        entry.amortizationsUsd += amtUsd
      }
    }
    // Ordenar por fecha desc (más reciente primero)
    for (const v of map.values()) {
      v.ops.sort((a, b) => (b.date || '').localeCompare(a.date || ''))
    }
    return map
  }, [bondOps, tcBlue])

  async function fetchPrices(pos, cfg, bkrs) {
    const arsBrokers = new Set(bkrs.filter(b => b.currency === 'ARS').map(b => b.name))
    // Todo lo que no sea ARS (USDT, USD) se valúa directo en USD sin conversión
    const usdtBrokers = new Set(bkrs.filter(b => b.currency !== 'ARS').map(b => b.name))

    const arsSyms = [...new Set(
      pos.filter(p => arsBrokers.has(p.broker) && !p.is_cash).map(p => p.asset + '.BA')
    )]
    const usdtSyms = [...new Set(
      pos.filter(p => usdtBrokers.has(p.broker) && !p.is_cash && p.asset !== 'USDT').map(p => p.asset)
    )]
    const all = [...arsSyms, ...usdtSyms].join(',')
    if (!all) return
    try {
      const data = await api.get(`/prices?symbols=${all}`)
      setPrices(data)
      setLastUpdated(new Date())
    } catch {}
  }

  function openAdd(broker) {
    // El flujo nuevo siempre pasa por el AddPositionFlow (asset type → ticker
    // → form). Si ya viene un broker preseleccionado (desde el menú de cada
    // broker), lo cargamos en el form para que el step 3 lo tenga listo.
    setForm({ ...EMPTY_POS, broker: broker || (brokers[0]?.name ?? ''), entry_date: today() })
    setModal('add-flow')
  }

  // Callback del AddPositionFlow cuando el user selecciona un ticker.
  // Cierra el flow y abre el form (PositionFormModal) con el asset ya cargado.
  function onAssetSelectedFromFlow({ asset }) {
    setForm(f => ({ ...f, asset }))
    setModal('add')
  }
  function openEdit(p) {
    setForm({
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
    setModal('edit')
  }

  async function save() {
    const body = {
      ...form,
      buy_price: form.buy_price !== '' ? +form.buy_price : null,
      quantity: form.quantity !== '' ? +form.quantity : null,
      invested: form.invested !== '' ? +form.invested : null,
      tc_compra: form.tc_compra !== '' ? +form.tc_compra : null,
      commissions: form.commissions !== '' ? +form.commissions : 0,
      entry_date: form.entry_date || null,
    }
    if (modal === 'edit') {
      await api.put(`/positions/${form.id}`, body)
    } else {
      await api.post('/positions', body)
    }
    setModal(null)
    loadAll()
  }

  async function del(id) {
    if (!confirm('¿Eliminar esta posición? La acción no se puede deshacer.')) return
    await api.delete(`/positions/${id}`)
    loadAll()
  }

  function openSell(p) {
    if (p.is_cash) return
    const broker = brokers.find(b => b.name === p.broker)
    const isARS = broker?.currency === 'ARS'
    const c = isARS ? calcARS(p) : calcUSDT(p)
    const suggested = isARS ? c.priceArs : c.price
    setSellForm({
      broker: p.broker,
      asset: p.asset,
      currency: broker?.currency || 'USDT',
      quantity: '',
      exit_price: suggested != null ? +suggested.toFixed(4) : '',
      tc_venta: isARS ? +tcBlue.toFixed(2) : '',
      date: today(),
      commissions: '',
    })
    setModal('sell')
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
    if (!body.quantity || body.quantity <= 0) return toast.push('La cantidad ingresada no es válida.', { type: 'warn' })
    if (body.exit_price == null || body.exit_price < 0) return toast.push('El precio ingresado no es válido.', { type: 'warn' })
    try {
      const res = await api.post('/positions/sell', body)
      setModal(null)
      loadAll()
      // Mensaje breve
      if (res.closed_count > 1) {
        // FIFO cerró múltiples lotes
      }
    } catch (e) {
      toast.push('No se pudo registrar la venta: ' + e.message, { type: 'error' })
    }
  }

  function openCashFlow(p, direction) {
    const broker = brokers.find(b => b.name === p.broker)
    setCashFlowForm({
      broker: p.broker,
      currency: broker?.currency || 'USDT',
      direction,
      amount: '',
      available: p.invested || 0,
    })
    setModal('cashflow')
  }

  function openConvert(p, direction) {
    // p es la posición cash desde la cual se inicia la conversión.
    // Para usd_to_ars guardamos también el `tc_compra` promedio del cash USD
    // para poder previsualizar el P&L cambiario en el modal.
    setConvertForm({
      direction,
      from_broker: p.broker,
      available: p.invested || 0,
      tc_compra_avg: direction === 'usd_to_ars' ? (p.tc_compra || null) : null,
      kind: 'MEP',
      ars_amount: '',
      usd_amount: '',
      tc: tcBlue ? String(tcBlue) : '',
      date: today(),
    })
    setModal('convert')
  }

  async function confirmConvert() {
    const arsAmount = +convertForm.ars_amount
    const usdAmount = +convertForm.usd_amount
    const tc = +convertForm.tc
    if (!arsAmount || arsAmount <= 0) return toast.push('Ingresá un monto ARS válido.', { type: 'warn' })
    if (!usdAmount || usdAmount <= 0) return toast.push('Ingresá un monto USD válido.', { type: 'warn' })
    if (!tc || tc <= 0) return toast.push('Ingresá un tipo de cambio válido.', { type: 'warn' })
    // Validar saldo según dirección
    const debit = convertForm.direction === 'ars_to_usd' ? arsAmount : usdAmount
    if (debit > convertForm.available + 0.001) {
      const curr = convertForm.direction === 'ars_to_usd' ? 'ARS' : 'USD'
      return toast.push(`Saldo insuficiente. Disponible: ${convertForm.available.toFixed(2)} ${curr}.`, { type: 'warn' })
    }
    try {
      await api.post('/conversions', {
        from_broker: convertForm.from_broker,
        direction: convertForm.direction,
        ars_amount: arsAmount,
        usd_amount: usdAmount,
        tc,
        kind: convertForm.kind,
        date: convertForm.date || null,
      })
      setModal(null)
      loadAll()
    } catch (e) {
      toast.push('Ocurrió un error: ' + e.message, { type: 'error' })
    }
  }

  async function createUsdSibling(broker) {
    try {
      await api.post(`/brokers/${broker.id}/usd-sibling`)
      loadAll()
    } catch (e) {
      toast.push('Ocurrió un error: ' + e.message, { type: 'error' })
    }
  }

  async function confirmCashFlow() {
    const amount = +cashFlowForm.amount
    if (!amount || amount <= 0) return toast.push('Ingresá un monto válido.', { type: 'warn' })
    if (cashFlowForm.direction === 'withdraw' && amount > cashFlowForm.available + 0.001) {
      return toast.push(`Saldo insuficiente. Disponible: ${cashFlowForm.available.toFixed(2)} ${cashFlowForm.currency}.`, { type: 'warn' })
    }
    try {
      await api.post('/cash/flow', {
        broker_name: cashFlowForm.broker,
        direction: cashFlowForm.direction,
        amount,
        tc_blue: tcBlue,
      })
      setModal(null)
      loadAll()
    } catch (e) {
      toast.push('Ocurrió un error: ' + e.message, { type: 'error' })
    }
  }

  const sortCash = arr => [...arr.filter(p => !p.is_cash), ...arr.filter(p => p.is_cash)]

  function calcUSDT(p) {
    if (p.is_cash) return { value: p.invested, pnl: 0, pnlPct: 0, price: null }
    const price = p.price_override ?? prices[p.asset]
    if (price == null) return { value: null, pnl: null, pnlPct: null, price: null }
    // Cost basis = invested + commissions (las comisiones de compra son costo real).
    const realCost = (p.invested || 0) + (p.commissions || 0)
    const value = price * p.quantity
    const pnl = value - realCost
    return { value, pnl, pnlPct: realCost > 0 ? pnl / realCost : 0, price }
  }

  function calcARS(p) {
    if (p.is_cash) {
      return { valueArs: p.invested, valueUsd: p.invested / tcBlue, pnlArs: 0, pnlUsd: 0, pnlPct: 0, priceArs: null }
    }
    const priceArs = p.price_override ?? prices[p.asset + '.BA']
    if (priceArs == null) return { valueArs: null, valueUsd: null, pnlArs: null, pnlUsd: null, pnlPct: null, priceArs: null }
    // Cost basis ARS = invested + commissions (ambos en pesos para broker ARS).
    const realCostArs = (p.invested || 0) + (p.commissions || 0)
    const valueArs = priceArs * p.quantity
    const pnlArs = valueArs - realCostArs
    const valueUsd = valueArs / tcBlue
    // FX-phantom fix: cost basis USD usa el blue actual (no tc_compra histórico).
    // Eso elimina el "P&L USD fantasma" generado por el mero movimiento del blue
    // cuando el activo no se mueve. tc_compra queda como dato informativo.
    const invUsd = realCostArs / tcBlue
    const pnlUsd = valueUsd - invUsd
    return { valueArs, valueUsd, pnlArs, pnlUsd, pnlPct: realCostArs > 0 ? pnlArs / realCostArs : 0, priceArs, invUsd }
  }

  // sticky top-0 + bg matched al thead row para que al scrollear la tabla
  // (especialmente en mobile o brokers con muchas posiciones) el header
  // quede pegado arriba — convención fintech standard (Robinhood, Stripe).
  const thClass = 'px-3 py-2.5 text-left label-mono whitespace-nowrap sticky top-0 z-10 bg-slate-50/95 dark:bg-bg-2/95 backdrop-blur-sm'
  const tdClass = 'px-3 py-2.5 text-sm whitespace-nowrap'
  const inputClass = 'w-full bg-slate-50 dark:bg-bg-2 border border-slate-300 dark:border-line rounded-md px-3 py-2 text-sm text-slate-900 dark:text-ink-0'

  const selectedBrokerCurrency = brokers.find(b => b.name === form.broker)?.currency ?? 'USDT'

  // Totales agregados (USD) para el hero "Tu portfolio hoy".
  // IMPORTANTE: useMemo va ANTES del early return — los hooks deben llamarse
  // en el mismo orden en cada render (rules of hooks).
  const totals = useMemo(() => {
    let value = 0, invested = 0
    for (const b of brokers) {
      const r = computeBrokerValue(positions, prices, b, tcBlue)
      value += r.value || 0
      invested += r.invested || 0
    }
    const pnl = value - invested
    const pct = invested > 0 ? pnl / invested : 0
    return { value, invested, pnl, pct }
  }, [brokers, positions, prices, tcBlue])

  // Delta vs último snapshot guardado. Se llama "variación diaria" cuando
  // dayDiff === 1, pero si el usuario no abrió la app durante varios días
  // el snapshot anterior puede ser de hace 5/16/N días — en ese caso el
  // copy refleja la realidad ("últimos N días" o "desde DATE") en lugar
  // de mentir con un "HOY" engañoso.
  // Para variación diaria 100% confiable hace falta un cron server-side
  // que tome snapshot automático cada noche (tarea spawneada aparte).
  const daily = useMemo(() => {
    if (!totals.value || snapshots.length === 0) return null
    const today = new Date().toISOString().slice(0, 10)
    const lastClose = snapshots.find(s => s.date < today)  // snapshots vienen DESC
    if (!lastClose || !lastClose.total_value) return null
    const delta = totals.value - lastClose.total_value
    const pct = delta / lastClose.total_value
    const dayDiff = Math.round((new Date(today) - new Date(lastClose.date)) / 86_400_000)
    // Label corto del badge (lo que va dentro del banner como kicker)
    const badgeLabel = dayDiff === 1
      ? 'Hoy'
      : dayDiff <= 7
      ? `${dayDiff} días`
      : 'Variación'
    // Label largo de referencia (lo que aclara el período exacto)
    const refLabel = dayDiff === 1
      ? 'desde el cierre de ayer'
      : dayDiff <= 7
      ? `últimos ${dayDiff} días`
      : `desde ${lastClose.date}`
    return { delta, pct, badgeLabel, refLabel, lastValue: lastClose.total_value, dayDiff }
  }, [totals.value, snapshots])

  if (brokers.length === 0) {
    return (
      <div className="page-shell-wide">
        <PageHeader title="Posiciones activas" subtitle="Posiciones abiertas en cada broker, con valoración a precios de mercado." />
        <div className="bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded">
          <EmptyState
            title="Sin brokers configurados"
            description="Configurá tu primer broker desde la sección Config para comenzar a registrar posiciones."
          />
        </div>
      </div>
    )
  }

  const meta = lastUpdated ? `Precios · ${lastUpdated.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}` : null

  return (
    <div className="page-shell-wide">
      <PageHeader
        title="Posiciones activas"
        subtitle="Posiciones abiertas en cada broker, con valoración a precios de mercado."
        meta={meta}
      />

      {/* Phase 3E — Inbox de cobranzas pendientes. Sólo se renderea cuando hay
          al menos una pendiente. Va arriba del hero para máxima visibilidad —
          pagos no registrados distorsionan el P&L total. */}
      <PendingCashflowsBanner
        pending={pendingCashflows}
        brokers={brokers}
        onConfirm={confirmPendingCashflow}
        onSkip={skipPendingCashflow}
      />

      {/* ══════════════════════════════════════════════════════════════════════
          HERO — 'Tu portfolio hoy' agregado total. Single hero per page rule.
          ══════════════════════════════════════════════════════════════════════ */}
      <div className="mb-4">
        <StatCard
          tone="hero"
          label="Tu portfolio hoy"
          value={fmtUsd(totals.value)}
          sub={
            <span className="inline-flex items-center gap-3 flex-wrap">
              <span className="text-ink-2">P&L no realizado</span>
              <span className={`inline-flex items-center gap-1 font-semibold ${totals.pnl >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                {totals.pnl >= 0 ? <TrendingUp size={14} strokeWidth={1.5} /> : <TrendingDown size={14} strokeWidth={1.5} />}
                USD {usd(Math.abs(totals.pnl))}
              </span>
              <span className={`tabular ${totals.pnl >= 0 ? 'text-rendi-pos/80' : 'text-rendi-neg/80'}`}>
                ({pctSigned(totals.pct)})
              </span>
            </span>
          }
          hint={`Invertido USD ${usd(totals.invested)} · ${brokers.length} ${brokers.length === 1 ? 'broker' : 'brokers'} activos`}
        />
      </div>

      {/* ══════════════════════════════════════════════════════════════════════
          BANNER 'Hoy' — variación intradía respecto del último cierre
          guardado (snapshots diarios). Solo se muestra si hay historial.
          ══════════════════════════════════════════════════════════════════════ */}
      {daily && (
        <div className={`mb-8 flex items-center gap-3 px-4 py-3 rounded border ${
          daily.delta >= 0
            ? 'bg-rendi-pos/[0.06] border-rendi-pos/25'
            : 'bg-rendi-neg/[0.06] border-rendi-neg/25'
        }`}>
          <div className={`flex items-center justify-center w-8 h-8 rounded-sm flex-shrink-0 ${
            daily.delta >= 0 ? 'bg-rendi-pos/15 text-rendi-pos' : 'bg-rendi-neg/15 text-rendi-neg'
          }`}>
            {daily.delta >= 0 ? <TrendingUp size={16} strokeWidth={1.75} /> : <TrendingDown size={16} strokeWidth={1.75} />}
          </div>
          <div className="flex-1 min-w-0 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="label-mono">{daily.badgeLabel}</span>
            <span className={`text-base font-semibold tabular ${
              daily.delta >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'
            }`}>
              {daily.delta >= 0 ? '+' : '−'}USD {usd(Math.abs(daily.delta))}
            </span>
            <span className={`text-sm tabular ${
              daily.delta >= 0 ? 'text-rendi-pos/80' : 'text-rendi-neg/80'
            }`}>
              ({pctSigned(daily.pct)})
            </span>
            <span className="text-xs text-ink-2 font-mono">
              {daily.refLabel} · cierre USD {usd(daily.lastValue)}
            </span>
          </div>
        </div>
      )}

      {sortBrokersForDisplay(brokers).map(({ broker, indent, parentName }, bi) => {
        const color = BROKER_COLORS[bi % BROKER_COLORS.length]
        const bpos = sortCash(positions.filter(p => p.broker === broker.name))
        const isARS = broker.currency === 'ARS'
        const isSubBroker = broker.parent_broker_id != null
        const showDetail = detailBrokers.has(broker.name)
        const r = computeBrokerValue(positions, prices, broker, tcBlue)

        // ── Header (compartido) ────────────────────────────────────────────
        // Eyebrow 'Broker' + nombre prominente · badges discretos · métricas
        // inline · acciones a la derecha. Patrón specimen sheet del audit.
        const headerPnlUsd = r.pnlUsd
        const headerPnlPct = r.invested > 0 ? r.pnlUsd / r.invested : 0
        const Header = (
          <div className="flex flex-col gap-3 px-4 sm:px-5 py-4 border-b border-slate-200 dark:border-line">
            <div className="flex items-start justify-between flex-wrap gap-3">
              <div className="min-w-0">
                <p className="eyebrow mb-1 flex items-center gap-2">
                  {isSubBroker && (
                    <span className="text-ink-3 select-none" title={`Sub-broker de ${parentName}`}>└─</span>
                  )}
                  Broker · {isARS ? 'ARS' : 'USD'}
                  {isSubBroker && (
                    <span className="text-ink-3 normal-case tracking-normal" title="Creado automáticamente al convertir ARS a USD">
                      sub-broker
                    </span>
                  )}
                  {isARS && <span className="text-ink-3 normal-case tracking-normal">· TC blue {tcBlue}</span>}
                </p>
                <h3 className={`text-lg font-semibold leading-tight ${color.text}`}>{broker.name}</h3>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                {/* Para brokers ARS sin sub-broker USD: ofrecemos crearlo
                    manualmente. Util para el caso de CEDEARs en USD comprados
                    en Cocos sin pasar primero por una conversión ARS→USD. */}
                {isARS && !brokers.some(b => b.parent_broker_id === broker.id) && (
                  <button
                    onClick={() => createUsdSibling(broker)}
                    className="flex items-center gap-1 text-[11px] text-rendi-accent hover:text-rendi-accent/80 px-2 py-1 rounded-sm hover:bg-rendi-accent/10 transition"
                    title="Crea un sub-broker USD asociado para registrar tenencias en dólares (CEDEARs en USD, USDT, etc.)"
                  >
                    <DollarSign size={12} strokeWidth={1.5} /> Crear sub-broker USD
                  </button>
                )}
                <button
                  onClick={() => toggleDetail(broker.name)}
                  className="flex items-center gap-1 text-[11px] text-slate-500 dark:text-ink-2 hover:text-slate-900 dark:hover:text-ink-0 px-2 py-1 rounded-sm hover:bg-slate-100 dark:hover:bg-bg-2 transition"
                  title={showDetail ? 'Ocultar columnas auxiliares' : 'Mostrar tipo de cambio, conversiones y detalles adicionales'}
                >
                  {showDetail ? <ChevronUp size={12} strokeWidth={1.5} /> : <ChevronDown size={12} strokeWidth={1.5} />}
                  {showDetail ? 'Ocultar detalle' : 'Detalle'}
                </button>
                <button onClick={() => openAdd(broker.name)} className="flex items-center gap-1 text-xs bg-bg-2 hover:bg-bg-3 border border-line text-slate-700 dark:text-ink-1 px-2.5 py-1.5 rounded-sm transition">
                  <Plus size={12} strokeWidth={1.5} /> Agregar
                </button>
              </div>
            </div>
            <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 text-xs sm:text-sm tabular">
              <span>
                <span className="label-mono mr-1.5">Valor</span>
                <span className="font-semibold text-slate-900 dark:text-ink-0">
                  {isARS ? fmtArs(r.valueArs) : fmtUsd(r.value)}
                </span>
              </span>
              <span className="text-ink-2">
                <span className="label-mono mr-1.5">Inv</span>
                {isARS ? fmtArs(r.invArs) : fmtUsd(r.invested)}
              </span>
              <span className={`${colorClass(headerPnlUsd)} font-medium`}>
                <span className="label-mono mr-1.5 text-ink-2">P&L</span>
                {headerPnlUsd >= 0 ? '+' : '−'}{isARS ? `ARS ${ars(Math.abs(r.pnlArs))}` : `USD ${usd(Math.abs(headerPnlUsd))}`}
                <span className="ml-1 opacity-80">({pctSigned(headerPnlPct)})</span>
              </span>
            </div>
          </div>
        )

        // ── ARS broker ─────────────────────────────────────────────────────
        if (isARS) {
          return (
            <div key={broker.id} className="bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded overflow-hidden mb-6">
              {Header}
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-slate-100 dark:border-line bg-slate-50/40 dark:bg-bg-2/40">
                      <th className={thClass}>Activo</th>
                      <th className={thClass}>Cantidad</th>
                      <th className={thClass}>Precio prom.</th>
                      <th className={thClass}>Precio actual</th>
                      <th className={thClass}>Invertido</th>
                      {showDetail && <th className={thClass}>TC Compra</th>}
                      {showDetail && <th className={thClass}>Inv. USD</th>}
                      <th className={thClass}>Valor</th>
                      <th className={thClass}>P&L</th>
                      {showDetail && <th className={thClass}>P&L USD</th>}
                      <th className={thClass}>P&L %</th>
                      <th className={thClass}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {bpos.map(p => {
                      const c = calcARS(p)
                      // P&L "con cupones": sumamos cobranzas (en ARS, misma moneda
                      // que el broker) al P&L mark-to-market. Es el "total return"
                      // del bono — captura tanto la variación de precio como los
                      // flujos cobrados durante la tenencia.
                      const isBond = isBondTicker(p.asset) && !p.is_cash
                      const bondKey = `${p.broker}:${p.asset}`
                      const bondSummary = isBond ? bondCashflowsByKey.get(bondKey) : null
                      // Phase 3D sub-fix: P&L augmentado usa pnlContribution
                      // (sólo cupones + ganancia realizada de amorts), NO el
                      // cash total — la devolución de capital de los amorts
                      // no es ganancia.
                      const cobranzasCash = bondSummary?.total || 0
                      const pnlContrib = bondSummary?.pnlContribution || 0
                      const adjPnlArs = (c.pnlArs != null && pnlContrib)
                        ? c.pnlArs + pnlContrib
                        : c.pnlArs
                      const adjPnlPct = (isBond && adjPnlArs != null && p.invested > 0)
                        ? adjPnlArs / p.invested
                        : c.pnlPct
                      const pnlBg = adjPnlArs == null ? '' : adjPnlArs > 0 ? 'bg-rendi-pos/[0.06]' : adjPnlArs < 0 ? 'bg-rendi-neg/[0.06]' : ''
                      const avgPriceArs = (!p.is_cash && p.quantity > 0 && p.invested) ? p.invested / p.quantity : null
                      const expanded = isBond && expandedBonds.has(bondKey)
                      const arsColSpan = showDetail ? 12 : 9
                      const pnlTooltip = (isBond && pnlContrib !== 0)
                        ? `P&L = mark-to-market (${c.pnlArs >= 0 ? '+' : '-'}ARS ${ars(Math.abs(c.pnlArs || 0))}) + ${pnlContrib >= 0 ? '+' : '-'}ARS ${ars(Math.abs(pnlContrib))} de ganancia realizada (cupones + parte de ganancia de amorts). Cash total cobrado: ARS ${ars(cobranzasCash)}.`
                        : undefined
                      return (
                        <Fragment key={p.id}>
                        <tr className={`border-b border-slate-100 dark:border-line/50 hover:bg-slate-50 dark:hover:bg-bg-2/40 ${p.is_cash ? 'bg-slate-50/60 dark:bg-bg-2/30' : ''}`}>
                          <td className={`${tdClass}`}>
                            <div className="flex items-center gap-2.5 min-w-0">
                              <AssetLogo asset={p.asset} isCash={p.is_cash} size={32} />
                              <div className="min-w-0">
                                <div className="font-semibold text-slate-800 dark:text-ink-0 flex items-center gap-1.5 flex-wrap">
                                  {p.asset}
                                  {!!p.is_cash && <span className="text-[9px] font-mono uppercase tracking-[0.12em] px-1 py-0.5 rounded-sm bg-bg-3 border border-line text-ink-2 flex items-center gap-0.5"><Wallet size={9} strokeWidth={1.5} /> CASH</span>}
                                  {isBond && (
                                    <span
                                      className="text-[9px] font-mono uppercase tracking-[0.12em] px-1 py-0.5 rounded-sm bg-rendi-accent/15 text-rendi-accent border border-rendi-accent/30 flex items-center gap-0.5"
                                      title="Bono / Obligación Negociable"
                                    >
                                      <Coins size={9} strokeWidth={1.5} /> BONO
                                    </span>
                                  )}
                                  {!!p.price_override && <span className="text-rendi-warn" title="Precio manual configurado">●</span>}
                                  {!p.is_cash && (!p.tc_compra || p.tc_compra <= 0) && (
                                    <span
                                      className="text-[9px] font-mono uppercase tracking-[0.12em] px-1 py-0.5 rounded-sm bg-rendi-warn/15 text-rendi-warn border border-rendi-warn/30"
                                      title="Falta el tipo de cambio de compra. El P&L en USD se aproxima con el blue actual — editá la posición para mayor precisión."
                                    >
                                      TC?
                                    </span>
                                  )}
                                </div>
                                <div className="text-[10px] text-ink-3 mt-0.5 font-mono flex items-center gap-2">
                                  <span>{p.entry_date || 'sin fecha'}</span>
                                  {isBond && (
                                    <button
                                      onClick={() => toggleBondExpand(p)}
                                      className="inline-flex items-center gap-0.5 text-rendi-accent hover:text-rendi-accent/80 normal-case tracking-normal"
                                      title={expanded ? 'Ocultar cobranzas y meta del bono' : 'Ver meta + historial de cobranzas'}
                                    >
                                      {expanded ? <ChevronUp size={10} strokeWidth={1.75} /> : <ChevronDown size={10} strokeWidth={1.75} />}
                                      {expanded
                                        ? 'Ocultar cobranzas'
                                        : `Ver cobranzas${bondSummary?.ops?.length ? ` (${bondSummary.ops.length})` : ''}`}
                                    </button>
                                  )}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className={`${tdClass} text-slate-600 dark:text-slate-300 tabular`}>{p.quantity ?? '—'}</td>
                          <td className={`${tdClass} text-slate-600 dark:text-slate-300 tabular`}>{avgPriceArs != null ? `ARS ${ars(avgPriceArs)}` : '—'}</td>
                          <td className={`${tdClass} text-slate-700 dark:text-slate-200 tabular`}>{c.priceArs != null ? `ARS ${ars(c.priceArs)}` : <span title="Cargando precio" className="text-slate-400">—</span>}</td>
                          <td className={`${tdClass} text-slate-700 dark:text-slate-200 tabular`}>{fmtArs(p.invested)}</td>
                          {showDetail && <td className={`${tdClass} text-slate-500 dark:text-slate-400 text-xs tabular`}>{p.tc_compra ?? '—'}</td>}
                          {showDetail && <td className={`${tdClass} text-slate-600 dark:text-slate-300 tabular`}>{c.invUsd != null ? fmtUsd(c.invUsd) : '—'}</td>}
                          <td className={`${tdClass} text-slate-900 dark:text-slate-100 font-medium tabular`}>{c.valueArs != null ? fmtArs(c.valueArs) : <span title="Cargando precio" className="text-slate-400">—</span>}</td>
                          <td className={`${tdClass} font-bold tabular ${colorClass(adjPnlArs)} ${pnlBg}`} title={pnlTooltip}>
                            {adjPnlArs != null ? `${adjPnlArs >= 0 ? '+' : '-'}ARS ${ars(Math.abs(adjPnlArs))}` : '—'}
                            {isBond && pnlContrib !== 0 && (
                              <span className="ml-1 text-[10px] font-mono text-rendi-accent normal-case" title={pnlTooltip}>·c</span>
                            )}
                          </td>
                          {showDetail && <td className={`${tdClass} font-medium tabular ${colorClass(c.pnlUsd)}`}>{c.pnlUsd != null ? `${c.pnlUsd >= 0 ? '+' : '-'}USD ${usd(Math.abs(c.pnlUsd))}` : '—'}</td>}
                          <td className={`${tdClass} font-bold tabular ${colorClass(adjPnlPct)} ${pnlBg}`}>{adjPnlPct != null ? pctSigned(adjPnlPct) : '—'}</td>
                          <td className={tdClass}>
                            <ActionMenu items={buildPositionMenu(p, { openEdit, openAdd, openSell, del, openCashFlow, openConvert, openBondCashflow, broker })} />
                          </td>
                        </tr>
                        {expanded && (
                          <BondDetailRow
                            p={p}
                            colSpan={arsColSpan}
                            summary={bondSummary}
                            isARS={true}
                            currentPrice={c.priceArs}
                            tcMep={tcMep}
                            cerSeries={cerSeries}
                            cerStale={cerStale}
                            onAddCoupon={() => openBondCashflow(p, 'coupon')}
                            onAddAmortization={() => openBondCashflow(p, 'amortization')}
                          />
                        )}
                        </Fragment>
                      )
                    })}
                  </tbody>
                  <tfoot>
                    <tr className="border-t-2 border-slate-300 dark:border-line-2 bg-slate-50 dark:bg-bg-2/40">
                      {/* Activo + Cantidad + Precio prom + Precio actual collapsed (colSpan=4) */}
                      <td colSpan={4} className="px-3 py-2.5 text-xs font-bold text-slate-600 dark:text-slate-300 uppercase tracking-wider">TOTAL</td>
                      <td className="px-3 py-2.5 text-xs font-bold text-slate-800 dark:text-slate-200 tabular">{fmtArs(r.invArs)}</td>
                      {showDetail && <td className="px-3 py-2.5 text-xs text-slate-400 dark:text-slate-500">—</td>}
                      {showDetail && <td className="px-3 py-2.5 text-xs font-bold text-slate-800 dark:text-slate-200 tabular">{fmtUsd(r.invested)}</td>}
                      <td className="px-3 py-2.5 text-xs font-bold text-slate-900 dark:text-slate-100 tabular">{fmtArs(r.valueArs)}</td>
                      <td className={`px-3 py-2.5 text-xs font-bold tabular ${colorClass(r.pnlArs)}`}>{r.pnlArs >= 0 ? '+' : '-'}ARS {ars(Math.abs(r.pnlArs))}</td>
                      {showDetail && <td className={`px-3 py-2.5 text-xs font-bold tabular ${colorClass(r.pnlUsd)}`}>{r.pnlUsd >= 0 ? '+' : '-'}USD {usd(Math.abs(r.pnlUsd))}</td>}
                      <td className={`px-3 py-2.5 text-xs font-bold tabular ${colorClass(r.pnlUsd)}`}>
                        {r.invUsd > 0 ? pctSigned(r.pnlUsd / r.invUsd) : '—'}
                      </td>
                      <td />
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          )
        }

        // ── USD broker ─────────────────────────────────────────────────────
        return (
          <div key={broker.id} className="bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded overflow-hidden mb-6">
            {Header}
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-100 dark:border-slate-700/30">
                    <th className={thClass}>Activo</th>
                    <th className={thClass}>Cantidad</th>
                    <th className={thClass}>Precio prom.</th>
                    <th className={thClass}>Precio actual</th>
                    <th className={thClass}>Invertido</th>
                    <th className={thClass}>Valor</th>
                    <th className={thClass}>P&L</th>
                    <th className={thClass}>P&L %</th>
                    <th className={thClass}></th>
                  </tr>
                </thead>
                <tbody>
                  {bpos.map(p => {
                    const c = calcUSDT(p)
                    const isBond = isBondTicker(p.asset) && !p.is_cash
                    const bondKey = `${p.broker}:${p.asset}`
                    const bondSummary = isBond ? bondCashflowsByKey.get(bondKey) : null
                    // Phase 3D sub-fix: ver comentario equivalente en tabla ARS.
                    const cobranzasCash = bondSummary?.total || 0
                    const pnlContrib = bondSummary?.pnlContribution || 0
                    const adjPnl = (c.pnl != null && pnlContrib)
                      ? c.pnl + pnlContrib
                      : c.pnl
                    const adjPnlPct = (isBond && adjPnl != null && p.invested > 0)
                      ? adjPnl / p.invested
                      : c.pnlPct
                    const pnlBg = adjPnl == null ? '' : adjPnl > 0 ? 'bg-rendi-pos/[0.06]' : adjPnl < 0 ? 'bg-rendi-neg/[0.06]' : ''
                    const avgPrice = (!p.is_cash && p.quantity > 0)
                      ? (p.buy_price ?? (p.invested ? p.invested / p.quantity : null))
                      : null
                    const expanded = isBond && expandedBonds.has(bondKey)
                    const pnlTooltip = (isBond && pnlContrib !== 0)
                      ? `P&L = mark-to-market (${c.pnl >= 0 ? '+' : '-'}USD ${usd(Math.abs(c.pnl || 0))}) + ${pnlContrib >= 0 ? '+' : '-'}USD ${usd(Math.abs(pnlContrib))} de ganancia realizada (cupones + ganancia de amorts). Cash total cobrado: USD ${usd(cobranzasCash)}.`
                      : undefined
                    return (
                      <Fragment key={p.id}>
                      <tr className={`border-b border-slate-100 dark:border-line/50 hover:bg-slate-50 dark:hover:bg-bg-2/40 ${p.is_cash ? 'bg-slate-50/60 dark:bg-bg-2/30' : ''}`}>
                        <td className={`${tdClass}`}>
                          <div className="flex items-center gap-2.5 min-w-0">
                            <AssetLogo asset={p.asset} isCash={p.is_cash} size={32} />
                            <div className="min-w-0">
                              <div className="font-semibold text-slate-800 dark:text-ink-0 flex items-center gap-1.5 flex-wrap">
                                {p.asset}
                                {!!p.is_cash && <span className="text-[9px] font-mono uppercase tracking-[0.12em] px-1 py-0.5 rounded-sm bg-bg-3 border border-line text-ink-2 flex items-center gap-0.5"><Wallet size={9} strokeWidth={1.5} /> CASH</span>}
                                {isBond && (
                                  <span
                                    className="text-[9px] font-mono uppercase tracking-[0.12em] px-1 py-0.5 rounded-sm bg-rendi-accent/15 text-rendi-accent border border-rendi-accent/30 flex items-center gap-0.5"
                                    title="Bono / Obligación Negociable"
                                  >
                                    <Coins size={9} strokeWidth={1.5} /> BONO
                                  </span>
                                )}
                                {!!p.price_override && <span className="text-rendi-warn" title="Precio manual configurado">●</span>}
                              </div>
                              <div className="text-[10px] text-ink-3 mt-0.5 font-mono flex items-center gap-2">
                                <span>{p.entry_date || 'sin fecha'}</span>
                                {isBond && (
                                  <button
                                    onClick={() => toggleBondExpand(p)}
                                    className="inline-flex items-center gap-0.5 text-rendi-accent hover:text-rendi-accent/80 normal-case tracking-normal"
                                    title={expanded ? 'Ocultar cobranzas y meta del bono' : 'Ver meta + historial de cobranzas'}
                                  >
                                    {expanded ? <ChevronUp size={10} strokeWidth={1.75} /> : <ChevronDown size={10} strokeWidth={1.75} />}
                                    {expanded
                                      ? 'Ocultar cobranzas'
                                      : `Ver cobranzas${bondSummary?.ops?.length ? ` (${bondSummary.ops.length})` : ''}`}
                                  </button>
                                )}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className={`${tdClass} text-slate-600 dark:text-slate-300 tabular`}>{p.quantity ?? '—'}</td>
                        <td className={`${tdClass} text-slate-600 dark:text-slate-300 tabular`}>{avgPrice != null ? fmtUsd(avgPrice) : '—'}</td>
                        <td className={`${tdClass} text-slate-700 dark:text-slate-200 tabular`}>{c.price != null ? fmtUsd(c.price) : <span title="Cargando precio" className="text-slate-400">—</span>}</td>
                        <td className={`${tdClass} text-slate-700 dark:text-slate-200 tabular`}>{fmtUsd(p.invested)}</td>
                        <td className={`${tdClass} text-slate-900 dark:text-slate-100 font-medium tabular`}>{c.value != null ? fmtUsd(c.value) : <span title="Cargando precio" className="text-slate-400">—</span>}</td>
                        <td className={`${tdClass} font-bold tabular ${colorClass(adjPnl)} ${pnlBg}`} title={pnlTooltip}>
                          {adjPnl != null ? `${adjPnl >= 0 ? '+' : '-'}USD ${usd(Math.abs(adjPnl))}` : '—'}
                          {isBond && pnlContrib !== 0 && (
                            <span className="ml-1 text-[10px] font-mono text-rendi-accent normal-case" title={pnlTooltip}>·c</span>
                          )}
                        </td>
                        <td className={`${tdClass} font-bold tabular ${colorClass(adjPnlPct)} ${pnlBg}`}>{adjPnlPct != null ? pctSigned(adjPnlPct) : '—'}</td>
                        <td className={tdClass}>
                          <ActionMenu items={buildPositionMenu(p, { openEdit, openAdd, openSell, del, openCashFlow, openConvert, openBondCashflow, broker })} />
                        </td>
                      </tr>
                      {expanded && (
                        <BondDetailRow
                          p={p}
                          colSpan={9}
                          summary={bondSummary}
                          isARS={false}
                          currentPrice={c.price}
                          tcMep={tcMep}
                          cerSeries={cerSeries}
                          cerStale={cerStale}
                          onAddCoupon={() => openBondCashflow(p, 'coupon')}
                          onAddAmortization={() => openBondCashflow(p, 'amortization')}
                        />
                      )}
                      </Fragment>
                    )
                  })}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-700/30">
                    {/* Activo + Cantidad + Precio prom + Precio actual collapsed (colSpan=4) */}
                    <td colSpan={4} className="px-3 py-2.5 text-xs font-bold text-slate-600 dark:text-slate-300 uppercase tracking-wider">TOTAL</td>
                    <td className="px-3 py-2.5 text-xs font-bold text-slate-800 dark:text-slate-200 tabular">{fmtUsd(r.invested)}</td>
                    <td className="px-3 py-2.5 text-xs font-bold text-slate-900 dark:text-slate-100 tabular">{fmtUsd(r.value)}</td>
                    <td className={`px-3 py-2.5 text-xs font-bold tabular ${colorClass(r.pnlUsd)}`}>{r.pnlUsd >= 0 ? '+' : '-'}USD {usd(Math.abs(r.pnlUsd))}</td>
                    <td className={`px-3 py-2.5 text-xs font-bold tabular ${colorClass(r.pnlUsd)}`}>
                      {r.invested > 0 ? pctSigned(r.pnlUsd / r.invested) : '—'}
                    </td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        )
      })}

      {modal === 'add-flow' && (
        <AddPositionFlow
          onClose={() => setModal(null)}
          onAssetSelected={onAssetSelectedFromFlow}
        />
      )}

      {(modal === 'add' || modal === 'edit') && (
        <PositionFormModal
          mode={modal}
          form={form}
          setForm={setForm}
          brokers={brokers}
          selectedBrokerCurrency={selectedBrokerCurrency}
          tcBlue={tcBlue}
          onClose={() => setModal(null)}
          onSave={save}
          onChangeAsset={modal === 'add'
            ? () => { setForm(f => ({ ...f, asset: '' })); setModal('add-flow') }
            : undefined}
        />
      )}

      {modal === 'cashflow' && (
        <Modal
          title={`${cashFlowForm.direction === 'deposit' ? 'Depositar en' : 'Retirar de'} ${cashFlowForm.broker}`}
          onClose={() => setModal(null)}
        >
          <div className="space-y-4">
            <p className="text-sm text-slate-600 dark:text-slate-300">
              {cashFlowForm.direction === 'deposit'
                ? `Ingresá el monto a depositar. Se acreditará al cash del broker y se registrará como aporte del mes en curso.`
                : `Ingresá el monto a retirar. Se debitará del cash del broker y se registrará como retiro del mes en curso.`}
            </p>
            {cashFlowForm.direction === 'withdraw' && (
              <p className="text-xs text-slate-400 dark:text-slate-500">
                Disponible: <span className="font-medium text-slate-600 dark:text-slate-300">
                  {cashFlowForm.currency === 'ARS' ? ars(cashFlowForm.available) : `$${usd(cashFlowForm.available)}`} {cashFlowForm.currency}
                </span>
              </p>
            )}
            <div>
              <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">
                Monto ({cashFlowForm.currency})
              </label>
              <input
                type="number"
                step="any"
                autoFocus
                value={cashFlowForm.amount}
                onChange={e => setCashFlowForm(f => ({ ...f, amount: e.target.value }))}
                className={inputClass}
                placeholder="0"
              />
            </div>
            {cashFlowForm.currency === 'ARS' && (
              <p className="text-xs text-slate-400 dark:text-slate-500">
                Equivalente en USD al blue actual ({tcBlue}):
                <span className="font-medium text-slate-600 dark:text-slate-300 ml-1">
                  ${usd((+cashFlowForm.amount || 0) / tcBlue)}
                </span>
                {' '}· valor que se utilizará en el resumen global.
              </p>
            )}
            <div className="flex justify-end gap-2 pt-1">
              <button
                onClick={() => setModal(null)}
                className="px-4 py-2 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
              >
                Cancelar
              </button>
              <button
                onClick={confirmCashFlow}
                disabled={!+cashFlowForm.amount}
                className={`px-4 py-2 text-sm rounded-md font-medium text-white disabled:opacity-40 disabled:cursor-not-allowed transition ${
                  cashFlowForm.direction === 'deposit'
                    ? 'bg-emerald-600 hover:bg-emerald-500'
                    : 'bg-orange-600 hover:bg-orange-500'
                }`}
              >
                Confirmar {cashFlowForm.direction === 'deposit' ? 'depósito' : 'retiro'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {modal === 'sell' && (
        <SellModal
          form={sellForm}
          setForm={setSellForm}
          positions={positions}
          tcBlue={tcBlue}
          onClose={() => setModal(null)}
          onConfirm={confirmSell}
        />
      )}

      {modal === 'convert' && (
        <ConvertModal
          form={convertForm}
          setForm={setConvertForm}
          tcBlue={tcBlue}
          onClose={() => setModal(null)}
          onConfirm={confirmConvert}
        />
      )}

      {bondCashflow && (
        <BondCashflowModal
          flowType={bondCashflow.flowType}
          broker={bondCashflow.broker}
          brokerCurrency={bondCashflow.brokerCurrency}
          asset={bondCashflow.asset}
          position={bondCashflow.position}
          onClose={() => setBondCashflow(null)}
          onSuccess={onBondCashflowSuccess}
        />
      )}

    </div>
  )
}

function ConvertModal({ form, setForm, tcBlue, onClose, onConfirm }) {
  // Conversión interna ARS ↔ USD dentro de un mismo broker. La modal soporta
  // ambas direcciones; los campos cambian de etiqueta según `direction`.
  // Al confirmar, llama a POST /api/conversions que:
  //   1. Debita la moneda de origen
  //   2. Acredita la moneda de destino (auto-creando el sub-broker USD si es la primera conversión)
  //   3. Registra una operación tipo CONVERSION (auditoría)
  const isArsToUsd = form.direction === 'ars_to_usd'
  const arsNum = +form.ars_amount || 0
  const usdNum = +form.usd_amount || 0
  const tcNum = +form.tc || 0

  // Auto-cálculo: si el usuario tipea ARS o TC, recalculamos USD (y viceversa).
  // Mantiene los dos campos editables pero coherentes.
  function setArs(v) {
    const ars = +v
    const next = { ...form, ars_amount: v }
    if (ars > 0 && tcNum > 0) next.usd_amount = (ars / tcNum).toFixed(2)
    setForm(next)
  }
  function setUsd(v) {
    const usd = +v
    const next = { ...form, usd_amount: v }
    if (usd > 0 && tcNum > 0) next.ars_amount = (usd * tcNum).toFixed(2)
    setForm(next)
  }
  function setTc(v) {
    const tc = +v
    const next = { ...form, tc: v }
    // Si hay ARS, recalculamos USD; si solo hay USD, recalculamos ARS.
    if (arsNum > 0 && tc > 0) next.usd_amount = (arsNum / tc).toFixed(2)
    else if (usdNum > 0 && tc > 0) next.ars_amount = (usdNum * tc).toFixed(2)
    setForm(next)
  }

  const inputCls = 'w-full bg-slate-50 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-md px-3 py-2 text-sm text-slate-900 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60'

  const title = isArsToUsd
    ? `Comprar USD desde ${form.from_broker}`
    : `Vender USD a ARS en ${form.from_broker}`

  return (
    <Modal title={title} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
          {isArsToUsd
            ? 'Se debitan los pesos del broker y se acreditan los dólares en un sub-broker USD asociado. Si es la primera vez, el sub-broker se crea automáticamente.'
            : 'Se debitan los dólares del sub-broker USD y se acreditan los pesos en el broker padre.'}
        </p>

        <div className="bg-slate-50 dark:bg-slate-900/40 rounded-lg px-3 py-2 text-xs text-slate-500 dark:text-slate-400">
          Disponible: <span className="font-semibold text-slate-700 dark:text-slate-200 tabular">
            {form.available?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {isArsToUsd ? 'ARS' : 'USD'}
          </span>
        </div>

        {/* Tipo de operación */}
        <div>
          <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1.5">Tipo</label>
          <div className="flex gap-1 bg-slate-100 dark:bg-slate-900/60 rounded-md p-1">
            {['MEP', 'CCL', 'USDT', 'Otro'].map(k => (
              <button
                key={k}
                type="button"
                onClick={() => setForm(f => ({ ...f, kind: k }))}
                className={`flex-1 px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                  form.kind === k
                    ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 shadow-sm'
                    : 'text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                {k}
              </button>
            ))}
          </div>
        </div>

        {/* Montos */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">
              {isArsToUsd ? 'Monto ARS a convertir' : 'ARS a recibir'}
            </label>
            <input
              type="number"
              step="any"
              autoFocus={isArsToUsd}
              value={form.ars_amount}
              onChange={e => setArs(e.target.value)}
              className={inputCls}
              placeholder="0"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">
              {isArsToUsd ? 'USD a recibir' : 'Monto USD a convertir'}
            </label>
            <input
              type="number"
              step="any"
              autoFocus={!isArsToUsd}
              value={form.usd_amount}
              onChange={e => setUsd(e.target.value)}
              className={inputCls}
              placeholder="0"
            />
          </div>
        </div>

        {/* Tipo de cambio */}
        <div>
          <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Tipo de cambio (ARS por USD)</label>
          <input
            type="number"
            step="any"
            value={form.tc}
            onChange={e => setTc(e.target.value)}
            className={inputCls}
            placeholder={String(tcBlue || 1500)}
          />
          {tcNum > 0 && tcBlue > 0 && (
            <p className="text-[10px] text-slate-400 dark:text-slate-500 mt-1">
              Blue actual: {tcBlue} · {Math.abs((tcNum - tcBlue) / tcBlue * 100).toFixed(1)}% {tcNum > tcBlue ? 'por encima' : 'por debajo'}
            </p>
          )}
        </div>

        {/* Fecha */}
        <div>
          <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Fecha</label>
          <DateInput
            value={form.date}
            onChange={v => setForm(f => ({ ...f, date: v }))}
          />
        </div>

        {/* Resumen */}
        {arsNum > 0 && usdNum > 0 && tcNum > 0 && (
          <div className="bg-rendi-accent/[0.06] border border-rendi-accent/25 rounded-md px-3 py-2 text-xs leading-relaxed">
            {isArsToUsd ? (
              <>
                Vas a convertir <span className="font-semibold tabular">ARS {arsNum.toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>{' '}
                en <span className="font-semibold tabular">USD {usdNum.toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>{' '}
                a un TC de <span className="font-semibold tabular">{tcNum}</span>.
              </>
            ) : (
              <>
                Vas a convertir <span className="font-semibold tabular">USD {usdNum.toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>{' '}
                en <span className="font-semibold tabular">ARS {arsNum.toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>{' '}
                a un TC de <span className="font-semibold tabular">{tcNum}</span>.
              </>
            )}
          </div>
        )}

        {/* P&L cambiario — solo en venta de USD, cuando hay tc_compra promedio */}
        {!isArsToUsd && form.tc_compra_avg && form.tc_compra_avg > 0 && usdNum > 0 && tcNum > 0 && (() => {
          const costBasisArs = usdNum * form.tc_compra_avg
          const arsReceived = arsNum > 0 ? arsNum : usdNum * tcNum
          const pnlArs = arsReceived - costBasisArs
          const pnlUsd = pnlArs / tcNum
          const isProfit = pnlArs >= 0
          return (
            <div className={`rounded-md px-3 py-2 text-xs leading-relaxed border ${
              isProfit
                ? 'bg-emerald-500/[0.07] border-emerald-500/30 text-emerald-700 dark:text-emerald-300'
                : 'bg-red-500/[0.07] border-red-500/30 text-red-700 dark:text-red-300'
            }`}>
              <p className="font-semibold mb-1">
                {isProfit ? 'Ganancia cambiaria realizada' : 'Pérdida cambiaria realizada'}
              </p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
                <span>Costo en pesos (TC compra prom.):</span>
                <span className="text-right tabular font-medium">ARS {costBasisArs.toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>
                <span>Pesos a recibir:</span>
                <span className="text-right tabular font-medium">ARS {arsReceived.toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>
                <span className="font-semibold">P&L:</span>
                <span className="text-right tabular font-bold">
                  {isProfit ? '+' : '-'}ARS {Math.abs(pnlArs).toLocaleString('en-US', { maximumFractionDigits: 2 })}
                  {' '}({isProfit ? '+' : '-'}USD {Math.abs(pnlUsd).toLocaleString('en-US', { maximumFractionDigits: 2 })})
                </span>
              </div>
              <p className="text-[10px] mt-1.5 opacity-80">
                TC compra promedio: {form.tc_compra_avg.toFixed(2)} · TC venta: {tcNum.toFixed(2)}
              </p>
            </div>
          )
        })()}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200">
            Cancelar
          </button>
          <button
            onClick={onConfirm}
            disabled={!arsNum || !usdNum || !tcNum}
            className="px-4 py-2 text-sm rounded-md font-semibold text-white bg-rendi-accent hover:bg-rendi-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition"
          >
            Confirmar conversión
          </button>
        </div>
      </div>
    </Modal>
  )
}

// Build the row-action menu items for a position. Centralized so the ARS and
// USD tables stay consistent and we can add/reorder actions in one place.
// Ordena la lista de brokers para que el render visual los muestre agrupados:
// cada padre va seguido inmediatamente por sus hijos. Los brokers sin relación
// padre-hijo se intercalan en el orden en que llegan del backend.
//
// Devuelve: [{ broker, indent, parentName }] donde:
//   - indent: true si es hijo (sub-broker)
//   - parentName: nombre del padre (solo en hijos)
function sortBrokersForDisplay(brokers) {
  const byId = new Map(brokers.map(b => [b.id, b]))
  const childrenByParent = new Map()
  const standalones = []
  for (const b of brokers) {
    if (b.parent_broker_id != null) {
      const arr = childrenByParent.get(b.parent_broker_id) || []
      arr.push(b)
      childrenByParent.set(b.parent_broker_id, arr)
    } else {
      standalones.push(b)
    }
  }
  const out = []
  for (const parent of standalones) {
    out.push({ broker: parent, indent: false, parentName: null })
    const kids = childrenByParent.get(parent.id) || []
    for (const k of kids) {
      out.push({ broker: k, indent: true, parentName: parent.name })
    }
  }
  // Edge case: hijo huérfano (padre eliminado) — lo mostramos al final como standalone
  for (const b of brokers) {
    if (b.parent_broker_id != null && !byId.has(b.parent_broker_id)) {
      out.push({ broker: b, indent: false, parentName: null })
    }
  }
  return out
}

function buildPositionMenu(p, { openEdit, openAdd, openSell, del, openCashFlow, openConvert, openBondCashflow, broker }) {
  if (p.is_cash) {
    const isArsCash = broker?.currency === 'ARS'
    const isUsdCashSubBroker = broker?.currency === 'USDT' && broker?.parent_broker_id != null
    const items = [
      { label: 'Depositar',       icon: <ArrowDownCircle size={13} className="text-emerald-500" />, onClick: () => openCashFlow(p, 'deposit') },
      { label: 'Retirar',         icon: <ArrowUpCircle size={13} className="text-orange-500" />,    onClick: () => openCashFlow(p, 'withdraw') },
    ]
    if (isArsCash) {
      items.push({ label: 'Comprar USD', icon: <DollarSign size={13} className="text-blue-500" />, onClick: () => openConvert(p, 'ars_to_usd') })
    }
    if (isUsdCashSubBroker) {
      items.push({ label: 'Vender USD a ARS', icon: <DollarSign size={13} className="text-violet-500" />, onClick: () => openConvert(p, 'usd_to_ars') })
    }
    items.push(
      { divider: true },
      { label: 'Editar posición', icon: <Pencil size={13} />, onClick: () => openEdit(p) },
      { label: 'Eliminar',        icon: <Trash2 size={13} />, onClick: () => del(p.id), danger: true },
    )
    return items
  }
  // Para bonos agregamos entries específicas — cupón y amortización son
  // los eventos que generan cash recibido del bono. Van arriba porque son
  // las acciones más frecuentes en una posición de renta fija.
  const isBond = isBondTicker(p.asset)
  if (isBond) {
    return [
      { label: 'Registrar cupón',         icon: <Coins size={13} className="text-rendi-pos" />,       onClick: () => openBondCashflow(p, 'coupon') },
      { label: 'Registrar amortización',  icon: <LayersIcon size={13} className="text-rendi-accent" />, onClick: () => openBondCashflow(p, 'amortization') },
      { divider: true },
      { label: 'Agregar compra',  icon: <ShoppingCart size={13} />, onClick: () => openAdd(p.broker) },
      { label: 'Registrar venta', icon: <DollarSign size={13} />,   onClick: () => openSell(p) },
      { divider: true },
      { label: 'Editar posición', icon: <Pencil size={13} />,       onClick: () => openEdit(p) },
      { label: 'Eliminar',        icon: <Trash2 size={13} />,       onClick: () => del(p.id), danger: true },
    ]
  }
  return [
    { label: 'Agregar compra',  icon: <ShoppingCart size={13} />, onClick: () => openAdd(p.broker) },
    { label: 'Registrar venta', icon: <DollarSign size={13} />,   onClick: () => openSell(p) },
    { divider: true },
    { label: 'Editar posición', icon: <Pencil size={13} />,       onClick: () => openEdit(p) },
    { label: 'Eliminar',        icon: <Trash2 size={13} />,       onClick: () => del(p.id), danger: true },
  ]
}

// ─── BondDetailRow ────────────────────────────────────────────────────────────
// Fila expandible que aparece debajo de una posición de bono cuando el user
// hace click en el chevron "Ver cobranzas". Muestra (Fase 1 + Fase 2):
//   • Meta del bono (issuer, vencimiento, cupón, frecuencia)
//   • Totales de lo cobrado (cupones + amortizaciones) y % del capital recuperado
//   • Calendario futuro generado del bondSchedule + TIR estimada al precio actual
//   • Lista cronológica de cobranzas registradas
// El "% recuperado" es el diferencial Rendi: contexto narrativo "ya recuperaste
// X% del capital vía cupones", no se ve en otras apps de tracking.
//
// Convención para TIR: usamos `currentPrice × 100` como precio por 100 nominal,
// asumiendo qty=nominales-individuales (1 nominal = 1 USD/ARS de face value).
// Para ETFs y bonos sin maturity, omitimos TIR.
function BondDetailRow({ p, colSpan, summary, isARS, currentPrice, tcMep, cerSeries, cerStale, onAddCoupon, onAddAmortization }) {
  const meta = getBondMeta(p.asset)
  const moneyLabel = isARS ? 'ARS' : 'USD'
  const fmt = isARS ? ars : usd
  const invested = p.invested || 0
  const coupons = summary?.coupons || 0
  const amortizations = summary?.amortizations || 0
  const total = summary?.total || 0
  // Phase 3D: distinción crítica entre CASH (lo que entró al broker) y
  // P&L CONTRIBUTION (la ganancia real). Para cupones son iguales; para amorts
  // el cash incluye devolución de capital, el pnlContribution no.
  const totalUsd = summary?.totalUsd || 0
  const pnlContribution = summary?.pnlContribution || 0
  const pnlContributionUsd = summary?.pnlContributionUsd || 0
  const hasLegacyOps = summary?.hasLegacyOps || false
  const ops = summary?.ops || []
  const recoveryPct = invested > 0 ? (total / invested) : 0
  // Ganancia realizada del amort = amorts cash − parte que es devolución de capital
  const amortRealizedGain = pnlContribution - coupons

  // ── Fase 2+3A+3C+3D: schedule + TIR + próximo pago ───────────────────────
  // Esto SOLO aplica a bonos con maturity definida en bondMeta. ETFs y
  // tickers sin metadata caen en el fallback de Fase 1.
  //
  // Phase 3C: ajuste CER (capital indexado por inflación) para bonos
  // type='cer' cuando la serie está disponible.
  //
  // Phase 3D — Cross-currency (fix C5 del audit):
  // Para un bono USD comprado en broker ARS, currentPrice viene en pesos
  // (lo que cotiza AL30 en BYMA). El schedule está en USD. Para que la
  // TIR sea coherente, convertimos el precio ARS → USD vía MEP (el dolar
  // financiero implícito en bonos hard-dollar). Sin MEP cargado, fallback
  // al blue con warning.
  const today = new Date().toISOString().slice(0, 10)
  const cerOpts = (meta?.type === 'cer' && cerSeries && Object.keys(cerSeries).length > 0)
    ? { cerSeries }
    : {}
  const fullSchedule = generateSchedule(p.asset, cerOpts)
  const remaining = fullSchedule ? getRemainingPayments(p.asset, today, cerOpts) : null

  const bondCurrency = meta?.currency || 'USD'
  const brokerCurrency = isARS ? 'ARS' : 'USD'
  const isCrossCurrency = bondCurrency !== brokerCurrency
  // Si hay cross-currency, normalizar precio a moneda del bono.
  let priceInBondCurrency = currentPrice
  let priceConversion = null
  if (isCrossCurrency && currentPrice != null && currentPrice > 0) {
    if (bondCurrency === 'USD' && brokerCurrency === 'ARS' && tcMep) {
      priceInBondCurrency = currentPrice / tcMep
      priceConversion = { from: 'ARS', to: 'USD', rate: tcMep, type: 'MEP' }
    } else if (bondCurrency === 'ARS' && brokerCurrency === 'USD' && tcMep) {
      priceInBondCurrency = currentPrice * tcMep
      priceConversion = { from: 'USD', to: 'ARS', rate: tcMep, type: 'MEP' }
    }
  }
  const pricePer100Clean = priceInBondCurrency != null && priceInBondCurrency > 0
    ? priceInBondCurrency * 100
    : null
  const yieldDetail = pricePer100Clean != null
    ? estimateYieldDetailed(p.asset, pricePer100Clean, today, cerOpts)
    : null
  const yieldEstimate = yieldDetail?.ytm ?? null
  const nextPay = p.quantity ? nextPaymentForPosition(p.asset, p.quantity, today) : null
  // Para bonos CER: el coeficiente actual (factor al día de hoy) ayuda a
  // mostrar contexto: "CER hoy ≈ 2.4× emisión" → el user ve el ajuste
  // implícito en sus flujos futuros.
  function cerLocfLookup(date) {
    if (!cerSeries || !date) return null
    if (cerSeries[date] != null) return cerSeries[date]
    const dates = Object.keys(cerSeries).sort()
    let best = null
    for (const d of dates) {
      if (d <= date) best = d
      else break
    }
    return best ? cerSeries[best] : null
  }
  const cerToday = meta?.type === 'cer' ? cerLocfLookup(today) : null
  const cerBase = meta?.type === 'cer' && meta.cerEmissionDate ? cerLocfLookup(meta.cerEmissionDate) : null
  const cerFactorToday = (cerToday != null && cerBase != null && cerBase > 0)
    ? cerToday / cerBase
    : null

  return (
    <tr className="bg-rendi-accent/[0.04] dark:bg-rendi-accent/[0.05] border-b border-line">
      <td colSpan={colSpan} className="px-5 py-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Meta */}
          <div className="space-y-1">
            <p className="eyebrow text-rendi-accent">Bono</p>
            {meta ? (
              <>
                <p className="text-sm font-semibold text-ink-0">
                  {formatBondType(meta.type)} · {meta.issuer}
                  {meta.governingLaw && (
                    <span className="ml-1.5 text-[9px] font-mono uppercase tracking-[0.12em] px-1 py-0.5 rounded-sm bg-bg-3 border border-line text-ink-2">
                      Ley {meta.governingLaw === 'Argentina' ? 'AR' : 'NY'}
                    </span>
                  )}
                </p>
                <p className="text-xs text-ink-2 font-mono">
                  {meta.maturity ? `Vence ${meta.maturity}` : 'ETF · sin vencimiento'}
                  {meta.couponFreq && (
                    <>
                      {' · '}
                      <span
                        className="border-b border-dotted border-ink-3/40 cursor-help"
                        title={formatCouponTooltip(meta)}
                      >
                        {formatCouponLabel(meta)}
                      </span>
                    </>
                  )}
                </p>
                <p className="text-[10px] text-ink-3 font-mono">
                  Moneda original: {meta.currency}
                  {meta.dayCount && ` · day-count ${meta.dayCount}`}
                </p>
                {meta._verificationLevel === 'approx' && (
                  <p className="text-[10px] text-rendi-warn font-mono">
                    ⚠ Cronograma aproximado — verificar contra prospecto para fineza
                  </p>
                )}
                {/* Phase 3C: status del ajuste CER. Sólo aplica a bonos type='cer'. */}
                {meta.type === 'cer' && (
                  <div className="mt-1">
                    {cerFactorToday != null ? (
                      <p className="text-[10px] text-rendi-accent font-mono">
                        ✓ Capital ajustado por CER · factor hoy ≈ {cerFactorToday.toFixed(3)}×
                        {cerStale && <span className="text-rendi-warn"> (serie posiblemente desactualizada)</span>}
                      </p>
                    ) : cerSeries === null ? (
                      <p className="text-[10px] text-ink-3 font-mono">
                        Cargando coeficiente CER…
                      </p>
                    ) : (
                      <p className="text-[10px] text-rendi-warn font-mono">
                        ⚠ Serie CER no disponible — flujos mostrados en nominal sin ajuste de inflación
                      </p>
                    )}
                  </div>
                )}
              </>
            ) : (
              <p className="text-xs text-ink-2">Sin metadata configurada para este ticker.</p>
            )}
          </div>

          {/* Totales cobrados */}
          <div className="space-y-1">
            <p className="eyebrow text-rendi-accent">Ya cobraste</p>
            {total > 0 ? (
              <>
                <p className="text-lg font-bold text-rendi-pos tabular">
                  +{moneyLabel} {fmt(total)}
                </p>
                <p className="text-[11px] text-ink-2 font-mono">
                  {coupons > 0 && <>Cupones: {moneyLabel} {fmt(coupons)}</>}
                  {coupons > 0 && amortizations > 0 && ' · '}
                  {amortizations > 0 && <>Amortizaciones: {moneyLabel} {fmt(amortizations)}</>}
                </p>
                {/* Phase 3D sub-fix: distinguir cash recibido vs aporte al P&L.
                    Los amorts incluyen DEVOLUCIÓN DE CAPITAL (no es ganancia)
                    + GANANCIA REALIZADA. Mostramos la separación para que el
                    user entienda dónde "está" su rentabilidad. */}
                {amortizations > 0 && (
                  <p className="text-[10px] text-ink-3 font-mono leading-snug">
                    De los amorts, sólo{' '}
                    <span className={amortRealizedGain >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}>
                      {moneyLabel} {fmt(amortRealizedGain)}
                    </span>{' '}
                    {amortRealizedGain >= 0 ? 'es ganancia' : 'es pérdida'}; el resto es devolución de capital.
                  </p>
                )}
                <p className="text-[11px] text-rendi-pos font-semibold">
                  Aporte al P&L: {pnlContribution >= 0 ? '+' : '-'}{moneyLabel} {fmt(Math.abs(pnlContribution))}
                </p>
                {isARS && totalUsd > 0 && (
                  <p className="text-[10px] text-ink-3 font-mono">
                    ≈ USD {usd(totalUsd)} en cash {hasLegacyOps && <span className="text-rendi-warn">(aprox)</span>}
                  </p>
                )}
                {invested > 0 && (
                  <p className="text-xs text-rendi-accent font-semibold">
                    {pctSigned(recoveryPct)} del capital recuperado
                  </p>
                )}
              </>
            ) : (
              <p className="text-xs text-ink-2">
                Aún no registraste cobranzas. Cuando recibas un cupón o amortización,
                cargalo desde el menú de acciones para que se acredite al cash del broker
                y aparezca acá.
              </p>
            )}
          </div>

          {/* Acciones rápidas */}
          <div className="space-y-1">
            <p className="eyebrow text-rendi-accent">Registrar pago</p>
            <div className="flex flex-col gap-1.5">
              <button
                onClick={onAddCoupon}
                className="inline-flex items-center justify-center gap-1.5 text-xs bg-rendi-pos/15 hover:bg-rendi-pos/25 text-rendi-pos border border-rendi-pos/30 rounded-sm px-2.5 py-1.5 transition"
              >
                <Coins size={12} strokeWidth={1.5} /> Cupón cobrado
              </button>
              <button
                onClick={onAddAmortization}
                className="inline-flex items-center justify-center gap-1.5 text-xs bg-rendi-accent/15 hover:bg-rendi-accent/25 text-rendi-accent border border-rendi-accent/30 rounded-sm px-2.5 py-1.5 transition"
              >
                <LayersIcon size={12} strokeWidth={1.5} /> Amortización
              </button>
            </div>
          </div>
        </div>

        {/* ── Fase 2: cronograma + TIR + próximo pago ────────────────────── */}
        {fullSchedule && remaining && remaining.length > 0 && (
          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4 pt-3 border-t border-line/60">
            {/* TIR + próximo pago */}
            <div className="space-y-2 md:col-span-1">
              <p className="eyebrow text-rendi-accent">Rendimiento estimado</p>
              {yieldEstimate != null ? (
                <>
                  <p className="text-lg font-bold tabular text-ink-0">
                    {pctSigned(yieldEstimate)} <span className="text-xs font-normal text-ink-2">TIR ef. anual</span>
                  </p>
                  {/* Phase 3A: metadata transparente. Phase 3D: si hay conversión
                      cross-currency, mostrarla también para que el user entienda
                      por qué la TIR no coincide con un cálculo "ARS vs USD" naïve. */}
                  <p className="text-[10px] text-ink-3 font-mono leading-snug">
                    Convención: {yieldDetail.dayCount}
                    {yieldDetail.accrued > 0.01 && (
                      <>
                        {' · '}
                        dirty {yieldDetail.dirty.toFixed(2)} (clean {yieldDetail.clean.toFixed(2)} + accrued {yieldDetail.accrued.toFixed(2)})
                      </>
                    )}
                    {!yieldDetail.converged && (
                      <span className="text-rendi-warn"> · ⚠ aproximada</span>
                    )}
                  </p>
                  {priceConversion && (
                    <p className="text-[10px] text-rendi-accent font-mono leading-snug">
                      ✓ Precio convertido {priceConversion.from} → {priceConversion.to} al {priceConversion.type} {priceConversion.rate.toFixed(2)}
                    </p>
                  )}
                  <p className="text-[10px] text-ink-3 font-mono leading-snug">
                    Asume qty = nominales VN, precio entrado por nominal en moneda del broker.
                    {isCrossCurrency && !priceConversion && (
                      <span className="text-rendi-warn"> ⚠ Bono {bondCurrency} en broker {brokerCurrency} sin MEP disponible — TIR puede estar distorsionada.</span>
                    )}
                  </p>
                </>
              ) : (
                <p className="text-xs text-ink-2 leading-snug">
                  {currentPrice == null
                    ? 'Cargá un precio override en la posición para estimar la TIR a precios de mercado.'
                    : yieldDetail?.method === 'bracket_failed'
                      ? 'No se pudo estimar la TIR — precio fuera del rango razonable. Verificá la moneda y la unidad del precio entrado.'
                      : 'No se pudo estimar la TIR — verificá que el precio esté en la misma moneda que el bono.'}
                </p>
              )}
              {nextPay && (
                <div className="pt-2 mt-1 border-t border-line/40">
                  <p className="eyebrow text-rendi-accent">Próximo pago</p>
                  <p className="text-sm font-semibold text-ink-0 tabular">{nextPay.date}</p>
                  <p className="text-xs text-rendi-pos font-mono">
                    ≈ +{moneyLabel} {fmt(nextPay.total)}
                  </p>
                  <p className="text-[10px] text-ink-3 font-mono">
                    {nextPay.isPureAmort ? 'Amortización' : nextPay.isPureCoupon ? 'Cupón' : 'Cupón + amort.'}
                  </p>
                </div>
              )}
            </div>

            {/* Mini-cronograma de los próximos pagos */}
            <div className="md:col-span-2">
              <p className="eyebrow text-rendi-accent mb-1.5">
                Calendario futuro · {remaining.length} {remaining.length === 1 ? 'pago' : 'pagos'} hasta {meta?.maturity}
              </p>
              <div className="border border-line/60 rounded-sm overflow-hidden">
                <div className="bg-bg-2/40 px-3 py-1 grid grid-cols-12 gap-2 text-[10px] uppercase tracking-wider text-ink-3 font-mono">
                  <div className="col-span-3">Fecha</div>
                  <div className="col-span-3 text-right">Cupón</div>
                  <div className="col-span-3 text-right">Amort.</div>
                  <div className="col-span-3 text-right">Tu monto</div>
                </div>
                <div className="max-h-44 overflow-y-auto divide-y divide-line/30">
                  {remaining.slice(0, 8).map(pay => {
                    const qty = p.quantity || 0
                    const tuMonto = qty > 0 ? (pay.total * qty / 100) : null
                    return (
                      <div key={pay.date} className="px-3 py-1.5 grid grid-cols-12 gap-2 text-xs">
                        <div className="col-span-3 text-ink-1 font-mono">{pay.date}</div>
                        <div className="col-span-3 text-right tabular text-ink-2">
                          {pay.coupon > 0 ? pay.coupon.toFixed(3) : '—'}
                        </div>
                        <div className="col-span-3 text-right tabular text-ink-2">
                          {pay.amort > 0 ? pay.amort.toFixed(3) : '—'}
                        </div>
                        <div className="col-span-3 text-right tabular font-semibold text-rendi-pos">
                          {tuMonto != null ? `${moneyLabel} ${fmt(tuMonto)}` : '—'}
                        </div>
                      </div>
                    )
                  })}
                </div>
                {remaining.length > 8 && (
                  <div className="bg-bg-2/30 px-3 py-1 text-[10px] text-ink-3 font-mono text-center border-t border-line/30">
                    + {remaining.length - 8} pago{remaining.length - 8 === 1 ? '' : 's'} más hasta vencimiento
                  </div>
                )}
              </div>
              <p className="text-[10px] text-ink-3 font-mono mt-1 leading-snug">
                Aproximación basada en cupón promedio del prospecto. Step-up exacto y CER ajustado vienen en Fase 3.
                Cupón/Amort. expresados por 100 nominal.
              </p>
            </div>
          </div>
        )}

        {/* Historial */}
        {ops.length > 0 && (
          <div className="mt-4 border border-line rounded-sm overflow-hidden">
            <div className="bg-bg-2/60 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-ink-2">
              Historial de cobranzas · {ops.length} {ops.length === 1 ? 'pago' : 'pagos'}
            </div>
            <div className="max-h-48 overflow-y-auto divide-y divide-line/50">
              {ops.map(o => (
                <div key={o.id} className="px-3 py-2 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-ink-3 font-mono shrink-0">{o.date}</span>
                    <span className={`text-[9px] font-mono uppercase tracking-[0.12em] px-1 py-0.5 rounded-sm border shrink-0 ${
                      o.op_type === 'Cupón'
                        ? 'bg-rendi-pos/15 text-rendi-pos border-rendi-pos/30'
                        : 'bg-rendi-accent/15 text-rendi-accent border-rendi-accent/30'
                    }`}>
                      {o.op_type}
                    </span>
                    {o.notes && <span className="text-ink-3 truncate">{o.notes}</span>}
                  </div>
                  <span className="font-mono font-semibold text-rendi-pos tabular shrink-0">
                    +{moneyLabel} {fmt(+o.pnl_usd || 0)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </td>
    </tr>
  )
}

function SellModal({ form, setForm, positions, tcBlue, onClose, onConfirm }) {
  // Posiciones FIFO del par (broker, asset)
  const lots = positions
    .filter(p => p.broker === form.broker && p.asset === form.asset && !p.is_cash && (p.quantity || 0) > 0)
    .sort((a, b) => (a.entry_date || '9999').localeCompare(b.entry_date || '9999') || a.id - b.id)

  const totalQty = lots.reduce((s, p) => s + (p.quantity || 0), 0)
  const totalInvested = lots.reduce((s, p) => s + (p.invested || 0), 0)
  const avgBuy = totalInvested && totalQty ? totalInvested / totalQty : null
  const isARS = form.currency === 'ARS'

  const qtyNum = +form.quantity || 0
  const priceNum = +form.exit_price || 0
  const tcVenta = +form.tc_venta || tcBlue || 1

  // Preview FIFO — cost basis incluye buy commissions prorrateadas (mismo
  // criterio que el backend en /positions/sell).
  let remaining = qtyNum
  const fifoPreview = []
  for (const p of lots) {
    if (remaining <= 1e-9) break
    const take = Math.min(remaining, p.quantity || 0)
    const ratio = (p.quantity || 0) > 0 ? take / p.quantity : 0
    const baseInvested = (p.invested || 0) + (p.commissions || 0)
    const investedPart = baseInvested * ratio
    let pnlUsd = 0
    if (isARS) {
      // FX-phantom fix: P&L USD = P&L ARS / TC venta (cost basis alineado al
      // mismo TC que la venta, así no aparece "FX gain" fantasma).
      const pnlArs = (priceNum * take) - investedPart
      pnlUsd = pnlArs / tcVenta
    } else {
      pnlUsd = (priceNum * take) - investedPart
    }
    fifoPreview.push({
      lot_id: p.id,
      entry_date: p.entry_date,
      take,
      pos_qty: p.quantity,
      buy_price: p.buy_price,
      pnl_usd: pnlUsd,
      partial: take < p.quantity,
    })
    remaining -= take
  }
  const totalPnl = fifoPreview.reduce((s, x) => s + x.pnl_usd, 0)
  const exceeds = qtyNum > totalQty + 1e-9

  const inputCls = 'w-full bg-slate-50 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-md px-3 py-2 text-sm text-slate-900 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60'

  return (
    <Modal title={`Vender ${form.asset} en ${form.broker}`} onClose={onClose}>
      <div className="space-y-3">
        {/* Resumen del activo */}
        <div className="bg-slate-50 dark:bg-slate-900/50 rounded-lg p-3 grid grid-cols-3 gap-3 text-xs">
          <div>
            <div className="text-slate-400 dark:text-slate-500">Total disponible</div>
            <div className="font-mono font-semibold text-slate-900 dark:text-white">{totalQty.toLocaleString('en-US', { maximumFractionDigits: 8 })}</div>
          </div>
          <div>
            <div className="text-slate-400 dark:text-slate-500">Lotes ({lots.length})</div>
            <div className="font-mono font-semibold text-slate-900 dark:text-white">FIFO</div>
          </div>
          <div>
            <div className="text-slate-400 dark:text-slate-500">Precio compra prom.</div>
            <div className="font-mono font-semibold text-slate-900 dark:text-white">
              {avgBuy != null ? (isARS ? `$${ars(avgBuy)}` : `$${usd(avgBuy)}`) : '—'}
            </div>
          </div>
        </div>

        {/* Lotes FIFO */}
        <div className="border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
          <div className="bg-slate-100 dark:bg-slate-800 px-3 py-1.5 text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">
            Lotes · orden de cierre FIFO
          </div>
          <div className="max-h-32 overflow-y-auto divide-y divide-slate-200 dark:divide-slate-700">
            {lots.map((p, i) => {
              const preview = fifoPreview.find(f => f.lot_id === p.id)
              return (
                <div key={p.id} className="px-3 py-1.5 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className="text-slate-400 dark:text-slate-500 font-mono">#{i + 1}</span>
                    <span className="text-slate-700 dark:text-slate-300">{p.entry_date || 'sin fecha'}</span>
                    <span className="text-slate-400 dark:text-slate-500">·</span>
                    <span className="font-mono text-slate-900 dark:text-white">{p.quantity}</span>
                  </div>
                  {preview && (
                    <div className="flex items-center gap-2">
                      <span className="text-rendi-accent font-mono text-[11px]">
                        −{preview.take}{preview.partial ? ' (parcial)' : ''}
                      </span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* Slider de cantidad */}
        <QtySlider
          totalQty={totalQty}
          quantity={form.quantity}
          onChange={q => setForm(f => ({ ...f, quantity: q }))}
          asset={form.asset}
          priceUsd={isARS ? (priceNum && tcVenta ? priceNum / tcVenta : 0) : priceNum}
          pnlUsd={qtyNum > 0 && priceNum > 0 ? totalPnl : null}
        />

        {/* Precio de venta */}
        <div>
          <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">
            Precio de venta {isARS ? '(ARS)' : '(USD)'}
          </label>
          <input
            type="number"
            step="any"
            value={form.exit_price}
            onChange={e => setForm(f => ({ ...f, exit_price: e.target.value }))}
            className={inputCls}
          />
          <p className="text-[10px] text-slate-400 dark:text-slate-500 mt-1">
            Se autocompleta con el precio actual de mercado. Ajustá si la venta se realizó a otro precio.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Fecha de venta</label>
            <DateInput value={form.date} onChange={v => setForm(f => ({ ...f, date: v }))} />
          </div>
          <div>
            <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">
              Comisiones {isARS ? '(ARS)' : '(USD)'}
            </label>
            <input
              type="number"
              step="any"
              value={form.commissions}
              onChange={e => setForm(f => ({ ...f, commissions: e.target.value }))}
              className={inputCls}
              placeholder="0"
            />
          </div>
        </div>

        {isARS && (
          <div>
            <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">TC Venta</label>
            <input
              type="number"
              step="any"
              value={form.tc_venta}
              onChange={e => setForm(f => ({ ...f, tc_venta: e.target.value }))}
              className={inputCls}
            />
          </div>
        )}

        {/* Net cash recibido = (qty × precio) − comisiones */}
        {qtyNum > 0 && priceNum > 0 && (
          <div className="bg-slate-50 dark:bg-slate-900/50 rounded-md px-3 py-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-slate-500 dark:text-slate-400">Bruto</span>
              <span className="font-mono text-slate-700 dark:text-slate-200">
                {(qtyNum * priceNum).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {isARS ? 'ARS' : 'USD'}
              </span>
            </div>
            {(+form.commissions || 0) > 0 && (
              <div className="flex items-center justify-between mt-1">
                <span className="text-slate-500 dark:text-slate-400">Comisiones</span>
                <span className="font-mono text-red-500 dark:text-red-400">
                  −{(+form.commissions).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {isARS ? 'ARS' : 'USD'}
                </span>
              </div>
            )}
            <div className="flex items-center justify-between border-t border-slate-200 dark:border-slate-700/50 mt-1.5 pt-1.5">
              <span className="text-slate-600 dark:text-slate-300 font-medium">Neto recibido</span>
              <span className="font-mono font-semibold text-emerald-600 dark:text-emerald-400">
                {(qtyNum * priceNum - (+form.commissions || 0)).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {isARS ? 'ARS' : 'USD'}
              </span>
            </div>
          </div>
        )}

        {exceeds && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-600 dark:text-red-400 rounded-lg p-2 text-xs">
            La cantidad ingresada supera el total disponible ({totalQty}).
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200">
            Cancelar
          </button>
          <button
            onClick={onConfirm}
            disabled={exceeds || !qtyNum || !priceNum}
            className="px-4 py-2 text-sm bg-rendi-accent text-white rounded-md font-semibold hover:bg-rendi-accent/90 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Confirmar venta
          </button>
        </div>
      </div>
    </Modal>
  )
}

function Field({ label, value, onChange, hint, type = 'text', autoFocus = false, inputRef, placeholder = '0', step }) {
  return (
    <div>
      <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">{label}</label>
      <input
        ref={inputRef}
        type={type}
        step={step}
        autoFocus={autoFocus}
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full bg-slate-50 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-md px-3 py-2 text-sm text-slate-900 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60 transition"
        placeholder={placeholder}
      />
      {hint && <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">{hint}</p>}
    </div>
  )
}

// ─── PositionFormModal ───────────────────────────────────────────────────────
// UX simplificada para agregar/editar posiciones.
// Features:
//  • Auto-fill precio actual al elegir ticker (editable).
//  • Lógica bidireccional: cantidad × precio = invertido (y vice versa).
//    `lastEdited` = source of truth: si tocaste invested, recalculo qty;
//    si tocaste qty, recalculo invested. Cambios en precio recalculan según
//    el último editado, sin loops.
//  • Sin "Precio override" — quien quiera editar el precio actual lo hace
//    directo en el campo principal.
//  • Comisiones: campo opcional. Real cost = invertido + comisiones.
function PositionFormModal({ mode, form, setForm, brokers, selectedBrokerCurrency, tcBlue, onClose, onSave, onChangeAsset }) {
  const isARS = selectedBrokerCurrency === 'ARS'
  const [lastEdited, setLastEdited] = useState('invested') // 'invested' | 'quantity'
  const [pricesFetched, setPricesFetched] = useState(false)
  const inputClass = 'w-full bg-slate-50 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-md px-3 py-2 text-sm text-slate-900 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60 transition'

  // Si el asset viene preseteado desde el AddPositionFlow (no por TickerSearch
  // interno), hacemos el auto-fetch de precio igual. Solo al montar / cuando
  // cambia el asset por la prop externa.
  useEffect(() => {
    if (mode === 'add' && form.asset && !pricesFetched && !form.buy_price) {
      fetchAndFillPrice(form.asset)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, form.asset])

  // Redondeo razonable según rango (cripto = más decimales, acciones = menos)
  const roundQty = (n) => {
    if (!n || !isFinite(n)) return ''
    if (n < 1) return +n.toFixed(8)
    if (n < 100) return +n.toFixed(6)
    return +n.toFixed(4)
  }
  const roundMoney = (n) => {
    if (!n || !isFinite(n)) return ''
    return +n.toFixed(2)
  }

  // Auto-fill del precio cuando elegís ticker (solo en modo "add", para no
  // pisar lo que ya estaba al editar).
  async function fetchAndFillPrice(ticker) {
    if (!ticker || mode === 'edit') return
    const symbol = isARS ? `${ticker}.BA` : ticker
    try {
      const data = await api.get(`/prices?symbols=${symbol}`)
      const price = data?.[symbol]
      if (price && price > 0) {
        setForm(f => {
          // Si ya hay precio puesto a mano, no pisar
          if (f.buy_price && f.buy_price !== '') return f
          const next = { ...f, buy_price: roundMoney(price) }
          // Recalcular el campo dependiente con el nuevo precio
          if (lastEdited === 'invested' && next.invested) {
            next.quantity = roundQty(+next.invested / price)
          } else if (lastEdited === 'quantity' && next.quantity) {
            next.invested = roundMoney(+next.quantity * price)
          }
          return next
        })
      }
    } catch {}
    setPricesFetched(true)
  }

  function onAssetChange(v) {
    const upper = (v || '').toUpperCase()
    setForm(f => ({ ...f, asset: upper }))
    setPricesFetched(false)
    if (upper.length >= 2) {
      // Pequeño debounce implícito: solo si el ticker tiene al menos 2 chars
      setTimeout(() => fetchAndFillPrice(upper), 150)
    }
  }

  function onPriceChange(v) {
    setForm(f => {
      const next = { ...f, buy_price: v }
      const priceNum = +v
      if (priceNum > 0) {
        if (lastEdited === 'invested' && next.invested) {
          next.quantity = roundQty(+next.invested / priceNum)
        } else if (lastEdited === 'quantity' && next.quantity) {
          next.invested = roundMoney(+next.quantity * priceNum)
        }
      }
      return next
    })
  }

  function onInvestedChange(v) {
    setLastEdited('invested')
    setForm(f => {
      const next = { ...f, invested: v }
      const inv = +v
      const price = +next.buy_price
      if (inv > 0 && price > 0) {
        next.quantity = roundQty(inv / price)
      }
      return next
    })
  }

  function onQuantityChange(v) {
    setLastEdited('quantity')
    setForm(f => {
      const next = { ...f, quantity: v }
      const qty = +v
      const price = +next.buy_price
      if (qty > 0 && price > 0) {
        next.invested = roundMoney(qty * price)
      }
      return next
    })
  }

  // Costo real total (incluye comisiones) — feedback en vivo
  const realCost = (() => {
    const inv = +form.invested || 0
    const com = +form.commissions || 0
    return inv + com
  })()
  const moneyLabel = isARS ? 'ARS' : 'USD'

  // Si es bono, mostramos un banner con la meta-data arriba del form
  const bondMeta = form.asset ? getBondMeta(form.asset) : null

  return (
    <Modal title={mode === 'edit' ? 'Editar posición' : 'Nueva posición'} onClose={onClose}>
      <div className="space-y-3">
        {bondMeta && (
          <div className="px-3 py-2.5 rounded bg-rendi-accent/[0.06] border border-rendi-accent/25">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[9px] font-mono uppercase tracking-[0.12em] px-1.5 py-0.5 rounded-sm bg-rendi-accent/15 text-rendi-accent border border-rendi-accent/30">
                Bono
              </span>
              <span className="text-xs font-semibold text-ink-0">{formatBondType(bondMeta.type)} · {bondMeta.issuer}</span>
            </div>
            <p className="text-[11px] text-ink-2 font-mono">
              {bondMeta.maturity ? `Vence ${bondMeta.maturity}` : 'Sin vencimiento (ETF)'}
              {(bondMeta.couponRate > 0 || bondMeta.couponSchedule || bondMeta.couponFreq === 'none') && (
                <>
                  {' · '}
                  <span
                    className="border-b border-dotted border-ink-3/40 cursor-help"
                    title={formatCouponTooltip(bondMeta)}
                  >
                    {formatCouponLabel(bondMeta)}
                  </span>
                </>
              )}
              {` · moneda ${bondMeta.currency}`}
            </p>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Broker</label>
            <select
              value={form.broker}
              onChange={e => setForm(f => ({ ...f, broker: e.target.value }))}
              className={inputClass}
            >
              {brokers.map(b => <option key={b.id} value={b.name}>{b.name} ({b.currency})</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Activo</label>
            {/* En modo 'add' el asset viene preseleccionado desde el flow
                (AddPositionFlow → step 2). Mostramos un display con logo +
                botón 'Cambiar' que vuelve al flow. En modo 'edit' o si no
                hay asset (fallback), mantenemos el TickerSearch. */}
            {mode === 'add' && form.asset && onChangeAsset ? (
              <div className="flex items-center gap-2.5 bg-slate-50 dark:bg-bg-2 border border-slate-300 dark:border-line rounded-md px-3 py-2">
                <AssetLogo asset={form.asset} size={28} />
                <span className="font-semibold text-ink-0 text-sm tabular flex-1">{form.asset}</span>
                <button
                  type="button"
                  onClick={onChangeAsset}
                  className="text-xs text-rendi-accent hover:underline"
                >
                  Cambiar
                </button>
              </div>
            ) : (
              <TickerSearch
                value={form.asset}
                onChange={onAssetChange}
                currency={selectedBrokerCurrency}
              />
            )}
          </div>
        </div>

        <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300 cursor-pointer">
          <input type="checkbox" checked={form.is_cash} onChange={e => setForm(f => ({ ...f, is_cash: e.target.checked }))} />
          Es cash
        </label>

        {!form.is_cash && (
          <>
            {/* Precio de compra — autofill al elegir ticker. Para bonos
                agregamos hint sobre la convención (precio por unidad VN,
                no por 100 VN) — esto es ambiguo en la UI de Cocos/BYMA
                donde el precio quoted es típicamente por 100 nominal. */}
            <Field
              label={`Precio de compra ${bondMeta ? '· por unidad VN' : ''}(${moneyLabel})`}
              value={form.buy_price}
              onChange={onPriceChange}
              type="number"
              step="any"
              hint={
                bondMeta
                  ? `Convención del sistema: precio por 1 VN (valor nominal). Si Cocos te muestra "${form.buy_price ? Math.round((+form.buy_price)*100) : '71.5'} por 100 VN", entrá ${form.buy_price ? (+form.buy_price).toFixed(3) : '0.715'} acá (precio quote ÷ 100). El total invertido se autocompleta abajo.`
                  : (pricesFetched && form.buy_price ? 'Precio actual de mercado · editable.' : 'Se autocompleta al seleccionar el activo. Ajustalo si la compra se realizó a otro precio.')
              }
            />

            {/* Invertido ⇄ Cantidad — bidireccional */}
            <div className="grid grid-cols-2 gap-3">
              <Field
                label={`Invertido (${moneyLabel})`}
                value={form.invested}
                onChange={onInvestedChange}
                type="number"
                step="any"
              />
              <Field
                label={bondMeta ? 'Cantidad (VN)' : 'Cantidad'}
                value={form.quantity}
                onChange={onQuantityChange}
                type="number"
                step="any"
                hint={bondMeta ? 'Valor nominal: 1 VN = 1 unidad de face value. Ej: 1000 VN de AL30 = USD 1000 face.' : undefined}
              />
            </div>
          </>
        )}

        {/* Comisiones (compra) — afectan el cost basis real */}
        {!form.is_cash && (
          <Field
            label={`Comisiones (${moneyLabel})`}
            value={form.commissions}
            onChange={v => setForm(f => ({ ...f, commissions: v }))}
            type="number"
            step="any"
            hint={(+form.commissions || 0) > 0
              ? `Costo total: ${realCost.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${moneyLabel} (invertido + comisión).`
              : 'Opcional. Se incluye en el costo de adquisición sin modificar la cantidad.'}
          />
        )}

        {isARS && !form.is_cash && (
          <Field
            label="TC Compra"
            value={form.tc_compra}
            onChange={v => setForm(f => ({ ...f, tc_compra: v }))}
            type="number"
            step="any"
            hint="Tipo de cambio del momento de la compra. Se usa para calcular el P&L equivalente en USD."
          />
        )}

        <div>
          <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Fecha de entrada</label>
          <DateInput
            value={form.entry_date}
            onChange={v => setForm(f => ({ ...f, entry_date: v }))}
          />
          <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">Por defecto se completa con la fecha de hoy. Ajustala para posiciones históricas.</p>
        </div>

        <Field label="Notas (opcional)" value={form.notes} onChange={v => setForm(f => ({ ...f, notes: v }))} placeholder="" />

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200">Cancelar</button>
          <button onClick={onSave} className="px-4 py-2 text-sm bg-rendi-accent hover:bg-rendi-accent/90 text-white rounded-md font-semibold transition">Guardar</button>
        </div>
      </div>
    </Modal>
  )
}

function QtySlider({ totalQty, quantity, onChange, asset, priceUsd, pnlUsd }) {
  const qtyNum = +quantity || 0
  const pctRaw = totalQty > 0 ? (qtyNum / totalQty) * 100 : 0
  const pct = Math.max(0, Math.min(100, pctRaw))
  const usdEq = priceUsd && qtyNum ? priceUsd * qtyNum : 0

  function setPct(p) {
    const newQty = (totalQty * p) / 100
    // redondeo razonable: 8 decimales para cripto, 4 para acciones
    const decimals = totalQty < 1 ? 8 : 6
    onChange(+newQty.toFixed(decimals))
  }

  function setQty(q) {
    const clean = q === '' ? '' : +q
    onChange(clean)
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-xs text-slate-500 dark:text-slate-400">Cantidad a vender</label>
        <span className="text-xs text-slate-400 dark:text-slate-500">
          Disp. <span className="font-mono text-slate-700 dark:text-slate-300">{totalQty.toLocaleString('en-US', { maximumFractionDigits: 8 })}</span>
        </span>
      </div>

      {/* Input combinado: cantidad + porcentaje */}
      <div className="flex items-stretch gap-2 mb-3">
        <div className="flex-1 relative">
          <input
            type="number"
            step="any"
            value={quantity}
            onChange={e => setQty(e.target.value)}
            placeholder="0"
            className="w-full bg-slate-50 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-md pl-3 pr-14 py-2 text-sm font-mono text-slate-900 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60"
          />
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400 dark:text-slate-500 font-medium pointer-events-none">
            {asset}
          </span>
        </div>
        <div className="w-20 bg-slate-50 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-md px-2 flex items-center justify-center">
          <span className="font-mono text-sm font-semibold text-rendi-accent">{pct.toFixed(0)}%</span>
        </div>
      </div>

      {/* Slider */}
      <div className="px-1">
        <input
          type="range"
          min="0"
          max="100"
          step="1"
          value={pct}
          onChange={e => setPct(+e.target.value)}
          className="rendi-range w-full"
          style={{ '--val': `${pct}%` }}
        />
        {/* Marks */}
        <div className="flex justify-between mt-2">
          {[0, 25, 50, 75, 100].map(p => (
            <button
              key={p}
              type="button"
              onClick={() => setPct(p)}
              className={`text-[10px] font-medium px-1.5 py-0.5 rounded transition ${
                Math.abs(pct - p) < 1
                  ? 'text-rendi-accent'
                  : 'text-slate-400 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
              }`}
            >
              {p === 100 ? 'MAX' : `${p}%`}
            </button>
          ))}
        </div>
      </div>

      {/* USD equivalente + P&L */}
      <div className="mt-3 px-3 py-2 bg-slate-50 dark:bg-slate-900/50 rounded-md space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-500 dark:text-slate-400">Equivalente</span>
          <span className="font-mono text-sm font-semibold text-slate-900 dark:text-white">
            ≈ ${usdEq.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD
          </span>
        </div>
        {pnlUsd != null && (
          <div className="flex items-center justify-between border-t border-slate-200 dark:border-slate-700/50 pt-1.5">
            <span className="text-xs text-slate-500 dark:text-slate-400">Profit estimado</span>
            <span className={`font-mono text-sm font-semibold ${pnlUsd >= 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-red-500 dark:text-red-400'}`}>
              {pnlUsd >= 0 ? '+' : ''}${Math.abs(pnlUsd).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
