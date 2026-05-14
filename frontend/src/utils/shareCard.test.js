// Tests para shareCard.js — solo testean lógica pura (spec builders + helpers).
// El render de Canvas se testea por integración (vitest jsdom no implementa
// canvas 2D al 100%).

import { describe, it, expect } from 'vitest'
import {
  specFromInsight,
  specFromMonth,
  hexToRgba,
  wrapText,
  roundRect,
} from './shareCard'

describe('specFromInsight', () => {
  it('mapea severity alta a tone red + label', () => {
    const spec = specFromInsight({
      code: 'disposition_effect',
      severity: 'high',
      title: 'Vendés ganadoras 3.5× más rápido',
      one_liner: 'Disposition ratio de 3.5',
      value_label: '3.51× ratio',
    })
    expect(spec.kind).toBe('insight')
    expect(spec.eyebrow).toBe('Disposition effect')
    expect(spec.title).toBe('Vendés ganadoras 3.5× más rápido')
    expect(spec.subtitle).toBe('Disposition ratio de 3.5')
    expect(spec.pill.tone).toBe('red')
    expect(spec.pill.label).toBe('Severidad alta')
    expect(spec.stats).toHaveLength(1)
    expect(spec.stats[0]).toEqual({ label: 'Indicador', value: '3.51× ratio' })
  })

  it('positive severity → tone green + "Patrón saludable"', () => {
    const spec = specFromInsight({
      code: 'concentration',
      severity: 'positive',
      title: 'Cartera bien diversificada',
      one_liner: 'Top 5 representa <50%',
    })
    expect(spec.pill.tone).toBe('green')
    expect(spec.pill.label).toBe('Patrón saludable')
  })

  it('medium → amber, low → blue, neutral → gray', () => {
    expect(specFromInsight({ severity: 'medium' }).pill.tone).toBe('amber')
    expect(specFromInsight({ severity: 'low' }).pill.tone).toBe('blue')
    expect(specFromInsight({ severity: 'neutral' }).pill.tone).toBe('gray')
  })

  it('code desconocido cae al code raw como eyebrow', () => {
    const spec = specFromInsight({ code: 'whatever', severity: 'low' })
    expect(spec.eyebrow).toBe('whatever')
  })

  it('card sin value_label no agrega stats', () => {
    const spec = specFromInsight({
      code: 'overtrade',
      severity: 'high',
      title: 'Operás demasiado',
    })
    expect(spec.stats).toHaveLength(0)
  })

  it('mapea TODOS los códigos del Behavioral.jsx', () => {
    const codes = [
      'disposition_effect','overtrade','loss_aversion','averaging_down',
      'concentration','inflation_loss','counterfactual',
      'winrate_payoff','home_bias','cash_drag',
      'recency_bias','sector_concentration',
    ]
    for (const code of codes) {
      const spec = specFromInsight({ code, severity: 'low' })
      // El eyebrow no debe ser el code raw (debe haberlo mapeado a label)
      expect(spec.eyebrow).not.toBe(code)
      expect(spec.eyebrow.length).toBeGreaterThan(0)
    }
  })

  it('respeta el now opcional para la fecha', () => {
    const now = new Date('2026-05-14T00:00:00')
    const spec = specFromInsight({ code: 'overtrade', severity: 'low' }, now)
    // mayo 2026, formato es-AR
    expect(spec.date.toLowerCase()).toContain('mayo')
    expect(spec.date).toContain('2026')
  })
})

