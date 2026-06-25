// /brokers/iol — keyword landing para "tracker IOL Invertí Online"

import KeywordLanding from '../../components/landing/KeywordLanding'

const FEATURES = [
  {
    title: 'Cargá tu cartera de IOL Invertí Online',
    desc: 'Soporte completo del catálogo IOL: acciones AR (Merval), CEDEARs, bonos canje 2020 (AL30, GD30, GD35, AE38), bonos CER (TX26, TX28) y ON corporativas.',
  },
  {
    title: 'P&L real en USD blue para tu cartera ARS',
    desc: 'IOL opera mayormente en pesos. Rendi convierte cada operación al dólar blue del día y calcula el P&L real en USD — no la ilusión nominal en ARS.',
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
    title: 'Coach IA con memoria persistente (Pro)',
    desc: 'Chat IA con contexto de tu cartera. "¿Cuánto realmente gané en AL30 este año?", "¿Por qué bajó mi cartera en mayo?". Memoria persistente: los hechos que le aclarás los respeta entre sesiones.',
  },
]

const HOW_STEPS = [
  { n: 1, title: 'Creá tu cuenta gratis en Rendi', desc: 'Sin tarjeta. El plan Free te permite empezar a trackear 1 broker.' },
  { n: 2, title: 'Exportá tu historial de IOL', desc: 'En IOL: Mi Cuenta → Movimientos → Detalle de Movimientos. Elegí desde el inicio de tu cuenta hasta hoy y, abajo de todo, “Descargar movimientos históricos” (.xls).' },
  { n: 3, title: 'Importá el .xls en Rendi', desc: 'Mapeamos automáticamente los campos de IOL (asset, fecha, cantidad, precio, broker). Verificá la previa antes de confirmar.' },
  { n: 4, title: 'Ves tu cartera en USD + insights', desc: 'Dashboard con KPIs, gráfico de evolución, allocation por activo, top 5. Tu cartera real en USD blue, no en pesos.' },
]

const RELATED = [
  { to: '/brokers/cocos', label: 'Tracker Cocos Capital' },
  { to: '/brokers/binance', label: 'Tracker Binance' },
  { to: '/bonos-argentinos', label: 'Bonos AR' },
  { to: '/cedears', label: 'CEDEARs con FIFO' },
  { to: '/planes', label: 'Ver planes' },
]

export default function IOL() {
  return (
    <KeywordLanding
      kicker="Tracker para IOL Invertí Online"
      h1="Seguí tu cartera de IOL en USD real, con bonos AR y FIFO automático"
      intro="IOL te muestra el monto en pesos. Rendi convierte cada operación al dólar blue del día, soporta el catálogo completo (acciones AR, CEDEARs, bonos canje 2020, CER) y calcula tu FIFO automático para AFIP."
      features={FEATURES}
      howSteps={HOW_STEPS}
      relatedLinks={RELATED}
      metaTitle="Tracker IOL Invertí Online — Rendi | P&L real en USD"
      metaDescription="Seguí tu cartera de IOL en USD real con Rendi. Bonos AR (AL30, GD30, TX26), CEDEARs, acciones Merval. FIFO automático para AFIP, Coach IA, multi-broker."
      canonicalPath="/brokers/iol"
    />
  )
}
