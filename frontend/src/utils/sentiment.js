// Sentimiento de una noticia — el único lugar donde viven sus colores.
// ═══════════════════════════════════════════════════════════════════════════
// El backend estampa 'positive' | 'negative' | 'neutral' UNA vez, cuando la
// noticia entra (heurística por léxico, compartida entre todos los usuarios —
// no consume cuota de IA de nadie). Ver _sentiment_news_item en main.py.
//
// Esto vivía dentro de News.jsx y se sacó cuando una segunda superficie
// necesitó pintarlo. Esa segunda superficie después cambió de forma y hoy no
// lo usa, así que por ahora News.jsx es el único consumidor — el archivo queda
// porque el lugar correcto de la tabla es este, no adentro de una página, y
// volver a meterla ahí sólo garantiza sacarla de nuevo la próxima vez.
//
// Clases literales COMPLETAS a propósito: Tailwind purga las clases que arma
// por concatenación (`bg-rendi-${x}` no sobrevive al build).

export const SENTIMENT_META = {
  positive: { label: 'POS', dot: 'bg-rendi-pos', text: 'text-rendi-pos', stripe: 'border-l-rendi-pos' },
  negative: { label: 'NEG', dot: 'bg-rendi-neg', text: 'text-rendi-neg', stripe: 'border-l-rendi-neg' },
  neutral:  { label: 'NEU', dot: 'bg-ink-3',     text: 'text-ink-3',     stripe: 'border-l-line-3' },
}

/** Meta del sentimiento, con fallback a neutral para null/desconocido. */
export function sentimentMeta(s) {
  return SENTIMENT_META[s] || SENTIMENT_META.neutral
}
