// usoCatalogo — LA lista cerrada de lo que se mide del uso de Rendi.
// ═══════════════════════════════════════════════════════════════════════════
// Cada clave es un evento que el código ya marca con `track()` (o, si dice
// `soloGA`, con `trackEvent()` de analytics.js, que hasta ahora iba sólo a
// Google Analytics). Lo que está acá se cuenta en nuestra base (`uso_diario`,
// vía utils/uso.js) y el panel /admin lo muestra con este nombre legible.
//
// Por qué una lista cerrada y no "todos los clics": medir todo automáticamente
// da nombres ilegibles ("button.sc-3f9a") y puede capturar texto de la
// pantalla, montos incluidos. Acá sólo viaja el NOMBRE del evento y cuántas
// veces pasó — nunca los datos que lo acompañan.
//
// Agregar un `track()` nuevo sin anotarlo acá hace fallar
// usoCatalogo.test.js: así ningún botón aparece en el panel con su nombre
// interno, ni deja de contarse sin que nadie se entere.
//
// `soloGA`: el mismo nombre existe también como track() en algunos lugares
// (checklist, onboarding). Se cuenta por UN solo camino para no duplicar.
//
// `tipo: 'vista'`: algo que se MOSTRÓ o TERMINÓ solo (una pantalla que montó, un
// análisis que llegó, un error), no un toque. Viaja como 'vista:<nombre>', no
// suma en "Toques" y en el panel va en "Avisos y resultados", no en "Botones".
//
// Una acción, un nombre: si la misma acción existe en la compu y en el celular,
// se marca con el MISMO evento en las dos (cash_flow_recorded, position_*).

