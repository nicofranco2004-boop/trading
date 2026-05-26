# Onboarding Wizard — Implementación nocturna 2026-05-26

Wizard de bienvenida + checklist en home para nuevos users de Rendi, según el plan que validamos antes de que te durmieras.

---

## ✅ TL;DR

**5 commits aplicados en `main` y deployados en producción**:

```
5f2ff6e fix(onboarding): cerrar loop CSV import → wizard complete step
b25e9cf feat(ai-coach): markAIDiscovered en send para que checklist detecte uso
b319552 feat(onboarding): checklist persistente en Home (desktop + mobile)
2402653 fix(analytics): hardcode GA_ID (NO es del onboarding, viene de la sesión previa)
...   feat(onboarding): wizard de 4 steps para nuevos users
```

**Total**: 8 archivos nuevos + 4 modificados, ~900 líneas de código.

Bundle de producción: `index-BzoqVcbx.js` (verificado: contiene la ruta `/onboarding`).
Test directo a `https://rendi.finance/onboarding` devuelve 200 OK.

---

## 🎯 Lo que recibe un user nuevo ahora

### Flow completo desde signup hasta primera operación

1. **Landing** → click "Empezar gratis"
2. **`/login?mode=register`** → ingresa email/password
3. **Email con código OTP** → llega a su inbox
4. **`/verify-email`** → tipea el código de 6 dígitos
5. **`/onboarding`** ← **NUEVO** ← acá empieza el wizard

### Los 4 steps del wizard (`/onboarding`)

#### Step 1 — Welcome (10s)

- Icon violet + "Hola {nombre}, bienvenido a Rendi"
- Subtítulo: "En 2 minutos vamos a tener tu primera cartera funcionando"
- 3 mini-features highlights (Tu broker / Tu cartera / Coach IA)
- CTAs: **Empezar** (violet, primary) + **Saltar y explorar yo solo** (text-only)

#### Step 2 — Broker (30s)

- "¿Dónde tenés tu plata?"
- 8 chips populares con tag de mercado:
  - **Cocos Capital** (AR) · **IOL** (AR) · **Balanz** (AR) · **Bull Market** (AR)
  - **Schwab** (US) · **Interactive Brokers** (US)
  - **Binance** (Crypto) · **Lemon Cash** (Crypto)
- Botón "+ Otro broker (manual)" → input libre
- Radio buttons de moneda: ARS / USD / USDT (cada chip pre-llena la moneda sugerida)
- Botones: **Atrás** + **Continuar** (con loading state)
- POST `/api/brokers` → si 409 (broker duplicado del flow back/forward) sigue como OK; si 403 (cap free) muestra mensaje de upgrade

#### Step 3 — Position (1-2 min)

Selector inicial con 3 opciones (cards clickeables):

**A. Importar CSV** (recomendado, badge violet)
- Flag `rendi_onboarding_pending` en localStorage
- Navega a `/imports?from=onboarding`
- Cuando termine el import → ImportWizard lo lleva a `/bienvenida` (FirstInsight) → ese ahora detecta el flag y redirige a `/onboarding?step=complete` → cierre del loop

**B. Cargar manual** (form inline)
- Ticker (uppercase auto, autoCapitalize="characters")
- Cantidad (`inputMode="decimal"`)
- Precio promedio (`inputMode="decimal"`)
- Tip educativo sobre lotes múltiples y promedio
- POST `/api/positions` con `broker={brokerStep.name}`, `invested = qty × price`

**C. Lo hago después** (skip)
- Salta directo a step 4 con flag `skipped: true`

#### Step 4 — Complete (10-20s)

- Check verde + "Todo listo"
- Mensaje contextual:
  - Si cargó posición: "Tu posición en {ASSET} ya está en tu cartera"
  - Si saltó: "Cuando cargues tus posiciones vas a ver el dashboard cobrar vida"
- 3 action cards:
  - **Ver tu Insight** → `/insights` (con highlight violet si cargó posición)
  - **Coach IA** → abre el drawer del Coach
  - **Quiz de perfil** → `/perfil-inversor`
- CTA principal: **Ir a mi cartera** → `/dashboard`

### Header del wizard

- Logo Rendi + nombre
- "Saltar onboarding" siempre visible (excepto en step 4)
- ProgressBar arriba con pills horizontales + label del step actual
- Footer con escape hatch a Configuración

---

## 📋 Checklist persistente en Home (`OnboardingChecklist`)

Sección que aparece **arriba de todo** en Home (desktop + mobile) si el user no completó todos los items clave de configuración. Complementa el wizard one-time.

### Items trackeados

| # | Item | Detección |
|---|------|-----------|
| 1 | Sumá tu primer broker | `GET /brokers` → length > 0 |
| 2 | Cargá tu primera operación | `GET /positions` → length > 0 |
| 3 | Probá el Coach IA | localStorage flag `rendi_ai_discovered` |
| 4 | Quiz de perfil inversor | `GET /investor-profile` → !null |

