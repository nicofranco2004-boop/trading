// /brokers/iol — keyword landing para "tracker IOL Invertí Online"
//
// Los pasos para bajar los archivos salen de la guía de la app (ver
// components/landing/landingDeBroker.js): acá no se escribe ningún camino del
// menú de IOL.

import KeywordLanding from '../../components/landing/KeywordLanding'
import { guiaDeBroker, descargaDe, comoFuncionaDe } from '../../components/landing/landingDeBroker'
import { otrasGuiasDeBrokers } from '../../data/guiasDeBrokers'

const GUIA = guiaDeBroker('iol')

const FEATURES = [
  {
    title: 'Cargá tu cartera de IOL Invertí Online',
    desc: 'Soporte completo del catálogo IOL: acciones AR (Merval), CEDEARs, bonos canje 2020 (AL30, GD30, GD35, AE38), bonos CER (TX26, TX28) y ON corporativas.',
  },
  {
    title: 'P&L real en USD para tu cartera en pesos',
    desc: 'IOL opera mayormente en pesos. Rendi pasa cada operación al dólar MEP de su fecha y calcula el P&L real en USD — no la ilusión nominal en ARS.',
  },
  {
    title: 'FIFO automático para tu declaración AFIP',
    desc: 'Cada venta descuenta del lote más viejo primero (FIFO, criterio fiscal AR). Exportás el consolidado anual para presentar a AFIP / ARCA sin armar Excels.',
  },
  {
    title: 'Multi-broker: combiná IOL + Cocos + Binance',
    desc: 'Rendi soporta múltiples brokers en simultáneo. Ves tu cartera total consolidada, no fragmentada plataforma por plataforma.',
  },
  {
    title: 'Bonos canje 2020 + CER con metadata completa',
    desc: 'AL30, GD30, GD35, GD41, TX26, TZX27 y más. Cupones automáticos, amortizaciones, valor técnico, paridad. IOL te muestra el precio; Rendi te dice la historia.',
  },
  {
    title: 'Mervall-E AI con memoria persistente (Pro)',
    desc: 'Chat IA con contexto de tu cartera. "¿Cuánto realmente gané en AL30 este año?", "¿Por qué bajó mi cartera en mayo?". Memoria persistente: los hechos que le aclarás los respeta entre sesiones.',
  },
]

const HOW_STEPS = comoFuncionaDe(GUIA, {
  title: 'Ves tu cartera en USD + insights',
  desc: 'Dashboard con KPIs, gráfico de evolución, allocation por activo, top 5. Tu cartera real en USD, no en pesos.',
})

const RELATED = [
  ...otrasGuiasDeBrokers('/brokers/iol'),
  { to: '/bonos-argentinos', label: 'Bonos AR' },
  { to: '/cedears', label: 'CEDEARs con FIFO' },
  { to: '/planes', label: 'Ver planes' },
]

export default function IOL() {
  return (
    <KeywordLanding
      kicker="Tracker para IOL Invertí Online"
      h1="Seguí tu cartera de IOL en USD real, con bonos AR y FIFO automático"
      intro="IOL te muestra el monto en pesos. Rendi pasa cada operación al dólar MEP de su fecha, soporta el catálogo completo (acciones AR, CEDEARs, bonos canje 2020, CER) y calcula tu FIFO automático para AFIP."
      features={FEATURES}
      descarga={descargaDe(GUIA, 'Son dos archivos, los dos desde la web de IOL: el Detalle de Movimientos (tu historial) y el Resumen de Cuenta (lo que tenés hoy).')}
      howSteps={HOW_STEPS}
      relatedLinks={RELATED}
      metaTitle="Tracker IOL Invertí Online — Rendi | P&L real en USD"
      metaDescription="Seguí tu cartera de IOL en USD real con Rendi. Bonos AR (AL30, GD30, TX26), CEDEARs, acciones Merval. FIFO automático para AFIP, Mervall-E AI, multi-broker."
      canonicalPath="/brokers/iol"
    />
  )
}
