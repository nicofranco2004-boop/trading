// /blog/fifo-cedears-argentina
// Target query: "cedears pagan ganancias", "cedears exentos ganancias",
// "FIFO CEDEARs argentina" (las tres primeras salen en el autocompletado de
// Google; "fifo cedears" a secas, no).
//
// ⚠️ Hasta el 16/11/2026 esta nota decía lo contrario de la ley: calculaba un
// 15 % de Ganancias sobre la venta de CEDEARs, amenazaba con «ajuste + multa»,
// decía que la declaración vence en abril y ponía el CEDEAR de NVIDIA a
// US$ 110-180 (el precio de la ACCIÓN: con ratio 24, cada CEDEAR vale 1/24).
// Las frases sobre impuestos salen de data/impuestos.js; las fechas y el título,
// de data/blogPosts.js (si se corrige el contenido, se actualiza `updatedAt`).

import BlogPost from '../../../components/blog/BlogPost'
import { VENTA_EXENTA, CRIPTO_PAGA, NO_ES_ASESORAMIENTO } from '../../../data/impuestos'

const LEY_GANANCIAS = 'https://servicios.infoleg.gob.ar/infolegInternet/anexos/330000-334999/332890/texact.htm'
const CPCECABA = 'https://www.consejo.org.ar/herramientas-profesionales/gerencia-tecnica/los-cedear-en-el-impuesto-a-las-ganancias'
const ARCA_CRIPTO = 'https://www.afip.gob.ar/economia-digital/criptoactivos/impuesto-a-las-ganancias.asp'
const ARCA_GANANCIAS_Y_BIENES = 'https://www.arca.gob.ar/gananciasYBienes/'

const RELATED = [
  { to: '/cedears', label: 'Tus CEDEARs en dólares, con FIFO automático', desc: 'Cómo Rendi calcula el valor de tus CEDEARs en dólares y la ganancia de cada venta.' },
  { to: '/afip-cripto', label: 'Cripto e impuestos', desc: 'La ganancia de tu cripto con FIFO, para tu contador.' },
  { to: '/blog/pnl-real-usd-blue-argentina', label: 'P&L real en USD blue: por qué tus pesos te engañan', desc: 'Cómo medir tu rendimiento real cuando operás en un país con inflación alta.' },
]

