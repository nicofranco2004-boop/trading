// BriefPrefs — el brief del libro del asesor, 2x/día, atado al mercado argentino.
// ═══════════════════════════════════════════════════════════════════════════
// Decisión de producto: un solo resumen a la mañana temprano mostraría lo de
// AYER (que el asesor ya vio). Por eso son dos: uno cuando ABRE la rueda (el
// plan del día) y otro cuando CIERRA (el resultado). Acá el asesor prende o
// apaga cada uno y puede espiar cómo se ve antes de que llegue.
import { useEffect, useState } from 'react'
import { Sunrise, Sunset } from 'lucide-react'
import Panel from '../Panel'
import { api } from '../../utils/api'
import { useToast } from '../Toast'

const ROWS = [
  { key: 'brief_open', icon: Sunrise, title: 'Cuando abre el mercado',
    when: '~11:00', desc: 'El plan del día: a quién llamar, quién tiene plata parada, qué eventos hay hoy.' },
  { key: 'brief_close', icon: Sunset, title: 'Cuando cierra el mercado',
    when: '~17:15', desc: 'El resultado del día: cuánto se movió tu libro, quién subió y quién bajó.' },
]

export default function BriefPrefs() {
  const toast = useToast()
  const [prefs, setPrefs] = useState(null)
  const [preview, setPreview] = useState(null)   // {kind, data} | 'loading'

  useEffect(() => {
    api.get('/advisor/brief/prefs')
      .then(setPrefs)
      .catch(() => setPrefs({ brief_open: true, brief_close: true }))
  }, [])

  async function toggle(key) {
    const next = { ...prefs, [key]: !prefs[key] }
    setPrefs(next)                                   // optimista
    try {
      await api.patch('/advisor/brief/prefs', { [key]: next[key] })
    } catch {
      setPrefs(prefs)                                // revertir
      toast.push('No se pudo guardar', { type: 'error' })
    }
  }

  async function showPreview(kind) {
    setPreview('loading')
    try {
      const r = await api.get(`/advisor/brief/preview?kind=${kind}`)
      setPreview({ kind, data: r.brief })
    } catch {
      setPreview(null)
      toast.push('No se pudo cargar la vista previa', { type: 'error' })
    }
  }

  return (
    <Panel padding="none">
      <header className="px-4 py-3 border-b border-line">
        <h2 className="text-sm font-medium text-ink-0">Brief de tu libro</h2>
        <p className="text-xs text-ink-3 mt-0.5">Dos mails por día hábil, en los horarios del mercado argentino</p>
      </header>

      {ROWS.map((r, i) => {
        const Icon = r.icon
        const on = prefs ? prefs[r.key] : true
        return (
          <div key={r.key} className={`flex items-start gap-3 px-4 py-3.5 ${i > 0 ? 'border-t border-line/30' : ''}`}>
            <Icon size={17} strokeWidth={1.75} className="text-ink-3 flex-shrink-0 mt-0.5" aria-hidden="true" />
            <div className="flex-1 min-w-0">
              <div className="text-sm text-ink-0">{r.title} <span className="text-ink-3 font-normal">· {r.when}</span></div>
              <div className="text-xs text-ink-3 mt-0.5">{r.desc}</div>
              <button type="button" onClick={() => showPreview(r.key === 'brief_open' ? 'open' : 'close')}
                className="text-[11px] text-rendi-accent hover:underline mt-1.5">
                Ver cómo se ve
              </button>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={on}
              aria-label={`${on ? 'Apagar' : 'Prender'} ${r.title}`}
              onClick={() => prefs && toggle(r.key)}
              disabled={!prefs}
              className={`relative w-10 h-6 rounded-full transition-colors flex-shrink-0 ${on ? 'bg-rendi-accent' : 'bg-bg-3'}`}
            >
              <span className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-all ${on ? 'left-5' : 'left-1'}`} />
            </button>
          </div>
        )
      })}

      {preview && (
        <div className="border-t border-line/40 px-4 py-3 bg-bg-2/40">
          {preview === 'loading' ? (
            <p className="text-xs text-ink-3">Armando la vista previa…</p>
          ) : !preview.data ? (
            <p className="text-xs text-ink-3">
              Todavía no hay nada para contar — cuando tengas clientes con cartera cargada, acá vas a ver el brief.
            </p>
          ) : (
            <div className="space-y-2">
              {(preview.data.sections || []).map(sec => (
                <div key={sec.title}>
                  <div className="text-[11px] uppercase tracking-wider text-ink-3">{sec.title}</div>
                  {(sec.items || []).map((it, k) => (
                    <div key={k} className="text-xs text-ink-1 mt-0.5">
                      <span className="font-medium">{it.label}</span>
                      {it.detail ? <span className="text-ink-2"> — {it.detail}</span> : null}
                    </div>
                  ))}
                </div>
              ))}
              <button type="button" onClick={() => setPreview(null)}
                className="text-[11px] text-ink-3 hover:text-ink-1 pt-1">Cerrar</button>
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}
