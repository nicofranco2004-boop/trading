## Modelo de datos — núcleo de negocio

Auditoría del schema real de producción (`origin/main`, commit `b74f450f`, 2026-09-05).
Fuente primaria: `backend/main.py`, función `init_db()` (línea 698) y `backend/schema_pg.sql`.
Evidencia secundaria (base de dev vieja): `backend/trading.db`.

Convención: `[V]` = verificado leyendo el código; `[I]` = inferencia mía.

---

### 0. Cómo nace el schema: hay DOS caminos, no uno

`[V]` `init_db()` arranca en `backend/main.py:698` y lo **primero** que hace es bifurcar:

```
backend/main.py:699-707
    if USANDO_PG:
        _init_db_postgres()
        return
```

`USANDO_PG` es simplemente `bool(DATABASE_URL)` (`backend/main.py:423-424`). O sea:

| Motor | Cómo se construye el schema | Dónde |
|---|---|---|
| **SQLite** (sin `DATABASE_URL`) | `CREATE TABLE` condicionales + ~46 migraciones `ALTER TABLE` incrementales, ejecutadas **en cada arranque** | `backend/main.py:708`–`~2700` |
| **Postgres** (con `DATABASE_URL`) | Se aplica el DDL **final** de un archivo, sin historia | `backend/main.py:684-695` → `backend/schema_pg.sql` |

`[V]` `_init_db_postgres()` (`backend/main.py:684-695`) lee `schema_pg.sql`, lo parte por `";\n"` y ejecuta cada sentencia, tragándose sólo `psycopg.errors.DuplicateObject` (las FK, que no tienen `IF NOT EXISTS`).

`[V]` **Consecuencia grande y verificable**: `schema_pg.sql` no tiene NI UN solo `UPDATE` ni `DELETE` (`grep -c "^UPDATE\|^DELETE" backend/schema_pg.sql` → 0). Los **backfills de datos** que viven dentro de las migraciones SQLite **no existen en el camino Postgres**:

- backfill de `positions.currency` (`backend/main.py:980-994`)
- backfill de `positions.asset_type` desde `import_normalized_tx` (`backend/main.py:1004-1029`)
- `_backfill_manual_flows` de `monthly_entries` (`backend/main.py:1097`)
- purga de noticias en inglés (`backend/main.py:1284-1291`)

`[I]` Si la app se migra a Postgres con datos copiados de SQLite, esos backfills ya corrieron en origen y no hacen falta; pero si algún día se crea una base Postgres **nueva** y se importan datos crudos, ninguno de esos arreglos se aplica. El código no tiene ningún guard que lo advierta.

#### El guard `_table_cols` y su allowlist

`[V]` `backend/main.py:576-586`:

```python
def _table_cols(conn, table: str) -> set:
    allowed = {'positions', 'monthly_entries', 'operations', 'config', 'brokers', 'users',
               'snapshots', 'goals', 'import_batches', 'import_raw_rows',
               'import_normalized_tx', 'import_op_links', 'import_mappings', 'news',
               'subscriptions', 'ai_usage_daily', 'ai_user_facts', 'ai_tool_usage',
               'yfinance_cache', 'credit_ledger', 'plazos_fijos', 'user_broker_credentials'}
    if table not in allowed:
        return set()
    ...
```

Casi todas las migraciones incrementales están gateadas por `if cols and 'X' not in cols`. Una tabla **fuera del allowlist** devuelve `set()` → el `if` es falso → **el ALTER nunca corre**. El propio código documenta dos veces que este bug ya explotó en producción:

- `backend/main.py:893-900`: `advisor_op_batch_items` no estaba en la allowlist → las 4 columnas de undo exacto nunca se agregaron en prod → "table advisor_op_batch_items has no column named cost_debited" en cada alta grupal. Fix: `PRAGMA table_info` directo (`backend/main.py:904-910`).
- `backend/main.py:2214-2220`: `advisor_profile.logo_data`, mismo bug.

`[V]` De **mis** tablas, quedan fuera del allowlist: `archived_positions`, `futures_positions`, `watchlist`, `deleted_ops_journal`. Hoy ninguna tiene migraciones `ALTER` gateadas por `_table_cols`, así que la bomba no está armada — pero **la próxima columna que se le agregue a cualquiera de esas cuatro no va a migrar en producción**.

`[V]` Regla de oro repetida 4 veces en el archivo (`main.py:1105-1107`, `1434-1436`, `1568-1571`, `2226-2228`): **primero la columna, después el índice**. Un `CREATE INDEX` sobre columna inexistente tiró prod ~20 minutos el 2026-08-02, porque dentro de un `executescript` un fallo corta el arranque entero.

---

### 1. `users` — la cuenta

**Negocio**: la persona (o la cuenta *shadow* que un asesor crea por su cliente). Concentra identidad, autorización, plan pagado, prueba gratis y las marcas de idempotencia de las campañas de email.

`[V]` DDL base: `backend/main.py:711-722` (10 columnas). Todo lo demás llega por `ALTER TABLE` (`main.py:778-816` y `main.py:2264-2298`). En Postgres la tabla nace completa: `backend/schema_pg.sql:1717-1745`.

| campo | tipo | qué significa en negocio | quién lo escribe | quién lo lee | notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | identidad de la cuenta | SQLite | **todo**: es el `user_id` de las 13 tablas de datos | única FK real del modelo (`brokers.user_id`) |
| `email` | TEXT UNIQUE NOT NULL | login | `POST /api/register` (`main.py:3113`), alta de cliente shadow (`main.py:34396`), claim (`main.py` "SET email=…") | login, emails, admin | UNIQUE → índice implícito |
| `name` | TEXT | nombre a mostrar | register (`main.py:3114`), shadow (label del asesor, `main.py:34399`) | UI, emails, informes del asesor | no hay endpoint de rename propio `[V]` (no aparece ningún `UPDATE users SET name=`) |
| `password_hash` | TEXT NOT NULL | credencial | register, `POST /api/auth/change-password` (`main.py:3579`), reset por token (`main.py:3441`) | login | shadow nace con `token_urlsafe(24)` hasheado → imposible loguear (`main.py:34393`) |
| `is_admin` | INTEGER NOT NULL DEF 0 | admin de Rendi | `init_db` sincroniza por email admin (`main.py:912-917`), register | `quota.get_tier` (`ai/quota.py:207`), gates admin | se re-sincroniza **en cada boot** recorriendo toda la tabla |
| `approved` | INTEGER NOT NULL DEF 0 | ¿puede entrar? | register pone `1` siempre (`main.py:3111`); shadow `0` | login, `quota.get_tier:186` | la migración vieja hizo `UPDATE users SET approved=1` masivo (`main.py:786`) |
| `tier` | TEXT | override explícito del plan: `'pro'|'plus'|'free'|'advisor'|NULL` | admin grant, billing (`billing/subscriptions.py`, `billing/trial.py`) | `ai/quota.py:206-218` | NULL = cae a `is_admin` → `free` |
| `password_changed_at` | TEXT | invalidación de JWT viejos | change-password (`main.py:3579`, `3441`) | `create_token` / validación | es el "pca" del token |
| `last_login_at` | TEXT | último login | login (`main.py:3213`) | panel admin | |
| `created_at` | TEXT | alta | default SQL | métricas de signup | |
| `email_verified` | INTEGER DEF 0 | OTP confirmado | register / verify (`main.py:3112`) | gate de acceso | migración puso `1` a todos los preexistentes (`main.py:793`) |
| `investor_profile` | TEXT (JSON) | 7 respuestas del test de perfil | `POST /api/investor-profile` (`main.py:4004`) | `GET` (`main.py:3977`), system prompt de la IA (`main.py:20871`) | ⚠️ JSON crudo en columna TEXT, sin validación de schema en DB |
| `reengagement_email_sent_at` | TEXT | idempotencia campaña "importá tu historial" | endpoint admin | el mismo endpoint | |
| `gift_plan_email_sent_at` | TEXT | idempotencia campaña "te regalamos un mes" | `/api/admin/email/gift-plus` | ídem | ⚠️ la base de dev tiene **además** `gift_plus_email_sent_at`, columna que **no existe en el código actual** — huérfana de una versión anterior |
| `trial_invite_email_sent_at` | TEXT | anti-repetición del sorteo de tandas de 50 | campaña admin | campaña admin | |
| `pro_trial_until` | TEXT | prueba de Pro **encima** de un plan pago | `billing/trial.py` | `ai/quota.py:199-204` (en tiempo real) | vence sola, sin cron |
| `pro_trial_used_at` | TEXT | una vez por cuenta, para siempre | `billing/trial.py` | ídem | |
| `managed_by` | INTEGER | `users.id` del asesor dueño de la cuenta shadow | alta de cliente (`main.py:34397`) | `quota.get_tier:187` (shadow sin reclamar ⇒ 'pro'), exclusión de campañas | ⚠️ **NO es una FK declarada**: `INTEGER` pelado (`main.py:816`), y en PG `managed_by bigint` sin constraint |
| `credit_active_until` | TEXT | hasta cuándo mantiene tier ≠ free | `billing/credits.py:246` | `quota.get_tier:213`, cron de expiración (`billing/subscriptions.py:176-180`) | el modelo de proration es "ventana de tiempo", no plata |
| `credit_anchor_plan` / `_period` / `_amount_usd` / `_at` | TEXT/TEXT/REAL/TEXT | de qué plan salió la ventana de crédito | `billing/credits.py:246-247,378-379` | `billing/credits.py:85-108` | |
| `trial_started_at` / `trial_used_at` / `trial_ends_at` | TEXT | free trial de 15 días (7 Pro + 8 Plus) | `billing/trial.py` | cron de bajada Pro→Plus | `trial_ends_at` existe para saber **cuál** crédito es el del trial (`main.py:2286-2289`) |
| `quota_window_from` | TEXT | desde qué día cuenta la cuota del plan actual | `ai/quota.py` (`note_tier_change`), grants admin | `ai/quota.py` | evita que el consumo del techo Pro se le descuente al techo Plus |

