// TuLista — la pestaña «Tu lista» de Análisis técnico (pages/AnalisisTecnico.jsx):
// lo que tenés y lo que seguís (watchlist), juntos en una tabla, con su lectura
// técnica. También se llega desde el inicio → panel Watchlist → «Ver como
// tablero» (/analisis-tecnico?tab=lista).
// ════════════════════════════════════════════════════════════════════════════
// Una sola pantalla para compu y celular (R6): en el celular la tabla se
// desliza de costado, con la columna del activo fija, como la de Cartera.
//
// De dónde sale cada cosa (utils/listaTecnica.js):
//   · los números técnicos, de POST /api/tecnico/lista (la misma lectura que la
//     ficha, en dólares);
//   · qué tenés y cuánto pesa cada activo, del mismo pedido (`tenencias`: la
//     valuación del servidor, LA misma del % alcista y de la pestaña Señales);
//   · el último cambio, de la cuenta única de «qué cambió esta semana».
// Con «Ocultar saldos» no se muestra cuánto pesa (la proporción también es
// información de la cartera, como en la radiografía).

import { useEffect, useMemo, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { api } from '../utils/api'
import Panel from '../components/Panel'
import Skeleton from '../components/Skeleton'
import { PildoraTendencia } from '../components/RadiografiaTecnica'
import { usePrivacy } from '../contexts/PrivacyContext'
import { indexarLecturas } from '../utils/radiografia'
import { RSI_CASTIGADO, RSI_ESTIRADO, ADX_CLAVE } from '../utils/tecnico'
import {
  activosDeLaLista, filasDeLaLista, contarFilas, filtrarFilas, ordenarFilas,
  FILTROS, ORDENES, MAX_POR_PEDIDO, trazoDeLinea, textoDelPeso,
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

// Columnas que ordenan al tocarlas: la de cada opción de «Ordenar por».
const COLUMNA_DE = { peso: 'tenes', fuerza: 'rsi', maximo: 'maximo', cambio: 'cambio' }

function Encabezado({ id, orden, onOrdenar, children, className = '' }) {
  const por = Object.keys(COLUMNA_DE).find(k => COLUMNA_DE[k] === id)
  if (!por) return <th scope="col" className={`px-3 py-2.5 font-medium leading-tight align-bottom ${className}`}>{children}</th>
  const activa = orden.por === por
  const Flecha = orden.desc ? ArrowDown : ArrowUp
  return (
    <th scope="col" aria-sort={activa ? (orden.desc ? 'descending' : 'ascending') : 'none'}
      className={`px-3 py-2.5 font-medium leading-tight align-bottom ${className}`}>
      <button type="button" onClick={() => onOrdenar(por)}
        className={`inline-flex items-end gap-1 text-left hover:text-ink-0 ${className.includes('text-right') ? 'justify-end text-right' : ''} ${activa ? 'text-ink-0' : ''}`}>
        {children}
        {activa && <Flecha size={12} strokeWidth={2} aria-hidden="true" />}
      </button>
    </th>
  )
}

const EXPLICACIONES = [
  { k: 'De fondo y corto plazo', t: 'Si el precio está arriba (alcista) o abajo (bajista) de su promedio de los últimos 200 o 50 días de mercado.' },
  { k: 'Fuerza (RSI)', t: `De 0 a 100, qué tan rápido subió o bajó. Arriba de ${RSI_ESTIRADO} subió muy rápido; abajo de ${RSI_CASTIGADO}, cayó muy rápido.` },
  { k: 'Fuerza de la tendencia (ADX)', t: `De 0 a 100, qué tan marcada es la dirección. Debajo de ${ADX_CLAVE} el precio va de costado.` },
  { k: 'Último cambio', t: 'El último cruce de un promedio, máximo del año o salto de la fuerza, y hace cuánto pasó.' },
]

/**
 * La tabla con sus filtros y su orden. `filas`: las de `filasDeLaLista`;
 * `oculto`: «Ocultar saldos» (no muestra cuánto pesa cada uno).
 */
export function TablaLista({ filas, oculto = false, onAbrir }) {
  const [filtro, setFiltro] = useState('todo')
  const [orden, setOrden] = useState({ por: 'cambio', desc: true })
  const cuantas = contarFilas(filas)
  const vista = useMemo(() => ordenarFilas(filtrarFilas(filas, filtro), orden.por, orden.desc), [filas, filtro, orden])

  function ordenar(por) {
    setOrden(o => (o.por === por ? { por, desc: !o.desc } : { por, desc: ORDENES.find(x => x.id === por).desc }))
  }

  return (
    <div className="space-y-4">
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
        <label className="flex items-center gap-2 text-[13px] text-ink-2">
          Ordenar por
          <select value={orden.por} onChange={e => setOrden({ por: e.target.value, desc: ORDENES.find(x => x.id === e.target.value).desc })}
            className="rounded-lg border border-line-2 bg-bg-1 px-2.5 py-1.5 text-[13px] text-ink-0 min-h-[34px]">
            {ORDENES.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
          </select>
        </label>
      </div>

      <Panel padding="none" className="overflow-hidden">
        <div className="overflow-x-auto overscroll-x-contain">
          <table className="w-full min-w-[960px] border-collapse text-left">
            <thead className="text-[12px] text-ink-2 border-b border-line">
              <tr>
                <th scope="col" className="sticky left-0 z-[1] bg-bg-1 px-3 py-2.5 font-medium align-bottom" style={BORDE_FIJO}>Activo</th>
                <Encabezado id="tenes" orden={orden} onOrdenar={ordenar}>¿Lo tenés?</Encabezado>
                <Encabezado id="linea" orden={orden} onOrdenar={ordenar}>3 meses</Encabezado>
                <Encabezado id="fondo" orden={orden} onOrdenar={ordenar}>De fondo <span className="block text-ink-3">200 días</span></Encabezado>
                <Encabezado id="corto" orden={orden} onOrdenar={ordenar}>Corto plazo <span className="block text-ink-3">50 días</span></Encabezado>
                <Encabezado id="rsi" orden={orden} onOrdenar={ordenar} className="text-right">Fuerza (RSI)</Encabezado>
                <Encabezado id="adx" orden={orden} onOrdenar={ordenar} className="text-right">Fuerza de la{' '}<br />tendencia (ADX)</Encabezado>
                <Encabezado id="maximo" orden={orden} onOrdenar={ordenar} className="text-right">Desde el{' '}<br />máximo del año</Encabezado>
                <Encabezado id="cambio" orden={orden} onOrdenar={ordenar}>Último cambio</Encabezado>
              </tr>
            </thead>
            <tbody className="text-[14px]">
              {vista.map(f => (
                <tr key={f.clave} onClick={() => onAbrir?.(f)}
                  className={`group cursor-pointer border-b border-line/40 last:border-b-0 hover:bg-bg-2/50 ${f.vigente ? '' : 'opacity-60'}`}>
                  <td className="sticky left-0 z-[1] bg-bg-1 group-hover:bg-bg-2 px-3 py-2.5" style={BORDE_FIJO}>
                    <Link to={`/activo/${encodeURIComponent(f.ruta)}`} onClick={e => e.stopPropagation()}
                      className="font-semibold text-ink-0 hover:text-data-violet">
                      {f.nombre}
                    </Link>
                    {f.detalle && <span className="block text-[11.5px] text-ink-3 whitespace-nowrap">{f.detalle}</span>}
                  </td>
                  <td className="px-3 py-2.5 whitespace-nowrap">
                    {f.tenes
                      ? <span className="text-data-violet">Sí{!oculto && f.peso > 0 ? ` · ${textoDelPeso(f.peso)}` : ''}</span>
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
              {!vista.length && (
                <tr><td colSpan={9} className="px-3 py-6 text-center text-[13px] text-ink-2">
                  {filtro === 'watchlist' ? 'No seguís nada que no tengas. Agregá un activo a tu watchlist desde su ficha.' : 'No hay activos para mostrar.'}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {EXPLICACIONES.map(e => (
          <Panel key={e.k} padding="sm">
            <p className="text-[12px] font-medium text-ink-2">{e.k}</p>
            <p className="mt-1 text-[13px] leading-relaxed text-ink-1">{e.t}</p>
          </Panel>
        ))}
      </div>
      <p className="text-[12px] text-ink-2">Describe cómo se movieron los precios. No es una recomendación de compra o venta.</p>
    </div>
  )
}

/** La pestaña «Tu lista» de Análisis técnico. `datos`: lo de useListaTecnica
 *  (la página lo pide una vez: lo usa también el Panorama); `filas`: las de
 *  filasDeLaLista con esos datos. */
export default function TuLista({ datos, filas }) {
  const navigate = useNavigate()
  const { hidden } = usePrivacy()
  if (datos.error === 'base') {
    return <Panel padding="lg" className="text-center text-[13px] text-ink-2">No pudimos cargar tu cartera y tu watchlist. Probá de nuevo en un rato.</Panel>
  }
  if (datos.error === 'lectura') {
    return <Panel padding="lg" className="text-center text-[13px] text-ink-2">No pudimos traer la lectura técnica. Probá de nuevo en un rato.</Panel>
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
  return <TablaLista filas={filas} oculto={hidden} onAbrir={f => navigate(`/activo/${encodeURIComponent(f.ruta)}`)} />
}
