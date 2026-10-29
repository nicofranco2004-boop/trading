// fibonacci.js — las palabras del Fibonacci automático de la ficha.
// ════════════════════════════════════════════════════════════════════════════
// Las CUENTAS (picos, pozos, tramos, rupturas y niveles) vienen hechas de
// GET /api/tecnico en el campo `fibonacci` (backend/estructura.py). Acá sólo se
// dicen en castellano y se decide qué rótulo del gráfico entra.
//
// El tono es el del resto del análisis técnico (Nico, 22/10: «claro, conciso,
// del día a día, sin tecnicismos que no sirven»): «días de mercado» y no
// «ruedas», cada nivel dicho por lo que significa para quien mira («hasta dónde
// podría volver a bajar antes de seguir subiendo») y el porcentaje como dato al
// lado, nunca como jerga («el 0,618»).

export const NIVELES_FIB = [0.236, 0.382, 0.5, 0.618, 0.786]

/** 0.5 → "50 %"; 0.618 → "61,8 %". */
export const nivelPct = (r) => `${(r * 100).toLocaleString('es-AR', { maximumFractionDigits: 1 })} %`

/** El rótulo de una raya del gráfico: los extremos por su nombre (el pico o el
 *  piso donde terminó el tramo, y su arranque), los niveles por su porcentaje. */
export function rotuloNivel(nivel, dir) {
  if (nivel === 0) return dir === 'suba' ? 'Pico' : 'Piso'
  if (nivel === 1) return 'Arranque'
  return nivelPct(nivel)
}

/** El nivel más lejano que el precio llegó a tocar: 0 si no llegó al 23,6 %,
 *  1 si pasó el arranque del tramo. */
export function nivelAlcanzado(r) {
  if (r == null) return null
  if (r >= 1) return 1
  let out = 0
  for (const n of NIVELES_FIB) if (r >= n) out = n
  return out
}

/**
 * Un Fibonacci marcado A MANO (la herramienta «Fibonacci a mano» de la barra):
 * el tramo de `desde` a `hasta` (los precios de los dos toques), con la misma
 * cuenta que el automático (backend/estructura.py: nivel r → hasta − r ×
 * (hasta − desde)) y la misma forma, para que lo dibujen las mismas rayas.
 */
export function fibonacciAMano(desde, hasta) {
  return {
    disponible: true, aMano: true, dir: hasta >= desde ? 'suba' : 'bajada',
    desde: { precio: desde }, hasta: { precio: hasta },
    niveles: NIVELES_FIB.map(r => ({ nivel: r, precio: hasta - r * (hasta - desde) })),
  }
}

/**
 * La EXTENSIÓN de Fibonacci a mano (la «Trend-Based Fib Extension» de
 * TradingView): tres toques — dónde arranca un movimiento (a), dónde termina
 * (b) y dónde termina el retroceso (c) — y los niveles hacia adelante desde c,
 * medidos con el tamaño del movimiento: nivel r → c + r × (b − a). Los niveles
 * son los más usados (0 %, 61,8 %, 100 %, 161,8 %, 200 % y 261,8 %).
 */
export const NIVELES_EXTENSION = [0, 0.618, 1, 1.618, 2, 2.618]
export function extensionFibonacci(a, b, c) {
  return NIVELES_EXTENSION.map(r => ({ nivel: r, precio: c + r * (b - a) }))
}

/**
 * Las rayas del gráfico: [{ nivel, precio, extremo }]. 0 es el final del tramo
 * (el pico de una suba) y 1 su arranque; en el medio, los cinco niveles.
 */
export function rayas(f) {
  if (!f?.disponible) return []
  return [
    { nivel: 0, precio: f.hasta.precio, extremo: true },
    ...f.niveles.map(n => ({ nivel: n.nivel, precio: n.precio, extremo: false })),
    { nivel: 1, precio: f.desde.precio, extremo: true },
  ]
}

/**
 * Qué rótulos de nivel entran sin pisarse: `tops` son las alturas (0 a 100) de
 * cada raya, en el orden de `rayas`. Primero los extremos y los niveles entre
 * los que está hoy el precio, después los demás; uno que cae a menos de
 * `minimo` de otro ya puesto se saltea (la raya se dibuja igual).
 */
