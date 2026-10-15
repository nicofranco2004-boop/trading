// fueraDeHorario.js — el pre y el post mercado de Wall Street sobre la cartera.
// ════════════════════════════════════════════════════════════════════════════
// QUÉ ES
// ──────
// Antes de abrir y después de cerrar, las acciones de EE.UU. siguen operando.
// Rendi muestra cuánto se mueve cada tenencia y cuánta plata iría ganando o
// perdiendo el usuario. Es un ANTICIPO: **no se suma a ningún total**. El total,
// la ganancia, el rendimiento y los gráficos siguen con el precio de la rueda;
// se mueven recién cuando abre el mercado.
//
// UNA SOLA CUENTA PARA TODAS LAS PANTALLAS
// ────────────────────────────────────────
// Cartera (compu y celular), Dashboard y el inicio del celular leen de acá. La
// plata de cada tenencia es su valor —el MISMO de `valuePositionLot`, el que
// suman los totales de esas pantallas— por el % del pre o post. Así la suma de
// las filas cierra con el chip del total, y el chip del total con «si abriera
// así». El servidor (`backend/fuera_de_horario.py`) sólo da el % de cada acción
// de EE.UU. y qué momento es; no calcula plata.
//
// QUÉ ACCIÓN DE EE.UU. MIRA CADA TENENCIA (`referenciaEnEEUU`)
//   · Acción o ETF de EE.UU. en un broker del exterior → ella misma ('propio').
//   · ADR argentino en un broker del exterior (GGAL en Schwab) → él mismo.
//   · CEDEAR → su acción en EE.UU. (DISN → DIS, BRKB → BRK-B) ('eeuu').
//   · Acción argentina con ADR (YPFD → YPF, PAMP → PAM) ('adr').
//   · Acción argentina SIN ADR, bonos, fondos, cripto, efectivo → nada. Buscar
//     el ticker local tal cual en Yahoo daría OTRA empresa (AGRO → Adecoagro).
// Los dos anticipos ('eeuu' y 'adr') NO incluyen lo que se mueva el dólar CCL,
// y se apagan cuando abre BYMA: desde ahí el papel tiene precio propio.

import { valuePositionLot, priceSymbol, costInPesos, BYMA_EXCEPCIONES } from './valuation'
import { classifyAsset, isArMarket } from './assetClass'
import { cedearEspecieBase, CEDEAR_EN_EEUU, ADR_DE_ACCION_AR, CEDEAR_TICKERS } from './tickers'

/** Los índices no operan fuera de la rueda; los ETFs que los copian, sí. La
 *  cinta de arriba muestra el pre/post del índice a través de su ETF. */
export const ETF_DEL_INDICE = { '^GSPC': 'SPY', '^IXIC': 'QQQ', '^DJI': 'DIA' }

/** Cada cuánto se repide (el servidor guarda cada cotización 60 s). */
export const FUERA_DE_HORARIO_MS = 60 * 1000

const sinBA = (s) => (s || '').toUpperCase().replace(/\.BA$/, '')

/**
 * La acción de EE.UU. que anticipa a esta tenencia, o null.
 * @returns {{ s: string, via: 'propio'|'eeuu'|'adr' } | null}
 */
