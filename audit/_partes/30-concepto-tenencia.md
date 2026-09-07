## Tenencia / posición / holding

### Definición según el código

En Rendi, **una "posición" NO es "lo que tenés de un activo": es UN LOTE**. La tabla `positions` guarda una fila por *compra abierta* (lote FIFO), con su propia `quantity`, su propio `invested` (costo en moneda nativa), su propia `entry_date`, su propia `currency` y su propio `tc_compra`. Un mismo ticker comprado en tres tandas son **tres filas**. `[V]` `backend/schema_pg.sql:1431-1448` (DDL) y `backend/main.py:8186-8195` (el endpoint devuelve las filas crudas, ordenadas `broker, asset, entry_date, id` — sin agrupar).

La "tenencia" que ve el usuario (una fila por activo, con cantidad total y P&L) es una **vista calculada al vuelo en el frontend**, no un registro. El propio código lo dice: *"La fila agregada de Cartera es una VISTA (se calcula al vuelo), no un registro: editarla = aplicar una regla a cada lote"* `[V]` `backend/main.py:8334-8337`.

Cinco cosas más que el código define de forma **no estándar** y conviene tener presentes:

1. **El efectivo también es una fila de `positions`** (`is_cash=1`). Ahí `invested` **es el saldo de caja** (no un costo) y `quantity` queda en `0`/NULL. `[V]` `backend/main.py:9750-9791` (`_adjust_broker_cash` suma el delta sobre `positions.invested`), `backend/main.py:4100-4104` (al crear un broker se inserta la fila cash con `invested=0, quantity=0`).
2. **El costo de una tenencia es `invested + commissions`**, no `invested` solo. Está declarado como "la definición de la casa" en el frontend `[V]` `frontend/src/utils/valuation.js:549-553` y en el persister `[V]` `backend/importing/persister.py:594` (`cost_total = invested + fees`). **El motor canónico del backend NO la sigue** (ver Implementaciones divergentes).
3. **La moneda del costo la decide el LOTE, no la cuenta** (`positions.currency`). Un CEDEAR comprado por dólar-MEP vive en un broker ARS pero con `currency='USD'`, y su costo NO se divide por el MEP. `[V]` `frontend/src/utils/valuation.js:324-336` (`costInUsd`), `frontend/src/utils/valuation.js:214-217` (`costInPesos`), `backend/behavioral.py:195-224` (`_native_ccy`).
4. **La moneda del PRECIO es un eje distinto de la del costo.** Un CEDEAR cotiza `.BA` (pesos) aunque su costo esté en dólares. `[V]` `backend/behavioral.py:166-194` (`_price_is_ars`), `backend/behavioral.py:413-421` (el comentario "DOS ejes de moneda, distintos").
5. **La valuación tiene un techo duro** (`trustMktValue`): si el precio de mercado da un múltiplo absurdo del costo, la tenencia **se valúa al costo** y su P&L queda exactamente 0. Renta fija: banda `[0,02×, 4×]`. Resto: `[0,002×, 50×]`. `[V]` `frontend/src/utils/valuation.js:448-456` y su port Python `backend/behavioral.py:47-61` / `backend/snapshots_job.py:42-58`.

Además hay **tres tablas más** que son "tenencia" a los ojos del usuario pero no de `positions`: `plazos_fijos`, `futures_positions` y `archived_positions` (posiciones archivadas, serializadas a JSON). `[V]` `backend/schema_pg.sql:1382`, `:864`, `:528`.

Y hay **una segunda definición completa de tenencia que no lee `positions` en absoluto**: `ledger_replay.tenencia_en()`, que reconstruye `{(broker, activo): cantidad}` replayando `import_normalized_tx`. `[V]` `backend/ledger_replay.py:35-84`.

---

### Dónde se calcula

