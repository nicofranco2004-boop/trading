// MarketBriefPrefs — el resumen del mercado por mail, una vez por día hábil.
// ═══════════════════════════════════════════════════════════════════════════
// Decisión de producto (Nico, sep 2026): UNO solo, a las 11:00 de Argentina —
// el minuto en que abre BYMA. El de cierre se descartó: "duplica el costo y no
// agrega mucho valor". Y el mismo mail para todos, sin versión recortada por
// plan.
//
// Arranca APAGADO, a diferencia del brief del asesor (que viene prendido): ese
// va a un puñado de casillas conocidas, este a toda la base, y un mail diario
// que nadie pidió es cómo se llega a la pestaña "Actualizaciones" de Gmail.
//
// Sistema visual: la generación nueva — Panel como superficie (rounded-xl),
// rótulos sans sentence-case, cero tipografía de ancho fijo. Mismo tratamiento
// que components/advisor/BriefPrefs.jsx, del que sale este componente.
// (El nombre de la clase prohibida no se escribe ni en los comentarios: el
// guard del contrato cuenta el literal y no distingue prosa de código.)
import { useEffect, useState } from 'react'
import { Sunrise } from 'lucide-react'
import Panel from '../Panel'
import { api } from '../../utils/api'
import { useToast } from '../Toast'

// ─── El ejemplo ──────────────────────────────────────────────────────────────
// Es FIJO y el mismo para todos, a propósito. Antes este botón generaba el
// resumen real de hoy contra la cartera de la persona, y eso estaba mal por
// tres motivos (decisión de Nico, sep 2026):
//   1. El mail de hoy ya lo va a ver en su casilla; mostrarlo acá es repetirlo.
//   2. Ocupaba media pantalla — el resumen real son cuatro párrafos densos.
//   3. Gastaba una llamada al modelo por cada click, para enseñar un formato
//      que no cambia.
// Lo que la persona necesita antes de prender el interruptor es entender QUÉ
// le va a llegar. Para eso alcanza un ejemplo, y conviene que sea corto.
//
// Está escrito a mano sobre resúmenes reales, pero con datos inventados y
// dichos: lo que se muestra acá nunca puede confundirse con el mercado de hoy.
const EJEMPLO = {
  titular: 'El petróleo sube y presiona a las tasas',
  mercado: [
    'El crudo subió 4% por tensiones en Medio Oriente. Cuando la energía se ' +
    'encarece, presiona la inflación de todo el mundo. Por eso el mercado ' +
    'espera que los bancos centrales tarden más en bajar las tasas.',
    'En Argentina, el riesgo país cerró en 490 puntos. Es lo que el mercado ' +
    'cobra de más por prestarle al país, y subió por la caída de los bonos.',
  ],
  tu_cartera: [
    'YPFD y PAMP acompañan la suba del petróleo. GGAL cae con los bonos, ' +
    'como suele pasar con los bancos cuando sube el riesgo país.',
  ],
  events: [
    { ticker: 'AAPL', label: 'Reporte trimestral' },
    { ticker: 'AL30', label: 'Cupón + amortización' },
  ],
}

