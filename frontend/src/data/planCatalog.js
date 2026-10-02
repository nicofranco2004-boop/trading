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

// ─── La prueba ───────────────────────────────────────────────────────────────
// Los días viven acá porque la LANDING los necesita y la landing es pública:
// no hay sesión, así que no puede preguntárselos al backend como hace la app
// (`trial.total_days` en /api/plan/features).
//
// ⚠️ Que estos números coincidan con los del backend (`billing/trial.py`) NO
// queda al cuidado de nadie: lo compara `backend/tests/test_promesas_vs_producto.py`.
// Si alguien cambia la prueba de 20 a 14 días y se olvida de la landing, ese
// test se pone rojo. Sin eso, la home seguiría ofreciendo 20 días para siempre.
export const TRIAL_TOTAL_DAYS = 20
export const TRIAL_PRO_DAYS = 10
export const TRIAL_PLUS_DAYS = 10

export const FREE_FEATURES = {
  essentials: [
    { label: 'Dashboard completo con 4 KPIs + curva de evolución' },
    { label: 'Posiciones, Operaciones, Wrapped anual y Objetivos' },
    { label: 'Métricas con TWR, benchmarks (S&P, inflación AR, dólar) y drawdown' },
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

// ⚠️ SIN FREE (decisión de Nico, 2026-09-26): no hay más Free a futuro — quien
// se registra arranca la prueba y después elige Plus o Pro. Las tarjetas que se
// venden no se comparan contra un plan que esa persona nunca tuvo: nada de
// "Todo lo del Free", "Vs Free" ni "N× más". Lo vigila
// `backend/tests/test_promesas_vs_producto.py::LasTarjetasNoSeComparanContraFree`.
// La tarjeta del Free (FREE_FEATURES) sigue: sólo la ven las cuentas viejas.
export const PLUS_FEATURES = {
  essentials: [
    { label: 'Dashboard, cartera, movimientos e insights' },
    { label: 'Personalizá el diagnóstico sin límite', sub: '“No me interesa” ilimitado' },
    { label: '6 detectores de comportamiento visibles (de 12 disponibles)' },
    { label: 'Métricas de riesgo', sub: 'Sharpe, Sortino, beta, alfa, Information Ratio, Calmar, CAGR y volatilidad' },
    { label: 'Reportes históricos completos (todos los meses)' },
    { label: 'Hasta 25 alertas, de precio objetivo y de variación %' },
    { label: 'Export CSV consolidado para tu contador', sub: 'Compras, ventas, depósitos, retiros y dividendos' },
    { label: 'Hasta 3 brokers consolidados' },
  ],
  // El muro de "elegí un plan" muestra las primeras (`LINEAS_POR_TARJETA`).
  diff: {
    title: 'Lo principal',
    items: [
      'Hasta 3 brokers consolidados',
      '6 detectores de comportamiento visibles (de 12 disponibles)',
      'Métricas de riesgo (Sharpe, Sortino, alfa, Calmar…)',
      'Hasta 25 alertas, de precio objetivo y de variación %',
      'Reportes históricos + Export CSV',
      '9 consultas por semana a Rendi AI, con preguntas guiadas',
    ],
  },
  quotas: [
    { label: 'Análisis IA / sem', value: '6' },
    { label: 'Chat Rendi AI / sem', value: '9' },
    { label: 'Brokers', value: '3' },
  ],
}

export const PRO_FEATURES = {
  essentials: [
    { label: 'Todo lo del Plus' },
    { label: '60 análisis IA / semana', sub: '10× más que Plus' },
    { label: 'Chat libre con Rendi AI', sub: '40 consultas/sem · texto libre, sin restricción de preguntas' },
    { label: 'Respuestas con causalidad y comparaciones', sub: 'Modo research-note: no solo describe, infiere por qué' },
    { label: 'Follow-ups: profundizá cualquier análisis con preguntas libres' },
    { label: 'Memoria persistente de Rendi AI', sub: 'Los hechos que le aclarás se respetan entre sesiones' },
    { label: 'Brokers ilimitados' },
    { label: '12 detectores de comportamiento completos' },
  ],
  diff: {
    title: 'Vs Plus',
    items: [
      '10× más análisis IA (60/sem vs 6/sem)',
      'Chat libre con Rendi AI (vs 12 preguntas guiadas)',
      'IA con causalidad y memoria persistente',
      'Comportamiento completo (12 vs 6) + brokers ilimitados',
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
