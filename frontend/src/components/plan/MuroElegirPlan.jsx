// MuroElegirPlan — la pantalla del día 21 para el que nació sin plan gratis.
// ════════════════════════════════════════════════════════════════════════════
// Se terminó su prueba de 20 días y no eligió un plan, así que la cuenta queda
// EN PAUSA. Esta pantalla es la única salida: elegir un plan, o cerrar sesión.
//
// Tres decisiones de diseño que son la pantalla, no adorno:
//
//   1. NO tiene botón de cerrar, y no se cierra con Escape ni clickeando
//      afuera. Un muro que se puede esquivar se esquiva, y el backend igual
//      va a contestar 402 en todo lo de atrás: dejarlo cerrar sólo produce
//      una app llena de errores rojos sin explicación.
//   2. La app se ve DESENFOCADA detrás. Lo que más espanta no es el precio,
//      es el miedo a haber perdido lo cargado; mostrar la cartera atrás dice
//      "está todo acá" mejor que cualquier frase.
//   3. Pro va marcado como "el que usaste los primeros 10 días" y en celular
//      va ARRIBA de Plus: le estamos pidiendo que elija justo lo que probó.
//
// El muro REAL lo aplica el backend (402 `plan_requerido` en cualquier
// endpoint de datos, desde `get_effective_user`). Esto es la cara visible.
import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { track } from '../../utils/track'
import {
  fmtArs, annualSavingsArs, ANNUAL_DISCOUNT_BADGE_PCT,
  PLUS_PRICE_ARS_MONTHLY, PRO_PRICE_ARS_MONTHLY,
  PLUS_PRICE_ARS_ANNUAL, PRO_PRICE_ARS_ANNUAL,
  PLUS_PRICE_ARS_ANNUAL_MONTHLY_EQ, PRO_PRICE_ARS_ANNUAL_MONTHLY_EQ,
} from '../../data/pricing'
import { PLUS_FEATURES, PRO_FEATURES } from '../../data/planCatalog'

// ⚠️ LAS FEATURES NO SE ESCRIBEN ACÁ. Salen de `data/planCatalog.js`, que es la
// fuente única del producto y la que lee la página de planes.
//
// Esta pantalla las tuvo escritas a mano y prometía CUATRO cosas falsas, en la
// pantalla donde se le pide la plata:
//   · "Brokers ilimitados" en Plus, cuando Plus tiene tope 3 (ilimitado es Pro);
//   · "20 análisis por semana" en Plus, cuando son 6;
//   · "sin límite de análisis" en Pro, cuando son 60 por semana;
//   · "calendario de cobros" y "carpeta de impuestos", que son ROADMAP del
//     catálogo (`Tax helper AFIP`) y el propio catálogo avisa que NUNCA van
//     mezcladas con las features activas.
// Nada de eso produce un error: se cobra y después el producto no cumple.
//
// Se usa `diff.items` —el "vs el plan anterior", que es la pregunta del muro—
// más `quotas`, que trae los números reales. El roadmap queda afuera siempre.
const PLANES = {
  plus: {
    nombre: 'Plus',
    bajada: 'Hasta 3 brokers y métricas de riesgo',
    mensual: PLUS_PRICE_ARS_MONTHLY,
    anualEq: PLUS_PRICE_ARS_ANNUAL_MONTHLY_EQ,
    anualTotal: PLUS_PRICE_ARS_ANNUAL,
    catalogo: PLUS_FEATURES,
  },
  pro: {
    nombre: 'Pro',
    bajada: 'Chat libre y brokers ilimitados',
    mensual: PRO_PRICE_ARS_MONTHLY,
    anualEq: PRO_PRICE_ARS_ANNUAL_MONTHLY_EQ,
    anualTotal: PRO_PRICE_ARS_ANNUAL,
    catalogo: PRO_FEATURES,
  },
}

// Cuántas líneas del "vs el plan anterior" entran en la tarjeta del muro. El
// muro es una decisión, no la comparativa completa: para eso está /planes.
const LINEAS_POR_TARJETA = 4

/** Los elementos que hay que apagar para que el muro sea de verdad modal:
 *  los HERMANOS del muro dentro de su padre. Exportada para poder probarla sin
 *  un navegador (los tests de este repo corren en 'node', sin DOM).
 *
 *  Devuelve [] si no hay nodo o no tiene padre — nunca revienta. */
export function hermanosDe(nodo) {
  const padre = nodo?.parentElement
  if (!padre) return []
  return Array.from(padre.children).filter(el => el !== nodo)
}

