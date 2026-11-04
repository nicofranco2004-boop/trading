// backtesting — las palabras de la pestaña «Backtesting» de Análisis técnico
// (Nico, 04/11; boceto aprobado: https://claude.ai/artifact/46cJx7aUeeH9CkVA7LAqX5).
// ═══════════════════════════════════════════════════════════════════════════
// LA CUENTA NO ESTÁ ACÁ. Qué habría pasado siguiendo la regla, y comprando y
// manteniendo, lo calcula el servidor (backend/backtest.py, GET
// /api/tecnico/:activo/backtest) con la serie y las cuentas de la ficha. Acá se
// dice qué es cada regla y se ponen en palabras los números que vuelven.
//
// NUNCA PROMETE. Todo en pasado y siempre al lado de comprar y mantener: lo que
// habría pasado no dice nada de lo que va a pasar. Medido el 04/11 en 14 papeles
// y 2 años: la regla que sale «mejor» cambia de papel en papel, y en 7 de los 14
// ninguna le ganó a mantener. Por eso, con pocas compras se dice que no alcanzan
// para separar la regla de la suerte, y si una sola compra explica el
// resultado, se dice cuál.
import { nfmt, pctVar } from './format'
import { fechaCorta } from './cuantoSeMueve'

// Las reglas, en el orden de backend/backtest.py (REGLAS): las cuatro que ya
// muestra la ficha (Nico, 04/11). `necesita`: por qué la prueba puede arrancar
// después de lo pedido (la cuenta todavía no existe).
export const REGLAS = [
  {
    id: 'media200', nombre: 'Precio y media de 200 días',
    explica: 'Compra cuando el precio pasa arriba de su media de 200 días. Vende cuando pasa abajo.',
    necesita: 'la media de 200 días necesita 200 días de precios antes',
  },
  {
    id: 'media50', nombre: 'Precio y media de 50 días',
    explica: 'Compra cuando el precio pasa arriba de su media de 50 días. Vende cuando pasa abajo.',
    necesita: 'la media de 50 días necesita 50 días de precios antes',
  },
  {
    id: 'rsi', nombre: 'RSI 30 / 70',
    explica: 'Compra cuando el RSI sale de abajo de 30. Vende cuando sale de arriba de 70.',
    necesita: 'el RSI necesita 15 días de precios antes',
  },
  {
    id: 'adx_squeeze', nombre: 'ADX + Squeeze',
    explica: 'Compra cuando el Squeeze empieza a subir desde abajo y el ADX gira para arriba con 23 o más. '
      + 'Vende cuando el empuje se apaga.',
    necesita: 'el ADX y el Squeeze necesitan unos 45 días de precios antes',
  },
]
export const reglaDe = (id) => REGLAS.find(r => r.id === id) || REGLAS[0]

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

/** Si la prueba arrancó después de lo pedido, por qué. null si no. */
export function textoDelRecorte(res) {
  if (!res?.disponible || !res.recortado) return null
  const hay = `Hay precios de ${res.asset} desde el ${fechaCorta(res.primera_vela)}`
  if (res.desde === res.primera_vela) return `${hay}: la prueba arranca ese día.`
  return `${hay} y ${reglaDe(res.regla).necesita}: la prueba arranca el ${fechaCorta(res.desde)}.`
}

/** Lo que dicen los números, en palabras: {titulo, frases}. Describe, en
 *  pasado, lo que habría pasado; nunca dice qué va a pasar. */
export function lectura(res) {
  if (!res?.disponible) return null
  const r = res.con_regla
  const m = res.mantener
  const periodo = res.recortado ? `desde el ${fechaCorta(res.desde)}` : `en ${periodoEnPalabras(res.anios)}`
  if (r.operaciones === 0) {
    return {
      titulo: 'No dio ninguna señal',
      frases: [`${capital(periodo)}, la regla no marcó ninguna compra: la plata habría quedado quieta. `
        + `Comprar y mantener dio ${porcentaje(m.resultado)}.`],
    }
  }
  const frases = []
  const afuera = Math.round((1 - r.ruedas_comprada / res.ruedas) * 100)
  const cayo = m.resultado < 0
  frases.push(`${res.asset} ${cayo ? 'bajó' : 'subió'} ${Math.abs(Math.round(m.resultado))}% ${periodo} y la regla `
    + `estuvo afuera el ${afuera}% de los días`
    + (cayo && afuera >= 50 && r.resultado > m.resultado ? ': cuando el precio cae, estar afuera ayuda.' : '.'))
  const s = r.sin_la_mejor
  if (compraClave(res)) {
    frases.push(`La compra del ${fechaCorta(s.compra)} (${porcentaje(s.resultado)}) explica casi todo: `
      + `sin ella, la regla habría dado ${porcentaje(s.sin_ella)}.`)
  }
  if (r.resultado > m.resultado && r.peor_caida <= CAIDA_PARA_CONTAR) {
    frases.push(`En el camino llegó a caer ${Math.abs(Math.round(r.peor_caida))}% desde su mejor momento.`)
  }
  if (r.operaciones < POCAS_COMPRAS) {
    frases.push(`${r.operaciones === 1 ? 'Fue una sola compra' : `Fueron ${r.operaciones} compras`} ${periodo}: `
      + 'con tan pocas, no alcanza para saber si el resultado es de la regla o de la suerte.')
  }
  return { titulo: titulo(r.resultado, m.resultado), frases }
}

/** La compra que explica casi todo el resultado (su fecha), o null: la regla
 *  ganó y sin su mejor compra habría dado menos de la mitad. Lo usan la frase
 *  de `lectura` y la marca en la lista de operaciones: la misma regla. */
export function compraClave(res) {
  const r = res?.con_regla
  const s = r?.sin_la_mejor
  if (!s || !(r.resultado > 0) || !(s.resultado > 0)) return null
  return s.sin_ella < r.resultado * EXPLICA_CASI_TODO ? s.compra : null
}

function titulo(regla, mantener) {
  if (Math.abs(regla - mantener) < 0.05) return 'Dio casi lo mismo que comprar y mantener'
  if (regla < mantener) return 'Comprar y mantener le ganó'
  if (regla < 0) return 'Perdió menos que comprar y mantener'
  if (mantener < 0) return 'Le fue mejor que comprar y mantener'
  return 'Le ganó a comprar y mantener'
}

const capital = (t) => t.charAt(0).toUpperCase() + t.slice(1)

/** Las filas del gráfico: US$ 100 de cada lado, día por día. */
export const filasDelGrafico = (res) => (res?.curva || []).map(p => ({ d: p.d, regla: p.regla, mantener: p.mantener }))

/** Cuántas compras ganaron, en palabras: «1 ganó» · «2 ganaron» · «ninguna ganó». */
export function ganaron(n) {
  if (!n) return 'ninguna ganó'
  return n === 1 ? '1 ganó' : `${n} ganaron`
}

/** La aclaración de abajo: cómo se simula y que no es una recomendación. */
export function comoSeSimula(res) {
  const com = res?.comision != null ? `${String(res.comision).replace('.', ',')}%` : 'la comisión'
  return 'Compra y vende a la apertura del día siguiente a la señal, con '
    + `${com} de comisión al comprar y al vender. Cuando la regla está afuera, la plata no gana nada. `
    + 'Si al final seguía comprada, se cuenta con el último cierre. No incluye dividendos. '
    + 'Es lo que habría pasado con los precios de cada día: no dice nada de lo que va a pasar '
    + 'y no es una recomendación de compra o de venta.'
}
