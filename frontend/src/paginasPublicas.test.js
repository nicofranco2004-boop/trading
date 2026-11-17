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

  it('robots.txt no le cierra la puerta a ninguna (leído como lo lee Google)', () => {
    const robots = leer('public/robots.txt')
    for (const ruta of RUTAS) {
      expect(googleDejaEntrar(robots, ruta), `robots.txt le cierra ${ruta} a Google`).toBe(true)
    }
  })
})

// ─── robots.txt, leído como lo lee Google ────────────────────────────────────
// La prueba anterior comparaba distinto que Google: tomaba «Disallow: /plan»
// como si cerrara sólo /plan y /plan/…, y para Google cierra TODA dirección que
// EMPIECE con ese texto (/planes incluida). Tampoco entendía «*» ni «$», ni
// que un Allow más largo le gana a un Disallow más corto. Así podía dar verde
// con un robots.txt que le cerraba una página pública a Google.
//
// Las reglas, según https://developers.google.com/search/docs/crawling-indexing/robots/robots_txt
//   · Google usa el grupo «User-agent: googlebot» si existe; si no, el de «*».
//   · Una regla vale para toda dirección que EMPIECE con su texto; «*» es
//     cualquier cosa y un «$» al final obliga a que la dirección termine ahí.
//   · Si valen varias, gana la de texto más largo; a igual largo, gana Allow.
//   · «Disallow:» vacío no cierra nada. Mayúsculas y minúsculas cuentan.
function reglasDeGoogle(robots) {
  const grupos = []
  let grupo = null
  let leyendoAgentes = false
  for (const cruda of robots.split(/\r?\n/)) {
    const linea = cruda.replace(/#.*/, '').trim()
    const m = /^([A-Za-z-]+)\s*:\s*(.*)$/.exec(linea)
    if (!m) continue
    const campo = m[1].toLowerCase()
    const valor = m[2].trim()
    if (campo === 'user-agent') {
      // Varias «User-agent» seguidas comparten las reglas que vienen abajo.
      if (!leyendoAgentes) { grupo = { agentes: [], reglas: [] }; grupos.push(grupo) }
      grupo.agentes.push(valor.toLowerCase())
      leyendoAgentes = true
    } else if (campo === 'allow' || campo === 'disallow') {
      leyendoAgentes = false
      if (grupo && valor) grupo.reglas.push({ permite: campo === 'allow', texto: valor })
    }
  }
  const propios = grupos.filter((g) => g.agentes.includes('googlebot'))
  return (propios.length ? propios : grupos.filter((g) => g.agentes.includes('*'))).flatMap((g) => g.reglas)
}

function reglaComoRegex(texto) {
  const anclada = texto.endsWith('$')
  const cuerpo = (anclada ? texto.slice(0, -1) : texto)
    .split('*').map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('.*')
  return new RegExp(`^${cuerpo}${anclada ? '$' : ''}`)
}

function googleDejaEntrar(robots, direccion) {
  let ganadora = null
  for (const r of reglasDeGoogle(robots)) {
    if (!reglaComoRegex(r.texto).test(direccion)) continue
    const largo = r.texto.length
    if (!ganadora || largo > ganadora.largo || (largo === ganadora.largo && r.permite)) ganadora = { largo, permite: r.permite }
  }
  return ganadora ? ganadora.permite : true
}

describe('robots.txt como lo lee Google', () => {
  // Los ejemplos de la documentación de Google. Los cuatro primeros los
  // contestaba mal la prueba anterior.
  const casos = [
    ['Disallow: /fish', '/fish.html', false],
    ['Disallow: /fish', '/fishheads/yummy.html', false],
    ['Disallow: /plan', '/planes', false],
    ['Disallow: /*.php$', '/carpeta/archivo.php', false],
    ['Disallow: /fish', '/Fish.asp', true],
    ['Disallow: /fish', '/catfish', true],
    ['Disallow: /fish/', '/fish', true],
    ['Disallow: /*.php$', '/archivo.php/', true],
    ['Allow: /p\nDisallow: /', '/page', true],
    ['Allow: /folder\nDisallow: /folder', '/folder/page', true],
    ['Allow: /page\nDisallow: /*.htm', '/page.htm', false],
    ['Allow: /$\nDisallow: /', '/', true],
    ['Allow: /$\nDisallow: /', '/page.htm', false],
    ['Disallow:', '/lo-que-sea', true],
  ]
  for (const [reglas, direccion, entra] of casos) {
    it(`${reglas.replace('\n', ' + ')} → ${direccion} ${entra ? 'entra' : 'no entra'}`, () => {
      expect(googleDejaEntrar(`User-agent: *\n${reglas}\n`, direccion)).toBe(entra)
    })
  }

  it('si hay un grupo para googlebot, Google usa ése y no el de «*»', () => {
    const robots = 'User-agent: *\nDisallow: /\n\nUser-agent: Googlebot\nDisallow: /privado\n'
    expect(googleDejaEntrar(robots, '/planes')).toBe(true)
    expect(googleDejaEntrar(robots, '/privado/x')).toBe(false)
  })

  // Las pantallas de la app y las direcciones que no existen dicen «noindex»
  // adentro de la página (dist/app.html). Si robots.txt las cierra, Google no
  // entra, no lo lee, y conserva la foto vieja que tenga (pasó con /imports).
  it('no le cierra a Google ninguna pantalla de la app: tiene que entrar a leer su «noindex»', () => {
    const robots = leer('public/robots.txt')
    const deLaApp = [...new Set([...fuenteDeApp.matchAll(/path="([^"]+)"/g)].map((m) => m[1]))]
      .filter((r) => r !== '*' && !RUTAS.includes(r))
      .map((r) => r.replace(/:\w+/g, 'x'))
    expect(deLaApp.length, 'no encontré las rutas de App.jsx').toBeGreaterThan(20)
    const cerradas = deLaApp.filter((r) => !googleDejaEntrar(robots, r))
    expect(cerradas, `robots.txt cierra: ${cerradas.join(', ')}`).toEqual([])
    expect(googleDejaEntrar(robots, '/esto-no-existe')).toBe(true)
  })

  // Para dibujar una página como la ve una persona, Google baja su JS, sus
  // estilos, sus letras y sus imágenes. Cerrar /assets/ «porque no son
  // páginas» (el mismo razonamiento que cierra /api/) le dejaría el texto sin
  // diseño.
  it('no le cierra a Google lo que las páginas necesitan para dibujarse', () => {
    const robots = leer('public/robots.txt')
    const archivos = ['/assets/x.js', '/assets/x.css', '/assets/x.woff2', '/founder.jpg',
      '/og-image-v3.png', '/video/rendi-en-un-minuto.jpg', '/rss.xml', '/sitemap.xml']
    const cerrados = archivos.filter((a) => !googleDejaEntrar(robots, a))
    expect(cerrados, `robots.txt cierra: ${cerrados.join(', ')}`).toEqual([])
  })

  it('/api/ sigue cerrado: son datos para la app, no páginas', () => {
    expect(googleDejaEntrar(leer('public/robots.txt'), '/api/auth/me')).toBe(false)
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

describe('los archivos que nombran los datos para Google existen', () => {
  // El logo de la Organization apuntaba a /favicon.svg, que nunca existió:
  // Vercel devolvía la página y Google se quedaba sin logo, sin ningún error.
  it('cada https://rendi.finance/<archivo> de index.html y de las notas del blog está en public/', () => {
    const fuentes = [leer('index.html'), leer('src/components/blog/BlogPost.jsx'), leer('src/components/PageMeta.jsx')]
    const nombrados = new Set()
    for (const f of fuentes) {
      for (const m of f.matchAll(/(?:https:\/\/rendi\.finance|\$\{BASE_URL\})(\/[\w./-]+\.(?:png|jpe?g|svg|webp|ico))/g)) nombrados.add(m[1])
    }
    expect(nombrados.size).toBeGreaterThan(0)
    for (const p of nombrados) {
      expect(fs.existsSync(path.join(raiz, 'public', p)), `${p} no está en public/`).toBe(true)
    }
  })
})
