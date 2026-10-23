// RadiografiaTecnica — arriba de la Cartera: cuánto de TU plata está en activos
// con tendencia de fondo alcista, la barra partida alcista / bajista / sin
// lectura, y «Lo que cambió esta semana». Más las dos celdas que la tabla de
// posiciones suma por fila: la tendencia y la fuerza del movimiento (RSI).
// ════════════════════════════════════════════════════════════════════════════
// Una sola pieza para compu y celular (R6): la montan Positions.jsx y
// PositionsMobile.jsx con SU valuación (`valorDe`), la misma que arma el total
// de cada pantalla. Las cuentas: utils/radiografia.js; los números técnicos,
// POST /api/tecnico/cartera (backend/tecnico.py, los mismos que la ficha).
//
// «Alcista» = el precio está arriba de su promedio de 200 días, medido en DÓLARES
// (un CEDEAR en pesos sube con el dólar aunque la empresa no se mueva). Sin
// velas guardadas, «Sin lectura»: nunca se inventa, y la tarjeta dice POR QUÉ
// cada uno (un bono no se mide; una acción recién agregada todavía no tiene
// precios guardados; ver MOTIVOS_SIN_LECTURA en utils/radiografia.js).
//
// Con "Ocultar saldos" no se muestran los porcentajes ni la barra: la
// proporción también es información de la cartera (como PesoEnCartera).

import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { api } from '../utils/api'
import { usePrivacy } from '../contexts/PrivacyContext'
import {
  activosParaLeer, indexarLecturas, lecturaDeFila, tendencia, fuerza, radiografia,
} from '../utils/radiografia'
import { RSI_CASTIGADO, RSI_ESTIRADO } from '../utils/tecnico'

/**
 * Pide la lectura de todos los activos de la cartera de una vez. Vuelve a pedir
 * sólo si cambia QUÉ activos hay (no con cada refresco de precios: las velas son
 * de cierre y se guardan de noche). → { indice, cargando, error }
 *
 * Si el pedido falla, `error` y `indice` null: NO un índice vacío, que la
 * pantalla leería como «ningún activo tiene lectura» (y no es eso lo que pasó).
 */
