import { it, expect, vi } from 'vitest'

// La barra de arriba del celular, DIBUJADA, anota su alto en
// --alto-barra-celular. Si deja de hacerlo, vuelve el error que costó tres
// vueltas de auditoría: el total de Cartera y de Movimientos tapado al bajar
// para el que está en la prueba gratis o mira un cliente. Probar la función de
// medir suelta no alcanza: hay que ver que la barra la use, sobre su <header>.
//
// Sin navegador (vitest en node) los efectos no corren al dibujar: acá se
// juntan los de la barra y se corren a mano, con una barra falsa de 139,6 px.
const efectos = []
let barraFalsa = null
vi.mock('react', async (original) => {
  const real = await original()
  const useLayoutEffect = (fn) => { efectos.push(fn) }
  const useRef = (v) => (v === null && barraFalsa ? { current: barraFalsa } : real.useRef(v))
  return { ...real, default: { ...real, useLayoutEffect, useRef }, useLayoutEffect, useRef }
})
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ user: { tier: 'pro' } }) }))
vi.mock('../../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: null }) }))
vi.mock('../../contexts/CoachDrawerContext', () => ({ useCoachDrawer: () => ({ open: () => {} }) }))
vi.mock('../CurrencySwitcher', () => ({ default: () => null }))

import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import MobileTopBar from './MobileTopBar'

it('la barra, dibujada, anota su alto y lo borra al desarmarse', () => {
  const vars = {}
  vi.stubGlobal('document', { documentElement: { style: {
    setProperty: (k, v) => { vars[k] = v }, removeProperty: (k) => { delete vars[k] },
  } } })
  try {
    barraFalsa = { getBoundingClientRect: () => ({ height: 139.6 }) }
    renderToStaticMarkup(<MemoryRouter><MobileTopBar /></MemoryRouter>)
    barraFalsa = null
    const limpiezas = efectos.map(fn => { try { return fn() } catch { return null } })
    expect(vars).toEqual({ '--alto-barra-celular': '140px' })
    limpiezas.forEach(l => { if (typeof l === 'function') l() })   // se pasó al armado de compu
    expect(vars).toEqual({})
  } finally {
    vi.unstubAllGlobals()
  }
})