### Comportamiento

- **Fetch en paralelo** al montar (3 endpoints)
- **Listener a `storage` events + focus** → reactivo si el user prueba el Coach en otro tab
- **Self-hides** cuando todos los items están done (sin necesidad de close manual)
- **Close manual**: botón X persiste `rendi_checklist_dismissed=1`
- Item "primera operación" está **disabled** si todavía no hay broker (forzar orden lógico)
- "Probá Coach IA" abre el AICoachDrawer directamente (no requiere navegar)

### Diseño

- Border violet sutil (`data-violet/30`) + bg `data-violet/[0.04]`
- Progress bar mini arriba con % completado
- Items con check verde (done) vs círculo gris (pendiente)
- Item done queda con `line-through` + cursor-default

---

## 🎨 Detalles de UX que vale la pena destacar

1. **Step 3 con 3 opciones explícitas** — el power user con CSV no tiene fricción; el que no tiene CSV no se queda trabado; el que quiere explorar primero también es bienvenido (no se le fuerza)

2. **Loop cerrado del CSV import** — antes de mi cambio, el user que elegía CSV terminaba en `/bienvenida` y no veía el "Listo" del onboarding. Ahora con el flag `rendi_onboarding_pending`, después del import vuelve a `/onboarding?step=complete`

3. **markAIDiscovered al primer chat send** — antes solo se marcaba si el user clickeaba el banner de descubrimiento o el botón ✦ inline. Ahora también al mandar mensaje al Coach desde el drawer, que es el path más natural

4. **Skip persistente** — si el user clickea "Saltar onboarding" no se le insiste de nuevo (flag `rendi_onboarding_skipped`)

5. **Checklist self-aware** — si el user cumple los 4 items por otro path (no por el wizard), el checklist se oculta solo cuando todos están done. No queda atado a si pasó por el wizard o no

6. **Inputs amigables mobile** — todos los campos numéricos con `inputMode="decimal"`, ticker con `autoCapitalize="characters"` + `autoCorrect="off"`, etc.

7. **Acessibilidad** — labels mono uppercase coherentes con el resto del producto, aria-label en buttons, focus visible

---

## 📊 Tracking GA4 + telemetry interno

### Wizard
- `onboarding_started` (param: `at_step` — para detectar si entró directo a complete vía CSV flow)
- `onboarding_step_completed` (param: `step` — welcome/broker/position/complete)
- `onboarding_skipped` (param: `at_step`)
- `onboarding_completed` (param: `had_position`)

### Checklist
- `checklist_viewed` (param: `items_done`)
- `checklist_item_clicked` (param: `item` — broker/position/ai/profile)
- `checklist_dismissed` (param: `items_done`)

Todos se mandan **doble**: a GA4 (via `trackEvent`) y al backend (via `track`). En GA4 ya podés ver:
- **Funnel exploration**: `onboarding_started → step 2 → step 3 → completed`. Para ver dónde se cae la gente.
- **Audiences**: "Users que saltaron en step 2" para campañas de re-engagement

---

## 📁 Archivos del cambio

### Nuevos (8)

```
frontend/src/pages/Onboarding.jsx                          196 líneas
frontend/src/components/onboarding/ProgressBar.jsx          47 líneas
frontend/src/components/onboarding/WelcomeStep.jsx          74 líneas
frontend/src/components/onboarding/BrokerStep.jsx          200 líneas
frontend/src/components/onboarding/PositionStep.jsx        249 líneas
frontend/src/components/onboarding/CompleteStep.jsx         91 líneas
frontend/src/components/home/OnboardingChecklist.jsx       212 líneas
ONBOARDING_REPORT_2026-05-26.md                            este archivo
```

### Modificados (4)

```
frontend/src/App.jsx                — Lazy import Onboarding + ruta /onboarding
frontend/src/pages/VerifyEmail.jsx  — Redirige a /onboarding tras signup OK
frontend/src/pages/Home.jsx         — Monta <OnboardingChecklist />
frontend/src/pages/HomeMobile.jsx   — Monta <OnboardingChecklist /> en mobile
frontend/src/pages/FirstInsight.jsx — Cierra loop CSV import → onboarding step complete
frontend/src/components/AICoach.jsx — markAIDiscovered al mandar mensaje
```

---

## 🧪 Cómo probarlo

### Path A: nuevo user (E2E real)

1. Logout (top right del sidebar)
2. Andá a `/login?mode=register`
3. Registrate con un email nuevo de prueba (podés usar `nico+test1@gmail.com`)
4. Verificá el código del mail
5. Debería redirigirte automático a `/onboarding`
6. Recorré el flow

### Path B: ver el wizard sin signup nuevo

