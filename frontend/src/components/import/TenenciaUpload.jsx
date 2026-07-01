import { useEffect, useState } from 'react'
import { api } from '../../utils/api'

// Completar la cartera con la "Tenencia valorizada" (PDF) de Bull Market — la
// foto de posiciones. Reconcilia contra lo ya importado de la Cuenta Corriente:
// completa SOLO lo que falta (comprado antes de la ventana de la CC), sin
// duplicar. Backend: POST /imports/tenencia/preview → confirm con session_id.
export default function TenenciaUpload({
  onClose, onConfirmed,
  title = 'Completá tu cartera con la Tenencia',
  introText = null,
  brokerMatch = /bull/i,
  accept = 'application/pdf,.pdf',
  fileLabel = 'Tenencia valorizada (PDF)',
  fileHint = 'Bull Market WEB → Mi Cuenta → Otras consultas → Tenencia Valorizada a una Fecha → Acceder. No tiene botón de descarga: guardá la página como PDF con Ctrl+P (Windows) o Cmd+P (Mac) → “Guardar como PDF”.',
  format = null,
  docLabel = 'la Tenencia',   // para la copia: "leer {docLabel}", "no están en {docLabel}", etc.
}) {
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
      const bm = list.find(b => brokerMatch.test(b.name))
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
      if (format) fd.append('format', format)
      setPreview(await api.upload('/imports/tenencia/preview', fd))
    } catch (e) { setError(e?.message || `No pudimos leer ${docLabel}.`) }
    finally { setBusy(false) }
  }

  async function doConfirm() {
    if (!preview?.session_id) return
    setBusy(true); setError(null)
    try {
      await api.post('/imports/confirm', { session_id: preview.session_id, skip_row_indices: [] })
      setDone(true)
      onConfirmed && onConfirmed()
    } catch (e) { setError(e?.message || `No pudimos aplicar ${docLabel}.`) }
    finally { setBusy(false) }
  }

  const fmt = n => (n ?? 0).toLocaleString('es-AR', { maximumFractionDigits: 2 })
  const seeded = preview?.to_seed || []
  // Total POR MONEDA (no sumamos ARS + USD en un solo número): la foto de PPI
  // puede traer holdings en pesos y en dólares.
  const seedByCcy = seeded.reduce((m, h) => {
    const c = h.currency || 'ARS'; m[c] = (m[c] || 0) + (h.value || 0); return m
  }, {})
  const seedValueLabel = Object.entries(seedByCcy)
    .filter(([, v]) => v > 0).map(([c, v]) => `${fmt(v)} ${c}`).join(' · ')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="w-full max-w-lg max-h-[88vh] overflow-y-auto rounded-xl bg-rendi-card border border-white/10 p-6"
           onClick={e => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-1">
          <h2 className="text-lg font-semibold text-ink-1">{title}</h2>
          <button onClick={onClose} className="text-ink-3 hover:text-ink-1 text-xl leading-none">×</button>
        </div>
        <p className="text-sm text-ink-3 mb-4">
          {introText || (<>La Cuenta Corriente no trae las posiciones que ya tenías antes. Subí la
          <strong className="text-ink-2"> Tenencia valorizada</strong> (PDF) y completamos lo que falta —
          sin tocar lo que ya está.</>)}
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

            <label className="block text-xs text-ink-3 mb-1">{fileLabel}</label>
            <input type="file" accept={accept}
                   onChange={e => setFile(e.target.files?.[0] || null)}
                   className="w-full mb-1 text-sm text-ink-2 file:mr-3 file:py-2 file:px-3 file:rounded-md file:border-0 file:bg-white/10 file:text-ink-1 file:text-sm" />
            {Array.isArray(fileHint) ? (
              <ol className="text-xs text-ink-3 mb-4 list-decimal pl-4 space-y-0.5">
                {fileHint.map((s, i) => <li key={i}>{s}</li>)}
              </ol>
            ) : (
              <p className="text-xs text-ink-3 mb-4">{fileHint}</p>
            )}

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
            <p className="text-ink-1">{preview.message || `Tu cartera ya coincide con ${docLabel}.`}</p>
            <button onClick={onClose} className="mt-4 px-4 py-2 text-sm bg-rendi-accent text-white rounded-md font-semibold">Cerrar</button>
          </div>
        ) : (
          <>
            <div className="rounded-md bg-rendi-bg border border-white/10 p-3 mb-3 text-sm">
              <p className="text-ink-2">
                Ya tenés <strong className="text-ink-1">{preview.matched}</strong> posiciones cargadas (no las tocamos)
                y vamos a <strong className="text-rendi-accent">completar {seeded.length}</strong> que faltaban
                {seedValueLabel && <> (≈ {seedValueLabel})</>}.
              </p>
            </div>
            <div className="max-h-56 overflow-y-auto border border-white/10 rounded-md mb-3">
              <table className="w-full text-sm">
                <thead className="text-xs text-ink-3 sticky top-0 bg-rendi-card">
                  <tr><th className="text-left px-3 py-1.5">Activo</th><th className="text-right px-3 py-1.5">Cantidad</th><th className="text-right px-3 py-1.5">Valor</th></tr>
                </thead>
                <tbody>
                  {seeded.map(h => (
                    <tr key={`${h.ticker}-${h.currency || ''}`} className="border-t border-white/5">
                      <td className="px-3 py-1.5 text-ink-1">{h.ticker} <span className="text-ink-3 text-xs">{h.type}{h.currency === 'USD' ? ' · USD' : ''}</span></td>
                      <td className="px-3 py-1.5 text-right text-ink-2 tabular">{fmt(h.qty)}</td>
                      <td className="px-3 py-1.5 text-right text-ink-2 tabular">{fmt(h.value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {/* Foto en modo OVERRIDE (Balanz / IEB): la foto PISA — ajusta lo que
                quedó de más/de menos (cierra a costo, sin P&L). Lo mostramos. */}
            {preview.override && (preview.override.reduced?.length > 0 || preview.override.removed?.length > 0) && (
              <div className="rounded-md border border-white/10 bg-rendi-bg p-2.5 mb-2 text-xs text-ink-2">
                <p className="mb-1">La foto ajusta tu cartera (se cierra a costo, sin ganancia/pérdida):</p>
                <ul className="list-disc pl-4 space-y-0.5">
                  {(preview.override.reduced || []).map(r => (
                    <li key={`red-${r.ticker}`}>{r.ticker}: bajamos de {fmt(r.rendi)} a {fmt(r.tenencia)}</li>
                  ))}
                  {(preview.override.removed || []).map(r => (
                    <li key={`rm-${r.ticker}`}>{r.ticker}: lo sacamos ({fmt(r.qty)}) — no está en {docLabel}</li>
                  ))}
                </ul>
              </div>
            )}
            {preview.override?.capped && (
              <p className="text-xs text-rendi-warn mb-2">
                ⚠ El ajuste tocaría más de la mitad de tu cartera → lo frenamos por seguridad: sólo completamos lo que falta. Revisá el archivo o escribinos.
              </p>
            )}
            {(preview.warnings?.length > 0) && (
              <div className="rounded-md border border-rendi-warn/40 bg-rendi-warn/10 p-2.5 mb-2 text-xs text-rendi-warn">
                <p className="font-medium mb-1">Leímos {docLabel} pero puede estar incompleto:</p>
                <ul className="list-disc pl-4 space-y-0.5">
                  {preview.warnings.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
                <p className="mt-1 text-ink-3">Por eso no sacamos posiciones por ‘ausencia’ esta vez.</p>
              </div>
            )}
            {(preview.not_in_snapshot?.length > 0) && (
              <p className="text-xs text-rendi-warn mb-2">
                ⚠ Tenés {preview.not_in_snapshot.length} activo(s) en Rendi que no están en {docLabel} (¿vendidos?). {(preview.override?.removed?.length > 0) ? 'Los que correspondía los sacamos (ver arriba).' : 'No los tocamos.'}
              </p>
            )}
            <p className="text-xs text-ink-3 mb-3">
              Las posiciones que completamos arrancan al costo de {docLabel} (PPP si lo trae).
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
