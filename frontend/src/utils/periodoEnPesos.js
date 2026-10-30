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
//   • Lo que tenías al EMPEZAR el período, al dólar de la foto que usó el servidor
//     (`puntas_desde`; si no la dice, el del día anterior al inicio).
//   • Lo que tenías al CERRAR, al dólar de la foto de cierre (hoy, si el período sigue).
//   • Depósitos y retiros de un mes o un año: los pesos que se pusieron o
//     sacaron (`aportesDelMesEnPesos`, la regla del Dashboard). De una semana o
//     un día —`monthly_entries` no baja a esa escala—, al dólar del cierre.
//   • Lo que se ganó o perdió en el período (resultado) depende de DE QUÉ TIPO es el delta que
//     manda el servidor (`metrics.medicion`), que la pantalla NO adivina:
//       'mercado' → la resta de los pesos de la propia tarjeta (cierre − inicio − flujos), cada
//                   punta a su dólar: cierra con la tarjeta e incluye lo que el dólar movió sobre
//                   lo que ya tenías.
//       'motor'   → el resultado en pesos de la ventana que midió el motor mensual (`delta_ars`).
//       'costo' / 'realizado' → lo realizado en pesos exactos más el resto al dólar del cierre
//                   (las puntas son costo en dólares: multiplicarlas por un dólar inventa ganancia).
//   • El REALIZADO en pesos es el de las ventas en pesos (cobrado − costo, los
//     pesos de verdad: la cuenta única de backend/resultado_dual.py, la misma de
//     Movimientos); sólo lo que no tiene pesos (dividendos en dólares, lo cargado
//     a mano) va al dólar del cierre, y se avisa (`realizadoNota`).
//   • El RESULTADO del período contiene a ese realizado, y lo que sobra es el no realizado.
//     NO se arma cambiando el pedazo realizado adentro del delta en dólares: ese delta trae el
//     vaciado de lo latente que la posición traía de antes, y en pesos no es ganancia (ver el
//     bloque de `enVista`).
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
 * @param {boolean}  [args.oculto]    «Ocultar saldos»: la nota de lo convertido sale sin el monto
 */
