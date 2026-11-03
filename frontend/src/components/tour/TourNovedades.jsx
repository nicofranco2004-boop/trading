// TourNovedades — el paseo que presenta la voz, el micrófono, la isla, Alertas
// y el tema. El mecanismo es Tour.jsx (el mismo del de Análisis técnico); acá
// van sólo sus pasos (pasos.js), dónde se guarda que ya lo vio y dónde no va.
//
// ⚠️ SUBIR LA VERSIÓN DE `vioNovedades` (utils/catalogoDelAlmacen.js) ES LA
// ÚNICA FORMA DE QUE UNA NOVEDAD LLEGUE A QUIEN YA VIO EL TUTORIAL. El
// almacenamiento guarda un sí/no, no qué pasos vio, así que con la clave vieja
// un paso nuevo sólo lo verían los usuarios nuevos — o sea, exactamente los que
// no lo necesitan. El costo es que todos vuelven a ver el tutorial entero una
// vez. Se sube SÓLO cuando se agrega algo que vale ese costo; v2 = el modo claro.

import Tour from './Tour'
import { PASOS } from './pasos'
import { CATALOGO } from '../../utils/catalogoDelAlmacen'

// Nunca en las pantallas que piden la pantalla entera (login, alta de cuenta,
// la primera lectura).
const PANTALLA_ENTERA = /^\/(login|registro|onboarding|bienvenida|claim|verify-email|reset-password)/
export const dondeVaNovedades = (pathname) => !PANTALLA_ENTERA.test(pathname)

export default function TourNovedades() {
  return (
    <Tour id="novedades" pasos={PASOS} entrada={CATALOGO.vioNovedades} etiqueta="Novedades"
      cuando={dondeVaNovedades} />
  )
}
