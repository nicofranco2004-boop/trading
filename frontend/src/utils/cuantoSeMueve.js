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
 * El % entre los cierres de dos días y cuántos días de mercado pasaron, sobre
 * los puntos DIARIOS del gráfico (aunque se esté mirando en velas semanales).
 * El orden en que se tocaron no importa: siempre del más viejo al más nuevo.
 * null si falta alguno.
 */
export function medicion(puntos = [], fechaA, fechaB) {
  if (!fechaA || !fechaB) return null
  const ia = puntos.findIndex(p => p.d === fechaA)
  const ib = puntos.findIndex(p => p.d === fechaB)
  if (ia < 0 || ib < 0) return null
  const [i, j] = ia <= ib ? [ia, ib] : [ib, ia]
  const a = puntos[i], b = puntos[j]
  if (!(a.c > 0) || b.c == null) return null
  return { desde: a.d, hasta: b.d, precioDesde: a.c, precioHasta: b.c, pct: (b.c / a.c - 1) * 100, dias: j - i }
}

export function textoMedicion(m) {
  if (!m) return ''
  if (m.dias === 0) return 'Es el mismo día: tocá otro.'
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
    lineas.push(`Pagó ${e.moneda === 'ars' ? '$' : 'US$'} ${m} por acción.`)
  }
  lineas.push('Desde el día de corte, el que compra ya no cobra ese pago.')
  if (mov) lineas.push(`Ese día el precio: ${mov}`)
  return { titulo: `Dividendo · día de corte ${fechaCorta(e.fecha)}`, lineas }
}

/**
 * El globo de varias marcas juntas (en el celular, o con dividendos todos los
 * meses, se pisaban): un renglón por cada una, del más viejo al más nuevo. Con
 * una sola, el globo de siempre (`textoEvento`).
 */
export function textoGrupo(eventos = []) {
  if (eventos.length === 1) return textoEvento(eventos[0])
  const balances = eventos[0]?.tipo === 'balance'
  const lineas = eventos.map(e => {
    const r = e.reaccion ? pctConSigno(e.reaccion.pct) : null
    if (balances) {
      const cuando = e.momento === 'despues_del_cierre' ? 'al otro día' : e.momento === 'antes_del_cierre' ? 'ese día' : 'en dos días'
      return `${fechaCorta(e.fecha)}: ${r ? `${cuando} ${r}` : 'sin precio para comparar'}`
    }
    const monto = e.monto > 0
      ? `pagó ${e.moneda === 'ars' ? '$' : 'US$'} ${e.monto.toLocaleString('es-AR', { maximumSignificantDigits: 4 })}`
      : 'dividendo'
    return `${fechaCorta(e.fecha)}: ${monto}${r ? ` · ese día ${r}` : ''}`
  })
  if (!balances) lineas.push('Por acción. Desde el día de corte, el que compra ya no cobra ese pago.')
  return { titulo: `${eventos.length} ${balances ? 'balances' : 'dividendos'}`, lineas }
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
 */
export function tarjetasMovimiento(m, { moneda = 'usd', precio = String, tenencia = null, peso = null } = {}) {
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
    const deCuando = dm.anio_completo ? 'el máximo del año' : 'el máximo del período'
    out.push({
      id: 'desde_maximo', titulo: 'Caída desde el máximo', tono: enMaximo ? 'neutro' : 'neg',
      veredicto: enMaximo ? 'En su máximo' : pctConSigno(dm.pct),
      texto: enMaximo ? `Hoy cerró en ${deCuando}.` : `Hoy, contra ${deCuando} (${precio(dm.maximo)}).`,
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
    out.push({ id: 'dia', titulo: 'Un día normal', tono: 'neutro', veredicto: `±${num1(d.desvio_pct)}%`, texto: partes.join(' ') })

    if (tenencia?.valor > 0) {
      const mueve = -tenencia.valor * d.desvio_pct / 100
      const partesT = [`Lo que te mueve un día malo normal de este papel (una baja de ${num1(d.desvio_pct)}%).`]
      if (peso > 0 && peso <= 1) {
        partesT.push(`Es el ${Math.round(peso * 100).toLocaleString('es-AR')}% de tu cartera: a toda tu cartera ese día la mueve ${pctConSigno(-peso * d.desvio_pct)}.`)
      }
      out.push({ id: 'cartera', titulo: 'En tu cartera', tono: 'neutro', veredicto: plata(mueve, moneda), texto: partesT.join(' ') })
    }
  }
  return out
}

function diasEntre(a, b) {
  return Math.round((Date.parse(b + 'T12:00:00Z') - Date.parse(a + 'T12:00:00Z')) / 86400000)
}

/** La foto de la cartera más nueva que sirve como medición (`apto`) con valor.
 *  Por FECHA, no por el orden de la lista: el servidor las manda de la más vieja
 *  a la más nueva y el demo al revés. */
export function ultimaFotoApta(fotos = []) {
  let mejor = null
  for (const f of fotos || []) {
    if (f?.apto && f.total_value > 0 && (!mejor || String(f.date) > String(mejor.date))) mejor = f
  }
  return mejor
}
