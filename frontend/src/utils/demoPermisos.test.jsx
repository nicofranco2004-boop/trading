// 🔴 EL DEMO DICE QUE SÍ A LO MISMO QUE EL PRO (2026-10-21).
//
// El demo contesta /plan/features con una copia escrita a mano de la fila
// 'pro' de backend/ai/plan.py. Cuando el servidor sumó 'alerts.pct_move', la
// copia no se enteró: quien entraba al demo tocaba «Se mueve un %» en Alertas
// y leía «Los avisos por % son de Rendi Plus» — justo lo que el video del
// 21/10 invita a probar. Y el «Crear alerta −10 %» de Mervall-E abría el de
// precio, vacío.
//
// Acá se cruzan tres listas:
//   · la del servidor (FEATURE_IDS y la fila 'pro' de PLAN_LIMITS, leídas del
//     archivo, con cualquier comilla; si queda una entrada sin leer, rojo);
//   · la del demo (lo que contesta handleDemoRequest);
//   · la de la pantalla: cada `can('…')` y `limit('…')` del código de la app.
//
// Lo que NO ve el recorrido de la pantalla: un permiso pedido por un alias
// (`const puede = can; puede('x')`) o leído directo de `access`. Si la
// pantalla le pasa a `can(` algo que no es un texto fijo, la prueba falla en
// vez de saltearlo.
import { describe, it, expect, vi } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../hooks/usePushNotifications', () => ({
  usePushNotifications: () => ({ supported: false, permission: 'default', subscribed: false, subscribe: vi.fn(), unsubscribe: vi.fn() }),
}))
vi.mock('./api', () => ({ api: { get: vi.fn(() => Promise.resolve({})) } }))

import { handleDemoRequest } from './demo.js'
import AlertaForm from '../components/alerts/AlertaForm'

const AQUI = dirname(fileURLToPath(import.meta.url))
const SRC = resolve(AQUI, '..')
const PLAN_PY = readFileSync(resolve(AQUI, '../../../backend/ai/plan.py'), 'utf8')
const DEMO = handleDemoRequest('GET', '/plan/features')

