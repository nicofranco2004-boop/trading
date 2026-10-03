// Qué cara pone Mervall-E según la conversación. El orden de las reglas ES la
// decisión de producto (ver estadoDelChat.js): cada caso de acá es una frase
// de la propuesta aprobada el 2026-10-03.
import { describe, it, expect } from 'vitest'
import { estadoDelChat, ultimaRespuesta, tocaSaludar, REACCION_POR_TONO } from './estadoDelChat'
import { ESTADOS } from './motor'

const base = { sending: false, loading: false, status: 'idle', askError: null, upgradeInfo: null, sinCupo: null, reaccion: null }
const e = (cambios) => estadoDelChat({ ...base, ...cambios })

describe('estadoDelChat — la cara según lo que pasa', () => {
  it('sin nada pasando, reposo', () => {
    expect(e({})).toEqual({ estado: 'reposo', tono: null })
  })

  it('mandaste la pregunta y todavía no llegó nada → pensando', () => {
    expect(e({ sending: true, loading: true }).estado).toBe('pensando')
  })

  it('el texto está llegando → hablando', () => {
    expect(e({ sending: true, loading: false }).estado).toBe('hablando')
  })

  it('la voz la está leyendo en voz alta → hablando', () => {
    expect(e({ status: 'playing' }).estado).toBe('hablando')
  })

  it('la respuesta terminó con tono: buena → contento, para mirar → atento, mala → serio, y el tono pasa al monitor', () => {
    expect(e({ reaccion: { tono: 'pos' } })).toEqual({ estado: 'contento', tono: 'pos' })
    expect(e({ reaccion: { tono: 'warn' } })).toEqual({ estado: 'atento', tono: 'warn' })
    expect(e({ reaccion: { tono: 'neg' } })).toEqual({ estado: 'serio', tono: 'neg' })
  })

  it('un tono neutral o desconocido NO reacciona ni pinta el monitor', () => {
    expect(e({ reaccion: { tono: 'neutral' } })).toEqual({ estado: 'reposo', tono: null })
    expect(e({ reaccion: { tono: 'cualquiera' } })).toEqual({ estado: 'reposo', tono: null })
  })

  it('la pregunta falló → confundido', () => {
    expect(e({ askError: 'No pude conectarme' }).estado).toBe('confundido')
  })

  it('sin consultas gana a todo → durmiendo, sin color', () => {
    expect(e({ upgradeInfo: { available: true }, askError: 'cuota', reaccion: { tono: 'pos' } }))
      .toEqual({ estado: 'durmiendo', tono: null })
    expect(e({ sinCupo: { resets_on: '2026-10-06' } }).estado).toBe('durmiendo')
  })

  it('una pregunta nueva le gana a la reacción de la anterior', () => {
    expect(e({ sending: true, loading: true, reaccion: { tono: 'pos' } }).estado).toBe('pensando')
  })

  it('la reacción le gana a la voz que todavía lee la respuesta (los 3-4 s de la cara)', () => {
    expect(e({ status: 'playing', reaccion: { tono: 'neg' } }).estado).toBe('serio')
  })

  it('cada estado que puede devolver existe en el motor', () => {
    const posibles = ['reposo', 'pensando', 'hablando', 'confundido', 'durmiendo', ...Object.values(REACCION_POR_TONO)]
    for (const p of posibles) expect(ESTADOS[p], p).toBeTruthy()
  })
})

describe('ultimaRespuesta', () => {
  it('devuelve el último mensaje de Mervall-E, no el del usuario', () => {
    const t = [{ role: 'user', content: 'a' }, { role: 'assistant', content: 'b' }, { role: 'user', content: 'c' }]
    expect(ultimaRespuesta(t).content).toBe('b')
    expect(ultimaRespuesta([])).toBe(null)
    expect(ultimaRespuesta(null)).toBe(null)
  })
})

describe('tocaSaludar — una vez por día', () => {
  const memoria = () => { const m = {}; return { getItem: (k) => m[k] ?? null, setItem: (k, v) => { m[k] = v } } }

  it('saluda la primera vez del día y no la segunda', () => {
    const s = memoria(), hoy = new Date(2026, 9, 3, 10, 0)
    expect(tocaSaludar(hoy, s)).toBe(true)
    expect(tocaSaludar(new Date(2026, 9, 3, 22, 0), s)).toBe(false)
  })

  it('al día siguiente vuelve a saludar', () => {
    const s = memoria()
    tocaSaludar(new Date(2026, 9, 3), s)
    expect(tocaSaludar(new Date(2026, 9, 4), s)).toBe(true)
  })

  it('sin almacenamiento (navegación privada que lo bloquea) no saluda ni rompe', () => {
    const roto = { getItem: () => { throw new Error('bloqueado') }, setItem: () => { throw new Error('bloqueado') } }
    expect(tocaSaludar(new Date(), roto)).toBe(false)
    expect(tocaSaludar(new Date(), null)).toBe(false)
  })
})
