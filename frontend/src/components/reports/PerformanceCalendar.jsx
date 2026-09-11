// PerformanceCalendar — el año por año de Reportes (V3).
// ═══════════════════════════════════════════════════════════════════════════
// Dos piezas:
//   1) KPI strip 12M (acumulado realizado, meses positivos, trades)
//   2) Una fila por año: el CIERRE del año (del motor canónico, vía
//      `/api/reports/years`), un gráfico de BARRAS mes a mes, los veredictos
//      contra el S&P y la inflación, y las métricas del año.
//
// ⚠️ ACÁ HABÍA UN HEATMAP DE DOCE CUADRADOS con el número adentro, y tenía dos
// problemas: doce números chicos compiten entre sí —para leer la forma del año
// había que leerlos todos— y no entran en una laptop, porque un cuadrado con
// texto adentro no se puede comprimir. Las barras muestran la forma sin leer un
// solo número y sí se comprimen; el detalle aparece al pasar el mouse.
//
// Visual: barras en los verdes/rojos semánticos, números en Geist + tabular.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Lock } from 'lucide-react'
import { useCurrency, useMoneyFormat } from '../../contexts/CurrencyContext'
import { fechaEnPalabras } from '../YearReturnLine'

function monthNum(period_key) {
  if (!period_key) return null
  const m = period_key.match(/-(\d{1,2})/)
  return m ? parseInt(m[1], 10) : null
}

