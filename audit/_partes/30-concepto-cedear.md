## CEDEAR: ratio, split, valuación y pata en dólares

### Definición según el código

En Rendi, «CEDEAR» **no es un tipo de activo con ratio propio**. Es, en orden de importancia:

1. **Un ruteo de precio.** `asset_type == 'CEDEAR'` significa una sola cosa operativa: *«este holding se cotiza por su símbolo `.BA` (en pesos, BYMA), nunca por el ticker US del mismo nombre»*. Es la bandera que evita el bug bautizado C1 en los comentarios: un CEDEAR de MELI valuado como la acción de MELI queda 15-100× inflado. [V] `frontend/src/utils/valuation.js:83-87`, `backend/snapshots_job.py:105-128`, `backend/behavioral.py:166-190`.
2. **Un ruteo de moneda.** El precio `.BA` viene en ARS y se pasa a USD dividiendo por un único rate llamado `cedearRate` / `tc_cedear` / `cedear_rate`, que es el **dólar financiero elegido por el usuario (MEP por defecto, CCL opcional), al MEDIO (compra+venta)/2**, no el blue. [V] `frontend/src/contexts/CurrencyContext.jsx:47-54`, `backend/analysis_prep.py:31-48`.
3. **Una excepción de fuente de precio, con un ratio de verdad, para exactamente UN ticker.** El único lugar del repo donde el «ratio del CEDEAR» (cuántos CEDEARs equivalen a una acción US) existe como número es un dict de un elemento: `CEDEAR_USD_RATIOS = {"BAC": 4}`. [V] `backend/main.py:7125-7127`. Se usa sólo cuando la fuente de mercado devuelve el precio en USD en vez de en pesos, con la fórmula `ARS = precio_US × CCL ÷ ratio`.
4. **Un evento de corrección de cantidad («split» / «cambio de ratio»).** No modela el ratio del CEDEAR: aplica el factor de split que **yfinance** reporta para el símbolo `.BA` a `quantity` y `buy_price`, dejando `invested` intacto. [V] `backend/main.py:8651-8656, 8940-8955`.
5. **Una decisión de en qué cuenta vive la tenencia cuando se pagó en dólares («pata en dólares»).** Un CEDEAR comprado por dólar-MEP consolida la **tenencia** en el broker padre ARS, pero la **plata** sale del sub-broker `<Padre> · USD`. [V] `backend/importing/persister.py:68-95, 306-320`.
6. **Una consolidación de tickers D/C.** La «pata dólar» de un instrumento (AL30/AL30D, GGAL/GGALD, SID/SIDD, PETR3/PETRD) se colapsa al ticker base para que el FIFO no arme dos ledgers. [V] `backend/importing/tickers_cd.py:122-163`.

**No estándar, explícito:** el ratio del CEDEAR **no se guarda, no se muestra y no participa de ninguna valuación** salvo el caso BAC. Rendi no convierte nunca «N CEDEARs → M acciones»: valúa el CEDEAR por su propio precio local. Un `asset_type='CEDEAR'` en un broker de EE.UU. de verdad (Schwab) igual se rutea a `.BA` — el tipo gana sobre el broker. [V] `frontend/src/utils/valuation.js:87`, test `frontend/src/utils/buildPriceSymbols.test.js:28-35`.

---

