// MapaCartera — el mapa de calor de TU cartera, en el Dashboard (pieza 8).
// ═══════════════════════════════════════════════════════════════════════════
// Un cuadro por activo que tenés (más efectivo y plazos fijos). El tamaño es lo
// que pesa en tu plata; el color, según «Color por»: cuánto se movió hoy, su
// tendencia de fondo o cuánto está arriba o abajo de tu precio promedio.
// Cada cuadro abre la ficha del activo.
//
// Los números no se cuentan acá (ver utils/mapaCartera.js):
//   · peso y tendencia: POST /api/tecnico/lista, el MISMO pedido de Tu lista,
//     sin watchlist (`activos: []`). Este componente lo hace solo.
//   · hoy y contra tu promedio: los lotes que le pasa el Dashboard (`lotes`),
//     con la «Var. día» de la Cartera y el resultado no realizado del Dashboard.
//   · el «Hoy tu cartera» de arriba: el «Hoy» del Dashboard (`encabezado`), el
//     de su tarjeta. No se suma de los cuadros: es otra cuenta (contra la foto
//     de ayer, con efectivo y dólar adentro) y se mide aparte (`sumaDeHoy`).
//
// Compu y celular en el mismo archivo (frontend/CLAUDE.md R6): el mapa mide su
// ancho y, si un cuadro queda demasiado chico para tocarlo, ese activo baja a
// la lista de abajo del mapa en vez de dibujarse como una astilla.
// «Ocultar saldos»: no se ven montos ni cuánto pesa cada uno.

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Panel from './Panel'
import { api } from '../utils/api'
import { indexarLecturas } from '../utils/radiografia'
import { textoDelPeso } from '../utils/listaTecnica'
import { squarify } from '../utils/squarify'
import { urlDeActivo } from '../utils/buscadorRapido'
import { pctSigned } from '../utils/format'
import { polarityLegend, CORTES_DIA, CORTES_PROMEDIO } from '../utils/polarityScale'
import {
  MODOS, QUE_ES_EL_COLOR, cuadrosDelMapa, colorDelCuadro, losExtremosDeHoy,
} from '../utils/mapaCartera'

const GUARDADO = 'rendi_mapa_color'
// Lado mínimo de un cuadro para que se pueda tocar (celular) o leer (compu).
const LADO_MINIMO = { movil: 52, compu: 40 }
const ANCHO_MOVIL = 640
// El gris de «sin lectura» / «sin dato»: el mismo que pinta colorDelCuadro.
const SIN_DATO = colorDelCuadro({ fondo: { id: 'sin' } }, 'tendencia').bg

function modoGuardado() {
  try {
    const m = localStorage.getItem(GUARDADO)
    return MODOS.some(x => x.id === m) ? m : 'hoy'
  } catch { return 'hoy' }
}

/** Cuánto mide el mapa: el ancho del contenedor, y un alto que en el celular es
 *  más alto que ancho (los cuadros se apilan) y en la compu, apaisado. */
