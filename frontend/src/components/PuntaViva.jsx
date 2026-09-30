// PuntaViva — el punto final de un gráfico de evolución cuando ESE punto es el
// valor de ahora (no una foto guardada): un punto con un anillo que se abre y
// se apaga, como el "en vivo" de las secciones de mercado. Lo decide quien lo
// usa (Dashboard: sólo con los precios cargados y la punta fechada hoy).
// Con "reducir movimiento" queda el punto quieto (index.css, `.anillo-vivo`).

// ¿El último punto de la serie es el valor de AHORA? Sí sólo con los precios
// cargados (sin ellos el valor vivo es el costo y no se agrega) y con la punta
// fechada hoy: buildPortfolioValueSeries (utils/evolution.js) reemplaza el
// último punto por el vivo con la fecha de hoy. Una foto guardada no late.
export function puntaEsDeAhora(serie, preciosCargados, hoy) {
  if (!preciosCargados || !Array.isArray(serie) || serie.length === 0) return false
  return serie[serie.length - 1]?.date === hoy
}

export default function PuntaViva({ cx, cy, color }) {
  if (cx == null || cy == null) return null
  return (
    <g aria-hidden="true">
      <circle cx={cx} cy={cy} r={4} fill={color} className="anillo-vivo" />
      <circle cx={cx} cy={cy} r={4} fill={color} stroke="rgb(var(--bg-1))" strokeWidth={2} />
    </g>
  )
}
