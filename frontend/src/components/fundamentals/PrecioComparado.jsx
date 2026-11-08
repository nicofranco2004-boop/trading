// PrecioComparado — pestaña «Precio» de Comparar (pieza 16).
// ═══════════════════════════════════════════════════════════════════════════
// De 1 a 4 activos en el mismo gráfico, todos arrancando en 100 el mismo día,
// contra el S&P 500, guardar dólares y (en pesos) la inflación. Debajo, «cada
// US$ 100 de tal fecha hoy son…» y una frase que describe sin recomendar.
//
// La cuenta entera (el 100, la moneda, qué serie de precios) la hace el
// servidor: GET /api/comparar/precio → backend/comparar.py, con la misma serie
// que la ficha. Acá se elige qué pedir (utils/comparadorPrecio.js, con las
// reglas de la ficha para tus lotes) y se dibuja lo que vuelve.
//
// El Merval no está: no hay fuente desde que Yahoo dejó de publicarlo.

import { useState, useEffect, useMemo, useRef } from 'react'
import { AlertCircle, LineChart as IconoLinea } from 'lucide-react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from 'recharts'
import Panel from '../Panel'
import Skeleton from '../Skeleton'
import EmptyState from '../EmptyState'
import Segmento from '../asset/Segmento'
import { api } from '../../utils/api'
import { track } from '../../utils/track'
import { useLotesDeLaCuenta } from '../../hooks/useLotesDeLaCuenta'
import { chartGrid, chartTickSm, chartTooltip, chartReferenceStroke } from '../../utils/chartTheme'
import { fechaCorta } from '../../utils/cuantoSeMueve'
import { MONTHS } from '../../utils/format'
import { hoyISO } from '../../utils/fecha'
import {
  MAX_ACTIVOS, PLAZOS, marcaLocal, primeraCompraDe, urlDelPedido, filasDelGrafico,
  monto, fraseComparacion, porQueArrancaAhi, vaciaPorVieja,
} from '../../utils/comparadorPrecio'

const v = (token) => `rgb(var(--${token}))`
// Los colores no salen de SERIES_COLORS (utils/chartTheme.js) a propósito: esa
// lista arranca con el verde de ganancia y termina con el rojo de pérdida, y
// acá una línea verde se leería «va ganando». Cuatro que no dicen ni gana ni
// pierde y que no se confunden entre sí ni con las varas (auditoría 29/10:
// `data-amber` y `rendi-warn` son el MISMO color en los dos temas, y azul con
// violeta son el par que chartTheme ya anota como demasiado cerca). Las varas,
// en tonos quietos y punteadas.
const COLOR_ACTIVO = [v('rendi-accent'), v('data-amber'), v('cat-magenta'), v('data-cyan')]
const VARA = {
  sp500: { color: v('ink-1'), dash: '6 3', chip: 'S&P 500' },
  mep: { color: v('ink-3'), dash: '2 4', chip: 'Guardar dólares (MEP)' },
  cer: { color: v('cat-teal'), dash: '4 3', chip: 'Inflación (CER)' },
}
const ORDEN_VARAS = ['sp500', 'mep', 'cer']
// Un dato que se quedó más días que esto atrás de los activos se dice «al dd/mm».
const DIAS_ATRASO = 5
// «bajando»: otra persona está bajando ese activo; se vuelve a pedir, como la ficha.
const REINTENTOS = 3
const ESPERA_MS = 4000

// Sobre lo que TENEMOS, no sobre el activo: un bono cotiza todos los días; lo que
// no tenemos es su serie para graficar (auditoría de «Una cartera», 05/11, M10).
const MOTIVO = {
  sin_serie: () => 'no tenemos sus precios de cada día para graficar (un bono o un fondo)',
  sin_datos: () => 'no encontramos sus precios',
  tope: () => 'pediste muchos activos nuevos en poco tiempo; probá de nuevo en un rato',
  bajando: () => 'estamos bajando sus precios; probá de nuevo en unos segundos',
  // Su último precio no es de hoy: no se dibuja como si lo fuera (comparar.py).
  vieja: (f) => `sus precios llegan hasta el ${fechaCorta(f.hasta)}: no entra en la comparación`,
}

const mesCorto = (iso) => {
  const [y, m] = iso.split('-')
  return `${MONTHS[Number(m) - 1]?.slice(0, 3).toLowerCase()} ${y.slice(2)}`
}
const dias = (a, b) => Math.round((new Date(b) - new Date(a)) / 86400000)

