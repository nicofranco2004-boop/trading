// CuentaCambiadaEnOtraPestana — el cartel de la pestaña cuya SESIÓN cambió en
// otra: entró otra persona, o se entró o se salió del modo demo.
// ═══════════════════════════════════════════════════════════════════════════
// La sesión (una cookie) y la marca del demo son una para todo el navegador.
// Desde ese instante utils/api no deja salir ningún pedido de esta pestaña
// (`pestanaDesfasada`): lo que se tocara acá se guardaba en la cuenta de otro,
// o lo tocado en el demo en la cuenta real (re-test a ciegas 3 y 4, 30/10).
// AuthContext la recarga sola en un instante; el cartel lo avisa. No hay a
// qué volver —la sesión ya es la otra—, pero el cartel nunca queda sin salida
// (re-test a ciegas 5 y 6): «Recargar», siempre.
// El cartel NUNCA cierra una sesión que no es la de esta pestaña (re-test a
// ciegas 7 y 8: con la recarga frenada por un «¿Salir del sitio?», «Cerrar
// sesión» cerraba la de Bruno, que acababa de entrar, y borraba lo suyo). Lo
// decide el DUEÑO, no el motivo del cartel: «Cerrar sesión» aparece sólo si la
// sesión del navegador sigue siendo la de esta pestaña (utils/api,
// laSesionEsDeEstaPestana) —una pestaña de una cuenta real mientras otra entró
// al demo—. Con dos motivos a la vez (entró Bruno y después otra pestaña abrió
// el demo) el del demo tapaba al de la persona y el botón aparecía. Y aunque
// apareciera, el servidor no cierra la sesión de otra persona.
// Lo que estaba a medio cargar se pierde con la recarga.
// «Salió alguien» (motivo 'sinSesion') y «está por recargar» frenan sin cartel.
// El CLIENTE del asesor no pasa por acá: cada pestaña tiene el suyo
// (utils/api), así que dos pestañas con dos clientes trabajan a la vez.
// Se redibuja con cada aviso: si el motivo cambia, dice el de ahora.
import { useEffect, useState } from 'react'
import { ArrowLeftRight } from 'lucide-react'
import { EVENTO_PESTANA_DESFASADA, pestanaDesfasada, laSesionEsDeEstaPestana } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'

function queCambio(desfase) {
  const despues = desfase.sinSalida
    ? 'No se pudo recargar sola: recargala para seguir.'
    : 'Esta se recarga sola.'
  if (desfase.motivo === 'demo') {
    return desfase.estabaEnDemo
      ? `En otra pestaña saliste del modo demo. ${despues} Lo que tocaste acá en el demo no pasa a tu cuenta.`
      : `En otra pestaña entraste al modo demo. ${despues} La cartera de ejemplo no se mezcla con la tuya.`
  }
  return `En otra pestaña entró otra persona: la sesión de este navegador ahora es la suya, y desde acá no se puede usar ni cerrar. ${despues} Esta pestaña no guardó nada de lo que había acá.`
}

const CON_CARTEL = new Set(['persona', 'demo'])

export default function CuentaCambiadaEnOtraPestana() {
  const { logout } = useAuth() || {}
  const [desfase, setDesfase] = useState(() => pestanaDesfasada())
  useEffect(() => {
    const mirar = () => setDesfase(pestanaDesfasada())
    window.addEventListener(EVENTO_PESTANA_DESFASADA, mirar)
    mirar()
    return () => window.removeEventListener(EVENTO_PESTANA_DESFASADA, mirar)
  }, [])

  if (!desfase || !CON_CARTEL.has(desfase.motivo)) return null
  // Cerrar sesión cierra la sesión de verdad (la cookie): sólo cuando es la de
  // esta pestaña (una pestaña de una cuenta real mientras otra entró al demo).
  const puedeCerrar = laSesionEsDeEstaPestana()

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
          </div>
        </div>
        <div className="flex flex-col sm:flex-row sm:justify-end gap-2 mt-4">
          {puedeCerrar && (
            <button
              onClick={() => { try { logout?.() } finally { window.location.href = '/' } }}
              className="px-4 py-2 text-sm bg-bg-2 hover:bg-bg-3 border border-line text-ink-1 rounded transition">
              Cerrar sesión
            </button>
          )}
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 text-sm bg-rendi-accent hover:bg-rendi-accent/90 text-white rounded font-semibold transition">
            Recargar
          </button>
        </div>
      </div>
    </div>
  )
}