**Claves / índices**: PK `id`; `UNIQUE(email)`. `[V]` **No hay ningún otro índice** sobre `users` en `init_db` ni en `schema_pg.sql`. Los comentarios lo justifican explícitamente ("la tabla es chica", `main.py:806`).

**Duplicación de la verdad del trial** `[V]`: `trial_used_at` vive en `users`, pero además existe `trial_consumed(email_key, consumed_at)` (`main.py:2303-2308`) porque borrar la cuenta borraba `trial_used_at` y habilitaba trials infinitos con el mismo mail. O sea: la marca canónica de "este mail ya usó su prueba" **no está en `users`**.

---

### 2. `brokers` — la cuenta del broker (y el sub-broker `· USD`)

**Negocio**: cada lugar donde el usuario tiene plata. Un broker argentino que opera en las dos monedas se representa con **dos filas**: el padre (ARS) y un hijo `"<Padre> · USD"`.

`[V]` DDL: `backend/main.py:723-730`.

```sql
CREATE TABLE IF NOT EXISTS brokers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USDT',
    parent_broker_id INTEGER REFERENCES brokers(id) ON DELETE CASCADE,
    UNIQUE(user_id, name)
);
```

| campo | tipo | qué significa en negocio | quién lo escribe | quién lo lee | notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK | identidad de la cuenta-broker | SQLite | `parent_broker_id`, `brokerAccounts.js` (key de la cuenta) | |
| `user_id` | INTEGER NOT NULL FK→users | dueño | todos los INSERT | todos | **la única FK a `users` de todo el modelo** |
| `name` | TEXT NOT NULL | el nombre que ve el usuario, y **la clave foránea de facto** de 6 tablas | `POST /api/brokers` (`main.py:4092`), `_ensure_usd_sibling` (`main.py:10810`), rename (`main.py:4282`) | TODO el sistema, siempre por string | ⚠️ ver "relaciones por nombre" abajo |
| `currency` | TEXT NOT NULL DEF `'USDT'` | moneda operativa: `'ARS'`, `'USD'`, `'USDT'` | alta / PUT | valuación (`snapshots_job.compute_broker_value_usd`), `behavioral.byma_broker_names:247`, FIFO | ⚠️ `'USDT'` se usa como *bucket* genérico "dólar" también para brokers tradfi — el comentario lo llama "plumbing interno" (`main.py:10781-10787`) |
| `parent_broker_id` | INTEGER FK→brokers ON DELETE CASCADE | apunta al padre si esta fila es el sub-broker en dólares | `_ensure_usd_sibling` (`main.py:10803`, `10810`), `POST /api/brokers` si el cliente lo manda (`main.py:4092`) | `broker_pair` (`importing/persister.py:99`), `plan.count_broker_accounts` (`ai/plan.py:170`), `byma_broker_names`, `_broker_name_sets` (`snapshots_job.py:68`), `brokerAccounts.js` | ⚠️ **la acción `ON DELETE CASCADE` sólo existe en bases nuevas** — ver abajo |

#### Padre / sub-broker: cómo funciona de verdad

`[V]` **Creación**: `_ensure_usd_sibling` (`backend/main.py:10776-10815`). Busca un hijo con `parent_broker_id=padre AND currency='USDT'`; si no existe, arma el nombre `f"{parent_name} · USD"` (separador U+00B7) y lo inserta con `currency='USDT'`. Si ya existía un broker suelto con ese nombre, lo **adopta** (`UPDATE brokers SET parent_broker_id=?, currency='USDT'`, `main.py:10803`).

`[V]` **El par es la SSoT del FIFO**: `broker_pair(conn, uid, broker)` (`backend/importing/persister.py:99-125`) devuelve los nombres de las dos patas. Existe porque el mismo activo comprado en pesos y vendido por dólar-MEP queda **partido** entre padre e hijo; el FIFO consume lotes de **ambos** para que el neteo dé bien. Hay 25+ call sites (`main.py:8442, 8537, 11178, 14514, 14658, 14783, 14850, 24133, 29907, 30127, 31143`, `reporting/builder.py:128`, …).

`[V]` **La cuota de plan cuenta CUENTAS, no filas**: `ai/plan.py:151-179` cuenta `parent_broker_id IS NULL` **más los huérfanos** (hijos cuyo padre ya no existe), porque el sibling "nace sin pasar por la cuota" y contarlo le comía un cupo pago.

`[V]` **La UI agrupa por FK, nunca por sufijo**: `frontend/src/utils/brokerAccounts.js:14-18` — *"El par se arma SIEMPRE por `parent_broker_id`, NUNCA parseando el sufijo"*, porque un renombre degrada el parseo en silencio.

`[V]` **Pero la resolución de PRECIO sí mira el nombre**: `snapshots_job._is_ar_usd_subbroker` (`backend/snapshots_job.py:57-65`) usa la regex `·\s*usd$`. Es un **fallback declarado** para datos viejos sin `parent_broker_id` (`snapshots_job.py:75-76`), y convive con la vía parent-aware en `_broker_name_sets` (`snapshots_job.py:68-84`) y `behavioral.byma_broker_names` (`backend/behavioral.py:247-268`). O sea: hay **dos criterios distintos** para "¿esto es un sub-broker USD argentino?", uno estricto por nombre y otro robusto por FK, y el código documenta que son a propósito distintos (`snapshots_job.py:61-65`).

`[V]` **Renombrar**: `PUT /api/brokers/{bid}` (`main.py:4137`). Reglas reales:
- renombrar un **sibling** directamente → 400 `sibling_rename_forbidden` (`main.py:4172-4179`);
- el nombre nuevo del sibling se **deriva fresco** de `f"{new_name} · USD"`, nunca por `str.replace` del prefijo (`main.py:4213`);
- `'global'` es nombre **reservado** → 409 (`main.py:4184-4195`), porque es la clave del agregado cross-broker en `monthly_entries`;
- colisión de nombre → 409, **nunca merge** (`main.py:4226-4249`);
- todo el cascade va en **una** transacción (`main.py:4295-4300`).

`[V]` **Borrar**: `DELETE /api/brokers/{bid}` (`main.py:4339`). Sin `?force=true`, si hay data → 409 con los conteos. Con force borra `operations`/`positions`/`monthly_entries` de **padre + todos los hijos** (`broker IN (...)`, `main.py:4452-4466`) y marca los `import_batches` como `reverted`.

⚠️ **El hallazgo más importante de esta tabla, y está documentado en el propio código** (`main.py:4476-4487`):

> el schema de `brokers` existe en DOS formas y sólo una tiene el cascade. El `CREATE TABLE` (bases nuevas) declara `parent_broker_id ... ON DELETE CASCADE`, pero la migración lo agrega por `ALTER TABLE ADD COLUMN` (`main.py:774`) y **SQLite no admite acción referencial en un ADD COLUMN** → toda base preexistente, o sea **producción**, tiene la FK sin cascade.

Verificado contra la base de dev: `sqlite3 backend/trading.db ".schema brokers"` devuelve `parent_broker_id INTEGER REFERENCES brokers(id)` — **sin** `ON DELETE CASCADE`. Por eso el `DELETE` de los hijos es explícito (`main.py:4488`) antes del padre. En Postgres el constraint sí se declara aparte y sí cascadea (`schema_pg.sql:2017`).

⚠️ **`delete_broker` NO limpia todo**: el comentario en `main.py:4123-4126` lo dice — no toca `import_normalized_tx` ni `bond_cashflow_skips` ("orphan gap conocido"). Tampoco `deleted_ops_journal.broker`, ni `snapshots` (los purga aparte por fecha), ni `futures_positions.broker`, ni `archived_positions` (que guarda `positions` serializadas con su `broker` adentro del JSON).

**Índices**: sólo el implícito de `UNIQUE(user_id, name)`. `[I]` Alcanza para los lookups por `(uid, name)` y por `uid`, que son los dos patrones reales; pero `WHERE user_id=? AND parent_broker_id=?` (`main.py:4215`, `4382`, `4488`) no tiene índice propio — irrelevante por el tamaño de la tabla.

