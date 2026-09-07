## Tipo de cambio (blue, MEP, CCL, cripto) y conversión de moneda

### Definición según el código

En Rendi **el dólar no es uno solo: son cuatro rieles, dos ejes de decisión y dos épocas**.

**Los cuatro rieles** salen todos de la misma API pública (`dolarapi.com`), una casa por endpoint [V]: `blue`, `bolsa` (que el código llama MEP — el comentario dice literalmente que `/v1/dolares/mep` devuelve 404), `contadoconliqui` (CCL) y `cripto` (`backend/main.py:4852-4855`, `backend/main.py:32027-32029`).

**La tasa de una casa no es su punta de venta, es el punto medio** `(compra+venta)/2`, estampado como `medio` (`backend/main.py:4623`) y leído por `_val_rate` con caída a `venta` (`backend/main.py:4630-4644`). Es una definición NO estándar y deliberada: el docstring dice que es "el dólar de VALUACIÓN … porque es lo que muestra el broker (Cocos/IOL/Balanz valúan al medio, no a la punta de compra)" (`backend/main.py:4616-4622`). El test que lo fija cuenta el caso real: US$ 6.884 en Rendi contra US$ 6.933 en Cocos, 0,71 % parejo en todo el total (`backend/tests/test_dolar_medio.py:1-13`). **Excepción declarada: la cripto NO pasó al medio** y sigue leyéndose de `venta` (`backend/main.py:4964-4970`), con la justificación de que su premium es el *ratio* cripto/MEP y el frontend lee `dolar.cripto.venta` crudo. **Segunda excepción, esta sin justificar: `_display_blue` también lee `venta`** (`backend/main.py:4896`).

**Los dos ejes de decisión del usuario** viven en el frontend, en `localStorage`, per-device, y NO viajan al backend (`frontend/src/contexts/CurrencyContext.jsx:24-27`):
- `currency` ∈ {USD, ARS} — en qué moneda se MUESTRA todo. Default USD.
- `valuationDollar` ∈ {mep, ccl} — con qué dólar se VALÚA. Default `mep`.
- (un tercero, `costBasis` ∈ {purchase, today}, decide con qué dólar se cuenta el COSTO de un lote en pesos; default `purchase`.)

La función canónica que los resuelve en una tasa es `pickFinancialRate(dolar, pref)`: **el elegido, el otro financiero como red, y el blue solo como último recurso** (`frontend/src/contexts/CurrencyContext.jsx:46-54`). El comentario es explícito: la variable "se llamaba `tcBlue` sin contener el blue" y hoy se llama `tcValuacion` (`frontend/src/contexts/CurrencyContext.jsx:6-11`).

**Las dos épocas** son la regla de negocio más importante del concepto. Existe un versionado POR CUENTA, `config.fx_version` ∈ {v1, v2} (`backend/fx.py:126-168`):
- **v1** — el motor dolariza con "el dólar VIVO del momento en que se corre el import". Las cuentas con historia previa quedan grandfathered acá.
- **v2** — el motor dolariza con `fx_for_date`: **el TC de la FECHA del hecho**, cadena `MEP de la fecha → blue de la fecha → fallback explícito del caller`, y **nunca** el dólar de hoy (`backend/fx.py:76-107`). Las cuentas nuevas nacen v2.

El docstring de `backend/fx.py:1-41` explica por qué la estrictez es el punto: el replay tiene que ser determinístico (mismo input, mismo output) para poder reparar el histórico replayando en vez de escribiendo números que el próximo rebuild pisa. Y documenta la medición que lo motivó: 51.475 ventas de 503 usuarios con el TC equivocado, un usuario con 370 ventas de diez años estampadas todas con el mismo 1415,00, y 80.868 de 84.123 flujos en pesos (96 %) al mismo 1415 desde 2013.

**La regla de valuación en una línea** (tal como la implementa el código, no como la enunciaría un manual):

| qué | a qué dólar | dónde |
|---|---|---|
| holdings `.BA` (CEDEAR / acción AR / bono AR) | `pickFinancialRate` = MEP o CCL según preferencia | `frontend/src/utils/valuation.js:545` |
| cash en pesos | **el MISMO** `cedearRate` (MEP), no el blue | `frontend/src/utils/valuation.js:629-634`, `backend/snapshots_job.py:214-222` |
| costo de un lote en pesos | `tc_compra` del lote (modo `purchase`) o el MEP de hoy (modo `today`) | `frontend/src/utils/valuation.js:263-268` |
| cripto en BROKER argentino | spot × (cripto/MEP) | `frontend/src/utils/crypto.js:47-53`, `backend/main.py:7096-7113` |
| cripto en EXCHANGE | spot, factor 1.0 | idem |
| CEDEAR que la fuente cotiza en USD (BAC) | precio US × **CCL** ÷ ratio | `backend/main.py:7833`, `backend/snapshots_job.py:504` |
| flujos / ventas / cupones históricos | `fx_for_date` (MEP de la fecha → blue de la fecha) si v2 | `backend/importing/pipeline.py:97`, `backend/importing/persister.py:734` |
| stamp de display del snapshot (`fx_to_usd_blue`) | **el BLUE del día**, no el MEP con el que se valuó | `backend/snapshots_job.py:791` |

La regla que el proyecto declara como canónica —"todo MEP excepto cripto de exchange"— aparece escrita en `backend/analysis_prep.py:34-38` y en el prompt de la IA (`backend/main.py:28490`: "todo en dólares al tipo MEP (la cripto de exchange va al spot) … el blue es solo referencia, no la base de valuación").

---

### Dónde se calcula

