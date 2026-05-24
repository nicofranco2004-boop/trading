// /afip-cripto — keyword landing para "declarar cripto AFIP", "FIFO cripto"

import KeywordLanding from '../../components/landing/KeywordLanding'

const FEATURES = [
  {
    title: 'FIFO automático sobre tus operaciones cripto',
    desc: 'AFIP / ARCA requiere criterio FIFO (First In, First Out) para cripto desde 2018. Rendi aplica el criterio automático en cada venta y te entrega el P&L declarable.',
  },
  {
    title: 'Cost basis correcto al precio de adquisición',
    desc: 'Cada compra queda con su costo en USD al TC del día. Cuando vendés, descontás el lote más viejo primero y calculás la ganancia o pérdida realizada en USD.',
  },
  {
    title: 'Distinguís staking, trading, P2P',
    desc: 'AFIP tiene tratamiento distinto para staking (rendimiento financiero) vs trading spot (ganancia de capital). Rendi categoriza cada operación y separa los reportes.',
  },
  {
    title: 'Exportás CSV consolidado anual',
    desc: 'Al cierre del año fiscal, exportás un consolidado con todas tus operaciones cripto en USD: compras, ventas, FIFO aplicado, ganancia neta declarable. Listo para tu contador.',
  },
  {
    title: 'Soporte de Binance, exchanges P2P y wallets',
    desc: 'Cargás desde Binance (CSV directo) o manualmente desde otros exchanges. Stablecoins (USDT, USDC) tratadas como dólar; BTC/ETH/altcoins con precio live a USD.',
  },
  {
    title: 'Coach IA con conocimiento fiscal AR',
    desc: '"¿Cuánto ganancia declaro este año por mi BTC?", "¿Qué pasa con el staking en ETH?". Coach IA con contexto de la regulación argentina vigente.',
  },
]

const HOW_STEPS = [
  { n: 1, title: 'Creá tu cuenta gratis', desc: 'Free incluye 1 broker (alcanza para Binance). Sin tarjeta requerida para empezar.' },
  { n: 2, title: 'Cargá tu historial de operaciones', desc: 'Exportás el CSV de Binance (Wallet → Transaction History) o cargás manualmente. Rendi reconoce los pares y los precia al dólar del día.' },
  { n: 3, title: 'Rendi aplica FIFO automático', desc: 'Cuando vendés (o convertís) un token, Rendi descuenta del lote más viejo primero y calcula el cost basis al precio de adquisición original.' },
  { n: 4, title: 'Exportás el consolidado anual', desc: 'En diciembre / al cierre fiscal, descargás el CSV con todas tus operaciones, FIFO aplicado, ganancia neta declarable. Tu contador lo lee directo.' },
]

const RELATED = [
  { to: '/brokers/binance', label: 'Tracker Binance' },
  { to: '/cedears', label: 'CEDEARs con FIFO' },
  { to: '/bonos-argentinos', label: 'Bonos AR' },
  { to: '/planes', label: 'Ver planes' },
]

export default function AfipCripto() {
  return (
    <KeywordLanding
      kicker="AFIP / ARCA + cripto con FIFO"
      h1="Declarás tu cripto a AFIP con FIFO automático, sin armar Excels"
      intro="AFIP / ARCA requiere FIFO (First In, First Out) en operaciones cripto desde 2018. Armar la planilla a mano es un dolor de cabeza: cada venta hay que matchearla con la compra más vieja. Rendi lo hace automático — vos solo cargás las operaciones, nosotros calculamos el cost basis y la ganancia declarable."
      features={FEATURES}
      howSteps={HOW_STEPS}
      relatedLinks={RELATED}
      metaTitle="Declarar cripto a AFIP con FIFO — Rendi"
      metaDescription="FIFO automático para tu cripto (Binance, exchanges, wallets) según criterio fiscal AR. Cost basis correcto, distinción staking/trading, export CSV anual para tu contador."
      canonicalPath="/afip-cripto"
    />
  )
}
