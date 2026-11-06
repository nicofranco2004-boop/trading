// Sondas sobre cómo se comportan los programas de Google y Meta (no el código de Rendi):
// qué perillas existen para que lo que mandan no lleve la dirección real.
import { abrirPestana, leerEnvios, contar, espera, intentosDeSalir, BLOQUE_PIXEL, paquete, cerrarPestana } from './banco.mjs'

const SITIO = 'https://rendi.finance'
const DATOS1 = '/analisis-tecnico?tab=backtesting&activos=ZZPRIVADO&pesos=73,27'
const DATOS2 = '/analisis-tecnico?tab=backtesting&activos=ZZPRIVADO&pesos=74,26'

async function soloGoogle(url, titulo) {
  const p = await abrirPestana({ url, titulo })
  p.w.eval(paquete)
  return p
}

// F · gtag('set', {page_location, page_referrer, page_title}) al arrancar: ¿lo respetan
// la vista manual, un evento, el scroll y las vistas automáticas por cambio de dirección?
{
  const p = await soloGoogle(SITIO + DATOS1, 'Informe de cartera — Cliente Secreta')
  p.w.__rendi.initAnalytics()
  p.w.gtag('set', { page_location: SITIO + '/LIMPIO-1', page_referrer: SITIO + '/REF-LIMPIO', page_title: 'TITULO-LIMPIO' })
  p.w.gtag('event', 'page_view')
  p.w.gtag('event', 'ai_chat_sent', { source: 'x' })
  await espera(1500)
  p.w.history.pushState({}, '', DATOS2)
  await espera(1500)
  p.w.history.replaceState({}, '', DATOS1)
  await espera(1500)
  await cerrarPestana(p)
  contar('F · set al arrancar (sin tocar nada más)', leerEnvios(p.anotados))
}

// F2 · Además, la app envuelve pushState/replaceState ANTES de que cargue gtag.js y en
// cada cambio de dirección pone la dirección limpia con set, antes de que pase.
{
  const p = await soloGoogle(SITIO + DATOS1, 'Rendi')
  p.w.eval(`(function () {
    function limpia(u) { var x = new URL(u, location.href); return x.origin + '/LIMPIO' + x.pathname.replace(/\\//g, '_') }
    ['pushState', 'replaceState'].forEach(function (m) {
      var orig = history[m]
      history[m] = function (s, t, u) {
        if (u != null && window.gtag) gtag('set', { page_location: limpia(u), page_referrer: limpia(location.href) })
        return orig.apply(this, arguments)
      }
    })
  })()`)
  p.w.__rendi.initAnalytics()
  p.w.gtag('set', { page_location: SITIO + '/LIMPIO-arranque', page_referrer: '' })
  await espera(1500)
  p.w.history.pushState({}, '', DATOS2)
  await espera(1500)
  p.w.history.replaceState({}, '', DATOS1)
  await espera(1500)
  p.w.dispatchEvent(new p.w.PopStateEvent('popstate', { state: {} }))
  await espera(1500)
  await cerrarPestana(p)
  contar('F2 · set en cada cambio de dirección, desde un envoltorio puesto antes de gtag.js', leerEnvios(p.anotados))
}

// G · ¿Se puede volver al título vivo de la página después de un set page_title?
{
  const p = await soloGoogle(SITIO + '/cartera', 'Titulo vivo 1')
  p.w.__rendi.initAnalytics()
  p.w.gtag('set', { page_title: 'TITULO-FIJO' })
  p.w.gtag('event', 'evento_1')
  await espera(800)
  p.w.gtag('set', { page_title: undefined })
  p.w.document.title = 'Titulo vivo 2'
  p.w.gtag('event', 'evento_2_tras_undefined')
  await espera(800)
  p.w.gtag('set', { page_title: null })
  p.w.document.title = 'Titulo vivo 3'
  p.w.gtag('event', 'evento_3_tras_null')
  await espera(800)
  p.w.gtag('set', { page_title: '' })
  p.w.document.title = 'Titulo vivo 4'
  p.w.gtag('event', 'evento_4_tras_vacio')
  await espera(1500)
  await cerrarPestana(p)
  contar('G · page_title: fijo y después undefined / null / vacío', leerEnvios(p.anotados).filter((e) => e.destino === 'Google Analytics' && e.evento !== 'scroll'))
}

// H · Meta con fbq.disablePushState = true: ¿deja de mandar vistas solas al cambiar la dirección?
{
  const p = await abrirPestana({ url: SITIO + '/analisis?tab=resumen' })
  p.w.eval(BLOQUE_PIXEL.replace("fbq('init'", "fbq.disablePushState = true;\n      fbq('init'"))
  await espera(1500)
  p.anotados.length = 0
  p.w.history.pushState({}, '', DATOS1)
  await espera(1200)
  p.w.history.replaceState({}, '', DATOS2)
  await espera(1200)
  p.w.dispatchEvent(new p.w.PopStateEvent('popstate', { state: {} }))
  await espera(1200)
  contar('H · Meta con disablePushState: cambios de dirección después de entrar limpio', leerEnvios(p.anotados))
}

// H0 · Control: lo mismo SIN disablePushState.
{
  const p = await abrirPestana({ url: SITIO + '/analisis?tab=resumen' })
  p.w.eval(BLOQUE_PIXEL)
  await espera(1500)
  p.anotados.length = 0
  p.w.history.pushState({}, '', DATOS1)
  await espera(1200)
  p.w.history.replaceState({}, '', DATOS2)
  await espera(1200)
  contar('H0 · control: Meta como está hoy, mismos cambios de dirección', leerEnvios(p.anotados))
}

console.log(`\nIntentos de salir a internet: ${intentosDeSalir.length}`)
process.exit(0)