### Dónde se calcula

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `frontend/src/utils/valuation.js:81-104` | `priceSymbol(asset, isARS, assetType)` | SSoT del símbolo de precio. CEDEAR ⇒ `.BA` siempre; acción AR sólo si el broker es ARS | `if (assetType === 'CEDEAR' && !(asset \|\| '').endsWith('.BA')) return \`${asset}.BA\`` | **fuente** (frontend) |
| 2 | `frontend/src/utils/valuation.js:543-737` | `valuePositionLot(p, ctx)` | Motor canónico por lote, 6 ramas. Rama 5 = instrumento BYMA en broker USD | `const mktUsd = priceArs != null ? (priceArs * (p.quantity \|\| 0)) / cedearRate : null` (l. 693) | **fuente** (canónica declarada) |
| 3 | `frontend/src/utils/valuation.js:740-765` | `computeBrokerValue(...)` | Suma de `valuePositionLot` por broker | `const ctx = { broker, prices, tcValuacion, tcCedear: cedearRate, tcCripto, costBasis }` | **fuente** |
| 4 | `frontend/src/utils/valuation.js:191-201` | `isArUsdBroker(brokerName)` | ¿Sub-broker dólar de padre ARS? Decide `.BA` cuando `asset_type` no dice CEDEAR | `return /·\s*USD$/.test(brokerName \|\| '')` (fallback) | **fuente** |
| 5 | `frontend/src/utils/valuation.js:338-352` | `usdLotValue(p, prices, cedearRate)` | Lote de **costo USD** (CEDEAR pagado por MEP, `currency='USD'`) en broker ARS | `const mktUsd = raw != null ? (priceIsArs ? raw / cedearRate : raw) : null` | **fuente** |
| 6 | `frontend/src/utils/valuation.js:293-308` | `pesoLotUsd(p, prices, tcCedear)` | Lote de **costo ARS** alojado en cuenta USD | `const valueUsd = priceArs != null ? (priceArs * (p.quantity \|\| 0)) / tcCedear : investedUsdToday` | **fuente** |
| 7 | `frontend/src/utils/valuation.js:360-421` | `valueEquityLot(...)` | 5ª implementación por lote (usada por «Calidad de cartera») | `valueUsd = priceArs != null ? (priceArs / cedearRate) * qty : null` (l. 405) | **fuente paralela** |
| 8 | `frontend/src/utils/valuation.js:469-475` | `valuationPriceKey(p, isArsBroker)` | Key con la que la valuación LEE `prices` — espejo declarado de la rama de arriba | `if (isArUsdBroker(p.broker) \|\| costInPesos(p)) return priceSymbol(p.asset, true, p.asset_type)` | **fuente** |
| 9 | `frontend/src/utils/valuation.js:484-494` | `buildPriceSymbols(positions, brokers)` | Única lista canónica de símbolos a pedir a `/prices` | `const k = valuationPriceKey(p, arsBrokers.has(p.broker))` | **fuente** |
| 10 | `frontend/src/utils/valuation.js:448-455` | `trustMktValue(...)` | Guard anti-distorsión que ataja el CEDEAR preciado como acción US | `return fixed ? (mult <= 4 && mult >= 0.02) : (mult <= 50 && mult >= 0.002)` | **fuente** |
| 11 | `frontend/src/contexts/CurrencyContext.jsx:47-54` | `pickFinancialRate(dolar, pref)` | El `cedearRate`: MEP (default) o CCL, al **medio** | `const rate = c => c?.medio ?? c?.venta;` … `return (pref === 'ccl' ? (ccl \|\| mep) : (mep \|\| ccl)) \|\| blue` | **fuente** |
| 12 | `backend/snapshots_job.py:105-128` | `position_price_key(p, ars_names, ar_usd_names)` | SSoT backend del símbolo (fetch + cobertura + valuación) | `wants_ba = (broker in ars_names or broker in ar_usd_names or (p.get('asset_type') or '').upper() == 'CEDEAR')` | **fuente** (backend) |
| 13 | `backend/snapshots_job.py:70-86` | `_broker_name_sets(brokers)` | `(ars_names, ar_usd_names)` parent-aware **+ fallback por nombre siempre** | `elif _is_ar_usd_subbroker(b.get('name')): ar_usd_names.add(b['name'])` | **fuente** |
| 14 | `backend/snapshots_job.py:60-67` | `_is_ar_usd_subbroker(name)` | Detección estricta por el separador `·` | `return bool(_AR_USD_SUBBROKER_RE.search((broker_name or '').strip().lower()))` (`re.compile(r'·\s*usd$')`, l. 57) | **fuente** |
| 15 | `backend/snapshots_job.py:158-317` | `compute_broker_value_usd(...)` | Port del motor frontend. Rama CEDEAR en broker USD (l. 299-309) | `mkt_usd = (price_ars * (p.get('quantity') or 0)) / cedear_rate if cedear_rate > 0 else 0` (l. 306) | **fuente** (snapshot, asesor, replay) |
| 16 | `backend/snapshots_job.py:185` | ídem | Decide `ar_usd` **sólo por el nombre**, no parent-aware | `ar_usd = _is_ar_usd_subbroker(broker_name)` | **fuente** (ver divergencias) |
| 17 | `backend/snapshots_job.py:146-155` | `_user_tc_cedear(conn, uid, tc_blue)` | dólar-MEP del usuario para holdings `.BA` | `return tc_cedear if (tc_cedear and tc_cedear > 0) else tc_blue` | **fuente** |
| 18 | `backend/snapshots_job.py:715` | `build_and_persist_snapshot` | Rate del snapshot: MEP del job → caché → config → blue | `tc_cedear = tc_mep if (tc_mep and tc_mep > 0) else _user_tc_cedear(conn, uid, tc_blue)` | **consumidor** |
| 19 | `backend/behavioral.py:247-269` | `byma_broker_names(brokers)` | Brokers que se valúan por `.BA`: currency ARS + hijos de padre ARS. **Sin** fallback por nombre | `if (b.get("currency") or "").strip().upper() == "ARS": out.add(name)` … `parent = by_id.get(b.get("parent_broker_id"))` | **fuente** |
| 20 | `backend/behavioral.py:272-282` | `stamp_byma(positions, brokers)` | Estampa `p['_byma']` en la fila | `p["_byma"] = ((p.get("asset_type") or "").upper() == "CEDEAR") or (p.get("broker") in byma)` | **fuente** |
| 21 | `backend/behavioral.py:166-190` | `_price_is_ars(p)` | ¿El precio live cotiza en ARS? CEDEAR ⇒ sí; si no, `_byma`; si no, heurística por nombre | `if (p.get("asset_type") or "").upper() == "CEDEAR": return True` | **fuente** (Análisis/IA) |
| 22 | `backend/behavioral.py:354-388` | `_resolve_price(asset, broker, prices, is_ars)` | Busca `<TICKER>.BA` para contexto AR, sin fallback cruzado | `return prices.get(a + ".BA")` | **fuente** |
| 23 | `backend/behavioral.py:391-482` | `_position_value_usd(...)` | Valuación USD por posición para Análisis/IA | `mkt_usd = (value_native / rate_holdings) if (price_is_ars and rate_holdings > 0) else value_native` | **fuente paralela** |
| 24 | `backend/analysis_prep.py:31-48` | `user_fx(conn, uid)` | `(tc_blue, tc_cedear)` — MEP **live-first** (caché dolarapi) → `config.tc_mep` → blue | `tc_cedear = live_mep if (live_mep and live_mep > 0) else _config_float(conn, user_id, "tc_mep", tc_blue)` | **fuente** |
| 25 | `backend/analysis_prep.py:51-74` | `fetch_ba_aware_prices(positions)` | Pide `.BA` según `_price_is_ars` | `if _price_is_ars(p) and not a.upper().endswith(".BA"): symbols.add(a + ".BA")` | **fuente** |
| 26 | `backend/main.py:7125-7127` | `CEDEAR_USD_RATIOS` | **El único ratio del repo.** Ticker base → cedears por acción US | `CEDEAR_USD_RATIOS = {\n    "BAC": 4,\n}` | **fuente** |
| 27 | `backend/main.py:7826-7833` | `get_prices` (`/api/prices`) | CEDEARs cotizados en USD → pesos | `result[_csym] = round(result[_csym] * _ccl_ars / _ratio, 4)` | **fuente** |
| 28 | `backend/main.py:8023-8028` | `get_prev_close` | Mismo cálculo para el cierre previo (Var. día) | `result[_csym] = round(result[_csym] * _ccl_ars / _ratio, 4)` | **fuente** |
| 29 | `backend/main.py:8080-8127` | `get_price_history` | Serie histórica del subyacente US → pesos punto por punto | `pt["close"] = round(pt["close"] * _ccl / _ratio, 4)` | **fuente** |
| 30 | `backend/snapshots_job.py:415-505` | `fetch_prices_for_symbols` | Igual que `/api/prices` para el cron; sin CCL deja `None` (no persiste el valor roto) | `result[_csym] = round(result[_csym] * _ccl / _r, 4) if (_ccl and _ccl > 0) else None` | **fuente** |
| 31 | `backend/main.py:4904-4921` | `_display_ccl(conn, uid)` | CCL de display, cascada `ccl→mep→cripto`, fallback blue del config | `for casa in ("ccl", "mep", "cripto"): v = _val_rate(cached.get(casa))` | **fuente** |
| 32 | `backend/main.py:4923-4936` | `_current_ccl()` | Igual sin `conn` (cron); `None` si el caché está frío | ídem | **fuente** |
| 33 | `backend/main.py:4939-4959` | `_current_cedear_rate()` | dólar-MEP live, cascada `mep→ccl→cripto` — el espejo backend de `cedearRate` | `for casa in ("mep", "ccl", "cripto"): v = _val_rate(cached.get(casa))` | **fuente** |
| 34 | `backend/main.py:7300-7327` | `_resolve_ar_equity_price(symbol)` | data912 (BYMA) primario para `.BA`; **excluye** los CEDEAR con ratio | `if base in CRYPTO_SYMBOLS or base in CEDEAR_USD_RATIOS: return None` | **fuente** |
| 35 | `backend/main.py:8660-8688` | `_fetch_ba_splits(ba_symbol)` | Splits del `.BA` vía yfinance, TTL 6h | `s = yf.Ticker(ba_symbol).splits` | **fuente** (split) |
| 36 | `backend/main.py:8690-8707` | `_dedup_splits(splits)` | Colapsa el mismo evento logueado dos veces (±7 días, mismo factor) | `if abs((cur - prev).days) <= _SPLIT_DEDUP_DAYS: out[-1] = (d, f)` | **fuente** |
| 37 | `backend/main.py:8709-8798` | `_applicable_splits(base, entry, wm, foto_wm)` | SSoT compartida por `/split-check` y `/adjust-ratio` | `if entry and d <= entry: continue` / `if foto_wm and d <= foto_wm: continue` | **fuente** |
| 38 | `backend/main.py:8800-8820` | `_foto_split_watermarks(conn, uid)` | La foto de tenencia («Tenencia — apertura») como watermark, sin ventana de dedup | `MAX(n.date)` agrupado por `(broker, UPPER(asset_symbol))` | **fuente** |
| 39 | `backend/main.py:8822-8857` | `_corporate_split_watermarks(conn, uid)` | El split bookeado como LOTE $0 por Balanz también es watermark | `AND COALESCE(n.unit_price,0) = 0 AND COALESCE(n.gross_amount,0) = 0 AND ( LOWER(...notes) LIKE 'split%' OR ... LIKE '%cambio de ratio%' )` | **fuente** |
| 40 | `backend/main.py:8860-8874` | `_foto_wm_for(...)` | Toma el watermark del PAR de brokers padre↔`· USD` | `return max((foto_map.get((pb, base), "") for pb in pair_cache[broker]), default="")` | **fuente** |
| 41 | `backend/main.py:8877-8965` | `POST /api/positions/{pid}/adjust-ratio` | Aplica el split: cantidad ×F, precio ÷F, `invested` intacto | `new_qty = float(row["quantity"] or 0) * combined` / `new_buy = (float(row["buy_price"]) / combined) if row["buy_price"] else row["buy_price"]` (l. 8943-8944) | **fuente** (escritura) |
| 42 | `backend/main.py:8967-9040` | `GET /api/positions/split-check` | Detección. Gate: `asset_type='CEDEAR'` **o** broker ARS; excluye BOND/FIAT/CRYPTO/FCI | `UPPER(COALESCE(p.asset_type,'')) = 'CEDEAR' OR EXISTS (SELECT 1 FROM brokers b … UPPER(COALESCE(b.currency,'')) = 'ARS')` | **fuente** |
| 43 | `backend/importing/tickers_cd.py:122-146` | `strip_cd_suffix(raw, is_fci)` | Saca la D/C final de la pata dólar; respeta `KNOWN_CD_TICKERS` y el mapa brasileño | `if len(t) >= 3 and t[-1] in ("D", "C") and t not in KNOWN_CD_TICKERS: t = t[:-1]` | **fuente** (pata en dólares) |
| 44 | `backend/importing/tickers_cd.py:149-163` | `consolidate_cd(raw, asset_type)` | Igual, gateado por tipo | `if (asset_type or "").upper() not in CD_ASSET_TYPES: return raw_ticker` (`CD_ASSET_TYPES = {"BOND","STOCK","CEDEAR"}`, l. 90) | **fuente** |
| 45 | `backend/importing/tickers_cd.py:117-119` | `BR_DOLLAR_LEG` | Pata dólar de CEDEARs brasileños (mapa exacto, no regla) | `BR_DOLLAR_LEG = {\n    "PETRD": "PETR3",\n}` | **fuente** |
| 46 | `backend/importing/normalizer.py:441-449` | `normalize_rows` | Aplica `consolidate_cd` al ticker de cada fila importada | `asset_symbol = consolidate_cd(asset_raw, asset_type)` | **consumidor** |
| 47 | `backend/importing/persister.py:68-95` | `cash_broker_for(conn, uid, broker, currency, asset_type)` | **Pata en dólares**: CEDEAR pagado en USD ⇒ tenencia en el padre, plata en el sibling | `if (asset_type or "").upper() != "CEDEAR": return broker` | **fuente** |
| 48 | `backend/importing/persister.py:98-125` | `broker_pair(conn, uid, broker)` | Identidad del par padre↔`· USD` por `parent_broker_id` | `if row["parent_broker_id"]: … names.add(pr["name"])` | **fuente** (21 call sites según `reporting/builder.py:112`) |
| 49 | `backend/importing/persister.py:295-330` | `_route_usd_rows` (bloque de ruteo) | Decide si la fila va al sibling o consolida | `_cb_alta = cash_broker_for(conn, uid, tx.broker, cur, tx.asset_type)` / `if op in (OP_BUY, OP_SELL) and _cb_alta != tx.broker: tx.cash_broker = _cb_alta` | **fuente** |
| 50 | `backend/importing/rebuild.py:111-160` | `_cancel_conduit_pairs(events)` | Cancela el conducto MEP (compra en pesos + venta en dólares del mismo nominal) también para CEDEARs | `if is_exchange: return events` / `_CONDUIT_BLOCKED_TYPES = {"CRYPTO","FIAT","FUND"}` | **fuente** |
| 51 | `backend/importing/tenencia.py:849-857` | `_iol_asset_type(name)` | Clasifica por el nombre del instrumento de la foto IOL | `if n.startswith("cedear") or "cedear" in n: return "CEDEAR"` | **fuente** |
| 52 | `backend/importing/tenencia.py:1316-1317` | parser tenencia Cocos | Ídem por prefijo | `if iu.startswith("CEDEAR"): at = "CEDEAR"` | **fuente** |
| 53 | `backend/importing/parsers/cocos.py:518-525` | parser movimientos Cocos | Hint `asset_type` desde el nombre del instrumento | `if _instr_up.startswith("CEDEAR"): asset_type = "CEDEAR"` | **fuente** |
| 54 | `backend/importing/parsers/balanz_movimientos.py:83` / `balanz_resultados.py:95` / `balanz_internacional.py:52` | parsers Balanz | Sección «Cedears» → `CEDEAR` | `return "CEDEAR"` | **fuente** |
| 55 | `backend/importing/normalizer.py:226-241` | `guess_asset_type(symbol)` | Sin hint del parser **nunca** infiere CEDEAR | `return AT_OTHER  # Sin más contexto del broker, no asumimos STOCK/CEDEAR` | **fuente** (define el hueco) |
| 56 | `frontend/src/utils/assetClass.js:199-205, 239-244` | `isArMarket` / `classifyAsset` | Clasificación para tortas: CEDEAR ⇒ mercado AR | `if ((position.asset_type \|\| '').toUpperCase() === 'CEDEAR') return true` / `if (CEDEAR_SYMS.has(ticker)) return 'cedear'` | **fuente** (composición) |
| 57 | `frontend/src/utils/insightsModel.js:450-461` | `classifyAssetType` | Clasificación vieja, 4 categorías | `if (position.asset_type === 'CEDEAR' \|\| isArUsdBroker(position.broker)) return 'CEDEAR/AR'` | **fuente paralela** |
| 58 | `backend/advisor_groups.py:38-72` | `_class_of(asset, asset_type)` | Clase para las reglas de grupos del asesor | `if t == "CEDEAR": return "cedear"` … `if base in CEDEAR_TICKERS and a.endswith(".BA"): return "cedear"` | **fuente paralela** |
| 59 | `backend/main.py:36933-36939` | `_advisor_positions_valued` | Resuelve `is_ar_market` server-side para el libro del asesor | `(p.get("asset_type") or "").upper() == "CEDEAR" or p["broker"] in ars_names or p["broker"] in ar_usd_names` | **fuente** |
| 60 | `backend/main.py:23836-23840` | Coach IA / `register_trade` | Una acción US en broker ARS se re-tipa a CEDEAR sola | `if kind == "STOCK" and currency == "ARS": if "CEDEAR" in kinds: kind = "CEDEAR"; fields["asset_type"] = "CEDEAR"` | **fuente** (escritura) |
| 61 | `frontend/src/pages/Positions.jsx:63-66` | `CATEGORY_ASSET_TYPE` | Alta manual: categoría «CEDEARs» ⇒ `asset_type='CEDEAR'` | `cedears: 'CEDEAR', stocks: 'STOCK', etfs: 'ETF', crypto: 'CRYPTO',` | **fuente** (escritura) |
| 62 | `frontend/src/components/AddPositionFlow.jsx:155-162` | `resolvePick(symbol, name)` | Desempate CEDEAR vs acción US por la moneda del broker | `const wantCedear = brokerCurrency === 'ARS'` | **fuente** |
| 63 | `frontend/src/utils/tickers.js:435-441` | `CEDEAR_ESPECIE_ALIAS` / `cedearEspecieBase` | Alias de especie-pesos → ticker canónico US (`SI` → `SID`) | `export const CEDEAR_ESPECIE_ALIAS = { SI: 'SID' }` | **fuente** |
| 64 | `frontend/src/utils/valuation.js:239-243` | `holdingHasReliableFundamentals` | Gatea qué holdings tienen fundamentals confiables: en BYMA sólo un CEDEAR reconocido | `return CEDEAR_TICKERS.has(cedearEspecieBase(p?.asset))` | **fuente** |

