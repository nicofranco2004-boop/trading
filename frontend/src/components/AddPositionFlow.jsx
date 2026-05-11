// AddPositionFlow — flujo progresivo para agregar una posición.
// ════════════════════════════════════════════════════════════════════════════
// Reemplaza el modal denso de "Agregar posición" que mostraba TODO de una.
// Patrón inspirado en Delta by eToro / TradingView: pasos progresivos donde
// el usuario primero elige tipo de asset, después busca el ticker, y recién
// ahí carga los datos de la operación.
//
// Steps:
//   1. AssetTypePicker — grid de categorías (Cripto / Acciones / CEDEARs /
//      ETFs / Índices / AR Líder / AR General)
//   2. TickerPicker — lista filtrada por categoría con buscador y logos
//   3. (lo maneja el padre) PositionFormModal con el asset ya seleccionado
//
// Responsive:
//   • Desktop ≥768px → modal grande max-w-3xl, h≈80vh, centrado
//   • Mobile         → bottom sheet full-width con safe-area

import { useState, useMemo, useRef, useEffect } from 'react'
import { X, ArrowLeft, Search, Coins, TrendingUp, Layers, BarChart3, Activity, Building2 } from 'lucide-react'
import { CRYPTO, STOCKS_US, ETFS, INDICES, CEDEARS_LIST, ARG_LIDER, ARG_GENERAL } from '../utils/tickers'
import AssetLogo from './AssetLogo'

// ─── Categorías ──────────────────────────────────────────────────────────────
// El orden refleja prioridad UX: tipos más usados primero.
const CATEGORIES = [
  { id: 'crypto',  label: 'Cripto',        icon: Coins,      list: CRYPTO,        hint: 'Bitcoin, Ethereum, stablecoins' },
  { id: 'stocks',  label: 'Acciones US',   icon: TrendingUp, list: STOCKS_US,     hint: 'NVDA, AAPL, MSFT…' },
  { id: 'cedears', label: 'CEDEARs',       icon: Layers,     list: CEDEARS_LIST,  hint: 'Acciones US listadas en BCBA' },
  { id: 'etfs',    label: 'ETFs',          icon: BarChart3,  list: ETFS,          hint: 'SPY, QQQ, VTI…' },
  { id: 'ar_lider',label: 'Panel Líder',   icon: Building2,  list: ARG_LIDER,     hint: 'Acciones argentinas — panel líder' },
  { id: 'ar_gen',  label: 'Panel General', icon: Building2,  list: ARG_GENERAL,   hint: 'Acciones argentinas — panel general' },
  { id: 'indices', label: 'Índices',       icon: Activity,   list: INDICES,       hint: 'S&P 500, Merval, IBOV…' },
]

