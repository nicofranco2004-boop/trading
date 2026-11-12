// Dibujos a mano sobre el gráfico técnico, como en TradingView: líneas de
// tendencia (de un punto a otro), líneas horizontales (un precio), un Fibonacci
// propio (el tramo que uno elige) y un conteo propio de ondas de Elliott. Pedido
// de Nico, 24/10: «que vos con eso marcás tendencias», «que se guarden por
// activo»; 28/10: Fibonacci y Elliott automáticos, pero «poder calcularlo como
// ellos estiman».
// ════════════════════════════════════════════════════════════════════════════
// Se guardan en tu CUENTA, por activo y por moneda (en pesos y en dólares los
// precios son otros), para verlos en todos tus dispositivos (Nico, 24/10):
// GET/PUT /api/tecnico/{activo}/dibujos (tabla `dibujos_grafico`). Además queda
// una copia en el navegador: aparecen al instante, antes de que conteste el
// servidor, y no se pierden si el guardado falla.
//
// 🔴 LA COPIA ES DE QUIEN LA HIZO: `rendi_dibujos:<persona>|<cuenta>:AAPL:usd`
// (`useDuenoDeLaCopia`). Antes era del ACTIVO (`rendi_dibujos:AAPL:usd`) y la
// usaba cualquiera: si a Ana no se le pudo guardar un dibujo y después Bruno
// abría AAPL en la misma compu, se le mostraba y se SUBÍA a la cuenta de Bruno;
// y el asesor que dibujaba en un cliente se lo llevaba al siguiente (auditoría
// de la pestaña Gráfico, 30/10). Sin nadie logueado no hay copia, y una copia
// sin dueño (la clave vieja) no se lee: no se sube a nadie.
//
// Un punto se guarda por DÍA y precio, no por lugar en la pantalla, así queda
// en su lugar con el zoom, con las velas semanales y cuando llegan días nuevos:
// { d: 'AAAA-MM-DD', mas: n, precio }. `mas` son los días de mercado después de
// `d`: un punto dibujado en el espacio vacío de la derecha (hacia adelante) es
// «n días de mercado después del último día que había».
// En velas de 1 o 4 horas, además, el momento (`t`): ver utils/velasPorHora.js.
//
// La línea de tendencia y el canal recuerdan en qué escala se dibujaron
// (`escala: 'log'`, Nico 12/11; sin ella, la de siempre): son rectos en SU
// escala, también para el aviso (utils/escalaPrecio.js). El `ancho` de un canal
// logarítmico es el logaritmo de cuánto multiplica su paralela.

import { indiceDeFecha } from './tecnico'
import { ANCHO_LOG_MAXIMO, aEje, esLog, precioEnLaRecta, precioMasAncho } from './escalaPrecio'
import { api } from './api'
import { useDuenoDeLaPestana } from './duenoDeLaPestana'
import { leer, guardar, leerDe, guardarDe, borrarDe } from './almacen'
import { CATALOGO } from './catalogoDelAlmacen'
import { ENVIOS, enviarDe } from './enviosConDueno'

/** De quién es lo que se dibuja ahora en esta pestaña (utils/duenoDeLaPestana:
 *  la persona logueada y la cuenta abierta). null = nadie: no se guarda copia.
 *  El gráfico SIGUE a la pestaña: si cambia la cuenta, arranca de cero con los
 *  de la nueva. Pero lo que lee, guarda y sube lo hace con el `dueno` de lo que
 *  muestra (el del dibujo en pantalla), nunca con el de la pestaña de ahora:
 *  entre que otra pestaña cambia la cuenta y el gráfico se redibuja, los dos no
 *  son el mismo (re-test a ciegas 3, 30/10). */
export const useDuenoDeLaCopia = useDuenoDeLaPestana

// La copia va por la única puerta (utils/almacen), a nombre de su dueño:
// `rendi_dibujos:<dueño>:AAPL:usd`. La puerta no la guarda si el dueño ya no es
// el de la pestaña.
const resto = (asset, moneda) => `:${String(asset || '').toUpperCase()}:${moneda === 'ars' ? 'ars' : 'usd'}`
export const DIBUJOS_MAXIMOS = 60

