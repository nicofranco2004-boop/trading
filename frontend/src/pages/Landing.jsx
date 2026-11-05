// Landing — la portada: lo primero que ve quien llega sin sesión (y desde un
// anuncio).
// ════════════════════════════════════════════════════════════════════════════
// Rediseño del 2026-11 (maqueta aprobada por Nico el 03/11): deja de vender una
// sola cosa («cuánto ganaste en dólares») y muestra que Rendi junta TODAS tus
// inversiones en un solo lugar: cartera, salud, técnico, fundamental, IA y
// reportes. Lo único que no hace es operar.
//
// De arriba hacia abajo:
//   Héroe            título + los brokers mandándole todo a Rendi (HubBrokers)
//   Cinta            brokers con los que funciona
//   Video            «Mirá Rendi en un minuto» (VideoRendi)
//   Qué hace         seis pestañas que pasan solas cada 4 s (RecorridoModulos)
//   Sin / con Rendi  por qué en un solo lugar, renglón por renglón
//   Cómo funciona    tres pasos (el HowTo de index.html dice los MISMOS tres)
//   Precios · Guías por broker · Preguntas · Fundador · Cierre · Pie
//   + en el celular, un botón fijo abajo para registrarse.
//
// Todo se ve completo sin animación: es lo que sale en el HTML ya escrito que
// leen Google y las IA (scripts/prerender.mjs) y lo que ve quien pidió
// «reducir movimiento». Las animaciones son de entrada (clases `lp-*`).

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Check, Eye, Mail, Instagram, Linkedin } from 'lucide-react'
import RendiLogo from '../components/RendiLogo'
import PageMeta from '../components/PageMeta'
// Precios y features desde `data/`, NO desde la página de planes: importarlos
// de ahí arrastraba esa página entera al bundle de la landing y anulaba su
// carga diferida.
import { fmtArs, PLUS_PRICE_ARS_MONTHLY, PRO_PRICE_ARS_MONTHLY } from '../data/pricing'
import {
  PLUS_FEATURES, PRO_FEATURES,
  TRIAL_TOTAL_DAYS, TRIAL_PRO_DAYS, TRIAL_PLUS_DAYS, CUPO_CHAT } from '../data/planCatalog'
import { pedirAlServidor } from '../utils/api'
import { whatsappUrl } from '../utils/support'
import SupportWhatsAppFab, { WhatsAppIcon } from '../components/SupportWhatsAppFab'
import { ESPACIO_ABAJO_CELULAR } from '../components/mobile/espacioAbajo'
import FAQ from '../components/landing/FAQ'
import HubBrokers from '../components/landing/HubBrokers'
import RecorridoModulos from '../components/landing/RecorridoModulos'
import VideoRendi from '../components/landing/VideoRendi'
// El botón de la prueba es el MISMO texto en la home, las landings de SEO, el
// blog y la guía.
import { CTA_PRUEBA, cupoDe } from '../data/prueba'
import { useAlVerse } from '../hooks/useAlVerse'

// El demo se abre con una carga completa (no con el router): arranca la app
// con su propio estado de demo.
const abrirDemo = () => { window.location.href = '/?demo=1' }

// ─── Piezas chicas ───────────────────────────────────────────────────────────

const BOTON = 'inline-flex items-center justify-center gap-2 font-medium rounded-xl transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-data-violet'
const BOTON_1 = `${BOTON} bg-data-violet hover:bg-rendi-violet-hover text-white lp-sombra-boton hover:-translate-y-px`
const BOTON_2 = `${BOTON} bg-bg-1 text-ink-0 border border-line-2 hover:border-data-violet/60`

function Ceja({ children }) {
  return <p className="text-[13px] font-medium text-data-violet mb-2.5">{children}</p>
}

function Cabecera({ ceja, titulo, children, centro }) {
  return (
    <div className={`max-w-[720px] mb-10 ${centro ? 'mx-auto text-center' : ''}`}>
      <Ceja>{ceja}</Ceja>
      <h2 className="text-[clamp(28px,3.6vw,42px)] leading-[1.08] font-semibold tracking-tight text-ink-0 text-balance mb-3">{titulo}</h2>
      {children && <p className="text-[16.5px] text-ink-1 leading-relaxed">{children}</p>}
    </div>
  )
}

const Tilde = ({ className = '' }) => <Check size={16} strokeWidth={2.4} className={`shrink-0 text-rendi-pos ${className}`} aria-hidden="true" />

// ─── Barra de arriba ─────────────────────────────────────────────────────────

