# Autorización entre usuarios — tramo 5 de 6 (`main.py` 30738–33879)

> Auditoría de seguridad · Tanda A · commit auditado `b74f450f` (`/tmp/rendi-main`).
> Área: **autorización entre usuarios** — sesión, propiedad del recurso, filtro por `user_id`,
> contexto de cliente del Plan Asesor, escrituras por GET.
> Este documento **no contiene ningún valor de secreto**.

---

## Método

- **NO ejecuté nada contra producción.** No levanté el backend, no firmé JWTs, no mandé
  requests a la app desplegada, no toqué código fuera de `audit/`.
- **Leído íntegro** el rango 30738–33879 de `/tmp/rendi-main/backend/main.py` (verificado:
  38.029 líneas, coincide con el handoff), más los módulos que ese rango llama y de los que
  depende la decisión de autorización:
  `importing/pipeline.py`, `importing/persister.py`, `alerts_engine.py`, `advisor_groups.py`,
  `advisor_twr.py`, `twr.py`, `wallbit.py`, `iol_api.py`, `mantenimiento.py`, `schema_pg.sql`,
  y los helpers `get_current_user` / `get_effective_user` / `_resolve_client_context` /
  `_require_advisor` / `_check_rate_limit` / `_ip_del_cliente` / `_wipe_broker_data`
  (`main.py:2691–2830`).
- **Barrido sistemático** de todas las sentencias SQL del rango que NO mencionan
  `user_id` / `advisor_uid` / `uid`, para no depender de la lectura secuencial:
  ```
  awk 'NR>=30738 && NR<=33879' main.py \
    | grep -n "SELECT\|UPDATE \|DELETE FROM\|INSERT INTO" | grep -vi "user_id\|advisor_uid\|uid"
  ```
  → 36 líneas, revisadas una por una. Las que quedaron como hallazgo están abajo.
- **Verificación de deriva contra `origin/main`** (11 commits adelante) para los dos hallazgos
  principales: **los dos siguen vivos** (`git show origin/main:backend/main.py | grep -n …` →
  `33597` para el `DELETE` de `alert_symbol_state`, y `31568 / 33627 / 33695 / 33977` para los
  cuatro `got != expected`).
- **Evidencia**: todo lo de abajo es **ESTRUCTURAL** (falta un filtro, se cita con grep) o
  **DEDUCIDO** (razonamiento sobre código leído, con los supuestos dichos). **No hay ningún
  MEDIDO en este informe**: no ejecuté ataque ni prueba. Lo digo explícito para no inflar nada.
- El mapa `audit/00-mapa-sistema.md` **no se usó**: todas las citas de acá salen de grep sobre
  el código real.

### ⚠️ El inventario de endpoints tiene un agujero (y justo en lo peor de este tramo)

`_inventario_endpoints.txt` tiene 260 filas y **cero** endpoints declarados con
`@app.api_route`. En `main.py` hay **4**, y son exactamente los cuatro endpoints de cron —
los únicos que **no piden sesión** y **escriben datos de TODOS los usuarios**:

```
31559:@app.api_route("/api/iol/lab/run-cron",     methods=["GET", "POST"])
33590:@app.api_route("/api/alerts/evaluate",      methods=["GET", "POST"])
33647:@app.api_route("/api/snapshots/run-cron",   methods=["GET", "POST"])
33936:@app.api_route("/api/advisor/brief/run-cron", methods=["GET", "POST"])
```

Tres caen en mi tramo. **Los audito igual y van en la tabla**, así que mi tabla tiene 46 filas:
los 43 del inventario + esos 3. El cuarto (33936) queda fuera de mi rango pero comparte el
mismo defecto y lo cito en H-2 por la regla de propagación.

---

## Resumen — hallazgos por severidad

| id | sev | título | archivo:línea | evidencia |
|---|---|---|---|---|
| H-1 | **ALTO** | `DELETE /api/alerts/{id}` borra el estado de las alertas de OTRO usuario (`alert_symbol_state` no tiene `user_id` y la query no filtra por nada) | `main.py:33572` | ESTRUCTURAL |
| H-2 | **ALTO** | Los 4 endpoints de cron comparan el token con `!=` (no `hmac.compare_digest`), lo aceptan por **query string** y no tienen rate limit — y escriben para todos los usuarios | `main.py:31567, 33600-33602, 33668-33670, 33950-33952` | ESTRUCTURAL |
| H-3 | **ALTO** | Las credenciales de broker (Wallbit + refresh token de IOL) se cifran con una Fernet **derivada de `SECRET_KEY`**, que el Paso 0 ya demostró hardcodeada | `main.py:31013-31026` | DEDUCIDO |
| H-4 | **MEDIO** | `/api/wallbit/*` NO está exento del contexto de cliente: un asesor `read_write` planta, usa y borra credenciales de broker en la cuenta del cliente | `main.py:2748-2757` vs `31218/31238/31278/31310` | DEDUCIDO |
| H-5 | **MEDIO** | GETs que ESCRIBEN: `/api/iol/lab/status` y `/api/advisor/twr`. El chequeo de `read_write` sólo corre para métodos no-GET | `main.py:2799`, `31472-31481`, `33707-33709` | ESTRUCTURAL |
| H-6 | **MEDIO** | `PATCH /api/alerts/{id}` hace el `UPDATE` final con `WHERE id=?` sin `user_id` (hoy blindado por un `SELECT` previo — un `WHERE` de más, no un fix) | `main.py:33557` | ESTRUCTURAL |
| H-7 | **BAJO** | Tres consultas del tramo leen por id sin repetir el filtro de dueño, alcanzables sólo después de la validación | `main.py:30957`, `31646`, `31406` | ESTRUCTURAL |
| H-8 | **BAJO** | `POST /api/sections/restore` arma el `INSERT` interpolando nombres de columna leídos de un JSON | `main.py:31873` | ESTRUCTURAL |
| H-9 | **BAJO** | `POST /api/imports/wipe-broker` recibe el nombre del broker por query string (queda en logs de proxy) | `main.py:31740` | ESTRUCTURAL |
| H-10 | **BAJO** | `/api/iol/lab/status` responde `{"enabled": false, "reason": …}` distinguiendo "no configurado" de "no estás en la lista" | `main.py:31466-31468` | ESTRUCTURAL |

