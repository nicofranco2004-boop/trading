// Censo de «Ocultar saldos»: cada archivo que le pide al servidor TU plata
// (posiciones, operaciones, movimientos, efectivo…) tiene que respetar el
// ojito, o estar en la lista de abajo con el porqué.
//
// POR QUÉ ESTE TEST
// ─────────────────
// Auditorías A3 y D4 (29/10): «Ocultar saldos» no es una regla de la app, es
// algo que cada pantalla pide a mano (usePrivacy). La ficha y Movimientos nunca
// lo pidieron y nadie se enteró: ninguna prueba miraba las pantallas que se
// olvidan. ocultar-saldos.render.test.jsx monta la ficha y Movimientos con el
// ojito prendido; esto es la red de abajo: un archivo NUEVO que traiga tu plata
// y no mire el ojito pone esto en rojo, y obliga a decidir.
//
// Cuenta como «lo mira»: usePrivacy, PrivacyMask, useHistoricalMoney (el
// formateador de plata de las listas, que esconde solo), OCULTO, o recibir el
// prop `oculto` de quien sí lo mira.
//
// La lista se achica sola: si un archivo de la lista empieza a mirar el ojito
// (o deja de traer plata), el test pide sacarlo, como el baseline de diseño.
//
// Hueco declarado: un componente que RECIBE montos por props sin pedirlos al
// servidor no entra en el censo (lo cubre la prueba de la pantalla que lo monta).
import { describe, it, expect } from 'vitest'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const TRAE_PLATA = /api\.(get|post)\(\s*['`"]\/(positions|operations|movements|cash|snapshots|dividends|summary|cobros|portfolio)/
const MIRA_EL_OJITO = /usePrivacy|PrivacyMask|useHistoricalMoney|\bOCULTO\b|\boculto\b/

// Archivos que traen tu plata y no miran el ojito, con el porqué.
export const SIN_OJITO = {
  // No muestran saldos (lo que muestran, la Cartera también lo deja a la vista).
  'components/AddPositionFlow.jsx': 'formulario: muestra lo que estás cargando',
  'components/onboarding/PositionStep.jsx': 'formulario del primer activo',
  'components/SplitRatioBanner.jsx': 'cantidades y precio de compra, como la Cartera',
  'components/alerts/AlertaForm.jsx': 'formulario de alerta: precios',
  'components/fundamentals/AnalyzeView.jsx': 'cantidad, costo por unidad y %, como la Cartera',
  'components/fundamentals/DetailPortfolioBlocks.jsx': 'cantidad, costo por unidad y %, como la Cartera',
  'components/fundamentals/CarteraList.jsx': 'lista de tus papeles, sin montos',
  'components/tesis/TesisPosiciones.jsx': 'tus tesis, sin montos',
  'pages/MobileSearch.jsx': 'buscador',
  'hooks/useCuponesPorCobrar.js': 'trae el dato; lo muestra DividendosPorCobrar, que sí mira el ojito',
  'hooks/useDividendosPorCobrar.js': 'trae el dato; lo muestra DividendosPorCobrar, que sí mira el ojito',
  'hooks/useMonthlyData.js': 'trae el dato; lo muestra MonthlySummary (abajo)',
  // DEUDA: muestran montos con el ojito prendido. Ya era así en main (29/10);
  // quedan anotadas para una ronda propia, fuera de la del análisis técnico.
  'components/MonthlySummary.jsx': 'DEUDA: el resumen del mes muestra montos',
  'pages/Goals.jsx': 'DEUDA: las metas muestran montos',
  'pages/FirstInsight.jsx': 'DEUDA: la bienvenida muestra valor, ganancia e invertido (se ve una vez, antes de prender nada)',
}

function archivos(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const r = path.join(dir, e.name)
    if (e.isDirectory()) return e.name === '__guards__' || e.name === 'testing' ? [] : archivos(r)
    return /\.(jsx?|tsx?)$/.test(e.name) && !/\.test\./.test(e.name) ? [r] : []
  })
}
const rel = (r) => path.relative(SRC, r).split(path.sep).join('/')
// Sin comentarios: «oculto» en un comentario no es mirar el ojito (pasó con
// AnalyzeView: «Con el buscador oculto…»).
const sinComentarios = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1')
const TODOS = archivos(SRC).map((r) => ({ ruta: rel(r), src: sinComentarios(fs.readFileSync(r, 'utf8')) }))
const conPlata = TODOS.filter((a) => TRAE_PLATA.test(a.src))

describe('«Ocultar saldos»: censo de lo que trae tu plata', () => {
  it('el censo encuentra las pantallas conocidas (contra el falso verde)', () => {
    const rutas = conPlata.map((a) => a.ruta)
    for (const r of ['pages/Positions.jsx', 'pages/Operations.jsx', 'pages/AssetDetail.jsx', 'pages/Dashboard.jsx']) {
      expect(rutas, r).toContain(r)
    }
  })

  it('cada archivo que trae tu plata mira el ojito o dice por qué no', () => {
    const sinDecidir = conPlata.filter((a) => !MIRA_EL_OJITO.test(a.src) && !SIN_OJITO[a.ruta]).map((a) => a.ruta)
    expect(sinDecidir, 'usá usePrivacy (o useHistoricalMoney) o anotalo en SIN_OJITO con el porqué').toEqual([])
  })

  it('la lista se achica: lo que ya mira el ojito o ya no trae plata sale de la lista', () => {
    const sobran = Object.keys(SIN_OJITO).filter((r) => {
      const a = TODOS.find((x) => x.ruta === r)
      return !a || !TRAE_PLATA.test(a.src) || MIRA_EL_OJITO.test(a.src)
    })
    expect(sobran).toEqual([])
  })
})