---

### 3. `positions` — el LOTE (no "la tenencia")

**Negocio**: cada fila es **un lote de compra** (o el saldo de efectivo de un broker). El FIFO consume lotes; no hay una fila "tenencia consolidada" en ningún lado — la consolidación es siempre en query time.

#### Las dos variantes del CREATE

`[V]` `backend/main.py:920-957`:

- **Rama A — base nueva** (`if not cols:`, línea 921): `CREATE TABLE positions (...)` con 11 columnas (`main.py:923-935`).
- **Rama B — base pre-multi-tenancy** (`elif 'user_id' not in cols:`, línea 937): `RENAME TO positions_old` → `CREATE TABLE positions` idéntica → `INSERT ... SELECT id, 0, ...` (todos caen en `user_id=0`) → `DROP TABLE positions_old` (`main.py:938-957`).
- **Rama C implícita**: la tabla ya existe con `user_id` → no se toca, y sólo corren los `ALTER` de abajo.

`[V]` Las columnas 12 a 17 llegan **siempre** por `ALTER`, incluso en base nueva (donde son no-op porque `_table_cols` se re-lee):

| columna | línea del ALTER | comentario |
|---|---|---|
| `entry_date` | `main.py:960-961` | |
| `commissions` | `main.py:963-965` | `REAL DEFAULT 0` |
| `currency` | `main.py:971-973` | + **backfill** en `main.py:980-994` |
| `asset_type` | `main.py:1001-1003` | + backfill desde `import_normalized_tx` (`main.py:1004-1029`) |
| `split_adjusted_through` | `main.py:1035-1037` | |
| `undo_meta_json` | `main.py:1175-1178` | loop compartido con `operations` |

⚠️ **El backfill de `currency` corre en CADA arranque, para TODOS los usuarios** (`main.py:980-994`). No está adentro del `if ... not in cols` — es un `try/except: pass` suelto. Es un `UPDATE positions SET currency = CASE ... WHERE currency IS NULL OR currency = ''` con una subquery correlacionada a `brokers` **por nombre**. Consecuencias reales:
1. Cualquier lote que se cree con `currency` NULL (varios INSERT manuales no la setean: `main.py:4102`, `9782`, `10078`, `10170`) queda **reclasificado en el próximo reboot** según la moneda del broker, no según cómo se compró.
2. Si falla (p. ej. sintaxis distinta en Postgres) se traga la excepción en silencio — aunque en el camino PG ni siquiera se llega acá.

#### Campos

| campo | tipo | qué significa en negocio | quién lo escribe | quién lo lee | notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | identidad del lote | SQLite | `import_op_links.position_id`, `advisor_op_batch_items.position_id`, undo | `/api/sections/restore` **re-inserta con el id original** (`main.py:31873`) |
| `user_id` | INTEGER NOT NULL DEF 0 | dueño | todos | todos | ⚠️ **sin FK a `users`**, ni en SQLite ni en PG (`schema_pg.sql:1431`) |
| `broker` | TEXT NOT NULL | a qué cuenta pertenece — **por nombre** | todos | todos | ⚠️ ver §14 |
| `asset` | TEXT NOT NULL | ticker o token de cash (`ARS`/`USDT`/`USD`) | todos | todos | también es el discriminador de moneda del cash |
| `is_cash` | INTEGER DEF 0 | 1 = fila de **saldo**, 0 = lote de activo | alta de broker (`main.py:4102`), `_adjust_cash` | toda la valuación; `WHERE is_cash=0` aparece en decenas de queries | el saldo se guarda en `invested` (no en `quantity`) |
| `buy_price` | REAL | precio unitario de compra, en la moneda del lote | compras | UI, P&L | NULL en filas de cash |
| `quantity` | REAL | nominales del lote | compras, FIFO parcial, amortizaciones | valuación, FIFO | ⚠️ para cash queda 0/NULL — el saldo NO está acá |
| `invested` | REAL | **costo bruto** del lote (sin fees) en la moneda del lote; **y el SALDO cuando `is_cash=1`** | `_persist_buy` = `tx.gross_amount` (`importing/persister.py:567`); `_adjust_cash` para cash (`persister.py:1033`, `1041`) | absolutamente todo | ⚠️ **una columna, dos significados** según `is_cash` |
| `tc_compra` | REAL | TC ARS/USD del día de la compra | parser si lo trae, si no `_tc_for_date` (`persister.py:581-583`); `fx_migrate.py:442` | vista "costo en dólares al dólar de la compra" | sólo 6 de 18 parsers lo emiten `[V]` (`persister.py:578-579`) |
| `price_override` | REAL | precio fijado a mano / por una foto de tenencia (FCI) | fotos de tenencia, `recompute_backfill.py:340` | valuación (gana sobre el precio de mercado) | se limpia al revertir el batch que lo fijó (`main.py:31917`) |
| `notes` | TEXT | texto libre | import, alta manual | ⚠️ **no encontré ningún lector que lo muestre en el frontend** (`grep "\.notes" frontend/src/pages/Cartera.jsx` → sin resultados) | `[I]` sirve sobre todo para trazabilidad interna |
| `entry_date` | TEXT (`YYYY-MM-DD`) | fecha de compra → **el orden del FIFO** | import, alta manual | `ORDER BY COALESCE(entry_date,'9999-12-31') ASC, id ASC` en `main.py:8315, 10563, 10611, 11184, 14118`, `persister.py:657, 699`, `maturity.py:351` | ⚠️ es **fecha sin hora**: los lotes del mismo día desempatan por `id`, o sea por orden de inserción |
| `commissions` | REAL DEF 0 | fees de compra (suman al costo real) | import, recompute | `real_cost = invested + commissions` (`snapshots_job.py:208`) | |
| `currency` | TEXT | moneda **en la que está expresado `invested`** (`'ARS'`/`'USD'`) | `_persist_buy` (`persister.py:584-591`), backfill de boot | FIFO cross-currency, `_cost_in_usd` (`snapshots_job.py:199-204`) | `'USDT'` se normaliza a `'USD'` al persistir (`persister.py:573-574`) |
| `asset_type` | TEXT | `CEDEAR`/`STOCK`/`ETF`/`BOND`/`FUND`/`OTHER`… | import; `recompute_backfill.py:279` fuerza `'BOND'` | decide si se cotiza por `.BA` o por el ticker US (diferencia de 15-100×) | ⚠️ hay filas reales con valores en **minúscula** (`frontend/src/utils/assetClass.test.js:114`) |
| `split_adjusted_through` | TEXT (`YYYY-MM-DD`) | watermark de la última ex-date de split ya aplicada a **este** lote | motor de splits | el mismo motor | "load-bearing": sin esto un 10:1 se aplicaría dos veces = 100× (`main.py:1032-1034`) |
| `undo_meta_json` | TEXT (JSON) | de qué camino salió la fila y todo lo necesario para deshacerla | `main.py:8266` (`src:"manual_position"`), `14056`, `17731` | `_delete_manual_position_cascade` | `src` conocidos: `manual_position` |

**Claves / índices**: PK `id`. **Un solo índice**: `idx_positions_user ON positions(user_id)` (`main.py:1220`).
⚠️ `[I]` El patrón de query dominante es `WHERE user_id=? AND broker=? AND asset=? AND is_cash=0` (188 lecturas de `FROM positions` en backend, sin contar tests/scripts). Con sólo `user_id` indexado, cada una de esas queries escanea todas las filas del usuario. No es catastrófico por el tamaño típico, pero es la asimetría más visible del schema: `operations` sí tiene índice compuesto y `positions` no.

**Sin FK**: `user_id` no referencia `users`; `broker` no referencia `brokers`. Ni en SQLite ni en `schema_pg.sql:1431-1448`.

---

### 4. `archived_positions` — el borrado reversible de una sección

**Negocio**: cuando el usuario "elimina" una sección de renta fija que importó mal (ej. *Bonos USD*), no se hace hard-delete: las `positions` se serializan a JSON y se sacan de la tabla, así desaparecen de **todas** las superficies sin filtrar query por query.

`[V]` DDL: `backend/main.py:1585-1595`.

| campo | tipo | qué significa en negocio | quién lo escribe | quién lo lee | notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK | identidad del archivo | SQLite | `POST /api/sections/restore` (`main.py:31862`) | |
| `user_id` | INTEGER NOT NULL | dueño | `main.py:31835` | `main.py:31806`, `31862` | sin FK |
| `section` | TEXT NOT NULL | clave de la sección, formato `'BONO|USD'` | `sections.section_key(cat, ccy)` (`main.py:31834`) | listado | el parseo vive en `backend/importing/sections.py` |
| `label` | TEXT | etiqueta legible ("Bonos USD") | `sections.section_label` | UI y respuesta del restore | |
| `payload` | TEXT NOT NULL | **JSON con las filas completas de `positions`** (`json.dumps([dict(r) for r in matched])`) | `main.py:31833` | restore (`main.py:31866-31874`) | ⚠️ snapshot **estructural**: si `positions` gana una columna después del archivado, el restore la inserta sin ella |
| `count` | INTEGER NOT NULL DEF 0 | cuántas filas se archivaron | `main.py:31837` | UI | dato derivado, redundante con `payload` |
| `archived_at` | TEXT DEF `datetime('now')` | cuándo | default | orden `DESC` del listado | |

