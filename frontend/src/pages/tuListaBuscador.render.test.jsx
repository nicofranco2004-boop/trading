// El buscador de «Tu lista» (Análisis técnico → ?tab=lista), por el MISMO
// camino que producción: la app entera, con un servidor simulado (fetch) que
// guarda la watchlist y anota cada pedido. Pedido de Nico (02/11): para sumar
// un activo a la watchlist había que ir al inicio.
//
// Lo que se prueba es lo que la persona ve: escribe, toca la sugerencia, y el
// activo aparece ABAJO, en la lista, sin recargar la página (la lista vuelve a
// pedir /watchlist y /tecnico/lista cuando la watchlist cambia). Y que lo que
// ya está —en la cartera o en la watchlist— se avisa y no se manda de nuevo.
import { describe, it, expect, beforeAll } from 'vitest'
import { createElement as h } from 'react'
import { prepararApp, textoConCortes, cargando } from '../testing/pantallaConOjito'
import { montar, clic, texto, escribir, tecla, enActo } from '../testing/navegadorMinimo'
import { CLAVES_DE_LOS_TOURS } from '../components/tour/recorrido'

let App, HelmetProvider, ToastProvider, MemoryRouter, api, SUMAR_A_LA_WATCHLIST
const servidor = { watchlist: [], pedidos: [], fallarLectura: false }
const json = (r, status = 200) => new Response(JSON.stringify(r), { status, headers: { 'content-type': 'application/json' } })

beforeAll(async () => {
  await prepararApp({ ancho: 1280 })
  // La pantalla se importa DESPUÉS de armar el navegador de mentira: React mira
  // al cargarse si el navegador tiene el evento `input`, y si se importaba antes
  // (arriba de todo) decidía que no, y lo escrito nunca llegaba al buscador.
  ;({ SUMAR_A_LA_WATCHLIST } = await import('./TuLista'))
  ;({ default: App } = await import('../App'))
  ;({ HelmetProvider } = await import('react-helmet-async'))
  ;({ ToastProvider } = await import('../components/Toast'))
  ;({ MemoryRouter } = await import('react-router-dom'))
  api = await import('../utils/api')
  const { vi } = await import('vitest')
  vi.stubGlobal('fetch', async (url, opts = {}) => {
    const method = opts.method || 'GET'
    const path = String(url).replace(/^\/api/, '')
    const body = opts.body && typeof opts.body === 'string' ? JSON.parse(opts.body) : undefined
    servidor.pedidos.push(`${method} ${path.split('?')[0]}`)
    if (path.startsWith('/auth/me')) return json({ name: 'Ana', email: 'ana@prueba.test', tier: 'pro' })
    if (path === '/watchlist' && method === 'GET') return json({ items: servidor.watchlist })
    if (path === '/watchlist' && method === 'POST') {
      servidor.watchlist = [...servidor.watchlist, { symbol: body.symbol }]
      return json({ ok: true })
    }
    // Lo que tenés: MELI. La lectura técnica no hace falta para ver la fila.
    // Un 500 y no un 503: el 503 («probá de nuevo») la app lo reintenta sola.
    if (path === '/tecnico/lista' && servidor.fallarLectura) return json({ detail: 'falló' }, 500)
    if (path === '/tecnico/lista') return json({ tenencias: [{ asset: 'MELI', local: false, peso: 1, tipo: 'STOCK' }], lecturas: [] })
    if (path === '/positions') return json([])
    if (path.startsWith('/tickers/search')) return json({ results: [] })
    return json(method === 'GET' ? {} : { ok: true })
  })
}, 180000)