Ordenado: primero el motor canónico declarado, después sus ports, después las re-implementaciones por pantalla, después los escritores.

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `frontend/src/utils/valuation.js:543` | `valuePositionLot(p, ctx)` | **LA valuación de UN lote** (declarada canónica). 6 ramas: cash / lote-ARS-en-cuenta-USD / lote-USD-en-broker-ARS / broker-ARS / BYMA-en-broker-USD / USD nativo | `const realCost = (p.invested \|\| 0) + comm` ; `pnlUsd: o.valueUsd - o.investedUsd` | Fuente (canónica) |
| 2 | `frontend/src/utils/valuation.js:740` | `computeBrokerValue(...)` | La SUMA de `valuePositionLot` sobre los lotes del broker. Es el TOTAL del pie/hero | `const bpos = allPositions.filter(p => p.broker === broker.name)` ; `value += r.valueUsd` | Fuente |
| 3 | `frontend/src/utils/valuation.js:448` | `trustMktValue(mkt, realCost, assetType, hasOverride)` | Guard anti-distorsión: decide si se confía en el precio o se cae a costo | `return fixed ? (mult <= 4 && mult >= 0.02) : (mult <= 50 && mult >= 0.002)` | Fuente |
| 4 | `frontend/src/utils/valuation.js:293` | `pesoLotUsd(p, prices, tcCedear, costBasis)` | Lote en PESOS → USD por MEP. Costo y valor al mismo riel | `const investedUsd = realCost / costBasisRate(p, tcCedear, costBasis)` ; `const valueUsd = priceArs != null ? (priceArs * (p.quantity \|\| 0)) / tcCedear : investedUsdToday` | Fuente (helper) |
| 5 | `frontend/src/utils/valuation.js:338` | `usdLotValue(p, prices, cedearRate)` | Lote de costo USD (bono/ON/FCI-USD/CEDEAR-MEP). Costo YA en USD | `const investedUsd = (p.invested \|\| 0) + (p.commissions \|\| 0)` ; `const mktUsd = raw != null ? (priceIsArs ? raw / cedearRate : raw) : null` | Fuente (helper) |
| 6 | `frontend/src/utils/valuation.js:360` | `valueEquityLot(p, broker, prices, ...)` | 5ª implementación por-lote, para "Calidad de cartera" | `const invested = (p.invested \|\| 0) + (p.commissions \|\| 0)` ; `if (valueUsd == null \|\| !trustMktValue(valueUsd, guardCost, ...)) { valueUsd = guardCost; investedUsd = guardCost }` | Fuente (paralela) |
| 7 | `frontend/src/utils/valuation.js:469` | `valuationPriceKey(p, isArsBroker)` | La key de `prices` con la que la valuación LEE esta tenencia | `if (isArUsdBroker(p.broker) \|\| costInPesos(p)) return priceSymbol(p.asset, true, p.asset_type)` | Fuente |
| 8 | `frontend/src/utils/valuation.js:484` | `buildPriceSymbols(positions, brokers)` | Los símbolos a pedir a `/prices` para valuar. Debe espejar #7 | `if (p.is_cash \|\| p.asset === 'USDT' \|\| !known.has(p.broker)) continue` | Fuente |
| 9 | `backend/behavioral.py:391` | `_position_value_usd(p, prices, tc_blue, tc_cedear, honor_override)` | **Motor canónico del backend** (Análisis, IA, Reportes, Home). Doble eje de moneda | `invested_native = float(p.get("invested") or 0)` ; `mkt_usd = (value_native / rate_holdings) if (price_is_ars and rate_holdings > 0) else value_native` | Fuente (canónica backend) |
| 10 | `backend/snapshots_job.py:158` | `compute_broker_value_usd(...)` | **Port Python de `computeBrokerValue`**. Lo usan el cron de snapshots, el chat IA y el libro del asesor | `real_cost = (p.get('invested') or 0) + comm` ; `inv_usd = real_cost / cedear_rate if cedear_rate > 0 else 0` | Fuente (canónica snapshot) |
| 11 | `backend/snapshots_job.py:105` | `position_price_key(p, ars_names, ar_usd_names)` | SSoT del símbolo de precio en el backend | `wants_ba = (broker in ars_names or broker in ar_usd_names or (p.get('asset_type') or '').upper() == 'CEDEAR')` ; `return f"{asset}.BA" if wants_ba else asset` | Fuente |
| 12 | `backend/snapshots_job.py:623` | `take_snapshot_for_user(...)` | Valúa TODA la cartera y persiste `snapshots.total_value` + `holdings_json` (foto por activo) | `for b in brokers: bpos = [p for p in positions if p['broker'] == b['name']]` ; `by_asset[p['asset']] += rp['value']` | Fuente (persiste) |
| 13 | `backend/behavioral.py:247` | `byma_broker_names(brokers)` | Qué brokers valúan por `.BA` (parent-aware, no por nombre) | `parent = by_id.get(b.get("parent_broker_id"))` ; `if parent and (parent.get("currency") or "").strip().upper() == "ARS": out.add(name)` | Fuente |
| 14 | `backend/behavioral.py:225` | `stamp_positions_currency(positions, broker_ccy)` | Estampa `positions[].currency` desde la moneda del broker cuando la fila la tiene NULL | `p["currency"] = "ARS" if bc == "ARS" else "USD"` | Fuente (muta in-place) |
| 15 | `frontend/src/pages/Positions.jsx:1134` | `_buildAgg(asset, lots, ccy)` | **Arma la fila-tenencia** del desktop desde N lotes | `const totalQty = lots.reduce((s, x) => s + (x.quantity \|\| 0), 0)` ; `buy_price: (multiCcy \|\| !(totalQty > 0)) ? null : totalInv / totalQty` | Fuente (agregación UI) |
| 16 | `frontend/src/pages/Positions.jsx:1198` | `aggregateAndSort(arr, isARS, scopeKey, unified)` | Agrupa por `(asset, moneda)` — o solo por `asset` en la tarjeta de cuenta unificada | `const k = unified ? p.asset : \`${p.asset}::${ccy}\`` | Fuente (agregación UI) |
| 17 | `frontend/src/pages/Positions.jsx:1263` | `calcUSDT(p)` | Fila de un broker USD (desktop) | `const realCost = ((p.invested \|\| 0) + (p.commissions \|\| 0)) * f` ; `const value = price * p.quantity * f` | Consumidor (re-implementa) |
| 18 | `frontend/src/pages/Positions.jsx:1321` | `calcARS(p)` | Fila de un broker ARS (desktop) | `const valueArs = priceArs * p.quantity` ; `const valueUsd = valueArs / tcCedear` | Consumidor (re-implementa) |
| 19 | `frontend/src/utils/valuation.js:905` / `:925` | `sumRowUSDT(cs)` / `sumRowARS(cs)` | Suman los lotes de una fila agregada (para que las filas cierren con el pie) | `const value = withValue.reduce((s, c) => s + c.value, 0)` ; `pnlPct: costWithValue > 0 && pnl != null ? pnl / costWithValue : 0` | Fuente (helper UI) |
| 20 | `frontend/src/utils/valuation.js:868` | `avgCostUsdPerUnit(p, rate, costBasis, isArsBroker)` | Precio promedio USD por unidad, ruteado POR LOTE | `cost += costIsPesos ? inv / costBasisRate(l, rate, costBasis) : inv` ; `return cost > 0 ? cost / qty : null` | Fuente (helper UI) |
| 21 | `frontend/src/pages/Positions.jsx:1248` | `routedInvUsd(p, rate)` | Costo USD de la fila, sumando lote por lote (modo `purchase`) | `const lots = p._lots` | Consumidor |
| 22 | `frontend/src/pages/Positions.jsx:1502` | `valuePos(p)` | Shape unificado para la zona Renta Fija (cross-broker) y la fila multi-moneda | `const invUsd = c.invUsd ?? routedInvUsd(p, tcValuacion)` | Consumidor |
| 23 | `frontend/src/pages/PositionsMobile.jsx:653` | `enriched = useMemo(...)` | **Toda la valuación por-lote del mobile**, re-implementada inline | `const invested = cashInvested + (p.commissions \|\| 0)` ; `let investedUsd = isAR && costInUsd(p) ? invested : isAR ? invested / tcValuacion : costInPesos(p) ? invested / tcCedear : invested` | Consumidor (re-implementa) |
| 24 | `frontend/src/pages/AssetDetail.jsx:34` | `valueLot(p, {...})` | Ficha del activo (desktop) — 6ª implementación por-lote | `const invested = cashInvested + (p.commissions \|\| 0)` ; `const valueUsd = trustMktValue(mkt, guardCost, ...) ? mkt : investedUsd` | Consumidor (re-implementa) |
| 25 | `frontend/src/pages/PositionDetailMobile.jsx:101` | (inline en el componente) | Detalle de una tenencia en mobile — 7ª implementación | `const invested = p.invested \|\| 0` ← **sin comisiones** | Consumidor (re-implementa) |
| 26 | `frontend/src/pages/Dashboard.jsx:302` | `positionsForInsight = useMemo(...)` | Valúa cada lote para la torta de composición + insights | `const realCost = (p.invested \|\| 0) + (p.commissions \|\| 0)` ; `valueUsd = (trust ? mktArs : realCost) / tcValuacion` | Consumidor (re-implementa) |
| 27 | `frontend/src/pages/Insights.jsx:421` | `holdingValueUsd(p)` | Valor USD de UNA tenencia para atribución/torta de Análisis | `return (mktArs != null && trustMktValue(mktArs, realCost, ...)) ? mktArs / tcValuacion : realCost / tcValuacion` | Consumidor (re-implementa) |
| 28 | `frontend/src/pages/HomeMobile.jsx:111` | (inline) | Totales por broker en el Home mobile | `brokers.map(b => ({ ...b, ...computeBrokerValue(positions, prices, b, tcValuacion, tcCedear, tcCripto, costBasis) }))` | Consumidor |
| 29 | `frontend/src/pages/FirstInsight.jsx:92` | (inline) | Primer insight post-onboarding | `const r = computeBrokerValue(positions, prices, b, tcValuacion, tcCedear, tcCripto, costBasis)` | Consumidor |
| 30 | `frontend/src/components/fundamentals/CarteraList.jsx:116` | (inline en `useMemo`) | Lista holding-first de "Calidad de cartera": agrupa por **base canónica** del ticker (alias de especie) | `const base = onBA ? cedearEspecieBase(p.asset) : baseTicker(p.asset)` ; `h.valueUsd += valueUsd \|\| 0` | Consumidor |
| 31 | `frontend/src/components/fundamentals/DetailPortfolioBlocks.jsx:144` | (inline) | Bloque "tu posición" de la ficha fundamentals | `for (const { p, broker } of lots) valueUsd += valueEquityLot(p, broker, prices, tc, tc, costBasis).valueUsd` | Consumidor |
| 32 | `frontend/src/utils/assetClass.js:281` | `computeClassBreakdown(positions, brokers, extraSlices, ops)` | Torta por clase de activo. **Espera `p.value_usd` ya calculado por el caller** | `const value = p?.value_usd` ; `if (value == null \|\| !(value > 0)) continue` | Consumidor |
| 33 | `frontend/src/hooks/useMonthlyData.js:509` | (inline) | Valor "hoy" de la serie mensual | `const r = computeBrokerValue(context.positions, context.prices \|\| {}, brokerObj, ...)` | Consumidor |
| 34 | `frontend/src/components/MonthlySummary.jsx:284` | (inline) | Cierre mensual | `const result = computeBrokerValue(pos, pricesData, b, tc, tcCedear, tcCripto)` | Consumidor |
| 35 | `frontend/src/hooks/usePfRollup.js:9` + `pfUsd` | `usePfRollup` / `pfUsd(totals, tc)` | Plazos fijos → USD, para sumarlos al patrimonio del hero | `const valueUsd = (totals?.USD?.valor \|\| 0) + (totals?.ARS?.valor \|\| 0) / tc` | Fuente (otra tabla) |
| 36 | `backend/main.py:22818` | `_valuate_positions_for_chat(conn, uid)` | Valúa lote por lote y **agrupa por `(broker, asset)`** → un "holding" por activo-broker para la IA | `r = compute_broker_value_usd([p], prices, bccy, tc_blue, broker_name=p['broker'], cedear_rate=tc_cedear)` ; `h["quantity"] = (h["quantity"] or 0) + (p.get('quantity') or 0)` | Fuente (IA) |
| 37 | `backend/main.py:36844` | `_advisor_positions_valued(conn, ids, tc_blue, tc_mep, stats)` | Valúa las tenencias de TODOS los clientes del asesor. **Excluye las que no tienen precio** | `has_price = (p.get("price_override") is not None or prices.get(position_price_key(...)) is not None)` ; `if not has_price: skipped += 1 ... continue` | Fuente (asesor) |
| 38 | `backend/ai/builders/dashboard_top_holdings.py:34` | `holding_weights(conn, user_id)` | Mapa ticker → % de cartera, **agregando por ticker cross-broker** | `by_ticker[t] = by_ticker.get(t, 0.0) + v` ; `if invested <= 0 or qty <= 0: continue` | Fuente (IA) |
| 39 | `backend/ai/builders/dashboard_top_holdings.py:67` | `build(conn, user_id)` | Top-8 holdings **por LOTE** (no agregado por ticker) | `enriched.sort(key=lambda x: x["value_usd"], reverse=True)` ; `top = enriched[:8]` | Consumidor (IA) |
| 40 | `backend/ai/builders/position.py:40` | `build(...)` | Ficha de UNA tenencia para la IA: suma los lotes del ticker | `qty = sum(float(p.get("quantity") or 0) for p in positions)` ; `weight_pct = (current_value_usd / total_value * 100)` ← denominador a **costo** | Consumidor (IA) |
| 41 | `backend/ai/builders/dashboard.py:49` | `_compute_pnl_pct_for_position(p, prices, ...)` | % P&L de una tenencia para la IA | `return (value_usd - invested_usd) / invested_usd` con `invested_usd = _position_value_usd(p, {}, ..., honor_override=False)` | Consumidor (IA) |
| 42 | `backend/reporting/timeline.py:96` | `_fetch_positions_for_concentration(...)` | Concentración/top-holdings del reporte de período | `v = _position_value_usd(p, prices, tc_blue, tc_cedear)` ; `out.append({"asset": r["asset"], "value_usd": v, "is_cash": bool(r["is_cash"])})` | Consumidor |
| 43 | `backend/main.py:32635` | `_portfolio_snapshot_summary(...)` | KPIs de Reportes: `positions_count`, `brokers_count`, `top_holdings`, `cash_value` | `SELECT COUNT(*) ... WHERE is_cash=0 AND COALESCE(quantity,0) > 0` ; `COALESCE(p.invested,0) / (CASE WHEN UPPER(COALESCE(br.currency,''))='ARS' THEN ? ELSE 1 END) AS invested_usd` | Consumidor |
| 44 | `backend/home/briefing.py:39` | `_user_holdings(conn, uid)` | Holdings consolidados por activo para el Home | `SELECT asset, SUM(quantity) AS qty, SUM(invested) AS invested FROM positions WHERE user_id=? AND is_cash=0 GROUP BY asset HAVING SUM(quantity) > 0` | Consumidor |
| 45 | `backend/advisor_groups.py:200` | (inline en el perfilado de clientes) | Tenencias de los clientes del asesor; cae a costo si el motor no las valuó | `cost = float(r["invested"] or 0) + float(r["commissions"] or 0)` ; `val = cost / tc_mep if (r["bc"] == "ARS" and tc_mep) else cost` | Consumidor |
| 46 | `backend/ledger_replay.py:35` | `tenencia_en(conn, uid, fecha)` | **Tenencia histórica reconstruida del ledger** (NO de `positions`) | `pos[k] = pos.get(k, 0.0) + (q if r["operation_type"] == OP_BUY else -q)` ; `return {k: v for k, v in pos.items() if v > 1e-9}` | Fuente (paralela) |
| 47 | `backend/ledger_replay.py:136` | `verificar_contra_hoy(conn, uid, tolerancia)` | Contrasta el replay contra `positions` de hoy | `SELECT broker, asset, SUM(quantity) q FROM positions WHERE user_id=? AND COALESCE(is_cash,0)=0 GROUP BY broker, asset` | Consumidor |
| 48 | `backend/importing/rebuild.py:232` | `_replay_asset(events, broker_currency, ...)` | **El motor FIFO**: reconstruye los lotes abiertos de un (broker, activo) desde el ledger | `lots.append({"qty": qty, "invested": invested, "buy_price": unit if unit > 0 else None, ...})` ; `_same = [l for l in lots if (l["currency"] or currency) == currency]` | Fuente (escritor) |
| 49 | `backend/importing/tenencia.py:327` | `compute_reconcile(current_qty_by_asset, snapshot, ...)` | Concilia la FOTO del broker contra la tenencia de Rendi, por activo | `gap = h.quantity - rq` ; `if abs(gap) <= tolerancia_qty(rq, h.quantity, ...)` → matched ; `elif gap > 0` → to_seed ; `else` → over | Fuente (escritor) |
| 50 | `backend/importing/tenencia.py:271` | `tolerancia_qty(rendi_qty, foto_qty, rel, abs_min)` | Umbral de "hay algo que decidir" en la conciliación | `return max(abs_min, rel * min(abs(rendi_qty or 0.0), abs(foto_qty or 0.0)))` | Fuente |
| 51 | `backend/main.py:10587` | `_amortize_position_fifo(...)` | Amortización de bono: baja `quantity` e `invested` proporcionalmente | `ratio = take / lot_qty` ; `new_invested = (lot['invested'] or 0) * (1 - ratio)` | Escritor |
| 52 | `backend/main.py:11147` | `sell_position_fifo(data, uid)` | Venta FIFO: consume lotes en orden `entry_date, id`, borra o prorratea | `new_invested = round((p["invested"] or 0) * remaining_ratio, 6)` ; `if take >= pos_qty - 1e-9: DELETE FROM positions` | Escritor |
| 53 | `backend/main.py:8877` | `adjust_position_ratio(pid, uid)` | Split de CEDEAR: `quantity *= F`, `buy_price /= F`, `invested` intacto | `new_qty = float(row["quantity"] or 0) * combined` ; `new_buy = (float(row["buy_price"]) / combined)` | Escritor |
| 54 | `backend/importing/persister.py:563` | `_persist_buy(...)` | Compra importada → nueva fila `positions` + débito de caja | `invested = float(tx.gross_amount) if tx.gross_amount is not None else (unit * qty)` ; `cost_total = invested + fees` | Escritor |
| 55 | `backend/main.py:8206` | `_insert_manual_position(conn, uid, p, meta_out)` | Alta manual de tenencia + débito de caja + autodepósito si no alcanza | `cost = invested if invested is not None else (buy_price or 0) * (quantity or 0)` ; `return (cost or 0) + (commissions or 0)` (`_manual_position_cost`, `backend/main.py:8198`) | Escritor |
| 56 | `backend/main.py:29551` | `_tenencia_apply_override(...)` | Modo OVERRIDE: la foto PISA — reduce/elimina tenencias que Rendi tiene de más | guardas: `_is_safe_to_rebuild`, `sibling_assets`, cap 50% | Escritor |
| 57 | `backend/main.py:31129` | `_wallbit_reconcile_positions(conn, uid, holdings, cash_usd)` | Concilia la foto de Wallbit contra el par de brokers | `SELECT asset, SUM(quantity) q, SUM(invested) inv FROM positions WHERE user_id=? AND is_cash=0 AND broker IN (...) GROUP BY asset` | Escritor |
| 58 | `backend/main.py:31786` | `_positions_in_section(conn, uid, cat, ccy)` | Qué tenencias caen en una sección de renta fija (para archivar) | `sec = _sections.position_section(r["asset_type"], r["asset"], r["currency"])` | Consumidor |
| 59 | `backend/importing/sections.py:42` | `position_section(asset_type, symbol, currency)` | Clasifica una tenencia en (BONO/LETRA/FCI, USD/ARS) | `if sym and letra_maturity(sym) is not None: return (CATEGORY_LETRA, ccy)` | Fuente |
| 60 | `backend/importing/invariantes.py:114` | `check_costo_no_positivo(conn, uid)` | Invariante: no puede haber tenencia con `invested <= 0` | `WHERE p.is_cash=0 AND COALESCE(p.quantity,0)>0 AND COALESCE(p.invested,0)<=0` | Verificador |
| 61 | `backend/importing/invariantes.py:52` | `check_moneda_posicion_vs_broker` | Invariante: lote ARS dentro de un broker USD | `AND UPPER(COALESCE(p.currency,''))='ARS' AND UPPER(COALESCE(b.currency,'')) IN ('USD','USDT')` | Verificador |
| 62 | `backend/main.py:8306` | `_group_lots(conn, uid, broker, asset, currency)` | Los lotes del "grupo" con el MISMO criterio que la fila agregada del front | `WHERE user_id=? AND broker=? AND asset=? AND is_cash=0` + `AND UPPER(COALESCE(currency,''))=?` | Fuente |

