// listaDelGrafico.js — tu lista al costado del gráfico (pestaña «Gráfico» de
// Análisis técnico, como en TradingView; Nico, 10/11; lienzo aprobado:
// https://claude.ai/artifact/3XbhPrhCWDdgYSUshPTgxQ). Acá, sin React: las
// banderas, cómo se agrupa y se ordena, qué renglón es el que estás mirando y
// lo que dice la ficha corta de abajo.
// ════════════════════════════════════════════════════════════════════════════
// Es la MISMA watchlist de toda la app (GET /api/watchlist): lo que agregás acá
// aparece en «Tu lista» y en el inicio, y al revés. Lo propio de esta lista:
//   · la BANDERA de cada activo: una de siete, o ninguna (como TradingView);
//   · el NOMBRE de cada bandera, que pone la persona («EE.UU.», «Para comprar»);
//   · «como los acomodás»: el lugar de cada activo (`orden`).
// Las tres cosas van en la cuenta (backend/main.py, BANDERAS_DE_LA_LISTA y
// /api/watchlist): se ven igual en la compu y en el celular.
// «Cómo se ve» (agrupar, ordenar, mostrar Var. y la ficha) y si la lista está
// abierta quedan en ESTE navegador: son preferencias de la pantalla, no datos
// (utils/catalogoDelAlmacen, `vistaListaDelGrafico`).
//
// Separar EE.UU. de CEDEARs no necesita banderas: «Por tipo de activo» se arma
// solo, con la regla de toda la app para saber qué es cada símbolo
// (tickers.inferType, accionLocal.esLocalSinTenencia).

import { inferType, isBondPosition } from './tickers'
import { esLocalSinTenencia, esLoteLocal } from './accionLocal'
import { isBymaHolding } from './valuation'
import { isCrypto } from './crypto'
import { lecturaDeSeguido } from './listaTecnica'
import { clave, tendencia, fuerza } from './radiografia'
import { mismoGrafico } from './graficoTecnico'
import { nfmt, pctVar, pctVarSign, pctSigned } from './format'
import { leer, guardar } from './almacen'
import { CATALOGO } from './catalogoDelAlmacen'

// ─── Las banderas ───────────────────────────────────────────────────────────
// Los ids son los del servidor (main.BANDERAS_DE_LA_LISTA), en su orden: es el
// de los grupos y el del menú. El color es una variable del tema (frontend/
// CLAUDE.md, R8): sigue al modo claro y al oscuro. Ninguno es un color nuevo:
// son los de las categorías y los datos de la app. `color` es la palabra que
// se muestra mientras la bandera no tiene nombre.
export const BANDERAS = Object.freeze([
  { id: 'azul', color: 'Azul', variable: '--data-blue' },
  { id: 'naranja', color: 'Naranja', variable: '--cat-orange' },
  { id: 'verde', color: 'Verde', variable: '--rendi-pos' },
  { id: 'violeta', color: 'Violeta', variable: '--cat-indigo' },
  { id: 'rosa', color: 'Rosa', variable: '--cat-pink' },
  { id: 'cian', color: 'Celeste', variable: '--data-cyan' },
  { id: 'rojo', color: 'Roja', variable: '--rendi-neg' },
])
const POR_ID = new Map(BANDERAS.map(b => [b.id, b]))
export const esBandera = (id) => POR_ID.has(id)

/** El color de la bandera `id` para un `style` (con `alfa`, para un fondo). */
export function colorDeBandera(id, alfa = 1) {
  const b = POR_ID.get(id)
  return b ? `rgb(var(${b.variable}) / ${alfa})` : null
}

/** {id → nombre que le puso la persona} de lo que manda el servidor
 *  (`banderas`: [{ id, nombre }]). Sólo los que tienen nombre. */
export function nombresDeBanderas(banderas = []) {
  const out = {}
  for (const b of banderas || []) if (esBandera(b?.id) && b.nombre) out[b.id] = b.nombre
  return out
}

/** Cómo se llama la bandera: su nombre o, sin nombre, su color («Azul»).
 *  `conNombre` dice cuál de las dos: la pantalla escribe el color en gris. */
export function nombreDeBandera(id, nombres = {}) {
  const b = POR_ID.get(id)
  if (!b) return { texto: 'Sin bandera', conNombre: false }
  return nombres[id] ? { texto: nombres[id], conNombre: true } : { texto: b.color, conNombre: false }
}

