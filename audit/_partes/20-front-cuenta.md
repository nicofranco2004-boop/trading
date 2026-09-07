## Frontend — Cuenta, config, admin, planes, onboarding, público

Alcance: pantallas de autenticación, onboarding, configuración, planes/billing, panel de admin, el laboratorio de IOL, la navegación (sidebar + mobile) y todas las páginas públicas de marketing/SEO/legales.

Todas las rutas relativas son a la raíz del repo. `[V]` = verificado leyendo el código; `[I]` = inferencia (digo de qué me agarré).

---

### 0. Mapa de rutas (contexto para todo lo que sigue)

`[V]` El router vive en `frontend/src/App.jsx`. Hay **dos árboles de rutas distintos** según haya sesión o no (`frontend/src/App.jsx:276` — `if (!user)`).

**Árbol NO autenticado** (`frontend/src/App.jsx:279-329`): `/` → `Landing`; `/verify-email`, `/reset-password`, `/claim`, `/acceso`, `/i/:token`, `/planes`, `/terminos`, `/reembolso`, `/privacidad`, las 6 landings de keyword, `/blog` + 3 artículos, `/guia` + 7 sub-páginas. El catch-all `*` renderiza `<Login />` (`frontend/src/App.jsx:328`) — o sea que **cualquier ruta desconocida sin sesión muestra el login, sin redirigir la URL**.

**Árbol autenticado** (`frontend/src/App.jsx:185-268`): todo lo anterior duplicado + las rutas de la app. El catch-all es `<Navigate to="/" replace />` (`frontend/src/App.jsx:267`).

`[V]` Consecuencia directa de esa duplicación: **`/billing/success`, `/billing/pending` y `/billing/failure` SOLO existen en el árbol autenticado** (`frontend/src/App.jsx:260-262`). No están en el árbol público. Ver la ficha de `BillingReturn` más abajo — la rama "iniciá sesión" de esa página es casi inalcanzable por eso.

`[V]` Redirects de back-compat declarados: `/objetivos`→`/posiciones?tab=objetivos`, `/insights`→`/analisis?tab=diagnostico`, `/comportamiento`→`/analisis?tab=comportamiento`, `/reportes`→`/analisis?tab=reportes`, `/eventos`→`/novedades?tab=eventos`, `/noticias`→`/novedades?tab=noticias`, `/config/notificaciones`→`/alertas` (`frontend/src/App.jsx:205-230`).

---

## AUTENTICACIÓN

### `/login` (y catch-all sin sesión) → `frontend/src/pages/Login.jsx`

- **Qué muestra**: logo, botón "Probar sin cuenta · Modo demo", tabs Login/Registro, form (nombre solo en registro, email, contraseña con toggle ojo), panel inline de "olvidé mi contraseña", panel especial "este email ya está registrado".
- **De dónde saca los datos**: nada al montar salvo un warm-up. Llamadas:
  - `fetch('/api/health')` fire-and-forget al montar, para despertar Railway (`frontend/src/pages/Login.jsx:61`).
  - `POST /api/auth/forgot-password` (`frontend/src/pages/Login.jsx:73`).
  - `POST /api/auth/login` o `POST /api/auth/register` según el modo (`frontend/src/pages/Login.jsx:126`, fetch en `:135`).
  - Ojo: **usa `fetch` crudo, no el wrapper `api`** de `frontend/src/utils/api.js`. Por eso no pasa por el interceptor de demo ni por el header de contexto de asesor. Es coherente con el flujo (todavía no hay sesión) pero es la única familia de páginas que lo hace.
- **⚠️ Cálculos en el cliente**: ninguno financiero. Sí hay validación pre-flight en el browser: email por regex (`frontend/src/pages/Login.jsx:107`), password ≥10 caracteres en registro (`:115`), nombre no vacío (`:119`). El backend revalida.
- **Estado/contexto**: `useAuth()` (solo `login`). No consume Currency/Advisor/Alerts/Privacy/Theme.
- **Gating por plan**: no aplica.
- **Variante mobile**: no hay; es el mismo componente, responsive.
- **Rarezas**:
  - `[V]` `const [info, setInfo] = useState('')` (`frontend/src/pages/Login.jsx:44`) se limpia en `:93` y se renderiza en `:440`, **pero nunca se le asigna un valor no vacío**. Estado muerto: ese `<p>` verde no se puede mostrar jamás.
  - `[V]` El manejo de `?next=` está bien hecho: compara **orígenes** con el parser de `URL`, no prefijos (`frontend/src/pages/Login.jsx:22-30`). Cierra el open-redirect.
  - `[V]` Timeout de 20 s con `AbortController` y mensajes distintos para "abort" vs "red caída" (`:132-151`).
  - `[V]` Tracking: `Lead` a Meta + `sign_up_submitted` a GA4 se disparan **antes** de verificar el email (`:217-218`); `CompleteRegistration` sale después, desde `AuthContext`.

### `/verify-email` → `frontend/src/pages/VerifyEmail.jsx`

- **Qué muestra**: 6 cajitas de OTP con auto-focus y auto-submit, botón Confirmar, "Reenviar código" con cooldown de 60 s, link "Volver al login".
- **De dónde saca los datos**: el email viene del query param `?email=` (`frontend/src/pages/VerifyEmail.jsx:26`). Llamadas: `POST /api/auth/verify-email` (`:119`), `POST /api/auth/resend-verification` (`:162`). También con `fetch` crudo.
- **⚠️ Cálculos en el cliente**: ninguno.
- **Estado/contexto**: `useAuth().login`.
- **Gating por plan**: no aplica.
- **Rarezas / bug**:
  - `[V]` **BUG en el pegado del código.** `frontend/src/pages/VerifyEmail.jsx:104`:
    ```js
    const next = pasted.padEnd(6, '').slice(0, 6).split('')
    ```
    `String.prototype.padEnd` con un `padString` **vacío no rellena nada**. Si el usuario pega 4 dígitos, `next` queda con 4 elementos y `setDigits` deja el array con longitud 4 → el `.map()` de `:210` renderiza **4 cajas en vez de 6**, el auto-submit (`:54`, exige `length === 6`) no dispara y el botón Confirmar queda deshabilitado (`:238`). El usuario queda trabado sin poder tipear los dos dígitos que faltan. Sólo se salva si pega exactamente 6.
  - `[V]` Post-verificación decide el destino leyendo dos flags de localStorage — `rendi_onboarding_skipped` y `rendi_onboarding_completed` (`:143-144`) — y manda a `/onboarding` o a `/`. Es el **único** lugar del frontend que navega a `/onboarding` (verificado con grep: sólo `App.jsx:232` la declara y `VerifyEmail.jsx:149` la usa).
  - `[V]` Si no hay `?email=` en la URL, redirige a `/login` (`:40`) — o sea que el link del mail tiene que traerlo sí o sí.

### `/reset-password` → `frontend/src/pages/ResetPassword.jsx`

- **Qué muestra**: form de contraseña nueva + confirmación, con contadores inline ("Faltan caracteres · N/10") y link al login.
- **De dónde saca los datos**: token del query param (`frontend/src/pages/ResetPassword.jsx:24`). `POST /api/auth/reset-password` (`:50`), también con `fetch` crudo. Si el backend responde OK, hace auto-login con `login(data.token, data.name, { email: data.email })` (`:66`) y navega a `/`.
- **⚠️ Cálculos en el cliente**: ninguno.
- **Estado/contexto**: `useAuth().login`.
- **Rarezas**: `[V]` Sin token en la URL redirige a `/login` (`:34`). Nada más que anotar: es la página más limpia del set.

---

## ONBOARDING

### `/onboarding` → `frontend/src/pages/Onboarding.jsx` (+ `frontend/src/components/onboarding/`)

- **Qué muestra**: wizard de 3 pasos con barra de progreso — `Bienvenida` → `Cartera` → `Listo` (`frontend/src/pages/Onboarding.jsx:39-40`).
- **Flujo paso por paso** `[V]`:
  1. **WelcomeStep** (`frontend/src/components/onboarding/WelcomeStep.jsx`): saludo con el primer nombre, 3 tarjetas de valor (Tu broker / Tu cartera / Coach IA), CTA "Empezar" y "Saltar y explorar yo solo". Sin llamadas a la API.
  2. **PositionStep** (`frontend/src/components/onboarding/PositionStep.jsx`): tres caminos.
     - *Importar CSV* → escribe `localStorage['rendi_onboarding_pending']='1'` y navega a `/imports?from=onboarding` (`:53-56`). `Imports.jsx:31` lee ese `from` y abre el wizard solo. Al terminar el import, `frontend/src/pages/FirstInsight.jsx:50-53` consume el flag y redirige a `/onboarding?step=complete`. **El circuito cierra bien.**
     - *Cargar manual* → mini-form con chips de 6 brokers populares (`:22-29`), moneda ARS/USD/USDT, ticker, cantidad y precio. Hace **dos** llamadas: `POST /api/brokers` (`:195`) y después `POST /api/positions` (`:214`). Tolera el duplicado del broker por 400/409 o por texto del mensaje (`:199`) y trata el 403 como "tu plan no permite más brokers" (`:200`).
     - *Lo hago después* → `onNext({ skipped: true })`.
  3. **CompleteStep** (`frontend/src/components/onboarding/CompleteStep.jsx`): celebración + 3 tarjetas (Ver tu Insight, Coach IA, Quiz de perfil) + CTA "Ir a mi cartera" → `/posiciones`.
