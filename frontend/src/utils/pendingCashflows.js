// pendingCashflows.js — detector de cobranzas teóricas pendientes.
// ════════════════════════════════════════════════════════════════════════════
// Phase 3E (Nivel 2 de automatización del MVP de bonos).
//
// Por cada posición de bono, comparamos:
//   • Schedule teórico del bono (bondSchedule.generateSchedule) — fechas y
//     montos esperados según prospecto.
//   • Cobros ya registrados del activo — a mano (Cupón / Amortización) o
//     importados (Dividendo / Interés / Renta) — en cualquier pata de la
//     cuenta (ver cobroRegistrado).
//   • Skips manuales del user (POST /bonds/cashflow/skip) — pagos que el user
//     marcó "no aplica" (ej: bono en default, vendido antes, etc.).
//
// Resultado: lista de pagos teóricos PASADOS que ni están registrados ni
// están skipped — el inbox del user.
//
// Matching teórico ↔ operación registrada:
//   • Mismo asset, en el broker o en otra pata de la misma cuenta.
//   • Fecha dentro de ±DATE_TOLERANCE_DAYS de la fecha del prospecto.
//     (El broker puede acreditar T+1/T+2 o incluso semanas tarde.)
//
// IMPORTANTE: los montos son ESTIMACIONES (cronograma teórico × qty actual).
// El user los confirma o ajusta antes de registrar. La función NO produce
// efectos de side-effect ni acredita nada.

import { isBondTicker } from './tickers'
import { generateSchedule, cerOptsFor, nominalOriginalDe } from './bondSchedule'
import { getBondMeta } from './bondMeta'
import { hoyISO } from './fecha'
import { groupBrokersIntoAccounts, accountForBrokerName } from './brokerAccounts'

// Tolerancia para matchear una operation con una fecha del prospecto.
// 14 días cubre T+1/T+2 estándar + delays operativos + diferencias de huso
// en data de operaciones cargadas manualmente.
const DATE_TOLERANCE_DAYS = 14

// Cuán atrás miramos. Si un pago del cronograma fue hace más de 2 años y el
// user nunca lo registró ni saltó, asumimos que ya no aplica — probablemente
// el user empezó a usar Rendi después de esa fecha. Evita inundar el inbox
// con históricos al cargar un AL30 que paga semestral desde 2024.
const MAX_BACKLOG_DAYS = 730

// Un lote cobra los pagos desde el día de su compra, ni uno antes: el pago
// anterior lo cobró quien vendió. Hasta 2026-10-10 había 7 días "de gracia" y la
// bandeja ofrecía —con el botón de un click— el pago del 09/07 a un lote
// comprado el 13/07: entraban US$ 827 que nunca existieron, y el servidor (que
// aplica esta misma regla: `_reparto_de_amortizacion(hasta=…)`) no le bajaba
// nominales a nadie.

function todayIso() {
  return hoyISO()
}

function diffDaysAbs(a, b) {
  const pa = a.slice(0, 10).split('-').map(Number)
  const pb = b.slice(0, 10).split('-').map(Number)
  const ta = Date.UTC(pa[0], pa[1] - 1, pa[2])
  const tb = Date.UTC(pb[0], pb[1] - 1, pb[2])
  return Math.abs(Math.round((tb - ta) / 86400000))
}

// Resta N días a una fecha ISO. Útil para aplicar el margen de gracia sobre
// entry_date. Trabaja en UTC para evitar timezone drift.
function subDays(iso, days) {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  const date = new Date(Date.UTC(y, m - 1, d))
  date.setUTCDate(date.getUTCDate() - days)
  return date.toISOString().slice(0, 10)
}

