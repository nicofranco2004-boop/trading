## Flujos end-to-end

Trazado sobre `origin/main` @ `b74f450f` (2026-09-05). Cada paso lleva `archivo:línea`.
Convención: `[V]` = verificado leyendo el código en esa línea · `[I]` = inferencia (digo de qué me agarré).

Antes de empezar, tres piezas transversales que aparecen en casi todos los flujos:

| Pieza | Dónde | Qué hace |
|---|---|---|
| `get_effective_user` | `backend/main.py:2806` | Depends por defecto de los endpoints de DATOS. Resuelve JWT → uid, y si viene el header `X-Rendi-Client-Id` puede devolver el uid del CLIENTE (lente del asesor) |
| `get_current_user` | `backend/main.py:2806` lo envuelve; se usa directo en identidad/billing/admin/advisor | uid real, sin lente |
| `_ai_cache_invalidate(uid)` | `backend/main.py:25863` | Se llama después de casi toda mutación. Borra el cache de análisis IA + `_CHAT_VAL_CACHE` |

---

## 1. Alta de usuario: registro → verificación → onboarding → primera cartera

### Los pasos

1. **[V]** El CTA de la landing apunta a `/login?mode=register`; `frontend/src/pages/Login.jsx:34` lee el query param para arrancar en modo registro.
2. **[V]** Submit → `frontend/src/pages/Login.jsx:126` elige endpoint: `/api/auth/login` o `/api/auth/register`. Validación cliente: password ≥ 10 (`Login.jsx:115`) y nombre no vacío (`Login.jsx:119`).
3. **[V]** `POST /api/auth/register` — `backend/main.py:3094`.
   - **Bifurcación A (gate de registro):** `backend/main.py:3100` — si `ALLOW_REGISTRATION` es false (env var, default `"true"`, `backend/main.py:121`) y el email NO es de admin → 403. Si es admin, pasa igual.
   - Rate limit 5 llamadas / 300 s por IP: `backend/main.py:3101`.
   - Validación del modelo: `RegisterIn` normaliza el email a `strip().lower()` y lo matchea contra `_EMAIL_RE` (`backend/main.py:2866-2872`); password mín. 10 (`backend/main.py:2874-2879`). **No hay chequeo de complejidad más allá del largo.**
4. **[V]** INSERT en `users` con `approved=1` SIEMPRE y `email_verified = 1 solo si es admin` (`backend/main.py:3111-3118`). El gate de aprobación manual está muerto; la columna `approved` queda por compat (comentario en `backend/main.py:3204-3206`).
   - **Bifurcación B (admin):** si `_is_admin_email(email)`, además hereda los datos legacy con `user_id=0` en `positions/monthly_entries/operations/config` (`backend/main.py:3122-3125`) e infiere moneda por nombre de broker (`backend/main.py:3131-3148`).
5. **[V]** Se siembran dos filas de config: `tc_mep=1415` y `tc_blue=1415` (`backend/main.py:3151-3152`). Son los valores por defecto de la app; sobreviven hasta que alguien los edite.
6. **[V]** **Bifurcación C (verificación):**
   - **No-admin** → se crea código OTP síncrono (`_create_verification_code`, llamado en `backend/main.py:3158`), el envío del email va a un `BackgroundTask` (`backend/main.py:3159-3161`, worker en `backend/main.py:3076`) y se devuelve `{"needs_verification": true}` **sin token** (`backend/main.py:3162-3166`).
   - **Admin** → token directo + cookie, sin verificación (`backend/main.py:3169-3176`).
   - Email duplicado → 409 estructurado `{"code": "EMAIL_ALREADY_REGISTERED"}` (`backend/main.py:3178-3184`), que el front usa para ofrecer "ir al login" (`frontend/src/pages/Login.jsx:170`).
7. **[V]** El front redirige a `/verify-email?email=…` (`frontend/src/pages/Login.jsx:211-219`).
8. **[V]** `POST /api/auth/verify-email` — `backend/main.py:3240`. Rate limit 5/60 s **por email** (`backend/main.py:3255`). Toma el código no usado más reciente (`backend/main.py:3268-3273`), compara con `hmac.compare_digest` (`backend/main.py:3276`) y chequea expiración (`backend/main.py:3281-3286`).
   - **Decisión importante:** solo mira **el último código no usado**. Si el usuario pidió reenvío, los códigos anteriores dejan de servir de hecho aunque no estén marcados `used_at`.
9. **[V]** Al verificar: `email_verified=1`, se registra login (`_record_login_and_maybe_alert`, `backend/main.py:3297`), se manda el mail de bienvenida best-effort (`backend/main.py:3303-3308`), se alerta al equipo si `signup_count <= ADMIN_SIGNUP_ALERT_LIMIT` (default 100, `backend/main.py:2921`; uso en `backend/main.py:3312-3322`) y se emite token + cookie (`backend/main.py:3324-3330`).
10. **[V]** El front hace login y **decide el destino con localStorage**: `frontend/src/pages/VerifyEmail.jsx:141-149` — si `rendi_onboarding_skipped` o `rendi_onboarding_completed` están en `'1'`, va a `/`; si no, a `/onboarding`.
11. **[V]** Onboarding de 3 pasos — `frontend/src/pages/Onboarding.jsx:39-40` (`welcome` → `position` → `complete`). El guard de sesión está en `frontend/src/pages/Onboarding.jsx:69-73`.
12. **[V]** Paso "cartera" (`frontend/src/components/onboarding/PositionStep.jsx`) — **tres caminos**:
    - **CSV** → setea `rendi_onboarding_pending='1'` y navega a `/imports?from=onboarding` (`PositionStep.jsx:47-57`). Sigue en el flujo 2.
    - **Manual** → `POST /brokers` primero (`PositionStep.jsx:195`) y después `POST /positions` (`PositionStep.jsx:214-220`). El comentario de `PositionStep.jsx:192-194` dice explícitamente que `POST /positions` NO auto-crea el broker.
    - **Saltar** → `handleSkip` marca `rendi_onboarding_skipped` y navega a `/posiciones` (`frontend/src/pages/Onboarding.jsx:90-99`).
13. **[V]** Si el broker devuelve 403 por cuota (Free = 1 broker), el paso muestra "Tu plan no permite más brokers" (`PositionStep.jsx:200-204`); el 403 lo emite `backend/main.py:4060-4079`.

### Rarezas y cosas que anoto sin corregir

- **[V]** `POST /api/auth/verify-email` devuelve solo `{token, name, verified}` (`backend/main.py:3325-3329`), pero el front lee `data.user_id || data.id`, `data.is_admin` y `data.email` (`frontend/src/pages/VerifyEmail.jsx:135-140`). Los tres llegan `undefined`. El `login()` del contexto recibe id/email vacíos en el signup — el `sign_up` de analytics arranca sin identificador propio.
- **[V]** La decisión "¿va al onboarding?" es 100% localStorage, no estado del servidor (`VerifyEmail.jsx:143-144`). Un usuario que verifica desde otro dispositivo repite el wizard.
- **[V]** El comentario de `frontend/src/pages/Onboarding.jsx:11-12` dice que el trigger es "si el user no tiene brokers cargados (es fresh signup)". Eso **no** es lo que hace el código: no se consulta ningún broker, solo las dos flags de localStorage.
- **[V]** El registro auto-aprueba a todos (`backend/main.py:3113`), pero sigue existiendo `POST /api/admin/users/{user_id}/approve` (`backend/main.py:20146`).

---

## 2. Importar un archivo de broker

Es el flujo más largo del sistema y el que más veces puede pisar lo anterior. Lo marco paso a paso; los puntos de pisada van rotulados **⚠ PISA**.

### 2.1 Subida y detección

1. **[V]** Wizard: `frontend/src/components/import/ImportWizard.jsx` con 7 estados — `intro`(:70) → `upload`(:71) → `map`(:72) → `preview`(:73) → `seed`(:74) → `reconcile`(:79) → `done`(:83).
2. **[V]** Si el usuario adjunta varios archivos, el wizard le pregunta al backend cuál es la FOTO: `POST /imports/classify-tenencia` (`ImportWizard.jsx:506`) → `backend/main.py:29496`. Clasifica por contenido: PDF→bullmarket, xlsx multi-hoja→ieb, xlsx con grilla PPI→ppi, xlsx inviu→inviu, CSV con header Cocos→cocos (`backend/main.py:29520-29546`). Devuelve el PRIMERO que matchee.
3. **[V]** **Bifurcación (parser específico vs mapeo manual):**
   - Parser específico (`isSpecificParser`) → va derecho a `POST /imports/preview` (`ImportWizard.jsx:531-533`).
   - Genérico → `POST /imports/inspect` (`ImportWizard.jsx:540`) → paso `map` → recién ahí `preview` (`ImportWizard.jsx:575-577`).
4. **[V]** `POST /api/imports/preview` — `backend/main.py:30439`. Acepta `files` (lista) o `file` (legacy); si vienen ambos gana `files` (`backend/main.py:30458-30462`). Cap de 20 archivos (`backend/main.py:30466`) y lectura chunked contra `MAX_TOTAL_BYTES` (`backend/main.py:30473-30494`). Los archivos se **concatenan** en uno con `combine_csv_files` (`backend/main.py:30497`).

### 2.2 Parseo y normalización — `run_preview` (`backend/importing/pipeline.py:440`)

5. **[V]** Hash del archivo + búsqueda de batch duplicado (`pipeline.py:456-457`). Solo informativo: se devuelve como `duplicate_of_batch_id`, no bloquea.
6. **[V]** Decodifica/convierte a CSV (`pipeline.py:462`, `to_csv_text` maneja xlsx y encodings).
7. **[V]** **Bifurcación de parser** (`pipeline.py:470-480`): con `mapping` se traduce el CSV a headers internos y se corre `rendi_generic`; con `parser_format` se busca el parser específico.
8. **[V]** **Fallback silencioso de parser** (`pipeline.py:492-505`): si el parser elegido devuelve 0 filas + errores, se **autodetecta por headers** y, si el alternativo sí parsea, `parser` y `parse_result` se reemplazan. El usuario eligió "Balanz" y puede terminar importando con otro parser sin verlo explícito.
9. **[V]** `normalize_rows` (`backend/importing/normalizer.py:255`) → `List[NormalizedTx]` + errores por fila.
10. **⚠ PISA — canonicalización de broker.** `pipeline.py:518-526`: los nombres de broker de las filas se reescriben al nombre canónico existente por `strip().lower()`. "Cocos capital" pasa a ser "Cocos Capital".
11. **⚠ PISA — auto-heal de moneda del broker.** `pipeline.py:544-563`: si el broker destino ya existe con moneda distinta a la base del parser (`FORMAT_BASE_CURRENCY`) **y está vacío de posiciones**, se hace `UPDATE brokers SET currency=…`. Con posiciones cargadas no lo toca (`pipeline.py:557-559`).
12. **⚠ PISA — auto-creación de brokers.** `pipeline.py:569-635`: cualquier broker del CSV que no exista se INSERTA, con moneda inferida en cascada: nombre cripto conocido → USDT; moneda base del parser → esa; mayoría USDT → USDT; mayoría ARS → ARS; **cualquier otro caso → USD** (`pipeline.py:610-619`). Este INSERT ocurre en **preview**, o sea antes de que el usuario confirme nada.
13. **[V]** **Auto-ruteo por moneda** (`pipeline.py:648-655`): si un broker ARS trae alguna fila USD/USDT o una FX, se prende `route_by_currency` solo. Se decide ANTES de validar.
14. **[V]** Validación (`backend/importing/validator.py:37`) con estado del usuario ya modificado por los pasos 11-12.

