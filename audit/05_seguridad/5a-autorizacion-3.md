# 5a · Autorización entre usuarios — tramo 3 de 6 (líneas 15040–19696, 43 endpoints)

Copia auditada: `/tmp/rendi-main` (commit `b74f450f`, prod al 2026-09-05).
`backend/main.py` = 38.029 líneas (verificado). **No se tocó producción ni el working tree.**

## Método

Qué ejecuté:

1. **Escáner estático propio**, guardado en `audit/_scripts/5a_autorizacion_3_scan.py`. Parsea
   `main.py` con regex, y por cada `@app.<verbo>("<ruta>")` resuelve la línea `def`, el final
   real del cuerpo (primera línea a columna 0 que abre otro constructo) y busca dentro de ese
   cuerpo `INSERT `, `UPDATE `, `DELETE FROM`, `commit()`. Salida completa reproducible con
   `python3 audit/_scripts/5a_autorizacion_3_scan.py`.
   - Resultado: **43 endpoints exactos** en el tramo (coincide con el inventario).
   - **47/47 rutas `/api/admin` dependen de `get_admin_user`. Cero excepciones.** (MEDIDO)
2. Lectura manual del cuerpo de los 43 (los 7 no-admin enteros; los 36 admin, docstring +
   queries + escrituras).
3. Verificación cruzada de la cadena de confianza que sostiene el tramo: `get_admin_user`
   (2719-2725) → `is_admin` → `_is_admin_email` (131-134) → `POST /api/auth/register` (3094) →
   `RegisterIn.email_valid` (2866-2872) → `email TEXT UNIQUE` (713).
4. Grep de duplicados de ruta en todo el archivo (`0 duplicados`) — descarta que una ruta admin
   quede sombreada por otra registrada antes.
5. Grep de `_check_rate_limit` en todo el archivo para ver cuáles de mis 43 lo tienen.

Qué **no** ejecuté: ningún request contra la app desplegada, ningún ataque, ningún test dinámico.
No levanté el backend. Todo lo marcado DEDUCIDO/ESTRUCTURAL sale de leer el código congelado.

Supuestos declarados:
- El escáner asume que todo endpoint se declara con `@app.<verbo>("<literal>")`. Un `add_api_route`
  dinámico o un `APIRouter` incluido aparte se le escaparía — grepeé `add_api_route` e `include_router`
  y no hay ninguno que agregue rutas `/api/admin`.
- Para las tres preguntas del tramo sobre `get_effective_user` me apoyo en el contrato documentado
  en 2729-2800 (leído entero) y no en el mapa del sistema.

## Resumen — hallazgos por severidad

| id | severidad | título | archivo:línea | evidencia |
|---|---|---|---|---|
| H-1 | MEDIO | El undo por token escribe 3 veces sin filtrar por usuario | `main.py:15092,15120,15123` | ESTRUCTURAL |
| H-2 | MEDIO | `POST /api/goals` no tiene tope ni rate limit: filas ilimitadas por usuario | `main.py:15171-15188` | ESTRUCTURAL |
| H-3 | BAJO | Clon completo de la base en `/tmp`: 2 de 3 call sites no borran los sidecars WAL/SHM | `main.py:16992,17307` vs `15750` | ESTRUCTURAL |
| H-4 | BAJO | SQL armado con f-string sobre un parámetro de query (`days`) | `main.py:18735,18745,18759` | ESTRUCTURAL |
| H-5 | BAJO | El detalle crudo de la excepción vuelve al cliente en 4 endpoints admin | `main.py:16956,16993,17305,17356` | ESTRUCTURAL |
| V-1 | (verificado NEGATIVO) | Escalada a admin por variante de mayúsculas del email — **cerrada** | `main.py:2869` | DEDUCIDO |
| V-2 | (verificado NEGATIVO) | `/api/admin` exento del header `X-Rendi-Client-Id` — **doble cierre correcto** | `main.py:2752`, `2719` | MEDIDO |

**Ningún CRÍTICO ni ALTO en este tramo.** Los 43 endpoints validan sesión, los 36 admin validan rol,
y ninguno acepta un id de recurso ajeno sin gate. El tramo es, con diferencia, el más sólido de la
superficie que vi.

---

## Tabla — los 43 endpoints