// ── ¿Este pago del cronograma ya entró? ─────────────────────────────────────
// Una sola respuesta para la bandeja de pendientes Y para el ✓ del cronograma
// en la ficha del bono (BondDetail). Si cada uno se hace la pregunta a su
// manera, uno dice "pendiente" y el otro "cobrado" del mismo pago.
//
// EL BUG (2026-10-09). La bandeja sólo reconocía 'Cupón' y 'Amortización', que
// son los nombres que escribe el registro A MANO (POST /bonds/cashflow). Pero un
// cupón que entra IMPORTADO (normalizer: DIVIDEN/COUPON/RENTA/AMORTIZA) se guarda
// como 'Dividendo' o 'Interés' (persister._persist_dividend_or_interest) — y en
// la copia de prod del 2026-08-16 ése era el caso de 40 usuarios / 52 bonos. La
// bandeja ofrecía ese cupón como pendiente, y confirmarlo lo anotaba dos veces:
// el cash del broker y el P&L realizado subían otra vez por la misma plata.
//
// Y el broker: el cupón en dólares de un bono comprado en pesos el importador
// lo acredita en la pata "Cocos · USD", mientras el bono vive en "Cocos". Las
// dos patas son UNA cuenta (brokerAccounts.js, por parent_broker_id); comparar
// el nombre exacto también dejaba el cobro afuera.
const TIPOS_DE_COBRO = new Set(['CUPON', 'AMORTIZACION', 'DIVIDENDO', 'INTERES', 'RENTA'])

// Sin acentos ni mayúsculas: hay filas viejas 'Cupon'/'Interes' sin tilde.
// Comparación EXACTA, no "contiene": 'Interés PF' (plazo fijo) no es renta de
// un bono, y no tiene que colarse por contener "INTERES".
export function esCobroDeRenta(op) {
  const tipo = String(op?.op_type || '').trim().toUpperCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
  return TIPOS_DE_COBRO.has(tipo)
}

// ¿Es un PAGO del bono ya anotado? Los cobros de renta, más la "venta" con la que
// el lector de Balanz anota una amortización ("Renta y Amortización" con
// cantidad): se llama 'Venta', pero es el pago del cronograma, y sin contarla la
// bandeja lo ofrecía como pendiente (auditoría 2026-10-10: 403 operaciones de 46
// usuarios en la copia de producción). Lo dice /api/operations
// (`amortizacion_importada`); ESPEJO de cobros_bonos.ventas_que_son_amortizacion.
// Sólo para "¿ya está anotado?": las sumas de lo cobrado usan `esCobroDeRenta`
// (esa venta ya cuenta su ganancia como venta, y su `quantity` son nominales).
export function esPagoDelBono(op) {
  return esCobroDeRenta(op) || op?.amortizacion_importada === true
}

// ¿Lo escribió la carga A MANO (POST /bonds/cashflow)? Son los únicos que suma
// el resumen de cobranzas de la fila (Positions.jsx → bondCashflowsByKey): su
// `pnl_usd` está en la moneda del broker, el de los importados ya en dólares.
// El nombre solo no alcanza: el importador también escribe 'Amortización' (la
// devolución de capital sin cantidad); `importada` lo dice /api/operations.
export function esCobroAMano(op) {
  return (op?.op_type === 'Cupón' || op?.op_type === 'Amortización') && !op?.importada
}

// El TC con que un cobro cargado a mano pasa a dólares. UNA sola regla para el
// resumen del bono (Positions.jsx) y lo cobrado "aparte" (cobradoDelBonoUsd):
// antes cada uno tenía la suya y un cupón viejo en pesos sin moneda se leía como
// dólares en un lado y como pesos en el otro.
//   · con `fx_to_usd` sellado, ése;
//   · si no (filas viejas): pesos si la fila dice ARS o si no dice moneda y el
//     monto es grande (> 1.000: un cupón de bono en dólares nunca es tan alto
//     por fila); el dólar de referencia del que llama.
export function fxDeCobroAMano(op, tcRef) {
  const fx = Number(op?.fx_to_usd)
  if (fx > 0) return fx
  const monto = Number(op?.quantity ?? op?.pnl_usd) || 0
  const ccy = (op?.currency || '').toUpperCase()
  if (ccy === 'ARS' || (!ccy && monto > 1000)) return tcRef > 0 ? tcRef : 1
  return 1
}

