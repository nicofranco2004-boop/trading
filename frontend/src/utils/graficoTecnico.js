// La pestaña «Gráfico» de Análisis técnico (Nico, 30/10): sólo el gráfico, con
// el activo arriba a la izquierda como en TradingView, y que se acuerde en qué
// activo lo dejaste. Acá, sin React: qué activo abrir, los últimos que miraste
// y qué ofrece el buscador de la pestaña.
// ════════════════════════════════════════════════════════════════════════════
// Se guarda en ESTE navegador, por persona y por cuenta (claveDeActivos, la del
// ⌘K: en una compu compartida el siguiente no ve lo que miró el anterior; un
// asesor adentro de un cliente tiene su lista aparte). No va al servidor: no
// abre ningún pedido nuevo ni guarda nada en tu cuenta.
//
// Los dibujos de cada activo NO viven acá: se guardan solos en tu cuenta, por
// activo y por moneda (utils/dibujos.js). Cambiar de activo no borra nada.

import { normalizar, puntaje } from './buscadorRapido'
import { POPULAR_TICKERS, tickerName, inferType, isBondPosition } from './tickers'
import { isFciSym } from './valuation'
import { esLoteLocal, esLocalSinTenencia } from './accionLocal'
import { isCrypto } from './crypto'

export const RECIENTES_MAXIMOS = 8
// Con nada guardado ni nada tuyo para mostrar: el S&P 500.
export const ACTIVO_DE_ENTRADA = 'SPY'

const clave = (persona) => (persona ? `rendi_grafico:${persona}` : null)

// Forma de ticker, la misma de `_SYMBOL_RE` del servidor (main.py): lo que no
// la tiene no se guarda ni se abre (una dirección inventada, un fondo «FCI:»).
const FORMA = /^[A-Z0-9]{1,12}([.-][A-Z0-9]{1,4})?$/
export function activoValido(s) {
  if (typeof s !== 'string') return null
  const t = s.trim().toUpperCase()
  return FORMA.test(t) ? t : null
}

/** El nombre con que la pestaña abre un papel que pediste (el buscador, la
 *  dirección, lo guardado): UNO por papel, porque los dibujos se guardan por
 *  nombre y con dos, lo dibujado en uno no se vería en el otro.
 *    · una cripto, por su código corto: tu lista guarda «BTC-USD», el
 *      catálogo dice «BTC»;
 *    · una acción argentina, sin «.BA»: la estrella de la ficha guarda
 *      «GGAL.BA», el buscador «GGAL», y las dos son el papel de BYMA (la regla
 *      de lo que no tenés, esLocalSinTenencia). Un CEDEAR no: AAPL.BA y AAPL
 *      son dos papeles.
 *  Si lo TENÉS con otro nombre (un lote «BTC-USD»), la ficha lo encuentra y la
 *  pestaña abre ése (GraficoTecnico, otroNombre). */
export function canonico(s) {
  const t = activoValido(s)
  if (!t) return null
  const cripto = t.replace(/-(USD|USDT|USDC)$/, '')
  if (cripto !== t && isCrypto(cripto)) return cripto
  const local = t.replace(/\.BA$/, '')
  if (local !== t && esLocalSinTenencia(local)) return local
  return t
}

/** Lo guardado de esta persona: { activo, recientes }. Sin persona, sin
 *  almacenamiento o con algo roto: vacío. */
export function guardado(persona) {
  const k = clave(persona)
  if (!k) return { activo: null, recientes: [] }
  try {
    const g = JSON.parse(localStorage.getItem(k) || 'null')
    const recientes = (Array.isArray(g?.recientes) ? g.recientes : [])
      .map(canonico).filter(Boolean)
    return {
      activo: canonico(g?.activo),
      recientes: [...new Set(recientes)].slice(0, RECIENTES_MAXIMOS),
    }
  } catch {
    return { activo: null, recientes: [] }
  }
}

