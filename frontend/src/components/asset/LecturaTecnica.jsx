// LecturaTecnica — el gráfico técnico y su lectura en la ficha del activo.
// ════════════════════════════════════════════════════════════════════════════
// Gráfico de precio con las medias de 50 y 200 días, las Bandas de Bollinger
// (prendidas de entrada, Nico 28/10: apagadas no las encontraba; su ojito de la
// leyenda las apaga junto con su tarjeta), tu precio promedio y tus
// compras y ventas; la fuerza del movimiento (RSI) abajo; y tarjetas en
// castellano. El Fibonacci muestra la capa del último tramo de suba o bajada
// (CapaFibonacci.jsx) y las ondas de Elliott un conteo posible (CapaElliott.jsx).
// Cada capa se prende y se apaga desde la barra de herramientas del costado
// (BarraGrafico.jsx): todo arranca prendido y se recuerda lo que cada uno apaga. Se mide en
// DÓLARES por defecto: un CEDEAR en pesos sube con el dólar aunque la empresa
// no se mueva (ver backend/tecnico.py).
//
// Encima del gráfico, los balances («B») y dividendos («D») de la empresa con
// lo que se movió el precio (GET /api/tecnico/{asset}/eventos), el modo «Medir
// entre dos puntos» y el rango «Desde que lo tenés». Debajo de las tarjetas,
// «Cuánto se mueve este papel» (backend/movimiento.py). Todo es lo que YA pasó:
// nada de esto anticipa nada. Las palabras: utils/cuantoSeMueve.js.
//
// Los números vienen de GET /api/tecnico (las velas que se guardan de noche, o
// que el servidor baja en el momento si nadie seguía el activo). Sirve también
// para un activo que no tenés: sin lotes no hay tu precio, tus compras ni
// «Contra lo que pagaste». Si no hay velas (un bono/fondo, o el servidor no las
// pudo traer), se muestra el gráfico de 30 días de siempre (`AssetMiniChart`).
//
// Una sola vista para compu y celular (R6): el gráfico es `width: 100%`, los
// precios del eje van en su propia columna a la derecha (no tapan la línea) y
// las tarjetas se acomodan en la grilla. Colores sólo por variables del tema
// (R8): `rgb(var(--token))` en el SVG, que sigue al modo claro y al oscuro.
// Lo que cambia en un gráfico angosto (el celular) se decide por el ancho del
// GRÁFICO, que él mismo mide, nunca por el de la pantalla: abre con lo reciente
// (diasRecientes) y, si los dividendos se pisarían, muestra sólo los balances
// (dividendosAmontonados).
//
// «Compartir» (CompartirGrafico.jsx) arma una imagen de lo que se ve para
// WhatsApp (utils/imagenGrafico.js), sin nada de tu cartera.
//
// Debajo del RSI, la fuerza de la tendencia en dos franjas: el ADX con su línea
// de 23 y las barras del Squeeze (el combo «DMI/ADX/KEYLEVEL» + «SQZMOM_LB» de
// TradingView), con su tarjeta «Fuerza de la tendencia».
//
// «✦ Analizar con Mervall-E» (ResumenMervalle.jsx): en la ficha, dentro de «La
// lectura de hoy» (el párrafo a pedido, uno por activo y por día, que ven todos,
// y las preguntas para seguir en el chat); en la pestaña «Gráfico», que no tiene
// esa tarjeta, debajo de la leyenda.

import { cloneElement, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Bell, Brush, ChevronDown, LineChart, Maximize2, Minimize2, Redo2, RotateCcw, Ruler, StickyNote, Trash2, Undo2 } from 'lucide-react'
import { usePrivacy } from '../../contexts/PrivacyContext'
import AssetMiniChart from '../home/AssetMiniChart'
import BarraGrafico, { CAPAS_DE_FABRICA, LeyendaIndicadores, capasGuardadas, guardarCapas, olvidarCapas, sonDeFabrica } from './BarraGrafico'
import CapaFibonacci, { COLOR_FIB, ID_FIB_AUTO, TarjetaFibonacci, preciosDeLaCapa, trazosDelFibonacci, ventanaDelTramo, ventanaDesde } from './CapaFibonacci'
import CapaElliott, { COLOR_ELLIOTT, ID_ELL_AUTO, TarjetaElliott, fechaDelConteo, preciosDelConteo, trazosDelConteo } from './CapaElliott'
import CapaDibujos, { anchoDelCanal, colorDe, preciosAlBorde, trazosDeDibujos } from './CapaDibujos'
import CompartirGrafico from './CompartirGrafico'
import LecturaDeHoy from './LecturaDeHoy'
import TarjetasPorTema from './TarjetasPorTema'
import Banderitas, { CartelDeNotas, banderitaEn, banderitasEnVista, esClaveDeGrupo, esClaveDeTesis } from './NotasGrafico'
import { BotonMervalle, PanelMervalle, useResumenMervalle } from './ResumenMervalle'
import { BotonAvisame, BotonAvisameLinea, alertaDeLinea, useAvisosTecnicos, senalDeTarjeta } from '../alerts/AvisameTecnico'
import { api, getClientContext } from '../../utils/api'
import { factorDeFechas, fechaDeLaMira, marcasDeFechas, marcasDePrecio, empezarAMano, correrAMano, estirarAMano, arrastreDentroDelTope } from '../../utils/ejesGrafico'
import { PRIORIDAD, taparRotulos } from '../../utils/rotulos'
import { ANCHO_DEL_GRAFICO, archivoDelGrafico, specDelGrafico } from '../../utils/imagenGrafico'
import {
  DIBUJOS_MAXIMOS, copiaLocal, etiquetasDe, diaDelPunto, dibujoCorrido, dibujoTocado, dibujosDelServidor, dibujosGuardados, guardarDibujos, idNuevo,
  marcarSubidos, PINCEL_MAXIMO, COLORES_DIBUJO, colorDeLosNuevos, recordarColor, precioCorrido, precioRedondo, puntasDe, puntoDelDia, subirDibujos,
  limpiarNota, useDuenoDeLaCopia,
} from '../../utils/dibujos'
import {
  RSI_CASTIGADO, RSI_ESTIRADO, ADX_CLAVE, fmtAdx, tarjetas, tarjetaBandas, lineaPromedio, marcas, variacionDeHoy,
  indiceDeFecha, tendenciasDistintas, velaCompleta, velasSemanales, zoomVentana, zoomEnElTope, moverVentana, RUEDAS_MINIMAS,
  ventanaInicial, margenDerecho, futuroMaximo, sumarVelaDeHoy, textoVelaDeHoy,
} from '../../utils/tecnico'
import { useVelaDeHoy } from '../../hooks/useVelaDeHoy'
import {
  medicion as medirEntre, primeraCompra, puntosDesde, tarjetasMovimiento, textoGrupo, textoMedicion,
} from '../../utils/cuantoSeMueve'
import {
  INTERVALOS_POR_HORA, esIntradia, fechaHoraCorta, fechaHoraDeLaMira, marcasDeHoras, primeraVelaDelDia, textoEnCurso,
  textoMedicionPorHora, ubicadorPorHora, useVelasPorHora, velasRecientes,
} from '../../utils/velasPorHora'
import { proximoTic } from '../../utils/preciosEnVivo'
import { borrar as borrarDelAlmacen, guardar as guardarEnAlmacen, leer as leerDelAlmacen } from '../../utils/almacen'
import { CATALOGO } from '../../utils/catalogoDelAlmacen'

const v = (t) => `rgb(var(--${t}))`
const COLOR = {
  precio: v('ink-0'),
  media200: v('rendi-accent'),
  // Naranja categórico, no celeste: con el azul de la media de 200 tenían la
  // misma luminosidad en modo claro y para un daltónico eran la misma línea.
  media50: v('cat-orange'),
  promedio: v('ink-2'),
  // Balances y dividendos: violeta de la marca y verde azulado, que se
  // distinguen también por claridad (no sólo por el tono) y por la letra.
  balance: v('data-violet'),
  dividendo: v('cat-teal'),
  medir: v('rendi-accent'),
  // Tus dibujos (líneas de tendencia y horizontales): cian, que no es ninguna
  // de las capas calculadas.
  dibujo: v('data-cyan'),
  // Bandas de Bollinger: verde oliva. No se confunde con el azul de la de 200,
  // el naranja de la de 50, el magenta del Fibonacci ni el verde azulado de
  // los dividendos.
  bandas: v('cat-olive'),
}
const W = 1000
const H = 260
// Dos marcas de balance o dividendo más cerca que esto (en la pantalla) se
// juntan: es lo que ocupa una marca con su número al lado («D 2»).
const MARCA_PX = 34

// Con qué se abre un gráfico ANGOSTO (Nico, 29/10). En el celular el gráfico
// mide ~250 px: con «Todo» eran 752 velas a 0,33 px cada una, una mancha. La
// temporalidad (velas diarias o semanales) no cambia sola nunca, como en
// TradingView: lo que cambia es cuánto se ve al abrir. Las velas más recientes
// que entran a PX_POR_VELA, terminando hoy y con el aire de la derecha de
// siempre; «Todo» sigue en el menú y muestra la historia entera.
//   · 4 px: la vela es el 65 % de su lugar, así que queda un cuerpo de 2,6 px
//     con su color y 1,4 px de aire con la de al lado: se distingue cada una.
//     En 250 px entran ~60 velas, unos 3 meses de diarias (o ~14 meses de
//     semanales): el panorama del viejo rango «3M». Con 6 px serían 2 meses y
//     ya no se ve hacia dónde venía el precio.
//   · Se mide el ancho del GRÁFICO (no de la pantalla, R6): angosto es menos de
//     ANCHO_ANGOSTO. El celular más ancho (430 px) deja un gráfico de ~350; en
//     la compu, aun con la ficha angosta, pasa de 600. En la compu se abre con
//     «Todo», como siempre.
export const PX_POR_VELA = 4
export const ANCHO_ANGOSTO = 480
/**
 * Cuántos días de mercado se ven al abrir un gráfico de `ancho` px, o null si
 * es «Todo» (gráfico ancho, sin medir todavía, o la historia ya entra
 * completa). `porVela`: días por vela (5 en semanales).
 */
export function diasRecientes(ancho, total, porVela = 1) {
  if (!(ancho > 0) || ancho >= ANCHO_ANGOSTO) return null
  const lugares = Math.floor(ancho / PX_POR_VELA)
  // Las velas más su aire de la derecha (tecnico.margenDerecho, en días) tienen que entrar.
  let velas = lugares
  while (velas > RUEDAS_MINIMAS && velas + margenDerecho(velas * porVela) / porVela > lugares) velas--
  const dias = velas * porVela
  return dias < total ? dias : null
}

/**
 * Balances y dividendos en lo que se ve (Nico, 29/10): si dos dividendos
 * seguidos quedarían a menos de MARCA_PX en la pantalla, los dividendos no se
 * muestran (con la historia entera en el celular, cada marca era «4», mezcla
 * de todo). Quedan los balances, que son de a uno por trimestre; los
 * dividendos aparecen al acercar, cuando entran separados. `pctX(i)`: dónde
 * cae el lugar `i` (0 a 100); `ancho`: el del gráfico en px; `pxMaximo`: los
 * px por lugar con lo más acercado que se puede (RUEDAS_MINIMAS). Dos
 * dividendos tan pegados que ni así se separan (uno especial y uno normal en
 * la misma semana) no cuentan: si no, no se verían nunca y «acercá» sería
 * mentira; esos se juntan en una marca, como antes.
 */
export function dividendosAmontonados(eventos, pctX, ancho, pxMaximo = Infinity) {
  const ds = eventos.filter(e => e.tipo === 'dividendo').sort((a, b) => a.i - b.i)
  return ds.some((e, k) => k > 0
    && ((pctX(e.i) - pctX(ds[k - 1].i)) / 100) * ancho < MARCA_PX
    && (e.i - ds[k - 1].i) * pxMaximo >= MARCA_PX)
}
const H_RSI = 64
// Cuánto hay entre los dos primeros dedos (para pellizcar).
// Cuánto hay que mantener el dedo quieto para que deslizar pasee el globo de
// los datos en vez de mover el gráfico (como TradingView).
const MANTENER_MS = 400
const distanciaDedos = (t) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY)
const VOL_ALTO = 0.15  // la franja del volumen: el 15 % de abajo del gráfico de precio (más bajo y tenue: Nico, 29/10)
const H_ADX = 56
const H_SQUEEZE = 40
// El ADX se dibuja de 0 a 50 (casi nunca pasa; si pasa, la escala se estira).
const ADX_TOPE = 50
// Las barras del Squeeze: fuerte (creciendo) bien pintada, apagada (perdiendo
// empuje) más transparente, como en TradingView. La apagada no baja de 0,55: con
// 0,38 casi no se veía contra el fondo en modo claro (auditoría 22/10).
const SQUEEZE = {
  verde_fuerte: [v('rendi-pos-fill'), 1], verde_apagado: [v('rendi-pos-fill'), 0.55],
  rojo_fuerte: [v('rendi-neg-fill'), 1], rojo_apagado: [v('rendi-neg-fill'), 0.55],
}
// Línea o velas: lo que eligió la persona la última vez. El navegador puede
// tener el almacenamiento bloqueado (modo privado): entonces, línea.
const CLAVE_TIPO = 'rendi_grafico_tipo'
function tipoGuardado() {
  try { return leerDelAlmacen(CATALOGO.graficoTipo) === 'velas' ? 'velas' : 'linea' } catch { return 'linea' }
}
function guardarTipo(t) {
  try { guardarEnAlmacen(CATALOGO.graficoTipo, t) } catch { /* sin almacenamiento */ }
}
function olvidarTipo() {
  try { borrarDelAlmacen(CATALOGO.graficoTipo) } catch { /* sin almacenamiento */ }
}


// El volumen, corto: 1,2 M · 850 mil.
const VOLUMEN = new Intl.NumberFormat('es-AR', { notation: 'compact', maximumFractionDigits: 1 })
function fmtVolumen(n) { return VOLUMEN.format(n) }

function fmtPrecio(x, moneda) {
  if (x == null) return '—'
  // Abajo de 1 (una cripto de US$ 0,0004) van cifras significativas: con dos
  // decimales fijos el eje entero diría "US$ 0,00".
  const n = Math.abs(x) >= 1000 ? x.toLocaleString('es-AR', { maximumFractionDigits: 0 })
    : Math.abs(x) >= 1 ? x.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : x.toLocaleString('es-AR', { maximumSignificantDigits: 3 })
  return moneda === 'ars' ? `$ ${n}` : `US$ ${n}`
}

