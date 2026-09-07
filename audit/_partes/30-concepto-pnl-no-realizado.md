## P&L no realizado / ganancia latente

### Definición según el código

En Rendi, «P&L no realizado» **no es un dato guardado que el sistema calcule una vez**: es una **resta entre dos números que se recalculan en cada render**, y la resta se llama distinto y se arma distinto según quién la haga.

La forma canónica, la que repite el 90 % de los sitios, es:

```
pnl_no_realizado = Σ(valor de mercado HOY de cada lote abierto) − Σ(costo de ese lote)
```

con cinco decisiones de negocio propias de Rendi, todas verificadas en el código:

1. **`costo = invested + commissions`** — las comisiones de compra son costo económico, no gasto aparte. `[V]` `frontend/src/utils/valuation.js:553` (`const realCost = (p.invested || 0) + comm`), espejado en `backend/snapshots_job.py:208`.
2. **Sin precio confiable → P&L exactamente 0, no `null`.** Si el feed no contestó, o si el guard anti-distorsión rechaza la cotización, el lote se valúa **al costo** y aporta cero. `[V]` `frontend/src/utils/valuation.js:420` y el guard `trustMktValue` en `frontend/src/utils/valuation.js:449-454` (renta fija: banda `[0.02×, 4×]`; el resto `[0.002×, 50×]`). Es una decisión deliberada: prefiere subestimar a publicar un ×100 de un bono per-100.
3. **Modelo FX-neutral por default en lo que se PERSISTE**: para un broker ARS, costo y valor se convierten a USD con el **mismo** dólar de hoy, así los pesos quietos no generan «ganancia fantasma» cambiaria. `[V]` `frontend/src/utils/valuation.js:26-35`.
4. **Pero en PANTALLA el default es el contrario**: el modo «Costo en dólares» arranca en **`'purchase'`** (`[V]` `frontend/src/contexts/CurrencyContext.jsx:102-109`), o sea el costo va al `tc_compra` del lote → **el P&L no realizado que ve el usuario incluye la devaluación**, mientras el que se guarda en la base no. Ver §divergencias.
5. **El cash tiene P&L 0 por construcción** (`investedUsd == valueUsd`), pero **entra igual a la suma** de `computeBrokerValue`. `[V]` `frontend/src/utils/valuation.js:632-640`.

Además hay **tres significados de «no realizado» que conviven con el mismo nombre** y NO son el mismo número:

| Significado | Dónde vive | Qué mide realmente |
|---|---|---|
| **A — latente vivo** | frontend (`computeBrokerValue`, KPI del Dashboard, Cartera, Insights, chat IA) | `valor hoy − costo`, **acumulado desde que compraste cada activo**. No tiene período. |
| **B — columna `monthly_entries.pnl_unrealized`** | base de datos | El MISMO número A, pero **sólo del mes calendario en curso**; forzado a `0` en todo mes cerrado. `[V]` `backend/main.py:9716-9731` |
| **C — «no realizado del período»** en Reportes día/semana | `backend/reporting/builder.py:1521-1531` | Un **residuo**: `delta_del_período − realizado_del_período`. Todo lo que se movió y no fue una venta. |

El propio código admite que A y C no son lo mismo: `[V]` `backend/reporting/builder.py:1544-1548` — *«`unrealized` de monthly_entries es el latente ACUMULADO desde que se compró cada activo …, no la variación del período»*.

Y hay un **cuarto** significado, aparte y correcto: el de los **futuros**, que es `(precio − entrada) × cantidad × dirección` y sí contempla el short. `[V]` `frontend/src/components/FuturosGroup.jsx:40-46`.

---

### Dónde se calcula