/** Abriste `activo`: queda como el último y primero de los recientes. Devuelve
 *  lo que quedó guardado (o lo que hubiera quedado, si no se pudo guardar). */
export function recordar(persona, activo) {
  const a = canonico(activo)
  const antes = guardado(persona)
  if (!a) return antes
  const nuevo = { activo: a, recientes: [a, ...antes.recientes.filter(x => x !== a)].slice(0, RECIENTES_MAXIMOS) }
  const k = clave(persona)
  if (k) {
    try { localStorage.setItem(k, JSON.stringify(nuevo)) } catch { /* sin almacenamiento */ }
  }
  return nuevo
}

/** Qué activo abre la pestaña: el de la dirección (?activo=GGAL, un link o
 *  recargar la página), si no el último que miraste, si no el primero de tu
 *  cartera que tiene gráfico técnico (un bono no: no tiene), si no el S&P 500. */
export function activoDeEntrada({ deLaDireccion, persona, posiciones = [] }) {
  return canonico(deLaDireccion)
    || guardado(persona).activo
    || tuyos(posiciones).find(f => f.tipo !== 'bond')?.simbolo
    || ACTIVO_DE_ENTRADA
}

// ─── El buscador de la pestaña ──────────────────────────────────────────────

// Los filtros de arriba del buscador. `tipos`: qué tipos entran (los del
// cartelito de toda la app, ASSET_TYPE_META de utils/tickers.js).
export const FILTROS = [
  { id: 'todo', label: 'Todo' },
  { id: 'cartera', label: 'Tu cartera' },
  { id: 'lista', label: 'Tu lista' },
  { id: 'ar', label: 'Acciones AR', tipos: ['stock_ar'] },
  { id: 'eeuu', label: 'CEDEARs y EE.UU.', tipos: ['cedear', 'stock_us'] },
  { id: 'cripto', label: 'Cripto', tipos: ['crypto'] },
  { id: 'etf', label: 'ETFs', tipos: ['etf'] },
]

const DEL_CATALOGO = new Map(POPULAR_TICKERS.map(t => [t.symbol.toUpperCase(), t]))
const nombreDe = (s) => DEL_CATALOGO.get(s)?.name || tickerName(s) || null

/** Tus activos con gráfico, uno por ticker, en el orden de tus lotes: sin el
 *  efectivo ni los fondos (FCI), que no tienen serie de precios. */
export function tuyos(posiciones = []) {
  const vistos = new Set()
  const out = []
  for (const p of posiciones || []) {
    const s = activoValido(p?.asset)
    if (!s || p.is_cash || isFciSym(p.asset) || vistos.has(s)) continue
    vistos.add(s)
    // El tipo lo dice tu lote: un bono es bono (también en BYMA); GGAL de IOL
    // es la acción argentina y GGAL de Schwab el ADR (la regla única de
    // utils/accionLocal.js).
    const tipo = isBondPosition(p) ? 'bond' : esLoteLocal(p) ? 'stock_ar' : p.asset_type === 'CEDEAR' ? 'cedear' : null
    out.push(fila(s, { tipo, origen: 'cartera' }))
  }
  return out
}

// Una fila del buscador. `tipo`: el del cartelito (si no lo dice tu lote, la
// regla de la app para un ticker, inferType).
function fila(simbolo, { tipo = null, origen }) {
  return { simbolo, nombre: nombreDe(simbolo), tipo: tipo || inferType(simbolo), origen }
}

/**
 * Lo que muestra el buscador, en secciones ({ titulo, filas }).
 * Sin nada escrito: los últimos que miraste, tu cartera y tu lista.
 * Con algo escrito: lo que coincide (tuyo primero, después tu lista y el
 * catálogo; la misma regla de puntaje que el ⌘K) y, si lo escrito tiene forma
 * de ticker y no está, «Abrir XYZ». Los bonos que no tenés no se ofrecen: no
 * tienen gráfico técnico (la misma regla del ⌘K, destinoDeTicker).
 */
