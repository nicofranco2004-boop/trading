// CompositionByAsset — peso de cada activo sobre el total de la cartera.
// ═══════════════════════════════════════════════════════════════════════════
// Body del módulo: una barra horizontal por activo (incluye cash / stables),
// ya ordenados desc por el padre. Violeta = invertido, gris = cash. Los colores
// de serie van SOLO en las marcas — el texto siempre en tokens ink. El header
// y el título viven en la card contenedora.

const VIOLET = '#8B7DFF'
const GRAY = '#4A5468'

const clamp = (v) => Math.max(0, Math.min(100, Number(v) || 0))

export default function CompositionByAsset({ rows }) {
  if (!rows?.length) return null

  return (
    <div>
      <div className="space-y-2">
        {rows.map((r, i) => {
          const pct = clamp(r.pct)
          return (
            <div key={i} className="flex items-center gap-3">
              <span className="w-16 shrink-0 text-xs text-ink-1 truncate whitespace-nowrap">
                {r.name}
              </span>
              <div className="flex-1 h-[6px] rounded-full bg-bg-3 overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${pct}%`, background: r.cash ? GRAY : VIOLET }}
                />
              </div>
              <span
                className={`font-mono text-[11px] tabular-nums w-9 text-right ${
                  r.cash ? 'text-ink-2' : 'text-ink-1'
                }`}
              >
                {Math.round(pct)}%
              </span>
            </div>
          )
        })}
      </div>

      {/* Leyenda */}
      <div className="flex items-center gap-4 mt-3">
        <span className="inline-flex items-center gap-1.5 text-[11px] text-ink-2">
          <span
            className="inline-block w-3 h-2 rounded-[2px]"
            style={{ background: VIOLET }}
            aria-hidden="true"
          />
          Invertido
        </span>
        <span className="inline-flex items-center gap-1.5 text-[11px] text-ink-2">
          <span
            className="inline-block w-3 h-2 rounded-[2px]"
            style={{ background: GRAY }}
            aria-hidden="true"
          />
          Cash / stables
        </span>
      </div>
    </div>
  )
}
