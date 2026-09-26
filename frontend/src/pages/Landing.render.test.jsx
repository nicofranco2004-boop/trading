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

describe('la home dice los cupos del chat que da el plan', () => {
  const plus = cupoDe(PLUS_FEATURES, 'Chat Rendi AI / sem')
  const pro = cupoDe(PRO_FEATURES, 'Chat Rendi AI / sem')

  it('el catálogo tiene los dos cupos (si no, la página diría "undefined")', () => {
    // Contra el falso verde: si alguien renombra la etiqueta del catálogo, la
    // página y este test leerían los dos `undefined` y coincidirían.
    expect(plus).toMatch(/^\d+$/)
    expect(pro).toMatch(/^\d+$/)
  })

  it('el paso 05 dice el cupo del Plus', () => {
    expect(texto).toContain(`12 preguntas guiadas (${plus} consultas por semana en Plus)`)
    expect(texto).toContain(`12 guiadas · ${plus}/sem (Plus)`)
  })

  it('y el del Pro', () => {
    expect(texto).toContain(`Chat libre · ${pro}/sem (Pro)`)
  })

  it('nombra a la IA con su nombre de hoy', () => {
    expect(texto).toContain('Rendi AI')
    expect(texto).not.toMatch(/coach/i)
  })
})