function fechaCorta(iso) {
  if (!iso) return ''
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y.slice(2)}`
}

// La ficha abierta desde el aviso de una línea tuya («Ver en el gráfico» de
// Mis alertas, el botón del mail o el push: /activo/AAPL?linea=…&moneda=…):
// cuál y en qué moneda (alerts_engine._camino_a_la_ficha). null si no vino.
function lineaDeLaDireccion() {
  try {
    const q = new URLSearchParams(window.location.search)
    const id = q.get('linea')
    return id ? { id, moneda: q.get('moneda') === 'ars' ? 'ars' : 'usd' } : null
  } catch { return null }
}

export default function LecturaTecnica({
  asset, symbolMiniChart, lotes = [], operaciones = [], pnlPctUsd = null,
  pnlPctLinea = undefined, lineaSinTc = false, referencia = null,
  costoPesos = null, accionLocal = false, tenencia = null, pesoEnCartera = null,
  // La ficha pone el título de la sección («Análisis técnico») y pasa null.
  titulo = 'Análisis técnico',
  // Tu tesis de este activo, cada versión (los `items` de /api/tesis de este
  // activo): una banderita por versión, en el día en que la escribiste
  // (NotasGrafico.jsx). `onVerTesis` lleva a la tesis de la ficha, donde se edita.
  tesis = [], onVerTesis = null,
  // La pestaña «Gráfico» de Análisis técnico: sólo el gráfico, sin «La lectura
  // de hoy» arriba y con las tarjetas de abajo como antes, en una grilla. En la
  // ficha van la lectura y las tarjetas en pestañas (LecturaDeHoy.jsx,
  // TarjetasPorTema.jsx).
  soloGrafico = false,
}) {
  const { hidden: oculto } = usePrivacy()
  const [moneda, setMoneda] = useState(() => (lineaDeLaDireccion()?.moneda === 'ars' ? 'ars' : 'usd'))
  // «Todo» (toda la historia que guarda Rendi), «Desde que lo tenés» o, en un
  // gráfico angosto, «Lo reciente» (diasRecientes). null = el de entrada: lo
  // reciente si el gráfico es angosto, si no «Todo». Los rangos cortos (3M,
  // 1A, 2A) se sacaron (Nico, 29/10); para acercar está la ruedita, pellizcar o
  // arrastrar las fechas.
  const [rango, setRango] = useState(null)
  // El ancho del gráfico en px, que mide el propio gráfico (null = sin medir).
  const [anchoGrafico, setAnchoGrafico] = useState(null)
  const [datos, setDatos] = useState({ usd: undefined, ars: undefined })
  // Qué capas se ven: la barra de herramientas prende y apaga cada una. De
  // entrada, todas (Nico, 24/10); lo que cada uno apaga queda guardado.
  const [ver, setVerEstado] = useState(capasGuardadas)
  const setVer = (f) => setVerEstado(x => { const n = typeof f === 'function' ? f(x) : f; guardarCapas(n); return n })
  // Lo que dice un botón sin datos al tocarlo (en el celular no hay globo).
  const [aviso, setAviso] = useState(null)
  // Balances y dividendos de la empresa, por moneda (lo que se movió el precio
  // es sobre la serie de esa moneda). Llegan después del gráfico: piden Yahoo.
  const [eventos, setEventos] = useState({ usd: undefined, ars: undefined })
  // Medir entre dos puntos, como la regla de TradingView: cada punto es un día
  // (`i`, contado sobre los días del gráfico; puede pasar de hoy, hacia
  // adelante) y el PRECIO donde se tocó, no el cierre (Nico, 24/10). Por día y
  // no por lugar en pantalla: sobreviven al zoom y al arrastre. a sin b =
  // esperando el segundo toque.
  const [medir, setMedirEstado] = useState({ activo: false, a: null, b: null })
  // Dibujar (utils/dibujos.js): la herramienta elegida ('tendencia',
  // 'horizontal'; a mano: 'fibonacci' (retroceso) y 'extension' de Fibonacci,
  // 'impulso' y 'correccion' de Elliott) y los toques ya hechos ({ i, precio }).
  // Una herramienta por vez: medir, dibujar o ninguna.
  const [dibujar, setDibujarEstado] = useState({ tipo: null, puntos: [] })
  const setMedir = (f) => { setDibujarEstado({ tipo: null, puntos: [] }); setMedirEstado(f) }
  // Prender una herramienta suelta lo elegido: si no, con una nota elegida y
  // otra escribiéndose, Suprimir borraba la elegida sin que se viera.
  const setDibujar = (f) => { setMedirEstado({ activo: false, a: null, b: null }); setElegido(null); setDibujarEstado(f) }
  useEffect(() => {
    setMedirEstado(m => ({ ...m, a: null, b: null }))
    setDibujarEstado(d => ({ ...d, puntos: [] }))
    setElegido(null)
    setTextoNota('')
  }, [moneda])
  // Tus dibujos, por moneda (en pesos y en dólares los precios son otros), y el
  // que está elegido para borrarlo. Se muestra al instante la copia de este
  // navegador; los de tu cuenta llegan después y mandan (utils/dibujos.js).
  // Son de una persona en una cuenta (`dueno`, utils/dibujos.js): si cambia
  // (el asesor pasa a otro cliente, otra pestaña cambia la sesión) se arranca
  // de cero con los de la cuenta nueva, en vez de seguir mostrando —y subiendo
  // a la nueva— los de la anterior.
  const dueno = useDuenoDeLaCopia()
  const [dibujos, setDibujos] = useState({})
  const [elegido, setElegido] = useState(null)
  // Tus notas (NotasGrafico.jsx): lo que se está escribiendo, en una nota
  // nueva o en la elegida (`editandoNota`: true mientras se corrige).
  const [textoNota, setTextoNota] = useState('')
  const [editandoNota, setEditandoNota] = useState(false)
  useEffect(() => { setEditandoNota(false) }, [elegido])
  useEffect(() => { if (dibujar.tipo !== 'nota') setTextoNota('') }, [dibujar.tipo])
  // Mirando la cuenta de un cliente (asesor), tus notas no van: son tuyas y no
  // dicen de qué cliente son (el servidor tampoco las manda ni las toca ahí).
  const conNotas = !getClientContext()
  const misDibujos = (dibujos[moneda] ?? dibujosGuardados(asset, moneda, dueno)).filter(d => conNotas || d.tipo !== 'nota')
  // Las monedas en las que ya dibujaste algo en esta visita: si los de la
  // cuenta llegan después, no pisan lo recién dibujado.
  const tocados = useRef(new Set())
  // Deshacer y rehacer (Nico, 29/10), como TradingView: cada cambio de tus
  // dibujos queda anotado con cómo estaba ANTES ({ dibujos } y, si el cambio
  // también apagó un automático, { ver: { fib } }). Deshacer vuelve a esa
  // foto y guarda la de ahora para rehacer; un cambio nuevo borra lo que había
  // para rehacer. Por activo y moneda, y sólo en esta visita (hasta 50 pasos).
  const historia = useRef({ atras: [], adelante: [] })
  useEffect(() => { historia.current = { atras: [], adelante: [] } }, [asset, moneda])
  const fotoComo = (e) => ({
    ...(e.dibujos ? { dibujos: misDibujos } : {}),
    ...(e.ver ? { ver: Object.fromEntries(Object.keys(e.ver).map(k => [k, !!ver[k]])) } : {}),
    // Los avisos que el cambio apagó (al borrar su línea): ir para un lado los
    // prende, para el otro los apaga.
    ...(e.avisos ? { avisos: { ids: e.avisos.ids, prender: !e.avisos.prender } } : {}),
  })
  const anotar = (e) => {
    const h = historia.current
    h.atras = [...h.atras.slice(-49), e]
    h.adelante = []
  }
  const volver = (de, a) => {
    const e = historia.current[de].pop()
    if (!e) return
    historia.current[a].push(fotoComo(e))
    if (e.dibujos) cambiarDibujos(e.dibujos, { sinAnotar: true })
    if (e.ver) setVer(x => ({ ...x, ...e.ver }))
    if (e.avisos) {
      Promise.all(e.avisos.ids.map(id => api.patch(`/alerts/${id}`, { active: e.avisos.prender }).catch(() => null)))
        .then(() => avisos.recargar())
    }
    setNotaAviso(null)
    setElegido(null)
    setDibujarEstado({ tipo: null, puntos: [] })
  }
  const deshacer = () => volver('atras', 'adelante')
  const rehacer = () => volver('adelante', 'atras')
  // Otra persona u otra cuenta en esta pestaña (`dueno`): se arranca de cero,
  // sin los dibujos ni la historia de deshacer de la anterior.
  const duenoVisto = useRef(dueno)
  if (duenoVisto.current !== dueno) {
    duenoVisto.current = dueno
    tocados.current = new Set()
    historia.current = { atras: [], adelante: [] }
    if (Object.keys(dibujos).length) setDibujos({})
  }
  // `apaga`: el automático que este cambio apaga ('fib' o 'ell'), para que
  // deshacer lo vuelva a prender.
  // El color de los dibujos nuevos: el último que elegiste (utils/dibujos).
  const [colorNuevo, setColorNuevo] = useState(colorDeLosNuevos)
  const cambiarDibujos = (listaPedida, { sinAnotar = false, apaga = null } = {}) => {
    // Un dibujo nuevo (que no estaba) sale con el color de los nuevos.
    const lista = sinAnotar || colorNuevo === 'cian' ? listaPedida
      : listaPedida.map(d => (d.color || misDibujos.some(x => x.id === d.id) ? d : { ...d, color: colorNuevo }))
    if (!sinAnotar) anotar({ dibujos: misDibujos, ...(apaga ? { ver: { [apaga]: !!ver[apaga] } } : {}) })
    // Otro cambio: el cartel del aviso (y su «Deshacer») era del anterior.
    setNotaAviso(null)
    tocados.current.add(moneda)
    // `dueno` es el de los dibujos que se ven (el de este dibujo): si otra
    // pestaña ya cambió la cuenta y esto todavía no se redibujó, ni la copia
    // ni la subida van a la cuenta nueva.
    const m = moneda, d = dueno
    guardarDibujos(asset, m, lista, true, d)
    setDibujos(x => ({ ...x, [m]: lista }))
    subirDibujos(asset, m, lista, d).then(ok => {
      if (ok === true) marcarSubidos(asset, m, lista, d)
      else if (ok?.cuentaCambiada) setAviso('No se guardó: en otra pestaña se cambió de cuenta y este gráfico muestra la anterior. Recargá la página.')
      else if (ok) setAviso(`Tus dibujos quedaron sólo en este navegador. ${ok}`)
      else setAviso('No se pudieron guardar tus dibujos en tu cuenta: por ahora quedaron en este navegador. Se vuelve a intentar la próxima vez que abras este gráfico.')
    })
  }
  useEffect(() => {
    let vivo = true
    const m = moneda
    const d = dueno
    dibujosDelServidor(asset, m).then(deLaCuenta => {
      if (!vivo || deLaCuenta == null || tocados.current.has(m)) return
      const local = copiaLocal(asset, m, d)
      if (local.pendiente) {
        // Un cambio hecho acá —por ESTA persona en ESTA cuenta— que no llegó a
        // la cuenta (el guardado falló): se sube. `=== true`: si el servidor lo
        // rechaza, `subirDibujos` devuelve el motivo (un texto, E3) y eso no es
        // «subido».
        subirDibujos(asset, m, local.dibujos, d).then(ok => { if (ok === true) marcarSubidos(asset, m, local.dibujos, d) })
        return
      }
      guardarDibujos(asset, m, deLaCuenta, false, d)
      setDibujos(x => ({ ...x, [m]: deLaCuenta }))
    })
    return () => { vivo = false }
  }, [asset, moneda, dueno])
  // Borrar el Fibonacci o el conteo AUTOMÁTICOS es apagarlos (Nico, 28/10: «si
  // el usuario la borra, es como desactivarla»); se prenden de nuevo desde su
  // botón de la barra. Lo demás son tus dibujos.
  const borrarDibujo = (id) => {
    if (id === ID_FIB_AUTO) { anotar({ ver: { fib: !!ver.fib } }); setVer(x => ({ ...x, fib: false })) }
    else if (id === ID_ELL_AUTO) { anotar({ ver: { ell: !!ver.ell } }); setVer(x => ({ ...x, ell: false })) }
    else {
      const d = misDibujos.find(x => x.id === id)
      cambiarDibujos(misDibujos.filter(x => x.id !== id))
      const apagados = apagarAvisosDe([id])
      anotarAvisos(apagados)
      if (apagados.length) {
        setNotaAviso({ texto: `Borraste ${d?.tipo === 'canal' ? 'tu canal' : 'tu línea'} y se apagó su aviso. Queda en Mis alertas, apagado.`, deshacer: true, tono: 'borrado' })
      }
    }
    setElegido(null)
  }
  // Borrar una línea con aviso apaga el aviso en el momento (el servidor
  // también lo apagaría esa noche, al no encontrarla). Apagado, no borrado:
  // queda en Mis alertas por si fue sin querer.
  function apagarAvisosDe(ids) {
    const lista = ids.map(dibujo => alertaDeLinea(avisos.items, { asset, moneda, dibujo })).filter(Boolean)
    if (!lista.length) return []
    Promise.all(lista.map(a => api.patch(`/alerts/${a.id}`, { active: false }).catch(() => null)))
      .then(() => avisos.recargar())
    return lista.map(a => a.id)
  }
  // El borrado recién anotado también apagó estos avisos: deshacerlo los prende.
  function anotarAvisos(ids) {
    const ultimo = historia.current.atras[historia.current.atras.length - 1]
    if (ids.length && ultimo) ultimo.avisos = { ids, prender: true }
  }
  // Si el automático elegido se apaga por otro lado (su botón), deja de estar elegido.
  useEffect(() => {
    if ((elegido === ID_FIB_AUTO && !ver.fib) || (elegido === ID_ELL_AUTO && !ver.ell)) setElegido(null)
  }, [elegido, ver.fib, ver.ell])
  const queEsElegido = elegido === ID_FIB_AUTO ? 'fibAuto' : elegido === ID_ELL_AUTO ? 'ellAuto'
    : misDibujos.find(d => d.id === elegido)?.tipo
  // ¿Borrar todos? Se pregunta antes: es trabajo de la persona y no se deshace.
  const [borrarTodos, setBorrarTodos] = useState(false)
  // Con una línea elegida, la tecla Suprimir (o la de borrar) la borra. Y Esc,
  // como en TradingView, cancela lo que se está dibujando o midiendo (se borra
  // lo marcado a medias y la herramienta se apaga).
  const borrarRef = useRef(null)
  // Una banderita de tu tesis o un grupo de banderitas no se borran con la tecla:
  // la tesis se borra donde se edita (la ficha) y el grupo es varias cosas.
  // Con una nota escribiéndose o corrigiéndose, las teclas son del texto
  // (aunque el foco haya quedado afuera): ni Suprimir ni Cmd+Z tocan los dibujos.
  const escribiendo = (dibujar.tipo === 'nota' && dibujar.puntos.length > 0) || editandoNota
  borrarRef.current = elegido && !escribiendo && !dibujar.tipo && !esClaveDeTesis(elegido) && !esClaveDeGrupo(elegido) ? () => borrarDibujo(elegido) : null
  const cancelarRef = useRef(null)
  const deshacerRef = useRef(null)
  const rehacerRef = useRef(null)
  deshacerRef.current = escribiendo ? null : deshacer
  rehacerRef.current = escribiendo ? null : rehacer
  cancelarRef.current = (dibujar.tipo || medir.activo)
    ? () => { setDibujarEstado({ tipo: null, puntos: [] }); setMedirEstado({ activo: false, a: null, b: null }) }
    : null
  useEffect(() => {
    const tecla = (e) => {
      if (e.key === 'Escape' && cancelarRef.current) { cancelarRef.current(); return }
      // Cmd/Ctrl+Z deshace; Cmd/Ctrl+Shift+Z o Ctrl+Y rehace (fuera de un campo de texto).
      const z = String(e.key).toLowerCase()
      if ((e.metaKey || e.ctrlKey) && (z === 'z' || z === 'y') && !/^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName || '') && !e.target?.isContentEditable) {
        e.preventDefault()
        if (z === 'y' || e.shiftKey) rehacerRef.current?.()
        else deshacerRef.current?.()
        return
      }
      if (!borrarRef.current || !['Delete', 'Backspace'].includes(e.key)) return
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName || '') || e.target?.isContentEditable) return
      e.preventDefault()
      borrarRef.current()
    }
    window.addEventListener('keydown', tecla)
    return () => window.removeEventListener('keydown', tecla)
  }, [])
  const [tipo, setTipoEstado] = useState(tipoGuardado)
  const setTipo = (t) => { setTipoEstado(t); guardarTipo(t) }
  // Zoom con la rueda y arrastre: qué ruedas se ven ({ n: cuántas, fin: hasta
  // cuál, sin incluirla }). null = el del rango elegido («Todo», «Lo reciente» o «Desde que lo tenés»).
  const [ventana, setVentana] = useState(null)
  // Velas diarias siempre; semanales sólo si se eligen (para mirar el panorama
  // de 2 años). El análisis (Fibonacci, giros) se hace sobre las diarias.
  // 1H y 4H (Nico, 30/10): sus velas vienen de su propio pedido y la última
  // se mueve sola cada minuto (utils/velasPorHora.js). Sólo con velas.
  const [intervalo, setIntervalo] = useState('dia')
  const cadaHoras = tipo === 'velas' && esIntradia(intervalo) ? intervalo : null
  const porHoras = useVelasPorHora({ asset, moneda, local: accionLocal, cada: cadaHoras })
  // Otra temporalidad son otros lugares: el zoom y lo marcado a medias eran de la anterior.
  useEffect(() => {
    setVentana(null)
    setMedirEstado(m => ({ ...m, a: null, b: null }))
    setDibujarEstado(d => ({ ...d, puntos: [] }))
    setElegido(null)
  }, [cadaHoras])
  // Empezó otra hora y llegó una vela nueva: si se estaba mirando hasta la
  // última (acercado o corrido a mano), la vista la sigue, como TradingView.
  const velasHoras = porHoras.datos?.puntos?.length || 0
  const antesHoras = useRef({ clave: null, n: 0 })
  useEffect(() => {
    const clave = `${moneda}|${cadaHoras}`, antes = antesHoras.current
    antesHoras.current = { clave, n: velasHoras }
    if (!cadaHoras || antes.clave !== clave || !antes.n || velasHoras <= antes.n) return
    setVentana(v => (v && v.fin >= antes.n ? { ...v, fin: v.fin + (velasHoras - antes.n) } : v))
  }, [velasHoras, cadaHoras, moneda])
  // En 1H/4H, dólares y pesos pueden ser otro ticker con otras velas (la
  // acción de Nueva York o el CEDEAR de BYMA): el zoom, que cuenta velas, era
  // de las otras. En diarias queda como siempre.
  useEffect(() => {
    if (cadaHoras) setVentana(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moneda])
  // Pantalla completa (Nico, 28/10: «para un análisis profundo, que toda la
  // pantalla sea el gráfico, como entrar a TradingView»): la misma sección, fija
  // sobre toda la página y con el gráfico más alto; «Achicar» o Esc vuelven a la
  // ficha con el menú de Rendi. Mientras tanto la página de atrás no se mueve.
  // Esc primero cancela lo que se esté dibujando; recién el siguiente achica.
  const [grande, setGrande] = useState(false)
  useEffect(() => {
    if (!grande) return
    const antes = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const tecla = (e) => { if (e.key === 'Escape' && !cancelarRef.current) setGrande(false) }
    window.addEventListener('keydown', tecla)
    return () => { document.body.style.overflow = antes; window.removeEventListener('keydown', tecla) }
  }, [grande])
  const elegirRango = (r) => { setRango(r); setVentana(null) }
  // Las alertas de la cuenta, para que cada «Avisame» sepa si ya hay una igual.
  // Arriba de los return de abajo: un hook después de un return rompe la ficha.
  const avisos = useAvisosTecnicos()
  // La escala de precios del gráfico para la imagen de «Compartir»: la de la
  // pantalla sin estirarse hasta tu precio, también la estirada a mano (que
  // arranca de esa, no de la pantalla: ejesGrafico.empezarAMano).
  const escala = useRef(null)
  // Lo que le pasó al aviso de la línea que moviste o borraste (Nico, 29/10):
  // { texto, deshacer, tono } o null. Lo limpia el próximo cambio.
  const [notaAviso, setNotaAviso] = useState(null)
  // Abierta desde el aviso de una línea: esa línea elegida, cuando tus dibujos
  // de esa moneda están (la copia del navegador o, después, los de la cuenta).
  const lineaPedida = useRef(lineaDeLaDireccion())
  const anclaLinea = useRef(null)
  useEffect(() => {
    const p = lineaPedida.current
    if (!p || p.moneda !== moneda || !misDibujos.some(d => d.id === p.id)) return
    lineaPedida.current = null
    setElegido(p.id)
    anclaLinea.current?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
  }, [moneda, misDibujos])

  // Dólares al abrir; pesos recién la primera vez que se tocan (la mayoría no
  // los mira y es otra cuenta en el servidor). Otro activo = otro componente
  // (la ficha lo monta con `key`), así que no hay que limpiar nada a mano.
  // Un pedido que falla se guarda como { error } (no como "no hay datos"): la
  // pantalla lo dice y ofrece reintentar, en vez de mostrar otro gráfico.
  const ref = referencia?.simbolo ? `&ref=${encodeURIComponent(referencia.simbolo)}` : ''
  useEffect(() => {
    if (datos[moneda] !== undefined) return
    let vivo = true
    api.get(`/tecnico/${encodeURIComponent(asset)}?moneda=${moneda}${accionLocal ? '&local=1' : ''}${ref}`)
      .then(r => { if (vivo) setDatos(d => ({ ...d, [moneda]: r })) })
      .catch(() => { if (vivo) setDatos(d => ({ ...d, [moneda]: { error: true } })) })
    return () => { vivo = false }
  }, [asset, moneda, accionLocal, ref, datos])
  const reintentar = () => setDatos(d => ({ ...d, [moneda]: undefined }))

  const actual = datos[moneda]
  const conGrafico = !!actual?.disponible
  // «✦ Analizar con Mervall-E»: el estado acá (antes de los `return` tempranos),
  // el botón y el panel donde toque (ResumenMervalle.jsx).
  const mervalle = useResumenMervalle({
    asset, moneda, local: accionLocal, resumen: actual?.resumen,
    alTenerlo: (r) => setDatos(d => ({ ...d, [moneda]: { ...d[moneda], resumen: r } })),
  })
  // La vela de hoy (y algún día cerrado que la noche todavía no guardó): se
  // dibuja (sumarVelaDeHoy) y cuenta para medir, tu tesis y tus compras de hoy;
  // la lectura, el Fibonacci y los dibujos siguen con las velas guardadas.
  const vivas = useVelaDeHoy(asset, moneda, accionLocal, conGrafico)
  // La ficha quedó abierta de un día para el otro y la noche guardó otra vela:
  // la serie se vuelve a pedir sola (sin el gris de carga), y así la de hoy
  // sigue a la última guardada en vez de quedar pegada a la de anteayer.
  const ultimaDeLaSerie = actual?.puntos?.[actual.puntos.length - 1]?.d
  useEffect(() => {
    if (!vivas?.base || !ultimaDeLaSerie || !(vivas.base > ultimaDeLaSerie)) return undefined
    let vivo = true
    api.get(`/tecnico/${encodeURIComponent(asset)}?moneda=${moneda}${accionLocal ? '&local=1' : ''}${ref}`)
      .then(r => { if (vivo && r?.disponible) setDatos(d => ({ ...d, [moneda]: r })) })
      .catch(() => {})
    return () => { vivo = false }
  }, [vivas?.base, ultimaDeLaSerie, asset, moneda, accionLocal, ref])
  useEffect(() => {
    if (!conGrafico || eventos[moneda] !== undefined) return
    let vivo = true
    api.get(`/tecnico/${encodeURIComponent(asset)}/eventos?moneda=${moneda}${accionLocal ? '&local=1' : ''}`)
      .then(r => { if (vivo) setEventos(e => ({ ...e, [moneda]: r?.eventos || [] })) })
      .catch(() => { if (vivo) setEventos(e => ({ ...e, [moneda]: [] })) })
    return () => { vivo = false }
  }, [asset, moneda, accionLocal, conGrafico, eventos])
  // «Desde que lo tenés»: sólo si tenés el activo hoy.
  const primera = primeraCompra(lotes)

  // Otra persona está bajando la historia de este activo ahora mismo
  // (`motivo: 'bajando'`): el servidor no deja un pedido esperando, así que se
  // vuelve a pedir solo, unas pocas veces.
  const intentos = useRef(0)
  useEffect(() => {
    if (actual?.motivo !== 'bajando' || intentos.current >= 5) return
    const t = setTimeout(() => { intentos.current += 1; reintentar() }, 3000)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actual])

  // Tu resultado para dibujar la LÍNEA de tu precio:
  //   · dólares: al dólar del día de cada compra (`pnlPctLinea`), sin importar
  //     la preferencia de la pantalla; null si a alguna compra le falta ese dólar;
  //   · pesos: sólo si todo lo compraste en pesos (`costoPesos`, con la cuenta
  //     de costo de la ficha) y el gráfico es el de BYMA (misma unidad que tus
  //     lotes). Si no, no se dibuja: no hay un "precio en pesos" tuyo que sea verdad.
  const pnlPct = useMemo(() => {
    if (moneda === 'usd') return pnlPctLinea === undefined ? pnlPctUsd : pnlPctLinea
    if (!actual?.disponible || actual.convertida || !costoPesos) return null
    const ultimo = actual.puntos[actual.puntos.length - 1]?.c
    return costoPesos.invertido > 0 && ultimo > 0
      ? (costoPesos.cantidad * ultimo) / costoPesos.invertido - 1 : null
  }, [moneda, pnlPctUsd, pnlPctLinea, actual, costoPesos])

  // `visto`: el rango que se está viendo (null si se acercó o movió a mano);
  // `recientes`: cuántos días es «Lo reciente» (null = no hace falta).
  // `arriba`: «La lectura de hoy», encima del marco. Su lugar existe siempre
  // (null mientras carga): así el marco no se vuelve a armar al llegar los datos.
  const marco = (hijos, { conPesos = datos.ars?.disponible !== false, visto = ventana ? null : rango ?? (anchoGrafico > 0 && anchoGrafico < ANCHO_ANGOSTO ? 'reciente' : 'todo'), recientes = null, textoReciente = null, compartir = null, antesDeCompartir = null, arriba = null } = {}) => (
    <>{arriba}<Marco moneda={moneda} setMoneda={setMoneda} rango={visto} setRango={elegirRango} recientes={recientes} textoReciente={textoReciente} compartir={compartir} antesDeCompartir={antesDeCompartir} archivo={archivoDelGrafico(asset)}
      conPesos={conPesos} conTuyo={!!primera} tipo={tipo} setTipo={setTipo} intervalo={intervalo} setIntervalo={setIntervalo}
      grande={grande} setGrande={setGrande} titulo={titulo}>{hijos}</Marco></>
  )
  // Cargando: el marco con sus botones queda quieto y el gris va adentro, con la
  // altura del gráfico ya reservada (antes desaparecía todo y la página saltaba).
  // La MISMA altura que el gráfico (altoDelGrafico), también en pantalla
  // completa: era un 22rem fijo y, al pasar a 4H con las velas tardando, el
  // gráfico ampliado se achicaba y volvía a agrandarse (Nico, 31/10).
  const cargando = <div role="status" aria-label="Cargando gráfico" className={`${altoDelGrafico(grande)} rounded-lg bg-bg-2/40 esqueleto`} />
  if (actual === undefined) {
    return moneda === 'usd' && datos.ars === undefined && !datos.usd ? (
      <div role="status" aria-label="Cargando gráfico" className="h-72 mb-5 rounded-lg bg-bg-2/40 border border-line esqueleto" />
    ) : marco(cargando)
  }
  if (actual?.error) {
    return marco(
      <div className="flex flex-wrap items-center gap-3 py-6 justify-center text-sm text-ink-1">
        No se pudo cargar el gráfico.
        <button type="button" onClick={reintentar}
          className="min-h-10 px-3 rounded-lg border border-line-2 text-ink-0 hover:bg-bg-2">Reintentar</button>
      </div>)
  }
  if (!actual?.disponible) {
    if (moneda === 'ars' && datos.usd?.disponible) {
      return marco(<p className="text-sm text-ink-2">Este activo no tiene precio en pesos.</p>, { conPesos: false })
    }
    // Sin velas: el gráfico de siempre. Si el servidor no las pudo traer en el
    // momento (un activo que nadie sigue), se dice por qué (`motivo`).
    const aviso = actual?.motivo === 'bajando' && intentos.current < 5
      ? 'Estamos trayendo la historia de este activo…'
      : actual?.motivo === 'tope' || actual?.motivo === 'bajando'
      ? 'Ahora no pudimos traer la historia completa de este activo. Probá de nuevo en un rato.'
      : actual?.motivo === 'sin_datos'
        ? 'No encontramos la historia de precios de este activo para el análisis técnico.'
        : null
    return symbolMiniChart ? (
      <section className="mb-5">
        {aviso && <p className="text-[13px] text-ink-1 mb-2">{aviso}</p>}
        <div className="text-[12.5px] text-ink-2 mb-2 font-medium">Precio · últimos 30 días</div>
        <div className="bg-bg-1 border border-line/60 rounded-lg p-3">
          <AssetMiniChart symbol={symbolMiniChart} />
        </div>
      </section>
    ) : null
  }

  // En 1H y 4H el gráfico dibuja las velas de horas (`serie`); la lectura, las
  // tarjetas, tu precio y lo demás siguen saliendo de las diarias (`actual`).
  // Lo que se guarda por día (tus dibujos, tus notas) se ubica por fecha y
  // hora con `porHora` (utils/velasPorHora.ubicadorPorHora).
  const horas = cadaHoras && porHoras.datos?.disponible && porHoras.datos.puntos?.length ? porHoras.datos : null
  const serie = horas ? horas.puntos : actual.puntos
  const porHora = horas ? ubicadorPorHora(serie, { sesion: horas.sesion, cada: cadaHoras, diarios: actual.puntos }) : null
  const total = serie.length
  const semanales = tipo === 'velas' && intervalo === 'semana'
  // Cuántos días muestra el rango elegido; «Desde que lo tenés», desde tu
  // primera compra; «Lo reciente», las velas que entran a un ancho legible
  // (en 1H y 4H, también en la compu: «Todo» son ~1.000 velas).
  const recientes = horas ? velasRecientes(anchoGrafico, total) : diasRecientes(anchoGrafico, total, semanales ? 5 : 1)
  const rangoVisto = rango ?? (recientes ? 'reciente' : 'todo')
  const nRango = rangoVisto === 'tuyo' && primera
    ? Math.max(RUEDAS_MINIMAS, puntosDesde(serie, primera))
    : rangoVisto === 'reciente' && recientes ? recientes
      : total
  // La ventana en LUGARES (ver tecnico.margenDerecho): los días que se ven más
  // el aire vacío de la derecha, por donde se puede arrastrar hacia el futuro.
  const inicial = ventanaInicial(nRango, total)
  const v0 = ventana || inicial
  const nVista = v0.n
  const finVista = Math.min(v0.fin, total + futuroMaximo(nVista))
  const inicioVista = Math.max(0, finVista - nVista)
  const diarios = serie.slice(inicioVista, Math.min(finVista, total))
  const huecosDias = Math.max(0, finVista - total)
  const puntos = semanales ? velasSemanales(diarios, actual.puntos.slice(Math.max(0, inicioVista - 7), inicioVista)) : diarios
  const huecos = semanales ? Math.round(huecosDias / 5) : huecosDias
  // La vela de hoy (useVelaDeHoy) se suma a las diarias y semanales; en 1H/4H
  // las horas traen su propia vela en curso (al juntar las dos, 30/10).
  const dibujo = sumarVelaDeHoy({ puntos, huecos, vivas: horas ? null : vivas, ultimaGuardada: actual.puntos[actual.puntos.length - 1]?.d,
    semanales, diarios, previos: actual.puntos.slice(Math.max(0, inicioVista - 7), inicioVista), alBorde: finVista >= total })
  const conHoy = dibujo.puntos[dibujo.puntos.length - 1]?.hoy ? dibujo.puntos[dibujo.puntos.length - 1] : null
  // Las velas vivas que se ven, como días más de la serie (en diarias ocupan
  // los lugares siguientes al último guardado, `diaDelLugar` da esos índices):
  // medir, tu tesis de hoy y tus compras de hoy caen en ellas y no en «lo que
  // todavía no pasó».
  const vivasVistas = semanales ? [] : dibujo.puntos.slice(puntos.length)
  const serieConHoy = horas ? serie : vivasVistas.length ? [...actual.puntos, ...vivasVistas] : actual.puntos
  const vista = { n: nVista, fin: finVista, total }
  // true = el gesto ya usó lo que venía juntando: movió el gráfico o lo empujó
  // contra el tope (ver tecnico.zoomEnElTope). Los tres gestos empiezan de cero.
  const zoom = (factor, f) => { const v2 = zoomVentana(vista, factor, f); if (v2) setVentana(v2); return !!v2 || zoomEnElTope(vista, factor) }
  const mover = (frac) => { const v2 = moverVentana(vista, frac); if (v2) setVentana(v2) }
  const promedio = lineaPromedio(actual.puntos, pnlPct,
    moneda === 'usd' ? variacionDeHoy(referencia?.precio, actual.cierre_ref) : 0)
  const ultimaFecha = actual.puntos[actual.puntos.length - 1]?.d
  // Hasta el último día que se dibuja: con la vela de hoy, hoy; en 1H/4H, hoy
  // también (las diarias todavía no lo tienen).
  const misMarcas = marcas(lotes, operaciones).filter(m => m.fecha <= serieConHoy[serieConHoy.length - 1]?.d)
  // Si los precios no se pudieron actualizar en más de una semana, se avisa
  // arriba (antes sólo se veía la fecha en letra chica al pie).
  const diasViejo = ultimaFecha ? Math.floor((Date.now() - Date.parse(ultimaFecha + 'T12:00:00Z')) / 86400000) : 0
  const lista = tarjetas(actual.lectura)
  const distintas = tendenciasDistintas(datos.usd?.lectura, datos.ars?.lectura)
  const alternar = (k) => setVer(x => ({ ...x, [k]: !x[k] }))
  const losEventos = eventos[moneda] || []
  // Al prender el Fibonacci o las ondas, el gráfico se acerca a lo medido si se
  // ve chico, con el aire de la derecha de siempre.
  const acercar = (v2) => { if (v2) setVentana({ n: v2.n + margenDerecho(v2.n), fin: v2.fin + margenDerecho(v2.n) }) }
  const deFabrica = sonDeFabrica(ver) && tipo === 'linea'
  const volverDeFabrica = () => {
    setVerEstado({ ...CAPAS_DE_FABRICA }); olvidarCapas()
    setTipoEstado('linea'); olvidarTipo()
    setMedirEstado({ activo: false, a: null, b: null })
    setDibujarEstado({ tipo: null, puntos: [] })
  }
  // Un toque en el gráfico (modo medir): el lugar `k` (puede caer en el
  // espacio vacío de la derecha) y el precio a esa altura. En velas semanales,
  // el ÚLTIMO día de esa semana (el de la vela); hacia adelante, cada vela son 5
  // días de mercado.
  const porVela = semanales ? 5 : 1
  const diaDelLugar = (k) => {
    if (k > puntos.length - 1) return total - 1 + Math.round((k - (puntos.length - 1)) * porVela)
    if (!semanales) return inicioVista + k
    const sig = puntos[k + 1]
    const j = sig ? Math.max(0, indiceDeFecha(diarios, sig.d) - 1) : diarios.length - 1
    return inicioVista + j
  }
  // Y al revés: dónde cae en lo que se ve un día medido (fuera de la vista,
  // un lugar afuera del ancho; el gráfico lo dibuja contra el borde).
  const lugarDelDia = (i) => {
    // Una vela por lugar (diarias, 1H y 4H): siempre a su distancia del primer
    // lugar que se ve, también hacia adelante o antes de la historia. La
    // cuenta de abajo, «desde la última vela que se ve», sólo valía mirando
    // hasta hoy: con el gráfico corrido hacia atrás, una línea que llegaba a
    // la vela en curso (con decimales, en 1H) se dibujaba corrida.
    if (!semanales) return i - inicioVista
    if (i > total - 1) return puntos.length - 1 + (i - (total - 1)) / porVela
    // Antes de la historia guardada (un punto anclado en un día que ya se
    // borró): afuera a la izquierda, a su distancia (utils/dibujos diaDelPunto).
    if (i < 0) return lugarDelDia(0) + i / porVela
    const d = actual.puntos[i]?.d
    const k = d ? indiceDeFecha(puntos, d) : null
    return k != null ? k : (d < (puntos[0]?.d || '') ? -1 : puntos.length)
  }
  // Lo que se guarda de un punto tocado (`i`: su lugar en la serie del
  // gráfico) y, al revés, en qué lugar cae un punto guardado: por día en
  // diarias y semanales; por fecha y hora en 1H/4H (null: antes de las velas
  // de horas que hay, no se sabe dónde va y no se dibuja).
  const puntoGuardado = (i, precio, f = 0) => (porHora
    ? porHora.puntoDelLugar(i + f, precio, { fraccion: f > 0 }) : puntoDelDia(actual.puntos, i, precio, f))
  const lugarGuardado = (q) => (porHora ? porHora.lugarDelPunto(q) : diaDelPunto(actual.puntos, q))
  const tocar = (k, precio) => {
    if (!(precio > 0)) return
    const p = { i: diaDelLugar(k), precio }
    const guardado = (q) => puntoGuardado(q.i, q.precio)
    if (dibujar.tipo === 'nota') {
      // Una nota: el punto y después el texto (el cartel de arriba). Tocar
      // otro punto antes de guardar la cambia de lugar.
      setDibujarEstado({ tipo: 'nota', puntos: [p] })
    } else if (dibujar.tipo === 'horizontal') {
      cambiarDibujos([...misDibujos, { id: idNuevo(), tipo: 'horizontal', precio: precioRedondo(precio) }])
      setDibujarEstado({ tipo: null, puntos: [] })     // una línea por vez, como TradingView
    } else if (dibujar.tipo === 'tendencia' || dibujar.tipo === 'fibonacci') {
      if (!dibujar.puntos.length) { setDibujarEstado({ tipo: dibujar.tipo, puntos: [p] }); return }
      cambiarDibujos([...misDibujos, { id: idNuevo(), tipo: dibujar.tipo, a: guardado(dibujar.puntos[0]), b: guardado(p) }],
        { apaga: dibujar.tipo === 'fibonacci' ? 'fib' : null })
      // Tu Fibonacci reemplaza al automático (si no, se mezclan las rayas);
      // el automático se vuelve a prender desde su botón.
      if (dibujar.tipo === 'fibonacci') {
        setVer(x => ({ ...x, fib: false }))
        // En 1H/4H el automático no se ve: se dice, si no, al volver a 1D no estaba.
        if (horas && ver.fib) setAviso('Se apagó el Fibonacci automático de las velas diarias, para que no se mezcle con el tuyo. Se vuelve a prender desde el botón Fibonacci, en 1D.')
      }
      setDibujarEstado({ tipo: null, puntos: [] })
    } else if (dibujar.tipo === 'canal') {
      // El canal paralelo (Nico, 29/10): dos toques para la línea de abajo y
      // el tercero, a la altura de la paralela (arriba o abajo).
      const puntos = [...dibujar.puntos, p]
      if (puntos.length < 3) { setDibujarEstado({ tipo: 'canal', puntos }); return }
      const [a, b] = puntos.map(guardado)
      const ancho = anchoDelCanal({ k: puntos[0].i, precio: puntos[0].precio }, { k: puntos[1].i, precio: puntos[1].precio }, { k: p.i, precio: p.precio })
      if (Math.abs(ancho) > 0) cambiarDibujos([...misDibujos, { id: idNuevo(), tipo: 'canal', a, b, ancho: Math.round(ancho * 1e4) / 1e4 || ancho }])
      setDibujarEstado({ tipo: null, puntos: [] })
    } else if (dibujar.tipo === 'extension') {
      const puntos = [...dibujar.puntos, p]
      if (puntos.length < 3) { setDibujarEstado({ tipo: 'extension', puntos }); return }
      const [a, b, c] = puntos.map(guardado)
      cambiarDibujos([...misDibujos, { id: idNuevo(), tipo: 'extension', a, b, c }])
      setDibujarEstado({ tipo: null, puntos: [] })
    } else if (FORMA_ELLIOTT[dibujar.tipo]) {
      // El segundo click de un doble click cae en el mismo lugar que el
      // primero: no es una onda nueva (el doble click termina el conteo).
      const ult = dibujar.puntos[dibujar.puntos.length - 1]
      if (ult && ult.i === p.i && Math.abs(ult.precio - p.precio) <= ult.precio * 0.002) return
      const puntos = [...dibujar.puntos, p]
      if (puntos.length >= etiquetasDe(FORMA_ELLIOTT[dibujar.tipo]).length) terminarElliott(puntos)
      else setDibujarEstado({ tipo: dibujar.tipo, puntos })
    } else {
      setMedirEstado(m => (m.a && !m.b ? { ...m, b: p } : { activo: true, a: p, b: null }))
    }
  }
  // Tu conteo de Elliott se termina con «Terminar acá», con doble click o click
  // derecho en el gráfico (uno que va por la onda 3) o solo, al llegar a la 5
  // (impulso) o a la C (corrección). Como con el Fibonacci, apaga el automático.
  function terminarElliott(puntos = dibujar.puntos) {
    const forma = FORMA_ELLIOTT[dibujar.tipo]
    if (puntos.length >= 2 && forma) {
      cambiarDibujos([...misDibujos, { id: idNuevo(), tipo: 'elliott', forma, puntos: puntos.map(q => puntoGuardado(q.i, q.precio)) }], { apaga: 'ell' })
      setVer(x => ({ ...x, ell: false }))
      if (horas && ver.ell) setAviso('Se apagó el conteo automático de Elliott de las velas diarias, para que no se mezcle con el tuyo. Se vuelve a prender desde el botón Ondas de Elliott, en 1D.')
    }
    setDibujarEstado({ tipo: null, puntos: [] })
  }
  // Un trazo del pincel (Nico, 29/10), ya soltado: cada punto a su día, con
  // la fracción del lugar para que no quede en escalones. La herramienta
  // sigue prendida (se dibuja de a varios trazos) hasta Esc o «Listo».
  const trazarPincel = (lista) => {
    const puntos = lista.map(q => {
      const base = Math.max(0, Math.floor(q.k))
      return puntoGuardado(diaDelLugar(base), q.precio, q.k - base)
    })
    if (puntos.length >= 2) cambiarDibujos([...misDibujos, { id: idNuevo(), tipo: 'pincel', puntos: puntos.slice(0, PINCEL_MAXIMO) }])
  }
  // Doble click o click derecho en el gráfico mientras se cuenta: «hasta acá».
  const terminarDesdeElGrafico = () => {
    if (FORMA_ELLIOTT[dibujar.tipo] && dibujar.puntos.length >= 2) { terminarElliott(); return true }
    return false
  }
  // Soltaste un dibujo arrastrado (Grafico): `que` es la punta agarrada o
  // 'todo'; `dk`, cuántos lugares se corrió y `dp`, cuánto precio. Cada punta
  // se guarda otra vez por día, como al dibujarla: en diarias un lugar es un
  // día; en semanales, el día de esa vela (o 5 días por vela antes del gráfico).
  const moverDibujo = (id, que, dk, dp) => {
    const correr = (q) => {
      const i = lugarGuardado(q)
      // En 1H/4H se corre por velas y se guarda el momento nuevo; corrida sólo
      // de precio, el punto queda donde estaba (día, hora y todo), como en diarias.
      if (porHora && !dk) return { ...q, precio: precioRedondo(precioCorrido(q.precio, dp)) }
      if (porHora) return porHora.puntoDelLugar(Math.max(0, i + dk), precioCorrido(q.precio, dp), { fraccion: q.f != null })
      const k = lugarDelDia(i) + dk
      // Corrida sólo de precio, el día queda (en semanales, si no, iría al
      // último día de su semana) y también su hora, si se dibujó en 1H/4H.
      // El pincel conserva dónde iba dentro del día (`f`).
      const i2 = !semanales || !dk ? i + dk : k >= 0 ? diaDelLugar(Math.round(k)) : i + Math.round(dk * porVela)
      const nuevo = puntoDelDia(actual.puntos, Math.max(0, i2), precioCorrido(q.precio, dp), q.f || 0)
      return !dk && q.t != null ? { ...nuevo, t: q.t } : nuevo
    }
    cambiarDibujos(misDibujos.map(d => (d.id !== id ? d
      : dibujoCorrido(d, que, correr, (x) => precioRedondo(precioCorrido(x, dp)), dp))))
    // Con aviso: el aviso la sigue (lee la línea guardada cada noche). Se dice.
    if (alertaDeLinea(avisos.items, { asset, moneda, dibujo: id })) {
      const canal = misDibujos.find(d => d.id === id)?.tipo === 'canal'
      setNotaAviso({ texto: `Moviste ${canal ? 'tu canal' : 'tu línea'}. El aviso ${canal ? 'lo' : 'la'} sigue: desde la próxima rueda mira esta posición.`, deshacer: true })
    }
  }
  // Los dibujos en lo que se ve: cada punto en su lugar (`k`) y su precio.
  // En 1H/4H el lugar ya trae la fracción de la vela; un dibujo con algún
  // punto sin lugar (antes de las velas de horas que hay) no se dibuja ahí.
  const enVista = (q) => {
    const i = lugarGuardado(q)
    return i == null ? null : { k: lugarDelDia(i) + (porHora ? 0 : (q.f || 0)), precio: q.precio }
  }
  const dibujosEnVista = misDibujos.map(d => (d.tipo === 'horizontal' ? d
    : d.tipo === 'elliott' || d.tipo === 'pincel' ? { ...d, puntos: d.puntos.map(enVista) }
      : { ...d, a: enVista(d.a), ...(d.b ? { b: enVista(d.b) } : {}), ...(d.c ? { c: enVista(d.c) } : {}) }))
    .filter(d => !(d.puntos || [d.a, d.b, d.c]).some(q => q === null))
  const sinLugarEnHoras = porHora ? misDibujos.length - dibujosEnVista.length : 0
  // Cada versión de tu tesis, en el día en que la escribiste (o el día de
  // mercado de antes, si fue un fin de semana) y al cierre de ese día. Antes
  // de lo que hay guardado, no va.
  // En 1H/4H, la última vela de ese día: su cierre es el del día.
  const tesisEnVista = tesis.map(t => {
    const i = indiceDeFecha(serieConHoy, String(t.escrita_el || '').slice(0, 10))
    if (i == null || !(serieConHoy[i]?.c > 0)) return null
    return { id: t.id, texto: t.texto, escrita_el: t.escrita_el, k: lugarDelDia(i), precio: serieConHoy[i].c }
  }).filter(Boolean)
  // La nota nueva, ya escrita: se guarda con el resto (deshacer la incluye).
  const guardarNota = () => {
    const texto = limpiarNota(textoNota), p = dibujar.puntos[0]
    if (!texto || !p) return
    cambiarDibujos([...misDibujos, { id: idNuevo(), tipo: 'nota', a: puntoGuardado(p.i, p.precio), texto }])
    setDibujarEstado({ tipo: null, puntos: [] })
    setTextoNota('')
  }
  const corregirNota = (id, texto) => {
    const t = limpiarNota(texto)
    if (!t) return
    cambiarDibujos(misDibujos.map(d => (d.id === id ? { ...d, texto: t } : d)))
    setEditandoNota(false)
  }
  // «Ver tu tesis»: desde pantalla completa, primero vuelve a la ficha.
  const verTesis = onVerTesis ? () => { setElegido(null); if (grande) setGrande(false); setTimeout(onVerTesis, 0) } : null
  // Los avisos de líneas miran cada noche la línea por DÍA (backend
  // tecnico.valor_de_linea): una inclinada dibujada en 1H/4H con las dos
  // puntas el mismo día no la pueden seguir (nunca avisaban), y una que
  // cruza días la seguirían con la inclinación que tiene en diarias, no la
  // que se ve en horas. Por eso el aviso de una inclinada se pone en diarias,
  // y nunca para una que empieza y termina el mismo día. Con un aviso ya
  // puesto, el botón queda: es por donde se apaga.
  const sinAvisoDeLinea = (() => {
    const d = misDibujos.find(x => x.id === elegido)
    if (!d || (d.tipo !== 'tendencia' && d.tipo !== 'canal')) return null
    if (alertaDeLinea(avisos.items, { asset, moneda, dibujo: d.id })) return null
    if (horas) return 'Los avisos de líneas miran el cierre de cada día: para ponerle uno a esta, elegila en velas diarias (1D).'
    if (diaDelPunto(actual.puntos, d.a) === diaDelPunto(actual.puntos, d.b)) {
      return 'Esta línea empieza y termina el mismo día: el aviso, que mira el cierre de cada día, no la puede seguir.'
    }
    return null
  })()
  const herramienta = medir.activo ? 'medir' : dibujar.tipo
  const medida = medir.activo ? medirEntre(serieConHoy, medir.a, medir.b) : null
  // Lo que dice un punto medido: su día, o cuántos días de mercado después de
  // hoy. En 1H/4H, su día y su hora, o cuántas velas después de la última.
  const diaDicho = (fecha, adelante) => (fecha ? `el ${fechaCorta(fecha)}` : `dentro de ${adelante} día${adelante === 1 ? '' : 's'} de mercado`)
  const cuandoDicho = (i) => {
    const adelante = i - (total - 1)
    if (!horas) return diaDicho(serieConHoy[i]?.d, i - (serieConHoy.length - 1))
    return adelante > 0 ? `dentro de ${adelante} vela${adelante === 1 ? '' : 's'}` : `el ${fechaHoraCorta(serie[i].t)}`
  }
  const textoDeMedicion = (m) => (horas ? textoMedicionPorHora(m, cadaHoras) : textoMedicion(m))
  const tenenciaEnMoneda = tenencia?.valorUsd > 0
    ? { valor: moneda === 'usd' ? tenencia.valorUsd : tenencia.valorUsd * (tenencia.tc || 0) } : null

  // «Compartir» (Nico, 29/10): la imagen de lo que se ve, con las capas
  // prendidas y tus dibujos (utils/imagenGrafico.js). No recibe tu precio,
  // tus compras ni tus avisos: la imagen no lleva nada de tu cartera.
  // «Desde que lo tenés» arranca el día de tu primera compra (y el «% en el
  // período» sería casi lo que ganaste): antes de armarla, el gráfico pasa a
  // «Todo», así lo que se manda sigue siendo lo que se ve (auditoría 29/10).
  const antesDeCompartir = rangoVisto === 'tuyo' && !ventana ? () => elegirRango('todo') : null
  // El cartel de las notas: escribiendo una nueva (con su punto ya tocado) o
  // con una nota, una versión de tu tesis o un grupo de banderitas elegido.
  const cartelDeNotas = borrarTodos ? null
    : dibujar.tipo === 'nota' ? (dibujar.puntos.length ? 'escribir' : null)
      : !dibujar.tipo && elegido && (queEsElegido === 'nota' || esClaveDeTesis(elegido) || esClaveDeGrupo(elegido)) ? 'elegido' : null
  const lugaresMinimos = (RUEDAS_MINIMAS + margenDerecho(RUEDAS_MINIMAS)) / (semanales ? 5 : 1)
  const compartir = () => specDelGrafico({
    activo: asset, moneda, puntos: dibujo.puntos, huecos: dibujo.huecos, lo: escala.current?.min, hi: escala.current?.max,
    ver, tipo, semanales, cada: horas ? cadaHoras : null, dibujos: dibujosEnVista,
    fibonacci: horas ? null : actual.fibonacci, elliott: horas ? null : actual.elliott,
    eventos: losEventos, convertida: actual.convertida, fechaDatos: actual.lectura?.fecha,
    precio: (x) => fmtPrecio(x, moneda), volAlto: VOL_ALTO, adxTope: ADX_TOPE, squeeze: SQUEEZE, ultimaFecha,
    // Los dividendos que se pisarían se esconden con la misma regla que en la pantalla, al ancho de la imagen.
    amontonados: (evs, pctX) => dividendosAmontonados(evs, pctX, ANCHO_DEL_GRAFICO, ANCHO_DEL_GRAFICO / Math.max(1, lugaresMinimos - 1)),
    colores: { ...COLOR, fibonacci: COLOR_FIB, elliott: COLOR_ELLIOTT, grilla: v('chart-grid'),
      sube: v('rendi-pos-fill'), baja: v('rendi-neg-fill'), positivo: v('rendi-pos'), negativo: v('rendi-neg') },
  })

  const botones = botonesDeLaBarra({
    actual, ver, alternar, losEventos, eventosCargando: eventos[moneda] === undefined,
    misMarcas, promedio, moneda, pnlPctUsd, lineaSinTc, medir, setMedir,
    tenes: pnlPctUsd != null, operaste: pnlPctUsd != null || lotes.length > 0 || operaciones.length > 0,
    dibujar, setDibujar, cuantosDibujos: misDibujos.length, conNotas, cuantosSon: cuantosSon(misDibujos), pedirBorrarTodos: () => { setElegido(null); setBorrarTodos(true) },
    deshacer, rehacer, puedeDeshacer: historia.current.atras.length > 0, puedeRehacer: historia.current.adelante.length > 0,
    nVista, acercar, serie, cada: horas ? cadaHoras : null,
  })

  return marco(
    <>
      {diasViejo > 7 && (
        <div className="rounded-lg border border-rendi-warn/40 bg-rendi-warn/10 px-3.5 py-2.5 mb-3 text-[13px] text-ink-1">
          <b className="text-rendi-warn font-semibold">Los precios son del {fechaCorta(ultimaFecha)}.</b> No se pudieron actualizar desde ese día.
        </div>
      )}
      {moneda === 'ars' && distintas && (
        <div className="rounded-lg border border-rendi-warn/40 bg-rendi-warn/10 px-3.5 py-3 mb-3">
          <div className="text-sm font-semibold text-rendi-warn">En pesos, la tendencia es distinta que en dólares.</div>
          <p className="text-[13px] text-ink-1 leading-relaxed mt-1">
            Parte de lo que se mueve en pesos es el dólar, no la empresa. Por eso Rendi mira la tendencia en dólares.
          </p>
        </div>
      )}

      <div className="flex flex-col sm:flex-row gap-1.5 sm:gap-3">
        <BarraGrafico onAviso={setAviso} grupos={botones.barra} />
        <div className="min-w-0 flex-1">
          {aviso && (
            <div role="status" className="mb-2 flex items-start justify-between gap-2 rounded-lg border border-line-2 bg-bg-2/60 px-3 py-2 text-[12.5px] text-ink-1 leading-relaxed">
              <span>{aviso}</span>
              <button type="button" onClick={() => setAviso(null)} aria-label="Cerrar aviso"
                className="shrink-0 -my-1 -mr-1 min-h-8 px-2 rounded text-ink-2 hover:text-ink-0">✕</button>
            </div>
          )}
          {/* Lo que dicen las herramientas de dibujo y la de medir (qué tocar,
              borrar la línea elegida, cuánto dio): arriba del gráfico. Abajo
              quedaba debajo de todos los paneles (en el celular, fuera de la
              pantalla) y encima del gráfico tapaba justo donde se quiere tocar. */}
          {medir.activo && (
            <div role="status" aria-live="polite"
              className="mb-2 rounded-lg border border-rendi-accent/30 bg-rendi-accent/10 px-3 py-2 text-[12.5px] text-ink-1 leading-relaxed">
              {!medir.a && 'Tocá cualquier punto del gráfico para empezar a medir: el precio y el día donde tocás. También podés tocar el espacio vacío de la derecha, para medir hacia adelante.'}
              {medir.a && !medir.b && (
                <span className="tabular">{`Desde ${fmtPrecio(medir.a.precio, moneda)}, ${cuandoDicho(medir.a.i)}. Ahora tocá el otro punto.`}</span>
              )}
              {medida && (
                <>
                  <b className={`font-semibold tabular ${medida.diferencia === 0 ? 'text-ink-0' : medida.pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{textoDeMedicion(medida)}</b>
                  {medida.diferencia !== 0 && (
                    <span className="tabular">{`: de ${fmtPrecio(medida.precioDesde, moneda)} (${cuandoDicho(Math.min(medir.a.i, medir.b.i))}) a ${fmtPrecio(medida.precioHasta, moneda)} (${cuandoDicho(Math.max(medir.a.i, medir.b.i))}), ${medida.diferencia > 0 ? '+' : '−'}${fmtPrecio(Math.abs(medida.diferencia), moneda)}. `}</span>
                  )}
                  {medida.adelanteHasta > 0 && 'La parte a la derecha de hoy es una proyección: todavía no hay precios ahí. '}
                  Tocá otro punto para medir de nuevo.
                </>
              )}
            </div>
          )}
          <span ref={anclaLinea} aria-hidden="true" />
          {notaAviso && (
            <div role="status" aria-live="polite"
              className={`mb-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border px-3 py-2 text-[12.5px] text-ink-1 leading-relaxed ${notaAviso.tono === 'borrado' ? 'border-rendi-warn/45 bg-rendi-warn/10' : 'border-data-cyan/40 bg-data-cyan/10'}`}>
              <Bell size={14} aria-hidden="true" className={`flex-shrink-0 ${notaAviso.tono === 'borrado' ? 'text-rendi-warn' : 'text-data-cyan'}`} />
              <span className="flex-1 min-w-[12rem]">{notaAviso.texto}</span>
              {notaAviso.deshacer && (
                <button type="button" onClick={deshacer}
                  className="min-h-10 sm:min-h-8 px-3 rounded-lg border border-data-violet/50 bg-data-violet/10 text-ink-0 font-medium">Deshacer</button>
              )}
              <button type="button" onClick={() => setNotaAviso(null)}
                className="min-h-10 sm:min-h-8 px-3 rounded-lg border border-line-2 text-ink-1 hover:text-ink-0">Listo</button>
            </div>
          )}
          {cartelDeNotas ? (
            // Tus notas y tu tesis (NotasGrafico.jsx): escribir la nueva, o
            // leer, corregir, colorear o borrar la elegida. Arriba del
            // gráfico y a todo el ancho: en el celular, se lee entera.
            <div role="group" aria-label={cartelDeNotas === 'escribir' ? 'Tu nota nueva' : 'Tu nota'}
              className="mb-2 rounded-lg border border-data-cyan/40 bg-data-cyan/10 px-3 py-2 text-[12.5px] text-ink-1 leading-relaxed">
              <CartelDeNotas modo={cartelDeNotas} elegido={elegido} notas={misDibujos.filter(d => d.tipo === 'nota')} tesis={tesis}
                texto={textoNota} setTexto={setTextoNota} onGuardar={guardarNota}
                onCancelar={() => { setDibujarEstado({ tipo: null, puntos: [] }); setTextoNota('') }}
                editando={editandoNota} setEditando={setEditandoNota} onCorregir={corregirNota}
                onBorrar={borrarDibujo} onElegir={setElegido} onListo={() => setElegido(null)} onVerTesis={verTesis}
                precio={(x) => fmtPrecio(x, moneda)} fecha={fechaCorta}
                colores={(n) => (
                  <ColoresDelDibujo actual={n.color || 'cian'} onElegir={(c) => {
                    cambiarDibujos(misDibujos.map(d => (d.id === n.id ? { ...d, color: c } : d)))
                    setColorNuevo(c); recordarColor(c)
                  }} />
                )} />
            </div>
          ) : (dibujar.tipo || elegido || borrarTodos) && (
            <div role="status" aria-live="polite"
              className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-data-cyan/40 bg-data-cyan/10 px-3 py-2 text-[12.5px] text-ink-1 leading-relaxed">
              <span className="flex-1 min-w-[12rem]">
                {borrarTodos ? `¿Borrar ${cuantosSon(misDibujos)} de este activo en ${moneda === 'usd' ? 'dólares' : 'pesos'}? No se puede deshacer.`
                  : dibujar.tipo ? textoDibujando(dibujar)
                    : ELEGIDO[queEsElegido]?.[0]}
              </span>
              {borrarTodos ? (
                <>
                  <button type="button" onClick={() => {
                    const off = apagarAvisosDe(misDibujos.map(d => d.id)); cambiarDibujos([]); anotarAvisos(off); setBorrarTodos(false); setElegido(null)
                    if (off.length) setNotaAviso({ texto: off.length === 1 ? 'Se apagó el aviso de una de tus líneas. Queda en Mis alertas, apagado.' : `Se apagaron los avisos de ${off.length} de tus líneas. Quedan en Mis alertas, apagados.`, deshacer: true, tono: 'borrado' })
                  }}
                    className="min-h-10 sm:min-h-8 px-3 rounded-lg border border-rendi-neg/50 bg-rendi-neg/10 text-ink-0 font-medium">Sí, borrar</button>
                  <button type="button" onClick={() => setBorrarTodos(false)}
                    className="min-h-10 sm:min-h-8 px-3 rounded-lg border border-line-2 text-ink-1 hover:text-ink-0">No</button>
                </>
              ) : elegido && !dibujar.tipo ? (
                <>
                  <button type="button" onClick={() => borrarDibujo(elegido)}
                    className="inline-flex items-center gap-1.5 min-h-10 sm:min-h-8 px-3 rounded-lg border border-rendi-neg/50 bg-rendi-neg/10 text-ink-0 font-medium">
                    <Trash2 size={14} aria-hidden="true" />{ELEGIDO[queEsElegido]?.[1] || 'Borrar esta línea'}
                  </button>
                  {elegido !== ID_FIB_AUTO && elegido !== ID_ELL_AUTO && misDibujos.some(d => d.id === elegido) && (
                    <ColoresDelDibujo actual={misDibujos.find(d => d.id === elegido)?.color || 'cian'} onElegir={(c) => {
                      cambiarDibujos(misDibujos.map(d => (d.id === elegido ? { ...d, color: c } : d)))
                      setColorNuevo(c); recordarColor(c)
                    }} />
                  )}
                  {(queEsElegido === 'horizontal' || queEsElegido === 'tendencia' || queEsElegido === 'canal') && (
                    sinAvisoDeLinea
                      ? <span data-sin-aviso="" className="text-[12px] text-ink-2 leading-snug">{sinAvisoDeLinea}</span>
                      : <BotonAvisameLinea avisos={avisos} asset={asset} accionLocal={accionLocal} moneda={moneda}
                          dibujo={elegido} tipoLinea={queEsElegido} />
                  )}
                  <button type="button" onClick={() => setElegido(null)}
                    className="min-h-10 sm:min-h-8 px-3 rounded-lg border border-line-2 text-ink-1 hover:text-ink-0">Listo</button>
                </>
              ) : (
                <>
                  {FORMA_ELLIOTT[dibujar.tipo] && dibujar.puntos.length >= 2 && (
                    <button type="button" onClick={() => terminarElliott()}
                      className="min-h-10 sm:min-h-8 px-3 rounded-lg border border-data-cyan/60 bg-data-cyan/15 text-ink-0 font-medium">Terminar acá</button>
                  )}
                  <button type="button" onClick={() => setDibujarEstado({ tipo: null, puntos: [] })}
                    className="min-h-10 sm:min-h-8 px-3 rounded-lg border border-line-2 text-ink-1 hover:text-ink-0">
                    {/* Con el pincel lo dibujado ya quedó guardado: no se cancela nada, se termina. */}
                    {dibujar.tipo === 'pincel' ? 'Listo' : 'Cancelar'}
                  </button>
                </>
              )}
            </div>
          )}
          {cadaHoras && !horas ? (
            // 1H o 4H todavía sin sus velas: cargando, o lo que pasó (la
            // lectura y las tarjetas de abajo siguen siendo las diarias).
            porHoras.datos === undefined ? cargando : (
              <div role="status" className={`${altoDelGrafico(grande)} flex flex-col items-center justify-center gap-3 text-center text-sm text-ink-1 px-4`}>
                {porHoras.datos?.error
                  ? `No se pudieron traer las velas de ${INTERVALOS_POR_HORA[cadaHoras].nombre}.`
                  : porHoras.datos?.motivo === 'tope'
                    // El servidor llegó a su cupo de primeras descargas de la hora
                    // (velas_horarias.NUEVOS_*): no es que no existan.
                    ? `Ahora no pudimos traer las velas de ${INTERVALOS_POR_HORA[cadaHoras].nombre} de este activo. Probá de nuevo en un rato.`
                    : `No encontramos velas de ${INTERVALOS_POR_HORA[cadaHoras].nombre} de este activo.`}
                <span className="flex flex-wrap justify-center gap-2">
                  {(porHoras.datos?.error || porHoras.datos?.motivo === 'tope') && (
                    <button type="button" onClick={porHoras.reintentar}
                      className="min-h-10 px-3 rounded-lg border border-line-2 text-ink-0 hover:bg-bg-2">Reintentar</button>
                  )}
                  <button type="button" onClick={() => setIntervalo('dia')}
                    className="min-h-10 px-3 rounded-lg border border-line-2 text-ink-0 hover:bg-bg-2">Ver velas diarias</button>
                </span>
              </div>
            )
          ) : (
          <Grafico leyenda={
            <LeyendaIndicadores items={botones.indicadores} onAviso={setAviso} deFabrica={deFabrica} onFabrica={volverDeFabrica} />
          } grande={grande} puntos={dibujo.puntos} huecos={dibujo.huecos} moneda={moneda} promedio={ver.prom ? promedio : null}
            marcas={ver.marcas ? misMarcas : []} ver={ver} tipo={tipo} cada={horas ? cadaHoras : null}
            fibonacci={ver.fib && !horas ? actual.fibonacci : null} elliott={ver.ell && !horas ? actual.elliott : null} onZoom={zoom} onMover={mover}
            pie={
              // Cómo se usa, corto (Nico, 29/10): en el celular, para el dedo
              // (antes hablaba de «la ruedita»). Va pegado a las fechas, antes
              // del RSI y la fuerza: abajo de todo, con esos paneles prendidos,
              // caía donde flotan WhatsApp y Mervall-E y quedaba tapado.
              <div className="flex items-start gap-2">
                <p data-ayuda="" className="flex-1 min-w-0 text-[11.5px] text-ink-2 mt-0.5 leading-snug">
                  {semanales && 'Cada vela es una semana. '}
                  {horas && (
                    <>
                      {`Cada vela es ${cadaHoras === '4h' ? 'un bloque de 4 horas' : 'una hora'}, en hora de Argentina. `}
                      <EnCurso puntos={serie} actualizada={horas.actualizada} demora={horas.demora_min} />
                      {sinLugarEnHoras > 0 && `${sinLugarEnHoras === 1 ? 'Uno de tus dibujos arranca' : `${sinLugarEnHoras} de tus dibujos arrancan`} antes de las velas de ${INTERVALOS_POR_HORA[cadaHoras].nombre} que hay: ${sinLugarEnHoras === 1 ? 'se ve' : 'se ven'} en diarias. `}
                    </>
                  )}
                  {tipo === 'velas' && !semanales && !horas && diarios.length > 300 && 'Cada vela es un día: acercá o pasá a velas semanales. '}
                  {conHoy && <span data-hoy="">{textoVelaDeHoy(conHoy, semanales)} </span>}
                  <span className="sm:hidden">{`Pellizcá para acercar o alejar, deslizá para moverte, mantené apretado para ver cada ${horas ? 'vela' : 'día'} y tocá un dibujo para elegirlo.`}</span>
                  <span className="hidden sm:inline">Ruedita: acercar o alejar. Arrastrar: moverte. Doble click en los precios o las fechas: vuelve a automático.</span>
                </p>
                {/* «Compartir» en el celular: arriba no entra en el renglón de los controles. */}
                <CompartirGrafico armar={compartir} antes={antesDeCompartir} archivo={archivoDelGrafico(asset)} className="sm:hidden shrink-0" />
              </div>
            }
            lugaresMinimos={lugaresMinimos}
            onAncho={setAnchoGrafico} onFechasAuto={() => setVentana(null)} fechasAMano={ventana != null} reinicioPrecio={`${moneda}|${rangoVisto}|${tipo}|${intervalo}`}
            eventos={ver.eventos ? losEventos : []}
            medicion={medir.activo ? {
              a: medir.a && { k: lugarDelDia(medir.a.i), precio: medir.a.precio },
              b: medir.b && { k: lugarDelDia(medir.b.i), precio: medir.b.precio }, m: medida,
              // Con el primer punto puesto, lo que daría la medición hasta el mouse.
              hasta: medir.a && !medir.b ? (k, precio) => medirEntre(serieConHoy, medir.a, { i: diaDelLugar(k), precio }) : null,
            } : null}
            onToque={herramienta && herramienta !== 'pincel' ? tocar : null} onTerminar={terminarDesdeElGrafico}
            onPincel={herramienta === 'pincel' ? trazarPincel : null}
            colorNuevo={colorNuevo === 'cian' ? null : colorNuevo}
            dibujos={dibujosEnVista} elegido={elegido} onElegir={setElegido} onMoverDibujo={moverDibujo} escala={escala} tesis={tesisEnVista}
            conAviso={misDibujos.filter(d => alertaDeLinea(avisos.items, { asset, moneda, dibujo: d.id })).map(d => d.id)}
            trazo={dibujar.puntos.length ? { tipo: dibujar.tipo, puntos: dibujar.puntos.map(q => ({ k: lugarDelDia(q.i), precio: q.precio })) } : null} />
          )}
          {rangoVisto === 'tuyo' && !ventana && primera && primera < serie[0].d && (
            <p className="text-[11.5px] text-ink-2 mt-1">Lo tenés desde el {fechaCorta(primera)}; el gráfico empieza el {fechaCorta(serie[0].d)}, porque desde ahí hay historia de precios guardada.</p>
          )}
        </div>
      </div>

      {/* En la pestaña «Gráfico» no hay «La lectura de hoy»: Mervall-E va acá. */}
      {soloGrafico && mervalle.ofrecido && (
        <div className="mt-3 overflow-hidden rounded-xl border border-line/60">
          <div className="px-4 py-3"><BotonMervalle r={mervalle} /></div>
          <PanelMervalle r={mervalle} direccion={actual.fibonacci?.en_curso?.dir} />
        </div>
      )}

      <TarjetasPorTema enPestanas={!soloGrafico} Tarjeta={Tarjeta} lista={lista} lectura={actual.lectura} puntos={actual.puntos}
        ver={ver} fibonacci={actual.fibonacci} elliott={actual.elliott} moneda={moneda}
        precio={(x) => fmtPrecio(x, moneda)} fecha={fechaCorta} avisos={avisos} asset={asset} accionLocal={accionLocal}
        // En dólares, el MISMO resultado de arriba de la ficha; en pesos, el de lo que pagaste en pesos.
        resultado={moneda === 'usd' ? pnlPctUsd : pnlPct} lineaSinTc={lineaSinTc}
        movimiento={actual.movimiento} tenencia={tenenciaEnMoneda} peso={tenencia?.valorUsd > 0 ? pesoEnCartera : null}
        periodo={periodoDeMovimiento(actual.movimiento)} colores={{ media200: COLOR.media200, media50: COLOR.media50 }} />

      <p className="text-[12px] text-ink-2 mt-3 leading-relaxed">
        {moneda === 'usd' && 'Se mira en dólares aunque uses la app en pesos, porque en pesos el precio también sube con el dólar. Para verlo en pesos, tocá «US$» arriba del gráfico y elegí «Pesos». '}
        {actual.convertida === 'mep' && (moneda === 'usd'
          ? 'El precio en pesos de cada día está pasado a dólares con el MEP de ese día. '
          : 'El precio en dólares de cada día está pasado a pesos con el MEP de ese día. ')}
        Datos al cierre del {fechaCorta(actual.lectura?.fecha)}. Muestra cómo se movió el precio: no es una recomendación para comprar ni vender.
      </p>
    </>,
    // En 1H/4H «Lo reciente» se cuenta en velas, no en días de mercado.
    { visto: ventana ? null : rangoVisto, recientes, textoReciente: horas && recientes ? `${recientes} velas` : null, compartir, antesDeCompartir,
      arriba: soloGrafico ? null : <LecturaDeHoy lectura={actual.lectura} lista={lista} puntos={actual.puntos} adxTope={ADX_TOPE}
        boton={<BotonMervalle r={mervalle} ancho />}
        panel={<PanelMervalle r={mervalle} direccion={actual.fibonacci?.en_curso?.dir} />} /> },
  )
}

