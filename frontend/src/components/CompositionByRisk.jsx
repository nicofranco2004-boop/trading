// CompositionByRisk — el corte grueso de una cartera: variable / fija / efectivo.
// ═══════════════════════════════════════════════════════════════════════════
// Una barra horizontal por grupo, en el mismo estilo que CompositionByAsset
// (diagnostico/) — violeta/ámbar/gris, texto en tokens ink, el color va SOLO
// en la marca.
//
// Por qué barras y no otra torta: la pregunta es de comparación entre dos o
// tres magnitudes ("¿cuánto de esto se puede mover?"), y para comparar
// longitudes el ojo es mucho mejor que para comparar ángulos. Las tortas de
// abajo contestan otra cosa — cómo se reparte cada lado por adentro.
//
// Los colores son LOS MISMOS que usan las porciones equivalentes en los
// donuts de la sección: el ámbar de "Renta fija" es el de "Bonos y letras" y
// el gris el de "Efectivo". Así la barra y las tortas se leen como una sola
// pieza y el ojo puede saltar de una a la otra.

import InfoTooltip from './InfoTooltip'

const clamp = (v) => Math.max(0, Math.min(100, Number(v) || 0))

export default function CompositionByRisk({
  items = [],
  total = 0,
  fmt = (v) => `US$ ${Math.round(v).toLocaleString('es-AR')}`,
  title = 'Renta variable, renta fija y efectivo',
  info = null,
  className = '',
}) {
  if (!items.length || !(total > 0)) return null

  // El titular: cuánto está expuesto a que el mercado se mueva. Es el número
  // que resume la fila entera, y va con un decimal — el de la barra está
  // redondeado y a veces el 0,4 importa.
  const variable = items.find(i => i.key === 'variable')

  return (
    <div className={`border border-line rounded bg-bg-1 p-4 ${className}`}>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <h3 className="text-sm font-medium text-ink-0 truncate">{title}</h3>
          {info && <InfoTooltip size={12} align="left">{info}</InfoTooltip>}
        </div>
        {variable && (
          <span className="text-xs text-ink-2 flex-shrink-0">
            Variable:{' '}
            <span className="font-semibold tabular text-ink-1">
              {variable.pct.toFixed(1)}%
            </span>
          </span>
        )}
      </div>

      <div className="space-y-2.5">
        {items.map(it => {
          const pct = clamp(it.pct)
          return (
            <div key={it.key} className="flex items-center gap-3">
              <span className="w-[104px] shrink-0 text-xs text-ink-1 truncate whitespace-nowrap">
                {it.label}
              </span>
              <div className="flex-1 h-[6px] rounded-full bg-bg-3 overflow-hidden min-w-[60px]">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${pct}%`, background: it.color }}
                />
              </div>
              {/* Ancho FIJO, no `flex-shrink-0` a secas: con ancho variable el
                  riel de cada fila terminaba midiendo distinto según cuántos
                  dígitos tuviera SU monto, y entonces las barras dejaban de
                  compartir escala. Medido en el libro demo: 948px contra
                  954px por un carácter de diferencia — poco acá, pero en
                  mobile con el toggle en pesos el riel colapsa y una porción
                  chica puede llegar a dibujar una barra más larga que una
                  grande. En un gráfico cuyo único trabajo es comparar
                  longitudes, eso lo invalida.

                  Y en pantallas chicas el monto directamente no entra: se
                  oculta para que el riel siga siendo legible. El % queda, que
                  es el número que se compara. */}
              <span className="hidden sm:block text-ink-3 tabular text-[11px] w-28 text-right flex-shrink-0">
                {fmt(it.value)}
              </span>
              <span className="text-ink-0 tabular font-medium text-xs w-11 text-right flex-shrink-0">
                {pct.toFixed(1)}%
              </span>
            </div>
          )
        })}
      </div>

      {/* Leyenda: qué instrumentos entraron en cada barra. No es decoración —
          que la cripto y los FCI cuenten como "renta variable" son decisiones
          de criterio, y quien lee el número tiene derecho a saber cuáles se
          tomaron sin abrir el código. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-3 pt-3 border-t border-line/40">
        {items.map(it => (
          <span key={it.key} className="inline-flex items-center gap-1.5 text-[10.5px] text-ink-3">
            <span
              className="inline-block w-3 h-2 rounded-[2px] flex-shrink-0"
              style={{ background: it.color }}
              aria-hidden="true"
            />
            {it.classes?.length ? it.classes.join(' · ') : it.label}
          </span>
        ))}
      </div>
    </div>
  )
}