Primero lo canónico (`fx.py` y la cascada live), después los consumidores que derivan su propia tasa.

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `backend/fx.py:76-97` | `fx_for_date_detail` | **SSoT del TC histórico.** Devuelve `(tc, fuente)` con fuente ∈ {mep, blue, fallback} | `v = _lookup(conn, _COL[primero], d)` … `if primero != RIEL_BLUE: v = _lookup(conn, _COL[RIEL_BLUE], d)` | fuente |
| 2 | `backend/fx.py:50-73` | `_lookup` | último valor NO NULO de la columna en o antes de la fecha | `SELECT {col} FROM fx_rates_daily WHERE date <= ? AND {col} IS NOT NULL ORDER BY date DESC LIMIT 1` | fuente |
| 3 | `backend/fx.py:44-47` | constantes de riel | mapea riel→columna | `_COL = {RIEL_MEP: "mep_venta", RIEL_BLUE: "blue_venta"}` | fuente |
| 4 | `backend/fx.py:131-168` | `fx_version` | resuelve y PERSISTE v1/v2 por cuenta (con historia→v1, virgen→v2) | `version = FX_V1 if tiene_historia else FX_V2` | fuente |
| 5 | `backend/main.py:4606-4627` | `_fetch_dolar(casa)` | pega a dolarapi y estampa el **medio** | `medio = round((compra + venta) / 2, 2) if compra else venta` | fuente |
| 6 | `backend/main.py:4630-4644` | `_val_rate` | tasa de valuación de una casa | `v = obj.get("medio") or obj.get("venta")` | fuente |
| 7 | `backend/main.py:4842-4877` | `_get_dolar_data` | caché en memoria TTL 300 s de las 4 casas + resiliencia per-casa | `blue = blue or prev.get("blue")` (idem mep/ccl/cripto) | fuente |
| 8 | `backend/main.py:4939-4954` | `_current_cedear_rate` | **el "MEP" del backend**: cascada mep→ccl→cripto sobre el caché | `for casa in ("mep","ccl","cripto"): v = _val_rate(cached.get(casa))` | fuente |
| 9 | `backend/main.py:4923-4936` | `_current_ccl` | CCL sin `conn` (cron): cascada ccl→mep→cripto | `for casa in ("ccl","mep","cripto")` | fuente |
| 10 | `backend/main.py:4904-4920` | `_display_ccl` | igual que 9 pero cae a `_user_tc_blue(conn, uid)` | `return _user_tc_blue(conn, uid)` | fuente |
| 11 | `backend/main.py:4957-4975` | `_current_cripto_rate` | dólar cripto **de la punta `venta`**, no del medio | `v = obj.get("venta") if isinstance(obj, dict) else obj` | fuente |
| 12 | `backend/main.py:4880-4901` | `_display_blue` | blue "de display" **de la punta `venta`**, fallback al config | `v = blue_obj.get("venta") …; return _user_tc_blue(conn, uid)` | fuente |
| 13 | `backend/main.py:33040-33048` | `_user_tc_blue` | lee `config.tc_blue` del usuario, default 1415 | `SELECT value FROM config WHERE user_id=? AND key='tc_blue'` | fuente |
| 14 | `backend/main.py:7096-7113` | `crypto_broker_factor` | premium cripto/MEP para broker no-exchange | `return float(cripto_rate) / float(mep_rate)` | fuente |
| 15 | `frontend/src/utils/crypto.js:47-53` | `cryptoBrokerFactor` | espejo exacto de 14 | `return tcCripto / tcMep` | fuente |
| 16 | `frontend/src/contexts/CurrencyContext.jsx:46-54` | `pickFinancialRate` | **SSoT del dólar de valuación en el frontend** | `const rate = c => c?.medio ?? c?.venta` … `return (pref === 'ccl' ? (ccl \|\| mep) : (mep \|\| ccl)) \|\| blue` | fuente |
| 17 | `backend/analysis_prep.py:31-48` | `user_fx` | `(tc_blue, tc_cedear)`: blue del config, MEP live-first con caída a `config.tc_mep` | `tc_cedear = live_mep if (live_mep and live_mep > 0) else _config_float(conn, user_id, "tc_mep", tc_blue)` | fuente |
| 18 | `backend/snapshots_job.py:146-155` | `_user_tc_cedear` | envuelve 17 y cae a `tc_blue` | `return tc_cedear if (tc_cedear and tc_cedear > 0) else tc_blue` | fuente |
| 19 | `backend/main.py:32016-32033` | `_get_mep_for_scheduler` | MEP del cron nocturno: caché → fetch directo `bolsa` → `contadoconliqui`; **fail-closed** | `for casa in ("bolsa","contadoconliqui")` … `raise RuntimeError("No se pudo obtener cotización del MEP")` | fuente |
| 20 | `backend/main.py:32009-32013` | `_get_blue_for_scheduler` | blue del cron, punta `venta` | `return float(blue["venta"])` | fuente |
| 21 | `backend/main.py:33051-33063` | `_live_valuation_rate` | MEP live para el `end_value` de Reportes | `return _get_mep_for_scheduler()` / `except: return _user_tc_blue(...)` | fuente |
| 22 | `backend/main.py:36820-36841` | `_advisor_book_fx` | `(tc_blue, tc_mep)` del libro del asesor, desde la TABLA (no el caché) | `SELECT blue_venta, mep_venta FROM fx_rates_daily ORDER BY date DESC LIMIT 1` + fallback a la última fila CON mep | fuente |
| 23 | `backend/advisor_brief.py:160-185` | `_fx` | gemelo de 22 para el brief; prefiere `_current_cedear_rate()` | `_live = main._current_cedear_rate()` | fuente |
| 24 | `backend/twr.py:1220-1280` | `serie_fx` | serie fecha→TC para medir la cartera **en pesos**; riel MEP con caída a blue por fila | `v = _col(r,"mep_venta"); if v is None or float(v or 0) <= 0: v, riel = _col(r,"blue_venta"), "blue"` | fuente |
| 25 | `backend/ledger_replay.py:185-192` | `_fx_en` | MEP de una fecha para reconstruir un borde. **Sin MEP no inventa** | `SELECT mep_venta FROM fx_rates_daily WHERE date <= ? AND mep_venta IS NOT NULL ORDER BY date DESC LIMIT 1` | fuente |
| 26 | `backend/importing/persister.py:45-65` | `blue_for_date` | riel BLUE puro por fecha (camino v1) | `SELECT blue_venta FROM fx_rates_daily WHERE date <= ? ORDER BY date DESC LIMIT 1` | fuente |
| 27 | `backend/main.py:4658-4694` | `_persist_blue_for_date` | **escritor** del blue (+ MEP opcional) del día | `ON CONFLICT(date) DO UPDATE SET blue_venta = excluded.blue_venta, mep_venta = COALESCE(excluded.mep_venta, fx_rates_daily.mep_venta)` | escritor |
| 28 | `backend/main.py:4701-4706` | `SQL_BACKFILL_FX_BLUE` | sentencia del backfill (fuera de la función a propósito, para que el test se ate a ella) | `INSERT INTO fx_rates_daily (date, blue_venta, source) … DO UPDATE SET blue_venta = EXCLUDED.blue_venta` | escritor |
| 29 | `backend/main.py:4709-4788` | `_backfill_fx_rates_if_empty` | seed histórico del blue (~5.700 días) al startup si la tabla está vacía | `requests.get("https://api.argentinadatos.com/v1/cotizaciones/dolares/blue")` | escritor |
| 30 | `backend/main.py:4791-4839` | `_backfill_mep_rates_if_missing` | rellena `mep_venta` desde `/bolsa`. **Solo UPDATE, nunca INSERT** | `UPDATE fx_rates_daily SET mep_venta = ? WHERE date = ? AND mep_venta IS NULL` | escritor |
| 31 | `backend/snapshots_job.py:979-988` | cron nocturno | persiste el blue del día. **No escribe `mep_venta`** | `INSERT INTO fx_rates_daily (date, blue_venta, source) VALUES (?, ?, 'snapshot_cron')` | escritor |
| 32 | `backend/main.py:5039-5040` | `post_snapshot` | persiste blue+MEP del caché al postear la foto | `_persist_blue_for_date(today, float(blue_now), source='dolarapi', mep=mep_now)` | escritor |
| 33 | `backend/importing/pipeline.py:71-100` | `_stamp_gross_amount_usd` | **dolariza los FLUJOS** al TC de la fecha (si hay conn+date) | `tc = fx_for_date(conn, date, fallback=tc_blue) if (conn is not None and date) else tc_blue` … `return float(gross_amount) / float(tc)` | escritor |
| 34 | `backend/importing/pipeline.py:103-127` | `stamp_tx_gross_usd` | camino aparte para conversiones: usa **las dos patas reales**, no una cotización | `usd = getattr(tx, "quantity", None); if usd: return abs(float(usd))` | escritor |
| 35 | `backend/importing/pipeline.py:736-745` | `run_preview` | gatea el TC histórico por `fx_version` al estampar | `_hist = fx_version(conn, uid) == FX_V2` … `conn=conn if _hist else None, date=tx.date if _hist else None` | escritor |
| 36 | `backend/importing/pipeline.py:1179-1185` | confirm | gemelo de 35 en el confirm | idem | escritor |
| 37 | `backend/importing/pipeline.py:40-68` | `_read_user_tc_blue` | blue del import: LIVE primero, config después | `live = _main._display_blue(conn, uid)` | fuente |
| 38 | `backend/importing/persister.py:730-736` | `_persist_sell_fifo` | **TC de la venta** | `if sell_currency != "ARS": tc_venta = 1.0 / elif _hist: tc_venta = fx_for_date(conn, tx.date, fallback=tc_blue) / else: tc_venta = tc_blue` | escritor |
| 39 | `backend/importing/persister.py:757-772` | `_persist_sell_fifo` cross-currency | lote USD vendido en ARS → ×`tc_venta`; lote ARS vendido en USD → ÷TC de la fecha de COMPRA | `base_invested = base_invested * (tc_venta or tc_blue)` / `purchase_fx = (fx_for_date(conn, entry_dt, fallback=tc_blue) if _hist else blue_for_date(conn, entry_dt, tc_blue)); base_invested = base_invested / (purchase_fx or tc_blue)` | escritor |
| 40 | `backend/importing/persister.py:789-794` | `_persist_sell_fifo` ARS | P&L y costo al MISMO TC (fix FX-phantom) | `pnl_usd = pnl_ars_chunk / tc_venta`; `invested_usd = (entry_invested or 0) / tc_venta` | escritor |
| 41 | `backend/importing/persister.py:816` | `_persist_sell_fifo` | sella `operations.fx_to_usd` **solo si la venta fue en pesos** | `fx_stamp = tc_venta if sell_currency == "ARS" else None` | escritor |
| 42 | `backend/importing/persister.py:549-583` | `_tc_for_date` + `_persist_buy` | completa `tc_compra` del lote en pesos con el TC de la fecha | `if _tc is None and lot_currency == "ARS" and tx.date: _tc = _tc_for_date(conn, tx.date)` | escritor |
| 43 | `backend/importing/rebuild.py:390-395` | rebuild FIFO | gemelo de 38 en el replay | `elif use_hist: tc_venta = fx_for_date(conn, op_date, fallback=tc_blue)` | escritor |
| 44 | `backend/importing/rebuild.py:416-442` | rebuild cross-currency | gemelo de 39 (el comentario dice que divergir acá metía "una pérdida fantasma en TODA operación dólar-MEP") | `base_invested = base_invested * (tc_venta or tc_blue)` / `_pfx = fx_for_date(conn, lot.get("entry_date"), fallback=tc_blue)` | escritor |
| 45 | `backend/importing/rebuild.py:701-729` | `_lot_tc_compra` | gemelo de 42 en el replay | `rate = fx_for_date(conn, entry)` | escritor |
| 46 | `backend/importing/persister.py:1005-1069` | `_apply_cash_flow` | flujo a `monthly_entries` en USD: prioriza el stamp del preview | `if getattr(tx,"gross_amount_usd",None) is not None: amount_usd = float(tx.gross_amount_usd) else: amount_usd = (amount / tc_blue) if currency=="ARS" else amount` | escritor |
| 47 | `backend/importing/persister.py:1108-1148` | `_persist_fx` (ARS→USD) | conversión importada: saca la pata ARS **al blue** y mete la USD a face | `_ars_as_usd = (ars_amount / tc_blue) if tc_blue else 0.0` | escritor |
| 48 | `backend/importing/persister.py:1163-1171` | `_persist_fx` (USD→ARS) | P&L cambiario contra el `tc_compra` promedio del cash USD | `tc_avg = (cash_usd["tc_compra"] if cash_usd else None) or tc; pnl_ars = ars_amount - usd_amount*tc_avg; op_pnl_usd = pnl_ars / tc` | escritor |
| 49 | `backend/main.py:10933-10943` | `POST /api/conversions` | gemelo MANUAL de 48 | `pnl_usd_realized = pnl_ars_realized / data.tc if data.tc > 0 else 0.0` | escritor |
| 50 | `backend/main.py:11282-11289` | `POST /api/positions/sell` | venta manual: si el user no puso TC y es v2, el de la fecha | `tc_venta = data.tc_venta or _fx.fx_for_date(conn, op_date, fallback=_user_tc_blue(conn, uid)) or 1` (v1: `data.tc_venta or 1`) | escritor |
| 51 | `backend/main.py:8227-8229` | `POST /api/positions` | alta manual: completa `tc_compra` con el TC de la fecha | `tc_compra = _fx.fx_for_date(conn, entry_date)` | escritor |
| 52 | `backend/main.py:10405-10419` | `bond_cashflow` (cupón) | sella `currency` + `fx_to_usd` del cobro | `if currency in ('USD','USDT'): fx_to_usd = 1.0 / elif data.fx_to_usd is not None: … / else: fx_to_usd, fx_source = _fx.fx_for_date_detail(conn, data.date)` | escritor |
| 53 | `backend/main.py:9794-9806` | `_autodeposit_rate` | TC del autodepósito: MEP live como fallback de `fx_for_date` | `live = _current_cedear_rate(); fallback = live or _user_tc_blue(conn, uid); return _fx.fx_for_date(conn, date_iso, fallback=fallback) or fallback` | escritor |
| 54 | `backend/main.py:10195-10197` | `POST /api/cash/flow` | depósito/retiro manual con fecha → TC de la fecha, **el del navegador de último recurso** | `_rate = _fx.fx_for_date(conn, data.date, fallback=data.tc_blue) or data.tc_blue; amount_usd = data.amount / _rate` | escritor |
| 55 | `backend/main.py:10100` | ajuste de cash (`target_cash`) | dolariza el diff **con el TC que manda el navegador**, sin `fx_for_date` | `amount_usd = magnitude / data.tc_blue if currency == 'ARS' else magnitude` | escritor |
| 56 | `backend/main.py:12205-12224` | `_pnl_en_moneda_del_broker` | P&L de futuros USD→moneda nativa del broker | `tc = _fx.fx_for_date(conn, fecha, fallback=_user_tc_blue(conn, uid)); return pnl_usd * float(tc or 1)` | escritor |
| 57 | `backend/importing/fx_migrate.py:325-345` | migrador v1→v2, pata FLUJOS | re-estampa `gross_amount_usd` de las filas ARS al TC de su fecha | `cache[d] = fx_for_date(conn, d)` … `UPDATE import_normalized_tx SET gross_amount_usd = ? WHERE id = ?` con `float(f["gross_amount"]) / tc` | escritor |
| 58 | `backend/importing/fx_migrate.py:367-380` | migrador, pata VENTAS | marca v2 **antes** del rebuild y replaya todos los batches | `set_fx_version(conn, uid, FX_V2)` | escritor |
| 59 | `backend/importing/fx_migrate.py:464-487` | verificación post-migración | compara el `fx_to_usd` sellado contra el esperado | `if abs(float(v["fx_to_usd"]) / esperado - 1) <= 0.01` | consumidor |
| 60 | `backend/snapshots_job.py:158-320` | `compute_broker_value_usd` | **motor de valuación backend**: TODO el path ARS (cash, costo, `.BA`) va por `cedear_rate` | `cash_usd = cash_ars / cedear_rate`; `inv_usd = real_cost / cedear_rate`; `mkt_usd = (price_ars * qty) / cedear_rate` | consumidor |
| 61 | `backend/snapshots_job.py:711-720` | `snapshot_user` | resuelve el `cedear_rate` del cron y convierte el cash | `tc_cedear = tc_mep if (tc_mep and tc_mep > 0) else _user_tc_cedear(conn, uid, tc_blue)`; `return (c / tc_cedear) if (ccy == 'ARS' and tc_cedear > 0) else c` | consumidor |
| 62 | `backend/snapshots_job.py:771-791` | `snapshot_user` | estampa `snapshots.fx_to_usd_blue` = **el blue**, mientras el valor se calculó al MEP | `… net_deposited, fx_to_usd_blue, holdings_json …", (uid, target_date, total_value, total_invested, net_deposited, tc_blue, holdings_json))` | escritor |
| 63 | `frontend/src/utils/valuation.js:263-268` | `costBasisRate` | dólar del COSTO según el modo | `return (costBasis === 'purchase' && p?.tc_compra > 0) ? p.tc_compra : currentRate` | consumidor |
| 64 | `frontend/src/utils/valuation.js:293-307` | `pesoLotUsd` | lote en pesos → USD; **el valor SIEMPRE a hoy** | `investedUsd = realCost / costBasisRate(p, tcCedear, costBasis)`; `valueUsd = priceArs != null ? (priceArs * qty) / tcCedear : investedUsdToday` | consumidor |
| 65 | `frontend/src/utils/valuation.js:338-352` | `usdLotValue` | lote de costo USD: costo sin ÷MEP, valor ÷MEP solo si el símbolo es `.BA` | `const mktUsd = raw != null ? (priceIsArs ? raw / cedearRate : raw) : null` | consumidor |
| 66 | `frontend/src/utils/valuation.js:544-702` | `valueLotUsd` / `computeBrokerValue` | **motor de valuación frontend** | `const cedearRate = tcCedear ?? tcValuacion`; `const cashUsd = cashArs / cedearRate`; `valueUsd: trustArs ? mktArs / cedearRate : invUsdHoy` | consumidor |
| 67 | `frontend/src/hooks/useFxHistory.js:149-167` | `getRateForDate` / `getRateOrFallback` | serie **BLUE** por fecha (búsqueda binaria, día anterior más cercano) | `return best >= 0 ? byDate.get(dates[best]) : null` ; `return r != null && r > 0 ? r : fallbackRef.current` | consumidor |
| 68 | `frontend/src/hooks/useFxHistory.js:177-208` | `getMepDetail` / `getMepOrFallback` | serie **MEP** por fecha con traza (`tc`, `source`, `asOf`) y red al blue | `if (exact != null && exact > 0) return { tc: exact, source: 'mep', asOf: dateIso }` … `return { tc: b, source: 'blue', asOf: dates[best] }` | consumidor |
| 69 | `frontend/src/hooks/useHistoricalMoney.js:30-48` | `resolveHistoricalFx` | cadena `fx_to_usd` sellado → blue de la fecha → `tcValuacion` | `const stampUsable = stamped && stamped > 0 && !(rowCcy && rowCcy !== 'ARS'); if (stampUsable) return stamped` | consumidor |
| 70 | `frontend/src/hooks/useHistoricalMoney.js:101-112` | `sumConvertedAt` | convert-then-sum: cada fila a SU FX y recién ahí suma | `const v = convertedValue(usd, { stampedFx: r?.fx_to_usd, dateIso: r?.date, rowCurrency: r?.currency })` | consumidor |
| 71 | `frontend/src/utils/evolution.js:156-171` | `convertSeriesToArs` | curva del Dashboard a pesos: **stamp del snapshot (blue) primero** | `const fx = (stamped && stamped > 0) ? stamped : getFxForDate(p.date); valueUsd: p.valueUsd * safeFx` | consumidor |
| 72 | `frontend/src/utils/fx.js:26-48` | `lookupHistoricalDolar` | blue MENSUAL de `bench.dolar_blue`; mes corriente → tasa live | `if (year === todayY && month === todayM) return liveTc` | consumidor |
| 73 | `frontend/src/utils/insightsModel.js:551-568` | `monthlyReturnArs` | retorno mensual en pesos: cada punta a SU FX, el flujo al medio **geométrico** | `const ciArs = _ci * fxPrev; const cfArs = _cf * fx; const netArs = _net * Math.sqrt(fxPrev * fx)` | consumidor |
| 74 | `backend/twr.py:666-704` | `_leg_en_moneda` | gemelo backend de 73 (Reportes / Métricas) | `return v0 * f0, v1 * f1, flow * ((f0 * f1) ** 0.5)` | consumidor |
| 75 | `backend/twr.py:650-663` | `_factor_fx` | arrastra la devaluación donde la cadena salta sin medir retorno | `return f1 / f0` | consumidor |
| 76 | `backend/reporting/builder.py:643-655` | `_pct_en_pesos` | convierte **solo el porcentaje** del mes, no los montos | `sv, ev, dep = _twr_fx._leg_en_moneda(p0, {"fx": f1, "net_deposited": float(deposits or 0)}, v0, v1)` | consumidor |
| 77 | `backend/realized_pnl.py:98-107` | `realized_usd_sql` | divide `pnl_usd` por `fx_to_usd` SOLO en Cupón/Amortización ARS | `CASE WHEN {p}op_type IN (…) AND {p}currency='ARS' AND {p}fx_to_usd > 0 THEN {p}pnl_usd / {p}fx_to_usd ELSE {p}pnl_usd END` | consumidor |
| 78 | `frontend/src/utils/bondCashflowFx.js:58-105` | `suggestBrokerAmount` | sugiere el monto del cupón en la moneda del broker y decide el `fx_to_usd` de la fila | `amount: round2(theoreticalAmount * tc), fxToUsdForRow: tc` / `amount: round2(theoreticalAmount / tc), fxToUsdForRow: 1` | consumidor |
| 79 | `backend/main.py:7704-7713` + `7822-7825` | `fetch_prices_for_symbols` | cripto en broker AR: el precio `.BA` se devuelve **en pesos al dólar cripto** | `_cripto_ars = _current_cripto_rate() or _current_cedear_rate() or _display_blue(_cdb, uid)`; `result[_csym] = round(result[_csym] * _cripto_ars, 6)` | consumidor |
| 80 | `backend/main.py:7827-7833` | `fetch_prices_for_symbols` | CEDEAR cotizado en USD (BAC) → pesos por **CCL** | `result[_csym] = round(result[_csym] * _ccl_ars / _ratio, 4)` | consumidor |
| 81 | `backend/snapshots_job.py:497-504` | `fetch_prices_*` del cron | gemelo de 80; **sin CCL deja el precio en None** | `result[_csym] = round(result[_csym] * _ccl / _r, 4) if (_ccl and _ccl > 0) else None` | consumidor |
| 82 | `backend/behavioral.py:391-411` | `_position_value_usd` | dos rieles explícitos: `tc_blue` para cash, `tc_cedear` para `.BA` | `rate_holdings = tc_cedear if (tc_cedear and tc_cedear > 0) else tc_blue` | consumidor |
| 83 | `backend/main.py:12446-12459` | `/api/movements` | memoiza el TC por fecha para la pata BUY de cada venta | `_fx_por_fecha[k] = _fx.fx_for_date(conn, k)` | consumidor |
| 84 | `backend/main.py:35717-35733` | informe del asesor | variación MEP de la MISMA ventana que la cartera | `mep_var_pct = round((float(fx1["mep_venta"]) / float(fx0["mep_venta"]) - 1) * 100, 2)` | consumidor |
| 85 | `frontend/src/pages/Insights.jsx:588-599` + `700-705` | curva de Métricas en pesos | usa `bench.dolar_blue` (**blue mensual**), no la serie MEP diaria | `const fx = lookupDolar(monthKey(m.year, m.month)) \|\| fxBase` | consumidor |
| 86 | `frontend/src/pages/HomeMobile.jsx:125-131` | home mobile | valúa **también** al MEP estricto solo para comparar contra snapshots | `const tcMep = pickFinancialRate(dolar, 'mep') \|\| tcValuacion` | consumidor |
| 87 | `frontend/src/pages/Positions.jsx:246-249` | Cartera | "MEP estricto" que NO sigue el toggle MEP/CCL, para badges rotulados MEP | `const tcMepStrict = dolar?.mep?.medio ?? dolar?.mep?.venta ?? config.tc_mep ?? 1415` | consumidor |
| 88 | `backend/main.py:4565-4597` | `PUT /api/config` | el usuario puede guardar `tc_mep` y `tc_blue` a mano | `INSERT INTO config (key, value, user_id) VALUES ('tc_mep', ?, ?) ON CONFLICT (key, user_id) DO UPDATE SET value = EXCLUDED.value` | escritor |
| 89 | `backend/main.py:4556-4562` | `GET /api/config` | default 1415 para las dos claves | `cfg.setdefault("tc_mep", 1415); cfg.setdefault("tc_blue", 1415)` | fuente |
| 90 | `backend/main.py:5378-5392` | `_fetch_dolar_blue_monthly` | benchmark `dolar_blue`: **último día de cada mes** (gana el último por overwrite de dict) | `out[fecha[:7]] = float(venta)` | fuente |