// ─── El gráfico de barras de un año ─────────────────────────────────────────
//
// ⚠️ LA ESCALA ES PROPIA DE CADA AÑO, Y POR ESO SE DECLARA. Cada gráfico usa
// todo su alto, así que se ve lleno — pero un mes de +2 % en un año tranquilo
// dibuja la MISMA barra que uno de +30 % en otro, y el ojo compara alturas sin
// preguntar. El rótulo "barra más alta = X %" de abajo no es decoración: es lo
// único que evita esa lectura. Si algún día se pasa a escala común, se borra el
// rótulo en el mismo movimiento.
const MES_INICIAL = ['E', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D']

// Cuánto del alto de la caja ocupa la barra más extrema. Por debajo de 100 para
// que no toque el borde y se lea como cortada.
const ALTO_MAX_PCT = 92

function BarrasDelAnio({ cells, money, enPesos, tipAbajo }) {
  const [encima, setEncima] = useState(null)

  const meses = cells.map(({ month }) => {
    const m = month?.metrics
    if (!month || !month.is_relevant || m?.delta_pct == null) return null
    return {
      pct: m.delta_pct,
      usd: m.delta_usd,
      // Sólo lo que se cerró vendiendo. NO es lo mismo que `delta_usd`, que
      // incluye lo que se movieron las posiciones que siguen abiertas.
      realizado: m.realized_pnl,
      label: month.period_label,
      actual: month.is_current,
    }
  })

  const conDato = meses.filter(Boolean)
  // El piso de 0,5 evita que un año plano dibuje barras enormes por dividir por
  // casi cero.
  const max = Math.max(0.5, ...conDato.map(m => Math.abs(m.pct)))
  const activo = encima != null ? meses[encima] : null

  return (
    <div className="relative">
      {activo && (
        <div
          className="absolute z-10 pointer-events-none bg-bg-3 border border-line-2
                     rounded-lg px-2.5 py-1.5 whitespace-nowrap"
          style={{
            // ⚠️ EN LA PRIMERA FILA EL GLOBO VA PARA ABAJO. Arriba se salía de la
            // tarjeta y quedaba cortado a la mitad: el contenedor de las bandas
            // lleva scroll horizontal —para que las barras no se recorten— y un
            // `overflow-x` recorta también en vertical. No hay lugar arriba de la
            // primera banda, así que ahí se abre hacia abajo.
            ...(tipAbajo ? { top: '100%', marginTop: '6px' } : { top: '-6px' }),
            // Y se ancla al centro de su columna, salvo en las puntas: con doce
            // columnas, enero y diciembre lo mandarían fuera de la caja.
            ...(encima <= 1 ? { left: 0 }
              : encima >= 10 ? { right: 0 }
                : { left: `${((encima + 0.5) / 12) * 100}%` }),
            transform: [
              encima > 1 && encima < 10 ? 'translateX(-50%)' : '',
              tipAbajo ? '' : 'translateY(-100%)',
            ].filter(Boolean).join(' ') || 'none',
          }}
        >
          <div className="text-[10.5px] text-ink-3 leading-none">{activo.label}</div>
          <div className="flex items-baseline gap-1.5 mt-1 leading-none">
            <b className={`text-[13px] font-semibold tabular ${
              activo.pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
              {activo.pct >= 0 ? '+' : '−'}{Math.abs(activo.pct).toFixed(2)}%
            </b>
            <span className="text-ink-3 text-[11px]">·</span>
            <b className={`text-[13px] font-semibold tabular ${
              activo.usd >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
              {money.fmtMoney(activo.usd, { signed: true })}
            </b>
          </div>
          {/* ⚠️ EN PESOS EL % Y EL MONTO NO ESTÁN EN EL MISMO PESO. El porcentaje lo
              mide el motor con el dólar de CADA PUNTA, así que incluye la devaluación
              de ese mes; el monto sale en dólares y lo convierte la pantalla al dólar
              de HOY (es deliberado: convertirlo también en el servidor lo convertiría
              dos veces, ver `_pct_en_pesos`). Puestos uno al lado del otro invitan a
              una cuenta que no da, así que el globo dice a qué dólar está el monto.
              Medido: mayo 2025 = +3,98 % y +$629.063, que son US$409 al dólar de hoy. */}
          {enPesos && (
            <div className="text-[10px] text-ink-3 mt-1 leading-none">al dólar de hoy</div>
          )}
          {/* El renglón de abajo sólo cuando hubo ventas: en un mes sin operaciones
              cerradas, un "realizado: 0" no informa, ocupa. */}
          {!!activo.realizado && (
            <div className="text-[10.5px] text-ink-3 mt-1 leading-none tabular">
              de operaciones cerradas: {money.fmtMoney(activo.realizado, { signed: true })}
            </div>
          )}
        </div>
      )}

      <div className="flex items-stretch gap-[3px] h-[72px] relative">
        <div className="absolute inset-x-0 top-1/2 h-px bg-line-2 pointer-events-none" />
        {meses.map((m, i) => (
          <div
            key={i}
            onMouseEnter={() => setEncima(i)}
            onMouseLeave={() => setEncima(prev => (prev === i ? null : prev))}
            onFocus={() => setEncima(i)}
            onBlur={() => setEncima(null)}
            tabIndex={m ? 0 : -1}
            aria-label={m
              ? `${m.label}: ${m.pct >= 0 ? '+' : '−'}${Math.abs(m.pct).toFixed(2)} por ciento, ${money.fmtMoney(m.usd, { signed: true })}`
              : undefined}
            className={`flex-1 min-w-0 relative rounded-sm transition-colors
                        focus:outline-none focus-visible:ring-1 focus-visible:ring-rendi-accent
                        ${encima === i ? 'bg-ink-0/5' : ''}
                        ${m?.actual ? 'ring-1 ring-inset ring-rendi-pos/40' : ''}`}
          >
            {m ? (
              <div
                className={`absolute left-[14%] right-[14%] rounded-xs transition-colors ${
                  m.pct >= 0
                    ? `bottom-1/2 ${encima === i ? 'bg-green-200' : 'bg-rendi-pos'}`
                    : `top-1/2 ${encima === i ? 'bg-red-100' : 'bg-rendi-neg'}`}`}
                style={{ height: `${Math.max(2, (Math.abs(m.pct) / max) * ALTO_MAX_PCT / 2)}%` }}
              />
            ) : (
              // ⚠️ UN MES SIN MEDIR NO ES UN MES QUE DIO CERO. Una barra de altura
              // cero se leería como "plano"; esta rayita gris dice "acá no hay dato".
              <div className="absolute left-[32%] right-[32%] top-1/2 -mt-px h-0.5 rounded-xs bg-line-2" />
            )}
          </div>
        ))}
      </div>

      <div className="flex gap-[3px] mt-1.5">
        {MES_INICIAL.map((l, i) => (
          <span
            key={i}
            className={`flex-1 min-w-0 text-center text-[9px] font-semibold tracking-wide leading-none
                        ${encima === i ? 'text-ink-0' : 'text-ink-3'}`}
          >
            {l}
          </span>
        ))}
      </div>

      {conDato.length > 0 && (
        <div className="text-[10px] text-ink-3 text-right mt-1.5 tabular leading-none">
          barra más alta = {max.toFixed(1)}%
        </div>
      )}
    </div>
  )
}


// ─── KPI strip data ──────────────────────────────────────────────────────────
function computeKpis(yearGroups) {
  const allMonths = yearGroups
    .flatMap(g => g.months)
    .filter(m => m.is_relevant && m.metrics)
  const sorted = [...allMonths].sort((a, b) => (a.period_key < b.period_key ? 1 : -1))
  const last12 = sorted.slice(0, 12)
  if (last12.length === 0) return null

  const realizedSum = last12.reduce((s, m) => s + (m.metrics.realized_pnl || 0), 0)
  const trades = last12.reduce((s, m) => s + (m.metrics.trades_count || 0), 0)
  const positiveCount = last12.filter(m => (m.metrics.delta_pct || 0) > 0).length

  let best = null, worst = null
  for (const m of last12) {
    if (m.metrics.delta_pct == null) continue
    if (!best  || m.metrics.delta_pct > best.metrics.delta_pct)  best  = m
    if (!worst || m.metrics.delta_pct < worst.metrics.delta_pct) worst = m
  }
  return { realizedSum, trades, positiveCount, totalCount: last12.length, best, worst }
}

function KpiCell({ label, value, sub, tone, first }) {
  const valueColor =
    tone === 'pos' ? 'text-rendi-pos' :
    tone === 'neg' ? 'text-rendi-neg' :
    'text-ink-0'
  return (
    <div className={`px-4 py-3 flex-1 min-w-[140px] ${first ? '' : 'border-l border-line/50'}`}>
      <div className="text-[12.5px] text-ink-2 leading-none font-medium">
        {label}
      </div>
      <div className={`mt-2 font-medium tabular num leading-none text-2xl tracking-tight ${valueColor}`}>
        {value}
      </div>
      <div className="text-[12.5px] text-ink-2 mt-1.5 leading-none truncate font-medium">
        {sub}
      </div>
    </div>
  )
}

// ─── Veredicto contra un benchmark ───────────────────────────────────────────
// `pp` es el EXCESO en puntos porcentuales (cartera − benchmark), no el retorno
// del índice. Sin dato no se dibuja nada: un "—" por año ocupa lugar y no dice
// más que el vacío.
function Veredicto({ nombre, articulo, pp, detalle }) {
  if (pp == null) return null
  const gana = pp >= 0
  const de = articulo === 'el' ? 'del' : 'de la'
  return (
    <span
      className="inline-flex items-center gap-1.5 text-[11px] text-ink-2 bg-bg-2 border border-line-2 rounded-full px-2.5 py-1 tabular whitespace-nowrap"
      title={`${gana ? 'Por encima' : 'Por debajo'} ${de} ${nombre} por ${Math.abs(pp).toFixed(1)} puntos porcentuales`
             + (detalle ? `. ${detalle}` : '')}
    >
      vs {nombre}
      <b className={`font-semibold ${gana ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
        {gana ? '+' : '−'}{Math.abs(pp).toFixed(1)} pp
      </b>
    </span>
  )
}

// dd/mm/aa — corto pero sin perder el año, que es lo que distingue las dos
// puntas de una ventana anual.
function fmtFechaCorta(iso) {
  if (!iso || iso.length < 10) return iso || ''
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(2, 4)}`
}

// ─── La fila de métricas del año ─────────────────────────────────────────────
// Lo que Reportes ya calculaba para el año en curso y sólo mostraba ahí. Los
// meses en verde y el mejor/peor salen de las celdas que ya están dibujadas
// arriba, así que describen exactamente lo que el usuario tiene delante.
function Dato({ label, valor, tono }) {
  const color = tono === 'pos' ? 'text-rendi-pos' : tono === 'neg' ? 'text-rendi-neg' : 'text-ink-1'
  return (
    <div className="flex flex-col gap-0.5 min-w-[92px]">
      <span className="text-[10.5px] text-ink-3 font-medium leading-none">{label}</span>
      <span className={`text-[13px] font-semibold tabular leading-none ${color}`}>{valor}</span>
    </div>
  )
}

function MetricasDelAno({ resumen, months, money, enPesos }) {
  if (!resumen) return null
  const conDato = months.filter(m => m.is_relevant && m.metrics?.delta_pct != null)
  const pcts = conDato.map(m => m.metrics.delta_pct)
  const verdes = pcts.filter(p => p > 0).length
  // ⚠️ EL DENOMINADOR SON LOS MESES DEL AÑO, NO LOS QUE TIENEN DATO. Contando sólo
  // los medidos, un año con un hueco se publicaba como perfecto: "11 de 11" cuando
  // 2024 tuvo doce meses y a marzo le falta la medición. El usuario leía "no fallé
  // ni un mes" donde la verdad es "no fallé ninguno de los que pudimos medir".
  // El denominador lo dice el SERVIDOR (`meses_del_anio`): 12 para un año cerrado,
  // los meses transcurridos para el año en curso. No se deriva de `bench_hasta`
  // —esa fecha describe la ventana en que se midió el índice, no el calendario— ni
  // de `new Date()`, porque el "hoy" de Rendi es el día argentino.
  const mesesDelAnio = resumen.meses_del_anio ?? (resumen.is_current ? conDato.length : 12)
  const sinMedir = Math.max(0, mesesDelAnio - conDato.length)
  const datos = []
  if (resumen.sp500_return_pct != null) {
    datos.push({ label: 'S&P 500 ese año',
                 valor: `${resumen.sp500_return_pct >= 0 ? '+' : '−'}${Math.abs(resumen.sp500_return_pct).toFixed(1)}%` })
  }
  if (resumen.inflation_pct != null) {
    datos.push({ label: 'Inflación AR', valor: `+${resumen.inflation_pct.toFixed(1)}%` })
  }
  if (resumen.deposits > 0) {
    datos.push({ label: 'Aportaste', valor: money.fmtMoney(resumen.deposits) })
  }
  if (resumen.withdrawals > 0) {
    datos.push({ label: 'Retiraste', valor: money.fmtMoney(resumen.withdrawals) })
  }
  if (resumen.realized_pnl) {
    datos.push({ label: 'P&L realizado', valor: money.fmtMoney(resumen.realized_pnl, { signed: true }),
                 tono: resumen.realized_pnl >= 0 ? 'pos' : 'neg' })
  }
  if (resumen.trades_count > 0) {
    datos.push({ label: 'Operaciones', valor: `${resumen.trades_count} cerradas` })
    if (resumen.win_rate != null) {
      datos.push({ label: 'Win rate', valor: `${resumen.win_rate.toFixed(0)}%` })
    }
  }
  if (pcts.length > 0) {
    datos.push({ label: 'Meses en verde', valor: `${verdes} de ${mesesDelAnio}` })
    const mejor = Math.max(...pcts), peor = Math.min(...pcts)
    datos.push({ label: 'Mejor mes', valor: `+${mejor.toFixed(1)}%`, tono: 'pos' })
    if (peor < 0) datos.push({ label: 'Peor mes', valor: `−${Math.abs(peor).toFixed(1)}%`, tono: 'neg' })
  }
  // Sin un solo dato la fila no se dibuja: un separador vacío bajo cada año es
  // ruido que el ojo tiene que descartar en cada pasada.
  if (datos.length === 0) return null
  const hayMontos = resumen.deposits > 0 || resumen.withdrawals > 0 || !!resumen.realized_pnl
  return (
    <div className="flex flex-wrap gap-x-6 gap-y-2.5 pl-[120px] pt-2.5 border-t border-line/50">
      {datos.map((d, i) => <Dato key={i} {...d} />)}
      {/* ⚠️ TODOS LOS MONTOS DE ESTA FILA ESTÁN AL DÓLAR DE HOY, NO AL DE SU FECHA.
          El servidor los publica en dólares a propósito (ver `_pct_en_pesos`) y la
          pantalla los convierte al pasar a pesos. Eso hace que dos aportes de US$500
          hechos en años distintos se muestren como el MISMO monto en pesos —medido:
          2025 y 2026 dicen los dos "$769.100"— cuando en su momento fueron cantidades
          bien distintas. Mientras el monto no venga convertido a la época, esto se
          declara en vez de dejar que se lea como pesos de entonces. */}
      {enPesos && hayMontos && (
        <span className="text-[10.5px] text-ink-3 self-end leading-none">montos al dólar de hoy</span>
      )}
      {sinMedir > 0 && (
        // ⚠️ ESTO EXPLICA POR QUÉ LAS BARRAS NO COMPONEN EL TOTAL DE AL LADO. El
        // total lo mide el motor punta a punta; las barras son los meses que hay.
        // Con un mes sin medición los dos números difieren —2024: +22,00 % arriba
        // y +20,88 % componiendo sus barras— y están a diez centímetros.
        <span className="text-[10.5px] text-rendi-warn/80 self-end leading-none">
          {sinMedir === 1 ? '1 mes sin medir' : `${sinMedir} meses sin medir`}
        </span>
      )}
      {resumen.bench_desde && resumen.bench_hasta && (
        // ⚠️ CON AÑO. Sin él, un año cerrado se leía "comparado del 31/12 al
        // 31/12" — dos fechas idénticas que sugieren un solo día, cuando son los
        // dos extremos del año. La ventana existe justamente para poder leerla.
        <span className="text-[10.5px] text-ink-3 self-end leading-none">
          comparado del {fmtFechaCorta(resumen.bench_desde)} al {fmtFechaCorta(resumen.bench_hasta)}
        </span>
      )}
    </div>
  )
}

export default function PerformanceCalendar({ yearGroups, years = [], yearsLoading = false,
                                             historicos = true }) {
  const kpis = computeKpis(yearGroups)
  // Fase B: el P&L Realizado 12M respeta el toggle global ARS/USD.
  // Los % no cambian (son ratios) — solo el valor monetario se convierte.
  const money = useMoneyFormat()
  // El selector global de moneda: decide si los montos que dibuja esta pantalla
  // están convertidos, y por lo tanto si hay que declarar a qué dólar.
  const { currency } = useCurrency()
  const enPesos = currency === 'ARS'
  if (!kpis) return null

  return (
    <section className="mb-6 space-y-3">
      {/* ── KPI strip ── */}
      <div className="border border-line rounded-xl bg-bg-1 flex flex-wrap">
        <KpiCell
          first
          label="P&L Realizado · 12M"
          value={money.fmtMoney(kpis.realizedSum, { signed: true })}
          tone={kpis.realizedSum >= 0 ? 'pos' : 'neg'}
          sub={`${kpis.totalCount} ${kpis.totalCount === 1 ? 'mes activo' : 'meses activos'}`}
        />
        <KpiCell
          label="Meses positivos"
          value={`${kpis.positiveCount}/${kpis.totalCount}`}
          sub={
            kpis.totalCount > 0
              ? `${Math.round((kpis.positiveCount / kpis.totalCount) * 100)}% en verde`
              : '—'
          }
        />
        <KpiCell
          label="Trades · 12M"
          value={kpis.trades.toLocaleString('es-AR')}
          sub="operaciones cerradas"
        />
      </div>

      {/* ── Calendar heatmap ── */}
      <div className="border border-line rounded-xl bg-bg-1 overflow-hidden">
        <header className="flex items-center justify-between px-4 py-2.5 border-b border-line">
          <div className="flex items-center gap-2">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-rendi-pos" aria-hidden="true" />
            <span className="text-[12.5px] text-ink-0 font-medium">
              Calendario de performance
            </span>
            <span className="text-[12.5px] text-ink-2 ml-1 font-medium">
              / TWR mensual
            </span>
          </div>
          <span className="text-[12.5px] text-ink-2 font-medium">
            {yearGroups.length} {yearGroups.length === 1 ? 'año' : 'años'} cargados
          </span>
        </header>

        {/* ⚠️ SCROLL, NO RECORTE. La card de afuera lleva `overflow-hidden`, así que
            sin esto las bandas angostas se CORTABAN: en 554px de ancho, noviembre,
            diciembre y los chips de veredicto desaparecían sin ninguna señal. Doce
            meses más el cierre no entran en un teléfono, y el contrato del repo ya
            marca este archivo como sitio de riesgo por sus anchos fijos. */}
        <div className="px-4 py-5 space-y-5 overflow-x-auto">
          {yearGroups.map(({ year, months }, idxAnio) => {
            const cells = Array.from({ length: 12 }, (_, idx) => {
              const m = months.find(mm => monthNum(mm.period_key) === idx + 1)
              return { idx, month: m }
            })
            // ⚠️ ACÁ VIVÍA UN SEGUNDO MOTOR DEL RENDIMIENTO ANUAL, Y CONTRADECÍA AL
            // PRIMERO. Componía los meses que la timeline hubiera traído y contaba
            // los ausentes como +0% (factor 1). Con la timeline en 12 meses, el año
            // anterior sólo tenía sus últimos meses cargados: medido en la cuenta de
            // prueba, 2025 publicaba "+6,50%" acá mientras el motor canónico mide
            // +32,95% — 26 puntos de diferencia para el mismo año, y el rótulo de
            // arriba diciendo "TWR mensual" como si fuera lo mismo.
            // Ahora el número viene de `/api/reports/years` (`twr.curva_indexada`),
            // que es el mismo que publica la pestaña Año y el inicio.
            const resumen = years.find(a => a.year === year) || null
            // El mismo criterio que la card del inicio: si el año entero no se puede
            // medir pero hay un tramo medido adentro, se muestra ese tramo con su
            // fecha. Ver `YearReturnLine` — la regla vive documentada allá.
            const parcial = resumen != null && resumen.pct == null && resumen.parcial_pct != null
            const pct = parcial ? resumen.parcial_pct : resumen?.pct
            // ⚠️ "BLOQUEADO" NO ES "SIN MEDIR". Sin el resumen —porque el plan no
            // lo incluye— la fila diría "sin fotos a precio de mercado", que es
            // falso: el número existe y está del otro lado del muro. Decirle al
            // usuario que le faltan datos cuando lo que le falta es el plan es la
            // peor de las dos mentiras posibles.
            const bloqueado = !historicos && !resumen
            return (
              <div key={year} className="space-y-2.5 min-w-[560px]">
              <div className="flex items-center gap-4">
                <div className="min-w-[104px] flex flex-col gap-1">
                  <span className="font-mono text-[12px] tracking-label text-ink-3 tabular">
                    {year}{resumen?.is_current ? ' · hasta hoy' : ''}
                  </span>
                  {pct != null ? (
                    <span className={`text-[22px] font-semibold tracking-tight leading-none tabular ${
                      resumen.basis === 'contable' ? 'text-ink-1'
                        : pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                      {pct >= 0 ? '+' : '−'}{Math.abs(pct).toFixed(2)}%
                    </span>
                  ) : bloqueado ? (
                    <Link to="/planes" className="inline-flex items-center gap-1.5 text-[13px] text-rendi-accent hover:text-rendi-accent/80 font-medium leading-none">
                      <Lock size={12} strokeWidth={2} /> Ver {year}
                    </Link>
                  ) : (
                    <span className="text-[13px] text-ink-3 font-medium leading-none">
                      {yearsLoading ? '…' : 'Sin medir'}
                    </span>
                  )}
                  <span className="text-[10.5px] text-ink-3 leading-tight">
                    {bloqueado
                      ? 'los años anteriores están en el plan pago'
                      : parcial
                        ? `desde el ${fechaEnPalabras(resumen.parcial_desde)}`
                        : pct == null
                          ? (resumen?.motivo_texto
                              ? 'el motor no publica este año'
                              : 'todavía sin mediciones que cubran el año')
                          : resumen.basis === 'contable'
                            ? 'de tu historia importada'
                            : 'medido a precio de mercado'}
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  {/* ⚠️ "NO TE LO PEDÍ" NO ES "NO SE PUDO MEDIR". El servidor devuelve
                      hasta doce años de rendimiento, pero el detalle mensual se pide
                      de a 36 meses: para un año más viejo que eso, las doce rayitas
                      grises dirían "sin medir" cuando lo cierto es que esta pantalla
                      no trajo sus meses. El total de arriba sigue siendo válido. */}
                  {months.length === 0 && pct != null ? (
                    <div className="h-[72px] flex items-center text-[11.5px] text-ink-3">
                      El detalle mes a mes de este año todavía no está cargado.
                    </div>
                  ) : (
                    <BarrasDelAnio cells={cells} money={money} enPesos={enPesos}
                                   tipAbajo={idxAnio === 0} />
                  )}
                </div>
                <div className="flex flex-col gap-1.5 items-end min-w-[132px]">
                  <Veredicto nombre="S&P 500" articulo="el"
                             pp={parcial ? resumen.parcial_vs_sp500_pct : resumen?.vs_sp500_pct} />
                  {/* ⚠️ LA INFLACIÓN SE COMPARA SIEMPRE EN PESOS (ver `twr.vs_inflacion_ar`):
                      restarle a un retorno en dólares un índice que mide precios
                      argentinos es restar unidades distintas. Cuando el usuario está
                      mirando en dólares, el veredicto sale de SU retorno convertido a
                      pesos — un número que no está en pantalla —, así que el globo lo
                      dice: si no, la resta que el usuario puede hacer con lo que ve no
                      le va a dar. */}
                  <Veredicto
                    nombre="inflación" articulo="la" pp={parcial ? null : resumen?.vs_inflation_pct}
                    detalle={!enPesos && resumen?.retorno_ars_pct != null
                      ? `Se compara en pesos: tu cartera hizo ${resumen.retorno_ars_pct.toFixed(2)} % en pesos y la inflación ${resumen.inflation_pct?.toFixed(1)} %`
                      : null}
                  />
                </div>
              </div>
              <MetricasDelAno resumen={resumen} months={months} money={money} enPesos={enPesos} />
              </div>
            )
          })}

          <div className="flex items-center gap-2 flex-wrap pt-3 border-t border-line/50 text-[11px] text-ink-3">
            <span className="inline-block w-2.5 h-2.5 rounded-xs bg-rendi-pos" aria-hidden="true" />
            <span>mes en verde</span>
            <span className="inline-block w-2.5 h-2.5 rounded-xs bg-rendi-neg ml-2" aria-hidden="true" />
            <span>mes en rojo</span>
            <span className="inline-block w-2.5 h-0.5 rounded-xs bg-line-2 ml-2" aria-hidden="true" />
            <span>sin medir</span>
            <span className="ml-auto">Pasá el mouse por una barra para ver el mes</span>
          </div>
        </div>
      </div>
    </section>
  )
}