function NavBar() {
  const links = [['#video', 'Video'], ['#features', 'Qué hace'], ['#como-funciona', 'Cómo funciona'], ['#pricing', 'Precios'], ['#faq', 'Preguntas']]
  return (
    <header className="sticky top-0 z-30 backdrop-blur-md bg-bg-0/80 border-b border-line/70">
      <div className="max-w-[1180px] mx-auto px-4 sm:px-6 h-16 flex items-center gap-6">
        <Link to="/" className="flex items-center gap-2.5 shrink-0">
          <RendiLogo size={32} />
          <span className="text-[21px] font-semibold tracking-tight text-ink-0">rendi</span>
        </Link>
        <nav className="hidden md:flex gap-5 ml-3 text-sm text-ink-2" aria-label="Secciones">
          {links.map(([h, t]) => <a key={h} href={h} className="hover:text-ink-0 transition-colors">{t}</a>)}
        </nav>
        <div className="ml-auto flex items-center gap-2.5">
          <Link to="/login" className="hidden min-[420px]:inline text-sm text-ink-1 hover:text-ink-0 px-1.5 py-2">Ingresar</Link>
          <Link to="/login?mode=register" className={`${BOTON_1} text-sm px-3.5 py-2`}>Probar gratis</Link>
        </div>
      </div>
    </header>
  )
}

// ─── Héroe ───────────────────────────────────────────────────────────────────

const MODULOS_CHIPS = ['Cartera unificada', 'Ganancia en dólares', 'Salud de cartera', 'Análisis técnico',
  'Análisis fundamental', 'Comparador', 'Alertas', 'Mervall-E AI', 'Reportes']

function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="relative max-w-[1180px] mx-auto px-4 sm:px-6 py-10 lg:py-16 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] gap-10 items-center">
        <div className="min-w-0">
          {/* H1 único de la portada. */}
          <h1 className="text-[clamp(38px,5.6vw,68px)] leading-none font-semibold tracking-tighter text-ink-0 mb-6">
            Todas tus inversiones,
            <span className="block headline-sweep">en un solo lugar.</span>
          </h1>
          {/* Las palabras que busca la gente (Cocos, IOL, Schwab, Binance,
              dólares, cartera) van acá, en el primer párrafo. */}
          <p className="text-[clamp(16px,1.5vw,18px)] text-ink-1 leading-relaxed max-w-[34em] mb-6">
            Juntá Cocos, IOL, Balanz, Schwab y Binance y mirá cuánto ganás de verdad, en dólares.
            Revisá la salud de tu cartera, analizá cada activo y compará antes de decidir. Todo lo que
            hoy hacés con cinco apps y un Excel, en una sola.
          </p>
          <ul className="flex flex-wrap gap-1.5 mb-7" aria-label="Lo que hace Rendi">
            {MODULOS_CHIPS.map(m => (
              <li key={m} className="text-[12.5px] text-ink-1 border border-line-2 rounded-full px-2.5 py-1 bg-bg-1/60">{m}</li>
            ))}
          </ul>
          <div data-ctas-heroe="" className="flex flex-wrap gap-2.5 mb-4">
            <Link to="/login?mode=register" className={`${BOTON_1} px-5 py-3`}>
              {CTA_PRUEBA}<ArrowRight size={16} strokeWidth={2.2} />
            </Link>
            <button type="button" onClick={abrirDemo} className={`${BOTON_2} px-5 py-3`}>
              <Eye size={16} strokeWidth={2} />Ver demo sin registrarme
            </button>
          </div>
          <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-[13px] text-ink-2">
            {['Sin tarjeta', 'Sólo lectura', 'No pedimos las claves de tu broker'].map(t => (
              <li key={t} className="inline-flex items-center gap-1.5"><Tilde className="!w-3.5 !h-3.5" />{t}</li>
            ))}
          </ul>
        </div>
        <HubBrokers />
      </div>
    </section>
  )
}

// ─── Cinta de brokers ────────────────────────────────────────────────────────

function CintaBrokers() {
  const brokers = ['Cocos', 'IOL', 'Balanz', 'Bull Market', 'Schwab', 'Binance', 'Wise', 'PPI', 'Allaria']
  return (
    <section className="border-y border-line/70 bg-bg-1/45 py-5 overflow-hidden">
      <p className="text-center text-[13px] text-ink-2 mb-3">Funciona con los brokers que ya usás</p>
      <div className="relative overflow-hidden lp-borde-difuso">
        {/* Dos copias iguales: la cinta corre media pista y vuelve a empezar. */}
        <div className="ticker-scroll flex gap-[52px] w-max">
          {[...brokers, ...brokers].map((b, i) => (
            <span key={i} aria-hidden={i >= brokers.length} className="text-[17px] font-semibold tracking-tight text-ink-2 whitespace-nowrap">{b}</span>
          ))}
        </div>
      </div>
    </section>
  )
}

