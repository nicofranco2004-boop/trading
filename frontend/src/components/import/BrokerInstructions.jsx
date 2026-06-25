// Widget "Antes de subir / Cómo descargar tus archivos" — mostrado arriba
// del file picker en el wizard de import. Es informativo: no controla el
// parser que se elige abajo, solo le dice al usuario cómo bajar el archivo
// de cada broker. Cada broker tiene su parserNote describiendo qué se importa.
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

function SchwabLogo({ size = 18 }) {
  // Charles Schwab brand: celeste sobre fondo azul marino.
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect width="24" height="24" rx="4" fill="#00A0DF" />
      <text x="12" y="16" textAnchor="middle" fontFamily="-apple-system,sans-serif" fontWeight="800" fontSize="11" fill="#FFFFFF">S</text>
    </svg>
  )
}

function BullMarketLogo({ size = 18 }) {
  // Bull Market Brokers: verde sobre fondo oscuro.
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect width="24" height="24" rx="4" fill="#0E1A2B" />
      <text x="12" y="16" textAnchor="middle" fontFamily="-apple-system,sans-serif" fontWeight="800" fontSize="11" fill="#22C55E">BM</text>
    </svg>
  )
}

function IebLogo({ size = 18 }) {
  // IEB (Invertir en Bolsa): índigo sobre fondo oscuro.
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect width="24" height="24" rx="4" fill="#2D2A6E" />
      <text x="12" y="16" textAnchor="middle" fontFamily="-apple-system,sans-serif" fontWeight="800" fontSize="9" fill="#FFFFFF">IEB</text>
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
    summary: 'Usamos tu historial de Movimientos para reconstruir tu cartera y tu P&L.',
    steps: [
      'Entrá a app.cocos.capital e iniciá sesión.',
      'Andá a Actividad → Descargar Movimientos.',
      'Descargá los movimientos de todos los años disponibles (cuantos más, mejor).',
      'Subí ese (o esos) archivo(s) acá.',
    ],
    parserNote: 'Con tus movimientos completos reconstruimos solas tus posiciones activas. Si faltara historial viejo, te pedimos confirmar cuánto efectivo (cash sin invertir) tenés hoy en la cuenta en el paso siguiente — es rápido.',
  },
  {
    id: 'balanz',
    label: 'Balanz',
    Logo: BalanzLogo,
    summary: 'Recomendado: el reporte "Resultados del período" en informe "Completo" — un Excel con todo (posiciones, P&L y renta).',
    steps: [
      'En Balanz (web o app), en el menú de la izquierda tocá "Reportes" → se abre "Descargar Reportes".',
      'En "Reporte" elegí "Resultados del período".',
      'En "Informe" elegí "Completo". ⚠️ Importante: NO elijas "Realizado" — ese viene sin precios y no sirve.',
      'En "Período" poné desde lo más antiguo posible hasta hoy.',
      'Tocá "Descargar" (baja un Excel .xlsx con 3 hojas) y subílo acá.',
    ],
    parserNote: 'Del Excel de Resultados reconstruimos tus posiciones abiertas, las operaciones cerradas (con su P&L) y la renta —cupones, dividendos e intereses— además de las comisiones. Clasificamos cada activo (bono, CEDEAR, acción, fondo) automáticamente. Por ahora NO tomamos los movimientos de caja (depósitos/retiros) ni las compras de dólar MEP — si necesitás ajustar el saldo, lo cargás a mano en el paso siguiente.',
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
    id: 'schwab',
    label: 'Charles Schwab',
    Logo: SchwabLogo,
    summary: 'Usamos el export de History (transacciones) en formato CSV.',
    steps: [
      'Entrá a schwab.com → Accounts → History (Historial).',
      'Elegí la cuenta y el rango de fechas (lo más amplio posible: desde que abriste la cuenta hasta hoy).',
      'Hacé clic en el ícono de export (arriba a la derecha de la tabla) y elegí CSV.',
      'Subí ese CSV acá. Si tenés varias cuentas, exportá una por una.',
    ],
    parserNote: 'Schwab exporta en USD — Rendi crea el broker en dólares automáticamente.',
  },
  {
    id: 'bullmarket',
    label: 'Bull Market',
    Logo: BullMarketLogo,
    summary: 'Usamos el export de Cuenta Corriente. Bull Market lo baja en Excel.',
    steps: [
      'Entrá a Bull Market → Mi Cuenta → Cuenta Corriente.',
      'En la pestaña Pesos, poné el rango más amplio, Buscar → Exportar (.xlsx).',
      'Si operaste en dólares, repetí con las pestañas Dólares y Dólares cable.',
      'Subí los Excel acá — podés subir varios juntos y los acomodamos solos (pesos y dólares).',
    ],
    parserNote: 'Importamos compras, ventas, depósitos, retiros, el interés de tus cauciones y los dividendos en dólares. Las conversiones internas cable↔MEP se omiten. Si tenés un fondo común (FCI) abierto hoy, cargalo manualmente desde Posiciones.',
  },
  {
    id: 'iol',
    label: 'IOL',
    Logo: IolLogo,
    summary: 'Usamos el export de Detalle de Movimientos para reconstruir tus operaciones y movimientos de dinero.',
    steps: [
      'Iniciá sesión en IOL (invertironline.com o la app).',
      'Andá a Mi Cuenta → Movimientos → Detalle de Movimientos.',
      'Elegí la fecha de inicio (desde que abriste la cuenta) y la fecha de hoy.',
      'Abajo de todo tocá “Descargar movimientos históricos”: baja un archivo .xls. Subílo acá tal cual, sin abrirlo ni convertirlo.',
    ],
    parserNote: 'Importamos compras, ventas, dividendos, rentas y amortizaciones de bonos, intereses de cuenta, depósitos y extracciones, y suscripciones/rescates de FCI. Detectamos la moneda (pesos/dólares) de cada movimiento y consolidamos las patas dólar-MEP/cable (ej. GGALD → GGAL). Las transferencias de títulos se cargan a mano porque no traen el costo.',
  },
  {
    id: 'ieb',
    label: 'IEB',
    Logo: IebLogo,
    summary: 'Usamos el export de "Toda la actividad" (Movimientos totales) para reconstruir tus operaciones, dividendos, renta y caja.',
    steps: [
      'Entrá al homebanking web de IEB (hb.iebmas.com.ar) e iniciá sesión. ⚠️ Tiene que ser desde la WEB, no desde la app.',
      'Andá a Actividad → Toda la actividad (Movimientos totales).',
      'En "Desde" poné la fecha más antigua posible (idealmente desde que abriste la cuenta) y en "Hasta" la fecha de hoy.',
      'Descargá el archivo (.xlsx) y subílo acá tal cual, sin abrirlo ni convertirlo.',
    ],
    parserNote: 'Importamos compras y ventas (en pesos y en dólares), dividendos, renta y amortización de bonos, comisiones, compra/venta de dólar (MEP) y el interés de tus cauciones. Detectamos la moneda de cada operación. Si el export no llega hasta el inicio de tu cuenta, te pedimos confirmar tu saldo/tenencia inicial en el paso siguiente. Los fondos comunes (FCI) abiertos hoy, por ahora, cargalos a mano desde Posiciones.',
  },
]

