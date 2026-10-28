// LecturaTecnica — el gráfico técnico y su lectura en la ficha del activo.
// ════════════════════════════════════════════════════════════════════════════
// Gráfico de precio con las medias de 50 y 200 días, las Bandas de Bollinger
// (apagadas de entrada; el botón de la leyenda las prende junto con su
// tarjeta), tu precio promedio y tus compras y ventas; la fuerza del movimiento (RSI) abajo; y tarjetas en
// castellano. El botón «Fibonacci» de la leyenda (prendido de entrada) muestra la
// capa del último tramo de suba o bajada (CapaFibonacci.jsx). Se mide en
// DÓLARES por defecto: un CEDEAR en pesos sube con el dólar aunque la empresa
// no se mueva (ver backend/tecnico.py).
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
//
// Debajo del RSI, la fuerza de la tendencia en dos franjas: el ADX con su línea
// de 23 y las barras del Squeeze (el combo «DMI/ADX/KEYLEVEL» + «SQZMOM_LB» de
// TradingView), con su tarjeta «Fuerza de la tendencia».

import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Maximize2, Minimize2 } from 'lucide-react'
import AssetMiniChart from '../home/AssetMiniChart'
import CapaFibonacci, { COLOR_FIB, TarjetaFibonacci, preciosDeLaCapa, ventanaDelTramo } from './CapaFibonacci'
import { BotonAvisame, useAvisosTecnicos, senalDeTarjeta } from '../alerts/AvisameTecnico'
import { api } from '../../utils/api'
import { factorDeFechas, rangoCorrido, rangoEstirado } from '../../utils/ejesGrafico'
import {
  RANGOS, RSI_CASTIGADO, RSI_ESTIRADO, ADX_CLAVE, fmtAdx, tarjetas, tarjetaBandas, lineaPromedio, marcas, puntosEnDias, variacionDeHoy,
  indiceDeFecha, tendenciasDistintas, velaCompleta, velasSemanales, zoomVentana, moverVentana,
  ventanaInicial, margenDerecho, futuroMaximo,
} from '../../utils/tecnico'

const v = (t) => `rgb(var(--${t}))`
const COLOR = {
  precio: v('ink-0'),
  media200: v('rendi-accent'),
  // Naranja categórico, no celeste: con el azul de la media de 200 tenían la
  // misma luminosidad en modo claro y para un daltónico eran la misma línea.
  media50: v('cat-orange'),
  promedio: v('ink-2'),
  // Verde azulado: no se confunde con el azul de la de 200, el naranja de la de
  // 50 ni el magenta del Fibonacci.
  bandas: v('cat-teal'),
}
const W = 1000
const H = 260
const H_RSI = 64
const VOL_ALTO = 0.2   // la franja del volumen: el 20 % de abajo del gráfico de precio
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
  try { return localStorage.getItem(CLAVE_TIPO) === 'velas' ? 'velas' : 'linea' } catch { return 'linea' }
}
function guardarTipo(t) {
  try { localStorage.setItem(CLAVE_TIPO, t) } catch { /* sin almacenamiento */ }
}

const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

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

