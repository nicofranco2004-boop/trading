// Privacidad — política de privacidad y manejo de datos personales.
// ════════════════════════════════════════════════════════════════════════════
// Página pública accesible sin login. Linkeada desde el footer de Landing,
// desde Terminos.jsx y desde Planes.jsx. Describe qué datos maneja Rendi, para
// qué, con quién se comparten, cómo se protegen y cómo ejercer tus derechos.
// Sujeto a ley argentina (Ley 25.326 de Protección de Datos Personales).
//
// IMPORTANTE: este texto NO sustituye asesoría legal. Si Rendi crece
// significativamente, conviene que un abogado lo revise. Mientras tanto es la
// mejor versión que podemos sostener honestamente sobre cómo funciona Rendi hoy.

import { Link } from 'react-router-dom'
import RendiLogo from '../components/RendiLogo'
import PageMeta from '../components/PageMeta'

export default function Privacidad() {
  return (
    <div className="min-h-screen bg-bg-0 text-ink-0">
      <PageMeta
        title="Política de Privacidad — Rendi"
        description="Cómo Rendi maneja tus datos personales: qué recolectamos, para qué, con quién compartimos, transferencias internacionales, cookies, seguridad, conservación y tus derechos como titular. Compliance Ley 25.326 (Argentina). Última actualización junio 2026."
        canonical="/privacidad"
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
        <h1 className="text-3xl font-semibold tracking-tight mb-1">Política de Privacidad</h1>
        <p className="text-sm text-ink-3 mb-10">Última actualización: 3 de junio de 2026</p>

        {/* Resumen prominente */}
        <div className="border border-data-violet/40 bg-data-violet/[0.06] rounded-lg p-5 mb-10">
          <p className="text-[10px] font-mono uppercase tracking-caps text-data-violet mb-1.5">Resumen rápido</p>
          <ul className="text-sm text-ink-1 leading-relaxed space-y-1.5 list-disc pl-5 [&_li]:marker:text-data-violet">
            <li>Guardamos solo lo que vos cargás (operaciones, posiciones, plazos fijos, entradas mensuales) más tu email y nombre.</li>
            <li>No tenemos acceso a tu dinero ni a tus cuentas: no hay integración bancaria. Vos cargás los datos manualmente o por CSV.</li>
            <li>No vendemos, alquilamos ni compartimos tus datos con fines comerciales, ni hacemos profiling publicitario.</li>
            <li>El pago lo procesa Rebill: nunca almacenamos datos de tu tarjeta o medio de pago.</li>
            <li>El Coach IA usa Claude (Anthropic), que no entrena sus modelos con tus datos.</li>
            <li>Podés acceder, rectificar o eliminar tus datos en cualquier momento escribiéndonos.</li>
            <li>Sujeto a la Ley 25.326 (Protección de Datos Personales, Argentina).</li>
          </ul>
        </div>

        <Section title="1. Introducción y responsable del tratamiento">
          <p>
            Rendi es una herramienta web de seguimiento de portafolio de inversiones,
            operada por un equipo individual con domicilio en la República Argentina. El
            servicio se accede en <Code>rendi.finance</Code>. Esta Política de Privacidad
            explica qué datos personales tratamos cuando usás Rendi, con qué finalidad,
            sobre qué base legal, con quién los compartimos y qué derechos tenés sobre ellos.
          </p>
          <p>
            El responsable del tratamiento de tus datos es el equipo que opera Rendi. Para
            cualquier cuestión vinculada a privacidad o al ejercicio de tus derechos,
            podés contactarnos en{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
              soporte@rendi.finance
            </a>.
          </p>
          <p>
            <strong className="text-ink-0">Alcance.</strong> Esta política aplica a todo el
            tratamiento de datos que hacemos en el marco de Rendi: la creación y uso de tu
            cuenta, los datos de cartera que cargás, el Coach IA y nuestras comunicaciones
            con vos. No cubre los sitios o servicios de terceros que puedas visitar desde
            enlaces dentro de la app, que se rigen por sus propias políticas. El uso del
            servicio se complementa con nuestros{' '}
            <Link to="/terminos" className="text-data-violet hover:underline">Términos y Condiciones</Link>.
          </p>
          <p>
            <strong className="text-ink-0">Qué es y qué no es Rendi.</strong> Rendi es una
            herramienta informativa y de seguimiento. <strong className="text-ink-0">No
            es un broker, no es un asesor financiero y no tiene acceso a tu dinero ni
            integración bancaria.</strong> No ejecutamos operaciones ni custodiamos fondos.
            Vos cargás tus datos de forma manual o importándolos por CSV.
          </p>
        </Section>

        <Section title="2. Qué datos personales recolectamos">
          <p><strong className="text-ink-0">Datos de cuenta:</strong></p>
          <ul>
            <li>Email, con el que creás y accedés a tu cuenta.</li>
            <li>Nombre (opcional, para mostrar en la interfaz).</li>
            <li>
              Contraseña, que nunca almacenamos en texto plano: la guardamos como un hash
              generado con <Code>bcrypt</Code>.
            </li>
          </ul>
          <p className="mt-4"><strong className="text-ink-0">Datos de cartera que vos cargás:</strong></p>
          <ul>
            <li>Posiciones de inversión (broker, ticker, cantidad, precio de compra).</li>
            <li>Operaciones (compras, ventas, dividendos, depósitos, retiros).</li>
            <li>Plazos fijos (capital, tasa, fechas de alta y vencimiento, cobros).</li>
            <li>Entradas mensuales (cash flow por broker).</li>
            <li>Perfil de inversor, si completás el cuestionario opcional (horizonte, tolerancia al riesgo).</li>
            <li>Hechos persistentes que le aclarás al Coach IA para mejorar sus respuestas.</li>
          </ul>
          <p className="mt-4"><strong className="text-ink-0">Datos de uso y técnicos que se generan automáticamente:</strong></p>
          <ul>
            <li>Tu dirección IP (para rate limiting, seguridad y debugging).</li>
            <li>Tipo de dispositivo y navegador (User-Agent: Safari, Chrome, etc.).</li>
            <li>Logs de actividad: timestamps de login, creación de cuenta y eventos del sistema.</li>
            <li>Logs de errores (sin información personal sensible).</li>
          </ul>
          <p className="mt-4"><strong className="text-ink-0">Datos de pago (procesados por Rebill):</strong></p>
          <p>
            Cuando contratás un plan pago, el cobro lo procesa{' '}
            <strong className="text-ink-0">Rebill</strong>, un tercero especializado en
            pagos. <strong className="text-ink-0">Rendi NO almacena los datos de tu
            tarjeta ni de tu medio de pago.</strong> Esos datos los recibe y resguarda
            Rebill directamente. Nosotros solo conservamos información mínima de tu
            suscripción (plan, estado, fechas y montos) para prestarte el servicio.
          </p>
          <p className="mt-4"><strong className="text-ink-0">Comunicaciones que nos enviás:</strong></p>
          <p>
            Si nos escribís por email o WhatsApp, conservamos el contenido de esos mensajes
            y los datos de contacto asociados para responderte y dar seguimiento a tu consulta.
          </p>
          <p className="mt-4"><strong className="text-ink-0">Lo que NO recolectamos:</strong></p>
          <ul>
            <li>Datos de tarjetas o cuentas bancarias (los maneja Rebill, no nosotros).</li>
            <li>Credenciales de tus brokers (nunca te pedimos las contraseñas de Cocos, IOL, etc.).</li>
            <li>Categorías especiales de datos (salud, ideología política, religión, orientación, etc.).</li>
            <li>Identificadores de tracking publicitario o cookies de terceros con fines de advertising.</li>
          </ul>
        </Section>

        <Section title="3. Cómo y para qué usamos tus datos">
          <p>
            Tratamos tus datos con las siguientes finalidades, cada una apoyada en una base
            legal específica:
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Prestar el servicio (ejecución del contrato).</strong>{' '}
              Para que Rendi funcione: calcular P&amp;L, mostrar tus dashboards, generar
              reportes, aplicar el criterio FIFO al vender y mantener tu cartera. Sin estos
              datos no podemos darte el servicio que contrataste.
            </li>
            <li>
              <strong className="text-ink-0">Gestionar tu cuenta y autenticarte (ejecución del contrato).</strong>{' '}
              Para registrarte, identificarte de forma segura y administrar tu suscripción.
            </li>
            <li>
              <strong className="text-ink-0">Responder con el Coach IA (consentimiento).</strong>{' '}
              Cuando le hacés una consulta al Coach IA, enviamos un snapshot de tu cartera
              a Anthropic (Claude) para que pueda responderte con contexto. Lo hacemos
              porque vos elegís usar esa función. Ver la sección 4 para el detalle.
            </li>
            <li>
              <strong className="text-ink-0">Comunicación transaccional (ejecución del contrato).</strong>{' '}
              Para enviarte emails operativos: bienvenida, recibo de pago, recordatorio de
              vencimiento de un plazo fijo o de tu suscripción, y alertas relevantes.
            </li>
            <li>
              <strong className="text-ink-0">Seguridad y prevención de abuso (interés legítimo).</strong>{' '}
              Para aplicar rate limiting, detectar fraude o uso abusivo y mantener la
              integridad del servicio para todos.
            </li>
            <li>
              <strong className="text-ink-0">Mantener y mejorar el producto (interés legítimo).</strong>{' '}
              Para diagnosticar errores y entender patrones de uso de forma agregada. No
              usamos esta información para identificarte individualmente con fines publicitarios.
            </li>
            <li>
              <strong className="text-ink-0">Cumplir obligaciones legales.</strong> Cuando
              una norma aplicable nos obligue a conservar o aportar cierta información.
            </li>
          </ul>
        </Section>

        <Section title="4. Coach IA y procesamiento por Anthropic">
          <p>
            Rendi ofrece un <strong className="text-ink-0">Coach IA</strong> que usa Claude,
            el modelo de inteligencia artificial de{' '}
            <strong className="text-ink-0">Anthropic</strong>, para responder preguntas
            sobre tu cartera.
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Qué se envía.</strong> Cuando le hacés una
              consulta, enviamos a Anthropic un snapshot de los datos de tu cartera
              relevantes para la pregunta, junto con tu consulta. Es un procesamiento que
              ocurre dentro de tu sesión, para generar la respuesta que ves.
            </li>
            <li>
              <strong className="text-ink-0">Anthropic NO entrena con tus datos.</strong>{' '}
              Según la política comercial de Anthropic, los datos que se le envían a través
              de su API no se utilizan para entrenar sus modelos. Podés consultar su política en{' '}
              <a href="https://www.anthropic.com/legal/privacy" target="_blank" rel="noopener noreferrer" className="text-data-violet hover:underline">anthropic.com/legal/privacy</a>.
            </li>
            <li>
              <strong className="text-ink-0">Para qué sirve y para qué no.</strong> Las
              respuestas del Coach IA son informativas y pueden contener errores: es una
              herramienta probabilística, no asesoramiento financiero. Las decisiones de
              inversión son tuyas y a tu propio riesgo (ver{' '}
              <Link to="/terminos" className="text-data-violet hover:underline">Términos y Condiciones</Link>).
            </li>
          </ul>
        </Section>

        <Section title="5. Con quién compartimos y qué NO hacemos">
          <p>
            Para prestar el servicio trabajamos con proveedores (encargados del tratamiento)
            que procesan datos por cuenta y según nuestras instrucciones. Compartimos solo
            el mínimo dato necesario para cada función:
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Railway (hosting del backend).</strong>{' '}
              Almacena y procesa la base de datos y la lógica del servidor.
            </li>
            <li>
              <strong className="text-ink-0">Vercel (hosting del frontend).</strong>{' '}
              Sirve la interfaz web de Rendi.
            </li>
            <li>
              <strong className="text-ink-0">Anthropic (Coach IA).</strong> Recibe el
              snapshot de tu cartera y tu consulta cuando usás el Coach IA. Política:{' '}
              <a href="https://www.anthropic.com/legal/privacy" target="_blank" rel="noopener noreferrer" className="text-data-violet hover:underline">anthropic.com/legal/privacy</a>.
            </li>
            <li>
              <strong className="text-ink-0">Resend (emails transaccionales).</strong>{' '}
              Recibe tu email y el contenido del mensaje para entregártelo. Política:{' '}
              <a href="https://resend.com/legal/privacy-policy" target="_blank" rel="noopener noreferrer" className="text-data-violet hover:underline">resend.com/legal/privacy-policy</a>.
            </li>
            <li>
              <strong className="text-ink-0">Rebill (procesamiento de pagos).</strong>{' '}
              Recibe los datos necesarios para procesar tu pago. Como aclaramos, Rendi no
              almacena los datos de tu tarjeta: los maneja Rebill. Política:{' '}
              <a href="https://www.rebill.com/legal/privacy" target="_blank" rel="noopener noreferrer" className="text-data-violet hover:underline">rebill.com/legal/privacy</a>.
            </li>
            <li>
              <strong className="text-ink-0">Fuentes de datos de mercado.</strong> Para
              mostrar precios y contexto, consultamos servicios externos como Yahoo Finance,
              dolarapi.com, BCRA, data912.com, ArgentinaDatos, CAFCI y Google News. A estas
              fuentes les pedimos datos de mercado públicos; <strong className="text-ink-0">no
              les enviamos tus datos personales ni de cartera</strong>.
            </li>
          </ul>
          <p className="mt-4">
            Cuando un encargado lo permite, suscribimos acuerdos que lo obligan a tratar tus
            datos solo según nuestras instrucciones y con medidas de seguridad adecuadas.
          </p>
          <p className="mt-4"><strong className="text-ink-0">Lo que NO hacemos:</strong></p>
          <ul>
            <li>NO vendemos, alquilamos ni cedemos tus datos a terceros con fines comerciales.</li>
            <li>NO hacemos profiling ni segmentación con fines publicitarios.</li>
            <li>
              NO compartimos tu información con tu broker, AFIP, ARCA ni ningún ente
              regulatorio, salvo orden judicial o requerimiento legal válido al que estemos
              obligados a responder.
            </li>
          </ul>
        </Section>

        <Section title="6. Transferencias internacionales de datos">
          <p>
            Algunos de nuestros proveedores (por ejemplo, los de hosting, IA o emails)
            operan servidores ubicados fuera de la República Argentina. Esto implica que,
            para prestarte el servicio, ciertos datos pueden transferirse y procesarse en
            otros países.
          </p>
          <p>
            En esos casos buscamos que la transferencia se apoye en resguardos contractuales
            con cada proveedor que los obliguen a proteger tus datos con estándares
            adecuados y a tratarlos únicamente según nuestras instrucciones, en línea con la
            normativa argentina de protección de datos personales.
          </p>
        </Section>

        <Section title="7. Cookies y tecnologías de seguimiento">
          <p>
            Rendi usa <strong className="text-ink-0">solo cookies funcionales esenciales</strong>{' '}
            para operar:
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Cookie de sesión HttpOnly</strong> — mantiene
              tu login activo. Es necesaria para que la app funcione y no es accesible
              desde JavaScript.
            </li>
            <li>
              <strong className="text-ink-0">Preferencia de tema</strong> — recuerda si
              elegís el modo claro u oscuro de la interfaz.
            </li>
          </ul>
          <p className="mt-4">
            <strong className="text-ink-0">NO usamos</strong> cookies de tracking
            publicitario, pixels de Facebook, conversion tracking de Google Ads ni
            rastreadores de terceros con fines de profiling. Como las únicas cookies que
            usamos son estrictamente necesarias para que puedas usar tu sesión,{' '}
            <strong className="text-ink-0">no mostramos un banner de consentimiento de
            cookies</strong>: no hay nada de tracking que aceptar o rechazar.
          </p>
        </Section>

        <Section title="8. Seguridad de la información">
          <p>
            Aplicamos medidas técnicas y organizativas razonables para proteger tus datos.
            Ningún sistema es 100% infalible, pero estos son los resguardos que mantenemos hoy:
          </p>
          <ul>
            <li>HTTPS para cifrar la información en tránsito entre tu dispositivo y Rendi.</li>
            <li>Cookies de sesión HttpOnly, no accesibles desde JavaScript.</li>
            <li>Contraseñas guardadas como hash con <Code>bcrypt</Code>, nunca en texto plano.</li>
            <li>Backups de la base de datos.</li>
            <li>Acceso a los sistemas de producción restringido al equipo de Rendi.</li>
          </ul>
          <p>
            En caso de un incidente de seguridad que afecte tus datos personales, te
            notificaremos por email y daremos aviso a la autoridad de control cuando
            corresponda, según la normativa aplicable.
          </p>
        </Section>

        <Section title="9. Conservación de los datos">
          <p>
            Conservamos tus datos <strong className="text-ink-0">mientras tengas una cuenta
            activa</strong> en Rendi, para que puedas seguir usando el servicio. Si cancelás
            una suscripción paga y volvés al plan Free, tus datos siguen disponibles para vos
            en tu cuenta.
          </p>
          <p>
            Cuando dejás de necesitar el servicio y solicitás la baja, eliminamos tu cuenta y
            tus datos asociados (ver la sección 13). Podemos conservar cierta información por
            el tiempo necesario para cumplir obligaciones legales, resolver disputas o hacer
            valer nuestros acuerdos; una vez vencidos esos plazos, la eliminamos o anonimizamos.
          </p>
        </Section>

        <Section title="10. Tus derechos como titular de datos (Ley 25.326)">
          <p>
            La Ley 25.326 de Protección de Datos Personales te reconoce, como titular de los
            datos, los siguientes derechos:
          </p>
          <ul>
            <li><strong className="text-ink-0">Acceso</strong> — saber qué datos tuyos tratamos y obtener información sobre ese tratamiento.</li>
            <li><strong className="text-ink-0">Rectificación</strong> — corregir datos inexactos o erróneos.</li>
            <li><strong className="text-ink-0">Actualización</strong> — mantener tus datos al día.</li>
            <li><strong className="text-ink-0">Supresión o cancelación</strong> — pedir que eliminemos tus datos cuando corresponda.</li>
          </ul>
          <p>
            Para ejercer cualquiera de estos derechos, escribinos a{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
              soporte@rendi.finance
            </a>{' '}
            indicando el derecho que querés ejercer. Te respondemos dentro de los plazos
            previstos por la normativa: como referencia, los pedidos de acceso se contestan
            dentro de los 10 días corridos y los de rectificación, actualización o supresión
            dentro de los 5 días hábiles. Si necesitamos verificar tu identidad antes de
            actuar sobre los datos, te lo pediremos.
          </p>
          <p>
            <strong className="text-ink-0">Autoridad de control.</strong> La autoridad de
            aplicación en Argentina es la{' '}
            <strong className="text-ink-0">Agencia de Acceso a la Información Pública (AAIP)</strong>.
            Si considerás que no respetamos tus derechos, podés presentar un reclamo
            directamente ante ella.
          </p>
        </Section>

        <Section title="11. Datos de menores">
          <p>
            Rendi está dirigido a personas <strong className="text-ink-0">mayores de 18
            años</strong>. No recolectamos a sabiendas datos de menores de edad. Si tomamos
            conocimiento de que un menor creó una cuenta sin la debida autorización,
            procederemos a eliminarla.
          </p>
          <p>
            Si sos madre, padre o tutor y creés que un menor a tu cargo usó Rendi,
            escribinos a{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
              soporte@rendi.finance
            </a>{' '}
            y resolvemos la baja.
          </p>
        </Section>

        <Section title="12. Datos financieros y de cartera">
          <p>
            Los datos de tu cartera (posiciones, operaciones, plazos fijos, entradas
            mensuales y los cálculos derivados) son <strong className="text-ink-0">sensibles
            por su naturaleza</strong>: reflejan tu situación patrimonial. Por eso los
            tratamos con especial cuidado.
          </p>
          <p>
            Los usamos <strong className="text-ink-0">exclusivamente para prestarte el
            servicio</strong>: mostrarte tu portafolio, calcular resultados, generar reportes
            y alimentar el Coach IA cuando se lo pedís. No los vendemos, no los usamos para
            publicidad ni los compartimos con tu broker, AFIP, ARCA ni reguladores, salvo
            orden judicial. Vos mantenés la propiedad de tu información y podés exportarla o
            pedir su eliminación cuando quieras.
          </p>
        </Section>

        <Section title="13. Eliminación de cuenta y datos">
          <p>
            Podés solicitar la <strong className="text-ink-0">baja total de tu cuenta y la
            eliminación de tus datos</strong> en cualquier momento, escribiéndonos a{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
              soporte@rendi.finance
            </a>{' '}
            con el asunto "Eliminación de cuenta".
          </p>
          <p>
            Procesamos la baja y eliminamos de forma permanente tu cuenta y los datos
            asociados en un plazo razonable, en general dentro de los 30 días. Solo
            conservamos lo que una obligación legal nos exija mantener, por el tiempo
            estrictamente necesario, tras lo cual también se elimina o anonimiza.
          </p>
        </Section>

        <Section title="14. Cambios a esta política">
          <p>
            Podemos actualizar esta política para reflejar cambios en el servicio o en la
            normativa aplicable. Si hay cambios materiales (qué datos recolectamos, con quién
            los compartimos o tus derechos), te lo comunicaremos por email con una antelación
            razonable antes de que entren en vigor.
          </p>
          <p>
            La fecha de "Última actualización" al inicio de esta página indica la versión
            vigente. Si seguís usando Rendi después de que un cambio entre en vigor,
            entendemos que tomaste conocimiento de la versión actualizada.
          </p>
        </Section>

        <Section title="15. Contacto y responsable">
          <p>
            El responsable del tratamiento de tus datos es el equipo que opera Rendi, con
            domicilio en la República Argentina. Para cualquier consulta sobre privacidad o
            para ejercer tus derechos, escribinos a{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
              soporte@rendi.finance
            </a>{' '}
            o contactanos por{' '}
            <a href="https://wa.me/542914373695" target="_blank" rel="noopener noreferrer" className="text-data-violet hover:underline">
              WhatsApp
            </a>.
          </p>
        </Section>

        <div className="mt-16 pt-6 border-t border-line flex items-center justify-between text-xs text-ink-3">
          <Link to="/terminos" className="hover:text-ink-1">← Términos y condiciones</Link>
          <Link to="/reembolso" className="hover:text-ink-1">Política de reembolso →</Link>
        </div>
      </main>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <section className="mb-10">
      <h2 className="text-xl font-semibold text-ink-0 mb-3">{title}</h2>
      <div className="text-sm text-ink-1 leading-relaxed space-y-3 [&_ul]:space-y-1.5 [&_ul]:pl-5 [&_ul]:list-disc [&_ul_li]:marker:text-ink-3">
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