// Los nombres de broker que son la MISMA cuenta que `brokerNames` (sus patas
// pesos/dólar). Sin la lista de brokers, sólo los nombres dados.
export function patasDeLaCuenta(brokerNames, brokers) {
  const out = new Set(brokerNames.filter(Boolean))
  if (!Array.isArray(brokers) || brokers.length === 0) return out
  const cuentas = groupBrokersIntoAccounts(brokers)
  for (const name of [...out]) {
    const cuenta = accountForBrokerName(cuentas, name)
    if (cuenta) for (const n of cuenta.patasNames) out.add(n)
  }
  return out
}

const mismoActivo = (a, b) =>
  String(a || '').trim().toUpperCase() === String(b || '').trim().toUpperCase()

/**
 * Todos los cobros de renta (a mano o importados) del activo de la posición
 * `p`, en cualquier pata de su cuenta.
 *
 * @param ops      operations tal cual /api/operations (se filtran acá: no hace
 *                 falta, ni conviene, filtrarlas antes)
 * @param p        la posición; si es una fila que junta las dos patas, trae
 *                 `_brokers` (ver bondSummaryMerge.js)
 * @param brokers  filas de /api/brokers, para reconocer las patas de la cuenta
 */
export function cobrosDelActivo(ops, p, brokers) {
  const nombres = (p?._brokers && p._brokers.length) ? p._brokers : [p?.broker]
  const patas = patasDeLaCuenta(nombres, brokers)
  return (ops || []).filter(o =>
    esCobroDeRenta(o) && patas.has(o.broker) && mismoActivo(o.asset, p?.asset)
  )
}

/**
 * El cobro registrado que corresponde al pago del cronograma `fecha` de la
 * posición `p` (±DATE_TOLERANCE_DAYS), o undefined si no hay.
 */
export function cobroRegistrado(ops, p, fecha, brokers) {
  const nombres = (p?._brokers && p._brokers.length) ? p._brokers : [p?.broker]
  const patas = patasDeLaCuenta(nombres, brokers)
  return (ops || []).find(o =>
    esPagoDelBono(o) && patas.has(o.broker) && mismoActivo(o.asset, p?.asset) &&
    o.date && diffDaysAbs(o.date, fecha) <= DATE_TOLERANCE_DAYS
  )
}

// ── La cuenta donde entra el cobro ──────────────────────────────────────────
// Un bono en dólares comprado en la cuenta en pesos («Cocos») paga en la cuenta
// en dólares («Cocos · USD»), si existe: la misma regla que el importador
// (`cash_broker_for`). Un bono en pesos paga en la cuenta en pesos.
export function cuentaDelCobro(p, bondCurrency, brokers) {
  const cuenta = accountForBrokerName(groupBrokersIntoAccounts(brokers || []), p?.broker)
  if (!cuenta) return p?.broker
  const quiere = bondCurrency === 'ARS'
    ? (b) => (b.currency || '').toUpperCase() === 'ARS'
    : (b) => ['USD', 'USDT'].includes((b.currency || '').toUpperCase())
  const propia = cuenta.patas.find(b => b.name === p.broker)
  if (propia && quiere(propia)) return p.broker
  return (cuenta.patas.find(quiere) || propia || { name: p.broker }).name
}

// Lo que costó cada nominal VIVO de la posición, en la moneda de la caja donde
// entra el cobro. Estimado: el número exacto lo calcula el servidor al
// confirmar (`_costo_amortizado_en_caja`, con el TC de compra de cada lote).
function costoPorNominal(p, monedaCaja, tcRef, brokers) {
  if (!p.quantity || !(p.invested > 0)) return null
  const unit = p.invested / p.quantity
  // La moneda del lote; si no la dice, la de su cuenta (un lote sin moneda de
  // una cuenta en pesos se leía como dólares: $ 480.000 de costo como US$).
  const ccy = p.currency || (brokers || []).find(b => b.name === p.broker)?.currency || ''
  const enPesos = ccy.toUpperCase() === 'ARS'
  const cajaUsd = monedaCaja !== 'ARS'
  if (enPesos === !cajaUsd) return unit
  if (enPesos && cajaUsd) {
    const tc = p.tc_compra || tcRef
    return tc > 0 ? unit / tc : null
  }
  return tcRef > 0 ? unit * tcRef : null
}

