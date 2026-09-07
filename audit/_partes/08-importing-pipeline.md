## Importación — pipeline, persistencia y reconstrucción

Alcance: `backend/importing/*` + `backend/sim_import.py` + los endpoints de `backend/main.py` que los orquestan. Todo lo que sigue está leído sobre `origin/main` (producción).

Convención: `[V]` = verificado leyendo el código (con cita); `[I]` = inferencia (digo de qué me agarré).

---

### 0. Mapa del subsistema

| Archivo | Líneas | Qué es |
|---|---:|---|
| `backend/importing/schema.py` | 295 | El contrato interno: `NormalizedTx`, `RowError`, enums de op_type y aliases |
| `backend/importing/pipeline.py` | 1354 | Orquestador: decode → parse → normalize → validate → preview → persistir sesión |
| `backend/importing/normalizer.py` | 601 | `RawRow` → `NormalizedTx` (fechas, números, tipos, triángulo qty×precio=monto) |
| `backend/importing/validator.py` | 193 | Validación semántica por op_type. **No** rechaza ventas sin stock ni overdrafts |
| `backend/importing/persister.py` | 1705 | Aplica las tx a `positions`/`operations`/`monthly_entries` + `revert_batch` |
| `backend/importing/rebuild.py` | 991 | Replay FIFO global post-import: **borra y reescribe** posiciones y ventas |
| `backend/importing/recompute_backfill.py` | 725 | La misma secuencia post-import corrida offline (script/admin) + normalizadores de costo |
| `backend/importing/tenencia.py` | 1999 | 7 parsers de FOTO de tenencia + reconciliación + generación de tx sintéticas |
| `backend/importing/maturity.py` | 421 | Sweeps post-import: cierre de letras vencidas + amortización de bonos |
| `backend/importing/seed.py` | 393 | "Estado inicial": depósitos y compras sintéticas para CSV parciales |
| `backend/importing/cash_sim.py` | 183 | Simulación de caja en memoria (solo warnings de preview) |
| `backend/importing/invariantes.py` | 319 | 6 chequeos de contradicción sobre datos ya escritos. **Solo endpoint admin** |
| `backend/importing/fx_migrate.py` | 651 | Migración FX v1→v2 de una cuenta entera |
| `backend/importing/proyeccion.py` | 262 | Rueda `positions` hacia atrás a la fecha de la foto |
| `backend/importing/excel.py` | 367 | xlsx / PDF / tabla HTML → CSV o filas |
| `backend/importing/mapper.py` | 226 | Mapeo de columnas del wizard "formato libre" |
| `backend/importing/preview.py` | 136 | Arma el payload de preview |
| `backend/importing/fci_map.py` | 101 | Ticker de FCI del broker → `FCI:<slug>` del catálogo |
| `backend/importing/tickers_cd.py` | 163 | Consolida el sufijo dólar/cable (`AL30D` → `AL30`) |
| `backend/importing/sections.py` | 82 | Clasificación de renta fija para presentación |
| `backend/sim_import.py` | 109 | Script CLI de simulación end-to-end en DB temporal |

Parsers de MOVIMIENTOS registrados: 16 en `backend/importing/parsers/registry.py:22-53` (`rendi_generic`, `binance`, `binance_futures_trade_history`, `binance_transaction_history`, `cocos`, `ppi`, `balanz_movimientos`, `balanz_internacional`, `balanz`, `balanz_resultados`, `iol`, `schwab`, `bullmarket`, `ieb`, `inviu`). `[V]`

---

### 1. Pipeline end-to-end: de un archivo subido a filas en `positions`/`operations`

#### 1.A — Fase PREVIEW (`POST /api/imports/preview`)

| # | Paso | Dónde |
|---:|---|---|
| 1 | Resolver input (`files[]` preferido, `file` legacy). Máx **20 archivos** | `backend/main.py:30456-30466` |
| 2 | Lectura **chunked** de 64 KB con corte al pasar `MAX_TOTAL_BYTES` (5 MB) → evita OOM | `backend/main.py:30471-30494` |
| 3 | `sanitize_filename` por archivo (whitelist `[\w.\- ]`, trunca a 80) | `backend/importing/pipeline.py:130-150` |
| 4 | `combine_csv_files`: exige **mismo header** en todos, concatena, y hace **dedup línea-a-línea entre archivos** (no dentro del mismo) | `backend/importing/pipeline.py:297-395` |
| 5 | `run_preview` — cap `MAX_FILE_BYTES` (5 MB) sobre el combinado | `backend/importing/pipeline.py:440`, `:454-455` |
| 6 | `file_hash = sha256(bytes)` y `find_duplicate_batch` (batches `confirmed` con el mismo hash) → solo informativo | `backend/importing/pipeline.py:457-458`, `:217-225` |
| 7 | `to_csv_text`: xlsx→CSV, PDF, tabla HTML, o decode `utf-8-sig / cp1252 / latin-1` | `backend/importing/excel.py:348`, `pipeline.py:262-284` |
| 8 | Elegir parser: `mapping` explícito → `rendi_generic` sobre el CSV traducido; si no, `get_parser(format)` | `backend/importing/pipeline.py:470-487` |
| 9 | `parser.parse(content)` | `backend/importing/pipeline.py:490` |
| 10 | **Fallback de autodetect**: si el parser elegido dio 0 filas y sí errores, se reintenta con `autodetect(headers)` | `backend/importing/pipeline.py:497-512` |
| 11 | Cap `MAX_ROWS = 10_000` | `backend/importing/pipeline.py:520-521` |
| 12 | `normalize_rows(raw_rows)` → `(List[NormalizedTx], errors)` | `backend/importing/pipeline.py:524` |
| 13 | Canonicalización de nombre de broker (case-insensitive + trim contra `brokers` del user) | `backend/importing/pipeline.py:526-539` |
| 14 | **Auto-heal de moneda**: si el broker existe con moneda ≠ `FORMAT_BASE_CURRENCY[format]` y está **vacío** (`positions` sin filas), se le corrige la moneda | `backend/importing/pipeline.py:548-570` |
| 15 | **Auto-creación de brokers** ausentes, con inferencia de moneda: cripto conocido→USDT, luego `fmt_base`, luego mayoría USDT/ARS, si no USD | `backend/importing/pipeline.py:572-641` |
| 16 | **Auto-ruteo por moneda**: si un broker ARS trae filas USD/USDT o FX → `route_by_currency = True` | `backend/importing/pipeline.py:643-661` |
| 17 | `validate(...)` con brokers + posiciones existentes | `backend/importing/pipeline.py:663-670` |
| 18 | `cleanup_stale_previews` (borra previews > 1 h) — **a propósito acá**, porque es el primer `DELETE` y en SQLite la primera escritura toma el lock | `backend/importing/pipeline.py:190-197`, `:697-699` |
| 19 | `INSERT INTO import_batches` con `status='preview'` + `route_by_currency` | `backend/importing/pipeline.py:700-707` |
| 20 | `INSERT INTO import_raw_rows` (una por fila cruda, con `errors_json`) | `backend/importing/pipeline.py:710-720` |
| 21 | Por cada tx válida: `fingerprint`, `gross_amount_usd` estampado (`stamp_tx_gross_usd`), `INSERT INTO import_normalized_tx` | `backend/importing/pipeline.py:733-761` |
| 22 | `build_preview(...)` + extras: `duplicate_row_indices`, `new_brokers_created`, `brokers_already_imported`, `cash_warnings`, `projected_cash`, `projected_cash_standalone`, `seed_suggestions`, `routing_breakdown` | `backend/importing/pipeline.py:763-991` |

Notas del preview:

- El TC con el que se estampa `gross_amount_usd` sale de `_read_user_tc_blue` (blue **live** de `main._display_blue`, con fallback al `config.tc_blue`, default `1415.0`) — `backend/importing/pipeline.py:40-68`. `[V]`
- Solo si la cuenta está en **FX v2** se usa `fx_for_date(conn, tx.date)`; en v1 se estampa todo con el blue de hoy — `backend/importing/pipeline.py:735-737` con `_hist = fx_version(conn, uid) == FX_V2` (`:733`). `[V]`
- Las conversiones (`FX_*`) tienen camino propio: el USD es `abs(tx.quantity)` (la pata real de la operación), no una conversión por TC — `backend/importing/pipeline.py:103-127`. `[V]`

#### 1.B — Fase CONFIRM (`POST /api/imports/confirm`, `backend/main.py:30738`)

Dentro de **una** transacción (`with conn:`) — lo atómico:

| # | Paso | Dónde |
|---:|---|---|
| 1 | `load_session_with_seed_revalidate(...)` → rehidrata `NormalizedTx` desde `import_normalized_tx` (o re-normaliza todo si vino `seed_state`) | `backend/main.py:30749-30751`; `pipeline.py:1105-1200` |
| 2 | `skip_row_indices` del usuario | `backend/main.py:30755` |
| 3 | **Opt-in**: las filas con `MARCA_APROBACION` en `notes` se saltean salvo que su ticker venga en `aprobar_tickers` | `backend/main.py:30756-30764`; `tenencia.py:397-402` |
| 4 | **Dedup cross-batch** por fingerprint (`already_imported_row_indices`) salvo `include_duplicates` | `backend/main.py:30774-30780`; `pipeline.py:227-253` |
| 5 | `DELETE FROM import_normalized_tx` de las filas salteadas — crítico: si no, el rebuild las resucitaría | `backend/main.py:30783-30799` |
| 6 | `persist_batch(...)` | `backend/main.py:30801-30810` |

Fuera de la transacción (post-proceso, cada uno con su propio `with conn:` y su `try/except` que solo hace `traceback.print_exc()`):

| # | Paso | Dónde |
|---:|---|---|
| 7 | `rebuild_fifo_after_import(conn, uid, session_id, tc_blue=_read_tc_blue(...))` | `backend/main.py:30842-30845` |
| 8 | `sweep_matured_letras` | `backend/main.py:30858` |
| 9 | `sweep_bond_amortizations` | `backend/main.py:30872` |
| 10 | `_fetch_data912_bonds()` (red, **fuera** del lock) + `tag_bonds_from_data912` | `backend/main.py:30892-30893` |
| 11 | `normalize_bond_units` (per-100 → per-1) | `backend/main.py:30905` |
| 12 | `normalize_usd_commissions` (comisión ARS en lote USD → ÷ tc_blue) | `backend/main.py:30915` |
| 13 | `_recalc_pnl_realized_from_ops` | `backend/main.py:30930` |
| 14 | `_backfill_snapshots_from_monthly` (segunda vez) | `backend/main.py:30943` |
| 15 | Re-estampar `positions.price_override` de los FCI desde `import_batches.fund_price_overrides` | `backend/main.py:30956-30966` |
| 16 | `_auto_migrar_fx_post_import(uid)` — conexión propia, ya commiteado | `backend/main.py:30975` |
| 17 | `_reconstruir_mtm_post_import(uid)` — **thread daemon** en background (sale a yfinance) | `backend/main.py:30984`, `:30713-30731` |

El comentario en `backend/main.py:30813-30832` explica por qué el post-proceso salió de la transacción: el lock de escritura de SQLite es **por base**, no por usuario, y quedaba tomado durante todo el rebuild + sweeps + un fetch de red. `[V]`

Camino paralelo — **Wallbit** usa el mismo motor pero con menos pasos: `_wallbit_apply_batch` corre `persist_batch → rebuild → recalc → backfill_snapshots` y **omite** los sweeps de bonos/letras y los normalizadores de costo (`backend/main.py:31078-31097`). `[V]`

---

### 2. El esquema normalizado (`schema.py`) — el contrato interno

`NormalizedTx` (`backend/importing/schema.py:201-266`): `[V]`

| Campo | Tipo | Notas del propio código |
|---|---|---|
| `row_index` | int | link al `RawRow`; los sintéticos usan negativos (`-10000` seed, `-20000` tenencia, `-21000` true-up de caja) |
| `date` | str `YYYY-MM-DD` | **sin hora** — `schema.py:205`. Es la causa de que el desempate FIFO del mismo día lo decida el orden de la fila |
| `broker` | str | mapea a `portfolio_id`; se muta en el ruteo por moneda |
| `operation_type` | str | uno de `OPERATION_TYPES` (`schema.py:30-33`) |
| `asset_symbol` | str? | canónico (FCI reescrito a `FCI:<slug>`, sufijo D/C consolidado) |
| `asset_symbol_raw` | str? | **crudo** del parser; se usa para el fingerprint de dedup (`schema.py:209-214`) |
| `asset_name` | str? | nombre largo del instrumento (de ahí sale el vencimiento de bonos) |
| `asset_type` | str? | `STOCK/CEDEAR/ETF/CRYPTO/FIAT/BOND/FUND/OTHER` |
| `quantity`, `unit_price`, `gross_amount` | float? | en FX cambian de significado: `gross_amount`=ARS, `quantity`=USD, `unit_price`=TC |
| `fees` | float | **sin moneda** (float pelado) — `normalizer.py:391-407` documenta que ése es el origen del bug de "comisión en pesos sobre lote en dólares" |
| `taxes` | float | |
| `currency`, `settlement_currency` | str? | `{USD, USDT, ARS}` |
| `cash_broker` | str? | de qué cuenta sale la PLATA cuando no es la del activo (CEDEAR pagado en dólares) |
| `notes` | str? | canal de marcas: `MARCA_APROBACION`, `TENENCIA_APERTURA_NOTE_PREFIX`, `"Estado inicial…"`, `"Ajuste de cash a Estado de Cuenta…"` |
| `gross_amount_usd` | float? | estampado al preview/confirm; el persister **debe** usarlo (`schema.py:231-237`) |
| `cost_basis_pending` | bool | posición transferida sin precio → va al flujo de seed |
| `corporate_close` | bool | venta a proceeds 0 por acción societaria; el validador acepta precio 0 |
| `transfer_out` | bool | retiro del activo fuera de la cuenta: cierre **a costo** (P&L 0), sin caja |
| `tc_compra` | float? | ARS por USD de la compra; alimenta la vista "costo al dólar de la compra" |

**Persistencia parcial del contrato.** `import_normalized_tx` NO tiene columnas para `asset_symbol_raw`, `cost_basis_pending`, `corporate_close` ni `cash_broker` (`backend/main.py:2479-2507` + migraciones `:2564`, `:2576`, `:2589`, `:2601`). O sea: `transfer_out` y `tc_compra` sobreviven al round-trip (`pipeline.py:1093-1104`), y los otros tres **no**. `[V]`

Consecuencia concreta: `_row_fingerprint` usa `asset_symbol_raw or asset_symbol` (`pipeline.py:157-162`), y al rehidratar desde la DB `asset_symbol_raw` es siempre `None`, así que el confirm recalcula el fingerprint contra el símbolo canónico. Por eso existe `_row_fingerprint_legacy` y el dedup compara contra **ambos** (`pipeline.py:164-170`, `:250-253`). `[V]`

Otros tipos del módulo: `RawRow` (`:194-198`), `RowError` (`:269-277`), `ParseResult` (`:280-284`), `PipelineResult` (`:287-295`, **no se usa** — ver §11).

`OP_TYPE_ALIASES` tiene ~200 entradas castellano/inglés (`schema.py:36-151`) y `UNSUPPORTED_OP_HINTS` (`:158-177`) rechaza con mensaje accionable: splits, spin-off, merger, **caución**, plazo fijo, convert cripto-a-cripto, forks.

---

### 3. Persistencia (`persister.py`)

#### 3.1 `persist_batch` (`backend/importing/persister.py:136`)

Orden real de lo que hace:

1. Si vino `seed_state`: `build_seed_txs` y se **insertan** en `import_raw_rows` + `import_normalized_tx` (`:157-223`). Estas filas se insertan **sin `fingerprint`** (`:213-220`) — esa omisión es lo que después usa `fx_migrate` para reconocerlas (`fx_migrate.py:310-317`). `[V]`
2. El `gross_amount_usd` del seed se estampa con el blue de **hoy** y nunca con `fx_for_date`, con un comentario largo explicando por qué (`:189-208`): el monto lo tipeó el usuario hoy pero la fecha es `earliest − 1 día`. `[V]`
3. Orden determinístico: `(date, BUY-antes-que-todo, row_index)` (`:231-237`).
4. Ruteo por moneda si `import_batches.route_by_currency` (`:240-320`):
   - crea el sibling `<Padre> · USD` (`_ensure_usd_sibling`, `backend/main.py:10776`) y le garantiza una posición de caja `USDT` con 0 (`:264-275`);
   - `FX_ARS_TO_USD` queda en el padre, `FX_USD_TO_ARS` va al sibling (`:283-289`);
   - filas USD/USDT: si `cash_broker_for` dice que el activo se consolida en el padre (CEDEAR), **solo la caja** va al sibling vía `tx.cash_broker` (`:291-307`); si no, la fila entera se mueve al sibling;
   - el cambio de broker se sincroniza a `import_normalized_tx` para que el revert lea el broker real (`:308-318`).
