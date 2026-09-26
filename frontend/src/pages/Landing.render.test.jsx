import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { HelmetProvider } from 'react-helmet-async'
import Landing from './Landing.jsx'
import { PLUS_FEATURES, PRO_FEATURES } from '../data/planCatalog'
import { cupoDe } from '../data/prueba'

// La home como la lee un visitante: se renderiza de verdad y se lee el texto,
// no las props. El paso 05 ("Le preguntás lo que necesites") decía los cupos
// del chat escritos a mano, y su copia para Google en `index.html` ya se había
// quedado vieja (6 consultas cuando el Plus da 9).
const texto = renderToStaticMarkup(
  <HelmetProvider><MemoryRouter><Landing /></MemoryRouter></HelmetProvider>,
).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

// El número que dice la página en ese lugar, o undefined si la frase cambió.
// Así el aviso de un rojo dice "expected '6' to be '9'" y no 40 KB de HTML.
const dice = (patron) => texto.match(patron)?.[1]

describe('la home dice los cupos del chat que da el plan', () => {
  const plus = cupoDe(PLUS_FEATURES, 'Chat Rendi AI / sem')
  const pro = cupoDe(PRO_FEATURES, 'Chat Rendi AI / sem')

  it('el catálogo tiene los dos cupos (si no, la página diría "undefined")', () => {
    // Contra el falso verde: si alguien renombra la etiqueta del catálogo, la
    // página y este test leerían los dos `undefined` y coincidirían.
    expect(plus, 'el catálogo ya no tiene «Chat Rendi AI / sem» en el Plus').toMatch(/^\d+$/)
    expect(pro, 'el catálogo ya no tiene «Chat Rendi AI / sem» en el Pro').toMatch(/^\d+$/)
  })

  it('el paso 05 dice el cupo del Plus', () => {
    expect(dice(/12 preguntas guiadas \((\S+) consultas por semana en Plus\)/),
      'el texto del paso 05 de la home').toBe(plus)
    expect(dice(/12 guiadas · (\S+)\/sem \(Plus\)/), 'la etiqueta del Plus del paso 05').toBe(plus)
  })

  it('y el del Pro', () => {
    expect(dice(/Chat libre · (\S+)\/sem \(Pro\)/), 'la etiqueta del Pro del paso 05').toBe(pro)
  })

  it('nombra a la IA con su nombre de hoy', () => {
    expect(texto).toContain('Rendi AI')
    const i = texto.search(/coach/i)
    expect(i === -1 ? null : texto.slice(Math.max(0, i - 60), i + 60),
      'la home dice "coach" acá').toBeNull()
  })
})
