// More — "Más" drawer en mobile (Sprint M1, item 11 anticipado).
// ═══════════════════════════════════════════════════════════════════════════
// Aloja todas las rutas secundarias que no entran en las 4 tabs visibles.
// En mobile es una página real (/mas). En desktop esta ruta no se usa
// porque la sidebar muestra todo directamente.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ChevronRight, LogOut, Bell, BellRing, BellOff, Send, MessageCircle,
  Sun, Moon, Smartphone,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'
import RecommendationsModal from '../components/RecommendationsModal'
import InstalarAppModal, { precargarFotosDeInstalar } from '../components/InstalarAppModal'
import AvisoNotificaciones from '../components/AvisoNotificaciones'
import { MENSAJE_FALLA } from '../utils/notificaciones'
import { yaInstalada } from '../utils/instalarApp'
import { useToast } from '../components/Toast'
import { usePushNotifications } from '../hooks/usePushNotifications'
import { useCoachDrawer } from '../contexts/CoachDrawerContext'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import { useAlertsContext } from '../contexts/AlertsContext'
import { menuVisible, pantallasVisibles, ASESOR_PROPIO, GROUPS, nombreDelCliente } from '../utils/navegacion'
import Panel from '../components/Panel'
import MervallE from '../components/ai/MervallE'

// QUÉ pantallas se ven NO se decide acá: sale de utils/navegacion.js, la misma
// lista y la misma regla del asesor que usan el menú lateral de la compu y el
// buscador ⌘K. Este archivo tenía su propia copia y se desvió: el asesor tenía
// "Cobros" en la compu y en el celular no (ningún otro enlace del celular
// llevaba ahí).
//
// Las secciones son los grupos del menú de la compu (con el nombre del
// celular). Lo de abajo es sólo CÓMO se presenta cada pantalla acá: el orden,
// el renglón de ayuda y, si acá se llama distinto, su nombre. Una pantalla de
// la lista compartida que acá no tenga renglón aparece igual (en su grupo, con
// su nombre y sin ayuda): nunca desaparece del celular por falta de una línea
// en este archivo.
const PLAN_ASESOR = 'Plan Asesor'
const TU_PORTFOLIO = 'Tu portfolio'
// Grupo de la compu → sección del celular, cuando se llaman distinto (por el id
// del grupo: su nombre cambia adentro de un cliente). Lo que en la compu va
// suelto (Alertas) acá va con la cartera. Importar no está acá: vive adentro
// del "+" de la barra de abajo, como adentro de Registrar en la compu
// (`enRegistrar` en utils/navegacion.js).
const SECCION_DE_GRUPO = { cartera: TU_PORTFOLIO }
// El orden de las secciones es el de los grupos de la compu (GROUPS). Estaba
// escrito a mano acá: al reordenar el menú lateral, el celular se quedaba con
// el orden viejo sin que nada avisara.
const SECCIONES = [PLAN_ASESOR, ...GROUPS.map(g => SECCION_DE_GRUPO[g.id] || g.label)]

// Los renglones de ayuda no dicen "tu"/"tus": el asesor adentro de un cliente
// está mirando la cartera de OTRO.
const EN_EL_CELULAR = {
  '/dashboard':       { sub: 'Evolución, distribución y de dónde sale la ganancia' },
  '/posiciones':      { sub: 'Tenencias, brokers y objetivos' },
  '/operaciones':     { sub: 'Compras, ventas, depósitos y dividendos' },
  '/alertas':         { sub: 'Resumen diario del mercado y avisos de precio' },
  // En el celular "/" es la pestaña Inicio (arriba el saldo, abajo el
  // mercado): se llama igual acá. En la compu es "Resumen", otra pantalla.
  '/':                { label: 'Inicio', sub: 'Saldo del día, mapa del mercado y noticias' },
  '/novedades':       { sub: 'Noticias y eventos de los activos' },
  '/analisis':        { sub: 'Diagnóstico, comportamiento, reportes' },
  '/fundamentals':    { sub: 'Calidad de las tenencias + buscador de empresas' },
  '/perfil-inversor': { sub: 'Perfil declarado vs. la cartera real' },
}

