import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Upload, RotateCcw, AlertTriangle, CheckCircle2, Trash2, ChevronLeft, Loader2, Edit3 } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import Pill from '../components/Pill'
import EmptyState from '../components/EmptyState'
import Modal from '../components/Modal'
import ImportWizard from '../components/import/ImportWizard'
import TenenciaUpload from '../components/import/TenenciaUpload'
import { api } from '../utils/api'

// Flag de localStorage: si el user nunca completó un import → al confirmar
// el primero lo redirigimos a /bienvenida para el "primer insight" en lugar
// de devolverlo a la tabla administrativa.
const FIRST_IMPORT_FLAG = 'rendi_first_import_done'

export default function Imports() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const fromOnboarding = searchParams.get('from') === 'onboarding'
  const [batches, setBatches] = useState([])
  const [loading, setLoading] = useState(true)
  const [reverting, setReverting] = useState(null) // batch_id en proceso
  const [redoing, setRedoing] = useState(null)     // batch_id en proceso de redo
  const [confirmRevert, setConfirmRevert] = useState(null) // batch object pendiente de confirmación
  const [confirmRedo, setConfirmRedo] = useState(null)     // batch object pendiente de "rehacer"
  const [redoPreview, setRedoPreview] = useState(null)     // {preview, original_batch_id} → abre wizard
  const [showWizard, setShowWizard] = useState(false)      // wizard de import nuevo (no redo)
  const [showPpiEstado, setShowPpiEstado] = useState(false)  // modal "completar con Estado de Cuenta" (PPI Excel)
  const [importJustConfirmed, setImportJustConfirmed] = useState(false)  // marca interna: el wizard pasó por onConfirmed
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)

  useEffect(() => { load() }, [])

  // Si el user viene del onboarding (?from=onboarding) abrimos el wizard
  // automáticamente — un paso menos para ver su P&L real.
  useEffect(() => {
    if (fromOnboarding) setShowWizard(true)
  }, [fromOnboarding])

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
      window.dispatchEvent(new Event('rendi:portfolio-changed'))
      setInfo(force
        ? 'Import revertido en modo forzado. Revisá tu cartera: las posiciones que ventas del lote consumieron no se recrean automáticamente.'
        : `Importación del ${fmtDate(batch.created_at)} revertida correctamente.`)
      setConfirmRevert(null)
      await load()
    } catch (ex) {
      const msg = ex.message || 'No se pudo revertir.'
      // Errores terminales donde forzar tampoco ayuda → cerramos el modal.
      const terminal = /no encontrado|confirmad/i.test(msg)
      if (force || terminal) {
        setError(msg)
        setConfirmRevert(null)
      } else {
        // Cualquier OTRO fallo del revert safe (ventas, conversiones, o una
        // posición "vendida después del import") mantiene el modal abierto y
        // ofrece "Forzar revert". Antes el regex /ventas|conversiones|fifo/ no
        // matcheaba "vendida" → el modal se cerraba y el usuario quedaba sin
        // forma de borrar el import: los datos quedaban cargados (F1).
        setError(msg + ' Si querés borrarlo igual, usá "Forzar revert".')
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
      window.dispatchEvent(new Event('rendi:portfolio-changed'))
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
      window.dispatchEvent(new Event('rendi:portfolio-changed'))
      setInfo(`Aggregates mensuales recalculados desde las operaciones e imports confirmados (${data.rows_updated} entradas actualizadas).`)
    } catch (ex) {
      setError(ex.message || 'No pudimos recalcular los aggregates.')
    } finally {
      setRecalculating(false)
    }
  }

  const [wiping, setWiping] = useState(false)
  const [wipeOpen, setWipeOpen] = useState(false)        // modal abierto
  const [wipeBrokers, setWipeBrokers] = useState([])     // brokers cargados del user
  const [wipeSel, setWipeSel] = useState(null)           // broker seleccionado

  // Abre el modal: trae la lista de brokers del user para que SELECCIONE
  // (antes había que escribir el nombre a mano en un prompt nativo).
  async function openWipe() {
    setError(null); setInfo(null); setWipeSel(null)
    try {
      const data = await api.get('/brokers')
      setWipeBrokers(data || [])
    } catch {
      setWipeBrokers([])
    }
    setWipeOpen(true)
  }

  async function confirmWipe() {
    if (!wipeSel) return
    setWiping(true); setError(null); setInfo(null)
    try {
      const data = await api.post(`/imports/wipe-broker?broker=${encodeURIComponent(wipeSel)}`, {})
      window.dispatchEvent(new Event('rendi:portfolio-changed'))
      setInfo(`Listo: eliminamos "${wipeSel}" y todos sus datos (${data.positions_deleted} posiciones, ${data.operations_deleted} operaciones). Si volvés a importarlo, se crea de nuevo limpio.`)
      setWipeOpen(false); setWipeSel(null)
      await load()
    } catch (ex) {
      setError(ex.message || 'No se pudo limpiar el broker.')
    } finally {
      setWiping(false)
    }
  }

  // Primer uso = sin historial de imports. Cambia el header a modo "bienvenida"
  // y esconde los botones avanzados/admin para no parecer un panel técnico.
  const isFirstUse = !loading && batches.length === 0

  return (
    <div className="page-shell">
      <PageHeader
        eyebrow={isFirstUse ? undefined : "Importaciones / CSV"}
        title={isFirstUse ? "Importá tu cartera" : "Histórico de lotes"}
        subtitle={isFirstUse ? "Subí el CSV de tu broker y en un minuto ves tu P&L real en dólares." : undefined}
        action={
          <div className="flex items-center gap-2">
            {!isFirstUse && (
              <button
                onClick={doRecalcPnl}
                disabled={recalculating}
                title="Recalcula P&L, deposits y withdrawals mensuales desde las operations e imports confirmados. Útil si el dashboard quedó con drift de cycles import/revert."
                className="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-caps border border-line bg-bg-2 hover:bg-bg-3 text-ink-2 hover:text-ink-0 px-2.5 py-1.5 rounded-sm transition-colors disabled:opacity-50"
              >
                {recalculating
                  ? <Loader2 size={12} strokeWidth={1.75} className="animate-spin" />
                  : <RotateCcw size={12} strokeWidth={1.75} />}
                Recalcular aggregates
              </button>
            )}
            {!isFirstUse && (
              <button
                onClick={openWipe}
                disabled={wiping}
                title="Borra TODOS los datos de un broker (posiciones, operaciones y movimientos), incluyendo cualquier resto de imports viejos. Después podés volver a importar limpio."
                className="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-caps border border-rendi-neg/30 bg-rendi-neg/[0.08] hover:bg-rendi-neg/15 text-rendi-neg px-2.5 py-1.5 rounded-sm transition-colors disabled:opacity-50"
              >
                {wiping
                  ? <Loader2 size={12} strokeWidth={1.75} className="animate-spin" />
                  : <Trash2 size={12} strokeWidth={1.75} />}
                Limpiar broker
              </button>
            )}
            {!isFirstUse && (
              <button
                onClick={() => setShowPpiEstado(true)}
                title="Completá tu cartera de PPI subiendo el Estado de Cuenta (Excel). Agrega las posiciones que los Movimientos no reconstruyen, sin duplicar."
                className="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-caps border border-line bg-bg-2 hover:bg-bg-3 text-ink-2 hover:text-ink-0 px-2.5 py-1.5 rounded-sm transition-colors"
              >
                <Upload size={12} strokeWidth={1.75} /> Estado de Cuenta PPI
              </button>
            )}
            <button
              onClick={() => setShowWizard(true)}
              className="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-caps bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 px-2.5 py-1.5 rounded-sm transition-colors"
            >
              <Upload size={12} strokeWidth={2} /> Nueva importación
            </button>
          </div>
        }
      />

      {error && (
        <div className="mb-4 flex items-start gap-2 px-3 py-2 rounded-md bg-rendi-neg/[0.08] border border-rendi-neg/25 text-rendi-neg text-sm">
          <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {info && (
        <div className="mb-4 flex items-start gap-2 px-3 py-2 rounded-md bg-rendi-pos/[0.08] border border-rendi-pos/25 text-rendi-pos text-sm">
          <CheckCircle2 size={14} className="mt-0.5 flex-shrink-0" />
          <span>{info}</span>
        </div>
      )}

      <Panel padding="none">
        {loading ? (
          <div className="p-6 text-center text-ink-3 text-sm" aria-live="polite">Cargando…</div>
        ) : batches.length === 0 ? (
          <EmptyState
            icon={<Upload size={20} />}
            title="Subí tu primer CSV"
            description="Exportá el CSV de tu broker (Cocos, Binance, Schwab o el template genérico) y en un minuto ves tu P&L real en dólares."
            action={
              <button
                onClick={() => setShowWizard(true)}
                className="inline-flex items-center gap-1.5 text-sm bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 font-mono uppercase tracking-caps text-[11px] px-3 py-2 rounded-md font-semibold transition"
              >
                <Upload size={14} /> Importar CSV
              </button>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-line/50">
                  <th className="px-4 py-2 text-left text-xs text-ink-3 font-medium uppercase tracking-wider">Fecha</th>
                  <th className="px-4 py-2 text-left text-xs text-ink-3 font-medium uppercase tracking-wider">Archivo</th>
                  <th className="px-4 py-2 text-left text-xs text-ink-3 font-medium uppercase tracking-wider">Broker</th>
                  <th className="px-4 py-2 text-left text-xs text-ink-3 font-medium uppercase tracking-wider">Filas</th>
                  <th className="px-4 py-2 text-left text-xs text-ink-3 font-medium uppercase tracking-wider">Estado</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {batches.map(b => (
                  <tr key={b.id} className="border-b border-line/50 dark:border-line/20">
                    <td className="px-4 py-2 text-sm text-ink-2 tabular whitespace-nowrap">
                      {fmtDate(b.created_at)}
                    </td>
                    <td className="px-4 py-2 text-sm text-ink-1 max-w-[260px] truncate" title={b.file_name}>
                      {b.file_name || '—'}
                    </td>
                    <td className="px-4 py-2 text-sm text-ink-2">{b.broker}</td>
                    <td className="px-4 py-2 text-sm text-ink-2 tabular">
                      {b.valid_rows} válidas
                      {b.invalid_rows > 0 && <span className="text-rendi-warn"> · {b.invalid_rows} con errores</span>}
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
                            className="inline-flex items-center gap-1.5 text-xs text-ink-2 hover:text-ink-0 px-2 py-1 rounded transition disabled:opacity-50"
                            title="Revertir y abrir el wizard ya pre-cargado para ajustar y reimportar"
                          >
                            {redoing === b.id ? <Loader2 size={12} className="animate-spin" /> : <Edit3 size={12} />}
                            Editar y rehacer
                          </button>
                          <button
                            onClick={() => setConfirmRevert(b)}
                            disabled={reverting === b.id || redoing === b.id}
                            className="inline-flex items-center gap-1.5 text-xs text-ink-3 hover:text-rendi-neg px-2 py-1 rounded transition disabled:opacity-50"
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
      </Panel>

      {confirmRedo && (
        <Modal title="Editar y rehacer" onClose={() => setConfirmRedo(null)}>
          <div className="space-y-3 text-sm text-ink-1">
            <p>Vamos a revertir la importación del <strong>{fmtDate(confirmRedo.created_at)}</strong> ({confirmRedo.file_name || 'sin nombre'}) y abrir el wizard ya pre-cargado con los mismos datos para que ajustes lo que haga falta.</p>
            <p className="text-ink-2">
              Esto va a:
            </p>
            <ul className="list-disc list-inside text-xs text-ink-2 space-y-0.5 pl-2">
              <li>Borrar las posiciones, operaciones y movimientos de cash creados por este import.</li>
              <li>Marcar el batch como <em>reverted</em>.</li>
              <li>Abrir el wizard ya en <em>Vista previa</em> con los mismos datos (podés omitir filas, cargar estado inicial, etc.).</li>
              <li>Al confirmar se crea un import <em>nuevo</em> — el original queda en el historial como reverted.</li>
            </ul>
            <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-rendi-warn/[0.08] border border-rendi-warn/25 text-xs text-rendi-warn">
              <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
              <span>
                Si el batch incluye ventas o conversiones de moneda, la reversa es <strong>best-effort</strong>: recreamos las posiciones consumidas pero el tipo de cambio promedio del cash USD puede tener un drift menor. Al re-importar se sobrescribe.
              </span>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setConfirmRedo(null)}
                className="px-4 py-2 text-sm text-ink-3 hover:text-ink-0"
              >
                Cancelar
              </button>
              <button
                onClick={() => doRedo(confirmRedo)}
                disabled={redoing === confirmRedo.id}
                className="px-4 py-2 text-sm bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 font-mono uppercase tracking-caps text-[11px] rounded-md font-semibold transition disabled:opacity-50 inline-flex items-center gap-1.5"
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

      {showWizard && (
        <ImportWizard
          onClose={() => {
            setShowWizard(false)
            // Si es el primer import del user, redirect al primer insight.
            // El flag se setea cuando hicieron click en "Cerrar" del DoneStep
            // (= confirmaron el import). Después ya no se vuelve a mostrar.
            if (importJustConfirmed && !localStorage.getItem(FIRST_IMPORT_FLAG)) {
              localStorage.setItem(FIRST_IMPORT_FLAG, '1')
              setImportJustConfirmed(false)
              navigate('/bienvenida')
              return
            }
            setImportJustConfirmed(false)
            load()
          }}
          onConfirmed={() => {
            setImportJustConfirmed(true)
            load()
          }}
        />
      )}

      {showPpiEstado && (
        <TenenciaUpload
          onClose={() => setShowPpiEstado(false)}
          onConfirmed={() => { setInfo('Cartera completada con el Estado de Cuenta de PPI.'); load() }}
          title="Completá tu cartera con el Estado de Cuenta (PPI)"
          introText="Los Movimientos de PPI no traen las posiciones que ya tenías antes. Subí el Estado de Cuenta (Excel) y completamos lo que falta — sin tocar lo que ya está."
          brokerMatch={/ppi/i}
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          fileLabel="Estado de Cuenta (Excel)"
          fileHint={[
            'Entrá a tu cuenta de PPI desde la web.',
            'Quedate en la pantalla principal, donde aparece tu cartera.',
            'Arriba a la derecha, tocá el botón Exportar.',
            'Elegí Excel (no PDF) y descargá el archivo.',
          ]}
          format="ppi"
          docLabel="el Estado de Cuenta"
        />
      )}

      {confirmRevert && (
        <Modal title="Confirmar reversa" onClose={() => setConfirmRevert(null)}>
          <div className="space-y-3 text-sm text-ink-1">
            <p>Vas a revertir la importación del <strong>{fmtDate(confirmRevert.created_at)}</strong> ({confirmRevert.file_name || 'sin nombre'}).</p>
            <p className="text-ink-2">
              Esto va a:
            </p>
            <ul className="list-disc list-inside text-xs text-ink-2 space-y-0.5 pl-2">
              <li>Borrar las posiciones que se crearon en este import.</li>
              <li>Reversar los movimientos de cash y los entries mensuales correspondientes.</li>
              <li>Marcar el batch como <em>reverted</em> (no se borra del historial).</li>
            </ul>
            <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-rendi-warn/[0.08] border border-rendi-warn/25 text-xs text-rendi-warn">
              <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
              <span>
                Si este import incluye ventas o conversiones de moneda, la reversa normal va a fallar. Usá <strong>Forzar revert</strong> para revertir todo de una (incluye ventas/conversiones — modo nuclear).
              </span>
            </div>
            {error && (
              <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-rendi-neg/[0.08] border border-rendi-neg/25 text-xs text-rendi-neg">
                <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => { setConfirmRevert(null); setError(null) }}
                className="px-4 py-2 text-sm text-ink-3 hover:text-ink-0"
              >
                Cancelar
              </button>
              <button
                onClick={() => doRevert(confirmRevert, { force: true })}
                disabled={reverting === confirmRevert.id}
                className="px-4 py-2 text-sm bg-rendi-warn/15 hover:bg-rendi-warn/25 text-rendi-warn border border-rendi-warn/30 rounded-md font-semibold transition disabled:opacity-50 inline-flex items-center gap-1.5"
                title="Revierte también ventas y conversiones (modo nuclear)"
              >
                {reverting === confirmRevert.id && <Loader2 size={12} className="animate-spin" />}
                <AlertTriangle size={12} />
                Forzar revert
              </button>
              <button
                onClick={() => doRevert(confirmRevert)}
                disabled={reverting === confirmRevert.id}
                className="px-4 py-2 text-sm bg-rendi-neg/15 hover:bg-rendi-neg/25 text-rendi-neg border border-rendi-neg/30 rounded-md font-semibold transition disabled:opacity-50 inline-flex items-center gap-1.5"
              >
                {reverting === confirmRevert.id && <Loader2 size={12} className="animate-spin" />}
                <Trash2 size={12} />
                Revertir
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* Modal: limpiar datos de un broker — selección + warning + CONFIRMAR */}
      {wipeOpen && (
        <Modal title="Limpiar broker" onClose={() => { setWipeOpen(false); setError(null) }}>
          <div className="space-y-4 text-sm text-ink-1">
            <p className="text-ink-2">
              Elegí el broker que querés eliminar. Se borra <strong className="text-ink-0">todo</strong>: el broker y sus
              operaciones, posiciones y movimientos. Si lo volvés a importar, se crea de nuevo limpio.
            </p>

            {wipeBrokers.length === 0 ? (
              <p className="text-ink-3 text-xs">No tenés brokers cargados.</p>
            ) : (
              <div className="space-y-1.5 max-h-64 overflow-y-auto">
                {wipeBrokers.map((b) => {
                  const sel = wipeSel === b.name
                  return (
                    <button
                      key={b.name}
                      type="button"
                      onClick={() => setWipeSel(b.name)}
                      className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg border text-left transition-colors ${
                        sel ? 'border-rendi-neg/50 bg-rendi-neg/[0.08]' : 'border-line hover:border-line-2 hover:bg-bg-2/60'
                      }`}
                    >
                      <span className="flex items-center gap-2.5 min-w-0">
                        <span className={`w-4 h-4 rounded-full border flex items-center justify-center flex-shrink-0 ${sel ? 'border-rendi-neg' : 'border-line-2'}`}>
                          {sel && <span className="w-2 h-2 rounded-full bg-rendi-neg" />}
                        </span>
                        <span className="font-medium text-ink-0 truncate">{b.name}</span>
                      </span>
                      <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3 flex-shrink-0">{b.currency}</span>
                    </button>
                  )
                })}
              </div>
            )}

            {wipeSel && (
              <div className="flex items-start gap-2 px-3 py-2.5 rounded-md bg-rendi-neg/[0.08] border border-rendi-neg/30 text-xs text-rendi-neg">
                <AlertTriangle size={13} className="mt-0.5 flex-shrink-0" />
                <span>
                  Al confirmar vas a <strong>eliminar {wipeSel}</strong> y todos sus datos (operaciones, posiciones y
                  movimientos), incluido cualquier resto de imports anteriores. Para recuperarlo vas a tener que{' '}
                  <strong>volver a importar el CSV</strong>.
                </span>
              </div>
            )}

            {error && (
              <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-rendi-neg/[0.08] border border-rendi-neg/25 text-xs text-rendi-neg">
                <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => { setWipeOpen(false); setError(null) }}
                className="px-4 py-2 text-sm text-ink-3 hover:text-ink-0"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={confirmWipe}
                disabled={!wipeSel || wiping}
                className="px-4 py-2 text-sm bg-rendi-neg/15 hover:bg-rendi-neg/25 text-rendi-neg border border-rendi-neg/30 rounded-md font-semibold uppercase tracking-caps transition disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
              >
                {wiping && <Loader2 size={12} className="animate-spin" />}
                <Trash2 size={12} />
                Confirmar
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
      <Pill tone="signal" dot>
        <CheckCircle2 size={9} strokeWidth={2} className="mr-0.5" /> Confirmada
      </Pill>
    )
  }
  if (status === 'reverted') {
    return (
      <Pill tone="off">
        <ChevronLeft size={9} strokeWidth={2} className="mr-0.5" /> Revertida
      </Pill>
    )
  }
  return (
    <Pill tone="warn" dot>
      {status}
    </Pill>
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