export default function AddPositionFlow({ onClose, onAssetSelected }) {
  const [step, setStep] = useState(1)
  const [category, setCategory] = useState(null)

  // Esc cierra el flow desde cualquier step (a11y standard)
  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  function selectCategory(cat) {
    setCategory(cat)
    setStep(2)
  }
  function selectTicker(t) {
    onAssetSelected({ asset: t.s, name: t.n, category: category?.id })
  }
  function back() {
    if (step === 2) {
      setStep(1)
      setCategory(null)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm sm:p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded-t-2xl sm:rounded w-full max-w-3xl shadow-2xl max-h-[95vh] sm:max-h-[85vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <FlowHeader
          step={step}
          category={category}
          onBack={step > 1 ? back : null}
          onClose={onClose}
        />
        {step === 1 && <Step1AssetType onPick={selectCategory} />}
        {step === 2 && <Step2TickerPicker category={category} onPick={selectTicker} />}
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// Header — botón back (si aplica) + título + cerrar
// ════════════════════════════════════════════════════════════════════════════
function FlowHeader({ step, category, onBack, onClose }) {
  const title = step === 1
    ? 'Elegí el tipo de activo'
    : `Buscar — ${category?.label || ''}`
  const subtitle = step === 1
    ? 'Empezá eligiendo qué tipo de activo querés agregar.'
    : 'Buscá por ticker o nombre. Después cargás precio y cantidad.'

  return (
    <div className="flex items-start gap-3 px-5 py-4 border-b border-slate-200 dark:border-line flex-shrink-0">
      {onBack && (
        <button
          onClick={onBack}
          className="flex-shrink-0 -ml-2 p-2 rounded-sm text-ink-2 hover:text-ink-0 hover:bg-bg-2 transition-colors"
          aria-label="Volver al paso anterior"
        >
          <ArrowLeft size={16} strokeWidth={1.75} aria-hidden="true" />
        </button>
      )}
      <div className="min-w-0 flex-1">
        <p className="eyebrow mb-1">Paso {step} de 3</p>
        <h2 className="text-lg font-semibold text-ink-0 leading-tight">{title}</h2>
        <p className="text-xs text-ink-2 mt-0.5">{subtitle}</p>
      </div>
      <button
        onClick={onClose}
        className="flex-shrink-0 -mr-2 p-2 rounded-sm text-ink-2 hover:text-ink-0 hover:bg-bg-2 transition-colors"
        aria-label="Cerrar"
      >
        <X size={16} strokeWidth={1.75} aria-hidden="true" />
      </button>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// STEP 1 — Asset Type Picker (grid de categorías)
// ════════════════════════════════════════════════════════════════════════════
function Step1AssetType({ onPick }) {
  return (
    <div className="overflow-y-auto flex-1 p-5">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {CATEGORIES.map(cat => {
          const Icon = cat.icon
          return (
            <button
              key={cat.id}
              onClick={() => onPick(cat)}
              className="text-left bg-slate-50/40 dark:bg-bg-2/40 border border-slate-200 dark:border-line rounded p-4 hover:border-rendi-accent/40 dark:hover:border-rendi-accent/40 transition-colors group focus:outline-none focus:ring-2 focus:ring-rendi-accent/40"
            >
              <div className="flex items-start gap-3">
                <div className="flex-shrink-0 w-9 h-9 rounded-sm bg-bg-3 border border-line flex items-center justify-center text-rendi-accent">
                  <Icon size={18} strokeWidth={1.5} aria-hidden="true" />
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="font-semibold text-ink-0 text-sm leading-tight">{cat.label}</h3>
                  <p className="text-xs text-ink-2 mt-1 leading-snug">{cat.hint}</p>
                  <p className="text-[10px] font-mono text-ink-3 mt-2 uppercase tracking-[0.12em]">
                    {cat.list.length} {cat.list.length === 1 ? 'opción' : 'opciones'}
                  </p>
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// STEP 2 — Ticker Picker (search + lista con logos)
// ════════════════════════════════════════════════════════════════════════════
function Step2TickerPicker({ category, onPick }) {
  const [query, setQuery] = useState('')
  const inputRef = useRef(null)

  // Autofocus al search al entrar al step
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Filtrado por ticker (símbolo) o nombre, case-insensitive
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return category.list
    return category.list.filter(t =>
      t.s.toLowerCase().includes(q) || (t.n || '').toLowerCase().includes(q)
    )
  }, [query, category])

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Search bar — sticky top */}
      <div className="px-5 py-3 border-b border-slate-200 dark:border-line bg-slate-50/40 dark:bg-bg-2/30 flex-shrink-0">
        <div className="relative">
          <Search size={14} strokeWidth={1.75} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3 pointer-events-none" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder={`Buscar por ticker o nombre…`}
            autoComplete="off"
            spellCheck="false"
            className="w-full bg-white dark:bg-bg-1 border border-slate-300 dark:border-line rounded-sm pl-9 pr-3 py-2 text-sm text-ink-0 placeholder-ink-3 focus:outline-none focus:border-rendi-accent/60 focus:ring-2 focus:ring-rendi-accent/20 transition"
          />
        </div>
        <p className="text-xs text-ink-3 font-mono mt-2">
          {filtered.length} de {category.list.length} {category.list.length === 1 ? 'opción' : 'opciones'}
        </p>
      </div>

      {/* Lista scrollable */}
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="p-8 text-center text-sm text-ink-2">
            Sin resultados para <span className="font-mono">"{query}"</span>
          </div>
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-line/40">
            {filtered.map(t => (
              <li key={t.s}>
                <button
                  onClick={() => onPick(t)}
                  className="w-full flex items-center gap-3 px-5 py-3 hover:bg-slate-50 dark:hover:bg-bg-2/40 transition-colors text-left focus:outline-none focus:bg-slate-50 dark:focus:bg-bg-2/40"
                >
                  <AssetLogo asset={t.s} size={32} />
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-ink-0 text-sm tabular">{t.s}</p>
                    <p className="text-xs text-ink-2 truncate">{t.n}</p>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
