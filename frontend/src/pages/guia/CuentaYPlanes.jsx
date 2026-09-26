// /guia/cuenta-y-planes — sección 6 del manual

import GuidePage from '../../components/guide/GuidePage'
import AdvisorNote from '../../components/guide/AdvisorNote'
// Precios, cupos y lo que incluye cada plan salen de los mismos archivos que
// /planes. Esta sección estaba escrita a mano y contaba otro Rendi: "Free
// (gratis para siempre)" —que no existe para quien se registra—, precios en
// dólares ("USD 4 / mes"), "al TC blue del día", "−15%" anual y cupos de IA que
// ya no eran. Nada de eso daba error; sólo lo leía el que estaba decidiendo.
import {
  FREE_FEATURES, PLUS_FEATURES, PRO_FEATURES,
  TRIAL_TOTAL_DAYS, TRIAL_PRO_DAYS, TRIAL_PLUS_DAYS,
} from '../../data/planCatalog'
import {
  fmtArs, PLUS_PRICE_ARS_MONTHLY, PRO_PRICE_ARS_MONTHLY, ANNUAL_DISCOUNT_BADGE_PCT,
} from '../../data/pricing'
import { alTerminar, cupoDe } from '../../data/prueba'

/** Lo que incluye un plan, tal cual lo publica /planes. */
function LoQueIncluye({ plan }) {
  const brokers = cupoDe(plan, 'Brokers')
  return (
    <ul>
      {plan.essentials.map(f => (
        <li key={f.label}>{f.label}{f.sub ? ` — ${f.sub}` : ''}</li>
      ))}
      <li>
        {cupoDe(plan, 'Análisis IA / sem')} análisis IA y {cupoDe(plan, 'Chat Rendi AI / sem')}{' '}
        consultas a Rendi AI por semana · brokers: {brokers === '∞' ? 'ilimitados' : brokers}
      </li>
    </ul>
  )
}

