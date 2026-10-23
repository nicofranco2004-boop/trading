// elliott.js — las palabras de las ondas de Elliott de la ficha.
// ════════════════════════════════════════════════════════════════════════════
// Las CUENTAS (qué picos y pozos son cada onda, las reglas, las proporciones y
// el precio que invalida) vienen hechas de GET /api/tecnico en el campo
// `elliott` (backend/elliott.py). Acá sólo se dicen en castellano.
//
// El conteo de Elliott es subjetivo: siempre se dice como «un conteo posible»,
// con la confianza y lo que lo invalida, y nunca como lo que va a pasar ni como
// una recomendación. Mismo tono que el Fibonacci (utils/fibonacci.js):
// «días de mercado», porcentajes como dato al lado y no como jerga.

const pct = (x) => `${Math.round(x * 100)} %`
const veces = (x) => x.toLocaleString('es-AR', { maximumFractionDigits: 2, minimumFractionDigits: 1 })

export const QUE_ES = 'La teoría de Elliott dice que el precio suele avanzar en 5 ondas —tres a favor (1, 3 y 5) '
  + 'y dos de descanso (2 y 4)— y después corregir en 3 (A, B y C).'

/** El nombre del movimiento contado: «la suba» o «la bajada». */
const mov = (c) => (c.dir === 'suba' ? 'la suba' : 'la bajada')

const punto = (c, onda) => c.ondas.find(o => o.onda === onda)

/**
 * Dónde podría estar hoy, para poner después de «Según un conteo posible,».
 * Todo en condicional: es una hipótesis, no lo que va a pasar (Nico, 23/10:
 * «que no sea tan como seguro que lo dice»).
 */
export function dondeHoy(c, fecha) {
  if (!c) return ''
  const corrSuelta = c.tipo === 'correccion'
  // Una corrección suelta: su 'dir' es el de su onda A (una A-B-C a la baja
  // corrige una suba anterior).
  const corr = corrSuelta ? `la corrección ${c.dir === 'bajada' ? 'a la baja, después de una suba' : 'al alza, después de una bajada'}` : 'la corrección'
  switch (c.ahora) {
    case 'onda_3': return `el precio podría estar en la onda 3 de ${mov(c)}, que en la teoría suele ser la más larga`
    case 'onda_4': return `el precio podría estar en la onda 4, un descanso de ${mov(c)} después de la onda 3`
    case 'onda_5': return `el precio podría estar en la onda 5, que en la teoría es la última de ${mov(c)}`
    case 'correccion': return `las 5 ondas de ${mov(c)} podrían haber terminado el ${fecha(punto(c, '5').fecha)}, y el precio podría estar en la corrección que en la teoría suele venir después`
    case 'onda_B': return `las 5 ondas de ${mov(c)} podrían haber terminado el ${fecha(punto(c, '5').fecha)}; la corrección habría hecho su onda A y el precio podría estar en la B, un movimiento corto en contra de la corrección`
    case 'onda_C': return `el precio podría estar en la onda C de ${corr}, que en la teoría es su último tramo`
    case 'fin_abc': return `${corr} (A, B y C) podría haber terminado el ${fecha(punto(c, 'C').fecha)}`
    default: return ''
  }
}

/** El veredicto corto de la tarjeta. */
export function veredictoElliott(c) {
  if (!c) return 'Sin conteo claro'
  const v = {
    onda_3: 'Onda 3', onda_4: 'Onda 4', onda_5: 'Onda 5', correccion: 'Corrección después de 5 ondas',
    onda_B: 'Onda B de la corrección', onda_C: 'Onda C de la corrección', fin_abc: 'Fin de una corrección A-B-C',
  }[c.ahora]
  return `Un conteo posible: ${v.charAt(0).toLowerCase()}${v.slice(1)}`
}

const cruza = (lado, p, precio) => (lado === 'debajo' ? `baja de ${precio(p)}` : `sube de ${precio(p)}`)

/**
 * En qué precio el conteo dejaría de tener sentido, como posibilidad («si el
 * precio…, dejaría de…»), nunca como sentencia. Con el segundo nivel que también
 * lo corta, del otro lado, si hay (backend/elliott.py, `invalida.otro`).
 */
export function textoInvalida(c, precio) {
  const { precio: p, lado, por, otro } = c.invalida
  const x = cruza(lado, p, precio)
  const primero = {
    arranque_1: `Si el precio ${x} (donde arrancó la onda 1), este conteo dejaría de tener sentido: en la teoría, la onda 2 no va más allá de ese punto.`,
    final_1: `Si el precio ${x} (donde terminó la onda 1), este conteo dejaría de tener sentido: en la teoría, la onda 4 no se mete en el terreno de la 1.`,
    final_5: `Si el precio ${x} (el final de la onda 5), esta lectura dejaría de tener sentido: podría ser que la 5 todavía no haya terminado.`,
    arranque_A: `Si el precio ${x} (donde arrancó la onda A), este conteo dejaría de tener sentido: en la teoría, la B no va más allá de ese punto.`,
    final_C: `Si el precio ${x} (el final de la onda C), esta lectura dejaría de tener sentido: podría ser que la corrección siga.`,
  }[por] || ''
  if (!otro) return primero
  const y = cruza(otro.lado, otro.precio, precio)
  const segundo = {
    tope_3_corta: `También dejaría de tener sentido si ${y}: con una onda 3 más corta que la 1, en la teoría la 5 no mide más que la 3.`,
    arranque_1: `Y también si ${y} (donde arrancó la onda 1): sería devolver todo el movimiento de 5 ondas.`,
    borro_lo_corregido: `Y también si ${y}: la corrección habría borrado todo el movimiento que venía corrigiendo.`,
    arranque_A: `Y también si ${y} (donde arrancó la onda A): ya no se vería como una corrección.`,
  }[otro.por]
  return segundo ? `${primero} ${segundo}` : primero
}

