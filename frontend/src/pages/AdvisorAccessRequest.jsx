// AdvisorAccessRequest — donde aterriza el CLIENTE cuando un asesor le pide
// acceso a una cuenta que ya es suya.
// ═══════════════════════════════════════════════════════════════════════════
// La diferencia con ClaimAccount (/claim): allá la cuenta la había armado el
// asesor y no la usaba nadie — el mail invitaba a quedársela. Acá la cuenta ya
// tiene dueño, contraseña y cartera adentro. El mail no invita: PREGUNTA.
//
// Flow:
//   1. El asesor invitó un email que ya tenía Rendi → backend creó un pedido
//      (advisor_link_requests) y mandó "Ver el pedido" → /acceso?token=xxx
//   2. GET /api/auth/link-request/preview?token=xxx → quién pide, qué podría
//      hacer, y si el que está mirando es el dueño de esa cuenta
//   3. Aceptar exige estar LOGUEADO con esa cuenta (le estamos dando la cartera
//      entera a un tercero: el que reenvía un mail no puede regalarla).
//      Rechazar alcanza con el link — cortar nunca es peor que no cortar.
//   4. POST /api/auth/link-request/respond { token, accept }
//
// El token va a sessionStorage y sale de la URL: si el cliente tiene que pasar
// por el login, vuelve acá sin arrastrarlo por la barra de direcciones (mismo
// criterio del audit que sacó el token de claim de GA/Meta).

import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { UserRound, CheckCircle2, AlertTriangle, Eye, PencilLine, ShieldCheck } from 'lucide-react'
import RendiLogo from '../components/RendiLogo'
import PageMeta from '../components/PageMeta'
import { useAuth } from '../contexts/AuthContext'

const TOKEN_KEY = 'rendi_link_request_token'