export function referenciaEnEEUU(p, brokers = []) {
  if (!p || p.is_cash) return null
  const clase = classifyAsset(p, brokers)
  const ticker = sinBA(p.asset)
  if (!ticker) return null
  // Un lote comprado EN PESOS se valúa por su .BA aunque viva en una cuenta en
  // dólares (costInPesos, la misma regla que valuationPriceKey y el servidor):
  // es un papel de BYMA. Sin esto la pantalla lo contaba como «exacto» y el
  // chat como anticipo (auditoría 2026-10-15).
  const enAr = isArMarket(p, brokers) || costInPesos(p)
  // El ticker de BYMA, con las mismas excepciones que el precio (BRK.B → BRKB).
  const especie = cedearEspecieBase(BYMA_EXCEPCIONES[ticker] || ticker)
  const esCedear = clase === 'cedear' || (enAr && (clase === 'accion_us' || clase === 'etf')
    && CEDEAR_TICKERS.has(especie))
  if (esCedear) return { s: CEDEAR_EN_EEUU[especie] || especie, via: 'eeuu' }
  if (clase === 'accion_ar') {
    if (!enAr) return { s: ticker, via: 'propio' }   // el ADR en Schwab
    const adr = ADR_DE_ACCION_AR[ticker]
    return adr ? { s: adr, via: 'adr' } : null
  }
  if (clase === 'accion_us' || clase === 'etf') {
    // El MISMO símbolo con que se pide el precio: 'BRK.B' → 'BRK-B'.
    return enAr ? null : { s: priceSymbol(ticker, false, p.asset_type), via: 'propio' }
  }
  return null
}

/** Los símbolos de EE.UU. que hay que pedir para estas tenencias. */
export function simbolosFueraDeHorario(positions = [], brokers = []) {
  const out = new Set()
  for (const p of positions) {
    const r = referenciaEnEEUU(p, brokers)
    if (r) out.add(r.s)
  }
  return [...out].sort()
}

/** ¿Hay pre o post para mostrar? */
export const haySesion = (datos) => Boolean(datos?.sesion)

/**
 * El % (en puntos: 0,64 = 0,64 %) que corresponde a esta tenencia, o null si
 * no aplica. `{ pct: null }` = aplica pero todavía no operó.
 */
export function pctDeLaTenencia(p, brokers, datos) {
  if (!haySesion(datos)) return null
  const ref = referenciaEnEEUU(p, brokers)
  if (!ref) return null
  if (ref.via !== 'propio' && datos.byma_abierto) return null
  const q = datos.cotizaciones?.[ref.s]
  if (!q) return null
  return { pct: q.pct, via: ref.via, s: ref.s }
}

/**
 * Lo que mueve el pre/post en cada tenencia, cada broker y la cartera.
 *
 * `ctx` = lo mismo que se le pasa a computeBrokerValue: { prices, tcValuacion,
 * tcCedear, tcCripto }. Los montos:
 *   · `usd`: en dólares (la vara del total de la cartera).
 *   · `ars`: en pesos — en un broker en pesos, sobre su valor en pesos; en uno
 *     en dólares, el monto en dólares × tcValuacion (igual que el total en
 *     pesos de Cartera, que es el total en dólares × tcValuacion).
 *
 * @returns {{
 *   aplica: boolean,                       // alguna tenencia tiene pre/post
 *   total: { usd, ars, pct },              // pct = fracción del valor (0,0029)
 *   porBroker: { [nombre]: { usd, ars, valorUsd, valorArs, pct, aplica } },
 *   porPosicion: { [id]: { usd, ars, pct, via, s } },  // pct en puntos; null = sin operar
 *   porVia: {                              // para «¿Cómo se calcula?»
 *     exacto:   { usd, ars, valorUsd, valorArs },   // la acción misma (Schwab, IBKR…)
 *     anticipo: { usd, ars, valorUsd, valorArs },   // CEDEAR o acción argentina vía ADR:
 *   },                                                //   en pesos también se mueve con el CCL
 * }}
 */
