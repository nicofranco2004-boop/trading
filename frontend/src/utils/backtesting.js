// backtesting — las palabras de la pestaña «Backtesting» de Análisis técnico
// (Nico, 04/11; boceto aprobado: https://claude.ai/artifact/46cJx7aUeeH9CkVA7LAqX5).
// ═══════════════════════════════════════════════════════════════════════════
// LA CUENTA NO ESTÁ ACÁ. Qué habría pasado siguiendo cada regla, y comprando y
// manteniendo, lo calcula el servidor (backend/backtest.py, GET
// /api/tecnico/:activo/backtest) con la serie y las cuentas de la ficha. Acá se
// dice qué es cada regla y se ponen en palabras los números que vuelven.
//
// NUNCA PROMETE. Todo en pasado, sobre ESTA prueba, y siempre al lado de comprar
// y mantener: lo que habría pasado no dice nada de lo que va a pasar. Nada de
// reglas generales en presente («cuando el precio cae, estar afuera ayuda»: la
// auditoría del 04/11 la sacó, la CNV pide todo en pasado y la misma pantalla la
// contradecía). Medido el 04/11 en 14 papeles y 2 años: la regla que dio más
// cambió de papel en papel, y en 7 de los 14 ninguna le ganó a mantener. Por
// eso, con pocas compras se dice que no alcanzan para separar la regla de la
// suerte, si sin su mejor compra no habría ganado se dice cuál, y al comparar
// se cuenta cuántas le ganaron, nunca cuál es «la mejor».
import { decimalesFinos, pctColor, pctVarFino } from './format'
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
// Una caída en el camino que se cuenta al lado de un resultado que le ganó a mantener.
const CAIDA_PARA_CONTAR = -25

/** «−30,0%» · «+25,5%»: el porcentaje que ya viene en escala de 100. Lo que con
 *  un decimal sería «0,0%» se escribe con más (+0,03%): una operación que ganó
 *  no se ve en cero (auditoría 04/11, B9). */
export const porcentaje = (x, decimales = 1) => pctVarFino(x, decimales)
/** El color de ese mismo número, el que se ve (verde, rojo o neutro). */
export const colorDe = (x, decimales = 1) => pctColor(x, decimalesFinos(x, decimales))

/** Un precio: «59,85»; abajo de 1, con 4 cifras (una cripto de US$ 0,0004). */
export const precio = (x) => (Math.abs(x) >= 1
  ? Number(x).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  : Number(x).toLocaleString('es-AR', { maximumSignificantDigits: 4 }))

/** «el último año» · «los últimos 2 años». */
export const periodoEnPalabras = (anios) => (anios === 1 ? 'el último año' : `los últimos ${anios} años`)

/** ¿Le ganó a comprar y mantener? Con los números TAL COMO SE VEN en las
 *  tarjetas (un decimal): 'sin_compras' | 'gano' | 'empate' | 'perdio'. Es LA
 *  respuesta: la usan el título de una regla, el conteo al comparar y «llegó a
 *  caer». Antes eran cuatro cuentas con dos criterios, y decía «le ganó» con
 *  −1,4 % contra −1,4 % (auditoría 04/11, M2). Una regla que no compró nunca no
 *  le ganó a nadie (M1). */
export function contraMantener(x, m) {
  if (!x?.compras) return 'sin_compras'
  const a = Math.round(x.resultado * 10)
  const b = Math.round(m.resultado * 10)
  return a > b ? 'gano' : a < b ? 'perdio' : 'empate'
}

/** Qué parte de los días estuvo afuera, en palabras («el 55%»), sin redondeos
 *  que se contradigan: con alguna compra nunca «el 100 %», y afuera algún día
 *  nunca «el 0 %» (auditoría 04/11, B1). */
export function parteAfuera(res, x) {
  const p = (1 - x.ruedas_comprada / res.ruedas) * 100
  if (p === 0) return 'el 0%'
  if (p < 1) return 'menos del 1%'
  if (p > 99) return 'más del 99%'
  return `el ${Math.round(p)}%`
}

/** Qué hizo el PRECIO en el período (`variacion_precio`, sin comisiones): «GGAL
 *  bajó 35%». No sale de comprar y mantener, que además paga las comisiones: con
 *  un precio quieto decía «bajó 1%» (auditoría 04/11, H2). */