const sinComentariosPy = (py) => py.replace(/#[^\n]*/g, '')
const valorPy = (v) => (v === 'True' ? true : v === 'False' ? false : v === 'None' ? null : Number(v))

// "clave": valor, … de un bloque de Python. Cuenta las entradas para no
// saltear en silencio una que la expresión no supo leer.
function leerDict(cuerpo, que) {
  const limpio = sinComentariosPy(cuerpo)
  const pares = [...limpio.matchAll(/['"]([\w.]+)['"]\s*:\s*(True|False|None|-?\d+(?:\.\d+)?)\s*,?/g)]
  const entradas = limpio.split('\n').filter(l => l.includes(':'))
  expect(pares.length, `hay una entrada de ${que} que no se pudo leer`).toBe(entradas.length)
  return Object.fromEntries(pares.map(m => [m[1], valorPy(m[2])]))
}

function featureIds() {
  const bloque = PLAN_PY.match(/^FEATURE_IDS = \{([\s\S]*?)\n\}/m)
  expect(bloque, 'no encontré FEATURE_IDS en ai/plan.py').toBeTruthy()
  const cuerpo = sinComentariosPy(bloque[1])
  const ids = [...cuerpo.matchAll(/['"]([\w.]+)['"]/g)].map(m => m[1])
  const entradas = cuerpo.split(',').map(x => x.trim()).filter(Boolean)
  expect(ids.length, 'hay una entrada de FEATURE_IDS que no se pudo leer').toBe(entradas.length)
  return new Set(ids)
}

// La fila 'pro' de PLAN_LIMITS: sus topes y su `can_access`.
function filaPro() {
  const bloque = PLAN_PY.match(/^    "pro": \{\n([\s\S]*?)\n    \},/m)
  expect(bloque, 'no encontré la fila "pro" de PLAN_LIMITS').toBeTruthy()
  const acceso = bloque[1].match(/"can_access": \{\n([\s\S]*?)\n\s*\},/)
  expect(acceso, 'no encontré el can_access de la fila "pro"').toBeTruthy()
  const topes = bloque[1].slice(0, acceso.index)
  return { topes: leerDict(topes, 'la fila "pro"'), acceso: leerDict(acceso[1], 'el can_access del "pro"') }
}

// Cada `can(…)` / `limit(…)` del código de la app (no de las pruebas).
function loQuePreguntaLaPantalla() {
  const archivos = []
  const recorrer = (dir) => {
    for (const n of readdirSync(dir)) {
      const p = join(dir, n)
      if (statSync(p).isDirectory()) { if (n !== 'testing' && n !== '__design__') recorrer(p); continue }
      if (/\.(js|jsx)$/.test(n) && !/\.test\./.test(n)) archivos.push(p)
    }
  }
  recorrer(SRC)
  const can = new Map(), limit = new Map(), ilegibles = []
  for (const p of archivos) {
    // Sin comentarios: los que cuentan la historia nombran `can('export.csv')`.
    const codigo = readFileSync(p, 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1')
    for (const m of codigo.matchAll(/\b(can|limit)\(\s*([^)]*?)\s*\)/g)) {
      const fijo = m[2].match(/^['"`]([\w.]+)['"`]$/)
      const donde = relative(SRC, p)
      if (!fijo) { ilegibles.push(`${donde}: ${m[0]}`); continue }
      const lista = m[1] === 'can' ? can : limit
      lista.set(fijo[1], [...(lista.get(fijo[1]) || []), donde])
    }
  }
  return { can, limit, ilegibles }
}

describe('el demo contesta /plan/features como el plan Pro', () => {
  it('los mismos permisos que la fila "pro" del servidor, clave por clave', () => {
    const ids = featureIds()
    const { acceso } = filaPro()
    // El servidor sólo manda lo declarado en FEATURE_IDS (get_plan_features).
    const delServidor = Object.fromEntries(Object.entries(acceso).filter(([k]) => ids.has(k)))
    expect(delServidor['alerts.pct_move']).toBe(true)
    expect(DEMO.access).toEqual(delServidor)
  })

  it('los topes que la pantalla usa son los del Pro', () => {
    const { topes } = filaPro()
    for (const k of ['brokers_max', 'behavioral_tags_visible', 'alerts_max']) {
      expect(k in DEMO.limits, `el demo no manda limits.${k}`).toBe(true)
      expect(DEMO.limits[k], `limits.${k}`).toBe(topes[k])
    }
  })
})

describe('lo que pregunta la pantalla existe en el servidor y el demo lo contesta', () => {
  const { can, limit, ilegibles } = loQuePreguntaLaPantalla()

  it('cada `can(` y `limit(` de la app pide un nombre fijo (si no, esta prueba no lo ve)', () => {
    expect(ilegibles).toEqual([])
    // Si un día la búsqueda no encuentra nada, la prueba no prueba nada.
    expect([...can.keys()]).toEqual(expect.arrayContaining(['alerts.pct_move', 'export.csv', 'reportes.historicos']))
    expect([...limit.keys()]).toEqual(expect.arrayContaining(['alerts_max', 'behavioral_tags_visible']))
  })

  it('cada permiso que pregunta la pantalla es uno que el servidor conoce (un error de tipeo da «no» para siempre)', () => {
    const ids = featureIds()
    const desconocidos = [...can].filter(([id]) => !ids.has(id)).map(([id, donde]) => `${id} (${donde.join(', ')})`)
    expect(desconocidos).toEqual([])
  })

  it('el demo contesta cada permiso y cada tope que la pantalla pregunta', () => {
    const sinRespuesta = [
      ...[...can].filter(([id]) => !(id in DEMO.access)).map(([id, donde]) => `can('${id}') en ${donde.join(', ')}`),
      ...[...limit].filter(([k]) => !(k in DEMO.limits)).map(([k, donde]) => `limit('${k}') en ${donde.join(', ')}`),
    ]
    expect(sinRespuesta).toEqual([])
  })
})

describe('Alertas en el demo: el aviso por % está abierto', () => {
  // La misma regla que usePlanFeatures: `access[id] === true`.
  const plan = { can: (f) => DEMO.access[f] === true, limit: (k) => DEMO.limits[k] }
  const html = (props) => renderToStaticMarkup(
    <MemoryRouter><AlertaForm plan={plan} onClose={() => {}} {...props} /></MemoryRouter>)

  it('«Se mueve un %» sin el candado de Plus', () => {
    const h = html()
    expect(h).toContain('Se mueve un %')
    expect(h).not.toMatch(/>Plus</)
  })

  it('«Crear alerta −10 %» de Mervall-E abre el aviso por % con el 10 cargado', () => {
    const h = html({ prefill: { symbol: 'BTC', downPct: 10 } })
    expect(h).toContain('Si cae más de')
    expect([...h.matchAll(/<input[^>]*value="([^"]*)"/g)].map(m => m[1])).toContain('10')
  })
})
