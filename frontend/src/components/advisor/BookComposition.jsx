// BookComposition — las tres tortas del libro del asesor.
// ═══════════════════════════════════════════════════════════════════════════
// La misma cartera mirada por tres ejes, ponderada por el valor de TODAS las
// carteras que el asesor administra:
//   • por tipo de activo  — en qué instrumentos está el libro
//   • por activo          — en qué papeles concretos
//   • por sector          — a qué parte de la economía está expuesto
//
// ── De dónde salen los números ────────────────────────────────────────────
// GET /api/advisor/book/composition devuelve filas YA VALUADAS Y AGREGADAS por
// (activo, asset_type, mercado). El backend valúa porque /api/prices tiene un
// cap duro de 60 símbolos que TRUNCA EN SILENCIO, y un libro toca cientos de
// tickers: valuar desde el navegador no daría un error, daría una torta
// incompleta con pinta de correcta.
//
// La CLASIFICACIÓN, en cambio, la hace acá — con classifyAsset / classifySector,
// los mismos que usa el Dashboard de cada cliente, sin una línea de diferencia.
// Es la única forma de que la torta del libro y la de la cartera del cliente no
// puedan contradecirse.
//
// ── Por qué el total no es el mismo número que el hero ────────────────────
// El "Total administrado" de arriba sale de los snapshots nocturnos. Esta
// composición valúa las posiciones AHORA con los últimos precios conocidos, y
// además suma los plazos fijos, que el snapshot no incluye. Son dos
// mediciones distintas de la misma cosa y no tienen por qué coincidir al
// dólar: el pie de la sección lo dice explícitamente en vez de dejar dos
// números que se contradicen sin explicación.

import { useMemo } from 'react'
import { PieChart } from 'lucide-react'
import CompositionDonut, { UnclassifiedNote } from '../CompositionDonut'
import InfoTooltip from '../InfoTooltip'
import AskAIAbout from '../ai/AskAIAbout'
import { computeClassBreakdown } from '../../utils/assetClass'
import { computeSectorBreakdown } from '../../utils/assetSector'
import {
  assetSlicesFromRows, mostHeldAssets, pfSlice, realizedToOps,
  toBookCompositionAiParams, DEFAULT_TOP_ASSETS,
} from '../../utils/bookComposition'
import { fmtUsd, fmtArs } from '../../utils/format'
import { useMoneyFormat } from '../../contexts/CurrencyContext'

// El color de la porción "Plazo fijo" en el vocabulario de clases de activo —
// para que la porción sintética se vea igual en las tres tortas.
const PF_COLOR = '#C98A2E'