**Lo que NO encontré, y vale decirlo:** ningún endpoint de este tramo permite **leer** datos de
otro usuario. Los 43 del inventario validan sesión (43/43) y los 20 que reciben un id de recurso
lo resuelven contra el dueño antes de usarlo. El gate de IOL Lab (`IOL_LAB_EMAILS`) **falla
cerrado** y es sólido. Los 8 endpoints de `/api/advisor` derivan todo del roster
`advisor_clients WHERE advisor_uid=? AND status='active'`. **No hay ningún CRÍTICO en este
tramo.**

---

## Tabla — los 43 del inventario + los 3 crons que el inventario no ve

| # | línea | método | ruta | qué hace | valida sesión | valida propiedad | veredicto |
|---|---|---|---|---|---|---|---|
| 1 | 30738 | POST | `/api/imports/confirm` | Aplica un batch de import (persist + rebuild FIFO + recalc + snapshots) | `get_effective_user` | Sí — `load_session_*_revalidate` → `import_batches WHERE id=? AND user_id=?` (`pipeline.py:1046`, `1119`) | OK (ver H-7) |
| 2 | 31218 | GET | `/api/wallbit/status` | ¿Hay conector Wallbit? última sync | `get_effective_user` | n/a — no recibe id; la query filtra `WHERE user_id=?` | REVISAR: H-4 (un asesor read-only ve el conector del cliente) |
| 3 | 31238 | POST | `/api/wallbit/connect` | Valida la API key, la guarda cifrada, sync inicial completo | `get_effective_user` + rate limit 6/60s | n/a — escribe `WHERE user_id=?` | MEDIO: H-3, H-4 |
| 4 | 31278 | POST | `/api/wallbit/sync` | Descifra la key guardada y re-sincroniza | `get_effective_user` + rate limit 10/60s | n/a — lee/escribe `WHERE user_id=?` | MEDIO: H-3, H-4 |
| 5 | 31310 | DELETE | `/api/wallbit/disconnect` | Borra la credencial | `get_effective_user` | n/a — `DELETE … WHERE user_id=?` | MEDIO: H-4 |
| 6 | 31464 | GET | `/api/iol/lab/status` | Estado del lab + **refresh oportunista del token** | `get_current_user` + `_iol_lab_gate` | n/a — todo `WHERE user_id=?` | MEDIO: H-5 (GET que escribe), H-10 |
| 7 | 31490 | POST | `/api/iol/lab/probe` | Login a IOL con user+pass del tester, probe read-only en thread | `get_current_user` + gate + rate limit 5/600s | n/a | OK (relay de credenciales, pero gateado y sin persistir la contraseña) |
| 8 | 31531 | POST | `/api/iol/lab/refresh` | Renueva el refresh token propio | `get_current_user` + gate + rate limit | n/a — `WHERE user_id=?` | OK |
| 9 | 31544 | DELETE | `/api/iol/lab/disconnect` | Borra el refresh token propio | `get_current_user` + gate | n/a — `WHERE user_id=?` | OK |
| 10 | **31559** | GET+POST | `/api/iol/lab/run-cron` | Renueva el token de **todos** los testers | **Ninguna sesión** — sólo `IOL_LAB_CRON_TOKEN` | n/a — itera todos los `user_id` | **ALTO: H-2** |
| 11 | 31608 | GET | `/api/admin/iol-lab/runs` | Todas las corridas + emails de los testers | `get_admin_user` | n/a — es admin por diseño | OK |
| 12 | 31627 | GET | `/api/imports` | Lista batches del usuario | `get_effective_user` | n/a — `list_batches` filtra `WHERE user_id=?` (`pipeline.py:1030`) | OK |
| 13 | 31637 | GET | `/api/imports/{batch_id}` | Detalle del batch + filas crudas | `get_effective_user` | Sí — `WHERE id=? AND user_id=?` → 404 | OK (ver H-7) |
| 14 | 31665 | GET | `/api/imports/mappings` | Plantillas de mapeo | `get_effective_user` | n/a — `WHERE user_id=?` | OK |
| 15 | 31684 | POST | `/api/imports/mappings` | Guarda plantilla (upsert por `(user_id,name)`) | `get_effective_user` | n/a | OK |
| 16 | 31707 | DELETE | `/api/imports/mappings/{mid}` | Borra plantilla | `get_effective_user` | Sí — `DELETE WHERE id=? AND user_id=?` | OK |
| 17 | 31718 | POST | `/api/imports/recalc-pnl` | Recalcula P&L realizado del usuario | `get_effective_user` | n/a | OK |
| 18 | 31740 | POST | `/api/imports/wipe-broker` | Borrado nuclear de un broker (ops + posiciones + monthly) | `get_effective_user` | Sí — `brokers WHERE user_id=? AND name=?` → 404; `_wipe_broker_data` scoped al uid | OK (ver H-9) |
| 19 | 31800 | GET | `/api/sections/archived` | Secciones archivadas | `get_effective_user` | n/a — `WHERE user_id=?` | OK |
| 20 | 31814 | POST | `/api/sections/archive` | Archiva (borra reversible) una sección de renta fija | `get_effective_user` | n/a — recibe una clave de sección, no un id; `_positions_in_section` filtra `WHERE user_id=?` | OK |
| 21 | 31853 | POST | `/api/sections/restore` | Restaura una sección archivada | `get_effective_user` | Sí — `archived_positions WHERE id=? AND user_id=?` → 404 | OK (ver H-8) |
| 22 | 31890 | POST | `/api/imports/{batch_id}/revert` | Revierte un batch confirmado | `get_effective_user` | Sí — `revert_batch` → `WHERE id=? AND user_id=?` (`persister.py:1341`) | OK |
| 23 | 31930 | POST | `/api/imports/{batch_id}/redo` | Revierte en nuclear y re-abre el preview | `get_effective_user` | Sí — `WHERE id=? AND user_id=?` → 404, y `reconstruct_csv_from_batch` lo re-valida | OK |
| 24 | 33072 | GET | `/api/reports/timeline` | Timeline de N meses | `get_effective_user` | n/a — `months` capeado 1..36; `reporting/` es read-only (verificado por grep: 0 `INSERT/UPDATE/DELETE`) | OK |
| 25 | 33136 | GET | `/api/reports/period/{pt}/{pk}` | Detalle de un período | `get_effective_user` | n/a — `period_type` en allowlist, `period_key` parseado con `int()`; `br_clause` con placeholders (`main.py:32659`) | OK |
| 26 | 33235 | GET | `/api/home/indices` | Strip de índices | `get_effective_user` | n/a — dato de mercado, no del usuario | OK |
| 27 | 33241 | GET | `/api/home/heatmap` | Heatmap | `get_effective_user` | n/a — `market` validado contra `MARKETS` | OK |
| 28 | 33249 | GET | `/api/home/movers` | Top gainers/losers | `get_effective_user` | n/a — idem | OK |
| 29 | 33272 | GET | `/api/watchlist` | Watchlist + quotes | `get_effective_user` | n/a — `WHERE user_id=?` | OK |
| 30 | 33297 | POST | `/api/watchlist` | Agrega símbolo | `get_effective_user` | n/a — símbolo validado por regex | OK |
| 31 | 33314 | DELETE | `/api/watchlist/{symbol}` | Saca símbolo | `get_effective_user` | Sí — `WHERE user_id=? AND symbol=?` | OK |
| 32 | 33411 | GET | `/api/alerts` | Alertas + últimos disparos | `get_effective_user` | n/a — ambas queries `WHERE user_id=?` | OK |
| 33 | 33432 | POST | `/api/alerts` | Crea alerta (cuota + gate de plan) | `get_effective_user` | n/a | OK |
| 34 | 33519 | PATCH | `/api/alerts/{alert_id}` | Edita/activa/pausa | `get_effective_user` | Sí (por el `SELECT` previo) — pero el `UPDATE` es `WHERE id=?` a secas | **MEDIO: H-6** |
| 35 | 33563 | DELETE | `/api/alerts/{alert_id}` | Borra alerta + eventos + estado por símbolo | `get_effective_user` | **NO** para `alert_symbol_state` | **ALTO: H-1** |
| 36 | 33578 | POST | `/api/alerts/events/seen` | Marca eventos vistos | `get_effective_user` | n/a — `WHERE user_id=?` | OK |
| 37 | **33590** | GET+POST | `/api/alerts/evaluate` | Evalúa las alertas de **todos** y manda push/mail | **Ninguna sesión** — `ALERTS_CRON_TOKEN` | n/a | **ALTO: H-2** |
| 38 | **33647** | GET+POST | `/api/snapshots/run-cron` | Snapshot diario de la cartera de **todos** | **Ninguna sesión** — `SNAPSHOT_CRON_TOKEN` | n/a | **ALTO: H-2** |
| 39 | 33698 | GET | `/api/advisor/twr` | TWR por cliente — **sella meses antes de leer** | `get_current_user` + `_require_advisor` | Sí — `_clientes_vigentes` → `advisor_clients WHERE advisor_uid=? AND status='active'` | MEDIO: H-5 (GET que escribe en filas de los clientes) |
| 40 | 33715 | GET | `/api/advisor/data-health` | Semáforo de datos del libro (read-only) | `get_current_user` + `_require_advisor` | Sí — mismo roster | OK |
| 41 | 33730 | GET | `/api/advisor/groups` | Grupos + cuántos caen ahora | `get_current_user` + `_require_advisor` | Sí — `advisor_groups WHERE advisor_uid=?` y `client_profiles` sobre el roster | OK |
| 42 | 33751 | POST | `/api/advisor/groups` | Crea grupo (tope `MAX_GROUPS`) | `get_current_user` + `_require_advisor` | n/a — inserta con `advisor_uid=uid` | OK |
| 43 | 33776 | PATCH | `/api/advisor/groups/{group_id}` | Edita grupo | `get_current_user` + `_require_advisor` | Sí — `get_group(conn, uid, gid)` → 404, **y** el `UPDATE` repite `WHERE id=? AND advisor_uid=?` | OK (es el patrón correcto; comparar con H-6) |
| 44 | 33807 | DELETE | `/api/advisor/groups/{group_id}` | Borra grupo + apaga su alerta | `get_current_user` + `_require_advisor` | Sí — `DELETE WHERE id=? AND advisor_uid=?`, y **404 si `rowcount==0`** | OK |
| 45 | 33836 | POST | `/api/advisor/groups/preview` | Quiénes caen sin guardar | `get_current_user` + `_require_advisor` | n/a — `excluded` es sólo un filtro negativo sobre el roster propio | OK |
| 46 | 33852 | GET | `/api/advisor/groups/{group_id}/clients` | Clientes del grupo | `get_current_user` + `_require_advisor` | Sí — `get_group(conn, uid, gid)` → 404 | OK |

