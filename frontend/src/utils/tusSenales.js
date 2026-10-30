// tusSenales.js — las cuentas de la pestaña «Tus señales» (Mercado → Novedades).
// ════════════════════════════════════════════════════════════════════════════
// Nada se calcula de nuevo acá: los cambios, sus palabras, el peso de cada
// tenencia y el % en tendencia alcista vienen armados de GET /api/tus-senales
// (backend/senales_semana.py, la MISMA cuenta que el mail de los sábados). Acá
// sólo se filtra, se agrupa por día y se arman los textos de las tres tarjetas.

import { parteDeTuPlata } from './parteDeTuPlata'
import { AVISO_OCULTO } from './ocultarSaldos'

// Lo mismo, dicho igual en la Cartera (RadiografiaTecnica), el Panorama y
// Señales (auditoría D12, 29/10: había tres frases para «Ocultar saldos», dos
// títulos distintos y «la semana pasada» con y sin coma).
export const TITULO_PLATA_ALCISTA = 'Tu cartera en tendencia alcista de largo plazo'
export const PLATA_ALCISTA_OCULTA = `Qué parte de tu cartera está en tendencia alcista de largo plazo: ${AVISO_OCULTO.charAt(0).toLowerCase()}${AVISO_OCULTO.slice(1)}`
// Los cambios incluyen la watchlist: «en lo tuyo» a secas hacía pensar que no.
export const TITULO_CAMBIOS = 'Qué cambió esta semana en lo que tenés y en tu watchlist'
export const QUE_ES_ESTA_SEMANA = 'Los últimos 7 días, contados desde hoy.'

export const FILTROS = [
  { id: 'todo', label: 'Todo' },
  { id: 'tenes', label: 'Lo que tenés' },
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
  return p ? `Lo tenés · ${p}` : 'Lo tenés'
}

/** Las tres tarjetas de arriba. `datos` = la respuesta del servidor. */
export function tarjetas(datos, hidden) {
  const senales = datos?.senales || []
  const tuyas = senales.filter(s => s.tenes)
  const deWatch = senales.filter(s => s.watchlist && !s.tenes)
  const activos = datos?.tenes?.activos || 0
  const conCambios = datos?.tenes?.con_cambios || 0

  const tenes = {
    titulo: 'En lo que tenés',
    valor: plural(tuyas.length, 'cambio', 'cambios'),
    texto: activos === 0
      ? 'Todavía no hay precios guardados de ninguno de tus activos.'
      // «Con precios al día», no «con lectura»: en el Panorama y la Cartera «sin
      // lectura» es «sin tendencia de fondo» (sin promedio de 200), y un papel de
      // 120 días se contaba acá y salía allá «sin lectura» (re-test A2, 29/10).
      // Lo que se cuenta es `_se_lee` del servidor: precios al día.
      : tuyas.length === 0 ? `Nada cambió en tus ${plural(activos, 'activo', 'activos')} con precios al día.`
        : `en ${conCambios} de tus ${plural(activos, 'activo', 'activos')} con precios al día`,
  }
  const nombres = [...new Set(deWatch.map(s => s.asset))]
  const watch = {
    titulo: 'En tu watchlist',
    valor: plural(deWatch.length, 'cambio', 'cambios'),
    texto: !datos?.watchlist ? 'No seguís ningún activo todavía.'
      : nombres.length ? nombres.join(', ') : 'Nada cambió en lo que seguís.',
  }

  const a = datos?.alcista
  // Lo que se dio vuelta esta semana en lo tuyo: los cruces del promedio de 200.
  const vueltas = tuyas.filter(s => s.tipo === 'media200')
  const giro = vueltas.length
    ? vueltas.map(s => `${s.asset} pasó a ${s.sentido === 'arriba' ? 'alcista' : 'bajista'}`).join(', ') + ' esta semana'
    : null
  const plata = {
    titulo: TITULO_PLATA_ALCISTA,
    valor: !a ? '—' : hidden ? '••' : `${a.pct}%`,
    antes: a?.semana_pasada && !hidden ? antesConPct(a.semana_pasada, datos.hasta) : null,
    // Subió o bajó contra la semana pasada (el color del «antes»).
    tono: !a?.semana_pasada || hidden ? null : a.pct > a.semana_pasada.pct ? 'pos' : a.pct < a.semana_pasada.pct ? 'neg' : null,
    texto: !a ? 'Ninguno de tus activos tiene todavía suficiente historia de precios para calcular su tendencia de largo plazo.'
      : hidden ? PLATA_ALCISTA_OCULTA
        : giro || 'Medido en dólares, con el último cierre.',
  }
  return { tenes, watch, plata }
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

/** El texto del botón: si escribiste una tesis, revisarla; si no, el gráfico. */
export function boton(s) {
  return s.tesis ? 'Revisar tu tesis' : 'Ver el gráfico'
}

/** A dónde lleva el botón: la ficha del activo (/activo/X), por el símbolo que
 *  dio el servidor (el de tu cartera, o el de tu watchlist: «GGAL.BA»). */
export function rutaDeFicha(s) {
  return `/activo/${encodeURIComponent(s.ficha || s.asset)}`
}
