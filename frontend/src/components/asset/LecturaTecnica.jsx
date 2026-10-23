// LecturaTecnica — el gráfico técnico y su lectura en la ficha del activo.
// ════════════════════════════════════════════════════════════════════════════
// Gráfico de precio con las medias de 50 y 200 días, tu precio promedio y tus
// compras y ventas; la fuerza del movimiento (RSI) abajo; y tarjetas en
// castellano. El botón «Fibonacci» de la leyenda (prendido de entrada) muestra la
// capa del último tramo de suba o bajada (CapaFibonacci.jsx). Se mide en
// DÓLARES por defecto: un CEDEAR en pesos sube con el dólar aunque la empresa
// no se mueva (ver backend/tecnico.py).
//
// Encima del gráfico, los balances («B») y dividendos («D») de la empresa con
// lo que se movió el precio (GET /api/tecnico/{asset}/eventos), el modo «Medir
// entre dos puntos» y el rango «Desde que lo tenés». Debajo de las tarjetas,
// «Cuánto se mueve este papel» (backend/movimiento.py). Todo es lo que YA pasó:
// nada de esto anticipa nada. Las palabras: utils/cuantoSeMueve.js.
//
// Los números vienen de GET /api/tecnico (las velas que se guardan de noche).
// Si el activo todavía no tiene velas (recién agregado, o un bono/fondo), se
// muestra el gráfico de 30 días de siempre (`AssetMiniChart`).
//
// Una sola vista para compu y celular (R6): el gráfico es `width: 100%`, los
// precios del eje van en su propia columna a la derecha (no tapan la línea) y
// las tarjetas se acomodan en la grilla. Colores sólo por variables del tema
// (R8): `rgb(var(--token))` en el SVG, que sigue al modo claro y al oscuro.