**Sesión: 43/43 del inventario la validan.** Los 3 endpoints públicos-por-token son los crons,
y ninguno de ellos está en el inventario.

---

## Hallazgos

### [ALTO] H-1 · `DELETE /api/alerts/{id}` borra el estado de las alertas de otro usuario

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:33563-33576` (el `DELETE` culpable en `main.py:33572`);
schema en `main.py:1704-1711` y `schema_pg.sql:442-449`.
Vive igual en `origin/main:backend/main.py:33597`.

**Qué pasa:** el handler hace tres borrados. Los dos primeros están bien scopeados; el tercero
no tiene ningún filtro de dueño:

```python
conn.execute("DELETE FROM alerts       WHERE id=? AND user_id=?", (alert_id, uid))          # ok
conn.execute("DELETE FROM alert_events WHERE alert_id=? AND user_id=?", (alert_id, uid))    # ok
conn.execute("DELETE FROM alert_symbol_state WHERE alert_id=?", (alert_id,))                # ← 33572
```

Y no hay red de contención posible más abajo, porque **`alert_symbol_state` no tiene columna
`user_id` ni FK a `alerts`**:

```sql
CREATE TABLE IF NOT EXISTS alert_symbol_state (
    alert_id INTEGER NOT NULL,
    symbol   TEXT NOT NULL,
    armed    INTEGER NOT NULL DEFAULT 1,
    last_fired_date TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (alert_id, symbol)
);
```

El handler **no hace un `SELECT` de propiedad antes** (a diferencia del PATCH de al lado), así
que un `alert_id` ajeno no aborta nada: los dos primeros `DELETE` borran 0 filas en silencio y
el tercero borra las del dueño real. Devuelve `{"ok": True}` siempre.

**Cómo se explota en la práctica:** `alerts.id` es `INTEGER PRIMARY KEY AUTOINCREMENT` en SQLite
y `GENERATED BY DEFAULT AS IDENTITY` en Postgres (`schema_pg.sql:462`) — o sea, **enteros
correlativos, triviales de enumerar**. Cualquier usuario con una cuenta gratuita itera
`DELETE /api/alerts/1 … /api/alerts/N` y limpia la tabla entera. No hace falta ningún rol, ni
ninguna fuga, ni el header del Plan Asesor.

**Qué queda expuesto:** no es una fuga de datos — es una **escritura cruzada entre inquilinos**.
`alert_symbol_state` es el edge-trigger y el tope de "1 disparo por día" de las alertas
`pct_move` (`alerts_engine.py:170-200`):

```python
def _sym_state(conn, alert_id, symbol):
    row = conn.execute("SELECT armed, last_fired_date FROM alert_symbol_state WHERE alert_id=? AND symbol=?", …)
    if not row:
        return (1, None)     # ← sin fila = ARMADA y sin disparo previo