---

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `backend/main.py:4978-4980` | `GET /api/dolar` — lo fetchean 17 pantallas | (no se muestra; alimenta todo) |
| `backend/main.py:4983-4993` | `GET /api/public/dolar` (solo blue, sin auth) | **no encontrado** ningún consumidor en `frontend/src` |
| `backend/main.py:5170-5197` | `GET /api/fx-rates?days=3650` → `[{date, blue, mep}]` | serie que alimenta `useFxHistory` |
| `frontend/src/pages/Config.jsx:729-779` | panel "Cotizaciones" | **"Blue / MEP / CCL / Cripto"**, cada uno con `ARS/USD` (la cripto rotulada `ARS/USDT`), el número grande = el **medio**, y debajo compra/venta; el crédito dice `dolarapi.com · sync {hora}` |
| `frontend/src/pages/Config.jsx:690-726` | selector de costo | **"Costo en dólares"** → "Dólar de la compra" (default) / "Dólar de hoy" |
| `frontend/src/hooks/useCurrencyChoice.js:19-23` | riel de /config | **"USD MEP"** ("Dólar local (default)") · **"USD CCL"** ("El dólar implícito del CEDEAR") · **"Pesos"** |
| `frontend/src/components/CurrencySwitcher.jsx:47-64` | shell (sidebar + topbar mobile) | toggle **"USD | Pesos"**; debajo "Dólar MEP · $1.424" con link a `/config?tab=fx` |
| `frontend/src/contexts/CurrencyContext.jsx:129-144` | `CurrencyProvider` | fetch de `/dolar` al mount + cada 300 s; publica `tcValuacion` y `dolar` |
| `frontend/src/contexts/CurrencyContext.jsx:214-229` | `fmtMoneyRaw` | símbolo `$` para ARS, `US$` para USD, locale `es-AR` |
| `frontend/src/contexts/CurrencyContext.jsx:304-325` | `useMoneyFormat` | conversión al `tcValuacion` **ACTUAL** (no histórico) |
| `frontend/src/pages/Dashboard.jsx:192-194` | Dashboard | `tcValuacion` / `tcCedear` / `tcCripto` |
| `frontend/src/pages/Dashboard.jsx:606-609` | curva de evolución | en ARS, cada punto a su FX (stamp del snapshot = blue) |
| `frontend/src/pages/Dashboard.jsx:250-262` | KPI "P&L Realizado" | convert-then-sum con el blue del último día de cada mes |
| `frontend/src/pages/Positions.jsx:241-257` | Cartera | `tcValuacion`, `tcMep` (alias), `tcMepStrict`, `tcCedear`, `tcCripto` |
| `frontend/src/pages/Positions.jsx:866` | modal de venta | precarga `tc_venta` con `tcValuacion` solo si la venta es en ARS |
| `frontend/src/pages/Positions.jsx:515-533` | cobranzas de bonos | divide por `op.fx_to_usd`; sin sello, `tcValuacion` si parece ARS |
| `frontend/src/pages/Insights.jsx:404-406` | Métricas | `tcValuacion` / `tcCedear` / `tcCripto` |
| `frontend/src/pages/Insights.jsx:917-1006` | serie ARS de Métricas | acumulado en pesos con `lookupBlue` |
| `frontend/src/pages/HomeMobile.jsx:99-131` | home mobile | `tcMep` aparte solo para comparar contra snapshots |
| `frontend/src/pages/PositionsMobile.jsx:629-631` | Cartera mobile | mismos tres rates |
| `frontend/src/pages/PositionDetailMobile.jsx:97-99` | ficha mobile | idem |
| `frontend/src/pages/AssetDetail.jsx:151-153` | ficha de activo | idem |
| `frontend/src/pages/FirstInsight.jsx:85-86` | primer insight | idem |
| `frontend/src/pages/Goals.jsx:66-69` | Objetivos | idem |
| `frontend/src/pages/Events.jsx:149-151` | Novedades | idem |
| `frontend/src/components/MonthlySummary.jsx:94-96` | resumen mensual | idem |
| `frontend/src/components/fundamentals/CarteraList.jsx:69-71` | Calidad de cartera | **`tcCedear = tcValuacion`** (sin `pickFinancialRate` propio) |
| `frontend/src/components/fundamentals/DetailPortfolioBlocks.jsx:112` | detalle de calidad | `pickFinancialRate(dolar, valuationDollar) \|\| 1415` |
| `frontend/src/hooks/useMonthlyData.js:188-190` | datos mensuales | idem |
| `frontend/src/components/RentaFijaSections.jsx:302` | Renta Fija | convierte el precio del bono cuando bono y broker difieren: `pBond = bondCcy === 'USD' ? price / tcMep : price * tcMep` |
| `frontend/src/pages/Terminos.jsx:118`, `frontend/src/pages/Privacidad.jsx:246` | legales | listan `dolarapi.com` como fuente de terceros |
| `frontend/src/utils/fxPanel.js:1-55` + `frontend/src/pages/Admin.jsx:2027` | panel admin de migración FX | buscar/ordenar/filtrar las 497 cuentas por `deltaRendimiento` |
| `backend/main.py:16157` | `GET /api/admin/diagnose-sell-fx` | informe read-only: "tc_venta = blue VIVO del import, no el de la fecha de la venta" (`backend/main.py:16214`) |
| `backend/main.py:16888-16991` | `POST /api/admin/fx-migrate-user` | migración v1→v2 (dry-run + apply) |
| `backend/main.py:16995` | `GET /api/admin/fx-migrate-candidates` | candidatas a migrar |
| `backend/main.py:22939-22940` | contexto de la IA | `"tc_mep": round(tc_cedear, 2)`, `"tc_blue": round(tc_blue, 2)` |
| `backend/main.py:28490` | prompt de la IA | "todo en dólares al tipo MEP … el blue es solo referencia, no la base de valuación" |
| `backend/main.py:11756-11758` | diagnóstico ΔG | `"fx": {"blue_ini": b_i, "blue_fin": b_f, "variacion_pct": fx_var}` |
| `backend/performance.py:232-236` | `/api/insights/performance` | expone `"moneda"` y `"riel_fx"` (mep / blue / mixto) |

