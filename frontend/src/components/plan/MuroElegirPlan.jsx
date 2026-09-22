// MuroElegirPlan — la pantalla del día 21 para el que nació sin plan gratis.
// ════════════════════════════════════════════════════════════════════════════
// Se terminó su prueba de 20 días y no eligió un plan, así que la cuenta queda
// EN PAUSA. Esta pantalla es la única salida: elegir un plan, o cerrar sesión.
//
// Tres decisiones de diseño que son la pantalla, no adorno:
//
//   1. NO tiene botón de cerrar, y no se cierra con Escape ni clickeando
//      afuera. Un muro que se puede esquivar se esquiva, y el backend igual
//      va a contestar 402 en todo lo de atrás: dejarlo cerrar sólo produce
//      una app llena de errores rojos sin explicación.
//   2. La app se ve DESENFOCADA detrás. Lo que más espanta no es el precio,
//      es el miedo a haber perdido lo cargado; mostrar la cartera atrás dice
//      "está todo acá" mejor que cualquier frase.
//   3. Pro va marcado como "el que usaste los primeros 10 días" y en celular
//      va ARRIBA de Plus: le estamos pidiendo que elija justo lo que probó.
//
// El muro REAL lo aplica el backend (402 `plan_requerido` en cualquier
// endpoint de datos, desde `get_effective_user`). Esto es la cara visible.
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { track } from '../../utils/track'
import {
  fmtArs, annualSavingsArs, ANNUAL_DISCOUNT_BADGE_PCT,
  PLUS_PRICE_ARS_MONTHLY, PRO_PRICE_ARS_MONTHLY,
  PLUS_PRICE_ARS_ANNUAL, PRO_PRICE_ARS_ANNUAL,
  PLUS_PRICE_ARS_ANNUAL_MONTHLY_EQ, PRO_PRICE_ARS_ANNUAL_MONTHLY_EQ,
} from '../../pages/Planes'

const PLANES = {
  plus: {
    nombre: 'Plus',
    bajada: 'Todos tus brokers en un lugar',
    mensual: PLUS_PRICE_ARS_MONTHLY,
    anualEq: PLUS_PRICE_ARS_ANNUAL_MONTHLY_EQ,
    anualTotal: PLUS_PRICE_ARS_ANNUAL,
    features: [
      'Brokers ilimitados y consolidado',
      'Cartera, movimientos y reportes',
      'Rendimiento vs inflación y S&P 500',
      '20 análisis de IA por semana',
    ],
  },
  pro: {
    nombre: 'Pro',
    bajada: 'Todo, sin límite de análisis',
    mensual: PRO_PRICE_ARS_MONTHLY,
    anualEq: PRO_PRICE_ARS_ANNUAL_MONTHLY_EQ,
    anualTotal: PRO_PRICE_ARS_ANNUAL,
    features: [
      'Todo lo de Plus, más:',
      'Análisis de IA sin límite',
      'Calidad de cartera y calendario de cobros',
      'Informe del período y carpeta de impuestos',
    ],
  },
}