export function crearPesosDelPeriodo({
  moneda, tcHoy, tcEnFecha, dolarMes, monthly, brokers, broker = 'global', oculto = false,
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
    // DE QUÉ TIPO ES EL DELTA que mandó el servidor (`metrics.medicion`): la pantalla no lo adivina
    // mirando los números, porque la identidad `delta == fin − inicio − flujos` también se cumple en
    // una cadena al costo (por construcción) y no se cumple en el delta del motor mensual.
    const medicion = m.medicion
    // A mercado, cada punta va al dólar de la FOTO que usó el servidor (`puntas_desde/hasta`): la
    // semana arranca con la foto de hasta cinco días antes y el mes acepta bordes corridos un día,
    // así que adivinar por la fecha del período toma el dólar de otro día.
    // Sin `puntas_desde` el arranque no tiene foto: la cuenta nació adentro del período (arranque 0) o su
    // capital previo es chico y está al costo (el guard del servidor lo deja pasar). Se pone al dólar del día
    // anterior: multiplica a un 0 o a un capital chico, cuyo error (capital × lo que subió el dólar desde que
    // entró) el servidor acota con su tolerancia en dólares, no en pesos.
    const puntasMercado = medicion === 'mercado' && !!m.puntas_hasta
    const fxInicio = puntasMercado && m.puntas_desde
      ? tc(m.puntas_desde)
      : (p?.period_start ? tc(diaAnterior(p.period_start)) : fxCierre)
    const fxPuntaCierre = puntasMercado && !p?.is_current ? tc(m.puntas_hasta) : fxCierre

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
    const cierre = x(m.end_value, fxPuntaCierre)
    // El realizado: los pesos EXACTOS que manda el servidor (la cuenta única de Operaciones) y,
    // sólo de lo que no tiene pesos, los dólares al dólar del cierre. Ver realizadoEnPesos.js.
    const realUsd = num(m.realized_pnl)
    const real = realUsd == null ? null : realizadoEnPesos({
      usd: m.realized_pnl, ars: m.realized_ars, cubreUsd: m.realized_ars_cubre_usd, fx: fxCierre,
    })
    const conRealizado = !!real && real.monto != null
    const delta = x(m.delta_usd, fxCierre)

    // EL RESULTADO, SEGÚN DE QUÉ TIPO ES EL DELTA. Tiene que contener al realizado.
    //
    // POR QUÉ NO ALCANZA CON `delta_usd × dólar` NI CON CAMBIARLE EL PEDAZO REALIZADO.
    // `delta_usd` a mercado trae el realizado en dólares MÁS el vaciado de la ganancia o pérdida
    // latente que la posición traía de antes. GGAL comprada a $4.500 (dólar 1.000), que valía
    // $4.500 al arrancar el mes (dólar 1.450 → US$ 3,10) y se vende a $6.900 (dólar 1.500): en
    // dólares el costo es US$ 4,5 y la cartera pasó de 3,10 a 4,6, o sea +1,5 de los cuales sólo
    // 0,1 es "realizado" y 1,4 es el latente que se vació. En pesos no hay latente que vaciar
    // (costaba $4.500 y valía $4.500): se ganaron $2.400, todos realizados. Cambiar sólo el pedazo
    // realizado y dejar el vaciado en dólares sumaba $4.495: casi el doble.
    //
    //  · 'mercado': la resta de los pesos de la propia tarjeta —valor de cierre − valor de inicio −
    //    (depósitos − retiros)—, cada punta a su dólar. Es la cuenta del porcentaje de Pesos del
    //    servidor y del «Resultado total» del Dashboard; cierra por construcción, e incluye lo que
    //    el dólar movió sobre lo que ya se tenía. Lo realizado es una PARTE: lo que sobra es el no
    //    realizado.
    //  · 'motor': el delta es de OTRA ventana que start/end_value (la que midió el motor mensual),
    //    así que la resta de la tarjeta no aplica: el servidor manda el resultado en pesos de esa
    //    ventana (`delta_ars`, las mismas patas que su % en pesos).
    //  · 'costo' y 'realizado': start/end_value son COSTO en dólares (a cada dólar de depósito) o el
    //    delta es lo vendido de un broker filtrado: multiplicar por el dólar de las fechas fabrica
    //    una ganancia que no existió. Ahí el resultado es lo realizado en pesos exactos más lo que
    //    el delta trae aparte (dividendos y demás) al dólar del cierre.
    // Si el tipo no viene (una respuesta anterior al campo) se trata como 'costo', la lectura que
    // no inventa pesos. Con base incomparable el servidor ya no publica monto: no se mezcla nada.
    // (Sin saldo en ninguna de las dos puntas no hay resta que repetir: daría 0 − 0 − 0 aunque se haya
    // vendido. Y un delta del motor sin su monto en pesos queda en delta × dólar, sin mezclar nada.)
    const sumaMercado = medicion === 'mercado' && !m.basis_incomparable && inicio != null && cierre != null
      && (num(m.start_value) !== 0 || num(m.end_value) !== 0)
    const delMotor = medicion === 'motor' && num(m.delta_ars) != null
    const alCosto = !m.basis_incomparable && !sumaMercado && !delMotor && medicion !== 'motor'
    const sinSaldo = num(m.start_value) === 0 && num(m.end_value) === 0

    let resultado, noRealizado
    if (sumaMercado) {
      resultado = cierre - inicio - (depositos - retiros)
      noRealizado = conRealizado ? resultado - real.monto : x(m.unrealized_pnl, fxCierre)
    } else if (delMotor) {
      resultado = num(m.delta_ars)
      noRealizado = conRealizado ? resultado - real.monto : x(m.unrealized_pnl, fxCierre)
    } else if (alCosto && conRealizado && sinSaldo) {
      // Un período sin ninguna foto (cuenta cuyo cron nunca corrió): el servidor no midió nada —las dos
      // puntas valen 0 y el delta queda en 0— y arma el «no realizado» restando delta − realizado. En
      // pesos eso se multiplicaba por el dólar y salía una ganancia que nadie midió (+$125.027 al lado de
      // una venta de +$65.982). Lo único que se sabe es lo vendido, y es exacto.
      resultado = real.monto
      noRealizado = 0
    } else if (alCosto && conRealizado && delta != null) {
      resultado = real.monto + (num(m.delta_usd) - realUsd) * fxCierre
      noRealizado = x(m.unrealized_pnl, fxCierre)
    } else {
      resultado = delta
      noRealizado = x(m.unrealized_pnl, fxCierre)
    }
    return {
      moneda: 'ARS', fxInicio, fxCierre, fxDepositos,
      // De qué tipo es el resultado ('mercado' | 'motor' | 'costo' | 'realizado'): quien lo repite
      // (la evidencia de un hallazgo) sabe si incluye lo que el dólar movió sobre lo que ya se tenía.
      medicion: medicion ?? null,
      inicio, cierre,
      depositos, retiros,
      resultado,
      realizado: real ? real.monto : null,
      realizadoNota: real ? notaDelRealizado({
        restoUsd: Math.abs(real.restoUsd), valuado: !!m.realized_ars_valuado, oculto,
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

  /**
   * ¿El % de este período sigue en DÓLARES aunque el monto se vea en pesos? El servidor sólo pasa a
   * pesos el % de un mes o un año (y lo dice en `metrics.moneda`: la demo y un servidor anterior
   * lo mandan en dólares); el de un día o una semana sale de las fotos en dólares. Mirándolos
   * juntos pueden tener signos opuestos (la cartera cae 0,2 % en dólares, el dólar sube 0,5 %: en
   * pesos ganó), así que la pantalla lo rotula en vez de dejarlos como si fueran la misma cuenta.
   */
  const pctEnDolares = (p) => enPesos && (p?.period_type === 'day' || p?.period_type === 'week'
    || String(p?.metrics?.moneda ?? 'usd').toLowerCase() !== 'ars')

  /** Un resultado en dólares de un período, al dólar de su cierre (hoy si sigue). */
  const alCierre = (usd, periodEnd, enCurso) => (num(usd) == null ? null
    : (enPesos ? num(usd) * ((enCurso || !periodEnd) ? tcHoy : tc(periodEnd)) : num(usd)))
  /** Un monto en dólares de una FECHA puntual (una operación cerrada). */
  const deFecha = (usd, iso) => (num(usd) == null ? null : (enPesos ? num(usd) * tc(iso) : num(usd)))
  /** Un monto en dólares de HOY (el valor actual, variaciones recientes). */
  const deHoy = (usd) => (num(usd) == null ? null : (enPesos ? num(usd) * tcHoy : num(usd)))

  return { moneda: enPesos ? 'ARS' : 'USD', enVista, pctEnDolares, aportadoHasta, alCierre, deFecha, deHoy }
}
