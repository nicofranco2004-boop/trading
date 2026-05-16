// AISkeleton — shimmer mientras se genera el análisis.
// ═══════════════════════════════════════════════════════════════════════════
// 3 bloques que aproximan la forma del AnalysisCard: TLDR grande +
// 2 secciones con eyebrow + body. Cuando cae el resultado real, fade-in.

export default function AISkeleton() {
  return (
    <div className="space-y-5 animate-pulse">
      {/* TLDR */}
      <div className="space-y-1.5">
        <div className="h-4 bg-bg-2 rounded-sm w-11/12" />
        <div className="h-4 bg-bg-2 rounded-sm w-7/12" />
      </div>
      {/* 2 sections */}
      {[0, 1].map(i => (
        <div key={i} className="space-y-1.5">
          <div className="h-2.5 bg-bg-2 rounded-sm w-24" />
          <div className="h-3 bg-bg-2 rounded-sm w-full" />
          <div className="h-3 bg-bg-2 rounded-sm w-10/12" />
          <div className="h-3 bg-bg-2 rounded-sm w-6/12" />
        </div>
      ))}
      {/* chips */}
      <div className="pt-3 border-t border-line/40 flex gap-1.5">
        <div className="h-6 w-32 bg-bg-2 rounded-sm" />
        <div className="h-6 w-28 bg-bg-2 rounded-sm" />
      </div>
    </div>
  )
}
