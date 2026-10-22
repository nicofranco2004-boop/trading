// Sidebar — navegación lateral colapsable (V3).
// ═══════════════════════════════════════════════════════════════════════════
// Reestructura 2026-07: de links planos a 3 secciones ACORDEÓN que se despliegan
// al tocarlas (menos ruido, más aire). Arriba de todo, debajo de la moneda, el
// botón violeta «Registrar» (RegistrarMenu) con la campanita de Alertas al lado,
// en chico; Importar vive ADENTRO de Registrar, separado de las cargas a mano
// (pedido de Nico, 2026-10-19: como filas sueltas abajo ocupaban como una
// sección más). Después Mervall-E AI; utilidades (Guía / Config /
// Recomendaciones) + cuenta abajo.
//
// Espaciado GENEROSO a propósito (filas altas, texto grande): llena el alto y
// evita el vacío negro. Dos estados de ancho:
// • Expandida (248px): acordeón con labels.
// • Colapsada (56px): íconos planos de cada destino (el acordeón no aplica).
//   Preferencia persistida en localStorage.
//
// La sección de la ruta activa se abre sola. Acordeón de a uno (abrir una cierra
// las demás). Mobile: design aparte.
//
// QUÉ pantallas se ven (y la regla del asesor) sale de utils/navegacion.js, la
// misma lista que usa el buscador ⌘K. Una lupa abre ese buscador (para quien no
// conoce el atajo): desplegado, en el encabezado al lado de las tres rayas;
// plegado, debajo de la moneda.
//
// El pie (Admin, Guía, Config, Descargar app, Recomendaciones) se puede PLEGAR con la flechita que está sobre su línea de
// arriba: le tapaba lugar a las secciones de la cartera (pedido de Nico,
// 2026-10-19). Abierto por defecto; la preferencia queda en localStorage. El
// tema, salir y el plan quedan siempre a la vista. Si la ruta activa es una
// del pie, se abre solo (como el acordeón).

import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  MessageCircle, Smartphone,
  Sun, Moon, LogOut, Menu, ChevronRight, ChevronDown, Users, Search,
} from 'lucide-react'
import RendiLogo from './RendiLogo'
import CurrencySwitcher from './CurrencySwitcher'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'
import { useCoachDrawer } from '../contexts/CoachDrawerContext'
import { useAlertsContext } from '../contexts/AlertsContext'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import { prefetchRoute } from '../utils/routePrefetch'
import { menuVisible, GROUPS, etiquetaDeGrupo } from '../utils/navegacion'
import { abrirBuscador, atajoBuscador } from './BuscadorRapido'
import RecommendationsModal from './RecommendationsModal'
import InstalarAppModal, { precargarFotosDeInstalar } from './InstalarAppModal'
import MervallE from './ai/MervallE'
import RegistrarMenu from './RegistrarMenu'

const SIDEBAR_W_EXPANDED = '248px'
const SIDEBAR_W_COLLAPSED = '56px'
const LS_KEY = 'rendi_sidebar_collapsed'
const LS_PIE = 'rendi_sidebar_pie_plegado'

// Las listas de pantallas y quién ve cuáles viven en utils/navegacion.js: las
// comparte el buscador rápido ⌘K (BuscadorRapido), así nunca ofrece un lugar
// que este menú no muestra.

// ¿La ruta actual cae dentro de este `to`? '/' es exacto; el resto por prefijo.
function matchPath(pathname, to) {
  if (to === '/') return pathname === '/'
  return pathname === to || pathname.startsWith(to + '/')
}