// La vela que todavía se mueve, en 1H/4H: «La última vela está en curso ·
// hace 20 s.» (en BYMA, con la demora de sus precios). Se reescribe sola
// (cada segundo; cada 15 s cuando ya dice minutos), sin redibujar el gráfico entero.
function EnCurso({ puntos, actualizada, demora = 0 }) {
  const [ahora, setAhora] = useState(Date.now)
  const ultima = puntos[puntos.length - 1]
  const enCurso = !!ultima?.enCurso
  useEffect(() => {
    if (!enCurso) return
    const t = setTimeout(() => setAhora(Date.now()), proximoTic(actualizada, ahora))
    return () => clearTimeout(t)
  }, [ahora, actualizada, enCurso])
  if (!ultima) return null
  if (!enCurso) return `La última vela es la del ${fechaHoraCorta(ultima.t)}. `
  // BYMA llega con demora (velas_diarias.DEMORA_MIN, la única): se dice, así el «hace
  // 20 s» no parece el precio de hace 20 s.
  return <span data-en-curso="">{`La última vela está ${textoEnCurso(actualizada, ahora)}${demora > 0 ? ` (los precios de esta bolsa llegan con unos ${demora} minutos de demora)` : ''}. `}</span>
}

// Las herramientas de Elliott a mano y la forma de conteo que dibujan.
const FORMA_ELLIOTT = { impulso: 'impulso', correccion: 'correccion' }