- **⚠️ Cálculos en el cliente**: `[V]` `frontend/src/components/onboarding/PositionStep.jsx:219` — el `invested` que se manda al backend lo calcula el navegador: `invested: qty * price`. No lo deriva el servidor de `quantity`/`buy_price`. Es el único número financiero que esta pantalla fabrica.
- **Estado/contexto**: `useAuth()` (guard de sesión), `useCoachDrawer()` en el CompleteStep.
- **Gating por plan**: `[V]` indirecto — el 403 de `POST /api/brokers` se traduce a "Tu plan no permite más brokers" (`PositionStep.jsx:200-204`). No hay gate visual previo.
- **Persistencia**: 3 flags en localStorage — `rendi_onboarding_skipped` (`Onboarding.jsx:36`), `rendi_onboarding_completed` (`:37`), `rendi_onboarding_pending` (`PositionStep.jsx:54`). Ninguno viaja al backend: **si el usuario cambia de navegador, el onboarding vuelve a aparecer** `[I]` (inferido de que `VerifyEmail.jsx:141-148` es el único lector y sólo mira localStorage).
- **Rarezas**:
  - `[V]` **La promesa de "volver al onboarding desde Configuración" es falsa.** El header del archivo lo afirma (`frontend/src/pages/Onboarding.jsx:15-16`, *"El user puede volver al onboarding manualmente desde Config (link 'Repetir tour')"*) y el CompleteStep se lo dice al usuario en pantalla (`frontend/src/components/onboarding/CompleteStep.jsx:77`, *"Podés volver al onboarding desde Configuración si necesitás"*). Grepeando `onboarding` en `frontend/src/pages/Config.jsx` no hay **ni una** ocurrencia. El link no existe.
  - `[V]` `openCoach()` en `CompleteStep.jsx:18-21` navega a `/` y después, con un `setTimeout` de 300 ms, llama a `coachDrawer.open()` — que a su vez navega a `/ai` (`frontend/src/contexts/CoachDrawerContext.jsx:32`). Son **dos navegaciones encadenadas con un timer** para llegar a una página; el paso por `/` es un resto del drawer que ya no existe.
  - `[V]` La tarjeta "Quiz de perfil" apunta a `/analisis?tab=perfil` (`CompleteStep.jsx:61`), que ya no es un tab válido: `frontend/src/pages/Analisis.jsx:48-50` lo intercepta y redirige a `/perfil-inversor`. Funciona, pero por rebote — y esa página **no es el test**, es el cruce; el test vive en `/config?tab=test`.
  - `[V]` `handleSkip()` marca `skipped` y manda a `/posiciones` (`Onboarding.jsx:99`), pero `finishOnboarding()` (`:102`) **no navega**: deja al usuario en el CompleteStep. Es intencional (los CTAs son del paso), pero significa que el flag `rendi_onboarding_completed` se escribe dos veces (`:106` y `:115`).
  - `[V]` El guard de sesión (`:69-73`) sólo chequea `!user`. El comentario de arriba dice "si el user no está logueado **o es admin/demo**, no debería estar acá" (`:68`) — el caso admin/demo no está implementado.

---

## CONFIGURACIÓN

### `/config` → `frontend/src/pages/Config.jsx` (1573 líneas)

Estructura: sub-navegación por `?tab=`. En **desktop** hay un sub-sidebar vertical + contenido; en **mobile**, sin `?tab` se muestra la **lista de secciones** y al tocar una se entra en drill-in con botón "atrás" (`frontend/src/pages/Config.jsx:848-888` vs `:891-926`). El `setSearchParams` es siempre `replace: true` para no ensuciar el historial (`:302`, `:308`).

**Secciones reales** (`frontend/src/pages/Config.jsx:46-52`):

| id | label | contenido |
|---|---|---|
| `cuenta` | Cuenta | panel del asesor + Datos + Importar + Contraseña + Empezar de cero + Eliminar cuenta |
| `test` | Test de inversor | `InvestorProfileForm` |
| `planes` | Planes | `PlanHero` + `<Planes embedded />` |
| `fx` | Tipos de cambio | Moneda de valuación + Costo en dólares + Cotizaciones |
| `soporte` | Soporte | WhatsApp |

- **De dónde saca los datos** (todas por el wrapper `api`, prefijo `/api`):
  | Llamada | Línea | Para qué |
  |---|---|---|
  | `GET /api/dolar` | `frontend/src/pages/Config.jsx:316` | tarjetas Blue/MEP/CCL/Cripto. Refresca cada 10 min (`:42`, `:287`) |
  | `GET /api/brokers` | `:322` | **sólo** el contador "N conectados" de la sección Cuenta |
  | `GET /api/ai/usage` | `:312` | barra de uso de IA del PlanHero |
  | `GET /api/me/advisor` | `:119` | quién administra esta cuenta + pedidos pendientes |
  | `POST /api/me/advisor/requests/{id}/respond` | `:128` | aceptar/rechazar a un asesor |
  | `POST /api/me/advisor/{uid}/revoke` | `:152` | quitarle el acceso a un asesor |
  | `POST /api/auth/change-password` | `:337` | cambiar contraseña |
  | `POST /api/me/reset-data` + `GET /api/me/reset-data/status` | `:363`, `:375` | "Empezar de cero" (**función muerta**, ver rarezas) |
  | `DELETE /api/me` | `:399` | eliminar la cuenta |
  | `POST /api/billing/cancel` | `:1207` | cancelar la suscripción |
  | `GET`/`POST /api/auth/investor-profile` | `frontend/src/components/InvestorProfileForm.jsx:106`, `:118` | test de inversor |

  Además hereda lo que fetchea `<Planes embedded />` (ver esa ficha) y `CurrencyProvider`.

- **⚠️ PREFERENCIAS QUE AFECTAN NÚMEROS FINANCIEROS** — esta es la parte crítica de la pantalla. Las dos viven **sólo en localStorage, per-device, y NUNCA viajan al backend**:

  1. **Moneda de valuación** (`<CurrencyRail />`, `frontend/src/pages/Config.jsx:683`). Tres opciones: USD MEP (default) · USD CCL · Pesos. Mapea a dos ejes del `CurrencyContext`: `currency` (`USD`/`ARS`, clave `rendi_display_currency`) y `valuationDollar` (`mep`/`ccl`, clave `rendi_valuation_dollar`) — `frontend/src/contexts/CurrencyContext.jsx:24-25`, `:146-156`. La cascada de tasa está en `pickFinancialRate` (`frontend/src/contexts/CurrencyContext.jsx:46-54`): el elegido primero, el otro como fallback y **el blue como último recurso**. La conversión usa el `medio` = (compra+venta)/2, no la punta (`:51`).
     - `[V]` **Limitación documentada en el propio archivo** (`frontend/src/contexts/CurrencyContext.jsx:10-14`): la conversión usa el TC **actual**, así que en vista ARS los snapshots históricos se re-expresan al dólar de hoy, no al de la fecha de cada punto. El comentario lo llama "limitación conocida del MVP".
     - `[V]` El mismo control existe en dos lugares: acá (`CurrencyRail`, ancho) y en el shell (`CurrencySwitcher`, sidebar/topbar). Comparten `frontend/src/hooks/useCurrencyChoice.js` (`frontend/src/components/CurrencyRail.jsx:19`), así que no pueden divergir.

  2. **Costo en dólares** (`frontend/src/pages/Config.jsx:703-725`). Toggle `purchase` (default) / `today`, clave `rendi_cost_basis` (`frontend/src/contexts/CurrencyContext.jsx:26`, `:102-109`, `:158-162`). Cambia el **Invertido USD** y el **P&L en dólares** de la Cartera; el valor de mercado siempre va al dólar de hoy. El comentario del contexto (`frontend/src/contexts/CurrencyContext.jsx:87-97`) documenta que el default **era `today` y estaba mal**, con el caso real: una compra de ALUA a 880 pesos con `tc_compra` 1048 mostraba US$0,58 en vez de US$0,84 porque dividía por el MEP de hoy (1517).
     - `[V]` El propio comentario dice que "NO viaja al backend ni a la IA (que razonan a hoy)" (`:85`). O sea: **la Cartera y el Rendi AI pueden mostrar números de costo distintos para el mismo lote** según cómo esté este toggle. Es la fuente de divergencia entre pantallas más limpia que encontré en esta sección.

  Todo lo demás de Config (contraseña, borrado, planes, soporte) no toca números.

- **Otros cálculos en el cliente**:
  - `[V]` `memberSince()` (`frontend/src/pages/Config.jsx:69-79`) calcula la antigüedad en meses con `(Date.now() - created_at) / (1000*60*60*24*30)` — meses de 30 días fijos, redondeado, con piso en 1.
  - `[V]` `PlanHeroFree`: `pct = min(100, count/limit*100)`, `remaining = max(0, limit-count)` con `limit` por defecto **6** (`:973-975`). `PlanHeroPro`: default **6 si es Plus, 60 si es Pro** (`:1157`). El servidor manda `analyses_limit`; los defaults son fallback del browser.
  - `[V]` `FasesDelTrial` (`:1092-1138`) **reconstruye las fechas del trial en el browser** restando días al `ends_at`: `arranquePlus = fin − plus_days*86400000` (`:1096-1097`) y `arranque = fin − total_days*86400000` (`:1103-1104`). El backend no manda esas dos fechas; las inventa el cliente a partir de `ends_at`, `total_days` y `plus_days`.
  - `[V]` `renewalDays` en `Planes` (que Config embebe) hace `Math.ceil((new Date(subscription_period_end) - Date.now())/86400000)` — `frontend/src/pages/Planes.jsx:175-180`.

- **Estado/contexto**: `useAuth()` (`:249`), `useCurrency()` — sólo `costBasis`/`setCostBasis` (`:250`), `useIsMobile()` (`:251`), `usePlanFeatures()` (`:265`), `useAdvisorContext()` (`:274`), `useToast()` (dentro de `AdvisorAccessPanel`, `:112`). **No** usa Privacy ni Theme ni Alerts.

