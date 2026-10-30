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
import { esAccionLocal, esLocalSinTenencia } from '../../utils/accionLocal'

// ── Alertas técnicas ─────────────────────────────────────────────────────────
// Las señales que se pueden vigilar (backend/tecnico.py → SENALES), dichas con
// las palabras de la ficha técnica: «promedio de 200 días», «fuerza (RSI)».
// `tarjeta` = la tarjeta de la ficha donde va su botón «Avisame».
export const SENALES_TECNICAS = [
  { id: 'media200', texto: 'Cruce su promedio de 200 días', conSentido: true, tarjeta: 'fondo' },
  { id: 'media50', texto: 'Cruce su promedio de 50 días', conSentido: true, tarjeta: 'corto' },
  { id: 'rsi_bajo_30', texto: 'La fuerza (RSI) baje de 30', tarjeta: 'rsi' },
  { id: 'rsi_sobre_70', texto: 'La fuerza (RSI) pase 70', tarjeta: 'rsi' },
  { id: 'rsi_sube_30', texto: 'La fuerza (RSI) vuelva a pasar 30', tarjeta: 'rsi' },
  { id: 'rsi_baja_70', texto: 'La fuerza (RSI) vuelva a bajar de 70', tarjeta: 'rsi' },
  { id: 'maximo_12m', texto: 'Cierre en su máximo del año', tarjeta: 'maximo' },
]
export const conSentido = (senal) => !!SENALES_TECNICAS.find(s => s.id === senal)?.conSentido

// Tu línea del gráfico (senal 'linea', Nico 28/10): no es una señal de la
// lista, se pide desde la línea elegida. De qué tipo es lo dice el borrador
// (`tipoLinea`) o, en una alerta guardada, su referencia al dibujo (`dibujo`,
// el JSON que guarda main._crear_alerta_de_linea).
export function tipoDeLinea(a) {
  if (a?.tipoLinea) return a.tipoLinea
  try { return JSON.parse(a?.dibujo || 'null')?.tipo || null } catch { return null }
}
const nombreDeLinea = (a) => (tipoDeLinea(a) === 'tendencia' ? 'tu línea de tendencia' : 'tu línea horizontal')
/** «Toque tu línea horizontal», para el formulario. */
export const textoDeLinea = (a) => `Toque ${nombreDeLinea(a)}`

// Qué pasa, en presente («pasa para arriba su promedio de 200 días») o en
// subjuntivo para la confirmación («cuando pase para arriba…»).
function queTecnico(senal, direction, subj) {
  const v = (pres, sub) => (subj ? sub : pres)
  if (senal === 'media200' || senal === 'media50') {
    const dias = senal === 'media200' ? 200 : 50
    if (direction === 'above') return `${v('pasa', 'pase')} para arriba su promedio de ${dias} días`
    if (direction === 'below') return `${v('queda', 'quede')} abajo de su promedio de ${dias} días`
    return `${v('cruza', 'cruce')} su promedio de ${dias} días`
  }
  if (senal === 'rsi_bajo_30') return `${v('baja', 'baje')} de 30`
  if (senal === 'rsi_sobre_70') return `${v('pasa', 'pase')} 70`
  if (senal === 'rsi_sube_30') return `${v('vuelve', 'vuelva')} a pasar 30`
  if (senal === 'rsi_baja_70') return `${v('vuelve', 'vuelva')} a bajar de 70`
  return `${v('cierra', 'cierre')} en su máximo del año`
}
const esRsi = (senal) => String(senal || '').startsWith('rsi_')

// «AAPL» o «AAPL en pesos»: la ficha y la alerta miran en dólares por defecto
// (en pesos el precio también sube con el dólar). La misma regla que el mail
// (alerts_engine._quien_tecnico).
function quienTecnico(a) {
  const s = simbolo(a.symbol)
  const ccy = String(a.currency || '').toUpperCase()
  if (ccy === 'ARS' && !a.accion_local) return `${s} en pesos`
  if (ccy === 'USD' && a.accion_local) return `${s} en dólares`
  return s
}