export default function LecturaTecnica({
  asset, symbolMiniChart, lotes = [], operaciones = [], pnlPctUsd = null,
  pnlPctLinea = undefined, lineaSinTc = false, referencia = null,
  costoPesos = null, accionLocal = false,
  // La ficha pone el título de la sección («Análisis técnico») y pasa null.
  titulo = 'Análisis técnico',
}) {
  const [moneda, setMoneda] = useState('usd')
  const [rango, setRango] = useState('1a')
  const [datos, setDatos] = useState({ usd: undefined, ars: undefined })
  // Qué líneas se ven: la leyenda prende y apaga cada una.
  // El Fibonacci arranca prendido (Nico, 22/10): es lo primero que se mira.
  const [ver, setVer] = useState({ s200: true, s50: true, bb: false, prom: true, marcas: true, fib: true, vol: true })
  const [tipo, setTipoEstado] = useState(tipoGuardado)
  const setTipo = (t) => { setTipoEstado(t); guardarTipo(t) }
  // Zoom con la rueda y arrastre: qué ruedas se ven ({ n: cuántas, fin: hasta
  // cuál, sin incluirla }). null = el rango del botón (3M/1A/2A).
  const [ventana, setVentana] = useState(null)
  // Velas diarias siempre; semanales sólo si se eligen (para mirar el panorama
  // de 2 años). El análisis (Fibonacci, giros) se hace sobre las diarias.
  const [intervalo, setIntervalo] = useState('dia')
  const elegirRango = (r) => { setRango(r); setVentana(null) }
  // Agrandado: el gráfico ocupa toda la pantalla (la ficha es angosta y el
  // gráfico quedaba chico con mucho negro alrededor, Nico 22/10). Esc o el
  // mismo botón lo achican; mientras tanto la página de atrás no se mueve.
  const [grande, setGrande] = useState(false)
  useEffect(() => {
    if (!grande) return
    const antes = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const tecla = (e) => { if (e.key === 'Escape') setGrande(false) }
    window.addEventListener('keydown', tecla)
    return () => { document.body.style.overflow = antes; window.removeEventListener('keydown', tecla) }
  }, [grande])
  // Las alertas de la cuenta, para que cada «Avisame» sepa si ya hay una igual.
  // Arriba de los return de abajo: un hook después de un return rompe la ficha.
  const avisos = useAvisosTecnicos()

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

  const marco = (hijos, conPesos = datos.ars?.disponible !== false) => (
    <Marco moneda={moneda} setMoneda={setMoneda} rango={ventana ? null : rango} setRango={elegirRango}
      tipo={tipo} setTipo={setTipo} conPesos={conPesos} grande={grande} setGrande={setGrande} titulo={titulo}>{hijos}</Marco>
  )
  // Cargando: el marco con sus botones queda quieto y el gris va adentro, con la
  // altura del gráfico ya reservada (antes desaparecía todo y la página saltaba).
  const cargando = <div role="status" aria-label="Cargando gráfico" className="h-[22rem] rounded-lg bg-bg-2/40 esqueleto" />
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
      return marco(<p className="text-sm text-ink-2">Este activo no tiene precio en pesos.</p>, false)
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

  const total = actual.puntos.length
  // La ventana en LUGARES (ver tecnico.margenDerecho): los días que se ven más
  // el aire vacío de la derecha, por donde se puede arrastrar hacia el futuro.
  const inicial = ventanaInicial(puntosEnDias(actual.puntos, RANGOS.find(r => r.id === rango)?.dias || 365), total)
  const v0 = ventana || inicial
  const nVista = v0.n
  const finVista = Math.min(v0.fin, total + futuroMaximo(nVista))
  const inicioVista = Math.max(0, finVista - nVista)
  const diarios = actual.puntos.slice(inicioVista, Math.min(finVista, total))
  const huecosDias = Math.max(0, finVista - total)
  const semanales = tipo === 'velas' && intervalo === 'semana'
  const puntos = semanales ? velasSemanales(diarios, actual.puntos.slice(Math.max(0, inicioVista - 7), inicioVista)) : diarios
  const huecos = semanales ? Math.round(huecosDias / 5) : huecosDias
  const vista = { n: nVista, fin: finVista, total }
  const zoom = (factor, f) => { const v2 = zoomVentana(vista, factor, f); if (v2) setVentana(v2); return !!v2 }
  const mover = (frac) => { const v2 = moverVentana(vista, frac); if (v2) setVentana(v2) }
  const promedio = lineaPromedio(actual.puntos, pnlPct,
    moneda === 'usd' ? variacionDeHoy(referencia?.precio, actual.cierre_ref) : 0)
  const ultimaFecha = actual.puntos[total - 1]?.d
  const misMarcas = marcas(lotes, operaciones).filter(m => m.fecha <= ultimaFecha)
  const marcasEnVista = misMarcas.filter(m => m.fecha >= (puntos[0]?.d || ''))
  // Si los precios no se pudieron actualizar en más de una semana, se avisa
  // arriba (antes sólo se veía la fecha en letra chica al pie).
  const diasViejo = ultimaFecha ? Math.floor((Date.now() - Date.parse(ultimaFecha + 'T12:00:00Z')) / 86400000) : 0
  const lista = tarjetas(actual.lectura)
  const distintas = tendenciasDistintas(datos.usd?.lectura, datos.ars?.lectura)
  const alternar = (k) => setVer(x => ({ ...x, [k]: !x[k] }))

  return marco(
    <>
      {diasViejo > 7 && (
        <div className="rounded-lg border border-rendi-warn/40 bg-rendi-warn/10 px-3.5 py-2.5 mb-3 text-[13px] text-ink-1">
          <b className="text-rendi-warn font-semibold">Los precios son del {fechaCorta(ultimaFecha)}.</b> No se pudieron actualizar desde ese día.
        </div>
      )}
      {moneda === 'ars' && distintas && (
        <div className="rounded-lg border border-rendi-warn/40 bg-rendi-warn/10 px-3.5 py-3 mb-3">
          <div className="text-sm font-semibold text-rendi-warn">En pesos la tendencia es otra que en dólares.</div>
          <p className="text-[13px] text-ink-1 leading-relaxed mt-1">
            Parte de lo que se mueve en pesos es el dólar, no la empresa. Por eso Rendi mira la tendencia en dólares.
          </p>
        </div>
      )}

      {tipo === 'velas' && (
        <div className="flex justify-end mb-2">
          <Segmento etiqueta="Cada vela es" valor={intervalo} alElegir={setIntervalo}
            opciones={[['dia', 'Diarias'], ['semana', 'Semanales']]} />
        </div>
      )}
      <Grafico puntos={puntos} huecos={huecos} moneda={moneda} promedio={ver.prom ? promedio : null}
        marcas={ver.marcas ? misMarcas : []} ver={ver} tipo={tipo} grande={grande}
        fibonacci={ver.fib ? actual.fibonacci : null} onZoom={zoom} onMover={mover}
        onFechasAuto={() => setVentana(null)} fechasAMano={ventana != null} reinicioPrecio={`${moneda}|${rango}|${tipo}|${intervalo}`} />
      <p className="text-[11.5px] text-ink-2 mt-1">
        {semanales && 'Cada vela es una semana. '}
        {tipo === 'velas' && !semanales && diarios.length > 300 && 'Cada vela es un día: acercá con la ruedita o pasá a velas semanales. '}
        <span className="hidden sm:inline">Con la ruedita del mouse acercás o alejás (como arrastrar las fechas). Arrastrá el gráfico para ir más atrás o más adelante. </span>
        Arrastrá los precios de la derecha para estirar el gráfico, y las fechas de abajo para acercar o alejar; con doble click (o «Automático») vuelve a como estaba.
      </p>

      <div className="flex flex-wrap gap-1.5 mt-3" role="group" aria-label="Qué líneas mostrar">
        {tipo === 'velas'
          ? <Chip activo fijo puntos>Velas: subió · bajó</Chip>
          : <Chip activo fijo color={COLOR.precio}>Precio</Chip>}
        <Chip activo={ver.s200} onClick={() => alternar('s200')} color={COLOR.media200} grueso>Promedio 200 días</Chip>
        <Chip activo={ver.s50} onClick={() => alternar('s50')} color={COLOR.media50}>Promedio 50 días</Chip>
        <Chip activo={ver.bb} onClick={() => alternar('bb')} color={COLOR.bandas}>Bandas de Bollinger</Chip>
        {puntos.some(p => p.v > 0) && (
          <Chip activo={ver.vol} onClick={() => alternar('vol')} barras>Volumen</Chip>
        )}
        {promedio != null && (
          <Chip activo={ver.prom} onClick={() => alternar('prom')} color={COLOR.promedio} punteado>Tu precio promedio</Chip>
        )}
        {marcasEnVista.length > 0 && (
          <Chip activo={ver.marcas} onClick={() => alternar('marcas')} puntos>Tus compras y ventas</Chip>
        )}
        {actual.fibonacci && (
          <Chip activo={ver.fib} onClick={() => {
            // Al prenderlo, el gráfico se acerca al tramo medido (si se ve chico).
            const v2 = !ver.fib && ventanaDelTramo(actual.puntos, actual.fibonacci, nVista)
            if (v2) setVentana({ n: v2.n + margenDerecho(v2.n), fin: v2.fin + margenDerecho(v2.n) })
            alternar('fib')
          }} color={COLOR_FIB}>Fibonacci</Chip>
        )}
      </div>

      <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
        {ver.fib && actual.fibonacci && (
          <TarjetaFibonacci fib={actual.fibonacci} precio={(x) => fmtPrecio(x, moneda)} fecha={fechaCorta} />
        )}
        {ver.bb && tarjetaBandas(actual.lectura) && <Tarjeta t={tarjetaBandas(actual.lectura)} />}
        {lista.map(t => {
          const s = senalDeTarjeta(t.id, actual.lectura)
          return (
            <Tarjeta key={t.id} t={t} pie={s && (
              <BotonAvisame avisos={avisos} asset={asset} accionLocal={accionLocal} moneda={moneda} {...s} />
            )} />
          )
        })}
        {(() => {
          // La tarjeta: en dólares, el MISMO resultado de arriba de la ficha; en
          // pesos, el de lo que pagaste en pesos.
          const r = moneda === 'usd' ? pnlPctUsd : pnlPct
          if (r == null) return null
          return (
            <Tarjeta t={{
              id: 'tuyo', titulo: 'Contra lo que pagaste', tono: r >= 0 ? 'pos' : 'neg',
              veredicto: `${r >= 0 ? 'Ganás' : 'Perdés'} ${Math.abs(r * 100).toLocaleString('es-AR', { maximumFractionDigits: 1, minimumFractionDigits: 1 })}%`,
              texto: moneda === 'usd'
                ? (lineaSinTc
                  ? 'Es el mismo resultado de arriba. La línea de tu precio promedio no se dibuja porque a alguna compra le falta el dólar de ese día.'
                  : 'Es el mismo resultado de arriba. La línea punteada es tu precio promedio, con el dólar del día de cada compra.')
                : 'Lo que vale hoy contra lo que pagaste, todo en pesos.',
            }} />
          )
        })()}
      </div>

      <p className="text-[12px] text-ink-2 mt-3 leading-relaxed">
        {moneda === 'usd' && 'Se mira en dólares aunque uses la app en pesos, porque en pesos el precio también sube con el dólar. Para verlo en pesos, tocá «Pesos» arriba del gráfico. '}
        {actual.convertida === 'mep' && (moneda === 'usd'
          ? 'El precio en pesos de cada día está pasado a dólares con el MEP de ese día. '
          : 'El precio en dólares de cada día está pasado a pesos con el MEP de ese día. ')}
        Datos al cierre del {fechaCorta(actual.lectura?.fecha)}. Muestra cómo se movió el precio: no es una recomendación para comprar ni vender.
      </p>
    </>
  )
}