---

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `frontend/src/pages/Positions.jsx:1282-1291` | `calcUSDT` — filas de la tabla de Cartera (desktop), broker USD | «Precio», «Valor», «P&L» de la fila |
| `frontend/src/pages/Positions.jsx:1320-1338` | `calcARS` — rama `costInUsd` (CEDEAR pagado por MEP en broker ARS) | columnas «Valor», «Inv USD» |
| `frontend/src/pages/Positions.jsx:1542-1559` | `dvFor` — variación del día CEDEAR-aware (`.BA` contra `.BA`) | columna «Var. día» |
| `frontend/src/pages/Positions.jsx:620-635` | `openAlertForPosition` — riel `.BA`/ARS para CEDEARs | «Crear alerta» del menú de la posición |
| `frontend/src/pages/Positions.jsx:1851` | `<SplitRatioBanner onAdjusted={loadAll} />` | banner «Una posición tuvo un cambio de ratio (split)» |
| `frontend/src/pages/PositionsMobile.jsx:726-738` | matriz de valuación mobile, rama BYMA-en-broker-USD | tarjetas de Cartera (mobile) |
| `frontend/src/pages/PositionsMobile.jsx:805-820` | Var. día mobile con prevClose en `.BA` ÷ MEP | «Hoy» de cada tarjeta |
| `frontend/src/pages/PositionsMobile.jsx:1282` | `<SplitRatioBanner …>` | mismo banner en mobile |
| `frontend/src/pages/PositionDetailMobile.jsx:152-159` | detalle de posición (mobile) | «Precio actual», «Valor», «Resultado» |
| `frontend/src/pages/AssetDetail.jsx:34-98, 152` | `valueLot` — ficha del activo | «Valor», «Invertido», «P&L» por lote |
| `frontend/src/pages/Dashboard.jsx:341-352` | `positionsForInsight` — rama CEDEAR/`· USD` | tarjetas y KPIs del Dashboard |
| `frontend/src/pages/Dashboard.jsx:552-564` | loop de `pnl_unrealized` por broker | «Ganancia no realizada» / capital del mes |
| `frontend/src/pages/HomeMobile.jsx:100, 214-231` | valor por unidad para el ranking de holdings | Home mobile, «Tus activos» |
| `frontend/src/pages/Insights.jsx:405, 424-457, 2016-2030` | valuación por posición para tortas y atribución | «Composición», «Qué te dio y qué te sacó» |
| `frontend/src/pages/FirstInsight.jsx:85, 116-145` | primer insight post-import | pantalla de bienvenida |
| `frontend/src/pages/Goals.jsx:64-85` | valor actual de la cartera para el objetivo | «Objetivos» |
| `frontend/src/pages/Events.jsx:150-158` | total de cartera para el % de impacto de un evento | «Novedades» / eventos |
| `frontend/src/components/MonthlySummary.jsx:96, 251-284` | `syncUnrealizedForAll` + recomputo mensual | «Resumen mensual» |
| `frontend/src/components/fundamentals/CarteraList.jsx:70, 116` | `valueEquityLot` para el listado holding-first | «Calidad de cartera» |
| `frontend/src/hooks/useMonthlyData.js:156, 229, 509` | `tcCedear` en el contexto + valor live por broker | curva de evolución |
| `frontend/src/components/SplitRatioBanner.jsx:1-149` | fetch `/positions/split-check` + POST `/adjust-ratio` | «Ajustar {TICKER} (×3)» / «1:N» para split inverso (l. 14) |
| `frontend/src/utils/assetClass.js:95` | meta de la clase | etiqueta **«CEDEARs»**, color `#8B7DFF`, en las tortas |
| `frontend/src/utils/tickers.js:606-614` | `ASSET_TYPE_META.cedear` | badge **«CEDEAR»** violeta en los 5 buscadores |
| `frontend/src/utils/assetSector.js:60-63, 165-178` | sector económico | «Composición por sector» (un CEDEAR de NVDA cuenta como semis) |
| `frontend/src/utils/bookComposition.js:56-58, 293-330` | composición del libro del asesor | «CEDEARs» vs «Acciones US» separadas |
| `backend/reporting/timeline.py:102-144` | `_position_value_usd` con `tc_cedear` | Reportes / línea de tiempo |
| `backend/reporting/builder.py:102-130` | `brokers_del_filtro` vía `broker_pair` | reporte por broker (incluye el sibling `· USD`) |
| `backend/ai/builders/insights.py:344-440` | contexto de la IA (`_price_is_ars`, `tc_cedear`) | Rendi AI / Análisis |
| `backend/ai/builders/dashboard.py:111-138`, `dashboard_brokers.py:37-53`, `dashboard_composition.py:29-45`, `dashboard_top_holdings.py:47-73`, `position.py:42-101` | packets de la IA | Rendi AI |
| `backend/ai/builders/profile_card.py:158-162`, `profile_summary.py:31-79` | perfil del inversor | «Tu perfil» |
| `backend/advisor_brief.py:145-172` | AUM por cliente con `cedear_rate=tc_mep` | brief diario del asesor |
| `backend/main.py:36922-36943` | `_advisor_positions_valued` | libro del asesor (AUM, motor estrella) |
| `backend/ledger_replay.py:195-280` | `valor_en(conn, uid, fecha)` — delega en el motor canónico | reconstrucción histórica / TWR |
| `backend/price_history.py:153-169` | `simbolos_de(conn, uid)` vía `build_price_symbols` | backfill de precios históricos |
| `backend/alerts_engine.py:38, 115, 210-218, 384` | riel `.BA`→ARS y ventana de mercado | Alertas de precio |
| `backend/main.py:11351, 18410-18440, 22848-22898, 25437` | payloads que exponen `asset_type` | varias vistas y el chat |
| `frontend/src/pages/blog/articles/FifoCedearsArgentina.jsx` | contenido público | nota «FIFO con CEDEARs» (marketing, no cálculo) |