Ordenado: primero lo canónico, después los re-implementadores, después el backend, después los derivados.

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `frontend/src/utils/valuation.js:545-564` | `valuePositionLot` → `salida()` | **LA valuación por lote.** 6 ramas (cash, pesos-en-cuenta-USD, costo-USD-en-broker-ARS, ARS nativo, BYMA-en-broker-USD, USD nativo) | `pnlUsd: o.valueUsd - o.investedUsd` | **fuente canónica** |
| 2 | `frontend/src/utils/valuation.js:740-761` | `computeBrokerValue` | Suma `valuePositionLot` sobre los lotes del broker | `pnlUsd: value - invested,` / `pnlArs: valueArs - invArs,` | **fuente canónica** (agregada) |
| 3 | `frontend/src/utils/valuation.js:59-68` | docstring | Declara el contrato de persistencia | `ARS broker → result.pnlArs / tcValuacion` · `USD broker → result.pnlUsd` | contrato |
| 4 | `frontend/src/utils/valuation.js:355-420` | `valueEquityLot` | Valuación de un lote equity/CEDEAR para «Calidad de cartera» | `return { valueUsd, investedUsd, pnlUsd: valueUsd - investedUsd }` | fuente (paralela) |
| 5 | `frontend/src/utils/valuation.js:905-924` / `926-945` | `sumRowUSDT` / `sumRowARS` | Suma los lotes de UNA fila de la Cartera (no re-valúa el agregado) | `pnl = cs.every(c => c.pnl == null) ? null : cs.reduce((s, c) => s + (c.pnl \|\| 0), 0)` | fuente (fila) |
| 6 | `frontend/src/utils/valuation.js:449-454` | `trustMktValue` | Guard: si `mkt/costo` sale de banda, el lote cae a costo → P&L 0 | `return fixed ? (mult <= 4 && mult >= 0.02) : (mult <= 50 && mult >= 0.002)` | modulador |
| 7 | `frontend/src/utils/valuation.js:263-268` | `costBasisRate` | Elige el dólar del COSTO según el modo del usuario | `(costBasis === 'purchase' && p?.tc_compra > 0) ? p.tc_compra : currentRate` | modulador |
| 8 | `frontend/src/pages/Dashboard.jsx:211-215` | Dashboard (KPI «P&L no realizado») | El número grande de la pantalla principal | `const totalPnl = totalValue - totalCostBasis` | **consumidor visible** |
| 9 | `frontend/src/pages/Dashboard.jsx:496-591` | `useEffect` sync | **ESCRITOR #1** de `monthly_entries.pnl_unrealized`. Loop por lote hecho a mano, NO usa `computeBrokerValue` | `pnlForBroker = pnlArs / tcValuacion + pnlUsdDirect` (ARS) · `pnlForBroker += val - cost` (USD) | **fuente + escritor** |
| 10 | `frontend/src/components/MonthlySummary.jsx:241-306` | `syncUnrealizedForAll` | **ESCRITOR #2**. Sí usa `computeBrokerValue`, sin pasar `costBasis` | `const pnlForBroker = b.currency === 'ARS' ? result.pnlArs / tc : result.pnlUsd` | **fuente + escritor** |
| 11 | `backend/main.py:11038-11091` | `POST /api/monthly/sync-unrealized` | Persiste el número del navegador y recalcula `capital_final` | `capital_inicio + deposits − withdrawals + pnl_realized + pnl_unrealized` (l. 11073-11081) | **persistencia** |
| 12 | `backend/main.py:9660-9755` | `_repair_monthly_chain` | Fuerza `pnl_unrealized = 0` en TODO mes que no sea el calendario actual | `SET capital_inicio = ?, capital_final = ?, pnl_unrealized = 0` (l. 9726-9731) | **destructor deliberado** |
| 13 | `backend/main.py:11433-11512` | `_rollover_to_current_month` | Al cerrar un mes, lo pone en 0 y recalcula el cierre a costo | `clean_cap_final = cap_inicio_last + deposits_last - withdrawals_last + pnl_realized_last` (l. 11477) | destructor |
| 14 | `backend/main.py:9586-9594` | recalc post-import | Resetea `pnl_unrealized=0` en cada recomputación | `SET pnl_realized=?, pnl_unrealized=0,` | destructor |
| 15 | `frontend/src/pages/Positions.jsx:1262-1310` | `calcUSDT` | P&L por lote en broker USD (Cartera desktop) | `const pnl = value - realCost` (l. 1309) | fuente (fila) |
| 16 | `frontend/src/pages/Positions.jsx:1321-1365` | `calcARS` | P&L por lote en broker ARS; devuelve **`null`** si no hay precio | `const pnlArs = valueArs - realCostArs` (l. 1357) · `const pnlUsd = valueUsd - invUsd` (l. 1364) | fuente (fila) |
| 17 | `frontend/src/pages/Positions.jsx:1420-1436` | fila `_multiCcy` | Fila que fusiona pata pesos + pata dólar | `const pnlUsd = valueUsd - investedUsd` (l. 1431) | fuente (fila) |
| 18 | `frontend/src/pages/Positions.jsx:1501-1520` | `valuePos` | Valuación cross-broker para la zona Renta Fija | `const pnlUsd = valueUsd - invUsd` (l. 1511, 1519) | fuente |
| 19 | `frontend/src/pages/Positions.jsx:1586-1599` / `1652-1672` | `totals` / hero «Tu cartera hoy» | Total de la Cartera; suma plazos fijos | `const pnl = value - invested` (l. 1596) · `const heroPnl = heroValue - heroInvested` (l. 1659) | consumidor visible |
| 20 | `frontend/src/pages/PositionsMobile.jsx:770-792` | memo por lote | P&L por lote en mobile, **con dos versiones** (modo y a-hoy) | `const pnlUsd = valueUsd - investedUsdDisplay` · `const pnlUsdToday = valueUsd - investedUsd` | fuente (mobile) |
| 21 | `frontend/src/pages/PositionsMobile.jsx:939-946` | fila agrupada | Suma los lotes de la fila | `const pnlUsd = valueUsd - investedUsd` | fuente (mobile) |
| 22 | `frontend/src/pages/PositionDetailMobile.jsx:111-174` | detalle de posición mobile | 5 ramas propias | `pnlUsd = valueUsd - investedUsdDisplay` (l. 127, 150) · `pnlUsd = valueUsd - u.investedUsd` (l. 138) | fuente (mobile) |
| 23 | `frontend/src/pages/AssetDetail.jsx:34-164` | `valueLot` + `agg` | Ficha del activo (desktop) | `const pnlUsd = valueUsd - investedUsd` (l. 164) | fuente |
| 24 | `frontend/src/pages/HomeMobile.jsx:110-116` | `totals` | Hero del home mobile | `const totalPnl = totalValue - totalCost` (l. 114) | consumidor visible |
| 25 | `frontend/src/pages/HomeMobile.jsx:206-260` | «mejor activo» | Ranking por % latente | `const pct = (value - invested) / invested` (l. 257) | consumidor |
| 26 | `frontend/src/pages/Dashboard.jsx:302-381` | `positionsForInsight` | P&L por posición para tortas/atribución. **Otra** re-implementación por lote | `pnlUsd = valueUsd - u.investedUsd` (l. 319, 340) · `pnlUsd = valueUsd - invUsd` (l. 330) · `pnlUsd = valueUsd - realCost` (l. 351) · `pnlUsd = valueUsd - cost` (l. 367) | fuente |
| 27 | `frontend/src/pages/Insights.jsx:524-528` | hero de Métricas | «Cost basis y P&L no realizado (live…)» | `const unrealizedPnl = totalPortfolio - totalCostBasis` | consumidor visible |
| 28 | `frontend/src/pages/Insights.jsx:2010-2036` | `aiPositions` | P&L por posición para tortas + snapshot IA. **Otra** re-implementación | `const pnlUsd = valueUsd - investedUsd` (l. 2036) | fuente |
| 29 | `frontend/src/hooks/usePfRollup.js:34-38` | `pfUsd` | Plazos fijos: interés devengado tratado como P&L latente | `pnlUsd: valueUsd - investedUsd` | fuente |
| 30 | `frontend/src/components/FuturosGroup.jsx:40-46` | `noRealizado` | **Único sitio con la fórmula de derivados** (respeta short) | `const pnl = (precio - pos.entry_price) * pos.quantity * dir` | fuente |
| 31 | `frontend/src/components/RentaFijaSections.jsx:310-312` | fila de renta fija | «P&L con cupones» = latente + cobranzas realizadas | `const pnlAdjUsd = (v.pnlUsd \|\| 0) + (summary?.pnlContributionUsd \|\| 0)` | consumidor |
| 32 | `frontend/src/utils/assetPnl.js:150-162` / `241` | `computePnlByKey` | Las 3 patas del resultado por clase/sector | `b.unrealized += p.pnl_usd` (l. 159) · `b.total = b.realized + b.unrealized + b.income` (l. 241) | agregador |
| 33 | `frontend/src/utils/insightsModel.js:270-295` | `computeAssetContribution` | Contribución por activo | `cur.unrealized += p.pnl_usd` (l. 287) · `.map(x => ({ ...x, pnl: x.realized + x.unrealized }))` (l. 293) | agregador |
| 34 | `frontend/src/utils/insightsModel.js:571-663` | `applyMtmToMonthly` | Reemplaza la cadena contable (que tiene el latente en 0) por snapshots MtM | `capital_inicio: snapPrev.value, capital_final: snapCur.value` (l. 662) | corrector |
| 35 | `frontend/src/utils/diagnostics.js:600-618` | regla `unrealized_dominates` | Alerta cuando ≥75 % del P&L es latente | `const share = (unrealizedPnl / totalPnl) * 100` | consumidor |
| 36 | `frontend/src/utils/diagnostics.js:749-780` | rachas mensuales | Racha positiva/negativa mes a mes | `const totalPnl = (m.pnl_realized \|\| 0) + (m.pnl_unrealized \|\| 0)` | consumidor |
| 37 | `frontend/src/hooks/useMonthlyData.js:339-390` | hook mensual | Lee `pnl_unrealized` del entry; lo usa como proxy del delta si falta capital | `deltaUsd = pnlRealized + pnlUnrealized` (l. 386) | consumidor |
| 38 | `backend/snapshots_job.py:158-319` | `compute_broker_value_usd` | **Port fiel de `computeBrokerValue` a Python.** Devuelve `{value, invested}` — el latente es la resta, que hace el caller | `return {'value': value, 'invested': invested}` (l. 319) | **fuente canónica backend** |
| 39 | `backend/snapshots_job.py:744-796` | job de snapshot | Persiste `total_value` y `total_invested` — el latente queda implícito | `total_invested += r['invested']` (l. 754) | persistencia indirecta |
| 40 | `backend/main.py:22818-22945` | `_valuate_positions_for_chat` | Snapshot valuado que ve la IA, por holding | `h["unrealized_pnl_usd"] = round(h["value_usd"] - h["invested_usd"], 2)` (l. 22921) · `"total_unrealized_pnl_usd": round(total_value - total_invested, 2)` (l. 22938) | fuente (IA) |
| 41 | `backend/main.py:25385-25520` | tool `get_realized_vs_unrealized` | **La «referencia canónica» declarada** para la IA | `unrealized_usd = market_value_usd - invested_usd` (l. 25483) · `combined_pnl_usd = realized_usd + unrealized_usd` (l. 25485) | fuente (IA) |
| 42 | `backend/reporting/builder.py:888-894` | período = mes | Lee la columna cruda | `unrealized = float(me.get("pnl_unrealized") or 0)` | consumidor |
| 43 | `backend/reporting/builder.py:1112-1130` | período = año | Toma el latente **del último mes**, no la suma | `unrealized = float(rows[-1]["pnl_unrealized"] or 0)` | consumidor |
| 44 | `backend/reporting/builder.py:1521-1531` | período = día/semana | **Lo DERIVA como residuo** | `unrealized = delta_usd - realized` (l. 1531); con filtro de broker: `unrealized = 0.0` (l. 1529) | **fuente alternativa** |
| 45 | `backend/reporting/builder.py:1656` | `PeriodMetrics` | Lo publica en la API de Reportes | `unrealized_pnl=round(unrealized, 2),` | salida |
| 46 | `backend/reporting/detectors.py:294-317` | `detect_realized_vs_unrealized_gap` | Insight «cerraste ganancias pero arrastrás pérdidas abiertas» | `if unrealized > -realized * 0.5: return None` | consumidor |
| 47 | `backend/behavioral.py:391-482` | `_position_value_usd` | **Motor de valuación #3** (Análisis / behavioral / objetivos). Sirve valor Y costo según `honor_override` | `cost_usd = (invested_native / rate_holdings) if (cost_ccy == "ARS" …) else invested_native` (l. 470) | fuente |
| 48 | `backend/ai/builders/insights_attribution.py:88-93` | atribución por ticker | Latente por ticker usando el motor #3 | `unrealized_by_ticker[asset] = … + (mv_usd - invested_usd)` | fuente (IA) |
| 49 | `backend/ai/builders/insights.py:493-515` | packet de Insights | Latente total de la cartera; **`None` si no hay ningún precio live** | `unrealized_pnl_total_usd += h["market_value_usd"] - h["invested_usd"]` (l. 503) | fuente (IA) |
| 50 | `backend/ai/builders/position.py:96-97` | ficha de posición para IA | | `pnl_usd = current_value_usd - invested_usd` | fuente (IA) |
| 51 | `backend/main.py:36930-36943` | libro del asesor (por cliente) | Latente por posición cross-cliente | `"pnl_usd": value - invested,` (l. 36942) | fuente (asesor) |
| 52 | `backend/main.py:37733-37743` | `/api/advisor/book` | Latente agregado por activo del libro | `"pnl_usd": round(b["value_usd"] - b["invested_usd"], 2),` (l. 37742) | fuente (asesor) |
| 53 | `backend/wrapped.py:144, 167, 192, 450, 459` | Wrapped anual | P&L del año y mejor/peor mes | `pnl_usd = sum((r.get('pnl_realized') or 0) + (r.get('pnl_unrealized') or 0) for r in rows)` | consumidor |
| 54 | `backend/scripts/backfill_historical_mtm.py:504-545` | backfill histórico MtM | Reconstruye el latente de meses pasados con precios de cierre | `u = val - inv` (l. 524); si el guard no confía: `u = 0.0` (l. 540) | fuente (histórica) |
| 55 | `backend/twr.py:2195-2199` | motor TWR | Declara al frontend que el modo estimado **no cuenta** el latente | `"excluye_no_realizado": (modo == MODO_ESTIMADO),` | metadato |
| 56 | `backend/main.py:11838-11895` | `/api/insights/mtm-audit` | Reconcilia la cadena a costo (latente 0) contra la de mercado | `ci_m, cf_m, modo = sp["value"], sc["value"], "ambos"` | diagnóstico |

