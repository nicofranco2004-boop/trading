import { describe, it, expect } from 'vitest'
import { parseStructured, RENDI_DELIM } from './aiStructured.js'

const META = '{"verdict":"Buen mes","tone":"pos","headline":"Vas +4,2% en julio.","stats":[{"l":"Este mes","v":"+4,2%","t":"pos"}],"followups":["¿Y en el año?"],"sources":["12 posiciones"]}'

describe('parseStructured', () => {
  it('texto sin bloque → prose intacta, meta null', () => {
    const r = parseStructured('Hola, tu cartera viene bien.')
    expect(r.prose).toBe('Hola, tu cartera viene bien.')
    expect(r.meta).toBe(null)
  })

  it('bloque completo → prose recortada + meta parseada', () => {
    const r = parseStructured(`La respuesta.\n${RENDI_DELIM}\n${META}`)
    expect(r.prose).toBe('La respuesta.')
    expect(r.meta.verdict).toBe('Buen mes')
    expect(r.meta.tone).toBe('pos')
    expect(r.meta.stats).toHaveLength(1)
    expect(r.meta.followups).toEqual(['¿Y en el año?'])
  })

  it('streaming: delimitador parcial al final NO se muestra como texto', () => {
    const r = parseStructured('La respuesta.\n---REN')
    expect(r.prose).toBe('La respuesta.')
    expect(r.meta).toBe(null)
  })

  it('streaming: JSON cortado a la mitad → prose limpia, meta null (todavía)', () => {
    const r = parseStructured(`La respuesta.\n${RENDI_DELIM}\n{"verdict":"Buen`)
    expect(r.prose).toBe('La respuesta.')
    expect(r.meta).toBe(null)
  })

  it('JSON roto → fallback silencioso a texto (sin throw)', () => {
    const r = parseStructured(`Texto.\n${RENDI_DELIM}\n{esto no es json}`)
    expect(r.prose).toBe('Texto.')
    expect(r.meta).toBe(null)
  })

  it('sanitiza: tone inválido → neutral, stats>3 → 3, followups no-string filtrados', () => {
    const meta = JSON.stringify({
      verdict: 'Ok', tone: 'banana', headline: 'x',
      stats: [1, 2, 3, 4].map(i => ({ l: `L${i}`, v: `${i}%`, t: 'zzz' })),
      followups: ['¿a?', 42, null, '¿b?', '¿c?', '¿d?'],
      sources: ['s1'],
    })
    const r = parseStructured(`p\n${RENDI_DELIM}${meta}`)
    expect(r.meta.tone).toBe('neutral')
    expect(r.meta.stats).toHaveLength(3)
    expect(r.meta.stats[0].t).toBe('neutral')
    expect(r.meta.followups).toEqual(['¿a?', '¿b?', '¿c?'])
  })

  it('bloque sin nada renderizable → meta null', () => {
    const r = parseStructured(`p\n${RENDI_DELIM}{"tone":"pos","stats":[]}`)
    expect(r.meta).toBe(null)
  })
})
