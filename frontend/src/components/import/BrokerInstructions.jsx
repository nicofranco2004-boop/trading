// Widget "Antes de subir / Cómo descargar tus archivos" — mostrado arriba
// del file picker en el wizard de import. Es informativo: no controla el
// parser que se elige abajo, solo le dice al usuario cómo bajar el archivo
// de cada broker. Para Balanz / IOL (sin parser nativo) hay una nota al
// final que los manda al parser Genérico.
//
// Cuando el user pase los ejemplos reales de import, actualizar BROKERS.
import { useState } from 'react'
import { ChevronDown, ChevronUp, BookOpen, RefreshCw } from 'lucide-react'

// Logos inline — un SVG simple por broker. Reemplazar con assets reales si
// se quiere, pero esto evita un network request más.
function CocosLogo({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect width="24" height="24" rx="5" fill="#FFFFFF" />
      <path d="M16.5 8.5c-1.3-1.6-3.3-2.5-5.4-2.3-3.5.3-6.1 3.3-5.8 6.8.3 3.4 3.2 6 6.7 5.8 2.1-.2 3.9-1.4 5-3"
        stroke="#1F3CFE" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  )
}

function BalanzLogo({ size = 18 }) {
  // Balanz brand: B en mayúscula sobre azul marino. Probamos "BALANZ"
  // completo pero a este tamaño se cortaba — más limpio quedarse con la
  // inicial.
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect width="24" height="24" rx="4" fill="#1F2C8C" />
      <text x="12" y="18" textAnchor="middle" fontFamily="-apple-system,sans-serif" fontWeight="800" fontSize="16" fill="#FFFFFF">B</text>
    </svg>
  )
}

function BinanceLogo({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="#F0B90B" aria-hidden="true">
      <path d="M12 2L8.5 5.5l2 2L12 6l1.5 1.5 2-2L12 2zm-7 7l-2 2 3.5 3.5L4 18l2 2 3.5-3.5L13 20l2-2-3.5-3.5L15 11l-2-2-3.5 3.5L6 9l-1 0zm14 0l-3.5 3.5L19 16l-2 2-3.5-3.5L17 11l2-2zM12 14l-1.5 1.5 2 2L12 18l1.5-1.5 2-2L12 14z"/>
    </svg>
  )
}

function IolLogo({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect width="24" height="24" rx="4" fill="#0E5C8A" />
      <text x="12" y="15" textAnchor="middle" fontFamily="-apple-system,sans-serif" fontWeight="800" fontSize="8" fill="#FFFFFF">IOL</text>
    </svg>
  )
}

// Diccionario broker → contenido. El user va a actualizar `steps` y `summary`
// cuando mande los ejemplos reales.
const BROKERS = [
  {
    id: 'cocos',
    label: 'Cocos',
    Logo: CocosLogo,
    summary: 'Necesitás el portfolio actual y el historial anual de movimientos.',
    steps: [
      'Portfolio → Descargar Portfolio.',
      'Actividad → Descargar Movimientos → descargá todos los archivos anuales disponibles.',
      'Subí el portfolio actual junto con esos movimientos.',
    ],
    parserNote: null,
  },
  {
    id: 'balanz',
    label: 'Balanz',
    Logo: BalanzLogo,
    summary: 'La carga inicial sale de un rango amplio de movimientos.',
    steps: [
      'Actividad → Movimientos.',
      'Filtrá el período desde el inicio de tu cuenta hasta hoy.',
      'Descargá el archivo y subilo acá.',
    ],
    parserNote: 'Balanz todavía no tiene parser dedicado — subí el archivo y mapealo en el paso siguiente con el parser Genérico.',
  },
  {
    id: 'binance',
    label: 'Binance',
    Logo: BinanceLogo,
    summary: 'Usamos el Historial de transacciones completo para reconstruir cripto y caja stable.',
    steps: [
      'Wallet → Transaction History.',
      'Exportá el historial completo para la carga inicial.',
      'Después exportá mes a mes los movimientos nuevos; si repetís el completo, Rendi deduplica.',
    ],
    parserNote: null,
  },
  {
    id: 'iol',
    label: 'IOL',
    Logo: IolLogo,
    summary: 'Usamos el Excel de Movimientos Históricos para reconstruir movimientos y transferencias.',
    steps: [
      'Mi cuenta → Movimientos → Detalle de Movimientos.',
      'Seleccioná el rango de fechas completo desde el inicio de tu cuenta hasta hoy.',
      'Hacé clic en Descargar movimientos históricos y guardá el Excel como CSV (Archivo → Guardar como → CSV UTF-8).',
    ],
    parserNote: 'IOL todavía no tiene parser dedicado — convertí el Excel a CSV y mapealo en el paso siguiente con el parser Genérico.',
  },
]

