// carteraSimulada — las palabras y las cuentas chicas de «Una cartera», dentro
// de la pestaña Backtesting de Análisis técnico (Nico, 05/11; boceto aprobado,
// opción A: https://claude.ai/artifact/46cJx7aUeeH9CkVA7LAqX5).
// ═══════════════════════════════════════════════════════════════════════════
// LA CUENTA NO ESTÁ ACÁ. Qué habría pasado con la cartera, el S&P 500 y el
// Nasdaq lo calcula el servidor (backend/cartera_simulada.py, GET
// /api/backtest/cartera), y «Mi cartera de hoy» también la arma él (GET
// /api/backtest/cartera/hoy), con LA regla de qué activos tienen precio de todos
// los días. Acá: lo que se puede escribir en cada porcentaje, cuánto falta para
// 100, la torta, la dirección y las palabras de lo que volvió.
//
// NUNCA PROMETE, como el Backtesting de una regla (utils/backtesting.js): todo en
// pasado, siempre al lado del S&P 500 y del Nasdaq, sin «la mejor cartera».
// Y habla de lo que TENEMOS, no del activo: «no tenemos los precios de AL30»,
// no «AL30 no tiene precio» (cotiza todos los días: lo que falta es nuestro
// dato; auditoría 05/11, M10).
//
// `cliente`: el asesor adentro de la cuenta de un cliente (`nombreDelCliente`).
// Ahí no es «tu cartera»: es la de él (M11).
import { porcionColor } from './chartTheme'
import { fechaCorta } from './cuantoSeMueve'
import { comoSeVe, enQueTermino, periodoEnPalabras, porcentaje } from './backtesting'

// Los del servidor (backend/cartera_simulada.py): cuántos activos entran y con
// qué tolerancia los porcentajes «suman 100».
export const MAX_ACTIVOS = 10
export const TOLERANCIA = 0.05

// Lo que falta para 100 en la torta: el fondo, como un hueco por llenar.
const SIN_REPARTIR = 'rgb(var(--bg-3))'

export const MODOS = [['regla', 'Una regla'], ['cartera', 'Una cartera']]
export const modoDe = (t) => (t === 'cartera' ? 'cartera' : 'regla')
/** Las dos maneras de arrancar, en el selector. */
export const origenes = (cliente = null) => [['hoy', cliente ? 'Su cartera de hoy' : 'Mi cartera de hoy'], ['cero', 'Armar de cero']]
/** Con qué arranca: lo que dice la dirección. Un link con una cartera y sin
 *  `origen` es una armada a mano (la de hoy nunca va en la dirección). */
export const origenDe = (t, conActivos = false) => (t === 'cero' || (!t && conActivos) ? 'cero' : 'hoy')

export const QUE_SE_SIMULA = 'Poné cada activo y cuánto de la cartera va en él, sobre 100%. Te mostramos qué '
  + 'habría pasado con US$ 100 comprados así el primer día y sin tocar, al lado del S&P 500 y del Nasdaq.'

const deQuien = (cliente) => (cliente ? `la cartera de hoy de ${cliente}` : 'tu cartera de hoy')

/** Arriba de «Mi cartera de hoy». La cartera de hoy no viaja en el link (dice qué
 *  tenés): quien lo abre ve la suya. */
export function notaHoy(cliente = null, cambiada = false) {
  if (cambiada) {
    return `Partiste de ${deQuien(cliente)} y la cambiaste. Los cambios no quedan en el link: al recargar vuelve `
      + 'la de hoy.'
  }
  return `Con ${cliente ? `los activos de ${cliente}` : 'tus activos'} y lo que pesa cada uno hoy, sin bonos, fondos `
    + 'ni efectivo (no tienen precio de todos los días). Cambiá lo que quieras. El link no la lleva: quien lo abra '
    + 've la suya.'
}
export const notaOjito = (cliente = null) => `Con «Ocultar saldos» prendido no traemos ${deQuien(cliente)}: los `
  + `porcentajes dicen qué ${cliente ? 'tiene' : 'tenés'}. Apagalo, o armala de cero.`
export const notaSinActivos = (cliente = null) => `Todavía no ${cliente ? 'tiene' : 'tenés'} activos con precio de `
  + 'todos los días: armala de cero.'
export const trayendoHoy = (cliente = null) => `Trayendo ${deQuien(cliente)}…`
export const errorDeHoy = (cliente = null) => `No pudimos traer ${deQuien(cliente)}.`