---

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `frontend/src/pages/Dashboard.jsx:903-916` | KPI del Dashboard | **«P&L no realizado»**, sub `«X% sobre costo»`; tooltip: *«Ganancia "en papel" … = valor actual − costo de compra»* |
| `frontend/src/pages/Dashboard.jsx:855-865` | KPI de descuadre | «Diferencia sin explicar» / «Dividendos e intereses» — nace de `realizedPnl + totalPnl − totalReturnUsd` (l. 291) |
| `frontend/src/pages/Positions.jsx:1870-1877` | hero de Cartera | píldora con `+USD …` / `+ARS …` (sin la palabra «no realizado») |
| `frontend/src/pages/Positions.jsx:80-81` | columnas de la tabla | **«P&L USD»** y **«P&L %»** |
| `frontend/src/pages/Positions.jsx:2334`, `2619` | tooltip de bonos | *«P&L = mark-to-market (…) + … de ganancia realizada (cupones…)»* |
| `frontend/src/pages/PositionsMobile.jsx:52` | orden mobile | **«P&L %»** |
| `frontend/src/pages/PositionDetailMobile.jsx:236-245, 299-303` | detalle mobile | monto + % sin etiqueta explícita |
| `frontend/src/pages/AssetDetail.jsx:243` | ficha del activo | **«no realizado»** (sufijo del monto) |
| `frontend/src/pages/HomeMobile.jsx:110-116` | hero mobile | monto + % del portfolio |
| `frontend/src/pages/Insights.jsx:524-528, 2340` | Métricas → diagnósticos | se pasa al pool como `unrealizedPnl // P&L abierto` |
| `frontend/src/utils/diagnostics.js:612` | tarjeta de diagnóstico | *«El **N%** de tu P&L total está sin realizar … ganancia "en papel" que puede esfumarse»* |
| `frontend/src/components/MonthlySummary.jsx:590` | tabla /mensual, vista detallada | columna **«P&L No Realizado»** (0 en todos los meses menos el último) |
| `frontend/src/components/MonthlySummary.jsx:650` | fila de totales | total de la columna |
| `frontend/src/components/MonthlySummary.jsx:728` | modal de edición | input editable **«P&L No Realizado»** |
| `frontend/src/components/reports/MonthCard.jsx:226` | Reportes, grilla técnica | celda **«No realizado»** |
| `frontend/src/pages/Reports.jsx:569-576` | Reportes, strip de KPIs | **«P&L no realizado»**, sub **«mark-to-market»** |
| `frontend/src/components/reports/InsightEvidence.jsx:167-179, 279` | evidencia del insight | cuadro **«No realizado»** (siempre pintado en rojo, ver zonas grises) |
| `frontend/src/components/CompositionDonut.jsx:283-296` | tortas tipo/sector | fila **«Resultado»** de cada porción (= no realizado + realizado + renta) |
| `frontend/src/components/FuturosGroup.jsx:130-134, 192` | Cartera → Futuros | **«no realizado»**; pie: *«El no realizado todavía no es plata tuya»* |
| `frontend/src/components/advisor/BookComposition.jsx:66-95` | libro del asesor | «Resultado» por porción; comentario admite que la torta por activo muestra *«solo no realizado»* |
| `frontend/src/pages/Admin.jsx:1651-1710` | Admin | auditoría costo-vs-mercado (`pnl_unrealized = 0` en cerrados) |
| `frontend/src/pages/Admin.jsx:1446`, `2824`, `2911` | Admin | botón «Valuación histórica (MTM)» |
| `backend/main.py:24745-24746` | tool schema de la IA | *«desglose preciso de P&L realizado … vs P&L unrealized (mark-to-market actual de posiciones abiertas)»* |
| `backend/main.py:25513-25519` | `_note` que viaja al LLM | *«NUNCA mezclar realized con unrealized en una sola afirmación sin etiquetar el bucket»* |
| `backend/main.py:20536` | system prompt | *«Si tiene posición unrealized grande, mencionalo»* |
| `frontend/src/pages/Insights.jsx:1070` | Métricas | *«· sólo se mueve cuando vendés»* cuando `perf.excluye_no_realizado` |