// Lo que dice el cartel mientras se dibuja. «Esc cancela», como TradingView.
function textoDibujando({ tipo, puntos }) {
  const esc = ' (Esc cancela.)'
  if (tipo === 'horizontal') return 'Tocá la altura del gráfico (el precio) donde va la línea horizontal.' + esc
  if (tipo === 'nota') return 'Tocá el punto del gráfico donde va tu nota: el día y el precio. Después la escribís.' + esc
  if (tipo === 'tendencia') {
    return (puntos.length ? 'Ahora tocá donde termina la línea (también podés tocar el espacio vacío de la derecha).'
      : 'Tocá donde empieza la línea de tendencia.') + esc
  }
  if (tipo === 'fibonacci') {
    return (puntos.length ? 'Ahora tocá donde termina el tramo (el máximo de la suba o el mínimo de la bajada).'
      : 'Retroceso: tocá donde empieza el tramo que querés medir (el mínimo donde arrancó una suba o el máximo donde arrancó una bajada). Al terminar se desactiva el Fibonacci automático, para que no se superpongan.') + esc
  }
  if (tipo === 'canal') {
    return ['Canal: tocá donde empieza la línea de abajo (o la de arriba).', 'Ahora tocá donde termina esa línea.',
      'Ahora tocá a qué altura va la paralela: el ancho del canal.'][puntos.length] + esc
  }
  if (tipo === 'pincel') return 'Dibujá con el mouse apretado (en el celular, con el dedo). Podés hacer varios trazos; Esc o «Listo» para terminar.'
  if (tipo === 'extension') {
    return ['Extensión: tocá donde empieza el movimiento (por ejemplo, el mínimo donde arrancó la suba).',
      'Ahora tocá donde termina el movimiento (por ejemplo, el máximo de la suba).',
      'Ahora tocá donde terminó el retroceso: desde ese punto se proyectan los niveles hacia adelante.'][puntos.length] + esc
  }
  if (FORMA_ELLIOTT[tipo]) {
    const etiquetas = etiquetasDe(FORMA_ELLIOTT[tipo])
    if (!puntos.length) {
      return (tipo === 'impulso'
        ? 'Impulso: tocá el arranque (el 0) y después, una por una, las ondas 1 a 5.'
        : 'Corrección: tocá dónde arranca y después las ondas A, B y C.') + ' Al terminar se desactiva el conteo automático.' + esc
    }
    return `Ahora tocá la onda ${etiquetas[puntos.length]}${puntos.length >= 2 ? '. Para terminar acá: doble click, click derecho o «Terminar acá»' : ''}.${esc}`
  }
  return ''
}

// «tu dibujo», «tus 3 dibujos», «tus 2 dibujos y tu nota»: las notas, aparte.
function cuantosSon(lista) {
  const n = lista.filter(d => d.tipo === 'nota').length, d = lista.length - n
  const dib = d === 1 ? 'dibujo' : `${d} dibujos`, not = n === 1 ? 'nota' : `${n} notas`
  return d && n ? `tus ${dib} y ${n === 1 ? 'tu' : 'tus'} ${not}` : n ? (n === 1 ? 'tu nota' : `tus ${not}`) : (d === 1 ? 'tu dibujo' : `tus ${dib}`)
}

// El cartel de un dibujo elegido: [qué es, el botón de borrar].
const ELEGIDO = {
  horizontal: ['Línea horizontal seleccionada. Arrastrala para cambiarle el precio.', 'Borrar esta línea'],
  tendencia: ['Línea de tendencia seleccionada. Arrastrala para moverla, o arrastrá una punta para corregirla.', 'Borrar esta línea'],
  fibonacci: ['Fibonacci seleccionado. Arrastralo para moverlo, o arrastrá una punta para corregir el tramo.', 'Borrar este Fibonacci'],
  extension: ['Extensión de Fibonacci seleccionada. Arrastrala para moverla, o arrastrá uno de sus puntos para corregirla.', 'Borrar esta extensión'],
  fibAuto: ['Fibonacci automático seleccionado. Si lo borrás, se desactiva; podés volver a activarlo desde el botón Fibonacci de la barra.', 'Borrar el Fibonacci automático'],
  ellAuto: ['Conteo automático de Elliott seleccionado. Si lo borrás, se desactiva; podés volver a activarlo desde el botón Ondas de Elliott de la barra.', 'Borrar el conteo automático'],
  elliott: ['Conteo de Elliott seleccionado. Arrastralo para moverlo, o arrastrá una onda para corregirla.', 'Borrar este conteo'],
  canal: ['Canal seleccionado. Arrastralo para moverlo, arrastrá una punta para corregir la línea, o la paralela para ensancharlo.', 'Borrar este canal'],
  pincel: ['Trazo seleccionado. Arrastralo para moverlo.', 'Borrar este trazo'],
}

// «Últimos 2 años» o, si hay menos guardado, desde cuándo.
function periodoDeMovimiento(m) {
  if (!m?.desde || !m?.hasta) return ''
  const dias = (Date.parse(m.hasta) - Date.parse(m.desde)) / 86400000
  return dias >= 700 ? 'Últimos 2 años' : `Desde el ${fechaCorta(m.desde)}`
}

function Marco({ moneda, setMoneda, rango, setRango, recientes = null, textoReciente = null, conPesos = true, conTuyo = false, tipo, setTipo, intervalo, setIntervalo, grande = false, setGrande, titulo, compartir = null, antesDeCompartir = null, archivo, children }) {
  // En la ficha, ya ampliado (Nico, 24/10: «que sea automáticamente ampliado»).
  // Con «Pantalla completa», la MISMA sección fija sobre toda la página (no es
  // otra vista: mismos datos, mismos botones; R6). Arriba a la derecha, en UN
  // renglón (Nico, 29/10: en el celular eran dos antes del gráfico): pantalla
  // completa, línea o velas, cada cuánto es una vela y un menú con la moneda y
  // el período. En el celular, «Pantalla completa» es sólo el ícono y cada
  // botón mide 44 px de alto (lo que pide un dedo).
  return (
    <section aria-label="Análisis técnico" role={grande ? 'dialog' : undefined} aria-modal={grande || undefined}
      className={grande ? 'fixed inset-0 z-[70] overflow-y-auto bg-bg-0 px-3 py-3 sm:px-6 sm:py-4' : 'mb-5'}>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        {titulo ? <div className="text-[12.5px] text-ink-2 font-medium">{titulo}</div> : <span />}
        {/* data-tour: lo ilumina el recorrido de Análisis técnico (tour/pasosTecnico.js). */}
        <div data-tour="grafico-vista" className="flex flex-wrap items-center justify-end gap-1.5 sm:gap-2">
          {/* «Compartir»: la imagen del gráfico (CompartirGrafico.jsx); sólo con
              gráfico. En el celular va al lado de la ayuda, abajo de las fechas. */}
          {compartir && <CompartirGrafico armar={compartir} antes={antesDeCompartir} archivo={archivo} className="hidden sm:inline-flex" />}
          {setGrande && (
            <button type="button" data-capa="pantalla" onClick={() => setGrande(!grande)} aria-pressed={grande}
              title={grande ? 'Volver a la ficha, con el menú de Rendi (también con Esc)' : 'Ver el gráfico en pantalla completa'}
              className={`inline-flex items-center justify-center gap-1.5 min-h-11 min-w-11 sm:min-h-8 sm:min-w-0 sm:px-3 rounded-lg border text-xs font-medium transition-colors ${grande ? 'border-line-2 bg-bg-2 text-ink-0 hover:border-ink-3' : 'border-rendi-accent/55 bg-rendi-accent/15 text-ink-0 hover:border-rendi-accent'}`}>
              {grande ? <Minimize2 size={16} aria-hidden="true" /> : <Maximize2 size={16} aria-hidden="true" />}
              <span className="sr-only sm:not-sr-only">{grande ? 'Achicar' : 'Pantalla completa'}</span>
            </button>
          )}
          {setTipo && (
            <div className="inline-flex gap-0.5 bg-bg-2 border border-line rounded-lg p-0.5" role="group" aria-label="Tipo de gráfico">
              {[['linea', 'Línea', <LineChart key="l" size={16} aria-hidden="true" />], ['velas', 'Velas', <IconoVelas key="v" />]].map(([id, nombre, icono]) => (
                <button key={id} type="button" data-capa={id} onClick={() => setTipo(id)} aria-pressed={tipo === id}
                  title={`Gráfico de ${nombre.toLowerCase()}`}
                  className={`inline-flex items-center justify-center min-h-11 min-w-11 sm:min-h-8 sm:min-w-8 rounded transition-colors ${tipo === id ? 'bg-bg-1 text-ink-0 shadow-sm' : 'text-ink-2 hover:text-ink-0 opacity-70 hover:opacity-100'}`}>
                  {icono}<span className="sr-only">{nombre}</span>
                </button>
              ))}
            </div>
          )}
          {tipo === 'velas' && setIntervalo && (
            <ElegirIntervalo valor={intervalo} alElegir={setIntervalo} />
          )}
          <ElegirVista moneda={moneda} setMoneda={setMoneda} conPesos={conPesos}
            rango={rango} setRango={setRango} recientes={recientes} textoReciente={textoReciente} conTuyo={conTuyo} />
        </div>
      </div>
      <div className="bg-bg-1 border border-line/60 rounded-xl p-3 sm:p-4">{children}</div>
    </section>
  )
}

// Un botón que despliega sus opciones debajo (como el «1D» de TradingView):
// se cierra al elegir, al tocar afuera o con Esc. `contenido(cerrar)` dibuja
// las opciones.
function Desplegable({ capa, etiqueta, titulo, boton, ancho = 'w-44', contenido }) {
  const [abierto, setAbierto] = useState(false)
  const caja = useRef(null)
  useEffect(() => {
    if (!abierto) return
    const fuera = (e) => { if (!caja.current?.contains?.(e.target)) setAbierto(false) }
    const esc = (e) => { if (e.key === 'Escape') setAbierto(false) }
    document.addEventListener('pointerdown', fuera)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('pointerdown', fuera); document.removeEventListener('keydown', esc) }
  }, [abierto])
  return (
    <div ref={caja} className="relative">
      <button type="button" data-capa={capa} aria-haspopup="menu" aria-expanded={abierto} onClick={() => setAbierto(!abierto)}
        title={titulo}
        className="inline-flex items-center gap-1 min-h-11 sm:min-h-8 px-3 rounded-lg border border-line bg-bg-2 text-xs font-medium text-ink-0 hover:border-ink-3 whitespace-nowrap">
        {boton}
        <ChevronDown size={13} aria-hidden="true" className={`text-ink-2 transition-transform ${abierto ? 'rotate-180' : ''}`} />
      </button>
      {abierto && (
        // Pegado a la derecha del botón: es el último del renglón y, a la
        // izquierda, en el celular se saldría de la pantalla.
        <div role="menu" aria-label={etiqueta} className={`absolute right-0 top-full mt-1 z-[60] ${ancho} rounded-lg border border-line-2 bg-bg-raised p-1 shadow-lg`}>
          {contenido(() => setAbierto(false))}
        </div>
      )}
    </div>
  )
}