export function rotulosQueEntran(lista, tops, entre, minimo = 6) {
  const prioridad = (r) => (r.extremo ? 0 : entre?.includes(r.nivel) ? 1 : r.nivel === 0.5 || r.nivel === 0.618 ? 2 : 3)
  const orden = lista.map((r, k) => k).sort((a, b) => prioridad(lista[a]) - prioridad(lista[b]))
  const puestos = []
  for (const k of orden) {
    if (puestos.every(j => Math.abs(tops[j] - tops[k]) >= minimo)) puestos.push(k)
  }
  return new Set(puestos)
}

const pct0 = (r) => `${Math.round(r * 100)} %`

// "Ahora sube desde US$ 349 (25/06/26). Si un día cierra debajo de US$ 486 (el
// último pozo más alto, del …), podría ser una señal de que esa suba está
// perdiendo fuerza." Dicho como posibilidad, no como certeza (Nico, 23/10:
// «ahí se termina la suba» sonaba a que iba a pasar seguro)."
function textoEnCurso(e, precio, fecha) {
  if (!e) return ''
  const suba = e.dir === 'suba'
  const corte = suba ? e.se_rompe_si_cierra.debajo_de : e.se_rompe_si_cierra.encima_de
  const donde = e.se_rompe_si_cierra.fecha === e.desde.fecha
    ? 'donde arrancó'
    : `${suba ? 'el último pozo más alto' : 'el último techo más bajo'}, del ${fecha(e.se_rompe_si_cierra.fecha)}`
  return `Ahora ${suba ? 'sube' : 'baja'} desde ${precio(e.desde.precio)} (${fecha(e.desde.fecha)}). `
    + `Si un día cierra ${suba ? 'debajo' : 'encima'} de ${precio(corte)} (${donde}), podría ser una señal de que esa ${e.dir} está perdiendo fuerza.`
}

/**
 * La tarjeta del Fibonacci: { titulo, veredicto, texto, explicacion?, pie }. `precio` y
 * `fecha` formatean como el resto de la ficha. Describe, no recomienda.
 */
