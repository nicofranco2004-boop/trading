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

function PpiLogo({ size = 18 }) {
  // PPI (Portafolio Personal Inversiones): "ppi" en turquesa sobre fondo oscuro.
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect width="24" height="24" rx="4" fill="#0E2A38" />
      <text x="12" y="16" textAnchor="middle" fontFamily="-apple-system,sans-serif" fontWeight="800" fontSize="10" fill="#2FBFB3">ppi</text>
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
    summary: 'Subí dos archivos juntos: el historial de Movimientos (reconstruye tu cartera y tu P&L) + el Estado de Cuenta / Portfolio (completa las posiciones que ya tenías de antes).',
    steps: [
      'Movimientos: entrá a app.cocos.capital, andá a Actividad → Descargar Movimientos y bajá todos los años disponibles (cuantos más, mejor).',
      'Estado de Cuenta: en la WEB de Cocos andá a Portfolio, arriba tocá “Descargar portfolio”, elegí la fecha más reciente y descargá el CSV.',
      'Subí los Movimientos + el Estado de Cuenta, todo junto acá — los acomodamos solos.',
    ],
    parserNote: 'Con tus Movimientos reconstruimos tus posiciones activas, tu P&L y tu efectivo. Como los Movimientos solo cubren el período del export, el Estado de Cuenta (Portfolio) completa las posiciones que ya tenías de antes y ajusta lo que quedó de más (cerrando a costo, sin inventar ganancias). Por seguridad, si tocaría más de la mitad de tu cartera lo frenamos. ¿Ya importaste antes? Subí solo el Estado de Cuenta con el botón “Estado de Cuenta Cocos”.',
  },
  {
    id: 'balanz',
    label: 'Balanz',
    Logo: BalanzLogo,
    summary: 'Subí dos archivos juntos: el export de Movimientos (reconstruye tu historial, tu P&L y tu efectivo) + el Resumen de Cuenta / Posición consolidada (PDF), que fija tus tenencias y tu saldo de HOY exactos.',
    steps: [
      'En Balanz web (no la app) andá a Actividad → Movimientos.',
      'Filtrá el período DESDE EL INICIO DE TU CUENTA hasta hoy y descargá el archivo (Excel .xlsx). ⚠️ Si tomás solo un rango parcial, falta el fondeo y el saldo no cierra.',
      'Resumen de Cuenta: en la WEB de Balanz andá a Actividad → Reportes → Posición consolidada, elegí la fecha de hoy y la moneda PESOS (no dólares — en pesos ya viene también tu saldo en dólares, así lo leemos bien), y descargá el PDF.',
      'Subí el Excel de Movimientos + el PDF del Resumen, todo junto acá — los acomodamos solos.',
    ],
    parserNote: 'Del export de Movimientos reconstruimos tu cartera, tu P&L Y tu efectivo —incluye depósitos, retiros, dólar MEP, cupones, dividendos y comisiones— y clasificamos cada activo (bono, CEDEAR, acción, fondo) automáticamente. El Resumen de Cuenta (Posición consolidada) es la foto de HOY y MANDA: ajusta tus tenencias y tu saldo (pesos y dólares) para que queden exactos, aunque el historial no llegue hasta el inicio. ¿Ya importaste antes? Volvé a importar incluyendo el PDF del Resumen: no duplicamos lo que ya está. Ojo: el export de «Resultados» NO sirve —no trae tus depósitos/retiros—, tiene que ser el de Movimientos.',
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
    summary: 'Subí la Cuenta Corriente (Excel) + la Tenencia valorizada (PDF), todo junto, y armamos tu cartera completa.',
    steps: [
      'Cuenta Corriente: Bull Market → Mi Cuenta → Cuenta Corriente. En la pestaña Pesos poné el rango más amplio, Buscar → Exportar (.xlsx). Si operaste en dólares, repetí con Dólares y Dólares cable.',
      'Tenencia valorizada: en la WEB de Bull Market andá a Mi Cuenta → Otras consultas → Tenencia Valorizada a una Fecha → Acceder. Como no tiene botón de descarga, guardá la página como PDF: Ctrl+P (Windows) o Cmd+P (Mac) → en Destino elegí “Guardar como PDF”.',
      'Subí los Excel + el PDF de la Tenencia, todos juntos acá — los acomodamos solos.',
    ],
    parserNote: 'De la Cuenta Corriente importamos compras, ventas, depósitos, retiros, el interés de cauciones y los dividendos (las conversiones cable↔MEP se omiten). Como la Cuenta Corriente solo cubre el período del export, la Tenencia valorizada (PDF) es tu foto de HOY y MANDA: completa las posiciones que ya tenías de antes y ajusta lo que quedó de más o de menos (cerrando a costo, sin inventar ganancias). Por seguridad, si tocaría más de la mitad de tu cartera lo frenamos. ¿Ya importaste antes sin la Tenencia? Volvé a importar incluyendo el PDF. Si tenés un fondo común (FCI) abierto, cargalo a mano desde Posiciones.',
  },
  {
    id: 'iol',
    label: 'IOL',
    Logo: IolLogo,
    summary: 'Subí dos archivos juntos: el Detalle de Movimientos (reconstruye tu historial y tu efectivo) + el Resumen de Cuenta (PDF), que fija tus tenencias y tu saldo de HOY.',
    steps: [
      'Iniciá sesión en IOL (invertironline.com) desde la WEB.',
      'Movimientos: Mi Cuenta → Movimientos → Detalle de Movimientos, elegí desde que abriste la cuenta hasta hoy y abajo tocá “Descargar movimientos históricos” (.xls).',
      'Resumen de Cuenta: andá a Mi Cuenta → Estado de Cuenta, bajá hasta el final (Detalle de Saldos) y tocá el botón verde para descargar el PDF.',
      'Subí el .xls de Movimientos + el PDF del Resumen, todo junto acá — los acomodamos solos.',
    ],
    parserNote: 'Del Detalle de Movimientos reconstruimos compras, ventas, dividendos, rentas y amortizaciones de bonos, intereses, depósitos/extracciones y suscripciones/rescates de FCI, detectando la moneda y consolidando las patas dólar-MEP/cable (ej. GGALD → GGAL). El Resumen de Cuenta es la foto de HOY y MANDA: completa las posiciones que ya tenías de antes, cierra tu efectivo (pesos y dólares) y ajusta lo que quedó de más o de menos (cerrando a costo, sin inventar ganancias). Por seguridad, si tocaría más de la mitad de tu cartera lo frenamos. ¿Ya importaste antes? Alcanza con volver a subir el Resumen. Las transferencias de títulos entrantes se cargan a mano porque no traen el costo.',
  },
  {
    id: 'ieb',
    label: 'IEB',
    Logo: IebLogo,
    summary: 'Subí dos archivos juntos: el export de "Toda la actividad" (Movimientos) + el "Portafolio" (Excel) — reconstruimos tus operaciones y ajustamos tus posiciones y saldos a la foto de hoy.',
    steps: [
      'Entrá al homebanking web de IEB (hb.iebmas.com.ar) e iniciá sesión. ⚠️ Tiene que ser desde la WEB, no desde la app.',
      'Movimientos: andá a Actividad → Toda la actividad (Movimientos totales). En "Desde" poné la fecha más antigua posible (idealmente desde que abriste la cuenta) y en "Hasta" hoy, y descargá el .xlsx.',
      'Portafolio (tu tenencia de hoy): andá a Portafolio, seleccioná la moneda Pesos y descargá el Excel.',
      'Subí los dos Excel juntos acá, tal cual, sin abrirlos ni convertirlos — los acomodamos solos (el Portafolio completa lo que el historial no alcanza y pone el costo real).',
    ],
    parserNote: 'Importamos compras y ventas (en pesos y en dólares MEP/cable), dividendos, renta y amortización de bonos, comisiones, compra/venta de dólar (MEP) y el interés de tus cauciones. El Portafolio es la foto de HOY y MANDA: completa las posiciones que ya tenías de antes con su costo real (PPP), cierra tu efectivo a la foto y ajusta lo que quedó de más o de menos (cerrando a costo, sin inventar ganancias). Por seguridad, si el ajuste tocaría más de la mitad de tu cartera lo frenamos y sólo completamos. ¿Ya importaste antes? Alcanza con volver a subir el Portafolio. Por ahora, las cauciones y las transferencias de títulos quedan para revisar a mano.',
  },
  {
    id: 'ppi',
    label: 'PPI',
    Logo: PpiLogo,
    summary: 'Subí dos archivos juntos: el export de Movimientos (Excel) + el Estado de Cuenta (Excel) — reconstruimos tu cartera y completamos las posiciones que ya tenías de antes.',
    steps: [
      'Entrá a tu cuenta de PPI desde la WEB (Portfolio Personal). ⚠️ Desde la web, no la app.',
      'Movimientos: andá a Actividad → Todos los movimientos, filtrá desde que abriste la cuenta hasta hoy y tocá Exportar → Excel (.xlsx).',
      'Estado de Cuenta: en la pantalla principal —donde ves tu cartera— tocá Exportar arriba a la derecha y elegí Excel.',
      'Subí los dos Excel juntos acá — los acomodamos solos (el Estado de Cuenta completa lo que el historial no alcanza).',
    ],
    parserNote: 'Importamos compras y ventas (en pesos y en dólares MEP/cable), suscripciones y rescates de FCI, dividendos, renta y amortización de bonos, comisiones y retenciones, depósitos y retiros, y el interés de tus cauciones. Las sub-cuentas en dólares se consolidan en una sola. El Estado de Cuenta es tu foto de HOY y MANDA: completa las posiciones con su costo real, cierra tu efectivo a la foto y ajusta lo que quedó de más o de menos (cerrando a costo, sin inventar ganancias). Por seguridad, si tocaría más de la mitad de tu cartera lo frenamos. ¿Ya importaste antes? Subí solo el Estado de Cuenta con el botón “Estado de Cuenta PPI”. Por ahora, las operaciones de dólar SPOT y las transferencias de títulos entrantes quedan para revisar a mano.',
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