export const EVENTOS = {
  // ── Cartera ──
  position_add_started: { label: 'Empezó a agregar una posición', donde: 'Cartera' },
  position_add_completed: { label: 'Agregó una posición', donde: 'Cartera' },
  position_sell_started: { label: 'Empezó a vender', donde: 'Cartera' },
  position_sold: { label: 'Vendió una posición', donde: 'Cartera' },
  position_deleted: { label: 'Borró una posición', donde: 'Cartera' },
  mobile_row_action: { label: 'Acción en una fila', donde: 'Cartera · celular' },
  cash_flow_recorded: { label: 'Movió efectivo (depósito/retiro)', donde: 'Cartera' },
  plazo_fijo_agregado: { label: 'Agregó un plazo fijo', donde: 'Cartera' },
  cartera_tab_viewed: { label: 'Cambió de pestaña', donde: 'Cartera', tipo: 'vista' },
  operation_added: { label: 'Cargó una operación', donde: 'Movimientos' },
  export_csv_downloaded: { label: 'Exportó a CSV', donde: 'Movimientos / Cartera' },

  // ── Importar ──
  import_started: { label: 'Empezó a importar', donde: 'Importar' },
  import_completed: { label: 'Importó un archivo', donde: 'Importar' },
  import_failed: { label: 'Falló una importación', donde: 'Importar', tipo: 'vista' },

  // ── Mervall-E AI ──
  mervalle_abierto: { label: 'Abrió Mervall-E', donde: 'Botón o burbuja' },
  ai_chat_sent: { label: 'Le escribió a Mervall-E', donde: 'Mervall-E', soloGA: true },
  ai_benchmark_question: { label: 'Preguntó por un benchmark', donde: 'Mervall-E', soloGA: true },
  ai_analyze_opened: { label: 'Tocó «Analizar con IA»', donde: 'Cartera · Activo' },
  ai_analyze_loaded: { label: 'Recibió un análisis de IA', donde: 'Análisis IA', tipo: 'vista' },
  ai_analyze_refresh: { label: 'Pidió rehacer un análisis', donde: 'Análisis IA' },
  ai_analyze_error: { label: 'Falló un análisis de IA', donde: 'Análisis IA', tipo: 'vista' },
  ai_followup_loaded: { label: 'Hizo una repregunta', donde: 'Análisis IA', tipo: 'vista' },
  ai_followup_error: { label: 'Falló una repregunta', donde: 'Análisis IA', tipo: 'vista' },
  ai_followup_blocked_cap: { label: 'Llegó al tope de repreguntas', donde: 'Análisis IA', tipo: 'vista' },
  ai_discovery_banner_shown: { label: 'Vio el cartel de la IA', donde: 'Inicio', tipo: 'vista' },
  ai_discovery_banner_dismissed: { label: 'Cerró el cartel de la IA', donde: 'Inicio' },
  first_insight_viewed: { label: 'Vio su primer diagnóstico', donde: 'Bienvenida', tipo: 'vista' },
  first_insight_coach_cta: { label: 'Fue a la IA desde la bienvenida', donde: 'Bienvenida' },

  // ── Análisis y mercado ──
  analisis_tab_viewed: { label: 'Cambió de pestaña', donde: 'Análisis', tipo: 'vista' },
  behavioral_viewed: { label: 'Abrió Comportamiento', donde: 'Análisis', tipo: 'vista' },
  behavioral_card_opened: { label: 'Abrió una tarjeta de Comportamiento', donde: 'Análisis' },
  calidad_cartera_view: { label: 'Vio la calidad de la cartera', donde: 'Fundamentals', tipo: 'vista' },
  fundamentals_ticker_viewed: { label: 'Analizó un ticker', donde: 'Fundamentals', tipo: 'vista' },
  fundamentals_compared: { label: 'Comparó tickers', donde: 'Fundamentals' },
  fundamentals_ai_summary_loaded: { label: 'Leyó el resumen IA de un ticker', donde: 'Fundamentals', tipo: 'vista' },
  fundamentals_favorite_toggled: { label: 'Marcó/desmarcó un favorito', donde: 'Fundamentals' },
  watchlist_added: { label: 'Agregó a favoritos', donde: 'Buscar · celular' },
  share_card_opened: { label: 'Abrió la tarjeta para compartir', donde: 'Análisis' },
  share_card_generated: { label: 'Generó la tarjeta para compartir', donde: 'Análisis' },
  share_card_downloaded: { label: 'Descargó la tarjeta', donde: 'Análisis' },
  share_card_copied: { label: 'Copió la tarjeta', donde: 'Análisis' },
  share_card_shared: { label: 'Compartió la tarjeta', donde: 'Análisis' },
  wrapped_viewed: { label: 'Abrió el Wrapped', donde: 'Wrapped', tipo: 'vista' },
  wrapped_slide_viewed: { label: 'Pasó una lámina del Wrapped', donde: 'Wrapped', tipo: 'vista' },
  wrapped_share_opened: { label: 'Quiso compartir el Wrapped', donde: 'Wrapped' },
  alerta_creada: { label: 'Creó una alerta', donde: 'Alertas' },

  // ── Navegar ──
  buscador_abierto: { label: 'Abrió el buscador (⌘K)', donde: 'Arriba' },
  buscador_elegido: { label: 'Eligió un resultado del buscador', donde: 'Buscador ⌘K' },
  mobile_search_viewed: { label: 'Abrió Buscar', donde: 'Celular', tipo: 'vista' },
  mobile_search_pick: { label: 'Eligió un resultado de Buscar', donde: 'Celular' },
  mobile_fab_opened: { label: 'Abrió el botón +', donde: 'Celular' },
  moneda_cambiada: { label: 'Cambió USD / Pesos', donde: 'Barra lateral' },
  dolar_valuacion_cambiado: { label: 'Cambió MEP / CCL', donde: 'Configuración' },
  montos_ocultos_cambiado: { label: 'Ocultó/mostró los montos', donde: 'Barra lateral' },
  config_tab_viewed: { label: 'Cambió de pestaña', donde: 'Configuración', tipo: 'vista' },
  recommendation_sent: { label: 'Recomendó Rendi', donde: 'Recomendar' },
  recommendation_email_copied: { label: 'Copió el mail para recomendar', donde: 'Recomendar' },

  // ── Primeros pasos ──
  onboarding_started: { label: 'Empezó el onboarding', donde: 'Onboarding', tipo: 'vista' },
  onboarding_step_completed: { label: 'Completó un paso del onboarding', donde: 'Onboarding' },
  onboarding_completed: { label: 'Terminó el onboarding', donde: 'Onboarding' },
  onboarding_skipped: { label: 'Salteó el onboarding', donde: 'Onboarding' },
  checklist_viewed: { label: 'Vio la lista de primeros pasos', donde: 'Inicio', soloGA: true, tipo: 'vista' },
  checklist_item_clicked: { label: 'Tocó un paso de la lista', donde: 'Inicio' },
  checklist_dismissed: { label: 'Cerró la lista de primeros pasos', donde: 'Inicio' },
  demo_mode_started: { label: 'Entró al demo', donde: 'Demo' },
  demo_mode_exited: { label: 'Salió del demo', donde: 'Demo' },
  demo_plan_cta: { label: 'Fue a planes desde el demo', donde: 'Planes' },

  // ── Planes y pagos ──
  feature_blocked_clicked: { label: 'Tocó algo bloqueado por el plan', donde: 'Varias' },
  upgrade_modal_cta_clicked: { label: 'Tocó «Mejorar plan» en el cartel', donde: 'Cartel de plan' },
  upgrade_promo_clicked: { label: 'Tocó la promo de plan', donde: 'IA' },
  plan_hero_upgrade_clicked: { label: 'Tocó «Mejorar plan»', donde: 'Configuración' },
  upgrade_subscribe_clicked: { label: 'Tocó «Suscribirme»', donde: 'Planes' },
  subscribe_clicked: { label: 'Tocó un plan para pagar', donde: 'Planes', soloGA: true },
  subscribe_started: { label: 'Llegó al link de pago', donde: 'Planes', soloGA: true },
  subscribe_completed: { label: 'Volvió de pagar', donde: 'Pago', soloGA: true, tipo: 'vista' },
  planes_viewed: { label: 'Vio los planes', donde: 'Planes', tipo: 'vista' },
  subscription_plan_changed: { label: 'Cambió de plan', donde: 'Planes' },
  subscription_cancelled: { label: 'Canceló la suscripción', donde: 'Configuración' },
  billing_return: { label: 'Volvió del pago', donde: 'Pago', tipo: 'vista' },
  paywall_muro_visto: { label: 'Vio el muro de elegir plan', donde: 'Muro', tipo: 'vista' },
  paywall_muro_elegir: { label: 'Eligió plan desde el muro', donde: 'Muro' },
  trial_start_clicked: { label: 'Tocó empezar la prueba', donde: 'Cartel de prueba' },
  trial_started: { label: 'Empezó la prueba', donde: 'Cartel de prueba', tipo: 'vista' },
  trial_banner_plans_clicked: { label: 'Fue a planes desde la prueba', donde: 'Cartel de prueba' },
  pro_upsell_banner_clicked: { label: 'Tocó el cartel de Pro', donde: 'Cartel de prueba' },
  pro_upsell_clicked: { label: 'Tocó pasar a Pro', donde: 'Cartel de prueba' },
  pro_upsell_started: { label: 'Empezó a pasar a Pro', donde: 'Cartel de prueba' },

  // ── Asesor ──
  cliente_agregado: { label: 'Creó un cliente', donde: 'Asesor · Clientes' },
  informe_generado: { label: 'Generó informes del período', donde: 'Asesor · Libro' },

  // ── Interno ──
  app_abierta: { label: 'Abrió la app', donde: '—' },
}

