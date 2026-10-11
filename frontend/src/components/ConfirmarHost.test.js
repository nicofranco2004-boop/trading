// El "¿Seguro?" es de Rendi, no del navegador (utils/confirmar.js).
//
// Visto por Nico el 2026-10-10: en un navegador embebido que no muestra el
// cartel propio del navegador, `window.confirm` contestaba "no" solo y el
// tachito de Movimientos no hacía nada. Acá se monta el cartel de verdad y se
// contesta como una persona: tocando sus botones.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h, act } from 'react'
import fs from 'node:fs'
import path from 'node:path'
import { instalarNavegadorMinimo, montar, texto, buscarBoton, clic, enActo } from '../testing/navegadorMinimo'

let ConfirmarHost, confirmar
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ confirmar } = await import('../utils/confirmar'))
  ConfirmarHost = (await import('./ConfirmarHost')).default
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null })

const tocar = (boton) => enActo(() => clic(montado.contenedor, boton))

// Abre la pregunta y espera a que el cartel se dibuje. La respuesta va envuelta:
// devolver la promesa pelada desde una función `async` haría esperar a que la
// persona conteste antes de seguir.
async function preguntar(mensaje, opciones) {
  let respuesta
  await act(async () => { respuesta = confirmar(mensaje, opciones) })
  return { respuesta }
}

describe('el cartel de Rendi', () => {
  it('muestra la pregunta como título y el resto como explicación', async () => {
    montado = await montar(h(ConfirmarHost))
    expect(texto(montado.contenedor)).toBe('')                       // cerrado no dibuja nada
    const p = await preguntar('¿Borrar el depósito?\n\nSale la plata de la cuenta.')
    const t = texto(montado.contenedor)
    expect(t).toContain('¿Borrar el depósito?')
    expect(t).toContain('Sale la plata de la cuenta.')
    expect(t).toContain('Cancelar')
    expect(t).toContain('Confirmar')
    await tocar(buscarBoton(montado.contenedor, 'Confirmar'))
    expect(await p.respuesta).toBe(true)
    expect(texto(montado.contenedor)).toBe('')                       // y se cierra
  })

  it('"Cancelar" contesta que no', async () => {
    montado = await montar(h(ConfirmarHost))
    const p = await preguntar('¿Borrar?')
    await tocar(buscarBoton(montado.contenedor, 'Cancelar'))
    expect(await p.respuesta).toBe(false)
  })

  it('con una pregunta abierta, otra no se apila: se contesta que no', async () => {
    montado = await montar(h(ConfirmarHost))
    const primera = await preguntar('¿Borrar KO?')
    expect(await (await preguntar('¿Borrar SPY?')).respuesta).toBe(false)             // el doble click no acepta solo
    expect(texto(montado.contenedor)).toContain('¿Borrar KO?')      // sigue la primera
    await tocar(buscarBoton(montado.contenedor, 'Confirmar'))
    expect(await primera.respuesta).toBe(true)
  })

  it('los botones pueden decir lo que la pantalla necesite', async () => {
    montado = await montar(h(ConfirmarHost))
    const p = await preguntar('¿Borrar todo?', { si: 'Sí, borrar', no: 'Mejor no', peligro: true })
    expect(texto(montado.contenedor)).toContain('Mejor no')
    await tocar(buscarBoton(montado.contenedor, 'Sí, borrar'))
    expect(await p.respuesta).toBe(true)
  })

  it('si el cartel se desmonta con la pregunta abierta, se contesta que no', async () => {
    montado = await montar(h(ConfirmarHost))
    const p = await preguntar('¿Borrar?')
    await montado.desmontar(); montado = null
    expect(await p.respuesta).toBe(false)
  })
})

describe('sin el cartel montado (una pantalla suelta en una prueba)', () => {
  it('pregunta con el del navegador: la pregunta nunca se saltea', async () => {
    const nativo = vi.fn(() => true)
    window.confirm = nativo
    expect(await confirmar('¿Borrar?')).toBe(true)
    expect(nativo).toHaveBeenCalledWith('¿Borrar?')
    window.confirm = () => false
    expect(await confirmar('¿Borrar?')).toBe(false)
    delete window.confirm
  })
})

// Guardián: nadie vuelve a preguntar con el cartel del navegador. Si una
// pantalla nueva escribe `confirm(…)`, esa pregunta deja de verse en los
// navegadores embebidos — el error de hoy, en otro lado.
describe('nadie usa el cartel del navegador', () => {
  const SRC = path.resolve(__dirname, '..')
  // Estos dos archivos tienen una función PROPIA que se llama `confirm` (el
  // "confirmar" de un paso del formulario): no es el cartel del navegador.
  const CON_FUNCION_PROPIA = new Set(['components/AddPositionFlow.jsx', 'components/import/ImportWizard.jsx'])
  const archivos = []
  ;(function andar(dir) {
    for (const f of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, f.name)
      if (f.isDirectory()) andar(p)
      else if (/\.(jsx?|tsx?)$/.test(f.name) && !/\.test\./.test(f.name)) archivos.push(p)
    }
  })(SRC)

  it('ningún archivo llama a confirm() ni a window.confirm()', () => {
    const culpables = []
    for (const p of archivos) {
      const rel = path.relative(SRC, p)
      if (rel === 'utils/confirmar.js') continue                    // el único que lo conoce (respaldo)
      const lineas = fs.readFileSync(p, 'utf8').split('\n')
      lineas.forEach((l, i) => {
        if (/^\s*(\/\/|\*|\{\/\*)/.test(l)) return                  // comentarios
        const nativo = /window\.confirm\(/.test(l)
          || (!CON_FUNCION_PROPIA.has(rel) && /(?<![A-Za-z_.$])confirm\(/.test(l))
        if (nativo) culpables.push(`${rel}:${i + 1}`)
      })
    }
    expect(culpables).toEqual([])
  })

  it('el guardián ve un confirm() si alguien lo escribe', () => {
    expect(/(?<![A-Za-z_.$])confirm\(/.test("    if (!confirm('¿Borrar?')) return")).toBe(true)
    expect(/(?<![A-Za-z_.$])confirm\(/.test("    if (!await confirmar('¿Borrar?')) return")).toBe(false)
  })
})
