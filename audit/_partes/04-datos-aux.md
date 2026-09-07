## Modelo de datos auxiliar: cache, mercado, auth, billing e importación

Esta sección documenta las 28 tablas que **no** son la cartera (positions / operations /
monthly_entries / snapshots): el andamiaje de precios, noticias, IA, identidad, cobro e
importación. Todo lo que sigue está leído del commit `b74f450f` de `main`.

Convención: `[V]` = verificado leyendo el código (con cita); `[I]` = inferencia mía (digo de
qué me agarré). ⚠️ = rareza / riesgo. 💀 = columna o tabla muerta (nadie la escribe, nadie la
lee, o quedó de una era anterior).

---

### 0. Dónde nace este esquema (y la bifurcación que hay que tener en la cabeza)

`[V]` Todas estas tablas se crean en `init_db()`, `backend/main.py:698`, que se ejecuta al
importar el módulo (`backend/main.py:2676`, `init_db()` a nivel de módulo). Las dos únicas
excepciones son `fci_catalog` y `fci_prices`, que las crea `ensure_tables()` en
`backend/pricing/fci.py:176-201`, llamada desde `bootstrap()` (`backend/pricing/fci.py:300`)
en un thread daemon al arrancar (`backend/main.py:32506-32521`).

⚠️ **`init_db()` tiene dos caminos y el de Postgres se saltea TODO el archivo.**

```
backend/main.py:713-721
def init_db():
    if USANDO_PG:
        _init_db_postgres()
        return
```

`[V]` `USANDO_PG = bool(DATABASE_URL)` (`backend/main.py:424`). Si hay `DATABASE_URL`, la
función aplica `backend/schema_pg.sql` línea por línea (`backend/main.py:700-711`) y **retorna
antes** de las ~2.000 líneas de `CREATE TABLE` + ~46 `ALTER TABLE` incrementales. Consecuencia
concreta para esta sección: las tres "migraciones de datos" que viven embebidas en esas líneas
**sólo corren en SQLite**:

| Purga embebida en `init_db()` | Cita | Corre en PG? |
|---|---|---|
| Borrado del backlog de noticias en inglés | `backend/main.py:1287-1294` | no |
| Purga del cache yfinance envenenado de `.BA` | `backend/main.py:2661-2670` | no |
| Backfill de crédito para subs pre-prorrateo | `backend/main.py:2380-2440` | no |

