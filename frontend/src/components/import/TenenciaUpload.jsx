import { useEffect, useState } from 'react'
import { api } from '../../utils/api'

// Completar la cartera con la "Tenencia valorizada" (PDF) de Bull Market — la
// foto de posiciones. Reconcilia contra lo ya importado de la Cuenta Corriente:
// completa SOLO lo que falta (comprado antes de la ventana de la CC), sin
// duplicar. Backend: POST /imports/tenencia/preview → confirm con session_id.
export default function TenenciaUpload({ onClose, onConfirmed }) {
  const [brokers, setBrokers] = useState([])
  const [broker, setBroker] = useState('')
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [preview, setPreview] = useState(null)   // { session_id, to_seed[], matched, ... }
  const [done, setDone] = useState(false)

  useEffect(() => {
    api.get('/brokers').then(bs => {
      const list = (bs || []).filter(b => !/·\s*USD/i.test(b.name))   // sin los siblings
      setBrokers(list)
      const bm = list.find(b => /bull/i.test(b.name))
      setBroker(bm ? bm.name : (list[0]?.name || ''))
    }).catch(() => {})
  }, [])

  async function doPreview() {
    if (!file || !broker) return
    setBusy(true); setError(null); setPreview(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('broker', broker)
      setPreview(await api.upload('/imports/tenencia/preview', fd))
    } catch (e) { setError(e?.message || 'No pudimos leer la Tenencia.') }
    finally { setBusy(false) }
  }

  async function doConfirm() {
    if (!preview?.session_id) return
    setBusy(true); setError(null)
    try {
      await api.post('/imports/confirm', { session_id: preview.session_id, skip_row_indices: [] })
      setDone(true)
      onConfirmed && onConfirmed()
    } catch (e) { setError(e?.message || 'No pudimos aplicar la Tenencia.') }
    finally { setBusy(false) }
  }

  const fmt = n => (n ?? 0).toLocaleString('es-AR', { maximumFractionDigits: 2 })
  const seeded = preview?.to_seed || []
  const seedValue = seeded.reduce((s, h) => s + (h.value || 0), 0)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="w-full max-w-lg max-h-[88vh] overflow-y-auto rounded-xl bg-rendi-card border border-white/10 p-6"
           onClick={e => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-1">
          <h2 className="text-lg font-semibold text-ink-1">Completá tu cartera con la Tenencia</h2>
          <button onClick={onClose} className="text-ink-3 hover:text-ink-1 text-xl leading-none">×</button>
        </div>
        <p className="text-sm text-ink-3 mb-4">
          La Cuenta Corriente no trae las posiciones que ya tenías antes. Subí la
          <strong className="text-ink-2"> Tenencia valorizada</strong> (PDF) y completamos lo que falta —
          sin tocar lo que ya está.
        </p>

        {done ? (
          <div className="text-center py-6">
            <div className="text-2xl mb-2">✅</div>
            <p className="text-ink-1 font-medium">¡Listo! Tu cartera quedó completa.</p>
            <button onClick={onClose} className="mt-4 px-4 py-2 text-sm bg-rendi-accent hover:bg-rendi-accent/90 text-white rounded-md font-semibold">
              Cerrar
            </button>
          </div>
        ) : !preview ? (
          <>
            <label className="block text-xs text-ink-3 mb-1">Broker</label>
            <select value={broker} onChange={e => setBroker(e.target.value)}
                    className="w-full mb-3 bg-rendi-bg border border-white/10 rounded-md px-3 py-2 text-sm text-ink-1">
              {brokers.map(b => <option key={b.name} value={b.name}>{b.name}</option>)}
            </select>

            <label className="block text-xs text-ink-3 mb-1">Tenencia valorizada (PDF)</label>
            <input type="file" accept="application/pdf,.pdf"
                   onChange={e => setFile(e.target.files?.[0] || null)}
                   className="w-full mb-1 text-sm text-ink-2 file:mr-3 file:py-2 file:px-3 file:rounded-md file:border-0 file:bg-white/10 file:text-ink-1 file:text-sm" />
            <p className="text-xs text-ink-3 mb-4">
              Bull Market WEB → Mi Cuenta → Otras consultas → Tenencia Valorizada a una Fecha → Acceder.
              No tiene botón de descarga: guardá la página como PDF con Ctrl+P (Windows) o ⌘+P (Mac) → “Guardar como PDF”.
            </p>

            {error && <p className="text-sm text-rendi-warn mb-3">{error}</p>}
            <div className="flex justify-end gap-2">
              <button onClick={onClose} className="px-4 py-2 text-sm text-ink-2 hover:text-ink-1">Cancelar</button>
              <button onClick={doPreview} disabled={!file || !broker || busy}
                      className="px-4 py-2 text-sm bg-rendi-accent hover:bg-rendi-accent/90 disabled:opacity-50 text-white rounded-md font-semibold">
                {busy ? 'Analizando…' : 'Analizar'}
              </button>
            </div>
          </>
        ) : preview.nothing_to_do ? (
          <div className="text-center py-6">
            <p className="text-ink-1">{preview.message || 'Tu cartera ya coincide con la Tenencia.'}</p>
            <button onClick={onClose} className="mt-4 px-4 py-2 text-sm bg-rendi-accent text-white rounded-md font-semibold">Cerrar</button>
          </div>
        ) : (
          <>
            <div className="rounded-md bg-rendi-bg border border-white/10 p-3 mb-3 text-sm">
              <p className="text-ink-2">
                Ya tenés <strong className="text-ink-1">{preview.matched}</strong> posiciones cargadas (no las tocamos)
                y vamos a <strong className="text-rendi-accent">completar {seeded.length}</strong> que faltaban
                {seedValue > 0 && <> (≈ {fmt(seedValue)} {seeded[0]?.currency || 'ARS'})</>}.
              </p>
            </div>
            <div className="max-h-56 overflow-y-auto border border-white/10 rounded-md mb-3">
              <table className="w-full text-sm">
                <thead className="text-xs text-ink-3 sticky top-0 bg-rendi-card">
                  <tr><th className="text-left px-3 py-1.5">Activo</th><th className="text-right px-3 py-1.5">Cantidad</th><th className="text-right px-3 py-1.5">Valor</th></tr>
                </thead>
                <tbody>
                  {seeded.map(h => (
                    <tr key={h.ticker} className="border-t border-white/5">
                      <td className="px-3 py-1.5 text-ink-1">{h.ticker} <span className="text-ink-3 text-xs">{h.type}</span></td>
                      <td className="px-3 py-1.5 text-right text-ink-2 tabular">{fmt(h.qty)}</td>
                      <td className="px-3 py-1.5 text-right text-ink-2 tabular">{fmt(h.value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {(preview.not_in_snapshot?.length > 0) && (
              <p className="text-xs text-rendi-warn mb-2">
                ⚠ Tenés {preview.not_in_snapshot.length} activo(s) en Rendi que no están en la Tenencia (¿vendidos?). No los tocamos.
              </p>
            )}
            <p className="text-xs text-ink-3 mb-3">
              Las posiciones que completamos arrancan en 0% (precio de la foto), porque la Tenencia no trae el costo histórico.
            </p>
            {error && <p className="text-sm text-rendi-warn mb-3">{error}</p>}
            <div className="flex justify-end gap-2">
              <button onClick={() => setPreview(null)} className="px-4 py-2 text-sm text-ink-2 hover:text-ink-1">Volver</button>
              <button onClick={doConfirm} disabled={busy}
                      className="px-4 py-2 text-sm bg-rendi-accent hover:bg-rendi-accent/90 disabled:opacity-50 text-white rounded-md font-semibold">
                {busy ? 'Completando…' : `Completar ${seeded.length} posiciones`}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