| # | línea | método | ruta | qué hace | valida sesión | valida propiedad | veredicto |
|---|---|---|---|---|---|---|---|
| 1 | 15040 | POST | `/api/assets/undo/{token}` | Deshace el borrado del historial de un activo: restaura filas, devuelve cash, re-deriva pares | `get_effective_user` | **Sí** — `SELECT … FROM deleted_ops_journal WHERE user_id=? AND token=?` (15047). Token = `secrets.token_hex(8)` (15001), 64 bits, y además atado al uid: no cruza cuentas | MEDIO: 3 escrituras posteriores sin filtro de usuario (H-1) |
| 2 | 15162 | GET | `/api/goals` | Lista los objetivos | `get_effective_user` | n/a (no recibe id) — la query filtra `WHERE user_id=?` (15166) | OK |
| 3 | 15171 | POST | `/api/goals` | Crea un objetivo | `get_effective_user` | n/a (crea) — `INSERT … (user_id, …)` con el uid de sesión (15177) | MEDIO: sin tope de filas ni rate limit (H-2) |
| 4 | 15189 | PUT | `/api/goals/{gid}` | Edita un objetivo | `get_effective_user` | **Sí** — `UPDATE goals … WHERE id=? AND user_id=?` (15195) y re-`SELECT` con el mismo par (15199) → 404 si no es tuyo | OK |
| 5 | 15209 | DELETE | `/api/goals/{gid}` | Borra un objetivo | `get_effective_user` | **Sí** — `DELETE FROM goals WHERE id=? AND user_id=?` (15214) | OK |
| 6 | 15223 | GET | `/api/goals/{gid}/diagnostic` | Cruza velocidad real vs. necesaria + sesgo conductual | `get_effective_user` | **Sí** — goal (15239), positions (15245) y operations (15250) los tres con `WHERE user_id=?` | OK |
| 7 | 15394 | GET | `/api/goals/cagr` | Rendimiento histórico del motor canónico (`twr.curva_indexada`) | `get_effective_user` | n/a — delega en `_historical_cagr_global(conn, uid, …)` (15404), que propaga el uid | OK |
| 8 | 15598 | POST | `/api/admin/recompute-snapshots-netdep` | Re-corre el backfill netdep del admin logueado + borra snapshots V-shape | `get_admin_user` | n/a — opera sobre `uid` (el propio admin), no acepta target | OK |
| 9 | 15759 | POST | `/api/admin/repair-user-history` | Repara los snapshots contaminados de UN usuario (por email) | `get_admin_user` | n/a — resuelve el target por email (15776); opera sobre terceros **a propósito**, gate = admin | OK |
| 10 | 15792 | POST | `/api/admin/repair-snapshots-all` | Repara los snapshots de TODOS, en tandas; `apply=false` ⇒ dry-run sobre clon | `get_admin_user` | n/a — barrido global deliberado | OK |
| 11 | 15818 | POST | `/api/admin/backfill-recompute` | Recomputa posiciones de todos (FIFO + amortización) sin re-importar | `get_admin_user` | n/a — barrido global deliberado | OK |
| 12 | 15889 | POST | `/api/admin/backfill-mtm` | Valuación histórica a mercado de meses cerrados | `get_admin_user` | n/a — barrido global deliberado | OK |
| 13 | 15933 | POST | `/api/admin/backfill-currency` | Corrige filas ARS mal-etiquetadas USD en cuentas con capital negativo | `get_admin_user` | n/a — barrido con gate `min_capital` | OK |
| 14 | 15980 | GET | `/api/admin/diag/client-ip` | Cómo llega `X-Forwarded-For` y qué IP se deduce | `get_admin_user` | n/a (no toca DB) | OK — expone `RENDI_TRUSTED_PROXY_HOPS` y `RENDI_ENV`, no secretos |
| 15 | 16007 | GET | `/api/admin/diagnose-negative-capital` | Cuentas con `capital_final` negativo gigante y qué broker lo causa | `get_admin_user` | n/a — lee de todos los usuarios, es el punto del endpoint | OK (read-only verificado: 0 escrituras en el cuerpo) |
| 16 | 16157 | GET | `/api/admin/diagnose-sell-fx` | Con qué TC se dolarizaron ventas y flujos (estimador `T_rec`) | `get_admin_user` | n/a | OK — read-only: los 1 `UPDATE` del rango es texto de un comentario (16545), no SQL |
| 17 | 16566 | GET | `/api/admin/diagnose-scale` | Error de escala per-100 en las ventas | `get_admin_user` | n/a | OK — read-only: los 2 `UPDATE` son texto (16764, 16856) |
| 18 | 16888 | POST | `/api/admin/fx-migrate-user` | Migra UNA cuenta de FX v1→v2; `apply=false` ⇒ clon | `get_admin_user` | n/a — `user_id` por query, verifica existencia (16947) pero opera sobre terceros por diseño | OK · BAJO por H-3 y H-5 |
| 19 | 16995 | GET | `/api/admin/fx-migrate-candidates` | Lista todas las cuentas con versión FX y si están bloqueadas | `get_admin_user` | n/a — 6 queries agregadas sobre toda la base | OK |
| 20 | 17086 | GET | `/api/admin/fx-aportado-breakdown` | Abre el aportado de una cuenta por año y dirección | `get_admin_user` | n/a — `user_id` por query, read-only | OK |
| 21 | 17238 | POST | `/api/admin/fx-migrate-batch` | Dry-run de la migración FX de muchas cuentas sobre UNA copia | `get_admin_user` | n/a — `body.user_ids`, siempre `applied:false` | OK · BAJO por H-3 y H-5 |
| 22 | 17314 | POST | `/api/admin/cleanup-future-snapshots` | Borra los snapshots con fecha futura de todas las cuentas | `get_admin_user` | n/a — `DELETE FROM snapshots WHERE date > ?` global, gateado por `apply=true` | OK · BAJO por H-5 |
| 23 | 17362 | GET | `/api/admin/ventas-legacy-debug` | Qué pasaría si dedujéramos la moneda de las ventas viejas | `get_admin_user` | n/a — target por `?email=` o `?user_id=`; 400 si no viene ninguno | OK (read-only) |
| 24 | 17504 | GET | `/api/admin/commissions-debug` | Desglose de fees por batch de un usuario | `get_admin_user` | n/a — mismo patrón email/user_id | OK (read-only) |
| 25 | 17600 | GET | `/api/admin/pg-type-audit` | Qué filas rechazaría Postgres | `get_admin_user` | n/a — muestreo global | OK |
| 26 | 17637 | POST | `/api/admin/repair-comisiones` | Pone en cero las comisiones implausibles ya escritas en `positions` | `get_admin_user` | n/a — barrido global, dry-run por defecto, reversible vía `undo_meta_json` | OK |
| 27 | 17771 | GET | `/api/admin/check-invariantes` | Chequeador de invariantes (una cuenta o toda la base) | `get_admin_user` | n/a — `user_id` opcional; sin él barre todo | OK (read-only) |
| 28 | 17803 | GET | `/api/admin/diagnose-reportes-basis` | Blast radius del guard AUDIT D-1 + origen del `start_value` | `get_admin_user` | n/a | OK (read-only) |
| 29 | 18115 | GET | `/api/admin/diagnose-flujo-implausible` | Rastrea flujos de caja absurdos hasta la fila del archivo | `get_admin_user` | n/a | OK (read-only) |
| 30 | 18375 | GET | `/api/admin/diagnose-costo-inconsistente` | Posiciones donde `buy_price×qty ≠ invested` | `get_admin_user` | n/a | OK (read-only) |
| 31 | 18485 | GET | `/api/admin/disk-usage` | Uso de disco + archivos más grandes + internals de SQLite | `get_admin_user` | n/a — **ninguna ruta viene del cliente**: `_db_dir_of`, `gettempdir`, `cwd`, `BACKUP_LOCAL_DIR` | OK |
| 32 | 18590 | POST | `/api/admin/delete-snapshot` | Borra un snapshot por fecha | `get_admin_user` | **Sí** — `DELETE FROM snapshots WHERE user_id=? AND date=?` con el uid del admin (18618); `date` validado con regex `^\d{4}-\d{2}-\d{2}$` (18604) | OK |
| 33 | 18631 | POST | `/api/admin/backup-trigger` | Dispara el backup diario a mano | `get_admin_user` | n/a | OK |
| 34 | 18647 | GET | `/api/admin/stats` | Top-line + embudo de activación | `get_admin_user` | n/a — agregados, sin PII fila a fila | OK |
| 35 | 18718 | GET | `/api/admin/ai/tool-usage` | Ranking de tools del Coach IA + top 10 usuarios con email | `get_admin_user` | n/a | BAJO: f-string en el SQL (H-4) |
| 36 | 18775 | GET | `/api/admin/plan/conversion` | Métricas de conversión free→pro desde `plan_events` | `get_admin_user` | n/a — agregados | OK |
| 37 | 18918 | GET | `/api/admin/users` | Lista COMPLETA de usuarios (email, nombre, tier, crédito, contadores) | `get_admin_user` | n/a — sin `LIMIT`, es la lista del panel; **no devuelve `password_hash`** (verificado en `_ADMIN_USERS_SELECT`, 18861-18872) | OK |
| 38 | 18937 | GET | `/api/admin/users/search` | Busca por id exacto / substring de email o nombre | `get_admin_user` | n/a — comodines de `LIKE` escapados con `ESCAPE '\'` (18973), `limit` acotado 1..100, mínimo 2 chars | OK |
| 39 | 19011 | POST | `/api/admin/email/re-engagement` | Mail a usuarios con poca actividad; stampea `reengagement_email_sent_at` | `get_admin_user` | n/a — `confirm=false` ⇒ dry-run; excluye admins y shadows (`managed_by IS NULL`) | OK |
| 40 | 19123 | POST | `/api/admin/email/gift-plan` | Mail de regalo de plan; excluye a los que están en trial | `get_admin_user` | n/a — mismo patrón dry-run | OK |
| 41 | 19296 | POST | `/api/admin/email/trial-invite` | Invitación al trial usando `trial.eligibility()` | `get_admin_user` | n/a — stampea antes de enviar y **desmarca si falla** (19391) | OK |
| 42 | 19413 | POST | `/api/admin/email/broadcast` | Mail custom a un segmento; `test_to` / dry-run / idempotencia por `content_hash` | `get_admin_user` | n/a — el cuerpo lo escribe el admin; sin tope de destinatarios salvo `limit` | OK |
| 43 | 19551 | GET | `/api/admin/billing/inspect` | Estado de billing de un usuario por email + diagnóstico del cron | `get_admin_user` | n/a — `?email=`; devuelve columnas de tier/crédito **sin `password_hash`** (19577-19587) | OK |