5. Loop por fila, **cada una en su propio `SAVEPOINT`** (`:353-431`): una fila que revienta hace `ROLLBACK TO` y va a `skipped[]`; el resto del lote entra. Solo un fallo al crear el savepoint es fatal.
6. `_repair_monthly_chain` una vez por broker tocado + `global` (`:435-437`).
7. `_backfill_snapshots_from_monthly` (`:443`).
8. `cash_health` por broker tocado (`:447-462`).
9. `UPDATE import_batches SET status='confirmed'` (`:465-471`).

#### 3.2 Qué escribe cada op_type

| op_type | Escribe | Función |
|---|---|---|
| `BUY` | 1 fila en `positions` (lote nuevo, nunca merge) + débito de caja en `cash_broker or broker` | `:563-599` |
| `SELL` | N filas en `operations` (`op_type='Venta'`), consume/borra lotes, crédito de caja, `_update_monthly_pnl_realized` broker + global | `:601-861` |
| `DEPOSIT` / `WITHDRAW` / `FEE` / `IMPUESTO` | `positions.invested` de la caja (**overdraft permitido**) + `_update_monthly_flow` broker + global | `:899-901`, `:1000-1071` |
| `DIVIDEND` / `INTEREST` | caja + 1 fila `operations` (`Dividendo`/`Interés`/`Amortización`) + `pnl_realized` (salvo amortización) | `:938-997` |
| `FX_ARS_TO_USD` / `FX_USD_TO_ARS` | caja en las dos patas + 1 `operations` `CONVERSION IMPORT X→Y` + flujos mensuales / `pnl_realized` | `:1108-1199` |
| `FUTURES_PNL` | 1 `operations` `Futuros` + caja + `pnl_realized` | `:863-896` |
| `TRANSFER` | nunca llega (lo filtra el validator) → `PersistError` | `:391-393` |

Detalles importantes:

- **Cada BUY crea un lote nuevo**. No hay merge por (broker, activo): `INSERT INTO positions` sin `ON CONFLICT` (`:588-597`). El FIFO vive en las filas.
- **`reconciled_unit_price`** (`:492-546`): guard de escala acotado a **dos** convenciones (renta fija per-100 y VCP de FCI por 1.000), con tolerancia ±2 %. Fuera de eso no toca nada, a propósito.
- El **cost basis del lote** sale de `gross_amount`, no de `precio × cantidad` (`:567`). Los **proceeds** de una venta salen de `unit_price × qty` (`:704`, `:788`). Los dos números nunca se reconcilian entre sí — de ahí que un error de escala en el precio caiga entero sobre el P&L.
- **FIFO por moneda + par de brokers**: los lotes se buscan en `broker_pair(...)` (padre + `· USD`), y `_by_ccy` prioriza los de la moneda de la venta con fallback a todos (`:633-668`).
- **Ventas sin stock** → se fabrica un lote semilla al precio de venta (P&L 0 sobre esa porción) y se linkea al batch para que el revert lo borre (`:670-706`).
- **TC de venta**: `fx_for_date(tx.date)` solo si la cuenta es FX v2; en v1 es el blue vivo (`:747-753`).
- **`fx_to_usd` se estampa solo en ventas ARS**; en USD queda `NULL` a propósito (`:820-828`).

#### 3.3 `_link` y la trazabilidad para el revert

`_link` (`:1202-1227`) hace dos cosas: `COALESCE` sobre `import_normalized_tx.created_position_id/created_operation_id` (solo el **primero**) e `INSERT` en `import_op_links` (todos). `import_op_links` es la fuente real de "qué creó este batch". `[V]`

#### 3.4 Dedup, idempotencia y re-import

- **Dedup por fingerprint**: `sha256(date|broker_lower|op_type|symbol_upper|qty:.8f|price:.8f|gross:.4f)[:16]` — `pipeline.py:172-184`. No incluye fees ni notes. `[V]`
- Es **cross-batch, no intra-batch**: `b.id != ?` (`pipeline.py:243`). Dos operaciones idénticas en el mismo archivo se respetan; lo que ya entró en otro batch confirmado se saltea. `[V]`
- **Re-importar el mismo archivo** (mismo `file_hash`): NO se bloquea. Solo se informa `duplicate_of_batch_id` en el preview (`pipeline.py:217-225`, `:458`) y `brokers_already_imported` (`:780-787`). Las filas se saltean una por una por fingerprint en el confirm. `[V]`
- **Re-importar un export DISTINTO del mismo período** (p.ej. "Órdenes" y después "Resultados" de Balanz): el fingerprint no matchea (valores distintos) → **duplica**. El propio código lo dice en `pipeline.py:775-779`. `[V]`
- Los seed sintéticos (`Estado inicial`) van **sin fingerprint**, así que **no** participan del dedup: dos confirms con el mismo `seed_state` crean dos depósitos sintéticos. `[V]` (`persister.py:213-220` vs. `pipeline.py:236-241`)
- `store_preview_txs` (el camino de la foto de tenencia) dice en su docstring "Idempotente por hash de fingerprints" (`pipeline.py:992-998`) pero **no hay ninguna comprobación de duplicado en el cuerpo**: calcula un `file_hash` a partir de los fingerprints y hace el `INSERT` igual (`:1000-1038`). El docstring miente. `[V]`

#### 3.5 `revert_batch` (`:1323-1705`)

- Solo revierte batches `confirmed`.
- Modo **safe** (default): si el batch tiene `SELL`/`FX_*`/`FUTURES_PNL`, aborta con mensaje (`:1352-1370`). Además chequea que ninguna posición creada haya sido vendida después (`:1388-1404`).
- Modo **nuclear** (`?nuclear=1`, lo usa "Editar y rehacer"): best-effort. En `SELL` **no recrea los lotes consumidos** (`:1527-1536`) — el comentario lo declara aceptable porque el flujo asume re-import.
- Orden crítico: `status='reverted'` se escribe **antes** del `_repair_monthly_chain` + `recalc`, porque si no el recalc volvería a sumar los deposits del batch (`:1657-1668`).
- Purga snapshots desde la fecha más vieja del batch y re-backfillea (`:1687-1703`).

---

### 4. ⚠️ Rebuild / recompute: qué pisa, y el orden completo de escritura

#### 4.1 Qué es el rebuild

`rebuild_fifo_after_import` (`backend/importing/rebuild.py:804`) existe porque el persister es **incremental**: procesa un batch contra el estado actual. Si el historial se carga fuera de orden cronológico, una venta cuya compra todavía no se cargó usa un lote semilla al precio de venta (P&L 0) y la compra posterior queda como lote abierto fantasma (`rebuild.py:1-27`). `[V]`

Qué hace, por cada `(par de brokers, activo)` tocado por el batch:

1. `_affected_assets` → `(broker, asset_symbol)` con BUY/SELL en **este** batch (`:519-531`).
2. `broker_pair` → agrupa padre + `· USD` como **un** grupo, con dedup de grupos ya vistos (`:824-832`).
3. `_full_events` → **TODOS** los BUY/SELL confirmados del activo en el par, de **todos** los batches, ordenados `(date, BUY-primero, id)` y filtrando `excluded_at IS NULL` (`:533-561`).
4. Si no hay ninguna venta → se saltea (`skipped_no_sell`, `:836-838`).
5. `_is_safe_to_rebuild` → si hay **alguna** posición o venta actual no vinculada en `import_op_links`, se saltea entero (`:565-598`, `:840-845`). Esta es la única frontera de seguridad contra data manual.
6. `_cancel_conduit_pairs` → cancela pares de conducto dólar-MEP de bonos (compra+venta del mismo bono, monedas distintas, mismo nominal, ≤ 7 días) antes del FIFO (`:112-218`, `:869-873`).
7. `_replay_asset` → replay puro en memoria, **sin efectos de caja** (`:232-517`).
8. Dentro de un `SAVEPOINT` por activo (`:882-921`):
   - `_capturar_precio_manual` (guarda `positions.price_override`),
   - `_clear_old_state` → **`DELETE FROM positions` + `DELETE FROM operations WHERE op_type='Venta'`** para ese par/activo, y borra los `import_op_links` de esas filas (`:640-676`),
   - `_write_rebuilt` → re-inserta lotes y ventas y re-linkea (`:732-770`),
   - `_restaurar_precio_manual`,
   - `_ensure_monthly_rows` (`INSERT OR IGNORE` de la fila mensual, para que el recalc tenga dónde sumar) (`:773-801`),
   - `_write_buy_tombstones` para las compras consumidas del todo.