// Eventos que existen en el código pero NO se cuentan, con el motivo.
//   route_change → las pantallas se cuentan aparte (pantalla:…), con nombre fijo.
export const NO_SE_CUENTAN = new Set(['route_change'])

// Pantallas: la ruta se lleva a un nombre FIJO. Lo que tiene un dato adentro
// (/activo/GGAL, /posiciones/123) se cuenta como la pantalla, sin el dato.
// El orden importa: gana el primer prefijo que coincide.
export const PANTALLAS = [
  ['/posiciones/', 'pantalla:/posiciones/detalle', 'Detalle de posición'],
  ['/posiciones', 'pantalla:/posiciones', 'Cartera'],
  ['/activo/', 'pantalla:/activo', 'Activo'],
  ['/operaciones', 'pantalla:/operaciones', 'Movimientos'],
  ['/analisis', 'pantalla:/analisis', 'Análisis'],
  ['/fundamentals', 'pantalla:/fundamentals', 'Fundamentals'],
  ['/ai', 'pantalla:/ai', 'Mervall-E AI'],
  ['/novedades', 'pantalla:/novedades', 'Novedades'],
  ['/mensual', 'pantalla:/mensual', 'Mensual'],
  ['/alertas', 'pantalla:/alertas', 'Alertas'],
  ['/imports', 'pantalla:/imports', 'Importar'],
  ['/config', 'pantalla:/config', 'Configuración'],
  ['/planes', 'pantalla:/planes', 'Planes'],
  ['/wrapped', 'pantalla:/wrapped', 'Wrapped'],
  ['/clientes', 'pantalla:/clientes', 'Asesor · Clientes'],
  ['/importar-historiales', 'pantalla:/importar-historiales', 'Asesor · Importar historiales'],
  ['/cobros', 'pantalla:/cobros', 'Asesor · Cobros'],
  ['/dashboard', 'pantalla:/dashboard', 'Asesor · Libro'],
  ['/perfil-inversor', 'pantalla:/perfil-inversor', 'Perfil inversor'],
  ['/onboarding', 'pantalla:/onboarding', 'Onboarding'],
  ['/bienvenida', 'pantalla:/bienvenida', 'Bienvenida'],
  ['/guia', 'pantalla:/guia', 'Guía'],
  ['/mas', 'pantalla:/mas', 'Más · celular'],
  ['/buscar', 'pantalla:/buscar', 'Buscar · celular'],
  ['/admin', 'pantalla:/admin', 'Admin'],
]