```

Borrar la fila devuelve la alerta ajena a `(armed=1, last_fired_date=None)`. En la corrida
siguiente del cron, la alerta del otro usuario **vuelve a dispararse sobre un movimiento que ya
había notificado**, mandando push y mail (`channel='both'` es el default). Repetido en bucle es
un canal de spam a la casilla de la víctima **desde la infraestructura de Rendi**, con el
remitente de Rendi: además del ruido, quema la reputación del dominio de envío.

**Otros call sites del mismo patrón:** grepeé las tres únicas escrituras a esta tabla en todo el
repo — `alerts_engine.py:183` y `alerts_engine.py:194` (ambas dentro del motor del cron, con el
`alert_id` que el propio motor acaba de leer de `alerts`, así que están bien) y esta. Es el
**único** call site roto. En el resto del tramo el patrón correcto sí está aplicado: el mejor
contraejemplo es `advisor_groups_delete` (`main.py:33812-33818`), que borra con
`WHERE id=? AND advisor_uid=?` **y** devuelve 404 si `rowcount==0`, con un comentario que
explica exactamente por qué ("sin filas borradas el grupo no era suyo… decir 'ok' sería mentir").
Ese razonamiento no se propagó 240 líneas más arriba.

**Solución de fondo:** el filtro por `user_id` no se puede poner en la query porque **la columna
no existe**. Parchear con un `SELECT` de propiedad previo repetiría el error de H-6 (blindaje por
orden de ejecución, que la próxima refactorización se lleva puesto). La causa real es de
**esquema**: `alert_symbol_state` cuelga de `alerts` sin decirlo. El arreglo de fondo es
`FOREIGN KEY (alert_id) REFERENCES alerts(id) ON DELETE CASCADE` — con eso el tercer `DELETE`
sobra: lo hace la base al borrar la fila de `alerts`, y sólo si esa fila era del usuario.
Ojo con el orden de la migración (ver `project_migration_index_order.md`) y con que en SQLite
la FK sólo actúa con `PRAGMA foreign_keys=ON`, que `get_db()` **sí** setea (`main.py:2857`).

---

### [ALTO] H-2 · Los 4 crons: token comparado con `!=`, aceptado por query string, sin rate limit, y escriben para todos

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:31564-31568`, `33597-33602`, `33665-33670`, `33946-33952`.
Vivos los cuatro en `origin/main` (`31568`, `33627`, `33695`, `33977`).

**Qué pasa:** los cuatro endpoints de cron repiten el mismo bloque literal:

```python
expected = (os.environ.get("SNAPSHOT_CRON_TOKEN") or "").strip()
if not expected:
    raise HTTPException(503, …)                       # ✅ falla cerrado, esto está bien
got = (request.headers.get("x-cron-token")
       or request.query_params.get("token") or "").strip()
if got != expected:                                   # ← 1) comparación no constant-time
    raise HTTPException(401, "Token inválido.")
```

Tres defectos, y ningún `_check_rate_limit` en ninguno de los cuatro:

1. **`!=` en vez de `hmac.compare_digest`.** El `==` de `str` en CPython corta en el primer byte
   distinto. Es el canal lateral de timing clásico.
2. **El token se acepta por query string.** Un token en la URL queda en los access logs del
   proxy (Railway), en el `Referer` y en el historial. Los tokens de cron no rotan.
3. **Sin rate limit ni lockout.** El resto de la app tiene 27 rate limiters
   (`_check_rate_limit`, `main.py:…`); estos cuatro no llaman a ninguno. Se puede sondear a
   velocidad de red, indefinidamente, sin dejar más rastro que 401s.

Y hay un cuarto punto que agrava a los tres: **son `GET` además de `POST`** (`@app.api_route(…,
methods=["GET","POST"])`), o sea que un acierto se materializa con una URL en la barra del
navegador.

