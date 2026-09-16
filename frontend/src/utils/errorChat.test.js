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

describe('traducirErrorDeChat — qué cupo se agotó', () => {
  it('deja pasar el `kind` del backend', () => {
    const r = traducirErrorDeChat({
      status: 429,
      payload: { detail: {
        error: 'chat_quota_exceeded',
        kind: 'analyses',
        message: 'Llegaste al máximo de análisis (1/1) de esta semana.',
        usage: { analyses_count: 1, analyses_limit: 1, chat_count: 0, chat_limit: 1 },
        upgrade: { available: true, current_tier: 'free', target_tier: 'plus' },
      } },
    })
    expect(r.kind).toBe('analyses')
    expect(r.usage.analyses_count).toBe(1)
    expect(r.upgrade.target_tier).toBe('plus')
  })

  it('un backend viejo, sin el campo, no rompe nada', () => {
    const r = traducirErrorDeChat({
      status: 429,
      payload: { detail: { error: 'chat_quota_exceeded', message: 'x', usage: {} } },
    })
    expect(r.kind).toBeUndefined()
    expect(r.mensaje).toBe('x')
  })
})

describe('traducirErrorDeChat — el 403 de "chat libre" NO es una cuota', () => {
  // El caso real de producción (2026-09-16): un Free escribió "tengo 0,001
  // bitcoin". No es una de las 12 preguntas guiadas y no se parece a registrar
  // una operación, así que el backend contesta 403 con el texto que le dice qué
  // SÍ puede hacer. La tarjeta lo tapaba con un contador que no frenó nada.
  const RESPUESTA_403 = {
    status: 403,
    payload: { detail: {
      error: 'free_chat_not_allowed',
      message: 'El chat libre está disponible solo en el plan Pro. Elegí una de las preguntas guiadas, registrá una operación o un movimiento…',
      tier: 'free',
      upgrade: { available: true, current_tier: 'free', target_tier: 'pro', benefits: ['Chat libre con el Coach IA — preguntá lo que quieras'] },
    } },
  }

  it('trae el código, para que la tarjeta no lo confunda con cuota agotada', () => {
    const r = traducirErrorDeChat(RESPUESTA_403)
    expect(r.codigo).toBe('free_chat_not_allowed')
  })

  it('NO trae usage: no hay ningún contador que se haya llenado', () => {
    const r = traducirErrorDeChat(RESPUESTA_403)
    expect(r.usage).toBeUndefined()
  })

  it('conserva el mensaje accionable — es lo único útil de la pantalla', () => {
    const r = traducirErrorDeChat(RESPUESTA_403)
    expect(r.mensaje).toContain('preguntas guiadas')
    expect(r.mensaje).toContain('registrá una operación')
  })

  it('la cuota de verdad sigue distinguiéndose por su propio código', () => {
    const r = traducirErrorDeChat({
      status: 429,
      payload: { detail: { error: 'chat_quota_exceeded', kind: 'analyses', message: 'x', usage: {} } },
    })
    expect(r.codigo).toBe('chat_quota_exceeded')
    expect(r.kind).toBe('analyses')
  })
})