---

### Dónde se persiste

**Tabla global (no particionada por usuario): `fx_rates_daily`**

| columna | tipo | quién escribe | notas |
|---|---|---|---|
| `date` | TEXT PK (`YYYY-MM-DD`) | — | `backend/main.py:1477-1483`, `backend/schema_pg.sql:910-917` |
| `blue_venta` | REAL **NOT NULL** | `_persist_blue_for_date`, `SQL_BACKFILL_FX_BLUE`, cron de snapshots | la punta `venta`, no el medio |
| `mep_venta` | REAL **NULLABLE** | solo `_persist_blue_for_date` (con MEP del caché) y `_backfill_mep_rates_if_missing` | el cron nocturno **no la escribe** (`backend/snapshots_job.py:981`) |
| `source` | TEXT | los tres escritores | `'dolarapi' \| 'argentinadatos' \| 'snapshot_cron' \| 'manual'` |
| `fetched_at` | TEXT | los tres | |

Cobertura declarada en `backend/fx.py:33-37`: MEP diario completo desde **2018-10-29** (2.829 filas / 2.830 días); blue diario completo desde **2011-01-03** (5.685 / 5.686). `backend/twr.py:1233-1236` repite la medición con otros números (2.847 y 5.704) sobre la copia de producción del 2026-08-16.

