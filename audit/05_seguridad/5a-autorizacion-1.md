# 5a · Autorización entre usuarios — tramo 1 de 6 (`main.py` 3094–9102, 44 endpoints)

Auditoría sobre `/tmp/rendi-main` (commit congelado `b74f450f`, `backend/main.py` = 38.029 líneas).
Área: **autorización entre usuarios** — sesión, propiedad del recurso, filtro `user_id`, contexto
de asesor (`X-Rendi-Client-Id`) y escrituras disparadas por GET.

---

## Método

**Ejecutado:**

- `awk` sobre `audit/05_seguridad/_inventario_endpoints.txt` → 44 endpoints en el rango. Los 44
  están en la tabla.
- `audit/_scripts/5a_tramo1_deps.py` (escrito para esta auditoría): parsea la firma de cada
  handler del tramo y extrae los `Depends(...)`. Salida completa pegada en el hallazgo H-0.
- `audit/_scripts/5a_tramo1_sql.py` (idem): junta cada bloque `.execute(...)` del tramo, detecta
  la tabla del `FROM/INTO/UPDATE/DELETE` y marca las que tocan una tabla con columna `user_id`
  **sin** que la sentencia mencione `user_id`. Salida completa pegada en H-0. **23 hits, todos
  benignos** (verificados uno por uno; el detalle está en H-0).
- Lectura completa del cuerpo de los 44 handlers y de los helpers a los que delegan cuando el
  handler no cierra la validación por sí mismo: `get_current_user` (2692), `get_admin_user` (2721),
  `_resolve_client_context` (2764), `get_effective_user` (2806), `_check_rate_limit` (395),
  `_rate_limit_ip` (391), `_ip_del_cliente` (335), `_gen_verification_code` (3034),
  `_create_verification_code` (3039), `_gen_reset_token` (2943), `_insert_manual_position` (8205),
  `_edit_position_group` (8333), `_undo_edit_position_group` (8477), `_delete_position_cascade`
  (14599), `_group_lots` (8306), `_src_tx_for_position` (8317),
  `pricing/fci.py:get_prices_detail_for` (321).
- `grep` de propagación: `_check_rate_limit(` (31 call sites), `CLIENT_CTX_HEADER` (3),
  `managed_by` (16), `CORSMiddleware`, schema de `users` en SQLite (711) y en `schema_pg.sql` (1717).

**NO ejecutado:**

- Ningún request contra producción ni contra ninguna instancia viva. Ninguna modificación de código.
- No levanté el backend: los hallazgos de este tramo son de **estructura** (falta un filtro, la
  clave de un contador incluye una dimensión de más), no de magnitud. Por eso ninguno se marca
  MEDIDO — ver la regla del prompt común: un deducido honesto vale más que un medido falso.
- No verifiqué el frontend: cuando un hallazgo depende de qué pantalla llama al endpoint (H-7) lo
  digo explícitamente y lo dejo en `REVISAR`.

**Supuestos declarados:**

1. Prod corre **SQLite** (`USANDO_PG` falso). Cuando un hallazgo cambia bajo Postgres, lo aclaro
   (H-6).
2. El frontend web pega a rutas relativas y Vercel proxea server-side, o sea el browser no cruza
   origin — es lo que afirma el comentario de `main.py:238-240`. No lo verifiqué en la
   infraestructura real.
3. El commit auditado es el de prod al 2026-09-05. `origin/main` está 11 commits adelante; no
   comprobé deriva porque ninguno de mis hallazgos cae en los archivos de la tanda F1.

---

## Resumen — hallazgos por severidad

| id | severidad | título | archivo:línea | evidencia |
|----|-----------|--------|---------------|-----------|
| H-0 | — | **No hay IDOR en este tramo**: los 44 endpoints filtran por dueño | `main.py:3094-9102` | ESTRUCTURAL (script) |
| H-1 | ALTO | El OTP de verificación no tiene contador de intentos por cuenta: el límite "por email" está cortado por IP | `main.py:396-397`, `3250`, `3034` | ESTRUCTURAL |
| H-2 | ALTO | El límite anti-brute-force "por email" del login tampoco es por email — mismo defecto, mismo helper | `main.py:3192` | ESTRUCTURAL |
| H-3 | MEDIO | Dos oráculos de enumeración de usuarios: `register` (409 estructurado) y `verify-email` ("ya está verificada") | `main.py:3181`, `3261` | ESTRUCTURAL |
| H-4 | MEDIO | El email admin en claro en el comentario anula el hash, y el alta de admin saltea `ALLOW_REGISTRATION` **y** la verificación de email | `main.py:123-131`, `3098-3141` | DEDUCIDO |
| H-5 | MEDIO | PARCHE: el único guard de contexto-de-cliente hardcodeado vive en un solo endpoint | `main.py:5015` | ESTRUCTURAL |
| H-6 | MEDIO | `schema_pg.sql` declara `users.email` **sin UNIQUE**: en Postgres booteado desde ese schema, dos cuentas con el mismo email | `schema_pg.sql:1717-1728` | ESTRUCTURAL |
| H-7 | BAJO | `/api/auth/investor-profile` cae en prefijo exento: el asesor escribe SU perfil creyendo que edita el del cliente | `main.py:2753`, `3971`, `3989` | DEDUCIDO |
| H-8 | BAJO | Oráculo 400-vs-404 sobre posiciones ajenas: el probe de `import_op_links` no filtra por usuario | `main.py:8614` | DEDUCIDO |
| H-9 | BAJO | 6 GET del tramo escriben en base; ninguno toca datos de usuario, pero la cookie es `SameSite=Lax` | `main.py:5622`, `6045`, `6913`, `6974`, `7606` | ESTRUCTURAL |
| H-10 | BAJO | CORS no permite `PATCH` ni el header `X-Rendi-Client-Id` | `main.py:259-264` | ESTRUCTURAL |
| H-11 | BAJO | `POST /api/positions` acepta un `broker` que no existe en `brokers` | `main.py:8280`, `8205` | ESTRUCTURAL |
| H-12 | BAJO | `/api/prices`: los símbolos `FCI:` esquivan el cap `MAX_SYMBOLS` | `main.py:7617-7631` | DEDUCIDO |

---

## Tabla — los 44 endpoints del tramo

Columna "valida sesión": la dependencia real, extraída por script (no leída a ojo).
Columna "valida propiedad": `n/a` = el endpoint no recibe ningún id de recurso.

