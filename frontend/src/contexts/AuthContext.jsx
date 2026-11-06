import { createContext, useContext, useEffect, useLayoutEffect, useState } from 'react'
import { api, clearClientContext, EVENTO_PLAN_REQUERIDO, recargarPorPersona, fijarPersonaDeLaPestana, arranqueResuelto, avisarDesfase, entrandoALaSesion, abrirLaPestana, mostrandoLaCuentaDe, personaDeLaPestana, pedirAlServidor } from '../utils/api'
import { setBrokersRegistry } from '../utils/valuation'
import { isDemoMode, enableDemoMode, disableDemoMode, vencerDemoSiCorresponde, EMAIL_DEL_DEMO } from '../utils/demo'
import { track } from '../utils/track'
import { refreshPlanFeatures } from '../hooks/usePlanFeatures'
import { setUserId, setUserProperties, trackEvent } from '../utils/analytics'
import { trackMetaEvent } from '../utils/metaPixel'
import { quienEs } from '../utils/quienEs'
import { activarUso, mandar as mandarUso } from '../utils/uso'
import { avisarSiEstaInstalada } from '../utils/instalarApp'
import { guardar as guardarEnAlmacen, claves, quitarClaves } from '../utils/almacen'
import { olvidarLaSesionSiEsDe, personaGuardada, sesionGuardadaEsDe } from '../utils/sesionGuardada'
import { CATALOGO, LOCAL, SESION } from '../utils/catalogoDelAlmacen'

const AuthContext = createContext(null)

// User fake para modo demo. No tiene token real — todas las llamadas API
// son interceptadas por handleDemoRequest en api.js.
//
// ⚠️ Tiene que tener los MISMOS campos que el usuario de verdad (mapMeToUser),
// ni uno más salvo `demo` — lo vigila usuarioDemoComoElReal.test.js. Lo que se
// prueba en el demo tiene que fallar en el demo si en las cuentas de verdad
// falla: este objeto tenía `id: 0` y el real no tiene `id`, y el buscador ⌘K
// andaba acá y en ninguna cuenta de verdad.
export const DEMO_USER = {
  name: 'Inversor Demo',
  email: EMAIL_DEL_DEMO,
  is_admin: false,
  tier: 'pro',  // Demo siempre simula Pro para mostrar todas las features
  // En demo simulamos una sub authorized — Config muestra "Activo" + opción
  // de cancelar (que no haría nada real porque las llamadas a la API
  // están interceptadas en api.js).
  access_mode: 'authorized',
  subscription_status: 'authorized',
  subscription_period: 'monthly',
  demo: true,
  created_at: '2024-04-01T00:00:00Z',
}