// ─── Video ───────────────────────────────────────────────────────────────────

function SeccionVideo() {
  return (
    <section id="video" className="max-w-[1180px] mx-auto px-4 sm:px-6 pt-16 sm:pt-[88px] scroll-mt-20">
      <Cabecera centro ceja="Mirá Rendi en un minuto" titulo="Una cartera de ejemplo, de punta a punta.">
        Cuatro brokers juntos, la ganancia en dólares, la salud de la cartera, el gráfico, el comparador y
        Mervall-E AI. Todo en la app real.
      </Cabecera>
      <VideoRendi />
    </section>
  )
}

// ─── Qué hace ────────────────────────────────────────────────────────────────

function SeccionModulos() {
  return (
    <section id="features" className="max-w-[1180px] mx-auto px-4 sm:px-6 py-16 sm:py-[88px] scroll-mt-20">
      <Cabecera ceja="Todo lo que hace Rendi" titulo="Seguís, analizás y decidís desde el mismo lugar.">
        Lo único que no hace Rendi es operar: eso lo seguís haciendo en tu broker. Todo lo demás, desde
        cuánto ganaste hasta qué comprar después, está acá adentro.
      </Cabecera>
      <RecorridoModulos />
    </section>
  )
}

// ─── Sin Rendi / con Rendi ───────────────────────────────────────────────────

const ANTES_AHORA = [
  ['La app de Cocos, la de IOL y la de Binance, cada una con su número', 'Un solo número: todo lo que tenés', 'Con el detalle de cada broker cuando lo querés ver'],
  ['La calculadora para saber si ganaste en dólares o sólo en pesos', 'Tu ganancia real en dólares', 'Cada operación en pesos, al dólar MEP del día en que la hiciste'],
  ['Un Excel que se rompe cada vez que vendés', 'Las cuentas se hacen solas', 'Importás el archivo de tu broker y listo'],
  ['Una web para el gráfico, otra para los balances, otra para las noticias', 'Técnico, fundamental y noticias en la misma ficha', 'Del activo que tenés o del que estás mirando'],
  ['Nadie que te diga qué estás haciendo mal', 'Salud de cartera y Mervall-E AI', 'Te marcan el riesgo antes de que te cueste plata'],
]

