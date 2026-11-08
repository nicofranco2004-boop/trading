// listaTecnica.js — «Tu lista, con su lectura técnica»: lo que tenés y lo que
// seguís (watchlist), juntos en una tabla (inicio → Watchlist → «Ver como tablero»).
// ════════════════════════════════════════════════════════════════════════════
// Nada se recalcula acá:
//   · los NÚMEROS técnicos vienen de POST /api/tecnico/lista (backend/tecnico.py,
//     la misma `lectura` que la ficha y la radiografía);
//   · las PALABRAS son las de la ficha: `tendencia` (la tarjeta «Largo plazo»),
//     la tarjeta «Corto plazo» de `tarjetas`, `veredictoRsi`, `fmtAdx` y la
//     línea de 23 del ADX (`ADX_CLAVE`);
//   · CUÁNTO PESA cada activo y QUÉ tenés: lo manda el servidor (`tenencias`
//     de POST /api/tecnico/lista, con la valuación de senales_semana.cartera,
//     LA misma del % alcista y de la pestaña Señales): el 12 % de Tu lista es
//     el 12 % de Señales.
//   · el ÚLTIMO CAMBIO lo cuenta el servidor con `cambios_desde`, la cuenta
//     única de «qué cambió esta semana».
// Ninguna palabra habla del futuro ni dice qué hacer: describe cómo se movió.

import { inferType, CRYPTO, STOCKS_US, ETFS, INDICES, CEDEARS_LIST, ARG_LIDER, ARG_GENERAL } from './tickers'
import { esLocalSinTenencia } from './accionLocal'
import { isCrypto } from './crypto'
import { hoyISO } from './fecha'
import { tarjetas, fmtAdx, ADX_CLAVE, RSI_GANA } from './tecnico'
import { fciLabel } from './valuation'
import { clave, tendencia, fuerza, lecturaVieja, MOTIVOS_SIN_LECTURA } from './radiografia'
import { leer, guardar } from './almacen'
import { CATALOGO } from './catalogoDelAlmacen'
import { ordenConElOjito } from './parteDeTuPlata'

/**
 * Cómo se lee un símbolo de la watchlist, con la regla de la ficha para lo que
 * no tenés: una acción argentina (GGAL o GGAL.BA) se mira en BYMA ÷ MEP, no por
 * su ADR; un CEDEAR (AAPL.BA) por su acción de afuera; una cripto guardada con
 * '-USD' (BTC-USD) es la misma BTC que tenés. → { asset, local, simbolo }
 * (`asset` sin '.BA' ni '-USD': la clave con que la Cartera nombra el activo).
 * `tipo`: el `asset_type` de la fila, si lo trae. Uno que no es de acción
 * argentina manda sobre la lista: «AGRO» de tipo STOCK es Adecoagro de Nueva
 * York, no Agrometal. Espejo de backend/accion_local.seguido (misma tabla de
 * casos: fixtures/accionLocal.json).
 */
export function lecturaDeSeguido(simbolo, tipo = null) {
  const s = String(simbolo || '').trim().toUpperCase()
  const local = esLocalSinTenencia(s, tipo)
  let asset = s.endsWith('.BA') ? s.slice(0, -3) : s
  if (asset.endsWith('-USD') && isCrypto(asset.slice(0, -4))) asset = asset.slice(0, -4)
  return { asset, local, simbolo: s }
}

/**
 * ¿`simbolo` ya está en tu lista? 'cartera' | 'watchlist' | null. Con la MISMA
 * regla con la que filasDeLaLista junta lo que tenés y lo que seguís (la clave
 * activo + mercado): GGAL.BA y tu GGAL de BYMA son uno; GGAL (el ADR) es otro.
 * La usa el buscador de «Tu lista» para avisar en vez de duplicar.
 */
export function dondeEstaEnLaLista(filas = [], simbolo) {
  const { asset, local } = lecturaDeSeguido(simbolo)
  if (!asset) return null
  const f = filaOcupada(new Map(filas.map(x => [x.clave, x])), asset, local)
  return f ? (f.tenes ? 'cartera' : 'watchlist') : null
}

