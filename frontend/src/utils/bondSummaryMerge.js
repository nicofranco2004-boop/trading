// bondSummaryMerge.js — las cobranzas de un bono que vive en las DOS patas.
// ════════════════════════════════════════════════════════════════════════════
// `bondCashflowsByKey` guarda las cobranzas por (broker, activo). Eso está bien
// mientras cada fila de la tabla sea de UN broker. Pero en una cuenta unificada
// (la pata pesos y la pata dólar mostradas juntas) la tabla fusiona el mismo
// bono de las dos patas en UNA fila, y esa fila no tiene un broker: `_buildAgg`
// le pone `broker: null` a propósito, porque el nombre del broker es a dónde
// iría a parar una escritura.
//
// Sin esta función, esa fila buscaba la clave "null:GD30", que no existe nunca.
// Consecuencias medidas en la app el 2026-09-22, con tres cupones cargados:
//   • el P&L de la fila daba +USD 9.201,85 unificada y +USD 10.500,12 separada
//     — US$1.298 de diferencia, que son exactamente los cupones que la fila
//     fusionada no veía. El mismo bono, el mismo día, a un click de distancia.
//   • el panel afirmaba "Aún no registraste cobranzas" con los cupones ya
//     cobrados y acreditados al cash, y el cronograma decía "sin registro".
//   • el contador del botón ("Ver cobranzas (2)") desaparecía.
//
// Todo lo que se suma acá es aditivo entre patas PORQUE está en USD. La única
// excepción es `pnlContribution`, que está en la moneda NATIVA de cada pata:
// sumar los pesos de una con los dólares de la otra daría un número sin unidad.
// Cuando las patas no coinciden en moneda queda en null, y la fila cae al P&L
// sin cupones en esa columna — que es lo que ya hace con `valueArs`.

/**
 * @param sums  los resúmenes de cada pata (los que falten vienen undefined)
 * @returns un resumen con la misma forma, o null si no hay ninguno
 */
export function mergeBondSummaries(sums) {
  const reales = (sums || []).filter(Boolean)
  if (reales.length === 0) return null
  if (reales.length === 1) return reales[0]

  const monedas = new Set(reales.map(s => s.currency || null))
  const mismaMoneda = monedas.size === 1

  const usdByOpId = new Map()
  for (const s of reales) {
    if (s.usdByOpId) for (const [k, v] of s.usdByOpId) usdByOpId.set(k, v)
  }

  const sum = (campo) => reales.reduce((acc, s) => acc + (s[campo] || 0), 0)

  return {
    ops: reales.flatMap(s => s.ops || []),
    // Cash recibido y su conversión a USD: aditivos.
    coupons: mismaMoneda ? sum('coupons') : null,
    amortizations: mismaMoneda ? sum('amortizations') : null,
    total: mismaMoneda ? sum('total') : null,
    couponsUsd: sum('couponsUsd'),
    amortizationsUsd: sum('amortizationsUsd'),
    totalUsd: sum('totalUsd'),
    // Aporte al P&L: el nativo sólo si las dos patas hablan la misma moneda.
    pnlContribution: mismaMoneda ? sum('pnlContribution') : null,
    pnlContributionUsd: sum('pnlContributionUsd'),
    usdByOpId,
    hasLegacyOps: reales.some(s => s.hasLegacyOps),
    currency: mismaMoneda ? (reales[0].currency || null) : null,
    // Marca para la fila: acá hay más de una pata, así que registrar un cobro
    // nuevo no sabe a cuál mandarlo. El panel se muestra, pero de sólo lectura.
    _variasPatas: true,
  }
}

/**
 * El resumen que le corresponde a UNA fila de la tabla, sea de una pata o de
 * las dos. `_brokers` lo pone `_buildAgg` con todas las patas del grupo.
 */
export function bondSummaryDeLaFila(p, bondCashflowsByKey) {
  if (!p || !bondCashflowsByKey) return null
  const patas = (p._brokers && p._brokers.length) ? p._brokers : [p.broker]
  return mergeBondSummaries(patas.map(b => bondCashflowsByKey.get(`${b}:${p.asset}`)))
}
