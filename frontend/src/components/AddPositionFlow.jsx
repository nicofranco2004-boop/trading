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
import { X, ArrowLeft, Search, Coins, TrendingUp, Layers, BarChart3, Activity, Building2, Landmark, PiggyBank, Wallet, ChevronDown, ChevronUp, FileText, ArrowRight } from 'lucide-react'
import {
  CRYPTO, STOCKS_US, ETFS, INDICES, CEDEARS_LIST, ARG_LIDER, ARG_GENERAL,
  BONDS_AR_SOV_USD, BONDS_AR_CER, BONDS_AR_ONS, BONDS_US_ETF, CATEGORY_TO_TYPE,
} from '../utils/tickers'
import { isLetraTicker } from '../utils/sections'
import { api } from '../utils/api'
import AssetResultRow from './AssetResultRow'

const _MONTH_NAMES = { E:'ene', F:'feb', M:'mar', A:'abr', Y:'may', J:'jun', L:'jul', G:'ago', S:'sep', O:'oct', N:'nov', D:'dic' }
function decodeLetraDate(sym) {
  const m = /^([A-Z])(\d{1,2})([EFMAYJLGSOND])(\d)$/.exec((sym || '').toUpperCase())
  if (!m) return null
  const [, , dd, mcode, yy] = m
  return `${dd} ${_MONTH_NAMES[mcode]} ${2020 + parseInt(yy)}`
}

// ─── Categorías ──────────────────────────────────────────────────────────────
// El orden refleja prioridad UX: tipos más usados primero.
// Bonos: combinamos las 4 sub-listas en una sola lista visible en step 2.
// Para que se distingan visualmente, cada item lleva un sufijo del subgrupo
// que se renderiza chiquito al lado del nombre.
const BONDS_COMBINED = [
  ...BONDS_AR_SOV_USD.map(b => ({ ...b, _sub: 'Soberano AR' })),
  ...BONDS_AR_CER.map(b =>     ({ ...b, _sub: 'CER (ARS)' })),
  ...BONDS_AR_ONS.map(b =>     ({ ...b, _sub: 'ON (Argentina)' })),
  ...BONDS_US_ETF.map(b =>     ({ ...b, _sub: 'ETF US' })),
]

const CATEGORIES = [
  { id: 'crypto',  label: 'Cripto',        icon: Coins,      list: CRYPTO,        hint: 'Bitcoin, Ethereum, stablecoins' },
  { id: 'stocks',  label: 'Acciones US',   icon: TrendingUp, list: STOCKS_US,     hint: 'NVDA, AAPL, MSFT…' },
  { id: 'cedears', label: 'CEDEARs',       icon: Layers,     list: CEDEARS_LIST,  hint: 'Acciones US listadas en BCBA' },
  { id: 'etfs',    label: 'ETFs',          icon: BarChart3,  list: ETFS,          hint: 'SPY, QQQ, VTI…' },
  { id: 'bonds',   label: 'Bonos y ONs',   icon: Landmark,   list: BONDS_COMBINED, hint: 'Soberanos AR, CER, obligaciones negociables, ETFs US' },
  { id: 'letras',  label: 'Letras',        icon: FileText,   list: null,          hint: 'LECAP, Letes, Boncap — ticker libre', freeText: true },
  { id: 'ar_lider',label: 'Panel Líder',   icon: Building2,  list: ARG_LIDER,     hint: 'Acciones argentinas — panel líder' },
  { id: 'ar_gen',  label: 'Panel General', icon: Building2,  list: ARG_GENERAL,   hint: 'Acciones argentinas — panel general' },
  { id: 'indices', label: 'Índices',       icon: Activity,   list: INDICES,       hint: 'S&P 500, Merval, IBOV…' },
]

