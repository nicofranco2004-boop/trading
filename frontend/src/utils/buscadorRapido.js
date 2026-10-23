// buscadorRapido — qué ofrece el buscador ⌘K y en qué orden. Sin React: lo
// arma BuscadorRapido.jsx con lo que ve el usuario (pantallas de su menú, sus
// activos, el universo de tickers conocido) y acá sólo se decide.
//
// Cuatro clases de opción, en este orden de prioridad cuando empatan:
//   activo   → un activo que TENÉS: su ficha (/activo/X), con tus lotes.
//   pantalla → una pantalla del menú (las mismas que muestra el menú lateral).
//   accion   → hacer algo: cargar una operación, cambiar de moneda o de tema,
//              tapar los montos.
//   empresa  → un ticker que NO tenés: la MISMA ficha (/activo/X), sin lotes,
//              con el gráfico y el análisis técnico; desde ahí, "Calidad de
//              cartera" si la empresa tiene puntaje.
// Y siempre al final, con algo escrito: preguntárselo a Mervall-E AI — o, si tu
// plan no tiene chat libre, ir a ver las preguntas que sí le podés hacer.

import { CEDEAR_EN_EEUU, ADR_DE_ACCION_AR, ETFS, CEDEARS_DE_ETF, cedearEspecieBase, inferType } from './tickers'
import { classifyAsset } from './assetClass'
import { quienEs } from './quienEs'

const PRIORIDAD = { activo: 0, pantalla: 1, accion: 2, empresa: 3 }

// ¿Es el atajo del buscador? ⌘K en Mac, Ctrl+K en el resto. En Mac NO Ctrl+K:
// adentro de un campo de texto es "borrar hasta el final de la línea" y el
// buscador se lo comía.
export function esAtajoBuscador(e, mac) {
  if (!e || e.altKey || (e.key !== 'k' && e.key !== 'K')) return false
  return mac ? (e.metaKey && !e.ctrlKey) : (e.ctrlKey && !e.metaKey)
}
export function esMac(nav = typeof navigator !== 'undefined' ? navigator : null) {
  return !!nav && /Mac|iPhone|iPad/i.test(nav.platform || nav.userAgent || '')
}

// Minúsculas y sin tildes: "dolar" encuentra "dólar", "metricas" "Métricas".
export function normalizar(t) {
  return (t ?? '').toString().normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim()
}

// 3 = el título empieza con lo escrito · 2 = alguna palabra (o clave) empieza
// así · 1 = aparece en el medio · 0 = no tiene que ver.
export function puntaje(opcion, consulta) {
  const q = normalizar(consulta)
  if (!q) return 0
  const titulo = normalizar(opcion.titulo)
  if (titulo.startsWith(q)) return 3
  const palabras = [titulo, ...(opcion.claves || []).map(normalizar)].join(' ').split(/[\s·/,()-]+/)
  if (palabras.some(p => p && p.startsWith(q))) return 2
  if (titulo.includes(q) || (opcion.claves || []).some(c => normalizar(c).includes(q))) return 1
  return 0
}

export const MAXIMO_RESULTADOS = 8

// Bajo qué llave se guardan tus activos entre una apertura y otra: por PERSONA
// (cerrar sesión no recarga la página: en una compu compartida el siguiente no
// puede ver los del anterior) y por cuenta (un asesor adentro de un cliente ve
// los del cliente). Sin nadie logueado no se guarda nada — y tampoco se piden.
// La persona es la de la regla única (utils/quienEs). Se armaba con `user.id`,
// que el usuario de la app no trae: en toda cuenta de verdad la llave quedaba
// vacía y el buscador NUNCA pedía tus activos ("nvda" + Enter iba a la
// empresa). Andaba sólo en el demo, cuyo usuario tenía `id: 0` escrito a mano.
export function claveDeActivos(user, clientCtx) {
  const quien = quienEs(user)
  if (quien == null) return null
  return `${quien}:${clientCtx?.id ? `cliente:${clientCtx.id}` : 'propia'}`
}

// "Cargar una operación" abre el formulario en Movimientos (?nueva=1). Si ya
// estás ahí, conserva lo que tenías elegido (la pestaña, los filtros).
export function urlNuevaOperacion(pathname, search = '') {
  const sp = new URLSearchParams(pathname === '/operaciones' ? search : '')
  sp.set('nueva', '1')
  return `/operaciones?${sp}`
}

