// RecorridoModulos — «Todo lo que hace Rendi»: pestañas que pasan solas.
// ════════════════════════════════════════════════════════════════════════════
// Pedido de Nico (03/11): cuando la persona LLEGA a esta parte, arranca en
// «Tu cartera» y pasa a la siguiente cada 4 segundos, en ronda. Si toca una
// pestaña, se queda ahí y no pasa más: eligió dónde quiere estar.
//
// Las seis pantallas están siempre en el HTML (escondidas las que no se ven):
// así el HTML ya escrito que leen Google y las IA trae lo que hace cada módulo,
// no sólo el primero. La que se muestra se monta de nuevo cada vez que le toca
// (key con la vuelta), para que sus barras y líneas vuelvan a dibujarse.

import { useEffect, useRef, useState } from 'react'
import { Wallet, Compass, CandlestickChart, Gauge, MessageSquare, BarChart3 } from 'lucide-react'
import { useAlVerse } from '../../hooks/useAlVerse'
import { prefiereSinMovimiento } from '../../utils/movimiento'
import { PANTALLAS } from './PantallasModulos'

/** Cuánto se queda cada pestaña cuando pasan solas. */
export const DURACION_PESTANA_MS = 4000

const MODULOS = [
  { id: 'cartera', Icon: Wallet, titulo: 'Tu cartera', desc: 'Todos tus brokers juntos y tu ganancia real en dólares.', miga: ['Tu cartera', 'Dashboard'] },
  { id: 'salud', Icon: Compass, titulo: 'Salud de cartera', desc: 'Qué riesgo corrés y si tu cartera es la de tu perfil.', miga: ['Salud de cartera', 'Métricas'] },
  { id: 'tecnico', Icon: CandlestickChart, titulo: 'Análisis técnico', desc: 'Gráfico, señales de la semana y alertas.', miga: ['Análisis de mercado', 'Análisis técnico'] },
  { id: 'fundamental', Icon: Gauge, titulo: 'Análisis fundamental', desc: 'Balances y comparación entre empresas.', miga: ['Análisis de mercado', 'Análisis fundamental'] },
  { id: 'ia', Icon: MessageSquare, titulo: 'Mervall-E AI', desc: 'Le preguntás y te contesta con tus datos.', miga: ['Mervall-E AI'] },
  { id: 'reportes', Icon: BarChart3, titulo: 'Reportes', desc: 'Tu mes contra el S&P 500, el Merval y la inflación.', miga: ['Salud de cartera', 'Reportes'] },
]

export default function RecorridoModulos() {
  const [actual, setActual] = useState(0)
  const [vuelta, setVuelta] = useState(0)
  const [andando, setAndando] = useState(false)
  const [elegida, setElegida] = useState(false)
  const [alVerse, visto] = useAlVerse({ threshold: 0.4, rootMargin: '0px' })
  const fila = useRef(null)

  const mostrar = (i) => { setActual(i); setVuelta(v => v + 1) }

  // Arranca recién al llegar, y siempre desde «Tu cartera».
  useEffect(() => {
    if (!visto || elegida || prefiereSinMovimiento()) return
    mostrar(0)
    setAndando(true)
  }, [visto]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!andando) return undefined
    const t = setTimeout(() => mostrar((actual + 1) % MODULOS.length), DURACION_PESTANA_MS)
    return () => clearTimeout(t)
  }, [andando, actual, vuelta])

  // En el celular las pestañas son una fila que se desliza: se corre sólo la
  // fila (nunca la página) para que la activa quede a la vista.
  useEffect(() => {
    const c = fila.current, b = c?.children[actual]
    if (!c || !b || c.scrollWidth <= c.clientWidth) return
    c.scrollTo({ left: b.offsetLeft - (c.clientWidth - b.offsetWidth) / 2, behavior: 'smooth' })
  }, [actual])

  const elegir = (i) => { setElegida(true); setAndando(false); mostrar(i) }

  return (
    <div ref={alVerse} className="grid grid-cols-1 lg:grid-cols-[290px_minmax(0,1fr)] gap-5 items-start"
         style={{ '--lp-dur': `${DURACION_PESTANA_MS}ms` }}>
      <div ref={fila} role="tablist" aria-label="Módulos de Rendi"
           className="flex lg:flex-col gap-1.5 overflow-x-auto lg:overflow-visible lp-sin-barra pb-0.5">
        {MODULOS.map((m, i) => {
          const activa = i === actual
          return (
            <button key={m.id} type="button" role="tab" id={`modulo-${m.id}`} aria-selected={activa}
                    aria-controls={`pantalla-${m.id}`} onClick={() => elegir(i)}
                    className={`relative shrink-0 grid lg:grid-cols-[34px_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-left rounded-xl border px-3.5 py-2.5 lg:py-3 overflow-hidden transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-data-violet ${
                      activa ? 'bg-bg-1 border-line-2' : 'border-line lg:border-transparent hover:bg-bg-1/70'}`}>
              <span className={`hidden lg:grid row-span-2 w-[34px] h-[34px] rounded-lg place-items-center border ${
                activa ? 'text-data-violet border-data-violet/35 bg-rendi-violet-deep' : 'text-ink-2 border-line bg-bg-2'}`}>
                <m.Icon size={17} strokeWidth={1.8} />
              </span>
              <b className={`font-semibold text-sm lg:text-[15px] whitespace-nowrap ${activa ? 'text-ink-0' : 'text-ink-1'}`}>{m.titulo}</b>
              <small className={`hidden lg:block text-[13px] leading-snug ${activa ? 'text-ink-2' : 'text-ink-3'}`}>{m.desc}</small>
              {activa && andando && (
                <span key={vuelta} aria-hidden="true" className="absolute left-3.5 right-3.5 bottom-0 h-0.5 bg-data-violet lp-llena" />
              )}
            </button>
          )
        })}
      </div>

      <div className="border border-line-2 rounded-xl bg-bg-1 overflow-hidden lp-sombra-ventana min-w-0">
        <div className="flex items-center gap-2.5 px-4 py-2.5 border-b border-line bg-bg-2/60 text-[13px] text-ink-2">
          <span className="flex gap-1.5" aria-hidden="true">{[0, 1, 2].map(i => <i key={i} className="w-2 h-2 rounded-full bg-line-3" />)}</span>
          <span className="truncate">
            {MODULOS[actual].miga.map((p, k, a) => (
              <span key={p}>{k > 0 && ' › '}{k === a.length - 1 ? <b className="font-semibold text-ink-0">{p}</b> : p}</span>
            ))}
          </span>
          <span className="ml-auto text-[11.5px] border border-line-2 rounded-full px-2 py-0.5 shrink-0">Ejemplo</span>
        </div>
        {MODULOS.map((m, i) => {
          const Pantalla = PANTALLAS[m.id]
          const activa = i === actual
          return (
            <div key={activa ? `${m.id}-${vuelta}` : m.id} id={`pantalla-${m.id}`} role="tabpanel"
                 aria-labelledby={`modulo-${m.id}`} hidden={!activa}
                 className="p-3.5 sm:p-5 sm:min-h-[420px] lp-entra">
              <Pantalla activa={activa} />
            </div>
          )
        })}
      </div>
    </div>
  )
}
