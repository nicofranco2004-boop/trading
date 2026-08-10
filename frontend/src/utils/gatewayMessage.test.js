// El cartel de 502/503/504 le prometía al usuario algo que no podíamos cumplir:
//
//   "El servidor se está reiniciando — suele tardar menos de un minuto.
//    Probá de nuevo."
//
// El 2026-08-10 el backend NO estaba reiniciando: estaba colgado (la migración
// de arranque se quedaba con el lock de escritura de SQLite y el threadpool se
// llenaba). Duró bastante más de un minuto. Y "probá de nuevo" sobre una
// ESCRITURA es consejo peligroso: un 502 no dice si el servidor llegó a
// procesar — un usuario reintentó una cancelación de suscripción que ya había
// ocurrido.
//
// Estos tests fijan las dos reglas: no prometer duración, y no tratar igual a
// leer que a escribir.
import { describe, it, expect } from 'vitest'
import { gatewayMessage } from './api'

describe('mensaje de gateway — no promete lo que no sabe', () => {
  const todos = [gatewayMessage({ write: true }), gatewayMessage({ write: false }), gatewayMessage()]

  it('NUNCA promete una duración', () => {
    // El corazón del bug: "menos de un minuto" era falso y mandaba a la gente a
    // esperar en vez de a reportarlo.
    for (const m of todos) {
      expect(m).not.toMatch(/minuto s?\b.*menos|menos de un minuto/i)
      expect(m).not.toMatch(/suele tardar/i)
      expect(m).not.toMatch(/se está reiniciando/i)
    }
  })

  it('ningún mensaje queda vacío ni dice "HTTP 502"', () => {
    for (const m of todos) {
      expect(typeof m).toBe('string')
      expect(m.length).toBeGreaterThan(20)
      expect(m).not.toMatch(/HTTP \d/)
    }
  })
})

describe('leer y escribir no se avisan igual', () => {
  it('ESCRITURA: admite que no sabemos si se completó, y no manda a repetir a ciegas', () => {
    const m = gatewayMessage({ write: true })
    expect(m).toMatch(/no sabemos si/i)
    expect(m).toMatch(/revisá el estado/i)
  })

  it('LECTURA: puede sugerir recargar, porque repetir un GET no rompe nada', () => {
    const m = gatewayMessage({ write: false })
    expect(m).toMatch(/recarg/i)
  })

  it('los dos casos dan mensajes DISTINTOS', () => {
    // Si volvieran a colapsar en uno solo, se pierde justamente la distinción
    // que causó el reintento de la cancelación.
    expect(gatewayMessage({ write: true })).not.toBe(gatewayMessage({ write: false }))
  })

  it('sin contexto cae en el mensaje de lectura (el conservador para el usuario)', () => {
    expect(gatewayMessage()).toBe(gatewayMessage({ write: false }))
  })

  it('la escritura deja una salida: a quién escribirle o cuándo reintentar', () => {
    // Un error sin próximo paso deja a la persona trabada. Lectura → soporte;
    // escritura → reintentar después de verificar.
    expect(gatewayMessage({ write: false })).toMatch(/soporte/i)
    expect(gatewayMessage({ write: true })).toMatch(/volvé a intentar/i)
  })
})