function Marco({ moneda, setMoneda, rango, setRango, tipo, setTipo, conPesos = true, grande = false, setGrande, titulo, children }) {
  // Agrandado = la misma sección, fija sobre toda la pantalla (no es otra vista:
  // mismos datos, mismos botones; R6).
  return (
    <section aria-label="Análisis técnico" role={grande ? 'dialog' : undefined} aria-modal={grande || undefined}
      className={grande ? 'fixed inset-0 z-[70] overflow-y-auto bg-bg-0 px-3 py-3 sm:px-6 sm:py-5' : 'mb-5'}>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        {titulo ? <div className="text-[12.5px] text-ink-2 font-medium">{titulo}</div> : <span />}
        <div className="flex flex-wrap items-center gap-2">
          {setGrande && (
            <button type="button" onClick={() => setGrande(!grande)} aria-pressed={grande}
              title={grande ? 'Achicar (Esc)' : 'Agrandar el gráfico'}
              className="inline-flex items-center gap-1.5 min-h-10 sm:min-h-8 px-3 sm:px-2.5 rounded-lg border border-line bg-bg-2 text-xs text-ink-1 hover:text-ink-0">
              {grande ? <Minimize2 size={14} aria-hidden="true" /> : <Maximize2 size={14} aria-hidden="true" />}
              {grande ? 'Achicar' : 'Agrandar'}
            </button>
          )}
          <Segmento etiqueta="Tipo de gráfico" valor={tipo} alElegir={setTipo}
            opciones={[['linea', 'Línea'], ['velas', 'Velas']]} />
          <Segmento etiqueta="Moneda" valor={moneda} alElegir={setMoneda}
            opciones={[['usd', 'Dólares'], ...(conPesos ? [['ars', 'Pesos']] : [])]} />
          <Segmento etiqueta="Rango" valor={rango} alElegir={setRango}
            opciones={RANGOS.map(r => [r.id, r.label])} />
        </div>
      </div>
      <div className="bg-bg-1 border border-line/60 rounded-xl p-3 sm:p-4">{children}</div>
    </section>
  )
}

