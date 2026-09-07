## 5. Autenticación, autorización, planes y cuotas

Todo lo de este capítulo vive prácticamente en un solo archivo: `backend/main.py` (38.029 líneas). El gating por plan se reparte entre `backend/ai/quota.py` (tiers + cuotas de IA), `backend/ai/plan.py` (features), y `backend/billing/{trial,credits,subscriptions,pricing}.py`. El frontend consume todo eso por `/api/plan/features` y `/api/auth/me`.

---

### 5.1 El token

| Qué | Cómo es realmente | Dónde |
|---|---|---|
| Tipo | JWT (`python-jose`) | `backend/main.py:2681-2689` |
| Algoritmo | `HS256` | `backend/main.py:115` |
| Secreto | env var **`SECRET_KEY`** | `backend/main.py:100` |
| Expiración | **7 días** (`TOKEN_DAYS = 7`) | `backend/main.py:116` |
| Claims | `sub` (user_id como string), `iat`, `exp`, y opcionalmente `pca` | `backend/main.py:2682-2688` |
| Transporte | **cookie primero, header como fallback** | `backend/main.py:2697-2701` |
| Nombre de la cookie | `rendi_token` | `backend/main.py:148` |

**[V] El secreto falla cerrado en prod.** Si `SECRET_KEY` no está seteada y `RENDI_ENV=prod`, el proceso **no bootea** (`RuntimeError`, `backend/main.py:105-109`). En dev genera una key efímera por proceso y avisa por stdout (`backend/main.py:112-113`). El comentario explica el porqué: con key efímera y >1 worker, el token del worker A lo rechaza el worker B.

**[V] Flags de la cookie** (`backend/main.py:151-160`):

```python
response.set_cookie(
    key=COOKIE_NAME, value=token,
    max_age=TOKEN_DAYS * 86400,
    httponly=True,
    secure=_COOKIE_SECURE,      # True SOLO si RENDI_ENV == 'prod' (línea 149)
    samesite="lax",
    path="/",
)
```

- `HttpOnly`: **sí**, siempre.
- `Secure`: **condicional a `RENDI_ENV=prod`** (`backend/main.py:149`). En dev va sin Secure a propósito (HTTP local).
- `SameSite`: **`lax`**. [I] Esto es lo que hace de anti-CSRF de facto — no hay ningún token CSRF en la app; busqué `csrf` en `backend/main.py` y `frontend/src/utils/api.js` y **no encontrado**. Con `Lax` el browser no manda la cookie en POST cross-site, así que los POST/PATCH/DELETE están cubiertos; una navegación GET top-level cross-site **sí** lleva la cookie, pero no encontré endpoints GET que muten estado salvo los crons con token propio (ver 5.9).

**[V] Orden de resolución en `get_current_user`** (`backend/main.py:2692-2719`): primero `request.cookies.get("rendi_token")`; si no hay, cae al `Authorization: Bearer` (`HTTPBearer(auto_error=False)`, `backend/main.py:140`). Después de decodificar hace un `SELECT id, password_changed_at FROM users WHERE id=?` — o sea, **una query a la DB por request autenticado**.

**[V] Los endpoints de login/registro devuelven el token TAMBIÉN en el body** (`backend/main.py:3225`, `3319-3325`, `3455-3459`), por back-compat con clientes no-browser. El frontend web lo ignora (`frontend/src/utils/api.js:5-11`) y borra el `rendi_token` de localStorage si quedó de una versión vieja (`frontend/src/utils/api.js:13-17`).

---

### 5.2 Invalidación de sesión (`pw_changed_at` / claim `pca`)

**[V] El mecanismo.** `create_token` mete el claim `pca` con el valor de `users.password_changed_at` (`backend/main.py:2687-2688`). `get_current_user` compara (`backend/main.py:2716-2717`):

```python
pca = payload.get("pca")
if pca and row["password_changed_at"] and pca != row["password_changed_at"]:
    raise HTTPException(401, "Token expirado por cambio de contraseña")
```

Los **tres** lugares que bumpean `password_changed_at` y por lo tanto matan las sesiones viejas (los grepeé todos: no hay un cuarto):

| Acción | Línea |
|---|---|
| `POST /api/auth/reset-password` | `backend/main.py:3440-3443` |
| `POST /api/auth/change-password` | `backend/main.py:3578-3581` |
| `POST /api/auth/claim` (cliente reclama la cuenta shadow) | `backend/main.py:35155-35159` |

En los tres casos se emite un token nuevo y se re-setea la cookie, así que la sesión que hizo el cambio sobrevive.

**[V] HALLAZGO — hay un agujero de un solo lado en la invalidación.** El `if` de arriba exige que **las dos** puntas tengan valor. Si el token se emitió cuando `users.password_changed_at` era `NULL`, el payload sale **sin** `pca` (`backend/main.py:2687`: `if pw_changed_at:`), y entonces el chequeo se saltea entero: `pca` es `None` → cortocircuita el `and`. Un cambio de contraseña posterior **no** invalida ese token, que sigue vivo hasta su `exp` (7 días).

¿Puede haber filas con `password_changed_at NULL`? Sí:
- El `CREATE TABLE` sí tiene default (`backend/main.py:719`: `password_changed_at TEXT DEFAULT (datetime('now'))`).
- Pero la migración para bases viejas agrega la columna **sin default** (`backend/main.py:782`: `ALTER TABLE users ADD COLUMN password_changed_at TEXT`), y **no encontré** ningún backfill (`UPDATE users SET password_changed_at = ...` para filas NULL) en todo `backend/`.
- El esquema Postgres sí trae default en las dos formas (`backend/schema_pg.sql:1725` y `:1760`), así que [I] en Postgres el ALTER pone default y probablemente no queden NULLs; en la SQLite histórica sí pueden quedar.

[I] O sea: el agujero es acotado a cuentas anteriores a la migración que nunca cambiaron la contraseña. No pude medir cuántas son (no hago SELECT de datos de usuarios).

**[V] `logout` no invalida nada server-side.** `POST /api/auth/logout` (`backend/main.py:3231-3238`) solo hace `delete_cookie`. El propio docstring lo dice: *"Para clientes que usan Bearer header, esto es no-op server-side"*. No hay denylist de JTI, no hay `jti` en el payload, y no hay tabla de sesiones. La única forma de matar un Bearer robado es cambiar la contraseña.

**[V] Granularidad de un segundo.** `password_changed_at` se escribe con `datetime('now')` (segundos). Dos cambios en el mismo segundo producen el mismo valor. [I] No es explotable de forma práctica.

---

### 5.3 Admin

**[V] Cómo se determina, en dos capas.**

1. **Quién es "el email admin"**: no está en plano, se compara por hash SHA-256 con `hmac.compare_digest` (`backend/main.py:131-134`):

```python
def _is_admin_email(email: str) -> bool:
    h = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
    return hmac.compare_digest(h, ADMIN_EMAIL_HASH)
```

   El hash hardcodeado es `_ADMIN_EMAIL_HASH = "3dace40c…48b74d"` (`backend/main.py:126`), overrideable por la env var **`ADMIN_EMAIL_HASH`** (`backend/main.py:128`).

   **Emails admin hardcodeados**: hay **uno solo**, y el propio comentario del código lo escribe en claro dos líneas arriba del hash (`backend/main.py:125`): *"El email real es nicofranco2004@gmail.com pero solo se sabe por el hash"*. O sea, el hash no oculta nada — el email está en el repo, en el comentario. Lista completa: **`nicofranco2004@gmail.com`**.

