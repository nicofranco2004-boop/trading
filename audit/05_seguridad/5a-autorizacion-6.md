# 5a · Autorización entre usuarios — tramo 6 de 6 (`main.py` 33880 → 38029)

**Área:** los 43 endpoints del final de `backend/main.py`. Casi todo producto asesor
(`/api/advisor/*`), más push, el claim/link-request de cuentas y tres endpoints públicos.

**Veredicto de una línea: cero CRÍTICOS.** El tramo es la superficie más peligrosa del
sistema y está construido con cuidado: **los 27 endpoints `/api/advisor/*` gatean con
`_require_advisor` y NINGUNO acepta por HTTP la lista de clientes sobre la que opera — la
derivan siempre de `advisor_clients` con `advisor_uid=? AND status='active'`**. Los tres
que sí reciben un `client_uid` por ruta pasan por `_advisor_own_link`. Lo que encontré son
**huecos de REVOCACIÓN** (el vínculo se corta y quedan cosas vivas del otro lado) y un
`DELETE` cross-tenant disparado por un GET.

---

## Método

Auditoría de **lectura + análisis estático**, sobre la copia congelada
`/tmp/rendi-main` (commit `b74f450f`, 38.029 líneas en `backend/main.py`), verificada
antes de empezar.

**Qué EJECUTÉ** (MEDIDO):

- `audit/_scripts/5a_autorizacion_6_tramo.py` — script propio, solo lectura, que parsea el
  archivo y para cada endpoint del tramo extrae: método, ruta, `Depends(...)` de auth,
  si el prefijo cae en `CLIENT_CTX_EXEMPT_PREFIXES` (reimplementando el match por límite
  de segmento de `_resolve_client_context`, `main.py:2779-2781`), y si el cuerpo llama
  `_require_advisor` / `_advisor_own_link` / lleva `advisor_uid=?` en algún `WHERE`.
  Salida completa pegada más abajo. Detectó **44** decoradores en el rango: los 43 del
  inventario más `@app.api_route("/api/advisor/brief/run-cron")` (33936), que el
  inventario no lista porque no usa `@app.get/@app.post`. Lo audito igual.
- `awk` sobre `_inventario_endpoints.txt` para fijar el tramo.
- `git show origin/main:backend/main.py` para chequear deriva de los 3 hallazgos
  principales: **siguen vivos** en `origin/main` (`897b0d63`), corridos ~25 líneas.

**Qué NO ejecuté:** ninguna petición a producción, ningún ataque, ningún levantamiento
del backend. No hay pruebas de explotación en vivo. Todo lo que digo sobre comportamiento
en runtime es DEDUCIDO del código leído entero (leí el cuerpo completo de los 44
handlers, no solo la firma) o ESTRUCTURAL (falta una cláusula, se verifica con grep).

**Supuestos:**

- `get_tier` (`ai/quota.py:148-223`) es la única fuente del tier; leí la función entera.
  Una cuenta shadow (`managed_by` seteado, `approved=0`) resuelve `"pro"`, **no**
  `"advisor"` → no puede entrar a `/api/advisor/*`. Un `is_admin` sin `users.tier='advisor'`
  resuelve `"admin"` → tampoco. Ambas cosas están comentadas como intencionales.
- El frontend no es parte de mi área; cuando un dato sale del backend a una página pública
  lo evalúo por el dato, no por cómo se pinta.
- El **modelo** del vínculo asesor-cliente lo audita otro agente. Lo que toco de modelo
  (H-5) queda anotado sin desarrollar.

---

## Resumen — hallazgos por severidad

| id | sev | título | archivo:línea | evidencia |
|----|-----|--------|---------------|-----------|
| H-1 | **ALTO** | Revocar el vínculo NO mata los informes públicos ya generados: la cartera del ex-cliente sigue legible 180 días y él no tiene forma de bajarla | `main.py:34609`, `35241`, `36005` | ESTRUCTURAL |
| H-2 | **MEDIO** | `/api/advisor/reports` sigue sirviendo nombre, teléfono y links de clientes con vínculo **revocado** (LEFT JOIN sin `status='active'`, `u.name` en vivo) | `main.py:34419-34437` | ESTRUCTURAL |
| H-3 | **MEDIO** | `/api/advisor/brief/run-cron`: efecto masivo (emails a todos los asesores) por **GET**, con el token aceptado en el **query string**, y fallback al secreto de snapshots | `main.py:33936-33957` | ESTRUCTURAL |
| H-4 | **MEDIO** | GET que escribe cross-tenant: `/api/advisor/alerts` dispara un `DELETE` sobre `advisor_alert_events` de **todos** los asesores, sin filtro de dueño y con el error tapado | `advisor_alerts.py:81-97` + `main.py:33880-33893` | ESTRUCTURAL |
| H-5 | **MEDIO** | Reclamar la cuenta no le pregunta al cliente si el asesor conserva `read_write`: post-claim el asesor sigue pudiendo escribirle la cartera por block trade | `main.py:35106-35160`, `36292` | DEDUCIDO |
| H-6 | **BAJO** | Rechazar un pedido de acceso no exige autenticación y dispara un cooldown de 30 días contra el asesor | `main.py:35034-35056` | ESTRUCTURAL |
| H-7 | **BAJO** | `/api/auth/link-request/preview` entrega nombre, matrícula y logo (≤200 KB) del asesor para tokens ya vencidos, rechazados o cancelados | `main.py:34993-35031` | ESTRUCTURAL |
| H-8 | **BAJO** | `/api/health` es público y publica el SHA del commit desplegado | `main.py:34270-34294` | ESTRUCTURAL |

No hay CRÍTICO en este tramo. Lo digo explícito porque el criterio del prompt común es
"un usuario cualquiera llega a datos de otro": **no encontré ningún camino así acá**.

---

## La tabla — los 43 endpoints (+ el 44°)

`sesión` = qué `Depends` valida identidad. `propiedad` = qué comprueba que el recurso
sea del que llama. Todos los `/api/advisor/*` están además bajo `_require_advisor`
(tier `advisor` exacto) y bajo `CLIENT_CTX_EXEMPT_PREFIXES` (el header
`X-Rendi-Client-Id` se ignora y `uid` es siempre el asesor real).

