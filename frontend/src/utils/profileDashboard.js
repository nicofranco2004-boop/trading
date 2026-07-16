// profileDashboard — motor de relevancia del Tablero del perfil de inversor.
import { computeAllocationBuckets } from './profileAllocations'
// ═══════════════════════════════════════════════════════════════════════════
// La plantilla es FIJA; el relleno es POR USUARIO: qué módulos aparecen, en
// qué orden y cuáles quedan bloqueados sale de un score determinístico (REL)
// computado sobre los cruces que YA calcula profileMatch.js — acá NO se
// inventa ningún número y la IA no decide el layout (misma filosofía que el
// featured-by-severity que este motor generaliza).
//
//   buildProfileDashboard({ cards, positions }) →
//     {
//       modules: [{ id, rel, avail, lock, wide }],  // ordenados por rel desc
//       radar:   { axes: [{ label, declared, actual }] } | null,
//       topHoldings: [{ name, pct }],               // top 5 para el donut
//       availCount,
//     }
//
// REL = base (importancia intrínseca del módulo) + boost (severidad del
// mismatch, misma semántica que severityScore de Insights) + lockBoost
// (un módulo bloqueado por test incompleto rankea alto a propósito: completar
// el test es lo que más valor desbloquea — patrón del mockup).
// Empates se resuelven por orden fijo de módulo → el layout es estable entre
// visitas mientras no cambie la data.

// ── Config por módulo ────────────────────────────────────────────────────────

const MODULE_ORDER = [
  'concentration', 'return_exp', 'horizon', 'allocation', 'radar',
  'liquidity', 'style', 'objective', 'drawdown',
]

const BASE_REL = {
  concentration: 45,
  return_exp: 40,
  horizon: 40,
  allocation: 38,
  radar: 36,
  liquidity: 34,
  style: 32,
  objective: 30,
  drawdown: 28,
}

const WIDE = new Set(['radar', 'allocation'])

// Bloqueado por test incompleto → rankea más alto: es el desbloqueo más
// barato y de más valor para el usuario.
const LOCK_BOOST_NO_PROFILE = 22

// Mensajes de desbloqueo por módulo × status. El default cubre lo que falte.
const LOCK_MESSAGES = {
  radar: {
    no_profile: 'Respondé más del test para armar tu radar.',
    no_portfolio: 'Cargá posiciones para comparar tu perfil con la cartera.',
    no_data: 'Respondé más del test para armar tu radar.',
  },
  allocation: {
    no_profile: 'Respondé el test para conocer tu asignación sugerida.',
    no_portfolio: 'Cargá posiciones para ver tu asignación real.',
  },
  concentration: {
    no_profile: 'Respondé el test para comparar tu concentración con tu perfil.',
    no_portfolio: 'Cargá posiciones para medir tu concentración.',
  },
  return_exp: {
    no_profile: 'Respondé qué esperás que haga tu plata en el test.',
    no_data: 'Todavía no hay historial suficiente para medir tu retorno real.',
  },
  style: {
    no_profile: 'Respondé tu estilo de inversión en el test.',
    no_data: 'Todavía no hay suficiente actividad para medir tu estilo.',
  },
  liquidity: {
    no_profile: 'Respondé si necesitás la plata pronto.',
    no_portfolio: 'Cargá posiciones para medir tu colchón de liquidez.',
  },
  horizon: {
    no_profile: 'Respondé tu horizonte en el test.',
    no_portfolio: 'Cargá posiciones para cruzar tu horizonte con la cartera.',
  },
  objective: {
    no_profile: 'Respondé tu objetivo en el test.',
    no_portfolio: 'Cargá posiciones para cruzar tu objetivo con la cartera.',
  },
  drawdown: {
    no_profile: 'Respondé cómo reaccionás a una caída en el test.',
    no_data: 'Necesitás más historial para medir tu caída real.',
    no_portfolio: 'Necesitás más historial para medir tu caída real.',
  },
}

const DEFAULT_LOCKS = {
  no_profile: 'Completá el test para desbloquear este cruce.',
  no_portfolio: 'Cargá posiciones para desbloquear este cruce.',
  no_data: 'Todavía no hay data suficiente para este cruce.',
}

// ── Boost por severidad (misma semántica que severityScore de Insights) ─────