---

### Dónde se persiste

| tabla.columna | qué guarda | dónde se crea | dónde se lee |
|---|---|---|---|
| `positions.asset_type` | `'CEDEAR'` / `STOCK` / `ETF` / `BOND` / `FUND` / `CRYPTO` / `FIAT` / `OTHER` / `''` | `ALTER TABLE` + backfill desde `import_normalized_tx` en `backend/main.py:995-1029`; `schema_pg.sql:1446, 1477` | todas las ramas de valuación (frontend y backend) |
| `positions.split_adjusted_through` | watermark `YYYY-MM-DD` de la última ex-date de split ya aplicada a ese lote | `backend/main.py:1031-1037`; `schema_pg.sql:1447, 1479` | `_applicable_splits` (`main.py:8730-8737`), `adjust-ratio` (`main.py:8949-8953`) |
| `positions.currency` | `'ARS'` / `'USD'` / `'USDT'` — la moneda del **costo** del lote; es lo que separa «CEDEAR comprado en pesos» de «CEDEAR comprado por MEP» | `main.py:1189-1193`, persister | `costInPesos` / `costInUsd` (`valuation.js:214, 324`), `_cost_in_usd` (`snapshots_job.py:200-205`) |
| `positions.price_override` | precio manual; **desactiva** la rama `.BA` del CEDEAR (rama 5 exige `price_override == null`) | `main.py:8232` | `valuation.js:687`, `snapshots_job.py:299` |
| `import_normalized_tx.asset_type` | el tipo tal como lo dio el parser — sobrevive al re-import y al borrado de la posición | `persister.py:213-218` | backfill de `positions.asset_type`, `ledger_replay.py:230-241`, watermarks de split |
| `import_normalized_tx.asset_symbol` vs `.asset_symbol_raw` | símbolo consolidado (sin la D/C de la pata dólar) vs el crudo del broker | `normalizer.py:449` | replay FIFO, watermarks |
| `brokers.parent_broker_id` + `brokers.currency` | identidad del par padre ARS ↔ sub-broker `· USD`; es lo que decide `.BA` sin depender del nombre | `_ensure_usd_sibling` | `broker_pair`, `byma_broker_names`, `_broker_name_sets`, `isArUsdBroker` |
| `asset_last_price` | último precio conocido, guardado con la **misma key** que valúa (`SYM.BA` para CEDEARs) | `snapshots_job.persist_last_prices` (l. 561-587) | `read_last_prices`, libro del asesor |

