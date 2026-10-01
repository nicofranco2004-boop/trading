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
//   · Cada persona viaja con la fecha de envío que se vio (`sent_at`, donde el
//     mail la tiene): si ya le llegó por otro click u otra pestaña, el backend
//     no gana la marca y la saltea. Por eso un doble click no le manda dos
//     veces a nadie.
//   · Si un pedido falla se corta ahí, y se devuelve lo que ya se sumó marcado
//     `cortado`: lo que salió, salió, y el panel lo tiene que decir.

export const LOTE_POR_DEFECTO = 20

export function totalVacio() {
  return { sent_count: 0, failed_count: 0, skipped_count: 0, discarded_count: 0, marcas_trabadas: [] }
}

export async function enviarEnTandas({ post, url, cuerpo = {}, vistos, lote, alAvanzar = () => {} }) {
  const total = totalVacio()
  const n = vistos.length
  const tam = Math.max(1, Math.floor(Number(lote)) || LOTE_POR_DEFECTO)
  try {
    for (let i = 0; i < n; i += tam) {
      alAvanzar({ desde: i + 1, hasta: Math.min(i + tam, n), total: n })
      const r = await post(url, { ...cuerpo, confirm: true, vistos: vistos.slice(i, i + tam) })
      total.sent_count += r?.sent_count || 0
      total.failed_count += r?.failed_count || 0
      total.skipped_count += r?.skipped_count || 0
      total.discarded_count += r?.discarded_count || 0
      total.marcas_trabadas.push(...(r?.marcas_trabadas || []))
    }
  } catch (e) {
    return { ...total, cortado: true, error: e?.message || String(e) }
  }
  return total
}

export function textoDeProgreso(progreso) {
  return progreso
    ? `Enviando ${progreso.desde}–${progreso.hasta} de ${progreso.total}…`
    : 'Enviando…'
}