import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Maximize2, Minimize2, Ruler } from 'lucide-react'
import AssetMiniChart from '../home/AssetMiniChart'
import CapaFibonacci, { COLOR_FIB, TarjetaFibonacci, preciosDeLaCapa, ventanaDelTramo } from './CapaFibonacci'
import { api } from '../../utils/api'
import { factorDeFechas, rangoCorrido, rangoEstirado } from '../../utils/ejesGrafico'
import {
  RANGOS, RSI_CASTIGADO, RSI_ESTIRADO, tarjetas, lineaPromedio, marcas, puntosEnDias, variacionDeHoy,
  indiceDeFecha, tendenciasDistintas, velaCompleta, velasSemanales, zoomVentana, moverVentana, RUEDAS_MINIMAS,
} from '../../utils/tecnico'
import {
  medicion as medirEntre, primeraCompra, puntosDesde, tarjetasMovimiento, textoGrupo, textoMedicion,
} from '../../utils/cuantoSeMueve'

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
}
const W = 1000
const H = 260
// Dos marcas de balance o dividendo más cerca que esto (en la pantalla) se
// juntan: es lo que ocupa una marca con su número al lado («D 2»).
const MARCA_PX = 34
const H_RSI = 64
const VOL_ALTO = 0.2   // la franja del volumen: el 20 % de abajo del gráfico de precio
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
  costoPesos = null, accionLocal = false, tenencia = null, valorCartera = null,
}) {
  const [moneda, setMoneda] = useState('usd')
  const [rango, setRango] = useState('1a')
  const [datos, setDatos] = useState({ usd: undefined, ars: undefined })
  // Qué líneas se ven: la leyenda prende y apaga cada una.
  // El Fibonacci arranca prendido (Nico, 22/10): es lo primero que se mira.
  const [ver, setVer] = useState({ s200: true, s50: true, prom: true, marcas: true, fib: true, vol: true, eventos: true })
  // Balances y dividendos de la empresa, por moneda (lo que se movió el precio
  // es sobre la serie de esa moneda). Llegan después del gráfico: piden Yahoo.
  const [eventos, setEventos] = useState({ usd: undefined, ars: undefined })
  // Medir entre dos puntos: los dos días tocados, por FECHA (sobreviven al zoom
  // y al arrastre). a sin b = esperando el segundo toque.
  const [medir, setMedir] = useState({ activo: false, a: null, b: null })
  useEffect(() => { setMedir(m => ({ ...m, a: null, b: null })) }, [moneda])
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
      tipo={tipo} setTipo={setTipo} conPesos={conPesos} grande={grande} setGrande={setGrande}
      conTuyo={!!primera}>{hijos}</Marco>
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
    // Sin velas todavía: el gráfico de siempre.
    return symbolMiniChart ? (
      <section className="mb-5">
        <div className="text-[12.5px] text-ink-2 mb-2 font-medium">Precio · últimos 30 días</div>
        <div className="bg-bg-1 border border-line/60 rounded-lg p-3">
          <AssetMiniChart symbol={symbolMiniChart} />
        </div>
      </section>
    ) : null
  }

  const total = actual.puntos.length
  const nRango = rango === 'tuyo' && primera
    ? Math.max(RUEDAS_MINIMAS, puntosDesde(actual.puntos, primera))
    : puntosEnDias(actual.puntos, RANGOS.find(r => r.id === rango)?.dias || 365)
  const nVista = Math.min(ventana?.n ?? nRango, total)
  const finVista = Math.min(ventana?.fin ?? total, total)
  const diarios = actual.puntos.slice(Math.max(0, finVista - nVista), finVista)
  const semanales = tipo === 'velas' && intervalo === 'semana'
  const puntos = semanales ? velasSemanales(diarios) : diarios
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
  const losEventos = eventos[moneda] || []
  // Un toque en el gráfico (modo medir): el día de ese punto. En velas
  // semanales, el ÚLTIMO día de esa semana (el cierre de la vela).
  const tocar = (k) => {
    let fecha = puntos[k]?.d
    if (semanales) {
      const sig = puntos[k + 1]
      fecha = sig ? diarios[Math.max(0, indiceDeFecha(diarios, sig.d) - 1)]?.d : diarios[diarios.length - 1]?.d
    }
    if (!fecha) return
    setMedir(m => (m.a && !m.b ? { ...m, b: fecha } : { activo: true, a: fecha, b: null }))
  }
  const medida = medir.activo ? medirEntre(actual.puntos, medir.a, medir.b) : null
  const tenenciaEnMoneda = tenencia?.valorUsd > 0
    ? { valor: moneda === 'usd' ? tenencia.valorUsd : tenencia.valorUsd * (tenencia.tc || 0) } : null
  const cuanto = tarjetasMovimiento(actual.movimiento, {
    moneda, precio: (x) => fmtPrecio(x, moneda), tenencia: tenenciaEnMoneda,
    peso: tenencia?.valorUsd > 0 && valorCartera > 0 ? tenencia.valorUsd / valorCartera : null,
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
      <Grafico puntos={puntos} moneda={moneda} promedio={ver.prom ? promedio : null}
        marcas={ver.marcas ? misMarcas : []} ver={ver} tipo={tipo} grande={grande}
        fibonacci={ver.fib ? actual.fibonacci : null} onZoom={zoom} onMover={mover}
        onFechasAuto={() => setVentana(null)} fechasAMano={ventana != null} reinicioPrecio={`${moneda}|${rango}|${tipo}|${intervalo}`}
        eventos={ver.eventos ? losEventos : []} medicion={medir.activo ? { a: medir.a, b: medir.b, m: medida } : null}
        onToque={medir.activo ? tocar : null} />
      {medir.activo && (
        <div role="status" aria-live="polite"
          className="mt-2 rounded-lg border border-rendi-accent/30 bg-rendi-accent/10 px-3 py-2 text-[12.5px] text-ink-1 leading-relaxed">
          {!medir.a && 'Tocá un día del gráfico para empezar a medir.'}
          {medir.a && !medir.b && `Desde el ${fechaCorta(medir.a)}. Ahora tocá el otro día.`}
          {medida && (
            <>
              <b className={`font-semibold tabular ${medida.dias === 0 ? 'text-ink-0' : medida.pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{textoMedicion(medida)}</b>
              {medida.dias > 0 && <span className="tabular">{`: del ${fechaCorta(medida.desde)} (${fmtPrecio(medida.precioDesde, moneda)}) al ${fechaCorta(medida.hasta)} (${fmtPrecio(medida.precioHasta, moneda)}), de cierre a cierre. `}</span>}
              Tocá otro día para medir de nuevo.
            </>
          )}
        </div>
      )}
      {rango === 'tuyo' && !ventana && primera && primera < actual.puntos[0].d && (
        <p className="text-[11.5px] text-ink-2 mt-1">Lo tenés desde el {fechaCorta(primera)}; el gráfico empieza el {fechaCorta(actual.puntos[0].d)}, que es lo que hay guardado.</p>
      )}
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
        {puntos.some(p => p.v > 0) && (
          <Chip activo={ver.vol} onClick={() => alternar('vol')} barras>Volumen</Chip>
        )}
        {promedio != null && (
          <Chip activo={ver.prom} onClick={() => alternar('prom')} color={COLOR.promedio} punteado>Tu precio promedio</Chip>
        )}
        {marcasEnVista.length > 0 && (
          <Chip activo={ver.marcas} onClick={() => alternar('marcas')} puntos>Tus compras y ventas</Chip>
        )}
        {losEventos.length > 0 && (
          <Chip activo={ver.eventos} onClick={() => alternar('eventos')} letras>Balances y dividendos</Chip>
        )}
        <Chip activo={medir.activo} onClick={() => setMedir(m => ({ activo: !m.activo, a: null, b: null }))} regla>
          Medir entre dos puntos
        </Chip>
        {actual.fibonacci && (
          <Chip activo={ver.fib} onClick={() => {
            // Al prenderlo, el gráfico se acerca al tramo medido (si se ve chico).
            const v2 = !ver.fib && ventanaDelTramo(actual.puntos, actual.fibonacci, nVista)
            if (v2) setVentana(v2)
            alternar('fib')
          }} color={COLOR_FIB}>Fibonacci</Chip>
        )}
      </div>

      <div className={`mt-4 grid grid-cols-1 sm:grid-cols-2 gap-2 ${grande ? 'xl:grid-cols-3' : ''}`}>
        {ver.fib && actual.fibonacci && (
          <TarjetaFibonacci fib={actual.fibonacci} precio={(x) => fmtPrecio(x, moneda)} fecha={fechaCorta} />
        )}
        {lista.map(t => <Tarjeta key={t.id} t={t} />)}
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

      {cuanto.length > 0 && (
        <section aria-label="Cuánto se mueve este papel" className="mt-5">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 mb-2">
            <h3 className="text-[14px] font-semibold text-ink-0">Cuánto se mueve este papel</h3>
            <span className="text-[12px] text-ink-2">
              {periodoDeMovimiento(actual.movimiento)}, en {moneda === 'usd' ? 'dólares' : 'pesos'}
            </span>
          </div>
          <div className={`grid grid-cols-1 sm:grid-cols-2 gap-2 ${grande ? 'xl:grid-cols-4' : ''}`}>
            {cuanto.map(t => <Tarjeta key={t.id} t={t} />)}
          </div>
          <p className="text-[11.5px] text-ink-2 mt-2 leading-relaxed">
            Es lo que pasó, de cierre a cierre: no dice cuánto se va a mover de acá en adelante.
          </p>
        </section>
      )}

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

// «Últimos 2 años» o, si hay menos guardado, desde cuándo.
function periodoDeMovimiento(m) {
  if (!m?.desde || !m?.hasta) return ''
  const dias = (Date.parse(m.hasta) - Date.parse(m.desde)) / 86400000
  return dias >= 700 ? 'Últimos 2 años' : `Desde el ${fechaCorta(m.desde)}`
}

function Marco({ moneda, setMoneda, rango, setRango, tipo, setTipo, conPesos = true, grande = false, setGrande, conTuyo = false, children }) {
  // Agrandado = la misma sección, fija sobre toda la pantalla (no es otra vista:
  // mismos datos, mismos botones; R6).
  return (
    <section aria-label="Análisis técnico" role={grande ? 'dialog' : undefined} aria-modal={grande || undefined}
      className={grande ? 'fixed inset-0 z-[70] overflow-y-auto bg-bg-0 px-3 py-3 sm:px-6 sm:py-5' : 'mb-5'}>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <div className="text-[12.5px] text-ink-2 font-medium">Análisis técnico</div>
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
            opciones={[...RANGOS.map(r => [r.id, r.label]), ...(conTuyo ? [['tuyo', 'Desde que lo tenés']] : [])]} />
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

function Chip({ activo, fijo, onClick, color, grueso, punteado, puntos, barras, letras, regla, children }) {
  // `puntos`: la muestra es un punto verde y uno rojo (compras/ventas, o velas que suben/bajan).
  // `barras`: tres barritas (el volumen). `letras`: la «B» y la «D» de balances y
  // dividendos. `regla`: el ícono de medir.
  const muestra = letras ? (
    <span className="inline-flex gap-0.5" aria-hidden="true">
      <Letra tipo="balance" /><Letra tipo="dividendo" />
    </span>
  ) : regla ? (
    <Ruler size={13} aria-hidden="true" />
  ) : barras ? (
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
  // Las líneas apagadas se ven tenues (no se dibujan). Medir es una herramienta,
  // no una línea: apagado se ve como un botón común y prendido, resaltado.
  const clase = `inline-flex items-center gap-1.5 min-h-10 sm:min-h-[30px] px-3 sm:px-2.5 rounded-full border text-[12px] transition-colors ${
    regla ? (activo ? 'border-rendi-accent/60 bg-rendi-accent/15 text-ink-0' : 'border-line-2 text-ink-1')
      : activo ? 'border-line-2 bg-bg-2/60 text-ink-1' : 'border-line text-ink-3 opacity-60'}`
  if (fijo) return <span className={clase}>{muestra}{children}</span>
  return (
    <button type="button" onClick={onClick} aria-pressed={!!activo} className={`${clase} hover:text-ink-0`}>
      {muestra}{children}
    </button>
  )
}

// La «B» de un balance o la «D» de un dividendo: un círculo con la letra.
function Letra({ tipo, grande: g = false }) {
  return (
    <span className={`inline-flex items-center justify-center rounded-full font-bold leading-none ${g ? 'w-[18px] h-[18px] text-[10px]' : 'w-3.5 h-3.5 text-[9px]'}`}
      style={{ background: tipo === 'balance' ? COLOR.balance : COLOR.dividendo, color: v('bg-0') }}>
      {tipo === 'balance' ? 'B' : 'D'}
    </span>
  )
}

function Tarjeta({ t }) {
  const tono = t.tono === 'pos' ? 'text-rendi-pos' : t.tono === 'neg' ? 'text-rendi-neg' : 'text-ink-0'
  return (
    <div className="rounded-lg border border-line/60 bg-bg-2/40 px-3.5 py-3">
      <div className="text-[12px] text-ink-2 font-medium">{t.titulo}</div>
      <div className={`text-[15px] font-semibold mt-0.5 tabular ${tono}`}>{t.veredicto}</div>
      {t.rsi != null && <BarraRsi rsi={t.rsi} />}
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

function Grafico({ puntos, moneda, promedio, marcas: lista, ver, tipo = 'linea', grande = false, fibonacci = null, onZoom, onMover, onFechasAuto, fechasAMano = false, reinicioPrecio, eventos = [], medicion = null, onToque = null }) {
  const conVelas = tipo === 'velas'
  const ref = useRef(null)
  const arrastre = useRef(null)
  // Un toque del dedo (para medir): dónde empezó y si se movió. El navegador
  // después del dedo manda también un click de mouse: se ignora un rato.
  const dedo = useRef(null)
  const ultimoDedo = useRef(0)
  // El balance o dividendo que se está mirando (su globo): la clave del grupo.
  const [eventoSel, setEventoSel] = useState(null)
  const conMouse = useRef(false)
  // El ancho del gráfico en pantalla: con él se sabe qué marcas se pisarían.
  const [ancho, setAncho] = useState(1000)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    // Se mide ya (con la página en segundo plano el aviso de abajo no llega
    // hasta que vuelve a verse) y después se sigue cada cambio de tamaño.
    const w = el.getBoundingClientRect?.().width
    if (w > 0) setAncho(w)
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([e]) => { if (e?.contentRect?.width) setAncho(e.contentRect.width) })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
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
    const x = (i) => (puntos.length > 1 ? (i / (puntos.length - 1)) * W : W / 2)
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
    // Las velas: el ancho de cada una es el 65 % de su lugar, la mecha va del
    // mínimo al máximo y el cuerpo de la apertura al cierre.
    const ancho = Math.max((W / Math.max(puntos.length, 1)) * 0.65, 1)
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
    const anchoVol = Math.max((W / Math.max(puntos.length, 1)) * 0.65, 1)
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
      path: { c, s50: linea('s50'), s200: linea('s200') },
      area: c ? `${c}L${x(puntos.length - 1).toFixed(1)},${H}L0,${H}Z` : '',
    }
  }, [puntos, promedio, ver.s50, ver.s200, ver.vol, conVelas, fibonacci, precioMano])

  const rsiPath = useMemo(() => {
    let d = '', abierto = false
    puntos.forEach((p, i) => {
      if (p.rsi == null) { abierto = false; return }
      const xx = puntos.length > 1 ? (i / (puntos.length - 1)) * W : W / 2
      d += `${abierto ? 'L' : 'M'}${xx.toFixed(1)},${(H_RSI - (p.rsi / 100) * H_RSI).toFixed(1)}`
      abierto = true
    })
    return d
  }, [puntos])

  const pctX = (i) => (puntos.length > 1 ? (i / (puntos.length - 1)) * 100 : 50)
  const pctY = (val) => (escalaY(val) / H) * 100
  const desde = puntos[0]?.d
  const visibles = lista
    .filter(m => m.fecha >= desde)
    .map(m => ({ ...m, i: indiceDeFecha(puntos, m.fecha) }))
    .filter(m => m.i != null && pctY(puntos[m.i].c) >= 0 && pctY(puntos[m.i].c) <= 100)

  // El mouse o el dedo: el punto más cercano en el tiempo.
  function indiceEn(clientX) {
    const r = ref.current?.getBoundingClientRect()
    if (!r || !puntos.length) return null
    const i = Math.round(((clientX - r.left) / r.width) * (puntos.length - 1))
    return Math.max(0, Math.min(puntos.length - 1, i))
  }
  function mover(clientX) {
    const i = indiceEn(clientX)
    if (i != null) setHover(i)
  }

  // Balances y dividendos dentro de lo que se ve, con su lugar. Si hay de los
  // dos, cada tipo va en su renglón (en el celular un balance y un dividendo
  // separados por diez días caen uno encima del otro). Y las del mismo tipo que
  // en la pantalla quedarían a menos de MARCA_PX se juntan en UNA marca con
  // cuántas son (Galicia paga todos los meses: en el celular eran doce «D»
  // pisadas); su globo las lista.
  const hasta = puntos[puntos.length - 1]?.d
  const evVisibles = eventos
    .filter(e => e.fecha >= (puntos[0]?.d || '') && e.fecha <= (hasta || ''))
    .map(e => ({ ...e, i: indiceDeFecha(puntos, e.fecha) }))
    .filter(e => e.i != null)
  const grupos = []
  for (const tipo of ['balance', 'dividendo']) {
    let actual = null
    for (const e of evVisibles.filter(x => x.tipo === tipo)) {
      const x = pctX(e.i)
      if (actual && ((x - actual.x0) / 100) * ancho < MARCA_PX) {
        actual.items.push(e)
        actual.x = (actual.x0 + x) / 2
      } else {
        actual = { clave: `${tipo}|${e.fecha}`, tipo, x0: x, x, items: [e] }
        grupos.push(actual)
      }
    }
  }
  const dosRenglones = grupos.some(g => g.tipo === 'balance') && grupos.some(g => g.tipo === 'dividendo')
  const grupoSel = grupos.find(g => g.clave === eventoSel) || null

  // La medición, dibujada: cada día tocado en su punto (en velas semanales, en
  // la semana que lo contiene) y a la altura de SU cierre.
  const lugar = (fecha) => {
    if (!fecha || !puntos.length) return null
    if (fecha < puntos[0].d) return { x: 0, fuera: true }
    const i = indiceDeFecha(puntos, fecha)
    return i == null ? null : { x: pctX(i), fuera: false }
  }
  const mA = medicion ? lugar(medicion.m ? medicion.m.desde : medicion.a) : null
  const mB = medicion?.m ? lugar(medicion.m.hasta) : null
  const yDe = (precio) => (precio != null ? Math.min(100, Math.max(0, pctY(precio))) : null)
  const precioA = medicion?.m ? medicion.m.precioDesde : (medicion?.a ? puntos[indiceDeFecha(puntos, medicion.a) ?? 0]?.c : null)
  const precioB = medicion?.m ? medicion.m.precioHasta : null
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
          onMouseDown={e => { arrastre.current = { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY } }}
          onMouseUp={e => {
            // Un click sin arrastrar, en el modo medir, marca ese día.
            const a = arrastre.current
            arrastre.current = null
            if (!a || !onToque || Date.now() - ultimoDedo.current < 800) return
            if (Math.abs(e.clientX - a.x0) < 5 && Math.abs(e.clientY - a.y0) < 5) {
              const i = indiceEn(e.clientX)
              if (i != null) onToque(i)
            }
          }}
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
          onTouchStart={e => {
            const t = e.touches[0]
            dedo.current = { x0: t.clientX, y0: t.clientY, x: t.clientX, quieto: e.touches.length === 1 }
            mover(t.clientX)
          }}
          onTouchMove={e => {
            const t = e.touches[0], d = dedo.current
            if (d) {
              d.x = t.clientX
              if (Math.abs(t.clientX - d.x0) > 10 || Math.abs(t.clientY - d.y0) > 10) d.quieto = false
            }
            mover(t.clientX)
          }}
          onTouchEnd={e => {
            // Un toque quieto (sin deslizar) en el modo medir marca ese día.
            const d = dedo.current
            dedo.current = null
            setHover(null)
            if (d?.quieto && onToque) {
              const i = indiceEn(d.x)
              if (i != null) { ultimoDedo.current = Date.now(); onToque(i); if (e.cancelable) e.preventDefault() }
            }
          }}
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
            {/* Una raya tenue por balance; la del que se mira, marcada. */}
            {grupos.flatMap(g => g.items.filter(() => g.tipo === 'balance' || g === grupoSel).map(e => (
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
              style={{ left: '100%', top: `${pctY(ultimo.c)}%`, background: COLOR.precio }} />
          )}
          {[[mA, precioA], [mB, precioB]].map(([l, precio], k) => l && !l.fuera && precio != null && (
            <span key={`m${k}`} aria-hidden="true" className="pointer-events-none absolute w-3 h-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg-1"
              style={{ left: `${l.x}%`, top: `${yDe(precio)}%`, background: COLOR.medir }} />
          ))}
          {mA && mB && medicion.m.dias > 0 && (
            <span aria-hidden="true"
              className={`pointer-events-none absolute z-10 top-1 rounded border border-rendi-accent/40 bg-bg-raised/95 px-2 py-1 text-[12px] font-semibold tabular whitespace-nowrap shadow-sm ${(mA.x + mB.x) / 2 > 60 ? '-translate-x-full' : (mA.x + mB.x) / 2 < 40 ? '' : '-translate-x-1/2'} ${medicion.m.pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}
              style={{ left: `${(mA.x + mB.x) / 2}%` }}>
              {textoMedicion(medicion.m)}
            </span>
          )}
          {ph && (
            <>
              <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 w-px bg-ink-2/50" style={{ left: `${pctX(hover)}%` }} />
              <span aria-hidden="true" className="pointer-events-none absolute w-2.5 h-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg-1"
                style={{ left: `${pctX(hover)}%`, top: `${pctY(ph.c)}%`, background: COLOR.precio }} />
              {/* El globo va pegado al punto que se mira (abajo a la derecha;
                  del otro lado si no entra), chico y de un renglón por dato:
                  arriba y fijo tapaba casi todo el gráfico (Nico, 22/10). */}
              <div className={`pointer-events-none absolute z-10 rounded border border-line-2 bg-bg-raised/95 px-2 py-1.5 text-[11px] leading-tight shadow-sm tabular whitespace-nowrap ${pctX(hover) > 62 ? '-translate-x-[calc(100%+12px)]' : 'translate-x-3'} ${pctY(ph.c) > 55 ? '-translate-y-[calc(100%+12px)]' : 'translate-y-3'}`}
                style={{ left: `${pctX(hover)}%`, top: `${pctY(ph.c)}%` }}>
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
                  {ph.rsi != null && <Fila k="RSI" v={Math.round(ph.rsi)} />}
                  {ver.vol && ph.v > 0 && <Fila k="Vol." v={fmtVolumen(ph.v)} />}
                </div>
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

      {/* Balances («B») y dividendos («D»), sobre el eje de fechas. Cada uno es
          un botón: con el mouse encima, con el foco o con un toque, el globo
          dice qué fue y cuánto se movió el precio. */}
      {grupos.length > 0 && (
        <div className={`relative mr-[72px] mt-1 ${dosRenglones ? 'h-10' : 'h-5'}`} role="group" aria-label="Balances y dividendos">
          {grupos.map(g => {
            const t = textoGrupo(g.items)
            return (
              <button key={g.clave} type="button" aria-label={`${t.titulo}. ${t.lineas.join(' ')}`}
                aria-expanded={g.clave === eventoSel}
                className={`absolute -translate-x-1/2 inline-flex items-center p-0.5 rounded-full focus-visible:outline focus-visible:outline-2 focus-visible:outline-rendi-accent ${dosRenglones && g.tipo === 'dividendo' ? 'top-5' : 'top-0'}`}
                style={{ left: `${g.x}%` }}
                onPointerEnter={ev => { if (ev.pointerType === 'mouse') { conMouse.current = true; setEventoSel(g.clave) } }}
                onPointerLeave={ev => { if (ev.pointerType === 'mouse') { conMouse.current = false; setEventoSel(null) } }}
                onFocus={() => setEventoSel(g.clave)} onBlur={() => setEventoSel(null)}
                onClick={() => setEventoSel(s => (s === g.clave && !conMouse.current ? null : g.clave))}>
                <Letra tipo={g.tipo} grande />
                {g.items.length > 1 && <span className="ml-0.5 text-[10px] font-semibold text-ink-1 tabular">{g.items.length}</span>}
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
    </div>
  )
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
