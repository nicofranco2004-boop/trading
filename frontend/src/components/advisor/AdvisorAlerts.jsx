// AdvisorAlerts — las alertas del LIBRO, una card por tipo.
// ═══════════════════════════════════════════════════════════════════════════
// El asesor no trackea una cartera propia, así que sus alertas no son de
// activos: son de su libro. Cada tipo vive en su propia card (pedido de Nico)
// y abajo el historial de lo que se disparó, que se renueva solo a los 3 días.
import { useCallback, useEffect, useState } from 'react'
import { History } from 'lucide-react'
import Panel from '../Panel'
import Skeleton from '../Skeleton'
import BriefPrefs from './BriefPrefs'
import ClientMoveAlert from './ClientMoveAlert'
import { api } from '../../utils/api'

function fmtWhen(iso) {
  if (!iso) return ''
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 16).replace('T', ' ')
  return d.toLocaleString('es-AR', { day: '2-digit', month: '2-digit',
                                     hour: '2-digit', minute: '2-digit' })
}

export default function AdvisorAlerts() {
  const [data, setData] = useState(null)   // {config, history, history_days}
  const [error, setError] = useState(false)

  const load = useCallback(() => {
    api.get('/advisor/alerts')
      .then(d => { setData(d); setError(false) })
      .catch(() => setError(true))
  }, [])
  useEffect(() => { load() }, [load])

  const hist = data?.history || []
  const days = data?.history_days ?? 3

  return (
    <div className="space-y-4">
      {/* 1. El brief diario (dos entregas atadas al mercado) */}
      <BriefPrefs />

      {/* 2. Movimiento fuerte en la cartera de un cliente */}
      {data === null && !error ? (
        <Panel><Skeleton className="h-28" /></Panel>
      ) : error ? (
        <Panel>
          <p className="text-xs text-ink-3 text-center py-4">
            No pudimos cargar tu alerta de movimiento.{' '}
            <button type="button" onClick={load} className="text-rendi-accent hover:underline">
              Reintentar
            </button>
          </p>
        </Panel>
      ) : (
        <ClientMoveAlert
          config={data?.config}
          onSaved={(cfg) => setData(d => ({ ...(d || {}), config: cfg }))}
        />
      )}

      {/* 3. Historial — se limpia solo */}
      <Panel padding="none">
        <header className="px-4 py-3 border-b border-line flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <History size={16} strokeWidth={1.75} className="text-ink-3" aria-hidden="true" />
            <div>
              <h2 className="text-sm font-medium text-ink-0">Historial de avisos</h2>
              <p className="text-xs text-ink-3 mt-0.5">
                Lo que te avisamos en los últimos {days} días — después se limpia solo
              </p>
            </div>
          </div>
          {hist.length > 0 && (
            <span className="text-[11px] text-ink-3 flex-shrink-0">{hist.length}</span>
          )}
        </header>
        {error ? (
          <div className="px-4 py-6 text-center">
            <p className="text-xs text-ink-3">No pudimos cargar el historial.</p>
            <button type="button" onClick={load} className="text-xs text-rendi-accent hover:underline mt-1">
              Reintentar
            </button>
          </div>
        ) : hist.length === 0 ? (
          <p className="px-4 py-6 text-center text-xs text-ink-3">
            Todavía no te avisamos nada. Cuando salte una alerta, va a aparecer acá.
          </p>
        ) : (
          <div>
            {hist.map(ev => (
              <div key={ev.id} className="flex items-center gap-3 px-4 py-2.5 border-t border-line/30">
                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                  (ev.pct ?? 0) >= 0 ? 'bg-rendi-pos' : 'bg-rendi-neg'}`} aria-hidden="true" />
                <span className="text-xs text-ink-1 flex-1 min-w-0 truncate">{ev.message}</span>
                <span className="text-[10px] text-ink-3 flex-shrink-0">{fmtWhen(ev.fired_at)}</span>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  )
}