2. **El flag persistido**: `users.is_admin`. Se escribe en dos lugares y **solo** en dos:
   - En el registro, si el email matchea (`backend/main.py:3098` + `3113`).
   - En cada boot, `init_db` recorre **todos** los users y promueve al que matchee (`backend/main.py:913-917`): `UPDATE users SET is_admin=1, approved=1 WHERE id=?`.

   No hay endpoint para otorgar `is_admin` a otro usuario — grepeé `SET is_admin` y solo aparece esa línea 916. [V]

**[V] El guard**: `get_admin_user` (`backend/main.py:2721-2726`) depende de `get_current_user` y hace un `SELECT is_admin`; si no, **403 "Acceso restringido"**. Lo usan **47 endpoints** `/api/admin/*`.

**[V] El frontend NO es un guard**: `/admin` está montada sin wrapper de protección (`frontend/src/App.jsx:233`), y `Admin.jsx` solo esconde el contenido con `if (!user?.is_admin)` (`frontend/src/pages/Admin.jsx:195`). El gate real es el backend, que está bien puesto.

**[V] Contradicción documentada.** El admin **no** es asesor. `_require_advisor` lo dice explícitamente (`backend/main.py:2823-2831`):

```python
def _require_advisor(conn, uid: int) -> str:
    """… tier 'advisor' de verdad — is_admin NO alcanza …"""
    tier = _q.get_tier(conn, uid)
    if tier != "advisor":
        raise HTTPException(403, "Requiere el plan Asesor")
```

Pero el comentario de cabecera de toda la sección del Plan Asesor dice lo contrario: *"gatean por `_require_advisor` (tier 'advisor' **o admin**)"* (`backend/main.py:34339`). El comentario está **desactualizado**: `quota.get_tier` devuelve `'admin'` para un admin sin override de tier (`backend/ai/quota.py:219`), y `'admin' != 'advisor'` → 403. Un admin puro **no puede** entrar a `/api/advisor/*`.

---

### 5.4 Verificación de email, reset de password, rate limiting

#### 5.4.1 Verificación de email (OTP de 6 dígitos)

**[V] Flujo real** (`backend/main.py:3094-3332`):
- `POST /api/auth/register` **no devuelve token** para usuarios no-admin: devuelve `{"needs_verification": True, …}` y manda el código por `BackgroundTask` (`backend/main.py:3153-3163`).
- El admin **se auto-verifica** y recibe token directo (`backend/main.py:3111`: `email_verified = 1 if is_admin_signup else 0`; token en `3169-3170`).
- TTL del código: **15 minutos** (`EMAIL_CODE_TTL_MINUTES = 15`, `backend/main.py:2912`).
- Cooldown de reenvío: **60 segundos** (`EMAIL_CODE_RESEND_COOLDOWN_SECONDS = 60`, `backend/main.py:2913`).
- Comparación del código con `hmac.compare_digest` (`backend/main.py:3272`).
- `POST /api/auth/login` bloquea con **403 `EMAIL_NOT_VERIFIED`** si `email_verified == 0` (`backend/main.py:3203-3208`).
- El gate de aprobación manual del admin **ya no existe** — `approved` se escribe siempre en 1 y no bloquea el login (`backend/main.py:3110` y el comentario en `3209-3211`).

**[V] HALLAZGO — se puede obtener una sesión válida sin verificar nunca el email.** `POST /api/auth/reset-password` (`backend/main.py:3412-3466`) valida el token de reset, actualiza la contraseña y **emite token + setea la cookie** (`backend/main.py:3454-3455`) **sin mirar `email_verified` y sin ponerlo en 1**. Y `get_current_user` tampoco chequea `email_verified` nunca (`backend/main.py:2692-2719`).

Consecuencia concreta: alguien que se registra, nunca pone el código OTP, y después hace *"olvidé mi contraseña"* → recibe el magic link → resetea → **queda logueado con cookie válida de 7 días** y `users.email_verified` sigue en 0. A partir de ahí:
- Toda la app le funciona (ningún endpoint mira `email_verified`).
- Pero si cierra sesión, **no puede volver a entrar por login** (403 `EMAIL_NOT_VERIFIED`).
- Y el free trial se le niega con `reason="email_not_verified"` (`backend/billing/trial.py:295-296`).

[I] No es escalada de privilegios (el que resetea probó control del inbox, que es lo mismo que prueba el OTP), pero deja la cuenta en un estado mixto: sesión sí, login no, trial no.

#### 5.4.2 Reset de password

**[V]**
- TTL del link: **30 minutos** (`PASSWORD_RESET_TTL_MINUTES = 30`, `backend/main.py:2914`).
- Token: `secrets.token_urlsafe(32)` ≈ 43 chars, ~256 bits (`backend/main.py:2943-2945`).
- Un solo link vivo: al pedir uno nuevo se marcan usados los anteriores (`backend/main.py:3379-3383`).
- **Respuesta siempre genérica**, exista o no el email (`backend/main.py:3403-3407`) — no hay enumeración de usuarios por acá.
- La URL base sale de `_frontend_url()` (`backend/main.py:2919-2937`), que prioriza la env var **`MP_FRONTEND_BASE_URL`** y en prod cae a `https://rendi.finance` (nunca localhost — el comentario documenta el bug real de un usuario que recibió `http://localhost:5173/reset-password`).

#### 5.4.3 Rate limiting

**[V] La implementación** (`backend/main.py:395-410`): store **en memoria del proceso**, `defaultdict(list)` de timestamps, con cap de 10.000 claves y limpieza perezosa (`backend/main.py:309-310`). El comentario lo admite: *"Per-process. Para multi-worker o multi-host conviene migrar a Redis"*.

[V] El arranque es **un solo worker** de uvicorn, sin `--workers` (`nixpacks.toml:31`), así que hoy el store es efectivamente global por instancia. [I] Si Railway escala horizontalmente o alguien agrega `--workers N`, todos los límites se multiplican por N en silencio.

**[V] La clave del límite** es la IP resuelta por `_ip_del_cliente` (`backend/main.py:369-387`), que **solo confía en `X-Forwarded-For` si `RENDI_ENV == "prod"`** y usa `RENDI_TRUSTED_PROXY_HOPS` para contar saltos desde la derecha; sin esa var elige la última IP pública de la cadena.

**Límites concretos, endpoint por endpoint** (todos verificados con `grep -n "_check_rate_limit("`):

| Endpoint | Límite | Clave | Línea |
|---|---|---|---|
| `POST /api/auth/register` | 5 / 5 min | IP | `main.py:3102` |
| `POST /api/auth/login` | 10 / 60 s | IP | `main.py:3191` |
| `POST /api/auth/login` | 10 / 60 s | IP+email | `main.py:3192` |
| `POST /api/auth/verify-email` | 5 / 60 s | IP+email | `main.py:3250` |
| `POST /api/auth/resend-verification` | 1 / 60 s | IP+email | `main.py:3340` |
| `POST /api/auth/resend-verification` | 5 / 3600 s | IP+email | `main.py:3341` |
| `POST /api/auth/forgot-password` | 5 / 5 min | IP | `main.py:3366` |
| `POST /api/auth/forgot-password` | 3 / 3600 s | IP+email | `main.py:3368` |
| `POST /api/auth/reset-password` | 10 / 5 min | IP | `main.py:3419` |
| `GET /api/auth/link-request/preview` | 20 / 5 min | IP | `main.py:34998` |
| `POST /api/auth/link-request/respond` | 15 / 5 min | IP | `main.py:35041` |
| `GET /api/auth/claim/preview` | 20 / 5 min | IP | `main.py:35065` |
| `POST /api/auth/claim` | 10 / 5 min | IP | `main.py:35111` |
| `POST /api/ai/analyze` | 10 / 60 s | IP+uid | `main.py:25913` |
| `POST /api/ai/chat` | 12 / 60 s | IP+uid | `main.py:28295` |
| `POST /api/billing/subscribe` | 5 / 10 min | IP+uid | `main.py:26527` |
| `POST /api/billing/change-plan` | 3 / 10 min | IP+uid | `main.py:26665` |
| `POST /api/billing/cancel` | 5 / 10 min | IP+uid | `main.py:27318` |
| `POST /api/wallbit/connect` | 6 / 60 s | IP+uid | `main.py:31241` |
| `POST /api/advisor/clients` | 30 / 60 s | IP+uid | `main.py:34377` |
| `POST /api/advisor/clients/{id}/invite` | 10 / 5 min | IP+uid | `main.py:34696` |
| `POST /api/advisor/reports/generate` | 6 / 5 min | IP+uid | `main.py:35947` |
| `GET /api/reports/public/{token}` | 30 / 5 min | IP | `main.py:36013` |
| `POST /api/advisor/group-op` | 10 / 60 s | IP+uid | `main.py:36296` |

