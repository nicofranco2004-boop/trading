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
//   • Lo que se ganó o perdió en el período (resultado): la resta de los pesos de la propia
//     tarjeta —valor de cierre − valor de inicio − (depósitos − retiros)—, cada punta a su
//     dólar, así que la tarjeta cierra. Sólo cuando el servidor midió el delta con otra medida
//     (motor mensual, broker filtrado) queda el delta en dólares al dólar del cierre.
//   • El REALIZADO en pesos es el de las ventas en pesos (cobrado − costo, los
//     pesos de verdad: la cuenta única de backend/resultado_dual.py, la misma de
//     Movimientos); sólo lo que no tiene pesos (dividendos en dólares, lo cargado
//     a mano) va al dólar del cierre, y se avisa (`realizadoNota`).
//   • El RESULTADO del período contiene a ese realizado, y lo que sobra es el no realizado
//     (resultado = realizado + no realizado + otros, también en pesos). NO se arma cambiando
//     el pedazo realizado adentro del delta en dólares: ese delta trae el vaciado de lo latente
//     que la posición traía de antes, y en pesos no es ganancia (ver el bloque de `enVista`).
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
    const inicio = x(m.start_value, fxInicio)
    const cierre = x(m.end_value, fxCierre)
    // El realizado: los pesos EXACTOS que manda el servidor (la cuenta única de Operaciones) y,
    // sólo de lo que no tiene pesos, los dólares al dólar del cierre. Ver realizadoEnPesos.js.
    const real = num(m.realized_pnl) == null ? null : realizadoEnPesos({
      usd: m.realized_pnl, ars: m.realized_ars, cubreUsd: m.realized_ars_cubre_usd, fx: fxCierre,
    })

    // EL RESULTADO TIENE QUE CONTENER AL REALIZADO, y la tarjeta tiene que cerrar:
    // valor inicio + depósitos − retiros + resultado = valor cierre.
    //
    // POR QUÉ NO ALCANZA CON `delta_usd × dólar` NI CON CAMBIARLE EL PEDAZO REALIZADO.
    // `delta_usd` mide la cartera a mercado en DÓLARES: trae el realizado en dólares MÁS el
    // vaciado de la ganancia o pérdida latente que la posición traía de antes. GGAL comprada a
    // $4.500 (dólar 1.000), que valía $4.500 al arrancar el mes (dólar 1.450 → US$ 3,10) y se
    // vende a $6.900 (dólar 1.500): en dólares el costo es US$ 4,5 y la cartera pasó de 3,10 a
    // 4,6, o sea +1,5 de los cuales sólo 0,1 es "realizado" y 1,4 es el latente que se vació. En
    // pesos no hay latente que vaciar (costaba $4.500 y valía $4.500): se ganaron $2.400, todos
    // realizados. Cambiar sólo el pedazo realizado (+$2.400 en vez de 0,1 × 1.500) y dejar el
    // vaciado en dólares (1,4 × 1.500 = $2.095) sumaba $4.495: casi el doble.
    //
    // Por eso, cuando el servidor midió el período como "valor de cierre − valor de inicio −
    // flujos" (el caso normal: su `delta_usd` es exactamente esa resta), el resultado en pesos
    // es la MISMA resta con los números en pesos que la propia tarjeta muestra, cada punta a su
    // dólar. Es lo que ya hace el porcentaje de Pesos del servidor (`_pct_en_pesos`) y el
    // resultado del Dashboard (valor − capital aportado en pesos). Cierra por construcción, y
    // lo realizado es una PARTE de él: lo que sobra (`noRealizado`) sale de restar.
    const dolaresDelServidor = num(m.delta_usd)
    const noRealizadoUsd = num(m.unrealized_pnl)
    const iniUsd = num(m.start_value)
    const finUsd = num(m.end_value)
    const sumaDelServidor = iniUsd != null && finUsd != null && dolaresDelServidor != null
      && (iniUsd !== 0 || finUsd !== 0)
      && Math.abs(dolaresDelServidor - (finUsd - iniUsd - (dep - ret))) <= 0.05
    const delta = x(m.delta_usd, fxCierre)

    let resultado, noRealizado
    if (sumaDelServidor && inicio != null && cierre != null) {
      resultado = cierre - inicio - (depositos - retiros)
      // Lo que no es ni vendido ni abierto (dividendos y demás) va al dólar del cierre, como siempre.
      const otrosUsd = (real && num(m.realized_pnl) != null && noRealizadoUsd != null)
        ? dolaresDelServidor - num(m.realized_pnl) - noRealizadoUsd : 0
      noRealizado = real && real.monto != null
        ? resultado - real.monto - otrosUsd * fxCierre
        : x(m.unrealized_pnl, fxCierre)
    } else {
      // El servidor pisó el delta con otra medida (el motor mensual, un broker filtrado en una
      // semana, base incomparable): no hay resta que repetir en pesos. Si no hay posiciones
      // abiertas que se hayan movido (`unrealized_pnl` 0, como las semanas con un broker
      // filtrado, donde el delta ES lo realizado), el resultado es el realizado en pesos. Si las
      // hay, queda el delta en dólares × dólar del cierre, sin meterle pesos exactos encima:
      // mezclar las dos medidas era lo que inflaba el resultado.
      const sinAbiertas = noRealizadoUsd != null && Math.abs(noRealizadoUsd) < 0.005
      resultado = delta == null || !real || real.monto == null || num(m.realized_pnl) == null || !sinAbiertas
        ? delta
        : delta + (real.monto - num(m.realized_pnl) * fxCierre)
      noRealizado = x(m.unrealized_pnl, fxCierre)
    }
    return {
      moneda: 'ARS', fxInicio, fxCierre, fxDepositos,
      inicio, cierre,
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
      noRealizado,
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