| # | línea | mét. | ruta | qué hace | valida sesión | valida propiedad | veredicto |
|---|-------|------|------|----------|---------------|------------------|-----------|
| 1 | 33880 | GET | `/api/advisor/alerts` | config de alerta de movimiento + historial 3 días | `get_current_user` + `_require_advisor` | n/a — no recibe id; `get_config`/`history` filtran por `advisor_uid` | **MEDIO: H-4** — el GET hace un `DELETE` global de `advisor_alert_events` |
| 2 | 33896 | POST | `/api/advisor/alerts/events/seen` | apaga el puntito del sidebar | ídem | n/a — `UPDATE … WHERE advisor_uid=? AND seen=0` | OK |
| 3 | 33911 | PATCH | `/api/advisor/alerts` | guarda umbrales/canal/alcance | ídem | `group_id` validado con `advisor_groups.get_group(conn, uid, gid)` (deriva de `list_groups(uid)`) → 404 si no es suyo | OK |
| 4 | 33936 | GET+POST | `/api/advisor/brief/run-cron` *(no está en el inventario)* | arma y **manda por email** el brief a TODOS los asesores | token de cron (`X-Cron-Token` **o `?token=`**) contra `ADVISOR_BRIEF_TOKEN`, con fallback a `SNAPSHOT_CRON_TOKEN` | n/a — es global | **MEDIO: H-3** |
| 5 | 33979 | GET | `/api/advisor/brief/preview` | preview del brief propio | `get_current_user` + `_require_advisor` | n/a — `build_brief(conn, uid, kind)`; `kind` validado contra allowlist | OK |
| 6 | 33998 | GET | `/api/advisor/brief/prefs` | lee prefs de email | ídem | n/a — `WHERE advisor_uid=?` | OK |
| 7 | 34011 | PATCH | `/api/advisor/brief/prefs` | escribe prefs | ídem | n/a — `WHERE advisor_uid=?` | OK |
| 8 | 34052 | GET | `/api/push/vapid-public-key` | devuelve la clave pública VAPID | **ninguna (público)** | n/a | OK — la clave pública no es secreta y el código lo dice |
| 9 | 34062 | POST | `/api/push/subscribe` | alta/upsert de la suscripción del device | `get_effective_user`, pero `/api/push` está EXENTO → resuelve al uid REAL | n/a — `user_id=uid` en el INSERT | OK |
| 10 | 34085 | DELETE | `/api/push/subscribe` | baja de la suscripción | ídem | `DELETE … WHERE user_id=? AND endpoint=?` | OK |
| 11 | 34101 | GET | `/api/push/status` | cuenta devices suscritos | ídem | n/a — `WHERE user_id=?` | OK |
| 12 | 34167 | POST | `/api/push/test` | manda un push de prueba a los devices propios | ídem | n/a — `_send_push_to_user(uid, …)` con `WHERE user_id=?` | OK |
| 13 | 34180 | GET | `/api/home/personal` | cards "lo que te afecta" (holdings + earnings) | `get_effective_user`, **NO exento** → hereda el contexto de cliente | n/a — todas las queries llevan `WHERE user_id=?` con el uid efectivo, ya autorizado por `_resolve_client_context` | OK — **único del tramo que hereda contexto**; correcto, es un endpoint de datos |
| 14 | 34252 | POST | `/api/admin/snapshots/run-now` | corre el snapshot diario a mano | `get_admin_user` | n/a — job global | OK |
| 15 | 34270 | GET | `/api/health` | ping + timestamp + commit SHA | **ninguna (público)** | n/a | **BAJO: H-8** — publica el SHA desplegado |
| 16 | 34304 | GET | `/api/stats/public` | count de usuarios verificados, cacheado 30 min | **ninguna (público)** | n/a — agregado, sin PII | OK |
| 17 | 34370 | POST | `/api/advisor/clients` | crea cliente shadow (user + vínculo `managed`/`read_write`) | `get_current_user` + `_require_advisor` | n/a — crea; cap 500 activos + rate-limit 30/60s; email sintético; hash random; `approved=0` | OK |
| 18 | 34419 | GET | `/api/advisor/reports` | historial de informes con link, teléfono y nombre del cliente | ídem | `WHERE r.advisor_uid=?` ✓ **pero** el `LEFT JOIN advisor_clients` no filtra `status='active'` y `u.name` se lee en vivo | **MEDIO: H-2** |
| 19 | 34465 | GET | `/api/advisor/clients` | roster + AUM + estado de invitación | ídem | `WHERE ac.advisor_uid=? AND ac.status='active'`; los `IN (…)` posteriores usan solo esos ids | OK |
| 20 | 34578 | PATCH | `/api/advisor/clients/{client_uid}` | edita label/notas/teléfono del vínculo | ídem | **`_advisor_own_link`** (404 si no hay fila activa) + los 3 `UPDATE` llevan `advisor_uid=? AND client_uid=?` | OK |
| 21 | 34609 | POST | `/api/advisor/clients/{client_uid}/revoke` | corta el vínculo, cierra claims y link-requests | ídem | **`_advisor_own_link`** ✓; los 3 `UPDATE` llevan `advisor_uid=?` | **ALTO: H-1** — la revocación no alcanza a `advisor_reports` |
| 22 | 34690 | POST | `/api/advisor/clients/{client_uid}/invite` | manda claim, o deriva a pedido de acceso si el email ya existe | ídem | **`_advisor_own_link`** ✓; rate-limit 10/300s + tope 8/día por ficha; 2 pasos con 409 antes de mailear a un tercero | OK |
| 23 | 34993 | GET | `/api/auth/link-request/preview` | quién pide acceso y a qué, antes de loguear | **ninguna (público, por token)** | el token ES la capability; `is_owner` compara `_optional_uid` con `req.client_uid`; email enmascarado | **BAJO: H-7** — sirve el payload aunque el pedido esté vencido/rechazado/cancelado |
| 24 | 35034 | POST | `/api/auth/link-request/respond` | acepta o rechaza el pedido | **ninguna (público, por token)**; aceptar exige login **y** `me == req.client_uid` | asimetría deliberada y documentada: rechazar solo pide el token | **BAJO: H-6** |
| 25 | 35060 | GET | `/api/auth/claim/preview` | quién invita y a qué ficha | **ninguna (público, por token)** | token no usado + no vencido; solo branding y label | OK |
| 26 | 35106 | POST | `/api/auth/claim` | setea contraseña, `approved=1`, `managed_by=NULL` | **ninguna (público, por token)** | token 256 bits, TTL 7 días, cierre con `WHERE used_at IS NULL` + `rowcount==1` (anti-carrera), re-chequeo de colisión de email | OK — muy bien hecho |
| 27 | 35176 | GET | `/api/me/advisor` | quién tiene acceso a MI cuenta + pedidos pendientes | `get_current_user` (`/api/me` exento) | `WHERE ac.client_uid=?` y `lr.client_uid=?` con el uid propio | OK |
| 28 | 35224 | POST | `/api/me/advisor/requests/{req_id}/respond` | sí/no desde adentro de la app | ídem | `SELECT … WHERE id=? AND client_uid=?` → 404 si el pedido es de otro | OK |
| 29 | 35241 | POST | `/api/me/advisor/{advisor_uid}/revoke` | el cliente corta el acceso del asesor | ídem | `WHERE advisor_uid=? AND client_uid=uid AND status='active'` → 404 si no existe | **ALTO: H-1** — el cliente corta el acceso pero no puede matar los informes ya emitidos |
| 30 | 35307 | GET | `/api/advisor/radar/events` | eventos de los activos del libro, con atribución por cliente | `get_current_user` + `_require_advisor` | n/a — el universo sale de `_advisor_ticker_holders` (`WHERE ac.advisor_uid=? AND ac.status='active'`); `days` acotado 1-365 | OK |
| 31 | 35373 | GET | `/api/advisor/radar/news` | ídem con noticias | ídem | ídem; `limit` acotado 1-100; los `LIKE` se arman con placeholders | OK |
| 32 | 35900 | GET | `/api/advisor/profile` | branding del asesor | ídem | n/a — `WHERE advisor_uid=?` | OK |
| 33 | 35910 | PATCH | `/api/advisor/profile` | guarda nombre, matrícula y logo | ídem | n/a — `advisor_uid=?`; `logo_data` validado por regex a `data:image/(png\|jpeg\|webp);base64` (SVG excluido a propósito), ≤200 KB | OK |
| 34 | 35943 | POST | `/api/advisor/reports/generate` | genera el lote de informes con token público | ídem | `data.client_uids` se **cruza** contra el dict de vínculos activos; el que no está va a `skipped` con motivo, no se genera | OK |
| 35 | 36005 | GET | `/api/reports/public/{token}` | el informe que abre el cliente: patrimonio, tenencias, movimientos | **ninguna (público, por token)** | token de 22 chars url-safe (~132 bits) + rate-limit 30/300s por IP + 404 uniforme para revocado/vencido (no confirma existencia) | **MEDIO: H-1** — el link no muere cuando muere el vínculo |
| 36 | 36039 | POST | `/api/advisor/reports/{report_id}/revoke` | corta (o reactiva) el link público | `get_current_user` + `_require_advisor` | `UPDATE … WHERE id=? AND advisor_uid=?` + 404 si `rowcount==0` ✓ | OK |
| 37 | 36092 | GET | `/api/advisor/group-op/prep` | tabla de asignación del block trade | ídem | n/a — roster derivado con `advisor_uid=? AND status='active'`; los `IN (…)` usan solo esos ids; `asset` va parametrizado | OK |
| 38 | 36292 | POST | `/api/advisor/group-op` | aplica UNA compra a N clientes | `get_current_user`; `_require_advisor` corre dentro de `_advisor_group_op_apply` | **por fila**: vínculo activo + `permission=='read_write'` + broker que existe en ESE cliente + familia de moneda compatible; las inválidas van a `skipped` | OK — la mejor validación por fila del tramo |
| 39 | 36584 | POST | `/api/advisor/group-op/{batch_id}/undo` | deshace el lote y re-acredita el cash | `get_current_user` + `_require_advisor` | `SELECT … WHERE id=? AND advisor_uid=?` ✓; además re-chequea `read_write` por item y el `DELETE FROM positions` lleva `AND user_id=?` con `rowcount==1` anti-doble-crédito | OK |
| 40 | 36947 | GET | `/api/advisor/book` | AUM, captación, distribución, colas | ídem | n/a — `_advisor_client_ids` (`advisor_uid=? AND status='active'`) | OK |
| 41 | 37661 | GET | `/api/advisor/book/composition` | composición valuada y agregada del libro | ídem | ídem; el docstring dice explícito "la lista de clientes se DERIVA de la DB — nunca se acepta por HTTP" | OK |
| 42 | 37795 | GET | `/api/advisor/book/asset-clients` | quién tiene ESE activo y cómo le fue | ídem | ids derivados; el `SELECT` de labels lleva `WHERE ac.advisor_uid=? AND ac.client_uid IN (…)` con ids ya filtrados (doble filtro) | OK |
| 43 | 37883 | GET | `/api/advisor/book/history` | serie histórica del AUM | ídem | ids derivados; `days` acotado 1-730 | OK |
| 44 | 37944 | GET | `/api/advisor/book/detail` | desglose por cliente del hero | ídem | ids derivados; labels con `advisor_uid=? AND status='active'` | OK |

