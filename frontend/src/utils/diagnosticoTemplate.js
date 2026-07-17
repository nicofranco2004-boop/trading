// diagnosticoTemplate — motor de la plantilla adaptativa del tab Diagnóstico.
// ═══════════════════════════════════════════════════════════════════════════
// La plantilla es FIJA (un set de slots); qué slot aparece, en qué orden y
// cuáles se suprimen lo decide este motor determinístico a partir de señales
// que Insights.jsx ya computa. Mismo espíritu que profileDashboard.js: la IA
// no decide el layout, y un slot sin data se SUPRIME (no se muestra vacío).
//
//   buildDiagnosticoLayout(signals) →
//     { archetype, slots: ['data_integrity','delta',...], isNew, isEmpty }
//
// Capa 1 — arquetipo (empty / new / crypto / conservador_ar / completo):
//   clasifica al usuario por señales de cartera + historial.
// Capa 2 — orden + visibilidad de slots:
//   cada slot tiene un peso base y una regla de visibilidad; algunos
//   arquetipos re-priorizan (el conservador AR pone el veredicto "¿le gano a
//   la inflación?" arriba de todo; el cripto lo sube como "vs quedarte quieto").

// ── Señales esperadas (todas derivables en el scope de Insights) ────────────
// {
//   nonCashPositions:int, monthsTracked:int, snapshotsCount:int,
//   cryptoSharePct:number, rentaFijaSharePct:number,
//   hasMissingPrices:bool, diagnosisCount:int, hasFeatured:bool,
//   hasVerdicts:bool, hasContributors:bool, hasComposition:bool,
//   hasDrawdown:bool, isFirstVisit:bool,
// }

export const ARCHETYPES = ['empty', 'new', 'crypto', 'conservador_ar', 'completo']

const CRYPTO_MIN_SHARE = 60      // ≥60% en exchanges → cartera cripto
const RENTA_FIJA_MIN_SHARE = 60  // ≥60% en bonos/FCI → conservador AR

export function classifyArchetype(s = {}) {
  if ((s.nonCashPositions || 0) === 0) return 'empty'
  // "new" = sin historial suficiente para performance/series (2 meses/snaps).
  if ((s.monthsTracked || 0) < 2 || (s.snapshotsCount || 0) < 2) return 'new'
  if ((s.cryptoSharePct || 0) >= CRYPTO_MIN_SHARE) return 'crypto'
  if ((s.rentaFijaSharePct || 0) >= RENTA_FIJA_MIN_SHARE) return 'conservador_ar'
  return 'completo'
}

// Cada slot: peso base (menor = más arriba) + visibilidad. La visibilidad
// SUPRIME el slot cuando no hay data — no mostramos placeholders vacíos.
const SLOTS = [
  { id: 'data_integrity', base: 5,   visible: (s) => !!s.hasMissingPrices },
  { id: 'delta',          base: 10,  visible: (s) => (s.nonCashPositions || 0) > 0 && !s.isFirstVisit },
  { id: 'ai_reading',     base: 15,  visible: () => true },
  { id: 'featured',       base: 20,  visible: (s) => !!s.hasFeatured },
  { id: 'kpi',            base: 30,  visible: (s) => (s.nonCashPositions || 0) > 0 },
  // Veredicto: sólo con historial suficiente y verdicts computados (si no,
  // emitiría "le perdés al plazo fijo" sobre días de ruido).
  { id: 'verdict',        base: 40,  visible: (s) => !!s.hasVerdicts && (s.monthsTracked || 0) >= 2 },
  { id: 'diagnosis',      base: 50,  visible: (s) => (s.diagnosisCount || 0) > 0 },
  { id: 'attribution',    base: 60,  visible: (s) => !!s.hasContributors },
  { id: 'composition',    base: 70,  visible: (s) => !!s.hasComposition },
  // Evolución vs benchmark: ESTÁNDAR — se muestra siempre que haya cartera
  // (arranca corta con poca historia; el riel ARS/USD ya existe).
  { id: 'benchmark',      base: 80,  visible: (s) => (s.nonCashPositions || 0) > 0 },
  // Caída y recuperación: necesita ≥2 meses de serie (si no, se suprime).
  { id: 'drawdown',       base: 90,  visible: (s) => !!s.hasDrawdown },
  // Checklist de desbloqueo: sólo para el que recién arranca.
  { id: 'checklist',      base: 100, visible: (s, a) => a === 'new' || a === 'empty' },
]

// Re-priorización por arquetipo: resta al peso base (mueve el slot ARRIBA).
const BOOST = {
  // El conservador AR viene a preguntar "¿le gano a la inflación?" → veredicto
  // arriba de todo (después del delta/lectura).
  conservador_ar: { verdict: 27 },   // 40 - 27 = 13 (por encima de featured)
  // El cripto: "¿tu trading le gana a quedarte quieto?" → veredicto alto.
  crypto:         { verdict: 18 },   // 40 - 18 = 22
  // El nuevo: la composición ES el hallazgo del día (no hay findings de riesgo).
  new:            { composition: 48 }, // 70 - 48 = 22
}

export function buildDiagnosticoLayout(signals = {}) {
  const archetype = classifyArchetype(signals)
  const boost = BOOST[archetype] || {}

  const slots = SLOTS
    .filter((slot) => slot.visible(signals, archetype))
    .map((slot) => ({ id: slot.id, order: slot.base - (boost[slot.id] || 0) }))
    .sort((a, b) => (a.order - b.order) || (slotBase(a.id) - slotBase(b.id)))
    .map((slot) => slot.id)

  return {
    archetype,
    slots,
    isNew: archetype === 'new',
    isEmpty: archetype === 'empty',
  }
}

function slotBase(id) {
  const s = SLOTS.find((x) => x.id === id)
  return s ? s.base : 999
}