- **Gating por plan**: `[V]` Config **no oculta nada por tier**. El `PlanHero` cambia de forma (`PlanHeroFree` / `PlanHeroPro` / `PlanHeroAdmin`, `:962-966`) y las cards de `/planes` cambian sus CTAs, pero todas las secciones son visibles para free. El único gate real es por **contexto de asesor**: dentro de un cliente se ocultan `cuenta`, `test` y `planes` (`:275-276`), y si el `?tab=` apunta a una de esas se ignora (`:280`).

- **Variante mobile**: `[V]` No hay archivo aparte — es el mismo componente con dos ramas. La divergencia real:
  - Desktop: sin `?tab` cae a `cuenta` (o `fx` en contexto de cliente) — `:281`. Muestra `PageHeader` con eyebrow "Workspace" + sub-sidebar sticky de 190 px.
  - Mobile: sin `?tab` `activeSection` es `null` y se renderiza la **lista** de secciones con chevrons (`:848-874`); al entrar, un `<h1>` con el nombre de la sección y un botón "‹ Configuración" (`:877-888`). No hay sub-sidebar.
  - El evento de telemetría `config_tab_viewed` lleva `surface: 'mobile'|'desktop'` (`:292`).

- **Rarezas de Config**:
  - `[V]` **`resetData()` es código muerto.** La función completa (`frontend/src/pages/Config.jsx:350-389`), con doble `window.confirm`, `POST /api/me/reset-data` y un bucle de polleo de `/api/me/reset-data/status`, **no la llama nadie** (grep de `resetData` en el archivo: sólo la definición en `:350`). El botón está `disabled` y sin `onClick`, diciendo "Próximamente" (`:591-598`). El comentario explica por qué se pausó: SQLite de un solo escritor y el reset le tiraba "database is locked" a todos los usuarios, no al que reseteaba (`:585-590`). El bloque de progreso `resetState` (`:602-617`) tampoco se puede mostrar nunca.
  - `[V]` **`irALasCardsDePlanes()` tiene recursión infinita.** `frontend/src/pages/Config.jsx:956-960`:
    ```js
    function irALasCardsDePlanes(navigate) {
      const el = typeof document !== 'undefined' && document.getElementById('planes-cards')
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      else irALasCardsDePlanes(navigate)      // ← se llama a sí misma
    }
    ```
    El comentario de arriba dice *"Si el ancla no estuviera, cae a la navegación de siempre"* (`:955`) — pero el `else` **no navega**: se re-invoca, sin cambiar nada, hasta reventar el stack (`RangeError`). El parámetro `navigate` que recibe nunca se usa. Hoy el ancla `#planes-cards` está siempre montada (`:661`), así que la rama no se alcanza `[I]`; pero es un crash latente y siete botones pasan por esta función: `:979`, `:1295`, `:1373`, `:1389`, `:1396`, `:1407`, `:1565`.
  - `[V]` **Un asesor ve el hero de plan Free.** `renderPlanes()` hace `const tier = user?.tier || 'free'` (`:651`) y `PlanHero` sólo desvía a `PlanHeroAdmin`/`PlanHeroPro` para `admin`/`pro`/`plus` (`:963-965`). Con `tier === 'advisor'` cae a `PlanHeroFree` → el asesor lee **"Mejorá a Pro y desbloqueá todo"** y una barra "Uso IA 0/6", y justo debajo el componente `Planes` embebido le dice "Tenés el Plan Asesor" (`frontend/src/pages/Planes.jsx:318-344`). Dos mensajes contradictorios en la misma pantalla.
  - `[V]` **El header del archivo miente sobre las secciones.** `frontend/src/pages/Config.jsx:9` lista una sección "Notificaciones → placeholder 'Próximamente'" que **no existe** en `TABS` (`:46-52`). El subtítulo visible al usuario también la promete: *"Tu cuenta, tu plan, los tipos de cambio y las notificaciones — cada cosa en su lugar"* (`:896`). Las notificaciones se mudaron a `/alertas` (redirect en `frontend/src/App.jsx:230`) y a la sección push de `/mas`.
  - `[V]` Imports sin usar: `Mail`, `CalendarClock` y `Check` en `frontend/src/pages/Config.jsx:20` (grep: sólo aparecen en la línea del import).
  - `[V]` El comentario de `renderPerfil` dice *"el formulario de 7 preguntas"* (`:813`) pero `QUESTIONS` en `frontend/src/components/InvestorProfileForm.jsx:16-97` tiene **8**. La UI usa `QUESTIONS.length`, así que en pantalla dice 8; el comentario quedó viejo.
  - `[V]` `AdvisorAccessPanel` define `revoke` **después** del `return` temprano (`:146` vs `:148`) — funciona por hoisting de `const` dentro del closure sólo porque el `return` está antes de su uso en el JSX; es frágil de leer.
  - `[V]` `AdvisorAccessPanel` usa `window.confirm` nativo para rechazar (`:125`) y para revocar (`:149`), igual que "Empezar de cero" (`:352`, `:358`) y "Eliminar cuenta" (`:392`), mientras que **cancelar la suscripción** sí tiene un modal estilizado (`CancelSubscriptionModal`, `:1447`). Criterio inconsistente: el borrado de la cuenta —lo más destructivo— es un `confirm()` del browser.
  - `[V]` Tras cancelar, la página se recarga sola con `setTimeout(() => window.location.reload(), 1800)` (`:1212`) — el usuario no puede leer el mensaje si tarda.

---

## PLANES Y BILLING

### `/planes` → `frontend/src/pages/Planes.jsx` (1075 líneas)

Se renderiza en **dos superficies**: como página (`frontend/src/App.jsx:234` y `:298`, accesible sin login) y **embebida** dentro de `/config?tab=planes` con `<Planes embedded />` (`frontend/src/pages/Config.jsx:662`). El flag `embedded` saca `PageMeta`, `PageHeader` y el "Volver atrás" (`frontend/src/pages/Planes.jsx:320-327`, `:619`).

- **Qué muestra**: banner del trial, banner contextual según `access_mode`, toggle Mensual/Anual, tres cards (Free / Plus / Pro), modal de cambio de plan con preview de crédito, links legales.
- **De dónde saca los datos**:
  - `GET /api/dolar` (`frontend/src/pages/Planes.jsx:133`) — **ver rarezas: el resultado no se usa**.
  - `GET /api/plan/features` vía `usePlanFeatures()` (`:125`) → `tier`, `loading`, `trial`.
  - `user` de `AuthContext` (`:126`) → `access_mode`, `credit_*`, `subscription_period_end`, `subscription_period`.
  - `POST /api/billing/subscribe` (`:232`) → devuelve `init_point`, se valida con `isSafePaymentUrl` antes de redirigir (`:236`).
  - `GET /api/billing/preview-change-plan?plan=..&period=..` (`:278`).
  - `POST /api/billing/change-plan` (`:293`).
  - `POST /api/billing/trial/start` y `POST /api/billing/trial/pro-upsell` desde `TrialCta`/`ProUpsellCta` (`frontend/src/components/plan/TrialCta.jsx:93`, `:155`).

#### 🔴 PRECIOS: hardcodeados en el front, y hay CUATRO fuentes que no coinciden

`[V]` **Los precios están hardcodeados en el frontend.** `frontend/src/pages/Planes.jsx:44-53`:

```
PLUS_PRICE_ARS_MONTHLY            = '5990'
PRO_PRICE_ARS_MONTHLY             = '13990'
PLUS_PRICE_ARS_ANNUAL             = '59900'
PRO_PRICE_ARS_ANNUAL              = '139900'
PLUS_PRICE_ARS_ANNUAL_MONTHLY_EQ  = '4992'
PRO_PRICE_ARS_ANNUAL_MONTHLY_EQ   = '11658'
```

Comparación contra `backend/billing/pricing.py`:

| Plan / período | Front (`Planes.jsx:44-53`) | Backend (`backend/billing/pricing.py`) | ¿Coincide? |
|---|---|---|---|
| Plus mensual | ARS 5.990 | `PLUS_ARS_MONTHLY_TOTAL = 5_990` (`:36`) | ✅ |
| **Pro mensual** | **ARS 13.990** | **`ARS_MONTHLY_TOTAL = 12_100`** (`:51`) | ❌ **+1.890** |
| **Plus anual** | **ARS 59.900** | **`PLUS_ARS_ANNUAL_TOTAL = 59_990`** (`:44`) | ❌ −90 |
| **Pro anual** | **ARS 139.900** | **`ARS_ANNUAL_TOTAL = 123_420`** (`:57`) | ❌ **+16.480** |

Y hay **dos fuentes más**:

- `[V]` `backend/billing/credits.py:38-43` define `PLAN_PRICES_USD = {('plus','monthly'):4.0, ('plus','annual'):40.0, ('pro','monthly'):9.0, ('pro','annual'):90.0}` con el comentario *"Mantener sincronizado con Planes.jsx"* (`:35`). Es lo que alimenta `daily_rate()` (`:51-58`) y por lo tanto **el crédito en USD que Config le muestra al usuario** (`credit_remaining_usd`, renderizado en `frontend/src/pages/Config.jsx:1357` como "equivale a $X"). Coincide con los **alias deprecados** del front (`PLUS_PRICE_USD='4'`, `PRO_PRICE_USD='9'`, `frontend/src/pages/Planes.jsx:70-76`), no con los ARS que el usuario ve.
- `[V]` **El precio que se cobra de verdad no está en ninguno de los dos.** `POST /api/billing/subscribe` (`backend/main.py:26504`) migró de Mercado Pago a Rebill (`backend/main.py:26522-26523`) y llama a `rebill.create_payment_link` (`:26560`), que resuelve el plan por **variable de entorno** `REBILL_PLAN_ID_{PLAN}_{PERIOD}` (`backend/billing/rebill.py:69-73`). El monto vive en el dashboard de Rebill. `backend/billing/pricing.py` sólo lo consume `backend/billing/mercadopago.py:111-112` — **la vía muerta**.
  - Se inserta `amount_ars` en la tabla `subscriptions` con valor **0 literal** (`backend/main.py:26610`), así que la base tampoco guarda cuánto se cobró en el alta.

