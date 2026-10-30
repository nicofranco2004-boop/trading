// cuantoSeMueve.js — las palabras de «Cuánto se mueve este papel», de los globos de
// balances y dividendos del gráfico, y la medición entre dos puntos.
// ════════════════════════════════════════════════════════════════════════════
// Los NÚMEROS de «Cuánto se mueve» (peor caída, un día normal, el S&P 500) y lo
// que se movió el precio con cada balance o dividendo vienen hechos del servidor
// (backend/movimiento.py), sobre la misma serie del gráfico. Acá sólo se dicen
// en castellano. Son datos de lo que YA pasó, nunca pronósticos: la verificación
// del 23/10 mostró que los indicadores no anticipan mejor que el azar.
//
// Lo único que se cuenta acá es la medición entre dos días que toca la persona
// (sobre los mismos puntos que dibuja el gráfico) y lo que te toca a vos de un
// día malo normal (tu tenencia la sabe la ficha, no el servidor).
import { OCULTO, AVISO_OCULTO } from './ocultarSaldos'
import { esElDeTuCartera } from './parteDeTuPlata'

const NUM1 = { minimumFractionDigits: 1, maximumFractionDigits: 1 }
const num1 = (v) => Math.abs(v).toLocaleString('es-AR', NUM1)
/** «+10,1%» · «−4,2%» (el menos de verdad, no el guion). */
export const pctConSigno = (v) => `${v >= 0 ? '+' : '−'}${num1(v)}%`

