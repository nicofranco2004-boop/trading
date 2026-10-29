// RadiografiaTecnica — arriba de la Cartera, corta (recuadro 21c, 28/10): «54 %
// de tu plata está en tendencia de fondo alcista (la semana pasada, 61 %)» y un
// link a Análisis técnico, adonde se mudaron la barra y «Lo que cambió esta
// semana». Más las dos celdas que la tabla de posiciones suma por fila: la
// tendencia y la fuerza del movimiento (RSI), que son la lectura de cada activo.
// `TarjetaPlata` es la tarjeta grande del Panorama de Análisis técnico.
// ════════════════════════════════════════════════════════════════════════════
// Una sola pieza para compu y celular (R6): la montan Positions.jsx y
// PositionsMobile.jsx. El % NO se calcula acá: lo manda el servidor
// (senales_semana.reparto, LA cuenta, la misma del Panorama, de la pestaña
// Señales y del mail de los sábados) en el mismo POST /api/tecnico/cartera que
// trae la lectura de cada fila.
//
// «Alcista» = el precio está arriba de su promedio de 200 días, medido en DÓLARES
// (un CEDEAR en pesos sube con el dólar aunque la empresa no se mueva). Sin
// velas guardadas, «Sin lectura»: nunca se inventa, y la tarjeta grande dice POR
// QUÉ cada uno (MOTIVOS_SIN_LECTURA en utils/radiografia.js pone las palabras).
//
// Con "Ocultar saldos" no se muestran los porcentajes ni la barra: la
// proporción también es información de la cartera (como PesoEnCartera).

import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../utils/api'
import { usePrivacy } from '../contexts/PrivacyContext'
import {
  activosParaLeer, indexarLecturas, lecturaDeFila, tendencia, fuerza, MOTIVOS_SIN_LECTURA,
} from '../utils/radiografia'
import { fciLabel } from '../utils/valuation'
import { hoyISO } from '../utils/fecha'
import { RSI_CASTIGADO, RSI_ESTIRADO } from '../utils/tecnico'

/**
 * Pide la lectura de todos los activos de la cartera de una vez (y, en el
 * mismo pedido, el % de tu plata en tendencia alcista). Vuelve a pedir
 * sólo si cambia QUÉ activos hay (no con cada refresco de precios: las velas son
 * de cierre y se guardan de noche). → { indice, cargando, error }
 *
 * Si el pedido falla, `error` y `indice` null: NO un índice vacío, que la
 * pantalla leería como «ningún activo tiene lectura» (y no es eso lo que pasó).
 */
export function useLecturasCartera(lotes) {
  const pedido = useMemo(() => activosParaLeer(lotes), [lotes])
  const firma = JSON.stringify(pedido)
  const [estado, setEstado] = useState({ firma: null, indice: null, reparto: null, error: false })
  useEffect(() => {
    if (!pedido.length) return undefined
    let vivo = true
    api.post('/tecnico/cartera', { activos: pedido })
      .then(r => { if (vivo) setEstado({ firma, indice: indexarLecturas(r?.lecturas), reparto: r?.reparto || null, error: false }) })
      .catch(() => { if (vivo) setEstado({ firma, indice: null, reparto: null, error: true }) })
    return () => { vivo = false }
    // `firma` resume `pedido`: depender del array haría un pedido por render.
  }, [firma])
  const listo = estado.firma === firma
  return {
    indice: listo ? estado.indice : null,
    // El % de tu plata en tendencia alcista: lo manda el servidor en el mismo
    // pedido (senales_semana.reparto, LA cuenta).
    reparto: listo ? estado.reparto : null,
    cargando: pedido.length > 0 && !listo,
    error: listo && estado.error,
  }
}

/** Lo que muestra una fila de la tabla: 'cargando' | 'error' | 'listo' (con su
 *  lectura `x`, que puede ser null = sin lectura). Lo usan las dos tablas. */
export function lecturaDeLaFila(lecturas, p) {
  if (lecturas?.cargando) return { estado: 'cargando', x: null }
  if (lecturas?.error || !lecturas?.indice) return { estado: 'error', x: null }
  return { estado: 'listo', x: lecturaDeFila(lecturas.indice, p) }
}

// Para las filas del celular (componentes memo, adentro de otros): las lecturas
// viajan por contexto en vez de por cinco niveles de props.
const LecturasCtx = createContext(null)
export const LecturasTecnicasProvider = LecturasCtx.Provider
export function useLecturaDeFila(p) {
  return lecturaDeLaFila(useContext(LecturasCtx), p)
}

const TONO = {
  alcista: { texto: 'text-rendi-pos', fondo: 'bg-rendi-pos/10', barra: 'bg-rendi-pos' },
  bajista: { texto: 'text-rendi-neg', fondo: 'bg-rendi-neg/10', barra: 'bg-rendi-neg' },
  sin: { texto: 'text-ink-3', fondo: 'bg-bg-2', barra: 'bg-ink-3/40' },
}