**Conclusión del hallazgo**: hay cuatro lugares que dicen cuánto vale Pro (front ARS 13.990, `pricing.py` ARS 12.100, `credits.py` USD 9, y Rebill vía env var) y **ninguno es la autoridad de los otros tres**. El número que se muestra y el que se cobra no comparten origen; el crédito proporcional se calcula con un tercero.

`[V]` **Además, tres textos del producto describen tres modelos de precio distintos:**

1. `frontend/src/pages/Planes.jsx:34-43` (comentario) y `frontend/src/components/landing/FAQ.jsx:55` (texto visible al usuario): *"Cobramos en pesos argentinos **a precio fijo**. Plus $5.990 / Pro $13.990 por mes… El cargo en tu tarjeta es el mismo número que ves en la página de planes."* — precios ARS fijos, hardcodeados **por quinta vez** como string literal en el FAQ.
2. `frontend/src/pages/Planes.jsx:633` (pie de la misma página): *"Cobramos en pesos **al TC blue del día**."* Y el `PageMeta` de la página: *"Precios en pesos al blue del día"* (`:352`).
3. `frontend/src/pages/Terminos.jsx:213-215` (los T&C): *"El precio de referencia está expresado en **dólares estadounidenses (USD) y se convierte a ARS al tipo de cambio del día**. Por eso el ancla es el precio en USD y el monto exacto en ARS puede variar de un día a otro."* Repetido en `frontend/src/pages/Reembolso.jsx:201-203`.

La implementación es la (1). Los T&C y el pie de `/planes` afirman lo contrario en una materia con consecuencia legal (Defensa del Consumidor).

`[V]` Detalle menor de la misma familia: el toggle anual muestra **"−15%"** (`frontend/src/pages/Planes.jsx:462`), que es el `ANNUAL_DISCOUNT_PCT = 0.15` del backend (`backend/billing/pricing.py:62`), pero los precios propios del front dan 16,7 % de descuento (el comentario lo dice en `Planes.jsx:47-48`).

- **⚠️ Cálculos en el cliente (Planes)**:
  - `[V]` `renewalDays` — días hasta el próximo cobro: `Math.ceil((new Date(subscription_period_end) - Date.now())/86400000)`, con fallback a `Math.round(creditDays)` si no hay `period_end` (`:175-180`).
  - `[V]` `accessMode` con fallback a `'authorized'` si el usuario tiene `tier != free` pero el backend no mandó `access_mode` (`:139-141`). Mismo fallback en Config (`frontend/src/pages/Config.jsx:1173`).
  - `[V]` `isCurrentAnchor()` (`:196-212`) decide si la card es "tu plan actual" comparando `credit_anchor_plan`/`credit_anchor_period` y, si no hay anchor, cae a `tier` + `subscription_period` con default `monthly` (`:210`).
  - `[V]` `hasPaidProTier = hasProTier && !trial?.active` (`:161`) — el corte que evita que durante la prueba las cards queden todas deshabilitadas.
  - `[V]` `fmtArs()` (`:59-63`) formatea a `es-AR` en el browser.

- **Estado/contexto**: `usePlanFeatures()`, `useAuth()`. No usa Currency (aunque fetchea `/dolar`), ni Advisor, ni Alerts.

- **Gating por plan**: `[V]` No hay contenido bloqueado — es la pantalla de venta. Lo que cambia es el CTA de cada card, resuelto en `ctaForPlan()` (`:665-695`): `Tu plan actual` (disabled) / `Ya tenés Pro` (disabled) / `Cambiar a X` → `change-plan` / `Reactivar X` / `Suscribirme`. Y para `tier === 'advisor'` la página entera se reemplaza por un bloque de contacto por WhatsApp (`:318-344`), con un `wa.me` **hardcodeado con número y texto** (`:335`) en vez de usar `whatsappUrl()` de `frontend/src/utils/support.js` como hace el resto del archivo (`:609`).

- **Variante mobile**: no hay componente aparte; grid `md:grid-cols-3` que colapsa (`:469`).

- **Rarezas**:
  - `[V]` **`tcValuacion` es estado muerto.** `frontend/src/pages/Planes.jsx:129` declara `const [tcValuacion, setTcValuacion] = useState(1415)` y `:132-136` hace `GET /api/dolar` para setearlo con `d.blue.venta`. Grepeando `tcValuacion` en el archivo: sólo aparece en la declaración y en un comentario (`:42`). **Nunca se lee.** O sea: cada montaje de `/planes` —y también cada apertura de `/config?tab=planes`, porque va embebido— dispara un `GET /api/dolar` cuyo resultado se descarta. Encima toma `blue.venta`, la fuente que el resto de la app ya abandonó (`frontend/src/contexts/CurrencyContext.jsx:46-54` usa MEP con `medio`).
  - `[V]` Ternario sin efecto: `const targetPeriod = planId === 'plus' ? billingPeriod : billingPeriod` (`:216`) — las dos ramas son idénticas.
  - `[V]` La página usa `alert()` nativo del browser para todos los errores de pago (`:242`, `:244`, `:254`, `:259`, `:285`, `:309`), mientras Config usa modal y Admin usa toasts.
  - `[V]` Los alias deprecados (`PLUS_PRICE_USD`, `PRO_PRICE_USD`, `PLUS_PRICE_ANNUAL_USD`, `PRO_PRICE_ANNUAL_USD`, `ARS_PLUS_MONTHLY`, `ARS_PLUS_ANNUAL`, `ARS_PLUS_ANNUAL_MONTHLY_EQ`, `ARS_MONTHLY`) y la función `arsPriceRounded()` con un TC 1466 hardcodeado siguen exportados (`:65-96`). `arsPriceRounded` mapea USD 4/9/40/90 a los ARS actuales y, para cualquier otro valor, multiplica por 1466 y redondea a la centena. Es un fósil que sigue siendo importable.
  - `[V]` El `PageMeta` de la página promete en el título *"Plus desde ARS 5.990/mes"* (`:351`) — un precio más, esta vez en la metadata de SEO.

### `/billing/success` · `/billing/pending` · `/billing/failure` → `frontend/src/pages/BillingReturn.jsx`

- **Qué muestra**: tres variantes de una misma tarjeta de resultado (`ReturnLayout`, `:216`). Success pollea hasta que el webhook active el tier; Pending informa; Failure explica el rechazo.
- **De dónde saca los datos**: `[V]` **Ninguna llamada propia.** El hook `useTierPolling` (`:34-96`) llama a `refreshUser()` del `AuthContext` cada 2 s (`POLL_INTERVAL_MS = 2_000`, `:30`) hasta 30 s (`POLL_TIMEOUT_MS`, `:31`); `refreshUser` hace `GET /api/auth/me` (`frontend/src/contexts/AuthContext.jsx:202`). Usar `refreshUser` y no un `api.get` suelto es deliberado: así el navbar y Config se actualizan en vivo (`:40-45`).
- **⚠️ Cálculos en el cliente**: ninguno. La activación la decide el tier que devuelve el backend (`:63`).
- **Estado/contexto**: `useAuth().refreshUser`.
- **Gating**: no aplica.
- **Rarezas**:
  - `[V]` **La rama `unauthenticated` es prácticamente inalcanzable.** `frontend/src/pages/BillingReturn.jsx:113-124` renderiza "Iniciá sesión para ver tu suscripción" cuando `/auth/me` da 401. Pero las rutas `/billing/*` **sólo están declaradas en el árbol autenticado** (`frontend/src/App.jsx:260-262`); si no hay `user`, el `Layout` entra en la rama pública y el catch-all `*` muestra `<Login />` (`frontend/src/App.jsx:328`). El único caso que la alcanza es el de un `rendi_user` hidratado desde localStorage cuya cookie ya venció `[I]` (inferido de la hidratación optimista en `frontend/src/contexts/AuthContext.jsx:84`).
  - `[V]` El texto de éxito para Pro promete "60 análisis IA por semana" hardcodeado (`:145`), duplicando el `PRO_FEATURES` de `frontend/src/data/planCatalog.js:84`.
  - `[V]` El CTA de failure dice literalmente **"Volver a /planes"** (`:209`) — con la barra y todo, como si fuera texto de sistema.
  - `[V]` El `PageMeta` de las tres variantes declara el mismo `canonical="/billing/success"` (`:226`), incluso en pending y failure.
  - `[V]` `PageHeader` se renderiza con `title=""` y `subtitle=""` (`:229`) — sólo para el eyebrow.

### Componentes de plan — `frontend/src/components/plan/`

