import { useState, useEffect } from 'react'
import { RefreshCw, Loader2, CheckCircle2, Trash2, Plug, ChevronDown } from 'lucide-react'
import { api } from '../../utils/api'

// WallbitConnect — conexión read-only a Wallbit vía API key. El usuario pega una
// key con permiso `read`; Rendi trae sus operaciones y las sincroniza solas (sin
// subir archivos). Estado + sync + desconexión, todo contra /api/wallbit/*.
//
// onlyWhenConnected: si true, NO renderiza el formulario de conexión (devuelve null
//   cuando no está conectado). Se usa en la página de Importar como card de gestión
//   —estado + sincronizar + desconectar— mientras el ALTA vive en el wizard.
export default function WallbitConnect({ onSynced, onlyWhenConnected = false }) {
  const [status, setStatus] = useState(null)   // null = cargando; {connected, ...}
  const [apiKey, setApiKey] = useState('')
  const [busy, setBusy] = useState('')          // '' | 'connect' | 'sync' | 'disconnect'
  const [msg, setMsg] = useState(null)          // {type:'ok'|'err', text}
  const [showHelp, setShowHelp] = useState(false)

  async function loadStatus() {
    try { setStatus(await api.get('/wallbit/status')) }
    catch { setStatus({ connected: false }) }
  }
  useEffect(() => { loadStatus() }, [])

  async function connect() {
    const key = apiKey.trim()
    if (!key) { setMsg({ type: 'err', text: 'Pegá tu API key read-only de Wallbit.' }); return }
    setBusy('connect'); setMsg(null)
    try {
      const r = await api.post('/wallbit/connect', { api_key: key })
      setApiKey('')
      setMsg({ type: 'ok', text: `Conectado. Importamos ${r.new_trades ?? 0} operaciones.` })
      await loadStatus(); onSynced && onSynced()
    } catch (e) {
      setMsg({ type: 'err', text: e?.message || 'No se pudo conectar con Wallbit.' })
    } finally { setBusy('') }
  }

  async function sync() {
    setBusy('sync'); setMsg(null)
    try {
      const r = await api.post('/wallbit/sync')
      setMsg({ type: 'ok', text: r.new_trades ? `Sincronizado: ${r.new_trades} operaciones nuevas.` : 'Ya estabas al día.' })
      await loadStatus(); onSynced && onSynced()
    } catch (e) {
      setMsg({ type: 'err', text: e?.message || 'No se pudo sincronizar.' })
    } finally { setBusy('') }
  }

  async function disconnect() {
    if (!window.confirm('¿Desconectar Wallbit? Se borra la API key guardada. Tus posiciones ya importadas quedan.')) return
    setBusy('disconnect'); setMsg(null)
    try { await api.delete('/wallbit/disconnect'); await loadStatus() }
    catch (e) { setMsg({ type: 'err', text: e?.message || 'No se pudo desconectar.' }) }
    finally { setBusy('') }
  }

  if (status === null) return null   // no flashear mientras carga el estado
  const connected = !!status.connected
  // Modo "gestión" (card de Importar): si no está conectado, el alta vive en el wizard.
  if (onlyWhenConnected && !connected) return null

  const fmtDate = (s) => {
    if (!s) return null
    try { return new Date(String(s).replace(' ', 'T') + 'Z').toLocaleString('es-AR') } catch { return s }
  }

  return (
    <div className="mb-4 border border-line rounded bg-bg-1 px-4 py-3.5">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <h2 className="text-sm font-medium text-ink-1 flex items-center gap-2">
            <Plug size={15} className="text-data-violet" strokeWidth={1.75} aria-hidden="true" />
            Wallbit — sincronización automática
          </h2>
          <p className="text-xs text-ink-3 mt-0.5">
            {connected
              ? 'Tu cuenta de Wallbit se sincroniza sola: traemos tus operaciones y calculamos tu ganancia real.'
              : 'Conectá tu cuenta con una API key de solo lectura y Rendi trae tus operaciones solo — sin subir archivos.'}
          </p>
        </div>
        {connected && (
          <span className="inline-flex items-center gap-1.5 text-[12.5px] text-rendi-pos border border-rendi-pos/30 bg-rendi-pos/[0.08] px-2 py-1 rounded-sm shrink-0 font-medium">
            <CheckCircle2 size={12} /> Conectado
          </span>
        )}
      </div>

      {msg && (
        <div className={`mt-3 text-xs px-2.5 py-1.5 rounded-md border ${
          msg.type === 'ok'
            ? 'text-rendi-pos bg-rendi-pos/[0.08] border-rendi-pos/25'
            : 'text-rendi-neg bg-rendi-neg/[0.08] border-rendi-neg/25'}`}>
          {msg.text}
        </div>
      )}

      {!connected ? (
        <div className="mt-3">
          <div className="flex gap-2 flex-wrap">
            <input
              type="password"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') connect() }}
              placeholder="Pegá tu API key read-only de Wallbit"
              className="flex-1 min-w-[220px] bg-bg-0 border border-line rounded-md px-3 py-2 text-sm text-ink-0 placeholder:text-ink-3 focus:border-data-violet/50 outline-none"
            />
            <button
              onClick={connect} disabled={busy === 'connect'}
              className="inline-flex items-center gap-1.5 text-sm bg-data-violet/15 hover:bg-data-violet/25 text-data-violet border border-data-violet/40 px-4 py-2 rounded-md font-medium transition-colors disabled:opacity-50">
              {busy === 'connect' ? <Loader2 size={14} className="animate-spin" /> : <Plug size={14} />} Conectar
            </button>
          </div>
          {/* Disclaimer de responsabilidad — siempre visible. La API de Wallbit NO
              expone los permisos de una key, así que no podemos bloquear por código
              una key con permiso de operar; el mitigante es esta instrucción clara. */}
          <p className="mt-2 text-[11px] text-ink-3 leading-relaxed">
            Usá una key de <b>solo lectura (read)</b>. Rendi solo lee tus operaciones — nunca opera ni mueve tu dinero. Es tu responsabilidad generar la key con permiso de lectura; Rendi no se hace responsable por keys creadas con permisos de operar (<i>trade</i>).
          </p>
          <button onClick={() => setShowHelp(v => !v)} className="mt-2 inline-flex items-center gap-1 text-[11px] text-ink-3 hover:text-ink-1 transition-colors">
            <ChevronDown size={12} className={showHelp ? 'rotate-180 transition-transform' : 'transition-transform'} /> ¿Cómo genero mi API key?
          </button>
          {showHelp && (
            <ol className="mt-2 text-xs text-ink-2 space-y-1 list-decimal pl-4 leading-relaxed">
              <li>Entrá a tu cuenta de Wallbit → <b>Settings → API Keys</b> (o <b>Agents → Create agent</b>).</li>
              <li>Creá una key con permiso <b>read</b> (solo lectura). Nunca uses <b>trade</b>.</li>
              <li>Copiá la key (se muestra una sola vez) y pegala acá arriba.</li>
              <li>Rendi solo <b>lee</b> tus operaciones — nunca puede operar ni mover tu plata.</li>
            </ol>
          )}
        </div>
      ) : (
        <div className="mt-3 flex items-center gap-3 flex-wrap">
          <span className="text-xs text-ink-3">
            {status.last_sync_at ? `Última sync: ${fmtDate(status.last_sync_at)}` : 'Sin sincronizar aún'}
            {status.last_sync_status && status.last_sync_status !== 'ok' && (
              <span className="text-rendi-neg"> · {status.last_sync_status}</span>
            )}
          </span>
          <button onClick={sync} disabled={busy === 'sync'}
            className="inline-flex items-center gap-1.5 text-[12.5px] border border-line bg-bg-2 hover:bg-bg-3 text-ink-2 hover:text-ink-0 px-2.5 py-1.5 rounded-sm transition-colors disabled:opacity-50 font-medium">
            {busy === 'sync' ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Sincronizar ahora
          </button>
          <button onClick={disconnect} disabled={busy === 'disconnect'}
            className="inline-flex items-center gap-1.5 text-[12.5px] border border-rendi-neg/30 bg-rendi-neg/[0.08] hover:bg-rendi-neg/15 text-rendi-neg px-2.5 py-1.5 rounded-sm transition-colors disabled:opacity-50 font-medium">
            {busy === 'disconnect' ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />} Desconectar
          </button>
        </div>
      )}
    </div>
  )
}
