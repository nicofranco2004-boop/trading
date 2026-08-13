// /guia/insights-y-reportes — sección 3 del manual

import GuidePage from '../../components/guide/GuidePage'
import AdvisorNote from '../../components/guide/AdvisorNote'
import ReturnsDiagram from '../../components/guide/ReturnsDiagram'

export default function InsightsYReportes() {
  return (
    <GuidePage
      n={3}
      title="Insights y reportes"
      intro="Las 5 cards de análisis automático, el timeline histórico de 12 meses, los detectores de comportamiento y cómo exportar el CSV para tu contador."
      prev={{ to: '/guia/cartera-y-operaciones', label: 'Cartera y operaciones' }}
      next={{ to: '/guia/coach-ia', label: 'Rendi AI' }}
      metaTitle="Insights y reportes — Guía Rendi"
      metaDescription="Las 5 cards de Insights, timeline histórico, 12 detectores de comportamiento y export CSV consolidado para AFIP en Rendi."
      canonicalPath="/guia/insights-y-reportes"
    >
      <AdvisorNote>
        <p>
          Este análisis es <strong>por cliente</strong>: lo ves entrando a su cuenta, y lo
          ves <strong>completo</strong> —con lente Pro— aunque el cliente esté en plan
          Free. Es lo que conviene mirar antes de llamarlo: dónde está concentrado, qué le
          rindió y qué no.
        </p>
        <p>
          Dos cosas de acá tienen su versión propia del lado tuyo, y están en la sección
          Para asesores:
        </p>
        <ul>
          <li>
            Para <strong>mandarle</strong> algo al cliente, no exportes el CSV: generá el{' '}
            <strong>informe del período</strong> desde Tu libro, que sale listo y con tu
            logo.
          </li>
          <li>
            El número de <strong>tu gestión</strong> no está en esta sección: es el{' '}
            <strong>TWR del libro</strong>, y vive en Tu libro. Descuenta los depósitos y
            retiros del cliente, así mide tus decisiones y no cuánta plata puso él.
          </li>
        </ul>
      </AdvisorNote>

      <h2>Las 5 cards de Insights</h2>
      <p>
        En <strong>Insights</strong> tenés 5 análisis automáticos de tu cartera:
      </p>

      <h3>1. Distribución por activo</h3>
      <p>
        Allocation real de tu portfolio: % en acciones AR, % en CEDEARs, % en bonos
        AR, % en crypto, % en cash. Comparado con benchmarks típicos por perfil de
        inversor (conservador, moderado, agresivo).
      </p>

      <h3>2. Horizonte declarado vs composición</h3>
      <p>
        Si llenaste el cuestionario, comparamos tu horizonte declarado (corto/medio/largo
        plazo) con la duración real de tus activos. Sirve para detectar incoherencias —
        ej. "decís horizonte 10+ años pero tu cartera está 80% en cash y bonos cortos".
      </p>

      <h3>3. Tolerancia drawdown vs realidad</h3>
      <p>
        Calculamos el drawdown máximo real de tu cartera (pico-a-valle) y lo comparamos
        con el drawdown que dijiste tolerar. Si superás el límite, te alertamos.
      </p>

      <h3>4. Concentración top 3</h3>
      <p>
        Qué % de tu portfolio está en tus 3 activos más grandes. Más de 60% = alta
        concentración (mayor riesgo). Te muestra cuáles son y sugiere si conviene
        rebalancear.
      </p>

      <h3>5. Coherencia objetivo</h3>
      <p>
        Si tenés objetivos cargados (Goals), evalúa si tu asset allocation actual te
        acerca o aleja de cada objetivo.
      </p>

      <p>
        <strong>Free</strong> ve el diagnóstico completo, con las métricas de riesgo
        (Sharpe, Sortino, alfa…) bloqueadas. <strong>Plus y Pro</strong> las desbloquean.
      </p>

      <h2>Reportes históricos</h2>
      <p>
        En <strong>Reportes</strong> ves un timeline cronológico de tu cartera. Vista
        principal: 12 meses con métricas por mes (delta % en USD, P&amp;L realizado,
        depósitos, retiros). Cada mes se puede expandir para ver las semanas adentro.
      </p>
      <p>
        Tabs disponibles arriba: <strong>Día</strong> (últimos 7 días),{' '}
        <strong>Semana</strong> (semana actual), <strong>Mes</strong> (vista default
        12 meses), <strong>Año</strong> (años visibles).
      </p>

      <h2>Detectores de comportamiento</h2>
      <p>
        Cada reporte mensual viene con "insights" auto-generados por reglas heurísticas
        (no IA — son detectores deterministas). Algunos ejemplos:
      </p>
      <ul>
        <li><strong>Streak / Reversal</strong>: rachas de meses ganando o perdiendo.</li>
        <li><strong>Dividend Heavy</strong>: si más del X% del mes vino de dividendos.</li>
        <li><strong>FOMO Buy</strong>: si compraste cerca del techo histórico.</li>
        <li><strong>Loss Aversion</strong>: si vendiste activos ganadores y mantuviste perdedores.</li>
        <li><strong>Anchoring</strong>: si recomprás lo que vendiste mal recientemente.</li>
      </ul>
      <p>
        <strong>Free</strong> ve 3 detectores. <strong>Plus</strong> ve 6.{' '}
        <strong>Pro</strong> ve los 12 disponibles.
      </p>

      <h2>Export CSV consolidado</h2>
      <p>
        Botón <strong>"Exportar mensual"</strong> arriba de Reportes te baja un CSV con
        todas tus operaciones del período, ya consolidadas por broker, con FIFO aplicado
        y P&amp;L en USD. Es lo que necesita tu contador para tu declaración a AFIP/ARCA.
      </p>
      <p>
        El CSV incluye:
      </p>
      <ul>
        <li>Compras: fecha, broker, activo, cantidad, precio, costo total USD.</li>
        <li>Ventas: fecha, broker, activo, cantidad, precio venta, costo base FIFO, P&amp;L realizado USD.</li>
        <li>Dividendos / cupones: fecha, activo, monto USD.</li>
        <li>Depósitos / retiros: fecha, broker, monto USD.</li>
      </ul>
      <p>
        <strong>Free</strong> exporta solo el último mes.{' '}
        <strong>Plus y Pro</strong> exportan todos los meses históricos.
      </p>

      <h2>Cómo calculamos tu rendimiento</h2>
      <p>
        Cada número de rendimiento que ves en Rendi sale de una cuenta con reglas
        fijas — no es simplemente "lo que vale hoy menos lo que creés que pusiste".
        Acá te mostramos las 5 piezas que usamos, con ejemplos y números redondos,
        para que sepas exactamente qué estás mirando. La idea de fondo es una sola:
        separar la plata que pusiste vos de la que ganó (o perdió) el mercado, y
        medir el % por tiempo para que refleje tu cartera y no tu timing.
      </p>

      <figure className="my-9">
        <ReturnsDiagram />
        <div className="mt-4 flex flex-wrap justify-center gap-x-4 gap-y-1.5 text-[11px] text-ink-2">
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: '#8B7DFF' }} />
            lo que pusiste
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: '#21D07A' }} />
            ganancia (USD)
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: '#5B9DF9' }} />
            el % en el tiempo
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: '#3A4256' }} />
            FIFO (la maquinaria)
          </span>
        </div>
        <figcaption className="mt-3 text-center text-xs text-ink-3">
          Los mismos insumos, dos respuestas: cuántos dólares ganaste y qué tan bien rindió tu cartera.
        </figcaption>
      </figure>

      <h3>La base: cuánto pusiste y cuánto vale</h3>
      <p>
        Todo arranca con el <strong>capital aportado</strong>: la plata que pusiste
        de tu bolsillo. Sumamos cada depósito y restamos cada retiro, 1 a 1, sin
        ponderar nada. Si metiste US$1.000 y después US$500 más, aportaste US$1.500.
      </p>
      <p>
        El número grande en dólares es tu <strong>ganancia acumulada</strong>: valor
        de mercado menos capital aportado. Junta lo que ya realizaste (lo vendido)
        con lo no realizado (lo que todavía tenés).
      </p>
      <p>
        Restar los flujos es lo que hace que la cuenta sea honesta. Si esos US$1.500
        hoy valen US$1.800, ganaste US$300 — no US$800. Así un depósito no se disfraza
        de ganancia, ni un retiro de pérdida.
      </p>

      <h3>El % se pondera por el tiempo</h3>
      <p>
        El número en dólares está bueno, pero para comparar necesitás un %. Y un %
        justo tiene que mirar <strong>cuándo</strong> entró cada peso, no solo cuánto.
        Para eso usamos <strong>Modified Dietz</strong>, el estándar de la industria.
      </p>
      <p>
        La idea del famoso <strong>0,5</strong>: si un depósito entró a mitad del
        período, solo "trabajó" la mitad del tiempo, así que lo contamos a la mitad
        en la base del cálculo.
      </p>
      <p>
        Ejemplo: empezás el mes con US$1.000, a mitad de mes agregás otros US$1.000 y
        terminás con US$2.100. Ganaste US$100. Si dividieras por los US$2.000, te daría
        5%. Pero esos segundos mil recién entraron: la base real es 1.000 + la mitad de
        1.000 = 1.500, y el rendimiento sube a 6,7%. Le das crédito solo a la plata que
        estuvo laburando.
      </p>
      <p>
        <strong>Ojo</strong>: si retirás más del 30% del capital de un saque, ese
        "medio flujo" distorsiona feo, así que ahí usamos el valor inicial directo y
        evitamos picos falsos.
      </p>

      <h3>En el largo plazo, se multiplica (no se suma)</h3>
      <p>
        Para varios meses seguidos no sumamos los rendimientos: los{' '}
        <strong>multiplicamos</strong>. Eso se llama encadenar, o <strong>TWR</strong>{' '}
        (rendimiento ponderado por tiempo).
      </p>
      <p>
        Un mes +10% y al siguiente otro +10% no es +20%, es (1,10 × 1,10) − 1 ={' '}
        <strong>21%</strong>. El segundo 10% corre sobre un capital ya más grande.
      </p>
      <p>
        Encadenar así neutraliza cuánto y cuándo metiste plata: mide cómo laburó tu
        cartera, no el timing de tus aportes. Por eso podés compararte de igual a igual
        contra el <strong>S&amp;P 500</strong>.
      </p>
      <p>
        El <strong>CAGR</strong> es esa misma historia como una tasa anual pareja —
        "como si hubieras ganado X% todos los años". Sobre esta serie encadenada salen
        la volatilidad, el Sharpe, el Sortino y el alfa/beta vs el S&amp;P 500.
      </p>

      <h3>Cada venta se matchea con FIFO</h3>
      <p>
        Del historial que importás, cada venta se matchea contra tus compras más viejas
        primero. Es <strong>FIFO</strong> ("first in, first out").
      </p>
      <p>
        Ejemplo: compraste 10 CEDEARs a US$100 y después 10 más a US$150. Cuando vendés
        10, usamos los de US$100 (los más viejos) como costo. El resultado = precio de
        venta × cantidad − ese costo − comisiones.
      </p>
      <p>
        Si la operación fue en pesos, la calculamos en ARS y la pasamos a dólares al
        tipo de cambio <strong>del día de la venta</strong>, no al de hoy. La ganancia
        queda congelada en el momento real en que pasó.
      </p>
      <p>
        Lo <strong>no realizado</strong> es lo que todavía tenés, a valor de mercado,
        menos el costo que le queda. Y no importa en qué orden subas los archivos: el
        sistema recalcula todo desde cero desde la fuente, así que el número siempre da
        igual.
      </p>
      <p>
        Todas estas cuentas — aportado, ganancia, el %, el encadenado y el FIFO —
        corren en <strong>todos los planes</strong>. Las métricas de riesgo que salen
        del rendimiento encadenado (volatilidad, Sharpe, Sortino, alfa/beta vs el{' '}
        S&amp;P 500) están bloqueadas en <strong>Free</strong> y se desbloquean en{' '}
        <strong>Plus y Pro</strong>.
      </p>
      <blockquote>
        En una frase: separamos la plata que pusiste de la que ganó el mercado, y
        ponderamos todo por tiempo — así el % mide tu cartera, no tu timing.
      </blockquote>

      <h2>Calidad de cartera</h2>
      <p>
        En <strong>Calidad de cartera</strong> (en el sidebar, disponible en{' '}
        <strong>todos los planes</strong>) analizamos tus acciones y CEDEARs en 2 ejes:{' '}
        <strong>Negocio</strong> (qué tan sólida es la empresa) y <strong>Precio</strong>{' '}
        (si está cara o atractiva hoy).
      </p>
      <p>
        Es <strong>holding-first</strong>: abre con tus tenencias valuadas y sus dos pills
        Negocio/Precio a la vista. Desde ahí podés pedir un análisis con IA por categoría
        para profundizar.
      </p>
      <p>
        Ojo: bonos, FCI y cripto no tienen fundamentals, así que aparecen como{' '}
        <strong>"sin datos"</strong>.
      </p>

      <h2>Wrapped anual</h2>
      <p>
        En diciembre/enero se desbloquea <strong>Wrapped</strong> — un resumen del año
        estilo Spotify Wrapped: mejor mes, peor mes, activo estrella, total operado,
        cantidad de compras vs ventas, etc. Generás una imagen para compartir.
      </p>
    </GuidePage>
  )
}