Sobre las celdas `n/a` en "valida propiedad": los 36 endpoints admin **operan sobre cuentas ajenas
a propósito** — reparar, migrar y diagnosticar cuentas de terceros es su razón de existir. Ahí la
propiedad del recurso no aplica; lo que aplica es el gate de rol, y los 36 lo tienen. Los que no
reciben ningún id (barridos globales, agregados, `disk-usage`, `backup-trigger`, `client-ip`)
también van `n/a` porque no hay recurso individual que verificar.

---

## Respuestas a las cinco preguntas del encargo

**1 · ¿Valida sesión?** Los 43. Ninguno es público. 7 usan `get_effective_user`, 36 usan
`get_admin_user`. **Ningún endpoint del tramo carece de dependencia de auth** (MEDIDO por el
escáner: el listado global de rutas sin auth no contiene ninguna del rango 15040-19696).

**2 · ¿Valida propiedad, o solo que estés logueado?** Los 6 endpoints del tramo que reciben un id
de recurso propio (`/api/goals/{gid}` ×3, `/api/goals/{gid}/diagnostic`, `/api/assets/undo/{token}`,
`/api/admin/delete-snapshot`) **filtran los seis por `user_id` en la misma query**. No hay un solo
`WHERE id=?` pelado en la lectura o en el borrado del recurso. El único resto es H-1: escrituras
*secundarias* del undo que se apoyan en ids ya validados en vez de re-validarlos.