// lockBrokerId: si viene, el widget queda fijo a ese broker (sin chips ni
// selector) — lo usa el Paso 0 del wizard, donde el broker ya fue elegido.
export default function BrokerInstructions({ defaultBrokerId = 'cocos', lockBrokerId = null }) {
  const [open, setOpen] = useState(true)
  const [selectedId, setSelectedId] = useState(lockBrokerId || defaultBrokerId)
  const locked = !!lockBrokerId
  const effectiveId = lockBrokerId || selectedId
  const selected = BROKERS.find(b => b.id === effectiveId) || BROKERS[0]
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
            <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2">Antes de subir</div>
            <div className="text-sm font-medium text-ink-0 truncate">Cómo descargar tus archivos</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {!locked && (
            <span className="hidden sm:inline-flex items-center gap-1 text-[11px] font-mono uppercase tracking-caps text-ink-2 border border-line/60 rounded-sm px-2 py-0.5">
              Cocos · Balanz · Binance · IOL
            </span>
          )}
          {open
            ? <ChevronUp size={14} strokeWidth={1.75} className="text-ink-3" />
            : <ChevronDown size={14} strokeWidth={1.75} className="text-ink-3" />}
        </div>
      </button>

      {open && (
        <div className="border-t border-line/50">
          {/* Chips de broker — ocultos cuando el broker ya viene fijado (Paso 0) */}
          {!locked && (
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
          )}

          {/* Pasos del broker seleccionado */}
          <div className={`mx-3 mb-3 ${locked ? 'mt-3' : ''} rounded-md border border-data-violet/30 bg-data-violet/[0.04] p-3`}>
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

          {/* Footer: 2 opciones de mantenimiento post carga inicial.
              Antes decía solo "descargá mes a mes el CSV" — pero el user
              también puede ir cargando manual cada compra/venta cuando
              ocurre, desde Posiciones. Las dos opciones son válidas y
              vale aclarar ambas para que el user elija la que más le
              cuadra. */}
          <div className="mx-3 mb-3 rounded-md border border-rendi-pos/25 bg-rendi-pos/[0.04] p-3">
            <div className="flex items-start gap-2.5 mb-2">
              <RefreshCw size={14} strokeWidth={1.75} className="text-rendi-pos flex-shrink-0 mt-0.5" />
              <div className="min-w-0">
                <div className="text-sm font-medium text-ink-0">Mantenimiento después de la carga inicial</div>
                <div className="text-xs text-ink-3 mt-0.5 leading-relaxed">
                  Tenés dos formas de mantener Rendi actualizado. Podés usar la que más te convenga:
                </div>
              </div>
            </div>

            {/* Opción 1: manual */}
            <div className="mt-2.5 pl-[26px] text-xs text-ink-2 leading-relaxed">
              <div className="font-medium text-ink-1 mb-0.5">Opción 1 — Manual (recomendado si operás poco)</div>
              <div className="text-ink-3">
                Cada vez que hagas una compra o venta, usá los botones <span className="text-ink-1">"Registrar compra"</span> y <span className="text-ink-1">"Registrar venta"</span> arriba de Posiciones. Tu cartera queda actualizada en el momento.
              </div>
            </div>

            {/* Opción 2: CSV mensual */}
            <div className="mt-2 pl-[26px] text-xs text-ink-2 leading-relaxed">
              <div className="font-medium text-ink-1 mb-0.5">Opción 2 — CSV mensual (recomendado si operás mucho)</div>
              <div className="text-ink-3">
                Una vez por mes, descargá el archivo de movimientos nuevo de tu broker (CSV o Excel, según el broker) y subilo acá. Rendi suma lo nuevo sin duplicar.
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
