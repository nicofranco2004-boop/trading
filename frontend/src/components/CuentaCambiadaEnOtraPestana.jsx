// CuentaCambiadaEnOtraPestana — el cartel de la pestaña cuya SESIÓN cambió en
// otra: entró otra persona, o se entró o se salió del modo demo.
// ═══════════════════════════════════════════════════════════════════════════
// La sesión (una cookie) y la marca del demo son una para todo el navegador.
// Desde ese instante utils/api no deja salir ningún pedido de esta pestaña
// (`pestanaDesfasada`): lo que se tocara acá se guardaba en la cuenta de otro,
// o lo tocado en el demo en la cuenta real (re-test a ciegas 3 y 4, 30/10).
// AuthContext la recarga sola en un instante; el cartel lo avisa. No hay a
// qué volver —la sesión ya es la otra—, pero SIEMPRE ofrece «Cerrar sesión»:
// si la recarga no lo arregla (tiene tope: utils/api.recargarPorPersona), es la
// salida, y sale aunque la pestaña esté frenada (re-test a ciegas 5: una
// recarga sin fin con un cartel sin botones no dejaba ni cerrar sesión). Lo
// que estaba a medio cargar se pierde con la recarga.
// El CLIENTE del asesor no pasa por acá: cada pestaña tiene el suyo
// (utils/api), así que dos pestañas con dos clientes trabajan a la vez.
// Se redibuja con cada aviso: si el motivo cambia, dice el de ahora.
import { useEffect, useState } from 'react'
import { ArrowLeftRight } from 'lucide-react'
import { EVENTO_PESTANA_DESFASADA, pestanaDesfasada } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'

function queCambio(desfase) {
  if (desfase.motivo === 'demo') {
    return desfase.estabaEnDemo
      ? 'En otra pestaña saliste del modo demo. Esta se recarga sola, y lo que tocaste acá en el demo no pasa a tu cuenta.'
      : 'En otra pestaña entraste al modo demo. Esta se recarga sola, y no mezcla la cartera de ejemplo con la tuya.'
  }
  return 'En otra pestaña entró otra persona. Esta se recarga sola con esa sesión, y no guardó nada de lo que había acá.'
}

export default function CuentaCambiadaEnOtraPestana() {
  const { logout } = useAuth() || {}
  const [desfase, setDesfase] = useState(() => pestanaDesfasada())
  useEffect(() => {
    const mirar = () => setDesfase(pestanaDesfasada())
    window.addEventListener(EVENTO_PESTANA_DESFASADA, mirar)
    mirar()
    return () => window.removeEventListener(EVENTO_PESTANA_DESFASADA, mirar)
  }, [])

  if (!desfase) return null

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
            <p className="text-sm text-ink-2">{queCambio(desfase)}</p>
            {desfase.sinSalida && (
              <p className="text-sm text-ink-2">
                No se pudo recargar con la sesión nueva. Cerrá sesión y volvé a entrar.
              </p>
            )}
          </div>
        </div>
        <div className="flex justify-end mt-4">
          <button
            onClick={() => { try { logout?.() } finally { window.location.href = '/' } }}
            className="px-4 py-2 text-sm bg-bg-2 hover:bg-bg-3 border border-line text-ink-1 rounded transition">
            Cerrar sesión
          </button>
        </div>
      </div>
    </div>
  )
}
