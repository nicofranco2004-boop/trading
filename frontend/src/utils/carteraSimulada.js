// carteraSimulada — las palabras y las cuentas chicas de «Una cartera», dentro
// de la pestaña Backtesting de Análisis técnico (Nico, 05/11; boceto aprobado,
// opción A: https://claude.ai/artifact/46cJx7aUeeH9CkVA7LAqX5).
// ═══════════════════════════════════════════════════════════════════════════
// LA CUENTA NO ESTÁ ACÁ. Qué habría pasado con la cartera, el S&P 500 y el
// Nasdaq lo calcula el servidor (backend/cartera_simulada.py, GET
// /api/backtest/cartera), y «Mi cartera de hoy» también la arma él (GET
// /api/backtest/cartera/hoy), con LA regla de qué activos tienen precio de todos
// los días. Acá: lo que se puede escribir en cada porcentaje, cuánto falta para
// 100, la barra del 100 %, la dirección y las palabras de lo que volvió.
//
// NUNCA PROMETE, como el Backtesting de una regla (utils/backtesting.js): todo en
// pasado, siempre al lado del S&P 500 y del Nasdaq, sin «la mejor cartera». Lo que
// NO pasó va en condicional («le habría ido mejor»): en pasado real se leía como
// tu resultado, y con «Mi cartera de hoy» encima sale mejor de lo que fue
// (auditorías de producto y de método, 05/11: con los pesos de hoy desde el primer
// día decía «le ganó al S&P 500» el doble de veces de lo que pasó).
// Y habla de lo que TENEMOS, no del activo: «no tenemos los precios de AL30»,
// no «AL30 no tiene precio» (cotiza todos los días: lo que falta es nuestro
// dato; auditoría 05/11, M10).
//
// `cliente`: el asesor adentro de la cuenta de un cliente (`nombreDelCliente`).
// Ahí no es «tu cartera»: es la de él (M11).
import { fechaCorta } from './cuantoSeMueve'
import { comoSeVe, porcentaje } from './backtesting'

// Los del servidor (backend/cartera_simulada.py): cuántos activos entran y con
// qué tolerancia los porcentajes «suman 100».
export const MAX_ACTIVOS = 10
export const TOLERANCIA = 0.05

/** Las dos maneras de arrancar, en el selector. */
export const origenes = (cliente = null) => [['hoy', cliente ? 'Su cartera de hoy' : 'Mi cartera de hoy'], ['cero', 'Armar de cero']]
/** Con qué arranca: lo que dice la dirección. Un link con una cartera y sin
 *  `origen` es una armada a mano (la de hoy nunca va en la dirección). */
export const origenDe = (t, conActivos = false) => (t === 'cero' || (!t && conActivos) ? 'cero' : 'hoy')

export const QUE_SE_SIMULA = 'Poné cada activo y cuánto de la cartera va en él, sobre 100%. Te mostramos qué '
  + 'habría pasado con US$ 100 comprados así el primer día y sin tocar, al lado del S&P 500 y del Nasdaq.'

const deQuien = (cliente) => (cliente ? `la cartera de hoy de ${cliente}` : 'tu cartera de hoy')

/** Arriba de «Mi cartera de hoy». La cartera de hoy no viaja en el link (dice qué
 *  tenés): quien lo abre ve la suya. Lo que queda afuera es lo que no TENEMOS
 *  para simular (verificación y diseño 05/11, V4 y M8). */
