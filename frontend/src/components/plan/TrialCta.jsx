// Free trial de 15 días — el botón y el estado, en un solo lugar.
// ═══════════════════════════════════════════════════════════════════════════
// El backend manda todo resuelto en /api/plan/features → trial:
//   { active, used, can_start, stage: 'pro'|'plus', days_left, days_to_switch }
// Acá NO se decide elegibilidad ni se calculan fechas: si el server dice que
// no se puede, no se ofrece. Duplicar esa lógica en el front es cómo se
// terminan mostrando botones que fallan al apretarlos.
//
// Se usa en tres lugares: los paywalls (TrialCta), la barra de la app
// (TrialBanner) y al terminar el primer import — que es el mejor momento,
// porque recién ahí la app tiene datos adentro y el trial demuestra algo.

import { useState } from 'react'
import { Sparkles, Loader2 } from 'lucide-react'
import { api } from '../../utils/api'
import { usePlanFeatures, refreshPlanFeatures } from '../../hooks/usePlanFeatures'
import { track } from '../../utils/track'
import { useToast } from '../Toast'

export const TRIAL_TOTAL_DAYS = 15
export const TRIAL_PRO_DAYS = 7

// Traducción de los códigos del backend. 'already_used' no está: cuando ya lo
// usó no se muestra nada (ver TrialCta), no un cartel de error.
const REASONS = {
  email_not_verified: 'Verificá tu email para activar la prueba.',
  already_paying: 'Ya tenés un plan activo.',
  already_premium: 'Ya tenés un plan activo.',
  monthly_cap_reached: 'Se agotaron las pruebas gratis de este mes. Escribinos y te damos una mano.',
  disabled: 'La prueba gratis no está disponible por ahora.',
}

/** ¿Se ofrece el trial? SOLO lo decide el backend — no recalculamos
 *  elegibilidad en el front (así es como se muestran botones que fallan). */
export function canOfferTrial(trial) {
  return !!trial?.can_start
}

/** El aviso del banner, o null si no hay nada urgente que decir.
 *  El aviso ANTES del cambio es el que sirve: le da tiempo a usar lo que está
 *  por perder y a decidir. Después ya es la notificación de algo consumado. */
export function trialNotice(trial) {
  if (!trial?.active) return null
  const { stage, days_left: left, days_to_switch: toSwitch } = trial
  if (stage === 'pro' && toSwitch != null && toSwitch <= 1) {
    return 'Mañana pasás a Plus: aprovechá hoy el chat libre y los análisis.'
  }
  if (left != null && left <= 2) {
    return `Te ${left === 1 ? 'queda 1 día' : `quedan ${left} días`} de prueba.`
  }
  return null
}

/** Texto de días restantes para el encabezado del banner. */
export function trialDaysLabel(days) {
  if (days == null) return null
  return days === 1 ? 'último día' : `${days} días restantes`
}

/** Botón "Probar gratis". No renderiza NADA si el server no lo habilita. */
export function TrialCta({ source = 'paywall', className = '', onStarted }) {
  const { trial } = usePlanFeatures()
  const [busy, setBusy] = useState(false)
  const toast = useToast()

  if (!canOfferTrial(trial)) return null

  async function start() {
    if (busy) return
    setBusy(true)
    track('trial_start_clicked', { source })
    try {
      await api.post('/billing/trial/start')
      // El tier cambió: sin esto la app sigue mostrando los candados de Free
      // hasta el próximo refresh.
      await refreshPlanFeatures()
      window.dispatchEvent(new Event('rendi:portfolio-changed'))
      track('trial_started', { source })
      toast.push(
        `Listo: tenés ${TRIAL_PRO_DAYS} días de Pro y después ${TRIAL_TOTAL_DAYS - TRIAL_PRO_DAYS} de Plus.`,
        { type: 'success' })
      onStarted?.()
    } catch (e) {
      // El 409 trae el motivo del server; cualquier otra cosa es un problema
      // nuestro y no del usuario.
      const reason = e?.payload?.detail || e?.message || ''
      toast.push(REASONS[reason] || 'No pudimos activar la prueba. Probá de nuevo en un minuto.',
                 { type: 'error' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <button
      type="button"
      onClick={start}
      disabled={busy}
      className={className || 'w-full inline-flex items-center justify-center gap-1.5 text-sm font-medium bg-data-violet hover:bg-rendi-violet-hover text-white rounded-sm py-2.5 transition-colors disabled:opacity-60'}
    >
      {busy
        ? <><Loader2 size={13} className="animate-spin" /> Activando…</>
        : <><Sparkles size={13} strokeWidth={1.75} /> Probar gratis {TRIAL_TOTAL_DAYS} días</>}
    </button>
  )
}

/** La letra chica del trial. Aclara que no se pide tarjeta y qué pasa después. */
export function TrialFinePrint({ className = '' }) {
  const { trial } = usePlanFeatures()
  if (!canOfferTrial(trial)) return null
  return (
    <p className={className || 'mt-2 text-[10px] text-ink-3 text-center leading-relaxed'}>
      Sin tarjeta. Los primeros {TRIAL_PRO_DAYS} días con todo Pro y los{' '}
      {TRIAL_TOTAL_DAYS - TRIAL_PRO_DAYS} siguientes con Plus.
    </p>
  )
}

/** Barra de estado mientras el trial corre. Null si no hay trial activo. */
export function TrialBanner({ onSeePlans }) {
  const { trial } = usePlanFeatures()
  if (!trial?.active) return null

  const { stage, days_left: left } = trial
  const plan = stage === 'plus' ? 'Plus' : 'Pro'
  const aviso = trialNotice(trial)
  const diasLabel = trialDaysLabel(left)

  return (
    <div className="mb-4 rounded-lg border border-data-violet/40 bg-data-violet/[0.07] px-3.5 py-2.5">
      <div className="flex items-center gap-2.5 flex-wrap">
        <Sparkles size={14} strokeWidth={1.75} className="text-data-violet flex-shrink-0" />
        <p className="text-sm text-ink-0 font-medium">
          Estás probando Rendi {plan}
          {diasLabel && (
            <span className="text-ink-2 font-normal">{' · '}{diasLabel}</span>
          )}
        </p>
        <button
          type="button"
          onClick={() => { track('trial_banner_plans_clicked', { stage }); onSeePlans?.() }}
          className="ml-auto text-xs font-medium text-data-violet hover:underline"
        >
          Ver planes
        </button>
      </div>
      {aviso && <p className="text-xs text-ink-2 mt-1 pl-6">{aviso}</p>}
    </div>
  )
}
