// PositionStep — paso 2 del wizard: cargar primera posición (+ broker inline).
// ════════════════════════════════════════════════════════════════════════════
// 1-2 min. Le damos 3 opciones al user:
//   A. Importar CSV → redirige a /imports (flow existente, pero con flag de
//      vuelta a /onboarding al terminar)
//   B. Cargar manual → mini-form inline (ticker + cantidad + precio promedio)
//   C. Saltar → next directo a CompleteStep
//
// El CSV es lo más fricción pero más completo. Manual es rápido pero pide al
// user 3 datos. Saltar es lo menos friction — el user puede cargar después.

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowRight, ArrowLeft, Loader2, AlertCircle, Upload,
  PlusCircle, SkipForward,
} from 'lucide-react'
import { api } from '../../utils/api'

// Brokers comunes en AR + moneda default sugerida (mismo set que el viejo
// BrokerStep). El chip pre-llena nombre + moneda; el user puede tipear otro.
const POPULAR_BROKERS = [
  { name: 'Cocos Capital', currency: 'ARS' },
  { name: 'IOL', currency: 'ARS' },
  { name: 'Balanz', currency: 'ARS' },
  { name: 'Bull Market', currency: 'ARS' },
  { name: 'Binance', currency: 'USDT' },
  { name: 'Interactive Brokers', currency: 'USD' },
]

export default function PositionStep({ onNext, onBack }) {
  const navigate = useNavigate()
  const [mode, setMode] = useState(null) // null | 'manual' | 'csv' | 'skip'

  if (!mode) {
    return <ModeSelector setMode={setMode} onBack={onBack} navigate={navigate} onSkip={() => onNext({ skipped: true })} />
  }
  if (mode === 'manual') {
    return <ManualForm onNext={onNext} onBack={() => setMode(null)} />
  }
  // mode === 'skip' caso ya manejado en setMode
  return null
}

// ─── Selector de modo ──────────────────────────────────────────────────────

function ModeSelector({ setMode, onBack, navigate, onSkip }) {
  function goImport() {
    // Marcar que volvemos a onboarding al terminar la importación.
    // pages/Imports.jsx ya redirige a /bienvenida en first-time import; el
    // flag rendi_onboarding_pending hace que /bienvenida después nos lleve
    // a /onboarding?step=complete en lugar de a /.
    try {
      localStorage.setItem('rendi_onboarding_pending', '1')
    } catch {}
    navigate('/imports?from=onboarding')
  }

  return (
    <div>
      <div className="text-center mb-8">
        <h1 className="text-2xl md:text-3xl font-semibold tracking-tight text-ink-0 mb-3">
          Tu primera posición
        </h1>
        <p className="text-sm md:text-base text-ink-2 max-w-md mx-auto leading-relaxed">
          Cargá tu primera posición o subí el CSV de tu broker. Podés agregar más después.
        </p>
      </div>

      <div className="space-y-3 max-w-lg mx-auto">
        {/* Opción 1: CSV import */}
        <button
          type="button"
          onClick={goImport}
          className="w-full p-4 border border-line hover:border-data-violet hover:bg-data-violet/[0.04] rounded text-left transition-all group"
        >
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 rounded bg-bg-2 border border-line flex items-center justify-center text-data-violet flex-shrink-0">
              <Upload size={16} strokeWidth={1.75} />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-base font-medium text-ink-0 mb-1 flex items-center gap-2">
                Importar CSV
                <span className="text-[12.5px] text-data-violet bg-data-violet/15 px-1.5 py-0.5 rounded font-medium">recomendado</span>
              </h3>
              <p className="text-sm text-ink-2 leading-relaxed">
                Subís el archivo que te da tu broker. Detectamos formato automático (Cocos, Schwab, Binance, Bull Market) y mapeamos todas tus posiciones de una.
              </p>
            </div>
            <ArrowRight size={16} strokeWidth={1.75} className="text-ink-3 group-hover:text-data-violet group-hover:translate-x-0.5 transition-all flex-shrink-0 mt-1" />
          </div>
        </button>

        {/* Opción 2: Manual */}
        <button
          type="button"
          onClick={() => setMode('manual')}
          className="w-full p-4 border border-line hover:border-data-violet hover:bg-data-violet/[0.04] rounded text-left transition-all group"
        >
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 rounded bg-bg-2 border border-line flex items-center justify-center text-data-violet flex-shrink-0">
              <PlusCircle size={16} strokeWidth={1.75} />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-base font-medium text-ink-0 mb-1">Cargar manual</h3>
              <p className="text-sm text-ink-2 leading-relaxed">
                Tipeás ticker, cantidad y precio promedio. Ideal si tenés pocas posiciones o querés probar la app rápido.
              </p>
            </div>
            <ArrowRight size={16} strokeWidth={1.75} className="text-ink-3 group-hover:text-data-violet group-hover:translate-x-0.5 transition-all flex-shrink-0 mt-1" />
          </div>
        </button>

        {/* Opción 3: Saltar */}
        <button
          type="button"
          onClick={onSkip}
          className="w-full p-4 border border-line/40 hover:border-line rounded text-left transition-all group"
        >
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 rounded bg-bg-2/40 border border-line/40 flex items-center justify-center text-ink-3 flex-shrink-0">
              <SkipForward size={16} strokeWidth={1.75} />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-base font-medium text-ink-1 mb-1">Lo hago después</h3>
              <p className="text-sm text-ink-3 leading-relaxed">
                Voy a explorar la app primero. Puedo cargar mis posiciones cuando quiera desde Cartera.
              </p>
            </div>
            <ArrowRight size={16} strokeWidth={1.75} className="text-ink-3/60 group-hover:text-ink-2 flex-shrink-0 mt-1" />
          </div>
        </button>
      </div>

      {/* Back */}
      <div className="flex items-center justify-start mt-6 pt-4 border-t border-line/40 max-w-lg mx-auto">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink-1 transition-colors px-3 py-2"
        >
          <ArrowLeft size={14} strokeWidth={1.75} />
          Atrás
        </button>
      </div>
    </div>
  )
}