// ─── Qué es cada activo (agrupar «Por tipo de activo») ──────────────────────
// En este orden van los grupos. `tag`: el cartelito al lado del ticker cuando
// una sección mezcla tipos (un CEDEAR al lado de la acción de EE.UU.).
export const TIPOS = Object.freeze([
  { id: 'eeuu', titulo: 'Acciones de EE.UU.', corto: 'Acción de EE.UU.', tag: null },
  { id: 'etf', titulo: 'ETFs e índices', corto: 'ETF', tag: 'ETF' },
  { id: 'cedear', titulo: 'CEDEARs', corto: 'CEDEAR', tag: 'CEDEAR' },
  { id: 'arg', titulo: 'Acciones argentinas', corto: 'Acción argentina', tag: 'ARG' },
  { id: 'cripto', titulo: 'Cripto', corto: 'Cripto', tag: 'CRIPTO' },
  { id: 'bono', titulo: 'Bonos', corto: 'Bono', tag: 'BONO' },
  { id: 'otro', titulo: 'Otros', corto: 'Otro', tag: null },
])
const TIPO = new Map(TIPOS.map(t => [t.id, t]))
export const tipoInfo = (id) => TIPO.get(id) || TIPO.get('otro')

/** El tipo de un activo de tu lista, con la regla de la app: «GGAL» y «GGAL.BA»
 *  son la acción argentina; «AAPL.BA» el CEDEAR; «AGRO» guardado como STOCK es
 *  Adecoagro de Nueva York, no Agrometal (esLocalSinTenencia). */
export function tipoDeSimbolo(simbolo, assetType = null) {
  const t = inferType(String(simbolo || '').toUpperCase())
  if (t === 'crypto') return 'cripto'
  if (t === 'stock_ar') return esLocalSinTenencia(simbolo, assetType) ? 'arg' : 'eeuu'
  if (t === 'cedear') return 'cedear'
  if (t === 'bond') return 'bono'
  if (t === 'etf' || t === 'index') return 'etf'
  if (t === 'fci') return 'otro'
  return 'eeuu'
}

// La moneda sale del símbolo, como en el inicio (home/Watchlist.monedaDe): lo
// que termina en `.BA` cotiza en BYMA, en pesos.
const enPesos = (simbolo) => String(simbolo || '').toUpperCase().endsWith('.BA')

/** Un activo de la watchlist (lo que manda GET /api/watchlist) como renglón. */
export function filaDe(it) {
  const simbolo = String(it?.symbol || '').toUpperCase()
  const { asset } = lecturaDeSeguido(simbolo, it?.asset_type)
  return {
    simbolo,
    ticker: asset || simbolo,
    assetType: it?.asset_type || null,
    tipo: tipoDeSimbolo(simbolo, it?.asset_type),
    pesos: enPesos(simbolo),
    precio: Number.isFinite(it?.price) ? it.price : null,
    cambio: Number.isFinite(it?.change) ? it.change : null,
    pct: Number.isFinite(it?.change_pct) ? it.change_pct : null,
    bandera: esBandera(it?.bandera) ? it.bandera : null,
    orden: Number.isFinite(it?.orden) ? it.orden : null,
    agregado: it?.added_at || '',
    id: it?.id ?? 0,
    mercado: it?.mercado || null,
    enHorario: !!it?.en_horario,
    cierra: it?.cierra || null,
    asOf: it?.as_of || null,
    pendiente: !!it?._pending,
  }
}

/** Tus activos en «como los acomodás»: los que nunca se movieron (sin lugar)
 *  primero, en el orden en que se agregaron; después los que tienen lugar.
 *  Lo nuevo entra al final (el servidor le da el lugar siguiente). */
export function enSuLugar(filas = []) {
  return [...filas].sort((a, b) => (a.orden ?? -1) - (b.orden ?? -1)
    || String(a.agregado).localeCompare(String(b.agregado)) || a.id - b.id)
}

export const AGRUPAR = Object.freeze([
  { id: 'bandera', titulo: 'Por bandera', detalle: 'Los grupos que armás vos' },
  { id: 'tipo', titulo: 'Por tipo de activo', detalle: 'Solo: EE.UU., CEDEARs, argentinas, cripto' },
  { id: 'nada', titulo: 'Sin grupos', detalle: 'Una sola lista' },
])
export const ORDENAR = Object.freeze([
  { id: 'tuyo', titulo: 'Como los acomodás', detalle: 'Arrastrá un renglón para moverlo' },
  { id: 'ticker', titulo: 'Por ticker', detalle: 'De la A a la Z' },
  { id: 'hoy', titulo: 'Lo que más subió hoy', detalle: 'Arriba lo que más subió' },
])

