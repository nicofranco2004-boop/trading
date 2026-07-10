// Red de seguridad client-side para el chat streaming: el path SSE no pasa por
// el _strip_markdown del servidor, así que limpiamos el markdown acá sobre el
// texto acumulado. El modelo está instruido a NO usar markdown — esto casi
// nunca hace nada, pero evita que se cuele un **bold** o un "- " suelto.
// Idempotente: se aplica sobre el buffer completo en cada delta.
export function stripMarkdown(t) {
  if (!t) return t
  // Bold/italic: el contenido NO puede empezar/terminar en espacio (regla
  // markdown real) NI cruzar saltos de línea ([^*\n], line-bound como el `.`
  // del regex original — sin eso, dos * pegados en LÍNEAS distintas formaban
  // un par y colapsaban números cross-line: "100*1.05\n...200*1.02" → "1001.05").
  // Sin el borde sin-espacio, "2 * 3 = 6 * 2" matcheaba "* 3 = 6 *" y
  // colapsaba aritmética — mutilando NÚMEROS en una app de plata (B-14).
  // Limitación conocida (pre-existente): la multiplicación PEGADA en la misma
  // línea ("2*3 = 6*2") sigue siendo indistinguible de énfasis intraword y
  // colapsa; mitigada exigiendo que el * de apertura no venga pegado a dígito.
  let s = t.replace(/(^|[^\d*])\*\*([^\s*](?:[^*\n]*[^\s*])?)\*\*/g, '$1$2')   // bold
  s = s.replace(/(^|[^\d*])\*([^\s*](?:[^*\n]*[^\s*])?)\*/g, '$1$2')           // italic
  s = s.replace(/^\s{0,3}[-*+]\s+/gm, '')     // list markers
  s = s.replace(/^\s{0,3}#{1,6}\s+/gm, '')    // headers
  return s
}
