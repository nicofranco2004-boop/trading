// pctDeLaFila.js — el P&L % de una fila de Cartera, en la moneda que se mira.
// ════════════════════════════════════════════════════════════════════════════
// Una posición de un broker en pesos tiene DOS porcentajes de ganancia, y los
// dos son ciertos: el nominal en pesos (pesos de hoy contra pesos pagados) y el
// que resulta en dólares (contra los dólares que valían esos pesos el día de
// cada compra, en el modo "dólar de compra", que es el de casi todos). Cuando el
// peso se devaluó más de lo que subió la acción, tienen signo distinto.
//
// La regla es que el % va en la MISMA moneda que el monto de al lado. El
// escritorio la cumple desde 932bebfc (`adjPnlPct` en Positions.jsx). El
// celular, hasta el 21/10/2026, dejaba el % en pesos también con la vista en
// dólares: GGAL del demo salía "−$133 · +13,4 %" en el teléfono y
// "−USD 132,56 · −16,4 %" en la compu.
//
// Recibe la fila ya valuada por PositionsMobile (`isAR`, `pnlPct` nativo,
// `pnlUsd` e `investedUsd` en la base del modo). En pesos o fuera de un broker
// ARS devuelve `pnlPct` tal cual; con la vista en dólares, una fila de broker
// ARS pasa a `pnlUsd / investedUsd`. La fila que fusiona monedas ya trae su %
// en USD (aggregateMobile), así que no se toca. En modo 'today' los dos
// porcentajes coinciden y el resultado es el mismo de siempre.
export function pctEnVista(p, moneda) {
  if (!p) return null
  if (moneda === 'ARS' || !p.isAR || p._multiCcy) return p.pnlPct ?? null
  return p.investedUsd > 0 ? p.pnlUsd / p.investedUsd : 0
}
