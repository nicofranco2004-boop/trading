// MapaCartera — «Mapa de tu cartera», en el Panorama de Análisis técnico
// (lienzo «1 · Panorama», aprobado por Nico el 30/10): un cuadrito por activo,
// de tamaño proporcional a lo que pesa y pintado según su tendencia de largo
// plazo (verde alcista, rojo bajista, punteado sin lectura). Cada cuadrito
// lleva a la ficha del activo.
// ════════════════════════════════════════════════════════════════════════════
// Una sola pieza para compu y celular (R6): la caja tiene siempre la misma
// proporción (PROPORCION) y los cuadritos van en % de la caja; lo que no entra
// en un cuadrito chico (el %, después el nombre) se esconde y queda en el globo.
//
// Los cuadritos y su lugar los arma utils/mapaCartera.js con el peso y la
// tendencia de las filas de Tu lista (la misma cuenta del % alcista). Con
// «Ocultar saldos» todos del mismo tamaño, en orden alfabético y sin %: el
// tamaño y el orden también dicen cuánto pesa cada uno.

import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { cuadritosDelMapa, ubicarCuadritos, PROPORCION } from '../utils/mapaCartera'
import { pesoVisible, deTuCartera } from '../utils/parteDeTuPlata'

const TONO = {
  alcista: 'bg-rendi-pos/15 border border-rendi-pos/40',
  bajista: 'bg-rendi-neg/15 border border-rendi-neg/40',
  sin: 'bg-ink-3/10 border border-dashed border-ink-3/60',
  otros: 'bg-bg-2 border border-line',
}
const PALABRA = { alcista: 'tendencia alcista', bajista: 'tendencia bajista', sin: 'sin lectura', otros: '' }

function Cuadrito({ c, r, rutaOtros, hidden }) {
  const peso = c.peso == null ? null : pesoVisible(c.peso, hidden)
  // Lo que entra según el tamaño (en % de la caja): el nombre en casi todos,
  // el % sólo en los que tienen alto para dos renglones.
  const conNombre = r.w >= 7 && r.h >= 13
  const conPct = peso != null && r.w >= 10 && r.h >= 26
  const grande = r.w >= 22 && r.h >= 40
  const globo = [c.nombre, c.peso == null ? null : deTuCartera(c.peso, hidden), PALABRA[c.tendencia] || null]
    .filter(Boolean).join(' · ')
  const cuerpo = (
    <span className={`h-full w-full rounded-lg ${TONO[c.tendencia]} px-2 py-1.5 sm:px-2.5 sm:py-2 flex flex-col justify-between overflow-hidden text-ink-0 transition-colors`}>
      {conNombre && (
        <b className={`font-semibold leading-tight truncate ${grande ? 'text-[14px] sm:text-[16px]' : 'text-[11.5px] sm:text-[13px]'}`}>{c.nombre}</b>
      )}
      {conPct && <span className="text-[11px] sm:text-[12px] text-ink-1 tabular">{peso}</span>}
    </span>
  )
  const lugar = { left: `${r.x}%`, top: `${r.y}%`, width: `${r.w}%`, height: `${r.h}%` }
  const ruta = c.ruta ? `/activo/${encodeURIComponent(c.ruta)}` : c.tendencia === 'otros' ? rutaOtros : null
  if (!ruta) {
    return <li className="absolute p-0.5" style={lugar} title={globo} aria-label={globo}>{cuerpo}</li>
  }
  return (
    <li className="absolute p-0.5" style={lugar}>
      <Link to={ruta} title={globo} aria-label={globo} className="block h-full w-full rounded-lg hover:brightness-125 focus-visible:outline focus-visible:outline-2 focus-visible:outline-rendi-accent">
        {cuerpo}
      </Link>
    </li>
  )
}

/** `filas`: las de Tu lista; `sinLectura`: los nombres del grupo «sin lectura»
 *  del % (senales_semana.reparto); `rutaOtros`: a dónde lleva «y N más». */
const NINGUNO = []

export default function MapaCartera({ filas, cargando, error, hidden, sinLectura = NINGUNO, rutaOtros }) {
  const cuadritos = useMemo(() => cuadritosDelMapa(filas, { hidden, sinLectura }), [filas, hidden, sinLectura])
  const lugares = useMemo(() => ubicarCuadritos(cuadritos.map(c => c.peso)), [cuadritos])

  return (
    <section aria-label="Mapa de tu cartera" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-3 min-w-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <h2 className="text-[15px] font-semibold text-ink-0">Mapa de tu cartera</h2>
        <span className="text-[12px] text-ink-2 font-medium">
          {hidden ? 'color = tendencia de largo plazo' : <><span className="sm:hidden">tamaño = cuánto pesa</span><span className="hidden sm:inline">tamaño = cuánto pesa · color = tendencia de largo plazo</span></>}
        </span>
      </div>
      {error ? (
        <p className="text-[13.5px] text-ink-1">En este momento no pudimos cargar tus activos. Probá recargar la página en unos minutos.</p>
      ) : cargando ? (
        <div className="w-full rounded-lg bg-bg-2/40 esqueleto" style={{ aspectRatio: PROPORCION }} aria-label="Cargando el mapa de tu cartera" />
      ) : !cuadritos.length ? (
        <p className="text-[13.5px] text-ink-1">Cuando cargues tus activos, acá vas a ver cuánto pesa cada uno y hacia dónde va su precio.</p>
      ) : (
        <>
          {hidden && <p className="text-[12px] text-ink-2">Con los saldos ocultos, todos van del mismo tamaño.</p>}
          <ul className="relative w-full" style={{ aspectRatio: PROPORCION }} aria-label="Tus activos">
            {cuadritos.map((c, i) => <Cuadrito key={c.clave} c={c} r={lugares[i]} rutaOtros={rutaOtros} hidden={hidden} />)}
          </ul>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-2">
            <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className={`w-2.5 h-2.5 rounded-xs ${TONO.alcista}`} />Alcista</span>
            <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className={`w-2.5 h-2.5 rounded-xs ${TONO.bajista}`} />Bajista</span>
            <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className={`w-2.5 h-2.5 rounded-xs ${TONO.sin}`} />Sin lectura (bonos, fondos, efectivo)</span>
          </div>
        </>
      )}
    </section>
  )
}
