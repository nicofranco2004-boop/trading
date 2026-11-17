// Lo que leen Google, las IA y los lectores de pantalla en las páginas públicas
// y en los archivos públicos sueltos (el manifiesto de la app, el manual de marca).
//
// Sale de la auditoría SEO del 16/11/2026, medida contra producción:
//   • Preguntas frecuentes: de las 10 respuestas, 1 estaba en el HTML. Las otras
//     9 vivían sólo en el bloque FAQPage para Google, que pide que lo marcado
//     esté a la vista de la persona (se dibujaban recién al abrirlas).
//   • El titular de la portada se leía «Todas tus inversiones,en un solo lugar.»:
//     el segundo renglón es otro elemento y entre los dos no había espacio.
//   • Las descripciones de Términos, Reembolso y Privacidad medían ~260-285
//     letras; Google muestra ~155 y corta el resto.
//   • Privacidad mandaba a la política de Rebill a una dirección que da 404.
//   • El manifiesto de la app decía lemas viejos.
//   • El manual de marca publicado mostraba un fundador inventado, una empleada
//     inventada, mails de un dominio que no es de Rendi y teléfonos que pueden
//     ser de cualquiera.
//   • Ninguna página pública enlazaba la guía para asesores.
//
// Por qué ARMA las páginas en vez de leer los .jsx: lo que reciben los robots es
// lo que escribe scripts/prerender.mjs con prerender/entry-server.jsx (como
// impuestos-bien-dichos.test.jsx). Buscar en el código fuente no ve si una
// respuesta se dibuja o no, ni si entre dos etiquetas queda un espacio.
import { describe, it, expect, beforeAll } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const raiz = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const leer = (f) => fs.readFileSync(path.join(raiz, f), 'utf8')

function almacenVacio() {
  const m = new Map()
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)) },
    removeItem: (k) => { m.delete(k) },
    clear: () => m.clear(),
    key: (i) => [...m.keys()][i] ?? null,
    get length() { return m.size },
  }
}

const decodificar = (s) => s
  .replace(/&quot;/g, '"').replace(/&#x27;|&#39;/g, "'").replace(/&lt;/g, '<')
  .replace(/&gt;/g, '>').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&')
const sinScripts = (html) => html.replace(/<script[\s\S]*?<\/script>/g, ' ')
// Las palabras a la vista, con un espacio donde había una etiqueta: sirve para
// buscar una frase, no para ver si dos palabras quedaron pegadas.
const visible = (html) => decodificar(sinScripts(html).replace(/<[^>]+>/g, ' ')).replace(/\s+/g, ' ')
// Lo que junta un robot o un lector de pantalla que lee los nodos de texto en
// fila: una etiqueta NO agrega un espacio. Así se leyó el titular en la auditoría.
const enFila = (html) => decodificar(sinScripts(html).replace(/<[^>]+>/g, '')).replace(/\s+/g, ' ').trim()

const metaDe = (helmet, nombre) => {
  const m = helmet.meta.toString().match(new RegExp(`name="${nombre}" content="([^"]*)"`))
  return m ? decodificar(m[1]) : null
}
const datosParaBuscadores = (helmet) => [...helmet.script.toString()
  .matchAll(/<script[^>]*type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/g)]
  .map((m) => JSON.parse(m[1]))
const hrefsExternos = (html) => [...html.matchAll(/href="(https?:\/\/[^"]+)"/g)].map((m) => decodificar(m[1]))

const RUTAS_QUE_MIRA = ['/', '/guia', '/terminos', '/reembolso', '/privacidad']
const paginas = {}
beforeAll(async () => {
  globalThis.localStorage = almacenVacio()
  globalThis.sessionStorage = almacenVacio()
  const { render } = await import('../prerender/entry-server.jsx')
  for (const ruta of RUTAS_QUE_MIRA) paginas[ruta] = await render(ruta)
}, 60_000)

describe('preguntas frecuentes de la portada: las 10 respuestas están en el HTML', () => {
  const faqDe = () => datosParaBuscadores(paginas['/'].helmet).find((d) => d['@type'] === 'FAQPage')

  it('lo que se le marca a Google como respuesta está escrito en la página', () => {
    const faq = faqDe()
    expect(faq, 'la portada perdió el bloque FAQPage').toBeTruthy()
    expect(faq.mainEntity.length).toBeGreaterThanOrEqual(10)
    const texto = visible(paginas['/'].html)
    const faltan = faq.mainEntity
      .filter((p) => !texto.includes(p.acceptedAnswer.text.replace(/\s+/g, ' ')))
      .map((p) => p.name)
    expect(faltan, `respuestas que sólo ve Google:\n${faltan.join('\n')}`).toEqual([])
  })

  it('cada botón dice si está abierto y qué región abre, y esa región existe', () => {
    const html = paginas['/'].html
    const seccion = html.slice(html.indexOf('id="faq"'))
    const botones = [...seccion.matchAll(/<button[^>]*aria-controls="([^"]+)"[^>]*>/g)]
    expect(botones.length).toBe(faqDe().mainEntity.length)
    for (const [boton, id] of botones) {
      expect(boton, `${id}: falta aria-expanded`).toMatch(/aria-expanded="(true|false)"/)
      expect(seccion, `${id}: el botón apunta a una región que no existe`).toMatch(new RegExp(`id="${id}"`))
    }
  })

  it('a la vista no cambia nada: arranca abierta sólo la primera, las otras ocultas', () => {
    const seccion = paginas['/'].html.slice(paginas['/'].html.indexOf('id="faq"'))
    const regiones = [...seccion.matchAll(/<div[^>]*role="region"[^>]*>/g)].map((m) => m[0])
    expect(regiones.length).toBe(faqDe().mainEntity.length)
    expect(regiones.filter((r) => !/\shidden=""/.test(r)).length, 'abiertas al cargar').toBe(1)
    expect(regiones[0]).not.toMatch(/\shidden=""/)
  })
})

describe('el titular de la portada se lee con su espacio', () => {
  it('«Todas tus inversiones, en un solo lugar.»', () => {
    const h1 = paginas['/'].html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/)
    expect(h1, 'la portada perdió su h1').toBeTruthy()
    expect(enFila(h1[1])).toBe('Todas tus inversiones, en un solo lugar.')
  })
})

