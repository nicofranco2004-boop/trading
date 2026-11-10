// La pestaña «Gráfico» de Análisis técnico (Nico, 30/10): sólo el gráfico, con
// el activo arriba a la izquierda como en TradingView, y que se acuerde en qué
// activo lo dejaste. Acá, sin React: qué activo abrir, los últimos que miraste
// y qué ofrece el buscador de la pestaña.
// ════════════════════════════════════════════════════════════════════════════
// Se guarda en ESTE navegador, a nombre de la persona y la cuenta (`dueno`,
// utils/duenoDeLaPestana, por la única puerta utils/almacen): en una compu
// compartida el siguiente no ve lo que miró el anterior; un asesor adentro de
// un cliente tiene su lista aparte. No va al servidor: no
// abre ningún pedido nuevo ni guarda nada en tu cuenta.
//
// Los dibujos de cada activo NO viven acá: se guardan solos en tu cuenta, por
// activo y por moneda (utils/dibujos.js). Cambiar de activo no borra nada.
//
// Cada activo se abre con el NOMBRE con que lo abriría la ficha desde el mismo
// lugar (tu lista dice «GGAL.BA», el catálogo «GGAL», tus lotes como los
// cargaste): los dibujos se guardan por nombre, y así los de la ficha y los de
// la pestaña son los mismos. Si lo tenés con otro nombre, decide la ficha
// (useFichaDelActivo, otroNombre), que sabe en qué mercado está cada lote. No
// hay una regla propia para «es el mismo papel» que pase por arriba de ésa:
// la hubo (canonico, 30/10) y mezclaba GGAL.BA de BYMA con tu GGAL de Nueva
// York, y AGRO.BA (Agrometal) con tu AGRO de Schwab (Adecoagro).

import { normalizar, puntaje, mismoPapel, miradaSinTenencia } from './buscadorRapido'
import { POPULAR_TICKERS, catalogoDelBuscador, tickerName, inferType, isBondPosition } from './tickers'
import { isFciSym, isBymaHolding } from './valuation'
import { esLoteLocal } from './accionLocal'
import { leerDe, guardarDe } from './almacen'
import { CATALOGO } from './catalogoDelAlmacen'

export const RECIENTES_MAXIMOS = 8
// Con nada guardado ni nada tuyo para mostrar: el S&P 500.
export const ACTIVO_DE_ENTRADA = 'SPY'


// Forma de ticker, la misma de `_SYMBOL_RE` del servidor (main.py): lo que no
// la tiene no se guarda ni se abre (una dirección inventada, un fondo «FCI:»).
const FORMA = /^[A-Z0-9]{1,12}([.-][A-Z0-9]{1,4})?$/
export function activoValido(s) {
  if (typeof s !== 'string') return null
  const t = s.trim().toUpperCase()
  return FORMA.test(t) ? t : null
}

/** Lo guardado de `dueno` (la persona y la cuenta): { activo, recientes }. Sin
 *  dueño, sin almacenamiento o con algo roto: vacío. */
export function guardado(dueno) {
  if (!dueno) return { activo: null, recientes: [] }
  try {
    const g = JSON.parse(leerDe(CATALOGO.graficoRecientes, dueno) || 'null')
    const recientes = (Array.isArray(g?.recientes) ? g.recientes : [])
      .map(activoValido).filter(Boolean)
    return {
      activo: activoValido(g?.activo),
      recientes: [...new Set(recientes)].slice(0, RECIENTES_MAXIMOS),
    }
  } catch {
    return { activo: null, recientes: [] }
  }
}

/** Abriste `activo`: queda como el último y primero de los recientes. Devuelve
 *  lo que quedó guardado (o lo que hubiera quedado, si no se pudo guardar). */
export function recordar(dueno, activo) {
  const a = activoValido(activo)
  const antes = guardado(dueno)
  if (!a) return antes
  const nuevo = { activo: a, recientes: [a, ...antes.recientes.filter(x => x !== a)].slice(0, RECIENTES_MAXIMOS) }
  // La puerta no lo guarda si `dueno` ya no es el de la pestaña.
  if (dueno) {
    try { guardarDe(CATALOGO.graficoRecientes, dueno, JSON.stringify(nuevo)) } catch { /* sin almacenamiento */ }
  }
  return nuevo
}