**Índices**: `idx_archpos_user ON archived_positions(user_id)` (`main.py:1594`).

⚠️ `[V]` El restore re-inserta con el **`id` original** (`main.py:31871-31874`, `INSERT INTO positions ({cols})` donde `cols` incluye `id`) para no romper los `import_op_links`. `[I]` Funciona porque `positions.id` es `AUTOINCREMENT` (SQLite no reusa ids liberados). En Postgres, `id bigint GENERATED BY DEFAULT AS IDENTITY` (`schema_pg.sql:1432`) **acepta** el id explícito pero **no adelanta la secuencia** → un INSERT posterior sin id podría chocar. No encontré ningún `setval` ni manejo de esto en el código.

⚠️ `[V]` `archived_positions` NO está en el allowlist de `_table_cols`, y **sí** está en `_RESET_PORTFOLIO_TABLES` (`main.py:3607`) — o sea, "Empezar de cero" borra los archivos sin restaurarlos.

---

### 5. `operations` — el EVENTO cerrado (venta, cupón, dividendo, futuro…)

**Negocio**: cada fila es un hecho consumado que genera resultado o efectivo. Es la fuente de `monthly_entries.pnl_realized` y de todas las métricas de "P&L realizado".

#### Las dos variantes del CREATE

`[V]` `backend/main.py:1115-1152`, exactamente el mismo patrón que `positions`:
- **Rama A — base nueva** (`if not cols:`, línea 1116): `CREATE TABLE operations` con 11 columnas (`main.py:1118-1130`).
- **Rama B — base pre-multi-tenancy** (`elif 'user_id' not in cols:`, línea 1132): rename → recreate → `INSERT ... SELECT id, 0, ...` → drop (`main.py:1133-1152`).

`ALTER` posteriores: `entry_date` (`main.py:1153-1155`), `commissions` (`1157-1159`), `notes` (`1162-1164`), `undo_meta_json` (`1175-1178`), `currency` (`1189-1191`), `fx_to_usd` (`1192-1193`), `cost_basis_consumed` (`1201-1203`).

| campo | tipo | qué significa en negocio | quién lo escribe | quién lo lee | notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK | identidad del evento | SQLite | `import_op_links.operation_id`, undo | |
| `user_id` | INTEGER NOT NULL DEF 0 | dueño | todos | todos | sin FK |
| `date` | TEXT NOT NULL | fecha del evento | todos | agregación mensual, orden, reportes | ⚠️ **string sin formato garantizado**: `_recalc` filtra con `date LIKE '____-__-__%'` porque hay filas mal formadas que en Postgres tiran error en el `CAST` (`main.py:9455-9463`) |
| `broker` | TEXT NOT NULL | dónde pasó — **por nombre** | todos | todos | ver §14 |
| `asset` | TEXT NOT NULL | ticker | todos | todos | |
| `op_type` | TEXT | **el tipo de evento** — string libre, no enum | `main.py:9317, 10479, 10959, 11312, 12352, 13854, 15109`; `persister.py:818, 881, 982, 1180`; `rebuild.py:759` | `realized_pnl.py`, reportes, IA | ⚠️ ver abajo |
| `entry_price` | REAL | precio de entrada | ventas FIFO, alta manual | diagnósticos de escala (`main.py:11576`) | ⚠️ en ventas cruzadas entry y exit pueden estar en **monedas distintas** en la misma fila (backlog conocido) |
| `exit_price` | REAL | precio de salida | ídem | ídem | |
| `quantity` | REAL | nominales | ídem | ídem | |
| `pnl_usd` | REAL DEF 0 | **el número más peligroso del schema** | todos | dashboards, reportes, IA, win-rate | ⚠️ ver abajo |
| `pnl_pct` | REAL | % de resultado guardado | `main.py:10957`, `11301`, `13854` | 💀-casi: sólo el **diagnóstico admin** de escala lo lee (`main.py:11611, 11639-11654, 11717-11720`). `grep pnl_pct frontend/src` → sólo tests | se devuelve por `SELECT *` en `GET /api/operations` (`main.py:12384`) pero ningún componente lo usa |
| `entry_date` | TEXT | fecha de la compra que se cerró | ventas | UI de holding period | |
| `commissions` | REAL DEF 0 | fees de venta | import, manual | neto recibido | |
| `notes` | TEXT | texto libre + **marcador de sub-tipo** | cobranzas de bonos (`main.py:10484`), import | `/api/movements` excluye "cobranzas de bonos (sub-tipo de `operations.notes` con kind `_bond_*`)" (`main.py:12420-12421`); `maturity.py:326` filtra `notes LIKE 'Tenencia — apertura%'` | ⚠️ **campo libre usado como discriminador** |
| `undo_meta_json` | TEXT (JSON) | de qué camino salió la fila y cómo deshacerla | `main.py:10485` (`bond_cashflow`), `11336` (`fifo_sell`), `12358`/`13850` (`manual_futures`), `13851` (`manual_form`) | `DELETE /api/operations/{oid}` despacha por `meta["src"]` (`main.py:14001`) | sin esto, borrar una venta hecha con el botón "Vender" es indistinguible de borrar una tipeada a mano → saldo inflado |
| `currency` | TEXT | moneda **nativa** del flujo (`ARS`/`USD`/`USDT`) | `_resolve_op_currency` (`main.py:13806`, usado en `13834`), bond_cashflow (`main.py:10484`) | `realized_pnl.realized_usd_sql` (`realized_pnl.py:97-107`) | desde 2026-08-15 |
| `fx_to_usd` | REAL | factor nativa→USD **al momento del evento** | bond_cashflow (`main.py:10412-10420`), ventas | `realized_pnl.py:102-106` | ⚠️ en `Venta` **no es un factor**: guarda el `tc_venta` (`realized_pnl.py:23-25`) — mismo nombre, otro significado |
| `cost_basis_consumed` | REAL | costo consumido por una amortización | `main.py:10484` | 💀 **el propio código dice que está 100% NULL en las filas reales**: `frontend/src/utils/assetPnl.js:18`, `frontend/src/utils/bookComposition.js:210`, `main.py:37436` | escrito por un solo camino, descartado por todos los lectores |

#### `op_type`: un enum que no es enum

`[V]` No hay CHECK ni tabla de referencia. Los valores que aparecen en el código: `'Compra'`, `'Venta'`, `'Dividendo'`, `'Futuros'`, `'LONG'`, `'Cupón'`/`'Cupon'`, `'Amortización'`/`'Amortizacion'`, `'Renta'`, `'Interés'`, `'Interés PF'`, `''`, y prefijos `'CONVERSION%'`/`'Conversión%'` (`backend/realized_pnl.py:74, 78, 95, 111`; `main.py:14528, 14666, 14889`).
⚠️ Las variantes **con y sin acento conviven** y los filtros las listan a mano: `op_type IN ('Cupón','Cupon','Amortización','Amortizacion','Renta')` (`main.py:14528`). Cualquier lector nuevo que se olvide de una variante cuenta de menos.

#### `pnl_usd`: la columna que **no siempre está en USD**

`[V]` Está documentado en el encabezado de `backend/realized_pnl.py:9-15`:

> La columna se llama `pnl_usd`, pero en las cobranzas de renta fija NO guarda USD: guarda el monto en la MONEDA DEL BROKER (`bond_cashflow` inserta `net_amount` tal cual).

`[V]` El criterio único vive en `realized_pnl.py`; sólo divide cuando `op_type IN ('Cupón','Amortización') AND currency='ARS' AND fx_to_usd > 0` (`realized_pnl.py:97-107`). Y el módulo declara **tres pendientes abiertos**:

1. `realized_pnl.py:35-53` — el **win rate cuenta los cupones como operaciones ganadas** (la lista de afectados la enumera el propio módulo en `realized_pnl.py:47-51`: `reporting/timeline.py:61` `_compute_user_historical_win_rate`, `behavioral.py`, `reporting/builder.py`, `ai/builders/reports.py`).
2. `realized_pnl.py:55-61` — **398 filas viejas** sin `fx_to_usd` siguen infladas en el dashboard; no se convierten porque ~125 de las 276 marcadas ARS ya vienen en dólares y convertirlas todas las haría 1250× más chicas.
3. `realized_pnl.py:63-71` — `'Interés PF'` guarda moneda nativa igual que un cupón y **no está excluido** de `closed_filter_sql` ni se convierte. Hoy 0 filas en producción; el primer plazo fijo en pesos que alguien cobre entra inflado en los 4 lectores.

**Índices**: `idx_operations_user_date ON operations(user_id, date DESC)` (`main.py:1221`) — compuesto a propósito, para eliminar el sort (`main.py:1211-1215`).

---

### 6. `monthly_entries` — la contabilidad mensual por broker

