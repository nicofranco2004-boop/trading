# 5a · El rol ASESOR — auditoría del MODELO de permisos

> Auditor externo. Alcance: **el modelo** (cómo nace el vínculo, qué habilita, dónde se verifica),
> no la revisión endpoint-por-endpoint (esa la hacen otros agentes de la tanda).
> Código auditado: **`/tmp/rendi-main`**, commit congelado `b74f450f` (prod al 2026-09-05).

---

## Método

**Qué ejecuté** (sondas propias, en `audit/_scripts/`, contra la copia congelada y una base SQLite
temporal — **nunca contra producción ni contra ningún sistema en vivo**):

| script | qué prueba |
|---|---|
| `audit/_scripts/5a_asesor_probe.py` | resolver de contexto (vínculo inexistente / de otro asesor / revocado), permiso `read` vs escritura, qué alcanza el contexto además de la cartera, prefijos exentos, supervivencia de los informes tras la revocación, alta de cliente shadow |
| `audit/_scripts/5a_asesor_claim_probe.py` | flujo `claim` completo: alta shadow → invitación → preview público → claim → estado del vínculo DESPUÉS del claim → reuso de token |

Corridas con `cd /tmp/rendi-main/backend && python3 <script>` (FastAPI `TestClient` in-process,
`DB_PATH` a un tempfile). Las trazas están pegadas en cada hallazgo.

**Barridos estáticos** (python + `re` sobre `backend/main.py`, 38.029 líneas): mapeo de las 33 rutas
`/api/advisor/*` contra los helpers de verificación; mapeo de las 131 rutas que heredan el contexto
de cliente; búsqueda de handlers `GET` que escriban (para cazar un bypass del `read`); búsqueda de
consultas a `advisor_clients` **sin** filtro `status='active'`.

**Qué NO ejecuté / no pude verificar:** ver la sección final.

**Trampa que casi me come un hallazgo (y que anoto por si sirve a otro agente):** `TestClient`
guarda cookies, y `get_current_user` (`main.py:2731-2733`) **prefiere la cookie sobre el header
`Authorization`**. El `POST /api/auth/claim` auto-loguea con `set_auth_cookie`, así que la primera
corrida de la sonda 2 midió los pasos 6-9 **como el cliente recién reclamado**, no como el asesor,
y daba un falso "el asesor puede escribir". Se corrigió con `C.cookies.clear()` y **el resultado se
confirmó igual** — pero el número original era falso.

**Corrección al mapa:** el mapa cita `get_effective_user` en `main.py:2729-2800`. En el código real
el bloque va de **2731 a 2820** (`CLIENT_CTX_HEADER` en `2748`, `_resolve_client_context` en `2767`,
`get_effective_user` en `2806`, `_require_advisor` en `2823`). Gana el código.

**Deriva:** las 4 líneas que sostienen los hallazgos siguen vivas en `origin/main` (`897b0d63`),
corridas ~25 líneas: `_advisor_own_link` 34566→34591, el `LEFT JOIN advisor_clients` de
`advisor_list_reports` 34428→34456, `ai_user_facts … is_active=1` 29348→29358, `_report_ttl_days`
35990→36015.

**Ninguno de mis hallazgos toca los archivos de la tanda F1.** Sin cruces.

---

## Lo primero, porque cambia cómo se lee todo lo demás

**El resolver de contexto está bien construido y lo comprobé.** No encontré ni un solo IDOR en la
superficie asesor. `_resolve_client_context` (`main.py:2767-2804`) exige fila
`advisor_clients` con `status='active'`, tira **403 explícito** (nunca degrada en silencio al uid
propio), valida el rango del entero antes del bind, exime por **límite de segmento** (no `startswith`
crudo) y bloquea toda escritura si el permiso no es `read_write`. Los 33 endpoints `/api/advisor/*`
gatean por `_require_advisor`, y los que agregan datos de varios clientes derivan la lista de la DB
(`_advisor_client_ids`, `main.py:36695`) en vez de aceptarla por HTTP. Hay además una batería IDOR
dedicada en `backend/tests/test_advisor_plan.py`.

**Y el rol no es autoservicio:** `tier='advisor'` solo se otorga por
`POST /api/admin/billing/grant-comp` (`main.py:19844-19851`, `Depends(get_admin_user)`); el checkout
de Mercado Pago solo vende `plus`/`pro` (`billing/mercadopago.py:287`). Es decir: **para explotar
cualquier cosa de este informe hay que ser primero un asesor que un admin habilitó a mano.**

Por eso **no hay ningún CRÍTICO acá**. Los hallazgos son de otra naturaleza y son igual de
importantes: **la brecha entre lo que el modelo concede y lo que al cliente se le dice que concede**,
y **qué sobrevive a la revocación**.

---

## Resumen — hallazgos por severidad