export default function BookComposition({ data, error = false }) {
  // ⚠️ Todos los hooks ANTES de cualquier return. Esta página ya tiene un bug
  // latente de Rules-of-Hooks en BookEvolution (useMoneyFormat después de dos
  // early returns): si `series` pasa de <2 a ≥2 puntos entre renders, React
  // tira y se lleva la pantalla entera al error boundary. Acá no.
  const { isArs, convert } = useMoneyFormat()
  const rows = data?.rows
  const included = data?.included

  // Con unidad explícita (USD 1.234 / ARS 1.234), no el número pelado que usa
  // el resto de esta página: acá los montos aparecen también EN PROSA (el pie
  // de la sección), y "incluye 886 en plazos fijos" no dice en qué moneda.
  // Sin decimales — son cifras de libro, no de una posición.
  const fmt = useMemo(
    () => (v) => (isArs ? fmtArs(convert(v)) : fmtUsd(v, 0)),
    [isArs, convert],
  )

  // Lo cerrado + la renta, con forma de operaciones: sin esto el "Resultado"
  // de cada porción sería solo lo no realizado, y un bono que rindió todo en
  // cupones se leería como si no hubiera rendido nada.
  const ops = useMemo(() => realizedToOps(data?.realized_by_asset), [data])

  const clase = useMemo(
    () => computeClassBreakdown(rows || [], [], [pfSlice(included, 'plazo_fijo')].filter(Boolean), ops),
    [rows, included, ops],
  )
  const sector = useMemo(
    () => computeSectorBreakdown(rows || [], [], [pfSlice(included, 'renta_fija')].filter(Boolean), ops),
    [rows, included, ops],
  )
  // Ojo: la torta por activo queda a propósito SIN resultado. El P&L por
  // activo cross-cliente ya lo muestra la sección Estrella de esta misma
  // pantalla, y es OTRA cosa (solo no realizado). Dos números distintos para
  // "cómo le fue a AAPL en el libro", a diez centímetros uno del otro, es el
  // bug clásico de esta app. Acá la pregunta es cuánto pesa.
  const activo = useMemo(
    () => assetSlicesFromRows(
      rows || [],
      [pfSlice(included, 'plazo_fijo', 'Plazos fijos', PF_COLOR)].filter(Boolean),
    ),
    [rows, included],
  )
  const difundidos = useMemo(() => mostHeldAssets(rows || []), [rows])

  // Packets de la IA. Los topics son `book.composition_*` y NO
  // `book.distribution_*`: `book.distribution` ya significa otra cosa del
  // lado asesor (cuántos clientes en verde/rojo, la card "¿Cómo vienen tus
  // clientes?") y el prompt del libro ya se la describe al modelo con ese
  // sentido.
  const aiOpts = useMemo(
    () => ({ clients: data?.clients, mostHeld: difundidos }),
    [data, difundidos],
  )
  const aiClase = useMemo(() => toBookCompositionAiParams(clase, aiOpts), [clase, aiOpts])
  const aiSector = useMemo(() => toBookCompositionAiParams(sector, aiOpts), [sector, aiOpts])

  if (error && !data) return null
  if (!data || !rows?.length) return null
  if (!(clase.total > 0)) return null

  const totalTxt = fmt(clase.total)
  const excluidas = excludedPhrase(data.excluded)

  return (
    <section className="mb-4">
      <div className="flex items-baseline justify-between gap-3 flex-wrap mb-2.5">
        <h2 className="flex items-center gap-2 text-[13px] font-semibold text-ink-0">
          <PieChart size={13} strokeWidth={1.75} className="text-data-violet" />
          En qué está tu libro
          <InfoTooltip size={12} align="left">
            <p className="font-semibold text-ink-0">Qué estás viendo</p>
            <p>
              La suma de las carteras de todos tus clientes, mirada por tres ejes.
              Cada activo pesa por su valor, así que un cliente grande pesa más
              que uno chico — es la composición del libro, no el promedio de las
              carteras.
            </p>
            <p>
              Se clasifica con el mismo criterio que ve cada cliente en su
              Dashboard: primero el mercado (BYMA o exterior), después el
              instrumento. Por eso AAPL en un broker argentino es un CEDEAR y en
              uno del exterior es la acción.
            </p>
            <p className="text-ink-3">
              Incluye efectivo y plazos fijos, así que las tres tortas suman el
              mismo total: {totalTxt}.
            </p>
          </InfoTooltip>
        </h2>
        <span className="text-[11px] text-ink-3 tabular-nums">
          {totalTxt} · {data.clients} {data.clients === 1 ? 'cliente' : 'clientes'}
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <AskAIAbout
          topic="book.composition_type"
          params={aiClase}
          subtitle="Composición del libro por tipo de activo"
          rounded={false}
        >
        <CompositionDonut
          title="Por tipo de activo"
          items={clase.items}
          fmt={fmt}
          info={(
            <>
              <p className="font-semibold text-ink-0">Cómo se calcula</p>
              <p>
                Cada posición de cada cliente se clasifica por dónde cotiza y qué
                instrumento es. Un CEDEAR y la acción del exterior son porciones
                distintas aunque compartan ticker: no son el mismo riesgo.
              </p>
              <p className="text-ink-3">
                Incluye el efectivo y los plazos fijos de todas las carteras.
              </p>
            </>
          )}
          footnote={<UnclassifiedNote data={clase.unclassified} kind="tipo" />}
        />
        </AskAIAbout>

        <CompositionDonut
          title="Por activo"
          subtitle={`top ${DEFAULT_TOP_ASSETS}`}
          items={activo.items}
          fmt={fmt}
          // El agregador ya cortó en top-N + "Resto": el donut no tiene que
          // volver a agrupar (ver la cabecera de bookComposition.js).
          maxSlices={activo.items.length}
          minSlicePct={0}
          info={(
            <>
              <p className="font-semibold text-ink-0">Cómo se calcula</p>
              <p>
                Los {DEFAULT_TOP_ASSETS} activos más grandes del libro por valor.
                Todo lo demás va a “Resto”, que se despliega para ver qué hay
                adentro.
              </p>
              <p>
                El mismo papel comprado de dos formas es una sola porción: el
                CEDEAR de AAPL en Balanz y la acción en un broker del exterior
                son la misma exposición a Apple.
              </p>
              <p className="text-ink-3">
                Un libro toca muchos más activos que una cartera sola, así que
                acá el corte es explícito en vez de dejar todo en “otros”.
              </p>
            </>
          )}
          footnote={difundidos.length > 0 && (
            <>
              <span className="text-ink-2">En más carteras:</span>{' '}
              {difundidos.map((a, i) => (
                <span key={a.asset}>
                  {i > 0 && ' · '}
                  <span className="font-mono text-ink-1">{a.asset}</span>
                  {' '}<span className="tabular-nums">({a.clients})</span>
                </span>
              ))}
              <span className="text-ink-3">
                {' '}— en cuántos clientes está, más allá de cuánto pese.
              </span>
            </>
          )}
        />

        <AskAIAbout
          topic="book.composition_sector"
          params={aiSector}
          subtitle="Composición del libro por sector"
          rounded={false}
        >
        <CompositionDonut
          title="Por sector"
          items={sector.items}
          fmt={fmt}
          info={(
            <>
              <p className="font-semibold text-ink-0">Cómo se calcula</p>
              <p>
                A qué parte de la economía está expuesto el libro. Un CEDEAR
                cuenta en el sector de su empresa subyacente: un CEDEAR de NVDA
                es exposición a semiconductores.
              </p>
              <p className="text-ink-3">
                Bonos, letras, FCI, plazos fijos y efectivo no tienen sector
                económico — van a su propia porción.
              </p>
            </>
          )}
          footnote={<UnclassifiedNote data={sector.unclassified} kind="sector" />}
        />
        </AskAIAbout>
      </div>

      {/* El pie que evita el número contradictorio: esta valuación NO es la
          del hero, y decirlo es más barato que dejar al asesor descubriendo
          solo que dos totales de la misma pantalla no cierran. */}
      <p className="text-[10.5px] text-ink-3 leading-snug mt-2">
        Valuado con los últimos precios conocidos
        {data.as_of ? ` (al ${data.as_of})` : ''}
        {included?.plazos_fijos_count > 0 && (
          <> e incluye {fmt(included.plazos_fijos_usd)} en plazos fijos</>
        )}
        , así que puede no coincidir exacto con el total administrado de arriba,
        que sale de los snapshots de la noche.
        {excluidas && <> {excluidas}</>}
      </p>
    </section>
  )
}


/**
 * excludedPhrase — qué quedó afuera de la valuación, en una frase.
 *
 * Se dice SIEMPRE que haya algo excluido, aunque sea una posición: una torta
 * que calla lo que dejó afuera se lee como si cubriera todo. Y se aclara que
 * sin precio no es lo mismo que valer cero — es justamente la trampa que el
 * motor evita al excluirlas en vez de contarlas en cero.
 */
function excludedPhrase(ex) {
  const sinPrecio = ex?.no_price || 0
  const huerfanas = ex?.orphan_broker || 0
  const n = sinPrecio + huerfanas
  if (n === 0) return null

  const cola = sinPrecio > 0 ? ' Sin precio no es lo mismo que valer cero.' : ''
  const verbo = n === 1 ? 'Quedó afuera 1 posición' : `Quedaron afuera ${n} posiciones`
  if (sinPrecio > 0 && huerfanas > 0) {
    return `${verbo}: ${sinPrecio} sin precio conocido y ${huerfanas} con el broker borrado.${cola}`
  }
  if (sinPrecio > 0) return `${verbo} sin precio conocido.${cola}`
  return `${verbo} con el broker borrado.`
}
