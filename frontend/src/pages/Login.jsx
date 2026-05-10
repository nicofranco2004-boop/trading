import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import RendiLogo from '../components/RendiLogo'

export default function Login() {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setInfo('')
    setLoading(true)
    try {
      const endpoint = mode === 'login' ? '/api/auth/login' : '/api/auth/register'
      const body = mode === 'login' ? { email, password } : { email, password, name }
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      let data
      try {
        data = await res.json()
      } catch {
        throw new Error('No pudimos contactar el servidor. Verificá que el backend esté corriendo en el puerto 8000.')
      }
      if (!res.ok) throw new Error(data.detail || 'Ocurrió un error')
      // Registro pendiente: el admin debe aprobar
      if (data.pending) {
        setInfo(data.message || 'Cuenta creada. Pendiente de aprobación.')
        setMode('login')
        setPassword('')
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

  const inputClass = 'w-full bg-slate-50 dark:bg-bg-2 border border-slate-300 dark:border-line rounded-lg px-3 py-2 text-sm text-slate-900 dark:text-ink-0 placeholder-slate-400 dark:placeholder-ink-3 focus:outline-none focus:border-rendi-accent focus:ring-2 focus:ring-rendi-accent/20 transition-colors'

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-center gap-3 mb-8">
          <RendiLogo size={36} />
          <span className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">rendi</span>
        </div>

        <div className="bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/50 rounded-2xl p-6">
          <div className="flex mb-6 bg-slate-100 dark:bg-slate-900/60 rounded-lg p-1">
            <button
              onClick={() => setMode('login')}
              className={`flex-1 py-1.5 rounded-md text-sm font-medium transition-colors ${
                mode === 'login' ? 'bg-blue-600 text-white' : 'text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
              }`}
            >
              Iniciar sesión
            </button>
            <button
              onClick={() => setMode('register')}
              className={`flex-1 py-1.5 rounded-md text-sm font-medium transition-colors ${
                mode === 'register' ? 'bg-blue-600 text-white' : 'text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
              }`}
            >
              Registrarse
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            {mode === 'register' && (
              <div>
                <label htmlFor="login-name" className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Nombre</label>
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
              <label htmlFor="login-email" className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Email</label>
              <input
                id="login-email"
                type="email"
                name="email"
                autoComplete="email"
                inputMode="email"
                spellCheck={false}
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="tu@email.com"
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="login-password" className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Contraseña</label>
              <input
                id="login-password"
                type="password"
                name="password"
                autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                minLength={mode === 'register' ? 10 : undefined}
                placeholder={mode === 'register' ? 'Mínimo 10 caracteres' : '••••••••'}
                className={inputClass}
              />
              {mode === 'register' && password && password.length < 10 && (
                <p className="text-xs text-amber-500 dark:text-amber-400 mt-1">Faltan caracteres · {password.length}/10</p>
              )}
            </div>
            {error && <p className="text-red-500 text-xs">{error}</p>}
            {info && <p className="text-emerald-600 dark:text-emerald-400 text-xs">{info}</p>}
            <button
              type="submit"
              disabled={loading}
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
