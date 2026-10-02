import { pctTxt } from '../../utils/format'
import AnimatedNumber from '../AnimatedNumber'
import { useVistoPerfil, formatoQueCuenta } from './vistoPerfil'
// DrawdownStat — peor caída real del período vs tolerancia declarada.
// ═══════════════════════════════════════════════════════════════════════════
// Body de la card de drawdown en Análisis › Perfil. Stat grande con la peor
// caída real de la cartera; se pinta de warn solo si superó la banda de
// tolerancia que el usuario declaró en el test (comparison === 'above').

export default function DrawdownStat({ behaviorLabel, toleranceLabel, drawdownPct, comparison }) {
  // Al verse, la caída cuenta hasta su valor.
  const visto = useVistoPerfil()
  if (drawdownPct == null) return null

  return (
    <div>
      <div className="flex items-baseline gap-3">
        <span
          className={`text-3xl font-semibold tabular-nums ${
            comparison === 'above' ? 'text-rendi-warn' : 'text-ink-0'
          }`}
        >
          -<AnimatedNumber value={drawdownPct} visto={visto} format={formatoQueCuenta(drawdownPct)} />
        </span>
        <span className="text-xs text-ink-2 max-w-[220px] leading-snug">
          tu peor caída del período
        </span>
      </div>

      <p className="text-xs text-ink-2 mt-3 leading-relaxed">
        Declaraste que ante una caída: <b className="text-ink-1">{behaviorLabel}</b> (tolerancia{' '}
        <span className="tabular-nums">{toleranceLabel}</span>).{' '}
        {comparison === 'above' ? (
          <span className="text-rendi-warn">Tu caída real la superó.</span>
        ) : comparison === 'below' ? (
          'Tu caída real quedó por debajo — sin estrés.'
        ) : (
          'Tu caída real quedó dentro de esa banda.'
        )}
      </p>
    </div>
  )
}