describe('las descripciones de las páginas legales entran en lo que muestra Google', () => {
  // Google corta alrededor de 155 letras (no es un número oficial: es lo que
  // entra en el renglón). Lo esencial tiene que estar adentro: qué página es,
  // qué ley la rige y de cuándo es.
  const LEGALES = {
    '/terminos': { es: /^Términos y Condiciones de Rendi/, ley: /ley argentina/i },
    '/reembolso': { es: /^Política de reembolso de Rendi/, ley: /Ley 24\.240/ },
    '/privacidad': { es: /^Política de privacidad de Rendi/, ley: /Ley 25\.326/ },
  }
  for (const [ruta, { es, ley }] of Object.entries(LEGALES)) {
    it(`${ruta}: ≤155 letras, dice qué es, qué ley y la fecha de la página`, () => {
      const { html, helmet } = paginas[ruta]
      const descripcion = metaDe(helmet, 'description')
      expect(descripcion, `${ruta} sin descripción`).toBeTruthy()
      expect(descripcion.length, descripcion).toBeLessThanOrEqual(155)
      expect(descripcion).toMatch(es)
      expect(descripcion).toMatch(ley)
      // La fecha de la descripción es la del renglón «Última actualización»: si
      // alguien actualiza la página, la descripción no puede quedar en la vieja.
      const fecha = visible(html).match(/Última actualización: \d{1,2} de (\p{L}+ de \d{4})/u)
      expect(fecha, `${ruta}: no se encontró el renglón «Última actualización»`).toBeTruthy()
      expect(descripcion).toContain(fecha[1])
    })
  }
})