/** La tendencia de una fila: «Alcista» / «Bajista» / «Sin lectura», con la
 *  explicación de la ficha en el globo. `p` (la fila) dice si es un bono o un
 *  fondo, para explicar bien por qué no tiene lectura. */
export function TendenciaChip({ x, p = null, className = '' }) {
  return <PildoraTendencia {...tendencia(x, undefined, p)} className={className} />
}

/** La píldora de una tendencia ya leída: `id` 'alcista' | 'bajista' | 'sin',
 *  su palabra y, en el globo, la explicación. La usan también «Tu lista» y su
 *  columna de corto plazo. */
export function PildoraTendencia({ id, palabra, motivo, className = '' }) {
  const tono = TONO[id] || TONO.sin
  return (
    <span title={motivo}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[12px] font-medium whitespace-nowrap ${tono.texto} ${tono.fondo} ${className}`}>
      {palabra}
    </span>
  )
}

/** La fuerza del movimiento: la barrita 0–100 con 30 y 70 marcados (la misma
 *  regla que la ficha) y el número. «—» si no hay. */
export function FuerzaRsi({ x, className = '', sinGuion = false }) {
  const f = fuerza(x)
  if (!f) return sinGuion ? null : <span className={`text-ink-3 ${className}`}>—</span>
  const pos = Math.min(100, Math.max(0, f.rsi))
  return (
    <span className={`inline-flex items-center gap-2 ${className}`} title={`Fuerza (RSI): ${Math.round(f.rsi)} de 100 · ${f.palabra}`}>
      <span aria-hidden="true" className="relative w-14 h-1.5 rounded-full bg-bg-3 flex-none">
        <span className="absolute inset-y-0 left-0 rounded-l-full bg-rendi-neg-fill/35" style={{ width: `${RSI_CASTIGADO}%` }} />
        <span className="absolute inset-y-0 right-0 rounded-r-full bg-rendi-pos-fill/35" style={{ width: `${100 - RSI_ESTIRADO}%` }} />
        <span className="absolute -top-[3px] w-[3px] h-3 rounded-full bg-ink-0" style={{ left: `calc(${pos}% - 1.5px)` }} />
      </span>
      <span className="text-[12px] text-ink-1 tabular">{Math.round(f.rsi)}</span>
      <span className="sr-only">{f.palabra}</span>
    </span>
  )
}


function Lista({ nombres, max = 6 }) {
  if (!nombres.length) return null
  const vista = nombres.slice(0, max)
  const resto = nombres.length - vista.length
  return <span className="text-ink-2"> · {vista.join(', ')}{resto > 0 ? ` y ${resto} más` : ''}</span>
}

/** «la semana pasada, 61%» si es el sábado de hace 7 días; si no, «el sábado 17/10, 61%». */
function antesTxt(sp) {
  if (!sp?.semana) return null
  const dias = (Date.parse(hoyISO() + 'T00:00:00Z') - Date.parse(sp.semana + 'T00:00:00Z')) / 86400000
  const [, m, d] = sp.semana.split('-')
  return `${dias <= 7 ? 'la semana pasada' : `el sábado ${d}/${m}`}, ${Math.round(sp.pct)}%`
}

/**
 * La tarjeta de la Cartera, corta como el recuadro 21c (28/10): «54 % de tu
 * plata está en tendencia de fondo alcista (la semana pasada, 61 %)» y «Ver
 * análisis técnico →». La barra y los grupos viven en el Panorama; «Lo que
 * cambió esta semana», también. El número es `reparto` de useLecturasCartera
 * (senales_semana.reparto: el mismo del Panorama, de Señales y del mail).
 */
export default function RadiografiaTecnica({ lotes, reparto, cargando, error, className = '' }) {
  const { hidden } = usePrivacy()
  if (!lotes?.some(p => !p.is_cash)) return null
  const enlace = <Link to="/analisis-tecnico" className="text-[13px] font-medium text-data-violet hover:underline whitespace-nowrap">Ver análisis técnico →</Link>
  if (cargando) return <div className={`h-14 rounded-xl bg-bg-2/40 border border-line esqueleto ${className}`} aria-label="Cargando la radiografía técnica" />
  const antes = !hidden ? antesTxt(reparto?.semana_pasada) : null
  return (
    <section aria-label="Radiografía técnica"
      className={`bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 ${className}`}>
      <p className="text-[14px] sm:text-[15px] text-ink-0 leading-snug min-w-0">
        {error ? 'No pudimos traer el análisis técnico de tus activos ahora.'
          : reparto?.pct == null ? 'Ninguno de tus activos tiene todavía una tendencia de fondo para leer.'
            : hidden ? 'Mirá cómo está repartida tu plata entre tendencias de fondo.'
              : <><b className="font-semibold text-rendi-pos tabular">{reparto.pct}%</b> de tu plata está en tendencia de fondo alcista{antes && <span className="text-ink-2"> ({antes})</span>}</>}
      </p>
      {enlace}
    </section>
  )
}

/**
 * El % de tu plata en tendencia de fondo alcista, con la barra, los grupos y
 * por qué algunos van sin lectura: la tarjeta grande del Panorama de Análisis
 * técnico. Sólo dibuja: `reparto` lo arma el servidor (senales_semana.reparto,
 * LA cuenta de la Cartera, el Panorama, Señales y el mail). `nota`: una línea
 * abajo (lo que se dio vuelta esta semana).
 */
export function TarjetaPlata({ reparto, cargando, error, titulo, nota = null, className = '' }) {
  const { hidden } = usePrivacy()
  const cabecera = <div className="text-[12px] text-ink-2 font-medium">{titulo}</div>
  if (error) {
    return (
      <section aria-label="Radiografía técnica" className={`bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 ${className}`}>
        {cabecera}
        <p className="text-[13.5px] text-ink-1 mt-1.5">No pudimos traer el análisis técnico de tus activos ahora. Probá recargar la página en un rato.</p>
      </section>
    )
  }
  if (cargando || !reparto) {
    return <div className={`h-36 rounded-xl bg-bg-2/40 border border-line esqueleto ${className}`} aria-label="Cargando la radiografía técnica" />
  }
  const g = reparto.grupos || {}
  const pct = (id) => (g[id]?.pct === 0 && g[id]?.fraccion > 0 ? 'menos de 1%' : `${g[id]?.pct ?? 0}%`)
  const etiqueta = `${pct('alcista')} alcista, ${pct('bajista')} bajista, ${pct('sin')} sin lectura`
  const antes = !hidden ? antesTxt(reparto.semana_pasada) : null
  const tonoAntes = reparto.semana_pasada && reparto.pct != null
    ? (reparto.pct > reparto.semana_pasada.pct ? 'pos' : reparto.pct < reparto.semana_pasada.pct ? 'neg' : null) : null

  return (
    <section aria-label="Radiografía técnica" className={`bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-3 ${className}`}>
      {cabecera}
      {reparto.pct == null ? (
        <p className="text-[15px] text-ink-1 leading-snug">
          Ninguno de tus activos tiene todavía una tendencia de fondo para leer: bonos, fondos y
          efectivo no tienen historia de precios en Rendi, y una acción o un CEDEAR necesita 200
          días de mercado con precios guardados.
        </p>
      ) : (
        <p className="text-[19px] sm:text-[21px] font-semibold leading-snug text-ink-0">
          {hidden
            ? 'Así está repartida tu plata entre tendencias de fondo.'
            : <><span className="text-rendi-pos tabular">{reparto.pct}%</span> de tu plata está en activos con tendencia de fondo alcista.</>}
          {antes && (
            <span className={`ml-2 text-[14px] font-medium ${tonoAntes === 'pos' ? 'text-rendi-pos' : tonoAntes === 'neg' ? 'text-rendi-neg' : 'text-ink-2'}`}>({antes})</span>
          )}
        </p>
      )}
      {!hidden && (
        <div className="flex h-3 rounded-full overflow-hidden gap-0.5" role="img" aria-label={etiqueta}>
          {['alcista', 'bajista', 'sin'].map(id => g[id]?.fraccion > 0 && (
            <div key={id} className={`barra-intensidad ${TONO[id].barra}`} style={{ width: `${g[id].fraccion * 100}%` }} />
          ))}
        </div>
      )}
      <div className="flex flex-col sm:flex-row sm:flex-wrap gap-x-5 gap-y-1.5 text-[13px] text-ink-1">
        {['alcista', 'bajista', 'sin'].map(id => {
          if (!g[id]?.nombres?.length) return null
          const palabra = id === 'alcista' ? 'alcista' : id === 'bajista' ? 'bajista' : 'sin lectura'
          return (
            <span key={id}>
              <b className={`font-semibold ${TONO[id].texto}`}>{hidden ? '' : `${pct(id)} `}{palabra}</b>
              <Lista nombres={g[id].nombres.map(fciLabel)} />
            </span>
          )
        })}
      </div>
      {reparto.motivos?.length > 0 && (
        <ul className="flex flex-col gap-1 text-[12px] text-ink-2 leading-relaxed" aria-label="Por qué algunos van sin lectura">
          {reparto.motivos.filter(m => MOTIVOS_SIN_LECTURA[m.porque]).map(m => (
            <li key={m.porque}><b className="font-semibold text-ink-1">{m.nombres.map(fciLabel).join(', ')}</b>: {MOTIVOS_SIN_LECTURA[m.porque]}</li>
          ))}
        </ul>
      )}
      {nota && <p className="text-[13px] text-ink-1 leading-snug">{nota}</p>}
      <p className="text-[12px] text-ink-3 leading-relaxed">
        «Alcista» = el precio está arriba de su promedio de los últimos 200 días. Describe el precio; no es una recomendación.
      </p>
    </section>
  )
}
