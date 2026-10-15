// capitalAportado.js
// ──────────────────
// "¿Cuánta plata pusiste?" — UNA sola cuenta, en dólares y en pesos, para todas
// las pantallas que la muestran (Capital aportado, Ganancia total y su %, la
// atribución del crecimiento, el resultado total de Análisis).
//
// ⚠️ POR QUÉ LOS PESOS NO SON "DÓLARES × EL DÓLAR DE HOY". `monthly_entries`
// guarda los aportes en dólares: un depósito de $10.000.000 del 13/10/2025 queda
// como US$ 7.067 (dolarizado al MEP de ese día). Hasta el 2026-10-15 la pantalla
// en pesos multiplicaba esos US$ 7.067 por el dólar de HOY (1.539) y decía
// "Aportado $10.861.131": la devaluación entre el depósito y hoy se metía adentro
// de "lo que pusiste" y se le restaba a "lo que ganaste". Medido con esa cuenta
// (fixtures/compraYMantieneArs.json): "Ganancia total +$3.357.029" cuando las
// acciones valen hoy $14,2 M y la persona puso $10 M — la ganancia en pesos es
// ~$4,2 M, que es lo que suma la lista "Atribución por activo".
//
// LA REGLA para llevar un aporte a pesos — la misma que `useHistoricalMoney` usa
// para cada movimiento de la lista:
//   1. Si se cargó EN PESOS, son esos pesos. El servidor los guarda tal cual en
//      `manual_deposits_native` / `manual_withdrawals_native` de la fila del
//      broker (en la moneda del broker; en 'global' esas columnas no se llenan).
//   2. Si no hay pesos guardados (aportes en dólares, imports, el saldo con el
//      que arrancó la historia), son esos dólares AL DÓLAR DE SU MES: el blue
//      del cierre del mes (`/benchmarks` → `dolar_blue`; la fila es mensual, no
//      hay día exacto). Es el MISMO riel con el que `simulatePlazoFijoUva` y la
//      comparación contra la inflación llevan cada aporte a pesos: "la misma
//      plata" de esas alternativas arranca de los mismos pesos que acá.
//   3. Si el blue de ese mes no está (la serie no cargó todavía, o el aporte es
//      anterior a la serie), el dólar de hoy — lo de antes, declarado como
//      último recurso. Los pesos guardados (regla 1) no dependen de esto.
//
// El saldo inicial (`capital_inicio` del primer mes) va al blue del mes ANTERIOR
// al primero: es plata que ya estaba cuando empezó la historia.
//
// Lo que NO hace: no toca el número en dólares. `usd` es exactamente lo que
// devolvía `netCapitalContributed` (y lo que va a las fotos del servidor).

import { lookupMonthly } from './benchmarkSim'
import { denominadorAportado, retornoTotal } from './evolution'
import { netCapitalContributed } from './insightsModel'

function claveMes(year, month) {
  return `${year}-${String(month).padStart(2, '0')}`
}

function ordenar(filas) {
  return [...(filas || [])].sort((a, b) => (a.year - b.year) || (a.month - b.month))
}

const n = (v) => (Number.isFinite(+v) ? +v : 0)

// Un nativo sólo se usa si el dólar que implica (pesos ÷ dólares de la misma
// fila) es un dólar plausible para ese mes. Protege de una fila que mezcla
// cargas con pesos guardados y cargas viejas sin ellos (de antes de que existiera
// la columna): ahí el cociente da cualquier cosa y es mejor caer a la regla 2.
const RANGO_PLAUSIBLE = [0.6, 1.6]

function nativoUsable(pesos, usd, fxMes) {
  if (!(pesos > 0) || !(usd > 0)) return false
  if (!(fxMes > 0)) return true
  const r = (pesos / usd) / fxMes
  return r >= RANGO_PLAUSIBLE[0] && r <= RANGO_PLAUSIBLE[1]
}