---

### Dónde se persiste

**Sí se persiste, en una sola columna, y sólo para un mes:**

| Tabla | Columna | Tipo | Semántica real |
|---|---|---|---|
| `monthly_entries` | `pnl_unrealized` | `double precision DEFAULT 0` `[V]` `backend/schema_pg.sql:1200` y `:1224` (ALTER idempotente) | Latente **acumulado** (no del mes) del broker, **en USD**, **sólo** en la fila del mes calendario en curso. `0` en todas las demás. |

Confirmado también en el esquema SQLite embebido en el código: `[V]` `backend/main.py:1053` y `:1071` (`pnl_unrealized REAL DEFAULT 0`), y en la copia de desarrollo (`sqlite3 backend/trading.db ".schema monthly_entries"`).

**Cómo entra y cómo sale:**
- Entra **sólo** por `POST /api/monthly/sync-unrealized` `[V]` `backend/main.py:11038`, llamado desde exactamente **dos** lugares del frontend: `frontend/src/pages/Dashboard.jsx:588,590` y `frontend/src/components/MonthlySummary.jsx:298,300`. Verificado con grep: no hay ningún otro caller en todo el repo.
- También se puede **escribir a mano**: el modal de /mensual expone el campo (`frontend/src/components/MonthlySummary.jsx:728`) y `POST/PUT /api/monthly` lo aceptan (`backend/main.py:11422`, `12000`, `12022-12023`).
- Se **borra** en cuatro lugares: `_repair_monthly_chain` (`backend/main.py:9726-9731`), `_rollover_to_current_month` (`backend/main.py:11481`), el recalc post-import (`backend/main.py:9592`) y el propio `sync-unrealized` (`backend/main.py:11066`, que pone en 0 todas las filas menos la del mes actual).

