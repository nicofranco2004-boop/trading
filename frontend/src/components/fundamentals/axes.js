// Dos ejes de "Calidad de cartera": el NEGOCIO (calidad de la empresa) y el PRECIO
// (qué pagás hoy). Derivados de las category scores del contrato
// /api/fundamentals/{ticker}. Deliberadamente NO los colapsamos en un único score
// 0-100 — eso esconde que una empresa puede ser sólida y estar cara. Compartido
// entre la lista holding-first (CarteraList) y el detalle (AnalyzeView) para que
// digan exactamente lo mismo.

// El negocio = promedio de rentabilidad, crecimiento y solidez (SIN valuación).
export function businessQuality(categories) {
  const keys = ['profitability', 'growth', 'health']
  const scores = (categories || [])
    .filter(c => keys.includes(c.key) && c.score != null)
    .map(c => c.score)
  if (!scores.length) return { label: 'Sin datos', tone: 'muted', score: null, sub: '' }
  const avg = Math.round(scores.reduce((a, b) => a + b, 0) / scores.length)
  if (avg >= 70) return { label: 'Sólido', tone: 'pos', score: avg, sub: 'Rentable, sólido y/o creciendo.' }
  if (avg >= 50) return { label: 'Mixto', tone: 'warn', score: avg, sub: 'Algunas luces y algunas sombras.' }
  return { label: 'Flojo', tone: 'neg', score: avg, sub: 'Los números del negocio flojean.' }
}

// El precio = la categoría valuación (score alto = barata para lo que genera).
export function priceRead(categories) {
  const val = (categories || []).find(c => c.key === 'valuation')
  if (!val || val.score == null) return { label: 'Sin datos', tone: 'muted', score: null, sub: '' }
  const s = val.score
  if (s >= 65) return { label: 'Atractivo', tone: 'pos', score: s, sub: 'Cotiza barata para lo que genera.' }
  if (s >= 45) return { label: 'En precio', tone: 'warn', score: s, sub: 'Ni cara ni barata hoy.' }
  return { label: 'Caro', tone: 'neg', score: s, sub: 'Estás pagando caro lo que genera.' }
}

export const AXIS_TEXT = { pos: 'text-rendi-pos', neg: 'text-rendi-neg', warn: 'text-rendi-warn', muted: 'text-ink-3' }
export const AXIS_BAR = { pos: 'bg-rendi-pos', neg: 'bg-rendi-neg', warn: 'bg-rendi-warn', muted: 'bg-ink-3' }
export const AXIS_PILL = { pos: 'signal', neg: 'red', warn: 'warn', muted: 'off' }