function Segmento({ etiqueta, valor, alElegir, opciones }) {
  return (
    <div className="inline-flex gap-0.5 bg-bg-2 border border-line rounded-lg p-0.5" role="group" aria-label={etiqueta}>
      {opciones.map(([id, label]) => (
        <button key={id} type="button" onClick={() => alElegir(id)} aria-pressed={valor === id}
          className={`min-h-10 sm:min-h-8 px-3 sm:px-2.5 text-xs rounded tabular transition-colors ${valor === id ? 'bg-bg-1 text-ink-0 font-medium shadow-sm' : 'text-ink-2 hover:text-ink-0'}`}>
          {label}
        </button>
      ))}
    </div>
  )
}

function Chip({ activo, fijo, onClick, color, grueso, punteado, puntos, barras, children }) {
  // `puntos`: la muestra es un punto verde y uno rojo (compras/ventas, o velas que suben/bajan).
  // `barras`: tres barritas (el volumen).
  const muestra = barras ? (
    <svg width="14" height="10" aria-hidden="true" className="text-ink-3">
      <rect x="0" y="5" width="3" height="5" fill="currentColor" />
      <rect x="5" y="2" width="3" height="8" fill="currentColor" />
      <rect x="10" y="6" width="3" height="4" fill="currentColor" />
    </svg>
  ) : puntos ? (
    <span className="inline-flex gap-0.5" aria-hidden="true">
      <span className="w-2 h-2 rounded-full bg-rendi-pos-fill" />
      <span className="w-2 h-2 rounded-full bg-rendi-neg-fill" />
    </span>
  ) : (
    <svg width="16" height="6" aria-hidden="true">
      <line x1="0" y1="3" x2="16" y2="3" stroke={color} strokeWidth={grueso ? 3 : 2}
        strokeDasharray={punteado ? '4 3' : undefined} />
    </svg>
  )
  const clase = `inline-flex items-center gap-1.5 min-h-10 sm:min-h-[30px] px-3 sm:px-2.5 rounded-full border text-[12px] transition-colors ${activo ? 'border-line-2 bg-bg-2/60 text-ink-1' : 'border-line text-ink-3 opacity-60'}`
  if (fijo) return <span className={clase}>{muestra}{children}</span>
  return (
    <button type="button" onClick={onClick} aria-pressed={!!activo} className={`${clase} hover:text-ink-0`}>
      {muestra}{children}
    </button>
  )
}

