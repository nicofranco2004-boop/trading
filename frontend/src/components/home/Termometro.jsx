// Termometro — «¿Cómo está el mercado?» (pieza 7, recuadro 7 del tablero).
// ════════════════════════════════════════════════════════════════════════════
// Arriba del mapa de calor del Resumen de Análisis de mercado. Un número de 0 a
// 100 con sus tres partes a la vista (cuánto suma cada una), el de hace una
// semana y la frase fija de que describe, no recomienda.
//
// Una sola pieza para compu y celular (R6): en compu el arco va a la izquierda
// y las partes a la derecha; en celular, una abajo de la otra. Lo monta Home y
// también HomeMobile (el fork viejo de la pantalla de inicio): el recuadro es
// el mismo archivo para los dos.
//
// Abajo, «tu plata por sector»: cuánto de tu plata está en sectores donde la
// mayoría de las acciones sube o baja de fondo y, al tocar, qué papeles tuyos
// cayeron en cada uno (y cuáles no tienen sector). Con «Ocultar saldos» no se
// muestran los %.
//
// El número y sus partes vienen armados de GET /api/termometro
// (backend/termometro.py); las palabras, de utils/termometro.js.

import { useEffect, useState } from 'react'
import { api } from '../../utils/api'
import { usePrivacy } from '../../contexts/PrivacyContext'
import { SECTOR_META } from '../../utils/assetSector'
import {
  LEYENDA, CORTE_DEBIL, CORTE_FIRME, zona, cuando, semanaPasadaTxt, partes, sumaTxt, comoSeArma,
  puntoDelArco, tramo, frasesTuPlata, filasTuPlata,
} from '../../utils/termometro'

// Las palabras de cada sector: las de la torta de la Cartera (las claves son
// las mismas), aunque la clasificación del termómetro sea la del S&P (GICS).
const nombreSector = k => SECTOR_META[k]?.label || k

const TONO_TEXTO = { neg: 'text-rendi-neg', neutro: 'text-ink-0', pos: 'text-rendi-pos' }

export function useTermometro() {
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    let vivo = true
    api.get('/termometro')
      .then(r => { if (vivo) setDatos(r) })
      .catch(() => { if (vivo) setError(true) })
    return () => { vivo = false }
  }, [])
  return { datos, error }
}

/** El arco de 0 a 100 en tres tramos (débil / mixto / firme) y la aguja. */
export function Arco({ puntaje }) {
  const cx = 130, cy = 130, r = 110
  const [x, y] = puntoDelArco(puntaje, cx, cy, r - 18)
  const z = zona(puntaje)
  return (
    <svg viewBox="0 0 260 142" className="w-full max-w-[260px]" role="img"
      aria-label={`Termómetro en ${puntaje} de 100: ${z.texto.toLowerCase()}`}>
      <path d={tramo(0, CORTE_DEBIL, cx, cy, r)} fill="none" strokeWidth="16" className="stroke-rendi-neg/35" />
      <path d={tramo(CORTE_DEBIL, CORTE_FIRME, cx, cy, r)} fill="none" strokeWidth="16" className="stroke-line-2" />
      <path d={tramo(CORTE_FIRME, 100, cx, cy, r)} fill="none" strokeWidth="16" className="stroke-rendi-pos/35" />
      <line x1={cx} y1={cy} x2={x} y2={y} strokeWidth="3" strokeLinecap="round" className="stroke-ink-0" />
      <circle cx={cx} cy={cy} r="6" className="fill-ink-0" />
    </svg>
  )
}

function Parte({ p }) {
  return (
    <div className="flex flex-col gap-1.5 py-3 border-t border-line first:border-t-0 first:pt-0">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[14px] text-ink-0 font-medium">{p.titulo}</span>
        <span className="text-[12px] text-ink-2 tabular shrink-0">{sumaTxt(p)}</span>
      </div>
      <div className="text-[14px] text-ink-1 tabular">{p.valor}</div>
      <div className="h-1.5 rounded-full bg-bg-2 overflow-hidden" aria-hidden="true">
        <div className="h-full rounded-full bg-ink-2" style={{ width: `${Math.max(0, Math.min(100, p.barra))}%` }} />
      </div>
      <div className="text-[12.5px] text-ink-2 leading-snug tabular">{p.detalle}</div>
    </div>
  )
}

const TONO_FRASE = { suben: 'text-rendi-pos', bajan: 'text-rendi-warn', sin: 'text-ink-1' }

/** «Tu plata por sector»: las frases y, al tocar, qué papeles tuyos cayeron en
 *  cada sector (también los que no tienen sector, nombrados). `abierto` lo
 *  puede fijar quien lo dibuja sin estado (la prueba). */
