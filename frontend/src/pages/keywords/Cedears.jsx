// /cedears — keyword landing para "tracker CEDEARs", "FIFO CEDEARs"

import KeywordLanding from '../../components/landing/KeywordLanding'

const FEATURES = [
  {
    title: 'Soporte completo de CEDEARs con ratios actualizados',
    desc: 'NVDA.BA, AAPL.BA, AMZN.BA, TSLA.BA, KO.BA, MELI.BA, GGAL y los 250+ del catálogo BYMA. Ratio de conversión al subyacente actualizado automáticamente.',
  },
  {
    title: 'Precio del subyacente USA + ratio = valor real en USD',
    desc: 'No mirás el precio en pesos del CEDEAR. Rendi calcula: precio del subyacente en NYSE × ratio × cantidad = valor real en USD. Eso es lo que tenés.',
  },
  {
    title: 'FIFO automático para AFIP / ARCA',
    desc: 'Cuando vendés un CEDEAR, Rendi aplica FIFO (lote más viejo primero, criterio fiscal AR). El P&L declarable queda calculado sin armar Excels. Exportás CSV anual.',
  },
  {
    title: 'Conversión correcta de dividendos en pesos',
    desc: 'CEDEARs pagan dividendos en ARS al MEP del día. Rendi registra el cobro al TC correcto y suma al P&L sin distorsionar tu rendimiento real en USD.',
  },
  {
    title: 'Allocation real: % de tu cartera en CEDEARs',
    desc: 'En Insights ves cuánto de tu portfolio total está en CEDEARs vs acciones AR vs bonos vs cripto. Diversificación medida en USD, no pesos.',
  },
  {
    title: 'Coach IA: preguntale por tus CEDEARs',
    desc: '"¿Cuánto realmente gané en NVDA este año?", "¿Mi concentración en tech CEDEARs es alta?", "¿Qué pasó con TSLA.BA esta semana?". Coach IA con contexto y memoria.',
  },
]

const HOW_STEPS = [
  { n: 1, title: 'Creá tu cuenta gratis', desc: 'Sin tarjeta. Plan Free suficiente para empezar a trackear tus CEDEARs.' },
  { n: 2, title: 'Cargá tus CEDEARs', desc: 'Manualmente o importá el CSV de tu broker (Cocos, IOL, Balanz). Rendi reconoce CEDEARs por el sufijo .BA automáticamente.' },
  { n: 3, title: 'Rendi calcula valor + P&L en USD', desc: 'Para cada CEDEAR, levantamos el precio del subyacente USA y aplicamos el ratio. Tu P&L queda en dólares reales — no en pesos nominales.' },
  { n: 4, title: 'Vendé con FIFO y declarás a AFIP', desc: 'Al vender, FIFO se aplica automático. El consolidado anual está listo para exportar a CSV y darle a tu contador.' },
]

const RELATED = [
  { to: '/brokers/cocos', label: 'Tracker Cocos' },
  { to: '/brokers/iol', label: 'Tracker IOL' },
  { to: '/bonos-argentinos', label: 'Bonos AR' },
  { to: '/afip-cripto', label: 'AFIP cripto + FIFO' },
  { to: '/planes', label: 'Ver planes' },
]

export default function Cedears() {
  return (
    <KeywordLanding
      kicker="CEDEARs con FIFO automático"
      h1="Seguí tus CEDEARs en USD real, con FIFO automático para AFIP"
      intro="Los CEDEARs cotizan en pesos pero representan acciones extranjeras. Rendi calcula tu valor real en USD usando el ratio de conversión + precio del subyacente. Y cuando vendés, aplica FIFO automático para que tu declaración a AFIP / ARCA sea correcta."
      features={FEATURES}
      howSteps={HOW_STEPS}
      relatedLinks={RELATED}
      metaTitle="CEDEARs con FIFO automático — Rendi | P&L real en USD"
      metaDescription="Tracker de CEDEARs (NVDA, AAPL, MELI, GGAL) con valor real en USD usando ratios. FIFO automático para AFIP, dividendos al MEP correcto, Coach IA con contexto."
      canonicalPath="/cedears"
    />
  )
}
