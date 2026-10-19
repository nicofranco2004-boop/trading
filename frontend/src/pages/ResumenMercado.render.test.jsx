import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

// La pantalla /resumen que abre la notificación del resumen del mercado, y el
// ejemplo de la card de /alertas: los dos dibujan con ResumenMercadoCuerpo.
// La forma de `resumen` es la que devuelve GET /api/market-brief/ultimo; el
// lado del servidor (que sea el último, que lleve lo mismo que el mail) lo
// certifica backend/tests/test_market_brief.py entrando por el cron real.

vi.mock('../components/Toast', () => ({ useToast: () => ({ push: () => {} }) }))

import ResumenMercadoCuerpo from '../components/alerts/ResumenMercadoCuerpo'
import CrearAlerta from '../components/alerts/CrearAlerta'
import { subtituloDelResumen, hoyArgentina, fechaLarga } from './ResumenMercado'
import fuenteDeApp from '../App.jsx?raw'

const RESUMEN = {
  date: '2026-10-16',
  titular: 'La Fed deja la tasa quieta',
  mercado: ['Primer párrafo del mercado.', 'Segundo párrafo.'],
  tu_cartera: ['NVDA sube con los chips.'],
  fuera_de_horario: { lineas: ['Anoche, en el post-mercado, tu cartera se movió +US$ 10.'], nota: 'Una nota.' },
  agenda: [{ ticker: 'AL30', label: 'Cupón + amortización' }],
}

describe('el cuerpo del resumen', () => {
  it('dibuja todo lo que lleva el mail', () => {
    const html = renderToStaticMarkup(<ResumenMercadoCuerpo resumen={RESUMEN} />)
    for (const t of ['La Fed deja la tasa quieta', 'Primer párrafo del mercado.',
      'Segundo párrafo.', 'Lo tuyo', 'NVDA sube con los chips.',
      'Wall Street fuera de la rueda', 'tu cartera se movió +US$ 10.', 'Una nota.',
      'En tu agenda de hoy', 'AL30', 'Cupón + amortización']) {
      expect(html, `falta «${t}»`).toContain(t)
    }
  })

  it('un resumen viejo, sin los bloques nuevos, se dibuja igual', () => {
    // Las filas guardadas antes del 2026-10-16 sólo tienen la narración.
    const html = renderToStaticMarkup(
      <ResumenMercadoCuerpo resumen={{ titular: 'Viejo', mercado: ['p'], tu_cartera: [] }} />)
    expect(html).toContain('Viejo')
    expect(html).not.toContain('Lo tuyo')
    expect(html).not.toContain('En tu agenda de hoy')
  })
})

describe('de qué día es', () => {
  it('el de hoy dice que es el de hoy', () => {
    expect(subtituloDelResumen(RESUMEN, '2026-10-16')).toBe('El de hoy, viernes 16 de octubre.')
  })

  it('uno viejo dice de qué día es y que lo reemplaza el próximo', () => {
    const s = subtituloDelResumen(RESUMEN, '2026-10-20')
    expect(s).toContain('del viernes 16 de octubre')
    expect(s).toContain('reemplaza')
  })

  it('a las 22 de Argentina sigue siendo el mismo día (no el de UTC)', () => {
    // 2026-10-16 22:30 ART = 2026-10-17 01:30 UTC.
    expect(hoyArgentina(new Date('2026-10-17T01:30:00Z'))).toBe('2026-10-16')
  })

  it('la fecha no se corre de día ni lleva coma', () => {
    expect(fechaLarga('2026-10-16')).toBe('viernes 16 de octubre')
    expect(fechaLarga('2026-10-19')).toBe('lunes 19 de octubre')
  })
})

describe('la notificación lleva a una ruta que existe', () => {
  it('/resumen está en el árbol de rutas', () => {
    expect(fuenteDeApp).toContain('path="/resumen"')
  })
})

describe('el ejemplo de la card usa el mismo cuerpo', () => {
  it('se dibuja sin romperse', () => {
    // Cerrado no muestra el ejemplo; alcanza con que la card monte con el
    // cuerpo compartido importado.
    const resumen = { cargado: true, prendido: false, error: false, cargar: () => {}, cambiar: () => {} }
    const html = renderToStaticMarkup(<MemoryRouter><CrearAlerta resumen={resumen} onCrearAviso={() => {}} /></MemoryRouter>)
    expect(html).toContain('Resumen del mercado')
  })
})
