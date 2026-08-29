// distributionAi — el corte de distribución, listo para mandarle a la IA.
// ═══════════════════════════════════════════════════════════════════════════
// El packet de los topics `portfolio.distribution_type` / `_sector` lo arma el
// FRONTEND, no el backend. El motivo está en la cabecera de
// backend/ai/builders/distribution.py: la clasificación y el cálculo de
// resultado viven acá, y una segunda implementación en Python terminaría
// dando números distintos a los que la persona tiene en pantalla.
//
// Este módulo traduce el breakdown al shape del builder y lo achica: la card
// muestra 10 porciones con 12 activos cada una, pero al modelo le alcanza con
// las que mueven la aguja. Claves cortas (`a`/`w`/`p`) porque viajan por red y
// entran en el contexto del modelo.

const MAX_SLICES = 12
const MAX_ASSETS = 6

/**
 * @param {Object} breakdown  lo que devuelve computeClassBreakdown /
 *                            computeSectorBreakdown
 * @returns {Object} params para AskAIAbout
 */
export function toDistributionAiParams(breakdown) {
  const items = breakdown?.items || []
  return {
    total_usd: Math.round(breakdown?.total || 0),
    unclassified_pct: +(breakdown?.unclassified?.pct || 0).toFixed(1),
    slices: items.slice(0, MAX_SLICES).map(i => {
      const s = {
        label: i.label,
        value_usd: Math.round(i.value),
        weight_pct: +i.pct.toFixed(1),
      }
      if (i.pnl) {
        s.pnl_usd = Math.round(i.pnl.total)
        // Puede faltar a propósito: cuando alguna venta no trae con qué
        // despejar el costo preferimos no publicar una tasa inflada.
        if (i.pnl.pct != null) s.pnl_pct = +i.pnl.pct.toFixed(1)
      }
      const assets = (i.assets || []).slice(0, MAX_ASSETS).map(a => {
        const o = { a: a.asset, w: +a.pct.toFixed(1) }
        if (a.pnl?.pct != null) o.p = +a.pnl.pct.toFixed(1)
        return o
      })
      if (assets.length) s.assets = assets
      return s
    }),
  }
}
