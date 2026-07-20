// FAQ — preguntas frecuentes de la landing.
// ════════════════════════════════════════════════════════════════════════════
// Componente con doble propósito:
//   1. Contenido útil para el usuario que está evaluando si suscribirse.
//   2. SEO: el JSON-LD FAQPage genera "rich snippets" en Google que ocupan
//      2-3x el espacio en SERP y aumentan CTR drásticamente.
//
// Mantener el array `FAQS` sincronizado entre el render y el JSON-LD (lo
// generamos del mismo array para no duplicar).
//
// Reglas de contenido:
//   - Preguntas en lenguaje natural (cómo googlea el user, no jargon).
//   - Respuestas cortas (50-150 palabras) con keywords AR-relevantes.
//   - Sin claim falsos / sin sobre-promete (Google penaliza YMYL spam).

import { useState } from 'react'
import { Helmet } from 'react-helmet-async'
import { ChevronDown } from 'lucide-react'

// Orden = secuencia de objeciones que frenan el signup (no orden SEO). La #1 de
// un retail frío que va a cargar su cartera es la confianza/seguridad, así que
// va primera y abierta por default. Luego privacidad de datos, después
// validación (brokers) y costo (¿gratis?), y al final el detalle operativo.
const FAQS = [
  {
    q: '¿Es seguro? ¿Rendi tiene acceso a mi plata o a mis brokers?',
    a: 'No. Rendi es una herramienta solo de seguimiento e informativa. No hay integración bancaria, ni custodia de fondos, ni operatoria. No ejecutamos órdenes ni vemos tus credenciales de broker — vos cargás los datos manualmente o por CSV. Tu plata vive en tu broker; Rendi solo te ayuda a ver todo consolidado.',
  },
  {
    q: '¿Qué hacen con mis datos? ¿Puedo borrar mi cuenta?',
    a: 'Tus datos son tuyos y los usamos solo para mostrarte tu cartera consolidada — no los vendemos ni los compartimos con terceros. Las posiciones y montos que cargás viajan encriptados (HTTPS). Podés pedir la baja de tu cuenta y el borrado de tus datos cuando quieras escribiéndonos a hola@rendi.finance. Más detalle en nuestra Política de Privacidad.',
  },
  {
    q: '¿Rendi funciona con Cocos Capital, IOL, Balanz, Schwab y Binance?',
    a: 'Sí. Rendi es multi-broker: podés cargar tu cartera de Cocos Capital, IOL Invertí Online, Balanz, Bull Market Brokers, Schwab, Interactive Brokers, Binance y otros brokers o exchanges. Importás el CSV o cargás manualmente las posiciones. Cada broker queda con su moneda original, valor live en USD y P&L. El plan Plus permite hasta 3 brokers; Pro es ilimitado.',
  },
  {
    q: '¿Es gratis de verdad? ¿Qué incluye el plan Free?',
    a: 'Sí. El plan Free es gratis para siempre y no te pedimos tarjeta para empezar. Incluye el seguimiento de tu cartera con P&L real en dólares, FIFO automático para AFIP y 12 preguntas guiadas al Coach IA. Si en algún momento querés más —más brokers, chat libre con el Coach IA o métricas avanzadas— pasás a Plus o Pro. El Free no caduca.',
  },
  {
    q: '¿Cómo se calcula el P&L en dólares cuando opero en pesos?',
    a: 'Rendi convierte cada operación al dólar blue del día en que ocurrió (o al MEP/CCL según el activo). Eso te da un P&L real en USD que refleja qué pasó con tu poder de compra, no solo con el monto nominal en pesos. Para CEDEARs y bonos AR usamos el MEP implícito; para activos USD-denominated en brokers ARS, el blue.',
  },
  {
    q: '¿Cómo funciona el FIFO automático para AFIP / ARCA?',
    a: 'Cuando vendés un activo, Rendi descuenta automáticamente del lote más viejo primero (First In, First Out — el criterio fiscal que usa AFIP / ARCA en Argentina). El resultado: cada venta tiene su costo de adquisición correcto y el P&L declarable queda calculado sin que tengas que hacer planillas. Exportás el CSV consolidado para pasárselo a tu contador.',
  },
  {
    q: '¿Funciona con CEDEARs, bonos argentinos y criptomonedas?',
    a: 'Sí. Rendi soporta CEDEARs (NVDA.BA, AAPL.BA, etc.) con ratio de conversión, bonos argentinos canje 2020 (AL30, GD30, GD35, AE38, AL41) y bonos CER (TX26, TX28, TZX26/27/28), incluyendo metadata de amortizaciones y cupones. También crypto (BTC, ETH, USDT y otras) cargadas desde Binance o exchanges manualmente.',
  },
  {
    q: '¿Cobran en pesos argentinos o en dólares?',
    a: 'Cobramos en pesos argentinos a precio fijo. Plus $5.990 / Pro $13.990 por mes, sin sorpresas. El cargo en tu tarjeta es el mismo número que ves en la página de planes. Periódicamente ajustamos los precios para mantenernos en equilibrio con la inflación — siempre con anuncio previo y respetando el precio actual de tu próximo cobro si ya estás suscripto.',
  },
  {
    q: '¿Qué hace el Coach IA y en qué planes está incluido?',
    a: 'El Coach IA usa el modelo Claude Haiku 4.5 con contexto completo de tu cartera (posiciones, operaciones, P&L histórico). Free y Plus tienen 12 preguntas guiadas predefinidas + 3 a 9 consultas por semana. En Pro desbloqueás chat libre con 40 consultas por semana, follow-ups en cualquier análisis, memoria persistente (los hechos que le aclarás los respeta entre sesiones) y respuestas con causalidad ("por qué pasó X", no solo "qué pasó").',
  },
  {
    q: '¿Puedo cancelar mi suscripción cuando quiera?',
    a: 'Sí, sin penalidad. Cancelás desde Configuración con un click. Mantenés acceso al plan pagado hasta el fin del período actual (mes o año) y después tu cuenta vuelve a Free automáticamente. No devolvemos el dinero del período en curso porque el servicio ya fue entregado por esos días — para casos especiales (cobro duplicado, falla material) ver nuestra Política de Reembolso.',
  },
]

