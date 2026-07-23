// /guia/cartera-y-operaciones — sección 2 del manual

import GuidePage from '../../components/guide/GuidePage'

export default function CarteraYOperaciones() {
  return (
    <GuidePage
      section="2 de 6"
      title="Cartera y operaciones"
      intro="Cómo funcionan las posiciones, FIFO al vender, bonos AR, CEDEARs, crypto y el resumen mensual."
      prev={{ to: '/guia/empezar', label: 'Empezar' }}
      next={{ to: '/guia/insights-y-reportes', label: 'Insights y reportes' }}
      metaTitle="Cartera y operaciones — Guía Rendi"
      metaDescription="Cómo gestionar posiciones, vender con FIFO, registrar bonos AR (AL30, GD30, TX26), CEDEARs y crypto en Rendi."
      canonicalPath="/guia/cartera-y-operaciones"
    >
      <h2>Posiciones</h2>
      <p>
        En <strong>Posiciones</strong> ves todo lo que tenés vivo, agrupado por broker.
        Cada fila te muestra:
      </p>
      <ul>
        <li><strong>Activo</strong> + ticker + cantidad actual.</li>
        <li><strong>Precio promedio</strong> de tus compras (ya incluyendo comisiones).</li>
        <li><strong>Precio actual</strong> live (yfinance para US/cripto, data912 para bonos AR).</li>
        <li><strong>Valor en USD</strong>: convertido al tipo de cambio correcto según el broker.</li>
        <li><strong>P&amp;L</strong>: ganancia/pérdida no realizada en USD y %.</li>
      </ul>
      <p>
        Tocás una fila para editarla, ver el detalle (lotes FIFO) o eliminarla.
        En mobile, swipe izquierda muestra acciones rápidas (vender, editar).
      </p>
      <p>
        En la barra de herramientas de la Cartera tenés un toggle <strong>USD | ARS</strong>:
        muestra todas las tarjetas de broker en la moneda que elijas, convirtiendo por el
        dólar-MEP activo. Así ves todo en dólares o todo en pesos de un toque. Por defecto
        cada broker arranca en su moneda nativa, pero el toggle lo unifica.
      </p>

      <h2>Operaciones — qué podés cargar</h2>
      <p>
        Cada cosa que pasa en tu broker es una "operación" en Rendi. Tipos disponibles:
      </p>
      <ul>
        <li><strong>Compra</strong>: suma cantidad a tu posición, registra costo + comisión.</li>
        <li><strong>Venta</strong>: descuenta cantidad aplicando FIFO, calcula P&amp;L realizado.</li>
        <li><strong>Depósito</strong>: cash que metés al broker (no es compra de activo).</li>
        <li><strong>Retiro</strong>: cash que sacás del broker.</li>
        <li><strong>Dividendo</strong>: cobro periódico de una acción/CEDEAR.</li>
        <li><strong>Cupón</strong>: pago de renta de un bono.</li>
        <li><strong>Amortización</strong>: devolución parcial de capital de un bono. Rendi separa qué parte es capital (no es ganancia) y qué parte es renta.</li>
      </ul>

      <h2>FIFO al vender (criterio fiscal AR)</h2>
      <p>
        Cuando vendés un activo que tenés en varios lotes (compras distintas), Rendi
        aplica <strong>FIFO automático</strong> — descuenta primero del lote más viejo.
        Esto es lo que AFIP/ARCA exige para calcular tu ganancia declarable.
      </p>
      <p>
        Ejemplo: compraste 20 NVDA.BA a $110 (lote 1) y 20 a $130 (lote 2). Vendés 30
        a $180. Rendi consume los 20 del lote 1 + 10 del lote 2. Costo base: $3.500.
        Ganancia realizada: $5.400 - $3.500 = <strong>$1.900</strong>.
      </p>

      <h2>Bonos AR (AL30, GD30, TX26, etc.)</h2>
      <p>
        Rendi tiene soporte específico para bonos canje 2020 (AL30, GD30, GD35, AE38,
        AL41) y bonos CER (TX26, TX28, TZX26/27/28). Metadata automática:
      </p>
      <ul>
        <li>Vencimiento, cupón actual, próxima amortización.</li>
        <li>Si cobrás en pesos, convertimos al MEP del día.</li>
        <li>Cuando un bono amortiza, separamos capital devuelto vs renta realizada.</li>
      </ul>
      <p>
        Cargás el bono normal en Posiciones (ej. ticker "AL30"). Si lo tenés en
        broker ARS, agregá el sufijo "D" (AL30D) si querés trackearlo en USD MEP.
      </p>

      <h2>CEDEARs (NVDA.BA, AAPL.BA, etc.)</h2>
      <p>
        Cargás el ticker con sufijo <code>.BA</code>. Rendi:
      </p>
      <ul>
        <li>Levanta el precio del subyacente en NYSE/NASDAQ.</li>
        <li>Aplica el ratio de conversión actualizado (1 NVDA.BA = X NVDA real).</li>
        <li>Calcula tu valor real en USD, no la ilusión nominal en pesos.</li>
      </ul>

      <h2>Crypto</h2>
      <p>
        Mismo flow que acciones, ticker = símbolo (BTC, ETH, SOL, USDT). Soportamos
        Binance directo (CSV) y carga manual desde otros exchanges. Stablecoins se
        tratan como dólar a 1:1.
      </p>

      <h2>Resumen mensual</h2>
      <p>
        En <strong>Mensual</strong> ves un row por mes y broker con:
      </p>
      <ul>
        <li><strong>Capital inicio</strong>: cuánto tenías al primer día del mes.</li>
        <li><strong>Depósitos / Retiros</strong>: cash flows del mes.</li>
        <li><strong>P&amp;L realizado</strong>: de ventas que cerraste en el mes.</li>
        <li><strong>P&amp;L no realizado</strong>: cambio del valor de posiciones abiertas.</li>
        <li><strong>Capital final</strong>: cuánto tenés al cierre del mes.</li>
      </ul>
      <p>
        Cuando arranca un mes nuevo, Rendi hace <strong>rollover automático</strong>:
        el capital_final del mes anterior se transforma en capital_inicio del mes
        actual. No tenés que hacer nada.
      </p>

      <h2>Filtros y búsqueda</h2>
      <p>
        En Operaciones podés filtrar por:
      </p>
      <ul>
        <li><strong>Broker</strong>: ver solo Cocos, solo IOL, etc.</li>
        <li><strong>Tipo</strong>: solo compras, solo dividendos, etc.</li>
        <li><strong>Fecha</strong>: rango custom o presets (mes actual, año, todo).</li>
        <li><strong>Activo</strong>: buscar por ticker.</li>
      </ul>
    </GuidePage>
  )
}