export function tarjetaFibonacci(f, precio, fecha) {
  if (!f) return null
  const n = f.n_pivote ?? 3
  const pie = `Un pico o un pozo recién se confirma ${n} días de mercado después: hasta entonces no se sabe si alguno de esos días lo supera. `
    + 'Describe cómo se movió el precio; no es una recomendación de compra o venta.'
  if (!f.disponible) {
    if (f.motivo === 'pocos_datos') {
      return { titulo: 'Fibonacci', veredicto: 'Faltan datos', pie,
        texto: `Para ver picos y pozos hacen falta al menos 30 días de mercado y este activo tiene ${f.ruedas}.` }
    }
    const e = f.en_curso
    const enCurso = e ? `${e.dir === 'suba' ? 'Suba' : 'Bajada'} en curso` : null
    const cola = e ? ` ${textoEnCurso(e, precio, fecha)} Si eso pasa, recién ahí se mide su Fibonacci.` : ''
    const tramo = (t) => `${t.dir} (de ${precio(t.desde.precio)} el ${fecha(t.desde.fecha)} a ${precio(t.hasta.precio)} el ${fecha(t.hasta.fecha)})`
    if (f.motivo === 'superado' && f.superado) {
      return {
        titulo: 'Fibonacci', veredicto: enCurso || 'Sin tramo para medir', pie,
        texto: `La última ${tramo(f.superado)} ya quedó atrás: el precio salió de ese tramo y sus niveles no dicen nada hoy.${cola}`,
      }
    }
    if (f.motivo === 'sin_tramo_terminado') {
      return {
        titulo: 'Fibonacci', veredicto: enCurso || 'Sin tramo para medir', pie,
        texto: `En la historia guardada todavía no terminó ninguna suba ni bajada: el Fibonacci se mide sobre un tramo que ya se rompió.${cola}`,
      }
    }
    if (f.motivo === 'tramo_viejo') {
      return {
        titulo: 'Fibonacci', veredicto: 'Sin tramo reciente', pie,
        texto: `${f.viejo ? `La última ${tramo(f.viejo)}` : 'El último tramo claro'} terminó hace más de un año: sus niveles ya no describen cómo se mueve hoy.${cola}`,
      }
    }
    // tramos_chicos: un activo lateral.
    return {
      titulo: 'Fibonacci', veredicto: 'Sin tramo claro', pie,
      texto: `No hubo una suba ni una bajada clara: los movimientos fueron del tamaño de lo que el precio se mueve en pocos días, y con eso no se dibuja un Fibonacci.${cola}`,
    }
  }

  const suba = f.dir === 'suba'
  const [a, b] = f.entre || []
  const hoy = f.retroceso_hoy
  const veredicto = hoy < 0.05
    ? `Sigue cerca del ${suba ? 'pico' : 'piso'}`
    : `${suba ? 'Devolvió' : 'Recuperó'} el ${pct0(hoy)} de la ${f.dir}`

  // Si nunca llegó a formar un segundo pico, lo que defendía era su arranque.
  const contra = f.ruptura.nivel_fecha === f.desde.fecha
    ? `donde había arrancado (${precio(f.ruptura.nivel)})`
    : `su ${suba ? 'último pozo más alto' : 'último techo más bajo'} (${precio(f.ruptura.nivel)}, del ${fecha(f.ruptura.nivel_fecha)})`
  // El pico (o piso) se confirma 3 días de mercado después: a veces el precio
  // ya había cerrado del otro lado antes de que se supiera cuál era el nivel.
  const fuera = f.ruptura.cerro_fuera_fecha
  const fin = fuera && fuera !== f.ruptura.fecha
    ? `El ${fecha(f.ruptura.fecha)} se confirmó que el nivel a defender era ${contra}, y el precio ya había cerrado ${suba ? 'debajo' : 'encima'} el ${fecha(fuera)}: ahí terminó la ${f.dir}.`
    : `El ${fecha(f.ruptura.fecha)} cerró ${suba ? 'debajo' : 'encima'} de ${contra}: ahí terminó la ${f.dir}.`

  const zona = a === 0
    ? `${suba ? 'devolvió' : 'recuperó'} menos del 23,6 % de la ${f.dir}`
    : b === 1
      ? `${suba ? 'devolvió' : 'recuperó'} casi toda la ${f.dir} (más del 78,6 %)`
      : `está entre el ${nivelPct(a)} y el ${nivelPct(b)} de la ${f.dir}`
  const rm = f.retroceso_maximo
  const lejos = rm && rm.precio != null && rm.valor >= 0.05
    ? ` Lo más ${suba ? 'bajo' : 'alto'} que llegó fue ${precio(rm.precio)}, el ${fecha(rm.fecha)} (${rm.valor >= 1 ? `pasó el arranque de la ${f.dir}` : `${pct0(rm.valor)} de la ${f.dir}`}).`
    : ''
  // El último CIERRE, con su fecha: «hoy» al lado del precio en vivo de la
  // ficha eran dos «hoy» distintos (auditoría D5, 29/10).
  const alCierre = f.fecha_hoy ? `Al cierre del ${fecha(f.fecha_hoy)}` : 'En el último cierre'
  const hoyTxt = f.precio_hoy != null ? `${alCierre} estaba en ${precio(f.precio_hoy)}: ${zona}.` : `${alCierre} ${zona}.`
  const queSon = suba
    ? 'Las rayas marcan hasta dónde podría volver a bajar antes de seguir subiendo: muchos miran el 38,2 %, el 50 % y el 61,8 % de la suba. Pasar el 78,6 % es devolver casi toda la suba.'
    : 'Las rayas marcan hasta dónde podría volver a subir antes de seguir bajando: muchos miran el 38,2 %, el 50 % y el 61,8 % de la bajada. Pasar el 78,6 % es recuperar casi toda la bajada.'

  return {
    titulo: suba ? 'Fibonacci de la última suba' : 'Fibonacci de la última bajada',
    veredicto, pie,
    texto: `La última ${f.dir} fue de ${precio(f.desde.precio)} (${fecha(f.desde.fecha)}) a ${precio(f.hasta.precio)} (${fecha(f.hasta.fecha)}). ${fin} `
      + `${hoyTxt}${lejos}`,
    explicacion: queSon,
  }
}