**Columnas que materializan un TC estampado:**

| tabla.columna | qué guarda | escritor |
|---|---|---|
| `positions.tc_compra` | ARS/USD de la compra del lote | `backend/main.py:8229`, `backend/importing/persister.py:581-589`, `backend/importing/rebuild.py:701-729` |
| `positions.tc_compra` (fila `is_cash`) | **reusada** como `tc_compra` promedio ponderado del cash USD | `backend/main.py:10864-10866`, leída en `backend/main.py:10939` |
| `import_normalized_tx.tc_compra` | idem, en la fila normalizada | `backend/importing/pipeline.py:755`, `backend/schema_pg.sql:1086` |
| `import_normalized_tx.gross_amount_usd` | el flujo YA dolarizado al TC de su fecha | `backend/importing/pipeline.py:743-750`, re-estampado por `backend/importing/fx_migrate.py:336-338` |
| `operations.currency` + `operations.fx_to_usd` | moneda del hecho y TC nativa-por-USD | `backend/importing/persister.py:816-828`, `backend/main.py:10480-10484`; migración en `backend/main.py:1192-1193` |
| `snapshots.fx_to_usd_blue` | **el BLUE del día del snapshot** (stamp de display) | `backend/snapshots_job.py:791`, `backend/main.py:5062-5078` |
| `config[key='tc_blue']` / `config[key='tc_mep']` | overrides manuales por usuario, default 1415 | `backend/main.py:4581-4592`, sembrados en `backend/main.py:3145-3146` |
| `config[key='fx_version']` | `'v1'` / `'v2'` por cuenta | `backend/fx.py:160-163`, `backend/fx.py:179-182` |

