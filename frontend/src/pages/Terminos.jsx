// Terminos — términos y condiciones de uso de Rendi.
// ════════════════════════════════════════════════════════════════════════════
// Página pública accesible sin login. Linkeada desde Planes.jsx, Landing.jsx
// y desde el footer general. Cubre uso del servicio, suscripciones, pagos,
// datos, propiedad intelectual, responsabilidades y derechos del consumidor.
// Sujeto a ley argentina (CABA).
//
// IMPORTANTE: este texto NO sustituye asesoría legal. Es la mejor versión que
// podemos sostener honestamente sobre cómo funciona Rendi hoy, redactada por el
// equipo y no por un abogado. Antes de apoyarte fuerte en estas cláusulas —o si
// el negocio crece— conviene que un/a abogado/a matriculado/a lo revise y lo
// adapte a tu caso. No tomes estas líneas como asesoramiento legal.

import { Link } from 'react-router-dom'
import RendiLogo from '../components/RendiLogo'
import PageMeta from '../components/PageMeta'

export default function Terminos() {
  return (
    <div className="min-h-screen bg-bg-0 text-ink-0">
      <PageMeta
        title="Términos y Condiciones — Rendi"
        description="Términos y Condiciones de Rendi: definiciones, qué hacemos y qué no, planes Free/Plus/Pro, pagos y renovación, reembolsos, datos, propiedad intelectual, responsabilidades, Defensa del Consumidor y jurisdicción argentina (CABA). Última actualización junio 2026."
        canonical="/terminos"
      />
      {/* Header simple — logo + link a home */}
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
        <p className="text-[12.5px] text-ink-2 mb-2 font-medium">Legal</p>
        <h1 className="text-3xl font-semibold tracking-tight mb-1">Términos y Condiciones</h1>
        <p className="text-sm text-ink-3 mb-4">Última actualización: 3 de junio de 2026</p>

        <p className="text-sm text-ink-1 leading-relaxed mb-10">
          Estos Términos y Condiciones (los "Términos") regulan el acceso y uso de
          Rendi. Te pedimos que los leas con atención: al crear una cuenta o usar el
          servicio, aceptás todo lo que sigue. Si algo no te cierra, no uses Rendi y
          escribinos —prefermos aclararlo antes que después.
        </p>

        <Section title="1. Definiciones">
          <p>
            Para que nos entendamos sin ambigüedades, a lo largo de estos Términos usamos
            estas palabras con el siguiente significado:
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">"Rendi", "nosotros" o "el equipo"</strong> —
              la herramienta web de seguimiento de portafolio descripta en estos Términos y
              el equipo individual, con domicilio en la República Argentina, que la opera.
            </li>
            <li>
              <strong className="text-ink-0">"Usuario", "vos" o "tu cuenta"</strong> — la
              persona humana, mayor de edad y con capacidad legal para contratar, que se
              registra y usa el Servicio.
            </li>
            <li>
              <strong className="text-ink-0">"Servicio"</strong> — el sitio, la aplicación
              web, las funcionalidades, el Coach IA y todo lo que se accede en{' '}
              <Code>rendi.finance</Code>.
            </li>
            <li>
              <strong className="text-ink-0">"Contenido del Usuario"</strong> — todos los
              datos que vos cargás o importás: posiciones, operaciones, tenencias, entradas
              manuales, archivos CSV y cualquier otra información de tu cartera.
            </li>
            <li>
              <strong className="text-ink-0">"Plan"</strong> — el nivel de suscripción que
              tengas activo (Free, Plus o Pro), con sus features y, si corresponde, su precio.
            </li>
            <li>
              <strong className="text-ink-0">"Coach IA"</strong> — el asistente
              conversacional de Rendi que responde preguntas sobre tu cartera apoyándose en
              modelos de Claude (Anthropic).
            </li>
            <li>
              <strong className="text-ink-0">"Terceros"</strong> — proveedores externos que
              Rendi usa para funcionar (fuentes de datos de mercado, procesador de pagos,
              infraestructura, email, IA), detallados más abajo.
            </li>
          </ul>
        </Section>

        <Section title="2. Aceptación de los términos y capacidad legal">
          <p>
            Al registrarte, acceder o usar el Servicio declarás que leíste, entendiste y
            aceptás estos Términos en su totalidad, junto con la{' '}
            <Link to="/privacidad" className="text-data-violet hover:underline">Política de Privacidad</Link>{' '}
            y la{' '}
            <Link to="/reembolso" className="text-data-violet hover:underline">Política de Reembolso</Link>,
            que forman parte integral de este acuerdo.
          </p>
          <p>
            Para usar Rendi tenés que ser <strong className="text-ink-0">mayor de 18 años</strong>{' '}
            y tener capacidad legal para contratar según la legislación argentina. Si usás el
            Servicio en representación de otra persona o de una entidad, declarás que contás
            con facultades suficientes para obligarla a estos Términos.
          </p>
          <p>
            Si no estás de acuerdo con alguna parte de estos Términos, la solución es simple:
            no uses Rendi. Si ya tenés una cuenta, podés darla de baja en cualquier momento.
          </p>
        </Section>

        <Section title="3. Quiénes somos">
          <p>
            Rendi es una herramienta web de seguimiento de portafolio de inversiones,
            operada por un equipo individual con domicilio en la República Argentina.
            El Servicio se accede en <Code>rendi.finance</Code> y consume datos de
            mercado de Terceros (Yahoo Finance, dolarapi.com, BCRA, data912.com,
            ArgentinaDatos, CAFCI, Google News y similares), sin afiliación con ninguno
            de ellos.
          </p>
          <p>
            Somos un proyecto chico y honesto: no somos un banco, ni una sociedad de bolsa,
            ni un fondo. Lo que ves en estos Términos es exactamente cómo funciona Rendi hoy,
            sin letra chica escondida.
          </p>
        </Section>

        <Section title="4. Descripción del servicio: qué hace y qué NO es">
          <p><strong className="text-ink-0">Qué hace Rendi:</strong></p>
          <ul>
            <li>
              Te deja registrar y trackear tu cartera de inversiones: acciones, CEDEARs,
              cripto, bonos y obligaciones negociables (ON), fondos comunes de inversión (FCI)
              y plazos fijos.
            </li>
            <li>Te muestra tus posiciones y operaciones agrupadas por broker.</li>
            <li>Calcula P&amp;L realizado y no realizado en USD con criterio FIFO.</li>
            <li>Te genera insights, reportes históricos y diagnósticos de tu cartera.</li>
            <li>Te ofrece un Coach IA (basado en Claude, de Anthropic) para responder preguntas sobre tus datos.</li>
          </ul>
          <p>
            Vos cargás la información <strong className="text-ink-0">manualmente o por archivo CSV</strong>.
            No hay integración con tu banco ni con tu broker: Rendi refleja lo que vos le contás.
          </p>
          <p className="mt-4"><strong className="text-ink-0">Qué NO hace y qué NO es Rendi:</strong></p>
          <ul>
            <li>
              <strong className="text-ink-0">No es un broker ni una sociedad de bolsa.</strong>{' '}
              No ejecuta órdenes de compra ni de venta. Las operaciones las hacés en tu broker
              real (Cocos, IOL, Schwab, Binance, etc.).
            </li>
            <li>
              <strong className="text-ink-0">No es asesoramiento financiero.</strong> Rendi
              no está registrado ante la Comisión Nacional de Valores (CNV) ni ante ningún
              ente regulador como asesor de inversiones. Los análisis, scorecards y respuestas
              del Coach IA son herramientas meramente informativas. No constituyen una
              recomendación de comprar, vender o mantener ningún activo.
            </li>
            <li>
              <strong className="text-ink-0">No tiene custodia ni acceso a tu dinero.</strong>{' '}
              No hay integración bancaria, ni custodia de fondos, ni operatoria. Rendi nunca
              toca tu plata: solo muestra los números que vos cargás.
            </li>
          </ul>
          <p>
            Dicho de otro modo: Rendi es una <strong className="text-ink-0">calculadora y un
            tablero</strong> para que veas tu cartera con claridad. Las decisiones de inversión,
            con todo su riesgo, son siempre tuyas.
          </p>
        </Section>

        <Section title="5. Registro, cuenta y seguridad de las credenciales">
          <p>
            Para usar Rendi tenés que crear una cuenta con tu email, tu nombre y una
            contraseña. Te comprometés a brindar datos verídicos y a mantenerlos
            actualizados.
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Una cuenta por persona.</strong> Las cuentas son
              personales e intransferibles. No compartas tu cuenta ni uses la de otra persona.
            </li>
            <li>
              <strong className="text-ink-0">Sos responsable de tu contraseña.</strong> Guardá
              tu contraseña en un lugar seguro y no la compartas. Toda actividad realizada
              desde tu cuenta se presume hecha por vos.
            </li>
            <li>
              <strong className="text-ink-0">Aviso de uso no autorizado.</strong> Si sospechás
              que alguien accedió a tu cuenta sin permiso, escribinos cuanto antes a{' '}
              <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">soporte@rendi.finance</a>{' '}
              y cambiá tu contraseña. Vamos a ayudarte, pero no podemos responsabilizarnos por
              accesos derivados de una contraseña mal cuidada.
            </li>
          </ul>
          <p>
            Guardamos tu contraseña <strong className="text-ink-0">hasheada con bcrypt</strong>:
            ni nosotros podemos leerla en texto plano.
          </p>
        </Section>

        <Section title="6. Planes y suscripciones">
          <p>
            Rendi ofrece un plan gratuito (<strong className="text-ink-0">"Free"</strong>) sin
            vencimiento y dos planes pagos (<strong className="text-ink-0">"Plus"</strong> y{' '}
            <strong className="text-ink-0">"Pro"</strong>) con límites y features ampliados. Los
            precios vigentes y lo que incluye cada plan se publican en{' '}
            <Link to="/planes" className="text-data-violet hover:underline">/planes</Link>.
          </p>
          <p>
            <strong className="text-ink-0">Precio en pesos, anclado en dólares.</strong> Cobramos
            en pesos argentinos (ARS). El precio de referencia está expresado en dólares
            estadounidenses (USD) y se convierte a ARS al tipo de cambio del día. Por eso el
            ancla es el precio en USD y el monto exacto en ARS puede variar de un día a otro.
            Siempre vas a ver el monto final en ARS antes de confirmar el pago.
          </p>
          <p>
            <strong className="text-ink-0">Renovación automática.</strong> Las suscripciones
            pagas se renuevan automáticamente al final de cada período (mensual o anual) hasta
            que las canceles. Cada renovación se cobra al mismo medio de pago que tengas registrado.
          </p>
          <p>
            <strong className="text-ink-0">Cambio de plan con proración.</strong> Podés cambiar
            entre Plus y Pro cuando quieras desde{' '}
            <Link to="/planes" className="text-data-violet hover:underline">/planes</Link>. El
            crédito que te quede del período en curso se reconvierte automáticamente al rate del
            plan nuevo, de modo que no pagás dos veces por los días que ya tenías cubiertos.
          </p>
          <p>
            <strong className="text-ink-0">Cancelación.</strong> Podés cancelar en cualquier
            momento desde{' '}
            <Link to="/config" className="text-data-violet hover:underline">/config</Link>. Al
            cancelar, mantenés el acceso a tu plan pago hasta el final del período ya cobrado y,
            a partir de ahí, tu cuenta vuelve a Free de forma automática. No se programan nuevos
            cobros una vez que cancelás.
          </p>
        </Section>

        <Section title="7. Pagos y facturación">
          <p>
            El procesamiento de los pagos lo realiza un <strong className="text-ink-0">tercero,
            Rebill</strong>, que es nuestro procesador de pagos. Cuando suscribís un plan pago,
            tus datos de tarjeta se ingresan en el entorno de Rebill.
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Rendi no almacena datos de tarjeta.</strong> No
              guardamos el número de tu tarjeta, su código de seguridad ni su vencimiento. Esa
              información la maneja Rebill bajo sus propios términos y estándares de seguridad.
            </li>
            <li>
              <strong className="text-ink-0">Autorización de cobros.</strong> Al suscribir,
              autorizás a que se debiten del medio de pago registrado el monto del plan y sus
              renovaciones, hasta que canceles.
            </li>
            <li>
              <strong className="text-ink-0">Impuestos.</strong> Los precios pueden no incluir
              impuestos, percepciones o retenciones que correspondan según tu situación. Si
              aplicaran, esos importes quedan a tu cargo.
            </li>
            <li>
              <strong className="text-ink-0">Cobros fallidos.</strong> Si Rebill no puede cobrar
              una renovación (por ejemplo, tarjeta vencida o sin saldo), podemos reintentar el
              cobro y/o pausar el acceso al plan pago hasta regularizar.
            </li>
          </ul>
        </Section>

        <Section title="8. Reembolsos y derecho de arrepentimiento">
          <p>
            Como Usuario consumidor en Argentina, tenés derecho de arrepentimiento sobre la
            contratación a distancia, dentro de los plazos que prevé la ley. Las condiciones,
            los plazos y el modo de ejercerlo —incluido el botón de arrepentimiento— están
            detallados en nuestra{' '}
            <Link to="/reembolso" className="text-data-violet hover:underline">Política de Reembolso</Link>.
          </p>
          <p>
            <strong className="text-ink-0">Resumen:</strong> por regla general no devolvemos el
            monto del período ya cobrado; lo que conservás es el acceso pleno a tu plan hasta el
            final de ese período. La Política de Reembolso explica las excepciones (por ejemplo,
            cobros duplicados por un error técnico nuestro o de Rebill) y cómo gestionarlas.
          </p>
        </Section>

        <Section title="9. Contenido del Usuario y licencia">
          <p>
            <strong className="text-ink-0">Tu contenido es tuyo.</strong> El Contenido del
            Usuario —tus posiciones, operaciones, tenencias y demás datos de cartera— es y sigue
            siendo de tu propiedad. Rendi no reclama titularidad sobre tus datos.
          </p>
          <p>
            Para que el Servicio funcione, nos otorgás una{' '}
            <strong className="text-ink-0">licencia limitada, no exclusiva y revocable</strong>{' '}
            para almacenar, procesar, calcular y mostrarte tu propio Contenido del Usuario dentro
            de Rendi. Esta licencia existe con el único fin de prestarte el Servicio: no usamos tus
            datos para otra cosa.
          </p>
          <p>
            Sos responsable de la exactitud de lo que cargás. Si los datos de entrada están mal,
            los cálculos también lo van a estar. Podés exportar tu Contenido del Usuario y, si
            das de baja la cuenta, eliminamos los datos asociados de forma permanente (ver{' '}
            <Link to="/privacidad" className="text-data-violet hover:underline">Política de Privacidad</Link>).
          </p>
        </Section>

        <Section title="10. Propiedad intelectual">
          <p>
            El nombre <strong className="text-ink-0">Rendi</strong>, el logo (la "R" violeta),
            el dominio rendi.finance, el diseño de la interfaz, los textos y el código del
            software son propiedad exclusiva del equipo de Rendi. Están protegidos por las leyes
            argentinas e internacionales de propiedad intelectual.
          </p>
          <p>
            No está permitido copiar, modificar, distribuir, descompilar, hacer ingeniería
            inversa ni crear obras derivadas de la marca, el diseño o el software de Rendi sin
            nuestra autorización previa y por escrito.
          </p>
          <p>
            Esta sección no afecta la titularidad de tu Contenido del Usuario, que se rige por la
            sección 9.
          </p>
        </Section>

        <Section title="11. Servicios y datos de terceros">
          <p>
            Rendi se apoya en proveedores externos para funcionar. No tenemos afiliación,
            sociedad ni patrocinio con ninguno de ellos, y su disponibilidad o exactitud está
            fuera de nuestro control.
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Fuentes de datos de mercado.</strong> Precios,
              cotizaciones y datos de contexto provienen de Yahoo Finance, dolarapi.com, BCRA,
              data912.com, ArgentinaDatos, CAFCI y Google News, entre otros. Se ofrecen{' '}
              <strong className="text-ink-0">"tal como están" ("as-is")</strong>: pueden tener
              delays, gaps o errores. No garantizamos su exactitud ni su disponibilidad.
            </li>
            <li>
              <strong className="text-ink-0">Anthropic (Claude).</strong> El Coach IA se apoya
              en modelos de Claude. Cuando le hacés una consulta, se envía a Anthropic un{' '}
              <em>snapshot</em> de tu cartera para que pueda responder con contexto. Según la
              política comercial de Anthropic, <em>esos datos no se usan para entrenar sus
              modelos</em>.
            </li>
            <li>
              <strong className="text-ink-0">Rebill.</strong> Procesa los pagos y maneja los
              datos de tarjeta. Rendi no almacena esa información.
            </li>
            <li>
              <strong className="text-ink-0">Infraestructura.</strong> El backend corre en
              Railway, el frontend en Vercel y los emails se envían con Resend. Algunos de estos
              servidores pueden estar ubicados fuera de la Argentina.
            </li>
          </ul>
          <p>
            El uso que hagas de estos Terceros, cuando corresponda, puede estar sujeto a sus
            propios términos y políticas.
          </p>
        </Section>

        <Section title="12. Disclaimers">
          <p>
            El Servicio se ofrece <strong className="text-ink-0">"tal como está" ("as-is")</strong>{' '}
            y "según disponibilidad". Hacemos nuestro mejor esfuerzo para que todo sea preciso y
            esté online, pero queremos ser muy claros sobre lo que NO podemos garantizar:
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Rendi no brinda asesoramiento financiero ni
              recomendaciones de inversión.</strong> Nada de lo que veas —ni los análisis, ni los
              scorecards, ni el Coach IA— constituye un consejo para comprar, vender o mantener un
              activo. Las decisiones son tuyas y a tu propio riesgo.
            </li>
            <li>
              <strong className="text-ink-0">Los datos de mercado son meramente informativos.</strong>{' '}
              Vienen de fuentes de Terceros que pueden tener delays, errores o gaps. Verificá
              siempre en tu broker antes de tomar decisiones importantes.
            </li>
            <li>
              <strong className="text-ink-0">El P&amp;L y los cálculos impositivos son
              orientativos.</strong> El P&amp;L (realizado y no realizado), los rendimientos y
              cualquier estimación de impacto impositivo son aproximaciones informativas.
              Verificá los números finales en tu broker y consultá tu situación fiscal con un/a
              contador/a.
            </li>
            <li>
              <strong className="text-ink-0">El Coach IA puede equivocarse.</strong> Es una
              herramienta probabilística: puede dar respuestas imprecisas o incompletas. Tomá sus
              salidas como un punto de partida, no como una verdad cerrada.
            </li>
          </ul>
        </Section>

        <Section title="13. Uso aceptable y conductas prohibidas">
          <p>
            Te pedimos que uses Rendi de buena fe. En particular, está prohibido:
          </p>
          <ul>
            <li>Compartir credenciales, revender el acceso o usar la cuenta de otra persona.</li>
            <li>Intentar acceder a datos o cuentas de otros usuarios.</li>
            <li>Hacer scraping masivo, ataques de denegación de servicio (DoS) o ingeniería inversa del sistema.</li>
            <li>Vulnerar, sortear o probar mecanismos de seguridad sin autorización.</li>
            <li>Usar el Coach IA para generar contenido ilegal o que viole los términos de Anthropic (contenido ilícito, deepfakes, spam, etc.).</li>
            <li>Cargar contenido ilegal, malicioso o que infrinja derechos de terceros.</li>
            <li>Usar el Servicio para cualquier fin contrario a la ley o a estos Términos.</li>
          </ul>
        </Section>

        <Section title="14. Suspensión y terminación de la cuenta">
          <p>
            Podés dejar de usar Rendi y dar de baja tu cuenta cuando quieras (ver secciones 6
            y 9, y la{' '}
            <Link to="/privacidad" className="text-data-violet hover:underline">Política de Privacidad</Link>).
          </p>
          <p>
            De nuestro lado, podemos <strong className="text-ink-0">suspender o cancelar</strong>{' '}
            una cuenta —de forma temporal o definitiva, y sin reembolso— cuando exista un
            incumplimiento de estos Términos, un uso que ponga en riesgo el Servicio o a otros
            usuarios, una conducta prohibida (sección 13) o una exigencia legal. Cuando sea
            razonable y posible, vamos a avisarte antes y a darte la chance de corregir.
          </p>
          <p>
            Tras la terminación, dejás de tener acceso al Servicio. Las cláusulas que por su
            naturaleza deban sobrevivir (propiedad intelectual, disclaimers, limitación de
            responsabilidad, indemnidad, ley aplicable) siguen vigentes.
          </p>
        </Section>

        <Section title="15. Limitación de responsabilidad y tope económico">
          <p>
            En la máxima medida permitida por la ley argentina:
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Rendi no se hace responsable</strong> por pérdidas
              financieras, lucro cesante, oportunidades perdidas o daños indirectos derivados del
              uso (o de la imposibilidad de uso) de la herramienta. Las decisiones de inversión
              son tuyas y a tu propio riesgo.
            </li>
            <li>
              <strong className="text-ink-0">Tope (cap) de responsabilidad económica:</strong> en
              caso de que un tribunal nos encontrara responsables por un perjuicio relacionado con
              el Servicio, nuestra responsabilidad total se limita al monto que pagaste en los 12
              meses anteriores al hecho que generó el reclamo (o a USD 100 si nunca pagaste).
            </li>
            <li>
              <strong className="text-ink-0">No garantizamos disponibilidad ininterrumpida.</strong>{' '}
              Hacemos nuestro mejor esfuerzo, pero pueden ocurrir caídas por mantenimiento,
              problemas de proveedores (Vercel, Railway, Anthropic, Rebill, Resend), eventos de
              fuerza mayor o fallas técnicas.
            </li>
            <li>
              <strong className="text-ink-0">No garantizamos la precisión de los datos de
              mercado.</strong> Verificá siempre en tu broker antes de tomar decisiones importantes.
            </li>
          </ul>
          <p>
            Nada de esto limita las responsabilidades que, según la ley argentina —incluida la
            normativa de defensa del consumidor—, no puedan excluirse ni limitarse. Si una
            limitación no fuera aplicable a tu caso, esa limitación específica no aplica, pero las
            demás siguen vigentes.
          </p>
        </Section>

        <Section title="16. Indemnidad">
          <p>
            Te comprometés a mantener indemne a Rendi y a su equipo frente a cualquier reclamo,
            demanda, pérdida, daño o gasto razonable (incluidos honorarios legales) que surja de:
            (i) tu uso indebido del Servicio; (ii) el incumplimiento de estos Términos o de la
            ley; (iii) la violación de derechos de terceros; o (iv) el contenido que cargues.
          </p>
          <p>
            Esta cláusula no se aplica en la medida en que el reclamo se deba a nuestro propio
            dolo o culpa grave, ni alcanza a los derechos que la ley te reconoce como consumidor.
          </p>
        </Section>

        <Section title="17. Fuerza mayor">
          <p>
            Rendi no será responsable por incumplimientos o demoras causados por hechos fuera de
            su control razonable, tales como cortes de internet o de energía, fallas de
            proveedores de infraestructura o de datos, actos de autoridad, conflictos sociales,
            catástrofes naturales, pandemias u otros eventos de fuerza mayor o caso fortuito.
            Mientras dure el evento, las obligaciones afectadas quedan suspendidas y haremos lo
            razonable para restablecer el Servicio.
          </p>
        </Section>

        <Section title="18. Modificaciones del servicio y de los términos">
          <p>
            <strong className="text-ink-0">Del servicio.</strong> Rendi está en evolución
            constante: podemos agregar, cambiar o discontinuar funcionalidades para mejorar el
            producto. Vamos a evitar perjudicar funciones centrales de los planes pagos sin aviso
            razonable.
          </p>
          <p>
            <strong className="text-ink-0">De los términos.</strong> Podemos actualizar estos
            Términos. Si hay cambios materiales (por ejemplo, en precios, política de reembolso o
            manejo de datos), te lo comunicamos por email con al menos 15 días de anticipación.
          </p>
          <p>
            Si seguís usando Rendi después de la fecha en que entra en vigor el cambio, entendemos
            que aceptaste los nuevos Términos. Si no estás de acuerdo, podés cancelar tu
            suscripción en cualquier momento (sección 6).
          </p>
        </Section>

        <Section title="19. Defensa del Consumidor (Ley 24.240)">
          <p>
            Si sos consumidor o usuario final, te amparan los derechos de la Ley 24.240 de
            Defensa del Consumidor y normas complementarias. Ninguna cláusula de estos Términos
            debe interpretarse como una renuncia o restricción de esos derechos.
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Derecho de arrepentimiento.</strong> En las
              contrataciones a distancia podés arrepentirte dentro del plazo legal. Para
              ejercerlo está disponible el <strong className="text-ink-0">botón de
              arrepentimiento</strong> y el procedimiento detallado en nuestra{' '}
              <Link to="/reembolso" className="text-data-violet hover:underline">Política de Reembolso</Link>.
            </li>
            <li>
              <strong className="text-ink-0">Información clara.</strong> Procuramos informarte de
              forma cierta, clara y detallada las condiciones del Servicio, los precios y las
              características de cada plan.
            </li>
            <li>
              <strong className="text-ink-0">Vías de reclamo.</strong> Ante cualquier
              inconveniente, escribinos primero a{' '}
              <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">soporte@rendi.finance</a>:
              queremos resolverlo. Sin perjuicio de ello, podés acudir a la autoridad de
              aplicación y a los organismos de defensa del consumidor que correspondan a tu
              jurisdicción.
            </li>
          </ul>
        </Section>

        <Section title="20. Disposiciones generales, ley aplicable y jurisdicción">
          <ul>
            <li>
              <strong className="text-ink-0">Cesión.</strong> No podés ceder ni transferir tus
              derechos u obligaciones bajo estos Términos sin nuestro consentimiento previo. Rendi
              sí puede cederlos en el marco de una reorganización o transferencia del proyecto,
              preservando tus derechos.
            </li>
            <li>
              <strong className="text-ink-0">Divisibilidad (nulidad parcial).</strong> Si una
              cláusula se declarara inválida o inaplicable, las demás siguen plenamente vigentes,
              y la cláusula afectada se interpretará del modo más cercano posible a su intención
              original.
            </li>
            <li>
              <strong className="text-ink-0">Acuerdo completo.</strong> Estos Términos, junto con
              la Política de Privacidad y la Política de Reembolso, constituyen el acuerdo
              completo entre vos y Rendi respecto del Servicio, y reemplazan cualquier
              entendimiento previo sobre la misma materia.
            </li>
            <li>
              <strong className="text-ink-0">No renuncia.</strong> El hecho de que no exijamos el
              cumplimiento de una cláusula en un momento dado no implica renunciar a exigirla más
              adelante.
            </li>
          </ul>
          <p>
            <strong className="text-ink-0">Ley aplicable y jurisdicción.</strong> Estos Términos
            se rigen por las leyes de la República Argentina. Para cualquier controversia, las
            partes se someten a los tribunales ordinarios de la Ciudad Autónoma de Buenos Aires
            (CABA), sin perjuicio de las normas de competencia que protejan al consumidor.
          </p>
        </Section>

        <Section title="21. Contacto">
          <p>
            ¿Dudas, reclamos o sugerencias? Estamos del otro lado. Escribinos a{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
              soporte@rendi.finance
            </a>{' '}
            o mandanos un mensaje por{' '}
            <a href="https://wa.me/542914373695" target="_blank" rel="noopener noreferrer" className="text-data-violet hover:underline">
              WhatsApp
            </a>.
          </p>
        </Section>

        <div className="mt-16 pt-6 border-t border-line flex items-center justify-between text-xs text-ink-3">
          <Link to="/" className="hover:text-ink-1">← Volver al inicio</Link>
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
      <div className="text-sm text-ink-1 leading-relaxed space-y-3 [&_ul]:space-y-1.5 [&_ul]:pl-5 [&_ul]:list-disc [&_li]:marker:text-ink-3">
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