function ordenarFilas(filas, orden) {
  const x = enSuLugar(filas)
  if (orden === 'ticker') x.sort((a, b) => a.ticker.localeCompare(b.ticker) || a.simbolo.localeCompare(b.simbolo))
  // Sin cotización, al final.
  if (orden === 'hoy') x.sort((a, b) => (b.pct ?? -Infinity) - (a.pct ?? -Infinity))
  return x
}

function monedasDe(filas) {
  const m = [...new Set(filas.map(f => (f.pesos ? 'en pesos' : 'en dólares')))]
  return m.length > 1 ? 'en dólares y en pesos' : m[0] || ''
}

/**
 * Las secciones de la lista y los botones de arriba.
 * `agrupar`: 'bandera' | 'tipo' | 'nada'; `filtro`: 'todas' o la clave de un
 * grupo; `orden`: 'tuyo' | 'ticker' | 'hoy'; `nombres`: los de las banderas.
 * → { filtro (el que vale: uno que ya no existe vuelve a 'todas'), chips:
 *     [{ id, texto, conNombre, bandera, n }], secciones: [{ id, titulo,
 *     conNombre, bandera, sub, n, filas, mixta }] }
 */
export function armarLista({ filas = [], agrupar = 'bandera', filtro = 'todas', orden = 'tuyo', nombres = {} }) {
  const grupos = []
  if (agrupar === 'bandera') {
    for (const b of BANDERAS) {
      const its = filas.filter(f => f.bandera === b.id)
      const n = nombreDeBandera(b.id, nombres)
      if (its.length) grupos.push({ id: b.id, titulo: n.texto, conNombre: n.conNombre, bandera: b.id, its })
    }
    const sin = filas.filter(f => !f.bandera)
    if (sin.length) grupos.push({ id: 'sin', titulo: 'Sin bandera', conNombre: true, bandera: null, its: sin })
  } else if (agrupar === 'tipo') {
    for (const t of TIPOS) {
      const its = filas.filter(f => f.tipo === t.id)
      if (its.length) grupos.push({ id: t.id, titulo: t.titulo, conNombre: true, bandera: null, its })
    }
  } else {
    grupos.push({ id: 'todo', titulo: null, conNombre: true, bandera: null, its: filas })
  }
  const conChips = agrupar !== 'nada'
  const vale = conChips && grupos.some(g => g.id === filtro) ? filtro : 'todas'
  const chips = conChips
    ? [{ id: 'todas', texto: 'Todas', conNombre: true, bandera: null, n: filas.length },
      ...grupos.map(g => ({ id: g.id, texto: g.titulo, conNombre: g.conNombre, bandera: g.bandera, n: g.its.length }))]
    : []
  const secciones = grupos
    .filter(g => vale === 'todas' || g.id === vale)
    .filter(g => g.its.length)
    .map(g => ({
      id: g.id, titulo: g.titulo, conNombre: g.conNombre, bandera: g.bandera,
      sub: monedasDe(g.its), n: g.its.length,
      filas: ordenarFilas(g.its, orden),
      // El cartelito del tipo (CEDEAR, ARG) cuando la sección mezcla tipos, o
      // sin grupos: con todo junto, TSLA y TSLA (CEDEAR) tienen que distinguirse.
      mixta: agrupar === 'nada' || new Set(g.its.map(f => f.tipo)).size > 1,
    }))
  return { filtro: vale, chips, secciones }
}

/** Con qué bandera entra lo que agregás: la que estás mirando (agrupado por
 *  bandera y con su botón apretado), o ninguna. */
export function banderaAlAgregar({ agrupar, filtro }) {
  return agrupar === 'bandera' && esBandera(filtro) ? filtro : null
}

/**
 * Mover `simbolo` antes (o después, `despues`) de `destino` en «como los
 * acomodás». `lista`: los símbolos en su lugar (enSuLugar). → la lista nueva,
 * o la misma si no hay nada que mover.
 */
