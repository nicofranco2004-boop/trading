import { describe, it, expect } from 'vitest'
import { entrada } from './useAlVerse'

// La única definición de "entra en escalera" (8 listas y grillas la usan): las
// clases tienen que ser las que index.css anima y esconde.
describe('entrada', () => {
  it('antes de verse espera escondida; después entra, con su turno en --i', () => {
    expect(entrada(false, 3, 'h-full')).toEqual({ className: 'h-full por-entrar', style: { '--i': 3 } })
    expect(entrada(true, 3, 'h-full')).toEqual({ className: 'h-full entra', style: { '--i': 3 } })
  })
  it('sin clases propias no deja espacios sueltos', () => {
    expect(entrada(true, 0).className).toBe('entra')
  })
})

import { bastanteVisible } from './useAlVerse'

// Una lista alta (25 noticias, ~3.000 px) en una pantalla de 860 px: el 15 %
// DEL ELEMENTO no entra nunca, y las noticias de Novedades quedaban invisibles
// (2026-10-02). Alcanza con el 15 % de la pantalla.
describe('bastanteVisible', () => {
  const pantalla = { height: 860 }
  it('lista alta con 300 px a la vista: arranca (aunque sea el 10 % de la lista)', () => {
    expect(bastanteVisible({ isIntersecting: true, intersectionRatio: 0.1, intersectionRect: { height: 300 }, rootBounds: pantalla }, 0.15)).toBe(true)
  })
  it('lista alta con 30 px a la vista: todavía no', () => {
    expect(bastanteVisible({ isIntersecting: true, intersectionRatio: 0.01, intersectionRect: { height: 30 }, rootBounds: pantalla }, 0.15)).toBe(false)
  })
  it('sección corta: con el 15 % de ella alcanza, como antes', () => {
    expect(bastanteVisible({ isIntersecting: true, intersectionRatio: 0.2, intersectionRect: { height: 40 }, rootBounds: pantalla }, 0.15)).toBe(true)
  })
  it('fuera de la pantalla, nunca', () => {
    expect(bastanteVisible({ isIntersecting: false, intersectionRatio: 0, intersectionRect: { height: 0 }, rootBounds: pantalla }, 0.15)).toBe(false)
  })
})