/**
 * La fila que ya ocupa lo que seguís (`asset`, `local`), si hay. La misma clave
 * (activo + mercado) o, si es un BONO, el mismo activo en el otro mercado. Por
 * qué los bonos: el servidor marca como de BYMA todo lo que tenés que cotiza
 * con «.BA» —bonos incluidos (accion_local.es_lote_local)—, y lo que seguís
 * sólo es de BYMA si es una acción argentina (esLocalSinTenencia). Tu AL30 de
 * IOL quedaba «AL30|1» y el AL30 de tu watchlist «AL30|0»: dos filas del mismo
 * bono (revisión del 02/11). Para un bono el mercado no cambia nada acá: no
 * tiene lectura técnica. La usan filasDeLaLista y dondeEstaEnLaLista.
 */
function filaOcupada(porClave, asset, local) {
  return porClave.get(clave(asset, local))
    || (inferType(asset) === 'bond' ? porClave.get(clave(asset, !local)) : null)
    || null
}

// Lo que el servidor deja leer por pedido (tecnico.MAX_ACTIVOS_CARTERA). La
// watchlist tiene tope de 100 (main.WATCHLIST_TOPE): entra en uno.
export const MAX_POR_PEDIDO = 200

/** Lo que se le pide al servidor: lo que seguís, cada uno una vez, con la marca
 *  `local` de la ficha. Lo que TENÉS lo pone el servidor (sus `tenencias`). */
export function activosDeLaLista(seguidos = []) {
  const vistos = new Map()
  for (const it of seguidos) {
    const { asset, local } = lecturaDeSeguido(it?.symbol, it?.asset_type)
    if (asset && !vistos.has(clave(asset, local))) vistos.set(clave(asset, local), { asset, local })
  }
  return [...vistos.values()].sort((a, b) => clave(a.asset, a.local).localeCompare(clave(b.asset, b.local)))
}

/** Un lote de mentira para lo que seguís y no tenés: sólo para que «Sin
 *  lectura» diga bien por qué (un bono o un fondo no se miden). */
function loteDeSeguido(it, asset) {
  const tipo = String(it?.asset_type || '').toUpperCase()
  const inferido = inferType(asset)
  return { asset, asset_type: tipo || (inferido === 'bond' ? 'BONO' : inferido === 'fci' ? 'FCI' : null) }
}

// El nombre de la empresa o del fondo, de las listas del buscador. Una acción
// argentina (GGAL en BYMA) va con su nombre de BYMA, no con el de su ADR.
const NOMBRES = new Map()
for (const x of [...CRYPTO, ...INDICES, ...ETFS, ...STOCKS_US, ...CEDEARS_LIST]) if (!NOMBRES.has(x.s)) NOMBRES.set(x.s, x.n)
const NOMBRES_BYMA = new Map([...ARG_LIDER, ...ARG_GENERAL].map(x => [x.s, x.n]))
export function nombreDeActivo(asset, local = false) {
  const a = String(asset || '').toUpperCase()
  return (local ? NOMBRES_BYMA.get(a) : null) || NOMBRES.get(a) || NOMBRES_BYMA.get(a) || null
}

// «Esta semana»: los últimos 7 días contados desde hoy, la misma semana de la
// pestaña Señales (tecnico.DIAS_CAMBIOS del servidor, QUE_ES_ESTA_SEMANA).
export const DIAS_SEMANA = 7

const DIA = 86400000
const dias = (desde, hasta) => Math.round((Date.parse(hasta + 'T00:00:00Z') - Date.parse(desde + 'T00:00:00Z')) / DIA)

/** «hoy», «ayer», «hace 3 días», «hace 2 semanas», «hace 5 meses». */
export function haceCuanto(fecha, hoy = hoyISO()) {
  if (!fecha) return null
  const d = dias(fecha, hoy)
  if (d <= 0) return 'hoy'
  if (d === 1) return 'ayer'
  if (d < 14) return `hace ${d} días`
  if (d < 60) return `hace ${Math.floor(d / 7)} semanas`
  const m = Math.floor(d / 30)
  return m >= 12 ? 'hace un año' : `hace ${m} meses`
}