// Una opción de un Desplegable: el nombre y, a la derecha, lo corto.
function Opcion({ elegida, onClick, nombre, detalle, ...resto }) {
  return (
    <button type="button" role="menuitemradio" aria-checked={elegida} onClick={onClick} {...resto}
      className={`flex w-full items-center justify-between gap-2 min-h-11 sm:min-h-8 px-2.5 rounded text-left text-[12.5px] ${elegida ? 'bg-bg-2 text-ink-0 font-medium' : 'text-ink-1 hover:bg-bg-2 hover:text-ink-0'}`}>
      <span>{nombre}</span>{detalle && <span className="tabular text-ink-2 font-normal">{detalle}</span>}
    </button>
  )
}

// Cada cuánto es una vela, como TradingView (Nico, 29/10): un botón con lo
// elegido («1D») que al tocarlo despliega las opciones. 1 hora y 4 horas
// (Nico, 30/10): sus velas se piden a Yahoo al elegirlas y la última se mueve
// sola (utils/velasPorHora.js); la lectura de abajo sigue siendo la diaria.
const INTERVALOS = [['1h', '1H', '1 hora'], ['4h', '4H', '4 horas'], ['dia', '1D', 'Diarias'], ['semana', '1S', 'Semanales']]
function ElegirIntervalo({ valor, alElegir }) {
  const actual = INTERVALOS.find(i => i[0] === valor) || INTERVALOS.find(i => i[0] === 'dia')
  return (
    <Desplegable capa="intervalo" etiqueta="Cada vela es" titulo={`Cada vela es: ${actual[2].toLowerCase()}`}
      boton={<><span className="sr-only">Cada vela es </span>{actual[1]}</>}
      contenido={(cerrar) => INTERVALOS.map(([id, corto, nombre]) => (
        <Opcion key={id} data-intervalo={id} elegida={valor === id} nombre={nombre} detalle={corto}
          onClick={() => { alElegir(id); cerrar() }} />
      ))} />
  )
}

// La moneda y el período, en UN menú (Nico, 29/10: eran dos filas de botones
// antes del gráfico). El botón dice lo elegido («US$ · Todo»); sin período
// cuando se acercó o movió a mano (ya no es ninguno de los de la lista).
const MONEDAS = [['usd', 'Dólares', 'US$'], ['ars', 'Pesos', '$']]
const RANGOS = { reciente: 'Lo reciente', todo: 'Todo', tuyo: 'Desde que lo tenés' }
// Lo corto, para el botón: en el celular, con velas, entra en el renglón hasta
// «US$ · Reciente» (medido a 375 px; «Desde tu compra» lo mandaba abajo).
const RANGOS_CORTOS = { reciente: 'Reciente', todo: 'Todo', tuyo: 'Lo tuyo' }
// «Lo reciente» en palabras: «3 meses», «6 semanas» (días de mercado: 21 por mes, 5 por semana).
function cuantoEsReciente(dias) {
  const meses = Math.round(dias / 21)
  if (meses >= 2) return meses >= 24 ? `${Math.round(dias / 252)} años` : `${meses} meses`
  return `${Math.max(1, Math.round(dias / 5))} semanas`
}
function ElegirVista({ moneda, setMoneda, conPesos, rango, setRango, recientes, textoReciente = null, conTuyo }) {
  const m = MONEDAS.find(x => x[0] === moneda) || MONEDAS[0]
  const rangos = [...(recientes || rango === 'reciente' ? ['reciente'] : []), 'todo', ...(conTuyo ? ['tuyo'] : [])]
  const titulo = (t) => <div className="px-2.5 pt-1.5 pb-0.5 text-[11px] font-semibold text-ink-2">{t}</div>
  return (
    <Desplegable capa="vista" etiqueta="Moneda y período" ancho="w-56"
      titulo={`En ${m[1].toLowerCase()}${rango ? `; ${RANGOS[rango].toLowerCase()}` : ''}`}
      boton={<><span className="sr-only">Moneda y período: </span>{m[2]}{rango && <span className="text-ink-1 font-normal">{` · ${RANGOS_CORTOS[rango]}`}</span>}</>}
      contenido={(cerrar) => (
        <>
          <div role="group" aria-label="Moneda">
            {titulo('Moneda')}
            {MONEDAS.filter(([id]) => id === 'usd' || conPesos).map(([id, nombre, corto]) => (
              <Opcion key={id} data-moneda={id} elegida={moneda === id} nombre={nombre} detalle={corto}
                onClick={() => { setMoneda(id); cerrar() }} />
            ))}
          </div>
          <div role="group" aria-label="Período" className="border-t border-line/60 mt-1 pt-0.5">
            {titulo('Período')}
            {rangos.map(id => (
              <Opcion key={id} data-rango={id} elegida={rango === id} nombre={RANGOS[id]}
                detalle={id === 'reciente' && recientes ? (textoReciente || cuantoEsReciente(recientes)) : null}
                onClick={() => { setRango(id); cerrar() }} />
            ))}
          </div>
        </>
      )} />
  )
}

/**
 * Los botones de la barra de herramientas (BarraGrafico.jsx), en grupos: el
 * tipo de gráfico; lo que va sobre el precio; los paneles de abajo; lo tuyo y
 * lo de la empresa; las herramientas. Una capa sin datos para este activo va
 * con `sinDatos` (el porqué): el botón queda, deshabilitado. Lo tuyo es la
 * excepción: si nunca operaste el activo no hay «Tus compras y ventas», y si
 * hoy no lo tenés no hay «Tu precio promedio» (Nico, 24/10: en la ficha de un
 * activo que no tenés no aparece nada tuyo).
 */
function botonesDeLaBarra({
  actual, ver, alternar, losEventos, eventosCargando, misMarcas, promedio, moneda,
  pnlPctUsd, lineaSinTc, tenes, operaste, medir, setMedir, nVista, acercar,
  dibujar, setDibujar, cuantosDibujos, cuantosSon: cuantosLista = '', conNotas = true, pedirBorrarTodos,
  deshacer, rehacer, puedeDeshacer, puedeRehacer, serie = actual.puntos, cada = null,
}) {
  const capa = (id, nombre, icono, sinDatos, onClick) => ({
    id, nombre, icono, activo: !sinDatos && !!ver[id], sinDatos: sinDatos || null, onClick: onClick || (() => alternar(id)),
  })
  const hay = (k) => serie.some(p => p[k] != null)
  const fib = actual.fibonacci
  const ell = actual.elliott
  // En 1H/4H: las velas de horas (las medias son de 200 y 50 VELAS).
  const unidad = cada === '4h' ? 'velas de 4 h' : cada ? 'horas' : 'días'
  const faltan = (n) => `Faltan datos: hacen falta ${n} ${cada ? unidad : 'días de mercado'}.`
  const sinFib = cada ? 'El Fibonacci automático se calcula con las velas diarias: elegí «1D» para verlo.'
    : !fib ? 'Este activo todavía no tiene el cálculo del Fibonacci.'
    : !fib.disponible && !fib.en_curso
      ? (fib.motivo === 'pocos_datos' ? 'Faltan datos: este activo tiene poca historia todavía.' : 'No hay un tramo de suba o de bajada para medir.')
      : null
  const sinEll = cada ? 'El conteo automático de ondas se hace con las velas diarias: elegí «1D» para verlo.'
    : !ell ? 'Este activo todavía no tiene el conteo de ondas.'
    : !ell.disponible
      ? (ell.motivo === 'pocos_datos'
        ? `Faltan datos: para contar ondas hacen falta al menos 30 días de mercado y este activo tiene ${ell.ruedas}.`
        : 'Con los máximos y mínimos de este activo no aparece ningún conteo que cumpla las reglas de la teoría, y Rendi no fuerza uno.')
      : null
  const sinProm = promedio != null ? null
    : moneda === 'usd' && lineaSinTc ? 'A alguna de tus compras le falta la cotización del dólar de ese día: sin ese dato, la línea quedaría mal ubicada.'
      : moneda === 'ars' && pnlPctUsd != null ? 'En pesos, sólo se dibuja si compraste todo en pesos y el gráfico es el de la Bolsa de Buenos Aires.'
        : 'Falta el resultado de tu compra para ubicar la línea.'
  const lleno = cuantosDibujos >= DIBUJOS_MAXIMOS ? `Llegaste a ${DIBUJOS_MAXIMOS} dibujos en este activo: borrá alguno para hacer otro.` : null
  const aMano = (id, nombre, detalle) => ({
    id, nombre, detalle, activo: dibujar.tipo === id, sinDatos: lleno,
    onClick: () => setDibujar({ tipo: id, puntos: [] }),
  })
  return {
    // La barra del costado: las herramientas de análisis (Nico, 28/10).
    // Agrupada por lo que hace, como TradingView (Nico, 29/10): las líneas y
    // el pincel en UN botón con su menú; Fibonacci y Elliott; medir, solo;
    // deshacer y rehacer; borrar.
    barra: [
      [
        { id: 'menu-lineas', nombre: 'Líneas y pincel', icono: (LINEAS.find(l => l.id === dibujar.tipo) || LINEAS[0]).icono,
          activo: LINEAS.some(l => l.id === dibujar.tipo),
          estado: LINEAS.find(l => l.id === dibujar.tipo)?.estado || 'Tendencia, horizontal, canal o a mano alzada',
          menu: LINEAS.map(l => aMano(l.id, l.nombre, l.detalle)) },
        // Una nota de texto en un punto (Nico, 30/10): «compré acá por el balance».
        // Mirando a un cliente, no (ver `conNotas`).
        conNotas && { id: 'nota', nombre: 'Nota', icono: <StickyNote size={17} color={COLOR.dibujo} />, activo: dibujar.tipo === 'nota', herramienta: true,
          sinDatos: lleno, estado: dibujar.tipo === 'nota' ? 'Tocá el punto del gráfico' : 'Escribí una nota en un día y un precio; sólo la ves vos',
          onClick: () => setDibujar(dibujar.tipo === 'nota' ? { tipo: null, puntos: [] } : { tipo: 'nota', puntos: [] }) },
      ].filter(Boolean),
      // Fibonacci y Elliott: el automático y el «a mano» desde UN lugar.
      [
        { id: 'menu-fibonacci', nombre: 'Fibonacci', icono: <IconoFibonacci />,
          activo: (!sinFib && !!ver.fib) || dibujar.tipo === 'fibonacci' || dibujar.tipo === 'extension',
          estado: dibujar.tipo === 'fibonacci' || dibujar.tipo === 'extension' ? 'Marcando a mano' : !sinFib && ver.fib ? 'Activado: lo calcula Rendi' : 'Lo calcula Rendi o lo marcás a mano',
          menu: [
            { id: 'fib', nombre: 'Automático', interruptor: true, activo: !!ver.fib, sinDatos: sinFib,
              detalle: 'Rendi busca el último tramo de suba o de bajada y dibuja sus niveles.',
              onClick: () => {
                // Al prenderlo, el gráfico se acerca al tramo medido (si se ve chico).
                if (!ver.fib) acercar(ventanaDelTramo(actual.puntos, fib, nVista))
                alternar('fib')
              } },
            aMano('fibonacci', 'Retroceso a mano', 'Marcá el tramo: dónde empieza y dónde termina. Desactiva el automático.'),
            aMano('extension', 'Extensión a mano', 'Tres toques: dónde empieza y dónde termina un movimiento, y dónde terminó su retroceso. Proyecta niveles hacia adelante.'),
          ] },
        { id: 'menu-elliott', nombre: 'Ondas de Elliott', icono: <IconoElliott />,
          activo: (!sinEll && !!ver.ell) || !!FORMA_ELLIOTT[dibujar.tipo],
          estado: FORMA_ELLIOTT[dibujar.tipo] ? 'Contando a mano' : !sinEll && ver.ell ? 'Activado: lo calcula Rendi' : 'Lo calcula Rendi o lo marcás a mano',
          menu: [
            { id: 'ell', nombre: 'Automático', interruptor: true, activo: !!ver.ell, sinDatos: sinEll,
              detalle: 'Rendi busca un conteo posible sobre los máximos y mínimos del gráfico.',
              onClick: () => {
                if (!ver.ell) acercar(ventanaDesde(actual.puntos, fechaDelConteo(ell), nVista))
                alternar('ell')
              } },
            aMano('impulso', 'Impulso 1-5 a mano', 'Tocá el 0 y las ondas 1 a 5. Desactiva el automático.'),
            aMano('correccion', 'Corrección A-B-C a mano', 'Tocá dónde empieza y las ondas A, B y C. Desactiva el automático.'),
          ] },
      ],
      [
        { id: 'medir', nombre: 'Medir entre dos puntos', icono: <Ruler size={18} />, activo: medir.activo, herramienta: true,
          estado: medir.activo ? 'Tocá dos puntos del gráfico' : 'Cuánto sube o baja entre dos puntos, también hacia adelante',
          onClick: () => setMedir(m => ({ activo: !m.activo, a: null, b: null })) },
      ],
      [
        { id: 'deshacer', nombre: 'Deshacer', icono: <Undo2 size={17} />,
          sinDatos: puedeDeshacer ? null : 'Todavía no hay nada para deshacer.',
          estado: 'Vuelve atrás el último cambio de tus dibujos (Cmd/Ctrl+Z)', onClick: deshacer },
        { id: 'rehacer', nombre: 'Rehacer', icono: <Redo2 size={17} />,
          sinDatos: puedeRehacer ? null : 'No hay nada para rehacer: primero deshacé algo.',
          estado: 'Vuelve a hacer lo que deshiciste (Cmd/Ctrl+Shift+Z)', onClick: rehacer },
      ],
      [
        { id: 'borrarDibujos', nombre: 'Borrar mis dibujos', icono: <Trash2 size={17} />,
          sinDatos: cuantosDibujos ? null : 'Todavía no dibujaste ni anotaste nada en este activo (en esta moneda).',
          estado: `${cuantosLista.charAt(0).toUpperCase()}${cuantosLista.slice(1)} de este activo. Para borrar uno solo, tocalo en el gráfico.`,
          onClick: pedirBorrarTodos },
      ],
    ],
    // La lista de arriba a la izquierda del gráfico: los indicadores, con su ojito.
    indicadores: [
      capa('vol', 'Volumen', <IconoVolumen />, serie.some(p => p.v > 0) ? null : 'No hay datos de volumen para este activo.'),
      capa('s200', `Promedio 200 ${unidad}`, <IconoLinea color={COLOR.media200} grueso />, hay('s200') ? null : faltan(200)),
      capa('s50', `Promedio 50 ${unidad}`, <IconoLinea color={COLOR.media50} />, hay('s50') ? null : faltan(50)),
      capa('bb', 'Bandas de Bollinger', <IconoBandas />, hay('bb_arriba') ? null : faltan(20)),
      capa('rsi', 'RSI', <IconoRsi />, hay('rsi') ? null : cada ? faltan(15) : 'Faltan datos: hacen falta al menos 15 días de mercado.'),
      capa('fuerza', 'Fuerza de la tendencia', <IconoFuerza />, hay('adx') || hay('squeeze') ? null : 'Faltan datos para calcularla.'),
      capa('eventos', 'Balances y dividendos', <span className="inline-flex gap-px"><Letra tipo="balance" /><Letra tipo="dividendo" /></span>,
        eventosCargando ? 'Cargando los balances y dividendos…'
          : losEventos.length ? null : 'No hay balances ni dividendos de este activo (pasa con las criptos, los índices y los fondos).'),
      operaste && capa('marcas', 'Tus compras y ventas', <IconoPuntos />, misMarcas.length ? null : 'No hay compras ni ventas tuyas de este activo.'),
      tenes && capa('prom', 'Tu precio promedio', <IconoLinea color={COLOR.promedio} punteado />, sinProm),
      capa('globo', 'Datos al pasar el mouse', <IconoGlobo />, null),
    ].filter(Boolean),
  }
}

// Los íconos de la barra muestran cómo se ve cada capa (su color y su forma):
// hacen también de referencia de colores, en lugar de la leyenda de abajo.
function IconoLinea({ color, grueso, punteado }) {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18">
      <path d={punteado ? 'M1 9h16' : 'M1 13c4-1 5-7 9-7s4 3 7 2'} fill="none" stroke={color} strokeWidth={grueso ? 3 : 2}
        strokeLinecap="round" strokeDasharray={punteado ? '3.5 2.5' : undefined} />
    </svg>
  )
}
function IconoVelas() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18">
      <line x1="5" y1="2" x2="5" y2="15" stroke={v('rendi-pos-fill')} strokeWidth="1.3" />
      <rect x="2.5" y="5" width="5" height="7" rx="0.6" fill={v('rendi-pos-fill')} />
      <line x1="13" y1="3" x2="13" y2="16" stroke={v('rendi-neg-fill')} strokeWidth="1.3" />
      <rect x="10.5" y="6" width="5" height="6" rx="0.6" fill={v('rendi-neg-fill')} />
    </svg>
  )
}
// Las dos bandas y el relleno de entre medio, como se ven en el gráfico.
function IconoBandas() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke={COLOR.bandas} strokeWidth="1.5" strokeLinecap="round">
      <path d="M1 7c4-3 6-3 8-1s5 1 8-2V12c-3 3-6 3-8 1s-4-2-8 1Z" fill={COLOR.bandas} fillOpacity="0.15" stroke="none" />
      <path d="M1 7c4-3 6-3 8-1s5 1 8-2" />
      <path d="M1 14c4-3 6-3 8-1s5 1 8-1" />
    </svg>
  )
}
function IconoVolumen() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18">
      <rect x="1.5" y="9" width="3.5" height="7" fill={v('rendi-pos-fill')} />
      <rect x="7.25" y="4" width="3.5" height="12" fill={v('rendi-neg-fill')} />
      <rect x="13" y="7" width="3.5" height="9" fill={v('rendi-pos-fill')} />
    </svg>
  )
}
function IconoFibonacci({ color = COLOR_FIB }) {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" stroke={color} strokeWidth="1.6" strokeLinecap="round">
      <line x1="1" y1="3" x2="17" y2="3" />
      <line x1="1" y1="7.5" x2="17" y2="7.5" strokeDasharray="2.5 2" />
      <line x1="1" y1="11" x2="17" y2="11" strokeDasharray="2.5 2" />
      <line x1="1" y1="15" x2="17" y2="15" />
    </svg>
  )
}
function IconoElliott({ color = COLOR_ELLIOTT }) {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18">
      <path d="M1 15 4.5 8 7 11 11.5 3 14 7 17 5" fill="none" stroke={color} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx="11.5" cy="3" r="1.6" fill={color} />
    </svg>
  )
}
function IconoRsi() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18">
      <line x1="1" y1="4" x2="17" y2="4" stroke={v('rendi-pos-fill')} strokeWidth="1" strokeDasharray="2 2" />
      <line x1="1" y1="14" x2="17" y2="14" stroke={v('rendi-neg-fill')} strokeWidth="1" strokeDasharray="2 2" />
      <path d="M1 11c2-5 4-6 6-3s3 4 5 0 3-4 5-3" fill="none" stroke={v('ink-1')} strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}
function IconoFuerza() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18">
      <rect x="2" y="11" width="2.5" height="5" fill={v('rendi-neg-fill')} />
      <rect x="6" y="9" width="2.5" height="7" fill={v('rendi-neg-fill')} fillOpacity="0.55" />
      <rect x="10" y="8" width="2.5" height="8" fill={v('rendi-pos-fill')} fillOpacity="0.55" />
      <rect x="14" y="5" width="2.5" height="11" fill={v('rendi-pos-fill')} />
      <path d="M1 8c3 0 5-5 8-5s5 2 8 0" fill="none" stroke={v('ink-1')} strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}
function IconoTendencia() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18">
      <line x1="3" y1="15" x2="15" y2="3" stroke={COLOR.dibujo} strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="3" cy="15" r="2" fill={COLOR.dibujo} /><circle cx="15" cy="3" r="2" fill={COLOR.dibujo} />
    </svg>
  )
}
// Las herramientas del botón «Líneas y pincel».
const LINEAS = [
  { id: 'tendencia', nombre: 'Línea de tendencia', icono: <IconoTendencia />, estado: 'Tocá dos puntos del gráfico',
    detalle: 'De un punto a otro, para marcar una tendencia.' },
  { id: 'horizontal', nombre: 'Línea horizontal', icono: <IconoHorizontal />, estado: 'Tocá la altura del precio',
    detalle: 'Un precio que querés seguir de cerca (un soporte o una resistencia).' },
  { id: 'canal', nombre: 'Canal paralelo', icono: <IconoCanal />, estado: 'Tocá tres puntos del gráfico',
    detalle: 'Dos líneas paralelas: el piso y el techo de un precio que va de costado o en tendencia.' },
  { id: 'pincel', nombre: 'Pincel', icono: <Brush size={17} color={COLOR.dibujo} />, estado: 'Dibujá con el mouse apretado',
    detalle: 'Para marcar a mano alzada, como con una birome.' },
]

// El color de tu dibujo elegido (Nico, 29/10): siete, del tema. El elegido queda
// guardado en el dibujo y pasa a ser el de los nuevos.
function ColoresDelDibujo({ actual, onElegir }) {
  return (
    <span role="group" aria-label="Color del dibujo" className="inline-flex items-center gap-1">
      {COLORES_DIBUJO.map(c => (
        <button key={c.id} type="button" data-color={c.id} aria-pressed={actual === c.id} title={c.nombre}
          onClick={() => onElegir(c.id)}
          className={`inline-flex items-center justify-center w-8 h-8 sm:w-6 sm:h-6 rounded-full border-2 ${actual === c.id ? 'border-ink-0' : 'border-transparent hover:border-line-2'}`}>
          <span aria-hidden="true" className="block w-4 h-4 rounded-full" style={{ background: `rgb(var(--${c.token}))` }} />
          <span className="sr-only">{c.nombre}</span>
        </button>
      ))}
    </span>
  )
}

// Dos paralelas con la franja de entre medio, como se ve el canal.
function IconoCanal() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18">
      <path d="M2 11 L16 4 L16 9 L2 16 Z" fill={COLOR.dibujo} fillOpacity="0.15" />
      <line x1="2" y1="11" x2="16" y2="4" stroke={COLOR.dibujo} strokeWidth="1.6" strokeLinecap="round" />
      <line x1="2" y1="16" x2="16" y2="9" stroke={COLOR.dibujo} strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}
function IconoHorizontal() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18">
      <line x1="1" y1="9" x2="17" y2="9" stroke={COLOR.dibujo} strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="9" cy="9" r="2" fill={COLOR.dibujo} />
    </svg>
  )
}
// El cartel con los datos del día (precio, apertura, máximo, mínimo…).
function IconoGlobo() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18">
      <rect x="2" y="3" width="14" height="10" rx="2" fill="none" stroke={v('ink-1')} strokeWidth="1.5" />
      <line x1="5" y1="7" x2="13" y2="7" stroke={v('ink-1')} strokeWidth="1.3" strokeLinecap="round" />
      <line x1="5" y1="10" x2="10" y2="10" stroke={v('ink-1')} strokeWidth="1.3" strokeLinecap="round" />
      <path d="M7 13 9 15.5 11 13" fill="none" stroke={v('ink-1')} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  )
}
function IconoPuntos() {
  return (
    <span className="inline-flex gap-0.5">
      <span className="w-2 h-2 rounded-full bg-rendi-pos-fill" />
      <span className="w-2 h-2 rounded-full bg-rendi-neg-fill" />
    </span>
  )
}

// La «B» de un balance o la «D» de un dividendo: un círculo con la letra.
// `mixto`: un balance y un dividendo en la misma marca (mitad y mitad).
function Letra({ tipo, grande: g = false }) {
  const fondo = tipo === 'mixto' ? `linear-gradient(90deg, ${COLOR.balance} 50%, ${COLOR.dividendo} 50%)`
    : tipo === 'balance' ? COLOR.balance : COLOR.dividendo
  return (
    <span className={`inline-flex items-center justify-center rounded-full font-bold leading-none ${g ? 'w-[18px] h-[18px] text-[10px]' : 'w-3.5 h-3.5 text-[9px]'}`}
      style={{ background: fondo, color: v('bg-0') }}>
      {tipo === 'balance' ? 'B' : tipo === 'dividendo' ? 'D' : ''}
    </span>
  )
}