**Negocio**: una fila por `(usuario, año, mes, broker)` con los flujos y el resultado del mes. Es el **capital aportado** y la cadena `capital_inicio → capital_final` sobre la que se mide el rendimiento.

#### Las dos variantes del CREATE

`[V]` `backend/main.py:1041-1080`, mismo patrón:
- **Rama A — base nueva** (`if not cols:`, línea 1042): `CREATE TABLE monthly_entries` con 11 columnas + `UNIQUE(user_id, year, month, broker)` (`main.py:1044-1058`).
- **Rama B — pre-multi-tenancy** (`elif 'user_id' not in cols:`, línea 1059): rename → recreate → copy → drop (`main.py:1060-1080`).

`ALTER`: `manual_deposits` + `manual_withdrawals` con **backfill one-time** `_backfill_manual_flows` (`main.py:1092-1100`); `manual_deposits_native` + `manual_withdrawals_native` (`main.py:1108-1112`).

| campo | tipo | qué significa en negocio | quién lo escribe | quién lo lee | notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK | | SQLite | `/api/movements` (`me-{id}`) | |
| `user_id` | INTEGER NOT NULL DEF 0 | dueño | todos | todos | sin FK |
| `year` / `month` | INTEGER NOT NULL | período | todos | todos | ⚠️ enteros, no un `YYYY-MM` |
| `broker` | TEXT NOT NULL | broker **o el pseudo-broker `'global'`** | `_update_monthly_flow` (`main.py:9918`), `_recalc` (`main.py:9484`), rebuild | todos | ver abajo |
| `deposits` | REAL DEF 0 | aportes del mes, **en USD** | `_update_monthly_flow:9949`; **pisado** por `_recalc` (`main.py:9590-9596`) | capital aportado, `compute_net_deposited` | fórmula autoritativa: `imports_confirmados + manual_deposits` |
| `withdrawals` | REAL DEF 0 | retiros del mes, en USD | ídem | ídem | |
| `pnl_realized` | REAL DEF 0 | resultado realizado del mes | `_update_monthly_pnl_realized`; **pisado** por `_recalc` con `SUM(operations.pnl_usd)` | dashboard, reportes, wrapped | cache derivado, no fuente |
| `pnl_unrealized` | REAL DEF 0 | no realizado **sólo del mes en curso** | `POST /api/monthly/sync-unrealized` (`main.py:11038`, escribe en `11066`, `11082`, `11481`) | `wrapped.py:144`, `reporting/builder.py:692, 894, 1118, 1130`, `frontend/src/utils/diagnostics.js:754` | ⚠️ `_recalc` lo **fuerza a 0** en cada corrida (`main.py:9592`) y `_repair_monthly_chain` lo zeroa en todo mes cerrado (`main.py:9666`) |
| `capital_inicio` | REAL DEF 0 | capital al abrir el mes | `_repair_monthly_chain` (`main.py:9741`) | baseline de `compute_net_deposited` (`snapshots_job.py:400`) | invariante: `capital_inicio[N+1] = capital_final[N]` |
| `capital_final` | REAL DEF 0 | capital al cerrar el mes | `_update_monthly_flow` (suma/resta el flujo, `main.py:9949`), `_repair_monthly_chain` | curva de capital, TWR | fórmula en meses cerrados: `inicio + deposits − withdrawals + pnl_realized` (`main.py:9667`) |
| `manual_deposits` | REAL DEF 0 | **sólo** los aportes cargados a mano | `_update_monthly_flow(..., is_manual=True)` (`main.py:9952`) | `_recalc` como fuente autoritativa (`main.py:9582-9584`) | nació porque la heurística `existing − imports` dejaba huérfanos y fabricaba capital (`main.py:1084-1091`) |
| `manual_withdrawals` | REAL DEF 0 | ídem retiros | ídem | ídem | |
| `manual_deposits_native` | REAL DEF 0 | el mismo flujo **en la moneda del broker** | `_update_monthly_flow` sólo si el caller lo pasa (`main.py:9955-9957`) | borrado exacto de un depósito en pesos (`main.py:13079`) | NULL/0 en filas viejas → el borrado cae al aproximado |
| `manual_withdrawals_native` | REAL DEF 0 | ídem | ídem | ídem | |

#### El pseudo-broker `'global'`

`[V]` `'global'` **no es un broker**: es la clave del agregado cross-broker dentro de la misma tabla (`main.py:4182`, `9424`). Cada flujo manual se escribe **dos veces**: en el broker real y en `'global'` (`main.py:9867`, `10104`, `10203`, `10979`, `11395`). Por eso renombrar un broker a `'global'` está prohibido con 409 (`main.py:4184-4195`).

⚠️ `[V]` La fila `'global'` **driftaba**: no se decrementaba al borrar un broker → capital aportado fantasma. El fix fue recomputarla como `Σ(per-broker)` con `WHERE broker!='global'` (`main.py:9557-9571`) y re-sincronizar sus `manual_*` (`main.py:9600-9605`).

**Índices**: `UNIQUE(user_id, year, month, broker)` + `idx_monthly_user_period ON monthly_entries(user_id, year, month)` (`main.py:1222`).

**Unidad**: todo en USD (convención global del motor, `persister.py:1047-1048`), **salvo** `manual_*_native`.

---

### 7. `snapshots` — la foto diaria de la cartera

**Negocio**: el valor total del portafolio a una fecha. Es el eje de todas las curvas, del TWR y del benchmark.

`[V]` DDL: `backend/main.py:1368-1385`. Nace con **6 columnas** (`id, user_id, date, total_value, total_invested, source`) + `UNIQUE(user_id, date)`; las otras 6 llegan por `ALTER`.

| campo | tipo | qué significa en negocio | quién lo escribe | quién lo lee | notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK | | SQLite | `twr.estampar_base` (`twr.py:1205`) | |
| `user_id` | INTEGER NOT NULL | dueño | todos | todos | sin FK |
| `date` | TEXT NOT NULL (`YYYY-MM-DD`) | día de la foto | todos | todos | `UNIQUE(user_id, date)` → **una foto por día** |
| `total_value` | REAL NOT NULL | valor de mercado total en USD | cron (`snapshots_job.py:778`), browser (`main.py:5072`), import (`persister.py:1292`), backfill MtM (`scripts/backfill_historical_mtm.py:414`) | ~70 lecturas `FROM snapshots` en backend | |
| `total_invested` | REAL NOT NULL | **costo** total (Σ `invested`+`commissions` en USD) | `snapshots_job.py:747-754` | fallback legacy cuando `net_deposited=0` | no es el capital aportado |
| `source` | TEXT | **quién escribió la fila**: `'cron'` \| `'browser'` \| `'import'` \| `'mtm_backfill'` | cada escritor se estampa a sí mismo | `twr.clasificar_fila` (`twr.py:185-199`) | ⚠️ NULL en filas viejas → cae a heurística |
| `net_deposited` | REAL NOT NULL DEF 0 | capital aportado neto al cierre del día | cron (`snapshots_job.py:788`), `main.py:12946`, `15578` | Total Return = `value − net_deposited` | `ALTER` en `main.py:1394` |
| `fx_to_usd_blue` | REAL | el dólar **de esa fecha**, estampado | cron, browser (`main.py:5060-5079`) | la curva en pesos usa el TC histórico, no el de hoy | `ALTER` en `main.py:1402` |
| `holdings_json` | REAL→TEXT (JSON) | foto por activo: `[{asset, value_usd}]` | **sólo el cron** (`snapshots_job.py:758-762`) | atribución MtM por período (mejor/peor holding) | `ALTER` en `main.py:1408`; NULL en legacy |
| `mtm_coverage` | REAL | qué fracción del valor no-cash se pudo valuar a precio real | **sólo** `source='mtm_backfill'` (`scripts/backfill_historical_mtm.py`) | `twr.clasificar_fila` (`twr.py:193-197`), umbral `COBERTURA_MEDICION = 0.90` (`twr.py:127`) | NULL cuando la escribió el cron |
| `base` | TEXT | con qué **regla** se valuó la fila: `'mercado'` \| `'costo'` | cron/browser/import al insertar; `twr.estampar_base` (`twr.py:1205`) para las viejas | los ~40 lectores de `snapshots` | `ALTER` en `main.py:1438` |
| `apto` | INTEGER | ¿puede ser **pico y denominador**? 0/1 | ídem | ídem + la vista | `ALTER` en `main.py:1440` |

#### Quién estampa qué

`[V]`

| escritor | `source` | `base` | `apto` | dónde |
|---|---|---|---|---|
| cron de cierre | `'cron'` | `'mercado'` | `1` | `snapshots_job.py:777-791` |
| foto del browser (Dashboard) | `'browser'` | `'mercado'` | `0` | `main.py:5069-5083` |
| import | `'import'` | (costo) | 0 | `persister.py:1292` |
| backfill histórico MtM | `'mtm_backfill'` | según cobertura | | `scripts/backfill_historical_mtm.py:414` |

