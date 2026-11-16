// Las landings de broker (/brokers/*), leídas como las lee Google: se dibujan de
// verdad y se mira el HTML, no las props.
//
// Tres cosas que no rompen nada si se pierden, y por eso tienen prueba:
//   1. Los pasos de descarga salen de la guía de la app (BROKER_GUIDES). Cocos,
//      IOL y Binance los tenían copiados a mano: cuando la guía se corregía, la
//      página pública seguía con el camino viejo y ningún test lo veía.
//   2. Cada landing de broker está enlazada desde las demás y desde la portada
//      (sale de data/guiasDeBrokers.js, que tiene que coincidir con la lista de
//      páginas públicas).
//   3. Las tres guías nuevas no son la misma página con otro nombre.
// Lo que dicen de impuestos lo vigila, para todas las páginas públicas,
// `__guards__/impuestos-bien-dichos.test.jsx`.
import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { HelmetProvider } from 'react-helmet-async'
import fs from 'node:fs'
import path from 'node:path'

// Sin sesión: lo que ve un visitante, que es lo que se publica escrito.
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ user: null, logout: () => {} }) }))

import { PAGINAS_PUBLICAS } from '../../paginasPublicas'
import { GUIAS_DE_BROKERS } from '../../data/guiasDeBrokers'
import { BROKER_GUIDES, pasosDeDescarga } from '../../components/import/BrokerInstructions'
import { sinComentarios } from '../../../scripts/texto-visible.mjs'

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#x27;')

const dibujar = async (ruta) => {
  const { default: Pagina } = await PAGINAS_PUBLICAS[ruta]()
  return renderToStaticMarkup(<HelmetProvider context={{}}><MemoryRouter><Pagina /></MemoryRouter></HelmetProvider>)
}

describe('la lista de landings de broker', () => {
  it('es la misma que la de páginas públicas: ninguna queda sin links', () => {
    const publicas = Object.keys(PAGINAS_PUBLICAS).filter(r => r.startsWith('/brokers/'))
    expect(new Set(GUIAS_DE_BROKERS.map(g => g.to))).toEqual(new Set(publicas))
  })

  it('cada una apunta a una guía que existe en la app', () => {
    for (const g of GUIAS_DE_BROKERS) {
      expect(BROKER_GUIDES.some(b => b.id === g.guia), `${g.to} → «${g.guia}»`).toBe(true)
    }
  })
})

describe('cada landing de broker', () => {
  for (const { to, guia: id } of GUIAS_DE_BROKERS) {
    describe(to, () => {
      const guia = BROKER_GUIDES.find(b => b.id === id)

      it('muestra los pasos de descarga de SU guía, todos, en orden', async () => {
        const html = await dibujar(to)
        const pasos = pasosDeDescarga(guia)
        // Contra el falso verde: una guía sin pasos haría pasar el bucle sin mirar nada.
        expect(pasos.length).toBeGreaterThan(1)
        let desde = 0
        for (const { texto } of pasos) {
          const i = html.indexOf(esc(texto), desde)
          expect(i, `falta (o está fuera de orden) el paso: «${texto.slice(0, 60)}…»`).toBeGreaterThan(-1)
          desde = i
        }
      })

      it('no muestra el paso que habla de la caja de subida del asistente («subí… acá»)', async () => {
        const html = await dibujar(to)
        for (const i of guia.pasosSoloAsistente || []) {
          expect(html).not.toContain(esc(guia.steps[i]))
        }
      })

      it('enlaza a todas las otras landings de broker', async () => {
        const html = await dibujar(to)
        for (const otra of GUIAS_DE_BROKERS.filter(g => g.to !== to)) {
          expect(html, `${to} no enlaza ${otra.to}`).toContain(`href="${otra.to}"`)
        }
      })
    })
  }

  it('la portada enlaza a todas', async () => {
    const { default: Landing } = await import('../Landing.jsx')
    const html = renderToStaticMarkup(<HelmetProvider context={{}}><MemoryRouter><Landing /></MemoryRouter></HelmetProvider>)
    for (const g of GUIAS_DE_BROKERS) expect(html, g.to).toContain(`href="${g.to}"`)
  })
})

describe('ninguna landing escribe a mano un camino del menú de su broker', () => {
  // Cada «Algo → Otra» de las guías ("Actividad → Movimientos", "Wallet →
  // Transaction"): si aparece en el código de una landing, alguien lo copió en
  // vez de leerlo de la guía, y la próxima corrección de la guía no le llega.
  const caminos = [...new Set(BROKER_GUIDES.flatMap(g => g.steps)
    .flatMap(s => [...s.matchAll(/(\S+) → (\S+)/g)].map(m => `${m[1]} → ${m[2].replace(/[.,;:)]+$/, '')}`)))]
  const dir = path.resolve(__dirname)
  const landings = fs.readdirSync(dir).filter(f => /\.jsx$/.test(f) && !/\.test\./.test(f))

  it('hay caminos y landings para mirar (contra el falso verde)', () => {
    expect(caminos.length).toBeGreaterThan(10)
    expect(landings).toEqual(expect.arrayContaining(['Cocos.jsx', 'IOL.jsx', 'Balanz.jsx', 'BullMarket.jsx', 'PPI.jsx', 'Binance.jsx']))
  })

  for (const f of landings) {
    it(f, () => {
      const ruta = path.join(dir, f)
      const codigo = sinComentarios(ruta, fs.readFileSync(ruta, 'utf8'))
      for (const c of caminos) expect(codigo, `${f} copia «${c}»`).not.toContain(c)
    })
  }
})

describe('las tres guías nuevas no son la misma página con otro nombre', () => {
  const NUEVAS = ['/brokers/balanz', '/brokers/bull-market', '/brokers/ppi']

  it('cada una tiene sus errores típicos, sin repetir ninguno', async () => {
    const titulos = []
    for (const to of NUEVAS) {
      const html = await dibujar(to)
      const seccion = html.split('Errores típicos')[1]?.split('</section>')[0] || ''
      const propios = [...seccion.matchAll(/<h3[^>]*>([^<]+)<\/h3>/g)].map(m => m[1])
      expect(propios.length, `${to} tiene ${propios.length} errores típicos`).toBeGreaterThanOrEqual(3)
      titulos.push(...propios)
    }
    expect(new Set(titulos).size).toBe(titulos.length)
  })

  it('título y descripción para Google, distintos en cada una', async () => {
    const metas = await Promise.all(GUIAS_DE_BROKERS.map(async ({ to }) => {
      const ctx = {}
      const { default: Pagina } = await PAGINAS_PUBLICAS[to]()
      renderToStaticMarkup(<HelmetProvider context={ctx}><MemoryRouter><Pagina /></MemoryRouter></HelmetProvider>)
      return [ctx.helmet.title.toString(), ctx.helmet.meta.toString()]
    }))
    expect(new Set(metas.map(m => m[0])).size).toBe(metas.length)
    expect(new Set(metas.map(m => m[1])).size).toBe(metas.length)
  })
})