// Los lotes del MISMO bono en la MISMA cuenta (sus patas pesos/dólar) son UN
// pago: /api/positions devuelve una fila por lote, y armar una tarjeta por lote
// mostraba el mismo pago dos veces —con la misma llave— y, al confirmar una, la
// otra desaparecía con su parte sin anotar.
function bonosPorCuenta(positions, brokers) {
  const cuentas = groupBrokersIntoAccounts(brokers || [])
  const grupos = new Map()
  for (const p of positions || []) {
    if (p.is_cash || !isBondTicker(p.asset) || !(p.quantity > 0)) continue
    const cuenta = accountForBrokerName(cuentas, p.broker)
    const fam = cuenta ? `c${cuenta.key}` : `b${p.broker}`
    const k = `${fam}:${String(p.asset).toUpperCase()}`
    if (!grupos.has(k)) grupos.set(k, { fam, lotes: [] })
    grupos.get(k).lotes.push(p)
  }
  return [...grupos.values()]
}

// Detecta cobranzas pendientes (pagos teóricos pasados sin operation ni skip).
//
// Inputs:
//   positions: array de positions (bonds entre ellas; una fila por lote)
//   ops: operations SIN filtrar (las de /api/operations); el detector se
//        queda con los cobros de renta (esCobroDeRenta)
//   skips: array de skips ({ broker, asset, date, ... })
//   options:
//     brokers — filas de /api/brokers. Sin ellas un cobro acreditado en la
//               otra pata de la cuenta ("Cocos · USD") no se reconoce.
//     today (ISO opcional) — para tests con fecha fija.
//     maxBacklogDays — override del default de 730.
//     cerSeries — serie CER (bonos ajustados por inflación). `null` = todavía
//               cargando; `{}` = no se pudo traer.
//     cerStale  — la serie está desactualizada (se usa el último valor conocido).
//     tcRef — dólar de referencia para estimar el costo cuando cambia de moneda.
//
// Output: UN item por (cuenta, bono, fecha): { key, broker, asset, position,
//   date, coupon, amort, total, kind, daysAgo, currency, cuenta, nominales,
//   vivoAntes, vivoDespues, couponRate, amortPct, cuota, cuotas,
//   costoAmortizado, cerFactor, sinAjusteCer, cargandoCer, cerViejo, estimado,
//   tenencia, nominalesQueBajan }
//   ordenado por fecha descendente (más reciente primero).
export function detectPendingCashflows(positions, ops, skips = [], options = {}) {
  const today = options.today || todayIso()
  const maxBacklog = options.maxBacklogDays ?? MAX_BACKLOG_DAYS
  const earliestDate = (() => {
    const t = new Date(today)
    t.setDate(t.getDate() - maxBacklog)
    return t.toISOString().slice(0, 10)
  })()

  const pending = []
  for (const { fam, lotes } of bonosPorCuenta(positions, options.brokers)) {
    // La tarjeta se anota en la pata con más nominales (el servidor alcanza los
    // lotes de todas las patas del broker; la pata sólo decide a nombre de quién
    // queda el "No lo cobré" y la cuenta por defecto del cobro).
    const porPata = new Map()
    for (const l of lotes) porPata.set(l.broker, (porPata.get(l.broker) || 0) + (l.quantity || 0))
    const pata = [...porPata.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0][0]
    const p = lotes.filter(l => l.broker === pata)
      .reduce((a, b) => ((b.quantity || 0) > (a.quantity || 0) ? b : a))
    // El schedule necesita meta + maturity. ETFs y otros caen en null.
    // El ajuste CER va acá también: este cronograma es el que decide QUÉ pago
    // está pendiente y con qué monto se pre-llena lo que se registra.
    const schedule = generateSchedule(p.asset, cerOptsFor(p, options.cerSeries))
    if (!schedule) continue
    const meta = getBondMeta(p.asset)
    const bondCurrency = meta?.currency || 'USD'
    const esCer = meta?.type === 'cer'
    const amortDates = schedule.filter(x => (x.amortPct || 0) > 0).map(x => x.date)

    // Desde cuándo le corresponde cada lote: si tiene entry_date, no sugerimos
    // pagos anteriores a esa fecha (con margen de gracia) — esos los cobró el
    // vendedor previo. Sin entry_date, el backlog global.
    const desdeLote = (l) => {
      let d = earliestDate
      if (l.entry_date && l.entry_date.slice(0, 10) > d) d = l.entry_date.slice(0, 10)
      return d
    }
    // Un "No lo cobré" vale para toda la cuenta: se anotó a nombre de una pata,
    // y si esa pata se queda sin lotes la tarjeta no tiene que volver.
    const patas = patasDeLaCuenta(lotes.map(l => l.broker), options.brokers)

    const pendientes = []
    for (const pmt of schedule) {
      if (pmt.date > today) break  // futuro, no nos interesa para el inbox
      if (!lotes.some(l => pmt.date >= desdeLote(l))) continue  // antes de toda compra
      // Pagos teóricos = 0 (caso edge en el schedule) tampoco son útiles.
      if ((pmt.total || 0) <= 0) continue
      // ¿Ya tiene operation registrada? (cualquier pata de la cuenta)
      if (cobroRegistrado(ops, p, pmt.date, options.brokers)) continue
      // ¿Saltado por el user? (desde cualquier lote del grupo)
      if ((skips || []).some(s => patas.has(s.broker) && mismoActivo(s.asset, p.asset) && s.date === pmt.date)) continue
      pendientes.push(pmt)
    }
    if (!pendientes.length) continue

    // Los nominales ORIGINALES de cada lote, con el dato del servidor
    // (`nominalOriginalDe`): el cronograma está escrito por cada 100 originales y
    // la cantidad guardada es lo que queda vivo. Deducirlo de la cantidad fallaba
    // (6.400 vivos de AL30 = 10.000 originales proponían US$ 508 en vez de 827;
    // un lote barrido en junio, o uno al que nunca se le bajó nada, daban otro
    // número). No depende de qué pagos se confirmaron ni en qué orden.
    const originales = lotes.map(l => ({ l, desde: desdeLote(l), original: nominalOriginalDe(l, schedule) }))
    const cuenta = cuentaDelCobro(p, bondCurrency, options.brokers)
    // ¿La cuenta donde entra está en la moneda del bono? Un bono en dólares en
    // un broker SIN cuenta en dólares cobra en pesos: el monto del cronograma (en
    // dólares) no se puede acreditar tal cual — anotaba US$ 827 como $ 827 y una
    // pérdida de costo entero. Ahí no hay confirmación de un click: se cargan los
    // pesos que acreditó el broker.
    const ccyCuenta = ((options.brokers || []).find(b => b.name === cuenta)?.currency || '').toUpperCase()
    const cuentaMoneda = ccyCuenta === 'ARS' ? 'ARS' : (ccyCuenta ? 'USD' : bondCurrency)
    const otraMoneda = cuentaMoneda !== (bondCurrency === 'ARS' ? 'ARS' : 'USD')

    for (const pmt of pendientes) {
      // Sólo los lotes que ya estaban comprados para ESTE pago.
      const deEste = originales.filter(o => pmt.date >= o.desde)
      const original = deEste.reduce((s, o) => s + o.original, 0)
      const factor = original / 100
      const amort = +(pmt.amort * factor).toFixed(2)
      // El costo de lo que vuelve: los nominales amortizados (a la par) por lo que
      // costó cada nominal vivo, lote por lote. Estimado; el servidor lo recalcula.
      let costoAmortizado = null
      if (amort > 0) {
        const partes = deEste.map(o => {
          const c = costoPorNominal(o.l, bondCurrency, options.tcRef, options.brokers)
          return c == null ? null : o.original * (pmt.amortPct / 100) * c
        })
        if (partes.every(x => x != null)) costoAmortizado = +partes.reduce((s, x) => s + x, 0).toFixed(2)
      }
      pending.push({
        key: `${fam}:${p.asset}:${pmt.date}`,
        position: p,
        lotes: deEste.map(o => o.l),
        broker: p.broker,
        asset: p.asset,
        date: pmt.date,
        coupon: +(pmt.coupon * factor).toFixed(2),
        amort,
        total: +(pmt.total * factor).toFixed(2),
        kind: pmt.amort > 0 && pmt.coupon > 0
          ? 'mixto'
          : pmt.amort > 0
            ? 'amortizacion'
            : 'cupon',
        currency: bondCurrency,
        daysAgo: diffDaysAbs(today, pmt.date),
        cuenta,
        cuentaMoneda,
        otraMoneda,
        nominales: Math.round(original),
        nominalesExactos: original,
        vivoAntes: pmt.faceBefore,
        vivoDespues: pmt.faceAfter,
        couponRate: pmt.rate,
        amortPct: pmt.amortPct,
        cuota: amort > 0 ? amortDates.indexOf(pmt.date) + 1 : 0,
        cuotas: amortDates.length,
        costoAmortizado,
        cerFactor: pmt.cerFactor ?? null,
        // Bono ajustado por inflación SIN la serie CER (no cargó, o falló): el
        // monto es el nominal, muchas veces más chico que el real. No se ofrece
        // confirmar con un click: hay que cargar el monto del broker.
        sinAjusteCer: esCer && !(pmt.cerFactor > 0),
        // La serie todavía viaja (`null`): no es "no la pudimos traer". La
        // bandeja espera en vez de mostrar un monto 34 veces menor y el aviso
        // de falla durante un instante.
        cargandoCer: esCer && options.cerSeries == null,
        // Serie desactualizada: se ajustó con el último valor conocido, que da
        // un poco menos que lo cobrado. Tampoco hay confirmación de un click.
        cerViejo: esCer && pmt.cerFactor > 0 && !!options.cerStale,
        // Obligaciones negociables: no tenemos el cronograma del prospecto; las
        // fechas y montos salen de la tasa y el vencimiento (bondSchedule.js).
        // Es una estimación: se cargan los montos del broker.
        estimado: meta?.type === 'corporate',
        // Lo que hay hoy en cartera y lo que este cobro le va a bajar: los lotes
        // que no lleva el barrido de amortizaciones bajan su parte al confirmar.
        tenencia: lotes.reduce((s, l) => s + (Number(l.quantity) || 0), 0),
        nominalesQueBajan: amort > 0
          ? deEste.filter(o => !o.l.nominal_por_barrido)
            .reduce((s, o) => s + o.original * (pmt.amortPct / 100), 0)
          : 0,
      })
    }
  }
  // Más reciente primero — el user suele cargar los nuevos antes que los viejos.
  pending.sort((a, b) => b.date.localeCompare(a.date))
  return pending
}