const numero = (x) => typeof x === 'number' && Number.isFinite(x)
// `f` (opcional, sólo el pincel): la fracción del lugar, para que un trazo a
// mano no quede en escalones de a un día cuando el gráfico está muy acercado.
// `t` (opcional): el momento exacto, en segundos UTC, de un punto dibujado en
// velas de 1 o 4 horas (utils/velasPorHora.js); `d` y `mas` siguen siendo su día.
const punto = (p) => !!p && typeof p.d === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(p.d)
  && Number.isInteger(p.mas) && p.mas >= 0 && numero(p.precio) && p.precio > 0
  && (p.f == null || (numero(p.f) && p.f >= 0 && p.f < 1))
  && (p.t == null || (Number.isInteger(p.t) && p.t >= 0 && p.t <= 4102444800))
// El pincel (Nico, 29/10): un trazo a mano alzada, hasta tantos puntos (se
// guardan en tu cuenta con los demás dibujos: sin tope, un garabato largo
// pesaría como cien líneas).
export const PINCEL_MAXIMO = 200

// Las notas de texto (Nico, 30/10: «compré acá por el balance»): un texto tuyo
// en un día y un precio (`a`), con su banderita. Cortas, como un tuit: hasta
// 280 letras (el servidor también lo hace cumplir, main._NOTA_MAXIMA); para la
// explicación larga está tu tesis (1000). Se cuentan igual que el servidor
// (puntos de código): un emoji simple es una; uno compuesto (una bandera, una
// familia, un pulgar con color de piel) cuenta sus partes. `length` contaría
// dos por cada emoji simple.
export const NOTA_MAXIMA = 280
export const largoDeNota = (t) => Array.from(String(t || '')).length
/** Lo que se tipea, cortado al máximo sin partir un emoji al medio (tampoco
 *  uno compuesto: se corta antes de la bandera o la familia entera). */
export function recortarNota(t) {
  const s = String(t || '')
  if (largoDeNota(s) <= NOTA_MAXIMA) return s
  let out = '', n = 0
  const partes = typeof Intl !== 'undefined' && Intl.Segmenter
    ? Array.from(new Intl.Segmenter('es', { granularity: 'grapheme' }).segment(s), x => x.segment) : Array.from(s)
  for (const p of partes) {
    const largo = largoDeNota(p)
    if (n + largo > NOTA_MAXIMA) break
    out += p; n += largo
  }
  return out
}
/**
 * El texto de una nota como lo guarda el servidor (main._texto_de_nota): sin
 * caracteres de control (salvo el salto de renglón; el tab pasa a espacio;
 * también los «C1», U+0080 a U+009F, y la marca BOM), a lo sumo dos renglones
 * vacíos seguidos y sin espacios en las puntas. '' sin texto o si lo que queda
 * no se ve (sólo marcas invisibles, como el espacio de ancho cero). Tiene que
 * ser la MISMA regla: una nota que la pantalla acepta y el servidor no, traba
 * el guardado de todos tus dibujos de ese activo (la lista va entera).
 */
export function limpiarNota(t) {
  const s = String(t ?? '').replace(/\r\n?/g, '\n').replace(/\t/g, ' ')
  const sinControl = Array.from(s).filter(c => {
    const n = c.codePointAt(0)
    return c === '\n' || (n >= 32 && !(n >= 0x7F && n <= 0x9F) && n !== 0xFEFF && !(n >= 0xD800 && n <= 0xDFFF))
  }).join('')
  const limpio = sinControl.replace(/\n{3,}/g, '\n\n').trim()
  return /[^\s\p{Cf}]/u.test(limpio) ? limpio : ''
}

