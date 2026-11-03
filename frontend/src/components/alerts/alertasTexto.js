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
  { id: 'rsi_bajo_30', texto: 'Su impulso (RSI) baje de 30', tarjeta: 'rsi' },
  { id: 'rsi_sobre_70', texto: 'Su impulso (RSI) supere 70', tarjeta: 'rsi' },
  { id: 'rsi_sube_30', texto: 'Su impulso (RSI) vuelva a superar 30', tarjeta: 'rsi' },
  { id: 'rsi_baja_70', texto: 'Su impulso (RSI) vuelva a quedar debajo de 70', tarjeta: 'rsi' },
  { id: 'maximo_12m', texto: 'Cierre en su máximo del año', tarjeta: 'maximo' },
]
export const conSentido = (senal) => !!SENALES_TECNICAS.find(s => s.id === senal)?.conSentido

// Tu línea del gráfico (senal 'linea', Nico 28/10): no es una señal de la
// lista, se pide desde la línea elegida (o, en Alertas, eligiéndola de tus
// dibujos). Una horizontal, una de tendencia o (29/10) un canal. De qué tipo es
// lo dice el borrador (`tipoLinea`) o, en una alerta guardada, su referencia
// al dibujo (`dibujo`, el JSON que guarda main._crear_alerta_de_linea).
function referenciaDeLinea(a) {
  try {
    const r = JSON.parse(a?.dibujo || 'null')
    return r && typeof r === 'object' ? r : null
  } catch { return null }
}
export function tipoDeLinea(a) {
  if (a?.tipoLinea) return a.tipoLinea
  return referenciaDeLinea(a)?.tipo || null
}
/** El id de tu dibujo: el del borrador (`dibujo` ya es el id) o el de la referencia guardada. */
export function idDeLinea(a) {
  return referenciaDeLinea(a)?.id || (typeof a?.dibujo === 'string' && !a.dibujo.startsWith('{') ? a.dibujo : null)
}
/** El activo como lo guarda la ficha (la clave de tus dibujos), de una alerta guardada. */
export function assetDeLinea(a) {
  return referenciaDeLinea(a)?.asset || null
}
/** Un canal: cuándo cuenta salir. 'toque' (lo toca o lo pasa en el día) o 'cierre' (cierra afuera). */
export function modoDeCanal(a) {
  return (a?.modo || referenciaDeLinea(a)?.modo) === 'cierre' ? 'cierre' : 'toque'
}
const NOMBRE_LINEA = { tendencia: 'tu línea de tendencia', canal: 'tu canal' }
const nombreDeLinea = (a) => NOMBRE_LINEA[tipoDeLinea(a)] || 'tu línea horizontal'
const esCanal = (a) => tipoDeLinea(a) === 'canal'
/** Por qué borde sale el canal, dicho corto: «por cualquier borde», «por arriba». */
export const POR_BORDE = { either: 'por cualquier borde', above: 'por arriba', below: 'por abajo' }
/** «Toque tu línea horizontal» o «Salga de tu canal», para el formulario. */
export const textoDeLinea = (a) => (esCanal(a) ? 'Salga de tu canal' : `Toque ${nombreDeLinea(a)}`)

/** ¿Ya hay un aviso activo de esta línea tuya (`dibujo`: su id)? La referencia
 *  la guarda main._crear_alerta_de_linea: { asset, moneda, id, tipo }. */
export function alertaDeLinea(items = [], { asset, moneda = 'usd', dibujo }) {
  const sym = String(asset || '').toUpperCase()
  const mon = moneda === 'ars' ? 'ars' : 'usd'
  return items.find(a => {
    if (a.kind !== 'tecnica' || a.senal !== 'linea' || !a.active) return false
    const r = referenciaDeLinea(a)
    return r?.id === dibujo && r?.asset === sym && r?.moneda === mon
  }) || null
}

