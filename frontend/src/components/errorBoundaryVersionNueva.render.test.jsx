// El cartel de error cuando lo que falla es bajar un pedazo de la app (se publicó
// una versión nueva con la pestaña abierta y se abrió una pantalla que se baja
// aparte, como «Una cartera»): repara y recarga una vez, en vez de «Se rompió
// esta pantalla». React atrapa ese error y el navegador nunca avisa, así que la
// reparación de main.jsx no corría (auditoría de verificación 05/11, V3).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto } from '../testing/navegadorMinimo'

const recarga = vi.hoisted(() => ({ hace: true, mensajes: [] }))
vi.mock('../utils/chunkErrors', async (importar) => ({
  ...(await importar()),
  recargarUnaVez: (m) => { recarga.mensajes.push(m); return recarga.hace },
}))

function Rota({ mensaje }) { throw new Error(mensaje) }

let montado
beforeEach(() => { instalarNavegadorMinimo(); recarga.hace = true; recarga.mensajes = []; vi.spyOn(console, 'error').mockImplementation(() => {}) })
afterEach(async () => { await montado?.desmontar?.(); montado = null; vi.restoreAllMocks() })

describe('el cartel de error y una versión nueva', () => {
  it('un pedazo que no baja: repara y recarga, y lo dice', async () => {
    const { default: ErrorBoundary } = await import('./ErrorBoundary')
    const mensaje = 'Failed to fetch dynamically imported module: https://rendi.finance/assets/SimularCartera-abc.js'
    montado = await montar(h(ErrorBoundary, null, h(Rota, { mensaje })))
    expect(recarga.mensajes).toEqual([mensaje])
    expect(texto(montado.contenedor)).toContain('Hay una versión nueva de Rendi: la estamos cargando…')
    expect(texto(montado.contenedor)).not.toContain('Se rompió esta pantalla')
  })

  it('si ya recargó hace un momento, no entra en un bucle: muestra el cartel de siempre', async () => {
    recarga.hace = false
    const { default: ErrorBoundary } = await import('./ErrorBoundary')
    montado = await montar(h(ErrorBoundary, null, h(Rota, { mensaje: 'Failed to fetch dynamically imported module: x' })))
    expect(texto(montado.contenedor)).toContain('Se rompió esta pantalla')
  })

  it('cualquier otro error: el cartel de siempre, sin recargar', async () => {
    const { default: ErrorBoundary } = await import('./ErrorBoundary')
    montado = await montar(h(ErrorBoundary, null, h(Rota, { mensaje: 'x is not a function' })))
    expect(recarga.mensajes).toEqual([])
    expect(texto(montado.contenedor)).toContain('Se rompió esta pantalla')
  })
})