---

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `frontend/src/pages/Positions.jsx:1587` | Hero "Tu cartera hoy" (desktop) — suma `computeBrokerValue` por broker | **Cartera → Posiciones**: "Valor", "Invertido", "Ganancia" |
| `frontend/src/pages/Positions.jsx:1383` / `:1389` | Fila de la tabla (`calcRowUSDT` / `calcRowARS`) | Columnas **Cantidad / Precio prom. / Precio actual / Invertido / Valor / P&L / Var. día** |
| `frontend/src/pages/Positions.jsx:1420` | `calcRowCuenta` — fila de la tarjeta de CUENTA (padre + sub-broker `· USD`) | Tarjeta unificada de la cuenta (el activo comprado en pesos y en MEP = **una sola fila**) |
| `frontend/src/components/RentaFijaSections.jsx:209` | Zona **Renta Fija** cross-broker (Bonos/Letras/FCI × USD/ARS) | "Bonos USD", "Letras ARS", … con su total por sección |
| `frontend/src/pages/PositionsMobile.jsx:653` | Lista de tenencias en mobile | **Cartera** (mobile) |
| `frontend/src/pages/PositionDetailMobile.jsx:101` | Detalle de una tenencia (mobile) | Ficha del lote/posición |
| `frontend/src/pages/AssetDetail.jsx:34` | Ficha del activo (desktop) | **/activo/:ticker** — "Tu posición", lotes, P&L |
| `frontend/src/pages/Dashboard.jsx:211` | Totales por broker | **Dashboard** — hero, curva, "por cuenta" |
| `frontend/src/pages/Dashboard.jsx:419` | `computeClassBreakdown(positionsForComposition, ...)` | **Dashboard → Distribución** (torta por tipo y por sector) |
| `frontend/src/pages/Insights.jsx:411` | Torta por broker | **Análisis** — "Dónde está tu plata" |
| `frontend/src/pages/Insights.jsx:421` | `holdingValueUsd` → `assetPieData`, buckets, snapshot IA | **Análisis** — concentración/atribución por activo |
| `frontend/src/pages/HomeMobile.jsx:111` | Totales | **Home** (mobile) |
| `frontend/src/pages/Goals.jsx:82` | Valor actual del portfolio | **Objetivos** — progreso hacia la meta |
| `frontend/src/pages/Events.jsx:155` / `:167` | Peso de la tenencia afectada por un evento | **Novedades / Eventos** — "afecta X% de tu cartera" |
| `frontend/src/pages/FirstInsight.jsx:92` | Primer insight | Onboarding |
| `frontend/src/components/fundamentals/CarteraList.jsx:116` | Lista holding-first | **Calidad de cartera** |
| `frontend/src/components/fundamentals/DetailPortfolioBlocks.jsx:144` | Bloque de posición | **Calidad de cartera → ficha** |
| `frontend/src/components/advisor/BookComposition.jsx:82` | `computeClassBreakdown(rows, ...)` sobre `_advisor_positions_valued` | **Asesor → Libro → Composición** |
| `frontend/src/components/plan/ExportCsvButton.jsx` | Descarga `/api/export/positions.csv` | Botón "Exportar" |
| `backend/main.py:13384` (`/api/export/positions.csv`) | CSV de tenencias — **solo costo, sin valor de mercado** | Columnas "Activo / Broker / Es cash / Cantidad / Costo invertido / Comisiones / Fecha compra / TC compra (ARS) / Precio override" |
| `backend/main.py:8186` (`GET /api/positions`) | El endpoint que alimenta a TODO el frontend | — (payload crudo, lote por lote) |
| `backend/main.py:32635` → `/api/reports/...` | KPIs del reporte | **Reportes** — "N posiciones en M brokers", "Top holdings" |
| `backend/reporting/timeline.py:96` | Concentración del período | **Reportes → detectores** (`CONCENTRATION_RISK`) |
| `backend/home/briefing.py:160` (`/api/home/personal`) | Cards "Lo que te afecta" | **Home** — "AAPL subió hoy" |
| `backend/ai/builders/dashboard_top_holdings.py:67` | Packet `dashboard.top_holdings` | Contexto de **Rendi AI** |
| `backend/ai/builders/position.py:40` | Packet de una posición | **Rendi AI** — "¿cómo viene MELI?" |
| `backend/main.py:22818` → `_enrich_chat_snapshot_valuation` | Snapshot autoritativo del chat | **Rendi AI** (chat) |
| `backend/alerts_engine.py:77` | Símbolos a monitorear | **Alertas** de precio |
| `backend/price_history.py:166` | Símbolos a backfillear | Cron de historial |
| `backend/advisor_brief.py:103` | Tenencias de los clientes | **Brief del asesor** (email) |
| `backend/advisor_groups.py:200` | Perfil por cliente | **Asesor → Clientes** |
| `backend/main.py:8967` (`/api/positions/split-check`) | Lotes con split pendiente | Banner **"Ajustar split"** (`SplitRatioBanner.jsx`) |
| `backend/main.py:31801` (`/api/sections/archived`) | Secciones archivadas | Botón **"Restaurar"** en Renta Fija |

