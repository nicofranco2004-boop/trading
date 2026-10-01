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
//     `cortado`: lo que salió, salió, y el panel lo tiene que decir.

export const LOTE_POR_DEFECTO = 20

// Después de una tanda cortada (el pedido falló), el servidor puede seguir
// mandándola: el backend no empieza mails pasados 18 s y el último termina
// antes de los 30. Se espera eso antes de recargar la lista, para que no
// muestre como pendiente a quien está recibiendo el mail en ese momento.
export const ESPERA_TRAS_CORTE_MS = 30000

export const esperar = ms => new Promise(listo => setTimeout(listo, ms))

export function totalVacio() {
  return { sent_count: 0, failed_count: 0, skipped_count: 0, discarded_count: 0,
           marcas_trabadas: [], inciertos: [] }
}

// `seguir()` en false (el panel se desmontó) frena antes de la tanda siguiente.
export async function enviarEnTandas({ post, url, cuerpo = {}, vistos, lote, alAvanzar = () => {},
                                       seguir = () => true }) {
  const total = totalVacio()
  const n = vistos.length
  const tam = Math.max(1, Math.floor(Number(lote)) || LOTE_POR_DEFECTO)
  const cola = [...vistos]
  let hechos = 0
  try {
    while (cola.length) {
      if (!seguir()) throw new Error('se salió de la pantalla')
      const tanda = cola.splice(0, tam)
      alAvanzar({ desde: hechos + 1, hasta: hechos + tanda.length, total: n })
      const r = await post(url, { ...cuerpo, confirm: true, vistos: tanda })
      total.sent_count += r?.sent_count || 0
      total.failed_count += r?.failed_count || 0
      total.skipped_count += r?.skipped_count || 0
      total.discarded_count += r?.discarded_count || 0
      total.marcas_trabadas.push(...(r?.marcas_trabadas || []))
      total.inciertos.push(...(r?.inciertos || []))
      const quedan = new Set((r?.pendientes || []).map(p => p.id))
      const devueltos = tanda.filter(v => quedan.has(v.id))
      // El backend siempre intenta al menos uno: si devuelve la tanda entera,
      // algo anda mal, y seguir sería un loop sin fin.
      if (devueltos.length && devueltos.length === tanda.length) {
        throw new Error('el servidor no llegó a mandar ninguno')
      }
      cola.unshift(...devueltos)
      hechos += tanda.length - devueltos.length
    }
  } catch (e) {
    return { ...total, cortado: true, error: e?.message || String(e) }
  }
  return total
}

export function textoDeProgreso(progreso) {
  if (!progreso) return 'Enviando…'
  if (progreso.fase === 'esperando') return 'Esperando que termine la tanda cortada…'
  if (progreso.fase === 'recargando') return 'Actualizando la lista…'
  return `Enviando ${progreso.desde}–${progreso.hasta} de ${progreso.total}…`
}