#### 4.2 Lo que el rebuild PISA (lista explícita)

`_write_rebuilt` inserta la posición con estos valores literales (`backend/importing/rebuild.py:743-753`): `[V]`

```
INSERT INTO positions (... buy_price, quantity, invested, tc_compra, price_override, notes, entry_date, commissions, currency, asset_type)
VALUES (..., _lot_tc_compra(conn, lot), None, None, lot["entry_date"], ...)
                                          ^^^^  ^^^^
                                   price_override  notes
```

Se **pierde** en cada rebuild de un activo con al menos una venta:

| Campo de `positions` | Qué pasa | Mitigación |
|---|---|---|
| `price_override` | se escribe `None` | `_capturar_precio_manual`/`_restaurar_precio_manual` (`rebuild.py:601-638`) — y además `import_confirm` re-estampa los FCI **al final** (`backend/main.py:30951-30966`) |
| `notes` | se escribe `None` **sin restaurar** | ninguna. `maturity.sweep_bond_amortizations` esquiva el problema leyendo el `notes` desde `import_normalized_tx` vía `created_position_id` (`maturity.py:319-329`) |
| `tc_compra` | se re-deriva (`_lot_tc_compra`, `:701-728`): evento → `fx_for_date(entry_date)` si el lote es ARS → `None` | parcial |
| `id` de la posición | cambia siempre (fila nueva) | tombstones para que el revert siga bloqueando (`:678-698`) |
| `asset_type` | si el evento no lo trae o dice `OTHER`, se re-infiere con `guess_asset_type` (`:738-741`) | |
| filas de `operations` con `op_type='Venta'` | se borran y re-crean; los IDs cambian | re-link vía `_link` |

Lo que el rebuild **NO** toca, por diseño: caja (`positions is_cash=1`), depósitos/retiros, dividendos/intereses, FX, `monthly_entries` (`rebuild.py:29-38`). `[V]`

#### 4.3 Orden de escritura completo de un confirm (quién puede pisar a quién)

| Orden | Escritor | Escribe | Puede pisar |
|---:|---|---|---|
| 1 | `persist_batch` (`persister.py:136`) | `positions`, `operations`, caja, `monthly_entries` (`deposits`/`withdrawals`/`pnl_realized`), `import_op_links` | — |
| 2 | `_repair_monthly_chain` × broker + global (`persister.py:435-437`) | `monthly_entries.capital_inicio/capital_final`, `pnl_unrealized=0` en meses cerrados | 1 |
| 3 | `_backfill_snapshots_from_monthly` (`persister.py:443`) | `snapshots` (INSERT-only, `ON CONFLICT DO NOTHING`) + `DELETE snapshots WHERE date > hoy` | — |
| 4 | **`rebuild_fifo_after_import`** (`main.py:30843`) | **borra y reescribe** `positions` y `operations` `Venta` de cada par/activo tocado | **1** |
| 5 | `sweep_matured_letras` (`main.py:30858`) | `DELETE FROM positions` de letras vencidas (solo import-linked) | 1, 4 |
| 6 | `sweep_bond_amortizations` (`main.py:30872`) | `UPDATE/DELETE positions` (qty, invested, commissions × factor residual) | 1, 4 |
| 7 | `tag_bonds_from_data912` (`main.py:30893`) | `positions.asset_type='BOND'` | 1, 4 |
| 8 | `normalize_bond_units` (`main.py:30905`) | `positions.invested`, `positions.buy_price` (÷100) | 1, 4, 6 |
| 9 | `normalize_usd_commissions` (`main.py:30915`) | `positions.commissions` (÷ tc_blue) | 1, 4, 6 |
| 10 | **`_recalc_pnl_realized_from_ops`** (`main.py:30930`) | **sobrescribe** `monthly_entries.pnl_realized`, `deposits`, `withdrawals`, `pnl_unrealized=0`; borra filas todo-en-cero; `DELETE snapshots` si la cuenta queda vacía | **1, 2** |
| 11 | `_backfill_snapshots_from_monthly` (`main.py:30943`) | `snapshots` | — |
| 12 | Re-estampa FCI (`main.py:30956-30966`) | `positions.price_override` | 4 |
| 13 | `_auto_migrar_fx_post_import` (`main.py:30975`) | re-estampa `import_normalized_tx.gross_amount_usd`, corre **otro** rebuild de TODOS los batches, `recalc`, `backfill_snapshots`, `recompute_netdep`, `fx_version=v2` | 1–12 |
| 14 | `_reconstruir_mtm_post_import` (`main.py:30984`, **thread**) | `snapshots` con `source='mtm_backfill'` | asincrónico |

`recompute_backfill.recompute_user` (`recompute_backfill.py:285-324`) reproduce los pasos 4→9 + recalc + re-aplicar overrides de FCI, para todos los batches confirmados de una cuenta, sin re-importar. `[V]`

#### 4.4 🔴 Hallazgo: el recalc pisa los flujos que escribe `_persist_fx`

`_persist_fx` en `ars_to_usd` corrige el capital aportado escribiendo cuatro `_update_monthly_flow` (retiro de la pata ARS a valor blue, depósito de la pata USD a valor face) — `backend/importing/persister.py:1136-1143`, con un comentario que lo llama "FIX bug #1". `[V]`

`_update_monthly_flow` con `is_manual=False` (el default, y lo que usa el import) escribe en las columnas `deposits`/`withdrawals`, **no** en `manual_deposits`/`manual_withdrawals` — `backend/main.py:9918-9963`. `[V]`

`_recalc_pnl_realized_from_ops` reconstruye `deposits`/`withdrawals` de forma **autoritativa** como `imports_confirmados + manual_*` (`backend/main.py:9583-9593`), y `_import_flows_for_period` solo suma filas con `n.operation_type IN ('DEPOSIT','WITHDRAW')` (`backend/main.py:612`). Las filas de conversión están en `import_normalized_tx` con `operation_type` `FX_ARS_TO_USD`/`FX_USD_TO_ARS`, así que **no entran en esa suma**. `[V]`

Como el recalc corre en el paso 10, **después** del persist (paso 1), el efecto neto de esas cuatro escrituras del FX sobre `monthly_entries` es **cero** en cualquier import confirmado por el endpoint. Es exactamente el patrón "el test que no atraviesa el recalc": un test que llama a `persist_batch` directo ve el fix aplicado; producción no. `[V]`

Nota: el efecto sobre `positions` (la caja de las dos patas, `_adjust_cash_permissive`, `:1131-1132`) sí sobrevive — lo que se pierde es únicamente la corrección del capital aportado.

#### 4.5 Otros hallazgos del orden de escritura

- **`persist_batch` y el resto del pipeline usan dos TC distintos.** `persist_batch` lee `tc_blue` directo de `config` con default 1415 (`persister.py:341-351`), mientras que el rebuild, el revert, `fx_migrate` y `recompute_backfill` usan `_read_tc_blue`, que prefiere el blue **live** (`persister.py:1299-1321`, `main.py:30842`). En una cuenta con `config.tc_blue` viejo los dos números difieren. Ese `tc_blue` de `persist_batch` es el que alimenta el fallback de `_apply_cash_flow` (`:1063-1066`), el `_persist_dividend_or_interest` (`:979`) y el cost basis cross-currency del SELL (`:768-782`). `[V]`
- **Los dividendos/intereses en pesos se dolarizan con el blue de hoy, incluso en cuentas FX v2.** `amount_usd = amount / tc_blue` en `persister.py:979`, sin `fx_for_date` y sin `fx_version`. Las ventas (`:747-753`) y los flujos (`pipeline.py:735-737`) sí respetan la fecha. Un cupón de 2021 entra a `pnl_realized` con el dólar de hoy. `[V]`
- **Esas filas no llevan `currency` ni `fx_to_usd`.** El `INSERT` de `persister.py:981-988` omite las dos columnas, así que `realized_pnl.realized_usd_sql` (`backend/realized_pnl.py:96-107`) las manda al `ELSE` y suma `pnl_usd` crudo. Coincide con lo que escribió el persister, pero deja las filas sin la marca que permitiría repararlas después. `[V]`
- **`_persist_dividend_or_interest` decide la moneda por el BROKER, no por la fila** (`:958-960`, `:979`). Con `route_by_currency` un dividendo USD termina en el sibling USD y sale bien; sin ruteo (broker ARS y `route_by_currency=0`), un dividendo en dólares se divide por el blue. `[I]` — se sigue de que el ruteo solo corre si `import_batches.route_by_currency` (`persister.py:248`).
- **`_recalc_pnl_realized_from_ops` no aplica `closed_filter_sql`**: suma `realized_usd_sql` sobre TODAS las `operations` del mes (`backend/main.py:9524-9535`), incluidas `Dividendo`, `Interés` y `Futuros`. Es coherente con lo que escribió el persister, pero es una definición distinta de `pnl_realized` que la de `realized_pnl.closed_filter_sql`.
- **El rebuild vuelve a correr entero dentro de `migrate_user_fx`**, para **todos** los batches confirmados (`fx_migrate.py:372-380`), y eso se dispara **en cada import** de una cuenta que todavía esté en v1 (`main.py:30975` → `main.py:30598-30614`). O sea: el primer import de una cuenta v1 reescribe todo el histórico FIFO de esa cuenta.