// ── Lo que la bandeja le manda al servidor para confirmar un pago ───────────
// POST /api/bonds/cashflow/pago. Función pura (y no adentro del hook) para que
// el contrato con el servidor se pueda probar: backend/tests/fixtures/
// cupones_contrato.json guarda estos cuerpos, y test_cupones_contrato.py los
// postea tal cual. Hasta 2026-10-10 ninguna prueba del servidor mandaba lo que
// manda la pantalla (se podía dejar de mandar `face_amortized`, o mandar otra
// cuenta, y todo seguía verde).
//
//   montos: { cupon, amort, comision, cuenta?, editado? } en la moneda de la
//   cuenta donde entran (`montos.cuenta` si el usuario eligió otra, la de pesos;
//   si no, `item.cuenta`). El nominal amortizado (a la par, en nominales del
//   bono) viaja aparte para que el servidor no lo confunda con los pesos.
export function cuerpoDelPago(item, montos) {
  const cuerpo = {
    broker: item.broker,
    asset: item.asset,
    date: item.date,
    coupon_amount: montos.cupon,
    amort_amount: montos.amort,
    commissions: montos.comision || 0,
    cash_broker: montos.cuenta || item.cuenta,
    notes: montos.editado ? 'Confirmado desde la bandeja (montos editados)' : 'Confirmado desde la bandeja',
  }
  if (montos.amort > 0) {
    // Con los nominales SIN redondear: redondeados, 111,12 contra una amortización de 111,11.
    cuerpo.face_amortized = +((item.nominalesExactos ?? item.nominales) * (item.amortPct || 0) / 100).toFixed(6) || undefined
  }
  return cuerpo
}