| # | línea | método | ruta | qué hace | valida sesión | valida propiedad | veredicto |
|---|-------|--------|------|----------|---------------|------------------|-----------|
| 1 | 3094 | POST | `/api/auth/register` | crea usuario, manda OTP; si el email es el del admin: `is_admin=1`, se auto-verifica, adopta las filas `user_id=0` y devuelve token | **NINGUNA — público** | n/a (no recibe id; la identidad la fija el body) | `MEDIO: ...` H-3 (409 `EMAIL_ALREADY_REGISTERED` enumera) + H-4 (bypass admin de `ALLOW_REGISTRATION` y de la verificación) |
| 2 | 3187 | POST | `/api/auth/login` | verifica password, exige `email_verified`, emite JWT + cookie HttpOnly | **NINGUNA — público** | n/a | `ALTO: ...` H-2 — el límite `login_email:` está cortado por IP, la mitigación distribuida no existe. Lo demás correcto (401 genérico + `dummy_verify`) |
| 3 | 3231 | POST | `/api/auth/logout` | borra la cookie; no-op para clientes Bearer | **NINGUNA — público** | n/a | `OK` (documentado: no invalida el JWT server-side) |
| 4 | 3240 | POST | `/api/auth/verify-email` | valida OTP de 6 dígitos, marca `email_verified` y **emite token** | **NINGUNA — público** | n/a | `ALTO: ...` H-1 (brute-force del OTP → toma de cuenta) + `MEDIO` H-3 (mensaje "ya está verificada") |
| 5 | 3334 | POST | `/api/auth/resend-verification` | genera OTP nuevo y lo manda | **NINGUNA — público** | n/a | `OK` — respuesta genérica; 1/60s + 5/h, pero por IP (ver H-1) |
| 6 | 3358 | POST | `/api/auth/forgot-password` | invalida tokens previos, crea uno de 256 bits, manda el link | **NINGUNA — público** | n/a | `OK` — respuesta siempre genérica, token `token_urlsafe(32)` |
| 7 | 3412 | POST | `/api/auth/reset-password` | canjea el token, rota `password_changed_at`, loguea | **NINGUNA — público** | sí: el token ES la credencial (`WHERE token=?`, 256 bits, TTL 30 min, un solo uso) | `OK` |
| 8 | 3469 | GET | `/api/auth/me` | identidad + tier + estado de suscripción/crédito | `get_effective_user` | n/a — todas las queries son `WHERE id=uid` / `user_id=uid` | `OK` (`/api/auth` es prefijo exento → el header de cliente se ignora) |
| 9 | 3569 | POST | `/api/auth/change-password` | verifica la actual, rota el hash y el JWT | `get_effective_user` | n/a — `WHERE id=uid` | `OK` (exento: el asesor cambia SU password, nunca la del cliente) |
| 10 | 3741 | GET | `/api/me/reset-data/status` | progreso del reset (estado en memoria por uid) | `get_effective_user` | n/a | `OK` (`/api/me` exento) |
| 11 | 3759 | POST | `/api/me/reset-data` | lanza el worker de borrado de cartera | `get_effective_user` | n/a | `OK` — además está desactivado salvo `RENDI_RESET_DATA_ENABLED=1` |
| 12 | 3807 | DELETE | `/api/me` | cierre de cuenta: barrido dinámico de toda tabla con `user_id` + shadows `managed_by=uid` | `get_effective_user` | n/a — `WHERE user_id=uid` en todas | `OK` — verifiqué que `managed_by` solo se setea al crear un shadow (34397) y se pone a NULL al reclamar la cuenta (35157), así que nunca borra un usuario real ajeno |
| 13 | 3971 | GET | `/api/auth/investor-profile` | lee `users.investor_profile` | `get_effective_user` | n/a — `WHERE id=uid` | `REVISAR: ...` H-7 — exento por prefijo: en contexto de cliente devuelve el perfil del ASESOR |
| 14 | 3989 | POST | `/api/auth/investor-profile` | valida contra allowlist y guarda; invalida cache IA | `get_effective_user` | n/a — `WHERE id=uid` | `REVISAR: ...` H-7 — en contexto de cliente **escribe** el perfil del asesor |
| 15 | 4040 | GET | `/api/brokers` | lista brokers | `get_effective_user` | sí — `WHERE user_id=?` | `OK` |
| 16 | 4053 | POST | `/api/brokers` | crea broker + posición cash 0; cuota de plan | `get_effective_user` | sí — `parent_broker_id` se valida con `WHERE id=? AND user_id=?` (4257) y el `SELECT` de retorno también | `OK` |
| 17 | 4137 | PUT | `/api/brokers/{bid}` | rename + cascade del nombre en 6 tablas, dentro de una tx | `get_effective_user` | sí — el `SELECT` inicial es `WHERE id=? AND user_id=?` (4159) y **todos** los UPDATE del cascade llevan `user_id=?`; `import_normalized_tx` (que no tiene `user_id`) se acota por subquery de `import_batches WHERE user_id=?` | `OK` |
| 18 | 4337 | DELETE | `/api/brokers/{bid}` | borrado con `?force`, cascade a hijos, recalc y purga de snapshots | `get_effective_user` | sí — todos los `DELETE`/`UPDATE` llevan `user_id=?` + `broker IN (...)` derivado de brokers propios | `OK` |
| 19 | 4542 | GET | `/api/config` | tc_mep / tc_blue del usuario | `get_effective_user` | sí — `WHERE user_id=?` | `OK` |
| 20 | 4565 | PUT | `/api/config` | upsert con `ON CONFLICT (key, user_id)` | `get_effective_user` | sí — la PK compuesta incluye `user_id` | `OK` |
| 21 | 4978 | GET | `/api/dolar` | cotizaciones del día desde cache en memoria | `get_effective_user` | n/a — dato global, no toca la base | `OK` |
| 22 | 4983 | GET | `/api/public/dolar` | solo el blue, para la landing pre-login | **NINGUNA — público a propósito** (documentado) | n/a — dato de mercado público | `OK` |
| 23 | 5004 | POST | `/api/snapshots` | upsert de la foto del día; no pisa un cierre del cron | `get_effective_user` | sí — `WHERE user_id=? AND date=?` / `ON CONFLICT(user_id,date)` | `MEDIO: ...` H-5 — el guard de contexto de cliente está hardcodeado acá y en ningún lado más |
| 24 | 5093 | GET | `/api/snapshots` | serie de fotos + clasificación de calidad | `get_effective_user` | sí — `WHERE user_id=?` | `OK` (`days` se usa como LIMIT de filas, no de días — es un bug de cálculo, no de seguridad) |
| 25 | 5170 | GET | `/api/fx-rates` | serie diaria blue/MEP | `get_effective_user` | n/a — `fx_rates_daily` es global | `OK` |
| 26 | 5509 | GET | `/api/benchmarks` | 7 benchmarks externos, SWR en memoria | `get_effective_user` | n/a — global | `OK` |
| 27 | 5622 | GET | `/api/bond-indices/{index_name}` | serie CER/UVA/A3500; el `index_name` está en allowlist dura y las fechas contra `_DATE_RE` | `get_effective_user` | n/a — `bond_indices_daily` es global | `BAJO` H-9 (GET que escribe el cache global vía `_ensure_index_cached`) |
| 28 | 5791 | GET | `/api/events/popular` | eventos macro + earnings de tickers populares; marca `in_portfolio` | `get_effective_user` | sí para la parte privada — `SELECT DISTINCT asset FROM positions WHERE user_id=?` | `OK` |
| 29 | 6025 | GET | `/api/events/earnings-expectations` | consenso de earnings de un símbolo (yfinance cacheado) | `get_effective_user` | n/a — símbolo validado con `_SYMBOL_RE`, dato público | `OK` |
| 30 | 6045 | GET | `/api/events/portfolio` | eventos de los tickers en cartera | `get_effective_user` | sí — los tickers salen de `positions WHERE user_id=?` | `BAJO` H-9 (refresca `financial_events`, tabla global) |
| 31 | 6913 | GET | `/api/news/market` | feed macro/mercado | `get_effective_user` | n/a — `news` es global | `BAJO` H-9 |
| 32 | 6974 | GET | `/api/news/portfolio` | noticias de los tickers en cartera + peso de cada holding | `get_effective_user` | sí — tickers y `holding_weights` derivan de `user_id=?` | `BAJO` H-9. El `LIKE` se arma con tickers propios y va parametrizado; un `%` en un nombre de activo solo ensancha el match sobre noticias públicas |
| 33 | 7606 | GET | `/api/prices` | precios (data912 / yfinance / FCI) | `get_effective_user` | n/a — `asset_last_price`, `fci_prices` son globales; la query FCI va parametrizada | `BAJO` H-12 (los `FCI:` esquivan `MAX_SYMBOLS`) + H-9 |
| 34 | 7866 | GET | `/api/prices/prev-close` | cierre del día hábil anterior | `get_effective_user` | n/a — global; `_SYMBOL_RE` + `MAX_SYMBOLS` | `OK` |
| 35 | 8050 | GET | `/api/prices/history` | serie histórica para el mini-chart | `get_effective_user` | n/a — global; `symbol` contra `_SYMBOL_RE`, `period` contra allowlist | `OK` (lee el CCL del usuario vía `_display_ccl(conn, uid)`, que ya va scopeado) |
| 36 | 8186 | GET | `/api/positions` | todas las posiciones | `get_effective_user` | sí — `WHERE user_id=?` | `OK` |
| 37 | 8280 | POST | `/api/positions` | alta manual + débito de cash + autodepósito | `get_effective_user` | sí — inserta con `user_id=uid`; el `SELECT` de retorno es `WHERE id=? AND user_id=?` | `BAJO` H-11 (`broker` es texto libre, no se valida contra `brokers`) |
| 38 | 8460 | PATCH | `/api/positions/group` | edita todos los lotes de broker+activo+moneda; deja token de undo | `get_effective_user` | sí — `_group_lots` filtra `user_id=?`; cada `UPDATE positions` repite `AND user_id=?`; los `UPDATE import_normalized_tx ... WHERE id=?` usan ids que salen de `_src_tx_for_position`, que **sí** hace `JOIN import_batches ... WHERE b.user_id=?` (8327) | `OK` |
| 39 | 8512 | POST | `/api/positions/group/undo/{token}` | deshace la edición grupal | `get_effective_user` | sí — `WHERE user_id=? AND token=?` + claim atómico sobre `undone_at`; los ids restaurados vienen del payload que escribió el propio usuario | `OK` |
| 40 | 8528 | GET | `/api/positions/group/context` | cuántas ventas e importados tiene el grupo | `get_effective_user` | sí — `_group_lots` y el `COUNT` de `operations` filtran `user_id=?` | `OK` |
| 41 | 8549 | PUT | `/api/positions/{pid}` | edita un lote | `get_effective_user` | sí — `UPDATE ... WHERE id=? AND user_id=?` y el `SELECT` de retorno idem (con comentario `FIXED: include user_id ... to prevent IDOR`) | `OK` |
| 42 | 8594 | DELETE | `/api/positions/{pid}` | rutea a cascada importada / manual / bloqueo legacy | `get_effective_user` | sí en el efecto — `_delete_position_cascade` revalida `WHERE id=? AND user_id=? AND is_cash=0` (14609) y la rama manual filtra `user_id=?` | `BAJO: ...` H-8 — el **probe** de ruteo (8614) no filtra por usuario: no borra nada ajeno, pero distingue 400 de 404 sobre pids de otros |
| 43 | 8877 | POST | `/api/positions/{pid}/adjust-ratio` | re-deriva el split en el server y ajusta qty/precio | `get_effective_user` | sí — `SELECT ... WHERE id=? AND user_id=?`, `UPDATE ... WHERE id=? AND user_id=?` condicional por watermark | `OK` — además no confía en factor/fecha del cliente |
| 44 | 8967 | GET | `/api/positions/split-check` | lotes con split pendiente | `get_effective_user` | sí — `WHERE p.user_id=?` y el `EXISTS` sobre `brokers` correlaciona `b.user_id = p.user_id` | `OK` |

