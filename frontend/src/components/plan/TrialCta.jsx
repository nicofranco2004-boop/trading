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
import { useNavigate, useLocation } from 'react-router-dom'
import { Sparkles, Loader2, ArrowRight } from 'lucide-react'
import { api } from '../../utils/api'
import InfoTooltip from '../InfoTooltip'
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

/** Cuánto le queda de la etapa Pro, como frase. '' si no hay dato.
 *  Vive acá, al lado de trialNotice, para que /config y la barra no puedan
 *  contradecirse: el día que el cron todavía no corrió, days_to_switch llega en
 *  0 y /config decía "tenés Pro por 0 días más" mientras la barra —dos
 *  centímetros más arriba— decía "Mañana pasás a Plus". */
export function trialProStageLabel(toSwitch) {
  if (toSwitch == null) return ''
  if (toSwitch <= 1) return ' hasta mañana'
  return ` por ${toSwitch} días más`
}

/** Cuántos días le quedan, como frase entera para la barra. null si no hay dato.
 *  El día 0 no es "0 días": el trial sigue activo, le queda menos de uno. */
export function trialDaysLabel(days) {
  if (days == null) return null
  if (days <= 0) return 'Te queda menos de un día.'
  return days === 1 ? 'Te queda 1 día.' : `Te quedan ${days} días.`
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

/** La letra chica del trial + el (?) que explica las tres etapas.
 *
 *  Los días salen del SERVER (`pro_days`/`plus_days`/`total_days`), no de las
 *  constantes de acá: si mañana la prueba pasa a 5+10, el texto acompaña solo.
 *  Hardcodear el 7 en la explicación es cómo se termina describiendo un plan
 *  que ya no existe. Las constantes quedan de respaldo por si el payload viene
 *  viejo. */
export function TrialFinePrint({ className = '' }) {
  const { trial } = usePlanFeatures()
  if (!canOfferTrial(trial)) return null

  const pro = trial?.pro_days ?? TRIAL_PRO_DAYS
  const plus = trial?.plus_days ?? (TRIAL_TOTAL_DAYS - TRIAL_PRO_DAYS)
  const total = trial?.total_days ?? TRIAL_TOTAL_DAYS

  // Contenedor <div> y no <p>: el tooltip abre un <div> flotante, y un <div>
  // adentro de un <p> es inválido → el navegador cierra el <p> por su cuenta,
  // React pierde el hilo del DOM y el popover no aparece nunca. El botón se ve
  // pero no hace nada, y ni los tests ni el build lo detectan.
  return (
    <div className={className || 'mt-2 text-[10px] text-ink-3 text-center leading-relaxed'}>
      Sin tarjeta. Los primeros {pro} días con todo Pro y los {plus} siguientes con Plus.
      {' '}
      <InfoTooltip label="Cómo funciona la prueba" size={11} align="center" side="top">
        <p className="font-medium text-ink-0">Cómo funciona la prueba</p>
        <TrialStage
          rango={pro === 1 ? 'Día 1' : `Días 1 a ${pro}`}
          plan="Rendi Pro"
          detalle="Todo desbloqueado: chat libre, el máximo de análisis y brokers ilimitados."
        />
        <TrialStage
          rango={`Días ${pro + 1} a ${total}`}
          plan="Rendi Plus"
          detalle="Seguís con multi-broker y las features avanzadas, con menos cuota de IA."
        />
        <TrialStage
          rango={`Día ${total + 1}`}
          plan="Volvés a Free"
          detalle="Tus datos quedan intactos. Si querés seguir con un plan, lo elegís vos."
        />
        <p className="text-ink-3 pt-1">
          No pedimos tarjeta y no se renueva sola: cuando termina no se te cobra nada.
        </p>
      </InfoTooltip>
    </div>
  )
}

/** Una etapa de la prueba dentro del tooltip. */
function TrialStage({ rango, plan, detalle }) {
  return (
    <span className="block pt-1.5">
      <span className="text-ink-3">{rango}</span>
      {' · '}
      <span className="text-ink-0 font-medium">{plan}</span>
      <span className="block text-ink-3">{detalle}</span>
    </span>
  )
}

/** Barra de estado mientras el trial corre. Null si no hay trial activo.
 *
 *  Va montada en el shell de la app (App.jsx), al lado del DemoBanner y con
 *  su misma forma: antes vivía SOLO en /planes, que es una pantalla a la que
 *  no entra nadie salvo que ya esté por pagar — o sea, el aviso del día 8
 *  ("mañana pasás a Plus") no lo veía prácticamente ninguno. El aviso in-app
 *  del cambio de etapa es la mitad del mecanismo del trial encadenado; si no
 *  se ve, el usuario pierde Pro sin enterarse de que lo tenía. */
export function TrialBanner({ onSeePlans }) {
  const { trial } = usePlanFeatures()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  if (!trial?.active) return null

  const { stage, days_left: left } = trial
  const plan = stage === 'plus' ? 'Plus' : 'Pro'
  const aviso = trialNotice(trial)
  const diasLabel = trialDaysLabel(left)
  // En /planes el botón no lleva a ningún lado nuevo.
  const enPlanes = pathname === '/planes'

  function verPlanes() {
    track('trial_banner_plans_clicked', { stage })
    if (onSeePlans) onSeePlans()
    else navigate('/planes')
  }

  return (
    <div className="sticky top-0 z-40 border-b border-data-violet/30 bg-bg-1/95 backdrop-blur-sm">
      <div className="flex items-center justify-between gap-3 px-4 py-2 max-w-7xl mx-auto">
        <div className="flex items-center gap-2 min-w-0">
          <Sparkles size={13} strokeWidth={1.75} className="text-data-violet flex-shrink-0" aria-hidden="true" />
          <p className="text-xs text-ink-1 min-w-0">
            <span className="font-medium text-ink-0">Estás probando Rendi {plan}.</span>
            {diasLabel && <span className="text-ink-3">{' '}{diasLabel}</span>}
            {aviso && <span className="text-ink-2">{' '}{aviso}</span>}
          </p>
        </div>
        {!enPlanes && (
          <button
            type="button"
            onClick={verPlanes}
            className="flex-shrink-0 inline-flex items-center gap-1 text-xs bg-data-violet/15 hover:bg-data-violet/25 text-data-violet border border-data-violet/30 px-3 py-1.5 rounded-sm transition-colors"
          >
            Ver planes
            <ArrowRight size={11} strokeWidth={2} />
          </button>
        )}
      </div>
    </div>
  )
}
