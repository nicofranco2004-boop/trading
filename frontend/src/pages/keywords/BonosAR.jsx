// /bonos-argentinos — keyword landing para bonos AR (AL30, GD30, TX26, etc.)

import KeywordLanding from '../../components/landing/KeywordLanding'

const FEATURES = [
  {
    title: 'Soporte de bonos canje 2020: AL30, GD30, GD35, AE38, AL41',
    desc: 'Bonos soberanos ley local (ALxx) y ley NY (GDxx). Metadata completa: vencimiento, cupón actual, próxima amortización, paridad, TIR implícita.',
  },
  {
    title: 'Bonos CER (TX26, TX28, TZX26/27/28)',
    desc: 'Bonos ajustados por inflación con coeficiente CER actualizado. Rendi distingue capital ajustado vs renta cupón vs amortización de capital — clave para tu declaración.',
  },
  {
    title: 'P&L correcto: amortización vs renta',
    desc: 'Cuando un bono amortiza, parte del flujo es devolución de tu capital (no es ganancia). Rendi separa cost basis consumido vs ganancia realizada — la única forma de medir TIR real.',
  },
  {
    title: 'Cupones automáticos al broker correcto',
    desc: 'Cada cupón se registra al MEP del día en el broker donde tenés el bono. Si lo tenés en IOL ARS y cobrás cupón en pesos, Rendi convierte al dólar correcto.',
  },
  {
    title: 'Multi-broker para bonos: IOL, Cocos, Balanz, Bull',
    desc: 'Cargás tus bonos en cualquier broker. Rendi consolida la cartera total y te dice qué % está en soberanos vs CER vs corporativos.',
  },
  {
    title: 'Coach IA: análisis de tus bonos',
    desc: '"¿Cuál es la TIR de mi cartera de bonos?", "¿Mi exposición a AL30 vs GD30 es coherente?", "¿Cuándo recibo el próximo cupón de TX26?". Tool especializado en bonos AR.',
  },
]

const HOW_STEPS = [
  { n: 1, title: 'Creá tu cuenta gratis', desc: 'Sin tarjeta. El plan Free cubre carga manual de bonos AR.' },
  { n: 2, title: 'Cargá tus bonos AR', desc: 'En /posiciones, agregás el ticker (AL30, GD30, TX26, etc.), broker, cantidad y precio de compra. Rendi reconoce el bono y aplica la metadata.' },
  { n: 3, title: 'Registrá cobros y amortizaciones', desc: 'Cuando recibís un cupón o amortización, lo registrás en Operaciones. Rendi calcula la parte de capital vs renta automáticamente.' },
  { n: 4, title: 'Ves TIR real + flujo proyectado', desc: 'Dashboard con TIR de tu cartera de bonos, próximos cupones programados, vencimientos. Todo en USD MEP — la moneda en que cobrás los flujos.' },
]

const RELATED = [
  { to: '/brokers/iol', label: 'Tracker IOL' },
  { to: '/brokers/cocos', label: 'Tracker Cocos' },
  { to: '/cedears', label: 'CEDEARs con FIFO' },
  { to: '/planes', label: 'Ver planes' },
]

export default function BonosAR() {
  return (
    <KeywordLanding
      kicker="Tracker de bonos argentinos"
      h1="Seguí tus bonos AR (AL30, GD30, TX26) con TIR real y cupones automáticos"
      intro="Los bonos AR tienen complejidad: amortizaciones que no son renta, cupones en pesos que convertís a USD, CER que ajusta capital. Rendi maneja todo automático: metadata por bono, cupones al MEP correcto, separación capital/renta, TIR real de la cartera."
      features={FEATURES}
      howSteps={HOW_STEPS}
      relatedLinks={RELATED}
      metaTitle="Bonos AR (AL30, GD30, TX26) — Rendi | Tracker con TIR real"
      metaDescription="Tracker de bonos argentinos canje 2020 (AL30, GD30, GD35) y CER (TX26, TZX27). Cupones automáticos al MEP, amortización vs renta, TIR real. Multi-broker."
      canonicalPath="/bonos-argentinos"
    />
  )
}
