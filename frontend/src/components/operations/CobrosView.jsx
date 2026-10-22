// CobrosView — la pestaña "Cobros" de Movimientos: lo que te pagaron tus
// inversiones (dividendos, cupones, intereses).
// ═══════════════════════════════════════════════════════════════════════════
// Los cobros llegan renglón por renglón de GET /api/cobros (las mismas filas de
// Movimientos, cada una en dólares del día en que se cobró). Las sumas, el cupón
// de los pagos mixtos, el estimado y el próximo cobro salen de utils/cobros.js,
// con el cronograma de los bonos y los dividendos anunciados de Eventos. Acá
// sólo se pide y se dibuja.
//
// El estimado espera TODO lo que lo alimenta (posiciones, operaciones, eventos,
// el dólar de hoy y, si hay bonos CER, su serie): publicado antes, el número
// cambiaba solo segundos después. Si algo de eso falla, se dice que no se pudo
// calcular; un estimado de US$ 0 por un pedido caído sería un dato falso.
//
// Sistema visual (frontend/CLAUDE.md):
//   • Números en Geist con `tabular` (R1). Los tickers también en sans: este
//     archivo no suma ningún uso de la familia de ancho fijo.
//   • Superficies con Panel (12px); barras con radios de la escala (R5).
//   • Un solo archivo para las dos anchuras: la grilla se apila en el teléfono
//     por variantes de Tailwind, sin gemelo *Mobile (R6).
//   • Colores por variables del tema (R8). Lo cobrado en el acento, el año
//     anterior apagado, lo estimado con borde punteado.
//
// Los montos van SIEMPRE en dólares, aunque el interruptor de moneda diga pesos:
// es lo que permite comparar un año con otro sin que la devaluación lo infle.

import { useEffect, useMemo, useState } from 'react'
import { Coins } from 'lucide-react'
import Panel from '../Panel'
import EmptyState from '../EmptyState'
import { api } from '../../utils/api'
import { fmtMoney, pct, pctSigned } from '../../utils/format'
import { useCurrency, pickFinancialRate } from '../../contexts/CurrencyContext'
import { setBrokersRegistry } from '../../utils/valuation'
import { upcomingBondEvents, normalizeBackendEvents } from '../../utils/upcomingEvents'
import { useCerSeries } from '../../hooks/useCerSeries'
import { getBondMeta } from '../../utils/bondMeta'
import {
  resumirCobros, estimarProximos12, proximoCobro, dividendosAnunciados, barras,
  variacionAnual, tipoDeCobro, fechaLarga,
} from '../../utils/cobros'

const VISTAS = [
  { id: 'mes', label: 'Por mes' },
  { id: 'trimestre', label: 'Por trimestre' },
  { id: 'anio', label: 'Por año' },
]

// La vista elegida se recuerda en el navegador. Con el almacenamiento bloqueado
// (modo privado de algunos navegadores) leer o escribir tira un error: la
// pestaña sigue andando, sólo no recuerda la vista.
function leerVista() {
  try { return localStorage.getItem('rendi_cobros_vista') || 'mes' } catch { return 'mes' }
}
function guardarVista(v) {
  try { localStorage.setItem('rendi_cobros_vista', v) } catch { /* sin almacenamiento */ }
}

/** US$ con decimales sólo cuando el número es chico. */
function usd(v) {
  if (v == null) return '—'
  return fmtMoney(v, 'USD', { decimals: Math.abs(v) >= 1000 ? 0 : 2 })
}

function Kpi({ label, children, sub, subClass = 'text-ink-2' }) {
  return (
    <Panel className="flex flex-col gap-1 min-w-0">
      <p className="kpi-label">{label}</p>
      <div className="text-2xl font-semibold text-ink-0 tabular truncate">{children}</div>
      {sub && <p className={`text-xs ${subClass}`}>{sub}</p>}
    </Panel>
  )
}

