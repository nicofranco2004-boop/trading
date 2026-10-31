// navegacion — las pantallas de la app y quién ve cuáles. UNA lista para el
// menú lateral (Sidebar) y el buscador rápido ⌘K (BuscadorRapido): si cada uno
// tuviera la suya, el día que se agrega o se esconde una pantalla el buscador
// ofrecería un lugar que el menú ya no muestra (o al revés).
import {
  Briefcase, List, Wallet, LineChart, Activity, Newspaper, Compass, TrendingUp,
  Gauge, Bell, Upload, LayoutDashboard, UserRound, Users, CalendarDays,
  BookOpen, Settings, Shield, CandlestickChart,
} from 'lucide-react'
import { hoyISO } from './fecha'

// ── Lanzamiento del análisis técnico (Nico, 31/10/2026) ───────────────────
// «Análisis de mercado» dice «Nuevo» y la fila de «Análisis técnico» va
// resaltada durante 10 días desde que se publica (01/11 → 10/11, los dos
// incluidos): iguales para todos, no contados desde que cada uno lo ve. Se
// apaga solo, sin volver a publicar. El «Beta» NO vence: se saca a mano
// (borrando `beta: true`) cuando Nico lo diga. Un lugar solo: lo leen el menú
// de la compu (Sidebar), «Más» del celular (More) y el título de la página.
export const FIN_DEL_NUEVO = '2026-11-10'

/** ¿Sigue vigente algo que se ve «hasta» ese día (incluido)? `hoy` se pasa en
 *  las pruebas; si no, el día calendario de acá. */
export function sigueVigente(hasta, hoy = hoyISO()) {
  return !!hasta && !!hoy && hoy <= hasta
}

// ── 3 secciones acordeón ──────────────────────────────────────────────────
// «Arriba, cómo está tu plata. Abajo, cómo están los activos» (recuadro 22 del
// tablero, aprobado por Nico el 28/10):
// • Tu Cartera:          lo que tenés y moviste (lo que navegás seguido).
// • Salud de cartera:    cómo le va a tu plata (rendimiento y perfil).
// • Análisis de mercado: cómo están los activos (el pulso del día, la lectura
//                        técnica, el análisis fundamental y las noticias).
// Los `id` de los grupos no cambian (otras pantallas los usan): sólo el nombre.
// EL ORDEN ES EL DEL MENÚ, y va lo tuyo junto y primero (pedido de Nico,
// 2026-10-11): antes era Tu Cartera · Mercado · Análisis, y Mercado cortaba al
// medio las dos secciones que hablan de tu cartera. De acá lo toman el menú
// lateral, el buscador ⌘K y "Más" del celular.
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
    id: 'analisis', label: 'Salud de cartera', icon: Compass,
    items: [
      { to: '/analisis',        label: 'Métricas',           icon: TrendingUp },
      { to: '/perfil-inversor', label: 'Perfil de inversor', icon: UserRound },
    ],
  },
  {
    id: 'mercado', label: 'Análisis de mercado', icon: LineChart, nuevoHasta: FIN_DEL_NUEVO,
    items: [
      { to: '/',                label: 'Resumen',              icon: Activity },
      // Lo que tenés y lo que seguís con su lectura técnica (pages/TuLista.jsx).
      // `beta`: la etiqueta violeta (hasta que Nico diga); `resaltadaHasta`:
      // el fondo violeta suave mientras dure el «Nuevo».
      { to: '/analisis-tecnico', label: 'Análisis técnico',    icon: CandlestickChart, beta: true, resaltadaHasta: FIN_DEL_NUEVO },
      // Antes «Calidad de cartera»: la dirección no cambia (links guardados).
      { to: '/fundamentals',    label: 'Análisis fundamental', icon: Gauge },
      { to: '/novedades',       label: 'Novedades',            icon: Newspaper },
    ],
  },
]

