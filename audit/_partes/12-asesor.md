## Producto Asesor (B2B2C) — "Plan Asesor"

Auditoría del producto para asesores financieros sobre `origin/main` (`b74f450f`, 2026-09-05).
Todo lo marcado `[V]` está verificado leyendo el código en la ruta y línea que se cita;
`[I]` es inferencia mía y digo de qué me agarré.

---

### Resumen ejecutivo

| Pieza | Estado | Evidencia |
|---|---|---|
| Tier `advisor` + gate único | **Implementado** | `backend/main.py:2823` `_require_advisor` |
| Contexto de cliente (`X-Rendi-Client-Id`) | **Implementado y validado en backend** | `backend/main.py:2767` |
| Alta (a) asesor crea la cuenta | **Implementado** | `backend/main.py:34370` |
| Alta (b) pedido de acceso a cuenta existente | **Implementado** | `backend/main.py:34785` |
| Alta (c) claim de la ficha shadow | **Implementado** | `backend/main.py:35106` |
| Libro (AUM, estrella, colas, composición, historia, detalle) | **Implementado** | 5 endpoints, `backend/main.py:36947…37944` |
| TWR del libro (composite) | **NO existe** — sólo TWR per-cliente, y su endpoint no lo llama nadie | `backend/advisor_twr.py:79-85` |
| Grupos dinámicos | **Implementado** | `backend/advisor_groups.py` |
| Brief 2×/día por email | **Implementado**, disparado por cron externo | `backend/advisor_brief.py:371` |
| Alertas de movimiento del libro | **Implementado**, corre en el cron de alertas de precio | `backend/advisor_alerts.py:160` |
| Informe del período + link público | **Implementado**, con TTL y revocación | `backend/main.py:35943` / `36005` |
| Operación grupal (block trade) + undo | **Implementado, sólo COMPRAS** | `backend/main.py:36179` (`op_kind` hardcodeado `'buy'`) |
| IA del libro (book-mode) | **Implementado** (Sonnet, tools propias) | `backend/main.py:28352` |
| **Billing del plan Asesor** | **NO existe** — se otorga a mano por `grant-comp` | `backend/main.py:19878-19879` |

---

## 1. El modelo de la relación asesor ↔ cliente

### 1.1 La tabla que manda: `advisor_clients`

`[V]` DDL SQLite en `backend/main.py:845-863`; espejo Postgres en `backend/schema_pg.sql:112-148`.

```
advisor_clients(
  id, advisor_uid → users(id), client_uid → users(id),
  link_type  DEFAULT 'managed',      -- 'managed' | 'linked'
  permission DEFAULT 'read_write',   -- 'read' | 'read_write'
  status     DEFAULT 'active',       -- 'active' | 'revoked'
  label, notes, phone, consent_ref, created_at, revoked_at,
  UNIQUE(advisor_uid, client_uid))
```

El comentario del propio código la nombra como lo que es: `[V]` "advisor_clients es LA tabla de
autorización del contexto de cliente (get_effective_user)" (`backend/main.py:841-844`).

Índices: `idx_advisor_clients_advisor(advisor_uid, status)` y
`idx_advisor_clients_client(client_uid, status)` (`backend/main.py:859-862`).

**Dimensiones del vínculo** `[V]`:

| Campo | Valores | Quién lo setea |
|---|---|---|
| `link_type` | `managed` (ficha creada por el asesor) / `linked` (cuenta propia del cliente que aceptó) | `managed` en `main.py:34403`; `linked` en `main.py:34947-34950` |
| `permission` | `read_write` / `read` | `managed` siempre nace `read_write` (`34405`); `linked` toma lo que el asesor pidió y el cliente aceptó (`AdvisorInviteIn.permission`, validado en `34842-34844`) |
| `status` | `active` / `revoked` | `revoked` desde el asesor (`34620`), desde el cliente (`35251`), o al archivar la ficha shadow tras aceptar un pedido (`34964`) |
| `consent_ref` | texto de trazabilidad | `f"managed-by-advisor:{uid}:{iso}"` (`34406`) o `f"link-request:{req_id}:{iso}"` (`34960`) |
| `notes` | notas **privadas** del asesor | El docstring dice explícitamente "el cliente nunca las ve" (`main.py:34583`) — `[I]` y efectivamente no hay ningún endpoint que se las devuelva al cliente: `/api/me/advisor` (`35176`) devuelve sólo `advisor_uid/name/permission/since` |
| `phone` | celular del cliente para `wa.me` | `_norm_phone` deja sólo dígitos (`main.py:34362-34368`) |

**No hay estado intermedio "pendiente" en `advisor_clients`.** `[V]` El pendiente vive en otras
dos tablas: `advisor_claim_tokens` (invitación a reclamar) y `advisor_link_requests` (pedido de
acceso). El roster los **deriva** al vuelo en `/api/advisor/clients` (`main.py:34489-34530`)
para pintar el badge:

```
claim_status = 'claimed' si users.approved   (main.py:34537-34538)
             | 'invited' si hay claim token vivo y no usado
             | 'shadow'  (default)
```

### 1.2 Cómo se representa un "cliente" que todavía no es usuario: el shadow

`[V]` `backend/main.py:34334-34346`. Un cliente `managed` es una fila **real** en `users`:

- `email` sintético: `cliente.<12 hex>@shadow.rendi.internal` (`_SHADOW_EMAIL_DOMAIN`, `main.py:34346`)
- `password_hash` = hash de `secrets.token_urlsafe(24)` → nadie puede loguear
- `approved=0`, `email_verified=0`, `managed_by=<advisor_uid>`

El comentario dice el porqué del diseño: `[V]` "Toda la data del cliente cuelga de su uid como
cualquier usuario → el resto de la app funciona igual" (`main.py:34337-34338`).

Los shadows quedan **excluidos** de broadcast de emails, borrado de cuentas sin verificar y
métricas de signup (`main.py:834-838`).

**Cap duro: `ADVISOR_MAX_CLIENTS = 500`** (`main.py:34347`), chequeado al crear (`34385-34389`) y
al aceptar un pedido de acceso (`34922-34929`). El motivo declarado: una cuenta advisor
comprometida podría inflar `users` sin límite, y los `IN (...)` del roster/book reventarían el
tope de variables de SQLite.

### 1.3 Revocación

Dos caminos, ambos dejan la data del cliente intacta:

**Asesor → `POST /api/advisor/clients/{client_uid}/revoke`** (`main.py:34609`):
`[V]` marca `status='revoked'`, `revoked_at=now`, y de paso **cierra los pendientes**: marca
usados los `advisor_claim_tokens` sin usar (`34627-34630`) y cancela los `advisor_link_requests`
`pending` que salieron de esa ficha (`34635-34638`).

**Cliente → `POST /api/me/advisor/{advisor_uid}/revoke`** (`main.py:35241`):
`[V]` mismo `UPDATE`, con `WHERE advisor_uid=? AND client_uid=uid`. El docstring afirma que es
efectivo de inmediato "porque `get_effective_user` solo resuelve el contexto sobre vínculos
`status='active'`" — `[V]` cierto: `_resolve_client_context` hace el `SELECT` con
`AND status='active'` en **cada request** (`main.py:2791-2795`), no hay cache.

⚠️ **`revoke` NO chequea `_require_advisor` del lado del cliente** (correcto: el cliente no es
asesor) pero **tampoco valida que `advisor_uid` sea un asesor**; sólo que exista el vínculo activo.
`[I]` No es explotable: si no hay fila, 404.

⚠️ **Un vínculo revocado no se puede "re-activar" desde la UI del asesor.** `[V]` El único
`UPDATE … status='active'` sobre un vínculo existente es el `ON CONFLICT DO UPDATE` de
`_apply_link_request` (`main.py:34947-34961`), o sea: sólo re-nace por un nuevo pedido de acceso
aceptado. Un `managed` revocado queda archivado; el docstring dice "recuperable por soporte"
(`main.py:34611-34613`) — es decir, **a mano en la base**.

### 1.4 Borrado de cuenta y cascada

`[V]` `backend/main.py:3879-3905` (`delete_my_account`) y `main.py:20304-20350` (borrado admin):

- Se borran primero los vínculos (`advisor_clients` tiene FK a `users(id)` y bloquearía el DELETE).
- Si el que se borra es un **asesor**, se borran en cascada **todos sus shadows** (`managed_by=uid`).
  Por eso el claim pone `managed_by=NULL` (ver §2.3) — el comentario lo llama "bug real, hallado en
  el review de seguridad de F4a" (`main.py:35145-35152`).
- Se limpian también los artefactos sin columna `user_id`: `advisor_reports`, `advisor_profile`,
  `advisor_op_batch_items` donde el usuario es el CLIENTE de un lote de OTRO asesor
  (`main.py:3896-3905`).

---

## 2. Los tres caminos de alta — los tres existen

### 2.1 (a) El asesor crea la cuenta del cliente — `POST /api/advisor/clients`

`[V]` `backend/main.py:34370-34417`.

```
Body: AdvisorClientIn { label (req), name?, phone? }
Rate limit: 30 llamadas / 60 s por asesor  (main.py:34376)
```

Flujo end-to-end `[V]`:

1. `_require_advisor(conn, uid)` → 403 si el tier no es `advisor`.
2. Cuenta vínculos activos; si `>= 500` → 400.
3. `INSERT INTO users` con email sintético, hash random, `approved=0`, `managed_by=uid` (`34395-34400`).
4. `INSERT INTO advisor_clients` con `link_type='managed'`, `permission='read_write'`,
   `status='active'`, `consent_ref='managed-by-advisor:<uid>:<iso>'` (`34402-34408`).
5. Devuelve `{client_uid, label, link_type, permission}`.

UI: `AddClientModal` en `frontend/src/pages/AdvisorClients.jsx:438`.

**Desde ese momento el asesor opera la cuenta entera** entrando al "contexto de cliente"
(§3). La cuenta shadow resuelve tier `pro` en `quota.get_tier` mientras `managed_by IS NOT NULL
AND approved=0` (`backend/ai/quota.py:174-178`).

### 2.2 (b) Invitación a alguien que YA tiene Rendi → pedido de acceso

`[V]` Es una **rama** del mismo endpoint de invitación, no un endpoint aparte.

`POST /api/advisor/clients/{client_uid}/invite` (`main.py:34690-34783`), rate limit
10/300 s por asesor. Body `AdvisorInviteIn { email, mode?, permission? }`.

El endpoint chequea si el email pertenece a **otra** cuenta (`main.py:34712-34716`). Si sí,
delega en `_advisor_link_request` (`main.py:34785-34884`), que implementa un **flujo de dos
pasos deliberado**:

**Paso 1 — el 409 didáctico** `[V]` (`main.py:34846-34859`): si el POST vino **sin**
`mode='link_request'`, devuelve `HTTP 409` con
`{code:'existing_account', message, email, shadow_positions:<n>}`. El comentario lo explica:
"el asesor cree que está invitando y en realidad está pidiendo permiso, y la ficha que venía
cargando se archiva" (`main.py:34790-34794`).

El frontend lo trata **como cambio de pantalla, no como error**:
`frontend/src/pages/AdvisorClients.jsx:584-586` (`if (ex?.status === 409 && detalle?.code ===
'existing_account') setExistente(detalle)`), y el paso 2 del modal ofrece elegir permiso
`read_write` vs `read` y advierte que la ficha managed sale del libro
(`AdvisorClients.jsx:607-650`).

**Paso 2 — el pedido** `[V]` (`main.py:34861-34884`): crea `advisor_link_requests` con
token de 256 bits (`_gen_reset_token`, `main.py:2943-2945`), `expires_at = now + 14 días`
(`ADVISOR_LINK_TTL_DAYS`, `main.py:34654`), y manda el email
`emails.send_advisor_access_request` con URL `<frontend>/acceso?token=…`.

**Guardas antes de crear el pedido** `[V]`:

| Guarda | Línea | Comportamiento |
|---|---|---|
| El target es uno mismo | `34796-34797` | 400 |
| El target es shadow de otro asesor o cuenta administrada (`not approved` o `managed_by`) | `34801-34803` | 400 "Ya existe una cuenta de Rendi con ese email" — no hay a quién preguntarle |
| Ya hay vínculo activo con esa cuenta | `34804-34810` | 400 con email enmascarado |
| `permission` fuera de `{read, read_write}` | `34842-34844` | 400 |
| Rechazo previo dentro de 30 días (`ADVISOR_LINK_REJECT_COOLDOWN_DAYS`) | `34846-34855` | 429 |
| Más de 3 pedidos/día a la misma cuenta (`ADVISOR_LINK_MAX_PER_DAY`) | `34857-34864` | 429 |
| Reenvío | `34871-34876` | cancela el pedido `pending` anterior (un solo link vivo) |

**Del lado del cliente**, dos superficies:

1. **Link del email** → `/acceso?token=…` → `frontend/src/pages/AdvisorAccessRequest.jsx`.
   - `GET /api/auth/link-request/preview?token=` (`main.py:34993-35025`, rate limit 20/300 s
     por IP): devuelve `state`, nombre y matrícula del asesor, logo, `permission`,
     **email enmascarado** (`_mask_email`, `main.py:34667-34677`), `is_owner`, `logged_in`.
     El docstring explica el enmascaramiento: "sin publicar el email entero en una pantalla que
     abre cualquiera con el link".
   - `POST /api/auth/link-request/respond {token, accept}` (`main.py:35034-35056`).
     ⚠️ **Asimetría deliberada y correcta**: **aceptar exige estar logueado con esa cuenta**
     (401 si no hay sesión, 403 si el uid no es `req.client_uid`); **rechazar alcanza con el
     token**. Comentario: "le estamos dando a un tercero la cartera entera de alguien, y el que
     reenvía un mail no puede regalarla" (`main.py:35037-35040`).
   - El token se guarda en `sessionStorage` y **se saca de la URL** con `history.replaceState`
     (`AdvisorAccessRequest.jsx:36-47`), para que no viaje a analytics ni al historial.

2. **Dentro de la app**, Config › Tu asesor:
   `GET /api/me/advisor` (`main.py:35176`) lista los asesores activos **y los pedidos pendientes**;
   `POST /api/me/advisor/requests/{req_id}/respond` (`main.py:35224`) responde sin token, con
   `WHERE id=? AND client_uid=uid` (`35232-35234`). Frontend: `frontend/src/pages/Config.jsx:119,128,152`.

**Qué pasa al aceptar** — `_apply_link_request` (`main.py:34898-34973`) `[V]`:

- Rechaza si el pedido no está `pending` (incluye vencido, vía `_link_request_state`, `main.py:34886`).
- Chequea el cap de 500 **al aceptar**, no al pedir ("entre el pedido y el sí pueden haber pasado
  dos semanas y un libro entero", `34918-34921`).
- `UPDATE … status='accepted' … WHERE id=? AND status='pending'` y **exige `rowcount==1`** →
  protege de dos clicks simultáneos (mail + Config) (`34932-34940`).
- Crea/reactiva el vínculo `link_type='linked'` con `ON CONFLICT(advisor_uid, client_uid) DO UPDATE`
  que **resucita** un vínculo revocado (`revoked_at=NULL`, `status='active'`) y hereda label/notes/
  phone de la ficha shadow (`34946-34961`).
- **Archiva la ficha shadow** (`status='revoked'`) para que la persona no cuente dos veces en el
  AUM (`34962-34968`) — pero sólo si la ficha **sigue siendo ficha**: revalida `approved=0 AND
  managed_by=advisor_uid` porque `shadow_uid` quedó congelado hasta 14 días
  (`34908-34913`). Si alguien la reclamó en el medio, no la toca.

### 2.3 (c) El cliente reclama la cuenta que le armó el asesor

`[V]` Tabla `advisor_claim_tokens` (`main.py:2125-2137`), TTL 7 días (`ADVISOR_CLAIM_TTL_DAYS`,
`main.py:34650`).

**Generación** — la rama "normal" de `POST /api/advisor/clients/{client_uid}/invite`
(`main.py:34718-34783`) `[V]`:

1. `_require_advisor` + `_advisor_own_link(conn, uid, client_uid)` → 404 si el cliente no es suyo.
2. 400 si `users.approved` ya es 1 ("Este cliente ya tiene su cuenta activa").
3. Tope adicional: **8 invitaciones por cliente por día** (`34742-34748`) — además del rate limit
   de 10/300 s por asesor. El comentario: corta a alguien usando el mismo shadow para probar
   emails de terceros.
4. Invalida los tokens vivos previos (`UPDATE … used_at=now WHERE user_id=? AND used_at IS NULL`)
   y cancela pedidos de acceso `pending` de esa ficha (`34753-34765`).
5. Inserta el token y manda `emails.send_advisor_claim` con `<frontend>/claim?token=…`.
6. ⚠️ **Si `RESEND_API_KEY` está configurada y el envío falla → 502** (`34779-34781`), es decir el
   token queda creado pero el asesor recibe un error. `[I]` Es benigno (el próximo reenvío lo
   invalida) pero deja filas huérfanas en `advisor_claim_tokens`.

**Consumo** — `frontend/src/pages/ClaimAccount.jsx` (ruta `/claim`, `App.jsx:288`) `[V]`:

- `GET /api/auth/claim/preview?token=` (`main.py:35060-35104`, rate limit 20/300 s por IP):
  devuelve nombre del asesor (perfil › users.name › localpart del email), `label` del vínculo,
  matrícula CNV y logo. 400 si el token no existe, ya fue usado o expiró.
- `POST /api/auth/claim {token, new_password}` (`main.py:35106-35174`, rate limit 10/300 s por IP):
  - Re-chequea colisión de email (alguien pudo registrarse entre invitación y claim) → 400.
  - **Cierra el token PRIMERO** con `WHERE id=? AND used_at IS NULL` y exige `rowcount==1`
    (`main.py:35133-35143`) — protege de dos claims concurrentes del mismo link.
  - `UPDATE users SET email=?, password_hash=?, approved=1, email_verified=1,
    password_changed_at=now, managed_by=NULL WHERE id=?` (`35155-35160`).
  - Emite JWT y setea la cookie → auto-login.
- El token se saca de la URL con `history.replaceState` (`ClaimAccount.jsx:37-41`), con el
  comentario "audit de seguridad: GA/Meta recibían la URL completa con el token".

**Consecuencia de tier importante** `[V]`: al reclamar, `managed_by` pasa a NULL y `approved` a 1,
así que la rama "shadow → pro" de `quota.get_tier` (`backend/ai/quota.py:174-178`) deja de
aplicar y **el cliente cae a `free`**. El comentario lo declara como regla de negocio: "el cliente
entra a SU cuenta y ve visión Free — el plan del asesor no incluye a los clientes"
(`quota.py:181-186`). El **vínculo sigue vivo** en `advisor_clients`, así que el asesor no pierde
acceso.

---

## 3. ⚠️ Autorización — dónde se verifica que el cliente sea suyo

### 3.1 Los dos mecanismos

**(A) `_require_advisor(conn, uid)`** — `backend/main.py:2823-2832`:

```python
tier = _q.get_tier(conn, uid)
if tier != "advisor":
    raise HTTPException(403, "Requiere el plan Asesor")
```

`[V]` **`is_admin` NO alcanza** — es el único gate de la app que no tiene bypass de admin, y el
docstring lo dice explícitamente. Verificado también en el frontend: `AdvisorClients.jsx:112`
(`const isAdvisor = user?.tier === 'advisor'`) y `Sidebar.jsx:92-95`.

**(B) `_resolve_client_context(request, uid)`** — `backend/main.py:2767-2804`, llamado por
`get_effective_user` (`main.py:2806-2820`), el `Depends` por defecto de los endpoints de DATOS.

```
Header: X-Rendi-Client-Id   (CLIENT_CTX_HEADER, main.py:2748)
```

Reglas verificadas `[V]`:

| Situación | Resultado | Línea |
|---|---|---|
| Sin header | `None` → el uid propio | `2772-2773` |
| Path bajo un prefijo exento | `None` — el header **se ignora** | `2777-2779` |
| Header no entero | **400** | `2780-2783` |
| Header fuera de rango INTEGER de SQLite | **400** (evita `OverflowError` → 500) | `2784-2786` |
| `client_id == uid` | `None` (no-op) | `2787-2788` |
| **Sin fila activa en `advisor_clients`** | **403** — "jamás degradar en silencio al uid propio" | `2796-2799` |
| Método de escritura + `permission != 'read_write'` | **403** | `2801-2802` |

**Es un chequeo de backend, no un filtro de front.** El `SELECT` a `advisor_clients` con
`advisor_uid=<autenticado> AND client_uid=<header> AND status='active'` corre en **cada request**
(`2790-2795`). El frontend sólo pega el header (`frontend/src/utils/api.js:104`, y en las variantes
upload/blob/chat, `api.js:227,264,303`).

**Prefijos exentos** (`CLIENT_CTX_EXEMPT_PREFIXES`, `main.py:2749-2758`):
`/api/auth`, `/api/billing`, `/api/admin`, `/api/advisor`, `/api/me`, `/api/push`,
`/api/plan/track`, `/api/feedback`.
El match es **por límite de segmento** (`path == p or path.startswith(p + "/")`, `main.py:2778`),
con el comentario correcto de que un `startswith` crudo eximiría un futuro `/api/metrics`.

⚠️ **FAIL-OPEN declarado por el propio código** (`main.py:2764-2765`):
"todo endpoint futuro FUERA de estos prefijos hereda el contexto de cliente. Si agregás un
endpoint de IDENTIDAD/CUENTA/PAGO nuevo, agregalo acá." Es una nota de mantenimiento, no un bug
actual, pero es la superficie de riesgo estructural del diseño.

### 3.2 Endpoint por endpoint — TODOS validan

`[V]` Recorrí los 34 endpoints `/api/advisor/*` (más los 5 auxiliares) uno por uno. **Ninguno
queda sin gate de tier, y todos los que reciben un id de objeto lo filtran por `advisor_uid`.**

| Endpoint | Gate de tier | Ownership del objeto | Línea |
|---|---|---|---|
| `GET /api/advisor/twr` | `_require_advisor` 33707 | roster derivado de DB | 33698 |
| `GET /api/advisor/data-health` | 33723 | roster derivado | 33715 |
| `GET /api/advisor/groups` | 33735 | `WHERE advisor_uid=?` (`advisor_groups.py:79-80`) | 33730 |
| `POST /api/advisor/groups` | 33755 | inserta con `advisor_uid=uid` | 33751 |
| `PATCH /api/advisor/groups/{id}` | 33781 | `ag.get_group(conn, uid, gid)` + `WHERE id=? AND advisor_uid=?` | 33776 |
| `DELETE /api/advisor/groups/{id}` | 33811 | `WHERE id=? AND advisor_uid=?`, **404 si `rowcount==0`** | 33807 |
| `POST /api/advisor/groups/preview` | 33841 | roster derivado | 33836 |
| `GET /api/advisor/groups/{id}/clients` | 33856 | `ag.get_group(conn, uid, gid)` → 404 | 33852 |
| `GET /api/advisor/alerts` | 33885 | `WHERE advisor_uid=?` | 33880 |
| `POST /api/advisor/alerts/events/seen` | 33902 | `WHERE advisor_uid=?` | 33896 |
| `PATCH /api/advisor/alerts` | 33915 | valida `group_id` con `ag.get_group` → 404 | 33911 |
| `GET /api/advisor/brief/preview` | 33984 | roster derivado | 33979 |
| `GET/PATCH /api/advisor/brief/prefs` | 34002 / 34015 | `WHERE advisor_uid=?` | 33998 / 34011 |
| `POST /api/advisor/clients` | 34381 | crea el propio | 34370 |
| `GET /api/advisor/reports` | 34426 | `WHERE r.advisor_uid=?` | 34419 |
| `GET /api/advisor/clients` | 34474 | `WHERE ac.advisor_uid=? AND status='active'` | 34465 |
| `PATCH /api/advisor/clients/{cid}` | 34589 | **`_advisor_own_link`** → 404 | 34578 |
| `POST /api/advisor/clients/{cid}/revoke` | 34616 | **`_advisor_own_link`** → 404 | 34609 |
| `POST /api/advisor/clients/{cid}/invite` | 34700 | **`_advisor_own_link`** → 404 | 34690 |
| `GET /api/advisor/radar/events` | 35315 | `_advisor_ticker_holders` filtra por vínculo activo | 35307 |
| `GET /api/advisor/radar/news` | 35381 | ídem | 35373 |
| `GET/PATCH /api/advisor/profile` | 35904 / 35914 | `WHERE advisor_uid=?` | 35900 / 35910 |
| `POST /api/advisor/reports/generate` | 35952 | `client_uids` filtrado contra `links` del asesor; los ajenos van a `skipped` con razón "sin vínculo activo" | 35943 |
| `POST /api/advisor/reports/{id}/revoke` | 36050 | `WHERE id=? AND advisor_uid=?` → 404 | 36039 |
| `GET /api/advisor/group-op/prep` | 36113 | roster derivado | 36092 |
| `POST /api/advisor/group-op` | vía `_advisor_group_op_apply` 36190 | cada `rows[].client_uid` validado contra `links` activos + `permission=='read_write'` | 36292 |
| `POST /api/advisor/group-op/{batch_id}/undo` | 36592 | `WHERE id=? AND advisor_uid=?` → 404, **y** re-chequea `permission='read_write'` por item | 36584 |
| `GET /api/advisor/book` | 36968 | `_advisor_client_ids` | 36947 |
| `GET /api/advisor/book/composition` | 37677 | `_advisor_client_ids` | 37661 |
| `GET /api/advisor/book/asset-clients` | 37819 | `_advisor_client_ids` | 37795 |
| `GET /api/advisor/book/history` | 37900 | `_advisor_client_ids` | 37883 |
| `GET /api/advisor/book/detail` | 37960 | `_advisor_client_ids` | 37944 |

Endpoints auxiliares (fuera de `/api/advisor`):

| Endpoint | Autenticación | Línea |
|---|---|---|
| `GET|POST /api/advisor/brief/run-cron` | Token `ADVISOR_BRIEF_TOKEN` (fallback `SNAPSHOT_CRON_TOKEN`) por header `X-Cron-Token` o `?token=`; **503 si no hay token configurado** | 33937-33959 |
| `GET /api/auth/link-request/preview` | pública, rate-limited 20/300 s por IP; email enmascarado | 34993 |
| `POST /api/auth/link-request/respond` | aceptar exige sesión del dueño; rechazar sólo token | 35034 |
| `GET /api/auth/claim/preview` | pública, rate-limited | 35060 |
| `POST /api/auth/claim` | sólo token, rate-limited | 35106 |
| `GET /api/me/advisor` | `get_current_user` (identidad REAL, prefijo exento) | 35176 |
| `POST /api/me/advisor/requests/{id}/respond` | `WHERE id=? AND client_uid=uid` → 404 | 35224 |
| `POST /api/me/advisor/{advisor_uid}/revoke` | `WHERE advisor_uid=? AND client_uid=uid` → 404 | 35241 |
| `GET /api/reports/public/{token}` | **pública** — ver §7.3 | 36005 |

**Detalle que refuerza el diseño** `[V]`: las dos únicas listas de clientes que el backend usa se
**derivan de la DB**, nunca se aceptan por HTTP. `_advisor_client_ids` (`main.py:36695-36700`)
y el `SELECT` de `advisor_clients` en cada endpoint. El docstring de `/book/composition` lo
declara: "La lista de clientes se DERIVA de la DB con `_advisor_client_ids` — nunca se acepta por
HTTP" (`main.py:37673-37674`), y también explica por qué el endpoint vive bajo `/api/advisor/`:
para caer en `CLIENT_CTX_EXEMPT_PREFIXES` y ser inmune al header (`37668-37672`).

### 3.3 Hallazgos de autorización

**H-1 `[V]` — El "lente Pro" es una mentira parcial: la UI dice desbloqueado, el backend rebota.**

`/api/plan/features` fuerza `tier_override='pro'` cuando hay contexto de cliente
(`main.py:26469-26471`), así que el frontend pinta todo desbloqueado. Pero los gates
**cuantitativos** no reciben el override: `create_broker` llama
`plan.check_broker_quota(conn, uid)` con `uid` = **el cliente** (`main.py:4054-4061`), y
`check_broker_quota` resuelve `quota.get_tier(conn, user_id)` sin parámetro de override
(`backend/ai/plan.py:182-196`).

Consecuencia concreta: un cliente que **reclamó su cuenta** (F4a) cae a tier `free`
(`brokers_max=1`, `backend/ai/plan.py:47`). El asesor entra a su cuenta, la UI le muestra "brokers
ilimitados" y el `POST /api/brokers` le devuelve **403 con un upsell dirigido al asesor**. Con un
cliente `shadow` no pasa (resuelve `pro`).

El repo ya parcheó el mismo patrón en tres lugares distintos, uno por uno: el export
(`_gate_export`, `main.py:13310-13312`), los análisis IA (`main.py:25939-25942`) y el chat
(`main.py:28311-28316`) — los tres detectan "uid ≠ auth_uid y el autenticado es advisor" y suben
el tier. **`check_broker_quota` y `check_alert_quota` no tienen ese parche.**

**H-2 `[V]` — Dos comentarios del repo se contradicen sobre a quién se le cobra la cuota de IA.**

- `backend/ai/quota.py:104-107`: "Advisor … **Pool PROPIO del asesor**: toda la IA que use (en su
  cuenta o dentro de un cliente vía contexto) descuenta de acá, **nunca de la cuota del cliente**."