**Se calcula al vuelo (no se persiste):** el `tcValuacion` del frontend, `tcCedear`, `tcCripto`, y todas las tasas live del caché en memoria `_dolar_cache` (TTL 300 s, `backend/main.py:4602-4603`). El caché es de proceso: **cada worker/instancia tiene el suyo**.

⚠️ La base de desarrollo `backend/trading.db` **NO tiene la columna `mep_venta`** (`CREATE TABLE fx_rates_daily (date, blue_venta, source, fetched_at)`) — viene de una rama vieja; el código manda.

---

### ⚠️ Implementaciones divergentes

**NO hay una sola implementación.** Hay al menos diez divergencias reales, ordenadas por lo que le mueve la aguja al usuario.

#### D1 — La curva del Dashboard en pesos va al BLUE; los KPIs de arriba van al MEP

| | curva de evolución | KPIs / totales de la misma pantalla |
|---|---|---|
| dónde | `frontend/src/utils/evolution.js:156-171` | `frontend/src/contexts/CurrencyContext.jsx:214-229` vía `useMoneyFormat` |
| tasa | `p.fxToUsdBlue` (= `snapshots.fx_to_usd_blue` = `tc_blue` del cron, `backend/snapshots_job.py:791`), y si falta, `getHistoricalFx` = la serie **blue** (`frontend/src/hooks/useFxHistory.js:138` filtra por `r.blue`) | `tcValuacion` = `pickFinancialRate` = **MEP o CCL** |
| resultado | el valor en pesos del gráfico | el valor en pesos del hero |

El valor USD del snapshot se calculó dividiendo por el **MEP** (`backend/snapshots_job.py:715`), y después se lo re-multiplica por el **blue** para mostrarlo en pesos. La brecha blue−MEP entra entera en la curva. Con el toggle en Pesos, la última barra del gráfico y el número grande de arriba **no son la misma plata**. En USD coinciden byte a byte, así que el bug solo existe en modo Pesos.

#### D2 — Dos series históricas de dólar, dos rieles, dos resoluciones

| | riel | resolución | quién la usa |
|---|---|---|---|
| `useFxHistory.getRateOrFallback` | **blue** | diaria | Dashboard (curva, P&L realizado), `useHistoricalMoney` (Movimientos, P&L) — `frontend/src/hooks/useFxHistory.js:149-167` |
| `useFxHistory.getMepOrFallback` | **MEP** con red al blue | diaria | **solo** la vista previa del depósito con fecha (`frontend/src/hooks/useFxHistory.js:201-208`) |
| `bench.dolar_blue` | **blue** | **mensual** (último día del mes) | Métricas: curva en pesos, benchmark ARS — `backend/main.py:5378-5392`, `frontend/src/pages/Insights.jsx:588-599` |
| `twr.serie_fx` | **MEP** con red al blue por fila | diaria | Reportes / `/insights/performance` en modo pesos — `backend/twr.py:1242-1266` |
| `ledger_replay._fx_en` | **MEP puro**, sin red | diaria | reconstrucción de bordes — `backend/ledger_replay.py:185-192` |
| `fx.fx_for_date` | MEP→blue | diaria | todo el motor de escritura — `backend/fx.py:76-97` |

Consecuencia concreta: **el "rendimiento en pesos" de Métricas (blue mensual) y el de Reportes (MEP diario) son dos números distintos para el mismo período.** `backend/performance.py:236` incluso expone `riel_fx` en la respuesta, pero la pantalla de Métricas no lo usa: arma su propia serie en el browser.

#### D3 — `mep_venta` es nullable y el cron no la llena

`_persist_blue_for_date` escribe `mep_venta` solo si el caché de `/dolar` lo tenía (`backend/main.py:5039-5040`), mientras el cron nocturno **ni la nombra** (`backend/snapshots_job.py:981-987`). El resultado está documentado en tres lugares distintos, cada uno con su parche propio:

- `frontend/src/hooks/useFxHistory.js:169-176`: "el cron nocturno no lo escribe, así que el MEP 'del 15/08' puede ser en realidad el del 13/08" → devuelve `asOf` para poder decirlo.
- `backend/main.py:36832-36840`: "la fila MÁS NUEVA puede venir solo-blue → si no, el libro entero se valuaba al blue ~5 % abajo un fin de semana cualquiera".
- `backend/advisor_brief.py:164-165`: el mismo parche, copiado.

`fx.py` lo esquiva por diseño poniendo el `IS NOT NULL` dentro del `WHERE` (`backend/fx.py:53-58`), pero los tres lectores de arriba no usan `fx.py`.

#### D4 — El blue de la app tiene dos definiciones: `medio` en unos lados, `venta` en otros

