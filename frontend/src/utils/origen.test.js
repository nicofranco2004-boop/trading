import { describe, it, expect, vi, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import {
  anotarOrigen, origenParaElRegistro, olvidarOrigen, normalizarCodigo,
  codigoDeLaDireccion, ORIGEN_KEY, ORIGEN_DURA_MS,
} from './origen'

afterEach(() => { vi.unstubAllGlobals() })

// Un navegador de mentira con lo que usa origen.js: la dirección, el historial
// (replaceState cambia la dirección de verdad) y un localStorage en memoria.
function navegador(href, guardado = {}) {
  const store = new Map(Object.entries(guardado))
  const win = {
    location: new URL(href),
    history: {
      state: { idx: 0 },
      replaceState(state, _t, url) { this.state = state; win.location = new URL(url, win.location.href) },
    },
  }
  vi.stubGlobal('window', win)
  vi.stubGlobal('localStorage', {
    getItem: k => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: k => store.delete(k),
  })
  return { win, store, guardado: () => JSON.parse(store.get(ORIGEN_KEY) || 'null') }
}

const AHORA = Date.parse('2026-10-19T12:00:00Z')

describe('al entrar con un código', () => {
  it('se guarda con su fecha y la página donde entró', () => {
    const n = navegador('https://rendi.finance/blog/brokers?d=x-1019')
    anotarOrigen(AHORA)
    expect(n.guardado()).toEqual({ codigo: 'x-1019', visto: '2026-10-19T12:00:00.000Z', pagina: '/blog/brokers' })
    expect(origenParaElRegistro(AHORA)).toEqual({ origen: 'x-1019', origen_visto: '2026-10-19T12:00:00.000Z' })
  })

  it('se saca `d` de la dirección y lo demás queda', () => {
    const n = navegador('https://rendi.finance/planes?x=1&d=x-1019#precios')
    anotarOrigen(AHORA)
    expect(n.win.location.pathname + n.win.location.search + n.win.location.hash).toBe('/planes?x=1#precios')
    // El estado del historial (el de React Router) no se pisa.
    expect(n.win.history.state).toEqual({ idx: 0 })
  })

  it('con `?demo=1&d=…` el demo sigue arrancando y el código no se pierde', () => {
    // El demo (AuthContext) borra todo lo que hay después del `?`. Por eso esto
    // corre antes, en main.jsx, y tiene que dejarle `demo=1` intacto.
    const n = navegador('https://rendi.finance/?demo=1&d=x-1019')
    anotarOrigen(AHORA)
    expect(new URLSearchParams(n.win.location.search).get('demo')).toBe('1')
    expect(n.win.location.search).toBe('?demo=1')
    expect(n.guardado().codigo).toBe('x-1019')
  })

  it('los utm_* se aceptan y se DEJAN en la dirección (los lee Google Analytics)', () => {
    const n = navegador('https://rendi.finance/?utm_source=X&utm_campaign=post-1019')
    anotarOrigen(AHORA)
    expect(n.guardado().codigo).toBe('x/post-1019')
    expect(n.win.location.search).toBe('?utm_source=X&utm_campaign=post-1019')
  })

  it('`d` le gana a los utm', () => {
    expect(codigoDeLaDireccion('?utm_source=ig&d=x-1019')).toBe('x-1019')
    expect(codigoDeLaDireccion('?utm_campaign=solo')).toBe('solo')
    expect(codigoDeLaDireccion('?demo=1')).toBe(null)
  })
})

describe('manda el primero', () => {
  it('una segunda visita con otro código no lo pisa', () => {
    const n = navegador('https://rendi.finance/?d=x-1019')
    anotarOrigen(AHORA)
    n.win.location = new URL('https://rendi.finance/?d=ig-1022')
    anotarOrigen(AHORA + 3 * 864e5)
    expect(n.guardado().codigo).toBe('x-1019')
    expect(n.win.location.search).toBe('')
  })

  it('una visita sin código tampoco lo borra', () => {
    const n = navegador('https://rendi.finance/?d=x-1019')
    anotarOrigen(AHORA)
    n.win.location = new URL('https://rendi.finance/login')
    anotarOrigen(AHORA + 864e5)
    expect(n.guardado().codigo).toBe('x-1019')
  })

  it('a los 30 días vence: no viaja con el registro y un código nuevo lo reemplaza', () => {
    const n = navegador('https://rendi.finance/?d=x-1019')
    anotarOrigen(AHORA)
    const despues = AHORA + ORIGEN_DURA_MS + 1000
    expect(origenParaElRegistro(despues)).toBe(null)
    n.win.location = new URL('https://rendi.finance/?d=ig-1120')
    anotarOrigen(despues)
    expect(n.guardado().codigo).toBe('ig-1120')
  })

  it('después de registrarse se olvida', () => {
    navegador('https://rendi.finance/?d=x-1019')
    anotarOrigen(AHORA)
    olvidarOrigen()
    expect(origenParaElRegistro(AHORA)).toBe(null)
  })
})

describe('nunca rompe la página', () => {
  it('con el almacenamiento bloqueado no tira y igual limpia la dirección', () => {
    const n = navegador('https://rendi.finance/?d=x-1019')
    const boom = () => { throw new DOMException('acceso denegado', 'SecurityError') }
    vi.stubGlobal('localStorage', { getItem: boom, setItem: boom, removeItem: boom })
    expect(() => anotarOrigen(AHORA)).not.toThrow()
    expect(n.win.location.search).toBe('')
    expect(origenParaElRegistro(AHORA)).toBe(null)
    expect(() => olvidarOrigen()).not.toThrow()
  })

  it('algo raro guardado se ignora', () => {
    navegador('https://rendi.finance/', { [ORIGEN_KEY]: '{no es json' })
    expect(origenParaElRegistro(AHORA)).toBe(null)
  })
})

// Los mismos casos que `LaMismaReglaQueElNavegador` en
// backend/tests/test_origen_registros.py: el servidor limpia igual.
describe('la regla de limpieza es la misma que la del servidor', () => {
  it.each([
    ['x-20261019', 'x-20261019'],
    ['IG-20261019', 'ig-20261019'],
    ['  x 1019 ', 'x-1019'],
    ['x/campaña', 'x/campaa'],
    ['<b>', 'b'],
    ['', null],
    ['!!!', null],
  ])('%j → %j', (entrada, esperado) => {
    expect(normalizarCodigo(entrada)).toBe(esperado)
  })
})

// Las dos puntas que estas pruebas no montan: dónde se llama y qué se manda.
describe('dónde está enchufado', () => {
  it('main.jsx lo anota ANTES de montar la app (el demo borraría el código)', () => {
    const main = readFileSync(new URL('../main.jsx', import.meta.url), 'utf8')
    const anota = main.indexOf('\nanotarOrigen()')
    expect(anota).toBeGreaterThan(-1)
    expect(anota).toBeLessThan(main.indexOf('createRoot('))
  })

  it('Login.jsx lo manda con el registro y no con el login', () => {
    const login = readFileSync(new URL('../pages/Login.jsx', import.meta.url), 'utf8')
    expect(login).toMatch(/password, name: name\.trim\(\), \.\.\.\(origenParaElRegistro\(\) \|\| \{\}\)/)
    expect(login).toMatch(/if \(mode === 'register'\) olvidarOrigen\(\)/)
  })
})