export function mover(lista, simbolo, destino, { despues = false } = {}) {
  if (!simbolo || simbolo === destino || !lista.includes(simbolo) || !lista.includes(destino)) return lista
  const sin = lista.filter(s => s !== simbolo)
  const i = sin.indexOf(destino) + (despues ? 1 : 0)
  return [...sin.slice(0, i), simbolo, ...sin.slice(i)]
}

/** Qué es lo que tenés, por tu lote (el gráfico de lo tuyo es el de tu lote):
 *  tu TSLA de IOL cargado como CEDEAR es el CEDEAR aunque se llame «TSLA». */
export function tipoDelLote(p) {
  if (!p || p.is_cash) return null
  if (isCrypto(p.asset)) return 'cripto'
  if (isBondPosition(p)) return 'bono'
  if (esLoteLocal(p)) return 'arg'
  if (String(p.asset_type || '').toUpperCase() === 'CEDEAR' || isBymaHolding(p)) return 'cedear'
  return tipoDeSimbolo(p.asset, p.asset_type)
}

/** El renglón que estás mirando en el gráfico. `tipoTenido`: lo que tenés de
 *  ese activo (tipoDelLote), si lo tenés. Lo tuyo se abre con TU lote: si
 *  tenés TSLA como CEDEAR, tocar TSLA.BA abre «TSLA» (useFichaDelActivo,
 *  otroNombre) y lo que se ve es el CEDEAR, así que el renglón es el del
 *  CEDEAR, no el de Nueva York. Si no lo tenés: el mismo nombre o el que abre
 *  el mismo gráfico (GGAL y GGAL.BA). */
export function filaDelActivo(filas = [], activo, tipoTenido = null) {
  const a = String(activo || '').toUpperCase()
  const exacta = filas.find(f => f.simbolo === a)
  if (tipoTenido) {
    const ticker = lecturaDeSeguido(a).asset
    const delTipo = filas.find(f => (f.simbolo === a || f.ticker === ticker || mismoGrafico(f.simbolo, a)) && f.tipo === tipoTenido)
    return delTipo || exacta || null
  }
  return exacta || filas.find(f => mismoGrafico(f.simbolo, a)) || null
}

/** ¿Lo tenés? Con lo que manda el servidor de tu cartera (`tenencias` de POST
 *  /api/tecnico/lista: activo, si es de BYMA y su tipo). El CEDEAR y la acción
 *  de EE.UU. son el mismo activo para la lectura técnica (los dos se leen en
 *  dólares): el tipo del lote dice cuál de los dos tenés. */
export function loTenes(fila, tenencias = []) {
  if (!fila) return false
  const { asset, local } = lecturaDeSeguido(fila.simbolo, fila.assetType)
  const k = clave(asset, local)
  return (tenencias || []).some(t => {
    if (clave(String(t.asset || '').toUpperCase(), t.local) !== k) return false
    const cedear = String(t.tipo || '').toUpperCase() === 'CEDEAR'
    if (fila.tipo === 'cedear') return cedear
    if (fila.tipo === 'eeuu' || fila.tipo === 'etf') return !cedear
    return true
  })
}

// ─── Números ────────────────────────────────────────────────────────────────

/** Cuántos decimales lleva un precio: los de siempre (2) salvo los grandes en
 *  pesos o los muy grandes (0) y los de centavos (4). */
export function decimalesDe(precio, pesos = false) {
  const p = Math.abs(precio ?? 0)
  if (p >= 10000 || (pesos && p >= 1000)) return 0
  if (p > 0 && p < 1) return 4
  return 2
}
const menos = (v) => (v < 0 ? '−' : v > 0 ? '+' : '')

/** Lo que dice el renglón: último, variación en plata y en %, y su tono. */
export function numerosDe(f) {
  if (f.precio == null) return { precio: '—', cambio: '—', pct: '—', tono: 0 }
  const d = decimalesDe(f.precio, f.pesos)
  // El signo del tono sale del % redondeado (pctVarSign), como en el inicio.
  const tono = pctVarSign(f.pct)
  return {
    precio: nfmt(f.precio, d),
    // El signo, del número que se ve (−0,001 con dos decimales es «0,00»).
    cambio: f.cambio == null ? '—' : `${menos(Number(f.cambio.toFixed(d)))}${nfmt(Math.abs(f.cambio), d)}`,
    pct: pctVar(f.pct),
    tono,
  }
}