**[V] Nota sobre el rate limit "por email":** la clave es `f"{ip}|login_email:{email}"` — o sea, **IP + email**, no email solo (`backend/main.py:397`: `key = f"{ip}|{suffix}"`). El docstring dice *"mitiga brute-force distribuido sobre una cuenta puntual"* (`backend/main.py:3190`), pero como la IP entra en la clave, un atacante distribuido con N IPs tiene N×10 intentos por minuto sobre la misma cuenta. El límite por email **no** es global.

**[V] `POST /api/billing/trial/start` no tiene rate limit** (`backend/main.py:26365-26385`). No es grave: el `UPDATE … WHERE trial_used_at IS NULL` lo hace idempotente (`backend/billing/trial.py:344-357`).

#### 5.4.4 Otros controles de auth

**[V] Contraseñas**: bcrypt vía `passlib` (`backend/main.py:135`), mínimo **10 caracteres**, máximo 128 (`backend/main.py:2861-2874`). No hay chequeo de complejidad ni de contraseñas filtradas. En login fallido por usuario inexistente se llama `pwd_ctx.dummy_verify()` (`backend/main.py:3196`) para no filtrar por timing.

**[V] Historial de logins**: `_record_login_and_maybe_alert` (`backend/main.py:3219`) — el User-Agent se guarda **hasheado** y se manda mail de alerta si el dispositivo es nuevo (`backend/main.py:2953-2960`).

**[V] `ALLOW_REGISTRATION`**: env var; con `false` solo el admin puede registrarse (`backend/main.py:99` + `3100-3101`). Default `true`.

**[V] CORS** (`backend/main.py:238-266`): origins explícitos (prod: `https://rendi.finance,https://www.rendi.finance`), `allow_credentials=True`, `allow_methods=["GET","POST","PUT","DELETE"]`, `allow_headers=["Authorization","Content-Type"]`.
Dos cosas que **no cierran** con la app tal como está:
- **`PATCH` no está en `allow_methods`**, y hay 7 rutas PATCH (`/api/positions/group`, `/api/alerts/{id}`, `/api/advisor/groups/{id}`, `/api/advisor/alerts`, `/api/advisor/brief/prefs`, `/api/advisor/clients/{client_uid}`, `/api/advisor/profile`).
- **`X-Rendi-Client-Id` no está en `allow_headers`**, y es el header que el frontend inyecta en cada request del Plan Asesor (`frontend/src/utils/api.js:104`).
[I] Hoy no rompe nada porque en prod el frontend pega a rutas relativas y Vercel proxea server-side (el propio comentario del código lo dice, `backend/main.py:238-241`): el browser nunca cruza origin. Rompería si alguien le pegara directo al dominio de Railway desde un browser.