`[V]` **Regla dura**: *un cierre del cron no se pisa* (`main.py:5045-5056`). Si ya hay `source='cron'` para ese día, la foto del browser sólo actualiza `net_deposited` y `fx_to_usd_blue`, nunca el valor. Al revés, el cron **sí** pisa una foto del browser (`snapshots_job.py:786-789`).

#### La vista `snapshots_medibles`

`[V]` `main.py:1442-1470`. Se crea condicionada a que `base` **y** `apto` existan, siempre **después** del `CREATE INDEX idx_snapshots_apto` (`main.py:1443-1444`). Se hace `DROP VIEW IF EXISTS` + `CREATE VIEW` en **cada arranque** (`main.py:1459-1461`).

```sql
CREATE VIEW snapshots_medibles AS
SELECT * FROM snapshots
 WHERE CASE
         WHEN apto IS NOT NULL THEN apto
         WHEN source = 'import'  THEN 0
         WHEN source = 'browser' THEN 0
         WHEN source = 'mtm_backfill'
              THEN (CASE WHEN COALESCE(mtm_coverage,-1) >= 0.90 THEN 1 ELSE 0 END)
         ELSE 1
       END = 1
```

El `COALESCE` es deliberado: `WHERE apto = 1` a secas dejaría fuera toda la base hasta que la migración termine de estampar (`main.py:1449-1457`). Lectores: `main.py:18024`, `37162`. En PG la vista está en `schema_pg.sql:1997`. `main.py:18046` contempla el caso "deploy a medio migrar" en que la vista no existe.

⚠️ `[V]` El propio comentario dice que **hay ~40 lugares que leen `snapshots` directo** (`main.py:1429`); el AUM del asesor lo hace a propósito, pero la disciplina de "usá la vista" no está forzada por nada.

**Índices**: `idx_snapshots_user_date(user_id, date)` (`main.py:1384`) + `idx_snapshots_apto(user_id, apto, date)` (`main.py:1443`).

---

### 8. `config` — clave/valor por usuario

**Negocio**: los tipos de cambio que el usuario fija a mano y un puñado de banderas por cuenta.

#### Las dos variantes del CREATE

`[V]` `backend/main.py:1345-1366`:
- **Rama A — base nueva** (`if not cols:`, línea 1346): `CREATE TABLE config (key TEXT NOT NULL, value TEXT, user_id INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (key, user_id))` (`main.py:1348-1355`).
- **Rama B — pre-multi-tenancy** (`elif 'user_id' not in cols:`, línea 1356): `RENAME TO config_old` → recreate → `INSERT INTO config SELECT key, value, 0 FROM config_old` → drop (`main.py:1357-1366`).

| campo | tipo | qué significa en negocio | quién lo escribe | quién lo lee | notas |
|---|---|---|---|---|---|
| `key` | TEXT NOT NULL | nombre del setting | ver claves abajo | ídem | parte de la PK |
| `value` | TEXT | el valor, siempre string | ídem | ídem | el GET castea a float **por clave**, no en bloque |
| `user_id` | INTEGER NOT NULL DEF 0 | dueño (`0` = global/legacy) | ídem | ídem | parte de la PK |

**Claves reales** `[V]`:

| key | escribe | lee | notas |
|---|---|---|---|
| `tc_blue` | `PUT /api/config` (`main.py:4590`), register (`main.py:3146`), `sim_import.py:47` | `main.py:640, 669, 9501, 13960, 17526, 33042`, `persister.py:344, 1314`, `ai/builders/profile_card.py:170` | el TC de fallback de casi todo |
| `tc_mep` | `PUT /api/config` (`main.py:4583`), register (`main.py:3145`) | `main.py:29958, 30301, 32797` | |
| `fx_version` | `fx.py:161, 180` (`set_fx_version`) | `fx.py:131`, `main.py:11282, 17012` | `'v1'`/`'v2'` por cuenta; se borra en el reset (`main.py:3616`) |
| `migr_snapshots_netdep_v1` | `main.py:32365` con `user_id=0` | `main.py:32288` | marca one-shot de una migración de datos |
| `display_currency` | 💀 **nadie**. `grep -rn "display_currency" backend frontend/src` → un solo hit de LECTURA | `ai/builders/metrics_pro_card.py:126-130` | el frontend guarda la moneda en **localStorage** (`frontend/src/contexts/CurrencyContext.jsx:24`, `'rendi_display_currency'`), nunca en `config` → el card de IA siempre lee el default `"USD"` |

**Claves / índices**: PK compuesta `(key, user_id)`. **Sin `id`.**

⚠️ **Inconsistencia verificable**: `PUT /api/config` nombra las columnas a propósito, y el comentario explica por qué (`main.py:4578-4581`): *"el VALUES posicional de antes asumía el orden (key, value, user_id) … la próxima columna que se agregue lo rompe en silencio"*. Pero el **register sigue usando el VALUES posicional**: `INSERT OR IGNORE INTO config VALUES ('tc_mep', '1415', ?)` (`main.py:3145-3146`). La lección se aplicó en un solo call site.

⚠️ `[V]` `GET /api/config` **descarta silenciosamente** toda clave no numérica (`main.py:4556-4560`) — `fx_version` y `display_currency` nunca salen por esa API.

---

### 9. `goals` — la meta financiera

**Negocio**: "quiero llegar a US$ X para tal fecha". Alimenta el diagnóstico de meta y el CAGR necesario.

`[V]` DDL: `backend/main.py:1498-1507`.

| campo | tipo | qué significa en negocio | quién lo escribe | quién lo lee | notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK | | SQLite | `/api/goals/{gid}/diagnostic` | |
| `user_id` | INTEGER NOT NULL | dueño | `POST /api/goals` (`main.py:15177`) | `main.py:15166, 15181, 15199, 15239`, `ai/builders/goal.py:26` | sin FK |
| `target_usd` | REAL NOT NULL | monto objetivo, en USD | POST/PUT (`main.py:15177, 15195`) | diagnóstico, IA | |
| `target_date` | TEXT NOT NULL | fecha objetivo | ídem | ídem | validado por regex `_DATE_RE` en Pydantic (`main.py:15154-15159`), **no** por la DB |
| `expected_return_pct` | REAL NOT NULL DEF 10 | retorno anual esperado que el usuario asume | ídem | proyección | acotado `-50..200` en el modelo (`main.py:15151`) |
| `label` | TEXT | nombre de la meta | ídem | UI | |
| `created_at` | TEXT DEF `datetime('now')` | | default | | |

**Índices**: `idx_goals_user ON goals(user_id)` (`main.py:1507`).
`[V]` Sin FK, sin UNIQUE: un usuario puede tener N metas y no hay tope.

---

### 10. `plazos_fijos` — el depósito a plazo

**Negocio**: plazos fijos bancarios. **No cotizan**: el valor se computa determinísticamente (capital + interés devengado). No se atan a `brokers`: viven en su propio grupo "Plazos fijos" en Cartera (`main.py:1512-1515`).

`[V]` DDL: `backend/main.py:1517-1536`.

| campo | tipo | qué significa en negocio | quién lo escribe | quién lo lee | notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK | | SQLite | PUT/DELETE/renovar/cerrar | |
| `user_id` | INTEGER NOT NULL | dueño | `main.py:9146` | `main.py:9107, 9169, 9249, 9283, 37364` | sin FK |
| `banco` | TEXT NOT NULL | banco emisor | POST/PUT | UI | viene del listado de la API de tasas `[V]` (comentario `main.py:1514`) |
| `capital` | REAL NOT NULL | monto depositado | POST/PUT, renovación (`main.py:9260`) | valuación | |
| `moneda` | TEXT NOT NULL DEF `'ARS'` | moneda del depósito | POST/PUT | valuación | |
| `tasa` | REAL NOT NULL | **fracción** anual (0.19 = 19%) | POST/PUT | interés devengado | ⚠️ fracción, no porcentaje |
| `rate_type` | TEXT NOT NULL DEF `'TNA'` | `'TNA'` (simple) \| `'TEA'` (compuesta) | POST/PUT | `frontend/src/utils/valuation.js` | |
| `fecha_inicio` | TEXT NOT NULL | alta | POST/PUT, renovación | devengamiento | |
| `plazo_dias` | INTEGER NOT NULL | días | POST/PUT | cálculo de vencimiento | |
| `fecha_vencimiento` | TEXT NOT NULL | vencimiento | derivado en el endpoint (`venc`) | UI, alertas | redundante con `fecha_inicio + plazo_dias` |
| `renovacion_auto` | INTEGER NOT NULL DEF 0 | ¿se renueva sola? | `POST/PUT` (`main.py:9152, 9179`) | 💀 **nadie**: se devuelve casteado a bool (`main.py:9114`) y el único uso en frontend es el checkbox del formulario (`PfFormModal.jsx:143, 201, 352`). No hay lógica de renovación automática que lo consulte | dato inerte |
| `modalidad` | TEXT NOT NULL DEF `'vencimiento'` | `'vencimiento'` (interés al final) \| `'periodico'` | POST/PUT | `valuation.js:803`, `PlazosFijosGroup.jsx:140` | el comentario dice "fast-follow, todavía no valuado distinto" (`main.py:1597-1600`) |
| `pago_frecuencia_meses` | INTEGER | meses entre capitalizaciones (sólo si `periodico`) | POST/PUT, forzado a NULL si no es periódico (`main.py:9153`) | `main.py:9213`, `valuation.js:803` | |
| `notes` | TEXT | libre | POST/PUT | UI | |
| `created_at` | TEXT DEF `datetime('now')` | | default | | |
| `closed_at` | TEXT | cierre anticipado / cobro | `main.py:9324` | `WHERE closed_at IS NULL` en los listados (`main.py:9107, 9249, 9283`) | soft-delete |

