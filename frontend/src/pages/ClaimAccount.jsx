// ClaimAccount — donde aterriza el cliente al clickear el link de invitación
// de su asesor (Plan Asesor, F4a).
// ═══════════════════════════════════════════════════════════════════════════
// Flow:
//   1. El asesor invitó al cliente (le puso su email real) → backend mandó
//      un email con link "/claim?token=xxx"
//   2. El cliente clickea → llega acá
//   3. GET /api/auth/claim/preview?token=xxx → "Tu asesor X te invitó — ya
//      tenés <label> cargado" (contexto/confianza antes de pedir contraseña)
//   4. Tipea contraseña (con confirm)
//   5. POST /api/auth/claim { token, new_password }
//   6. Backend: valida token, setea password + approved=1 (la MISMA cuenta,
//      mismo uid, misma cartera, ahora autogestionada) + auto-login
//   7. Redirect a / — el cliente ve SU cartera con visión Free
//
// Mismo patrón/estilo que ResetPassword.jsx a propósito (mismo mecanismo de
// magic link) — reusar la forma que el user ya vio en el flow de contraseña.
//
// Edge cases:
//   • Token vencido / usado / inválido → mensaje claro, sin form
//   • Sin token en la URL → mensaje "abrí el link de tu email"

import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { Lock, UserRound, CheckCircle2, AlertTriangle, ArrowRight } from 'lucide-react'
import RendiLogo from '../components/RendiLogo'
import { useAuth } from '../contexts/AuthContext'
import PageMeta from '../components/PageMeta'

export default function ClaimAccount() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''
  const [preview, setPreview] = useState(null)     // { advisor_name, label } | null mientras carga
  const [previewError, setPreviewError] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [retryKey, setRetryKey] = useState(0)
  const { login } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (!token) { setPreviewError('missing'); return }
    let cancelled = false
    setPreviewError('')
    setPreview(null)
    const controller = new AbortController()
    // Sin esto el spinner "Validando tu invitación…" cuelga para siempre si
    // el fetch nunca resuelve (red caída a mitad de camino, no un error explícito).
    const timeout = setTimeout(() => controller.abort(), 15000)
    fetch(`/api/auth/claim/preview?token=${encodeURIComponent(token)}`, { signal: controller.signal })
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

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    if (password.length < 10) {
      setError('La contraseña tiene que tener al menos 10 caracteres.')
      return
    }
    if (password !== confirm) {
      setError('Las contraseñas no coinciden.')
      return
    }
    setLoading(true)
    try {
      const res = await fetch('/api/auth/claim', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: password }),
      })
      const data = await res.json()
      if (!res.ok) {
        const msg = typeof data.detail === 'string'
          ? data.detail
          : (data.detail?.error || 'No pudimos activar tu cuenta.')
        throw new Error(msg)
      }
      login(data.token, data.name, { email: data.email })
      navigate('/')
    } catch (ex) {
      setError(ex.message)
    } finally {
      setLoading(false)
    }
  }

  const inputClass = 'w-full bg-bg-2 dark:bg-bg-2 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 placeholder-ink-3 focus:outline-none focus:border-data-violet focus:ring-2 focus:ring-data-violet/20 transition-colors'

  return (
    <div className="min-h-screen bg-bg-2 dark:bg-bg-0 flex items-center justify-center px-4">
      <PageMeta
        title="Activá tu cuenta — Rendi"
        description="Creá tu contraseña para entrar a la cartera que tu asesor cargó en Rendi."
        canonical="/claim"
        noindex={true}
      />
      <div className="w-full max-w-md">
        <div className="flex items-center justify-center gap-3 mb-8">
          <RendiLogo size={36} />
          <span className="text-2xl font-bold text-ink-0 dark:text-white tracking-tight">rendi</span>
        </div>

        <div className="bg-white dark:bg-bg-2/60 border border-line/50 rounded-2xl p-7">
          {previewError ? (
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
              {previewError === 'network' ? (
                <button
                  onClick={() => setRetryKey(k => k + 1)}
                  className="text-xs text-data-violet hover:underline"
                >
                  Reintentar
                </button>
              ) : (
                <Link to="/login" className="text-xs text-data-violet hover:underline">
                  Ir al login
                </Link>
              )}
            </div>
          ) : !preview ? (
            <div className="text-center py-6">
              <p className="text-sm text-ink-3">Validando tu invitación…</p>
            </div>
          ) : (
            <>
              <div className="text-center mb-6">
                <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-data-violet/10 mb-3">
                  <UserRound size={22} className="text-data-violet" strokeWidth={1.75} />
                </div>
                <h1 className="text-xl font-semibold text-ink-0 mb-1.5">
                  {preview.advisor_name} te invitó a Rendi
                </h1>
                <p className="text-sm text-ink-2 leading-relaxed">
                  {preview.label
                    ? <>Ya tenés <span className="text-ink-0 font-medium">{preview.label}</span> cargada — creá tu contraseña para entrar a verla.</>
                    : 'Creá tu contraseña para entrar a tu cuenta.'}
                </p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label htmlFor="claim-password" className="block text-xs text-ink-3 mb-1">Contraseña</label>
                  <input
                    id="claim-password"
                    type="password"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    autoComplete="new-password"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    placeholder="Mínimo 10 caracteres"
                    className={inputClass}
                    autoFocus
                  />
                  {password && password.length < 10 && (
                    <p className="text-xs text-amber-500 dark:text-amber-400 mt-1">
                      Faltan caracteres · {password.length}/10
                    </p>
                  )}
                </div>
                <div>
                  <label htmlFor="claim-confirm" className="block text-xs text-ink-3 mb-1">Confirmar contraseña</label>
                  <input
                    id="claim-confirm"
                    type="password"
                    value={confirm}
                    onChange={e => setConfirm(e.target.value)}
                    autoComplete="new-password"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    placeholder="Repetí la misma"
                    className={inputClass}
                  />
                  {confirm && password !== confirm && (
                    <p className="text-xs text-amber-500 dark:text-amber-400 mt-1">
                      Las contraseñas no coinciden
                    </p>
                  )}
                </div>

                {error && <p className="text-red-500 text-xs">{error}</p>}

                <button
                  type="submit"
                  disabled={loading || password.length < 10 || password !== confirm}
                  className="w-full bg-data-violet hover:bg-data-violet/90 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg py-2.5 text-sm font-medium transition-colors inline-flex items-center justify-center gap-1.5"
                >
                  {loading ? 'Activando…' : (
                    <>
                      <CheckCircle2 size={14} strokeWidth={1.75} />
                      Entrar a mi cuenta
                    </>
                  )}
                </button>
              </form>

              <p className="text-center text-[11px] text-ink-3 mt-5 pt-4 border-t border-line/40 inline-flex items-center justify-center gap-1 w-full">
                Vas a poder ver todo lo que {preview.advisor_name} cargó por vos
                <ArrowRight size={11} strokeWidth={1.75} />
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