const capital = (t) => t.charAt(0).toUpperCase() + t.slice(1)
/** «AAPL» · «AAPL y GGAL» · «AAPL, GGAL y BTC». */
const enLista = (xs) => (xs.length < 2 ? String(xs[0] ?? '') : `${xs.slice(0, -1).join(', ')} y ${xs.at(-1)}`)

/** Lo escrito en un porcentaje como número: «33,3» · «33.3» → 33.3; vacío o
 *  algo que no es un número, 0. */
export function numeroDe(txt) {
  const n = Number.parseFloat(String(txt ?? '').trim().replace(',', '.'))
  return Number.isFinite(n) && n > 0 ? n : 0
}

/** Un porcentaje como se escribe: 40 → «40», 33.3 → «33,3» (hasta 2 decimales). */
export const textoDe = (n) => (n > 0 ? String(Math.round(n * 100) / 100).replace('.', ',') : '')

/** «55,8%» · «50%»: un peso, con un decimal si lo tiene. */
export const pesoTxt = (x) => `${(Math.round(x * 10) / 10).toLocaleString('es-AR', { maximumFractionDigits: 1 })}%`

/** Lo que se acepta mientras se escribe: dígitos y una coma (el punto pasa a
 *  coma), hasta 2 decimales y nunca más de 100. */
export function limpiar(txt) {
  let s = String(txt ?? '').replace('.', ',').replace(/[^0-9,]/g, '')
  const coma = s.indexOf(',')
  if (coma >= 0) s = s.slice(0, coma + 1) + s.slice(coma + 1).replace(/,/g, '').slice(0, 2)
  if (s.startsWith(',')) s = `0${s}`
  s = s.replace(/^0+(?=\d)/, '')
  return numeroDe(s) > 100 ? '100' : s
}

// La suma a centavos: el servidor la redondea igual antes de comparar con la
// tolerancia (50,03 + 50,02 es 100,05000000000001; auditoría 05/11, H6).
export const totalDe = (filas) => Math.round(filas.reduce((s, f) => s + numeroDe(f.txt), 0) * 100) / 100

/** ¿Se puede simular? {listo, total, totalTxt, texto, aviso}: suma 100 y cada
 *  activo tiene su porcentaje. `texto` va al lado del total; `aviso`, abajo. */
export function estadoDeLaCartera(filas) {
  const total = totalDe(filas)
  const base = { total, totalTxt: `${textoDe(total) || '0'}%` }
  const aviso = (que) => `Para ver cómo le habría ido, los porcentajes tienen que sumar 100%: ${que}.`
  if (!filas.length) return { ...base, listo: false, texto: 'Faltan 100%', aviso: null }
  if (Math.abs(total - 100) <= TOLERANCIA) {
    const sinPeso = filas.filter(f => !(numeroDe(f.txt) > 0)).map(f => f.asset)
    if (!sinPeso.length) return { ...base, listo: true, texto: 'Suma 100%', aviso: null }
    const uno = sinPeso.length === 1
    return { ...base, listo: false, texto: uno ? 'Falta un porcentaje' : 'Faltan porcentajes',
      aviso: uno ? `${sinPeso[0]} no tiene porcentaje: poné cuánto va, o sacalo.`
        : `${enLista(sinPeso)} no tienen porcentaje: poné cuánto va en cada uno, o sacalos.` }
  }
  if (total < 100) {
    const f = `${textoDe(100 - total)}%`
    return { ...base, listo: false, texto: `Faltan ${f}`, aviso: aviso(`falta repartir ${f}`) }
  }
  const s = `${textoDe(total - 100)}%`
  return { ...base, listo: false, texto: `Sobran ${s}`, aviso: aviso(`sobran ${s}`) }
}

/** `n` partes iguales que suman 100: 3 → [34, 33, 33]. */
export function repartirIgual(n) {
  if (!(n > 0)) return []
  const base = Math.floor(100 / n)
  return Array.from({ length: n }, (_, k) => base + (k < 100 - base * n ? 1 : 0))
}

/** Lo que le toca al que se suma: lo que falta para 100 (nada si ya está). */
export const loQueFalta = (filas) => Math.max(0, Math.round((100 - totalDe(filas)) * 100) / 100)

const partes = (s) => String(s || '').split(',').map(x => x.trim())
const activosDe = (params) => partes(params.get('activos')).map(s => s.toUpperCase()).filter(Boolean)

/** La cartera armada de la dirección (?activos=AAPL,GGAL&pesos=60,40&local=GGAL):
 *  [{asset, local, txt}], sin repetir y hasta `MAX_ACTIVOS`. Recargar o mandar el
 *  link abre la misma cartera. */
