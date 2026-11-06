// Piezas de la pestaña «Backtesting» que usan sus dos modos: «Una regla»
// (pages/Backtesting.jsx) y «Una cartera» (pages/SimularCartera.jsx). Un solo
// gráfico de «Cómo habrían ido US$ 100», un solo aviso, los mismos trazos y un
// solo pedido al servidor (`usePedidoDePrueba`): los dos modos se ven y se
// comportan igual porque son lo mismo, no dos copias. La tarjeta de resultado es
// de «Una regla»; «Una cartera» pone sus tres números en una tabla al lado de la
// suya, para que se vean mientras escribís (Nico, 06/11; diseño 05/11, M1).
import { useEffect, useRef, useState } from 'react'
import { AlertCircle } from 'lucide-react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ReferenceArea,
} from 'recharts'
import { chartGrid, chartTickSm, chartTooltip, chartReferenceStroke } from '../../utils/chartTheme'
import { api } from '../../utils/api'
import { colorDe, enQueTermino, porcentaje } from '../../utils/backtesting'
import { fechaCorta } from '../../utils/cuantoSeMueve'
import { MONTHS } from '../../utils/format'

export const v = (token) => `rgb(var(--${token}))`
// La vara (comprar y mantener, los índices): un tono quieto y punteado.
export const PUNTEADO = '6 3'
// «bajando»: otra persona está bajando ese activo; se vuelve a pedir, como en Comparar.
export const REINTENTOS = 3
export const ESPERA_MS = 4000

// Lo que el navegador trae en inglés cuando el servidor no contesta bien.
const DETALLE_EN_CASTELLANO = {
  'internal server error': 'el servidor tuvo un error',
  'bad gateway': 'el servidor no respondió',
  'service unavailable': 'el servidor no está disponible',
  'gateway timeout': 'el servidor tardó demasiado',
  'failed to fetch': 'no hay conexión',
  'load failed': 'no hay conexión',
}
const enCastellano = (d) => DETALLE_EN_CASTELLANO[String(d).trim().toLowerCase()] || d
// «HTTP 500» no le dice nada a nadie: ese detalle no se muestra (diseño 05/11, B2).
const sinTripas = (d) => (/^HTTP \d+$/i.test(String(d).trim()) ? null : d)

// Las respuestas que se guardan por pantalla: volver a una consulta que ya se vio
// (50 → 5 → 50 mientras se escribe) no pide de nuevo (auditoría 05/11, B12). Sólo
// las que se pudieron simular, y por un rato: con la pestaña abierta de un día
// para el otro, la noche ya bajó precios nuevos (verificación 05/11, V10).
const GUARDADAS = 20
const GUARDADA_MS = 10 * 60 * 1000

/**
 * El pedido de una prueba al servidor, el MISMO en los dos modos (auditoría 05/11,
 * M8: «Una regla» decía que estaba trayendo los precios y «Una cartera» no).
 *   · Si otra persona está bajando los precios ('bajando'), se vuelve a pedir
 *     hasta REINTENTOS veces cada ESPERA_MS, y `trayendo` lo dice.
 *   · Lo que llega tarde, de otra consulta, no se usa.
 *   · `pausa`: mientras se escribe se espera quieto antes de pedir; el primero
 *     y el de «Reintentar» salen en el momento.
 *   · `url` null: todavía no hay nada que pedir.
 * {res, error, estadoHttp, cargando, trayendo, reintentar}.
 */
