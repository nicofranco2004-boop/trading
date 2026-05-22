// profileMatch — funciones puras que cruzan investor profile con cartera real.
// ═══════════════════════════════════════════════════════════════════════════
// Cada función devuelve un CardData con shape consistente:
//
//   {
//     status: 'ready' | 'no_profile' | 'no_portfolio' | 'no_data',
//     declared: { ... },     // info derivada del test (siempre que haya profile)
//     actual:   { ... },     // info derivada de la cartera (siempre que haya positions)
//     comparison: { ... },   // comparación + magnitud del gap
//   }
//
// REGLA: estas funciones NUNCA generan texto interpretativo ("deberías", "te
// conviene"). Solo devuelven datos crudos. El componente de UI los formatea
// en una frase descriptiva neutra.

import {
  deriveProfileCategory,
  SUGGESTED_ALLOCATIONS,
  PROFILE_LABELS,
  TYPICAL_CONCENTRATION_TOP3,
  DRAWDOWN_TOLERANCE_BY_BEHAVIOR,
  HORIZON_EXPECTATION,
  classifyAssetBucket,
  computeAllocationBuckets,
} from './profileAllocations'


// ─── Card 1: Match perfil vs cartera (allocation) ───────────────────────────
//
// Compara la asignación de activos sugerida por el perfil declarado contra
// la asignación real de la cartera, bucket por bucket.

/**
 * computeAllocationMatch
 *
 * @param {Object} profile   { horizon, drawdown, goal, ... } o null
 * @param {Array}  positions con value_usd
 * @param {Array}  brokers
 * @returns {Object} CardData
 */
export function computeAllocationMatch(profile, positions, brokers) {
  const category = deriveProfileCategory(profile)

  if (!category) {
    return {
      status: positions?.length > 0 ? 'no_profile' : 'no_data',
    }
  }

  const actual = computeAllocationBuckets(positions || [], brokers || [])
  if (actual.totalUsd === 0) {
    return {
      status: 'no_portfolio',
      declared: {
        category,
        categoryLabel: PROFILE_LABELS[category],
        suggested: SUGGESTED_ALLOCATIONS[category],
      },
    }
  }

  const suggested = SUGGESTED_ALLOCATIONS[category]
  const buckets = ['cash', 'fixed_income', 'equity', 'alternative']

  // Delta absoluto por bucket (puntos porcentuales sobre/debajo del sugerido).
  // Magnitud agregada = suma de |delta| / 2 (porque cada gap se cuenta una
  // vez positivo y una vez negativo, dividido por 2 nos da el "shift" total).
  const deltas = {}
  let absSum = 0
  for (const b of buckets) {
    deltas[b] = (actual[b] || 0) - suggested[b]
    absSum += Math.abs(deltas[b])
  }
  const driftPct = absSum / 2

  return {
    status: 'ready',
    declared: {
      category,
      categoryLabel: PROFILE_LABELS[category],
      suggested,
    },
    actual: {
      buckets: {
        cash:         Math.round(actual.cash),
        fixed_income: Math.round(actual.fixed_income),
        equity:       Math.round(actual.equity),
        alternative:  Math.round(actual.alternative),
      },
      totalUsd: actual.totalUsd,
    },
    comparison: {
      deltas,           // signed pp por bucket
      driftPct,         // magnitud total del desvío, 0-100
    },
  }
}


// ─── Card 5: Coherencia objetivo declarado ──────────────────────────────────
//
// Cruza el `goal` del test con el % de la cartera que está en activos
// alineados con ese objetivo (o desalineados).
//
// Mapeo objetivo → buckets "alineados" y "desalineados":
//   specific_purchase, retirement (corto-medio plazo de vida)
//     → alineado: cash + fixed_income
//     → desalineado: equity + alternative
//   freedom, learn, hobby (largo plazo / crecimiento)
//     → alineado: equity + alternative
//     → desalineado: cash + fixed_income