`[V]` `backend/schema_pg.sql` tiene 63 `CREATE TABLE` y contiene las 28 tablas de esta sección
salvo una (ver `import_incidents` más abajo). El comentario de
`backend/scripts/verificar_copia.py:415-418` ("producción tiene **60 tablas** y `schema_pg.sql`
tiene **58**: faltan `fci_catalog` y `fci_prices`") **quedó desactualizado**: hoy las dos están
en el esquema (`backend/schema_pg.sql:788` y `:819`).

⚠️ **El guard de migraciones tiene una allowlist que deja afuera a casi todas estas tablas.**
`_table_cols()` (`backend/main.py:576-587`) sólo responde para 22 tablas; para cualquier otra
devuelve `set()`, o sea "la tabla no existe", o sea "no migres". De las tablas de esta sección
están DENTRO: `import_batches`, `import_raw_rows`, `import_normalized_tx`, `import_op_links`,
`import_mappings`, `news`, `subscriptions`, `ai_usage_daily`, `ai_user_facts`, `ai_tool_usage`,
`yfinance_cache`, `credit_ledger`. Quedan AFUERA: `fx_rates_daily`, `bond_indices_daily`,
`financial_events`, `bond_cashflow_skips`, `push_subscriptions`, `ai_analyses_cache`,
`asset_last_price`, `billing_events`, `plan_events`, `email_verification_codes`,
`password_reset_tokens`, `login_history`, `trial_consumed`, `trial_email_log`, `fci_*`. El
propio código ya se tropezó con esto y lo dice: `backend/main.py:1490-1492` explica que para
`fx_rates_daily` tuvieron que usar `try/except` en vez del guard porque la tabla no está en la
allowlist.

---

### 1. Mercado y FX — tablas GLOBALES (sin `user_id`)

`[V]` Hay un comentario explícito que las trata como categoría aparte:
`backend/main.py:3601-3605` prohíbe meter tablas globales en el allowlist del reset de cartera
("`asset_last_price` y `financial_events` estaban y son caches COMPARTIDOS entre todos los
usuarios"). Corolario importante: **el barrido dinámico de borrado de cuenta**
(`backend/main.py:3846-3853`, que borra de toda tabla que tenga columna `user_id`) **no las
toca**, porque no tienen `user_id`.

#### 1.1 `fx_rates_daily` — la serie ARS/USD por fecha

`[V]` `backend/main.py:1477-1484`. Es la fuente única para dolarizar cualquier cosa histórica.
El docstring de `backend/fx.py:1-38` explica por qué existe con números medidos: 51.475 ventas
de 503 usuarios estampadas con el TC del día del import, y 80.868 de 84.123 flujos en pesos
(96%) al mismo 1415 desde 2013.

| Campo | Tipo | Significado | Quién escribe | Quién lee | Notas |
|---|---|---|---|---|---|
| `date` | TEXT PK | `YYYY-MM-DD` | los 4 escritores de abajo | todos | PK de texto; el índice es la PK |
| `blue_venta` | REAL NOT NULL | dólar blue (venta) del día | ídem | `backend/fx.py:61`, `backend/importing/persister.py:58`, `backend/scripts/backfill_historical_mtm.py:144`, `backend/advisor_brief.py:171` | red histórica |
| `mep_venta` | REAL (nullable) | dólar MEP (bolsa) | `_persist_blue_for_date`, `_backfill_mep_rates_if_missing` | `backend/fx.py:61`, `backend/ledger_replay.py:189`, `backend/twr.py:1242`, `backend/main.py:35723`, `:35726`, `:36838` | **riel por defecto** |
| `source` | TEXT DEFAULT 'unknown' | `'dolarapi'` / `'argentinadatos'` / `'snapshot_cron'` / `'manual'` | escritores | nadie lo filtra `[V]` | telemetría |
| `fetched_at` | TEXT DEFAULT `datetime('now')` | cuándo se trajo | escritores | nadie `[V]` | |

**Escritores (4):**
1. `_persist_blue_for_date()` — `backend/main.py:4658-4694`. UPSERT idempotente con
   `ON CONFLICT(date) DO UPDATE`, y `mep_venta = COALESCE(excluded.mep_venta, fx_rates_daily.mep_venta)`
   para no pisar el backfill histórico con un NULL del día.
2. `POST /api/snapshots` — `backend/main.py:5003`, llama a `_persist_blue_for_date(...,
   source='dolarapi', ...)` en `backend/main.py:5040` con lo que haya en `_dolar_cache`.
3. El cron nocturno de snapshots — `backend/snapshots_job.py:975-991`.
4. Los dos backfills de arranque — `_backfill_fx_rates_if_empty()` (`backend/main.py:4710`, sólo
   si la tabla está VACÍA) y `_backfill_mep_rates_if_missing()` (`backend/main.py:4792`, rellena
   `mep_venta IS NULL`). Corren en un thread daemon en el startup
   (`backend/main.py:32097-32118`).

`[V]` La lectura canónica es `backend/fx.py:_lookup()` (`backend/fx.py:47-72`): "último valor NO
NULO de la columna en o antes de la fecha", con el `IS NOT NULL` **en el WHERE** y no después de
traer la fila — el comentario dice explícitamente por qué (un solo día sin MEP devolvía NULL y
el caller creía que no había cobertura).

⚠️ **Dos rieles con cobertura declarada distinta.** El docstring de `backend/fx.py:29-33`
declara medido: MEP diario completo desde 2018-10-29 (2.829 filas / 2.830 días), blue desde
2011-01-03 (5.685 / 5.686), y sólo 290 de 73.718 ventas (0,4%) anteriores a la cobertura MEP.
Sobre la copia de dev: 5.634 filas `[V]` (`sqlite3 backend/trading.db "SELECT COUNT(*) FROM
fx_rates_daily"`), consistente con la cifra del blue.

⚠️ `source` no se lee en ningún lado `[V]` (grep sobre `fx_rates_daily`: ningún `WHERE source`).
Es telemetría de escritura pura: si mañana hay que saber cuántas filas vinieron del cron y
cuántas del browser de un usuario, el dato está pero nadie lo usa.

⚠️ `_persist_blue_for_date` abre y cierra su propia conexión (`get_db()` / `close()` en
`backend/main.py:4670` y `:4688-4693`), fuera de la transacción del caller. En el POST de
snapshot eso es una conexión extra por request.

**Retención:** ninguna. Es una serie histórica que se quiere entera; el `_backfill_fx_rates_if_empty`
sólo corre "si está vacía" (`backend/main.py:4717-4719`), así que un TRUNCATE se recupera solo
al siguiente boot desde argentinadatos — pero se pierde el `mep_venta` de los días donde la
fuente externa ya no publica.

#### 1.2 `bond_indices_daily` — CER / UVA / A3500

`[V]` `backend/main.py:1232-1240`. Cache de coeficientes diarios para bonos ajustados.

| Campo | Tipo | Significado | Quién escribe | Quién lee | Notas |
|---|---|---|---|---|---|
| `index_name` | TEXT PK(1) | `'CER'` \| `'UVA'` \| `'A3500'` según el comentario | `_ensure_index_cached` | `GET /api/bond-indices/{index_name}` | **sólo se escribe `'CER'`** |
| `date` | TEXT PK(2) | `YYYY-MM-DD` | ídem | ídem | |
| `value` | REAL NOT NULL | coeficiente | ídem | ídem | |
| `source` | TEXT | `'bcra'`\|`'argentinadatos'`\|`'manual'` | siempre `'argentinadatos'` | nadie `[V]` | |
| `updated_at` | TEXT NOT NULL | | ídem | nadie `[V]` | |

💀 **De los 3 índices declarados en el comentario, sólo existe uno.** El mapa de fetchers es
`fetcher_map = {"CER": _fetch_cer_series}` (`backend/main.py:5600`); si `index_name` no está en
el mapa la función hace `return` sin fetchear (`backend/main.py:5601-5603`). O sea `UVA` y
`A3500` devuelven serie vacía para siempre.

`[V]` Un único consumidor en todo el frontend:
`frontend/src/pages/Positions.jsx:276` → `api.get('/bond-indices/CER')`.

⚠️ **El TTL vive en memoria del proceso, no en la tabla.** `_indices_fetched = {}` con
`INDICES_TTL = 4*3600` (`backend/main.py:5569-5570`), y el flag `stale` que devuelve el endpoint
se calcula contra ese dict (`backend/main.py:5678-5680`). Después de un redeploy el dict arranca
en `{}`, y `updated_at` —el dato que SÍ está persistido y serviría para esto— no se lee nunca.
Con más de un worker, dos requests pueden reportar `stale` distinto para el mismo estado de la
tabla.

⚠️ **El refresh reescribe la serie ENTERA.** `_ensure_index_cached` itera todas las fechas que
devuelve argentinadatos y hace un UPSERT por fila (`backend/main.py:5607-5619`), dentro de un
solo `with conn`. La serie CER es diaria y arranca a principios de los 2000: son miles de
statements cada 4 horas por proceso. `[I]` No medí el volumen (la tabla está en 0 filas en la
copia de dev), pero la forma del loop es la que es.

**Retención:** ninguna; y no hace falta, es una serie histórica.

#### 1.3 `asset_last_price` — el último precio conocido por símbolo

`[V]` `backend/main.py:1974-1978`. Existe para no valuar a costo cuando yfinance falla: "sin
precio hoy → la dejo igual que la última vez que la vi" (`backend/main.py:1966-1973`).

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `symbol` | TEXT PK | símbolo tal como se valúa (`AAPL`, `GGAL.BA`, `BTC`) | `persist_last_prices` | `read_last_prices` |
| `price` | REAL NOT NULL | último precio real visto | ídem | ídem |
| `updated_at` | TEXT NOT NULL | ISO UTC | ídem | `backend/main.py:23444`, `backend/main.py:37763` |

`[V]` Escritura: `persist_last_prices()` en `backend/snapshots_job.py:565-586` (UPSERT en
`executemany`, `ON CONFLICT(symbol)`), llamada desde `apply_last_known_prices()`
(`backend/snapshots_job.py:604-616`). La escriben tanto `/api/prices` (intradía) como el cron de
cierre `[V]` (comentario en `backend/main.py:1971-1973`; en el shutdown también se baja el buffer
pendiente, `backend/main.py:32596-32602`).

⚠️ **Guarda el precio en la moneda en la que se lo dieron, y hay un caller que lo convierte
antes.** `backend/main.py:7821` dice: "ANTES de persistir/last-known para que el
cache/asset_last_price guarden pesos". O sea la semántica de `price` depende del camino que lo
escribió. `[I]` No auditué todos los callers de `apply_last_known_prices`; lo digo porque el
comentario lo hace explícito.

⚠️ **`MAX(updated_at)` global usado como "fecha de la valuación" de un asesor.**
`backend/main.py:37762-37764` hace `SELECT MAX(updated_at) d FROM asset_last_price` (sin filtrar
por los símbolos de esa cartera) y lo devuelve como `as_of` de la card del asesor. Si CUALQUIER
símbolo del sistema se actualizó hoy, la card dice "al día de hoy" aunque los activos de ese
libro estén con precio de la semana pasada.

`[V]` El consumidor de `register_trade` sí acota por edad: si el `updated_at` del símbolo tiene
más de 48h, no confía y le pide el precio al usuario (`backend/main.py:23443-23453`).

**Retención:** ninguna. Una fila por símbolo; 89 filas en la copia de dev `[V]`. Un símbolo
delisted queda con su último precio para siempre y sigue valuando posiciones.

#### 1.4 `yfinance_cache` — payloads normalizados de yfinance

`[V]` `backend/main.py:1956-1964`.

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `ticker` | TEXT PK(1) | ticker normalizado a yfinance (`_yf_normalize_ticker`) | `_yf_cache_write` | `_yf_cache_read` |
| `kind` | TEXT PK(2) | `fundamentals`\|`scorecard`\|`earnings`\|`analysts`\|`profile`\|`financials` | ídem | ídem |
| `fetched_at` | TEXT NOT NULL | | ídem | ídem |
| `payload_json` | TEXT NOT NULL | payload normalizado serializado | ídem | ídem |

⚠️ **El comentario del esquema contradice al código en dos puntos, los dos verificables.**
`backend/main.py:1954-1955` dice:
> `fetched_at` en ISO. TTL hardcoded 6h en el lector. / Cleanup: cron diario borra rows > 7 días.

- **No es ISO, es epoch float como string.** `_yf_cache_write` escribe `str(_time.time())`
  (`backend/main.py:21092`) y `_yf_cache_read` hace
  `float(row["fetched_at"])` (`backend/main.py:21071`). El docstring del lector lo aclara
  (`backend/main.py:21060-21063`), pero el comentario del `CREATE TABLE` quedó viejo.
- **El TTL no es 6h fijo: es por `kind`.** `YF_CACHE_TTL_BY_KIND`
  (`backend/main.py:21019-21031`): profile/analysts/financials 24h, fundamentals/scorecard 12h,
  earnings 6h, default 6h. Más un fallback stale de 7 días si el fetcher falla
  (`YF_CACHE_STALE_FALLBACK_SECONDS`, `backend/main.py:21035`, usado en `backend/main.py:21160`
  y `:21168`).
- 💀 **El "cron diario que borra rows > 7 días" no existe.** Los únicos jobs registrados son
  cinco: `daily_snapshot`, `iol_lab_refresh`, `subscription_lifecycle`, `backup_db`, `fci_refresh`
  (`backend/main.py:32534-32575`). No hay ninguno de limpieza. El único DELETE sobre esta tabla
  es la purga de `.BA` envenenados que corre en cada boot (`backend/main.py:2661-2670`) — y que
  en Postgres no corre (§0).

⚠️ El índice `idx_yfinance_cache_fetched ON yfinance_cache(fetched_at DESC)`
(`backend/main.py:1963-1964`) no lo usa ninguna consulta: las dos que existen filtran por
`(ticker, kind)`, que es la PK `[V]`. Y ordenaría lexicográficamente un epoch en texto, que sólo
coincide con el orden numérico mientras todos los epochs tengan la misma cantidad de dígitos.

#### 1.5 `fci_catalog` y `fci_prices` — fondos comunes

`[V]` `backend/pricing/fci.py:176-201`. Son las dos únicas tablas de la app creadas fuera de
`init_db()`. Cita textual del propio esquema sobre por qué el tipo importa
(`backend/pricing/fci.py:190-197`): usan `DOUBLE PRECISION` y no `REAL` porque estas dos tablas
"no pasan por el traductor que convierte los tipos" y en Postgres `REAL` son 4 bytes.

**`fci_catalog`**

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `symbol` | TEXT PK | `FCI:<slug>` | `seed_catalog` (`backend/pricing/fci.py:245-254`) | `refresh_prices`, `list_catalog` |
| `ad_name` | TEXT NOT NULL | nombre EXACTO en ArgentinaDatos — es la clave de match | ídem | `refresh_prices` (`backend/pricing/fci.py:283`) |
| `display_name` | TEXT NOT NULL | nombre para UI | ídem | `list_catalog` |
| `emisor`, `clase`, `moneda`, `categoria` | TEXT | derivados del nombre | ídem | `list_catalog` |
| `activo` | INTEGER DEFAULT 1 | ¿sigue vivo? | ídem | `WHERE activo=1` |
| `created_at` | TEXT | | default | nadie `[V]` |

💀 ⚠️ **`activo` nunca vale 0.** El UPSERT lo fuerza a 1 en el INSERT y en el
`DO UPDATE SET ... activo=1` (`backend/pricing/fci.py:248` y `:253`), y no hay ningún otro
`UPDATE fci_catalog` en el repo `[V]` (grep `activo` sobre `backend/pricing/fci.py` da 7 hits,
todos de creación o de `WHERE activo=1`). Un fondo que desaparece de la fuente queda `activo=1`
para siempre: entra en el `SELECT ... WHERE activo=1` de `refresh_prices`
(`backend/pricing/fci.py:276-278`), no matchea, y engrosa la lista `missing` en cada corrida.
La única defensa contra fondos muertos es el corte de frescura **del seed**, que además es
POR CATEGORÍA por un bug ya sufrido y documentado (`backend/pricing/fci.py:210-227`: con corte
global "una categoría fresca dejaba al catálogo entero sin poder incorporar fondos nuevos, en
silencio").

**`fci_prices`**

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `symbol` | TEXT PK | | `refresh_prices` (`backend/pricing/fci.py:288-295`) | `get_prices_detail_for` (`backend/pricing/fci.py:331-334`) |
| `price` | DOUBLE PRECISION | `vcp / 1000`, redondeado a 6 | ídem | ídem |
| `moneda` | TEXT | copiada del catálogo | ídem | `list_catalog` |
| `as_of_date` | TEXT | fecha del VCP según la fuente | ídem | ídem — **se muestra en UI a propósito** |
| `fetched_at` | TEXT | | ídem | nadie `[V]` |

`[V]` El docstring de `get_prices_detail_for` (`backend/pricing/fci.py:321-327`) documenta el
incidente que justifica exponer `as_of`: la fuente dejó de publicar entre 2026-07-21 y
2026-08-13 (tres semanas) y el precio viejo se seguía mostrando como si fuera de hoy.

`[V]` `refresh_prices` **no borra precios viejos si el fetch falla**
(`backend/pricing/fci.py:265-270`: aborta y devuelve `{"ok": False, ...}` sin tocar la tabla).
Escritores: el cron `fci_refresh` a las 12:10 UTC (`backend/main.py:32568-32573`) y el
`bootstrap()` en cada arranque (`backend/main.py:32506-32521`). 117 filas en cada una en la copia
de dev `[V]`.

#### 1.6 `news` — feed de noticias compartido

`[V]` `backend/main.py:1252-1272`. Compartido cross-user a propósito; la personalización es en
query time.

| Campo | Tipo | Significado | Quién escribe | Quién lee | Notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK AUTOINC | | | | |
| `source` | TEXT NOT NULL | `'google_news_rss'` \| … | `_persist_news_items` | se devuelve al front | UNIQUE(source, external_id) |
| `external_id` | TEXT NOT NULL | guid del feed — dedup | ídem | — | |
| `title`, `summary`, `url` | TEXT | | ídem | endpoints de news | |
| `image_url` | TEXT | | **NULL siempre** | nadie | 💀 |
| `published_at` | TEXT NOT NULL | ISO | ídem | `ORDER BY published_at DESC` | índice `idx_news_published` |
| `tickers` | TEXT | JSON array | **NULL siempre** | nadie | 💀 |
| `category` | TEXT | `market`\|`portfolio`\|`macro` | ídem | filtro principal | |
| `query_source` | TEXT | el query que la trajo | ídem | `LIKE '{TICKER} %'` | índice `idx_news_qsource_cat` |
| `tags` | TEXT | CSV de keywords | `_tag_news_item` | front | agregada por ALTER `backend/main.py:1277-1279` |
| `sentiment` | TEXT | heurística al ingerir | `_sentiment_news_item` | front | ALTER `backend/main.py:1297-1299` |
| `fetched_at` | TEXT NOT NULL | | ídem | **nadie** | ⚠️ |

💀 **`image_url` y `tickers` son columnas muertas.** Hay un único INSERT en toda la app
(`backend/main.py:6675-6683`) y pasa `NULL` literal en las dos posiciones:

```
backend/main.py:6678-6679
   (source, external_id, title, summary, url, image_url,
    published_at, tickers, category, query_source, tags, sentiment, fetched_at)
   VALUES (?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?, ?, ?)
```
Confirmado también contra la copia de dev: `SELECT COUNT(*) FROM news WHERE tickers IS NOT NULL`
→ 0, ídem `image_url` `[V]`.

⚠️ **`fetched_at` se escribe y no se lee nunca.** La frescura la decide `_news_fetched_at`, un
dict en memoria del proceso (`backend/main.py:6149`) con `NEWS_TICKER_TTL = 30 min` /
`NEWS_MARKET_TTL = 60 min` (`backend/main.py:6150-6151`). Mismo patrón sistémico que
`bond_indices_daily` y `financial_events`: **el TTL vive en el proceso, la columna que lo
soportaría vive en la tabla, y no se hablan.** Cada redeploy y cada worker nuevo re-fetchea todo.

⚠️ **La purga de noticias en inglés corre en CADA boot.** `backend/main.py:1287-1294` ejecuta
`DELETE FROM news WHERE query_source LIKE '% stock' OR query_source LIKE '%www.investing.com%'`
en cada arranque. Los dos `LIKE` tienen comodín a la izquierda, así que ningún índice sirve: es
un full scan de `news` en cada boot (2.179 filas en la copia de dev `[V]`; en producción el
orden de magnitud es mayor `[I]`, basado en que el feed acumula sin límite). Es idempotente y
barato hoy; es una bomba de relojería de crecimiento.

⚠️ **El feed también filtra en Python lo que la DB ya trajo.** `backend/main.py:6949-6965`
sobre-pide `limit*5` filas y re-aplica `_is_market_relevant` en memoria, porque hay noticias
persistidas con el filtro viejo (pre 2026-05-26) que nunca se borraron. O sea: la tabla tiene
basura conocida y la solución elegida fue filtrarla en cada lectura, no purgarla.

**Retención:** 💀 ninguna por antigüedad. `news` crece indefinidamente y sólo se le borra el
backlog en inglés al bootear.

#### 1.7 `financial_events` — earnings / dividendos / splits

`[V]` `backend/main.py:1309-1321`.

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `ticker` | TEXT NOT NULL | | `_refresh_events_for_tickers` | 6 lectores (abajo) |
| `event_type` | TEXT NOT NULL | `earnings`\|`ex_dividend`\|`payment_date`\|`split` | ídem | ídem |
| `event_date` | TEXT NOT NULL | `YYYY-MM-DD` | ídem | ídem |
| `details` | TEXT | JSON | ídem | `backend/main.py:5851` |
| `confirmed` | INTEGER DEFAULT 0 | 1 si la fuente lo confirma | ídem | `backend/main.py:5851` |
| `source` | TEXT | siempre `'yfinance'` `[V]` (`backend/main.py:6020`) | ídem | `backend/main.py:5851` |
| `fetched_at` | TEXT NOT NULL | | ídem | **nadie** ⚠️ |

`[V]` Escritor único: `_refresh_events_for_tickers()` (`backend/main.py:5993-6022`), UPSERT por
`(ticker, event_type, event_date)`. Lectores: `backend/main.py:5850-5858`, `backend/main.py:6106`,
`backend/main.py:35345`, `backend/advisor_brief.py:249`, `backend/ai/builders/home.py:150`,
`backend/ai/builders/events.py:59`, `backend/ai/builders/dashboard_events.py:62`.

⚠️ Mismo patrón: la frescura la decide `_events_fetched_at`, dict en memoria con
`EVENTS_TTL = 6*3600` (`backend/main.py:5708-5709`, usado en `backend/main.py:6002` y `:6022`);
`fetched_at` en la tabla no se consulta. Y cuando el fetch devuelve vacío igual se marca como
"fetcheado" para no reintentar en loop (`backend/main.py:6004-6007`).

**Retención:** 💀 ninguna. Los eventos pasados quedan para siempre. 86 filas en la copia de dev
`[V]`. El acotado se hace en la lectura (`event_date >= today AND <= end_date`).

---

### 2. Del usuario, alrededor del mercado

#### 2.1 `bond_cashflow_skips` — cupones que el usuario dice que no cobró

`[V]` `backend/main.py:1330-1340`.

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `user_id` | INTEGER NOT NULL | | `POST /api/bonds/cashflow/skip` | `GET /api/bonds/cashflow/skips` |
| `broker` | TEXT NOT NULL | **linkeado por NOMBRE, no por FK** | ídem | ídem |
| `asset` | TEXT NOT NULL | upper-case forzado (`backend/main.py:10736`) | ídem | ídem |
| `date` | TEXT NOT NULL | fecha del pago teórico saltado | ídem | ídem |
| `reason` | TEXT | `'default'`, `'sold_before'`, … | ídem | ídem |
| `created_at` | TEXT NOT NULL | | ídem | ídem |

UNIQUE `(user_id, broker, asset, date)`; el POST es idempotente vía `ON CONFLICT ... DO UPDATE`
(`backend/main.py:10729-10739`). El DELETE está en `backend/main.py:10765-10770`.

⚠️ **Está en `NAME_KEYED_TABLES` pero el delete de broker no la limpia.** El comentario lo
declara como deuda conocida: "delete_broker limpia positions/operations/monthly_entries/
import_batches pero **NO toca import_normalized_tx ni bond_cashflow_skips** (orphan gap
conocido)" (`backend/main.py:4123-4126`). En el rename SÍ se cascadea
(`backend/main.py:4128-4135`).

`[V]` Sí se borra en el reset de cartera (`_RESET_PORTFOLIO_TABLES`, `backend/main.py:3609`) y
en el borrado de cuenta (tiene `user_id`).

#### 2.2 `push_subscriptions` — una fila por device

`[V]` `backend/main.py:1629-1640`.

| Campo | Tipo | Significado | Quién escribe | Quién lee | Notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK | | | `DELETE ... WHERE id=?` al 410 | |
| `user_id` | INTEGER NOT NULL | | `POST /api/push/subscribe` | `_send_push_to_user` | índice `idx_push_user` |
| `endpoint` | TEXT NOT NULL | URL único del browser | ídem | ídem | UNIQUE(user_id, endpoint) |
| `p256dh`, `auth` | TEXT NOT NULL | claves de cifrado del push | ídem | ídem | **material criptográfico en claro** |
| `user_agent` | TEXT | | ídem | **nadie** 💀 | |
| `created_at` | TEXT | | default | nadie `[V]` | |
| `last_used_at` | TEXT | "último uso" | **sólo al suscribir** | nadie 💀 | ⚠️ el nombre miente |

⚠️ 💀 **`last_used_at` no registra uso: registra la última suscripción.** Los tres únicos hits
de la columna en todo el backend son el `CREATE` (`backend/main.py:1637`) y el INSERT/UPSERT
(`backend/main.py:34071` y `:34077`) `[V]`. `_send_push_to_user()` (`backend/main.py:34114-34163`)
manda el push y **no lo actualiza**. Consecuencia práctica: no hay forma de podar devices
inactivos por antigüedad de uso; la única poda es reactiva, cuando el endpoint devuelve 404/410
(`backend/main.py:34153-34158`).

💀 `user_agent` se guarda y no se lee en ninguna parte `[V]`.

**Retención:** sólo el borrado reactivo por 410, más el barrido por `user_id` al borrar la cuenta.

---

### 3. IA — cache, cuota, memoria

#### 3.1 `ai_analyses_cache`

`[V]` `backend/main.py:1873-1889`.

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `cache_key` | TEXT PK | `sha256(uid:screen:tier:packet_hash)` | `set_cached` (`backend/ai/cache.py:126-146`) | `get_cached` (`backend/ai/cache.py:81-85`) |
| `user_id` | INTEGER NOT NULL | | ídem | está en el WHERE del get + índice |
| `screen` | TEXT NOT NULL | pantalla del análisis | ídem | `invalidate_for_user(screens=[...])` |
| `result_json` | TEXT NOT NULL | el análisis | ídem | ídem |
| `created_at` | TEXT | `datetime('now')` | ídem | nadie `[V]` |
| `expires_at` | TEXT NOT NULL | ISO de `utcnow()+TTL` | ídem | `get_cached` (en Python) y `cleanup_expired` |
| `packet_hash` | TEXT NOT NULL | sha256 del packet | ídem | nadie lee la columna `[V]` |
| `model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_create_tokens`, `cost_usd_cents` | | contabilidad de costo | ídem | telemetría |

⚠️ **El comentario del esquema quedó viejo en los dos datos que da.**
`backend/main.py:1868-1869` dice `cache_key = sha256(uid+screen+packet_json)` y `TTL 24h`. El
código real mete el **tier** en la clave (`_compute_keys`, `backend/ai/cache.py:67-72`) y el TTL
es por tier: free 72h, pro/admin 24h (`CACHE_TTL_BY_TIER`, `backend/ai/cache.py:44-48`).

💀 **`cleanup_expired()` existe y no lo llama nadie.** Definida en `backend/ai/cache.py:170-176`;
grep sobre todo `backend/` da un único hit, el de la definición `[V]`. Sumado a que no hay cron
de limpieza (§1.4), la tabla crece sin techo: el único borrado real es `invalidate_for_user`
(`backend/ai/cache.py:148-167`), que se llama desde 4 lugares `[V]`, y el reset de cartera
(`backend/main.py:3610`).

⚠️ Y si algún día se llamara, la comparación de `cleanup_expired` es de strings entre formatos
distintos: `expires_at` se guarda con `datetime.isoformat()` → `2026-09-06T12:00:00` (con `T`),
y el WHERE compara contra `datetime('now')` → `2026-09-06 12:00:00` (con espacio). Como
`'T'` (0x54) > `' '` (0x20), una fila vencida **hoy** no cae hasta que cambie el día. `[I]`
Deducido de `backend/ai/cache.py:125` (el `isoformat()`) contra `backend/ai/cache.py:174`
(el `datetime('now')`); el lector no tiene el problema porque hace la comparación en Python
(`backend/ai/cache.py:88-93`).

`[I]` La "pre-generación nocturna" que el docstring menciona como escritor
(`backend/ai/cache.py:6-7`) no la encontré: no hay job de pre-generación en el scheduler
(`backend/main.py:32534-32575`) ni ningún caller de `set_cached` fuera del path de request. **no
encontrado**.

#### 3.2 `ai_usage_daily` — el medidor de la cuota

`[V]` `backend/main.py:1893-1908`. PK compuesta `(user_id, date)`.

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `user_id`, `date` | PK | | los 6 UPSERT de `backend/ai/quota.py` | `get_current_usage` |
| `analyses_count` | INTEGER | análisis del día | `backend/ai/quota.py:433-438` | `backend/ai/quota.py:357-368`, `backend/billing/trial.py:656` |
| `hub_queries_count` | INTEGER | consultas al hub | `backend/ai/quota.py:446-451` | ídem |
| `chat_count` | INTEGER | consultas al chat | `reserve_chat` `backend/ai/quota.py:489-500`, `refund_chat` `:512-518` | ídem |
| `diag_dismiss_count` | INTEGER | "No me interesa" del diagnóstico | `backend/ai/quota.py:562-570` | ídem |
| `cost_usd_cents` | INTEGER | costo acumulado del día | todos los anteriores + `record_chat_cost` (`backend/ai/quota.py:527-534`) | auditoría de costos |

`chat_count` y `diag_dismiss_count` llegaron por ALTER (`backend/main.py:2547-2554`) — de las
pocas migraciones de esta sección que sí tienen guard, porque `ai_usage_daily` **sí** está en la
allowlist de `_table_cols`.

`[V]` **La reserva del slot de chat es un solo statement**, a propósito: el INSERT trae su propio
`WHERE (SELECT SUM(chat_count) …) < ?` y el `DO UPDATE` lo repite
(`backend/ai/quota.py:489-500`), y `ok = cur.rowcount > 0`. El comentario de
`backend/billing/trial.py:364-372` explica el mismo patrón en `credit_ledger` con el número
medido: "con tope 5 y 20 pedidos simultáneos entraron los 20" con check-then-act.

⚠️ **Limitación documentada por el propio código:** agrega por DÍA, sin hora, así que el "piso"
de la ventana rodante sólo puede ser un día y lo consumido hoy antes de un cambio de tier sigue
contando contra el techo nuevo (`backend/ai/quota.py:265-269`).

**Retención:** 💀 ninguna. La ventana de cuota es de 7 días (`WHERE date >= ?`,
`backend/ai/quota.py:365`) pero las filas viejas nunca se borran. Es una fila por usuario por
día activo, para siempre.

#### 3.3 `ai_tool_usage`

`[V]` `backend/main.py:1918-1928`. PK `(user_id, date, tool_name)`.

Escritor único: `_record_tool_usage()` (`backend/main.py:21218-21235`), UPSERT `count = count+1`,
best-effort (traga excepciones para no tumbar el tool). Lector único: el endpoint admin
`admin_ai_tool_usage` (`backend/main.py:18719-18760`), que agrega por tool y por tier.

El propósito está declarado en el esquema (`backend/main.py:1910-1917`): detectar tools no usadas,
patrones por tier, y abuso ("1 user con miles de calls a un tool").

**Retención:** ninguna; el lector acota con `days: int = 14`.

#### 3.4 `ai_user_facts` — memoria del coach

`[V]` `backend/main.py:1997-2013`.

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `id` | INTEGER PK | | | `backend/main.py:29385` |
| `user_id` | INTEGER NOT NULL | | `backend/main.py:29161-29166` | `backend/main.py:28336`, `:29351`, `:29358` |
| `content` | TEXT NOT NULL | texto libre, cap 280 chars | ídem | inyectado al system prompt |
| `source` | TEXT DEFAULT 'user_correction' | `user_correction`\|`ai_inferred`\|`manual` | ídem | listado |
| `is_active` | INTEGER DEFAULT 1 | soft-delete | `UPDATE ... SET is_active=0` (`backend/main.py:29391`) | filtro |
| `created_at`, `updated_at` | TEXT | | default / update | orden DESC |

`[V]` **El INSERT es un `SELECT ... WHERE` con dos subconsultas de tope**
(`backend/main.py:29161-29166`) — mismo patrón atómico que la cuota de chat. Y hay un
**índice único parcial** `ON ai_user_facts(user_id, content) WHERE is_active=1`
(`backend/main.py:2012-2013`) que impide que el LLM persista el mismo hecho 50 veces; el
comentario lo atribuye a "Auditoría #2 H5".

Se borra en el reset de cartera (`backend/main.py:3610`) y por `user_id` al borrar la cuenta.

---

### 4. Auth e identidad

#### 4.1 `email_verification_codes`

`[V]` `backend/main.py:2094-2103`.

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `id` | INTEGER PK | | | `UPDATE ... WHERE id=?` |
| `user_id` | INTEGER NOT NULL | | `_create_verification_code` (`backend/main.py:3052-3056`) | `backend/main.py:3264-3268` |
| `code` | TEXT NOT NULL | 6 dígitos sin cero inicial (`backend/main.py:3033-3035`) | ídem | ídem |
| `expires_at` | TEXT NOT NULL | `utcnow + EMAIL_CODE_TTL_MINUTES` | ídem | ídem |
| `used_at` | TEXT | | `backend/main.py:3286`, y el "invalidar previos" de `backend/main.py:3047-3051` | filtro |
| `created_at` | TEXT | | default | nadie `[V]` |

`[V]` Al pedir un código nuevo se marcan como `used_at = now` todos los previos sin usar
(`backend/main.py:3047-3051`), así que sólo hay uno vivo por usuario.

💀 **El "cleanup en cron de codes > 30 días" del comentario (`backend/main.py:2093`) no existe.**
El único DELETE de esta tabla es el borrado de usuarios no verificados y sin data del job de
lifecycle (`backend/billing/subscriptions.py:377`) `[V]`. Los códigos usados de cuentas vivas
quedan para siempre.

#### 4.2 `password_reset_tokens`

`[V]` `backend/main.py:2108-2117`. Token `secrets.token_urlsafe(32)` (256 bits), TTL 30 min según
el comentario; `used_at` al confirmar.

Escritura en `backend/main.py:3382-3390` (que primero invalida los previos con
`UPDATE ... SET used_at = datetime('now')`, mismo patrón que el OTP). Lectura y consumo en
`backend/main.py:3422-3427` y `backend/main.py:3446`. Índices en `token` y en `(user_id, used_at)`.

💀 Retención: **ninguna**. No hay DELETE de esta tabla en ningún lado `[V]`. Los tokens usados
y vencidos se acumulan indefinidamente (se van sólo si se borra la cuenta, por el barrido de
`user_id`).

#### 4.3 `login_history`

`[V]` `backend/main.py:2199-2208`.

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `user_id` | INTEGER NOT NULL | | `backend/main.py:3012-3015` | `backend/main.py:3000-3009` |
| `ip` | TEXT | IP del cliente (`_client_ip`) | ídem | se manda en el mail de alerta |
| `ua_hash` | TEXT | hash del user-agent | ídem | "¿es un device nuevo?" |
| `ua_brief` | TEXT | resumen legible del UA | ídem | mail de alerta |
| `created_at` | TEXT | | default | índice `(user_id, created_at DESC)` |

`[V]` Lógica: si el `ua_hash` no apareció antes **y no es el primer login ever**, se manda mail de
alerta (`backend/main.py:3000-3009` + `:3018-3029`). Todo el bloque está envuelto en try/except:
si falla, el login igual pasa (`backend/main.py:3030-3031`).

⚠️ 💀 **Retención: ninguna, y guarda IPs.** Una fila por login, para siempre, con IP en claro. Es
la tabla de esta sección con más carga de privacidad y la única sin ningún acotamiento (ni por
antigüedad ni por cantidad). Se borra sólo con la cuenta.

⚠️ El chequeo de "device nuevo" hace `SELECT COUNT(*)` sobre todo el historial del usuario en
cada login (`backend/main.py:3000-3002`); el índice `idx_login_history_user` lo cubre, pero el
costo crece linealmente con la vida de la cuenta.

---

### 5. Billing

#### 5.1 `subscriptions`

`[V]` `backend/main.py:2021-2042` + ALTER de `amount_usd` en `backend/main.py:2244-2245` y de los
tres flags de email en `backend/main.py:2238-2241`.

| Campo | Tipo | Significado | Quién escribe | Quién lee | Notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK | | | | |
| `user_id` | INTEGER NOT NULL | | los 2 INSERT | todos | índice |
| `mp_subscription_id` | TEXT | preapproval_id de MP / link_id de Rebill | `backend/main.py:26611`, `:27039-27044` | matching de webhooks | índice |
| `external_reference` | TEXT NOT NULL | `rendi-{uid}-{plan}-{period}` | ídem | | |
| `period` | TEXT NOT NULL | `monthly`\|`annual` | ídem | prorrateo | |
| `status` | TEXT DEFAULT 'pending' | ver abajo | 6 UPDATE | lifecycle | índice |
| `amount_ars` | INTEGER NOT NULL | monto en pesos | **siempre 0** | mails de bienvenida y recibo | 🔴 ver abajo |
| `amount_usd` | REAL | monto real cobrado | `backend/main.py:27031`, `:27044` | `backend/main.py:19600` | agregada por ALTER |
| `current_period_start` / `_end` | TEXT | ventana pagada | webhooks MP | `_downgrade_expired_cancellations` | |
| `next_charge_date` | TEXT | | webhooks | mail de recibo | |
| `init_point` | TEXT | URL del checkout | `backend/main.py:26611` | retry | validada contra allowlist de hosts Rebill (`backend/main.py:26594-26604`) |
| `last_payment_id` | TEXT | último pago procesado | `backend/main.py:27701` | idempotencia de mails | |
| `cancelled_at` | TEXT | | `backend/billing/subscriptions.py:546` | | |
| `welcome_email_sent_at` | TEXT | idempotencia | `backend/main.py:27677` | `backend/main.py:27662` | |
| `cancellation_email_sent_at` | TEXT | idempotencia | `backend/main.py:27779` | | |
| `expiration_reminder_sent_at` | TEXT | idempotencia | `backend/billing/subscriptions.py:433` | | |
| `created_at`, `updated_at` | TEXT | | | | |

⚠️ **`status`: el comentario y el código no coinciden.** El comentario declara
`'pending'|'authorized'|'paused'|'cancelled'|'failed'` (`backend/main.py:2019-2020`). El código
escribe `pending` (INSERT), `authorized`, `paused`, `cancelled` (los tres del `status_map` de
`backend/billing/subscriptions.py:581-586`) y **`expired`** (`backend/billing/subscriptions.py:493`).
`'failed'` **no lo escribe nadie** `[V]`.

🔴 **`amount_ars` es legacy y se inserta en 0, pero los mails lo siguen imprimiendo como plata.**
Los dos únicos INSERT pasan el literal `0`:

```
backend/main.py:26609-26611      VALUES (?, ?, ?, ?, 'pending', 0, ?, ...)
backend/main.py:27041-27044      VALUES (?, ?, ?, ?, 'authorized', 0, ?, ...)
```

Y los mails leen esa columna y la formatean como pesos: `_maybe_send_welcome_email` hace
`amount_ars=row["amount_ars"]` (`backend/main.py:27669`) y `_process_payment_event` hace lo mismo
para el recibo (`backend/main.py:27731`), contra `emails.send_welcome_pro(...)` /
`emails.send_receipt(...)` que lo pasan por `_fmt_ars()` (`backend/billing/emails.py:346`, `:379`).
El comentario del ALTER ya lo reconoce: "los planes son USD desde la migración a Rebill —
amount_ars queda como legacy" (`backend/main.py:2242-2243`).
`[I]` **El impacto es latente, no activo**: esas dos funciones cuelgan del webhook de
MercadoPago (`POST /api/billing/webhook`, `backend/main.py:27501`), y las suscripciones nuevas
son de Rebill, que tiene su propio path. Pero el endpoint sigue montado y las filas nuevas ya
tienen el 0 puesto: si llega un evento MP contra una fila creada por el path Rebill, el mail sale
con `$0`.

#### 5.2 `billing_events` — log de webhooks

`[V]` `backend/main.py:2053-2067`.

| Campo | Tipo | Significado | Quién escribe | Quién lee | Notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK | | | | |
| `mp_event_id` | TEXT | `id` top-level del payload | `backend/main.py:26874`, `:27546` | `UPDATE ... WHERE mp_event_id=?` | |
| `mp_event_type` | TEXT | `rebill:{tipo}` o el tipo MP | ídem | display admin | |
| `mp_data_id` | TEXT | preapproval/payment id **o el rendi_user_id** | ídem | `WHERE mp_data_id = ?` | ⚠️ sobrecargado |
| `user_id` | INTEGER | "decoded desde external_reference (si match)" | **nadie** 💀 | `WHERE ... OR user_id = ?` | 🔴 |
| `signature_valid` | INTEGER | 1/0 | ídem | display admin | |
| `processed` | INTEGER | 1 tras procesar | `backend/main.py:26926`, `:27577` | display admin | |
| `raw_payload` | TEXT | JSON completo del webhook | ídem | resumen admin (`backend/main.py:19636`) | 🔴 PII |
| `created_at` | TEXT | | default | orden | |

🔴 💀 **`user_id` nunca se escribe.** Los dos únicos INSERT
(`backend/main.py:26871-26883` para Rebill, `backend/main.py:27540-27553` para MP) no incluyen la
columna, y no hay ningún `UPDATE billing_events SET user_id` `[V]`. Dos consecuencias:

1. El índice `idx_billing_events_user ON billing_events(user_id)` (`backend/main.py:2064-2065`)
   indexa una columna siempre NULL.
2. **El barrido de borrado de cuenta no borra ni una fila de esta tabla.** `_wipe_user_rows`
   borra con `DELETE FROM {t} WHERE user_id=?` sobre toda tabla que tenga esa columna
   (`backend/main.py:3850-3854`); con `user_id` NULL, ninguna fila matchea. Los `raw_payload` de
   los webhooks de esa persona —que `[I]` es donde el procesador manda email del pagador y demás
   datos, no lo verifiqué contra un payload real— sobreviven al "derecho al olvido".

El propio lector admin ya sabe que la columna no sirve sola y busca por las dos vías:
`WHERE mp_data_id = ? OR user_id = ?` (`backend/main.py:19621-19631`), con el comentario "el
rebill-webhook guarda el rendi_user_id en `mp_data_id`; el flujo MP setea `user_id`" — **la
segunda mitad de ese comentario es falsa** `[V]`.

⚠️ **`UPDATE ... WHERE raw_payload = ?`.** El marcado de procesado del path Rebill compara el
JSON completo como texto (`backend/main.py:26924-26928`). No hay índice sobre `raw_payload`, así
que es un full scan de una tabla append-only; y si el mismo payload llegó dos veces (que es
exactamente el caso que este log quiere capturar), marca las dos filas.

**Retención:** 💀 ninguna. Append-only sin poda y sin borrado por cuenta.

#### 5.3 `plan_events` — telemetría del paywall

`[V]` `backend/main.py:2073-2088`.

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `user_id` | INTEGER NOT NULL | | `POST /api/plan/track` (`backend/main.py:26350-26362`) | `backend/main.py:18831` |
| `tier` | TEXT NOT NULL | tier al momento del evento | ídem | `backend/main.py:18803-18820` |
| `event_name` | TEXT NOT NULL | contra whitelist `_ALLOWED_PLAN_EVENTS` | ídem | ídem |
| `feature_id` | TEXT | `comportamiento.full`, … | ídem | índice `(feature_id, event_name)` |
| `source` | TEXT | `behavioral_grid`, … | ídem | ídem |
| `props_json` | TEXT | extras | ídem | `[I]` no vi lector |
| `created_at` | TEXT | | default | índice |

`[V]` El endpoint devuelve 204 y descarta en silencio los `event_name` fuera de la whitelist
(`backend/main.py:26359-26363`), a propósito: "es telemetría, no acción crítica".

**Retención:** ninguna; se borra con la cuenta (tiene `user_id`) — lo que significa que **borrar
la cuenta borra la telemetría de conversión de esa persona**, a diferencia de `credit_ledger`,
que sí se protege. `[I]` No sé si eso es deliberado; el comentario de `_NO_BORRAR_ANONIMIZAR`
sólo nombra `credit_ledger`.

#### 5.4 `credit_ledger` — el libro mayor del crédito

`[V]` `backend/main.py:2332-2349`. Es la tabla de billing más cargada de reglas.

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `id` | INTEGER PK | | | |
| `user_id` | INTEGER NOT NULL | **se anonimiza a 0, no se borra** | 7 escritores | `backend/main.py:19614` |
| `kind` | TEXT NOT NULL | ver abajo | ídem | `backend/billing/trial.py:79`, `:1008`, `:1121` |
| `amount_usd` | REAL NOT NULL | + agrega crédito, − consume | ídem | diagnóstico admin |
| `days_delta` | REAL NOT NULL | idem en tiempo | ídem | ídem |
| `from_plan`/`from_period`/`to_plan`/`to_period` | TEXT | transición | ídem | `backend/billing/trial.py:1008` (`l.to_plan='pro'`) |
| `active_until_before`/`_after` | TEXT | ventana antes/después | ídem | diagnóstico |
| `source_subscription_id` | TEXT | sub de Rebill | `backend/billing/credits.py:255-266` | idempotencia |
| `payment_id` | TEXT | **idempotency key** | ídem | idempotencia |
| `note` | TEXT | texto libre | ídem | diagnóstico |
| `created_at` | TEXT | | default | `substr(replace(created_at,'T',' '),1,10)` para el tope mensual |

⚠️ **El enum de `kind` del comentario está incompleto.** Declara
`'payment' | 'plan_change' | 'manual_adjust' | 'expiration'` (`backend/main.py:2335`). El código
escribe además:

| kind | dónde |
|---|---|
| `payment` | `backend/billing/credits.py:255` |
| `plan_change` | `backend/billing/credits.py:391` |
| `manual_adjust` | `backend/main.py:2431-2440` (backfill), `backend/main.py:19783-19790` |
| `expiration` | `backend/billing/subscriptions.py:215-225` y `:500-510` |
| **`comp`** | `backend/main.py:19940-19943` (regalar plan desde admin) |
| **`trial`** | `backend/billing/trial.py:373-382` y `:389-397` |
| **`trial_step`** | `backend/billing/trial.py:549-553` |

`[V]` **Tres mecanismos de integridad, todos verificables:**
1. *Idempotencia de pagos en dos capas*: chequeo app-side por `(source_subscription_id,
   payment_id, kind='payment')` (`backend/billing/credits.py:185-206`) **y** un `CREATE UNIQUE
   INDEX ... WHERE payment_id IS NOT NULL AND source_subscription_id IS NOT NULL`
   (`backend/main.py:2364-2368`), con captura del `IntegrityError` para la carrera
   (`backend/billing/credits.py:265`).
2. *El orden de la migración está documentado con la razón*: `CREATE TABLE` → `ALTER` →
   `CREATE INDEX`, en tres pasos separados, porque el índice necesita que la columna exista
   (`backend/main.py:2325-2331` y `:2354-2368`).
3. *El tope mensual de trials se hace cumplir en el INSERT*, no en un check-then-act
   (`backend/billing/trial.py:372-388`), con el número medido en el comentario: "con tope 5 y 20
   pedidos simultáneos entraron los 20".

`[V]` **Es la única tabla del sistema que se anonimiza en vez de borrarse.**
`_NO_BORRAR_ANONIMIZAR = ("credit_ledger",)` (`backend/main.py:3836`) y el `UPDATE ... SET
user_id=0` de `backend/main.py:3870-3875`. La razón está escrita completa
(`backend/main.py:3856-3868`): el barrido genérico se la llevaba y "borrar la cuenta DEVOLVÍA un
cupo: crear, activar la prueba, borrar y repetir salteaba el único freno de gasto que hay". Usan
`0` y no NULL porque la columna es NOT NULL y en SQLite cambiarlo obliga a reconstruir la tabla.

⚠️ El conteo del tope mensual usa `substr(replace(created_at,'T',' '),1,10) >= ?`
(`backend/billing/trial.py:76-81`) para normalizar los dos formatos de fecha que conviven en la
columna (los INSERT explícitos usan `datetime.utcnow().isoformat()` con `T`, el DEFAULT usa
`datetime('now')` con espacio). El comentario documenta el bug que eso arregló: "con tope 3
entraron 8 trials el día 1 y el mes cerró con 11".

**Retención:** append-only por diseño. Nunca se borra.

#### 5.5 `trial_consumed` — "este email ya usó su prueba"

`[V]` `backend/main.py:2303-2308`.

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `email_key` | TEXT PK | `sha256(normalizar_email(email))` | `_mark_email_consumed` (`backend/billing/trial.py:238-246`) | `_email_consumed` (`backend/billing/trial.py:227-233`) |
| `consumed_at` | TEXT NOT NULL | ISO | ídem | nadie `[V]` |

`[V]` **Existe precisamente para sobrevivir al borrado de cuenta.** El comentario
(`backend/main.py:2299-2302`) dice: "borrar la cuenta borra la fila de users, y con ella
`trial_used_at` — lo que habilitaba trials infinitos con el mismo mail". Y como **no tiene
columna `user_id`**, el barrido dinámico de `_wipe_user_rows` no la toca `[V]`.

`[V]` La normalización previa (`normalizar_email`, `backend/billing/trial.py:~228` hacia arriba,
visible en `backend/billing/trial.py:230-240`) tira el `+alias`, y para gmail/googlemail saca los
puntos y unifica el dominio. El propio docstring acota la ambición: "No pretende frenar a un
decidido con dos casillas de verdad: corta el abuso trivial".

⚠️ Se guarda hasheado a propósito ("sirve para comparar, no para reconstruir la casilla",
`backend/billing/trial.py:214-216`). Esto es lo correcto y contrasta con `broadcast_send_log`
(`backend/main.py:1937-1942`), que guarda el **email en claro**, tampoco tiene `user_id` y por lo
tanto también sobrevive al borrado de cuenta `[V]`.

**Retención:** por diseño, para siempre.

#### 5.6 `trial_email_log`

`[V]` `backend/main.py:2313-2319`. PK `(user_id, kind)`.

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `user_id` | INTEGER PK(1) | | `_mark_sent` (`backend/billing/trial.py:596-608`) | `_already_sent` (`backend/billing/trial.py:584-593`) |
| `kind` | TEXT PK(2) | `started`\|`pro_ending`\|`ending_soon`\|`ended` (`backend/billing/trial.py:578-581`) | ídem | ídem |
| `sent_at` | TEXT NOT NULL | ISO | ídem | nadie `[V]` |

`[V]` Idempotencia **propia**, deliberadamente no apoyada en `subscriptions`: el comentario del
esquema (`backend/main.py:2309-2312`) explica que un usuario de trial no tiene fila ahí y "por eso
el aviso genérico de vencimiento le salía todos los días (audit)". Además `_mark_sent` **marca
antes de mandar** y devuelve si ganó la carrera (`INSERT OR IGNORE` + `rowcount > 0`), y
`_already_sent` es **fail-closed**: si no puede consultar, devuelve `True` y no manda
(`backend/billing/trial.py:590-593`).

⚠️ Tiene `user_id`, así que **el barrido de borrado de cuenta sí se la lleva**. Borrar y recrear
la cuenta resetea la idempotencia de los mails de trial — aunque `trial_consumed` impide que
haya un trial nuevo que justifique mandarlos.

---

### 6. Importación

Es el subsistema con más filas del producto. Cita medida en el repo: la base sintética que
imita producción declara **933 MB · ~3,4M filas · 60 tablas · ~1.084 usuarios**, y que "el 92% de
las filas es andamio de import (`import_raw_rows.raw_json`, el CSV entero guardado para
siempre). El negocio real son ~250 mil filas" (`backend/scripts/base_sintetica.py:9-12`). El
copiador a Postgres avisa cada 250.000 filas porque "`import_raw_rows` (3,1M) es una caja negra"
(`backend/scripts/copiar_a_postgres.py:63-65`).

#### 6.1 `import_batches` — un upload

`[V]` `backend/main.py:2449-2467`, más 3 ALTER (`backend/main.py:2612-2645`).

| Campo | Tipo | Significado | Quién escribe | Quién lee | Notas |
|---|---|---|---|---|---|
| `id` | TEXT PK | uuid del batch | `backend/importing/pipeline.py:704-708` | todo el subsistema | PK de texto |
| `user_id` | INTEGER NOT NULL | | ídem | ídem | índice `(user_id, created_at DESC)` |
| `broker` | TEXT NOT NULL | **por nombre** | ídem | ídem | está en `NAME_KEYED_TABLES` |
| `parser_format` | TEXT NOT NULL | qué parser lo leyó | ídem | diagnósticos | |
| `file_name` | TEXT | | ídem | UI | |
| `file_hash` | TEXT NOT NULL | dedup de archivo idéntico | ídem | índice `(user_id, file_hash, status)` | |
| `total_rows`/`valid_rows`/`invalid_rows` | INTEGER | | ídem | UI | |
| `status` | TEXT NOT NULL | `preview` → `confirmed` → `reverted` | `backend/importing/persister.py:467`, `:1665` | **~40 sitios filtran `status='confirmed'`** | |
| `created_at`/`confirmed_at`/`reverted_at` | TEXT | | ídem | | |
| `route_by_currency` | INTEGER NOT NULL DEFAULT 0 | rutear filas USD al sub-broker `· USD` | `backend/importing/pipeline.py:704-708` | `backend/importing/persister.py:245-248`, `backend/importing/pipeline.py:1166` | ALTER `backend/main.py:2615-2616` |
| `fund_price_overrides` | TEXT | JSON precio-por-cuotaparte de FCI que Rendi no cotiza | path Balanz | `backend/importing/recompute_backfill.py:329` | ALTER `backend/main.py:2624-2625` |
| `override_info` | TEXT | JSON de lo que la foto **decidió** | `backend/main.py:30375-30377` | **nadie** ⚠️ | ALTER `backend/main.py:2643-2644` |

⚠️ **`override_info` es write-only a propósito, y el comentario lo declara sin vueltas.**
`backend/main.py:2627-2642`:
> 🔴 EXISTE PARA CERRAR UN PUNTO CIEGO DE MEDICIÓN, no para el producto. […] todo lo que sabemos
> de `over` está medido sobre la población que SOBREVIVIÓ tres filtros (n=21 sobre la copia de
> prod del 2026-08-16) […] Con esto, en un mes el número está.

Y aclara que **no lleva índice a propósito**: "Un `CREATE INDEX` sobre una columna recién
agregada es lo que tiró prod 20 minutos el 2026-08-02". Ese incidente aparece citado tres veces
en `init_db()` (`backend/main.py:2226-2229`, `:2640-2642`, `:2606-2610`) y explica la forma rara
de varias migraciones de esta sección.

#### 6.2 `import_raw_rows` — el archivo original, fila por fila

`[V]` `backend/main.py:2469-2477`.

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `id` | INTEGER PK | | `backend/importing/persister.py:176-181` | FK de las otras dos tablas |
| `batch_id` | TEXT NOT NULL **REFERENCES import_batches(id) ON DELETE CASCADE** | | ídem | índice |
| `row_index` | INTEGER NOT NULL | posición en el archivo | ídem | `backend/main.py:31649` |
| `raw_json` | TEXT NOT NULL | **la fila cruda entera** | ídem | `backend/main.py:17195`, `:18231`, `:31649` |
| `status` | TEXT NOT NULL | `valid` / rechazada | ídem | `backend/flujos.py:56` |
| `errors_json` | TEXT | por qué se rechazó | ídem | `backend/flujos.py:50-56` |

🔴 ⚠️ **Es el 92% de las filas de la base y no tiene ninguna política de retención.** No hay
DELETE por antigüedad, ni por batch revertido: el único borrado es en cascada al borrar la
cuenta (`backend/main.py:3841-3846` y `:3688-3691`) `[V]`. El "vaciado de `raw_json`" que
mencionan los scripts de migración (`backend/scripts/verificar_copia.py:535-599`) es una
operación **manual, de una sola vez, para la migración a Postgres**, y el copiador aclara:
"⚠️ **EL VACIADO DE `raw_json` NO ES PARTE DE ESTO.** Se decidió migrar todo"
(`backend/scripts/copiar_a_postgres.py:16-17`). En el código de la app no existe.

⚠️ El `ON DELETE CASCADE` está declarado pero **SQLite no lo aplica sin
`PRAGMA foreign_keys=ON`**, y el propio código lo dice: "SQLite no soporta FK ON DELETE CASCADE
sin enable_foreign_keys=ON, y nuestras FKs no están declaradas"
(`backend/billing/subscriptions.py:375-376`). Por eso el borrado hace la cascada a mano, en el
orden correcto, resolviendo primero los `batch_ids` (`backend/main.py:3839-3846`).

#### 6.3 `import_normalized_tx` — el evento normalizado

`[V]` `backend/main.py:2479-2510`, más 6 ALTER (`backend/main.py:2556-2611`). Es la tabla desde la
que **se re-deriva la cartera** en cada rebuild.

| Campo | Tipo | Significado | Quién escribe | Quién lee | Notas |
|---|---|---|---|---|---|
| `id` | INTEGER PK | | `backend/importing/pipeline.py:753-757` | | |
| `batch_id` | TEXT NOT NULL FK | | ídem | índice `idx_import_norm_batch` | |
| `raw_row_id` | INTEGER NOT NULL FK | trazabilidad al CSV | ídem | joins de diagnóstico | |
| `date` | TEXT NOT NULL | | ídem | `_import_flows_for_period` (`backend/main.py:600-616`) | |
| `broker` | TEXT NOT NULL DEFAULT '' | **por nombre** | ídem | ídem | ALTER `backend/main.py:2558-2560`; en `NAME_KEYED_TABLES` |
| `operation_type` | TEXT NOT NULL | `BUY`/`SELL`/`DEPOSIT`/`WITHDRAW`/… | ídem | ídem | |
| `asset_symbol`/`asset_name`/`asset_type` | TEXT | | ídem | rebuild | |
| `quantity`/`unit_price`/`gross_amount`/`fees`/`taxes` | REAL | | ídem | rebuild | |
| `currency`/`settlement_currency` | TEXT | | ídem | rebuild | |
| `notes` | TEXT | | ídem | | |
| `created_position_id`/`created_operation_id` | INTEGER | qué generó esta fila | `backend/importing/rebuild.py:667`, `:691`; `backend/main.py:15123` | `backend/importing/maturity.py:319-323` | conviven con `import_op_links` |
| `transfer_out` | INTEGER NOT NULL DEFAULT 0 | cierre-a-costo explícito | ídem | rebuild | ALTER `backend/main.py:2585-2587`; razón en `backend/main.py:2577-2584` |
| `tc_compra` | REAL | ARS/USD de la compra | ídem | vista "costo al dólar de la compra" | ALTER `backend/main.py:2594-2596` |
| `excluded_at`/`excluded_by` | TEXT/INTEGER | **tombstone reversible** | borrado de op importada | `rebuild._full_events` y `_import_flows_for_period` | ALTER `backend/main.py:2601-2604` |
| `fingerprint` | TEXT | dedup cross-batch a nivel fila | `backend/importing/pipeline.py:740` | `backend/importing/pipeline.py:236-251`, `:724-741` | ALTER `backend/main.py:2562-2566` |
| `gross_amount_usd` | REAL | USD **estampado al write-time** | `_stamp_gross_amount_usd` | `backend/main.py:605` | ALTER `backend/main.py:2574-2576` |

`[V]` **`gross_amount_usd` es el arreglo de un drift histórico**, y el comentario lo explica
entero (`backend/main.py:2567-2573`): antes `monthly_entries.deposits` acumulaba USD dividiendo
por el `tc_blue` **actual**, así que cambiar el TC en config y recalcular reescribía el histórico.
NULL en filas legacy → los lectores caen a la conversión runtime.

`[V]` **El tombstone `excluded_at` es lo que hace que borrar una operación importada no la
resucite en el próximo import**: el rebuild filtra `excluded_at IS NULL`, y `_import_flows_for_period`
—que ES la fuente de `monthly_entries.deposits`, o sea del capital aportado— también
(`backend/main.py:596-613`). El docstring lo dice sin ambigüedad: "Sin este filtro, un depósito
borrado seguiría contando en el aportado para siempre".

⚠️ **El índice de `excluded_at` se creó tres veces mal antes de quedar bien**, y el comentario es
un manual de la trampa (`backend/main.py:2606-2610`): el `CREATE INDEX` va **después** del ALTER
y **fuera del `if`**, "en el bloque de esquema corría antes de que la columna existiera y tumbaba
el arranque contra cualquier base ya creada ('no such column: excluded_at' → boot loop → 502)".

⚠️ **Dedup con dos fingerprints en paralelo.** `_row_fingerprint` y `_row_fingerprint_legacy`
(`backend/importing/pipeline.py:157` y `:164`), y el chequeo prueba los dos
(`backend/importing/pipeline.py:250-251`, `:741`). El comentario explica por qué: "sin esto,
estabilizar el fingerprint habría duplicado una vez más a todo el […]"
(`backend/importing/pipeline.py:167`).

#### 6.4 `import_op_links` — el mapeo fila → objetos creados

`[V]` `backend/main.py:2532-2544`.

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `id` | INTEGER PK | | persister | |
| `batch_id` | TEXT NOT NULL FK | | ídem | índice `idx_import_op_links_batch` |
| `raw_row_id` | INTEGER FK | | ídem | `backend/main.py:13110`, `:13117`, `:14469` |
| `position_id` | INTEGER | | ídem | `backend/main.py:8323`, `:12760`, `:13539` |
| `operation_id` | INTEGER | | ídem | `backend/main.py:12466`, `:13015`, `:13474` |

Existe porque una fila puede generar N objetos (una venta FIFO genera N filas en `operations`)
(`backend/main.py:2529-2531`).

`[V]` **Es también el discriminante "importado vs. manual"** en todo el producto: hay consultas
del estilo `AND o.id NOT IN (SELECT operation_id FROM import_op_links WHERE operation_id IS NOT
NULL)` para aislar lo cargado a mano (`backend/main.py:13474`, `:13539`).

⚠️ El índice `idx_import_op_links_op ON import_op_links(operation_id)`
(`backend/main.py:2541-2544`) tiene su propia historia escrita: "Sin este índice, cada lookup era
un full scan de la tabla — con ~150k links, el panel de migración hacía timeout al listar
candidatos".

#### 6.5 `import_mappings` — plantillas de mapeo de columnas

`[V]` `backend/main.py:2650-2658`. UNIQUE `(user_id, name)`.

| Campo | Tipo | Significado | Quién escribe | Quién lee |
|---|---|---|---|---|
| `id` | INTEGER PK | | `POST /api/imports/mappings` (`backend/main.py:31690-31695`) | `DELETE .../{mid}` |
| `user_id` | INTEGER NOT NULL | | ídem | `GET /api/imports/mappings` (`backend/main.py:31671-31675`) |
| `name` | TEXT NOT NULL | nombre de la plantilla | ídem | ídem |
| `mapping_json` | TEXT NOT NULL | `{columns, defaults}` | ídem | ídem |
| `created_at` | TEXT | | default | se devuelve |

`[V]` **No es una tabla muerta**: la consume el wizard —
`frontend/src/components/import/ImportWizard.jsx:287` (list), `:301` (save), `:314` (delete). Está
excluida del reset de cartera a propósito (`backend/main.py:3598-3600`).

#### 6.6 `import_incidents` — 💀 la tabla fantasma

🔴 **Existe en la base de dev, no existe en el código de `main`.**

`[V]` `grep -rn "import_incidents"` sobre todo el repo en `b74f450f` da **cero** hits. No está en
`backend/main.py`, no está en `backend/schema_pg.sql`
(`grep -c import_incidents backend/schema_pg.sql` → 0), no está en ningún test.

`[V]` Pero está en la copia de la base de desarrollo, con esta forma:

```
sqlite3 backend/trading.db ".schema import_incidents"
CREATE TABLE import_incidents (
    id TEXT PRIMARY KEY, batch_id TEXT, user_id INTEGER NOT NULL,
    parser_format TEXT, total_rows INTEGER NOT NULL DEFAULT 0,
    valid_rows INTEGER NOT NULL DEFAULT 0, invalid_rows INTEGER NOT NULL DEFAULT 0,
    new_codes_json TEXT, sample_json TEXT, diagnosis_text TEXT, diagnosis_model TEXT,
    status TEXT NOT NULL DEFAULT 'new', notified_at TEXT,
    created_at TEXT DEFAULT (datetime('now')), reviewed_at TEXT, reviewed_by INTEGER
);
CREATE INDEX idx_import_incidents_user   ON import_incidents(user_id, created_at DESC);
CREATE INDEX idx_import_incidents_status ON import_incidents(status, created_at DESC);
```

`[I]` Por la forma de las columnas (`new_codes_json`, `sample_json`, `diagnosis_text`,
`diagnosis_model`, `status='new'`, `notified_at`, `reviewed_by`) esto es el "Import Guardian":
una tabla que iba a capturar cada import problemático, diagnosticarlo con un LLM y notificar al
admin. Coincide con lo que la memoria del proyecto describe como *proyecto Import Guardian*
("nunca se deployó y no cazaba los bugs reales"), reemplazado por el chequeador de invariantes.
No lo verifiqué contra el historial de git (no corrí git, por la regla read-only) — es
inferencia sobre la forma de la tabla.

**Consecuencia operativa:** en cualquier base creada por una rama que sí tenía este `CREATE`, la
tabla sigue ahí, sin lector ni escritor, y `_wipe_user_rows` **sí la va a barrer** al borrar una
cuenta (tiene `user_id`, y el barrido es dinámico sobre `sqlite_master`,
`backend/main.py:3846-3854`). O sea: código muerto que igual participa del borrado.

---

### 7. Retención y limpieza: lo que dicen los comentarios vs. lo que corre

`[V]` **Los únicos jobs periódicos del proceso son cinco** (`backend/main.py:32534-32575`):

| id | cron (UTC) | qué hace | limpia algo de esta sección? |
|---|---|---|---|
| `daily_snapshot` | 02:59 | snapshot diario | escribe `fx_rates_daily` y `asset_last_price`; no borra |
| `iol_lab_refresh` | cada hora, min 7 | renueva tokens IOL | no |
| `subscription_lifecycle` | 03:30 | downgrades, pendings stale, sync MP, mails de trial, borrado de no-verificados | borra `email_verification_codes` **sólo** de usuarios no verificados sin data (`backend/billing/subscriptions.py:377`) |
| `backup_db` | 03:45 | backup de la SQLite | no |
| `fci_refresh` | 12:10 | precios FCI | no |

Contra eso, las promesas escritas en el esquema:

| Comentario | Cita | Realidad |
|---|---|---|
| "Cleanup: cron diario borra rows > 7 días" (`yfinance_cache`) | `backend/main.py:1955` | 💀 no existe |
| "Cleanup en cron de codes > 30 días" (`email_verification_codes`) | `backend/main.py:2093` | 💀 no existe |
| "`cleanup_expired` … Para cron nocturno" (`ai_analyses_cache`) | `backend/ai/cache.py:170` | 💀 función sin caller |

Y las tablas de esta sección **sin ninguna poda, de ningún tipo**: `news`, `financial_events`,
`bond_indices_daily`, `fx_rates_daily`, `asset_last_price`, `yfinance_cache`,
`ai_analyses_cache`, `ai_usage_daily`, `ai_tool_usage`, `password_reset_tokens`,
`email_verification_codes` (para cuentas vivas), `login_history`, `billing_events`,
`plan_events`, `credit_ledger`, `trial_consumed`, `import_batches`, `import_raw_rows`,
`import_normalized_tx`, `import_op_links`.

Las tres únicas purgas que existen son **de arranque, no de cron**, y **no corren en Postgres**
(§0): el backlog de noticias en inglés (`backend/main.py:1287-1294`), el cache yfinance de `.BA`
envenenado (`backend/main.py:2661-2670`) y el backfill de crédito (`backend/main.py:2380-2440`).

---

### 8. Cache vs. fuente de verdad

Clasificación de las 28 tablas de esta sección. La pregunta operativa es: **si mañana esta tabla
aparece vacía, ¿qué se pierde?**

#### (a) Cache puro — se puede truncar sin perder nada

| Tabla | Por qué | Cómo se reconstruye |
|---|---|---|
| `yfinance_cache` | Payloads derivados de una API pública; el lector hace fetch en el miss (`backend/main.py:21136-21158`) | sola, al primer uso. Costo: latencia (1-3s por call, según `backend/main.py:1944-1946`) |
| `news` | Feed público de Google News RSS, dedup por `(source, external_id)` | sola, pero **sólo hacia adelante**: el RSS da los últimos N items, no el histórico. Se pierde el archivo viejo — que hoy nadie lee más allá de los últimos ~75 (`limit*5` de `backend/main.py:6959`) |
| `financial_events` | Derivada de yfinance, UPSERT por `(ticker, event_type, event_date)` | sola, al primer request que toque esos tickers |
| `bond_indices_daily` | La serie CER completa la vuelve a bajar `_fetch_cer_series` (`backend/main.py:5572-5591`) | sola, en el próximo request al endpoint |
| `fci_prices` | `vcp/1000` de ArgentinaDatos | sola: `bootstrap()` en cada boot + cron 12:10 |
| `fci_catalog` | Idem, se re-seedea entero | sola, mismo camino |
| `ai_analyses_cache` | Respuestas de LLM cacheadas por packet | sola, pagando tokens de nuevo |
| `broadcast_send_log` *(adyacente)* | Idempotencia de un broadcast puntual | no se reconstruye, pero truncarla sólo arriesga un mail duplicado |

⚠️ Matiz sobre `news` y `financial_events`: son "cache puro" respecto de la **corrección**, no
del **contenido**. La fuente externa no reexpone el pasado, así que truncar pierde archivo. Como
ningún lector va más atrás de una ventana corta, lo cuento como (a).

#### (b) Derivada pero cara de recomputar

| Tabla | Por qué no es (a) | Qué cuesta reconstruirla |
|---|---|---|
| `fx_rates_daily` | Se reconstruye desde argentinadatos (`backend/main.py:4710-4780` para el blue, `:4792-4829` para el MEP) **pero es el insumo del replay determinístico**. Todo el P&L histórico dolarizado depende de ella (`backend/fx.py:1-38`) | Una llamada HTTP y ~5.700 filas. El riesgo no es el costo: es que si la fuente ya no publica un día que sí teníamos, ese día queda NULL para siempre y `fx.py` cae al valor anterior sin avisar |
| `asset_last_price` | Deriva de precios de mercado, pero **nadie guarda el pasado**: cuando un símbolo deja de cotizar, esta fila es el último precio que existió. Sin ella la posición vuelve al fallback anterior — valuar a costo, que es el bug que la tabla existe para no tener (`backend/main.py:1966-1970`) | Se repuebla para los símbolos que hoy cotizan; los delisted no vuelven |
| `import_normalized_tx` | Es el input del rebuild: de acá se re-derivan positions y operations. Se podría reconstruir desde `import_raw_rows` re-parseando | **Muy caro y no idempotente en la práctica**: los campos estampados al write-time (`gross_amount_usd`, `tc_compra`) y el tombstone `excluded_at` **no están en el CSV**. Re-parsear resucitaría lo borrado y re-estamparía el FX. En rigor, por `excluded_at`, esta tabla tiene un pedazo de (c) |
| `import_op_links` | Se re-genera al re-confirmar un batch | Reconstruirla implica revertir y re-confirmar, o sea tocar la cartera del usuario. Y mientras no esté, todo lo importado se ve como "manual" (`backend/main.py:13474`) |
| `ai_user_facts` | El usuario podría volver a decirlos | No se recupera solo: es memoria que el usuario ya invirtió tiempo en darle al bot |
| `subscriptions` | El estado real vive en Rebill/MP y hay un `_sync_authorized_with_mp` (`backend/billing/subscriptions.py:556-598`) | Recuperable parcialmente; se pierden los flags de idempotencia de mails y el histórico de cancelaciones |

#### (c) Fuente de verdad irrecuperable

| Tabla | Por qué |
|---|---|
| `import_raw_rows` | Es **el archivo del usuario**. No hay copia en ningún otro lado. Es también el 92% de las filas de la base (`backend/scripts/base_sintetica.py:9-12`): el trade-off "archivo eterno vs. tamaño" está tomado, y tomado a favor del archivo |
| `import_batches` | La cabecera de cada import: qué parser, qué hash, qué estado, `route_by_currency`, `fund_price_overrides`. Sin ella los raw rows son huérfanos y el rebuild no sabe qué es `confirmed` |
| `credit_ledger` | **Append-only por diseño y por defensa.** Es lo que hace cumplir el tope mensual de trials (`backend/billing/trial.py:76-81`, `:372-388`) y lo único que reconstruye el "por qué este usuario tiene X días". Tan es fuente de verdad que es la única tabla del sistema que se **anonimiza** en vez de borrarse al eliminar la cuenta (`backend/main.py:3836`, `:3856-3875`) |
| `trial_consumed` | Sin `user_id` a propósito, para que borrar la cuenta no devuelva el trial (`backend/main.py:2299-2302`). Truncarla regala un trial a cada email que ya lo usó |
| `bond_cashflow_skips` | Decisiones **del usuario** ("este cupón no lo cobré"). No se derivan de nada; se pierden y el inbox de pendientes vuelve a llenarse de cobranzas fantasma |
| `import_mappings` | Plantillas que el usuario armó a mano |
| `billing_events` | Log de auditoría de webhooks, con el `raw_payload` como único registro de lo que el procesador dijo. Es la base para el replay manual de un pago legítimo que llegó con la auth mal configurada (`backend/main.py:26886-26889`) |
| `plan_events` | Telemetría de conversión; no se re-deriva de nada |
| `ai_usage_daily` | **Es el medidor, no un cache.** Truncarla resetea la cuota semanal de todos. Idem `ai_tool_usage` para la detección de abuso |
| `ai_tool_usage` | ídem |
| `trial_email_log` | Idempotencia de los mails de trial. Truncarla re-manda avisos ya enviados |
| `login_history` | Registro de seguridad. Truncarla no rompe el login, pero **la primera vez que cada usuario vuelva a entrar no dispara alerta** (la lógica es "si `total_prev > 0`", `backend/main.py:3000-3009`): se pierde la línea de base de dispositivos conocidos |
| `push_subscriptions` | Las claves `p256dh`/`auth` sólo las tiene el browser en el momento de suscribirse. Truncarla deja a todos sin push hasta que cada uno re-habilite manualmente |
| `email_verification_codes` | Sólo importan las filas vivas (una por usuario, TTL 15 min); pero truncarla **en medio** deja en el aire a quien esté verificando. En rigor es (a) con una ventana chica de (c) |
| `password_reset_tokens` | Mismo caso: sólo importan los tokens vivos (TTL 30 min) |

**El patrón que sale de la clasificación:** las tablas verdaderamente caras (`import_raw_rows`,
`credit_ledger`, `login_history`, `billing_events`) son todas **append-only sin poda**, y las
tablas verdaderamente descartables (`yfinance_cache`, `news`, `ai_analyses_cache`) son
**exactamente las tres a las que el código les prometió un cron de limpieza que nunca se
escribió**. Es decir: el crecimiento está donde no se puede podar, y lo que sí se puede podar no
se poda.
