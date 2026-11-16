// /afip-cripto — keyword landing para "declarar cripto ARCA / AFIP", "FIFO cripto"
// Lo que dice de impuestos sale de data/impuestos.js: no escribir frases fiscales a mano.
// Ojo: para la cripto de una persona la ley no exige FIFO con texto expreso
// (sólo por remisión al capítulo de empresas): es la forma prudente. Por eso
// acá no dice «ARCA requiere FIFO» (ni «la ley no lo exige»).

import KeywordLanding from '../../components/landing/KeywordLanding'
import { PASO_CREAR_CUENTA } from '../../data/prueba'
import { FIFO_PARA_QUE, CRIPTO_PAGA, CSV_CONTADOR } from '../../data/impuestos'

const FEATURES = [
  {
    title: 'FIFO automático sobre tus operaciones cripto',
    desc: `${FIFO_PARA_QUE} Descontar primero de la compra más vieja es la forma prudente, y la más usada, de calcular la ganancia de tu cripto.`,
  },
  {
    title: 'El costo de cada compra, al dólar de su día',
    desc: 'Cada compra queda con su costo en dólares al tipo de cambio de ese día. Cuando vendés, Rendi descuenta de la compra más vieja primero y te da la ganancia o pérdida en dólares.',
  },
  {
    title: 'Nada del historial de Binance se pierde',
    desc: 'Rendi lee cada fila del historial de Binance: compras y ventas, P2P, Convert, Earn y lo que te regalan, y la cantidad de cada moneda te da igual que en Binance. Ojo: lo que entra por Convert, Earn, un regalo o desde otra billetera queda sin costo, porque el archivo de Binance no dice cuánto pagaste.',
  },
  {
    title: 'Exportás el CSV de tus ventas',
    desc: 'Cuando quieras (por ejemplo, al cierre del año), exportás desde Operaciones un CSV con cada venta, compra por compra: cuándo y a cuánto compraste, cuándo y a cuánto vendiste, y la ganancia en dólares. Trae todos tus activos y años juntos: tu contador se queda con la cripto del año. Es de los planes Plus y Pro.',
  },
  {
    title: 'Soporte de Binance, exchanges P2P y wallets',
    desc: 'Cargás desde Binance (CSV directo) o manualmente desde otros exchanges. Stablecoins (USDT, USDC) tratadas como dólar; BTC/ETH/altcoins con precio live a USD.',
  },
  {
    title: 'Mervall-E AI: preguntale por tu cripto',
    desc: '"¿Cuánta ganancia realicé este año con BTC?", "¿Qué cripto me está costando más plata?". Mervall-E AI responde con tus operaciones reales. Lo impositivo lo define tu contador, con el CSV que exportás.',
  },
]

const HOW_STEPS = [
  // El paso 1 es el mismo en las seis landings y sale de `data/prueba.js`:
  // decía que el plan Free alcanzaba para empezar, y el Free ya no existe
  // para quien se registra.
  { n: 1, ...PASO_CREAR_CUENTA },
  { n: 2, title: 'Cargá tu historial de operaciones', desc: 'Exportás el CSV de Binance (Wallet → Transaction History) o cargás manualmente. Rendi reconoce los pares y los precia al dólar del día.' },
  { n: 3, title: 'Rendi aplica FIFO automático', desc: 'Cuando vendés un token por dólares o USDT, Rendi descuenta de la compra más vieja primero y calcula la ganancia contra lo que te costó.' },
  { n: 4, title: 'Exportás el consolidado anual', desc: 'En diciembre / al cierre fiscal, descargás desde Operaciones el CSV con cada venta, compra por compra, y su ganancia. Tu contador filtra la cripto y el año que declara.' },
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
      kicker="Cripto e impuestos (ARCA, la ex AFIP)"
      h1="Calculá la ganancia de tu cripto con FIFO, sin armar Excels"
      intro={`${CRIPTO_PAGA} Para saber cuánto ganaste, lo prudente es descontar cada venta de la compra más vieja primero (FIFO, o PEPS) y pasar cada compra al dólar de su fecha: a mano es un dolor de cabeza. Con Rendi, vos cargás las operaciones y la cuenta se hace sola. ${CSV_CONTADOR}`}
      features={FEATURES}
      howSteps={HOW_STEPS}
      relatedLinks={RELATED}
      metaTitle="Impuestos de tu cripto (ARCA, ex AFIP), con FIFO — Rendi"
      metaDescription="La ganancia de cada venta de tu cripto (Binance, exchanges, wallets) con FIFO, y un CSV para que tu contador declare en ARCA (ex AFIP)."
      canonicalPath="/afip-cripto"
    />
  )
}
