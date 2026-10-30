// TuLista — la pestaña «Tu lista» de Análisis técnico (pages/AnalisisTecnico.jsx):
// lo que tenés y lo que seguís (watchlist), con su lectura técnica. También se
// llega desde el inicio → panel Watchlist → «Ver como tablero»
// (/analisis-tecnico?tab=lista).
// ════════════════════════════════════════════════════════════════════════════
// Dos vistas de lo mismo (Nico, 30/10): de entrada TARJETAS (una por activo,
// con su mini-gráfico de 3 meses y tres medidores), y TABLA, la de antes. Los
// filtros y el orden valen para las dos; la elección queda en el navegador.
// Una sola pantalla para compu y celular (R6): en el celular las tarjetas van
// una debajo de otra y la tabla se desliza de costado, con la columna del
// activo fija, como la de Cartera.
//
// De dónde sale cada cosa (utils/listaTecnica.js):
//   · los números técnicos, de POST /api/tecnico/lista (la misma lectura que la
//     ficha, en dólares);
//   · qué tenés y cuánto pesa cada activo, del mismo pedido (`tenencias`: la
//     valuación del servidor, LA misma del % alcista y de la pestaña Señales);
//   · el último cambio, de la cuenta única de «qué cambió esta semana».
// Con «Ocultar saldos» no se muestra cuánto pesa (la proporción también es
// información de la cartera, como en la radiografía).