**Cómo se explota en la práctica:** el vector realista no es romper el token por fuerza bruta
(dependen de su longitud, que no medí), sino **encontrarlo**: en los logs del proxy, en un
`Referer` saliente, en el historial de quien alguna vez lo pegó a mano, o en la configuración
del cron externo (cron-job.org). Los tres defectos conspiran: el token viaja por un canal que se
loguea, no rota, y no hay ningún límite que convierta un sondeo en ruido detectable.

**Qué queda expuesto:** los cuatro **escriben para todos los usuarios de Rendi** y ninguno
requiere sesión:

- `/api/snapshots/run-cron` → dispara la valuación diaria de **toda** la base. Es idempotente
  (UPSERT por `(user_id,date)`), pero es también el motor del que salen la variación diaria y
  el TWR. Correrlo a destiempo (con el MEP del día equivocado, o a mitad de rueda) reescribe la
  foto del día de todos.
- `/api/alerts/evaluate` → evalúa **todas** las alertas activas y **dispara push y mail**. Un
  atacante con el token manda notificaciones a toda la base de usuarios.
- `/api/iol/lab/run-cron` → renueva (y ante un 4xx **borra**) las credenciales guardadas de
  todos los testers de IOL Lab.
- `/api/advisor/brief/run-cron` → arma y **manda por mail** el brief del libro a todos los
  asesores.

**Otros call sites del mismo patrón — y por qué esto es un caso de libro de la regla de
propagación:** el patrón CORRECTO ya está escrito en este repo, con la justificación explícita,
en `mantenimiento.py:56-58` y `:100-112`:

> *"El bypass va por header y no por query param porque un token en la URL queda en los logs del
> proxy, en el historial del navegador y en el `Referer`. Se compara con `hmac.compare_digest`,
> que no filtra información por el tiempo que tarda."*

```python
def bypass_valido(valor):
    esperado = _marca("RENDI_MANTENIMIENTO_TOKEN")
    if not esperado or not valor:
        return False
    return hmac.compare_digest(valor, esperado)     # mantenimiento.py:112
```

Y `hmac.compare_digest` se usa correctamente en otros 8 lugares: `main.py:134` (hash del email
admin), `main.py:3273` (código de verificación), `billing/mercadopago.py:236`,
`billing/rebill.py:356, 451, 457, 473, 479`. **La decisión ya se tomó, se documentó y se aplicó
en 9 sitios; los 4 crons son los 4 que quedaron afuera** — y son justo los que escriben para
todos. Grep de control:

```
$ grep -n "compare_digest" backend/main.py
134:    return hmac.compare_digest(h, ADMIN_EMAIL_HASH)
3273:            if not hmac.compare_digest(str(row["code"]), str(data.code))
$ grep -n "got != expected" backend/main.py
31567 / 33602 / 33670 / 33952
```

**Solución de fondo:** no cuatro parches. Un único helper —
`def _cron_autorizado(request, *nombres_de_env) -> None` — que centralice: `compare_digest`,
**sólo header** (dejar de leer `query_params["token"]`), rate limit por IP, y log del intento
fallido. Los cuatro endpoints lo llaman. Mientras el query param siga aceptado, cualquier
rotación del secreto queda desmentida por el log del proxy que lo guardó. Bajar los cuatro a
`methods=["POST"]` es el complemento natural (cron-job.org sabe hacer POST) y de paso cierra el
lado CSRF de H-5.
**⚠️ posible cruce con F1** — `/api/snapshots/run-cron` entra por `snapshots_job.py`.

---

### [ALTO] H-3 · Las credenciales de broker se cifran con una clave derivada de `SECRET_KEY`

**Evidencia:** DEDUCIDO
**Supuesto:** que `audit/05_seguridad/5a-paso0-secret-key.md` está en lo cierto sobre el valor
de `SECRET_KEY` en producción. No re-verifiqué ese hallazgo ni descifré nada.
**Dónde:** `main.py:31013-31026`.

**Qué pasa:** la Fernet con la que se cifran **todas** las credenciales de broker sale de un
SHA-256 de `SECRET_KEY`:

```python
def _wallbit_cipher():
    digest = hashlib.sha256((SECRET_KEY or "dev-insecure").encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))
```

`_wallbit_encrypt` / `_wallbit_decrypt` son los únicos accesos a `user_broker_credentials.
api_key_enc`, y los usan **dos** integraciones, no una: Wallbit (`main.py:31264`, `31288`) y el
refresh token de IOL Lab (`main.py:31647`, `31718`, `31780` — el comentario del bloque IOL lo
dice: *"Fernet, misma tabla que Wallbit"*).

**Cómo se explota en la práctica:** no es un endpoint. Es una **cadena de dependencia**: quien
tenga `SECRET_KEY` (que el Paso 0 encontró hardcodeada en `start-rendi.sh:43`) y una copia del
contenido de `user_broker_credentials` obtiene en claro las API keys de Wallbit y los refresh
tokens de IOL de cada usuario conectado. La misma clave firma los JWT de sesión (HS256,
simétrico), así que el mismo compromiso da las dos cosas.

**Qué queda expuesto:** credenciales de terceros. Una API key de Wallbit con permiso `read` da
acceso directo a la cartera real del usuario **en el broker**, sin pasar por Rendi. Un refresh
token de IOL renueva solo y sobrevive al cambio de contraseña del usuario.

**Otros call sites del mismo patrón:** los 6 usos de `_wallbit_encrypt`/`_wallbit_decrypt` están
todos en este tramo (`31264`, `31288`, `31647`, `31718`, `31780`, y `31752` en el probe). No hay
un segundo esquema de cifrado en el repo — lo cual es bueno (un solo lugar donde arreglarlo) y
malo (un solo secreto para todo).

**Solución de fondo:** separar la raíz de confianza de los datos de la de las sesiones. Una
`CREDENTIALS_KEY` propia (una Fernet key de verdad, no un digest de otra cosa), rotable sin
desloguear a nadie, con `MultiFernet` para poder rotar sin perder lo ya guardado. Y —
consecuencia práctica de la rotación — al girar la clave hay que **invalidar y pedir reconexión**
de las credenciales que no se puedan re-cifrar, no borrarlas en silencio como hace hoy
`_iol_lab_refresh_one` (`main.py:31721-31725`: *"dead: no se pudo descifrar el token (SECRET_KEY
cambió)"* → `DELETE`).

