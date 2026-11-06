import { describe, it, expect } from 'vitest'
import {
  PARAMS_PERMITIDOS, RUTAS_SENSIBLES, direccionParaTerceros, referenteConDatos,
  referenteParaTerceros, rutaSensible, urlTieneDatosSensibles,
} from './rutasSensibles'

const SITIO = 'https://rendi.finance'

// Nombres de parámetro al azar, repetibles (misma semilla, mismos nombres).
function nombresAlAzar(cuantos, semilla = 20261105) {
  let s = semilla
  const azar = () => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648 }
  const letras = 'abcdefghijklmnopqrstuvwxyz_0123456789'
  const nombres = new Set()
  while (nombres.size < cuantos) {
    const largo = 1 + Math.floor(azar() * 12)
    let n = ''
    for (let i = 0; i < largo; i++) n += letras[Math.floor(azar() * letras.length)]
    if (!PARAMS_PERMITIDOS.includes(n)) nombres.add(n)
  }
  return [...nombres]
}

describe('urlTieneDatosSensibles: las rutas con el secreto en la ruta (RENDI-09)', () => {
  it('bloquea /verify-email, /reset-password, /i/, /claim y /acceso', () => {
    expect(urlTieneDatosSensibles('/verify-email', '?email=juan%40x.com')).toBe(true)
    expect(urlTieneDatosSensibles('/reset-password', '?token=abc123')).toBe(true)
    expect(urlTieneDatosSensibles('/i/abc', '')).toBe(true)
    expect(urlTieneDatosSensibles('/claim', '?token=x')).toBe(true)
    expect(urlTieneDatosSensibles('/acceso', '')).toBe(true)
  })

  it('también en mayúsculas: el router abre el mismo informe con /I/<token>', () => {
    expect(rutaSensible('/I/TOKEN')).toBe('/i/')
    expect(urlTieneDatosSensibles('/Claim', '')).toBe(true)
  })
})

describe('urlTieneDatosSensibles: lista de PERMITIDOS, no de prohibidos', () => {
  it('la cartera de «Una cartera» no es limpia (activos, pesos, local, activo)', () => {
    expect(urlTieneDatosSensibles('/analisis-tecnico', '?tab=backtesting&modo=cartera&activos=AAPL,GGAL&pesos=50,50')).toBe(true)
    expect(urlTieneDatosSensibles('/analisis-tecnico', '?tab=grafico&activo=GGAL')).toBe(true)
    expect(urlTieneDatosSensibles('/analisis-tecnico', '?tab=backtesting&local=GGAL')).toBe(true)
  })

  it('lo de siempre sigue sin ser limpio: token, email, code, next', () => {
    expect(urlTieneDatosSensibles('/lo-que-sea', '?email=x')).toBe(true)
    expect(urlTieneDatosSensibles('/otra', '?token=x')).toBe(true)
    expect(urlTieneDatosSensibles('/x', '?code=123456')).toBe(true)
    expect(urlTieneDatosSensibles('/login', '?mode=register&next=%2Fi%2Fabc')).toBe(true)
  })

  it('falla cerrado: 500 nombres de parámetro inventados, ninguno pasa', () => {
    for (const n of nombresAlAzar(500)) {
      expect(urlTieneDatosSensibles('/', `?${encodeURIComponent(n)}=1`), n).toBe(true)
      expect(urlTieneDatosSensibles('/cartera', `?tab=resumen&${encodeURIComponent(n)}=1`), n).toBe(true)
    }
  })

  it('deja pasar las páginas sin nada de la persona y la atribución de los anuncios', () => {
    expect(urlTieneDatosSensibles('/', '')).toBe(false)
    expect(urlTieneDatosSensibles('/planes', '?plan=pro&period=annual')).toBe(false)
    expect(urlTieneDatosSensibles('/login', '?mode=register')).toBe(false)
    expect(urlTieneDatosSensibles('/x', '?d=post-123&utm_source=ig')).toBe(false)
    expect(urlTieneDatosSensibles('/', '?utm_source=instagram&utm_medium=paid&utm_campaign=x&fbclid=IwAR0&gclid=Cj0&gad_source=1')).toBe(false)
    expect(urlTieneDatosSensibles('/analisis-tecnico', '?tab=backtesting&modo=cartera&origen=cero&anios=2&reglas=rsi,media50')).toBe(false)
  })

  it('cada permitido, solo, es limpio (y ninguno es una ruta sensible)', () => {
    for (const k of PARAMS_PERMITIDOS) expect(urlTieneDatosSensibles('/', `?${k}=1`), k).toBe(false)
    expect(new Set(PARAMS_PERMITIDOS).size).toBe(PARAMS_PERMITIDOS.length)
    expect(RUTAS_SENSIBLES.every((r) => r.startsWith('/'))).toBe(true)
  })
})