Sobre el token de undo (pregunta explícita del encargo): `secrets.token_hex(8)` = 64 bits (15001).
No es adivinable por fuerza bruta en la práctica, y **aunque lo fuera no serviría**: el `SELECT`
exige `user_id=? AND token=?`, así que un token de otro usuario devuelve 404 aunque lo adivines.
El claim del undo es atómico (`UPDATE … WHERE id=? AND undone_at IS NULL` con chequeo de `rowcount`,
15087-15090), lo que cierra el doble-undo → doble-crédito de cash. Está bien hecho.

**3 · ¿Toda query filtra por el usuario dueño?** En los 7 no-admin, sí, con la excepción de H-1.
En los 36 admin no corresponde: barren la base por diseño.

**4 · `X-Rendi-Client-Id`.** `/api/admin` **está** en `CLIENT_CTX_EXEMPT_PREFIXES` (`main.py:2752`)
y el match es por límite de segmento (2778), así que exime `/api/admin` y `/api/admin/...`
sin eximir un futuro `/api/administracion`. Pero hay algo mejor: **el prefijo es redundante acá**.
`get_admin_user` depende de `get_current_user`, no de `get_effective_user` — nunca lee el header,
exista el prefijo o no. Doble cierre: para llegar a un endpoint admin con contexto de cliente
habría que cambiar las dos cosas a la vez.

