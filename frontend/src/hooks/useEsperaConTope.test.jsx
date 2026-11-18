// useEsperaConTope: una pantalla ya mostrada no vuelve al esqueleto porque lo
// de arriba se pide de nuevo; pero si la pantalla vuelve a SU esqueleto (en la
// ficha, otro activo elegido en el buscador, con la misma página), la vez
// siguiente espera otra vez. Sin eso, el chip de pre/post del segundo activo
// llegaba con la ficha ya dibujada y la bajaba (17/11/2026).
import { describe, it, expect, beforeAll } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar } from '../testing/navegadorMinimo'
import { useEsperaConTope } from './useEsperaConTope'

let visto
function Pantalla({ desde, listo }) {
  visto = useEsperaConTope({ desde, listo })
  return null
}

beforeAll(() => { instalarNavegadorMinimo() })

describe('useEsperaConTope', () => {
  it('espera a lo de arriba sólo desde que la pantalla tiene lo suyo, y mostrada queda mostrada', async () => {
    const m = await montar(h(Pantalla, { desde: false, listo: true }))
    expect(visto, 'sin lo suyo, la pantalla no se muestra aunque lo de arriba diga «listo»').toBe(false)
    await m.redibujar(h(Pantalla, { desde: true, listo: false }))
    expect(visto, 'lo de arriba todavía no sabe cuánto ocupa').toBe(false)
    await m.redibujar(h(Pantalla, { desde: true, listo: true }))
    expect(visto).toBe(true)
    // Se pide de nuevo (cambió la cartera): no vuelve al esqueleto.
    await m.redibujar(h(Pantalla, { desde: true, listo: false }))
    expect(visto, 'una pantalla ya mostrada volvió al esqueleto').toBe(true)
    await m.desmontar()
  })

  it('si la pantalla vuelve a su esqueleto, la vez siguiente espera de nuevo', async () => {
    const m = await montar(h(Pantalla, { desde: true, listo: true }))
    expect(visto).toBe(true)
    // Otro activo: la ficha vuelve a cargar lo suyo…
    await m.redibujar(h(Pantalla, { desde: false, listo: true }))
    // …lo tiene, y lo de arriba del activo nuevo todavía no contestó.
    await m.redibujar(h(Pantalla, { desde: true, listo: false }))
    expect(visto, 'el segundo activo se mostró sin esperar a lo de arriba').toBe(false)
    await m.redibujar(h(Pantalla, { desde: true, listo: true }))
    expect(visto).toBe(true)
    await m.desmontar()
  })
})
