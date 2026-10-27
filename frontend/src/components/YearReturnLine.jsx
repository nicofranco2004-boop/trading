// YearReturnLine — "cómo viene ESTE año, y si le está ganando al mercado".
// ═══════════════════════════════════════════════════════════════════════════
// Ocupa el lugar de `BenchmarksLine`, que comparaba TODA la historia junta en un
// solo número: útil para descubrir que la comparación existe, inútil para saber
// en qué año le ganaste.
//
// ⚠️ NO REPITE LA TABLA DEL AÑO POR AÑO. La misma tabla en dos pantallas es
// deuda: dos lugares para arreglar, dos lugares para que se contradigan. Acá va
// el año en curso y una puerta; el detalle vive en Reportes, una sola vez.
//
// El número sale de `/api/reports/years` (motor canónico `twr.curva_indexada`),
// el mismo que publica Reportes. No hay un cálculo propio de esta card.

import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import useReportYears from '../hooks/useReportYears'
import { useCurrency } from '../contexts/CurrencyContext'
import { pctSigned } from '../utils/format'
import { anioPublicado, detalleVsInflacion } from '../utils/anioPublicado'
import { Veredicto } from './VeredictoChip'

const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
               'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']

// "2026-06-30" → "30 de junio". La fecha en palabras porque va dentro de una
// oración ("desde el 30 de junio"), no en una columna de números.
export function fechaEnPalabras(iso) {
  if (!iso || iso.length < 10) return ''
  return `${parseInt(iso.slice(8, 10), 10)} de ${MESES[parseInt(iso.slice(5, 7), 10) - 1]}`
}

// Sin `modo`, el hook usa la elección guardada del usuario: el inicio del celular
// lo monta sin modo y medía siempre en certero aunque la app estuviera en estimado.
export default function YearReturnLine({ modo, className = '' }) {
  const { currency } = useCurrency()
  const moneda = currency === 'ARS' ? 'ars' : 'usd'
  const { current, loading, refreshing } = useReportYears('global', modo, moneda)

  // ⚠️ EL HUECO SE RESERVA DESDE EL PRIMER INSTANTE. El número del año necesita el
  // valor VIVO de la cartera, y bajar los precios tarda unos segundos la primera
  // vez (medido: 6,2 s con el caché frío, 0,0 s después). Sin este esqueleto la
  // card aparecía de golpe varios segundos tarde y empujaba todo lo de abajo.
  if (loading && !current) {
    return (
      <div className={`h-full bg-bg-1 border border-line rounded-xl px-4 py-3.5 ${className}`}>
        <div className="text-[12px] text-ink-3 leading-none font-medium">Este año</div>
        <div className="mt-2 h-[22px] w-24 rounded bg-bg-2 esqueleto" />
        <div className="mt-2.5 h-[20px] w-32 rounded-full bg-bg-2 esqueleto" />
      </div>
    )
  }
  if (!current) return null

  // ⚠️ SI EL AÑO ENTERO NO SE PUEDE MEDIR, SE MUESTRA EL TRAMO QUE SÍ.
  // Reportado desde producción: la card decía "Todavía no se puede medir · sin dos
  // fotos a mercado" mientras la card de AL LADO decía "Desde que medimos · +5,9 %
  // · 74 días". Había sesenta fotos; lo que no llegaba era a cubrir el año. El
  // motor sabe medir ese tramo, así que se publica con la fecha desde la que corre
  // — "desde el 30 de junio" es verdadero; llamarlo "2026" sería la mentira.
  // El número y sus dos veredictos salen del MISMO tramo, en el modo pedido: lo
  // decide `anioPublicado`, la misma función que usa Reportes. Antes acá se
  // escribía `vsInfl = parcial ? null : …` y el tramo mostraba "vs el S&P" sin
  // "vs la inflación".
  const anio = anioPublicado(current)
  const { parcial, pct, vsSp, vsInfl, motivoInfl } = anio
  const positivo = pct != null && pct >= 0

  return (
    <div className={`h-full bg-bg-1 border border-line rounded-xl px-4 py-3.5 flex flex-col
                     transition-opacity ${refreshing ? 'opacity-60' : ''} ${className}`}>
      <div className="text-[12px] text-ink-3 leading-none font-medium">
        Este año · <span className="tabular">{current.year}</span>
      </div>

      {pct != null ? (
        <div className={`mt-2 font-semibold tabular num leading-none text-[22px] tracking-tight ${
          positivo ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
          {pctSigned(pct / 100)}
        </div>
      ) : (
        // ⚠️ EL VACÍO HABLA. Un hueco donde había un número se lee como "se rompió
        // algo"; el motivo del motor ya viene redactado y dice qué falta.
        <div className="mt-2 text-[13px] text-ink-2 font-medium leading-snug">
          Todavía no se puede medir
        </div>
      )}

      {pct != null && (vsSp != null || vsInfl != null || motivoInfl) && (
        <div className="flex flex-wrap gap-1.5 mt-2.5">
          <Veredicto nombre="S&P 500" articulo="el" pp={vsSp} />
          {/* El veredicto contra la inflación se calcula SIEMPRE en pesos (el backend
              convierte el retorno con `twr.vs_inflacion_ar`), así que aparece en las
              dos monedas. En dólares, el globo aclara contra qué número se restó. */}
          {/* Sin veredicto pero con número, la pastilla aparece "sin medir" con el
              motivo: un "vs el S&P" solo, sin la inflación al lado, se leyó
              como un error de la app. */}
          <Veredicto
            nombre="inflación" articulo="la" pp={vsInfl}
            detalle={detalleVsInflacion(anio, moneda === 'ars')}
            motivo={motivoInfl}
          />
        </div>
      )}

      {pct == null && current.motivo_texto && (
        <p className="text-[11px] text-ink-3 leading-snug mt-1.5">{current.motivo_texto}</p>
      )}

      {/* Pie — con qué está hecho el número, y la puerta al detalle. `mt-auto`
          para que quede abajo aunque la card se estire al alto de sus hermanas. */}
      <div className="flex items-center justify-between gap-2 flex-wrap mt-auto pt-2.5">
        <span className="text-[11px] text-ink-3 leading-none">
          {parcial ? `desde el ${fechaEnPalabras(anio.desde)}`
            : pct == null ? 'todavía sin dos mediciones que cubran el año'
            : current.basis === 'contable' ? 'de tu historia importada'
            : 'medido a mercado'}
        </span>
        <Link
          to="/reportes"
          className="text-[11.5px] text-rendi-accent hover:text-rendi-accent/80 inline-flex items-center gap-0.5 transition-colors font-medium whitespace-nowrap"
        >
          Ver año por año <ArrowRight size={11} strokeWidth={1.75} />
        </Link>
      </div>
    </div>
  )
}