function severityBoost(id, card) {
  if (!card || card.status !== 'ready') return 0
  const c = card.comparison
  switch (id) {
    case 'liquidity':
      if (c === 'mismatch_severe') return 55
      if (c === 'mismatch_risky') return 35
      return 0
    case 'concentration':
      if (c === 'above') return 25 + Math.min(15, (card.actual?.top3Pct || 0) / 5)
      if (c === 'below') return 3
      return 0
    case 'drawdown':
      if (c === 'above') return 35
      if (c === 'below') return 5
      return 0
    case 'horizon':
      // Para horizonte LARGO, riskPct = cash+renta fija (drag, no timing) y el
      // texto del módulo no cubre ese caso → sin boost acá; ese desvío lo
      // captura allocation (driftPct alto). Evita una ★ que diga "Coherente".
      if (card.declared?.horizon === 'long') return 0
      return Math.min(35, (card.actual?.riskPct || 0) * 0.35)
    case 'objective':
      return Math.min(30, (card.actual?.misalignedPct || 0) * 0.35)
    case 'return_exp':
      if (c === 'below') return 30
      if (c === 'above') return 8
      return 0
    case 'allocation':
      return Math.min(30, (card.comparison?.driftPct || 0) * 0.35)
    case 'style':
      return c && c !== 'aligned' ? 25 : 0
    default:
      return 0
  }
}

// ── Radar: 5 ejes declarado-vs-real en 0-100 ────────────────────────────────

const RISK_BY_CATEGORY = { conservador: 25, moderado: 55, agresivo: 85 }
const HORIZON_POS = { short: 25, medium: 55, long: 85 }
export const STYLE_POS = { passive: 20, mixed: 50, active: 85 }
// "Liquidez" en el radar = cuánta necesidad de plata disponible declaró.
const LIQ_POS = { yes: 85, partial: 55, no: 25 }

// trades/mes → posición 0-100 usando las mismas bandas que STYLE_BANDS
// (pasivo 0-2, mixto 3-8, activo 9+), lineal por tramos.
export function tradesToActivityPos(tpm) {
  if (tpm == null || !Number.isFinite(tpm) || tpm < 0) return null
  if (tpm <= 2) return Math.round(8 + tpm * 12.5)            // 0→8, 2→33
  if (tpm <= 8) return Math.round(33 + (tpm - 2) * 5.5)      // 2→33, 8→66
  return Math.min(95, Math.round(66 + (tpm - 8) * 4.8))      // 8→66, cap 95
}

// Buckets reales de la cartera, con FALLBACK a computarlos directo de las
// positions. Sin el fallback, un test a medias (horizon respondido pero
// drawdown/liquidity no) deja a horizon 'ready' sin fuente de buckets → el
// módulo se caía en silencio y la ★ desaparecía (hallazgo H1 del review).
function resolveBuckets(cards, positions) {
  const fromCards = cards.liquidity?.actual?.buckets || cards.allocation?.actual?.buckets
  if (fromCards) return fromCards
  const computed = computeAllocationBuckets(positions || [])
  if (!computed.totalUsd) return null
  return {
    cash: Math.round(computed.cash),
    fixed_income: Math.round(computed.fixed_income),
    equity: Math.round(computed.equity),
    alternative: Math.round(computed.alternative),
  }
}

function buildRadar(cards, buckets) {
  const { allocation, horizon, concentration, style, liquidity } = cards
  const category = allocation?.declared?.category || null

  const axes = []

  // Riesgo: apetito declarado (categoría) vs riesgo real ponderado por bucket.
  const decRisk = category ? RISK_BY_CATEGORY[category] : null
  const actRisk = buckets
    ? Math.min(100, Math.round(
        (buckets.alternative || 0) + (buckets.equity || 0) * 0.75 + (buckets.fixed_income || 0) * 0.15
      ))
    : null
  if (decRisk != null && actRisk != null) axes.push({ label: 'Riesgo', declared: decRisk, actual: actRisk })

  // Horizonte: plazo declarado vs % en activos de plazo largo.
  const decHor = HORIZON_POS[horizon?.declared?.horizon] ?? null
  const actHor = buckets ? Math.min(100, (buckets.equity || 0) + (buckets.alternative || 0)) : null
  if (decHor != null && actHor != null) axes.push({ label: 'Horizonte', declared: decHor, actual: actHor })

  // Diversificación: 100 - concentración (típica del perfil vs top3 real).
  const tr = concentration?.declared?.typicalRange
  const decDiv = tr ? Math.round(100 - (tr.min + tr.max) / 2) : null
  const actDiv = concentration?.actual?.top3Pct != null
    ? Math.max(0, 100 - concentration.actual.top3Pct)
    : null
  if (decDiv != null && actDiv != null) axes.push({ label: 'Diversif.', declared: decDiv, actual: actDiv })

  // Actividad: estilo declarado vs trades/mes reales.
  const decAct = STYLE_POS[style?.declared?.style] ?? null
  const actAct = style?.actual ? tradesToActivityPos(style.actual.tradesPerMonth) : null
  if (decAct != null && actAct != null) axes.push({ label: 'Actividad', declared: decAct, actual: actAct })

  // Liquidez: necesidad declarada vs colchón real (safePct).
  const decLiq = LIQ_POS[liquidity?.declared?.liquidity] ?? null
  const actLiq = liquidity?.actual?.safePct ?? null
  if (decLiq != null && actLiq != null) axes.push({ label: 'Liquidez', declared: decLiq, actual: actLiq })

  return axes
}

