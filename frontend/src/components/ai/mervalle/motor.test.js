// El dibujo de Mervall-E, probado sin navegador: el motor arma el SVG como
// texto (dibujo) y eso alcanza para verificar las reglas que no se ven a ojo.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import { dibujo, formaPara, proporcion, eyePath, FORMAS, ESTADOS } from './motor'

const AQUI = dirname(fileURLToPath(import.meta.url))

describe('formaPara — la forma sale del tamaño', () => {
  it('visor solo hasta 20 px, cabeza hasta 48, busto hasta 110, cuerpo entero después', () => {
    expect(formaPara(16)).toBe('visor')
    expect(formaPara(20)).toBe('visor')
    expect(formaPara(21)).toBe('head')
    expect(formaPara(48)).toBe('head')
    expect(formaPara(49)).toBe('bust')
    expect(formaPara(110)).toBe('bust')
    expect(formaPara(111)).toBe('full')
  })

  it('la proporción reserva el lugar justo (cabeza cuadrada, cuerpo más alto que ancho)', () => {
    expect(proporcion('head')).toBe(1)
    expect(proporcion('full')).toBeGreaterThan(1)
    expect(proporcion('visor')).toBeLessThan(1)
  })
})

describe('dibujo — reglas del sistema de diseño', () => {
  it('ninguna forma trae colores escritos a mano (contrato R8): todo sale de clases', () => {
    for (const forma of Object.keys(FORMAS)) {
      const svg = dibujo(1, forma)
      expect(svg, forma).not.toMatch(/#[0-9A-Fa-f]{3,6}\b/)
      expect(svg, forma).not.toMatch(/rgb\(\s*\d/)
    }
  })

  it('el motor tampoco: los colores en vivo son tokens --mv-*', () => {
    const fuente = readFileSync(resolve(AQUI, 'motor.js'), 'utf8')
    expect(fuente).not.toMatch(/#[0-9A-Fa-f]{6}\b/)
    for (const t of ['--mv-ojo', '--mv-pantalla-pos', '--mv-pantalla-neg', '--mv-pantalla-warn']) {
      expect(fuente).toContain(`var(${t})`)
    }
  })

  it('dos personajes en la misma pantalla no comparten ids (si no, uno pinta con el degradé del otro)', () => {
    const ids = (s) => [...s.matchAll(/ id="([^"]+)"/g)].map((m) => m[1])
    const a = ids(dibujo(1, 'full')), b = ids(dibujo(2, 'full'))
    expect(a.length).toBeGreaterThan(3)
    expect(a.filter((x) => b.includes(x))).toEqual([])
  })

  it('cada forma lleva lo suyo: el monitor del pecho sólo donde hay pecho', () => {
    expect(dibujo(1, 'full')).toContain('mv-scr')
    expect(dibujo(1, 'bust')).toContain('mv-scr')
    expect(dibujo(1, 'screen')).toContain('mv-scr')
    expect(dibujo(1, 'head')).not.toContain('mv-scr')
    expect(dibujo(1, 'visor')).not.toContain('mv-scr')
    for (const forma of ['full', 'bust', 'head', 'visor']) expect(dibujo(1, forma), forma).toContain('mv-eye-l')
  })

  it('es decorativo: los lectores de pantalla lo saltean (el nombre lo dice el texto de al lado)', () => {
    expect(dibujo(1, 'full')).toContain('aria-hidden="true"')
  })
})

describe('ESTADOS — los 13 de la propuesta aprobada', () => {
  it('están todos, con cara y gráfico del pecho', () => {
    const esperados = ['reposo', 'saludo', 'escuchando', 'pensando', 'hablando', 'contento', 'atento',
      'serio', 'sorpresa', 'confundido', 'durmiendo', 'festejo', 'cargando']
    expect(Object.keys(ESTADOS).sort()).toEqual([...esperados].sort())
    for (const n of esperados) {
      expect(ESTADOS[n].eyes, n).toBeTruthy()
      expect(ESTADOS[n].scr, n).toBeTruthy()
    }
  })
})

describe('eyePath — los ojos', () => {
  const ojo = { w: 17, h: 12, ti: 1, to: 1, bi: 1, bo: 1, r: 0 }
  it('un ojo abierto es una figura cerrada con alto', () => {
    const d = eyePath(ojo, false, 1, 1, 1)
    expect(d.startsWith('M')).toBe(true)
    expect(d.endsWith('Z')).toBe(true)
    expect(d).not.toContain('NaN')
  })
  it('parpadear achata el ojo (los puntos de control se acercan a la línea del medio)', () => {
    const alto = (d) => Math.max(...d.match(/-?\d+(\.\d+)?/g).map(Number).map(Math.abs).filter((v) => v !== 8.5))
    expect(alto(eyePath(ojo, false, 0.1, 1, 1))).toBeLessThan(alto(eyePath(ojo, false, 1, 1, 1)))
  })
})