### 2.3 Persistencia del preview

15. **[V]** `cleanup_stale_previews(conn)` se ejecuta acá y no antes, deliberadamente, porque es el primer write y en SQLite el primer write toma el lock (`pipeline.py:699`, def en `pipeline.py:190`).
16. **[V]** INSERT del batch en estado `'preview'` (`pipeline.py:701-708`) + `import_raw_rows` (`pipeline.py:712-722`) + `import_normalized_tx` (`pipeline.py:751-762`).
17. **[V]** **Estampado del FX al momento de escribir** (`pipeline.py:736-737`): `tc_blue_at_import` se lee de la config del usuario; si la cuenta está en FX v2 se usa `fx_for_date(tx.date)`. El `gross_amount_usd` queda congelado en la fila.
18. **[V]** El preview devuelve, además del detalle: `duplicate_row_indices`, `new_brokers_created`, `brokers_already_imported` (`pipeline.py:775` y `:786`), `cash_warnings` + `projected_cash` + `projected_cash_standalone` (`pipeline.py:810` y `:836-838`), `seed_suggestions` (`pipeline.py:894`) y `routing_breakdown` (`pipeline.py:968`).

### 2.4 Confirmación — `POST /api/imports/confirm` (`backend/main.py:30738`)

19. **[V]** `load_session_with_seed_revalidate` (`backend/main.py:30749`) reinserta las txs (incluyendo el seed) en `import_normalized_tx`.
20. **[V]** Se arma el `skip_set`: filas que el usuario marcó (`backend/main.py:30757`) + las que llevan `[requiere-aprobacion]` y NO fueron nombradas en `aprobar_tickers` (`backend/main.py:30760-30766`). Este segundo es **opt-in**: falla cerrado.
21. **[V]** **Dedup cross-batch** (`backend/main.py:30775-30781`): las filas cuyo fingerprint ya existe en OTRO batch confirmado se saltean solas, salvo `include_duplicates`.
22. **⚠ PISA — borrado de las salteadas.** `backend/main.py:30783-30795`: las filas del skip_set se **DELETE**an de `import_normalized_tx` para que el log de "lo aplicado" no mienta. El comentario explica por qué es crítico: si quedaran, el rebuild FIFO las replayaría y el revert intentaría revertir cash que nunca se debitó.
23. **[V]** `persist_batch` (`backend/importing/persister.py:136`), todo dentro de `with conn:` → atómico.

### 2.5 Dentro de `persist_batch`

24. **[V]** Si hay `seed_state`, se generan txs sintéticas y se persisten como filas del batch (`persister.py:158-217`).
    - **[V] Trampa documentada:** el seed **nunca** se dolariza al TC de su fecha, ni en v2 (`persister.py:189-210`). El monto lo tipeó el usuario hoy y la fecha es "primer movimiento − 1 día". Hay un caso medido en el comentario: US$3.090.522 fantasma, 92% del aportado de una cuenta.
25. **[V]** Orden de ejecución: `(date, BUY antes que todo lo demás, row_index)` (`persister.py:224-229`).
26. **⚠ PISA — routing per-row.** `persister.py:243-274`: si `route_by_currency`, se crea el sibling `'<Padre> · USD'` (`_ensure_usd_sibling`, `backend/main.py:10776`) y se le fuerza una posición cash USD con 0 si no existía (`persister.py:265-273`). Después se **mutan `tx.broker`** y se hace `UPDATE import_normalized_tx SET broker=?` (`persister.py:308-314`) para que el revert lea el broker real.
    - **Sub-bifurcación (CEDEAR):** `persister.py:290-303` — para BUY/SELL en USD donde `cash_broker_for` dice otra cosa, la **tenencia queda en el padre** y solo la **plata sale del sibling** (`tx.cash_broker`). Las acciones del exterior (`STOCK`) sí van enteras al sibling.
27. **[V]** Loop por fila, cada una en su propio `SAVEPOINT` (`persister.py:353-425`). Una fila que falla se rollbackea sola y va a `skipped`; el resto sigue.
28. **[V]** Dispatch por tipo (`persister.py:361-410`): BUY→`_persist_buy`(:563), SELL→`_persist_sell_fifo`(:601), DEPOSIT→`_persist_cash_in`(:899), DIVIDEND/INTEREST→`_persist_dividend_or_interest`(:938), WITHDRAW/FEE/TAX→`_persist_cash_out`(:1000), FX→`_persist_fx`(:1108), FUTURES_PNL→`_persist_futures_pnl`(:863).
29. **[V]** `_repair_monthly_chain` por broker tocado + global (`persister.py:428-430`), `_backfill_snapshots_from_monthly` (`persister.py:437`) y `UPDATE import_batches SET status='confirmed'` (`persister.py:456-462`).

### 2.6 Post-proceso — **fuera** de la transacción

El comentario de `backend/main.py:30810-30826` explica por qué se movió afuera: antes el lock de escritura de SQLite quedaba tomado durante todo el post-proceso (incluido un fetch de red a data912), y **nadie en Rendi podía guardar nada** mientras un usuario importaba.

Cada uno corre en su propio `with conn:`, es best-effort y **puede pisar lo del anterior**:

| # | Paso | Línea | ⚠ Qué pisa |
|---|---|---|---|
| 30 | `rebuild_fifo_after_import` | `backend/main.py:30841-30846` | Reconstruye lotes y ventas de cada (par, activo) tocado replayando TODO su historial. **Reescribe `positions` con `price_override=None`** (por eso el FCI override va al final) |
| 31 | `sweep_matured_letras` | `backend/main.py:30858` | Cierra letras vencidas → borra tenencia fantasma |
| 32 | `sweep_bond_amortizations` | `backend/main.py:30872` | **Re-escala el nominal** de bonos amortizantes a residual |
| 33 | `tag_bonds_from_data912` | `backend/main.py:30893` (precalentado en `:30891`) | Reescribe `asset_type` a BOND |
| 34 | `normalize_bond_units` | `backend/main.py:30905` | **Reescribe el cost basis** de per-100 a per-1 |
| 35 | `normalize_usd_commissions` | `backend/main.py:30915` | **Reescribe comisiones** de ARS a USD |
| 36 | `_recalc_pnl_realized_from_ops` | `backend/main.py:30930` | Reescribe `monthly_entries.pnl_realized/deposits/withdrawals` desde las fuentes |
| 37 | `_backfill_snapshots_from_monthly` (2ª vez) | `backend/main.py:30943` | Re-corre los snapshots de fin de mes con el capital ya corregido |
| 38 | FCI `price_override` de la foto | `backend/main.py:30952-30966` | **Va último a propósito**: el rebuild del paso 30 lo borraría |
| 39 | `_auto_migrar_fx_post_import` | `backend/main.py:30975` (def en `:30564`) | Migra la cuenta ENTERA v1→v2. **Reescribe el P&L realizado y el aportado de toda la cuenta**, no solo del broker importado |
| 40 | `_reconstruir_mtm_post_import` | `backend/main.py:30984` (def en `:30715`) | Lanza un **thread daemon** que reconstruye snapshots a mercado. Sale a yfinance con timeout 8s por ticker |

- **[V]** El orden 39→40 es deliberado: la migración FX reescribe el P&L realizado, que es sumando del costo sobre el que se apoya la reconstrucción (`backend/main.py:30977-30983`).
- **[V]** El paso 40 es asíncrono: la respuesta devuelve `{"reconstruida": "en_curso"}` (`backend/main.py:30730`) y la curva aparece sola cuando el thread termina.

### 2.7 Después de la foto (cadena Bull Market / PPI / etc.)

41. **[V]** Si el wizard también tenía un archivo de tenencia, tras el confirm de movimientos llama a `POST /imports/tenencia/preview` (`ImportWizard.jsx:688`) y **frena** en el paso `reconcile` para que el usuario decida (`ImportWizard.jsx:694-698`). Aplicar es un segundo `POST /imports/confirm` con `aprobar_tickers` (`ImportWizard.jsx:726-730`).

### 2.8 Lo que ve en Cartera

42. Salta al **flujo 5**. Nada del import escribe un "valor de cartera" — ese número se calcula en el browser en cada render.

### Inventario de puntos donde algo pisa lo anterior

1. `pipeline.py:518-526` — nombre de broker canonicalizado.
2. `pipeline.py:544-563` — moneda del broker reescrita (auto-heal).
3. `pipeline.py:569-635` — brokers creados en **preview**, sin confirmación.
4. `backend/main.py:30783-30795` — filas salteadas borradas de `import_normalized_tx`.
5. `persister.py:243-314` — `tx.broker` mutado + fila de DB reescrita (routing).
6. `backend/main.py:30841` — rebuild FIFO reescribe posiciones y ventas (y borra `price_override`).
7. `backend/main.py:30872` — sweep de amortizaciones re-escala nominales.
8. `backend/main.py:30905` / `:30908` — cost basis y comisiones reescritos.
9. `backend/main.py:30930` — recalc reescribe `monthly_entries` (con preservación del "residual manual", ver `backend/main.py:9434-9441`).
10. `backend/main.py:30975` — migración FX reescribe P&L y aportado de **toda la cuenta**.
11. `backend/main.py:30984` — thread MtM escribe snapshots **después** de que el request terminó.

---

## 3. Subir una "foto" de tenencia y cómo convive con el historial

`POST /api/imports/tenencia/preview` — `backend/main.py:29661`.

### Los pasos

1. **[V]** Lectura chunked contra `MAX_FILE_BYTES` (`backend/main.py:29675-29685`).
2. **[V]** **Bifurcación por formato** (`backend/main.py:29688-29785`): `ieb` (xlsx multi-hoja), `ppi` (xlsx), `inviu` (xlsx), `cocos` (CSV), y para PDF **auto-detección por contenido** entre Balanz / IOL / Bull Market (`backend/main.py:29769-29785`).
3. **⚠ PISA — canonicalización de tickers** (`backend/main.py:29790`, `normalizar_tickers` en `backend/importing/tenencia.py:197`). Sin esto la foto dice AL30D donde Rendi dice AL30 y el reconcile inventa dos problemas. El resultado viaja SIEMPRE en `tickers_normalizados`.
4. **[V]** **Resolución de fecha, tres escalones** (`backend/main.py:29824-29830`): del archivo → del nombre del archivo (`fecha_de_nombre_archivo`, `tenencia.py:165`) → `fallback_hoy` (reloj del servidor). El origen se declara en `fecha_origen`.
   - Dato medido, en el propio comentario (`backend/main.py:29803-29811`): **93 de 152 fotos confirmadas en prod están con fecha inventada**, y `parse_cocos_tenencia` no setea fecha nunca (47 de 47).
