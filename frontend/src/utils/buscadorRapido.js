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
// Y siempre al final, con algo escrito: preguntárselo a Rendi AI — o, si tu
// plan no tiene chat libre, ir a ver las preguntas que sí le podés hacer.

import { CEDEAR_EN_EEUU, ADR_DE_ACCION_AR, ETFS } from './tickers'

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
// algo escrito, lo que coincide — y al final, preguntárselo a Rendi AI.
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
  // Un ticker que tenés no se repite como "empresa".
  const tuyos = new Set(encontrados.filter(o => o.clase === 'activo').map(o => o.simbolo))
  const sinRepetir = encontrados.filter(o => o.clase !== 'empresa' || !tuyos.has(o.simbolo))
  return [...sinRepetir.slice(0, maximo - 1), opcionRendiAI(texto, chatLibre)]
}

// Sin chat libre (Plus) mandar el texto rebotaría: se ofrece ir a Rendi AI a
// elegir entre las preguntas sugeridas (`pregunta: null`).
export function opcionRendiAI(texto, chatLibre = true) {
  if (!chatLibre) {
    return { clase: 'ia', id: 'ia', titulo: 'Ver las preguntas que le podés hacer a Rendi AI', detalle: 'Rendi AI', pregunta: null }
  }
  return { clase: 'ia', id: 'ia', titulo: `Preguntarle a Rendi AI: «${texto}»`, detalle: 'Rendi AI', pregunta: texto }
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
// Hay CEDEARs de ETFs (SPY, QQQ…): tampoco tienen ficha de empresa.
const ES_ETF = new Set(ETFS.map(e => e.s))
export function destinoDeTicker(simbolo, { tuyo = false, tipo = null } = {}) {
  const s = (simbolo || '').toUpperCase()
  if (!s) return null
  if (tuyo) return `/activo/${encodeURIComponent(s)}`
  if (SIN_FICHA_DE_EMPRESA.has(tipo)) return null
  const local = s.replace(/\.BA$/, '')
  if (tipo === 'cedear' && ES_ETF.has(local)) return null
  const empresa = tipo === 'cedear' ? (CEDEAR_EN_EEUU[local] || local)
    : tipo === 'stock_ar' ? ADR_DE_ACCION_AR[local]
    : s
  return empresa ? `/fundamentals?ticker=${encodeURIComponent(empresa)}` : null
}

// Tus activos, uno por ticker (los lotes y los brokers se juntan), sin el
// efectivo. `nombreDe` pone "NVIDIA" al lado de "NVDA" cuando se conoce.
export function opcionesDeActivos(posiciones, nombreDe = () => null) {
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
      detalle: 'Tu posición',
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