---

### Dónde se persiste

**Tabla principal: `positions`** — `[V]` `backend/schema_pg.sql:1431-1448`, y el DDL SQLite en `backend/main.py:940-952` + migraciones sucesivas (`entry_date`, `commissions`, `currency`, `asset_type`, `split_adjusted_through`, `undo_meta_json`).

| columna | qué guarda REALMENTE |
|---|---|
| `id` | PK del **lote** |
| `user_id`, `broker` | dueño y cuenta. `broker` es un **string**, no FK — el vínculo es por NOMBRE `[V]` `backend/main.py:4115` ("Tablas cuyo vínculo con el broker es por NOMBRE (string), NO por broker_id") |
| `asset` | ticker crudo, tal como lo dejó el parser |
| `is_cash` | `1` → la fila es **saldo de caja**, no una tenencia |
| `quantity` | nominales del lote. **NULL/0 en las filas cash** |
| `invested` | costo bruto **en moneda nativa del lote**. En una fila cash: **el saldo** |
| `commissions` | comisiones de compra. Parte del costo económico (`invested + commissions`) en el frontend; **ignoradas por `_position_value_usd`** |
| `buy_price` | precio unitario de compra (informativo; el costo canónico es `invested`) |
| `currency` | moneda del **costo** (`'ARS'`/`'USD'`) — decide FIFO, agrupación y conversión |
| `tc_compra` | dólar de la compra. Solo se usa en modo "Costo en dólares → dólar de la compra" `[V]` `frontend/src/utils/valuation.js:263-271` |
| `price_override` | precio manual. Gana sobre el precio live |
| `asset_type` | `CEDEAR`/`BOND`/`FUND`/… — decide ruteo `.BA` y banda del guard |
| `entry_date` | fecha de compra → **el orden del FIFO** |
| `split_adjusted_through` | watermark de splits ya aplicados (idempotencia) |
| `notes` | notas; también CONTRATO: el prefijo `"Tenencia — apertura"` marca los lotes semilla de una foto `[V]` `backend/importing/tenencia.py:38` |
| `undo_meta_json` | qué debitó el alta (para revertirla exacto) `[V]` `backend/main.py:8265` |

