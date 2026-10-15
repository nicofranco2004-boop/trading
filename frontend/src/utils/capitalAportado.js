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
//   1. Si entró EN PESOS, son esos pesos. `/api/monthly` los manda en cada fila
//      de broker, con los dólares de la fila que cubren:
//        · lo IMPORTADO (y las dos patas de cada conversión ARS↔USD, con los
//          pesos de la conversión para que sume cero, como en dólares):
//          `pesos_importados_dep`/`_ret` (+ `_usd`). Ver
//          `_aportes_en_pesos_por_mes` en main.py.
//        · lo cargado A MANO en un broker en pesos: `manual_*_native`.
//   2. Si entró EN DÓLARES, son esos dólares AL DÓLAR DE SU DÍA (`tcEnFecha`,
//      el mismo que usa Movimientos para cada fila: utils/tcHistorico.js, el
//      dólar que eligió el usuario). `/api/monthly` manda en cada fila de broker
//      esos aportes con su día (`usd_con_dia`), armados con las mismas funciones
//      que la lista de Movimientos (`_aportes_en_dolares_con_dia` en main.py):
//        · 'importado': lo importado en dólares, con la fecha del import.
//        · 'a_mano': lo cargado a mano, cada carga con su día (y lo que no tiene
//          día, al 15 del mes, como en Movimientos). En un broker en pesos se usa
//          sólo si no se pudieron usar sus pesos guardados.
//      Hasta el 2026-10-15 iban al dólar del CIERRE del mes y la misma plata daba
//      dos números: US$2.000 del 02/03/2026 eran $2.835.200 en Movimientos y
//      $2.852.100 en "Capital aportado" (cuenta `mixta` del fixture).
//   3. Lo que queda sin pesos ni día (el saldo con el que arrancó la historia,
//      lo editado a mano en Global, filas viejas), al dólar del CIERRE DE SU MES
//      en la serie de la app (`/api/fx-rates`, ver `dolarMensualDe`): el MEP, o
//      el blue donde no hay MEP.
//   4. Si el dólar de ese mes no está (la serie no cargó, o el aporte es
//      anterior a la serie), el dólar de hoy — lo de antes, declarado como
//      último recurso. Los pesos guardados (regla 1) no dependen de esto.
//
// El saldo inicial (`capital_inicio` del primer mes) va al dólar del mes
// ANTERIOR al primero: es plata que ya estaba cuando empezó la historia.
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

// Los pesos cargados A MANO se usan salvo que cubran claramente MENOS dólares de
// los que dice la fila: una fila que mezcla cargas con pesos guardados y cargas
// viejas sin ellos (de antes de que existiera la columna) da un cociente
// pesos ÷ dólares muy por debajo del dólar del mes, y ahí son mejores las reglas 2 y 3.
// El control es de UN solo lado a propósito: un cociente ALTO es una carga vieja
// dolarizada con el dólar del día en que se cargó y no el de su fecha (pasó hasta
// que el servidor empezó a resolver el dólar por fecha) — sus pesos están bien y
// sus dólares no. Medido en la copia de prod: depósitos de 2020 y 2023 con
// cociente 4× y 18× el blue de su mes; descartar esos pesos erraba 65–94 %.
// Lo importado no pasa por este control: sus pesos salen de la misma fila del
// import que sus dólares, no se pueden mezclar.
const MINIMO_PLAUSIBLE = 0.6

function pesosAMano(pesos, usd, dolarDeLaSerie) {
  if (!(pesos > 0) || !(usd > 0)) return false
  if (!(dolarDeLaSerie > 0)) return true
  return (pesos / usd) / dolarDeLaSerie >= MINIMO_PLAUSIBLE
}

/**
 * dolarMensualDe — de la serie diaria de `/api/fx-rates` (ascendente, filas
 * {date, blue, mep}), el dólar del CIERRE de cada mes: {'AAAA-MM': dólar}. El
 * último MEP del mes; sin ninguno en el mes (la serie no lo tiene antes de
 * 2018), el último blue. Es lo que usa `fx_for_date` del servidor para guardar flujos.
 */
export function dolarMensualDe(filas) {
  // Por mes, el último MEP y el último blue por separado: el cron nocturno escribe
  // el blue y no siempre el MEP, así que el último día de un mes puede no tener
  // MEP aunque el mes sí lo tenga. Se prefiere el último MEP del mes.
  const mep = {}, blue = {}
  for (const r of filas || []) {
    if (!r?.date) continue
    const k = String(r.date).slice(0, 7)
    if (Number(r.mep) > 0) mep[k] = Number(r.mep)
    if (Number(r.blue) > 0) blue[k] = Number(r.blue)
  }
  return { ...blue, ...mep }
}