// Qué pasa, en presente («pasa para arriba su promedio de 200 días») o en
// subjuntivo para la confirmación («cuando pase para arriba…»).
function queTecnico(senal, direction, subj) {
  const v = (pres, sub) => (subj ? sub : pres)
  if (senal === 'media200' || senal === 'media50') {
    const dias = senal === 'media200' ? 200 : 50
    if (direction === 'above') return `${v('supera', 'supere')} su promedio de ${dias} días`
    if (direction === 'below') return `${v('cae', 'caiga')} por debajo de su promedio de ${dias} días`
    return `${v('cruza', 'cruce')} su promedio de ${dias} días`
  }
  if (senal === 'rsi_bajo_30') return `${v('baja', 'baje')} de 30`
  if (senal === 'rsi_sobre_70') return `${v('supera', 'supere')} 70`
  if (senal === 'rsi_sube_30') return `${v('vuelve', 'vuelva')} a superar 30`
  if (senal === 'rsi_baja_70') return `${v('vuelve', 'vuelva')} a quedar debajo de 70`
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
    if (a.senal === 'linea' && esCanal(a)) {
      const borde = POR_BORDE[a.direction] || POR_BORDE.either
      return { quien, que: `${modoDeCanal(a) === 'cierre' ? 'cierra afuera de tu canal' : 'sale de tu canal'}, ${borde}` }
    }
    if (a.senal === 'linea') return { quien, que: `toca ${nombreDeLinea(a)}` }
    return esRsi(a.senal)
      ? { quien, que: `el impulso (RSI) ${queTecnico(a.senal, a.direction, false)}`, sep: ': ' }
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

// Tus líneas (y un canal en modo «si lo toca») se miran también durante la
// rueda, en cada pasada del cron de alertas (alerts_engine._evaluar_en_la_rueda).
const EN_LA_RUEDA = 'Lo miramos durante la rueda, cada 10 minutos'

// La confirmación del formulario: la frase de arriba contada en segunda persona.
export function confirmacion(a) {
  if (a.kind === 'tecnica') {
    if (!a.symbol || !a.senal) return null
    const quien = quienTecnico(a)
    if (a.senal === 'linea' && esCanal(a)) {
      const inclinado = 'Los bordes de un canal inclinado cambian de precio cada día: miramos dónde está cada uno ese día.'
      if (modoDeCanal(a) === 'cierre') {
        const lado = a.direction === 'above' ? ', por arriba' : a.direction === 'below' ? ', por abajo' : ''
        return `Te avisamos cuando ${quien} cierre afuera de tu canal${lado}. ${inclinado} Lo miramos cada día con el precio de cierre: te llega a la mañana siguiente.`
      }
      const bordes = a.direction === 'above' ? 'el borde de arriba' : a.direction === 'below' ? 'el borde de abajo' : 'cualquiera de los dos bordes'
      return `Te avisamos cuando ${quien} toque o pase ${bordes} de tu canal. ${inclinado} ${EN_LA_RUEDA}: si lo toca, te llega ese mismo día.`
    }
    if (a.senal === 'linea') return `Te avisamos cuando ${quien} toque ${nombreDeLinea(a)}. ${EN_LA_RUEDA}: si la toca, te llega ese mismo día.`
    const que = esRsi(a.senal)
      ? `el impulso (RSI) de ${quien} ${queTecnico(a.senal, a.direction, true)}`
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
// `linea`: el de una línea tuya, lo que dice GET /api/alerts/lineas (dónde está
// hoy la línea y el último cierre), o undefined mientras no llegó.
export function estado(a, precio, eventos = [], hoy = '', linea = undefined) {
  if (a.kind === 'tecnica' && a.senal === 'linea' && linea?.borrada) {
    return { texto: 'Se apagó: borraste la línea del gráfico', tono: 'apagada', borrada: true }
  }
  if (!a.active) {
    // Una alerta de «una sola vez» que ya avisó: el motor la apaga sola.
    if (a.repeat === 'once' && a.last_fired_at) return { texto: `Cumplida el ${fechaCorta(a.last_fired_at)}`, tono: 'apagada' }
    return { texto: 'Pausada', tono: 'apagada' }
  }
  const ultimo = eventos.find(e => e.alert_id === a.id)
  const avisoHoy = ultimo && hoy && diaArgentina(ultimo.fired_at) === hoy
  if (a.kind === 'tecnica') {
    if (avisoHoy) return { texto: `Hoy avisó: ${ultimo.message}`, tono: 'aviso' }
    if (a.senal === 'linea') {
      const donde = dondeEstaLaLinea(a, linea)
      if (donde) return { texto: donde, tono: 'normal' }
      // Tus líneas se miran durante la rueda (salvo un canal que pide «cierra
      // afuera», que espera el cierre): decir «con el cierre» era otra regla.
      const como = esCanal(a) && modoDeCanal(a) === 'cierre' ? 'cada día con el precio de cierre' : 'durante la rueda, cada 10 minutos'
      return { texto: ultimo ? `Último aviso el ${fechaCorta(ultimo.fired_at)} · se mira ${como}` : `Se mira ${como}`, tono: 'normal' }
    }
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

// «Está en US$ 187,60 · adentro, a 3,3 % del borde de arriba» / «· le falta
// 4,2 %»: dónde está el precio contra tu línea hoy (con el último cierre
// guardado, el mismo que mira el aviso). null si todavía no hay con qué decirlo.
export function dondeEstaLaLinea(a, linea) {
  const ult = Number(linea?.ultimo)
  const hoy = linea?.hoy
  if (!(ult > 0) || !Array.isArray(hoy) || hoy.some(x => x == null)) return null
  const ccy = String(a.currency || '').toUpperCase() === 'ARS' ? 'ARS' : 'USD'
  const esta = `Está en ${fmtPrecio(ult, ccy)}`
  const dist = (nivel) => fmtPct(Math.abs((nivel / ult - 1) * 100))
  if (linea.tipo === 'canal' && hoy.length === 2) {
    const [abajo, arriba] = hoy
    // Sólo dónde está: si ya salió, el aviso de la mañana lo puede estar por
    // mandar (llega desde las 9); prometer «la próxima vez» mentía (auditoría 29/10).
    if (ult > arriba) return `${esta} · afuera del canal, por arriba`
    if (ult < abajo) return `${esta} · afuera del canal, por abajo`
    // Un borde de abajo en cero o menos no existe: el precio no llega ahí.
    const hayAbajo = abajo > 0
    const lado = a.direction === 'above' || !hayAbajo ? 'arriba' : a.direction === 'below' ? 'abajo'
      : arriba - ult <= ult - abajo ? 'arriba' : 'abajo'
    return `${esta} · adentro, a ${dist(lado === 'arriba' ? arriba : abajo)} % del borde de ${lado}`
  }
  const nivel = hoy[0]
  if (!(nivel > 0)) return null
  if (Math.abs(nivel / ult - 1) < 0.0005) return `${esta} · justo en tu línea`
  return `${esta} · le falta ${dist(nivel)} %`
}

export function canal(ch) {
  return ch === 'push' ? 'Por celular' : ch === 'email' ? 'Por mail' : 'Por mail y celular'
}