export function carteraDe(params) {
  const activos = activosDe(params)
  const pesos = partes(params.get('pesos'))
  const locales = new Set(partes(params.get('local')).map(s => s.toUpperCase()).filter(Boolean))
  const out = []
  activos.forEach((a, i) => {
    if (out.length < MAX_ACTIVOS && !out.some(f => f.asset === a)) {
      out.push({ asset: a, local: locales.has(a), txt: textoDe(numeroDe(pesos[i])) })
    }
  })
  return out
}

/** Los de la dirección que no entraron: pasado el máximo (un link a mano con 12). */
export function sobranDe(params) {
  const entran = new Set(carteraDe(params).map(f => f.asset))
  return [...new Set(activosDe(params))].filter(a => !entran.has(a))
}

/** «El link traía 12 activos y entran hasta 10: quedaron afuera X y Y.» (null si nada). */
export function notaDeLosQueSobran(sobran) {
  if (!sobran?.length) return null
  const uno = sobran.length === 1
  return `El link traía ${MAX_ACTIVOS + sobran.length} activos y entran hasta ${MAX_ACTIVOS}: `
    + `${uno ? 'quedó' : 'quedaron'} afuera ${enLista(sobran)}.`
}

/** La cartera para la dirección y para el pedido: los pesos con punto. */
export function aLaDireccion(filas) {
  return {
    activos: filas.map(f => f.asset).join(','),
    pesos: filas.map(f => String(Math.round(numeroDe(f.txt) * 100) / 100)).join(','),
    local: filas.filter(f => f.local).map(f => f.asset).join(','),
  }
}

/** Lo que va después de `/backtest/cartera?`, o null si todavía no se puede simular. */
export function consultaDe(filas, anios) {
  if (!estadoDeLaCartera(filas).listo) return null
  const d = aLaDireccion(filas)
  return `activos=${d.activos}&pesos=${d.pesos}${d.local ? `&local=${d.local}` : ''}&anios=${anios}`
}

/** Las porciones de la torta (components/CompositionDonut, `montos={false}`): una
 *  por activo con porcentaje, de la que más pesa a la que menos, con LA rampa de
 *  las tortas de composición (`porcionColor`: el color dice cuánto pesa, no quién
 *  es); lo que falta para 100, al final. La leyenda dice lo ESCRITO: pasado de
 *  100, el dibujo reparte la vuelta entre todos, pero los números son los de la
 *  izquierda (con GGAL 150 → 100 y AAPL 33,5, decía 74,9 % y 25,1 %; auditoría
 *  05/11, M9). */
export function porcionesDeLaTorta(filas) {
  const con = filas.map(f => ({ asset: f.asset, p: numeroDe(f.txt) })).filter(x => x.p > 0)
    .sort((a, b) => b.p - a.p || a.asset.localeCompare(b.asset))
  const total = con.reduce((s, x) => s + x.p, 0)
  const items = con.map((x, i) => ({ key: x.asset, label: x.asset, value: x.p, pct: x.p, color: porcionColor(i) }))
  if (total < 100) items.push({ key: 'sin_dato', label: 'Falta repartir', value: 100 - total, pct: 100 - total, color: SIN_REPARTIR })
  return items
}

/** «Mi cartera de hoy» (GET /backtest/cartera/hoy) como filas para editar. */
export const filasDeHoy = (r) => (r?.activos || []).map(a => ({ asset: a.asset, local: !!a.local, txt: textoDe(a.peso) }))

/** Qué quedó afuera de «Mi cartera de hoy», en palabras (null si nada). */
export function notaDeHoy(r) {
  const afuera = r?.afuera || []
  const sin = afuera.filter(x => x.motivo === 'sin_serie').map(x => x.asset.replace(/^FCI:/, ''))
  const tope = afuera.filter(x => x.motivo === 'tope').map(x => x.asset)
  const out = []
  if (sin.length) {
    out.push(`${sin.length === 1 ? 'Quedó' : 'Quedaron'} afuera ${enLista(sin)}: no tenemos sus precios de cada día.`)
  }
  if (tope.length) {
    out.push(`Entran hasta ${MAX_ACTIVOS} activos: ${tope.length === 1 ? 'quedó' : 'quedaron'} afuera ${enLista(tope)}, `
      + `${tope.length === 1 ? 'el que menos pesa' : 'los que menos pesan'}.`)
  }
  return out.length ? `${out.join(' ')} El resto se repartió sobre 100%.` : null
}