function Barras({ filas, vista, anio }) {
  const max = Math.max(1, ...filas.map(f => Math.max(f.cobrado + f.estimado, f.anterior || 0)))
  // 88 % y no 100 %: arriba de la barra más alta queda lugar para su monto.
  const alto = (v) => `${Math.max(0, (v / max) * 88)}%`
  // El monto se escribe sólo en las barras que se ven: en una de dos píxeles
  // taparía a la vecina. El detalle de todas está en el globo (title).
  const conMonto = (v) => v > 0 && v >= max * 0.12
  return (
    <div className="flex flex-col gap-2">
      <div
        className="h-44 sm:h-52 flex items-end gap-1 sm:gap-2 border-b border-line"
        role="img"
        aria-label={vista === 'anio' ? 'Barras de cobros por año' : `Barras de cobros, ${anio} contra ${anio - 1}`}
      >
        {filas.map(f => {
          const titulo = [
            `${f.etiqueta}: ${usd(f.cobrado)} cobrado`,
            f.estimado > 0 ? `${usd(f.estimado)} estimado` : null,
            f.anterior != null ? `${usd(f.anterior)} en ${anio - 1}` : null,
          ].filter(Boolean).join(' · ')
          return (
            <div key={f.clave} className="flex-1 min-w-0 h-full flex items-end justify-center gap-px sm:gap-0.5" title={titulo}>
              {f.anterior != null && (
                <div className="w-2/5 bg-ink-3/40 rounded-t-sm" style={{ height: alto(f.anterior) }} />
              )}
              <div className={`${f.anterior != null ? 'w-2/5' : 'w-3/5'} h-full flex flex-col justify-end`}>
                {conMonto(f.cobrado + f.estimado) && (
                  <div className="flex justify-center mb-0.5">
                    <span className="whitespace-nowrap text-[10px] leading-none text-ink-1 tabular">
                      {Math.round(f.cobrado + f.estimado).toLocaleString('es-AR')}
                    </span>
                  </div>
                )}
                {f.estimado > 0 && (
                  <div className="border border-dashed border-rendi-accent bg-rendi-accent/10 rounded-t-sm"
                    style={{ height: alto(f.estimado) }} />
                )}
                {f.cobrado > 0 && (
                  <div className={`bg-rendi-accent ${f.estimado > 0 ? '' : 'rounded-t-sm'}`}
                    style={{ height: alto(f.cobrado) }} />
                )}
              </div>
            </div>
          )
        })}
      </div>
      <div className="flex gap-1 sm:gap-2">
        {filas.map(f => (
          <div key={f.clave} className="flex-1 min-w-0 text-center text-xs text-ink-2 tabular">{f.etiqueta}</div>
        ))}
      </div>
    </div>
  )
}

