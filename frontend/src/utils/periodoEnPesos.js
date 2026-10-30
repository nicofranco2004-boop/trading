// periodoEnPesos.js
// ─────────────────
// Los montos de UN PERÍODO de Reportes (un día, una semana, un mes, un año), en
// la moneda en que se mira.
//
// El servidor manda todo en dólares. Hasta el 2026-10-15 la pantalla los pasaba
// a pesos con el dólar de HOY: los depósitos de octubre de 2025, el valor con
// que cerró ese mes y lo que ganó, todos re-expresados al dólar de un año
// después. Un depósito de $10.000.000 se leía $10,85 M.
//
// LA REGLA — la misma que Movimientos (cada fila al dólar de su fecha) y que
// "Capital aportado" (utils/capitalAportado.js), con el dólar que eligió el
// usuario (MEP; ver utils/tcHistorico.js):
//   • Lo que tenías al EMPEZAR el período, al dólar del día anterior al inicio
//     (es el cierre del período anterior).
//   • Lo que tenías al CERRAR, al dólar del cierre (hoy, si el período sigue).
//   • Depósitos y retiros de un mes o un año: los pesos que se pusieron o
//     sacaron (`aportesDelMesEnPesos`, la regla del Dashboard). De una semana o
//     un día —`monthly_entries` no baja a esa escala—, al dólar del cierre.
//   • Lo que se ganó o perdió en el período (resultado, no realizado), al dólar
//     del cierre: es plata de ese momento.
//   • El REALIZADO en pesos es el de las ventas en pesos (cobrado − costo, los
//     pesos de verdad: la cuenta única de backend/resultado_dual.py, la misma de
//     Movimientos); sólo lo que no tiene pesos (dividendos en dólares, lo cargado
//     a mano) va al dólar del cierre, y se avisa (`realizadoNota`).
//   • El RESULTADO del período contiene a ese realizado: es el resultado en dólares al
//     dólar del cierre, con el pedazo realizado cambiado por el realizado en pesos. Así
//     resultado = realizado + no realizado + otros, también en pesos.
//
// En dólares devuelve los mismos números del servidor, sin tocar.

import { aportesDelMesEnPesos, aportadoAcumuladoAl } from './capitalAportado'
import { realizadoEnPesos, notaDelRealizado } from './realizadoEnPesos'

