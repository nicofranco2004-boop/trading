// catalogoDelAlmacen — TODO lo que la app guarda en el navegador, con qué es y
// por qué. Es la lista que usa la única puerta (utils/almacen.js): una clave
// que no está acá no se puede leer ni escribir.
//
// Cada entrada declara:
//   · `clave` (una sola) o `prefijo` (una familia: la clave sigue con algo más;
//     si no es de una cuenta, `restos` dice qué puede seguir);
//   · `donde`: LOCAL (queda) o SESION (dura lo que la pestaña);
//   · `tipo`:
//       CON_DUENO    — datos de UNA cuenta. Se guardan a nombre de la persona y
//                      la cuenta DE LOS DATOS (utils/duenoDeLaPestana), y la
//                      puerta no los guarda si ese dueño ya no es el de la
//                      pestaña. Siempre por `prefijo`.
//       DUENO_PROPIO — datos de una persona con un dueño propio, anterior a la
//                      regla y con su prueba. Lista cerrada: no se suma nada.
//       PREFERENCIA  — cómo se ve o qué ayudas ya vio: sin datos de una cuenta.
//       SESION       — la mecánica de la sesión y de la página.
//   · `porque`: por qué es de ese tipo.
//
// ⚠️ Reusar una entrada para guardar otra cosa (un total en `tema`) no lo frena
// ninguna máquina: lo frena que cada una dice qué guarda. Una cosa nueva, una
// entrada nueva, con su porqué.

export const LOCAL = 'local'
export const SESION = 'sesion'
export const CON_DUENO = 'conDueno'
export const DUENO_PROPIO = 'duenoPropio'
export const PREFERENCIA = 'preferencia'
export const SESION_MECANICA = 'sesion'

const e = (o) => Object.freeze(o)

