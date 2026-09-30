// relojVisible — llama a `fn` cada `ms` mientras la pestaña esté a la vista.
// ════════════════════════════════════════════════════════════════════════════
// Lo usan los que refrescan datos de mercado solos: la cinta de cotizaciones
// (useMarketIndices), los movers y la watchlist del inicio (useRelojVisible).
// Una sola implementación para los tres: antes de esto, la cinta tenía la suya
// y el resto no refrescaba nunca.
//
// Con la pestaña oculta no pide nada (nadie está mirando, y el navegador igual
// frena los relojes). Al volver a la vista llama a `alVolver`: por defecto, a
// `fn` si ya pasó el plazo desde la última vez; quien necesite otra cuenta (la
// cinta mira la edad del DATO, no la del reloj) pasa la suya.
//
// El tic llama a `fn` sin mirar la edad: si mirara, un pedido que tardó 300 ms
// quedaría "300 ms más joven" que el plazo y se salteaba una vuelta entera.
//
// Devuelve la función que lo apaga.

// Cada cuánto se refrescan las secciones de mercado. Los datos vienen de
// servidores que los guardan entre 1 minuto (cotizaciones sueltas) y 30
// (movers): pedir más seguido no trae nada más nuevo, sólo carga.
export const REFRESCO_MERCADO_MS = 5 * 60 * 1000
// Con todas las ruedas de una lista cerradas los números no pueden cambiar, y
// la watchlist es la que más cuida esto: cada pedido suyo puede bajar
// cotizaciones de Yahoo POR USUARIO (el cache de una cotización dura 1 min), y
// ese límite de Yahoo es el mismo del que comen los precios de toda la app.
//
// Pero con un intervalo fijo de 30 min el cartel seguía diciendo "Cerrado"
// hasta media hora después de la campana. Las dos aperturas caen en punto o y
// media (NY 9:30 ET, BYMA 11:00 ART, y los husos son de horas enteras), así que
// con todo cerrado el próximo pedido va a la próxima media hora en punto, más
// un margen para que el proveedor ya tenga la barra: a lo sumo un pedido cada
// 30 min, y el cartel cambia ~1,5 min después de que abre.
export const MARGEN_APERTURA_MS = 90 * 1000

export function msHastaProximaMediaHora(ahora = new Date()) {
  const media = 30 * 60 * 1000
  const t = ahora.getTime()
  return (Math.floor(t / media) + 1) * media - t
}

// Cada cuánto refrescar según el estado de rueda que manda el servidor
// (home.market.estado_de_rueda). Sin estado todavía, el ritmo normal.
export function refrescoSegunRueda(estado, ahora = new Date()) {
  if (!estado) return REFRESCO_MERCADO_MS
  const algoVivo = estado.abierto || estado.en_rueda > 0 || estado.en_horario
  return algoVivo ? REFRESCO_MERCADO_MS : msHastaProximaMediaHora(ahora) + MARGEN_APERTURA_MS
}

export function relojVisible(fn, ms, { alVolver } = {}) {
  if (typeof document === 'undefined') return () => {}
  let ultimo = Date.now()
  const correr = () => { ultimo = Date.now(); fn() }
  const id = setInterval(() => {
    if (document.visibilityState !== 'hidden') correr()
  }, ms)
  const onVisibility = () => {
    if (document.visibilityState !== 'visible') return
    if (alVolver) alVolver()
    else if (Date.now() - ultimo >= ms) correr()
  }
  document.addEventListener('visibilitychange', onVisibility)
  return () => {
    clearInterval(id)
    document.removeEventListener('visibilitychange', onVisibility)
  }
}