- `backend/main.py:2759-2763`: "/api/ai NO está exento a propósito … **la cuota corre en los
  contadores del cliente** … F5 centraliza la cuota en el asesor."

El código hace lo segundo `[V]`: `quota.can_chat(conn, uid, …)` con `uid` = el cliente
(`main.py:28322`), y el comentario en el sitio dice "Los contadores siguen en la cuenta del
cliente (criterio del shadow; F5 centraliza el pool en el asesor)" (`main.py:28310-28311`).
O sea: **el docstring de `quota.py` describe una fase que no se construyó.**

**H-3 `[V]` — El pedido de acceso se puede usar para enumerar cuentas de Rendi.**

`POST /api/advisor/clients/{cid}/invite` con un email que ya tiene cuenta devuelve **409 con
`code:'existing_account'`**; con uno que no la tiene, manda un mail y devuelve 200. Un asesor
puede así distinguir emails registrados de no registrados, a razón de 10 llamadas cada 300 s
(`main.py:34696`). Mitigantes: hace falta tier `advisor` (que hoy sólo se otorga a mano) y el 409
**no manda ningún email** (`main.py:34846`, el comentario del test lo llama
`test_email_existente_devuelve_409_y_no_manda_nada`, `backend/tests/test_advisor_plan.py:3683`).

**H-4 `[V]` — El contexto de cliente vive en `localStorage` y sobrevive al reload.**