// ── Top holdings para el donut (mismo criterio que computeConcentration) ────

export function buildTopHoldings(positions = [], maxItems = 5) {
  const byAsset = {}
  let total = 0
  for (const p of positions) {
    if (!p || p.is_cash) continue
    const v = p.value_usd
    if (v == null || v <= 0) continue
    const key = String(p.asset || '').toUpperCase().trim()
    if (!key) continue
    byAsset[key] = (byAsset[key] || 0) + v
    total += v
  }
  if (total <= 0) return []
  return Object.entries(byAsset)
    .sort((a, b) => b[1] - a[1])
    .slice(0, maxItems)
    .map(([name, v]) => ({ name, pct: Math.round((v / total) * 100) }))
}

// ── Motor principal ─────────────────────────────────────────────────────────

function lockMessage(id, status) {
  return LOCK_MESSAGES[id]?.[status] || DEFAULT_LOCKS[status] || DEFAULT_LOCKS.no_data
}

export function buildProfileDashboard({ cards = {}, positions = [] } = {}) {
  const buckets = resolveBuckets(cards, positions)
  const radarAxes = buildRadar(cards, buckets)
  const topHoldings = buildTopHoldings(positions)

  // Cuántos cruces "de cartas" están en mismatch — alimenta el boost del radar
  // (el radar importa más cuanto más desalineado está el conjunto).
  const mismatches = ['allocation', 'style', 'liquidity', 'concentration', 'drawdown']
    .filter((id) => {
      const card = cards[id]
      if (!card || card.status !== 'ready') return false
      if (id === 'allocation') return (card.comparison?.driftPct || 0) > 15
      const c = card.comparison
      // 'below' en drawdown/concentración es estado BUENO (menos riesgo del
      // tolerado) — no cuenta como desalineación.
      return c && c !== 'aligned' && c !== 'within' && c !== 'in_line' && c !== 'below'
    }).length

  const modules = MODULE_ORDER.map((id) => {
    let rel = BASE_REL[id]
    let avail
    let lock = null

    if (id === 'radar') {
      // El radar necesita ≥3 ejes con ambos lados para dibujarse.
      avail = radarAxes.length >= 3
      if (avail) {
        rel += mismatches >= 2 ? 10 : 0
      } else {
        // Sin ejes suficientes casi siempre es test incompleto.
        lock = lockMessage('radar', 'no_profile')
        rel += LOCK_BOOST_NO_PROFILE
      }
    } else {
      const card = cards[id]
      const status = card?.status || 'no_data'
      avail = status === 'ready'
      if (avail) {
        rel += severityBoost(id, card)
      } else {
        lock = lockMessage(id, status)
        if (status === 'no_profile') rel += LOCK_BOOST_NO_PROFILE
      }
    }

    return { id, rel: Math.round(Math.min(100, rel)), avail, lock, wide: WIDE.has(id) }
  })

  // Orden: rel desc; empate → orden fijo de módulo (layout estable).
  modules.sort((a, b) => (b.rel - a.rel) || (MODULE_ORDER.indexOf(a.id) - MODULE_ORDER.indexOf(b.id)))

  return {
    modules,
    radar: radarAxes.length >= 3 ? { axes: radarAxes } : null,
    topHoldings,
    // Buckets resueltos (cards → fallback positions) — el módulo Horizonte los
    // consume de acá para que avail⇔renderizable sea un invariante real.
    buckets,
    availCount: modules.filter((m) => m.avail).length,
  }
}
