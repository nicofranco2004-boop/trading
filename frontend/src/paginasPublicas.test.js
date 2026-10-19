// Las páginas públicas tienen que estar en CUATRO lugares a la vez, y si falta
// uno no da error: la página sigue andando para la gente y el robot de una IA
// recibe la cáscara vacía (o Google no se entera de que existe). Este test ata
// los cuatro a la lista única de paginasPublicas.js.
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { PAGINAS_PUBLICAS } from './paginasPublicas'
import fuenteDeApp from './App.jsx?raw'

const raiz = path.resolve(__dirname, '..')
const RUTAS = Object.keys(PAGINAS_PUBLICAS)
const leer = (f) => fs.readFileSync(path.join(raiz, f), 'utf8')

describe('las páginas públicas', () => {
  it('cada una tiene su ruta en los DOS árboles de App.jsx (con y sin sesión)', () => {
    for (const ruta of RUTAS) {
      const veces = fuenteDeApp.split(`path="${ruta}"`).length - 1
      expect(veces, `${ruta} aparece ${veces} veces en App.jsx`).toBe(2)
    }
  })

  it('Vercel manda cada una a su archivo ya escrito, antes del comodín de la app', () => {
    const { rewrites } = JSON.parse(leer('vercel.json'))
    const comodin = rewrites.findIndex((r) => r.destination === '/app.html')
    expect(comodin, 'falta el comodín a /app.html').toBeGreaterThan(-1)
    for (const ruta of RUTAS.filter((r) => r !== '/')) {
      const i = rewrites.findIndex((r) => r.source === ruta && r.destination === `${ruta}/index.html`)
      expect(i, `${ruta} no tiene rewrite a su archivo`).toBeGreaterThan(-1)
      expect(i, `${ruta} está después del comodín: nunca se usaría`).toBeLessThan(comodin)
    }
  })

  it('ninguna se guarda vieja en el navegador (igual que "/": Safari guarda el HTML y apunta a pedazos que ya no existen)', () => {
    const { headers } = JSON.parse(leer('vercel.json'))
    const sinCache = headers
      .filter((h) => h.headers.some((x) => x.key === 'Cache-Control' && x.value.includes('no-store')))
      .map((h) => new RegExp(`^${h.source}$`))
    for (const ruta of RUTAS) {
      expect(sinCache.some((re) => re.test(ruta)), `${ruta} no tiene Cache-Control: no-store`).toBe(true)
    }
  })

  it('el sitemap las lista todas, y nada más', () => {
    const enSitemap = [...leer('public/sitemap.xml').matchAll(/<loc>https:\/\/rendi\.finance([^<]*)<\/loc>/g)]
      .map((m) => m[1] || '/')
    expect(new Set(enSitemap)).toEqual(new Set(RUTAS))
  })

  it('robots.txt no le cierra la puerta a ninguna', () => {
    const cerradas = [...leer('public/robots.txt').matchAll(/^Disallow:\s*(\S+)/gm)].map((m) => m[1])
    for (const ruta of RUTAS) {
      for (const c of cerradas) {
        expect(ruta === c || ruta.startsWith(c.endsWith('/') ? c : `${c}/`), `${c} bloquea ${ruta}`).toBe(false)
      }
    }
  })
})

describe('lazyPublica: la página escrita no pasa por el esqueleto gris', () => {
  // Se prueba con el renderizador del servidor: igual que el navegador, con
  // un lazy sin resolver dibuja el `fallback` (el esqueleto) y con uno
  // resuelto en el acto dibuja la página.
  const dibujar = async (C) => {
    const { renderToString } = await import('react-dom/server')
    const { Suspense, createElement } = await import('react')
    return renderToString(createElement(Suspense, { fallback: 'ESQUELETO' }, createElement(C)))
  }
  const Pagina = () => 'LA PAGINA'

  it('sin precargar, muestra el esqueleto (lo que pasaba antes)', async () => {
    const { lazyPublica } = await import('./paginasPublicas')
    const C = lazyPublica(() => Promise.resolve({ default: Pagina }))
    expect(await dibujar(C)).toContain('ESQUELETO')
  })

  it('precargada, dibuja la página de una', async () => {
    const { lazyPublica } = await import('./paginasPublicas')
    const C = lazyPublica(() => Promise.resolve({ default: Pagina }))
    await C.precargar()
    const html = await dibujar(C)
    expect(html).toContain('LA PAGINA')
    expect(html).not.toContain('ESQUELETO')
  })

  it('una ruta que no es pública monta sin esperar nada', async () => {
    const { precargarPaginaPublica } = await import('./paginasPublicas')
    await expect(precargarPaginaPublica('/ruta-que-no-existe')).resolves.toBeUndefined()
  })
})
