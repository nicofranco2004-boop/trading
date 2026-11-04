import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

// Lanzamiento del análisis técnico (Nico, 31/10/2026): «Nuevo» en Análisis de
// mercado y la fila de Análisis técnico resaltada durante 10 días; «Beta» hasta
// que Nico diga; «Backtesting» como Pronto (abierto el 04/11: ahora es una
// pestaña y el Pronto queda para Mercado). Se DIBUJA el menú de la compu, el
// «Más» del celular y la fila de pestañas, el día del vencimiento y el
// siguiente. Las fechas salen de FIN_DEL_NUEVO (no se escriben acá): la prueba
// no vence el día que pasa la fecha.
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { tier: 'pro' }, logout: () => {} }) }))
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: null }) }))
vi.mock('../contexts/AlertsContext', () => ({ useAlertsContext: () => ({ unseenCount: 0 }) }))
vi.mock('../contexts/ThemeContext', () => ({ useTheme: () => ({ dark: true, toggle: () => {} }) }))
vi.mock('../contexts/CoachDrawerContext', () => ({ useCoachDrawer: () => ({ open: () => {} }) }))
vi.mock('./CurrencySwitcher', () => ({ default: () => null }))
vi.mock('./RecommendationsModal', () => ({ default: () => null }))

import Sidebar from './Sidebar'
import { FIN_DEL_NUEVO, sigueVigente, esBeta, GROUPS, pantallasVisibles } from '../utils/navegacion'
import { seccionesDelMenuMas } from '../pages/More'
import { PESTANAS, pestanaDe } from '../pages/AnalisisTecnico'

// El mediodía de un día calendario, en el huso de la máquina (hoyISO usa el
// día de acá): ni las 21 h de Buenos Aires lo corren de día.
const elDia = (iso, mas = 0) => { const d = new Date(`${iso}T12:00:00`); d.setDate(d.getDate() + mas); return d }
const dibujar = (en = '/dashboard') =>
  renderToStaticMarkup(<MemoryRouter initialEntries={[en]}><Sidebar /></MemoryRouter>)
// El pedazo del menú que va de un texto al siguiente (la fila de Análisis técnico).
const fila = (html, to) => {
  const i = html.indexOf(`href="${to}"`)
  return html.slice(html.lastIndexOf('<a', i), html.indexOf('</a>', i))
}
const grupoMercado = (html) => {
  const i = html.indexOf('>Análisis de mercado<')
  return html.slice(html.lastIndexOf('<button', i), html.indexOf('</button>', i))
}

describe('«Nuevo» 10 días, «Beta» hasta que Nico diga', () => {
  beforeAll(() => { vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => {}, removeItem: () => {} }) })
  afterAll(() => { vi.unstubAllGlobals() })
  afterEach(() => { vi.useRealTimers() })

  it('el «Nuevo» va del 01/11 al 10/11 incluidos, y la cuenta compara días', () => {
    expect(FIN_DEL_NUEVO).toBe('2026-11-10')
    expect(sigueVigente(FIN_DEL_NUEVO, '2026-11-01')).toBe(true)
    expect(sigueVigente(FIN_DEL_NUEVO, FIN_DEL_NUEVO)).toBe(true)
    expect(sigueVigente(FIN_DEL_NUEVO, '2026-11-11')).toBe(false)
    expect(sigueVigente(null, '2026-11-01')).toBe(false)
  })

  it('una sola lista: el grupo lleva el «Nuevo», la pantalla el «Beta» y el resaltado', () => {
    const mercado = GROUPS.find(g => g.id === 'mercado')
    expect(mercado.nuevoHasta).toBe(FIN_DEL_NUEVO)
    expect(GROUPS.filter(g => g.nuevoHasta).map(g => g.id)).toEqual(['mercado'])
    const conBeta = GROUPS.flatMap(g => g.items).filter(i => i.beta).map(i => i.to)
    expect(conBeta).toEqual(['/analisis-tecnico'])
    expect(esBeta('/analisis-tecnico')).toBe(true)
    expect(esBeta('/fundamentals')).toBe(false)
  })

  it('compu, último día: «Nuevo» en el grupo y la fila resaltada con «Beta»', () => {
    vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(elDia(FIN_DEL_NUEVO))
    const html = dibujar()
    expect(grupoMercado(html)).toContain('>Nuevo<')
    const tecnico = fila(html, '/analisis-tecnico')
    expect(tecnico).toContain('>Beta<')
    expect(tecnico).toContain('bg-data-violet/[0.08]')
    // Las demás filas, como siempre.
    expect(fila(html, '/fundamentals')).not.toContain('bg-data-violet/[0.08]')
    expect(fila(html, '/fundamentals')).not.toContain('>Beta<')
  })

  it('compu, estando adentro: manda el «estás acá», no el resaltado (sigue el «Beta»)', () => {
    vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(elDia(FIN_DEL_NUEVO))
    const tecnico = fila(dibujar('/analisis-tecnico'), '/analisis-tecnico')
    expect(tecnico).toContain('bg-bg-2')
    expect(tecnico).not.toContain('bg-data-violet/[0.08]')
    expect(tecnico).toContain('>Beta<')
  })

  it('compu, día 11: se van solos el «Nuevo» y el resaltado; queda el «Beta»', () => {
    vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(elDia(FIN_DEL_NUEVO, 1))
    const html = dibujar()
    expect(html).not.toContain('>Nuevo<')
    const tecnico = fila(html, '/analisis-tecnico')
    expect(tecnico).not.toContain('bg-data-violet/[0.08]')
    expect(tecnico).toContain('>Beta<')
  })

  it('«Más» del celular recibe lo mismo de la misma lista', () => {
    const secciones = seccionesDelMenuMas(pantallasVisibles({ user: { tier: 'pro' } }))
    const mercado = secciones.find(s => s.label === 'Análisis de mercado')
    expect(mercado.nuevoHasta).toBe(FIN_DEL_NUEVO)
    expect(secciones.filter(s => s.nuevoHasta).map(s => s.label)).toEqual(['Análisis de mercado'])
    const tecnico = mercado.items.find(i => i.to === '/analisis-tecnico')
    expect(tecnico.beta).toBe(true)
    expect(tecnico.resaltadaHasta).toBe(FIN_DEL_NUEVO)
    expect(mercado.items.filter(i => i.beta).map(i => i.to)).toEqual(['/analisis-tecnico'])
  })

  it('Backtesting ya se abre (04/11); el Pronto queda sólo para Mercado', () => {
    expect(PESTANAS.filter(p => p.pronto).map(p => p.label)).toEqual(['Mercado'])
    expect(pestanaDe(new URLSearchParams('tab=backtesting'))).toBe('backtesting')
    expect(pestanaDe(new URLSearchParams('tab=mercado'))).toBe('grafico')
  })
})