/** Qué activo abre la pestaña: el de la dirección (?activo=GGAL, un link o
 *  recargar la página), si no el último que miraste, si no el primero de tu
 *  cartera que tiene gráfico técnico (un bono no: no tiene), si no el S&P 500. */
export function activoDeEntrada({ deLaDireccion, persona, posiciones = [] }) {
  return activoValido(deLaDireccion)
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
// El nombre de la empresa: el del catálogo o, con otro nombre del mismo papel
// (GGAL.BA, BTC-USD), el del papel (Galicia, Bitcoin).
const nombreDe = (s) => DEL_CATALOGO.get(s)?.name || tickerName(s)
  || DEL_CATALOGO.get(mismoPapel(s))?.name || tickerName(mismoPapel(s)) || null

// ¿Abren el mismo gráfico? El mismo papel (mismoPapel: GGAL y GGAL.BA, BTC y
// BTC-USD, DISN y DIS) Y el mismo mercado: lo tuyo, donde está tu lote
// (isBymaHolding); lo que no tenés, donde lo mira la ficha (miradaSinTenencia:
// GGAL y GGAL.BA en BYMA; AAPL en Nueva York y AAPL.BA, el CEDEAR, en BYMA).
// Sirve para no mostrar dos filas que abren lo mismo, no para cambiar el nombre
// con que se abre.
const enByma = (s) => miradaSinTenencia(s).simboloPrecio.endsWith('.BA')
const grafico = (simbolo, byma) => `${mismoPapel(simbolo)}|${byma ? 'byma' : 'afuera'}`

/** ¿`a` y `b` abren el mismo gráfico? El mismo nombre, o el mismo papel en el
 *  mismo mercado según la regla de lo que no tenés (GGAL y GGAL.BA sí; AAPL y
 *  AAPL.BA, la acción y su CEDEAR, no). La usa la lista al costado del gráfico
 *  para saber cuál de sus renglones es el que estás mirando: tocar GGAL.BA
 *  puede abrir tu GGAL de IOL (useFichaDelActivo, otroNombre). */
export function mismoGrafico(a, b) {
  const x = activoValido(a)
  const y = activoValido(b)
  if (!x || !y) return false
  return x === y || grafico(x, enByma(x)) === grafico(y, enByma(y))
}

/** Tus activos con gráfico, uno por ticker, en el orden de tus lotes: sin el
 *  efectivo ni los fondos (FCI), que no tienen serie de precios. */
export function tuyos(posiciones = []) {
  const vistos = new Set()
  const out = []
  for (const p of posiciones || []) {
    const s = activoValido(p?.asset)
    if (!s || p.is_cash || isFciSym(p.asset) || vistos.has(s)) continue
    vistos.add(s)
    const byma = isBymaHolding(p)
    // El tipo lo dice tu lote: un bono es bono (también en BYMA); GGAL de IOL
    // es la acción argentina y GGAL de Schwab el ADR (la regla única de
    // utils/accionLocal.js). Un ticker argentino que tenés AFUERA de BYMA es
    // de Nueva York: AGRO de Schwab es Adecoagro, no Agrometal (el nombre del
    // catálogo es el de BYMA y no se pone).
    const deAca = inferType(s) === 'stock_ar' || inferType(s) === 'cedear'
    const tipo = isBondPosition(p) ? 'bond' : esLoteLocal(p) ? 'stock_ar' : p.asset_type === 'CEDEAR' ? 'cedear'
      : !byma && deAca ? 'stock_us' : null
    const f = fila(s, { tipo, origen: 'cartera', byma })
    out.push(!byma && deAca ? { ...f, nombre: null } : f)
  }
  return out
}

// Una fila del buscador. `tipo`: el del cartelito (si no lo dice tu lote, la
// regla de la app para un ticker, inferType). `grafico`: qué abre (ver arriba).
function fila(simbolo, { tipo = null, origen, byma = enByma(simbolo) }) {
  return { simbolo, nombre: nombreDe(simbolo), tipo: tipo || inferType(simbolo), origen, grafico: grafico(simbolo, byma) }
}

/**
 * Lo que muestra el buscador, en secciones ({ titulo, filas }).
 * Sin nada escrito: los últimos que miraste, tu cartera y tu lista.
 * Con algo escrito: lo que coincide (tuyo primero, después tu lista y el
 * catálogo; la misma regla de puntaje que el ⌘K) y, si lo escrito tiene forma
 * de ticker y no está, «Abrir XYZ». Los bonos que no tenés no se ofrecen: no
 * tienen gráfico técnico (la misma regla del ⌘K, destinoDeTicker).
 */
export function opcionesDelBuscador({ consulta = '', filtro = 'todo', recientes = [], posiciones = [], lista = [], cliente = null }) {
  const mios = tuyos(posiciones)
  const deMiLista = []
  // Sin dos filas que abren lo mismo: lo tuyo primero, después tu lista, al
  // final el catálogo. Un nombre que ya está (tu GGAL de Schwab) tampoco se
  // repite: abrirlo cae en tus lotes igual.
  const vistos = new Set(mios.flatMap(f => [f.grafico, f.simbolo]))
  const yaEsta = (x) => vistos.has(x.grafico) || vistos.has(x.simbolo)
  for (const item of lista || []) {
    const s = activoValido(item?.symbol)
    if (!s) continue
    const x = fila(s, { origen: 'lista' })
    if (yaEsta(x)) continue
    vistos.add(x.grafico); vistos.add(x.simbolo)
    deMiLista.push(x)
  }
  // Un asesor adentro de la cuenta de un cliente: no es «tu» cartera (la
  // misma regla del ⌘K).
  const titulo = { cartera: cliente ? `Cartera de ${cliente}` : 'Tu cartera', lista: cliente ? `Lista de ${cliente}` : 'Tu lista' }
  const f = FILTROS.find(x => x.id === filtro) || FILTROS[0]
  const pasa = (x) => (f.id === 'cartera' ? x.origen === 'cartera'
    : f.id === 'lista' ? x.origen === 'lista'
      : f.tipos ? f.tipos.includes(x.tipo) : true)

  const q = normalizar(consulta)
  if (!q) {
    const secciones = []
    if (f.id === 'todo') {
      const ult = recientes.map(s => [...mios, ...deMiLista].find(x => x.simbolo === s) || fila(s, { origen: 'reciente' }))
      if (ult.length) secciones.push({ titulo: 'Últimos que miraste', filas: ult })
    }
    const c = mios.filter(pasa)
    if (c.length) secciones.push({ titulo: titulo.cartera, filas: c })
    const l = deMiLista.filter(pasa)
    if (l.length) secciones.push({ titulo: titulo.lista, filas: l })
    if (f.tipos) {
      const cat = POPULAR_TICKERS.map(t => fila(t.symbol.toUpperCase(), { origen: 'catalogo' }))
        .filter(x => x.tipo !== 'bond' && pasa(x) && !yaEsta(x))
      if (cat.length) secciones.push({ titulo: 'Otros', filas: cat })
    }
    return secciones
  }

  // Con algo escrito, el catálogo de los buscadores que suman a la watchlist
  // (tickers.catalogoDelBuscador: los populares y además TODOS los CEDEARs, las
  // acciones argentinas y las de EE.UU.), no sólo los populares: «apple» ofrece
  // la acción en dólares Y el CEDEAR en pesos (AAPL.BA), que abren dos gráficos
  // distintos. Lo usa también la lista al costado del gráfico para agregar
  // (Nico, 10/11): un solo buscador.
  const catalogo = catalogoDelBuscador(consulta)
    .map(t => fila(t.symbol.toUpperCase(), { tipo: t.type, origen: 'catalogo' }))
    .filter(x => x.tipo !== 'bond' && activoValido(x.simbolo) && !yaEsta(x))
  const PRIORIDAD = { cartera: 0, lista: 1, catalogo: 2 }
  const escrito = activoValido(consulta)
  // Primero de todo, lo escrito tal cual (tu AGRO de Schwab, si escribiste
  // «agro»); después lo que abre el mismo gráfico: «GGAL.BA» encuentra tu GGAL
  // de IOL (BYMA) y «BTC-USD» el BTC del catálogo. Tu GGAL de Schwab (Nueva
  // York) no: «GGAL.BA» es el de BYMA.
  const loEscrito = escrito && grafico(escrito, enByma(escrito))
  const mismo = (x) => (escrito && x.simbolo === escrito ? 5 : loEscrito && x.grafico === loEscrito ? 4 : 0)
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
    ? [{ simbolo: escrito, nombre: null, tipo: null, origen: 'escrito', grafico: loEscrito }] : []
  const filas = [...encontrados, ...abrir]
  return filas.length ? [{ titulo: 'Resultados', filas }] : []
}

/** El motivo de una falla, corto, para el renglón «Detalle» del aviso: lo que
 *  hace falta para saber qué pasó sin abrir nada (02/11: «Tu cartera» quedaba
 *  vacía y no había cómo saber si el pedido había fallado). */
export function motivoDeLaFalla(err) {
  if (err?.status) return `error ${err.status}`
  const m = String(err?.message || '').trim()
  return m ? m.slice(0, 80) : 'sin respuesta'
}

/**
 * Qué decir arriba de las opciones cuando tu cartera o tu lista no están por
 * algo que no es lo que escribiste: todavía no llegaron, no se pudieron traer
 * o no tienen nada con gráfico. Antes un pedido que fallaba se tomaba como
 * «no tenés nada» y el filtro «Tu cartera» quedaba vacío sin decir por qué.
 * `cartera` / `lista`: { estado: 'cargando' | 'listo' | 'error', motivo };
 * `posiciones` y `seguidos`: lo que llegó de cada uno.
 * → { texto, reintentar, detalle } o null.
 */
export function avisoDelBuscador({ filtro = 'todo', consulta = '', secciones = [], cartera, lista, posiciones = [], seguidos = [], cliente = null }) {
  const de = (que) => (cliente ? `la ${que} de ${cliente}` : `tu ${que}`)
  // Qué filtros muestran cada una: tu cartera, todos menos «Tu lista»; tu
  // lista, todos menos «Tu cartera» (los de tipo también muestran lo que seguís).
  const fallo = []
  if (cartera?.estado === 'error' && filtro !== 'lista') fallo.push(['cartera', cartera.motivo])
  if (lista?.estado === 'error' && filtro !== 'cartera') fallo.push(['lista', lista.motivo])
  if (fallo.length) {
    return {
      texto: `No pudimos traer ${fallo.map(([q]) => de(q)).join(' ni ')}.`,
      reintentar: true,
      detalle: fallo.map(([q, m]) => (fallo.length > 1 ? `${q}: ${m}` : m)).join(' · '),
    }
  }
  if (filtro !== 'cartera' && filtro !== 'lista') return null
  const estado = filtro === 'cartera' ? cartera?.estado : lista?.estado
  // Todavía no llegó: también con algo escrito (si no, «No encontramos ese
  // activo» cuando lo que pasa es que falta la respuesta).
  if (estado === 'cargando') return { texto: `Trayendo ${de(filtro)}…`, reintentar: false, detalle: null }
  if (normalizar(consulta) || secciones.some(s => s.filas.some(x => x.origen === filtro))) return null
  if (filtro === 'lista') {
    const validos = (seguidos || []).filter(x => activoValido(x?.symbol))
    const Lista = cliente ? `La lista de ${cliente}` : 'Tu lista'
    return {
      texto: !(seguidos || []).length ? `${Lista} está vacía.`
        : validos.length ? `Lo de ${de('lista')} ya está en ${de('cartera')}.`
          : `${Lista} no tiene activos con gráfico.`,
      reintentar: false, detalle: null,
    }
  }
  // Lo que llegó y no se muestra, dicho con su número: si un día vuelve a
  // quedar vacío con activos, el renglón dice cuántos lotes llegaron.
  const activos = (posiciones || []).filter(p => p && !p.is_cash)
  if (!activos.length) {
    return { texto: `${cliente ? `La cartera de ${cliente}` : 'Tu cartera'} no tiene activos todavía.`, reintentar: false, detalle: null }
  }
  const soloFondos = activos.every(p => isFciSym(p.asset))
  return {
    texto: soloFondos
      ? `En ${de('cartera')} no hay activos con gráfico: los fondos no tienen.`
      : `En ${de('cartera')} no hay activos con gráfico.`,
    reintentar: false,
    detalle: soloFondos ? null : `llegaron ${activos.length} ${activos.length === 1 ? 'lote' : 'lotes'} sin un ticker que se pueda abrir`,
  }
}
