// El «no me guardes» de vercel.json para las copias en *.vercel.app no puede
// tocar nunca a rendi.finance.
//
// Por qué existe: el sitio entero se ve también en https://trading-irb3.vercel.app
// y https://trading-htn9.vercel.app (las direcciones que Vercel le da al
// proyecto), sin «noindex» (medido el 16/11/2026 con curl -I). Google puede
// guardarlas como copias de rendi.finance. vercel.json les agrega el encabezado
// `X-Robots-Tag: noindex` SÓLO cuando el pedido llega con esa dirección
// (condición `has` de tipo `host`, documentada en
// https://vercel.com/docs/project-configuration/vercel-json#headers y con este
// mismo uso en https://vercel.com/docs/headers/response-headers#x-robots-tag).
//
// Lo peligroso: si esa condición alguna vez coincidiera con rendi.finance,
// Google sacaría el sitio ENTERO del buscador, sin ningún error en ningún lado.
// Esta prueba lee vercel.json y revisa que toda regla que agrega «noindex» a
// una página pública esté atada a una dirección que coincide con las copias y
// NO con rendi.finance ni www.rendi.finance.
//
// Cómo evalúa la condición, del lado seguro: Vercel dice que un `value` de
// texto es «parecido a una expresión regular» pero no si tiene que coincidir
// entero o alcanza con una parte. La prueba la evalúa de las dos formas: para
// las copias tiene que coincidir de las dos, y para rendi.finance no puede
// coincidir de ninguna. Una condición que no sabe evaluar la toma como error.
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { PAGINAS_PUBLICAS } from '../paginasPublicas'

const raiz = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const VERCEL = JSON.parse(fs.readFileSync(path.join(raiz, 'vercel.json'), 'utf8'))
const RUTAS = Object.keys(PAGINAS_PUBLICAS)

const NUESTRAS = ['rendi.finance', 'www.rendi.finance']
const COPIAS = ['trading-irb3.vercel.app', 'trading-htn9.vercel.app']

// `source` de Vercel (sintaxis de path-to-regexp) → expresión regular.
function fuenteARegex(source) {
  const re = source
    .replace(/\/:\w+\*/g, '(?:/.*)?')
    .replace(/:\w+\+/g, '.+')
    .replace(/:\w+\?/g, '[^/]*')
    .replace(/:\w+/g, '[^/]+')
  return new RegExp(`^${re}$`)
}

const regex = (fuente, modo) => new RegExp(modo === 'entera' ? `^(?:${fuente})$` : fuente)

// ¿El `value` de una condición coincide con `texto`? `modo`: 'entera' o 'parte'.
function cumple(valor, texto, modo) {
  if (valor === undefined) return true // sin valor, Vercel acepta cualquiera
  if (typeof valor === 'string') return regex(valor, modo).test(texto)
  if (!valor || typeof valor !== 'object') throw new Error(`valor de condición raro: ${JSON.stringify(valor)}`)
  const conocidas = ['eq', 'neq', 'inc', 'ninc', 'pre', 'suf', 're']
  for (const k of Object.keys(valor)) {
    if (!conocidas.includes(k)) throw new Error(`condición «${k}» que esta prueba no sabe evaluar: agregala acá antes de usarla`)
  }
  if ('eq' in valor && String(valor.eq) !== texto) return false
  if ('neq' in valor && valor.neq === texto) return false
  if ('inc' in valor && !valor.inc.includes(texto)) return false
  if ('ninc' in valor && valor.ninc.includes(texto)) return false
  if ('pre' in valor && !texto.startsWith(valor.pre)) return false
  if ('suf' in valor && !texto.endsWith(valor.suf)) return false
  if ('re' in valor && !regex(valor.re, modo).test(texto)) return false
  return true
}
const cumpleDeLasDos = (valor, texto) => cumple(valor, texto, 'entera') && cumple(valor, texto, 'parte')
const cumpleDeAlguna = (valor, texto) => cumple(valor, texto, 'entera') || cumple(valor, texto, 'parte')

// ¿Puede la regla aplicarse a un pedido que llega a `host`? Del lado seguro:
// las condiciones de encabezado, cookie o query pueden darse en cualquier
// pedido, y un `missing` no se cuenta como protección.
function podriaAplicarseEn(regla, host) {
  return (regla.has || []).every((c) => c.type !== 'host' || cumpleDeAlguna(c.value, host))
}

// ¿Se aplica SIEMPRE a los pedidos que llegan a `host`?
function seAplicaSiempreEn(regla, host) {
  if ((regla.missing || []).length) return false
  return (regla.has || []).every((c) => c.type === 'host' && cumpleDeLasDos(c.value, host))
}

const diceNoindex = (regla) => regla.headers.some((h) => h.key.toLowerCase() === 'x-robots-tag' && /noindex|none/i.test(h.value))