**Conteo: 43 endpoints del inventario + `/api/advisor/brief/run-cron` (#4), que el
inventario no lista.** OK: 34. Con hallazgo: 10 (algunos comparten hallazgo).

---

## Las 5 preguntas del encargo, respondidas de frente

**1. ¿Valida sesión?** Sí, salvo 8 públicos, todos justificados:
`/api/health`, `/api/stats/public`, `/api/push/vapid-public-key` (públicos por diseño) y
5 por token de capability (`claim/preview`, `claim`, `link-request/preview`,
`link-request/respond`, `reports/public/{token}`), todos con rate-limit por IP.
`/api/advisor/brief/run-cron` va por token de cron. Los 27 `/api/advisor/*` restantes
además comprueban que el usuario **sea asesor de verdad**: `_require_advisor`
(`main.py:2823-2832`) exige `get_tier(conn, uid) == "advisor"` exacto — `is_admin` **no
alcanza**, y una cuenta shadow resuelve `"pro"`, no `"advisor"`.

**2. ¿Valida propiedad, o solo que estés logueado?** **No encontré un solo `WHERE id=?`
sin su `AND advisor_uid=?` (o su join a `advisor_clients`) en todo el tramo.** Los tres
ids de ruta que existen (`{client_uid}`, `{report_id}`, `{batch_id}`) se validan:
`_advisor_own_link` en los tres de cliente, `AND advisor_uid=?` + chequeo de `rowcount`
en report y batch. `client_uids` en `reports/generate` y `rows[].client_uid` en
`group-op` se cruzan contra el roster activo antes de tocar nada.

**3. ¿Toda query filtra por el dueño?** Una excepción, y es un `DELETE`: el `purge_old`
de `advisor_alerts` (H-4). El resto sí.

**4. ¿La exención de `X-Rendi-Client-Id` deja un agujero acá?** **No** (MEDIDO con el
script). De los 43, **42 son inmunes al header**: 27 por `/api/advisor`, 5 por
`/api/push`, 5 por `/api/auth`, 3 por `/api/me`, 1 por `/api/admin`, más 2 públicos fuera
de prefijo que no usan `get_effective_user`. El único que hereda el contexto es
`/api/home/personal` (34180) — y es correcto: es un endpoint de datos, y todas sus
queries llevan `WHERE user_id=?` con el uid que `_resolve_client_context` ya autorizó
contra `advisor_clients`. El match por límite de segmento (`path == p or
path.startswith(p + "/")`, `main.py:2779-2781`) impide que un futuro `/api/advisorX` o
`/api/metrics` quede exento por accidente — está bien resuelto.

**5. ¿Hay GET que escriban salteándose el gate `read_write`?** Tres, y solo uno importa:

- **`/api/advisor/alerts` (GET) → `DELETE FROM advisor_alert_events`** cross-tenant. Es H-4.
- `/api/advisor/brief/run-cron` acepta **GET** y manda emails masivos. Es H-3.
- `/api/advisor/radar/{events,news}` (GET) escriben en `financial_events`/`news`, que son
  tablas de cache **globales**, no per-usuario. No es un hallazgo: es el mismo SWR que
  `/events/portfolio`.

Ninguno de los tres escribe en la cuenta de un cliente, así que el gate `read_write` de
`_resolve_client_context` no aplica — pero el patrón "GET con efecto" está presente y
vale dejarlo escrito.

---

## Hallazgos

### [ALTO] H-1 · Revocar el vínculo no mata los informes públicos ya emitidos

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:34609` (revoca el asesor), `main.py:35241` (revoca el cliente),
`main.py:36005` (el link público), `main.py:36039` (el único revocador)

**Qué pasa.** `/api/advisor/reports/generate` congela en `advisor_reports.payload` un JSON
que contiene, para UN cliente: `value_end_usd` (su patrimonio), `holdings` (sus tenencias
con peso porcentual), `movements` + `movements_total` (sus movimientos del período),
`series` (su curva de valor), `ret_pct`, `movers` y `client_label`
(`main.py:35834-35866`). Ese payload lo sirve `/api/reports/public/{token}` **sin
autenticación de ningún tipo** — así tiene que ser, viaja por WhatsApp.

El problema es qué pasa cuando la relación termina. Grepeé **todos** los escritores de la
tabla:

```
$ grep -n "advisor_reports" backend/main.py
 3901:  DELETE FROM advisor_reports WHERE advisor_uid=? OR client_uid=?   ← borrar cuenta
20326:  DELETE FROM advisor_reports WHERE advisor_uid=? OR client_uid=?   ← admin
35977:  INSERT INTO advisor_reports …                                      ← generate
36053:  UPDATE advisor_reports SET revoked_at=? WHERE id=? AND advisor_uid=?  ← revoke
```

Los dos endpoints de revocación de vínculo **no aparecen**. Leí sus cuerpos enteros:
`advisor_revoke_client` (34609) toca `advisor_clients`, `advisor_claim_tokens` y
`advisor_link_requests`; `revoke_my_advisor` (35241) toca **solo** `advisor_clients`.

Resultado: cuando un cliente entra a Configuración y le corta el acceso a su asesor —el
gesto explícito de "no quiero que veas más mi cartera"— **los informes con su patrimonio
y sus tenencias siguen abriéndose para cualquiera que tenga la URL**, hasta que venza el
TTL. El default es **180 días** (`REPORTS_TTL_DAYS`, `main.py:36000`); si alguien lo puso
en `0`, es **para siempre**.

**Cómo se explota en la práctica.** No hace falta explotar nada: basta con que la relación
termine mal. El asesor conserva la URL (se la devuelve su propio `/api/advisor/reports`,
ver H-2), la reenvía a quien quiera, o simplemente el link ya está en un chat de WhatsApp
grupal, en una captura, en el historial de un mail reenviado. El cliente no tiene ninguna
manera de cerrarlo: **no existe ningún endpoint que le permita ni siquiera enterarse de
qué informes se emitieron sobre su cartera** — `/api/me/advisor` (35176) devuelve
asesores y pedidos pendientes, nada de informes. La única palanca es
`/api/advisor/reports/{id}/revoke`, y exige `_require_advisor` + `advisor_uid=?`: la tiene
exactamente la persona de la que el cliente se está separando.

**Qué queda expuesto.** Patrimonio total en USD, composición completa de la cartera con
pesos, movimientos del período y curva de valor de una persona identificada por
`client_label`. De una persona que ya ejerció su derecho a cortar.

**Otros call sites del mismo patrón (regla de propagación).** La revocación es incompleta
en más de un lado. Lo que sí se propaga y lo que no:

| Efecto colateral | `advisor_revoke_client` (34609) | `revoke_my_advisor` (35241) |
|---|---|---|
| `advisor_clients.status='revoked'` | ✅ | ✅ |
| `advisor_claim_tokens` pendientes | ✅ cierra | ❌ **no toca** |
| `advisor_link_requests` pendientes | ✅ cancela | ❌ **no toca** |
| `advisor_reports` (links públicos) | ❌ **no toca** | ❌ **no toca** |
| `push_subscriptions` del shadow | ❌ | ❌ |

O sea: el mismo fix de "cerrar lo que cuelga del vínculo" se aplicó en el revoke **del
asesor** y no se propagó al revoke **del cliente**, que es justamente el que se ejerce en
conflicto. Un cliente que revoca deja vivos su claim token pendiente **y** sus informes.

**Solución de fondo.** Un único helper `_revoke_link(conn, advisor_uid, client_uid)` que
cierre las cuatro cosas, llamado por los dos endpoints (y por el borrado de cuenta), en
vez de dos bloques de `UPDATE` que ya divergieron. Y, aparte del helper, darle al cliente
visibilidad y palanca propias: listar en `/api/me/advisor` los informes emitidos sobre su
cuenta y dejarlo revocarlos. Hoy el dueño del dato es el único que no puede tocarlo.

---

### [MEDIO] H-2 · El historial de informes no filtra por vínculo activo

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:34419-34437`

**Qué pasa.** La query es:

```sql
SELECT r.id, r.client_uid, …, ac.label, ac.phone, u.name
  FROM advisor_reports r
  LEFT JOIN advisor_clients ac
    ON ac.advisor_uid = r.advisor_uid AND ac.client_uid = r.client_uid
  LEFT JOIN users u ON u.id = r.client_uid
 WHERE r.advisor_uid = ?
 ORDER BY r.created_at DESC LIMIT 200
```

El `WHERE` por `advisor_uid` está bien: un asesor no ve informes de otro. Lo que falta es
`AND ac.status='active'` en el join. Y `u.name` se lee de `users` **en vivo**, no del
payload congelado.

Consecuencia: después de que el cliente revoca (o de que el asesor lo saca del roster), su
ficha sigue apareciendo en el historial con **el nombre que tenga hoy**, **su teléfono** y
**la URL de cada informe**. Si el ex-cliente se cambia el nombre en su cuenta, el asesor
lo ve cambiado.

**Cómo se explota en la práctica.** No es una fuga hacia un tercero: es que la revocación
no se siente. El asesor abre su pantalla de informes y sigue teniendo ahí al ex-cliente,
con teléfono para WhatsApp y links que funcionan (H-1). Los dos hallazgos se potencian:
H-2 le devuelve las URLs que H-1 mantiene vivas.

**Qué queda expuesto.** Nombre actual, teléfono y links a datos financieros de personas que
ya no son clientes.

**Otros call sites del mismo patrón.** Grepeé los `JOIN`/`SELECT` sobre `advisor_clients`
del tramo: **este es el único sin `status='active'`**. `advisor_list_clients` (34478),
`_advisor_client_ids` (36690), `_advisor_ticker_holders` (35285),
`advisor_reports_generate` (35957), `advisor_book_detail` (37966),
`advisor_book_asset_clients` (37862) y el core del group-op (36386) lo llevan todos. Es un
único olvido, no un patrón — pero está en el endpoint que sirve los links.

**Solución de fondo.** El teléfono y el nombre del cliente pertenecen al vínculo; si el
vínculo no está activo, no se sirven. Congelar el `client_label` desde
`payload["client_label"]` (que ya existe) en vez de re-leer `users.name`, y filtrar el
join por `status='active'` — dejando el informe listado (es un registro histórico del
asesor) pero sin datos de contacto vivos.

---

### [MEDIO] H-3 · `brief/run-cron`: efecto masivo por GET, con el token en la URL

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:33936-33957`

**Qué pasa.** Tres cosas juntas:

```python
@app.api_route("/api/advisor/brief/run-cron", methods=["GET", "POST"])
def advisor_brief_run_cron(request: Request):
    expected = ((os.environ.get("ADVISOR_BRIEF_TOKEN") or "").strip()
                or (os.environ.get("SNAPSHOT_CRON_TOKEN") or "").strip())
    …
    got = (request.headers.get("x-cron-token")
           or request.query_params.get("token") or "").strip()
    if got != expected:
        raise HTTPException(401, "Token inválido.")
```

1. **Acepta GET** para una operación que arma y **manda emails a todos los asesores** con
   el resumen de sus libros. Un GET con ese efecto es alcanzable por un prefetcher, un
   escáner de links, un bot de preview de un chat corporativo, o un `<img src>`.
2. **Acepta el token por query string.** Un secreto en la URL queda en los access logs de
   Railway, en el `Referer` de cualquier recurso que la página cargue, en el historial del
   navegador de quien lo pegue, y en los logs de cualquier proxy intermedio. El header
   `X-Cron-Token` ya está soportado: el `?token=` es una comodidad que abarata el secreto.
3. **Cae a `SNAPSHOT_CRON_TOKEN` si `ADVISOR_BRIEF_TOKEN` no está.** El comentario lo
   justifica ("para no multiplicar secretos"), pero el efecto es que un solo valor
   filtrado abre dos superficies distintas: el brief y el cron de snapshots.

La comparación `got != expected` además no es de tiempo constante (`secrets.compare_digest`
sería lo correcto), aunque contra un secreto de alta entropía por red esto es teórico.

**Cómo se explota en la práctica.** Quien obtenga el token —de un log, de un Referer, de
un screenshot del panel de Railway— puede disparar el envío del brief a todos los asesores
cuando quiera. No lee datos de nadie (el brief se arma por asesor con su propio libro y le
llega a él), pero es un amplificador de email con la reputación del dominio de Rendi
detrás, y un vector de agotamiento de la cuota de Resend. El lock `_brief_cron_running`
limita a una corrida simultánea por `kind`, no la frecuencia.

**Qué queda expuesto.** No hay fuga de datos entre usuarios. Lo expuesto es la capacidad
de disparar envíos masivos y el secreto compartido con el cron de snapshots.

**Otros call sites del mismo patrón.** Grepeé el archivo entero por el patrón "token de
cron por query string": `main.py:33952` (este) es el que encontré en mi tramo. El cron de
snapshots vive fuera de mi rango — **lo dejo señalado para el agente que audita ese
tramo**, porque comparte el secreto y probablemente el patrón.

**Solución de fondo.** `methods=["POST"]` solamente, token solo por header, y
`secrets.compare_digest`. El fallback a `SNAPSHOT_CRON_TOKEN` debería exigir que
`ADVISOR_BRIEF_TOKEN` esté seteado en prod (hoy el 503 solo salta si faltan los dos).

---

### [MEDIO] H-4 · Un GET de un asesor borra filas de todos los demás

**Evidencia:** ESTRUCTURAL
**Dónde:** `advisor_alerts.py:81-97`, llamado desde `main.py:33880-33893`

**Qué pasa.**

```python
# main.py:33880
@app.get("/api/advisor/alerts")
def advisor_alerts_get(uid: int = Depends(get_current_user)):
    …
        out = {"config": …, "history": advisor_alerts.history(conn, uid), …}
        conn.commit()   # history() purga lo viejo: sin commit era no-op + write-lock
```

```python
# advisor_alerts.py:81
def history(conn, uid, limit=30):
    purge_old(conn)                      # ← sin uid
    …
def purge_old(conn, days=HISTORY_DAYS):
    try:
        conn.execute("DELETE FROM advisor_alert_events WHERE fired_at < ?", (…,))
    except Exception:
        pass                             # ← el error se traga
```

El `DELETE` **no lleva `advisor_uid`**. El GET del asesor A borra eventos del asesor B, C
y D. Tres agravantes:

- Es un **GET**, así que ni conceptualmente pasa por un control de escritura.
- El `except Exception: pass` **tapa cualquier fallo** — si el `DELETE` empieza a errar
  (lock, migración a medias, cambio de tipo de `fired_at` en Postgres), nadie se entera y
  el historial deja de purgarse en silencio. Eso es un **PARCHE** en el sentido del prompt
  común: el `try/except` está tapando el error en vez de dejarlo salir.
- El `conn.commit()` explícito en el endpoint muestra que ya hubo un bug acá (el comentario
  dice "sin commit era no-op + write-lock"): se arregló que el purge *efectivamente
  escribiera*, sin revisar que escribiera **solo lo propio**.

**Cómo se explota en la práctica.** No hay fuga de datos y el efecto es una purga por TTL
que igual iba a pasar. Lo explotable es el **timing**: un asesor que pegue al endpoint
puede adelantar el borrado del historial de alertas de otro asesor unas horas. Con
`HISTORY_DAYS` bajo es ruido; el problema real es que la tabla no está aislada por tenant
y hoy nada lo impide.

**Qué queda expuesto.** Integridad del historial de alertas de otros asesores, no
confidencialidad.

**Otros call sites del mismo patrón.** `purge_old` se llama desde `history()`, y `history()`
solo desde `advisor_alerts_get` (33887) — un solo camino. Pero el patrón "purga por TTL sin
filtro de dueño disparada desde el request de un usuario" conviene grepearlo a nivel app:
en mi tramo no hay otro.

**Solución de fondo.** `DELETE … WHERE fired_at < ? AND advisor_uid = ?` y pasarle el uid.
Si la intención era una purga global, entonces no va en el request de un usuario: va en el
cron nocturno, donde un fallo se ve. Y sacar el `except Exception: pass`.

---

### [MEDIO] H-5 · Reclamar la cuenta no le pregunta al cliente si el asesor sigue pudiendo escribirle

**Evidencia:** DEDUCIDO — leí `claim_account` (35106-35172), `advisor_create_client`
(34370-34417) y el core del block trade (36386-36400). No lo ejecuté.
**Dónde:** `main.py:35106`, `main.py:34403`, `main.py:36386`

**Qué pasa.** `advisor_create_client` crea el vínculo con
`link_type='managed', permission='read_write'` (34403-34406) — correcto: la ficha es una
cáscara que solo el asesor opera. Cuando el cliente reclama la cuenta, `claim_account`
setea `approved=1` y `managed_by=NULL` (35456-35460) y el comentario aclara, bien, que el
vínculo sigue vivo en `advisor_clients` a propósito.

Lo que **no** cambia es `permission`. Sigue en `read_write`. Y `_advisor_group_op_apply`
solo pide eso (36386-36393):

```python
if link["permission"] != "read_write":
    skipped.append({"client_uid": cid, "reason": "vínculo de solo lectura"})
```

Entonces, después del claim, el asesor puede seguir **escribiendo posiciones y debitando
cash** en una cuenta que ahora tiene dueño real, con contraseña propia. Y el flujo de claim
no le muestra al cliente en ningún momento qué permiso está heredando: la pantalla habla de
poner una contraseña, no de autorizar escrituras.

Compará con el otro camino: en `_advisor_link_request` (34810-34812) el permiso se declara
(`read` o `read_write`), se lo mandan al cliente en el email, se lo muestra
`link-request/preview` (`"permission": req["permission"]`, 35019) y él acepta o rechaza. El
consentimiento explícito existe **en la rama de la cuenta que ya existía, y no en la del
claim**.

**Cómo se explota en la práctica.** No hace falta un atacante externo: es el asesor
haciendo lo que el sistema le permite sobre la cartera de alguien que nunca dijo que sí a
eso. El cliente puede revocar desde Configuración (35241), pero solo si sabe que hay algo
que revocar.

**Qué queda expuesto.** Escritura sobre la cartera de una cuenta reclamada: alta de
posiciones, débito de cash, ajuste de flujos mensuales.

**Otros call sites del mismo patrón.** Todo lo que gatea por `permission=='read_write'`:
`_resolve_client_context` (`main.py:2798`, para toda escritura vía contexto de cliente),
`_advisor_group_op_apply` (36386) y `advisor_group_op_undo` (36609). Los tres heredan el
`read_write` que nadie consintió. **Anotado y no desarrollado: esto es del MODELO del
vínculo, que audita otro agente.** Lo dejo acá porque se ve desde los endpoints.

**Solución de fondo.** Que el claim degrade a `permission='read'` salvo consentimiento
explícito en la pantalla, o que muestre el permiso heredado y pida confirmarlo — el mismo
trato que ya recibe la persona que acepta un `link_request`.

---

### [BAJO] H-6 · Rechazar un pedido de acceso no exige estar logueado

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:35034-35056`

**Qué pasa.** Aceptar exige login **y** que el uid coincida con `req["client_uid"]`. Rechazar
alcanza con el token, y está documentado como decisión deliberada: *"cortar nunca puede ser
peor que no cortar"*. La lógica es sana, pero tiene un efecto que la decisión no
contempla: el rechazo dispara `ADVISOR_LINK_REJECT_COOLDOWN_DAYS = 30` (34776, chequeado en
34828-34836). Un rechazo no solo cierra ese pedido: **bloquea al asesor 30 días** contra
esa cuenta.

**Cómo se explota en la práctica.** Cualquiera que vea el email (una casilla compartida, un
reenvío, un archivo de correo corporativo) puede rechazar y cerrarle la puerta al asesor por
un mes. Requiere un POST deliberado con el token, así que no lo dispara un escáner de links.

**Qué queda expuesto.** Nada de datos: es una denegación de servicio menor sobre el flujo de
alta, con el efecto benigno de que el vínculo NO se crea.

**Solución de fondo.** Separar las dos cosas: el rechazo sin login cierra el pedido (bien),
pero el cooldown de 30 días solo se aplica cuando el rechazo lo firma el dueño autenticado.

---

### [BAJO] H-7 · El preview del pedido de acceso responde para tokens ya muertos

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:34993-35031`

**Qué pasa.** `link_request_preview` busca `WHERE token=?` sin más y devuelve el payload
completo —`advisor_name`, `advisor_matricula`, `advisor_logo` (data-URI de hasta 200 KB) y
`email_masked`— **cualquiera sea el estado**. `state` dice `expired`/`rejected`/`cancelled`,
pero los datos van igual. Comparalo con `claim_preview` (35060), que sí corta:
`WHERE ct.token=? AND ct.used_at IS NULL` + chequeo de vencimiento → 400.

**Cómo se explota en la práctica.** Quien tenga un token viejo (de un mail archivado, de un
reenvío) confirma indefinidamente que la persona detrás de `email_masked` fue objeto de un
pedido de acceso del asesor X, con su matrícula CNV. Y sirve 200 KB por request; con
20 requests/300s por IP eso es ~4 MB por IP por ventana, banda barata pero gratis.

**Qué queda expuesto.** Metadato de relación (quién le pidió acceso a quién), branding del
asesor, un email parcialmente enmascarado.

**Otros call sites del mismo patrón.** `claim_preview` (35060) **sí** valida estado: es
exactamente el mismo tipo de pantalla resuelto de dos maneras distintas. El fix ya existe
en el repo, en el endpoint de al lado, y no se propagó.

**Solución de fondo.** Copiar el criterio de `claim_preview`: para estados no `pending`,
devolver solo `state`, sin branding ni email.

---

### [BAJO] H-8 · `/api/health` publica el SHA del commit desplegado

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:34270-34294`

Endpoint público (correcto: lo pinga el cron de wake-up y el uptime check) que devuelve
`RAILWAY_GIT_COMMIT_SHA[:40]`. El comentario explica por qué está —distinguir "deployó mi
cambio" de "sigue el de antes"— y es una razón buena. El costo es que cualquiera sabe qué
commit exacto corre en prod; si el repo alguna vez fuera público o se filtrara, eso mapea
la versión desplegada a un diff conocido. Recon menor. Alternativa: exponerlo solo bajo
`get_admin_user` o detrás de una variable de entorno.

---

## Lo que NO pude verificar (dicho explícitamente)

1. **Nada de esto está MEDIDO en runtime.** No levanté el backend ni ejecuté ningún
   request. Lo único que ejecuté es análisis estático sobre el archivo (el script de
   `audit/_scripts/`). Todos los hallazgos son ESTRUCTURAL o DEDUCIDO, y están marcados.
2. **H-1 no lo confirmé end-to-end.** No generé un informe, no revoqué un vínculo y no
   reabrí el link. La conclusión sale de que ningún revocador escribe en `advisor_reports`
   (grep exhaustivo pegado) y de que `report_public` solo mira `revoked_at` y el TTL. Si
   existiera un trigger de DB o un job que revoque informes al revocar el vínculo, no lo
   encontré — busqué en `main.py` y no revisé `snapshots_job.py` ni los módulos de billing.
3. **El valor real de `REPORTS_TTL_DAYS` en producción no lo sé** (no toco prod). Asumí el
   default de 180 días. Si estuviera en `0`, H-1 pasa de 180 días a permanente.
4. **`advisor_brief.run_briefs` y `advisor_brief.build_brief` no los leí enteros** — solo
   verifiqué cómo se los invoca desde mis dos endpoints. Si `build_brief` cruzara datos
   entre asesores, se me escapó.
5. **No auditė el frontend.** Que `note` (1200 chars libres del asesor) y `client_label`
   terminen en una página pública sin escapar es un riesgo de XSS que depende de cómo
   React los renderice; `logo_data` sí está validado en el backend a raster base64 (SVG
   excluido a propósito), que es la mitad peligrosa.
6. **El modelo del vínculo asesor-cliente no es mío.** H-5 lo anoto sin desarrollar, como
   pide el encargo. También dejo señalado, sin desarrollarlo, que ningún endpoint de mi
   tramo le da al cliente visibilidad sobre los informes emitidos a partir de su cartera.
7. **Postgres.** Todo lo leído es SQL que pasa por `pgshim`. No verifiqué que el
   comportamiento sea idéntico bajo `USANDO_PG` — en particular la comparación de fechas
   en texto de `purge_old` (H-4) y en el corte de TTL de `report_public`.
8. **Concurrencia.** `claim_account` y `_apply_link_request` tienen defensas anti-carrera
   explícitas (`rowcount==1`) que leí y me parecen correctas, pero no las probé.

---

## Anexo — salida del script (MEDIDO)

`python3 audit/_scripts/5a_autorizacion_6_tramo.py`, sobre `/tmp/rendi-main/backend/main.py`:

```
total endpoints en el tramo: 44
 linea metodo    ruta                                           auth                 exento  req_adv  own_link  adv_uid_en_where
 33880 get       /api/advisor/alerts                            get_current_user     True    True     False     False
 33896 post      /api/advisor/alerts/events/seen                get_current_user     True    True     False     True
 33911 patch     /api/advisor/alerts                            get_current_user     True    True     False     False
 33936 api_route /api/advisor/brief/run-cron                    token-cron           True    False    False     False
 33979 get       /api/advisor/brief/preview                     get_current_user     True    True     False     False
 33998 get       /api/advisor/brief/prefs                       get_current_user     True    True     False     True
 34011 patch     /api/advisor/brief/prefs                       get_current_user     True    True     False     True
 34052 get       /api/push/vapid-public-key                     NINGUNA              True    False    False     False
 34062 post      /api/push/subscribe                            get_effective_user   True    False    False     False
 34085 delete    /api/push/subscribe                            get_effective_user   True    False    False     False
 34101 get       /api/push/status                               get_effective_user   True    False    False     False
 34167 post      /api/push/test                                 get_effective_user   True    False    False     False
 34180 get       /api/home/personal                             get_effective_user   False   False    False     False
 34252 post      /api/admin/snapshots/run-now                   get_admin_user       True    False    False     False
 34270 get       /api/health                                    NINGUNA              False   False    False     False
 34304 get       /api/stats/public                              NINGUNA              False   True*    False     False
 34370 post      /api/advisor/clients                           get_current_user     True    True     False     True
 34419 get       /api/advisor/reports                           get_current_user     True    True     False     True
 34465 get       /api/advisor/clients                           get_current_user     True    True     True      True
 34578 patch     /api/advisor/clients/{client_uid}              get_current_user     True    True     True      True
 34609 post      /api/advisor/clients/{client_uid}/revoke       get_current_user     True    True     True      True
 34690 post      /api/advisor/clients/{client_uid}/invite       get_current_user     True    True     True      True
 34993 get       /api/auth/link-request/preview                 NINGUNA              True    False    False     True
 35034 post      /api/auth/link-request/respond                 NINGUNA              True    False    False     False
 35060 get       /api/auth/claim/preview                        NINGUNA              True    False    False     False
 35106 post      /api/auth/claim                                NINGUNA              True    False    False     False
 35176 get       /api/me/advisor                                get_current_user     True    False    False     False
 35224 post      /api/me/advisor/requests/{req_id}/respond      get_current_user     True    False    False     False
 35241 post      /api/me/advisor/{advisor_uid}/revoke           get_current_user     True    False    False     True
 35307 get       /api/advisor/radar/events                      get_current_user     True    True     False     False
 35373 get       /api/advisor/radar/news                        get_current_user     True    True     False     True
 35900 get       /api/advisor/profile                           get_current_user     True    True     False     False
 35910 patch     /api/advisor/profile                           get_current_user     True    True     False     True
 35943 post      /api/advisor/reports/generate                  get_current_user     True    True     False     True
 36005 get       /api/reports/public/{token}                    NINGUNA              False   False    False     False
 36039 post      /api/advisor/reports/{report_id}/revoke        get_current_user     True    True     False     True
 36092 get       /api/advisor/group-op/prep                     get_current_user     True    True     False     True
 36292 post      /api/advisor/group-op                          get_current_user     True    False**  False     True
 36584 post      /api/advisor/group-op/{batch_id}/undo          get_current_user     True    True     False     True
 36947 get       /api/advisor/book                              get_current_user     True    True     False     True
 37661 get       /api/advisor/book/composition                  get_current_user     True    True     False     False
 37795 get       /api/advisor/book/asset-clients                get_current_user     True    True     False     True
 37883 get       /api/advisor/book/history                      get_current_user     True    True     False     False
 37944 get       /api/advisor/book/detail                       get_current_user     True    True     False     True

--- get_effective_user en ruta NO exenta (hereda contexto de cliente) ---
  34180 GET /api/home/personal

--- SIN dependencia de auth (públicos) ---
  33936 API_ROUTE /api/advisor/brief/run-cron  (token-cron)
  34052 GET /api/push/vapid-public-key  (NINGUNA)
  34270 GET /api/health  (NINGUNA)
  34304 GET /api/stats/public  (NINGUNA)
  34993 GET /api/auth/link-request/preview  (NINGUNA)
  35034 POST /api/auth/link-request/respond  (NINGUNA)
  35060 GET /api/auth/claim/preview  (NINGUNA)
  35106 POST /api/auth/claim  (NINGUNA)
  36005 GET /api/reports/public/{token}  (NINGUNA)

--- /api/advisor/* SIN _require_advisor ---
  33936 API_ROUTE /api/advisor/brief/run-cron
  36292 POST /api/advisor/group-op
```

**Dos falsos positivos del script, verificados a mano leyendo el código:**

- `*` **34304 `/api/stats/public` — `req_adv=True` es falso.** El script corta el cuerpo
  hasta el decorador siguiente y ahí cae el comentario de cabecera del bloque PLAN ASESOR
  (`main.py:34335-34337`), que menciona `_require_advisor` en prosa. El endpoint es público
  y no gatea nada, que es lo correcto: devuelve un `COUNT(*)` agregado, sin PII.
- `**` **36292 `/api/advisor/group-op` — `req_adv=False` no es un hueco.** El gate corre,
  pero adentro del helper: `_advisor_group_op_apply` llama `_require_advisor(conn, uid)` en
  `main.py:36382`. El handler es un pasamanos de 5 líneas. Vale como observación de diseño
  (el gate no se ve en el endpoint, y el mismo core lo comparte el registro grupal por
  chat), no como hallazgo.

**Deriva verificada contra `origin/main` (`897b0d63`):** los tres hallazgos principales
siguen vivos, corridos ~25 líneas — `/api/advisor/alerts` en 33905, `/api/reports/public/`
en 36030, `/api/advisor/book/detail` en 37969, y el único `UPDATE advisor_reports SET
revoked_at` sigue siendo el del endpoint del asesor (36078).