export function usePedidoDePrueba(url, { pausa = 0 } = {}) {
  const [estado, setEstado] = useState({ res: null, error: null, cargando: false, trayendo: false, estadoHttp: null })
  const [vuelta, setVuelta] = useState(0)
  const guardadas = useRef(new Map())
  const primera = useRef(true)
  const yaMismo = useRef(false)

  useEffect(() => {
    if (!url) {
      setEstado({ res: null, error: null, cargando: false, trayendo: false, estadoHttp: null })
      return undefined
    }
    const guardada = guardadas.current.get(url)
    if (guardada && Date.now() - guardada.cuando < GUARDADA_MS) {
      primera.current = false
      setEstado({ res: guardada.res, error: null, cargando: false, trayendo: false, estadoHttp: null })
      return undefined
    }
    let vivo = true
    let intento = 0
    let espera = null
    const pedir = () => {
      setEstado(e => ({ ...e, cargando: true, error: null }))
      api.get(url)
        .then(r => {
          if (!vivo) return
          if (r?.motivo === 'bajando' && intento < REINTENTOS) {
            intento += 1
            setEstado(e => ({ ...e, trayendo: true }))
            espera = setTimeout(pedir, ESPERA_MS)
            return
          }
          if (r?.disponible) {
            guardadas.current.delete(url)
            guardadas.current.set(url, { res: r, cuando: Date.now() })
            if (guardadas.current.size > GUARDADAS) guardadas.current.delete(guardadas.current.keys().next().value)
          }
          setEstado({ res: r, error: null, cargando: false, trayendo: false, estadoHttp: null })
        })
        .catch(e => {
          if (!vivo) return
          // Sin respuesta nueva no queda la vieja (de otra consulta) en pantalla.
          // `estadoHttp`: con 429 (el freno) el servidor ya dice cuánto esperar.
          setEstado({ res: null, error: e?.message || 'sin respuesta', cargando: false, trayendo: false,
            estadoHttp: e?.status ?? null })
        })
    }
    if (primera.current || !pausa || yaMismo.current) pedir()
    else espera = setTimeout(pedir, pausa)
    primera.current = false
    yaMismo.current = false
    return () => { vivo = false; if (espera) clearTimeout(espera) }
  }, [url, vuelta, pausa])

  const reintentar = () => {
    guardadas.current.delete(url)
    yaMismo.current = true
    setVuelta(x => x + 1)
  }
  return { ...estado, reintentar }
}

export const mesCorto = (iso) => {
  const [y, m] = iso.split('-')
  return `${MONTHS[Number(m) - 1]?.slice(0, 3).toLowerCase()} ${y.slice(2)}`
}