// Lo que se ve: sin nada escrito, los accesos de siempre (`deEntrada`); con
// algo escrito, lo que coincide — y al final, preguntárselo a Mervall-E AI.
// Las empresas que no tenés recién con 2 letras: con una sola, "A" traería
// media bolsa de Nueva York arriba de tus cosas.
export function resultadosDelBuscador(opciones, consulta, { maximo = MAXIMO_RESULTADOS, chatLibre = true } = {}) {
  const texto = (consulta ?? '').trim()
  if (!texto) return opciones.filter(o => o.deEntrada).slice(0, maximo)
  const q = normalizar(texto)
  const encontrados = opciones
    .filter(o => o.clase !== 'empresa' || q.length >= 2)
    .map((o, i) => ({ o, i, p: puntaje(o, q) }))
    .filter(x => x.p > 0)
    .sort((a, b) => b.p - a.p || PRIORIDAD[a.o.clase] - PRIORIDAD[b.o.clase] || a.i - b.i)
    .map(x => x.o)
  // Un ticker que tenés no se repite como "empresa" — tampoco su CEDEAR: si
  // tenés BABA (guardado sin .BA) no aparece además "BABA.BA · Ver la empresa".
  const base = (s) => (s || '').replace(/\.BA$/, '')
  const tuyos = new Set(encontrados.filter(o => o.clase === 'activo').map(o => base(o.simbolo)))
  const sinRepetir = encontrados.filter(o => o.clase !== 'empresa' || !tuyos.has(base(o.simbolo)))
  return [...sinRepetir.slice(0, maximo - 1), opcionRendiAI(texto, chatLibre)]
}

// Sin chat libre (Plus) mandar el texto rebotaría: se ofrece ir a Mervall-E AI a
// elegir entre las preguntas sugeridas (`pregunta: null`).
export function opcionRendiAI(texto, chatLibre = true) {
  if (!chatLibre) {
    return { clase: 'ia', id: 'ia', titulo: 'Ver las preguntas que le podés hacer a Mervall-E AI', detalle: 'Mervall-E AI', pregunta: null }
  }
  return { clase: 'ia', id: 'ia', titulo: `Preguntarle a Mervall-E: «${texto}»`, detalle: 'Mervall-E AI', pregunta: texto }
}

// La ficha de un activo: UN lugar para todo activo, lo tengas o no. La abren la
// Cartera, los buscadores, el mapa de calor, los movers, la watchlist y los
// eventos. Con lotes muestra lo tuyo; sin lotes, el precio y el análisis técnico.
export const urlDeActivo = (simbolo) => `/activo/${encodeURIComponent((simbolo || '').toUpperCase())}`

// A dónde lleva un ticker en CUALQUIER buscador de la app (este ⌘K y la lupa
// del celular, pages/MobileSearch). Una sola regla: la lupa tenía la suya y
// llevaba a /posiciones#X, que nadie lee.
//   • A la ficha del activo, lo tengas o no (con tus lotes si lo tenés).
//     Antes, lo que no tenías iba a "Calidad de cartera" y una cripto o un ETF
//     a ningún lado: no había forma de ver su gráfico sin agregarlo a la
//     watchlist. "Calidad de cartera" sigue a un toque, desde la ficha.
//   • Un bono o un fondo que no tenés: a ningún lado (null). No tienen gráfico
//     técnico y la ficha quedaría casi vacía.
const SIN_FICHA_SI_NO_LO_TENES = new Set(['bond', 'fci'])
export function destinoDeTicker(simbolo, { tuyo = false, tipo = null } = {}) {
  const s = (simbolo || '').toUpperCase()
  if (!s) return null
  if (!tuyo && SIN_FICHA_SI_NO_LO_TENES.has(tipo)) return null
  return urlDeActivo(s)
}

export const urlDeEmpresa = (ticker) => `/fundamentals?ticker=${encodeURIComponent(ticker)}`

// La empresa de un ticker en "Calidad de cartera", que sólo arma el puntaje de
// acciones que cotizan en dólares en EE.UU.:
//   • Un CEDEAR (AAPL.BA) se abre por esa acción (AAPL; DISN → DIS:
//     CEDEAR_EN_EEUU): en pesos el servidor no lo arma y él mismo sugiere ese
//     ticker. Hay CEDEARs de ETFs (SPY, QQQ, URA…): ésos no tienen empresa.
//   • Una acción argentina, por su ADR (YPFD → YPF: ADR_DE_ACCION_AR); si no
//     tiene, no hay empresa (TEN, AGRO abrían OTRA empresa con ese ticker).
//   • Bonos, cripto, ETFs y fondos: no —el servidor contesta "no aplica"—.
// null = no hay empresa. Lo usan la ficha de un activo que no tenés, la de uno
// tuyo (empresaDeTenencias) y la lista con puntaje (CarteraList).
const SIN_FICHA_DE_EMPRESA = new Set(['bond', 'crypto', 'etf', 'fci'])
const ES_ETF = new Set([...ETFS.map(e => e.s), ...CEDEARS_DE_ETF])
export function tickerDeEmpresa(simbolo, tipo) {
  const s = (simbolo || '').toUpperCase()
  if (!s || SIN_FICHA_DE_EMPRESA.has(tipo)) return null
  if (tipo === 'cedear') {
    // SI es la especie en pesos del CEDEAR de CSN, cuyo ticker en EE.UU. es SID.
    const local = cedearEspecieBase(s)
    if (ES_ETF.has(local)) return null
    return CEDEAR_EN_EEUU[local] || local
  }
  if (tipo === 'stock_ar') return ADR_DE_ACCION_AR[s.replace(/\.BA$/, '')] || null
  return s
}