`frontend/src/utils/api.js:26-36` hidrata `rendi_client_ctx` al arrancar el módulo. Hay sync
multi-pestaña por el evento `storage` en los dos lados (`api.js:57-67` y
`contexts/AdvisorContext.jsx:32-36`) con el comentario de un audit previo ("una pestaña vieja
seguía mandando el header de un cliente ajeno tras el logout+login de otro usuario"). El backend
igual valida en cada request, así que el peor caso es un 403, no una fuga.

**H-5 `[V]` — El asesor NO puede pisar la serie histórica del cliente por mirarla.**

`POST /api/snapshots` (`main.py:5004-5017`) chequea el header crudo:
`if request.headers.get(CLIENT_CTX_HEADER): return {"ok": True, "skipped": "contexto de cliente"}`.
Devuelve 200 sin escribir. Cubierto por
`backend/tests/test_advisor_plan.py:2186` (`test_con_la_lente_puesta_no_escribe_el_snapshot_del_cliente`).

---

## 4. El "libro"

El libro es **la agregación de todas las carteras de los clientes con vínculo activo**, valuada
sin salir a la red. Se sirve por cinco endpoints.

### 4.1 `GET /api/advisor/book` — el hero (`main.py:36947-37280`)

`[V]` Fuentes: `snapshots` + `positions` + `operations` + `asset_last_price`. **Cero fetches de
red en el request** (docstring `36951-36954`). FX del día vía `_advisor_book_fx` (`36820`).

Devuelve:

| Bloque | Qué es | Reglas notables |
|---|---|---|
| `aum` | Σ `total_value` del último snapshot por cliente, + `clients` / `with_data` / `delta_7d_usd` / `delta_7d_pct` / `as_of` | El delta 7d exige: cliente presente en ambos cortes, **fechas distintas**, base no más vieja que 14 días, y **las dos puntas en base de mercado** (`_es_base_de_mercado`) — `37003-37017` |
| `flows_month` | `net_deposited_usd` + `market_effect_usd` desde el último día del mes anterior | Misma exigencia de base de mercado, más un piso anti-cron-caído de 8 días (`37032-37041`) |
| `distribution` | verde / rojo / plano + mejor y peor cliente | Denominador = **MAX histórico** de `net_deposited` (no el actual), y base mínima US$ 100 (`37047-37078`) |
| `star` | "motor estrella": P&L NO realizado per-activo cross-cliente, top-5 ganadores y perdedores | Posiciones sin precio se **excluyen** y se cuentan en `star.skipped_no_price` (`37105-37129`) |
| `queues` | "¿a quién llamar hoy?" | 4 razones, ver abajo |

**Las 4 colas** (`main.py:37205-37246`) `[V]`:

1. `sin_cargar` — ni posiciones ni cash en ninguna moneda.
2. `drawdown` — caída ≥15 % del **resultado ajustado por flujos** desde el máximo, con dos guardas:
   piso `adj_mx >= 500` USD y `_pico_es_plausible` (el pico no puede ser más de
   `PICO_MAX_VECES_LA_CARTERA` veces el valor de hoy, `main.py:36737-36752`). El pico se lee de la
   vista `snapshots_medibles`, no de `snapshots` (`37166-37173`).
3. `cash_ocioso` — cash ARS > 15 % del portfolio.
4. `inactivo` — sin operaciones ni altas hace >90 días.

Frontend: `frontend/src/pages/AdvisorDashboard.jsx` — `BookHero` (`163`), `CallQueue` (`594`),
`StarSection` (`647`), `DistributionCard` (`698`).

### 4.2 `GET /api/advisor/book/composition` — las tres tortas (`main.py:37661-37793`)

`[V]` **El backend valúa y agrega; el frontend clasifica.** El comentario de diseño
(`main.py:37281-37310`) da las tres razones, todas verificables:

- El backend valúa porque `/api/prices` **trunca en silencio** a 60 símbolos y un libro de 100
  clientes toca ~486 tickers → valuar desde el browser daría una torta incompleta con pinta de
  correcta.
- El frontend clasifica para no tener **dos** implementaciones de `assetClass`/`assetSector`.
  El comentario documenta que el clasificador Python que ya existe del lado asesor
  (`advisor_groups.classify`, `backend/advisor_groups.py:39-72`) manda 9,4 % de las posiciones
  reales a "otro" y se equivoca con AAPL en broker ARS y con AL30.
- Se mandan filas **agregadas** por `(activo, asset_type, mercado)`: 8,0 MB crudos de 500 clientes
  → 115 KB agregados.

Las **tres fuentes del patrimonio** son explícitas (`37692-37698`): posiciones no-cash
(`_advisor_positions_valued`, `36844`), cash (`_advisor_cash_usd`, `37292`) y plazos fijos
(`_advisor_pf_usd`, `37333`). Devuelve además `realized_by_asset` (`37520`) y `return_spread`
(`37573`, el rango de retorno entre clientes por activo), y un bloque `excluded`
con `no_price` / `orphan_broker`.

Frontend: `frontend/src/components/advisor/BookComposition.jsx` +
`frontend/src/utils/bookComposition.js` (top-12 activos + porción "Resto (N activos)" desplegable,
`bookComposition.js:33-36`).

### 4.3 `GET /api/advisor/book/asset-clients` (`main.py:37795-37881`)

`[V]` Quién tiene un activo y cómo le fue a cada uno. Se sirve **aparte y a pedido** porque
per-cliente per-activo son ~32.000 filas para 500 clientes. El docstring documenta el problema de
lectura que lo originó (un "+1,0 %" ponderado por plata junto a "2 de 6 clientes en rojo"), y el
componente `AssetClientsModal.jsx` lo repite con el caso real.

### 4.4 `GET /api/advisor/book/history` (`main.py:37883-37942`)

`[V]` Serie diaria del AUM + línea de "plata aportada neta", hasta 730 días.
Construcción por **forward-fill**: un cliente sin snapshot ese día no hace caer la serie; un
cliente nuevo suma desde su primer snapshot. Hay un **seed** con el último snapshot anterior a la
ventana (`_snapshots_asof`) para no dibujar una rampa falsa. Downsample a ~400 puntos preservando
extremos.

⚠️ `[V]` Este endpoint **no** filtra por `_es_base_de_mercado` (a diferencia del delta del hero):
la serie suma `total_value` de cualquier snapshot. Es coherente con la regla declarada del repo
("el AUM MUESTRA un valor, no lo resta", `main.py:37175-37176`), pero la línea del gráfico sí es
una serie sobre la que el ojo hace restas.

### 4.5 `GET /api/advisor/book/detail` (`main.py:37944-38029`)

`[V]` Desglose por cliente del hero: `value_usd`, `share_pct`, y el Δ7d **separado en aportes vs
mercado** (`flows_7d_usd` / `market_7d_usd`). Estados explícitos: `ok` / `new` (sin base de 7 días)
/ `no_snapshot`. Aplica el mismo filtro `_es_base_de_mercado` a las dos puntas.

### 4.6 TWR del libro — **NO existe**

`[V]` Hay dos cosas, y ninguna es el TWR del libro:

- `salud_del_libro` (`backend/advisor_twr.py:32-70`) → `GET /api/advisor/data-health`: semáforo
  por cliente de "desde cuándo su historia es medible a mercado", con `cobertura_pct`.
  **Sí se usa**: `frontend/src/pages/AdvisorClients.jsx:54-61`.
- `twr_por_cliente` (`backend/advisor_twr.py:79-124`) → `GET /api/advisor/twr`: TWR de cada
  cliente, con piso de `MESES_MINIMOS = 3` para publicar el porcentaje.

El docstring dice literalmente `[V]`: "El TWR del LIBRO — el composite ponderado por capital — es
la **Fase 2**: NO se puede sacar promediando estos números, porque el peso de cada cliente cambia
mes a mes" (`advisor_twr.py:83-85`).

⚠️ **`GET /api/advisor/twr` es código muerto desde la UI.** `[V]` Grepeé todo `frontend/src`
buscando `/advisor/twr` y `twr` case-insensitive: **cero llamadas**. Los únicos hits de "twr" en
el frontend son a la implementación JS propia de TWRR de la app retail
(`frontend/src/utils/evolution.js`, `insightsModel.js`). Y no es un endpoint inocuo: **escribe**
— `twr_por_cliente(sellar_primero=True)` llama `twr.sellar(conn, cid)` por cada cliente
(`advisor_twr.py:93-97`).

`[V]` Otro sesgo declarado y no corregido: `_clientes_vigentes` usa el roster de **hoy**, y el
comentario avisa que para un TWR histórico eso es **sesgo de supervivencia** — el que se da de
baja hoy desaparece de toda la historia y el retorno del año pasado mejora solo
(`advisor_twr.py:19-23`).

---

## 5. Grupos (`advisor_groups`)

`[V]` `backend/advisor_groups.py` (296 líneas) + tabla en `main.py:1718-1727`.

**Qué son**: filtros guardados y **dinámicos**, no listas congeladas. "Si mañana un cliente compra
Amazon entra solo a 'Los de Amazon'; si vende, sale" (`advisor_groups.py:3-6`).

**Condiciones soportadas** (todas opcionales, se combinan con Y) — `normalize_rules`
(`advisor_groups.py:103-127`):

| Regla | Semántica |
|---|---|
| `has_asset` | tiene ese ticker (normalizado sin `.BA`), en cualquier broker |
| `aum_min` / `aum_max` | tamaño de la cartera en USD |
| `cash_pct_min` | % sin invertir (cash de cualquier moneda → USD al MEP) |
| `class` + `class_pct_min` | `ar_stock` / `cedear` / `bond` / `fund` / `crypto` / `us_stock` |
| `losing` | `snap_value < net_deposited` |

`excluded` es una lista de `client_uid` sacados a mano ("todos los de Amazon menos Juan").
`MAX_GROUPS = 30` por asesor (`advisor_groups.py:36`, enforced en `main.py:33761-33763`).

**Para qué sirven** `[V]`, tres usos concretos:

1. **Filtrar el roster** en `/clientes` (`frontend/src/components/advisor/GroupsBar.jsx`).
2. **Acotar el alcance de la alerta del libro**: `advisor_alerts.group_id` — la alerta se evalúa
   sólo sobre los que caen en el grupo **en esa corrida** (`advisor_alerts.py:205-227`).
3. **WhatsApp en lote asistido**: `GroupWhatsAppModal.jsx` — el propio comentario aclara que
   WhatsApp no permite difusión desde un link, así que lo honesto es "escribís una vez y la lista
   te lleva de a uno con el texto ya cargado" (`GroupWhatsAppModal.jsx:1-7`).

**Valuación**: `client_profiles` (`advisor_groups.py:151-251`) reusa
`main._advisor_positions_valued` para no discutir con el resto de la app, pero con una diferencia
declarada: donde el motor del libro **excluye** las posiciones sin precio, acá se cae al **costo
como piso** ("una cartera vale al menos lo que costó", `advisor_groups.py:181-184`) para no hacer
desaparecer a un cliente entero por un ticker raro.

⚠️ El casamiento valor↔fila es **lote a lote** por `(cliente, activo, broker)` con `lots.pop()`
(`advisor_groups.py:192-217`). El comentario documenta el bug que arregló: agregar por
`(cliente, activo)` multiplicaba la cartera por la cantidad de lotes — "con 3 compras de AAPL,
US$ 15.000 se leían como US$ 45.000".

**Detalle de integridad bien resuelto** `[V]`: borrar un grupo **apaga** la alerta que lo apuntaba
(`group_id=NULL, active=0`) en vez de dejarla muda, y re-arma el estado
(`main.py:33813-33830`). El comentario: "apagada se VE, muda no. Tampoco se pasa sola a 'todo el
libro' — avisar de más también sería mentir."

---

## 6. Alertas de asesor (`advisor_alerts.py`)

`[V]` Una sola clase de alerta: **"la cartera de un cliente se movió X % hoy"**.

**Configuración** — una fila por asesor en `advisor_alerts` (`main.py:1734-1742`):
`up_pct`, `down_pct` (asimétricos, cualquiera puede ser NULL), `channel ∈ {push, email, both}`,
`active`, `group_id`.

**Qué dispara** — `advisor_alerts.evaluate` (`advisor_alerts.py:160-326`):

1. Selecciona asesores con `active=1` **y `u.tier='advisor'`**. El comentario: "sin él, un asesor
   con el plan vencido seguía recibiendo los nombres y los movimientos de sus ex-clientes sin
   poder apagarlo" (`advisor_alerts.py:163-171`).
2. **Fuera de rueda no evalúa** (`market_open`, `advisor_alerts.py:182-185`).
3. Valúa el libro **en vivo** con `advisor_brief.live_book_values` (fetch de precios frescos).
4. Base = el **último snapshot APTO anterior a hoy**, con dos filtros:
   - `COALESCE(s.apto, <heurística source>) = 1` — por la columna estampada, no por el string
     `source` (`advisor_alerts.py:253-273`, con el comentario que explica que el filtro por string
     se equivocaba en las dos direcciones).
   - Piso de antigüedad de 4 días (`_floor`, `advisor_alerts.py:244`); base más vieja → ese cliente
     no se evalúa.
   - **Se excluye HOY a propósito**: el browser escribe un snapshot intradiario al abrir la app y
     si ése fuera la base el "% del día" se compararía contra sí mismo (`advisor_alerts.py:246-249`).
5. **Descuenta los flujos** posteriores a la base (`_net_deposited_now`) para que un depósito no se
   lea como suba (`advisor_alerts.py:284-289`).
6. **Edge-trigger + 1 aviso por cliente por día** (`advisor_alert_state.armed` / `last_fired_date`).

**Cómo se notifica** — `_deliver` (`advisor_alerts.py:136-157`): Web Push (`main._send_push_to_user`
con `url:'/alertas'`) y/o email (`emails.send_alert_email` con `cta_path='/clientes'`).
El evento se **sella en DB ANTES de mandar** y se hace `conn.commit()` para no tener el write-lock
tomado durante dos llamadas HTTP (`advisor_alerts.py:304-321`).

**Historial**: `advisor_alert_events`, se **purga solo a los 3 días** (`HISTORY_DAYS = 3`, `advisor_alerts.py:28`) — "es un feed, no un archivo".

**Quién lo corre** `[V]`: **no tiene cron propio**. Se evalúa dentro de
`GET|POST /api/alerts/evaluate` (`main.py:33590-33626`), el mismo cron ~10 min de las alertas de
precio, con `try/except` propio para que un fallo del motor de precios no se lleve el del libro
(`main.py:33617-33624`).

Frontend: `frontend/src/components/advisor/AdvisorAlerts.jsx` (card por tipo + historial),
`ClientMoveAlert.jsx` (la config), `BriefPrefs.jsx` (los toggles del brief).

---

## 7. Brief e Informe del período — son dos cosas distintas

### 7.1 El brief diario (`advisor_brief.py`) — email automático al ASESOR

`[V]` **Dos entregas por día hábil**, ancladas a la rueda argentina (`advisor_brief.py:1-19`):

| Kind | Hora | Contenido |
|---|---|---|
| `open` | ~11:00 ART (abre BYMA) | **El plan del día**: a quién llamar (las colas del libro, top 5), eventos de HOY de activos del libro con atribución, invitaciones por vencer (≤2 días) |
| `close` | ~17:15 ART (cerró BYMA) | **El resultado del día**: Δ del día valuando EN VIVO vs el último snapshot apto, mejor y peor cliente, los activos que mandan (motor estrella), flujos del mes |

**Por qué el Δ del cierre no sale de snapshots** `[V]`: el cron nocturno corre 23:59, así que a las
17:15 el último snapshot es el de ayer. Se valúa en vivo con `live_book_values`
(`advisor_brief.py:83-157`), que además **persiste** los precios traídos en `asset_last_price`
("beneficia al resto de la app", `advisor_brief.py:127`) y comparte el `price_cache` entre
asesores dentro de la misma corrida.

`[V]` Bug documentado y arreglado en `live_book_values`: los símbolos se arman **por cliente**,
porque `build_price_symbols` mira los nombres de broker sin `user_id` y un `Balanz` ARS de un
cliente arrastraba al `Balanz` USD de otro → clave de precio equivocada y una caída fantasma
(`advisor_brief.py:109-119`).

**Entrega**: email vía `billing/emails.send_advisor_brief` (`backend/billing/emails.py:1447`),
al `users.email` **del asesor**. **No hay link público ni versión web del brief.**

**Idempotencia**: `advisor_brief_log(advisor_uid, kind, date)` PK compuesta → re-correr el cron no
duplica (`advisor_brief.py:65-78`).

**Preferencias**: `advisor_profile.brief_open` / `brief_close`, default 1
(`advisor_brief.py:53-62`; endpoints `main.py:33998` / `34011`; UI `BriefPrefs.jsx`).

**Disparo**: `GET|POST /api/advisor/brief/run-cron?kind=open|close` (`main.py:33937`),
autenticado por `ADVISOR_BRIEF_TOKEN` (fallback `SNAPSHOT_CRON_TOKEN`). Corre en un thread de
fondo con guarda anti-doble-corrida (`_brief_cron_running`, `main.py:33962-33977`) porque el fetch
de precios del cierre tarda más que el timeout del gateway.

**Vista previa para el asesor**: `GET /api/advisor/brief/preview?kind=` (`main.py:33979`), sin
mandar email.

`[V]` Nota de acoplamiento: `build_brief` llama a `main.advisor_book(uid=uid)` **como función
plana** (`advisor_brief.py:225`), no vía HTTP. Funciona porque `advisor_book` abre su propia
conexión y hace su propio `_require_advisor`.

### 7.2 El informe del período (`advisor_reports`) — el entregable que firma el asesor

`[V]` `POST /api/advisor/reports/generate` (`main.py:35943-35988`), rate limit 6/300 s.

```
Body: AdvisorReportIn { period_start, period_end, client_uids? (None = todos), note? (≤1200) }
```

Genera **uno por cliente, en lote** (cap 200), cada uno con:
- `payload` JSON **congelado** al momento de generar (`advisor_reports.payload`)
- `token` = `_gen_reset_token()[:22]` → URL `<frontend>/i/<token>`
- `wa_text` = versión WhatsApp determinística (`_report_wa_text`, `main.py:35877`)

Clientes sin vínculo activo van a `skipped` con razón (`main.py:35965-35968`).

**Contenido del payload** — `_advisor_report_payload` (`main.py:35615-35875`) `[V]`:
`branding` (nombre + matrícula CNV + logo del asesor), `client_label`, `period`, `value_end_usd`,
`market_usd`, `flows_usd`, `ret_pct`, `mep_var_pct` (benchmark MEP **sobre la misma ventana**
base→as_of, no start→end), `tc_mep`, `series` (cap 60 puntos), `holdings` (top 6),
`movements` (últimos 15) + `movements_total`, `movers`, `note`, `claimed`, y las banderas
de honestidad: `value_as_of`, `base_date`, `base_note ∈ {onboarding, stale, None}`,
`holdings_basis ∈ {market, cost}`, `holdings_as_of`, `medicion_dudosa`.

**Guardas de "no publicar un número inventado"** `[V]` — este archivo es donde más se nota la
cicatriz de audits previos:

- La serie sale de `twr.serie_medible(...)["medibles"]`, no de `snapshots` crudo. El comentario
  dice que antes traía también las fotos al costo y "el informe FIRMADO publicaba (medido)
  −47,26 % · −US$65.966,54 de mercado para un mes sin una sola operación" (`main.py:35692-35697`).
- **Modified Dietz simple** para el `ret_pct` (flujos ponderan mitad), con base mínima
  US$ 100 (`main.py:35700-35702`); el comentario cita un audit donde se mostraba +63 % para un mes
  de +3 %.
- Si hay un **corte dudoso** dentro de la ventana, `ret_pct` y `market_usd` quedan en `None` y
  `base_note='dudosa'` (`main.py:35703-35716`). Números medidos citados: tres cuentas publicaban
  +472,9 %, −100 % y −90,3 %.
- Distinción `onboarding` vs cuenta nueva de verdad (`main.py:35657-35682`): si el cliente tiene
  prehistoria (`monthly_entries` / `operations` / `positions` anteriores al período), la base cero
  presentaría depósitos viejos como aportes del período.
- `_advisor_branding` (`main.py:35601-35613`): sin perfil configurado usa **sólo** `users.name`,
  **jamás el localpart del email** — "esto termina en una página pública sin auth; audit".

**Historial**: `GET /api/advisor/reports` (`main.py:34419`) devuelve los últimos 200 con
`estado ∈ {activo, vencido, revocado}` — al asesor **sí** se le distingue por qué un link no abre.
El comentario dice por qué existe: "los links públicos vivían solo en el `useState` del modal —
cerrarlo era perderlos" (`main.py:34421-34422`).

UI: `ReportModal` en `frontend/src/pages/AdvisorDashboard.jsx:742`; botón de revocar en
`AdvisorDashboard.jsx:785-791`.

### 7.3 ⚠️ El link público `/i/{token}` — cómo se protege

`[V]` `GET /api/reports/public/{token}` (`main.py:36005-36037`). **No requiere login.**
Frontend: `frontend/src/pages/ReportPublic.jsx`, ruta `/i/:token` registrada **tres veces**
(flujo autenticado `App.jsx:199`, `App.jsx:294`, y flujo sin login) — el comentario explica que un
cliente logueado caía al catch-all y aterrizaba en Home (`App.jsx:196-199`).

Capas de protección, todas verificadas:

| Capa | Implementación | Línea |
|---|---|---|
| **Entropía del token** | `secrets.token_urlsafe(32)[:22]` → 22 chars base64url ≈ **131 bits** | `35972` + `2943-2945` |
| **Validación de forma** | rechaza `len < 10` o `> 40` antes de tocar la DB | `36014` |
| **Rate limit** | 30 llamadas / 300 s **por IP** | `36013` |
| **TTL** | `REPORTS_TTL_DAYS`, default **180 días**, `0` = para siempre | `_report_ttl_days`, `35990-36003` |
| **Revocación** | `POST /api/advisor/reports/{id}/revoke?revoke=true|false`, con `WHERE id=? AND advisor_uid=?` | `36039-36063` |
| **404 uniforme** | revocado, vencido e inexistente devuelven **el mismo 404**, no 410 | `36021-36029` |
| **`noindex`** | `<PageMeta noindex={true} />` en la página | `frontend/src/pages/ReportPublic.jsx:64` |
| **Sin uid interno** | el label cae a `name → label → "Cliente"`, nunca `f"Cliente {uid}"` | `35954` |

El razonamiento del 404 uniforme está escrito: "distinguirlos le confirmaría a quien tenga un link
filtrado que el informe EXISTE y de cuándo es. Para el asesor la diferencia sí se ve, en su
historial" (`main.py:36009-36012`). El del TTL también: el link "viaja por WhatsApp — se reenvía,
queda en un chat grupal, en una captura — y sin vencimiento la cartera y el rendimiento del cliente
quedan legibles para siempre por quien tenga la URL" (`main.py:35991-35999`).

⚠️ **Lo que el link público NO tiene**: contraseña, segundo factor, límite de aperturas, ni
registro de accesos. `[V]` No hay ninguna columna de `hits`/`opened_at` en `advisor_reports`
(`main.py:2171-2184`) ni ningún `INSERT` de auditoría en `report_public`. Un link filtrado se
detecta sólo si alguien lo cuenta.

⚠️ `[V]` **`revoke` es reversible por query param** (`?revoke=false` reactiva el link,
`main.py:36039-36041`). Está bien pensado (un revoke por error se deshace) pero significa que el
"corte" no es definitivo.

---

## 8. Operaciones en lote (`advisor_op_batches`)

`[V]` Core en `_advisor_group_op_apply` (`main.py:36179-36290`), compartido por **dos** superficies:
el endpoint `POST /api/advisor/group-op` (`36292`) y el registro por chat
`register_group_op` (`36392`).

**Tablas** (`main.py:866-884`):
```
advisor_op_batches(id, advisor_uid, asset, op_kind DEFAULT 'buy', created_at, undone_at)
advisor_op_batch_items(id, batch_id, client_uid, position_id, status,
                       cost_debited, autodep_native, autodep_usd, autodep_ym)
```

### 8.1 El flujo del modal (3 pasos)

`[V]` `GroupOpModal` en `frontend/src/pages/AdvisorClients.jsx:698`.
Paso 1 la operación común; paso 2 para quiénes; paso 3 la tabla de asignación con
**broker/cantidad/precio por fila** (las posiciones viven por broker).

`GET /api/advisor/group-op/prep?asset=&currency=` (`main.py:36092-36174`) precalcula el broker
sugerido por cliente, en este orden: (1) donde YA tiene ese activo, (2) su único broker,
(3) el primero — **filtrando por familia de moneda** (ARS vs no-ARS) si viene `currency`.
Devuelve también `has_asset` y `permission`.

### 8.2 Semántica del apply

`[V]` (`main.py:36212-36242`): las filas se **pre-validan** una por una; las inválidas van a
`skipped` con razón explícita y **no bloquean el resto**. Las válidas se aplican **en UNA
transacción** (o entran todas o ninguna).

Razones de `skipped`:

| Razón | Chequeo |
|---|---|
| `duplicado en el lote` | `seen` set |
| `sin vínculo activo` | no está en `links` |
| `vínculo de solo lectura` | `permission != 'read_write'` (`36224-36226`) — "escribirle la cartera a un cliente linked es ilegal acá" (`36192`) |
| `no tiene el broker 'X'` | `(cid, broker)` no está en `brokers` |
| `moneda del lote (X) ≠ moneda del broker 'Y' (Z)` | familias ARS vs no-ARS, con hint de crear el sub-broker dólar |

Cada fila se inserta vía `_insert_manual_position` (el mismo camino que una carga manual), y el
item guarda `cost_debited` + el autodepósito que se disparó (`autodep_native`, `autodep_usd`,
`autodep_ym`) para poder revertir exacto.

`[V]` ⚠️ **Sólo COMPRAS**: `INSERT INTO advisor_op_batches (…, op_kind) VALUES (?,?, 'buy')` está
**hardcodeado** (`main.py:36246-36248`). La columna `op_kind` existe pero nunca toma otro valor.
El prompt de la IA lo confirma del lado del producto: "Solo COMPRAS: si dicta una VENTA, decile
que por ahora las ventas se registran cliente por cliente" (`main.py:20694`).

### 8.3 El undo

`[V]` `POST /api/advisor/group-op/{batch_id}/undo` (`main.py:36584-36683`). Best-effort e
idempotente (409 si ya fue deshecho). Por cada item:

- Re-chequea `permission='read_write'` **ahora** — si el vínculo se revocó, el item queda `'ok'`,
  el lote **no** se marca deshecho y se puede reintentar (`36614-36622`).
- `DELETE FROM positions WHERE id=? AND user_id=?` y exige `rowcount==1`; si otro undo concurrente
  la borró, **no re-acredita** (evita el doble crédito, `36644-36651`).
- **Crédito neto = `cost_debited` − `autodep_native`** para que el cash vuelva al nivel PREVIO —
  el comentario cita el audit: "acreditar el costo entero dejaba cash y capital aportado fantasma
  en cada cuenta sin fondos" (`36652-36655`).
- Revierte el flujo mensual con montos **negativos** (broker y `global`) y repara la cadena
  (`36656-36681`).
- Lee `cost_debited` **del item**, no de la fila viva: "recomputar desde la fila viva permitía que
  una edición del cliente infle/desvíe el crédito" (`36634-36639`).

### 8.4 El lote por chat

`[V]` `_register_group_op_handler` (`main.py:36392+`). Sólo en book-mode; re-chequea
`get_tier(conn, uid) != 'advisor'` (`36399-36400`). Resuelve nombres dictados contra el roster
por label o `users.name`, sin tildes y case-insensitive (`_resolve_group_clients`, `36317-36351`),
y **repregunta** ante ambigüedad o cliente desconocido devolviendo la lista de nombres.
Confirmación **enforced en turno distinto** (mismo patrón que `register_trade`), y hay un undo del
último lote con TTL de 24 h (`_LAST_GROUP_BATCH`).

---

## 9. IA del libro (book-mode)

`[V]` `book_mode = (tier == "advisor" and uid == _auth_uid)` — es decir, el asesor chateando
**en su propio nivel**, sin contexto de cliente (`main.py:28352`).

Diferencias con el chat retail, todas verificadas:

| Aspecto | Book-mode | Normal |
|---|---|---|
| Modelo | **Sonnet** (`_llm.MODEL_SONNET`) | Haiku | `28363` |
| Tools | `_AI_TOOLS_ADVISOR` — incluye `register_group_op`, **excluye** `register_trade`/`undo_last_trade` | `_AI_TOOLS` / `_AI_TOOLS_FREE` | `28357` |
| Contexto | El snapshot del frontend (cuenta vacía del asesor) **se ignora**; se arma server-side con `_advisor_book_chat_context` | snapshot del browser enriquecido | `28436-28442` |
| System prompt | `_AI_CHAT_SYSTEM + _AI_CHAT_SYSTEM_ADVISOR` | base | `28410-28411` |

`_advisor_book_chat_context` (`main.py:35425-…`) devuelve `aum`, `flows_month`, `star`, `queues`,
`distribution` + `clients[]` (roster con AUM, `ret_pct`, top tenencias) + `exposure[]` (por activo,
value/weight por cliente).

`[V]` **Mitigación de inyección de prompt**: los labels/nombres/activos los escribe el cliente y
van al prompt de Sonnet, así que `_ctx_txt` aplana `\r\n\t` y capea a 60 chars
(`main.py:35444-35448`).

`[V]` El comentario en `advisor_book` avisa que `ret_pct` no es sólo un número de pantalla: entra
al prompt "donde el prompt le ORDENA al modelo rankear clientes con él", y por eso lleva el filtro
`_es_base_de_mercado` (`main.py:37062-37070`).

`[V]` La IA **nunca registra sola** desde el libro por la vía visual: emite el deep-link
`/clientes?groupop=TICKER` que abre el modal precargado
(`frontend/src/pages/AdvisorClients.jsx:88-105`). Por chat sí puede registrar, pero con
confirmación en turno separado.

---

## 10. Cómo se ve la app cuando sos asesor

`[V]` No hay rutas nuevas salvo `/clientes`. Las mismas rutas **cambian de componente**:

| Ruta | Asesor sin contexto | Con contexto de cliente / retail |
|---|---|---|
| `/` | redirige a `/dashboard` (`App.jsx:161-177`) | Home / Mercado |
| `/dashboard` | `<AdvisorDashboard />` (`Dashboard.jsx:56`) | `<PersonalDashboard />` |
| `/novedades` | `<AdvisorNovedades />` (`Novedades.jsx:42`) | `<PersonalNovedades />` |
| `/clientes` | `<AdvisorClients />` (`App.jsx:222`) | redirige a `/` (`AdvisorClients.jsx:137`) |
| `/alertas` | alertas del libro | alertas de precio |
| `/planes` | pantalla "Tenés el Plan Asesor" + WhatsApp (`Planes.jsx:318-343`) | cards de Free/Plus/Pro |

`[V]` **El asesor no tiene cartera propia** — es decisión de producto, no restricción técnica:
el sidebar oculta los grupos Tu Cartera/Mercado/Análisis y el ítem Importar cuando
`atOwnLevel = isAdvisor && !clientCtx` (`Sidebar.jsx:100-109`). El comentario: "si quiere invertir
él, se agrega como su propio cliente". `[I]` A nivel API nada le impide tener posiciones propias;
es sólo la nav.

Entrar/salir de un cliente: `AdvisorContext.enterClient/exitClient`
(`frontend/src/contexts/AdvisorContext.jsx:38-51`), que además fuerza `refreshPlanFeatures()`
porque el tier efectivo cambia. La banda violeta persistente es
`components/advisor/ClientContextBar.jsx`.

---

## 11. Diferencias con el producto retail

| Dimensión | Retail | Asesor |
|---|---|---|
| **Objeto central** | una cartera | el libro (N carteras) |
| **Home** | Dashboard personal | Tu libro (AUM, estrella, colas, composición) |
| **Novedades** | activos de su cartera | activos de **cualquier** cliente, con atribución ("lo tienen 3 de tus clientes") |
| **Alertas** | precio objetivo + variación % de un activo | variación % de la **cartera completa** de un cliente |
| **Emails automáticos** | alertas, lifecycle | **+ brief 2×/día** anclado a BYMA |
| **IA** | Haiku, tools sobre su cartera | **Sonnet**, tools de libro, contexto cross-cliente |
| **Registro de operaciones** | una por una | **block trade a N clientes** + undo por lote |
| **Entregable** | — | **informe con marca propia** (nombre, matrícula CNV, logo) y link público |
| **Segmentación** | — | **grupos dinámicos** por reglas |
| **Cuota IA** | por tier | tier `advisor` = niveles Pro (60/60/40) — `backend/ai/quota.py:107-113` |
| **Brokers** | 1 (Free) / 3 (Plus) / ∞ (Pro) | ∞ (`backend/ai/plan.py:103`) |
| **Billing** | Rebill self-serve | **no existe** |

---

## 12. Qué está implementado, qué a medias, qué no está

### Implementado y vivo

- Los **tres** caminos de alta, con sus guardas de rate limit, cooldown, expiración y concurrencia.
- El contexto de cliente con validación server-side en cada request.
- Los 5 endpoints del libro + composición con las tres tortas.
- Grupos dinámicos con 6 tipos de condición.
- Brief 2×/día + alertas de movimiento + informe con marca y link público revocable.
- Block trade con undo exacto (incluido el autodepósito).
- IA del libro con Sonnet y registro grupal por chat.
- Cobertura de tests sustancial: `backend/tests/test_advisor_plan.py` (3.960 líneas, ~180 tests)
  + `test_advisor_composition.py` (1.094) + `test_advisor_report_revoke.py` +
  `test_advisor_schema_migration.py` + `test_grant_comp_advisor.py` + `test_over_gate_asesor.py` +
  `test_tenencia_gate_asesor.py`. Incluye una clase entera de IDOR (`ResolverIdorTest`,
  `test_advisor_plan.py:99-201`).

### A medias

**A-1 `[V]` — TWR: existe el motor per-cliente pero no el composite, y el endpoint está desconectado.**
`GET /api/advisor/twr` no lo llama nadie desde el frontend (grep exhaustivo en `frontend/src`);
sí se usa `data-health`. El composite ponderado por capital está declarado como "Fase 2"
(`advisor_twr.py:83-85`). El endpoint muerto además **escribe** (`twr.sellar` por cliente).

**A-2 `[V]` — Block trade sólo compra.** `op_kind` hardcodeado `'buy'` (`main.py:36247`). Las
ventas hay que hacerlas cliente por cliente, y el prompt de la IA se lo dice al asesor.

**A-3 `[V]` — El pool de IA no está centralizado en el asesor.** El docstring de
`backend/ai/quota.py:104-107` describe un pool propio; el código cobra en los contadores del
cliente (`main.py:28322`, comentarios en `2759-2763` y `28310-28311` que remiten a una "F5").

**A-4 `[V]` — `permission='read'` (vínculo `linked` de sólo lectura) tiene enforcement pero
superficie de UI mínima.** Se puede elegir al pedir acceso (`AdvisorClients.jsx:618-641`) y se
respeta en `_resolve_client_context` (`main.py:2801-2802`), en el block trade
(`main.py:36224-36226`) y en el undo (`main.py:36614-36622`). Pero **no hay ningún endpoint para
cambiar el `permission` de un vínculo existente** — `AdvisorClientPatchIn` sólo acepta
`label/notes/phone` (`main.py:34356-34359`). Para pasar de `read` a `read_write` hay que revocar y
volver a pedir.

**A-5 `[V]` — Un vínculo revocado no se re-activa desde la UI.** Ver §1.3.

### No está

**N-1 `[V]` — Billing del Plan Asesor.** `SubscribeIn.plan` tiene el patrón `^(plus|pro)$`
(`main.py:26500`) y `pricing.Plan = Literal["plus", "pro"]` (`backend/billing/pricing.py:71`).
El único camino para llegar a tier `advisor` es
`POST /api/admin/billing/grant-comp?plan=advisor&days=N` (`main.py:19844-19884`), con el
comentario "'advisor' habilita el Plan Asesor a pilotos sin construir billing (F4)"
(`main.py:19878`). La pantalla `/planes` del asesor lo asume: "escribinos directo"
+ link de WhatsApp (`frontend/src/pages/Planes.jsx:326-338`).
`[I]` Es decir: el producto está construido, el plan se vende y se factura fuera del sistema.
El vencimiento sí lo maneja la app — el grant deja `credit_active_until` y
`_paid_override_expired` corta en tiempo real (`backend/ai/quota.py:121-146`).

**N-2 `[V]` — No hay límite de clientes por plan.** Sólo el cap duro global de 500
(`ADVISOR_MAX_CLIENTS`). La UI de `/planes` habla de "límite de clientes" como algo negociable por
WhatsApp (`Planes.jsx:330-332`), pero en el código no existe ningún tier de asesor con cupos.

**N-3 `[V]` — No hay landing pública del Plan Asesor.** Grepeé "asesor" en
`frontend/src/pages/Landing.jsx`: cero hits. La única superficie pública es
`/guia/asesores` (`frontend/src/pages/guia/Asesores.jsx`), que es manual de uso, no venta.

**N-4 `[V]` — No hay multi-asesor / equipo / firma.** `advisor_clients` no tiene concepto de
organización; un cliente puede tener N asesores (la UNIQUE es por par) pero cada asesor ve su
propio libro y no hay roles ni delegación.

**N-5 `[V]` — No hay auditoría de accesos del asesor a la cuenta del cliente.** El
`consent_ref` guarda **cómo nació** el vínculo, pero no hay log de qué miró ni qué escribió el
asesor dentro de la cuenta. `[I]` Para un producto regulado (el propio informe publica matrícula
CNV) es una ausencia notable; el único rastro son las filas que el block trade deja en
`advisor_op_batch_items`.

**N-6 `[V]` — El brief no tiene versión web.** Sólo email; hay `preview` para el asesor pero no
un link compartible ni historial de briefs enviados (`advisor_brief_log` guarda sólo que se mandó).

---

## 13. Otras observaciones de código

**O-1 `[V]` — Auto-reparación de esquema en caliente en un `PATCH`.**
`advisor_set_profile` captura `ERR_OPERACIONAL` al escribir `logo_data`, corre
`ALTER TABLE advisor_profile ADD COLUMN logo_data TEXT` y reintenta (`main.py:35925-35937`).
Funciona, pero es un DDL disparado desde un request de usuario.

**O-2 `[V]` — Inconsistencia de tamaño del logo.** El validador Pydantic acepta hasta
200.000 caracteres (`AdvisorProfileIn.logo_data`, `main.py:35586`); el comentario del DDL dice
"data-URI (raster, ≤ ~300KB)" (`main.py:2191`). El regex sí restringe a
`data:image/(png|jpeg|webp);base64,` — nada de SVG (`main.py:35590-35598`).

**O-3 `[V]` — PK rara en el esquema Postgres generado.**
`advisor_alerts.advisor_uid` y `advisor_profile.advisor_uid` salen como
`bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY` (`backend/schema_pg.sql:49` y `252`), porque
`mkschema.py` traduce todo `INTEGER PRIMARY KEY` de SQLite a identidad (`backend/scripts/mkschema.py:66-75`).
No rompe nada — el código siempre inserta el `advisor_uid` explícito — pero semánticamente la
columna es una FK a `users(id)`, no un autoincremental.

**O-4 `[V]` — Falta de FK en la mayoría de las tablas advisor.**
Sólo `advisor_clients` y `advisor_op_batches` declaran `REFERENCES users(id)`
(`main.py:847-848`, `868`). `advisor_groups`, `advisor_alerts`, `advisor_claim_tokens`,
`advisor_link_requests`, `advisor_reports`, `advisor_profile`, `advisor_brief_log` no.
El borrado de cuenta compensa a mano (`main.py:3879-3905`, `20304-20350`) — funciona hoy, pero es
integridad por convención.

**O-5 `[V]` — `advisor_book_history` no filtra base de mercado.** Ver §4.4.

**O-6 `[V]` — Un 502 en el envío del claim deja el token creado.** Ver §2.3, punto 6.

**O-7 `[V]` — `advisor_groups.classify` es un segundo clasificador de activos.** El propio
comentario de `/book/composition` documenta que manda 9,4 % de las posiciones reales a "otro",
dice `us_stock` para un AAPL en broker ARS y "otro" para AL30 (`main.py:37294-37303`) — y por eso
la composición clasifica en el frontend. Pero **los grupos siguen usando el clasificador Python**
(`advisor_groups.py:223`), así que un grupo "30 % en acciones argentinas" corre sobre el
clasificador que el propio repo declara defectuoso.

---

## 14. Variables de entorno que toca el producto asesor

`[V]` (sólo nombres, no valores):

| Variable | Uso | Línea |
|---|---|---|
| `ADVISOR_BRIEF_TOKEN` | auth del cron del brief | `main.py:33946` |
| `SNAPSHOT_CRON_TOKEN` | fallback del anterior | `main.py:33947` |
| `ALERTS_CRON_TOKEN` | cron que evalúa también las alertas del libro | `main.py:33596` |
| `REPORTS_TTL_DAYS` | TTL del link público del informe (default 180, `0` = infinito) | `main.py:36000` |
| `MP_FRONTEND_BASE_URL` | base de los magic links (`/claim`, `/acceso`, `/i/<token>`) | `_frontend_url` |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` | push de las alertas del libro | `main.py:34056,34125-34127` |
| `RESEND_API_KEY` | envío real de los mails (sin ella, `sent=False` no es falla) | vía `billing.emails._api_key` |
