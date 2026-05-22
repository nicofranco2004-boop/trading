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

import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { ArrowDownUp, Search, Repeat, Star, Check, Briefcase, Sparkles, Plus, Pencil, Trash2, X } from 'lucide-react'
import AnalysisDrawer from '../components/ai/AnalysisDrawer'
import AssetLogo from '../components/AssetLogo'
import EmptyState from '../components/EmptyState'
import SwipeRow from '../components/mobile/SwipeRow'
import Modal from '../components/Modal'
import UpgradeModal from '../components/plan/UpgradeModal'
import AddPositionFlow from '../components/AddPositionFlow'
import { PositionFormModal, EMPTY_POS, today } from './Positions'
import { useToast } from '../components/Toast'
import { api } from '../utils/api'
import { fmtUsd, ars, pctSigned, colorClass } from '../utils/format'
import { track } from '../utils/track'
import { notifyWatchlistChanged } from '../utils/watchlistEvents'
import { refreshPlanFeatures } from '../hooks/usePlanFeatures'

const SORT_OPTIONS = [
  { id: 'value',  label: 'Valor' },
  { id: 'pnl',    label: 'P&L %' },
  { id: 'alpha',  label: 'A-Z' },
]

const ALL_FILTER = '__all__'

export default function PositionsMobile() {
  const navigate = useNavigate()
  const location = useLocation()
  const [positions, setPositions] = useState([])
  const [brokers, setBrokers] = useState([])
  const [prices, setPrices] = useState({})
  const [dolar, setDolar] = useState(null)
  const [loading, setLoading] = useState(true)
  const [sortBy, setSortBy] = useState('value')
  const [query, setQuery] = useState('')
  const [brokerFilter, setBrokerFilter] = useState(ALL_FILTER)
  // Modales de gestión de broker (mismo flow que el desktop BrokerManager)
  const [showAddBroker, setShowAddBroker] = useState(false)
  const [editingBroker, setEditingBroker] = useState(null)
  const [newBroker, setNewBroker] = useState({ name: '', currency: 'USDT' })
  const [brokerUpgrade, setBrokerUpgrade] = useState(null)
  // Modales del flow de Nueva Posición (gatillados por el FAB del mobile tabbar
  // que navega a /posiciones?action=new). Reusan los mismos componentes que
  // desktop: AddPositionFlow (asset type → ticker search) → PositionFormModal
  // (broker, precio, cantidad, comisión, fecha).
  //
  //   addModal = null         → ningún modal abierto
  //              'add-flow'   → picker de tipo de activo + ticker search
  //              'add'        → form completo con asset preseteado
  const [addModal, setAddModal] = useState(null)
  const [addForm, setAddForm] = useState(EMPTY_POS)

  useEffect(() => { loadAll() }, [])

  // ?action=new → abrir el flow de Nueva Posición automáticamente.
  // Limpiamos el query param para que un reload posterior no re-abra el modal.
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    if (params.get('action') === 'new') {
      track('position_add_started', { source: 'mobile_fab' })
      setAddForm({
        ...EMPTY_POS,
        broker: brokers[0]?.name ?? '',
        entry_date: today(),
      })
      setAddModal('add-flow')
      // Limpiar el param sin recargar
      navigate('/posiciones', { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search, brokers.length])

  async function loadAll() {
    try {
      const [pos, bkrs, dol] = await Promise.all([
        api.get('/positions').catch(() => []),
        api.get('/brokers').catch(() => []),
        api.get('/dolar').catch(() => null),
      ])
      setPositions(pos || [])
      setBrokers(bkrs || [])
      setDolar(dol)
      await loadPrices(pos || [], bkrs || [])
    } finally {
      setLoading(false)
    }
  }

  async function loadPrices(pos, bkrs) {
    const arsBrokers = new Set(bkrs.filter(b => b.currency === 'ARS').map(b => b.name))
    const usdtBrokers = new Set(bkrs.filter(b => b.currency !== 'ARS').map(b => b.name))
    const arsSyms = [...new Set(pos.filter(p => arsBrokers.has(p.broker) && !p.is_cash).map(p => p.asset + '.BA'))]
    const usdtSyms = [...new Set(pos.filter(p => usdtBrokers.has(p.broker) && !p.is_cash && p.asset !== 'USDT').map(p => p.asset))]
    const all = [...arsSyms, ...usdtSyms].join(',')
    if (!all) return
    try { setPrices(await api.get(`/prices?symbols=${all}`)) } catch { /* silent */ }
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
    if (!confirm(`¿Eliminar el broker "${b.name}"? Se van a borrar también TODAS sus posiciones, operaciones y datos mensuales. Esta acción no se puede deshacer.`)) return
    await api.delete(`/brokers/${b.id}`)
    if (brokerFilter === b.name) setBrokerFilter(ALL_FILTER)
    await loadAll()
    refreshPlanFeatures()
  }

  const tcBlue = dolar?.blue?.venta || 1415
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
        return { ...p, valueUsd, priceLocal: null, pnlUsd: null, pnlPct: null, isAR }
      } else if (isAR) {
        priceLocal = p.price_override ?? prices[p.asset + '.BA']
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
      return { ...p, valueUsd, priceLocal, pnlUsd, pnlPct, isAR }
    })
  }, [positions, prices, arsBrokerSet, tcBlue])

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
  const visibleCount = brokerFilter === ALL_FILTER
    ? filteredByBroker.length
    : (flatList?.length || 0)

  if (loading) {
    return (
      <div className="px-4 py-8 text-center text-ink-3 text-sm" aria-live="polite">
        Cargando posiciones…
      </div>
    )
  }

  return (
    <div className="pb-8">
      {/* Header con total + sort */}
      <header className="sticky top-[88px] z-20 bg-bg-0/95 backdrop-blur-md border-b border-line/40 px-4 pt-3 pb-2">
        <div className="flex items-baseline justify-between mb-2">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 leading-none mb-1">
              Cartera total
            </div>
            <div className="text-xl font-medium tabular text-ink-0 leading-none">
              ${Math.round(total).toLocaleString('en-US')}
              <span className="text-xs text-ink-3 ml-1 font-normal">USD</span>
            </div>
          </div>
          <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
            {visibleCount} {visibleCount === 1 ? 'pos' : 'pos'}
          </span>
        </div>

        {/* Search input compacto */}
        <div className="relative mb-2">
          <Search size={12} strokeWidth={1.75} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar ticker o broker…"
            className="w-full bg-bg-2 border border-line/40 rounded-sm pl-7 pr-3 py-1.5 text-xs text-ink-0 placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-rendi-accent/40"
          />
        </div>

        {/* Filtro de broker — chips horizontales scrollables */}
        <div className="-mx-4 px-4 mb-2 overflow-x-auto no-scrollbar">
          <div className="inline-flex gap-1.5 pb-0.5">
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
              className="inline-flex items-center gap-1 text-[11px] font-medium bg-data-violet/10 hover:bg-data-violet/15 text-data-violet border border-dashed border-data-violet/40 rounded-sm px-2.5 py-1.5 whitespace-nowrap transition-colors"
            >
              <Plus size={11} strokeWidth={2} />
              Agregar
            </button>
          </div>
        </div>

        {/* Sort segmented */}
        <div className="flex items-center gap-1.5">
          <ArrowDownUp size={11} strokeWidth={1.75} className="text-ink-3" />
          <div className="inline-flex bg-bg-2 p-0.5 rounded-sm">
            {SORT_OPTIONS.map(o => (
              <button
                key={o.id}
                onClick={() => setSortBy(o.id)}
                className={`px-2 py-0.5 text-[10px] font-mono uppercase tracking-caps rounded-sm transition-colors ${
                  sortBy === o.id ? 'bg-bg-3 text-ink-0' : 'text-ink-3 hover:text-ink-1'
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
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
        <div className="divide-y divide-line/20">
          {grouped?.map(g => (
            <BrokerSection
              key={g.broker.name}
              broker={g.broker}
              positions={g.positions}
              totalUsd={g.totalUsd}
              onEdit={() => setEditingBroker({ ...g.broker })}
              onDelete={() => deleteBrokerAction(g.broker)}
            />
          ))}
        </div>
      ) : (
        // Vista filtrada — lista plana del broker seleccionado
        <ul className="divide-y divide-line/30">
          {flatList?.map(p => (
            <PositionRow
              key={`${p.broker}:${p.asset}:${p.id || p.entry_date}`}
              p={p}
            />
          ))}
        </ul>
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
                  PositionFormModal con el asset preseteado. */}
      {addModal === 'add-flow' && (
        <AddPositionFlow
          onClose={() => setAddModal(null)}
          onAssetSelected={({ asset }) => {
            setAddForm(f => ({ ...f, asset }))
            setAddModal('add')
          }}
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

// ─── BrokerSection ─────────────────────────────────────────────────────────
// Header con nombre del broker + currency + valor total + acciones edit/delete.
// Debajo, las positions del broker (cash siempre al final).

function BrokerSection({ broker, positions, totalUsd, onEdit, onDelete }) {
  return (
    <section>
      <div className="sticky top-[252px] z-10 bg-bg-0/95 backdrop-blur-md px-4 py-2 flex items-center justify-between gap-2 border-b border-line/30">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[11px] font-mono uppercase tracking-caps text-ink-1 truncate">
            {broker.name}
          </span>
          <span className="text-[9px] font-mono uppercase tracking-caps px-1 py-px rounded-sm bg-bg-2 text-ink-3">
            {broker.currency}
          </span>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <span className="text-xs font-medium tabular text-ink-1">
            ${Math.round(totalUsd).toLocaleString('en-US')}
          </span>
          <button
            type="button"
            onClick={onEdit}
            className="p-1 rounded-sm text-ink-3 hover:text-ink-0 hover:bg-bg-2 transition-colors"
            aria-label={`Editar ${broker.name}`}
          >
            <Pencil size={10} strokeWidth={1.75} />
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="p-1 rounded-sm text-ink-3 hover:text-rendi-neg hover:bg-bg-2 transition-colors"
            aria-label={`Eliminar ${broker.name}`}
          >
            <Trash2 size={10} strokeWidth={1.75} />
          </button>
        </div>
      </div>
      <ul className="divide-y divide-line/20">
        {positions.map(p => (
          <PositionRow
            key={`${p.broker}:${p.asset}:${p.id || p.entry_date}`}
            p={p}
          />
        ))}
      </ul>
    </section>
  )
}

// ─── Row ──────────────────────────────────────────────────────────────────
// Layout en 3 columnas para aprovechar el ancho:
//   [avatar]  TICKER · broker        P/L USD       $value USD
//             qty · CUR              +X.X%         USD
// Cash: NO muestra P/L (no tiene sentido la variación %). Solo value.
//
// Sprint M3 item 12: swipe izquierda revela 2 acciones rápidas:
//   - Operar: navega a /operaciones?action=new&asset=X
//   - Watchlist: agrega el símbolo a la watchlist

function PositionRow({ p }) {
  const navigate = useNavigate()
  const toast = useToast()
  const cur = p.isAR ? 'ARS' : 'USD'
  const [addedToWl, setAddedToWl] = useState(false)
  const [aiOpen, setAiOpen] = useState(false)

  const actions = p.is_cash ? [] : [
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
    {
      id: 'op',
      label: 'Operar',
      icon: Repeat,
      tone: 'accent',
      onClick: () => {
        track('mobile_swipe_action', { code: 'operate', asset: p.asset })
        navigate(`/operaciones?action=new&asset=${encodeURIComponent(p.asset)}&broker=${encodeURIComponent(p.broker)}`)
      },
    },
    {
      id: 'wl',
      label: addedToWl ? 'Listo' : 'Watchlist',
      icon: addedToWl ? Check : Star,
      tone: addedToWl ? 'pos' : 'warn',
      onClick: async () => {
        if (addedToWl) return
        track('mobile_swipe_action', { code: 'watchlist', asset: p.asset })
        try {
          await api.post('/watchlist', { symbol: p.asset })
          setAddedToWl(true)
          notifyWatchlistChanged({ symbol: p.asset, added: true })
          toast?.show?.({ kind: 'success', text: `${p.asset} agregado a watchlist` })
        } catch (ex) {
          toast?.show?.({ kind: 'error', text: ex?.message || 'Error al agregar' })
        }
      },
    },
  ]

  return (
    <>
    <SwipeRow
      actions={actions}
      onTap={() => navigate(p.id ? `/posiciones/${p.id}` : '/posiciones')}
      rowId={`${p.broker}:${p.asset}:${p.id || ''}`}
    >
      <div
        className="flex items-center gap-3 px-4 py-3 hover:bg-bg-2/30 active:bg-bg-3 transition-colors cursor-pointer"
      >
      <AssetLogo asset={p.asset} isCash={!!p.is_cash} size={32} />

      {/* Col 1: identificador */}
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-1.5">
          <span className="text-sm font-semibold text-ink-0 leading-none truncate">
            {p.asset}
          </span>
        </div>
        <div className="text-[11px] font-mono text-ink-3 leading-none mt-1.5 truncate">
          {p.is_cash ? 'Cash' : `${formatQty(p.quantity)} · ${cur}`}
        </div>
      </div>

      {/* Col 2: P/L (oculto para cash — no tiene variación) */}
      {!p.is_cash && (p.pnlUsd != null || p.pnlPct != null) && (
        <div className="flex-shrink-0 text-right min-w-[72px]">
          <div className={`text-sm font-medium tabular leading-none ${colorClass(p.pnlUsd)}`}>
            {p.pnlUsd >= 0 ? '+' : '−'}${Math.abs(Math.round(p.pnlUsd)).toLocaleString('en-US')}
          </div>
          <div className={`text-[11px] font-mono tabular leading-none mt-1.5 ${colorClass(p.pnlPct)}`}>
            {pctSigned(p.pnlPct)}
          </div>
        </div>
      )}

      {/* Col 3: valor actual */}
      <div className="flex-shrink-0 text-right min-w-[78px]">
        <div className="text-sm font-medium tabular text-ink-0 leading-none">
          ${Math.round(p.valueUsd).toLocaleString('en-US')}
        </div>
        <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 leading-none mt-1.5">
          USD
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
        subtitle={`${p.asset} · ${p.broker}`}
      />
    )}
    </>
  )
}

function formatQty(q) {
  if (q == null || isNaN(q)) return '—'
  if (Math.abs(q) >= 1000) return Math.round(q).toLocaleString('en-US')
  if (Math.abs(q) >= 1) return q.toFixed(2).replace(/\.00$/, '')
  return q.toFixed(4)
}