export default function PrecioComparado({ tickers }) {
  const activos = tickers.slice(0, MAX_ACTIVOS)
  const lotes = useLotesDeLaCuenta()              // { posiciones, operaciones } — null mientras carga
  const [moneda, setMoneda] = useState('usd')
  const [plazo, setPlazo] = useState(null)        // se elige al saber si tenés alguno
  const [varas, setVaras] = useState({ sp500: true, mep: true, cer: true })
  const [res, setRes] = useState(null)
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState(null)
  const pedido = useRef(0)
  // «Comparó precios» se cuenta una vez por juego de activos, no en cada cambio
  // de moneda o de plazo ni en cada reintento.
  const contado = useRef(null)

  const clave = activos.join(',')
  const primera = useMemo(
    () => (lotes ? primeraCompraDe(activos, lotes.posiciones, hoyISO()) : null),
    [lotes, clave], // eslint-disable-line react-hooks/exhaustive-deps
  )
  const locales = useMemo(
    () => (lotes ? activos.filter(a => marcaLocal(a, lotes.posiciones, lotes.operaciones)) : []),
    [lotes, clave], // eslint-disable-line react-hooks/exhaustive-deps
  )
  // De entrada: desde tu primera compra si tenés alguno; si no, 1 año. Si
  // sacás el que tenías, «desde tu primera compra» deja de existir.
  const plazoVigente = plazo === 'compra' && !primera ? '1a' : (plazo || (primera ? 'compra' : '1a'))

  useEffect(() => {
    if (!lotes || !activos.length) return
    const id = ++pedido.current
    let intento = 0
    let espera = null
    const pedir = () => {
      setCargando(true)
      setError(null)
      api.get(urlDelPedido({ activos, locales, moneda, plazo: plazoVigente, desde: primera }))
        .then(r => {
          if (id !== pedido.current) return
          const bajando = (r?.faltan || []).some(f => f.motivo === 'bajando')
          if (bajando && intento < REINTENTOS) {
            intento += 1
            espera = setTimeout(pedir, ESPERA_MS)
          }
          setRes(r)
          setCargando(false)
          // Se cuenta lo que se pudo comparar: con todo viejo (la noche caída) no se
          // dibuja nada, y contarlo inflaba las comparaciones justo esos días (H6, 06/11).
          if (contado.current !== clave && (r?.series || []).some(s => s.tipo === 'activo')) {
            contado.current = clave
            track('comparar_precio', { n: activos.length, moneda, plazo: plazoVigente })
          }
        })
        .catch(e => {
          if (id !== pedido.current) return
          // Sin respuesta nueva no queda el gráfico viejo con la moneda cambiada.
          setRes(null)
          setError(e?.message || 'No se pudo armar la comparación')
          setCargando(false)
        })
    }
    pedir()
    return () => { if (espera) clearTimeout(espera) }
  }, [lotes, clave, locales.join(','), moneda, plazoVigente, primera]) // eslint-disable-line react-hooks/exhaustive-deps

  const visibles = useMemo(() => {
    if (!res) return []
    const deActivo = (res.series || []).filter(s => s.tipo === 'activo')
    const deVara = ORDEN_VARAS
      .map(k => (res.series || []).find(s => s.clave === k))
      .filter(s => s && varas[s.clave])
    return [
      ...deActivo.map(s => ({ ...s, color: COLOR_ACTIVO[activos.indexOf(s.clave)] || COLOR_ACTIVO[0] })),
      ...deVara.map(s => ({ ...s, color: VARA[s.clave].color, dash: VARA[s.clave].dash })),
    ]
  }, [res, varas, clave]) // eslint-disable-line react-hooks/exhaustive-deps

  const filas = useMemo(() => filasDelGrafico(visibles), [visibles])
  // La frase mira las varas que estás viendo (sacaste el S&P: no se habla del S&P).
  const frase = useMemo(
    () => (res ? fraseComparacion({ ...res, series: visibles }) : ''),
    [res, visibles],
  )
  const ultimoActivo = useMemo(() => visibles.filter(s => s.tipo === 'activo')
    .reduce((m, s) => (s.fecha_final > m ? s.fecha_final : m), ''), [visibles])

  // Lo que se MUESTRA va en la moneda de la respuesta, no en la del botón:
  // mientras llega la nueva, los números siguen siendo los de antes y tienen
  // que decir su moneda (auditoría 29/10).
  const enPesos = res?.moneda === 'ars'
  const monedaRes = res?.moneda || moneda
  const opcionesPlazo = PLAZOS.filter(([id]) => id !== 'compra' || primera)
  const avisos = (res?.faltan || []).filter(f => MOTIVO[f.motivo] && activos.includes(f.clave))
  const vieja = vaciaPorVieja(res, activos)
  const sinVara = (res?.faltan || []).filter(f => (f.motivo === 'sin_datos' || f.motivo === 'vieja') && VARA[f.clave])
  // «El día de tu primera compra» sólo si el 100 es ESE día.
  const esTuCompra = res?.plazo === 'compra' && res?.base === res?.desde

  if (!activos.length) {
    return (
      <Panel padding="lg">
        <EmptyState icon={<IconoLinea size={20} strokeWidth={1.75} />} eyebrow="Precio"
          title="Agregá activos para comparar su precio"
          description="Buscá arriba hasta 4 (acciones, CEDEARs, ETFs o cripto): todos arrancan en 100 el mismo día, contra el S&P 500 y guardar dólares." />
      </Panel>
    )
  }

  return (
    <div className="space-y-4">
      {tickers.length > MAX_ACTIVOS && (
        <p className="text-xs text-rendi-warn flex items-start gap-1.5">
          <AlertCircle size={13} className="mt-0.5 flex-shrink-0" />
          El gráfico de precios compara hasta {MAX_ACTIVOS}: van los primeros {MAX_ACTIVOS}. Quitá uno arriba para elegir cuáles.
        </p>
      )}

      {/* ── Controles: moneda, plazo y contra qué ──────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:flex-wrap sm:items-center gap-2 sm:gap-3">
        <div className="flex">
          <Segmento etiqueta="Moneda" valor={moneda} alElegir={setMoneda} estirar
            opciones={[['usd', 'En dólares'], ['ars', 'En pesos']]} />
        </div>
        <div className="flex">
          <Segmento etiqueta="Desde cuándo" valor={plazoVigente} alElegir={setPlazo} estirar
            opciones={opcionesPlazo} />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Contra qué comparar">
        <span className="text-[12px] text-ink-3 font-medium mr-1">Contra</span>
        {ORDEN_VARAS.map(k => {
          const soloPesos = k === 'cer' && moneda !== 'ars'
          const prendida = varas[k] && !soloPesos
          return (
            <button key={k} type="button" disabled={soloPesos} aria-pressed={prendida}
              onClick={() => setVaras(x => ({ ...x, [k]: !x[k] }))}
              className={`inline-flex items-center gap-1.5 min-h-9 px-3 rounded-full border text-xs transition-colors ${
                soloPesos ? 'border-line text-ink-3 opacity-60 cursor-not-allowed'
                  : prendida ? 'border-data-violet/60 bg-data-violet/10 text-ink-0'
                    : 'border-line text-ink-2 hover:text-ink-0'}`}>
              <svg width="14" height="4" aria-hidden="true">
                <line x1="0" y1="2" x2="14" y2="2" stroke={VARA[k].color} strokeWidth="2" strokeDasharray={VARA[k].dash} />
              </svg>
              {VARA[k].chip}{soloPesos ? ' · sólo en pesos' : ''}
            </button>
          )
        })}
      </div>

      {/* Avisos: un activo sin precios, el 100 que se corrió, una vara sin dato */}
      {avisos.map(f => (
        <div key={f.clave} className="flex items-start gap-2 text-xs text-rendi-warn bg-rendi-warn/5 border border-rendi-warn/20 rounded px-3 py-2">
          <AlertCircle size={13} className="mt-0.5 flex-shrink-0" />
          <span><span className="font-medium">{f.clave}</span> — {MOTIVO[f.motivo](f)}.</span>
        </div>
      ))}
      {error && (
        <div className="flex items-start gap-2 text-xs text-rendi-neg bg-rendi-neg/5 border border-rendi-neg/20 rounded px-3 py-2">
          <AlertCircle size={13} className="mt-0.5 flex-shrink-0" /> {error}
        </div>
      )}

      {/* ── El gráfico ─────────────────────────────────────────────────────── */}
      {!res && (cargando || !lotes) && <Skeleton className="h-80 w-full rounded-xl" />}

      {res && !visibles.some(s => s.tipo === 'activo') && !cargando && (
        <Panel padding="lg">
          <EmptyState icon={<IconoLinea size={20} strokeWidth={1.75} />} eyebrow="Precio"
            title={vieja ? vieja.titulo : 'No hay precios para comparar'}
            description={vieja ? vieja.texto
              : 'Probá con otro activo: de acciones, CEDEARs, ETFs y cripto tenemos los precios de cada día.'} />
        </Panel>
      )}

      {res && visibles.some(s => s.tipo === 'activo') && (
        <>
          <Panel padding="md" className={cargando ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
            <div className="flex items-start justify-between gap-3 mb-2 text-[12px] text-ink-3">
              <span>
                Todos arrancan en 100 el {fechaCorta(res.base)}
                {esTuCompra ? ', el día de tu primera compra' : ''}
                {porQueArrancaAhi(res)}
              </span>
              <span className="flex-shrink-0">{enPesos ? 'en pesos' : 'en dólares'}</span>
            </div>
            <Leyenda series={visibles} />
            <div className="h-64 sm:h-80 -mx-1" role="img"
              aria-label={visibles.map(s => `${s.nombre} terminó en ${Math.round(s.final)}`).join(', ')}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={filas} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid {...chartGrid} />
                  <XAxis dataKey="d" tick={chartTickSm} axisLine={false} tickLine={false}
                    tickFormatter={mesCorto} minTickGap={40} />
                  <YAxis tick={chartTickSm} axisLine={false} tickLine={false} width={36}
                    domain={['auto', 'auto']} tickFormatter={x => Math.round(x)} />
                  <ReferenceLine y={100} stroke={chartReferenceStroke} />
                  <Tooltip {...chartTooltip}
                    labelFormatter={fechaCorta}
                    formatter={(val, key) => [Math.round(val), visibles.find(s => s.clave === key)?.nombre || key]} />
                  {visibles.map(s => (
                    <Line key={s.clave} dataKey={s.clave} name={s.nombre} type="linear" dot={false}
                      stroke={s.color} strokeWidth={s.tipo === 'activo' ? 2 : 1.5}
                      strokeDasharray={s.dash} connectNulls isAnimationActive={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Panel>

          {/* ── Cada 100 de ese día, hoy son… + lo que dicen los números ───── */}
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px] gap-4">
            <Panel padding="md">
              <p className="text-[12px] text-ink-3 font-medium mb-3">
                Cada {monto(100, monedaRes)} del {fechaCorta(res.base)}, hoy son
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-x-3 gap-y-3">
                {visibles.map(s => (
                  <div key={s.clave} className="min-w-0">
                    <div className={`text-[13px] leading-tight break-words ${s.tipo === 'activo' ? 'font-medium' : ''}`} style={{ color: s.color }}>
                      {s.nombre}
                    </div>
                    <div className={`text-xl font-semibold tabular ${Math.round(s.final) < 100 ? 'text-rendi-neg' : 'text-ink-0'}`}>
                      {monto(s.final, monedaRes)}
                    </div>
                    {ultimoActivo && dias(s.fecha_final, ultimoActivo) > DIAS_ATRASO && (
                      <div className="text-[11px] text-ink-3">al {fechaCorta(s.fecha_final)}</div>
                    )}
                  </div>
                ))}
              </div>
            </Panel>
            {frase && (
              <Panel padding="md" className="!border-data-violet/30">
                <p className="text-[12px] text-data-violet font-medium mb-1.5">Lo que dicen los números</p>
                <p className="text-sm text-ink-1 leading-relaxed">{frase}</p>
              </Panel>
            )}
          </div>

          {sinVara.length > 0 && (
            <p className="text-[12px] text-ink-3">
              {sinVara.map(f => (f.motivo === 'vieja'
                ? `${VARA[f.clave].chip}: el dato llega hasta el ${fechaCorta(f.hasta)}, no aparece.`
                : `${VARA[f.clave].chip}: sin datos desde esa fecha, no aparece.`)).join(' ')}
            </p>
          )}
          <p className="text-[12px] text-ink-3 leading-relaxed">
            {enPesos
              ? 'En pesos, la vara es el dólar MEP y la inflación (CER): si algo subió menos que la inflación, tenés más pesos pero alcanzan para menos.'
              : 'En dólares, guardar dólares queda quieto en 100: lo que termina abajo de esa línea perdió dólares.'}
            {enPesos
              ? ' Lo que cotiza afuera se pasa a pesos con el MEP de cada día.'
              : ' Las acciones argentinas se pasan a dólares con el MEP de cada día.'}
            {' '}No incluye dividendos. Mira hacia atrás; no es una recomendación.
          </p>
        </>
      )}
    </div>
  )
}

function Leyenda({ series }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 mb-2 text-[12px]">
      {series.map(s => (
        <li key={s.clave} className="inline-flex items-center gap-1.5 min-w-0">
          <svg width="16" height="4" aria-hidden="true" className="flex-shrink-0">
            <line x1="0" y1="2" x2="16" y2="2" stroke={s.color} strokeWidth="2" strokeDasharray={s.dash} />
          </svg>
          <span className={`text-ink-1 truncate ${s.tipo === 'activo' ? 'font-medium' : ''}`}>{s.nombre}</span>
          <span className="text-ink-0 font-semibold tabular">{Math.round(s.final)}</span>
        </li>
      ))}
    </ul>
  )
}
