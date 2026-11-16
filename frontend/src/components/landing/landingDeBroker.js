// Lo que las landings de broker (pages/keywords/<Broker>.jsx) leen de la guía de
// descarga que ya usa la app adentro (BROKER_GUIDES, en BrokerInstructions.jsx).
//
// Los pasos para bajar los archivos NO se escriben en la landing: salen de esa
// guía. Antes Cocos, IOL y Binance tenían los pasos copiados a mano y, cuando la
// guía de adentro se corregía, la página que lee Google seguía con el camino
// viejo. `guiasDeBrokers.render.test.jsx` se pone rojo si una landing vuelve a
// escribir un camino del menú de su broker.
import { BROKER_GUIDES, pasosDeDescarga } from '../import/BrokerInstructions'
import { PASO_CREAR_CUENTA } from '../../data/prueba'

export function guiaDeBroker(id) {
  const guia = BROKER_GUIDES.find(g => g.id === id)
  // Mejor que se caiga la publicación a que salga una página sin pasos.
  if (!guia) throw new Error(`No hay guía de descarga para «${id}» en BROKER_GUIDES`)
  return guia
}

// La sección «Cómo descargar tus movimientos de X» de KeywordLanding.
export function descargaDe(guia, bajada) {
  return {
    titulo: `Cómo descargar tus movimientos de ${guia.label}`,
    bajada,
    pasos: pasosDeDescarga(guia),
  }
}

// «Cómo funciona»: crear la cuenta → cargar los archivos de ESTE broker (lo que
// dice la guía que hay que subir) → lo que ves después, que pone cada página.
export function comoFuncionaDe(guia, final) {
  return [
    { n: 1, ...PASO_CREAR_CUENTA },
    { n: 2, title: `Cargá tus archivos de ${guia.label} en Rendi`, desc: guia.summary },
    { n: 3, ...final },
  ]
}