const NOMBRE_INDICE = { sp500: 'S&P 500', nasdaq: 'Nasdaq' }
// ¿Le fue mejor? Con los números TAL COMO SE VEN en las tarjetas (`comoSeVe`, el
// redondeo de la tarjeta), como en el Backtesting de una regla (`contraMantener`).
const contra = (c, i) => {
  const a = comoSeVe(c)
  const b = comoSeVe(i)
  return a > b ? 'gano' : a < b ? 'perdio' : 'empate'
}

function titulo(c, indices) {
  if (!indices.length) return 'Así habría ido esta cartera'
  const de = (k) => indices.filter(i => contra(c.resultado, i.resultado) === k).map(i => `el ${i.nombre}`)
  const [g, p, e] = [de('gano'), de('perdio'), de('empate')]
  const todos = indices.length
  if (g.length === todos) return `Le fue mejor que ${g.join(' y que ')}`
  if (p.length === todos) return `${capital(p.join(' y '))} le ${todos === 1 ? 'ganó' : 'ganaron'}`
  if (e.length === todos) return `Dio casi lo mismo que ${e.join(' y ')}`
  if (g.length && p.length) return `Le fue mejor que ${g[0]}, pero no que ${p[0]}`
  if (g.length) return `Le fue mejor que ${g[0]} y dio casi lo mismo que ${e[0]}`
  return `Dio casi lo mismo que ${e[0]}, y ${p[0]} le ganó`
}

// La peor caída como se ve en las tarjetas (sin decimales, más si redondea a 0),
// sin el signo.
const caida = (x) => porcentaje(x, 0).replace(/^[−+-]/, '')

/** «La peor caída de la cartera —lo más que llegó a bajar desde su mejor
 *  momento— fue de 27%, contra…». Se dice qué es (no es «terminó 27 % abajo») y
 *  de quién: después de la frase de un activo, «Su peor caída» se leía como la de
 *  ese activo (auditoría 05/11, M2). */
function fraseDeLaCaida(c, idx) {
  const lasOtras = idx.map(i => `${caida(i.peor_caida)} del ${i.nombre}`)
  if (caida(c.peor_caida) === '0%') {
    const otras = idx.length ? ` En el mismo período, el ${idx.map(i => `${i.nombre} llegó a caer ${caida(i.peor_caida)}`).join(' y el ')}.` : ''
    return `La cartera no llegó a bajar desde su mejor momento.${otras}`
  }
  return `La peor caída de la cartera —lo más que llegó a bajar desde su mejor momento— fue de ${caida(c.peor_caida)}`
    + `${lasOtras.length ? `, contra ${enLista(lasOtras)}` : ''}.`
}

/** Lo que dicen los números, en palabras: {titulo, frases}. En pasado: qué
 *  habría pasado, nunca qué va a pasar ni cuál cartera es mejor. */
export function lecturaCartera(res) {
  if (!res?.disponible) return null
  const c = res.cartera
  const idx = res.indices || []
  const xs = res.activos || []
  const periodo = res.recortado ? `desde el ${fechaCorta(res.desde)}` : `en ${periodoEnPalabras(res.anios)}`
  const frases = []
  let quedo = `${capital(periodo)}, US$ 100 en esta cartera habrían quedado en ${enQueTermino(c.final)}`
  if (idx.length === 1) quedo += `, y en el ${idx[0].nombre}, en ${enQueTermino(idx[0].final)}`
  if (idx.length === 2) {
    quedo += `; en el ${idx[0].nombre}, en ${enQueTermino(idx[0].final)}, y en el ${idx[1].nombre}, en ${enQueTermino(idx[1].final)}`
  }
  frases.push(`${quedo}.`)
  if (xs.length > 1) {
    const orden = [...xs].sort((a, b) => b.aporte - a.aporte)
    const [mas, menos] = [orden[0], orden.at(-1)]
    const pts = (x) => porcentaje(x).replace('%', '')
    if (mas.aporte > 0 && menos.aporte < 0) {
      frases.push(`El que más sumó fue ${mas.asset}, ${pts(mas.aporte)} puntos, y el que más restó, ${menos.asset}, `
        + `${pts(menos.aporte)}: entre todos, la cartera dio ${porcentaje(c.resultado)}.`)
    } else if (mas.aporte > 0) {
      frases.push(`El que más sumó fue ${mas.asset}: ${pts(mas.aporte)} de los ${pts(c.resultado)} puntos de la cartera.`)
    } else if (menos.aporte < 0) {
      frases.push(`El que más restó fue ${menos.asset}: ${pts(menos.aporte)} de los ${pts(c.resultado)} puntos de la cartera.`)
    }
    // El que más cambió de peso sin tocar la cartera (el mayor, no un orden: la
    // lista de «Cada activo» va en el orden en que la armaste).
    const corrida = (x) => Math.abs(x.peso_final - x.peso)
    const cambio = xs.reduce((m, x) => (corrida(x) > corrida(m) ? x : m))
    if (corrida(cambio) >= 1) {
      frases.push(`Sin tocarla, ${cambio.asset} pasó de ${pesoTxt(cambio.peso)} a ${pesoTxt(cambio.peso_final)} de la cartera.`)
    }
  }
  frases.push(fraseDeLaCaida(c, idx))
  if (res.recortado && res.recorte_por) {
    const primera = xs.find(a => a.asset === res.recorte_por)?.primera_vela || res.desde
    frases.push(`Tenemos precios de ${res.recorte_por} desde el ${fechaCorta(primera)}: la simulación arranca ese día.`)
  }
  for (const f of res.faltan || []) {
    const nombre = NOMBRE_INDICE[f.clave]
    if (!nombre) continue
    frases.push(f.motivo === 'vieja'
      ? `No tenemos precios del ${nombre} desde el ${fechaCorta(f.hasta)}: quedó afuera.`
      : `Todavía no tenemos la historia del ${nombre} para compararla.`)
  }
  return { titulo: titulo(c, idx), frases }
}

