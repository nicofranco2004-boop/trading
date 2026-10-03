// buscadorRapido — qué ofrece el buscador ⌘K y en qué orden. Sin React: lo
// arma BuscadorRapido.jsx con lo que ve el usuario (pantallas de su menú, sus
// activos, el universo de tickers conocido) y acá sólo se decide.
//
// Cuatro clases de opción, en este orden de prioridad cuando empatan:
//   activo   → un activo que TENÉS: su ficha (/activo/X), con tus lotes.
//   pantalla → una pantalla del menú (las mismas que muestra el menú lateral).
//   accion   → hacer algo: cargar una operación, cambiar de moneda o de tema,
//              tapar los montos.
//   empresa  → un ticker que NO tenés: "Calidad de cartera" lo muestra con sus
//              números. La ficha de activo no sirve ahí (es de tus lotes).
// Y siempre al final, con algo escrito: preguntárselo a Mervall-E AI — o, si tu
// plan no tiene chat libre, ir a ver las preguntas que sí le podés hacer.

import { CEDEAR_EN_EEUU, ADR_DE_ACCION_AR, ETFS, CEDEARS_DE_ETF, cedearEspecieBase } from './tickers'
import { classifyAsset } from './assetClass'

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

// Bajo qué llave se guardan tus activos entre una apertura y otra: por USUARIO
// (cerrar sesión no recarga la página: en una compu compartida el siguiente no
// puede ver los del anterior) y por cuenta (un asesor adentro de un cliente ve
// los del cliente). Sin usuario no se guarda nada. OJO con el 0: el usuario del
// modo demo es el id 0, y `!user.id` lo trataba como "sin usuario" (el
// buscador no pedía sus activos — lo atrapó la prueba en el navegador).
export function claveDeActivos(user, clientCtx) {
  if (user?.id == null) return null
  return `${user.id}:${clientCtx?.id ? `cliente:${clientCtx.id}` : 'propia'}`
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
  return { clase: 'ia', id: 'ia', titulo: `Preguntarle a Mervall-E AI: «${texto}»`, detalle: 'Mervall-E AI', pregunta: texto }
}

// A dónde lleva un ticker en CUALQUIER buscador de la app (este ⌘K y la lupa
// del celular, pages/MobileSearch). Una sola regla: la lupa tenía la suya y
// llevaba a /posiciones#X, que nadie lee.
//   • Si lo tenés: a tu posición (la ficha del activo).
//   • Si no: a la empresa en "Calidad de cartera", que sólo arma el puntaje de
//     acciones que cotizan en dólares en EE.UU. Un CEDEAR (AAPL.BA) se abre por
//     esa acción (AAPL; DISN → DIS: CEDEAR_EN_EEUU): en pesos el servidor no lo
//     arma y él mismo sugiere ese ticker. Una acción argentina, por su ADR
//     (YPFD → YPF: ADR_DE_ACCION_AR); si no tiene, no hay ficha. Bonos, cripto,
//     ETFs y fondos tampoco —el servidor contesta "no aplica" por tipo—.
//   • null = no hay a dónde llevar. Antes terminaban en un cartel que decía que
//     ahí no había nada, o en OTRA empresa con el mismo ticker (TEN, AGRO).
const SIN_FICHA_DE_EMPRESA = new Set(['bond', 'crypto', 'etf', 'fci'])
// Hay CEDEARs de ETFs (SPY, QQQ, URA…): tampoco tienen ficha de empresa.
const ES_ETF = new Set([...ETFS.map(e => e.s), ...CEDEARS_DE_ETF])
export function destinoDeTicker(simbolo, { tuyo = false, tipo = null } = {}) {
  const s = (simbolo || '').toUpperCase()
  if (!s) return null
  if (tuyo) return `/activo/${encodeURIComponent(s)}`
  const empresa = tickerDeEmpresa(s, tipo)
  return empresa ? urlDeEmpresa(empresa) : null
}

export const urlDeEmpresa = (ticker) => `/fundamentals?ticker=${encodeURIComponent(ticker)}`

// El ticker con el que "Calidad de cartera" abre la empresa, o null. Lo usa
// también su lista con puntaje (CarteraList) para los CEDEARs.
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

// Tickers que no tenés: los abre "Calidad de cartera" (/fundamentals?ticker=X).
// Los que no tienen ficha de empresa (bonos, cripto…) no se ofrecen como
// "Ver la empresa": llevarían a una pantalla vacía. Y al asesor en su nivel,
// ninguna: no tiene "Calidad de cartera" en su menú (no tiene cartera propia),
// y el buscador no lleva a un lugar que el menú no muestra. Adentro de un
// cliente sí (es la cartera de ese cliente).
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
    // Sin ficha, o la misma empresa que otra fila (AAPL y su CEDEAR AAPL.BA).
    if (!ir || destinos.has(ir)) continue
    destinos.add(ir)
    out.push({
      clase: 'empresa', id: `empresa:${s}`, simbolo: s,
      titulo: u.name ? `${s} · ${u.name}` : s,
      detalle: 'Ver la empresa',
      claves: u.name ? [u.name] : [],
      ir,
    })
  }
  return out
}
