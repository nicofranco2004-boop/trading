// El menú del recuadro 22 (aprobado por Nico el 28/10): «Arriba, cómo está tu
// plata. Abajo, cómo están los activos». Tu Cartera igual; «Análisis» pasa a
// «Salud de cartera» (Métricas, Perfil de inversor); «Mercado» pasa a «Análisis
// de mercado» (Resumen, Análisis técnico, Análisis fundamental, Novedades).
// Las direcciones no cambian. El menú de la compu, «Más» del celular y el
// buscador ⌘K leen esta misma lista (utils/navegacion.js); la compu contra el
// celular, dibujados, la cuida menuMas.render.test.jsx.
import { describe, it, expect } from 'vitest'
import { GROUPS, pantallasVisibles } from './navegacion'
import { seccionesDelMenuMas } from '../pages/More'

const grupo = (id) => GROUPS.find(g => g.id === id)
const items = (id) => grupo(id).items.map(i => [i.to, i.label])

describe('el menú del recuadro 22', () => {
  it('Tu Cartera queda igual', () => {
    expect(grupo('cartera').label).toBe('Tu Cartera')
    expect(items('cartera')).toEqual([['/dashboard', 'Dashboard'], ['/posiciones', 'Cartera'], ['/operaciones', 'Movimientos']])
  })

  it('Salud de cartera: Métricas y Perfil de inversor', () => {
    expect(grupo('analisis').label).toBe('Salud de cartera')
    expect(items('analisis')).toEqual([['/analisis', 'Métricas'], ['/perfil-inversor', 'Perfil de inversor']])
  })

  it('Análisis de mercado: Resumen, Análisis técnico, Análisis fundamental, Novedades (las direcciones de siempre)', () => {
    expect(grupo('mercado').label).toBe('Análisis de mercado')
    expect(items('mercado')).toEqual([
      ['/', 'Resumen'], ['/analisis-tecnico', 'Análisis técnico'],
      ['/fundamentals', 'Análisis fundamental'], ['/novedades', 'Novedades'],
    ])
  })

  it('«Más» del celular: las mismas secciones, en el mismo orden, con su explicación', () => {
    const secciones = seccionesDelMenuMas(pantallasVisibles({ user: { tier: 'pro' } }))
    const de = (label) => secciones.find(s => s.label === label)?.items.map(i => i.to)
    expect(de('Salud de cartera')).toEqual(['/analisis', '/perfil-inversor'])
    expect(de('Análisis de mercado')).toEqual(['/', '/analisis-tecnico', '/fundamentals', '/novedades'])
    const tecnico = secciones.flatMap(s => s.items).find(i => i.to === '/analisis-tecnico')
    expect(tecnico.sub).toBe('Lo que tenés y lo que seguís, con su lectura técnica')
    expect(secciones.flatMap(s => s.items).some(i => /calidad de cartera/i.test(i.label))).toBe(false)
  })

  it('el asesor en su nivel no ve las secciones de la cartera; adentro de un cliente, sí', () => {
    const asesor = { tier: 'advisor' }
    expect(pantallasVisibles({ user: asesor }).some(p => p.to === '/analisis-tecnico')).toBe(false)
    expect(pantallasVisibles({ user: asesor, clientCtx: { id: 3, label: 'Ana' } }).some(p => p.to === '/analisis-tecnico')).toBe(true)
  })
})
