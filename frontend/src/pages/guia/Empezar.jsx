// /guia/empezar — sección 1 del manual

import GuidePage from '../../components/guide/GuidePage'
import { SoloVisitantes } from '../../components/CabeceraPublica'
import AdvisorNote from '../../components/guide/AdvisorNote'
// La prueba y los brokers por plan salen del catálogo: la guía decía "Crear
// cuenta gratis" y "Plan Free permite 1 broker", y quien se registra hoy no
// tiene plan Free — arranca la prueba.
import { PLUS_FEATURES, PRO_FEATURES, TRIAL_TOTAL_DAYS } from '../../data/planCatalog'
import { PRUEBA_EN_UNA_LINEA, cupoDe } from '../../data/prueba'

const brokersDe = (plan) => {
  const v = cupoDe(plan, 'Brokers')
  return v === '∞' ? 'ilimitados' : `hasta ${v}`
}

export default function Empezar() {
  return (
    <GuidePage
      n={1}
      title="Empezar con Rendi"
      intro="Crear tu cuenta, subir el historial de tu broker con la ayuda de Mervall-E y ver tu cartera. Suele llevar unos minutos."
      next={{ to: '/guia/cartera-y-operaciones', label: 'Cartera y operaciones' }}
      metaTitle="Empezar con Rendi — Guía"
      metaDescription="Cómo crear tu cuenta en Rendi y subir el historial de tu broker (Cocos, Balanz, IOL, Schwab, Binance) con la ayuda de Mervall-E, y después sumar lo que falte."
      canonicalPath="/guia/empezar"
    >
      <AdvisorNote>
        <p>
          Vos ya tenés tu cuenta, y no vas a armar una cartera propia:{' '}
          <strong>cada cartera vive en la cuenta de un cliente</strong>. Así que el orden
          para vos es otro:
        </p>
        <ul>
          <li>
            Primero <strong>agregás al cliente</strong> desde Clientes, con su email real.
            No hace falta que él entre todavía ni que tenga contraseña.
          </li>
          <li>
            Después <strong>entrás a su cuenta</strong> y recién ahí seguís esta sección
            tal cual: agregar el broker, importar el CSV o cargar la posición a mano.
          </li>
          <li>
            Cuando quieras que tome el control, lo <strong>invitás</strong>: le llega un
            mail para reclamar la cuenta, con la cartera que vos ya le armaste adentro.
          </li>
        </ul>
        <p>
          Mientras estés adentro de un cliente, arriba te queda una barra que te recuerda
          en qué cuenta estás parado. Todo lo que cargues ahí queda en la cuenta de él.
        </p>
        <p>
          Un dato importante: los <strong>límites de plan</strong> que menciona esta
          sección (cuántos brokers entran en Free, en Plus, en Pro) <strong>no te
          frenan</strong>. Adentro de un cliente operás con <strong>lente Pro</strong>,
          aunque el cliente esté en Free — así que le podés cargar todos los brokers que
          necesite.
        </p>
      </AdvisorNote>

      <h2>1. Crear tu cuenta</h2>
      <p>
        {/* Con la sesión abierta el enlace te dejaba en el Inicio: queda el nombre. */}
        Andá a <SoloVisitantes sino={<strong>Crear cuenta</strong>}><a href="/login?mode=register">Crear cuenta</a></SoloVisitantes>. Te pedimos
        email + contraseña. Te llega un código de 6 dígitos al mail para verificar
        que sos vos (revisá Spam si no aparece en 2 minutos). Listo: al verificar
        el mail arranca tu prueba de {TRIAL_TOTAL_DAYS} días gratis. {PRUEBA_EN_UNA_LINEA}
      </p>
      {/* Con la sesión abierta, entrar a la demo te cambia TU cuenta por la del
          inversor ficticio (hasta 12 h): sólo para quien todavía no entró. */}
      <SoloVisitantes>
      <p>
        Antes de cargar tu data real, podés <a href="/?demo=1">probar la demo</a>{' '}
        — es Rendi con datos de un inversor ficticio. Ves todo sin riesgo de
        ensuciar tu cuenta.
      </p>
      </SoloVisitantes>

      {/* Desde el 25/11 una cuenta nueva no entra a Rendi hasta subir el
          historial de su broker (pages/Onboarding.jsx): la guía no puede
          mandarla primero a Posiciones ni ofrecerle la carga a mano como
          primer paso, porque la app no la deja. */}
      <h2>2. Elegir tu broker y subir su historial</h2>
      <p>
        Apenas verificás el mail te recibe <strong>Mervall-E</strong> y, antes de mostrarte
        tu plata, te pide una sola cosa: tu historial. Elegís con qué broker invertís
        (Cocos, Balanz, IOL, Bull Market, PPI y otros) y te explica cómo bajar el archivo
        de movimientos de ese broker. Lo subís, mirás la vista previa y confirmás.
      </p>
      <p>
        La mayoría de los brokers deja bajar ese archivo sólo desde su página web, así que
        este paso suele ser más cómodo desde la compu.
      </p>
      <ul>
        <li>
          <strong>Si tu broker no está en la lista</strong> (Interactive Brokers, Lemon,
          Mercado Pago…): elegís «Otro / mi broker no está» y usás la{' '}
          <strong>planilla de Rendi</strong>, un Excel simple con una fila por cada compra
          o venta.
        </li>
        <li>
          <strong>Si invertís con Wallbit</strong>: no hace falta ningún archivo. Pegás una
          clave de solo lectura de tu cuenta y se traen tus operaciones.
        </li>
      </ul>
      <p>
        Cuando confirmás, Mervall-E te muestra lo que tenés hoy. Después te ofrece dos cosas
        opcionales que podés dejar para más tarde: el perfil de inversor y, si estás en el
        celular, agregar Rendi a la pantalla de inicio.
      </p>

      <h2>3. Sumar otros brokers y lo que falte</h2>
      <p>
        Con tu primer broker cargado ya entrás a Rendi. Desde ahí:
      </p>
      <ul>
        <li>
          <strong>Otro broker</strong>: <strong>Registrar → Importar historial</strong> (el
          botón violeta del menú lateral en la compu; el "+" de abajo en el celular) y
          elegís el broker. Plus permite {brokersDe(PLUS_FEATURES)} brokers y Pro,{' '}
          {brokersDe(PRO_FEATURES)}.
        </li>
        <li>
          <strong>Algo que no estaba en el archivo</strong>: lo cargás a mano con{' '}
          <strong>Registrar → Compra</strong>: el broker, el activo (ticker, con
          autocompletar), la cantidad, el precio promedio de compra y la fecha. Si vendiste
          algo, va en <strong>Operaciones → Nueva operación → Venta</strong>, y Rendi aplica
          FIFO con tus lotes.
        </li>
      </ul>
      <p>
        Si tu broker no está en la lista, podés mandarnos el archivo a{' '}
        <a href="mailto:soporte@rendi.finance">soporte@rendi.finance</a> y vemos de sumarlo.
      </p>

      <h2>4. Cuestionario de perfil de inversor (opcional)</h2>
      <p>
        En <strong>Perfil de inversor</strong> respondés 7-8 preguntas sobre tu
        horizonte, tolerancia al drawdown y objetivos. <em>No es obligatorio</em>,
        pero si lo llenás, Métricas compara tu cartera real contra lo que vos declaraste
        y te marca incoherencias (ej. "decís perfil conservador pero tenés 70% en
        crypto").
      </p>

      <h2>5. Próximos pasos</h2>
      <p>
        Una vez que tenés data cargada:
      </p>
      <ul>
        <li><strong>Dashboard</strong>: tu portfolio total en USD, P&amp;L del mes, evolución.</li>
        <li><strong>Métricas</strong>: 5 cards de análisis automático.</li>
        <li><strong>Mervall-E AI</strong>: 12 preguntas guiadas (Plus) o chat libre (Pro).</li>
      </ul>
    </GuidePage>
  )
}
