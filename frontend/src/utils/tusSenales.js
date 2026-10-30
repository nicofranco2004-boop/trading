// tusSenales.js — las cuentas de la pestaña «Tus señales» (Mercado → Novedades).
// ════════════════════════════════════════════════════════════════════════════
// Nada se calcula de nuevo acá: los cambios, sus palabras, el peso de cada
// tenencia y el % en tendencia alcista vienen armados de GET /api/tus-senales
// (backend/senales_semana.py, la MISMA cuenta que el mail de los sábados). Acá
// sólo se filtra, se ordena, se agrupa por día y se arman los textos de la
// franja de arriba y de cada tarjeta de la agenda.

import { parteDeTuPlata } from './parteDeTuPlata'
import { AVISO_OCULTO } from './ocultarSaldos'

// Lo mismo, dicho igual en la Cartera (RadiografiaTecnica), el Panorama y
// Señales (auditoría D12, 29/10: había tres frases para «Ocultar saldos», dos
// títulos distintos y «la semana pasada» con y sin coma).
export const TITULO_PLATA_ALCISTA = 'Tu cartera en tendencia alcista de largo plazo'
export const PLATA_ALCISTA_OCULTA = `Qué parte de tu cartera está en tendencia alcista de largo plazo: ${AVISO_OCULTO.charAt(0).toLowerCase()}${AVISO_OCULTO.slice(1)}`
// Los cambios incluyen la watchlist: «en lo tuyo» a secas hacía pensar que no.
export const TITULO_CAMBIOS = 'Qué cambió esta semana en tu cartera y en tu watchlist'
export const QUE_ES_ESTA_SEMANA = 'Los últimos 7 días, contados desde hoy.'

export const FILTROS = [
  { id: 'todo', label: 'Todo' },
  { id: 'tenes', label: 'Tu cartera' },
  { id: 'watchlist', label: 'Watchlist' },
]

export const CANALES = [
  { id: 'mail', label: 'Mail' },
  { id: 'push', label: 'Notificación' },
  { id: 'ambos', label: 'Mail y notificación' },
  { id: 'no', label: 'No recibirlo' },
]

export const NO_ES_RECOMENDACION = 'Muestra cómo se movieron los precios: no es una recomendación para comprar ni vender.'

const DIAS = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']

/** «Viernes 23/10» de un 'YYYY-MM-DD'. */
export function diaLargo(iso) {
  const [y, m, d] = String(iso).split('-').map(Number)
  const f = new Date(Date.UTC(y, m - 1, d))
  return `${DIAS[f.getUTCDay()]} ${String(d).padStart(2, '0')}/${String(m).padStart(2, '0')}`
}

/** Lo que pasa el filtro elegido. Un activo que tenés Y seguís sale en los dos. */
export function filtrar(senales = [], filtro = 'todo') {
  if (filtro === 'tenes') return senales.filter(s => s.tenes)
  if (filtro === 'watchlist') return senales.filter(s => s.watchlist)
  return senales
}

/** [{ fecha, dia, items }] en el orden en que vienen (el día más nuevo primero). */
export function porDia(senales = []) {
  const out = []
  for (const s of senales) {
    const ultimo = out[out.length - 1]
    if (ultimo && ultimo.fecha === s.fecha) ultimo.items.push(s)
    else out.push({ fecha: s.fecha, dia: diaLargo(s.fecha), items: [s] })
  }
  return out
}