const esperar = (ms) => new Promise(r => setTimeout(r, ms))
const RUTA = '/analisis-tecnico?tab=lista'
const el = () => h(HelmetProvider, null, h(ToastProvider, null, h(MemoryRouter, { initialEntries: [RUTA] }, h(App))))
// Sin volver a dibujar desde afuera: eso arma la pantalla de nuevo y el cuadro
// perdía lo escrito. Se espera a que lo de adentro (pedidos, avisos) se aquiete.
async function quieta(m) {
  let antes = null, quietas = 0
  for (let i = 0; i < 200 && (i < 10 || quietas < 8); i++) {
    await esperar(60)
    const t = textoConCortes(m.contenedor)
    quietas = (t === antes && !cargando(m.contenedor)) ? quietas + 1 : 0
    antes = t
  }
  return textoConCortes(m.contenedor).replace(/\s+/g, ' ')
}
function buscar(nodo, cumple) {
  const pila = [nodo]
  while (pila.length) {
    const n = pila.shift()
    if (cumple(n)) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}
const campo = (m) => buscar(m.contenedor, n => n.nodeName === 'INPUT' && n.getAttribute?.('aria-label') === SUMAR_A_LA_WATCHLIST)
// La sugerencia del desplegable: un botón que empieza con el ticker.
const sugerencia = (m, ticker) => buscar(m.contenedor, n => n.nodeName === 'BUTTON' && texto(n).trim().startsWith(ticker))

async function abrir() {
  localStorage.clear(); sessionStorage.clear()
  for (const k of CLAVES_DE_LOS_TOURS) localStorage.setItem(k, '1')
  localStorage.setItem('rendi_user', JSON.stringify({ name: 'Ana', email: 'ana@prueba.test', tier: 'pro' }))
  api.fijarPersonaDeLaPestana('ana@prueba.test')
  const m = await montar(el())
  await quieta(m)
  return m
}

describe('«Tu lista»: sumar a la watchlist ahí mismo', () => {
  it('se busca, se toca, y el activo aparece en la lista sin recargar', async () => {
    servidor.watchlist = []; servidor.pedidos = []
    const m = await abrir()
    expect(textoConCortes(m.contenedor)).toContain(SUMAR_A_LA_WATCHLIST)
    expect(textoConCortes(m.contenedor)).not.toMatch(/\bKO\b/)

    await escribir(campo(m), 'KO')
    await quieta(m)
    const ko = sugerencia(m, 'KO')
    expect(ko, 'no apareció KO en el desplegable').toBeTruthy()
    const antes = servidor.pedidos.filter(p => p === 'POST /tecnico/lista').length
    clic(m.contenedor, ko)
    const t = await quieta(m)

    expect(servidor.watchlist.map(w => w.symbol)).toEqual(['KO'])
    // La lista volvió a pedir lo suyo por el aviso de la watchlist…
    expect(servidor.pedidos.filter(p => p === 'POST /tecnico/lista').length).toBeGreaterThan(antes)
    // …y KO está abajo, en «En tu watchlist», con el aviso de que llegó.
    expect(t).toMatch(/En tu watchlist.*KO/)
    expect(t).toContain('Listo: KO ya aparece en tu lista.')
    await m.desmontar()
  }, 120000)

  it('lo que ya tenés o ya seguís se avisa y no se manda de nuevo', async () => {
    servidor.watchlist = [{ symbol: 'TSLA' }]; servidor.pedidos = []
    const m = await abrir()

    await escribir(campo(m), 'MELI')
    await quieta(m)
    const meli = sugerencia(m, 'MELI')
    expect(texto(meli)).toContain('En tu cartera')
    clic(m.contenedor, meli)
    let t = await quieta(m)
    expect(t).toContain('MELI ya está en tu lista: lo tenés en tu cartera.')

    await escribir(campo(m), 'TSLA')
    await quieta(m)
    const tsla = sugerencia(m, 'TSLA')
    expect(texto(tsla)).toContain('En tu watchlist')
    clic(m.contenedor, tsla)
    t = await quieta(m)
    expect(t).toContain('TSLA ya está en tu watchlist.')

    expect(servidor.pedidos).not.toContain('POST /watchlist')
    expect(servidor.watchlist.map(w => w.symbol)).toEqual(['TSLA'])
    await m.desmontar()
  }, 120000)

  it('Enter con el cuadro vacío no suma nada', async () => {
    // Antes sumaba el primero de los populares (AAPL) sin que nadie lo escribiera.
    // Con la lista ABIERTA, como en el navegador: al entrar al cuadro (`focusin`).
    // Sin abrirla, esta prueba quedaba verde aunque se borrara el arreglo
    // (auditoría de verificación 05/11, V12).
    servidor.watchlist = []; servidor.pedidos = []
    const m = await abrir()
    await enActo(async () => {
      const ev = { type: 'focusin', target: campo(m), bubbles: true, cancelable: true, defaultPrevented: false,
        timeStamp: Date.now(), preventDefault() {}, stopPropagation() {} }
      for (const fn of m.contenedor.escuchas.focusin || []) fn(ev)
    })
    expect(sugerencia(m, 'AAPL'), 'la lista de populares está abierta').not.toBeNull()
    await tecla(campo(m), 'Enter')
    await quieta(m)
    expect(servidor.pedidos).not.toContain('POST /watchlist')
    await m.desmontar()
  }, 120000)

  it('si la lista no puede volver a pedir lo suyo, el aviso lo dice en vez de quedarse esperando', async () => {
    servidor.watchlist = []; servidor.pedidos = []
    const m = await abrir()
    servidor.fallarLectura = true
    await escribir(campo(m), 'KO')
    await quieta(m)
    clic(m.contenedor, sugerencia(m, 'KO'))
    const t = await quieta(m)
    servidor.fallarLectura = false
    expect(servidor.watchlist.map(w => w.symbol)).toEqual(['KO'])
    expect(t).toContain('Sumamos KO a tu watchlist, pero no pudimos traer su lectura ahora.')
    // Lo que ya estaba sigue en pantalla.
    expect(t).toMatch(/En tu cartera.*MELI/)
    await m.desmontar()
  }, 120000)
})