| id | sev | título | archivo:línea | evidencia |
|---|---|---|---|---|
| H-1 | ALTO | El `claim` entrega `read_write` permanente sin decírselo a nadie — la pantalla que sí lo explica es la otra | `frontend/src/pages/ClaimAccount.jsx:238-240` · `main.py:35147-35158` | MEDIDO |
| H-2 | ALTO | La promesa "ver + registrar operaciones" cubre 131 endpoints, incluidos borrado masivo, desconexión de API del broker y la memoria personal de la IA | `main.py:2749-2762` · `main.py:29339` · `main.py:31740` | MEDIDO |
| H-3 | ALTO | Revocar no revoca los informes: el link público sigue abriendo la cartera del ex-cliente y el asesor lo conserva en su historial | `main.py:34419-34462` · `main.py:36053` | MEDIDO |
| H-4 | MEDIO | El link público de informe: 180 días, sin auth, y el cliente no sabe que existe ni lo puede dar de baja | `main.py:35990-36002` · `main.py:36039` | ESTRUCTURAL |
| H-5 | MEDIO | 23 copias inline del predicado de autorización; `_advisor_own_link` cubre 3 de 14 sitios | 5 archivos, lista abajo | ESTRUCTURAL |
| H-6 | BAJO | `AdvisorInviteIn.email` no valida formato (único modelo de email del repo sin `_EMAIL_RE`) | `main.py:34677-34683` | ESTRUCTURAL |
| H-7 | BAJO | La cookie le gana al header `Authorization` sin avisar; con identidades distintas no hay error | `main.py:2731-2733` | MEDIDO |

---

## 1 · ¿Cómo nace el vínculo y quién lo autoriza?

**El mapa dice tres caminos de alta. Verificado sobre el código: son exactamente tres**, y lo
verifiqué por el lado duro — **solo hay 2 `INSERT INTO advisor_clients` en todo el backend**
(`main.py:34403` y `main.py:34947`; los demás hits son tests):

| # | camino | quién consiente | permiso | dónde |
|---|---|---|---|---|
| 1 | **managed / shadow** — el asesor crea la ficha | **nadie** (no hay persona todavía) | `read_write` fijo, sin opción | `main.py:34370-34417` |
| 2 | **claim** — la ficha shadow pasa a ser del cliente | consentimiento **implícito** (poner contraseña) | hereda el `read_write` del paso 1 | `main.py:34690-34776` → `main.py:35119-35170` |
| 3 | **link_request** — el email ya tiene cuenta propia | consentimiento **explícito**, informado | el asesor elige `read` o `read_write`; el cliente lo ve | `main.py:34785-34884` → `_apply_link_request` `34898` |

### ¿Puede un asesor vincularse a alguien sin que esa persona lo acepte?

**Sí, por el camino 1, y es correcto que así sea** (MEDIDO — sonda 1, paso 6):

```
POST /advisor/clients -> 200 {"client_uid":6,"label":"Persona real","link_type":"managed","permission":"read_write"}
```

Del otro lado no hay nadie: es una ficha que el asesor arma con datos que él carga. **No es una
toma de control de la cuenta de un tercero.** El camino 3 es el que cubre "esa persona ya tiene
Rendi", y ahí **nunca** se puede entrar sin un sí explícito: aceptar exige estar logueado con esa
misma cuenta (`main.py:35035-35043`, `403` si `me != req["client_uid"]`), y el 409 de dos pasos
(`main.py:34817-34827`) obliga al asesor a enterarse de que cambió el trato antes de mandar nada.
Rechazar, en cambio, alcanza con el token — asimetría correcta y comentada.

**Lo que sí encontré es el camino 2.** Ver H-1.

### Los tokens

| | claim (`advisor_claim_tokens`) | link_request (`advisor_link_requests`) |
|---|---|---|
| generación | `secrets.token_urlsafe(32)` = **256 bits** (`main.py:2943-2945`) | idéntico |
| **¿adivinable?** | **no** | **no** |
| **¿expira?** | **sí**, 7 días (`ADVISOR_CLAIM_TTL_DAYS`, `main.py:34650`) | **sí**, 14 días (`main.py:34654`) |
| **¿un solo uso?** | **sí**, y bien hecho: el `UPDATE … WHERE used_at IS NULL` + chequeo de `rowcount != 1` (`main.py:35141-35147`) cierra la carrera de dos claims simultáneos | **sí**, mismo patrón con `rowcount` en `_apply_link_request` (`main.py:34930-34935`) |
| anti-spam | 8 invites/día por ficha + 10/300s por asesor | 3/día por (asesor, cuenta) + **cooldown de 30 días tras un rechazo** (`main.py:34657`) |
| en la URL | sale de la barra con `history.replaceState` en las dos pantallas | idem |

MEDIDO (sonda 2): `token len: 43 | expira: 2026-09-15 | usado: None`, y el reuso devuelve
`400 "Link inválido o ya usado"`. **No tengo objeciones a los tokens.** El cooldown de rechazo y el
`rowcount` de la carrera son mejores que el promedio del repo.

---

## 2 · Qué puede ver y hacer el asesor vs. qué se le promete al cliente

### El mecanismo

