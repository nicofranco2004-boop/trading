// Guard del catálogo de uso + el envío en tandas.
//
// 1. Todo `track('algo')` del código tiene nombre legible en usoCatalogo.js.
//    Sin esto, un botón nuevo aparece en el panel /admin con su nombre interno
//    —o, peor, alguien lo agrega a una lista y no a la otra y deja de contarse.
// 2. Lo marcado `soloGA` existe de verdad como trackEvent() y NO como track():
//    si estuviera por los dos caminos se contaría dos veces.
// 3. utils/uso.js: suma en memoria, manda sólo con sesión, una vez por día
//    "abrió la app", y las pantallas con nombre fijo (sin el dato de la URL).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { EVENTOS, NO_SE_CUENTAN, pantallaDe, nombreDeUso, claveDeUso } from './usoCatalogo'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')

function archivos(dir) {
  const out = []
  for (const n of readdirSync(dir)) {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) out.push(...archivos(p))
    else if (/\.(jsx?|tsx?)$/.test(n) && !/\.test\./.test(n)) out.push(p)
  }
  return out
}

function llamadasEn(evento) {
  const out = new Set()
  for (const f of archivos(SRC)) {
    if (readFileSync(f, 'utf8').includes(`track('${evento}'`)) out.add(f.slice(SRC.length + 1))
  }
  return out
}

function llamadas(fn) {
  const re = new RegExp(`\\b${fn}\\(\\s*['"]([a-z_]+)['"]`, 'g')
  const out = new Map()
  for (const f of archivos(SRC)) {
    const txt = readFileSync(f, 'utf8')
    for (const m of txt.matchAll(re)) {
      if (!out.has(m[1])) out.set(m[1], f.slice(SRC.length + 1))
    }
  }
  return out
}

describe('catálogo de uso', () => {
  const tracks = llamadas('track')
  const gas = llamadas('trackEvent')

  it('todo track() del código tiene nombre legible', () => {
    const faltan = [...tracks].filter(([ev]) => !EVENTOS[ev] && !NO_SE_CUENTAN.has(ev))
    expect(faltan, 'agregalos a utils/usoCatalogo.js').toEqual([])
  })

  it('lo marcado soloGA se manda por trackEvent y no por track (no se cuenta doble)', () => {
    for (const [ev, e] of Object.entries(EVENTOS)) {
      if (!e.soloGA) continue
      expect(gas.has(ev), `${ev} no aparece como trackEvent()`).toBe(true)
      expect(tracks.has(ev), `${ev} también es track(): se contaría dos veces`).toBe(false)
    }
  })

  it('los nombres respetan la forma que acepta el servidor', () => {
    // backend: _USO_EVENTO_RE
    const re = /^(?:(?:vista:)?[a-z][a-z0-9_]{1,47}|pantalla:\/[a-z0-9_/-]{0,40})$/
    for (const ev of Object.keys(EVENTOS)) expect(re.test(claveDeUso(ev)), ev).toBe(true)
    for (const p of ['/', '/posiciones', '/posiciones/12', '/activo/GGAL', '/config/notificaciones', '/importar-historiales']) {
      const k = pantallaDe(p)
      expect(k && re.test(k), `${p} → ${k}`).toBe(true)
    }
  })

  it('las pantallas no llevan el dato de la URL', () => {
    expect(pantallaDe('/activo/GGAL')).toBe('pantalla:/activo')
    expect(pantallaDe('/posiciones/123')).toBe('pantalla:/posiciones/detalle')
    expect(pantallaDe('/posiciones')).toBe('pantalla:/posiciones')
    expect(pantallaDe('/config/notificaciones')).toBe('pantalla:/config')
    expect(pantallaDe('/configurar')).toBe(null)
    expect(pantallaDe('/blog/fifo-cedears-argentina')).toBe(null)
    expect(nombreDeUso('pantalla:/posiciones').label).toBe('Cartera')
    expect(nombreDeUso('moneda_cambiada').label).toBe('Cambió USD / Pesos')
    expect(nombreDeUso('vista:paywall_muro_visto').label).toBe('Vio el muro de elegir plan')
    expect(claveDeUso('paywall_muro_visto')).toBe('vista:paywall_muro_visto')
    expect(claveDeUso('moneda_cambiada')).toBe('moneda_cambiada')
  })

  it('una acción, un nombre: nada del catálogo dice «sólo celular» si existe en la compu', () => {
    // Auditoría 2026-10-08: el efectivo se llamaba distinto en cada pantalla y
    // salían dos filas en el ranking; borrar/vender/empezar a agregar sólo se
    // medían en el celular.
    for (const ev of ['cash_flow_recorded', 'position_add_started', 'position_sell_started', 'position_deleted', 'ai_analyze_opened']) {
      const donde = [...llamadasEn(ev)]
      expect(donde.some(f => f.includes('PositionsMobile')), `${ev} en el celular`).toBe(true)
      expect(donde.some(f => f.endsWith('pages/Positions.jsx') || f.includes('components/ai/')), `${ev} en la compu`).toBe(true)
    }
  })
})

