// /brokers/binance — keyword landing para "tracker Binance Argentina"
//
// Los pasos para bajar el historial salen de la guía de la app (ver
// components/landing/landingDeBroker.js): acá no se escribe ningún camino del
// menú de Binance.

import KeywordLanding from '../../components/landing/KeywordLanding'
import { guiaDeBroker, descargaDe, comoFuncionaDe } from '../../components/landing/landingDeBroker'
import { cupoDe } from '../../data/prueba'
import { PRO_FEATURES, CUPO_CHAT } from '../../data/planCatalog'
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
    title: 'FIFO automático para AFIP / ARCA sobre crypto',
    desc: 'AFIP requiere FIFO en cripto desde 2018. Rendi aplica criterio fiscal AR automático y exporta el consolidado anual de ganancias y pérdidas declarables.',
  },
  {
    title: 'Precio live de cada par contra USD',
    desc: 'Yahoo Finance + Binance API. Rendi muestra el precio actual de cada token y tu valor live en dólares — no la cotización stale en ARS de cripto.',
  },
  {
    title: 'Distinguís staking, P2P, trading y holding',
    desc: 'Categorizás cada operación. Importante para tu reporte AFIP: el staking tiene tratamiento distinto al trading spot.',
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
  { to: '/afip-cripto', label: 'AFIP cripto + FIFO' },
  ...otrasGuiasDeBrokers('/brokers/binance'),
  { to: '/planes', label: 'Ver planes' },
]

export default function Binance() {
  return (
    <KeywordLanding
      kicker="Tracker para Binance Argentina"
      h1="Seguí tu portfolio crypto de Binance, con FIFO AFIP automático"
      intro="Binance te muestra balances en cripto y USDT. Rendi convierte tu portfolio a dólares, aplica FIFO automático (criterio fiscal AR) y te permite combinar crypto con CEDEARs, bonos AR y acciones en un solo dashboard."
      descarga={descargaDe(GUIA, 'Es un solo archivo: el historial completo de transacciones de tu cuenta.')}
      features={FEATURES}
      howSteps={HOW_STEPS}
      relatedLinks={RELATED}
      metaTitle="Tracker Binance Argentina — Rendi | Crypto en USD con FIFO AFIP"
      metaDescription="Seguí tu portfolio crypto de Binance con Rendi: BTC, ETH, USDT y más en USD real. FIFO automático para AFIP / ARCA. Mezclá crypto con acciones AR y CEDEARs."
      canonicalPath="/brokers/binance"
    />
  )
}