/**
 * brokersDelFiltro — los brokers que mira un reporte filtrado por `broker`: el
 * broker y su PAR padre↔"· USD", por `parent_broker_id` (no por el nombre). Es
 * la MISMA regla que el servidor (`broker_pair` en importing/persister.py, que
 * usa `brokers_del_filtro` de Reportes): el padre suma sus "· USD"; un "· USD"
 * suma su padre. Sin esto, Reportes de "IOL" sumaba en el servidor también
 * "IOL · USD" y la pantalla no, y los pesos no cerraban.
 */
export function brokersDelFiltro(brokers, broker) {
  if (broker === 'global') return ['global']
  const lista = brokers || []
  const b = lista.find(x => x.name === broker)
  if (!b) return [broker]
  const nombres = new Set([broker])
  if (b.parent_broker_id) {
    const padre = lista.find(x => x.id === b.parent_broker_id)
    if (padre) nombres.add(padre.name)
  } else {
    for (const x of lista) if (x.parent_broker_id === b.id) nombres.add(x.name)
  }
  return [...nombres].sort()
}

// Las filas de varios brokers, sumadas por mes, con la forma de una fila 'global'.
function sumarPorMes(filas) {
  const porMes = new Map()
  for (const r of filas) {
    const k = claveMes(r.year, r.month)
    const a = porMes.get(k) || { year: r.year, month: r.month, deposits: 0, withdrawals: 0,
      capital_inicio: 0, capital_inicio_costo: 0 }
    a.deposits += n(r.deposits)
    a.withdrawals += n(r.withdrawals)
    a.capital_inicio += n(r.capital_inicio)
    a.capital_inicio_costo += n(r.capital_inicio_costo ?? r.capital_inicio)
    porMes.set(k, a)
  }
  return ordenar([...porMes.values()])
}

