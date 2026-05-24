// /guia/empezar — sección 1 del manual

import GuidePage from '../../components/guide/GuidePage'

export default function Empezar() {
  return (
    <GuidePage
      section="1 de 6"
      title="Empezar con Rendi"
      intro="Crear tu cuenta, agregar tu primer broker y cargar tu primera operación. En 10 minutos tenés tu cartera lista."
      next={{ to: '/guia/cartera-y-operaciones', label: 'Cartera y operaciones' }}
      metaTitle="Empezar con Rendi — Guía"
      metaDescription="Cómo crear cuenta en Rendi, agregar tu primer broker (Cocos, IOL, Schwab, Binance) y cargar tu primera operación. Setup en 10 minutos."
      canonicalPath="/guia/empezar"
    >
      <h2>1. Crear tu cuenta</h2>
      <p>
        Andá a <a href="/login?mode=register">Crear cuenta gratis</a>. Te pedimos
        email + contraseña. Te llega un código de 6 dígitos al mail para verificar
        que sos vos (revisá Spam si no aparece en 2 minutos). Listo, ya entrás.
      </p>
      <p>
        Antes de cargar tu data real, podés <a href="/?demo=1">probar la demo</a>{' '}
        — es Rendi con datos de un inversor ficticio. Vez todo sin riesgo de
        ensuciar tu cuenta.
      </p>

      <h2>2. Agregar tu primer broker</h2>
      <p>
        Andá a <strong>Posiciones</strong> y abrí el panel de brokers (botón
        "Gestionar brokers"). Agregá uno con:
      </p>
      <ul>
        <li><strong>Nombre</strong>: como vos lo identifiques (ej. "Cocos", "IOL", "Binance").</li>
        <li><strong>Moneda</strong>: ARS (Cocos, IOL, Balanz, Bull), USD (Schwab, IBKR) o USDT (Binance, exchanges crypto).</li>
      </ul>
      <p>
        Plan Free permite 1 broker. Plus hasta 3. Pro ilimitados.
      </p>

      <h2>3. Cargar tu primera operación</h2>
      <p>
        Tenés dos caminos según cuánta data tengas:
      </p>

      <h3>Opción A: Importar CSV (rápido)</h3>
      <p>
        Si ya operás hace un tiempo, bajá el historial de tu broker en CSV y subílo
        en <strong>Importes</strong>. Rendi reconoce los formatos de Cocos, IOL,
        Balanz, Schwab y Binance automáticamente. Mapeamos las columnas, te mostramos
        un preview antes de confirmar, y creamos las posiciones + operaciones de una.
      </p>
      <p>
        Si tu broker no está en la lista, exportá igual el CSV y mandalo a{' '}
        <a href="mailto:soporte@rendi.finance">soporte@rendi.finance</a> — sumamos
        el parser nuevo en 1-2 días.
      </p>

      <h3>Opción B: Cargar manualmente</h3>
      <p>
        Andá a <strong>Posiciones → Nueva posición</strong> (botón "+ Nueva posición"
        en desktop, FAB "+" en mobile). Completás:
      </p>
      <ul>
        <li><strong>Broker</strong> (el que creaste antes).</li>
        <li><strong>Activo</strong>: ticker (ej. NVDA, AAPL.BA, AL30, BTC). Hay autocomplete.</li>
        <li><strong>Cantidad</strong>: unidades (acciones, bonos VN, tokens).</li>
        <li><strong>Precio promedio de compra</strong>: en la moneda nativa del activo.</li>
        <li><strong>Fecha</strong> opcional (default hoy).</li>
      </ul>
      <p>
        Si vendiste algo en el pasado, después lo cargás en <strong>Operaciones →
        Nueva operación → Venta</strong>. Rendi aplica FIFO automático con tus lotes.
      </p>

      <h2>4. Cuestionario de perfil de inversor (opcional)</h2>
      <p>
        En <strong>Perfil de inversor</strong> respondés 7-8 preguntas sobre tu
        horizonte, tolerancia al drawdown y objetivos. <em>No es obligatorio</em>,
        pero si lo llenás, Insights compara tu cartera real contra lo que vos declaraste
        y te marca incoherencias (ej. "decís perfil conservador pero tenés 70% en
        crypto").
      </p>

      <h2>5. Próximos pasos</h2>
      <p>
        Una vez que tenés data cargada:
      </p>
      <ul>
        <li><strong>Dashboard</strong>: tu portfolio total en USD, P&amp;L del mes, evolución.</li>
        <li><strong>Insights</strong>: 5 cards de análisis automático.</li>
        <li><strong>Coach IA</strong>: 12 preguntas guiadas (Free) o chat libre (Pro).</li>
      </ul>
    </GuidePage>
  )
}
