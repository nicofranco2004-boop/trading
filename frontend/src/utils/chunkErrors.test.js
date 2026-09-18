import { describe, it, expect } from 'vitest'
import { isChunkLoadError, urlsAReparar, repararAssets } from './chunkErrors.js'

// Cada string de acá es el mensaje TEXTUAL de un motor real, no una paráfrasis.
// Si un patrón se escribe "de memoria" y el motor dice otra cosa, la reparación
// automática no arranca y el usuario ve la pantalla de "Se rompió esta pantalla".
// Eso es exactamente lo que pasó en Safari hasta 2026-09-16.
describe('isChunkLoadError — el mensaje real de cada navegador', () => {
  it('Safari: el mensaje EXACTO que se vio en producción (2026-09-16)', () => {
    expect(isChunkLoadError("'text/html' is not a valid JavaScript MIME type.")).toBe(true)
  })

  it('Chrome: module script con MIME text/html', () => {
    expect(isChunkLoadError(
      'Failed to load module script: Expected a JavaScript module script but the ' +
      'server responded with a MIME type of "text/html". Strict MIME type checking ' +
      'is enforced for module scripts per HTML spec.',
    )).toBe(true)
  })

  it('Firefox: module bloqueado por MIME', () => {
    expect(isChunkLoadError(
      'Loading module from "https://rendi.finance/assets/Home-x.js" was blocked ' +
      'because of a disallowed MIME type ("text/html").',
    )).toBe(true)
  })

  it('Vite: el chunk no bajó', () => {
    expect(isChunkLoadError(
      'Failed to fetch dynamically imported module: https://rendi.finance/assets/Home-x.js',
    )).toBe(true)
    expect(isChunkLoadError(
      'error loading dynamically imported module: https://rendi.finance/assets/Home-x.js',
    )).toBe(true)
  })

  it('Chrome viejo: script clásico no ejecutable', () => {
    expect(isChunkLoadError(
      "Refused to execute script because its MIME type ('text/html') is not executable",
    )).toBe(true)
  })

  it('NO confunde un error común de la app con un chunk roto', () => {
    expect(isChunkLoadError("Cannot read properties of undefined (reading 'map')")).toBe(false)
    expect(isChunkLoadError('NetworkError when attempting to fetch resource.')).toBe(false)
    expect(isChunkLoadError(undefined)).toBe(false)
    expect(isChunkLoadError(null)).toBe(false)
    expect(isChunkLoadError('')).toBe(false)
  })
})

describe('urlsAReparar — qué se manda a reparar', () => {
  const origin = 'https://rendi.finance'

  it('la URL que viene DENTRO del mensaje va primera: es la que realmente falló', () => {
    const urls = urlsAReparar({
      mensaje: 'Failed to fetch dynamically imported module: https://rendi.finance/assets/Home-x.js',
      recursos: ['https://rendi.finance/assets/react-y.js'],
      origin,
    })
    expect(urls[0]).toBe('https://rendi.finance/assets/Home-x.js')
    expect(urls).toContain('https://rendi.finance/assets/react-y.js')
  })

  it('Safari no pone la URL en el mensaje: igual repara por lo que la página pidió', () => {
    const urls = urlsAReparar({
      mensaje: "'text/html' is not a valid JavaScript MIME type.",
      recursos: ['https://rendi.finance/assets/Home-x.js', 'https://rendi.finance/assets/app-z.css'],
      origin,
    })
    expect(urls).toEqual([
      'https://rendi.finance/assets/Home-x.js',
      'https://rendi.finance/assets/app-z.css',
    ])
  })

  it('NO toca nada que no sea un archivo de build de este dominio', () => {
    const urls = urlsAReparar({
      mensaje: '',
      recursos: [
        'https://rendi.finance/api/positions',            // el backend, no
        'https://www.google-analytics.com/assets/g.js',    // otro dominio, no
        'https://rendi.finance/og-image.png',              // no está en /assets/
        'https://rendi.finance/assets/Home-x.js',          // sí
      ],
      origin,
    })
    expect(urls).toEqual(['https://rendi.finance/assets/Home-x.js'])
  })

  it('no repite y no se pasa del tope', () => {
    const muchas = Array.from({ length: 60 }, (_, i) => `${origin}/assets/c${i}.js`)
    const urls = urlsAReparar({ mensaje: '', recursos: [...muchas, ...muchas], origin, max: 40 })
    expect(urls).toHaveLength(40)
    expect(new Set(urls).size).toBe(40)
  })
})

describe('repararAssets — cómo pide los archivos', () => {
  it('pide SIEMPRE con cache:reload — un fetch normal devuelve el HTML envenenado del cache', async () => {
    const pedidos = []
    const fetchImpl = (u, o) => { pedidos.push([u, o]); return Promise.resolve({ ok: true }) }
    const n = await repararAssets(['https://rendi.finance/assets/Home-x.js'], { fetchImpl })
    expect(n).toBe(1)
    expect(pedidos[0][1].cache).toBe('reload')
  })

  it('si la red no contesta, no deja al usuario colgado', async () => {
    const fetchImpl = () => new Promise(() => {})   // nunca resuelve
    const t0 = Date.now()
    await repararAssets(['https://rendi.finance/assets/Home-x.js'], { fetchImpl, timeoutMs: 40 })
    expect(Date.now() - t0).toBeLessThan(1000)
  })

  it('sin URLs no hace nada', async () => {
    let llamado = false
    await repararAssets([], { fetchImpl: () => { llamado = true } })
    expect(llamado).toBe(false)
  })
})
