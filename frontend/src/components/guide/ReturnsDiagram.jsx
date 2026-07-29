// ReturnsDiagram — diagrama "Una cartera, dos preguntas".
// ════════════════════════════════════════════════════════════════════════════
// Explica visualmente cómo Rendi calcula el rendimiento: los mismos insumos
// (capital aportado + FIFO del historial) se BIFURCAN en dos respuestas —
// la PLATA en USD (verde) y el RENDIMIENTO en % (sky, ponderado por tiempo).
// El mini-timeline del carril % prueba que el % ignora CUÁNDO aportaste.
//
// App dark-only (darkMode:'class', .dark siempre puesta) → paleta hardcodeada
// del theme (patrón ProfileRadar/Heatmap). Sin sombras: elevación = borde 1px.
// Se usa en /guia/insights-y-reportes dentro de <figure> (fuera de .blog-prose).

const C = {
  violet: '#8B7DFF', violetFill: 'rgba(139,125,255,0.12)', violetDeep: '#1E1840',
  green: '#21D07A', greenFill: 'rgba(33,208,122,0.10)',
  sky: '#5B9DF9', skyFill: 'rgba(91,157,249,0.10)', aqua: '#46C6E0',
  ink0: '#E6EAF2', ink1: '#C3CAD8', ink2: '#9CA3B5', ink3: '#5A6478',
  line: '#1B2230', line2: '#262E40', surface: '#141923', panel: '#0E1218',
}
const SANS = 'Geist, system-ui, sans-serif'
const MONO = "'JetBrains Mono', ui-monospace, monospace"

// Badge numerado (riel de progreso 1-5). Texto oscuro sobre acento, claro sobre neutro.
function Badge({ x, y, n, fill, dark = true }) {
  return (
    <g aria-hidden="true">
      <rect x={x} y={y} width="17" height="17" rx="4" fill={fill} />
      <text x={x + 8.5} y={y + 12.3} textAnchor="middle" fontFamily={SANS}
        fontSize="10.5" fontWeight="600" fill={dark ? '#07090C' : C.ink0}>{n}</text>
    </g>
  )
}

