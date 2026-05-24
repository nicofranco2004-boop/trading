// Reembolso — política de reembolso de Rendi.
// ════════════════════════════════════════════════════════════════════════════
// Página pública (sin login). Linkeada desde Planes.jsx y desde Terminos.jsx.
//
// Política del negocio (decidida fuera de código):
//   - No devolvemos el monto del período ya cobrado.
//   - El user mantiene acceso pleno hasta el final del período pagado.
//   - Cancelar anula la renovación, no devuelve plata del período actual.
//   - Cambio de plan mid-período → crédito tiempo-based proporcional, sin
//     cobro adicional ni reembolso.
//   - Pagos fallidos / cargos accidentales → ver el caso a caso por email.

import { Link } from 'react-router-dom'
import RendiLogo from '../components/RendiLogo'

export default function Reembolso() {
  return (
    <div className="min-h-screen bg-bg-0 text-ink-0">
      <header className="border-b border-line">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 hover:opacity-90">
            <RendiLogo size={28} />
            <span className="font-semibold text-base tracking-tight">rendi</span>
          </Link>
          <Link to="/planes" className="text-sm text-ink-2 hover:text-ink-0">Volver a planes →</Link>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-12">
        <p className="font-mono text-[10px] uppercase tracking-caps text-ink-3 mb-2">Legal</p>
        <h1 className="text-3xl font-semibold tracking-tight mb-1">Política de reembolso</h1>
        <p className="text-sm text-ink-3 mb-10">Última actualización: 23 de mayo de 2026</p>

        {/* Resumen prominente */}
        <div className="border border-data-violet/40 bg-data-violet/[0.06] rounded-lg p-5 mb-10">
          <p className="text-[10px] font-mono uppercase tracking-caps text-data-violet mb-1.5">Resumen rápido</p>
          <ul className="text-sm text-ink-1 leading-relaxed space-y-1.5 list-disc pl-5 [&_li]:marker:text-data-violet">
            <li>No devolvemos el monto del período ya cobrado.</li>
            <li>Si cancelás, mantenés acceso a tu plan hasta el final del período.</li>
            <li>Cambiar de plan no genera cobro adicional ni reembolso — convertimos el crédito proporcionalmente.</li>
            <li>Excepciones (cobro duplicado, error técnico nuestro): se evalúan caso a caso.</li>
          </ul>
        </div>

        <Section title="1. Por qué esta política">
          <p>
            Rendi es un servicio de suscripción mensual o anual. Cuando pagás un
            período, te damos acceso pleno a todas las features del plan por toda
            la duración del período, sin importar cuánto lo uses.
          </p>
          <p>
            Esto significa que <strong className="text-ink-0">si cancelás a los 10 días
            de haber pagado un mes</strong>, no perdés el acceso — lo seguís teniendo
            los 20 días restantes. Por eso no devolvemos el dinero al cancelar: el
            servicio ya fue entregado por todo el período.
          </p>
        </Section>

        <Section title="2. Qué pasa cuando cancelás">
          <ol>
            <li>
              Tu suscripción deja de renovarse automáticamente.
            </li>
            <li>
              Conservás acceso completo a tu plan (Pro o Plus) hasta el final del
              período actual ya cobrado. La fecha exacta la ves en{' '}
              <Link to="/config" className="text-data-violet hover:underline">/config</Link>.
            </li>
            <li>
              Al expirar el período, tu cuenta pasa automáticamente a Free. No
              perdés tu información — seguís pudiendo ver y exportar tus datos
              históricos.
            </li>
            <li>
              Podés reactivar tu suscripción en cualquier momento desde{' '}
              <Link to="/planes" className="text-data-violet hover:underline">/planes</Link>.
            </li>
          </ol>
        </Section>

        <Section title="3. Qué pasa cuando cambiás de plan mid-período">
          <p>
            Si estás en Plus y te pasás a Pro (o viceversa) antes de que termine tu
            período, no te cobramos dos veces. Convertimos el crédito remanente al
            rate del plan nuevo.
          </p>
          <p>
            <strong className="text-ink-0">Ejemplo</strong>: pagaste Plus mensual el día 1.
            El día 10 te pasás a Pro. Pro vale ~2,25× lo que vale Plus mensual.
            Entonces los 20 días restantes que tenías comprados de Plus se
            convierten a ~9 días de Pro. Cuando se acabe ese crédito (día 19), te
            volvemos a cobrar Pro normal y seguís autoritario.
          </p>
          <p>
            <strong className="text-ink-0">Si bajás de plan</strong> (ej. Pro → Plus),
            el crédito remanente te alcanza para más días en el plan menor — los días
            equivalentes a tu compra original.
          </p>
          <p>
            <strong className="text-ink-0">No hay reembolso en cambio de plan.</strong>{' '}
            Lo que tenés comprado se transforma en acceso al plan nuevo. Vas a ver el
            cálculo exacto antes de confirmar el cambio en{' '}
            <Link to="/planes" className="text-data-violet hover:underline">/planes</Link>.
          </p>
        </Section>

        <Section title="4. Cuándo SÍ devolvemos plata">
          <p>
            En estos casos sí evaluamos un reembolso parcial o total:
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Cobro duplicado</strong>: si por un error
              técnico nuestro o de Rebill (nuestro procesador de pagos) te cobraron dos
              veces el mismo período, devolvemos el monto duplicado.
            </li>
            <li>
              <strong className="text-ink-0">Falla material del servicio</strong>: si el
              servicio estuvo caído por más de 72 horas continuas durante tu período
              cobrado y eso afectó tu uso, evaluamos un crédito o devolución
              proporcional.
            </li>
            <li>
              <strong className="text-ink-0">Fraude o uso no autorizado</strong>: si
              alguien usó tu tarjeta sin tu consentimiento, escribinos
              inmediatamente. Cancelamos la suscripción y trabajamos con vos en la
              regularización.
            </li>
          </ul>
          <p>
            En todos estos casos, mandanos los detalles a{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
              soporte@rendi.finance
            </a>{' '}
            y te respondemos en menos de 5 días hábiles.
          </p>
        </Section>

        <Section title="5. Pagos fallidos">
          <p>
            Si Rebill no puede cobrar tu renovación (tarjeta vencida, saldo
            insuficiente, etc.), te avisamos por email. Tenés un período de gracia
            para regularizar antes de que tu cuenta baje a Free. Si pagaste OK y
            después la renovación falla, no perdés inmediatamente el acceso — vamos
            a intentar de nuevo y comunicarnos vos.
          </p>
        </Section>

        <Section title="6. Cómo solicitar un reembolso">
          <p>
            Escribinos a{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
              soporte@rendi.finance
            </a>{' '}
            con:
          </p>
          <ul>
            <li>El email asociado a tu cuenta Rendi.</li>
            <li>La fecha y monto del cobro.</li>
            <li>El motivo del reembolso solicitado.</li>
          </ul>
          <p>
            Te respondemos en menos de 5 días hábiles. Si el reembolso aplica, lo
            procesamos en los siguientes 7 días hábiles vía el mismo medio de pago.
          </p>
        </Section>

        <Section title="7. Tu derecho de arrepentimiento (consumo argentino)">
          <p>
            Conforme al artículo 34 de la Ley 24.240 de Defensa del Consumidor de
            Argentina, tenés derecho a revocar la suscripción durante los 10 días
            corridos posteriores a la primera compra, contados desde la fecha del
            cobro. En ese caso, devolvemos el monto íntegro de esa primera compra.
          </p>
          <p>
            Este derecho aplica solo a la <strong className="text-ink-0">primera
            suscripción</strong> de cada user. Renovaciones automáticas y cambios de
            plan no califican (porque ya conociste el servicio).
          </p>
          <p>
            Para ejercerlo, escribinos a{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
              soporte@rendi.finance
            </a>{' '}
            dentro de esos 10 días con asunto "Revocación".
          </p>
        </Section>

        <div className="mt-16 pt-6 border-t border-line flex items-center justify-between text-xs text-ink-3">
          <Link to="/terminos" className="hover:text-ink-1">← Términos y condiciones</Link>
          <Link to="/planes" className="hover:text-ink-1">Ver planes →</Link>
        </div>
      </main>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <section className="mb-10">
      <h2 className="text-xl font-semibold text-ink-0 mb-3">{title}</h2>
      <div className="text-sm text-ink-1 leading-relaxed space-y-3 [&_ul]:space-y-1.5 [&_ul]:pl-5 [&_ul]:list-disc [&_ul_li]:marker:text-ink-3 [&_ol]:space-y-1.5 [&_ol]:pl-5 [&_ol]:list-decimal [&_ol_li]:marker:text-ink-3">
        {children}
      </div>
    </section>
  )
}
