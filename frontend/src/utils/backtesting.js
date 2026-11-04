// backtesting — las palabras de la pestaña «Backtesting» de Análisis técnico
// (Nico, 04/11; boceto aprobado: https://claude.ai/artifact/46cJx7aUeeH9CkVA7LAqX5).
// ═══════════════════════════════════════════════════════════════════════════
// LA CUENTA NO ESTÁ ACÁ. Qué habría pasado siguiendo cada regla, y comprando y
// manteniendo, lo calcula el servidor (backend/backtest.py, GET
// /api/tecnico/:activo/backtest) con la serie y las cuentas de la ficha. Acá se
// dice qué es cada regla y se ponen en palabras los números que vuelven.
//
// NUNCA PROMETE. Todo en pasado y siempre al lado de comprar y mantener: lo que
// habría pasado no dice nada de lo que va a pasar. Medido el 04/11 en 14 papeles
// y 2 años: la regla que sale «mejor» cambia de papel en papel, y en 7 de los 14
// ninguna le ganó a mantener. Por eso, con pocas compras se dice que no alcanzan
// para separar la regla de la suerte, si una sola compra explica el resultado
// se dice cuál, y al comparar no se ordena de la que dio más a la que dio menos.
import { nfmt, pctVar } from './format'
import { fechaCorta } from './cuantoSeMueve'

// Las reglas, en el orden de backend/backtest.py (REGLAS): las cuatro que ya
// muestra la ficha (Nico, 04/11). `corto`: su nombre al compararlas.
// `necesita`: por qué la prueba puede arrancar después de lo pedido (la cuenta
// todavía no existe).
export const REGLAS = [
  {
    id: 'media200', nombre: 'Precio y media de 200 días', corto: 'Media de 200',
    explica: 'Compra cuando el precio pasa arriba de su media de 200 días. Vende cuando pasa abajo.',
    necesita: 'la media de 200 días necesita 200 días de precios antes',
  },
  {
    id: 'media50', nombre: 'Precio y media de 50 días', corto: 'Media de 50',
    explica: 'Compra cuando el precio pasa arriba de su media de 50 días. Vende cuando pasa abajo.',
    necesita: 'la media de 50 días necesita 50 días de precios antes',
  },
  {
    id: 'rsi', nombre: 'RSI 30 / 70', corto: 'RSI 30 / 70',
    explica: 'Compra cuando el RSI sale de abajo de 30. Vende cuando sale de arriba de 70.',
    necesita: 'el RSI necesita 15 días de precios antes',
  },
  {
    id: 'adx_squeeze', nombre: 'ADX + Squeeze', corto: 'ADX + Squeeze',
    explica: 'Compra cuando el Squeeze empieza a subir desde abajo y el ADX gira para arriba con 23 o más. '
      + 'Vende cuando el empuje se apaga.',
    necesita: 'el ADX y el Squeeze necesitan unos 45 días de precios antes',
  },
]
export const reglaDe = (id) => REGLAS.find(r => r.id === id) || REGLAS[0]
// Cuántas se comparan a la vez (backend/backtest.py, MAX_REGLAS).
export const MAX_REGLAS = 3

// Los períodos, los de backend/backtest.py (ANIOS). Se guardan 5 años de
// precios y la media de 200 necesita casi uno antes: 4 es lo más largo en que
// las cuatro reglas tienen el período entero.
export const PERIODOS = [[1, '1 año'], [2, '2 años'], [3, '3 años'], [4, '4 años']]
export const DE_ENTRADA = { regla: 'media200', anios: 2 }

/** El período de la dirección (?anios=3); uno que no se ofrece, el de entrada. */
export function aniosDe(texto) {
  const n = Number(texto)
  return PERIODOS.some(([a]) => a === n) ? n : DE_ENTRADA.anios
}

/** Las reglas de la dirección (?reglas=rsi,adx_squeeze), en su orden: sólo las
 *  que se ofrecen, sin repetir, hasta `MAX_REGLAS`. Ninguna: la de entrada. */
export function reglasDe(texto) {
  const out = []
  for (const id of String(texto || '').split(',').map(s => s.trim())) {
    if (REGLAS.some(r => r.id === id) && !out.includes(id) && out.length < MAX_REGLAS) out.push(id)
  }
  return out.length ? out : [DE_ENTRADA.regla]
}

/** La que se suma al tocar «Comparar con otra regla»: la primera que no está. */
export const otraRegla = (elegidas) => REGLAS.find(r => !elegidas.includes(r.id))?.id || null

// Con menos compras que esto, el resultado depende de muy pocas operaciones.
export const POCAS_COMPRAS = 10
// La mejor compra «explica casi todo» si sin ella la regla habría dado menos
// de la mitad.
const EXPLICA_CASI_TODO = 0.5
// Una caída en el camino que se cuenta al lado de un buen resultado.
const CAIDA_PARA_CONTAR = -25

