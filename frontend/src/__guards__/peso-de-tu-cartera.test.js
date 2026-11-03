// «Qué parte de tu cartera es» (el peso de un activo) se escribe con UNA
// función que ya sabe del ojito: utils/parteDeTuPlata.js. Nadie lo arma a mano.
//
// POR QUÉ ESTE TEST (re-test de la auditoría D, 29/10)
// ─────────────────────────────────────────────────────
// Con «Ocultar saldos» prendido, Novedades › Eventos seguía diciendo «3,40 % de
// tu cartera»: en Events.jsx un renglón lo tapaba y otros dos no; Noticias decía
// «afecta X% de tu cartera». El censo de ocultar-saldos-censo.test.js mira
// ARCHIVOS («¿este archivo pregunta por el ojito?») y Events.jsx preguntaba una
// vez: lo dio por bueno. Esto mira RENGLONES: todo número de peso que se dibuje
// tiene que pasar por parteDeTuPlata.js (pesoVisible / deTuCartera), que con el
// ojito prendido devuelve null.
import { describe, it, expect } from 'vitest'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import { pesoVisible, deTuCartera } from '../utils/parteDeTuPlata'

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const sinComentarios = (s) => s.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ''))
  .replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1')

// Un número pegado a «de tu cartera / de tu cartera», o el peso dibujado con
// pct()/toFixed. Los nombres con que viaja el peso: impactPct, weight_pct, peso.
// Segunda versión (re-test D, ronda 2): la primera buscaba nombres fijos
// (impactPct, weight_pct…) y sólo frases con `${…}`; Análisis fundamental dibuja
// `weight.toFixed(1)` y `{pctTxt(x)} de tu cartera` (JSX) y se le escaparon.
// Ahora: cualquier nombre que empiece con weight / peso / impact, y la frase
// armada tanto en un texto como en JSX con un pct…( ) o toFixed( ).
const ARMADO_A_MANO = [
  /\$\{[^}]*\}\s*%?\s*de tu (cartera|plata)/,
  /\{[^{}]*(pct\w*|toFixed)\([^{}]*\}\s*%?\s*de tu (cartera|plata)/,
  /\bpct\w*\(\s*(?:\w+\.)?(impact|weight|peso)\w*/i,
  /\b(impact|weight|peso)\w*\??\.toFixed\(/i,
]
// Renglones que dicen «de tu cartera» y NO son el peso, o que no van con el ojito.
const EXCEPCIONES = {
  'utils/parteDeTuPlata.js': 'la función',
  'utils/tusSenales.js': 'usa parteDeTuPlata; PLATA_ALCISTA_OCULTA no lleva número',
  'components/operations/CobrosView.jsx': '«X % de tu cartera por año»: lo que rinden los cobros, no un peso',
  'pages/Insights.jsx': '«X % de tu cartera valuada a precio real»: cobertura de precios, no un peso',
  'utils/diagnostics.js': 'DEUDA: Métricas (ver ocultar-saldos-censo)',
  'pages/ReportPublic.jsx': 'el informe público: lo ve otra gente, a propósito sin el ojito de quien lo mira',
  'utils/distributionAi.js': 'datos que van a la IA, no a la pantalla',
  'utils/demo.js': 'datos inventados del modo de prueba: no son la cartera de nadie',
}

function archivos(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const r = path.join(dir, e.name)
    if (e.isDirectory()) return ['__guards__', 'testing'].includes(e.name) ? [] : archivos(r)
    return /\.(jsx?)$/.test(e.name) && !/\.test\./.test(e.name) ? [r] : []
  })
}

describe('el peso en tu cartera sale de una sola función, que sabe del ojito', () => {
  it('la función: con el ojito prendido no dice nada; apagado, «menos de 1%» como en todos lados', () => {
    expect(pesoVisible(3.4, true)).toBeNull()
    expect(deTuCartera(3.4, true)).toBeNull()
    expect(pesoVisible(3.4, false)).toBe('3%')
    expect(deTuCartera(0.4, false)).toBe('menos de 1% de tu cartera')
  })

  it('ningún renglón arma el peso a mano', () => {
    const hallados = archivos(SRC).flatMap((r) => {
      const rel = path.relative(SRC, r).split(path.sep).join('/')
      if (EXCEPCIONES[rel]) return []
      return sinComentarios(fs.readFileSync(r, 'utf8')).split('\n')
        .flatMap((l, i) => (ARMADO_A_MANO.some((p) => p.test(l)) ? [`${rel}:${i + 1}  ${l.trim().slice(0, 110)}`] : []))
    })
    expect(hallados, 'usá pesoVisible / deTuCartera de utils/parteDeTuPlata.js').toEqual([])
  })
})

// EL ORDEN TAMBIÉN DICE CUÁNTO (auditoría D1+D5+D6, 31/10)
// ────────────────────────────────────────────────────────
// Con el ojito prendido, ordenar «de más a menos peso» delata cuál pesa más sin
// un solo % a la vista: el termómetro, «Mayor peso en tu cartera» de Tu lista
// y los activos que abría «Comparar» seguían en ese orden. Todo orden por peso
// pasa por ordenConElOjito (utils/parteDeTuPlata.js), que con el ojito ordena
// de la A a la Z: un comparador de peso sólo puede escribirse como su
// `sinOjito`. Hueco declarado: el orden que ya viene del SERVIDOR (de más a
// menos plata) no tiene comparador que buscar; lo cubren las pruebas montadas
// (utils/ordenConElOjito.render.test.jsx).
const ORDEN_POR_PESO = [
  /\b[ab]\.(peso|weight)\w*\b[^,;]*-\s*\(?\s*[ab]\.(peso|weight)\w*\b/,
  /\(\s*[ab]\.(peso|weight)\w*\s*(\|\||\?\?)\s*0\s*\)\s*-/,
]

describe('el orden por peso sabe del ojito', () => {
  it('ningún renglón ordena por peso sin pasar por ordenConElOjito', () => {
    const hallados = archivos(SRC).flatMap((r) => {
      const rel = path.relative(SRC, r).split(path.sep).join('/')
      if (rel === 'utils/demo.js') return []
      return sinComentarios(fs.readFileSync(r, 'utf8')).split('\n')
        .flatMap((l, i) => (ORDEN_POR_PESO.some((p) => p.test(l)) && !/\bsinOjito\s*:/.test(l)
          ? [`${rel}:${i + 1}  ${l.trim().slice(0, 110)}`] : []))
    })
    expect(hallados, 'ordená con ordenConElOjito(items, oculto, { sinOjito }) de utils/parteDeTuPlata.js').toEqual([])
  })

  it('el patrón ve el renglón que se escapó (Comparar, 9e6036e8)', () => {
    const viejo = 'return urlDeComparar(filas.filter(f => f.tenes).sort((a, b) => (b.peso || 0) - (a.peso || 0)).map(f => f.ruta))'
    expect(ORDEN_POR_PESO.some((p) => p.test(viejo))).toBe(true)
    expect(ORDEN_POR_PESO.some((p) => p.test('out.sort((a, b) => b.peso - a.peso || a.nombre.localeCompare(b.nombre))'))).toBe(true)
  })
})