// La tabla de la que salen las dos preguntas ("¿cuánto aportaste?" y "¿cuánto
// tenías aportado tal día?"): el saldo inicial y, mes a mes, lo aportado en
// dólares y en pesos, con su acumulado.
function tablaDeAportes({ monthly, brokers, blueMap, tcHoy }) {
  const globales = ordenar((monthly || []).filter(m => m.broker === 'global'))
  if (globales.length === 0) return null

  const respaldo = tcHoy > 0 ? tcHoy : 0
  const blueDe = (y, mo) => {
    const v = lookupMonthly(blueMap, claveMes(y, mo))
    return v > 0 ? v : respaldo
  }

  // Brokers en pesos: sus columnas *_native son pesos.
  const enPesos = new Set((brokers || [])
    .filter(b => (b?.currency || '').toUpperCase() === 'ARS')
    .map(b => b.name))
  const filasEnPesos = new Map()
  for (const m of monthly || []) {
    if (m.broker === 'global' || !enPesos.has(m.broker)) continue
    const k = claveMes(m.year, m.month)
    filasEnPesos.set(k, [...(filasEnPesos.get(k) || []), m])
  }

  // Igual que netCapitalContributed: el baseline es costo, nunca valor de mercado.
  const primero = globales[0]
  const baselineUsd = n(primero.capital_inicio_costo ?? primero.capital_inicio)
  const antes = primero.month === 1 ? [primero.year - 1, 12] : [primero.year, primero.month - 1]
  const blueAntes = lookupMonthly(blueMap, claveMes(...antes))
  const baselineArs = baselineUsd * (blueAntes > 0 ? blueAntes : blueDe(primero.year, primero.month))

  let cumUsd = baselineUsd
  let cumArs = baselineArs
  const meses = globales.map(g => {
    const k = claveMes(g.year, g.month)
    const fx = blueDe(g.year, g.month)
    const usd = n(g.deposits) - n(g.withdrawals)
    let sinPesosUsd = usd
    let pesos = 0
    for (const b of filasEnPesos.get(k) || []) {
      const [depUsd, depArs] = [n(b.manual_deposits), n(b.manual_deposits_native)]
      const [retUsd, retArs] = [n(b.manual_withdrawals), n(b.manual_withdrawals_native)]
      if (nativoUsable(depArs, depUsd, fx)) { sinPesosUsd -= depUsd; pesos += depArs }
      if (nativoUsable(retArs, retUsd, fx)) { sinPesosUsd += retUsd; pesos -= retArs }
    }
    const ars = pesos + sinPesosUsd * fx
    cumUsd += usd
    cumArs += ars
    return { k, fx, usd, ars, cumUsd, cumArs }
  })
  return { baselineUsd, baselineArs, meses }
}

/**
 * capitalAportado — lo aportado neto, en las dos monedas.
 *
 * @param {object} args
 * @param {Array}  args.monthly  filas de /api/monthly (las de 'global' Y las de
 *                               cada broker: los pesos guardados viven en las de
 *                               broker)
 * @param {Array}  args.brokers  /api/brokers (para saber cuáles son en pesos)
 * @param {Object} args.blueMap  `/benchmarks` → `dolar_blue` ({'YYYY-MM': blue})
 * @param {number} args.tcHoy    el dólar de hoy: último recurso (regla 3)
 * @returns {{ usd:number, ars:number, arsMaximo:number }}
 *   usd        = capital_inicio del primer mes + Σ(deposits − withdrawals)
 *                (idéntico a `netCapitalContributed`)
 *   ars        = lo mismo en pesos, con la regla de arriba
 *   arsMaximo  = lo máximo que se llegó a tener aportado, en pesos: el
 *                denominador del % cuando hubo retiros (ver denominadorAportado)
 */
export function capitalAportado(args = {}) {
  const t = tablaDeAportes(args)
  if (!t) return { usd: 0, ars: 0, arsMaximo: 0 }
  const ultimo = t.meses[t.meses.length - 1]
  const arsMaximo = t.meses.reduce((mx, m) => Math.max(mx, m.cumArs), t.baselineArs)
  // Los dólares, con LA fórmula de siempre (no una copia): es lo que va a las
  // fotos del servidor y lo que se compara contra ellas.
  const usd = netCapitalContributed((args.monthly || []).filter(m => m.broker === 'global'))
  return { usd, ars: ultimo.cumArs, arsMaximo }
}

/**
 * aportadoEnPesosAl — "¿cuánto tenía aportado, en pesos, tal día?", para la
 * línea punteada del gráfico de evolución en pesos.
 *
 * Cada foto guarda su aportado en dólares (`net_deposited`) y antes se pasaba a
 * pesos con el dólar del DÍA DE LA FOTO: la línea de "capital aportado" subía
 * sola con el dólar aunque nadie depositara nada. Acá ese dato en dólares se
 * lleva a pesos con la tabla de arriba: lo aportado hasta el cierre del mes
 * anterior, en pesos, más lo aportado en lo que va del mes al dólar que tuvieron
 * esos aportes (pesos ÷ dólares del mes). Al cierre de cada mes da exactamente
 * el acumulado en pesos, y hoy da `capitalAportado().ars`.
 *
 * @returns {(ndUsd:number, fechaIso:string) => number} | null sin meses
 */