**Conteo:** 44 de 44. 8 públicos (7 de `/api/auth/*` + `/api/public/dolar`), 36 autenticados, **los
36 con `get_effective_user`** — ninguno usa `get_current_user` ni `get_admin_user` directamente.

---

## Hallazgos

### H-0 · No hay IDOR en este tramo (el resultado negativo, con su evidencia)

**Evidencia:** ESTRUCTURAL (dos scripts + lectura de los 44 cuerpos)
**Dónde:** `main.py:3094-9102`; scripts en `audit/_scripts/5a_tramo1_deps.py` y
`audit/_scripts/5a_tramo1_sql.py`

**Qué pasa:** Los 8 endpoints que reciben un id de recurso (`{bid}` ×2, `{pid}` ×3, `{token}`,
`{index_name}`, y el par broker+asset de `/positions/group*`) filtran por dueño **en la sentencia
que produce el efecto**, no solo en un chequeo previo. Los tres patrones que aparecen:

1. `WHERE id=? AND user_id=?` en el `SELECT` de entrada **y** repetido en cada `UPDATE`/`DELETE`
   (brokers PUT/DELETE, positions PUT/DELETE/adjust-ratio).
2. Para `import_normalized_tx`, que **no tiene columna `user_id`**, el scope va por
   `JOIN import_batches b ON b.id=n.batch_id WHERE b.user_id=?` (`_src_tx_for_position`, 8317-8331;
   `_delete_position_cascade`, 14624-14630) o por subquery equivalente (`update_broker`, 4295-4302).
   Es el punto donde un `WHERE id=?` suelto habría sido crítico, y está cubierto en los tres sitios.