**Tablas satélite:**

- `archived_positions` (`section`, `label`, `payload` JSON, `count`) — borrado reversible de una sección entera de renta fija. `[V]` `backend/schema_pg.sql:528`, `backend/main.py:31815-31848` (archivar) y `:31854-31885` (restaurar, **re-insertando el id original**).
- `snapshots.holdings_json` — **foto persistida de la tenencia valuada por activo** (`[{asset, value_usd}]`), escrita por el cron. `[V]` `backend/snapshots_job.py:763-764`.
- `futures_positions` (`side`, `quantity`, `entry_price`, `leverage`, `margin_usd`, `liquidation_price`, `closed_at`) — posiciones de futuros, **fuera** de todo el motor de valuación. `[V]` `backend/schema_pg.sql:864-888`.
- `plazos_fijos` — plazos fijos, **fuera** de `positions`. `[V]` `backend/schema_pg.sql:1382`.
- `import_normalized_tx` (BUY/SELL) — la fuente de la que `rebuild`/`ledger_replay` **re-derivan** la tenencia. `[V]` `backend/schema_pg.sql:1020`, `backend/importing/rebuild.py:533`.
- `import_op_links` (`position_id`) — liga cada lote a la fila del archivo que lo creó, para revertir. `[V]` `backend/importing/rebuild.py:754`.

**Lo que NO se persiste:** la fila-tenencia agregada (una por activo), el valor de mercado por lote, el P&L no realizado por lote y el peso `%`. Todo eso se calcula al vuelo en cada render / cada request. La única materialización es `snapshots.holdings_json`, y es diaria y global (no por broker ni por lote).

---

### ⚠️ Implementaciones divergentes

**NO hay una sola implementación.** El propio código lo declara: *"había CINCO implementaciones de la valuación por lote (computeBrokerValue, valueEquityLot, AssetDetail.valueLot, PositionDetailMobile y PositionsMobile) y ninguna era 'la buena a la que volver'"* `[V]` `frontend/src/utils/valuation.js:503-509`. Y sigue: *"Esta es la que va a serlo. **Todavía NO la consume nadie más**"*.

