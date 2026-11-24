// resultadoDelMes.js — el resultado de un mes de /api/monthly SIN el puente de un pase.
// ═══════════════════════════════════════════════════════════════════════════
// Cuando pasás títulos de un broker tuyo (A) a otro (B) con «Mover a otro
// broker», el servidor suma al realizado del mes de A la diferencia entre lo que
// valían ese día y lo que costaron (el «puente»: `puente_salida_usd`), y le resta
// lo mismo a B (`puente_entrada_usd`). En el total de la cuenta se anula. Es lo
// correcto para el MONTO (A ganó eso mientras los tuvo; B arranca valiéndolos),
// pero no es rendimiento del mes: no se vendió nada.
//
// Por eso todo cálculo de RENDIMIENTO (el % del mes, el compuesto) sobre filas de
// /api/monthly de un mes CERRADO usa `resultadoSinPuente`. El gasto del trámite
// (`gasto_pase_usd`) SÍ queda: es una pérdida de verdad del broker que lo pagó.
//
// ⚠️ EL MES EN CURSO ES DISTINTO, y por eso la regla vive en una sola función
// (`resultadoParaElPorcentaje`). Ahí el % suma además el no realizado
// (`pnl_unrealized` = lo que vale hoy − lo que costó, de lo que HAY en el
// broker), y los títulos llegan a B con su costo ORIGINAL (C), no con lo que
// valían el día del pase (V). Entonces el no realizado de B ya trae la ganancia
// vieja (V − C), y el puente de entrada −(V − C) es justo lo que la compensa. En
// A pasa al revés: esa ganancia estaba en su no realizado y, al irse los
// títulos, pasa al puente de salida. Sacar el puente en el mes en curso hacía
// que el % de B saltara y el de A cayera el día del pase, y que el % dijera otra
// cosa que el monto de la misma fila. Ejemplo (revisión E12): B arranca el mes
// con 1.000, recibe títulos con C = 100 y V = 300, hoy valen 310 → el monto
// dice +10 (−200 + 210); sin el puente el % decía +21 % (210 / 1.000); con el
// puente, +1 %. En los meses cerrados el no realizado vale 0 y ahí sacar el
// puente es lo correcto (no se vendió nada).
//
// En la fila 'global' con las dos patas vivas el puente viene en 0, así que nada
// cambia; sólo se nota en la fila de cada broker.

const n = (v) => (Number.isFinite(+v) ? +v : 0)

/** El puente neto de la fila (US$): lo que salió menos lo que entró. */
export function puenteDelMes(m) {
  return n(m?.puente_salida_usd) - n(m?.puente_entrada_usd)
}

/** El realizado de la fila (US$) sin el puente de los pases: el que mide rendimiento en un mes cerrado. */
export function resultadoSinPuente(m) {
  return n(m?.pnl_realized) - puenteDelMes(m)
}

/**
 * El resultado (US$) con que se calcula el % de una fila de /api/monthly. UNA
 * regla para los totales, el compuesto y cada fila (MonthlySummary):
 *   · mes cerrado (`enCurso` falso): el realizado SIN el puente;
 *   · mes en curso: el realizado CON el puente + el no realizado. El puente
 *     compensa la ganancia vieja que el no realizado trae al costo original
 *     (ver arriba): así el % cuenta lo mismo que el monto de la fila.
 */
export function resultadoParaElPorcentaje(m, enCurso) {
  return enCurso ? n(m?.pnl_realized) + n(m?.pnl_unrealized) : resultadoSinPuente(m)
}

/**
 * El puente de salida, el de entrada y el gasto de la fila en la moneda de la
 * pestaña. En dólares (`alDolarDelMes` null) son los `*_usd` del servidor. En la
 * pestaña EN PESOS (E.7), la misma regla que el realizado (utils/realizadoEnPesos):
 * la parte de lotes en pesos va con sus pesos exactos (`puente_*_ars`, que
 * `realized_ars` ya lleva adentro; `gasto_pase_ars`, el gasto pagado en pesos) y el
 * resto —lotes en dólares, gasto en dólares— al dólar del mes (`alDolarDelMes`).
 */
export function montosDelPuente(m, alDolarDelMes = null) {
  const salida = n(m?.puente_salida_usd)
  const entrada = n(m?.puente_entrada_usd)
  const gasto = n(m?.gasto_pase_usd)
  if (typeof alDolarDelMes !== 'function') return { salida, entrada, gasto }
  const enPesos = (usd, ars, arsUsd) => n(ars) + n(alDolarDelMes(usd - n(arsUsd)))
  return {
    salida: enPesos(salida, m?.puente_salida_ars, m?.puente_salida_ars_usd),
    entrada: enPesos(entrada, m?.puente_entrada_ars, m?.puente_entrada_ars_usd),
    gasto: enPesos(gasto, m?.gasto_pase_ars, m?.gasto_pase_ars_usd),
  }
}

/**
 * Los renglones que explican el puente debajo del realizado de la fila (uno por
 * concepto distinto de 0). `fmt(x)` formatea un monto en la moneda de la pestaña
 * (y tapa con el ojito); `alDolarDelMes`, en la pestaña en pesos, pasa dólares a
 * pesos con el dólar del mes de la fila (ver `montosDelPuente`).
 */
export function lineasDelPuente(m, fmt, { alDolarDelMes = null } = {}) {
  const out = []
  const { salida, entrada, gasto } = montosDelPuente(m, alDolarDelMes)
  // Qué renglones van lo decide el monto en dólares del servidor (los centavos
  // de redondeo no dibujan un renglón); el signo y el número, el de la pestaña.
  if (Math.abs(n(m?.puente_salida_usd)) >= 0.005) {
    out.push(`Incluye una ${salida > 0 ? 'ganancia' : 'pérdida'} de ${fmt(Math.abs(salida))} de los títulos que pasaste a otro broker (no es una venta).`)
  }
  if (Math.abs(n(m?.puente_entrada_usd)) >= 0.005) {
    out.push(entrada > 0
      ? `Descuenta ${fmt(entrada)}: los títulos que llegaron desde otro broker ya traían esa ganancia (no es una pérdida).`
      : `Suma ${fmt(Math.abs(entrada))}: los títulos que llegaron desde otro broker ya traían esa pérdida.`)
  }
  if (Math.abs(n(m?.gasto_pase_usd)) >= 0.005) out.push(`Incluye ${fmt(gasto)} del costo del pase.`)
  return out
}