function Leyenda({ vista, anio }) {
  const item = (cls, txt) => (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block w-2.5 h-2.5 rounded-xs ${cls}`} />{txt}
    </span>
  )
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-2">
      {item('bg-rendi-accent', vista === 'anio' ? 'Cobrado' : String(anio))}
      {vista !== 'anio' && item('bg-ink-3/40', String(anio - 1))}
      {item('border border-dashed border-rendi-accent', 'Estimado')}
    </div>
  )
}

export default function CobrosView({ conTitulo = false }) {
  const { valuationDollar } = useCurrency()
  const [vista, setVistaEstado] = useState(leerVista)
  const setVista = (v) => { setVistaEstado(v); guardarVista(v) }

  const [datos, setDatos] = useState(null)
  const [error, setError] = useState(null)
  // Lo que alimenta el estimado. `null` = todavía no volvió.
  const [positions, setPositions] = useState(null)
  const [operations, setOperations] = useState(null)
  const [eventos, setEventos] = useState(null)
  const [dolar, setDolar] = useState(undefined)        // undefined = no volvió; null = falló
  const [falloEstimado, setFalloEstimado] = useState(false)
  const [valorCartera, setValorCartera] = useState(null)

  const tieneCer = (positions || []).some(p => !p.is_cash && getBondMeta(p.asset)?.type === 'cer')
  const { series: cerSeries, loaded: cerListo } = useCerSeries(tieneCer)

  useEffect(() => {
    let vivo = true
    const fallo = () => { if (vivo) setFalloEstimado(true) }
    api.get('/cobros')
      .then(r => { if (vivo) setDatos(r) })
      .catch(e => { if (vivo) setError(e.message || 'No pudimos traer tus cobros.') })
    Promise.all([api.get('/positions'), api.get('/brokers')])
      .then(([pos, bkrs]) => {
        if (!vivo) return
        // Sin el registro de brokers, el dividendo anunciado de un CEDEAR sale en
        // la escala de la acción (150 CEDEARs de KO no son 150 acciones).
        setBrokersRegistry(bkrs || [])
        setPositions(pos || [])
      })
      .catch(fallo)
    // Las operaciones cerradas: para saber cuántas acciones tenías al cobrar.
    api.get('/operations')
      .then(ops => { if (vivo) setOperations(ops || []) })
      .catch(fallo)
    // Sin eventos de las empresas el estimado sigue valiendo (sale de tu historia
    // y del cronograma); sólo no hay dividendos anunciados.
    api.get('/events/portfolio?days=365')
      .then(r => { if (vivo) setEventos(r?.events || []) })
      .catch(() => { if (vivo) setEventos([]) })
    api.get('/dolar').then(d => { if (vivo) setDolar(d || null) }).catch(() => { if (vivo) setDolar(null) })
    // El valor de la cartera: la última foto que sirve como medición (`apto`).
    api.get('/snapshots?days=10')
      .then(s => {
        if (!vivo) return
        const ult = [...(s || [])].reverse().find(f => f.apto && f.total_value > 0)
        setValorCartera(ult ? ult.total_value : null)
      })
      .catch(() => {})
    return () => { vivo = false }
  }, [])

  const tc = dolar ? pickFinancialRate(dolar, valuationDollar) : undefined
  const resumen = useMemo(() => resumirCobros(datos, { cerSeries }), [datos, cerSeries])
  const listoEstimado = !falloEstimado && positions != null && operations != null && eventos != null
    && dolar !== undefined && (!tieneCer || cerListo)
  const hoy = resumen?.hoy

  const { estimado, proximo } = useMemo(() => {
    if (!resumen || !listoEstimado) return { estimado: null, proximo: null }
    const eventosBonos = upcomingBondEvents(positions, { windowDays: 365, cerSeries, today: hoy })
    const anunciados = dividendosAnunciados(normalizeBackendEvents(eventos, { today: hoy }), hoy)
    const est = estimarProximos12({
      ultimos12: resumen.ultimos_12_meses, positions, operations, eventosBonos,
      anunciados: anunciados.map(e => e.ticker), tc,
    })
    return {
      estimado: est,
      proximo: proximoCobro({
        estimado: est, eventosBonos, anunciados, tc,
        cobroCtx: { positions, tc },
        diasHastaElPago: resumen.dias_hasta_el_pago || 0,
      }),
    }
  }, [resumen, listoEstimado, positions, operations, eventos, cerSeries, tc, hoy])

  const filas = useMemo(() => barras(resumen, estimado, vista), [resumen, estimado, vista])

  if (error) {
    return <Panel><p className="text-sm text-rendi-neg">{error}</p></Panel>
  }
  if (!resumen) {
    return <Panel><p className="text-sm text-ink-2">Buscando tus cobros…</p></Panel>
  }

  const anio = resumen.anio
  const nadaNunca = !resumen.por_anio.length && !(estimado?.total > 0)
  if (nadaNunca && (listoEstimado || falloEstimado)) {
    return (
      <Panel>
        <EmptyState
          icon={<Coins size={18} />}
          title="Todavía no tenés cobros anotados"
          description="Los dividendos, cupones e intereses entran cuando importás el archivo de tu broker o cuando confirmás un cobro en Cartera. Apenas haya uno, acá vas a ver cuánto te pagaron por mes y por activo."
        />
      </Panel>
    )
  }

  const variacion = variacionAnual(resumen)
  const maxActivo = Math.max(1, ...resumen.por_activo.map(a => Math.abs(a.usd)))
  const pctCartera = estimado && valorCartera > 0 ? estimado.total / valorCartera : null

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          {/* En la pantalla ancha el título ya lo dice el encabezado de la página. */}
          {conTitulo && <h2 className="text-lg font-semibold text-ink-0">Lo que te pagaron tus inversiones</h2>}
          <p className="text-xs text-ink-2">
            Dividendos, cupones e intereses, en dólares. Cada cobro en pesos se pasa a dólares con el dólar del día en que lo cobraste.
          </p>
        </div>
        <div className="inline-flex rounded-lg border border-line bg-bg-1 p-0.5 text-xs font-medium" role="tablist" aria-label="Agrupar cobros">
          {VISTAS.map(v => (
            <button
              key={v.id}
              role="tab"
              aria-selected={vista === v.id}
              onClick={() => setVista(v.id)}
              className={`px-3 py-1.5 rounded transition-colors ${vista === v.id ? 'bg-bg-3 text-ink-0 font-semibold' : 'text-ink-2 hover:text-ink-0'}`}
            >
              {v.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Kpi
          label={`Cobraste en ${anio}`}
          sub={variacion != null
            ? `${pctSigned(variacion, 0)} contra el mismo período de ${anio - 1}`
            : `Sin cobros en el mismo período de ${anio - 1}`}
          subClass={variacion == null ? 'text-ink-2' : variacion >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}
        >
          {usd(resumen.total_anio)}
        </Kpi>
        <Kpi
          label="Próximos 12 meses (estimado)"
          sub={falloEstimado ? 'No se pudo calcular: no llegaron tus posiciones u operaciones. Probá recargar.'
            : !estimado ? 'Calculando…'
            : pctCartera != null ? `${pct(pctCartera, 1)} de tu cartera por año`
            : `${usd(estimado.total / 12)} por mes`}
        >
          {estimado ? usd(estimado.total) : falloEstimado ? '—' : '…'}
        </Kpi>
        <Kpi
          label="Próximo cobro"
          sub={falloEstimado ? 'No se pudo calcular'
            : !listoEstimado ? 'Calculando…'
            : !proximo ? 'No hay ninguno que se pueda anticipar'
            : proximo.corte
              // Sólo se conoce el corte: la plata entra unos días después (regla medida).
              ? `cerca del ${fechaLarga(proximo.fecha)} · el corte es el ${fechaLarga(proximo.corte)}${proximo.usd != null ? ', antes de impuestos' : ''}`
              : `${fechaLarga(proximo.fecha)} · ${
                proximo.fuente === 'cronograma' ? (proximo.conAmortizacion ? 'cupón + amortización, según el cronograma' : 'según el cronograma del bono')
                : proximo.fuente === 'anunciado' ? 'anunciado, antes de impuestos'
                : 'estimado por lo que te pagó el año pasado'}`}
        >
          {proximo
            ? <span className="text-xl">{proximo.activo} · {proximo.usd != null ? usd(proximo.usd) : 'monto a confirmar'}</span>
            : '—'}
        </Kpi>
      </div>

      <div className="flex flex-col lg:flex-row gap-4">
        <Panel as="section" className="lg:flex-[3] min-w-0 flex flex-col gap-3" aria-label="Cobros por período">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-ink-0">
              {vista === 'mes' ? `Por mes: ${anio} contra ${anio - 1}`
                : vista === 'trimestre' ? `Por trimestre: ${anio} contra ${anio - 1}`
                : 'Por año'}
            </h3>
            <Leyenda vista={vista} anio={anio} />
          </div>
          <Barras filas={filas} vista={vista} anio={anio} />
          <p className="text-xs text-ink-2">
            Lo punteado es lo que falta cobrar este año según el estimado.
          </p>
        </Panel>

        <Panel as="section" className="lg:flex-[2] min-w-0 flex flex-col" aria-label="Cobros por activo">
          <h3 className="text-sm font-semibold text-ink-0 pb-2">Por activo, en {anio}</h3>
          {!resumen.por_activo.length && (
            <p className="text-sm text-ink-2 py-2">Todavía no cobraste nada este año.</p>
          )}
          {resumen.por_activo.map(a => (
            <div key={a.activo || '—'} className="grid grid-cols-[minmax(0,6rem)_minmax(0,1fr)_auto] items-center gap-3 py-2 border-t border-line text-sm">
              <div className="min-w-0">
                <p className="font-semibold text-ink-0 truncate">{a.activo || 'Sin activo'}</p>
                <p className="text-xs text-ink-2 truncate">{a.activo ? tipoDeCobro(a.activo, a.tipos) : 'tu broker no dice de cuál'}</p>
              </div>
              <div className="h-2 bg-bg-2 rounded-full overflow-hidden">
                <div className="h-2 bg-rendi-accent" style={{ width: `${Math.max(0, (a.usd / maxActivo) * 100)}%` }} />
              </div>
              <p className="tabular font-semibold text-ink-0 text-right">{usd(a.usd)}</p>
            </div>
          ))}
          {estimado && estimado.total > 0 && (
            <p className="mt-auto pt-3 text-sm text-ink-1">
              Lo estimado te da <span className="font-semibold text-ink-0 tabular">{usd(estimado.total / 12)} por mes</span>.
            </p>
          )}
        </Panel>
      </div>

      {resumen.mixtos.sinSeparar > 0 && (
        <Panel padding="sm">
          <p className="text-xs text-ink-2 leading-relaxed">
            <span className="font-medium text-ink-1">Falta una parte: </span>
            {resumen.mixtos.sinSeparar === 1 ? 'un pago de bono trae' : `${resumen.mixtos.sinSeparar} pagos de bonos traen`} el cupón y la amortización juntos (<span className="tabular">{usd(resumen.mixtos.usdSinSeparar)}</span> en total) y el cronograma no dice cuánto es cupón, así que no {resumen.mixtos.sinSeparar === 1 ? 'entra' : 'entran'} en lo cobrado. Contarlos enteros sumaría como renta el capital que te devolvieron.
          </p>
        </Panel>
      )}

      {estimado && (
        <Panel padding="sm">
          <p className="text-xs text-ink-2 leading-relaxed">
            <span className="font-medium text-ink-1">Cómo se estima: </span>
            los cupones de tus bonos salen de su cronograma (sin la amortización, que es tu capital que vuelve).
            Para tus acciones, CEDEARs y ETFs se repite lo que te pagaron en los últimos 12 meses, ajustado a lo que tenés hoy contra lo que tenías cuando cobraste.
            {estimado.sinAjustar.length > 0 && (
              <> De {estimado.sinAjustar.join(', ')} no se sabe cuánto tenías al cobrar (falta la fecha de compra de algún lote), así que se repite lo cobrado sin ajustar.</>
            )}
            {estimado.sinHistoria.length > 0 && (
              <> {estimado.sinHistoria.join(', ')} {estimado.sinHistoria.length === 1 ? 'tiene' : 'tienen'} un dividendo anunciado pero no {estimado.sinHistoria.length === 1 ? 'entra' : 'entran'}: todavía no hay cobros {estimado.sinHistoria.length === 1 ? 'suyos' : 'de ellos'} anotados para saber cada cuánto paga{estimado.sinHistoria.length === 1 ? '' : 'n'}.</>
            )}
            {estimado.sinActivoUsd > 0 && (
              <> Tampoco entran <span className="tabular">{usd(estimado.sinActivoUsd)}</span> de cobros sin activo: tu broker no dice de qué inversión son.</>
            )}
            {estimado.cuponesSinDolar > 0 && (
              <> Faltan cupones en pesos: no llegó el dólar de hoy para pasarlos.</>
            )}
          </p>
        </Panel>
      )}
    </div>
  )
}
