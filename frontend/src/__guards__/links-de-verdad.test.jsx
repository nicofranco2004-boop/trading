// D12 (auditoría D, 29/10): «Ver gráfico» (cada cambio de Señales y del
// Panorama), «Ver las 2 señales de la semana» y la pestaña «Tus señales ↗» de
// Novedades llevan a OTRA página pero eran botones: no se podían abrir en otra
// pestaña (botón del medio, ⌘+click) ni copiar el link, y la pestaña anunciaba
// «pestaña» a un lector de pantalla y te sacaba de la página. Ahora son links
// (<a href>); un click normal sigue navegando adentro de la app.
import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { Cambio } from '../components/TusSenales'
import { clicNormal } from '../utils/clicNormal'
import fuentePanorama from '../pages/AnalisisTecnico.jsx?raw'
import fuenteNovedades from '../pages/Novedades.jsx?raw'

vi.mock('../utils/api', async (orig) => ({ ...(await orig()), api: { get: vi.fn(() => new Promise(() => {})) } }))

const S = { asset: 'AAPL', ficha: 'AAPL', local: false, tenes: true, peso: 0.1, tipo: 'media200', etiqueta: 'Tendencia de fondo',
  tono: 'neg', texto: 'quedó abajo de su promedio de 200 días.', tesis: null }

describe('lo que lleva a otra página es un link', () => {
  it('«Ver gráfico» de cada cambio: <a href> a la ficha', () => {
    const html = renderToStaticMarkup(<MemoryRouter><ul><Cambio s={S} hidden={false} onVer={() => {}} /></ul></MemoryRouter>)
    expect(html).toMatch(/<a [^>]*href="\/activo\/AAPL"[^>]*>Ver gráfico<\/a>/)
  })

  it('un click normal navega adentro; con ⌘, Ctrl, Shift o el botón del medio, no se intercepta', () => {
    expect(clicNormal({ button: 0 })).toBe(true)
    for (const e of [{ button: 1 }, { button: 0, metaKey: true }, { button: 0, ctrlKey: true }, { button: 0, shiftKey: true }]) {
      expect(clicNormal(e)).toBe(false)
    }
  })

  it('«Ver las N señales de la semana» es un link a la pestaña', () => {
    const bloque = fuentePanorama.slice(fuentePanorama.indexOf('{total > 0 && ('), fuentePanorama.indexOf('de la semana <ArrowRight'))
    expect(bloque).toMatch(/<a href=\{urlDePestana\('senales'\)\}/)
  })

  it('«Tus señales ↗» de Novedades no es una pestaña: es un link afuera de la lista de pestañas', () => {
    expect(fuenteNovedades).toMatch(/SECTIONS\.filter\(s => !s\.fuera\)/)
    expect(fuenteNovedades).toMatch(/<Link[^>]*to=\{s\.fuera\}/)
  })
})