export default function AdvisorAccessRequest() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { logout } = useAuth()
  const [token] = useState(() => {
    const fromUrl = searchParams.get('token')
    if (fromUrl) {
      try { sessionStorage.setItem(TOKEN_KEY, fromUrl) } catch { /* modo privado */ }
      return fromUrl
    }
    try { return sessionStorage.getItem(TOKEN_KEY) || '' } catch { return '' }
  })
  useEffect(() => {
    if (window.location.search.includes('token=')) {
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  const [preview, setPreview] = useState(null)
  const [previewError, setPreviewError] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(null)   // 'accept' | 'reject' | null
  const [done, setDone] = useState(null)       // 'accepted' | 'rejected' | null
  const [retryKey, setRetryKey] = useState(0)

  useEffect(() => {
    if (!token) { setPreviewError('missing'); return }
    let cancelled = false
    setPreviewError('')
    setPreview(null)
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 15000)
    fetch(`/api/auth/link-request/preview?token=${encodeURIComponent(token)}`,
          { signal: controller.signal, credentials: 'include' })
      .then(async (res) => {
        const data = await res.json()
        if (cancelled) return
        if (!res.ok) {
          setPreviewError(typeof data.detail === 'string' ? data.detail : 'Link inválido o vencido.')
          return
        }
        setPreview(data)
      })
      .catch(() => { if (!cancelled) setPreviewError('network') })
      .finally(() => clearTimeout(timeout))
    return () => { cancelled = true; clearTimeout(timeout); controller.abort() }
  }, [token, retryKey])

  async function responder(accept) {
    setError('')
    setSaving(accept ? 'accept' : 'reject')
    try {
      const res = await fetch('/api/auth/link-request/respond', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ token, accept }),
      })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(typeof data.detail === 'string'
          ? data.detail
          : (data.detail?.message || 'No pudimos registrar tu respuesta.'))
      }
      try { sessionStorage.removeItem(TOKEN_KEY) } catch { /* noop */ }
      setDone(accept ? 'accepted' : 'rejected')
    } catch (ex) {
      setError(ex.message)
    } finally {
      setSaving(null)
    }
  }

  const puedeEditar = preview?.permission === 'read_write'
  const btnBase = 'w-full rounded-lg py-2.5 text-sm font-medium transition-colors inline-flex items-center justify-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed'

  return (
    <div className="min-h-screen bg-bg-2 dark:bg-bg-0 flex items-center justify-center px-4">
      <PageMeta
        title="Pedido de acceso — Rendi"
        description="Un asesor te pide acceso a tu cartera en Rendi. Vos decidís."
        canonical="/acceso"
        noindex={true}
      />
      <div className="w-full max-w-md">
        <div className="flex items-center justify-center gap-3 mb-8">
          <RendiLogo size={36} />
          <span className="text-2xl font-bold text-ink-0 dark:text-white tracking-tight">rendi</span>
        </div>

        <div className="bg-white dark:bg-bg-2/60 border border-line/50 rounded-xl p-7">
          {done ? (
            <div className="text-center">
              <div className={`inline-flex items-center justify-center w-12 h-12 rounded-full mb-3 ${done === 'accepted' ? 'bg-rendi-pos/10' : 'bg-bg-2'}`}>
                {done === 'accepted'
                  ? <CheckCircle2 size={22} className="text-rendi-pos" strokeWidth={1.75} />
                  : <ShieldCheck size={22} className="text-ink-2" strokeWidth={1.75} />}
              </div>
              <h1 className="text-xl font-semibold text-ink-0 mb-1.5">
                {done === 'accepted' ? 'Listo' : 'Pedido rechazado'}
              </h1>
              <p className="text-sm text-ink-2 leading-relaxed mb-5">
                {done === 'accepted'
                  ? <>{preview?.advisor_name} ya puede {puedeEditar ? 'ver tu cartera y registrar operaciones' : 'ver tu cartera'}. Le podés cortar el acceso cuando quieras desde Configuración › Tu asesor.</>
                  : <>{preview?.advisor_name} no va a ver nada de tu cuenta.</>}
              </p>
              <Link to="/" className="text-xs text-data-violet hover:underline">Ir a mi cartera</Link>
            </div>
          ) : previewError ? (
            <div className="text-center">
              <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-rendi-neg/10 mb-3">
                <AlertTriangle size={22} className="text-rendi-neg" strokeWidth={1.75} />
              </div>
              <h1 className="text-xl font-semibold text-ink-0 mb-1.5">
                {previewError === 'missing' ? 'Falta el link' : previewError === 'network' ? 'No pudimos conectar' : 'Link inválido'}
              </h1>
              <p className="text-sm text-ink-2 leading-relaxed mb-5">
                {previewError === 'missing'
                  ? 'Abrí el link completo que te llegó por email.'
                  : previewError === 'network'
                  ? 'Revisá tu conexión e intentá de nuevo.'
                  : previewError}
              </p>
              {previewError === 'network'
                ? <button onClick={() => setRetryKey(k => k + 1)} className="text-xs text-data-violet hover:underline">Reintentar</button>
                : <Link to="/login" className="text-xs text-data-violet hover:underline">Ir al login</Link>}
            </div>
          ) : !preview ? (
            <div className="text-center py-6">
              <p className="text-sm text-ink-3">Buscando el pedido…</p>
            </div>
          ) : preview.state !== 'pending' ? (
            <div className="text-center">
              <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-bg-2 mb-3">
                <ShieldCheck size={22} className="text-ink-2" strokeWidth={1.75} />
              </div>
              <h1 className="text-xl font-semibold text-ink-0 mb-1.5">
                {preview.state === 'accepted' ? 'Ya lo aceptaste'
                  : preview.state === 'rejected' ? 'Ya lo rechazaste'
                  : preview.state === 'expired' ? 'El pedido venció'
                  : 'El pedido ya no está activo'}
              </h1>
              <p className="text-sm text-ink-2 leading-relaxed mb-5">
                {preview.state === 'accepted'
                  ? <>{preview.advisor_name} tiene acceso a tu cartera. Se lo podés quitar desde Configuración › Tu asesor.</>
                  : preview.state === 'expired'
                  ? <>Pedile a {preview.advisor_name} que te lo mande de nuevo.</>
                  : <>{preview.advisor_name} no tiene acceso a tu cuenta.</>}
              </p>
              <Link to="/" className="text-xs text-data-violet hover:underline">Ir a mi cartera</Link>
            </div>
          ) : (
            <>
              <div className="text-center mb-5">
                {preview.advisor_logo
                  ? <img src={preview.advisor_logo} alt="" className="h-10 mx-auto mb-3 rounded" />
                  : (
                    <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-data-violet/10 mb-3">
                      <UserRound size={22} className="text-data-violet" strokeWidth={1.75} />
                    </div>
                  )}
                <h1 className="text-xl font-semibold text-ink-0 mb-1.5">
                  {preview.advisor_name} te pide acceso a tu cartera
                </h1>
                <p className="text-sm text-ink-2 leading-relaxed">
                  A tu cuenta <span className="text-ink-0 font-medium">{preview.email_masked}</span>. Vos decidís.
                </p>
                {preview.advisor_matricula && (
                  <p className="text-[11px] text-ink-3 mt-1.5">
                    Matrícula CNV N° {preview.advisor_matricula} (declarada por el asesor)
                  </p>
                )}
              </div>

              <div className="rounded-lg border border-line/60 bg-bg-2/40 p-3.5 mb-4 space-y-2">
                <p className="text-xs text-ink-3">Si aceptás, va a poder:</p>
                <div className="flex items-start gap-2">
                  <Eye size={13} strokeWidth={1.75} className="text-ink-2 mt-0.5 flex-shrink-0" />
                  <p className="text-xs text-ink-1">Ver tu cartera como la ves vos: tenencias, valor, resultado y movimientos.</p>
                </div>
                {puedeEditar && (
                  <div className="flex items-start gap-2">
                    <PencilLine size={13} strokeWidth={1.75} className="text-ink-2 mt-0.5 flex-shrink-0" />
                    <p className="text-xs text-ink-1">Registrar operaciones por vos (cargarlas en Rendi — no las ejecuta en tu broker).</p>
                  </div>
                )}
                <div className="flex items-start gap-2 pt-1.5 border-t border-line/40">
                  <ShieldCheck size={13} strokeWidth={1.75} className="text-rendi-pos mt-0.5 flex-shrink-0" />
                  <p className="text-xs text-ink-2">No va a poder entrar con tu contraseña, cambiarla, ni tocar tu plata. Y le cortás el acceso cuando quieras.</p>
                </div>
              </div>

              {error && <p className="text-red-500 text-xs mb-3">{error}</p>}

              {preview.is_owner ? (
                <div className="space-y-2">
                  <button
                    type="button"
                    onClick={() => responder(true)}
                    disabled={!!saving}
                    className={`${btnBase} bg-data-violet hover:bg-data-violet/90 text-white`}
                  >
                    {saving === 'accept' ? 'Guardando…' : <><CheckCircle2 size={14} strokeWidth={1.75} />Darle acceso</>}
                  </button>
                  <button
                    type="button"
                    onClick={() => responder(false)}
                    disabled={!!saving}
                    className={`${btnBase} border border-line text-ink-1 hover:bg-bg-2`}
                  >
                    {saving === 'reject' ? 'Guardando…' : 'Rechazar'}
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  <p className="text-xs text-ink-2 leading-relaxed rounded border border-line/60 bg-bg-2/40 px-3 py-2">
                    {preview.logged_in
                      ? <>Estás con otra cuenta de Rendi. Para aceptar, entrá con <span className="text-ink-0">{preview.email_masked}</span>.</>
                      : <>Para aceptar, entrá a tu cuenta <span className="text-ink-0">{preview.email_masked}</span>. Así nos aseguramos de que sos vos y no alguien que reenvió el email.</>}
                  </p>
                  <button
                    type="button"
                    onClick={() => {
                      // Con sesión activa hay que SALIR primero: /login no es
                      // ruta del árbol autenticado, así que navegar ahí logueado
                      // cae al catch-all y deposita al cliente en el Home, sin
                      // haber respondido nada — el mismo callejón sin salida que
                      // este flujo vino a arreglar. El token vive en
                      // sessionStorage y logout() solo limpia localStorage.
                      if (preview.logged_in) logout()
                      navigate('/login?next=/acceso')
                    }}
                    className={`${btnBase} bg-data-violet hover:bg-data-violet/90 text-white`}
                  >
                    {preview.logged_in ? 'Salir y entrar con esa cuenta' : 'Iniciar sesión'}
                  </button>
                  <button
                    type="button"
                    onClick={() => responder(false)}
                    disabled={!!saving}
                    className={`${btnBase} border border-line text-ink-1 hover:bg-bg-2`}
                  >
                    {saving === 'reject' ? 'Guardando…' : 'Rechazar sin entrar'}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
