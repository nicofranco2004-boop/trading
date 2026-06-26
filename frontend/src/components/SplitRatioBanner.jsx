// Banner de "cambio de ratio (split)" — detecta CEDEARs cuyo ratio cambió y que
// Rendi todavía no ajustó (pérdida fantasma: precio al ratio nuevo vs cantidad al
// viejo). Ofrece un ajuste de un clic: cantidad×F, precio÷F, la inversión queda
// igual. Self-contained: hace su propio fetch a /positions/split-check y, al
// ajustar, dispara rendi:portfolio-changed + el callback onAdjusted del padre.
import { useEffect, useState } from 'react'
import { AlertTriangle, Loader2, X } from 'lucide-react'
import Modal from './Modal'
import { api } from '../utils/api'

const fmt = (n) => Number(n || 0).toLocaleString('es-AR', { maximumFractionDigits: 2 })
const baseTicker = (a) => (a || '').replace(/\.BA$/i, '')
// F>=1 → "×3" (split normal); F<1 → "1:N" (split inverso, la cantidad se reduce)
const ratioLabel = (f) => (Number(f) >= 1 ? `×${fmt(f)}` : `1:${fmt(1 / Number(f || 1))}`)

export default function SplitRatioBanner({ onAdjusted }) {
  const [suggestions, setSuggestions] = useState([])
  const [dismissed, setDismissed] = useState(false)
  const [active, setActive] = useState(null) // suggestion en confirmación
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let alive = true
    api.get('/positions/split-check')
      .then((d) => { if (alive) setSuggestions(d?.suggestions || []) })
      .catch(() => {}) // silencioso: es un realce, no debe romper la página
    return () => { alive = false }
  }, [])

  if (dismissed || suggestions.length === 0) return null

  async function confirmAdjust() {
    if (!active) return
    setBusy(true); setErr(null)
    try {
      // Sin body: el server re-deriva el split (no confía en factor/ex_date del cliente).
      await api.post(`/positions/${active.pid}/adjust-ratio`)
      window.dispatchEvent(new Event('rendi:portfolio-changed'))
      setSuggestions((prev) => prev.filter((s) => s.pid !== active.pid))
      setActive(null)
      onAdjusted?.()
    } catch (e) {
      setErr(e?.message || 'No pudimos ajustar la posición. Reintentá.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/[0.07] px-3.5 py-3 text-sm">
        <div className="flex items-start gap-2.5">
          <AlertTriangle size={16} className="mt-0.5 flex-shrink-0 text-amber-500" />
          <div className="flex-1 min-w-0">
            <p className="text-ink-0 font-medium">
              {suggestions.length === 1
                ? 'Una posición tuvo un cambio de ratio (split)'
                : `${suggestions.length} posiciones tuvieron un cambio de ratio (split)`}
            </p>
            <p className="text-ink-2 mt-0.5">
              No perdiste plata — cambió el ratio del CEDEAR (split). Ajustá para que el P&amp;L deje de
              mostrar una diferencia que no es real.
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {suggestions.map((s) => (
                <button
                  key={s.pid}
                  onClick={() => { setErr(null); setActive(s) }}
                  className="inline-flex items-center gap-1.5 text-xs font-medium rounded-md border border-amber-500/40 bg-amber-500/10 hover:bg-amber-500/20 text-amber-600 dark:text-amber-400 px-2.5 py-1.5 transition-colors"
                >
                  Ajustar {baseTicker(s.asset)} ({ratioLabel(s.factor)})
                </button>
              ))}
            </div>
          </div>
          <button onClick={() => setDismissed(true)} className="text-ink-3 hover:text-ink-0 flex-shrink-0" aria-label="Cerrar">
            <X size={15} />
          </button>
        </div>
      </div>

      {active && (
        <Modal title="Ajustar por cambio de ratio" onClose={() => setActive(null)}>
          <div className="space-y-4 text-sm text-ink-1">
            <p>
              <strong className="text-ink-0">{baseTicker(active.asset)}</strong> tuvo un{' '}
              {active.factor < 1 ? 'split inverso' : 'split'} de <strong>{ratioLabel(active.factor)}</strong>{' '}
              el {active.ex_date}. Tu inversión no cambia:{' '}
              {active.factor < 1
                ? 'se reduce la cantidad de nominales y sube el precio unitario en la misma proporción.'
                : 'se multiplica la cantidad de nominales y baja el precio unitario en la misma proporción.'}
            </p>
            <div className="rounded-md border border-line bg-bg-2 px-3 py-2.5 font-mono text-xs space-y-1">
              <div className="flex justify-between">
                <span className="text-ink-3">Cantidad</span>
                <span>{fmt(active.current_qty)} → <span className="text-ink-0 font-semibold">{fmt(active.suggested_qty)}</span></span>
              </div>
              <div className="flex justify-between">
                <span className="text-ink-3">Tu inversión</span>
                <span>queda igual</span>
              </div>
            </div>
            <p className="text-ink-3 text-xs">
              Corrige la pérdida fantasma: el precio de hoy ya está al ratio nuevo, pero la cantidad
              guardada estaba al viejo.
            </p>
            {active.raw_splits?.length > 1 && (
              <p className="text-ink-3 text-xs">
                Splits detectados: {active.raw_splits.map((r) => `×${fmt(r.factor)} (${r.ex_date})`).join(', ')}.
              </p>
            )}
            {err && <div className="text-rendi-neg text-xs">{err}</div>}
            <div className="flex justify-end gap-2 pt-1">
              <button onClick={() => setActive(null)} className="px-4 py-2 text-sm text-ink-3 hover:text-ink-0">
                Cancelar
              </button>
              <button
                onClick={confirmAdjust}
                disabled={busy}
                className="px-4 py-2 text-sm rounded-md bg-rendi-pos/15 hover:bg-rendi-pos/25 text-rendi-pos border border-rendi-pos/30 font-semibold inline-flex items-center gap-1.5 disabled:opacity-50"
              >
                {busy && <Loader2 size={13} className="animate-spin" />} Ajustar
              </button>
            </div>
          </div>
        </Modal>
      )}
    </>
  )
}