**El ratio del CEDEAR NO se persiste en ningún lado.** No hay columna `ratio`, `cedear_ratio` ni equivalente en `positions`, `operations`, `import_normalized_tx` ni `watchlist` [V] `sqlite3 backend/trading.db ".schema positions"` y `backend/schema_pg.sql:1440-1479`. El único ratio del sistema es la constante de código `CEDEAR_USD_RATIOS` (un elemento). El factor de split tampoco se persiste: se recalcula desde yfinance en cada request y sólo queda su **fecha** en `split_adjusted_through` [V] `backend/main.py:8938-8953`.

---

### ⚠️ Implementaciones divergentes

#### D-1. `ar_usd` en el snapshot: parent-aware para PEDIR el precio, por-nombre para USARLO

Dentro del mismo módulo conviven dos reglas distintas:

| | archivo:línea | regla | efecto |
|---|---|---|---|
| Qué símbolo se **pide** | `backend/snapshots_job.py:70-86` + `105-128` | parent-aware (`parent_broker_id` → currency ARS), con fallback por nombre | un sub-broker renombrado («Balanz cuenta 2») igual pide `AAPL.BA` |
| Qué símbolo se **lee al valuar** | `backend/snapshots_job.py:185` | `ar_usd = _is_ar_usd_subbroker(broker_name)` — **sólo el nombre**, regex `·\s*usd$` | ese mismo lote, si su `asset_type` no dice `CEDEAR`, cae al `else` y lee `prices.get(p['asset'])` (ticker pelado) → `None` → `value += real_cost` |