**Migraciones**: `modalidad` (`main.py:1601-1603`) y `pago_frecuencia_meses` (`main.py:1604-1606`), ambas gateadas por `_table_cols(conn,'plazos_fijos')` — y `plazos_fijos` **sí** está en el allowlist (`main.py:581`), así que corren.

**Índices**: `idx_pf_user ON plazos_fijos(user_id)` (`main.py:1535`).

⚠️ `[V]` El interés de un plazo fijo se registra como `operations.op_type = 'Interés PF'`, y ése es el **pendiente #3** de `realized_pnl.py:63-71`: guarda moneda nativa como un cupón, no está excluido de "trades cerrados" y no se convierte a USD.

---

### 11. `futures_positions` — futuros abiertos, en su propia tabla

**Negocio**: posiciones de futuros (Binance). Tabla **separada de `positions` a propósito**: `main.py:1539-1550` explica que hay 116 lecturas de `positions` en backend y 7 consumidores en el front que asumen que *tenés* el activo y que la exposición es *positiva* — un short rompe las dos.

`[V]` DDL: `backend/main.py:1551-1567`.

| campo | tipo | qué significa en negocio | quién lo escribe | quién lo lee | notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK | | SQLite | PUT/DELETE/cerrar | |
| `user_id` | INTEGER NOT NULL | dueño | `main.py:12247` | `main.py:12232, 12256, 12281, 12297, 12327` | sin FK |
| `broker` | TEXT NOT NULL | dónde | POST/PUT | filtro | por nombre; ⚠️ `delete_broker` **no** limpia esta tabla |
| `symbol` | TEXT NOT NULL | el par (`BTCUSDT`) | POST/PUT (`.strip().upper()`) | UI | |
| `base_asset` | TEXT | el subyacente derivado (`BTCUSDT` → `BTC`) | `_base_asset_de(data.symbol)` (`main.py:12252, 12274`) | `FuturosGroup.jsx:60, 112, 146, 202` (para pedir el precio) | derivado, no lo manda el cliente |
| `side` | TEXT NOT NULL DEF `'long'` | `long` \| `short` | POST/PUT | signo del no-realizado | |
| `quantity` | REAL NOT NULL | tamaño | POST/PUT | no-realizado | |
| `entry_price` | REAL NOT NULL | precio de entrada | POST/PUT | no-realizado | |
| `leverage` | REAL | apalancamiento | POST/PUT | `FuturosGroup.jsx:158` (`{f.leverage}x`) | sólo display |
| `margin_usd` | REAL | margen puesto | POST/PUT | sólo el propio formulario de edición (`FuturosGroup.jsx:378-379`) | ⚠️ **no se descuenta del efectivo a propósito** (`main.py:1544-1550`): en Binance el pase spot→futuros es interno |
| `liquidation_price` | REAL | precio de liquidación | `POST/PUT` (`main.py:12254, 12276`) | 💀 **nadie**. `grep -rn "liquidation_price" .` → sólo el DDL, el modelo Pydantic, los 2 writes y `schema_pg.sql`. **Ni siquiera hay input en el formulario** | columna write-only: sólo se puede setear por API cruda |
| `opened_at` | TEXT NOT NULL | apertura | POST/PUT | UI | |
| `notes` | TEXT | libre | POST/PUT | UI | |
| `closed_at` | TEXT | cierre (soft) | `main.py:12345`, `14373`; se **reabre** con NULL en `main.py:14138` | `idx_futpos_abiertas`, filtro de abiertas | |
| `created_at` | TEXT DEF `datetime('now')` | | default | | |

**Índices**: creados en un `executescript` **aparte** del `CREATE TABLE`, con el motivo escrito (`main.py:1568-1573`): `idx_futpos_user(user_id)` y `idx_futpos_abiertas(user_id, closed_at)` (`main.py:1574-1576`).

⚠️ `[V]` `futures_positions` **no está** en `_RESET_PORTFOLIO_TABLES` (`main.py:3606-3611`): "Empezar de cero" deja los futuros vivos. Tampoco está en el allowlist de `_table_cols`.

---

### 12. `watchlist` — tickers que seguís sin tener

**Negocio**: símbolos que el usuario mira pero no posee. `main.py:1608-1611`: *"No tiene relación con `positions` — son universos separados."*

`[V]` DDL: `backend/main.py:1613-1622`.

| campo | tipo | qué significa en negocio | quién lo escribe | quién lo lee | notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK | | SQLite | listado | |
| `user_id` | INTEGER NOT NULL | dueño | `POST /api/watchlist` (`main.py:33305`) | `main.py:33279`, `DELETE` (`main.py:33322`) | sin FK |
| `symbol` | TEXT NOT NULL | ticker | POST, validado por regex `^[A-Z0-9]{1,10}(\.BA|-USD)?$` (`main.py:33267`) | listado + quotes en batch | el DELETE es **por símbolo**, no por id (`main.py:33313`) |
| `asset_type` | TEXT | tipo de activo | POST (`main.py:33307`) | 💀 se devuelve en el JSON (`main.py:33274`) pero **ningún componente lo usa**: `grep asset_type` en `components/home/Watchlist.jsx`, `fundamentals/useWatchlist.js`, `fundamentals/StarToggle.jsx` → sin resultados | |
| `added_at` | TEXT DEF `datetime('now')` | cuándo | default | `ORDER BY added_at DESC` | |

**Claves / índices**: `UNIQUE(user_id, symbol)` (que hace idempotente el `INSERT OR IGNORE`) + `idx_watchlist_user(user_id)` (`main.py:1621`).

⚠️ `[V]` `watchlist` **no** está en `_RESET_PORTFOLIO_TABLES` — es prefencia de UX y sobrevive al reset, por diseño explícito (`main.py:3598-3600`).

---

### 13. `deleted_ops_journal` — el journal de "Deshacer"

**Negocio**: cuando el usuario borra algo cargado a mano (una operación, una posición, un cobro de bono) no hay rebuild que lo re-derive, así que se guarda una foto JSON del borrado + los deltas de cash/tenencia para poder re-insertarlo. Lo **importado** no usa esto: su undo es limpiar `excluded_at` en `import_normalized_tx`.

`[V]` DDL: `backend/main.py:2515-2527` (dentro del bloque grande de tablas de import).

| campo | tipo | qué significa en negocio | quién lo escribe | quién lo lee | notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK | | SQLite | | |
| `user_id` | INTEGER NOT NULL | dueño | todos los INSERT | los SELECT de undo | sin FK |
| `token` | TEXT NOT NULL | **agrupa un borrado** (un borrado puede ser N filas) | `secrets.token_hex(8)` en cada borrado | `POST /api/operations/undo/{token}` (`main.py:14743`), `main.py:8483, 14750, 15047` | ⚠️ **sin UNIQUE**: la unicidad la da `token_hex(8)` (64 bits), no la DB |
| `kind` | TEXT NOT NULL | qué tipo de borrado fue | ver abajo | despacho del undo | ⚠️ el comentario del DDL dice `'imported' | 'manual'` (`main.py:2520`) — **está desactualizado** |
| `payload_json` | TEXT NOT NULL | la foto JSON de lo borrado + deltas | cada camino arma el suyo | el undo | ⚠️ **shape distinto por `kind`**, sin schema |
| `since_date` | TEXT | desde qué fecha hay que recomputar agregados/snapshots | los borrados manuales; `None` en `position_group_edit` (`main.py:8455`) | cascada de recálculo | |
| `broker` | TEXT | broker afectado | ídem | cascada | ⚠️ en `imported_asset` guarda **sólo el primero** de los brokers tocados (`main.py:15010`) mientras el payload lleva la lista completa |
| `created_at` | TEXT DEF `datetime('now')` | cuándo | default | ventana de undo | |
| `undone_at` | TEXT | cuándo se deshizo (idempotencia) | `main.py:8489, 14342, 14792, 15087` | `WHERE undone_at IS NULL` | soft-flag, la fila no se borra |

**Valores reales de `kind`** `[V]`:

| kind | dónde se escribe | qué guarda el payload |
|---|---|---|
| `position_group_edit` | `main.py:8450-8456` | `{lots, src, asset, new_asset, broker, pair}` |
| `manual_op` | `main.py:14163-14167` | la fila entera de `operations` + deltas |
| `manual_position` | `main.py:14270-14276` | `{pos_row, credit, autodep}` |
| `imported` | `main.py:14578-14585` y `14700-14710` | `{tx_id, batch_id, raw_row_id, cash_reversed, broker, asset}` |
| `imported_asset` | `main.py:15002-15011` | `{tx_ids, cash_by_broker, asset, pairs, brokers, rf_ops}` |