// ─── Form manual ───────────────────────────────────────────────────────────

function ManualForm({ onNext, onBack }) {
  const [brokerName, setBrokerName] = useState('')
  const [brokerCurrency, setBrokerCurrency] = useState('ARS')
  const [asset, setAsset] = useState('')
  const [quantity, setQuantity] = useState('')
  const [buyPrice, setBuyPrice] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  function pickBroker(b) {
    setBrokerName(b.name)
    setBrokerCurrency(b.currency)
    setError('')
  }

  async function handleSubmit(e) {
    e?.preventDefault?.()
    const cleanBroker = brokerName.trim()
    const cleanAsset = asset.trim().toUpperCase()
    const qty = parseFloat(quantity)
    const price = parseFloat(buyPrice)
    if (!cleanBroker) {
      setError('Elegí o tipeá el broker donde tenés esta posición.')
      return
    }
    if (!cleanAsset) {
      setError('Tipeá el ticker (ej. NVDA, AAPL, AL30, BTC).')
      return
    }
    if (!isFinite(qty) || qty <= 0) {
      setError('Cantidad debe ser un número positivo.')
      return
    }
    if (!isFinite(price) || price <= 0) {
      setError('Precio de compra debe ser un número positivo.')
      return
    }
    setSaving(true)
    setError('')
    // 1) Crear el broker (antes lo hacía BrokerStep). Si ya existe (409) seguimos.
    //    El backend NO auto-crea el broker desde POST /positions, así que sin
    //    esto la posición quedaría con un broker fantasma (moneda mal inferida).
    try {
      await api.post('/brokers', { name: cleanBroker, currency: brokerCurrency })
    } catch (ex) {
      // El backend devuelve 400 (IntegrityError) ante broker duplicado; algunos
      // setups devuelven 409. Cubrimos ambos para no depender del texto del mensaje.
      const dup = ex?.status === 409 || ex?.status === 400 || /existe|duplicate|UNIQUE/i.test(ex?.message || '')
      if (ex?.status === 403) {
        setError('Tu plan no permite más brokers. Importá por CSV o actualizá el plan.')
        setSaving(false)
        return
      }
      if (!dup) {
        setError(ex?.message || 'No pudimos guardar el broker. Probá de nuevo.')
        setSaving(false)
        return
      }
      // 409 → el broker ya existía, seguimos a crear la posición.
    }
    // 2) Crear la posición en ese broker.
    try {
      await api.post('/positions', {
        broker: cleanBroker,
        asset: cleanAsset,
        quantity: qty,
        buy_price: price,
        invested: qty * price,
      })
      onNext({ position: { asset: cleanAsset, quantity: qty, buy_price: price } })
    } catch (ex) {
      setError(ex?.message || 'No pudimos guardar la posición. Probá de nuevo.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <div className="text-center mb-8">
        <h2 className="text-2xl font-semibold text-ink-0 mb-2">Cargá una posición</h2>
        <p className="text-sm text-ink-2 max-w-md mx-auto">
          Sumá tu posición principal. Después podés agregar más desde Cartera.
        </p>
      </div>

      <div className="space-y-4 max-w-md mx-auto">
        {/* Broker — antes era un paso aparte; ahora se elige/crea acá inline */}
        <div>
          <label className="block text-[12.5px] text-ink-2 mb-2 font-medium">
            / broker
          </label>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {POPULAR_BROKERS.map((b) => (
              <button
                key={b.name}
                type="button"
                onClick={() => pickBroker(b)}
                className={`px-2.5 py-1 rounded border text-xs transition-colors ${
                  brokerName === b.name
                    ? 'border-data-violet bg-data-violet/10 text-ink-0'
                    : 'border-line text-ink-2 hover:border-line-3'
                }`}
              >
                {b.name}
              </button>
            ))}
          </div>
          <input
            type="text"
            value={brokerName}
            onChange={(e) => setBrokerName(e.target.value)}
            placeholder="ej. Cocos, IOL, Binance…"
            maxLength={60}
            className="w-full px-3 py-2.5 rounded bg-bg-1 border border-line focus:border-data-violet focus:outline-none text-base text-ink-0 placeholder-ink-3"
          />
          <div className="flex gap-2 mt-2">
            {['ARS', 'USD', 'USDT'].map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setBrokerCurrency(c)}
                className={`flex-1 px-2 py-1.5 rounded border text-xs font-mono transition-colors ${
                  brokerCurrency === c
                    ? 'border-data-violet bg-data-violet/5 text-ink-0'
                    : 'border-line text-ink-2 hover:border-line-3'
                }`}
              >
                {c}
              </button>
            ))}
          </div>
        </div>
        {/* Ticker */}
        <div>
          <label className="block text-[12.5px] text-ink-2 mb-2 font-medium">
            / ticker
          </label>
          <input
            type="text"
            value={asset}
            onChange={(e) => setAsset(e.target.value.toUpperCase())}
            placeholder="NVDA, AAPL, AL30, BTC…"
            maxLength={20}
            autoCapitalize="characters"
            autoCorrect="off"
            spellCheck="false"
            className="w-full px-3 py-2.5 rounded bg-bg-1 border border-line focus:border-data-violet focus:outline-none text-base text-ink-0 placeholder-ink-3 font-mono tracking-wider"
          />
          <p className="text-[11px] text-ink-3 mt-1.5">
            Si es CEDEAR argentino, usá sufijo .BA (ej. NVDA.BA).
          </p>
        </div>

        {/* Cantidad + Precio en 2 cols */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-[12.5px] text-ink-2 mb-2 font-medium">
              / cantidad
            </label>
            <input
              type="number"
              inputMode="decimal"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              placeholder="10"
              step="any"
              min="0"
              className="w-full px-3 py-2.5 rounded bg-bg-1 border border-line focus:border-data-violet focus:outline-none text-base text-ink-0 placeholder-ink-3"
            />
          </div>
          <div>
            <label className="block text-[12.5px] text-ink-2 mb-2 font-medium">
              / precio promedio
            </label>
            <input
              type="number"
              inputMode="decimal"
              value={buyPrice}
              onChange={(e) => setBuyPrice(e.target.value)}
              placeholder="120.50"
              step="any"
              min="0"
              className="w-full px-3 py-2.5 rounded bg-bg-1 border border-line focus:border-data-violet focus:outline-none text-base text-ink-0 placeholder-ink-3"
            />
          </div>
        </div>

        {/* Tip */}
        <div className="text-[11px] text-ink-3 leading-relaxed bg-bg-1/40 border border-line/40 rounded p-3">
          El precio promedio es lo que pagaste por unidad (sin contar comisiones).
          Si tenés varios lotes a precios distintos, podés cargarlos por separado después desde Cartera.
        </div>

        {/* Error */}
        {error && (
          <div className="p-3 border border-rendi-neg/30 bg-rendi-neg/5 rounded text-sm text-rendi-neg flex items-start gap-2">
            <AlertCircle size={16} strokeWidth={1.75} className="flex-shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}
      </div>

      {/* Botones */}
      <div className="flex items-center justify-between gap-3 mt-6 pt-4 border-t border-line/40 max-w-md mx-auto">
        <button
          type="button"
          onClick={onBack}
          disabled={saving}
          className="inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink-1 transition-colors px-3 py-2 disabled:opacity-40"
        >
          <ArrowLeft size={14} strokeWidth={1.75} />
          Cambiar opción
        </button>
        <button
          type="submit"
          disabled={saving || !brokerName.trim() || !asset.trim() || !quantity || !buyPrice}
          className="group inline-flex items-center gap-2 bg-data-violet hover:bg-data-violet/90 disabled:bg-data-violet/40 disabled:cursor-not-allowed text-white font-medium rounded-sm px-5 py-2.5 transition-colors text-sm"
        >
          {saving ? (
            <>
              <Loader2 size={14} strokeWidth={2} className="animate-spin" />
              Guardando…
            </>
          ) : (
            <>
              Guardar y continuar
              <ArrowRight size={14} strokeWidth={2} className="group-hover:translate-x-0.5 transition-transform" />
            </>
          )}
        </button>
      </div>
    </form>
  )
}