// Lo que se guarda de un activo elegido en el buscador para una alerta técnica:
// el activo pelado (como lo pide la ficha) y si es una acción argentina (su
// precio de BYMA ÷ MEP, no el ADR). Con la MISMA regla que la ficha: por tus
// lotes si lo tenés (`esAccionLocal`), y si no por la regla de lo que no tenés
// (`esLocalSinTenencia`, la de `miradaSinTenencia`). Así el aviso mira la
// misma serie que muestra la ficha a la que lleva el botón del mail. El 22/10
// se pasó a «sólo tus lotes» porque la ficha sin lotes mostraba el ADR; después
// la ficha pasó a mostrar BYMA y esto no se movió: GGAL sin tenerla miraba el
// ADR y la ficha BYMA (re-test de la auditoría A, 29/10).
export function activoTecnico(symbol, posiciones = []) {
  const s = String(symbol || '').trim().toUpperCase()
  const pelado = s.replace(/\.BA$/, '')
  const lotes = (posiciones || []).filter(p => !p.is_cash && String(p.asset || '').toUpperCase() === pelado)
  return { symbol: pelado, accion_local: lotes.length ? esAccionLocal(pelado, lotes) : esLocalSinTenencia(s) }
}

// El activo que se vigila con un aviso de PRECIO o de %. Una acción argentina
// (GGAL, BMA, YPFD…) se mira en la Bolsa de Buenos Aires, en pesos ('GGAL.BA'):
// el buscador la ofrece como «Grupo Financiero Galicia · BCBA» pero su código
// viene pelado, y 'GGAL' a secas es el ADR de Nueva York, en dólares (10
// acciones por ADR). Así, quien buscaba GGAL para «avisame si llega a $ 8.000»
// quedaba mirando US$ 40 y el aviso no saltaba nunca (22/10/2026).
// La única excepción es un link que pide dólares a propósito: la posición de un
// broker de afuera (Schwab) tiene el ADR y abre /alertas?new=GGAL&ccy=USD
// (alertaDePosicion.linkDeAlerta). Por eso se mira la moneda DEL LINK, no la
// del formulario, que arranca en dólares para cualquier código sin '.BA'.
// «¿Es acción argentina?» es LA regla de lo que no tenés (`esLocalSinTenencia`,
// la de la ficha, Tu lista y las alertas técnicas): al juntar (30/10) esta
// función traía la suya (`isArStock`, otra lista).
export function simboloDelAviso(symbol, monedaDelLink) {
  const s = String(symbol || '').trim().toUpperCase()
  if (!s || s.endsWith('.BA') || s.startsWith('FCI:')) return s
  if (String(monedaDelLink || '').toUpperCase() === 'USD') return s
  return esLocalSinTenencia(s) ? `${s}.BA` : s
}

export function monedaDe(symbol) {
  return String(symbol || '').toUpperCase().endsWith('.BA') ? 'ARS' : 'USD'
}

// Un aviso de precio de un CEDEAR en DÓLARES (AAPL en la Bolsa como AAPLD): se
// guarda 'AAPL.BA' + currency 'USD' y el servidor lo mira con el precio en
// dólares (alerts_engine.cedear_en_dolares — la misma regla, del otro lado).
export function esCedearEnDolares(a) {
  return !!a && a.kind === 'price_target' && (a.scope || 'ticker') === 'ticker'
    && String(a.symbol || '').toUpperCase().endsWith('.BA')
    && String(a.currency || '').toUpperCase() === 'USD'
}

// Con qué clave buscar el precio de ahora de un aviso: el mismo CEDEAR tiene
// un precio en pesos y otro en dólares.
export function claveDePrecio(a) {
  const s = String(a?.symbol || '').toUpperCase()
  return esCedearEnDolares(a) ? `${s}|USD` : s
}

