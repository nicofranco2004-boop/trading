// /guia/coach-ia — sección 4 del manual

import GuidePage from '../../components/guide/GuidePage'

export default function CoachIA() {
  return (
    <GuidePage
      section="4 de 6"
      title="Coach IA"
      intro="Cómo funciona el asistente IA: 12 preguntas guiadas, chat libre (Pro), memoria persistente y cuotas semanales."
      prev={{ to: '/guia/insights-y-reportes', label: 'Insights y reportes' }}
      next={{ to: '/guia/novedades', label: 'Novedades' }}
      metaTitle="Coach IA — Guía Rendi"
      metaDescription="Cómo usar el Coach IA de Rendi: preguntas guiadas, chat libre Pro, memoria persistente y cuotas semanales."
      canonicalPath="/guia/coach-ia"
    >
      <h2>Qué es el Coach IA</h2>
      <p>
        Asistente conversacional con contexto completo de tu cartera. Usa{' '}
        <strong>Claude Haiku 4.5</strong> (Anthropic) y recibe un snapshot de tus
        posiciones + operaciones + perfil cada vez que le preguntás algo. Eso le
        permite responder cosas específicas tuyas, no respuestas genéricas.
      </p>

      <h2>Cómo abrirlo</h2>
      <p>
        En el sidebar (desktop) o en cualquier página, botón "Coach IA" con ícono de
        chispas. Se abre un drawer lateral con el chat. También aparece como FAB en
        algunas pantallas (mobile).
      </p>

      <h2>12 preguntas guiadas (todos los planes)</h2>
      <p>
        Las preguntas guiadas son chips clickeables que ya te traen una pregunta lista.
        Útiles si no sabés qué preguntar. Algunos ejemplos:
      </p>
      <ul>
        <li>"¿Cuánto realmente gané este año en USD?"</li>
        <li>"¿Dónde está concentrado el riesgo de mi cartera?"</li>
        <li>"¿Qué activo me está costando más plata?"</li>
        <li>"¿Está cara mi posición más grande?"</li>
        <li>"¿Cuándo reportan earnings los activos de mi cartera?"</li>
        <li>"¿Mi cartera coincide con mi perfil de inversor?"</li>
      </ul>

      <h2>Chat libre (solo Pro)</h2>
      <p>
        Plus y Free están limitados a las 12 preguntas guiadas. <strong>Pro</strong>{' '}
        desbloquea chat libre — preguntás cualquier cosa en texto libre, el bot
        responde con causalidad ("por qué pasó X", no solo "qué pasó").
      </p>
      <p>
        Ejemplos de preguntas que solo Pro puede hacer:
      </p>
      <ul>
        <li>"¿Por qué bajó mi cartera este mes específicamente?"</li>
        <li>"Recordá que el AL30 lo tengo en IOL, no en Cocos."</li>
        <li>"Compará mi exposición a tech vs el S&amp;P 500."</li>
        <li>"Si mañana vendo NVDA, ¿cuánto declaro a AFIP?"</li>
      </ul>

      <h2>Follow-ups (solo Pro)</h2>
      <p>
        En Pro, cada respuesta del bot tiene un input al pie para hacer una pregunta
        de seguimiento sin perder el contexto. Útil para profundizar un análisis:
        primera pregunta general, segunda pregunta sobre un detalle específico.
      </p>

      <h2>Memoria persistente (solo Pro)</h2>
      <p>
        El bot puede equivocarse en cosas que vos sabés mejor que él (ej. dice "perdiste
        X" pero en realidad el broker te devolvió el monto). En esos casos hacés click
        en <strong>"Corregir bot"</strong> debajo de la respuesta y le aclarás. El bot
        guarda ese hecho como "verdad declarada" y lo respeta en futuras sesiones —
        no contradice lo que vos le confirmaste antes.
      </p>
      <p>
        Podés ver y gestionar tus hechos guardados desde{' '}
        <strong>Config → Memoria del Coach</strong>.
      </p>

      <h2>Cuotas semanales</h2>
      <p>
        Para mantener costos sostenibles, hay límites de uso. Ventana móvil de 7 días
        (no resetea el lunes — el slot más viejo se libera cada día):
      </p>
      <ul>
        <li><strong>Free</strong>: 6 análisis + 3 chat por semana.</li>
        <li><strong>Plus</strong>: 6 análisis + 9 chat por semana (3× más chat que Free).</li>
        <li><strong>Pro</strong>: 60 análisis + 40 chat por semana + memoria persistente.</li>
      </ul>
      <p>
        Cuando llegás al cap, te avisamos cuándo se libera la próxima consulta. Si
        querés más cuota antes, podés <a href="/planes">cambiar de plan</a> en cualquier
        momento.
      </p>

      <h2>Qué puede hacer el bot</h2>
      <p>
        El bot tiene <strong>tools</strong> que le permiten consultar datos en tiempo
        real más allá del snapshot de tu cartera:
      </p>
      <ul>
        <li>Buscar precios fundamentales (P/E, dividend yield, market cap) de cualquier ticker.</li>
        <li>Generar un <strong>scorecard de valor</strong> tipo Smart Investors (Fair Value, PEG, ROE, payout, etc.).</li>
        <li>Buscar próximos earnings.</li>
        <li>Calcular tu P&amp;L realizado vs no realizado por broker.</li>
        <li>Mostrar metadata de bonos AR (AL30, GD30, TX26, etc.).</li>
        <li>Buscar noticias recientes de tus activos.</li>
      </ul>

      <h2>Tips para sacarle más jugo</h2>
      <ul>
        <li>Sé específico: "¿cómo está NVDA?" → mejor: "¿está cara NVDA a precio actual? ¿qué dice su P/E vs su sector?".</li>
        <li>Pedile comparaciones: "¿mi cartera vs el Merval este año?".</li>
        <li>Usá follow-ups para profundizar: primera pregunta general, segunda más específica.</li>
        <li>Aclarale hechos que él no puede saber: "tengo XYZ que no está cargado en Rendi" / "el AL30 lo vendí ayer pero todavía no lo cargué".</li>
      </ul>
    </GuidePage>
  )
}
