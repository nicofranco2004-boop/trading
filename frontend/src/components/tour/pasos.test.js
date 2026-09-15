import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { PASOS, ATRIBUTO, yaLoVio, marcarVisto, CLAVE_VISTO } from './pasos'

const leer = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')

// ─── Que lo que el tutorial promete resaltar EXISTA ─────────────────────────
// Un paso que apunta a algo que no está deja al usuario mirando una pantalla
// oscura con un agujero en la nada. El tutorial lo saltea solo —está hecho para
// eso— pero entonces la novedad no se explica y nadie se entera.
//
// Esto ata cada paso con la marca puesta en el código de la pantalla.
describe('cada paso resalta algo que está de verdad', () => {
  const FUENTES = [
    '../voz/RendiMate.jsx', '../voz/BotonMicrofono.jsx',
    '../AICoach.jsx', '../../pages/RendiAI.jsx',
  ].map(leer).join('\n')

  it('las cuatro marcas existen en la pantalla', () => {
    const sinMarcar = PASOS.filter(p => !FUENTES.includes(`${ATRIBUTO}="${p.marca}"`))
    expect(sinMarcar.map(p => p.id)).toEqual([])
  })

  it('cada paso dice a dónde va y qué cuenta', () => {
    for (const p of PASOS) {
      expect(p.id, 'id').toBeTruthy()
      expect(p.titulo.length, p.id).toBeGreaterThan(8)
      expect(p.texto.length, p.id).toBeGreaterThan(40)
    }
  })

  it('el primero no mueve al usuario de donde está', () => {
    // Arranca donde esté: sacarlo de la pantalla que estaba mirando antes de
    // explicarle nada es empezar desorientándolo.
    expect(PASOS[0].ruta).toBeNull()
  })
})

describe('se muestra una vez y se puede omitir', () => {
  it('si el almacenamiento no se puede leer, NO se muestra', () => {
    // Mejor no mostrarlo que mostrárselo en loop a alguien que no lo puede
    // apagar — sin almacenamiento, "omitir" no se podría recordar.
    const roto = { getItem() { throw new Error('bloqueado') } }
    expect(yaLoVio(roto)).toBe(true)
  })

  it('marcarlo visto no revienta sin almacenamiento', () => {
    const roto = { setItem() { throw new Error('bloqueado') } }
    expect(() => marcarVisto(roto)).not.toThrow()
  })

  it('recuerda que ya lo vio', () => {
    const guardado = {}
    const almacen = { getItem: k => guardado[k] ?? null, setItem: (k, v) => { guardado[k] = v } }
    expect(yaLoVio(almacen)).toBe(false)
    marcarVisto(almacen)
    expect(yaLoVio(almacen)).toBe(true)
    expect(guardado[CLAVE_VISTO]).toBe('1')
  })
})

describe('el tutorial no puede dejar la pantalla trabada', () => {
  const tour = leer('./TourNovedades.jsx')

  it('si no encuentra qué resaltar, saltea el paso', () => {
    expect(tour).toMatch(/if \(esperado >= ESPERA_MAX\) \{ setCaja\(null\); avanzar\(\) \}/)
  })

  it('siempre hay cómo salir', () => {
    expect(tour).toMatch(/Omitir/)
    expect(tour).toMatch(/onClick=\{cerrar\}/)
  })

  it('lo resaltado no se puede tocar', () => {
    // Si el usuario aprieta el botón iluminado se va del paseo a mitad de
    // camino y el tutorial queda hablando de algo que ya no está.
    expect(tour).toMatch(/pointer-events-none/)
  })

  it('va adentro de la red que impide que se lleve la pantalla', () => {
    const app = leer('../../App.jsx')
    expect(app).toMatch(/<IslaSegura[\s\S]{0,400}<TourNovedades \/>/)
  })
})