const GOAL_ALIGNMENT = {
  specific_purchase: {
    label: 'compra puntual (casa, auto, viaje)',
    timeframe: 'corto/medio plazo',
    alignedBuckets: ['cash', 'fixed_income'],
    misalignedBuckets: ['equity', 'alternative'],
    alignedLabel: 'cash y renta fija',
    misalignedLabel: 'renta variable y alternativos',
  },
  retirement: {
    label: 'jubilación',
    timeframe: 'largo plazo, baja tolerancia a drawdown cercano',
    // Para retirement la respuesta correcta depende mucho de la edad del
    // user (que no preguntamos). Asumimos que retirement implica preservar
    // capital — sesgo conservador. Si el user tiene 25 años y marcó
    // retirement, esta card va a sugerir que está sobre-expuesto a equity,
    // lo cual es discutible. Aceptamos esa simplificación.
    alignedBuckets: ['cash', 'fixed_income'],
    misalignedBuckets: ['equity', 'alternative'],
    alignedLabel: 'cash y renta fija',
    misalignedLabel: 'renta variable y alternativos',
  },
  freedom: {
    label: 'libertad financiera',
    timeframe: 'largo plazo, crecimiento',
    alignedBuckets: ['equity', 'alternative'],
    misalignedBuckets: ['cash', 'fixed_income'],
    alignedLabel: 'renta variable y alternativos',
    misalignedLabel: 'cash y renta fija',
  },
  learn: {
    label: 'aprender a invertir',
    timeframe: 'horizonte abierto, exposición a múltiples instrumentos',
    alignedBuckets: ['equity', 'alternative'],
    misalignedBuckets: ['cash', 'fixed_income'],
    alignedLabel: 'renta variable y alternativos',
    misalignedLabel: 'cash y renta fija',
  },
  hobby: {
    label: 'hobby / pasatiempo',
    timeframe: 'experimentación, exposición activa',
    alignedBuckets: ['equity', 'alternative'],
    misalignedBuckets: ['cash', 'fixed_income'],
    alignedLabel: 'renta variable y alternativos',
    misalignedLabel: 'cash y renta fija',
  },
}

/**
 * computeObjectiveCoherence
 *
 * @param {Object} profile
 * @param {Array}  positions
 * @param {Array}  brokers
 * @returns {Object} CardData
 */
export function computeObjectiveCoherence(profile, positions, brokers) {
  const goal = profile?.goal
  if (!goal || !GOAL_ALIGNMENT[goal]) {
    return {
      status: positions?.length > 0 ? 'no_profile' : 'no_data',
    }
  }

  const goalCfg = GOAL_ALIGNMENT[goal]
  const actual = computeAllocationBuckets(positions || [], brokers || [])
  if (actual.totalUsd === 0) {
    return {
      status: 'no_portfolio',
      declared: {
        goal,
        goalLabel: goalCfg.label,
        timeframe: goalCfg.timeframe,
        alignedLabel: goalCfg.alignedLabel,
      },
    }
  }

  const alignedPct = goalCfg.alignedBuckets.reduce(
    (sum, b) => sum + (actual[b] || 0), 0,
  )
  const misalignedPct = goalCfg.misalignedBuckets.reduce(
    (sum, b) => sum + (actual[b] || 0), 0,
  )

  return {
    status: 'ready',
    declared: {
      goal,
      goalLabel: goalCfg.label,
      timeframe: goalCfg.timeframe,
      alignedLabel: goalCfg.alignedLabel,
      misalignedLabel: goalCfg.misalignedLabel,
    },
    actual: {
      alignedPct: Math.round(alignedPct),
      misalignedPct: Math.round(misalignedPct),
      totalUsd: actual.totalUsd,
    },
  }
}


// ─── Card 2: Horizonte declarado vs composición ─────────────────────────────
//
// Cruza el horizonte declarado con el % de cartera en activos consistentes
// con ese horizonte (expectedBuckets) vs activos que generan riesgo para
// ese horizonte (riskBuckets).
//
// Ejemplo: horizon=long → expectedBuckets=[equity, alternative]. Si el
// user marcó largo plazo pero tiene 70% en cash, la card lo muestra
// sin juzgar ("Marcaste horizonte largo. Tu cartera tiene 70% en cash y
// renta fija.").

export function computeHorizonComposition(profile, positions, brokers) {
  const horizon = profile?.horizon
  if (!horizon || !HORIZON_EXPECTATION[horizon]) {
    return {
      status: positions?.length > 0 ? 'no_profile' : 'no_data',
    }
  }

  const horCfg = HORIZON_EXPECTATION[horizon]
  const actual = computeAllocationBuckets(positions || [], brokers || [])
  if (actual.totalUsd === 0) {
    return {
      status: 'no_portfolio',
      declared: {
        horizon,
        horizonLabel: horCfg.label,
        expectedLabel: horCfg.expectedLabel,
        riskLabel: horCfg.riskLabel,
      },
    }
  }

  const expectedPct = horCfg.expectedBuckets.reduce(
    (sum, b) => sum + (actual[b] || 0), 0,
  )
  const riskPct = horCfg.riskBuckets.reduce(
    (sum, b) => sum + (actual[b] || 0), 0,
  )

  return {
    status: 'ready',
    declared: {
      horizon,
      horizonLabel: horCfg.label,
      expectedLabel: horCfg.expectedLabel,
      riskLabel: horCfg.riskLabel,
    },
    actual: {
      expectedPct: Math.round(expectedPct),
      riskPct: Math.round(riskPct),
      totalUsd: actual.totalUsd,
    },
  }
}


