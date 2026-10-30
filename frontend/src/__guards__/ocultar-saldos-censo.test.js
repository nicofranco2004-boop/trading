// Censo de «Ocultar saldos»: cada archivo que le pide al servidor TU plata
// tiene que respetar el ojito, o estar en la lista de abajo con el porqué.
//
// POR QUÉ ESTE TEST
// ─────────────────
// Auditorías A3 y D4 (29/10): «Ocultar saldos» no es una regla de la app, es
// algo que cada pantalla pide a mano (usePrivacy). La ficha y Movimientos nunca
// lo pidieron y nadie se enteró. ocultar-saldos.render.test.jsx y
// ocultar-saldos-cartera.render.test.jsx montan esas pantallas con el ojito
// prendido; esto es la red de abajo.
//
// SEGUNDA VERSIÓN (re-test de la auditoría A, 29/10). La primera vigilaba una
// lista de rutas elegida a mano (/positions, /operations…) y por eso no vio
// /futures ni /events/portfolio: Futuros y el calendario de eventos mostraban
// plata con el ojito prendido. Ahora TODAS las rutas que pide la pantalla
// están clasificadas en RUTAS (plata tuya / mercado / tu cuenta): una ruta
// nueva sin clasificar pone esto en rojo y obliga a decidir. Ya no hay
// «la lista de las que importan».
//
// Cuenta como «lo mira» (sin comentarios): usePrivacy, PrivacyMask, los
// formateadores que tapan solos (useHistoricalMoney, useMoneyFormat), OCULTO o
// recibir el prop `oculto` de quien sí lo mira.
//
// La lista SIN_OJITO se achica sola: si un archivo empieza a mirar el ojito (o
// deja de traer plata), el test pide sacarlo, como el baseline de diseño.
//
// Huecos declarados: (1) un componente que RECIBE montos por props sin pedirlos
// al servidor no entra (lo cubre la prueba de la pantalla que lo monta); (2) un
// pedido con la ruta en una variable (`api.get(url)`) no se ve; (3) que un
// archivo «mire el ojito» no prueba que tape TODO: eso lo dicen las pruebas
// montadas.
import { describe, it, expect } from 'vitest'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

// Cada ruta del servidor que pide la pantalla, por lo que trae. Ante la duda,
// 'plata' (la que obliga a decidir).
export const RUTAS = {
  plata: ['advisor', 'positions', 'operations', 'imports', 'monthly', 'plazos-fijos', 'goals', 'events', 'snapshots',
    'cash', 'bonds', 'home', 'dividendos', 'movements', 'iol', 'wallbit', 'futures', 'insights', 'reports', 'wrapped',
    'behavioral', 'diagnostics', 'cobros', 'pf', 'conversions', 'primeros-pasos', 'tus-senales', 'tecnico',
    // El termómetro (pieza 7): el número es del mercado, pero `tu_plata` es tu cartera por sector.
    'termometro'],
  // Precios, noticias, datos de empresas: lo mismo para todos.
  mercado: ['prices', 'dolar', 'fundamentals', 'market-brief', 'news', 'benchmarks', 'assets', 'tickers', 'fci',
    'fx-rates', 'cedears', 'bond-indices', 'liquidez', 'sections'],
  // Tu cuenta, tus preferencias, la IA, el panel del dueño de Rendi: no son saldos.
  cuenta: ['admin', 'me', 'auth', 'config', 'billing', 'plan', 'push', 'preferencias', 'feedback', 'alerts', 'watchlist',
    'brokers', 'tesis', 'ai'],
  // Una ruta que no existe en el servidor: la usa una prueba del modo demo.
  prueba: ['algo-que-el-demo-no-conoce'],
}
const PLATA = new Set(RUTAS.plata)
const CLASIFICADAS = new Set(Object.values(RUTAS).flat())