function loQueHizoElPrecio(res, periodo) {
  const v = res.variacion_precio
  if (Math.abs(v) < 0.5) return `${res.asset} terminó casi igual ${periodo}`
  return `${res.asset} ${v < 0 ? 'bajó' : 'subió'} ${Math.abs(Math.round(v))}% ${periodo}`
}

/** Por qué no se pudo probar, en una oración entera con el activo adentro. */
export function motivoEnPalabras(res, activo) {
  const a = activo || res?.asset || 'este activo'
  switch (res?.motivo) {
    case 'sin_serie':
      return `Para probar una regla hacen falta los precios de cada día (apertura, máximo, mínimo y cierre), `
        + `y de ${a} no los tenemos.`
    case 'tope':
      return 'Pediste muchos activos nuevos en poco tiempo: probá de nuevo en un rato.'
    case 'bajando':
      return `Estamos trayendo los precios de ${a}: probá de nuevo en unos segundos.`
    case 'demo':
      return 'En el modo demo no hay precios de todos los días para probar reglas.'
    case 'poca_historia': {
      if (!res.recorte_por) return `${a} tiene muy pocos días de precios para probar una regla.`
      const r = reglaDe(res.recorte_por)
      const varias = (res.reglas || []).length > 1
      return `${a} tiene muy pocos días de precios para probar «${r.nombre}»: ${r.necesita}.`
        + (varias ? ' Sacá esa regla para probar las otras.' : '')
    }
    default:
      return `No encontramos los precios de ${a}.`
  }
}

/** Si la prueba arrancó después de lo pedido, por qué. null si no. Al
 *  comparar, la que corrió el principio es la que más historia necesita
 *  (`recorte_por`): todas arrancan ese día. */
export function textoDelRecorte(res) {
  if (!res?.disponible || !res.recortado || !res.recorte_por) return null
  return `Hay precios de ${res.asset} desde el ${fechaCorta(res.primera_vela)} y ${reglaDe(res.recorte_por).necesita}: `
    + `la prueba arranca el ${fechaCorta(res.desde)}.`
}

const periodoDe = (res) => (res.recortado ? `desde el ${fechaCorta(res.desde)}` : `en ${periodoEnPalabras(res.anios)}`)

/** Lo que dicen los números, en palabras: {titulo, frases}. Describe, en
 *  pasado, lo que habría pasado; nunca dice qué va a pasar. Con una regla, esa
 *  regla contra comprar y mantener; con varias, `lecturaComparada`. */
export function lectura(res) {
  if (!res?.disponible) return null
  if (res.resultados.length > 1) return lecturaComparada(res)
  const r = res.resultados[0]
  const m = res.mantener
  const periodo = periodoDe(res)
  const contra = contraMantener(r, m)
  if (contra === 'sin_compras') {
    return {
      titulo: 'No dio ninguna señal',
      frases: [`${capital(periodo)}, la regla no marcó ninguna compra: la plata habría quedado quieta. `
        + `Comprar y mantener dio ${porcentaje(m.resultado)}.`],
    }
  }
  const frases = [`${loQueHizoElPrecio(res, periodo)} y la regla estuvo afuera ${parteAfuera(res, r)} de los días.`]
  if (compraClave(r)) frases.push(fraseClave(r))
  if (contra === 'gano' && r.peor_caida <= CAIDA_PARA_CONTAR) {
    frases.push(`En el camino llegó a caer ${Math.abs(Math.round(r.peor_caida))}% desde su mejor momento.`)
  }
  if (r.compras < POCAS_COMPRAS) {
    frases.push(`${r.compras === 1 ? 'Fue una sola compra' : `Fueron ${r.compras} compras`} ${periodo}: `
      + 'con tan pocas, no alcanza para saber si el resultado es de la regla o de la suerte.')
  }
  return { titulo: titulo(contra, r.resultado, m.resultado), frases }
}

/** Varias reglas: cuántas le ganaron a comprar y mantener (nunca cuál es «la
 *  mejor»), cuánto estuvieron afuera las que compraron, cuáles no compraron
 *  nunca, la compra sin la que no habría ganado cada una, y que con pocas
 *  compras no se puede separar una regla de otra. */
