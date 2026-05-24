// /blog/fifo-cedears-argentina
// Target query: "FIFO CEDEARs argentina", "cómo declarar CEDEARs AFIP",
// "FIFO criterio fiscal cedears"

import BlogPost from '../../../components/blog/BlogPost'

const RELATED = [
  { to: '/blog/pnl-real-usd-blue-argentina', label: 'P&L real en USD blue: por qué tus pesos te engañan', desc: 'Cómo medir tu rendimiento real cuando operás en un país con inflación alta.' },
  { to: '/cedears', label: 'Tracker de CEDEARs con FIFO automático', desc: 'Cómo Rendi calcula el valor real de tus CEDEARs en USD.' },
  { to: '/blog/comparativa-brokers-argentina', label: 'Cocos vs IOL vs Balanz vs Bull en 2026', desc: 'Comparativa honesta para elegir el broker AR que mejor te conviene.' },
]

export default function FifoCedearsArgentina() {
  return (
    <BlogPost
      slug="fifo-cedears-argentina"
      title="Cómo funciona el FIFO en CEDEARs (criterio fiscal AR)"
      description="Por qué AFIP / ARCA exige FIFO, cómo se aplica al vender un CEDEAR, errores comunes que cuestan caro en la declaración y cómo automatizarlo sin armar Excels."
      publishedAt="2026-05-24"
      category="FIFO y AFIP"
      readTime="8 min"
      related={RELATED}
    >
      <p>
        Si invertís en CEDEARs desde Argentina y declarás ganancias a AFIP / ARCA, vas a chocar
        tarde o temprano con la palabra <strong>FIFO</strong>. Suena a jerga, pero entenderla bien te
        puede ahorrar miles de pesos en impuestos mal calculados — o evitar que tu contador
        te cobre un extra por armar la planilla a mano.
      </p>

      <p>
        En este artículo: qué es FIFO, por qué AFIP lo exige, cómo se aplica al vender un CEDEAR
        (con un ejemplo concreto), errores que vemos seguido y cómo automatizarlo para no
        depender de Excels que se rompen al moverse una celda.
      </p>

      <h2>Qué es FIFO y por qué AFIP lo exige</h2>
      <p>
        FIFO significa <strong>First In, First Out</strong> — "el primero que entra es el
        primero que sale". Cuando vendés un activo del cual tenés varios lotes comprados
        en distintas fechas, AFIP / ARCA asume que estás vendiendo los del lote
        <em> más viejo</em> primero. No el más nuevo, no un promedio, no el que más te conviene
        fiscalmente. El más viejo.
      </p>

      <p>
        ¿Por qué? Porque ese criterio es estándar contable internacional y evita que el
        contribuyente "elija" qué lote vender para minimizar impuesto. Si te dejaran elegir,
        siempre venderías el lote con mayor costo (menor ganancia declarable). FIFO te
        obliga a tributar sobre la ganancia real acumulada en el tiempo.
      </p>

      <h2>Ejemplo concreto: vendés 30 NVDA.BA</h2>
      <p>Supongamos que compraste CEDEARs de NVIDIA en tres momentos distintos:</p>

      <table>
        <thead>
          <tr><th>Fecha compra</th><th>Cantidad</th><th>Precio unitario (USD)</th><th>Costo total</th></tr>
        </thead>
        <tbody>
          <tr><td>15-mar-2025</td><td>20</td><td>$110</td><td>$2.200</td></tr>
          <tr><td>10-jun-2025</td><td>20</td><td>$130</td><td>$2.600</td></tr>
          <tr><td>5-sep-2025</td><td>20</td><td>$150</td><td>$3.000</td></tr>
        </tbody>
      </table>

      <p>
        En total tenés <strong>60 CEDEARs de NVDA.BA</strong> con un costo total de USD 7.800
        (promedio: USD 130).
      </p>

      <p>
        Hoy vendés <strong>30 CEDEARs</strong> a USD 180. Cobraste USD 5.400. ¿Cuánto declarás
        como ganancia? <strong>Depende del criterio que uses</strong>:
      </p>

      <ul>
        <li><strong>FIFO (correcto AFIP)</strong>: vendés los 20 del lote más viejo ($110) y 10 del segundo ($130). Costo: 20×110 + 10×130 = $3.500. Ganancia: 5.400 − 3.500 = <strong>USD 1.900</strong>.</li>
        <li><strong>LIFO (Last In, First Out)</strong>: vendés los 20 más nuevos ($150) y 10 del medio ($130). Costo: 20×150 + 10×130 = $4.300. Ganancia: 5.400 − 4.300 = USD 1.100.</li>
        <li><strong>Promedio ponderado</strong>: costo $130 × 30 = $3.900. Ganancia: $1.500.</li>
      </ul>

      <p>
        La diferencia entre FIFO y LIFO es de <strong>USD 800 de ganancia declarada</strong>.
        Si la alícuota efectiva es 15%, son USD 120 de diferencia en impuestos. Si AFIP te
        cruza la información de tu broker y vos declaraste con otro criterio, te puede ajustar
        + multa + intereses.
      </p>

      <h2>Errores comunes (que pagás caro)</h2>

      <h3>1. Usar el precio promedio</h3>
      <p>
        Es lo más intuitivo y lo que mucha gente hace cuando arma la planilla en Excel: divide
        el costo total por la cantidad total y ya. Pero <strong>no es FIFO</strong>. AFIP no
        acepta promedio ponderado para acciones, CEDEARs o cripto.
      </p>

      <h3>2. Ignorar las comisiones de compra</h3>
      <p>
        Las comisiones del broker forman parte del <strong>costo de adquisición</strong>.
        Si compraste 20 NVDA.BA a $110 con $10 de comisión, tu costo unitario es $110.50, no
        $110. Olvidarte de sumarlas hace que pagues más impuesto del que corresponde.
      </p>

      <h3>3. Mezclar CEDEARs con el subyacente</h3>
      <p>
        Si tenés NVDA.BA (CEDEAR) en Cocos y NVDA real (acción USA) en Schwab,
        <strong>no son el mismo activo fiscal</strong>. FIFO se aplica por instrumento, no
        por subyacente. Tus 20 NVDA.BA del 15-mar y tus 10 NVDA del 20-mar son lotes
        independientes.
      </p>

      <h3>4. No registrar los dividendos</h3>
      <p>
        Los dividendos de CEDEARs pagan en ARS al MEP. Olvidarte de registrarlos a tiempo
        en el cost basis correcto cambia el cálculo del lote y rompe el FIFO.
      </p>

      <h2>Cómo automatizarlo</h2>

      <p>
        Hacer FIFO manualmente en Excel con 50+ operaciones al año es un dolor de cabeza.
        Cada compra suma una fila al inventario, cada venta tiene que cruzar con el lote más
        viejo, hay que rastrear si el lote ya se consumió parcialmente, las comisiones se
        agregan al costo, los dividendos van aparte. Una celda rota = todo el cálculo
        comprometido.
      </p>

      <p>
        En <a href="/">Rendi</a> el FIFO está automatizado de raíz:
      </p>

      <ul>
        <li>Cada compra crea un <strong>lote</strong> con su fecha + costo + comisión.</li>
        <li>Cuando vendés, el sistema busca el lote más viejo no consumido y descuenta la cantidad de ahí. Si la venta es mayor al lote, pasa al siguiente.</li>
        <li>El P&L realizado se calcula automáticamente: precio de venta menos cost basis del lote consumido (incluyendo comisiones).</li>
        <li>Al cierre del año exportás un CSV con todas las ventas, FIFO aplicado, ganancia/pérdida realizada en USD. Listo para tu contador.</li>
      </ul>

      <p>
        Lo mismo aplica a <a href="/cedears">CEDEARs</a>, acciones AR, bonos y
        <a href="/afip-cripto"> cripto</a> (que también requiere FIFO desde 2018).
      </p>

      <h2>Conclusión</h2>

      <p>
        FIFO no es opcional: es el criterio que AFIP / ARCA usa para auditar tu declaración
        de inversiones. Aplicarlo bien evita ajustes y multas, y te da claridad sobre
        cuánto realmente ganaste con cada operación.
      </p>

      <p>
        Si todavía estás armando tu planilla en Excel, andá probando una herramienta
        especializada. El tiempo que te ahorra en abril (cuando vence la declaración) compensa
        muchas veces el costo de la suscripción.
      </p>
    </BlogPost>
  )
}
