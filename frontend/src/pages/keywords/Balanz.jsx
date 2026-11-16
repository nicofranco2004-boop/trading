// /brokers/balanz — "cómo descargar mis movimientos de Balanz"
// ════════════════════════════════════════════════════════════════════════════
// Intent: alguien con cuenta en Balanz que quiere bajar su historial (para un
// Excel, para su contador o para un tracker). Búsqueda con intención clara y,
// al 16/11/2026, sin nadie que la conteste — y es el primer paso de un usuario
// de Rendi.
//
// Los pasos salen de la guía de la app (landingDeBroker.js). Lo que esta página
// escribe es lo propio de Balanz: los errores típicos y qué hace Rendi con esos
// archivos. Cada afirmación sale del lector de Balanz del servidor
// (backend/importing/parsers/balanz_movimientos.py, balanz_resultados.py,
// balanz_internacional.py): si cambia lo que el lector hace, cambiá esto.

import KeywordLanding from '../../components/landing/KeywordLanding'
import { guiaDeBroker, descargaDe, comoFuncionaDe, ITEM_IMPUESTOS } from '../../components/landing/landingDeBroker'
import { otrasGuiasDeBrokers } from '../../data/guiasDeBrokers'

const GUIA = guiaDeBroker('balanz')

const ERRORES = [
  {
    // balanz_resultados.py: el formato se detecta sólo para rechazarlo con
    // este mensaje (BALANZ_RESULTADOS_NO_SOPORTADO).
    title: 'Bajar «Resultados» en vez de «Movimientos»',
    desc: 'Es el error más común, porque el nombre suena a lo que buscás. Pero el reporte de Resultados (y el de Órdenes) no trae tus depósitos ni tus retiros: con él, lo que pusiste y lo que ganaste quedarían mal. Si lo subís a Rendi, no lo importa y te avisa cuál tenés que bajar.',
  },
  {
    title: 'Elegir sólo el último año',
    desc: 'Si el export no arranca el día que abriste la cuenta, falta la plata con la que la fondeaste y el saldo no cierra. Si igual te faltan años, el Resumen de Cuenta lo corrige: fija tus tenencias y tu saldo de hoy.',
  },
  {
    title: 'Pedir el Resumen de Cuenta en dólares',
    desc: 'Pedilo en pesos. El de pesos ya trae también tu saldo en dólares, así que con ese archivo Rendi lee las dos monedas.',
  },
  {
    title: 'Mezclar tu cuenta local con Balanz Internacional',
    desc: 'Si además tenés la cuenta del exterior (Balanz Capital International, en dólares), sus movimientos van en otro archivo. Rendi la carga como un broker aparte y valúa cada acción a su precio en Estados Unidos, no como si fuera un CEDEAR.',
  },
]

const FEATURES = [
  {
    title: 'Tu efectivo, en pesos y en dólares, igual al de Balanz',
    desc: 'El export de Movimientos es el libro de caja: trae los depósitos, los retiros y las compras de dólar MEP. Por eso, con él, tu saldo reconcilia — justo lo que el reporte de Resultados no puede darte.',
  },
  {
    title: 'Cupones, dividendos y comisiones, con su fecha',
    desc: 'Cada cupón de bono, cada dividendo y cada comisión entra el día que pasó. Ves cuánto te rindió cada activo de verdad, no sólo la diferencia de precio.',
  },
  {
    title: 'Cada activo en su lugar',
    desc: 'Rendi reconoce solo si cada cosa es un bono, un CEDEAR, una acción o un fondo, y la valúa como corresponde.',
  },
  {
    title: 'Lo que tenés hoy, exacto',
    desc: 'El Resumen de Cuenta es la foto de hoy y manda: si al historial le falta algo, Rendi ajusta tus tenencias y tu saldo para que coincidan con los de Balanz, sin inventar ganancias.',
  },
  {
    title: 'Tu ganancia medida en dólares',
    desc: 'Balanz te muestra la cartera en pesos. Rendi pasa cada operación al dólar MEP de su fecha: ves si ganaste poder de compra o si sólo acompañaste la inflación.',
  },
  ITEM_IMPUESTOS,
]

const HOW_STEPS = comoFuncionaDe(GUIA, {
  title: 'Ves tu cartera de Balanz en dólares',
  desc: 'Cuánto pusiste, cuánto vale hoy y cuánto ganaste, en pesos y en dólares, con la evolución mes a mes. Si después sumás otro broker, queda todo junto.',
})

const RELATED = [
  ...otrasGuiasDeBrokers('/brokers/balanz'),
  { to: '/blog/comparativa-brokers-argentina', label: 'Cocos vs IOL vs Balanz vs Bull' },
  { to: '/planes', label: 'Ver planes' },
]

export default function Balanz() {
  return (
    <KeywordLanding
      kicker="Guía · Balanz"
      h1="Cómo descargar tus movimientos de Balanz (y ver tu ganancia en dólares)"
      intro="Balanz te deja bajar varios reportes, y no todos sirven para saber cuánto ganaste. Acá tenés el camino exacto al export de Movimientos y al Resumen de Cuenta, los errores que hacen que el saldo no cierre y qué hace Rendi con esos dos archivos."
      descarga={descargaDe(GUIA, 'Son dos archivos y los dos se bajan desde la web de Balanz, no desde la app: Movimientos (tu historial completo) y el Resumen de Cuenta (lo que tenés hoy).')}
      errores={ERRORES}
      features={FEATURES}
      featuresTitle="Qué calcula Rendi con tus archivos de Balanz"
      howSteps={HOW_STEPS}
      relatedLinks={RELATED}
      metaTitle="Cómo descargar tus movimientos de Balanz — Rendi"
      metaDescription="Paso a paso para bajar el export de Movimientos y el Resumen de Cuenta de Balanz (el de Resultados no sirve) y ver tu ganancia real en dólares."
      canonicalPath="/brokers/balanz"
    />
  )
}
