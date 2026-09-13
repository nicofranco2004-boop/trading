import { describe, it, expect } from 'vitest'
import { traducirErrorDeChat, esCancelacion } from './errorChat.js'

describe('lo que ve el usuario cuando el chat falla', () => {
  it('la cuota agotada muestra el mensaje del backend, no uno genérico', () => {
    const r = traducirErrorDeChat({
      status: 429,
      payload: { detail: {
        error: 'chat_quota_exceeded',
        message: 'Llegaste al máximo de consultas (9/9) de esta semana.',
        usage: { chat_count: 9, chat_limit: 9 },
        upgrade: { available: true, target_tier: 'pro' },
      } },
    })
    expect(r.mensaje).toContain('9/9')
    expect(r.usage.chat_count).toBe(9)
    expect(r.upgrade.target_tier).toBe('pro')
  })

  it('sin upgrade.available NO se ofrece pasar de plan', () => {
    // A un Pro en el techo no hay adónde mandarlo: ofrecerle "mejorá tu plan"
    // es ruido.
    const r = traducirErrorDeChat({
      status: 429,
      payload: { detail: { message: 'Sin cupo.', upgrade: { available: false } } },
    })
    expect(r.upgrade).toBeUndefined()
  })

  it('el array de validación NUNCA se muestra crudo', () => {
    const r = traducirErrorDeChat({
      status: 422,
      payload: { detail: [{ type: 'string_too_long', loc: ['body'], msg: 'x' }] },
    })
    expect(r.mensaje).not.toContain('string_too_long')
    expect(r.mensaje).not.toContain('[')
    expect(r.mensaje).toContain('muy larga')
  })

  it('otro error de validación tampoco', () => {
    const r = traducirErrorDeChat({ status: 422, payload: { detail: [{ type: 'missing' }] } })
    expect(r.mensaje).not.toContain('missing')
    expect(r.mensaje).toContain('Nuevo')
  })

  it('la respuesta cortada a la mitad se avisa, no se hace pasar por completa', () => {
    const r = traducirErrorDeChat({ truncated: true })
    expect(r.mensaje).toContain('se cortó')
  })

  it('el proxy que corta por tiempo da un mensaje útil, no "algo salió mal"', () => {
    for (const status of [502, 503, 504]) {
      expect(traducirErrorDeChat({ status, payload: null }).mensaje).toContain('tardó más de lo normal')
    }
  })

  it('un detalle en texto se muestra tal cual', () => {
    expect(traducirErrorDeChat({ payload: { detail: 'El activo no existe.' } }).mensaje)
      .toBe('El activo no existe.')
  })

  it('lo que no reconoce cae a un mensaje que igual se entiende', () => {
    for (const e of [null, undefined, {}, { status: 500 }, new Error('boom')]) {
      const m = traducirErrorDeChat(e).mensaje
      expect(m).toContain('Intentalo nuevamente')
      expect(m).not.toContain('boom')
    }
  })
})

describe('cancelar no es fallar', () => {
  it('tocar "Nuevo" en medio de una respuesta no muestra ningún error', () => {
    expect(esCancelacion({ name: 'AbortError' })).toBe(true)
    expect(esCancelacion(new Error('otra cosa'))).toBe(false)
    expect(esCancelacion(null)).toBe(false)
  })
})
