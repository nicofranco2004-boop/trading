import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import InstalarAppModal, { PASOS_IPHONE, PASOS_ANDROID } from './InstalarAppModal.jsx'
import {
  plataformaDe, yaInstalada, escucharInstalador, hayInstalador, instalarAhora,
} from '../utils/instalarApp.js'

// «Descargar app»: el cartel que explica cómo dejar Rendi en la pantalla de
// inicio. Lo que se cuida acá es que el cartel le hable al celular correcto y
// que las cuatro fotos existan — una foto que falta no rompe nada a la vista
// del programador: el hosting contesta la página de inicio en su lugar y el
// usuario ve un recuadro vacío.

const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1'
const SAMSUNG = 'Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36'
const MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15'
const WINDOWS = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

function dibujar(navegador) {
  vi.stubGlobal('navigator', navegador)
  return renderToStaticMarkup(<InstalarAppModal open onClose={() => {}} />)
}
const texto = (html) => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()

afterEach(() => vi.unstubAllGlobals())

describe('plataformaDe — qué celular tiene', () => {
  it('reconoce iPhone, Android y computadora', () => {
    expect(plataformaDe({ userAgent: IPHONE, maxTouchPoints: 5 })).toBe('iphone')
    expect(plataformaDe({ userAgent: SAMSUNG, maxTouchPoints: 5 })).toBe('android')
    expect(plataformaDe({ userAgent: MAC, maxTouchPoints: 0 })).toBe('otro')
    expect(plataformaDe({ userAgent: WINDOWS, maxTouchPoints: 0 })).toBe('otro')
  })

  it('el iPad se presenta como Mac: lo delata la pantalla táctil', () => {
    expect(plataformaDe({ userAgent: MAC, maxTouchPoints: 5 })).toBe('iphone')
  })

  it('sin datos no revienta: computadora', () => {
    expect(plataformaDe()).toBe('otro')
    expect(plataformaDe({ userAgent: null })).toBe('otro')
  })
})

describe('yaInstalada — no ofrecer instalar lo que ya está', () => {
  const ventana = ({ standalone, modo }) => ({
    navigator: { standalone },
    matchMedia: (q) => ({ matches: q === '(display-mode: standalone)' && modo === 'standalone' }),
  })

  it('iPhone abierto desde el ícono', () => {
    expect(yaInstalada(ventana({ standalone: true, modo: 'browser' }))).toBe(true)
  })
  it('Android abierto desde el ícono', () => {
    expect(yaInstalada(ventana({ standalone: undefined, modo: 'standalone' }))).toBe(true)
  })
  it('una pestaña común del navegador', () => {
    expect(yaInstalada(ventana({ standalone: false, modo: 'browser' }))).toBe(false)
  })
  it('un navegador sin matchMedia no revienta', () => {
    expect(yaInstalada({ navigator: {} })).toBe(false)
    expect(yaInstalada(undefined)).toBe(false)
  })
})

describe('el cartel le habla al celular que tiene delante', () => {
  it('en iPhone abre en iPhone, con las cuatro fotos y sin el aviso de la compu', () => {
    const html = dibujar({ userAgent: IPHONE, maxTouchPoints: 5 })
    expect((html.match(/<img /g) || []).length).toBe(PASOS_IPHONE.length)
    expect(texto(html)).toContain('Agregar a inicio')
    expect(texto(html)).not.toContain('Estos pasos se hacen en el celular')
  })

  it('en Android abre en Android: nombra a Chrome y no muestra fotos de Safari', () => {
    const html = dibujar({ userAgent: SAMSUNG, maxTouchPoints: 5 })
    expect(texto(html)).toContain('en Chrome')
    expect(texto(html)).toContain('Agregar a pantalla principal')
    expect(texto(html)).not.toContain('Safari')
    expect(texto(html)).not.toContain('Estos pasos se hacen en el celular')
  })

  it('en la computadora abre en iPhone y avisa que los pasos van en el celular', () => {
    const html = dibujar({ userAgent: WINDOWS, maxTouchPoints: 0 })
    expect(texto(html)).toContain('Estos pasos se hacen en el celular')
    expect(texto(html)).toContain('en Safari')
  })

  it('cerrado no dibuja nada', () => {
    vi.stubGlobal('navigator', { userAgent: IPHONE })
    expect(renderToStaticMarkup(<InstalarAppModal open={false} onClose={() => {}} />)).toBe('')
  })
})

describe('las fotos y el recuadro violeta', () => {
  const carpeta = join(dirname(fileURLToPath(import.meta.url)), '../assets/instalar')

  it('las cuatro capturas de iPhone existen y son JPEG de verdad', () => {
    for (const n of [1, 2, 3, 4]) {
      const ruta = join(carpeta, `iphone-${n}.jpg`)
      expect(existsSync(ruta), ruta).toBe(true)
      const b = readFileSync(ruta)
      expect([b[0], b[1]]).toEqual([0xff, 0xd8])
    }
  })

  it('cada paso de iPhone tiene foto, descripción y un recuadro DENTRO de la foto', () => {
    expect(PASOS_IPHONE).toHaveLength(4)
    for (const p of PASOS_IPHONE) {
      expect(p.foto).toBeTruthy()
      expect(p.alt.length).toBeGreaterThan(10)
      const n = (k) => parseFloat(p.marco[k])
      expect(n('left')).toBeGreaterThanOrEqual(0)
      expect(n('top')).toBeGreaterThanOrEqual(0)
      expect(n('left') + n('width')).toBeLessThanOrEqual(100)
      expect(n('top') + n('height')).toBeLessThanOrEqual(100)
    }
  })

  it('Android tiene sus cuatro pasos', () => {
    expect(PASOS_ANDROID).toHaveLength(4)
  })
})

describe('instalar de un toque (Chrome en Android)', () => {
  function ventanaFalsa() {
    const oyentes = {}
    return {
      addEventListener: (tipo, f) => { oyentes[tipo] = f },
      disparar: (tipo, e) => oyentes[tipo]?.(e),
    }
  }

  it('sin aviso del navegador no hay botón, y pedirlo no revienta', async () => {
    expect(hayInstalador()).toBe(false)
    expect(await instalarAhora()).toBe('no-disponible')
  })

  it('guarda el aviso SIN apagar la barrita propia de Chrome, y lo usa una sola vez', async () => {
    const win = ventanaFalsa()
    escucharInstalador(win)
    const aviso = {
      preventDefault: vi.fn(),
      prompt: vi.fn(async () => {}),
      userChoice: Promise.resolve({ outcome: 'accepted' }),
    }
    win.disparar('beforeinstallprompt', aviso)
    expect(hayInstalador()).toBe(true)
    expect(aviso.preventDefault).not.toHaveBeenCalled()

    expect(await instalarAhora()).toBe('accepted')
    expect(aviso.prompt).toHaveBeenCalledTimes(1)
    expect(hayInstalador()).toBe(false)
    expect(await instalarAhora()).toBe('no-disponible')
  })

  it('si la instalación termina por otro lado, el botón se va', () => {
    const win = ventanaFalsa()
    escucharInstalador(win)
    win.disparar('beforeinstallprompt', { prompt: async () => {}, userChoice: Promise.resolve({ outcome: 'dismissed' }) })
    expect(hayInstalador()).toBe(true)
    win.disparar('appinstalled', {})
    expect(hayInstalador()).toBe(false)
  })
})