- `[V]` `TrialCta.jsx` (444 líneas): la elegibilidad **la decide sólo el backend** (`canOfferTrial` = `!!trial?.can_start`, `:38-40`); si el server no habilita, no se renderiza nada. `POST /api/billing/trial/start` (`:93`) y `POST /api/billing/trial/pro-upsell` (`:155`). Exporta `TRIAL_TOTAL_DAYS=15` y `TRIAL_PRO_DAYS=7` (`:23-24`), `trialNotice()` (`:45`), `trialProStageLabel()` (`:62`), `trialDaysLabel()` (`:70`) y el `TrialBanner` que monta el shell en **los dos** layouts (`frontend/src/App.jsx:352` mobile y `:381` desktop; el comentario de `:346-351` cuenta que durante un tiempo estuvo sólo en desktop y la mitad de los usuarios no veía el contador).
- `[V]` `LockedSection.jsx` y `UpgradeModal.jsx`: ambos sólo trackean y navegan a `/planes` (`frontend/src/components/plan/LockedSection.jsx:27-28`, `frontend/src/components/plan/UpgradeModal.jsx:31-33`). No consultan features por su cuenta.
- `[V]` `ExportCsvButton.jsx`: `api.getBlob('/export/{resource}.csv')` (`:42`) y descarga con un `<a href>` a un object URL (`:54`). Si está bloqueado, trackea `feature_blocked_clicked` (`:33`).

---

## ADMIN

### `/admin` → `frontend/src/pages/Admin.jsx` (3265 líneas)

Es la superficie más sensible del producto. Gate del cliente: `if (!user?.is_admin) return <Acceso restringido>` (`frontend/src/pages/Admin.jsx:195-205`). `[V]` La ruta **no tiene guard propio** (`frontend/src/App.jsx:233`), así que el gate es puramente cosmético — y `user` se hidrata de `localStorage['rendi_user']` antes de que `/auth/me` responda (`frontend/src/contexts/AuthContext.jsx:84`, `:92-113`). `[I]` Manipular ese objeto renderiza el chrome del panel por unos cientos de ms; no desbloquea nada porque **todos** los endpoints `/api/admin/*` dependen de `get_admin_user` (verificado en `backend/main.py:15793`, `:18632`, `:19845`).

- **Datos que carga al montar** (`frontend/src/pages/Admin.jsx:51-70`, `Promise.all`): `GET /api/admin/stats` (`:56`), `GET /api/admin/users` (`:57`), `GET /api/admin/plan/conversion` (`:58`, con `.catch(()=>null)`), `GET /api/admin/billing/trial-funnel?days=90` (`:59`, idem).
- **Búsqueda**: `GET /api/admin/users/search?q=…&limit=100` con debounce de 300 ms y guard anti-carrera por secuencia (`:33-49`, `:76`).

#### Tabla completa de acciones de admin

| Acción | Endpoint | Qué modifica | ¿Reversible? | Línea |
|---|---|---|---|---|
| Refrescar panel | `GET /api/admin/stats`, `/admin/users`, `/admin/plan/conversion`, `/admin/billing/trial-funnel` | nada (lectura) | n/a | `:56-59` |
| Buscar usuario | `GET /api/admin/users/search` | nada | n/a | `:76` |
| Aprobar usuario | `POST /api/admin/users/{id}/approve` | `users.approved` | `[I]` no hay botón inverso en la UI | `:93` |
| **Eliminar usuario** | `DELETE /api/admin/users/{id}` | borra la cuenta + posiciones, operaciones, snapshots y brokers | **NO** (sólo backup) | `:104` |
| Regalar plan (Plus / Pro / **Asesor**) 30 días | `POST /api/admin/billing/grant-comp?email=&plan=&days=30` | crédito de cortesía; con `plan=advisor` **reemplaza** el plan de usuario y habilita `/clientes` | `[I]` vence solo a los 30 días; no hay "quitar regalo" | `:124-126` |
| Regalar plan forzando sobre crédito activo | mismo + `&force=true` | pisa el crédito vigente; **los días arrancan hoy** (puede ACORTAR el acceso) | `[I]` no | `:165` |
| Restaurar tier | `POST /api/admin/billing/restore-tier?email=` | realinea `users.tier` con el crédito ya pagado; no recobra ni mueve fechas | `[I]` idempotente | `:181` |
| Broadcast — ver destinatarios | `POST /api/admin/email/broadcast {confirm:false}` | nada (dry-run) | n/a | `:532` |
| Broadcast — enviar prueba | `POST /api/admin/email/broadcast {test_to}` | manda 1 mail | **NO** | `:543` |
| **Broadcast — enviar a todos** | `POST /api/admin/email/broadcast {confirm:true}` | manda mails masivos por Resend | **NO** | `:556` |
| Re-engagement — preview | `POST /api/admin/email/re-engagement {confirm:false}` | nada | n/a | `:678` |
| Re-engagement — enviar | `POST /api/admin/email/re-engagement {confirm:true, resend}` | manda mails + estampa `reengagement_email_sent_at` | **NO** (el mail; el flag lo pisa `resend`) | `:694` |
| Backup manual a S3 | `POST /api/admin/backup-trigger` | sube copia de la base a S3 (pisa la del día) | `[V]` idempotente por día (`backend/main.py:18634-18636`) | `:816` |
| Invitación al trial — preview | `POST /api/admin/email/trial-invite {confirm:false, limit, variant}` | nada | n/a | `:880` |
| Invitación al trial — enviar tanda | `POST /api/admin/email/trial-invite {confirm:true, limit, variant}` | manda N mails y **marca** a esas personas (salen del bolillero) | **NO** | `:893` |
| Regalo Pro — preview | `POST /api/admin/email/gift-plan {confirm:false, only_gifted}` | nada | n/a | `:1015` |
| Regalo Pro — enviar | `POST /api/admin/email/gift-plan {confirm:true, resend, only_gifted}` | manda mails + `gift_plan_email_sent_at` | **NO** | `:1031` |
| Backfill recompute — simular | `POST /api/admin/backfill-recompute?apply=false&safe_only=&cost_only=&offset=&limit=25` | nada (corre sobre copia) | n/a | `:1221` |
| **Backfill recompute — aplicar** | mismo con `apply=true` | reescribe cantidades (modo seguro) o costos de bonos per-100→per-1 (modo costo) de todas las cuentas | **NO — sólo desde backup** (lo dice el `confirm`, `:1251-1252`) | `:1221` |
| Valuación histórica (MTM) — simular | `POST /api/admin/backfill-mtm?apply=false&offset=&limit=6` | nada | n/a | `:1446` |
| **Valuación histórica — aplicar** | mismo con `apply=true` | reescribe `monthly_entries.capital_final` + snapshots de meses cerrados a valor de mercado | **NO** | `:1446` |
| Corrección de moneda — simular | `POST /api/admin/backfill-currency?apply=false&offset=&limit=12` | nada | n/a | `:2615` |
| **Corrección de moneda — aplicar** | mismo con `apply=true` | corrige in-place `import_normalized_tx` envenenadas y re-rebuildea FIFO (sólo cuentas con capital < −50k) | **NO** | `:2615` |
| Re-seedear catálogo FCI | `POST /api/admin/fci/refresh` | reescribe el catálogo de FCI y las cuotapartes | `[I]` re-ejecutable (lo mismo hace el cron diario) | `:1615` |
| Auditoría MtM (costo vs mercado) | `GET /api/insights/mtm-audit` | nada | n/a | `:1668` |
| Detalle de un mes | `GET /api/insights/gap-month?mes=` | nada | n/a | `:1679` |
| Desglose del aportado por año | `GET /api/admin/fx-aportado-breakdown?user_id=` | nada | n/a | `:1997` |
| Cargar candidatas a migrar FX | `GET /api/admin/fx-migrate-candidates` | nada | n/a | `:2007` |
| Snapshots futuros — contar | `POST /api/admin/cleanup-future-snapshots?apply=false` | nada | n/a | `:2044` |
| **Snapshots futuros — borrar** | `POST /api/admin/cleanup-future-snapshots?apply=true` | **borra** snapshots con fecha futura | **NO** | `:2044` |
| Migración FX — simular lote | `POST /api/admin/fx-migrate-batch {user_ids}` (tandas de 25) | nada (una copia por request) | n/a | `:2110` |
| **Migración FX — aplicar por cuenta** | `POST /api/admin/fx-migrate-user?user_id=&apply=true` | re-dolariza ventas + depósitos al TC de la fecha de cada operación (pasa la cuenta de v1 a v2) | **NO** | `:2126` |
| **Migración FX — forzar** | mismo + `&force=true` | igual, salteando el freno de verificación del backend | **NO** | `:2126` (botón en `:2411`) |
| **Reparar histórico de 1 usuario** | `POST /api/admin/repair-user-history {email}` | recalcula `monthly_entries`, borra y regenera snapshots (no toca posiciones ni cash) | **NO** | `:2806` |
| Reparación masiva — simular | `POST /api/admin/repair-snapshots-all?apply=false&offset=&limit=50` | nada | n/a | `:2862` |
| **Reparación masiva — aplicar** | mismo con `apply=true` | borra snapshots contaminados de **todas** las cuentas y regenera fin-de-mes | **NO** | `:2862` |
| Comprobar versión del bundle | `fetch('/version.json')` | nada | n/a | `:1977` |

**Observaciones sobre el panel:**

