// /brokers/cocos — keyword landing para "tracker Cocos Capital"
// ════════════════════════════════════════════════════════════════════════════
// Target query: "tracker cocos capital", "seguir cartera cocos", "P&L cocos"
// Intent: usuario de Cocos buscando manera de ver su cartera consolidada con
// otros brokers (porque Cocos solo muestra Cocos).

import KeywordLanding from '../../components/landing/KeywordLanding'

const FEATURES = [
  {
    title: 'Importá tu CSV de Cocos Capital en 30 segundos',
    desc: 'Descargá el archivo desde Cocos (Operaciones → Exportar) y subí a Rendi. Reconocemos automáticamente acciones AR, CEDEARs, bonos y FCI.',
  },
  {
    title: 'P&L real en USD blue, no pesos nominales',
    desc: 'Cocos te muestra el monto en ARS. Rendi convierte cada operación al dólar blue del día — vez si realmente ganaste poder de compra o solo seguiste la inflación.',
  },
  {
    title: 'Combiná Cocos con IOL, Balanz, Schwab, Binance',
    desc: 'Rendi es multi-broker. Carga Cocos + el resto y ves todo consolidado: cartera total, allocation por geo, top 5 ganadores y perdedores.',
  },
  {
    title: 'FIFO automático para CEDEARs y acciones',
    desc: 'Cuando vendés desde Cocos, Rendi aplica FIFO (criterio fiscal AR) y calcula tu P&L declarable. Exportás el CSV para tu contador / AFIP.',
  },
  {
    title: 'Soporte completo de bonos AR (AL30, GD30, TX26)',
    desc: 'Bonos canje 2020 y CER con metadata de cupones y amortizaciones. Cocos muestra el precio; Rendi te dice qué porcentaje es capital y qué es renta.',
  },
  {
    title: 'Coach IA: preguntale por qué bajó tu cartera',
    desc: 'Chat IA con contexto completo de tu cartera. "¿Por qué bajó mi mes?", "¿Dónde estoy concentrado?", "¿Cuánto realmente gané en NVDA?". Pro: 40 consultas/sem.',
  },
]

const HOW_STEPS = [
  {
    n: 1,
    title: 'Creá tu cuenta gratis en Rendi',
    desc: 'En 30 segundos. Sin tarjeta, sin compromiso. El plan Free te alcanza para empezar a trackear con 1 broker.',
  },
  {
    n: 2,
    title: 'Descargá el CSV de Cocos',
    desc: 'En Cocos: Operaciones → Filtros → Exportar a CSV. Te baja el historial completo de compras, ventas, dividendos y depósitos.',
  },
  {
    n: 3,
    title: 'Importá el CSV en Rendi',
    desc: 'En /imports subís el archivo. Rendi mapea automáticamente los campos (asset, fecha, cantidad, precio, comisión, moneda) y crea las posiciones + operaciones.',
  },
  {
    n: 4,
    title: 'Ves tu cartera consolidada en USD',
    desc: 'Dashboard con P&L en pesos y USD, gráfico de evolución, top performers, allocation. Si sumás otros brokers, todo queda en un solo lugar.',
  },
]

const RELATED = [
  { to: '/brokers/iol', label: 'Tracker IOL' },
  { to: '/brokers/binance', label: 'Tracker Binance' },
  { to: '/cedears', label: 'CEDEARs con FIFO' },
  { to: '/bonos-argentinos', label: 'Bonos AR' },
  { to: '/planes', label: 'Ver planes' },
]

export default function Cocos() {
  return (
    <KeywordLanding
      kicker="Tracker para Cocos Capital"
      h1="Seguí tu cartera de Cocos en USD real, con FIFO automático"
      intro="Cocos te muestra tu cartera en pesos. Rendi la consolida con tus otros brokers (IOL, Balanz, Schwab, Binance) y te muestra el P&L real en dólares blue, con FIFO automático para AFIP y Coach IA con memoria."
      features={FEATURES}
      howSteps={HOW_STEPS}
      relatedLinks={RELATED}
      metaTitle="Tracker Cocos Capital — Rendi | Cartera consolidada en USD"
      metaDescription="Seguí tu cartera de Cocos Capital + otros brokers (IOL, Balanz, Schwab, Binance) en Rendi. P&L real en USD blue, FIFO automático, Coach IA. Importás el CSV de Cocos en 30 segundos."
      canonicalPath="/brokers/cocos"
    />
  )
}
