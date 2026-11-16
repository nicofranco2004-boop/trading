// /cedears — keyword landing para "tracker CEDEARs", "FIFO CEDEARs"
// Lo que dice de impuestos sale de data/impuestos.js: no escribir frases fiscales a mano.

import KeywordLanding from '../../components/landing/KeywordLanding'
import { PASO_CREAR_CUENTA } from '../../data/prueba'
import { FIFO_PARA_QUE, VENTA_EXENTA, LO_QUE_SI_PAGA } from '../../data/impuestos'

const FEATURES = [
  {
    title: 'Soporte completo de CEDEARs con ratios actualizados',
    desc: 'NVDA.BA, AAPL.BA, AMZN.BA, TSLA.BA, KO.BA, MELI.BA, GGAL y los 250+ del catálogo BYMA. Ratio de conversión al subyacente actualizado automáticamente.',
  },
  {
    title: 'Tu CEDEAR en dólares, al MEP de cada día',
    desc: 'Rendi toma el precio del CEDEAR en BYMA, en pesos, y lo pasa a dólares al MEP del día. Así ves cuánto valen de verdad tus CEDEARs en dólares, no un número en pesos que sube con la inflación.',
  },
  {
    title: 'FIFO automático: cuánto ganaste en cada venta',
    desc: `${FIFO_PARA_QUE} ${VENTA_EXENTA} ${LO_QUE_SI_PAGA}`,
  },
  {
    title: 'Dividendos por CEDEAR, con el ratio bien aplicado',
    desc: 'Un CEDEAR es una fracción de la acción: con ratio 20, son 20 CEDEARs por acción, así que cada uno cobra 1/20 del dividendo. BYMA los paga en dólares (algunos brokers te los acreditan en pesos). Cuando paga una empresa de EE.UU., Rendi calcula con el ratio cuánto te toca y te lo muestra en Cartera; lo confirmás (o importás el archivo de tu broker) y se suma a tu ganancia en dólares.',
  },
  {
    title: 'Allocation real: % de tu cartera en CEDEARs',
    desc: 'En Métricas ves cuánto de tu portfolio total está en CEDEARs vs acciones AR vs bonos vs cripto. Diversificación medida en USD, no pesos.',
  },
  {
    title: 'Mervall-E AI: preguntale por tus CEDEARs',
    desc: '"¿Cuánto realmente gané en NVDA este año?", "¿Mi concentración en tech CEDEARs es alta?", "¿Qué pasó con TSLA.BA esta semana?". Mervall-E AI con contexto y memoria.',
  },
]

const HOW_STEPS = [
  // El paso 1 es el mismo en las seis landings y sale de `data/prueba.js`:
  // decía que el plan Free alcanzaba para empezar, y el Free ya no existe
  // para quien se registra.
  { n: 1, ...PASO_CREAR_CUENTA },
  { n: 2, title: 'Cargá tus CEDEARs', desc: 'Manualmente o importá el CSV de tu broker (Cocos, IOL, Balanz). Rendi reconoce CEDEARs por el sufijo .BA automáticamente.' },
  { n: 3, title: 'Rendi calcula valor y ganancia en dólares', desc: 'Cada compra queda al dólar MEP de su fecha y el precio de hoy, al MEP de hoy. Tu ganancia queda en dólares reales, no en pesos nominales.' },
  { n: 4, title: 'Vendé y mirá cuánto ganaste', desc: 'Al vender, FIFO se aplica solo y ves la ganancia de esa venta. El CSV con todas tus ventas queda listo para tu contador.' },
]

const RELATED = [
  { to: '/brokers/cocos', label: 'Tracker Cocos' },
  { to: '/brokers/iol', label: 'Tracker IOL' },
  { to: '/bonos-argentinos', label: 'Bonos AR' },
  { to: '/afip-cripto', label: 'Cripto e impuestos' },
  { to: '/planes', label: 'Ver planes' },
]

export default function Cedears() {
  return (
    <KeywordLanding
      kicker="CEDEARs con FIFO automático"
      h1="Seguí tus CEDEARs en dólares reales, con FIFO automático"
      intro="Los CEDEARs cotizan en pesos pero representan acciones del exterior. Rendi pasa cada compra al dólar MEP del día en que la hiciste, y el precio de hoy, al MEP de hoy: así ves tu ganancia real en dólares. Y cuando vendés, descuenta primero de tu compra más vieja (FIFO) para decirte cuánto ganaste en cada venta."
      features={FEATURES}
      howSteps={HOW_STEPS}
      relatedLinks={RELATED}
      metaTitle="CEDEARs en dólares, con FIFO automático — Rendi"
      metaDescription="Tracker de CEDEARs (NVDA, AAPL, MELI): tu cartera en dólares al MEP de cada día, la ganancia de cada venta con FIFO, tus dividendos y Mervall-E AI."
      canonicalPath="/cedears"
    />
  )
}