// El asesor en SU nivel (sin haber entrado a un cliente): todo va en "Plan
// Asesor" y la ayuda habla de sus clientes — Dashboard acá es el del libro,
// no el de una cartera. Adentro de un cliente queda en "Plan Asesor" sólo lo
// que no es de la cartera de ese cliente (hoy, "Clientes", para volver).
const DEL_ASESOR = {
  '/dashboard':            { sub: 'Total administrado, quién necesita atención y qué activos mandan' },
  '/clientes':             { sub: 'Tus clientes y el resumen de sus carteras' },
  '/novedades':            { sub: 'Eventos y noticias de los activos de tus clientes' },
  '/cobros':               { sub: 'Cupones y amortizaciones de los bonos de tus clientes' },
  '/alertas':              { sub: 'Brief del libro y movimientos de tus clientes' },
  '/importar-historiales': { sub: 'Cargá los archivos de varios clientes en una sola tanda' },
}
const ES_DEL_ASESOR = new Set(ASESOR_PROPIO.map(i => i.to))

// El pie del menú de la compu (`utilidades`: Admin, Guía, Configuración). En
// el celular Admin va en su propia sección y las otras dos en "Cuenta", junto
// a los botones que no son pantallas (Recomendaciones, tema, cerrar sesión).
const DEL_PIE = {
  '/config': { sub: 'Cuenta, plan, tipos de cambio y soporte' },
  '/guia':   { sub: 'Cómo se usa Rendi, paso a paso' },
  '/admin':  { sub: 'Panel administrativo' },
}

// Lugar de una pantalla en el orden del celular; las que no figuran, al final.
const posicion = (presentacion, to) =>
  to in presentacion ? Object.keys(presentacion).indexOf(to) : Infinity

// Reparte en secciones las pantallas que este usuario ve en la compu
// (`pantallasVisibles`, sin el pie). `cliente`: el nombre del cliente cuya
// cartera mira el asesor — la sección deja de llamarse "Tu portfolio".
// Exportada para las pruebas.
export function seccionesDelMenuMas(pantallas, { atOwnLevel = false, cliente = null } = {}) {
  const secciones = new Map(SECCIONES.map(s => [s, []]))
  for (const p of pantallas) {
    // En la compu, lo del asesor no tiene grupo (va arriba, suelto); lo que
    // tiene grupo es de la cartera, aunque la misma ruta esté en su lista.
    const delAsesor = atOwnLevel || (!p.grupo && ES_DEL_ASESOR.has(p.to))
    const presentacion = delAsesor ? DEL_ASESOR : EN_EL_CELULAR
    const extra = presentacion[p.to] || {}
    const seccion = delAsesor ? PLAN_ASESOR
      : p.grupo ? (SECCION_DE_GRUPO[p.grupoId] || p.grupo)
      : TU_PORTFOLIO
    if (!secciones.has(seccion)) secciones.set(seccion, [])
    secciones.get(seccion).push({
      to: p.to, icon: p.icon, label: extra.label || p.label, sub: extra.sub,
      orden: posicion(presentacion, p.to),
    })
  }
  return [...secciones]
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({
      label: label === TU_PORTFOLIO && cliente ? `Cartera de ${cliente}` : label,
      items: items.sort((a, b) => a.orden - b.orden),
    }))
}

// El renglón de ayuda de Mervall-E AI: sobre qué trabaja la IA en cada caso.
function ayudaDeRendiAI({ atOwnLevel, clientCtx }) {
  if (atOwnLevel) return 'Asistente con contexto de tu libro de clientes'
  if (clientCtx) return `Asistente con contexto de la cartera de ${nombreDelCliente(clientCtx)}`
  return 'Asistente con contexto de tu portfolio'
}