export const CATALOGO = Object.freeze({
  // ── Datos de una cuenta: a nombre de la persona y la cuenta de los datos ──
  ultimaVisitaDiagnostico: e({ prefijo: 'rendi_lastvisit_diagnostico:', donde: LOCAL, tipo: CON_DUENO,
    porque: '«desde tu última visita» en Análisis: el valor de la cartera y los hallazgos' }),
  descartesDiagnostico: e({ prefijo: 'rendi_diag_dismissed_diag:', donde: LOCAL, tipo: CON_DUENO,
    porque: 'las tarjetas del diagnóstico que se descartaron' }),
  valorVisto: e({ prefijo: 'rendi_valor_visto:', donde: SESION, tipo: CON_DUENO,
    porque: 'el «antes» de los números que cambian (montos)' }),
  versionCartera: e({ prefijo: 'rendi_version_cartera:', donde: SESION, tipo: CON_DUENO,
    porque: 'cuántas veces cambió la cartera de esa cuenta en esta visita' }),
  cambiosMovimientos: e({ prefijo: 'rendi_cambios_movimientos:', donde: SESION, tipo: CON_DUENO,
    porque: 'lo que se cambió en Movimientos (con montos) y todavía no se mostró' }),
  ultimoTotal: e({ prefijo: 'rendi_ultimo_total:', donde: SESION, tipo: CON_DUENO,
    porque: 'el último total visto en cada pantalla (monto)' }),
  fotoDelDia: e({ prefijo: 'rendi_snapshot_date:', donde: LOCAL, tipo: CON_DUENO,
    porque: '«ya guardé la foto de hoy»: si no es de la cuenta, otra se queda sin la suya' }),
  // `deLaPersona`: el dueño es la persona en su cuenta propia aunque tenga un
  // cliente abierto (la tanda es del asesor a su nivel y lleva varios clientes).
  tandaAsesor: e({ prefijo: 'rendi_tanda_ultima:', donde: SESION, tipo: CON_DUENO, deLaPersona: true,
    porque: 'la última tanda de importación del asesor, con nombres de clientes' }),

  dibujos: e({ prefijo: 'rendi_dibujos:', donde: LOCAL, tipo: CON_DUENO, seConservaParaSuDueno: true,
    porque: 'los dibujos del gráfico, que se suben a la cuenta si quedaron pendientes: no se borran cuando entra otra persona (su dueño los sube al volver)' }),

  // ── Dueño propio, anterior a la regla (lista cerrada) ─────────────────────
  conversacionIA: e({ prefijo: 'rendi_chat_', donde: SESION, tipo: DUENO_PROPIO,
    restos: /^(v1(_c\d+)?|demo_v1|dueno)$/,
    porque: 'la conversación con la IA: chatSession.adoptarConversaciones anota de quién es y la borra si entra otra persona' }),
  instaladaAvisada: e({ clave: 'rendi_instalada_avisada', donde: LOCAL, tipo: DUENO_PROPIO,
    porque: 'guarda la persona a la que ya se le avisó al servidor que instaló la app; si entra otra, no coincide' }),

  // ── La sesión y la página ─────────────────────────────────────────────────
  usuario: e({ clave: 'rendi_user', donde: LOCAL, tipo: SESION_MECANICA,
    porque: 'quién está logueado (nombre y email de la propia persona): de acá sale el dueño' }),
  tokenViejo: e({ clave: 'rendi_token', donde: LOCAL, tipo: SESION_MECANICA,
    porque: 'la sesión de versiones viejas: sólo se borra (ahora es una cookie)' }),
  clienteAbierto: e({ clave: 'rendi_client_ctx', donde: LOCAL, tipo: SESION_MECANICA,
    porque: 'con qué cliente ARRANCA una pestaña nueva: el último que eligió el asesor en cualquiera (utils/api)' }),
  clienteDeLaPestana: e({ clave: 'rendi_cliente_de_la_pestana', donde: SESION, tipo: SESION_MECANICA,
    porque: 'qué cliente tiene abierto ESTA pestaña (cada una el suyo), con la persona de la que es: es la cuenta del dueño' }),
  recargasPorPersona: e({ clave: 'rendi_recargas_por_persona', donde: SESION, tipo: SESION_MECANICA,
    porque: 'cuándo se recargó esta pestaña por otra persona en la sesión: tope para que no sea una recarga sin fin' }),
  planGuardado: e({ clave: 'rendi_plan_features_v1', donde: SESION, tipo: SESION_MECANICA,
    porque: 'el plan de la cuenta de esta pestaña (con su dueño), para no parpadear al recargarla; se vuelve a pedir en cada login, /auth/me y cambio de cliente' }),
  modoDemo: e({ clave: 'rendi_demo_mode', donde: LOCAL, tipo: SESION_MECANICA, porque: 'el modo demo está prendido' }),
  demoCambios: e({ clave: 'rendi_demo_overlay', donde: LOCAL, tipo: SESION_MECANICA,
    porque: 'lo que se tocó en el demo (cartera de ejemplo, no de nadie)' }),
  recargaPorVersion: e({ clave: 'rendi_chunk_reload_at', donde: SESION, tipo: SESION_MECANICA,
    porque: 'cuándo se recargó por una versión nueva, para no recargar en bucle' }),
  guardaDeActualizacion: e({ clave: 'rendi_update_guard', donde: SESION, tipo: SESION_MECANICA,
    porque: 'ídem, la guarda de la actualización automática' }),
  origen: e({ clave: 'rendi_origen', donde: LOCAL, tipo: SESION_MECANICA,
    porque: 'de dónde llegó este navegador (atribución del registro)' }),
  pedidoDeVinculo: e({ clave: 'rendi_link_request_token', donde: SESION, tipo: SESION_MECANICA,
    porque: 'el link de pedido de vínculo abierto en esta pestaña; lo responde quien esté logueado y lo valida el servidor' }),

  // ── Preferencias de pantalla o de la máquina ──────────────────────────────
  tema: e({ clave: 'rendi_theme', donde: LOCAL, tipo: PREFERENCIA, porque: 'tema claro u oscuro' }),
  moneda: e({ clave: 'rendi_display_currency', donde: LOCAL, tipo: PREFERENCIA, porque: 'moneda en que se mira' }),
  monedaDelInicioVieja: e({ clave: 'rendi_dashboard_currency', donde: LOCAL, tipo: PREFERENCIA,
    porque: 'la moneda del inicio de versiones viejas: se lee una vez y se pasa a `moneda`' }),
  dolar: e({ clave: 'rendi_valuation_dollar', donde: LOCAL, tipo: PREFERENCIA, porque: 'qué dólar se usa para mirar' }),
  costo: e({ clave: 'rendi_cost_basis', donde: LOCAL, tipo: PREFERENCIA, porque: 'costo a hoy o a la compra' }),
  ocultarSaldos: e({ clave: 'rendi_privacy', donde: LOCAL, tipo: PREFERENCIA, porque: '«Ocultar saldos» prendido o apagado' }),
  modoRendimiento: e({ clave: 'rendi_modo_rendimiento', donde: LOCAL, tipo: PREFERENCIA,
    porque: 'cómo se mide el rendimiento (además se guarda en la cuenta)' }),
  vozPrendida: e({ clave: 'rendi:voz:on', donde: LOCAL, tipo: PREFERENCIA, porque: 'la voz prendida o apagada' }),
  vozVelocidad: e({ clave: 'rendi:voz:rate', donde: LOCAL, tipo: PREFERENCIA, porque: 'la velocidad de la voz' }),
  islaVisible: e({ clave: 'rendi:isla:on', donde: LOCAL, tipo: PREFERENCIA, porque: 'la isla de la voz a la vista o no' }),
  islaPosicion: e({ clave: 'rendi:isla:pos', donde: SESION, tipo: PREFERENCIA, porque: 'dónde quedó la isla arrastrada' }),
  cuadroPosicion: e({ clave: 'rendi:cuadro:pos', donde: SESION, tipo: PREFERENCIA, porque: 'dónde quedó el cuadro de Mervall-E arrastrado' }),
  barraLateral: e({ clave: 'rendi_sidebar_collapsed', donde: LOCAL, tipo: PREFERENCIA, porque: 'barra lateral plegada' }),
  pieDeLaBarra: e({ clave: 'rendi_sidebar_pie_plegado', donde: LOCAL, tipo: PREFERENCIA, porque: 'pie de la barra lateral plegado' }),
  vistaCobros: e({ clave: 'rendi_cobros_vista', donde: LOCAL, tipo: PREFERENCIA, porque: 'cómo se ve la lista de cobros' }),
  pestanaMovimientos: e({ clave: 'rendi_operations_tab', donde: LOCAL, tipo: PREFERENCIA, porque: 'la pestaña elegida en Movimientos' }),
  agruparOperaciones: e({ clave: 'rendi_trades_group', donde: LOCAL, tipo: PREFERENCIA, porque: 'cómo se agrupan las operaciones' }),
  agruparMovimientos: e({ clave: 'rendi_movements_group', donde: LOCAL, tipo: PREFERENCIA, porque: 'cómo se agrupan los movimientos' }),
  densidadCartera: e({ clave: 'rendi_pos_density', donde: LOCAL, tipo: PREFERENCIA, porque: 'densidad de la tabla de la cartera' }),
  cuentasSeparadas: e({ clave: 'rendi_cuentas_separadas', donde: LOCAL, tipo: PREFERENCIA,
    porque: 'qué brokers se ven separados: sólo filtra los brokers de quien mira, no muestra los de otro' }),
  indiceDolares: e({ clave: 'rendi_insights_bench_usd', donde: LOCAL, tipo: PREFERENCIA, porque: 'contra qué índice se compara en dólares' }),
  indicePesos: e({ clave: 'rendi_insights_bench_ars', donde: LOCAL, tipo: PREFERENCIA, porque: 'contra qué índice se compara en pesos' }),
  graficoCapas: e({ clave: 'rendi_grafico_capas', donde: LOCAL, tipo: PREFERENCIA, porque: 'qué indicadores del gráfico están prendidos' }),
  graficoLeyenda: e({ clave: 'rendi_grafico_leyenda', donde: LOCAL, tipo: PREFERENCIA, porque: 'la lista de indicadores abierta o plegada' }),
  graficoTipo: e({ clave: 'rendi_grafico_tipo', donde: LOCAL, tipo: PREFERENCIA, porque: 'línea o velas' }),
  ordenDeLaFicha: e({ clave: 'rendi_ficha_orden', donde: LOCAL, tipo: PREFERENCIA, porque: 'el orden de las secciones de la ficha' }),
  // Ayudas y primeros pasos: a lo sumo una ayuda de más o de menos; no muestran datos.
  conocioLaIA: e({ clave: 'rendi_ai_discovered', donde: LOCAL, tipo: PREFERENCIA, porque: 'ya conoció la IA' }),
  saludoDelDia: e({ clave: 'mervalle_saludo_dia', donde: LOCAL, tipo: PREFERENCIA, porque: 'el saludo del día de Mervall-E ya se dio' }),
  vioNovedades: e({ clave: 'rendi:tour:novedades:v2', donde: LOCAL, tipo: PREFERENCIA, porque: 'ya vio el recorrido de novedades' }),
  pasosOmitidos: e({ clave: 'rendi_checklist_omitidos', donde: LOCAL, tipo: PREFERENCIA, porque: 'pasos de la lista de inicio que se omitieron' }),
  listaDeInicioCerrada: e({ clave: 'rendi_checklist_dismissed', donde: LOCAL, tipo: PREFERENCIA, porque: 'la lista de inicio se cerró' }),
  volverABienvenida: e({ clave: 'rendi_onboarding_pending', donde: LOCAL, tipo: PREFERENCIA, porque: 'volver a la bienvenida después de cargar' }),
  bienvenidaSalteada: e({ clave: 'rendi_onboarding_skipped', donde: LOCAL, tipo: PREFERENCIA, porque: 'se salteó la bienvenida' }),
  bienvenidaCompleta: e({ clave: 'rendi_onboarding_completed', donde: LOCAL, tipo: PREFERENCIA, porque: 'se completó la bienvenida' }),
  primeraImportacion: e({ clave: 'rendi_first_import_done', donde: LOCAL, tipo: PREFERENCIA, porque: 'ya importó alguna vez (para la primera lectura)' }),
  conocioLaCartera: e({ clave: 'rendi_positions_discovered', donde: LOCAL, tipo: PREFERENCIA, porque: 'ya conoció la cartera' }),
  pistaDeslizar: e({ clave: 'rendi_cartera_scroll_descubierto', donde: LOCAL, tipo: PREFERENCIA, porque: 'ya vio la pista de deslizar la cartera' }),
})
