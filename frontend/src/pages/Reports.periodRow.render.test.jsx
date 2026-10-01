import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { PeriodRow } from './Reports.jsx'

// La fila de cada mes en Reportes → Mes → "Ver más meses". Escribía el % con
// PUNTO ("+3.25%") mientras la tarjeta que se abre debajo decía "+3,25%": el
// mismo número de dos formas en la misma pantalla.
function fila(delta_pct, delta_usd = 100) {
  const period = {
    period_key: '2026-08', period_label: 'Agosto 2026', is_relevant: true, is_current: false,
    metrics: { delta_pct, delta_usd, basis_incomparable: false },
  }
  return renderToStaticMarkup(<PeriodRow period={period} expanded={false} onToggle={() => {}} />)
}

describe('Reports — la fila del mes', () => {
  it('coma decimal y signo: dos decimales si es chico, uno si es grande', () => {
    expect(fila(3.25)).toContain('>+3,25%<')
    expect(fila(-12.34, -500)).toContain('>−12,3%<')
    expect(fila(3.25)).not.toMatch(/\d\.\d+%/)
  })
  it('lo que se escribe "0,00%" va neutro, no rojo', () => {
    const h = fila(-0.001, -3)
    expect(h).toContain('>0,00%<')
    expect(h).not.toContain('text-rendi-neg')
  })
})