5. **[V]** **Bifurcación crítica — contexto de asesor** (`backend/main.py:29881-29888`): si el uid autenticado ≠ el efectivo (o sea, un asesor mirando a un cliente) **y** la fecha es `fallback_hoy` → `motivo_corte = "fecha_desconocida"` y el flujo aborta con `nothing_to_do` + mensaje (`backend/main.py:30343-30357`). Para el usuario común el corte NO aplica, porque alcanzaría al 61% de las fotos.
6. **[V]** **Proyección hacia atrás** (`_qty_a_fecha`, `backend/main.py:29838-29869`): la reconciliación no compara contra el estado de hoy sino contra lo que había **a la fecha de la foto** (`backend/importing/proyeccion.py:67`). Solo proyecta si la fecha es real; con `fallback_hoy` devuelve el estado actual.
7. **[V]** **Bifurcación de camino** (`backend/main.py:29890` vs `backend/main.py:30123`):
   - **Particionado por moneda** (PPI/Balanz/IEB/Cocos/BMB/IOL/inviu): concilia el padre ARS y el sibling `· USD` por separado; si hay holdings USD y el sibling no existe, lo **crea** (`backend/main.py:30060-30064`).
   - **Agregado** (el resto): un solo `broker_pair`.
8. **[V]** **Re-tag cross-currency de bonos amortizantes** (`backend/main.py:30013-30058`): si el bono vive solo en la partición hermana, se le cambia `h.currency` y se hereda el costo unitario de los lotes existentes; si el costo es degenerado, se convierte por MEP. El propio comentario (`backend/main.py:30003-30012`) declara que este re-tag **no vuelve a fusionar** y puede dejar dos holdings con la misma (ticker, moneda) — **no está medido y no se toca**.
9. **[V]** `compute_reconcile` (`backend/importing/tenencia.py:327`) produce cuatro baldes: `matched`, `to_seed`, `over`, `not_in_snapshot`.
10. **[V]** Correcciones cross-partición (`backend/main.py:30081-30105`): a `not_in_snapshot` se le sacan los tickers que la foto trae en la otra moneda; `to_seed` se re-netea contra la cantidad del PAR con la misma tolerancia (`tolerancia_qty`, `tenencia.py:271`). **`over` NO se toca** — declarado en el comentario `backend/main.py:30084-30105` como asimetría conocida y sin medir.
11. **[V]** Dos gates opt-in: `marcar_bonos_amortizantes` (`tenencia.py:404`, llamado en `backend/main.py:30101`) y `marcar_ausentes` (`tenencia.py:497`, llamado en `backend/main.py:30104`). Marcan filas con `[requiere-aprobacion]` (`tenencia.py:397`) → no entran salvo que el confirm las nombre.
12. **[V]** **Modo OVERRIDE** — `_tenencia_apply_override` (`backend/main.py:29551`). Tres guardas duras porque el wizard aplica sin checkpoint:
    - `_is_safe_to_rebuild`: no toca activos con posiciones/ventas manuales (`backend/main.py:29586-29590`, helper `_reducible` en `:29583`).
    - same-broker: no reduce activos que tengan lotes en el sibling (`backend/main.py:29584-29586`, vía `sibling_assets`).
    - **cap 50%**: si cortaría >50% del valor **o** >50% de la cantidad de activos, aborta a solo gap-fill + cash (`backend/main.py:29618-29625`).
13. **[V]** Las reducciones/cierres se materializan como **ventas sintéticas `transfer_out`** fechadas en `max(fecha_foto, última fecha BUY/SELL)` (`backend/main.py:29654-29657`) para ordenarse DESPUÉS de las compras reales en el replay del rebuild.
14. **[V]** **Cash true-up** (`backend/main.py:30177-30208`): la foto pisa el efectivo con DEPÓSITO/RETIRO sintéticos. Gate: **solo si `_complete`** — si no, se saltea con log (`backend/main.py:30191-30194`). El motivo es que los parsers dejan `cash_ars/cash_usd` en `0.0` (no `None`) cuando el archivo no trae saldos, y sobre una lectura parcial el ajuste llevaba el efectivo a CERO en silencio.
15. **[V]** **`complete` es el gate de "borrar por ausencia"** (`backend/main.py:30008-30017` y `backend/main.py:30159-30162`): Balanz siempre, salvo que el parser avise sección vacía (`_BAL_WARN_SECCION_VACIA`); el resto solo si el parser no dejó warnings.
16. **[V]** El batch queda en `preview` (`store_preview_txs`, `pipeline.py:992`, llamado en `backend/main.py:30366`) con `override_info` persistido (`backend/main.py:30376-30377`) y `fund_price_overrides` si es Balanz (`backend/main.py:30370-30371`).
17. **[V]** Lo aplica el **mismo** `POST /api/imports/confirm` del flujo 2 — con toda su cola de post-proceso (rebuild, sweeps, recalc, snapshots, migración FX, MtM).

### Cómo convive con el historial

- **[V]** La foto **no reemplaza** el historial: se traduce a movimientos sintéticos (BUY de apertura, ventas `transfer_out`, DEPOSIT/WITHDRAW de cash) que entran al **mismo** pipeline y son revertibles y auditables (`build_tenencia_seed_txs`, `tenencia.py:598`).
- **[V]** El `row_index` de las filas sintéticas es `-20000 - i` (`backend/main.py:30117-30118` y de nuevo `:30213-30216`), renumerado dos veces: primero entre particiones, después incluyendo el cash. El comentario explica que `build_tenencia_seed_txs` reinicia en −20000 en cada llamada y ARS/USD colisionarían.
- **[V]** La respuesta declara **confianza asimétrica por balde** (`backend/main.py:30412-30425`): `to_seed` y `not_in_snapshot` son de composición y están respaldados por `verificar_contra_snapshot` (`proyeccion.py:194`), pero `over` es de cantidad y `snapshots.holdings_json` guarda **valor en USD, no cantidades** → `"over": "sin_verificar_cantidad"`. Es el único balde que puede reducir una tenencia.
- **[V]** **Aviso de escala** (`backend/main.py:30297-30329`): compara el DEPÓSITO de apertura contra el invertido existente del broker, normalizando pesos a USD. Avisa, no bloquea. El caso que lo originó está en el comentario: un aporte de US$1.700.854.139 (foto de IEB sembrada en Cocos con precios en pesos estampados como USD).

---

## 4. Alta manual de una compra y todo lo que se recalcula

`POST /api/positions` — `backend/main.py:8280`, cuerpo en `_insert_manual_position` (`backend/main.py:8206`).

### Los pasos

1. **[V]** El front abre el modal desde Cartera y postea (`frontend/src/pages/Positions.jsx:779`).
2. **[V]** `entry_date` default = hoy UTC (`backend/main.py:8213`).
3. **[V]** **Moneda nativa del lote**: la explícita del form, o inferida del broker — ARS si el broker es ARS, USD en cualquier otro caso (`backend/main.py:8216-8222`). El comentario dice que sin esto los lotes manuales quedaban NULL y mezclaban ARS+USD en el FIFO.
4. **[V]** **`tc_compra` auto-rellenado**: si el usuario lo dejó vacío y el lote es en pesos, se completa con `fx_for_date(entry_date)` (`backend/main.py:8228-8230`). Un TC tipeado manda siempre.
5. **[V]** INSERT en `positions` (`backend/main.py:8231-8238`).
6. **[V]** **Débito de cash** (`backend/main.py:8241-8283`) — solo si `is_cash=0`:
   - Costo = `_manual_position_cost` = `invested ?? buy_price×quantity` **+ comisiones** (`backend/main.py:8199-8204`). El comentario advierte que el alta y el undo grupal DEBEN usar la misma fórmula o el cash driftea.
   - **Bifurcación (autodepósito):** `_autodeposit_if_overdraw` (`backend/main.py:9809`). Si el costo supera el cash del broker, se auto-deposita el faltante: sube el cash **y** lo registra como capital aportado. Sin esto el P&L mentiría (comprar $1000 sin cash daría +$1000 de ganancia falsa).
     - El dólar del autodepósito es el **MEP de la fecha de la compra** (`_autodeposit_rate`, `backend/main.py:9794-9807`).
     - Escribe dos flujos mensuales: broker y global (`backend/main.py:9865-9866`) y repara las dos cadenas (`backend/main.py:9867-9868`).
   - `_adjust_broker_cash(conn, uid, broker, -cost)` (`backend/main.py:8253`). Si no existe posición cash, **la crea** con el delta (`backend/main.py:9773-9788`), y **se permiten saldos negativos** (`backend/main.py:9761`).
7. **[V]** **Foto de reversa**: se guarda `undo_meta_json` en la fila con `{cost, autodep, entry_date, broker}` (`backend/main.py:8262-8277`). Guarda el broker de ORIGEN porque el broker de la fila es mutable desde Cartera.
8. **[V]** Todo dentro de un `with conn:` (`backend/main.py:8286`).
9. **[V]** `_ai_cache_invalidate(uid)` (`backend/main.py:8288`).

### Qué se recalcula y qué NO

| Se recalcula | Dónde |
|---|---|
| Cash del broker | `_adjust_broker_cash` — `backend/main.py:9750` |
| `monthly_entries` deposits (broker + global), solo si hubo autodepósito | `_update_monthly_flow` × 2 — `backend/main.py:9865-9866` |
| Cadena de `capital_final` (broker + global), solo si hubo autodepósito | `_repair_monthly_chain` — `backend/main.py:9661` |
| Cache de IA | `backend/main.py:8288` |

**No se recalcula** (verificado por ausencia en `backend/main.py:8206-8296`):
- **[V]** No corre el rebuild FIFO. Coherente: `_is_safe_to_rebuild` (`backend/importing/rebuild.py:565`) justamente excluye activos con datos manuales.
- **[V]** No se tocan snapshots. La curva de evolución no cambia hasta el próximo cron o la próxima visita al Dashboard.
- **[V]** No se recalcula `pnl_unrealized` ni `capital_final` del mes salvo por la cadena del autodepósito.
- **[V]** Sin autodepósito (o sea con cash suficiente) **`monthly_entries` no se toca en absoluto**: el capital aportado no cambia (correcto — ya estaba aportado) pero tampoco se repara la cadena.

---

## 5. Ver la cartera

### 5.1 Qué pide el front

**[V]** `Positions.jsx:456-464` — `loadAll()` dispara 7 requests en paralelo:

| Request | Para qué |
|---|---|
| `GET /positions` | los lotes crudos (`backend/main.py:8186`, `SELECT * FROM positions WHERE user_id=?`) |
| `GET /config` | `tc_mep`/`tc_blue` como fallback |
| `GET /brokers` | moneda, `parent_broker_id`, `is_exchange` |
| `GET /dolar` | cotizaciones vivas (`backend/main.py:4978`) |
| `GET /snapshots?days=30` | base de la "variación diaria" |
| `GET /operations` | cupones y amortizaciones de bonos |
| `GET /bonds/cashflow/skips` | cupones descartados |

**[V]** Después, `fetchPrices` (`Positions.jsx:571`) arma la lista de símbolos con `buildPriceSymbols` (`frontend/src/utils/valuation.js:484`) y pide `GET /prices?symbols=…` (`Positions.jsx:580`) y `GET /prices/prev-close?symbols=…` (`Positions.jsx:587`, best-effort).

### 5.2 Cómo se resuelve el precio de cada activo

**[V]** `GET /api/prices` — `backend/main.py:7606`. Cascada:

1. **FCI** (`FCI:` prefix): salen de la tabla `fci_prices`, no de yfinance (`backend/main.py:7612-7631`). Viajan con `__meta.as_of` para que la pantalla pueda decir a qué fecha está valuado.
2. **Cache in-memory 60 s**: si todos los símbolos están frescos, se devuelve sin tocar ninguna fuente (`backend/main.py:7648-7651`).
3. **data912 (BYMA) — PRIMARIO para AR** (`backend/main.py:7673-7691`): bonos/ONs (`_resolve_ar_bond_price`) y después CEDEARs/acciones `.BA` (`_resolve_ar_equity_price`, marca `px_src='byma'`).
   - El comentario (`backend/main.py:7669-7681`) explica el porqué: yfinance no es confiable para `.BA` — devuelve la rueda en NaN o el ticker congelado (medido: DISN.BA clavado en 10.416 con volumen 0 durante 15 días contra 13.840 en BYMA). Como devuelve un número y no `None`, el fallback no se disparaba.
4. **yfinance** para lo que data912 no cubra (`backend/main.py:7686`).
5. **Último precio conocido** (`_fill_last_known_prices`, usado en `backend/main.py:7695`) — la tabla `asset_last_price`.

**[V]** Qué símbolo se pide por posición lo decide `valuationPriceKey` (`frontend/src/utils/valuation.js:469`) vía `buildPriceSymbols` (`valuation.js:484`). El espejo server-side es `position_price_key` (`backend/snapshots_job.py:105`) — declarado explícitamente SSoT para que armado, cobertura y valuación no diverjan (raíz del bug C1: el snapshot pedía el ticker US de un CEDEAR comprado por dólar-MEP → 15-100× inflado).

### 5.3 Qué se calcula en el browser

**[V]** Casi todo. El backend NO devuelve ningún "valor de cartera".

**Tipos de cambio** (`Positions.jsx:241-257`):
- `tcValuacion = pickFinancialRate(dolar, valuationDollar) || config.tc_mep || config.tc_blue || 1415`
- `pickFinancialRate` (`frontend/src/contexts/CurrencyContext.jsx:46`) usa `medio = (compra+venta)/2` con fallback a `.venta`, elige MEP o CCL según preferencia y cae al blue (`CurrencyContext.jsx:51-53`).
- `tcCedear = tcMep || tcValuacion` (`Positions.jsx:253`) — o sea el mismo número.
- `tcCripto = dolar?.cripto?.venta` (`Positions.jsx:257`).
- El comentario de `Positions.jsx:231-237` documenta un bug real: mientras `dolar` no llegaba, dos expresiones idénticas caían a fallbacks distintos y las filas se convertían con uno y el TOTAL con otro — 13,4% de diferencia en la misma tabla.

**Valuación por lote** — `valuePositionLot` (`frontend/src/utils/valuation.js:543`), **seis ramas en orden fijo** (documentado en `valuation.js:520-527`):

| # | Condición | Cómo valúa |
|---|---|---|
| 1 | cash | ARS → `invested / cedearRate`; USD → `invested` (`valuation.js:625-643` y `:678-681`) |
| 2 | `costInPesos(p) && !isAR` | lote en pesos en cuenta USD → costo Y valor por el MEP (`valuation.js:573-596`) |
| 3 | `costInUsd(p) && isAR` | lote de costo USD en broker ARS → **no** divide por MEP (`valuation.js:604-622`) |
| 4 | `isAR` nativo | precio `.BA` × qty ÷ `cedearRate` (`valuation.js:645-671`) |
| 5 | `(CEDEAR \|\| arUsd)` en broker USD, sin cripto/FCI/override | precio LOCAL `.BA` ÷ MEP (`valuation.js:689-712`) |
| 6 | resto | USD nativo × `cryptoBrokerFactor` (`valuation.js:714-735`) |

**Guard anti-distorsión** — `trustMktValue` (`valuation.js:448`): si el valor de mercado se va absurdamente lejos del costo (bono cotizado ×100, colisión de ticker), **no se confía en el precio y se muestra el costo con P&L 0**. Renta fija tiene banda estrecha; un override manual se respeta salvo en renta fija. El espejo server-side es `_trust_mkt_value` (`backend/snapshots_job.py:42`).

### 5.4 El número final: "valor de mi cartera"

**[V]** Cadena exacta:

```
heroValue = totals.value + pfValueUsd          Positions.jsx:1652
  totals.value = Σ_brokers computeBrokerValue(...).value    Positions.jsx:1587-1599
    computeBrokerValue = Σ_lotes valuePositionLot(p, ctx).valueUsd   valuation.js:740-768
  pfValueUsd = pfTotals.USD.valor + pfTotals.ARS.valor / tcValuacion  Positions.jsx:1649
```

- **[V]** Es un **número en USD**, calculado en el browser, sumando lote por lote.
- **[V]** `computeBrokerValue` (`valuation.js:740`) itera SOLO los lotes cuyo `p.broker === broker.name` — los brokers se recorren en `Positions.jsx:1590`.
- **[V]** Los plazos fijos entran al hero pero **no** al `computeBrokerValue`, y `Positions.jsx:1648` aclara que **no entran en la variación diaria** (los snapshots históricos no tienen PF). Confirmado también en `backend/main.py:37337`: los PF no están en el snapshot nocturno ni en el motor de valuación.
- **[V]** En display ARS el hero usa un cálculo **distinto**: `totalsToday` (siempre `costBasis='today'`, mode-independiente) × `tcValuacion` (`Positions.jsx:1607-1614` y `:1665-1666`). O sea que el número en pesos NO es el número en dólares × TC del modo elegido.
- **[V]** La suma de las **filas** de la tabla y el TOTAL del pie son dos cálculos distintos: las filas usan `calcUSDT`/`calcARS`/`calcRowUSDT` (`Positions.jsx:1281-1400`) y el pie usa `computeBrokerValue` sobre lotes crudos. El comentario de `Positions.jsx:1370-1380` documenta el bug reportado con captura: 10 filas sumaban USD 64.147,88 sobre un TOTAL de USD 56.582,51. La reconciliación (por-lote vía `p._lots`) está en `sumRowUSDT`/`sumRowARS` (`valuation.js:905` y `:925`).
- **[V]** La renta fija (bonos/letras/ONs/FCI) se excluye de las tarjetas por broker a propósito y vive en su propia zona; **el hero sí la suma** (`Positions.jsx:1655-1658`, flag `hasFixedIncome`).

---

## 6. Vender un activo

`POST /api/positions/sell` — `backend/main.py:11147`.

### Los pasos

1. **[V]** El front postea desde `Positions.jsx:888`.
2. **[V]** **Moneda de la venta** (`backend/main.py:11165-11169`): la explícita del usuario (`data.currency`), o la del broker por back-compat. Normalizada a `'ARS'|'USD'`. Es la que decide qué lotes se consumen.
3. **[V]** **Neteo cross-broker**: se buscan lotes del activo en AMBOS brokers del par padre↔`· USD` vía `broker_pair` (`backend/main.py:11177-11178`, def en `backend/importing/persister.py:99`). El comentario dice que para ventas manuales es casi no-op pero deja el modelo FIFO idéntico al del import/rebuild.
4. **[V]** **Orden FIFO** (`backend/main.py:11182-11188`): `ORDER BY COALESCE(entry_date,'9999-12-31') ASC, id ASC`. NULLs al final, desempate por id.
5. **[V]** **Bifurcación — FIFO por moneda** (`backend/main.py:11197-11199`): una venta en X consume SOLO lotes en X (`_native_ccy`, `backend/behavioral.py`). **Si no hay lotes de esa moneda**, cae a TODOS con conversión cross-currency (red de seguridad para data legacy con `currency` NULL). El comentario aclara que el spill cross-currency (dólar-MEP) es **exclusivo del rebuild de import**, no de la venta manual.
6. **[V]** Si la cantidad excede el total → 400 **atómico**, sin tocar nada (`backend/main.py:11202-11203`).

### El matcheo contra el costo

7. **[V]** Por cada lote (`backend/main.py:11219-11363`):
   - `ratio = take / pos_qty`; `base_invested = (invested + commissions_de_compra)` (`backend/main.py:11233-11238`). **Las comisiones de compra son parte del costo.**
   - **Bifurcación cross-currency** (`backend/main.py:11246-11254`):
     - lote USD vendido en ARS → `base_invested × (tc_venta o blue actual)`
     - lote ARS vendido en USD → `base_invested / blue_de_la_fecha_de_compra` (`blue_for_date`, `persister.py:45`)
   - Comisión de venta prorrateada por `take / data.quantity` (`backend/main.py:11259`).
8. **[V]** **Bifurcación de P&L, gateada por `sell_ccy` NO por la moneda del broker** (`backend/main.py:11278-11304`):
   - **ARS:** `pnl_ars = exit_price×take − entry_invested − comisión`; `pnl_usd = pnl_ars / tc_venta`. El `tc_venta` sale de `data.tc_venta`, o —si la cuenta es FX v2— de `fx_for_date(op_date)` (`backend/main.py:11288-11291`); en v1 cae a `1`.
   - **USD:** `pnl_usd = exit_price×take − cost − comisión`, `invested_usd = cost`.
   - El comentario de `backend/main.py:11262-11277` documenta el bug que esto arregla: con `currency` (la del broker) una venta USD sobre broker ARS dividía por el TC un P&L que ya estaba en dólares — error de ~1440× que además se veía plausible.

### Dónde queda el P&L realizado

9. **[V]** **Una fila en `operations` por cada lote consumido** (`backend/main.py:11312-11326`), con `op_type='Venta'`, `pnl_usd`, `pnl_pct`, `entry_date` del lote, `commissions` del chunk, `currency = sell_ccy` y `fx_to_usd = tc_venta` (NULL en ventas USD — estampar 1.0 haría que el front colapse el P&L en pesos 1:1, `backend/main.py:11306-11310`).
   - Ojo: la operación se estampa con **el broker del LOTE**, que en un par padre↔`· USD` puede no ser el broker de la venta.