describe('envío en tandas', () => {
  let uso
  beforeEach(async () => {
    vi.resetModules()
    vi.useFakeTimers()
    globalThis.fetch = vi.fn(() => Promise.resolve({ ok: true }))
    // El repo no trae un navegador simulado: alcanza con lo que uso.js toca.
    const win = new EventTarget()
    win.location = { pathname: '/' }
    globalThis.window = win
    const doc = new EventTarget()
    doc.visibilityState = 'visible'
    globalThis.document = doc
    uso = await import('./uso')
  })

  const cuerpo = (i = 0) => JSON.parse(globalThis.fetch.mock.calls[i][1].body).eventos

  it('sin sesión no junta ni manda nada', () => {
    uso.registrarUso('position_add_completed')
    vi.advanceTimersByTime(60_000)
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  const tocar = () => window.dispatchEvent(new Event('pointerdown'))

  it('con sesión suma y manda a los 30 s, con la pantalla y «abrió la app»', () => {
    window.location.pathname = '/posiciones'
    uso.activarUso(true)
    tocar()
    uso.registrarUso('position_add_completed')
    uso.registrarUso('position_add_completed')
    uso.registrarUso('route_change')           // no se cuenta
    uso.registrarUso('ai_chat_sent')           // soloGA: por track() no
    uso.registrarUsoGA('ai_chat_sent')         // por trackEvent() sí
    uso.registrarUsoGA('login')                // fuera del catálogo
    uso.registrarUso('paywall_muro_visto')     // vista: viaja con prefijo
    vi.advanceTimersByTime(29_000)
    expect(globalThis.fetch).not.toHaveBeenCalled()
    vi.advanceTimersByTime(2_000)
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
    expect(globalThis.fetch.mock.calls[0][0]).toBe('/api/uso/eventos')
    expect(cuerpo()).toEqual({
      app_abierta: 1, 'pantalla:/posiciones': 1, position_add_completed: 2, ai_chat_sent: 1,
      'vista:paywall_muro_visto': 1,
    })
  })

  it('una pestaña que se recarga sola y nadie toca no cuenta como uso', () => {
    // autoUpdate.js recarga las pestañas quietas al publicar una versión; el
    // navegador reabre pestañas al arrancar. Sin un toque, no es uso.
    uso.activarUso(true)
    uso.registrarUso('checklist_item_clicked')
    vi.advanceTimersByTime(120_000)
    expect(globalThis.fetch).not.toHaveBeenCalled()
    document.visibilityState = 'hidden'
    document.dispatchEvent(new Event('visibilitychange'))   // se esconde sin que nadie la tocara
    expect(globalThis.fetch).not.toHaveBeenCalled()
    document.visibilityState = 'visible'
    document.dispatchEvent(new Event('visibilitychange'))
    tocar()                                                 // ahora sí alguien la usa
    uso.registrarUso('moneda_cambiada')
    vi.advanceTimersByTime(31_000)
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
    // Sale sólo lo de después del toque: lo juntado sin uso se descartó.
    expect(cuerpo()).toEqual({ moneda_cambiada: 1 })
  })

  it('«abrió la app» va una vez por día aunque la pestaña se esconda y vuelva', () => {
    uso.activarUso(true)
    tocar()
    document.visibilityState = 'hidden'
    document.dispatchEvent(new Event('visibilitychange'))          // manda al esconderse
    expect(globalThis.fetch.mock.calls[0][1].keepalive).toBe(true)
    document.visibilityState = 'visible'
    document.dispatchEvent(new Event('visibilitychange'))          // mismo día: no suma
    vi.advanceTimersByTime(31_000)
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
    expect(cuerpo(0).app_abierta).toBe(1)
  })

  it('al cerrar sesión se descarta lo pendiente (ya no es de esa persona)', () => {
    uso.activarUso(true)
    tocar()
    uso.registrarUso('operation_added')
    uso.activarUso(false)
    vi.advanceTimersByTime(60_000)
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })
})