/** «−30,0%» · «+25,5%»: el porcentaje que ya viene en escala de 100. */
export const porcentaje = (x, decimales = 1) => pctVar(x, decimales)

/** Un precio: «59,85»; abajo de 1, con 4 cifras (una cripto de US$ 0,0004). */
export const precio = (x) => (Math.abs(x) >= 1 ? nfmt(x, 2)
  : Number(x).toLocaleString('es-AR', { maximumSignificantDigits: 4 }))

/** «el último año» · «los últimos 2 años». */
export const periodoEnPalabras = (anios) => (anios === 1 ? 'el último año' : `los últimos ${anios} años`)

/** Por qué no se pudo probar (los motivos de la ficha, y el del backtesting). */
export const MOTIVOS = {
  sin_serie: 'no tiene un precio de todos los días para probar una regla (un bono o un fondo).',
  sin_datos: 'no encontramos sus precios.',
  tope: 'pediste muchos activos nuevos en poco tiempo: probá de nuevo en un rato.',
  bajando: 'estamos bajando sus precios: probá de nuevo en unos segundos.',
  poca_historia: 'tiene muy pocos días de precios para probar esta regla en ese período.',
}

/** Si la prueba arrancó después de lo pedido, por qué. null si no. Al
 *  comparar, la que corrió el principio es la que más historia necesita
 *  (`recorte_por`): todas arrancan ese día. */
export function textoDelRecorte(res) {
  if (!res?.disponible || !res.recortado) return null
  const hay = `Hay precios de ${res.asset} desde el ${fechaCorta(res.primera_vela)}`
  if (!res.recorte_por || res.desde === res.primera_vela) return `${hay}: la prueba arranca ese día.`
  return `${hay} y ${reglaDe(res.recorte_por).necesita}: la prueba arranca el ${fechaCorta(res.desde)}.`
}

const periodoDe = (res) => (res.recortado ? `desde el ${fechaCorta(res.desde)}` : `en ${periodoEnPalabras(res.anios)}`)
const afueraDe = (res, x) => Math.round((1 - x.ruedas_comprada / res.ruedas) * 100)

/** Lo que dicen los números, en palabras: {titulo, frases}. Describe, en
 *  pasado, lo que habría pasado; nunca dice qué va a pasar. Con una regla, esa
 *  regla contra comprar y mantener; con varias, `lecturaComparada`. */
export function lectura(res) {
  if (!res?.disponible) return null
  if (res.resultados.length > 1) return lecturaComparada(res)
  const r = res.resultados[0]
  const m = res.mantener
  const periodo = periodoDe(res)
  if (r.compras === 0) {
    return {
      titulo: 'No dio ninguna señal',
      frases: [`${capital(periodo)}, la regla no marcó ninguna compra: la plata habría quedado quieta. `
        + `Comprar y mantener dio ${porcentaje(m.resultado)}.`],
    }
  }
  const frases = []
  const afuera = afueraDe(res, r)
  const cayo = m.resultado < 0
  frases.push(`${res.asset} ${cayo ? 'bajó' : 'subió'} ${Math.abs(Math.round(m.resultado))}% ${periodo} y la regla `
    + `estuvo afuera el ${afuera}% de los días`
    + (cayo && afuera >= 50 && r.resultado > m.resultado ? ': cuando el precio cae, estar afuera ayuda.' : '.'))
  const s = r.sin_la_mejor
  if (compraClave(r)) {
    frases.push(`La compra del ${fechaCorta(s.compra)} (${porcentaje(s.resultado)}) explica casi todo: `
      + `sin ella, la regla habría dado ${porcentaje(s.sin_ella)}.`)
  }
  if (r.resultado > m.resultado && r.peor_caida <= CAIDA_PARA_CONTAR) {
    frases.push(`En el camino llegó a caer ${Math.abs(Math.round(r.peor_caida))}% desde su mejor momento.`)
  }
  if (r.compras < POCAS_COMPRAS) {
    frases.push(`${r.compras === 1 ? 'Fue una sola compra' : `Fueron ${r.compras} compras`} ${periodo}: `
      + 'con tan pocas, no alcanza para saber si el resultado es de la regla o de la suerte.')
  }
  return { titulo: titulo(r.resultado, m.resultado), frases }
}

/** Varias reglas: cuántas le ganaron a comprar y mantener (sin decir cuál es
 *  «la mejor»), cuánto estuvieron afuera, la compra que explica casi todo de
 *  cada una, y que con pocas compras no se puede separar una regla de otra. */