export function impactoFueraDeHorario(positions = [], brokers = [], ctx = {}, datos = null) {
  const nuevaVia = () => ({ usd: 0, ars: 0, valorUsd: 0, valorArs: 0 })
  const vacio = { aplica: false, total: { usd: 0, ars: 0, pct: 0 }, porBroker: {}, porPosicion: {},
    porVia: { exacto: nuevaVia(), anticipo: nuevaVia() } }
  if (!haySesion(datos)) return vacio
  const { prices = {}, tcValuacion, tcCedear, tcCripto = null } = ctx
  if (!tcValuacion) return vacio
  const porNombre = Object.fromEntries((brokers || []).map(b => [b.name, b]))
  const porBroker = {}
  const porPosicion = {}
  const porVia = { exacto: nuevaVia(), anticipo: nuevaVia() }
  let totalUsd = 0, totalArs = 0, valorTotalUsd = 0, aplica = false

  for (const p of positions || []) {
    const broker = porNombre[p.broker]
    if (!broker) continue
    const v = valuePositionLot(p, { broker, prices, tcValuacion, tcCedear, tcCripto, costBasis: 'today' })
    const enPesos = broker.currency === 'ARS'
    if (!porBroker[p.broker]) porBroker[p.broker] = { usd: 0, ars: 0, valorUsd: 0, valorArs: 0, pct: 0, aplica: false }
    const b = porBroker[p.broker]
    b.valorUsd += v.valueUsd || 0
    b.valorArs += enPesos ? (v.valueArs || 0) : (v.valueUsd || 0) * tcValuacion
    valorTotalUsd += v.valueUsd || 0

    const t = pctDeLaTenencia(p, brokers, datos)
    if (!t) continue
    aplica = true
    b.aplica = true
    const f = t.pct != null ? t.pct / 100 : 0
    const usd = (v.valueUsd || 0) * f
    const ars = enPesos ? (v.valueArs || 0) * f : usd * tcValuacion
    porPosicion[p.id] = { usd, ars, pct: t.pct, via: t.via, s: t.s }
    const pv = porVia[t.via === 'propio' ? 'exacto' : 'anticipo']
    pv.usd += usd
    pv.ars += ars
    pv.valorUsd += v.valueUsd || 0
    pv.valorArs += enPesos ? (v.valueArs || 0) : (v.valueUsd || 0) * tcValuacion
    b.usd += usd
    b.ars += ars
    totalUsd += usd
    totalArs += ars
  }
  for (const b of Object.values(porBroker)) b.pct = b.valorUsd > 0 ? b.usd / b.valorUsd : 0
  return {
    aplica,
    total: { usd: totalUsd, ars: totalArs, pct: valorTotalUsd > 0 ? totalUsd / valorTotalUsd : 0 },
    porBroker,
    porPosicion,
    porVia,
  }
}

/** Suma lo de varias tenencias (una fila con varios lotes). null si ninguna aplica. */
export function sumarTenencias(ids, impacto) {
  let usd = 0, ars = 0, hay = false, pct = null, via = null, sinOperar = true
  for (const id of ids) {
    const r = impacto?.porPosicion?.[id]
    if (!r) continue
    hay = true
    usd += r.usd
    ars += r.ars
    if (r.pct != null) { pct = r.pct; sinOperar = false }
    via = r.via
  }
  return hay ? { usd, ars, pct: sinOperar ? null : pct, via } : null
}

/** «Pre-mercado» · «Post-mercado» · «Post-mercado (cerró)». */
export function nombreDeSesion(sesion) {
  if (sesion === 'pre') return 'Pre-mercado'
  if (sesion === 'post') return 'Post-mercado'
  if (sesion === 'post_cerrado') return 'Post-mercado (cerró)'
  return ''
}

/** «Pre» · «Post» — para el rótulo corto de una fila o una tarjeta. */
export const nombreCorto = (sesion) => (sesion === 'pre' ? 'Pre' : 'Post')

/** El agregado al rótulo de un anticipo: «EE.UU.» (CEDEAR) o «ADR». */
export const rotuloVia = (via) => (via === 'eeuu' ? 'EE.UU.' : via === 'adr' ? 'ADR' : '')

/** «Abierto · cierra 10:30», «Cerró a las 21:00»… para el cartel de estado. */
export function estadoDeSesion(datos) {
  if (!datos?.sesion) return ''
  if (datos.sesion === 'post_cerrado') return 'Cerrado · último dato del post-mercado'
  return datos.cierra ? `Abierto · cierra ${datos.cierra}` : 'Abierto'
}
