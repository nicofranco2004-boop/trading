import { Link } from 'react-router-dom'
import { useCurrency, pickFinancialRate } from '../contexts/CurrencyContext'
import { fmtRate } from '../hooks/useCurrencyChoice'

/**
 * CurrencySwitcher — el selector de moneda GLOBAL, fijo en el chrome de la app.
 * ═════════════════════════════════════════════════════════════════════════════
 * En qué moneda ve el usuario sus números es una decisión que atraviesa TODA la
 * app (state global, persistido). El control, en cambio, vivía repartido: un
 * toggle USD|ARS escondido en la toolbar de Cartera, otro arriba del hero del
 * Dashboard, y el riel de 3 opciones sólo en Configuración → Tipos de cambio.
 * Resultado: en Métricas —donde los números SÍ respetan la preferencia— no había
 * cómo cambiarla, y el que la encontraba en Cartera tenía que volver ahí cada vez.
 *
 * Este componente es la respuesta: UN control, siempre en el mismo lugar de la
 * pantalla, en todas las páginas. Vive en el shell (sidebar en escritorio, barra
 * superior en mobile), nunca dentro de una página.
 *
 * DOS OPCIONES, NO TRES. El primer intento puso acá el riel completo (USD MEP ·
 * USD CCL · Pesos) en un popover. Se cambió a un toggle `USD | Pesos` a secas:
 * elegir la moneda es la decisión de todos los días, elegir CON QUÉ DÓLAR se
 * valúa es una preferencia que se toca una vez. El switcher USA el dólar que ya
 * está configurado (`valuationDollar`) y lo MUESTRA debajo ("Dólar MEP ·
 * $1.424"), con link a /config?tab=fx para cambiarlo. Nunca lo pisa.
 *
 * Variantes (`variant`) — cambia el envoltorio, el toggle es el mismo:
 *   • 'row'  → sidebar expandida: segmentado ancho + la línea del dólar debajo
 *   • 'chip' → barra superior mobile: segmentado compacto
 *   • 'mini' → sidebar colapsada: segmentado VERTICAL en 40px de ancho útil
 *
 * ⚠️ QUÉ PANTALLAS LA RESPETAN — verificado a mano en demo, moneda = Pesos:
 *   • SÍ: Cartera, Dashboard, Movimientos, Métricas → Diagnóstico, las vistas
 *     mobile, y los KPIs de arriba de Métricas → Reportes.
 *   • NO: Métricas → Comportamiento (todas sus cifras) y el detalle del período
 *     de Métricas → Reportes (Capital actual / P&L del mes / la narrativa).
 *     No es un descuido del frontend: esos textos llegan YA FORMATEADOS en USD
 *     desde el backend (`backend/behavioral.py`, `backend/reporting/builder.py`),
 *     así que honrar la preferencia ahí es un cambio de backend, no de acá.
 *
 * El control igual se muestra en todas: la preferencia es una sola y el usuario
 * la cambia desde donde esté. Cuando el backend devuelva números en vez de
 * strings, esas dos pantallas se convierten — la salida NO es esconder el
 * control en algunas páginas, que es justo el problema que este componente vino
 * a resolver.
 */

const OPTS = [
  { key: 'USD', label: 'USD',   short: 'USD' },
  { key: 'ARS', label: 'Pesos', short: 'ARS' },
]

export default function CurrencySwitcher({ variant = 'row', className = '' }) {
  const { currency, setCurrency, valuationDollar, dolar } = useCurrency()
  const isArs = currency === 'ARS'

  // El dólar que YA eligió el usuario en Configuración — acá sólo se informa.
  // Se deriva con el mismo `pickFinancialRate` del contexto (y no con `tcValuacion`)
  // para no mostrar el default 1415 durante el vuelo del primer /dolar.
  const dollarName = valuationDollar === 'ccl' ? 'CCL' : 'MEP'
  const rate = fmtRate(pickFinancialRate(dolar, valuationDollar))

  const title = isArs
    ? `Estás viendo todo en pesos${rate ? ` (dólar ${dollarName} ${rate})` : ''}`
    : `Estás viendo todo en dólares${rate ? ` (${dollarName} ${rate})` : ''}`

  // Un segmento del toggle. `vertical` sólo cambia el ancho: el estilo activo
  // (pastilla violeta) es el mismo en las tres variantes.
  function Seg({ opt, text, pad }) {
    const on = (opt.key === 'ARS') === isArs
    return (
      <button
        type="button"
        onClick={() => setCurrency(opt.key)}
        aria-pressed={on}
        title={opt.key === 'ARS' ? 'Mostrar los importes en pesos' : 'Mostrar los importes en dólares'}
        className={`flex-1 rounded-full ${pad} text-center font-medium select-none transition-colors ${
          on ? 'bg-data-violet/15 text-data-violet' : 'text-ink-2 hover:text-ink-0'
        }`}
      >
        {text}
      </button>
    )
  }

  const groupCls = 'flex items-center rounded-full border border-line-2 bg-bg-2 p-0.5'

  if (variant === 'chip') {
    return (
      <div role="group" aria-label="Moneda de visualización" title={title}
        className={`${groupCls} ${className}`}>
        {OPTS.map(o => <Seg key={o.key} opt={o} text={o.label} pad="px-2.5 py-1 text-[11.5px]" />)}
      </div>
    )
  }

  if (variant === 'mini') {
    return (
      <div role="group" aria-label="Moneda de visualización" title={title}
        className={`${groupCls} flex-col w-full ${className}`}>
        {OPTS.map(o => <Seg key={o.key} opt={o} text={o.short} pad="px-1 py-1 text-[10px]" />)}
      </div>
    )
  }

  return (
    <div className={className}>
      <div role="group" aria-label="Moneda de visualización" className={`${groupCls} w-full`}>
        {OPTS.map(o => <Seg key={o.key} opt={o} text={o.label} pad="px-3 py-1.5 text-[13px]" />)}
      </div>
      {/* El dólar de valuación: se informa, no se elige acá. El link lleva
          derecho a la sección donde sí se cambia. */}
      <Link
        to="/config?tab=fx"
        title="Cambiar el dólar de valuación (MEP / CCL)"
        className="mt-1.5 flex items-center justify-center gap-1 text-[10.5px] text-ink-3 hover:text-ink-1 transition-colors"
      >
        <span>Dólar {dollarName}</span>
        {rate && <span className="tabular">· {rate}</span>}
      </Link>
    </div>
  )
}