function AntesConRendi() {
  // Se tacha lo de antes y se prende lo de ahora, renglón por renglón, cuando
  // la tabla entra en pantalla. Antes de verse (y sin animación) está completa.
  const [alVerse, visto] = useAlVerse({ threshold: 0.35, rootMargin: '0px' })
  const [armada, setArmada] = useState(false)
  useEffect(() => { if (!visto) setArmada(true) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <section className="max-w-[1180px] mx-auto px-4 sm:px-6 pb-16 sm:pb-[88px]">
      <Cabecera ceja="Por qué en un solo lugar" titulo="Hoy tus inversiones están repartidas. Rendi las junta.">
        Cada broker te muestra sólo su parte, en su moneda y con su cuenta. Rendi es el lugar donde todo se
        encuentra y se lee igual.
      </Cabecera>
      <div ref={alVerse} className={`border border-line-2 rounded-xl bg-bg-1 overflow-hidden ${armada ? 'lp-por-tachar' : ''} ${visto ? 'lp-visto' : ''}`}>
        <div className="hidden md:grid grid-cols-[minmax(0,1fr)_40px_minmax(0,1fr)] text-[13px] font-semibold text-ink-2 bg-bg-2/60 border-b border-line">
          <div className="px-[18px] py-3.5">Sin Rendi</div><div /><div className="px-[18px] py-3.5 text-ink-0">Con Rendi</div>
        </div>
        {ANTES_AHORA.map(([antes, ahora, detalle], i) => (
          <div key={antes} style={{ '--i': i }}
               className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_40px_minmax(0,1fr)] md:items-center border-b border-line/70 last:border-0">
            <div className="px-[18px] pt-3.5 pb-0.5 md:py-3.5 text-[13.5px] md:text-[15px] text-ink-2 min-w-0">
              <span className="lp-tachado">{antes}</span>
            </div>
            <div className="hidden md:block text-center text-ink-3" aria-hidden="true">→</div>
            <div className="px-[18px] pt-1 pb-3.5 md:py-3.5 flex gap-2.5 items-start text-[15px] text-ink-0 min-w-0 lp-ahora">
              <Tilde className="mt-1" />
              <div>{ahora}<small className="block text-[13px] text-ink-2">{detalle}</small></div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

// ─── Cómo funciona ───────────────────────────────────────────────────────────
// Los tres pasos los repite el HowTo de `index.html` para Google: si cambian
// acá, cambian allá (el prerender lo deja sólo en la portada).

function DibujoArchivo() {
  return (
    <>
      <div className="absolute left-1/2 top-[22px] -ml-[78px] w-[156px] flex items-center gap-2 px-2.5 py-2 rounded-lg bg-bg-1 border border-line-2 text-[11.5px] text-ink-1 lp-cae">
        <i className="w-4 h-5 rounded-sm bg-rendi-pos/25 border border-rendi-pos/60 shrink-0" />movimientos-cocos.xlsx
      </div>
      <div className="absolute left-[22px] right-[22px] bottom-[18px] h-11 border-[1.5px] border-dashed border-line-3 rounded-lg grid place-items-center text-xs text-ink-2">
        Soltá el archivo de tu broker
      </div>
      <div className="absolute left-[22px] right-[22px] bottom-2.5 h-[3px] rounded-full bg-bg-3 overflow-hidden">
        <i className="block h-full bg-rendi-pos lp-carga" />
      </div>
    </>
  )
}

const DESORDEN = [[-52, 18, -12, 64], [40, -22, 9, 82], [-18, 30, 15, 70], [60, 10, -8, 90], [-40, -25, 18, 60], [22, 34, -14, 76], [-60, -8, 10, 88], [48, 26, -16, 66], [-26, -30, 12, 80]]

function DibujoOrdena() {
  const cols = [['Compras', 'bg-data-blue/55', 4], ['Ventas', 'bg-data-cyan/55', 3], ['Dividendos', 'bg-data-amber/55', 2]]
  let n = 0
  return (
    <div className="absolute inset-4 grid grid-cols-3 gap-2">
      {cols.map(([nombre, color, cuantos]) => (
        <div key={nombre} className="flex flex-col gap-1.5">
          <b className="text-[11px] font-medium text-ink-2">{nombre}</b>
          {Array.from({ length: cuantos }, () => {
            const [x, y, r, w] = DESORDEN[n]
            const style = { '--x': `${x}px`, '--y': `${y}px`, '--r': `${r}deg`, '--d': `${n * 0.12}s`, width: `${w}%` }
            n += 1
            return <span key={n} className={`h-3.5 rounded ${color} lp-acomoda`} style={style} />
          })}
        </div>
      ))}
    </div>
  )
}

function DibujoDecide() {
  return (
    <>
      <svg viewBox="0 0 200 100" preserveAspectRatio="none" className="absolute left-3.5 right-3.5 top-3.5 w-[calc(100%-28px)] h-[calc(100%-44px)]">
        <path d="M0 82 L20 76 L40 80 L60 62 L80 66 L100 50 L120 54 L140 36 L160 40 L180 22 L200 16"
              fill="none" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className="stroke-rendi-pos-fill lp-traza-bucle" />
      </svg>
      <p className="absolute left-3.5 bottom-2 text-xs text-rendi-pos lp-listo">Listo: tu cartera al día</p>
    </>
  )
}

function ComoFunciona() {
  const pasos = [
    { Dibujo: DibujoArchivo, titulo: 'Importás lo de tu broker', texto: 'Bajás el archivo de movimientos de Cocos, IOL, Balanz, Schwab o Binance y lo soltás en Rendi. Si preferís, cargás a mano: acciones, CEDEARs, bonos, cripto, fondos y plazos fijos.' },
    { Dibujo: DibujoOrdena, titulo: 'Rendi ordena todo', texto: 'Separa compras, ventas, dividendos y depósitos, pasa cada operación a dólares y arma tu cartera por broker y por tipo de activo. Las ventas se descuentan del lote más viejo (FIFO).' },
    { Dibujo: DibujoDecide, titulo: 'Mirás y decidís', texto: `Desde ahí se actualiza solo cada día. Mirás la salud de tu cartera, analizás cada activo, le preguntás a Mervall-E AI y comparás antes de tu próxima compra. Mervall-E AI responde 12 preguntas guiadas (${cupoDe(PLUS_FEATURES, CUPO_CHAT)} consultas por semana en Plus); en Pro, chat libre (${cupoDe(PRO_FEATURES, CUPO_CHAT)} consultas por semana).` },
  ]
  return (
    <section id="como-funciona" className="max-w-[1180px] mx-auto px-4 sm:px-6 pb-16 sm:pb-[88px] scroll-mt-20">
      <Cabecera ceja="Cómo funciona" titulo="Tres pasos y ya estás mirando tu cartera entera." />
      <ol className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {pasos.map(({ Dibujo, titulo, texto }, i) => (
          <li key={titulo} className="border border-line rounded-xl bg-bg-1 p-[18px] flex flex-col gap-3.5">
            <div className="relative h-[150px] rounded-xl bg-bg-2/60 border border-line overflow-hidden" aria-hidden="true"><Dibujo /></div>
            <p className="text-[13px] font-medium text-ink-3">Paso {i + 1}</p>
            <h3 className="text-[19px] font-semibold tracking-tight text-ink-0">{titulo}</h3>
            <p className="text-[14.5px] text-ink-1 leading-relaxed">{texto}</p>
          </li>
        ))}
      </ol>
      <p className="mt-8 text-center text-sm text-ink-2">
        ¿Querés ver cada parte en detalle?{' '}
        <Link to="/guia" className="text-ink-0 underline underline-offset-2 hover:text-data-violet">Mirá la guía completa</Link>
      </p>
    </section>
  )
}

// ─── Precios ─────────────────────────────────────────────────────────────────
// ⚠️ Sin tarjeta de Free, y no es una decisión de diseño: quien se registra NO
// tiene plan gratis. Su puerta de entrada es la prueba de TRIAL_TOTAL_DAYS días
// y al final elige Plus o Pro. (El Free sigue existiendo para los que ya lo
// tenían; lo que no existe es como puerta de entrada.)
// Las listas salen del catálogo (`data/planCatalog.js`): lo que cambia ahí,
// cambia acá.

function PlanCard({ nombre, bajada, precio, nota, items, cta, pro }) {
  return (
    <div className={`relative border rounded-xl bg-bg-1 p-6 ${pro ? 'border-data-violet/55 lp-sombra-pro' : 'border-line-2'}`}>
      {pro && <span className="absolute -top-3 left-6 text-xs font-semibold bg-data-violet text-white px-2.5 py-0.5 rounded-full">Más completo</span>}
      <h3 className="text-xl font-semibold tracking-tight text-ink-0">{nombre}</h3>
      <p className="text-sm text-ink-2 mt-0.5">{bajada}</p>
      <p className="text-[40px] font-semibold tracking-tighter tabular text-ink-0 mt-4">
        ${fmtArs(precio)} <small className="text-sm text-ink-3 font-medium tracking-normal">/ mes</small>
      </p>
      <p className="text-[12.5px] text-ink-3 mb-[18px]">{nota}</p>
      <Link to="/login?mode=register" className={`${pro ? BOTON_1 : BOTON_2} w-full py-3 mb-5`}>{cta}</Link>
      <ul className="grid gap-2.5">
        {items.map(t => <li key={t} className="flex gap-2.5 text-[14.5px] text-ink-1"><Tilde className="mt-[3px]" /><span>{t}</span></li>)}
      </ul>
    </div>
  )
}

function Pricing() {
  return (
    <section id="pricing" className="max-w-[1180px] mx-auto px-4 sm:px-6 pb-16 sm:pb-[88px] scroll-mt-20">
      <Cabecera centro ceja="Precios" titulo={`Probá ${TRIAL_TOTAL_DAYS} días gratis. Después elegís.`}>
        Arrancás con Rendi completo y sin tarjeta: {TRIAL_PRO_DAYS} días con Pro y {TRIAL_PLUS_DAYS} con Plus.
        Pagás en pesos, por mes.
      </Cabecera>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-[18px] max-w-[880px] mx-auto items-start">
        <PlanCard nombre="Plus" bajada="Toda tu cartera y sus métricas" precio={PLUS_PRICE_ARS_MONTHLY}
                  nota={`Después de tus ${TRIAL_TOTAL_DAYS} días gratis`} cta="Probar y elegir Plus"
                  items={PLUS_FEATURES.diff.items} />
        <PlanCard pro nombre="Pro" bajada="Todo lo del Plus, con la IA a fondo" precio={PRO_PRICE_ARS_MONTHLY}
                  nota={`Con el que arrancás tus primeros ${TRIAL_PRO_DAYS} días`} cta="Probar y elegir Pro"
                  items={['Todo lo del Plus', ...PRO_FEATURES.diff.items]} />
      </div>
      <p className="text-center text-sm text-ink-2 mt-6">
        No te pedimos la tarjeta para probar.{' '}
        <Link to="/login?mode=register" className="text-ink-0 hover:text-data-violet">Creá tu cuenta</Link> y arrancá tus {TRIAL_TOTAL_DAYS} días hoy.
      </p>
    </section>
  )
}

// ─── Guías por broker ────────────────────────────────────────────────────────
// Para SEO, no sólo para el visitante: las seis landings de palabras clave
// quedaban huérfanas sin un link desde la portada, que es la página con más
// autoridad del dominio. No sacar sin dejarlas enlazadas en otro lado.

function GuiasPorBroker() {
  const guias = [
    ['/brokers/cocos', 'Cocos Capital'], ['/brokers/iol', 'IOL Inversiones'], ['/brokers/binance', 'Binance y cripto'],
    ['/cedears', 'CEDEARs'], ['/bonos-argentinos', 'Bonos argentinos'], ['/afip-cripto', 'AFIP y cripto'],
  ]
  return (
    <section id="para-tu-broker" className="max-w-[1180px] mx-auto px-4 sm:px-6 pb-4">
      <Ceja>Guías</Ceja>
      <h2 className="text-[clamp(22px,2.6vw,28px)] font-semibold tracking-tight text-ink-0 mb-5">¿Usás un broker en particular?</h2>
      <ul className="flex flex-wrap gap-2">
        {guias.map(([to, t]) => (
          <li key={to}>
            <Link to={to} className="inline-flex items-center gap-1.5 text-sm border border-line-2 rounded-full px-3.5 py-2 bg-bg-1 text-ink-1 hover:text-ink-0 hover:border-data-violet/60 transition-colors">
              {t}<ArrowRight size={13} strokeWidth={2} />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

// ─── Fundador ────────────────────────────────────────────────────────────────
// Prueba social: "¿quién está atrás?" (cara y nombre) y "¿lo usa alguien?"
// (inversores reales, vía /api/stats/public). La foto vive en /founder.jpg; si
// no está, quedan las iniciales.

function FounderBlock() {
  const [users, setUsers] = useState(null)
  // La foto se prueba antes de mostrarla: si /founder.jpg no existe, el
  // fallback de la SPA devuelve index.html con 200, que no decodifica como
  // imagen. `onError` de <img> con un 200-text/html es poco confiable.
  const [photoOk, setPhotoOk] = useState(false)

  useEffect(() => {
    let alive = true
    pedirAlServidor('/stats/public', {}, { freno: false })
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (alive && d && typeof d.users === 'number') setUsers(d.users) })
      .catch(() => {})
    const probe = new Image()
    probe.onload = () => { if (alive && probe.naturalWidth > 0) setPhotoOk(true) }
    probe.onerror = () => {}
    probe.src = '/founder.jpg'
    return () => { alive = false }
  }, [])

  // El contador aparece sólo con una base presentable: "3 inversores" es peor
  // que no decir nada. Por debajo, el mensaje de etapa temprana.
  const SHOW_COUNT_MIN = 25
  const showCount = users != null && users >= SHOW_COUNT_MIN

  return (
    <section className="max-w-[780px] mx-auto px-4 sm:px-6 py-16">
      <div className="flex flex-col sm:flex-row gap-5 sm:gap-6 items-start border border-line rounded-xl bg-bg-1 p-5 sm:p-7">
        {photoOk ? (
          <img src="/founder.jpg" alt="Nicolás Pussetto, fundador de Rendi" loading="lazy"
               className="w-16 h-16 rounded-full object-cover border border-line-2 shrink-0" />
        ) : (
          <div className="w-16 h-16 rounded-full bg-rendi-violet-deep border border-data-violet/35 text-data-violet font-semibold text-xl grid place-items-center shrink-0">NP</div>
        )}
        <div className="min-w-0">
          <blockquote className="text-base text-ink-1 leading-relaxed mb-4">
            “Empecé a invertir hace 5 años y siempre me costó llevar el registro: tenía todo en un Excel que
            se rompía cada dos por tres, era un caos cruzar mis rendimientos en pesos y en dólares, y encima no
            sabía qué estaba haciendo mal. Hice Rendi para que invertir no sea tirar una moneda al aire, sino
            tener la información que necesitás para decidir.”
          </blockquote>
          <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-5">
            <div>
              <p className="text-sm font-semibold text-ink-0">Nicolás Pussetto</p>
              <p className="text-[13px] text-ink-3">Fundador de Rendi</p>
            </div>
            <p className="text-xs text-ink-2 sm:ml-auto">
              {showCount ? (
                <><span className="text-ink-0 font-semibold tabular">{users.toLocaleString('es-AR')}</span> inversores ya consolidan su cartera en Rendi</>
              ) : 'En etapa temprana: sumate a los primeros.'}
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}

// ─── Cierre ──────────────────────────────────────────────────────────────────

function CtaFinal() {
  return (
    <section className="max-w-[1180px] mx-auto px-4 sm:px-6">
      <div data-cierre="" className="relative overflow-hidden text-center border border-line-2 rounded-xl px-5 py-14 bg-bg-1">
        <div className="relative">
          <h2 className="text-[clamp(28px,4vw,44px)] font-semibold tracking-tight text-ink-0 mb-3">Tu cartera entera, en una pantalla.</h2>
          <p className="text-ink-1 mb-6">{TRIAL_TOTAL_DAYS} días gratis, sin tarjeta. En cinco minutos ya la estás mirando.</p>
          <div className="flex flex-wrap gap-2.5 justify-center">
            <Link to="/login?mode=register" className={`${BOTON_1} px-5 py-3`}>{CTA_PRUEBA}<ArrowRight size={16} strokeWidth={2.2} /></Link>
            <button type="button" onClick={abrirDemo} className={`${BOTON_2} px-5 py-3`}>Ver demo sin registrarme</button>
          </div>
        </div>
      </div>
    </section>
  )
}

// ─── Botón fijo abajo (celular) ──────────────────────────────────────────────
// Desde un anuncio casi todos entran por el celular: el registro queda a un
// toque en toda la página. Aparece cuando ya no se ven los botones del héroe y
// se esconde en el cierre, que tiene los suyos. El de WhatsApp flota encima
// (FLOTANTES_DESDE_ABAJO), no se pisan.

function BarraCtaCelular() {
  const [ve, setVe] = useState(false)
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return undefined
    const heroe = document.querySelector('[data-ctas-heroe]'), cierre = document.querySelector('[data-cierre]')
    if (!heroe || !cierre) return undefined
    const visto = { heroe: true, cierre: false }
    const ojo = new IntersectionObserver((es) => {
      for (const e of es) visto[e.target === heroe ? 'heroe' : 'cierre'] = e.isIntersecting
      setVe(!visto.heroe && !visto.cierre)
    })
    ojo.observe(heroe); ojo.observe(cierre)
    return () => ojo.disconnect()
  }, [])
  return (
    <div aria-hidden={!ve}
         className={`md:hidden fixed inset-x-0 bottom-0 z-30 flex gap-2 px-4 pt-2.5 pb-[calc(10px+env(safe-area-inset-bottom,0px))] bg-bg-0/90 backdrop-blur-md border-t border-line-2 transition-transform duration-300 ${ve ? 'translate-y-0' : 'translate-y-[110%]'}`}>
      <Link to="/login?mode=register" tabIndex={ve ? 0 : -1} className={`${BOTON_1} flex-1 py-3 text-[14.5px]`}>{CTA_PRUEBA}</Link>
      <button type="button" tabIndex={ve ? 0 : -1} onClick={abrirDemo} className={`${BOTON_2} px-3.5 py-3 text-[14.5px]`}>Ver demo</button>
    </div>
  )
}

// ─── Pie ─────────────────────────────────────────────────────────────────────

const SUPPORT_EMAIL = 'hola@rendi.finance'

const SOCIAL_LINKS = {
  instagram: 'https://www.instagram.com/rendifinance/',
  // LinkedIn: perfil del fundador (build-in-public). X se quitó: la cuenta
  // oficial todavía no existe y un ícono a una cuenta inexistente resta
  // confianza. Re-agregar cuando esté creada.
  linkedin: 'https://www.linkedin.com/in/nicolas-pussetto-6a656a1a8/',
}

function Footer() {
  const year = new Date().getFullYear()
  const titulo = 'text-[13px] font-semibold text-ink-2 mb-3'
  const link = 'text-ink-1 hover:text-ink-0 transition-colors'
  return (
    <footer className="border-t border-line/70 mt-16" style={{ '--espacio-abajo': `${ESPACIO_ABAJO_CELULAR}px` }}>
      <div className="max-w-[1180px] mx-auto px-4 sm:px-6 pt-12 pb-[var(--espacio-abajo)] md:pb-12">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-8 md:gap-10 mb-10">
          <div className="md:col-span-4">
            <div className="flex items-center gap-2.5 mb-3">
              <RendiLogo size={32} />
              <span className="text-base font-semibold text-ink-1">rendi</span>
            </div>
            <p className="text-[13px] text-ink-2 leading-relaxed max-w-xs">
              Todas tus inversiones en un solo lugar: cartera multi-broker, ganancia real en dólares, salud de
              cartera, análisis técnico y fundamental, y Mervall-E AI.
            </p>
            <p className="text-[13px] text-ink-2 leading-relaxed mt-3">
              Hecho en Argentina por{' '}
              <a href={SOCIAL_LINKS.linkedin} target="_blank" rel="noreferrer noopener" className="text-ink-1 hover:text-data-violet underline underline-offset-2 transition-colors">Nicolás Pussetto</a>,
              inversor argentino.
            </p>
          </div>
          <div className="md:col-span-2">
            <h3 className={titulo}>Producto</h3>
            <ul className="space-y-2 text-sm">
              <li><Link to="/planes" className={link}>Planes y precios</Link></li>
              <li><a href="#como-funciona" className={link}>Cómo funciona</a></li>
              <li><Link to="/guia" className={link}>Guía completa</Link></li>
              <li><a href="#faq" className={link}>Preguntas frecuentes</a></li>
              <li><Link to="/blog" className={link}>Blog</Link></li>
            </ul>
          </div>
          <div className="md:col-span-2">
            <h3 className={titulo}>Cuenta</h3>
            <ul className="space-y-2 text-sm">
              <li><Link to="/login?mode=register" className={link}>{CTA_PRUEBA}</Link></li>
              <li><Link to="/login" className={link}>Iniciar sesión</Link></li>
              <li><button type="button" onClick={abrirDemo} className={`${link} text-left`}>Probar demo</button></li>
            </ul>
          </div>
          <div className="md:col-span-2">
            <h3 className={titulo}>Legal</h3>
            <ul className="space-y-2 text-sm">
              <li><Link to="/terminos" className={link}>Términos y condiciones</Link></li>
              <li><Link to="/reembolso" className={link}>Política de reembolso</Link></li>
              <li><Link to="/privacidad" className={link}>Privacidad</Link></li>
            </ul>
          </div>
          <div className="md:col-span-2">
            <h3 className={titulo}>Contacto</h3>
            <ul className="space-y-2 text-sm">
              <li>
                <a href={`mailto:${SUPPORT_EMAIL}`} className={`inline-flex items-center gap-2 ${link}`} title="Escribinos por mail">
                  <Mail size={13} strokeWidth={1.75} /><span className="text-xs">{SUPPORT_EMAIL}</span>
                </a>
              </li>
              <li>
                <a href={whatsappUrl()} target="_blank" rel="noreferrer noopener" title="WhatsApp"
                   className="inline-flex items-center gap-2 text-ink-1 hover:text-[rgb(var(--whatsapp))] transition-colors">
                  <WhatsAppIcon size={13} /><span className="text-xs">WhatsApp</span>
                </a>
              </li>
            </ul>
            <div className="flex items-center gap-3 mt-4">
              <a href={SOCIAL_LINKS.instagram} target="_blank" rel="noreferrer noopener" className="text-ink-3 hover:text-ink-0 transition-colors" title="Rendi en Instagram" aria-label="Instagram">
                <Instagram size={16} strokeWidth={1.75} />
              </a>
              <a href={SOCIAL_LINKS.linkedin} target="_blank" rel="noreferrer noopener" className="text-ink-3 hover:text-ink-0 transition-colors" title="Nicolás Pussetto (fundador de Rendi) en LinkedIn" aria-label="LinkedIn">
                <Linkedin size={16} strokeWidth={1.75} />
              </a>
            </div>
          </div>
        </div>
        <div className="pt-6 border-t border-line/70 flex items-center justify-between flex-wrap gap-3 text-[13px] text-ink-3">
          <span>© {year} Rendi · rendi.finance</span>
          <span>Hecho en Argentina</span>
        </div>
      </div>
    </footer>
  )
}

// ─── Raíz ────────────────────────────────────────────────────────────────────

export default function Landing() {
  useEffect(() => {
    document.documentElement.style.scrollBehavior = 'smooth'
    return () => { document.documentElement.style.scrollBehavior = '' }
  }, [])

  return (
    <div className="min-h-screen bg-bg-0 text-ink-0 overflow-x-hidden">
      {/* El canonical del home vive acá y NO en index.html: si estuviera en los
          dos lados, cada ruta de la SPA quedaría con DOS <link rel="canonical">
          (el fijo del home + el de su PageMeta) y Google los ignora a todos.
          Va SOLO `canonical`: el título y la descripción de index.html están
          escritos más cortos a mano para que entren en el preview. */}
      <PageMeta canonical="/" />
      <NavBar />
      <main>
        <Hero />
        <CintaBrokers />
        <SeccionVideo />
        <SeccionModulos />
        <AntesConRendi />
        <ComoFunciona />
        <Pricing />
        <GuiasPorBroker />
        <FAQ />
        <FounderBlock />
        <CtaFinal />
      </main>
      <Footer />
      <BarraCtaCelular />
      <SupportWhatsAppFab />
    </div>
  )
}