---

### 5. `tenencia.py` — el modo "foto"

#### 5.1 Qué brokers lo soportan

Siete parsers de foto, todos en `backend/importing/tenencia.py`: `[V]`

| Broker | Formato | Detector | Parser |
|---|---|---|---|
| Bull Market | PDF "Tenencia valorizada" | `looks_like_tenencia` `:700` | `parse_bullmarket_tenencia` `:706` |
| IOL | PDF "Resumen de Cuenta" | `looks_like_iol_tenencia` `:844` | `parse_iol_tenencia` `:869` |
| PPI | xlsx "Estado de Cuenta" | `looks_like_ppi_tenencia` `:1026` | `parse_ppi_tenencia` `:1062` |
| Cocos | CSV `portfolio_report` | `looks_like_cocos_tenencia` `:1245` | `parse_cocos_tenencia` `:1260` |
| Balanz | PDF "Resumen de Cuenta" | `looks_like_balanz_tenencia` `:1394` | `parse_balanz_tenencia` `:1410` |
| IEB | xlsx multi-hoja "Portafolio" | `looks_like_ieb_portfolio` `:1572` | `parse_ieb_portfolio` `:1619` |
| inviu | xlsx "Tenencias" | `looks_like_inviu_tenencia` `:1773` | `parse_inviu_tenencia` `:1806` |

Ruteo: `POST /api/imports/classify-tenencia` (`backend/main.py:29496`) separa la foto de los Movimientos en el upload combinado; `POST /api/imports/tenencia/preview` (`backend/main.py:29661`) hace todo lo demás. Los formatos xlsx/CSV llegan por el campo `format`; los tres PDF se auto-detectan por contenido (`backend/main.py:29758-29786`).

#### 5.2 El flujo de la foto, paso a paso

1. Parseo → `TenenciaSnapshot(holdings, date, total_ars, cash_ars, cash_usd, fx_mep, warnings)` (`tenencia.py:91-99`).
2. `normalizar_tickers(snap)` (`tenencia.py:197-262`) — canonicaliza los tickers de la foto con el mismo `consolidate_cd` que los movimientos y **fusiona** holdings por `(ticker, moneda)`. Sin esto la foto dice `AL30D` y Rendi dice `AL30` → dos problemas falsos del mismo activo (`backend/main.py:29790-29799`).
3. **Fecha** (`backend/main.py:29804-29826`), cascada de tres escalones con el origen declarado: `archivo` → `nombre_archivo` (`fecha_de_nombre_archivo`, `tenencia.py:165`) → `fallback_hoy` (reloj del servidor). El comentario dice que **93 de 152** fotos confirmadas en prod caen al fallback y que `parse_cocos_tenencia` no setea fecha nunca.
4. **Contexto asesor**: si `request.state.rendi_auth_uid != uid` y la fecha es `fallback_hoy` → `motivo_corte='fecha_desconocida'` y **todo** va a `no_reconciliable` (`backend/main.py:29882-29886` + `tenencia.py:341-360`).
5. `_qty_a_fecha` (`backend/main.py:29848-29870`): rueda `positions` hacia atrás a la fecha de la foto vía `proyeccion.proyectar`, **salvo** con fecha inventada (ahí usa el estado de hoy).
6. Re-tag cross-currency de bonos amortizantes: si el bono vive solo en la partición hermana, se le cambia la moneda y hereda el costo unitario de los lotes existentes (`backend/main.py:29904-29991`).
7. Por partición de moneda (`ARS` en el padre, `USD` en el sibling — creado si hace falta): `compute_reconcile` → correcciones cross-partición → `marcar_bonos_amortizantes` → `marcar_ausentes` → `_tenencia_apply_override` (`backend/main.py:30035-30119`).
8. Cash true-up (`build_cash_trueup_txs`) — solo si `_complete` (`backend/main.py:30170-30212`).
9. `store_preview_txs` → batch en `preview`; `fund_price_overrides` y `override_info` se guardan en `import_batches` (`backend/main.py:30366-30378`).
10. Lo aplica el **mismo** `/api/imports/confirm` de siempre.

#### 5.3 Los cuatro baldes de la reconciliación

`compute_reconcile` (`tenencia.py:327-386`), comparando la foto contra `current_qty_by_asset`: `[V]`

| Balde | Condición | Qué genera |
|---|---|---|
| `matched` | `|gap| ≤ tolerancia_qty` | nada |
| `to_seed` | Rendi < foto | COMPRA sintética del hueco a `price_per1` (P&L 0) |
| `over` | Rendi > foto | VENTA sintética de `rendi − foto`, precio 0, `transfer_out=True` |
| `not_in_snapshot` | está en Rendi y no en la foto | VENTA de TODO — **solo si `complete`** |
| `no_reconciliable` | catch-all de "no sé" | nada aplicable; sale a decisión |

`tolerancia_qty` (`tenencia.py:271-325`) es **relativa**: `max(1e-6, 1e-4 · min(|rendi|, |foto|))`. El docstring documenta la medición que la justifica (77 filas sintéticas de redondeo que dejaron de crearse, sobre 52 usuarios, todas en FCI/money market). `[V]`

#### 5.4 ¿Se cierran los activos ausentes de la foto?

**Depende de `complete` y del contexto.** `[V]`

- `not_in_snapshot` se convierte en venta **solo si `complete=True`** (`tenencia.py:658-660`).
- `_complete` se calcula así (`backend/main.py:30011-30018`): para Balanz, `not _sec_vacia` (solo la warning `SECCION_SIN_FILAS` lo bloquea); para el resto, `not snap.warnings` — cualquier warning del parser lo apaga.
- Además `marcar_ausentes` (`tenencia.py:497-538`) mete **todos** los `not_in_snapshot` en `no_reconciliable` con `requiere_aprobacion=True`, y `MARCA_APROBACION` se agrega al `notes` de la venta sintética (`tenencia.py:665-668`). El confirm las saltea salvo que el ticker venga en `aprobar_tickers` (`backend/main.py:30756-30764`). O sea: **hoy el cierre por ausencia nunca se aplica solo** — falla cerrado.
- Lo mismo con los bonos amortizantes (`marcar_bonos_amortizantes`, `:404-491`), con un discriminador: si Rendi no tenía **nada** de ese bono a la fecha, no hay desajuste de escala posible y se auto-aplica.
- `marcar_over` (`:544-593`) solo corre **en contexto asesor** (`gate_over=es_contexto_asesor`, `backend/main.py:30117`). Para el usuario normal, `over` sí se aplica solo — el docstring lo justifica con la medición (19 de 21 `over` reales eran correctos).

Guardas de `_tenencia_apply_override` (`backend/main.py:29553-29652`): `[V]`

1. **safe-to-rebuild**: no toca activos con posiciones/ventas manuales (reusa `rebuild._is_safe_to_rebuild`).
2. **same-broker**: no reduce activos que tienen lotes en el sibling.
3. **cap 50 %**: si el corte se llevaría > 50 % del valor invertido **o** > 50 % de la cantidad de tickers, aborta todo el override y deja solo gap-fill + cash.

#### 5.5 Qué es un "cierre sintético"

Una fila `NormalizedTx` con `operation_type=OP_SELL`, `unit_price=0.0`, `gross_amount=0.0` y `transfer_out=True` (`tenencia.py:661-669`). `[V]`

Efecto: el validator acepta el precio 0 por el flag (`validator.py:115-120`); el persister cierra el lote **a costo** (`invested_usd` del lote, `pnl_usd = 0.0`, `proceeds_native = 0.0`, sin crédito de caja) — `persister.py:775-784`; el rebuild lo espeja (`rebuild.py:452-467`). El efectivo se ajusta aparte con el true-up, para no doble-contar.