const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`

/** El peso de una tenencia en palabras, o null si no se muestra. Con «Ocultar
 *  saldos» no va: la proporción también es información de la cartera. */
export function pesoTxt(peso, hidden) {
  if (hidden || peso == null) return null
  return `${parteDeTuPlata(peso * 100)} de tu cartera`
}

/** La línea de abajo de cada cambio: «Lo tenés · 12% de tu plata» / «En tu watchlist». */
export function deQuien(s, hidden) {
  if (!s.tenes) return 'En tu watchlist'
  const p = pesoTxt(s.peso, hidden)
  return p ? `En tu cartera · ${p}` : 'En tu cartera'
}

/** De qué lado movió el precio un cambio: 'favor' (subió o se afirmó para
 *  arriba), 'contra' (bajó) o null (la fuerza de la tendencia sin dirección).
 *  Es lo que cuenta «A favor · en contra» y el color de cada cambio. */
export function lado(s) {
  if (s?.tipo === 'media200' || s?.tipo === 'media50') return s.sentido === 'arriba' ? 'favor' : s.sentido === 'abajo' ? 'contra' : null
  if (s?.tipo === 'rsi_bajo_30') return 'contra'
  if (s?.tipo === 'rsi_sobre_70' || s?.tipo === 'maximo_12m') return 'favor'
  if (s?.tipo === 'adx23') return s.squeeze === 1 ? 'favor' : s.squeeze === -1 ? 'contra' : null
  return null
}

/** El color de un cambio en las barras y en su etiqueta: 'azul' el máximo y
 *  la fuerza (como el lienzo de Nico); los demás, verde o rojo según `lado`. */
export function colorDelCambio(s) {
  if (s?.tipo === 'maximo_12m' || s?.tipo === 'adx23') return 'azul'
  const l = lado(s)
  return l === 'favor' ? 'pos' : l === 'contra' ? 'neg' : 'azul'
}

/** La etiqueta corta de la tarjeta de la agenda. */
export const ETIQUETA_CORTA = {
  media200: 'Largo plazo', media50: 'Mediano plazo',
  rsi_bajo_30: 'Impulso', rsi_sobre_70: 'Impulso',
  maximo_12m: 'Máximo', adx23: 'Fuerza',
}

/** «hoy» / «ayer» / «hace 3 días»: contado desde `hasta` (el hoy del
 *  servidor), no desde el reloj de la compu. */
export function hace(fecha, hasta) {
  const d = Math.round((Date.parse(`${hasta}T00:00:00Z`) - Date.parse(`${fecha}T00:00:00Z`)) / 86400000)
  if (!Number.isFinite(d) || d < 0) return null
  return d === 0 ? 'hoy' : d === 1 ? 'ayer' : `hace ${d} días`
}

/** La segunda línea de la tarjeta: `detalle` del servidor (un servidor de
 *  antes, mientras se despliega, no lo manda: va `texto` entero). */
export function detalleDe(s) {
  return s.detalle || s.texto
}

/** De quién es, al pie de la tarjeta: «18% de tu cartera» / «en tu cartera»
 *  (sin el peso, o con «Ocultar saldos») / «en tu watchlist». */
export function quienCorto(s, hidden) {
  if (!s.tenes) return 'en tu watchlist'
  return pesoTxt(s.peso, hidden) || 'en tu cartera'
}

/** El orden en que se muestran. El servidor manda, dentro de cada día, lo
 *  tuyo de más a menos peso: con «Ocultar saldos» ese orden delata cuál pesa
 *  más (memoria «la privacidad se filtra por la forma»). Con el ojito, adentro
 *  de cada día va lo tuyo y después la watchlist, cada parte por nombre. Lo
 *  usan Señales, sus barras y el Panorama (que elige los 3 más nuevos). */
export function enOrden(senales = [], hidden = false) {
  if (!hidden) return senales
  return [...senales].sort((a, b) => (a.fecha < b.fecha ? 1 : a.fecha > b.fecha ? -1 : 0)
    || (Number(!!b.tenes) - Number(!!a.tenes))
    || String(a.asset).localeCompare(String(b.asset)))
}

/** Los días de las barras, de `desde` (exclusive, como el servidor) a `hasta`:
 *  [{ fecha, dia, items }], el más viejo primero. */
export function diasDeLasBarras(senales = [], desde, hasta) {
  const out = []
  const ini = Date.parse(`${desde}T00:00:00Z`)
  const fin = Date.parse(`${hasta}T00:00:00Z`)
  if (!Number.isFinite(ini) || !Number.isFinite(fin)) return out
  for (let t = ini + 86400000; t <= fin; t += 86400000) {
    const fecha = new Date(t).toISOString().slice(0, 10)
    out.push({ fecha, dia: diaLargo(fecha), items: senales.filter(s => s.fecha === fecha) })
  }
  return out
}

/** La franja de 3 números de arriba. `datos` = la respuesta del servidor. */
export function franja(datos, hidden) {
  const senales = datos?.senales || []
  const tuyas = senales.filter(s => s.tenes).length
  const deWatch = senales.filter(s => s.watchlist && !s.tenes).length
  const activos = datos?.tenes?.activos || 0

  const cambios = {
    titulo: 'Cambios esta semana',
    valor: senales.length,
    texto: senales.length
      ? `${tuyas} en tu cartera · ${deWatch} en tu watchlist`
      : activos === 0 ? 'Todavía no hay precios guardados de ninguno de tus activos.'
        // «Con precios al día», no «con lectura» (re-test A2, 29/10): lo que se
        // cuenta es `_se_lee` del servidor.
        : `Nada cambió en tus ${plural(activos, 'activo', 'activos')} con precios al día.`,
  }
  const lados = {
    titulo: 'A favor · en contra',
    favor: senales.filter(s => lado(s) === 'favor').length,
    contra: senales.filter(s => lado(s) === 'contra').length,
  }

  const a = datos?.alcista
  // Lo que se dio vuelta esta semana en lo tuyo: la MISMA frase que «Qué lo
  // movió» del Panorama, `queLoMovio`.
  const giro = queLoMovio(datos, hidden)
  const plata = {
    titulo: TITULO_PLATA_ALCISTA,
    valor: !a ? '—' : hidden ? '••' : `${a.pct}%`,
    // El mismo chip del Panorama: «▲ 8 puntos más que la semana pasada».
    cambio: a ? cambioContraAntes(a, datos.hasta, hidden) : null,
    texto: !a ? 'Ninguno de tus activos tiene todavía suficiente historia de precios para calcular su tendencia de largo plazo.'
      : hidden ? PLATA_ALCISTA_OCULTA
        : giro || 'Medido en dólares, con el último cierre.',
  }
  return { cambios, lados, plata }
}

/** «la semana pasada» si es el sábado de hace 7 días; si no, «el sábado 17/10». */
export function semanaPasadaTxt(sp, hasta) {
  if (!sp?.semana) return ''
  const dias = (Date.parse(hasta + 'T00:00:00Z') - Date.parse(sp.semana + 'T00:00:00Z')) / 86400000
  if (dias === 7) return 'la semana pasada'
  return `el ${diaLargo(sp.semana).toLowerCase()}`
}

/** «el sábado 24/10, 86%»: la semana pasada con su %, con coma, en las tres pantallas. */
export function antesConPct(sp, hasta) {
  if (!sp?.semana) return null
  return `${semanaPasadaTxt(sp, hasta)}, ${Math.round(sp.pct)}%`
}

/** El chip del Panorama contra la semana pasada: «▲ 8 puntos más que la semana
 *  pasada» / «▼ 3 puntos menos que el sábado 17/10» / «Igual que la semana
 *  pasada». `a`: el reparto del servidor (pct + semana_pasada). null sin semana
 *  pasada o con «Ocultar saldos» (la diferencia también dice cuánto se movió tu
 *  plata). → { texto, tono: 'pos' | 'neg' | null } */
export function cambioContraAntes(a, hasta, hidden) {
  const sp = a?.semana_pasada
  if (hidden || a?.pct == null || !sp?.semana || sp.pct == null) return null
  const d = Math.round(a.pct) - Math.round(sp.pct)
  const cuando = semanaPasadaTxt(sp, hasta)
  if (d === 0) return { texto: `Igual que ${cuando}`, tono: null }
  const n = Math.abs(d)
  return {
    texto: `${d > 0 ? '▲' : '▼'} ${n} ${n === 1 ? 'punto' : 'puntos'} ${d > 0 ? 'más' : 'menos'} que ${cuando}`,
    tono: d > 0 ? 'pos' : 'neg',
  }
}

/** «GGAL (18% de tu cartera) pasó a alcista el jueves 29/10»: lo que se dio
 *  vuelta esta semana en lo que tenés (los cruces del promedio de 200, lo único
 *  que cambia de grupo a un activo). null si no se dio vuelta nada. Con
 *  «Ocultar saldos», sin el peso. */
export function queLoMovio(datos, hidden) {
  const vueltas = enOrden(datos?.senales || [], hidden).filter(s => s.tenes && s.tipo === 'media200')
  if (!vueltas.length) return null
  return vueltas.map(s => {
    const p = pesoTxt(s.peso, hidden)
    return `${s.asset}${p ? ` (${p})` : ''} pasó a ${s.sentido === 'arriba' ? 'alcista' : 'bajista'} el ${diaLargo(s.fecha).toLowerCase()}`
  }).join('; ') + '.'
}

/** El texto del botón: si escribiste una tesis, revisarla; si no, el gráfico. */
export function boton(s) {
  return s.tesis ? 'Revisar tu tesis' : 'Ver el gráfico'
}

/** A dónde lleva el botón: la ficha del activo (/activo/X), por el símbolo que
 *  dio el servidor (el de tu cartera, o el de tu watchlist: «GGAL.BA»). */
export function rutaDeFicha(s) {
  return `/activo/${encodeURIComponent(s.ficha || s.asset)}`
}

/** «El resumen de la semana te llega el sábado 31/10 a las 10:00, por mail».
 *  `proximo`: el sábado en que sale el próximo, que lo dice el servidor
 *  (`proximo_resumen`, con la regla del envío). Antes se calculaba acá con la
 *  fecha sola, y el sábado a la tarde anunciaba en futuro el resumen que ya
 *  había salido (auditoría A 29/10, A9). Sin el dato (un servidor de antes,
 *  mientras se despliega), no se inventa una fecha. */
export function textoDelResumen(canal, proximo) {
  if (!canal || canal === 'no') return 'No te llega el resumen de los sábados.'
  const como = { mail: 'por mail', push: 'por notificación', ambos: 'por mail y notificación' }[canal]
  const [, m, d] = String(proximo || '').split('-')
  if (!m || !d) return `El resumen de la semana te llega los sábados a las 10:00, ${como}.`
  return `El resumen de la semana te llega el sábado ${d}/${m} a las 10:00, ${como}.`
}