describe('direccionParaTerceros: lo que se le da a Google', () => {
  it('la cartera de «Una cartera» llega sin activos ni pesos', () => {
    expect(direccionParaTerceros(`${SITIO}/analisis-tecnico?tab=backtesting&modo=cartera&origen=cero&activos=AAPL,GGAL,BTC&pesos=50,30,20&local=GGAL&anios=2`))
      .toBe(`${SITIO}/analisis-tecnico?tab=backtesting&modo=cartera&origen=cero&anios=2`)
  })

  it('un parámetro desconocido no se lleva puesta la atribución: utm y gclid quedan', () => {
    expect(direccionParaTerceros(`${SITIO}/?utm_source=google&gclid=Cj0&algo_nuevo=dato&gad_source=1`))
      .toBe(`${SITIO}/?utm_source=google&gclid=Cj0&gad_source=1`)
  })

  it('de una ruta sensible, sólo el comienzo (sin el token, sin la query)', () => {
    expect(direccionParaTerceros(`${SITIO}/i/TOKENSECRETO`)).toBe(`${SITIO}/i/`)
    expect(direccionParaTerceros(`${SITIO}/I/TOKENSECRETO`)).toBe(`${SITIO}/i/`)
    expect(direccionParaTerceros(`${SITIO}/reset-password?token=abc`)).toBe(`${SITIO}/reset-password`)
    expect(direccionParaTerceros(`${SITIO}/verify-email?email=ana%40x.com`)).toBe(`${SITIO}/verify-email`)
  })

  it('sin el #… (la cartera vieja iba a /posiciones#TICKER)', () => {
    expect(direccionParaTerceros(`${SITIO}/posiciones?tab=lista#GGAL`)).toBe(`${SITIO}/posiciones?tab=lista`)
  })

  it('una dirección que no se puede leer no sale', () => {
    expect(direccionParaTerceros('no es una dirección')).toBe('')
    expect(direccionParaTerceros('')).toBe('')
  })

  it('falla cerrado: con parámetros inventados, lo que sale tiene sólo permitidos', () => {
    for (const n of nombresAlAzar(200, 7)) {
      const sale = new URL(direccionParaTerceros(`${SITIO}/cartera?tab=resumen&${encodeURIComponent(n)}=DATO&utm_source=ig`))
      expect([...sale.searchParams.keys()], n).toEqual(['tab', 'utm_source'])
    }
  })
})

describe('referenteParaTerceros: de dónde venía, como se le da a Google', () => {
  it('una página web: la misma limpieza que la dirección', () => {
    expect(referenteParaTerceros(`${SITIO}/login?email=ana%40x.com&next=%2Fcartera`)).toBe(`${SITIO}/login`)
    expect(referenteParaTerceros('https://l.instagram.com/?u=https%3A%2F%2Frendi.finance&e=AT0')).toBe('https://l.instagram.com/')
    expect(referenteParaTerceros('')).toBe('')
    expect(referenteParaTerceros('no es una dirección')).toBe('')
  })

  it('una app de Android (Gmail, el buscador de Google) queda entera: la atribución la lee así', () => {
    // new URL le da origen «null»: con la limpieza de las páginas quedaba «null/…».
    expect(referenteParaTerceros('android-app://com.google.android.gm/')).toBe('android-app://com.google.android.gm/')
    expect(referenteParaTerceros('android-app://com.google.android.googlequicksearchbox/https/www.google.com'))
      .toBe('android-app://com.google.android.googlequicksearchbox/https/www.google.com')
    expect(referenteParaTerceros('android-app://com.algo/?dato=1#x')).toBe('android-app://com.algo/')
  })
})

describe('referenteConDatos: la página de la que venía la persona', () => {
  it('una página de Rendi con datos sí cuenta (el email del login llegaba a Meta)', () => {
    expect(referenteConDatos(`${SITIO}/login?email=ana%40x.com&next=%2Fcartera`)).toBe(true)
    expect(referenteConDatos('https://www.rendi.finance/i/TOKEN')).toBe(true)
  })

  it('una de Rendi limpia, o sólo el sitio (lo que manda strict-origin), no', () => {
    expect(referenteConDatos(`${SITIO}/`)).toBe(false)
    expect(referenteConDatos(`${SITIO}/planes?plan=pro`)).toBe(false)
    expect(referenteConDatos('')).toBe(false)
  })

  it('la de otro sitio no cuenta: no es un dato de Rendi y la atribución la usa', () => {
    expect(referenteConDatos('https://l.instagram.com/?u=https%3A%2F%2Frendi.finance&e=AT0')).toBe(false)
    expect(referenteConDatos('https://www.google.com/')).toBe(false)
  })
})