export default function MarketBriefPrefs() {
  const toast = useToast()
  const [prefs, setPrefs] = useState(null)        // {enabled} | null mientras carga
  const [verEjemplo, setVerEjemplo] = useState(false)
  const [loadError, setLoadError] = useState(false)

  function load() {
    return api.get('/market-brief/prefs')
      .then(d => { setPrefs(d); setLoadError(false) })
      // Sin dato NO inventamos el estado: creería que apagó algo que sigue
      // mandando, o al revés. Se avisa y se ofrece reintentar.
      .catch(() => setLoadError(true))
  }

  useEffect(() => { load() }, [])

  async function toggle() {
    const next = !prefs.enabled
    setPrefs({ enabled: next })                    // optimista
    try {
      await api.patch('/market-brief/prefs', { enabled: next })
      toast.push(next
        ? 'Listo — te llega mañana cuando abra el mercado'
        : 'Resumen apagado')
    } catch {
      setPrefs({ enabled: !next })                 // revertir
      toast.push('No se pudo guardar', { type: 'error' })
    }
  }

  const on = !!(prefs && prefs.enabled)

  return (
    <Panel padding="none">
      <header className="px-4 py-3 border-b border-line">
        <h2 className="text-sm font-medium text-ink-0">Resumen del mercado</h2>
        <p className="text-xs text-ink-3 mt-0.5">
          Un mail por día hábil, cuando abre el mercado argentino
        </p>
      </header>

      {loadError && (
        <div className="px-4 py-2.5 border-b border-line/30 text-xs text-ink-2">
          No pudimos leer tu configuración.{' '}
          <button type="button" className="text-rendi-accent hover:underline"
            onClick={() => { setLoadError(false); load() }}>
            Reintentar
          </button>
        </div>
      )}

      <div className="flex items-start gap-3 px-4 py-3.5">
        <Sunrise size={17} strokeWidth={1.75} className="text-ink-3 flex-shrink-0 mt-0.5" aria-hidden="true" />
        <div className="flex-1 min-w-0">
          <div className="text-sm text-ink-0">
            Todos los días hábiles <span className="text-ink-3 font-normal">· ~11:00</span>
          </div>
          <div className="text-xs text-ink-3 mt-0.5">
            Qué pasó en el mercado desde que cerró ayer, contado en unos párrafos:
            tasas, inflación, dólar, petróleo, y lo que toca a tus activos.
          </div>
          <button type="button" onClick={() => setVerEjemplo(v => !v)}
            aria-expanded={verEjemplo}
            className="text-[11px] text-rendi-accent hover:underline mt-1.5">
            {verEjemplo ? 'Ocultar ejemplo' : 'Ver ejemplo'}
          </button>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-label={`${on ? 'Apagar' : 'Prender'} el resumen del mercado`}
          onClick={() => prefs && toggle()}
          disabled={!prefs}
          // Blanco del tutorial de novedades (components/tour/pasos.js). Va en
          // el INTERRUPTOR y no en una fila de la lista: el tutorial resalta
          // sólo cosas que están SIEMPRE en pantalla, y esto está siempre.
          data-tour="resumen-mercado"
          className={`relative w-10 h-6 rounded-full transition-colors flex-shrink-0 ${on ? 'bg-rendi-accent' : 'bg-bg-3'}`}
        >
          <span className={`absolute top-1 w-4 h-4 rounded-full bg-white transition-all ${on ? 'left-5' : 'left-1'}`} />
        </button>
      </div>

      {verEjemplo && (
        <div className="border-t border-line/40 px-4 py-3 bg-bg-2/40 space-y-3">
          <div className="text-[11px] text-ink-3">
            Un ejemplo con datos inventados, para que veas el formato. El tuyo se
            arma con las noticias del día y tus activos.
          </div>
          <div>
            <div className="text-sm font-medium text-ink-0 leading-snug">
              {EJEMPLO.titular}
            </div>
            {EJEMPLO.mercado.map((p, k) => (
              <p key={k} className="text-xs text-ink-1 leading-relaxed mt-2">{p}</p>
            ))}
            <div className="text-[11px] tracking-label text-ink-3 mt-3">Lo tuyo</div>
            {EJEMPLO.tu_cartera.map((p, k) => (
              <p key={k} className="text-xs text-ink-1 leading-relaxed mt-1">{p}</p>
            ))}
            <div className="text-[11px] tracking-label text-ink-3 mt-3">En tu agenda de hoy</div>
            {EJEMPLO.events.map((e, k) => (
              <div key={k} className="text-xs text-ink-1 mt-0.5">
                <span className="font-medium">{e.ticker}</span>
                <span className="text-ink-2"> — {e.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Panel>
  )
}
