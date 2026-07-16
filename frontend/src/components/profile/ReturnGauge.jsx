// ReturnGauge — bullet chart del retorno real vs la meta del perfil.
// ═══════════════════════════════════════════════════════════════════════════
// Body del módulo de retorno en el perfil: barra horizontal (divs, sin libs)
// con marcador de cero, fill desde 0 hasta el retorno real (neto de
// inflación) y marcador de la meta que implica la expectativa declarada.
// Verde si real ≥ meta, amber si ≥ 0 pero abajo de la meta, rojo si negativo.

export default function ReturnGauge({ realPct, floorPct, expectationLabel, comparison }) {
  if (realPct == null || floorPct == null || !Number.isFinite(realPct)) return null

  // Escala con aire a ambos lados para que los tags nunca queden pegados al borde.
  const min = Math.min(-8, realPct - 4, floorPct - 4)
  const max = Math.max(24, realPct + 6, floorPct + 6)
  const pos = (v) => Math.min(1, Math.max(0, (v - min) / (max - min))) * 100
  const clampTag = (x) => Math.min(92, Math.max(8, x))
  const sign = (v) => (v > 0 ? '+' : '')

  const fillCls =
    realPct >= floorPct ? 'bg-rendi-pos' : realPct >= 0 ? 'bg-rendi-warn' : 'bg-rendi-neg'
  const toneCls =
    realPct >= floorPct ? 'text-rendi-pos' : realPct >= 0 ? 'text-rendi-warn' : 'text-rendi-neg'

  const zero = pos(0)
  const real = pos(realPct)
  const meta = pos(floorPct)
  const fillLeft = Math.min(zero, real)
  const fillWidth = Math.abs(real - zero)

  const compText =
    comparison === 'below'
      ? 'por debajo de esa expectativa'
      : comparison === 'above'
        ? 'por encima de esa expectativa'
        : 'en línea con esa expectativa'

  return (
    <div>
      <div className="px-6 overflow-visible">
        {/* Track + marcadores; my-8 deja lugar a los tags arriba y abajo */}
        <div
          role="img"
          aria-label={`Retorno real ${sign(realPct)}${realPct}% frente a una meta de ${sign(floorPct)}${floorPct}%`}
          className="relative h-[10px] rounded-full bg-bg-3 my-8"
        >
          {/* Fill desde el cero hasta el retorno real */}
          <div
            className={`absolute h-full rounded-full ${fillCls}`}
            style={{ left: `${fillLeft}%`, width: `${fillWidth}%` }}
          />

          {/* Marcador de cero */}
          <div
            className="absolute w-px h-[16px] top-1/2 -translate-y-1/2"
            style={{ left: `${zero}%`, background: '#4A5468' }}
          />

          {/* Meta — línea gris + tag debajo del track */}
          <div
            className="absolute w-0.5 h-[18px] top-1/2 -translate-y-1/2 bg-ink-2"
            style={{ left: `${meta}%` }}
          />
          <div
            className="absolute top-full mt-1.5 -translate-x-1/2 font-mono text-[10px] text-ink-2 tabular-nums whitespace-nowrap"
            style={{ left: `${clampTag(meta)}%` }}
          >
            meta {sign(floorPct)}{floorPct}%
          </div>

          {/* Real — línea del color del fill + tag arriba del track */}
          <div
            className={`absolute w-0.5 h-[18px] top-1/2 -translate-y-1/2 ${fillCls}`}
            style={{ left: `${real}%` }}
          />
          <div
            className={`absolute bottom-full mb-1.5 -translate-x-1/2 font-mono text-[10px] tabular-nums whitespace-nowrap ${toneCls}`}
            style={{ left: `${clampTag(real)}%` }}
          >
            real {sign(realPct)}{realPct}%
          </div>
        </div>
      </div>

      <p className="text-xs text-ink-2 leading-relaxed">
        Buscás <b className="text-ink-1">{expectationLabel}</b>. Tu retorno real (neto de
        inflación) es{' '}
        <span className={`${toneCls} tabular-nums`}>
          {sign(realPct)}
          {realPct}%
        </span>{' '}
        · {compText}.
      </p>
    </div>
  )
}