export default function More() {
  const { user, logout } = useAuth()
  const { dark, toggle } = useTheme()
  const coachDrawer = useCoachDrawer()
  const { clientCtx } = useAdvisorContext()
  const [recomOpen, setRecomOpen] = useState(false)
  const [instalarOpen, setInstalarOpen] = useState(false)
  // Quien ya abre Rendi desde el ícono de su pantalla de inicio no necesita
  // que le ofrezcan instalarla.
  const [instalada] = useState(() => yaInstalada())
  // En el celular no hay «pasar el mouse por encima»: las fotos del cartel se
  // piden al entrar a esta pantalla, para que estén cuando toque la tarjeta.
  useEffect(() => { if (!instalada) precargarFotosDeInstalar() }, [instalada])

  const { unseenCount = 0 } = useAlertsContext()  // el puntito de alertas sin ver
  const { atOwnLevel, isAdvisor, utilidades } = menuVisible({ user, clientCtx })
  const delPie = new Set(utilidades.map(u => u.to))
  const conAyuda = (u) => ({ ...u, sub: DEL_PIE[u.to]?.sub })
  const admin = utilidades.filter(u => u.soloAdmin).map(conAyuda)
  const deCuenta = utilidades.filter(u => !u.soloAdmin).map(conAyuda)
    .sort((a, b) => posicion(DEL_PIE, a.to) - posicion(DEL_PIE, b.to))
  const allGroups = [
    ...seccionesDelMenuMas(
      pantallasVisibles({ user, clientCtx }).filter(p => !delPie.has(p.to) && !p.enRegistrar),
      { atOwnLevel, cliente: nombreDelCliente(clientCtx) }),
    ...(admin.length > 0 ? [{ label: 'Admin', items: admin }] : []),
  ]

  return (
    <div className="page-shell space-y-5">
      <PageHeader
        eyebrow="Menú"
        title="Más"
        subtitle="Todas las secciones de Rendi."
      />

      {/* Descargar app — el paso a paso para dejar Rendi en la pantalla de
          inicio. Va primero porque es lo único de esta lista que se hace una
          sola vez; desaparece cuando ya está instalada. */}
      {!instalada && (
        <section>
          <Panel padding="none" className="overflow-hidden">
            <button
              type="button"
              onClick={() => setInstalarOpen(true)}
              className="w-full flex items-center gap-3 px-4 py-3 hover:bg-bg-2/60 active:bg-bg-3 transition-colors text-left"
            >
              <Smartphone size={18} strokeWidth={1.75} className="text-data-violet flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-ink-0 leading-tight">Descargar app</div>
                <div className="text-[11px] text-ink-3 leading-tight mt-0.5">Poné Rendi en tu pantalla de inicio, en 4 pasos</div>
              </div>
              <ChevronRight size={14} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" />
            </button>
          </Panel>
        </section>
      )}

      {/* Asistente — Mervall-E AI abre el drawer global, no navega a una ruta */}
      <section>
        <h2 className="text-[12.5px] text-ink-2 mb-2 px-1 font-medium">
          Asistente
        </h2>
        <Panel padding="none" className="!border-data-violet/30 overflow-hidden">
          <button
            type="button"
            onClick={() => coachDrawer.open()}
            className="w-full flex items-center gap-3 px-4 py-3 hover:bg-data-violet/[0.04] active:bg-data-violet/[0.08] transition-colors text-left"
          >
            <MervallE size={30} forma="head" quieto />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-ink-0 leading-tight">Mervall-E AI</div>
              <div className="text-[11px] text-ink-3 leading-tight mt-0.5">{ayudaDeRendiAI({ atOwnLevel, clientCtx })}</div>
            </div>
            <ChevronRight size={14} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" />
          </button>
        </Panel>
      </section>

      {allGroups.map((group) => (
        <section key={group.label}>
          <h2 className="text-[12.5px] text-ink-2 mb-2 px-1 font-medium">
            {group.label}
          </h2>
          <Panel padding="none" className="overflow-hidden">
            {group.items.map((item, i) => {
              const Icon = item.icon
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={`flex items-center gap-3 px-4 py-3 hover:bg-bg-2/60 active:bg-bg-3 transition-colors ${
                    i > 0 ? 'border-t border-line/40' : ''
                  }`}
                >
                  <Icon size={16} strokeWidth={1.75} className="text-ink-2 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-ink-0 leading-tight flex items-center gap-2">
                      {item.label}
                      {/* Lo mismo que el menú de la compu: el puntito sólo si
                          hay alertas SIN VER (al entrar a /alertas se apaga). */}
                      {item.to === '/alertas' && unseenCount > 0 && (
                        <span title="Tenés alertas sin ver" className="w-2 h-2 rounded-full bg-data-violet"
                          style={{ boxShadow: '0 0 0 3px rgb(var(--data-violet) / 0.12)' }} />
                      )}
                    </div>
                    {item.sub && (
                      <div className="text-[11px] text-ink-3 leading-tight mt-0.5">{item.sub}</div>
                    )}
                  </div>
                  <ChevronRight size={14} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" />
                </Link>
              )
            })}
          </Panel>
        </section>
      ))}

      {/* Notificaciones push */}
      <PushNotificationsSection esAsesor={isAdvisor} />

      {/* Configuración + logout */}
      <section>
        <h2 className="text-[12.5px] text-ink-2 mb-2 px-1 font-medium">
          Cuenta
        </h2>
        <Panel padding="none" className="overflow-hidden">
          {/* Configuración y Guía salen del pie del menú de la compu: antes
              Configuración estaba escrita a mano acá y la Guía no estaba (en el
              celular ningún enlace llevaba a ella). */}
          {deCuenta.map(({ to, label, icon: Icon, sub }, i) => (
            <Link
              key={to}
              to={to}
              className={`flex items-center gap-3 px-4 py-3 hover:bg-bg-2/60 active:bg-bg-3 transition-colors ${
                i > 0 ? 'border-t border-line/40' : ''
              }`}
            >
              <Icon size={16} strokeWidth={1.75} className="text-ink-2 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-ink-0 leading-tight">{label}</div>
                {sub && <div className="text-[11px] text-ink-3 leading-tight mt-0.5">{sub}</div>}
              </div>
              <ChevronRight size={14} strokeWidth={1.75} className="text-ink-3" />
            </Link>
          ))}
          <button
            type="button"
            onClick={() => setRecomOpen(true)}
            className="w-full flex items-center gap-3 px-4 py-3 border-t border-line/40 hover:bg-data-violet/[0.04] active:bg-data-violet/[0.08] transition-colors text-left"
          >
            <MessageCircle size={16} strokeWidth={1.75} className="text-data-violet flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-ink-0 leading-tight">Recomendaciones</div>
              <div className="text-[11px] text-ink-3 leading-tight mt-0.5">Mandanos ideas, bugs o feedback</div>
            </div>
            <ChevronRight size={14} strokeWidth={1.75} className="text-ink-3" />
          </button>
          {/* El interruptor de tema vivía SÓLO en el menú lateral, que en celular
              no existe: desde el teléfono el modo claro era inalcanzable. Acá
              lleva la misma marca del tutorial que el de escritorio, así que el
              paso encuentra uno de los dos según dónde esté el usuario. */}
          <button
            type="button"
            onClick={toggle}
            data-tour="tema"
            className="w-full flex items-center gap-3 px-4 py-3 border-t border-line/40 hover:bg-bg-2/60 active:bg-bg-3 transition-colors text-left"
          >
            {dark
              ? <Sun size={16} strokeWidth={1.75} className="text-ink-2 flex-shrink-0" />
              : <Moon size={16} strokeWidth={1.75} className="text-ink-2 flex-shrink-0" />}
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-ink-0 leading-tight">
                {dark ? 'Modo claro' : 'Modo oscuro'}
              </div>
              <div className="text-[11px] text-ink-3 leading-tight mt-0.5">
                {dark ? 'Fondo blanco, para usar de día' : 'Fondo oscuro, el de siempre'}
              </div>
            </div>
          </button>
          <button
            onClick={logout}
            className="w-full flex items-center gap-3 px-4 py-3 border-t border-line/40 text-left text-rendi-neg hover:bg-rendi-neg/[0.04] active:bg-rendi-neg/[0.08] transition-colors"
          >
            <LogOut size={16} strokeWidth={1.75} className="flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium leading-tight">Cerrar sesión</div>
              {user?.name && (
                <div className="text-[11px] text-ink-3 leading-tight mt-0.5">{user.name}</div>
              )}
            </div>
          </button>
        </Panel>
      </section>

      {/* Modal de recomendaciones — trigger desde el botón "Recomendaciones"
          de la sección Cuenta arriba. */}
      <RecommendationsModal open={recomOpen} onClose={() => setRecomOpen(false)} />
      <InstalarAppModal open={instalarOpen} onClose={() => setInstalarOpen(false)} origen="mas" />
    </div>
  )
}