export default function Sidebar() {
  const { user, logout } = useAuth()
  const { dark, toggle } = useTheme()
  const coachDrawer = useCoachDrawer()
  const location = useLocation()
  const { unseenCount = 0 } = useAlertsContext()  // badge de alertas sin ver
  const { clientCtx } = useAdvisorContext()
  // Qué ve cada uno (asesor en su nivel, adentro de un cliente, el resto):
  // la regla vive en utils/navegacion.js, compartida con el buscador ⌘K.
  const { atOwnLevel, groups: visibleGroups, loose: visibleLoose, importar,
          asesorPropio, clientesDesdeCliente, utilidades } = menuVisible({ user, clientCtx })
  const visibleLeaves = visibleGroups.flatMap(g => g.items)
  // Los «sueltos» ya no son filas: Alertas va de campanita al lado de
  // Registrar e Importar adentro de su menú. Qué se ve sigue saliendo de la
  // lista compartida (el asesor en su nivel no tiene Importar).
  const alertas = visibleLoose.find(i => i.to === '/alertas')
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(LS_KEY) === 'true')
  const [piePlegado, setPiePlegado] = useState(() => localStorage.getItem(LS_PIE) === 'true')
  const [recomOpen, setRecomOpen] = useState(false)
  const [instalarOpen, setInstalarOpen] = useState(false)

  // Grupo de la ruta activa (para abrirlo solo).
  const activeGroupId = GROUPS.find(g => g.items.some(it => matchPath(location.pathname, it.to)))?.id
  const [openGroup, setOpenGroup] = useState(activeGroupId || 'cartera')

  // Al navegar a una ruta de otro grupo, abrir ese grupo.
  useEffect(() => {
    if (activeGroupId) setOpenGroup(activeGroupId)
  }, [activeGroupId])

  // Si la ruta activa vive en el pie, el pie se abre solo: si no, la pantalla
  // en la que estás no se ve marcada en ningún lado del menú.
  const activaEnPie = utilidades.some(it => matchPath(location.pathname, it.to))
  useEffect(() => {
    if (activaEnPie) setPiePlegado(false)
  }, [activaEnPie])

  useEffect(() => {
    localStorage.setItem(LS_PIE, String(piePlegado))
  }, [piePlegado])

  // Persistir + setear CSS var consumida por <main> (margin dinámico)
  useEffect(() => {
    localStorage.setItem(LS_KEY, String(collapsed))
    document.documentElement.style.setProperty(
      '--sidebar-w',
      collapsed ? SIDEBAR_W_COLLAPSED : SIDEBAR_W_EXPANDED,
    )
  }, [collapsed])

  // Clases de una fila-link con ícono (colapsada / utilidad). Generosa.
  const rowCls = ({ isActive }) =>
    `relative flex items-center gap-3 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2.5'} py-2.5 rounded-md text-[13.5px] font-medium transition-colors ${
      isActive ? 'text-ink-0 bg-bg-2' : 'text-ink-2 hover:text-ink-0 hover:bg-bg-1'
    }`

  const ActiveBar = () => (
    <span aria-hidden className="absolute left-0 top-1.5 bottom-1.5 w-0.5 bg-data-violet rounded-full" />
  )

  return (
    <>
    <aside
      className="fixed top-0 left-0 bottom-0 bg-bg-0 border-r border-line flex flex-col z-40 transition-[width] duration-200 ease-out"
      style={{ width: collapsed ? SIDEBAR_W_COLLAPSED : SIDEBAR_W_EXPANDED }}
    >
      {/* Top: logo + toggle hamburguesa */}
      <div className="flex items-center h-14 border-b border-line flex-shrink-0 px-2">
        <NavLink to="/" className="flex items-center gap-2.5 flex-1 px-2 overflow-hidden" title={collapsed ? 'Rendi' : undefined}>
          <RendiLogo size={40} />
          {!collapsed && <span className="font-semibold text-xl tracking-tight text-ink-0">rendi</span>}
        </NavLink>
        {/* La lupa del buscador ⌘K, al lado de las tres rayas (pedido de Nico,
            2026-10-01). Plegado no entra acá (56 px): va debajo de la moneda. */}
        {!collapsed && (
          <button
            type="button"
            onClick={abrirBuscador}
            className="p-1.5 rounded-sm text-ink-3 hover:text-ink-0 hover:bg-bg-2 transition-colors"
            title={`Buscar (${atajoBuscador()})`}
            aria-label="Buscar en Rendi"
          >
            <Search size={15} strokeWidth={1.75} aria-hidden="true" />
          </button>
        )}
        <button
          onClick={() => setCollapsed(c => !c)}
          className="p-1.5 rounded-sm text-ink-3 hover:text-ink-0 hover:bg-bg-2 transition-colors"
          title={collapsed ? 'Expandir menú' : 'Colapsar menú'}
          aria-label={collapsed ? 'Expandir menú' : 'Colapsar menú'}
        >
          <Menu size={15} strokeWidth={1.75} aria-hidden="true" />
        </button>
      </div>

      {/* Moneda — fija acá arriba, fuera del <nav> scrolleable: es la misma
          decisión en todas las páginas, así que el control tiene que estar
          siempre en el mismo lugar y no adentro de la pantalla de turno.
          Antes vivía repartido (toolbar de Cartera, hero del Dashboard,
          /config) y en Métricas no estaba, aunque sus números sí la respetan. */}
      <div className={`flex-shrink-0 border-b border-line ${collapsed ? 'px-2 py-2 flex flex-col items-center' : 'px-2.5 py-2.5'}`}>
        <CurrencySwitcher variant={collapsed ? 'mini' : 'row'} />
        {/* Plegado, la lupa del buscador ⌘K va acá: en el encabezado (56 px)
            sólo entran las tres rayas. Desplegado está arriba, al lado. */}
        {collapsed && (
          <button
            type="button"
            onClick={abrirBuscador}
            title={`Buscar (${atajoBuscador()})`}
            aria-label="Buscar en Rendi"
            className="mt-2 p-1.5 rounded border border-line text-ink-3 hover:text-ink-1 hover:bg-bg-2 transition-colors"
          >
            <Search size={14} strokeWidth={1.75} aria-hidden="true" />
          </button>
        )}
      </div>

      {/* Registrar — el botón violeta, fijo arriba como la moneda (fuera del
          <nav> scrolleable): compra, venta, depósito, retiro y movimiento desde
          cualquier pantalla. Antes eran tres botones en el encabezado de la
          Cartera. El asesor en su nivel no tiene cartera propia donde anotar:
          lo ve recién adentro de un cliente. */}
      {/* Al lado, Alertas en chico: la campanita (con el puntito si hay
          alertas sin ver). El asesor en su nivel, sin Registrar, la ve como
          una fila chica con el nombre. */}
      <div className={`flex-shrink-0 pt-3 ${collapsed ? 'px-2 flex flex-col items-center gap-2' : 'px-2.5 flex items-center gap-2'}`}>
        {!atOwnLevel && (
          <div className={collapsed ? '' : 'flex-1 min-w-0'}>
            <RegistrarMenu collapsed={collapsed} importar={importar} />
          </div>
        )}
        {alertas && (() => {
          const soloIcono = collapsed || !atOwnLevel
          const AlertIcon = alertas.icon
          return (
            <NavLink to={alertas.to} title={soloIcono ? 'Alertas' : undefined}
              aria-label={soloIcono ? 'Alertas' : undefined}
              onMouseEnter={() => prefetchRoute(alertas.to)} onFocus={() => prefetchRoute(alertas.to)}
              className={({ isActive }) =>
                `relative flex-shrink-0 inline-flex items-center justify-center gap-2 rounded-lg border transition-colors ${
                  soloIcono ? (collapsed ? 'w-9 h-9' : 'w-10 h-10') : 'w-full h-9 text-[13px] font-medium'
                } ${isActive ? 'border-data-violet/60 bg-data-violet/10 text-data-violet' : 'border-line text-ink-2 hover:text-ink-0 hover:bg-bg-2'}`}>
              <AlertIcon size={16} strokeWidth={1.75} aria-hidden="true" />
              {!soloIcono && <span>{alertas.label}</span>}
              {/* Puntito violeta sólo si hay eventos SIN VER. Al entrar a
                  /alertas se marcan vistos (AlertsContext.markSeen) → se apaga. */}
              {unseenCount > 0 && (
                <span aria-hidden title="Tenés alertas sin ver"
                  className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-data-violet ring-2 ring-bg-0" />
              )}
            </NavLink>
          )
        })()}
      </div>

      {/* Navegación */}
      <nav className="flex-1 overflow-y-auto overflow-x-hidden py-5 px-2.5">
        {/* Plan Asesor: Dashboard (el libro) + Clientes (el roster), arriba de
            todo — es SU home. Dashboard acá es standalone, no el de la
            sección Tu Cartera (oculta en este estado): adentro de un cliente
            ese grupo reaparece con SU PROPIO Dashboard, así que no conviven
            los dos al mismo tiempo. */}
        {atOwnLevel && (
          <div className="mb-4 space-y-1">
            {asesorPropio.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} title={collapsed ? label : undefined}
                onMouseEnter={() => prefetchRoute(to)} onFocus={() => prefetchRoute(to)}
                className={rowCls}>
                {({ isActive }) => (<>
                  {isActive && <ActiveBar />}
                  <Icon size={18} strokeWidth={1.75} aria-hidden="true" />
                  {!collapsed && <span>{label}</span>}
                </>)}
              </NavLink>
            ))}
          </div>
        )}
        {/* Dentro de un cliente, "Clientes" sigue accesible para volver al
            roster, pero SIN el Dashboard standalone de arriba (ese cliente
            ya tiene el suyo propio en la sección Tu Cartera de abajo). */}
        {clientesDesdeCliente && (
          <div className="mb-4">
            <NavLink to="/clientes" title={collapsed ? 'Clientes' : undefined}
              onMouseEnter={() => prefetchRoute('/clientes')} onFocus={() => prefetchRoute('/clientes')}
              className={rowCls}>
              {({ isActive }) => (<>
                {isActive && <ActiveBar />}
                <Users size={18} strokeWidth={1.75} aria-hidden="true" />
                {!collapsed && <span>Clientes</span>}
              </>)}
            </NavLink>
          </div>
        )}

        {/* Mervall-E AI — botón especial que abre drawer (no navega). En contexto
            de cliente el coach opera sobre LA CUENTA DEL CLIENTE (la IA sigue
            al contexto — /api/ai no es prefijo exento). */}
        <div className="mb-6">
          {!collapsed && (
            <p className="px-3 mb-2 text-[12.5px] text-ink-2 font-medium">Asistente</p>
          )}
          <button
            type="button"
            onClick={() => coachDrawer.open()}
            title={collapsed ? 'Mervall-E AI' : undefined}
            className={`relative w-full flex items-center gap-3 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2.5'} py-2.5 rounded-md text-[14.5px] font-medium transition-colors text-data-violet hover:bg-data-violet/10`}
          >
            {/* Quieto: parpadea y mira el cursor sólo si pasa cerca (250 px).
                Dibuja 26 px pero ocupa 18 (-mx-1): el texto queda alineado con
                el de las otras secciones, que llevan íconos de 18. */}
            <MervallE size={26} forma="head" quieto className="-my-1 -mx-1" />
            {!collapsed && <span>Mervall-E AI</span>}
          </button>
        </div>

        {collapsed ? (
          /* ── Colapsada: íconos planos de cada destino (sin acordeón) ── */
          <div className="space-y-1">
            {visibleLeaves.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} end={to === '/'} title={label}
                onMouseEnter={() => prefetchRoute(to)} onFocus={() => prefetchRoute(to)}
                className={rowCls}>
                {({ isActive }) => (<><Icon size={16} strokeWidth={1.75} aria-hidden="true" />{isActive && <ActiveBar />}</>)}
              </NavLink>
            ))}
          </div>
        ) : (
          /* ── Expandida: 3 secciones acordeón ── */
          <div className="space-y-3">
            {visibleGroups.map((group) => {
              const isOpen = openGroup === group.id
              const GroupIcon = group.icon
              return (
                <div key={group.id}>
                  <button
                    type="button"
                    onClick={() => setOpenGroup(o => (o === group.id ? null : group.id))}
                    aria-expanded={isOpen}
                    className={`w-full flex items-center gap-3 pl-3 pr-2.5 py-3.5 rounded-md text-[15px] font-semibold transition-colors ${
                      isOpen ? 'text-ink-0' : 'text-ink-1 hover:text-ink-0 hover:bg-bg-1'
                    }`}
                  >
                    <GroupIcon size={18} strokeWidth={1.75} aria-hidden="true"
                      className={isOpen ? 'text-data-violet' : 'text-ink-2'} />
                    {/* Adentro de un cliente, la cartera es la de él (el celular
                        dice lo mismo en "Más"). */}
                    {/* Un nombre largo ocupaba 4 renglones (y uno sin espacios, como
                        un mail, empujaba la flecha fuera del menú): se recorta,
                        y entero al pasar el mouse. */}
                    {(() => {
                      const titulo = etiquetaDeGrupo(group, clientCtx)
                      return <span className="flex-1 min-w-0 truncate text-left" title={titulo}>{titulo}</span>
                    })()}
                    <ChevronRight size={16} strokeWidth={2}
                      className={`text-ink-3 transition-transform duration-200 ${isOpen ? 'rotate-90' : ''}`} aria-hidden="true" />
                  </button>
                  <div className={`overflow-hidden transition-all duration-200 ease-out ${isOpen ? 'max-h-60 opacity-100' : 'max-h-0 opacity-0'}`}>
                    <div className="pt-1 pb-1.5 space-y-1">
                      {group.items.map(({ to, label, icon: Icon }) => (
                        <NavLink key={to} to={to} end={to === '/'} title={label}
                          onMouseEnter={() => prefetchRoute(to)} onFocus={() => prefetchRoute(to)}
                          className={({ isActive }) =>
                            `relative flex items-center gap-3 pl-11 pr-2.5 py-2.5 rounded-md text-[14px] transition-colors ${
                              isActive ? 'text-ink-0 bg-bg-2 font-medium' : 'text-ink-2 hover:text-ink-0 hover:bg-bg-1'
                            }`}>
                          {({ isActive }) => (<><Icon size={16} strokeWidth={1.75} aria-hidden="true" />{isActive && <ActiveBar />}<span>{label}</span></>)}
                        </NavLink>
                      ))}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </nav>

      {/* Footer: utilidades + cuenta */}
      <div className="relative border-t border-line px-2.5 py-3 flex-shrink-0">
        {/* La flechita que pliega el pie, montada sobre la línea divisoria.
            Abierto apunta para abajo («guardar»); plegado, para arriba. */}
        <button
          type="button"
          onClick={() => setPiePlegado(p => !p)}
          aria-expanded={!piePlegado}
          aria-controls="sidebar-pie"
          title={piePlegado ? 'Mostrar Guía, Configuración y el resto' : 'Achicar: dejar más lugar a la cartera'}
          aria-label={piePlegado ? 'Mostrar las opciones de abajo' : 'Ocultar las opciones de abajo'}
          className="absolute -top-3 left-1/2 -translate-x-1/2 z-10 w-6 h-6 flex items-center justify-center rounded-full border border-data-violet/50 bg-bg-0 text-data-violet hover:bg-data-violet/15 hover:border-data-violet transition-colors"
        >
          <ChevronDown size={14} strokeWidth={2} aria-hidden="true"
            className={`transition-transform duration-200 ${piePlegado ? 'rotate-180' : ''}`} />
        </button>

        {/* Lo plegable: las utilidades. El alto anima de 0 a lo que
            mida (grid 0fr → 1fr), sin tope fijo que corte una fila. */}
        <div id="sidebar-pie"
          className={`grid transition-[grid-template-rows,opacity] duration-200 ease-out ${piePlegado ? 'grid-rows-[0fr] opacity-0' : 'grid-rows-[1fr] opacity-100'}`}
          inert={piePlegado ? '' : undefined}>
        <div className="overflow-hidden min-h-0">
        {/* Admin, Guía y Configuración: la lista vive en utils/navegacion.js
            (UTILIDADES), compartida con el buscador ⌘K. Admin conserva su
            estilo de fila; las otras dos, el de utilidad. */}
        {utilidades.map(({ to, label, icon: Icon, soloAdmin }) => soloAdmin ? (
          <NavLink key={to} to={to} title={collapsed ? label : undefined} className={rowCls}>
            {({ isActive }) => (<><Icon size={16} strokeWidth={1.75} aria-hidden="true" />{!collapsed && <span>{label}</span>}{isActive && <ActiveBar />}</>)}
          </NavLink>
        ) : (
          <NavLink key={to} to={to} title={collapsed ? label : undefined}
            onMouseEnter={() => prefetchRoute(to)} onFocus={() => prefetchRoute(to)}
            className={({ isActive }) =>
              `flex items-center gap-3 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2.5'} py-2.5 rounded-md text-[13.5px] font-medium transition-colors ${
                isActive ? 'text-ink-0 bg-bg-2' : 'text-ink-3 hover:text-ink-1 hover:bg-bg-1'
              }`}>
            <Icon size={16} strokeWidth={1.75} aria-hidden="true" />
            {!collapsed && <span>{label}</span>}
          </NavLink>
        ))}

        {/* No es una pantalla: abre el cartel con el paso a paso para poner
            Rendi en el celular. Por eso es un botón y no vive en UTILIDADES. */}
        <button type="button" onClick={() => setInstalarOpen(true)}
          onMouseEnter={precargarFotosDeInstalar} onFocus={precargarFotosDeInstalar}
          title={collapsed ? 'Descargar app' : 'Poné Rendi en tu celular'}
          className={`w-full flex items-center gap-3 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2.5'} py-2.5 rounded text-[13.5px] font-medium transition-colors text-ink-3 hover:text-data-violet hover:bg-data-violet/[0.06]`}>
          <Smartphone size={16} strokeWidth={1.75} aria-hidden="true" />
          {!collapsed && <span>Descargar app</span>}
        </button>

        <button type="button" onClick={() => setRecomOpen(true)}
          title={collapsed ? 'Recomendaciones' : 'Mandanos una recomendación'}
          className={`w-full flex items-center gap-3 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2.5'} py-2.5 rounded-md text-[13.5px] font-medium transition-colors text-ink-3 hover:text-data-violet hover:bg-data-violet/[0.06]`}>
          <MessageCircle size={16} strokeWidth={1.75} aria-hidden="true" />
          {!collapsed && <span>Recomendaciones</span>}
        </button>
        </div>
        </div>

        {/* User row: nombre + badge de plan (solo expandida) */}
        {user && !collapsed && (
          <div className="px-1 mt-2 mb-1 flex items-center gap-1.5 min-w-0">
            <span className="flex-1 text-[11.5px] text-ink-3 truncate font-mono" title={user.name}>{user.name}</span>
            <PlanBadge tier={user.tier} />
          </div>
        )}

        {/* Action buttons: theme + logout (siempre visibles) */}
        <div className={`flex items-center gap-1 ${collapsed ? 'flex-col mt-1' : 'px-1'}`}>
          {user && collapsed && (
            <div title={`Plan ${user.tier || 'free'}`} className="mb-1"><PlanBadge tier={user.tier} compact /></div>
          )}
          <button onClick={toggle}
            data-tour="tema"
            className="p-1.5 rounded-sm text-ink-3 hover:text-ink-0 hover:bg-bg-1 transition-colors"
            title={dark ? 'Modo claro' : 'Modo oscuro'} aria-label={dark ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'}>
            {dark ? <Sun size={14} strokeWidth={1.75} aria-hidden="true" /> : <Moon size={14} strokeWidth={1.75} aria-hidden="true" />}
          </button>
          <button onClick={logout}
            className="p-1.5 rounded-sm text-ink-3 hover:text-rendi-neg hover:bg-bg-1 transition-colors"
            title="Cerrar sesión" aria-label="Cerrar sesión">
            <LogOut size={14} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>
      </div>
    </aside>

    <RecommendationsModal open={recomOpen} onClose={() => setRecomOpen(false)} />
    <InstalarAppModal open={instalarOpen} onClose={() => setInstalarOpen(false)} origen="menu" />
    </>
  )
}

// ─── PlanBadge ───────────────────────────────────────────────────────────────
function PlanBadge({ tier, compact = false }) {
  const t = tier || 'free'
  const styles = {
    free:  { label: 'FREE',  bg: 'bg-bg-2',           text: 'text-ink-2',       dot: 'bg-ink-3' },
    plus:  { label: 'PLUS',  bg: 'bg-data-cyan/15',   text: 'text-data-cyan',   dot: 'bg-data-cyan' },
    pro:   { label: 'PRO',   bg: 'bg-data-violet/15', text: 'text-data-violet', dot: 'bg-data-violet' },
    advisor: { label: 'ASESOR', bg: 'bg-data-violet/15', text: 'text-data-violet', dot: 'bg-data-violet' },
    admin: { label: 'ADMIN', bg: 'bg-rendi-pos/15',   text: 'text-rendi-pos',   dot: 'bg-rendi-pos' },
  }
  const s = styles[t] || styles.free
  if (compact) return <span className={`inline-block w-1.5 h-1.5 rounded-full ${s.dot}`} aria-label={`Plan ${s.label}`} />
  return (
    <span className={`shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-sm font-mono text-[9px] font-medium tracking-caps ${s.bg} ${s.text}`}
      aria-label={`Plan actual: ${s.label}`}>{s.label}</span>
  )
}
