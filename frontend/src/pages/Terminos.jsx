// Terminos — términos y condiciones de uso de Rendi.
// ════════════════════════════════════════════════════════════════════════════
// Página pública accesible sin login. Linkeada desde Planes.jsx, Landing.jsx
// y desde el footer general. Cubre uso del servicio, suscripciones, datos,
// responsabilidades. Sujeto a ley argentina.
//
// IMPORTANTE: este texto NO sustituye asesoría legal. Si el negocio crece,
// conviene que un abogado lo revise. Mientras tanto es la mejor versión que
// podemos sostener honestamente sobre cómo funciona Rendi hoy.

import { Link } from 'react-router-dom'
import RendiLogo from '../components/RendiLogo'
import PageMeta from '../components/PageMeta'

export default function Terminos() {
  return (
    <div className="min-h-screen bg-bg-0 text-ink-0">
      <PageMeta
        title="Términos y Condiciones — Rendi"
        description="Términos de uso de Rendi: qué hacemos y qué no, suscripciones Plus y Pro, manejo de datos, responsabilidades, jurisdicción argentina. Última actualización mayo 2026."
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
        <p className="font-mono text-[10px] uppercase tracking-caps text-ink-3 mb-2">Legal</p>
        <h1 className="text-3xl font-semibold tracking-tight mb-1">Términos y Condiciones</h1>
        <p className="text-sm text-ink-3 mb-10">Última actualización: 24 de mayo de 2026</p>

        <Section title="1. Quiénes somos">
          <p>
            Rendi es una herramienta web de seguimiento de portafolio de inversiones,
            operada por un equipo individual con domicilio en la República Argentina.
            El servicio se accede en <Code>rendi.finance</Code> y consume datos de
            mercado de terceros (Yahoo Finance, dolarapi.com, BCRA, data912.com,
            Google News y similares) sin filiación con ellos.
          </p>
        </Section>

        <Section title="2. Qué hace Rendi y qué NO hace">
          <p><strong className="text-ink-0">Rendi hace:</strong></p>
          <ul>
            <li>Te muestra tus posiciones y operaciones agrupadas por broker.</li>
            <li>Calcula P&L realizado y no realizado en USD con criterio FIFO.</li>
            <li>Te genera insights, reportes históricos y diagnósticos de tu cartera.</li>
            <li>Te ofrece un Coach IA (Claude Haiku) para responder preguntas sobre tus datos.</li>
          </ul>
          <p className="mt-4"><strong className="text-ink-0">Rendi NO hace y NO es:</strong></p>
          <ul>
            <li>
              <strong className="text-ink-0">No es un broker.</strong> No ejecuta órdenes
              de compra/venta. Las operaciones las hacés en tu broker real (Cocos, IOL,
              Schwab, Binance, etc.).
            </li>
            <li>
              <strong className="text-ink-0">No es asesoramiento financiero.</strong> Los
              análisis, scorecards y respuestas del Coach IA son herramientas
              informativas. Las decisiones de inversión son tuyas y a tu propio riesgo.
            </li>
            <li>
              <strong className="text-ink-0">No tenemos acceso a tu dinero.</strong> No
              hay integración bancaria, ni custodia, ni operatoria. Vos cargás los datos
              manualmente o vía CSV.
            </li>
          </ul>
        </Section>

        <Section title="3. Suscripciones y planes">
          <p>
            Rendi ofrece un plan gratuito ("Free") sin vencimiento y dos planes pagos
            ("Plus" y "Pro") con cuotas y features ampliados. Los precios se publican en{' '}
            <Link to="/planes" className="text-data-violet hover:underline">/planes</Link>.
          </p>
          <p>
            <strong className="text-ink-0">Cobramos en pesos argentinos</strong> al
            tipo de cambio blue del día, con referencia en dólares estadounidenses (USD).
            El precio en USD es el ancla; el monto exacto en ARS puede variar día a día.
            Verás el precio final en ARS al momento de confirmar el pago.
          </p>
          <p>
            <strong className="text-ink-0">Renovación automática.</strong> Las
            suscripciones se renuevan automáticamente al fin de cada período (mensual o
            anual) hasta que las canceles. Cada renovación se cobra al mismo medio de
            pago registrado.
          </p>
          <p>
            <strong className="text-ink-0">Cambio de plan.</strong> Podés cambiar entre
            Plus y Pro en cualquier momento desde{' '}
            <Link to="/planes" className="text-data-violet hover:underline">/planes</Link>.
            El crédito de tu período actual se reconvierte automáticamente al rate del
            plan nuevo. No te cobramos dos veces.
          </p>
          <p>
            <strong className="text-ink-0">Cancelación.</strong> Podés cancelar en
            cualquier momento desde{' '}
            <Link to="/config" className="text-data-violet hover:underline">/config</Link>.
            Tras cancelar, mantenés acceso a tu plan hasta el final del período ya
            cobrado. Después tu cuenta vuelve a Free automáticamente.
          </p>
          <p>
            <strong className="text-ink-0">Reembolsos.</strong> Mirá nuestra{' '}
            <Link to="/reembolso" className="text-data-violet hover:underline">política
            de reembolso</Link> para los detalles. Resumen: no devolvemos el monto del
            período ya cobrado; lo que tenés es acceso pleno hasta el final del período.
          </p>
        </Section>

        <Section title="4. Tus datos y privacidad">
          <p>
            Para usar Rendi tenés que crear una cuenta con tu email y una contraseña.
            Guardamos los datos que vos cargás (posiciones, operaciones, entradas
            mensuales) y los datos derivados que calculamos sobre ellos.
          </p>
          <p>
            <strong className="text-ink-0">Cómo usamos tus datos:</strong>
          </p>
          <ul>
            <li>
              Para ejecutar la lógica del servicio (calcular P&L, mostrar dashboards,
              generar reportes).
            </li>
            <li>
              Para entrenar el contexto del Coach IA <em>solo dentro de tu sesión</em>.
              Las consultas que le hacés al Coach se envían a Anthropic (Claude API) con
              un snapshot de tu cartera. Anthropic NO usa esos datos para entrenar sus
              modelos (per política comercial de Anthropic).
            </li>
            <li>
              Para enviarte correos transaccionales (welcome, recibo, recordatorio de
              vencimiento, alertas relevantes).
            </li>
          </ul>
          <p>
            <strong className="text-ink-0">Lo que NO hacemos:</strong>
          </p>
          <ul>
            <li>NO vendemos ni cedemos tus datos a terceros con fines comerciales.</li>
            <li>NO hacemos profiling para publicidad.</li>
            <li>NO compartimos tu información con tu broker, AFIP, ARCA ni ningún ente regulatorio (salvo orden judicial).</li>
          </ul>
          <p>
            <strong className="text-ink-0">Eliminación de cuenta.</strong> Escribinos a{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">soporte@rendi.finance</a>{' '}
            para solicitar la baja total. Te respondemos en menos de 5 días hábiles y
            eliminamos tu cuenta + datos asociados de forma permanente.
          </p>
        </Section>

        <Section title="5. Responsabilidades">
          <p>
            Rendi se ofrece "tal como está" ("as-is"). Hacemos nuestro mejor esfuerzo
            para que la información sea precisa y el servicio esté disponible 24/7,
            pero <strong className="text-ink-0">no garantizamos</strong>:
          </p>
          <ul>
            <li>
              La exactitud de los precios de mercado en tiempo real (provienen de Yahoo
              Finance, data912.com y otras fuentes públicas que pueden tener delays o errores).
            </li>
            <li>
              La disponibilidad ininterrumpida (puede haber mantenimientos, caídas
              transitorias del backend o de los proveedores de datos).
            </li>
            <li>
              La precisión de los análisis del Coach IA. Es una herramienta
              probabilística que puede equivocarse.
            </li>
          </ul>
          <p>
            <strong className="text-ink-0">No somos responsables por pérdidas
            financieras</strong> que resulten de decisiones de inversión tomadas a
            partir de la información que muestra Rendi. Repetimos: Rendi es una
            herramienta de seguimiento e informativa, no un asesor financiero registrado
            ante CNV.
          </p>
        </Section>

        <Section title="6. Uso aceptable">
          <p>
            Está prohibido usar Rendi para:
          </p>
          <ul>
            <li>Compartir credenciales o usar la cuenta de otra persona.</li>
            <li>Intentar acceder a datos de otros usuarios.</li>
            <li>Hacer scraping masivo, ataques DoS o ingeniería inversa del sistema.</li>
            <li>Usar el Coach IA para generar contenido que viole los términos de Anthropic (contenido ilegal, deepfakes, spam, etc.).</li>
            <li>Re-vender el acceso a Rendi o compartir tu cuenta con múltiples personas.</li>
          </ul>
          <p>
            Reservamos el derecho de suspender o cancelar cuentas que incurran en
            estos comportamientos, sin reembolso.
          </p>
        </Section>

        <Section title="7. Propiedad intelectual">
          <p>
            El nombre <strong className="text-ink-0">Rendi</strong>, el logo (la "R"
            violeta), el dominio rendi.finance, el diseño de la interfaz y el código
            del software son propiedad exclusiva del equipo de Rendi. Están protegidos
            por las leyes argentinas e internacionales de propiedad intelectual.
          </p>
          <p>
            <strong className="text-ink-0">Tu contenido sigue siendo tuyo.</strong> Los
            datos que cargás (posiciones, operaciones, etc.) son y siguen siendo de tu
            propiedad. Rendi solo tiene una licencia limitada para procesarlos y
            mostrártelos como parte del servicio. Si cancelás tu cuenta, los podés
            exportar y eliminamos los nuestros.
          </p>
          <p>
            No está permitido copiar, modificar, distribuir o crear obras derivadas
            de la marca o el diseño de Rendi sin autorización por escrito.
          </p>
        </Section>

        <Section title="8. Limitación de responsabilidad">
          <p>
            En la máxima medida permitida por la ley argentina:
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Rendi no se hace responsable</strong> por
              pérdidas financieras, lucro cesante, oportunidades perdidas o daños
              indirectos derivados del uso de la herramienta. Las decisiones de inversión
              son tuyas y a tu propio riesgo.
            </li>
            <li>
              <strong className="text-ink-0">Cap de responsabilidad económica:</strong>{' '}
              en caso de que un tribunal nos encontrara responsables por un perjuicio
              relacionado al servicio, nuestra responsabilidad total se limita al monto
              que pagaste en los 12 meses anteriores al hecho que generó el reclamo (o
              a USD 100 si nunca pagaste).
            </li>
            <li>
              <strong className="text-ink-0">No garantizamos disponibilidad ininterrumpida.</strong>{' '}
              Hacemos nuestro mejor esfuerzo (99% uptime target) pero pueden ocurrir
              caídas por mantenimiento, problemas de proveedores (Vercel, Railway,
              Anthropic), eventos de fuerza mayor o fallas técnicas.
            </li>
            <li>
              <strong className="text-ink-0">No garantizamos la precisión de los datos
              de mercado.</strong> Los precios vienen de fuentes terceras (Yahoo Finance,
              data912.com) que pueden tener delays, errores o gaps. Verificá siempre
              en tu broker antes de tomar decisiones importantes.
            </li>
          </ul>
          <p>
            Si la legislación argentina aplicable a vos no permite alguna de estas
            limitaciones, esa limitación específica no aplica, pero las demás siguen
            vigentes.
          </p>
        </Section>

        <Section title="9. Cookies y tracking">
          <p>
            Rendi usa <strong className="text-ink-0">solo cookies funcionales esenciales</strong>{' '}
            para operar (sesión de login, preferencia de tema). No usamos cookies de
            tracking publicitario, pixels de Facebook, Google Ads conversion tracking,
            ni terceros con fines de profiling.
          </p>
          <p>
            Por eso no mostramos banner de consentimiento de cookies — no hay nada que
            aceptar más allá de las cookies funcionales que la app necesita para que
            puedas usar tu sesión.
          </p>
          <p>
            Para detalles completos sobre el manejo de datos, ver nuestra{' '}
            <Link to="/privacidad" className="text-data-violet hover:underline">
              Política de Privacidad
            </Link>.
          </p>
        </Section>

        <Section title="10. Cambios a estos términos">
          <p>
            Podemos actualizar estos términos. Si hay cambios materiales (precio,
            política de reembolso, manejo de datos), te lo comunicamos por email con al
            menos 15 días de anticipación.
          </p>
          <p>
            Si seguís usando Rendi después de la fecha en que entra en vigor el cambio,
            entendemos que aceptaste los nuevos términos. Si no estás de acuerdo, podés
            cancelar tu suscripción en cualquier momento.
          </p>
        </Section>

        <Section title="11. Jurisdicción y contacto">
          <p>
            Estos términos se rigen por las leyes de la República Argentina. Cualquier
            disputa se resuelve ante los tribunales ordinarios de la Ciudad Autónoma de
            Buenos Aires.
          </p>
          <p>
            Para cualquier consulta, escribinos a{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
              soporte@rendi.finance
            </a>{' '}
            o por{' '}
            <a href="https://wa.me/5491134567890" target="_blank" rel="noopener noreferrer" className="text-data-violet hover:underline">
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
