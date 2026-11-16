// /brokers/cocos — keyword landing para "tracker Cocos Capital"
// ════════════════════════════════════════════════════════════════════════════
// Target query: "tracker cocos capital", "seguir cartera cocos", "P&L cocos"
// Intent: usuario de Cocos buscando manera de ver su cartera consolidada con
// otros brokers (porque Cocos solo muestra Cocos).
//
// Los pasos para bajar los archivos salen de la guía de la app (ver
// components/landing/landingDeBroker.js): acá no se escribe ningún camino del
// menú de Cocos.

import KeywordLanding from '../../components/landing/KeywordLanding'
import { guiaDeBroker, descargaDe, comoFuncionaDe } from '../../components/landing/landingDeBroker'
import { cupoDe } from '../../data/prueba'
import { FIFO_PARA_QUE, VENTA_EXENTA } from '../../data/impuestos'
import { PRO_FEATURES, CUPO_CHAT } from '../../data/planCatalog'
import { otrasGuiasDeBrokers } from '../../data/guiasDeBrokers'

const GUIA = guiaDeBroker('cocos')

const FEATURES = [
  {
    title: 'Importá tus archivos de Cocos Capital en 30 segundos',
    desc: 'Subís los Movimientos y el Estado de Cuenta juntos. Reconocemos automáticamente acciones AR, CEDEARs, bonos y FCI.',
  },
  {
    title: 'P&L real en USD, no pesos nominales',
    desc: 'Cocos te muestra el monto en ARS. Rendi pasa cada operación al dólar MEP de su fecha — ves si realmente ganaste poder de compra o solo seguiste la inflación.',
  },
  {
    title: 'Combiná Cocos con IOL, Balanz, Schwab, Binance',
    desc: 'Rendi es multi-broker. Carga Cocos + el resto y ves todo consolidado: cartera total, allocation por geo, top 5 ganadores y perdedores.',
  },
  {
    title: 'FIFO automático para CEDEARs y acciones',
    desc: `${FIFO_PARA_QUE} ${VENTA_EXENTA}`,
  },
  {
    title: 'Soporte completo de bonos AR (AL30, GD30, TX26)',
    desc: 'Bonos canje 2020 y CER con metadata de cupones y amortizaciones. Cocos muestra el precio; Rendi te dice qué porcentaje es capital y qué es renta.',
  },
  {
    title: 'Mervall-E AI: preguntale por qué bajó tu cartera',
    desc: `Chat IA con contexto completo de tu cartera. "¿Por qué bajó mi mes?", "¿Dónde estoy concentrado?", "¿Cuánto realmente gané en NVDA?". Pro: ${cupoDe(PRO_FEATURES, CUPO_CHAT)} consultas/sem.`,
  },
]

const HOW_STEPS = comoFuncionaDe(GUIA, {
  title: 'Ves tu cartera consolidada en USD',
  desc: 'Dashboard con P&L en pesos y USD, gráfico de evolución, top performers, allocation. Si sumás otros brokers, todo queda en un solo lugar.',
})

const RELATED = [
  ...otrasGuiasDeBrokers('/brokers/cocos'),
  { to: '/cedears', label: 'CEDEARs con FIFO' },
  { to: '/bonos-argentinos', label: 'Bonos AR' },
  { to: '/planes', label: 'Ver planes' },
]

export default function Cocos() {
  return (
    <KeywordLanding
      kicker="Tracker para Cocos Capital"
      h1="Seguí tu cartera de Cocos en USD real, con FIFO automático"
      intro="Cocos te muestra tu cartera en pesos. Rendi la junta con tus otros brokers (IOL, Balanz, Schwab, Binance) y te muestra cuánto ganaste de verdad en dólares, al MEP de cada fecha. Con FIFO automático ves la ganancia de cada venta, y Mervall-E AI te contesta con memoria de tu cartera."
      features={FEATURES}
      descarga={descargaDe(GUIA, 'Son dos archivos: tus Movimientos (lo que compraste, vendiste y cobraste) y el Estado de Cuenta (lo que tenés hoy).')}
      howSteps={HOW_STEPS}
      relatedLinks={RELATED}
      metaTitle="Tracker Cocos Capital — Rendi | Cartera consolidada en USD"
      metaDescription="Seguí tu cartera de Cocos Capital junto a IOL, Balanz, Schwab y Binance: P&L real en USD, FIFO automático y Mervall-E AI. Importás el CSV en 30 segundos."
      canonicalPath="/brokers/cocos"
    />
  )
}
