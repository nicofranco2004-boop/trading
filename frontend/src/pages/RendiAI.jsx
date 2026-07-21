// RendiAI — página de chat con la IA (/ai).
// ═══════════════════════════════════════════════════════════════════════════
// Reemplaza al drawer lateral (AICoachDrawer): tocar "Rendi AI" en el sidebar
// navega acá. Chat a pantalla completa estilo conversación centrada: topbar con
// la marca + chip de contexto + "Nueva conversación", mensajes con aire, input
// abajo. La lógica del chat (tiers, cuota, streaming, registrar operaciones)
// vive intacta en <AICoach fullHeight> — esta página solo arma el snapshot
// (mismo mecanismo que tenía el drawer) y pone el chrome.
//
// La pregunta inicial (✦ botones / onboarding) llega vía CoachDrawerContext:
// open(question) ahora navega acá y deja la pregunta en el contexto; la
// consumimos una sola vez y AICoach la auto-envía (autoAsk).

import { useEffect, useRef, useState } from 'react'
import { Loader2, AlertCircle, Plus } from 'lucide-react'
import AICoach from '../components/AICoach'
import { useCoachDrawer } from '../contexts/CoachDrawerContext'
import { api } from '../utils/api'
import { clearChatSession } from '../utils/chatSession'

export default function RendiAI() {
  const { initialQuestion, consumeInitialQuestion } = useCoachDrawer()
  const [snapshot, setSnapshot] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const snapshotRef = useRef(null)
  const [refreshTick, setRefreshTick] = useState(0)
  // Remount de AICoach = conversación nueva. La conversación PERSISTE al
  // navegar (sessionStorage, ver utils/chatSession) — por eso acá, además del
  // remount, hay que BORRAR la persistida (sin eso el remount la restaura).
  const [convKey, setConvKey] = useState(0)
  // La pregunta inicial se consume UNA vez (sino un remount la re-enviaría).
  const autoAskRef = useRef(null)
  if (initialQuestion && autoAskRef.current == null) {
    autoAskRef.current = initialQuestion
    consumeInitialQuestion?.()
  }

  // Snapshot vivo de la cartera — mismo criterio que el drawer: primer fetch
  // con loader, refreshes en background sin tirar el chat.
  useEffect(() => {
    let cancelled = false
    if (!snapshotRef.current) setLoading(true)
    setError(null)
    Promise.all([
      api.get('/positions'),
      api.get('/monthly'),
      api.get('/brokers'),
      api.get('/operations').catch(() => []),  // no crítico si falla
    ])
      .then(([positions, monthly, brokers, operations]) => {
        if (cancelled) return
        const opsCapped = Array.isArray(operations) ? operations.slice(0, 100) : []
        const snap = {
          summary: buildSummary(positions, monthly),
          positions: positions || [],
          operations: opsCapped,
          monthly: monthly || [],
          brokers: brokers || [],
        }
        snapshotRef.current = snap
        setSnapshot(snap)
        setLoading(false)
      })
      .catch(err => {
        if (cancelled) return
        if (!snapshotRef.current) setError(err?.message || 'No pudimos cargar el contexto de tu cartera.')
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [refreshTick])

  // El chat registró/deshizo una operación → refrescar snapshot en background.
  useEffect(() => {
    const onPortfolioChanged = () => setRefreshTick(t => t + 1)
    window.addEventListener('rendi:portfolio-changed', onPortfolioChanged)
    return () => window.removeEventListener('rendi:portfolio-changed', onPortfolioChanged)
  }, [])

  const nPos = snapshot?.summary?.open_positions_count
  const nBrokers = snapshot?.brokers?.length

  return (
    <div className="h-dvh flex flex-col pb-16 sm:pb-0">
      {/* Topbar de la página */}
      <div className="flex items-center justify-between gap-3 px-4 sm:px-7 py-3.5 border-b border-line/60 flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-9 h-9 rounded-xl grid place-items-center text-white text-[15px] flex-none"
            style={{ background: 'linear-gradient(135deg, #9d8cff, #4bd0e8)' }}>✦</div>
          <div className="min-w-0">
            <div className="text-[15.5px] font-semibold text-ink-0 leading-tight">Rendi AI</div>
            <div className="text-[12px] text-ink-3 truncate">Conoce tu cartera en tiempo real</div>
          </div>
        </div>
        <div className="flex items-center gap-2.5 flex-shrink-0">
          {snapshot && (
            <span className="hidden md:inline-flex items-center gap-2 text-[12.5px] text-ink-2 bg-bg-1 border border-line rounded-full px-3.5 py-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-rendi-pos" aria-hidden />
              Viendo tu cartera{nPos != null ? ` · ${nPos} posiciones` : ''}{nBrokers ? ` · ${nBrokers} brokers` : ''}
            </span>
          )}
          <button
            type="button"
            onClick={() => { clearChatSession(); setConvKey(k => k + 1) }}
            className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-ink-2 hover:text-ink-0 border border-line hover:border-ink-3 rounded-lg px-3 py-1.5 transition-colors"
          >
            <Plus size={13} strokeWidth={2} aria-hidden="true" /> Nueva conversación
          </button>
        </div>
      </div>

      {/* Cuerpo — conversación centrada */}
      <div className="flex-1 min-h-0 w-full max-w-3xl mx-auto flex flex-col px-2 sm:px-4">
        {loading && (
          <div className="flex items-center gap-2 text-sm text-ink-3 py-16 justify-center">
            <Loader2 size={15} className="animate-spin" aria-hidden="true" />
            Cargando el contexto de tu cartera…
          </div>
        )}

        {error && !loading && (
          <div className="flex items-start gap-2 mx-4 mt-8 px-4 py-3 rounded-xl bg-rendi-neg/[0.08] border border-rendi-neg/25 text-rendi-neg text-sm">
            <AlertCircle size={15} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}

        {snapshot && !loading && !error && (
          <AICoach key={convKey} snapshot={snapshot} autoAsk={autoAskRef.current} fullHeight />
        )}
      </div>
    </div>
  )
}

// ─── Helpers ────────────────────────────────────────────────────────────────
// (Mismo resumen mínimo que armaba el drawer — el modelo deriva el resto.)

function buildSummary(positions, monthly) {
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