export function TuPlata({ tp, oculto = false, abierto: fijo = null }) {
  const [abierto, setAbierto] = useState(false)
  const ver = fijo ?? abierto
  const frases = frasesTuPlata(tp, nombreSector, oculto)
  if (!frases.length) return null
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-3">
      <div className="text-[12px] text-ink-2 font-medium">Tu plata por sector</div>
      <p className="text-[15px] text-ink-0 font-medium leading-snug">
        {frases.map(f => (
          <span key={f.id}>
            <span className={`tabular ${TONO_FRASE[f.id]}`}>{f.cifra}</span> {f.texto}{' '}
          </span>
        ))}
      </p>
      <button type="button" onClick={() => setAbierto(a => !a)} aria-expanded={ver}
        className="self-start text-[13px] font-medium text-rendi-accent hover:underline min-h-[32px]">
        {ver ? 'Ocultar el detalle' : 'Qué papeles tuyos hay en cada sector'}
      </button>
      {ver && (
        <ul className="flex flex-col divide-y divide-line border border-line rounded-xl">
          {filasTuPlata(tp, nombreSector).map(f => (
            <li key={f.id} className="px-3 py-2.5 flex flex-col gap-0.5">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[14px] text-ink-0 font-medium">{f.nombre}</span>
                <span className="text-[13px] text-ink-1 tabular shrink-0">{oculto ? '—' : `${f.pct} % de tu plata`}</span>
              </div>
              <div className={`text-[12.5px] ${f.sube === true ? 'text-rendi-pos' : f.sube === false ? 'text-rendi-warn' : 'text-ink-2'}`}>
                {f.mercado}
              </div>
              <div className="text-[12.5px] text-ink-1">{f.papeles.join(' · ')}</div>
            </li>
          ))}
        </ul>
      )}
      {ver && (
        <p className="text-[12px] text-ink-2 leading-snug">
          Sectores como los clasifica el S&P 500 (GICS); las acciones argentinas del panel, con el mismo criterio.
          Por eso Alphabet y Meta van en Comunicación y no en Tecnología. Un CEDEAR toma el sector de su empresa.
        </p>
      )}
    </div>
  )
}

/** Lo que se dibuja con una respuesta de GET /api/termometro (sin pedir nada). */
export function TermometroVista({ datos, oculto = false }) {
  if (!datos?.disponible) {
    return (
      <section className="bg-bg-1 border border-line rounded-xl p-4 sm:p-5" aria-label="Termómetro del mercado">
        <h2 className="text-[15px] font-semibold text-ink-0">¿Cómo está el mercado?</h2>
        <p className="text-[13px] text-ink-2 mt-1">
          El termómetro se arma una vez por día con los cierres de la noche. Todavía no hay un número guardado.
        </p>
        <p className="text-[12px] text-ink-2 mt-3">{LEYENDA}</p>
      </section>
    )
  }
  const z = zona(datos.puntaje)
  return (
    <section className="bg-bg-1 border border-line rounded-xl p-4 sm:p-5 flex flex-col gap-4" aria-label="Termómetro del mercado">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h2 className="text-[15px] font-semibold text-ink-0">¿Cómo está el mercado?</h2>
        <span className={`text-[12.5px] tabular ${datos.viejo ? 'text-rendi-warn' : 'text-ink-2'}`}>{cuando(datos)}</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-[minmax(220px,300px)_1fr] gap-4 sm:gap-6">
        <div className="flex flex-col items-center text-center">
          <div className="text-[12px] text-ink-2 font-medium self-start sm:self-center">Termómetro · 0 a 100</div>
          <Arco puntaje={datos.puntaje} />
          <div className="text-[40px] font-semibold tabular leading-none text-ink-0 -mt-1">{datos.puntaje}</div>
          <div className={`text-[16px] font-semibold mt-1 ${TONO_TEXTO[z.tono]}`}>{z.texto}</div>
          <div className="text-[13px] text-ink-2 mt-1 tabular">{semanaPasadaTxt(datos)}</div>
        </div>
        <div className="flex flex-col min-w-0">
          {partes(datos).map(p => <Parte key={p.id} p={p} />)}
        </div>
      </div>
      <TuPlata tp={datos.tu_plata} oculto={oculto} />
      <div className="flex flex-col gap-1 border-t border-line pt-3">
        <p className="text-[12.5px] text-ink-2 leading-snug">{comoSeArma(datos)}</p>
        <p className="text-[12.5px] text-ink-1 leading-snug">{LEYENDA}</p>
      </div>
    </section>
  )
}

export default function Termometro() {
  const { datos, error } = useTermometro()
  const { hidden } = usePrivacy()
  if (error || !datos) return null
  return <TermometroVista datos={datos} oculto={hidden} />
}
