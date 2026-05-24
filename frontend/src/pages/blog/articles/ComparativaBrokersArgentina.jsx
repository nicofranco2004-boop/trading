// /blog/comparativa-brokers-argentina

import BlogPost from '../../../components/blog/BlogPost'

const RELATED = [
  { to: '/brokers/cocos', label: 'Tracker para Cocos Capital', desc: 'Si ya estás en Cocos, así sumás otros brokers a tu tracking.' },
  { to: '/brokers/iol', label: 'Tracker para IOL Invertí Online', desc: 'IOL con FIFO automático y bonos AR.' },
  { to: '/blog/pnl-real-usd-blue-argentina', label: 'P&L real en USD blue', desc: 'Cómo medir tu performance real, sin la trampa de los pesos.' },
]

export default function ComparativaBrokersArgentina() {
  return (
    <BlogPost
      slug="comparativa-brokers-argentina"
      title="Cocos vs IOL vs Balanz vs Bull: qué broker AR conviene en 2026"
      description="Comparativa honesta de los 4 brokers más populares en Argentina: comisiones, catálogo, app, soporte. Cuál elegir según tu perfil de inversor."
      publishedAt="2026-05-24"
      category="Brokers AR"
      readTime="10 min"
      related={RELATED}
    >
      <p>
        Elegir el broker para invertir en Argentina es la primera decisión grande del
        inversor argentino, y suele tomarse a las apuradas, basada en lo que tira el
        primer YouTuber. Cocos, IOL, Balanz, Bull Market Brokers: los 4 más populares
        compiten por el mismo público pero tienen perfiles muy distintos.
      </p>

      <p>
        Esta comparativa es honesta — no recibimos comisión de ninguno por recomendarlos.
        Cada uno tiene sus ventajas y desventajas concretas. Te paso lo que importa para
        decidir.
      </p>

      <h2>Cocos Capital</h2>
      <p>
        El más nuevo de los populares (lanzado 2021), y el que mejor app tiene. Diseño
        moderno, onboarding rápido, comisiones competitivas. Apunta al inversor joven /
        millenial.
      </p>

      <h3>A favor</h3>
      <ul>
        <li><strong>App excelente</strong>: la UX más limpia del mercado AR. Onboarding en 5 minutos.</li>
        <li><strong>Comisiones bajas</strong>: 0% en CEDEARs, 0.6% en acciones AR, 0.5% en bonos.</li>
        <li><strong>FCI sin comisión de gestión propios</strong> (tipo SoftBank).</li>
        <li><strong>Soporte por chat</strong>: responden rápido vía WhatsApp y web.</li>
      </ul>

      <h3>En contra</h3>
      <ul>
        <li><strong>Catálogo de bonos limitado</strong>: faltan algunos corporativos y subasta primaria.</li>
        <li><strong>Sin operativa USA directa</strong>: solo CEDEARs, no acciones USA en NYSE.</li>
        <li><strong>Sin garantía SIPC</strong> (es broker AR, plata en Argentina).</li>
      </ul>

      <p><strong>Conviene para</strong>: inversor que arranca, prioriza app fácil y CEDEARs como vehículo principal de exposición USA.</p>

      <h2>IOL Invertí Online</h2>
      <p>
        El veterano. Más de 20 años de mercado argentino, catálogo gigante de bonos
        soberanos, CER, ONs, FCIs. Su app es funcional pero menos amigable que Cocos.
      </p>

      <h3>A favor</h3>
      <ul>
        <li><strong>Catálogo más completo de bonos AR</strong>: soberanos (canje 2020), CER, dollar linked, BOPREAL, ONs corporativas. Si invertís en bonos AR seriamente, IOL gana.</li>
        <li><strong>Subasta primaria</strong>: podés participar de licitaciones del Tesoro y BCRA.</li>
        <li><strong>Reportes contables sólidos</strong>: el reporte fiscal anual que entrega es de los mejores para el contador.</li>
        <li><strong>Estabilidad</strong>: institución consolidada, casi nunca tienen caídas.</li>
      </ul>

      <h3>En contra</h3>
      <ul>
        <li><strong>UX anticuada</strong>: la app y web se sienten de hace 10 años.</li>
        <li><strong>Comisiones más altas que Cocos</strong> en CEDEARs y acciones AR (~0.8-1%).</li>
        <li><strong>Curva de aprendizaje</strong>: el panel tiene mil opciones, ideal para experto pero abrumador al inicio.</li>
      </ul>

      <p><strong>Conviene para</strong>: inversor con foco en bonos AR (soberanos + CER), o que quiere participar de licitaciones primarias.</p>

      <h2>Balanz</h2>
      <p>
        Intermedio entre Cocos y IOL en complejidad. Tiene buena cobertura de productos, app
        decente y muchos servicios complementarios (FCI propios, research, asesoramiento
        para tickets grandes).
      </p>

      <h3>A favor</h3>
      <ul>
        <li><strong>Research propio</strong>: análisis fundamentales y técnicos de calidad.</li>
        <li><strong>Acceso a USA directo</strong>: podés operar NYSE/NASDAQ via Balanz USA.</li>
        <li><strong>Asesoramiento personalizado</strong> a partir de ciertos tickets.</li>
        <li><strong>Catálogo amplio</strong>: cubre desde acciones AR y CEDEARs hasta bonos y FCI internacionales.</li>
      </ul>

      <h3>En contra</h3>
      <ul>
        <li><strong>Comisiones medio-altas</strong> sin sumar volumen.</li>
        <li><strong>App correcta pero sin el polish de Cocos</strong>.</li>
        <li><strong>Operativa USA cobra mantenimiento mensual</strong> si saldo bajo.</li>
      </ul>

      <p><strong>Conviene para</strong>: inversor con tickets más grandes que quiere asesoramiento + acceso a NYSE directo desde la misma plataforma.</p>

      <h2>Bull Market Brokers (BMB)</h2>
      <p>
        El broker de los profesionales — el que más usan trading desks y inversores con
        carteras grandes. Mesa propia, terminales avanzadas, atención humana.
      </p>

      <h3>A favor</h3>
      <ul>
        <li><strong>Mesa de operaciones humana</strong>: llamás y ejecutan. No es app-only.</li>
        <li><strong>Acceso institucional</strong>: bonos, licitaciones, OTC, opciones, derivados.</li>
        <li><strong>Custodia internacional</strong> a través de socios USA (NYSE, opciones, ETFs).</li>
        <li><strong>Research técnico avanzado</strong>: análisis con TradingView integrado.</li>
      </ul>

      <h3>En contra</h3>
      <ul>
        <li><strong>App básica</strong>: hecha para que el cliente vea su cuenta, no para operar todo desde el celular.</li>
        <li><strong>Comisiones más altas</strong>: el modelo es servicio premium, no low-cost.</li>
        <li><strong>Mínimo de cuenta más elevado</strong> para acceder a mesa.</li>
      </ul>

      <p><strong>Conviene para</strong>: inversor con cartera grande (USD 50k+) que valora servicio humano y acceso a productos institucionales.</p>

      <h2>Comparativa rápida</h2>

      <table>
        <thead>
          <tr><th>Aspecto</th><th>Cocos</th><th>IOL</th><th>Balanz</th><th>Bull</th></tr>
        </thead>
        <tbody>
          <tr><td>App / UX</td><td>★★★★★</td><td>★★</td><td>★★★</td><td>★★</td></tr>
          <tr><td>Catálogo bonos AR</td><td>★★★</td><td>★★★★★</td><td>★★★★</td><td>★★★★</td></tr>
          <tr><td>Comisiones bajas</td><td>★★★★</td><td>★★★</td><td>★★★</td><td>★★</td></tr>
          <tr><td>Acceso NYSE directo</td><td>—</td><td>—</td><td>★★★★</td><td>★★★★</td></tr>
          <tr><td>Soporte humano</td><td>★★★</td><td>★★</td><td>★★★</td><td>★★★★★</td></tr>
          <tr><td>Reporte fiscal</td><td>★★★</td><td>★★★★</td><td>★★★★</td><td>★★★</td></tr>
        </tbody>
      </table>

      <h2>Conclusión: ¿hay que elegir uno?</h2>

      <p>
        La pregunta es trampa. La realidad es que <strong>muchos inversores argentinos
        terminan con cuentas en 2 o 3 brokers a la vez</strong>: Cocos para CEDEARs y app
        rápida, IOL para bonos AR, Balanz o Bull para acceso NYSE directo. No hay un broker
        que sea best-in-class en todo.
      </p>

      <p>
        El problema cuando tenés varias cuentas es <strong>visibilidad consolidada</strong>:
        cada broker te muestra solo lo suyo. Tu allocation real, tu P&L real en USD, tu
        exposición por geografía, todo eso queda fragmentado.
      </p>

      <p>
        Por eso construimos <a href="/">Rendi</a>: para que vos puedas usar Cocos + IOL + Balanz
        + Bull todos juntos y ver tu cartera consolidada en USD real, con FIFO automático y
        Coach IA con contexto completo. Sin necesidad de elegir un único broker.
      </p>

      <p>
        <a href="/login?mode=register">Crear cuenta gratis</a> · <a href="/planes">Ver planes</a>
      </p>
    </BlogPost>
  )
}
