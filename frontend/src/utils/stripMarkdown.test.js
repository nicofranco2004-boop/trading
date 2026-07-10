// B-14 (audit IA #2): el regex de itálica colapsaba aritmética con asteriscos
// ("2 * 3 = 6 * 2" → matcheaba "* 3 = 6 *") — números mutilados en el chat.
import { describe, it, expect } from 'vitest'
import { stripMarkdown } from './stripMarkdown'

describe('stripMarkdown', () => {
  it('limpia bold e itálica reales', () => {
    expect(stripMarkdown('**fuerte** y *suave*')).toBe('fuerte y suave')
  })

  it('NO mutila aritmética con asteriscos (espacios alrededor)', () => {
    expect(stripMarkdown('2 * 3 = 6 * 2 = 12')).toBe('2 * 3 = 6 * 2 = 12')
    expect(stripMarkdown('rendimiento 5% * 12 meses * capital'))
      .toBe('rendimiento 5% * 12 meses * capital')
  })

  it('limpia list markers y headers', () => {
    expect(stripMarkdown('- item\n## título')).toBe('item\ntítulo')
  })

  it('es idempotente sobre texto ya limpio', () => {
    const s = 'AL30 rinde 8,2% anual * estimado'
    expect(stripMarkdown(stripMarkdown(s))).toBe(stripMarkdown(s))
  })

  it('bold con contenido numérico legítimo se limpia', () => {
    expect(stripMarkdown('ganaste **US$ 500** hoy')).toBe('ganaste US$ 500 hoy')
  })

  it('NO mutila multiplicación cross-line (asteriscos pegados en líneas distintas)', () => {
    // Regresión cazada por el review: [^*]* matcheaba \n → dos * pegados en
    // líneas distintas formaban par y colapsaban números.
    const s = 'AL30: 100*1.05 = 105\nGD30: 200*1.02 = 204'
    expect(stripMarkdown(s)).toBe(s)
  })

  it('NO mutila multiplicación PEGADA en la misma línea (guard anti-dígito)', () => {
    expect(stripMarkdown('2*3 = 6*2')).toBe('2*3 = 6*2')
    expect(stripMarkdown('100*1.05 y 200*1.02')).toBe('100*1.05 y 200*1.02')
  })

  it('documenta el quirk conocido: bold con espacio de borde NO se limpia', () => {
    // "**Etiqueta: **valor" (espacio antes del cierre) no cumple la regla
    // markdown de bordes → se muestra crudo. Trade-off deliberado: preferimos
    // no matchear (y no mutilar números) a limpiar este quirk de LLM. El
    // prompt instruye NO usar markdown, así que es rarísimo.
    expect(stripMarkdown('**Etiqueta: **valor')).toBe('**Etiqueta: **valor')
  })
})