La fecha de esas ventas es `max(fecha_foto, MAX(date) de BUY/SELL del par)` (`backend/main.py:29646-29653`): si la foto es más vieja que algún movimiento, la venta se ordenaría antes de una compra real en el replay y consumiría un lote semilla fantasma.

Distinción importante que el código marca: `transfer_out` (P&L 0, el activo sigue siendo tuyo) vs `corporate_close` (bookea el costo como pérdida) — `schema.py:245-257`.

#### 5.6 Cómo convive la foto con el historial de movimientos

- La foto **no reemplaza** el historial: se traduce a `NormalizedTx` sintéticas que entran por el mismo pipeline y quedan en `import_normalized_tx`, así que el rebuild las replaya como cualquier otra fila y **sobreviven** al rebuild (`tenencia.py:670-676`).
- Los lotes de apertura llevan la nota `TENENCIA_APERTURA_NOTE_PREFIX` (`tenencia.py:38`), que es un **contrato** leído por LIKE desde `maturity.py:319-329` (los exime de la amortización) y desde `main._foto_split_watermarks`.
- El true-up de caja emite `DEPOSITO`/`RETIRO` sintéticos con nota `"Ajuste de cash a Estado de Cuenta (<ccy>)"` (`tenencia.py:687-692`), que es lo que después lee `invariantes.check_caja_concilia`.
- Guard de plausibilidad del aporte de apertura: `seed_plausibility_warning` (`tenencia.py:1948`, factor 50× / piso US$ 100.000) — **avisa, no bloquea** (`backend/main.py:30294-30328`). El comentario cita el caso del aporte de US$ 1.700.854.139 del user 329 (foto de IEB sembrada en Cocos con `price_per1` en pesos estampados como dólares).

#### 5.7 🔴 Hallazgo: la rama de gap-fill puro del endpoint es código muerto

`backend/main.py:29891` abre `if is_ppi or is_balanz or is_ieb or is_cocos or is_bullmarket or is_iol or is_inviu:` y `backend/main.py:30125` es su `else`. Esos siete flags cubren **todos** los caminos de parseo del endpoint: los cuatro por `format` (`:29684-29687`) y los tres por auto-detección del PDF, que si no matchea ninguno tira `HTTPException(400)` (`backend/main.py:29783-29786`). Con lo cual siempre entra al `if` y el bloque `30125-30169` —incluida la única llamada a `build_tenencia_seed_txs(broker, rec, seed_date)` **sin** `override`— nunca se ejecuta desde el endpoint. `[V]`

#### 5.8 Asimetría declarada en el propio código

El comentario en `backend/main.py:30046-30073` documenta que, en el bucle por partición, `not_in_snapshot` y `to_seed` se corrigen cross-partición pero **`over` no**, y que por eso un activo partido entre padre y sibling puede producir un `over` inexistente. Dice explícitamente que no se arregla porque no está medido. Lo dejo asentado como está.

---

### 6. `validator.py` e `invariantes.py`

#### 6.1 `validator.py` — VIVO

Se llama desde `pipeline.run_preview` (`pipeline.py:665`) y desde `load_session_with_seed_revalidate` (`pipeline.py:1163`). `[V]`

Qué chequea (`validator.py:37-193`):

| op_type | Regla |
|---|---|
| todos | el broker debe existir en `user_brokers` → `UNKNOWN_BROKER` |
| `BUY` | `asset_symbol` presente; `quantity > 0`. Si falta precio **y** monto → **no es error**: marca `cost_basis_pending` y deriva al seed (`:99-101`) |
| `SELL` | `asset_symbol`; `quantity > 0`; precio **o** monto > 0, salvo `corporate_close` o `transfer_out` (`:115-120`) |
| `DEPOSIT`/`WITHDRAW`/`DIVIDEND`/`INTEREST`/`FEE` | `gross_amount > 0` |
| `FX_*` | `gross_amount`, `quantity` y `unit_price` > 0; chequeo de moneda del broker **solo si `route_by_currency=False`** (`:142-148`) |
| `TRANSFER` | rechazo duro `TRANSFER_NOT_SUPPORTED` |
| `FUTURES_PNL` | `|gross_amount| > 1e-9` (puede ser negativo) |

Lo que **no** valida, a propósito (política "history-as-truth", `:8-15`, `:167-174`):
- ventas con stock insuficiente → las acepta y el persister sintetiza el lote;
- compras sin caja suficiente → overdraft permitido;
- **no hay ninguna cota de magnitud** sobre montos, precios ni cantidades. `[V]`

Tolerancias: ninguna numérica. Los únicos umbrales del camino de normalización están en `normalizer.py`: `_FEE_MAX_FRAC = 0.05` (comisión > 5 % del monto → se pone en **cero** con nota, `:31`, `:390-417`) y `_TOL_ESCALA = 0.02` en `persister.reconciled_unit_price` (`:498`).

#### 6.2 `invariantes.py` — DORMIDO en el camino de import

Seis chequeos (`invariantes.py:271-279`): `[V]`

| Chequeo | Severidad | Qué afirma |
|---|---|---|
| `check_moneda_posicion_vs_broker` `:52` | **error** | una posición marcada `ARS` no puede vivir en un broker `USD/USDT` (mide 505 posiciones de ~20 usuarios antes del fix de Balanz) |
| `check_broker_inexistente` `:86` | error | `positions.broker` sin fila en `brokers` (el link es por NOMBRE, no FK) |
| `check_costo_no_positivo` `:114` | error | `quantity > 0` con `invested <= 0` |
| `check_subbroker_usd_bien_formado` `:142` | error | todo `%· USD` debe tener `parent_broker_id` y moneda USD/USDT |
| `check_cash_moneda` `:172` | aviso | caja en la moneda equivocada respecto del broker |
| `check_caja_concilia` `:201` | aviso | ajustes de true-up (`notes LIKE 'Ajuste de cash a Estado de Cuenta%'`) por encima de ARS 50.000 / USD 50, solo si la cuenta tiene movimientos propios |

**Quién los llama**: únicamente `GET /api/admin/check-invariantes` (`backend/main.py:17771-17797`, `get_admin_user`) y `backend/tests/test_invariantes.py`. Grep completo del repo: no hay ninguna llamada desde `import_confirm`, `persist_batch`, el rebuild ni ningún cron. `[V]`

O sea: **el chequeador de invariantes existe, es de solo lectura y no corre en el camino de ningún import**. El propio docstring del módulo (`:1-20`) dice que nace de que los tres bugs del 03/09/2026 terminaron el import sin un solo error — y sigue sin estar enganchado al import.

`correr()` (`:281-319`) es tolerante: un chequeo que revienta va a `chequeos_rotos` y los demás siguen; los totales cuentan todo aunque la muestra se trunque a 200 por chequeo.

---

### 7. `fx_migrate.py` — qué migra y cuándo se dispara

**Qué hace** `migrate_user_fx` (`backend/importing/fx_migrate.py:235`), sin commitear (decide el caller): `[V]`

1. Aborta si la cuenta ya es v2 (`:245-247`).
2. **Guard de escala per-100**: cuenta filas de `import_normalized_tx` donde `(unit_price·quantity)/gross_amount` está fuera de `[0.2, 5]`; con una sola, no migra (`:249-282`). El chequeo va sobre la **fuente**, no sobre `operations`, porque un rebuild borra la firma en `operations` pero deja el cash inflado.
3. **Pata 1 — re-estampar flujos**: `import_normalized_tx.gross_amount_usd = gross_amount / fx_for_date(date)` para toda fila ARS **con `fingerprint IS NOT NULL`** y `notes NOT LIKE 'Estado inicial%'` (`:302-337`). La exclusión de las sintéticas está documentada con el caso medido: una fila de 130.667.268 pesos fechada un domingo daba US$ 3.090.522, el 92 % del aportado de la cuenta #324.
4. Captura `price_override`/`tc_compra`/`notes` de los grupos `(broker, asset, currency)` que tengan alguno, para restaurarlos después del rebuild (`:345-362`).
5. `set_fx_version(v2)` **antes** del rebuild, porque el rebuild lee la versión (`:364-365`).
6. **Pata 2 — rebuild de TODOS los batches confirmados** (`:367-380`). Si algún activo falla, `ok=False` y el caller debe hacer rollback: "o sale todo, o no sale nada" (`:381-388`).
7. Restaura overrides no ambiguos; los grupos con más de un valor distinto van a `overrides_ambiguos` (`:390-416`).
8. Completa `tc_compra` de lotes ARS sin TC, **excluyendo** batches `parser_format LIKE '%tenencia%'` (la `entry_date` de un lote de foto es falsa) (`:418-444`).
9. `recalc` → `backfill_snapshots` → `recompute_netdep` (`:446-449`).
10. **Verificación**: cada venta ARS quedó al TC de su fecha (±1 %), los flujos dejaron de estar todos al mismo TC, y la caja no se movió (`:451-...`).