/** La pantalla de una ruta, o null si no se cuenta (landing, blog, legales). */
export function pantallaDe(pathname) {
  const p = String(pathname || '').toLowerCase()
  if (p === '/' || p === '') return 'pantalla:/'
  for (const [prefijo, clave] of PANTALLAS) {
    // '/activo/' (con barra) = sólo lo que tiene algo después; '/config' = la
    // pantalla y sus sub-rutas, pero no '/configurar'.
    const coincide = prefijo.endsWith('/')
      ? p.startsWith(prefijo) && p.length > prefijo.length
      : p === prefijo || p.startsWith(prefijo + '/')
    if (coincide) return clave
  }
  return null
}

const NOMBRE_PANTALLA = Object.fromEntries([['pantalla:/', 'Inicio'], ...PANTALLAS.map(([, k, l]) => [k, l])])

/** El nombre con el que viaja al servidor: las vistas llevan 'vista:'. */
export function claveDeUso(evento) {
  const e = EVENTOS[evento]
  if (!e) return null
  return e.tipo === 'vista' ? `vista:${evento}` : evento
}

/** Nombre legible de cualquier evento guardado (o el crudo si no está). */
export function nombreDeUso(evento) {
  if (evento?.startsWith('pantalla:')) return { label: NOMBRE_PANTALLA[evento] || evento.slice(9), donde: evento.slice(9) }
  if (evento?.startsWith('vista:')) evento = evento.slice(6)
  const e = EVENTOS[evento]
  return e ? { label: e.label, donde: e.donde } : { label: evento, donde: 'sin nombre en el catálogo' }
}
