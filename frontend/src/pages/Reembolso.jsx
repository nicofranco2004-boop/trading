// Reembolso — política de reembolso de Rendi.
// ════════════════════════════════════════════════════════════════════════════
// Página pública (sin login). Linkeada desde Planes.jsx y desde Terminos.jsx.
//
// Política del negocio (decidida fuera de código):
//   - El plan Free no genera cargos; esta política aplica a Plus / Pro.
//   - Derecho de arrepentimiento obligatorio: 10 días corridos desde la
//     contratación, reembolso total, sin penalidad (Ley 24.240 art. 34 +
//     CCyC art. 1110 + Resolución 424/2020 — botón de arrepentimiento).
//   - Fuera de esos 10 días: no devolvemos el monto del período ya cobrado;
//     el user mantiene acceso pleno hasta el final del período pagado.
//   - Cancelar anula la renovación, no devuelve plata del período actual.
//   - Cambio de plan mid-período → crédito tiempo-based proporcional, sin
//     cobro adicional ni reembolso.
//   - El reintegro se acredita al mismo medio de pago original vía Rebill.
//
// IMPORTANTE: este texto NO sustituye asesoría legal. Si el negocio crece,
// conviene que un abogado lo revise. Mientras tanto es la mejor versión que
// podemos sostener honestamente sobre cómo funciona Rendi hoy.

import { Link } from 'react-router-dom'
import RendiLogo from '../components/RendiLogo'
import PageMeta from '../components/PageMeta'