export function aportadoEnPesosAl(args = {}) {
  const t = tablaDeAportes(args)
  if (!t) return null
  const respaldo = args.tcHoy > 0 ? args.tcHoy : 0
  return (ndUsd, fechaIso) => {
    const k = String(fechaIso || '').slice(0, 7)
    let prevUsd = t.baselineUsd
    let prevArs = t.baselineArs
    let fx = t.meses[0].fx || respaldo
    for (const m of t.meses) {
      if (m.k < k) { prevUsd = m.cumUsd; prevArs = m.cumArs; fx = m.fx || fx; continue }
      if (m.k === k) {
        // El dólar que tuvieron los aportes de ESE mes. Con un neto chico (un
        // depósito y un retiro que casi se cancelan) el cociente no significa
        // nada: ahí, el blue del mes.
        const implicito = Math.abs(m.usd) >= 1 ? m.ars / m.usd : null
        fx = implicito && nativoUsable(implicito, 1, m.fx) ? implicito : (m.fx || fx)
      }
      break
    }
    return prevArs + (n(ndUsd) - prevUsd) * fx
  }
}

/**
 * resultadoTotal — "Capital aportado", "Ganancia total" y su %, en la moneda en
 * que se está mirando. Es la cuenta del hero del Dashboard y del resultado total
 * de Análisis: las dos pantallas la piden acá para no poder diferir.
 *
 *   en dólares: aportado = `capitalAportado().usd` (+ extra)
 *               valor    = el valor de hoy
 *               % sobre  = denominadorAportado(aportado, capitalMaximoUsd)
 *   en pesos:   aportado = `capitalAportado().ars` (+ extra al dólar de hoy)
 *               valor    = el valor de hoy × el dólar de hoy (son pesos de hoy)
 *               % sobre  = denominadorAportado(aportado, lo máximo aportado en
 *                          pesos, piso convertido al dólar de hoy)
 *
 * `extraUsd` es plata aportada que NO pasa por `monthly_entries` y que vive al
 * dólar de hoy (el capital de los plazos fijos: `pfUsd` lo divide por el dólar
 * de hoy, así que × el dólar de hoy son sus pesos exactos).
 *
 * Los montos de la respuesta YA están en `moneda`: se formatean sin convertir
 * (fmtConvertedRaw), no con `fmt`, que volvería a multiplicar por el dólar de hoy.
 *
 * @returns {{ moneda, aportado, valor, ganancia, pct, aportadoUsd }}
 *          pct en fracción (0,42 = +42 %), null si no hay denominador.
 */
export function resultadoTotal({
  monthly, brokers, blueMap, tcHoy, valorHoyUsd = 0, moneda = 'USD',
  extraUsd = 0, capitalMaximoUsd = null,
} = {}) {
  const ap = capitalAportado({ monthly, brokers, blueMap, tcHoy })
  const aportadoUsd = ap.usd + extraUsd
  if (moneda === 'ARS' && tcHoy > 0) {
    const aportado = ap.ars + extraUsd * tcHoy
    const valor = valorHoyUsd * tcHoy
    const ganancia = valor - aportado
    const denom = denominadorAportado(aportado, ap.arsMaximo + extraUsd * tcHoy, tcHoy)
    return { moneda: 'ARS', aportado, valor, ganancia, pct: denom ? ganancia / denom : null, aportadoUsd }
  }
  const { usd: ganancia, pct } = retornoTotal({
    totalValue: valorHoyUsd, netDeposited: aportadoUsd, capitalMaximo: capitalMaximoUsd,
  })
  return { moneda: 'USD', aportado: aportadoUsd, valor: valorHoyUsd, ganancia, pct, aportadoUsd }
}

/**
 * diferenciaDeCambio — en pesos, la parte de la "Ganancia total" que no está ni
 * en lo realizado ni en lo no realizado: lo que cambió en pesos la plata que
 * entró o está en DÓLARES, entre que entró y hoy.
 *
 * En dólares no existe (es la misma plata medida en otra moneda). En pesos
 * aparece desde que lo aportado se cuenta a los pesos que se pusieron: quien
 * depositó US$ 1.000 con el dólar a 1.200 puso $1,2 M; si hoy esos dólares valen
 * US$ 1.100 con el dólar a 1.500, ganó $450.000 en pesos — $150.000 por el papel
 * (el "no realizado", al dólar de hoy, como en Cartera) y $300.000 por el dólar.
 * Sin esta línea el desglose del Dashboard no sumaba la ganancia del título.
 *
 * Identidad (en dólares, la de siempre): ganancia = realizado + no realizado − descuadre.
 * En pesos le falta este término:        ganancia = realizado + no realizado − descuadre × dólar de hoy + esto.
 *
 * @param descuadreUsd  el `accountingGap` del Dashboard (en dólares; >0 = la
 *                      cartera vale menos de lo que explican flujos y P&L)
 * @returns {number} pesos (+ = el dólar sumó, − = restó). 0 fuera de pesos.
 */
export function diferenciaDeCambio({ moneda, ganancia, realizado, noRealizado, descuadreUsd = 0, tcHoy }) {
  if (moneda !== 'ARS' || !(tcHoy > 0)) return 0
  return ganancia - realizado - noRealizado + descuadreUsd * tcHoy
}