// Archivos que traen tu plata y no miran el ojito, con el porqué.
export const SIN_OJITO = {
  // Formularios: muestran lo que la persona está cargando.
  'components/AddPositionFlow.jsx': 'formulario: lo que estás cargando',
  'components/onboarding/PositionStep.jsx': 'formulario del primer activo',
  'components/PfFormModal.jsx': 'formulario de plazo fijo',
  'components/BondCashflowModal.jsx': 'formulario para anotar un cobro',
  'components/alerts/AlertaForm.jsx': 'formulario de alerta: precios',
  'components/import/ImportWizard.jsx': 'importador: muestra el archivo que estás subiendo',
  'components/import/TenenciaUpload.jsx': 'importador',
  'pages/Imports.jsx': 'importador',
  'pages/AdvisorImports.jsx': 'importador del asesor',
  'utils/tandaImport.js': 'envía tandas del importador; no dibuja',
  // Lo que muestran, la Cartera también lo deja a la vista (cantidad, precio, %).
  'components/SplitRatioBanner.jsx': 'cantidades y precio de compra',
  'components/fundamentals/AnalyzeView.jsx': 'cantidad, costo por unidad y %',
  'components/fundamentals/DetailPortfolioBlocks.jsx': 'cantidad, costo por unidad, %; de los plazos fijos usa la tasa',
  'components/tesis/TesisPosiciones.jsx': 'tus tesis, sin montos',
  'components/home/PersonalLayer.jsx': 'sólo % (como la Cartera)',
  'pages/MobileSearch.jsx': 'buscador',
  'pages/GraficoTecnico.jsx': 'buscador de la pestaña Gráfico: sólo los tickers de tu cartera, sin montos (los del gráfico los tapa LecturaTecnica)',
  // Piden una ruta «de plata» pero sólo la parte de mercado.
  'components/home/Heatmap.jsx': 'sólo /home/heatmap: el mercado',
  'components/home/MoversRail.jsx': 'sólo /home/movers: el mercado',
  'components/home/EventsPreview.jsx': 'sólo /events/popular: el mercado',
  'hooks/useMarketIndices.js': 'sólo índices del mercado',
  'hooks/useDiario.js': 'sólo /tecnico/en-fechas: tendencias de precios',
  'components/fundamentals/PrecioComparado.jsx': 'Comparar → Precio (pieza 16): precios del mercado en base 100; de tu cartera sólo usa qué activos tenés y la fecha de tu primera compra, sin montos',
  'utils/instalarApp.js': 'sólo marca un paso de «primeros pasos»',
  'components/mobile/InsightDelDiaHero.jsx': 'textos de comportamiento, sin montos',
  'components/advisor/BriefPrefs.jsx': 'preferencias del resumen del asesor',
  'components/advisor/ClientMoveAlert.jsx': 'aviso de movimiento, sin montos',
  'contexts/AlertsContext.jsx': 'cuenta avisos sin leer',
  'pages/AdvisorNovedades.jsx': 'noticias de los activos de los clientes',
  // Traen el dato; lo muestra otro, que es el que tiene que mirar el ojito.
  'hooks/useCuponesPorCobrar.js': 'lo muestra DividendosPorCobrar (mira el ojito)',
  'hooks/useDividendosPorCobrar.js': 'lo muestra DividendosPorCobrar (mira el ojito)',
  'hooks/useMonthlyData.js': 'lo muestra MonthlySummary (mira el ojito)',
  'hooks/usePfRollup.js': 'lo suma la Cartera, que mira el ojito',
  'hooks/useReportYears.js': 'años con informe, sin montos',
  'hooks/useReportsTimeline.js': 'lo muestran los informes',
  'hooks/useFichaDelActivo.js': 'trae el dato; quien lo usa entra al censo por su cuenta (USA_LA_FICHA)',
  // DEUDA: muestran montos con el ojito prendido. Ya era así en main (29/10);
  // fuera de la ronda del análisis técnico, para una ronda propia. (El resumen
  // del mes, Metas, la bienvenida, Métricas, Comportamiento y Wrapped salieron
  // de esta lista al juntar lo publicado el 30/10: 9de79cf8 los tapa.)
  'pages/AdvisorClients.jsx': 'DEUDA: lista de clientes del asesor',
  'pages/AdvisorCobros.jsx': 'DEUDA: cobros de los clientes',
  'components/advisor/AdvisorAlerts.jsx': 'DEUDA: alertas del asesor',
  'components/advisor/AssetClientsModal.jsx': 'DEUDA: qué clientes tienen un activo',
  'components/advisor/GroupsBar.jsx': 'DEUDA: grupos de clientes',
  'pages/IolLab.jsx': 'laboratorio interno de la conexión con IOL',
  'pages/Admin.jsx': 'panel del dueño de Rendi: números del negocio, no la cartera de quien mira',
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
const RUTA = /api\.(?:get|post|put|patch|delete)\(\s*[`'"]\/([a-zA-Z0-9_-]+)/g
const MIRA_EL_OJITO = /usePrivacy|PrivacyMask|useHistoricalMoney|useMoneyFormat|\bOCULTO\b|\boculto\b/
const TODOS = archivos(SRC).map((r) => {
  const src = sinComentarios(fs.readFileSync(r, 'utf8'))
  return { ruta: rel(r), src, rutas: [...new Set([...src.matchAll(RUTA)].map((m) => m[1]))] }
})
// Traer tu plata también es usar el gancho de la ficha (hooks/useFichaDelActivo,
// que la pide): así la ficha, la pestaña «Gráfico» y cualquier pantalla nueva
// que lo use entran al censo, no sólo el gancho.
const USA_LA_FICHA = /\buseFichaDelActivo\(/
const conPlata = TODOS.filter((a) => a.rutas.some((r) => PLATA.has(r)) || USA_LA_FICHA.test(a.src))

describe('«Ocultar saldos»: censo de lo que trae tu plata', () => {
  it('cada ruta que pide la pantalla está clasificada (una nueva obliga a decidir)', () => {
    const sinClasificar = [...new Set(TODOS.flatMap((a) => a.rutas))].filter((r) => !CLASIFICADAS.has(r))
    expect(sinClasificar, 'agregala a RUTAS: ¿trae plata de la persona, del mercado o de su cuenta?').toEqual([])
  })

  it('el censo encuentra las pantallas conocidas (contra el falso verde)', () => {
    const rutas = conPlata.map((a) => a.ruta)
    for (const r of ['pages/Positions.jsx', 'pages/Operations.jsx', 'pages/AssetDetail.jsx', 'hooks/useFichaDelActivo.js', 'pages/Dashboard.jsx',
      'components/FuturosGroup.jsx', 'components/novedades/CalendarioEventos.jsx', 'components/PlazosFijosGroup.jsx']) {
      expect(rutas, r).toContain(r)
    }
  })

  it('cada archivo que trae tu plata mira el ojito o dice por qué no', () => {
    const sinDecidir = conPlata.filter((a) => !MIRA_EL_OJITO.test(a.src) && !SIN_OJITO[a.ruta]).map((a) => a.ruta)
    expect(sinDecidir, 'usá usePrivacy (o un formateador que tape solo) o anotalo en SIN_OJITO con el porqué').toEqual([])
  })

  it('la lista se achica: lo que ya mira el ojito o ya no trae plata sale de la lista', () => {
    const sobran = Object.keys(SIN_OJITO).filter((r) => {
      const a = TODOS.find((x) => x.ruta === r)
      return !a || !a.rutas.some((x) => PLATA.has(x)) || MIRA_EL_OJITO.test(a.src)
    })
    expect(sobran).toEqual([])
  })
})