**[V] Headers de seguridad** (`backend/main.py:269-289`): `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, `Cache-Control: no-store`, y HSTS solo en prod. **No hay `Content-Security-Policy`** — no encontrado en `backend/main.py`.

**[V] Docs deshabilitadas**: `FastAPI(title="Rendi", docs_url=None, redoc_url=None)` (`backend/main.py:167`).

---

### 5.5 TIERS

**[V] Los cinco tiers que existen** (`backend/ai/quota.py:56`):

```python
Tier = Literal["free", "plus", "pro", "advisor", "admin"]
```

**[V] Cómo se resuelve el tier — `quota.get_tier`** (`backend/ai/quota.py:148-221`). Precedencia real, en orden:

1. **Cuenta administrada sin reclamar** (`managed_by IS NOT NULL AND approved = 0`) → **`'pro'`** (`quota.py:181-188`). Es el cliente shadow que solo ve el asesor.
2. **`pro_trial_until` en el futuro** → **`'pro'`** (`quota.py:198-203`). Es la "prueba de Pro encima de un plan pago" (el Plus que quiere ver Pro). Va por arriba del override pago y no lo toca.
3. **`users.tier` ∈ {`pro`,`plus`,`advisor`}** → ese valor, **salvo** que `_paid_override_expired` diga que el crédito venció y no hay sub `authorized`, en cuyo caso cae a `'admin'` (si `is_admin`) o `'free'` (`quota.py:208-215`). Esta es la red de seguridad en tiempo real que no depende del cron.
4. **`users.tier == 'free'`** → `'free'`.
5. **`is_admin = 1`** → **`'admin'`** (`quota.py:219`).
6. Fallback → `'free'`. Y **todo el bloque está envuelto en `try/except: pass`** (`quota.py:220-221`): cualquier error de DB devuelve `'free'` — falla cerrado.

**[V] Cuotas de IA por tier** (`backend/ai/quota.py:70-119`). Ventana **móvil de 7 días** (no semana ISO), con piso por cambio de plan (`_window_floor`, `quota.py:265-330`):

| | free | plus | pro | advisor | admin |
|---|---|---|---|---|---|
| `analyses_per_week` | 1 | 6 | 60 | 60 | 1000 |
| `hub_queries_per_week` | 0 | 0 | 60 | 60 | 1000 |
| `chat_per_week` | 1 | 9 | 40 | 40 | 1000 |
| `diag_dismiss_per_week` | 2 | ∞ | ∞ | ∞ | ∞ |

**[V] Features por tier** (`backend/ai/plan.py:45-134`):

| | free | plus | pro | advisor | admin |
|---|---|---|---|---|---|
| `brokers_max` | 1 | 3 | ∞ | ∞ | ∞ |
| `alerts_max` | 3 | 25 | ∞ | ∞ | ∞ |
| `insights_diagnostic_visible` | 3 | 6 | ∞ | ∞ | ∞ |
| `behavioral_tags_visible` | 3 | 6 | ∞ | ∞ | ∞ |
| `ai.followup` | ✗ | ✗ | ✓ | ✓ | ✓ |
| `ai.hub` | ✗ | ✗ | ✗ | ✗ | ✓ |
| `comportamiento.full` | ✗ | ✗ | ✓ | ✓ | ✓ |
| `insights.distribucion_activo` | ✗ | ✓ | ✓ | ✓ | ✓ |
| `reportes.historicos` | ✗ | ✓ | ✓ | ✓ | ✓ |
| `export.csv` | ✗ | ✓ | ✓ | ✓ | ✓ |
| `tax.helper` | ✗ | ✗ | ✗ | ✗ | ✓ |
| `alerts.pct_move` | ✗ | ✓ | ✓ | ✓ | ✓ |

#### 5.5.1 Tabla feature → ¿backend y frontend coinciden?

Esta es la tabla que pide el capítulo. La columna que importa es la última.

| Feature | Tier mínimo | Gate en BACKEND | Gate en FRONTEND | ¿Coinciden? |
|---|---|---|---|---|
| Crear broker (`brokers_max`) | plus (>1) | ✅ `plan.check_broker_quota` en `POST /api/brokers` — `backend/main.py:4061` | `usePlanFeatures().limits.brokers_can_create` | **Sí**, salvo el caso del asesor (ver abajo) |
| Crear alerta (`alerts_max`) | plus (>3) | ✅ `_plan.check_alert_quota` — `backend/main.py:33440` | `frontend/src/components/alerts/AlertsManager.jsx` | **Sí** |
| `alerts.pct_move` | plus | ✅ `_plan.can_access(…, "alerts.pct_move")` — `backend/main.py:33445` | `frontend/src/components/alerts/AlertsManager.jsx:76` | **Sí** |
| `export.csv` | plus | ✅ `_gate_export` → `plan.can_access` — `backend/main.py:13300-13329`, aplicado en los 4 endpoints `/api/export/*` | `frontend/src/components/plan/ExportCsvButton.jsx:28`, `frontend/src/pages/PositionsMobile.jsx:2854` | **Sí** |
| Chat libre de IA | pro | ✅ whitelist de 12 preguntas para free/plus — `backend/main.py:28380-28407` (403 `free_chat_not_allowed`) | UI de preguntas guiadas | **Sí** |
| `ai.followup` | pro | ✅ 403 si `tier in ("free","plus")` — `backend/main.py:25949-25963` | `frontend/src/hooks/useAIAnalysis.js` | **Sí** |
| Cuotas de IA (análisis/chat) | todos | ✅ `quota.can_analyze` / `reserve_chat` (reserva atómica) | badge de uso | **Sí** |
| `reportes.historicos` | plus | ❌ **no encontrado**. `GET /api/reports/timeline` (`backend/main.py:33072`) y `GET /api/reports/period/{type}/{key}` (`backend/main.py:33136`) usan solo `Depends(get_effective_user)`, sin gate de plan | `frontend/src/pages/Reports.jsx:221` (`plan.can('reportes.historicos')`) | **NO** — gate solo en el cliente |
| `comportamiento.full` / `behavioral_tags_visible` | pro / plus | ❌ **no encontrado**. `GET /api/behavioral/insights` (`backend/main.py:13760`) devuelve **todos** los detectores sin mirar tier | `frontend/src/pages/Behavioral.jsx:686` (`limit('behavioral_tags_visible') \|\| 1`) | **NO** — gate solo en el cliente |
| `insights.distribucion_activo` | plus | ❌ **no encontrado** | ❌ **no encontrado** — el id aparece solo en `frontend/src/utils/demo.js:2912`, en el comentario de `frontend/src/hooks/usePlanFeatures.js:10` y en textos de marketing (`planCatalog.js`, `UpgradeModal.jsx`) | **Ninguno de los dos** — flag declarado y servido que nadie lee |
| `insights_diagnostic_visible` | plus | ❌ **no encontrado** | ❌ **no encontrado** (no hay `limit('insights_diagnostic_visible')` en `frontend/src`) | **Ninguno de los dos** |
| `ai.hub` | admin | ❌ no hay endpoint de Hub (grep de rutas: 0 resultados con "hub"); `can_hub_query` / `record_hub_query` de `backend/ai/quota.py:411-418` y `:439-449` **no tienen call sites** en `main.py` | ❌ | Feature **inexistente** — código muerto |
| `tax.helper` | admin | ❌ no construido (el propio comentario lo dice, `backend/ai/plan.py:58`) | ❌ | Feature **inexistente** |
| Plan Asesor (`/api/advisor/*`) | advisor | ✅ `_require_advisor` en los 33 endpoints (ver 5.7) | `frontend/src/pages/AdvisorClients.jsx:112` (`user?.tier === 'advisor'`) | **Sí** |

**[V] HALLAZGO — tres features "pagas" se pueden obtener pegándole al endpoint.** `reportes.historicos` y las 12 tags de `comportamiento` están gateadas **solo en el frontend**. Un usuario Free logueado que llame `GET /api/reports/timeline?months=120` o `GET /api/behavioral/insights` recibe el dato completo. No es fuga de datos de otro (es su propia cartera), pero **es el paywall que no cierra** en dos de las features que la app vende como Plus/Pro (las mismas que enumera el mensaje de upsell del gate de brokers, `backend/main.py:4076`).

**[V] HALLAZGO — divergencia frontend/backend en el "lente Pro" del asesor.** `GET /api/plan/features` fuerza `tier_override="pro"` cuando hay contexto de cliente (`backend/main.py:26469-26471`), así que la UI del asesor dentro de un cliente muestra **brokers ilimitados y alertas ilimitadas**. Pero:
- `_gate_export` **sí** tiene la escapatoria del asesor (`backend/main.py:13310-13312`: si el `rendi_auth_uid` distinto del uid resuelto tiene tier `advisor`, pasa).
- `plan.check_broker_quota` (`backend/main.py:4061`) y `_plan.check_alert_quota` (`backend/main.py:33440`) **no la tienen**: resuelven el tier de la cuenta mirada.

Consecuencia: sobre un cliente **reclamado** (que tras el claim resuelve `'free'`, ver 5.7.4), la UI del asesor le ofrece crear el segundo broker y el backend le contesta **403 "El plan Free permite 1 broker"**. Sobre un cliente shadow no pasa (resuelve `'pro'` por `quota.py:181-188`).

---

### 5.6 TRIAL (`backend/billing/trial.py`, 1.200 líneas)

**[V] Cuántos días y cómo está armado** (`backend/billing/trial.py:1-27`, `:38-40`):

```
día 1-7   → pro    (TRIAL_PRO_DAYS  = 7)
día 8-15  → plus   (TRIAL_PLUS_DAYS = 8)
día 16    → free
```
Total **15 días** (`TRIAL_TOTAL_DAYS`).

**[V] Qué escribe al activar** (`_start_tx`, `backend/billing/trial.py:331-357`), en un solo UPDATE condicional:

```sql
UPDATE users SET tier='pro', credit_active_until=?,      -- arranque + 15 días, TODO de una
                 quota_window_from=date('now','localtime'),
                 trial_started_at=?, trial_used_at=?, trial_ends_at=?,
                 credit_anchor_plan=NULL, credit_anchor_period=NULL,
                 credit_anchor_amount_usd=NULL, credit_anchor_at=NULL
 WHERE id=? AND trial_used_at IS NULL
   AND (credit_active_until IS NULL OR credit_active_until <= ?)
```

Dos decisiones de diseño explícitas y bien argumentadas en los comentarios:
- **`credit_active_until` se graba a 15 días desde el arranque, no a 7**: si el cron del step-down falla, el usuario se queda **de más** en Pro en vez de quedarse sin acceso. El error cae siempre a favor del usuario (`backend/billing/trial.py:20-23`).
- **Los anchors se limpian**: si quedaba pegado el anchor de una suscripción vieja, `get_credit_state` valuaba los 15 días gratis como plata real y "cambiar de plan" los convertía en 41 días de Plus (`backend/billing/trial.py:338-343` — el comentario dice "audit: plata fabricada, reproducido").

**[V] Cómo se decide si venció — dos mecanismos distintos, no uno:**

1. **Día 8 (pro → plus): el cron.** `step_down_due_trials` (`backend/billing/trial.py:481-560`) baja a `tier='plus'` a los que cumplan **todas** estas: `tier='pro'`, `trial_started_at` ≤ hoy−7 **por fecha** (no por instante), `credit_active_until > now`, `trial_ends_at IS NOT NULL`, **`credit_active_until = trial_ends_at`** (esto es lo que distingue el crédito del trial de un regalo o un pago) y sin sub `authorized`. También estampa `quota_window_from = hoy` para que los 60 análisis de la semana Pro no se le descuenten del techo de 6 de Plus.
2. **Día 16 (plus → free): nadie lo ejecuta, se deduce.** El crédito vence y `quota.get_tier` devuelve `free` **en tiempo real** vía `_paid_override_expired` (`backend/ai/quota.py:122-146`, llamado en `:212`). El cron `_downgrade_expired_credit` (`backend/billing/subscriptions.py:161-240`) además limpia `users.tier = NULL` cuando pasa, pero el acceso ya estaba cortado sin él.

**[V] Qué pasa al vencer**: `users.tier = NULL`, fila en `credit_ledger` con `kind='expiration'`, y un aviso al admin — separando "prueba que terminó" de "cliente que se fue" para no tapar la señal de churn (`backend/billing/subscriptions.py:145-159` y `:225-231`).

**[V] Qué es `trial_consumed`.** Es una **tabla propia** (no una columna). El motivo está escrito (`backend/billing/trial.py:220-224`): *"borrar la cuenta borra la fila de users — y con ella `trial_used_at`, lo que habilitaba trials infinitos con el mismo mail"*. Guarda `email_key` (hash SHA-256 del email normalizado) + `consumed_at` (`backend/billing/trial.py:236-243`). Se consulta en `_email_consumed` (`backend/billing/trial.py:220-234`) y se escribe dentro de la misma transacción del alta (`backend/billing/trial.py:358`).

**[V] Cómo se evita que alguien lo repita — cuatro capas:**

1. **`users.trial_used_at`** — el `WHERE … AND trial_used_at IS NULL` del UPDATE lo hace idempotente y atómico contra dos requests simultáneos (`backend/billing/trial.py:353`, `:358`).
2. **`trial_consumed`** — sobrevive al borrado de la cuenta.
3. **Normalización del email** (`normalizar_email`, `backend/billing/trial.py:190-210`): corta el `+alias` en **todos** los dominios, y en Gmail/Googlemail además borra los puntos y unifica `googlemail.com → gmail.com`. El propio docstring reconoce el límite: *"No pretende frenar a un decidido con dos casillas de verdad: corta el abuso trivial, que es el que escala"*.
4. **Tope mensual global** (`TRIALS_MONTHLY_CAP`, `backend/billing/trial.py:52-59`). Cuando hay tope, el conteo y la inserción van en **un solo statement** contra `credit_ledger` (`backend/billing/trial.py:369-383`), porque `eligibility()` es check-then-act: el comentario documenta que *"con tope 5 y 20 pedidos simultáneos entraron los 20"*. Si no entra, se levanta `_TopeDelMes` y el `with conn` **deshace el alta entera**.
   - `_activations_this_month` cuenta sobre el **ledger append-only**, no sobre `users` (borrar la cuenta no devuelve cupo), y normaliza el separador de fecha con `substr(replace(created_at,'T',' '),1,10)` — porque el espacio de SQLite ordena antes que la `T` de Python y *"con tope 3 entraron 8 trials el día 1"* (`backend/billing/trial.py:62-86`).
   - Si el conteo falla, devuelve `10**9` → **fail-closed**, no se activa.

**[V] Resto de las exclusiones de `eligibility`** (`backend/billing/trial.py:262-308`): admin (`not_applicable` — le bajaría los límites), `tier == 'advisor'` o `managed_by IS NOT NULL` (`not_applicable`), sub `authorized` (`already_paying`, y `_has_paid_sub` **falla cerrado**: ante error devuelve `True`, `backend/billing/trial.py:248-260`), crédito vigente (`already_premium`), email sin verificar (`email_not_verified`), `TRIALS_ENABLED=false` (`disabled`).

**[V] Interruptores por env var**: `TRIALS_ENABLED` (default on) y `TRIALS_MONTHLY_CAP` (default 0 = sin tope). Apagar el trial **no** corta los que ya están corriendo (`backend/billing/trial.py:43-49`).

**[V] Los endpoints del trial usan `get_current_user` a propósito, no `get_effective_user`** (`backend/main.py:26366`, `:26388`, `:26428`): *"el trial es de la persona que está logueada. Un asesor mirando la cuenta de un cliente no puede activarle un trial sin querer desde el contexto"*.

**[V] Mecanismo aparte: "probar Pro sin dejar el Plus que ya pagás"** (`backend/billing/trial.py:790-880`). `PRO_UPSELL_DAYS = 7`, marcado con `users.pro_trial_until` / `pro_trial_used_at`, sin tocar `tier` ni `credit_active_until` ni los anchors. Vence solo (lo lee `get_tier` en `backend/ai/quota.py:198-203`). Solo elegible si el crédito vigente tiene `credit_anchor_plan == 'plus'` (`backend/billing/trial.py:833-838`).

---

### 5.7 AUTORIZACIÓN DEL ASESOR — lo más importante

#### 5.7.1 El mecanismo de la "vista como cliente"

**[V] Es un HEADER, no un query param: `X-Rendi-Client-Id`** (`backend/main.py:2764`).

La cadena completa:

```
frontend/src/utils/api.js:104
    if (_clientCtx?.id) headers['X-Rendi-Client-Id'] = String(_clientCtx.id)
        ↓
backend/main.py:2806  get_effective_user(request, creds)
        ↓
backend/main.py:2818  uid = get_current_user(...)      # identidad REAL
backend/main.py:2822  request.state.rendi_auth_uid = uid  # se stashea el uid real
backend/main.py:2823  client_uid = _resolve_client_context(request, uid)
        ↓
backend/main.py:2767-2803  _resolve_client_context
```

**[V] La función de chequeo, citada entera** — es `_resolve_client_context`, `backend/main.py:2767-2803`. No existe ningún `_assert_client` ni `_advisor_can` (grepeados, **no encontrado**); la validación vive acá y en `_advisor_own_link` / `_advisor_client_ids`:

```python
def _resolve_client_context(request: Request, uid: int) -> Optional[int]:
    raw = request.headers.get(CLIENT_CTX_HEADER)
    if not raw:
        return None
    path = request.url.path
    # Match por LÍMITE DE SEGMENTO: '/api/me' exime '/api/me' y '/api/me/...'
    # pero NO un futuro '/api/metrics' (startswith crudo lo eximiría en silencio).
    if any(path == p or path.startswith(p + "/") for p in CLIENT_CTX_EXEMPT_PREFIXES):
        return None
    try:
        client_id = int(str(raw).strip())
    except (TypeError, ValueError):
        raise HTTPException(400, "X-Rendi-Client-Id inválido")
    if not (0 < client_id < 2**63):
        raise HTTPException(400, "X-Rendi-Client-Id inválido")
    if client_id == uid:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT permission FROM advisor_clients
               WHERE advisor_uid=? AND client_uid=? AND status='active'""",
            (uid, client_id),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(403, "Sin acceso a ese cliente")   # nunca fallback silencioso
    if request.method not in ("GET", "HEAD", "OPTIONS") and row["permission"] != "read_write":
        raise HTTPException(403, "Acceso de solo lectura a ese cliente")
    return client_id
```

**Respuesta directa a la pregunta del capítulo: SÍ, el backend verifica que el cliente sea del asesor.** El `WHERE advisor_uid=? AND client_uid=? AND status='active'` corre en **cada request** que lleve el header, contra `advisor_clients`, que es la tabla de autorización (`backend/main.py:841-857`). Y lo hace bien en los tres puntos que importan:
- Sin vínculo → **403 explícito**, nunca degrada en silencio al uid propio (el comentario de `main.py:2743-2745` explica que eso *"enmascararía bugs del frontend mostrando datos del asesor como si fueran del cliente"*).
- Escrituras exigen `permission='read_write'`; los vínculos `'linked'` con `permission='read'` son solo lectura.
- El header se valida como entero y con rango de `INTEGER` de SQLite (sin eso, un valor gigante daba `OverflowError` → 500).

**[V] Los prefijos exentos** (`backend/main.py:2747-2758`) — acá el header se **ignora** y devuelve siempre el uid real del asesor:

```
/api/auth      /api/billing   /api/admin   /api/advisor
/api/me        /api/push      /api/plan/track   /api/feedback
```

**[V] `/api/ai` NO está exento a propósito** (`backend/main.py:2759-2762`): la IA sigue el contexto, y los contadores de cuota corren en la cuenta del **cliente**, no del asesor. El código anota que F5 va a centralizar el pool en el asesor.

**[V] El comentario del propio código marca el riesgo estructural** (`backend/main.py:2763-2764`):

> `⚠️ FAIL-OPEN: todo endpoint futuro FUERA de estos prefijos hereda el contexto de cliente. Si agregás un endpoint de IDENTIDAD/CUENTA/PAGO nuevo, agregalo acá.`

**[V] HALLAZGO — ya hay un endpoint de credenciales que cayó del lado fail-open.** `POST /api/wallbit/connect` usa `Depends(get_effective_user)` (`backend/main.py:31238-31239`) y `/api/wallbit` **no está** en los prefijos exentos. Sus cuatro rutas (`connect`, `sync`, `disconnect`, `status`) heredan el contexto de cliente. Un asesor con vínculo `read_write` puede **conectar y desconectar la API key del broker Wallbit en la cuenta del cliente** (la key se guarda cifrada con Fernet derivado de `SECRET_KEY`, `backend/main.py:31014-31019`). Para un shadow que el asesor administra es probablemente el comportamiento buscado; para un cliente **reclamado** (cuenta independiente, con su login propio) es un endpoint de credenciales operado por un tercero. Comparar con `/api/iol/lab/*`, que sí usa `get_current_user` (`backend/main.py:31490`, `:31531`, `:31544`).

#### 5.7.2 ¿Todos los endpoints de asesor usan el chequeo?

Revisé los **33** endpoints `@app.*("/api/advisor/…")` uno por uno. Resultado:

| Endpoint | Línea | Gate |
|---|---|---|
| `GET /api/advisor/twr` | 33698 | `_require_advisor` (33707) |
| `GET /api/advisor/data-health` | 33715 | `_require_advisor` (33723) |
| `GET /api/advisor/groups` | 33730 | `_require_advisor` (33735) |
| `POST /api/advisor/groups` | 33751 | `_require_advisor` (33755) |
| `PATCH /api/advisor/groups/{id}` | 33776 | `_require_advisor` (33781) |
| `DELETE /api/advisor/groups/{id}` | 33807 | `_require_advisor` (33811) |
| `POST /api/advisor/groups/preview` | 33836 | `_require_advisor` (33841) |
| `GET /api/advisor/groups/{id}/clients` | 33852 | `_require_advisor` (33856) |
| `GET /api/advisor/alerts` | 33880 | `_require_advisor` (33885) |
| `POST /api/advisor/alerts/events/seen` | 33896 | `_require_advisor` (33902) |
| `PATCH /api/advisor/alerts` | 33911 | `_require_advisor` (33915) |
| `GET /api/advisor/brief/preview` | 33979 | `_require_advisor` (33984) |
| `GET /api/advisor/brief/prefs` | 33998 | `_require_advisor` (34002) |
| `PATCH /api/advisor/brief/prefs` | 34011 | `_require_advisor` (34015) |
| `POST /api/advisor/clients` | 34370 | `_require_advisor` (34381) + cap 500 |
| `GET /api/advisor/reports` | 34419 | `_require_advisor` (34426) + `WHERE r.advisor_uid = ?` |
| `GET /api/advisor/clients` | 34465 | `_require_advisor` (34474) |
| `PATCH /api/advisor/clients/{cid}` | 34578 | `_require_advisor` (34589) + **`_advisor_own_link`** (34590) |
| `POST /api/advisor/clients/{cid}/revoke` | 34609 | `_require_advisor` (34616) + `_advisor_own_link` (34617) |
| `POST /api/advisor/clients/{cid}/invite` | 34690 | `_require_advisor` (34700) + `_advisor_own_link` (34701) |
| `GET /api/advisor/radar/events` | 35307 | `_require_advisor` (35315) |
| `GET /api/advisor/radar/news` | 35373 | `_require_advisor` (35381) |
| `GET /api/advisor/profile` | 35900 | `_require_advisor` (35904) |
| `PATCH /api/advisor/profile` | 35910 | `_require_advisor` (35914) |
| `POST /api/advisor/reports/generate` | 35943 | `_require_advisor` (35952) + filtro por `links` (35965-35967) |
| `POST /api/advisor/reports/{id}/revoke` | 36039 | `_require_advisor` (36050) + `WHERE id=? AND advisor_uid=?` (36053-36054) |
| `GET /api/advisor/group-op/prep` | 36092 | `_require_advisor` (36113) |
| `POST /api/advisor/group-op` | 36292 | **indirecto**, ver abajo |
| `POST /api/advisor/group-op/{batch}/undo` | 36584 | `_require_advisor` (36592) + `WHERE id=? AND advisor_uid=?` (36594-36595) |
| `GET /api/advisor/book` | 36947 | `_require_advisor` (36968) |
| `GET /api/advisor/book/composition` | 37661 | `_require_advisor` (37677) |
| `GET /api/advisor/book/asset-clients` | 37795 | `_require_advisor` (37819) |
| `GET /api/advisor/book/history` | 37883 | `_require_advisor` (37900) |
| `GET /api/advisor/book/detail` | 37944 | `_require_advisor` (37960) |
| `GET/POST /api/advisor/brief/run-cron` | 33936 | **cron token**, no auth de usuario (ver 5.9) |

**El único que NO llama `_require_advisor` en su propio cuerpo es `POST /api/advisor/group-op`** (`backend/main.py:36292-36300`). Lo revisé y **no es un agujero**: delega en `_advisor_group_op_apply`, que lo hace en su primera línea (`backend/main.py:36190`) y además vuelve a resolver los vínculos `read_write` con una query propia (`backend/main.py:36193-36198`), descartando a `sin vínculo activo` y `vínculo de solo lectura` fila por fila (`backend/main.py:36222-36228`). Es el mismo core que usa el registro grupal por chat, que a su vez tiene su propio gate `_q.get_tier(conn, uid) != "advisor"` (`backend/main.py:36399`).

**[V] Ningún endpoint de asesor deriva la lista de clientes de un parámetro HTTP.** Los que necesitan el roster usan `_advisor_client_ids(conn, uid)` (`backend/main.py:36695-36701`), que es `SELECT client_uid FROM advisor_clients WHERE advisor_uid=? AND status='active'`. El único que acepta `client_uids` por body es `POST /api/advisor/reports/generate`, y ahí cada id se cruza contra el dict `links` construido del roster; los que no matchean van a `skipped: "sin vínculo activo"` (`backend/main.py:35966-35968`). El docstring de `book/composition` incluso lo declara: *"La lista de clientes se DERIVA de la DB con `_advisor_client_ids` — nunca se acepta por HTTP"* (`backend/main.py:37671-37672`).

**Conclusión de esta parte: no encontré ningún endpoint de asesor que se saltee el chequeo de propiedad del cliente.** La superficie está sólida.

#### 5.7.3 HALLAZGO — el vínculo sobrevive al plan: el asesor vencido sigue entrando a las carteras

Este es el hallazgo importante de la sección, y no está en `/api/advisor/*` sino en el resolver.

**[V] `_resolve_client_context` (`backend/main.py:2767-2803`) NO consulta el tier.** Solo pregunta si existe la fila `advisor_clients` activa. `_require_advisor` (que es el que exige `tier == 'advisor'`) **solo protege los endpoints `/api/advisor/*`** — o sea el libro, el roster, los informes, el block trade.

**[V] Nada en billing revoca los vínculos.** Grepeé `advisor_clients` en `backend/billing/` y `backend/ai/`: **cero** resultados (el único match es un comentario en `backend/ai/quota.py:177`). `_downgrade_expired_credit` (`backend/billing/subscriptions.py:161-240`) hace `UPDATE users SET tier = NULL` y nada más; las filas de `advisor_clients` quedan en `status='active'` para siempre.

Consecuencia concreta, cuando a un asesor se le vence el grant-comp o cancela:

| Superficie | Qué le pasa |
|---|---|
| `/api/advisor/book`, `/clients`, `/reports`, `/group-op`… | **403** — `_require_advisor` corta |
| **Todo el resto de la app con `X-Rendi-Client-Id`** (dashboard, cartera, posiciones, operaciones, movimientos, insights, reportes, imports, IA, alertas, watchlist, exports CSV, y los `DELETE`) | **sigue funcionando igual** |

Y con `permission='read_write'` —que es el default de todo cliente `managed` (`backend/main.py:850`, `backend/main.py:34405`)— eso incluye **escritura y borrado** sobre la cuenta del cliente: `DELETE /api/positions/{pid}`, `DELETE /api/operations/{oid}`, `POST /api/me/reset-data`… (el último no: `/api/me` está exento).

[I] Severidad: no es fuga cross-tenant —el vínculo sigue siendo real y el cliente lo consintió—, pero es **una entitlement que sobrevive al pago** y, sobre todo, **acceso de escritura a carteras de terceros que ya no está respaldado por ninguna relación comercial vigente**. El frontend tampoco lo frena: `AdvisorClients.jsx:112` esconde la pantalla si `tier !== 'advisor'`, pero `rendi_client_ctx` queda persistido en `localStorage` (`frontend/src/utils/api.js:26-49`) y el header se sigue inyectando en cada request mientras no se llame `exitClient()`.

La corrección natural sería agregar el chequeo de tier dentro de `_resolve_client_context`, o revocar/pausar los vínculos en `_downgrade_expired_credit`. **Ninguna de las dos existe hoy.**

#### 5.7.4 El resto del modelo de vínculo (para contexto)

**[V] Tabla `advisor_clients`** (`backend/main.py:845-858`): `link_type ∈ {'managed','linked'}`, `permission ∈ {'read','read_write'}`, `status ∈ {'active','revoked'}`, `UNIQUE(advisor_uid, client_uid)`, más índices por las dos puntas.

**[V] Cliente shadow (`managed`)** — `POST /api/advisor/clients` (`backend/main.py:34370-34415`): crea una fila real en `users` con email sintético `cliente.<12 hex>@shadow.rendi.internal`, **password random hasheado** (`pwd_ctx.hash(secrets.token_urlsafe(24))`), `approved=0`, `email_verified=0`, `managed_by=<asesor>`. Nadie puede loguear con esa cuenta. Cap duro **500 clientes activos** por asesor (`ADVISOR_MAX_CLIENTS`, `backend/main.py:34347`).

**[V] Claim (el cliente se queda con su cuenta)** — `POST /api/auth/claim` (`backend/main.py:35106-35170`), público:
- Token de `secrets.token_urlsafe(32)`, TTL **7 días** (`ADVISOR_CLAIM_TTL_DAYS`, `backend/main.py:34650`).
- Cierra el token **primero** con `WHERE id=? AND used_at IS NULL` y solo sigue si `rowcount==1` — protege contra dos claims concurrentes del mismo link (`backend/main.py:35143-35152`).
- Pone `approved=1, email_verified=1, managed_by=NULL` y rota `password_changed_at`.
- **El vínculo NO se corta**: sigue vivo en `advisor_clients` (`backend/main.py:35149-35152`).
- Tope de **8 invitaciones por cliente por día** además del rate limit del asesor (`backend/main.py:34726-34737`).

**[V] Pedido de acceso a una cuenta que ya existe** (`_advisor_link_request`, `backend/main.py:34785+`; `_apply_link_request`, `backend/main.py:34898+`):
- Flujo de **dos pasos**: el primer POST devuelve **409 `existing_account`** explicando que ya no es una invitación sino un pedido de permiso; recién el segundo, con `mode='link_request'`, lo manda.
- **Aceptar exige estar logueado con esa cuenta exacta**: `POST /api/auth/link-request/respond` chequea `me != req["client_uid"]` → 403 (`backend/main.py:35053-35056`). Rechazar alcanza con el token — *"cortar nunca puede ser peor que no cortar"*.
- El permiso que se concede es el que **pidió el asesor** (`permission` del body, default `read_write`, `backend/main.py:34811-34813`); el cliente lo ve en el preview (`backend/main.py:35019`).
- No se puede pedir acceso a un shadow de otro asesor ni a una cuenta administrada (`backend/main.py:34797-34799`).

**[V] El cliente puede cortar en cualquier momento**: `POST /api/me/advisor/{advisor_uid}/revoke` (`backend/main.py:35241-35262`), con `get_current_user` (nunca el contexto). Es efectivo al instante porque el resolver exige `status='active'`.

**[V] Tras el claim, el cliente cae a Free.** `get_tier` devuelve `'pro'` **solo** mientras la cuenta sea shadow sin reclamar (`managed_by IS NOT NULL AND approved = 0`, `backend/ai/quota.py:181-188`). Reclamada, `managed_by` es `NULL` y resuelve `'free'` — el comentario lo declara regla de negocio: *"el cliente entra a SU cuenta y ve visión Free — el plan del asesor no incluye a los clientes"*. El asesor viendo la **misma** cuenta sigue viendo Pro por el `tier_override` de `/api/plan/features`.

**[V] Informes públicos** — `GET /api/reports/public/{token}` (`backend/main.py:36005-36036`): sin auth, token de 22 chars (`_gen_reset_token()[:22]`, `backend/main.py:35972`), TTL configurable por **`REPORTS_TTL_DAYS`** (default **180 días**, `backend/main.py:35998-36002`), revocable. Devuelve **404 y no 410** para revocado/vencido a propósito: distinguirlos le confirmaría a quien tenga un link filtrado que el informe existe. El label del cliente usa el nombre, nunca el uid interno (`backend/main.py:35955-35957`, comentario "audit").

---

### 5.8 Inventario de endpoints por nivel de auth

**260 rutas** `@app.<método>` + **4** `@app.api_route`. Reparto por dependencia:

| Nivel | Cantidad | Dependencia |
|---|---|---|
| Datos del usuario (y contexto de cliente) | **150** | `Depends(get_effective_user)` |
| Admin | **47** | `Depends(get_admin_user)` |
| Identidad real (sin contexto) | **44** | `Depends(get_current_user)` |
| Público | **17** | — |
| Webhooks de billing | **2** | `Depends(_raw_body)` + firma/token |
| Crons | **4** | token propio por env var |

#### Públicos (17)

| Método | Ruta | Línea | Nota |
|---|---|---|---|
| POST | `/api/auth/register` | 3094 | |
| POST | `/api/auth/login` | 3187 | |
| POST | `/api/auth/logout` | 3231 | solo borra la cookie |
| POST | `/api/auth/verify-email` | 3240 | |
| POST | `/api/auth/resend-verification` | 3334 | respuesta genérica |
| POST | `/api/auth/forgot-password` | 3358 | respuesta genérica |
| POST | `/api/auth/reset-password` | 3412 | **emite sesión** (ver 5.4.1) |
| GET | `/api/public/dolar` | 4983 | |
| GET | `/api/ai/topics` | 26308 | |
| GET | `/api/push/vapid-public-key` | 34052 | |
| GET | `/api/health` | 34270 | keep-alive del frontend |
| GET | `/api/stats/public` | 34304 | |
| GET | `/api/auth/link-request/preview` | 34993 | email enmascarado |
| POST | `/api/auth/link-request/respond` | 35034 | aceptar exige sesión |
| GET | `/api/auth/claim/preview` | 35060 | |
| POST | `/api/auth/claim` | 35106 | **emite sesión** |
| GET | `/api/reports/public/{token}` | 36005 | token de 22 chars, TTL 180 d |

#### Crons (auth por token de env var, sin usuario)

| Ruta | Línea | Env var del token |
|---|---|---|
| `GET/POST /api/iol/lab/run-cron` | 31559 | `IOL_LAB_CRON_TOKEN` |
| `GET/POST /api/alerts/evaluate` | 33590 | `ALERTS_CRON_TOKEN` |
| `GET/POST /api/snapshots/run-cron` | 33647 | `SNAPSHOT_CRON_TOKEN` |
| `GET/POST /api/advisor/brief/run-cron` | 33936 | `ADVISOR_BRIEF_TOKEN` (fallback a `SNAPSHOT_CRON_TOKEN`) |

**[V]** Los cuatro aceptan el token por **header `X-Cron-Token` o por query param `?token=`** (`backend/main.py:31567`, `33600-33601`, `33668-33669`, `33949-33950`) y devuelven **503 si la env var no está configurada** (fail-closed, `backend/main.py:31565-31566`, etc.). Dos detalles:
- La comparación es `got != expected` — **no** es constant-time, a diferencia de `_is_admin_email` que sí usa `hmac.compare_digest`. [I] Explotable en teoría por timing; en la práctica, sobre HTTP con jitter de red, muy difícil.
- Aceptar el token por **query string** lo deja en los logs de acceso del gateway y en el historial del cron externo.

#### Admin (47)

Los 47 están bajo `/api/admin/*` con `Depends(get_admin_user)`. Los que más superficie tienen: `POST /api/admin/billing/grant-comp` (otorga plan **incluido `advisor`**, 1-366 días, `backend/main.py:19844-19884`), `POST /api/admin/billing/restore-tier`, `DELETE /api/admin/users/{user_id}`, `POST /api/admin/wipe-broker-data`, `POST /api/admin/email/broadcast`, y las 6 herramientas de reparación/backfill.

**[V]** `grant-comp` toma `email`, `plan`, `days`, `force`, `note` como **query params** (son escalares en un POST, FastAPI los lee del query string) — igual que en el frontend, `frontend/src/pages/Admin.jsx:124`: `` `/admin/billing/grant-comp?email=…&plan=${plan}&days=${days}` ``. Con `SameSite=Lax` un POST cross-site no lleva la cookie, así que no es CSRF-able hoy.

#### Asesor

No hay un `Depends` propio de asesor: los 33 endpoints usan `Depends(get_current_user)` **+ `_require_advisor(conn, uid)` en el cuerpo** (ver la tabla de 5.7.2). Es un patrón imperativo, no declarativo — funciona, pero depende de que el próximo endpoint se acuerde de la línea.

---

### 5.9 Resumen de hallazgos de este capítulo

Ordenados por lo que me preocuparía primero.

1. **[V] El vínculo asesor→cliente sobrevive al vencimiento del plan.** `_resolve_client_context` (`backend/main.py:2767-2803`) nunca mira el tier, y nada en `backend/billing/` toca `advisor_clients`. Un asesor cuyo grant venció (`users.tier = NULL` por `backend/billing/subscriptions.py:210`) pierde `/api/advisor/*` pero conserva lectura **y escritura** sobre las carteras de sus ex-clientes vía el header.
2. **[V] Dos features pagas gateadas solo en el frontend.** `reportes.historicos` (`GET /api/reports/timeline`, `backend/main.py:33072`; `GET /api/reports/period/…`, `:33136`) y `comportamiento.full` / `behavioral_tags_visible` (`GET /api/behavioral/insights`, `backend/main.py:13760`) no tienen gate de plan en el backend.
3. **[V] Un endpoint de credenciales quedó del lado fail-open del contexto de cliente.** `/api/wallbit/*` usa `get_effective_user` (`backend/main.py:31238-31239`) y no está en `CLIENT_CTX_EXEMPT_PREFIXES` (`backend/main.py:2747-2758`), a diferencia de `/api/iol/lab/*` que usa `get_current_user`.
4. **[V] La invalidación de sesión por cambio de contraseña tiene un caso muerto.** `if pca and row["password_changed_at"] and …` (`backend/main.py:2716`): un token emitido cuando `users.password_changed_at` era `NULL` (filas migradas por el `ALTER TABLE` sin default de `backend/main.py:782`) sobrevive al cambio de contraseña hasta su `exp`.
5. **[V] `reset-password` emite sesión sin verificar ni marcar el email.** (`backend/main.py:3454-3455`). La cuenta queda con sesión válida y `email_verified = 0`: la app le funciona, pero no puede volver a loguearse ni activar el trial.
6. **[V] Divergencia del "lente Pro" del asesor.** `_gate_export` tiene la escapatoria (`backend/main.py:13310-13312`), `check_broker_quota` (`backend/main.py:4061`) y `check_alert_quota` (`backend/main.py:33440`) no. Sobre un cliente reclamado, la UI ofrece y el backend rebota con 403.
7. **[V] El rate limit "por email" del login no es global**: la clave incluye la IP (`backend/main.py:397`), así que un atacante con N IPs consigue N×10 intentos/min sobre la misma cuenta, pese a lo que dice el comentario de `backend/main.py:3190`.
8. **[V] El rate limiting es in-memory per-process** (`backend/main.py:306-310`). Hoy da igual (un solo worker, `nixpacks.toml:31`), pero se multiplica en silencio con `--workers` o con más de una réplica.
9. **[V] Código muerto y flags fantasma**: `ai.hub` y `tax.helper` no tienen endpoint ni UI; `can_hub_query` / `record_hub_query` (`backend/ai/quota.py:411-418`, `:439-449`) no tienen call sites; `insights.distribucion_activo` e `insights_diagnostic_visible` se calculan y se sirven pero nadie los lee en `frontend/src`.
10. **[V] Comentario que miente**: `backend/main.py:34339` dice que los endpoints de asesor gatean por *"tier 'advisor' o admin"*; `_require_advisor` (`backend/main.py:2823-2831`) rechaza al admin explícitamente.
11. **[V] CORS incompleto vs. la app real**: falta `PATCH` en `allow_methods` y `X-Rendi-Client-Id` en `allow_headers` (`backend/main.py:262-266`). Inofensivo mientras Vercel proxee same-origin.
12. **[V] Los tokens de cron viajan por query string y se comparan sin `compare_digest`** (`backend/main.py:31567-31569` y equivalentes).
13. **[V] El email del admin está en claro en un comentario** dos líneas arriba de su hash (`backend/main.py:125`). El hash no protege nada mientras el comentario esté ahí.
14. **[V] No hay CSP** — no encontrado en `backend/main.py` ni en el middleware de headers (`backend/main.py:269-289`).
