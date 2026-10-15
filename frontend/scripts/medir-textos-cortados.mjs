// Recorre las pantallas en modo demo a ancho de celular y lista los textos que
// se cortan con «…» mostrando menos del 60 % de lo que dicen.
//
// Por qué existe: el 2026-10-13, en Novedades → Eventos a 390 px, los títulos
// («Earnings de GOOGL») medían 0 px: los botones de la fila se comían todo y en
// pantalla quedaba sólo el logo. Ningún test lo veía, porque jsdom no mide
// anchos. Esto mide en un navegador de verdad.
//
// Uso (con `npx vite --port 5191` corriendo en frontend/):
//   npm i --no-save playwright-core
//   CHROME="/ruta/a/Chrome" node scripts/medir-textos-cortados.mjs 360,390
//
// Mide el TEXTO (cuánto se ve contra cuánto necesita), no el ancho a secas:
// «BTC» mide 22 px y está entero. Antes de confiar en un 0, se probó contra el
// código viejo: marcaba «Ex-dividendo de AAPL» con 0 de 147 px visibles.
// El cartel «Modo demo activo…» aparece siempre: es del demo y se corta a
// propósito.
import { chromium } from 'playwright-core'

const BASE = process.env.BASE || 'http://localhost:5191'
const ANCHOS = (process.argv[2] || '390').split(',').map(Number)
const RUTAS = [
  '/dashboard', '/posiciones', '/operaciones', '/novedades?tab=eventos',
  '/novedades?tab=noticias', '/analisis', '/insights', '/reportes', '/mensual',
  '/cobros', '/alertas', '/objetivos', '/comportamiento', '/config', '/mas',
  '/buscar', '/imports', '/fundamentals', '/wrapped', '/planes', '/ai',
]

const b = await chromium.launch({ executablePath: process.env.CHROME || undefined })
let total = 0
for (const w of ANCHOS) {
  const ctx = await b.newContext({ viewport: { width: w, height: 844 } })
  // El recorrido de bienvenida de Novedades tapa la lista.
  await ctx.addInitScript(() => { try { localStorage.setItem('rendi:tour:novedades:v2', '1') } catch { /* sin almacenamiento */ } })
  const p = await ctx.newPage()
  for (const r of RUTAS) {
    try {
      await p.goto(`${BASE}${r}${r.includes('?') ? '&' : '?'}demo=1`, { waitUntil: 'networkidle', timeout: 20000 })
    } catch { console.log(`${r} @${w}: no cargó`); continue }
    await p.waitForTimeout(2500)
    const cortados = await p.evaluate(() => {
      const out = []
      document.querySelectorAll('.truncate, .line-clamp-1, .line-clamp-2').forEach(el => {
        const txt = (el.textContent || '').trim()
        const cs = getComputedStyle(el)
        if (txt.length < 3 || cs.display === 'none' || !el.getClientRects().length) return
        if (el.scrollWidth <= el.clientWidth + 1) return
        if (el.clientWidth / el.scrollWidth < 0.6 && !txt.startsWith('Modo demo activo')) {
          out.push(`${el.clientWidth}/${el.scrollWidth}px «${txt.replace(/\s+/g, ' ').slice(0, 45)}»`)
        }
      })
      return out
    })
    total += cortados.length
    console.log(`${r} @${w}: ${cortados.length}${cortados.length ? '  ' + cortados.slice(0, 4).join(' · ') : ''}`)
  }
  await ctx.close()
}
await b.close()
console.log(total ? `\n${total} textos cortados` : '\nNingún texto cortado')
process.exit(total ? 1 : 0)