**Persistencia indirecta:** `snapshots.total_value` y `snapshots.total_invested` (`backend/schema_pg.sql:1525-1539`) — el latente es su resta, pero nunca se guarda como tal. `snapshots.holdings_json` guarda `[{asset, value_usd}]` para atribución (`backend/main.py:1404-1410`), sin costo → de ahí **no** se puede derivar el latente por activo.

**Nunca se persiste:** el latente **por posición** (`positions` no tiene columna de P&L — `[V]` `sqlite3 backend/trading.db ".schema positions"`), el de **futuros** (se recalcula en el navegador cada vez, `frontend/src/components/FuturosGroup.jsx:111-114`) y el de **plazos fijos** (se deriva de `computePf`).

---

### ⚠️ Implementaciones divergentes

**NO hay una sola implementación.** Conté **al menos 14 cálculos independientes del mismo concepto** (9 en frontend, 5 en backend), y el propio código lo dice: `[V]` `frontend/src/utils/valuation.js:761-773` — *«había CINCO implementaciones de la valuación por lote … y ninguna era "la buena a la que volver" … Esta es la que va a serlo. **Todavía NO la consume nadie más**»*. `valuePositionLot` es canónica **sólo a través de `computeBrokerValue`**; las filas de la Cartera desktop, mobile, el detalle mobile, la ficha del activo y los dos loops de tortas siguen teniendo su propia aritmética.

#### D-1 · El número que se MUESTRA usa otro dólar que el que se GUARDA (el más grave)