- `[V]` **La auditoría MtM no es de admin: es del propio admin.** `MtmAuditPanel` (`frontend/src/pages/Admin.jsx:1658`) llama a `GET /api/insights/mtm-audit` y `GET /api/insights/gap-month`, que en el backend dependen de `get_effective_user`, no de `get_admin_user` (`backend/main.py:11839` y `:11562`). O sea: el panel muestra **la cartera del admin logueado** (o la del cliente si hay contexto de asesor activo), no la de un usuario elegido. No hay selector de usuario en el panel. Presentado dentro de `/admin` se lee como una herramienta global y no lo es.
- `[V]` **El botón "Forzar" de la migración FX dispara dos o tres confirmaciones.** `correr(true, true)` (`:2411`) entra igual por el bloque `if (apply)` de `:2072`: primero el `confirm` propio del botón (`:2406`), después el de "cuentas sin simulación" si aplica (`:2087`), y finalmente el genérico "¿Migrar N cuenta(s) al TC histórico?" (`:2089`). Además, el filtro que saca las cuentas en **rojo** (`:2075-2084`) corre **antes** y **no lo saltea el `force`** — así que "forzar" no fuerza la verificación del cliente, sólo la del backend.
- `[V]` **Sin protección de doble envío en el broadcast.** El comentario lo admite: *"OJO: sin protección de duplicado — apretá 'Enviar' una sola vez"* (`:510-511`). Los otros paneles de mail (re-engagement, gift-plan, trial-invite) sí son idempotentes por flag.
- `[V]` El panel se auto-protege contra bundle viejo: `FxMigratePanel` compara su `__BUILD_ID__` contra `/version.json` y muestra un aviso si difieren (`:1974-1988`), porque el auto-update no recarga mientras estás trabajando.
- **⚠️ Cálculos en el cliente**:
  - Embudo de activación: `pct = round(n/base*100)` y `drop = round((prev-n)/prev*100)` sobre `stats.activation` (`:285-287`).
  - "Tasa de actividad": `(active_last_7d / users_total) * 100` (`:257`).
  - `ConversionPanel`: `totalEvents = suma de todos los valores de data.totals` (`:2960`).
  - Los agregados de las tandas (`agg.users_changed`, `positions_changed`, `snapshots_removed`, deltas de P&L y depósitos) se **suman en el browser** chunk por chunk: `BackfillPanel:1215-1236`, `MtmBackfillPanel:1433-1440`, `CurrencyBackfillPanel:1595-…` (`:2593-2607`), `MassRepairPanel:2857-2870`, y `dPnl`/`dDep` en `:2085-2086`. Si una tanda falla se contabiliza aparte pero el total mostrado ya no es el del servidor.
  - `nivelVerif()` (`:2052-2064`): el semáforo rojo/ámbar/verde de la migración FX **lo decide el frontend** combinando 7 señales de la verificación del backend.
- **Estado/contexto**: `useAuth()` (`:16`), `useToast()` (`:27`). Nada más.
- **Gating por plan**: no aplica (es admin/no-admin).
- **Variante mobile**: `[V]` no existe. El panel es una sola implementación con tablas dentro de `overflow-x-auto`; no consulta `useIsMobile`.
- **Cobertura**: `[V]` La UI cablea **25** endpoints `/api/admin/*`. Grepeando los decoradores en el backend hay ~45. Quedan **sin ninguna superficie en la app** (sólo alcanzables con curl + cookie de admin), entre ellos varios destructivos: `POST /api/admin/wipe-broker-data` (`backend/main.py:20273`), `POST /api/admin/delete-snapshot` (`:18590`), `POST /api/admin/repair-comisiones` (`:17637`), `POST /api/admin/recompute-snapshots-netdep` (`:15598`), `POST /api/admin/snapshots/run-now` (`:34252`), y los de diagnóstico `diagnose-negative-capital` (`:16007`), `diagnose-sell-fx` (`:16157`), `diagnose-scale` (`:16566`), `check-invariantes` (`:17771`), `diagnose-reportes-basis` (`:17803`), `diagnose-flujo-implausible` (`:18115`), `diagnose-costo-inconsistente` (`:18375`), `disk-usage` (`:18485`), `ai/tool-usage` (`:18718`), `billing/inspect` (`:19551`), `fci/probe` (`:19985`), `pf/probe` (`:20098`), `iol-lab/runs` (`:31608`), `pg-type-audit` (`:17600`), `ventas-legacy-debug` (`:17362`), `commissions-debug` (`:17504`), `diag/client-ip` (`:15980`).

---

## LABORATORIO IOL

### `/lab/iol` → `frontend/src/pages/IolLab.jsx`

- **Qué muestra**: tres paneles — (1) correr la prueba, con **usuario y contraseña de IOL**; (2) resultado de la corrida (JSON crudo en un `<pre>`); (3) "duración del acceso" con bitácora, botones "Renovar ahora" y "Desconectar y borrar".
- **Quién puede entrar**: `[V]` **La ruta es pública dentro del árbol autenticado** — `frontend/src/App.jsx:226` la declara sin guard, y **no hay ítem de menú en ningún lado** (comentario en `frontend/src/App.jsx:53`: *"escondida: /lab/iol"*). El gate real es del backend: allowlist por email en la variable de entorno `IOL_LAB_EMAILS` (separada por comas) o `is_admin` — `backend/main.py:31338-31339`. El frontend sólo pinta el motivo que devuelve `/iol/lab/status` (`frontend/src/pages/IolLab.jsx:86-98`).
- **¿Pide credenciales del broker?**: `[V]` **SÍ.** Dos inputs, usuario y contraseña de IOL (`frontend/src/pages/IolLab.jsx:129`, `:134`), que se mandan en claro en el body de `POST /api/iol/lab/probe` (`:47`). El frontend limpia el estado del password apenas responde (`:48`). El subtítulo promete que *"Rendi usa tu contraseña una vez para pedirle un token a IOL y la descarta"* (`:109`) y el comentario del backend afirma *"La contraseña no se persiste nunca ni se loguea"* (`backend/main.py:31329-31330`).
- **De dónde saca los datos**: `GET /api/iol/lab/status` (`:26`, y en polleo cada 3 s mientras corre — `:35`), `POST /api/iol/lab/probe` (`:47`), `POST /api/iol/lab/refresh` (`:59`), `DELETE /api/iol/lab/disconnect` (`:72`).
- **⚠️ Cálculos en el cliente**: ninguno financiero. `fmt()` (`:77-80`) le **agrega una `Z`** a la fecha antes de parsear (`new Date(s.replace(' ','T') + 'Z')`), o sea asume que todo lo que devuelve el backend es UTC.
- **Opt-in de persistencia**: checkbox "Medir cuánto dura el acceso", **activado por defecto** (`useState(true)`, `:20`) — guarda el refresh token cifrado y lo renueva por cron hasta que IOL lo rechace (`:138-142`).
- **Estado/contexto**: ninguno. Ni `useAuth` ni nada; se apoya en el `api` con cookie.
- **Gating por plan**: no aplica; el gate es la allowlist.
- **Rarezas**: `[V]` La página no usa `PageMeta` (queda con el `<title>` del index.html o el de la página anterior). El resultado de la corrida se muestra como texto plano sin parsear (`:167`).

---

## NAVEGACIÓN

### Desktop — `frontend/src/components/Sidebar.jsx`

`[V]` Estructura V3: 3 grupos acordeón + sueltos + utilidades + cuenta. Ancho persistido en `localStorage['rendi_sidebar_collapsed']` (`:36`, `:108`, `:122`) y publicado como CSS var `--sidebar-w` que consume el `<main>` (`:123-126`, `frontend/src/App.jsx:377`).

| Grupo | Ítems | Línea |
|---|---|---|
| **Tu Cartera** | `/dashboard`, `/posiciones`, `/operaciones` | `:46-53` |
| **Mercado** | `/` (Resumen), `/novedades` | `:54-60` |
| **Análisis** | `/analisis` (label **"Métricas"**), `/fundamentals` (**"Calidad de cartera"**), `/perfil-inversor` | `:61-68` |
| Sueltos | `/alertas` (con punto violeta si `unseenCount>0`), `/imports` | `:74-77`, `:300-325` |
| Utilidades | Rendi AI (botón → `coachDrawer.open()` → `/ai`), `/admin` (si `is_admin`), `/guia`, `/config`, Recomendaciones (modal) | `:232-240`, `:329-360` |
| Cuenta | nombre + `PlanBadge`, toggle de tema, logout | `:363-385` |

`[V]` Reglas del Plan Asesor: `atOwnLevel = tier==='advisor' && !clientCtx` (`:102`) → se ocultan **los 3 grupos** e `Importar` (`:103`, `:107`), y arriba aparece un bloque propio con `/dashboard`, `/clientes`, `/novedades` (`:177-207`). Dentro de un cliente vuelve todo y queda además `/clientes` para volver al roster (`:211-223`).

`[V]` Contextos que consume: `useAuth`, `useTheme`, `useCoachDrawer`, `useAlertsContext` (badge), `useAdvisorContext`.

### Mobile — `frontend/src/components/mobile/MobileTabBar.jsx` + `MobileTopBar.jsx` + `frontend/src/pages/More.jsx`

`[V]` **TabBar** (`MobileTabBar.jsx:30-36`): 5 slots — `/` Home · `/posiciones` Cartera · **[+] FAB** (bottom sheet, no navega) · `/insights` Insights · `/mas` Más. Para asesores en su propio nivel: `/dashboard`, `/clientes`, `/novedades`, `/mas` **sin FAB** (`:42-47`, `:55-71`).

`[V]` Acciones rápidas del FAB (`:154-190`): `/posiciones?action=new`, `/posiciones?action=sell`, `/?action=watchlist`, `/buscar`.

`[V]` **TopBar** (`MobileTopBar.jsx`): logo, `CurrencySwitcher` variant `chip` (`:86`), botón Coach IA (`:88-95`), búsqueda (`:96-102`), y una tira de cotizaciones con `GET /api/home/indices` (`:36`), pull-to-refresh incluido (`:41-46`).

`[V]` **Página "Más"** (`frontend/src/pages/More.jsx:25-45`): dos grupos — *Tu portfolio* (`/dashboard`, `/posiciones`, `/operaciones`, `/imports`, `/alertas`) y *Análisis* (`/analisis`, `/fundamentals`, `/perfil-inversor`, `/novedades`) — más el bloque de asesor, el de admin, la sección de push y Cuenta (`/config`, Recomendaciones, logout).

