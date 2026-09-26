/**
 * El demo no deja salir nada al backend real, no dice "listo" a lo que no guarda
 * y no atrapa a nadie para siempre.
 *
 * Lo medido el 2026-09-25 en producción, como visitante sin sesión:
 *   · Movimientos mostraba "Unauthorized" y Alertas "No pudimos leer tu
 *     configuración": 11 GET que el demo no conocía salían al backend.
 *   · Con una cuenta real abierta en el mismo navegador, esos GET traían SUS
 *     datos (sus movimientos, sus plazos fijos sumados al total del demo).
 *   · 95 escrituras contestaban "listo" sin guardar nada; "Suscribirme"
 *     terminaba en "No pudimos generar el checkout".
 *   · Quien volvía otro día a rendi.finance veía el demo, no la portada.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { handleDemoRequest, demoVencido, DEMO_DURA_MS, enableDemoMode, isDemoMode, vencerDemoSiCorresponde } from './demo.js'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

// Los que se escapaban, con la forma que lee cada pantalla.
const LOS_ONCE = [
  ['/movements', r => Array.isArray(r) && r.length > 0],
  ['/plazos-fijos', r => Array.isArray(r)],
  ['/futures', r => Array.isArray(r)],
  ['/bonds/cashflow/skips', r => Array.isArray(r)],
  ['/positions/split-check', r => Array.isArray(r.suggestions)],
  ['/sections/archived', r => Array.isArray(r.archived)],
  ['/market-brief/prefs', r => typeof r.enabled === 'boolean'],
  ['/me/advisor', r => Array.isArray(r.advisors) && Array.isArray(r.requests)],
  ['/wallbit/status', r => r.connected === false],
  ['/advisor/alerts', r => Array.isArray(r.history)],
  ['/fx-rates', r => Array.isArray(r) && r.every(f => f.date && f.blue > 0)],
]

describe('el demo contesta lo que piden sus pantallas', () => {
  for (const [path, formaOk] of LOS_ONCE) {
    it(`GET ${path}`, () => {
      const r = handleDemoRequest('GET', path)
      expect(r, `${path} caía al backend real`).not.toBeNull()
      expect(formaOk(r)).toBe(true)
    })
  }

  it('Movimientos cuenta la misma historia que las operaciones cerradas', () => {
    const movs = handleDemoRequest('GET', '/movements')
    const ops = handleDemoRequest('GET', '/operations')
    const ventas = movs.filter(m => m.type === 'SELL')
    expect(ventas).toHaveLength(ops.length)
    const pnl = (xs) => xs.reduce((s, x) => s + (x.pnl_usd || 0), 0)
    expect(pnl(ventas)).toBeCloseTo(pnl(ops), 6)
    expect(movs.some(m => m.type === 'DEPOSIT')).toBe(true)
  })
})

describe('en demo, un GET desconocido no sale a la red', () => {
  it('api.get tira el error del demo sin llamar a fetch', async () => {
    vi.stubGlobal('window', Object.assign(Object.create(globalThis), { addEventListener() {}, removeEventListener() {} }))
    vi.stubGlobal('localStorage', { getItem: (k) => (k === 'rendi_demo_mode' ? String(Date.now()) : null), setItem() {}, removeItem() {} })
    const fetchEspia = vi.fn(() => Promise.resolve(new Response('{}')))
    vi.stubGlobal('fetch', fetchEspia)
    const { api } = await import('./api.js')
    await expect(api.get('/algo-que-el-demo-no-conoce')).rejects.toMatchObject({ demoBlocked: true })
    expect(fetchEspia).not.toHaveBeenCalled()
  })
})

describe('lo que el visitante guarda a mano se bloquea; lo de fondo, no', () => {
  const bloqueada = (m, p) => handleDemoRequest(m, p, {})?.__demoBlocked === true
  it.each([
    ['POST', '/cash/flow'], ['POST', '/alerts'], ['PATCH', '/alerts/7'], ['DELETE', '/alerts/7'],
    ['POST', '/goals'], ['PUT', '/goals/3'], ['POST', '/plazos-fijos'], ['POST', '/futures'],
    ['POST', '/wallbit/connect'], ['PATCH', '/market-brief/prefs'], ['POST', '/billing/subscribe'],
    ['POST', '/billing/trial/start'], ['DELETE', '/movements/me-1-dep'], ['PATCH', '/positions/group'],
    ['POST', '/positions/12/adjust-ratio'], ['POST', '/monthly'], ['DELETE', '/me'],
  ])('%s %s → "creá una cuenta"', (m, p) => {
    expect(bloqueada(m, p)).toBe(true)
  })
  it.each([
    ['POST', '/snapshots'], ['POST', '/monthly/sync-unrealized'], ['POST', '/plan/track'],
    ['POST', '/alerts/events/seen'], ['POST', '/auth/logout'],
  ])('%s %s sigue en silencio (nadie la pidió a mano)', (m, p) => {
    expect(bloqueada(m, p)).toBe(false)
  })
  it('agregar a la watchlist y registrar una posición siguen funcionando en el demo', () => {
    expect(bloqueada('POST', '/watchlist')).toBe(false)
    expect(bloqueada('POST', '/positions')).toBe(false)
  })
})

describe('el modo demo vence', () => {
  it('la marca vieja, sin fecha, está vencida', () => {
    expect(demoVencido('1')).toBe(true)
  })
  it('recién activada no está vencida; pasadas 12 horas, sí', () => {
    const ahora = Date.now()
    expect(demoVencido(String(ahora - 60_000), ahora)).toBe(false)
    expect(demoVencido(String(ahora - DEMO_DURA_MS - 1), ahora)).toBe(true)
  })
  it('sin marca no hay nada que vencer', () => {
    expect(demoVencido(null)).toBe(false)
  })
})

describe('entrar al demo y seguir en el demo (el formato nuevo de la marca)', () => {
  const almacen = () => {
    const m = new Map()
    return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k) }
  }
  it('después de enableDemoMode, isDemoMode dice que sí (y al reabrir la app, también)', () => {
    // La primera versión guardaba la fecha pero isDemoMode seguía esperando '1':
    // el demo entero habría dejado de funcionar.
    vi.stubGlobal('window', globalThis)
    vi.stubGlobal('localStorage', almacen())
    enableDemoMode()
    expect(isDemoMode()).toBe(true)
    expect(vencerDemoSiCorresponde()).toBe(false)
    expect(isDemoMode()).toBe(true)
  })
  it('una marca vieja se limpia al abrir la app y deja ver la portada', () => {
    vi.stubGlobal('window', globalThis)
    const ls = almacen()
    ls.setItem('rendi_demo_mode', '1')
    vi.stubGlobal('localStorage', ls)
    expect(vencerDemoSiCorresponde()).toBe(true)
    expect(isDemoMode()).toBe(false)
  })
})