function diaAnterior(iso) {
  const d = new Date(`${String(iso).slice(0, 10)}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return null
  d.setUTCDate(d.getUTCDate() - 1)
  return d.toISOString().slice(0, 10)
}

const num = (v) => (v == null || !Number.isFinite(+v) ? null : +v)
// "¿La tabla de aportes explica los mismos dólares que muestra el reporte?"
const cerca = (a, b) => Math.abs((a || 0) - (b || 0)) <= Math.max(1, 0.01 * Math.abs(b || 0))

/**
 * crearPesosDelPeriodo — arma `enVista(período)` para una moneda y un broker.
 *
 * @param {object} args
 * @param {'USD'|'ARS'} args.moneda
 * @param {number}   args.tcHoy       el dólar de hoy (el elegido)
 * @param {(iso:string)=>number|null} args.tcEnFecha  el dólar elegido de una
 *                                    fecha (`getRateForDate` de useFxHistory)
 * @param {Object}   args.dolarMes    `dolarMes` de useDolarMensual
 * @param {Array}    [args.monthly]   /api/monthly (sin esto, los flujos van al
 *                                    dólar del cierre)
 * @param {Array}    [args.brokers]   /api/brokers
 * @param {string}   [args.broker]    'global' o el broker del filtro
 */
export function crearPesosDelPeriodo({
  moneda, tcHoy, tcEnFecha, dolarMes, monthly, brokers, broker = 'global',
} = {}) {
  const enPesos = moneda === 'ARS' && tcHoy > 0
  const meses = enPesos && Array.isArray(monthly) && monthly.length
    ? aportesDelMesEnPesos({ monthly, brokers, dolarMes, tcEnFecha, tcHoy, broker })
    : new Map()
  const tc = (iso) => {
    const v = iso && typeof tcEnFecha === 'function' ? tcEnFecha(iso) : null
    return v > 0 ? v : tcHoy
  }

  /**
   * @returns {{ moneda, fxInicio, fxCierre, fxDepositos, inicio, cierre,
   *             depositos, retiros, resultado, realizado, noRealizado }}
   *   montos YA en `moneda` (formatear sin convertir: fmtConvertedRaw). Los
   *   `fx*` sirven para pasar otros montos del mismo período con la misma regla
   *   (`fxDepositos`: el de sus depósitos).
   */
  function enVista(p) {
    const m = p?.metrics || {}
    const dep = num(m.deposits) || 0
    const ret = num(m.withdrawals) || 0
    if (!enPesos) {
      return {
        moneda: 'USD', fxInicio: 1, fxCierre: 1, fxDepositos: 1,
        inicio: num(m.start_value), cierre: num(m.end_value),
        depositos: dep, retiros: ret,
        resultado: num(m.delta_usd), realizado: num(m.realized_pnl), noRealizado: num(m.unrealized_pnl),
        realizadoNota: null, realizadoRestoUsd: 0, realizadoValuado: false,
      }
    }
    const fxCierre = (p?.is_current || !p?.period_end) ? tcHoy : tc(p.period_end)
    const fxInicio = p?.period_start ? tc(diaAnterior(p.period_start)) : fxCierre

    let depositos = dep * fxCierre
    let retiros = ret * fxCierre
    const tipo = p?.period_type
    if ((tipo === 'month' || tipo === 'year') && p?.period_start && p?.period_end && meses.size) {
      const k0 = String(p.period_start).slice(0, 7)
      const k1 = String(p.period_end).slice(0, 7)
      let du = 0, ru = 0, da = 0, ra = 0
      for (const [k, v] of meses) {
        if (k < k0 || k > k1) continue
        du += v.depUsd; ru += v.retUsd; da += v.depArs; ra += v.retArs
      }
      // Sólo si la tabla explica los mismos dólares que muestra el reporte: si
      // no, mezclaríamos dos fuentes y el número no sería de nadie.
      if (cerca(du, dep) && cerca(ru, ret)) { depositos = da; retiros = ra }
    }
    // El dólar que tuvieron los DEPÓSITOS del período (los pesos que mostramos ÷
    // sus dólares): con él, otro monto de depósitos del mismo período (la
    // evidencia de un hallazgo) dice lo mismo que la fila "Depósitos". Se mira
    // sólo el lado de los depósitos: con el neto, un retiro en el mes lo movía.
    const fxDepositos = dep > 0 ? depositos / dep : fxCierre

    const x = (v, fx) => (num(v) == null ? null : num(v) * fx)
    // El realizado: los pesos EXACTOS que manda el servidor (la cuenta única de Operaciones) y,
    // sólo de lo que no tiene pesos, los dólares al dólar del cierre. Ver realizadoEnPesos.js.
    const real = num(m.realized_pnl) == null ? null : realizadoEnPesos({
      usd: m.realized_pnl, ars: m.realized_ars, cubreUsd: m.realized_ars_cubre_usd, fx: fxCierre,
    })
    // El resultado TIENE que contener al realizado, o la tarjeta dice "resultado +$15.000" y debajo
    // "realizado +$240.000" sin posiciones abiertas que lo expliquen. El servidor lo mide en
    // dólares (`delta_usd`), que ya trae adentro el realizado en dólares (`realized_pnl`): se le
    // saca ese pedazo × el dólar del cierre y se le pone el realizado en pesos. Lo demás (lo que
    // no se vendió, el efecto del dólar sobre lo que sigue abierto) queda como estaba.
    const delta = x(m.delta_usd, fxCierre)
    const resultado = delta == null || !real || real.monto == null || num(m.realized_pnl) == null
      ? delta
      : delta + (real.monto - num(m.realized_pnl) * fxCierre)
    return {
      moneda: 'ARS', fxInicio, fxCierre, fxDepositos,
      inicio: x(m.start_value, fxInicio), cierre: x(m.end_value, fxCierre),
      depositos, retiros,
      resultado,
      realizado: real ? real.monto : null,
      realizadoNota: real ? notaDelRealizado({
        restoUsd: Math.abs(real.restoUsd), valuado: !!m.realized_ars_valuado,
      }) : null,
      // Para quien junta varios períodos (el calendario del año): sumar `Math.abs` de estos y
      // armar UNA nota con `notaDelRealizado`, en vez de repetir la de cada mes.
      realizadoRestoUsd: real ? Math.abs(real.restoUsd) : 0,
      realizadoValuado: !!m.realized_ars_valuado,
      noRealizado: x(m.unrealized_pnl, fxCierre),
    }
  }

  /**
   * aportadoHasta — "Capital aportado" acumulado hasta el cierre del período
   * (lo que pusiste, en pesos), con la misma tabla. null si la tabla no explica
   * los dólares del servidor (`cumUsd` = lo que el reporte llama cum_deposited).
   */
  function aportadoHasta(fechaIso, cumUsd) {
    if (!enPesos) return num(cumUsd)
    // `cum_deposited` del servidor no trae el saldo inicial: se compara sin él.
    const a = aportadoAcumuladoAl({ monthly, brokers, dolarMes, tcEnFecha, tcHoy, broker, hastaIso: fechaIso, sinSaldoInicial: true })
    return a && cerca(a.usd, cumUsd) ? a.ars : null
  }

  /** Un resultado en dólares de un período, al dólar de su cierre (hoy si sigue). */
  const alCierre = (usd, periodEnd, enCurso) => (num(usd) == null ? null
    : (enPesos ? num(usd) * ((enCurso || !periodEnd) ? tcHoy : tc(periodEnd)) : num(usd)))
  /** Un monto en dólares de una FECHA puntual (una operación cerrada). */
  const deFecha = (usd, iso) => (num(usd) == null ? null : (enPesos ? num(usd) * tc(iso) : num(usd)))
  /** Un monto en dólares de HOY (el valor actual, variaciones recientes). */
  const deHoy = (usd) => (num(usd) == null ? null : (enPesos ? num(usd) * tcHoy : num(usd)))

  return { moneda: enPesos ? 'ARS' : 'USD', enVista, aportadoHasta, alCierre, deFecha, deHoy }
}