#### Problemas del mapa de navegación

- `[V]` 🔴 **El tab "Insights" de mobile apunta a una ruta que redirige.** `MobileTabBar.jsx:34` linkea a `/insights`, pero `frontend/src/App.jsx:206` la reemplaza por `<Navigate to="/analisis?tab=diagnostico" replace />`. Consecuencia: al tocar el tab, el `pathname` termina siendo `/analisis`, que **no está en `TABS`** — así que el punto verde de tab activa (`MobileTabBar.jsx:138-143`) no se enciende para ninguno. En toda la sección de Métricas la barra inferior queda sin indicador. Y el nombre del tab ("Insights") ya no coincide con el de la pantalla ("Métricas", `frontend/src/pages/Analisis.jsx:85`) ni con el del sidebar de desktop.
- `[V]` 🔴 **Rutas huérfanas: `/mensual` y `/wrapped`.** Ambas están declaradas (`frontend/src/App.jsx:209` y `:224`) y sus páginas existen (`frontend/src/pages/Monthly.jsx`, `frontend/src/pages/Wrapped.jsx`, 604 líneas). Grepeando `to="/mensual"` / `navigate('/mensual')` / `/wrapped` en todo `frontend/src`: **cero enlaces**. Sólo se llega tipeando la URL. Y `frontend/src/data/planCatalog.js:19` vende "Wrapped anual" como feature del plan Free.
- `[V]` **`/guia` y `/planes` no están en el menú mobile.** `frontend/src/pages/More.jsx` no tiene ninguna entrada a ninguna de las dos (grep de `guia`/`planes` en el archivo: cero). En desktop `/guia` está en el footer del sidebar (`Sidebar.jsx:335`); en mobile sólo se llega desde links internos o desde la sección Planes de `/config`.
- `[V]` **`/ai` no tiene ítem de menú propio** en ninguno de los dos: se llega por el botón "Rendi AI" del sidebar (`Sidebar.jsx:234`), el ✦ de la topbar mobile (`MobileTopBar.jsx:90`) o el botón de `/mas` (`More.jsx:101`), todos vía `coachDrawer.open()`.
- `[V]` **`/objetivos` no está en ningún menú** (es redirect a `/posiciones?tab=objetivos`, `frontend/src/App.jsx:205`), pero `planCatalog.js:19` lo lista como feature.
- `[V]` Filtro muerto: `More.jsx:75` hace `g.items.filter(it => !it.adminOnly || user?.is_admin)` y **ningún ítem tiene la propiedad `adminOnly`** (el comentario de `:72` dice "ej. Fundamentals", que hoy es público). El filtro no filtra nada.

#### 🔴 Bug: los toasts de la sección mobile de notificaciones no aparecen nunca

`[V]` `useToast()` devuelve `{ push, dismiss }` (`frontend/src/components/Toast.jsx:48`, `:57-68`). No existe un método `show`. Sin embargo hay **9 call-sites** que llaman `toast?.show?.(...)`:

- `frontend/src/pages/More.jsx:230, 233, 236, 245, 247, 250` — toda la sección de push notifications: activar, desactivar, error, y el resultado del push de prueba.
- `frontend/src/pages/MobileSearch.jsx:134, 136`
- `frontend/src/pages/PositionsMobile.jsx:1785`

Como usan optional chaining (`?.`), **no tiran error: no hacen nada**. El usuario activa las notificaciones push, la suscripción se registra contra `POST /api/push/subscribe` (`frontend/src/hooks/usePushNotifications.js:134`), y **no recibe ninguna confirmación visual**; si falla, tampoco ve el error. Nótese además que en `PositionsMobile.jsx:1785` la firma usada es distinta (`show('texto', {variant})`) que en `More.jsx` (`show({kind, text})`), lo que sugiere que se copió de una API que nunca existió en este repo.

---

## PÁGINAS PÚBLICAS (marketing, SEO, legales)

### `/` sin sesión → `frontend/src/pages/Landing.jsx` (1560 líneas)

- **Qué muestra** (`frontend/src/pages/Landing.jsx:1543-1558`): `NavBar` → `Hero` → `BrokerTicker` → `LivePreview` (mock de dashboard "vivo") → `Features` → `HowItWorks` (con 5 mocks: posiciones, operaciones, insights, análisis, chat) → `BrokerSolutions` → `Pricing` → `FAQ` → `FounderBlock` → `CtaFinal` → `Footer` → `SupportWhatsAppFab`.
- **De dónde saca los datos**: `[V]` **una sola llamada real**: `fetch('/api/stats/public')` en `FounderBlock` (`:1251`), para el contador de inversores. El endpoint existe (`backend/main.py:34304`). Todo lo demás es contenido estático o simulado.
- **⚠️ Cálculos en el cliente**:
  - `useCountUp` anima el "8+" de brokers (`:43-59`, `:185`).
  - `LivePreview` **fabrica números** con un `wobble(base, amp)` senoidal que corre cada 2,2 s (`:220-230`): total US$48.217,42, aportado US$38.140, etc. Es un mock declarado como tal en el comentario (`:215-216`), pero **el usuario que llega desde Google ve una pantalla que parece un dashboard en vivo**.
  - `[V]` El contador de usuarios tiene umbral: sólo se muestra si `users >= 25` (`:1268-1270`); por debajo se cae a un texto sin número.
  - `[V]` La foto del fundador se pre-carga con `new Image()` y sólo se renderiza si `naturalWidth > 0` (`:1257-1260`), para que el fallback de la SPA (que devuelve index.html con 200) no deje una imagen rota.
- **Precios**: `[V]` importa `PLUS_PRICE_ARS_MONTHLY` y `PRO_PRICE_ARS_MONTHLY` de `./Planes` (`:15-19`) y los usa en `Pricing()` (`:1046`, `:1059`). **Comparte fuente con `/planes`** — acá no hay divergencia. La que sí hay es la del FAQ (ver abajo).
- **Estado/contexto**: ninguno. No usa `useAuth`.
- **Rarezas**:
  - `[V]` **La landing no tiene `<PageMeta>`.** Grep de `PageMeta` en el archivo: cero. Es deliberado (`frontend/src/components/PageMeta.jsx:3` dice *"El index.html define el title/description GLOBAL (que cubre la landing /)"*) y `frontend/index.html:24-25,39` los define. Pero como es una SPA con Helmet, `[I]` si el visitante navega a `/planes` y vuelve a `/` con el botón atrás, el `<title>` queda con el de `/planes` (no hay nada que lo restaure).
  - `[V]` `Terminal` está importado (`:9`) y no se usa en ninguna parte del archivo.
  - `[V]` `import { api } from '../utils/api'` (`:20`) y **no se usa** — el único fetch es crudo (`:1251`).
  - `[V]` Las anclas del `NavBar` (`#features`, `#live`, `#como-funciona`, `#pricing` — `:72-83`) y la del footer (`#faq`, `:1429`) resuelven bien: los ids están en `frontend/src/pages/Landing.jsx:381`, `:241`, `:506`, `:1025` y en `frontend/src/components/landing/FAQ.jsx:71`.

### `/planes` (público) → misma ficha que arriba

`[V]` Es la única página de "producto" indexable con `PageMeta` propio (`frontend/src/pages/Planes.jsx:350-354`, sin `noindex`) y está en el sitemap (`frontend/public/sitemap.xml`).

### FAQ de la landing → `frontend/src/components/landing/FAQ.jsx`

`[V]` Estático, 8 preguntas. **Hardcodea los precios como texto plano**: `'Cobramos en pesos argentinos a precio fijo. Plus $5.990 / Pro $13.990 por mes'` (`:55`). Es la quinta copia del precio de Pro en el repo y la única que no importa las constantes. También hardcodea el modelo de IA que se usa ("Claude Haiku 4.5", `:59`) y las cuotas de chat.

### `/blog` + 3 artículos → `frontend/src/pages/Blog.jsx`, `frontend/src/pages/blog/articles/`

- `[V]` **100 % estáticas**, cero llamadas a la API (verificado con grep de `api.`/`fetch(` sobre los 4 archivos: sin resultados).
- `[V]` El índice tiene un array `POSTS` con 3 entradas (`frontend/src/pages/Blog.jsx:19-44`) que hay que mantener sincronizado a mano con: el archivo del artículo, la ruta en `App.jsx:248-250` y el sitemap (el comentario lo dice en `:4-6`). Los tres posts tienen `publishedAt: '2026-05-24'`.
- `[V]` `PageMeta` propio en el índice (`:49-53`); cada artículo usa `frontend/src/components/blog/BlogPost.jsx`.

### `/guia` + 7 sub-páginas → `frontend/src/pages/Guia.jsx`, `frontend/src/pages/guia/`, `frontend/src/components/guide/`

- `[V]` **Estáticas**, sin llamadas a la API.
- `[V]` El índice adapta el contenido por tier: si `user?.tier === 'advisor'` antepone la sección "Para asesores" y usa las descripciones `descAsesor` de cada sección (`frontend/src/pages/Guia.jsx:85-87`, `:21-26`). O sea: **una página pública que lee `useAuth()`**.
- `[V]` `GuidePage` calcula el "N de M" en runtime según el tier — `${n+1} de 7` para asesor, `${n} de 6` para el resto (`frontend/src/components/guide/GuidePage.jsx:36-38`) — y emite `BreadcrumbList` JSON-LD (`:42-66`).
- `[V]` **`/guia/asesores` está fuera del sitemap.** La ruta existe y es pública (`frontend/src/App.jsx:259`, `:327`) y tiene canonical propio, pero `frontend/public/sitemap.xml` lista las 6 sub-páginas "normales" y no ésa.