---

### [MEDIO] H-4 · `/api/wallbit/*` no está exento del contexto de cliente: el asesor maneja credenciales de broker ajenas

**Evidencia:** DEDUCIDO
**Supuesto:** que existe al menos un vínculo `advisor_clients` con `permission='read_write'`
(el comentario del código lo llama "managed" y lo trata como el caso normal del plan).
**Dónde:** `CLIENT_CTX_EXEMPT_PREFIXES` en `main.py:2748-2757`; los cuatro endpoints Wallbit en
`31218`, `31238`, `31278`, `31310`.

**Qué pasa:** los cuatro endpoints de Wallbit usan `get_effective_user`, y `/api/wallbit` **no**
figura en la lista de prefijos exentos:

```python
CLIENT_CTX_EXEMPT_PREFIXES = (
    "/api/auth", "/api/billing", "/api/admin", "/api/advisor",
    "/api/me", "/api/push", "/api/plan/track", "/api/feedback",
)
```

El propio comentario de arriba define la intención de la lista como *"identidad/cuenta (auth),
billing, admin…"* y avisa, con todas las letras:

> `# ⚠️ FAIL-OPEN: todo endpoint futuro FUERA de estos prefijos hereda el contexto de cliente.`
> `# Si agregás un endpoint de IDENTIDAD/CUENTA/PAGO nuevo, agregalo acá.`

Las credenciales de un broker externo son material de cuenta tanto como el email o el medio de
pago. La lista se escribió pensando en tres categorías y los conectores no existían todavía:
el fail-open funcionó exactamente como el comentario advirtió que funcionaría.

**Cómo se explota en la práctica:** no hace falta explotar nada — es una capacidad que el
producto concede hoy. Un asesor con un vínculo `read_write` manda
`X-Rendi-Client-Id: <client_uid>` y:

- **`POST /api/wallbit/connect`** → guarda **una API key elegida por él** cifrada en la fila del
  cliente, y dispara un sync completo que escribe trades, posiciones y P&L en la cuenta del
  cliente. El cliente ve un conector que nunca conectó.
- **`POST /api/wallbit/sync`** → hace que Rendi **use la API key del cliente** contra
  `api.wallbit.io` cuando el asesor lo decide.
- **`DELETE /api/wallbit/disconnect`** → borra la credencial del cliente. Silencioso.
- **`GET /api/wallbit/status`** → esta la alcanza **cualquier** vínculo, incluso el read-only
  (`linked`), porque `_resolve_client_context` sólo exige `read_write` para métodos no-GET
  (`main.py:2799`).

**Qué queda expuesto:** el control del conector de broker de otra persona. No es una fuga de la
cartera (eso el asesor ya lo ve por diseño), es la capacidad de **plantar y destruir credenciales
de un tercero** en su cuenta. `_check_rate_limit(…, suffix=f"wallbit_connect:{uid}")` usa el uid
**efectivo**, así que además el asesor consume la cuota del cliente.

**Otros call sites del mismo patrón:** revisé qué más del tramo cae en el mismo fail-open.
`/api/imports/*` y `/api/sections/*` también heredan el contexto — pero ahí es **correcto**:
importar y archivar los datos del cliente es literalmente lo que el plan Asesor vende.
`/api/iol/lab/*` **no** hereda, porque usa `get_current_user` (no `get_effective_user`): esa
integración quedó bien por accidente de haberse escrito con el helper de identidad.
La asimetría entre las dos integraciones de broker —una hereda el contexto, la otra no, sin
ningún comentario que lo explique— es en sí misma la señal de que nadie lo decidió.

**Solución de fondo:** decidirlo explícitamente, no dejarlo al fail-open. Si la respuesta es que
un asesor no administra credenciales de terceros (lo razonable: son credenciales de un servicio
externo, no datos de Rendi), agregar `"/api/wallbit"` y `"/api/iol"` a
`CLIENT_CTX_EXEMPT_PREFIXES` y de paso escribir en el comentario la cuarta categoría que faltaba:
**conectores/credenciales**. Y, ya que la lista es fail-open por diseño, vale un test que
enumere las rutas de `app.routes` y falle si aparece una ruta nueva que no esté clasificada
explícitamente como "hereda contexto" o "exenta": la lista sólo protege lo que alguien se acordó
de agregarle.

---

### [MEDIO] H-5 · GETs que escriben — y el permiso `read_write` sólo se exige a los no-GET

**Evidencia:** ESTRUCTURAL
**Dónde:** la regla en `main.py:2799`; los dos casos en `main.py:31472-31481` y `33707-33709`.

**Qué pasa:** el control de escritura del Plan Asesor se decide **por el verbo HTTP**:

```python
if request.method not in ("GET", "HEAD", "OPTIONS") and row["permission"] != "read_write":
    raise HTTPException(403, "Acceso de solo lectura a ese cliente")
```

Eso vale **sólo** si ningún GET escribe. En este tramo hay dos que sí:

