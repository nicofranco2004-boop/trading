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

const TONES = new Set(['pos', 'warn', 'neg', 'neutral'])

/** parseStructured(text) → { prose, meta|null }. Nunca lanza. */
export function parseStructured(text) {
  if (!text) return { prose: text || '', meta: null }
  const i = text.indexOf(RENDI_DELIM)
  if (i === -1) return { prose: trimPartialDelim(text), meta: null }
  const prose = text.slice(0, i).trimEnd()
  const tail = text.slice(i + RENDI_DELIM.length)
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

// Valida y recorta el shape — el modelo puede alucinar claves/formatos.
function sanitizeMeta(m) {
  if (!m || typeof m !== 'object') return null
  const str = (v, max) => (typeof v === 'string' && v.trim() ? v.trim().slice(0, max) : null)
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
  const verdict = str(m.verdict, 30)
  const headline = str(m.headline, 140)
  // Sin nada renderizable → tratamos como texto plano.
  if (!verdict && !headline && stats.length === 0 && followups.length === 0) return null
  return { verdict, tone, headline, stats, followups, sources }
}
