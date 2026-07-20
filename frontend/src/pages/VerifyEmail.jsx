// VerifyEmail — confirma el email del user con código OTP de 6 dígitos.
// ═══════════════════════════════════════════════════════════════════════════
// Flow:
//   1. User llega acá tras registrarse (o tras login si tiene email no verificado)
//   2. Muestra 6 cajitas de 1 dígito (típico OTP UX)
//   3. User tipea o pega el código del email
//   4. POST /api/auth/verify-email → si OK, recibimos token + login
//   5. Redirect a /
//
// Features:
//   • Auto-focus en la siguiente caja al tipear un dígito
//   • Auto-submit al completar los 6 dígitos
//   • Botón "Reenviar código" con cooldown de 60s
//   • Backspace en caja vacía → vuelve a la anterior
//   • Pegar (Cmd+V) el código entero distribuye en las 6 cajas

import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { Sparkles, CheckCircle2, RefreshCw, ArrowLeft } from 'lucide-react'
import RendiLogo from '../components/RendiLogo'
import { useAuth } from '../contexts/AuthContext'
import PageMeta from '../components/PageMeta'

export default function VerifyEmail() {
  const [searchParams] = useSearchParams()
  const emailFromUrl = searchParams.get('email') || ''
  const [email] = useState(emailFromUrl)
  const [digits, setDigits] = useState(['', '', '', '', '', ''])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [resending, setResending] = useState(false)
  const [resendCooldown, setResendCooldown] = useState(0)
  const [info, setInfo] = useState('')
  const inputs = useRef([])
  const { login } = useAuth()
  const navigate = useNavigate()

  // Si no hay email en URL, mandar al login (no podemos verificar sin saber quién)
  useEffect(() => {
    if (!email) navigate('/login')
    else inputs.current[0]?.focus()
  }, [email, navigate])

  // Resend cooldown countdown
  useEffect(() => {
    if (resendCooldown <= 0) return
    const t = setInterval(() => setResendCooldown(c => Math.max(0, c - 1)), 1000)
    return () => clearInterval(t)
  }, [resendCooldown])

  // Auto-submit cuando se completan los 6 dígitos
  useEffect(() => {
    const code = digits.join('')
    if (code.length === 6 && !digits.includes('') && !loading) {
      handleSubmit(code)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [digits])

  function handleDigitChange(i, v) {
    // Soporta tanto tipeo de 1 char como autofill/paste de varios chars
    // (Safari iOS suele meter el código entero en un input cuando viene de SMS).
    const cleanAll = (v || '').replace(/\D/g, '')
    if (!cleanAll) {
      // Borraron el char — limpiar este box
      const next = [...digits]
      next[i] = ''
      setDigits(next)
      setError('')
      return
    }
    if (cleanAll.length === 1) {
      // Caso normal: 1 dígito tipeado
      const next = [...digits]
      next[i] = cleanAll
      setDigits(next)
      setError('')
      if (i < 5) inputs.current[i + 1]?.focus()
    } else {
      // Llegaron varios chars (autofill o paste-no-en-primera-caja).
      // Distribuir en las cajas siguientes.
      const next = [...digits]
      for (let k = 0; k < cleanAll.length && (i + k) < 6; k++) {
        next[i + k] = cleanAll[k]
      }
      setDigits(next)
      setError('')
      const focusIdx = Math.min(i + cleanAll.length, 5)
      setTimeout(() => inputs.current[focusIdx]?.focus(), 0)
    }
  }

  function handleKeyDown(i, e) {
    // Backspace en caja vacía → ir a la anterior
    if (e.key === 'Backspace' && !digits[i] && i > 0) {
      inputs.current[i - 1]?.focus()
    }
  }

  function handlePaste(e) {
    e.preventDefault()
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6)
    if (!pasted) return
    const next = pasted.padEnd(6, '').slice(0, 6).split('')
    setDigits(next)
    const lastIdx = Math.min(pasted.length, 5)
    setTimeout(() => inputs.current[lastIdx]?.focus(), 50)
  }

  async function handleSubmit(codeOverride) {
    const code = codeOverride || digits.join('')
    if (code.length !== 6) {
      setError('Ingresá los 6 dígitos del código.')
      return
    }
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/auth/verify-email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, code }),
      })
      const data = await res.json()
      if (!res.ok) {
        setDigits(['', '', '', '', '', ''])
        inputs.current[0]?.focus()
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Código inválido o expirado.')
      }
      // Verificación exitosa → login + redirect.
      // Si el user es fresh signup (recién verificó email por primera vez)
      // y no clickeó "saltar onboarding" en algún intento previo,
      // lo mandamos al wizard de onboarding. Sino al home.
      login(data.token, data.name, {
        is_admin: !!data.is_admin,
        id: data.user_id || data.id,
        email: data.email || email,
        event_type: 'sign_up',
      })
      const skippedBefore = (() => {
        try {
          return localStorage.getItem('rendi_onboarding_skipped') === '1' ||
                 localStorage.getItem('rendi_onboarding_completed') === '1'
        } catch {
          return false
        }
      })()
      navigate(skippedBefore ? '/' : '/onboarding')
    } catch (ex) {
      setError(ex.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleResend() {
    if (resendCooldown > 0 || resending) return
    setResending(true)
    setError('')
    try {
      const res = await fetch('/api/auth/resend-verification', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || 'No pudimos reenviar el código. Esperá un minuto e intentá de nuevo.')
      }
      setInfo('Código reenviado. Chequeá tu inbox.')
      setResendCooldown(60)
      setDigits(['', '', '', '', '', ''])
      inputs.current[0]?.focus()
    } catch (ex) {
      setError(ex.message)
    } finally {
      setResending(false)
    }
  }

  return (
    <div className="min-h-screen bg-bg-2 dark:bg-bg-0 flex items-center justify-center px-4">
      <PageMeta
        title="Verificar email — Rendi"
        description="Confirmá tu email para activar tu cuenta de Rendi."
        canonical="/verify-email"
        noindex={true}
      />
      <div className="w-full max-w-md">
        <div className="flex items-center justify-center gap-3 mb-8">
          <RendiLogo size={36} />
          <span className="text-2xl font-bold text-ink-0 dark:text-white tracking-tight">rendi</span>
        </div>

        <div className="bg-white dark:bg-bg-2/60 border border-line/50 rounded-2xl p-7">
          <div className="text-center mb-6">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-rendi-pos/10 mb-3">
              <CheckCircle2 size={22} className="text-rendi-pos" strokeWidth={1.75} />
            </div>
            <h1 className="text-xl font-semibold text-ink-0 mb-1.5">Confirmá tu cuenta</h1>
            <p className="text-sm text-ink-2 leading-relaxed">
              Te enviamos un código de 6 dígitos a <b className="text-ink-1">{email}</b>.
              Revisá tu inbox (y la carpeta de spam).
            </p>
          </div>

          {/* 6 cajitas de 1 dígito */}
          <div className="flex justify-center gap-2 mb-5">
            {digits.map((d, i) => (
              <input
                key={i}
                ref={el => (inputs.current[i] = el)}
                type="text"
                inputMode="numeric"
                maxLength={1}
                value={d}
                onChange={e => handleDigitChange(i, e.target.value)}
                onKeyDown={e => handleKeyDown(i, e)}
                onPaste={i === 0 ? handlePaste : undefined}
                disabled={loading}
                className="w-11 h-12 text-center text-xl font-mono font-bold bg-bg-2 dark:bg-bg-1 border border-line rounded-lg text-ink-0 focus:outline-none focus:border-rendi-pos focus:ring-2 focus:ring-rendi-pos/20 transition-colors"
                autoComplete="one-time-code"
              />
            ))}
          </div>

          {error && (
            <p className="text-xs text-rendi-neg text-center mb-3 leading-snug">{error}</p>
          )}
          {info && (
            <p className="text-xs text-rendi-pos text-center mb-3 leading-snug">{info}</p>
          )}

          <button
            type="button"
            onClick={() => handleSubmit()}
            disabled={loading || digits.join('').length !== 6}
            className="w-full bg-rendi-pos hover:bg-rendi-pos/90 text-white font-medium rounded-lg py-2.5 mb-3 transition-colors disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center justify-center gap-1.5"
          >
            {loading ? 'Verificando...' : (
              <>
                <Sparkles size={14} strokeWidth={1.75} />
                Confirmar
              </>
            )}
          </button>

          <button
            type="button"
            onClick={handleResend}
            disabled={resendCooldown > 0 || resending}
            className="w-full inline-flex items-center justify-center gap-1.5 text-xs text-ink-3 hover:text-ink-0 disabled:opacity-50 disabled:cursor-not-allowed py-2 transition-colors"
          >
            <RefreshCw size={11} strokeWidth={1.75} className={resending ? 'animate-spin' : ''} />
            {resending ? 'Reenviando…' : (
              resendCooldown > 0 ? `Reenviar código (en ${resendCooldown}s)` : 'Reenviar código'
            )}
          </button>

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