// ─── Card 3: Tolerancia drawdown declarada vs drawdown real ────────────────
//
// El test captura un BEHAVIOR (sell_all / sell_some / hold / buy_more) ante
// un drawdown del 30%. Lo mapeamos a un rango de tolerancia implícita en %
// (ver DRAWDOWN_TOLERANCE_BY_BEHAVIOR en profileAllocations.js).
//
// Cruzamos con el drawdown máximo REAL de la cartera en los últimos 12m
// (que viene precomputado en Insights — computeDrawdownOnReturns sobre TWRR).
//
// drawdownMaxPct: número POSITIVO (magnitud del drawdown). El caller le
// hace Math.abs() antes de pasarlo porque computeDrawdownOnReturns devuelve
// el drawdown como % negativo.

export function computeDrawdownTolerance(profile, drawdownMaxPct) {
  const behavior = profile?.drawdown
  if (!behavior || !DRAWDOWN_TOLERANCE_BY_BEHAVIOR[behavior]) {
    return {
      status: drawdownMaxPct != null ? 'no_profile' : 'no_data',
    }
  }

  const tol = DRAWDOWN_TOLERANCE_BY_BEHAVIOR[behavior]
  // Si no tenemos drawdown real (sin cartera o sin historia), solo mostramos
  // la tolerancia declarada como informativa.
  if (drawdownMaxPct == null || !isFinite(drawdownMaxPct)) {
    return {
      status: 'no_portfolio',
      declared: {
        behavior,
        behaviorLabel: tol.label,
        impliedTolerance: tol,
      },
    }
  }

  // Magnitud absoluta (drawdownMaxPct puede llegar negativo o positivo —
  // computeDrawdownOnReturns devuelve negativo).
  const realDdPct = Math.abs(drawdownMaxPct)

  // Comparison: el real está DENTRO del rango declarado, ABAJO, o ARRIBA?
  let comparison = 'within'
  if (realDdPct < tol.min) comparison = 'below'
  else if (realDdPct > tol.max) comparison = 'above'

  return {
    status: 'ready',
    declared: {
      behavior,
      behaviorLabel: tol.label,
      impliedTolerance: tol,
    },
    actual: {
      drawdownPct: Math.round(realDdPct * 10) / 10,  // 1 decimal
    },
    comparison,
  }
}


// ─── Card 4: Concentración top 3 vs benchmark del perfil ───────────────────
//
// Calcula el % del portfolio en los top 3 activos (por valor USD agregado
// entre brokers), y lo compara con el rango típico del perfil derivado.
//
// Edge cases:
//   • <3 holdings: top N = TODO el portfolio. Lo notamos en holdingsCount.
//   • Sin perfil derivable: no_profile.

export function computeConcentrationVsProfile(profile, positions, brokers) {
  const category = deriveProfileCategory(profile)
  if (!category) {
    return {
      status: positions?.length > 0 ? 'no_profile' : 'no_data',
    }
  }

  const range = TYPICAL_CONCENTRATION_TOP3[category]
  // Agregamos por activo (no por position individual) sumando entre brokers.
  const valuesByAsset = new Map()
  let total = 0
  for (const p of positions || []) {
    if (p.is_cash) continue
    if (p.value_usd == null || p.value_usd <= 0) continue
    const k = String(p.asset || '').toUpperCase()
    valuesByAsset.set(k, (valuesByAsset.get(k) || 0) + p.value_usd)
    total += p.value_usd
  }

  if (total === 0 || valuesByAsset.size === 0) {
    return {
      status: 'no_portfolio',
      declared: {
        category,
        categoryLabel: PROFILE_LABELS[category],
        typicalRange: range,
      },
    }
  }

  const sorted = [...valuesByAsset.entries()].sort((a, b) => b[1] - a[1])
  const top3Sum = sorted.slice(0, 3).reduce((s, [, v]) => s + v, 0)
  const top3Pct = (top3Sum / total) * 100
  const top3Assets = sorted.slice(0, 3).map(([asset]) => asset)

  // Comparison contra el rango típico.
  let comparison = 'within'
  if (top3Pct < range.min) comparison = 'below'
  else if (top3Pct > range.max) comparison = 'above'

  return {
    status: 'ready',
    declared: {
      category,
      categoryLabel: PROFILE_LABELS[category],
      typicalRange: range,
    },
    actual: {
      top3Pct: Math.round(top3Pct),
      top3Assets,
      holdingsCount: valuesByAsset.size,
    },
    comparison,
  }
}