1. **`GET /api/iol/lab/status`** (`31472-31481`): "renovación oportunista" — si hace más de 55
   minutos que no se renueva, llama a `_iol_lab_refresh_one`, que hace `UPDATE` de
   `user_broker_credentials`, `INSERT` en `iol_lab_token_log` y, ante un 4xx de IOL, **`DELETE`
   de la credencial**. Está justificado con un comentario ("abrir la página = avanzar la
   medición") — es una decisión deliberada, no un descuido, y por eso no la marco más alto.
2. **`GET /api/advisor/twr`** (`33707-33709`): `twr_por_cliente(…, sellar_primero=True)` corre
   `twr.sellar(conn, cid)` para cada cliente → `INSERT INTO twr_periods` (`twr.py:824`). También
   documentado ("sella los meses cerrados antes de leer, idempotente").

Ninguno de los dos es hoy explotable a través del contexto de cliente, y conviene decir por qué
con precisión: **los dos usan `get_current_user`, no `get_effective_user`**, y `/api/advisor`
además está en los prefijos exentos. O sea que están a salvo por dos motivos independientes,
ninguno de los cuales es la regla del verbo. El riesgo es de **diseño**: la regla "GET no
escribe" es un invariante que nadie chequea y que ya tiene dos excepciones en 3.000 líneas.
El día que uno de estos dos migre a `get_effective_user` —o que aparezca un GET-que-escribe
nuevo bajo `get_effective_user`— un vínculo read-only escribirá en la cuenta del cliente y el
403 no va a saltar.

**Cómo se explota en la práctica (el lado CSRF, hoy):** la sesión viaja en la cookie HttpOnly
`rendi_token` con `samesite="lax"` (`main.py:158`) y **no hay token CSRF** (grep: 0 apariciones
de `csrf` en `main.py`). Lax bloquea la cookie en POST cross-site y en subrecursos, pero **la
manda en una navegación top-level GET**. Un sitio hostil que lleve a la víctima a
`https://<app>/api/iol/lab/status` dispara esa escritura con su sesión. El impacto es acotado
(renueva su propio token, y hay que estar en la allowlist de IOL Lab), pero es real y gratis.
Los tres crons (H-2) son el mismo problema con impacto mucho mayor: `GET` + escritura global.

**Otros call sites del mismo patrón:** grepeé `INSERT|UPDATE|DELETE|commit` en `reporting/*.py`
→ **cero**: los dos endpoints de `/api/reports/*` de este tramo son genuinamente read-only.
`/api/imports`, `/api/sections/archived`, `/api/watchlist`, `/api/alerts` y `/api/home/*` GET
tampoco escriben. Los únicos GET-que-escriben del tramo son los cinco listados (2 + los 3 crons).

**Solución de fondo:** dejar de derivar el permiso del verbo. El verbo es una convención, no una
garantía. Lo correcto es que la **intención** sea explícita: marcar los endpoints que escriben
(una dependencia `Depends(requiere_escritura)` o un decorador) y que `_resolve_client_context`
exija `read_write` según esa marca, no según `request.method`. Como red de contención, un test
que recorra `app.routes` y falle si un `GET` está marcado como escritor sin declararlo.

---

### [MEDIO] H-6 · El `UPDATE` de `PATCH /api/alerts/{id}` no lleva `user_id`

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:33524-33527` (el `SELECT` que hoy lo salva) y `main.py:33557` (el `UPDATE`).

**Qué pasa:**

```python
row = conn.execute("SELECT * FROM alerts WHERE id=? AND user_id=?", (alert_id, uid)).fetchone()
if not row:
    raise HTTPException(404, "Alerta no encontrada.")
...
params.append(alert_id)
conn.execute(f"UPDATE alerts SET {', '.join(sets)} WHERE id=?", params)   # ← 33557
```

**Hoy no es explotable**: el `SELECT` de arriba corta con 404 y `alert_id` es la misma variable
en las dos consultas. Lo reporto igual, y no como higiene, porque es **la misma forma** del
bug ALTO H-1: la seguridad depende de que dos sentencias separadas por 30 líneas se mantengan
en el orden correcto para siempre. En H-1 esa distancia ya se cobró la pieza — ahí directamente
no hay `SELECT` previo. Y el contraejemplo correcto está en el mismo archivo, 220 líneas más
abajo: `advisor_groups_update` (`main.py:33797-33799`) valida con `get_group(conn, uid, gid)`
**y además** cierra el `UPDATE` con `WHERE id=? AND advisor_uid=?`. Cinturón y tiradores.

**Qué queda expuesto:** nada hoy. Es la deuda que produce el hallazgo de al lado.

**Otros call sites del mismo patrón (barrido completo del tramo):** las tres escrituras por id
sin filtro de dueño son `main.py:33557` (esta), `main.py:33572` (H-1, la rota) y
`main.py:31406` (`UPDATE iol_lab_runs … WHERE id=?`, con un `run_id` que el propio proceso
acaba de insertar — inalcanzable desde afuera). No hay más.

**Solución de fondo:** agregar `AND user_id=?` al `UPDATE` y chequear `rowcount` en vez de
confiar en el `SELECT` previo — la regla es que **la sentencia que escribe lleve el filtro del
dueño**, siempre, aunque parezca redundante. La redundancia es el punto: sobrevive a la
refactorización que mueve el `SELECT`.

---

### [BAJO] H-7 · Lecturas por id que no repiten el filtro de dueño

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:30957`, `main.py:31646-31649`, `main.py:31406`.

**Qué pasa:** tres consultas leen por id sin `user_id`:

- `main.py:30957` (final de `import_confirm`): `SELECT broker, fund_price_overrides FROM
  import_batches WHERE id=?`. Alcanzable sólo después de que `load_session_*_revalidate` validó
  el mismo `session_id` contra `user_id` y de que el batch se persistió; y el `UPDATE positions`
  que sigue sí filtra `WHERE user_id=?`, así que ni siquiera un batch ajeno escribiría fuera.
- `main.py:31646` (`import_detail`): las `import_raw_rows` se traen por `batch_id` solo, después
  del `SELECT … WHERE id=? AND user_id=?` que ya devolvió 404.
- `main.py:31406` (`_iol_lab_run_bg`): `UPDATE iol_lab_runs … WHERE id=?` con un `run_id`
  generado en el mismo request.

**Qué queda expuesto:** nada alcanzable hoy. Se listan porque son las candidatas naturales a
convertirse en el próximo H-1 si alguien mueve la validación.

**Solución de fondo:** misma regla que H-6 — filtro del dueño en la sentencia, no en el orden.

---

### [BAJO] H-8 · `POST /api/sections/restore` arma el `INSERT` interpolando nombres de columna

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:31866-31875`.

```python
items = _json.loads(row["payload"]) or []
for it in items:
    cols = [k for k in it.keys()]
    ph = ",".join("?" * len(cols))
    conn.execute(f"INSERT INTO positions ({','.join(cols)}) VALUES ({ph})", tuple(it[c] for c in cols))
```

Los **valores** van parametrizados; los **nombres de columna** salen de las claves de un JSON e
se interpolan crudos. **No es explotable hoy**: verifiqué por grep que el único escritor de
`archived_positions.payload` es `sections_archive` (`main.py:31835`), que serializa
`dict(r)` de filas de `positions` — o sea, las claves son siempre el esquema real de la tabla,
nunca texto del usuario. Y la fila se lee con `WHERE id=? AND user_id=?`.

Lo reporto como BAJO porque el aislamiento depende de que **nadie más escriba jamás en esa
columna**. Un import, una restauración de backup o un backfill que meta un `payload` con otra
forma convierte esto en inyección directa.

**Solución de fondo:** validar `cols` contra una allowlist derivada de `PRAGMA table_info
(positions)` antes de interpolar, y descartar la fila si aparece una columna desconocida.

---

### [BAJO] H-9 · `POST /api/imports/wipe-broker` recibe el broker por query string

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:31740-31741` (`def import_wipe_broker(broker: str, uid=…)` — sin `Body`,
FastAPI lo lee de la query).

La autorización está bien (`brokers WHERE user_id=? AND name=?` → 404, y `_wipe_broker_data`
está scopeado al uid; verificado en `main.py:31000`+). Lo que queda mal es que el nombre del
broker del usuario —dato personal— viaje en la URL de una operación **destructiva**, y por lo
tanto quede en los access logs del proxy y en el `Referer`. Mismo defecto de canal que el
`?token=` de H-2, con datos en vez de secretos.

**Solución de fondo:** pasar `broker` en el body (un `BaseModel`, como hace el resto del tramo:
`SectionKeyIn`, `WatchlistAddIn`, `ImportMappingIn`).

---

### [BAJO] H-10 · `/api/iol/lab/status` distingue "no configurado" de "no estás habilitado"

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:31466-31468`, con los mensajes en `_iol_lab_gate` (`main.py:31626-31632`).

El endpoint atrapa la `HTTPException` del gate y devuelve `{"enabled": False, "reason": e.detail}`.
Los dos `detail` posibles son distinguibles: `"IOL Lab no está habilitado."` (503 — la variable
`IOL_LAB_EMAILS` está vacía) vs `"Tu cuenta no está habilitada para esta prueba."` (403 — la
variable está poblada y tu email no está). Cualquier usuario logueado puede leer, gratis, si la
allowlist está configurada o no.

**Lo bueno, que también hay que decirlo:** el gate en sí **falla cerrado** y es sólido
(`main.py:31626-31632`): sin `IOL_LAB_EMAILS` **nadie** que no sea admin entra (503, no un
"allowlist vacía = pasan todos"), la comparación es sobre el email de la fila de `users` leída
por id (no sobre nada que mande el cliente), y se normaliza con `.strip().lower()` de los dos
lados. Es el endurecimiento correcto; el único reparo es el mensaje de error.

**Solución de fondo:** un solo `reason` genérico hacia afuera, con el detalle en el log.

---

## Lo que NO pude verificar (dicho explícitamente)

1. **No medí nada.** No levanté el backend, no corrí ningún test, no emití requests. Los diez
   hallazgos son ESTRUCTURAL o DEDUCIDO, y están marcados uno por uno.
2. **No verifiqué la longitud ni la entropía de los tokens de cron** (`SNAPSHOT_CRON_TOKEN`,
   `ALERTS_CRON_TOKEN`, `IOL_LAB_CRON_TOKEN`, `ADVISOR_BRIEF_TOKEN`) — son variables de entorno
   de Railway y no consulté esa configuración. Por eso en H-2 el vector que sostengo es la
   **fuga por el canal** (logs / `Referer`), no la fuerza bruta: sin conocer la longitud, afirmar
   que se rompe por fuerza bruta sería un medido falso.
3. **No verifiqué si `IOL_LAB_EMAILS` está seteada en producción.** Memoria del proyecto sugiere
   que no (lo que dejaría IOL Lab en 503 para todo el mundo salvo admins), pero no lo confirmé
   contra Railway. Auditá H-10 y el punto 7 de la tabla asumiendo que **puede** estar seteada.
4. **No verifiqué cuántos vínculos `advisor_clients` tienen `permission='read_write'`** ni si el
   frontend expone hoy la pantalla de Wallbit bajo contexto de cliente. H-4 describe lo que el
   **backend permite**; su explotabilidad práctica depende de datos de producción que no consulté.
   La API es alcanzable con `curl` aunque la UI no muestre el botón.
5. **No audité el motor del cron por dentro** (`alerts_engine.evaluate_alerts`,
   `snapshots_job`, `advisor_brief.run_briefs`, `advisor_alerts.evaluate`): sólo la puerta de
   entrada. Si dentro de esos motores hay una consulta sin `user_id`, no es un hallazgo mío.
   **⚠️ posible cruce con F1** en `snapshots_job.py`.
6. **No revisé el CSRF a nivel app** (ausencia de token, `samesite=lax`, `ALLOWED_ORIGINS`):
   lo cito en H-5 sólo donde toca un GET-que-escribe de mi tramo. Es materia de otro tramo.
7. **No re-verifiqué el Paso 0.** H-3 se apoya en `5a-paso0-secret-key.md` tal como está escrito.
8. **No audité las migraciones de arranque** que caen dentro de mi rango de líneas pero no son
   endpoints (`_remap_fci_broker_tickers` en `main.py:32410-32417`, con un
   `UPDATE {tbl} SET {col}=? WHERE {col}=?` **global a todos los usuarios**, y
   `_repair_fx_gross_usd` en `main.py:32462`). Corren en el boot, no por request, así que no son
   superficie de autorización — pero **son escritores globales sin filtro de usuario** y alguien
   debería mirarlos en el tramo de integridad de datos.