1. En el browser (logueado), abrí DevTools → Console
2. Ejecutá:
   ```js
   localStorage.removeItem('rendi_onboarding_skipped')
   localStorage.removeItem('rendi_onboarding_completed')
   ```
3. Navegá manualmente a https://rendi.finance/onboarding
4. Vas a ver el wizard desde el step 1

### Path C: probar el checklist solo

1. Console:
   ```js
   localStorage.removeItem('rendi_checklist_dismissed')
   localStorage.removeItem('rendi_ai_discovered')
   ```
2. Recargá Home
3. Si tu cuenta de testeo ya tiene broker/positions/perfil/AI → el checklist no aparece. Para verlo, borrá un broker o usá una cuenta fresh.

---

## ⚠️ Limitaciones conocidas y posibles mejoras futuras

### 1. Detección de "user nuevo" es client-side

Hoy el wizard se gatilla solo desde `VerifyEmail.jsx` post-signup. Si un user nuevo de alguna manera salta esa pantalla (ej. paga sub y se loguea por primera vez sin pasar por verify), no ve el wizard.

**Mejora**: agregar al backend `/api/auth/me` el flag `needs_onboarding` derivado de `count(brokers) == 0 AND created_at > 1 día`. Front consulta y redirige si corresponde. **No urgente** porque el path normal es siempre por verify-email.

### 2. No hay "Repetir tour" desde Config

El user que terminó el wizard no tiene botón para volver a verlo. Si quiere repetirlo tiene que borrar los flags manualmente.

**Mejora trivial**: agregar en `Config.jsx` un link "Repetir bienvenida" que limpie los flags y navegue a `/onboarding`. Estimado: 10 min.

### 3. El step "Position manual" pide precio en la moneda del broker

Si el user tiene un broker ARS y carga manual NVDA.BA, espera que el precio sea en ARS. Pero el form no aclara explícitamente. Hoy el código asume que el user sabe (igual que en `/posiciones`). Funciona, pero podría agregar hint contextual.

### 4. No hay analytics de "qué broker pickearon"

El POST a `/brokers` solo trackea `step_completed`, no `broker_name`. Si quisiéramos saber qué broker es más popular entre nuevos users, hay que extender el tracking. **Trivial** pero no lo hice porque PII-adjacent (algunos users querrán privacidad).

### 5. Mobile UX: el wizard es responsive pero no testeado en device real

El layout es mobile-first con `sm:` breakpoints. Debería andar bien en iPhone SE / 13 / Android pero no lo testeé físicamente, solo en DevTools responsive. Recomiendo probar tras despertar.

---

## 📈 Cómo medir si funciona

Cuando GA4 tenga 1-2 semanas de data (hoy recién arranca a juntar), miralo:

1. **GA4 → Reports → Engagement → Events**
   - `onboarding_started` total vs `onboarding_completed` total
   - Ratio = **activation rate** (objetivo: >60%)

2. **GA4 → Explore → Funnel exploration**
   - Crear funnel: `sign_up` → `onboarding_started` → `step_completed (broker)` → `step_completed (position)` → `onboarding_completed`
   - Vas a ver el **paso donde más se cae la gente** y enfocás mejoras ahí

3. **Backend → admin → tabla `plan_events`**
   - Filtrar por `event_name IN ('onboarding_*', 'checklist_*')` y agrupar por día para ver tendencia

4. **Indicador a largo plazo**:
   - Users con `has_position=true` después de 7 días vs total signups
   - Si sube ≥ 15% del baseline previo → wizard está funcionando

---

## 🌅 Si querés afinar algo cuando despiertes

Tres mejoras que tengo identificadas pero no son críticas:

1. **Link "Repetir bienvenida" en Config** (10 min) — para users que se equivocaron y quieren volver
2. **Hint de moneda en step 3 manual form** (5 min) — "Si tu broker es ARS, el precio va en pesos"
3. **Skip-to-step en URL** (15 min) — para tu propio QA: `/onboarding?step=position` etc

¿O preferís pasar a otra cosa? Las opciones del audit que quedaron del Sprint:
- **Sentry** para error tracking client-side
- **Mobile UX hardening** (inputMode + alert→Toast en Positions mobile)
- **Performance** (memoization Insights, AI streaming)
- **A11y** (contrast text-ink-3, modal aria)

---

## 🚀 Producción

✅ Pusheado a `main` (5 commits)
✅ Deployado en `https://rendi.finance` (bundle `index-BzoqVcbx.js`)
✅ Build limpio sin errores ni warnings nuevos
✅ Ruta `/onboarding` responde 200 OK
✅ Tracking GA4 + telemetry interno listos

**Buenos días.** Si encontrás algo que no anda o querés cambiar copy/colores/orden de pasos, decime exactamente qué y lo ajusto. Si todo te gusta, listo — pasamos a la próxima.