**Cuándo se dispara**: `[V]`

| Trigger | Dónde |
|---|---|
| **Automático, después de cada import confirmado** de una cuenta todavía en v1, con `force=False` | `backend/main.py:30975` → `_auto_migrar_fx_post_import` `backend/main.py:30573-30638` |
| Admin, una cuenta: `/api/admin/fx-migrate-user` | `backend/main.py:16889` |
| Admin, tanda: `/api/admin/fx-migrate-batch` | `backend/main.py:17239` |

El auto-trigger corre **fuera** de la transacción del import, con su propia conexión, y su fallo no toca el import (`backend/main.py:30596-30631`). Al terminar invalida el caché de IA (`:30634-30637`).

---

### 8. `cash_sim.py` — la simulación de caja

`simulate(...)` (`backend/importing/cash_sim.py:40-183`) es **solo de preview**: no toca la base y **no bloquea nada** (docstring `:8-10`). `[V]`

- Mismo orden que el persister: `(date, BUY primero, row_index)` (`:51-55`).
- Ruteo virtual: si `route_by_currency`, proyecta el nombre `"<parent> · USD"` sin crearlo (`:62-89`).
- Emite un `CashWarning` solo cuando el saldo **cruza** de ≥0 a <0 (`:106-115`); las ventas nunca generan warning (`:137`).
- Se consume en `pipeline.run_preview` (`:801-843`) y produce tres campos del payload: `cash_warnings`, `projected_cash` (apilado sobre el saldo actual) y `projected_cash_standalone` (solo este archivo, desde cero — para detectar re-imports). El front los muestra en `frontend/src/components/import/ImportWizard.jsx:2361-2376`.

**Divergencias con el persister** (el simulador no es el mismo motor): `[V]`
- para `SELL` usa `gross_amount − fees` (`:134-135`), mientras el persister usa `reconciled_unit_price × qty − comisión` (`persister.py:704`, `:794`);
- no modela `cash_broker_for`: un `BUY` USD lo manda entero al sibling (`:87-88`), mientras el persister deja la tenencia en el padre y solo la plata en el sibling. Para la **caja** el resultado coincide; para el activo, no (pero el simulador no simula activos);
- no aplica `reconciled_unit_price` en `BUY` (`:125`).

La reconciliación de caja "de verdad" no vive acá: es (a) el `cash_health` que devuelve `persist_batch` (`persister.py:447-462`), que el front convierte en tarjetas "Confirmá el cash con tu broker" (`ImportWizard.jsx:2892-2915`); y (b) el true-up contra la foto (`tenencia.build_cash_trueup_txs`).

---

### 9. Incidentes: cómo se registran los errores y dónde los ve el usuario

| Etapa | Se registra en | Lo ve el usuario |
|---|---|---|
| Archivo ilegible / formato desconocido / > 5 MB / > 10.000 filas | `{"error": ...}` del `run_preview` → `HTTPException(400)` | banner de error del wizard (`ImportWizard.jsx`, `setError`) |
| Parse / normalize / validate por fila | `import_raw_rows.status='invalid'` + `errors_json` (`pipeline.py:710-720`) y `errors` plano del preview (`preview.py:80-85`, `:133`) | tabla de errores del preview |
| Overdraft proyectado | `preview.cash_warnings` (`pipeline.py:816-826`) | `ImportWizard.jsx:2361-2376` |
| Duplicados detectados | `preview.duplicate_row_indices` + `brokers_already_imported` + `duplicate_of_batch_id` | aviso de re-import |
| Fila que revienta **al persistir** | `SAVEPOINT` → `ROLLBACK TO` → `skipped[]` → `summary.skipped_rows` (`persister.py:420-429`, `:474`) | bloque ámbar "N filas no se importaron" (`ImportWizard.jsx:2919-2938`) |
| Duplicados auto-salteados | `auto_skipped_duplicates` en el response (`backend/main.py:30987`) | chip azul "N ya estaban (omitidas)" (`ImportWizard.jsx:2868-2870`) |
| Saldos finales por broker | `summary.cash_health` | tarjetas de reconciliación de caja (`ImportWizard.jsx:2892-2915`) |
| Avisos de escala de la foto | `avisos_escala` del preview de tenencia (`backend/main.py:30294-30328`) | pantalla de reconciliación |
| **Fallo de cualquier paso post-proceso** (rebuild, sweeps, tags, normalizadores, recalc, backfill, FCI) | **solo `traceback.print_exc()`** — 7 bloques idénticos en `backend/main.py:30846-30968` | **nada**. El import devuelve `ok: true` |
| Fallo de la migración FX automática | `log.info`/`log.exception` + `fx_migracion: {"migrada": false, "motivo": ...}` en el response | campo del response; no hay UI dedicada verificada |
| Fallo de la reconstrucción MTM | `log.exception` dentro del thread | nada (`mtm_reconstruccion: {"reconstruida": "en_curso"}` se devuelve siempre) |
| True-up de caja aplicado | `log.info` (`backend/main.py:30208-30210`) — el comentario dice "SILENCIOSO, la foto manda" | **no se le muestra**. Solo lo ve un admin vía `check_caja_concilia` |
| Comisión implausible descartada | `_log.warning` + se agrega la nota `⚠ Comisión de N% descartada…` a `tx.notes` (`normalizer.py:409-415`) | la nota viaja en el preview y queda en `positions.notes`… **hasta el primer rebuild**, que pone `notes=None` (`rebuild.py:749`) |

Historial: `GET /api/imports` (`backend/main.py:31627`) y `GET /api/imports/{batch_id}` (`:31637`), que devuelve `import_raw_rows` con sus `errors_json`.

Lo que no existe: **no hay tabla de incidentes ni contador persistido de fallos de post-proceso**. El único rastro de que un rebuild falló es la salida estándar del proceso. `[V]`

---

### 10. `sim_import.py` y `proyeccion.py`

#### `backend/sim_import.py` — script CLI, no está en el servidor

`python3 sim_import.py "<ruta al .xlsx>" [parser_format]` (`:6`). Crea una DB temporal (`DB_PATH` a un `NamedTemporaryFile`, `:14-15`), vacía 11 tablas, crea un usuario y un broker ARS, y corre `run_preview → load_session_for_confirm → persist_batch → rebuild → sweeps → recalc` (`:56-76`). Imprime los agregados que vería el dashboard, con semáforos para "capital aportado negativo" y "ganancias retiradas fantasma" (`:90-102`). `[V]`

**Uso**: no lo importa nadie. Grep en `backend/` + `frontend/src`: la única mención fuera del propio archivo es un comentario en `backend/tests/test_backfill_currency_fix.py:6` ("están verificadas con archivos reales vía sim_import"). Es una herramienta de diagnóstico manual del founder, no código de producción. `[V]`

⚠️ Es el único lugar del repo donde se llama a `persist_batch` + `rebuild` **sin** pasar por `_recalc_pnl_realized_from_ops`… no, sí lo llama (`:73`). Pero **no** corre `_backfill_snapshots_from_monthly` ni la migración FX, así que sus números no son idénticos a los de un confirm real.

#### `backend/importing/proyeccion.py` — vivo, en el camino de la foto

- `proyectar(conn, uid, pair, fecha)` (`:67`) rueda `positions` hacia atrás a la fecha D. La decisión de diseño está escrita en el docstring (`:9-33`): **ancla en `positions`, no en un replay del ledger**, para no crear un segundo motor de tenencia.
- Lo que no se puede rodar hacia atrás sale en `no_reconciliable` con motivo cerrado: `datos_manuales`, `vencimiento_en_ventana`, `split_en_ventana` (`:58-60`). Lo que sí se corrige es la amortización de bonos (re-escala por `residual_factor(D)/residual_factor(hoy)`).
- `verificar_contra_snapshot(conn, uid, fecha, current)` (`:194`) con tres estados: `verificado_ok`, `no_coincide`, `sin_referencia` (`:189-191`). Compara **composición**, no cantidades, porque `snapshots.holdings_json` guarda `value_usd`.

