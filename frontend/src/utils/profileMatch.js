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
