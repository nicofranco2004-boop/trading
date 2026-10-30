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

// Un número pegado a «de tu cartera / de tu plata», o el peso dibujado con
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
