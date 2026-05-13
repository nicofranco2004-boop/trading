import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Upload, RotateCcw, AlertTriangle, CheckCircle2, Trash2, FileText, ChevronLeft, Loader2, Edit3 } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import Modal from '../components/Modal'
import ImportWizard from '../components/import/ImportWizard'
import { api } from '../utils/api'

export default function Imports() {
  const [batches, setBatches] = useState([])
  const [loading, setLoading] = useState(true)
  const [reverting, setReverting] = useState(null) // batch_id en proceso
  const [redoing, setRedoing] = useState(null)     // batch_id en proceso de redo
  const [confirmRevert, setConfirmRevert] = useState(null) // batch object pendiente de confirmación
  const [confirmRedo, setConfirmRedo] = useState(null)     // batch object pendiente de "rehacer"
  const [redoPreview, setRedoPreview] = useState(null)     // {preview, original_batch_id} → abre wizard
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await api.get('/imports')
      setBatches(data || [])
    } catch (ex) {
      setError(ex.message || 'No pudimos cargar el historial.')
    } finally {
      setLoading(false)
    }
  }

  async function doRevert(batch, { force = false } = {}) {
    setReverting(batch.id)
    setError(null)
    setInfo(null)
    try {
      const url = force
        ? `/imports/${batch.id}/revert?nuclear=1`
        : `/imports/${batch.id}/revert`
      await api.post(url, {})
      setInfo(`Importación del ${fmtDate(batch.created_at)} revertida correctamente.`)
      setConfirmRevert(null)
      await load()
    } catch (ex) {
      // Si el revert safe falló por ventas/conversiones, lo dejamos disponible
      // como "Forzar revert" en el mismo modal (sin cerrarlo).
      const msg = ex.message || 'No se pudo revertir.'
      const isSellFxBlock = /ventas|conversiones|fifo/i.test(msg)
      if (!force && isSellFxBlock) {
        setError(msg + ' Podés forzar el revert desde el botón "Forzar revert".')
      } else {
        setError(msg)
        setConfirmRevert(null)
      }
    } finally {
      setReverting(null)
    }
  }

  async function doRedo(batch) {
    setRedoing(batch.id)
    setError(null)
    setInfo(null)
    try {
      const data = await api.post(`/imports/${batch.id}/redo`, {})
      setRedoPreview({
        preview: data.preview,
        original_batch_id: data.original_batch_id,
      })
      setConfirmRedo(null)
      await load()
    } catch (ex) {
      setError(ex.message || 'No se pudo rehacer la importación.')
      setConfirmRedo(null)
    } finally {
      setRedoing(null)
    }
  }

  const [recalculating, setRecalculating] = useState(false)
  async function doRecalcPnl() {
    setRecalculating(true)
    setError(null)
    setInfo(null)
    try {
      const data = await api.post('/imports/recalc-pnl', {})
      setInfo(`Aggregates mensuales recalculados desde las operaciones e imports confirmados (${data.rows_updated} entradas actualizadas).`)
    } catch (ex) {
      setError(ex.message || 'No pudimos recalcular los aggregates.')
    } finally {
      setRecalculating(false)
    }
  }

  return (
    <div className="page-shell">
      <PageHeader
        title="Importaciones"
        subtitle="Historial de archivos CSV importados. Podés revertir un lote (BUY/aportes) o usar 'Editar y rehacer' para revertir y reabrir el wizard con los mismos datos para ajustar lo que haga falta."
        action={
          <div className="flex items-center gap-2">
            <button
              onClick={doRecalcPnl}
              disabled={recalculating}
              title="Recalcula P&L, deposits y withdrawals mensuales desde las operations e imports confirmados. Útil si el dashboard quedó con drift de cycles import/revert."
              className="inline-flex items-center gap-1.5 text-sm border border-slate-300 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-700/40 text-slate-700 dark:text-slate-200 px-3 py-2 rounded-md font-medium transition disabled:opacity-50"
            >
              {recalculating
                ? <Loader2 size={14} className="animate-spin" />
                : <RotateCcw size={14} />}
              Recalcular aggregates
            </button>
            <Link
              to="/operaciones"
              className="inline-flex items-center gap-1.5 text-sm border border-slate-300 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-700/40 text-slate-700 dark:text-slate-200 px-3 py-2 rounded-md font-medium transition"
            >
              <Upload size={14} /> Nueva importación
            </Link>
          </div>
        }
      />

      {error && (
        <div className="mb-4 flex items-start gap-2 px-3 py-2 rounded-md bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400 text-sm">
          <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {info && (
        <div className="mb-4 flex items-start gap-2 px-3 py-2 rounded-md bg-emerald-500/10 border border-emerald-500/20 text-emerald-700 dark:text-emerald-400 text-sm">
          <CheckCircle2 size={14} className="mt-0.5 flex-shrink-0" />
          <span>{info}</span>
        </div>
      )}

      <Card padding="none">
        {loading ? (
          <div className="p-6 text-center text-ink-3 text-sm" aria-live="polite">Cargando…</div>
        ) : batches.length === 0 ? (
          <EmptyState
            icon={<FileText size={20} />}
            title="Todavía no importaste ningún archivo"
            description="Cuando importes un CSV desde Operaciones, Posiciones o el Dashboard, va a quedar registrado acá para que puedas revisarlo o revertirlo."
            action={
              <Link
                to="/operaciones"
                className="inline-flex items-center gap-1.5 text-sm bg-rendi-accent text-white hover:bg-rendi-accent/90 px-3 py-2 rounded-md font-medium transition"
              >
                <Upload size={14} /> Importar CSV
              </Link>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700/50">
                  <th className="px-4 py-2 text-left text-xs text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wider">Fecha</th>
                  <th className="px-4 py-2 text-left text-xs text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wider">Archivo</th>
                  <th className="px-4 py-2 text-left text-xs text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wider">Broker</th>
                  <th className="px-4 py-2 text-left text-xs text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wider">Filas</th>
                  <th className="px-4 py-2 text-left text-xs text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wider">Estado</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {batches.map(b => (
                  <tr key={b.id} className="border-b border-slate-100 dark:border-slate-700/20">
                    <td className="px-4 py-2 text-sm text-slate-600 dark:text-slate-300 tabular whitespace-nowrap">
                      {fmtDate(b.created_at)}
                    </td>
                    <td className="px-4 py-2 text-sm text-slate-700 dark:text-slate-200 max-w-[260px] truncate" title={b.file_name}>
                      {b.file_name || '—'}
                    </td>
                    <td className="px-4 py-2 text-sm text-slate-600 dark:text-slate-300">{b.broker}</td>
                    <td className="px-4 py-2 text-sm text-slate-600 dark:text-slate-300 tabular">
                      {b.valid_rows} válidas
                      {b.invalid_rows > 0 && <span className="text-amber-600 dark:text-amber-400"> · {b.invalid_rows} con errores</span>}
                    </td>
                    <td className="px-4 py-2">
                      <StatusPill status={b.status} />
                    </td>
                    <td className="px-4 py-2 text-right">
                      {b.status === 'confirmed' && (
                        <div className="inline-flex items-center gap-2">
                          <button
                            onClick={() => setConfirmRedo(b)}
                            disabled={redoing === b.id || reverting === b.id}
                            className="inline-flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300 hover:text-rendi-accent px-2 py-1 rounded transition disabled:opacity-50"
                            title="Revertir y abrir el wizard ya pre-cargado para ajustar y reimportar"
                          >
                            {redoing === b.id ? <Loader2 size={12} className="animate-spin" /> : <Edit3 size={12} />}
                            Editar y rehacer
                          </button>
                          <button
                            onClick={() => setConfirmRevert(b)}
                            disabled={reverting === b.id || redoing === b.id}
                            className="inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400 px-2 py-1 rounded transition disabled:opacity-50"
                            title="Revertir esta importación"
                          >
                            {reverting === b.id ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                            Revertir
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {confirmRedo && (
        <Modal title="Editar y rehacer" onClose={() => setConfirmRedo(null)}>
          <div className="space-y-3 text-sm text-slate-700 dark:text-slate-200">
            <p>Vamos a revertir la importación del <strong>{fmtDate(confirmRedo.created_at)}</strong> ({confirmRedo.file_name || 'sin nombre'}) y abrir el wizard ya pre-cargado con los mismos datos para que ajustes lo que haga falta.</p>
            <p className="text-slate-600 dark:text-slate-300">
              Esto va a:
            </p>
            <ul className="list-disc list-inside text-xs text-slate-600 dark:text-slate-300 space-y-0.5 pl-2">
              <li>Borrar las posiciones, operaciones y movimientos de cash creados por este import.</li>
              <li>Marcar el batch como <em>reverted</em>.</li>
              <li>Abrir el wizard ya en <em>Vista previa</em> con los mismos datos (podés omitir filas, cargar estado inicial, etc.).</li>
              <li>Al confirmar se crea un import <em>nuevo</em> — el original queda en el historial como reverted.</li>
            </ul>
            <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/20 text-xs text-amber-700 dark:text-amber-400">
              <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
              <span>
                Si el batch incluye ventas o conversiones de moneda, la reversa es <strong>best-effort</strong>: recreamos las posiciones consumidas pero el tipo de cambio promedio del cash USD puede tener un drift menor. Al re-importar se sobrescribe.
              </span>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setConfirmRedo(null)}
                className="px-4 py-2 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
              >
                Cancelar
              </button>
              <button
                onClick={() => doRedo(confirmRedo)}
                disabled={redoing === confirmRedo.id}
                className="px-4 py-2 text-sm bg-rendi-accent hover:bg-rendi-accent/90 text-white rounded-md font-semibold transition disabled:opacity-50 inline-flex items-center gap-1.5"
              >
                {redoing === confirmRedo.id && <Loader2 size={12} className="animate-spin" />}
                <Edit3 size={12} />
                Revertir y editar
              </button>
            </div>
          </div>
        </Modal>
      )}

      {redoPreview && (
        <ImportWizard
          initialPreview={redoPreview.preview}
          redoBanner={true}
          onClose={() => { setRedoPreview(null); load() }}
          onConfirmed={() => { setRedoPreview(null); load() }}
        />
      )}

      {confirmRevert && (
        <Modal title="Confirmar reversa" onClose={() => setConfirmRevert(null)}>
          <div className="space-y-3 text-sm text-slate-700 dark:text-slate-200">
            <p>Vas a revertir la importación del <strong>{fmtDate(confirmRevert.created_at)}</strong> ({confirmRevert.file_name || 'sin nombre'}).</p>
            <p className="text-slate-600 dark:text-slate-300">
              Esto va a:
            </p>
            <ul className="list-disc list-inside text-xs text-slate-600 dark:text-slate-300 space-y-0.5 pl-2">
              <li>Borrar las posiciones que se crearon en este import.</li>
              <li>Reversar los movimientos de cash y los entries mensuales correspondientes.</li>
              <li>Marcar el batch como <em>reverted</em> (no se borra del historial).</li>
            </ul>
            <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/20 text-xs text-amber-700 dark:text-amber-400">
              <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
              <span>
                Si este import incluye ventas o conversiones de moneda, la reversa normal va a fallar. Usá <strong>Forzar revert</strong> para revertir todo de una (incluye ventas/conversiones — modo nuclear).
              </span>
            </div>
            {error && (
              <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-red-500/10 border border-red-500/20 text-xs text-red-700 dark:text-red-400">
                <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => { setConfirmRevert(null); setError(null) }}
                className="px-4 py-2 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
              >
                Cancelar
              </button>
              <button
                onClick={() => doRevert(confirmRevert, { force: true })}
                disabled={reverting === confirmRevert.id}
                className="px-4 py-2 text-sm bg-amber-600 hover:bg-amber-700 text-white rounded-md font-semibold transition disabled:opacity-50 inline-flex items-center gap-1.5"
                title="Revierte también ventas y conversiones (modo nuclear)"
              >
                {reverting === confirmRevert.id && <Loader2 size={12} className="animate-spin" />}
                <AlertTriangle size={12} />
                Forzar revert
              </button>
              <button
                onClick={() => doRevert(confirmRevert)}
                disabled={reverting === confirmRevert.id}
                className="px-4 py-2 text-sm bg-red-600 hover:bg-red-700 text-white rounded-md font-semibold transition disabled:opacity-50 inline-flex items-center gap-1.5"
              >
                {reverting === confirmRevert.id && <Loader2 size={12} className="animate-spin" />}
                <Trash2 size={12} />
                Revertir
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}


function StatusPill({ status }) {
  if (status === 'confirmed') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
        <CheckCircle2 size={10} /> Confirmada
      </span>
    )
  }
  if (status === 'reverted') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-slate-500/10 text-slate-600 dark:text-slate-400 border border-slate-500/20">
        <ChevronLeft size={10} /> Revertida
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20">
      {status}
    </span>
  )
}


function fmtDate(s) {
  if (!s) return '—'
  // Soporta tanto "2024-03-15 14:23:00" como ISO "2024-03-15T14:23:00Z"
  try {
    const d = new Date(s.includes('T') ? s : s.replace(' ', 'T') + 'Z')
    return d.toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' })
  } catch {
    return s
  }
}