export function notaHoy(cliente = null, cambiada = false) {
  if (cambiada) {
    return `Partiste de ${deQuien(cliente)} y la cambiaste. Los cambios no quedan en el link: al recargar vuelve `
      + 'la de hoy.'
  }
  return `Con ${cliente ? `los activos de ${cliente}` : 'tus activos'} y lo que pesa cada uno hoy. Quedan afuera los `
    + 'bonos y los fondos, porque no tenemos sus precios de cada día, y el efectivo. Cambiá lo que quieras.'
}
// Dónde se apaga: en esta pantalla no hay ojito; está en el Inicio y en Tu Cartera
// («Ocultar saldos»). «Apagalo» solo no decía dónde (auditoría de pantalla 06/11).
export const notaOjito = (cliente = null) => `Con «Ocultar saldos» prendido no traemos ${deQuien(cliente)}: los `
  + `porcentajes dicen qué ${cliente ? 'tiene' : 'tenés'}. Apagalo con el ojito del Inicio o de Tu Cartera, o armala `
  + 'de cero.'
export const notaSinActivos = (cliente = null) => `Todavía no ${cliente ? 'tiene' : 'tenés'} acciones, CEDEARs ni `
  + 'cripto para simular: armala de cero.'
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
 *  coma) y hasta 2 decimales. Más de 100 no se acepta: null, y queda lo que
 *  estaba. Antes se volvía 100: con «10» escrito y el cursor al final, un «5»
 *  dejaba 100 sin avisar (auditoría de pantalla 06/11). */
