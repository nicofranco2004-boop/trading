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

// PROVISORIO — lo que dicen de impuestos las landings de Balanz, Bull Market y PPI.
//
// La sesión «Auditoría profunda de SEO» corrige los textos fiscales de todas las
// páginas públicas en la rama `claude/textos-fiscales` y va a dejar las frases
// compartidas en `data/impuestos.js`. Cuando eso esté en main: importar de ahí,
// usarlo en estas tres landings y BORRAR esto (si no, quedan dos fuentes).
//
// El criterio, mientras tanto: para una persona humana residente, vender CEDEARs
// y acciones argentinas en BYMA está EXENTO de Ganancias (ley del impuesto, art.
// 26 inc. u). Nada de «FIFO para AFIP», «P&L declarable» ni «tu declaración».
export const IMPUESTOS_PROVISORIO = {
  title: 'Impuestos: qué te muestra Rendi y qué no',
  desc: 'Para una persona humana, vender CEDEARs y acciones argentinas en BYMA está exento de Ganancias. Por eso Rendi no te presenta esa ganancia como algo para declarar ante ARCA (la ex AFIP): te la muestra para que sepas cuánto ganaste. Lo que sí puede tributar —los dividendos de tus CEDEARs, o Bienes Personales sobre lo que tenés al 31 de diciembre— conviene revisarlo con tu contador.',
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
