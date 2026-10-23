// El resumen de Mervall-E montado dentro de la ficha de verdad
// (testing/navegadorMinimo.js), con el servidor simulado en la frontera
// (utils/api). Lo que se prueba es lo que ve la persona:
//   · si ya existe, se muestra solo, sin tocar nada y sin pedir nada;
//   · si no, el botón; al tocarlo aparece el texto y el resto de la ficha sigue;
//   · el tope y las fallas se dicen con calma, y la ficha no se rompe;
//   · sin IA (null), no hay ni botón.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscarBoton, clic } from '../../testing/navegadorMinimo'

function puntos(n, f) {
  return Array.from({ length: n }, (_, i) => ({
    d: new Date(Date.UTC(2025, 0, 1) + i * 86400000).toISOString().slice(0, 10),
    c: f(i), s50: f(i) * 1.02, s200: f(i) * 1.05, rsi: 40,
  }))
}
const BASE = {
  disponible: true, moneda: 'usd', ticker: 'NVDA', convertida: null,
  puntos: puntos(504, i => 250 - i * 0.03),
  lectura: { ruedas: 760, fecha: '2026-10-21', precio: 235, media50: 241, dist_media50: -2.5,
    media200: 250, dist_media200: -6, pendiente_media200: -1, rsi: 38, dist_maximo_12m: -14, anio_completo: true },
}
const TEXTO = 'En un año subió 23 %. Desde el 6 de octubre bajó de 243 a 213 dólares, y el 21 de octubre cerró en 222.'

let respuestas, alPost
vi.mock('../../utils/api', () => ({
  api: {
    get: vi.fn((ruta) => {
      const clave = Object.keys(respuestas).find(k => ruta.startsWith(k))
      return Promise.resolve(clave ? respuestas[clave] : [])
    }),
    post: vi.fn((ruta) => alPost(ruta)),
  },
}))

let LecturaTecnica, api
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
  ;({ api } = await import('../../utils/api'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  api.post.mockClear()
})

const el = () => h(LecturaTecnica, { asset: 'NVDA', symbolMiniChart: 'NVDA' })
async function dibujar(resumen) {
  respuestas = { '/tecnico/NVDA?moneda=usd': { ...BASE, resumen } }
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}
async function tocar(parte) {
  await clic(montado.contenedor, buscarBoton(montado.contenedor, parte))
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

describe('Resumen de Mervall-E en la ficha', () => {
  it('si ya existe se muestra solo, sin pedir nada', async () => {
    const t = await dibujar({ estado: 'listo', texto: TEXTO, fecha: '2026-10-21' })
    expect(t).toContain('Resumen de Mervall-E')
    expect(t).toContain(TEXTO)
    expect(t).toContain('al cierre del 21/10')
    expect(t).toContain('No es una recomendación')
    expect(api.post).not.toHaveBeenCalled()
  })

  it('si no existe: botón; al tocarlo aparece el texto y la ficha sigue igual', async () => {
    let t = await dibujar({ estado: 'no_hay', fecha: '2026-10-21' })
    expect(t).not.toContain(TEXTO)
    expect(t).toContain('Largo plazo')
    alPost = () => Promise.resolve({ estado: 'listo', texto: TEXTO, fecha: '2026-10-21' })
    t = await tocar('Resumen de Mervall-E')
    expect(api.post).toHaveBeenCalledTimes(1)
    expect(api.post.mock.calls[0][0]).toBe('/tecnico/NVDA/resumen?moneda=usd')
    expect(t).toContain(TEXTO)
    expect(t).toContain('Largo plazo')
  })

  it('mientras escribe, la ficha se ve igual y el botón lo dice', async () => {
    await dibujar({ estado: 'no_hay', fecha: '2026-10-21' })
    alPost = () => new Promise(() => {})                 // no contesta nunca
    const t = await tocar('Resumen de Mervall-E')
    expect(t).toContain('Mervall-E está escribiendo')
    expect(t).toContain('Largo plazo')
  })

  it('con el tope lleno lo dice con calma, sin botón para insistir', async () => {
    await dibujar({ estado: 'no_hay', fecha: '2026-10-21' })
    alPost = () => Promise.resolve({ estado: 'tope' })
    const t = await tocar('Resumen de Mervall-E')
    expect(t).toContain('Mañana vuelve a estar')
    expect(buscarBoton(montado.contenedor, 'Resumen de Mervall-E')).toBeFalsy()
    expect(t).toContain('Largo plazo')
  })

  it('si falla lo dice, deja probar de nuevo y la ficha no se rompe', async () => {
    await dibujar({ estado: 'no_hay', fecha: '2026-10-21' })
    alPost = () => Promise.reject(new Error('500'))
    let t = await tocar('Resumen de Mervall-E')
    expect(t).toContain('no se pudo escribir el resumen')
    expect(t).toContain('Largo plazo')
    alPost = () => Promise.resolve({ estado: 'listo', texto: TEXTO, fecha: '2026-10-21' })
    t = await tocar('Probar de nuevo')
    expect(t).toContain(TEXTO)
  })

  it('sin IA (o sin datos) no hay ni botón', async () => {
    const t = await dibujar(null)
    expect(t).not.toContain('Resumen de Mervall-E')
    expect(t).toContain('Largo plazo')
  })
})
