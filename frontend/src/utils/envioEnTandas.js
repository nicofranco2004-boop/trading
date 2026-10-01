// Envíos masivos del panel de admin, de a tandas.
//
// Los cinco mails masivos de /admin (re-engagement, regalo de plan, invitación
// a la prueba, feedback de la prueba y el mail libre) mandan igual, y el
// backend también (`_envio_masivo` en main.py):
//
//   · La lista que se VE en pantalla viaja en tandas de `lote` personas por
//     pedido. Cada pedido tiene que terminar antes del corte de ~30 s del proxy
//     de Vercel; con todo en uno solo, a partir de ~30 personas el admin veía un
//     error mientras los mails seguían saliendo, y volvía a apretar.
//   · Si al pedido se le acaba el tiempo (Resend lento), el backend devuelve
//     sin tocar los que no llegó a intentar (`pendientes`) y vuelven al frente
//     de la cola para el pedido siguiente.
//   · Cada persona viaja con la fecha de envío que se vio (`sent_at`, donde el
//     mail la tiene): si ya le llegó por otro click u otra pestaña, el backend
//     no gana la marca y la saltea. Por eso un doble click no le manda dos
//     veces a nadie.
//   · Si un pedido falla se corta ahí, y se devuelve lo que ya se sumó marcado
//     `cortado`: lo que salió, salió, y el panel lo tiene que decir. Con
//     `contesto` se distingue si el servidor llegó a contestar (un error suyo:
//     no quedó nada saliendo) o no (la red, o el proxy que corta a los 30 s:
//     la tanda puede seguir saliendo en el servidor).
//   · Si Resend no confirma mails seguidos (caído), el backend devuelve
//     `frenado` y acá se corta: seguir marcaba a todos sin mandar nada.
//   · El envío sigue aunque el panel se desmonte (se navegó a otra pantalla):
//     antes era un solo pedido y el servidor terminaba la lista igual. Su
//     estado (avance y último resultado) vive acá, fuera de los componentes,
//     para que el panel que se vuelve a montar lo muestre y no deje lanzar el
//     mismo mail otra vez mientras sale.

import { GATEWAY_ERRORS } from './gatewayRetry'

export const LOTE_POR_DEFECTO = 20

// Después de una tanda cortada (el pedido falló), el servidor puede seguir
// mandándola: el backend no empieza mails pasados 18 s y el último termina
// antes de los 30. Se espera eso antes de recargar la lista, para que no
// muestre como pendiente a quien está recibiendo el mail en ese momento.
export const ESPERA_TRAS_CORTE_MS = 30000

export const esperar = ms => new Promise(listo => setTimeout(listo, ms))

// ─── Los envíos en curso, por mail (url) ─────────────────────────────────────
// { [url]: { clave, progreso } } mientras sale, y el último resultado de cada
// mail. Cada cambio reemplaza el objeto (no lo modifica): así React ve que
// cambió (useSyncExternalStore compara por referencia).
let enCurso = {}
let ultimos = {}
const oyentes = new Set()

function cambio() {
  oyentes.forEach(fn => fn())
}

export function suscribirEnvios(fn) {
  oyentes.add(fn)
  return () => oyentes.delete(fn)
}

export function estadoEnvio(url) {
  return enCurso[url] || null
}

export function ultimoResultado(url) {
  return ultimos[url] || null
}

// Cerrar o recargar la pestaña SÍ frena las tandas que faltan: mientras haya
// un envío en curso, el navegador pregunta antes. Vive acá y no en el panel,
// porque el envío sigue aunque el panel ya no esté.
function avisarAntesDeSalir(e) {
  e.preventDefault()
  e.returnValue = ''
}

export function tomarEnvio(url, clave = 'enviar') {
  if (enCurso[url]) return false
  if (!Object.keys(enCurso).length && typeof window !== 'undefined') {
    window.addEventListener('beforeunload', avisarAntesDeSalir)
  }
  enCurso = { ...enCurso, [url]: { clave, progreso: null } }
  ultimos = { ...ultimos, [url]: null }
  cambio()
  return true
}

