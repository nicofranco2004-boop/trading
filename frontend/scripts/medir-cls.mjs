// medir-cls — cuánto se mueve sola una pantalla mientras carga (CLS, la medida
// de Google), contada como Chrome, y QUÉ se movió.
// ═══════════════════════════════════════════════════════════════════════════
// Nació con la auditoría SEO del 16/11/2026: con usuarios reales, el CLS del
// sitio en celulares era 0,43 (rojo; bueno es menos de 0,1). Con esto se
// encontró que la lista «Tu setup en Rendi» aparecía tarde arriba del inicio y
// empujaba todo (0,77) — ver hooks/useEsperaDeLaLista.js.
//
// Cómo cuenta: suma los saltos que Chrome reporta (PerformanceObserver
// 'layout-shift'), los agrupa en ráfagas (saltos a menos de 1 s entre sí, la
// ráfaga entera de menos de 5 s) y se queda con la peor, como Chrome.
// Además dibuja, cuadro a cuadro, dónde está y cuánto mide cada bloque de la
// pantalla: eso dice QUÉ caja cambió de alto.
//
// ⚠️ DOS COSAS QUE ENGAÑAN AL LEERLO
//   1. Un bloque que salta FUERA de la pantalla figura con «y …→0, alto …→0»:
//      Chrome recorta el rectángulo a lo visible. No es que subió: bajó tanto que
//      ya no se ve. (Así se leyó mal al principio: «sube 434 px» era «baja 992».)
//   2. Chrome no cuenta el mismo salto en todas las cargas: depende de en qué
//      cuadro cae. En una copia local, la lista se movía 4 de 4 veces y Chrome
//      lo contó 2. Por eso la prueba (pages/sinSaltosAlCargar.render.test.jsx)
//      mira cada dibujo, y por eso acá está la tabla cuadro a cuadro: es la
//      evidencia que no depende de la suerte.
//
// Condiciones: celular de Lighthouse (412 px, 4G lenta, CPU ×4) o compu.
// SÓLO GET: cualquier otro pedido se corta y se lista. Google Analytics, Meta y
// demás medidores, bloqueados (no ensuciar sus estadísticas). Usar el demo.
//
// Uso (desde frontend/):
//   npm i --no-save playwright-core        # una vez; usa el Chromium de Playwright
//   node scripts/medir-cls.mjs "https://rendi.finance/?demo=1" 4 15000
//   ANCHO=1350 node scripts/medir-cls.mjs "https://rendi.finance/?demo=1"          # compu
//   PRE_LS='{"rendi_checklist_dismissed":"1"}' node scripts/medir-cls.mjs …        # con la lista cerrada
//   npx vite build --outDir /tmp/x && DIST=/tmp/x node scripts/medir-cls.mjs …     # una compilación local
//   DETALLE=1 …                                  # la tabla cuadro a cuadro de TODAS las cargas
//   CHROME=/ruta/a/Chrome …                      # otro Chrome
//   RELOJ=2026-11-17T18:30:00-03:00 …            # el reloj de la página en esa hora
// RELOJ importa: el pre y el post mercado de EE.UU. (6:00–11:30 y 18:00–22:00 de
// Argentina) dibujan piezas que en la rueda no existen. El 16/11 se midió a las
// 17:30 (rueda), todo en verde, y a las 21:27 el inicio sin la lista daba 0,38–0,58.
// El demo arma el fuera de horario en el navegador con el reloj de la página, así
// que con RELOJ se reproduce a cualquier hora. Medir SIEMPRE rueda y fuera de horario.
// Con DIST, la página y sus archivos salen de esa carpeta (en la misma dirección
// rendi.finance) y sólo /api va a producción: sirve para comparar antes y después
// de un cambio en las mismas condiciones, sin publicar.
import { chromium } from 'playwright-core'
import fs from 'node:fs'
import path from 'node:path'

const url = process.argv[2] || 'https://rendi.finance/?demo=1'
const cargas = Number(process.argv[3] || 4)
const espera = Number(process.argv[4] || 15000)
const detalle = process.env.DETALLE === '1'
const preLs = process.env.PRE_LS ? JSON.parse(process.env.PRE_LS) : null
const ancho = Number(process.env.ANCHO || 412)
const celular = ancho < 768
const dist = process.env.DIST ? path.resolve(process.env.DIST) : null
const reloj = process.env.RELOJ ? new Date(process.env.RELOJ) : null
if (reloj && Number.isNaN(reloj.getTime())) throw new Error(`RELOJ no es una fecha: ${process.env.RELOJ}`)

