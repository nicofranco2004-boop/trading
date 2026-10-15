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
//   • Lo que se ganó o perdió en el período (resultado, realizado, no
//     realizado), al dólar del cierre: es plata de ese momento.
//
// En dólares devuelve los mismos números del servidor, sin tocar.

import { aportesDelMesEnPesos, aportadoAcumuladoAl } from './capitalAportado'

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
 * @param {Object}   args.tcMensual   `tcMensual` de useFxHistory
 * @param {Array}    [args.monthly]   /api/monthly (sin esto, los flujos van al
 *                                    dólar del cierre)
 * @param {Array}    [args.brokers]   /api/brokers
 * @param {string}   [args.broker]    'global' o el broker del filtro
 */
export function crearPesosDelPeriodo({
  moneda, tcHoy, tcEnFecha, tcMensual, monthly, brokers, broker = 'global',
} = {}) {
  const enPesos = moneda === 'ARS' && tcHoy > 0
  const meses = enPesos && Array.isArray(monthly) && monthly.length
    ? aportesDelMesEnPesos({ monthly, brokers, tcMensual, tcHoy, broker })
    : new Map()
  const tc = (iso) => {
    const v = iso && typeof tcEnFecha === 'function' ? tcEnFecha(iso) : null
    return v > 0 ? v : tcHoy
  }

  /**
   * @returns {{ moneda, fxInicio, fxCierre, fxFlujos, inicio, cierre,
   *             depositos, retiros, resultado, realizado, noRealizado }}
   *   montos YA en `moneda` (formatear sin convertir: fmtConvertedRaw). Los
   *   `fx*` sirven para pasar otros montos del mismo período con la misma regla.
   */
  function enVista(p) {
    const m = p?.metrics || {}
    const dep = num(m.deposits) || 0
    const ret = num(m.withdrawals) || 0
    if (!enPesos) {
      return {
        moneda: 'USD', fxInicio: 1, fxCierre: 1, fxFlujos: 1,
        inicio: num(m.start_value), cierre: num(m.end_value),
        depositos: dep, retiros: ret,
        resultado: num(m.delta_usd), realizado: num(m.realized_pnl), noRealizado: num(m.unrealized_pnl),
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
    // El dólar que tuvieron los flujos del período (para la evidencia de los
    // hallazgos). Con un neto chico el cociente no significa nada.
    const netoUsd = dep - ret
    const implicito = Math.abs(netoUsd) >= 1 ? (depositos - retiros) / netoUsd : null
    const fxFlujos = implicito && implicito / fxCierre >= 0.6 && implicito / fxCierre <= 1.6
      ? implicito : fxCierre

    const x = (v, fx) => (num(v) == null ? null : num(v) * fx)
    return {
      moneda: 'ARS', fxInicio, fxCierre, fxFlujos,
      inicio: x(m.start_value, fxInicio), cierre: x(m.end_value, fxCierre),
      depositos, retiros,
      resultado: x(m.delta_usd, fxCierre),
      realizado: x(m.realized_pnl, fxCierre),
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
    const a = aportadoAcumuladoAl({ monthly, brokers, tcMensual, tcHoy, broker, hastaIso: fechaIso })
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
