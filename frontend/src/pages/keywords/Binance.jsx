// /brokers/binance — keyword landing para "tracker Binance Argentina"
//
// Los pasos para bajar el historial salen de la guía de la app (ver
// components/landing/landingDeBroker.js): acá no se escribe ningún camino del
// menú de Binance.

import KeywordLanding from '../../components/landing/KeywordLanding'
import { guiaDeBroker, descargaDe, comoFuncionaDe } from '../../components/landing/landingDeBroker'
import { cupoDe } from '../../data/prueba'
import { PRO_FEATURES, CUPO_CHAT } from '../../data/planCatalog'
import { FIFO_PARA_QUE, CRIPTO_PAGA, CSV_CONTADOR } from '../../data/impuestos'
import { otrasGuiasDeBrokers } from '../../data/guiasDeBrokers'

const GUIA = guiaDeBroker('binance')

const FEATURES = [
  {
    title: 'Cargá tu portfolio crypto de Binance',
    desc: 'Soporte completo de Spot: BTC, ETH, BNB, SOL, USDT, USDC y stablecoins. Convertimos a USD para que veas tu P&L real, no perdido en cripto-volatilidad.',
  },
  {
    title: 'Mezclá crypto + acciones + bonos AR en un solo dashboard',
    desc: 'Rendi es multi-asset. Combiná Binance con Cocos, IOL, Schwab. Allocation total: %en crypto, %en CEDEARs, %en bonos AR, %en cash USD.',
  },
  {
    title: 'FIFO automático sobre tu cripto',
    desc: `${FIFO_PARA_QUE} ${CRIPTO_PAGA} ${CSV_CONTADOR}`,
  },
  {
    title: 'Precio live de cada par contra USD',
    desc: 'Yahoo Finance + Binance API. Rendi muestra el precio actual de cada token y tu valor live en dólares — no la cotización stale en ARS de cripto.',
  },
  {
    title: 'Nada del historial de Binance se pierde',
    desc: 'Rendi lee cada fila del historial de Binance: compras y ventas, P2P, Convert, Earn y lo que te regalan, y la cantidad de cada moneda te da igual que en Binance. Ojo: lo que entra por Convert, Earn, un regalo o desde otra billetera queda sin costo, porque el archivo de Binance no dice cuánto pagaste.',
  },
  {
    title: 'Mervall-E AI con contexto de tu cartera completa',
    desc: `Chat IA con tu portfolio total. "¿Mi exposición a BTC vs equities es coherente con mi perfil de inversor?", "¿Qué cripto me hizo perder más este año?". Pro: ${cupoDe(PRO_FEATURES, CUPO_CHAT)} consultas/sem + memoria.`,
  },
]

const HOW_STEPS = comoFuncionaDe(GUIA, {
  title: 'Ves tu portfolio crypto en USD',
  desc: 'Dashboard con valor live, P&L, allocation por token. Si sumás brokers tradicionales, ves el mix completo.',
})

const RELATED = [
  { to: '/afip-cripto', label: 'Cripto e impuestos' },
  ...otrasGuiasDeBrokers('/brokers/binance'),
  { to: '/planes', label: 'Ver planes' },
]

export default function Binance() {
  return (
    <KeywordLanding
      kicker="Tracker para Binance Argentina"
      h1="Seguí tu cripto de Binance en dólares, con FIFO automático"
      intro="Binance te muestra tus saldos en cripto y USDT. Rendi pasa tu cartera a dólares, calcula la ganancia de cada venta con FIFO y te deja juntar tu cripto con CEDEARs, bonos argentinos y acciones en una sola pantalla."
      features={FEATURES}
      descarga={descargaDe(GUIA, 'Es un solo archivo: el historial completo de transacciones de tu cuenta.')}
      howSteps={HOW_STEPS}
      relatedLinks={RELATED}
      metaTitle="Tracker Binance Argentina — Rendi | Cripto en dólares con FIFO"
      metaDescription="Seguí tu cripto de Binance en dólares: BTC, ETH, USDT y más. La ganancia de cada venta con FIFO, para tu contador. Sumala a tus CEDEARs y acciones."
      canonicalPath="/brokers/binance"
    />
  )
}