`get_effective_user` (`main.py:2806-2820`) resuelve el header `X-Rendi-Client-Id` contra
`advisor_clients` y devuelve el uid del **cliente**, de modo que los ~131 endpoints que hacen
`WHERE user_id=?` sirven la cuenta del cliente sin tocar su lógica. Lo que NO hereda el contexto son
8 prefijos exentos (`main.py:2749-2762`): `/api/auth`, `/api/billing`, `/api/admin`, `/api/advisor`,
`/api/me`, `/api/push`, `/api/plan/track`, `/api/feedback`.

MEDIDO — el resolver hace lo que promete:

```
GET /api/positions ctx=sin vinculo (otro user):  403 {"detail":"Sin acceso a ese cliente"}
GET /api/positions ctx=cliente de OTRO asesor:   403 {"detail":"Sin acceso a ese cliente"}
GET  /api/positions (permiso 'read')          -> 200
POST /api/positions (permiso 'read')          -> 403 {"detail":"Acceso de solo lectura a ese cliente"}
GET /api/me/advisor ctx=cliente               -> 200 {"advisors":[],"requests":[]}   # exento: uid = asesor
```

Y verifiqué el bypass obvio del `read`: **ningún handler `GET` no-exento escribe**. Barrí los 131
endpoints extrayendo el cuerpo real de cada función (no el bloque entre decoradores, que arrastra
helpers y da falsos positivos) buscando `INSERT/UPDATE/DELETE` y llamadas a
`_rebuild*|_recompute*|_repair*|_reconcile*|_recalc*|_persist*`: **cero resultados**. El
`read_write` no se puede saltar por método.

---

### 🔴 H-1 · [ALTO] El `claim` entrega `read_write` permanente y la pantalla no lo menciona

**Evidencia:** MEDIDO
**Dónde:** `frontend/src/pages/ClaimAccount.jsx:238-240` · `backend/main.py:35147-35158`

**Qué pasa.** El camino 3 (`/acceso`) es un modelo de consentimiento ejemplar. La pantalla
`AdvisorAccessRequest.jsx:207-224` enumera, antes de que el cliente toque nada:

- "Ver tu cartera como la ves vos: tenencias, valor, resultado y movimientos."
- "Registrar operaciones por vos" — **solo si `permission === 'read_write'`**, con el radio button
  que el asesor eligió a la vista.
- "No va a poder entrar con tu contraseña… Y le cortás el acceso cuando quieras."

El camino 2 (`/claim`) llega **al mismo estado de acceso** — `read_write` sobre una cuenta que a
partir de ese momento tiene contraseña, login propio y la persona real adentro — y su pantalla
completa dice, en total, esto (`ClaimAccount.jsx:238-240`):

> "Vas a poder ver todo lo que {asesor} cargó por vos"

