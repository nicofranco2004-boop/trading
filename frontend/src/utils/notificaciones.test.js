// Por qué no se pueden activar las notificaciones, y qué se le dice a la persona.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { motivoSinPush, textoSinPush } from './notificaciones'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')

describe('motivoSinPush', () => {
  const casos = [
    // [qué dispositivo, entrada, motivo]
    ['compu con Chrome', { supported: true, permission: 'default', plataforma: 'otro', instalada: false }, null],
    ['Android con Chrome', { supported: true, permission: 'granted', plataforma: 'android', instalada: false }, null],
    ['iPhone instalada (iOS 16.4+)', { supported: true, permission: 'default', plataforma: 'iphone', instalada: true }, null],
    ['iPhone en Safari', { supported: false, permission: 'default', plataforma: 'iphone', instalada: false }, 'iphone-sin-instalar'],
    ['iPhone instalada pero viejo', { supported: false, permission: 'default', plataforma: 'iphone', instalada: true }, 'iphone-viejo'],
    ['compu sin soporte', { supported: false, permission: 'default', plataforma: 'otro', instalada: false }, 'navegador'],
    ['dijo que no', { supported: true, permission: 'denied', plataforma: 'otro', instalada: false }, 'bloqueadas'],
  ]
  for (const [nombre, entrada, motivo] of casos) {
    it(nombre, () => expect(motivoSinPush(entrada)).toBe(motivo))
  }
})

describe('textoSinPush', () => {
  it('el botón al paso a paso aparece donde instalar es la salida', () => {
    expect(textoSinPush('iphone-sin-instalar', 'iphone').boton).toBe('Ver cómo agregarla')
    expect(textoSinPush('navegador', 'otro').boton).toBe('Ver cómo agregarla')
    expect(textoSinPush('navegador', 'android').boton).toBe(null)
    expect(textoSinPush('iphone-viejo', 'iphone').boton).toBe(null)
    expect(textoSinPush('bloqueadas', 'otro').boton).toBe(null)
  })

  it('bloqueadas: dice dónde tocar en SU dispositivo', () => {
    expect(textoSinPush('bloqueadas', 'iphone').cuerpo).toContain('Ajustes del iPhone')
    expect(textoSinPush('bloqueadas', 'android').cuerpo).toContain('Configuración de sitios')
    expect(textoSinPush('bloqueadas', 'otro').cuerpo).toContain('a la izquierda de la dirección')
  })

  it('sin motivo no hay cartel', () => expect(textoSinPush(null, 'otro')).toBe(null))

  it('ningún texto habla en jerga', () => {
    for (const m of ['iphone-sin-instalar', 'iphone-viejo', 'navegador', 'bloqueadas']) {
      for (const p of ['iphone', 'android', 'otro']) {
        const { titulo, cuerpo } = textoSinPush(m, p)
        expect(`${titulo} ${cuerpo}`).not.toMatch(/\b(push|browser|VAPID|PWA|service worker|device)\b/i)
      }
    }
  })
})

describe('las pantallas que ofrecen «Activar» usan el mismo cartel', () => {
  // Antes cada una tenía su frase propia, y dos pedían el permiso sin esperar
  // la respuesta: si salía mal, nadie se enteraba.
  const PANTALLAS = [
    'components/home/OnboardingChecklist.jsx',
    'pages/More.jsx',
    'components/alerts/AlertsManager.jsx',
    'components/advisor/ClientMoveAlert.jsx',
  ]
  for (const f of PANTALLAS) {
    it(f, () => {
      const src = readFileSync(join(SRC, f), 'utf8')
      expect(src).toContain('<AvisoNotificaciones')
      expect(src).not.toMatch(/subscribe\?\.\(\)/)        // pedido sin esperar respuesta
      expect(src).not.toMatch(/toast\?\.show\?\./)        // función que no existe
    })
  }
})