/**
 * El cambio en palabras, las que manda el servidor (`senales_semana.texto_del_cambio`,
 * las mismas de «Tus señales» y del mail de los sábados). En la celda va la
 * frase corta que arma el servidor (`corta`, la misma del asunto del mail);
 * la entera, con su aclaración (`extra`), en el globo. Antes la celda cortaba
 * el texto en los dos puntos y en el ADX quedaba «Tiene el ADX en 23,3»
 * (auditoría D6, 29/10). Un servidor viejo sin `corta`: el corte de antes.
 * null sin texto.
 */
export function textoDelCambio(c) {
  if (!c?.texto) return null
  const mayus = (t) => t.charAt(0).toUpperCase() + t.slice(1)
  const corta = c.corta || c.texto.split(':')[0].replace(/\.$/, '')
  return { corta: mayus(corta), completa: [mayus(c.texto), c.extra].filter(Boolean).join(' '), tono: c.tono || null }
}

/**
 * Las filas de la tabla. `tenencias`: lo que tenés y cuánto pesa, como lo manda
 * el servidor ([{ asset, local, peso (fracción), tipo }], de más a menos);
 * `seguidos`: los ítems de /watchlist; `indice`: clave → lectura del servidor.
 * Cada fila:
 *   { clave, nombre, ruta, tenes, peso (0–100), vigente, motivo,
 *     fondo, corto, rsi, adx, desdeMax, linea, cambio }
 * `vigente` false = «Sin lectura» (sin velas, bono/fondo o sin precios de la
 * última semana, `vieja` del servidor): esa fila no muestra números y `motivo`
 * dice por qué.
 */
export function filasDeLaLista({ tenencias = [], seguidos = [], indice, hoy = hoyISO() }) {
  const filas = new Map()
  const armar = (k, base) => {
    const x = indice?.get(k) || null
    const vigente = !!(x?.disponible && x.lectura && !lecturaVieja(x))
    const fondo = tendencia(x, base.p)
    const l = vigente ? x.lectura : null
    const corto = l ? tarjetas(l).find(t => t.id === 'corto') : null
    const linea = vigente && x.linea?.length > 1 ? x.linea : null
    const c = vigente ? x.ultimo_cambio : null
    const [asset, local] = [k.slice(0, -2), k.endsWith('|1')]
    filas.set(k, {
      ...base, clave: k, vigente, asset, local,
      empresa: nombreDeActivo(asset, local),
      lectura: l,
      precio: l?.precio ?? null,
      // Cuánto cambió el precio en los 3 meses de la línea chica.
      var3m: linea && linea[0].c ? (linea[linea.length - 1].c / linea[0].c - 1) * 100 : null,
      nuevo: !!(c?.fecha && dias(c.fecha, hoy) < DIAS_SEMANA),
      motivo: vigente ? null : fondo.motivo,
      porque: vigente ? null : fondo.porque,
      fondo,
      corto: corto ? { palabra: corto.veredicto, motivo: corto.texto } : null,
      rsi: vigente ? fuerza(x) : null,
      adx: l?.adx != null ? { valor: l.adx, texto: fmtAdx(l.adx), palabra: l.adx >= ADX_CLAVE ? 'marcada' : 'lateral' } : null,
      desdeMax: l?.dist_maximo_12m != null ? { pct: l.dist_maximo_12m, enMaximo: l.dist_maximo_12m >= -0.1, anioCompleto: !!l.anio_completo } : null,
      linea,
      cambio: c?.fecha ? { ...textoDelCambio(c), fecha: c.fecha, hace: haceCuanto(c.fecha, hoy) } : null,
    })
  }
  for (const t of tenencias) {
    const asset = String(t.asset || '').toUpperCase()
    if (!asset) continue
    armar(clave(asset, t.local), {
      nombre: fciLabel(asset), ruta: asset, tenes: true, peso: (t.peso || 0) * 100,
      p: { asset, asset_type: t.tipo || null },
    })
  }
  for (const it of seguidos) {
    const { asset, local, simbolo } = lecturaDeSeguido(it?.symbol, it?.asset_type)
    const k = clave(asset, local)
    if (!asset || filaOcupada(filas, asset, local)) continue
    armar(k, { nombre: isCrypto(asset) ? asset : simbolo, ruta: simbolo, tenes: false, peso: 0, p: loteDeSeguido(it, asset) })
  }
  return conDetalle([...filas.values()])
}