export function opcionesDelBuscador({ consulta = '', filtro = 'todo', recientes = [], posiciones = [], lista = [] }) {
  const mios = tuyos(posiciones)
  const deMiLista = []
  // Uno por papel (canonico): tu lote «BTC-USD» y el «BTC» del catálogo son uno.
  const vistos = new Set(mios.map(f => canonico(f.simbolo)))
  for (const item of lista || []) {
    const s = canonico(item?.symbol)
    if (!s || vistos.has(s)) continue
    vistos.add(s)
    deMiLista.push(fila(s, { origen: 'lista' }))
  }
  const f = FILTROS.find(x => x.id === filtro) || FILTROS[0]
  const pasa = (x) => (f.id === 'cartera' ? x.origen === 'cartera'
    : f.id === 'lista' ? x.origen === 'lista'
      : f.tipos ? f.tipos.includes(x.tipo) : true)

  const q = normalizar(consulta)
  if (!q) {
    const secciones = []
    if (f.id === 'todo') {
      const ult = recientes.map(s => [...mios, ...deMiLista].find(x => canonico(x.simbolo) === s) || fila(s, { origen: 'reciente' }))
      if (ult.length) secciones.push({ titulo: 'Últimos que miraste', filas: ult })
    }
    const c = mios.filter(pasa)
    if (c.length) secciones.push({ titulo: 'Tu cartera', filas: c })
    const l = deMiLista.filter(pasa)
    if (l.length) secciones.push({ titulo: 'Tu lista', filas: l })
    if (f.tipos) {
      const cat = POPULAR_TICKERS.map(t => fila(t.symbol.toUpperCase(), { origen: 'catalogo' }))
        .filter(x => x.tipo !== 'bond' && pasa(x) && !vistos.has(x.simbolo))
      if (cat.length) secciones.push({ titulo: 'Otros', filas: cat })
    }
    return secciones
  }

  const catalogo = POPULAR_TICKERS
    .map(t => fila(t.symbol.toUpperCase(), { origen: 'catalogo' }))
    .filter(x => x.tipo !== 'bond' && !vistos.has(x.simbolo))
  const PRIORIDAD = { cartera: 0, lista: 1, catalogo: 2 }
  const escrito = activoValido(consulta)
  // El mismo papel con otro nombre cuenta como lo escrito, primero de todo:
  // «GGAL.BA» encuentra GGAL y «BTC-USD» encuentra BTC. «AAPL.BA» (el CEDEAR)
  // NO encuentra AAPL (la acción de Nueva York): son dos papeles.
  const mismo = (x) => (escrito && canonico(x.simbolo) === canonico(escrito) ? 4 : 0)
  const encontrados = [...mios, ...deMiLista, ...catalogo]
    .filter(pasa)
    .map((x, i) => ({ x, i, p: mismo(x) || puntaje({ titulo: x.simbolo, claves: x.nombre ? [x.nombre] : [] }, q) }))
    .filter(e => e.p > 0)
    .sort((a, b) => b.p - a.p || PRIORIDAD[a.x.origen] - PRIORIDAD[b.x.origen] || a.i - b.i)
    .map(e => e.x)
    .slice(0, 30)
  // Lo escrito tal cual, sólo si no se encontró NADA, sin filtro (con «Cripto»
  // elegido, «Abrir GG» no es una cripto) y con largo de ticker: «vista»
  // encuentra VIST y «agrometal» no es un ticker (abría un gráfico vacío).
  const pareceTicker = escrito && (escrito.length <= 6 || /[.-]/.test(escrito))
  const abrir = pareceTicker && f.id === 'todo' && !encontrados.length
    ? [{ simbolo: canonico(escrito), nombre: null, tipo: null, origen: 'escrito' }] : []
  const filas = [...encontrados, ...abrir]
  return filas.length ? [{ titulo: 'Resultados', filas }] : []
}
