## Valuación de cartera / valor de mercado

### Definición según el código

En Rendi, "cuánto vale tu cartera" **no es** el número que devuelve una sola función. Es una familia de números que comparten un esqueleto y difieren en los bordes. El esqueleto, tal como lo implementa el código:

**`valor = Σ sobre los LOTES abiertos de (precio × cantidad), convertido a USD, con un guard que reemplaza el precio por el COSTO cuando el precio "no se cree"; más el efectivo.`**

Cinco decisiones no estándar definen el concepto en esta app:

1. **La unidad es el LOTE, no el holding.** `positions` guarda un lote FIFO abierto por fila (`backend/schema_pg.sql:1431-1449`: `broker, asset, is_cash, quantity, invested, tc_compra, price_override, commissions, currency, asset_type`). La valuación itera lotes y suma; agrupar por ticker es un paso posterior y opcional. `[V]`

2. **La moneda base del resultado es SIEMPRE el dólar** — y no cualquier dólar: el **dólar financiero MEP** (o CCL si el usuario cambia la preferencia), tomado al **MEDIO** `(compra+venta)/2`, no a la punta (`frontend/src/contexts/CurrencyContext.jsx:51-53`). El blue quedó relegado a un stamp de display. `[V]`

3. **"Sin precio" ⇒ el valor ES el costo.** No es `null`, no es "sin dato": la posición aporta su cost basis al total y su P&L queda exactamente 0. Está escrito así en las 6 ramas de `valuePositionLot` y en el port de Python (`frontend/src/utils/valuation.js:543-770`; `backend/snapshots_job.py:158-320`). Consecuencia directa: un total de cartera puede estar mezclando mercado y costo sin decirlo, y por eso existen los guards de cobertura ≥95% (`backend/snapshots_job.py:711-720`). `[V]`

4. **"Precio absurdo" también ⇒ el valor es el costo.** `trustMktValue` (`frontend/src/utils/valuation.js:448-455`) rechaza cualquier valuación cuyo cociente `valor/costo` se salga de una banda: renta fija `[0.02×, 4×]`, resto `[0.002×, 50×]`. Es un clamp de plausibilidad contra el COSTO — es decir, **el costo es parte de la definición del valor de mercado**, no un dato independiente. `[V]`

5. **El costo es `invested + commissions`**, en la moneda NATIVA del LOTE (`positions.currency`), no la de la cuenta (`frontend/src/utils/valuation.js:214-236` `costInPesos`, `324-336` `costInUsd`). Un CEDEAR con `currency='ARS'` en un broker USD se valúa "estilo pesos"; un ON con `currency='USD'` en Balanz (broker ARS) NO se divide por el MEP. `[V]`

Además hay **una segunda familia de "valor de cartera" que no es de mercado**: la cadena contable `monthly_entries.capital_final = capital_inicio + deposits − withdrawals + pnl_realized + pnl_unrealized` (`backend/main.py:11069-11082`). Cuando el import fabrica snapshots, escribe literalmente `total_value = capital_final` (`backend/importing/persister.py:1230-1296`) — o sea, mete contabilidad en la columna que todo el resto lee como mercado. Todo el andamiaje de `base`/`apto`/`sintetico` existe para separar estas dos cosas después de haberlas mezclado en la misma columna. `[V]`

**Lo que NO entra en el valor de cartera** (y varía según la pantalla): plazos fijos (tabla `plazos_fijos`), futuros (tabla `futures_positions`). Ver §Implementaciones divergentes. `[V]`

---

### Dónde se calcula

