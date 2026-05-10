// Toast — sistema de notificaciones in-app que reemplaza alert() del browser.
// alert() bloquea el thread y se ve "Windows 95"; los toasts custom son la
// convención fintech (Stripe, Linear, Vercel, Wealthfront).
//
// Patrón:
// - <ToastProvider> envuelve la app en main.jsx / App.jsx
// - useToast() hook expone push(message, options)
// - Toast aparece bottom-right, se autodestruye en 4s (override en options.duration)
// - Tipos: 'info' | 'success' | 'error' | 'warn' (afectan color del border)
// - aria-live="polite" para anuncio por screen readers
// - Honra prefers-reduced-motion (sin animación de slide)

import { createContext, useCallback, useContext, useState, useEffect, useRef } from 'react'
import { CheckCircle2, AlertTriangle, AlertCircle, Info, X } from 'lucide-react'

const ToastContext = createContext(null)

const TYPE_CONFIG = {
  info:    { Icon: Info,          accent: 'border-l-rendi-accent text-rendi-accent' },
  success: { Icon: CheckCircle2,  accent: 'border-l-rendi-pos text-rendi-pos' },
  error:   { Icon: AlertCircle,   accent: 'border-l-rendi-neg text-rendi-neg' },
  warn:    { Icon: AlertTriangle, accent: 'border-l-rendi-warn text-rendi-warn' },
}

let toastIdCounter = 0

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  // push(message, { type?, duration? })
  // Devuelve el id por si el caller quiere dismissear manualmente.
  const push = useCallback((message, options = {}) => {
    const id = ++toastIdCounter
    const type = options.type || 'info'
    const duration = options.duration ?? 4000
    setToasts(t => [...t, { id, message, type, duration }])
    return id
  }, [])

  const dismiss = useCallback((id) => {
    setToasts(t => t.filter(toast => toast.id !== id))
  }, [])

  const ctx = { push, dismiss }
  return (
    <ToastContext.Provider value={ctx}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) {
    // Fallback silencioso si el provider no está montado — evita crashes
    // en tests o storybook. En esos casos, log a consola.
    return {
      push: (msg, opts) => { console.log('[Toast]', opts?.type || 'info', msg) },
      dismiss: () => {},
    }
  }
  return ctx
}

function ToastContainer({ toasts, onDismiss }) {
  if (toasts.length === 0) return null
  return (
    <div
      role="region"
      aria-label="Notificaciones"
      className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 max-w-[calc(100vw-2rem)] sm:max-w-sm pointer-events-none"
    >
      {toasts.map(t => (
        <ToastItem key={t.id} toast={t} onDismiss={() => onDismiss(t.id)} />
      ))}
    </div>
  )
}

function ToastItem({ toast, onDismiss }) {
  const { Icon, accent } = TYPE_CONFIG[toast.type] || TYPE_CONFIG.info
  const timerRef = useRef(null)

  useEffect(() => {
    if (toast.duration > 0) {
      timerRef.current = setTimeout(onDismiss, toast.duration)
    }
    return () => clearTimeout(timerRef.current)
  }, [toast.duration, onDismiss])

  return (
    <div
      role="status"
      aria-live="polite"
      className={`pointer-events-auto flex items-start gap-3 px-4 py-3 rounded bg-white dark:bg-bg-1 border border-slate-200 dark:border-line border-l-4 ${accent} shadow-lg dark:shadow-2xl animate-[slide-in_0.2s_ease-out] motion-reduce:animate-none`}
      style={{
        // Inline keyframes para no tocar tailwind config
        animationFillMode: 'both',
      }}
    >
      <Icon size={16} strokeWidth={1.75} className="flex-shrink-0 mt-0.5" aria-hidden="true" />
      <p className="flex-1 min-w-0 text-sm leading-snug text-slate-800 dark:text-ink-1">
        {toast.message}
      </p>
      <button
        onClick={onDismiss}
        className="flex-shrink-0 text-ink-3 hover:text-ink-0 -mt-0.5 -mr-1 p-1"
        aria-label="Cerrar notificación"
      >
        <X size={14} strokeWidth={1.75} aria-hidden="true" />
      </button>
    </div>
  )
}
