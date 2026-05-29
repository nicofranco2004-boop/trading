// BrokerStep — paso 2 del wizard: agregar primer broker.
// ════════════════════════════════════════════════════════════════════════════
// 30s. El user elige su broker entre chips pre-armados (los más comunes en AR)
// o tipea uno custom. Selecciona la moneda. POST /api/brokers y next.
//
// Brokers populares listados en orden de mercado share AR (aprox).
// Cada chip pre-llena el name + sugiere la moneda default.

import { useState } from 'react'
import { ArrowRight, ArrowLeft, Loader2, AlertCircle, Plus } from 'lucide-react'
import { api } from '../../utils/api'

// Brokers comunes en AR + sugerencia de moneda default.
// USD = brokers internacionales (Schwab, IBKR) o cuentas USD-only.
// USDT = exchanges crypto.
// ARS = brokers locales AR (Cocos, IOL, Balanz, Bull) que operan en pesos.
const POPULAR_BROKERS = [
  { name: 'Cocos Capital', currency: 'ARS', tag: 'AR' },
  { name: 'IOL', currency: 'ARS', tag: 'AR' },
  { name: 'Balanz', currency: 'ARS', tag: 'AR' },
  { name: 'Bull Market', currency: 'ARS', tag: 'AR' },
  { name: 'Schwab', currency: 'USD', tag: 'US' },
  { name: 'Interactive Brokers', currency: 'USD', tag: 'US' },
  { name: 'Binance', currency: 'USDT', tag: 'Crypto' },
  { name: 'Lemon Cash', currency: 'USDT', tag: 'Crypto' },
]

const CURRENCY_LABELS = {
  USD: 'USD (dólar — brokers internacionales)',
  USDT: 'USDT / Crypto (exchanges)',
  ARS: 'ARS (pesos — brokers argentinos)',
}

export default function BrokerStep({ onNext, onBack }) {
  const [name, setName] = useState('')
  const [currency, setCurrency] = useState('ARS')
  const [custom, setCustom] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  function pickPopular(broker) {
    setName(broker.name)
    setCurrency(broker.currency)
    setCustom(false)
    setError('')
  }

  function startCustom() {
    setName('')
    setCustom(true)
    setError('')
  }

  async function handleSubmit(e) {
    e?.preventDefault?.()
    const cleanName = name.trim()
    if (!cleanName) {
      setError('Elegí un broker o tipeá el nombre.')
      return
    }
    if (cleanName.length > 60) {
      setError('Nombre muy largo (máx 60 caracteres).')
      return
    }
    setSaving(true)
    setError('')
    try {
      await api.post('/brokers', { name: cleanName, currency })
      onNext({ broker: { name: cleanName, currency } })
    } catch (ex) {
      // 409 si ya existe un broker con ese nombre (ej. user clickea atrás y reintenta)
      if (ex?.status === 409 || /existe|duplicate|UNIQUE/i.test(ex?.message || '')) {
        // Ya está creado — seguimos adelante igual
        onNext({ broker: { name: cleanName, currency } })
        return
      }
      // 403 si Free y excede cap (improbable en onboarding, pero defensivo)
      if (ex?.status === 403) {
        setError('Tu plan no permite más brokers. Actualizá el plan para sumar más.')
      } else {
        setError(ex?.message || 'No pudimos guardar el broker. Probá de nuevo.')
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <div className="text-center mb-8">
        <h1 className="text-2xl md:text-3xl font-semibold tracking-tight text-ink-0 mb-3">
          ¿Dónde tenés tu plata?
        </h1>
        <p className="text-sm md:text-base text-ink-2 max-w-md mx-auto leading-relaxed">
          Elegí tu broker principal. Después podés sumar más desde Configuración.
        </p>
      </div>

      {/* Grid de brokers populares */}
      <div className="mb-5">
        <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-3">
          / brokers populares en argentina
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {POPULAR_BROKERS.map((b) => {
            const isSelected = !custom && name === b.name
            return (
              <button
                key={b.name}
                type="button"
                onClick={() => pickPopular(b)}
                className={`p-3 border rounded text-left transition-all min-h-[64px] flex flex-col justify-center ${
                  isSelected
                    ? 'border-data-violet bg-data-violet/10 ring-1 ring-data-violet/30'
                    : 'border-line hover:border-line-3 hover:bg-bg-2/40'
                }`}
              >
                <div className="text-sm font-medium text-ink-0">{b.name}</div>
                <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 mt-0.5">
                  {b.tag}
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {/* Custom broker */}
      <div className="mb-6">
        {!custom ? (
          <button
            type="button"
            onClick={startCustom}
            className="inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-data-violet transition-colors"
          >
            <Plus size={14} strokeWidth={1.75} />
            Otro broker (manual)
          </button>
        ) : (
          <div>
            <label className="block text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-2">
              / nombre del broker
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="ej. Bull Market, Wise, Cocos…"
              maxLength={60}
              autoFocus
              className="w-full px-3 py-2.5 rounded bg-bg-1 border border-line focus:border-data-violet focus:outline-none text-base text-ink-0 placeholder-ink-3"
            />
          </div>
        )}
      </div>

      {/* Moneda (siempre visible) */}
      <div className="mb-6">
        <label className="block text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-2">
          / moneda principal de la cuenta
        </label>
        <div className="space-y-2">
          {['ARS', 'USD', 'USDT'].map((c) => (
            <label
              key={c}
              className={`flex items-center gap-3 p-3 border rounded cursor-pointer transition-colors ${
                currency === c
                  ? 'border-data-violet bg-data-violet/5'
                  : 'border-line hover:border-line-3'
              }`}
            >
              <input
                type="radio"
                name="currency"
                value={c}
                checked={currency === c}
                onChange={() => setCurrency(c)}
                className="accent-data-violet"
              />
              <span className="text-sm text-ink-1">{CURRENCY_LABELS[c]}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 p-3 border border-rendi-neg/30 bg-rendi-neg/5 rounded text-sm text-rendi-neg flex items-start gap-2">
          <AlertCircle size={16} strokeWidth={1.75} className="flex-shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Botones */}
      <div className="flex items-center justify-between gap-3 pt-2 border-t border-line/40">
        <button
          type="button"
          onClick={onBack}
          disabled={saving}
          className="inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink-1 transition-colors px-3 py-2 disabled:opacity-40"
        >
          <ArrowLeft size={14} strokeWidth={1.75} />
          Atrás
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={saving || !name.trim()}
          className="group inline-flex items-center gap-2 bg-data-violet hover:bg-data-violet/90 disabled:bg-data-violet/40 disabled:cursor-not-allowed text-white font-medium rounded-sm px-5 py-2.5 transition-colors text-sm"
        >
          {saving ? (
            <>
              <Loader2 size={14} strokeWidth={2} className="animate-spin" />
              Guardando…
            </>
          ) : (
            <>
              Continuar
              <ArrowRight size={14} strokeWidth={2} className="group-hover:translate-x-0.5 transition-transform" />
            </>
          )}
        </button>
      </div>
    </div>
  )
}
