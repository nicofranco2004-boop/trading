// planCatalog — fuente única de las features por plan (Free / Plus / Pro).
// ════════════════════════════════════════════════════════════════════════════
// Extraído de Planes.jsx para poder reusar la MISMA data en dos lugares sin
// duplicarla ni bundlear toda la página de Planes:
//   • /planes (Planes.jsx)                → comparativa pública + pricing + CTA
//   • /config?tab=planes (Config.jsx)     → cuadros de features junto al plan actual
// Planes.jsx re-exporta estas constantes para mantener su API previa.
//
// Cada feature es { label, sub? } — sub es la nota chica abajo (opcional).
// Template de 3 secciones:
//   1. essentials: lo CORE del plan (4-5 items)
//   2. diff: el AHA del upgrade vs el plan anterior (Plus vs Free, Pro vs Plus)
//   3. quotas: grid mini de números (análisis/sem, chat/sem, brokers)
// Sin emojis (decisión de producto: ASCII + tipografía + color, no glyph).

export const FREE_FEATURES = {
  essentials: [
    { label: 'Dashboard completo con 4 KPIs + curva de evolución' },
    { label: 'Posiciones, Operaciones, Wrapped anual y Objetivos' },
    { label: 'Insights con TWR, benchmarks (S&P, inflación AR, dólar) y drawdown' },
    { label: 'Diagnóstico completo + 3 detectores de comportamiento', sub: 'Con CAGR y volatilidad; personalizalo 2×/sem con “No me interesa” (métricas ajustadas por riesgo con Plus)' },
    { label: 'Rendi AI con 12 preguntas guiadas (taster)' },
    { label: 'Reportes: vista previa del último mes' },
  ],
  // Free no tiene "diff" — es el baseline.
  diff: null,
  quotas: [
    { label: 'Análisis IA / sem', value: '1' },
    { label: 'Chat Rendi AI / sem', value: '1' },
    { label: 'Brokers', value: '1' },
  ],
}

// Plus = **Rendi entero, sin el analista** (2026-10-15). Antes se definía por
// recortes —6 de 12 detectores, 6 puntos de diagnóstico, 25 alertas— y nadie
// podía nombrar lo que compraba. Ahora las métricas están COMPLETAS y lo que
// lo separa del Pro son dos cosas que se dicen en una frase: la IA y los
// brokers. El cupo de IA bajó a 2/sem justamente para que quede claro que el
// Plus no es el plan de la IA (Free tiene 1).
export const PLUS_FEATURES = {
  essentials: [
    { label: 'Todo lo del Free, sin recortes' },
    { label: 'Diagnóstico completo', sub: 'Todos los puntos, y personalizalo sin límite (Free: 2/semana)' },
    { label: 'Los 12 detectores de comportamiento' },
    { label: 'Métricas de riesgo desbloqueadas', sub: 'Sharpe, Sortino, beta, alfa, Information Ratio y Calmar (en Free se ven bloqueadas; CAGR y volatilidad ya vienen gratis)' },
    { label: 'Distribución por activo desbloqueada' },
    { label: 'Reportes históricos completos (todos los meses)' },
    { label: 'Alertas sin tope' },
    { label: 'Export CSV consolidado para tu contador', sub: 'Compras, ventas, depósitos, retiros y dividendos' },
    { label: 'Hasta 3 brokers consolidados' },
  ],
  diff: {
    title: 'Vs Free',
    items: [
      'Hasta 3 brokers (3× más)',
      'Diagnóstico completo y los 12 detectores de comportamiento',
      'Métricas de riesgo desbloqueadas (Sharpe, Sortino, alfa, Calmar…)',
      'Alertas sin tope (Free: 3, y sólo de precio objetivo)',
      'Reportes históricos + Export CSV',
      '9× más Chat Rendi AI (9 vs 1 /sem)',
    ],
  },
  quotas: [
    { label: 'Análisis IA / sem', value: '2' },
    { label: 'Chat Rendi AI / sem', value: '9', note: '9× Free' },
    { label: 'Brokers', value: '3' },
  ],
}

export const PRO_FEATURES = {
  essentials: [
    { label: 'Todo lo del Plus' },
    { label: '60 análisis IA / semana', sub: '60× más que Free · 30× que Plus' },
    { label: 'Chat libre con Rendi AI', sub: '40 consultas/sem · texto libre, sin restricción de preguntas' },
    { label: 'Respuestas con causalidad y comparaciones', sub: 'Modo research-note: no solo describe, infiere por qué' },
    { label: 'Follow-ups: profundizá cualquier análisis con preguntas libres' },
    { label: 'Memoria persistente del Coach', sub: 'Los hechos que le aclarás se respetan entre sesiones' },
    { label: 'Brokers ilimitados' },
  ],
  // Vs Plus quedó reducido a propósito: desde que el Plus tiene las métricas
  // completas, TODO lo que separa al Pro es la IA — más los brokers.
  diff: {
    title: 'Vs Plus',
    items: [
      '30× más análisis IA (60/sem vs 2/sem)',
      'Chat libre con Rendi AI (vs 12 preguntas guiadas)',
      'IA con causalidad y memoria persistente',
      'Repreguntá sobre cualquier análisis (follow-ups)',
      'Brokers ilimitados (Plus: 3)',
    ],
  },
  quotas: [
    { label: 'Análisis IA / sem', value: '60' },
    { label: 'Chat Rendi AI / sem', value: '40' },
    { label: 'Brokers', value: '∞' },
  ],
  // Roadmap visible — features prometidas que están en construcción.
  // Diferenciadas visualmente del resto (no son CHECKS, son CLOCKS).
  // Decisión de producto: mantenerlas para señalizar dirección, pero NUNCA
  // mezcladas con las features activas.
  roadmap: [
    'AI Hub: exploración libre sobre tu portfolio',
    'Tax helper AFIP: cálculo FIFO + reporte fiscal',
  ],
}
