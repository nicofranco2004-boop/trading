// rendimientoAi — el rendimiento que la pantalla YA calculó, listo para la IA.
// ═══════════════════════════════════════════════════════════════════════════
// El ✦ Analizar le manda al servidor el número que el usuario está mirando —el
// chip de la curva, "Hoy", "Este mes", "Últimos 30 días"— y el servidor se lo
// pasa al modelo tal cual (backend/ai/builders/rendimiento_pantalla.py).
//
// POR QUÉ NO LO RECALCULA EL SERVIDOR. Estos números salen de `evolution.js`
// con el valor VIVO de la cartera, que se calcula acá. Una segunda cuenta en
// Python da otro número apenas difiere cualquier entrada: el valor vivo, lo
// aportado, el día de arranque, qué foto sirve de base. Pasó: el ✦ de la curva
// restaba valores a secas y con un depósito en el medio del mes le decía al
// modelo "+83 %" al lado de un chip que decía "+2,0 %". Es el mismo criterio que
// `distributionAi.js` (las tortas).
//
// EL CONTRATO lo fija backend/tests/fixtures/rendimiento_pantalla.json, que leen
// el test de este archivo y el del servidor: si un lado cambia la forma, el otro
// se pone rojo.

/**
 * @param {null | { usd, pct, prevDate, dayDiff, desde?, valorInicio?, aportes? }} r
 *   lo que devuelven computeDailyPnl / computeReturnDelta / rendimientoDelRango
 * @returns {null | { usd, pct, desde, dias, rotulo_con_fecha?, valor_inicio?, aportes? }}
 *   `null` cuando la pantalla no tiene número: la IA recibe ese mismo vacío, y
 *   no una cuenta hecha por otro lado.
 */
export function rendimientoParaIa(r) {
  if (!r || !Number.isFinite(r.usd) || !Number.isFinite(r.pct)) return null
  const o = {
    usd: redondear(r.usd, 2),
    pct: redondear(r.pct, 8),
    // La fecha del cierre con el que abre la medición (`prevDate`). El motor
    // además trae `desde` —la misma fecha— SÓLO cuando la pantalla la rotula
    // ("desde el DD/MM") porque no había un cierre pegado al arranque del rango.
    desde: r.prevDate ?? r.desde ?? null,
    dias: Number.isFinite(r.dayDiff) ? r.dayDiff : null,
  }
  if (r.desde) o.rotulo_con_fecha = true
  // Sin estos dos la IA igual tiene el número; con ellos puede explicar que un
  // depósito no es ganancia en vez de adivinarlo.
  if (Number.isFinite(r.valorInicio)) o.valor_inicio = redondear(r.valorInicio, 2)
  if (Number.isFinite(r.aportes)) o.aportes = redondear(r.aportes, 2)
  return o
}

function redondear(n, decimales) {
  const f = 10 ** decimales
  return Math.round(n * f) / f
}
