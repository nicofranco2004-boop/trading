// LecturaTecnica — el gráfico técnico y su lectura en la ficha del activo.
// ════════════════════════════════════════════════════════════════════════════
// Gráfico de precio con las medias de 50 y 200 días, tu precio promedio y tus
// compras y ventas; la fuerza del movimiento (RSI) abajo; y tarjetas en
// castellano. Se mide en DÓLARES por defecto: un CEDEAR en pesos sube con el
// dólar aunque la empresa no se mueva (ver backend/tecnico.py).
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
import AssetMiniChart from '../home/AssetMiniChart'
import { BotonAvisame, useAvisosTecnicos, senalDeTarjeta } from '../alerts/AvisameTecnico'
import { api } from '../../utils/api'
import {
  RANGOS, RSI_CASTIGADO, RSI_ESTIRADO, tarjetas, lineaPromedio, marcas, puntosEnDias, variacionDeHoy,
  indiceDeFecha, tendenciasDistintas, velaCompleta, velasSemanales, zoomVentana, moverVentana,
} from '../../utils/tecnico'

const v = (t) => `rgb(var(--${t}))`
const COLOR = {
  precio: v('ink-0'),
  media200: v('rendi-accent'),
  // Naranja categórico, no celeste: con el azul de la media de 200 tenían la
  // misma luminosidad en modo claro y para un daltónico eran la misma línea.
  media50: v('cat-orange'),
  promedio: v('ink-2'),
}
const W = 1000
const H = 260
const H_RSI = 64
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
}) {
  const [moneda, setMoneda] = useState('usd')
  const [rango, setRango] = useState('1a')
  const [datos, setDatos] = useState({ usd: undefined, ars: undefined })
  // Qué líneas se ven: la leyenda prende y apaga cada una.
  const [ver, setVer] = useState({ s200: true, s50: true, prom: true, marcas: true })
  const [tipo, setTipoEstado] = useState(tipoGuardado)
  const setTipo = (t) => { setTipoEstado(t); guardarTipo(t) }
  // Zoom con la rueda y arrastre: qué ruedas se ven ({ n: cuántas, fin: hasta
  // cuál, sin incluirla }). null = el rango del botón (3M/1A/2A).
  const [ventana, setVentana] = useState(null)
  // Velas diarias siempre; semanales sólo si se eligen (para mirar el panorama
  // de 2 años). El análisis (Fibonacci, giros) se hace sobre las diarias.
  const [intervalo, setIntervalo] = useState('dia')
  const elegirRango = (r) => { setRango(r); setVentana(null) }
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
      tipo={tipo} setTipo={setTipo} conPesos={conPesos}>{hijos}</Marco>
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
  const nVista = Math.min(ventana?.n ?? puntosEnDias(actual.puntos, RANGOS.find(r => r.id === rango)?.dias || 365), total)
  const finVista = Math.min(ventana?.fin ?? total, total)
  const diarios = actual.puntos.slice(Math.max(0, finVista - nVista), finVista)
  const semanales = tipo === 'velas' && intervalo === 'semana'
  const puntos = semanales ? velasSemanales(diarios) : diarios
  const vista = { n: nVista, fin: finVista, total }
  const zoom = (factor, f) => { const v2 = zoomVentana(vista, factor, f); if (v2) setVentana(v2) }
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
      <Grafico puntos={puntos} moneda={moneda} promedio={ver.prom ? promedio : null}
        marcas={ver.marcas ? misMarcas : []} ver={ver} tipo={tipo}
        onZoom={zoom} onMover={mover} />
      <p className="text-[11.5px] text-ink-2 mt-1">
        {semanales && 'Cada vela es una semana. '}
        {tipo === 'velas' && !semanales && diarios.length > 300 && 'Cada vela es un día: acercá con la ruedita o pasá a velas semanales. '}
        <span className="hidden sm:inline">Con la ruedita del mouse acercás o alejás. Arrastrá para ir más atrás o más adelante.</span>
      </p>

      <div className="flex flex-wrap gap-1.5 mt-3" role="group" aria-label="Qué líneas mostrar">
        {tipo === 'velas'
          ? <Chip activo fijo puntos>Velas: subió · bajó</Chip>
          : <Chip activo fijo color={COLOR.precio}>Precio</Chip>}
        <Chip activo={ver.s200} onClick={() => alternar('s200')} color={COLOR.media200} grueso>Promedio 200 días</Chip>
        <Chip activo={ver.s50} onClick={() => alternar('s50')} color={COLOR.media50}>Promedio 50 días</Chip>
        {promedio != null && (
          <Chip activo={ver.prom} onClick={() => alternar('prom')} color={COLOR.promedio} punteado>Tu precio promedio</Chip>
        )}
        {marcasEnVista.length > 0 && (
          <Chip activo={ver.marcas} onClick={() => alternar('marcas')} puntos>Tus compras y ventas</Chip>
        )}
      </div>

      <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-2">
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

function Marco({ moneda, setMoneda, rango, setRango, tipo, setTipo, conPesos = true, children }) {
  return (
    <section className="mb-5" aria-label="Análisis técnico">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <div className="text-[12.5px] text-ink-2 font-medium">Análisis técnico</div>
        <div className="flex flex-wrap items-center gap-2">
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

function Chip({ activo, fijo, onClick, color, grueso, punteado, puntos, children }) {
  // `puntos`: la muestra es un punto verde y uno rojo (compras/ventas, o velas que suben/bajan).
  const muestra = puntos ? (
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

function Grafico({ puntos, moneda, promedio, marcas: lista, ver, tipo = 'linea', onZoom, onMover }) {
  const conVelas = tipo === 'velas'
  const ref = useRef(null)
  const arrastre = useRef(null)
  // La rueda tiene que frenar el scroll de la página mientras está sobre el
  // gráfico: eso sólo se puede con un escucha "no pasivo" (el onWheel de React
  // es pasivo y no puede frenarlo).
  const zoomRef = useRef(onZoom)
  zoomRef.current = onZoom
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const rueda = (e) => {
      if (!zoomRef.current) return
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width))
      zoomRef.current(e.deltaY > 0 ? 1.15 : 1 / 1.15, f)
    }
    el.addEventListener('wheel', rueda, { passive: false })
    return () => el.removeEventListener('wheel', rueda)
  }, [])
  const gid = useId().replace(/:/g, '')
  const [hover, setHover] = useState(null)

  const { escalaY, path, area, min, max, velas, promFuera } = useMemo(() => {
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
    return {
      escalaY: y, min: lo, max: hi, velas, promFuera: fuera,
      path: { c, s50: linea('s50'), s200: linea('s200') },
      area: c ? `${c}L${x(puntos.length - 1).toFixed(1)},${H}L0,${H}Z` : '',
    }
  }, [puntos, promedio, ver.s50, ver.s200, conVelas])

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
    .filter(m => m.i != null)

  // El mouse o el dedo: el punto más cercano en el tiempo.
  function mover(clientX) {
    const r = ref.current?.getBoundingClientRect()
    if (!r || !puntos.length) return
    const i = Math.round(((clientX - r.left) / r.width) * (puntos.length - 1))
    setHover(Math.max(0, Math.min(puntos.length - 1, i)))
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
        <div ref={ref} className="relative mr-[72px] h-56 sm:h-64 select-none touch-pan-y cursor-crosshair"
          onMouseDown={e => { arrastre.current = e.clientX }}
          onMouseUp={() => { arrastre.current = null }}
          onMouseMove={e => {
            if (arrastre.current != null && onMover) {
              const r = ref.current.getBoundingClientRect()
              const frac = (e.clientX - arrastre.current) / r.width
              if (Math.abs(frac) * puntos.length >= 1) { onMover(frac); arrastre.current = e.clientX }
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

        {/* Columna de precios: la grilla, tu precio y el último precio. */}
        <div className="absolute inset-y-0 right-0 w-[68px] pointer-events-none">
          {ticks.map((t, k) => !cerca(t) && (
            <span key={k} className="absolute left-1.5 -translate-y-1/2 text-[11px] text-ink-2 tabular whitespace-nowrap"
              style={{ top: `${pctY(t)}%` }}>{fmtPrecio(t, moneda).replace(/^US\$ /, '')}</span>
          ))}
          {promVisible && !promCerca && (
            <span className="absolute left-0 -translate-y-1/2 rounded border border-dashed border-ink-3 bg-bg-1 px-1 text-[10.5px] text-ink-1 tabular whitespace-nowrap"
              style={{ top: `${pctY(promedio)}%` }}>Tu precio</span>
          )}
          {promFuera && (
            <span className={`absolute left-0 rounded border border-dashed border-ink-3 bg-bg-1 px-1 text-[10.5px] text-ink-1 tabular whitespace-nowrap ${promFuera === 'abajo' ? 'bottom-0' : 'top-0'}`}
              title={`Tu precio: ${fmtPrecio(promedio, moneda)}, fuera de este gráfico`}>
              {promFuera === 'abajo' ? '↓' : '↑'} Tu precio
            </span>
          )}
          {ultimo && (
            <span className="absolute left-0 -translate-y-1/2 rounded px-1.5 py-0.5 text-[11px] font-semibold tabular whitespace-nowrap"
              style={{ top: `${pctY(ultimo.c)}%`, background: COLOR.precio, color: v('bg-0') }}>
              {fmtPrecio(ultimo.c, moneda).replace(/^US\$ /, '')}
            </span>
          )}
        </div>
      </div>

      {/* Meses. */}
      <div className="relative mr-[72px] h-5 mt-1.5 text-[11px] text-ink-2">
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
          <div className="relative mr-[72px] h-14">
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