/** Cada pauta en castellano: { texto, cumple }. */
export function textoPauta(p) {
  const v = p.valor
  switch (p.id) {
    case 'onda2': return `La onda 2 devolvió el ${pct(v)} de la 1 (lo habitual: entre 50 % y 61,8 %).`
    case 'onda3': return `La onda 3 midió ${veces(v)} veces la 1 (lo habitual: cerca de 1,6 veces).`
    case 'onda4': return `La onda 4 devolvió el ${pct(v)} de la 3 (lo habitual: cerca del 38 %).`
    case 'alternancia': return p.cumple
      ? 'Las ondas 2 y 4 fueron distintas (una devolvió la mitad o más y la otra poco, o una duró el triple), como suele pasar.'
      : 'Las ondas 2 y 4 se parecieron; lo habitual es que sean distintas.'
    case 'onda5': return `La onda 5 midió ${veces(v)} veces la 1 (lo habitual: parecida).`
    case 'ondaB': return `La onda B devolvió el ${pct(v)} de la A (lo habitual: entre 50 % y 61,8 %).`
    case 'ondaC': return `La onda C midió ${veces(v)} veces la A (lo habitual: parecida).`
    default: return ''
  }
}

export function textoConfianza(c) {
  const n = c.pautas.length
  const si = c.pautas.filter(p => p.cumple).length
  const base = `Confianza ${c.confianza}`
  if (!n) return `${base}: todavía no hay proporciones para comparar.`
  return `${base}: cumple ${si} de ${n} ${n === 1 ? 'proporción que suele darse' : 'proporciones que suelen darse'}.`
}

const NOMBRE_ONDA = { onda_3: 'la onda 3', onda_4: 'la onda 4', onda_5: 'la onda 5', onda_B: 'la onda B', onda_C: 'la onda C' }
const pctDe = (a, n) => `${Math.round((a / n) * 100)} %`

/**
 * La zona donde suele terminar la onda en curso, con cuánto acertó en la
 * historia y contra qué: una franja del mismo ancho puesta justo delante del
 * precio. Si Fibonacci no le gana a esa franja, se dice (Nico, 23/10: «con ese
 * número al lado»). null si no hay zona.
 */
export function textoZona(c, precio) {
  const z = c?.zona
  if (!z || !z.casos) return null
  const base = `Si ${NOMBRE_ONDA[c.ahora]} siguiera las proporciones habituales de Fibonacci, podría terminar entre ${precio(z.desde)} y ${precio(z.hasta)} (la franja del gráfico). `
    + `En la historia de ${z.activos} activos, de ${z.casos} veces que una onda así terminó, terminó dentro de su franja ${z.aciertos} (${pctDe(z.aciertos, z.casos)}); `
    + `una franja del mismo ancho puesta justo delante del precio acertó ${z.tonta} (${pctDe(z.tonta, z.casos)}).`
  return z.aciertos > z.tonta ? base : `${base} O sea: esta franja no adivinó mejor que una cualquiera puesta delante del precio.`
}

/**
 * La tarjeta: { titulo, veredicto, texto, invalida?, zona?, confianza?, pautas?, alternativo?, pie }.
 * `precio` y `fecha` formatean como el resto de la ficha. Describe, no recomienda.
 */
export function tarjetaElliott(e, precio, fecha) {
  if (!e) return null
  const n = e.n_pivote ?? 3
  const pie = 'Es una de varias lecturas posibles: dos personas pueden contar distinto el mismo gráfico. '
    + `Un pico o un pozo recién se confirma ${n} días de mercado después. `
    + 'No dice qué va a pasar ni es una recomendación de compra o venta.'
  if (!e.disponible) {
    if (e.motivo === 'pocos_datos') {
      return { titulo: 'Ondas de Elliott', veredicto: 'Faltan datos', pie,
        texto: `${QUE_ES} Para contarlas hacen falta al menos 30 días de mercado y este activo tiene ${e.ruedas}.` }
    }
    return { titulo: 'Ondas de Elliott', veredicto: 'Sin conteo claro', pie,
      texto: `${QUE_ES} Con los picos y pozos de este activo no aparece ningún conteo que cumpla las reglas, y no se fuerza uno.` }
  }
  const c = e.principal
  const a = e.alternativo
  return {
    titulo: 'Ondas de Elliott',
    veredicto: veredictoElliott(c),
    texto: `${QUE_ES} Según un conteo posible, ${dondeHoy(c, fecha)}.`,
    invalida: textoInvalida(c, precio),
    zona: textoZona(c, precio),
    confianza: textoConfianza(c),
    pautas: c.pautas.map(p => ({ texto: textoPauta(p), cumple: p.cumple })),
    alternativo: a ? `Otra lectura posible: ${dondeHoy(a, fecha)} (confianza ${a.confianza}).` : null,
    pie,
  }
}

/** El rótulo de cada punto en el gráfico ('0', el arranque, no lleva). */
export const rotuloOnda = (o) => (o.onda === '0' ? null : o.onda)