// Sueltos — siempre visibles, fuera del acordeón (acciones a mano). El puntito
// de "Alertas" ya NO es estático: se muestra sólo si hay eventos sin ver
// (unseenCount), ver el render en Sidebar.
export const LOOSE = [
  { to: '/alertas', label: 'Alertas',  icon: Bell },
  // `enRegistrar`: no es una fila del menú, vive ADENTRO del botón Registrar
  // (el de la compu y el "+" del celular), en su franja de abajo (pedido de
  // Nico, 2026-10-19). Sigue en esta lista para que la regla de quién lo ve sea
  // una sola y para que el buscador ⌘K lo encuentre.
  { to: '/imports', label: 'Importar', icon: Upload, enRegistrar: true },
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
// con personal. Tu Cartera/Análisis/Mercado + los sueltos asumen una cartera
// cargada → no aplican. Adentro de un cliente (clientCtx activo) es SU
// cartera → todo vuelve a mostrarse. El asesor SÍ ve Alertas a su nivel
// (brief del libro + avisos de sus clientes); Importar no.
//
// "Clientes" es sólo del plan Asesor de verdad (mismo predicado que el gate de
// /clientes) — is_admin NO alcanza.
export function menuVisible({ user, clientCtx } = {}) {
  const isAdvisor = user?.tier === 'advisor'
  const atOwnLevel = isAdvisor && !clientCtx
  const loose = atOwnLevel ? LOOSE.filter(i => i.to === '/alertas') : LOOSE
  return {
    isAdvisor,
    atOwnLevel,
    groups: atOwnLevel ? [] : GROUPS,
    loose,
    // Lo que va adentro del botón Registrar (compu y celular), o null.
    importar: loose.find(i => i.enRegistrar) || null,
    asesorPropio: atOwnLevel ? ASESOR_PROPIO : [],
    // Dentro de un cliente, "Clientes" sigue accesible para volver al roster.
    clientesDesdeCliente: isAdvisor && !atOwnLevel,
    utilidades: UTILIDADES.filter(u => !u.soloAdmin || user?.is_admin),
  }
}

// Cómo se llama el cliente cuya cuenta mira el asesor (o null). Y el grupo de
// la cartera, adentro de un cliente, dice de quién es: "Cartera de Ana", no
// "Tu Cartera". Antes cada pantalla lo armaba a mano (el menú lateral, "Más",
// la lupa, la franja) con respaldos distintos, y el ⌘K seguía diciendo
// "Tu Cartera".
/** ¿La pantalla `to` está en beta? Lo pregunta el título de la página, para
 *  decir lo mismo que el menú sin una segunda lista. */
export function esBeta(to) {
  return GROUPS.some(g => g.items.some(i => i.to === to && i.beta))
}

export function nombreDelCliente(clientCtx) {
  if (!clientCtx) return null
  return clientCtx.label || `Cliente ${clientCtx.id}`
}
export function etiquetaDeGrupo(grupo, clientCtx) {
  return grupo.id === 'cartera' && clientCtx ? `Cartera de ${nombreDelCliente(clientCtx)}` : grupo.label
}

// Todas las pantallas que el usuario ve en el menú, en una lista plana y sin
// repetidos (Dashboard aparece en dos grupos según el nivel). Para el buscador.
export function pantallasVisibles({ user, clientCtx } = {}) {
  const m = menuVisible({ user, clientCtx })
  const lista = [
    ...m.asesorPropio,
    ...(m.clientesDesdeCliente ? [ASESOR_PROPIO.find(i => i.to === '/clientes')] : []),
    ...m.groups.flatMap(g => g.items.map(i => ({ ...i, grupoId: g.id, grupo: etiquetaDeGrupo(g, clientCtx), grupoNuevoHasta: g.nuevoHasta }))),
    ...m.loose,
    ...m.utilidades,
  ]
  const vistos = new Set()
  return lista.filter(i => i && !vistos.has(i.to) && vistos.add(i.to))
}