### Landings de keyword → `frontend/src/pages/keywords/` (6) + `frontend/src/components/landing/KeywordLanding.jsx`

- `[V]` Seis páginas de 60-81 líneas cada una que sólo pasan props (`FEATURES`, `HOW_STEPS`, `RELATED`) al template `KeywordLanding`. **Estáticas.**
- `[V]` El template emite `PageMeta` + `BreadcrumbList` JSON-LD (`frontend/src/components/landing/KeywordLanding.jsx:49-79`) con `dangerouslySetInnerHTML` sobre un JSON armado en el cliente.
- `[V]` Hardcodean cuotas del producto en el copy: p. ej. `frontend/src/pages/keywords/Cocos.jsx:32` dice *"Pro: 40 consultas/sem"* (coincide con `PRO_FEATURES.quotas` de `frontend/src/data/planCatalog.js:85`, pero es otra copia a mano).

### `/terminos`, `/privacidad`, `/reembolso`

- `[V]` **Estáticas**, sin llamadas a la API. `PageMeta` propio en las tres. Fecha declarada: *"Última actualización: 3 de junio de 2026"* (`frontend/src/pages/Terminos.jsx:40`, `frontend/src/pages/Reembolso.jsx:47`).
- `[V]` 🔴 **Contradicen la implementación de precios** — ver el hallazgo de `/planes`. `frontend/src/pages/Terminos.jsx:213-215` y `frontend/src/pages/Reembolso.jsx:201-203` afirman que el ancla es USD y que el ARS varía día a día; el código cobra un ARS fijo hardcodeado.

---

## OTROS COMPONENTES DEL ALCANCE

### `frontend/src/components/ErrorBoundary.jsx`

`[V]` Class component montado **una sola vez, en la raíz** (`frontend/src/main.jsx:89-97`) — no hay boundaries por ruta, así que cualquier excepción de render tumba la app entera y muestra este cartel. Dos botones: recargar, y **"Limpiar datos guardados y recargar"** (`:80-83`) → `limpiarEstadoLocal()` (`:18-25`) hace `localStorage.clear()` + `sessionStorage.clear()` **preservando sólo `rendi_user`** para no desloguear. El comentario explica por qué existe (`:9-13`): el dato más peligroso es `rendi_client_ctx`, que hace que todos los pedidos vayan por la cuenta de otro usuario. La función está extraída para poder testearla (hay `frontend/src/components/errorBoundaryStorage.test.js`).

`[I]` Efecto colateral no documentado: ese `clear()` también borra las **preferencias financieras** (`rendi_display_currency`, `rendi_valuation_dollar`, `rendi_cost_basis`) y los flags de onboarding. Después de tocar el botón, la cartera vuelve a valuarse al default (USD MEP, costo a dólar de compra) sin avisar.

### `frontend/src/components/ShareCardModal.jsx`

`[V]` Orquesta el render de una tarjeta PNG con Canvas 2D (`frontend/src/utils/shareCard.js`). Invocado desde Behavioral y MonthlySummary. Tres acciones: descargar (`:61`), compartir nativo con fallback a descarga (`:73-87`) y copiar al portapapeles con `ClipboardItem`, también con fallback a descarga (`:89-109`). Trackea `share_card_generated` / `_downloaded` / `_shared` / `_copied`. Sin llamadas a la API — todo se genera en el browser.

`[V]` Rareza: el `useEffect` que renderiza la imagen depende **sólo de `source`**, no de `spec` (`:59`), con un eslint-disable y un comentario que dice que si el caller cambia la card debería re-montar el modal. Si dos tarjetas distintas se abren con el mismo `source`, se muestra la primera.

### `frontend/src/components/InvestorProfileForm.jsx`

`[V]` 8 preguntas (`:16-97`, el comentario del archivo dice 7 en `:1`). Guardado **optimista y automático**: cada click hace `POST /api/auth/investor-profile` con el objeto completo (`:113-124`); si falla, muestra el error pero **deja el estado local ya cambiado** (`setProfile(next)` en `:115` ocurre antes del try). `GET /api/auth/investor-profile` al montar (`:106`). El contador "N/8 respondidas" se calcula en el cliente (`:126`).

---

## Resumen de hallazgos de esta sección

**Bugs**

1. `frontend/src/pages/Config.jsx:956-960` — `irALasCardsDePlanes` se llama a sí misma en el `else`: recursión infinita (stack overflow) en vez del fallback de navegación que promete el comentario. 7 botones pasan por ahí.
2. `frontend/src/pages/VerifyEmail.jsx:104` — `padEnd(6, '')` no rellena nada: pegar menos de 6 dígitos deja el array corto y la UI renderiza menos de 6 cajas, con el botón Confirmar deshabilitado y sin forma de completar el código.
3. `frontend/src/pages/More.jsx:230-250` (+ `MobileSearch.jsx:134,136`, `PositionsMobile.jsx:1785`) — `toast?.show?.()` no existe (`useToast` devuelve `{push, dismiss}`, `frontend/src/components/Toast.jsx:48`): 9 toasts que nunca se muestran, incluida toda la confirmación de activar/desactivar push.
4. `frontend/src/components/mobile/MobileTabBar.jsx:34` — el tab "Insights" apunta a `/insights`, que redirige a `/analisis`: el indicador de tab activa nunca se enciende en esa sección.

**Divergencias de datos / contradicciones**

5. Precios: cuatro fuentes desalineadas — front ARS 13.990/139.900 (`frontend/src/pages/Planes.jsx:45,48`), backend ARS 12.100/123.420 (`backend/billing/pricing.py:51,57`), crédito en USD 9/90 (`backend/billing/credits.py:38-43`), y el cobro real en el dashboard de Rebill vía `REBILL_PLAN_ID_*` (`backend/billing/rebill.py:69-73`). `pricing.py` sólo lo lee la vía muerta de Mercado Pago (`backend/billing/mercadopago.py:111`).
6. Modelo de precio: "ARS fijo" (`frontend/src/components/landing/FAQ.jsx:55`) vs "al TC blue del día" (`frontend/src/pages/Planes.jsx:352,633`) vs "ancla en USD, convertido al TC del día" (`frontend/src/pages/Terminos.jsx:213-215`, `frontend/src/pages/Reembolso.jsx:201-203`).
7. `frontend/src/pages/Config.jsx:651` + `:963-965` — un asesor ve el hero de plan **Free** ("Mejorá a Pro", "Uso IA 0/6") justo encima del bloque que le dice "Tenés el Plan Asesor".

**Código muerto / promesas incumplidas**

8. `frontend/src/pages/Config.jsx:350-389` — `resetData()` completa, con polleo de progreso, sin ningún caller; el botón está `disabled` (`:591-598`).
9. `frontend/src/pages/Planes.jsx:129-136` — `tcValuacion` se fetchea (`GET /api/dolar`) y nunca se lee; el request se dispara también dentro de `/config?tab=planes`.
10. `frontend/src/pages/Onboarding.jsx:15-16` y `frontend/src/components/onboarding/CompleteStep.jsx:77` prometen un link "volver al onboarding desde Configuración" que no existe en `Config.jsx`.
11. `frontend/src/pages/Config.jsx:9` y `:896` prometen una sección "Notificaciones" que no está en `TABS` (`:46-52`).
12. Rutas huérfanas sin ningún enlace en el frontend: `/mensual` (`frontend/src/App.jsx:209`) y `/wrapped` (`:224`) — esta última vendida como feature en `frontend/src/data/planCatalog.js:19`.
13. `frontend/src/pages/More.jsx:75` — filtro `adminOnly` sobre una lista donde ningún ítem tiene esa propiedad.
14. `frontend/src/pages/Login.jsx:44` — estado `info` que nunca se setea.
15. Imports/constantes sin usar: `Mail`/`CalendarClock`/`Check` (`frontend/src/pages/Config.jsx:20`), `Terminal` y `api` (`frontend/src/pages/Landing.jsx:9`, `:20`), `TICKER_KEYS` (`frontend/src/components/mobile/MobileTopBar.jsx:19`), `Repeat` (`frontend/src/components/mobile/MobileTabBar.jsx:21`), `BarChart3` y `Target` (`frontend/src/pages/More.jsx:10-11`).
16. `frontend/src/pages/Planes.jsx:65-96` — bloque de exports deprecados (`PLUS_PRICE_USD`, `PRO_PRICE_USD`, `ARS_MONTHLY`, …) más `arsPriceRounded()` con un TC 1466 hardcodeado, todo todavía importable.

**Superficie de admin**

17. `frontend/src/pages/Admin.jsx:1658-1690` — el panel "Auditoría MtM" pega a `/api/insights/*` (dependencia `get_effective_user`, `backend/main.py:11839`, `:11562`), no a `/api/admin/*`: muestra la cartera **del propio admin**, no la de un usuario elegido.
18. ~20 endpoints `/api/admin/*` sin ninguna UI, incluidos `wipe-broker-data` (`backend/main.py:20273`) y `delete-snapshot` (`:18590`).
19. `frontend/src/pages/Admin.jsx:510-511` — el broadcast masivo no tiene protección de doble envío (los otros tres paneles de mail sí son idempotentes).
20. `frontend/src/pages/Admin.jsx:2411` + `:2072-2090` — el botón "Forzar" de la migración FX no saltea el filtro de verificación en rojo del cliente y encadena 2-3 `confirm()`.
21. `backend/main.py:26610` — el alta de suscripción inserta `amount_ars` con **0** literal: la base no registra el monto.
