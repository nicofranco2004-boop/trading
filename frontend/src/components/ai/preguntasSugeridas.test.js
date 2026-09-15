import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { SUGERIDAS, SUGERIDAS_ASESOR, paraLaIsla } from './preguntasSugeridas'

// 🔴 Estaban copiadas: el chat grande tenía las doce y la isla tenía dos suyas,
// escritas a mano. Resultado medido: a un ASESOR la isla le ofrecía "¿cómo está
// mi portfolio en general?" — una cartera personal que él no tiene — mientras
// el chat grande, con la lista bien, le ofrecía las del libro. Dos copias, una
// actualizada y la otra no.
describe('una sola lista para las dos pantallas', () => {
  const isla = readFileSync(new URL('../voz/RendiMate.jsx', import.meta.url), 'utf8')
  const chat = readFileSync(new URL('../AICoach.jsx', import.meta.url), 'utf8')

  it('ninguna de las dos tiene su propia copia', () => {
    for (const [nombre, src] of [['la isla', isla], ['el chat grande', chat]]) {
      expect(src, nombre).not.toMatch(/'¿Cómo está mi portfolio en general\?'/)
      expect(src, nombre).not.toMatch(/'¿Cómo viene mi libro en general\?'/)
    }
  })

  it('al asesor le ofrece preguntas sobre su LIBRO', () => {
    const [a, b] = paraLaIsla(true)
    expect(a).toMatch(/libro/i)
    expect(b).toMatch(/cliente/i)
  })

  it('y al usuario común, sobre su cartera', () => {
    expect(paraLaIsla(false)).toEqual(SUGERIDAS.slice(0, 2))
  })

  it('las doce del usuario siguen siendo doce', () => {
    // Tienen que coincidir letra por letra con la lista cerrada del backend:
    // Free y Plus sólo pueden mandar éstas.
    expect(SUGERIDAS).toHaveLength(12)
    expect(new Set(SUGERIDAS).size).toBe(12)
  })

  it('las del asesor no hablan de "mi cartera"', () => {
    // El asesor en su nivel no tiene una: tiene el libro de sus clientes.
    const sospechosas = SUGERIDAS_ASESOR.filter(q => /mi cartera|mi portfolio/i.test(q))
    expect(sospechosas).toEqual([])
  })
})
