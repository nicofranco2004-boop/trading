// fibonacci.js — las palabras del Fibonacci automático de la ficha.
// ════════════════════════════════════════════════════════════════════════════
// Las CUENTAS (picos, pozos, tramos, rupturas y niveles) vienen hechas de
// GET /api/tecnico en el campo `fibonacci` (backend/estructura.py). Acá sólo se
// dicen en castellano y se decide qué rótulo del gráfico entra.

export const NIVELES_FIB = [0.236, 0.382, 0.5, 0.618, 0.786]

/** 0.5 → "0,5"; 0.618 → "0,618". */
export const nivelTexto = (r) => r.toLocaleString('es-AR', { maximumFractionDigits: 3 })

/** El nivel más lejano que el precio llegó a tocar: 0 si no llegó al 0,236,
 *  1 si pasó el arranque del tramo. */
export function nivelAlcanzado(r) {
  if (r == null) return null
  if (r >= 1) return 1
  let out = 0
  for (const n of NIVELES_FIB) if (r >= n) out = n
  return out
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

// "Ahora sube desde US$ 349 (25/06/26) haciendo picos y pozos cada vez más
// altos. Se rompe si cierra debajo de US$ 486 (el último pozo más alto, del …)."
function textoEnCurso(e, precio, fecha) {
  if (!e) return ''
  const suba = e.dir === 'suba'
  const corte = suba ? e.se_rompe_si_cierra.debajo_de : e.se_rompe_si_cierra.encima_de
  const donde = e.se_rompe_si_cierra.fecha === e.desde.fecha
    ? 'donde arrancó'
    : `${suba ? 'el último pozo más alto' : 'el último techo más bajo'}, del ${fecha(e.se_rompe_si_cierra.fecha)}`
  return `Ahora ${suba ? 'sube' : 'baja'} desde ${precio(e.desde.precio)} (${fecha(e.desde.fecha)}). `
    + `Esa ${e.dir} se da por terminada si un día cierra ${suba ? 'debajo' : 'encima'} de ${precio(corte)} (${donde}).`
}

/**
 * La tarjeta del Fibonacci: { titulo, veredicto, texto, pie }. `precio` y
 * `fecha` formatean como el resto de la ficha. Describe, no recomienda.
 */
export function tarjetaFibonacci(f, precio, fecha) {
  if (!f) return null
  const n = f.n_pivote ?? 3
  const pie = `Un pico o un pozo recién se confirma ${n} ruedas después: hasta entonces no se sabe si alguno de los ${n} días siguientes lo supera. `
    + 'Describe cómo se movió el precio; no es una recomendación de compra o venta.'
  if (!f.disponible) {
    if (f.motivo === 'pocos_datos') {
      return { titulo: 'Fibonacci', veredicto: 'Faltan datos', pie,
        texto: `Para ver picos y pozos hacen falta al menos 30 ruedas y hay ${f.ruedas}.` }
    }
    const e = f.en_curso
    const enCurso = e ? `${e.dir === 'suba' ? 'Suba' : 'Bajada'} en curso` : null
    const cola = e ? ` ${textoEnCurso(e, precio, fecha)} Recién ahí se mide su Fibonacci.` : ''
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
  const alcanzado = nivelAlcanzado(f.retroceso_maximo?.valor ?? f.retroceso_hoy)
  const verbo = suba ? 'Bajó' : 'Recuperó'
  const veredicto = alcanzado === 0
    ? `Todavía no ${suba ? 'bajó' : 'subió'} al 0,236`
    : alcanzado === 1 ? `${verbo} más allá del arranque` : `${verbo} hasta el ${nivelTexto(alcanzado)}`
  const [a, b] = f.entre || []
  const hoy = a === 0
    ? `Hoy está cerca del final de la ${f.dir}, antes del 0,236`
    : b === 1 ? `Hoy está entre el 0,786 y el arranque de la ${f.dir}` : `Hoy está entre el ${nivelTexto(a)} y el ${nivelTexto(b)}`
  const cuanto = `${suba ? 'devolvió' : 'recuperó'} el ${pct0(f.retroceso_hoy)} de la ${f.dir}`
  // Si nunca llegó a formar un segundo pico, lo que defendía era su arranque.
  const contra = f.ruptura.nivel_fecha === f.desde.fecha
    ? `donde había arrancado (${precio(f.ruptura.nivel)})`
    : `${suba ? 'su último pozo más alto' : 'su último techo más bajo'} (${precio(f.ruptura.nivel)}, del ${fecha(f.ruptura.nivel_fecha)})`
  const fin = `La ${f.dir} se dio por terminada el ${fecha(f.ruptura.fecha)}, cuando cerró ${suba ? 'debajo' : 'encima'} de ${contra}.`
  const rm = f.retroceso_maximo
  const lejos = rm && alcanzado > 0
    ? ` Lo más ${suba ? 'bajo' : 'alto'} que llegó${rm.precio != null ? ` fue ${precio(rm.precio)},` : ''} el ${fecha(rm.fecha)}.` : ''
  return {
    titulo: suba ? 'Fibonacci de la última suba' : 'Fibonacci de la última bajada',
    veredicto, pie,
    texto: `De la última ${f.dir} (de ${precio(f.desde.precio)} el ${fecha(f.desde.fecha)} a ${precio(f.hasta.precio)} el ${fecha(f.hasta.fecha)}).${lejos} `
      + `${hoy}: ${cuanto}. ${fin}`,
  }
}