10. **[V]** **Foto de reversa** en `operations.undo_meta_json` (`backend/main.py:11336-11363`): `{src:'fifo_sell', cash, cash_broker, pnl_usd, lot:{...}}`. Sin esta foto borrar la venta después sería imposible: la venta consume el lote y esa información no vive en ningún otro lado. Incluye el `undo_meta` **del propio lote** (`backend/main.py:11357-11361`) — sin eso, el lote re-creado nacía con `autodep=None` y borrarlo después fabricaba cash y aportado (medido: 200 y 200 de la nada).
11. **[V]** **Consumo del lote** (`backend/main.py:11366-11380`): total → `DELETE FROM positions`; parcial → `UPDATE` con `quantity`, `invested` e `commissions` prorrateados por `(1 − ratio)`.
12. **[V]** **Cash**: `_adjust_broker_cash(conn, uid, data.broker, total_proceeds_native)` (`backend/main.py:11384`) — al broker de la **venta**, no al del lote.
13. **[V]** **`monthly_entries`** (`backend/main.py:11388-11400`): dos escrituras — la del broker (en USD-equivalente; si el broker es ARS se divide por `tc_venta`) y la de `'global'` (siempre `total_pnl_usd`).
14. **[V]** `_repair_monthly_chain` para los dos (`backend/main.py:11402-11403`) y `_ai_cache_invalidate` (`backend/main.py:11403`).

### Qué NO se dispara

- **[V]** No corre el rebuild FIFO ni el recalc global — la venta manual actualiza `monthly_entries` incrementalmente.
- **[V]** No se tocan snapshots.

---

## 7. Un día de mercado

### 7.1 Qué corre el cron nocturno

**[V]** Registrado en `@app.on_event("startup")` — `backend/main.py:32525`. Son cinco jobs de APScheduler in-process:

| Job | Cron (UTC) | Línea |
|---|---|---|
| `daily_snapshot` | 02:59 (= 23:59 ART) | `backend/main.py:32534-32539` |
| `iol_lab_refresh` | cada hora, minuto 7 | `backend/main.py:32542-32547` |
| `subscription_lifecycle` | 03:30 | `backend/main.py:32551-32556` |
| `backup_db` | 03:45 | `backend/main.py:32560-32565` |
| `fci_refresh` | 12:10 (~09:10 ART) | `backend/main.py:32569-32574` |

**[V]** El horario del snapshot está justificado en `backend/main.py:32527-32533`: antes corría a 01:00 UTC (22:00 ART) y perdía 2 horas de movimientos del día argentino.

**[V]** Es un scheduler **in-process** (`BackgroundScheduler`, `backend/main.py:32095`). El comentario de `backend/main.py:17813` reconoce que APScheduler in-process no es confiable acá. Hay un endpoint manual de rescate: `POST /api/admin/snapshots/run-now` (`backend/main.py:34252`).

### 7.2 El snapshot

**[V]** `run_daily_snapshot` — `backend/snapshots_job.py:910`.

1. **[V]** Fetch del blue; si falla o es ≤0 → **aborta el job entero** (`snapshots_job.py:940-950`).
2. **[V]** Fetch del MEP; si se pasó `fetch_tc_mep` y no resuelve → **aborta, fail-closed** (`snapshots_job.py:956-966`). El motivo (comentario `snapshots_job.py:951-955`): con caché frío todos los holdings `.BA` se valuaban a `config.tc_mep` default 1415 → snapshot −15% en un día plano + "P&L Día +17%" fantasma a la mañana.
3. **[V]** `PRAGMA busy_timeout=5000` + WAL (`snapshots_job.py:971-972`).
4. **[V]** Persiste el blue del día en `fx_rates_daily` con UPSERT (`snapshots_job.py:981-993`).
5. **[V]** Selección de usuarios (`snapshots_job.py:999-1006`): excluye shadows revocados del plan asesor (sin vínculo activo y sin login), porque acumulaban un snapshot por noche para siempre.
6. **[V]** **Commit por-usuario, no una transacción global** (`snapshots_job.py:1012-1019`): el lock se toma solo para el write breve de cada uno.

**[V]** `take_snapshot_for_user` — `snapshots_job.py:623`:

7. **[V]** La fecha del snapshot es el **día ART** (UTC−3), no UTC (`snapshots_job.py:647-653`).
8. **[V]** Skip si no hay brokers o posiciones (`snapshots_job.py:673-677`).
9. **[V]** Símbolos con `build_price_symbols` (`snapshots_job.py:130`) → `fetch_prices_for_symbols` (`snapshots_job.py:407`) → **reintento** de los que quedaron sin precio (`snapshots_job.py:687-692`) → `apply_last_known_prices` (`snapshots_job.py:697`).
10. **[V]** **Guard de cobertura, ponderado por cost basis en USD** (`snapshots_job.py:717-740`): si `coverage < 0.95`, **NO se escribe el snapshot**. El motivo: las posiciones sin precio caen a cost basis y el total quedaría falsamente bajo, rompiendo la variación diaria del día siguiente.
11. **[V]** Valuación por broker con `compute_broker_value_usd` (`snapshots_job.py:158`), y **de nuevo posición por posición** para `by_asset` (`snapshots_job.py:750-755`) — dos pasadas sobre la misma función.
12. **[V]** `net_deposited` desde `monthly_entries` (`compute_net_deposited`, `snapshots_job.py:388`).
13. **[V]** **UPSERT en `snapshots`** (`snapshots_job.py:769-790`) con `source='cron'`, `base='mercado'`, `apto=1`. **El cron SÍ pisa una foto intradía del browser** (`snapshots_job.py:785-787`): su cierre es la medición buena del día.

### 7.3 El otro escritor de la serie

**[V]** `POST /api/snapshots` — `backend/main.py:5004`. Lo dispara el Dashboard al cargar, con los totales calculados **en el browser**.

- **[V]** **Un cierre del cron NO se pisa** (`backend/main.py:5044-5059`): si `source='cron'`, solo se actualizan `net_deposited` y `fx_to_usd_blue`. El comentario explica que antes se conservaba la marca pero se sobreescribía `total_value` con el número de media rueda, dejando una fila que decía "cierre medido" con un valor que no lo era.
- **[V]** Se escribe con `source='browser'`, `base='mercado'`, **`apto=0`** (`backend/main.py:5065-5067`): es de media rueda, nunca puede fijar un máximo ni ser denominador.
- **[V]** **El asesor NO escribe la serie del cliente** (`backend/main.py:5010-5016`): si viene el header `X-Rendi-Client-Id`, se acepta el request pero no se escribe.
- **[V]** No hace fetch sincrónico al dolarapi: si el cache está frío escribe `fx=NULL` (`backend/main.py:5024-5040`).

### 7.4 Cómo produce la variación diaria del día siguiente

**[V]** `Positions.jsx:1622-1645`:

```
lastClose = snapshots.find(s => s.date < today)     // vienen DESC
delta     = totals.value − lastClose.total_value
pct       = delta / lastClose.total_value
dayDiff   = (today − lastClose.date) en días
```

- **[V]** `totals.value` es el número **vivo** del browser (flujo 5); `lastClose.total_value` es el snapshot persistido.
- **[V]** El label se adapta: `dayDiff===1` → "Hoy" / "desde el cierre de ayer"; ≤7 → "N días"; >7 → "desde {fecha}" (`Positions.jsx:1632-1644`). Si el usuario no abrió la app en días, el copy dice la verdad en vez de mentir con "HOY".
- **[V]** **Los plazos fijos no entran** (`Positions.jsx:1646-1648`): `daily` usa `totals.value`, no `heroValue`.
- **[V]** Si el guard de cobertura del cron cortó anoche, no hay fila de ayer y `lastClose` cae al día anterior disponible → la "variación diaria" es de N días, no de 1.

**[V]** Aparte, la variación **por posición** viene de `GET /api/prices/prev-close` (`backend/main.py:7866`): toma el penúltimo cierre válido de yfinance, pero para `.BA` deriva el previo del `pct_change` de **data912** — la misma fuente que el precio actual. El comentario (`backend/main.py:7900-7906`) explica por qué: si el actual viene de data912 (DISN 13.840) y el previo de yfinance congelado (10.416), la variación explota +33% fantasma.

**[V]** Los lectores que **restan** entre puntas usan la vista `snapshots_medibles` (`backend/main.py:1459-1471`), que excluye `source='import'` y `source='browser'`, y deja pasar `mtm_backfill` solo con cobertura ≥ 0.90. Los que **muestran** un valor (el AUM del asesor) siguen leyendo `snapshots` directo.

---

## 8. Suscribirse a un plan

### 8.1 Checkout

1. **[V]** `POST /api/billing/subscribe` — `backend/main.py:26504`. Rate limit 5/600 s por usuario (`backend/main.py:26529`).
2. **[V]** **Bifurcación**: si ya hay una `subscriptions` con `status='authorized'` → **409** con `hint: "use_change_plan"` (`backend/main.py:26538-26551`). El cambio va por `POST /api/billing/change-plan` (`backend/main.py:26630`).
3. **[V]** `rebill.create_payment_link(...)` (`backend/main.py:26559-26564`). Si falla, se loggea completo y se devuelve 502 con el mensaje real truncado a 300 chars (`backend/main.py:26565-26582`).
4. **[V]** **Allowlist de dominios del link de pago** (`backend/main.py:26592-26605`): si la URL no arranca con `app.rebill.com` / `checkout.rebill.com` / `pay.rebill.com` / los sandbox `.dev`, se rechaza con 502. Defensa contra una respuesta comprometida que apuntara a un phishing.
5. **[V]** INSERT en `subscriptions` con `status='pending'`, guardando el **link id** en `mp_subscription_id` (`backend/main.py:26607-26614`). El campo se reusa; cuando llega el webhook se actualiza al subscription id real.
6. **[V]** Se devuelve `init_point` y el front redirige.

### 8.2 Webhook

7. **[V]** `POST /api/billing/rebill-webhook` — `backend/main.py:26809`.
8. **[V]** Auth con `verify_webhook_auth(raw, sig, url_token)` (`backend/main.py:26862`), que prueba HMAC (`REBILL_WEBHOOK_SECRET`) y, como fallback, un token en el query param (`REBILL_WEBHOOK_TOKEN`). Comportamiento declarado (`backend/main.py:26847-26856`): dev sin nada → permite con warning; **prod sin nada → reject (fail-closed)**.
9. **[V]** **El audit log se escribe SIEMPRE**, antes de validar (`backend/main.py:26868-26886`), para poder hacer replay manual de pagos legítimos que llegaron mientras la auth no estaba seteada. Recién después, si la auth falló, se devuelve 401 (`backend/main.py:26888-26894`).
10. **[V]** Matching del usuario: `metadata.rendi_user_id` (`backend/main.py:26841`). Sin él → 200 y skip (`backend/main.py:26896-26898`).
11. **[V]** **Routing por evento** (`backend/main.py:26913-26925`):
    - `subscription.created` → `_rebill_activate` (`backend/main.py:26963`)
    - `subscription.updated` → `_rebill_subscription_status_change`
    - `payment.created` / `payment.updated` → `_rebill_record_payment`
    - `subscription.renewal_soon` → no se actúa