Orden: primero lo canónico, después los ports, después las reimplementaciones.

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `frontend/src/utils/valuation.js:543` | `valuePositionLot(p, ctx)` | **LA valuación canónica de UN lote.** 6 ramas en orden fijo: cash → `costInPesos && !isAR` → `costInUsd && isAR` → `isAR` → `(CEDEAR‖arUsd) en broker USD` → USD nativo | rama 4 (isAR): `const mktArs = priceArs != null ? priceArs * (p.quantity \|\| 0) : null` … `valueUsd: trustArs ? mktArs / cedearRate : invUsdHoy` | **FUENTE (canónica)** |
| 2 | `frontend/src/utils/valuation.js:740` | `computeBrokerValue(...)` | Suma `valuePositionLot` sobre los lotes del broker. "Toda la lógica por lote vive en valuePositionLot; acá no queda ninguna rama" | `for (const p of bpos) { const r = valuePositionLot(p, ctx); value += r.valueUsd; invested += r.investedUsd; valueArs += r.valueArs; invArs += r.invArs }` | **FUENTE (agregador canónico)** |
| 3 | `frontend/src/utils/valuation.js:448` | `trustMktValue(mkt, realCost, assetType, hasOverride)` | Guard anti-distorsión. Decide si el precio se usa o se cae a costo | `const mult = mktValue / realCost; return fixed ? (mult <= 4 && mult >= 0.02) : (mult <= 50 && mult >= 0.002)` | FUENTE (gate) |
| 4 | `frontend/src/utils/valuation.js:469` | `valuationPriceKey(p, isArsBroker)` | La key de `prices` con la que la valuación lee. Espejo declarado de las ramas de #1 | `if (isArsBroker) return priceSymbol(p.asset, true, p.asset_type)` / `if (isCrypto(p.asset)) return priceSymbol(p.asset, false, ...)` / `if (isArUsdBroker(p.broker) \|\| costInPesos(p)) return priceSymbol(p.asset, true, ...)` | FUENTE (ruteo de precio) |
| 5 | `frontend/src/utils/valuation.js:338` | `usdLotValue(p, prices, cedearRate)` | Lote de costo USD en broker ARS (ON/FCI-USD/CEDEAR-MEP) | `const mktUsd = raw != null ? (priceIsArs ? raw / cedearRate : raw) : null` … `valueUsd: trust ? mktUsd : investedUsd` | FUENTE (helper compartido) |
| 6 | `frontend/src/utils/valuation.js:293` | `pesoLotUsd(p, prices, tcCedear, costBasis)` | Lote en pesos alojado en cuenta USD | `const valueUsd = priceArs != null ? (priceArs * (p.quantity \|\| 0)) / tcCedear : investedUsdToday` | FUENTE (helper compartido) |
| 7 | `frontend/src/utils/valuation.js:360` | `valueEquityLot(p, broker, prices, tc, cedearRate, costBasis)` | 5.ª implementación de la valuación por lote, para "Calidad de cartera". Mismas ramas que #1 pero sin la de cash y sin factor cripto | `if (valueUsd == null \|\| !trustMktValue(valueUsd, guardCost, p.asset_type, p.price_override != null)) { valueUsd = guardCost; investedUsd = guardCost }` | FUENTE (paralela) |
| 8 | `frontend/src/utils/valuation.js:905` / `:925` | `sumRowUSDT(cs)` / `sumRowARS(cs)` | Suma las valuaciones de los lotes de una FILA agregada de la tabla | (agregación de `{value, pnl, investedUsd}` por lote) | FUENTE (agregador de fila) |
| 9 | `frontend/src/utils/valuation.js:797` | `computePf(pf, asOf)` | Valuación determinística de un plazo fijo (no usa precios) | TNA: `i = tasa × días/365`; TEA: `i = (1+tasa)^(días/365) − 1` | FUENTE (otro instrumento) |
| 10 | `backend/snapshots_job.py:158` | `compute_broker_value_usd(...)` | **Port Python de #2.** El motor de TODO el backend: cron, asesor, chat IA, replay, reconstructor | rama ARS holdings: `mkt_usd = (price_ars * (p.get('quantity') or 0)) / cedear_rate if cedear_rate > 0 else 0` … `value += mkt_usd if trust else inv_usd` | **FUENTE (canónica backend)** |
| 11 | `backend/snapshots_job.py:42` | `_trust_mkt_value(...)` | Port de #3 | `return (0.02 <= mult <= 4) if fixed else (0.002 <= mult <= 50)` | FUENTE (gate) |
| 12 | `backend/snapshots_job.py:104` | `position_price_key(p, ars_names, ar_usd_names)` | Port (parcial) de #4 | `wants_ba = (broker in ars_names or broker in ar_usd_names or (p.get('asset_type') or '').upper() == 'CEDEAR')` | FUENTE (ruteo de precio) |
| 13 | `backend/snapshots_job.py:623` | `take_snapshot_for_user(...)` | Cron diario: valúa broker por broker, suma, y **persiste** | `for b in brokers: r = compute_broker_value_usd(bpos, prices, b['currency'], tc_blue, broker_name=b['name'], cedear_rate=tc_cedear); total_value += r['value']` (`:751-753`) | **FUENTE + PERSISTE** |
| 14 | `backend/snapshots_job.py:810` | `compute_live_portfolio_value(conn, uid, tc_blue, crypto_yf)` | Valor live sin persistir, cacheado 60s. Mismas 3 defensas que el cron | `total_value += r['value']` (`:898`), con guard `if non_cash and coverage < 0.95: return None` | FUENTE |
| 15 | `backend/behavioral.py:391` | `_position_value_usd(p, prices, tc_blue, tc_cedear, honor_override)` | **SEGUNDO motor backend, independiente.** Alimenta comportamiento + casi todos los builders de IA | `mkt_usd = (value_native / rate_holdings) if (price_is_ars and rate_holdings > 0) else value_native` … `if _trust_mkt_value_usd(mkt_usd, cost_usd, p.get("asset_type")): return mkt_usd * crypto_f` | **FUENTE (paralela)** |
| 16 | `backend/behavioral.py:47` | `_trust_mkt_value_usd(mkt_usd, cost_usd, asset_type)` | Variante de #3 **sin parámetro `has_override`** | `if (asset_type or '').upper() in _FIXED_INCOME_TYPES: return 0.02 <= mult <= 4` / `return 0.002 <= mult <= 50` | FUENTE (gate, divergente) |
| 17 | `backend/ai/builders/insights.py:422-470` | bloque inline de `build_insights_packet` | **TERCER motor backend**, inline, para el packet de la IA | `mv = (price * qty) / tc_cedear if price else cost_usd` (`:451`) / `mv = price * qty if price else cost_usd` (`:454`); luego `if not _trust_mkt_value_usd(mv, cost_usd, p.get("asset_type")): mv = cost_usd` | FUENTE (paralela) |
| 18 | `frontend/src/pages/Dashboard.jsx:298-380` | memo `positionsForInsight` | **Reimplementación inline** del por-lote en el Dashboard, para la torta / mejores-peores / snapshot IA | `const mktArs = priceArs * (p.quantity \|\| 0); const trust = trustMktValue(mktArs, realCost, p.asset_type, p.price_override != null); valueUsd = (trust ? mktArs : realCost) / tcValuacion` | FUENTE (paralela, frontend) |
| 19 | `frontend/src/pages/Dashboard.jsx:495-585` | efecto "sync pnl_unrealized" | **Otra reimplementación inline**, esta calcula el P&L no realizado que se escribe en la base | `pnlForBroker = pnlArs / tcValuacion + pnlUsdDirect` (`:536`) | FUENTE (paralela) → escribe a DB |
| 20 | `frontend/src/pages/Insights.jsx:417-465` | `holdingValueUsd(p)` | **Reimplementación inline** para la torta por activo / atribución / packet | `return ((mkt != null && trustMktValue(mkt, realCost, p.asset_type, p.price_override != null)) ? mkt : realCost) * f` (`:463`) | FUENTE (paralela) |
| 21 | `frontend/src/pages/Positions.jsx:1240-1310` | `calcUSDT(p)` | Valuación de una FILA en un broker USD (tabla desktop) | `const value = price * p.quantity * f` … `if (!trustMktValue(value, realCost, ...)) return { value: realCost, pnl: 0, ... }` | FUENTE (paralela) |
| 22 | `frontend/src/pages/Positions.jsx:1319-1367` | `calcARS(p)` | Valuación de una FILA en un broker ARS | `const valueArs = priceArs * p.quantity` … `const valueUsd = valueArs / tcCedear` | FUENTE (paralela) |
| 23 | `frontend/src/pages/Positions.jsx:1382-1394` | `calcRowUSDT` / `calcRowARS` | Fila agregada = SUMA de sus lotes (no revaluación del agregado) | `if (!lots \|\| lots.length < 2) return calcUSDT(p); return sumRowUSDT(lots.map(calcUSDT))` | FUENTE (agregador) |
| 24 | `frontend/src/pages/PositionsMobile.jsx:668-780` | memo de filas mobile | **Reimplementación inline mobile**, con orden de ramas distinto al canónico | `let investedUsd = isAR && costInUsd(p) ? invested : isAR ? invested / tcValuacion : costInPesos(p) ? invested / tcCedear : invested` (`:675-678`) | FUENTE (paralela, mobile) |
| 25 | `frontend/src/pages/AssetDetail.jsx:38-99` | `valueLot(p, broker, ...)` | Valuación por lote de la ficha del activo (desktop) | `const valueUsd = trustMktValue(mkt, guardCost, p.asset_type, p.price_override != null) ? mkt : investedUsd` (`:58`) | FUENTE (paralela) |
| 26 | `frontend/src/pages/PositionDetailMobile.jsx:111-178` | bloque inline de la ficha mobile | Ídem #25 pero mobile | `valueUsd = (mkt != null && trustMktValue(mkt, investedF, p.asset_type, p.price_override != null)) ? mkt : investedF` (`:172`) | FUENTE (paralela, mobile) |
| 27 | `frontend/src/pages/HomeMobile.jsx:240-262` | bloque "mejor activo" | Otra reimplementación por lote para el KPI de mejor activo | `const value = trustMktValue(mkt, invested, p.asset_type, p.price_override != null) ? mkt : invested` (`:256`) | FUENTE (paralela, mobile) |
| 28 | `frontend/src/pages/FirstInsight.jsx:110-160` | onboarding | Reimplementación por lote para el primer insight | `valueUsd = (mktUsd != null && trustMktValue(mktUsd, cost, p.asset_type)) ? mktUsd : cost` (`:143`) | FUENTE (paralela) |
| 29 | `backend/scripts/backfill_historical_mtm.py:435` | `backfill_user(conn, uid, today)` | **Reconstructor MtM histórico.** Delega en #10 salvo por el CEDEAR-USD, y reimplementa el guard | `_lo, _hi = (0.02, 4.0) if _fixed else (0.002, 50.0); if _mult < _lo or _mult > _hi: trusted = False` … `efectivo = inv + u` | FUENTE + PERSISTE |
| 30 | `backend/importing/persister.py:1230` | `_backfill_snapshots_from_monthly(conn, uid)` | **NO valúa**: copia la contabilidad a la columna de valor | `total_value = capital_final del mes` (docstring `:1237`), `INSERT INTO snapshots (...) VALUES (?,?,?,?,?,'import','costo',0)` (`:1292-1295`) | PERSISTE (base = costo) |
| 31 | `backend/ledger_replay.py:195` | `valor_en(conn, uid, fecha)` | Valor histórico reconstruido desde el ledger. Delega explícitamente en #10 para no crear un motor más | `r = compute_broker_value_usd(pos, precios, ccy_de.get(broker) or "ARS", fx or 0.0, broker_name=broker, cedear_rate=fx)` (`:273-275`) | FUENTE (delegada) |
| 32 | `backend/main.py:22818` | `_valuate_positions_for_chat(conn, uid)` | Valuación autoritativa server-side para el chat IA; llama a #10 **una posición por vez** y agrupa por `(broker, asset)` | `r = compute_broker_value_usd([p], prices, bccy, tc_blue, broker_name=p['broker'], cedear_rate=tc_cedear)` (`:22882`) | FUENTE (delegada) |
| 33 | `backend/main.py:36844` | `_advisor_positions_valued(conn, ids, tc_blue, tc_mep)` | Valuación del LIBRO del asesor (todos los clientes), posición por posición vía #10 | `r = compute_broker_value_usd([p], prices, bccy, tc_blue, broker_name=p["broker"], cedear_rate=tc_cedear)` (`:36924-36926`) | FUENTE (delegada) |
| 34 | `backend/main.py:25385-25470` | tool IA `get_realized_vs_unrealized` | Valuación de cartera para el LLM vía #10 | `market_value_usd += r.get('value', 0) or 0` (`:25470`), `unrealized_usd = market_value_usd - invested_usd` (`:25483`) | FUENTE (delegada) |
| 35 | `backend/advisor_brief.py:83` | `live_book_values(conn, client_ids, price_cache)` | Valor vivo del libro para el Δ del brief diario, vía #10 | `out[cid] = out.get(cid, 0.0) + float(r.get("value") or 0)` (`:154`) | FUENTE (delegada) |
| 36 | `frontend/src/utils/demo.js:190-260` | `_BROKER_LIVE_USD` | **Valuación propia del modo demo**, con un algoritmo simplificado declarado como "el mismo que computeBrokerValue" | (rama ARS) `precio[asset+'.BA'] × quantity / tcValuacion`, sin `trustMktValue`, sin factor cripto, sin `costInPesos`/`costInUsd` | FUENTE (fixture) |
| 37 | `backend/main.py:11069-11082` | `POST /api/monthly/sync-unrealized` | Convierte el P&L no realizado que manda el frontend (#19) en `capital_final` | `capital_final = capital_inicio + deposits − withdrawals + pnl_realized + pnl_unrealized` | PERSISTE (base = contable) |
| 38 | `backend/main.py:32873` / `:32949` | `_snapshot_delta` / `_ytd_delta` | Restan dos "valores de cartera" para producir deltas 1d/7d/30d/YTD | (ver §Zonas grises: el borde de cierre no se filtra) | CONSUMIDOR |
| 39 | `backend/reporting/builder.py:523` | `bordes_mercado_periodo(...)` | Las dos puntas de un período, medidas a mercado. Exige que AMBAS sean base de mercado | `return float(ini["total_value"]), float(fin["total_value"])` (`:620`) | CONSUMIDOR |
| 40 | `backend/reporting/builder.py:783` | `_modified_dietz_pct(start_value, end_value, flows)` | Rendimiento del período a partir de dos valores de cartera | Modified Dietz sobre `start_value`/`end_value` de snapshots | CONSUMIDOR |
| 41 | `frontend/src/utils/insightsModel.js:601` | `applyMtmToMonthly(globalMonthly, snapshots, today, valorMercadoLive)` | Re-ancla la cadena contable a los snapshots de mercado. El mes en curso cierra con el valor LIVE | `return { ...m, capital_inicio: snapPrev.value, capital_final: valorMercadoLive, ..., mtm: 'inicio' }` | CONSUMIDOR (re-define capital_final) |
| 42 | `frontend/src/utils/evolution.js:174` | `buildPortfolioValueSeries(snapshots, days, liveValue, liveNet, liveFx)` | Serie de valor para el gráfico; appendea el valor live como punto de hoy | `valueUsd: +(s.total_value \|\| 0)` (`:193`); punto sintético `valueUsd: +liveValue` | CONSUMIDOR |
| 43 | `frontend/src/utils/evolution.js:399` | `buildEvolutionFromSnapshots(...)` | TWR chain-linked entre snapshots. Filtra con `esApto` | `pnl_t = (value_t − value_t-1) − flows_t; period_return = pnl_t / (value_t-1 + 0.5 × flows_t)` | CONSUMIDOR |
| 44 | `frontend/src/utils/evolution.js:363` | delta diario | Variación del día contra el snapshot anterior | `const usd = (todayValue - todayNetDep) - ((prev.total_value \|\| 0) - netDepositedOf(prev))` | CONSUMIDOR |
| 45 | `backend/main.py:32635` | `_portfolio_snapshot_summary(conn, uid, broker_filter, live_value_override)` | Resumen estático: `latest_value`, deltas, top holdings, `cash_value` | `latest_value = live_value_override` o `snap_value = float(latest_snap["total_value"])` | CONSUMIDOR |
| 46 | `backend/main.py:35651` | endpoint del informe firmado del asesor | `value_end_usd` del informe = último punto de la serie medible | `value_end = round(float(end_row["total_value"]), 2) if end_row else None` | CONSUMIDOR |

Consumidores del agregador `computeBrokerValue` en el frontend (todos suman `.value` sobre brokers):

| archivo:línea | qué total arma |
|---|---|
| `frontend/src/pages/Dashboard.jsx:211` | `brokerTotals` → hero "Valor actual", torta, curva |
| `frontend/src/pages/Positions.jsx:1591` | `totals` del hero "Tu cartera hoy" |
| `frontend/src/pages/Positions.jsx:1610` | `totalsToday` (forzado a modo `'today'`, para el hero en pesos) |
| `frontend/src/pages/Positions.jsx:2040` | subtotal por pata de la tarjeta de cuenta (padre + `· USD`) |
| `frontend/src/pages/Insights.jsx:411` | `pieData` → `totalPortfolio` de Análisis |
| `frontend/src/pages/Insights.jsx:328` | `liveUsdPerf` (punta "hoy" de la curva de performance) |
| `frontend/src/pages/Insights.jsx:526` | `totalCostBasis` |
| `frontend/src/pages/Insights.jsx:974` | valor live de los brokers ARS (tramo final del TWR en pesos) |
| `frontend/src/pages/HomeMobile.jsx:111` / `:128` | hero mobile + `totalsMep` (comparación contra snapshots) |
| `frontend/src/pages/FirstInsight.jsx:92` | onboarding |
| `frontend/src/pages/Goals.jsx:82` | valor actual para objetivos |
| `frontend/src/pages/Events.jsx:155` / `:167` | valor total y por-posición para el % de impacto de un evento |
| `frontend/src/components/MonthlySummary.jsx:284` | "Valor actual (live)" de Movimientos |
| `frontend/src/components/fundamentals/CarteraList.jsx:95` | total de "Calidad de cartera" |
| `frontend/src/hooks/useMonthlyData.js:509` | `liveValue` del hook mensual |

---

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `frontend/src/pages/Dashboard.jsx:804` | hero del Dashboard | **"Valor actual · USD"** / **"Valor actual · ARS"** |
| `frontend/src/pages/Dashboard.jsx:806` | tooltip del hero | "Valor de mercado de tu cartera" |
| `frontend/src/pages/Dashboard.jsx:1193` | eje/leyenda del gráfico de evolución | "Valor de la cartera" |
| `frontend/src/pages/Dashboard.jsx:1314` | tooltip de las cards por broker | "Valor actual de tus posiciones por broker, con P&L total (incluye cash)" |
| `frontend/src/pages/Positions.jsx:1859` | hero de Cartera | **"Tu cartera hoy"** |
| `frontend/src/pages/Positions.jsx:1652` | `heroValue = totals.value + pfValueUsd` | (el hero SÍ suma plazos fijos) |
| `frontend/src/pages/AssetDetail.jsx:231` | ficha del activo (desktop) | "Valor actual · N brokers" |
| `frontend/src/pages/PositionDetailMobile.jsx:230` | ficha del activo (mobile) | "Valor actual" |
| `frontend/src/components/MonthlySummary.jsx:842` | Movimientos | **"Valor actual (live)"** |
| `frontend/src/pages/ReportPublic.jsx:119` | informe firmado del asesor (público) | **"Valor de la cartera"** + "al {fecha} · dólar MEP {tc}" |
| `frontend/src/components/guide/ReturnsDiagram.jsx:106` | diagrama explicativo | "Valor de mercado" |
| `frontend/src/pages/Insights.jsx:553` | comentario del código de Análisis | "Resultado total = Valor actual − Capital aportado" |
| `frontend/src/utils/evolution.js:193` | serie del gráfico | lee `s.total_value` de cada snapshot |
| `frontend/src/hooks/useMonthlyData.js:314`, `:436-437`, `:503`, `:610-613` | hook mensual | `total_value` como `mtmStart`/`mtmEnd`/`liveValue` |
| `frontend/src/utils/insightsModel.js:610` | `applyMtmToMonthly` | `const v = Number(s?.total_value)` |
| `backend/main.py:5093` | `GET /api/snapshots` | devuelve `total_value` + `base`/`apto`/`source` |
| `backend/main.py:25507` | tool IA | `"market_value_usd": round(market_value_usd, 2)` |
| `backend/ai/builders/insights.py:547` | packet IA | `"market_value_usd": round(mv, 2)` por holding |
| `backend/main.py:22960` | `_enrich_chat_snapshot_valuation` | pisa el snapshot del frontend con la valuación server-side |
| `backend/ai/builders/dashboard*.py`, `insights_attribution.py`, `position.py` | builders del Coach IA | todos vía `_position_value_usd` |
| `backend/reporting/timeline.py:144` | timeline de Reportes | `v = _position_value_usd(p, prices, tc_blue, tc_cedear)` |
| `backend/behavioral.py:987`, `:1086`, `:1095`, `:1176`, `:1559`, `:1715` | detectores de comportamiento (concentración, exposición AR/intl, liquidez) | `value_usd = _position_value_usd(...)` |
| `backend/main.py:15263` | diagnóstico de objetivos | `current_value += v` |
| `backend/advisor_alerts.py:253`, `backend/advisor_brief.py:291` | alertas y brief del asesor | leen `total_value` con el filtro `apto` inline |

---

### Dónde se persiste

**Tabla `snapshots`** — es el único lugar donde el valor de cartera queda guardado.

`backend/schema_pg.sql:1525-1539`:

| columna | qué guarda |
|---|---|
| `total_value` (`double precision NOT NULL`) | **el valor de cartera en USD**. Positions-only (sin plazos fijos ni futuros) |
| `total_invested` | el cost basis agregado… salvo en las filas del import, donde guarda `net_deposited` (`backend/importing/persister.py:1237`) |
| `net_deposited` | Σ(deposits − withdrawals) + baseline |
| `fx_to_usd_blue` | stamp del blue del día — SOLO display (curva en ARS) |
| `holdings_json` | `[{asset, value_usd}]` — la foto por activo, sin cash (`backend/snapshots_job.py:763`) |
| `source` | `'cron'` \| `'browser'` \| `'import'` \| `'mtm_backfill'` |
| `mtm_coverage` | fracción del valor no-cash que se valuó a precio real (solo la reconstrucción) |
| `base` | `'mercado'` \| `'costo'` — **qué ES el número de `total_value`** |
| `apto` | `0/1` — si esa fila puede ser pico o denominador |
| UNIQUE | `(user_id, date)` |

**Cuatro escritores distintos, con cuatro semánticas distintas para la misma columna:**

| escritor | archivo:línea | `source` | `base` | `apto` | qué es `total_value` |
|---|---|---|---|---|---|
| cron nocturno | `backend/snapshots_job.py:778-790` | `cron` | `mercado` | `1` | posiciones × precio real, todo al MEP |
| Dashboard del navegador | `backend/main.py:5072-5083` | `browser` | `mercado` | `0` | lo que el frontend calculó y posteó (`frontend/src/pages/Dashboard.jsx:478`) |
| import | `backend/importing/persister.py:1292-1295` | `import` | `costo` | `0` | **`capital_final` de la contabilidad** — no es mercado |
| reconstructor MtM | `backend/scripts/backfill_historical_mtm.py:414-428` | `mtm_backfill` | según cobertura | según cobertura | mercado histórico donde hubo precio, costo donde no |

Además, valor de cartera **contable** persistido: `monthly_entries.capital_final` (`backend/schema_pg.sql:1201`), escrito por `POST /api/monthly/sync-unrealized` (`backend/main.py:11082`) con el P&L que el Dashboard calcula en el navegador (#19).

**Lo que NO se persiste:** el valor de cartera live (Dashboard, Cartera, Análisis) se calcula al vuelo en cada render, en el navegador. El backend lo recalcula al vuelo con caché de 60s en `compute_live_portfolio_value` (`backend/snapshots_job.py:806-808`, `_LIVE_VALUE_CACHE`) y otro de 60s para el chat (`_CHAT_VAL_CACHE`, `backend/main.py:22838-22843`).

⚠️ La copia SQLite de desarrollo (`backend/trading.db`) tiene la tabla `snapshots` SIN las columnas `holdings_json`, `source`, `mtm_coverage`, `base` ni `apto` — es de una rama vieja. **El schema que manda es `backend/schema_pg.sql`.** `[V]` (verificado con `sqlite3 backend/trading.db ".schema snapshots"`).

---

### ⚠️ Implementaciones divergentes

**No hay una sola implementación. Hay cuatro motores y unas diez reimplementaciones inline.** El código lo admite explícitamente: *"había CINCO implementaciones de la valuación por lote … y ninguna era 'la buena a la que volver'"* y *"Esta es la que va a serlo. Todavía NO la consume nadie más"* (`frontend/src/utils/valuation.js:504-511`). O sea: **la función canónica existe pero solo la usa su propio agregador.** `[V]`

#### D-1. La rama "lote en pesos alojado en cuenta USD" NO existe en el backend

| | frontend `valuePositionLot` | backend `compute_broker_value_usd` |
|---|---|---|
| rama | `if (!p.is_cash && !isAR && costInPesos(p))` (`valuation.js:578-604`) | **no existe** |
| costo | `realCost / cedearRate` | `invested += real_cost * cf` — cuenta los PESOS como dólares |
| valor | `mktArs / cedearRate` | `prices.get(p['asset'])` — ticker US |

`compute_broker_value_usd` tiene la rama espejo `_cost_in_usd` para el broker ARS (`backend/snapshots_job.py:246-268`), pero **no tiene la rama simétrica `costInPesos` para el broker USD**. Un lote con `currency='ARS'` en un broker USD que no sea CEDEAR ni sub-broker `· USD`: el frontend lo divide por el MEP y el cron lo cuenta 1:1. `[V]`

Peor: `position_price_key` (`backend/snapshots_job.py:104-126`) tampoco consulta `costInPesos`, mientras que `valuationPriceKey` sí (`frontend/src/utils/valuation.js:474`). O sea el cron ni siquiera pide el `.BA` de ese lote. **Pantallas afectadas:** el hero del Dashboard/Cartera muestra un número y la curva de snapshots otro, para el mismo lote. `[I]` — inferido de que las dos funciones son las únicas que deciden esa rama y una tiene el `if` y la otra no.

#### D-2. `arUsd` es parent-aware en el frontend y solo regex en el motor backend

| | resolución |
|---|---|
| `frontend/src/utils/valuation.js:191-201` `isArUsdBroker` | mira el registro de brokers → `parent_broker_id` → `currency` del padre; **fallback** al regex `/·\s*USD$/` |
| `backend/snapshots_job.py:158-160` `compute_broker_value_usd` | `ar_usd = _is_ar_usd_subbroker(broker_name)` → **solo** el regex `·\s*usd$` (`:56-67`) |
| `backend/snapshots_job.py:73-86` `_broker_name_sets` (que alimenta `build_price_symbols` y la cobertura) | **sí** es parent-aware |

Consecuencia: si el usuario renombra "Balanz · USD" a "Balanz dólares", el cron **pide** el `.BA` (parent-aware) pero **valúa** por el ticker US (regex) → `prices.get('MELI')` no está en el dict → la posición cae a costo, en silencio. El frontend, en cambio, la valúa bien. Es exactamente el modo de falla que documenta `valuationPriceKey` (`valuation.js:465-467`). `[I]` — inferido de leer las tres funciones; no encontré un test que lo cubra.

#### D-3. `trustMktValue` tiene tres versiones con tres contratos

| versión | archivo:línea | `has_override` | efecto |
|---|---|---|---|
| frontend | `frontend/src/utils/valuation.js:448` | sí | override de no-renta-fija se respeta; override de renta fija SE CLAMPEA |
| snapshots_job | `backend/snapshots_job.py:42` | sí (port fiel) | idéntico |
| behavioral | `backend/behavioral.py:47` | **NO existe el parámetro** | y además, en `_position_value_usd` (`:449-457`) el `price_override` **retorna ANTES del guard** → un override absurdo en un bono NUNCA se clampea del lado de Comportamiento / builders IA |

Caso real documentado en el propio código (`valuation.js:441-446`): una ON con precio manual en convención per-100 (97 en vez de 0,97) → ×100 (+9775%). El Dashboard lo clampea; los detectores de comportamiento y el packet de la IA, no. `[V]`

#### D-4. `_position_value_usd` ignora las comisiones

`backend/behavioral.py:412`: `invested_native = float(p.get("invested") or 0)` — sin `+ commissions`. Todas las demás implementaciones usan `realCost = (p.invested || 0) + (p.commissions || 0)` (`valuation.js:557-558`, `snapshots_job.py:213-214`, `AssetDetail.jsx:47`, `Positions.jsx:1300`). Lo mismo en `ai/builders/insights.py:432`: `invested = float(p.get("invested") or 0)`.

Efecto: el cost basis del motor #15/#17 es más chico → el P&L no realizado que ve la IA y los detectores es más grande que el que ve el usuario en pantalla, y el guard `_trust_mkt_value_usd` compara contra un denominador distinto. `[V]`

#### D-5. Los plazos fijos entran en unos totales y no en otros

| superficie | ¿incluye plazos fijos? | cita |
|---|---|---|
| hero de Cartera | **SÍ** | `heroValue = totals.value + pfValueUsd` (`frontend/src/pages/Positions.jsx:1652`) |
| hero del Dashboard | **SÍ** | `const totalValue = brokerTotals.reduce(...) + pf.valueUsd` (`frontend/src/pages/Dashboard.jsx:212`) |
| hero mobile | **SÍ** (via `pf`) | `frontend/src/pages/HomeMobile.jsx:102` |
| `totalPortfolio` de Análisis | **NO** | `const totalPortfolio = pieData.reduce((s, x) => s + x.value, 0)` (`frontend/src/pages/Insights.jsx:413`); el PF entra solo como porción de torta (`:2148`) |
| lo que se postea a `snapshots` | **NO** | `totalValuePositions = totalValue - pf.valueUsd` (`frontend/src/pages/Dashboard.jsx:232`) |
| el cron | **NO** | `take_snapshot_for_user` solo lee `positions` (`backend/snapshots_job.py:665-670`) |
| todo el backend (asesor, IA, reportes) | **NO** | ningún caller de `compute_broker_value_usd` lee `plazos_fijos` |

`[V]`. Un usuario con un PF grande ve un número en Cartera y otro, más chico, en Análisis y en el informe del asesor. El Dashboard lo sabe y lo compensa restándolo antes de comparar contra snapshots (`frontend/src/pages/Dashboard.jsx:230-233`), pero Análisis no compensa: usa `totalPortfolio` (sin PF) como cierre del mes en curso en `applyMtmToMonthly` (`Insights.jsx:544`) y contra los snapshots (que tampoco lo tienen), así que ahí sí cierra.

#### D-6. Los futuros no entran en ningún valor de cartera

`futures_positions` es una tabla propia (`backend/schema_pg.sql:864`) y ningún motor de valuación la lee. El comentario de la UI lo justifica: *"un futuro NO es una tenencia (no tenés el activo, y un short vale al revés)"* (`frontend/src/pages/Positions.jsx:2805-2806`). Es una decisión, no un bug — pero significa que "el valor de tu cartera" excluye los futuros abiertos en todas las superficies. `[V]`

#### D-7. La fila de la tabla y el total del broker no usan el mismo guard

`Positions.jsx` desktop, rama `costInPesos` de `calcUSDT` (`frontend/src/pages/Positions.jsx:1265-1280`): calcula `const value = (priceArs * p.quantity) / tcCedear` y devuelve **sin pasar por `trustMktValue`**. El comentario lo dice: *"No hay guard en esta rama → sin flip"* (`:1272`). El total del pie, en cambio, sale de `computeBrokerValue` → `valuePositionLot` rama 2, que **sí** guardea (`valuation.js:583-584`). Un bono en pesos con precio per-100 en una cuenta USD: la fila lo muestra ×100 y el total lo clampea. `[V]`

#### D-8. La ficha del activo publica el costo al `tc_compra` como valor de mercado

`frontend/src/pages/AssetDetail.jsx:52-59` (rama `costInPesos && !isAR`) y `:70-79` (rama `isAR`): cuando no hay precio, `mkt` cae a `investedUsd`, que es el costo **ruteado por el modo** (`costBasisRate(p, ..., costBasis)` → `tc_compra` en modo `'purchase'`). El canónico hace lo contrario a propósito:

```
// SIN PRECIO CONFIABLE — el valor Y el costo-display van los DOS al dólar de HOY
// (guardCost) y el P&L queda exactamente 0. Antes caían a `investedUsd`, que en
// modo 'purchase' está dividido por tc_compra: publicaba costo/tc_compra como
// valor de mercado.
```
(`frontend/src/utils/valuation.js:410-415`, y el mismo texto en `:596-598` y `:663-665`).

Y el modo por defecto **es** `'purchase'` (`frontend/src/contexts/CurrencyContext.jsx:102-109`). O sea: para un lote en pesos sin cotización, la ficha del activo muestra `costo/tc_compra` rotulado "Valor actual" mientras el hero de Cartera muestra `costo/MEP_hoy`. `[V]`

#### D-9. El orden de las ramas cambia entre desktop y mobile

| | orden |
|---|---|
| `valuePositionLot` (canónico) | cash → `costInPesos && !isAR` → `costInUsd && isAR` → `isAR` → `(CEDEAR‖arUsd)` → else (`valuation.js:519-525`) |
| `PositionsMobile` | cash → `isAR && costInUsd` → `isAR` → `(CEDEAR‖arUsd)` → `costInPesos` → else (`PositionsMobile.jsx:684-757`) |
| `Positions` desktop (`calcUSDT`) | cash → `costInPesos` → `(CEDEAR‖arUsd)` → else (`Positions.jsx:1259-1310`) |

El código canónico avisa: *"EL ORDEN DE LAS RAMAS IMPORTA"* (`valuation.js:518`). Para un lote CEDEAR con `currency='ARS'` en cuenta USD, desktop y mobile entran por ramas distintas (y hoy convergen en el número), pero es una convergencia por coincidencia, no por construcción. `[I]` — verifiqué que los números coinciden en ese caso concreto; no verifiqué todos los cruces.

#### D-10. `cedearRate` vs `tcValuacion`: coinciden hoy por accidente

El canónico usa `cedearRate` para TODO el path ARS —cash y tenencias— (`valuation.js:626-628`, `:657`). Varias reimplementaciones usan `tcValuacion`:

- `Dashboard.jsx:326-331` (`positionsForInsight`, rama isARS): `valueUsd = (trust ? mktArs : realCost) / tcValuacion`
- `Dashboard.jsx:536` (sync unrealized): `pnlForBroker = pnlArs / tcValuacion + pnlUsdDirect`
- `Insights.jsx:438-440` (`holdingValueUsd`, rama ARS): `mktArs / tcValuacion`
- `AssetDetail.jsx:71-74`, `PositionDetailMobile.jsx:113`, `PositionsMobile.jsx:722`

En todas esas páginas `tcValuacion` y `tcCedear` salen de la MISMA llamada `pickFinancialRate(dolar, valuationDollar)` (`Dashboard.jsx:192-193`, `Insights.jsx:404-405`, `AssetDetail.jsx:151-152`, `PositionsMobile.jsx:629-630`), así que hoy son iguales. Solo divergen si `pickFinancialRate` devuelve `undefined` (sin `/dolar`), donde `tcValuacion` cae a `config.tc_blue` y `tcCedear` a `tcValuacion` — o sea siguen iguales. **La divergencia está latente, no activa.** El propio código ya se comió este bug una vez: *"Esta función usaba tcValuacion, así que cada fila salía MEP/blue veces más grande que su aporte al total: … 10 filas que sumaban USD 64.147,88 daban un TOTAL de USD 56.582,51"* (`frontend/src/pages/Positions.jsx:1315-1322`). `[V]`

#### D-11. Dos "dólares del asesor" para el mismo libro

| | rate |
|---|---|
| `backend/main.py:36806-36827` `_advisor_book_fx` | `mep_venta` de `fx_rates_daily` — la **punta de venta** |
| `backend/advisor_brief.py:163-177` `_fx` | `main._current_cedear_rate()` — el **MEDIO**, "misma fuente que el snapshot" |

El comentario de `_fx` dice por qué: *"si no, el valor vivo y el snapshot se valúan con dólares distintos y aparece una pérdida fantasma de ~0,7% todos los días (audit)"*. Ese arreglo se aplicó al brief y **no** a `_advisor_book_fx`, que es el que valúa el libro, los informes y el contexto de la IA (su propio docstring dice *"Los tres tienen que valuar con el MISMO dólar"* — y los tres usan la punta, distinto del brief y del frontend, que usan el medio: `CurrencyContext.jsx:51`). `[V]`

#### D-12. Los snapshots se escriben con dos criterios y el cron pisa al navegador (pero no al revés)

- El navegador postea `total_value` calculado en el cliente (`Dashboard.jsx:478`) — solo si `valuationDollar === 'mep'` y la cobertura de precios ≥95% (`Dashboard.jsx:467-472`), una vez por día por `localStorage`.
- El cron recalcula server-side y **pisa** la foto del navegador: `source = 'cron', base = 'mercado', apto = 1` (`backend/snapshots_job.py:786-789`).
- El navegador **no** pisa al cron: `if _prev["source"] == "cron"` solo actualiza `net_deposited` y el fx (`backend/main.py:5055-5064`).

Los dos números salen de motores distintos (#2 vs #10), así que una misma fecha puede tener dos valores según quién escribió último. Es explícitamente el diseño, pero significa que la serie mezcla dos motores. `[V]`

#### D-13. `cash_value` suma pesos con dólares — documentado y no arreglado

`backend/main.py:32833-32852`: `SELECT COALESCE(SUM(invested), 0) AS cash FROM positions WHERE is_cash = 1`, sin convertir moneda. El comentario del propio código: *"Hoy, en 'IOL', ya devuelve pesos crudos rotulados como dólares — un defecto PREEXISTENTE"*, y el mitigante es *"nadie lo consume"*. Verifiqué: `cash_value` aparece en `frontend/src/utils/demo.js:668` como literal de fixture y en ningún otro lado del frontend. `[V]`

#### D-14. `top_holdings` ordena por COSTO, no por valor de mercado

`backend/main.py:32809-32821`: `ORDER BY invested_usd DESC LIMIT 3`, donde `invested_usd = invested / (CASE WHEN currency='ARS' THEN <config.tc_mep> ELSE 1 END)`. Usa el `tc_mep` de `config` (estático, default 1415 — `:32805`), no el rate live. Se llama "Top 3 holdings" pero es "top 3 por lo que pusiste", no "por lo que vale". El comentario lo llama *"proxy útil"*. `[V]`

#### D-15. El demo tiene su propia valuación, más simple

`frontend/src/utils/demo.js:200-260`: declara ser *"el mismo algoritmo que computeBrokerValue"* pero no tiene `trustMktValue`, ni `costInPesos`/`costInUsd`, ni factor cripto, ni la rama CEDEAR/`· USD`. Es un fixture, no producción — pero es el número que ve un prospecto. `[V]`

#### Lo que SÍ converge

- `trustMktValue` frontend ↔ `_trust_mkt_value` backend: bandas idénticas `[0.02,4]` / `[0.002,50]` y mismo trato del override. `[V]` (`valuation.js:448-455` vs `snapshots_job.py:42-54`)
- El costo de un lote USD en broker ARS: `test_broker_value_usd.py:29-58` pinnea que `invested` NO se divide por el MEP y que el valor va por `.BA÷MEP` o por NAV según el instrumento — con el comentario *"Debe dar números idénticos al frontend (computeBrokerValue / usdLotValue)"*.
- Las comisiones como parte del cost basis: `frontend/src/utils/valuation.test.js:428-465` lo pinnea para broker USD y ARS.
- `price_override = 0` es un precio válido, no "sin precio": `valuation.test.js:404-414` y `backend/snapshots_job.py:293-295`.
- La suma de las filas = el total del broker: `Positions.jsx:1374-1380` documenta el bug (10 filas sumando 64.147,88 sobre un total de 56.582,51) y `sumRowUSDT`/`sumRowARS` lo cierran.
- `ledger_replay.valor_en` y `_valuate_positions_for_chat` y `_advisor_positions_valued` **delegan** en `compute_broker_value_usd` en vez de reimplementar — y el docstring de `valor_en` explica por qué (`backend/ledger_replay.py:198-207`).

---

### Zonas grises

**Z-1. La palabra "canónico" aparece en el código de cinco funciones distintas.** `valuePositionLot` se autodenomina la que *"va a serlo"* pero *"todavía NO la consume nadie más"* (`valuation.js:504-511`); `compute_broker_value_usd` se llama *"el motor canónico del snapshot"* (`main.py:36956`); `_position_value_usd` es *"el valuador canónico"* según `ai/builders/dashboard.py:52`. Son tres cosas distintas con tres resultados distintos para el mismo lote. No pude determinar cuál es la que el producto considera la verdad. `[I]`

**Z-2. `total_value` es una columna con dos significados.** El mismo `double precision` guarda "posiciones × precio" (cron, browser, reconstructor) y "capital_final de la contabilidad" (import). Las columnas `base`/`apto` existen para desambiguar, pero el filtro se aplica **en el consumidor y no en la query** (`backend/main.py:36788-36792`), así que hay ~40 lectores y cada uno tiene que acordarse. El código nombra por lo menos seis lectores que se olvidaron: `main.py:11592`, `main.py:11855`, `main.py:18060`, `main.py:34515`, `main.py:36797` y `main.py:37915` leen `total_value` sin `apto`. Ese es exactamente el patrón que produjo el "−47,26% en el informe firmado" (`main.py:35630-35635`). `[I]` — verifiqué que las queries existen y no filtran; no verifiqué el impacto de cada una.

**Z-3. Un comentario que describe un bug que la línea de abajo ya arregla.** `backend/main.py:32663` abre con *"ACÁ NACE LA ASIMETRÍA QUE NADIE VIO. Las cuatro métricas que salen de esta función —delta_1d, delta_7d, delta_30d e YTD— filtran su borde de APERTURA con mucho cuidado … y las cuatro reciben el borde de CIERRE de esta query, SIN FILTRAR"*, y ocho líneas después el código llama `fetch_latest_measured_snapshot(conn, uid, accept=(_MED, _IND))` (`:32676`), que **sí** filtra. O el comentario quedó viejo tras el fix, o describe otra ruta que no encontré. Lo dejo anotado porque es el tipo de comentario que el próximo lector va a creer. `[I]`

**Z-4. `_position_value_usd` no distingue el fallback "sin precio" del valor real.** Devuelve `invested` en los dos casos, sin un flag. `ai/builders/insights.py` sí lleva un `has_live_price` por holding (`:479-481`, `:503`) para no publicar un unrealized falso, pero los detectores de `behavioral.py` (concentración, exposición geográfica, liquidez) suman `_position_value_usd` sin poder saber cuánto de ese total es costo disfrazado de mercado. `[V]`

**Z-5. El cron aborta el snapshot con <95% de cobertura; el navegador también; el reconstructor no.** `backend/snapshots_job.py:711-720` y `frontend/src/pages/Dashboard.jsx:469` cortan. `backfill_historical_mtm` en cambio **escribe igual** y estampa `mtm_coverage` (`backend/scripts/backfill_historical_mtm.py:410-428`), delegando la decisión al lector. El propio docstring del endpoint admite que para el perfil argentino la cobertura da ~50% y *"todavía no entrega la curva"* (`backend/main.py:30668-30672`). O sea: hay filas en `snapshots` cuyo `total_value` es mitad mercado y mitad costo, y el único aviso es una columna que varios lectores no piden. `[V]`

**Z-6. Un `total_value = 0` es una medición válida en el cierre y basura en la apertura.** `fetch_snapshot_at_or_before` lleva un `require_positive` opcional justamente por eso: *"como borde de ARRANQUE, un 0 no sirve: es el denominador del período … pero como borde de CIERRE, una cartera legítimamente vacía NO es 'no hay medición': es una medición DE CERO"* (`backend/reporting/builder.py:345-357`). O sea el mismo número, en la misma columna, es dato o es hueco según de qué lado de la resta caiga — y son 160 usuarios cuya última fila medida se descartaba por esto. La gris: el flag lo decide cada caller, no la columna. `[V]`

**Z-7. El P&L no realizado que se guarda en la base lo calcula el NAVEGADOR.** `frontend/src/pages/Dashboard.jsx:495-585` recorre las posiciones, calcula `pnlForBroker` con una implementación propia (#19) y hace `api.post('/monthly/sync-unrealized', ...)` por cada broker + global. El backend lo toma tal cual y lo convierte en `capital_final` (`backend/main.py:11069-11082`), que después alimenta la cadena mensual, el CAGR y los snapshots que fabrica el import. Un usuario que nunca abre el Dashboard (o lo abre con precios a medio cargar — hay un guard de cobertura en `:497`) tiene una cadena contable congelada. `[V]`

**Z-8. `_valuate_positions_for_chat` y `get_realized_vs_unrealized` leen los brokers sin `parent_broker_id`.** `SELECT id, name, currency FROM brokers` (`backend/main.py:22845-22847` y `:25434-25436`), mientras que el cron (`snapshots_job.py:663-665`), el replay (`ledger_replay.py:222-224`) y el asesor (`main.py:36871-36873`) sí lo piden. `_broker_name_sets` degrada silenciosamente al regex del nombre cuando falta la columna. Efecto: para un sub-broker renombrado, el chat IA y la tool de P&L rutean el precio distinto que el cron. `[V]`

**Z-9. El clamp del reconstructor es una cuarta copia de `trustMktValue`, escrita a mano.** `backend/scripts/backfill_historical_mtm.py:521-535` reescribe las bandas `(0.02, 4.0)` / `(0.002, 50.0)` inline en vez de importar `sj._trust_mkt_value`, y agrega una regla que las otras tres no tienen: `if val < 0: trusted = False` (*"valor de mercado < 0 = SIEMPRE bug"*). Las otras tres tratan `mkt <= 0` como "sin costo con qué comparar → confiar" (`valuation.js:449`, `snapshots_job.py:48`, `behavioral.py:56`), o sea lo dejan pasar. `[V]`

**Z-10. `total_invested` de la tabla `snapshots` significa dos cosas.** El cron escribe el cost basis agregado (`snapshots_job.py:757`); el import escribe `net_deposited` acumulado (`persister.py:1237`, `:1296`). `frontend/src/utils/evolution.js:509-511` lee `netDeposited: +(s.net_deposited || s.total_invested || 0)` — usa `total_invested` como fallback de `net_deposited`, que es correcto para las filas del import y **no** para las del cron. `[V]`

**Z-11. No encontrado:** ninguna función que exponga "el valor de cartera incluyendo plazos fijos y futuros" ni ningún test que compare el hero de Cartera contra el `total_value` del snapshot del mismo día. Los tests de `valuation.test.js` y `test_broker_value_usd.py` pinnean la valuación por lote y por broker, pero no la equivalencia entre los cuatro motores.