/** Dos filas con el mismo ticker (GGAL de IOL y el ADR GGAL de Schwab) son dos
 *  papeles distintos con dos lecturas: cada una dice dónde cotiza. */
function conDetalle(filas) {
  const base = (n) => n.replace(/\.BA$/, '')
  const cuantas = {}
  for (const f of filas) cuantas[base(f.nombre)] = (cuantas[base(f.nombre)] || 0) + 1
  return filas.map(f => (cuantas[base(f.nombre)] > 1
    ? { ...f, detalle: f.clave.endsWith('|1') ? 'en BYMA' : String(f.p?.asset_type).toUpperCase() === 'CEDEAR' ? 'CEDEAR' : 'en Nueva York' }
    : f))
}

/** Cuántas hay en cada filtro. «Watchlist» = lo que seguís y no tenés. */
export function contarFilas(filas) {
  const tenes = filas.filter(f => f.tenes).length
  return { todo: filas.length, tenes, watchlist: filas.length - tenes }
}

export const FILTROS = [
  { id: 'todo', label: 'Todo' },
  { id: 'tenes', label: 'Tu cartera' },
  { id: 'watchlist', label: 'Watchlist' },
]

export function filtrarFilas(filas, filtro) {
  if (filtro === 'tenes') return filas.filter(f => f.tenes)
  if (filtro === 'watchlist') return filas.filter(f => !f.tenes)
  return filas
}

// Cada orden con su valor y su sentido de entrada (el que se lee primero).
// `desc`: de mayor a menor. `conOjito`: el nombre con «Ocultar saldos», cuando
// el orden es por tu plata (ahí va lo tuyo primero, de la A a la Z).
export const ORDENES = [
  { id: 'cambio', label: 'Cambio más reciente', valor: f => f.cambio?.fecha ?? null, desc: true },
  { id: 'fuerza', label: 'Impulso (RSI)', valor: f => f.rsi?.rsi ?? null, desc: true },
  { id: 'maximo', label: 'Desde el máximo', valor: f => f.desdeMax?.pct ?? null, desc: true },
  { id: 'peso', label: 'Mayor peso en tu cartera', conOjito: 'Tu cartera primero', valor: f => (f.tenes ? f.peso : null), desc: true },
]

/** El nombre de un orden en el «Ordenar por», con o sin el ojito. */
export const nombreDelOrden = (o, oculto = false) => (oculto && o.conOjito) || o.label

/**
 * Ordena por `por` (un id de ORDENES). `desc` null = el sentido de entrada de
 * ese orden. Lo que no tiene el dato va al final (en cualquier sentido) y las
 * filas «Sin lectura», al final de todo; los empates, por nombre.
 *
 * `oculto` («Ocultar saldos»): «por peso» diría cuál pesa más aunque no se vea
 * un solo %; con el ojito va lo tuyo primero y cada parte de la A a la Z
 * (ordenConElOjito, utils/parteDeTuPlata; auditoría D5, 31/10).
 */
export function ordenarFilas(filas, por = 'cambio', desc = null, oculto = false) {
  const o = ORDENES.find(x => x.id === por) || ORDENES[0]
  if (oculto && o.id === 'peso') {
    return ordenConElOjito(filas, true, { nombre: f => f.nombre, antes: (a, b) => Number(!!b.tenes) - Number(!!a.tenes) })
  }
  const bajando = desc ?? o.desc
  return [...filas].sort((a, b) => {
    if (a.vigente !== b.vigente && por !== 'peso') return a.vigente ? -1 : 1
    const va = o.valor(a), vb = o.valor(b)
    if (va == null || vb == null) {
      if (va != null) return -1
      if (vb != null) return 1
      return a.nombre.localeCompare(b.nombre)
    }
    if (va === vb) return a.nombre.localeCompare(b.nombre)
    return (va < vb ? -1 : 1) * (bajando ? -1 : 1)
  })
}

/** El «por qué» de las filas sin lectura, agrupado como en la radiografía. */
export function motivosSinLectura(filas) {
  const por = {}
  for (const f of filas) if (!f.vigente) (por[f.porque] ||= []).push(f.nombre)
  return Object.keys(MOTIVOS_SIN_LECTURA).filter(k => por[k])
    .map(k => ({ porque: k, nombres: por[k], texto: MOTIVOS_SIN_LECTURA[k] }))
}