Resultado [I, inferido de leer las dos funciones y la cadena `build_price_symbols → prices → compute_broker_value_usd`]: en un sub-broker dólar **renombrado sin `· USD`** cuyo padre es ARS, y con un holding **sin `asset_type='CEDEAR'`** (una acción AR como PAMP/YPFD, o cualquier import que no etiqueta el tipo — IOL, IEB), el snapshot nocturno valúa **al costo, con P&L 0, en silencio**. La cobertura de precios no lo detecta porque `_has_price` usa `position_price_key` (l. 726-731), o sea la key parent-aware, que **sí** está en `prices`. El docstring de `_broker_name_sets` (l. 72-77) declara justamente lo contrario («ROBUSTO … no por el NOMBRE del broker»).

Quién ve qué: el **Dashboard live** (frontend) valúa bien (usa `isArUsdBroker`, parent-aware); la **curva de evolución / snapshot / libro del asesor / replay histórico** valúan al costo. Es la forma exacta del bug «el mismo lote vale distinto en mobile que en desktop» que el propio código documenta en `valuation.js:462-467`, pero entre live y snapshot.

#### D-2. Tres definiciones distintas de «sub-broker dólar de padre AR»

| implementación | archivo:línea | regla | fallback por nombre |
|---|---|---|---|
| Frontend `isArUsdBroker` | `frontend/src/utils/valuation.js:191-201` | registry: `currency ≠ ARS` **y** padre `ARS` | **sólo si el broker NO está en el registry** (`return /·\s*USD$/.test(...)`) |
| Backend `_broker_name_sets` | `backend/snapshots_job.py:78-86` | padre ARS | **siempre** (`elif _is_ar_usd_subbroker(...)`) |
| Backend `byma_broker_names` | `backend/behavioral.py:247-269` | currency ARS **o** padre ARS | **nunca** |

Además `behavioral.py` tiene una **cuarta** regla, laxa, para decidir la **moneda del costo** (no el precio): `_is_usd_subbroker` (l. 148-156) acepta `"· usd"`, `"·usd"`, `"- usd"` y `" usd"`. El propio comentario de `snapshots_job.py:62-66` explica por qué no se puede usar esa para el precio.

Caso concreto donde divergen [I]: un broker llamado `"Foo · USD"` **sin** `parent_broker_id` (sibling huérfano, padre borrado, o dato viejo) y presente en el registry del frontend → backend lo trata como BYMA (`.BA`), frontend NO (devuelve `false` en la l. 197). Cartera live y snapshot valúan el mismo lote con símbolos distintos.

#### D-3. `asset_type == 'CEDEAR'`: mayúsculas sí, mayúsculas no

| archivo:línea | comparación | ¿case-insensitive? |
|---|---|---|
| `backend/snapshots_job.py:126` | `(p.get('asset_type') or '').upper() == 'CEDEAR'` | **sí** |
| `backend/snapshots_job.py:299` | `if (asset_type == 'CEDEAR' or ar_usd)` (`asset_type = p.get('asset_type')`, l. 209, sin `.upper()`) | **no** |
| `backend/behavioral.py:178, 282` | `.upper() == "CEDEAR"` | sí |
| `backend/main.py:8913, 8987` | `.upper()` | sí |
| `backend/importing/persister.py:83` | `.upper()` | sí |
| `frontend/src/utils/valuation.js:87, 687` | `assetType === 'CEDEAR'` / `p.asset_type === 'CEDEAR'` | **no** |
| `frontend/src/utils/assetClass.js:200, 242` | `.toUpperCase()` | sí |
| `frontend/src/utils/insightsModel.js:457` | `position.asset_type === 'CEDEAR'` | **no** |

Que esto no es teórico lo dice el propio repo: `frontend/src/utils/assetClass.test.js:113-116` — *«Hay una fila real en la DB con asset_type='cedear' en minúscula»*. Para esa fila, en un broker USD: `position_price_key` **pide** `SYM.BA`, `compute_broker_value_usd` **no lo lee** (rama `else`, `prices.get('SYM')` → `None`) → al costo. Y en el frontend, `priceSymbol` no le pone `.BA` pero `classifyAsset` la pinta como CEDEAR en la torta: la torta y la valuación no están mirando el mismo activo.

#### D-4. De qué dólar sale `tc_cedear` — cuatro cascadas

| consumidor | archivo:línea | cascada |
|---|---|---|
| Frontend (todas las pantallas) | `frontend/src/contexts/CurrencyContext.jsx:47-54` | `medio` de: pref (`mep`\|`ccl`) → el otro → `blue` |
| Análisis / Reportes / IA (vía `currency_context`) | `backend/analysis_prep.py:41-47` | **MEP live** del caché (`_current_cedear_rate`, cascada `mep→ccl→cripto`) → `config.tc_mep` → `tc_blue` |
| Snapshot del cron | `backend/snapshots_job.py:715` | `tc_mep` que resuelve el job (fetch directo) → `_user_tc_cedear` (caché → `config.tc_mep` → `tc_blue`) |
| Packet de IA «insights» | `backend/ai/builders/insights.py:365-375` | **`config.tc_mep` a secas** → `tc_blue`. NO consulta el caché live |

O sea: el mismo usuario, en la misma carga de página, puede ver sus CEDEARs valuados al MEP live en el Dashboard y al `config.tc_mep` persistido en el texto que le escribe Rendi AI. El comentario de `analysis_prep.py:34-38` dice explícitamente que la razón de ser de `user_fx` es que «el backend (Análisis/snapshots/IA) no diverja del Dashboard» — y el builder de insights no la usa.

Adicional: en varias pantallas la rama de **broker ARS** divide por `tcValuacion` y no por `tcCedear`, aunque las dos variables se inicializan con la misma llamada a `pickFinancialRate` [V] `frontend/src/pages/Dashboard.jsx:326-329` (`valueUsd = (trust ? mktArs : realCost) / tcValuacion`), `frontend/src/pages/Insights.jsx:435-440`, `frontend/src/pages/AssetDetail.jsx:70-77`, contra `frontend/src/utils/valuation.js:650-663` que usa `cedearRate`. Hoy dan el mismo número; el día que se separen, se separan sólo esas pantallas. `Positions.jsx:1315-1322` documenta que este mismo desalineamiento ya produjo un total de US$ 56.582 contra filas que sumaban US$ 64.147.

