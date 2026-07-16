// ObjectiveStat — % de la cartera alineado con el objetivo declarado.
// ═══════════════════════════════════════════════════════════════════════════
// Body de la card de objetivo en Análisis › Perfil. Stat grande con el % que
// apunta al objetivo del test (ej: "Libertad financiera" → crecimiento) +
// barra de progreso fina. La nota marca cuando una porción grande de la
// cartera apunta para otro lado.

export default function ObjectiveStat({ goalLabel, alignedPct, alignedLabel, misalignedPct }) {
  if (alignedPct == null) return null

  return (
    <div>
      <div className="flex items-baseline gap-3">
        <span className="text-3xl font-semibold text-ink-0 tabular-nums">{alignedPct}%</span>
        <span className="text-xs text-ink-2 max-w-[220px] leading-snug">
          de la cartera alineado con tu objetivo ({alignedLabel})
        </span>
      </div>

      {/* Barra de progreso */}
      <div className="relative h-[6px] rounded-full bg-bg-2 mt-3 overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-data-violet"
          style={{ width: `${alignedPct}%` }}
        />
      </div>

      <p className="text-xs text-ink-2 mt-3 leading-relaxed">
        Tu objetivo: <b className="text-ink-1">{goalLabel}</b>.
        {misalignedPct > 40 ? (
          <>
            {' '}
            <span className="text-rendi-warn tabular-nums">{misalignedPct}%</span> apunta para
            otro lado.
          </>
        ) : (
          ' La composición acompaña.'
        )}
      </p>
    </div>
  )
}