export function avanceEnvio(url, progreso) {
  if (!enCurso[url]) return
  enCurso = { ...enCurso, [url]: { ...enCurso[url], progreso } }
  cambio()
}

export function soltarEnvio(url, resultado) {
  if (resultado !== undefined) ultimos = { ...ultimos, [url]: resultado }
  if (enCurso[url]) {
    const { [url]: _, ...resto } = enCurso
    enCurso = resto
    if (!Object.keys(enCurso).length && typeof window !== 'undefined') {
      window.removeEventListener('beforeunload', avisarAntesDeSalir)
    }
  }
  cambio()
}

// ─── El envío ────────────────────────────────────────────────────────────────

export function totalVacio() {
  return { sent_count: 0, failed_count: 0, skipped_count: 0, discarded_count: 0,
           marcas_trabadas: [], inciertos: [] }
}

export async function enviarEnTandas({ post, url, cuerpo = {}, vistos, lote, alAvanzar = () => {} }) {
  const total = totalVacio()
  const n = vistos.length
  const tam = Math.max(1, Math.floor(Number(lote)) || LOTE_POR_DEFECTO)
  const cola = [...vistos]
  let hechos = 0
  // Los "no sabemos" seguidos con que terminó el pedido anterior: el freno
  // contra Resend caído cuenta a lo largo de TODO el envío, no por pedido (con
  // Resend lento cada pedido podía hacer uno solo y el freno nunca saltaba).
  let inciertosSeguidos = 0
  try {
    while (cola.length) {
      const tanda = cola.splice(0, tam)
      alAvanzar({ desde: hechos + 1, hasta: hechos + tanda.length, total: n })
      const r = await post(url, { ...cuerpo, confirm: true, vistos: tanda,
                                  inciertos_seguidos: inciertosSeguidos })
      // Un servidor sin `frenado` en la respuesta es el de ANTES de este
      // cambio (pasa unos minutos en cada deploy: la web se publica antes que
      // el servidor): ignora `vistos` y le manda a toda su lista en cada
      // pedido. No se le pide ni una tanda más.
      if (typeof r?.frenado !== 'boolean') {
        return { ...total, cortado: true, contesto: true,
                 error: 'el servidor todavía no tiene la versión nueva' }
      }
      total.sent_count += r.sent_count || 0
      total.failed_count += r.failed_count || 0
      total.skipped_count += r.skipped_count || 0
      total.discarded_count += r.discarded_count || 0
      total.marcas_trabadas.push(...(r.marcas_trabadas || []))
      total.inciertos.push(...(r.inciertos || []))
      inciertosSeguidos = r.inciertos_seguidos || 0
      if (r.frenado) {
        return { ...total, cortado: true, frenado: true, contesto: true,
                 error: 'Resend no está confirmando los envíos' }
      }
      const quedan = new Set((r.pendientes || []).map(p => p.id))
      const devueltos = tanda.filter(v => quedan.has(v.id))
      // El backend siempre procesa al menos uno: si devuelve la tanda entera,
      // algo anda mal, y seguir sería un loop sin fin.
      if (devueltos.length && devueltos.length === tanda.length) {
        return { ...total, cortado: true, contesto: true,
                 error: 'el servidor no llegó a mandar ninguno' }
      }
      cola.unshift(...devueltos)
      hechos += tanda.length - devueltos.length
    }
  } catch (e) {
    // 502/503/504 los contesta el proxy, no el servidor: el pedido puede
    // seguir corriendo detrás.
    const contesto = Boolean(e?.status) && !GATEWAY_ERRORS.includes(e.status)
    return { ...total, cortado: true, contesto, error: e?.message || String(e) }
  }
  return total
}

export function textoDeProgreso(progreso) {
  if (!progreso) return 'Enviando…'
  if (progreso.fase === 'esperando') return 'Esperando que termine la tanda cortada…'
  if (progreso.fase === 'recargando') return 'Actualizando la lista…'
  return `Enviando ${progreso.desde}–${progreso.hasta} de ${progreso.total}…`
}
