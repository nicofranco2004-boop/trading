import { describe, it, expect, vi } from 'vitest'
import { seguirElBorrado, FALLAS_SEGUIDAS_MAX, MENSAJE } from './seguirElBorrado'

// El servidor, de mentira: una lista de respuestas en orden (un Error = falla de red).
function servidor(...respuestas) {
  const cola = [...respuestas]
  return vi.fn(async () => {
    const r = cola.length > 1 ? cola.shift() : cola[0]
    if (r instanceof Error) throw r
    return r
  })
}
const sinEspera = async () => {}
const siempre = () => true

describe('seguirElBorrado: sólo «listo» es terminado', () => {
  it('corriendo → listo: avisa el avance y termina bien', async () => {
    const alAvanzar = vi.fn()
    const r = await seguirElBorrado({
      pedir: servidor({ estado: 'corriendo', pct: 40, etapa: 'tus importaciones' }, { estado: 'listo' }),
      sigue: siempre, alAvanzar, esperar: sinEspera,
    })
    expect(r).toEqual({ fin: 'listo' })
    expect(alAvanzar).toHaveBeenCalledWith(expect.objectContaining({ etapa: 'tus importaciones' }))
  })

  it('«inactivo» en medio (el servidor se reinició) NO es terminado: se cortó', async () => {
    const r = await seguirElBorrado({
      pedir: servidor({ estado: 'corriendo', pct: 30 }, { estado: 'inactivo' }),
      sigue: siempre, esperar: sinEspera,
    })
    expect(r.fin).toBe('cortado')
    expect(r.mensaje).toBe(MENSAJE.cortado)
    expect(r.mensaje).toMatch(/otra vez/)
  })

  it('un estado que no se conoce tampoco se da por terminado', async () => {
    const r = await seguirElBorrado({ pedir: servidor({}), sigue: siempre, esperar: sinEspera })
    expect(r.fin).toBe('cortado')
  })

  it('error del servidor: muestra su motivo', async () => {
    const r = await seguirElBorrado({
      pedir: servidor({ estado: 'error', error: 'Se cortó a mitad del borrado.' }),
      sigue: siempre, esperar: sinEspera,
    })
    expect(r).toEqual({ fin: 'error', mensaje: 'Se cortó a mitad del borrado.' })
  })

  it('error sin motivo: un texto propio, no vacío', async () => {
    const r = await seguirElBorrado({ pedir: servidor({ estado: 'error' }), sigue: siempre, esperar: sinEspera })
    expect(r.mensaje).toBe(MENSAJE.error)
  })
})

describe('seguirElBorrado: la red', () => {
  it('fallas sueltas no cortan: sigue mirando', async () => {
    const r = await seguirElBorrado({
      pedir: servidor(new Error('Failed to fetch'), new Error('Failed to fetch'), { estado: 'listo' }),
      sigue: siempre, esperar: sinEspera,
    })
    expect(r.fin).toBe('listo')
  })

  it(`${FALLAS_SEGUIDAS_MAX} fallas seguidas: avisa en vez de esperar para siempre`, async () => {
    const pedir = servidor(new Error('Failed to fetch'))
    const r = await seguirElBorrado({ pedir, sigue: siempre, esperar: sinEspera })
    expect(r).toEqual({ fin: 'sin_conexion', mensaje: MENSAJE.sin_conexion })
    expect(pedir).toHaveBeenCalledTimes(FALLAS_SEGUIDAS_MAX)
  })

  it('una respuesta buena en el medio vuelve a contar desde cero', async () => {
    const fallas = Array(FALLAS_SEGUIDAS_MAX - 1).fill(new Error('x'))
    const r = await seguirElBorrado({
      pedir: servidor(...fallas, { estado: 'corriendo' }, ...fallas, { estado: 'listo' }),
      sigue: siempre, esperar: sinEspera,
    })
    expect(r.fin).toBe('listo')
  })
})

describe('seguirElBorrado: la persona se fue', () => {
  it('desmontada la pantalla, deja de pedir y no dice que terminó', async () => {
    let montada = true
    const pedir = vi.fn(async () => { montada = false; return { estado: 'corriendo' } })
    const r = await seguirElBorrado({ pedir, sigue: () => montada, esperar: sinEspera })
    expect(r).toEqual({ fin: 'desmontado' })
    expect(pedir).toHaveBeenCalledTimes(1)
  })

  it('si se fue durante la espera, ni siquiera pide', async () => {
    let montada = true
    const pedir = vi.fn()
    const r = await seguirElBorrado({
      pedir, sigue: () => montada, esperar: async () => { montada = false },
    })
    expect(r.fin).toBe('desmontado')
    expect(pedir).not.toHaveBeenCalled()
  })
})