// El color de cada dibujo (Nico, 29/10): se elige con el dibujo tocado y queda
// guardado en el dibujo (en tu cuenta). Sin color, el de siempre (celeste). Son
// colores del tema (se ven bien en claro y en oscuro) y ninguno es el de una
// capa calculada (Fibonacci magenta, Elliott índigo, Bollinger oliva). El
// último elegido es también el de los dibujos nuevos (en este navegador).
export const COLORES_DIBUJO = [
  { id: 'cian', nombre: 'Celeste', token: 'data-cyan' },
  { id: 'ambar', nombre: 'Ámbar', token: 'data-amber' },
  { id: 'rosa', nombre: 'Rosa', token: 'cat-pink' },
  { id: 'verde', nombre: 'Verde', token: 'rendi-pos' },
  { id: 'rojo', nombre: 'Rojo', token: 'rendi-neg' },
  { id: 'violeta', nombre: 'Violeta', token: 'data-violet' },
  { id: 'tinta', nombre: 'Blanco o negro (según el tema)', token: 'ink-0' },
]
export function colorDeLosNuevos() {
  try {
    const c = leer(CATALOGO.colorDibujo)
    return COLORES_DIBUJO.some(x => x.id === c) ? c : 'cian'
  } catch { return 'cian' }
}
export function recordarColor(id) {
  try { guardar(CATALOGO.colorDibujo, id) } catch { /* sin almacenamiento: dura la visita */ }
}
// Un conteo de Elliott a mano, en dos formas por separado (Nico, 28/10), como
// TradingView: el IMPULSO (0, 1, 2, 3, 4, 5) y la CORRECCIÓN (el arranque y
// A, B, C). Se puede terminar antes (un impulso que va por la 3). Los conteos
// guardados antes de separarlos no traen `forma`: son 0-1-2-3-4-5-A-B-C.
export const ETIQUETAS_ELLIOTT = ['0', '1', '2', '3', '4', '5', 'A', 'B', 'C']
export const ETIQUETAS_IMPULSO = ['0', '1', '2', '3', '4', '5']
export const ETIQUETAS_CORRECCION = ['', 'A', 'B', 'C']   // el arranque, sin nombre
export const etiquetasDe = (forma) => (forma === 'impulso' ? ETIQUETAS_IMPULSO
  : forma === 'correccion' ? ETIQUETAS_CORRECCION : ETIQUETAS_ELLIOTT)

// La posición (Nico, 03/11), como la «posición larga» y «corta» de TradingView:
// dónde entraste (`a`: el día y el precio de entrada), hasta dónde la mirás
// (`b`: sólo su día; su precio es el de entrada), tu objetivo (take profit) y
// tu stop (stop loss). `lado`: 'compra' (ganás si sube: el objetivo arriba de
// la entrada y el stop abajo) o 'venta' (al revés).
export const LADOS_POSICION = ['compra', 'venta']
/** ¿El objetivo y el stop están del lado que corresponde a la entrada? */
export function posicionEnOrden(x) {
  if (!LADOS_POSICION.includes(x?.lado) || !numero(x.objetivo) || !numero(x.stop) || !(x.objetivo > 0) || !(x.stop > 0)) return false
  const e = x.a?.precio
  return x.lado === 'compra' ? x.objetivo > e && x.stop < e : x.objetivo < e && x.stop > e
}
/** Una posición nueva en la entrada `a` hasta `b`, con el objetivo a dos
 *  veces la distancia del stop (`riesgo`, en precio): ratio 2, como sale en
 *  TradingView. El stop nunca llega a 0. */
export function posicionNueva(lado, a, b, riesgo) {
  const r = Math.min(Math.abs(riesgo) || a.precio * 0.03, a.precio * 0.45)
  const s = lado === 'venta' ? -1 : 1
  return { tipo: 'posicion', lado, a, b: { ...b, precio: a.precio },
    objetivo: precioRedondo(a.precio + s * 2 * r), stop: precioRedondo(a.precio - s * r) }
}
/**
 * Las cuentas de una posición: cuánto se gana en el objetivo y se pierde en
 * el stop (en % de la entrada) y cuánto se gana por cada peso arriesgado
 * (`ratio`, el «riesgo/beneficio» de TradingView: 2 = el objetivo está al
 * doble de distancia que el stop).
 */
export function cuentasDePosicion(x) {
  const e = x.a.precio, s = x.lado === 'venta' ? -1 : 1
  const gana = (s * (x.objetivo - e) / e) * 100
  const pierde = (s * (e - x.stop) / e) * 100
  return { gana, pierde, ratio: pierde > 0 ? gana / pierde : null }
}
/**
 * Qué pasó con la posición con las velas que hay (`velas`: [{ h, l, c }], la
 * serie entera; `desde` y `hasta`: los índices de la vela de entrada y de la
 * última que mira). Se recorre vela por vela desde la de DESPUÉS de la entrada
 * (en la de la entrada no se sabe si el máximo o el mínimo fue antes o después
 * de entrar) hasta `hasta` o la última que hay:
 *   · { estado: 'objetivo', i } — llegó a tu objetivo en la vela `i`;
 *   · { estado: 'stop', i } — tocó tu stop. Si una misma vela tocó los dos, no
 *     se sabe cuál fue primero: se cuenta el stop, lo que te habría pasado en
 *     el peor caso (TradingView hace lo mismo);
 *   · { estado: 'abierta', i, precio, pct, termino } — no tocó ninguno: con el
 *     último cierre que mira, cuánto vas ganando (o perdiendo) en %;
 *   · { estado: 'adelante' } — la entrada es hacia adelante (todavía no pasó).
 */