**Uso**: `backend/main.py:29864` (`proyectar` dentro de `_qty_a_fecha`), `:30258` y `:30271` (`verificar_contra_snapshot` + el estado que alimenta el campo `confianza` del response). También `backend/scripts/verificar_proyeccion.py:20` y `backend/scripts/escala_foto_bonos.py:28`. **Está vivo.** `[V]`

El endpoint es explícito sobre lo que la verificación respalda y lo que no (`backend/main.py:30392-30412`): `to_seed` y `not_in_snapshot` son de composición y quedan `verificada_composicion`; **`over` es de cantidad y queda `sin_verificar_cantidad`** — y es justo el balde que puede reducir una tenencia.

---

### 11. Cosas raras, dudosas o muertas

1. **`PipelineResult` (`schema.py:287-295`) no se usa.** `run_preview` devuelve un dict armado por `build_preview`. El dataclass que documenta el "resultado final de preview" es letra muerta. `[V]`
2. **La rama `else` del preview de tenencia es inalcanzable** — ver §5.7 (`backend/main.py:30125-30169`). `[V]`
3. **`FORMAT_BASE_CURRENCY` tiene una clave `'ibkr'` (`pipeline.py:438`) sin parser correspondiente** en `registry.py`. `[V]`
4. **`store_preview_txs` promete idempotencia que no implementa** — ver §3.4. `[V]`
5. **`reconstruct_csv_from_batch` pierde las marcas del parser.** Escribe solo las 12 columnas canónicas y descarta explícitamente toda clave que empiece con `_` (`pipeline.py:1255-1258`, `:1266-1268`). O sea que `_transfer_out`, `_corporate_close` y `_cost_basis_pending` **no** sobreviven a "Editar y rehacer" (`POST /api/imports/{batch_id}/redo`, `backend/main.py:31930`): al re-previsualizar, una venta con precio 0 que antes pasaba por `corporate_close`/`transfer_out` ahora falla con `MISSING_PRICE` (`validator.py:115-120`). `[V]`
6. **"Editar y rehacer" sobre un batch de FOTO produciría basura.** `store_preview_txs` guarda `raw_json` con las claves `{asset, op, qty, price, notes}` (`pipeline.py:1015-1019`), pero `reconstruct_csv_from_batch` escribe los headers canónicos `fecha/tipo/broker/...` y `normalize_rows` los busca por esos nombres (`normalizer.py:268`, `:277`, `:316`). El CSV reconstruido saldría con todas las columnas vacías → `INVALID_DATE` en todas las filas. `[I]` — inferido de esas tres citas; no encontré un guard que impida el `redo` sobre un batch de tenencia.
7. **`load_session_with_seed_revalidate` pierde `transfer_out`.** Su `INSERT INTO import_normalized_tx` (`pipeline.py:1180-1194`) no incluye la columna `transfer_out`, a diferencia del de `store_preview_txs` (`:1025-1037`). Además re-normaliza desde `raw_json`, con el mismo problema de claves del punto 6. Como el frontend nunca manda `seed_state` junto con una sesión de tenencia (`ImportWizard.jsx:719-724` manda solo `session_id`, `skip_row_indices`, `aprobar_tickers`), hoy no muerde; es una mina latente. `[I]`
8. **`_persist_futures_pnl` inserta `quantity=None`** en `operations` (`persister.py:880-885`). El resto de las inserciones de `operations` del persister sí llenan `quantity`.
9. **`FX_USD_TO_ARS` exige que el broker esté marcado `'USDT'`, literal** (`persister.py:1155`, `validator.py:146`). Un broker marcado `'USD'` (Schwab, Balanz Internacional) no puede originar una conversión, aunque `cash_broker_for` y `_norm_cur` traten `USD` y `USDT` como equivalentes en todo el resto del módulo. `[V]`
10. **El desempate FIFO del mismo día lo decide el orden de la fila.** `date` no tiene hora (`schema.py:205`), el orden es `n.id ASC` (`rebuild.py:557-560`), y el comentario de `_replay_asset` (`rebuild.py:379-386`) dice que el pool único **amplía** la superficie del problema porque ahora el empate decide también qué **moneda** paga y, con ella, un costo convertido por FX.
11. **`_replay_asset` no es FIFO puro sobre el pool**: `_same` (misma moneda) va antes que `_other` sin mirar `entry_date` (`rebuild.py:387-392`, `:369-377`). Documentado como limitación conocida.
12. **`_is_safe_to_rebuild` carga en memoria TODOS los `position_id`/`operation_id` linkeados del usuario, por cada activo** (`rebuild.py:583-596`). Con un usuario de muchos batches eso son dos scans completos por activo del lote.
13. **`check_caja_concilia` matchea por `notes LIKE 'Ajuste de cash a Estado de Cuenta%'`** (`invariantes.py:238`), mientras que el productor arma el texto con f-string en `tenencia.py:692`. Es un acoplamiento por string entre dos módulos, igual que `TENENCIA_APERTURA_NOTE_PREFIX` (que sí está centralizado).
14. **La política de `parse_number` con "150.000"**: `_es_ambiguo_miles` + `_desambiguar_por_triangulo` corrigen **solo** cuando el triángulo lo prueba; si no se puede probar, se deja el número como está y **no** se rechaza la fila (`normalizer.py:346-362`). El comentario explica que rechazarla rompía imports de Binance, Balanz e IEB que entraban bien.
15. **El `notes` con el aviso de comisión implausible se pierde**: se escribe en `positions.notes` en el `BUY` (`persister.py:588-596`) y el primer rebuild del activo lo pone en `None` (`rebuild.py:749`). `[V]`
16. **`_backfill_snapshots_from_monthly` borra snapshots futuros en cada corrida**: `DELETE FROM snapshots WHERE user_id=? AND date > hoy` (`persister.py:1379-1380`). Es intencional (evita que un month-end futuro y deflactado sea el "último" de la cuenta), pero es un `DELETE` incondicional dentro de una función llamada "backfill".
17. **`import_batches` está indexada por `(user_id, file_hash, status)`** (`backend/main.py:2467-2468`), pero `find_duplicate_batch` es puramente informativo: nada impide confirmar dos veces el mismo archivo si los fingerprints difieren.

---

### 12. Resumen de riesgos, ordenado

| # | Riesgo | Severidad | Cita |
|---:|---|---|---|
| 1 | El recalc post-import **anula** la corrección de capital aportado del FX (`FIX bug #1`) | alto | `persister.py:1136-1143` vs `main.py:612` + `main.py:9583-9593` + `main.py:30930` |
| 2 | Los fallos de los 7 pasos de post-proceso son **invisibles**: solo `traceback.print_exc()`, el import responde `ok: true` | alto | `main.py:30846-30968` |
| 3 | `invariantes.py` está **dormido** en el camino de import (solo endpoint admin) | alto | `main.py:17771` es el único caller |
| 4 | Dividendos/intereses en pesos dolarizados con el blue de **hoy**, incluso en cuentas FX v2, y sin estampar `currency`/`fx_to_usd` | medio-alto | `persister.py:979-988` |
| 5 | `persist_batch` usa `config.tc_blue` mientras el resto del pipeline usa el blue live (`_read_tc_blue`) | medio | `persister.py:341-351` vs `:1299-1321` |
| 6 | "Editar y rehacer" pierde `_transfer_out` / `_corporate_close` / `_cost_basis_pending` | medio | `pipeline.py:1255-1268` |
| 7 | Rebuild pisa `positions.notes` sin restaurarlo | medio | `rebuild.py:749` |
| 8 | Re-importar un export **distinto** del mismo período duplica (el fingerprint no matchea) | medio | `pipeline.py:775-779` |
| 9 | Cada import de una cuenta v1 dispara un rebuild de **todo** el histórico vía `migrate_user_fx` | medio | `main.py:30975` → `fx_migrate.py:367-380` |
| 10 | `over` de partición cross-currency puede ser falso; documentado y no arreglado | medio | `main.py:30046-30073` |
| 11 | Ninguna cota de magnitud sobre montos en el validator; el único guard es un **aviso** en la foto | medio | `validator.py` (ausencia) + `main.py:30294-30328` |
| 12 | `load_session_with_seed_revalidate` pierde `transfer_out` y re-normaliza `raw_json` con claves incompatibles | bajo (latente) | `pipeline.py:1180-1194` |
| 13 | `else` muerto en el preview de tenencia | bajo | `main.py:30125` |
| 14 | `store_preview_txs` documenta idempotencia inexistente | bajo | `pipeline.py:992-1038` |
