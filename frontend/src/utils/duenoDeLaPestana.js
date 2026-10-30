// duenoDeLaPestana — LA regla de «de quién es» lo que esta pestaña guarda en el
// navegador sobre UNA cuenta: tus dibujos del gráfico, «ya guardé la foto de
// hoy», el último total visto, la última tanda de importación del asesor.
//
// Son las dos cosas a la vez:
//   · la PERSONA logueada: la sesión que AuthContext guarda en `rendi_user`
//     (la misma que mira para saber si otra pestaña cambió de persona), con la
//     regla de utils/quienEs (el email, en minúsculas);
//   · la CUENTA abierta: la propia o el cliente del asesor, el mismo dato con
//     que api.js elige a qué cuenta va cada pedido (getClientContext).
//
// 🔴 POR QUÉ LAS DOS (auditoría de la pestaña Gráfico, 30/10). La copia de los
// dibujos era del ACTIVO: si a Ana no se le pudo guardar un dibujo y después
// Bruno abría ese activo en la misma compu, se le mostraba y se SUBÍA a la
// cuenta de Bruno; el asesor que dibujaba en un cliente se lo llevaba al
// siguiente. Otras copias separaban por cuenta pero no por persona: «Cerrar
// sesión» las borra (AuthContext.logout), pero una sesión que VENCE no —api.js
// sólo borra `rendi_user`—, y el siguiente en la pestaña las heredaba.
//
// null = nadie logueado: no se guarda ni se lee nada.

import { useEffect, useState } from 'react'
import { getClientContext, EVENTO_CUENTA_CAMBIADA } from './api'
import { isDemoMode } from './demo'
import { quienEs } from './quienEs'

export function duenoDeLaPestana() {
  if (isDemoMode()) return 'demo'
  let u = null
  try { u = JSON.parse(localStorage.getItem('rendi_user') || 'null') } catch { /* basura → nadie */ }
  const quien = quienEs(u)
  if (!quien) return null
  const cliente = getClientContext()?.id
  return `${quien}|${cliente != null ? `cliente-${cliente}` : 'propia'}`
}

/** El dueño, para una pantalla: cambia cuando el asesor cambia de cliente (en
 *  esta pestaña o en otra) o cuando otra pestaña cambia la sesión. */
export function useDuenoDeLaPestana() {
  const [dueno, setDueno] = useState(duenoDeLaPestana)
  useEffect(() => {
    const mirar = () => setDueno(duenoDeLaPestana())
    window.addEventListener(EVENTO_CUENTA_CAMBIADA, mirar)
    window.addEventListener('storage', mirar)
    return () => {
      window.removeEventListener(EVENTO_CUENTA_CAMBIADA, mirar)
      window.removeEventListener('storage', mirar)
    }
  }, [])
  return dueno
}