const TIPOS = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2',
  '.ico': 'image/x-icon', '.webmanifest': 'application/manifest+json' }
function archivoLocal(u) {
  let f = path.join(dist, decodeURIComponent(new URL(u).pathname))
  if (!f.startsWith(dist) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) f = path.join(dist, 'index.html')
  return { body: fs.readFileSync(f), contentType: TIPOS[path.extname(f)] || 'application/octet-stream' }
}

// Los medidores de terceros. Las fuentes de Google NO: cambiar de letra también
// mueve la pantalla, y eso le pasa al usuario de verdad.
const BLOQUEADOS = /google-analytics|googletagmanager|googleadservices|doubleclick|google\.com\/(ccm|pagead)|facebook\.(net|com)|fbcdn|clarity\.ms|hotjar/

// Se inyecta antes que cualquier script de la página.
const INIT = `(() => {
  const desc = (n) => {
    if (!n || n.nodeType !== 1) return n ? '#text' : '(nodo borrado)'
    const cls = (n.className && typeof n.className === 'string') ? '.' + n.className.trim().split(/\\s+/).slice(0, 4).join('.') : ''
    const txt = (n.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 50)
    return n.tagName.toLowerCase() + cls + (txt ? ' «' + txt + '»' : '')
  }
  const r = (x) => x ? { y: Math.round(x.y), h: Math.round(x.height) } : null
  window.__saltos = []
  new PerformanceObserver((l) => {
    for (const e of l.getEntries()) {
      window.__saltos.push({
        t: Math.round(e.startTime), v: e.value, input: e.hadRecentInput,
        fuentes: (e.sources || []).map(s => ({ nodo: desc(s.node), antes: r(s.previousRect), despues: r(s.currentRect) })),
      })
    }
  }).observe({ type: 'layout-shift', buffered: true })

  // Los bloques de la pantalla, cuadro a cuadro: la raíz es el padre de la
  // sección «Tu cartera» (inicio del celular) o el <main>.
  window.__altos = []
  let previo = ''
  const raiz = () => {
    const tc = [...document.querySelectorAll('section')].find(n => /^Tu cartera/.test((n.innerText || '').trim()))
    return tc ? tc.parentElement : (document.querySelector('main') || document.body)
  }
  const tick = () => {
    const root = raiz()
    if (root) {
      const filas = [...root.children].map((c, i) => {
        const b = c.getBoundingClientRect()
        return i + ':' + c.tagName.toLowerCase() + '@' + Math.round(b.top) + '+' + Math.round(b.height)
      }).join(' | ')
      if (filas !== previo) {
        previo = filas
        window.__altos.push({ t: Math.round(performance.now()), filas, raiz: desc(root).slice(0, 60),
          hijos: [...root.children].map(c => desc(c).slice(0, 90)) })
      }
    }
    if (performance.now() < ${espera + 5000}) requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
})()`

function peorRafaga(saltos) {
  let peor = 0, actual = 0, ini = -1, ult = -1, ventana = [], mejor = []
  for (const s of saltos) {
    if (s.input) continue
    if (ini >= 0 && s.t - ult < 1000 && s.t - ini < 5000) { actual += s.v; ventana.push(s) }
    else { actual = s.v; ini = s.t; ventana = [s] }
    ult = s.t
    if (actual > peor) { peor = actual; mejor = [...ventana] }
  }
  return { cls: peor, ventana: mejor }
}

