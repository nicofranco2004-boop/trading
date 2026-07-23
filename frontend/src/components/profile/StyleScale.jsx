// StyleScale — escala pasivo↔activo: estilo declarado vs operatoria real.
// ═══════════════════════════════════════════════════════════════════════════
// Body de la card de estilo en Análisis › Perfil. Dibuja una escala horizontal
// con dos marcadores: el gris es lo que el usuario declaró en el test (puede
// no existir) y el violeta es lo que inferimos de sus trades/mes reales.
// Los tags se clampean a [8, 92]% para que no se corten en los bordes.

export default function StyleScale({
  declaredPos,
  declaredLabel,
  actualPos,
  tradesPerMonth,
  inferredLabel,
}) {
  if (actualPos == null) return null

  // Los marcadores van donde corresponde; solo el TEXTO se clampea al borde.
  const clampTag = (x) => Math.min(92, Math.max(8, x))

  return (
    <div>
      {/* Escala — my-7 deja aire para los tags arriba y abajo */}
      <div className="relative h-[6px] rounded-full bg-bg-2 my-7">
        {declaredPos != null && (
          <>
            <span
              className="absolute top-1/2 w-3 h-3 rounded-full bg-ink-2 border-2 border-bg-1 -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${declaredPos}%` }}
            />
            <span
              className="absolute -top-5 font-mono text-[10px] text-ink-2 -translate-x-1/2 whitespace-nowrap"
              style={{ left: `${clampTag(declaredPos)}%` }}
            >
              declarado
            </span>
          </>
        )}
        <span
          className="absolute top-1/2 w-3 h-3 rounded-full bg-data-violet border-2 border-bg-1 -translate-x-1/2 -translate-y-1/2"
          style={{ left: `${actualPos}%` }}
        />
        <span
          className="absolute top-4 font-mono text-[10px] text-data-violet tabular-nums -translate-x-1/2 whitespace-nowrap"
          style={{ left: `${clampTag(actualPos)}%` }}
        >
          real ({tradesPerMonth}/mes)
        </span>
      </div>

      {/* Extremos de la escala */}
      <div className="flex justify-between text-[12px] text-ink-3 font-medium">
        <span>Pasivo</span>
        <span>Activo</span>
      </div>

      <p className="text-xs text-ink-2 mt-3 leading-relaxed">
        {declaredLabel ? (
          <>
            Declaraste estilo <b className="text-ink-1">{declaredLabel.toLowerCase()}</b>; operás{' '}
            <b className="text-ink-1 tabular-nums">{tradesPerMonth} veces/mes</b> — en los hechos,{' '}
            {inferredLabel.toLowerCase()}.
          </>
        ) : (
          <>
            Operás <b className="text-ink-1 tabular-nums">{tradesPerMonth} veces/mes</b> — en los
            hechos, {inferredLabel.toLowerCase()}.
          </>
        )}
      </p>
    </div>
  )
}
