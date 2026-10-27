// La elección Certero / Estimado es UNA para toda la app y se guarda hasta que el
// usuario la cambie. Antes cada pantalla tenía su `useState('certero')`: elegir
// Estimado en Métricas no llegaba al Dashboard y se perdía al navegar.
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import {
  ModoRendimientoProvider, useModoRendimiento, leerModoGuardado, guardarModo,
} from './ModoRendimientoContext'

function memoria() {
  const m = new Map()
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) }
}

function Pantalla({ id }) {
  const [modo] = useModoRendimiento()
  return <span>{id}={modo};</span>
}

describe('modo de rendimiento guardado', () => {
  let original
  beforeEach(() => { original = globalThis.localStorage; globalThis.localStorage = memoria() })
  afterEach(() => { globalThis.localStorage = original })

  it('arranca en certero si nunca se eligió', () => {
    expect(leerModoGuardado()).toBe('certero')
  })

  it('lo elegido queda guardado y se lee en la próxima visita', () => {
    guardarModo('estimado')
    expect(leerModoGuardado()).toBe('estimado')
  })

  it('un valor basura guardado cae a certero', () => {
    globalThis.localStorage.setItem('rendi_modo_rendimiento', 'cualquiera')
    expect(leerModoGuardado()).toBe('certero')
  })

  it('todas las pantallas leen la MISMA elección guardada', () => {
    guardarModo('estimado')
    const html = renderToStaticMarkup(
      <ModoRendimientoProvider>
        <Pantalla id="metricas" /><Pantalla id="dashboard" /><Pantalla id="metas" />
      </ModoRendimientoProvider>)
    expect(html).toBe('<span>metricas=estimado;</span><span>dashboard=estimado;</span><span>metas=estimado;</span>')
  })

  it('sin localStorage (modo privado) no rompe: certero', () => {
    globalThis.localStorage = { getItem() { throw new Error('bloqueado') }, setItem() { throw new Error('bloqueado') } }
    expect(leerModoGuardado()).toBe('certero')
    expect(() => guardarModo('estimado')).not.toThrow()
  })
})