// En qué monedas se puede marcar el precio de un activo — la regla del
// servidor (main._moneda_del_aviso): la moneda tiene que ser una que el activo
// TIENE, no un rótulo. `dolares` = dolaresPorSimbolo(…) (Map), `undefined`
// mientras carga, `null` si no llegó: en esos dos casos un CEDEAR conserva los
// dólares (decide el servidor) en vez de borrar la elección de la persona.
export function monedasPosibles(symbol, dolares) {
  const s = String(symbol || '').toUpperCase()
  if (!s) return ['ARS', 'USD']
  if (s.startsWith('FCI:')) return ['ARS', 'USD']   // los hay en pesos y en dólares
  if (!s.endsWith('.BA')) return ['USD']
  if (dolares instanceof Map) return dolares.has(s) ? ['ARS', 'USD'] : ['ARS']
  return ['ARS', 'USD']
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
//   { quien: 'AAPL', que: 'pasa para arriba su promedio de 200 días' }
//   { quien: 'AAPL', que: 'la fuerza (RSI) baja de 30', sep: ': ' }
// `sep` = lo que va entre las dos mitades cuando no es un espacio.
export function frase(a) {
  if (!a) return { quien: '', que: '' }
  if (a.kind === 'tecnica') {
    const quien = quienTecnico(a)
    if (a.senal === 'linea') return { quien, que: `toca ${nombreDeLinea(a)}` }
    return esRsi(a.senal)
      ? { quien, que: `la fuerza (RSI) ${queTecnico(a.senal, a.direction, false)}`, sep: ': ' }
      : { quien, que: queTecnico(a.senal, a.direction, false) }
  }
  if (a.kind === 'price_target') {
    const verbo = a.direction === 'below' ? 'baja a' : 'sube a'
    // «AAPL (CEDEAR)»: sin eso, el CEDEAR en dólares y la acción de Nasdaq se
    // leen igual («AAPL sube a US$ …») y son precios 15 veces distintos.
    const quien = esCedearEnDolares(a) ? `${simbolo(a.symbol)} (CEDEAR)` : simbolo(a.symbol)
    return { quien, que: `${verbo} ${fmtPrecio(a.threshold, a.currency)}` }
  }
  const cartera = a.scope === 'holdings'
  const partes = []
  if (Number(a.up_pct) > 0) partes.push(`sube ${fmtPct(a.up_pct)} %`)
  if (Number(a.down_pct) > 0) partes.push(`cae ${fmtPct(a.down_pct)} %`)
  const mov = partes.join(' o ') || 'se mueve'
  const cuando = !cartera && a.baseline === 'set_price' ? 'desde que la armé' : 'en el día'
  return cartera
    ? { quien: 'Mi cartera', que: `algo ${mov} ${cuando}`, sep: ': ' }
    : { quien: simbolo(a.symbol), que: `${mov} ${cuando}` }
}

// La confirmación del formulario: la frase de arriba contada en segunda persona.
export function confirmacion(a) {
  if (a.kind === 'tecnica') {
    if (!a.symbol || !a.senal) return null
    const quien = quienTecnico(a)
    if (a.senal === 'linea') return `Te avisamos cuando ${quien} toque ${nombreDeLinea(a)}. Lo miramos cada día con el precio más alto y el más bajo del día.`
    const que = esRsi(a.senal)
      ? `la fuerza (RSI) de ${quien} ${queTecnico(a.senal, a.direction, true)}`
      : `${quien} ${queTecnico(a.senal, a.direction, true)}`
    return `Te avisamos cuando ${que}. Lo miramos cada día con el precio de cierre.`
  }
  if (a.kind === 'price_target') {
    if (!a.symbol || !(Number(a.threshold) > 0)) return null
    const quien = esCedearEnDolares(a) ? `el CEDEAR de ${simbolo(a.symbol)} en dólares` : simbolo(a.symbol)
    return `Te avisamos cuando ${quien} ${a.direction === 'below' ? 'baje' : 'suba'} a ${fmtPrecio(a.threshold, a.currency)}.`
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
  if (a.kind === 'tecnica') {
    if (avisoHoy) return { texto: `Hoy avisó: ${ultimo.message}`, tono: 'aviso' }
    return { texto: ultimo ? `Último aviso el ${fechaCorta(ultimo.fired_at)} · se mira cada día con el cierre` : 'Se mira cada día con el precio de cierre', tono: 'normal' }
  }
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