// Lo que tiene que dar vacío: cada regla con «noindex» que toca una página
// pública y no está atada a las copias.
function problemasDeNoindex(headers) {
  const problemas = []
  for (const regla of headers.filter(diceNoindex)) {
    const tocadas = RUTAS.filter((r) => fuenteARegex(regla.source).test(r))
    if (!tocadas.length) continue // /login, /brand-kit/…: no son páginas públicas
    const quien = `«${regla.source}» (toca ${tocadas.slice(0, 3).join(', ')}${tocadas.length > 3 ? '…' : ''})`
    if (!(regla.has || []).some((c) => c.type === 'host')) {
      problemas.push(`${quien} dice noindex sin condición de dirección: aplicaría en rendi.finance`)
      continue
    }
    for (const h of NUESTRAS) if (podriaAplicarseEn(regla, h)) problemas.push(`${quien} podría aplicarse en ${h}`)
    for (const h of COPIAS) if (!seAplicaSiempreEn(regla, h)) problemas.push(`${quien} no cubre siempre a ${h}`)
  }
  return problemas
}

const regla = (extra) => ({ source: '/(.*)', headers: [{ key: 'X-Robots-Tag', value: 'noindex' }], ...extra })

describe('el guardián mismo: condiciones que tendría que frenar', () => {
  const peligrosas = [
    ['sin condición', regla({})],
    ['host que acepta cualquier cosa', regla({ has: [{ type: 'host', value: '(.*)' }] })],
    ['host sin valor', regla({ has: [{ type: 'host' }] })],
    ['regex que también nombra a rendi', regla({ has: [{ type: 'host', value: { re: 'vercel\\.app|rendi' } }] })],
    ['termina en «finance»', regla({ has: [{ type: 'host', value: { suf: 'finance' } }] })],
    ['«vercel.app» como texto suelto (sólo coincide si alcanza con una parte)', regla({ has: [{ type: 'host', value: 'vercel.app' }] })],
    ['encabezado «host» en vez de condición de tipo host', regla({ has: [{ type: 'header', key: 'host', value: '.*vercel.*' }] })],
    ['sólo un «missing» de rendi.finance', regla({ missing: [{ type: 'host', value: 'rendi.finance' }] })],
    ['noindex en /planes sin condición', { source: '/planes', headers: [{ key: 'X-Robots-Tag', value: 'noindex, follow' }] }],
  ]
  for (const [nombre, r] of peligrosas) {
    it(`frena: ${nombre}`, () => {
      expect(problemasDeNoindex([r]).length).toBeGreaterThan(0)
    })
  }

  it('acepta las formas seguras', () => {
    expect(problemasDeNoindex([regla({ has: [{ type: 'host', value: { suf: '.vercel.app' } }] })])).toEqual([])
    expect(problemasDeNoindex([regla({ has: [{ type: 'host', value: '[a-z0-9-]+\\.vercel\\.app' }] })])).toEqual([])
    expect(problemasDeNoindex([{ source: '/brand-kit/(.*)', headers: [{ key: 'X-Robots-Tag', value: 'noindex' }] }])).toEqual([])
  })

  it('una condición que no sabe evaluar la toma como error, no como segura', () => {
    expect(() => problemasDeNoindex([regla({ has: [{ type: 'host', value: { gt: 3 } }] })])).toThrow(/no sabe evaluar/)
  })
})

describe('vercel.json: «no me guardes» sólo donde corresponde', () => {
  it('ninguna regla con noindex sobre una página pública puede aplicarse en rendi.finance', () => {
    const problemas = problemasDeNoindex(VERCEL.headers)
    expect(problemas, problemas.join('\n')).toEqual([])
  })

  it('las copias en *.vercel.app dicen noindex en todas las páginas públicas', () => {
    for (const host of COPIAS) {
      for (const ruta of RUTAS) {
        const cubre = VERCEL.headers.some((r) => diceNoindex(r) && fuenteARegex(r.source).test(ruta) && seAplicaSiempreEn(r, host))
        expect(cubre, `${host}${ruta} sale sin noindex`).toBe(true)
      }
    }
  })

  it('rendi.finance no recibe noindex en ninguna página pública', () => {
    for (const host of NUESTRAS) {
      for (const ruta of RUTAS) {
        const tapa = VERCEL.headers.filter((r) => diceNoindex(r) && fuenteARegex(r.source).test(ruta) && podriaAplicarseEn(r, host))
        expect(tapa.map((r) => r.source), `${host}${ruta} recibiría noindex`).toEqual([])
      }
    }
  })

  // El manual de marca (public/brand-kit/) es material interno: no tiene por
  // qué salir en Google. Y /login sigue como estaba.
  it('/brand-kit/ y /login dicen noindex en rendi.finance', () => {
    for (const ruta of ['/brand-kit/manual.html', '/brand-kit/tokens.css', '/login']) {
      const cubre = VERCEL.headers.some((r) => diceNoindex(r) && fuenteARegex(r.source).test(ruta) && seAplicaSiempreEn(r, 'rendi.finance'))
      expect(cubre, `${ruta} sale sin noindex`).toBe(true)
    }
  })
})