// `pie`: el «Avisame» de la señal de esa tarjeta (AvisameTecnico), arriba a la
// derecha, chico, para no competir con la lectura.
function Tarjeta({ t, pie }) {
  const tono = t.tono === 'pos' ? 'text-rendi-pos' : t.tono === 'neg' ? 'text-rendi-neg' : 'text-ink-0'
  return (
    <div className="rounded-lg border border-line/60 bg-bg-2/40 px-3.5 py-3">
      <div className="flex items-start justify-between gap-2">
        <div className="text-[12px] text-ink-2 font-medium">{t.titulo}</div>
        {pie && <div className="-mt-1.5 flex-shrink-0">{pie}</div>}
      </div>
      <div className={`text-[15px] font-semibold mt-0.5 tabular ${tono}`}>{t.veredicto}</div>
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
        <span>← pierde fuerza</span><span>toma fuerza →</span>
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

// Rótulos de meses para el eje de abajo: el primer día de cada mes, salteando
// para que entren unos 6.
function rotulosDeMeses(puntos) {
  const cambios = []
  for (let i = 1; i < puntos.length; i++) {
    if (puntos[i].d.slice(0, 7) !== puntos[i - 1].d.slice(0, 7)) cambios.push(i)
  }
  const paso = Math.max(1, Math.ceil(cambios.length / 6))
  return cambios.filter((_, k) => k % paso === 0).map(i => {
    const [y, m] = puntos[i].d.split('-')
    return { i, texto: m === '01' ? y : MESES[Number(m) - 1] }
  })
}

function Grafico({ puntos, huecos = 0, moneda, promedio, marcas: lista, ver, tipo = 'linea', grande = false, fibonacci = null, onZoom, onMover, onFechasAuto, fechasAMano = false, reinicioPrecio }) {
  const conVelas = tipo === 'velas'
  // Los lugares del ancho: los días más el aire vacío de la derecha.
  const lugares = puntos.length + huecos
  const ref = useRef(null)
  const arrastre = useRef(null)
  // Los ejes se arrastran como en TradingView (utils/ejesGrafico.js): la
  // columna de precios estira el gráfico en vertical y deja el precio "a mano"
  // (`precioMano` = { lo, hi } fijo; null = automático), y la fila de fechas
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
    el.addEventListener('wheel', rueda, { passive: false })
    return () => el.removeEventListener('wheel', rueda)
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

  const { escalaY, path, area, min, max, velas, volumen, promFuera } = useMemo(() => {
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
      if (ver.bb && p.bb_arriba != null) valores.push(p.bb_arriba, p.bb_abajo)
    }
    valores.push(...preciosDeLaCapa(fibonacci, puntos))
    let lo = Math.min(...valores), hi = Math.max(...valores)
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
    const margen = (hi - lo) * 0.08 || hi * 0.02 || 1
    lo -= margen; hi += margen
    // El volumen va en la franja de abajo (el 20 % del alto): se le deja ese
    // lugar para que las barras no tapen las velas.
    const maxVol = ver.vol ? Math.max(0, ...puntos.map(p => p.v || 0)) : 0
    if (maxVol > 0) lo -= (hi - lo) * 0.25
    if (precioMano) {
      lo = precioMano.lo; hi = precioMano.hi
      fuera = promedio == null ? null : promedio < lo ? 'abajo' : promedio > hi ? 'arriba' : null
    }
    const y = (val) => H - ((val - lo) / (hi - lo)) * H
    const x = (i) => (lugares > 1 ? (i / (lugares - 1)) * W : W / 2)
    const linea = (k) => {
      let d = '', abierto = false
      puntos.forEach((p, i) => {
        if (p[k] == null) { abierto = false; return }
        d += `${abierto ? 'L' : 'M'}${x(i).toFixed(1)},${y(p[k]).toFixed(1)}`
        abierto = true
      })
      return d
    }
    const c = linea('c')
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
        cuerpoY: arriba, cuerpoH: Math.max(Math.abs(y(vela.o) - y(vela.c)), 0.8), ancho,
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
      return { k: i, x: x(i), y: H - alto, alto, ancho: anchoVol, sube }
    }).filter(Boolean) : []
    return {
      escalaY: y, min: lo, max: hi, velas, volumen, promFuera: fuera,
      path: { c, s50: linea('s50'), s200: linea('s200'), bbArriba: linea('bb_arriba'), bbAbajo: linea('bb_abajo'), bandas },
      area: c ? `${c}L${x(puntos.length - 1).toFixed(1)},${H}L0,${H}Z` : '',
    }
  }, [puntos, lugares, promedio, ver.s50, ver.s200, ver.bb, ver.vol, conVelas, fibonacci, precioMano])

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
  const visibles = lista
    .filter(m => m.fecha >= desde)
    .map(m => ({ ...m, i: indiceDeFecha(puntos, m.fecha) }))
    .filter(m => m.i != null && pctY(puntos[m.i].c) >= 0 && pctY(puntos[m.i].c) <= 100)

  // El mouse o el dedo: el punto más cercano en el tiempo.
  function mover(clientX) {
    const r = ref.current?.getBoundingClientRect()
    if (!r || !puntos.length) return
    const i = Math.round(((clientX - r.left) / r.width) * (lugares - 1))
    // En el aire de la derecha (el futuro) no hay día que mostrar.
    setHover(i > puntos.length - 1 ? null : Math.max(0, i))
  }
  const ph = hover != null ? puntos[hover] : null
  const ultimo = puntos[puntos.length - 1]
  const ticks = [max - (max - min) * 0.12, (max + min) / 2, min + (max - min) * 0.12]
  const meses = rotulosDeMeses(puntos)
  // Los rótulos del eje se esconden si chocan con la etiqueta del último precio
  // o con la de tu precio (que pesan más).
  const promVisible = promedio != null && !promFuera
  const promCerca = promVisible && ultimo && Math.abs(pctY(promedio) - pctY(ultimo.c)) < 9
  const cerca = (val) => (ultimo && Math.abs(pctY(val) - pctY(ultimo.c)) < 7)
    || (promVisible && !promCerca && Math.abs(pctY(val) - pctY(promedio)) < 7)
  const rsiCerca = (nivel) => ultimo?.rsi != null && Math.abs(nivel - ultimo.rsi) < 12

  return (
    <div>
      <div className="relative">
        {/* Área del gráfico: deja libre la columna de la derecha para los precios. */}
        {/* Con la escala vertical a mano, lo que queda fuera se recorta (como en
            TradingView); en automático no hace falta y el punto del último
            precio puede asomar sobre el borde. */}
        <div ref={ref} className={`relative mr-[72px] ${grande ? 'h-[58vh] min-h-64' : 'h-56 sm:h-64'} select-none touch-pan-y cursor-crosshair ${precioMano ? 'overflow-hidden' : ''}`}
          onMouseDown={e => { arrastre.current = { x: e.clientX, y: e.clientY } }}
          onMouseUp={() => { arrastre.current = null }}
          onMouseMove={e => {
            const a = arrastre.current
            if (a) {
              const r = ref.current.getBoundingClientRect()
              const frac = (e.clientX - a.x) / r.width
              if (onMover && Math.abs(frac) * puntos.length >= 1) { onMover(frac); a.x = e.clientX }
              // Con el precio a mano, también para arriba y para abajo.
              const fy = (e.clientY - a.y) / r.height
              if (precioMano && Math.abs(fy) >= 0.005) { setPrecioMano(rangoCorrido(min, max, fy)); a.y = e.clientY }
            }
            mover(e.clientX)
          }}
          onMouseLeave={() => { setHover(null); arrastre.current = null }}
          onTouchStart={e => mover(e.touches[0].clientX)} onTouchMove={e => mover(e.touches[0].clientX)}
          onTouchEnd={() => setHover(null)}
          role="img" aria-label={`Precio con su promedio de 200 y de 50 días. Último cierre ${fmtPrecio(ultimo?.c, moneda)}.`}>
          <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 w-full h-full" aria-hidden="true">
            <defs>
              <linearGradient id={`area-${gid}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" style={{ stopColor: COLOR.precio, stopOpacity: 0.12 }} />
                <stop offset="100%" style={{ stopColor: COLOR.precio, stopOpacity: 0 }} />
              </linearGradient>
            </defs>
            {ticks.map((t, k) => (
              <line key={k} x1="0" x2={W} y1={escalaY(t)} y2={escalaY(t)} stroke={v('chart-grid')} strokeWidth="1"
                strokeDasharray="2 4" vectorEffect="non-scaling-stroke" />
            ))}
            {!conVelas && <path d={area} fill={`url(#area-${gid})`} />}
            {volumen.map(b => (
              <rect key={`v${b.k}`} x={b.x - b.ancho / 2} width={b.ancho} y={b.y} height={b.alto}
                fill={b.sube ? v('rendi-pos-fill') : v('rendi-neg-fill')} fillOpacity="0.28" />
            ))}
            {ver.bb && (
              <>
                <path d={path.bandas} fill={COLOR.bandas} fillOpacity="0.08" stroke="none" />
                <path d={path.bbArriba} fill="none" stroke={COLOR.bandas} strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
                <path d={path.bbAbajo} fill="none" stroke={COLOR.bandas} strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
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
              return (
                <g key={b.k}>
                  <line x1={b.x} x2={b.x} y1={b.yh} y2={b.yl} stroke={color} strokeWidth="1" vectorEffect="non-scaling-stroke" />
                  <rect x={b.x - b.ancho / 2} width={b.ancho} y={b.cuerpoY} height={b.cuerpoH} fill={color} />
                </g>
              )
            }) : (
              <path d={path.c} fill="none" stroke={COLOR.precio} strokeWidth="1.7" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
            )}
          </svg>

          <CapaFibonacci fib={fibonacci} puntos={puntos} pctX={pctX} pctY={pctY} precio={(x) => fmtPrecio(x, moneda)} />
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
          {ph && (
            <>
              <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 w-px bg-ink-2/50" style={{ left: `${pctX(hover)}%` }} />
              <span aria-hidden="true" className="pointer-events-none absolute w-2.5 h-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg-1"
                style={{ left: `${pctX(hover)}%`, top: `${pctY(ph.c)}%`, background: COLOR.precio }} />
              {/* El globo va pegado al punto que se mira (abajo a la derecha;
                  del otro lado si no entra), chico y de un renglón por dato:
                  arriba y fijo tapaba casi todo el gráfico (Nico, 22/10). */}
              <div ref={globoRef} className={`pointer-events-none absolute z-10 rounded border border-line-2 bg-bg-raised/95 px-2 py-1.5 text-[11px] leading-tight shadow-sm tabular whitespace-nowrap ${pctY(ph.c) > 55 ? '-translate-y-[calc(100%+12px)]' : 'translate-y-3'}`}
                style={{ left: `${ladoGlobo(pctX(hover), ref.current?.clientWidth, anchoGlobo)}px`, top: `${pctY(ph.c)}%` }}>
                <div className="flex items-baseline gap-2">
                  <span className="text-ink-0 font-semibold text-[12px]">{fmtPrecio(ph.c, moneda)}</span>
                  <span className="text-ink-2">{ph.semana ? `semana del ${fechaCorta(ph.d)}` : fechaCorta(ph.d)}</span>
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
                    <Fila color={COLOR.bandas} k="Bandas" v={`${fmtPrecio(ph.bb_abajo, moneda).replace(/^US\$ |^\$ /, '')} – ${fmtPrecio(ph.bb_arriba, moneda).replace(/^US\$ |^\$ /, '')}`} />
                  </div>
                )}
                {/* RSI y ADX en su propio renglón: en uno solo el globo no
                    entraba en un celular. */}
                {(ph.rsi != null || ph.adx != null) && (
                  <div className="flex gap-2.5 mt-0.5">
                    {ph.rsi != null && <Fila k="RSI" v={Math.round(ph.rsi)} />}
                    {ph.adx != null && <Fila k="ADX" v={fmtAdx(ph.adx)} />}
                  </div>
                )}
                {visibles.filter(m => m.i === hover).map(m => (
                  <div key={m.tipo} className={`mt-0.5 font-medium ${m.tipo === 'compra' ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                    {m.tipo === 'compra' ? 'Compraste' : 'Vendiste'} {ph.semana ? 'esta semana' : 'este día'}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Columna de precios: la grilla, tu precio y el último precio. Se
            arrastra para estirar el gráfico en vertical (ver ejesGrafico.js). */}
        <div className="absolute inset-y-0 right-0 w-[68px] cursor-ns-resize touch-none select-none"
          title="Arrastrá hacia arriba o hacia abajo para estirar o achicar. Doble click: automático."
          onPointerDown={e => { e.currentTarget.setPointerCapture?.(e.pointerId); ejeY.current = { y: e.clientY, lo: min, hi: max } }}
          onPointerMove={e => { const t = ejeY.current; if (t) setPrecioMano(rangoEstirado(t.lo, t.hi, e.clientY - t.y)) }}
          onPointerUp={() => { ejeY.current = null }} onPointerCancel={() => { ejeY.current = null }}
          onDoubleClick={() => setPrecioMano(null)}>
          {ticks.map((t, k) => !cerca(t) && (
            <span key={k} className="absolute left-1.5 -translate-y-1/2 text-[11px] text-ink-2 tabular whitespace-nowrap"
              style={{ top: `${pctY(t)}%` }}>{fmtPrecio(t, moneda).replace(/^US\$ /, '')}</span>
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
            <span className="absolute left-0 -translate-y-1/2 rounded px-1.5 py-0.5 text-[11px] font-semibold tabular whitespace-nowrap"
              style={{ top: `${pctY(ultimo.c)}%`, background: COLOR.precio, color: v('bg-0') }}>
              {fmtPrecio(ultimo.c, moneda).replace(/^US\$ /, '')}
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

      {/* Meses. Se arrastran para acercar o alejar en el tiempo, con el último
          día quieto (ver ejesGrafico.js). */}
      <div className="relative mr-[72px] h-6 mt-1 pt-0.5 text-[11px] text-ink-2 cursor-ew-resize touch-none select-none"
        title="Arrastrá hacia los costados para acercar o alejar. Doble click: automático."
        onPointerDown={e => { e.currentTarget.setPointerCapture?.(e.pointerId); ejeX.current = { x: e.clientX } }}
        onPointerMove={e => {
          if (!ejeX.current || !onZoom) return
          const dx = e.clientX - ejeX.current.x
          if (Math.abs(dx) >= 4) { onZoom(factorDeFechas(dx), 1); ejeX.current.x = e.clientX }
        }}
        onPointerUp={() => { ejeX.current = null }} onPointerCancel={() => { ejeX.current = null }}
        onDoubleClick={() => onFechasAuto?.()}>
        {meses.map(m => (
          <span key={m.i} className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${pctX(m.i)}%` }}>{m.texto}</span>
        ))}
      </div>

      {/* RSI. */}
      <div className="mt-2 border-t border-line/40 pt-2.5">
        <div className="flex justify-between items-baseline text-[12px] text-ink-2 mr-[72px]">
          <span>Fuerza (RSI)</span>
        </div>
        <div className="relative mt-1.5">
          <div className={`relative mr-[72px] ${grande ? 'h-24' : 'h-14'}`}>
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
            {ultimo?.rsi != null && (
              <span className="absolute left-0 -translate-y-1/2 rounded px-1.5 py-0.5 font-semibold"
                style={{ top: `${100 - ultimo.rsi}%`, background: v('ink-1'), color: v('bg-0') }}>{Math.round(ultimo.rsi)}</span>
            )}
          </div>
        </div>
      </div>

      {/* Fuerza de la tendencia: ADX + Squeeze. */}
      {fuerza && (
        <div className="mt-2 border-t border-line/40 pt-2.5">
          <div className="flex flex-wrap items-baseline gap-x-2 text-[12px] text-ink-2 mr-[72px]">
            <span>Fuerza de la tendencia (ADX)</span>
            <span className="inline-flex items-center gap-1 text-[11px]">
              <svg width="14" height="4" aria-hidden="true"><line x1="0" y1="2" x2="14" y2="2" stroke={v('rendi-accent')} strokeWidth="1.5" strokeDasharray="3 2" /></svg>
              arriba de {ADX_CLAVE}: con fuerza
            </span>
          </div>
          <div className="relative mt-1.5">
            <div className={`relative mr-[72px] ${grande ? 'h-24' : 'h-14'}`} role="img"
              aria-label={`Fuerza de la tendencia (ADX)${ultimo?.adx != null ? `: ${fmtAdx(ultimo.adx)}` : ''}, con la línea de ${ADX_CLAVE}.`}>
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
              {ultimo?.adx != null && (
                <span aria-hidden="true" className="absolute left-0 -translate-y-1/2 rounded px-1.5 py-0.5 font-semibold"
                  style={{ top: `${Math.min(85, Math.max(15, fuerza.pctAdx(ultimo.adx)))}%`, background: v('ink-1'), color: v('bg-0') }}>{fmtAdx(ultimo.adx)}</span>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-x-2 mt-2 text-[12px] text-ink-2 mr-[72px]">
            <span>Squeeze</span>
            <span className="inline-flex items-center gap-1 text-[11px]">
              <span className="w-1.5 h-2.5 rounded-xs bg-rendi-pos-fill" aria-hidden="true" />a favor de la suba
              <span className="w-1.5 h-2.5 rounded-xs bg-rendi-neg-fill ml-1.5" aria-hidden="true" />de la baja
            </span>
          </div>
          <div className={`relative mr-[72px] ${grande ? 'h-16' : 'h-10'} mt-1`} role="img"
            aria-label={`Barras del Squeeze: verdes a favor de la suba, rojas a favor de la baja.${ultimo?.squeeze ? ` Hoy, ${ultimo.squeeze > 0 ? 'verde' : 'roja'}.` : ''}`}>
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
