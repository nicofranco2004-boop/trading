// El RSS del blog: dónde está y cómo se llama. Un solo lugar para los tres que
// lo nombran: scripts/paginasEscritas.mjs (que escribe dist/rss.xml al
// publicar), el índice del blog y cada nota (components/blog/LinkRss.jsx).
//
// Sin imports a propósito: lo lee también Node directo, desde el prerender.
export const RSS_URL = 'https://rendi.finance/rss.xml'
export const RSS_TITULO = 'Blog de Rendi'
