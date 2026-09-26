import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { cupoDe, vecesMas } from './prueba'
import { FREE_FEATURES, PLUS_FEATURES, PRO_FEATURES } from './planCatalog'

// ── Un cupo de plan se escribe UNA vez ──────────────────────────────────────
// Los números de los planes viven en el backend (`ai/quota.py`, `ai/plan.py`) y
// el frontend los tiene en UN solo lugar: el catálogo (`data/planCatalog.js`),
// que `backend/tests/test_promesas_vs_producto.py` compara contra el backend.
// Todo lo demás los lee de ahí (`cupoDe`, `vecesMas`) o del backend.
//
// Por qué existe: había copias sueltas y mentían sin que nada avisara —
// "10× más análisis IA (60/sem vs 6/sem)" en las listas de repuesto de los
// carteles (a un Free, que tiene 1: son 60×), "3× más Chat (9 vs 3)" (el Free
// tiene 1), "10× más análisis IA" en Configuración, "40 consultas/sem" y
// "9 consultas por semana" en la landing y en las de SEO. El 15/10 el Plus pasa
// a 2 análisis y casi todas iban a pasar a ser falsas el mismo día.

const SRC = fileURLToPath(new URL('..', import.meta.url))

function archivos(dir) {
  const out = []
  for (const nombre of readdirSync(dir)) {
    const ruta = join(dir, nombre)
    if (statSync(ruta).isDirectory()) {
      if (nombre !== 'node_modules' && nombre !== '__design__') out.push(...archivos(ruta))
    } else if (/\.(js|jsx)$/.test(nombre) && !/\.test\./.test(nombre)) {
      out.push(ruta)
    }
  }
  return out
}

// Sin comentarios: los que explican el bug citan las frases viejas a propósito.
const sinComentarios = (src) => src
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').filter(l => !l.trimStart().startsWith('//')).join('\n')

// Las formas en que un texto repetía un cupo de plan. Un número pegado a una de
// estas frases es una copia del catálogo (o del backend) que se va a quedar vieja.
const COPIAS = [
  /\d+\s*\/\s*sem\b/,                                    // "40/sem", "60/sem vs 6/sem"
  // "40 consultas/sem", "9 consultas por semana". No "escuchar gasta 1 consulta
  // más": eso es la regla de la voz (quota.reserve_listen), no un cupo de plan.
  /\d+\s+consultas?\s*(\/\s*sem|por semana)/,
  /\d+×\s*más\s+(análisis|consultas|chat)/i,             // "10× más análisis IA"
  /Hasta\s+\d+\s+brokers?/,                              // "Hasta 3 brokers"
  /vs\s+\d+\s+en\s+(Free|Plus)/,                         // "(vs 1 en Free)"
  /\d+\s+análisis\s+(IA\s+)?(por semana|\/\s*sem)/,        // "60 análisis por semana"
  /en vez de \d+/,                                       // "…en vez de 6"
  // "4 detectores", "6 detectores": un TOPE. "los 12 detectores" es el total
  // del producto (cuántos hay), no lo que da un plan: queda afuera a propósito.
  /(?<!los )\b\d+\s+detectores/,
  /respuestas habladas por semana/,                      // "Hasta 4 respuestas habladas…"
]

// El catálogo ES la copia vigilada: es el único que puede tener los números.
const PUEDE_TENERLOS = new Set(['data/planCatalog.js'])

describe('ningún texto del frontend repite un cupo de plan a mano', () => {
  const todos = archivos(SRC)

  it('el recorrido mira lo que tiene que mirar', () => {
    // Contra el falso verde: si el recorrido no encontrara archivos, pasaría.
    const rel = todos.map(r => relative(SRC, r))
    expect(rel.length).toBeGreaterThan(100)
    for (const esperado of ['components/plan/UpgradeModal.jsx', 'components/ai/UpgradePromoCard.jsx',
      'pages/Behavioral.jsx', 'pages/Landing.jsx', 'data/planCatalog.js']) {
      expect(rel).toContain(esperado)
    }
  })

  it('fuera del catálogo, ninguno', () => {
    const encontrados = []
    for (const ruta of todos) {
      const rel = relative(SRC, ruta)
      if (PUEDE_TENERLOS.has(rel)) continue
      const texto = sinComentarios(readFileSync(ruta, 'utf8'))
      for (const patron of COPIAS) {
        const m = texto.match(patron)
        if (m) encontrados.push(`${rel}: «${m[0]}»`)
      }
    }
    expect(encontrados).toEqual([])
  })

  it('los patrones cazan las frases que había (probado contra las viejas)', () => {
    // Si alguien afloja un patrón, esto se pone rojo antes de que vuelva la copia.
    const viejas = [
      '10× más análisis IA (60/sem vs 6/sem)',
      '3× más Chat Coach IA (9 consultas/sem vs 3)',
      'Hasta 3 brokers (vs 1 en Free)',
      'Eso es Pro (40 consultas/sem).',
      'Diagnóstico completo + 4 detectores de comportamiento',
      'Hasta 4 respuestas habladas por semana (en Free es 1)',
      '60 análisis por semana en vez de 6.',
    ]
    for (const frase of viejas) {
      expect(COPIAS.some(p => p.test(frase)), frase).toBe(true)
    }
  })

  it('la pantalla de Comportamiento no tiene el tope del Plus escrito', () => {
    const src = sinComentarios(readFileSync(join(SRC, 'pages/Behavioral.jsx'), 'utf8'))
    expect(src).not.toMatch(/PLUS_VISIBLE_COUNT/)
    // `|| 1` leía el "sin tope" (null) como una sola carta.
    expect(src).not.toMatch(/limit\('behavioral_tags_visible'\)\s*\|\|/)
    expect(src).toMatch(/planQueDestraba/)
  })
})

describe('vecesMas — el múltiplo entre dos cupos del catálogo', () => {
  it('lo dice sólo si la cuenta es exacta', () => {
    const a = { quotas: [{ label: 'X', value: '60' }] }
    const b = { quotas: [{ label: 'X', value: '6' }] }
    const c = { quotas: [{ label: 'X', value: '9' }] }
    expect(vecesMas(a, b, 'X')).toBe(10)
    expect(vecesMas(a, c, 'X')).toBeNull()        // 60/9: no hay múltiplo que decir
    expect(vecesMas(b, b, 'X')).toBeNull()        // 1×: no es "más"
    expect(vecesMas(a, { quotas: [{ label: 'X', value: '∞' }] }, 'X')).toBeNull()
    expect(vecesMas(a, {}, 'X')).toBeNull()
  })

  it('con el catálogo de verdad, es la cuenta entre sus cupos', () => {
    const pro = Number(cupoDe(PRO_FEATURES, 'Análisis IA / sem'))
    const free = Number(cupoDe(FREE_FEATURES, 'Análisis IA / sem'))
    const esperado = pro % free === 0 && pro / free > 1 ? pro / free : null
    expect(vecesMas(PRO_FEATURES, FREE_FEATURES, 'Análisis IA / sem')).toBe(esperado)
    expect(cupoDe(PLUS_FEATURES, 'Brokers')).toBeTruthy()
  })
})