| función | tasa | archivo:línea |
|---|---|---|
| `_val_rate` (usada por `_current_ccl`, `_display_ccl`, `_current_cedear_rate`) | `medio or venta` | `backend/main.py:4630-4644` |
| `_display_blue` | **`venta`** | `backend/main.py:4896` |
| `_current_cripto_rate` | **`venta`** (declarado y justificado) | `backend/main.py:4964-4970` |
| `_get_blue_for_scheduler` | **`venta`** | `backend/main.py:32011-32012` |
| `_get_mep_for_scheduler` (rama de fetch directo) | **`venta`** | `backend/main.py:32031-32032` |
| `pickFinancialRate` (frontend) | `medio ?? venta` | `frontend/src/contexts/CurrencyContext.jsx:51` |
| `tcCripto` (frontend) | **`venta`** | `frontend/src/pages/Dashboard.jsx:194` y 8 pantallas más |
| `tcMepStrict` (Cartera) | `medio ?? venta` | `frontend/src/pages/Positions.jsx:249` |

La cripto es una excepción declarada. `_display_blue` y `_get_blue_for_scheduler` no lo son: `_display_blue` es lo que el importador usa como TC de fallback (`backend/importing/pipeline.py:55`, `backend/importing/persister.py:1308`), así que un flujo importado con caché frío se dolariza a la **punta cara** mientras la pantalla lo muestra al **medio**. Y `_get_mep_for_scheduler` devuelve el **medio** por su primera rama (`_current_cedear_rate`) y la **punta venta** por la segunda (fetch directo con caché frío) — o sea que dos snapshots consecutivos pueden valuarse con bases distintas, que es exactamente el "spread como pérdida fantasma" que `backend/ledger_replay.py:20-25` describe.

#### D5 — El importador lee `tc_blue` de dos maneras dentro del MISMO archivo

| | `persist_batch` (aplicar un batch) | `_read_tc_blue` (revert, migrador) |
|---|---|---|
| línea | `backend/importing/persister.py:343-351` | `backend/importing/persister.py:1299-1320` |
| fórmula | `SELECT value FROM config WHERE user_id=? AND key='tc_blue'` (default 1415) | `live = _main._display_blue(conn, uid)` y **después** el config |

El docstring de `_read_tc_blue` dice explícitamente que el config "en cuentas viejas quedaba stale (~143 de 2021) e inflaba el 'aportado' ~10× con pérdida fantasma" — y el escritor que aplica el batch es justamente el que **no** lo usa. `pipeline._read_user_tc_blue` (`backend/importing/pipeline.py:40-68`) sí prefiere el live. O sea: dentro de un mismo import, el stamp de `gross_amount_usd` puede ir al blue live y el `tc_blue` que el persister pasa a `_apply_cash_flow`/`_persist_fx` al config stale.

#### D6 — Dos maneras de dolarizar un movimiento de caja manual, en el mismo endpoint family

| | `POST /api/cash/flow` (depósito/retiro) | ajuste de cash a un target |
|---|---|---|
| línea | `backend/main.py:10195-10197` | `backend/main.py:10100` |
| fórmula | `_rate = _fx.fx_for_date(conn, data.date, fallback=data.tc_blue); amount_usd = data.amount / _rate` | `amount_usd = magnitude / data.tc_blue` |

El primero resuelve el TC **en el servidor** por la fecha del movimiento; el segundo usa **el número que mandó el navegador**, que es el dólar de hoy. Los dos escriben `monthly_entries.deposits/withdrawals`, o sea el denominador del rendimiento.

#### D7 — La conversión ARS→USD del import NO es neutra en capital; la manual ni siquiera toca el capital

`_persist_fx` (import) saca la pata ARS del capital aportado a **`ars_amount / tc_blue`** (el blue live del momento del import) y mete la pata USD a **face value** (`backend/importing/persister.py:1139-1143`). Si el usuario convirtió al MEP —que es lo normal— las dos patas no se cancelan y la conversión **crea o destruye capital aportado**. El propio comentario dice que el criterio es "valuar el capital a la MISMA tasa que las tenencias (ARS→blue, USD→face)", pero las tenencias en pesos **no** se valúan al blue: se valúan al MEP (`backend/snapshots_job.py:214-222`).

`POST /api/conversions` con `direction='ars_to_usd'` **no llama a `_update_monthly_flow` en absoluto** (`backend/main.py:10898-10914`): la conversión manual no toca el capital aportado, la importada sí. Dos caminos para el mismo hecho de negocio, con efectos opuestos sobre el mismo número.

#### D8 — El P&L de una venta manual en pesos sin TC: v1 divide por 1

`backend/main.py:11282-11286`:

```
if _fx.fx_version(conn, uid) == _fx.FX_V2:
    tc_venta = data.tc_venta or _fx.fx_for_date(conn, op_date, fallback=_user_tc_blue(conn, uid)) or 1
else:
    tc_venta = data.tc_venta or 1
```

En una cuenta **v1** (todas las que tenían historia al deploy), si el frontend no manda `tc_venta` el P&L en pesos se guarda como si fuera dólares. El comentario de arriba (`backend/main.py:11277-11281`) lo llama "el bucket B5 del diagnóstico, imposible de distinguir después de una venta USD genuina". El frontend solo manda `tc_venta` cuando la venta es en ARS (`frontend/src/pages/Positions.jsx:866`), así que hoy el `or 1` tapa el agujero por accidente — pero el chat de la IA y cualquier cliente viejo pasan por el mismo endpoint.

#### D9 — `tc_compra` significa dos cosas distintas en la misma columna

- En una fila `is_cash=0` es el **TC de la compra del lote**, usado por `costBasisRate` (`frontend/src/utils/valuation.js:268`).
- En una fila `is_cash=1` de un sub-broker USD es el **TC promedio ponderado del cash en dólares**, usado como cost basis del P&L cambiario (`backend/main.py:10864-10866` lo escribe, `backend/main.py:10939` y `backend/importing/persister.py:1167` lo leen).

Nada en el esquema distingue los dos usos.

#### D10 — El backend valúa a un dólar, el frontend a otro, cuando el usuario elige CCL

`pickFinancialRate` respeta la preferencia MEP/CCL del usuario (`frontend/src/contexts/CurrencyContext.jsx:53`). El backend **no la conoce**: `valuationDollar` vive solo en `localStorage` y no viaja en ninguna request. Todo el backend (snapshots, IA, informe del asesor, Reportes, behavioral) valúa a `_current_cedear_rate()`, cascada `mep→ccl→cripto` (`backend/main.py:4939-4954`). Con la preferencia en **CCL**, la Cartera muestra un total y el snapshot de esa misma noche guarda otro. `frontend/src/pages/HomeMobile.jsx:119-125` conoce el problema y lo parchea **solo en el home mobile**, valuando aparte al MEP estricto "para no fabricar la brecha CCL/MEP como ganancia del día fantasma". Dashboard, Cartera y Métricas no tienen ese parche.

#### D11 — Convergencias verificadas (donde SÍ hay una sola implementación)