3. Los ids que se usan sin `user_id` (`UPDATE email_verification_codes ... WHERE id=?` 3285,
   `UPDATE password_reset_tokens ... WHERE id=?` 3445, `UPDATE deleted_ops_journal ... WHERE id=?`
   8488, los `UPDATE import_normalized_tx ... WHERE id=?` del undo grupal 8497) provienen **todos**
   de una fila leída inmediatamente antes con el filtro del dueño puesto. Los revisé uno por uno.

El script de SQL levantó 23 sentencias "sospechosas"; las 23 son de las categorías anteriores o son
`WHERE id=uid` sobre `users` (o sea, el propio usuario), o consultas por email dentro de los flujos
**no autenticados**, donde el email ES el identificador. **Cero hallazgos de propiedad.**

**Por qué importa decirlo:** es el resultado que justifica que las severidades de este tramo bajen
de CRÍTICO. Todo lo que sigue es autenticación (H-1..H-4), contexto de asesor (H-5, H-7) o defensa
en profundidad. Ningún usuario llega a datos de otro cambiando un número en la URL.

---

### [ALTO] H-1 · El OTP de verificación no tiene contador de intentos por cuenta

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:396-397` (la clave del contador), `main.py:3250` (el uso),
`main.py:3034-3036` (el espacio de códigos), `main.py:2912` (TTL)

**Qué pasa:** El código es de 6 dígitos sin cero inicial —`secrets.randbelow(900000) + 100000`—, o
sea **900.000 valores**, con TTL de 15 minutos. Es un secreto chico, y por eso todo depende del
límite de intentos. El endpoint lo pone así:

```python
_check_rate_limit(request, max_calls=5, window_seconds=60, suffix=f"verify_email:{email_norm}")
```

y el docstring de arriba explica la intención textualmente: *"rate limit por email (no global) para
evitar que un atacante bloquee la verificación de todos los users"*. Pero el helper construye la
clave así (`main.py:396-397`):

```python
ip = _rate_limit_ip(request)
key = f"{ip}|{suffix}" if suffix else ip
```

**La IP entra siempre.** El balde no es "este email", es "este email desde esta IP". El límite
protege contra un atacante de una sola IP y **no existe** contra uno distribuido: N IPs dan 5·N
intentos por minuto sobre la MISMA cuenta. No hay ninguna otra defensa que lo compense: la fila de
`email_verification_codes` no tiene columna de intentos fallidos, el código no se invalida tras N
errores (solo al usarse o al generarse uno nuevo, 3047-3051), y `verify_email` no incrementa nada.

**Cómo se explota en la práctica:** el atacante ve un signup (o simplemente prueba emails), y
durante los 15 minutos de vida del código itera los 900.000 valores desde un pool de proxies. Con
~12.000 IPs cubre el espacio entero en la ventana; con ~6.000 tiene ~50 % de probabilidad. Los pools
residenciales de ese tamaño son un commodity. El premio no es menor: `verify_email` **emite el
token y setea la cookie de sesión** (3316-3322), así que adivinar el OTP es tomar la cuenta antes de
que su dueño abra el mail — con acceso a tenencias, operaciones y patrimonio.

**Qué queda expuesto:** la cuenta completa de cualquier usuario en la ventana entre el registro y su
verificación. Un atacante que además controle el momento (invitándolo a registrarse) elige la ventana.

**Otros call sites del mismo patrón:** los 31 usos de `_check_rate_limit` heredan la clave con IP.
Los que dicen ser "por sujeto" y no lo son, en orden de gravedad:

- `main.py:3192` `login_email:{email}` → **H-2**, mismo defecto sobre la password.
- `main.py:3340` y `3341` `resend:{email}` / `resend_hourly:{email}` → el anti-flood del buzón del
  usuario es por IP: un atacante distribuido igual le llena la casilla.
- `main.py:3368` `forgot_pw_email:{email}` → idem para el mail de reseteo.
- `main.py:25913, 26192, 26527, 26665, 27318, 28226, 28295, 29318, 29380, 31241, 31281, 31493,
  31535, 34377, 34696, 35947, 36296` — todos `...:{uid}`. Ahí el efecto no es toma de cuenta sino
  **abuso de cuota** (IA, billing, sync de brokers): rotando IP el mismo usuario supera su tope.
  Fuera de mi tramo, los dejo listados para el que audite esas áreas.

**Solución de fondo:** separar las dos dimensiones en el helper en vez de parchear los call sites.
`_check_rate_limit` debería aceptar explícitamente el **sujeto** del límite (`por_ip=True/False`) y,
cuando el sujeto es un email o un uid, construir la clave **sin** la IP. Encima de eso, el OTP
necesita lo que ningún rate limit da: un contador de fallos **persistido en la fila del código**
(`attempts`), que lo invalide a los 5 intentos y obligue a pedir uno nuevo. Nota operativa: el
`_rate_store` es un dict en memoria del proceso, así que con más de un worker cada réplica tiene su
propio balde — el límite efectivo ya se multiplica por la cantidad de workers antes de contar IPs.

---

### [ALTO] H-2 · El límite anti-brute-force "por email" del login tampoco es por email

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:3191-3192`

**Qué pasa:** Es el mismo mecanismo de H-1, con el comentario que declara la intención pegado
justo arriba:

```python
# Rate limit por IP y por email (mitiga brute-force distribuido sobre una cuenta puntual)
_check_rate_limit(request, max_calls=10, window_seconds=60, suffix="login_ip")
_check_rate_limit(request, max_calls=10, window_seconds=60, suffix=f"login_email:{email_norm}")
```

Las dos líneas hacen **lo mismo**: la primera es "10/min por IP" y la segunda es "10/min por IP,
para esta cuenta". La segunda no agrega ninguna defensa contra el escenario que el comentario dice
mitigar. Un atacante distribuido tiene 10 intentos por minuto **por cada IP** sobre una cuenta
elegida, sin ningún tope agregado, sin bloqueo de cuenta y sin backoff.

**Cómo se explota en la práctica:** password spraying sobre una lista de emails (que H-3 permite
depurar), o brute-force dirigido a una cuenta concreta. bcrypt encarece cada intento del lado del
servidor, lo cual acota el throughput y de paso convierte el ataque en un vector de agotamiento de
CPU sobre el proceso.

**Qué queda expuesto:** cualquier cuenta con password débil, y el CPU del backend.

**Otros call sites del mismo patrón:** los de H-1 (misma raíz, mismo helper).

**Solución de fondo:** la misma que H-1 (clave sin IP para límites por sujeto) más un tope agregado
por cuenta —del orden de 20 fallos/hora contando **todas** las IPs— y bloqueo temporal con aviso al
dueño reusando `_record_login_and_maybe_alert`, que ya existe y ya manda mail.

---