export function resultadoDePosicion(x, velas, desde, hasta) {
  if (desde == null || desde > velas.length - 1) return { estado: 'adelante' }
  const fin = Math.min(hasta ?? velas.length - 1, velas.length - 1)
  const compra = x.lado !== 'venta'
  for (let i = Math.max(0, desde + 1); i <= fin; i++) {
    const v = velas[i]
    const alto = v.h ?? v.c, bajo = v.l ?? v.c
    const toco = compra ? bajo <= x.stop : alto >= x.stop
    if (toco) return { estado: 'stop', i }
    if (compra ? alto >= x.objetivo : bajo <= x.objetivo) return { estado: 'objetivo', i }
  }
  // `termino`: la caja termina antes de la última vela (el resultado es el del
  // cierre de su borde derecho, no el de hoy).
  const c = velas[Math.max(desde, fin)]?.c
  const termino = fin < velas.length - 1
  if (!(c > 0)) return { estado: 'abierta', precio: null, pct: null, termino }
  return { estado: 'abierta', i: Math.max(desde, fin), precio: c, pct: ((compra ? c - x.a.precio : x.a.precio - c) / x.a.precio) * 100, termino }
}

/** ¿Es un dibujo que se puede dibujar? (lo guardado puede venir roto o de otra versión)
 *  horizontal: un precio · tendencia y fibonacci (retroceso): dos puntos (a, b) ·
 *  extension: tres (a, b, c) · elliott: de 2 puntos al máximo de su forma ·
 *  nota: un punto (a) y su texto. */
export function dibujoValido(x) {
  if (!x || typeof x.id !== 'string') return false
  if (x.color != null && !COLORES_DIBUJO.some(c => c.id === x.color)) return false
  if (x.tipo === 'horizontal') return numero(x.precio) && x.precio > 0
  if (x.tipo === 'tendencia' || x.tipo === 'fibonacci') return punto(x.a) && punto(x.b)
  // El canal: la línea de abajo (a → b) y cuánto más arriba (o abajo) va su
  // paralela (Nico, 29/10: «el lateral»): en precio, o en uno logarítmico el
  // logaritmo de cuánto multiplica, con su tope (como el servidor).
  if (x.tipo === 'canal') return punto(x.a) && punto(x.b) && numero(x.ancho) && x.ancho !== 0 && (!esLog(x.escala) || Math.abs(x.ancho) <= ANCHO_LOG_MAXIMO)
  if (x.tipo === 'pincel') return Array.isArray(x.puntos) && x.puntos.length >= 2 && x.puntos.length <= PINCEL_MAXIMO && x.puntos.every(punto)
  if (x.tipo === 'extension') return punto(x.a) && punto(x.b) && punto(x.c)
  if (x.tipo === 'nota') return punto(x.a) && typeof x.texto === 'string' && !!limpiarNota(x.texto) && largoDeNota(limpiarNota(x.texto)) <= NOTA_MAXIMA
  if (x.tipo === 'posicion') return punto(x.a) && punto(x.b) && posicionEnOrden(x)
  if (x.tipo === 'elliott') {
    if (x.forma != null && x.forma !== 'impulso' && x.forma !== 'correccion') return false
    return Array.isArray(x.puntos) && x.puntos.length >= 2 && x.puntos.length <= etiquetasDe(x.forma).length && x.puntos.every(punto)
  }
  return false
}

/**
 * La copia de este navegador: { dibujos, pendiente }. `pendiente`: hay un
 * cambio hecho acá que todavía no llegó a tu cuenta (el guardado falló). Sin
 * pendiente, lo de la cuenta manda: si borraste todo desde el celular, la copia
 * de la compu no lo vuelve a subir.
 * La copia de formato viejo (la lista sola, de antes del guardado en la cuenta)
 * NO es pendiente: contarla así revivía dibujos borrados después de un reset
 * (auditoría C, 29/10), y esa versión nunca se publicó, así que no hay usuarios
 * con una copia así que haga falta subir.
 * Sin almacenamiento o con un valor roto: ninguno.
 */
