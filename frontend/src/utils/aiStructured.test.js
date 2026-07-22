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

  it('drift del modelo: delimitador con espacios o guiones extra igual parsea', () => {
    const spaced = parseStructured(`La respuesta.\n--- RENDI ---\n${META}`)
    expect(spaced.prose).toBe('La respuesta.')
    expect(spaced.meta.verdict).toBe('Buen mes')
    const dashes = parseStructured(`La respuesta.\n----RENDI----\n${META}`)
    expect(dashes.meta.verdict).toBe('Buen mes')
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

describe('blocks (catálogo visual)', () => {
  const wrap = (blocks) => parseStructured(`p\n${RENDI_DELIM}${JSON.stringify({ verdict: 'Ok', blocks })}`)

  it('compare/alloc/scenario/table/actions válidos pasan', () => {
    const r = wrap([
      { type: 'compare', items: [{ l: 'Vos', v: '+18%', pct: 92 }, { l: 'S&P', v: '+15%', pct: 76 }] },
      { type: 'actions', items: [{ label: 'Ver atribución', to: '/analisis' }] },
    ])
    expect(r.meta.blocks).toHaveLength(2)
    expect(r.meta.blocks[0].type).toBe('compare')
    expect(r.meta.blocks[1].items[0].to).toBe('/analisis')
  })

  it('máximo 2 bloques por respuesta', () => {
    const r = wrap([
      { type: 'scenario', if: 'a', then: 'b', tone: 'neg' },
      { type: 'scenario', if: 'c', then: 'd', tone: 'pos' },
      { type: 'scenario', if: 'e', then: 'f', tone: 'pos' },
    ])
    expect(r.meta.blocks).toHaveLength(2)
  })

  it('tipo desconocido se ignora (forward-compat)', () => {
    const r = wrap([{ type: 'hologram3d', data: [1, 2] }, { type: 'scenario', if: 'a', then: 'b' }])
    expect(r.meta.blocks).toHaveLength(1)
    expect(r.meta.blocks[0].type).toBe('scenario')
  })

  it('actions: rutas externas / no-whitelisted / javascript: se descartan', () => {
    const r = wrap([{ type: 'actions', items: [
      { label: 'Malicioso', to: 'https://evil.com' },
      { label: 'Proto', to: 'javascript:alert(1)' },
      { label: 'No listada', to: '/admin' },
      { label: 'Ok', to: '/alertas?new=NVDA' },
    ] }])
    expect(r.meta.blocks).toHaveLength(1)
    expect(r.meta.blocks[0].items).toEqual([{ label: 'Ok', to: '/alertas?new=NVDA' }])
  })

  it('table: caps 4 cols × 5 filas', () => {
    const r = wrap([{ type: 'table', cols: ['a', 'b', 'c', 'd', 'e', 'f'], rows: Array.from({ length: 9 }, () => ['x', '1', '2', '3', '4', '5']) }])
    expect(r.meta.blocks[0].cols).toHaveLength(4)
    expect(r.meta.blocks[0].rows).toHaveLength(5)
    expect(r.meta.blocks[0].rows[0]).toHaveLength(4)
  })

  it('title opcional: pasa sanitizado (≤40), ausente no agrega la clave', () => {
    const r = wrap([{ type: 'compare', title: '  Tu cartera vs S&P · YTD  ', items: [{ l: 'Vos', v: '+3%' }, { l: 'S&P', v: '+10%' }] }])
    expect(r.meta.blocks[0].title).toBe('Tu cartera vs S&P · YTD')
    const long = wrap([{ type: 'alloc', title: 'x'.repeat(80), items: [{ l: 'A', pct: 60 }, { l: 'B', pct: 40 }] }])
    expect(long.meta.blocks[0].title).toHaveLength(40)
    const none = wrap([{ type: 'alloc', items: [{ l: 'A', pct: 60 }, { l: 'B', pct: 40 }] }])
    expect('title' in none.meta.blocks[0]).toBe(false)
  })

  it('valores numéricos del modelo se coercionan a string (no matan el block)', () => {
    const r = wrap([{ type: 'compare', items: [{ l: 'Tu cartera', v: 6.71 }, { l: 'S&P 500', v: 10.4 }] }])
    expect(r.meta.blocks).toHaveLength(1)
    expect(r.meta.blocks[0].items[0].v).toBe('6.71')
    const s = wrap([{ type: 'scenario', if: 'BTC corrige', then: -4.2, tone: 'neg' }])
    expect(s.meta.blocks[0].then).toBe('-4.2')
  })

  it('compare con <2 items no renderiza', () => {
    const r = wrap([{ type: 'compare', items: [{ l: 'Solo', v: '+1%' }] }])
    expect(r.meta.blocks).toHaveLength(0)
  })
})
