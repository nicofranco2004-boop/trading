import { describe, it, expect, vi, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import {
  anotarOrigen, origenParaElRegistro, olvidarOrigen, normalizarCodigo,
  codigoDeLaDireccion, codigoDeLaVisita, MARCAS_DE_CLIC, ORIGEN_KEY, ORIGEN_DURA_MS,
} from './origen'
import { escenarios } from './origen.escenarios.json'

afterEach(() => { vi.unstubAllGlobals() })

// Un navegador de mentira con lo que usa origen.js: la dirección, el historial
// (replaceState cambia la dirección de verdad), la página de donde venía
// (document.referrer) y un localStorage en memoria.
function navegador(href, guardado = {}, referrer = '') {
  const store = new Map(Object.entries(guardado))
  const win = {
    location: new URL(href),
    history: {
      state: { idx: 0 },
      replaceState(state, _t, url) { this.state = state; win.location = new URL(url, win.location.href) },
    },
  }
  vi.stubGlobal('window', win)
  vi.stubGlobal('document', { referrer })
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

// Las mismas visitas que recorre backend/tests/test_origen_registros.py desde
// el registro hasta el canal del panel: acá, de la visita al código que viaja.
describe('sin código en el link: la marca del clic y el sitio de donde venía', () => {
  it.each(escenarios.map(e => [e.caso, e]))('%s', (_caso, e) => {
    const n = navegador(e.direccion, {}, e.referrer)
    anotarOrigen(AHORA)
    expect(origenParaElRegistro(AHORA)?.origen ?? null).toBe(e.codigo)
    // Lo que viaja ya está limpio: el servidor lo guarda tal cual.
    if (e.codigo) expect(normalizarCodigo(e.codigo)).toBe(e.codigo)
    // La marca y los utm se quedan en la dirección (los leen Google y Meta).
    for (const m of MARCAS_DE_CLIC) {
      expect(n.win.location.searchParams.get(m)).toBe(new URL(e.direccion).searchParams.get(m))
    }
  })

  it('de la página de donde venía se guarda SÓLO el sitio: ni la ruta ni lo que se buscó', () => {
    const n = navegador('https://rendi.finance/', {},
      'https://www.google.com/search?q=rendi+juan.perez%40mail.com&hl=es#arriba')
    anotarOrigen(AHORA)
    const guardado = JSON.stringify(n.guardado())
    expect(n.guardado().codigo).toBe('sitio/google.com')
    for (const pedazo of ['search', 'juan', 'perez', 'mail', 'q=', 'hl', 'arriba']) {
      expect(guardado).not.toContain(pedazo)
    }
  })

  it('de la marca se guarda el nombre, nunca el valor (identifica el clic)', () => {
    const n = navegador('https://rendi.finance/?fbclid=IwAR0SecretoDelClic', {}, 'https://l.facebook.com/')
    anotarOrigen(AHORA)
    expect(n.guardado().codigo).toBe('sitio/l.facebook.com/fbclid')
    expect(JSON.stringify(n.guardado())).not.toMatch(/secreto/i)
  })

  it('si vienen dos marcas se anota la primera de la lista', () => {
    expect(codigoDeLaVisita('?gclid=a&fbclid=b', '')).toBe('clic/fbclid')
    expect(codigoDeLaVisita('?msclkid=a&gclid=b', '')).toBe('clic/gclid')
    // Una marca vacía no es una marca.
    expect(codigoDeLaVisita('?fbclid=&gclid=b', '')).toBe('clic/gclid')
    expect(codigoDeLaVisita('?fbclid=', '')).toBe(null)
  })

  it('el sitio donde está abierta la página tampoco cuenta (servidor local, vista previa)', () => {
    navegador('http://localhost:5173/', {}, 'http://localhost:5173/login')
    anotarOrigen(AHORA)
    expect(origenParaElRegistro(AHORA)).toBe(null)
    expect(codigoDeLaVisita('', 'https://app.rendi.finance/x', 'rendi.finance')).toBe(null)
    expect(codigoDeLaVisita('', 'https://rendi-git-rama.vercel.app/', 'www.rendi-git-rama.vercel.app')).toBe(null)
    // Rendi es Rendi aunque la página esté abierta en otro lado (una vista previa).
    expect(codigoDeLaVisita('', 'https://rendi.finance/planes', 'rendi-git-rama.vercel.app')).toBe(null)
  })

  it('un sitio larguísimo se recorta por adelante: queda el sitio y entra en el servidor', () => {
    const largo = `${'muy-largo.'.repeat(8)}foro.ejemplo.com.ar`
    const codigo = codigoDeLaVisita('?fbclid=x', `https://${largo}/hilo/1`)
    expect(codigo.length).toBeLessThanOrEqual(60)
    expect(codigo).toMatch(/^sitio\/.*\.foro\.ejemplo\.com\.ar\/fbclid$/)
    expect(normalizarCodigo(codigo)).toBe(codigo)
  })

  it('una página de donde venía rara se ignora sin romper', () => {
    for (const raro of ['::::', 'javascript:alert(1)', 'file:///etc/passwd', 'android-app://', 'https://', 'about:blank']) {
      expect(() => codigoDeLaVisita('', raro)).not.toThrow()
      expect(codigoDeLaVisita('', raro)).toBe(null)
    }
    // Sin document (el arranque en un lugar sin navegador) tampoco rompe.
    navegador('https://rendi.finance/?fbclid=x')
    vi.stubGlobal('document', undefined)
    expect(() => anotarOrigen(AHORA)).not.toThrow()
    expect(origenParaElRegistro(AHORA).origen).toBe('clic/fbclid')
  })

  it('manda el primero también con el sitio: el post que vino después no lo pisa', () => {
    const n = navegador('https://rendi.finance/', {}, 'https://t.co/')
    anotarOrigen(AHORA)
    n.win.location = new URL('https://rendi.finance/?d=x-1022')
    vi.stubGlobal('document', { referrer: '' })
    anotarOrigen(AHORA + 864e5)
    expect(n.guardado().codigo).toBe('sitio/t.co')
    // Y una visita sin nada que reconocer no anota nada.
    const m = navegador('https://rendi.finance/', {}, '')
    anotarOrigen(AHORA)
    expect(m.guardado()).toBe(null)
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
