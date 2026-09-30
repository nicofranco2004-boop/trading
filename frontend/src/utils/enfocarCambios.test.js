import { describe, it, expect } from 'vitest'
import { elementosQueCambiaron } from './enfocarCambios'

// Elementos de mentira: `closest` sube por `padre` buscando la clase.
function el(nombre, clases = [], padre = null) {
  return {
    nombre, padre,
    closest(sel) {
      const buscadas = sel.split(',').map(s => s.trim().replace(/^\./, ''))
      for (let e = this; e; e = e.padre) if (buscadas.some(c => (e.clases || []).includes(c))) return e
      return null
    },
    clases,
  }
}
const texto = padre => ({ nodeType: 3, parentElement: padre })
const nombres = set => [...set].map(e => e.nombre).sort()

describe('elementosQueCambiaron — sólo anima lo que se reescribió', () => {
  it('un texto reescrito anima el número (.tabular) que lo contiene', () => {
    const numero = el('total', ['tabular'])
    const span = el('span-interno', [], numero)
    const out = elementosQueCambiaron([{ type: 'characterData', target: texto(span) }])
    expect(nombres(out)).toEqual(['total'])
  })

  it('React reemplazando el nodo de texto (childList) también cuenta', () => {
    const numero = el('pct', ['num'])
    const out = elementosQueCambiaron([{ type: 'childList', target: numero, addedNodes: [texto(numero)] }])
    expect(nombres(out)).toEqual(['pct'])
  })

  it('un texto sin número alrededor anima su elemento directo ("USD" → "ARS")', () => {
    const rotulo = el('rotulo', ['text-ink-3'])
    const out = elementosQueCambiaron([{ type: 'characterData', target: texto(rotulo) }])
    expect(nombres(out)).toEqual(['rotulo'])
  })

  it('un bloque entero que aparece (elementos, no texto) no se anima', () => {
    const panel = el('panel')
    const out = elementosQueCambiaron([{ type: 'childList', target: panel, addedNodes: [{ nodeType: 1 }] }])
    expect(out.size).toBe(0)
  })

  it('dos textos del mismo número cuentan una vez; sin mutaciones, nada', () => {
    const numero = el('total', ['tabular'])
    const a = el('entero', [], numero)
    const b = el('decimales', [], numero)
    const out = elementosQueCambiaron([
      { type: 'characterData', target: texto(a) },
      { type: 'characterData', target: texto(b) },
    ])
    expect(nombres(out)).toEqual(['total'])
    expect(elementosQueCambiaron(null).size).toBe(0)
  })
})
