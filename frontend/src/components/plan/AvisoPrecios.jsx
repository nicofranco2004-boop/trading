import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Modal from '../Modal'
import { api } from '../../utils/api'
import { useAuth } from '../../contexts/AuthContext'
import {
  PLUS_PRICE_ARS_MONTHLY, PRO_PRICE_ARS_MONTHLY, fmtArs,
} from '../../data/pricing'

// ─── Aviso único: cambiaron los precios (15/10/2026) ───────────────────────
// Se le muestra UNA vez a quien PAGA un plan. Quién califica NO se decide acá:
// lo decide el backend (`subscriptions.debe_ver_aviso_precios`) y llega en
// `user.aviso_precios`. Si la regla viviera en la pantalla habría que repetir
// la parte difícil —distinguir a quien paga de quien está en la PRUEBA, que
// tiene el mismo tier— y sería una segunda versión de la misma pregunta.
//
// ⭐ POR QUÉ SE MARCA AL MOSTRARLO Y NO AL CERRARLO. Es el bug que pidió Nico
// que no pase: "que no se le muestre varias veces". Si se marcara al cerrar,
// alcanza con cerrar la pestaña —o que falle esa llamada— para que vuelva en el
// próximo inicio de sesión. Marcándolo cuando aparece, no puede repetirse nunca;
// el precio de eso es que si alguien lo cierra en el mismo segundo no lo
// vuelve a ver, y está bien: el mail dice lo mismo y /planes también.
//
// La marca vive en la BASE, no en el navegador: con `localStorage` volvería a
// aparecer en cada dispositivo, cada navegador y cada ventana de incógnito.

export default function AvisoPrecios() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [cerrado, setCerrado] = useState(false)
  const yaMarcado = useRef(false)

  const visible = !!user?.aviso_precios && !cerrado

  useEffect(() => {
    if (!visible || yaMarcado.current) return
    yaMarcado.current = true          // una sola llamada por montaje
    // Sin `await` y sin romper nada si falla: el aviso ya está en pantalla y
    // lo que importa es que no vuelva. El endpoint es idempotente.
    api.post('/me/aviso-precios-visto', {}).catch(() => {})
  }, [visible])

  if (!visible) return null

  function verPrecios() {
    setCerrado(true)
    navigate('/config?tab=planes')
  }

  return (
    <Modal title="Cambiaron los precios de Rendi" onClose={() => setCerrado(true)}>
      <div className="space-y-4">
        <p className="text-sm text-ink-1">
          Desde hoy los planes de Rendi cuestan:
        </p>

        <div className="rounded-xl border border-line bg-bg-2/40 divide-y divide-line/60">
          <div className="flex items-baseline justify-between px-4 py-3">
            <span className="text-sm text-ink-1">Plus</span>
            <span className="text-sm text-ink-0 font-medium tabular">
              ${fmtArs(PLUS_PRICE_ARS_MONTHLY)}<span className="text-ink-3 font-normal"> / mes</span>
            </span>
          </div>
          <div className="flex items-baseline justify-between px-4 py-3">
            <span className="text-sm text-ink-1">Pro</span>
            <span className="text-sm text-ink-0 font-medium tabular">
              ${fmtArs(PRO_PRICE_ARS_MONTHLY)}<span className="text-ink-3 font-normal"> / mes</span>
            </span>
          </div>
        </div>

        <p className="text-xs text-ink-2 leading-relaxed">
          El precio nuevo rige <strong className="text-ink-1">desde tu próximo cobro</strong>.
          Lo que ya pagaste no se toca, y si preferís no seguir podés cancelar antes de esa
          fecha y usar Rendi hasta el final del período que tenés pago.
        </p>

        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={verPrecios}
            className="px-4 py-2 rounded-lg bg-data-violet text-bg-0 text-sm font-medium hover:bg-rendi-violet-hover transition-colors"
          >
            Ver nuevos precios
          </button>
          <button
            onClick={() => setCerrado(true)}
            className="px-4 py-2 rounded-lg border border-line text-ink-2 text-sm hover:bg-bg-2 transition-colors"
          >
            Entendido
          </button>
        </div>
      </div>
    </Modal>
  )
}
