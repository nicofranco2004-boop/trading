// TourTecnico — el paseo por las pestañas de Análisis técnico (pasosTecnico.js).
// El mecanismo es Tour.jsx, el mismo del de novedades.
//
// Arranca solo una vez, la primera vez que la persona entra a la pantalla, y
// sólo DESPUÉS del de novedades: quien todavía no lo vio y entra acá ve primero
// ese (que arranca en cualquier pantalla) y éste la próxima vez que vuelva, o
// apenas cierre aquel si sigue en Análisis técnico. Nunca los dos a la vez.
// Después se abre a mano con «¿Cómo se lee esto?» (pedirTour('tecnico')).

import Tour from './Tour'
import { PASOS_TECNICO } from './pasosTecnico'
import { CATALOGO } from '../../utils/catalogoDelAlmacen'

export const ID_TOUR_TECNICO = 'tecnico'
export const dondeVaTecnico = (pathname) => pathname === '/analisis-tecnico'

// El gráfico tarda en llegar un poco más que lo que espera el de novedades:
// sus botones aparecen cuando llegan los precios. No mucho más: mientras
// espera, la pantalla queda sin cartel (y sin gráfico, sus dos pasos se
// saltean juntos: ver `grupo` en pasosTecnico.js).
const ESPERA_GRAFICO = 4000
const DESPUES_DE = [CATALOGO.vioNovedades]

export default function TourTecnico() {
  return (
    <Tour id={ID_TOUR_TECNICO} pasos={PASOS_TECNICO} entrada={CATALOGO.vioTourTecnico} etiqueta="Análisis técnico"
      cuando={dondeVaTecnico} despuesDe={DESPUES_DE} espera={ESPERA_GRAFICO} />
  )
}