// La tabla de la que salen las dos preguntas ("¿cuánto aportaste?" y "¿cuánto
// tenías aportado tal día?"): el saldo inicial y, mes a mes, lo aportado en
// dólares y en pesos, con su acumulado.
//
// `broker`: 'global' (la cartera entera, lo de siempre) o el nombre de un broker
// (Reportes filtrado por broker): las filas de su PAR (`brokersDelFiltro`)
// sumadas mes a mes, y sus pesos guardados. `soloEseBroker`: sin el par (la
// pestaña de un broker del resumen mensual muestra sólo su fila).
function tablaDeAportes({ monthly, brokers, dolarMes, tcEnFecha, tcHoy, broker = 'global', soloEseBroker = false }) {
  const delFiltro = broker === 'global' ? null
    : new Set(soloEseBroker ? [broker] : brokersDelFiltro(brokers, broker))
  const globales = delFiltro
    ? sumarPorMes((monthly || []).filter(m => delFiltro.has(m.broker)))
    : ordenar((monthly || []).filter(m => m.broker === 'global'))
  if (globales.length === 0) return null

  const respaldo = tcHoy > 0 ? tcHoy : 0
  const dolarDeLaSerie = (y, mo) => {
    const v = lookupMonthly(dolarMes, claveMes(y, mo))
    return v > 0 ? v : null
  }
  // El dólar de UN DÍA (regla 2); sin él, el del mes (regla 3).
  const dolarDelDia = (fecha, delMes) => {
    const v = fecha && typeof tcEnFecha === 'function' ? tcEnFecha(fecha) : null
    return v > 0 ? v : delMes
  }

  // Brokers en pesos: sus columnas manual_*_native son pesos.
  const enPesos = new Set((brokers || [])
    .filter(b => (b?.currency || '').toUpperCase() === 'ARS')
    .map(b => b.name))
  const filasDelMes = new Map()
  for (const m of monthly || []) {
    if (m.broker === 'global') continue
    if (delFiltro && !delFiltro.has(m.broker)) continue
    const k = claveMes(m.year, m.month)
    filasDelMes.set(k, [...(filasDelMes.get(k) || []), m])
  }

  // Igual que netCapitalContributed: el baseline es costo, nunca valor de mercado.
  const primero = globales[0]
  const baselineUsd = n(primero.capital_inicio_costo ?? primero.capital_inicio)
  const antes = primero.month === 1 ? [primero.year - 1, 12] : [primero.year, primero.month - 1]
  const baselineFx = dolarDeLaSerie(...antes) ?? dolarDeLaSerie(primero.year, primero.month) ?? respaldo
  const baselineArs = baselineUsd * baselineFx

  let cumUsd = baselineUsd
  let cumArs = baselineArs
  const meses = globales.map(g => {
    const k = claveMes(g.year, g.month)
    const serie = dolarDeLaSerie(g.year, g.month)
    const fx = serie ?? respaldo
    const usd = n(g.deposits) - n(g.withdrawals)
    // Los dos lados por separado (Reportes muestra "Depósitos" y "Retiros").
    let depSinPesosUsd = n(g.deposits)
    let retSinPesosUsd = n(g.withdrawals)
    let depPesos = 0
    let retPesos = 0
    // Los aportes en dólares CON SU DÍA (regla 2): dólares y pesos de cada lado.
    const conDia = { dep: [0, 0], ret: [0, 0] }
    const sumarConDia = (lado, filas) => {
      for (const [fecha, u] of filas || []) {
        conDia[lado][0] += n(u)
        conDia[lado][1] += n(u) * dolarDelDia(fecha, fx)
      }
    }
    for (const b of filasDelMes.get(k) || []) {
      // Lo importado: siempre.
      depSinPesosUsd -= n(b.pesos_importados_dep_usd)
      retSinPesosUsd -= n(b.pesos_importados_ret_usd)
      depPesos += n(b.pesos_importados_dep)
      retPesos += n(b.pesos_importados_ret)
      const dia = b.usd_con_dia || {}
      sumarConDia('dep', dia.importado?.dep)
      sumarConDia('ret', dia.importado?.ret)
      // Lo cargado a mano: en un broker en pesos, sus pesos; si no (o si no
      // sirven), cada carga al dólar de su día.
      let depManualEnPesos = false
      let retManualEnPesos = false
      if (enPesos.has(b.broker)) {
        const [depArs, depUsd] = [n(b.manual_deposits_native), n(b.manual_deposits)]
        const [retArs, retUsd] = [n(b.manual_withdrawals_native), n(b.manual_withdrawals)]
        if (pesosAMano(depArs, depUsd, serie)) { depSinPesosUsd -= depUsd; depPesos += depArs; depManualEnPesos = true }
        if (pesosAMano(retArs, retUsd, serie)) { retSinPesosUsd -= retUsd; retPesos += retArs; retManualEnPesos = true }
      }
      if (!depManualEnPesos) sumarConDia('dep', dia.a_mano?.dep)
      if (!retManualEnPesos) sumarConDia('ret', dia.a_mano?.ret)
    }
    // Lo que tiene día cubre parte de los dólares sin pesos; el resto, al dólar
    // del mes (regla 3). Si los días dicen MÁS dólares de los que quedan (una
    // fila vieja que no cierra), se achican en proporción: la tabla nunca cuenta
    // más dólares que la fila.
    const enPesosDelLado = (sinPesosUsd, [usdDia, arsDia]) => {
      if (!(usdDia > 0) || !(sinPesosUsd > 0)) return sinPesosUsd * fx
      if (usdDia > sinPesosUsd + 0.01) return arsDia * (sinPesosUsd / usdDia)
      return arsDia + (sinPesosUsd - usdDia) * fx
    }
    const depArs = depPesos + enPesosDelLado(depSinPesosUsd, conDia.dep)
    const retArs = retPesos + enPesosDelLado(retSinPesosUsd, conDia.ret)
    const ars = depArs - retArs
    cumUsd += usd
    cumArs += ars
    return { k, fx, usd, ars, depUsd: n(g.deposits), retUsd: n(g.withdrawals), depArs, retArs, cumUsd, cumArs }
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
 * @param {Object} args.dolarMes {'AAAA-MM': dólar del cierre} (`dolarMensualDe`)
 * @param {(iso:string)=>number|null} args.tcEnFecha  el dólar elegido de un día
 *                               (`tcEnFecha` de useDolarMensual, el mismo de
 *                               Movimientos): los aportes en dólares con su día
 * @param {number} args.tcHoy    el dólar de hoy: último recurso (regla 4)
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
 * aportesDelMesEnPesos — los depósitos y retiros de CADA mes, en pesos, con la
 * misma regla (pesos guardados; si no, al dólar de su día o de su mes). Para las tarjetas de
 * Reportes, que muestran "Depósitos" y "Retiros" de un período: así suman lo
 * mismo que el "Capital aportado" del Dashboard.
 *
 * `args.broker` (opcional): 'global' o un broker, como el filtro de Reportes
 * (con su par); `args.soloEseBroker`: sólo esa fila, sin el par.
 *
 * @returns {Map<string, {depUsd, retUsd, depArs, retArs, fx}>} por 'AAAA-MM'
 *          (sólo los meses que tienen fila de ese broker)
 */
export function aportesDelMesEnPesos(args = {}) {
  const t = tablaDeAportes(args)
  const out = new Map()
  for (const m of t?.meses || []) {
    out.set(m.k, { depUsd: m.depUsd, retUsd: m.retUsd, depArs: m.depArs, retArs: m.retArs, fx: m.fx })
  }
  return out
}

/**
 * aportadoAcumuladoAl — lo aportado hasta el cierre del mes de `hastaIso`, en
 * las dos monedas, para `broker` ('global' o uno). Es el "Capital aportado" de
 * Reportes: el mismo acumulado que el Dashboard, cortado en otra fecha.
 *
 * `sinSaldoInicial`: sin el saldo con que arrancó la historia — lo que el
 * servidor llama `cum_deposited` en Reportes (depósitos − retiros, sin baseline).
 *
 * @returns {{usd:number, ars:number} | null} null sin filas
 */
export function aportadoAcumuladoAl({ hastaIso, sinSaldoInicial = false, ...args } = {}) {
  const t = tablaDeAportes(args)
  if (!t) return null
  const k = String(hastaIso || '9999-12').slice(0, 7)
  let out = { usd: t.baselineUsd, ars: t.baselineArs }
  for (const m of t.meses) {
    if (m.k > k) break
    out = { usd: m.cumUsd, ars: m.cumArs }
  }
  if (sinSaldoInicial) out = { usd: out.usd - t.baselineUsd, ars: out.ars - t.baselineArs }
  return out
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
        // nada: ahí, el dólar del mes.
        const implicito = Math.abs(m.usd) >= 1 ? m.ars / m.usd : null
        fx = implicito > 0 ? implicito : (m.fx || fx)
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
  monthly, brokers, dolarMes, tcEnFecha, tcHoy, valorHoyUsd = 0, moneda = 'USD',
  extraUsd = 0, capitalMaximoUsd = null,
} = {}) {
  const ap = capitalAportado({ monthly, brokers, dolarMes, tcEnFecha, tcHoy })
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
 * restoEnPesos — en pesos, la parte de la "Ganancia total" que no explican ni
 * "P&L realizado" ni "P&L no realizado", medida EN PESOS:
 *
 *   resto = ganancia total − realizado − no realizado        (todo en pesos)
 *
 * El desglose del Dashboard ("¿De dónde sale la ganancia?") la muestra como su
 * propia tarjeta para sumar el título. Qué suele haber adentro:
 *   · el dólar: la plata que está o entró en dólares vale más (o menos) pesos
 *     que cuando entró — el no realizado de lo que está en dólares va al dólar
 *     de hoy, lo aportado al de su fecha;
 *   · las ventas: "P&L realizado" cuenta cada venta en dólares de su fecha, y
 *     en pesos de hoy esa misma ganancia es otra;
 *   · dividendos o intereses no cargados, o un costo mal cargado (lo mismo que
 *     la tarjeta en dólares).
 * No se separa el dólar del resto porque para eso hace falta saber a qué dólar
 * entró cada dólar que hay en caja, y ese dato no está.
 *
 * ⚠️ NO es el descuadre en dólares × el dólar de hoy. Ese descuadre puede ser
 * sólo el dólar distinto del día del depósito y del de la compra, que en pesos
 * no existe. Medido en la revisión: un depósito de $10 M con el dólar a 1.000
 * y una compra con el dólar a 1.400 mostraban "+$4,4 M de diferencia de cambio"
 * y "$4,4 M sin explicar" a la vez, en una cuenta que nunca tuvo dólares. En
 * pesos esa cuenta cierra sola: resto = 0.
 *
 * @returns {number} pesos (+ = suma a la ganancia). 0 fuera de pesos.
 */
export function restoEnPesos({ resultado, realizado = 0, noRealizado = 0 }) {
  if (resultado?.moneda !== 'ARS') return 0
  return resultado.ganancia - realizado - noRealizado
}