12. **[V]** Cualquier excepción de procesamiento devuelve **200** para evitar retry agresivo (`backend/main.py:26932-26934`).

### 8.3 Tier actualizado

13. **[V]** `_rebill_activate` (`backend/main.py:26963`):
    - Normaliza `plan` y `period` **antes** de usarlos, para que metadata rara no rompa el ledger y deje el tier pago sin crédito (`backend/main.py:26970-26978`).
    - `UPDATE users SET tier=?, quota_window_from=date('now','localtime')` (`backend/main.py:27014-27015`).
    - **Bifurcación**: si existe una `subscriptions` pending, se la actualiza a `'authorized'`; si no (race: webhook antes del INSERT), se crea una (`backend/main.py:27019-27043`).
    - `credits.grant_payment_credit(...)` con `payment_id` como idempotency key (`backend/main.py:27047-27055`).
    - **Fallback si el ledger falla** (`backend/main.py:27056-27080`): el tier ya quedó en pago; sin `credit_active_until` ni el cron ni la red de seguridad de `get_tier` lo agarrarían → **Pro permanente**. Se setea un crédito fallback que **solo extiende, nunca acorta** — el `IS NULL` anterior no alcanzaba porque un usuario en free trial ya tiene `credit_active_until` y "pagaba un mes y recibía tres días".

### 8.4 Features desbloqueadas

14. **[V]** `GET /api/plan/features` — `backend/main.py:26439` → `ai.plan.get_plan_features`. Devuelve `tier`, `limits.brokers_max/brokers_current/brokers_can_create`, `access.<feature_id>` y `client_ctx`.
15. **[V]** **La resolución real del tier** es `quota.get_tier` (`backend/ai/quota.py:148`), con esta precedencia:
    1. Cuenta **administrada sin reclamar** (`managed_by` no NULL **y** `approved=0`) → `'pro'` (`quota.py:186-188`).
    2. `pro_trial_until` en el futuro → `'pro'`, por encima del override pago y sin tocarlo (`quota.py:199-204`).
    3. `users.tier` override, **pero** si es pago y el crédito venció sin sub que renueve → se trata como expirado (`quota.py:152-157`, `:206-208`).
    4. `is_admin` → `'admin'`.
    5. fallback → `'free'`.
16. **[V]** **Lente Pro del asesor** (`backend/main.py:26459-26463`): si hay contexto de cliente (uid ≠ auth_uid), las features se calculan sobre la cuenta del cliente pero con `tier_override='pro'`.
17. **[V]** Gates concretos que consumen esto: creación de brokers (`backend/main.py:4060`), follow-ups de IA solo Pro (`backend/main.py:25947-25963`), cuota de análisis (`backend/main.py:26018-26043`), cuota de chat (`backend/main.py:28322`).
18. **[V]** El bajón a Free lo hace el job `subscription_lifecycle` a las 03:30 UTC (`backend/main.py:32551-32556`).

### Rareza

- **[V]** Convive un webhook de Mercado Pago muerto (`POST /api/billing/webhook`, `backend/main.py:27501`) con el de Rebill. El comentario de `backend/main.py:26525-26526` dice que MP queda muerto "por si hay que revertir".

---

## 9. Pedirle un análisis a la IA

### Los pasos

1. **[V]** Click en "Analizar" → `useAIAnalysis` (`frontend/src/hooks/useAIAnalysis.js:25`) hace `api.post('/ai/analyze', { screen, params })` (`useAIAnalysis.js:45`).
2. **[V]** `POST /api/ai/analyze` — `backend/main.py:25890`. Rate limit 10/60 s por uid+IP (`backend/main.py:25914`).
3. **[V]** Si no hay `ANTHROPIC_API_KEY` → 503 (`backend/main.py:25918-25919`).
4. **[V]** **Dispatch por registry** (`backend/main.py:25926-25933`): `screen` (notación con puntos, ej. `dashboard.composition`) → `(build_packet, render_prompt)` desde `REGISTRY` (`backend/ai/registry.py:63`). Hay ~40 topics con su builder en `backend/ai/builders/`.
5. **[V]** **Resolución de tier** (`backend/main.py:25939`) + **lente del asesor** (`backend/main.py:25944-25948`): si uid ≠ auth_uid, el tier del cliente es free/plus y el auth es `advisor` → se fuerza `'pro'`. Los contadores siguen corriendo en la cuenta del cliente.
6. **[V]** **Gate de follow-ups** (`backend/main.py:25955-25976`): free Y plus reciben 403 con payload de upgrade.
7. **[V]** **El packet se arma PRIMERO**, antes de tocar el cupo, porque es barato y determinístico (`backend/main.py:25978-25984`). Ejemplo de builder: `backend/ai/builders/dashboard.py:76` — carga positions, brokers, monthly `global` y **`snapshots_medibles`** (no `snapshots`: el comentario de `builders/dashboard.py:99-104` explica que la query cruda era estructuralmente ciega a la base de cada punta y publicó `twr_30d_pct = -47,26%` con la pantalla en "—").
8. **[V]** Se enriquece con el **perfil del inversor** dentro del packet, no en el system prompt, para que el cache key incluya el perfil (`backend/main.py:25986-26000`).

### Cache

9. **[V]** `cache.get_cached` (`backend/ai/cache.py:75`), solo para análisis principales — los follow-ups **nunca** se cachean (`backend/main.py:26003-26013`).
10. **[V]** Claves (`backend/ai/cache.py:59-72`):
    - `packet_hash = sha256(json.dumps(packet, sort_keys=True))`
    - `cache_key = sha256(f"{user_id}:{screen}:{tier}:{packet_hash}")`
    - O sea: **si cambia cualquier número del packet, cambia la clave** → invalidación implícita.
11. **[V]** TTL por tier (`backend/ai/cache.py:44-56`): Free más largo que Pro, para reducir costo.
12. **[V]** Invalidación explícita: `_ai_cache_invalidate(uid)` (`backend/main.py:25863`) llamado desde cada endpoint de mutación.
13. **[V]** Un cache hit **no descuenta cupo** (`backend/main.py:25902-25905` y la posición del `can_analyze` en `:26016`).

### LLM y render

14. **[V]** Cache miss (o follow-up) → `quota.can_analyze` (`backend/main.py:26016`). Si no alcanza, 429 con mensaje dinámico por tier y payload de upgrade (`backend/main.py:26018-26043`).
15. **[V]** `system_prompt = render_prompt(tier=tier)` (`backend/main.py:26048`) y `llm.analyze(...)` con `MODEL_HAIKU`, `output_model=AnalysisResult` y `descriptive=is_descriptive_tier(tier)` (`backend/main.py:26050-26060`). Free/Plus reciben prompt **descriptivo** (describir, no interpretar).
16. **[V]** Errores del LLM → 502 (`backend/main.py:26061-26063`); `None` → 503 (`backend/main.py:26065-26066`).
17. **[V]** `cache.set_cached(...)` con tokens y costo (`backend/main.py:26070-26085`) y `quota.record_analysis(...)` (`backend/main.py:26087`).
18. **[V]** El hook guarda `result`, `cached`, `usage`, `tier` y emite `ai_analyze_loaded` con la latencia (`useAIAnalysis.js:46-52`). Cap de **1 follow-up por análisis** (`useAIAnalysis.js:23`).

### El chat, que es otro camino

- **[V]** `POST /api/ai/chat` — `backend/main.py:28264`. Rate limit 12/60 s (`backend/main.py:28296`). Free/Plus: solo preguntas de una whitelist de 12, cuota 6/semana, `max_tokens=300`. Pro/Admin: texto libre, 60/semana, `max_tokens=1000`, tools habilitadas (`backend/main.py:28268-28277`).
- **[V]** Misma lente del asesor (`backend/main.py:28305-28313`).
- **[V]** El prompt-cache está partido a propósito: `system_text` = solo manifiesto estable por tier (cache hit ~99%); snapshot + facts + perfil van en el primer mensaje de usuario con `cache_control` (`backend/main.py:28279-28284`).
- **[V]** La reserva **real** del slot de cuota es atómica y va justo antes del LLM, no al principio: el review encontró que reservar temprano dejaba ~130 líneas de ventana donde una excepción cobraba el slot sin dar respuesta (`backend/main.py:28315-28320`).
- **[V]** Un turno de continuación de un registro en curso (`_trade_flow_open`) **no** lo bloquea el cap (`backend/main.py:28321-28327`).

---

## 10. Un asesor da de alta a un cliente y mira su cartera

### 10.1 Los tres caminos de alta

**Camino A — cliente MANAGED (ficha shadow)**

1. **[V]** `POST /api/advisor/clients` — `backend/main.py:34370`. Usa `get_current_user` (identidad real, sin lente).
2. **[V]** `_require_advisor(conn, uid)` (`backend/main.py:34382`, def `backend/main.py:2823`): exige tier `'advisor'` de verdad — **`is_admin` NO alcanza**.
3. **[V]** Cap duro `ADVISOR_MAX_CLIENTS = 500` (`backend/main.py:34347`, chequeado en `:34386-34390`). Motivo declarado: una cuenta advisor comprometida podría inflar `users` sin límite y los `IN(...)` del roster reventarían el tope de variables de SQLite.
4. **[V]** Se crea un usuario **shadow**: email sintético `cliente.<hex>@shadow.rendi.internal` (`backend/main.py:34346`, `:34391`), password random hasheada (nadie puede loguear), `approved=0`, `email_verified=0`, `managed_by=<advisor_uid>` (`backend/main.py:34395-34401`).
5. **[V]** Vínculo en `advisor_clients` con `link_type='managed'`, `permission='read_write'`, `status='active'` y `consent_ref` con timestamp (`backend/main.py:34403-34408`).
6. **[V]** Ese shadow resuelve tier `'pro'` vía `quota.get_tier` (`backend/ai/quota.py:186-188`) **mientras no esté reclamado**.

**Camino B — invitación → claim (el cliente reclama la ficha)**

