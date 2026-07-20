// /guia/insights-y-reportes — sección 3 del manual

import GuidePage from '../../components/guide/GuidePage'

export default function InsightsYReportes() {
  return (
    <GuidePage
      section="3 de 6"
      title="Insights y reportes"
      intro="Las 5 cards de análisis automático, el timeline histórico de 12 meses, los detectores de comportamiento y cómo exportar el CSV para tu contador."
      prev={{ to: '/guia/cartera-y-operaciones', label: 'Cartera y operaciones' }}
      next={{ to: '/guia/coach-ia', label: 'Coach IA' }}
      metaTitle="Insights y reportes — Guía Rendi"
      metaDescription="Las 5 cards de Insights, timeline histórico, 12 detectores de comportamiento y export CSV consolidado para AFIP en Rendi."
      canonicalPath="/guia/insights-y-reportes"
    >
      <h2>Las 5 cards de Insights</h2>
      <p>
        En <strong>Insights</strong> tenés 5 análisis automáticos de tu cartera:
      </p>

      <h3>1. Distribución por activo</h3>
      <p>
        Allocation real de tu portfolio: % en acciones AR, % en CEDEARs, % en bonos
        AR, % en crypto, % en cash. Comparado con benchmarks típicos por perfil de
        inversor (conservador, moderado, agresivo).
      </p>

      <h3>2. Horizonte declarado vs composición</h3>
      <p>
        Si llenaste el cuestionario, comparamos tu horizonte declarado (corto/medio/largo
        plazo) con la duración real de tus activos. Sirve para detectar incoherencias —
        ej. "decís horizonte 10+ años pero tu cartera está 80% en cash y bonos cortos".
      </p>

      <h3>3. Tolerancia drawdown vs realidad</h3>
      <p>
        Calculamos el drawdown máximo real de tu cartera (pico-a-valle) y lo comparamos
        con el drawdown que dijiste tolerar. Si superás el límite, te alertamos.
      </p>

      <h3>4. Concentración top 3</h3>
      <p>
        Qué % de tu portfolio está en tus 3 activos más grandes. Más de 60% = alta
        concentración (mayor riesgo). Te muestra cuáles son y sugiere si conviene
        rebalancear.
      </p>

      <h3>5. Coherencia objetivo</h3>
      <p>
        Si tenés objetivos cargados (Goals), evalúa si tu asset allocation actual te
        acerca o aleja de cada objetivo.
      </p>

      <p>
        <strong>Free</strong> ve el diagnóstico completo, con las métricas de riesgo
        (Sharpe, Sortino, alfa…) bloqueadas. <strong>Plus y Pro</strong> las desbloquean.
      </p>

      <h2>Reportes históricos</h2>
      <p>
        En <strong>Reportes</strong> ves un timeline cronológico de tu cartera. Vista
        principal: 12 meses con métricas por mes (delta % en USD, P&amp;L realizado,
        depósitos, retiros). Cada mes se puede expandir para ver las semanas adentro.
      </p>
      <p>
        Tabs disponibles arriba: <strong>Día</strong> (últimos 7 días),{' '}
        <strong>Semana</strong> (semana actual), <strong>Mes</strong> (vista default
        12 meses), <strong>Año</strong> (años visibles).
      </p>

      <h2>Detectores de comportamiento</h2>
      <p>
        Cada reporte mensual viene con "insights" auto-generados por reglas heurísticas
        (no IA — son detectores deterministas). Algunos ejemplos:
      </p>
      <ul>
        <li><strong>Streak / Reversal</strong>: rachas de meses ganando o perdiendo.</li>
        <li><strong>Dividend Heavy</strong>: si más del X% del mes vino de dividendos.</li>
        <li><strong>FOMO Buy</strong>: si compraste cerca del techo histórico.</li>
        <li><strong>Loss Aversion</strong>: si vendiste activos ganadores y mantuviste perdedores.</li>
        <li><strong>Anchoring</strong>: si recomprás lo que vendiste mal recientemente.</li>
      </ul>
      <p>
        <strong>Free</strong> ve 3 detectores. <strong>Plus</strong> ve 6.{' '}
        <strong>Pro</strong> ve los 12 disponibles.
      </p>

      <h2>Export CSV consolidado</h2>
      <p>
        Botón <strong>"Exportar mensual"</strong> arriba de Reportes te baja un CSV con
        todas tus operaciones del período, ya consolidadas por broker, con FIFO aplicado
        y P&amp;L en USD. Es lo que necesita tu contador para tu declaración a AFIP/ARCA.
      </p>
      <p>
        El CSV incluye:
      </p>
      <ul>
        <li>Compras: fecha, broker, activo, cantidad, precio, costo total USD.</li>
        <li>Ventas: fecha, broker, activo, cantidad, precio venta, costo base FIFO, P&amp;L realizado USD.</li>
        <li>Dividendos / cupones: fecha, activo, monto USD.</li>
        <li>Depósitos / retiros: fecha, broker, monto USD.</li>
      </ul>
      <p>
        <strong>Free</strong> exporta solo el último mes.{' '}
        <strong>Plus y Pro</strong> exportan todos los meses históricos.
      </p>

      <h2>Wrapped anual</h2>
      <p>
        En diciembre/enero se desbloquea <strong>Wrapped</strong> — un resumen del año
        estilo Spotify Wrapped: mejor mes, peor mes, activo estrella, total operado,
        cantidad de compras vs ventas, etc. Generás una imagen para compartir.
      </p>
    </GuidePage>
  )
}
