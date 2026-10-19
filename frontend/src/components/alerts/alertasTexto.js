// alertasTexto — cómo se DICE una alerta, en un solo lugar.
// ═══════════════════════════════════════════════════════════════════════════
// La misma alerta se nombra en tres sitios: la fila de «Mis alertas», la
// confirmación del formulario («Te avisamos cuando…») y el estado de abajo de
// cada fila («Está en $ 7.350 · le falta 8,8 %»). Si cada pantalla armara su
// frase, la del formulario y la de la lista terminan diciendo cosas distintas
// sobre la misma alerta. Acá viven las tres, puras (sin React), y se prueban
// en alertasTexto.test.js.
//
// Los números salen en convención argentina: $ 7.350 · US$ 231,80 · 8,8 %.
import { nfmt } from '../../utils/format'

export function monedaDe(symbol) {
  return String(symbol || '').toUpperCase().endsWith('.BA') ? 'ARS' : 'USD'
}

// El ticker como lo lee una persona: sin el .BA del riel, el FCI: de los fondos
// ni el -USD de las cripto (BTC-USD → BTC).
export function simbolo(s) {
  if (!s) return ''
  return String(s).replace(/^FCI:/, '').replace(/\.BA$/, '').replace(/-USD$/, '')
}

export function fmtPrecio(v, ccy) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  if (String(ccy || '').toUpperCase() === 'ARS') return '$ ' + nfmt(Number(v), 0)
  return 'US$ ' + nfmt(Number(v), 2)
}

// 8 → "8"; 8.75 → "8,8". Sin decimales de más en una frase.
export function fmtPct(v) {
  const n = Math.abs(Number(v) || 0)
  return Math.abs(n - Math.round(n)) < 0.05 ? nfmt(Math.round(n), 0) : nfmt(n, 1)
}

// Las dos mitades de la frase: quién (en negrita) y qué tiene que pasar.
// Sirve igual para una alerta guardada que para el borrador del formulario.
//   { quien: 'GGAL', que: 'sube a $ 8.000' }
//   { quien: 'Mi cartera', que: 'algo sube 8 % o cae 5 % en el día' }
export function frase(a) {
  if (!a) return { quien: '', que: '' }
  if (a.kind === 'price_target') {
    const verbo = a.direction === 'below' ? 'baja a' : 'sube a'
    return { quien: simbolo(a.symbol), que: `${verbo} ${fmtPrecio(a.threshold, a.currency)}` }
  }
  const cartera = a.scope === 'holdings'
  const partes = []
  if (Number(a.up_pct) > 0) partes.push(`sube ${fmtPct(a.up_pct)} %`)
  if (Number(a.down_pct) > 0) partes.push(`cae ${fmtPct(a.down_pct)} %`)
  const mov = partes.join(' o ') || 'se mueve'
  const cuando = !cartera && a.baseline === 'set_price' ? 'desde que la armé' : 'en el día'
  return cartera
    ? { quien: 'Mi cartera', que: `algo ${mov} ${cuando}` }
    : { quien: simbolo(a.symbol), que: `${mov} ${cuando}` }
}

// La confirmación del formulario: la frase de arriba contada en segunda persona.
export function confirmacion(a) {
  if (a.kind === 'price_target') {
    if (!a.symbol || !(Number(a.threshold) > 0)) return null
    return `Te avisamos cuando ${simbolo(a.symbol)} ${a.direction === 'below' ? 'baje' : 'suba'} a ${fmtPrecio(a.threshold, a.currency)}.`
  }
  const up = Number(a.up_pct) > 0, down = Number(a.down_pct) > 0
  if (!up && !down) return null
  if (a.scope !== 'holdings' && !a.symbol) return null
  const partes = []
  if (up) partes.push(`sube más de ${fmtPct(a.up_pct)} %`)
  if (down) partes.push(`cae más de ${fmtPct(a.down_pct)} %`)
  const quien = a.scope === 'holdings' ? 'algo de tu cartera' : simbolo(a.symbol)
  const cuando = a.scope !== 'holdings' && a.baseline === 'set_price'
    ? 'desde el precio de ahora' : 'en el día'
  return `Te avisamos si ${quien} ${partes.join(' o ')} ${cuando}.`
}

// El servidor sella los avisos en hora UTC y SIN la «Z» (`datetime.utcnow()`
// en alerts_engine). Leído a secas, el navegador lo toma como hora local y un
// aviso de las 22:00 de Argentina figura al día siguiente. Se lee como UTC y
// se pasa al día de Argentina, el mismo que usa el resto de la app.
const ZONA = 'America/Argentina/Buenos_Aires'
function instante(iso) {
  if (!iso) return null
  const s = String(iso)
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s.replace(' ', 'T')}Z`)
  return Number.isNaN(d.getTime()) ? null : d
}
export function diaArgentina(iso) {
  const d = instante(iso)
  return d ? new Intl.DateTimeFormat('en-CA', { timeZone: ZONA, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d) : ''
}
export function horaArgentina(iso) {
  const d = instante(iso)
  return d ? new Intl.DateTimeFormat('es-AR', { timeZone: ZONA, hour: '2-digit', minute: '2-digit', hour12: false }).format(d) : ''
}
export function fechaCorta(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(diaArgentina(iso))
  return m ? `${m[3]}/${m[2]}` : ''
}

// La línea gris de abajo de cada fila. `precio` es el de ahora (puede no
// llegar); `eventos` son los avisos recientes de la cuenta; `hoy` es la fecha
// AAAA-MM-DD de Argentina, para no confundir un aviso de ayer con uno de hoy.
export function estado(a, precio, eventos = [], hoy = '') {
  if (!a.active) {
    // Una alerta de «una sola vez» que ya avisó: el motor la apaga sola.
    if (a.repeat === 'once' && a.last_fired_at) return { texto: `Cumplida el ${fechaCorta(a.last_fired_at)}`, tono: 'apagada' }
    return { texto: 'Pausada', tono: 'apagada' }
  }
  const ultimo = eventos.find(e => e.alert_id === a.id)
  const avisoHoy = ultimo && hoy && diaArgentina(ultimo.fired_at) === hoy
  if (a.kind === 'price_target') {
    if (precio == null) return { texto: 'Esperando el precio', tono: 'normal' }
    const falta = (Number(a.threshold) / precio - 1) * 100
    const ya = a.direction === 'below' ? falta >= 0 : falta <= 0
    return {
      texto: ya
        ? `Está en ${fmtPrecio(precio, a.currency)} · ya pasó tu precio`
        : `Está en ${fmtPrecio(precio, a.currency)} · le falta ${fmtPct(falta)} %`,
      tono: 'normal',
    }
  }
  if (avisoHoy) return { texto: `Hoy avisó: ${ultimo.message}`, tono: 'aviso' }
  if (a.scope !== 'holdings' && a.baseline === 'set_price' && precio != null && Number(a.anchor_price) > 0) {
    const va = (precio / Number(a.anchor_price) - 1) * 100
    return { texto: `Va ${va < 0 ? '−' : '+'}${fmtPct(va)} % desde que la armaste`, tono: 'normal' }
  }
  return { texto: a.scope === 'holdings' ? 'Mira tus activos cada día' : 'Mira el movimiento de cada día', tono: 'normal' }
}

export function canal(ch) {
  return ch === 'push' ? 'Por celular' : ch === 'email' ? 'Por mail' : 'Por mail y celular'
}