### [MEDIO] H-3 · Dos oráculos de enumeración de usuarios

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:3177-3183` (register) y `main.py:3259-3261` (verify-email)

**Qué pasa:** El resto del área de auth está cuidada: `login` devuelve 401 genérico para email
inexistente y para password incorrecta, y llama `pwd_ctx.dummy_verify()` (3196) para igualar el
tiempo; `forgot-password` (3401-3404) y `resend-verification` (3350-3351) responden siempre lo
mismo, con el comentario que lo explica. Dos endpoints rompen esa línea:

1. **`register`** responde `409` con `{"code": "EMAIL_ALREADY_REGISTERED", ..., "email": ...}`. Es
   deliberado (el comentario dice que es para ofrecer "Ir al login"), pero **es un oráculo exacto**:
   cualquier email prueba en un request si tiene cuenta en Rendi.
2. **`verify-email`** distingue tres casos donde debería haber uno: email inexistente → *"Código
   inválido o expirado"* (3257), email existente **ya verificado** → *"Tu cuenta ya está verificada.
   Iniciá sesión."* (3261), email existente sin verificar → *"Código inválido o expirado"*. O sea:
   con cualquier código basura, el segundo mensaje identifica a los usuarios **activos**. Éste no
   tiene comentario que lo justifique: es un descuido, y encima está dentro del mismo handler que
   sí se cuidó de no filtrar en el primer caso.

**Cómo se explota en la práctica:** listado de emails (una brecha de terceros, un scrape de
LinkedIn) → `verify-email` o `register` en lote → set de clientes de Rendi. Ese set alimenta H-2
(spraying) y H-1 (a quién vale la pena atacar), y por sí solo ya es un dato comercial y personal:
"estas personas manejan cartera de inversión en Argentina".

**Qué queda expuesto:** la pertenencia a la base de usuarios, que en una app de patrimonio personal
es información sensible aunque no venga acompañada de ningún número.

**Otros call sites del mismo patrón:** revisé los 7 endpoints públicos del tramo; los otros 5 están
bien. Fuera del tramo quedan los flujos de invitación/claim del plan asesor (`main.py:34998, 35041,
35065, 35111`, limitados por IP con sufijos `linkreq_*` / `claim_*`), que reciben emails o tokens y
podrían tener el mismo problema — **no los audité, son de otro tramo**.

**Solución de fondo:** unificar la respuesta. En `verify-email`, el caso "ya verificada" debe dar el
mismo 400 genérico que los otros dos (la UX se resuelve del lado del frontend, que ya sabe si
acaba de registrar). En `register`, si el 409 estructurado se mantiene por producto, que sea una
decisión escrita —hoy lo es a medias— y que quede claro que la defensa contra enumeración masiva
pasa a depender enteramente del rate limit… que es el que H-1 muestra roto.

---

### [MEDIO] H-4 · El email admin en claro anula su propio hash, y el alta de admin saltea dos puertas

**Evidencia:** DEDUCIDO (lectura de `main.py:120-135` y `3094-3175`; no ejecuté el flujo)
**Dónde:** `main.py:123-131` y `main.py:3098-3141`

**Qué pasa:** Hay dos cosas, y la segunda es la que importa.

**(a) El hash del email admin es una defensa anulada por su propio comentario.** El código guarda
`_ADMIN_EMAIL_HASH` y compara con `hmac.compare_digest`, con el comentario *"el email del admin no
se guarda en plano"* y una nota sobre timing attacks. Tres líneas más abajo, el mismo bloque dice el
email real en texto plano. El mecanismo criptográfico está bien implementado y protege exactamente
nada: quien lee el archivo obtiene el dato que el hash escondía. (Nota: el email admin es además el
del dueño del repo, o sea recuperable por otras vías — razón de más para no fingir que está oculto.)

**(b) El alta del admin saltea las dos puertas de entrada.** En `register`:

- `if not ALLOW_REGISTRATION and not is_admin_signup: raise 403` (3099-3100) → con el registro
  **cerrado**, el email admin es el único que todavía puede crear cuenta.
- `email_verified = 1 if is_admin_signup else 0` (3111) → el alta admin **no verifica el email**: no
  hace falta controlar el buzón.
- El bloque 3117-3141 le transfiere las filas legacy `user_id=0` de `positions`, `monthly_entries`,
  `operations` y `config`.
- 3168-3175 le devuelve token y cookie de una.

Encadenado: **si la fila del admin no existe en `users`, el primer request a `/api/auth/register`
con ese email crea una cuenta con `is_admin=1`, sesión inmediata y sin prueba de identidad.** Y esa
fila es borrable por su propio dueño: `DELETE /api/me` (endpoint 12 de este tramo) hace
`DELETE FROM users WHERE id=?` (3876) sin ninguna excepción para admin. O sea, el cierre de cuenta
del administrador —una acción que la UI ofrece— deja la silla de admin vacía y auto-asignable.

**Cómo se explota en la práctica:** requiere la condición extra de que la cuenta admin no exista
(por eso ALTO/MEDIO y no crítico): borrado accidental, restauración de un backup previo a su alta,
o un despliegue nuevo apuntando a una base recién creada. En cualquiera de esos estados, quien
llegue primero con ese email es administrador de Rendi. La carrera la gana el que está mirando.

**Qué queda expuesto:** todo `/api/admin/*` — o sea, según el propio índice del repo, herramientas de
billing (regalar Pro, tier, crédito), migradores de FX, backfills y paneles con datos de todos los
usuarios.

**Otros call sites del mismo patrón:** `_is_admin_email` se usa solo acá (grep: `main.py:131`
definición, `3098` uso). `is_admin` como gate vive en `get_admin_user` (2721) y en `_require_advisor`
(2823), que deliberadamente **no** acepta admin — o sea el proyecto ya distingue "admin" de "tier
pagado"; lo que falta es esa misma distinción entre "admin" y "quien se registró con este email".

**Solución de fondo:** desacoplar el otorgamiento de admin del registro. `register` no debería poder
crear un `is_admin=1` bajo ninguna condición: la promoción tiene que ser una operación fuera de banda
(migración, comando de consola, o un flag en la base) sobre una cuenta **ya verificada**. Como
mínimo inmediato: exigir verificación de email también para el admin (borrar el `1 if is_admin_signup`
de 3111), impedir el auto-borrado del último admin en `DELETE /api/me`, y sacar el email del
comentario o asumir que el hash no es un secreto y documentarlo como tal.

---

### [MEDIO] H-5 · PARCHE: el único guard de contexto-de-cliente vive hardcodeado en un endpoint

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:5006-5016` (el guard) y `main.py:2749-2762` (el mecanismo que debería cubrirlo)

**Qué pasa:** `POST /api/snapshots` abre con un `if` explícito:

```python
if request.headers.get(CLIENT_CTX_HEADER):
    return {"ok": True, "skipped": "contexto de cliente"}
```

El comentario explica bien el síntoma que lo motivó: el Dashboard postea la foto del día solo al
cargar, con el criterio de valuación del que mira; con la lente de un cliente abierta, el asesor le
pisaba la medición. Que exista es correcto. Lo que lo vuelve un parche es que es **el único**: grep
de `CLIENT_CTX_HEADER` en las 38.029 líneas devuelve exactamente 3 usos — la constante (2748), el
resolvedor (2772) y este `if` (5015).

**Cuál es la causa real:** `get_effective_user` decide con dos dimensiones —el prefijo de la ruta y
el método HTTP— y le falta la tercera, que es la que rompe acá: **si la escritura es una acción
deliberada del asesor o un efecto colateral de mirar**. Un POST que el browser dispara solo al
renderizar pasa el chequeo de `read_write` igual que un alta que el asesor tipeó, porque para
`_resolve_client_context` los dos son "no-GET". El propio comentario del bloque lo anticipa:
*"⚠️ FAIL-OPEN: todo endpoint futuro FUERA de estos prefijos hereda el contexto de cliente"*.

**Cómo se explota en la práctica:** no es explotación de un tercero — es corrupción de datos entre
un asesor y su cliente, dentro de un vínculo legítimo. El siguiente endpoint que el frontend
dispare automáticamente y que escriba en la cuenta del cliente reproduce el bug sin que nadie lo
note, porque no hay nada que lo detenga: hay que acordarse de agregar el `if`.

**Qué queda expuesto:** la integridad de la serie histórica del cliente (la medición sobre la que se
apoyan TWR, la curva de evolución y el informe que justifica el fee del asesor).

**Otros call sites del mismo patrón:** dentro de mi tramo, ninguno más lo necesita hoy: los otros
14 endpoints de escritura (`brokers` ×3, `config`, `positions` ×5, `snapshots`, `investor-profile`,
y los 3 de `/api/me` y `/api/auth`) son acciones explícitas del usuario o caen en prefijo exento.
Fuera del tramo **no lo verifiqué** — en particular los escritores de cache de IA y de precios, que
sí se disparan solos.

**Solución de fondo:** subir la decisión al mecanismo. Que el endpoint declare su naturaleza (por
ejemplo, una dependencia `get_effective_user_solo_lectura` para las escrituras-por-efecto-de-lectura,
o una lista `CLIENT_CTX_NO_ESCRIBE` al lado de `CLIENT_CTX_EXEMPT_PREFIXES`) y que
`_resolve_client_context` la aplique. Así el próximo endpoint de este tipo falla cerrado en vez de
depender de que alguien recuerde copiar tres líneas.

---

### [MEDIO] H-6 · `schema_pg.sql` declara `users.email` sin UNIQUE

**Evidencia:** ESTRUCTURAL
**Dónde:** `backend/schema_pg.sql:1717-1728` vs `backend/main.py:711-722`

**Qué pasa:** En SQLite la columna se declara `email TEXT UNIQUE NOT NULL` (713). En el schema de
Postgres generado, la misma columna es `email text NOT NULL` — **sin UNIQUE**, y un grep de índices
sobre `users(email)` en el archivo no devuelve nada. Que la restricción debería existir lo confirma
`dberrors.py:51`, que documenta el mensaje de Postgres `duplicate key value violates unique
constraint "users_email_key"` — el código sabe que hay un constraint con ese nombre; el schema no lo
crea.

**Por qué importa para autorización:** toda la identidad de la app asume que un email es una cuenta.
`login` (3194), `verify-email` (3253), `resend-verification` (3345) y `forgot-password` (3373) hacen
`SELECT ... FROM users WHERE email=?` y toman **una** fila (`fetchone`, sin `ORDER BY`). Sin UNIQUE,
`register` deja de fallar con `ERR_INTEGRIDAD` y crea una segunda cuenta con el mismo email; a
partir de ahí, cuál de las dos resuelve cada flujo depende del orden físico que devuelva Postgres.
Un atacante que registre el email de una víctima podría quedar del lado que recibe el link de
reseteo, o hacer que la víctima aterrice en la cuenta del atacante.

**Cómo se explota en la práctica:** solo si prod corre Postgres booteado desde este archivo. Según
el índice de memoria del proyecto, la migración está **deployada dormida** y prod sigue en SQLite,
así que hoy no es explotable. Es una mina en el camino de la migración, y el momento de desactivarla
es antes de cruzarlo.

**Otros call sites del mismo patrón:** no revisé el resto de `schema_pg.sql` en busca de UNIQUE
perdidos — es un archivo generado por `mkschema.py`, y el índice del proyecto ya registra que ese
generador *"reescribe `schema_pg.sql` en el lugar"*. **La revisión que corresponde no es de esta
columna sino del generador**: si perdió un UNIQUE, hay que preguntarse cuántos más perdió.

**Solución de fondo:** arreglar `mkschema.py` para que emita los UNIQUE de columna, regenerar, y
—porque un fix de generador no repara una base ya creada— verificar con un `\d users` contra la
base de Postgres real que el constraint exista antes de cortar el tráfico.

---

### [BAJO] H-7 · `/api/auth/investor-profile` cae en prefijo exento: el asesor escribe su propio perfil

**Evidencia:** DEDUCIDO (backend leído; **no verifiqué el frontend**)
**Dónde:** `main.py:2750` (`"/api/auth"` en `CLIENT_CTX_EXEMPT_PREFIXES`), `3971` y `3989`

**Qué pasa:** El perfil de inversor (horizonte, tolerancia al drawdown, patrimonio, experiencia) es
**dato del cliente**, no de identidad: se inyecta en el system prompt de todos los packets de IA, y
el propio handler invalida la cache de IA al guardarlo (4011). Pero vive bajo `/api/auth/`, que está
en la lista de exentos, así que con contexto de cliente activo el header se ignora: el GET devuelve
el perfil del **asesor** y el POST **sobrescribe el del asesor**.

Es el reverso exacto del riesgo que el comentario del bloque describe. Ahí la preocupación es que un
endpoint de identidad **no** esté exento y el asesor opere donde no corresponde; acá pasa lo
contrario, un endpoint de **datos** quedó exento por vivir en el prefijo equivocado. La lista de
prefijos es un proxy de la intención, y este endpoint está del lado equivocado del proxy.

**Cómo se explota en la práctica:** no hay atacante. El asesor abre la lente del cliente, completa
el test de 7 preguntas creyendo que perfila al cliente, y el resultado es que (a) el cliente sigue
sin perfil y (b) el perfil del asesor queda pisado con las respuestas del cliente — contaminando
**su propio** contexto de IA. Depende de que la pantalla sea alcanzable en modo cliente: **eso no lo
verifiqué**, por eso queda en `REVISAR` y en BAJO.

**Otros call sites del mismo patrón:** revisé los 8 prefijos exentos contra los endpoints de mi
tramo. Los otros 8 endpoints bajo `/api/auth` y los 3 bajo `/api/me` **sí** son de identidad o de
cuenta y están bien exentos. Éste es el único desalineado del tramo.

**Solución de fondo:** mover la ruta a un prefijo de datos (`/api/investor-profile` o
`/api/me/perfil-inversor` no sirve — `/api/me` también está exento; tiene que ser un prefijo nuevo,
no exento), o hacer el exento por **ruta exacta** en vez de por prefijo para poder excluir estas dos.

---

### [BAJO] H-8 · Oráculo 400-vs-404 sobre posiciones ajenas

**Evidencia:** DEDUCIDO
**Dónde:** `main.py:8613-8615`

**Qué pasa:** `DELETE /api/positions/{pid}` decide a qué motor rutear con un probe que no filtra por
usuario:

```python
link = conn.execute(
    "SELECT 1 FROM import_op_links WHERE position_id=? LIMIT 1", (pid,),
).fetchone()
```

No borra nada ajeno —el motor al que rutea revalida `WHERE id=? AND user_id=?` (14609)— pero las dos
ramas terminan en respuestas **distintas** para un `pid` de otro usuario: con link, el cascade tira
`404 "Posición no encontrada"`; sin link, la rama manual (que sí filtra por `user_id`, 8626) no
encuentra nada y cae en `400` con el mensaje legacy. La diferencia revela, para cualquier id del
espacio global, si esa posición existe y si vino de un import.

**Qué queda expuesto:** un bit por id (importada / no importada) y, agregado sobre el rango de ids,
una estimación del tamaño y la composición de la base. Es poco, y por eso es BAJO — pero es
exactamente el tipo de descuido que en otro handler habría sido el borrado.

**Otros call sites del mismo patrón:** el probe idéntico dentro de `_delete_position_cascade`
(14615-14617) tampoco filtra por usuario, pero ahí es inofensivo: la función ya validó la propiedad
de `pos_id` seis líneas antes (14609-14613), así que el `position_id` que consulta es propio.

**Solución de fondo:** hacer el probe sobre una posición **ya validada**: mover el
`SELECT * FROM positions WHERE id=? AND user_id=?` al principio del handler y devolver 404 antes de
mirar `import_op_links`. Eso además unifica el mensaje de error de las dos ramas.

---

### [BAJO] H-9 · Seis GET del tramo escriben en base

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:5622` (`_ensure_index_cached`), `6045` y `5791` (`_refresh_events_*`), `6913` y
`6974` (`_refresh_news_*`), `7606` (`_fill_last_known_prices`, 7538)

**Qué pasa:** El punto 5 del encargo pregunta si hay GET que escriban salteando el control de
`read_write` (que `_resolve_client_context` solo exige a los métodos no-GET, 2800). En este tramo
**sí los hay**, pero **ninguno escribe datos de un usuario**: las cinco tablas que tocan
—`bond_indices_daily`, `financial_events`, `news`, `asset_last_price` y el cache en memoria de
`/dolar`— son **globales**, sin columna `user_id`, keyed por símbolo o fecha. Verifiqué las cinco.

Queda entonces como defensa en profundidad, con dos aristas reales:

1. **Un asesor con vínculo `linked` (solo lectura) dispara escrituras globales.** No toca datos de
   su cliente, así que el modelo de permisos no se viola en lo que protege; pero la afirmación
   "read-only" es más floja de lo que suena.
2. **La cookie es `SameSite=Lax`** (`main.py:158`), lo que significa que sí viaja en navegaciones
   top-level cross-site por GET. Un `<a>` o un redirect desde cualquier sitio puede hacer que el
   browser del usuario ejecute estos GET autenticados. Hoy el daño es nulo (refrescan caches
   públicos); el día que un GET escriba algo con `user_id`, deja de serlo.

**Solución de fondo:** que el refresco de caches globales no cuelgue del request de un usuario —es
trabajo del cron, que ya existe (`snapshots_job.py`, `project_cron_infra`)—, y que la regla "un GET
no escribe nada scopeado por usuario" quede como invariante verificable en tests y no como
costumbre. Fuera de mi tramo hay más GET que escriben; **no los relevé**.

---

### [BAJO] H-10 · CORS no permite `PATCH` ni el header del contexto de asesor

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:258-264`

**Qué pasa:** `allow_methods=["GET", "POST", "PUT", "DELETE"]` y
`allow_headers=["Authorization", "Content-Type"]`. Falta **PATCH** —que es el método de
`PATCH /api/positions/group`, endpoint 38 de este tramo— y falta **`X-Rendi-Client-Id`**, el header
del que depende todo el plan Asesor. La lista de origins está bien (explícita, sin `*`, con default
por entorno) y `allow_credentials=True` es coherente con eso.

Hoy no rompe nada porque en prod el browser no cruza origin (Vercel proxea server-side, según el
comentario de 238-240). Lo anoto porque la configuración **dice** ser defensa en profundidad para
el caso en que alguien pegue directo al dominio de Railway, y en ese caso concreto no defiende: falla
como incompatibilidad, no como bloqueo. Una defensa que solo funciona mientras nadie la use no está
verificada.

**Solución de fondo:** agregar `PATCH` y `X-Rendi-Client-Id`, y —más al fondo— derivar la lista de
métodos del router en vez de escribirla a mano, que es lo que hizo que se desactualizara cuando
apareció el primer PATCH.

---

### [BAJO] H-11 · `POST /api/positions` acepta un broker que no existe

**Evidencia:** ESTRUCTURAL
**Dónde:** `main.py:8280` (handler), `8205-8258` (`_insert_manual_position`)

**Qué pasa:** `PositionIn.broker` es texto libre (`min_length=1, max_length=MAX_STR`) y el alta
nunca comprueba que exista una fila en `brokers` para ese `(user_id, name)`. El único lookup —
`SELECT currency FROM brokers WHERE user_id=? AND name=?` (8215)— trata el "no existe" como un
default silencioso (`resolved_ccy = "USD"`), no como un error. Contrasta con el mismo handler dos
campos más allá, donde `parent_broker_id` **sí** se valida contra el dueño (4256-4262).

No es un problema de autorización entre usuarios: todo lo que se escribe lleva `user_id=uid` y el
débito de cash (`_adjust_broker_cash`) también. Es integridad: quedan posiciones colgadas de un
broker inexistente, invisibles en una UI que agrupa por el broker actual — el mismo modo de falla
que el comentario de `NAME_KEYED_TABLES` (4117-4127) documenta para el rename. También esquiva la
cuota de brokers del plan Free, que se chequea en `POST /api/brokers` (4058) y no acá.

**Solución de fondo:** validar `(user_id, broker)` contra `brokers` en el alta —o auto-crearlo
pasando por el mismo camino que `POST /api/brokers`, cuota incluida—. Es un síntoma del modelo de
datos que el propio repo ya tiene fichado (brokers linkeados por NOMBRE y no por FK); mientras eso
siga así, cada escritor que acepte un nombre libre es una fuente de huérfanos.

---

### [BAJO] H-12 · Los símbolos `FCI:` de `/api/prices` esquivan el cap `MAX_SYMBOLS`

**Evidencia:** DEDUCIDO
**Dónde:** `main.py:7617-7631` vs `7634-7639`

**Qué pasa:** El handler separa `fci_syms = [s for s in raw if s.startswith("FCI:")]` **antes** de
aplicar el filtro `_SYMBOL_RE` y el `sym_list[:MAX_SYMBOLS]`. El cap —comentado como *"Hard cap to
prevent resource abuse"*— se aplica solo a la rama yfinance/data912; la lista de FCI va entera al
`IN (...)` de `get_prices_detail_for` (`pricing/fci.py:332`). La query está **parametrizada**, así
que no hay inyección; pero un request con miles de `FCI:` genera un `IN` con miles de placeholders,
que en SQLite choca contra el límite de variables (error 500) y en cualquier motor es trabajo
gratis para un request autenticado.

**Solución de fondo:** aplicar el mismo cap a las dos ramas — cortar `raw` una sola vez, antes de
partirlo, que es lo que la intención del comentario ya dice.

---

## Lo que NO pude verificar (dicho explícitamente)

1. **No ejecuté nada contra un backend vivo.** Ninguna severidad de este informe descansa en una
   traza medida; las que dependían de magnitud (H-1, H-2) las argumento con el espacio de búsqueda
   y la clave del contador, que son verificables leyendo dos funciones. Si se quiere una medición,
   la forma honesta es un test que llame `_check_rate_limit` con requests de IPs distintas y el
   mismo email, y verifique que ninguna se bloquea: no requiere levantar la app.
2. **No verifiqué el frontend** en ningún hallazgo. H-7 depende de si la pantalla del perfil de
   inversor es alcanzable con la lente de cliente abierta; queda en `REVISAR` por eso.
3. **No verifiqué la topología real de red** (si Vercel efectivamente proxea server-side, si hay
   uno o varios workers de uvicorn). Lo primero afecta cuánto importa H-10; lo segundo **agrava**
   H-1/H-2, porque `_rate_store` es un dict por proceso.
4. **No verifiqué la base de Postgres real** en H-6, solo el archivo `schema_pg.sql`. Es posible que
   la base viva tenga el constraint (`dberrors.py:51` sugiere que alguna vez existió) y que lo
   perdido sea solo el archivo generado. La comprobación es un `\d users`.
5. **No audité los 31 call sites de `_check_rate_limit` fuera de mi tramo**, solo los listé. Los 17
   con sufijo `:{uid}` tienen el mismo defecto de clave, pero su consecuencia es abuso de cuota y
   cae en otras áreas.
6. **No audité los flujos de invitación/claim del plan asesor** (`main.py:34998-35160`), que reciben
   emails y tokens y son los candidatos naturales a repetir H-3. Están fuera del rango 3094-9102.
7. **Deriva:** no comprobé si estos 44 endpoints cambiaron en los 11 commits que `origin/main` tiene
   por delante de `b74f450f`. Ninguno de mis hallazgos cae en los archivos de la tanda F1
   (`snapshots_job.py`, persister de FX, `reconcile-cash`, `CashFlowIn`, recalc de P&L,
   amortización manual, `SellModal`/`PositionsMobile`), así que **no marco cruce con F1**. El único
   que roza el área es H-5, que toca `POST /api/snapshots` en `main.py` — no `snapshots_job.py`.