Está escrito **al revés**: describe lo que el cliente va a ver del asesor, no lo que el asesor va a
seguir viendo del cliente. No hay una palabra sobre acceso continuo, ni sobre escritura, ni sobre
revocación. El email tampoco (`billing/emails.py:1172`: solo "si no reconocés a X, ignorá este
email"). Y el backend, en el mismo commit del claim, **documenta explícitamente que el vínculo
sobrevive** (`main.py:35147-35152`): *"El VÍNCULO con el asesor sigue viviendo en `advisor_clients`
… esto NO le corta el acceso."* La decisión es deliberada y está comentada — **no es un parche**.
Lo que falta es contárselo a quien firma.

**Cómo se explota en la práctica.** No hace falta explotar nada: es el flujo feliz. MEDIDO —
sonda 2, corrida limpia (sin la cookie del auto-login):

```
1) shadow creado: {'client_uid': 2, 'label': 'Juan P', 'link_type': 'managed', 'permission': 'read_write'}
2) invite -> 200 {"ok":true,"email":"victima-29b006e6@gmail.com"}
3) claim/preview (SIN auth) -> 200 {"advisor_name":"a-29b006e6","label":"Juan P", ...}
4) claim -> 200  (auto-login, contraseña puesta por el cliente)
5) vinculo DESPUES del claim: {'link_type': 'managed', 'permission': 'read_write', 'status': 'active'}
   users row: {'email': 'victima-...@gmail.com', 'approved': 1, 'managed_by': None}
6) el asesor sigue LEYENDO la cuenta reclamada -> 200
7) y ESCRIBIENDO en ella -> 200 {"id":1,"user_id":2,"broker":"X","asset":"AAPL", ...}
```

El paso 7 es lo importante: el asesor creó una posición **en la cuenta de una persona que puso su
propia contraseña**, y esa persona nunca vio una pantalla que se lo dijera.

**Qué queda expuesto.** La cartera completa y la capacidad de escritura sobre la cuenta de una
persona real, con un consentimiento que en el mejor de los casos es implícito. El cliente **sí**
tiene dónde enterarse y cortar después (Config › Tu asesor, `frontend/src/pages/Config.jsx:111-180`,
que solo se renderiza si hay vínculo o pedido) — pero eso es enterarse *después*, y solo si entra
a Configuración.

**Otros call sites del mismo patrón.** El desbalance es exactamente de dos pantallas: `/acceso`
divulga y `/claim` no. Los dos escriben en la misma tabla con la misma semántica. No hay un tercero.

**Solución de fondo.** El bloque de divulgación de `AdvisorAccessRequest.jsx:207-224` no depende de
nada del pedido salvo `permission`: **moverlo a un componente compartido y renderizarlo también en
`/claim`**, arriba del form de contraseña. Es la misma información, el mismo momento de decisión y
el mismo permiso a divulgar. Segundo: hoy el camino 1 hardcodea `permission='read_write'`
(`main.py:34406`) sin ofrecer `read`, mientras el camino 3 sí lo ofrece — darle al claim el mismo
selector cierra la asimetría entera.

---

### 🔴 H-2 · [ALTO] La promesa cubre "cartera y movimientos"; el contexto cubre 131 endpoints

**Evidencia:** MEDIDO (lo que se lee) + ESTRUCTURAL (el inventario)
**Dónde:** `main.py:2749-2762` (la lista de exentos) · `main.py:29339` · `main.py:31740`

**Qué pasa.** Lo que se le promete al cliente es *"tenencias, valor, resultado y movimientos"* +
*"registrar operaciones (cargarlas en Rendi — no las ejecuta en tu broker)"*. Lo que el header
efectivamente abre son **131 endpoints** (medido con el barrido estático). El desglose por prefijo:

```
 17 /api/imports/*     10 /api/positions/*    7 /api/ai/*         6 /api/brokers/*
  6 /api/plazos-fijos/* 6 /api/goals/*        5 /api/monthly/*    5 /api/futures/*
  5 /api/operations/*   5 /api/alerts/*       4 /api/bonds/*      4 /api/insights/*
  4 /api/export/*       4 /api/wallbit/*      4 /api/home/*       3 /api/events/*
  … + 23 prefijos más de 1-3 endpoints
```

Tres familias caen claramente **fuera** de lo prometido:

1. **La memoria personal de la IA.** `GET /api/ai/facts` (`main.py:29339`, `get_effective_user`)
   devuelve `ai_user_facts` — los hechos que el cliente le declaró al coach en el chat, que el
   prompt trata como "verdad declarada". Eso no es cartera. MEDIDO:

   ```
   GET /api/ai/facts -> 200  {"facts":[{"id":1,"content":"Cobro 3.500.000 ARS por mes y tengo un
                              hijo","source":"chat","is_active":1, ...
   ```

   (el contenido es un fixture que yo escribí; lo que la traza prueba es **que la tabla se sirve al
   asesor bajo contexto**). Con `read_write` además puede **escribir** facts (`POST /api/ai/remember`)
   y **borrarlos** (`DELETE /api/ai/facts/{id}`) — es decir, alterar la memoria con la que la IA
   le responde al cliente. Nada de esto aparece en ninguna pantalla de consentimiento.

2. **Borrado masivo.** `POST /api/imports/wipe-broker` (`main.py:31740`),
   `POST /api/imports/{batch_id}/revert`, los `DELETE` de `positions`/`brokers`/`operations`. "Registrar
   operaciones" no es "borrar el broker entero". Todos exigen `read_write`, ninguno exige nada más.

3. **La integración con el broker.** `DELETE /api/wallbit/disconnect` (`main.py:31310`) borra la
   credencial cifrada del cliente; `POST /api/wallbit/connect` (`main.py:31238`) la **reemplaza** por
   otra. La API key nunca se devuelve en claro — `wallbit_status` solo expone `scope`/fechas — así que
   **no hay fuga de credencial**, pero sí hay control sobre ella. MEDIDO: `GET /api/wallbit/status -> 200`
   incluso con permiso `read`.

Y `GET /api/export/*` entrega el CSV completo del cliente. MEDIDO:

```
GET /api/export/positions.csv -> 200  Activo,Broker,Es cash,Cantidad,Costo invertido,... GGAL,Cocos,0,100.0,100000.0,...
```

**Qué queda expuesto.** No es una fuga entre cuentas: es que el permiso concedido es sustancialmente
más ancho que el permiso descripto. En un producto financiero eso es el consentimiento.

**El mecanismo, y por qué está donde está.** El diseño es **allowlist invertida**: se enumeran los
prefijos que NO heredan y todo lo demás hereda. El propio código lo marca —
*"⚠️ FAIL-OPEN: todo endpoint futuro FUERA de estos prefijos hereda el contexto de cliente"*
(`main.py:2763-2765`). Es una decisión consciente y con una virtud real (nadie olvida agregar un
endpoint de datos), pero su costo es exactamente este: la superficie crece sola y **nadie mantiene
sincronizado el texto que el cliente firma**.

**Solución de fondo.** No es "achicar la lista de exentos" — eso rompería el producto. Es que el
permiso deje de ser binario y pase a ser por **capacidad**, con el mismo vocabulario en los dos
lados: `ver_cartera` / `registrar_operaciones` / `borrar` / `conectar_brokers` / `memoria_ia`. El
gate ya existe y es de una línea (`row["permission"] != "read_write"`, `main.py:2803`); lo que falta
es la granularidad y que la pantalla de consentimiento se genere **desde esa misma tabla**, para que
no puedan volver a divergir. Mientras eso no exista, el mínimo honesto es sacar
`/api/ai/facts`, `/api/wallbit/*` e `imports/wipe-broker` del alcance del contexto (o exigirles un
permiso aparte).

---

## 3 · ¿Puede llegar a datos de usuarios que NO son sus clientes?

**No encontré ninguna vía.** Es el capítulo donde el sistema sale bien parado y lo digo con la misma
firmeza que uso para los hallazgos.

Barrí **todos** los endpoints cuya firma acepta un identificador de usuario (`client_uid`,
`client_id`, `user_id`, `target_uid`) por path, query o body. Son 12, y ninguno queda sin gate:

| endpoint | gate |
|---|---|
| `/api/admin/*` (9 endpoints) | `Depends(get_admin_user)` |
| `PATCH /api/advisor/clients/{client_uid}` | `_require_advisor` + `_advisor_own_link` |
| `POST /api/advisor/clients/{client_uid}/revoke` | `_require_advisor` + `_advisor_own_link` |
| `POST /api/advisor/clients/{client_uid}/invite` | `_require_advisor` + `_advisor_own_link` |

Y los que reciben **listas** de clientes por body:

- **Informes en lote** — `POST /advisor/reports/generate` (`main.py:35953-35958`) arma primero el dict
  `links` con los vínculos **activos** y después hace `label = links.get(cid); if label is None:
  skipped.append(… "sin vínculo activo")`. Un `client_uid` ajeno cae a `skipped`, no a `out`.
- **Operación grupal** — `POST /advisor/group-op` es el único de los 33 que **no** llama
  `_require_advisor` en su propio cuerpo… porque lo llama el core que comparte con el chat:
  `_advisor_group_op_apply` (`main.py:36179-36195`) abre con `_require_advisor(conn, uid)` y valida
  fila por fila contra los vínculos activos `read_write`. **No es un hueco**, es delegación — pero
  conviene saberlo antes de refactorizar el endpoint.
- **Registro grupal por chat** — `_resolve_group_clients` (`main.py:36320-36325`) matchea los nombres
  que dictó el asesor **contra su propio roster activo**; un nombre que no está devuelve "no encontré
  al cliente", no una fila ajena. Y `_register_group_op_handler` re-chequea `get_tier == 'advisor'`.
- **Undo del lote** — `POST /advisor/group-op/{batch_id}/undo` (`main.py:36591-36610`) exige
  `advisor_op_batches.advisor_uid = uid` **y** re-lee los vínculos `read_write` en el momento del
  undo: si el vínculo se revocó entre el alta y el undo, el ítem se saltea y el lote **no** se marca
  deshecho (para poder reintentar si el acceso vuelve). Cuidado poco común, bien resuelto.
- **El libro, la composición, el detalle, la serie histórica, `asset-clients`** — los cinco derivan
  la lista con `_advisor_client_ids` (`main.py:36695`, `status='active'`) y **nunca la aceptan por
  HTTP**. El docstring de `/book/composition` (`main.py:37671-37673`) explica además por qué el
  endpoint vive bajo `/api/advisor/` (prefijo exento → inmune al header).
- **Grupos, alertas, TWR, brief, radar** — los 4 módulos externos filtran `status='active'`:
  `advisor_twr.py:29`, `advisor_alerts.py:196`, `advisor_groups.py:159`, `advisor_brief.py:217`.
- **Chat IA en modo libro** — `_advisor_book_chat_context` (`main.py:35425-35452`) arma el contexto
  con los vínculos activos y además **aplana saltos de línea y capea a 60 chars** los labels y
  nombres antes de meterlos en el prompt de Sonnet, contra inyección vía nombre de activo. Bien.

**Un detalle honesto:** `advisor_book_asset_clients` hace el `SELECT` de labels
(`main.py:37859-37863`) **sin** `status='active'`. No es explotable — las claves del dict `per` ya
vienen de `_advisor_client_ids`, así que la query solo puede *no* encontrar una etiqueta, nunca
agregar un cliente. Lo anoto porque es exactamente el tipo de query que en un refactor se convierte
en la fuente de la lista. Ver H-5.

**Y lo verifiqué también por el lado de la escritura de identidad:** ningún endpoint no-exento bajo
contexto de cliente ejecuta `INSERT/UPDATE/DELETE` sobre `users` (barrido: cero resultados). El
asesor no puede cambiarle el email, la contraseña ni el estado de la cuenta a nadie. `DELETE /api/me`
usa `get_effective_user` (`main.py:3807-3808`) pero `/api/me` está exento y el match es por límite de
segmento, así que el header se ignora y **siempre** borra la cuenta del asesor: doble red, correcta.

---

## 4 · Revocación: ¿corta de verdad, y qué sobrevive?

### Lo que funciona

**Hay endpoint del lado del CLIENTE**, no solo del asesor:
`POST /api/me/advisor/{advisor_uid}/revoke` (`main.py:35240-35262`), bajo `get_current_user` y bajo
prefijo exento, con UI en Config › Tu asesor (`Config.jsx:147-160`). El cliente además ve ahí los
pedidos pendientes, "por si el mail cae en promociones". Es correcto y está bien pensado.

Y **corta de inmediato**. MEDIDO (sonda 1, paso 5):

```
POST /api/me/advisor/1/revoke (por el CLIENTE)              -> 200 {"ok":true}
GET  /api/positions ctx=cliente DESPUES de revocar          -> 403
```

Sin cachés que lo esquiven: `_resolve_client_context` pega a la DB en cada request. Y los
derivados también se apagan solos, porque los 5 endpoints del libro y los 4 módulos externos
derivan la lista con el filtro `status='active'` (§3). La revocación del **asesor**
(`main.py:34609-34641`) además cancela en la misma transacción los claim tokens y los link requests
pendientes — para que un "sí" tardío no le devuelva un acceso que acaba de cortar.

### 🔴 H-3 · [ALTO] Los informes no se enteran de la revocación

**Evidencia:** MEDIDO
**Dónde:** `main.py:34419-34462` (`advisor_list_reports`) · `main.py:36053` (`report_public`)

**Qué pasa.** `advisor_reports` guarda el informe **congelado** (`payload` JSON con tenencias, pesos,
valor, P&L, ganadoras/perdedoras y movimientos del período) y un token público. Ni el endpoint que
lo sirve ni el que lo lista miran `advisor_clients`:

- `report_public` (`main.py:36053`) filtra por `revoked_at` y por TTL, **no por vínculo**.
- `advisor_list_reports` (`main.py:34428-34437`) hace `WHERE r.advisor_uid = ?` con un
  **`LEFT JOIN advisor_clients`** — el `LEFT` es justamente lo que hace que la fila sobreviva cuando
  el vínculo ya no está.

MEDIDO — la misma corrida donde el cliente acababa de revocar:

```
GET /api/reports/public/<token> DESPUES de revocar -> 200  (cartera del ex-cliente visible: True)
GET /advisor/reports DESPUES de revocar            -> 200, informes listados: 1
    {"id":1,"client_uid":3,"client":"Cli3","period_start":"2026-01-01","period_end":"2026-06-30",
     "url":"http://localhost:5173/i/XTrdNVmQ22q1YtLDAKljEI","wa_text": ...
```

O sea: el cliente cortó el acceso, `/api/positions` da 403 — y el asesor sigue teniendo, en su
propia pantalla, el link que abre la cartera del ex-cliente, con nombre y teléfono, y el texto de
WhatsApp listo para reenviar.

**Cómo se explota en la práctica.** Un asesor que ve venir la desvinculación genera informes de
todos sus clientes el día antes. Cuesta un `POST` (cap: 200 clientes por llamada, 6 llamadas cada
5 minutos) y le deja una foto navegable de cada cartera que sobrevive a cualquier revocación.

**Qué queda expuesto.** La composición completa de la cartera de un ex-cliente, su rendimiento y sus
movimientos del período, en una URL que abre cualquiera sin cuenta.

**Otros call sites del mismo patrón.** Busqué todas las consultas a `advisor_clients` **sin** filtro
de estado. Son 10 y las revisé una por una: 4 son barridos de borrado (`WHERE advisor_uid=? OR
client_uid=?`), 4 son lookups de etiqueta sobre un `client_uid` ya autorizado, 1 es el join del claim
preview. **`advisor_list_reports:34428` es la única donde la ausencia del filtro decide qué se
devuelve.** El hallazgo cubre N de N.

**Solución de fondo.** El estado del informe ya está modelado (`_estado()`, `main.py:34445-34452`,
distingue `activo|vencido|revocado`): falta la cuarta razón. (a) En `revoke_my_advisor` y
`advisor_revoke_client`, marcar `revoked_at` en los `advisor_reports` de esa pareja dentro de la
misma transacción donde ya se cancelan los claim tokens — el patrón ya está escrito ahí al lado.
(b) En `report_public`, dejar de leer solo la fila del informe y exigir vínculo vivo. (a) sola
alcanza para cerrar el hallazgo; (b) lo hace robusto contra el próximo escritor.

### 🔶 H-4 · [MEDIO] El informe público: 180 días, sin auth, y el cliente ni sabe que existe

**Evidencia:** ESTRUCTURAL (el TTL efectivo en prod depende de una env var que no puedo leer)
**Dónde:** `main.py:35990-36002` (`_report_ttl_days`) · `main.py:36039` (revocación)

El token tiene 22 chars base64url ≈ **131 bits** — no es adivinable, y el diseño de devolver `404` y
no `410` para no confirmar la existencia de un informe filtrado es un detalle fino. Lo que falla es
la **agencia**:

- El default de vida es **180 días** (`REPORTS_TTL_DAYS`, `main.py:35999`), sobre un link que el
  propio docstring reconoce que "viaja por WhatsApp — se reenvía, queda en un chat grupal, en una
  captura".
- **La única revocación es `POST /api/advisor/reports/{report_id}/revoke` (`main.py:36039`), del
  ASESOR.** Grepeé el backend entero: no existe ningún endpoint del lado del cliente para listar ni
  dar de baja los informes que se publicaron sobre su cartera. En Config › Tu asesor tampoco aparecen.

El sujeto del dato no puede ver qué se publicó sobre él ni cortarlo. **Solución de fondo:** extender
`GET /api/me/advisor` con los informes vivos de esa pareja y aceptar el `revoke` del cliente —
reusando el `revoked_at` que ya existe. Es el mismo trabajo que pide H-3, hecho una vez.

### Lo demás sí muere con la revocación

- **Snapshots y valuaciones:** `snapshots` cuelga del `user_id` del cliente; el libro los deja de
  sumar (§3).
- **Notas privadas del asesor** (`advisor_clients.notes`): quedan en la fila revocada, pero solo se
  leen con `status='active'` (`main.py:35504-35505`).
- **Historial de alertas** (`advisor_alert_events`): conserva label + porcentaje del ex-cliente sin
  filtro de vínculo (`advisor_alerts.py:83-88`), pero `purge_old` borra todo lo anterior a
  **`HISTORY_DAYS = 3`** (`advisor_alerts.py:28`). Se limpia solo en 72 h; no lo levanto como hallazgo.

---

## 5 · El entregable: helpers de verificación y quién NO los usa

### Los helpers que existen

| helper | qué verifica | call sites |
|---|---|---|
| `_require_advisor(conn, uid)` — `main.py:2823` | **el ROL** (`tier == 'advisor'`; `is_admin` **no** alcanza, deliberado y comentado). **No verifica ningún vínculo.** | 32 de 33 endpoints `/api/advisor/*` |
| `_advisor_own_link(conn, uid, client_uid)` — `main.py:34566` | **el VÍNCULO con UN cliente** (`advisor_uid=? AND client_uid=? AND status='active'`), 404 si no | **3** |
| `_advisor_client_ids(conn, uid)` — `main.py:36695` | deriva la LISTA de clientes activos | 5 |
| `_resolve_client_context(request, uid)` — `main.py:2767` | el vínculo + el permiso de escritura, para el header | vía `get_effective_user`, 131 endpoints |

No existen `_advisor_check` ni `_assert_client`: los busqué por nombre y por patrón.

### Endpoints `/api/advisor/*` que NO usan ninguno de los dos gates

**Uno solo, y es correcto:**

| endpoint | línea | por qué no lo usa |
|---|---|---|
| `GET\|POST /api/advisor/brief/run-cron` | `33936-33976` | **No es un endpoint de asesor: es un cron externo.** Autentica con `X-Cron-Token`/`?token=` contra `ADVISOR_BRIEF_TOKEN` (fallback `SNAPSHOT_CRON_TOKEN`), **falla cerrado con 503 si la env var no está** (`main.py:33948-33949`) y compara con `!=`. Verificado: `advisor_brief.run_briefs` recorre asesores y **filtra `status='active'`** (`advisor_brief.py:217`). ⚠️ La comparación de tokens no es tiempo-constante — es higiene, no un hallazgo por sí sola; queda para el agente de secretos. |

Y el que llama la atención pero no es un hueco:

| endpoint | línea | dónde está el gate |
|---|---|---|
| `POST /api/advisor/group-op` | `36292` | delegado a `_advisor_group_op_apply` (`main.py:36189`), que abre con `_require_advisor` + validación de vínculo `read_write` fila por fila |

**Los 31 restantes llaman `_require_advisor`.** Es decir: **no hay ningún endpoint de asesor sin
verificación de rol, y ninguno que toque datos de un cliente puntual sin verificación de vínculo.**

### 🔶 H-5 · [MEDIO] `_advisor_own_link` cubre 3 de 14 — el otro 79% reimplementa el predicado a mano

**Evidencia:** ESTRUCTURAL
**Dónde:** 23 ocurrencias en 5 archivos

Existe un helper canónico para "¿este cliente es mío y sigue activo?" y **lo usan 3 endpoints**
(`PATCH /clients/{id}`, `/clients/{id}/revoke`, `/clients/{id}/invite`). Los otros 11 lugares que
necesitan la misma garantía escriben el `WHERE` a mano, en 11 strings SQL distintos. Contando
también las variantes de lista, el predicado `advisor_uid=? AND status='active'` aparece **23 veces**:

```
main.py:2793  34386  34480  34570  34804  34916  34923  35250  35287  35451
        35505  35958  36117  36195  36323  36608  36698  36973  37969
advisor_groups.py:159   advisor_alerts.py:196   advisor_brief.py:217   advisor_twr.py:29
```

**Hoy las 23 son correctas** — las verifiqué una por una. Ese no es el punto. El punto es el que este
repo ya pagó 28 veces: **el predicado de autorización no tiene un solo dueño**, así que un cambio
futuro (agregar un estado `suspended`, un `expires_at` al vínculo, un permiso nuevo) hay que
acordarse de propagarlo a 23 lugares en 5 archivos, y el que se olvide no rompe ningún test — falla
abierto. La query de labels de `asset-clients` (`main.py:37859`, sin filtro de estado) es la
demostración de que la deriva ya empezó: es inocua hoy **porque** la lista viene de otro lado.

**Solución de fondo.** Dos funciones y que nadie escriba ese `WHERE` de nuevo:
`_advisor_own_link(conn, uid, client_uid)` (ya existe, hay que **usarla** en los 11 sitios que hoy
lo hacen inline) y `_advisor_client_ids(conn, uid)` (ya existe, y debe ser la **única** fuente de
listas, incluidos los 4 módulos externos, que hoy tienen su propia copia). Después de eso, un grep
de `advisor_clients` fuera de esos dos helpers debería devolver solo INSERT, UPDATE y barridos de
borrado — y ese grep se puede dejar como test.

---

## Hallazgos menores

### 🔹 H-6 · [BAJO] `AdvisorInviteIn.email` no valida formato

**Evidencia:** ESTRUCTURAL · **Dónde:** `main.py:34677-34683`

`RegisterIn` tiene un `@field_validator('email')` con `_EMAIL_RE` (`main.py:2866-2872`).
`AdvisorInviteIn` (`main.py:34677`) declara `email: str = Field(..., max_length=254)` **y nada más**;
la única normalización es `.strip().lower()` en el handler (`main.py:34697`). Es el único modelo de
email del repo que no valida.

Busqué el escalamiento y **no está**: `claim_account` (`main.py:35119-35170`) no toca `is_admin`, y
`_is_admin_email` solo se consulta en el registro. La colisión por mayúsculas tampoco es explotable
en cuentas nuevas — `users.email` es `TEXT UNIQUE` (`main.py:713`), case-sensitive en SQLite, pero
el validador de `RegisterIn` baja todo a minúsculas antes de insertar, así que no puede existir un
`Nico@Gmail.com` que un invite a `nico@gmail.com` esquive. **Lo que no puedo descartar** es que haya
filas legacy anteriores a ese validador (no tengo la base de prod; ver la sección final). El impacto
real hoy es que el `INSERT` guarda basura y el envío falla en Resend. **Solución:** el mismo
`@field_validator` que ya usa `RegisterIn` — literalmente cinco líneas copiadas.

### 🔹 H-7 · [BAJO] La cookie le gana al header, en silencio

**Evidencia:** MEDIDO (de la forma más incómoda: casi me falsea un hallazgo)
**Dónde:** `main.py:2731-2733`

```python
token = request.cookies.get(COOKIE_NAME)
if not token and creds:
    token = creds.credentials
```

Si llegan **las dos** credenciales y son de usuarios distintos, gana la cookie y no hay ni error ni
log. Verificado en vivo: `POST /api/auth/claim` auto-loguea con `set_auth_cookie`, y a partir de ese
punto mi sonda enviaba `Authorization: Bearer <asesor>` y el backend resolvía **el cliente**. En el
navegador esto no pasa (el front usa cookie), pero es la clase de precedencia silenciosa que
convierte un bug en una confusión de identidad. **Solución:** ante ambas presentes y `sub` distinto,
401 explícito. Barato, y hace ruido cuando algo está mal.

---

## Lo que NO pude verificar (dicho explícitamente)

1. **Producción.** No hice ni una request a la app desplegada (regla 2). Todo lo MEDIDO sale de
   `TestClient` in-process sobre `b74f450f` con base temporal.
2. **El valor real de `REPORTS_TTL_DAYS` en Railway.** H-4 asume el default de 180 días
   (`main.py:35999`). Si en prod está en `0`, los links **no vencen nunca** y H-4 sube de severidad.
   Se resuelve mirando las variables de entorno de Railway.
3. **Si `ADVISOR_BRIEF_TOKEN` / `SNAPSHOT_CRON_TOKEN` están seteadas en prod.** Si ninguna lo está,
   `/advisor/brief/run-cron` responde 503 a todo el mundo (falla cerrado, correcto) y el brief
   simplemente no corre. No puedo distinguir los dos casos desde el código.
4. **Cuántas cuentas tienen `tier='advisor'` hoy, y cuántos vínculos `managed` vs `linked` hay en
   prod.** Sin la base no puedo dimensionar el blast radius de H-1 y H-3 — solo describir el
   mecanismo. Es una query de dos líneas contra la copia estampada, si existe una.
5. **Emails legacy con mayúsculas** (`SELECT COUNT(*) FROM users WHERE email != lower(email)`).
   Si el resultado es 0, H-6 queda estrictamente en higiene.
6. **El backend Postgres (`USANDO_PG`).** Leí `schema_pg.sql` solo para confirmar que las tablas
   `advisor_*` existen. **No verifiqué la colación de `users.email` en Postgres**, donde el
   comportamiento de `=` y de `UNIQUE` puede diferir de SQLite; el análisis de H-6 vale para SQLite.
7. **El frontend como control de seguridad.** Leí las pantallas para contrastar la **promesa**
   (H-1, H-2). No audité su lógica: el gate real es el backend y ahí es donde medí.
8. **La suite `tests/test_advisor_plan.py` completa.** La leí (es una batería IDOR seria) pero no la
   corrí: escribí sondas propias para no confundir "el test pasa" con "el sistema hace lo que dice".