// Los pagos del cronograma que ya entraron con una IMPORTACIÓN (el archivo del
// broker los llama renta, dividendo o interés) dentro de la MISMA ventana que
// mira la bandeja (desde la compra, hasta 2 años atrás). Se muestran aparte —"ya
// entraron con tu importación"— para que nadie los vuelva a cargar a mano.
export function detectCobrosImportados(positions, ops, options = {}) {
  const today = options.today || todayIso()
  const backlog = subDays(today, options.maxBacklogDays ?? MAX_BACKLOG_DAYS)
  const out = []
  const vistos = new Set()
  for (const p of positions || []) {
    if (p.is_cash || !isBondTicker(p.asset) || !(p.quantity > 0)) continue
    const schedule = generateSchedule(p.asset, cerOptsFor(p, options.cerSeries))
    if (!schedule) continue
    let desde = backlog
    if (p.entry_date && p.entry_date.slice(0, 10) > desde) desde = p.entry_date.slice(0, 10)
    for (const pmt of schedule) {
      if (pmt.date > today) break
      if (pmt.date < desde) continue
      const op = cobroRegistrado(ops, p, pmt.date, options.brokers)
      if (!op || esCobroAMano(op)) continue
      const k = `${op.id ?? ''}:${p.asset}:${pmt.date}`
      if (vistos.has(k)) continue
      vistos.add(k)
      // En la venta-amortización de Balanz `quantity` son nominales, no plata.
      const esVenta = op.amortizacion_importada === true
      out.push({ key: k, asset: p.asset, date: pmt.date, broker: op.broker,
                 opDate: op.date, comoLoLlama: esVenta ? 'Venta (amortización)' : op.op_type,
                 monto: esVenta ? null : (Number(op.quantity) || null) })
    }
  }
  out.sort((a, b) => b.date.localeCompare(a.date))
  return out
}