describe('los links a proveedores de las páginas legales son direcciones comprobadas', () => {
  // Cada dirección externa de Términos, Reembolso y Privacidad se abrió el
  // 16/11/2026 y llevó a la página que dice el texto. Un link nuevo no entra
  // sin comprobarlo: hay que abrirlo y sumarlo acá.
  //   • Rebill: rebill.com/legal/privacy daba 404. La vigente la enlazan sus
  //     propios términos para usuarios (rebill.com/politica-de-privacidad, que
  //     redirige a ésta): 200, «Rebill - Política de privacidad».
  //   • OpenAI: a curl le contesta 403 con un desafío de Cloudflare (es su
  //     muro contra robots, no un link roto); el Internet Archive la bajó con
  //     200 el 16/11/2026 15:17 UTC.
  //   • Meta: a curl le contesta 400 (bloquea lo que no es un navegador); con
  //     un lector web abre «Política de privacidad de Meta».
  const COMPROBADAS = new Set([
    'https://www.rebill.com/es/privacy-policy',
    'https://www.anthropic.com/legal/privacy',
    'https://openai.com/policies/privacy-policy',
    'https://resend.com/legal/privacy-policy',
    'https://policies.google.com/privacy',
    'https://www.facebook.com/privacy/policy',
    'https://tools.google.com/dlpage/gaoptout',
    'https://wa.me/542914373695',
  ])

  it('ninguna dirección sin comprobar', () => {
    const sinComprobar = ['/terminos', '/reembolso', '/privacidad']
      .flatMap((ruta) => hrefsExternos(paginas[ruta].html).filter((u) => !COMPROBADAS.has(u)).map((u) => `${ruta}: ${u}`))
    expect(sinComprobar).toEqual([])
  })

  it('Privacidad sigue mandando a la política de privacidad de Rebill (quien cobra)', () => {
    expect(hrefsExternos(paginas['/privacidad'].html)).toContain('https://www.rebill.com/es/privacy-policy')
  })
})

describe('el manifiesto de la app dice lo mismo que el sitio', () => {
  // Es lo que muestra el celular al instalar Rendi. Decía «Tu portfolio, con
  // IA» y «Mervall-E AI con memoria», lemas de antes. Ahora se ata al título
  // y a la descripción de index.html: si cambia uno, este test pide el otro.
  const manifiesto = JSON.parse(leer('public/site.webmanifest'))
  const indice = leer('index.html')
  const deIndice = (re) => decodificar(indice.match(re)?.[1] ?? '')

  it('nombre = el título para compartir de la portada; descripción = la de la portada', () => {
    expect(manifiesto.name).toBe(deIndice(/<meta property="og:title" content="([^"]+)"/))
    expect(manifiesto.description).toBe(deIndice(/<meta name="description" content="([^"]+)"/))
    expect(manifiesto.name).toMatch(/Todas tus inversiones/)
  })

  it('el nombre corto, el de debajo del ícono, sigue siendo «Rendi»', () => {
    expect(manifiesto.short_name).toBe('Rendi')
  })
})

describe('el manual de marca publicado no muestra datos que parezcan reales y no lo son', () => {
  // Se publica tal cual en rendi.finance/brand-kit/manual.html.
  const manual = leer('public/brand-kit/manual.html')

  it('ningún dominio rendi.fi (no es de Rendi)', () => {
    const m = manual.match(/.{0,40}\brendi\.fi(?!nance)\b.{0,20}/)
    expect(m?.[0] ?? null).toBeNull()
  })

  it('los mails son los que muestra el sitio', () => {
    const mails = [...new Set(manual.match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g) ?? [])]
    expect(mails.filter((m) => !['hola@rendi.finance', 'soporte@rendi.finance'].includes(m))).toEqual([])
  })

  it('ningún teléfono', () => {
    expect(manual.match(/\+\s?54[\d\s-]{6,}/)?.[0] ?? null).toBeNull()
  })

  it('ni personas inventadas: el fundador es Nicolás Pussetto', () => {
    expect(manual.match(/Pablo Pussetto|Sofía Méndez/)?.[0] ?? null).toBeNull()
    const conApellido = [...manual.matchAll(/(\p{L}+) Pussetto/gu)].map((m) => m[0])
    expect(conApellido.filter((n) => n !== 'Nicolás Pussetto')).toEqual([])
  })

  it('ni una ronda de inversión que no existió', () => {
    // Estaba dos veces: en una story («ronda seed») y en un post («SERIES SEED»).
    expect(manual.match(/ronda seed|series seed|cerramos nuestra ronda|\$2\.4M|OS financiero/i)?.[0] ?? null).toBeNull()
  })
})

describe('/guia enlaza la guía para asesores a quien llega sin sesión', () => {
  // Estaba sólo en la grilla de quien entra con cuenta de asesor: para Google y
  // para un asesor que todavía no tiene cuenta, /guia/asesores no existía.
  it('el HTML pre-escrito de /guia tiene el link', () => {
    const links = [...paginas['/guia'].html.matchAll(/<a [^>]*href="([^"]+)"/g)].map((m) => m[1])
    expect(links).toContain('/guia/asesores')
  })
})