export function Aviso({ children, error = false, detalle = null, onReintentar = null }) {
  return (
    <div role="status" className={`flex items-start gap-2 rounded-xl border px-4 py-4 text-[14px] ${
      error ? 'border-rendi-neg/30 bg-rendi-neg/5 text-ink-0' : 'border-line bg-bg-1 text-ink-1'}`}>
      {error && <AlertCircle size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-rendi-neg" />}
      <div>
        <p>
          {children}
          {onReintentar && (
            <button type="button" onClick={onReintentar}
              className="ml-1.5 inline-flex items-center min-h-11 sm:min-h-0 font-medium text-data-violet hover:underline">
              Reintentar
            </button>
          )}
        </p>
        {detalle && sinTripas(detalle) && <p className="mt-0.5 text-[12px] text-ink-2">Detalle: {enCastellano(detalle)}</p>}
      </div>
    </div>
  )
}

export function Dato({ etiqueta, children }) {
  return (
    <div className="min-w-0">
      <dt className="text-[12px] text-ink-2">{etiqueta}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  )
}

// Lo que es «peor caída», una sola vez: debajo de las tarjetas de «Una regla» y de
// la tabla de «Una cartera» (diseño 05/11, M7: la tarjeta lo decía sin explicarlo).
export const QUE_ES_LA_PEOR_CAIDA = 'Peor caída: lo más que llegó a bajar desde su mejor momento.'

/**
 * La tarjeta de un resultado de «Una regla» (la de cada regla y la de comprar y
 * mantener). Eran dos copias, una por modo, con dos reglas de columnas: el arreglo
 * de una no llegó a la otra y el número grande pisaba al de al lado («−32,6%43%»:
 * el «−» de la caída desaparecía; diseño 05/11, A1). El número grande va solo en
 * su renglón; los datos chicos, debajo, en dos columnas. En condicional: es lo que
 * habría dado, no lo que pasó (producto y método 05/11, A1 y C2). `datos`:
 * [{etiqueta, valor, detalle?}].
 */
export function TarjetaDeResultado({ nombre, subtitulo = null, trazo = null, resultado, datos, resaltada = false }) {
  return (
    <div className={`bg-bg-1 border rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-3 min-w-0 ${
      resaltada ? 'border-data-violet/40' : 'border-line'}`}>
      <div className="min-w-0">
        <h3 className="flex items-center gap-2 text-[14px] font-semibold text-ink-0">{trazo}{nombre}</h3>
        {subtitulo && <p className="mt-0.5 text-[12px] text-ink-2">{subtitulo}</p>}
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-3">
        <div className="col-span-2 min-w-0">
          <dt className="text-[12px] text-ink-2">Habría dado</dt>
          <dd className={`mt-0.5 text-[26px] leading-tight font-semibold tabular ${colorDe(resultado)}`}>
            {porcentaje(resultado)}
          </dd>
        </div>
        {datos.map(d => (
          <Dato key={d.etiqueta} etiqueta={d.etiqueta}>
            <span className="text-[16px] font-semibold tabular text-ink-0">{d.valor}</span>
            {d.detalle && <span className="text-[12.5px] text-ink-2 tabular"> {d.detalle}</span>}
          </Dato>
        ))}
      </dl>
    </div>
  )
}

export function Trazo({ color, dash }) {
  return (
    <svg width="16" height="4" aria-hidden="true" className="shrink-0">
      <line x1="0" y1="2" x2="16" y2="2" stroke={color} strokeWidth="2.5" strokeDasharray={dash} />
    </svg>
  )
}

export function Punto({ color }) {
  return <span aria-hidden="true" className="inline-block w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
}

/** El globo del gráfico: en el orden de la leyenda, con el trazo de cada línea y
 *  la plata con un decimal, como la leyenda y las tarjetas. Iba al revés, sin
 *  colores y con dólares enteros («US$ 133 y US$ 133»; diseño 05/11, M4, y
 *  verificación, V5). */
function GloboDeCien({ active, payload, label, lineas }) {
  if (!active || !payload?.length) return null
  const valor = Object.fromEntries(payload.map(p => [p.dataKey, p.value]))
  return (
    <div style={chartTooltip.contentStyle}>
      <p style={chartTooltip.labelStyle}>{fechaCorta(label)}</p>
      <ul className="flex flex-col gap-0.5">
        {lineas.filter(l => valor[l.clave] != null).map(l => (
          <li key={l.clave} className="flex items-center gap-1.5 text-[12.5px] text-ink-0 tabular">
            <Trazo color={l.color} dash={l.dash} />{l.nombre}: {enQueTermino(valor[l.clave])}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** «Cómo habrían ido US$ 100»: una línea por cada cosa que se compara, todas en
 *  100 el primer día. `curva`: [{d, <clave>: valor}]; `lineas`: [{clave, nombre,
 *  color, dash, final}], la de adelante primero; `franjas`: [{compra, venta}]
 *  pintadas detrás (los días en que una regla estaba comprada). */
export function GraficoDeCien({ curva, lineas, desde, hasta, nota = '', franjas = [], colorFranjas, children }) {
  return (
    <section aria-label="Cómo habrían ido US$ 100" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-3 min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold text-ink-0">Cómo habrían ido US$ 100</h3>
          <p className="text-[12px] text-ink-2 mt-0.5">
            Del {fechaCorta(desde)} al {fechaCorta(hasta)}, en dólares.{nota ? ` ${nota}` : ''}
          </p>
        </div>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
          {lineas.map(l => (
            <li key={l.clave} className="inline-flex items-center gap-1.5">
              <Trazo color={l.color} dash={l.dash} /><span className="text-ink-1">{l.nombre}</span>
              <span className="font-semibold text-ink-0 tabular">{enQueTermino(l.final)}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="h-64 sm:h-80 -mx-1" role="img"
        aria-label={lineas.map(l => `${l.nombre}: US$ 100 terminaron en ${enQueTermino(l.final)}`).join('; ')}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={curva} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid {...chartGrid} />
            <XAxis dataKey="d" tick={chartTickSm} axisLine={false} tickLine={false} tickFormatter={mesCorto} minTickGap={40} />
            <YAxis tick={chartTickSm} axisLine={false} tickLine={false} width={36}
              domain={['auto', 'auto']} tickFormatter={x => Math.round(x)} />
            {franjas.map(o => (
              <ReferenceArea key={o.compra} x1={o.compra} x2={o.venta} fill={colorFranjas} fillOpacity={0.12}
                stroke="none" ifOverflow="hidden" />
            ))}
            {/* La vara de no hacer nada, con nombre, como en Comparar: lo que termina
                abajo de esta línea perdió dólares (producto 05/11, A2). */}
            <ReferenceLine y={100} stroke={chartReferenceStroke}
              label={{ value: 'Guardar dólares', position: 'insideBottomRight', fill: v('ink-2'), fontSize: 11 }} />
            <Tooltip cursor={chartTooltip.cursor} content={<GloboDeCien lineas={lineas} />} />
            {[...lineas].reverse().map(l => (
              <Line key={l.clave} dataKey={l.clave} name={l.nombre} type="linear" dot={false} stroke={l.color}
                strokeWidth={l.dash ? 1.5 : 2} strokeDasharray={l.dash} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {children}
    </section>
  )
}