// `pie`: el «Avisame» de la señal de esa tarjeta (AvisameTecnico), arriba a la
// derecha, chico, para no competir con la lectura. `dibujo`: el dibujito de la
// tarjeta en la ficha (TarjetasPorTema), debajo del veredicto.
function Tarjeta({ t, pie, dibujo = null }) {
  const tono = t.tono === 'pos' ? 'text-rendi-pos' : t.tono === 'neg' ? 'text-rendi-neg' : 'text-ink-0'
  return (
    <div className="rounded-lg border border-line/60 bg-bg-2/40 px-3.5 py-3">
      <div className="flex items-start justify-between gap-2">
        <div className="text-[12px] text-ink-2 font-medium">{t.titulo}</div>
        {pie && <div className="-mt-1.5 flex-shrink-0">{pie}</div>}
      </div>
      <div className={`text-[15px] font-semibold mt-0.5 tabular ${tono}`}>{t.veredicto}</div>
      {dibujo}
      {t.rsi != null && <BarraRsi rsi={t.rsi} />}
      {t.adx != null && <BarraAdx adx={t.adx} />}
      <div className="text-[12.5px] text-ink-1 leading-relaxed mt-1.5">{t.texto}</div>
      {t.cruce && (
        <div className="text-[12.5px] text-ink-0 leading-relaxed mt-2 rounded border border-rendi-accent/30 bg-rendi-accent/10 px-2.5 py-1.5">
          {t.cruce}
        </div>
      )}
    </div>
  )
}

// La regla del RSI dibujada: 0 a 100, con 30 y 70 marcados y dónde está hoy.
function BarraRsi({ rsi }) {
  const pos = Math.min(100, Math.max(0, rsi))
  return (
    <div className="mt-2.5" aria-hidden="true">
      <div className="relative h-2 rounded-full overflow-hidden bg-bg-3">
        <div className="absolute inset-y-0 left-0 bg-rendi-neg-fill/35" style={{ width: `${RSI_CASTIGADO}%` }} />
        <div className="absolute inset-y-0 right-0 bg-rendi-pos-fill/35" style={{ width: `${100 - RSI_ESTIRADO}%` }} />
      </div>
      <div className="relative h-0">
        <div className="absolute -top-3 w-1 h-4 rounded-full bg-ink-0 shadow-sm" style={{ left: `calc(${pos}% - 2px)` }} />
      </div>
      <div className="relative h-4 mt-1 text-[11px] text-ink-2 tabular">
        <span className="absolute left-0">0</span>
        <span className="absolute -translate-x-1/2" style={{ left: `${RSI_CASTIGADO}%` }}>{RSI_CASTIGADO}</span>
        <span className="absolute -translate-x-1/2" style={{ left: '50%' }}>50</span>
        <span className="absolute -translate-x-1/2" style={{ left: `${RSI_ESTIRADO}%` }}>{RSI_ESTIRADO}</span>
        <span className="absolute right-0">100</span>
      </div>
      <div className="flex justify-between text-[11px] text-ink-2 mt-0.5">
        <span>← pierde impulso</span><span>gana impulso →</span>
      </div>
    </div>
  )
}

// La regla del ADX dibujada: 0 a 50, con la línea de 23 y dónde está hoy.
function BarraAdx({ adx }) {
  const pos = (Math.min(ADX_TOPE, Math.max(0, adx)) / ADX_TOPE) * 100
  const clave = (ADX_CLAVE / ADX_TOPE) * 100
  return (
    <div className="mt-2.5" aria-hidden="true">
      <div className="relative h-2 rounded-full overflow-hidden bg-bg-3">
        <div className="absolute inset-y-0 right-0 bg-rendi-accent/30" style={{ width: `${100 - clave}%` }} />
      </div>
      <div className="relative h-0">
        <div className="absolute -top-3 w-1 h-4 rounded-full bg-ink-0 shadow-sm" style={{ left: `calc(${pos}% - 2px)` }} />
      </div>
      <div className="relative h-4 mt-1 text-[11px] text-ink-2 tabular">
        <span className="absolute left-0">0</span>
        <span className="absolute -translate-x-1/2" style={{ left: `${clave}%` }}>{ADX_CLAVE}</span>
        <span className="absolute right-0">{ADX_TOPE}+</span>
      </div>
      <div className="flex justify-between text-[11px] text-ink-2 mt-0.5">
        <span>← sin tendencia</span><span>con fuerza →</span>
      </div>
    </div>
  )
}

// El alto del gráfico, uno solo: lo usan el gráfico y lo que ocupa su lugar
// mientras llegan sus velas o si no llegaron (cargando, 1H/4H sin velas). Con
// dos copias, el gris quedó en 22rem y en pantalla completa el gráfico se
// achicaba al cambiar de intervalo (Nico, 31/10).
const altoDelGrafico = (grande) => (grande ? 'h-[68vh] min-h-72 sm:h-[74vh]' : 'h-[42vh] min-h-56 sm:h-[58vh] sm:min-h-64')

