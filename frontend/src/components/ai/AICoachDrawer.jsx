// Drawer lateral con el Coach IA — accesible desde el sidebar.
//
// Cuando se abre, bundlea las llamadas a /positions, /monthly, /brokers en
// paralelo y construye un snapshot básico. El backend /api/ai/chat espera
// `snapshot` como JSON opaco; con las posiciones, mensuales y brokers el
// modelo tiene contexto suficiente para responder la mayoría de preguntas.
// Los items específicos (drawdown, win rate, etc.) los puede inferir o
// calcular vía tool_use.

import { useEffect, useMemo, useRef, useState } from 'react'
import { X, Loader2, AlertCircle } from 'lucide-react'
import AICoach from '../AICoach'
import { useCoachDrawer } from '../../contexts/CoachDrawerContext'
import { api } from '../../utils/api'

// TTL del cache de snapshot — dentro de la sesión, abrir/cerrar el drawer no
// regenera el snapshot a menos que pasen más de 60s.
const SNAPSHOT_TTL_MS = 60_000

export default function AICoachDrawer() {
  const { isOpen, close } = useCoachDrawer()
  const [snapshot, setSnapshot] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const fetchedAtRef = useRef(0)

  // Cuando abre el drawer, traer data si no hay cache fresco
  useEffect(() => {
    if (!isOpen) return
    const fresh = snapshot && Date.now() - fetchedAtRef.current < SNAPSHOT_TTL_MS
    if (fresh) return

    setLoading(true)
    setError(null)
    Promise.all([
      api.get('/positions'),
      api.get('/monthly'),
      api.get('/brokers'),
      // Audit #3 fix B3: incluir operations al snapshot. Sin esto, el system
      // prompt declara que existen pero llegan undefined → toda la sección
      // anti-confusión open/closed (Ola 2) queda vacía. El bot terminaría
      // invocando get_asset_operations tool por cada pregunta histórica.
      api.get('/operations').catch(() => []),  // no crítico si falla
    ])
      .then(([positions, monthly, brokers, operations]) => {
        // Snapshot — datos crudos, el modelo deriva lo que necesite.
        // Operations capeadas a 100 más recientes para no inflar el snapshot
        // (200KB hard cap del backend; user con 500+ ops cae sin esto).
        const opsCapped = Array.isArray(operations) ? operations.slice(0, 100) : []
        const snap = {
          summary: buildSummary(positions, monthly),
          positions: positions || [],
          operations: opsCapped,
          monthly: monthly || [],
          brokers: brokers || [],
        }
        setSnapshot(snap)
        fetchedAtRef.current = Date.now()
        setLoading(false)
      })
      .catch(err => {
        setError(err?.message || 'No pudimos cargar el contexto del coach.')
        setLoading(false)
      })
  }, [isOpen])

  // Cerrar con ESC
  useEffect(() => {
    if (!isOpen) return
    function onKey(e) { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen, close])

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-label="Coach IA"
    >
      {/* backdrop oscuro — click cierra */}
      <button
        type="button"
        onClick={close}
        aria-label="Cerrar Coach IA"
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
      />

      {/* drawer */}
      <div className="relative h-full w-full sm:w-[520px] bg-bg-1 border-l border-line shadow-2xl flex flex-col animate-[slideIn_0.2s_ease-out]">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-line bg-bg-2/40">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-caps text-data-violet">Coach IA</div>
            <div className="text-sm font-medium text-ink-0">Preguntas con contexto de tu cartera</div>
          </div>
          <button
            onClick={close}
            aria-label="Cerrar"
            className="p-1.5 rounded-sm hover:bg-bg-3 text-ink-3 hover:text-ink-0 transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4">
          {loading && (
            <div className="flex items-center gap-2 text-sm text-ink-3 py-8 justify-center">
              <Loader2 size={14} className="animate-spin" />
              Cargando contexto de la cartera…
            </div>
          )}

          {error && !loading && (
            <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-rendi-neg/[0.08] border border-rendi-neg/25 text-rendi-neg text-sm">
              <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {snapshot && !loading && !error && (
            <AICoach snapshot={snapshot} />
          )}
        </div>
      </div>

      <style>{`
        @keyframes slideIn {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
      `}</style>
    </div>
  )
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function buildSummary(positions, monthly) {
  // Resumen mínimo derivado de los datos crudos. No incluye drawdown ni
  // win rate (el modelo los puede pedir via tools si los necesita).
  const totalInvestedUsd = (positions || [])
    .filter(p => !p.is_cash)
    .reduce((acc, p) => acc + (p.invested || 0), 0)
  const totalPositions = (positions || []).filter(p => !p.is_cash).length
  const totalCashPositions = (positions || []).filter(p => p.is_cash).length

  const monthsCount = (monthly || []).length
  const sumPnlRealized = (monthly || []).reduce((acc, m) => acc + (m.pnl_realized || 0), 0)
  const sumDeposits = (monthly || []).reduce((acc, m) => acc + (m.deposits || 0), 0)
  const sumWithdrawals = (monthly || []).reduce((acc, m) => acc + (m.withdrawals || 0), 0)

  return {
    total_invested_usd: +totalInvestedUsd.toFixed(2),
    open_positions_count: totalPositions,
    cash_lines_count: totalCashPositions,
    months_tracked: monthsCount,
    realized_pnl_usd_lifetime: +sumPnlRealized.toFixed(2),
    deposits_lifetime: +sumDeposits.toFixed(2),
    withdrawals_lifetime: +sumWithdrawals.toFixed(2),
  }
}