| | KPI del Dashboard | Lo que se persiste |
|---|---|---|
| Sitio | `frontend/src/pages/Dashboard.jsx:211-214` | `frontend/src/pages/Dashboard.jsx:496-591` y `frontend/src/components/MonthlySummary.jsx:285-287` |
| Modo de costo | **el del usuario**, que por default es `'purchase'` `[V]` `frontend/src/contexts/CurrencyContext.jsx:102-109` | **siempre `'today'`** (Dashboard no aplica `costBasisRate`; MonthlySummary llama a `computeBrokerValue` con 6 args → default `'today'`) |
| Qué incluye la devaluación | **sí** (el costo va al `tc_compra` del lote) | **no** (costo y valor al mismo dólar de hoy) |

Consecuencia `[I]` (inferida de leer las dos rutas, no medida sobre datos): para un usuario que nunca tocó `/config`, el KPI **«P&L no realizado»** del Dashboard y el `pnl_unrealized` que ese mismo Dashboard acaba de postear pueden diferir por toda la devaluación acumulada de los lotes en pesos. El comentario de `MonthlySummary.jsx:288-296` explica que se eligió a propósito no persistir el modo (*«lo persistido no puede moverse con un toggle»*), pero el Dashboard sigue mostrando el otro número al lado.

#### D-2 · Los dos escritores de la misma columna no calculan igual

| | Dashboard (`:496-591`) | MonthlySummary (`:241-306`) |
|---|---|---|
| Motor | loop a mano, ~90 líneas, 5 ramas | `computeBrokerValue` (canónico) |
| Broker ARS | `pnlArs / tcValuacion + pnlUsdDirect` (l. 536) | `result.pnlArs / tc` (l. 287) |
| Guard de cobertura de precios | **sí**: `priceCoverage >= 0.95` (l. 499) | **no** |
| Riel MEP/CCL | **escribe igual esté en MEP o CCL** | **sólo escribe en MEP** (`persistMep`, l. 282, 298, 300) |
| Cuándo corre | al montar `/dashboard` | al montar `/mensual` y después de cada guardado |

`[V]` La divergencia MEP/CCL está documentada del lado de MonthlySummary (`:278-281`: *«Si el user está en CCL … NO escribimos pnl CCL-flavored al backend»*) pero **no implementada del lado del Dashboard**: el `useEffect` no consulta `valuationDollar` en ningún lado (verificado leyendo las líneas 496-591 completas). Un usuario con el riel en CCL que abra el Dashboard escribe un latente CCL-flavored; si después abre /mensual en CCL, ese no se corrige (MonthlySummary no escribe). Gana el último que corra.

#### D-3 · El KPI del Dashboard incluye cosas que el número persistido no

| | Cash | Plazos fijos |
|---|---|---|
| KPI `totalPnl` (`Dashboard.jsx:212-214`) | **sí** (aporta 0) | **sí** — `pf.valueUsd − pf.investedUsd` = **interés devengado**, `[V]` `frontend/src/hooks/usePfRollup.js:36-38` |
| Sync persistido (`Dashboard.jsx:504-586`) | **no** (`if (p.is_cash) continue`, l. 508 y 539) | **no** (el loop sólo recorre `positions`) |

O sea: el intereses de un plazo fijo se publica bajo el rótulo «P&L no realizado» (que la propia tarjeta define como *«lo que pasaría si vendieras ahora»*) pero nunca llega a `monthly_entries`.

#### D-4 · Dentro de una misma pantalla, el hero y las tortas usan modos distintos

- **Dashboard**: el KPI usa `computeBrokerValue(..., costBasis)` → modo del usuario. Las tortas de tipo/sector consumen `positionsForInsight` (`:302-381`), cuya rama ARS hace `realCost / tcValuacion` **sin** `costBasisRate` → modo `'today'`. `[V]` líneas 327-330.
- **Insights/Métricas**: `unrealizedPnl` (`:526-528`) usa `.invested` con `costBasis`; `aiPositions` (`:2010-2036`) hace `investedUsd = realCost / tcValuacion` **sin** modo (l. 2028). Las dos cifras están en la misma página.

#### D-5 · «No realizado» del período en Reportes es tres cosas distintas según la pestaña

| Pestaña | Fórmula | Archivo |
|---|---|---|
| Mes | la columna cruda `pnl_unrealized` (latente **acumulado**, no del mes) | `backend/reporting/builder.py:894` |
| Año | `pnl_unrealized` **del último mes con filas**, no la suma del año | `backend/reporting/builder.py:1130` |
| Día / semana (global) | **residuo**: `delta_usd − realized` | `backend/reporting/builder.py:1531` |
| Día / semana (con filtro de broker) | **forzado a 0** | `backend/reporting/builder.py:1529` |

Las cuatro salen por el mismo campo `unrealized_pnl` de `PeriodMetrics` (`backend/reporting/schema.py:68`) y se pintan en la misma celda «No realizado» de `MonthCard.jsx:226`. El propio builder documenta que mezclar el acumulado con la variación del período es incorrecto (`:1544-1548`) — y aun así el mes publica el acumulado.

#### D-6 · Tres motores de valuación en el backend, no uno

