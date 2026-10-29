// SeccionFicha — una sección de la ficha del activo: un título grande y una
// línea arriba que separa una de otra, para que se note dónde empieza cada una
// (Nico, 24/10: «separá dentro de la ficha análisis técnico y fundamental»).
// La usan la ficha (técnico, tu operatoria) y AnalyzeView en la ficha
// (fundamental), que decide si aparece: sin empresa no queda un título suelto.
// `accion`: algo a la derecha del título (el link a Análisis fundamental).

export default function SeccionFicha({ titulo, accion = null, children, etiqueta }) {
  return (
    <section aria-label={etiqueta || titulo} className="mt-8 pt-6 border-t border-line">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 mb-4">
        <h2 className="text-lg font-semibold text-ink-0 leading-tight">{titulo}</h2>
        {accion}
      </div>
      {children}
    </section>
  )
}