#### D-5. Nueve implementaciones de «valuar un lote CEDEAR», con la misma condición copiada a mano

La condición `(p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker)) && !isCrypto(...) && !isFciSym(...) && p.price_override == null` está escrita, carácter por carácter, en:

| archivo:línea | pantalla |
|---|---|
| `frontend/src/utils/valuation.js:687` | motor canónico (`valuePositionLot`) |
| `frontend/src/utils/valuation.js:397` | `valueEquityLot` (**sin** el guard `!isCrypto`) |
| `frontend/src/pages/Positions.jsx:1282` | Cartera desktop |
| `frontend/src/pages/PositionsMobile.jsx:726` | Cartera mobile |
| `frontend/src/pages/PositionDetailMobile.jsx:152` | detalle mobile |
| `frontend/src/pages/AssetDetail.jsx:81` | ficha del activo |
| `frontend/src/pages/Dashboard.jsx:341` | Dashboard (insights) |
| `frontend/src/pages/Dashboard.jsx:552` | Dashboard (P&L no realizado) |
| `frontend/src/pages/HomeMobile.jsx:227` | Home mobile |
| `frontend/src/pages/FirstInsight.jsx:139-143` | primer insight |
| `backend/snapshots_job.py:299-301` | snapshot / asesor / replay |

El propio docstring de `valuePositionLot` lo reconoce: *«había CINCO implementaciones … Esta es la que va a serlo. Todavía NO la consume nadie más»* [V] `frontend/src/utils/valuation.js:497-506`. Hoy son más de cinco, y **ninguna pantalla de filas usa el motor canónico** — sólo los totales (`computeBrokerValue`). Diferencias reales entre copias:

- `valueEquityLot` (l. 397) **no** excluye la cripto de la rama BYMA; el resto sí. Una cripto en un sub-broker `· USD` se rutea a `BTC.BA` (inexistente) en «Calidad de cartera» y no en Cartera.
- `AssetDetail.valueLot` es la única que agrega `!isCrypto(p.asset)` en la rama pero usa `tcValuacion` para el cash ARS (l. 40) donde el canónico usa `cedearRate` (l. 634).

#### D-6. `Goals.jsx` arma su propia lista de símbolos

`buildPriceSymbols` existe justamente porque «cada pantalla que lo re-implementaba tenía un agujero distinto» [V] `frontend/src/utils/valuation.js:477-482`. `Goals.jsx:74-76` lo re-implementa igual:

```js
const usdtSyms = [...new Set(positions.filter(...).map(p => isArUsdBroker(p.broker) ? priceSymbol(p.asset, true, p.asset_type) : priceSymbol(p.asset, false, p.asset_type)))]
```

Le faltan los dos guards que `valuationPriceKey` sí tiene (`valuation.js:469-475`): (a) la **cripto** en un sub-broker `· USD` pide `BTC.BA`, que la valuación no lee → ese lote va al costo; (b) los lotes `costInPesos` en un broker USD no piden su `.BA`. La pantalla de Objetivos muestra un «valor actual» menor al de Cartera para esas carteras [I, inferido de comparar `Goals.jsx:74-76` contra `valuation.js:469-494`].

#### D-7. Cuatro universos de tickers CEDEAR, ninguno igual a otro

| universo | archivo:línea | tamaño | para qué |
|---|---|---|---|
| `CEDEARS_LIST` / `CEDEAR_TICKERS` | `frontend/src/utils/tickers.js:162-247, 427` | **168** símbolos | buscador, alta manual, clasificación de tortas, gate de fundamentals |
| `ai.trade_tickers.CEDEAR_TICKERS` | `backend/ai/trade_tickers.py:47-65` | **119** símbolos | Coach IA (registrar operación por chat), `advisor_groups._class_of` |
| `KNOWN_CD_TICKERS` | `backend/importing/tickers_cd.py:39-69` | 53 símbolos | proteger tickers que terminan en C/D de la consolidación de la pata dólar |
| `CEDEAR_USD_RATIOS` | `backend/main.py:7125-7127` | **1** (`BAC`) | el único con ratio numérico |

Hay UN test que sincroniza dos de ellas (`backend/tests/test_tickers_cd_sync.py`, frontend ↔ `KNOWN_CD_TICKERS`). Entre la lista del frontend y la de la IA no hay ninguno: un CEDEAR que existe en el buscador pero no en `ai/trade_tickers` no se puede registrar por chat, y `advisor_groups` lo clasifica «otro».

#### D-8. Detección de split: dos ramas de UI, una sola posible

`GET /api/positions/split-check` devuelve siempre `"evidence": "fecha"` — la variable se asigna literal y nunca se reasigna [V] `backend/main.py:9015` (`evidencia = "fecha"`) y `9033` (único uso). Pero el banner tiene toda una rama para `evidence === 'precio'`: un párrafo de advertencia y un bloque de confirmación distinto [V] `frontend/src/components/SplitRatioBanner.jsx:66-75, 119-125`. Es UI muerta desde que se desactivó la evidencia por precio (`_SPLIT_PRICE_EVIDENCE_ENABLED = False`, `backend/main.py:8765`).

#### Convergencias verificadas

- **`trustMktValue` / `_trust_mkt_value`**: mismas bandas `[0.02, 4]` renta fija y `[0.002, 50]` resto, mismo trato del override. [V] `frontend/src/utils/valuation.js:448-455` ≡ `backend/snapshots_job.py:42-53`.
- **La fórmula del ratio BAC** es idéntica en los cuatro sitios donde aparece: `precio_US × CCL ÷ ratio`. [V] `main.py:7832-7833`, `main.py:8027-8028`, `main.py:8124-8127`, `snapshots_job.py:503-504`.
- **`strip_cd_suffix`** es una sola implementación desde que `iol.py` delegó en ella. [V] `backend/importing/parsers/iol.py:185-197`.
- **Detección y escritura del split** comparten `_applicable_splits`, y el `UPDATE` es condicional sobre el watermark (`AND (split_adjusted_through IS NULL OR split_adjusted_through < ?)`), así que un doble POST es no-op. [V] `backend/main.py:8946-8956`.

---

### Zonas grises