export default function BrokerInstructions({ defaultBrokerId = 'cocos' }) {
  const [open, setOpen] = useState(true)
  const [selectedId, setSelectedId] = useState(defaultBrokerId)
  const selected = BROKERS.find(b => b.id === selectedId) || BROKERS[0]
  const SelectedLogo = selected.Logo

  return (
    <div className="rounded-md border border-line bg-bg-1/40 overflow-hidden">
      {/* Header colapsable */}
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-bg-2/40 transition-colors"
        aria-expanded={open}
      >
        <div className="flex items-center gap-2 min-w-0">
          <BookOpen size={14} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" />
          <div className="text-left min-w-0">
            <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3">Antes de subir</div>
            <div className="text-sm font-medium text-ink-0 truncate">Cómo descargar tus archivos</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="hidden sm:inline-flex items-center gap-1 text-[10px] font-mono uppercase tracking-caps text-ink-3 border border-line/60 rounded-sm px-2 py-0.5">
            Cocos · Balanz · Binance · IOL
          </span>
          {open
            ? <ChevronUp size={14} strokeWidth={1.75} className="text-ink-3" />
            : <ChevronDown size={14} strokeWidth={1.75} className="text-ink-3" />}
        </div>
      </button>

      {open && (
        <div className="border-t border-line/50">
          {/* Chips de broker */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-3">
            {BROKERS.map(b => {
              const Logo = b.Logo
              const active = b.id === selectedId
              return (
                <button
                  key={b.id}
                  type="button"
                  onClick={() => setSelectedId(b.id)}
                  className={`inline-flex items-center gap-2 px-3 py-2 rounded-md border transition-all text-left ${
                    active
                      ? 'border-data-violet/60 bg-data-violet/10 text-data-violet'
                      : 'border-line bg-bg-2/40 hover:border-line-3 text-ink-1'
                  }`}
                >
                  <Logo size={20} />
                  <span className="text-sm font-medium truncate">{b.label}</span>
                </button>
              )
            })}
          </div>

          {/* Pasos del broker seleccionado */}
          <div className="mx-3 mb-3 rounded-md border border-data-violet/30 bg-data-violet/[0.04] p-3">
            <div className="flex items-start gap-3">
              <div className="flex-shrink-0 mt-0.5">
                <SelectedLogo size={28} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-ink-0">{selected.label}</div>
                <div className="text-xs text-ink-3 mt-0.5">{selected.summary}</div>
              </div>
            </div>
            <ol className="mt-3 space-y-2">
              {selected.steps.map((step, i) => (
                <li key={i} className="flex items-start gap-2.5">
                  <span className="flex-shrink-0 w-5 h-5 rounded-full border border-data-violet/40 bg-data-violet/10 text-data-violet text-[10px] font-mono font-semibold flex items-center justify-center">
                    {i + 1}
                  </span>
                  <span className="text-sm text-ink-1 leading-relaxed">{step}</span>
                </li>
              ))}
            </ol>
            {selected.parserNote && (
              <div className="mt-3 text-[11px] text-ink-3 italic border-t border-line/40 pt-2">
                {selected.parserNote}
              </div>
            )}
          </div>

          {/* Footer: mantenimiento mensual */}
          <div className="mx-3 mb-3 rounded-md border border-rendi-pos/25 bg-rendi-pos/[0.04] p-3 flex items-start gap-2.5">
            <RefreshCw size={14} strokeWidth={1.75} className="text-rendi-pos flex-shrink-0 mt-0.5" />
            <div className="min-w-0">
              <div className="text-sm font-medium text-ink-0">Mantenimiento mensual</div>
              <div className="text-xs text-ink-3 mt-0.5 leading-relaxed">
                Después de la carga inicial, descargá mes a mes los movimientos nuevos de cada broker y subilos como actualización.
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