export default function AddPositionFlow({ onClose, onAssetSelected, brokers = [], initialBroker = null, onPlazoFijo, onCreateBroker }) {
  // Secuencia de pasos. Si ya viene un broker preseleccionado (alta desde el
  // menú de un broker puntual, o "Cambiar" activo), salteamos el paso de broker.
  const needsBrokerStep = !initialBroker
  const SEQ = needsBrokerStep ? ['broker', 'type', 'ticker'] : ['type', 'ticker']
  const TOTAL = SEQ.length + 1  // +1 = el form de precio/cantidad (lo abre el padre)

  const [stepIdx, setStepIdx] = useState(0)
  const [chosenBroker, setChosenBroker] = useState(initialBroker || null)
  const [categoryId, setCategoryId] = useState(null)
  const [fciList, setFciList] = useState([])
  const current = SEQ[stepIdx]

  // El catálogo de FCI es dinámico (viene del backend); el resto de categorías
  // son listas estáticas de utils/tickers. Lo cargamos al montar.
  useEffect(() => {
    let alive = true
    api.get('/fci/catalog')
      .then(rows => {
        if (alive) setFciList((rows || []).map(r => ({
          s: r.symbol, n: r.display_name, _sub: r.emisor, _moneda: r.moneda,
        })))
      })
      .catch(() => {})
    return () => { alive = false }
  }, [])

  // Moneda del broker elegido → filtramos el catálogo FCI a fondos de esa
  // moneda. Un fondo en USD no puede vivir en un broker ARS (se valuaría como
  // si el precio fuera en pesos). Para el resto de activos no aplica esta regla.
  const brokerCurrency = (brokers.find(b => b.name === chosenBroker) || {}).currency || null
  const fciForBroker = useMemo(() => {
    if (!brokerCurrency) return fciList
    const wantUSD = brokerCurrency !== 'ARS'  // ARS broker → fondos ARS; USDT/USD → fondos USD
    return fciList.filter(f => (f._moneda === 'USD') === wantUSD)
  }, [fciList, brokerCurrency])

  const categories = useMemo(() => ([
    ...CATEGORIES,
    {
      id: 'fci', label: 'Fondos (FCI)', icon: PiggyBank, list: fciForBroker,
      hint: brokerCurrency === 'ARS'
        ? 'FIMA, money market, renta fija (en pesos)'
        : brokerCurrency
          ? 'Fondos en dólares (FIMA Dólares, etc.)'
          : 'FIMA, money market, renta fija…',
    },
  ]), [fciForBroker, brokerCurrency])

  // Derivamos la categoría del id para que refleje siempre la lista actual
  // (importa para FCI, que se llena async después del fetch).
  const category = categories.find(c => c.id === categoryId) || null

  // Universo aplanado para el BUSCADOR GENERAL del step de tipo: junta todos los
  // items de todas las categorías (respeta el filtro de FCI por moneda del
  // broker, que ya viene aplicado en `categories`). Cada item lleva su categoría
  // de origen (`_catId`) y su tipo (`_type`) para el badge y para rutear la
  // selección directo al form sin pasar por el paso de categoría.
  const universe = useMemo(() => categories.flatMap(cat => {
    const type = CATEGORY_TO_TYPE[cat.id] || null
    return (cat.list || []).map(t => ({ ...t, _catId: cat.id, _type: type }))
  }), [categories])

  // Esc cierra el flow desde cualquier step (a11y standard)
  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  function selectBroker(b) {
    setChosenBroker(b.name)
    setStepIdx(i => i + 1)
  }
  function selectCategory(cat) {
    setCategoryId(cat.id)
    setStepIdx(i => i + 1)
  }
  function selectTicker(t, catId = categoryId) {
    onAssetSelected({ asset: t.s, name: t.n, category: catId, broker: chosenBroker })
  }
  function back() {
    setStepIdx(i => {
      const leaving = SEQ[i]
      if (leaving === 'ticker') setCategoryId(null)
      if (leaving === 'type' && needsBrokerStep) setChosenBroker(null)
      return Math.max(0, i - 1)
    })
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm sm:p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-bg-1 border border-line rounded-t-2xl sm:rounded w-full max-w-3xl shadow-2xl max-h-[95vh] sm:max-h-[85vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <FlowHeader
          current={current}
          stepNum={stepIdx + 1}
          total={TOTAL}
          category={category}
          chosenBroker={chosenBroker}
          onBack={stepIdx > 0 ? back : null}
          onClose={onClose}
        />
        {current === 'broker' && <StepBrokerPicker brokers={brokers} onPick={selectBroker} onPlazoFijo={onPlazoFijo} onCreateBroker={onCreateBroker} />}
        {current === 'type' && (
          <Step1AssetType
            categories={categories}
            universe={universe}
            onPick={selectCategory}
            onPickAsset={t => selectTicker(t, t._catId)}
          />
        )}
        {current === 'ticker' && (
          category?.id === 'fci'
            ? <StepFciPicker list={category.list} onPick={selectTicker} />
            : category?.id === 'letras'
              ? <StepLetraPicker onPick={selectTicker} />
              : <Step2TickerPicker category={category} onPick={selectTicker} />
        )}
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// Header — botón back (si aplica) + título + cerrar
// ════════════════════════════════════════════════════════════════════════════
function FlowHeader({ current, stepNum, total, category, chosenBroker, onBack, onClose }) {
  const TITLES = {
    broker: 'Elegí el broker',
    type: 'Elegí el tipo de activo',
    ticker: `Buscar — ${category?.label || ''}`,
  }
  const SUBTITLES = {
    broker: '¿En qué broker entra esta posición?',
    type: chosenBroker
      ? `Va a ${chosenBroker}. Elegí qué tipo de activo querés agregar.`
      : 'Empezá eligiendo qué tipo de activo querés agregar.',
    ticker: 'Buscá por ticker o nombre. Después cargás precio y cantidad.',
  }

  return (
    <div className="flex items-start gap-3 px-5 py-4 border-b border-line flex-shrink-0">
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
        <p className="eyebrow mb-1">Paso {stepNum} de {total}</p>
        <h2 className="text-lg font-semibold text-ink-0 leading-tight">{TITLES[current]}</h2>
        <p className="text-xs text-ink-2 mt-0.5">{SUBTITLES[current]}</p>
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
// STEP 0 — Broker Picker (en qué cartera entra la posición)
// ════════════════════════════════════════════════════════════════════════════
function StepBrokerPicker({ brokers, onPick, onPlazoFijo, onCreateBroker }) {
  const hasBrokers = brokers && brokers.length > 0
  return (
    <div className="overflow-y-auto flex-1 p-5">
      {hasBrokers && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {brokers.map(b => (
            <button
              key={b.id ?? b.name}
              onClick={() => onPick(b)}
              className="text-left bg-bg-2/40 dark:bg-bg-2/40 border border-line rounded p-4 hover:border-rendi-accent/40 dark:hover:border-rendi-accent/40 transition-colors focus:outline-none focus:ring-2 focus:ring-rendi-accent/40"
            >
              <div className="flex items-center gap-3">
                <div className="flex-shrink-0 w-9 h-9 rounded-sm bg-bg-3 border border-line flex items-center justify-center text-rendi-accent">
                  <Wallet size={18} strokeWidth={1.5} aria-hidden="true" />
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="font-semibold text-ink-0 text-sm leading-tight truncate">{b.name}</h3>
                  <p className="text-[10px] font-mono text-ink-3 mt-1 uppercase tracking-[0.12em]">{b.currency}</p>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {!hasBrokers && !onPlazoFijo && (
        <div className="p-8 text-center">
          <p className="text-sm text-ink-2 mb-4">
            Todavía no tenés brokers. Creá el primero para empezar a cargar posiciones.
          </p>
          {onCreateBroker && (
            <button
              type="button"
              onClick={onCreateBroker}
              className="inline-flex items-center gap-2 bg-data-violet hover:bg-data-violet/90 text-white text-sm font-medium rounded-sm px-4 py-2 transition-colors"
            >
              Crear mi primer broker
            </button>
          )}
        </div>
      )}

      {/* Plazo fijo — no entra a un broker, va a un banco. Abre su propio form. */}
      {onPlazoFijo && (
        <>
          {hasBrokers && (
            <div className="flex items-center gap-3 my-4">
              <div className="flex-1 h-px bg-line" />
              <span className="text-[10px] font-mono uppercase tracking-[0.12em] text-ink-3">o</span>
              <div className="flex-1 h-px bg-line" />
            </div>
          )}
          <button
            onClick={onPlazoFijo}
            className="w-full text-left bg-bg-2/40 border border-line rounded p-4 hover:border-rendi-accent/40 transition-colors focus:outline-none focus:ring-2 focus:ring-rendi-accent/40"
          >
            <div className="flex items-center gap-3">
              <div className="flex-shrink-0 w-9 h-9 rounded-sm bg-bg-3 border border-line flex items-center justify-center text-rendi-accent">
                <Landmark size={18} strokeWidth={1.5} aria-hidden="true" />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold text-ink-0 text-sm leading-tight">Plazo fijo</h3>
                <p className="text-xs text-ink-2 mt-1 leading-snug">En un banco — cargás banco, capital, tasa y plazo.</p>
              </div>
            </div>
          </button>
        </>
      )}
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// STEP 1 — Asset Type Picker (grid de categorías)
// ════════════════════════════════════════════════════════════════════════════
function Step1AssetType({ categories, universe, onPick, onPickAsset }) {
  const [query, setQuery] = useState('')
  const q = query.trim().toLowerCase()
  const searching = q.length > 0

  // Buscador GENERAL: filtra el universo entero por ticker o nombre. Cap a 40
  // resultados para no renderizar miles de filas (el usuario refina escribiendo).
  const RESULT_CAP = 40
  const results = useMemo(() => {
    if (!q) return []
    return universe
      .filter(t => t.s.toLowerCase().includes(q) || (t.n || '').toLowerCase().includes(q))
      .slice(0, RESULT_CAP)
  }, [q, universe])

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Buscador general — arriba de las categorías, busca en TODO el universo */}
      <div className="px-5 py-3 border-b border-line bg-bg-2/40 dark:bg-bg-2/30 flex-shrink-0">
        <div className="relative">
          <Search size={14} strokeWidth={1.75} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3 pointer-events-none" aria-hidden="true" />
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Buscar cualquier activo — ticker o nombre (AAPL, Bitcoin, GGAL…)"
            autoComplete="off"
            spellCheck="false"
            className="w-full bg-white dark:bg-bg-1 border border-line rounded-sm pl-9 pr-3 py-2 text-sm text-ink-0 placeholder-ink-3 focus:outline-none focus:border-rendi-accent/60 focus:ring-2 focus:ring-rendi-accent/20 transition"
          />
        </div>
        {searching && (
          <p className="text-xs text-ink-3 font-mono mt-2">
            {results.length}{results.length === RESULT_CAP ? '+' : ''} {results.length === 1 ? 'resultado' : 'resultados'} · o elegí una categoría abajo
          </p>
        )}
      </div>

      <div className="overflow-y-auto flex-1">
        {searching ? (
          results.length === 0 ? (
            <div className="p-8 text-center text-sm text-ink-2">
              Sin resultados para <span className="font-mono">"{query}"</span>.
              <br />Probá con el ticker o entrá a una categoría.
            </div>
          ) : (
            <ul className="divide-y divide-line/50 dark:divide-line/40">
              {results.map(t => {
                const isFci = t._catId === 'fci'
                return (
                  <li key={`${t._catId}:${t.s}`}>
                    <AssetResultRow
                      symbol={t.s}
                      title={isFci ? t.n : undefined}
                      name={isFci ? undefined : t.n}
                      sub={isFci ? t._sub : (t._catId === 'bonds' ? t._sub : undefined)}
                      type={t._type}
                      onClick={() => onPickAsset(t)}
                    />
                  </li>
                )
              })}
            </ul>
          )
        ) : (
          <div className="p-5">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {categories.map(cat => {
                const Icon = cat.icon
                return (
                  <button
                    key={cat.id}
                    onClick={() => onPick(cat)}
                    className="text-left bg-bg-2/40 dark:bg-bg-2/40 border border-line rounded p-4 hover:border-rendi-accent/40 dark:hover:border-rendi-accent/40 transition-colors group focus:outline-none focus:ring-2 focus:ring-rendi-accent/40"
                  >
                    <div className="flex items-start gap-3">
                      <div className="flex-shrink-0 w-9 h-9 rounded-sm bg-bg-3 border border-line flex items-center justify-center text-rendi-accent">
                        <Icon size={18} strokeWidth={1.5} aria-hidden="true" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <h3 className="font-semibold text-ink-0 text-sm leading-tight">{cat.label}</h3>
                        <p className="text-xs text-ink-2 mt-1 leading-snug">{cat.hint}</p>
                        <p className="text-[10px] font-mono text-ink-3 mt-2 uppercase tracking-[0.12em]">
                          {cat.freeText ? 'Entrada libre' : `${cat.list.length} ${cat.list.length === 1 ? 'opción' : 'opciones'}`}
                        </p>
                      </div>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>
        )}
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
      <div className="px-5 py-3 border-b border-line bg-bg-2/40 dark:bg-bg-2/30 flex-shrink-0">
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
            className="w-full bg-white dark:bg-bg-1 border border-line rounded-sm pl-9 pr-3 py-2 text-sm text-ink-0 placeholder-ink-3 focus:outline-none focus:border-rendi-accent/60 focus:ring-2 focus:ring-rendi-accent/20 transition"
          />
        </div>
        <p className="text-xs text-ink-3 font-mono mt-2">
          {filtered.length} de {category.list.length} {category.list.length === 1 ? 'opción' : 'opciones'}
        </p>
      </div>

      {/* Lista scrollable */}
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="p-8 text-center text-sm text-ink-2 flex flex-col items-center gap-3">
            <span>Sin resultados para <span className="font-mono">"{query}"</span></span>
            {category.id === 'bonds' && query.trim().length >= 2 && (
              <button
                onClick={() => onPick({ s: query.trim().toUpperCase(), n: query.trim().toUpperCase() })}
                className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-sm bg-bg-2 hover:bg-bg-3 border border-line text-ink-1 transition mt-1"
              >
                <ArrowRight size={13} />
                Agregar <span className="font-mono mx-1">{query.trim().toUpperCase()}</span> como bono/ON
              </button>
            )}
          </div>
        ) : (
          <ul className="divide-y divide-line/50 dark:divide-line/40">
            {filtered.map(t => (
              <li key={t.s}>
                <AssetResultRow
                  symbol={t.s}
                  name={t.n}
                  sub={t._sub}
                  type={CATEGORY_TO_TYPE[category.id] || null}
                  onClick={() => onPick(t)}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// STEP 2 (FCI) — Picker agrupado por fondo. Cada fondo FIMA tiene varias clases
// ════════════════════════════════════════════════════════════════════════════
// STEP 2 (Letras) — entrada libre validada por el patrón del ticker.
// Las letras cambian constantemente (nueva emisión cada semanas), así que no
// hay lista estática: el user tipea el ticker y lo validamos contra el regex.
// ════════════════════════════════════════════════════════════════════════════
function StepLetraPicker({ onPick }) {
  const [val, setVal] = useState('')
  const inputRef = useRef(null)
  useEffect(() => { inputRef.current?.focus() }, [])

  const upper = val.trim().toUpperCase()
  const valid = isLetraTicker(upper)
  const maturity = valid ? decodeLetraDate(upper) : null

  function confirm() {
    if (!valid) return
    onPick({ s: upper, n: `Letra del Tesoro — vto. ${maturity}` })
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 p-5 gap-4">
      <div>
        <label className="block text-xs text-ink-3 font-mono uppercase tracking-[0.12em] mb-2">Ticker de la letra</label>
        <input
          ref={inputRef}
          type="text"
          value={val}
          onChange={e => setVal(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && confirm()}
          placeholder="T30A7, S31O5, X18J5…"
          autoComplete="off"
          spellCheck="false"
          className="w-full bg-white dark:bg-bg-1 border border-line rounded-sm px-3 py-2.5 text-sm font-mono text-ink-0 placeholder-ink-3 focus:outline-none focus:border-rendi-accent/60 focus:ring-2 focus:ring-rendi-accent/20 transition uppercase"
        />
        {upper && (
          <p className={`text-xs mt-2 ${valid ? 'text-rendi-pos' : 'text-rendi-warn'}`}>
            {valid
              ? `✓ Letra válida — vencimiento: ${maturity}`
              : 'Ticker no reconocido. Formato: prefijo (1 letra) + día (1-2 dígitos) + mes (E/F/M/A/Y/J/L/G/S/O/N/D) + año (1 dígito). Ej: T30A7, S31O5'}
          </p>
        )}
      </div>
      <p className="text-xs text-ink-3 leading-relaxed">
        Los códigos de mes son: <span className="font-mono">E</span>=ene, <span className="font-mono">F</span>=feb, <span className="font-mono">M</span>=mar, <span className="font-mono">A</span>=abr, <span className="font-mono">Y</span>=may, <span className="font-mono">J</span>=jun, <span className="font-mono">L</span>=jul, <span className="font-mono">G</span>=ago, <span className="font-mono">S</span>=sep, <span className="font-mono">O</span>=oct, <span className="font-mono">N</span>=nov, <span className="font-mono">D</span>=dic.
      </p>
      <button
        onClick={confirm}
        disabled={!valid}
        className="inline-flex items-center justify-center gap-2 bg-rendi-accent hover:bg-rendi-accent/90 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-sm px-4 py-2.5 transition-colors"
      >
        Continuar <ArrowRight size={14} />
      </button>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// de cuotaparte (A/B/C/P); en vez de listarlas sueltas, agrupamos por fondo y
// la clase se elige en un acordeón con una ayuda ("casi siempre es Clase A").
// ════════════════════════════════════════════════════════════════════════════
function StepFciPicker({ list, onPick }) {
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState(null)
  const inputRef = useRef(null)
  useEffect(() => { inputRef.current?.focus() }, [])

  const groups = useMemo(() => {
    const map = new Map()
    for (const t of (list || [])) {
      const m = (t.n || '').match(/^(.*?)\s*-\s*Clase\s+(\w+)\s*$/i)
      const base = m ? m[1].trim() : (t.n || '').trim()
      const cls = m ? m[2] : null
      if (!map.has(base)) map.set(base, { base, emisor: t._sub, classes: [] })
      map.get(base).classes.push({ ...t, cls })
    }
    const arr = [...map.values()]
    arr.forEach(g => g.classes.sort((a, b) => (a.cls || '').localeCompare(b.cls || '')))
    arr.sort((a, b) => a.base.localeCompare(b.base))
    return arr
  }, [list])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return groups
    return groups.filter(g =>
      g.base.toLowerCase().includes(q) || (g.emisor || '').toLowerCase().includes(q)
    )
  }, [query, groups])

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="px-5 py-3 border-b border-line bg-bg-2/40 dark:bg-bg-2/30 flex-shrink-0">
        <div className="relative">
          <Search size={14} strokeWidth={1.75} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3 pointer-events-none" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Buscar fondo (ej. Premium, Money Market…)"
            autoComplete="off"
            spellCheck="false"
            className="w-full bg-white dark:bg-bg-1 border border-line rounded-sm pl-9 pr-3 py-2 text-sm text-ink-0 placeholder-ink-3 focus:outline-none focus:border-rendi-accent/60 focus:ring-2 focus:ring-rendi-accent/20 transition"
          />
        </div>
        <p className="text-xs text-ink-3 font-mono mt-2">
          {filtered.length} {filtered.length === 1 ? 'fondo' : 'fondos'}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="p-8 text-center text-sm text-ink-2">
            Sin resultados para <span className="font-mono">"{query}"</span>
          </div>
        ) : (
          <ul className="divide-y divide-line/50 dark:divide-line/40">
            {filtered.map(g => {
              const single = g.classes.length === 1
              const isOpen = expanded === g.base
              return (
                <li key={g.base}>
                  <button
                    onClick={() => single ? onPick(g.classes[0]) : setExpanded(isOpen ? null : g.base)}
                    className="w-full flex items-center gap-3 px-5 py-3 hover:bg-bg-2 dark:hover:bg-bg-2/40 transition-colors text-left focus:outline-none focus:bg-bg-2 dark:focus:bg-bg-2/40"
                  >
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-amber-500/15 border border-amber-500/30 flex items-center justify-center text-amber-600 dark:text-amber-400 text-[10px] font-bold">
                      FCI
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-ink-0 text-sm truncate">{g.base}</p>
                      <p className="text-xs text-ink-2 truncate">{g.emisor}</p>
                    </div>
                    {single ? (
                      <span className="text-[10px] font-mono uppercase tracking-[0.12em] text-ink-3 flex-shrink-0">
                        Clase {g.classes[0].cls || '—'}
                      </span>
                    ) : (
                      <span className="text-[10px] font-mono uppercase tracking-[0.12em] text-ink-3 flex items-center gap-1 flex-shrink-0">
                        {g.classes.length} clases {isOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                      </span>
                    )}
                  </button>
                  {!single && isOpen && (
                    <div className="px-5 pb-3 pt-1 bg-bg-2/30">
                      <p className="text-[11px] text-ink-3 mb-2 leading-relaxed">
                        Elegí tu clase de cuotaparte. Si no la sabés, mirá tu resumen del broker — en la mayoría de los casos es <span className="text-ink-1 font-medium">Clase A</span>.
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {g.classes.map(c => (
                          <button
                            key={c.s}
                            onClick={() => onPick(c)}
                            className="px-3 py-1.5 rounded-md border border-line bg-bg-1 hover:border-rendi-accent/50 hover:bg-rendi-accent/5 text-sm text-ink-1 transition-colors"
                          >
                            Clase {c.cls}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