export function fechaCorta(iso) {
  if (!iso) return ''
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y.slice(2)}`
}

/** Plata redonda: «US$ 85» · «$ 120.000». */
export function plata(x, moneda) {
  const n = Math.round(Math.abs(x)).toLocaleString('es-AR')
  return `${x < 0 ? '−' : ''}${moneda === 'ars' ? '$' : 'US$'} ${n}`
}

/** Días corridos dichos como se dicen: «12 días», «7 meses», «1 año y 2 meses». */
export function duracion(dias) {
  if (dias < 45) return `${dias} día${dias === 1 ? '' : 's'}`
  const meses = Math.round(dias / 30.44)
  if (meses < 12) return `${meses} meses`
  const a = Math.floor(meses / 12), m = meses % 12
  return `${a} año${a > 1 ? 's' : ''}${m ? ` y ${m} mes${m > 1 ? 'es' : ''}` : ''}`
}

// ─── «Desde que lo tenés» ───────────────────────────────────────────────────

/** La fecha de tu primera compra de lo que tenés hoy (el lote abierto más viejo). */
export function primeraCompra(lotes = []) {
  let f = null
  for (const l of lotes) {
    if (l.is_cash || !(Number(l.quantity) > 0) || !l.entry_date) continue
    const d = String(l.entry_date).slice(0, 10)
    if (!f || d < f) f = d
  }
  return f
}

/** Cuántos de los últimos puntos van desde `fecha` (incluida). Si la fecha es
 *  anterior al primer punto, todos. */
export function puntosDesde(puntos = [], fecha) {
  if (!fecha) return 0
  let n = 0
  for (let i = puntos.length - 1; i >= 0 && puntos[i].d >= fecha; i--) n++
  return n
}

// ─── Medir entre dos puntos ─────────────────────────────────────────────────

/**
 * Medir entre dos puntos CUALESQUIERA del gráfico, como la regla de
 * TradingView (Nico, 24/10: «no me tendría que obligar a elegir el cierre de
 * las velas»). Cada punto es { i, precio }: `i` es el día de mercado contado
 * sobre los puntos DIARIOS del gráfico (aunque se miren velas semanales) y
 * puede pasar del último día —el espacio vacío de la derecha, para medir hacia
 * adelante—; `precio`, la altura donde se tocó, no el cierre.
 * El orden en que se tocaron no importa: siempre del de la izquierda al de la
 * derecha (a igual día, del primero tocado). null si falta alguno.
 * Devuelve { desde, hasta (fecha, o null si es hacia adelante), adelanteDesde,
 * adelanteHasta (cuántos días de mercado después del último), precioDesde,
 * precioHasta, diferencia, pct, dias }.
 */
export function medicion(puntos = [], a, b) {
  if (!a || !b || !(puntos.length > 0)) return null
  const [x, y] = b.i < a.i ? [b, a] : [a, b]
  if (!(x.precio > 0) || !(y.precio > 0)) return null
  const ultimo = puntos.length - 1
  const fecha = (p) => (p.i >= 0 && p.i <= ultimo ? puntos[p.i].d : null)
  return {
    desde: fecha(x), hasta: fecha(y),
    adelanteDesde: Math.max(0, x.i - ultimo), adelanteHasta: Math.max(0, y.i - ultimo),
    precioDesde: x.precio, precioHasta: y.precio, diferencia: y.precio - x.precio,
    pct: (y.precio / x.precio - 1) * 100, dias: y.i - x.i,
  }
}

export function textoMedicion(m) {
  if (!m) return ''
  if (m.dias === 0) return m.diferencia === 0 ? 'Es el mismo punto: tocá otro.' : `${pctConSigno(m.pct)} en el mismo día`
  return `${pctConSigno(m.pct)} en ${m.dias} día${m.dias === 1 ? '' : 's'} de mercado`
}

// ─── Balances y dividendos ──────────────────────────────────────────────────

/**
 * El globo de un balance o un dividendo: { titulo, lineas: [...] }.
 *   · balance: cuándo lo presentó y cuánto se movió el precio con eso;
 *   · dividendo: cuánto pagó por acción y cuánto se movió el día de corte.
 */
export function textoEvento(e) {
  const r = e.reaccion
  const mov = r ? pctConSigno(r.pct) : null
  if (e.tipo === 'balance') {
    const lineas = []
    // Lo declarado contra lo esperado (Nico, 29/10): la ganancia por acción
    // (lo que ganó la empresa en el trimestre, dividido por sus acciones).
    const eps = textoGananciaPorAccion(e)
    if (eps) lineas.push(eps)
    if (e.momento === 'despues_del_cierre') {
      lineas.push('Lo presentó con el mercado ya cerrado.')
      lineas.push(mov ? `Al otro día el precio: ${mov}` : 'Todavía no hay precio del día siguiente.')
    } else if (e.momento === 'antes_del_cierre') {
      lineas.push('Lo presentó antes del cierre de ese día.')
      lineas.push(mov ? `Ese día el precio: ${mov}` : 'No hay precio de ese día.')
    } else {
      lineas.push(mov ? `Entre ese día y el siguiente, el precio: ${mov}` : 'No hay precio de esos días.')
    }
    return { titulo: `Balance del ${fechaCorta(e.fecha)}`, lineas }
  }
  const lineas = []
  if (e.monto > 0) {
    const m = e.monto.toLocaleString('es-AR', { maximumSignificantDigits: 4 })
    // Qué parte del precio de ese día fue (sólo si el precio está en la misma
    // moneda que el dividendo: si no, sería mezclar pesos con dólares).
    const parte = e.rendimiento > 0 ? `: el ${pctSinSigno(e.rendimiento)} de lo que valía la acción ese día` : ''
    lineas.push(`Pagó ${e.moneda === 'ars' ? '$' : 'US$'} ${m} por acción${parte}.`)
    if (e.anterior > 0) lineas.push(comparadoConElAnterior(e.monto, e.anterior, e.moneda))
  }
  lineas.push('Desde el día de corte, el que compra ya no cobra ese pago.')
  if (mov) lineas.push(`Ese día el precio: ${mov}`)
  return { titulo: `Dividendo · día de corte ${fechaCorta(e.fecha)}`, lineas }
}

// Con centavos (los dividendos y la ganancia por acción son de centavos; `plata` redondea).
const centavos = (x, moneda) => `${moneda === 'ars' ? '$' : 'US$'} ${Math.abs(x).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const pctSinSigno = (x) => `${Math.abs(x).toLocaleString('es-AR', { maximumFractionDigits: Math.abs(x) < 1 ? 2 : 1 })}%`
// «una ganancia de US$ 1,65» o «una pérdida de US$ 0,12».
const resultado = (x, moneda) => (x < 0 ? `una pérdida de ${centavos(x, moneda)}` : `una ganancia de ${centavos(x, moneda)}`)

/**
 * La línea de lo declarado contra lo esperado de un balance, o null si no se
 * sabe. «Declaró una ganancia de US$ 1,65 por acción; se esperaba US$ 1,50:
 * 10% más de lo esperado.» Describe lo que pasó; no anticipa nada.
 */
export function textoGananciaPorAccion(e) {
  const dec = e.eps_declarado, esp = e.eps_esperado
  if (dec == null && esp == null) return null
  if (dec == null) return `Se esperaba ${resultado(esp, e.moneda)} por acción.`
  if (esp == null) return `Declaró ${resultado(dec, e.moneda)} por acción.`
  const sorpresa = e.sorpresa_pct != null ? e.sorpresa_pct : (esp !== 0 ? ((dec - esp) / Math.abs(esp)) * 100 : null)
  const cuanto = sorpresa == null || Math.abs(sorpresa) < 0.5 ? 'lo mismo que se esperaba'
    : `${pctSinSigno(sorpresa)} ${sorpresa > 0 ? 'más' : 'menos'} de lo esperado`
  return `Declaró ${resultado(dec, e.moneda)} por acción; se esperaba ${centavos(esp, e.moneda)}${esp < 0 ? ' de pérdida' : ''}: ${cuanto}.`
}

/** «El anterior: US$ 0,24 (este es 8% más).» */
function comparadoConElAnterior(monto, anterior, moneda) {
  const dif = ((monto - anterior) / anterior) * 100
  if (Math.abs(dif) < 0.5) return `Igual que el anterior (${centavos(anterior, moneda)}).`
  return `El anterior: ${centavos(anterior, moneda)} (este es ${pctSinSigno(dif)} ${dif > 0 ? 'más' : 'menos'}).`
}

/**
 * El globo de varias marcas juntas (en el celular, o con dividendos todos los
 * meses, se pisaban): un renglón por cada una, del más viejo al más nuevo. Con
 * una sola, el globo de siempre (`textoEvento`).
 */
export function textoGrupo(eventos = []) {
  if (eventos.length === 1) return textoEvento(eventos[0])
  // Balances y dividendos pueden ir juntos en una marca (una sola fila sobre
  // las fechas): cada renglón dice el suyo.
  const tipos = new Set(eventos.map(e => e.tipo))
  const lineas = eventos.map(e => {
    const r = e.reaccion ? pctConSigno(e.reaccion.pct) : null
    if (e.tipo === 'balance') {
      const cuando = e.momento === 'despues_del_cierre' ? 'al otro día' : e.momento === 'antes_del_cierre' ? 'ese día' : 'en dos días'
      const sorpresa = e.sorpresa_pct != null && Math.abs(e.sorpresa_pct) >= 0.5
        ? ` · ${pctSinSigno(e.sorpresa_pct)} ${e.sorpresa_pct > 0 ? 'más' : 'menos'} de lo esperado` : ''
      const quien = tipos.size > 1 ? 'balance · ' : ''   // sólo si hay de los dos tipos en la marca
      return `${fechaCorta(e.fecha)}: ${quien}${r ? `${cuando} ${r}` : 'sin precio para comparar'}${sorpresa}`
    }
    const monto = e.monto > 0
      ? `pagó ${e.moneda === 'ars' ? '$' : 'US$'} ${e.monto.toLocaleString('es-AR', { maximumSignificantDigits: 4 })}`
      : 'dividendo'
    return `${fechaCorta(e.fecha)}: ${monto}${r ? ` · ese día ${r}` : ''}`
  })
  if (tipos.has('dividendo')) lineas.push('Por acción. Desde el día de corte, el que compra ya no cobra ese pago.')
  const titulo = tipos.size > 1 ? `${eventos.length} balances y dividendos`
    : `${eventos.length} ${tipos.has('balance') ? 'balances' : 'dividendos'}`
  return { titulo, lineas }
}

// ─── «Cuánto se mueve este papel» ───────────────────────────────────────────

/**
 * Las tarjetas de la sección, en la moneda del gráfico: [{ id, titulo,
 * veredicto, tono, texto }].
 *   · `m`: el `movimiento` de GET /api/tecnico (backend/movimiento.py).
 *   · `precio(x)`: el formato de precio del gráfico (US$ / $).
 *   · `tenencia`: { valor } lo que vale hoy lo tuyo, en la moneda del gráfico;
 *     null si no lo tenés.
 *   · `peso`: qué parte de tu cartera es (0 a 1); null si no se sabe.
 *   · `oculto`: «Ocultar saldos» prendido. Ni lo que te mueve en plata ni qué
 *     parte de tu cartera es (ni el % que mueve a toda la cartera, que con el
 *     del día normal deja sacar el peso): auditorías A3/D4, 29/10.
 */
export function tarjetasMovimiento(m, { moneda = 'usd', precio = String, tenencia = null, peso = null, oculto = false } = {}) {
  if (!m?.disponible) return []
  const out = []

  const c = m.peor_caida
  if (c) {
    const vuelta = c.volvio
      ? `Desde ese piso tardó ${duracion(diasEntre(c.piso.fecha, c.volvio))} (${c.dias_para_volver} días de mercado) en volver a ${precio(c.pico.precio)}.`
      : `Todavía no volvió a ${precio(c.pico.precio)}.`
    out.push({
      id: 'caida', titulo: 'Su peor caída', tono: 'neg', veredicto: pctConSigno(c.pct),
      texto: `De ${precio(c.pico.precio)} el ${fechaCorta(c.pico.fecha)} a ${precio(c.piso.precio)} el ${fechaCorta(c.piso.fecha)}. ${vuelta}`,
    })
  } else {
    out.push({ id: 'caida', titulo: 'Su peor caída', tono: 'neutro', veredicto: 'No tuvo',
      texto: 'En este período nunca cerró por debajo de un máximo anterior.' })
  }

  const dm = m.desde_el_maximo
  if (dm && dm.pct != null) {
    const enMaximo = dm.pct >= -0.1
    // Es el CIERRE más alto (la lectura técnica): Fibonacci, en el gráfico, dice
    // «lo más alto que llegó» con el pico de adentro del día, que puede ser otro
    // número. Cada uno dice cuál es (auditoría A 29/10, A5/D10).
    const deCuando = dm.anio_completo ? 'el cierre más alto del año' : 'el cierre más alto del período'
    const elMasAlto = dm.anio_completo ? 'el más alto del año' : 'el más alto del período'
    out.push({
      id: 'desde_maximo', titulo: 'Caída desde el máximo', tono: enMaximo ? 'neutro' : 'neg',
      veredicto: enMaximo ? 'En su máximo' : pctConSigno(dm.pct),
      // Del último cierre, con su fecha (auditoría D5): no es el precio en vivo.
      texto: m.hasta
        ? (enMaximo ? `El ${fechaCorta(m.hasta)} tuvo ${deCuando}.` : `Al cierre del ${fechaCorta(m.hasta)}, contra ${deCuando} (${precio(dm.maximo)}).`)
        : (enMaximo ? `Su último cierre fue ${elMasAlto}.` : `En el último cierre, contra ${deCuando} (${precio(dm.maximo)}).`),
    })
  }

  const d = m.dia_normal
  if (d) {
    const partes = [`Es lo que sube o baja en un día típico.`]
    if (d.sp500_desvio_pct != null && d.veces_el_sp500 != null) {
      const v = d.veces_el_sp500
      const cuanto = v >= 1.15 ? `se mueve ${v.toLocaleString('es-AR', { maximumFractionDigits: 1 })} veces lo que el S&P 500`
        : v <= 0.87 ? 'se mueve menos que el S&P 500' : 'se mueve parecido al S&P 500'
      partes.push(`El S&P 500 (las 500 empresas más grandes de EE.UU.) se mueve ±${num1(d.sp500_desvio_pct)}% en ${moneda === 'ars' ? 'pesos' : 'dólares'}: este papel ${cuanto}.`)
    }
    if (d.dias_malos > 0) {
      const cada = Math.round(d.dias / d.dias_malos)
      partes.push(`Bajó ${num1(d.desvio_pct)}% o más en 1 de cada ${cada} días de mercado.`)
    }
    // Del último año, como «su día normal del último año» de la tarjeta «Cuánto
    // se mueve»: es el MISMO número (movimiento.dia_normal usa la cuenta de la
    // lectura), aunque el resto de esta sección mire 2 años (A5, 29/10).
    out.push({ id: 'dia', titulo: 'Un día normal del último año', tono: 'neutro', veredicto: `±${num1(d.desvio_pct)}%`, texto: partes.join(' ') })

    if (tenencia?.valor > 0) {
      const mueve = -tenencia.valor * d.desvio_pct / 100
      const partesT = [`Lo que te mueve un día malo normal de este papel (una baja de ${num1(d.desvio_pct)}%).`]
      if (oculto) {
        out.push({ id: 'cartera', titulo: 'En tu cartera', tono: 'neutro', veredicto: OCULTO, texto: `${partesT[0]} ${AVISO_OCULTO}` })
      } else if (peso > 0 && peso <= 1) {
        partesT.push(`${esElDeTuCartera(peso * 100)}: a toda tu cartera ese día la mueve ${pctConSigno(-peso * d.desvio_pct)}.`)
      }
      if (!oculto) out.push({ id: 'cartera', titulo: 'En tu cartera', tono: 'neutro', veredicto: plata(mueve, moneda), texto: partesT.join(' ') })
    }
  }
  return out
}

function diasEntre(a, b) {
  return Math.round((Date.parse(b + 'T12:00:00Z') - Date.parse(a + 'T12:00:00Z')) / 86400000)
}