Lo que el prefijo **no** cubre en mi tramo, y es correcto que no cubra: `/api/assets/undo/{token}`
y los 6 de `/api/goals` usan `get_effective_user`, así que **un asesor con `permission='read_write'`
puede deshacer el borrado de un activo de su cliente y crear/editar/borrar sus objetivos**. Leí el
contrato (2729-2760) y es deliberado: son endpoints de DATOS, y el gate de escritura del vínculo
(2790-2791) rechaza los `linked` de solo lectura. **No es un hallazgo**, es la funcionalidad. Lo
anoto porque es la única superficie del tramo donde un usuario escribe legítimamente en la cuenta
de otro, y cualquier bug futuro en `advisor_clients` sale por acá.

**5 · Escrituras por GET.** **Ninguna.** Los 3 GET que mi primer escaneo marcó con `UPDATE` eran
falsos positivos: en `diagnose-sell-fx` (16545) y `diagnose-scale` (16764, 16856) la palabra
"UPDATE" está dentro de un comentario y de un string de nota al operador, no en SQL. Los verifiqué
uno por uno. En `/api/goals/cagr` el `UPDATE`/`DELETE` que aparecía era de dos funciones auxiliares
(`_detect_and_remove_corrupt_snapshots`, `_recompute_snapshots_netdep_for_user`) que viven **entre**
dos decoradores y que el endpoint no llama. Los 15 GET admin son read-only de verdad.

Relacionado: la cookie de sesión es `SameSite=lax` (`main.py:158`), así que un POST cross-site no
la manda. Combinado con "cero GET que escriben", el tramo no tiene superficie CSRF.

---

## Hallazgos

### [MEDIO] H-1 · El undo por token hace tres escrituras sin filtrar por usuario

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:15092`, `main.py:15120`, `main.py:15123`

**Qué pasa.** El endpoint abre bien: lee el journal con `WHERE user_id=? AND token=?` (15047).
Pero después toma ids **del payload JSON** y los usa a pelo:

```
15092:  UPDATE import_normalized_tx SET excluded_at=NULL, excluded_by=NULL WHERE id=?
15120:  INSERT INTO import_op_links (batch_id, raw_row_id, operation_id) VALUES (?,?,?)
15123:  UPDATE import_normalized_tx SET created_operation_id=? WHERE batch_id=? AND raw_row_id=?
```

Ninguna de las tres tiene `AND user_id=?` ni un `JOIN import_batches b ON b.user_id=?`.
Contrastá con el `INSERT INTO operations` de tres líneas más arriba (15108-15116), que **sí**
estampa `uid`, y con el `DELETE FROM operations WHERE id=? AND user_id=?` del path de borrado
(14990). La asimetría dentro del mismo bloque es la señal.

**Cómo se explota en la práctica.** Hoy, **no se explota**. El `payload_json` no lo controla el
atacante: lo escribe el path de borrado (15000-15011) con ids que salieron de queries scopeadas
por `b.user_id=?`, y el journal se lee filtrado por `user_id`. Para llegar a una escritura
cross-user harían falta dos cosas a la vez: (a) que algún path escriba un payload con un id
ajeno, o (b) que un id de `import_normalized_tx` se reutilice entre cuentas (un restore desde
backup, una migración a Postgres que renumere, el `AUTOINCREMENT` reseteado). Es una bomba con el
pin puesto, no una puerta abierta.

**Qué queda expuesto si el pin se cae.** Reactivación de filas de import (`excluded_at=NULL`) y
re-linkeo de operaciones **en la cuenta de otro usuario**: le reaparecen operaciones borradas y su
cartera cambia sin que él haga nada. No es fuga de datos, es corrupción de datos ajenos.

**Otros call sites del mismo patrón** (grep `UPDATE import_normalized_tx SET excluded_at=NULL`):
- `main.py:14797` — `/api/operations/undo/{token}` (tramo 2). Mismo patrón, **un poco mejor**:
  agrega `AND batch_id=?`, que estrecha pero tampoco prueba pertenencia (un batch_id ajeno pasa).
- `main.py:15092` — este endpoint. `WHERE id=?` pelado, sin ni siquiera el `batch_id`.
- `main.py:15120`, `15123` — mismo endpoint, `import_op_links` / `created_operation_id`.
- `main.py:8512` `/api/positions/group/undo/{token}` delega en `_undo_edit_position_group(conn, uid, token)`,
  que sí recibe el uid — no comparte el patrón.

O sea: 4 escrituras en 2 endpoints, con **tres grados distintos de scoping para la misma
operación**. Es exactamente la firma de la regla de propagación del repo.

**Solución de fondo.** Un único helper `_reactivar_tx(conn, uid, tx_ids)` que haga
`UPDATE import_normalized_tx SET excluded_at=NULL WHERE id IN (…) AND batch_id IN (SELECT id FROM
import_batches WHERE user_id=?)`, y que los dos endpoints de undo lo llamen. No agregar el
`AND user_id` cuatro veces a mano: eso es lo que produjo los tres grados distintos.

---

### [MEDIO] H-2 · `POST /api/goals` no tiene tope de filas ni rate limit

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:15171-15188`

