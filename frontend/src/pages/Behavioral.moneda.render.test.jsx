import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// Los precios de Comportamiento se escriben en SU moneda.
//
// 23/11/2026, cuenta de ejemplo: en «Chase the pump», Galicia (Cocos, en pesos)
// decía «Compraste a US$ 6.240 · hoy US$ 4.557,5». El servidor comparaba bien
// pesos con pesos, pero no decía la moneda, y la pantalla le ponía «US$» a todo
// precio. Ahora cada precio viaja con `moneda` (MONEDA_DE_LOS_PRECIOS en
// backend/behavioral.py) y la pantalla la usa. Las tarjetas se dibujan con la
// respuesta tal como la manda el servidor (las mismas filas que
// tests/test_behavioral.py::MonedaDeLosPreciosTest).
import { ModalEvidence } from './Behavioral'
import { handleDemoRequest } from '../utils/demo.js'

const texto = (card) => renderToStaticMarkup(<ModalEvidence card={card} />)
  .replace(/<[^>]+>/g, ' ')
  .replace(/\s+/g, ' ')

describe('Comportamiento — los precios dicen su moneda', () => {
  it('Chase the pump: Galicia en pesos se lee en pesos', () => {
    const t = texto({
      code: 'recency_bias',
      evidence: {
        chase_pct: 30, chase_pumps_invested_usd: 1288, flagged_count: 2,
        flagged_assets: [
          { asset: 'GGAL', buy_price: 6240, current_price: 4557.5, moneda: 'ARS', drawdown_pct: -27, invested_usd: 1288.34 },
          { asset: 'ETH', buy_price: 2486.46, current_price: 1782.41, moneda: 'USD', drawdown_pct: -28.3, invested_usd: 2673.62 },
        ],
      },
    })
    expect(t).toContain('Compraste a $ 6.240 · hoy $ 4.557,5')
    expect(t).not.toContain('US$ 6.240')
    expect(t).toContain('Compraste a US$ 2.486,46 · hoy US$ 1.782,41')
  })

  it('Promediar a la baja: compras en pesos, en pesos', () => {
    const t = texto({
      code: 'averaging_down',
      evidence: {
        total_instances: 1, avg_drop_pct: 16.67,
        instances: [{ asset: 'GGAL', moneda: 'ARS', first_buy: { date: '2024-03-01', price: 6000 },
          second_buy: { date: '2024-03-10', price: 5000 }, gap_days: 9, price_drop_pct: -16.67 }],
      },
    })
    expect(t).toContain('2024-03-01: $ 6.000 → 2024-03-10: $ 5.000')
    expect(t).not.toContain('US$')
  })

  it('Contrafáctica: precios en dólares y la diferencia también en dólares (no «$»)', () => {
    const t = texto({
      code: 'counterfactual',
      evidence: {
        realized_total_usd: 90, hypothetical_total_usd: 300, delta_total_usd: 210, trades_analyzed: 3,
        top_misses: [{ asset: 'NVDA', exit_price: 120, current_price: 170, moneda: 'USD', delta_usd: 50 }],
      },
    })
    expect(t).toContain('US$ 120 → US$ 170')
    expect(t).toContain('+US$ 50')
  })

  it('sin moneda, el número solo: la pantalla nunca adivina «US$»', () => {
    const t = texto({
      code: 'recency_bias',
      evidence: { flagged_count: 1, flagged_assets: [{ asset: 'GGAL', buy_price: 6240, current_price: 4557.5 }] },
    })
    expect(t).toContain('Compraste a 6.240 · hoy 4.557,5')
  })

  it('el demo también manda la moneda de cada precio', () => {
    const b = handleDemoRequest('GET', '/behavioral/insights')
    let vistos = 0
    for (const c of b.cards) {
      for (const v of Object.values(c.evidence || {})) {
        if (!Array.isArray(v)) continue
        for (const fila of v) {
          if (!fila || typeof fila !== 'object') continue
          if (!Object.keys(fila).some(k => k.endsWith('_price') || k === 'first_buy')) continue
          vistos += 1
          expect(['ARS', 'USD'], `${c.code}: ${JSON.stringify(fila)}`).toContain(fila.moneda)
        }
      }
    }
    expect(vistos).toBeGreaterThan(0)
  })
})