const browser = await chromium.launch({ headless: true, ...(process.env.CHROME ? { executablePath: process.env.CHROME } : {}) })
const resultados = []
for (let i = 0; i < cargas; i++) {
  const ctx = await browser.newContext({
    ...(celular ? {
      viewport: { width: ancho, height: 823 }, deviceScaleFactor: 1.75, isMobile: true, hasTouch: true,
      userAgent: 'Mozilla/5.0 (Linux; Android 11; moto g power (2022)) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36',
    } : { viewport: { width: ancho, height: 940 } }),
    locale: 'es-AR', timezoneId: 'America/Argentina/Buenos_Aires',
  })
  const cortados = []
  await ctx.route('**/*', (route) => {
    const req = route.request()
    if (BLOQUEADOS.test(req.url())) return route.abort()
    if (req.method() !== 'GET') { cortados.push(req.method() + ' ' + req.url()); return route.abort() }
    if (dist && /^https:\/\/rendi\.finance\//.test(req.url()) && !/\/api\//.test(req.url())) {
      return route.fulfill({ status: 200, ...archivoLocal(req.url()) })
    }
    return route.continue()
  })
  if (preLs) await ctx.addInitScript((kv) => { for (const [k, v] of Object.entries(kv)) localStorage.setItem(k, v) }, preLs)
  await ctx.addInitScript(INIT)
  // El reloj de la página arranca en RELOJ y sigue andando (se corre la hora, no
  // se congela: con page.clock.setFixedTime la página no terminaba de cargar).
  if (reloj) {
    await ctx.addInitScript((desfase) => {
      const Real = Date
      const ahora = () => Real.now() + desfase
      class Corrida extends Real {
        constructor(...a) { super(...(a.length ? a : [ahora()])) }
        static now() { return ahora() }
      }
      globalThis.Date = Corrida
    }, reloj.getTime() - Date.now())
  }
  const page = await ctx.newPage()
  const cdp = await ctx.newCDPSession(page)
  await cdp.send('Network.enable')
  // Celular: la 4G lenta de Lighthouse (150 ms de ida y vuelta, 1,6 Mb/s) con el
  // factor que aplica DevTools, y el procesador 4 veces más lento. Compu: red buena.
  await cdp.send('Network.emulateNetworkConditions', celular
    ? { offline: false, latency: 562.5, downloadThroughput: 1474.56 * 1024 / 8, uploadThroughput: 675 * 1024 / 8 }
    : { offline: false, latency: 40, downloadThroughput: 10240 * 1024 / 8, uploadThroughput: 10240 * 1024 / 8 })
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: celular ? 4 : 1 })
  await page.goto(url, { waitUntil: 'load', timeout: 120000 })
  await page.waitForTimeout(espera)
  const saltos = await page.evaluate(() => window.__saltos)
  const altos = await page.evaluate(() => window.__altos)
  const { cls, ventana } = peorRafaga(saltos)
  resultados.push(cls)
  console.log(`\n── carga ${i + 1}: CLS ${cls.toFixed(3)}  (${saltos.length} saltos en total, ${ventana.length} en la peor ráfaga)`)
  for (const s of ventana) {
    console.log(`   t=${s.t} ms  valor ${s.v.toFixed(3)}`)
    for (const f of s.fuentes) {
      const fuera = f.despues && f.despues.h === 0 && f.antes?.h > 0 ? '  ← quedó FUERA de la pantalla' : ''
      const dy = f.antes && f.despues ? f.despues.y - f.antes.y : null
      const dh = f.antes && f.despues ? f.despues.h - f.antes.h : null
      console.log(`     · ${f.nodo}\n       y ${f.antes?.y}→${f.despues?.y} (${dy >= 0 ? '+' : ''}${dy})  alto ${f.antes?.h}→${f.despues?.h} (${dh >= 0 ? '+' : ''}${dh})${fuera}`)
    }
  }
  if (detalle || i === 0) {
    console.log('   bloques de la pantalla, cuadro a cuadro (índice:etiqueta@arriba+alto, en px):')
    for (const a of altos) console.log(`     t=${a.t}  ${a.filas}`)
    const ult = altos[altos.length - 1]
    if (ult) { console.log('   raíz: ' + ult.raiz); ult.hijos.forEach((h, k) => console.log(`     ${k}: ${h}`)) }
  }
  if (cortados.length) console.log('   pedidos que NO eran GET (cortados): ' + cortados.join(', '))
  await ctx.close()
}
await browser.close()
console.log(`\nRESUMEN ${url}${dist ? ' [' + path.basename(dist) + ']' : ''}${preLs ? ' ' + JSON.stringify(preLs) : ''}${celular ? '' : ' (compu)'}${reloj ? ' reloj ' + process.env.RELOJ : ''}: CLS por carga = ${resultados.map(x => x.toFixed(3)).join(', ')}`)