⚠️ Dos de esos cinco (`imported`, `imported_asset`) **sí** son de filas importadas, contradiciendo el comentario del DDL ("Las importadas NO usan esto", `main.py:2513-2514`). El comentario describe un diseño anterior.

⚠️ Nota fina, documentada `[V]`: en `main.py:14705-14707` el payload guarda `-cash_reversed` (negado) porque el delete **devolvió** cash y el undo tiene que re-debitarlo; en la venta se guarda `+proceeds` porque su delete restó. Convención de signos que depende del `kind` y sólo vive en ese comentario.

**Índices**: `idx_deleted_ops_journal_tok ON deleted_ops_journal(user_id, token)` (`main.py:2526-2527`).

⚠️ `[V]` No hay **ninguna** limpieza por antigüedad: el journal crece indefinidamente. Sí está en `_RESET_PORTFOLIO_TABLES` (`main.py:3609`).

---

### 14. El mapa de relaciones: qué se linkea por ID y qué por NOMBRE

Esto es lo más estructural del modelo.

#### Por ID (FK declarada)

`[V]` Las únicas FK reales que tocan mis tablas:

| desde | hacia | acción | dónde |
|---|---|---|---|
| `brokers.user_id` | `users.id` | ninguna | `main.py:725`; `schema_pg.sql:2019` |
| `brokers.parent_broker_id` | `brokers.id` | `ON DELETE CASCADE` **sólo en bases nuevas** | `main.py:728` vs `main.py:774`; `schema_pg.sql:2017` |

Eso es **todo**. `positions`, `operations`, `monthly_entries`, `snapshots`, `config`, `goals`, `plazos_fijos`, `futures_positions`, `watchlist`, `archived_positions`, `deleted_ops_journal` **no tienen ninguna FK**: ni a `users`, ni a `brokers`. Verificado en las dos ramas (`init_db` y `schema_pg.sql:2009-2035`, donde la lista completa de `ADD CONSTRAINT` no menciona ninguna de ellas).

#### Por NOMBRE (string)

`[V]` `backend/main.py:4117-4134` lo declara explícitamente:

```python
NAME_KEYED_TABLES = (
    "positions", "operations", "monthly_entries",
    "import_batches", "import_normalized_tx", "bond_cashflow_skips",
)
```

Consecuencias verificadas:

1. **Renombrar un broker es un cascade manual de 6 tablas en una transacción** (`main.py:4295-4310`). `import_normalized_tx` necesita un caso especial porque **no tiene `user_id`**: se acota por subquery de `batch_id` (`main.py:4292-4294`).
2. **`delete_broker` limpia sólo 4 tablas** (`positions`, `operations`, `monthly_entries`, `import_batches`) y el comentario admite el gap: *"NO toca `import_normalized_tx` ni `bond_cashflow_skips` (orphan gap conocido)"* (`main.py:4123-4126`).
3. `[I]` **Tablas name-keyed que NO están en la lista y nadie cascadea**: `futures_positions.broker`, `deleted_ops_journal.broker`, y el `broker` que va dentro de `archived_positions.payload` (JSON). Un rename las deja apuntando a un nombre que ya no existe. En `futures_positions` esto es visible: el futuro queda huérfano de su cuenta.
4. **`'global'` es un nombre de broker que no corresponde a ninguna fila de `brokers`** — de ahí que renombrar a `'global'` esté prohibido (`main.py:4184-4195`).
5. **Un mismo activo vive partido entre dos nombres** (padre y `· USD`), y el sistema entero depende de `broker_pair` para volver a juntarlos (`persister.py:99`).

---

### 15. Hallazgos y rarezas (todo verificado)

1. **`positions.invested` tiene dos significados**: costo del lote si `is_cash=0`, **saldo de efectivo** si `is_cash=1` (`persister.py:1033-1045`). `quantity` queda en 0 para el cash. Cualquier `SUM(invested)` que no filtre por `is_cash` mezcla costo con caja.
2. **`operations.pnl_usd` no siempre está en USD** — documentado en `backend/realized_pnl.py:9-15`. Hay 398 filas viejas que siguen infladas en el dashboard (`realized_pnl.py:55-61`) y `'Interés PF'` es una bomba dormida (`realized_pnl.py:63-71`).
3. **`operations.fx_to_usd` cambia de significado según `op_type`**: factor de conversión en cupones/amortizaciones, `tc_venta` en `Venta` (`realized_pnl.py:23-25`).
4. **`operations.cost_basis_consumed` está 100% NULL en producción** — lo dicen tres lugares independientes del código (`main.py:37436`, `frontend/src/utils/assetPnl.js:18`, `frontend/src/utils/bookComposition.js:210`). Se escribe en un solo camino y se descarta en todos los lectores.
5. **`operations.pnl_pct` es casi-muerta**: se persiste en 3 caminos, se devuelve por `SELECT *`, y el único lector es un diagnóstico admin de escala (`main.py:11611-11720`). Ningún componente de producción del frontend la usa.
6. **`futures_positions.liquidation_price` es write-only**: no hay lector en ningún lado y **ni siquiera hay input en el formulario** — sólo se puede setear con un `POST` crudo.
7. **`plazos_fijos.renovacion_auto` es inerte**: hay checkbox, se guarda, se devuelve casteado a bool, y ninguna lógica lo consulta. No existe renovación automática.
8. **`watchlist.asset_type` no lo lee nadie** en el frontend.
9. **`config.display_currency` es un fantasma**: `ai/builders/metrics_pro_card.py:126-130` lo lee, pero **nadie lo escribe** — el frontend guarda la moneda en `localStorage` (`frontend/src/contexts/CurrencyContext.jsx:24`). El card de IA siempre ve `"USD"`.
10. **La allowlist de `_table_cols` (`main.py:578-582`) es un pie de rastrillo con dos víctimas confirmadas** (`advisor_op_batch_items`, `advisor_profile.logo_data`). Cuatro de mis tablas están fuera de ella: `archived_positions`, `futures_positions`, `watchlist`, `deleted_ops_journal`. Hoy no tienen migraciones gateadas; la próxima que se agregue no va a correr en prod.
11. **El backfill de `positions.currency` corre en cada arranque**, sin guard de columna, sobre todos los usuarios, dentro de un `try/except: pass` (`main.py:980-994`). Reclasifica silenciosamente cualquier lote nuevo que nazca con `currency` NULL.
12. **`ON DELETE CASCADE` de `brokers.parent_broker_id` no existe en producción** (`main.py:4476-4487`, verificado en `backend/trading.db`). El código lo compensa con un `DELETE` explícito de los hijos (`main.py:4488`) — pero cualquier camino nuevo que borre un broker padre sin ese `DELETE` explícito va a chocar con `FOREIGN KEY constraint failed` con `PRAGMA foreign_keys=ON` (`main.py:435`).
13. **El register usa el `VALUES` posicional de `config`** (`main.py:3145-3146`) que el propio código declara peligroso 1400 líneas después (`main.py:4578-4581`).
14. **`positions` tiene un solo índice (`user_id`)** mientras `operations` y `monthly_entries` tienen compuestos. Las 188 lecturas de `FROM positions` filtran casi siempre por `(user_id, broker, asset, is_cash)`.
15. **`deleted_ops_journal.token` no tiene UNIQUE** y el journal no se purga nunca.
16. **La base de dev tiene `users.gift_plus_email_sent_at`**, columna que ya no existe en el código — residuo de una versión anterior que en producción sigue ocupando lugar `[I]` (`sqlite3 backend/trading.db ".schema users"`).
17. **`backend/seed.py` es código muerto** con `sys.exit(1)` a nivel de módulo (`seed.py:10`) y el propio archivo documenta que sus `INSERT` a `config` son inválidos (2 valores para 3 columnas, `seed.py:21-27`).
18. **`monthly_entries.pnl_unrealized` se escribe por un endpoint y se borra por dos** (`_recalc` lo fuerza a 0 en `main.py:9592`, `_repair_monthly_chain` lo zeroa en todo mes cerrado en `main.py:9666`). Es válido sólo para el mes calendario en curso, y hay lectores que lo suman sobre meses cerrados (`wrapped.py:144`, `reporting/builder.py:692`) — donde vale 0, así que hoy no muerde.
19. **`snapshots` tiene 12 columnas de las que 6 llegaron por `ALTER`, y la vista `snapshots_medibles` se dropea y recrea en cada boot** (`main.py:1459-1461`). El comentario admite que **hay ~40 lugares que leen `snapshots` directo** sin pasar por la vista.
20. **En Postgres no corre ninguna de las 46 migraciones** (`main.py:699-707`), y `schema_pg.sql` **no contiene un solo `UPDATE`/`DELETE`** — o sea, los backfills de datos no tienen equivalente en ese camino.
