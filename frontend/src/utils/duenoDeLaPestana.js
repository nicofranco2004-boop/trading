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
//
// 🔴 EL DUEÑO DE LOS DATOS NO ES EL DE LA PESTAÑA (re-test a ciegas 2, 30/10).
// La pestaña puede cambiar de dueño con una pantalla abierta (otra pestaña
// entra como otra persona o a otro cliente), y lo que la pantalla tiene a la
// vista sigue siendo de la cuenta anterior. Lo que se guarda a partir de esos
// datos va a nombre de SU dueño — `useDuenoDeLosDatos`, el de cuando la
// pantalla se montó y pidió sus datos — y la única puerta al almacenamiento
// (utils/almacen.guardarDe) no lo guarda si ya no es el de la pestaña.

import { useEffect, useState } from 'react'
import { getClientContext, EVENTO_CUENTA_CAMBIADA } from './api'
import { isDemoMode } from './demo'
import { quienEs } from './quienEs'
import { leer, registrarReglaDeDueno } from './almacen'
import { CATALOGO } from './catalogoDelAlmacen'

export function duenoDeLaPestana() {
  if (isDemoMode()) return 'demo'
  let u = null
  try { u = JSON.parse(leer(CATALOGO.usuario) || 'null') } catch { /* basura o sin almacenamiento → nadie */ }
  const quien = quienEs(u)
  if (!quien) return null
  const cliente = getClientContext()?.id
  return `${quien}|${cliente != null ? `cliente-${cliente}` : 'propia'}`
}

/** El dueño, para una pantalla: cambia cuando el asesor cambia de cliente en
 *  esta pestaña o cuando otra pestaña cambia la sesión. (Si otra pestaña entra
 *  a otro cliente, ésta no cambia: cada una tiene el suyo, ver utils/api.) */
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

/** Lo mismo, pero de la cuenta PROPIA de la persona aunque tenga un cliente
 *  abierto: lo que el asesor hace a su nivel (sus tandas de importación, que
 *  llevan varios clientes) es suyo, no del cliente que tenga abierto. */
export function duenoPropioDeLaPestana() {
  const d = duenoDeLaPestana()
  return d && d !== 'demo' ? d.replace(/\|[^|]*$/, '|propia') : d
}

/** El dueño de los DATOS de una pantalla: el de la pestaña cuando se montó (y
 *  pidió sus datos). No cambia mientras la pantalla esté montada: si la pestaña
 *  pasa a otra persona o a otro cliente, lo que hay a la vista sigue siendo del
 *  anterior, y lo que se guarde con este dueño la puerta ya no lo guarda.
 *  `propio`: el de la persona en su cuenta propia (duenoPropioDeLaPestana). */
export function useDuenoDeLosDatos({ propio = false } = {}) {
  const [dueno] = useState(() => (propio ? duenoPropioDeLaPestana() : duenoDeLaPestana()))
  return dueno
}

/** ¿Lo que salió de los datos de `dueno` se puede guardar o mandar todavía?
 *  Sólo si sigue siendo el dueño de la pestaña (`propio`: de la persona). */
export const sigueSiendoDe = (dueno, { propio = false } = {}) =>
  !!dueno && dueno === (propio ? duenoPropioDeLaPestana() : duenoDeLaPestana())

// La puerta (utils/almacen) frena con esta regla: no se importa desde allá para
// no armar un círculo de importaciones (ver el comentario de la puerta).
registrarReglaDeDueno(sigueSiendoDe)