- **`crypto_broker_factor`**: backend (`backend/main.py:7096-7113`) y frontend (`frontend/src/utils/crypto.js:47-53`) son espejos; `frontend/src/utils/crypto.test.js` fija la paridad de `CRYPTO_SYMBOLS`.
- **`_leg_en_moneda`**: Reportes lo importa del motor en vez de reimplementarlo, con el comentario "Reimplementar esas dos líneas acá es exactamente cómo se desincronizan dos motores" (`backend/reporting/builder.py:639-641`).
- **`computeBrokerValue` ↔ `compute_broker_value_usd`**: son ports declarados uno del otro (`backend/snapshots_job.py:166`), incluida la regla de que el cash ARS va al `cedear_rate` y no al blue.
- **`_val_rate` ↔ `pickFinancialRate`**: leen el mismo campo `medio`, y `backend/tests/test_dolar_medio.py:9-11` lo declara "la regla de oro".
- **`realized_usd_sql`**: la expresión que divide por `fx_to_usd` vive en un solo lugar (`backend/realized_pnl.py:98-107`) porque, dice el comentario, estaba copiada a mano en 4 lectores y solo se arregló en uno.

---

### Zonas grises

1. **`snapshots.fx_to_usd_blue` no es "el blue del snapshot": es un campo de tres usos incompatibles.** Se escribe con `tc_blue` (`backend/snapshots_job.py:791`), pero (a) se lo usa como el FX de display de la curva en pesos —y ahí debería ser el MEP, que es con lo que se valuó—, (b) se lo usa como **marcador de tipo de fila**: `backend/twr.py:200-211` clasifica un snapshot como `MEDICION` o `INTRADIA` según si `fx_to_usd_blue is not None`, y (c) se lo usa como serie para medir la devaluación en un diagnóstico (`backend/main.py:11695-11697`). Un cambio en cualquiera de los tres roles rompe los otros dos.

2. **Nada garantiza que `mep_venta` de una fecha sea el MEP de esa fecha.** El backfill viene de `argentinadatos /bolsa` (`backend/main.py:4811`), pero `_persist_blue_for_date` puede pisarlo con el MEP del caché *del momento del POST* bajo la fecha `_iso_today()`. Y el backfill **solo hace UPDATE de filas que ya existen** (`backend/main.py:4797-4800`), cuyo universo lo define el blue: una fecha con MEP pero sin blue nunca entra a la tabla.

3. **`_backfill_mep_rates_if_missing` deja de reparar apenas la serie está completa.** El guard es `SELECT COUNT(*) FROM fx_rates_daily WHERE mep_venta IS NULL` (`backend/main.py:4805-4808`). Si el cron nocturno inserta filas nuevas con `mep_venta` NULL —que es lo que hace todas las noches (`backend/snapshots_job.py:981`)— el contador nunca llega a cero, así que la API se pega en **cada arranque**. No es un bug de corrección, pero contradice el comentario "Idempotent: si NO hay filas con mep_venta NULL, no pega a la API".

4. **`/api/public/dolar` no tiene consumidor en este repo.** El docstring dice que es "para mostrar precios en ARS en la landing pública" (`backend/main.py:4985-4990`), pero `Planes.jsx` dejó de convertir: los precios son ARS hardcodeados desde 2026-05-31 (`frontend/src/pages/Planes.jsx:34-48`). El único `api.get('/dolar')` de Planes es el autenticado (`frontend/src/pages/Planes.jsx:133`). Puede que la landing sea otro proyecto — no verificable desde acá.

5. **El caché de dólar es por proceso y el frontend refresca cada 5 minutos, igual que el TTL.** `DOLAR_TTL = 300` (`backend/main.py:4603`) y `setInterval(fetchAndPublish, 300_000)` (`frontend/src/contexts/CurrencyContext.jsx:142`). Con más de un worker, dos requests casi simultáneos pueden devolver tasas distintas, y el `prev.get(...)` de la resiliencia per-casa (`backend/main.py:4862-4866`) puede dejar una casa arrastrando un valor arbitrariamente viejo sin que nada lo marque como stale (`fetched_at` de la respuesta es el del último fetch **exitoso de cualquier casa**, `backend/main.py:4872`).

6. **`fx_version` se resuelve con un `try/except Exception: return FX_V1`** (`backend/fx.py:165-168`). Un fallo transitorio de base durante un import hace que esa corrida escriba con el dólar vivo aunque la cuenta esté migrada a v2 — silenciosamente, y el rebuild siguiente no lo corrige porque él vuelve a preguntar.

7. **No encontré ningún lugar que use el CCL como riel de conversión de moneda del usuario en el backend.** El CCL solo aparece (a) como fallback dentro de las cascadas y (b) para derivar el precio en pesos de los CEDEARs que la fuente cotiza en USD, hoy un solo ticker: `CEDEAR_USD_RATIOS = {"BAC": 4}` (`backend/main.py:7125-7127`). O sea: la opción "USD CCL" del riel de /config cambia la valuación **solo en el browser**.

8. **La cripto está a mitad de camino del cambio al `medio`.** `backend/main.py:4964-4968` explica que no se movió porque "el frontend lee `dolar.cripto.venta` crudo en ~8 lugares" — verificado: `Dashboard.jsx:194`, `Positions.jsx:257`, `Insights.jsx:406`, `HomeMobile.jsx`, `PositionsMobile.jsx:631`, `PositionDetailMobile.jsx:99`, `AssetDetail.jsx:153`, `Goals.jsx:69`, `Events.jsx:151`, `FirstInsight.jsx:86`, `MonthlySummary.jsx:98`, `CarteraList.jsx:71`. Pero `Config.jsx:775` **sí muestra el medio** de la cripto. La celda del panel de cotizaciones y la tasa que efectivamente valúa la cripto son números distintos.

9. **`costBasisRate` cambió de default y quedaron dos defaults distintos escritos.** El parámetro es `costBasis = 'purchase'` (`frontend/src/utils/valuation.js:263`), pero `pesoLotUsd`, `valueEquityLot`, `valueLotUsd`, `computeBrokerValue` y `avgCostUsdPerUnit` siguen declarando `costBasis = 'today'` (`frontend/src/utils/valuation.js:293`, `:360`, `:544`, `:740`, `:868`). El comentario de `costBasisRate:264-268` dice que esa asimetría era el bug ("cualquier caller que se olvidara de pasar `costBasis` volvía al dólar de hoy en silencio"), y sigue estando en los otros cinco.

10. **`Insights.jsx:328` pasa `tb` como `tcValuacion` Y como `cedearRate`** (`computeBrokerValue(positions, prices, b, tb, tb, tcr, costBasis)`), mientras el resto de la página pasa `tcValuacion, tcCedear` (`frontend/src/pages/Insights.jsx:411`). Hoy los dos valores son idénticos (ambos salen de `pickFinancialRate(dolar, valuationDollar)`), así que es inofensivo — pero es exactamente el patrón que `frontend/src/pages/Positions.jsx:232-236` documenta como el bug de "filas al 1.341,71 y pie al 1.521,10 en la misma tabla".

11. **`positions.currency` como discriminador de moneda del costo no está garantizado.** `costInUsd` y `costInPesos` (`frontend/src/utils/valuation.js:216-218`, `:324-327`) dependen de que el lote traiga `currency`. `backend/importing/persister.py:750-752` dice explícitamente que en lotes viejos puede ser NULL y ahí "asumimos la moneda del broker para back-compat". Un lote NULL en un broker mal marcado se dolariza al revés — que es la familia de bugs de `project_negative_capital_corruption` y `project_cedear_cost_usdleg`.

12. **La conversión de un CEDEAR en dólares usa `tcMepStrict` para el badge y `tcCedear` para la valuación.** `frontend/src/pages/Positions.jsx:246-253`: el badge dice "MEP" y usa el MEP puro; la fila de al lado valúa con la preferencia del usuario, que puede ser CCL. Es una divergencia deliberada y documentada, pero significa que el número rotulado y el número usado no son el mismo.
