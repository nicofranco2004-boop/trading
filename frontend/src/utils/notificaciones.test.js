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
    expect(textoSinPush('bloqueadas', 'iphone').cuerpo).toContain('la app Ajustes → Notificaciones → Rendi')
    expect(textoSinPush('bloqueadas', 'android').cuerpo).toContain('Configuración de sitios')
    expect(textoSinPush('bloqueadas', 'otro').cuerpo).toContain('a la izquierda de la dirección')
    // Safari de Mac no tiene ese ícono; Chrome de Mac sí (y su descripción también dice «Safari»).
    const SAFARI = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15'
    const CHROME = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36'
    expect(textoSinPush('bloqueadas', 'otro', SAFARI).cuerpo).toContain('menú de Safari → Ajustes → Sitios web')
    expect(textoSinPush('bloqueadas', 'otro', CHROME).cuerpo).toContain('a la izquierda de la dirección')
  })

  it('no promete el mail a secas: una alerta «sólo notificación» no manda mail', () => {
    for (const [m, p] of [['iphone-viejo', 'iphone'], ['navegador', 'otro'], ['navegador', 'android']]) {
      expect(textoSinPush(m, p).cuerpo).not.toContain('tus alertas te llegan por mail')
      expect(textoSinPush(m, p).cuerpo).toContain('también por mail')
    }
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
    // Alertas: el formulario (al elegir celular) y la lista (si algún aviso llega por ahí).
    'components/alerts/AlertaForm.jsx',
    'pages/Alertas.jsx',
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