// La empresa de un activo TUYO: la ficha del activo y los botones "Tus
// posiciones" de Calidad de cartera. Es la regla del buscador, pero el tipo
// sale de la clase de la torta (assetClass.classifyAsset), que mira en qué
// MERCADO está cada tenencia y no sólo el ticker. La ficha preguntaba sólo por
// el ticker: TECO2 no llevaba a Telecom (TEO), DISN abría "DISN" y no Disney
// (DIS), y AGRO (Agrometal) abría Adecoagro, otra empresa.
//   • TECO2 en Cocos → TEO · YPFD → YPF · GGAL en Schwab → GGAL
//   • DISN o AAPL en Cocos (CEDEAR) → DIS / AAPL · SPY en Cocos (CEDEAR de ETF) → null
//   • AGRO en Cocos (sin ADR) → null · CELU en Schwab (Celularity) → CELU
//   • Bonos, cripto, fondos, ETFs y lo que no se reconoce → null.
// Si tus tenencias de ese ticker dan empresas distintas (CELU en Cocos y CELU
// en Schwab son dos compañías), no se adivina: null.
// Devuelve { ticker, ir } o null.
const TIPO_DE_CLASE = { cedear: 'cedear', accion_ar: 'stock_ar', accion_us: 'stock_us' }
export function empresaDeTenencias(tenencias, brokers = []) {
  const empresas = new Set()
  for (const p of tenencias || []) {
    if (!p || p.is_cash) continue
    const tipo = TIPO_DE_CLASE[classifyAsset(p, brokers)]
    empresas.add(tipo ? tickerDeEmpresa(p.asset, tipo) : null)
  }
  if (empresas.size !== 1) return null
  const [ticker] = empresas
  return ticker ? { ticker, ir: urlDeEmpresa(ticker) } : null
}

// La empresa de un ticker que NO tenés (la ficha sin lotes): no hay tenencias
// que digan en qué mercado está, así que decide el ticker (inferType: GGAL y
// GGAL.BA son la acción argentina; AAPL.BA, el CEDEAR). { ticker, ir } o null.
// Lo TUYO decide por tus tenencias (empresaDeTenencias), nunca por acá.
export function empresaDeTicker(simbolo) {
  const ticker = tickerDeEmpresa(simbolo, inferType(simbolo))
  return ticker ? { ticker, ir: urlDeEmpresa(ticker) } : null
}

// Cómo se mira un activo que NO tenés, con la misma regla del ticker: una
// acción argentina se mira en BYMA (su precio en pesos y, en el gráfico en
// dólares, ese precio ÷ el MEP), no por su ADR de Nueva York.
//   GGAL / GGAL.BA → { accionLocal: true, simboloPrecio: 'GGAL.BA' }
//   NVDA → { accionLocal: false, simboloPrecio: 'NVDA' } · BTC igual.
export function miradaSinTenencia(simbolo) {
  const s = (simbolo || '').toUpperCase()
  const accionLocal = inferType(s) === 'stock_ar'
  return { accionLocal, simboloPrecio: accionLocal && !s.endsWith('.BA') ? `${s}.BA` : s }
}

// Tus activos, uno por ticker (los lotes y los brokers se juntan), sin el
// efectivo. `nombreDe` pone "NVIDIA" al lado de "NVDA" cuando se conoce.
// `cliente`: el asesor adentro de la cuenta de un cliente — no es "tu"
// posición, es la de él (el menú y la lupa dicen lo mismo).
export function opcionesDeActivos(posiciones, nombreDe = () => null, { cliente = null } = {}) {
  const vistos = new Set()
  const out = []
  for (const p of posiciones || []) {
    const s = (p?.asset || '').toUpperCase()
    if (!s || p.is_cash || vistos.has(s)) continue
    vistos.add(s)
    const nombre = nombreDe(s)
    out.push({
      clase: 'activo', id: `activo:${s}`, simbolo: s,
      titulo: nombre ? `${s} · ${nombre}` : s,
      detalle: cliente ? `Posición de ${cliente}` : 'Tu posición',
      claves: nombre ? [nombre] : [],
      ir: destinoDeTicker(s, { tuyo: true }),
    })
  }
  return out
}

// Tickers que no tenés: los abre su ficha (/activo/X), con el gráfico y el
// análisis técnico (destinoDeTicker). Los bonos y fondos no se ofrecen: no
// tienen gráfico técnico. Y al asesor en su nivel, ninguno: no tiene cartera
// propia y su buscador no ofrecía tickers sueltos; adentro de un cliente sí
// (es la cartera de ese cliente).
export function opcionesDeEmpresas(universo, { asesorEnSuNivel = false } = {}) {
  if (asesorEnSuNivel) return []
  const vistos = new Set()
  const destinos = new Set()
  const out = []
  for (const u of universo || []) {
    const s = (u?.symbol || '').toUpperCase()
    if (!s || vistos.has(s)) continue
    vistos.add(s)
    const ir = destinoDeTicker(s, { tipo: u.type })
    if (!ir || destinos.has(ir)) continue
    destinos.add(ir)
    out.push({
      clase: 'empresa', id: `empresa:${s}`, simbolo: s,
      titulo: u.name ? `${s} · ${u.name}` : s,
      detalle: 'Ver el gráfico',
      claves: u.name ? [u.name] : [],
      ir,
    })
  }
  return out
}