/** La rueda del activo, para la ficha corta. */
export function textoDeLaRueda(f) {
  if (!f) return null
  if (f.mercado === 'cripto') return { abierto: true, texto: 'Se opera todo el día' }
  if (f.enHorario) {
    return { abierto: true, texto: f.cierra ? `Mercado abierto · cierra a las ${f.cierra} (hora argentina)` : 'Mercado abierto' }
  }
  const [y, m, d] = String(f.asOf || '').split('-')
  return { abierto: false, texto: f.asOf ? `Mercado cerrado · precio del cierre del ${d}/${m}` : 'Mercado cerrado' }
}

/** La lectura de Rendi para la ficha corta, con las palabras de la ficha (las
 *  de «Tu lista»: radiografia.tendencia y fuerza). `x`: la lectura del servidor
 *  (POST /api/tecnico/lista). → { largo: {id, texto}, impulso } o null. */
export function lecturaCorta(x) {
  if (!x) return null
  const t = tendencia(x)
  const r = fuerza(x)
  if (t.id === 'sin' && !r) return null
  return {
    largo: { id: t.id, texto: t.id === 'sin' ? 'Largo plazo: sin lectura' : `Largo plazo: ${t.palabra.toLowerCase()}` },
    impulso: r ? { texto: `Impulso (RSI): ${r.palabra.toLowerCase()} · ${Math.round(r.rsi)}` } : null,
  }
}

// La unidad de lo que tenés, por tipo.
const UNIDAD = {
  eeuu: ['acción', 'acciones'], arg: ['acción', 'acciones'], cedear: ['CEDEAR', 'CEDEARs'],
  etf: ['cuotaparte', 'cuotapartes'], bono: ['nominal', 'nominales'],
}

/** «Lo tenés: 8 acciones · +22,4% desde que compraste», con la cuenta de la
 *  ficha (useFichaDelActivo: `agg.qty` y `agg.pnlPct`). Con «Ocultar saldos»,
 *  sin la cantidad. null si no lo tenés. */
export function textoLoTenes({ qty, pnlPct, tipo, ticker, oculto = false }) {
  if (!(qty > 0)) return null
  const n = Math.abs(qty) >= 1000 ? Math.round(qty).toLocaleString('es-AR')
    : qty.toLocaleString('es-AR', { maximumFractionDigits: qty >= 1 ? 2 : 6 })
  const u = tipo === 'cripto' ? ticker : (UNIDAD[tipo] || ['unidad', 'unidades'])[qty === 1 ? 0 : 1]
  const partes = [oculto ? null : `${n} ${u}`, pnlPct != null ? `${pctSigned(pnlPct)} desde que compraste` : null].filter(Boolean)
  return partes.length ? partes.join(' · ') : 'en tu cartera'
}

// ─── «Cómo se ve» y si está abierta: en este navegador ─────────────────────

export const VISTA_DE_ENTRADA = Object.freeze({
  abierta: null, agrupar: 'bandera', orden: 'tuyo', filtro: 'todas', verVar: true, verFicha: true, plegadas: [],
})

/** Lo guardado (o lo de entrada). `abierta` null = nunca se tocó: la pantalla
 *  decide (en la compu abierta; en el celular, cerrada). */
export function vistaGuardada() {
  try {
    const g = JSON.parse(leer(CATALOGO.vistaListaDelGrafico) || 'null')
    if (!g || typeof g !== 'object') return { ...VISTA_DE_ENTRADA }
    return {
      abierta: typeof g.abierta === 'boolean' ? g.abierta : null,
      agrupar: AGRUPAR.some(a => a.id === g.agrupar) ? g.agrupar : VISTA_DE_ENTRADA.agrupar,
      orden: ORDENAR.some(o => o.id === g.orden) ? g.orden : VISTA_DE_ENTRADA.orden,
      filtro: typeof g.filtro === 'string' && g.filtro.length < 20 ? g.filtro : 'todas',
      verVar: g.verVar !== false,
      verFicha: g.verFicha !== false,
      plegadas: Array.isArray(g.plegadas) ? g.plegadas.filter(x => typeof x === 'string').slice(0, 20) : [],
    }
  } catch {
    return { ...VISTA_DE_ENTRADA }
  }
}

export function guardarVista(vista) {
  try { guardar(CATALOGO.vistaListaDelGrafico, JSON.stringify(vista)) } catch { /* sin almacenamiento */ }
}