7. **[V]** `POST /api/advisor/clients/{client_uid}/invite` — `backend/main.py:34690`. Rate limit 10/300 s (`backend/main.py:34696`), `_require_advisor` + `_advisor_own_link` (`backend/main.py:34700-34701`, def `:34566`).
8. **[V]** Si el cliente ya está `approved` → 400 (`backend/main.py:34706-34707`).
9. **[V]** **Bifurcación crítica** (`backend/main.py:34715-34721`): si el email pertenece a **otra cuenta existente**, no se invita — se deriva a `_advisor_link_request` (camino C).
10. **[V]** Tope diario por cliente: 8 invitaciones (`backend/main.py:34728-34736`). Es además del rate limit por asesor.
11. **[V]** Se genera token con TTL `ADVISOR_CLAIM_TTL_DAYS`; **un solo link vivo por cliente** — los previos se marcan `used_at` (`backend/main.py:34740-34745`) y se cancelan los pedidos de acceso pendientes salidos de esa ficha (`backend/main.py:34746-34755`).
12. **[V]** El envío del mail **es** la operación: si Resend está configurado y no se pudo mandar → 502 (`backend/main.py:34761-34772`).
13. **[V]** `POST /api/auth/claim` — `backend/main.py:35106`. Valida token/expiración, re-chequea colisión de email (`backend/main.py:35127-35132`), y **cierra el token PRIMERO** con `WHERE used_at IS NULL` + chequeo de `rowcount==1` (`backend/main.py:35141-35146`) para que dos claims concurrentes no pisen la contraseña.
14. **[V]** `UPDATE users SET email, password_hash, approved=1, email_verified=1, password_changed_at, managed_by=NULL` (`backend/main.py:35156-35160`). El `managed_by=NULL` es deliberado: sin él, `delete_my_account` trataría la cuenta ya independiente como shadow y la borraría en cascada si el asesor cierra su cuenta (bug real, hallado en el review de F4a — `backend/main.py:35148-35155`).
15. **[V]** El vínculo sigue vivo en `advisor_clients`. Pero la cuenta pasa a resolver tier real → normalmente `'free'` (`quota.py:174-185`).

**Camino C — pedido de acceso a una cuenta que ya existe**

16. **[V]** `_advisor_link_request` — `backend/main.py:34785`. Se llega desde `invite` cuando el email choca.
17. **[V]** Rechazos duros: es el propio email del asesor (`backend/main.py:34793-34794`); la cuenta no puede consentir (shadow de otro asesor o todavía administrada, `backend/main.py:34798-34799`); ya hay vínculo activo (`backend/main.py:34800-34805`).
18. **[V]** **Dos pasos a propósito** (`backend/main.py:34811-34823`): el primer POST devuelve **409 `existing_account`** contando qué implica (incluido cuántas posiciones tiene la ficha que se va a archivar); recién el segundo, con `mode='link_request'`, manda el pedido. Sin ese paso el asesor mandaría mails a terceros sin enterarse de que cambió el trato.
19. **[V]** Cooldown si ya rechazó (`ADVISOR_LINK_REJECT_COOLDOWN_DAYS`, `backend/main.py:34825-34833`) y tope diario por (asesor, cuenta) (`backend/main.py:34835-34843`).
20. **[V]** Un solo pedido vivo por par; reenviar cancela el anterior (`backend/main.py:34857-34862`).
21. **[V]** `POST /api/auth/link-request/respond` (`backend/main.py:35034`) → `_apply_link_request` (`backend/main.py:34898`):
    - Estado ≠ pending → 400 (`backend/main.py:34903-34904`).
    - **Se re-verifica que la ficha siga siendo ficha** (`backend/main.py:34911-34914`): `shadow_uid` quedó congelado hasta 14 días; si en el medio alguien la reclamó, archivarla le sacaría el asesor a un tercero.
    - **El cap del plan se chequea al ACEPTAR, no al pedir** (`backend/main.py:34921-34929`).
    - Cierre con `UPDATE ... WHERE status='pending'` + `rowcount != 1` → 400 (`backend/main.py:34931-34939`): dos clicks simultáneos, gana el primero.
    - Al aceptar: nace el vínculo `link_type='linked'` sobre la cuenta REAL con `ON CONFLICT DO UPDATE` (`backend/main.py:34946-34965`) y la ficha managed se **revoca** (`backend/main.py:34966-34973`) para que la persona no cuente dos veces en el AUM.

### 10.2 Mirar la cartera: el chequeo de permisos en cada request

22. **[V]** El asesor entra al cliente → `enterClient({id, label})` (`frontend/src/contexts/AdvisorContext.jsx:38`) → `setClientContext` guarda en memoria **y en localStorage** (`frontend/src/utils/api.js:43-50`).
23. **[V]** **Cada** request de datos lleva `X-Rendi-Client-Id` (`frontend/src/utils/api.js:104` para JSON, `:227` para uploads, `:264` para blobs, `:303` para el chat).
24. **[V]** Sync multi-pestaña por evento `storage` (`frontend/src/utils/api.js:57-67`): sin esto, una pestaña vieja seguía mandando el header de un cliente ajeno tras logout+login de otro usuario.
25. **[V]** Backend: `get_effective_user` (`backend/main.py:2806`) → `_resolve_client_context` (`backend/main.py:2767`). El chequeo, en orden:

| Orden | Chequeo | Línea | Resultado |
|---|---|---|---|
| 1 | ¿hay header? | `backend/main.py:2772-2774` | no → uid propio |
| 2 | ¿el path está en un prefijo EXENTO? | `backend/main.py:2778-2779` | sí → **se ignora el header** |
| 3 | ¿parsea a int? | `backend/main.py:2780-2783` | no → 400 |
| 4 | ¿está en rango INTEGER de SQLite? | `backend/main.py:2784-2786` | no → 400 (evitaba OverflowError → 500) |
| 5 | ¿es el propio uid? | `backend/main.py:2787-2788` | sí → no-op |
| 6 | `SELECT permission FROM advisor_clients WHERE advisor_uid=? AND client_uid=? AND status='active'` | `backend/main.py:2791-2795` | sin fila → **403 explícito, nunca fallback silencioso** |
| 7 | método ≠ GET/HEAD/OPTIONS y `permission != 'read_write'` | `backend/main.py:2801-2802` | → 403 |

26. **[V]** Prefijos exentos (`backend/main.py:2749-2758`): `/api/auth`, `/api/billing`, `/api/admin`, `/api/advisor`, `/api/me`, `/api/push`, `/api/plan/track`, `/api/feedback`. El match es **por límite de segmento** (`path == p or path.startswith(p + "/")`) para que un futuro `/api/metrics` no quede eximido en silencio por un `startswith` crudo.
27. **[V]** El propio código declara el riesgo: **"⚠️ FAIL-OPEN: todo endpoint futuro FUERA de estos prefijos hereda el contexto de cliente"** (`backend/main.py:2763-2764`).
28. **[V]** Excepción a la lectura: `POST /api/snapshots` acepta el request pero **no escribe** si viene el header (`backend/main.py:5010-5016`) — la serie es la medición del cliente, no la del que observa.
29. **[V]** Endpoints de gestión (`/api/advisor/*`, `/api/me/advisor/*`) usan `get_current_user`, o sea identidad real (`backend/main.py:34372`, `:34419`, `:35176`).

### Rareza

- **[V]** El comentario de `frontend/src/utils/api.js:22-25` dice que el backend "IGNORA el header en los prefijos exentos (auth/billing/**ai**/push/advisor)". El backend **no** exime `/api/ai` — está explícitamente fuera de la lista y el comentario de `backend/main.py:2759-2762` dice que es a propósito ("la IA sigue al contexto"). El comentario del front contradice al backend.

---

## 11. Borrar algo

Hay **seis** caminos distintos de borrado. Los separo.

### 11.1 Una operación (venta)

**[V]** `DELETE /api/operations/{oid}` — `backend/main.py:14721` → `_delete_operation_cascade` (`backend/main.py:14446`).

**Bifurcación de entrada** (`backend/main.py:14470-14477`): si no hay fila en `import_op_links`, es una operación **manual** → se desvía a `_delete_manual_operation_cascade` (`backend/main.py:13976`), que se reversa desde su propia foto `undo_meta_json`, no desde el rebuild.

Para las importadas, **bloqueos** (todos con mensaje al usuario):

| Condición | Línea |
|---|---|
| No es SELL | `backend/main.py:14489-14493` |
| `asset_type == 'BOND'` | `backend/main.py:14494-14498` |
| El activo tiene ops manuales mezcladas (`_is_safe_to_rebuild`) | `backend/main.py:14518-14522` |
| El activo tiene Cupón/Amortización/Renta (renta fija sin catalogar) | `backend/main.py:14528-14538` |

**Excepción explícita** (`backend/main.py:14505-14515`): una venta sintética `transfer_out` (cierre emitido por una foto) **sí** se puede borrar, y es el borrado más seguro que hay — el persister no acreditó cash ni P&L. Antes se bloqueaba y era un callejón sin salida: la foto se equivocaba, el usuario veía una posición viva cerrada, y ni el tacho del activo ni el revert del batch la recreaban.

**La cascada, en orden crítico** (documentado en `backend/main.py:14456-14461`):

1. **[V]** **Claim atómico**: el tombstone (`excluded_at`) es el PRIMER paso y sirve de **lock** — dos requests concurrentes no pueden reversar el cash dos veces (la segunda matchea 0 filas → 409) (`backend/main.py:14542-14550`).
2. **[V]** **Reversa del cash** (`backend/main.py:14552-14574`): espeja la fórmula EXACTA del persister — `reconciled_unit_price × qty − fees`, y **solo si es > 0**. No `gross_amount − fees`: el bruto difiere de precio×cantidad por redondeo y comisión embebida. Con `transfer_out` la reversa es 0 explícitamente.
3. **[V]** Se borra el `import_op_links` y se escribe el `deleted_ops_journal` con el monto exacto revertido, para que el undo sea simétrico (`backend/main.py:14576-14591`).
4. **[V]** `rebuild_pair_asset(conn, uid, broker, asset)` (`backend/main.py:14595`) — re-deriva el FIFO desde los eventos que sobreviven: restaura la tenencia y borra la venta.
5. **[V]** `_cascade_after_movement_delete` (`backend/main.py:14598`).

**[V]** Reversible: `POST /api/operations/undo/{token}` (`backend/main.py:14743`).

### 11.2 `_cascade_after_movement_delete` — la cola compartida

**[V]** `backend/main.py:12883`. Es el corazón de lo que se recomputa. Orden:

1. `_repair_monthly_chain` por broker tocado + global (`backend/main.py:12921-12924`).
2. `_recalc_pnl_realized_from_ops` (`backend/main.py:12925`) — recompone `monthly_entries` desde las fuentes.
3. **Snapshots — y acá está la parte fina** (`backend/main.py:12927-12951`):
   - **Solo se borran las SINTÉTICAS**: `fx_to_usd_blue IS NULL` **Y** `holdings_json` vacío **Y** `date` es fin de mes (`backend/main.py:12929-12935`). Las tres condiciones juntas.
   - El comentario (`backend/main.py:12899-12920`) documenta el bug corregido: antes purgaba TODO desde `since_date`, y como `total_value` de una foto del cron es una **medición** irrepetible, el backfill la reescribía al costo → **borrar un dividendo de hace 3 años aplanaba la curva, el CAGR y el AUM del asesor para siempre**. También explica por qué no alcanza con "sin blue ni holdings": `POST /api/snapshots` guarda `fx=NULL` con caché frío y nunca escribe holdings, así que una medición real caía en esa red.
   - A las **reales** solo se les recomputa `net_deposited`, agrupando **por mes** y no por foto (`backend/main.py:12937-12951`): con 3 años de historia son ~36 UPDATEs en vez de ~1100, y el borrado no retiene el lock recorriendo foto a foto.
