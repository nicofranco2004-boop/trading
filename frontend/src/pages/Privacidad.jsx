// Privacidad — política de privacidad y manejo de datos personales.
// ════════════════════════════════════════════════════════════════════════════
// Página pública accesible sin login. Linkeada desde el footer de Landing.
// Cumple básicamente con LATAM data protection (Ley 25.326 AR + GDPR-like).
//
// IMPORTANTE: este texto NO sustituye asesoría legal. Si Rendi crece
// significativamente, conviene que un abogado lo revise.

import { Link } from 'react-router-dom'
import RendiLogo from '../components/RendiLogo'
import PageMeta from '../components/PageMeta'

export default function Privacidad() {
  return (
    <div className="min-h-screen bg-bg-0 text-ink-0">
      <PageMeta
        title="Política de Privacidad — Rendi"
        description="Cómo Rendi maneja tus datos personales: qué recolectamos, para qué, con quién compartimos, cómo proteger y cómo solicitar eliminación. Compliance Ley 25.326 (Argentina)."
        canonical="/privacidad"
      />

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
        <p className="font-mono text-[11px] uppercase tracking-caps text-ink-2 mb-2">Legal</p>
        <h1 className="text-3xl font-semibold tracking-tight mb-1">Política de Privacidad</h1>
        <p className="text-sm text-ink-3 mb-10">Última actualización: 24 de mayo de 2026</p>

        {/* Resumen prominente */}
        <div className="border border-data-violet/40 bg-data-violet/[0.06] rounded-lg p-5 mb-10">
          <p className="text-[10px] font-mono uppercase tracking-caps text-data-violet mb-1.5">Resumen rápido</p>
          <ul className="text-sm text-ink-1 leading-relaxed space-y-1.5 list-disc pl-5 [&_li]:marker:text-data-violet">
            <li>Guardamos solo lo que vos cargás (operaciones, posiciones, configuración) + tu email.</li>
            <li>No vendemos, alquilamos ni compartimos tus datos con fines comerciales.</li>
            <li>Compartimos datos mínimos con: Anthropic (Claude), Resend (emails), Rebill (pagos).</li>
            <li>Podés solicitar eliminación total de tu cuenta + datos en cualquier momento.</li>
            <li>Sujeto a Ley 25.326 (Protección de Datos Personales, Argentina).</li>
          </ul>
        </div>

        <Section title="1. Quiénes somos">
          <p>
            Rendi es operado por un equipo individual con domicilio en la República
            Argentina. Para temas de privacidad, escribinos a{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
              soporte@rendi.finance
            </a>.
          </p>
        </Section>

        <Section title="2. Qué datos recolectamos">
          <p><strong className="text-ink-0">Datos que vos cargás:</strong></p>
          <ul>
            <li>Email y contraseña al registrarte.</li>
            <li>Nombre opcional (display).</li>
            <li>Posiciones de inversión (broker, ticker, cantidad, precio de compra).</li>
            <li>Operaciones (compras, ventas, dividendos, depósitos, retiros).</li>
            <li>Datos mensuales (entradas de cash flow por broker).</li>
            <li>Perfil de inversor (cuestionario opcional — horizonte, tolerancia al riesgo).</li>
            <li>Hechos persistentes que le aclarás al Coach IA.</li>
          </ul>
          <p className="mt-4"><strong className="text-ink-0">Datos técnicos que generamos automáticamente:</strong></p>
          <ul>
            <li>IP de tus requests (para rate limiting y debugging).</li>
            <li>User-Agent del browser (Safari, Chrome, etc.).</li>
            <li>Timestamps de login y de creación de cuenta.</li>
            <li>Logs de errores (sin información personal sensible).</li>
            <li>Token de push notifications si autorizaste.</li>
          </ul>
          <p className="mt-4"><strong className="text-ink-0">Lo que NO recolectamos:</strong></p>
          <ul>
            <li>Datos bancarios o de tarjetas (los maneja Rebill, no nosotros).</li>
            <li>Credenciales de brokers (nunca te pedimos passwords de Cocos, IOL, etc.).</li>
            <li>Información personal sensible (salud, política, religión, orientación).</li>
            <li>Tracking publicitario o cookies de terceros para advertising.</li>
          </ul>
        </Section>

        <Section title="3. Para qué usamos tus datos">
          <ul>
            <li>
              <strong className="text-ink-0">Ejecutar el servicio</strong> — calcular P&L,
              mostrar dashboards, generar reportes, aplicar FIFO al vender.
            </li>
            <li>
              <strong className="text-ink-0">Entrenar el contexto del Coach IA</strong> —
              cuando le hacés una consulta, mandamos un snapshot de tu cartera a Anthropic
              (Claude) para que pueda responder con contexto. <em>Anthropic NO usa esos
              datos para entrenar sus modelos comerciales</em>, según su política comercial.
            </li>
            <li>
              <strong className="text-ink-0">Comunicación transaccional</strong> — emails de
              welcome, recibo de pago, recordatorio de vencimiento, alertas relevantes.
            </li>
            <li>
              <strong className="text-ink-0">Seguridad</strong> — rate limiting,
              detección de fraude/abuse, auditoría de billing events.
            </li>
            <li>
              <strong className="text-ink-0">Mejorar el producto</strong> — agregamos
              datos anonimizados para entender patrones de uso (cantidad de operaciones
              promedio, brokers más usados, etc.). No identificamos a usuarios individuales
              en estos analytics.
            </li>
          </ul>
        </Section>

        <Section title="4. Con quién compartimos">
          <p>
            Trabajamos con proveedores third-party para algunas operaciones específicas.
            Compartimos solo el mínimo dato necesario:
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Anthropic (Claude API)</strong> — recibe el
              snapshot de tu cartera + tu consulta cuando usás el Coach IA. Política:{' '}
              <a href="https://www.anthropic.com/legal/privacy" target="_blank" rel="noreferrer noopener" className="text-data-violet hover:underline">anthropic.com/legal/privacy</a>.
            </li>
            <li>
              <strong className="text-ink-0">Resend (envío de emails)</strong> — recibe
              tu email + el contenido del mensaje transaccional. Política:{' '}
              <a href="https://resend.com/legal/privacy-policy" target="_blank" rel="noreferrer noopener" className="text-data-violet hover:underline">resend.com/legal/privacy-policy</a>.
            </li>
            <li>
              <strong className="text-ink-0">Rebill (procesamiento de pagos)</strong> —
              recibe tu email + monto del cobro + metadata de tu suscripción. No vemos
              tu tarjeta, solo Rebill. Política:{' '}
              <a href="https://www.rebill.com/legal/privacy" target="_blank" rel="noreferrer noopener" className="text-data-violet hover:underline">rebill.com/legal/privacy</a>.
            </li>
            <li>
              <strong className="text-ink-0">Vercel (hosting frontend) + Railway (hosting backend)</strong>{' '}
              — almacenan y sirven el código y los datos. Compliance SOC 2 ambos.
            </li>
            <li>
              <strong className="text-ink-0">Google Search Console + Google Fonts</strong> —
              datos agregados de búsqueda y uso de tipografías. Sin acceso a tus datos
              de cartera.
            </li>
          </ul>
          <p>
            <strong className="text-ink-0">No vendemos, alquilamos, ni cedemos tus datos a terceros</strong>{' '}
            con fines comerciales, publicitarios o de profiling.
          </p>
        </Section>

        <Section title="5. Cookies y tracking">
          <p>
            Rendi usa cookies <strong className="text-ink-0">funcionales esenciales</strong> únicamente:
          </p>
          <ul>
            <li>
              <strong className="text-ink-0">Cookie de sesión HttpOnly</strong> — para mantener tu login.
              Necesaria para que funcione la app. Vence a los 7 días o cuando cerrás sesión.
            </li>
            <li>
              <strong className="text-ink-0">localStorage</strong> — guarda tu preferencia de tema (oscuro/claro)
              y un snapshot mínimo de user (nombre, tier) para que la UI no parpadee al cargar. Sin sensitive data.
            </li>
          </ul>
          <p className="mt-4">
            <strong className="text-ink-0">NO usamos:</strong> cookies de tracking publicitario,
            pixels de Facebook, Google Ads conversion tracking, ni third-party trackers.
            Por eso no mostramos banner de consentimiento de cookies — no hay nada que aceptar.
          </p>
        </Section>

        <Section title="6. Cuánto tiempo guardamos tus datos">
          <p>
            Mientras tu cuenta esté activa, guardamos tus datos para que puedas seguir
            usando Rendi. Si cancelás tu suscripción y volvés a Free, los datos siguen
            disponibles para vos en tu cuenta Free.
          </p>
          <p>
            <strong className="text-ink-0">Si solicitás eliminación total</strong> (ver
            sección 7), borramos tus datos personales en un plazo máximo de 30 días.
            Excepción: ciertos datos pueden retenerse por obligación legal (registros
            de transacciones para AFIP, billing events para auditoría) por hasta 10 años.
          </p>
          <p>
            <strong className="text-ink-0">Si tu cuenta queda inactiva por más de 24 meses</strong>{' '}
            (sin login y sin suscripción activa), te avisamos por email y procedemos a
            eliminarla automáticamente si no respondés en 30 días.
          </p>
        </Section>

        <Section title="7. Tus derechos (Ley 25.326 de Protección de Datos Personales)">
          <p>
            Como titular de datos personales en Argentina, tenés derecho a:
          </p>
          <ul>
            <li><strong className="text-ink-0">Acceso</strong> — ver qué datos tuyos tenemos.</li>
            <li><strong className="text-ink-0">Rectificación</strong> — corregir datos incorrectos.</li>
            <li><strong className="text-ink-0">Eliminación / supresión</strong> — pedir que borremos tus datos.</li>
            <li><strong className="text-ink-0">Portabilidad</strong> — exportar tus datos en CSV (lo podés hacer desde Importes / Reportes en la app).</li>
            <li><strong className="text-ink-0">Oposición</strong> — pedir que dejemos de procesar tus datos para fines específicos (ej. analytics).</li>
          </ul>
          <p>
            Para ejercer cualquiera de estos derechos, escribinos a{' '}
            <a href="mailto:soporte@rendi.finance" className="text-data-violet hover:underline">
              soporte@rendi.finance
            </a>{' '}
            con el asunto "Derecho de [acceso / rectificación / eliminación / etc]".
            Te respondemos en menos de 10 días hábiles.
          </p>
          <p>
            <strong className="text-ink-0">Autoridad de control:</strong> Dirección Nacional
            de Protección de Datos Personales (Agencia de Acceso a la Información Pública).
            Podés presentar reclamos directamente ante esa autoridad si considerás que
            tus derechos no fueron respetados.
          </p>
        </Section>

        <Section title="8. Seguridad">
          <p>
            Aplicamos medidas técnicas y organizativas razonables para proteger tus datos:
          </p>
          <ul>
            <li>HTTPS obligatorio en todo el tráfico (HSTS preload).</li>
            <li>Contraseñas con hash bcrypt (no almacenamos passwords en texto plano).</li>
            <li>Cookies HttpOnly + Secure (no accesibles desde JavaScript).</li>
            <li>Rate limiting para prevenir ataques de fuerza bruta.</li>
            <li>Validación de signatures en webhooks (Rebill).</li>
            <li>Backups automáticos diarios de la base de datos.</li>
            <li>Acceso a producción restringido al equipo de Rendi.</li>
          </ul>
          <p>
            En caso de incidente de seguridad que afecte tus datos, te notificaremos
            por email dentro de las 72 horas y reportaremos al organismo de control
            según corresponda.
          </p>
        </Section>

        <Section title="9. Menores de edad">
          <p>
            Rendi no está dirigido a menores de 18 años. Si descubrimos que un menor
            creó una cuenta, procederemos a eliminarla. Si sos padre/madre/tutor y
            sospechás que tu hijo/a usó Rendi sin autorización, escribinos.
          </p>
        </Section>

        <Section title="10. Cambios a esta política">
          <p>
            Podemos actualizar esta política. Si hay cambios materiales (qué datos
            recolectamos, con quién compartimos, derechos), te lo comunicamos por email
            con al menos 15 días de anticipación.
          </p>
          <p>
            La fecha de "Última actualización" arriba de esta página indica la versión vigente.
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