1. **El «ratio» del título casi no existe en el código.** Lo único con nombre de ratio es `CEDEAR_USD_RATIOS` (un ticker). Todo lo demás que se llama «ratio» en la UI (`/adjust-ratio`, «cambio de ratio») es en realidad **el factor de split que reporta yfinance para el `.BA`**, que no es lo mismo: un cambio de ratio del CEDEAR y un split de la acción subyacente llegan a yfinance indistinguibles. El código lo trata como uno solo a propósito, pero el nombre engaña.

2. **`asset_type` es opcional y muchos parsers no lo llenan.** `guess_asset_type` nunca infiere CEDEAR [V] `backend/importing/normalizer.py:241`; IEB manda `""` explícito [V] `backend/importing/parsers/ieb.py:446`; IOL no trae tipo en Movimientos. Para todas esas cuentas, «esto es un CEDEAR» se deduce **sólo** de la moneda del broker o del sufijo `· USD` del sub-broker. Un CEDEAR importado de IOL a un broker USD raíz (sin padre AR) se valúa como acción US y nadie lo detecta.

3. **`cash_broker_for` consolida sólo si `asset_type == 'CEDEAR'`** [V] `backend/importing/persister.py:83`. Una **acción argentina** comprada por dólar-MEP (GGAL, PAMP, YPFD) NO se consolida: la tenencia se queda en el sibling `· USD`. El comentario dice que la excepción es para «las acciones del EXTERIOR» (l. 317-319), pero la condición no distingue exterior de local — distingue CEDEAR de todo lo demás. Con `asset_type` vacío (IOL/IEB), ni siquiera un CEDEAR se consolida.

4. **El re-import borra el watermark de split.** `_write_rebuilt` re-inserta las filas de `positions` sin `split_adjusted_through` [V] `backend/importing/rebuild.py:741-748` (el INSERT no la incluye). Los otros dos watermarks (foto de tenencia y movimiento corporate) se derivan read-time de `import_normalized_tx` justamente para sobrevivir al rebuild [V] `backend/main.py:8806-8808, 8828-8830`, pero el del ajuste manual no. Un usuario que ajustó a mano y después re-importa vuelve a ver el aviso de «Ajustar» — y si lo aprieta, multiplica de nuevo. La única defensa que queda es el filtro por `entry_date` (el lote reconstruido puede traer otra fecha).

5. **Código muerto en la detección por precio.** `_SPLIT_PRICE_EVIDENCE_ENABLED` (l. 8765), `_cached_ba_price` (l. 8768-8789) y `_splits_solo_excluidos_por_fecha` (l. 8791-8797) están definidos y **no se llaman desde ningún lado** [V] `grep -n` sobre `backend/main.py` devuelve sólo las líneas de definición. El comentario de 8741-8764 explica muy bien por qué se desactivó (el razonamiento estaba invertido), pero el código quedó, junto con la rama de UI del punto D-8.

6. **La banda `[0.002, 50]` del guard no ataja al CEDEAR.** El caso que el guard dice cubrir («un CEDEAR/bono priceado como la acción US», `valuation.js:424-426`) es exactamente un factor de 15-100×. Con un ratio de 20 o 30, el valor inflado queda **dentro** de la banda de 50× y pasa. Sólo los CEDEARs de ratio >50 (MELI ~30:1, AMZN, GOOGL) se atajan, y ni siquiera todos. El guard es la última red, no la primera. [I, inferido de `trustMktValue` l. 448-455 contra los ratios que el propio código cita en `valuation.js:143-144`].

7. **La contabilidad de `is_ar_market` del asesor no pasa por `stamp_byma`.** `main.py:36937-36939` reconstruye la condición a mano (`asset_type CEDEAR or broker in ars_names or broker in ar_usd_names`) en vez de llamar a `byma_broker_names`. Son dos reglas que hoy coinciden porque `_broker_name_sets` y `byma_broker_names` se parecen — salvo por el fallback por nombre (ver D-2).

8. **`counterfactual` de Behavioral descarta todas las ventas de brokers AR.** [V] `backend/behavioral.py:1408-1416`: `if _is_ars_broker(o.get("broker")): skipped_fx += 1; continue`. El filtro usa `_is_ars_broker` (heurística por **nombre**, lista `_AR_BROKER_HINTS` de 8 strings, l. 111), no `_price_is_ars` ni `_byma`. Una venta de CEDEAR en un broker AR fuera de esa lista (Santander, Galicia, Naranja X con otro nombre) **no** se descarta y se compara el precio de salida en pesos contra el precio US en dólares — exactamente lo que el docstring dice que el filtro existe para evitar.

9. **`price_override` apaga el ruteo `.BA` del CEDEAR.** Todas las ramas exigen `price_override == null` [V] `valuation.js:687`, `snapshots_job.py:299`. Con un override cargado, la posición cae al camino USD nativo y el override se interpreta **en dólares**, no en pesos. No hay nada en la UI que le diga al usuario en qué moneda se espera ese número para un CEDEAR — y el guard de override se respeta salvo en renta fija (`trustMktValue`, l. 451), así que un override en pesos sobre un CEDEAR multiplica la posición por ~1.500 sin que nada lo frene.

10. **`_is_ar_usd_subbroker` exige el carácter `·` (U+00B7)**, no un punto medio cualquiera ni un guión [V] `backend/snapshots_job.py:57`, `backend/behavioral.py:44`, `frontend/src/utils/valuation.js:200`. `_ensure_usd_sibling` es quien lo genera, pero el nombre es editable por el usuario. Un rename que cambie ese carácter (copiar/pegar desde otro lado, un `-` en vez de `·`) desactiva el fallback en los tres sitios a la vez, y sólo `parent_broker_id` salva la valuación — salvo en `snapshots_job.py:185`, que no lo mira (D-1).

11. **No encontrado:** ningún lugar del código que muestre al usuario el ratio de un CEDEAR, ni que derive el ratio implícito (`US × CCL ÷ BYMA`). El único texto de UI sobre ratios es el del banner de split (`SplitRatioBanner.jsx:14`, `×3` / `1:N`), que es el factor del split, no el ratio del certificado.

12. **No encontrado:** ninguna validación de que `CEDEAR_USD_RATIOS` siga vigente. Los ratios de CEDEAR cambian por acción societaria (que es justo lo que el split-check detecta), y ese dict es una constante hardcodeada sin test de frescura ni fecha de verificación más allá del comentario «Verificado 11/06/2026» (`main.py:7123`). Si BYMA cambia el ratio de BAC, el precio en pesos de esa posición queda mal por el factor del cambio, y el guard de 50× no lo ataja.
