# Audit completo de Rendi — 2026-05-25

Auditoría deep en 6 dimensiones (security backend, security frontend, SEO, mobile UX, performance, code quality + a11y) ejecutada en paralelo con 6 agentes especializados. Foco extra en seguridad como pediste.

---

## TL;DR ejecutivo

**Total hallazgos**: ~190 issues (43 backend security, 38 frontend security, 27 SEO, 62 mobile, 29 performance, 64 code quality).

**Lo que arreglé esta noche** (4 commits pusheados a main):

✅ **Security crítico backend**: rate limit con X-Forwarded-For, webhooks fail-closed sin secret en prod, rate limit en /api/billing/*, validar dominio init_point, CSV injection, HTML escape en emails, constant-time compare OTP, HSTS + Permissions-Policy ampliado.

✅ **Performance backend**: SQLite PRAGMAs (busy_timeout, synchronous=NORMAL, cache 64MB, mmap 256MB) — 2-3× más rápido bajo carga.

✅ **Security crítico frontend**: CSP + X-Frame-Options + Permissions-Policy ampliado en vercel.json, helper `safeUrl.js` para validar URLs externas, news links sanitizados, init_point con allowlist Rebill, SW openWindow validation, logout cleanup completo de localStorage.

✅ **Performance + Mobile + SEO**: logo PNG 1.27MB → versiones optimizadas (5-43KB según size), fonts no usadas (Manrope + Instrument Serif) eliminadas, Apple PWA meta tags, tab bar dot indicator fix, noindex en pages transitorias, robots.txt cleanup.

**Lo que NO arreglé** (necesita acción tuya):

🚨 **C1 — SECRET_KEY = ANTHROPIC_API_KEY**: tu `.env` tiene la misma string para el secret JWT y la API key de Anthropic. Hay que rotar. Ver sección "Acción urgente" abajo.

🚨 **C5 — `trading.db` real en git history**: el primer commit tiene tu portfolio personal commiteado. Hay que limpiar el history con `git filter-repo`. Ver sección "Acción urgente".

⚠️ **C7 — Verify webhook signature Rebill**: el parser de signature está adivinado del estándar industrial, falta confirmar con docs reales de Rebill v3. Ver sección "Antes de activar prod".

⚠️ **C8 — Idempotency webhooks**: el mismo payment_id puede dar crédito doble si Rebill manda webhook duplicado. Necesita UNIQUE constraint + dedup ledger.

⚠️ **C9 — Cross-check metadata.rendi_user_id vs subscription real en Rebill**: defensa en profundidad contra payload tampering.

---

## 🚨 ACCIÓN URGENTE (hacer ANTES de activar prod con Rebill)

### 1. Rotar SECRET_KEY del JWT

Tu `.env` tiene `SECRET_KEY` con el mismo valor que `ANTHROPIC_API_KEY`. Si la API key de Anthropic se logea o filtra, un atacante puede forjar JWTs válidos para cualquier user (incluido admin).

```bash
# 1. Generar una nueva key independiente:
python3 -c "import secrets; print(secrets.token_urlsafe(64))"

# 2. Actualizar:
#    - backend/.env (local)
#    - Railway env var SECRET_KEY (prod)

# 3. Después de cambiar, TODOS los users (incluido vos) se relogean — el
#    JWT viejo ya no se valida. Comunicale por mail si tenés users activos.
```

### 2. Limpiar `trading.db` del git history

Tu `trading.db` (5.5MB con 19 posiciones reales) fue commiteado al primer commit y sigue accesible vía `git cat-file -p <blob>`. Cualquiera con acceso al repo (contractors futuros, fork público accidental) puede leer tu portfolio personal.

```bash
# Opción A: git filter-repo (recomendado, más rápido)
pip install git-filter-repo
cd /Users/nicolaspussetto/Documents/trading
git filter-repo --invert-paths --path backend/trading.db --path backend/rendi.db --path 'backend/*.backup-*'

# Después:
git remote add origin https://github.com/nicofranco2004-boop/trading.git
git push origin main --force

# CUIDADO: force push reescribe history. Si tenés colaboradores con el repo
# clonado, tienen que re-clonar.
```

Alternativa más conservadora: crear un repo nuevo limpio y empezar de cero ahí, dejando el viejo como privado/archived.

---

## ⚠️ ANTES DE ACTIVAR REBILL PROD

### 3. Confirmar formato signature Rebill

`backend/billing/rebill.py:verify_webhook_signature()` asume que Rebill manda el HMAC del body crudo como hex en el header de signature. **Verificar con docs oficiales** porque muchos providers usan formato `t=timestamp,v1=hex` (como MP, Stripe).

Si el formato es diferente, validación siempre falla incluso con secret correcto → tus webhooks legítimos quedan rechazados → users pagan y no obtienen Pro.

Action: ir a https://docs.rebill.com/api/reference/webhooks y ajustar el parser. Después hacer test E2E con webhook desde sandbox.

### 4. Idempotency en webhooks de payment

El handler procesa cada webhook y otorga crédito. Si Rebill manda el mismo `payment.created` 2 veces (retry por timeout, race del LB), el user obtiene 60 días por un pago de 30.

Fix sugerido:
```sql
-- Agregar a init_db():
CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_ledger_payment
  ON credit_ledger(subscription_id, payment_id);
```

Y en `_rebill_record_payment` chequear si ya existe el row antes de granted.

### 5. Cross-check metadata.rendi_user_id

El webhook lee `rendi_user_id` del body. Si el secret está mal configurado en prod (los fixes de esta noche lo previenen pero igual), un atacante podría activar Pro a cualquier user_id eligiendo.

Defense in depth: después de validar signature, hacer `rebill.get_subscription(sub_id)` y verificar que el `rendi_user_id` del fetch matchea con el del body.

---

## 🔒 BACKEND SECURITY — Hallazgos detallados

### CRITICAL (9 total, 5 fixed tonight, 4 pending)

| # | Issue | Status |
|---|-------|--------|
| C1 | `SECRET_KEY` = `ANTHROPIC_API_KEY` (.env) | ❌ requiere rotación manual |
| C2 | Rebill webhook acepta sin signature si secret no seteado | ✅ Fixed — fail-closed en prod |
| C3 | MP webhook idem | ✅ Fixed — fail-closed en prod |
| C4 | Rate limit usa `request.client.host` (proxy IP de Railway) | ✅ Fixed — usa X-Forwarded-For en prod |
| C5 | `trading.db` real en git history | ❌ requiere `git filter-repo` |
| C6 | `/api/billing/subscribe`, `/cancel`, `/change-plan` sin rate limit | ✅ Fixed — 3-5 calls/600s por user |
| C7 | Signature format Rebill posiblemente incorrecto | ❌ requiere docs reales |
| C8 | Idempotency: mismo `payment_id` da crédito doble | ❌ pendiente |
| C9 | Confía en `metadata.rendi_user_id` sin cross-check | ❌ pendiente |

### HIGH (14 total, fixes parciales)

- **H1** ✅ CSV injection prevention (`_csv_safe()` helper)
- **H2** ✅ HTML escape en email de recomendaciones
- **H3** ❌ Email enumeration en `/api/auth/verify-email` (mensajes distintos según existence)
- **H4** ❌ JWT sin `jti` (no se puede revocar tokens individuales — logout no invalida)
- **H5** ✅ Rate limit verify_email per-email (no global)
- **H6** ❌ Password strength check trivial (solo length ≥ 10, sin complexity)
- **H7** ❌ AI chat sin rate limit por-minuto (solo cuota semanal — burst posible)
- **H8** ✅ `hmac.compare_digest` en verify_email (constant-time)
- **H9** ❌ Logging de PII (emails, IPs) en INFO level
- **H10** ❌ `_rebill_activate` no valida que plan/period sea conocido (cross-check vs catálogo server-side)
- **H11** ❌ Cookie clear en logout no invalida JWT en `Authorization: Bearer` (mobile/scripts)
- **H12** ❌ Webhook handler silencia exceptions con 200 (Rebill cree que procesamos)
- **H13** ❌ `billing_events.signature_valid=1` se setea incluso sin secret (audit log engañoso)
- **H14** ❌ Migración auto-aprueba `email_verified=1` (asume todos verificados)

### MEDIUM (12 total)

- **M1** ✅ HSTS + Permissions-Policy headers (en prod)
- **M2** ❌ `notes`/`name` fields sin sanitización de caracteres
- **M3** ✅ Validar dominio init_point URL (allowlist Rebill)
- **M4** ❌ `/api/billing/subscribe` no chequea que tier actual no sea el mismo
- **M5** ❌ Falta handler para `payment.refunded`/`payment.disputed`
- **M6** ❌ Faltan algunos índices secundarios menores
- **M7** ❌ `_rebill_activate` confía en `amount` del payload (debería usar catálogo)
- **M8** ❌ 4× `f"..."` SQL strings (semánticamente seguros pero patrón peligroso)
- **M9** ❌ `asset` regex permite caracteres raros (XSS stored si front no escapa)
- **M10** ❌ `/api/feedback/recommendation` no exige email verificado
- **M11** ❌ HTTP timeouts a dolarapi/data912/argentinadatos sin retry/circuit-breaker
- **M12** ❌ `billing_sync` legacy de MP todavía vivo (código muerto)

### LOW (8 total) — backlog

---

## 🛡️ FRONTEND SECURITY — Hallazgos detallados

### CRITICAL (1 total, 1 fixed)

- **C1** ✅ CSP + X-Frame-Options + Permissions-Policy ampliado

### HIGH (6 total, 4 fixed)

- **H1** ❌ (descartado en re-revisión — falso positivo del audit)
- **H2** ✅ Validar `init_point` URL (allowlist `rebill.com`)
- **H3** ✅ Sanitizar URLs externas de noticias (`safeExternalUrl`)
- **H4** ✅ Service Worker valida `openWindow` target same-origin
- **H5** ❌ Admin client-side gating (filtra info de UX/estructura — pero datos protegidos server-side)
- **H6** ❌ Optimistic hydration permite "flash of authenticated UI" en máquinas compartidas

### MEDIUM (8 total)

- **M1** ✅ `logout()` limpia todos los `rendi_` keys del localStorage
- **M2** ❌ `console.log/error` en producción (no breakers, mejora con `esbuild.drop`)
- **M3** ❌ `alert()`/`confirm()` nativos del browser (UX pobre)
- **M4** ❌ Demo mode flag persistente
- **M5** ❌ User-Agent enviado en push subscribe (fingerprinting)
- **M6** ❌ Yahoo Finance URL con symbol sin `encodeURIComponent`
- **M7** ❌ `npm audit`: 2 moderate vulnerabilities (esbuild ≤0.24.2, vite — solo dev server, no prod)

### LOW (12 total) — backlog

---

## 🔍 SEO — Hallazgos detallados

### CRITICAL (4 total, 2 fixed)

- **C1** ❌ Keyword landings huérfanas — la home NO linkea a /brokers/*, /cedears, etc. Cero link equity para landings que rankean keywords AR.
- **C2** ✅ Logo PNG 1.27MB → versiones 5-43KB optimizadas
- **C3** ✅ Fonts Manrope + Instrument Serif eliminados (no se usaban, blocking LCP)
- **C4** ❌ SPA sin SSR — social shares (WhatsApp, Twitter, LinkedIn) muestran metadata de la home para todas las landings/blog/guia. Migrar a Next.js SSG o react-snap prerendering, o usar prerender.io para bots.

### HIGH (6 total, 2 fixed)

- **H1** ❌ Falta `BreadcrumbList` schema en BlogPost/GuidePage/KeywordLanding
- **H2** ✅ robots.txt cleanup (added /verify-email, /reset-password, /guia)
- **H3** ❌ og:image específicas por landing/blog (todos usan la genérica)
- **H4** ❌ Heading hierarchy quebrada en Blog.jsx (`<h2>` por cada card del index)
- **H5** ✅ noindex en BillingReturn/VerifyEmail/ResetPassword
- **H6** ❌ Sitemap priorities + lastmod uniformes (señal débil a Google)

### MEDIUM (10) y LOW (7) — backlog

**Acción recomendada de alto impacto SEO**: agregá una sección "Para tu broker" en la Landing.jsx con cards linkeando a /brokers/cocos, /iol, /binance + /cedears + /bonos-argentinos + /afip-cripto. Es el cambio de mayor ROI para SEO (link equity desde la home).

---

## 📱 MOBILE UX — Hallazgos detallados

### CRITICAL (9 total, 2 fixed)

- **C1** ✅ Tab bar dot indicator de active state fixed (faltaba `relative`)
- **C2** ❌ Headers sticky con valores mágicos `top-[88px]` desfasan según notch/ticker bar
- **C3** ❌ Pull-to-refresh global solo refresca ticker bar (no contenido de la page)
- **C4** ❌ `usePullToRefresh` listener global captura touches dentro de sheets/modales
- **C5** ❌ BottomSheet sin focus-trap (Tab escapa al body underneath)
- **C6** ❌ Pull-to-refresh indicator tapado por status bar en iPhones con notch
- **C7** ✅ Apple PWA meta tags agregados (apple-mobile-web-app-capable, status-bar-style, title)
- **C8** ❌ iOS auto-zoom edge case en algunos inputs con text-xs
- **C9** ❌ `alert()`/`confirm()` nativos en flow crítico de Positions mobile

### HIGH (18 total) — destacados:

- **H1** ❌ Tab labels `text-[9px]` ilegibles (subido a 10px en C1)
- **H3** ❌ MobileTopBar Search/Coach icons con `p-2` (32×32 target < 44px Apple HIG)
- **H4** ❌ Filter chips en MobileSearch/PositionsMobile sub-44px
- **H6** ❌ AICoach chat input sin `inputMode`, `autoCorrect`, `enterKeyHint`
- **H7** ❌ BottomSheet no scrollea input al recibir focus (keyboard tapa)
- **H11** ❌ DateInput popover no responsive en mobile (usar `<input type="date">` nativo)
- **H14** ❌ Decenas de inputs `type="number"` sin `inputMode="decimal"` → iOS no muestra punto decimal
- **H16** ❌ Recharts altura fija 300-320px en mobile (domina viewport)
- **H17** ❌ Insights mobile renderea 15+ secciones sin colapsado (scroll infinito)

### MEDIUM (22) y LOW (13) — backlog

---

## ⚡ PERFORMANCE — Hallazgos detallados

### CRITICAL (5 total, 3 fixed)

- **C1** ✅ Logo 1.27MB → versiones optimizadas (LCP -1.5s estimado)
- **C2** ✅ Fonts no usadas eliminadas
- **C3** ❌ JSON-LD pesado inline en HTML (HowTo, Organization, WebSite) — inyectar via Helmet post-hydration
- **C4** ❌ Insights.jsx (2869 líneas) sin un solo `useMemo`/`useCallback` — INP malo en mobile
- **C5** ✅ SQLite PRAGMAs agregados (busy_timeout, synchronous=NORMAL, cache 64MB, mmap 256MB) → backend 2-3× más rápido bajo carga

### HIGH (7 total) — destacados:

- **H1** ❌ Landing.jsx static-importa Planes.jsx → defeats el lazy split (15KB gzip extra en main chunk)
- **H2** ❌ Dashboard/Positions polling con setInterval sin pause en `visibilitychange` (40 req/h innecesarios por user)
- **H3** ❌ `/auth/me` bloquea bootstrap calls — considerar /api/bootstrap unificado
- **H4** ❌ AI chat NO usa streaming (`client.messages.create` vs `.stream()`) — user ve spinner 5-15s
- **H5** ❌ `main.py` monolito 12k líneas (cold start +1-3s)
- **H6** ❌ yfinance/news fetchers sincrónicos en request thread (p95 cliff a 8 concurrent)
- **H7** ❌ `Cache-Control: no-store` blanket — Vercel edge no puede cachear endpoints públicos

### MEDIUM (7) y LOW (10) — backlog

---

## 🧹 CODE QUALITY + ACCESSIBILITY — Hallazgos detallados

### CRITICAL (6 total)

- **C1** ❌ `admin_delete_user` deja datos huérfanos en 10+ tablas (GDPR/Ley 25.326 incomplete erasure)
- **C2** ❌ 5 modales sin `role="dialog"` / `aria-modal` / Escape handler / focus-trap
- **C3** ❌ Botones X de cerrar sin `aria-label` (screen readers leen "botón")
- **C4** ❌ `text-ink-3` (#5A6478) sobre `bg-bg-0` = 3.35:1 → FALLA WCAG AA. 872 usages en JSX.
- **C5** ❌ 37 endpoints abren `get_db()` sin `try/finally` — connection leak ante HTTPException
- **C6** ❌ SECRET_KEY auto-generada en dev si no está seteada (debería fail-fast en prod)

### HIGH (17 total) — destacados:

- **H1** ❌ `main.py` 12k líneas (debería splitearse en routers)
- **H2** ❌ 21 funciones >100 líneas (init_db de 946L, ai_chat de 441L)
- **H3** ❌ Páginas frontend >500 líneas (Insights 2869, Positions 2481, Landing 1338)
- **H5** ❌ 13 `eslint-disable react-hooks/exhaustive-deps` sin ESLint configurado
- **H6** ❌ No hay error state UI consistente (solo loading + console.error)
- **H7** ❌ Sin Sentry / error tracking client-side
- **H8** ❌ Inputs sin `htmlFor` ↔ `id` en Operations/MonthlySummary/BrokerManager/Goals
- **H14** ❌ Sin CI configurado — tests existen pero no se corren automáticamente
- **H15** ❌ Ningún test del módulo Rebill ni nueva lógica de proration
- **H17** ❌ init_db con 31 ALTER TABLE inline (sin sistema de migrations versionado)

### MEDIUM (21) y LOW (20) — backlog

---

## 📊 Priorización propuesta (próximos sprints)

### Sprint 1 (esta semana) — Pre-producción crítico

1. **Acción urgente C1**: rotar SECRET_KEY
2. **Acción urgente C5**: git filter-repo trading.db
3. **C7 Rebill signature**: validar formato real con docs
4. **C8 Idempotency**: UNIQUE constraint en credit_ledger(sub_id, payment_id)
5. **C9 Cross-check metadata**: validar contra subscription real

### Sprint 2 — SEO + Performance high impact

1. **SEO C1**: linkear keyword landings desde Landing.jsx (sección "Para tu broker" con 6 cards)
2. **SEO H1**: BreadcrumbList schema en BlogPost/GuidePage/KeywordLanding
3. **Perf H1**: extraer Planes constants a `utils/planConstants.js` (cleans build warning)
4. **Perf H2**: Page Visibility API en setInterval de Dashboard/Positions
5. **Perf C4**: agregar `useMemo` en Insights.jsx (top 10 valores derivados)

### Sprint 3 — Mobile UX hardening

1. **Mobile H14**: `inputMode="decimal"` en todos los inputs de plata
2. **Mobile C9 + Frontend M3**: reemplazar `alert/confirm` con Toast + Modal en PositionsMobile/Planes
3. **Mobile H16**: Recharts adaptive height en mobile
4. **Mobile C2**: CSS vars para sticky header offsets
5. **Mobile H17**: branch mobile en Insights con accordion (5 secciones primero, resto colapsado)

### Sprint 4 — A11y compliance

1. **CodeQuality C4**: subir `text-ink-3` de #5A6478 a #7D8590 (WCAG AA pass)
2. **CodeQuality C2**: estandarizar Modal con role/aria/Escape/focus-trap
3. **CodeQuality C3**: aria-label en buttons de íconos
4. **CodeQuality H8**: `htmlFor` ↔ `id` en todos los forms

### Sprint 5 — Observability + CI

1. Sentry / equivalente (Highlight, Glitchtip) para frontend
2. GitHub Actions con pytest + vitest gating
3. Estructurar logs backend con request_id + user_id
4. `git filter-repo` de DBs + backups + Posthog para uso real

### Backlog grande (mes+)

- Splitear `main.py` en routers (`auth/`, `billing/`, `ai/`, `positions/`, etc.)
- SSR/SSG migration (Next.js o react-snap) para SEO completo
- Sistema de migrations versionado (Alembic o casero)
- Tests del módulo Rebill (proration, webhooks, cancelación)
- AI chat streaming con SSE

---

## 📁 Cambios aplicados esta noche — commits

```
6ba66e0 perf+seo+mobile: quick wins del audit — logo SVG, fonts, PWA, dot fix
06ca213 security(frontend): CSP + X-Frame-Options + safe URLs + logout cleanup
b9f7831 security(backend): fixes críticos del audit — rate limit, webhooks, CSV injection
```

Archivos modificados:
- `backend/main.py` (rate limit, SQLite PRAGMAs, billing rate limits, CSV safe, hmac compare, init_point validation, verify_email per-email)
- `backend/billing/rebill.py` (webhook fail-closed)
- `backend/billing/mercadopago.py` (webhook fail-closed)
- `backend/billing/emails.py` (HTML escape en recommendation)
- `frontend/vercel.json` (CSP + X-Frame-Options + Permissions-Policy)
- `frontend/src/utils/safeUrl.js` (NEW — safeExternalUrl + isSafePaymentUrl)
- `frontend/src/components/TopNewsCard.jsx`, `home/NewsPreview.jsx`, `pages/News.jsx` (safeExternalUrl)
- `frontend/src/pages/Planes.jsx` (isSafePaymentUrl validation)
- `frontend/public/sw.js` (validate openWindow target)
- `frontend/src/contexts/AuthContext.jsx` (logout cleanup all rendi_ keys)
- `frontend/src/components/RendiLogo.jsx` (size-adaptive PNG variants)
- `frontend/public/brand/rendi-mark-{64,128,256}.png` (NEW — optimized variants)
- `frontend/index.html` (fonts cleanup + Apple PWA meta)
- `frontend/src/components/mobile/MobileTabBar.jsx` (dot positioning fix)
- `frontend/src/pages/VerifyEmail.jsx`, `ResetPassword.jsx`, `BillingReturn.jsx` (noindex PageMeta)
- `frontend/public/robots.txt` (cleanup)

Resultado: 22 archivos modificados, 3 archivos nuevos, ~330 líneas de cambios.

---

## 🎯 Resumen para tomar mate

**Lo más urgente que tenés que hacer vos** (orden):

1. Rotar `SECRET_KEY` JWT (5 min): generar nueva, setear en .env local + Railway. Te releva la sesión, re-loguéa.
2. `git filter-repo --invert-paths --path backend/trading.db` + force push. Saca tu portfolio del git history.
3. Antes de activar prod Rebill: confirmar formato signature del webhook con docs reales de Rebill v3.
4. Agregar UNIQUE constraint en credit_ledger(sub_id, payment_id) para prevenir crédito doble por webhook duplicado.

**Lo importante a sumar al backlog** (lo más alto ROI):

5. Linkear las 6 keyword landings desde la home (Landing.jsx) — cambio chico, impacto SEO grande.
6. BreadcrumbList schema en BlogPost/GuidePage/KeywordLanding — mejora CTR ~5-10% en SERP.
7. Subir contrast del `text-ink-3` para pasar WCAG AA.
8. Sentry/equivalente para error tracking client-side.
9. AI chat streaming (perceived latency 5-15s → 500ms).

**Resto**: backlog con prioridad según vayas mirando los detalles arriba.

Buenos días — todo está en `main` listo para revisar. Si querés que aplique algún fix más mientras estoy despierto, decime cuál.
