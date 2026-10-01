import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import InsightEvidence from './InsightEvidence.jsx'

// La evidencia va abajo del texto del insight, que lo escribe el SERVIDOR
// (reporting/detectors.py: `fmt_num(delta_pct, 1, signed=True)`). Los dos
// tienen que decir la misma cifra. Python escribe fmt_num(19.95, 1) → "19,9"
// (medido 2026-10-01); con el redondeo de toLocaleString la pantalla decía
// "+20,0%" justo abajo de "Tu portfolio: +19,9%".
function html(insight) {
  return renderToStaticMarkup(<InsightEvidence insight={insight} />)
}
const texto = (h) => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()

describe('InsightEvidence — la misma cifra que el texto del servidor', () => {
  it('cartera y S&P con el redondeo del backend', () => {
    const t = texto(html({ code: 'BEAT_BENCHMARK', evidence: { type: 'metric', portfolio: 19.95, sp500: 2.15 } }))
    expect(t).toContain('Cartera +19,9%')
    expect(t).toContain('S&amp;P 500 +2,1%')
  })
  it('una cartera que se escribe "0,0%" no va en rojo', () => {
    const h = html({ code: 'UNDERPERFORM_BENCHMARK', evidence: { type: 'metric', portfolio: -0.04, sp500: 3.2 } })
    const celda = h.slice(h.indexOf('Cartera'), h.indexOf('S&amp;P'))
    expect(celda).toContain('>0,0%<')
    expect(celda).not.toContain('text-rendi-neg')
  })
  it('las porciones sin "+", con coma', () => {
    const t = texto(html({ code: 'LARGE_CASH_DRAG', evidence: { type: 'metric', cash_usd: 5000, cash_pct: 35.2 } }))
    expect(t).toContain('35,2% de la cartera total')
  })
})