/**
 * El trazo de la línea chica (ancho × alto en px). null si no hay línea.
 * `area`: lo de abajo de la línea, para el relleno del mini-gráfico. Con
 * `promedio`, también `ma`: el promedio de 200 días de cada punto (`m`, del
 * servidor) en la MISMA escala, así se ve si el precio está arriba o abajo;
 * los días sin promedio cortan la línea. null si no viene ninguno.
 */
export function trazoDeLinea(linea, ancho = 64, alto = 22, { promedio = false } = {}) {
  if (!linea || linea.length < 2) return null
  const cs = linea.map(p => p.c)
  const ms = promedio ? linea.map(p => (Number.isFinite(p.m) ? p.m : null)) : []
  const todos = [...cs, ...ms.filter(m => m != null)]
  const lo = Math.min(...todos), hi = Math.max(...todos)
  const rango = hi - lo || 1
  const x = (i) => (i / (linea.length - 1)) * ancho
  const y = (c) => alto - 1 - ((c - lo) / rango) * (alto - 2)
  const d = linea.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.c).toFixed(1)}`).join('')
  const ma = ms.map((m, i) => (m == null ? '' : `${i && ms[i - 1] != null ? 'L' : 'M'}${x(i).toFixed(1)},${y(m).toFixed(1)}`)).join('')
  return { d, area: `${d}L${ancho},${alto}L0,${alto}Z`, ma: ma || null, sube: cs[cs.length - 1] >= cs[0] }
}

/**
 * Las barritas de «Fuerza» de la tarjeta (de 1 a 5): cada una vale media línea
 * del ADX (23), así que hasta la segunda es «sin dirección clara» y desde la
 * tercera, dirección marcada. → { prendidas, clara } o null sin ADX.
 */
export function barrasDeFuerza(adx) {
  if (adx == null) return null
  return { prendidas: Math.min(5, Math.floor(adx / (ADX_CLAVE / 2)) + 1), clara: adx >= ADX_CLAVE }
}

/**
 * La franja de arriba de Tu lista: cuántos tienen tendencia alcista de largo
 * plazo (y de cuántos con lectura, con un puntito por cada uno), cuántos ganan
 * impulso, cuáles están en su máximo del año y cuántos cambiaron esta semana.
 * Las filas llegan con lo tuyo de más a menos peso: con `oculto` («Ocultar
 * saldos») los nombres de «en su máximo» van de la A a la Z.
 */
export function resumenDeLaLista(filas = [], oculto = false) {
  const leidas = filas.filter(f => f.fondo?.id === 'alcista' || f.fondo?.id === 'bajista')
  const alcistas = leidas.filter(f => f.fondo.id === 'alcista').length
  return {
    alcistas,
    conLectura: leidas.length,
    puntos: [...Array(alcistas).fill('alcista'), ...Array(leidas.length - alcistas).fill('bajista')],
    ganando: filas.filter(f => f.rsi && f.rsi.rsi > RSI_GANA).length,
    enMaximo: ordenConElOjito(filas.filter(f => f.vigente && f.desdeMax?.enMaximo).map(f => f.nombre), oculto),
    cambiaron: filas.filter(f => f.nuevo).length,
  }
}

// Cómo se ve la lista: de entrada en tarjetas (Nico, 30/10). Lo que elige cada
// persona queda en ESTE navegador; sin almacenamiento, siempre en tarjetas.
export const VISTAS = [{ id: 'tarjetas', label: 'Tarjetas' }, { id: 'tabla', label: 'Tabla' }]
export function vistaGuardada(persona) {
  if (!persona) return 'tarjetas'
  try { return leer(CATALOGO.vistaDeLaLista, persona) === 'tabla' ? 'tabla' : 'tarjetas' } catch { return 'tarjetas' }
}

export function guardarVista(persona, vista) {
  if (!persona) return
  try { guardar(CATALOGO.vistaDeLaLista, vista === 'tabla' ? 'tabla' : 'tarjetas', persona) } catch { /* sin almacenamiento */ }
}

