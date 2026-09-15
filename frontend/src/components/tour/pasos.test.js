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
    // Los pasos de Alertas: el resumen diario del mercado (lo nuevo) y los
    // avisos de precio (lo que ya estaba).
    '../alerts/MarketBriefPrefs.jsx', '../alerts/AlertsManager.jsx',
  ].map(leer).join('\n')

  it('todas las marcas existen en la pantalla', () => {
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

  it('el paseo termina en Alertas, y primero lo nuevo', () => {
    // Orden pedido por Nico: el resumen del mercado es la novedad, así que va
    // antes que los avisos de precio, que ya existían. Si alguien los da
    // vuelta, el tutorial presenta como noticia algo que el usuario ya tenía.
    const ids = PASOS.map(p => p.id)
    expect(ids.indexOf('resumen-mercado')).toBeLessThan(ids.indexOf('alertas-precio'))
    expect(ids.slice(-2)).toEqual(['resumen-mercado', 'alertas-precio'])
  })

  it('los pasos de Alertas llevan a /alertas', () => {
    // Sin ruta, el tutorial los explicaría desde donde esté el usuario: iría a
    // buscar un interruptor que no está en pantalla y saltearía los dos pasos.
    for (const id of ['resumen-mercado', 'alertas-precio']) {
      expect(PASOS.find(p => p.id === id).ruta, id).toBe('/alertas')
    }
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

  it('el cartel tiene una punta que apunta a lo resaltado', () => {
    // El cartel se centra bajo lo resaltado, PERO si eso lo dejaría fuera de
    // la pantalla el recorte lo empuja hacia adentro. Con el interruptor del
    // resumen del mercado —pegado al borde derecho— el cartel terminaba 131px
    // corrido y se leía como un cartel suelto que no apunta a nada. Moverlo no
    // es opción: no hay lugar. La punta es lo que mantiene la conexión.
    expect(tour).toMatch(/rotate-45/)
    expect(tour).toMatch(/const puntaX =/)
    // Y se limita para no salirse por las esquinas redondeadas del cartel.
    expect(tour).toMatch(/Math\.min\(Math\.max\(20,[\s\S]{0,80}cartelAncho - 32\)/)
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