export function useLecturasCartera(lotes) {
  const pedido = useMemo(() => activosParaLeer(lotes), [lotes])
  const firma = JSON.stringify(pedido)
  const [estado, setEstado] = useState({ firma: null, indice: null, error: false })
  useEffect(() => {
    if (!pedido.length) return undefined
    let vivo = true
    api.post('/tecnico/cartera', { activos: pedido })
      .then(r => { if (vivo) setEstado({ firma, indice: indexarLecturas(r?.lecturas), error: false }) })
      .catch(() => { if (vivo) setEstado({ firma, indice: null, error: true }) })
    return () => { vivo = false }
    // `firma` resume `pedido`: depender del array haría un pedido por render.
  }, [firma])
  const listo = estado.firma === firma
  return {
    indice: listo ? estado.indice : null,
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
  const t = tendencia(x, undefined, p)
  const tono = TONO[t.id]
  return (
    <span title={t.motivo}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[12px] font-medium whitespace-nowrap ${tono.texto} ${tono.fondo} ${className}`}>
      {t.palabra}
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

const pctTxt = (g) => (g.pct === 0 && g.fraccion > 0 ? 'menos de 1%' : `${g.pct}%`)

function Lista({ nombres, max = 6 }) {
  if (!nombres.length) return null
  const vista = nombres.slice(0, max)
  const resto = nombres.length - vista.length
  return <span className="text-ink-2"> · {vista.join(', ')}{resto > 0 ? ` y ${resto} más` : ''}</span>
}

/**
 * La tarjeta. `lotes`: todas las posiciones (con el efectivo); `valorDe(p)`: el
 * valor en dólares de ese lote, el de la pantalla; `extra`: [{ nombre, valor }]
 * lo que suma al total sin ser posición (plazos fijos); `indice`/`cargando`: lo
 * que devuelve `useLecturasCartera`.
 */
export default function RadiografiaTecnica({ lotes, valorDe, extra = [], indice, cargando, error, className = '' }) {
  const { hidden } = usePrivacy()
  const r = useMemo(
    () => (indice ? radiografia(lotes, valorDe, indice, extra) : null),
    [lotes, valorDe, indice, extra])

  if (!lotes?.some(p => !p.is_cash)) return null
  if (error) {
    return (
      <section aria-label="Radiografía técnica" className={`bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 ${className}`}>
        <div className="text-[12px] text-ink-2 font-medium">Radiografía técnica · medida en dólares</div>
        <p className="text-[13.5px] text-ink-1 mt-1.5">No pudimos traer el análisis técnico de tus activos ahora. Probá recargar la página en un rato.</p>
      </section>
    )
  }
  if (cargando || !r) {
    return <div className={`h-36 rounded-xl bg-bg-2/40 border border-line esqueleto ${className}`} aria-label="Cargando la radiografía técnica" />
  }
  const { alcista, bajista, sin } = r.grupos
  const sinNinguna = alcista.valor === 0 && bajista.valor === 0
  const etiqueta = `${pctTxt(alcista)} alcista, ${pctTxt(bajista)} bajista, ${pctTxt(sin)} sin lectura`

  return (
    <section aria-label="Radiografía técnica"
      className={`bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-wrap gap-x-7 gap-y-4 ${className}`}>
      <div className="flex-[3_1_380px] min-w-0 flex flex-col gap-3">
        <div className="text-[12px] text-ink-2 font-medium">Radiografía técnica · medida en dólares</div>
        {sinNinguna ? (
          <p className="text-[15px] text-ink-1 leading-snug">
            Ninguno de tus activos tiene todavía una tendencia de fondo para leer: bonos, fondos y
            efectivo no tienen historia de precios en Rendi, y una acción o un CEDEAR necesita 200
            días de mercado con precios guardados.
          </p>
        ) : (
          <p className="text-[19px] sm:text-[21px] font-semibold leading-snug text-ink-0">
            {hidden
              ? 'Así está repartida tu plata entre tendencias de fondo.'
              : <><span className="text-rendi-pos tabular">{pctTxt(alcista)}</span> de tu plata está en activos con tendencia de fondo alcista.</>}
          </p>
        )}
        {!hidden && (
          <div className="flex h-3 rounded-full overflow-hidden gap-0.5" role="img" aria-label={etiqueta}>
            {['alcista', 'bajista', 'sin'].map(id => r.grupos[id].fraccion > 0 && (
              <div key={id} className={`barra-intensidad ${TONO[id].barra}`} style={{ width: `${r.grupos[id].fraccion * 100}%` }} />
            ))}
          </div>
        )}
        <div className="flex flex-col sm:flex-row sm:flex-wrap gap-x-5 gap-y-1.5 text-[13px] text-ink-1">
          {['alcista', 'bajista', 'sin'].map(id => {
            const g = r.grupos[id]
            if (!g.nombres.length) return null
            const palabra = id === 'alcista' ? 'alcista' : id === 'bajista' ? 'bajista' : 'sin lectura'
            return (
              <span key={id}>
                <b className={`font-semibold ${TONO[id].texto}`}>{hidden ? '' : `${pctTxt(g)} `}{palabra}</b>
                <Lista nombres={g.nombres} />
              </span>
            )
          })}
        </div>
        {sin.motivos.length > 0 && (
          <ul className="flex flex-col gap-1 text-[12px] text-ink-2 leading-relaxed" aria-label="Por qué algunos van sin lectura">
            {sin.motivos.map(m => (
              <li key={m.porque}><b className="font-semibold text-ink-1">{m.nombres.join(', ')}</b>: {m.texto}</li>
            ))}
          </ul>
        )}
        <p className="text-[12px] text-ink-3 leading-relaxed">
          «Alcista» = el precio está arriba de su promedio de los últimos 200 días. Describe el precio; no es una recomendación.
        </p>
      </div>

      <div className="flex-[2_1_260px] min-w-0 flex flex-col gap-2.5 sm:border-l sm:border-line sm:pl-6">
        <div className="text-[12px] text-ink-2 font-medium">Lo que cambió esta semana</div>
        {r.cambios.length === 0 ? (
          <p className="text-[13px] text-ink-2 leading-relaxed">
            Ninguno de tus activos cruzó su promedio de 50 o de 200 días, y ninguno subió o cayó muy rápido.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {r.cambios.slice(0, 6).map((c, i) => (
              <li key={i} className="flex gap-2.5 text-[13.5px] text-ink-1 leading-snug">
                <span aria-hidden="true" className={`font-semibold ${c.tono === 'pos' ? 'text-rendi-pos' : c.tono === 'neg' ? 'text-rendi-neg' : 'text-rendi-warn'}`}>
                  {c.tono === 'pos' ? '↑' : c.tono === 'neg' ? '↓' : '!'}
                </span>
                <span><span className="font-semibold text-ink-0">{c.asset}</span> {c.texto}</span>
              </li>
            ))}
            {r.cambios.length > 6 && <li className="text-[12.5px] text-ink-3">y {r.cambios.length - 6} más</li>}
          </ul>
        )}
      </div>
    </section>
  )
}