export function copiaLocal(asset, moneda, dueno) {
  if (!dueno) return { dibujos: [], pendiente: false }
  try {
    const g = JSON.parse(leerDe(CATALOGO.dibujos, dueno, resto(asset, moneda)) || 'null')
    const lista = Array.isArray(g) ? g : Array.isArray(g?.dibujos) ? g.dibujos : []
    return { dibujos: lista.filter(dibujoValido).slice(0, DIBUJOS_MAXIMOS), pendiente: !Array.isArray(g) && !!g?.pendiente }
  } catch {
    return { dibujos: [], pendiente: false }
  }
}

/** Los dibujos de la copia de este navegador. */
export const dibujosGuardados = (asset, moneda, dueno) => copiaLocal(asset, moneda, dueno).dibujos

export function guardarDibujos(asset, moneda, lista, pendiente, dueno) {
  if (!dueno) return            // sin nadie logueado no queda copia
  try {
    if (!pendiente && !lista.length) borrarDe(CATALOGO.dibujos, dueno, resto(asset, moneda))
    else guardarDe(CATALOGO.dibujos, dueno, JSON.stringify({ pendiente, dibujos: lista.slice(0, DIBUJOS_MAXIMOS) }), resto(asset, moneda))
  } catch { /* sin almacenamiento: el dibujo vive mientras la página esté abierta */ }
}

/** Ya llegó a la cuenta: si la copia (la de `dueno`, el de cuando se subió)
 *  sigue siendo ESA lista, deja de estar pendiente. */
export function marcarSubidos(asset, moneda, lista, dueno) {
  if (JSON.stringify(copiaLocal(asset, moneda, dueno).dibujos) === JSON.stringify(lista)) guardarDibujos(asset, moneda, lista, false, dueno)
}

/** El precio a guardar: el del toque viene con 15 decimales. 4 decimales y,
 *  abajo de 1, 6 cifras significativas (como backend/estructura.precio_redondo). */
export const precioRedondo = (x) => (Math.abs(x) >= 1 ? Math.round(x * 1e4) / 1e4 : Number(x.toPrecision(6)))

const rutaDesdeTecnico = (asset, moneda) => `${encodeURIComponent(String(asset || '').toUpperCase())}/dibujos?moneda=${moneda === 'ars' ? 'ars' : 'usd'}`
const ruta = (asset, moneda) => `/tecnico/${rutaDesdeTecnico(asset, moneda)}`

/** Los de tu cuenta. null si no se pudieron traer (sin conexión): se sigue con la copia. */
export async function dibujosDelServidor(asset, moneda) {
  try {
    const r = await api.get(ruta(asset, moneda))
    return Array.isArray(r?.dibujos) ? r.dibujos.filter(dibujoValido).slice(0, DIBUJOS_MAXIMOS) : null
  } catch {
    return null
  }
}

// Los guardados van en fila, uno detrás del otro por activo y moneda: la lista
// va entera, y si dos salieran juntos el viejo podría llegar después y pisar
// al nuevo.
const enFila = {}
/**
 * Guarda la lista entera en tu cuenta. Resuelve `true` si quedó guardada; si la
 * cuenta la RECHAZÓ (400/429: un activo que no conocemos, el tope de gráficos),
 * el motivo que mandó el servidor, para mostrarlo tal cual; si no, `false` (sin
 * conexión). Antes un rechazo y una caída decían lo mismo, «no se pudo guardar»,
 * y nadie sabía por qué (re-test E3, 29/10).
 */
export function subirDibujos(asset, moneda, lista, dueno) {
  // `dueno`: de quién es esta lista (el de los dibujos en pantalla). Si cuando
  // le toca salir ya no es el de la pestaña (el asesor cambió de cliente con el
  // guardado en fila, u otra pestaña cambió la cuenta antes de que el gráfico
  // se redibujara), no sale: api.js la mandaría a la cuenta nueva. El freno es
  // el de utils/enviosConDueno, en el instante en que sale.
  if (!dueno) return Promise.resolve(false)
  const k = `${dueno}${resto(asset, moneda)}`
  const sigue = (enFila[k] || Promise.resolve(true))
    // `notas`, `posiciones` y `escalas`: esta pantalla las conoce (si no, el servidor no las toca).
    .then(() => enviarDe(ENVIOS.dibujos, dueno, { dibujos: lista.slice(0, DIBUJOS_MAXIMOS), notas: true, posiciones: true, escalas: true }, rutaDesdeTecnico(asset, moneda)))
    // Si el servidor lo rechaza con un motivo (los topes y el activo válido de
    // E3), se devuelve ese texto para decirlo; si no, false.
    .then(() => true, (e) => {
      if (e?.cuentaCambiada) return { cuentaCambiada: true }
      const motivo = e?.payload?.detail
      return [400, 409, 429].includes(e?.status) && typeof motivo === 'string' && motivo.trim() ? motivo : false
    })
  enFila[k] = sigue
  return sigue
}