export default function FAQ() {
  const [openIdx, setOpenIdx] = useState(0)  // primera abierta por default

  return (
    <section id="faq" className="py-20 md:py-28 border-t border-line/40">
      {/* JSON-LD FAQPage — generado del mismo array que el render para no
          desincronizar. Lo metemos en Helmet para que aparezca en el <head>. */}
      <Helmet>
        <script type="application/ld+json">{JSON.stringify({
          '@context': 'https://schema.org',
          '@type': 'FAQPage',
          mainEntity: FAQS.map(({ q, a }) => ({
            '@type': 'Question',
            name: q,
            acceptedAnswer: { '@type': 'Answer', text: a },
          })),
        })}</script>
      </Helmet>

      <div className="max-w-3xl mx-auto px-6">
        <div className="text-center mb-12">
          <p className="text-[12.5px] text-ink-2 mb-2 font-medium">FAQ</p>
          <h2 className="text-3xl md:text-4xl font-semibold tracking-tight text-ink-0 mb-3">
            Preguntas frecuentes
          </h2>
          <p className="text-sm text-ink-2 max-w-xl mx-auto leading-relaxed">
            Lo que más nos preguntan los inversores argentinos antes de empezar.
          </p>
        </div>

        <ul className="space-y-2">
          {FAQS.map((item, i) => {
            const isOpen = openIdx === i
            return (
              <li
                key={i}
                className={`border rounded-lg transition-colors ${
                  isOpen
                    ? 'border-data-violet/40 bg-data-violet/[0.04]'
                    : 'border-line/50 hover:border-line-2/70'
                }`}
              >
                <button
                  type="button"
                  onClick={() => setOpenIdx(isOpen ? -1 : i)}
                  className="w-full flex items-start justify-between gap-4 px-5 py-4 text-left"
                  aria-expanded={isOpen}
                >
                  <h3 className={`text-sm md:text-base font-medium leading-snug ${isOpen ? 'text-ink-0' : 'text-ink-1'}`}>
                    {item.q}
                  </h3>
                  <ChevronDown
                    size={16}
                    strokeWidth={1.75}
                    className={`flex-shrink-0 mt-1 text-ink-3 transition-transform ${isOpen ? 'rotate-180 text-data-violet' : ''}`}
                  />
                </button>
                {isOpen && (
                  <div className="px-5 pb-4 text-sm text-ink-2 leading-relaxed">
                    {item.a}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      </div>
    </section>
  )
}