**Qué pasa.** El endpoint inserta en `goals` sin consultar cuántos objetivos tiene ya el usuario.
Grep `COUNT(*) FROM goals` → **cero coincidencias en todo `main.py`**. Y grep de `_check_rate_limit`
sobre todo el archivo: aparece en 29 sitios, **ninguno en el rango 15040-19696**. Los 43 endpoints
de este tramo, incluido este, no tienen rate limit.

**Cómo se explota en la práctica.** Cualquier usuario autenticado (incluida una cuenta free recién
verificada) hace `POST /api/goals` en bucle. Cada fila lleva `label` de hasta `MAX_STR`. No hay
nada que lo frene salvo el ancho de banda.

**Qué queda expuesto.** Disco. Y el disco de esta app **ya se llenó**: el docstring de
`/api/admin/disk-usage` (18488-18490) dice literalmente que los backfills tiraban
`OperationalError: database or disk is full`. Con SQLite en un volumen de Railway, llenar el disco
no degrada: **detiene toda escritura para todos los usuarios**. Un DoS al alcance de cualquiera
con una cuenta gratis. Además contamina `/api/goals` y `goal_diagnostic` del propio usuario, que
no paginan.

**Otros call sites del mismo patrón** — endpoints de creación sin tope ni rate limit que encontré
al grepear (los de fuera de mi tramo quedan para quien los audite, los listo por la regla de
propagación): `POST /api/goals` (15171) es el de mi tramo. Los de IA sí tienen rate limit
(`ai_remember` 29318, `ai_chat` 28295, `ai_analyze` 25913), y billing también — o sea que el
patrón "rate-limitear lo que crea filas" **existe en el repo y no se propagó a goals**.

**Solución de fondo.** Un tope por usuario en el propio `INSERT` (los objetivos de una persona son
unidades, no miles) más `_check_rate_limit(request, max_calls=…, suffix=f"goal_create:{uid}")`,
igual que ya se hace en IA. El tope importa más que el rate limit: un rate limit generoso sigue
permitiendo llenar el disco despacio.

---

### [BAJO] H-3 · Clon completo de la base en `/tmp`: 2 de 3 call sites no borran los sidecars

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:16992-16994` y `main.py:17307-17311`, contra `main.py:15750-15752`

**Qué pasa.** Tres endpoints admin hacen un dry-run copiando **la base entera** (todas las
carteras de todos los usuarios) a un archivo temporal con `sqlite3.Connection.backup()`. Al
terminar, la limpieza difiere:

- `_repair_snapshots_summary` (15750-15752), que sirve a `/api/admin/repair-snapshots-all`:
  borra `tmp.name`, `tmp.name + "-wal"` **y** `tmp.name + "-shm"`. **Correcto.**
- `/api/admin/fx-migrate-user` (16992-16994): borra **solo** `tmp.name`.
- `/api/admin/fx-migrate-batch` (17307-17311): borra **solo** `tmp.name`.

**Cómo se explota en la práctica.** No se explota remotamente: hace falta acceso al filesystem del
contenedor. En el camino feliz los sidecars tampoco quedan (cerrar la conexión limpia hace
checkpoint y los borra). El problema es el camino infeliz: si el proceso muere entre el `backup()`
y el `os.unlink` — OOM clonando una base grande, redeploy de Railway, timeout del gateway —
**queda en `/tmp` una copia íntegra de la base de producción**, y en los dos sitios sin limpieza de
sidecars puede quedar además un `-wal` con frames de datos reales.

**Qué queda expuesto.** Tenencias, operaciones y patrimonio de todos los usuarios, en claro, en
disco. Nada que un atacante alcance por HTTP; todo lo que alcanza cualquiera que llegue al
filesystem (otro proceso del contenedor, un volumen mal montado, un snapshot de infra).

**Otros call sites del mismo patrón:** los tres de arriba son todos los `NamedTemporaryFile` +
`.backup()` de `main.py` fuera de tests (grep: 15743, 16928, 17257; más `sim_import.py:14` y
`main.py:5326`, que es un `mkdtemp` de cache de yfinance, no la base). O sea **1 de 3 hace la
limpieza completa** — el fix existe y no se propagó.

**Solución de fondo.** Un context manager `clon_efimero(conn)` que haga el backup, ceda la
conexión y en el `finally` borre los tres archivos. Los tres endpoints lo usan. Bonus: clonar bajo
`0700` en un `mkdtemp` propio en vez de en el `/tmp` compartido.

---

### [BAJO] H-4 · SQL armado con f-string sobre un parámetro de query

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:18735`, `18745`, `18759` (`/api/admin/ai/tool-usage`)

