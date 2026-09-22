// PosicionesArchivadas — lo único que sobrevive de la zona "Renta Fija".
// ════════════════════════════════════════════════════════════════════════════
// La zona tenía un "borrar sección" REVERSIBLE: las posiciones de, por ejemplo,
// "Bonos USD" salían de `positions` y quedaban guardadas en `archived_positions`
// para poder restaurarlas. Ese botón de borrar se va con la zona (para deshacer
// una importación está "Revertir importación", que es lo que la gente usa).
//
// Pero el botón de RESTAURAR no puede irse: quien ya haya archivado una sección
// tiene sus posiciones guardadas y sin esta tarjeta no habría ninguna pantalla
// desde donde traerlas de vuelta — quedarían invisibles para siempre, sin que
// el usuario sepa siquiera que están. Así que el listado sigue, solo.
//
// No se restaura nada solo: archivar fue una decisión deliberada del usuario y
// revivirle posiciones que borró a propósito sería peor que dejarlas guardadas.
// Para quien nunca archivó nada (la enorme mayoría) esta tarjeta no aparece.
import { useState, useEffect } from 'react'
import { RotateCcw } from 'lucide-react'
import { api } from '../utils/api'
import { useToast } from './Toast'

export default function PosicionesArchivadas({ reloadKey = 0, onChanged }) {
  const toast = useToast()
  const [archived, setArchived] = useState([])
  const [busy, setBusy] = useState(null)

  async function loadArchived() {
    try { setArchived((await api.get('/sections/archived'))?.archived || []) }
    catch { /* si no responde, la tarjeta simplemente no aparece */ }
  }
  useEffect(() => { loadArchived() }, [reloadKey])

  async function restore(a) {
    setBusy(a.id)
    try {
      await api.post('/sections/restore', { archive_id: a.id })
      toast.push(`"${a.label}" restaurada.`, { type: 'success' })
      onChanged && onChanged()
      loadArchived()
    } catch (e) {
      toast.push('No se pudo restaurar: ' + e.message, { type: 'error' })
    } finally { setBusy(null) }
  }

  if (archived.length === 0) return null

  return (
    <div className="mt-8 text-xs text-ink-3">
      <div className="mb-1.5 kpi-label">Posiciones eliminadas</div>
      <p className="mb-2 text-ink-3 text-[11px] max-w-prose">
        Estas posiciones las sacaste de tu cartera y quedaron guardadas. No suman a tu
        patrimonio ni aparecen en ninguna tabla hasta que las restaures.
      </p>
      <div className="flex flex-col gap-1.5">
        {archived.map(a => (
          <div key={a.id} className="flex items-center justify-between gap-3 bg-bg-2/30 border border-line/60 rounded-lg px-3 py-1.5">
            <span className="text-ink-2">
              {a.label} <span className="text-ink-3">· {a.count} {a.count === 1 ? 'posición' : 'posiciones'}</span>
            </span>
            <button onClick={() => restore(a)} disabled={busy === a.id}
              className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md bg-bg-2 hover:bg-bg-3 border border-line text-ink-1 transition disabled:opacity-40">
              <RotateCcw size={11} /> Restaurar
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