export default function FifoCedearsArgentina() {
  return (
    <BlogPost
      slug="fifo-cedears-argentina"
      related={RELATED}
    >
      <p>
        <strong>La respuesta corta: por venderlos, no; por los dividendos, sí.</strong> {VENTA_EXENTA}
      </p>

      <p>
        En esta nota: qué condiciones tiene esa exención, qué sí paga impuesto cuando
        invertís en CEDEARs, para qué sirve entonces el FIFO (con un ejemplo con números)
        y en qué casos sí cambia lo que pagás.
      </p>

      <h2>Por qué vender CEDEARs no paga Ganancias</h2>
      <p>
        Lo dice el <a href={LEY_GANANCIAS} target="_blank" rel="noopener noreferrer">artículo 26, inciso u,
        de la Ley de Impuesto a las Ganancias</a>, vigente desde 2018: si vivís en Argentina,
        lo que ganás al vender acciones o certificados de depósito de acciones (eso es un
        CEDEAR de una empresa) está exento. Los CEDEARs de ETF, como SPY o QQQ, entran por
        otro párrafo del mismo inciso, el que exime lo que cotiza en un mercado autorizado
        por la Comisión Nacional de Valores: es la lectura habitual, aunque no hay un
        pronunciamiento oficial específico. El Consejo Profesional de Ciencias Económicas de
        CABA <a href={CPCECABA} target="_blank" rel="noopener noreferrer">lo explica igual</a>.
      </p>
      <p>
        Tiene requisitos, y si invertís como persona a través de un broker argentino,
        normalmente los cumplís:
      </p>
      <ul>
        <li>Que el CEDEAR o la acción tenga oferta pública autorizada por la Comisión Nacional de Valores, o que la vendas en un mercado autorizado por ella, como BYMA, que es donde operan Cocos, IOL, Balanz y el resto.</li>
        <li>Que no operes como empresa ni como comisionista: si la operación es de una sociedad o de un negocio a tu nombre, las reglas son otras.</li>
      </ul>
      <p>
        <strong>¿Y lo de noviembre de 2026?</strong> El Gobierno incluyó en un proyecto de
        ley un impuesto del 15 % a la venta de CEDEARs comprados desde fines de octubre, y lo
        retiró el 4 de noviembre sin que llegara a votarse. Al 16 de noviembre de 2026, la exención
        sigue igual. Si el proyecto vuelve al Congreso, actualizamos esta nota.
      </p>

      <h2>Qué sí paga impuesto</h2>
      <ul>
        <li>
          <strong>Los dividendos de tus CEDEARs.</strong> Cuentan como ganancia del exterior:
          se suman a tus otros ingresos y pagan según la escala del impuesto, que va del 5 %
          al 35 %. Lo que ya te retuvieron en el país de origen se puede descontar, con un tope.
        </li>
        <li>
          <strong>Los dividendos de acciones argentinas.</strong> La empresa te retiene un 7 %
          antes de pagarte. Si no estás inscripto en Ganancias, con esa retención ya cumpliste.
        </li>
        <li>
          <strong>Bienes Personales.</strong> Tener CEDEARs cuenta para el impuesto anual sobre
          tu patrimonio: se suman a tus bienes con su precio al 31 de diciembre, y pagás sólo si
          el total supera el mínimo que fija la ley. Las acciones argentinas no las sumás vos
          (el impuesto lo paga la propia empresa), y los bonos del Tesoro como AL30 o GD30 están
          exentos.
        </li>
        <li>
          <strong>La cripto.</strong> {CRIPTO_PAGA} No va por escala: es un porcentaje fijo de la
          ganancia, 5 % si operás en pesos comunes (sin ajuste por inflación ni por dólar) y 15 %
          si operás en dólares; si la ganancia se considera del exterior, 15 % siempre
          (<a href={ARCA_CRIPTO} target="_blank" rel="noopener noreferrer">ARCA, la ex AFIP, lo explica acá</a>).
        </li>
        <li>
          <strong>Las acciones y los ETF de un broker del exterior.</strong> Si comprás y vendés
          en Charles Schwab u otro broker de afuera, la venta no tiene la exención de la bolsa
          argentina: paga 15 % sobre la ganancia.
        </li>
      </ul>

      <h2>Entonces, ¿para qué sirve el FIFO en CEDEARs?</h2>
      <p>
        FIFO quiere decir <em>first in, first out</em>: «el primero que entra es el primero
        que sale». En castellano se dice PEPS: «primero entrado, primero salido». Si compraste
        lo mismo en varias veces, cada compra es un «lote»; cuando vendés, el FIFO descuenta la
        venta del lote más viejo primero.
      </p>
      <p>
        Si la venta está exenta, el método no cambia ningún impuesto. Lo que cambia es
        <strong> cuánto creés que ganaste en cada venta</strong>. Y eso importa para decidir:
        si esa operación te salió bien, si te conviene vender lo que queda, cuánto rindió tu
        cartera en el año.
      </p>

      <h3>Un ejemplo con números</h3>
      <p>
        Compraste CEDEARs de NVIDIA en tres momentos. Los precios son <strong>por CEDEAR</strong>,
        en dólares: el ratio de NVIDIA es 24, así que cada CEDEAR vale una veinticuatroava parte
        de la acción que cotiza en Nueva York.
      </p>

      <table>
        <thead>
          <tr><th>Fecha de compra</th><th>Cantidad</th><th>Precio por CEDEAR</th><th>Costo</th></tr>
        </thead>
        <tbody>
          <tr><td>15-mar-2025</td><td>20</td><td>US$ 5</td><td>US$ 100</td></tr>
          <tr><td>10-jun-2025</td><td>20</td><td>US$ 6</td><td>US$ 120</td></tr>
          <tr><td>5-sep-2025</td><td>20</td><td>US$ 7</td><td>US$ 140</td></tr>
        </tbody>
      </table>

      <p>
        Tenés 60 CEDEARs que te costaron US$ 360 (US$ 6 de promedio). Hoy vendés 30 a US$ 8
        y cobrás US$ 240. ¿Cuánto ganaste con esa venta? Depende de qué lotes digas que vendiste:
      </p>

      <ul>
        <li><strong>FIFO (los más viejos primero)</strong>: los 20 de US$ 5 y 10 de US$ 6. Costo: 20 × 5 + 10 × 6 = US$ 160. Ganancia: <strong>US$ 80</strong>.</li>
        <li><strong>Los más nuevos primero</strong>: los 20 de US$ 7 y 10 de US$ 6. Costo: US$ 200. Ganancia: US$ 40.</li>
        <li><strong>Precio promedio</strong>: 30 × US$ 6 = US$ 180. Ganancia: US$ 60.</li>
      </ul>

      <p>
        La misma venta parece haber ganado el doble o la mitad según el método. Cuando
        vendas todo, las tres cuentas terminan en el mismo total; lo que cambia es cómo se
        reparte entre una venta y otra. FIFO es el criterio más usado y el que te permite
        comparar una venta con otra sin trampas.
      </p>

      <h2>Dónde el FIFO sí cambia lo que pagás</h2>
      <p>
        En lo que sí paga impuesto. La Ley de Ganancias no usa las palabras FIFO ni PEPS. Dice
        que lo que vendés corresponde a «las adquisiciones más antiguas de su misma especie y
        calidad», o sea, a tus compras más viejas de ese mismo activo. Lo dice con todas las
        letras para las ventas de acciones que pagan impuesto (por ejemplo, acciones que no
        cotizan en bolsa). Para la cripto y para lo que comprás en un broker del exterior, la
        ley no lo dice tan claro para una persona. Igual, descontar del lote más viejo es la
        forma prudente y la más usada. Conviene que lo hables con tu contador.
      </p>

      <h2>Errores comunes</h2>

      <h3>1. Creer que vender CEDEARs paga Ganancias</h3>
      <p>
        Es el más caro: lleva a pagar de más, o a no vender por miedo a un impuesto que no
        existe. Si vendés en BYMA y vivís en Argentina, la ganancia de la venta está exenta.
      </p>

      <h3>2. Mirar el precio de la acción en vez del CEDEAR</h3>
      <p>
        Un CEDEAR es una fracción de la acción. Con ratio 20 (el de Apple), hacen falta 20
        CEDEARs para tener una acción: el precio de la acción se divide por el ratio, no se
        multiplica. Lo mismo con los dividendos: cada CEDEAR cobra la parte que le toca.
      </p>

      <h3>3. Olvidarte de las comisiones</h3>
      <p>
        Las comisiones del broker son parte del costo. Si compraste 20 CEDEARs a US$ 5 y
        pagaste US$ 1 de comisión, cada uno te costó US$ 5,05. Sin sumarlas, tu ganancia
        parece más grande de lo que fue.
      </p>

      <h3>4. Mezclar el CEDEAR con la acción de afuera</h3>
      <p>
        Si tenés CEDEARs de NVIDIA en Cocos y acciones de NVIDIA en Schwab, son dos cosas
        distintas: se cuentan por separado y no pagan lo mismo. Vender el CEDEAR en BYMA está
        exento; vender la acción en Schwab paga 15 % sobre la ganancia.
      </p>

      <h3>5. No registrar los dividendos</h3>
      <p>
        Pagan Ganancias, y si no los anotás tu rendimiento real queda más bajo de lo que fue.
        BYMA los paga en dólares, aunque algunos brokers te los acreditan en pesos.
      </p>

      <h2>Cuándo vence la declaración</h2>
      <p>
        La declaración anual de Ganancias y Bienes Personales vence, como regla, a mitad del
        año siguiente: en junio, según la terminación de tu CUIT. ARCA suele
        prorrogarla; en 2026, por ejemplo, el pago se corrió a fines de julio.
        Chequeá la fecha en <a href={ARCA_GANANCIAS_Y_BIENES} target="_blank" rel="noopener noreferrer">su sitio</a>.
      </p>

      <h2>Cómo lo hace Rendi</h2>
      <ul>
        <li>Cada compra crea un <strong>lote</strong> con su fecha, su costo y su comisión, y queda pasada al dólar MEP de ese día.</li>
        <li>Cuando vendés, Rendi descuenta del lote más viejo que todavía tenga cantidad, empezando por los de la moneda en que vendés; si la venta es más grande, sigue con el siguiente.</li>
        <li>La ganancia de cada venta queda calculada, en pesos y en dólares, comisiones incluidas.</li>
        <li>Con los planes Plus y Pro exportás un CSV con todas las ventas, lote por lote. Rendi no arma la declaración: te da los números para que tu contador la arme.</li>
      </ul>
      <p>
        Lo mismo para <a href="/cedears">CEDEARs</a>, acciones argentinas, bonos y <a href="/afip-cripto">cripto</a>.
      </p>

      <p>
        <em>{NO_ES_ASESORAMIENTO}</em>
      </p>
    </BlogPost>
  )
}
