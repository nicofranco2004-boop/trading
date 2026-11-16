// /brokers/bull-market — "cómo descargar mis movimientos de Bull Market"
// ════════════════════════════════════════════════════════════════════════════
// Intent: alguien con cuenta en Bull Market Brokers que quiere bajar su
// historial. Búsqueda con intención clara y, al 16/11/2026, sin nadie que la
// conteste — y es el primer paso de un usuario de Rendi.
//
// Los pasos salen de la guía de la app (landingDeBroker.js). Lo que esta página
// escribe es lo propio de Bull Market: los errores típicos y qué hace Rendi con
// esos archivos. Cada afirmación sale del lector del servidor
// (backend/importing/parsers/bullmarket.py): si cambia lo que el lector hace,
// cambiá esto.

import KeywordLanding from '../../components/landing/KeywordLanding'
import { guiaDeBroker, descargaDe, comoFuncionaDe } from '../../components/landing/landingDeBroker'
import { RENDI_Y_LOS_IMPUESTOS } from '../../data/impuestos'
import { otrasGuiasDeBrokers } from '../../data/guiasDeBrokers'

const GUIA = guiaDeBroker('bullmarket')

const ERRORES = [
  {
    title: 'Exportar sólo la pestaña Pesos',
    desc: 'La Cuenta Corriente está separada por moneda. Si alguna vez operaste en dólares, esos movimientos están en las pestañas Dólares y Dólares cable: si no las exportás, a tu cartera le faltan todas esas operaciones.',
  },
  {
    title: 'Quedarte sin los primeros años',
    desc: 'El portal no siempre deja exportar toda la historia. El histórico que Bull Market manda por mail sirve tal como llega —en un archivo o partido en varios—: si son varios, se suben todos juntos.',
  },
  {
    title: 'Buscar el botón de descarga de la Tenencia',
    desc: 'No tiene: se guarda la página como PDF desde el navegador. Y vale la pena, porque sin esa foto Rendi sólo ve lo que se movió en el período que exportaste, no lo que ya tenías de antes.',
  },
  {
    // bullmarket.py: las columnas Dolares + Mda del histórico compacto.
    title: 'Sumar a mano el histórico en pesos',
    desc: 'En el histórico que llega por mail, las filas en dólares traen al lado un equivalente en pesos, al dólar oficial, sólo para que cierre el total. Si sumás esa columna, un dividendo de US$ 2,57 te queda como $ 460. Rendi toma el monto real en dólares.',
  },
  {
    title: 'Esperar que aparezca tu fondo común',
    desc: 'Si tenés un FCI abierto en Bull Market, por ahora cargalo a mano desde Posiciones: no se arma solo con estos archivos.',
  },
]

const FEATURES = [
  {
    title: 'Tu cuenta en pesos y tu cuenta en dólares, cada una en su moneda',
    desc: 'Lo que se movió en dólares entra en dólares, no convertido a pesos. Así tu saldo en cada moneda es el que tenés en Bull Market.',
  },
  {
    title: 'Comprar dólar MEP no cuenta como plata nueva',
    desc: 'En Bull Market, comprar MEP son dos movimientos: compra de un bono en pesos y venta contra dólares. Rendi los junta en una sola conversión, así no te infla lo que pusiste ni lo que ganaste.',
  },
  {
    title: 'Cauciones, futuros de dólar y dividendos',
    desc: 'El interés de tus cauciones, el resultado de tus futuros de dólar y cada dividendo entran como lo que son, con su fecha.',
  },
  {
    title: 'La Tenencia valorizada manda',
    desc: 'Es tu foto de hoy: completa lo que ya tenías antes del período exportado y corrige lo que sobre o falte, cerrando a costo, sin inventar ganancias.',
  },
  {
    title: 'Tu ganancia, en pesos y en dólares',
    desc: 'Cada operación se pasa al dólar MEP de su fecha, así ves si tu cartera de Bull Market le ganó a la inflación o sólo la acompañó.',
  },
  RENDI_Y_LOS_IMPUESTOS,
]

const HOW_STEPS = comoFuncionaDe(GUIA, {
  title: 'Ves tu cartera de Bull Market en dólares',
  desc: 'Cuánto pusiste, cuánto vale hoy y cuánto ganaste, en pesos y en dólares. Si después sumás otro broker, queda todo junto.',
})

const RELATED = [
  ...otrasGuiasDeBrokers('/brokers/bull-market'),
  { to: '/blog/comparativa-brokers-argentina', label: 'Cocos vs IOL vs Balanz vs Bull' },
  { to: '/planes', label: 'Ver planes' },
]

export default function BullMarket() {
  return (
    <KeywordLanding
      kicker="Guía · Bull Market Brokers"
      h1="Cómo descargar tus movimientos de Bull Market (y ver tu ganancia en dólares)"
      intro="En Bull Market tus movimientos están en la Cuenta Corriente, separada por moneda, y la tenencia no tiene botón de descarga. Acá tenés cómo sacar las dos cosas —incluido el histórico que te mandan por mail— y qué hace Rendi con ellas."
      descarga={descargaDe(GUIA, 'Necesitás la Cuenta Corriente (tus movimientos, en Excel) y la Tenencia valorizada (lo que tenés hoy, en PDF).')}
      errores={ERRORES}
      features={FEATURES}
      featuresTitle="Qué calcula Rendi con tus archivos de Bull Market"
      howSteps={HOW_STEPS}
      relatedLinks={RELATED}
      metaTitle="Cómo descargar tus movimientos de Bull Market — Rendi"
      metaDescription="Cómo exportar la Cuenta Corriente y la Tenencia valorizada de Bull Market Brokers (o pedir el histórico por mail) y ver tu ganancia real en dólares."
      canonicalPath="/brokers/bull-market"
    />
  )
}