| Motor | Archivo | Quién lo usa |
|---|---|---|
| `compute_broker_value_usd` (port fiel del frontend) | `backend/snapshots_job.py:158-319` | snapshots, chat IA (`main.py:22885`), `get_realized_vs_unrealized` (`main.py:25469`), libro del asesor, backfill MtM |
| `_position_value_usd` | `backend/behavioral.py:391-482` | Análisis/behavioral, atribución IA (`insights_attribution.py:91-92`), ficha de posición IA, objetivos (`main.py:15257-15263`) |
| `holdings_agg` de los builders | `backend/ai/builders/insights.py:493-515` | packet de Insights para la IA |

`[V]` Difieren en al menos un punto observable: `_position_value_usd` **no** suma `commissions` al costo (`invested_native = float(p.get("invested") or 0)`, `behavioral.py:426`), mientras que `compute_broker_value_usd` sí (`real_cost = (p.get('invested') or 0) + comm`, `snapshots_job.py:208`). Para la misma posición, la atribución de Análisis y el `get_realized_vs_unrealized` del chat devuelven costos distintos → latentes distintos.

Además, `insights.py:509-511` devuelve `None` cuando **ningún** holding tiene precio live (decisión honesta), mientras `get_realized_vs_unrealized` devuelve **0** en el mismo caso (`main.py:25449` inicializa en `0.0` y sólo suma si hay brokers y posiciones).

#### D-7 · Cartera desktop: la fila dice «—» y el total dice «0»

`[V]` `calcARS` devuelve `pnlArs: null, pnlUsd: null` cuando falta precio (`frontend/src/pages/Positions.jsx:1346`), pero el total del pie sale de `computeBrokerValue` (`:1591`), que en ese caso **valúa al costo** → aporta 0. La fila muestra un guion y el total la cuenta como neutra. No es un error numérico, pero son dos respuestas a la misma pregunta en la misma tabla.

#### D-8 · Mobile aplica el modo del usuario a la fila; desktop lo aplica a la fila Y al hero, con distinto tratamiento en pesos

`[V]` `PositionsMobile.jsx:786-793` mantiene **dos** P&L por lote (`pnlUsd` del modo y `pnlUsdToday` para las cifras en pesos). `Positions.jsx:1666-1672` hace lo análogo para el hero (`heroPnlArs` mode-independent). `PositionDetailMobile.jsx:127-174` usa `investedUsdDisplay` en 3 de sus 5 ramas y el costo crudo en las otras 2 (l. 162, 173). No verifiqué si esas dos ramas deberían llevar el modo — **es una asimetría sin comentario que la explique**.

#### Lo que SÍ converge

- El guard `trustMktValue` está portado con la misma banda en frontend (`valuation.js:449-454`), backend (`behavioral.py:_trust_mkt_value_usd`, usado en `:471`) y backfill (`backfill_historical_mtm.py:532-539`, banda `(0.02, 4.0)` / `(0.002, 50.0)` escrita a mano pero idéntica).
- El factor cripto (`cryptoBrokerFactor`) se aplica a valor **y** costo en todos los sitios que lo usan → el % latente queda invariante. `[V]` `valuation.js:684-685`, `Dashboard.jsx:574-581`, `snapshots_job.py:293`.
- `commissions` está incluida en el costo en todo el frontend y en `snapshots_job.py`. La excepción es `behavioral.py` (ver D-6).

---

### Zonas grises

1. **La columna se llama «no realizado» pero guarda un acumulado de años, y sólo en una fila.** `monthly_entries.pnl_unrealized` de agosto no es «lo que ganó agosto sin vender»: es todo el latente desde la primera compra. Reportes lo publica igual como métrica del mes (`builder.py:894`), y el propio builder dice en el comentario que eso está mal (`:1544-1548`) pero sólo lo aplica para negarse a *reemplazar* el delta, no para dejar de publicar la celda.

2. **La cadena contable mide sólo lo realizado, y el sistema lo sabe.** Con `pnl_unrealized = 0` en todo mes cerrado, el retorno Modified Dietz de cada mes histórico colapsa a `pnl_realized / capital_promedio` `[V]` `frontend/src/utils/insightsModel.js:573-583`. El backend lo publica como flag (`excluye_no_realizado`, `backend/twr.py:2199`) y el frontend lo rotula *«sólo se mueve cuando vendés»* (`Insights.jsx:1070`). Es una subestimación **sistemática y siempre para el mismo lado**, parcheada en tres lugares distintos y de tres maneras distintas: `applyMtmToMonthly` (frontend), los snapshots MtM (`builder.py:940-960`) y el backfill histórico. No hay un solo lugar donde el latente histórico esté guardado bien.

3. **`_repair_monthly_chain` decide «mes abierto» por calendario UTC; `MonthlySummary` lo decide por posición en el array.** `[V]` backend: `is_open = (row['year'] == current_year and row['month'] == current_month)` (`main.py:9701`). Frontend: `const isCurrent = idx === tabData.length - 1` (`MonthlySummary.jsx:544`). Si la última fila **no** es el mes actual (huecos en el calendario, o mes futuro cargado a mano), la tabla pinta el `pnl_unrealized` de una fila que el backend ya puso en 0 — o al revés, esconde el del mes vivo. No lo pude reproducir sin correr la app; lo dejo como discrepancia de criterio verificada en el código.