function Grafico({ leyenda = null, grande = false, puntos, huecos = 0, moneda, promedio, marcas: lista, ver, tipo = 'linea', cada = null, fibonacci = null, elliott = null, onZoom, onMover, onFechasAuto, fechasAMano = false, reinicioPrecio, eventos = [], medicion = null, onToque = null, dibujos = [], elegido = null, onElegir = null, trazo = null, onTerminar = null, onMoverDibujo = null, conAviso = [], onPincel = null, colorNuevo = null, onAncho = null, pie = null, lugaresMinimos = RUEDAS_MINIMAS + margenDerecho(RUEDAS_MINIMAS), escala: escalaRef = null, tesis = [] }) {
  const conVelas = tipo === 'velas'
  // Los lugares del ancho: los días más el aire vacío de la derecha.
  const lugares = puntos.length + huecos
  const ref = useRef(null)
  const arrastre = useRef(null)
  // Un toque del dedo (para medir): dónde empezó y si se movió. El navegador
  // después del dedo manda también un click de mouse: se ignora un rato.
  const dedo = useRef(null)
  const ultimoDedo = useRef(0)
  // El balance o dividendo que se está mirando (su globo): la clave del grupo.
  const [eventoSel, setEventoSel] = useState(null)
  const conMouse = useRef(false)
  // El ancho del gráfico en pantalla: con él se sabe qué marcas se pisarían y,
  // en la ficha (`onAncho`), cuánto se ve al abrir (diasRecientes).
  const [ancho, setAncho] = useState(1000)
  const [alto, setAlto] = useState(300)
  const anchoRef = useRef(onAncho)
  anchoRef.current = onAncho
  // Antes de pintar: si no, el celular mostraría un instante la historia
  // entera antes de pasar a lo reciente.
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const medir = (w) => { setAncho(w); anchoRef.current?.(Math.round(w)) }
    // Se mide ya (con la página en segundo plano el aviso de abajo no llega
    // hasta que vuelve a verse) y después se sigue cada cambio de tamaño.
    const caja = el.getBoundingClientRect?.()
    if (caja?.width > 0) medir(caja.width)
    if (caja?.height > 0) setAlto(caja.height)
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([e]) => {
      if (e?.contentRect?.width) medir(e.contentRect.width)
      if (e?.contentRect?.height) setAlto(e.contentRect.height)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  // Los ejes se arrastran como en TradingView (utils/ejesGrafico.js): la
  // columna de precios estira el gráfico en vertical y deja el precio "a mano"
  // (`precioMano` = { lo, hi, comp } fijo, la pantalla y la imagen de «Compartir»
  // (ejesGrafico.empezarAMano); null = automático), y la fila de fechas
  // acerca o aleja. Con el precio a mano, arrastrar el gráfico también lo mueve
  // para arriba y para abajo. Doble click o «Automático»: vuelve a automático;
  // otro rango, moneda o tipo de gráfico (`reinicioPrecio`) también.
  const [precioMano, setPrecioMano] = useState(null)
  useEffect(() => { setPrecioMano(null) }, [reinicioPrecio])
  const ejeY = useRef(null)
  const ejeX = useRef(null)
  // La rueda tiene que frenar el scroll de la página mientras está sobre el
  // gráfico: eso sólo se puede con un escucha "no pasivo" (el onWheel de React
  // es pasivo y no puede frenarlo).
  const zoomRef = useRef(onZoom)
  zoomRef.current = onZoom
  useEffect(() => {
    const el = ref.current
    if (!el) return
    // La ruedita hace lo mismo que arrastrar la fila de fechas: acerca o aleja
    // el tiempo con el ÚLTIMO día quieto, no alrededor del mouse (Nico, 23/10:
    // «que amplíe como el eje X»). Hacia arriba acerca; hacia abajo aleja.
    // Proporcional a cuánto se giró: un paso de ruedita de mouse (~100) mueve
    // ~8 % y el trackpad, que manda muchos pasitos, va de a poco (antes cada
    // evento era un 15 % fijo y con el trackpad volaba). Lo girado se junta
    // hasta que alcanza para mover una rueda.
    let girado = 0
    const rueda = (e) => {
      if (!zoomRef.current) return
      e.preventDefault()
      const paso = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaMode === 2 ? e.deltaY * 400 : e.deltaY
      girado = Math.max(-600, Math.min(600, girado + paso))
      if (zoomRef.current(Math.exp(girado * 0.0008), 1)) girado = 0
    }
    // Con dos dedos (pellizcar para acercar) o arrastrando un dibujo, la
    // página no se tiene que mover: lo mismo, un escucha no pasivo.
    const quieta = (e) => { if (e.cancelable && (e.touches.length >= 2 || dedo.current?.agarre || dedo.current?.pincel)) e.preventDefault() }
    el.addEventListener('wheel', rueda, { passive: false })
    el.addEventListener('touchmove', quieta, { passive: false })
    return () => { el.removeEventListener('wheel', rueda); el.removeEventListener('touchmove', quieta) }
  }, [])
  const gid = useId().replace(/:/g, '')
  const [hover, setHover] = useState(null)
  // El globo se mide para que nunca se salga de la pantalla: en un celular el
  // gráfico mide ~250 px y el globo ~200; con la regla fija «a la derecha hasta
  // el 62 %» la página se ensanchaba o el precio quedaba cortado (auditoría 22/10).
  const globoRef = useRef(null)
  const [anchoGlobo, setAnchoGlobo] = useState(0)
  useLayoutEffect(() => {
    const w = globoRef.current?.offsetWidth
    if (w && Math.abs(w - anchoGlobo) > 1) setAnchoGlobo(w)
  })
  // Con todas las capas prendidas, los rótulos de una pueden caer sobre los de
  // otra: después de cada dibujo se miden y se esconde el de menos prioridad
  // (utils/rotulos.js). La raya queda; sólo se va el texto.
  useLayoutEffect(() => { taparRotulos(ref.current) })

  const { escalaY, path, area, min, max, velas, volumen, promFuera, compartible } = useMemo(() => {
    const valores = []
    let prevC = null
    for (const p of puntos) {
      valores.push(p.c)
      if (conVelas) {
        const vela = velaCompleta(p, prevC)
        valores.push(vela.h, vela.l)
        prevC = p.c
      }
      if (ver.s50 && p.s50 != null) valores.push(p.s50)
      if (ver.s200 && p.s200 != null) valores.push(p.s200)
    }
    valores.push(...preciosDeLaCapa(fibonacci, puntos), ...preciosDelConteo(elliott, puntos))
    let lo = Math.min(...valores), hi = Math.max(...valores)
    // Las bandas estiran la escala sólo cerca de lo que se ve, y nunca abajo de
    // 0: después de un salto brusco (un pump, un cambio de ratio que Yahoo no
    // corrige) la de abajo da un precio negativo y aplastaba todo el gráfico
    // contra un eje con precios bajo cero (auditoría 28/10). Lo que queda
    // afuera se corta en el borde, como en TradingView.
    if (ver.bb) {
      const rangoPrecio = hi - lo || hi * 0.1 || 1
      const piso = Math.max(0, lo - rangoPrecio * 0.35), techo = hi + rangoPrecio * 0.35
      let bLo = lo, bHi = hi
      for (const p of puntos) {
        if (p.bb_arriba == null || p.bb_abajo == null) continue
        if (p.bb_abajo >= piso) bLo = Math.min(bLo, p.bb_abajo)
        if (p.bb_arriba <= techo) bHi = Math.max(bHi, p.bb_arriba)
      }
      lo = bLo; hi = bHi
    }
    // La escala sin tu precio: la de la imagen de «Compartir», que no lleva
    // nada de tu cartera (si se estirara hasta tu precio, la franja vacía
    // diría más o menos a cuánto compraste).
    const sinTuPrecio = [lo, hi]
    // Tu precio entra en la escala sólo si está cerca de lo que se ve. Si está
    // muy lejos (ganás 70 %, o perdés 60 %), estirar la escala aplastaría el
    // gráfico contra un borde: va una etiqueta en ese borde con una flecha.
    let fuera = null
    if (promedio != null) {
      const rango = hi - lo || hi * 0.1 || 1
      if (promedio < lo - rango * 0.35) fuera = 'abajo'
      else if (promedio > hi + rango * 0.35) fuera = 'arriba'
      else { lo = Math.min(lo, promedio); hi = Math.max(hi, promedio) }
    }
    // El volumen va en la franja de abajo (el 20 % del alto): se le deja ese
    // lugar para que las barras no tapen las velas.
    const maxVol = ver.vol ? Math.max(0, ...puntos.map(p => p.v || 0)) : 0
    const conAire = ([a, b]) => {
      const margen = (b - a) * 0.08 || b * 0.02 || 1
      a -= margen; b += margen
      if (maxVol > 0) a -= (b - a) * 0.25
      return [a, b]
    }
    ;[lo, hi] = conAire([lo, hi])
    let compartible = conAire(sinTuPrecio)
    if (precioMano) {
      lo = precioMano.lo; hi = precioMano.hi
      // La imagen, con SU rango a mano: arrancó de `compartible`, no de la
      // pantalla estirada hasta tu precio (auditoría D4).
      compartible = [precioMano.comp.lo, precioMano.comp.hi]
      fuera = promedio == null ? null : promedio < lo ? 'abajo' : promedio > hi ? 'arriba' : null
    }
    const y = (val) => H - ((val - lo) / (hi - lo)) * H
    const x = (i) => (lugares > 1 ? (i / (lugares - 1)) * W : W / 2)
    const linea = (k, hasta = puntos.length) => {
      let d = '', abierto = false
      puntos.forEach((p, i) => {
        if (i >= hasta || p[k] == null) { abierto = false; return }
        d += `${abierto ? 'L' : 'M'}${x(i).toFixed(1)},${y(p[k]).toFixed(1)}`
        abierto = true
      })
      return d
    }
    // La vela de hoy (sumarVelaDeHoy) en la línea: el último tramo va
    // punteado, porque ese precio todavía se mueve o no se guardó.
    const n = puntos.length
    const conHoy = n > 1 && puntos[n - 1].hoy && puntos[n - 2].c != null
    const c = linea('c', conHoy ? n - 1 : n)
    const tramoHoy = conHoy
      ? `M${x(n - 2).toFixed(1)},${y(puntos[n - 2].c).toFixed(1)}L${x(n - 1).toFixed(1)},${y(puntos[n - 1].c).toFixed(1)}` : ''
    // El relleno entre las bandas: cada tramo seguido va por la de arriba hacia
    // adelante y vuelve por la de abajo.
    let bandas = ''
    if (ver.bb) {
      let tramo = []
      const cerrar = () => {
        if (tramo.length > 1) {
          bandas += tramo.map((i, k) => `${k ? 'L' : 'M'}${x(i).toFixed(1)},${y(puntos[i].bb_arriba).toFixed(1)}`).join('')
            + [...tramo].reverse().map(i => `L${x(i).toFixed(1)},${y(puntos[i].bb_abajo).toFixed(1)}`).join('') + 'Z'
        }
        tramo = []
      }
      puntos.forEach((p, i) => { if (p.bb_arriba != null && p.bb_abajo != null) tramo.push(i); else cerrar() })
      cerrar()
    }
    // Las velas: el ancho de cada una es el 65 % de su lugar, la mecha va del
    // mínimo al máximo y el cuerpo de la apertura al cierre.
    const ancho = Math.max((W / Math.max(lugares, 1)) * 0.65, 1)
    let pc = null
    const velas = conVelas ? puntos.map((p, i) => {
      const vela = velaCompleta(p, pc)
      pc = p.c
      const arriba = Math.min(y(vela.o), y(vela.c))
      return {
        k: i, x: x(i), sube: vela.c >= vela.o, yh: y(vela.h), yl: y(vela.l),
        cuerpoY: arriba, cuerpoH: Math.max(Math.abs(y(vela.o) - y(vela.c)), 0.8), ancho, enCurso: !!p.enCurso,
      }
    }) : []
    // Las barras del volumen, abajo de todo, del color de la vela (o de si cerró
    // arriba o abajo del día anterior, en el gráfico de línea).
    const anchoVol = Math.max((W / Math.max(lugares, 1)) * 0.65, 1)
    const volumen = maxVol > 0 ? puntos.map((p, i) => {
      if (!(p.v > 0)) return null
      const antes = i > 0 ? puntos[i - 1].c : null
      const vela = velaCompleta(p, antes)
      const sube = conVelas ? vela.c >= vela.o : (antes == null || p.c >= antes)
      const alto = (p.v / maxVol) * H * VOL_ALTO
      return { k: i, x: x(i), y: H - alto, alto, ancho: anchoVol, sube, enCurso: !!p.enCurso }
    }).filter(Boolean) : []
    return {
      escalaY: y, min: lo, max: hi, velas, volumen, promFuera: fuera, compartible,
      path: { c, hoy: tramoHoy, s50: linea('s50'), s200: linea('s200'), bbArriba: linea('bb_arriba'), bbAbajo: linea('bb_abajo'), bandas },
      area: c ? `${c}L${x(conHoy ? n - 2 : n - 1).toFixed(1)},${H}L0,${H}Z` : '',
    }
  }, [puntos, lugares, promedio, ver.s50, ver.s200, ver.bb, ver.vol, conVelas, fibonacci, elliott, precioMano])
  if (escalaRef) escalaRef.current = { min: compartible[0], max: compartible[1] }

  const rsiPath = useMemo(() => {
    let d = '', abierto = false
    puntos.forEach((p, i) => {
      if (p.rsi == null) { abierto = false; return }
      const xx = lugares > 1 ? (i / (lugares - 1)) * W : W / 2
      d += `${abierto ? 'L' : 'M'}${xx.toFixed(1)},${(H_RSI - (p.rsi / 100) * H_RSI).toFixed(1)}`
      abierto = true
    })
    return d
  }, [puntos, lugares])

  // La fuerza de la tendencia, en dos franjas: el ADX como línea (0 abajo, 50
  // arriba) con la de 23, y debajo el Squeeze como barras desde el medio
  // (arriba, verde; abajo, rojo). Juntos en una franja, la línea de 23 caía
  // casi sobre el cero del Squeeze y no se distinguían. El Squeeze está en
  // unidades de precio: sólo importan su lado y su tamaño.
  const fuerza = useMemo(() => {
    const conAdx = puntos.filter(p => p.adx != null)
    const conSq = puntos.filter(p => p.squeeze != null)
    if (!conAdx.length && !conSq.length) return null
    const tope = Math.max(ADX_TOPE, ...conAdx.map(p => p.adx))
    const yAdx = (a) => H_ADX - (a / tope) * H_ADX
    const xx = (i) => (lugares > 1 ? (i / (lugares - 1)) * W : W / 2)
    let d = '', abierto = false
    puntos.forEach((p, i) => {
      if (p.adx == null) { abierto = false; return }
      d += `${abierto ? 'L' : 'M'}${xx(i).toFixed(1)},${yAdx(p.adx).toFixed(1)}`
      abierto = true
    })
    const maxSq = Math.max(...conSq.map(p => Math.abs(p.squeeze)), 0) || 1
    const ancho = Math.max((W / Math.max(lugares, 1)) * 0.7, 1)
    const medio = H_SQUEEZE / 2
    const barras = puntos.map((p, i) => {
      // En 0 no empuja para ningún lado: sin barra (si no, rayitas rojas).
      if (!p.squeeze || !SQUEEZE[p.squeeze_color]) return null
      const alto = Math.max((Math.abs(p.squeeze) / maxSq) * (medio * 0.92), 0.5)
      return { k: i, x: xx(i) - ancho / 2, ancho, y: p.squeeze > 0 ? medio - alto : medio, alto, color: SQUEEZE[p.squeeze_color] }
    }).filter(Boolean)
    return { d, barras, yClave: yAdx(ADX_CLAVE), pctAdx: (a) => (yAdx(a) / H_ADX) * 100 }
  }, [puntos, lugares])

  const pctX = (i) => (lugares > 1 ? (i / (lugares - 1)) * 100 : 50)
  const pctY = (val) => (escalaY(val) / H) * 100
  const desde = puntos[0]?.d
  // En la primera vela de ese día (en diarias y semanales, la del día; en
  // 1H/4H, la primera hora de esa rueda).
  const visibles = lista
    .filter(m => m.fecha >= desde)
    .map(m => ({ ...m, i: primeraVelaDelDia(puntos, m.fecha) }))
    .filter(m => m.i != null && pctY(puntos[m.i].c) >= 0 && pctY(puntos[m.i].c) <= 100)

  // El mouse o el dedo: el punto más cercano en el tiempo.
  function indiceEn(clientX) {
    const r = ref.current?.getBoundingClientRect()
    if (!r || !puntos.length) return null
    const i = Math.round(((clientX - r.left) / r.width) * (lugares - 1))
    // En el aire de la derecha (el futuro) no hay día: ni globo ni medición.
    return i > puntos.length - 1 ? null : Math.max(0, i)
  }
  function mover(clientX) {
    setHover(indiceEn(clientX))
  }
  // Para medir, cualquier punto: el lugar (también en el aire de la derecha,
  // hacia adelante) y el precio a esa altura, no el cierre (Nico, 24/10).
  function lugarEn(clientX) {
    const r = ref.current?.getBoundingClientRect()
    if (!r || !r.width) return null
    return Math.min(lugares - 1, Math.max(0, Math.round(((clientX - r.left) / r.width) * (lugares - 1))))
  }
  function precioEn(clientY) {
    const r = ref.current?.getBoundingClientRect()
    if (!r || !r.height) return null
    return min + (1 - Math.min(1, Math.max(0, (clientY - r.top) / r.height))) * (max - min)
  }
  function tocarEn(clientX, clientY) {
    const k = lugarEn(clientX), precio = precioEn(clientY)
    if (k == null || !(precio > 0)) return false
    onToque(k, precio)
    return true
  }
  // Mover y corregir un dibujo ya hecho (Nico, 28/10), como TradingView:
  // agarrado de una punta la corre a ella sola; de cualquier otro lado, lo
  // mueve entero. Mientras se arrastra se ve corrido acá (`agarrado`: { id,
  // que, dk, dp }: cuántos lugares y cuánto precio); al soltar, la ficha lo
  // guarda (onMoverDibujo). Con el mouse, cualquier dibujo tuyo; con el dedo,
  // sólo el elegido (si no, cada deslizar para mover la página agarraría una línea).
  const [agarrado, setAgarrado] = useState(null)
  const vistos = agarrado ? dibujos.map(d => (d.id !== agarrado.id ? d
    : dibujoCorrido(d, agarrado.que, (p) => ({ ...p, k: p.k + agarrado.dk, precio: precioCorrido(p.precio, agarrado.dp) }),
      (x) => precioCorrido(x, agarrado.dp), agarrado.dp))) : dibujos
  // Tus dibujos en pantalla (CapaDibujos.jsx), como trazos: para saber a cuál
  // se le tocó encima y para el precio de las horizontales en la columna.
  const trazos = trazosDeDibujos(vistos, pctX, pctY, conAviso)
  // Lo que se puede elegir tocándolo: tus dibujos y también el Fibonacci y el
  // conteo AUTOMÁTICOS (elegirlos y borrarlos los apaga).
  const elegibles = [...trazos, ...trazosDelFibonacci(fibonacci, puntos, pctX, pctY), ...trazosDelConteo(elliott, puntos, pctX, pctY)]
  // Las banderitas de tus notas y de tu tesis (NotasGrafico.jsx), ya juntadas
  // las que se pisarían. La nota que se está escribiendo, con la suya.
  const notaNueva = trazo?.tipo === 'nota' ? trazo.puntos[0] : null
  const banderitas = banderitasEnVista({
    notas: vistos.filter(d => d.tipo === 'nota'), tesis, pctX, pctY, ancho, alto, elegido,
    provisoria: notaNueva && { ...notaNueva, color: colorDe({ color: colorNuevo }) },
  })
  // Un click (o un toque) sin herramienta, cerca de un dibujo: lo elige (para
  // borrarlo); lejos de todos, suelta el que estaba elegido. Una banderita
  // gana: está encima de todo.
  function dibujoBajo(clientX, clientY, radio) {
    const r = ref.current?.getBoundingClientRect()
    if (!r || !r.width) return null
    const bandera = banderitaEn(banderitas, clientX - r.left, clientY - r.top, radio / 2, elegido)
    if (bandera) return bandera
    if (!elegibles.length) return null
    const px = (t) => ({ id: t.id, ax: (t.x1 / 100) * r.width, ay: (t.y1 / 100) * r.height, bx: (t.x2 / 100) * r.width, by: (t.y2 / 100) * r.height })
    return dibujoTocado(elegibles.map(px), clientX - r.left, clientY - r.top, radio)
  }
  // El pincel (Nico, 29/10): con la herramienta prendida, apretar y arrastrar
  // dibuja. El trazo se ve mientras se hace (`pincel`: [{ k, precio }], k con
  // decimales para que no quede en escalones) y al soltar se guarda
  // (onPincel). Un punto cada 3 px como mínimo y, si son más de los que se
  // guardan, se toman parejos a lo largo del trazo.
  const [pincel, setPincel] = useState(null)
  const trazoPincel = useRef(null)
  function lugarExacto(clientX) {
    const r = ref.current.getBoundingClientRect()
    return Math.min(lugares - 1, Math.max(0, ((clientX - r.left) / r.width) * (lugares - 1)))
  }
  function empezarPincel(x, y) {
    trazoPincel.current = { x, y, puntos: [{ k: lugarExacto(x), precio: precioEn(y) }] }
    setPincel(trazoPincel.current.puntos)
  }
  function seguirPincel(x, y) {
    const t = trazoPincel.current
    if (!t || Math.hypot(x - t.x, y - t.y) < 3) return
    t.x = x; t.y = y
    t.puntos = [...t.puntos, { k: lugarExacto(x), precio: precioEn(y) }]
    setPincel(t.puntos)
  }
  function terminarPincel() {
    const t = trazoPincel.current
    trazoPincel.current = null
    setPincel(null)
    if (!t || t.puntos.length < 2) return
    let ps = t.puntos
    if (ps.length > PINCEL_MAXIMO) ps = Array.from({ length: PINCEL_MAXIMO }, (_, n) => ps[Math.round((n * (ps.length - 1)) / (PINCEL_MAXIMO - 1))])
    onPincel?.(ps)
  }
  // Qué se agarra apretando en (clientX, clientY): uno de TUS dibujos (el
  // automático no se mueve: es una cuenta) y de dónde. `soloId`: con el dedo, el elegido.
  function agarreEn(clientX, clientY, radio, soloId) {
    if (!onMoverDibujo || onToque || onPincel) return null
    const id = dibujoBajo(clientX, clientY, radio)
    const d = id && (!soloId || id === soloId) ? dibujos.find(x => x.id === id) : null
    if (!d) return null
    const r = ref.current.getBoundingClientRect()
    let que = 'todo', cerca = radio * 1.5
    for (const [nombre, p] of puntasDe(d)) {
      const dist = Math.hypot((pctX(p.k) / 100) * r.width - (clientX - r.left), (pctY(p.precio) / 100) * r.height - (clientY - r.top))
      if (dist <= cerca) { que = nombre; cerca = dist }
    }
    return { id, que }
  }
  // Lo corrido desde donde se apretó, en lugares y en precio.
  function corrimiento(g, x0, y0, x, y) {
    const r = ref.current.getBoundingClientRect()
    return { ...g, dk: Math.round(((x - x0) / r.width) * (lugares - 1)), dp: ((y0 - y) / r.height) * (max - min) }
  }
  function soltar(g) {
    setAgarrado(null)
    if (g && (g.dk || g.dp)) onMoverDibujo(g.id, g.que, g.dk, g.dp)
    if (g) onElegir?.(g.id)
  }
  function elegirEn(clientX, clientY, radio) {
    if (!onElegir) return false
    const id = dibujoBajo(clientX, clientY, radio)
    if (id || elegido) onElegir(id)
    return !!id
  }
  // El dibujo que está bajo el mouse (sin ninguna herramienta prendida): la
  // manito y la línea un poco más gruesa, como TradingView, para saber que un
  // click lo va a elegir (Nico, 28/10). Con el mismo margen que el click.
  const [sobreDibujo, setSobreDibujo] = useState(null)
  useEffect(() => { if (onToque) setSobreDibujo(null) }, [onToque])
  // Dónde está el mouse, mientras se mide: la cruz con su precio y, con el
  // primer punto puesto, lo que daría la medición hasta ahí.
  const [cursor, setCursor] = useState(null)

  // Balances y dividendos dentro de lo que se ve, con su lugar (Galicia paga
  // todos los meses: en el celular eran doce «D» pisadas).
  // En semanales, el último día de la última semana (`hasta`), no su lunes:
  // un balance del jueves de esta semana también va.
  const hasta = puntos[puntos.length - 1]?.hasta || puntos[puntos.length - 1]?.d
  // Cada dividendo con el anterior (para comparar) y qué parte del precio de
  // ese día fue, si el precio está en su misma moneda (Nico, 29/10).
  const divs = eventos.filter(e => e.tipo === 'dividendo').sort((a, b) => (a.fecha < b.fecha ? -1 : 1))
  const evVisibles = eventos
    .filter(e => e.fecha >= (puntos[0]?.d || '') && e.fecha <= (hasta || ''))
    .map(e => ({ ...e, i: primeraVelaDelDia(puntos, e.fecha) }))
    .filter(e => e.i != null)
    .map(e => {
      if (e.tipo !== 'dividendo') return e
      const k = divs.findIndex(x => x.fecha === e.fecha)
      // El cierre de ese día: en 1H/4H, el de su última vela.
      const c = puntos[indiceDeFecha(puntos, e.fecha)]?.c
      return { ...e, anterior: k > 0 ? divs[k - 1].monto : null,
        rendimiento: e.monto > 0 && c > 0 && e.moneda === moneda ? (e.monto / c) * 100 : null }
    })
  // Una sola fila de marcas sobre las fechas (antes, una por tipo): las que en
  // la pantalla quedarían a menos de MARCA_PX se juntan en UNA, aunque sean un
  // balance y un dividendo; su globo las lista. Si los dividendos se pisarían
  // entre ellos, se ven sólo los balances (dividendosAmontonados).
  const sinDividendos = dividendosAmontonados(evVisibles, pctX, ancho, ancho / Math.max(1, lugaresMinimos - 1))
  const grupos = []
  let actual = null
  for (const e of evVisibles.filter(e => !sinDividendos || e.tipo !== 'dividendo').sort((a, b) => a.i - b.i)) {
    const x = pctX(e.i)
    if (actual && ((x - actual.x0) / 100) * ancho < MARCA_PX) {
      actual.items.push(e)
      actual.x = (actual.x0 + x) / 2
      if (actual.tipo !== e.tipo) actual.tipo = 'mixto'
    } else {
      actual = { clave: `${e.tipo}|${e.fecha}`, tipo: e.tipo, x0: x, x, items: [e] }
      grupos.push(actual)
    }
  }
  const grupoSel = grupos.find(g => g.clave === eventoSel) || null

  // La medición, dibujada: cada punto tocado en su lugar (`k`, que manda la
  // ficha; fuera de lo que se ve, contra el borde) y a la altura de SU precio.
  // Con un solo punto puesto, el otro extremo va siguiendo al mouse.
  const enVista = (p) => p && { x: pctX(Math.min(Math.max(p.k, 0), lugares - 1)), fuera: p.k < 0 || p.k > lugares - 1, precio: p.precio }
  const previa = medicion?.hasta && cursor ? medicion.hasta(cursor.k, cursor.precio) : null
  const mA = enVista(medicion?.a)
  const mB = enVista(medicion?.b || (previa ? cursor : null))
  const mMed = medicion?.m || previa
  const yDe = (precio) => (precio != null ? Math.min(100, Math.max(0, pctY(precio))) : null)
  const precioA = mA?.precio
  const precioB = mB?.precio
  const ph = hover != null ? puntos[hover] : null
  const ultimo = puntos[puntos.length - 1]
  // Los ejes como TradingView (utils/ejesGrafico.js): precios redondos a lo
  // largo de la columna y fechas con el detalle que entra.
  const ticks = marcasDePrecio(min, max, alto)
  // Los precios del costado sin «,00» cuando son redondos («400», no
  // «400,00»); con decimales si el paso los necesita (una cripto de centavos).
  // El último precio y el del mouse siguen con todos sus decimales.
  const enteros = ticks.every(t => Number.isInteger(t))
  const rotuloDePrecio = (t) => (enteros ? t.toLocaleString('es-AR') : fmtPrecio(t, moneda).replace(/^US\$ /, ''))
  // El último precio, como TradingView: verde si el día cerró arriba del
  // anterior, rojo si abajo (gris si igual), con su raya punteada a lo ancho.
  const penultimo = puntos[puntos.length - 2]
  const colorDelDia = !ultimo || !penultimo || ultimo.c === penultimo.c ? COLOR.precio
    : ultimo.c > penultimo.c ? v('rendi-pos') : v('rendi-neg')
  const meses = (cada ? marcasDeHoras : marcasDeFechas)(puntos, (ancho * puntos.length) / Math.max(lugares, 1))
  // Los rótulos del eje se esconden si chocan con la etiqueta del último precio
  // o con la de tu precio (que pesan más).
  const promVisible = promedio != null && !promFuera
  const promCerca = promVisible && ultimo && Math.abs(pctY(promedio) - pctY(ultimo.c)) < 9
  const cerca = (val) => (ultimo && Math.abs(pctY(val) - pctY(ultimo.c)) < 7)
    || (promVisible && !promCerca && Math.abs(pctY(val) - pctY(promedio)) < 7)
  // RSI, ADX y Squeeze: los del último día guardado. Una vela viva no los trae
  // (sumarVelaDeHoy), y sin esto los carteles de la derecha desaparecían
  // durante toda la rueda (auditoría 30/10).
  const ultimoInd = ultimo?.vivo ? [...puntos].reverse().find(p => !p.vivo) : ultimo
  const rsiCerca = (nivel) => ultimoInd?.rsi != null && Math.abs(nivel - ultimoInd.rsi) < 12
  const verRsi = ver.rsi !== false
  const verAdx = !!fuerza && ver.fuerza !== false

  return (
    <div>
      <div className="relative">
        {/* Área del gráfico: deja libre la columna de la derecha para los precios. */}
        {/* Con la escala vertical a mano, lo que queda fuera se recorta (como en
            TradingView); en automático no hace falta y el punto del último
            precio puede asomar sobre el borde. */}
        {/* Siempre ampliado (Nico, 24/10). En el celular, un alto que deja ver
            la barra y el RSI sin comerse la pantalla; en compu, el de antes con «Agrandar». */}
        <div ref={ref} className={`relative mr-[72px] ${altoDelGrafico(grande)} select-none touch-pan-y ${agarrado ? 'cursor-grabbing' : sobreDibujo ? 'cursor-pointer' : 'cursor-crosshair'} ${precioMano ? 'overflow-hidden' : ''}`}
          onMouseDown={e => {
            if (e.button != null && e.button !== 0) return
            if (onPincel) { arrastre.current = { pincel: true }; empezarPincel(e.clientX, e.clientY); return }
            arrastre.current = { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, agarre: agarreEn(e.clientX, e.clientY, 8) }
          }}
          onMouseUp={e => {
            // Un click sin arrastrar, en el modo medir, marca ese día. Sólo el
            // botón izquierdo: el derecho termina un conteo (onContextMenu).
            const a = arrastre.current
            arrastre.current = null
            if (e.button != null && e.button !== 0) return
            if (a?.pincel) { terminarPincel(); return }
            if (a?.movido) { soltar(a.ultimo); return }
            if (!a || Date.now() - ultimoDedo.current < 800) return
            if (Math.abs(e.clientX - a.x0) >= 5 || Math.abs(e.clientY - a.y0) >= 5) return
            if (onToque) tocarEn(e.clientX, e.clientY)
            else elegirEn(e.clientX, e.clientY, 8)
          }}
          onMouseMove={e => {
            const a = arrastre.current
            if (a?.pincel) { seguirPincel(e.clientX, e.clientY); mover(e.clientX); return }
            if (a?.agarre) {
              // Arrastrando un dibujo tuyo: el gráfico queda quieto.
              if (!a.movido && Math.abs(e.clientX - a.x0) < 5 && Math.abs(e.clientY - a.y0) < 5) return
              a.movido = true
              a.ultimo = corrimiento(a.agarre, a.x0, a.y0, e.clientX, e.clientY)
              setAgarrado(a.ultimo)
              mover(e.clientX)
              return
            }
            if (a) {
              const r = ref.current.getBoundingClientRect()
              const frac = (e.clientX - a.x) / r.width
              if (onMover && Math.abs(frac) * puntos.length >= 1) { onMover(frac); a.x = e.clientX }
              // También para arriba y para abajo, hasta donde quieras aunque no
              // haya precios ahí, como TradingView (Nico, 29/10). Arrastrar en
              // vertical deja el precio «a mano» (vuelve con «Automático» o
              // doble click en los precios); en automático hace falta moverse
              // 12 px para arriba o abajo, así un arrastre de costado con el
              // pulso torcido no lo saca de automático.
              const fy = (e.clientY - a.y) / r.height
              if ((precioMano || a.vertical || Math.abs(e.clientY - a.y0) >= 12) && Math.abs(fy) >= 0.005) {
                a.vertical = true
                setPrecioMano(correrAMano(precioMano || empezarAMano([min, max], compartible), fy)); a.y = e.clientY
              }
            }
            mover(e.clientX)
            // La cruz del mouse, siempre (como TradingView): su precio en la
            // columna y su día en la fila de fechas.
            setCursor({ k: lugarEn(e.clientX), precio: precioEn(e.clientY) })
            if (!onToque && onElegir && !onPincel) setSobreDibujo(a ? null : dibujoBajo(e.clientX, e.clientY, 8))
          }}
          onMouseLeave={() => {
            // Sacar el mouse del gráfico arrastrando un dibujo es soltarlo ahí.
            if (arrastre.current?.pincel) terminarPincel()
            else if (arrastre.current?.movido) soltar(arrastre.current.ultimo)
            setHover(null); setCursor(null); setSobreDibujo(null); arrastre.current = null
          }}
          onDoubleClick={() => { onTerminar?.() }}
          onContextMenu={e => { if (onToque && onTerminar?.()) e.preventDefault(); else if (onToque) e.preventDefault() }}
          onTouchStart={e => {
            const t = e.touches[0]
            // Dos dedos: pellizcar acerca o aleja, como la ruedita (Nico, 28/10).
            if (e.touches.length >= 2) {
              // Un segundo dedo a mitad de un trazo: era para acercar, el trazo no va.
              setAgarrado(null); trazoPincel.current = null; setPincel(null)
              dedo.current = { pellizco: distanciaDedos(e.touches), quieto: false }
              return
            }
            if (onPincel) {
              dedo.current = { pincel: true, quieto: false }
              empezarPincel(t.clientX, t.clientY)
              return
            }
            dedo.current = { x0: t.clientX, y0: t.clientY, x: t.clientX, y: t.clientY, quieto: true, t0: Date.now(),
              xa: t.clientX, modo: null, agarre: elegido ? agarreEn(t.clientX, t.clientY, 16, elegido) : null }
            mover(t.clientX)
          }}
          onTouchMove={e => {
            const t = e.touches[0], d = dedo.current
            if (d?.pellizco && e.touches.length >= 2) {
              // Abrir los dedos acerca (menos días), cerrarlos aleja; con el
              // último día quieto, como la ruedita. Lo que no alcanza para
              // mover un día se junta para el próximo movimiento.
              const ahora = distanciaDedos(e.touches)
              if (ahora > 0 && onZoom?.(d.pellizco / ahora, 1)) d.pellizco = ahora
              return
            }
            if (d?.pincel) { seguirPincel(t.clientX, t.clientY); return }
            if (d?.agarre) {
              d.x = t.clientX
              d.y = t.clientY
              if (!d.movido && Math.abs(t.clientX - d.x0) <= 6 && Math.abs(t.clientY - d.y0) <= 6) return
              d.movido = true
              d.quieto = false
              d.ultimo = corrimiento(d.agarre, d.x0, d.y0, t.clientX, t.clientY)
              setAgarrado(d.ultimo)
              return
            }
            if (d) {
              d.x = t.clientX
              d.y = t.clientY
              const dx = t.clientX - d.x0, dy = t.clientY - d.y0
              if (Math.abs(dx) > 10 || Math.abs(dy) > 10) d.quieto = false
              // Con un dedo, como TradingView (Nico, 29/10: «deslizá para
              // moverte»): deslizar de costado lleva el gráfico para atrás o
              // para adelante en el tiempo; mantener apretado (MANTENER_MS) y
              // después deslizar pasea el globo con los datos de cada día; para
              // arriba o abajo se mueve la página (touch-pan-y). Se decide con
              // el primer movimiento y no cambia hasta levantar el dedo.
              if (!d.modo && !d.quieto) {
                d.modo = Date.now() - d.t0 >= MANTENER_MS ? 'mira' : Math.abs(dx) > Math.abs(dy) ? 'arrastre' : 'pagina'
              }
              if (d.modo === 'arrastre') {
                setHover(null)
                const r = ref.current.getBoundingClientRect()
                const frac = (t.clientX - d.xa) / r.width
                if (onMover && Math.abs(frac) * puntos.length >= 1) { onMover(frac); d.xa = t.clientX }
                return
              }
              if (d.modo === 'pagina') { setHover(null); return }
            }
            mover(t.clientX)
          }}
          onTouchEnd={e => {
            // Un toque quieto (sin deslizar) en el modo medir marca ese punto.
            const d = dedo.current
            dedo.current = null
            setHover(null)
            if (d?.pincel) {
              terminarPincel()
              ultimoDedo.current = Date.now()
              if (e.cancelable) e.preventDefault()
            } else if (d?.movido) {
              soltar(d.ultimo)
              ultimoDedo.current = Date.now()
              if (e.cancelable) e.preventDefault()
            } else if (d?.quieto && onToque && tocarEn(d.x, d.y)) {
              ultimoDedo.current = Date.now()
              if (e.cancelable) e.preventDefault()
            } else if (d?.quieto && !onToque && elegirEn(d.x, d.y, 16)) {
              // Con el dedo hace falta más margen para acertarle a una línea.
              ultimoDedo.current = Date.now()
              if (e.cancelable) e.preventDefault()
            }
          }}
          role="img" aria-label={`Precio con su promedio de 200 y de 50 días. ${ultimo?.enCurso ? 'Precio de hoy, en curso' : 'Último cierre'} ${fmtPrecio(ultimo?.c, moneda)}.`}>
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 w-full h-full" aria-hidden="true">
            <defs>
              <linearGradient id={`area-${gid}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" style={{ stopColor: COLOR.precio, stopOpacity: 0.12 }} />
                <stop offset="100%" style={{ stopColor: COLOR.precio, stopOpacity: 0 }} />
              </linearGradient>
            </defs>
            {/* La grilla: lisa y suave, sólo a la altura de los precios del
                costado (como TradingView; antes, punteada y más marcada). */}
            {ticks.map((t, k) => (
              <line key={k} x1="0" x2={W} y1={escalaY(t)} y2={escalaY(t)} stroke={v('chart-grid')} strokeWidth="1"
                strokeOpacity="0.55" vectorEffect="non-scaling-stroke" />
            ))}
            {!conVelas && <path d={area} fill={`url(#area-${gid})`} />}
            {volumen.map(b => (
              <rect key={`v${b.k}`} x={b.x - b.ancho / 2} width={b.ancho} y={b.y} height={b.alto}
                fill={b.sube ? v('rendi-pos-fill') : v('rendi-neg-fill')} fillOpacity={b.enCurso ? 0.1 : 0.2} />
            ))}
            {ver.bb && (
              <>
                {/* Más livianas (Nico, 29/10): eran lo que más pesaba en la vista. */}
                <path d={path.bandas} fill={COLOR.bandas} fillOpacity="0.045" stroke="none" />
                <path d={path.bbArriba} fill="none" stroke={COLOR.bandas} strokeWidth="0.9" strokeOpacity="0.75" vectorEffect="non-scaling-stroke" />
                <path d={path.bbAbajo} fill="none" stroke={COLOR.bandas} strokeWidth="0.9" strokeOpacity="0.75" vectorEffect="non-scaling-stroke" />
              </>
            )}
            {ver.s200 && <path d={path.s200} fill="none" stroke={COLOR.media200} strokeWidth="2.5" strokeLinecap="round" vectorEffect="non-scaling-stroke" />}
            {ver.s50 && <path d={path.s50} fill="none" stroke={COLOR.media50} strokeWidth="1.6" strokeLinecap="round" vectorEffect="non-scaling-stroke" />}
            {promedio != null && !promFuera && (
              <line x1="0" x2={W} y1={escalaY(promedio)} y2={escalaY(promedio)} stroke={COLOR.promedio}
                strokeWidth="1.3" strokeDasharray="6 5" vectorEffect="non-scaling-stroke" />
            )}
            {conVelas ? velas.map(b => {
              const color = b.sube ? v('rendi-pos-fill') : v('rendi-neg-fill')
              // La vela en curso (todavía se mueve), más transparente.
              return (
                // La vela de hoy mientras se mueve, más transparente: todavía no es una vela cerrada.
                <g key={b.k} opacity={b.enCurso ? 0.55 : undefined} data-en-curso={b.enCurso ? '' : undefined}>
                  <line x1={b.x} x2={b.x} y1={b.yh} y2={b.yl} stroke={color} strokeWidth="1" vectorEffect="non-scaling-stroke" />
                  <rect x={b.x - b.ancho / 2} width={b.ancho} y={b.cuerpoY} height={b.cuerpoH} fill={color} />
                </g>
              )
            }) : (
              <>
                <path d={path.c} fill="none" stroke={COLOR.precio} strokeWidth="1.7" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
                {path.hoy && <path d={path.hoy} data-tramo-hoy="" fill="none" stroke={COLOR.precio} strokeWidth="1.7" strokeDasharray="3 3" strokeLinecap="round" vectorEffect="non-scaling-stroke" />}
              </>
            )}
            {/* La raya del balance o dividendo que se está mirando (antes iba
                una por cada balance, siempre: ensuciaba el gráfico). */}
            {grupos.filter(g => g === grupoSel).flatMap(g => g.items.map(e => (
              <line key={`e${e.tipo}${e.fecha}`} x1={(pctX(e.i) / 100) * W} x2={(pctX(e.i) / 100) * W} y1="0" y2={H}
                stroke={e.tipo === 'balance' ? COLOR.balance : COLOR.dividendo}
                strokeOpacity={g === grupoSel ? 0.9 : 0.3} strokeWidth="1" strokeDasharray="2 4" vectorEffect="non-scaling-stroke" />
            )))}
            {mA && mB && (
              <>
                <rect x={(Math.min(mA.x, mB.x) / 100) * W} width={(Math.abs(mB.x - mA.x) / 100) * W} y="0" height={H}
                  fill={COLOR.medir} fillOpacity="0.08" />
                <line x1={(mA.x / 100) * W} y1={(yDe(precioA) / 100) * H} x2={(mB.x / 100) * W} y2={(yDe(precioB) / 100) * H}
                  stroke={COLOR.medir} strokeWidth="1.4" strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />
              </>
            )}
          </svg>

          <CapaFibonacci fib={fibonacci} puntos={puntos} pctX={pctX} pctY={pctY} precio={(x) => fmtPrecio(x, moneda)}
            marcado={sobreDibujo === ID_FIB_AUTO || elegido === ID_FIB_AUTO} />
          <CapaElliott elliott={elliott} puntos={puntos} pctX={pctX} pctY={pctY} precio={(x) => fmtPrecio(x, moneda)}
            marcado={sobreDibujo === ID_ELL_AUTO || elegido === ID_ELL_AUTO} />
          {/* Tus dibujos, y lo que se está dibujando (hasta el mouse). */}
          <CapaDibujos dibujos={pincel ? [...vistos, { id: '__pincel__', tipo: 'pincel', puntos: pincel, ...(colorNuevo ? { color: colorNuevo } : {}) }] : vistos} extendidos={conAviso} colorNuevo={colorNuevo} elegido={elegido} resaltado={agarrado?.id || sobreDibujo} trazo={notaNueva ? null : trazo} cursor={onToque && !notaNueva ? cursor : null}
            pctX={pctX} pctY={pctY} precio={(x) => fmtPrecio(x, moneda)} />
          {/* Tus notas y tu tesis: banderitas (sin línea). */}
          <Banderitas grupos={banderitas} elegido={elegido} resaltado={agarrado?.id || sobreDibujo} ancho={ancho} />
          {/* Marcas y el punto del mouse van en HTML: un círculo dentro de un
              SVG estirado (preserveAspectRatio=none) se deformaría en óvalo. */}
          {visibles.map((m, k) => (
            <span key={k} title={`${m.tipo === 'compra' ? 'Compraste' : 'Vendiste'} el ${fechaCorta(m.fecha)}`}
              className={`absolute w-3 h-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg-1 shadow-sm ${m.tipo === 'compra' ? 'bg-rendi-pos-fill' : 'bg-rendi-neg-fill'}`}
              style={{ left: `${pctX(m.i)}%`, top: `${pctY(puntos[m.i].c)}%` }} />
          ))}
          {ultimo && (
            <span aria-hidden="true" className="absolute w-2 h-2 -translate-x-1/2 -translate-y-1/2 rounded-full"
              style={{ left: `${pctX(puntos.length - 1)}%`, top: `${pctY(ultimo.c)}%`, background: COLOR.precio }} />
          )}
          {[[mA, precioA], [mB, precioB]].map(([l, precio], k) => l && !l.fuera && precio != null && (
            <span key={`m${k}`} aria-hidden="true" className="pointer-events-none absolute w-3 h-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg-1"
              style={{ left: `${l.x}%`, top: `${yDe(precio)}%`, background: COLOR.medir }} />
          ))}
          {mA && mB && mMed && mMed.diferencia !== 0 && (
            <span aria-hidden="true" data-rotulo={PRIORIDAD.medicion}
              className={`pointer-events-none absolute z-10 top-1 rounded border border-rendi-accent/40 bg-bg-raised/95 px-2 py-1 text-[12px] font-semibold tabular whitespace-nowrap shadow-sm ${(mA.x + mB.x) / 2 > 60 ? '-translate-x-full' : (mA.x + mB.x) / 2 < 40 ? '' : '-translate-x-1/2'} ${mMed.pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}
              style={{ left: `${(mA.x + mB.x) / 2}%` }}>
              {cada ? textoMedicionPorHora(mMed, cada) : textoMedicion(mMed)}
            </span>
          )}
          {/* Midiendo: la cruz del mouse, como en TradingView (la vertical, sólo
              en el aire de la derecha: sobre los días ya está la del globo). */}
          {ultimo && pctY(ultimo.c) >= 0 && pctY(ultimo.c) <= 100 && (
            <div aria-hidden="true" data-raya-ultimo="" className="pointer-events-none absolute inset-x-0 h-0 border-t border-dashed"
              style={{ top: `${pctY(ultimo.c)}%`, borderColor: colorDelDia, opacity: 0.55 }} />
          )}
          {cursor?.precio != null && (
            <>
              <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 h-0 border-t border-dashed border-ink-2/70" style={{ top: `${yDe(cursor.precio)}%` }} />
              {hover == null && <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 w-px bg-ink-2/50" style={{ left: `${pctX(cursor.k)}%` }} />}
            </>
          )}
          {ph && (
            <>
              <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 w-px bg-ink-2/50" style={{ left: `${pctX(hover)}%` }} />
              <span aria-hidden="true" className="pointer-events-none absolute w-2.5 h-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg-1"
                style={{ left: `${pctX(hover)}%`, top: `${pctY(ph.c)}%`, background: COLOR.precio }} />
              {/* El globo va pegado al punto que se mira (abajo a la derecha;
                  del otro lado si no entra), chico y de un renglón por dato:
                  arriba y fijo tapaba casi todo el gráfico (Nico, 22/10). Se
                  puede ocultar como un indicador más (Nico, 28/10: «hay veces
                  que es muy molesto»): queda la raya y el punto del día. */}
              {ver.globo !== false && (
              <div ref={globoRef} data-globo="" className={`pointer-events-none absolute z-10 rounded border border-line-2 bg-bg-raised/95 px-2 py-1.5 text-[11px] leading-tight shadow-sm tabular whitespace-nowrap ${pctY(ph.c) > 55 ? '-translate-y-[calc(100%+12px)]' : 'translate-y-3'}`}
                style={{ left: `${ladoGlobo(pctX(hover), ref.current?.clientWidth, anchoGlobo)}px`, top: `${pctY(ph.c)}%` }}>
                <div className="flex items-baseline gap-2">
                  <span className="text-ink-0 font-semibold text-[12px]">{fmtPrecio(ph.c, moneda)}</span>
                  <span className="text-ink-2">{ph.semana ? `semana del ${fechaCorta(ph.d)}` : cada ? fechaHoraCorta(ph.t) : fechaCorta(ph.d)}{ph.enCurso ? ' · en curso' : ph.hoy ? ' · hoy' : ''}</span>
                </div>
                {conVelas && (() => {
                  const vela = velaCompleta(ph, hover > 0 ? puntos[hover - 1].c : null)
                  return (
                    <>
                      <div className="text-ink-2 mt-0.5">
                        Ap. <span className="text-ink-1">{fmtPrecio(vela.o, moneda).replace(/^US\$ |^\$ /, '')}</span>
                        {' · '}Máx. <span className="text-ink-1">{fmtPrecio(vela.h, moneda).replace(/^US\$ |^\$ /, '')}</span>
                        {' · '}Mín. <span className="text-ink-1">{fmtPrecio(vela.l, moneda).replace(/^US\$ |^\$ /, '')}</span>
                      </div>
                    </>
                  )
                })()}
                <div className="flex gap-2.5 mt-0.5">
                  {ph.s200 != null && <Fila color={COLOR.media200} k="200" v={fmtPrecio(ph.s200, moneda).replace(/^US\$ |^\$ /, '')} />}
                  {ph.s50 != null && <Fila color={COLOR.media50} k="50" v={fmtPrecio(ph.s50, moneda).replace(/^US\$ |^\$ /, '')} />}
                  {ver.vol && ph.v > 0 && <Fila k="Vol." v={fmtVolumen(ph.v)} />}
                </div>
                {ver.bb && ph.bb_arriba != null && (
                  <div className="flex gap-2.5 mt-0.5">
                    {/* La de abajo puede dar negativa después de un salto brusco: un
                        precio bajo cero no existe, se dice «menos de 0». */}
                    <Fila color={COLOR.bandas} k="Bandas" v={`${ph.bb_abajo < 0 ? 'menos de 0' : fmtPrecio(ph.bb_abajo, moneda).replace(/^US\$ |^\$ /, '')} – ${fmtPrecio(ph.bb_arriba, moneda).replace(/^US\$ |^\$ /, '')}`} />
                  </div>
                )}
                {/* RSI y ADX en su propio renglón: en uno solo el globo no
                    entraba en un celular. */}
                {((verRsi && ph.rsi != null) || (verAdx && ph.adx != null)) && (
                  <div className="flex gap-2.5 mt-0.5">
                    {verRsi && ph.rsi != null && <Fila k="RSI" v={Math.round(ph.rsi)} />}
                    {verAdx && ph.adx != null && <Fila k="ADX" v={fmtAdx(ph.adx)} />}
                  </div>
                )}
                {visibles.filter(m => m.i === hover).map(m => (
                  <div key={m.tipo} className={`mt-0.5 font-medium ${m.tipo === 'compra' ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                    {m.tipo === 'compra' ? 'Compraste' : 'Vendiste'} {ph.semana ? 'esta semana' : cada ? 'ese día' : 'este día'}
                  </div>
                ))}
              </div>
              )}
            </>
          )}
        </div>

        {/* Los indicadores, arriba a la izquierda (como TradingView): afuera del
            área que escucha el mouse, para que tocar un ojito no sea tocar el gráfico. */}
        {leyenda && <div className="absolute left-1 top-1 right-[76px] z-20 pointer-events-none">{cloneElement(leyenda, { anchoDisponible: ancho, plegada: !!onToque })}</div>}
        {/* Columna de precios: la grilla, tu precio y el último precio. Se
            arrastra para estirar el gráfico en vertical (ver ejesGrafico.js). */}
        <div className="absolute inset-y-0 right-0 w-[68px] cursor-ns-resize touch-none select-none"
          title="Arrastrá hacia arriba o hacia abajo para estirar o achicar el gráfico. Doble click: vuelve a la escala automática."
          onPointerDown={e => { e.currentTarget.setPointerCapture?.(e.pointerId); ejeY.current = { y: e.clientY, ...(precioMano || empezarAMano([min, max], compartible)) } }}
          onPointerMove={e => {
            const t = ejeY.current
            if (!t) return
            // Lo arrastrado más allá del tope no se guarda (ver arrastreDentroDelTope).
            const dy = arrastreDentroDelTope(e.clientY - t.y)
            t.y = e.clientY - dy
            setPrecioMano(estirarAMano(t, dy))
          }}
          onPointerUp={() => { ejeY.current = null }} onPointerCancel={() => { ejeY.current = null }}
          onDoubleClick={() => setPrecioMano(null)}>
          {ticks.map((t, k) => !cerca(t) && (
            <span key={k} className="absolute left-1.5 -translate-y-1/2 text-[11px] text-ink-2 tabular whitespace-nowrap"
              style={{ top: `${pctY(t)}%` }}>{rotuloDePrecio(t)}</span>
          ))}
          {promVisible && !promCerca && pctY(promedio) >= 0 && pctY(promedio) <= 100 && (
            <span className="absolute left-0 -translate-y-1/2 rounded border border-dashed border-ink-3 bg-bg-1 px-1 text-[10.5px] text-ink-1 tabular whitespace-nowrap"
              style={{ top: `${pctY(promedio)}%` }}>Tu precio</span>
          )}
          {promFuera && (
            <span className={`absolute left-0 rounded border border-dashed border-ink-3 bg-bg-1 px-1 text-[10.5px] text-ink-1 tabular whitespace-nowrap ${promFuera === 'abajo' ? 'bottom-0' : 'top-0'}`}
              title={`Tu precio: ${fmtPrecio(promedio, moneda)}, fuera de este gráfico`}>
              {promFuera === 'abajo' ? '↓' : '↑'} Tu precio
            </span>
          )}
          {ultimo && pctY(ultimo.c) >= 0 && pctY(ultimo.c) <= 100 && (
            <span data-ultimo="" className="absolute left-0 -translate-y-1/2 rounded px-1.5 py-0.5 text-[11px] font-semibold tabular whitespace-nowrap"
              style={{ top: `${pctY(ultimo.c)}%`, background: colorDelDia, color: v('bg-0') }}>
              {fmtPrecio(ultimo.c, moneda).replace(/^US\$ /, '')}
            </span>
          )}
          {trazos.filter(t => t.tipo === 'horizontal' && t.y1 >= 0 && t.y1 <= 100).map(t => (
            <span key={t.id} data-aviso={conAviso.includes(t.id) ? '' : undefined}
              className="absolute left-0 -translate-y-1/2 inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] font-semibold tabular whitespace-nowrap"
              style={{ top: `${t.y1}%`, background: t.color || COLOR.dibujo, color: v('bg-0') }}>
              {conAviso.includes(t.id) && <Bell size={10} strokeWidth={2.5} aria-label="Con aviso" />}
              {fmtPrecio(t.precio, moneda).replace(/^US\$ /, '')}
            </span>
          ))}
          {/* Tu línea de tendencia o tu canal con aviso (Nico, 29/10): en la
              columna, con la campanita, dónde está hoy (en la última vela, la
              que mira el aviso; no en el borde derecho, que es el futuro). */}
          {vistos.filter(d => d.tipo !== 'horizontal' && conAviso.includes(d.id))
            .flatMap(d => preciosAlBorde(d, puntos.length - 1).map((p, k) => ({ key: `${d.id}-${k}`, p, color: colorDe(d) })))
            .filter(t => t.p > 0 && pctY(t.p) >= 0 && pctY(t.p) <= 100).map(t => (
              <span key={t.key} data-aviso="" className="absolute left-0 -translate-y-1/2 inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] font-semibold tabular whitespace-nowrap"
                style={{ top: `${pctY(t.p)}%`, background: t.color, color: v('bg-0') }}>
                <Bell size={10} strokeWidth={2.5} aria-label="Con aviso" />
                {fmtPrecio(t.p, moneda).replace(/^US\$ /, '')}
              </span>
            ))}
          {cursor?.precio != null && (
            <span aria-hidden="true" data-mira="" className="pointer-events-none absolute left-0 z-10 -translate-y-1/2 rounded px-1.5 py-0.5 text-[11px] font-semibold tabular whitespace-nowrap"
              style={{ top: `${yDe(cursor.precio)}%`, background: v('ink-2'), color: v('bg-0') }}>
              {fmtPrecio(cursor.precio, moneda).replace(/^US\$ /, '')}
            </span>
          )}
          {/* El doble click no se descubre solo y en el celular no existe:
              mientras el precio o las fechas están a mano, un botón vuelve LAS
              DOS cosas a automático (uno solo, no dos iguales uno al lado del
              otro). Va debajo de la columna, al lado de las fechas: abajo de
              todo lo pisaba «↓ Tu precio». */}
          {(precioMano || fechasAMano) && (
            <button type="button" onPointerDown={e => e.stopPropagation()} onClick={() => { setPrecioMano(null); onFechasAuto?.() }}
              className="absolute top-full mt-1 left-0 rounded border border-line-2 bg-bg-1 px-1.5 py-0.5 text-[10.5px] text-ink-1 hover:text-ink-0">
              Automático
            </button>
          )}
        </div>
      </div>

      {/* Balances («B») y dividendos («D»), sobre el eje de fechas. Cada uno es
          un botón: con el mouse encima, con el foco o con un toque, el globo
          dice qué fue y cuánto se movió el precio. */}
      {grupos.length > 0 && (
        <div className="relative mr-[72px] mt-1 h-4" role="group" aria-label="Balances y dividendos">
          {grupos.map(g => {
            const t = textoGrupo(g.items)
            return (
              <button key={g.clave} type="button" aria-label={`${t.titulo}. ${t.lineas.join(' ')}`}
                aria-expanded={g.clave === eventoSel}
                className="absolute top-0 -translate-x-1/2 inline-flex items-center rounded-full focus-visible:outline focus-visible:outline-2 focus-visible:outline-rendi-accent"
                style={{ left: `${g.x}%` }}
                onPointerEnter={ev => { if (ev.pointerType === 'mouse') { conMouse.current = true; setEventoSel(g.clave) } }}
                onPointerLeave={ev => { if (ev.pointerType === 'mouse') { conMouse.current = false; setEventoSel(null) } }}
                onFocus={() => setEventoSel(g.clave)} onBlur={() => setEventoSel(null)}
                onClick={() => setEventoSel(s => (s === g.clave && !conMouse.current ? null : g.clave))}>
                <Letra tipo={g.tipo} />
                {g.items.length > 1 && <span className="ml-0.5 text-[9.5px] font-semibold text-ink-2 tabular">{g.items.length}</span>}
              </button>
            )
          })}
          {grupoSel && (() => {
            const t = textoGrupo(grupoSel.items)
            const x = grupoSel.x
            return (
              // En el celular el globo ocupa el ancho del gráfico (pegado a la
              // marca quedaba de una palabra por renglón); desde sm, va junto a
              // la marca, del lado en que entra.
              <div aria-hidden="true"
                className={`pointer-events-none absolute bottom-full mb-1 z-20 left-0 right-0 sm:right-auto sm:left-[var(--x)] sm:w-max sm:max-w-[16rem] rounded border border-line-2 bg-bg-raised/95 px-2.5 py-1.5 text-[11.5px] leading-snug shadow-sm ${x > 62 ? 'sm:-translate-x-full' : x < 38 ? '' : 'sm:-translate-x-1/2'}`}
                style={{ '--x': `${x}%` }}>
                <div className="text-ink-0 font-semibold text-[12px]">{t.titulo}</div>
                {t.lineas.map((l, k) => <div key={k} className="text-ink-1 tabular">{l}</div>)}
              </div>
            )
          })()}
        </div>
      )}

      {/* Meses. Se arrastran para acercar o alejar en el tiempo, con el último
          día quieto (ver ejesGrafico.js). */}
      <div className="relative mr-[72px] h-6 mt-1 pt-0.5 text-[11px] text-ink-2 cursor-ew-resize touch-none select-none"
        title="Arrastrá hacia los costados para acercar o alejar el gráfico. Doble click: vuelve a la escala automática."
        onPointerDown={e => { e.currentTarget.setPointerCapture?.(e.pointerId); ejeX.current = { x: e.clientX } }}
        onPointerMove={e => {
          if (!ejeX.current || !onZoom) return
          const dx = e.clientX - ejeX.current.x
          // Como la ruedita: lo que no alcanza para mover una rueda se junta
          // (antes se tiraba, y acercado del todo un arrastre lento no alejaba).
          if (Math.abs(dx) >= 4 && onZoom(factorDeFechas(dx), 1)) ejeX.current.x = e.clientX
        }}
        onPointerUp={() => { ejeX.current = null }} onPointerCancel={() => { ejeX.current = null }}
        onDoubleClick={() => onFechasAuto?.()}>
        {meses.map(m => (
          <span key={m.i} className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${pctX(m.i)}%` }}>{m.texto}</span>
        ))}
        {/* El día bajo el mouse, encima de los rótulos (como TradingView). */}
        {cursor?.k != null && puntos[cursor.k] && (
          <span aria-hidden="true" data-mira="" className="pointer-events-none absolute z-10 -translate-x-1/2 rounded px-1.5 py-0.5 text-[11px] font-semibold tabular whitespace-nowrap"
            style={{ left: `${pctX(cursor.k)}%`, top: 0, background: v('ink-2'), color: v('bg-0') }}>{cada ? fechaHoraDeLaMira(puntos[cursor.k].t) : fechaDeLaMira(puntos[cursor.k].d)}</span>
        )}
      </div>
      {sinDividendos && (
        <p data-dividendos-ocultos="" className="mr-[72px] text-[11px] text-ink-2">Acercá el gráfico para ver los dividendos.</p>
      )}
      {pie}

      {/* RSI. */}
      {ver.rsi !== false && (
      <div className="mt-2 border-t border-line/40 pt-2.5">
        <div className="flex justify-between items-baseline text-[12px] text-ink-2 mr-[72px]">
          <span>Impulso (RSI)</span>
        </div>
        <div className="relative mt-1.5">
          <div className="relative mr-[72px] h-14 sm:h-24">
            <svg viewBox={`0 0 ${W} ${H_RSI}`} preserveAspectRatio="none" className="absolute inset-0 w-full h-full" aria-hidden="true">
              <rect x="0" y="0" width={W} height={H_RSI * (1 - RSI_ESTIRADO / 100)} fill={v('rendi-pos-fill')} fillOpacity="0.09" />
              <rect x="0" y={H_RSI * (1 - RSI_CASTIGADO / 100)} width={W} height={H_RSI * (RSI_CASTIGADO / 100)} fill={v('rendi-neg-fill')} fillOpacity="0.09" />
              <line x1="0" x2={W} y1={H_RSI / 2} y2={H_RSI / 2} stroke={v('chart-grid')} strokeDasharray="2 4" vectorEffect="non-scaling-stroke" />
              <path d={rsiPath} fill="none" stroke={v('ink-1')} strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
            </svg>
            {ph?.rsi != null && (
              <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 w-px bg-ink-2/50" style={{ left: `${pctX(hover)}%` }} />
            )}
          </div>
          <div className="absolute inset-y-0 right-0 w-[68px] text-[11px] text-ink-2 tabular pointer-events-none">
            {!rsiCerca(RSI_ESTIRADO) && <span className="absolute left-1.5 -translate-y-1/2" style={{ top: `${100 - RSI_ESTIRADO}%` }}>{RSI_ESTIRADO}</span>}
            {!rsiCerca(RSI_CASTIGADO) && <span className="absolute left-1.5 -translate-y-1/2" style={{ top: `${100 - RSI_CASTIGADO}%` }}>{RSI_CASTIGADO}</span>}
            {ultimoInd?.rsi != null && (
              <span className="absolute left-0 -translate-y-1/2 rounded px-1.5 py-0.5 font-semibold"
                style={{ top: `${100 - ultimoInd.rsi}%`, background: v('ink-1'), color: v('bg-0') }}>{Math.round(ultimoInd.rsi)}</span>
            )}
          </div>
        </div>
      </div>
      )}

      {/* Fuerza de la tendencia: ADX + Squeeze. */}
      {fuerza && ver.fuerza !== false && (
        <div className="mt-2 border-t border-line/40 pt-2.5">
          <div className="flex flex-wrap items-baseline gap-x-2 text-[12px] text-ink-2 mr-[72px]">
            <span>Fuerza de la tendencia (ADX)</span>
            <span className="inline-flex items-center gap-1 text-[11px]">
              <svg width="14" height="4" aria-hidden="true"><line x1="0" y1="2" x2="14" y2="2" stroke={v('rendi-accent')} strokeWidth="1.5" strokeDasharray="3 2" /></svg>
              arriba de {ADX_CLAVE}: con fuerza
            </span>
          </div>
          <div className="relative mt-1.5">
            <div className="relative mr-[72px] h-14 sm:h-24" role="img"
              aria-label={`Fuerza de la tendencia (ADX)${ultimoInd?.adx != null ? `: ${fmtAdx(ultimoInd.adx)}` : ''}, con la línea de ${ADX_CLAVE}.`}>
              <svg viewBox={`0 0 ${W} ${H_ADX}`} preserveAspectRatio="none" className="absolute inset-0 w-full h-full" aria-hidden="true">
                <rect x="0" y="0" width={W} height={fuerza.yClave} fill={v('rendi-accent')} fillOpacity="0.07" />
                <line x1="0" x2={W} y1={fuerza.yClave} y2={fuerza.yClave} stroke={v('rendi-accent')} strokeWidth="1.2"
                  strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />
                <path d={fuerza.d} fill="none" stroke={v('ink-1')} strokeWidth="1.5" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
              </svg>
              {/* El «23» va adentro, pegado a su línea a la izquierda: en la
                  columna de la derecha lo tapaba el cartel del ADX de hoy. */}
              <span aria-hidden="true" className="pointer-events-none absolute left-1 -translate-y-full pb-px text-[10.5px] leading-none text-rendi-accent tabular"
                style={{ top: `${fuerza.pctAdx(ADX_CLAVE)}%` }}>{ADX_CLAVE}</span>
              {ph && (
                <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 w-px bg-ink-2/50" style={{ left: `${pctX(hover)}%` }} />
              )}
            </div>
            <div className="absolute inset-y-0 right-0 w-[68px] text-[11px] tabular pointer-events-none">
              {ultimoInd?.adx != null && (
                <span aria-hidden="true" className="absolute left-0 -translate-y-1/2 rounded px-1.5 py-0.5 font-semibold"
                  style={{ top: `${Math.min(85, Math.max(15, fuerza.pctAdx(ultimoInd.adx)))}%`, background: v('ink-1'), color: v('bg-0') }}>{fmtAdx(ultimoInd.adx)}</span>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-x-2 mt-2 text-[12px] text-ink-2 mr-[72px]">
            <span>Squeeze · si el precio empuja al alza o a la baja</span>
            <span className="inline-flex items-center gap-1 text-[11px]">
              <span className="w-1.5 h-2.5 rounded-xs bg-rendi-pos-fill" aria-hidden="true" />al alza
              <span className="w-1.5 h-2.5 rounded-xs bg-rendi-neg-fill ml-1.5" aria-hidden="true" />a la baja
            </span>
          </div>
          <div className="relative mr-[72px] h-10 sm:h-16 mt-1" role="img"
            aria-label={`Barras del Squeeze (si el precio empuja al alza o a la baja): verdes al alza, rojas a la baja.${ultimoInd?.squeeze ? ` ${ultimoInd === ultimo ? 'Hoy' : 'Al último cierre'}, ${ultimoInd.squeeze > 0 ? 'verde' : 'roja'}.` : ''}`}>
            <svg viewBox={`0 0 ${W} ${H_SQUEEZE}`} preserveAspectRatio="none" className="absolute inset-0 w-full h-full" aria-hidden="true">
              <line x1="0" x2={W} y1={H_SQUEEZE / 2} y2={H_SQUEEZE / 2} stroke={v('chart-grid')} strokeWidth="1" vectorEffect="non-scaling-stroke" />
              {fuerza.barras.map(b => (
                <rect key={b.k} x={b.x} width={b.ancho} y={b.y} height={b.alto} fill={b.color[0]} fillOpacity={b.color[1]} />
              ))}
            </svg>
            {ph && (
              <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 w-px bg-ink-2/50" style={{ left: `${pctX(hover)}%` }} />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * Dónde va el borde izquierdo del globo, en px desde el borde del gráfico. A la
 * derecha del punto si entra (puede usar la columna de los precios, 68 px); si
 * no, a la izquierda; si tampoco, pegado al borde que tenga lugar. `pct` es
 * dónde está el punto (0 a 100), `ancho` el del gráfico y `globo` el del globo.
 */
export function ladoGlobo(pct, ancho, globo) {
  if (!ancho) return 0
  const g = globo || 200
  const x = (pct / 100) * ancho
  const tope = ancho + 68
  if (x + 12 + g <= tope) return x + 12
  if (x - 12 - g >= 0) return x - 12 - g
  return Math.max(0, tope - g)
}

// Un dato del globo, en una sola línea: la rayita del color de su línea, el
// nombre corto y el valor.
function Fila({ color, k, v: valor }) {
  return (
    <span className="inline-flex items-center gap-1 text-ink-2 whitespace-nowrap">
      {color && <span className="w-2 h-0.5 rounded-full" style={{ background: color }} />}{k}
      <span className="text-ink-1">{valor}</span>
    </span>
  )
}