export function limpiar(txt) {
  let s = String(txt ?? '').replace('.', ',').replace(/[^0-9,]/g, '')
  const coma = s.indexOf(',')
  if (coma >= 0) s = s.slice(0, coma + 1) + s.slice(coma + 1).replace(/,/g, '').slice(0, 2)
  if (s.startsWith(',')) s = `0${s}`
  s = s.replace(/^0+(?=\d)/, '')
  return numeroDe(s) > 100 ? null : s
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

/** La barra del 100 % debajo de la tabla (pages/SimularCartera.jsx): un tramo por
 *  activo con porcentaje, EN EL ORDEN DE LA TABLA, y lo que falta para 100. Era una
 *  torta (Nico, 06/11; diseño 05/11, M1 y M3): repetía la tabla, ocupaba el lugar
 *  de la respuesta y sus colores decían cuánto pesa cada porción, no quién es, así
 *  que cambiaban de activo mientras escribías. Pasada de 100, los tramos se
 *  reparten la barra entera; cada tramo dice lo ESCRITO (con GGAL 100 y AAPL 33,5,
 *  «100%» y «33,5%», no 74,9 y 25,1; M9). `ambar`: la barra está llena pero la
 *  cartera no está lista (sobra, o un activo sin porcentaje: con 50 / 50 / 0 se
 *  veía violeta y completa; auditoría de pantalla 06/11, B3). */
export function tramosDeLaBarra(filas) {
  const total = totalDe(filas)
  // El hueco, sólo si de verdad falta: con 33,33 × 3 decía «Falta repartir 0,0%» al
  // lado de «Suma 100%» (verificación 05/11, V6).
  const falta = 100 - total > TOLERANCIA ? Math.round((100 - total) * 100) / 100 : 0
  return {
    tramos: filas.map(f => ({ asset: f.asset, peso: numeroDe(f.txt) })).filter(t => t.peso > 0),
    falta,
    ambar: !falta && !estadoDeLaCartera(filas).listo,
  }
}

/** Arriba del resultado anterior, tenue, mientras la cartera no está lista: que
 *  es el de antes y por qué (auditorías de pantalla y de método 06/11, B4 y H6).
 *  Corto, para que entre en un renglón y la respuesta no se corra (M2), y sin el
 *  número que cambia en cada tecla: el total de la izquierda ya lo dice (B11). */
export const rotuloDelAnterior = (estado) => (Math.abs(estado.total - 100) <= TOLERANCIA
  ? 'Es el resultado anterior: falta un porcentaje'
  : 'Es el resultado anterior: no suman 100%')

/** «Mi cartera de hoy» (GET /backtest/cartera/hoy) como filas para editar. */
export const filasDeHoy = (r) => (r?.activos || []).map(a => ({ asset: a.asset, local: !!a.local, txt: textoDe(a.peso) }))

/** Qué parte de tu plata se simula y qué quedó afuera de «Mi cartera de hoy», en
 *  palabras (null si nada). La parte: el servidor la cuenta sobre TODA tu plata
 *  (`parte`); sin decirla, mitad fondo y mitad CEDEARs se veía como «tu cartera»
 *  toda en CEDEARs (producto 05/11, A4; método, C6). */
export function notaDeHoy(r, cliente = null) {
  const afuera = r?.afuera || []
  const sin = afuera.filter(x => x.motivo === 'sin_serie').map(x => x.asset.replace(/^FCI:/, ''))
  const tope = afuera.filter(x => x.motivo === 'tope').map(x => x.asset)
  const out = []
  if (r?.parte != null && r.parte < 100) {
    out.push(`Lo que se simula es el ${r.parte}% de ${cliente ? 'su' : 'tu'} plata: lo demás (efectivo, plazos fijos, `
      + 'bonos o fondos) no lo podemos simular.')
  }
  if (sin.length) {
    out.push(`${sin.length === 1 ? 'Quedó' : 'Quedaron'} afuera ${enLista(sin)}: no tenemos sus precios de cada día.`)
  }
  if (tope.length) {
    out.push(`Entran hasta ${MAX_ACTIVOS} activos: ${tope.length === 1 ? 'quedó' : 'quedaron'} afuera ${enLista(tope)}, `
      + `${tope.length === 1 ? 'el que menos pesa' : 'los que menos pesan'}.`)
  }
  if (!out.length) return null
  return `${out.join(' ')}${sin.length || tope.length ? ' El resto se repartió sobre 100%.' : ''}`
}

const NOMBRE_INDICE = { sp500: 'S&P 500', nasdaq: 'Nasdaq' }
// Menos de un punto es «casi lo mismo»: un ETF del S&P 500 contra el S&P 500
// salía «le ganó» por 0,2 puntos de diferencia de seguimiento (método 05/11, C9).
const CASI_LO_MISMO = 1
// ¿Le habría ido mejor? Con los números TAL COMO SE VEN en las tarjetas
// (`comoSeVe`, el redondeo de la tarjeta).
const contra = (c, i) => {
  const d = comoSeVe(c) - comoSeVe(i)
  return Math.abs(d) < CASI_LO_MISMO ? 'empate' : d > 0 ? 'gano' : 'perdio'
}

function titulo(c, indices) {
  if (!indices.length) return 'Así habría ido esta cartera'
  const de = (k) => indices.filter(i => contra(c.resultado, i.resultado) === k).map(i => `el ${i.nombre}`)
  const [g, p, e] = [de('gano'), de('perdio'), de('empate')]
  const todos = indices.length
  if (g.length === todos) return `Le habría ido mejor que ${g.join(' y que ')}`
  if (p.length === todos) return `${capital(p.join(' y '))} le ${todos === 1 ? 'habría ganado' : 'habrían ganado'}`
  if (e.length === todos) return `Habría dado casi lo mismo que ${e.join(' y ')}`
  if (g.length && p.length) return `Le habría ido mejor que ${g[0]}, pero no que ${p[0]}`
  if (g.length) return `Le habría ido mejor que ${g[0]} y habría dado casi lo mismo que ${e[0]}`
  return `Habría dado casi lo mismo que ${e[0]}, y ${p[0]} le habría ganado`
}

// Dólares de cada US$ 100, con un decimal: un «punto» del resultado es un dólar,
// y «sumó 17,8 puntos» explicaba «puntos» con «puntos» (diseño 05/11, M7).
const dolares = (x) => `US$ ${Math.abs(x).toLocaleString('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`

/** Lo que dice debajo del título según con qué se arrancó. Con «Mi cartera de hoy»,
 *  que es tu cartera de hoy puesta en el pasado y no lo que ganaste, y para qué lado
 *  se equivoca: con los pesos de hoy desde el primer día sale igual o mejor de lo que
 *  fue (método 05/11, C1: hasta +10,7 puntos a 2 años; método 06/11, H2: a 5 años
 *  hasta +501 puntos, y 22 % de «le habría ido mejor que el S&P 500» sin haberle
 *  ganado). La frase de «da de más» la aprobó Nico el 06/11. Con una armada, que
 *  elegir los porcentajes mirando el resultado es elegir con el diario del lunes
 *  (producto 05/11, A1). */
export function aclaracionDeLaCartera(origen, cliente = null) {
  if (origen === 'hoy') {
    return `Es ${deQuien(cliente)} puesta en el pasado: con los pesos de hoy desde el primer día, con lo que `
      + `${cliente ? 'compró' : 'compraste'} después y sin lo que ${cliente ? 'vendió' : 'vendiste'}. Por cómo se `
      + 'arma, da de más: lo que hoy pesa más, en buena parte pesa más porque subió. No es lo que '
      + `${cliente ? 'ganó' : 'ganaste'}: eso está en Métricas.`
  }
  return 'Elegir los porcentajes mirando este resultado es elegir con el diario del lunes.'
}

/** Lo que dicen los números, en palabras, en condicional: qué habría pasado, nunca
 *  qué va a pasar ni cuál cartera es mejor. `origen`: 'hoy' o 'cero'.
 *  {titulo, aclaracion, avisos, deLosActivos}:
 *    · `titulo`, `aclaracion` y `avisos` (desde cuándo arranca, qué índice falta)
 *      van en la respuesta, al lado de la tabla, con los números de la cartera y
 *      de los índices; ahí se ve la peor caída de los tres juntos, así que ya no
 *      va también en una frase (era para juntar las de tres tarjetas, M2);
 *    · `deLosActivos` (cuánto sumó o restó cada uno, cuál cambió de peso) va con
 *      «Cada activo», al lado de sus números.
 *  Los «US$ 100 habrían quedado en» no se repiten: están en el gráfico (M10). */
export function lecturaCartera(res, { origen = 'cero', cliente = null } = {}) {
  if (!res?.disponible) return null
  const c = res.cartera
  const idx = res.indices || []
  const xs = res.activos || []
  const deLosActivos = []
  if (xs.length > 1) {
    const orden = [...xs].sort((a, b) => b.aporte - a.aporte)
    const [mas, menos] = [orden[0], orden.at(-1)]
    if (mas.aporte > 0 && menos.aporte < 0) {
      deLosActivos.push(`De cada US$ 100, ${mas.asset} habría sumado ${dolares(mas.aporte)} y ${menos.asset} habría `
        + `restado ${dolares(menos.aporte)}: entre todos, la cartera habría dado ${porcentaje(c.resultado)}.`)
    } else if (mas.aporte > 0) {
      deLosActivos.push(`De cada US$ 100, el que más habría sumado es ${mas.asset}: ${dolares(mas.aporte)} de los `
        + `${dolares(c.resultado)} que habría ganado la cartera.`)
    } else if (menos.aporte < 0) {
      deLosActivos.push(`De cada US$ 100, el que más habría restado es ${menos.asset}: ${dolares(menos.aporte)} de los `
        + `${dolares(c.resultado)} que habría perdido la cartera.`)
    }
    // El que más cambió de peso sin tocar la cartera (el mayor, no un orden: la
    // lista de «Cada activo» va en el orden en que la armaste).
    const corrida = (x) => Math.abs(x.peso_final - x.peso)
    const cambio = xs.reduce((m, x) => (corrida(x) > corrida(m) ? x : m))
    if (corrida(cambio) >= 1) {
      deLosActivos.push(`Sin tocarla, ${cambio.asset} habría pasado de ${pesoTxt(cambio.peso)} a `
        + `${pesoTxt(cambio.peso_final)} de la cartera.`)
    }
  }
  const avisos = []
  if (res.recortado && res.recorte_por) {
    const primera = xs.find(a => a.asset === res.recorte_por)?.primera_vela || res.desde
    avisos.push(`Tenemos precios de ${res.recorte_por} desde el ${fechaCorta(primera)}: la simulación arranca ese día.`)
  }
  for (const f of res.faltan || []) {
    const nombre = NOMBRE_INDICE[f.clave]
    if (!nombre) continue
    avisos.push(f.motivo === 'vieja'
      ? `No tenemos precios del ${nombre} desde el ${fechaCorta(f.hasta)}: quedó afuera.`
      : `Todavía no tenemos la historia del ${nombre} para compararla.`)
  }
  return { titulo: titulo(c, idx), aclaracion: aclaracionDeLaCartera(origen, cliente), avisos, deLosActivos }
}

/** Debajo de los números de la respuesta: de cuándo a cuándo, y que los índices
 *  van sin dividendos, como la cartera (lo decía cada tarjeta de un índice). Sin
 *  ningún índice, lo de la cartera sola (método 06/11, H7). */
export const notaDelResumen = (res) => `Del ${fechaCorta(res.desde)} al ${fechaCorta(res.hasta)}, en dólares`
  + (res.indices?.length ? '. Los índices, sin dividendos, como la cartera.' : ' y sin dividendos.')

// «1 año» con un espacio que no se corta: partido en dos renglones no se lee (auditoría
// de pantalla 06/11, O4).
export const NOTA_ANIO_POR_ANIO = 'Cada año son 365 días, contados para atrás desde el último precio, con las fechas de '
  + '«1 año»: los índices dan lo mismo que ahí, la cartera no siempre. Acá es la misma cartera sin tocar, y cada '
  + 'año arranca con los pesos que le dejó el anterior; «1 año» la arma de nuevo con sus porcentajes. «Por año, '
  + 'en promedio»: lo que habría que ganar (o perder) todos los años, igual, para llegar al mismo total.'

/** Cuántos meses dura el tramo corto del principio, para su renglón: «7 meses». Hasta
 *  11: uno de 351 días no es un año entero y «12 meses» decía que sí (auditoría 06/11, B6). */
function mesesDe(dias) {
  const m = Math.min(11, Math.max(1, Math.round(dias / 30.44)))
  return m === 1 ? '1 mes' : `${m} meses`
}

/** El año en que más habría subido la cartera y en el que más habría bajado (si
 *  subió todos los años, el que menos), con los números de la tabla, en %. Sólo años
 *  enteros. Antes decía cuántos dólares de cada US$ 100 sumó cada año, como «Cada
 *  activo»: después de un año muy bueno, uno malo «restaba US$ 329,1 de cada US$ 100»,
 *  y el año nombrado no era el de la tabla (auditoría de pantalla 06/11, A1). */
function fraseDeLosAnios(anios) {
  const con = anios.filter(f => f.cartera != null)
  if (con.length < 2) return null
  const orden = [...con].sort((a, b) => b.cartera - a.cartera)
  const [mas, menos] = [orden[0], orden.at(-1)]
  if (comoSeVe(mas.cartera) === comoSeVe(menos.cartera)) return null
  const cual = (f) => `el ${f.numero} (del ${fechaCorta(f.desde)} al ${fechaCorta(f.hasta)}): ${porcentaje(f.cartera)}`
  if (mas.cartera > 0 && menos.cartera < 0) {
    return `El año que más habría subido la cartera es ${cual(mas)}. El que más habría bajado, ${cual(menos)}.`
  }
  if (menos.cartera >= 0) return `El año que más habría subido la cartera es ${cual(mas)}. El que menos, ${cual(menos)}.`
  return `El año que más habría bajado la cartera es ${cual(menos)}. El que menos, ${cual(mas)}.`
}

/** Contra un índice, cuántos años habría ganado cada uno (Nico, 06/11: «una
 *  devolución de quién gana»), con los números como se ven y la regla de «casi lo
 *  mismo» del título (`contra`). Primero el que ganó más años; el resto, «el otro» o
 *  «los otros N» (auditoría de pantalla 06/11, B1 y B2). */
function cuantosAnios(r, n, nombre) {
  const el = `el ${nombre}`
  if (r.gano === n) return `La cartera le habría ganado al ${nombre} en cada uno de los ${n} años.`
  if (r.perdio === n) return `${capital(el)} le habría ganado a la cartera en cada uno de los ${n} años.`
  if (r.empate === n) return `La cartera y ${el} habrían dado casi lo mismo en cada uno de los ${n} años.`
  const [lider, otro, g, p] = r.perdio > r.gano
    ? [`${capital(el)} le habría ganado a la cartera`, `la cartera al ${nombre}`, r.perdio, r.gano]
    : [`La cartera le habría ganado al ${nombre}`, `${el} a la cartera`, r.gano, r.perdio]
  const otros = (k) => (k === 1 ? 'el otro' : `los otros ${k}`)
  const resto = p && r.empate ? `; ${otro}, en ${p}, y en ${otros(r.empate)} habrían dado casi lo mismo`
    : p ? `; ${otro}, en ${otros(p)}`
      : `, y en ${otros(r.empate)} habrían dado casi lo mismo`
  return `${lider} en ${g} de los ${n} años${resto}.`
}

/** Cuando los años y el total dicen otra cosa, el total, y por qué: un año malo pesa
 *  más que tres buenos. Sin esto, «la cartera le habría ganado 3 de 5 años» quedaba en
 *  negrita debajo de un título que decía que perdió (auditoría de pantalla 06/11, A2 y M1). */
function yEnElTotal(r, total, nombre) {
  const cuenta = r.gano > r.perdio ? 'gano' : r.perdio > r.gano ? 'perdio' : 'empate'
  if (cuenta === total) return ''
  if (total === 'gano') {
    return cuenta === 'perdio'
      ? ' Aun así, en el total a la cartera le habría ido mejor: los años que ganó, habría ganado por más.'
      : ' En el total, a la cartera le habría ido mejor.'
  }
  if (total === 'perdio') {
    return cuenta === 'gano'
      ? ` Aun así, en el total le habría ganado el ${nombre}: los años que perdió, la cartera habría perdido por más.`
      : ` En el total, le habría ganado el ${nombre}.`
  }
  return ' En el total, habrían dado casi lo mismo.'
}

/** Al final de «Año por año», contra cada índice: cuántos años habría ganado cada
 *  uno y, si el total dice otra cosa, el total. Cuenta años enteros. No dice «en
 *  promedio»: el promedio de la tabla es otro número, el rendimiento por año. */
function veredicto(filas, res) {
  const anios = filas.filter(f => f.completo)
  const n = anios.length
  if (n < 2) return []
  return (res.indices || []).flatMap(i => {
    if (anios.some(f => f[i.clave] == null || f.cartera == null)) return []
    const r = { gano: 0, perdio: 0, empate: 0 }
    for (const f of anios) r[contra(f.cartera, f[i.clave])] += 1
    return [cuantosAnios(r, n, i.nombre) + yEnElTotal(r, contra(res.cartera.resultado, i.resultado), i.nombre)]
  })
}

/** «Año por año» (Nico, 06/11/2026), entre la respuesta y el gráfico: el total del
 *  período, cada año y, al final, quién habría ganado más años. La cuenta es del
 *  servidor (`cartera_simulada._anio_por_anio`); acá, los rótulos y las palabras.
 *  null con un solo año (sería el total otra vez). `origen` y `cliente`, los de la
 *  respuesta: con «Mi cartera de hoy» también avisa que da de más (M2).
 *  {frase, total, filas, promedio, aviso, veredicto, nota}: `frase`, el año que más
 *  subió y el que más bajó; cada fila, su `rotulo` («Año 2», o «7 meses» el tramo
 *  corto del principio). */
export function lecturaAnioPorAnio(res, { origen = 'cero', cliente = null } = {}) {
  const apa = res?.disponible ? res.anio_por_anio : null
  if (!apa?.tramos?.length) return null
  let n = 0
  const filas = apa.tramos.map(t => {
    const numero = t.completo ? ++n : null
    return { ...t, numero, rotulo: numero ? `Año ${numero}` : mesesDe(t.dias) }
  })
  const corto = filas.some(f => !f.completo)
  // El año 1 que se juntó con unos días de antes (menos de un mes) dura más que 365.
  const largo = filas[0].completo && filas[0].dias > 372 ? filas[0].dias : null
  return {
    frase: fraseDeLosAnios(filas.filter(f => f.completo)),
    total: { rotulo: res.recortado ? 'Todo el período' : `Los ${res.anios} años`, desde: res.desde, hasta: res.hasta },
    filas,
    promedio: apa.por_anio,
    aviso: origen === 'hoy' ? `Es ${deQuien(cliente)} puesta en el pasado: año por año, también da de más.` : null,
    veredicto: veredicto(filas, res),
    nota: NOTA_ANIO_POR_ANIO
      + (corto ? ' Lo de antes del primer año entero va aparte, con sus meses.' : '')
      + (largo ? ` El año 1 tiene ${largo} días: suma los de antes del primer año entero.` : ''),
  }
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
      // Cada uno con su fecha: con la noche caída y uno que ya estaba parado, la más
      // vieja para todos decía mal la del otro (auditoría 06/11, H5).
      const porFecha = new Map()
      for (const f of faltan) porFecha.set(f.hasta || '', [...(porFecha.get(f.hasta || '') || []), f.asset])
      const frase = 'No tenemos precios de ' + [...porFecha].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([h, xs]) => (h ? `${enLista(xs)} desde el ${fechaCorta(h)}` : enLista(xs))).join(' ni de ')
      // Viejo se mide contra hoy (auditoría 05/11, H9): puede ser el único activo, o
      // todos (la noche no trajo nada). Ahí no hay «resto» que simular, y cambiarlo no
      // sirve si la falla es nuestra (H4, 06/11): se dice qué hace falta.
      if (nombres.length >= cuantos) return `${frase}: para simular hacen falta los de la última semana.`
      return `${frase}: ${uno ? 'sacalo' : 'sacalos'} para simular el resto.`
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

/** Debajo de «Cada activo». Un activo gana peso si le va MEJOR QUE EL CONJUNTO, suba
 *  o baje: «el que sube pesa cada vez más» lo contradecía la tabla (GGAL +16 % pasó
 *  de 10 % a 8 %; auditoría 05/11, A4), y «el que baja lo pierde», también (BTC −22,6 %
 *  pasó de 50 % a 59,7 %, con GGAL bajando más; verificación 05/11, V1). Lo prueba
 *  utils/carteraSimulada.test.js contra lo que contesta el servidor. */
// «Aportó», en condicional: la cartera no existió (auditoría de pantalla 06/11).
export const NOTA_CADA_ACTIVO = 'Sin tocar la cartera, gana peso el que rinde más que el conjunto, aunque baje, y lo '
  + 'pierde el que rinde menos, aunque suba. «Aportó»: cuánto de cada US$ 100 habría ganado o perdido la cartera por '
  + 'ese activo.'

/** La aclaración de abajo: cómo se simula y que no es una recomendación. */
export const COMO_SE_SIMULA_CARTERA = 'La simulación compra todo el primer día, al cierre, con los porcentajes que '
  + 'pusiste, y no la toca más. Sin comisiones ni dividendos, ni en la cartera ni en los índices (el S&P 500 y el '
  + 'Nasdaq compuesto, en dólares). Los CEDEAR, con la acción de afuera; las acciones argentinas, en dólares MEP de '
  + 'cada día. Es lo que habría pasado con los precios de cada día: no dice nada de lo que va a pasar y no es una '
  + 'recomendación de compra o de venta.'