export function lecturaComparada(res) {
  const xs = res.resultados
  const m = res.mantener
  const periodo = periodoDe(res)
  const compraron = xs.filter(x => x.compras > 0)
  const ganan = xs.filter(x => contraMantener(x, m) === 'gano').length
  let primera = loQueHizoElPrecio(res, periodo)
  if (compraron.length === 1) {
    primera += ` y ${reglaDe(compraron[0].regla).corto} estuvo afuera ${parteAfuera(res, compraron[0])} de los días`
  } else if (compraron.length > 1) {
    const partes = compraron.map(x => 1 - x.ruedas_comprada / res.ruedas)
    const a = parteAfuera(res, compraron[partes.indexOf(Math.min(...partes))])
    const b = parteAfuera(res, compraron[partes.indexOf(Math.max(...partes))])
    primera += ` y las reglas estuvieron afuera ${a === b ? a : `entre ${a} y ${b}`} de los días`
  }
  const frases = [`${primera}.`]
  for (const x of xs) {
    if (!x.compras) frases.push(`${reglaDe(x.regla).corto} no marcó ninguna compra ${periodo}.`)
  }
  for (const x of xs) {
    if (compraClave(x)) frases.push(`${reglaDe(x.regla).corto}: ${fraseClave(x, true)}`)
  }
  if (compraron.some(x => x.compras < POCAS_COMPRAS)) {
    frases.push(`Con tan pocas compras (${enLista(compraron.map(x => x.compras))}) ${periodo}, no alcanza para `
      + 'saber si una regla es mejor que otra o si tuvo suerte.')
  }
  frases.push('Probá las mismas reglas en otro activo: cuando lo medimos en 14 papeles, la regla que dio más '
    + 'cambió de un papel a otro.')
  return { titulo: tituloComparado(ganan, xs.length, compraron.length), frases }
}

/** La compra sin la que la regla NO habría ganado (su fecha), o null. Sólo si
 *  la regla ganó, esa compra ganó y sin ella el resultado habría sido cero o
 *  negativo: entonces sí «explica» el resultado. Con «sin ella da menos de la
 *  mitad» decía «explica casi todo» de una compra de +56 % cuando las demás
 *  juntas habían dado +76 % (auditoría 04/11, A2). Lo usan las frases de
 *  `lectura` y la marca en la lista de operaciones: la misma regla. */
export function compraClave(x) {
  const s = x?.sin_la_mejor
  if (!s || !(x.resultado > 0) || !(s.resultado > 0) || !(s.sin_ella <= 0)) return null
  return s.compra
}

function fraseClave(x, minuscula = false) {
  const s = x.sin_la_mejor
  const sin = `${minuscula ? 's' : 'S'}in la compra del ${fechaCorta(s.compra)} (${porcentaje(s.resultado)})`
  return `${sin}, la regla no habría ganado: habría dado ${porcentaje(s.sin_ella)}.`
}

function titulo(contra, regla, mantener) {
  if (contra === 'empate') return 'Dio casi lo mismo que comprar y mantener'
  if (contra === 'perdio') return 'Comprar y mantener le ganó'
  if (regla < 0) return 'Perdió menos que comprar y mantener'
  if (mantener < 0) return 'Le fue mejor que comprar y mantener'
  return 'Le ganó a comprar y mantener'
}

function tituloComparado(ganan, cuantas, compraron) {
  if (compraron === 0) return 'Ninguna marcó compras en el período'
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
  const com = res?.comision != null
    ? `${Number(res.comision).toLocaleString('es-AR', { maximumFractionDigits: 2 })}%`
    : 'la comisión'
  const cual = res?.resultados?.length > 1 ? 'una regla' : 'la regla'
  return 'Compra y vende a la apertura del día siguiente a la señal, con '
    + `${com} de comisión al comprar y al vender. Cuando ${cual} está afuera, la plata no gana nada. `
    + 'Si al final seguía comprada, se cuenta con el último cierre. No incluye dividendos. '
    + 'Es lo que habría pasado con los precios de cada día: no dice nada de lo que va a pasar '
    + 'y no es una recomendación de compra o de venta.'
}
