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

import { useMemo, useState } from 'react'
import { PieChart } from 'lucide-react'
import CompositionDonut, { UnclassifiedNote } from '../CompositionDonut'
import CompositionByRisk from '../CompositionByRisk'
import InfoTooltip from '../InfoTooltip'
import AskAIAbout from '../ai/AskAIAbout'
import AssetClientsModal from './AssetClientsModal'
import { computeClassBreakdown, classifyAsset } from '../../utils/assetClass'
import { computeSectorBreakdown, classifySector } from '../../utils/assetSector'
import {
  assetSlicesFromRows, mostHeldAssets, pfSlice, realizedToOps, attachSpread,
  riskMixFromBreakdown, toBookCompositionAiParams, DEFAULT_TOP_ASSETS,
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
  // El activo cuyo detalle por cliente está abierto ({asset, market, label}).
  const [detalle, setDetalle] = useState(null)
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

  // El % de cada porción es AGRUPADO (Σresultado ÷ Σcosto): el retorno de la
  // plata efectivamente puesta ahí, que es el único que se reconcilia con los
  // montos de al lado. `attachSpread` le pega el rango entre clientes, que es
  // lo que el agrupado esconde — "+9,8% en AAPL" puede ser un cliente en −20%
  // y otro en +40%.
  const spread = data?.return_spread
  const clase = useMemo(
    () => attachSpread(
      computeClassBreakdown(rows || [], [], [pfSlice(included, 'plazo_fijo')].filter(Boolean), ops),
      spread, { rows, classify: classifyAsset }),
    [rows, included, ops, spread],
  )
  const sector = useMemo(
    () => attachSpread(
      computeSectorBreakdown(rows || [], [], [pfSlice(included, 'renta_fija')].filter(Boolean), ops),
      spread, { rows, classify: classifySector }),
    [rows, included, ops, spread],
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

  // El corte grueso sale de PLEGAR la torta por tipo, no de recorrer las filas
  // otra vez: así la barra y las tortas suman exactamente lo mismo por
  // construcción, incluidas las porciones sintéticas (los plazos fijos).
  const riesgo = useMemo(() => riskMixFromBreakdown(clase), [clase])

  // Packets de la IA. Los topics son `book.composition_*` y NO
  // `book.distribution_*`: `book.distribution` ya significa otra cosa del
  // lado asesor (cuántos clientes en verde/rojo, la card "¿Cómo vienen tus
  // clientes?") y el prompt del libro ya se la describe al modelo con ese
  // sentido.
  const aiOpts = useMemo(
    () => ({ clients: data?.clients, mostHeld: difundidos, spread }),
    [data, difundidos, spread],
  )
  const aiClase = useMemo(() => toBookCompositionAiParams(clase, aiOpts), [clase, aiOpts])
  const aiSector = useMemo(() => toBookCompositionAiParams(sector, aiOpts), [sector, aiOpts])

  // Si falló el fetch y no hay nada que mostrar, avisamos en vez de
  // desaparecer: la sección que se esfuma se lee como "esto todavía no existe"
  // o "mi libro no tiene composición", no como un error recuperable con F5.
  // Mismo criterio que BookEvolution al lado, que ya distingue error de vacío.
  if (error && !data) {
    return (
      <section className="mb-4 bg-bg-1 border border-line/60 rounded-xl p-4">
        <h2 className="flex items-center gap-2 text-[13px] font-semibold text-ink-0 mb-1">
          <PieChart size={13} strokeWidth={1.75} className="text-data-violet" />
          En qué está tu libro
        </h2>
        <p className="text-[11.5px] text-ink-3">
          No pudimos calcular la composición recién — es la parte más pesada del
          libro. Recargá la página para reintentar.
        </p>
      </section>
    )
  }
  if (!data) return null
  // El corte NO es por `rows`: los plazos fijos no viajan ahí (entran por
  // `included` como porción sintética), así que un libro cuyos clientes solo
  // cargaron plazos fijos tiene rows vacío y tortas perfectamente válidas.
  // Cortar por rows le hacía desaparecer la sección entera.
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

      <CompositionByRisk
        items={riesgo.items}
        total={riesgo.total}
        fmt={fmt}
        className="mb-3"
        info={(
          <>
            <p className="font-semibold text-ink-0">Cómo se calcula</p>
            <p>
              El mismo corte que las tortas de abajo, agrupado en dos lados y el
              efectivo: cuánto del libro se mueve con el mercado y cuánto no.
              Suma exactamente el mismo total.
            </p>
            <p>
              La <strong>cripto cuenta como renta variable</strong>: no es una
              acción, pero es un activo de riesgo. La torta por tipo la muestra
              aparte si querés ver cuánto pesa.
            </p>
            <p className="text-ink-3">
              Los FCI cuentan como renta variable. El importador no distingue el
              tipo de fondo, así que un money market queda contado como
              exposición al mercado aunque rinda parecido a un plazo fijo.
            </p>
          </>
        )}
      />

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
          onAssetClick={setDetalle}
          info={(
            <>
              <p className="font-semibold text-ink-0">Cómo se calcula</p>
              <p>
                Cada posición de cada cliente se clasifica por dónde cotiza y qué
                instrumento es. Un CEDEAR y la acción del exterior son porciones
                distintas aunque compartan ticker: no son el mismo riesgo.
              </p>
              <p>
                El rendimiento de cada porción es el de la plata junta: resultado
                total sobre capital total. Al desplegar un activo verás además
                cuánto se abren los clientes entre sí — el promedio puede tapar
                a uno que está en rojo.
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
          onAssetClick={setDetalle}
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
      {detalle && (
        <AssetClientsModal
          asset={detalle.asset}
          market={detalle.market}
          label={detalle.label}
          fmt={fmt}
          onClose={() => setDetalle(null)}
        />
      )}

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
