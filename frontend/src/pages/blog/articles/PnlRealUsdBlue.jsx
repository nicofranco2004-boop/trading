// /blog/pnl-real-usd-blue-argentina

import BlogPost from '../../../components/blog/BlogPost'

const RELATED = [
  { to: '/blog/fifo-cedears-argentina', label: 'Cómo funciona el FIFO en CEDEARs', desc: 'El criterio fiscal que AFIP exige y cómo automatizarlo.' },
  { to: '/blog/comparativa-brokers-argentina', label: 'Cocos vs IOL vs Balanz vs Bull', desc: 'Comparativa honesta de los 4 brokers más populares.' },
  { to: '/', label: 'Ver demo de Rendi', desc: 'Tracker multi-broker con P&L real en USD.' },
]

export default function PnlRealUsdBlue() {
  return (
    <BlogPost
      slug="pnl-real-usd-blue-argentina"
      title="P&L real en USD blue: por qué tus pesos te engañan"
      description="La diferencia entre 'ganaste 50% en pesos' y 'ganaste 5% en dólares'. Cómo medir tu rendimiento real cuando operás en un país con inflación alta."
      publishedAt="2026-05-24"
      category="P&L y rendimiento"
      readTime="6 min"
      related={RELATED}
    >
      <p>
        Una de las trampas más comunes del inversor argentino es mirar su P&L en pesos y
        sentir que "ganó". Tu broker te muestra que la cartera subió 30% en el año. Te alegrás,
        pensás que estás invirtiendo bien. Pero la inflación fue 40% y el dólar blue subió
        35%. <strong>En términos reales, perdiste poder de compra.</strong>
      </p>

      <p>
        Esto no es un detalle: es la diferencia entre invertir y mantener el patrimonio. Te
        cuento cómo pensarlo bien.
      </p>

      <h2>El problema: "ganaste" en una moneda que se evapora</h2>

      <p>
        Argentina es uno de los pocos países donde tu moneda doméstica pierde poder de compra
        de manera continua. El peso de hoy no compra lo mismo que el peso de hace 6 meses,
        y mucho menos que el de hace un año.
      </p>

      <p>
        Cuando tu broker te muestra "ganaste 30% en el año", está midiendo en una moneda
        que se devaluó. Si en el mismo período el dólar subió 35%, tu plata <em>en términos
        de bienes que podrías comprar afuera (o de cualquier bien con precio internacional
        en AR: nafta, electrodomésticos, alquiler en USD, viajes)</em> rindió −5%. Es decir,
        perdiste poder de compra a pesar del número positivo en pesos.
      </p>

      <h2>Cómo se calcula el P&L real en USD</h2>

      <p>
        El cálculo correcto consiste en convertir cada operación al dólar del día que ocurrió,
        usando el TC apropiado para ese instrumento:
      </p>

      <ul>
        <li><strong>Bonos USD denominated (AL30, GD30) cobrados en pesos</strong>: dólar MEP del día.</li>
        <li><strong>Acciones AR (Merval) y CEDEARs en ARS</strong>: dólar blue del día (o MEP si el broker lo permite).</li>
        <li><strong>Crypto en exchanges AR / P2P</strong>: blue del día (o el TC implícito que usás para entrar/salir).</li>
        <li><strong>Acciones USA en Schwab</strong>: ya están en USD, no se convierte.</li>
      </ul>

      <p>
        El P&L real se calcula así: <code>(Precio de venta en USD del día) − (Precio de compra
        en USD del día)</code>. La diferencia es tu ganancia real en poder de compra.
      </p>

      <h2>Ejemplo: la ilusión del 30% en pesos</h2>

      <p>
        Compraste $500.000 ARS de un FCI de renta variable AR en enero. El dólar blue ese
        día estaba a $1.000. Equivalente: <strong>USD 500</strong>.
      </p>

      <p>
        Después de un año, el FCI valía $650.000 ARS — subió 30%. Tu broker te felicita.
        Pero el dólar blue ese día está a $1.400. Equivalente: <strong>USD 464</strong>.
      </p>

      <p>
        En pesos: +30%. En dólares: −7%. <strong>Perdiste USD 36 de poder de compra real</strong>,
        aunque el ticket te diga que ganaste.
      </p>

      <h2>Por qué los brokers no te lo muestran</h2>

      <p>
        Mostrar el P&L en pesos es lo "natural" desde el broker AR — su contabilidad opera en
        pesos, los movimientos del banco son en pesos, los impuestos se liquidan en pesos.
        Pero <em>el inversor argentino piensa en dólares</em> (alquiler, ahorros, autos,
        viajes), y necesita el cálculo en USD para entender qué le pasó realmente con su
        plata.
      </p>

      <p>
        El blue (o MEP) no es el TC oficial, pero es el TC que define el poder de compra
        real en Argentina — el dólar al que vas a comprar, ahorrar o viajar. Por eso es la
        moneda de referencia honesta.
      </p>

      <h2>Tres cosas que cambian cuando medís en USD</h2>

      <h3>1. Ves cuáles activos te están "tapando" la inflación</h3>
      <p>
        Algunos activos rindieron bien <em>en pesos</em>, pero solo siguieron al blue. No son
        inversiones — son cobertura. Distinguirlos es clave para no confundir "no perdiste
        contra el dólar" con "ganaste".
      </p>

      <h3>2. Comparás contra benchmarks reales</h3>
      <p>
        El S&P 500 hizo +12% en USD. Tu cartera, +8%. Eso es comparable. Pero si comparás
        Merval en pesos (+45%) con S&P (+12%) sin ajustar por blue, estás comparando peras
        con manzanas.
      </p>

      <h3>3. Tomás mejores decisiones de allocation</h3>
      <p>
        Si entendés que algunos activos tu broker llama "ganadores" en realidad fueron
        perdedores reales, pasás más capital a los que sí ganaron en USD. Tu cartera, con
        el tiempo, mejora la calidad — no solo el número.
      </p>

      <h2>Cómo automatizar el cálculo</h2>

      <p>
        Hacer la conversión manual operación por operación con el TC del día es inviable si
        tenés más de 20 movimientos al año. En <a href="/">Rendi</a> esto ocurre automático:
      </p>

      <ul>
        <li>Cada operación se registra con su fecha y se le aplica el TC apropiado del día (blue, MEP, o ambos según el activo).</li>
        <li>El P&L en USD se actualiza en cada compra y venta.</li>
        <li>El dashboard te muestra <strong>en USD</strong> y <strong>en pesos</strong> lado a lado para que tengas la doble visión.</li>
        <li>El Coach IA usa el USD como moneda principal para análisis — porque ahí está tu performance real.</li>
      </ul>

      <h2>Conclusión</h2>

      <p>
        Mirar tu cartera solo en pesos en Argentina es como tomar la temperatura sin
        considerar la humedad: el número está, pero no te dice qué se siente realmente.
        El P&L en USD blue te da la lectura correcta — la única que importa para decisiones
        de largo plazo.
      </p>

      <p>
        La próxima vez que tu broker te diga "ganaste 30% este año", abrí calculadora,
        comparalo contra el dólar y vé si fue ganancia o ilusión.
      </p>
    </BlogPost>
  )
}