4. **El snapshot de HOY se borra siempre** (`backend/main.py:12952`) — lo reescribe la próxima visita o el cron.
5. `_backfill_snapshots_from_monthly` (`backend/main.py:12953`).

### 11.3 Un lote abierto (compra)

**[V]** `_delete_position_cascade` — `backend/main.py:14599`. Espeja el anterior sobre el evento BUY.

Bloqueos adicionales:
- Solo compras **importadas** (`backend/main.py:14616-14619`).
- No bonos (`backend/main.py:14629-14632`).
- **Lote semilla de una foto** (`_is_synthetic_seed_row`, `backend/main.py:12866`): lo fondea un depósito sintético COMPARTIDO que este borrado no sabe reversar → devolvía cash inventado (`backend/main.py:14636-14637`). El comentario aclara que la guarda existía en el borrado por-activo y **faltaba acá** — misma puerta, distinto camino.
- `transfer_out` (`backend/main.py:14638-14640`).
- **Compra parcialmente vendida** (`backend/main.py:14645-14648`): borrar el BUY dejaría la venta huérfana con costo fabricado.

**[V]** Reversa de cash: `invested + fees`, con `invested = gross_amount` o `reconciled × qty` si es NULL (`backend/main.py:14680-14688`). El journal guarda el **negado** (`backend/main.py:14697-14700`), porque el delete DEVOLVIÓ plata y el undo debe RE-DEBITAR — convención opuesta a la de la venta.

### 11.4 Un movimiento genérico

**[V]** `DELETE /api/movements/{movement_id}` — `backend/main.py:13130`. Router por prefijo del id compuesto (`backend/main.py:13147-13168`):

| Prefijo | Va a |
|---|---|
| `op-{n}` | `_delete_operation_cascade` |
| `pos-{n}` | `_delete_position_cascade` |
| `tx-{n}` | `_route_tx_delete` (`backend/main.py:13091`) (cash-flow → reverso clásico; compra/venta → cascada FIFO) |
| resto (`me-`) | `_delete_one_movement` + `_cascade_after_movement_delete` |

**[V]** Todo dentro de `with conn:` y bajo `_run_with_lock_retry` (`backend/main.py:13170`). El `undo_token` se propaga al front (`backend/main.py:13141-13143`) — antes se tiraba y el "podés deshacerlo" del confirm era mentira.

### 11.5 Todo el historial de un activo

**[V]** `DELETE /api/assets/history?asset=X` — `backend/main.py:15019` → `_delete_asset_history_cascade` (`backend/main.py:14819`). Borra compras, ventas, cupones, amortizaciones y dividendos **de todos los brokers**. Soporta bonos (a diferencia del borrado por operación) y bloquea foto de tenencia y data manual mezclada. Reversible: `POST /api/assets/undo/{token}` (`backend/main.py:15040`), que además verifica que **el broker siga existiendo** antes de devolver el cash — si no, crearía una posición fantasma bajo un broker inexistente (`backend/main.py:15065-15069`).

### 11.6 Un broker

**[V]** `DELETE /api/brokers/{bid}?force=` — `backend/main.py:4337`.

1. **[V]** Broker inexistente → `{"ok": true, "no_change": true}` (idempotente, `backend/main.py:4370`).
2. **[V]** **Se buscan TODOS los siblings** con `fetchall`, no `fetchone` (`backend/main.py:4382-4385`): `POST /api/brokers` acepta un `parent_broker_id` arbitrario, así que un padre puede tener más de un hijo y con `fetchone` quedaban huérfanas las filas del segundo en adelante.
3. **[V]** **Guard de confirmación**: se cuentan `positions`, `operations`, `monthly_entries`, `import_batches` sobre padre + siblings, y sin `?force=true` se devuelve **409** con el resumen (`backend/main.py:4392-4432`).
4. **[V]** Se calcula la ventana afectada (`MIN(date)` de operations, fallback al primer `monthly_entries`) **antes** de borrar (`backend/main.py:4436-4450`).
5. **[V]** Cascada (`backend/main.py:4453-4499`):
   - `DELETE FROM operations / positions / monthly_entries WHERE broker IN (padre, siblings...)`.
   - `UPDATE import_batches SET status='reverted'` — **no** delete físico, para auditoría.
   - `DELETE FROM brokers WHERE parent_broker_id=?` **explícito**, antes del padre. El comentario (`backend/main.py:4479-4494`) explica que el FK CASCADE solo existe en bases creadas de cero: la migración lo agrega por `ALTER TABLE ADD COLUMN` y SQLite no admite acción referencial ahí → **toda base preexistente, o sea producción, tiene la FK sin cascade**, y el DELETE del padre tiraba `FOREIGN KEY constraint failed`, dejando la cuenta indeleteable con un 500 genérico.
6. **[V]** `_recalc_pnl_realized_from_ops` (`backend/main.py:4502-4506`).
7. **[V]** **Purga de snapshots** (`backend/main.py:4508-4528`): borra desde `snap_affected_start` (diarios intermedios incluidos) y re-backfillea los month-ends. Si no se pudo acotar la ventana (broker solo con posiciones manuales) → **purga TOTAL** de los snapshots del usuario.
   - El comentario dice que `delete_broker` era el único de los tres flujos (vs wipe/revert) que NO reproyectaba, y el chart de Evolución mostraba plata fantasma indefinidamente.
   - ⚠ Ojo: acá la purga **sí** borra mediciones reales del cron, a diferencia de `_cascade_after_movement_delete` (11.2), que las conserva explícitamente. Los dos criterios conviven en el mismo repo.

### 11.7 Revertir un batch entero

**[V]** `POST /api/imports/{batch_id}/revert` — `backend/main.py:31890` → `revert_batch` (`backend/importing/persister.py:1323`).

- **[V]** Solo batches en estado `'confirmed'` (`persister.py:1345-1346`).
- **[V]** **Bifurcación safe/nuclear** (`persister.py:1350-1370`): en modo safe, un batch con SELL/FX/FUTURES_PNL se **bloquea** con mensaje explicando que las ventas consumieron lotes con FIFO. `?nuclear=1` hace best-effort aceptando drift.
- **[V]** Pre-check 2 (solo en safe): si una posición creada por el batch ya no existe o tiene menos cantidad, se bloquea (`persister.py:1379-1400`).
- **[V]** Si el batch fijaba `price_override` en FCI, se limpian y se **re-aplican las fotos que sigan confirmadas** (`backend/main.py:31911-31921`).

### Qué queda huérfano

| Huérfano | Evidencia |
|---|---|
| `import_normalized_tx` tras borrar un broker | **[V]** El comentario de `backend/main.py:4123-4125` lo dice literal: *"delete_broker limpia positions/operations/monthly_entries/import_batches pero NO toca import_normalized_tx ni bond_cashflow_skips (orphan gap conocido)"*. En el **rename** sí se incluyen (`NAME_KEYED_TABLES`, `backend/main.py:4126-4133`) |
| `bond_cashflow_skips` tras borrar un broker | misma línea |
| `import_batches` tras borrar un broker | **[V]** Quedan en `status='reverted'` sin borrado físico (`backend/main.py:4468-4475`) — es a propósito, para auditoría |
| `import_raw_rows` en general | **[I]** No encontré ningún DELETE de `import_raw_rows` fuera de `cleanup_stale_previews` (`pipeline.py:190`), que solo toca previews vencidos. Me agarro de que ni `delete_broker` ni `_delete_operation_cascade` ni `revert_batch` lo mencionan |
| Snapshots del cron tras borrar un broker | **[V]** Se **borran** (`backend/main.py:4514-4525`), a diferencia de `_cascade_after_movement_delete` que los preserva. Son mediciones no re-derivables |
| Filas salteadas en el confirm | **[V]** Se borran de `import_normalized_tx` a propósito (`backend/main.py:30783-30795`), pero **quedan** en `import_raw_rows` con su `status`/`errors_json` |

**[V]** El modelo de datos es la causa raíz de la mayoría: brokers linkeados por **NOMBRE** (columna `broker TEXT`), no por FK a `brokers.id`, en al menos seis tablas (`backend/main.py:4113-4133`). Por eso un rename tiene que reescribir el nombre en cascada — el bug reportado fue que renombrar "Cocos Capital" hacía desaparecer todas las posiciones.

---

## Anexo: contradicciones y rarezas que crucé al trazar

1. **[V]** `frontend/src/utils/api.js:25` afirma que `/api/ai` está exento del contexto de cliente. `backend/main.py:2749-2762` dice explícitamente lo contrario, y que es a propósito.
2. **[V]** `frontend/src/pages/Onboarding.jsx:11-12` dice que el onboarding se dispara "si el user no tiene brokers cargados". El código (`VerifyEmail.jsx:143-144`) solo mira dos flags de localStorage.
3. **[V]** `VerifyEmail.jsx:135-140` lee `data.user_id`, `data.id`, `data.is_admin` y `data.email` de una respuesta que solo devuelve `{token, name, verified}` (`backend/main.py:3325-3329`).
4. **[V]** Dos criterios opuestos para purgar snapshots ante un borrado: `_cascade_after_movement_delete` conserva las mediciones del cron (`backend/main.py:12899-12920`) y `delete_broker` las borra, incluso con purga total como fallback (`backend/main.py:4514-4525`).
5. **[V]** El hero en USD y el hero en ARS de Cartera salen de **dos cálculos distintos** (`Positions.jsx:1587-1614`): el de pesos ignora el toggle de cost basis por diseño, así que USD×TC ≠ ARS.
6. **[V]** Los brokers se crean en el **preview** del import (`pipeline.py:625-635`), no en el confirm. Un preview abandonado deja brokers creados.
7. **[V]** El `run_preview` puede **cambiar el parser elegido por el usuario** en silencio si el suyo no matchea (`pipeline.py:492-505`).
8. **[V]** El seed de import se dolariza a propósito con el TC de HOY y no el de su fecha (`persister.py:189-210`), al revés que todo el resto del pipeline — y está bien fundado, pero es la única fila del sistema con esa regla.
9. **[V]** El comentario de `backend/main.py:30084-30105` reconoce una asimetría **abierta** en la reconciliación de fotos: `not_in_snapshot` y `to_seed` se corrigen cross-partición, `over` no. Y `over` es el único balde que puede reducir una tenencia.
10. **[V]** El scheduler es in-process (`backend/main.py:32095`) y el propio código lo declara poco confiable (`backend/main.py:17813`). Los snapshots dependen de que el proceso de Railway esté vivo a las 02:59 UTC.
11. **[V]** `_reconstruir_mtm_post_import` lanza un **thread daemon** (`backend/main.py:30726-30728`) que escribe snapshots después de que el request terminó, sin ningún mecanismo de reporte hacia el usuario más allá de `{"reconstruida": "en_curso"}`.
