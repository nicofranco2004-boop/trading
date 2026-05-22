// ResetPassword — donde aterriza el user al clickear el link del email.
// ═══════════════════════════════════════════════════════════════════════════
// Flow:
//   1. User pidió reset → backend mandó email con link "/reset-password?token=xxx"
//   2. User clickea → llega acá
//   3. Tipea nueva contraseña (con confirm)
//   4. POST /api/auth/reset-password { token, new_password }
//   5. Backend valida token + hashea + invalida sessions viejas + devuelve token nuevo
//   6. Auto-login + redirect a /
//
// Edge cases:
//   • Token vencido / usado / inválido → mensaje claro + link "pedí uno nuevo"
//   • Sin token en la URL → redirect a /login

import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { Lock, CheckCircle2, ArrowLeft, ArrowRight } from 'lucide-react'
import RendiLogo from '../components/RendiLogo'
import { useAuth } from '../contexts/AuthContext'

export default function ResetPassword() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  // Sin token en URL → al login (no podemos hacer nada útil acá)
  useEffect(() => {
    if (!token) navigate('/login')
  }, [token, navigate])

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
      const res = await fetch('/api/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: password }),
      })
      const data = await res.json()
      if (!res.ok) {
        const msg = typeof data.detail === 'string'
          ? data.detail
          : (data.detail?.error || 'No pudimos restablecer la contraseña.')
        throw new Error(msg)
      }
      // Backend nos devuelve un token nuevo → auto-login
      login(data.token, data.name)
      navigate('/')
    } catch (ex) {
      setError(ex.message)
    } finally {
      setLoading(false)
    }
  }

  const inputClass = 'w-full bg-bg-2 dark:bg-bg-2 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 placeholder-ink-3 focus:outline-none focus:border-rendi-pos focus:ring-2 focus:ring-rendi-pos/20 transition-colors'

  return (
    <div className="min-h-screen bg-bg-2 dark:bg-bg-0 flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="flex items-center justify-center gap-3 mb-8">
          <RendiLogo size={36} />
          <span className="text-2xl font-bold text-ink-0 dark:text-white tracking-tight">rendi</span>
        </div>

        <div className="bg-white dark:bg-bg-2/60 border border-line/50 rounded-2xl p-7">
          <div className="text-center mb-6">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-rendi-pos/10 mb-3">
              <Lock size={22} className="text-rendi-pos" strokeWidth={1.75} />
            </div>
            <h1 className="text-xl font-semibold text-ink-0 mb-1.5">Nueva contraseña</h1>
            <p className="text-sm text-ink-2 leading-relaxed">
              Elegí una contraseña nueva para tu cuenta. Mínimo 10 caracteres.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="new-password" className="block text-xs text-ink-3 mb-1">Nueva contraseña</label>
              <input
                id="new-password"
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
              <label htmlFor="confirm-password" className="block text-xs text-ink-3 mb-1">Confirmar contraseña</label>
              <input
                id="confirm-password"
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
              className="w-full bg-rendi-pos hover:bg-rendi-pos/90 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg py-2.5 text-sm font-medium transition-colors inline-flex items-center justify-center gap-1.5"
            >
              {loading ? 'Guardando…' : (
                <>
                  <CheckCircle2 size={14} strokeWidth={1.75} />
                  Restablecer contraseña
                </>
              )}
            </button>
          </form>

          <div className="text-center mt-5 pt-4 border-t border-line/40">
            <Link
              to="/login"
              className="inline-flex items-center gap-1 text-xs text-ink-3 hover:text-ink-0 transition-colors"
            >
              <ArrowLeft size={11} strokeWidth={1.75} />
              Volver al login
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