function useAncho() {
  const ref = useRef(null)
  const [ancho, setAncho] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return undefined
    setAncho(Math.round(el.getBoundingClientRect().width))
    if (typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(([e]) => setAncho(Math.round(e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, ancho]
}

/** Los cuadros que entran en el mapa (con x, y, w, h) y los que bajan a la
 *  lista porque quedarían más chicos que `minimo` de lado. Los tamaños de los
 *  que quedan siguen siendo proporcionales entre sí. */
export function acomodar(cuadros, ancho, alto, minimo) {
  let enMapa = cuadros.filter(c => c.peso > 0)
  const abajo = []
  let laid = []
  while (enMapa.length) {
    laid = squarify(enMapa, ancho, alto, c => c.peso)
    if (enMapa.length === 1 || !laid.some(b => Math.min(b.w, b.h) < minimo)) break
    abajo.unshift(enMapa[enMapa.length - 1])
    enMapa = enMapa.slice(0, -1)
  }
  return { laid, abajo }
}

function valorDelModo(c, modo) {
  if (modo === 'tendencia') return c.fondo?.palabra || 'Sin lectura'
  if (modo === 'promedio') return c.promedio ? pctSigned(c.promedio.pct) : 'sin dato'
  if (c.hoy) return pctSigned(c.hoy.pct)
  return c.tipo === 'activo' ? 'sin dato' : 'no cotiza'
}

function Leyenda({ modo }) {
  if (modo === 'tendencia') {
    const items = [
      { key: 'a', bg: colorDelCuadro({ fondo: { id: 'alcista' } }, 'tendencia').bg, txt: 'Alcista' },
      { key: 'b', bg: colorDelCuadro({ fondo: { id: 'bajista' } }, 'tendencia').bg, txt: 'Bajista' },
      { key: 's', bg: SIN_DATO, txt: 'Sin lectura' },
    ]
    return (
      <div className="flex items-center gap-3 text-[12px] text-ink-2">
        {items.map(i => (
          <span key={i.key} className="inline-flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-xs" style={{ background: i.bg }} />{i.txt}
          </span>
        ))}
      </div>
    )
  }
  const cortes = modo === 'promedio' ? CORTES_PROMEDIO : CORTES_DIA
  const tope = cortes.pasos[cortes.pasos.length - 1]
  return (
    <div className="flex items-center gap-2 text-[12px] text-ink-2 tabular">
      <span>−{tope}%</span>
      <span className="inline-flex rounded-xs overflow-hidden" aria-hidden="true">
        {polarityLegend().map(p => <span key={p.key} className="inline-block w-5 h-2" style={{ background: p.bg }} />)}
      </span>
      <span>+{tope}%</span>
      <span className="inline-flex items-center gap-1.5 ml-2">
        <span className="inline-block w-3 h-3 rounded-xs" style={{ background: SIN_DATO }} />sin dato
      </span>
    </div>
  )
}

function Globo({ b, ancho, alto, oculto, fmtMonto }) {
  const cx = b.x + b.w / 2
  const [left, dx] = cx < ancho * 0.25 ? [b.x, '0%'] : cx > ancho * 0.75 ? [b.x + b.w, '-100%'] : [cx, '-50%']
  const arriba = b.y > alto * 0.18
  const nombre = b.detalle ? `${b.nombre} · ${b.detalle}` : b.nombre
  return (
    <div
      className="pointer-events-none absolute z-10 rounded-lg border border-line-2 bg-bg-raised px-3 py-2 text-[12px] shadow-lg w-max max-w-[260px]"
      style={{ left, top: arriba ? b.y : b.y + b.h, transform: `translate(${dx}, ${arriba ? 'calc(-100% - 6px)' : '6px'})` }}
    >
      <div className="font-semibold text-ink-0">{nombre}</div>
      {!oculto && <div className="text-ink-2">Pesa {textoDelPeso(b.peso * 100)} de tu plata</div>}
      <div className="text-ink-1 tabular">
        Hoy: {b.hoy ? `${pctSigned(b.hoy.pct)}${oculto ? '' : ` (${fmtMonto(b.hoy.usd)})`}` : (b.tipo === 'activo' ? 'sin cierre anterior para comparar' : 'no cotiza')}
      </div>
      {b.tipo === 'activo' && (
        <div className="text-ink-1 tabular">Contra tu promedio de compra: {b.promedio ? pctSigned(b.promedio.pct) : 'sin dato'}</div>
      )}
      <div className="text-ink-2 mt-0.5">Tendencia: {b.fondo?.palabra}. {b.fondo?.motivo}</div>
    </div>
  )
}

/**
 * @param lotes       [{ p, dia, valueUsd, pnlUsd }] — ver cuadrosDelMapa
 * @param encabezado  { label, pct, usd } del «Hoy» del Dashboard, o null
 * @param fmtMonto    usd → texto con signo, en la moneda que se mira
 * @param oculto      «Ocultar saldos»
 * @param recarga     cambia cuando cambió la cartera: vuelve a pedir pesos
 */
export default function MapaCartera({ lotes = [], encabezado = null, fmtMonto, oculto = false, recarga = 0 }) {
  const navigate = useNavigate()
  const [modo, setModoEstado] = useState(modoGuardado)
  const setModo = (m) => {
    setModoEstado(m)
    try { localStorage.setItem(GUARDADO, m) } catch { /* sin guardar: sólo esta vez */ }
  }
  const [datos, setDatos] = useState(null)   // { tenencias, sinMedir, indice } | { error }
  const [encima, setEncima] = useState(null)
  const [refMapa, ancho] = useAncho()

  useEffect(() => {
    let vivo = true
    api.post('/tecnico/lista', { activos: [] })
      .then(r => {
        if (vivo) setDatos({ tenencias: r?.tenencias || [], sinMedir: r?.sin_medir || null, indice: indexarLecturas(r?.lecturas || []) })
      })
      .catch(() => { if (vivo) setDatos({ error: true }) })
    return () => { vivo = false }
  }, [recarga])

  const cuadros = useMemo(
    () => (datos && !datos.error ? cuadrosDelMapa({ ...datos, lotes }) : []),
    [datos, lotes],
  )
  const movil = ancho > 0 && ancho < ANCHO_MOVIL
  const alto = ancho > 0 ? (movil ? Math.round(ancho * 1.15) : Math.max(300, Math.round(ancho * 0.42))) : 0
  const { laid, abajo } = useMemo(
    () => (ancho > 0 ? acomodar(cuadros, ancho, alto, movil ? LADO_MINIMO.movil : LADO_MINIMO.compu) : { laid: [], abajo: [] }),
    [cuadros, ancho, alto, movil],
  )
  const { sumo, resto } = useMemo(() => losExtremosDeHoy(cuadros), [cuadros])

  // Sin nada que mostrar (cartera vacía), el mapa no aparece.
  if (datos && !datos.error && cuadros.length === 0) return null

  const abrir = (c) => { if (c.ruta) navigate(urlDeActivo(c.ruta)) }
  const resaltado = encima ? laid.find(b => b.clave === encima) : null
  // Lo que lee un lector de pantalla (y las pruebas): nombre, el número del modo
  // y cuánto pesa.
  const etiquetaDe = (c) => `${c.nombre}${c.detalle ? ` ${c.detalle}` : ''}: ${valorDelModo(c, modo)}${oculto ? '' : `, pesa ${textoDelPeso(c.peso * 100)} de tu plata`}${c.ruta ? '. Abre su ficha' : ''}`
  const extremo = (c) => `${c.nombre}${c.detalle ? ` ${c.detalle}` : ''} (${oculto ? pctSigned(c.hoy.pct) : fmtMonto(c.hoy.usd)})`

  return (
    <Panel padding="lg" as="section" aria-label="Mapa de calor de tu cartera">
      <div className="flex flex-wrap items-end justify-between gap-3 mb-4">
        <div className="min-w-0">
          <h2 className="text-[18px] sm:text-[20px] font-semibold text-ink-0 leading-tight">
            {encabezado ? (
              <>
                {encabezado.label === 'Hoy' ? 'Hoy tu cartera' : `${encabezado.label}, tu cartera`}:{' '}
                <span className={`tabular ${encabezado.pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{pctSigned(encabezado.pct)}</span>
                {!oculto && <span className="tabular text-[15px] text-ink-1 font-medium"> ({fmtMonto(encabezado.usd)})</span>}
              </>
            ) : 'Tu cartera en un mapa'}
          </h2>
          <p className="text-[13px] text-ink-2 mt-1">
            El tamaño de cada cuadro es lo que pesa en tu cartera. {QUE_ES_EL_COLOR[modo]}
          </p>
        </div>
        <div className="flex flex-col gap-1.5 sm:items-end">
          <span className="text-[12px] text-ink-2 font-medium" id="mapa-color-por">Color por</span>
          <div role="radiogroup" aria-labelledby="mapa-color-por" className="inline-flex gap-0.5 bg-bg-0 border border-line rounded-lg p-0.5">
            {MODOS.map(m => (
              <button
                key={m.id}
                type="button"
                role="radio"
                aria-checked={modo === m.id}
                onClick={() => setModo(m.id)}
                className={`px-3 py-1.5 text-[13px] rounded transition-colors ${modo === m.id ? 'bg-bg-3 text-ink-0 font-semibold' : 'text-ink-2 hover:text-ink-0'}`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div ref={refMapa} data-mapa="" className="w-full">
        {!datos && <div className="rounded-lg bg-bg-2 esqueleto" style={{ height: alto || 300 }} />}
        {datos?.error && (
          <div className="text-[13px] text-ink-2 py-6">El mapa no está disponible ahora. Probá recargar en un rato.</div>
        )}
        {datos && !datos.error && ancho > 0 && (
          <div className="relative" style={{ height: alto }} onPointerLeave={() => setEncima(null)}>
            {laid.map(b => {
              const col = colorDelCuadro(b, modo)
              // Cuánto texto entra, por el tamaño del cuadro: nombre, número y
              // peso uno abajo del otro; en un cuadro bajo, nombre y número en un
              // renglón; en uno chico, sólo el nombre (el resto, en el globo).
              const texto = b.h >= 74 && b.w >= 72 ? 'completo' : b.h >= 34 && b.w >= 72 ? 'renglon' : 'nombre'
              const conPeso = !oculto && texto === 'completo'
              const Tag = b.ruta ? 'button' : 'div'
              const nombre = (
                <span className={`font-semibold truncate min-w-0 ${texto === 'nombre' ? 'text-[12px]' : 'text-[14px] sm:text-[15px]'}`}>
                  {b.nombre}{texto !== 'nombre' && b.detalle ? <span className="font-normal opacity-80"> {b.detalle}</span> : null}
                </span>
              )
              return (
                <Tag
                  key={b.clave}
                  type={b.ruta ? 'button' : undefined}
                  data-cuadro={b.clave}
                  onClick={b.ruta ? () => abrir(b) : undefined}
                  onPointerEnter={e => { if (e.pointerType === 'mouse') setEncima(b.clave) }}
                  aria-label={etiquetaDe(b)}
                  className={`absolute rounded-lg overflow-hidden text-left flex ${texto === 'renglon' ? 'flex-row items-center gap-2' : 'flex-col'} justify-between ${texto === 'completo' ? 'p-2 sm:p-3' : 'px-2 py-1'} ${b.ruta ? 'cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-data-violet' : ''} ${resaltado?.clave === b.clave ? 'ring-2 ring-ink-0/60 z-[1]' : ''}`}
                  style={{ left: b.x + 1.5, top: b.y + 1.5, width: Math.max(b.w - 3, 0), height: Math.max(b.h - 3, 0), background: col.bg, color: col.ink }}
                >
                  {nombre}
                  {texto === 'renglon' && (
                    <span className="font-semibold tabular text-[14px] shrink-0">{valorDelModo(b, modo)}</span>
                  )}
                  {texto === 'completo' && (
                    <span className="min-w-0">
                      <span className={`block font-semibold tabular truncate ${b.w >= 120 && b.h >= 90 ? 'text-[20px]' : 'text-[15px]'}`}>{valorDelModo(b, modo)}</span>
                      {conPeso && <span className="block text-[12px] tabular opacity-85 truncate">{textoDelPeso(b.peso * 100)}</span>}
                    </span>
                  )}
                </Tag>
              )
            })}
            {resaltado && <Globo b={resaltado} ancho={ancho} alto={alto} oculto={oculto} fmtMonto={fmtMonto} />}
          </div>
        )}
      </div>

      {abajo.length > 0 && (
        <div className="mt-3">
          <div className="text-[12px] text-ink-2 font-medium mb-1.5">Muy chicos para el mapa:</div>
          <div className="flex flex-wrap gap-1.5">
            {abajo.map(c => {
              const col = colorDelCuadro(c, modo)
              const Tag = c.ruta ? 'button' : 'div'
              return (
                <Tag
                  key={c.clave}
                  type={c.ruta ? 'button' : undefined}
                  data-cuadro={c.clave}
                  onClick={c.ruta ? () => abrir(c) : undefined}
                  aria-label={etiquetaDe(c)}
                  className="inline-flex items-center gap-2 rounded-lg border border-line px-2.5 py-1.5 min-h-[40px] text-[13px] text-ink-1"
                >
                  <span className="inline-block w-3 h-3 rounded-xs shrink-0" style={{ background: col.bg }} />
                  <span className="font-semibold text-ink-0">{c.nombre}{c.detalle ? ` ${c.detalle}` : ''}</span>
                  <span className="tabular">{valorDelModo(c, modo)}</span>
                  {!oculto && <span className="tabular text-ink-3">{textoDelPeso(c.peso * 100)}</span>}
                </Tag>
              )
            })}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 mt-4">
        <Leyenda modo={modo} />
        {(sumo || resto) && (
          <p className="text-[13px] text-ink-1">
            {sumo && <>Lo que más sumó hoy: <strong className="font-semibold text-ink-0">{extremo(sumo)}</strong>.</>}
            {sumo && resto && ' '}
            {resto && <>Lo que más restó: <strong className="font-semibold text-ink-0">{extremo(resto)}</strong>.</>}
          </p>
        )}
      </div>
      <p className="text-[12px] text-ink-3 mt-3">
        Describe cómo se movieron los precios. No es una recomendación de compra o venta.
      </p>
    </Panel>
  )
}
