// aiStructured — parser del bloque estructurado de las respuestas de Rendi AI.
// ═══════════════════════════════════════════════════════════════════════════
// El modelo agrega al FINAL de las respuestas de análisis una línea
// `---RENDI---` + UNA línea de JSON minificado con:
//   { verdict, tone, headline, stats:[{l,v,t}], followups:[...], sources:[...] }
// El frontend renderiza eso como veredicto + tarjetas + repreguntas. Si el
// bloque no viene (respuestas conversacionales, registro de operaciones,
// modelos viejos) TODO cae con gracia a texto plano — el parser nunca tira.
//
// Testeable sin React (mismo criterio que stripMarkdown.js).

export const RENDI_DELIM = '---RENDI---'

// Tolerancia a drift del modelo: "--- RENDI ---", "----RENDI----", etc.
// El delimitador canónico sigue siendo RENDI_DELIM (es lo que pide el prompt).
const DELIM_RE = /-{3,}\s*RENDI\s*-{3,}/

const TONES = new Set(['pos', 'warn', 'neg', 'neutral'])

/** parseStructured(text) → { prose, meta|null }. Nunca lanza. */
export function parseStructured(text) {
  if (!text) return { prose: text || '', meta: null }
  let i = text.indexOf(RENDI_DELIM)
  let dlen = RENDI_DELIM.length
  if (i === -1) {
    const m = text.match(DELIM_RE)
    if (!m) return { prose: trimPartialDelim(text), meta: null }
    i = m.index
    dlen = m[0].length
  }
  const prose = text.slice(0, i).trimEnd()
  const tail = text.slice(i + dlen)
  let meta = null
  try {
    // Tolerante: el JSON puede venir con espacios/saltos alrededor, o cortado
    // a mitad durante el streaming (→ parse falla → meta null hasta que cierre).
    const start = tail.indexOf('{')
    const end = tail.lastIndexOf('}')
    if (start !== -1 && end > start) {
      meta = sanitizeMeta(JSON.parse(tail.slice(start, end + 1)))
    }
  } catch {
    meta = null
  }
  return { prose, meta }
}

// Durante el streaming el delimitador puede llegar por la mitad ("---REN"):
// recortamos ese sufijo parcial para que no parpadee como texto visible.
function trimPartialDelim(text) {
  for (let k = RENDI_DELIM.length - 1; k >= 3; k--) {
    if (text.endsWith(RENDI_DELIM.slice(0, k))) return text.slice(0, -k).trimEnd()
  }
  return text
}

// Rutas internas permitidas para el bloque "actions" (deep-links). Cualquier
// otra cosa (URLs externas, javascript:, rutas no listadas) se descarta.
const ACTION_ROUTE_PREFIXES = [
  '/alertas', '/analisis', '/posiciones', '/operaciones', '/fundamentals',
  '/novedades', '/activo/', '/imports', '/ai', '/planes',
]

function safeRoute(to) {
  if (typeof to !== 'string') return null
  const t = to.trim()
  if (!t.startsWith('/') || t.startsWith('//') || t.includes('://')) return null
  return ACTION_ROUTE_PREFIXES.some(p => t === p || t.startsWith(p)) ? t.slice(0, 200) : null
}

// Valida y recorta el shape — el modelo puede alucinar claves/formatos.
function sanitizeMeta(m) {
  if (!m || typeof m !== 'object') return null
  const str = (v, max) => (typeof v === 'string' && v.trim() ? v.trim().slice(0, max) : null)
  const num = (v, lo, hi) => (typeof v === 'number' && isFinite(v) ? Math.max(lo, Math.min(hi, v)) : null)
  const tone = TONES.has(m.tone) ? m.tone : 'neutral'
  const stats = Array.isArray(m.stats)
    ? m.stats
        .filter(s => s && typeof s === 'object' && str(s.l, 40) && str(s.v, 30))
        .slice(0, 3)
        .map(s => ({ l: str(s.l, 40), v: str(s.v, 30), t: TONES.has(s.t) ? s.t : 'neutral' }))
    : []
  const followups = Array.isArray(m.followups)
    ? m.followups.filter(f => typeof f === 'string' && f.trim()).slice(0, 3).map(f => f.trim().slice(0, 120))
    : []
  const sources = Array.isArray(m.sources)
    ? m.sources.filter(s => typeof s === 'string' && s.trim()).slice(0, 3).map(s => s.trim().slice(0, 50))
    : []

  // Bloques visuales (catálogo V1). Tipo desconocido → se ignora (forward-compat).
  // `title` opcional (≤40) — la card lo muestra como encabezado; sin él, el
  // renderer cae al genérico del tipo ("Comparación", "Composición", …).
  const blocks = []
  if (Array.isArray(m.blocks)) {
    for (const b of m.blocks.slice(0, 4)) {
      if (!b || typeof b !== 'object') continue
      const title = str(b.title, 40)
      const withTitle = (obj) => (title ? { ...obj, title } : obj)
      if (b.type === 'compare' && Array.isArray(b.items)) {
        const items = b.items
          .filter(it => it && str(it.l, 30) && str(it.v, 20))
          .slice(0, 4)
          .map(it => ({ l: str(it.l, 30), v: str(it.v, 20), pct: num(it.pct, 0, 100) }))
        if (items.length >= 2) blocks.push(withTitle({ type: 'compare', items }))
      } else if (b.type === 'alloc' && Array.isArray(b.items)) {
        const items = b.items
          .filter(it => it && str(it.l, 24) && num(it.pct, 0, 100) != null)
          .slice(0, 6)
          .map(it => ({ l: str(it.l, 24), pct: num(it.pct, 0, 100) }))
        if (items.length >= 2) blocks.push(withTitle({ type: 'alloc', items }))
      } else if (b.type === 'scenario' && str(b.if, 60) && str(b.then, 60)) {
        blocks.push({ type: 'scenario', if: str(b.if, 60), then: str(b.then, 60), tone: TONES.has(b.tone) ? b.tone : 'neutral' })
      } else if (b.type === 'table' && Array.isArray(b.cols) && Array.isArray(b.rows)) {
        const cols = b.cols.filter(c => typeof c === 'string').slice(0, 4).map(c => c.trim().slice(0, 20))
        const rows = b.rows
          .filter(r => Array.isArray(r))
          .slice(0, 5)
          .map(r => r.slice(0, cols.length).map(c => String(c ?? '').slice(0, 24)))
        if (cols.length >= 2 && rows.length >= 1) blocks.push(withTitle({ type: 'table', cols, rows }))
      } else if (b.type === 'actions' && Array.isArray(b.items)) {
        const items = b.items
          .map(it => (it && str(it.label, 60) && safeRoute(it.to) ? { label: str(it.label, 60), to: safeRoute(it.to) } : null))
          .filter(Boolean)
          .slice(0, 3)
        if (items.length >= 1) blocks.push(withTitle({ type: 'actions', items }))
      }
      if (blocks.length >= 2) break   // máx 2 bloques por respuesta (regla de diseño)
    }
  }

  const verdict = str(m.verdict, 30)
  const headline = str(m.headline, 140)
  // Sin nada renderizable → tratamos como texto plano.
  if (!verdict && !headline && stats.length === 0 && followups.length === 0 && blocks.length === 0) return null
  return { verdict, tone, headline, stats, followups, sources, blocks }
}