**Qué pasa.** Tres queries interpolan `days` directamente: `date('now', '-{days} days')`.

**Cómo se explota en la práctica.** **No se explota.** `days: int = 14` lo castea FastAPI (un
`?days=1 OR 1=1` da 422 antes de llegar al handler) y encima 18728 hace
`days = max(1, min(int(days or 14), 90))`. La defensa es real y doble.

**Qué queda expuesto.** Nada hoy. Lo reporto por la regla de propagación: es el patrón "concatenar
en vez de bindear" en un archivo de 38.000 líneas, y el día que alguien copie estas tres líneas
para un filtro de tipo `str` (un `tool_name`, un `email`) la inyección es directa. En
`/api/admin/stats` (18656-18670) también hay f-strings de SQL, pero ahí lo interpolado son
constantes literales definidas dos líneas arriba (`NOTEST`, `REAL`): eso es composición de SQL
estático, no es lo mismo, y no lo cuento como hallazgo.

**Solución de fondo.** `date('now', ?)` con `(f"-{days} days",)` como bind. Tres líneas.

---

### [BAJO] H-5 · El detalle crudo de la excepción vuelve al cliente

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:16956`, `16993`, `17305`, `17356`

**Qué pasa.** Cuatro endpoints admin devuelven `HTTPException(500, detail=f"… {type(e).__name__}: {e}")`.
El mensaje de una excepción de SQLite o del sistema de archivos suele traer rutas absolutas,
nombres de tabla y de columna, y a veces valores de la fila que falló.

**Cómo se explota en la práctica.** Requiere ser admin, así que el destinatario ya tiene acceso a
todo. Es defensa en profundidad: si un día un endpoint con este patrón queda mal gateado, el 500
se vuelve un oráculo de la estructura interna. Contrastá con el patrón bueno del mismo tramo:
`/api/assets/undo/{token}` (15137-15141) loguea el detalle y devuelve `"No se pudo deshacer"` — el
error completo queda en el log del servidor, que es donde sirve.

**Solución de fondo.** El patrón de 15141 aplicado a los cuatro: `log.exception(...)` + mensaje
genérico al cliente.

---

## Verificados en NEGATIVO (busqué el agujero y no está)

Los anoto porque un "no está" verificado ahorra que el próximo auditor repita el camino.

### V-1 · Escalada a admin registrando una variante del email del admin — **cerrada**

Toda la seguridad de los 36 endpoints admin de mi tramo cuelga de `get_admin_user` → `users.is_admin`.
Seguí esa cadena hasta el final:

- `_ADMIN_EMAIL_HASH` está **hardcodeado en el repo** (`main.py:126`) y el comentario de la línea
  de arriba **dice el email en claro**. O sea: el "secreto" es público. Ver también
  `audit/05_seguridad/5a-paso0-secret-key.md`.
- `_is_admin_email` (131-134) hace `email.strip().lower()` antes de hashear.
- `register` (3098) le da `is_admin=1` **a quien se registre con ese email**, y además le saltea la
  verificación de email y le devuelve token en el acto (3168-3176).
- La columna es `email TEXT UNIQUE` (713). En SQLite `UNIQUE` sobre `TEXT` es **case-sensitive**
  (collation `BINARY`).

Con eso, el ataque obvio es registrarse con `NicoFranco2004@Gmail.com`: `_is_admin_email` lo
lowercasea y matchea, pero el `UNIQUE` lo ve como una fila distinta del admin real → cuenta nueva
con `is_admin=1`.

**No funciona**, y por una sola línea: `RegisterIn.email_valid` (2866-2872) normaliza a
`v.strip().lower()` **antes** del `INSERT`, así que la variante en mayúsculas choca con el `UNIQUE`
y sale por `ERR_INTEGRIDAD` → 409. El regex `_EMAIL_RE` (2858) es ASCII puro, lo que además cierra
los trucos de mayúsculas Unicode (`İ`, ancho completo). Y `INSERT INTO users` existe en exactamente
dos lugares (3114 y 34396); el segundo, las cuentas shadow del Plan Asesor, hardcodea `is_admin=0`
en el VALUES (34397).

**La normalización en el modelo Pydantic es lo único que sostiene esto.** Si alguien alguna vez
mueve el lowercase del validador al handler, o agrega un tercer camino de creación de usuarios
que no pase por `RegisterIn`, el agujero se abre. Recomendación barata: `email TEXT UNIQUE COLLATE
NOCASE` en el schema, para que la defensa no dependa de recordar normalizar.

### V-2 · El header de contexto de cliente no llega a admin

`/api/admin` está en `CLIENT_CTX_EXEMPT_PREFIXES` (2752) con match por límite de segmento (2778).
Y los 47 endpoints admin usan `get_admin_user`, que llama a `get_current_user` — nunca a
`get_effective_user` — así que el header ni se consulta. Ambas capas verificadas.

### V-3 · Rutas admin duplicadas / sombreadas

FastAPI resuelve por orden de registro: una ruta declarada dos veces deja ganar a la primera, y un
segundo registro con menos auth quedaría muerto pero confundiría a quien lea. Conté los pares
(método, ruta) de todo `main.py`: **0 duplicados**. Tampoco hay colisión de shape entre
`/api/goals/cagr` y `/api/goals/{gid}/diagnostic`.

### V-4 · `password_hash` en las respuestas admin

Revisé las tres superficies que devuelven filas de `users`: `_ADMIN_USERS_SELECT` (18861-18872,
compartido por `/api/admin/users` y `/api/admin/users/search`) y `/api/admin/billing/inspect`
(19577). Las tres enumeran columnas explícitamente y **ninguna incluye `password_hash`**. No hay
`SELECT *` sobre `users` en el tramo.

---

## Lo que NO pude verificar (dicho explícitamente)

1. **Nada de esto se ejecutó.** No levanté el backend ni corrí un test que atraviese
   `get_admin_user`. Lo único MEDIDO es el escáner estático sobre el archivo. Las afirmaciones
   sobre comportamiento en runtime (que el `UNIQUE` rechaza la variante en mayúsculas, que
   `SameSite=lax` bloquea el POST cross-site) son DEDUCIDAS de leer el código y del comportamiento
   documentado de SQLite y de los navegadores, no observadas.
2. **H-1 no lo probé end-to-end.** No construí el escenario de ids reutilizados entre cuentas.
   Afirmo lo que se lee: falta el filtro. No afirmo que hoy sea alcanzable — al contrario, digo
   que hoy no lo es.
3. **No auditué qué pasa en Postgres.** Con `USANDO_PG` los tres endpoints que clonan la base
   levantan `EnsayoPorClonNoDisponible` → 501 (16933, 17262), pero no revisé si el resto del tramo
   cambia de semántica (`datetime('now')`, `date('now', …)`, la case-sensitivity del `UNIQUE` —
   que en Postgres **también** es case-sensitive por defecto, o sea que V-1 sigue cerrado ahí).
4. **No auditué los módulos importados.** `_invariantes.correr`, `scripts.pg_type_audit.auditar`,
   `importing.fx_migrate.migrate_user_fx`, `billing.emails.*`, `scripts.backup_db.run_backup`,
   `reporting.builder`, `goals_diagnostic`, `behavioral`. Verifiqué que reciben el `uid`/`user_id`
   correcto desde el handler; **no** entré a ver si adentro filtran bien. Es superficie real que
   queda sin cubrir.
5. **`ALLOWED_ORIGINS`** (239-262) lo miré de reojo para razonar sobre CSRF; no lo audité. Es de
   otro tramo.
6. **Fuera de mi tramo, pero lo vi al correr el chequeo global y lo dejo señalado para quien
   corresponda:** `GET /api/ai/topics` (`main.py:26308`) y `GET /api/reports/public/{token}`
   (`main.py:36005`) no tienen ninguna dependencia de auth. El segundo suena intencional por el
   nombre; el primero merece una mirada.