let contador = 0
export const idNuevo = () => `d${Date.now().toString(36)}${(contador++).toString(36)}`

/**
 * El punto a guardar para el día `i` (contado sobre los puntos DIARIOS del
 * gráfico; puede pasar del último, hacia adelante) y un precio.
 */
export function puntoDelDia(puntos, i, precio, f = 0) {
  const ultimo = puntos.length - 1
  const fr = f > 0 && f < 1 ? { f: Math.min(0.99, Math.round(f * 100) / 100) } : {}
  if (i <= ultimo) return { d: puntos[Math.max(0, i)].d, mas: 0, precio: precioRedondo(precio), ...(fr.f ? fr : {}) }
  return { d: puntos[ultimo].d, mas: i - ultimo, precio: precioRedondo(precio), ...(fr.f ? fr : {}) }
}

/**
 * Y al revés: en qué día (índice de los puntos diarios) cae un punto guardado.
 * Si su fecha no está (un feriado, o datos que cambiaron) va al último día de
 * antes; si es anterior a todo el gráfico, un índice negativo: los días hábiles
 * entre el punto y el primer día (queda afuera, a la izquierda, a su
 * distancia). Antes iba siempre a -1 y la línea giraba a medida que se
 * borraban los días viejos; el aviso la mira igual (backend
 * tecnico._indice_del_punto) (auditoría 29/10).
 */
export function diaDelPunto(puntos, p) {
  if (!puntos.length) return null
  const i = indiceDeFecha(puntos, p.d)
  if (i != null) return i + p.mas
  return -diasHabilesEntre(p.d, puntos[0].d) + (p.mas || 0)
}

/** Los días de lunes a viernes desde `desde` (incluido) hasta `hasta` (sin incluir), 'AAAA-MM-DD'. */
export function diasHabilesEntre(desde, hasta) {
  const a = Date.parse(`${desde}T00:00:00Z`), b = Date.parse(`${hasta}T00:00:00Z`)
  if (!Number.isFinite(a) || !Number.isFinite(b) || b <= a) return 1
  let n = 0
  for (let t = a; t < b; t += 86400000) { const dia = new Date(t).getUTCDay(); if (dia !== 0 && dia !== 6) n++ }
  return Math.max(1, n)
}

/**
 * Las puntas de un dibujo, con su nombre: ['a', p], ['b', p], ['c', p] o, en
 * un conteo de Elliott, [n, p] por onda. Una horizontal, un trazo o una nota
 * no tienen: se agarran enteros.
 */
export function puntasDe(d) {
  if (d.tipo === 'horizontal' || d.tipo === 'pincel' || d.tipo === 'nota') return []
  if (d.tipo === 'elliott') return d.puntos.map((p, n) => [n, p])
  // La posición, como en TradingView: la entrada (a la izquierda), el borde
  // derecho (cuánto tiempo la mirás) y el objetivo y el stop (arriba y abajo).
  if (d.tipo === 'posicion') {
    return [['a', d.a], ['b', { ...d.b, precio: d.a.precio }],
      ['objetivo', { ...d.a, precio: d.objetivo }], ['stop', { ...d.a, precio: d.stop }]]
  }
  // El canal se ensancha agarrando la paralela de su mitad (como TradingView),
  // en la escala del canal.
  if (d.tipo === 'canal') return [['a', d.a], ['b', d.b], ['ancho', puntaDelAncho(d)]]
  return ['a', 'b', 'c'].filter(c => d[c]).map(c => [c, d[c]])
}

// La punta del ancho de un canal: su paralela, en el medio de a y b (en lugares de la pantalla).
function puntaDelAncho(d) {
  const k = (d.a.k + d.b.k) / 2
  return { k, precio: precioMasAncho(precioEnLaRecta(d.a, d.b, k, d.escala), d.ancho, d.escala) }
}