**D-0 — `valuePositionLot` es la canónica y nadie la usa.** `[V]` Verificado por grep: los únicos consumidores de `valuePositionLot` fuera de `valuation.js` son `frontend/src/utils/valuation.test.js`. `computeBrokerValue` (`valuation.js:740`) la llama; nada más. Las 7 pantallas de la tabla anterior (#17, #18, #23, #24, #25, #26, #27) siguen con su copia.

**D-1 — Las comisiones son costo en 8 lugares y no lo son en 2.**

| implementación | costo del lote |
|---|---|
| `frontend/src/utils/valuation.js:549-553` (`valuePositionLot`) | `(p.invested \|\| 0) + comm` |
| `frontend/src/utils/valuation.js:339` (`usdLotValue`) | `(p.invested \|\| 0) + (p.commissions \|\| 0)` |
| `frontend/src/utils/valuation.js:294` (`pesoLotUsd`) | `(p.invested \|\| 0) + (p.commissions \|\| 0)` |
| `frontend/src/pages/Positions.jsx:1300` (`calcUSDT`) | `((p.invested \|\| 0) + (p.commissions \|\| 0)) * f` |
| `frontend/src/pages/PositionsMobile.jsx:663` | `cashInvested + (p.commissions \|\| 0)` |
| `frontend/src/pages/AssetDetail.jsx:47` | `cashInvested + (p.commissions \|\| 0)` |
| `backend/snapshots_job.py:207-208` | `(p.get('invested') or 0) + comm` |
| **`backend/behavioral.py:426`** (`_position_value_usd`) | **`float(p.get("invested") or 0)`** ← sin comisiones |
| **`frontend/src/pages/PositionDetailMobile.jsx:101`** | **`p.invested \|\| 0`** ← sin comisiones (en las ramas `isAR`, `CEDEAR/·USD` y `else`) |

Quién ve cuál: la **misma tenencia** tiene un costo (y por lo tanto un P&L y un %) en la Cartera y otro en el **detalle mobile** de esa tenencia, y otro más en **Análisis / Rendi AI / Reportes / Home / Brief del asesor** (todo lo que pasa por `_position_value_usd`). En un lote con comisión no nula, `_position_value_usd` reporta un costo **más bajo** → un P&L **más alto**. `[I]` La magnitud es exactamente la comisión de compra; se infiere de comparar las dos expresiones citadas.

**D-2 — El guard anti-distorsión no corre en la misma rama en todas las copias.** En `valuePositionLot` la rama 2 (lote en pesos alojado en cuenta USD) aplica `trustMktValue`:

- `[V]` `frontend/src/utils/valuation.js:578-579`: `const trustArs = mktArs != null && trustMktValue(mktArs, realCost, p.asset_type, p.price_override != null)`

En la fila del desktop, esa misma rama **no lo aplica**, y está declarado como intencional:

- `[V]` `frontend/src/pages/Positions.jsx:1267-1279`: *"No hay guard en esta rama → sin flip"* — `const value = (priceArs * p.quantity) / tcCedear` sin `trustMktValue`.

Quién ve cuál: la **fila** de un lote `currency='ARS'` en una cuenta USD con un precio absurdo (bono per-100 ×100) muestra el valor inflado, mientras el **pie del broker** (que sale de `computeBrokerValue`) lo clampea a costo. Las dos cifras están en la misma pantalla. `Insights.jsx:447-449` y `Dashboard.jsx:333-340` **sí** clampean esa rama, con comentarios que dicen que se agregó justamente por ese síntoma ("689% de la cartera").

**D-3 — `snapshots_job.compute_broker_value_usd` no tiene la rama "lote en pesos dentro de un broker USD".** El JS tiene 6 ramas; el port Python tiene, en el brazo `else` (broker USD), solo cash / CEDEAR-o-`·USD` / genérico. `[V]` `backend/snapshots_job.py:284-306` — no hay ningún chequeo de `currency == 'ARS'` ahí (el helper `_cost_in_usd` en `:199-204` solo se usa en el brazo ARS). `[I]` Consecuencia: un lote con `currency='ARS'` alojado en un broker USD (el caso "IOL sin sibling" que el frontend nombra explícitamente) entra al snapshot con su **costo en pesos contado como dólares**, ~MEP× inflado, mientras el Dashboard lo muestra bien. Se infiere comparando `valuation.js:576-598` (rama 2) contra el `else` de `snapshots_job.py`.

**D-4 — Tres definiciones de "cuál es el precio de esta tenencia".**

| implementación | criterio para `.BA` |
|---|---|
| `frontend/src/utils/valuation.js:469` (`valuationPriceKey`) | cripto → spot; `isArsBroker` \| `isArUsdBroker` (parent-aware) \| `costInPesos` → `.BA`; `asset_type==='CEDEAR'` vía `priceSymbol` |
| `backend/snapshots_job.py:105` (`position_price_key`) | FCI → as-is; cripto → spot; `broker in ars_names \| ar_usd_names \| asset_type=='CEDEAR'` → `.BA`. **No mira `currency`** |
| `backend/behavioral.py:166` (`_price_is_ars`) | cripto → False; `asset_type=='CEDEAR'` → True; `_byma` estampado; si no: `_is_ar_usd_subbroker` \| `_is_ars_broker` (**heurística por NOMBRE**) \| `currency=='ARS'` |

`_is_ars_broker` decide por substrings del nombre del broker (`_AR_BROKER_HINTS`), con el aviso explícito de que la lista *"NO cubre todos los brokers AR (ej. 'Santander', 'Galicia', 'PPI', 'Mercado Pago')"* `[V]` `backend/behavioral.py:229-234`. El mitigante es `stamp_byma` / `stamp_positions_currency`, que hay que llamar **antes** de valuar — y no todos los callers lo hacen (`backend/reporting/timeline.py:126-146` llama a `_position_value_usd` con el `currency` que viene del JOIN a `brokers`, sin `stamp_byma`).

**D-5 — Dos definiciones de "top holdings", con unidades distintas.**

- `[V]` `backend/main.py:32810-32821` (`_portfolio_snapshot_summary`, Reportes): ordena por **costo** (`invested`), no por valor de mercado, con la conversión hecha en SQL: `COALESCE(p.invested,0) / (CASE WHEN UPPER(COALESCE(br.currency,''))='ARS' THEN ? ELSE 1 END)`. Además es **por LOTE** (no agrega por ticker).
- `[V]` `backend/ai/builders/dashboard_top_holdings.py:123-124` (Rendi AI): ordena por **valor de mercado** (`value_usd`), también **por lote**.
- `[V]` `backend/ai/builders/dashboard_top_holdings.py:34-64` (`holding_weights`): **sí** agrega por ticker.

O sea: el "Top holdings" de Reportes y el de la IA pueden dar rankings distintos para la misma cartera, y los dos pueden mostrar el mismo ticker dos veces si está comprado en dos tandas.

**D-6 — Dos definiciones de "cuántas posiciones tenés".**

- `[V]` `backend/main.py:32706-32713`: `SELECT COUNT(*) ... WHERE is_cash=0 AND COALESCE(quantity,0) > 0` → cuenta **lotes**. El KPI de Reportes dice "N posiciones".
- `[V]` `frontend/src/pages/Positions.jsx:1198-1222` (`aggregateAndSort`) → la Cartera muestra **una fila por (activo, moneda)**, o por activo solo en la tarjeta unificada.

Un usuario con 3 compras de AAPL lee "3 posiciones" en Reportes y **una** fila en Cartera.

**D-7 — Agregación por activo: cuatro claves distintas.**

| dónde | clave de agrupación |
|---|---|
| `frontend/src/pages/Positions.jsx:1207` | `(asset, moneda)` — o `asset` solo si `unified` |
| `backend/main.py:22881` (`_valuate_positions_for_chat`) | `(broker, asset)` |
| `backend/home/briefing.py:44-48` | `asset` (cross-broker, cross-moneda) |
| `frontend/src/components/fundamentals/CarteraList.jsx:114-116` | **base canónica del ticker** (`cedearEspecieBase` — la pata pesos `SI` y la dólar `SID` colapsan en una) |

**D-8 — Default de moneda para una tenencia huérfana (broker sin fila en `brokers`).**

| dónde | qué asume |
|---|---|
| `backend/importing/persister.py` (vía `broker_currency = br["currency"] if br else "USDT"`, citado en `backend/importing/invariantes.py:90-91`) | **USDT** |
| `backend/main.py:32812-32814` (top holdings de Reportes, `LEFT JOIN`) | **USD** (`CASE WHEN ... 'ARS' THEN ? ELSE 1`) |
| `backend/advisor_groups.py:203-205` | **ARS** (`COALESCE(b.currency,'ARS')`) |
| `backend/main.py:22874-22880` (chat IA) | **se descarta la posición** (`continue`) |
| `backend/main.py:36906-36914` (libro del asesor) | **se descarta** y se cuenta en `stats['orphan_broker']` |
| `frontend/src/utils/valuation.js:741` (`computeBrokerValue`) | **se descarta** (filtra por `p.broker === broker.name`) |
| `frontend/src/utils/valuation.js:191-202` (`isArUsdBroker`) | fallback por **sufijo del nombre** (`/·\s*USD$/`) |

**D-9 — Dos definiciones de "tenencia": la tabla y el ledger.** `positions` (estado materializado, incluye altas manuales y semillas de foto) vs `ledger_replay.tenencia_en` (replay de `import_normalized_tx`, solo batches `confirmed`, sin FIFO, descartando negativos). El propio módulo documenta que **no coinciden** y por qué: *"Las transferencias de títulos las filtra el validator y NO crean posición… y las posiciones cargadas a mano no están en el ledger en absoluto"* `[V]` `backend/ledger_replay.py:10-17`. `verificar_contra_hoy` (`:136`) existe justamente para detectar el desvío.

**D-10 — Tipo de cambio: la valuación de una tenencia en pesos usa rieles distintos según quién pregunte.**

- Frontend: `tcValuacion` y `tcCedear` son **el mismo número** (`pickFinancialRate(dolar, valuationDollar)`, MEP *medio* con cascada mep→ccl→blue) en las 6 pantallas. `[V]` `frontend/src/contexts/CurrencyContext.jsx:46-54` + `Positions.jsx:241/253`, `Dashboard.jsx:192-193`, `PositionsMobile.jsx:629-630`, `HomeMobile.jsx:99-100`, `AssetDetail.jsx:151-152`, `PositionDetailMobile.jsx:97-98`, `Insights.jsx:404-405`. La distinción blue-vs-MEP quedó **latente pero no activa** (los parámetros siguen ahí y `computeBrokerValue` los toma por separado).
- Backend: `tc_blue` sale de `config.tc_blue` del usuario y `tc_cedear` de `_current_cedear_rate()` (caché dolarapi, cascada mep→ccl→**cripto**) con fallback a `config.tc_mep` → `tc_blue`. `[V]` `backend/analysis_prep.py:31-48`, `backend/main.py:4939-4954`. La cascada del backend incluye **cripto** como tercer escalón y la del frontend incluye **blue**: con MEP y CCL fríos, backend y frontend valúan la misma tenencia a **dos dólares distintos**.
- El cron de snapshots pasa su propio `tc_mep` resuelto por el job, no el del caché. `[V]` `backend/snapshots_job.py:715`.

**D-11 — Filtros de exclusión que no coinciden.**

| dónde | qué se excluye |
|---|---|
| `backend/ai/builders/dashboard_top_holdings.py:90` y `:56` | `if invested <= 0 or qty <= 0: continue` → **una tenencia con costo 0 desaparece** (bono totalmente amortizado, semilla a precio 0) |
| `backend/ai/builders/dashboard.py:67` | idem |
| `backend/main.py:36916-36923` (`_advisor_positions_valued`) | **sin precio conocido → se excluye** ("sin precio ≠ P&L 0") |
| `backend/snapshots_job.py:729-742` | si la cobertura de precios ponderada por costo `< 95%`, **no se escribe el snapshot del día entero** |
| `frontend/src/utils/valuation.js:740` (`computeBrokerValue`) | sin precio → **cae a costo** (P&L 0), no se excluye |
| `frontend/src/utils/assetClass.js:288-289` | `if (value == null \|\| !(value > 0)) continue` → una tenencia con valor 0 no entra a la torta |

Es decir: el asesor y la IA ven una cartera **más chica** (excluyen), el usuario ve una cartera **completa a costo** (incluye). El código lo declara a propósito, pero los números no reconcilian entre pantallas.

**D-12 — Los plazos fijos son tenencia en el frontend y no en el backend.** El hero y la torta del Dashboard suman `pfUsd(usePfRollup(), tcValuacion)` `[V]` `frontend/src/pages/Dashboard.jsx:209` y `:418-421`. El snapshot del cron **no lee `plazos_fijos`** `[V]` verificado por grep sobre `backend/snapshots_job.py` y `backend/behavioral.py`: cero ocurrencias de `plazos_fijos` / `futures_positions`. `[I]` Consecuencia: el "valor de la cartera" que muestra el Dashboard hoy y el que quedó guardado en `snapshots.total_value` de ayer difieren por el plazo fijo entero — y la variación diaria se calcula contra ese snapshot (`frontend/src/pages/Positions.jsx:1617-1623`, "Delta vs último snapshot guardado").

---

### Zonas grises

**Z-1 — `weight_pct` de la IA divide mercado por costo.** `[V]` `backend/ai/builders/position.py:100-104`:
```
total_value = sum(_position_value_usd(p, {}, tc_blue, tc_cedear, honor_override=False) for p in all_pos)
weight_pct = (current_value_usd / total_value * 100) if total_value > 0 else None
```
El numerador es valor de mercado; el denominador, con `prices={}`, es el **cost basis** de toda la cartera. El comentario lo llama "cost basis canónico", así que puede ser deliberado, pero el número resultante no es un peso de cartera: con la cartera en ganancia, los pesos suman **más de 100%**.

**Z-2 — `/api/home/personal` precia los CEDEARs con el ticker de la acción US.** `[V]` `backend/main.py:34193-34200`: `SELECT DISTINCT asset FROM positions ...` → `_fetch_batch_quotes(symbols)` con el símbolo **crudo**, sin pasar por `position_price_key`. Y `[V]` `backend/home/briefing.py:59` lee `quotes.get(h["asset"])` igual de crudo, y la card muestra `context=f"US${h['price']:.2f}"` (`:84`). Para un CEDEAR de AAPL en Cocos, la card dice "AAPL subió 2,3% — US$255" con el precio y la variación de la **acción**, que no es lo que se movió la tenencia (el CEDEAR se mueve con `.BA` y el MEP). Es el mismo bug "C1" que el resto del backend ya arregló; este camino quedó afuera.

**Z-3 — `home/briefing._user_holdings` suma pesos con dólares.** `[V]` `backend/home/briefing.py:44-48`: `SUM(invested)` agrupado solo por `asset`, sin mirar la moneda del lote ni del broker. Hoy ese `invested` no se muestra en ninguna card (las cards usan `change_pct` y `price`), así que el daño es latente — pero el campo sale del helper y está disponible para cualquier consumidor nuevo.

**Z-4 — `_portfolio_snapshot_summary.cash_value` está roto y el código lo dice.** `[V]` `backend/main.py:32832-32851`: *"Hoy, en 'IOL', ya devuelve pesos crudos rotulados como dólares — un defecto PREEXISTENTE… Mitigante: nadie lo consume."* Verificado: el único match de `cash_value` en `frontend/src/` es un literal del fixture de demo (`frontend/src/utils/demo.js`). Queda como deuda declarada.

**Z-5 — `_native_ccy` y `_is_usd_subbroker` usan criterios distintos de "es un sub-broker USD".** `[V]` `backend/behavioral.py:147-157` (laxa: termina en `"· usd"`, `"·usd"`, `"- usd"` **o `" usd"`**) vs `backend/behavioral.py:158-164` (estricta: solo el separador `·`). O sea: un broker llamado **"Mi Broker USD"** (sin punto medio) se trata como **dólares** para el COSTO pero **no** rutea a `.BA` para el PRECIO. Está documentado en el docstring, pero significa que el nombre que elige el usuario cambia cómo se valúa su tenencia — y el frontend, en cambio, decide por `parent_broker_id` (`frontend/src/utils/valuation.js:191-201`) con el nombre solo como fallback.

**Z-6 — El `asset_type` de una fila agregada sale del primer lote.** `[V]` `frontend/src/pages/Positions.jsx:1162`: `asset_type: lots[0].asset_type || null`, con el comentario de `Positions.jsx:1369-1374` diciendo exactamente eso: *"si un ticker tiene lotes CEDEAR y otros con asset_type NULL, toda la fila se precia con el criterio del primero"*. La mitigación (`calcRowUSDT`/`calcRowARS` sumando lote por lote) cubre el **valor**, pero el objeto agregado sigue circulando con ese `asset_type` hacia el modal de edición (`openEditGroup(_buildAgg(...))`, `Positions.jsx:3005`) y hacia la venta.

**Z-7 — El orden del FIFO empata cuando dos lotes comparten `entry_date`.** `[V]` `backend/main.py:11149-11151` (docstring: "descuenta `quantity` empezando por la posición más vieja (entry_date asc)") y el `ORDER BY` de `_amortize_position_fifo` (`backend/main.py:10608-10612`): `ORDER BY COALESCE(entry_date, '9999-12-31') ASC, id ASC`. `entry_date` es `TEXT` con formato `YYYY-MM-DD` (sin hora) `[V]` `backend/importing/persister.py:589` (`tx.date`), así que dos compras del mismo día se desempatan por **`id`**, es decir, por orden de inserción del archivo. El costo consumido —y el P&L de la venta— dependen de eso.

**Z-8 — `_replay_asset` (rebuild) y el FIFO de la venta manual no son el mismo código.** `[V]` `backend/importing/rebuild.py:240-242` dice que *"Espeja `_persist_sell_fifo` / `_persist_buy` exactamente, pero EN MEMORIA"*; son dos implementaciones sincronizadas a mano (`backend/importing/rebuild.py:232` vs `backend/importing/persister.py:601` vs `backend/main.py:11147`, tres motores FIFO). No verifiqué si divergen; queda como riesgo estructural.

**Z-9 — El costo de un lote sobrevive a la venta parcial por prorrateo, no por FIFO interno.** `[V]` `backend/main.py:11369-11376`: `new_invested = round((p["invested"] or 0) * remaining_ratio, 6)`. Es consistente, pero significa que `buy_price` deja de reconciliar con `invested/quantity` cuando el lote nació con `gross_amount` distinto de `unit × qty` (que es el caso normal: `invested = gross_amount` y `buy_price = unit`, `backend/importing/persister.py:566-567`).

**Z-10 — La conciliación contra la foto compara HOY con una fecha posiblemente inventada.** `[V]` `backend/importing/tenencia.py:343-352`: *"esta función NO recibe fechas, así que compara la foto contra el estado de HOY. Eso vale sólo si la foto ES de hoy. Cuando el endpoint no pudo leer la fecha del archivo cae al reloj del servidor (medido: 93 de 152 fotos confirmadas en prod, y `parse_cocos_tenencia` no setea fecha NUNCA)"*. El escape (`no_reconciliable_motivo`) existe, pero la medición citada es del propio código y sugiere que el caso mayoritario es ese.

**Z-11 — La base de dev está por detrás del esquema.** `[V]` `sqlite3 backend/trading.db ".schema positions"` devuelve la tabla **sin `undo_meta_json`** (tiene `entry_date, commissions, currency, asset_type, split_adjusted_through` pero no la última). Y el único índice es `idx_positions_user` — no hay índice por `(user_id, broker, asset)`, que es el acceso más frecuente (`_group_lots`, `_bond_total_qty`, `_amortize_position_fifo`, `_adjust_broker_cash`). No pude confirmar los índices de producción: `backend/schema_pg.sql` no declara ninguno para `positions`.

**Z-12 — `positions.broker` es un string libre y no hay FK.** Todo el sistema resuelve la moneda de una tenencia por `SELECT ... FROM brokers WHERE name=?`. `check_broker_inexistente` (`backend/importing/invariantes.py:86-108`) existe justamente porque eso se rompe, y describe el modo de falla: *"Sin esa fila la moneda cae al default 'USDT' y la cuenta se lee en dólares"*. Cada consumidor elige su propio default (ver D-8).

**Z-13 — No encontré ninguna definición de tenencia "corta" (posición negativa) fuera de futuros.** `ledger_replay.tenencia_en` descarta explícitamente los negativos (`return {k: v for k, v in pos.items() if v > 1e-9}`, `backend/ledger_replay.py:82`) con el comentario *"Un nominal negativo no es una posición corta: es el ledger avisando que le falta la compra"*. `futures_positions.side` sí admite `'short'` (`backend/schema_pg.sql:870`), pero esa tabla no entra a ninguno de los motores de valuación.

**Z-14 — `demo.js` tiene un modelo de cash distinto.** `[V]` `frontend/src/utils/demo.js:216`: `v = p.broker === 'Cocos' ? (p.quantity || 0) / _DEMO_TC_BLUE : (p.invested || 0)` — usa `quantity` para el saldo de caja del broker ARS, cuando el modelo real lo guarda en `invested` (`backend/main.py:9787`). Es solo el fixture de demo, pero cualquiera que lea ese archivo para entender el modelo se lleva la definición equivocada.
