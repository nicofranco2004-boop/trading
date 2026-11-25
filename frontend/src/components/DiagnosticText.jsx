// DiagnosticText — dibuja un hallazgo con `**...**` en negrita.
// Sintaxis simple (no es markdown completo): se parte por `**` y cada tramo
// impar va en <strong>. Es la forma en que escriben sus textos los generadores
// de utils/diagnostics.js. Lo usan Diagnóstico (pages/Insights.jsx) y el resumen
// de «tu cartera» de la bienvenida (pages/Onboarding.jsx).
export default function DiagnosticText({ text }) {
  if (!text) return null
  const parts = text.split('**')
  return (
    <>
      {parts.map((part, i) => (
        i % 2 === 1
          ? <strong key={i} className="font-semibold text-ink-0 dark:text-white">{part}</strong>
          : <span key={i}>{part}</span>
      ))}
    </>
  )
}