export default function ReturnsDiagram() {
  return (
    <svg viewBox="0 0 480 716" width="100%" style={{ maxWidth: 460, height: 'auto' }}
      className="block mx-auto" role="img"
      aria-label="Cómo Rendi separa los dólares ganados del porcentaje de rendimiento: los mismos insumos (capital aportado y FIFO) se bifurcan en la plata en dólares y el rendimiento en porcentaje ponderado por tiempo.">
      <title>Una cartera, dos preguntas</title>
      <defs>
        <marker id="rdArrowN" markerWidth="8" markerHeight="8" refX="3.2" refY="4" orient="auto">
          <path d="M1,1.5 L5.5,4 L1,6.5" fill="none" stroke={C.ink3} strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
        </marker>
        <marker id="rdArrowG" markerWidth="8" markerHeight="8" refX="3.2" refY="4" orient="auto">
          <path d="M1,1.5 L5.5,4 L1,6.5" fill="none" stroke={C.green} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
        </marker>
        <marker id="rdArrowS" markerWidth="8" markerHeight="8" refX="3.2" refY="4" orient="auto">
          <path d="M1,1.5 L5.5,4 L1,6.5" fill="none" stroke={C.sky} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
        </marker>
        <marker id="rdArrowV" markerWidth="9" markerHeight="9" refX="4" refY="2" orient="auto">
          <path d="M1,6 L4,1 L7,6" fill="none" stroke={C.violet} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
        </marker>
      </defs>

      {/* ── Kicker ── */}
      <text x="240" y="22" textAnchor="middle" fontFamily={MONO} fontSize="10"
        letterSpacing="1.6" fill={C.ink2}>UNA CARTERA · DOS PREGUNTAS</text>

      {/* ══ ZONA A — INSUMOS COMPARTIDOS ══ */}
      {/* A1 · Capital aportado (violet) */}
      <rect x="28" y="42" width="196" height="100" rx="8" fill={C.violetFill} stroke={C.violet} strokeWidth="1" />
      <Badge x={38} y={52} n="1" fill={C.violet} />
      <text x="64" y="66" fontFamily={SANS} fontSize="13.5" fontWeight="600" fill={C.ink0}>Capital aportado</text>
      <text x="44" y="92" fontFamily={SANS} fontSize="10.5" fill={C.ink2}>la plata de tu bolsillo</text>
      <text x="44" y="118" fontFamily={MONO} fontSize="10.5" fill={C.ink1}>inicial + Σ(dep − ret)</text>
      <text x="44" y="133" fontFamily={SANS} fontSize="9" fill={C.ink3}>depósitos suman · retiros restan</text>

      {/* A2 · FIFO (neutro) */}
      <rect x="256" y="42" width="196" height="100" rx="8" fill={C.surface} stroke="#3A4256" strokeWidth="1" />
      <Badge x={266} y={52} n="5" fill="#3A4256" dark={false} />
      <text x="292" y="66" fontFamily={SANS} fontSize="13.5" fontWeight="600" fill={C.ink0}>FIFO arma la ganancia</text>
      <text x="272" y="92" fontFamily={SANS} fontSize="10.5" fill={C.ink2}>match vs la compra más vieja</text>
      <text x="272" y="118" fontFamily={MONO} fontSize="10.5" fill={C.ink1}>venta − costo − comis.</text>
      <text x="272" y="133" fontFamily={SANS} fontSize="9" fill={C.ink3}>realizado + no realizado</text>

      {/* Conectores A1,A2 → pivote (convergen) */}
      <path d="M126,142 C126,168 205,176 236,188" fill="none" stroke={C.line2} strokeWidth="1.2" markerEnd="url(#rdArrowN)" />
      <path d="M354,142 C354,168 275,176 244,188" fill="none" stroke={C.line2} strokeWidth="1.2" markerEnd="url(#rdArrowN)" />

      {/* ══ PIVOTE ══ */}
      <rect x="150" y="190" width="180" height="46" rx="8" fill={C.panel} stroke={C.line2} strokeWidth="1" />
      <text x="240" y="210" textAnchor="middle" fontFamily={SANS} fontSize="12.5" fontWeight="600" fill={C.ink0}>Misma plata,</text>
      <text x="240" y="226" textAnchor="middle" fontFamily={SANS} fontSize="12.5" fontWeight="600" fill={C.ink0}>dos preguntas</text>

      {/* ══ DIVISOR DE CARRILES ══ */}
      <line x1="240" y1="248" x2="240" y2="616" stroke={C.line2} strokeWidth="1" strokeDasharray="4 4" />
      <rect x="203" y="248" width="74" height="17" rx="4" fill={C.panel} stroke={C.line2} strokeWidth="1" />
      <text x="240" y="260" textAnchor="middle" fontFamily={MONO} fontSize="8" letterSpacing="0.6" fill={C.ink2}>ACÁ SE SEPARAN</text>

      {/* Conectores pivote → carriles (arrancan de las esquinas del pivote → esquivan el pill) */}
      <path d="M180,236 C150,258 126,262 126,283" fill="none" stroke={C.green} strokeWidth="1.2" opacity="0.85" markerEnd="url(#rdArrowG)" />
      <path d="M300,236 C330,258 354,262 354,283" fill="none" stroke={C.sky} strokeWidth="1.2" opacity="0.85" markerEnd="url(#rdArrowS)" />
      <text x="116" y="274" textAnchor="end" fontFamily={SANS} fontSize="8.5" fill={C.ink3}>resta simple</text>
      <text x="364" y="274" textAnchor="start" fontFamily={SANS} fontSize="8.5" fill={C.ink3}>ponderá por tiempo</text>

      {/* Lane chips (centrados sobre cada card) */}
      <rect x="74" y="286" width="104" height="19" rx="6" fill={C.greenFill} stroke={C.green} strokeWidth="1" />
      <text x="126" y="299" textAnchor="middle" fontFamily={MONO} fontSize="9" letterSpacing="0.8" fill={C.green}>PLATA · USD</text>
      <rect x="279" y="286" width="150" height="19" rx="6" fill={C.skyFill} stroke={C.sky} strokeWidth="1" />
      <text x="354" y="299" textAnchor="middle" fontFamily={MONO} fontSize="9" letterSpacing="0.8" fill={C.sky}>RENDIMIENTO · %</text>

      {/* ══ ZONA B-IZQ — CARRIL PLATA·USD ══ */}
      <rect x="28" y="314" width="196" height="150" rx="8" fill={C.greenFill} stroke={C.green} strokeWidth="1" />
      <Badge x={38} y={324} n="2" fill={C.green} />
      <text x="64" y="338" fontFamily={SANS} fontSize="14.5" fontWeight="600" fill={C.ink0}>Ganancia en USD</text>
      <text x="44" y="368" fontFamily={SANS} fontSize="10.5" fill={C.ink2}>el número grande</text>
      <text x="44" y="392" fontFamily={MONO} fontSize="11" fill={C.ink1}>Valor de mercado</text>
      <text x="44" y="408" fontFamily={MONO} fontSize="11" fill={C.green}>− Capital aportado</text>
      <text x="44" y="430" fontFamily={MONO} fontSize="9.5" fill={C.ink2}>= realizado + no realizado</text>
      <line x1="44" y1="440" x2="208" y2="440" stroke={C.line2} strokeWidth="1" />
      <text x="44" y="453" fontFamily={SANS} fontSize="9" fill={C.ink3}>un depósito no es ganancia;</text>
      <text x="44" y="464" fontFamily={SANS} fontSize="9" fill={C.ink3}>un retiro no es pérdida.</text>

      {/* ══ ZONA B-DER — CARRIL RENDIMIENTO·% ══ */}
      {/* B2 · Modified Dietz */}
      <rect x="256" y="314" width="196" height="106" rx="8" fill={C.skyFill} stroke={C.sky} strokeWidth="1" />
      <Badge x={266} y={324} n="3" fill={C.sky} />
      <text x="292" y="338" fontFamily={SANS} fontSize="13.5" fontWeight="600" fill={C.ink0}>Rendimiento del período</text>
      <text x="272" y="358" fontFamily={SANS} fontSize="9.5" fill={C.ink2}>Modified Dietz · estándar de industria</text>
      <text x="272" y="382" fontFamily={MONO} fontSize="10.5" fill={C.ink1}>(fin − ini − flujo)</text>
      <text x="272" y="398" fontFamily={MONO} fontSize="10.5" fill={C.ink1}>÷ (ini + ½·flujo)</text>
      <text x="272" y="413" fontFamily={SANS} fontSize="9" fill={C.ink3}>½ = entró a mitad del período</text>

      {/* Mini-timeline: el % ignora los depósitos */}
      <text x="354" y="438" textAnchor="middle" fontFamily={SANS} fontSize="9" fill={C.sky}>el % ignora cuándo aportaste</text>
      {/* eje */}
      <line x1="266" y1="482" x2="446" y2="482" stroke={C.line2} strokeWidth="1" />
      {[286, 328, 370, 412].map((x, i) => (
        <g key={i} aria-hidden="true">
          <line x1={x} y1="479" x2={x} y2="485" stroke={C.line} strokeWidth="1" />
          <text x={x} y="496" textAnchor="middle" fontFamily={MONO} fontSize="7.5" fill={C.ink3}>{`m${i + 1}`}</text>
        </g>
      ))}
      {/* depósitos = flechas violet ↑ (con ½) */}
      {[300, 352, 400].map((x, i) => (
        <g key={i} aria-hidden="true">
          <line x1={x} y1="482" x2={x} y2="464" stroke={C.violet} strokeWidth="1.4" markerEnd="url(#rdArrowV)" />
          <circle cx={x} cy="459" r="5" fill={C.violetDeep} stroke={C.violet} strokeWidth="1" />
          <text x={x} y="462" textAnchor="middle" fontFamily={MONO} fontSize="7" fill={C.violet}>½</text>
        </g>
      ))}
      {/* la línea del % NO salta con los depósitos */}
      <path d="M266,470 C300,463 336,474 372,466 C404,459 428,468 446,464" fill="none" stroke={C.sky} strokeWidth="1.6" strokeLinecap="round" />

      {/* Conector timeline → B3 */}
      <path d="M354,502 L354,516" fill="none" stroke={C.sky} strokeWidth="1.2" markerEnd="url(#rdArrowS)" />
      <text x="354" y="512" textAnchor="middle" fontFamily={SANS} fontSize="8.5" fill={C.ink3}>encadená los meses (×, no +)</text>

      {/* B3 · Largo plazo (TWR + CAGR) */}
      <rect x="256" y="520" width="196" height="96" rx="8" fill={C.violetDeep} stroke={C.sky} strokeWidth="1" />
      <rect x="256" y="520" width="3" height="96" fill={C.aqua} />
      <Badge x={266} y={530} n="4" fill={C.sky} />
      <text x="292" y="544" fontFamily={SANS} fontSize="13.5" fontWeight="600" fill={C.ink0}>Largo plazo</text>
      <text x="272" y="564" fontFamily={SANS} fontSize="9.5" fill={C.ink2}>TWR encadenado · tasa anual</text>
      <text x="272" y="587" fontFamily={MONO} fontSize="11" fill={C.ink1}>∏ (1+rₙ) − 1</text>
      <text x="272" y="605" fontFamily={MONO} fontSize="10" fill={C.aqua}>CAGR = crec.^(12/m) − 1</text>

      {/* ══ ZONA C — CAPTIONS DE CIERRE ══ */}
      {/* conectores lane → caption */}
      <line x1="126" y1="466" x2="126" y2="648" stroke={C.green} strokeWidth="1" strokeDasharray="3 4" opacity="0.55" />
      <line x1="354" y1="618" x2="354" y2="648" stroke={C.sky} strokeWidth="1" strokeDasharray="3 4" opacity="0.55" />
      <line x1="60" y1="656" x2="192" y2="656" stroke={C.green} strokeWidth="1.5" strokeLinecap="round" />
      <line x1="290" y1="656" x2="418" y2="656" stroke={C.sky} strokeWidth="1.5" strokeLinecap="round" />
      <text x="126" y="676" textAnchor="middle" fontFamily={SANS} fontSize="12" fontWeight="600" fill={C.green}>cuántos dólares ganaste</text>
      <text x="354" y="676" textAnchor="middle" fontFamily={SANS} fontSize="12" fontWeight="600" fill={C.sky}>qué tan bien rindió</text>
      <text x="354" y="690" textAnchor="middle" fontFamily={SANS} fontSize="9.5" fill={C.ink2}>· tasa anual comparable ·</text>

      {/* micro-nota */}
      <text x="240" y="710" textAnchor="middle" fontFamily={MONO} fontSize="8.5" letterSpacing="0.4" fill={C.ink3}>misma cartera — dos números correctos</text>
    </svg>
  )
}
