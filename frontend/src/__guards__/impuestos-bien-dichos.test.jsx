// Lo que Rendi dice sobre impuestos en las páginas públicas.
//
// Auditoría SEO del 16/11/2026: 14 archivos decían que vender CEDEARs paga
// Ganancias («si la alícuota efectiva es 15 %… te puede ajustar + multa»), que
// la declaración vence en abril, que el valor de un CEDEAR es «precio × ratio»,
// que sus dividendos se cobran en pesos y que Rendi te da el «P&L declarable».
// Para una persona humana residente, vender CEDEARs y acciones argentinas en
// BYMA está exento (Ley de Ganancias, art. 26 inc. u); el ratio divide; BYMA
// paga los dividendos en dólares. Google mira con lupa la exactitud en temas de
// plata, y un contador que lee eso descarta la marca.
//
// Por qué la prueba ARMA las páginas en vez de leer los .jsx: el texto que
// leen Google y las IA es el que escribe scripts/prerender.mjs con
// prerender/entry-server.jsx, título y descripción incluidos. Buscar en los
// archivos fuente no ve un texto que viene de un componente compartido.
import { describe, it, expect, beforeAll } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { VENTA_EXENTA } from '../data/impuestos'

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

// Texto visible + título + descripción + datos para buscadores de una página.
function textoDe({ html, helmet }) {
  const cabeza = [helmet.title.toString(), helmet.meta.toString(), helmet.script.toString()].join(' ')
  const visible = html.replace(/<script[\s\S]*?<\/script>/g, ' ').replace(/<[^>]+>/g, ' ')
  return (visible + ' ' + cabeza)
    .replace(/&quot;/g, '"').replace(/&#x27;|&#39;/g, "'").replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/\s+/g, ' ')
}

const PROHIBIDAS = [
  [/declarab/i, '«declarable»: Rendi no arma la declaración; da la ganancia de cada venta para tu contador'],
  [/FIFO(?: automático)? (?:para (?:tu declaración )?(?:a )?)?(?:AFIP|ARCA)/i, '«FIFO para AFIP»: para CEDEARs y acciones argentinas la venta está exenta'],
  [/(?:AFIP|ARCA)[^.]{0,25}(?:exige|requiere|pide|acepta)[^.]{0,25}(?:FIFO|PEPS|promedio)/i, '«AFIP exige FIFO» dicho en general'],
  [/declarás (?:tu cripto )?a (?:AFIP|ARCA)/i, '«declarás a AFIP»: el reporte fiscal está «En construcción» en /planes'],
  [/(?:subyacente|acción)[^.]{0,40}× ?ratio/i, '«precio × ratio»: un CEDEAR es una fracción de la acción, el ratio divide'],
  [/dividendos[^.]{0,30}(?<!acreditan )(?:en ARS|en pesos)/i, 'BYMA paga los dividendos de CEDEARs en dólares (algunos brokers los pasan a pesos)'],
  [/subyacente en (?:NYSE|NASDAQ)/i, 'Rendi no valúa el CEDEAR con el precio de Nueva York: toma su precio en BYMA y lo pasa al MEP'],
  [/abril[^.]{0,40}vence|vence[^.]{0,40}abril/i, 'la declaración anual vence a mitad de año, no en abril'],
  [/alícuota efectiva/i, 'un ejemplo de impuesto sobre la venta de CEDEARs'],
  [/(?<!ex )\bAFIP\b/, '«AFIP» a secas: se llama ARCA desde octubre de 2024 (se puede decir «ARCA (ex AFIP)»)'],
]

let paginas = {}
beforeAll(async () => {
  globalThis.localStorage = almacenVacio()
  globalThis.sessionStorage = almacenVacio()
  const { render, RUTAS } = await import('../prerender/entry-server.jsx')
  for (const ruta of RUTAS) paginas[ruta] = textoDe(await render(ruta))
}, 60_000)

describe('las páginas públicas no dicen cosas equivocadas sobre impuestos', () => {
  it('ninguna frase de las que ya estuvieron mal', () => {
    const encontradas = []
    for (const [ruta, texto] of Object.entries(paginas)) {
      for (const [re, por] of PROHIBIDAS) {
        const m = texto.match(re)
        if (m) encontradas.push(`${ruta}: «${texto.slice(Math.max(0, m.index - 40), m.index + 60)}» → ${por}`)
      }
    }
    expect(encontradas, encontradas.join('\n')).toEqual([])
  })

  it('las páginas que hablan de vender CEDEARs dicen, con la frase compartida, que esa venta está exenta', () => {
    for (const ruta of ['/', '/cedears', '/brokers/cocos', '/blog/fifo-cedears-argentina', '/guia/cartera-y-operaciones']) {
      expect(paginas[ruta], `${ruta} no dice que la venta de CEDEARs está exenta`).toContain(VENTA_EXENTA)
    }
  })

  it('llms.txt y el HTML base (lo que leen las IA y quien no corre JavaScript) tampoco', () => {
    for (const archivo of ['public/llms.txt', 'index.html']) {
      const texto = leer(archivo)
      for (const [re, por] of PROHIBIDAS) {
        const m = texto.match(re)
        expect(m, `${archivo}: «${m && texto.slice(Math.max(0, m.index - 40), m.index + 60)}» → ${por}`).toBeNull()
      }
    }
    expect(leer('public/llms.txt'), 'llms.txt tiene que decirles a las IA que la venta de CEDEARs no paga Ganancias')
      .toMatch(/CEDEARs y acciones argentinas en BYMA no paga Ganancias/)
  })
})