export function lecturaComparada(res) {
  const xs = res.resultados
  const m = res.mantener
  const periodo = periodoDe(res)
  const ganan = xs.filter(x => x.resultado > m.resultado).length
  const afuera = xs.map(x => afueraDe(res, x))
  const menos = Math.min(...afuera)
  const mas = Math.max(...afuera)
  const cayo = m.resultado < 0
  const frases = [`${res.asset} ${cayo ? 'bajó' : 'subió'} ${Math.abs(Math.round(m.resultado))}% ${periodo} y las `
    + `reglas estuvieron afuera ${menos === mas ? `el ${menos}%` : `entre el ${menos}% y el ${mas}%`} de los días`
    + (cayo && menos >= 50 && ganan > 0 ? ': cuando el precio cae, estar afuera ayuda.' : '.')]
  for (const x of xs) {
    if (!compraClave(x)) continue
    const s = x.sin_la_mejor
    frases.push(`${reglaDe(x.regla).corto}: la compra del ${fechaCorta(s.compra)} (${porcentaje(s.resultado)}) `
      + `explica casi todo; sin ella habría dado ${porcentaje(s.sin_ella)}.`)
  }
  if (xs.some(x => x.compras < POCAS_COMPRAS)) {
    frases.push(`Con ${enLista(xs.map(x => x.compras))} compras ${periodo}, no alcanza para saber si una regla `
      + 'es mejor que otra o si tuvo suerte.')
  }
  frases.push('Probá las mismas reglas en otro activo: la que sale mejor en uno muchas veces no es la que sale '
    + 'mejor en otro.')
  return { titulo: tituloComparado(ganan, xs.length), frases }
}

/** La compra que explica casi todo el resultado de UNA regla (su fecha), o
 *  null: la regla ganó y sin su mejor compra habría dado menos de la mitad. Lo
 *  usan las frases de `lectura` y la marca en la lista de operaciones: la misma
 *  regla. */
export function compraClave(x) {
  const s = x?.sin_la_mejor
  if (!s || !(x.resultado > 0) || !(s.resultado > 0)) return null
  return s.sin_ella < x.resultado * EXPLICA_CASI_TODO ? s.compra : null
}

function titulo(regla, mantener) {
  if (Math.abs(regla - mantener) < 0.05) return 'Dio casi lo mismo que comprar y mantener'
  if (regla < mantener) return 'Comprar y mantener le ganó'
  if (regla < 0) return 'Perdió menos que comprar y mantener'
  if (mantener < 0) return 'Le fue mejor que comprar y mantener'
  return 'Le ganó a comprar y mantener'
}

function tituloComparado(ganan, cuantas) {
  const todas = cuantas === 2 ? 'las dos' : 'las tres'
  if (ganan === 0) return 'Ninguna le ganó a comprar y mantener'
  if (ganan === cuantas) return `${capital(todas)} le ganaron a comprar y mantener`
  return `${ganan === 1 ? 'Una' : 'Dos'} de ${todas} le ${ganan === 1 ? 'ganó' : 'ganaron'} a comprar y mantener`
}

const capital = (t) => t.charAt(0).toUpperCase() + t.slice(1)
/** «3 y 7» · «10, 3 y 7». */
const enLista = (xs) => (xs.length < 2 ? String(xs[0]) : `${xs.slice(0, -1).join(', ')} y ${xs.at(-1)}`)

/** Cuántas compras ganaron, en palabras: «1 ganó» · «2 ganaron» · «ninguna ganó». */
export function ganaron(n) {
  if (!n) return 'ninguna ganó'
  return n === 1 ? '1 ganó' : `${n} ganaron`
}

/** Los tramos en que UNA regla estuvo comprada, en % del ancho del período
 *  (para las franjas de «Cuándo estuvo comprada cada una»): [{desde, ancho}]. */
export function tramosComprada(res, x) {
  const fechas = (res?.curva || []).map(p => p.d)
  const ultimo = fechas.length - 1
  if (ultimo < 1) return []
  return (x?.operaciones || []).map(o => {
    const a = fechas.indexOf(o.compra)
    const b = fechas.indexOf(o.venta)
    return a < 0 || b < 0 ? null : { desde: (a / ultimo) * 100, ancho: (Math.max(b - a, 1) / ultimo) * 100 }
  }).filter(Boolean)
}

/** La aclaración de abajo: cómo se simula y que no es una recomendación. */
export function comoSeSimula(res) {
  const com = res?.comision != null ? `${String(res.comision).replace('.', ',')}%` : 'la comisión'
  const cual = res?.resultados?.length > 1 ? 'una regla' : 'la regla'
  return 'Compra y vende a la apertura del día siguiente a la señal, con '
    + `${com} de comisión al comprar y al vender. Cuando ${cual} está afuera, la plata no gana nada. `
    + 'Si al final seguía comprada, se cuenta con el último cierre. No incluye dividendos. '
    + 'Es lo que habría pasado con los precios de cada día: no dice nada de lo que va a pasar '
    + 'y no es una recomendación de compra o de venta.'
}