export default function CuentaYPlanes() {
  return (
    <GuidePage
      n={6}
      title="Cuenta y planes"
      intro={`Configurar tu cuenta, gestionar brokers, la prueba de ${TRIAL_TOTAL_DAYS} días, los planes Plus y Pro, cambio de plan con conversión de crédito y cómo cancelar.`}
      prev={{ to: '/guia/novedades', label: 'Novedades y alertas' }}
      metaTitle="Cuenta y planes — Guía Rendi"
      metaDescription="Cómo configurar tu cuenta, cambiar de plan, cancelar tu suscripción y gestionar brokers en Rendi."
      canonicalPath="/guia/cuenta-y-planes"
    >
      <AdvisorNote>
        <p>
          <strong>Los planes de esta sección no son el tuyo.</strong> Free, Plus y Pro son
          los planes individuales, para alguien que sigue su propia cartera. Vos tenés el{' '}
          <strong>Plan Asesor</strong>, que es más grande: incluye a todos tus clientes con
          visión Pro —aunque ellos estén en Free—, la operación grupal, el chat libre y el
          resumen de carteras. Si entrás a Planes vas a ver eso mismo: tu estado, no las
          cards para comprar.
        </p>
        <p>
          Por eso <strong>no hay botón</strong> para cambiar de plan, cancelar o pasar a
          Pro. Cualquier cambio en tu Plan Asesor —límite de clientes, facturación o
          baja— lo resolvemos por <strong>WhatsApp</strong>, con el link que está en esa
          misma pantalla, en el día.
        </p>
        <p>
          El resto de la sección sí es tuyo tal cual: tus datos, tu contraseña, la moneda
          con la que valuás, las notificaciones y el soporte. Ojo con una cosa: lo que
          configures acá es de <strong>tu</strong> cuenta. La configuración de cada cliente
          vive en la cuenta de él, y la ves cuando entrás.
        </p>
      </AdvisorNote>

      <h2>Configuración</h2>
      <p>
        En <strong>Configuración</strong> tenés:
      </p>
      <ul>
        <li><strong>Cuenta</strong>: tu email, nombre, plan actual, contador de uso semanal de IA.</li>
        <li><strong>Brokers</strong>: agregar/editar/eliminar brokers conectados, gestionar monedas.</li>
        <li><strong>TC blue manual</strong>: si no querés que Rendi tome el blue automático, podés fijar un valor custom.</li>
        <li><strong>Cambiar contraseña</strong>: requiere tu password actual.</li>
        <li><strong>Importar datos</strong>: link al wizard CSV.</li>
        <li><strong>Tema</strong>: dark/light (default dark).</li>
        <li><strong>Memoria del Coach</strong>: ver/eliminar los hechos que el bot recuerda sobre vos (solo Pro).</li>
      </ul>

      <h2>Push notifications</h2>
      <p>
        Activás desde Configuración → Notificaciones push. Te avisamos por push de:
      </p>
      <ul>
        <li>Earnings de tus tickers (1 día antes).</li>
        <li>Drawdown grande (si tu cartera baja más de X% en pocos días).</li>
        <li>Renovación de suscripción (3 días antes del cobro).</li>
        <li>Pago fallido (si Rebill no pudo cobrar la renovación).</li>
      </ul>

      <h2>Planes — qué incluye cada uno</h2>

      <h3>La prueba: {TRIAL_TOTAL_DAYS} días gratis</h3>
      <p>
        Cuando creás tu cuenta y verificás el mail, arranca sola una prueba de{' '}
        <strong>{TRIAL_TOTAL_DAYS} días, sin tarjeta</strong>: los primeros {TRIAL_PRO_DAYS} días
        con Pro y los {TRIAL_PLUS_DAYS} siguientes con Plus. Al terminar elegís uno de los dos
        planes para seguir. Si todavía no elegiste, {alTerminar(true)}: no se borra nada y
        volvés a entrar apenas elegís.
      </p>

      <h3>Plus (${fmtArs(PLUS_PRICE_ARS_MONTHLY)} por mes)</h3>
      <LoQueIncluye plan={PLUS_FEATURES} />

      <h3>Pro (${fmtArs(PRO_PRICE_ARS_MONTHLY)} por mes)</h3>
      <LoQueIncluye plan={PRO_FEATURES} />

      <p>
        Los precios son fijos y en <strong>pesos argentinos</strong>: no dependen del dólar
        del día. Pagando el año ahorrás un {ANNUAL_DISCOUNT_BADGE_PCT}%.
      </p>

      <h3>Free (sólo cuentas que ya lo tenían)</h3>
      <p>
        El plan Free ya no se ofrece: quien se registra hoy arranca con la prueba. Las
        cuentas que ya lo tenían lo conservan, con esto:
      </p>
      <LoQueIncluye plan={FREE_FEATURES} />

      <h2>Cambiar de plan (proración automática)</h2>
      <p>
        Andá a <strong>Planes</strong> y click en el botón del plan al que querés
        cambiar. Te mostramos un modal con el cálculo:
      </p>
      <ul>
        <li>Cuánto crédito te queda del plan actual.</li>
        <li>A cuántos días equivale en el plan nuevo.</li>
      </ul>
      <p>
        <strong>No te cobramos de nuevo.</strong> Convertimos tu crédito remanente al
        rate del plan nuevo. Si bajás de plan, te alcanza para más días. Si subís, te
        alcanza para menos. Cuando se acabe el crédito, te avisamos por email para
        que confirmes si querés seguir.
      </p>

      <h2>Cancelar suscripción</h2>
      <p>
        Andá a <strong>Configuración</strong> y abajo de tu plan vas a ver un botón
        <strong>"Cancelar suscripción"</strong> (en rojo). Confirmás y listo:
      </p>
      <ul>
        <li>Tu suscripción deja de renovarse.</li>
        <li>Mantenés acceso a tu plan hasta el fin del período actual ya cobrado.</li>
        <li>
          Después, si tu cuenta tenía el plan Free, vuelve a él; si te registraste con la
          prueba, queda en pausa hasta que elijas un plan. En los dos casos{' '}
          <em>no perdés tus datos</em>.
        </li>
        <li>Podés reactivar cuando quieras desde Planes.</li>
      </ul>
      <p>
        <strong>No devolvemos el monto del período ya cobrado</strong> (servicio ya
        entregado). Detalles en{' '}
        <a href="/reembolso">Política de Reembolso</a>. Excepciones:
        cobro duplicado o falla técnica nuestra — esos sí los evaluamos caso a caso
        escribiendo a <a href="mailto:soporte@rendi.finance">soporte@rendi.finance</a>.
      </p>

      <h2>Eliminar cuenta</h2>
      <p>
        Si querés borrar todo, escribí a{' '}
        <a href="mailto:soporte@rendi.finance">soporte@rendi.finance</a> con asunto
        "Eliminación de cuenta". Te respondemos en menos de 5 días hábiles y
        eliminamos tu cuenta + todos los datos asociados de forma permanente. Si
        querés exportar tus datos antes (CSV), hacelo desde Reportes → Exportar.
      </p>
      <p>
        Más detalles sobre privacidad y derechos en{' '}
        <a href="/privacidad">Política de Privacidad</a>.
      </p>

      <h2>Recomendaciones y feedback</h2>
      <p>
        Hay un botón <strong>"Recomendaciones"</strong> en el sidebar (debajo de
        Configuración). Te abre un modal donde mandás ideas, bugs o feedback al
        equipo. Lo leemos personalmente y te contestamos en máximo 48 horas hábiles
        si requiere respuesta.
      </p>
    </GuidePage>
  )
}