export default function Reembolso() {
  return (
    <div className="min-h-screen bg-bg-0 text-ink-0">
      <PageMeta
        title="Política de Reembolso — Rendi"
        description="Política de reembolso de Rendi: derecho de arrepentimiento de 10 días corridos con reembolso total (Ley 24.240), botón de arrepentimiento, cómo solicitarlo, plazos vía Rebill, proración al cambiar de plan y cancelación. Última actualización junio 2026."
        canonical="/reembolso"
      />
      {/* Header simple — logo + link a planes */}
      <header className="border-b border-line">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 hover:opacity-90">
            <RendiLogo size={28} />
            <span className="font-semibold text-base tracking-tight">rendi</span>
          </Link>
          <Link to="/planes" className="text-sm text-ink-2 hover:text-ink-0">Volver a planes →</Link>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-12 prose-rendi">
        <p className="font-mono text-[11px] uppercase tracking-caps text-ink-2 mb-2">Legal</p>
        <h1 className="text-3xl font-semibold tracking-tight mb-1">Política de reembolso</h1>
        <p className="text-sm text-ink-3 mb-10">Última actualización: 3 de junio de 2026</p>

        {/* Resumen prominente */}
        <div className="border border-data-violet/40 bg-data-violet/[0.06] rounded-lg p-5 mb-10">
          <p className="text-[10px] font-mono uppercase tracking-caps text-data-violet mb-1.5">Resumen rápido</p>
          <ul className="text-sm text-ink-1 leading-relaxed space-y-1.5 list-disc pl-5 [&_li]:marker:text-data-violet">
            <li>Tenés <strong className="text-ink-0">10 días corridos</strong> desde que contratás Plus o Pro para arrepentirte y recibir el reembolso total, sin costo ni penalidad. Es un derecho que la ley argentina te garantiza.</li>
            <li>El reintegro se acredita al <strong className="text-ink-0">mismo medio de pago</strong> que usaste, a través de Rebill.</li>
            <li>Pasados los 10 días, no devolvemos el monto del período ya cobrado — pero mantenés acceso pleno hasta el final de ese período.</li>
            <li>Cancelar desde <Link to="/config" className="text-data-violet hover:underline">/config</Link> frena las renovaciones a futuro y no genera nuevos cobros.</li>
            <li>Cambiar de plan no genera cobro adicional ni reembolso: convertimos el crédito proporcionalmente.</li>
            <li>El plan Free no genera cargos, así que nunca hay nada que reembolsar.</li>
          </ul>
        </div>

        <Section title="1. Alcance de esta política">
          <p>
            Esta política aplica a las <strong className="text-ink-0">suscripciones pagas</strong> de
            Rendi: los planes <strong className="text-ink-0">Plus</strong> y{' '}
            <strong className="text-ink-0">Pro</strong>, en sus modalidades mensual o anual. Los
            precios y condiciones de cada plan se publican en{' '}
            <Link to="/planes" className="text-data-violet hover:underline">/planes</Link>.
          </p>
          <p>
            El plan <strong className="text-ink-0">Free</strong> es gratuito y no genera ningún cargo,
            por lo que no hay montos que reembolsar. Si nunca pagaste una suscripción, nada de lo que
            sigue te genera obligaciones ni costos.
          </p>
          <p>
            Rendi es una herramienta web de seguimiento de portafolio de inversiones, operada por un
            equipo individual con domicilio en la República Argentina, accesible en{' '}
            <Code>rendi.finance</Code>. El procesamiento de los pagos lo realiza un tercero
            (<strong className="text-ink-0">Rebill</strong>); cualquier reintegro se acredita a través
            de ese mismo procesador, al medio de pago que usaste originalmente.
          </p>
        </Section>

        <Section title="2. Tu derecho de arrepentimiento (10 días corridos)">
          <p>
            Por la legislación argentina de Defensa del Consumidor, en una compra a distancia tenés
            derecho a <strong className="text-ink-0">arrepentirte y revocar la contratación dentro de
            los 10 (diez) días corridos</strong> contados desde que celebraste el contrato de
            suscripción. Es un derecho irrenunciable: está previsto en el{' '}
            <strong className="text-ink-0">artículo 34 de la Ley 24.240</strong> de Defensa del
            Consumidor y en el <strong className="text-ink-0">artículo 1110 del Código Civil y
            Comercial</strong> de la Nación.
          </p>
          <p>
            Si ejercés este derecho dentro del plazo, te devolvemos el{' '}
            <strong className="text-ink-0">monto total que pagaste, sin penalidad ni costo alguno
            para vos</strong>. No tenés que explicar por qué te arrepentís: la decisión es tuya y no
            hace falta justificarla.
          </p>
          <p>
            <strong className="text-ink-0">Cómo ejercerlo.</strong> Alcanza con que nos avises dentro
            de esos 10 días, por cualquiera de estas vías:
          </p>
          <ul>
            <li>
              Usando el <strong className="text-ink-0">botón de arrepentimiento</strong> descripto en
              la sección 3.
            </li>
            <li>
              Escribiéndonos a{' '}
              <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
                soporte@rendi.finance
              </a>{' '}
              con el asunto "Arrepentimiento".
            </li>
            <li>
              Por{' '}
              <a href="https://wa.me/542914373695" target="_blank" rel="noopener noreferrer" className="text-data-violet hover:underline">
                WhatsApp
              </a>
              , indicándonos que querés revocar la suscripción.
            </li>
          </ul>
          <p>
            El plazo se cuenta en días corridos (no hábiles). Mientras estés dentro de los 10 días, el
            arrepentimiento procede aunque ya hayas usado la app: el derecho existe justamente para que
            puedas probar el servicio y dar marcha atrás sin perjuicio.
          </p>
        </Section>

        <Section title="3. Botón de arrepentimiento">
          <p>
            En cumplimiento de la <strong className="text-ink-0">Resolución 424/2020</strong> de la
            Secretaría de Comercio Interior, Rendi pone a tu disposición un mecanismo directo y
            gratuito para que ejerzas tu derecho de arrepentimiento sin trámites innecesarios.
          </p>
          <p>
            Encontrás la opción para iniciar el arrepentimiento desde tu configuración de cuenta en{' '}
            <Link to="/config" className="text-data-violet hover:underline">/config</Link>. Al
            activarla, registramos tu pedido con fecha y hora, frenamos las renovaciones futuras y
            damos curso al reintegro del monto que pagaste, siempre que estés dentro de los 10 días
            corridos.
          </p>
          <p>
            Te enviamos una <strong className="text-ink-0">confirmación por email</strong> dejando
            constancia de que recibimos tu solicitud de arrepentimiento. Si por algún motivo el botón
            no estuviera disponible cuando lo necesitás, podés ejercer el mismo derecho escribiéndonos
            a{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
              soporte@rendi.finance
            </a>{' '}
            o por{' '}
            <a href="https://wa.me/542914373695" target="_blank" rel="noopener noreferrer" className="text-data-violet hover:underline">
              WhatsApp
            </a>
            , y lo procesamos igual.
          </p>
        </Section>

        <Section title="4. Cómo solicitar el reembolso o el arrepentimiento">
          <p>
            Para pedir un reembolso o ejercer tu arrepentimiento, escribinos a{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
              soporte@rendi.finance
            </a>{' '}
            o contactanos por{' '}
            <a href="https://wa.me/542914373695" target="_blank" rel="noopener noreferrer" className="text-data-violet hover:underline">
              WhatsApp
            </a>
            . Para agilizar el trámite, incluí estos datos:
          </p>
          <ul>
            <li>El <strong className="text-ink-0">email asociado</strong> a tu cuenta de Rendi.</li>
            <li>La <strong className="text-ink-0">fecha y el monto</strong> del cobro que querés revisar.</li>
            <li>El <strong className="text-ink-0">plan</strong> contratado (Plus o Pro) y la modalidad (mensual o anual).</li>
            <li>El <strong className="text-ink-0">motivo</strong>: si es arrepentimiento dentro de los 10 días, o cualquier otra situación (por ejemplo, un cobro que no reconocés).</li>
          </ul>
          <p>
            <strong className="text-ink-0">Plazo de respuesta.</strong> Te respondemos en un máximo de{' '}
            <strong className="text-ink-0">5 días hábiles</strong>. Si tu solicitud es un
            arrepentimiento en término, la aprobamos y damos curso al reintegro sin más vueltas.
          </p>
        </Section>

        <Section title="5. Plazos y método de reembolso">
          <p>
            Cuando un reembolso corresponde, lo acreditamos al{' '}
            <strong className="text-ink-0">mismo medio de pago que usaste originalmente</strong>{' '}
            (la tarjeta o el instrumento con el que pagaste), a través de nuestro procesador de pagos{' '}
            <strong className="text-ink-0">Rebill</strong>. No emitimos el reintegro por otra vía ni a
            un tercero distinto del titular del pago.
          </p>
          <p>
            <strong className="text-ink-0">Plazo de acreditación.</strong> Una vez aprobado el
            reembolso, lo procesamos dentro de los <strong className="text-ink-0">7 días hábiles</strong>{' '}
            siguientes. La acreditación efectiva en tu resumen puede demorar algunos días adicionales,
            según los tiempos de tu banco o emisor de la tarjeta — eso depende de la entidad financiera
            y escapa a nuestro control y al de Rebill.
          </p>
          <p>
            El reintegro se hace en la misma moneda en la que se cobró (pesos argentinos). Recordá que
            el precio está anclado en dólares estadounidenses (USD) al tipo de cambio del día; el monto
            que devolvemos es el que efectivamente se te cobró en ARS por la operación reembolsada.
          </p>
        </Section>

        <Section title="6. Política general fuera del plazo de arrepentimiento">
          <p>
            Rendi es un servicio de suscripción. Cuando pagás un período (mensual o anual), te damos
            acceso pleno a todas las features del plan durante toda la duración de ese período, sin
            importar cuánto lo uses.
          </p>
          <p>
            Por eso, <strong className="text-ink-0">una vez vencido el plazo de arrepentimiento de 10
            días</strong>, no reintegramos el monto del período que ya fue cobrado. A cambio,{' '}
            <strong className="text-ink-0">conservás el acceso completo a tu plan hasta el final de ese
            período</strong>: si cancelás faltando 20 días, seguís usando Plus o Pro esos 20 días. El
            servicio ya está disponible para vos durante todo el período pagado.
          </p>
          <p>
            Esto no afecta tu derecho de arrepentimiento dentro de los 10 días (sección 2) ni los
            derechos que la legislación de consumo te reconoce. Si entendés que hubo un cobro indebido o
            un error, escribinos y lo revisamos: ver la sección 4.
          </p>
        </Section>

        <Section title="7. Cambios de plan y proración">
          <p>
            Podés cambiar entre <strong className="text-ink-0">Plus</strong> y{' '}
            <strong className="text-ink-0">Pro</strong> en cualquier momento desde{' '}
            <Link to="/planes" className="text-data-violet hover:underline">/planes</Link>. El cambio
            de plan <strong className="text-ink-0">no genera un cobro adicional ni un reembolso</strong>:
            funciona con un crédito proporcional al tiempo que te queda del período actual.
          </p>
          <p>
            <strong className="text-ink-0">Cómo funciona el crédito.</strong> El valor del tiempo que
            ya pagaste y todavía no usaste se reconvierte automáticamente al rate del plan nuevo. Si
            pasás a un plan de mayor precio, ese crédito te alcanza para menos días en el plan nuevo; si
            pasás a uno de menor precio, te alcanza para más días. En ningún caso te cobramos dos veces
            por el mismo período.
          </p>
          <p>
            <strong className="text-ink-0">Ejemplo.</strong> Pagaste Plus mensual el día 1. El día 10
            te pasás a Pro. Los 20 días que tenías comprados de Plus se convierten en su equivalente en
            días de Pro, según la diferencia de precio entre ambos planes. Cuando ese crédito se agota,
            se cobra el plan nuevo de forma normal. Vas a ver el cálculo exacto antes de confirmar el
            cambio.
          </p>
        </Section>

        <Section title="8. Cancelación de la suscripción">
          <p>
            Podés cancelar tu suscripción en cualquier momento, vos mismo, desde{' '}
            <Link to="/config" className="text-data-violet hover:underline">/config</Link>. No hace
            falta llamar ni pedir autorización.
          </p>
          <p>Al cancelar:</p>
          <ul>
            <li>
              <strong className="text-ink-0">No se generan nuevos cobros.</strong> La renovación
              automática se desactiva de inmediato.
            </li>
            <li>
              <strong className="text-ink-0">Mantenés el acceso hasta el fin del período ya
              cobrado.</strong> La fecha exacta la ves en{' '}
              <Link to="/config" className="text-data-violet hover:underline">/config</Link>.
            </li>
            <li>
              Al expirar ese período, tu cuenta <strong className="text-ink-0">vuelve a Free</strong>{' '}
              automáticamente. No perdés tu información: seguís pudiendo ver y exportar tus datos
              históricos.
            </li>
            <li>
              Podés reactivar la suscripción cuando quieras desde{' '}
              <Link to="/planes" className="text-data-violet hover:underline">/planes</Link>.
            </li>
          </ul>
          <p>
            Cancelar fuera del plazo de arrepentimiento no implica un reembolso del período en curso
            (ver sección 6), pero tampoco un nuevo cargo: simplemente dejás de renovar.
          </p>
        </Section>

        <Section title="9. Renovaciones automáticas">
          <p>
            Las suscripciones de Rendi se <strong className="text-ink-0">renuevan automáticamente</strong>{' '}
            al fin de cada período (mensual o anual) hasta que las canceles. Cada renovación se cobra al
            mismo medio de pago registrado, en pesos argentinos al tipo de cambio del día.
          </p>
          <p>
            <strong className="text-ink-0">Cómo evitar el próximo cobro.</strong> Para que no se genere
            la siguiente renovación, cancelá desde{' '}
            <Link to="/config" className="text-data-violet hover:underline">/config</Link>{' '}
            <strong className="text-ink-0">antes de la fecha de renovación</strong>. Mientras canceles
            antes de esa fecha, no se te cobra el período siguiente y conservás el acceso hasta que
            termine el período vigente.
          </p>
          <p>
            En{' '}
            <Link to="/config" className="text-data-violet hover:underline">/config</Link>{' '}
            siempre podés consultar cuándo es tu próxima fecha de renovación. Si un cobro de renovación
            te tomó por sorpresa y estás dentro de los 10 días corridos de esa renovación, escribinos:
            evaluamos tu caso a la luz de tu derecho de arrepentimiento (sección 2).
          </p>
        </Section>

        <Section title="10. Casos sin reembolso">
          <p>
            No corresponde reembolso, fuera del derecho de arrepentimiento, en los siguientes casos:
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Solicitudes fuera del plazo de 10 días.</strong> Pasado
              el período de arrepentimiento, no reintegramos el monto del período ya cobrado (ver
              sección 6). Conservás el acceso hasta el fin de ese período.
            </li>
            <li>
              <strong className="text-ink-0">Cambios de plan.</strong> El cambio entre Plus y Pro se
              resuelve con crédito proporcional, no con un reembolso (ver sección 7).
            </li>
            <li>
              <strong className="text-ink-0">Suspensión o baja por incumplimiento de los Términos.</strong>{' '}
              Si suspendemos o damos de baja una cuenta por un uso indebido o por violar nuestros{' '}
              <Link to="/terminos" className="text-data-violet hover:underline">Términos y
              Condiciones</Link> (por ejemplo, compartir credenciales, intentar acceder a datos de
              otros usuarios o re-vender el acceso), esa baja no genera reembolso.
            </li>
          </ul>
          <p>
            Estos supuestos no limitan tu derecho de arrepentimiento dentro de los 10 días corridos ni
            los derechos que la ley argentina te reconoce como consumidor.
          </p>
        </Section>

        <Section title="11. Cómo reclamar — Defensa del Consumidor">
          <p>
            Queremos resolver cualquier problema directamente con vos, así que el primer paso siempre es
            escribirnos a{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
              soporte@rendi.finance
            </a>{' '}
            o por{' '}
            <a href="https://wa.me/542914373695" target="_blank" rel="noopener noreferrer" className="text-data-violet hover:underline">
              WhatsApp
            </a>
            . Hacemos lo posible por darte una respuesta clara y rápida.
          </p>
          <p>
            Si aun así no llegamos a un acuerdo, como consumidor tenés derecho a iniciar un reclamo
            formal ante la autoridad de aplicación. Podés hacerlo a través de la{' '}
            <strong className="text-ink-0">Ventanilla Única Federal de Defensa del Consumidor</strong>,
            el canal oficial del Estado argentino para presentar reclamos de consumo. Nada de lo dicho
            en esta política restringe ese derecho.
          </p>
          <p>
            Esta política se complementa con nuestros{' '}
            <Link to="/terminos" className="text-data-violet hover:underline">Términos y
            Condiciones</Link>, que rigen el uso del servicio y la jurisdicción aplicable.
          </p>
        </Section>

        <Section title="12. Contacto">
          <p>
            Para cualquier consulta sobre reembolsos, arrepentimiento, cancelaciones o cambios de plan,
            estamos disponibles en:
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Email:</strong>{' '}
              <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
                soporte@rendi.finance
              </a>
            </li>
            <li>
              <strong className="text-ink-0">WhatsApp:</strong>{' '}
              <a href="https://wa.me/542914373695" target="_blank" rel="noopener noreferrer" className="text-data-violet hover:underline">
                wa.me/542914373695
              </a>
            </li>
          </ul>
          <p>
            Te respondemos en un máximo de 5 días hábiles. Si tu mensaje es un arrepentimiento dentro de
            los 10 días corridos, indicalo en el asunto para darle prioridad.
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

function Code({ children }) {
  return (
    <code className="font-mono text-[12px] bg-bg-2 text-ink-0 px-1 py-0.5 rounded">
      {children}
    </code>
  )
}
