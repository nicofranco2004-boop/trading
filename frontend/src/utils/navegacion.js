// navegacion — las pantallas de la app y quién ve cuáles. UNA lista para el
// menú lateral (Sidebar) y el buscador rápido ⌘K (BuscadorRapido): si cada uno
// tuviera la suya, el día que se agrega o se esconde una pantalla el buscador
// ofrecería un lugar que el menú ya no muestra (o al revés).
import {
  Briefcase, List, Wallet, LineChart, Activity, Newspaper, Compass, TrendingUp,
  Gauge, Bell, Upload, LayoutDashboard, UserRound, Users, CalendarDays,
  BookOpen, Settings, Shield,
} from 'lucide-react'

// ── 3 secciones acordeón ──────────────────────────────────────────────────
// • Tu Cartera: lo que tenés y moviste (lo que navegás seguido).
// • Mercado:    qué pasa afuera (el pulso del día + las noticias).
// • Análisis:   entender e interpretar (performance + calidad de tenencias).
// NOTA: el ítem "Rendimiento" (/analisis) se llamaba "Análisis"; se renombró
// para no chocar con el nombre del grupo. Si preferís, volvé a "Análisis" o
// "Diagnóstico".
export const GROUPS = [
  {
    id: 'cartera', label: 'Tu Cartera', icon: Wallet,
    items: [
      { to: '/dashboard',   label: 'Dashboard',    icon: LayoutDashboard },
      { to: '/posiciones',  label: 'Cartera',      icon: Briefcase },
      { to: '/operaciones', label: 'Movimientos',  icon: List },
    ],
  },
  {
    id: 'mercado', label: 'Mercado', icon: LineChart,
    items: [
      { to: '/',          label: 'Resumen',   icon: Activity },
      { to: '/novedades', label: 'Novedades', icon: Newspaper },
    ],
  },
  {
    id: 'analisis', label: 'Análisis', icon: Compass,
    items: [
      { to: '/analisis',        label: 'Métricas',           icon: TrendingUp },
      { to: '/fundamentals',    label: 'Calidad de cartera', icon: Gauge },
      { to: '/perfil-inversor', label: 'Perfil de inversor', icon: UserRound },
    ],
  },
]

// Sueltos — siempre visibles, fuera del acordeón (acciones a mano). El puntito
// de "Alertas" ya NO es estático: se muestra sólo si hay eventos sin ver
// (unseenCount), ver el render en Sidebar.
export const LOOSE = [
  { to: '/alertas', label: 'Alertas',  icon: Bell },
  { to: '/imports', label: 'Importar', icon: Upload },
]

// Plan Asesor en SU nivel (sin haber entrado a un cliente): su home. Dashboard
// acá es el del libro, no el de Tu Cartera (oculta en este estado).
export const ASESOR_PROPIO = [
  { to: '/dashboard',            label: 'Dashboard',            icon: LayoutDashboard },
  { to: '/clientes',             label: 'Clientes',             icon: Users },
  { to: '/novedades',            label: 'Novedades',            icon: Newspaper },
  // Cobros: cupones y amortizaciones de los bonos de TODOS los clientes, con
  // quién cobra cuánto (pedido de un tester, 2026-09).
  { to: '/cobros',               label: 'Cobros',               icon: CalendarDays },
  // Carga de historiales de varios clientes por tanda. Reemplaza, a este
  // nivel, al "Importar" que se oculta (el asesor no tiene cartera propia).
  { to: '/importar-historiales', label: 'Importar historiales', icon: Upload },
]

// El pie del menú: utilidades de la cuenta. Admin, sólo para is_admin.
export const UTILIDADES = [
  { to: '/admin',  label: 'Admin',         icon: Shield,   soloAdmin: true },
  { to: '/guia',   label: 'Guía',          icon: BookOpen },
  { to: '/config', label: 'Configuración', icon: Settings },
]

// Qué ve cada uno. El asesor EN SU PROPIO NIVEL (sin haber entrado a la cuenta
// de un cliente) no tiene cartera propia — decisión de producto: si quiere
// invertir él, se agrega como su propio cliente, no mezcla cuenta de trabajo
// con personal. Tu Cartera/Mercado/Análisis + los sueltos asumen una cartera
// cargada → no aplican. Adentro de un cliente (clientCtx activo) es SU
// cartera → todo vuelve a mostrarse. El asesor SÍ ve Alertas a su nivel
// (brief del libro + avisos de sus clientes); Importar no.
//
// "Clientes" es sólo del plan Asesor de verdad (mismo predicado que el gate de
// /clientes) — is_admin NO alcanza.
export function menuVisible({ user, clientCtx } = {}) {
  const isAdvisor = user?.tier === 'advisor'
  const atOwnLevel = isAdvisor && !clientCtx
  return {
    isAdvisor,
    atOwnLevel,
    groups: atOwnLevel ? [] : GROUPS,
    loose: atOwnLevel ? LOOSE.filter(i => i.to === '/alertas') : LOOSE,
    asesorPropio: atOwnLevel ? ASESOR_PROPIO : [],
    // Dentro de un cliente, "Clientes" sigue accesible para volver al roster.
    clientesDesdeCliente: isAdvisor && !atOwnLevel,
    utilidades: UTILIDADES.filter(u => !u.soloAdmin || user?.is_admin),
  }
}

// Todas las pantallas que el usuario ve en el menú, en una lista plana y sin
// repetidos (Dashboard aparece en dos grupos según el nivel). Para el buscador.
export function pantallasVisibles({ user, clientCtx } = {}) {
  const m = menuVisible({ user, clientCtx })
  const lista = [
    ...m.asesorPropio,
    ...(m.clientesDesdeCliente ? [ASESOR_PROPIO.find(i => i.to === '/clientes')] : []),
    ...m.groups.flatMap(g => g.items.map(i => ({ ...i, grupo: g.label }))),
    ...m.loose,
    ...m.utilidades,
  ]
  const vistos = new Set()
  return lista.filter(i => i && !vistos.has(i.to) && vistos.add(i.to))
}
