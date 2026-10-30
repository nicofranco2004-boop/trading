// CuentaCambiadaEnOtraPestana — el cartel de la pestaña que quedó mostrando
// una cuenta mientras en otra se abrió otra (otro cliente, u otra persona).
// ═══════════════════════════════════════════════════════════════════════════
// Desde ese instante utils/api no deja salir ningún pedido de esta pestaña
// (`pestanaDesfasada`): lo que se tocara acá se guardaba en una cuenta que no
// se estaba viendo (re-test a ciegas 3, 30/10). El cartel lo dice y deja
// elegir:
//   · «Seguir con <la que se ve> en esta pestaña»: vuelve a abrir esa cuenta.
//     Lo que estaba a medio cargar sigue ahí y se guarda donde se ve. Las
//     OTRAS pestañas pasan a preguntar lo mismo.
//   · «Ir a <la nueva>»: recarga la página. Recargar (y no volver a dibujar las
//     pantallas) porque hay datos de la cuenta anterior guardados en memoria
//     fuera de las pantallas; la recarga los tira todos. Lo que estaba a medio
//     cargar se pierde: era de la otra cuenta.
// Si cambió la PERSONA no hay a qué volver (la sesión ya es de la otra):
// AuthContext recarga solo en un instante, y el cartel sólo lo avisa.
import { useEffect, useRef, useState } from 'react'
import { ArrowLeftRight } from 'lucide-react'
import { EVENTO_PESTANA_DESFASADA, pestanaDesfasada, seguirConLaCuentaMostrada } from '../utils/api'

const nombreDe = (ctx) => (ctx ? (ctx.label || `el cliente ${ctx.id}`) : 'tu cuenta')

export default function CuentaCambiadaEnOtraPestana() {
  const [desfase, setDesfase] = useState(() => pestanaDesfasada())
  const primero = useRef(null)
  useEffect(() => {
    const mirar = () => setDesfase(pestanaDesfasada())
    window.addEventListener(EVENTO_PESTANA_DESFASADA, mirar)
    mirar()
    return () => window.removeEventListener(EVENTO_PESTANA_DESFASADA, mirar)
  }, [])
  useEffect(() => { if (desfase) primero.current?.focus?.() }, [desfase])

  if (!desfase) return null
  const persona = desfase.motivo === 'persona'
  const visto = nombreDe(desfase.mostrado)
  const abierto = nombreDe(desfase.abierto)

  // Arriba de TODO (300): el recorrido de Novedades va en 100, las
  // confirmaciones en 150 y los menús en 200. Con el cartel en 100, el
  // recorrido —dibujado después— lo tapaba con su máscara.
  return (
    <div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div role="alertdialog" aria-modal="true" aria-labelledby="cuenta-cambiada-titulo"
        className="w-full max-w-md bg-bg-1 border border-line rounded-xl p-5 shadow-xl">
        <div className="flex items-start gap-3">
          <ArrowLeftRight size={18} className="text-rendi-warn shrink-0 mt-0.5" />
          <div className="space-y-2">
            <h2 id="cuenta-cambiada-titulo" className="text-base font-semibold text-ink-0">
              Cambiaste de cuenta en otra pestaña
            </h2>
            {persona ? (
              <p className="text-sm text-ink-2">
                En otra pestaña entró otra persona. Esta se recarga sola con esa sesión, y no
                guardó nada de lo que había acá.
              </p>
            ) : (
              <>
                <p className="text-sm text-ink-2">
                  Esta pestaña muestra <span className="font-medium text-ink-0">{visto}</span>,
                  pero en otra abriste <span className="font-medium text-ink-0">{abierto}</span>.
                  Para que nada se guarde en la cuenta equivocada, esta pestaña no manda nada
                  hasta que elijas.
                </p>
                <p className="text-xs text-ink-3">
                  Si seguís con {visto}, lo que estabas cargando acá sigue como estaba y las otras
                  pestañas te van a preguntar lo mismo. Si vas a {abierto}, la página se recarga.
                </p>
              </>
            )}
          </div>
        </div>
        {!persona && (
          <div className="flex flex-col sm:flex-row sm:justify-end gap-2 mt-4">
            <button ref={primero} onClick={() => seguirConLaCuentaMostrada()}
              className="px-4 py-2 text-sm bg-rendi-accent hover:bg-rendi-accent/90 text-white rounded font-semibold transition">
              Seguir con {visto} en esta pestaña
            </button>
            <button onClick={() => window.location.reload()}
              className="px-4 py-2 text-sm bg-bg-2 hover:bg-bg-3 border border-line text-ink-1 rounded transition">
              Ir a {abierto}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