import { useEffect, useId, useMemo, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { ArrowDown, ArrowUp, Info, LayoutGrid, Rows3, X } from 'lucide-react'
import { api } from '../utils/api'
import Panel from '../components/Panel'
import Skeleton from '../components/Skeleton'
import AssetLogo from '../components/AssetLogo'
import { PildoraTendencia } from '../components/RadiografiaTecnica'
import { BotonAvisame, useAvisosTecnicos, senalDeTarjeta } from '../components/alerts/AvisameTecnico'
import { usePrivacy } from '../contexts/PrivacyContext'
import { useAuth } from '../contexts/AuthContext'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import { claveDeActivos } from '../utils/buscadorRapido'
import { pesoVisible, deTuCartera } from '../utils/parteDeTuPlata'
import { fmtMoney } from '../utils/format'
import { indexarLecturas } from '../utils/radiografia'
import { RSI_CASTIGADO, RSI_ESTIRADO, RSI_GANA, RSI_PIERDE, ADX_CLAVE } from '../utils/tecnico'
import {
  activosDeLaLista, contarFilas, filtrarFilas, ordenarFilas, trazoDeLinea, barrasDeFuerza,
  resumenDeLaLista, vistaGuardada, guardarVista, FILTROS, ORDENES, VISTAS, MAX_POR_PEDIDO,
} from '../utils/listaTecnica'

/**
 * Lo que necesita la tabla: tu watchlist y, del servidor, la lectura técnica de
 * todo más lo que tenés y cuánto pesa (`tenencias`: la valuación del servidor,
 * la misma del % alcista y de la pestaña Señales). → { cargando, error,
 * tenencias, seguidos, indice }
 */
export function useListaTecnica() {
  const [estado, setEstado] = useState(null)   // { seguidos, tenencias, indice }
  const [error, setError] = useState(null)     // 'base' | 'lectura'

  useEffect(() => {
    let vivo = true
    api.get('/watchlist')
      .catch(() => ({ items: [] }))
      .then(wl => {
        const seguidos = wl?.items || []
        return api.post('/tecnico/lista', { activos: activosDeLaLista(seguidos).slice(0, MAX_POR_PEDIDO) })
          .then(r => { if (vivo) setEstado({ seguidos, tenencias: r?.tenencias || [], indice: indexarLecturas(r?.lecturas || []) }) })
          .catch(() => { if (vivo) setError('lectura') })
      })
    return () => { vivo = false }
  }, [])

  return {
    cargando: !error && !estado,
    error,
    tenencias: estado?.tenencias || [],
    seguidos: estado?.seguidos || [],
    indice: estado?.indice || null,
  }
}

const pct1 = (v) => `${v.toLocaleString('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`
const signo = (v) => (v < 0 ? `−${pct1(-v)}` : pct1(v))
const conSigno = (v) => (v < 0 ? `−${pct1(-v)}` : `+${pct1(v)}`)
const ruta = (f) => `/activo/${encodeURIComponent(f.ruta)}`

function Linea({ linea }) {
  const t = trazoDeLinea(linea)
  if (!t) return <span className="text-ink-3">—</span>
  return (
    <svg width="64" height="22" viewBox="0 0 64 22" aria-hidden="true" className="block">
      <path d={t.d} fill="none" strokeWidth="1.5" strokeLinejoin="round"
        className={t.sube ? 'stroke-rendi-pos' : 'stroke-rendi-neg'} />
    </svg>
  )
}

function Corto({ corto }) {
  if (!corto) return <span className="text-ink-3">—</span>
  return <PildoraTendencia id={corto.palabra === 'Alcista' ? 'alcista' : 'bajista'} palabra={corto.palabra} motivo={corto.motivo} />
}

// El borde derecho de la columna fija del activo: con la tabla deslizada en el
// celular, marca qué queda quieto. Va por `style` (una sombra hacia adentro):
// con border-collapse el borde de una celda fija no viaja con ella, y
// `shadow-[var(--x)]` de Tailwind compila sin pintar (frontend/CLAUDE.md, R8).
const BORDE_FIJO = { boxShadow: 'inset -1px 0 0 rgb(var(--line))' }

// El color del cambio, el de su pastilla en «Tus señales» (`tono` del servidor).
const TONO_CAMBIO = { pos: 'text-rendi-pos', neg: 'text-rendi-neg' }
const PUNTO_CAMBIO = { pos: 'bg-rendi-pos ring-rendi-pos/20', neg: 'bg-rendi-neg ring-rendi-neg/20' }

// Columnas que ordenan al tocarlas: la de cada opción de «Ordenar por».
const COLUMNA_DE = { peso: 'tenes', fuerza: 'rsi', maximo: 'maximo', cambio: 'cambio' }

// Qué mide cada columna: en la tabla, en la «i» de su encabezado; en las
// tarjetas, en una línea al pie (PIE_TARJETAS).
const EXPLICACIONES = {
  fondo: { k: 'Largo plazo', t: 'Si el precio está por encima (alcista) o por debajo (bajista) de su promedio de los últimos 200 días de mercado.' },
  corto: { k: 'Mediano plazo', t: 'Si el precio está por encima (alcista) o por debajo (bajista) de su promedio de los últimos 50 días de mercado.' },
  rsi: { k: 'Impulso (RSI)', t: `De 0 a 100, qué tan rápido subió o bajó el precio en las últimas 3 semanas. Arriba de ${RSI_ESTIRADO}, subió muy rápido; abajo de ${RSI_CASTIGADO}, cayó muy rápido.` },
  adx: { k: 'Fuerza de la tendencia (ADX)', t: `De 0 a 100, qué tan marcada es la dirección del precio. Debajo de ${ADX_CLAVE}, se mueve sin una dirección clara (de forma lateral).` },
  cambio: { k: 'Último cambio', t: 'Lo último que cambió (cruzó uno de sus promedios, marcó un máximo del año, cambió su impulso o la fuerza de su tendencia) y hace cuánto pasó.' },
}
const PIE_TARJETAS = 'Tendencia: si el precio está arriba o abajo de su promedio de 200 días de mercado (largo plazo) o de 50 (mediano plazo). '
  + 'Impulso (RSI): de 0 a 100, qué tan rápido se movió en las últimas 3 semanas. '
  + `Fuerza (ADX): qué tan marcada es la dirección; debajo de ${ADX_CLAVE}, se mueve sin una dirección clara.`
const NO_ES_RECOMENDACION = 'Describe cómo se movieron los precios. No es una recomendación de compra ni de venta.'

function Encabezado({ id, orden, onOrdenar, explica, onExplicar, children, className = '' }) {
  const por = Object.keys(COLUMNA_DE).find(k => COLUMNA_DE[k] === id)
  const activa = por && orden.por === por
  const Flecha = orden.desc ? ArrowDown : ArrowUp
  const e = EXPLICACIONES[id]
  const derecha = className.includes('text-right')
  return (
    <th scope="col" aria-sort={por ? (activa ? (orden.desc ? 'descending' : 'ascending') : 'none') : undefined}
      className={`px-3 py-2.5 font-medium leading-tight align-bottom ${className}`}>
      <span className={`inline-flex items-end gap-1 ${derecha ? 'justify-end' : ''}`}>
        {por ? (
          <button type="button" onClick={() => onOrdenar(por)}
            className={`inline-flex items-end gap-1 text-left hover:text-ink-0 ${derecha ? 'justify-end text-right' : ''} ${activa ? 'text-ink-0' : ''}`}>
            {children}
            {activa && <Flecha size={12} strokeWidth={2} aria-hidden="true" />}
          </button>
        ) : <span>{children}</span>}
        {e && (
          <button type="button" onClick={() => onExplicar(explica === id ? null : id)} title={e.t}
            aria-label={`Qué es «${e.k}»`} aria-expanded={explica === id}
            className={`shrink-0 rounded-full p-0.5 hover:text-data-violet ${explica === id ? 'text-data-violet' : 'text-ink-3'}`}>
            <Info size={13} strokeWidth={2} aria-hidden="true" />
          </button>
        )}
      </span>
    </th>
  )
}

/**
 * La tabla. `filas`: ya filtradas y ordenadas (las de `filasDeLaLista`);
 * `oculto`: «Ocultar saldos» (no muestra cuánto pesa cada uno).
 */
export function TablaLista({ filas, oculto = false, orden, onOrdenar, filtro = 'todo', onAbrir }) {
  const [explica, setExplica] = useState(null)
  const col = { orden, onOrdenar, explica, onExplicar: setExplica }
  return (
    <div className="space-y-3">
      {explica && (
        <Panel padding="sm" className="flex items-start gap-3" role="note">
          <p className="flex-1 text-[13px] leading-relaxed text-ink-1">
            <span className="font-medium text-ink-0">{EXPLICACIONES[explica].k}:</span> {EXPLICACIONES[explica].t}
          </p>
          <button type="button" onClick={() => setExplica(null)} aria-label="Cerrar la explicación"
            className="shrink-0 rounded p-1 text-ink-2 hover:text-ink-0"><X size={14} aria-hidden="true" /></button>
        </Panel>
      )}
      <Panel padding="none" className="overflow-hidden">
        <div className="overflow-x-auto overscroll-x-contain">
          <table className="w-full min-w-[960px] border-collapse text-left">
            <thead className="text-[12px] text-ink-2 border-b border-line">
              <tr>
                <th scope="col" className="sticky left-0 z-[1] bg-bg-1 px-3 py-2.5 font-medium align-bottom" style={BORDE_FIJO}>Activo</th>
                <Encabezado id="tenes" {...col}>¿En tu cartera?</Encabezado>
                <Encabezado id="linea" {...col}>3 meses</Encabezado>
                <Encabezado id="fondo" {...col}>Largo plazo <span className="block text-ink-3">200 días</span></Encabezado>
                <Encabezado id="corto" {...col}>Mediano plazo <span className="block text-ink-3">50 días</span></Encabezado>
                <Encabezado id="rsi" {...col} className="text-right">Impulso (RSI)</Encabezado>
                <Encabezado id="adx" {...col} className="text-right">Fuerza de la{' '}<br />tendencia (ADX)</Encabezado>
                <Encabezado id="maximo" {...col} className="text-right">Desde el{' '}<br />máximo del año</Encabezado>
                <Encabezado id="cambio" {...col}>Último cambio</Encabezado>
              </tr>
            </thead>
            <tbody className="text-[14px]">
              {filas.map(f => (
                <tr key={f.clave} onClick={() => onAbrir?.(f)}
                  className={`group cursor-pointer border-b border-line/40 last:border-b-0 hover:bg-bg-2/50 ${f.vigente ? '' : 'opacity-60'}`}>
                  <td className="sticky left-0 z-[1] bg-bg-1 group-hover:bg-bg-2 px-3 py-2.5" style={BORDE_FIJO}>
                    <Link to={ruta(f)} onClick={e => e.stopPropagation()}
                      className="font-semibold text-ink-0 hover:text-data-violet">
                      {f.nombre}
                    </Link>
                    {f.detalle && <span className="block text-[11.5px] text-ink-3 whitespace-nowrap">{f.detalle}</span>}
                  </td>
                  <td className="px-3 py-2.5 whitespace-nowrap">
                    {f.tenes
                      ? <span className="text-data-violet">Sí{f.peso > 0 && pesoVisible(f.peso, oculto) ? ` · ${pesoVisible(f.peso, oculto)}` : ''}</span>
                      : <span className="text-ink-2">Watchlist</span>}
                  </td>
                  <td className="px-3 py-2.5"><Linea linea={f.linea} /></td>
                  <td className="px-3 py-2.5"><PildoraTendencia {...f.fondo} /></td>
                  <td className="px-3 py-2.5">{f.vigente ? <Corto corto={f.corto} /> : <span className="text-ink-3">—</span>}</td>
                  <td className="px-3 py-2.5 text-right whitespace-nowrap tabular">
                    {f.rsi ? (
                      <>
                        <span className={`font-semibold ${f.rsi.rsi > RSI_ESTIRADO ? 'text-rendi-pos' : f.rsi.rsi < RSI_CASTIGADO ? 'text-rendi-neg' : 'text-ink-1'}`}>{Math.round(f.rsi.rsi)}</span>
                        {' '}<span className="text-[12px] text-ink-2">{f.rsi.palabra.toLowerCase()}</span>
                      </>
                    ) : <span className="text-ink-3">—</span>}
                  </td>
                  <td className="px-3 py-2.5 text-right whitespace-nowrap tabular">
                    {f.adx ? (
                      <>
                        <span className="font-semibold text-ink-1">{f.adx.texto}</span>
                        {' '}<span className="text-[12px] text-ink-2">{f.adx.palabra}</span>
                      </>
                    ) : <span className="text-ink-3">—</span>}
                  </td>
                  <td className="px-3 py-2.5 text-right whitespace-nowrap tabular text-ink-1">
                    {!f.desdeMax ? <span className="text-ink-3">—</span>
                      : f.desdeMax.enMaximo ? 'En su máximo' : signo(f.desdeMax.pct)}
                  </td>
                  <td className="px-3 py-2.5 min-w-[200px] text-[13px]">
                    {!f.vigente ? <span className="text-ink-2">{f.motivo}</span>
                      : f.cambio ? (
                        <span title={f.cambio.completa}>
                          {f.cambio.corta && <span className={TONO_CAMBIO[f.cambio.tono] || 'text-ink-0'}>{f.cambio.corta}</span>}
                          <span className="text-[12px] text-ink-2">{f.cambio.corta ? ' · ' : ''}{f.cambio.hace}</span>
                        </span>
                      ) : <span className="text-ink-3">—</span>}
                  </td>
                </tr>
              ))}
              {!filas.length && (
                <tr><td colSpan={9} className="px-3 py-6 text-center text-[13px] text-ink-2"><SinFilas filtro={filtro} /></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}

function SinFilas({ filtro }) {
  return filtro === 'watchlist'
    ? 'Tu watchlist no tiene activos que no estén en tu cartera. Para sumar uno, entrá a su ficha y tocá «Agregar a watchlist».'
    : 'No hay activos para mostrar.'
}

// ─── La franja de arriba ────────────────────────────────────────────────────

function Dato({ titulo, children, pie }) {
  return (
    <div className="flex flex-col gap-0.5 bg-bg-1 px-4 py-3.5 sm:px-5">
      <span className="text-[12px] font-medium text-ink-2">{titulo}</span>
      <span className="tabular text-[22px] font-semibold leading-tight text-ink-0 sm:text-[24px]">{children}</span>
      {pie}
    </div>
  )
}

/** Cuántos con tendencia alcista de largo plazo, ganando impulso, en su máximo
 *  del año y que cambiaron esta semana. Son cuentas de activos: nada de plata. */
export function FranjaDeLaLista({ filas }) {
  const r = resumenDeLaLista(filas)
  const n = r.enMaximo.length
  const maximos = n > 3 ? `${r.enMaximo.slice(0, 2).join(', ')} y ${n - 2} más`
    : n > 1 ? `${r.enMaximo.slice(0, -1).join(', ')} y ${r.enMaximo[n - 1]}` : r.enMaximo[0]
  return (
    <section aria-label="Tu lista en números" className="overflow-hidden rounded-xl border border-line bg-line">
      <div className="grid grid-cols-2 gap-px lg:grid-cols-4">
        <Dato titulo="Con tendencia alcista de largo plazo" pie={r.conLectura > 0 && (
          <span className="mt-1.5 flex gap-0.5" aria-hidden="true">
            {r.puntos.map((p, i) => <span key={i} className={`h-1.5 flex-1 rounded-xs ${p === 'alcista' ? 'bg-rendi-pos' : 'bg-rendi-neg'}`} />)}
          </span>
        )}>
          <span className="text-rendi-pos">{r.alcistas}</span>{' '}
          <span className="text-[15px] font-medium text-ink-2">de {r.conLectura}</span>
        </Dato>
        <Dato titulo="Ganando impulso" pie={<span className="text-[12px] text-ink-2">Impulso (RSI) arriba de {RSI_GANA}</span>}>
          {r.ganando}
        </Dato>
        <Dato titulo="En su máximo del año" pie={<span className="truncate text-[12px] text-ink-2">{maximos || 'Ninguno'}</span>}>
          <span className={n ? 'text-data-blue' : ''}>{n}</span>
        </Dato>
        <Dato titulo="Cambiaron esta semana" pie={
          // urlDePestana('senales') de pages/AnalisisTecnico.jsx, escrita acá porque esa página importa esta.
          <Link to="/analisis-tecnico?tab=senales" className="text-[12px] font-medium text-data-violet hover:underline">Ver las señales →</Link>
        }>
          {r.cambiaron}
        </Dato>
      </div>
    </section>
  )
}

// ─── Las tarjetas ───────────────────────────────────────────────────────────

/** El mini-gráfico de 3 meses: la línea con su relleno (verde si subió, rojo si
 *  bajó) y, punteado en violeta, su promedio de 200 días (el que decide la
 *  tendencia de largo plazo). */
function MiniGrafico({ linea }) {
  const id = `lista-${useId().replace(/[^a-zA-Z0-9]/g, '')}`
  const t = trazoDeLinea(linea, 300, 70, { promedio: true })
  if (!t) return <div className="h-[94px]" aria-hidden="true" />
  return (
    <div className="pt-1.5">
      <span className="mb-1 block px-3.5 text-right text-[10.5px] text-ink-2">
        3 meses{t.ma && <> · <span className="text-data-violet">┄ promedio de 200 días</span></>}
      </span>
      <svg viewBox="0 0 300 70" width="100%" height="70" preserveAspectRatio="none" aria-hidden="true"
        className={`block ${t.sube ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="currentColor" stopOpacity=".3" />
            <stop offset="1" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={t.area} fill={`url(#${id})`} />
        {t.ma && <path d={t.ma} fill="none" strokeWidth="1.3" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" className="stroke-data-violet opacity-80" />}
        <path d={t.d} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  )
}

const COLOR_TENDENCIA = { alcista: 'text-rendi-pos', bajista: 'text-rendi-neg' }
const PUNTO_TENDENCIA = { alcista: 'bg-rendi-pos', bajista: 'bg-rendi-neg' }

function Plazo({ id, palabra, plazo }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`h-[7px] w-[7px] shrink-0 rounded-full ${PUNTO_TENDENCIA[id] || 'bg-ink-3'}`} aria-hidden="true" />
      <span className={`font-semibold ${COLOR_TENDENCIA[id] || 'text-ink-2'}`}>{palabra}</span>
      <span className="text-ink-2">{plazo}</span>
    </span>
  )
}

// El color del anillo del impulso, con los cortes de veredictoRsi.
const colorRsi = (rsi) => (rsi > RSI_GANA ? 'text-rendi-pos' : rsi < RSI_CASTIGADO ? 'text-rendi-neg'
  : rsi < RSI_PIERDE ? 'text-data-amber' : 'text-ink-2')
const VUELTA = 2 * Math.PI * 16

function Medidores({ f }) {
  const fz = barrasDeFuerza(f.adx?.valor)
  const corto = f.corto ? { id: f.corto.palabra === 'Alcista' ? 'alcista' : 'bajista', palabra: f.corto.palabra } : { id: 'sin', palabra: '—' }
  return (
    <div className="grid grid-cols-[1.1fr_1fr_1fr] border-y border-line">
      <div className="flex min-w-0 flex-col gap-1.5 border-r border-line px-3 py-2.5">
        <span className="text-[11px] font-medium text-ink-2">Tendencia</span>
        <span className="flex flex-col gap-1 text-[12px]">
          <Plazo id={f.fondo.id} palabra={f.fondo.palabra} plazo="largo" />
          <Plazo id={corto.id} palabra={corto.palabra} plazo="mediano" />
        </span>
      </div>
      <div className="flex min-w-0 flex-col gap-1.5 border-r border-line px-3 py-2.5">
        <span className="text-[11px] font-medium text-ink-2">Impulso</span>
        {f.rsi ? (
          <span className="flex items-center gap-1.5">
            <svg width="34" height="34" viewBox="0 0 40 40" role="img" aria-label={`Impulso (RSI): ${Math.round(f.rsi.rsi)} de 100`}
              className={`shrink-0 ${colorRsi(f.rsi.rsi)}`}>
              <circle cx="20" cy="20" r="16" fill="none" strokeWidth="4" className="stroke-line" />
              <circle cx="20" cy="20" r="16" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round"
                strokeDasharray={`${(f.rsi.rsi / 100) * VUELTA} ${VUELTA}`} transform="rotate(-90 20 20)" />
              <text x="20" y="24.5" textAnchor="middle" fontSize="12.5" fontWeight="600" className="fill-ink-0 tabular">{Math.round(f.rsi.rsi)}</text>
            </svg>
            <span className="min-w-0 text-[11.5px] leading-tight text-ink-1">{f.rsi.palabra.toLowerCase()}</span>
          </span>
        ) : <span className="text-ink-3">—</span>}
      </div>
      <div className="flex min-w-0 flex-col gap-1.5 px-3 py-2.5">
        <span className="text-[11px] font-medium text-ink-2">Fuerza</span>
        {fz ? (
          <>
            <span className="flex h-4 items-end gap-0.5" role="img" aria-label={`Fuerza de la tendencia (ADX): ${f.adx.texto}`}>
              {[1, 2, 3, 4, 5].map(k => (
                <span key={k} style={{ height: `${4 + k * 2.4}px` }}
                  className={`w-[7px] rounded-xs ${k > fz.prendidas ? 'bg-line' : fz.clara ? 'bg-data-blue' : 'bg-ink-3'}`} />
              ))}
            </span>
            <span className="text-[11.5px] leading-tight text-ink-1">{fz.clara ? 'dirección marcada' : 'sin dirección clara'}</span>
          </>
        ) : <span className="text-ink-3">—</span>}
      </div>
    </div>
  )
}

/** Logo, ticker, nombre y el link a la ficha, que cubre TODA la tarjeta (con
 *  `after:`), para que se pueda abrir en otra pestaña sin meter el botón de
 *  «Avisame» adentro de un link. */
function Cabeza({ f, children }) {
  return (
    <div className="flex items-center gap-2.5">
      <AssetLogo asset={f.asset} size={38} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <Link to={ruta(f)} className="text-[15px] font-semibold text-ink-0 after:absolute after:inset-0 after:rounded-xl after:content-['']">
            {f.nombre}
          </Link>
          {f.nuevo && <span className="rounded-full bg-data-violet/15 px-[7px] py-px text-[10.5px] font-semibold text-data-violet">Nuevo</span>}
        </div>
        <div className="truncate text-[12px] text-ink-2">{[f.empresa, f.detalle].filter(Boolean).join(' · ')}</div>
      </div>
      {children}
    </div>
  )
}

export function TarjetaActivo({ f, oculto = false, avisos }) {
  const peso = f.tenes && f.peso > 0 ? deTuCartera(f.peso, oculto) : null
  if (!f.vigente) {
    return (
      <article className="relative flex flex-col justify-center gap-2 rounded-xl border border-dashed border-line-2 bg-bg-1 p-4 transition-colors hover:border-data-violet/50">
        <Cabeza f={f} />
        {peso && <span className="tabular text-[12px] text-data-violet">{peso}</span>}
        <p className="text-[12.5px] leading-snug text-ink-2">Sin lectura técnica. {f.motivo}</p>
      </article>
    )
  }
  const aviso = senalDeTarjeta('fondo', f.lectura)
  return (
    <article className={`relative flex flex-col overflow-hidden rounded-xl border bg-bg-1 transition-colors hover:border-data-violet/50 ${f.nuevo ? 'border-data-violet/45' : 'border-line'}`}>
      <div className="px-3.5 pt-3.5">
        <Cabeza f={f}>
          <div className="shrink-0 text-right">
            <div className="tabular text-[14px] font-semibold text-ink-0">{f.precio != null ? fmtMoney(f.precio, 'USD', { decimals: f.precio < 1 ? 4 : 2 }) : '—'}</div>
            {f.var3m != null && (
              <div className={`tabular text-[12px] ${f.var3m >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{conSigno(f.var3m)} en 3 meses</div>
            )}
          </div>
        </Cabeza>
      </div>
      <MiniGrafico linea={f.linea} />
      <Medidores f={f} />
      <div className="flex items-center gap-2.5 px-3.5 py-2.5">
        <span className={`h-2 w-2 shrink-0 rounded-full ring-[3px] ${PUNTO_CAMBIO[f.cambio?.tono] || (f.cambio ? 'bg-data-blue ring-data-blue/20' : 'bg-ink-3 ring-ink-3/20')}`} aria-hidden="true" />
        <span className="min-w-0 flex-1 text-[12.5px] leading-snug" title={f.cambio?.completa}>
          {f.cambio
            ? <><span className="text-ink-0">{f.cambio.corta}</span><span className="text-ink-2"> · {f.cambio.hace}</span></>
            : <span className="text-ink-2">Sin cambios en el último año</span>}
        </span>
        {f.tenes
          ? peso && <span className="tabular whitespace-nowrap rounded-full bg-data-violet/10 px-2 py-0.5 text-[11.5px] font-semibold text-data-violet">{peso}</span>
          : <span className="whitespace-nowrap rounded-full bg-bg-2 px-2 py-0.5 text-[11.5px] text-ink-2">Watchlist</span>}
        <BotonAvisame avisos={avisos} asset={f.asset} accionLocal={f.local} moneda="usd"
          senal={aviso.senal} direction={aviso.direction} className="relative z-[1] shrink-0" />
      </div>
    </article>
  )
}

function Seccion({ titulo, filas, oculto, avisos }) {
  if (!filas.length) return null
  return (
    <section aria-label={titulo} className="space-y-3">
      <div className="flex items-center gap-2.5">
        <h2 className="text-[14px] font-semibold text-ink-0">{titulo}</h2>
        <span className="tabular text-[12px] font-medium text-ink-2">{filas.length}</span>
        <span className="h-px flex-1 bg-line" aria-hidden="true" />
      </div>
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-[repeat(auto-fill,minmax(280px,1fr))]">
        {filas.map(f => <TarjetaActivo key={f.clave} f={f} oculto={oculto} avisos={avisos} />)}
      </div>
    </section>
  )
}

/** Las tarjetas, separadas en lo que tenés y lo que seguís. */
export function TarjetasLista({ filas, oculto = false, avisos, filtro = 'todo' }) {
  if (!filas.length) return <Panel padding="lg" className="text-center text-[13px] text-ink-2"><SinFilas filtro={filtro} /></Panel>
  return (
    <div className="space-y-5">
      <Seccion titulo="En tu cartera" filas={filas.filter(f => f.tenes)} oculto={oculto} avisos={avisos} />
      <Seccion titulo="En tu watchlist" filas={filas.filter(f => !f.tenes)} oculto={oculto} avisos={avisos} />
    </div>
  )
}

// ─── Lo que comparten las dos vistas ────────────────────────────────────────

const ICONO_VISTA = { tarjetas: LayoutGrid, tabla: Rows3 }

/**
 * Tu lista entera: la franja, los filtros, el orden, el botón «Tarjetas /
 * Tabla» y la vista elegida. `vista`: 'tarjetas' | 'tabla'; `onVista` la cambia.
 */
export function ListaTecnica({ filas, oculto = false, vista = 'tarjetas', onVista, avisos, onAbrir }) {
  const [filtro, setFiltro] = useState('todo')
  const [orden, setOrden] = useState({ por: 'cambio', desc: true })
  const cuantas = contarFilas(filas)
  const elegidas = useMemo(() => ordenarFilas(filtrarFilas(filas, filtro), orden.por, orden.desc), [filas, filtro, orden])

  function ordenar(por) {
    setOrden(o => (o.por === por ? { por, desc: !o.desc } : { por, desc: ORDENES.find(x => x.id === por).desc }))
  }

  return (
    <div className="space-y-4">
      <FranjaDeLaLista filas={filas} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Qué mostrar">
          {FILTROS.map(f => (
            <button key={f.id} type="button" aria-pressed={filtro === f.id} onClick={() => setFiltro(f.id)}
              aria-label={`${f.label}: ${cuantas[f.id]}`}
              className={`rounded-full border px-3 py-1.5 text-[13px] min-h-[34px] transition-colors ${filtro === f.id
                ? 'border-data-violet bg-data-violet/10 text-ink-0'
                : 'border-line-2 bg-bg-1 text-ink-1 hover:text-ink-0'}`}>
              {f.label} · <span className="tabular">{cuantas[f.id]}</span>
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-[13px] text-ink-2">
            Ordenar por
            <select value={orden.por} onChange={e => setOrden({ por: e.target.value, desc: ORDENES.find(x => x.id === e.target.value).desc })}
              className="rounded-lg border border-line-2 bg-bg-1 px-2.5 py-1.5 text-[13px] text-ink-0 min-h-[34px]">
              {ORDENES.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
            </select>
          </label>
          <div className="inline-flex gap-0.5 rounded-lg border border-line bg-bg-2 p-0.5" role="group" aria-label="Cómo ver la lista">
            {VISTAS.map(v => {
              const Icono = ICONO_VISTA[v.id]
              return (
                <button key={v.id} type="button" aria-pressed={vista === v.id} onClick={() => onVista?.(v.id)}
                  className={`inline-flex min-h-[30px] items-center gap-1.5 rounded px-2.5 text-[13px] transition-colors ${vista === v.id
                    ? 'bg-line-2 font-medium text-ink-0' : 'text-ink-2 hover:text-ink-0'}`}>
                  <Icono size={14} strokeWidth={2} aria-hidden="true" />{v.label}
                </button>
              )
            })}
          </div>
        </div>
      </div>

      {vista === 'tabla'
        ? <TablaLista filas={elegidas} oculto={oculto} orden={orden} onOrdenar={ordenar} filtro={filtro} onAbrir={onAbrir} />
        : <TarjetasLista filas={elegidas} oculto={oculto} avisos={avisos} filtro={filtro} />}

      {vista === 'tarjetas' && <p className="text-[12px] leading-relaxed text-ink-2">{PIE_TARJETAS}</p>}
      <p className="text-[12px] text-ink-2">{NO_ES_RECOMENDACION}</p>
    </div>
  )
}

/** La pestaña «Tu lista» de Análisis técnico. `datos`: lo de useListaTecnica
 *  (la página lo pide una vez: lo usa también el Panorama); `filas`: las de
 *  filasDeLaLista con esos datos. */
export default function TuLista({ datos, filas }) {
  const navigate = useNavigate()
  const { hidden } = usePrivacy()
  const { user } = useAuth()
  const { clientCtx } = useAdvisorContext()
  const persona = claveDeActivos(user, clientCtx)
  const [vista, setVista] = useState(() => vistaGuardada(persona))
  useEffect(() => { setVista(vistaGuardada(persona)) }, [persona])
  const avisos = useAvisosTecnicos()
  const elegir = (v) => { setVista(v); guardarVista(persona, v) }

  if (datos.error === 'base') {
    return <Panel padding="lg" className="text-center text-[13px] text-ink-2">No pudimos cargar tu cartera y tu watchlist. Probá de nuevo en unos minutos.</Panel>
  }
  if (datos.error === 'lectura') {
    return <Panel padding="lg" className="text-center text-[13px] text-ink-2">No pudimos cargar el análisis técnico. Probá de nuevo en unos minutos.</Panel>
  }
  if (datos.cargando) {
    return (
      <div className="space-y-2" aria-label="Cargando tu lista">
        <Skeleton className="h-9 w-80" />
        <Skeleton className="h-72 w-full rounded-xl" />
      </div>
    )
  }
  if (!filas.length) {
    return (
      <Panel padding="lg" className="text-center text-[13px] text-ink-2">
        Todavía no tenés activos ni seguís ninguno. Buscá un ticker en el inicio y agregalo a tu watchlist desde su ficha.
      </Panel>
    )
  }
  return <ListaTecnica filas={filas} oculto={hidden} vista={vista} onVista={elegir} avisos={avisos}
    onAbrir={f => navigate(ruta(f))} />
}