4. **El KPI de Reportes hardcodea «US$» incluso con el toggle en pesos.** `[V]` `frontend/src/pages/Reports.jsx:571-573`: `value: \`${…}US$ ${fmtNum(Math.abs(m.unrealized_pnl))}\``. Lo mismo en «Capital actual» (l. 541) y «P&L del período» (l. 553). `MonthCard.jsx:218` sí acepta un `money.fmtMoney` inyectado. O sea, la misma cifra respeta la moneda en un componente y no en el otro.

5. **`RealizedVsUnrealizedEvidence` pinta el «No realizado» siempre de rojo.** `[V]` `frontend/src/components/reports/InsightEvidence.jsx:174-177`: `className="… bg-rendi-neg/[0.08] …"` y `text-rendi-neg`, sin mirar el signo. Es coherente con el detector (que sólo dispara cuando el latente es muy negativo, `detectors.py:303-305`), pero el componente está registrado por código de insight (`:279`) y no valida el signo.

6. **Insights: numerador y denominador de la resta no filtran igual.** `[V]` `Insights.jsx:411-413` arma `totalPortfolio` con `.filter(x => x.value > 0)`, mientras `totalCostBasis` (`:525-527`) suma **todos** los brokers sin filtro. Un broker con valor ≤ 0 (cash negativo) sale del minuendo pero su costo se queda en el sustraendo. Es un caso borde, pero la resta de la línea 528 no es entre dos conjuntos iguales.

7. **En el Dashboard, «realizado» y «no realizado» se convierten a pesos con reglas distintas.** `[V]` El realizado usa convert-then-sum con el FX del mes de cada asiento (`Dashboard.jsx:250-262`, con el comentario explicando por qué); el no realizado usa `fmtSigned` = `× tcValuacion` de hoy (`:711-716`). Defendible (uno es un stock de hoy, el otro un flujo histórico), pero los dos salen uno al lado del otro sin nada que lo indique, y la «Diferencia sin explicar» de abajo (`:291`) se calcula en USD mezclando ambos.

8. **`sync-unrealized` recalcula `capital_final` con la fórmula canónica pero no vuelve a chequear el resultado.** `[V]` `backend/main.py:11073-11083`: acepta cualquier `pnl_unrealized_usd` que el navegador mande (validado sólo por `_FINITE_BOUND = 1e12`, `main.py:11096`) y lo suma a `capital_final`. El único clamp de plausibilidad que existe para el latente vive en el **backfill** (`backfill_historical_mtm.py:603-609`, *«el MTM NUNCA debe DEJAR un capital_final negativo»*), no en el endpoint live.

9. **`sumRowUSDT`/`sumRowARS` propagan `null` de forma asimétrica.** `[V]` `valuation.js:912` y `:933-934`: si **todos** los lotes tienen `pnl == null` devuelve `null`, pero si **uno solo** lo tiene, se suma como 0 y el `pnlPct` se calcula sobre el costo de los lotes que sí tienen valor (`:915-916`). El comentario explica el % pero no el monto: la fila muestra un P&L parcial sin marcarlo como parcial (a diferencia de `FuturosGroup`, que sí lo dice: *«no realizado · N de M»*, `:133`).

10. **Nadie mide el latente de los futuros ni el de los plazos fijos fuera del navegador.** `[V]` `FuturosGroup.jsx:60-64` pide sus propios precios y calcula al vuelo; `backend/main.py:12197-12202` (`_futuro_a_dict`, que sólo agrega `dir`) y `backend/main.py:12227-12240` (`GET /api/futures`) no devuelven ningún P&L. Los plazos fijos entran al KPI del Dashboard (D-3) pero no a `monthly_entries` ni a los snapshots. Ninguno de los dos aparece en el snapshot que ve la IA.

11. **El «modo mobile» del home nunca escribe.** `[V]` `HomeMobile.jsx` calcula `totalPnl` (l. 114) pero no llama a `sync-unrealized` (verificado con grep: los únicos callers son Dashboard y MonthlySummary). El main mobile (`App.jsx:337`, `Home.jsx:28`) enruta a `HomeMobile`. Un usuario exclusivamente mobile que nunca abra `/dashboard` ni `/mensual` deja `pnl_unrealized` en 0 para siempre — y ahí Reportes publica `unrealized_pnl: 0` como si fuera un hecho medido.

12. **`get_realized_vs_unrealized` se declara «la referencia canónica»** (`main.py:22877` la cita como tal para el descarte de posiciones huérfanas) pero es la única que descarta posiciones cuyo broker no existe, incluye el **cash** en `market_value_usd`/`invested_usd` (llama a `compute_broker_value_usd` con todos los lotes del broker, `main.py:25468-25471`) y a la vez cuenta `open_positions_count` **excluyendo** cash (`:25480-25481`). El `_note` que viaja al LLM dice `unrealized_pnl_usd = market_value_usd − invested_usd` sin aclarar que ahí adentro hay efectivo.

13. **La base de desarrollo (`backend/trading.db`) no tiene las columnas nuevas de `snapshots`** (`source`, `holdings_json`, `mtm_coverage`, `base`, `apto`) que `schema_pg.sql:1525-1539` sí declara. Todo lo que dije sobre clasificación de snapshots (`twr.py:52-56`) sale del **código**, no de esa base.