// ─── Push notifications section ─────────────────────────────────────────

function PushNotificationsSection({ esAsesor = false }) {
  const toast = useToast()
  const {
    supported, permission, subscribed, loading, plataforma, motivo,
    subscribe, unsubscribe, sendTest,
  } = usePushNotifications()
  const [testing, setTesting] = useState(false)

  // Sin push en este dispositivo (iPhone sin Rendi en el inicio, navegador que
  // no lo trae): el cartel compartido dice por qué y qué hacer.
  if (!supported) {
    return (
      <section>
        <h2 className="text-[12.5px] text-ink-2 mb-2 px-1 font-medium">
          Notificaciones
        </h2>
        <AvisoNotificaciones motivo={motivo} plataforma={plataforma} origen="mas" />
      </section>
    )
  }

  // Ojo: el Toast se llama con push(texto, { type }). Hasta 2026-10-19 esta
  // sección llamaba a un `show` que no existe, y con el `?.` no daba error:
  // ningún mensaje —ni «activadas», ni los errores— se llegó a ver nunca.
  async function handleToggle() {
    try {
      if (subscribed) {
        await unsubscribe()
        toast.push('Notificaciones desactivadas', { type: 'success' })
      } else {
        await subscribe()
        toast.push('Notificaciones activadas', { type: 'success' })
      }
    } catch (ex) {
      // Los motivos con cartel (bloqueadas) ya se ven abajo; el resto, mensaje.
      if (ex?.motivo !== 'bloqueadas') toast.push(ex?.message || MENSAJE_FALLA, { type: ex?.motivo === 'cerro-el-pedido' ? 'info' : 'error' })
    }
  }

  async function handleTest() {
    setTesting(true)
    try {
      const sent = await sendTest()
      if (sent > 0) {
        toast.push(sent === 1 ? 'Te mandamos una notificación de prueba' : `Te mandamos una notificación de prueba a ${sent} dispositivos`, { type: 'success' })
      } else {
        toast.push('No encontramos ningún dispositivo con las notificaciones activadas.', { type: 'warn' })
      }
    } catch {
      toast.push('No pudimos mandar la prueba. Probá de nuevo en un rato.', { type: 'error' })
    } finally {
      setTesting(false)
    }
  }

  const statusLabel = subscribed
    ? 'Activadas'
    : permission === 'denied'
      ? 'Bloqueadas por el navegador'
      : 'Desactivadas'
  const statusTone = subscribed ? 'text-rendi-pos' : permission === 'denied' ? 'text-rendi-neg' : 'text-ink-3'

  return (
    <section>
      <h2 className="text-[12.5px] text-ink-2 mb-2 px-1 font-medium">
        Notificaciones
      </h2>
      <Panel padding="none" className="overflow-hidden">
        {/* Toggle activar/desactivar */}
        <button
          onClick={handleToggle}
          disabled={loading || permission === 'denied'}
          className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-bg-2/60 active:bg-bg-3 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {subscribed
            ? <BellRing size={16} strokeWidth={1.75} className="text-rendi-pos flex-shrink-0" />
            : <Bell size={16} strokeWidth={1.75} className="text-ink-2 flex-shrink-0" />}
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-ink-0 leading-tight flex items-center gap-2">
              Notificaciones push
              <span className={`text-[12px] ${statusTone} font-medium`}>
                {statusLabel}
              </span>
            </div>
            <div className="text-[11px] text-ink-3 leading-tight mt-0.5">
              {/* Lo que de verdad sale por push: los avisos de precio y de
                  variación (alerts_engine) y, al asesor, los movimientos de
                  las carteras de sus clientes (advisor_alerts). */}
              {permission === 'denied' && !subscribed
                ? 'Abajo te decimos cómo destrabarlas.'
                : `${subscribed ? 'Te llegan a este dispositivo' : 'Recibí en este dispositivo'} ${
                    esAsesor ? 'los movimientos de tus clientes y tus avisos de precio.' : 'tus avisos de precio y de variación.'}`}
              {/* Cada dispositivo se activa por separado: activarlas en la
                  compu no hace que lleguen al celular. */}
              {subscribed && plataforma === 'otro' && ' Para que te lleguen al celular, activalas también desde el celular.'}
            </div>
          </div>
          <span className={`text-[12px] ${subscribed ? 'text-rendi-neg' : 'text-rendi-pos'} font-medium`}>
            {loading ? '...' : subscribed ? 'Desactivar' : 'Activar'}
          </span>
        </button>

        {/* Test button */}
        {subscribed && (
          <button
            onClick={handleTest}
            disabled={testing}
            className="w-full flex items-center gap-3 px-4 py-3 border-t border-line/40 text-left hover:bg-bg-2/60 active:bg-bg-3 transition-colors disabled:opacity-60"
          >
            <Send size={16} strokeWidth={1.75} className="text-ink-2 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-ink-0 leading-tight">
                Mandame una de prueba
              </div>
              <div className="text-[11px] text-ink-3 leading-tight mt-0.5">
                Para ver que las notificaciones te llegan bien.
              </div>
            </div>
            <span className="text-[12px] text-data-blue font-medium">
              {testing ? '...' : 'Enviar'}
            </span>
          </button>
        )}

      </Panel>
      {motivo && <AvisoNotificaciones motivo={motivo} plataforma={plataforma} origen="mas" className="mt-2" />}
    </section>
  )
}