function TarjetaPlan({ plan, anual, destacado, onElegir }) {
  const p = PLANES[plan]
  const precio = anual ? p.anualEq : p.mensual
  return (
    <div className={`relative flex flex-col rounded-xl border p-6 bg-bg-1 ${
      destacado ? 'border-data-violet' : 'border-line'}`}>
      {destacado && (
        <div className="absolute -top-2.5 left-6 rounded px-2 py-0.5 bg-data-violet
                        text-[11px] font-bold text-bg-0">
          El que usaste los primeros 10 días
        </div>
      )}
      <div className="text-[15px] font-semibold text-ink-0">{p.nombre}</div>
      <div className="mt-1 text-[12.5px] text-ink-3">{p.bajada}</div>

      <div className="mt-4 flex items-baseline gap-1.5">
        <span className="text-[34px] font-semibold tracking-tight tabular text-ink-0">
          ${fmtArs(precio)}
        </span>
        <span className="text-[13px] text-ink-2">por mes</span>
      </div>
      <div className="mt-1 min-h-[17px] text-[12px] text-ink-3">
        {anual
          ? `Facturado anual ($${fmtArs(p.anualTotal)}) · ahorrás $${fmtArs(annualSavingsArs(plan))}`
          : ''}
      </div>

      <div className="my-5 h-px bg-line" />

      <div className="flex flex-grow flex-col gap-2.5">
        {(p.catalogo.diff?.items || []).slice(0, LINEAS_POR_TARJETA).map(f => (
          <div key={f} className="text-[13px] text-ink-2">{f}</div>
        ))}
      </div>

      {/* Los cupos, con los números del catálogo. Van aparte de la lista porque
          son lo que más se mira y lo que más caro sale prometer mal. */}
      <div className="mt-4 grid grid-cols-3 gap-2 border-t border-line pt-3">
        {(p.catalogo.quotas || []).map(q => (
          <div key={q.label}>
            <div className="text-[15px] font-semibold tabular text-ink-0">{q.value}</div>
            <div className="text-[10.5px] leading-tight text-ink-3">{q.label}</div>
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={() => onElegir(plan)}
        className={`mt-5 flex min-h-[44px] items-center justify-center rounded-lg
                    text-sm font-semibold transition-colors ${
          destacado
            ? 'bg-data-violet text-bg-0 hover:bg-rendi-violet-hover'
            : 'border border-line-2 bg-bg-2 text-ink-0 hover:bg-bg-3'}`}
      >
        Elegir {p.nombre}
      </button>
    </div>
  )
}

export default function MuroElegirPlan({ anual, onCambiarPeriodo, resumen }) {
  const navigate = useNavigate()
  const { logout } = useAuth()
  const caja = useRef(null)

  useEffect(() => { track('paywall_muro_visto') }, [])

  // El muro declara `aria-modal` y tiene que cumplirlo. Se monta como hermano
  // de <Layout/>, así que todo lo de atrás sigue en el orden de tabulación:
  // sin esto, con Tab se llega al sidebar y a los botones de la cartera
  // desenfocada, se los activa, y cada uno responde con un 402. No es un
  // agujero de seguridad —el backend corta igual— pero es una pantalla que
  // dice ser modal y no lo es.
  //
  // `inert` sobre el resto de la app es la forma corta y la soportan todos los
  // navegadores actuales; el ciclado del foco de abajo es el respaldo para los
  // que no, y además es lo que hace que Tab dé la vuelta adentro del muro.
  //
  // ⚠️ Los hermanos se buscan desde el PADRE DEL MURO, no desde `#root`. La
  // primera versión filtraba los hijos de `#root`, y `#root` tiene UN solo hijo
  // —el <div> que envuelve toda la app— que CONTIENE al muro: el filtro lo
  // descartaba y la lista quedaba vacía, así que `inert` no se aplicaba a nada.
  // Un no-op silencioso, con un comentario arriba diciendo que funcionaba.
  useEffect(() => {
    // ⚠️ Se re-aplica ante cada cambio del DOM, no una sola vez al montar. La
    // primera versión apagaba los hermanos QUE EXISTÍAN en ese instante, y
    // medido en el navegador apagó 2 de 5: el sidebar (<aside>) y el
    // acompañante se montan DESPUÉS, así que quedaban vivos y tabulables —
    // justo lo que este efecto existe para evitar.
    const apagar = () => {
      hermanosDe(caja.current).forEach(el => {
        if (el.inert) return
        el.inert = true
        el.setAttribute('aria-hidden', 'true')
      })
    }
    apagar()
    const padre = caja.current?.parentElement
    const observador = padre
      ? new MutationObserver(apagar)
      : null
    observador?.observe(padre, { childList: true })

    const foco = () => caja.current?.querySelectorAll(
      'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])')
    foco()?.[0]?.focus()

    const alTabular = (e) => {
      if (e.key !== 'Tab') return
      const items = foco()
      if (!items?.length) return
      const primero = items[0]
      const ultimo = items[items.length - 1]
      if (e.shiftKey && document.activeElement === primero) {
        e.preventDefault(); ultimo.focus()
      } else if (!e.shiftKey && document.activeElement === ultimo) {
        e.preventDefault(); primero.focus()
      }
    }
    document.addEventListener('keydown', alTabular)
    return () => {
      observador?.disconnect()
      document.removeEventListener('keydown', alTabular)
      hermanosDe(caja.current).forEach(el => {
        el.inert = false
        el.removeAttribute('aria-hidden')
      })
    }
  }, [])

  const elegir = (plan) => {
    track('paywall_muro_elegir', { plan, period: anual ? 'annual' : 'monthly' })
    navigate(`/planes?plan=${plan}&period=${anual ? 'annual' : 'monthly'}`)
  }

  return (
    // role="dialog" + aria-modal: para un lector de pantalla esto ES la
    // pantalla, no una capa encima de otra cosa navegable.
    <div
      ref={caja}
      role="dialog"
      aria-modal="true"
      aria-labelledby="muro-titulo"
      className="fixed inset-0 z-[100] overflow-y-auto bg-bg-0/[0.92]"
    >
      {/* ⚠️ El scroll va en el contenedor de AFUERA y el centrado en un envoltorio
          con `min-h-full` ADENTRO. Centrar con `items-center` en el mismo
          elemento que scrollea es el bug clásico de flex: cuando la caja es más
          alta que la ventana, el excedente se reparte para los dos lados y la
          parte de ARRIBA queda fuera del alcance del scroll. Medido en una
          ventana de 720 px: la caja mide 926, su borde superior quedaba en
          −106 px y el contenedor creía medir 860 — el título y el cartel
          "Terminaron tus 20 días" eran INALCANZABLES. Una notebook de 768 px
          entra justo en ese caso. */}
      <div className="flex min-h-full items-center justify-center p-4 sm:p-10">
      <div className="w-full max-w-[880px] rounded-xl border border-line bg-bg-1
                      p-6 sm:p-10">
        <div className="text-center">
          <div className="mb-4 inline-flex items-center rounded-full bg-data-violet/[0.12]
                          px-3 py-1.5">
            <span className="text-[11.5px] font-semibold uppercase tracking-wide
                             text-data-violet">
              Terminaron tus 20 días
            </span>
          </div>
          <h1 id="muro-titulo"
              className="mb-2.5 text-[25px] font-semibold leading-tight tracking-tight
                         text-ink-0 sm:text-[32px]">
            Elegí un plan para seguir<br className="hidden sm:inline" />
            {' '}organizando tus inversiones
          </h1>
          {/* El resumen es SUYO: "4 brokers y 312 movimientos" convence de que
              no se perdió nada mucho más que la palabra "guardado". Si no lo
              tenemos, se omite antes que decir un número inventado. */}
          <p className="mx-auto max-w-[520px] text-[14px] leading-relaxed text-ink-2">
            {resumen
              ? <>Tus <b className="text-ink-0">{resumen}</b> quedaron guardados.
                  Elegí un plan y seguís donde estabas.</>
              : <>Todo lo que cargaste quedó guardado. Elegí un plan y seguís
                  donde estabas.</>}
          </p>
        </div>

        <div className="my-6 flex justify-center">
          <div className="inline-flex rounded-lg border border-line bg-bg-2 p-[3px]">
            <button type="button" onClick={() => onCambiarPeriodo(false)}
              className={`inline-flex min-h-[38px] items-center rounded px-4
                          text-[13px] transition-colors ${
                anual ? 'font-medium text-ink-2' : 'bg-bg-3 font-semibold text-ink-0'}`}>
              Mensual
            </button>
            <button type="button" onClick={() => onCambiarPeriodo(true)}
              className={`inline-flex min-h-[38px] items-center gap-1.5 rounded px-4
                          text-[13px] transition-colors ${
                anual ? 'bg-bg-3 font-semibold text-ink-0' : 'font-medium text-ink-2'}`}>
              Anual
              <span className="rounded bg-rendi-pos/15 px-1.5 py-px text-[11.5px]
                               font-semibold text-rendi-pos">
                −{ANNUAL_DISCOUNT_BADGE_PCT}%
              </span>
            </button>
          </div>
        </div>

        {/* En celular Pro va PRIMERO (order) — es el que probó. */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="order-2 sm:order-1">
            <TarjetaPlan plan="plus" anual={anual} onElegir={elegir} />
          </div>
          <div className="order-1 sm:order-2">
            <TarjetaPlan plan="pro" anual={anual} destacado onElegir={elegir} />
          </div>
        </div>

        <div className="mt-6 flex flex-col items-start justify-between gap-4
                        border-t border-line pt-5 sm:flex-row sm:items-center">
          <p className="max-w-[520px] text-[12px] leading-relaxed text-ink-3">
            Se cobra en pesos con tarjeta. Cancelás cuando quieras desde
            Configuración y no se vuelve a cobrar. Si no elegís ahora, tus datos
            quedan guardados — volvés cuando quieras.
          </p>
          <button
            type="button"
            onClick={logout}
            className="min-h-[44px] shrink-0 text-[12.5px] text-ink-3 underline
                       decoration-dotted underline-offset-2 hover:text-ink-2"
          >
            Salir de mi cuenta
          </button>
        </div>
      </div>
      </div>
    </div>
  )
}
