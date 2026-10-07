import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'
import { readFileSync } from 'node:fs'
import { escribiendoEn } from './VozContext'
import CursorEscribiendo from '../components/ai/CursorEscribiendo'

// El cursor de Mervall-E AI va SÓLO en la respuesta que se está escribiendo.
describe('escribiendoEn', () => {
  const hilo = [{ role: 'user', content: '¿Cómo voy?' }, { role: 'assistant', content: 'Tu cartera' }]
  it('turno en curso y el texto llegando → la última respuesta', () => {
    expect(escribiendoEn(hilo, true, false)).toBe(1)
  })
  it('todavía pensando (sin ninguna letra) → ninguna: se ven los pasos', () => {
    expect(escribiendoEn(hilo.slice(0, 1), true, true)).toBe(-1)
    expect(escribiendoEn(hilo, true, true)).toBe(-1)
  })
  it('respuesta terminada → ninguna (un cursor ahí diría que falta algo)', () => {
    expect(escribiendoEn(hilo, false, false)).toBe(-1)
  })
  it('llegan letras pero todavía no hay texto para mostrar → ninguna', () => {
    expect(escribiendoEn(hilo.slice(0, 1), true, false)).toBe(-1)
  })
  it('sin conversación → ninguna', () => {
    expect(escribiendoEn([], true, false)).toBe(-1)
    expect(escribiendoEn(undefined, true, false)).toBe(-1)
  })
})

describe('<CursorEscribiendo>', () => {
  it('es decorativo (el lector de pantalla no lo lee) y parpadea con terminal-cursor', () => {
    const html = renderToStaticMarkup(createElement(CursorEscribiendo))
    expect(html).toContain('aria-hidden="true"')
    expect(html).toContain('terminal-cursor')
  })
  it('con "reducir movimiento" no parpadea: terminal-cursor está en la lista que se apaga', () => {
    const css = readFileSync(new URL('../index.css', import.meta.url), 'utf8')
    const bloque = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'))
    expect(bloque.slice(0, bloque.indexOf('animation: none !important'))).toContain('.terminal-cursor')
  })
})