// ── Lo cobrado de un bono, en dólares: la ganancia REALIZADA ────────────────
// Se muestra APARTE de la ganancia de la fila (que es sólo por precio, no
// realizada): misma regla que los dividendos (decisión de Nico, 2026-10-09).
//   · cargado a mano: `pnl_usd` es la ganancia en la moneda de la caja (desde
//     2026-10-09 la amortización guarda sólo lo cobrado por encima del costo);
//     las amortizaciones viejas guardaban el cobro entero: se les resta el costo.
//   · importado: 'Dividendo'/'Interés'/'Renta' traen la ganancia ya en dólares;
//     la 'Amortización' importada es capital que vuelve (0).
export function cobradoDelBonoUsd(ops, p, brokers, tcRef) {
  let total = 0
  for (const o of cobrosDelActivo(ops, p, brokers)) {
    const pnl = Number(o.pnl_usd) || 0
    let gan
    if (esCobroAMano(o)) {
      const vieja = o.op_type === 'Amortización' && o.quantity == null
      gan = vieja ? (o.cost_basis_consumed != null ? pnl - Number(o.cost_basis_consumed) : 0) : pnl
      gan = gan / fxDeCobroAMano(o, tcRef)
    } else {
      gan = o.op_type === 'Amortización' ? 0 : pnl
    }
    total += gan
  }
  return total
}

// Convenience: agrupa los pendientes por bono (broker + asset) para mostrar
// summary tipo "AL30 (Cocos): 3 pagos pendientes". Útil si el inbox crece mucho.
export function groupPendingByBond(pending) {
  const map = new Map()
  for (const item of pending) {
    const k = `${item.broker}:${item.asset}`
    if (!map.has(k)) map.set(k, { broker: item.broker, asset: item.asset, items: [], totalCash: 0 })
    const entry = map.get(k)
    entry.items.push(item)
    entry.totalCash += item.total
  }
  return [...map.values()]
}