function TarjetaPlan({ plan, anual, destacado, onElegir }) {
  const p = PLANES[plan]
  const precio = anual ? p.anualEq : p.mensual
  return (
    <div className={`relative flex flex-col rounded-xl border p-6 bg-bg-1 ${
      destacado ? 'border-data-violet' : 'border-line'}`}>
      {destacado && (
        <div className="absolute -top-2.5 left-6 rounded px-2 py-0.5 bg-data-violet
                        text-[11px] font-bold text-bg-0">
          El que usaste los primeros 10 días
        </div>
      )}
      <div className="text-[15px] font-semibold text-ink-0">{p.nombre}</div>
      <div className="mt-1 text-[12.5px] text-ink-3">{p.bajada}</div>

      <div className="mt-4 flex items-baseline gap-1.5">
        <span className="text-[34px] font-semibold tracking-tight tabular text-ink-0">
          ${fmtArs(precio)}
        </span>
        <span className="text-[13px] text-ink-2">por mes</span>
      </div>
      <div className="mt-1 min-h-[17px] text-[12px] text-ink-3">
        {anual
          ? `Facturado anual ($${fmtArs(p.anualTotal)}) · ahorrás $${fmtArs(annualSavingsArs(plan))}`
          : ''}
      </div>

      <div className="my-5 h-px bg-line" />

      <div className="flex flex-grow flex-col gap-2.5">
        {p.features.map((f, i) => (
          <div key={f} className={`text-[13px] ${i === 0 && plan === 'pro' ? 'text-ink-0' : 'text-ink-2'}`}>
            {f}
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={() => onElegir(plan)}
        className={`mt-5 flex min-h-[44px] items-center justify-center rounded-lg
                    text-sm font-semibold transition-colors ${
          destacado
            ? 'bg-data-violet text-bg-0 hover:bg-rendi-violet-hover'
            : 'border border-line-2 bg-bg-2 text-ink-0 hover:bg-bg-3'}`}
      >
        Elegir {p.nombre}
      </button>
    </div>
  )
}

export default function MuroElegirPlan({ anual, onCambiarPeriodo, resumen }) {
  const navigate = useNavigate()
  const { logout } = useAuth()

  useEffect(() => { track('paywall_muro_visto') }, [])

  const elegir = (plan) => {
    track('paywall_muro_elegir', { plan, period: anual ? 'annual' : 'monthly' })
    navigate(`/planes?plan=${plan}&period=${anual ? 'annual' : 'monthly'}`)
  }

  return (
    // role="dialog" + aria-modal: para un lector de pantalla esto ES la
    // pantalla, no una capa encima de otra cosa navegable.
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="muro-titulo"
      className="fixed inset-0 z-[100] flex items-center justify-center
                 overflow-y-auto bg-bg-0/[0.92] p-4 sm:p-10"
    >
      <div className="w-full max-w-[880px] rounded-xl border border-line bg-bg-1
                      p-6 sm:p-10">
        <div className="text-center">
          <div className="mb-4 inline-flex items-center rounded-full bg-data-violet/[0.12]
                          px-3 py-1.5">
            <span className="text-[11.5px] font-semibold uppercase tracking-wide
                             text-data-violet">
              Terminaron tus 20 días
            </span>
          </div>
          <h1 id="muro-titulo"
              className="mb-2.5 text-[25px] font-semibold leading-tight tracking-tight
                         text-ink-0 sm:text-[32px]">
            Elegí un plan para seguir<br className="hidden sm:inline" />
            {' '}organizando tus inversiones
          </h1>
          {/* El resumen es SUYO: "4 brokers y 312 movimientos" convence de que
              no se perdió nada mucho más que la palabra "guardado". Si no lo
              tenemos, se omite antes que decir un número inventado. */}
          <p className="mx-auto max-w-[520px] text-[14px] leading-relaxed text-ink-2">
            {resumen
              ? <>Tus <b className="text-ink-0">{resumen}</b> quedaron guardados.
                  Elegí un plan y seguís donde estabas.</>
              : <>Todo lo que cargaste quedó guardado. Elegí un plan y seguís
                  donde estabas.</>}
          </p>
        </div>

        <div className="my-6 flex justify-center">
          <div className="inline-flex rounded-lg border border-line bg-bg-2 p-[3px]">
            <button type="button" onClick={() => onCambiarPeriodo(false)}
              className={`inline-flex min-h-[38px] items-center rounded px-4
                          text-[13px] transition-colors ${
                anual ? 'font-medium text-ink-2' : 'bg-bg-3 font-semibold text-ink-0'}`}>
              Mensual
            </button>
            <button type="button" onClick={() => onCambiarPeriodo(true)}
              className={`inline-flex min-h-[38px] items-center gap-1.5 rounded px-4
                          text-[13px] transition-colors ${
                anual ? 'bg-bg-3 font-semibold text-ink-0' : 'font-medium text-ink-2'}`}>
              Anual
              <span className="rounded bg-rendi-pos/15 px-1.5 py-px text-[11.5px]
                               font-semibold text-rendi-pos">
                −{ANNUAL_DISCOUNT_BADGE_PCT}%
              </span>
            </button>
          </div>
        </div>

        {/* En celular Pro va PRIMERO (order) — es el que probó. */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="order-2 sm:order-1">
            <TarjetaPlan plan="plus" anual={anual} onElegir={elegir} />
          </div>
          <div className="order-1 sm:order-2">
            <TarjetaPlan plan="pro" anual={anual} destacado onElegir={elegir} />
          </div>
        </div>

        <div className="mt-6 flex flex-col items-start justify-between gap-4
                        border-t border-line pt-5 sm:flex-row sm:items-center">
          <p className="max-w-[520px] text-[12px] leading-relaxed text-ink-3">
            Se cobra en pesos con tarjeta. Cancelás cuando quieras desde
            Configuración y no se vuelve a cobrar. Si no elegís ahora, tus datos
            quedan guardados — volvés cuando quieras.
          </p>
          <button
            type="button"
            onClick={logout}
            className="min-h-[44px] shrink-0 text-[12.5px] text-ink-3 underline
                       decoration-dotted underline-offset-2 hover:text-ink-2"
          >
            Salir de mi cuenta
          </button>
        </div>
      </div>
    </div>
  )
}