// Mapea la respuesta de /auth/me al shape de `user` que consume la app.
// Centralizado para que el bootstrap inicial Y refreshUser() produzcan
// EXACTAMENTE el mismo objeto — antes el mapeo vivía inline solo en el
// bootstrap, así que cualquier refresh mid-sesión tenía que duplicarlo (o
// no existía, que era el bug: el tier quedaba stale tras un pago).
export function mapMeToUser(me) {
  return {
    name: me.name || me.email,
    email: me.email,
    is_admin: !!me.is_admin,
    tier: me.tier || 'free',
    // Cuándo se creó la cuenta: "Miembro desde" en Configuración. No se
    // copiaba y en toda cuenta de verdad ahí decía "—" (en el demo, que lo
    // tiene escrito a mano, se veía bien).
    created_at: me.created_at || null,
    // Estado de la suscripción Rebill — usado por Config/Planes para
    // distinguir authorized (mostrar "Cancelar") de cancelled
    // (mostrar "Reactivar" + permitir re-suscribirse).
    subscription_status: me.subscription_status || null,
    subscription_period_end: me.subscription_period_end || null,
    subscription_cancelled_at: me.subscription_cancelled_at || null,
    subscription_period: me.subscription_period || null,
    // Aviso único de cambio de precios (15/10/2026). Quién califica lo decide
    // el BACKEND: acá no se puede, porque quien está en la prueba tiene el
    // mismo tier que quien paga. Ver `subscriptions.debe_ver_aviso_precios`.
    aviso_precios: !!me.aviso_precios,
    // Crédito (modelo Rendi-managed proration). Si credit_active_until
    // > NOW el user tiene acceso al tier sin necesidad de tener una
    // sub Rebill autorizada — viene de un upgrade/downgrade mid-período.
    credit_active_until:   me.credit_active_until || null,
    credit_days_remaining: me.credit_days_remaining ?? 0,
    credit_remaining_usd:  me.credit_remaining_usd ?? 0,
    credit_anchor_plan:    me.credit_anchor_plan || null,
    credit_anchor_period:  me.credit_anchor_period || null,
    // access_mode: single source of truth para el estado del acceso.
    // Valores: 'authorized' (sub Rebill renovable) | 'credit_only'
    // (cambió plan, vive del crédito) | 'cancelled' (canceló manual,
    // grace period) | 'free'.
    access_mode:           me.access_mode || 'free',
    // Paywall de los que nacen sin plan gratis. Son DOS datos distintos:
    //   · requires_plan   → no tiene plan gratis al que caer. Cambia los
    //                       textos DURANTE la prueba ("el día 21 elegís un
    //                       plan" en vez de "vuelve a Free").
    //   · cuenta_en_pausa → se le terminó la prueba y no eligió: muro AHORA.
    // El muro de verdad lo aplica el backend (402 en cualquier endpoint de
    // datos). Esto existe para poder mostrar la pantalla en vez de una pared
    // de errores rojos, que es lo único que se vería con el 402 solo.
    requires_plan:   !!me.requires_plan,
    cuenta_en_pausa: !!me.cuenta_en_pausa,
    // "4 brokers y 312 movimientos" — el resumen que el muro muestra para
    // dejar claro que no se perdió nada. null cuando no hay nada que contar.
    pausa_resumen:   me.pausa_resumen || null,
    // 'prueba_terminada' | 'prueba_usada' — ver el porqué en /api/auth/me.
    pausa_motivo:    me.pausa_motivo || null,
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    // Activación de demo via query param. Soporta `?demo=1` y `?demo=true`.
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search)
      const demoParam = params.get('demo')
      if (demoParam === '1' || demoParam === 'true') {
        enableDemoMode()
        track('demo_mode_started')
        // Limpiamos la URL para no dejar el param visible (UX más limpia)
        try {
          const cleanUrl = window.location.pathname + window.location.hash
          window.history.replaceState({}, '', cleanUrl)
        } catch {}
      } else {
        // Sin `?demo=1` en la URL: una marca vieja no te deja atrapado en el demo.
        vencerDemoSiCorresponde()
      }
      if (isDemoMode()) return DEMO_USER
    }
    // Hidratación optimista: usamos lo que dejamos en localStorage la última
    // vez (solo metadata: nombre, email, tier — sin token). En paralelo
    // /auth/me valida la cookie y refresca los valores.
    // La MISMA lectura fija la persona de la pestaña (utils/api): eran dos
    // lecturas y podían dar distinto (re-test a ciegas 8).
    return abrirLaPestana()
  })
  // Qué cuenta muestra la pantalla, con CADA cambio del usuario, venga de donde
  // venga: si no es la de la pestaña, utils/api frena (re-test a ciegas 8).
  // Antes de que corran los efectos de las pantallas (que es donde piden).
  useLayoutEffect(() => {
    mostrandoLaCuentaDe(user && !user.demo ? quienEs(user) : null)
  }, [user])
  const [bootstrapped, setBootstrapped] = useState(false)

  // Rehidratación: si la cookie HttpOnly es válida, /auth/me devuelve el user.
  // No hay token visible para JS — confiamos en la cookie. En demo skipeamos.
  //
  // 🔴 «¿QUIÉN SOY?» AL ABRIR NO SE RECHAZA POR PERSONA (re-test a ciegas 5). Si
  // el navegador quedó con la persona guardada de Ana y la sesión de Bruno (un
  // inicio de sesión de Bruno cortado justo entre la respuesta y el guardado),
  // esta pregunta decía «soy Ana», el servidor la rechazaba, la página se
  // recargaba y volvía a preguntar lo mismo: recarga sin fin, sin poder ni
  // cerrar sesión. Al abrir, la pestaña todavía no tocó nada de nadie, así que
  // se le cree al servidor: sale sin decir quién es (`sinPersona`) y, si la
  // sesión es de otra persona que la guardada, se guarda la del servidor y se
  // recarga UNA vez; en la próxima apertura coinciden: no hay bucle.
  // Hasta la recarga la pestaña sigue siendo de la guardada (muestra lo que leyó
  // como Ana) y queda frenada, sin cartel: el re-test a ciegas 6 encontró que
  // adoptar la persona nueva en el acto le abría el paso a un «Guardar» de la
  // pantalla de Ana hacia la cuenta de Bruno.
  // Si mientras se preguntaba OTRA pestaña cambió lo guardado, la respuesta ya
  // es vieja: no se pisa lo guardado (era borrarle las ayudas a quien tiene la
  // sesión) y el aviso de esa pestaña recarga ésta.
  useEffect(() => {
    if (isDemoMode()) { setBootstrapped(true); arranqueResuelto(); return }
    // La persona de la PESTAÑA (no otra lectura de lo guardado): con la que se
    // compara la respuesta, y la del pedido si contesta 401.
    const guardada = personaDeLaPestana()
    const enComun = personaGuardada
    api.get('/auth/me', { sinPersona: true })
      .then(me => {
        const fresh = mapMeToUser(me)
        if (enComun() !== guardada) return
        if (guardada && quienEs(fresh) !== guardada) {
          guardarSesion(fresh)
          recargarPorPersona()
          return
        }
        // Sin persona guardada y con sesión: la pestaña pasa a ser de ésa (no
        // mostraba datos de nadie).
        if (!guardada) fijarPersonaDeLaPestana(quienEs(fresh))
        guardarSesion(fresh)
        setUser(fresh)
        refreshPlanFeatures()
        // Analytics: identificar al user y setear propiedades para segmentación
        // en GA4 (tier, access_mode). user_id permite trackear cross-device.
        if (me.id) setUserId(me.id)
        setUserProperties({
          tier: fresh.tier,
          access_mode: fresh.access_mode,
        })
      })
      .catch((err) => {
        // Sólo un 401 quiere decir "no hay sesión". Un corte de red o un error
        // del servidor (un deploy, el celular sin señal) no: antes también
        // borraba la sesión guardada y esta pestaña quedaba en el login con la
        // cookie todavía válida. Y desde que las pestañas se avisan cuando
        // cambia quién está logueado (ver abajo), además recargaba TODAS las
        // otras pestañas de la misma persona. Con otro error se sigue con el
        // usuario guardado; si la sesión de verdad venció, el primer pedido
        // que reciba un 401 la cierra (api.js).
        if (err?.status !== 401) return
        // Lo guardado se borra SÓLO si sigue siendo de quien preguntó: si en
        // el medio entró Bruno en otra pestaña, era borrarlo a él, y su
        // pestaña se recargaba (re-test a ciegas 8: la quinta salida del 401).
        olvidarLaSesionSiEsDe(guardada)
        fijarPersonaDeLaPestana(null)          // al abrir: todavía no mostraba nada de nadie
        setUser(null)
        refreshPlanFeatures()
        setUserId(null)
      })
      .finally(() => { setBootstrapped(true); arranqueResuelto() })
  }, [])

  // 🔴 OTRA PESTAÑA CAMBIÓ QUIÉN ESTÁ LOGUEADO.
  // La sesión es una cookie, y la cookie es UNA para todas las pestañas. Si en
  // otra pestaña alguien cerró sesión y entró con otra cuenta, ésta seguía
  // mostrando —y mandando— lo de la persona anterior, ahora con la sesión de la
  // nueva: la IA, por ejemplo, preguntaba con la cartera y la conversación de
  // una persona en la cuenta de otra. Se recarga la página, así todo lo que la
  // pestaña tenía en memoria (no sólo el chat) se vuelve a pedir con la sesión
  // de verdad. Si es la MISMA persona (un refresco del plan), no pasa nada.
  //
  // Se mira un instante DESPUÉS del aviso y no en el aviso mismo: hay cambios
  // que llegan en dos pasos —el "limpiar" del cartel de error vacía todo y
  // vuelve a poner la misma sesión— y en el medio parece que no hay nadie.
  // Pero en ese instante la cookie YA es de la otra persona: api.js no deja
  // salir nada mientras tanto (calcula el desfase en vivo contra lo guardado:
  // otra persona → cartel; nadie → sin cartel). Sin eso, un «Guardar» tocado
  // en esos 300 ms guardaba lo de una persona en la cuenta de otra (re-test a
  // ciegas 3). Estas recargas vienen de un cambio de verdad: no cuentan para el
  // tope (`porAviso`); contándolas, «salgo y entro con la cuenta correcta» dejaba
  // la pestaña trabada (re-test a ciegas 6).
  //
  // El modo demo cuenta como otra persona (re-test a ciegas 4): una pestaña en
  // el demo y, en otra, la persona entra a su cuenta real —o al revés—. Antes
  // ésta no se enteraba si había arrancado en el demo, y lo que se tocaba ahí
  // se guardaba en la cuenta real.
  useEffect(() => {
    let espera = null
    const yo = user?.demo ? 'demo' : quienEs(user)
    const ahora = () => {
      if (isDemoMode()) return 'demo'
      return personaGuardada()                          // basura → nadie
    }
    const mirar = () => {
      if (ahora() !== yo) recargarPorPersona(0, { porAviso: true })   // los 300 ms ya se esperaron
    }
    const alCambiarEnOtraPestana = (e) => {
      if (e.key !== null && e.key !== 'rendi_user' && e.key !== CATALOGO.modoDemo.clave) return
      avisarDesfase()                                   // el cartel, si corresponde
      clearTimeout(espera)
      espera = setTimeout(mirar, 300)
    }
    window.addEventListener('storage', alCambiarEnOtraPestana)
    return () => {
      clearTimeout(espera)
      window.removeEventListener('storage', alCambiarEnOtraPestana)
    }
  }, [user?.email, user?.demo])

  // El 402 "elegí un plan" despierta el muro sin recargar.
  // ──────────────────────────────────────────────────────────────────────────
  // `cuenta_en_pausa` sale de /auth/me y sólo se pedía al montar la app. A quien
  // se le vence la prueba con la pestaña abierta (el caso normal: la prueba
  // vence a la medianoche) le empezaba a fallar todo con 402 y el muro no
  // aparecía hasta recargar: veía la app rompiéndose sin una explicación.
  //
  // `utils/api.js` emite el evento en CUALQUIER 402 con `code:
  // "plan_requerido"`, y acá se vuelve a pedir /auth/me, que trae el estado
  // nuevo y dibuja el muro. Se ignora si ya está marcado en pausa para no
  // pedir /auth/me una vez por cada request que falla.
  useEffect(() => {
    if (!user || isDemoMode()) return
    let pidiendo = false
    const alPausar = () => {
      if (pidiendo || user.cuenta_en_pausa) return
      pidiendo = true
      refreshUser()
        .catch(() => {})
        .finally(() => { pidiendo = false })
    }
    window.addEventListener(EVENTO_PLAN_REQUERIDO, alPausar)
    return () => window.removeEventListener(EVENTO_PLAN_REQUERIDO, alPausar)
  }, [user])

  // Panel de uso de /admin: se mide sólo con una sesión real. Cambio de
  // persona = se corta lo pendiente de la anterior y arranca de nuevo.
  useEffect(() => {
    const quien = !user || isDemoMode() ? null : quienEs(user)
    activarUso(false)
    if (quien) {
      activarUso(true)
      avisarSiEstaInstalada(quien)
    }
  }, [user ? quienEs(user) : null])  // eslint-disable-line react-hooks/exhaustive-deps

  // Keep-alive: pinga /api/health cada 4 min para que Railway no duerma el servicio.
  // Se activa solo cuando hay un usuario logueado (no en demo ni sin sesión).
  useEffect(() => {
    if (!user || isDemoMode()) return
    const id = setInterval(() => { pedirAlServidor('/health', {}, { freno: false }).catch(() => {}) }, 4 * 60 * 1000)
    return () => clearInterval(id)
  }, [user])

  // 🔴 LA ÚNICA PUERTA: «ESTA PESTAÑA INICIA SESIÓN» (re-test a ciegas 7, 31/10).
  // Todas las entradas pasan por acá —iniciar sesión, registrarse y verificar el
  // mail, reclamar una cuenta, restablecer la contraseña—, después del pedido
  // que pone la cookie. Antes cada pantalla le pasaba el email de quien entraba,
  // y «restablecer la contraseña» no lo tenía (el servidor no lo devuelve): la
  // pestaña quedaba «de nadie», sin freno ni encabezado, y lo que se tocaba se
  // guardaba en la cuenta de quien entrara en otra pestaña. Ahora la persona
  // NUNCA sale de un dato de la pantalla: sale de preguntarle al servidor
  // «¿quién soy?» con la sesión nueva, y hasta tenerla la pestaña queda frenada
  // (sin cartel). Si no contesta, la entrada falla y la pantalla lo dice.
  // El guardián __guards__/claves-del-navegador.test.js da rojo si algo guarda
  // la sesión, o fija la persona al entrar, fuera de acá.
  // `evento`: 'sign_up' (verificar el mail) o 'login', para las métricas.
  async function entrar({ evento = 'login' } = {}) {
    entrandoALaSesion()
    // Plan Asesor: si quedó un contexto de cliente colgado (logout sin
    // "Volver" en la misma pestaña SPA), el header stale rompería TODOS los
    // requests del user nuevo con 403. Identity change = contexto afuera.
    clearClientContext()
    // `_brokersByName`/`_brokersById` de utils/valuation son estado de MÓDULO y
    // no se limpiaban NUNCA: no había un solo setBrokersRegistry([]) en el árbol.
    // Como el login es navegación SPA (sin reload), en una máquina compartida el
    // usuario B podía valuar con los brokers del usuario A hasta que alguna
    // pantalla repoblara el registro. Cambio de identidad = registro afuera.
    setBrokersRegistry([])
    let me
    try {
      // Sin freno (la pestaña está frenada justamente por esto) y sin decir
      // quién es (todavía no lo sabe).
      me = await api.get('/auth/me', { sinFreno: true, sinPersona: true })
    } catch (e) {
      fijarPersonaDeLaPestana(null)
      throw new Error(e?.status === 401
        ? 'La sesión no quedó abierta. Probá entrar de nuevo.'
        : 'No pudimos confirmar tu sesión. Probá de nuevo en un momento.')
    }
    const fresh = mapMeToUser(me)
    // La pestaña pasa a ser de quien dice el servidor —antes de guardarla, así
    // no hay un instante en que lo guardado no coincide— y se borra lo que otra
    // persona guardó en este navegador (la sesión es de ésta sin duda).
    fijarPersonaDeLaPestana(quienEs(fresh), { borrarOtras: true })
    guardarSesion(fresh)
    setUser(fresh)
    // Identity change → forzar refetch del plan features.
    refreshPlanFeatures()
    // Analytics: trackear login. El registro (verificar el mail) manda
    // sign_up también.
    if (evento === 'sign_up') {
      trackEvent('sign_up', { method: 'email' })
      // Meta Pixel: evento de conversión de registro. Es el que optimizan las
      // campañas de Meta Ads y con el que medimos el costo por signup.
      trackMetaEvent('CompleteRegistration', { content_name: 'signup', status: true })
    } else {
      trackEvent('login', { method: 'email' })
    }
    if (me.id) setUserId(me.id)
    // El user sale completo de /auth/me (tier incluido): un asesor aterriza
    // directo en su libro, sin pasar por la vista de usuario común.
    return fresh
  }

  // Lo único que escribe «quién está logueado» en este navegador (salvo
  // borrarlo): el guardián no deja otro lugar.
  // El demo no se guarda: su «usuario» no es una sesión, y guardado otras
  // pestañas lo tomaban por una persona que entró.
  function guardarSesion(u) {
    if (u?.demo) return
    guardarEnAlmacen(CATALOGO.usuario, JSON.stringify(u))
  }

  function updateUser(patch) {
    setUser(prev => {
      const next = { ...(prev || {}), ...patch }
      guardarSesion(next)
      return next
    })
  }

  // Re-fetcha /auth/me y actualiza el `user` canónico + el cache de plan
  // features. Llamar cuando el tier puede haber cambiado DENTRO de la misma
  // sesión sin un reload completo — el caso crítico es el retorno de un pago
  // Rebill: BillingReturn navega por SPA (no hard reload), así que el
  // AuthProvider no se re-monta y `/auth/me` no se vuelve a llamar solo. Sin
  // esto, el navbar y el banner de Config seguían mostrando el tier viejo
  // (free) aunque la cuenta ya estuviera activada en plus/pro.
  //
  // Propaga el error (ej. 401 si la sesión venció) para que el caller decida
  // qué hacer; no toca el estado local en ese caso.
  async function refreshUser() {
    const me = await api.get('/auth/me')
    const fresh = mapMeToUser(me)
    guardarSesion(fresh)
    setUser(fresh)
    refreshPlanFeatures()
    return fresh
  }

  function logout() {
    // 🔴 CERRAR SESIÓN DECIDE POR EL DUEÑO (re-test a ciegas 8). La sesión (la
    // cookie) y lo guardado son UNO para todo el navegador: si en otra pestaña
    // ya entró Bruno, el «Cerrar sesión» de la pestaña de Ana le cerraba la
    // sesión a él y borraba todo lo suyo. Ahora:
    //   · el pedido al servidor dice de quién es (como todos): si la sesión ya
    //     es de otra persona, el servidor no la cierra (409);
    //   · lo guardado en común se borra sólo si es de esta pestaña (o no hay
    //     nadie); si es de otra persona, se deja: es suyo;
    //   · lo de esta pestaña (su almacén, su memoria) se borra siempre.
    const persona = personaDeLaPestana()
    const loComunEsMio = user?.demo ? !personaGuardada() : sesionGuardadaEsDe(persona)
    // Lo que juntó el panel de uso sale ANTES de cortar la sesión: después ya
    // no se le puede atribuir a nadie y se descarta. Sale diciendo de quién es
    // (re-test a ciegas 7: si la pestaña ya no era de nadie salía sin decirlo,
    // y con la cookie de otra persona se le anotaba a ella).
    mandarUso({ alCerrar: true })
    trackEvent('logout')
    setUserId(null)
    // Plan Asesor: el loop rendi_* de abajo borra la KEY rendi_client_ctx,
    // pero la variable módulo-level de api.js seguiría inyectando el header
    // el resto de la sesión SPA — limpiar el mirror en memoria también.
    clearClientContext()
    // `_brokersByName`/`_brokersById` de utils/valuation son estado de MÓDULO y
    // no se limpiaban NUNCA: no había un solo setBrokersRegistry([]) en el árbol.
    // Como el login es navegación SPA (sin reload), en una máquina compartida el
    // usuario B podía valuar con los brokers del usuario A hasta que alguna
    // pantalla repoblara el registro. Cambio de identidad = registro afuera.
    setBrokersRegistry([])
    if (user?.demo) {
      track('demo_mode_exited')
      disableDemoMode()
    } else if (persona || loComunEsMio) {
      // Server-side: borra la cookie HttpOnly. Si falla (network), igual
      // limpiamos el estado local; la cookie expira en 7d como fallback.
      // Sin freno: cerrar sesión tiene que salir aunque la pestaña esté
      // desfasada. Dice de quién es (sale ANTES de que la pestaña deje de ser
      // de esa persona). Sin persona y con lo guardado de otra, no sale: esa
      // sesión no es de esta pestaña.
      api.post('/auth/logout', undefined, { sinFreno: true }).catch(() => {})
    }
    // ESTA pestaña sale: deja de ser de nadie.
    fijarPersonaDeLaPestana(null)
    // SECURITY: limpiar TODOS los flags rendi_ del localStorage para evitar
    // cross-user state leak en máquinas compartidas. Antes solo borrábamos
    // rendi_user, quedaban: rendi_first_import_done, rendi_ai_discovered,
    // rendi_dashboard_currency, rendi_sidebar_collapsed, rendi_demo_overlay,
    // rendi_demo_mode, rendi_theme, etc. User B veía preferencias de user A.
    // Sólo si lo guardado es de esta pestaña: si es de otra persona, es suyo.
    //
    // PRESERVE list — flags que NO se borran al logout:
    //   • rendi_theme: preferencia de máquina, no de cuenta.
    //   • rendi_ai_discovered: "el user de este browser ya descubrió la feature
    //     Coach IA". Si lo borramos, cada logout+login del MISMO user resetea
    //     el checklist y muestra "Coach IA pendiente" como si nunca lo hubiera
    //     usado. Trade-off aceptado: en máquina compartida user B ve ✓ Coach
    //     IA sin haberlo usado — minor leak (no es PII, solo discovery state)
    //     vs UX bug recurrente. Si en el futuro tracking server-side, mover
    //     este flag al endpoint /api/plan/features o similar.
    //   • rendi_user: lo borra sesionGuardada, el único que lo borra.
    //   • rendi_origen, SÓLO al salir del demo: de dónde llegó este navegador
    //     (utils/origen.js). Quien probó el demo todavía no tiene cuenta: si
    //     sale con «Cerrar sesión» y se registra, el origen tiene que viajar.
    //     Al cerrar una cuenta de verdad sí se borra: el que entra después en
    //     esa máquina no llegó por ahí.
    if (loComunEsMio) {
      try {
        const preserve = new Set([CATALOGO.tema.clave, CATALOGO.conocioLaIA.clave, CATALOGO.usuario.clave,
          ...(user?.demo ? [CATALOGO.origen.clave] : [])])
        quitarClaves(LOCAL, claves(LOCAL).filter(k => k.startsWith('rendi_') && !preserve.has(k)))
      } catch { /* localStorage puede no estar disponible (private mode iOS antiguo) — best effort */ }
      olvidarLaSesionSiEsDe(persona)
    }
    // sessionStorage TAMBIÉN (audit): la conversación del chat persiste ahí
    // (rendi_chat_v1*) — si otra persona loguea en la misma pestaña veía el
    // chat del anterior (en un asesor: nombres de clientes, AUM, colas).
    // Mismo criterio rendi_-prefix que arriba. Es de ESTA pestaña: siempre.
    try {
      quitarClaves(SESION, claves(SESION).filter(k => k.startsWith('rendi_')))
    } catch { /* best effort */ }
    setUser(null)
    refreshPlanFeatures()  // limpiamos cache para el próximo login
  }

  function exitDemo() {
    // ESTA pestaña sale del demo al inicio: no es de nadie (si quedaba con la
    // persona guardada de antes, quedaba frenada como «salió alguien»; lo
    // encontró la prueba al azar, pages/sesionAlAzar.render.test.jsx).
    fijarPersonaDeLaPestana(null)
    track('demo_mode_exited')
    disableDemoMode()
    setUser(null)
  }

  const isDemo = !!user?.demo

  return (
    <AuthContext.Provider value={{ user, isDemo, entrar, logout, exitDemo, updateUser, refreshUser, bootstrapped }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
