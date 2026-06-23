import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Sparkles, ArrowRight, Eye, EyeOff } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { enableDemoMode } from '../utils/demo'
import { track } from '../utils/track'
import { trackEvent } from '../utils/analytics'
import { trackMetaEvent } from '../utils/metaPixel'
import RendiLogo from '../components/RendiLogo'
import PageMeta from '../components/PageMeta'

export default function Login() {
  const [searchParams] = useSearchParams()
  // Los CTAs de la landing apuntan a /login?mode=register. Sin leer el param,
  // el visitante con intención de crear cuenta caía en la pestaña de LOGIN
  // (form inutilizable, sin cuenta) — fricción directa en el punto de conversión.
  const [mode, setMode] = useState(() => (searchParams.get('mode') === 'register' ? 'register' : 'login'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  // Toggle "ver contraseña" — feature crítica en mobile porque el user no
  // puede verificar visualmente que tipeó bien la pass. Causa #1 de "credenciales
  // inválidas" reportadas: autocomplete del browser mete pass viejo de otra
  // cuenta, o el user mete un caracter de más sin darse cuenta.
  const [showPassword, setShowPassword] = useState(false)
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  // Caso especial: email ya registrado al hacer signup. Mostramos un CTA
  // específico para ir al login en vez del mensaje de error genérico.
  const [emailExists, setEmailExists] = useState(false)
  const [loading, setLoading] = useState(false)
  // Mini-flow inline para "Olvidé mi contraseña" — no necesita página separada,
  // se muestra como un panel debajo del form de login.
  const [forgotMode, setForgotMode] = useState(false)
  const [forgotLoading, setForgotLoading] = useState(false)
  const [forgotSent, setForgotSent] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  // Warmup: el backend de Railway puede estar en cold start. Apenas el visitante
  // abre login/registro, despertamos el container (fire-and-forget) para que el
  // submit no espere el wake — el momento más frágil del funnel.
  useEffect(() => {
    fetch('/api/health').catch(() => {})
  }, [])

  async function handleForgotPassword(e) {
    e.preventDefault()
    if (!email.trim()) {
      setError('Ingresá tu email para recibir el link.')
      return
    }
    setError('')
    setForgotLoading(true)
    try {
      const res = await fetch('/api/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || 'No pudimos enviar el link. Intentá de nuevo en unos minutos.')
      }
      setForgotSent(true)
    } catch (ex) {
      setError(ex.message)
    } finally {
      setForgotLoading(false)
    }
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setInfo('')
    setEmailExists(false)

    // ── Validación frontend pre-flight ────────────────────────────────────
    // Mensajes específicos para errores de input ANTES de pegarle al backend.
    // Evitan que el user vea "credenciales inválidas" cuando el problema real
    // es que no completó algo o el email no tiene formato válido.
    const cleanEmail = email.trim()
    if (!cleanEmail) {
      setError('Ingresá tu email para continuar.')
      return
    }
    // Regex simple — no exhaustivo pero detecta los typos comunes (sin @,
    // sin dominio, sin TLD). El backend hace la validación estricta.
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
      setError('El email no tiene formato válido. Revisalo y probá de nuevo.')
      return
    }
    if (!password) {
      setError('Ingresá tu contraseña para continuar.')
      return
    }
    if (mode === 'register' && password.length < 10) {
      setError('La contraseña debe tener al menos 10 caracteres.')
      return
    }
    if (mode === 'register' && !name.trim()) {
      setError('Ingresá tu nombre para crear la cuenta.')
      return
    }

    setLoading(true)
    try {
      const endpoint = mode === 'login' ? '/api/auth/login' : '/api/auth/register'
      const body = mode === 'login' ? { email: cleanEmail, password } : { email: cleanEmail, password, name: name.trim() }
      let res
      // Timeout de 20s: si Railway está en cold start y tarda demasiado, en vez
      // de dejar el botón en "Cargando…" indefinidamente damos un mensaje claro
      // para que el visitante reintente en lugar de abandonar.
      const ctrl = new AbortController()
      const timeoutId = setTimeout(() => ctrl.abort(), 20000)
      try {
        res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: ctrl.signal,
        })
      } catch (netErr) {
        // Falla de red — no llegó al server. Distinguir esto del "credenciales
        // inválidas" es crítico: el user piensa que el password está mal
        // cuando en realidad no hay internet o el server está caído.
        if (netErr.name === 'AbortError') {
          throw new Error('El servidor está tardando más de lo normal. Esperá unos segundos y probá de nuevo.')
        }
        throw new Error('No hay conexión con el servidor. Revisá tu internet y probá de nuevo.')
      } finally {
        clearTimeout(timeoutId)
      }

      let data = {}
      try {
        data = await res.json()
      } catch {
        // Response no es JSON — probablemente HTML de error de Vercel/Cloudflare
        if (res.status >= 500) {
          throw new Error('El servidor está teniendo problemas. Probá de nuevo en un minuto.')
        }
        throw new Error('Respuesta inesperada del servidor. Probá de nuevo.')
      }

      if (!res.ok) {
        // ── Caso especial: email no verificado → redirect a /verify-email ──
        if (res.status === 403 && data?.detail?.code === 'EMAIL_NOT_VERIFIED') {
          navigate(`/verify-email?email=${encodeURIComponent(data.detail.email || cleanEmail)}`)
          return
        }
        // ── Caso especial: register con email ya registrado → CTA "ir a login" ──
        if (res.status === 409 && data?.detail?.code === 'EMAIL_ALREADY_REGISTERED') {
          setEmailExists(true)
          return
        }

        // ── Mensajes contextuales por status code ──
        // Importante: NO podemos distinguir entre "email no existe" vs
        // "password mal" porque el backend devuelve el mismo 401 para ambos
        // (anti-enumeration de cuentas). Pero SÍ mejoramos el copy para que
        // el user entienda mejor qué chequear.
        let friendly
        if (res.status === 401) {
          friendly = mode === 'login'
            ? 'El email o la contraseña no coinciden. Revisá que estén bien escritos — si olvidaste tu contraseña, podés resetearla con el link de arriba.'
            : 'Las credenciales no son válidas.'
        } else if (res.status === 403) {
          // Acceso denegado (ej.: registro deshabilitado). El caso de email
          // sin verificar se maneja arriba con redirect a /verify-email.
          const backendMsg = typeof data.detail === 'string' ? data.detail : (data.detail?.error || data.detail?.message)
          friendly = backendMsg || 'No pudimos completar la acción. Probá de nuevo en un momento.'
        } else if (res.status === 429) {
          friendly = 'Demasiados intentos. Esperá un minuto antes de intentar de nuevo.'
        } else if (res.status === 422 || res.status === 400) {
          // Validation error del backend (Pydantic, etc.)
          const backendMsg = typeof data.detail === 'string'
            ? data.detail
            : Array.isArray(data.detail)
              ? data.detail.map(d => d.msg || d).join('; ')
              : (data.detail?.error || data.detail?.message)
          friendly = backendMsg || 'Algunos datos no son válidos. Revisá el formulario.'
        } else if (res.status >= 500) {
          friendly = 'El servidor está teniendo problemas. Probá de nuevo en un minuto.'
        } else {
          // Fallback: usar el detail del backend si es legible
          const backendMsg = typeof data.detail === 'string' ? data.detail : (data.detail?.error || data.detail?.message)
          friendly = backendMsg || `Algo salió mal (código ${res.status}). Probá de nuevo.`
        }
        throw new Error(friendly)
      }
      // Registro con verificación pendiente → llevar a /verify-email
      if (data.needs_verification) {
        // Señal de mid-funnel para Meta/GA4: el signup se completó (falta el
        // OTP). Meta optimiza mucho mejor con un evento temprano y frecuente
        // como 'Lead' que con solo CompleteRegistration (post-OTP, mucho más
        // raro). CompleteRegistration se dispara después en AuthContext cuando
        // el user verifica el email.
        trackMetaEvent('Lead', { content_name: 'signup_submitted' })
        trackEvent('sign_up_submitted', { method: 'email' })
        navigate(`/verify-email?email=${encodeURIComponent(data.email || cleanEmail)}`)
        return
      }
      login(data.token, data.name, { is_admin: !!data.is_admin })
      navigate('/')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const inputClass = 'w-full bg-bg-2 dark:bg-bg-2 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 placeholder-ink-3 dark:placeholder-ink-3 focus:outline-none focus:border-rendi-accent focus:ring-2 focus:ring-rendi-accent/20 transition-colors'

  return (
    <div className="min-h-screen bg-bg-2 dark:bg-bg-0 flex items-center justify-center px-4">
      <PageMeta
        title="Iniciar sesión — Rendi"
        description="Accedé a tu cuenta de Rendi para ver tu portfolio multi-broker."
        canonical="/login"
        noindex={true}
      />
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-center gap-3 mb-8">
          <RendiLogo size={36} />
          <span className="text-2xl font-bold text-ink-0 dark:text-white tracking-tight">rendi</span>
        </div>

        {/* Demo mode CTA — entry point para probar sin cuenta */}
        <button
          onClick={() => {
            track('demo_mode_started')
            enableDemoMode()
            // Forzar reload para que AuthContext detecte el flag y monte el demo user
            window.location.href = '/'
          }}
          className="w-full mb-4 inline-flex items-center justify-center gap-2 bg-data-violet/10 hover:bg-data-violet/15 text-data-violet border border-data-violet/30 rounded-lg py-2.5 text-sm transition-colors"
        >
          <Sparkles size={14} strokeWidth={1.75} />
          Probar sin cuenta · Modo demo
          <ArrowRight size={13} strokeWidth={1.75} />
        </button>

        <div className="bg-white dark:bg-bg-2/60 border border-line/50 rounded-2xl p-6">
          <div className="flex mb-6 bg-bg-2 dark:bg-bg-1/60 rounded-lg p-1">
            <button
              onClick={() => { setMode('login'); setEmailExists(false); setError(''); }}
              className={`flex-1 py-1.5 rounded-md text-sm font-medium transition-colors ${
                mode === 'login' ? 'bg-blue-600 text-white' : 'text-ink-3 hover:text-ink-0 dark:hover:text-ink-0'
              }`}
            >
              Iniciar sesión
            </button>
            <button
              onClick={() => { setMode('register'); setEmailExists(false); setError(''); }}
              className={`flex-1 py-1.5 rounded-md text-sm font-medium transition-colors ${
                mode === 'register' ? 'bg-blue-600 text-white' : 'text-ink-3 hover:text-ink-0 dark:hover:text-ink-0'
              }`}
            >
              Registrarse
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            {mode === 'register' && (
              <div>
                <label htmlFor="login-name" className="block text-xs text-ink-3 mb-1">Nombre</label>
                <input
                  id="login-name"
                  type="text"
                  name="name"
                  autoComplete="name"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="Cómo querés que te llamemos"
                  className={inputClass}
                />
              </div>
            )}
            <div>
              <label htmlFor="login-email" className="block text-xs text-ink-3 mb-1">Email</label>
              <input
                id="login-email"
                type="email"
                name="email"
                autoComplete="email"
                inputMode="email"
                spellCheck={false}
                autoCapitalize="none"
                autoCorrect="off"
                value={email}
                onChange={e => { setEmail(e.target.value); if (emailExists) setEmailExists(false) }}
                placeholder="tu@email.com"
                className={inputClass}
              />
            </div>
            <div>
              <div className="flex items-baseline justify-between mb-1">
                <label htmlFor="login-password" className="block text-xs text-ink-3">Contraseña</label>
                {mode === 'login' && (
                  <button
                    type="button"
                    onClick={() => { setForgotMode(true); setError(''); setForgotSent(false); }}
                    className="text-xs text-data-violet hover:text-data-violet/80 transition-colors"
                  >
                    ¿Olvidaste tu contraseña?
                  </button>
                )}
              </div>
              {/* Password con toggle "ver contraseña". El botón se posiciona
                  absoluto sobre el lado derecho del input. Ayuda al user mobile
                  a verificar que tipeó bien la pass (resuelve la causa #1 de
                  "credenciales inválidas" reportada). */}
              <div className="relative">
                <input
                  id="login-password"
                  type={showPassword ? 'text' : 'password'}
                  name="password"
                  autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  minLength={mode === 'register' ? 10 : undefined}
                  placeholder={mode === 'register' ? 'Mínimo 10 caracteres' : '••••••••'}
                  className={`${inputClass} pr-10`}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(s => !s)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-ink-3 hover:text-ink-0 transition-colors"
                  aria-label={showPassword ? 'Ocultar contraseña' : 'Ver contraseña'}
                  tabIndex={-1}
                >
                  {showPassword
                    ? <EyeOff size={16} strokeWidth={1.75} />
                    : <Eye size={16} strokeWidth={1.75} />}
                </button>
              </div>
              {mode === 'register' && password && password.length < 10 && (
                <p className="text-xs text-amber-500 dark:text-amber-400 mt-1">Faltan caracteres · {password.length}/10</p>
              )}
            </div>
            {/* Aviso especial: email ya registrado al intentar signup. En vez
                del mensaje de error suelto, mostramos un panel con CTA a login. */}
            {emailExists && (
              <div className="bg-data-violet/10 border border-data-violet/30 rounded-lg p-3 space-y-2">
                <p className="text-sm text-ink-1">
                  <b className="text-data-violet">{email}</b> ya está registrado en Rendi.
                </p>
                <p className="text-xs text-ink-3 leading-relaxed">
                  ¿Es tu cuenta? Iniciá sesión con tu contraseña. Si la olvidaste, contactanos.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setMode('login')
                    setEmailExists(false)
                    setError('')
                    // Email queda pre-cargado para que solo tipee el password
                  }}
                  className="w-full inline-flex items-center justify-center gap-1.5 bg-data-violet text-white rounded-lg py-2 text-sm font-medium hover:bg-data-violet/90 transition-colors press"
                >
                  Iniciar sesión con {email}
                  <ArrowRight size={13} strokeWidth={1.75} />
                </button>
              </div>
            )}
            {/* Panel: Olvidé mi contraseña (mini-flow inline, sin página extra) */}
            {forgotMode && (
              <div className="bg-bg-2 dark:bg-bg-1/60 border border-line/60 rounded-lg p-3 space-y-2.5">
                {forgotSent ? (
                  <>
                    <p className="text-sm text-ink-0 font-medium">Revisá tu correo</p>
                    <p className="text-xs text-ink-3 leading-relaxed">
                      Si <b className="text-ink-1">{email}</b> está registrado, te enviamos un link para
                      restablecer tu contraseña. El link vence en 30 minutos.
                    </p>
                    <button
                      type="button"
                      onClick={() => { setForgotMode(false); setForgotSent(false); }}
                      className="w-full text-xs text-ink-3 hover:text-ink-0 py-1.5 transition-colors"
                    >
                      Volver al login
                    </button>
                  </>
                ) : (
                  <>
                    <p className="text-sm text-ink-1">
                      ¿Olvidaste tu contraseña?
                    </p>
                    <p className="text-xs text-ink-3 leading-relaxed">
                      Te mandamos un link a tu email para crear una nueva. Asegurate
                      de tener tu email <b className="text-ink-2">{email || 'arriba'}</b> bien escrito.
                    </p>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={handleForgotPassword}
                        disabled={forgotLoading || !email.trim()}
                        className="flex-1 inline-flex items-center justify-center gap-1.5 bg-data-violet hover:bg-data-violet/90 text-white rounded-lg py-2 text-xs font-medium transition-colors disabled:opacity-50"
                      >
                        {forgotLoading ? 'Enviando…' : 'Enviar link de reseteo'}
                      </button>
                      <button
                        type="button"
                        onClick={() => { setForgotMode(false); setError(''); }}
                        className="px-3 text-xs text-ink-3 hover:text-ink-0 transition-colors"
                      >
                        Cancelar
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
            {error && !emailExists && <p className="text-red-500 text-xs">{error}</p>}
            {info && <p className="text-emerald-600 dark:text-emerald-400 text-xs">{info}</p>}
            <button
              type="submit"
              disabled={loading || emailExists || forgotMode}
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg py-2.5 text-sm font-medium transition-colors"
            >
              {loading ? 'Cargando…' : mode === 'login' ? 'Iniciar sesión' : 'Crear cuenta'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