/**
 * El dibujo arrastrado (Nico, 28/10: «mover y corregir un dibujo ya hecho»):
 * `que` es la punta agarrada (su nombre en `puntasDe`) o 'todo', para moverlo
 * entero; en un canal, 'ancho' lleva su paralela a donde quedó esa punta.
 * `correr(p)` da el punto nuevo de una punta; `correrPrecio(x)`, el precio
 * nuevo de una horizontal (el arrastre en la escala que se está mirando:
 * utils/escalaPrecio.precioCorrido). La MISMA cuenta para lo que se ve
 * mientras se arrastra (puntos en lugares de la pantalla) y para lo que se
 * guarda (puntos por día).
 */
export function dibujoCorrido(d, que, correr, correrPrecio) {
  if (d.tipo === 'horizontal') return { ...d, precio: correrPrecio(d.precio) }
  if (d.tipo === 'canal' && que === 'ancho') {
    // El ancho nuevo, en la escala del canal: de su línea a donde quedó la punta.
    const punta = puntaDelAncho(d)
    const ancho = aEje(correrPrecio(punta.precio), d.escala) - aEje(precioEnLaRecta(d.a, d.b, punta.k, d.escala), d.escala)
    const vale = Number.isFinite(ancho) && ancho !== 0 && (!esLog(d.escala) || Math.abs(ancho) <= ANCHO_LOG_MAXIMO)
    return vale ? { ...d, ancho } : d
  }
  if (d.tipo === 'posicion') return posicionCorrida(d, que, correr, correrPrecio)
  const mueve = (nombre) => que === 'todo' || que === nombre
  if (d.tipo === 'elliott' || d.tipo === 'pincel') return { ...d, puntos: d.puntos.map((p, n) => (mueve(n) ? correr(p) : p)) }
  const out = { ...d }
  for (const c of ['a', 'b', 'c']) if (d[c] && mueve(c)) out[c] = correr(d[c])
  return out
}

// La posición arrastrada: entera, su entrada (el día y el precio; el objetivo
// y el stop se quedan en su precio), su borde derecho (sólo el día) o el
// objetivo o el stop (sólo su precio). Si así quedaría al revés (el stop del
// lado del objetivo, o el borde antes de la entrada), no se mueve: queda como
// estaba, como una punta que llegó a su tope.
function posicionCorrida(d, que, correr, correrPrecio) {
  const out = { ...d }
  if (que === 'todo' || que === 'a') out.a = correr(d.a)
  if (que === 'todo' || que === 'b') out.b = correr(d.b)
  if (que === 'todo' || que === 'objetivo') out.objetivo = correrPrecio(d.objetivo)
  if (que === 'todo' || que === 'stop') out.stop = correrPrecio(d.stop)
  out.b = { ...out.b, precio: out.a.precio }
  return posicionEnOrden(out) && antesQue(out.a, out.b) ? out : d
}
// ¿El punto p va antes que q? En lo que se ve, por su lugar (`k`); guardados,
// por día, días hacia adelante y momento (en 1H/4H).
function antesQue(p, q) {
  if (numero(p.k) && numero(q.k)) return p.k < q.k
  if (p.d !== q.d) return p.d < q.d
  if (p.mas !== q.mas) return p.mas < q.mas
  return (p.t ?? 0) < (q.t ?? 0)
}

/** La distancia de (x, y) al segmento de (ax, ay) a (bx, by), todo en píxeles. */
export function distanciaASegmento(x, y, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay
  const largo = dx * dx + dy * dy
  const t = largo ? Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / largo)) : 0
  return Math.hypot(x - (ax + t * dx), y - (ay + t * dy))
}

/**
 * Qué dibujo se tocó: el más cercano a (x, y) a menos de `radio` píxeles, o
 * null. `trazos`: [{ id, ax, ay, bx, by }] ya en píxeles (una horizontal va de
 * borde a borde).
 */
export function dibujoTocado(trazos, x, y, radio = 8) {
  let mejor = null, dist = radio
  for (const t of trazos) {
    const d = distanciaASegmento(x, y, t.ax, t.ay, t.bx, t.by)
    if (d <= dist) { mejor = t.id; dist = d }
  }
  return mejor
}
