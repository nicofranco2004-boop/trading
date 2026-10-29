// «Análisis técnico» es una sección de Análisis (pedido de Nico, 28/10): en el
// menú de la compu, en «Más» del celular y en el buscador ⌘K, porque los tres
// leen la misma lista (utils/navegacion.js). La de la compu contra la del
// celular dibujadas la cuida menuMas.render.test.jsx.
import { describe, it, expect } from 'vitest'
import { GROUPS, pantallasVisibles } from './navegacion'
import { seccionesDelMenuMas } from '../pages/More'

describe('Análisis técnico en el menú', () => {
  it('está en el grupo Análisis, después de Calidad de cartera', () => {
    const analisis = GROUPS.find(g => g.id === 'analisis').items.map(i => i.to)
    expect(analisis).toEqual(['/analisis', '/fundamentals', '/analisis-tecnico', '/perfil-inversor'])
  })

  it('el buscador y «Más» del celular la ofrecen, con su explicación', () => {
    const pantallas = pantallasVisibles({ user: { tier: 'pro' } })
    const item = pantallas.find(p => p.to === '/analisis-tecnico')
    expect(item).toMatchObject({ label: 'Análisis técnico', grupoId: 'analisis' })
    const enMas = seccionesDelMenuMas(pantallas).flatMap(s => s.items.map(i => ({ ...i, seccion: s.label })))
    const fila = enMas.find(i => i.to === '/analisis-tecnico')
    expect(fila.sub).toBe('Lo que tenés y lo que seguís, con su lectura técnica')
    expect(enMas.find(i => i.to === '/fundamentals').seccion).toBe(fila.seccion)
  })

  it('el asesor en su nivel no la ve (no tiene cartera propia), adentro de un cliente sí', () => {
    const asesor = { tier: 'advisor' }
    expect(pantallasVisibles({ user: asesor }).some(p => p.to === '/analisis-tecnico')).toBe(false)
    expect(pantallasVisibles({ user: asesor, clientCtx: { id: 3, label: 'Ana' } }).some(p => p.to === '/analisis-tecnico')).toBe(true)
  })
})