/** Por qué no se pudo simular, en una oración entera. `cuantos`: los activos de
 *  la cartera (con uno solo no hay «resto» que simular). */
export function motivoCartera(res, cuantos = 2) {
  const faltan = (res?.faltan || []).filter(f => f.asset)
  const nombres = faltan.map(f => f.asset)
  const uno = nombres.length === 1
  switch (res?.motivo) {
    case 'sin_serie':
      return `No tenemos los precios de cada día de ${enLista(nombres)}: `
        + `${uno ? 'sacalo o cambialo por otro' : 'sacalos o cambialos por otros'}.`
    case 'vieja': {
      const hasta = faltan.map(f => f.hasta).filter(Boolean).sort()[0]
      return `No tenemos precios de ${enLista(nombres)} desde el ${fechaCorta(hasta)}: `
        + `${uno ? 'sacalo' : 'sacalos'} para simular el resto.`
    }
    case 'poca_historia':
      if (!res.recorte_por) {
        return cuantos === 1
          ? 'Tenemos muy pocos días de precios de este activo: no alcanzan para simular. Cambialo por otro con más historia.'
          : 'Con estos activos tenemos muy pocos días de precios: no alcanzan para simular.'
      }
      return `Tenemos muy pocos días de precios de ${res.recorte_por}: no alcanzan para simular. `
        + (cuantos === 1 ? 'Cambialo por otro con más historia.' : 'Sacalo para probar el resto.')
    case 'tope':
      return 'Pediste muchos activos nuevos en poco tiempo: probá de nuevo en un rato.'
    case 'bajando':
      return 'Estamos trayendo los precios: probá de nuevo en unos segundos.'
    case 'demo':
      return 'En el modo demo no hay precios de todos los días para simular carteras.'
    default:
      return 'No pudimos simular la cartera.'
  }
}

/** Debajo de «Cada activo». Un activo gana peso si le va MEJOR QUE EL CONJUNTO, no
 *  sólo si sube: «el que sube pesa cada vez más» lo contradecía la tabla de arriba
 *  (GGAL +16 % pasó de 10 % a 8 %; auditoría 05/11, A4). */
export const NOTA_CADA_ACTIVO = 'Sin tocar la cartera, el que sube más que el conjunto gana peso, y el que sube '
  + 'menos (o baja), lo pierde. «Aportó»: cuántos puntos del resultado de la cartera vienen de ese activo.'

/** La aclaración de abajo: cómo se simula y que no es una recomendación. */
export const COMO_SE_SIMULA_CARTERA = 'La simulación compra todo el primer día, al cierre, con los porcentajes que '
  + 'pusiste, y no la toca más. Sin comisiones ni dividendos, ni en la cartera ni en los índices (el S&P 500 y el '
  + 'Nasdaq compuesto, en dólares). Los CEDEAR, con la acción de afuera; las acciones argentinas, en dólares MEP de '
  + 'cada día. Es lo que habría pasado con los precios de cada día: no dice nada de lo que va a pasar y no es una '
  + 'recomendación de compra o de venta.'