describe('specFromMonth', () => {
  it('mes positivo → tone green, sign +', () => {
    const spec = specFromMonth({
      pnl_pct: 0.0512,
      month_label: 'Abril 2026',
      capital_inicio: 10000,
      capital_final: 10512,
    })
    expect(spec.kind).toBe('performance')
    expect(spec.title).toBe('+5.12%')
    expect(spec.pill.tone).toBe('green')
    expect(spec.pill.label).toBe('Mes positivo')
    expect(spec.eyebrow).toBe('Mi Abril 2026 en Rendi')
  })

  it('mes negativo → tone red, sign minus unicode', () => {
    const spec = specFromMonth({
      pnl_pct: -0.082,
      month_label: 'Marzo 2026',
    })
    expect(spec.title).toBe('−8.20%')
    expect(spec.pill.tone).toBe('red')
    expect(spec.pill.label).toBe('Mes negativo')
  })

  it('incluye stats de capital y aportes netos cuando hay datos', () => {
    const spec = specFromMonth({
      pnl_pct: 0.03,
      month_label: 'Mayo',
      capital_inicio: 5000,
      capital_final: 5400,
      net: 250,
      best_trade: 'NVDA +18%',
    })
    expect(spec.stats.length).toBeGreaterThanOrEqual(3)
    expect(spec.stats.find(s => s.label === 'Capital inicial')).toBeTruthy()
    expect(spec.stats.find(s => s.label === 'Capital final')).toBeTruthy()
    expect(spec.stats.find(s => s.label === 'Aportes netos')).toBeTruthy()
    expect(spec.stats.find(s => s.label === 'Mejor trade')?.value).toBe('NVDA +18%')
  })

  it('aporte negativo → label "Retiros netos"', () => {
    const spec = specFromMonth({
      pnl_pct: 0.01,
      month_label: 'Mayo',
      net: -500,
    })
    const flowStat = spec.stats.find(s => s.label === 'Retiros netos')
    expect(flowStat?.value).toBe('−$500')
  })

  it('aporte cero no genera stat de flujo', () => {
    const spec = specFromMonth({
      pnl_pct: 0.01,
      month_label: 'Mayo',
      net: 0,
    })
    expect(spec.stats.find(s => /aportes|retiros/i.test(s.label))).toBeFalsy()
  })

  it('capital NaN/null se ignora', () => {
    const spec = specFromMonth({
      pnl_pct: 0.01,
      capital_inicio: NaN,
      capital_final: null,
    })
    expect(spec.stats.find(s => s.label === 'Capital inicial')).toBeFalsy()
    expect(spec.stats.find(s => s.label === 'Capital final')).toBeFalsy()
  })

  it('pnl_pct cero → +0.00% (mes positivo en el borde)', () => {
    const spec = specFromMonth({ pnl_pct: 0 })
    expect(spec.title).toBe('+0.00%')
    expect(spec.pill.tone).toBe('green')
  })

  it('sin month_label cae al fallback', () => {
    const spec = specFromMonth({ pnl_pct: 0.01 })
    expect(spec.eyebrow).toBe('Mi mes en Rendi')
  })
})

describe('hexToRgba', () => {
  it('parsea hex de 6 dígitos correctamente', () => {
    expect(hexToRgba('#FF5360', 0.3)).toBe('rgba(255,83,96,0.3)')
    expect(hexToRgba('#21D07A', 0.12)).toBe('rgba(33,208,122,0.12)')
    expect(hexToRgba('21D07A', 1)).toBe('rgba(33,208,122,1)')
  })

  it('hex inválido cae a negro transparente', () => {
    expect(hexToRgba('xx', 0.5)).toBe('rgba(0,0,0,0.5)')
    expect(hexToRgba('#abc', 0.5)).toBe('rgba(0,0,0,0.5)')
  })
})

describe('wrapText / roundRect (no crash con stubs)', () => {
  // Mock simple de canvas context para verificar que las funciones no exploten
  function makeStubCtx() {
    const calls = { fillText: [], measureText: [] }
    return {
      measureText: (s) => { calls.measureText.push(s); return { width: s.length * 10 } },
      fillText: (s, x, y) => { calls.fillText.push({ s, x, y }) },
      beginPath: () => {},
      moveTo: () => {},
      arcTo: () => {},
      closePath: () => {},
      _calls: calls,
    }
  }

  it('wrapText con texto vacío devuelve y sin dibujar', () => {
    const ctx = makeStubCtx()
    const y = wrapText(ctx, '', 0, 100, 500, 30)
    expect(y).toBe(100)
    expect(ctx._calls.fillText).toHaveLength(0)
  })

  it('wrapText con texto corto dibuja 1 línea', () => {
    const ctx = makeStubCtx()
    const y = wrapText(ctx, 'hola', 0, 100, 500, 30)
    expect(ctx._calls.fillText).toHaveLength(1)
    expect(ctx._calls.fillText[0].s).toBe('hola')
    expect(y).toBe(130)
  })

  it('wrapText con texto largo wrapea en varias líneas', () => {
    const ctx = makeStubCtx()
    // measureText devuelve len*10 → maxWidth=50 fuerza 1 palabra por línea
    const y = wrapText(ctx, 'uno dos tres cuatro', 0, 100, 50, 30)
    expect(ctx._calls.fillText.length).toBeGreaterThanOrEqual(2)
    expect(y).toBeGreaterThan(100)
  })

  it('wrapText respeta maxLines y añade ellipsis', () => {
    const ctx = makeStubCtx()
    wrapText(ctx, 'uno dos tres cuatro cinco seis siete', 0, 100, 50, 30, 2)
    // Última línea debe tener ellipsis
    const last = ctx._calls.fillText[ctx._calls.fillText.length - 1].s
    expect(last).toContain('…')
  })

  it('roundRect no crashea', () => {
    const ctx = makeStubCtx()
    expect(() => roundRect(ctx, 10, 10, 100, 50, 4)).not.toThrow()
  })
})
