// BarraGrafico — la barra de herramientas del gráfico técnico, como la de TradingView.
// ════════════════════════════════════════════════════════════════════════════
// Un botón por capa (volumen, promedios, Fibonacci, Elliott, RSI, fuerza de la
// tendencia, balances, tus compras, tu precio) y por herramienta (medir,
// dibujar), con su ícono y su nombre. Reemplaza a la leyenda de «chips» de
// abajo del gráfico: Fibonacci y Elliott ahí no se notaban (Nico, 24/10).
//
// Todo arranca PRENDIDO (pedido de Nico: «que estén todas puestas de manera
// predeterminada y que ahí cada uno decida si la deja o no»). Lo que cada uno
// apaga se guarda en el navegador (`rendi_grafico_capas`, como el tipo de
// gráfico en `rendi_grafico_tipo`); «Volver a lo de fábrica» lo olvida.
//
// Una sola barra para compu y celular (R6): en compu va parada, pegada a la
// izquierda del gráfico, con el ícono solo y el nombre al pasar el mouse; en el
// celular es la MISMA fila acostada arriba del gráfico, que se desliza de costado,
// con botones de 44 px y el nombre a la vista (no hay mouse que pase por encima).
//
// Una capa sin datos para este activo (sin volumen, sin conteo de Elliott, sin
// compras tuyas) no se esconde: el botón queda gris con el borde punteado y, al
// tocarlo, dice por qué. Así la barra es la misma en todos los activos.

const CLAVE = 'rendi_grafico_capas'

/** Cómo viene el gráfico: todo prendido. */
export const CAPAS_DE_FABRICA = Object.freeze({
  vol: true, s200: true, s50: true, fib: true, ell: true, rsi: true, fuerza: true,
  eventos: true, marcas: true, prom: true,
})

/**
 * Lo que la persona dejó prendido y apagado la última vez. Lo que no está
 * guardado (nunca lo tocó, o es una capa nueva) viene de fábrica. El navegador
 * puede tener el almacenamiento bloqueado (modo privado) o un valor roto: todo
 * prendido.
 */
export function capasGuardadas() {
  const capas = { ...CAPAS_DE_FABRICA }
  try {
    const g = JSON.parse(localStorage.getItem(CLAVE) || 'null')
    if (g && typeof g === 'object') {
      for (const k of Object.keys(capas)) if (typeof g[k] === 'boolean') capas[k] = g[k]
    }
  } catch { /* sin almacenamiento o valor roto: de fábrica */ }
  return capas
}

export function guardarCapas(capas) {
  try { localStorage.setItem(CLAVE, JSON.stringify(capas)) } catch { /* sin almacenamiento */ }
}

export function olvidarCapas() {
  try { localStorage.removeItem(CLAVE) } catch { /* sin almacenamiento */ }
}

export const sonDeFabrica = (capas) => Object.keys(CAPAS_DE_FABRICA).every(k => capas[k] === CAPAS_DE_FABRICA[k])

/**
 * `grupos`: listas de botones, separadas por una rayita. Cada botón:
 *   { id, nombre, icono, onClick,
 *     activo     — prendido (true) / apagado (false); undefined = no es un
 *                  interruptor (hace algo), se ve neutro,
 *     radio      — uno de varios (línea o velas): el no elegido no va tachado,
 *     herramienta — se prende para usarla (medir): apagada se ve como un botón
 *                  común, sin tachar,
 *     estado     — el texto del globo en vez de «prendido/apagado»,
 *     sinDatos   — por qué no se puede prender en este activo (deshabilitado) }
 * `onAviso(texto)`: al tocar un botón sin datos, la explicación (en el celular
 * no hay globo al pasar el mouse); null al tocar cualquier otro.
 */
export default function BarraGrafico({ grupos, onAviso }) {
  return (
    <div role="toolbar" aria-label="Herramientas del gráfico"
      className="flex sm:flex-col gap-1.5 sm:gap-1 -mx-3 px-3 sm:mx-0 sm:px-0 pb-1.5 sm:pb-0 overflow-x-auto sm:overflow-visible shrink-0 sm:self-start">
      {grupos.filter(g => g.length).map((g, k) => (
        <div key={k} className={`flex sm:flex-col gap-1.5 sm:gap-1 shrink-0 ${k > 0 ? 'border-l sm:border-l-0 sm:border-t border-line/70 pl-1.5 sm:pl-0 sm:pt-1' : ''}`}>
          {g.map(b => <Boton key={b.id} b={b} onAviso={onAviso} />)}
        </div>
      ))}
    </div>
  )
}

function Boton({ b, onAviso }) {
  const interruptor = typeof b.activo === 'boolean'
  const apagado = interruptor && !b.activo && !b.radio && !b.herramienta
  const estado = b.sinDatos || b.estado || (interruptor ? (b.activo ? 'Prendido. Tocá para apagarlo.' : 'Apagado. Tocá para prenderlo.') : '')
  const clase = b.sinDatos
    ? 'border-dashed border-line text-ink-3 opacity-55 cursor-not-allowed'
    : !interruptor || (b.herramienta && !b.activo) ? 'border-line-2 bg-bg-2 text-ink-1 hover:text-ink-0 hover:border-ink-3'
      : b.activo ? 'border-rendi-accent/55 bg-rendi-accent/15 text-ink-0 hover:border-rendi-accent'
        : 'border-line bg-transparent text-ink-3 hover:text-ink-1 hover:border-line-2'
  return (
    <button type="button" data-capa={b.id}
      aria-pressed={interruptor && !b.sinDatos ? b.activo : undefined}
      aria-disabled={b.sinDatos ? true : undefined}
      onClick={() => {
        if (b.sinDatos) { onAviso?.(`${b.nombre}: ${b.sinDatos}`); return }
        onAviso?.(null)
        b.onClick()
      }}
      className={`group relative shrink-0 inline-flex items-center gap-1.5 h-11 min-w-11 px-3 sm:h-9 sm:w-9 sm:min-w-0 sm:px-0 sm:justify-center rounded-lg border text-[12.5px] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-rendi-accent ${clase}`}>
      <span aria-hidden="true" className={`relative inline-flex items-center justify-center w-5 h-5 ${(interruptor && !b.activo && !b.herramienta) || b.sinDatos ? 'opacity-45 grayscale' : ''}`}>
        {b.icono}
        {/* Apagado: el ícono tachado, como un parlante en silencio. */}
        {apagado && <span className="absolute left-1/2 top-1/2 w-6 h-0.5 -translate-x-1/2 -translate-y-1/2 -rotate-45 rounded-full bg-ink-1" />}
      </span>
      <span className="whitespace-nowrap sm:sr-only">{b.nombre}</span>
      {b.sinDatos && <span className="sr-only">{`: ${b.sinDatos}`}</span>}
      {/* El globo con el nombre, al pasar el mouse o con el foco (sólo compu). */}
      <span aria-hidden="true"
        className="pointer-events-none absolute left-full top-1/2 -translate-y-1/2 ml-2 z-30 hidden sm:group-hover:block sm:group-focus-visible:block w-max max-w-[16rem] rounded border border-line-2 bg-bg-raised px-2 py-1 text-left text-[11.5px] leading-snug shadow-sm">
        <span className="block font-semibold text-ink-0">{b.nombre}</span>
        {estado && <span className="block text-ink-2">{estado}</span>}
      </span>
    </button>
  )
}
