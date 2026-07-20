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
    { label: 'Diagnóstico completo + 3 detectores de comportamiento', sub: 'Personalizalo 2×/sem con “No me interesa”; métricas de riesgo bloqueadas (con Plus)' },
    { label: 'Coach IA con 12 preguntas guiadas (taster)' },
    { label: 'Reportes: vista previa del último mes' },
  ],
  // Free no tiene "diff" — es el baseline.
  diff: null,
  quotas: [
    { label: 'Análisis IA / sem', value: '6' },
    { label: 'Chat Coach IA / sem', value: '3' },
    { label: 'Brokers', value: '1' },
  ],
}

export const PLUS_FEATURES = {
  essentials: [
    { label: 'Todo lo del Free' },
    { label: 'Personalizá el diagnóstico sin límite', sub: '“No me interesa” ilimitado (Free: 2/semana)' },
    { label: '6 detectores de comportamiento visibles (de 12 disponibles)' },
    { label: 'Métricas de riesgo desbloqueadas', sub: 'Sharpe, Sortino, beta, alfa, Information Ratio, Calmar, volatilidad y CAGR (en Free se ven bloqueadas)' },
    { label: 'Distribución por activo desbloqueada' },
    { label: 'Reportes históricos completos (todos los meses)' },
    { label: 'Export CSV consolidado para tu contador', sub: 'Compras, ventas, depósitos, retiros y dividendos' },
    { label: '3× más Chat Coach IA que Free', sub: '9 consultas/semana vs 3 en Free' },
  ],
  diff: {
    title: 'Vs Free',
    items: [
      'Hasta 3 brokers (3× más)',
      '3× más Chat Coach IA (9 vs 3 /sem)',
      'Personalizá el diagnóstico sin límite (Free: 2/sem)',
      'Métricas de riesgo desbloqueadas (Sharpe, Sortino, alfa, Calmar…)',
      '6 detectores de comportamiento (2× más)',
      'Reportes históricos + Export CSV',
    ],
  },
  quotas: [
    { label: 'Análisis IA / sem', value: '6', note: 'igual que Free' },
    { label: 'Chat Coach IA / sem', value: '9', note: '3× Free' },
    { label: 'Brokers', value: '3' },
  ],
}

export const PRO_FEATURES = {
  essentials: [
    { label: 'Todo lo del Plus' },
    { label: '60 análisis IA / semana', sub: '10× más que Free y Plus' },
    { label: 'Chat libre con el Coach IA', sub: '40 consultas/sem · texto libre, sin restricción de preguntas' },
    { label: 'Respuestas con causalidad y comparaciones', sub: 'Modo research-note: no solo describe, infiere por qué' },
    { label: 'Follow-ups: profundizá cualquier análisis con preguntas libres' },
    { label: 'Memoria persistente del Coach', sub: 'Los hechos que le aclarás se respetan entre sesiones' },
    { label: 'Brokers ilimitados' },
    { label: '12 detectores de comportamiento completos' },
  ],
  diff: {
    title: 'Vs Plus',
    items: [
      '10× más análisis IA (60/sem vs 6/sem)',
      'Chat libre del Coach (vs 12 preguntas guiadas)',
      'IA con causalidad y memoria persistente',
      'Comportamiento completo (12 vs 6) + brokers ilimitados',
    ],
  },
  quotas: [
    { label: 'Análisis IA / sem', value: '60' },
    { label: 'Chat Coach IA / sem', value: '40' },
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
