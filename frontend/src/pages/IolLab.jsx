import { useEffect, useRef, useState } from 'react'
import { FlaskConical, Loader2, RefreshCw, Trash2, ShieldCheck, AlertTriangle, CheckCircle2, Upload } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import ImportWizard from '../components/import/ImportWizard'
import { api } from '../utils/api'

// IolLab — /lab/iol. Página ESCONDIDA (sin ítem de nav) para que un tester pruebe
// la API de IOL desde Rendi (PLAN_iol_sync.md, Fase 0). El backend gatea por
// allowlist de emails (IOL_LAB_EMAILS) o admin; acá solo mostramos el motivo.
//
// Flujo: usuario + contraseña de IOL → POST /iol/lab/probe (login + probe
// read-only en un thread) → polleamos /iol/lab/status hasta que termine → summary.
// Opt-in "medir duración": guarda SOLO el refresh token cifrado; el cron lo renueva
// cada hora y acá se ve cuántas horas lleva vivo. "Desconectar" lo borra.

export default function IolLab() {
  const [status, setStatus] = useState(null)      // null = cargando
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [keepToken, setKeepToken] = useState(true)
  const [busy, setBusy] = useState('')            // '' | 'probe' | 'refresh' | 'disconnect'
  const [msg, setMsg] = useState(null)            // {type:'ok'|'err', text}
  const pollRef = useRef(null)
  const [imp, setImp] = useState(null)            // último import por API {status, stats, preview}
  const [showWizard, setShowWizard] = useState(false)
  const impPollRef = useRef(null)

  async function loadImport() {
    try { const r = await api.get('/iol/lab/import-status'); setImp(r.import) } catch { /* gate: lo muestra status */ }
  }
  useEffect(() => { loadImport() }, [])
  useEffect(() => {
    const running = imp?.status === 'running'
    if (running && !impPollRef.current) impPollRef.current = setInterval(loadImport, 3000)
    else if (!running && impPollRef.current) { clearInterval(impPollRef.current); impPollRef.current = null }
    return () => { if (impPollRef.current) { clearInterval(impPollRef.current); impPollRef.current = null } }
  }, [imp?.status])

  async function importStart() {
    if (!username.trim() || !password) { setMsg({ type: 'err', text: 'Completá usuario y contraseña de IOL.' }); return }
    setBusy('import'); setMsg(null)
    try {
      await api.post('/iol/lab/import-start', { username: username.trim(), password })
      setPassword('')
      setMsg({ type: 'ok', text: 'Trayendo tu historial de IOL. Tarda un par de minutos (un pedido por operación).' })
      await loadImport()
    } catch (err) {
      setMsg({ type: 'err', text: err?.message || 'No se pudo iniciar la importación.' })
    } finally { setBusy('') }
  }

  async function load() {
    try { setStatus(await api.get('/iol/lab/status')) }
    catch (e) { setStatus({ enabled: false, reason: e?.message || 'No se pudo cargar el estado.' }) }
  }
  useEffect(() => { load() }, [])

  // Mientras hay una corrida en curso, refrescamos cada 3 s.
  useEffect(() => {
    const running = !!status?.running || status?.run?.status === 'running'
    if (running && !pollRef.current) {
      pollRef.current = setInterval(load, 3000)
    } else if (!running && pollRef.current) {
      clearInterval(pollRef.current); pollRef.current = null
    }
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null } }
  }, [status?.running, status?.run?.status])

  async function probe(e) {
    e.preventDefault()
    if (!username.trim() || !password) { setMsg({ type: 'err', text: 'Completá usuario y contraseña de IOL.' }); return }
    setBusy('probe'); setMsg(null)
    try {
      const r = await api.post('/iol/lab/probe', { username: username.trim(), password, keep_token: keepToken })
      setPassword('')
      setMsg({ type: 'ok', text: `Login OK (token de ${r.expires_in ?? '?'} s). La prueba corre en el servidor, tarda ~1 minuto.` })
      await load()
    } catch (err) {
      setMsg({ type: 'err', text: err?.message || 'No se pudo iniciar la prueba.' })
    } finally { setBusy('') }
  }

  async function refreshNow() {
    setBusy('refresh'); setMsg(null)
    try {
      const r = await api.post('/iol/lab/refresh')
      setMsg({ type: r.ok && r.dead ? 'err' : 'ok',
               text: r.dead ? 'El refresh token ya no sirve: IOL lo rechazó. Esa es la medición.' :
                     r.transient ? 'Error de red al renovar, se reintenta en la próxima hora.' :
                     r.active ? `Renovado (#${r.count}).` : 'No hay medición activa.' })
      await load()
    } catch (err) { setMsg({ type: 'err', text: err?.message || 'No se pudo renovar.' }) }
    finally { setBusy('') }
  }

  async function disconnect() {
    if (!window.confirm('¿Borrar el refresh token guardado? Termina la medición de duración.')) return
    setBusy('disconnect'); setMsg(null)
    try { await api.delete('/iol/lab/disconnect'); setMsg({ type: 'ok', text: 'Token borrado.' }); await load() }
    catch (err) { setMsg({ type: 'err', text: err?.message || 'No se pudo desconectar.' }) }
    finally { setBusy('') }
  }

  const fmt = (s) => {
    if (!s) return '—'
    try { return new Date(String(s).replace(' ', 'T') + 'Z').toLocaleString('es-AR') } catch { return s }
  }

  if (status === null) {
    return <div className="p-6 text-sm text-ink-3 flex items-center gap-2"><Loader2 size={14} className="animate-spin" /> Cargando…</div>
  }

  if (!status.enabled) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-8">
        <PageHeader eyebrow="Laboratorio" title="Prueba de la API de IOL" />
        <Panel>
          <p className="text-sm text-ink-2 flex items-start gap-2">
            <AlertTriangle size={16} className="text-signal-amber shrink-0 mt-0.5" />
            <span>{status.reason || 'Esta prueba no está habilitada para tu cuenta.'} Si sos tester, avisanos con el email de tu cuenta de Rendi.</span>
          </p>
        </Panel>
      </div>
    )
  }

  const run = status.run
  const watch = status.watch || {}
  const running = !!status.running || run?.status === 'running'

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <PageHeader
        eyebrow="Laboratorio"
        title="Prueba de la API de IOL"
        subtitle="Solo lectura. Rendi usa tu contraseña una vez para pedirle un token a IOL y la descarta. No puede operar: el cliente no tiene ninguna función de compra, venta ni extracción."
      />

      {msg && (
        <div className={`mb-4 text-sm rounded-lg px-3 py-2 border ${msg.type === 'ok' ? 'border-signal-green/40 text-ink-1 bg-bg-1' : 'border-signal-red/40 text-signal-red bg-bg-1'}`}>
          {msg.text}
        </div>
      )}

      <Panel className="mb-4">
        <h2 className="text-sm font-medium text-ink-1 flex items-center gap-2 mb-1">
          <FlaskConical size={15} className="text-data-violet" strokeWidth={1.75} /> 1. Correr la prueba
        </h2>
        <p className="text-xs text-ink-3 mb-3">
          Antes, IOL tiene que tener tu API activada: mandales un mensaje pidiendo &quot;activación de APIs&quot; y aceptá los términos en
          <span className="text-ink-2"> Mi Cuenta › Personalización › APIs</span>. Sin eso, el login falla.
        </p>
        <form onSubmit={probe} className="grid gap-3 sm:grid-cols-2" autoComplete="off">
          <label className="text-xs text-ink-3">
            Usuario de IOL
            <input value={username} onChange={e => setUsername(e.target.value)} autoComplete="off"
                   className="mt-1 w-full rounded-lg border border-line bg-bg-0 px-3 py-2 text-sm text-ink-1" />
          </label>
          <label className="text-xs text-ink-3">
            Contraseña de IOL
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password"
                   className="mt-1 w-full rounded-lg border border-line bg-bg-0 px-3 py-2 text-sm text-ink-1" />
          </label>
          <label className="sm:col-span-2 flex items-start gap-2 text-xs text-ink-2">
            <input type="checkbox" checked={keepToken} onChange={e => setKeepToken(e.target.checked)} className="mt-0.5" />
            <span>
              Medir cuánto dura el acceso: guardar <b>solo el refresh token</b> (cifrado, nunca la contraseña) y renovarlo cada hora hasta que IOL lo rechace.
              Podés borrarlo cuando quieras con &quot;Desconectar&quot;. Al terminar, si querés estar 100% tranquilo, cambiá tu contraseña de IOL.
            </span>
          </label>
          <div className="sm:col-span-2">
            <button type="submit" disabled={busy === 'probe' || running}
                    className="inline-flex items-center gap-2 rounded-lg bg-data-violet text-white text-sm px-4 py-2 disabled:opacity-50">
              {busy === 'probe' || running ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
              {running ? 'Prueba en curso…' : 'Iniciar prueba de solo lectura'}
            </button>
            <button type="button" onClick={importStart} disabled={!!busy || imp?.status === 'running'}
                    className="ml-2 inline-flex items-center gap-2 rounded-lg border border-line text-sm px-4 py-2 text-ink-2 disabled:opacity-50">
              {busy === 'import' || imp?.status === 'running' ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
              Traer mi historial para importar (beta)
            </button>
          </div>
        </form>
      </Panel>

      <Panel className="mb-4">
        <h2 className="text-sm font-medium text-ink-1 mb-1">2. Resultado</h2>
        {!run && <p className="text-xs text-ink-3">Todavía no corriste ninguna prueba.</p>}
        {run && (
          <>
            <p className="text-xs text-ink-3 mb-2">
              Corrida #{run.id} · {fmt(run.started_at)} · {run.status === 'running'
                ? <span className="inline-flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> corriendo</span>
                : run.status === 'ok'
                  ? <span className="inline-flex items-center gap-1 text-signal-green"><CheckCircle2 size={12} /> terminó {fmt(run.finished_at)}</span>
                  : <span className="text-signal-red">error: {run.error}</span>}
            </p>
            {run.summary && (
              <pre className="text-[11px] leading-relaxed whitespace-pre-wrap bg-bg-0 border border-line rounded-lg p-3 max-h-[28rem] overflow-auto text-ink-2">{run.summary}</pre>
            )}
            {run.status === 'ok' && (
              <p className="text-xs text-ink-3 mt-2">Listo, ya nos llegó. Gracias. Si podés, mandanos también el export &quot;Movimientos históricos&quot; (.xls) de IOL.</p>
            )}
          </>
        )}
      </Panel>

      <Panel>
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <h2 className="text-sm font-medium text-ink-1 mb-1">3. Duración del acceso</h2>
            {!watch.active && !watch.started_at && <p className="text-xs text-ink-3">Sin medición activa.</p>}
            {(watch.active || watch.started_at) && (
              <ul className="text-xs text-ink-2 space-y-0.5">
                <li>Estado: {watch.active ? <span className="text-signal-green">activa ({watch.status})</span> : <span className="text-signal-red">terminada · {watch.status}</span>}</li>
                <li>Empezó: {fmt(watch.started_at)}</li>
                <li>Última renovación OK: {fmt(watch.last_ok_at)} · {watch.refresh_count} renovaciones · {watch.hours_alive ?? '—'} h vivo</li>
                {watch.last_fail && <li>Último fallo: {fmt(watch.last_fail.at)} · {watch.last_fail.detail}</li>}
              </ul>
            )}
          </div>
          {watch.active && (
            <div className="flex gap-2">
              <button onClick={refreshNow} disabled={!!busy}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-line text-xs px-3 py-1.5 text-ink-2 disabled:opacity-50">
                {busy === 'refresh' ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Renovar ahora
              </button>
              <button onClick={disconnect} disabled={!!busy}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-signal-red/40 text-xs px-3 py-1.5 text-signal-red disabled:opacity-50">
                {busy === 'disconnect' ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />} Desconectar y borrar
              </button>
            </div>
          )}
        </div>
        {watch.log?.length > 0 && (
          <details className="mt-3">
            <summary className="text-xs text-ink-3 cursor-pointer">Bitácora ({watch.log.length})</summary>
            <pre className="text-[11px] whitespace-pre-wrap bg-bg-0 border border-line rounded-lg p-2 mt-2 text-ink-3 max-h-48 overflow-auto">
              {watch.log.map(l => `${l.at}  ${l.ok ? 'OK ' : 'ERR'}  ${l.detail}`).join('\n')}
            </pre>
          </details>
        )}
      </Panel>

      <Panel className="mt-4">
        <h2 className="text-sm font-medium text-ink-1 mb-1">4. Importar mi historial por API (beta)</h2>
        <p className="text-xs text-ink-3 mb-2">
          Trae tus operaciones de IOL por API y las convierte al mismo formato que el archivo de Movimientos,
          así entran por el importador de siempre: ves el preview y confirmás vos. Dividendos, depósitos y
          retiros no vienen por API (limitación de IOL); esos siguen entrando por el archivo.
        </p>
        {!imp && <p className="text-xs text-ink-3">Todavía no trajiste tu historial.</p>}
        {imp && imp.status === 'running' && (
          <p className="text-xs text-ink-2 inline-flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> Trayendo operaciones… (empezó {fmt(imp.started_at)})</p>
        )}
        {imp && imp.status === 'error' && <p className="text-xs text-signal-red">Falló: {imp.error}</p>}
        {imp && imp.status === 'empty' && <p className="text-xs text-ink-2">IOL no devolvió operaciones importables. Salteadas: {imp.stats?.skipped?.length ?? 0}.</p>}
        {imp && imp.status === 'ok' && (
          <div className="text-xs text-ink-2 space-y-1">
            <p>
              {imp.stats?.ops ?? 0} operaciones en IOL · {imp.stats?.rows ?? 0} importables · {imp.stats?.skipped?.length ?? 0} salteadas
              {imp.stats?.details_capped ? ' · detalle de comisiones capeado' : ''}
            </p>
            {imp.preview && (
              <p>Preview: {imp.preview.summary?.valid_rows ?? imp.preview.valid_rows ?? '?'} filas válidas
                {(imp.preview.summary?.invalid_rows ?? imp.preview.invalid_rows) ? ` · ${imp.preview.summary?.invalid_rows ?? imp.preview.invalid_rows} con error` : ''}
                {imp.preview.duplicate_row_indices?.length ? ` · ${imp.preview.duplicate_row_indices.length} ya importadas (se omiten)` : ''}</p>
            )}
            {imp.stats?.assumptions?.length > 0 && (
              <p className="text-ink-3">Supuestos aplicados: {imp.stats.assumptions.join(' · ')}</p>
            )}
            <button onClick={() => setShowWizard(true)} disabled={!imp.preview?.session_id}
                    className="mt-2 inline-flex items-center gap-2 rounded-lg bg-data-violet text-white text-sm px-4 py-2 disabled:opacity-50">
              <CheckCircle2 size={14} /> Revisar y confirmar la importación
            </button>
          </div>
        )}
      </Panel>

      {showWizard && imp?.preview && (
        <ImportWizard
          initialPreview={imp.preview}
          onClose={() => { setShowWizard(false); loadImport() }}
          onConfirmed={() => { setShowWizard(false); setMsg({ type: 'ok', text: 'Importación confirmada. Mirá tu Cartera.' }); loadImport() }}
        />
      )}
    </div>
  )
}
