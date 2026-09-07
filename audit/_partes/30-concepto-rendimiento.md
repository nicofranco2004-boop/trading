## Rendimiento / retorno (simple, TWR, anualizado, CAGR)

### Definición según el código

En Rendi «rendimiento» no es **un** número: son **cinco familias distintas** que conviven, cada una con su propia aritmética, y el código las mezcla en la misma pantalla más de una vez. Ordenadas de más canónica a menos:

**1. El primitivo: Modified Dietz de un tramo.** [V] `backend/twr.py:559-576`

```
denom = v0 + 0.5 * flow
return max((v1 - v0 - flow) / denom, -1.0)
```

El docstring lo dice explícito: *"Es EL primitivo: si alguna pantalla calcula el retorno de otra forma, vuelve a haber dos motores"* (`backend/twr.py:564-566`). El 0,5 pondera el aporte como si hubiera entrado a mitad del tramo. **Piso de −100 %, sin techo**, y el docstring justifica por qué no hay techo: el clamp de +50 % *"NO se le aplica al benchmark → el sesgo es sistemático en contra del usuario"* (`backend/twr.py:568-571`).

**2. TWR encadenado = Π(1 + r_tramo) − 1.** [V] Dos implementaciones canónicas conviven:
- `backend/twr.py:848-889` (`twr_de`) — sobre meses **sellados** en la tabla `twr_periods`. Es la vía del asesor.
- `backend/twr.py:1611-2213` (`curva_indexada`) — sobre la serie **diaria** de snapshots, encadenando `dietz` punto-apto a punto-apto. Es la vía de toda la app retail.

**3. CAGR.** [V] `backend/twr.py:2165-2172`:

```
años = _dias(ventana_desde, _c1) / 365.25
if años >= 0.5:                # bajo medio año, anualizar es propaganda
    cagr = idx ** (1.0 / años) - 1.0
```

Definición **no estándar respecto de lo que un libro llamaría CAGR**: no se anualiza sobre las fechas extremas de la curva sino sobre `ventana_desde`/`ventana_hasta` — la ventana que el índice **efectivamente midió** —, y **no se publica si la ventana es menor a medio año**. Ese piso es una decisión de producto, no de finanzas, y está documentada como tal.

**4. «Retorno total» simple (money-weighted degenerado).** [V] `frontend/src/pages/Dashboard.jsx:265-266`:

```
const totalReturnUsd = totalValue - netDeposited
const totalReturnPct = netDeposited > 0 ? totalReturnUsd / netDeposited : 0
```

Es el número del hero «Ganancia total». **No neutraliza el timing de los flujos**: es valor de mercado hoy contra capital aportado neto de toda la vida. Es la misma familia que usa el asesor para rankear clientes (`backend/main.py:37080`), donde el denominador se endurece al `MAX(net_deposited)` histórico.

**5. Rendimiento por activo = resultado / costo.** [V] `backend/main.py:37392-37404` (`_rate_pct`) y su espejo JS `frontend/src/utils/assetPnl.js:122-126`. Suma tres patas —no realizado + realizado + renta (cupones/dividendos)— sobre el costo actual, y **se apaga** cuando `|total| > cost × 10` porque *"el denominador se evaporó"*.

**Lo que Rendi define de forma explícitamente no estándar:**

- **`modo` certero vs estimado** (`backend/twr.py:1213-1214`). El *certero* sólo encadena puntos valuados a precio real; el *estimado* además encadena la **cadena contable** (`monthly_entries`), que para meses cerrados tiene `pnl_unrealized = 0` — o sea que **excluye lo no realizado por diseño** y el motor lo declara en la respuesta (`excluye_no_realizado`, `backend/twr.py:2199`). El estimado **gana** `twr`/`cagr` y **pierde** drawdown y pico (`backend/twr.py:2151-2158`).
- **`base_del_twr`** (`'mercado'` | `'contable'`, `backend/twr.py:2194`): con qué regla se calculó el número. Es el campo que le permite a un consumidor saber si el % que tiene enfrente sirve para pico/drawdown/volatilidad.
- **Cota de plausibilidad de un leg** (`backend/twr.py:623-648`, `leg_dudoso`): sin flujo que lo explique, un valor que se multiplica o divide por más de **3** entre dos fotos no se encadena (`SALTO_MAX_VECES = 3.0`, `backend/twr.py:612`); y si el denominador de Dietz cae por debajo del 25 % del capital de arranque (`DENOM_MIN_FRACCION = 0.25`, `backend/twr.py:620`), tampoco. Los umbrales salieron de medir sobre una copia de producción y están tabulados en el comentario (`backend/twr.py:601-605`).
- **El retorno «en pesos»** (`backend/twr.py:666-706`, `_leg_en_moneda`): cada **punta** al TC de su fecha y el **flujo** al TC medio geométrico del tramo. El stock (`net_deposited`) **no se convierte**; se resta primero en dólares. El docstring explica por qué (`backend/twr.py:696-706`).
- **La serie se PARTE, no se rellena** (`backend/twr.py:882-897`, `MAX_HUECO_DIAS = 45`, `MAX_HUECO_CONTABLE_DIAS = 400`). Con la serie partida **no se publica** ni TWR ni drawdown máximo.

---

### Dónde se calcula

Orden: primero el motor canónico, después sus wrappers, después lo divergente.

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `backend/twr.py:559` | `dietz(v0, v1, flow)` | El primitivo Modified Dietz de UN tramo | `denom = v0 + 0.5 * flow` · `max((v1 - v0 - flow) / denom, -1.0)` | **FUENTE** (SSoT) |
| 2 | `backend/twr.py:1611` | `curva_indexada(...)` | Curva indexada + TWR + CAGR + drawdown, encadenando `dietz` sobre `serie_medible` | `idx *= (1.0 + ret)` (l. 1876) · `"twr": (idx - 1.0) if (publicable and legs > 0) else None` (l. 2189) | **FUENTE** (motor retail) |
| 3 | `backend/twr.py:2165` | `curva_indexada` (bloque CAGR) | Anualiza sobre la ventana medida, con piso de medio año | `años = _dias(ventana_desde, _c1) / 365.25` · `if años >= 0.5: cagr = idx ** (1.0 / años) - 1.0` | **FUENTE** |
| 4 | `backend/twr.py:848` | `twr_de(conn, uid, ...)` | TWR encadenado sobre meses **sellados** | `idx *= (1.0 + float(f["ret"]))` (l. 883) · `"twr": idx - 1.0` (l. 887) | **FUENTE** (motor asesor) |
| 5 | `backend/twr.py:740` | `tramos(conn, uid, ...)` | Legs mensuales medibles; el `ret` que después se sella | `r = dietz(v0, v1, flow)` (l. 768) | FUENTE |
| 6 | `backend/twr.py:623` | `leg_dudoso(v0, v1, flow)` | La cota de cordura: qué leg NO se encadena | `ratio = v1 / v0` · `if ratio > SALTO_MAX_VECES or ratio < 1.0 / SALTO_MAX_VECES: return "salto"` | FUENTE (guard) |
| 7 | `backend/twr.py:666` | `_leg_en_moneda(p0, p1, v0, v1)` | Pasa un leg a pesos: puntas a su TC, flujo al TC medio geométrico | `return v0 * f0, v1 * f1, flow * ((f0 * f1) ** 0.5)` (l. 704) | FUENTE (FX del retorno) |
| 8 | `backend/twr.py:650` | `_factor_fx(p0, p1)` | Arrastra la devaluación del hueco contable→mercado (no mide retorno) | `return f1 / f0` | FUENTE |
| 9 | `backend/twr.py:1283` | `serie_medible(...)` | Los puntos aptos, partidos por huecos; define qué entra al índice | (no hay fórmula de retorno; define el dominio) | FUENTE |
| 10 | `backend/performance.py:184` | `performance(conn, uid, bench_data, ...)` | Arma la respuesta de la sección Performance: curva + benchmark recortado al mismo rango | `c = twr.curva_indexada(...)` (l. 199) · reexpone `"twr": c["twr"]`, `"cagr": c["cagr"]` (l. 261-262) | Consumidor de (2), FUENTE del endpoint |
| 11 | `backend/performance.py:38` | `_benchmark_diario(datos, fechas)` | Índice del benchmark a resolución diaria, anclado a 1.0 en la primera fecha de la curva | (rebase por cociente contra el primer cierre) | FUENTE (benchmark) |
| 12 | `backend/performance.py:161` | `_en_pesos(bench, fx)` | Pasa el índice del benchmark a pesos y lo re-ancla | `v = float(i) * float(f)` · `round(v / base, 6)` | FUENTE |
| 13 | `backend/main.py:11788` | `GET /api/insights/performance` | El endpoint de Métricas/Diagnóstico. Acepta `modo` y `moneda` | `return perf.performance(conn, uid, data, ...)` | Consumidor |
| 14 | `backend/main.py:15320` | `_historical_cagr_global(conn, uid, modo, moneda)` | El «rendimiento histórico»: CAGR + acumulado + ventana | `"total_return": round(c["twr"], 6)` · `"cagr": round(c["cagr"] * 100, 2)` | Consumidor de (2) |
| 15 | `backend/main.py:15394` | `GET /api/goals/cagr` | Expone (14) con `modo`/`moneda` | `return _historical_cagr_global(conn, uid, modo=modo, moneda=moneda)` | Consumidor |
| 16 | `backend/reporting/builder.py:783` | `_modified_dietz_pct(start, end, flows)` | Dietz del período para Reportes. **NO clampa** | `avg = start_value + 0.5 * flows` · `return (pnl / avg) * 100` | FUENTE (Reportes) |
| 17 | `backend/reporting/builder.py:1059` | `compute_metrics_for_period` (rama mes) | El % del mes sale del motor canónico si publica | `_cm = _twr_m.curva_indexada(...)` · `month_twr_pct = round(_cm["twr"] * 100, 2)` | Consumidor de (2) |
| 18 | `backend/reporting/builder.py:1234` | `compute_metrics_for_period` (rama año) | El % del año sale del motor canónico si cubre el período | `_c = _twr.curva_indexada(...)` · `year_twr_pct = round(_c["twr"] * 100, 2)` (l. 1254) | Consumidor de (2) |
| 19 | `backend/reporting/builder.py:1307-1399` | `compute_metrics_for_period` (fallback contable) | TWR anual por composición geométrica de los Dietz mensuales de `monthly_entries` | `mp = _modified_dietz_pct(ci, cf, _flujo_mes)` · `comp *= (1 + mp / 100.0)` · `year_twr_pct = round((comp - 1) * 100, 2)` | **FUENTE divergente** |
| 20 | `backend/reporting/builder.py:1469` | `compute_metrics_for_period` (puntas) | Dietz punta a punta del período | `delta_pct_val = _modified_dietz_pct(start_value, end_value, flows)` | FUENTE |
| 21 | `backend/reporting/builder.py:623` | `_pct_en_pesos(conn, d0, d1, v0, v1, dep, wd)` | El punta-a-punta convertido a pesos, usando `twr._leg_en_moneda` | `pct = _modified_dietz_pct(sv, ev, dep - wd)` (l. 654) | Consumidor de (7) |
| 22 | `backend/reporting/builder.py:749` | `benchmark_return_for_period` | Retorno del benchmark del período (sólo mes) | `return ((cur / prev) - 1) * 100` (sp500) · `float(v)` (inflación, ya viene en %) | FUENTE (benchmark) |
| 23 | `backend/reporting/builder.py:1578` | `compute_metrics_for_period` (cota de puntas) | Aplica `leg_dudoso` al Dietz punta-a-punta contable | `_punta_dudosa = _twr_p.leg_dudoso(start_value, end_value, flows)` · con `v0=0`: `(end_value / _aportado) > _twr_p.SALTO_MAX_VECES` | Consumidor de (6) |
| 24 | `backend/advisor_twr.py:79` | `twr_por_cliente(conn, advisor_uid)` | TWR de cada cliente del libro; sella primero | `r = twr.twr_de(conn, cid)` · `publicable = r["twr"] is not None and meses >= MESES_MINIMOS` (=3) | Consumidor de (4) |
| 25 | `backend/main.py:33698` | `GET /api/advisor/twr` | Expone (24) | `return advisor_twr.twr_por_cliente(conn, uid)` | Consumidor |
| 26 | `backend/main.py:32873` | `_snapshot_delta(...)` | Δ1d / Δ7d / Δ30d del portfolio, cashflow-adjusted | `delta_usd = (latest_value - cur_netdep) - (prev_v - prev_netdep)` · `"pct": round((delta_usd / prev_v) * 100, 2)` | **FUENTE divergente** (denominador = valor previo, sin el 0,5 de Dietz) |
| 27 | `backend/main.py:32949` | `_ytd_delta(...)` | YTD desde el 1° de enero, Modified Dietz | `pnl = latest_value - start - net_flows` · `avg = start + 0.5 * net_flows` · `"pct": round((pnl / avg) * 100, 2)` | FUENTE |
| 28 | `backend/main.py:11872` | `dietz(ci, cf, net)` (local de `/api/insights/mtm-audit`) | Reconcilia la cadena a costo contra la de mercado | `den = ci + 0.5 * net` · `round((cf - ci - net) / den, 6)` · `cum_costo *= 1 + max(r_c, -0.99)` | FUENTE (auditoría interna) |
| 29 | `backend/main.py:35700` | `_advisor_client_report(...)` (informe firmado) | Retorno del período del cliente del asesor | `dietz_base = v0 + flows_usd / 2.0` · `ret_pct = round(market_usd / dietz_base * 100, 2)` (l. 35702) | **FUENTE divergente** (reimplementa Dietz) |
| 30 | `backend/main.py:37080` | `advisor_dashboard` (distribución de performance) | «Total return vs aportado» por cliente | `perf.append((i, (float(r["total_value"] or 0) - nd) / base_nd * 100))` con `base_nd = max(MAX(net_deposited), nd)` | **FUENTE divergente** (simple, no TWR) |
| 31 | `backend/main.py:35516` | `_advisor_book_chat_context` | El `ret_pct` que el prompt le ordena al modelo usar para rankear clientes | `ret = round((float(snap["total_value"]) - nd) / base_nd * 100, 1)` | Misma fórmula que (30) |
| 32 | `backend/main.py:37392` | `_rate_pct(total, cost, incomplete)` | Rendimiento por activo (3 patas / costo) con guard | `if abs(total) > cost * MAX_PNL_TO_COST: return None` · `return (total / cost) * 100` | FUENTE |
| 33 | `backend/main.py:37574` | `_advisor_return_spread(...)` | El **rango** de retorno entre clientes por activo | `pct = _rate_pct(total, cost, incomplete)` | Consumidor de (32) |
| 34 | `backend/main.py:23027` | `_chat_benchmarks_block` | Retornos del user + benchmarks para el prompt de IA | `user_ytd_ars = round(((1 + user_ytd / 100) * (1 + _blue_user_window / 100) - 1) * 100, 2)` (l. 23134) | Consumidor de (26)/(27) |
| 35 | `backend/main.py:15293` | `_cagr_from_monthly_rows(rows)` | **Sin callers.** CAGR por media geométrica anualizada sobre `monthly_entries` | `ret_m = max(-0.95, min(5.0, (cf - ci - net) / ci))` · `cagr = prod ** (12 / len(factors)) - 1` | **CÓDIGO MUERTO** |
| 36 | `backend/main.py:11301` | `sell` (venta parcial FIFO) | El `pnl_pct` que se persiste por operación | `pnl_pct = (pnl_usd / invested_usd * 100) if invested_usd else None` | FUENTE |
| 37 | `backend/importing/persister.py:805` | `_persist_sale` (import) | Idem, desde el importador | `pnl_pct = (pnl_usd / invested_usd * 100) if invested_usd else None` | FUENTE |
| 38 | `backend/importing/persister.py:1171` | (conversión de moneda del import) | `pnl_pct` de una conversión | `op_pnl_pct = (op_pnl_usd / usd_amount * 100) if usd_amount > 0 else None` | FUENTE |
| 39 | `backend/main.py:10957` | `POST` conversión manual | Idem, carga manual | `pnl_pct = (pnl_usd_realized / data.usd_amount) * 100` | FUENTE |
| 40 | `backend/wrapped.py:50` | `_twr_for_period(rows)` | «Tu rendimiento TWR del año» del Wrapped | `ret = (cf - ci - net) / ci` (l. 62) · `ret = max(-0.95, min(5.0, ret))` (l. 64) · `prod - 1` | **FUENTE divergente** (denominador = `ci`, **sin** el 0,5; clamp ±) |
| 41 | `backend/ai/builders/insights.py:259` | `build` (packet `insights`) | `twr_pct` del período para la IA | `ret = ((cf - dep + wd) / denom) - 1` con `denom = ci` · `if ret < -0.95 or ret > 5: continue` · `compound *= (1 + ret)` | **FUENTE divergente** |
| 42 | `backend/ai/builders/insights_evolution.py:59` | `build` (packet `insights.evolution`) | `twr_pct` + mejor/peor mes + consistencia | `ret = ((cf - dep + wd) / ci) - 1` · `if ret < -0.95 or ret > 5: continue` | **FUENTE divergente** (idéntica a 41) |
| 43 | `backend/ai/builders/reports.py:75` | `build` (packet `reports`) | `twr_year_pct` | `ret = ((cf - dep + wd) / ci) - 1` · `compound *= (1 + ret)` · `twr_year_pct = round((compound - 1) * 100, 2)` | **FUENTE divergente** (idéntica a 41/42) |
| 44 | `backend/ai/builders/dashboard.py:162` | `build` (packet `dashboard`) | `twr_30d_pct` — llamado «TWR» pero **sin ajuste por flujos** | `twr_30d_pct = (end_val - start_val) / start_val` | **FUENTE divergente** |
| 45 | `backend/ai/builders/dashboard.py:171` | `build` (packet `dashboard`) | `twr_lifetime_pct` — éste sí canónico | `twr_lifetime_pct = _historical_cagr_global(conn, user_id).get("total_return")` | Consumidor de (14) |
| 46 | `backend/ai/builders/dashboard.py:189` | `build` | Retorno del S&P a 30d para el delta | `sp_30d_pct = (last / prev) - 1` · `vs_sp500_pp = twr_30d_pct - sp_30d_pct` | FUENTE (benchmark) |
| 47 | `backend/ai/builders/insights_benchmarks.py:92-116` | `build` (packet `insights.benchmarks`) | `user_return_pct` = el mismo TWR de la pantalla, con ventana mínima de 28 días | `p = _perf.performance(conn, user_id, data, bench_key="sp500", modo=modo)` · `user_pct = round(float(perf["twr"]) * 100, 2)` | Consumidor de (10) |
| 48 | `backend/ai/builders/insights_benchmarks.py:36` | `_bench_pct_entre(bench, curva, desde, hasta)` | Retorno del benchmark entre las dos fechas del número del usuario | `return round((i1 / i0 - 1) * 100, 2)` | FUENTE (benchmark) |
| 49 | `backend/ai/builders/goal.py:77` | `build` (packet `goal`) | CAGR del usuario para la proyección de metas | `user_cagr_pct = _historical_cagr_global(conn, user_id).get("cagr")` | Consumidor de (14) |
| 50 | `backend/main.py:15271` | `goals_diagnostic` (endpoint) | Idem, para el diagnóstico de la meta | `user_cagr_pct = _historical_cagr_global(conn, uid).get("cagr")` | Consumidor de (14) |
| 51 | `backend/goals_diagnostic.py:215,267` | `diagnose(...)` | Retorno **requerido** anualizado para llegar a la meta | `user_cagr_frac = (user_cagr_pct or 0) / 100` · `'required_annual_pct': round(((1 + required_monthly) ** 12 - 1) * 100, 2)` | Consumidor + FUENTE (proyección) |
| 52 | `backend/advisor_brief.py:321` | `build_brief` (sección «cómo cerraron tus clientes») | Variación del día por cliente | `"pct": (now_v - base) / base * 100` · total: `round(tot_delta / tot_base * 100, 2)` | **FUENTE divergente** (sin ajuste por flujos) |
| 53 | `backend/importing/fx_migrate.py:106` | (reporte del migrador FX) | Rendimiento simple para diagnóstico del migrador | `"rendimiento_pct": (round(((valor - aportado) / aportado) * 100, 1)` | FUENTE (diagnóstico) |
| 54 | `frontend/src/utils/insightsModel.js:93` | `buildCumulativeReturnSeries(globalMonthly, liveValue)` | Índice TWRR mensual sobre la cadena contable | `avgCapital = isImportInitialMonth ? net : capInicio + 0.5 * net` · `rawReturn = (capFinal - capInicio - net) / avgCapital` · `monthlyReturn = Math.max(rawReturn, -0.99)` · `idx = idx * (1 + monthlyReturn)` | **FUENTE divergente** (frontend) |
| 55 | `frontend/src/utils/insightsModel.js:551` | `monthlyReturnArs({ci, cf, net, fxPrev, fx, isImportInitial})` | Retorno mensual **en pesos**: `ci` al FX del mes anterior | `ciArs = _ci * fxPrev` · `cfArs = _cf * fx` · `netArs = _net * Math.sqrt(fxPrev * fx)` · `raw = (cfArs - ciArs - netArs) / avgArs` · `Math.max(raw, -0.99)` | FUENTE (paralela a 7) |
| 56 | `frontend/src/utils/insightsModel.js:600` | `applyMtmToMonthly(globalMonthly, snapshots, ...)` | Re-ancla `capital_inicio`/`capital_final` a snapshots MtM, **sólo si están los dos** | `if (s?.sintetico) continue` (l. 621) | Transformador de input |
| 57 | `frontend/src/utils/insightsModel.js:968` | `acumuladoDeVentana(filas, claveMedida, claveEstimada)` | Acumulado del rango visible del gráfico (modo estimado) | `pct = tFin` (que es `(index − 1)·100`) · fallback `pct = (((100 + v1) / (100 + v0)) - 1) * 100` | Consumidor |
| 58 | `frontend/src/utils/insightsModel.js:1063` | `acumuladoPublicado(filas, benchKey, opts)` | KPI «Acumulado» del modo certero, leyendo `index_publicado` | `pct = +((b.ip / a.ip - 1) * 100).toFixed(2)` · bench: `+((((100 + b[benchKey]) / (100 + a[benchKey])) - 1) * 100)` | Consumidor de (2) |
| 59 | `frontend/src/utils/insightsMetrics.js:51` | `computeMonthlyReturns(globalMonthly)` | Retornos mensuales Modified Dietz, base de todas las métricas pro | `denom = start + netFlow * 0.5` · `ret = gain / denom` · descarta si `Math.abs(ret) > 3` | **FUENTE divergente** |
| 60 | `frontend/src/utils/insightsMetrics.js:380` | `computeCAGR(monthlyReturns)` | CAGR anualizado sobre el **span calendario**, no sobre los meses que sobrevivieron los filtros | `totalGrowth = returns.reduce((prod, r) => prod * (1 + r), 1) - 1` · `span = mesesEntre(primera, ultima)` · `cagr = Math.pow(1 + totalGrowth, 12 / n) - 1` (l. 415) | **FUENTE divergente** |
| 61 | `frontend/src/utils/insightsMetrics.js:180` | `computeSharpe(monthlyReturns, rfAnnual)` | Sharpe — publica un `returnAnnual` **aritmético** | `returnAnnual = mean * 12` · `sharpe = (returnAnnual - rfAnnual) / volatility` | **FUENTE divergente** (otro «anualizado») |
| 62 | `frontend/src/utils/insightsMetrics.js:86` | `computeAnnualizedVolatility` | Vol anualizada | `stdDev * Math.sqrt(12)` | FUENTE |
| 63 | `frontend/src/utils/insightsMetrics.js:113` | `computeSortino` | Sortino, con `returnAnnual` aritmético | `mean * 12` (mismo criterio que 61) | FUENTE |
| 64 | `frontend/src/utils/insightsMetrics.js:250` | `computeAlphaBeta` | Alpha de Jensen; anualización **lineal** | `alpha = meanP - (rfMonthly + beta * (meanB - rfMonthly))` · `alphaAnnual = alpha * 12` | FUENTE |
| 65 | `frontend/src/utils/insightsMetrics.js:322` | `computeInformationRatio` | IR sobre el active return | `tracking_error = stdev(active) × √12` · `IR = (mean(R_p) − mean(R_b)) × 12 / TE` | FUENTE |
| 66 | `frontend/src/utils/insightsMetrics.js:450` | `computeCalmar(cagrResult, maxDrawdownPct)` | Calmar = CAGR / |maxDD| — **mezcla el CAGR de (60) con el drawdown del backend** | `calmar: cagrResult.cagr / ddAbs` | Consumidor mixto |
| 67 | `frontend/src/utils/insightsMetrics.js:205` | `computePriceMapReturns(priceMap)` | Retornos mensuales del benchmark | `return: curr / prev - 1` | FUENTE (benchmark) |
| 68 | `frontend/src/utils/evolution.js:407` | `buildEvolutionFromSnapshots(snapshots, globalMonthly, bench, tc)` | Serie diaria TWRR (USD y ARS) del gráfico de Métricas | USD: `avgCap = isBigWithdraw ? prevValueUsd : (prevValueUsd + 0.5 * flows)` (l. 536) · `r = Math.max(rRaw, -0.99)` (l. 544) · `cumUsd *= (1 + r)` (l. 545) | **FUENTE divergente** |
| 69 | `frontend/src/utils/evolution.js:568-584` | idem, rama ARS | Serie diaria TWRR en pesos | `flowsArs = baselineArs - prevBaselineArs` · `avgArs = isBigWithdrawArs ? prevValueArs : (prevValueArs + 0.5 * flowsArs)` · `cumArs *= (1 + rArs)` | **FUENTE divergente** |
| 70 | `frontend/src/utils/evolution.js:305` | `computeReturnDelta(snapshots, opts)` | Δ del período (día / mes) cashflow-adjusted, filtrando por `esApto` en las DOS puntas | `usd = (todayValue - todayNetDep) - ((prev.total_value \|\| 0) - netDepositedOf(prev))` · `pct = prevValue > 0 ? usd / prevValue : 0` | FUENTE |
| 71 | `frontend/src/utils/evolution.js:375` | `computeDailyPnl(snapshots, opts)` | Wrapper de (70) sin `sinceDate` | `return computeReturnDelta(snapshots, { ...opts, sinceDate: null })` | Consumidor |
| 72 | `frontend/src/pages/Insights.jsx:657-690` | (IIFE `benchSeriesUsd`) | Índice TWRR mensual USD del gráfico de benchmarks | `avgCap = isImportInitial ? net : (isBigWithdraw ? ci : ci + 0.5 * net)` (l. 675) · `r = Math.max(rRaw, -0.99)` (l. 683) · `cumIdx *= (1 + r)` (l. 684) | **FUENTE divergente** |
| 73 | `frontend/src/pages/Insights.jsx:917-1030` | (IIFE `benchSeriesArs`) | Índice TWRR mensual **en pesos**, sólo brokers ARS | `rArs = monthlyReturnArs({ ci, cf, net, fxPrev: fxPrevArs, fx, isImportInitial }) ?? 0` (l. 955) · `cumIdxArs *= (1 + rArs)` (l. 959) · punto «Hoy»: `rLiveArs = (valueNowArs - lastCfArs) / lastCfArs` (l. 1008) | **FUENTE divergente** |
| 74 | `frontend/src/pages/Insights.jsx:1478-1491` | `buildShadowFromSim(simResult, ...)` | Retorno **simple** del índice para el chart | `result.set(p.key, +((p.price / firstPrice - 1) * 100).toFixed(4))` | FUENTE (benchmark) |
| 75 | `frontend/src/pages/Insights.jsx:2276-2292` | `returnExpectationCard` | Retorno real (neto de inflación) para la card de perfil | `ret = (usaPerfEnPesos && perf?.twr != null) ? perf.twr * 100 : portfolioReturnArsPctRaw` · `realReturnPct = ((1 + ret / 100) / (1 + infl / 100) - 1) * 100` | Consumidor mixto |
| 76 | `frontend/src/pages/Insights.jsx:2592-2597` | `verdictItems` (celda «Inflación») | El veredicto vs inflación **siempre** desde el motor viejo ARS | `((1 + portfolioReturnArsPctRaw / 100) / (1 + inflationCumArsWindow.cumPct / 100) - 1) * 100` | **Consumidor divergente** |
| 77 | `frontend/src/pages/Dashboard.jsx:265` | (cuerpo del componente) | «Ganancia total» — retorno simple sobre aportado | `totalReturnUsd = totalValue - netDeposited` · `totalReturnPct = netDeposited > 0 ? totalReturnUsd / netDeposited : 0` | **FUENTE divergente** |
| 78 | `frontend/src/pages/Dashboard.jsx:626-632` | `periodChange` | Δ del rango visible del chart, cashflow-adjusted | `delta = (last.valueUsd - last.netDeposited) - (first.valueUsd - first.netDeposited)` · `dPct = first.valueUsd > 0 ? delta / first.valueUsd : 0` | FUENTE |
| 79 | `frontend/src/pages/Dashboard.jsx:676-690` | `cagrVar` | La celda «Anual» del strip Rendimiento — ya no calcula, lee el motor | `if (rendHist.cagr != null) return { pct: rendHist.cagr / 100, ... anual: true }` · si no, `total_return_pct / 100` con `anual: false` | Consumidor de (15) |
| 80 | `frontend/src/hooks/useMonthlyData.js:379-386` | `useMonthlyData` (por mes) | `deltaPct` del mes en el Resumen Mensual | `avgCapital = (startUsd \|\| 0) + 0.5 * flows` · `deltaPct = avgCapital > 0 ? (deltaUsd / avgCapital) * 100 : 0` | **FUENTE divergente** |
| 81 | `frontend/src/hooks/useMonthlyData.js:436-441` | idem, mes EN CURSO | Recomputa el mes vivo puro-MtM desde snapshots aptos | `avgMtm = mtmStart + 0.5 * flows` · `deltaPct = avgMtm > 0 ? (deltaUsd / avgMtm) * 100 : 0` | FUENTE |
| 82 | `frontend/src/hooks/useMonthlyData.js:616-620` | idem, rollup del mes vivo con `liveValue` | Igual, con guard `baseIncomparable` | `avgCap = _start + 0.5 * flows` · `deltaPct = (deltaUsd / avgCap) * 100` | FUENTE |
| 83 | `frontend/src/hooks/useMonthlyData.js:696-704` | idem, YTD | YTD por chain-link de los `deltaPct` mensuales | `cum *= 1 + (m.deltaPct \|\| 0) / 100` · `ytdPct = (cum - 1) * 100` | **FUENTE divergente** |
| 84 | `frontend/src/hooks/useMonthlyData.js:711-716` | idem | Métrica alternativa: YTD sobre aportado acumulado | `ytdPctOverContrib = (cumNetDepEnd > 0 && ytdUsd != null) ? (ytdUsd / cumNetDepEnd) * 100 : null` | FUENTE |
| 85 | `frontend/src/utils/valuation.js:565` | `salida(o)` dentro de `computePositionValue` | `pnlPct` de una posición abierta | `pnlPct: o.investedUsd > 0 ? (o.valueUsd - o.investedUsd) / o.investedUsd : null` | FUENTE |
| 86 | `frontend/src/utils/valuation.js:919` | `sumRowUSDT(cs)` | `pnlPct` de una fila agrupada (USD) — el % sólo sobre el costo de los lotes con precio | `pnlPct: costWithValue > 0 && pnl != null ? pnl / costWithValue : 0` | FUENTE |
| 87 | `frontend/src/utils/valuation.js:941` | `sumRowARS(cs)` | Idem en pesos; el costo se **despeja** del valor menos el P&L | `costArs = valueArs - (pnlArs \|\| 0)` · `pnlPct: costArs > 0 && pnlArs != null ? pnlArs / costArs : 0` | FUENTE |
| 88 | `frontend/src/utils/assetPnl.js:122` | `ratePct(total, cost, costIncomplete)` | Rendimiento por clase/sector con el mismo guard que el backend | `if (Math.abs(total) > cost * MAX_PNL_TO_COST) return null` · `return (total / cost) * 100` | FUENTE (espejo de 32) |
| 89 | `frontend/src/utils/insights.js:20` | `buildDashboardInsight(...)` | La frase «Tu cartera rinde X% desde el inicio» | `totalReturnPct = netDeposited > 0 ? totalReturn / netDeposited : 0` | FUENTE (espejo de 77) |
| 90 | `frontend/src/utils/benchmarkSim.js:76` | `simulateBenchmark(globalMonthly, priceLookup)` | Simula TUS aportes en el índice (flow-matched) + serie de precio cruda | `units += net / price` · `series.push({ key: k, value: units * price })` | FUENTE (benchmark) |
| 91 | `frontend/src/utils/benchmarkSim.js:193` | `computeInflationCumulative(globalMonthly, inflationMap)` | Inflación acumulada del rango (compone %) | (composición de `(1 + pct/100)`) | FUENTE (benchmark) |
| 92 | `frontend/src/utils/demo.js:452-455` | `_demoPeriod` (modo demo) | `delta_pct` del año en el demo de Reportes | `avg = startV + 0.5 * flows` · `deltaPct = avg > 0 ? (deltaUsd / avg) * 100 : 0` | FUENTE (demo) |

---

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `frontend/src/pages/Dashboard.jsx:819-823` | Hero del Dashboard | **«Ganancia total» / «Pérdida total»** + `%` |
| `frontend/src/pages/Dashboard.jsx:958-1001` | Strip «Rendimiento» del Dashboard | **«Hoy» · «Este mes» · «Total» · «Anual»** (o **«Desde que medimos»** cuando el motor no anualiza, `l. 996`) |
| `frontend/src/pages/Dashboard.jsx:967-971` | Encabezado del strip | «Anual: CAGR»; tooltip: *«Rendimiento ajustado por flujos de capital»* (`l. 1066`) |
| `frontend/src/pages/Dashboard.jsx:131` | fetch | `GET /goals/cagr?modo=…&moneda=…` |
| `frontend/src/pages/Dashboard.jsx:1078` | estado vacío | **«Sin rendimiento medible en {rango}»** |
| `frontend/src/components/InsightsKpiStrip.jsx:122-123` | Tira de KPIs de Métricas | **«Acumulado {ventana} · {moneda}»**, con sufijo **« · recreado»** en modo estimado |
| `frontend/src/pages/Insights.jsx:2810` | KPI certero | `acumuladoPublicado(chartData, benchmarkKey)` |
| `frontend/src/pages/Insights.jsx:2794-2798` | KPI estimado | `acumuladoPublicado(..., { contable: true })` con fallback a `acumuladoDeVentana` |
| `frontend/src/pages/Insights.jsx:1057-1075` | Chip sobre el gráfico | **«Recreado de tu contabilidad · desde {fecha} · medido a mercado desde {fecha}»** / **«sólo se mueve cuando vendés»** |
| `frontend/src/pages/Insights.jsx:2584-2604` | `verdictItems` | **«Plazo fijo UVA» · «Dólar» · «Inflación»**, cada una con su nota de base |
| `frontend/src/pages/Insights.jsx:2181` | Diagnóstico | `computeProMetrics(globalMonthly, bench, drawdown?.max)` |
| `frontend/src/utils/diagnostics.js:845-854` | Generador `metric_cagr` | **«Tu CAGR anualizado es +X%… sobre N meses de historial»** (gratis, no premium) |
| `frontend/src/utils/diagnostics.js:951-953` | Generador `metric_calmar` | **«tu retorno anualizado dividido por tu peor caída»** |
| `frontend/src/utils/diagnostics.js:927` | Generador `metric_alpha` | **«Tu alpha anualizado vs S&P 500…»** |
| `frontend/src/utils/diagnostics.js:870` | Generador `metric_volatility` | **«Tu volatilidad anualizada…»** |
| `frontend/src/pages/Goals.jsx:150-205` | Card de Objetivos | **«Rendimiento histórico (CAGR)»** · «anualizado (TWR)» / «acumulado (TWR)» |
| `frontend/src/pages/Goals.jsx:53` | fetch | `GET /goals/cagr?modo=…` |
| `frontend/src/pages/Goals.jsx:92,567,574` | Form de meta | El CAGR se propone como `expected_return_pct` — **«Tu CAGR (X%)»** |
| `frontend/src/pages/Goals.jsx:381-389` | Hint de la meta | «Tu rendimiento histórico (X%) supera / se ubica por debajo del asumido» |
| `frontend/src/pages/Goals.jsx:336-344` | Escenarios | **«Solo con rendimiento»** · «Rendimiento anual requerido…» |
| `frontend/src/components/reports/MonthCard.jsx:67` | Reportes, tarjeta de mes | `deltaPct = noBasis ? null : p.metrics?.delta_pct` |
| `frontend/src/components/reports/MonthCard.jsx:235-236` | idem | **«Sobre aportado»** (`delta_pct_over_contrib`) |
| `frontend/src/components/reports/WeekCard.jsx:27` | Reportes, semana | `delta_pct` |
| `frontend/src/components/reports/PerformanceCalendar.jsx:157-168` | Calendario de performance | celdas coloreadas por `delta_pct` mensual |
| `frontend/src/components/reports/YearlyHighlights.jsx:13-53` | Highlights del año | **mejor / peor mes** por `delta_pct` |
| `frontend/src/pages/ReportPublic.jsx:143,169,255` | Informe firmado del asesor | motivo desde `twr.MOTIVO_TEXTO`; *«Retornos netos de comisiones»* |
| `frontend/src/pages/AdvisorClients.jsx:55` | Clientes del asesor | `GET /advisor/data-health` (**no** consume `/advisor/twr`) |
| `frontend/src/pages/Wrapped.jsx:53` | Wrapped anual | `GET /wrapped/{year}` → slide **«Tu rendimiento TWR de {year}»** (`backend/wrapped.py:150`) |
| `frontend/src/pages/HomeMobile.jsx:39` | Home mobile | `computeDailyPnl`, `computeReturnDelta` |
| `backend/main.py:20575` | Prompt de IA | Glosario: **«TWR (rendimiento ponderado por tiempo)»** |
| `backend/main.py:20682` | Prompt del libro | `ret_pct` descrito como **«retorno total vs aportado»** |
| `backend/main.py:23159-23176` | `_note` del prompt | *«Retornos REALES precalculados — citalos, NO hagas aritmética nueva»* |
| `backend/ai/prompts.py:1180` | Prompt `insights.benchmarks` | `user_return_pct` = **«el MISMO número que la pantalla de Métricas»** |
| `backend/ai/builders/metrics_pro_card.py:51,83-88` | Card de métrica pro | **«CAGR anualizado»**, con `total_growth_pct` + `cagr_annual_pct` |
| `backend/reporting/detectors.py:187` | Detectores de Reportes | `report.metrics.sp500_return_pct` |

---

### Dónde se persiste

**Una sola tabla materializa un retorno.** [V]

| tabla | columna | qué guarda | dónde se define |
|---|---|---|---|
| `twr_periods` | `ret` | «Modified Dietz del tramo» (mensual) | DDL en `backend/main.py:1833`; PG en `backend/schema_pg.sql:1677` |
| `twr_periods` | `v0_usd`, `v1_usd`, `flow_usd` | Los tres insumos del Dietz de ese mes | `backend/main.py:1828-1830` |
| `twr_periods` | `quality` | `'ok'` \| `'dudoso'` \| `'flujo_sospechoso'` \| `'plano'` | escrito en `backend/twr.py:775-783` |
| `twr_periods` | `revision`, `sealed_at` | Append-only: si el input cambia se escribe `revision+1`, nunca se pisa | `backend/twr.py:800-832` |
| `operations` | `pnl_pct` | Retorno **de la operación cerrada**: `100 · pnl_usd / invested_usd` | escrito en `backend/main.py:11301`, `backend/importing/persister.py:805`, `:1171`, `backend/main.py:10957` |
| `goals` | `expected_return_pct` | El rendimiento anual **asumido** por el usuario (no medido) | DDL `backend/main.py:1503`; modelo `backend/main.py:15151` |

**Todo lo demás se calcula al vuelo.** [V] `snapshots` guarda `total_value`, `total_invested`, `net_deposited`, `fx_to_usd_blue` (y, en producción, `holdings_json`, `source`, `mtm_coverage`, `apto`, `base` — ver Zonas grises) pero **ningún porcentaje**; `monthly_entries` guarda `capital_inicio`, `capital_final`, `deposits`, `withdrawals`, `pnl_realized`, `pnl_unrealized` pero **ningún retorno** (esquema verificado con `sqlite3 backend/trading.db ".schema monthly_entries"`). El TWR, el CAGR y el drawdown de la sección Métricas/Diagnóstico se recalculan en **cada request** a `/api/insights/performance` y `/api/goals/cagr`.

**⚠️ Y `twr_periods` está, en la práctica, muerta.** [V] El único escritor es `twr.sellar` (`backend/twr.py:800`), llamado sólo desde `advisor_twr.twr_por_cliente` (`backend/advisor_twr.py:95`), expuesto sólo por `GET /api/advisor/twr` (`backend/main.py:33698`) — y **ningún archivo del frontend llama a ese endpoint** (`grep -rn "advisor/twr" frontend/src/` → sin resultados; sólo aparece en `backend/tests/test_advisor_plan.py:3187`). Sí figura en la lista de tablas que se borran al resetear la cuenta (`backend/main.py:3608`).

---

### ⚠️ Implementaciones divergentes

**No hay una sola implementación. Hay al menos SEIS familias de fórmula viva**, y la mitad se llama «TWR» en el código.

#### A. La fórmula del retorno de un período — cinco variantes

| variante | fórmula literal | clamps | dónde vive | qué pantalla la ve |
|---|---|---|---|---|
| **A1 · Canónica** | `(v1 − v0 − flow) / (v0 + 0.5·flow)` | piso −1.0, **sin techo** | `backend/twr.py:573-575` | Métricas/Diagnóstico, Reportes (mes/año cuando el motor publica), `/goals/cagr`, Dashboard «Anual», packets `insights.benchmarks` y `goal` |
| **A2 · Dietz sin clamp** | `(end − start − flows) / (start + 0.5·flows) × 100` | **ninguno** | `backend/reporting/builder.py:790-794` | Reportes (todas las tarjetas cuando el motor no publica) |
| **A3 · Dietz + heurística «big withdraw»** | `avgCap = isBigWithdraw ? ci : ci + 0.5·net` con `isBigWithdraw = net < 0 && |net|/ci > 0.3` | piso −0.99 | `frontend/src/utils/evolution.js:535-544`, `frontend/src/pages/Insights.jsx:673-683` | Gráfico de evolución de Métricas y el chart de benchmarks |
| **A4 · Dietz + heurística «import inicial»** | `avgCapital = isFirst && ci===0 && net>0 ? net : ci + 0.5·net` | piso −0.99 | `frontend/src/utils/insightsModel.js:124-131`, `frontend/src/utils/insightsModel.js:561` | La serie que alimenta consistencia mensual y mejor/peor mes |
| **A5 · NO es Dietz: denominador = `capital_inicio`** | `((cf − dep + wd) / ci) − 1` | **descarta silenciosamente** si `ret < −0.95` o `ret > 5` | `backend/ai/builders/insights.py:259`, `backend/ai/builders/insights_evolution.py:59`, `backend/ai/builders/reports.py:75`, `backend/wrapped.py:62-64` | **Todo lo que le llega a la IA por esos tres packets, y el slide del Wrapped** |
| **A6 · Sin ajuste por flujos** | `(end − start) / start` | ninguno | `backend/ai/builders/dashboard.py:162` (llamado `twr_30d_pct`), `backend/advisor_brief.py:321` | Packet `dashboard` de la IA; brief diario del asesor |

**Diferencia concreta A1 vs A5.** Con `ci = 1000`, `cf = 2100`, `dep = 1000`:
- A1 (Dietz): `(2100 − 1000 − 1000) / (1000 + 500) = +6,67 %` — es el número que el propio test canónico fija (`backend/tests/test_cagr_snapshots.py:63`).
- A5: `((2100 − 1000) / 1000) − 1 = +10,0 %`.

El sesgo de A5 es **sistemático hacia arriba cuando hay aportes** (denominador más chico) y hacia abajo cuando hay retiros. Y el clamp `ret > 5` **descarta el mes entero en silencio**, achicando la ventana sin decirlo. `backend/ai/builders/insights_benchmarks.py:54-68` documenta que ese packet **ya se migró** al motor canónico por exactamente este motivo (*"este packet calculaba un TERCER rendimiento… el chat podía afirmar 'le ganaste al S&P' con un dato que ninguna posición del toggle publica"*); **los otros tres packets y el Wrapped no se migraron**.

**Diferencia A6 vs todo lo demás:** `twr_30d_pct` de `backend/ai/builders/dashboard.py:162` se llama «TWR» y no neutraliza un solo peso de flujo. En el mismo archivo, catorce líneas abajo, `twr_lifetime_pct` **sí** sale del motor canónico (`backend/ai/builders/dashboard.py:171`). Los dos viajan en el mismo packet al mismo prompt.

#### B. El «anualizado» — tres fórmulas distintas, dos de ellas en la misma pantalla

| variante | fórmula | piso para publicar | dónde |
|---|---|---|---|
| **B1 · CAGR canónico (geométrico, sobre días)** | `idx ** (1.0 / años) − 1.0` con `años = _dias(ventana_desde, hasta)/365.25` | **`años >= 0.5`**, si no devuelve `None` | `backend/twr.py:2165-2172` |
| **B2 · CAGR del frontend (geométrico, sobre meses de calendario)** | `Math.pow(1 + totalGrowth, 12 / n) − 1`, con `n = mesesEntre(primeraClave, ultimaClave)` | **≥ 2 meses** (`monthlyReturns.length < 2 → null`) | `frontend/src/utils/insightsMetrics.js:380-415` |
| **B3 · Anualización aritmética** | `returnAnnual = mean * 12` (y `alphaAnnual = alpha * 12`) | ≥ 3 meses (`MIN_MONTHS_FOR_STATS`) | `frontend/src/utils/insightsMetrics.js:185`, `:291` |

**B1 y B2 conviven en la pantalla de Métricas/Diagnóstico.** [V] `frontend/src/pages/Insights.jsx:2181` llama `computeProMetrics(globalMonthly, …)`, que internamente usa B2 (`frontend/src/utils/insightsMetrics.js:486`+), y el generador `metric_cagr` publica ese número como **«Tu CAGR anualizado»** (`frontend/src/utils/diagnostics.js:851-854`) **sin el piso de medio año de B1** (basta `months >= 2`, `frontend/src/utils/diagnostics.js:852`). Al mismo tiempo, el Dashboard (`frontend/src/pages/Dashboard.jsx:683-684`) y Objetivos (`frontend/src/pages/Goals.jsx:183`) publican B1, que para el mismo usuario con 3 meses de historia devuelve **`null`** («Desde que medimos», acumulado sin anualizar). **Mismo usuario, mismo día: el Diagnóstico anualiza y el Dashboard se niega.**

**B2 y B3 también conviven**: `computeCalmar` (`frontend/src/utils/insightsMetrics.js:450-458`) usa el CAGR de B2 como numerador, mientras la card de Sharpe publica `return_annual_pct` desde B3 (`frontend/src/pages/Insights.jsx:2473`). Son dos «rendimientos anualizados» distintos en la misma grilla de métricas.

**B1 mismo tiene un antecedente muerto, B4:** `backend/main.py:15293-15317` (`_cagr_from_monthly_rows`) anualiza con `prod ** (12 / len(factors)) − 1`, o sea **sobre la cantidad de meses que sobrevivieron los filtros**, no sobre el tiempo transcurrido. `grep -rn "_cagr_from_monthly_rows" . --include='*.py'` devuelve sólo su definición y una mención en un comentario de test: **no tiene un solo caller**. El docstring de `_historical_cagr_global` (`backend/main.py:15323-15343`) narra la eliminación del motor equivalente que producía «+16.841 % anual».

#### C. El «acumulado total» — dos definiciones que el usuario ve una al lado de la otra

| variante | fórmula | dónde | etiqueta |
|---|---|---|---|
| **C1 · Simple / money-weighted** | `(totalValue − netDeposited) / netDeposited` | `frontend/src/pages/Dashboard.jsx:265-266`, espejo en `frontend/src/utils/insights.js:20` | «Ganancia total», «Total» del strip |
| **C2 · TWR encadenado** | `index_publicado[fin] / index_publicado[inicio] − 1` | `frontend/src/utils/insightsModel.js:1081` (`acumuladoPublicado`) | «Acumulado {ventana}» |

`frontend/src/utils/format.js:142` reconoce el problema por escrito: *"Dashboard —que es toda la historia Y anualizado— y parecen contradecirse"*. En el propio Dashboard, la celda «Total» (C1) y la celda «Anual» (B1 sobre C2) salen de motores distintos: la primera no neutraliza flujos y la segunda sí.

#### D. El retorno «en pesos» — tres conversiones distintas

| variante | cómo convierte | dónde |
|---|---|---|
| **D1 · Canónica** | Puntas al TC de su fecha; **flujo** al TC medio **geométrico**; el stock (`net_deposited`) NO se convierte, se resta en dólares primero | `backend/twr.py:696-706` |
| **D2 · Frontend mensual** | `ciArs = ci × fxPrev`, `cfArs = cf × fx`, `netArs = net × √(fxPrev·fx)` — **equivalente a D1** | `frontend/src/utils/insightsModel.js:557-563` |
| **D3 · Frontend diario (evolution)** | `flowsArs = netDep_t × fx_t − netDep_{t−1} × fx_{t−1}` | `frontend/src/utils/evolution.js:571` |

**D3 hace exactamente lo que D1 prohíbe.** El docstring de `_leg_en_moneda` es explícito (`backend/twr.py:696-703`): *"EL FLUJO SE CONVIERTE, EL STOCK NO. `net_deposited` es un acumulado; pasarlo a pesos a cada punta y restar daría `nd·(fx1−fx0)`, o sea la revaluación de TODO lo aportado en la vida leída como un aporte del período."* La rama ARS de `buildEvolutionFromSnapshots` calcula literalmente esa resta. Además, el comentario que la acompaña (`frontend/src/utils/evolution.js:560-562`) afirma *"la conversión afecta tanto numerador como denominador del period_return, así que técnicamente el % se mantiene"* — **eso es falso para el código que está debajo**, que usa el FX de cada snapshot por separado (`prevValueArs` se guarda ya convertido al FX de su fecha, `frontend/src/utils/evolution.js:597`). El comentario describe el bug viejo, no la implementación actual.

#### E. Los guards de plausibilidad — presentes en un lado, ausentes en el otro

| guard | valor | dónde SÍ está | dónde NO está |
|---|---|---|---|
| `leg_dudoso` (salto ×3 sin flujo) | `SALTO_MAX_VECES = 3.0` (`backend/twr.py:612`) | `curva_indexada` (`backend/twr.py:1840`), `tramos` (`backend/twr.py:779`), Reportes composición (`backend/reporting/builder.py:1370`) y puntas (`backend/reporting/builder.py:1588`) | `wrapped.py`, los 3 packets de IA (A5), `evolution.js`, `Insights.jsx`, `useMonthlyData.js`, `_snapshot_delta`, `advisor_brief.py`, el informe firmado usa un guard distinto (`_cortes_adentro`, `backend/main.py:35711-35715`) |
| Desborde del denominador | `DENOM_MIN_FRACCION = 0.25` (`backend/twr.py:620`) | idem | idem |
| Serie partida ⇒ no publicar | `partida = len(s["tramos"]) > 1` (`backend/twr.py:1981`) | `curva_indexada` | Todo el resto |
| Piso de medio año para anualizar | `años >= 0.5` (`backend/twr.py:2171`) | `curva_indexada` | `computeCAGR` del frontend (2 meses) |
| Clamp de outlier mensual | ±300 % (`MAX_MONTHLY_RETURN = 3`, `frontend/src/utils/insightsMetrics.js:43`) | métricas pro del frontend | el motor canónico (que **no** clampea por arriba, a propósito) |
| Clamp de outlier mensual | `[−0.95, +5]` | A5 (`backend/ai/builders/*`, `backend/wrapped.py:64`) | el motor canónico |

#### F. El veredicto «¿le ganás a la inflación?» — dos números en la misma pantalla

[V] `frontend/src/pages/Insights.jsx:2281-2282` (card «Expectativa de retorno») usa `perf.twr` **cuando la serie en pesos viene del motor**; `frontend/src/pages/Insights.jsx:2595-2596` (celda «Inflación» de `verdictItems`) usa **siempre** `portfolioReturnArsPctRaw`, que es el índice del motor viejo `benchSeriesArs` (`frontend/src/pages/Insights.jsx:917-1030`) y **sólo cubre los brokers en pesos** (`arsBrokerNames`, `frontend/src/pages/Insights.jsx:918`). Son dos respuestas distintas a la misma pregunta, en la misma vista.

#### G. El retorno del asesor — cuatro números para el mismo cliente

| # | qué mide | fórmula | dónde | quién lo ve |
|---|---|---|---|---|
| G1 | TWR encadenado mensual sellado | `Π(1+r) − 1`, mínimo 3 meses | `backend/advisor_twr.py:98-111` | **nadie** (endpoint sin consumidor) |
| G2 | Retorno del período del informe | `market_usd / (v0 + flows/2) × 100` | `backend/main.py:35700-35702` | el cliente, en el PDF firmado |
| G3 | «Total return vs aportado» | `(total_value − nd) / MAX(net_deposited) × 100` | `backend/main.py:37080` | tarjeta Mejor/Peor del libro |
| G4 | Variación del día | `(now − base) / base × 100` | `backend/advisor_brief.py:321` | brief diario por mail |

G2 reimplementa Dietz a mano en vez de llamar a `twr.dietz`; G3 y G4 no ajustan por flujos dentro del período.

---

### Zonas grises

**1. `/api/advisor/twr` no lo consume nadie, y con él muere `twr_periods`.** [V] El motor mejor documentado del repo —el que sella meses, versiona revisiones y se niega a componer sobre un mes dudoso (`backend/twr.py:869-882`)— es el único que **no tiene pantalla**. El asesor sí consume `/advisor/data-health` (`frontend/src/pages/AdvisorClients.jsx:55`), que es el «prerrequisito» del TWR según el propio docstring (`backend/main.py:33718-33720`), pero el número nunca llega. **Consecuencia:** la única columna de retorno persistida en la base sólo se escribe si alguien golpea el endpoint a mano.

**2. El mismo comentario aparece tres veces citando una línea que no existe.** [V] `frontend/src/utils/evolution.js:543`, `:582` y `frontend/src/pages/Insights.jsx:682` dicen *"Mismo criterio que `twr.dietz` (backend/twr.py:215)"*. `backend/twr.py:215` es `return INDETERMINADO`, dentro de `clasificar_fila`; `dietz` está en la línea **559**. Mismo patrón en `backend/performance.py:5-6` (*"`applyMtmToMonthly` descarta sintéticos (insightsModel.js:621) y se abstiene sin borde medido (:653)… `buildCumulativeReturnSeries` (:106)"*): hoy `applyMtmToMonthly` está en `frontend/src/utils/insightsModel.js:600` y `buildCumulativeReturnSeries` en `:93`. Las referencias cruzadas envejecieron; alguien que las siga va a leer otra función.

**3. `_cagr_from_monthly_rows` es código muerto con un docstring que suena vivo.** [V] `backend/main.py:15293-15317`. Su comentario (*"Fallback cuando no hay snapshots"*) describe un camino que ya no existe — lo confirma el propio test que lo menciona (`backend/tests/test_cagr_snapshots.py:83-91`: *"El fallback a `monthly_entries` ya no existe"*). Riesgo: alguien lo reengancha creyendo que es el fallback documentado.

**4. El esquema de `snapshots` en la copia local NO tiene las columnas que el motor lee.** [V] `sqlite3 backend/trading.db ".schema snapshots"` devuelve sólo `id, user_id, date, total_value, total_invested, net_deposited, fx_to_usd_blue`. Pero `backend/twr.py:1312-1314` selecciona además `holdings_json, source, mtm_coverage` y `_sel_estampo(conn)` (que agrega `base`/`apto` si existen, `backend/twr.py:1094-1099`). O sea: **la base de dev es anterior a las columnas que el motor de retorno necesita**, y `_tiene_columna` (`backend/twr.py:1084`) existe precisamente para sobrevivir a eso. No pude verificar contra datos qué devuelve el motor en esa base; el código manda y así lo tomé.

**5. `_snapshot_delta` mezcla numerador Dietz-ajustado con denominador crudo.** [V] `backend/main.py:32939-32943`: el numerador descuenta flujos (`(latest − cur_netdep) − (prev_v − prev_netdep)`) pero el denominador es `prev_v` a secas, sin el `+0.5·flow`. El comentario lo llama *"Pct sobre el VALOR base (no Total Return — ese podría ser 0 o negativo)"* — es una decisión consciente, pero significa que **Δ30d no es el mismo % que el motor daría para esos 30 días**. Y ese `Δ30d` es el que viaja al prompt de IA como `usd_30d_pct` (`backend/main.py:23153`), donde el `_note` lo describe como *"cashflow-adjusted"* (`backend/main.py:23159-23161`) — cierto para el numerador, no para la base.

**6. `prev_netdep == 0` se lee como «no lo tengo» y cae a `total_invested`.** [V] `backend/main.py:32934-32936`. El comentario explica que la columna es `NOT NULL DEFAULT 0` y por eso el 0 es el único valor que significa hueco. Pero un usuario con **aportes netos exactamente 0** (aportó y retiró lo mismo) cae al costo. Es un caso raro pero no imposible, y la fila entra a un porcentaje publicado.

**7. Reportes puede publicar el % de un motor y el monto de otro.** [V] `backend/reporting/builder.py:1509-1511`: en `period_type == "month"`, si el motor canónico publicó, se pisan **los dos** (`delta_pct` y `delta_usd`). Pero en `period_type == "year"` (`backend/reporting/builder.py:1513`) **sólo se pisa `delta_pct`** — el `delta_usd` sigue siendo el punta-a-punta contable de `end_value − start_value − flows` (`backend/reporting/builder.py:1468`). El comentario de `backend/reporting/builder.py:1287-1289` reconoce que los dos van juntos en el mismo hero (`MonthCard.jsx:118` y `:121`); para el año pueden venir de bases distintas.

**8. El «TWR» del Wrapped es el número que más se comparte y el menos canónico.** [V] `backend/wrapped.py:50-69` usa A5 (denominador `capital_inicio`, clamp `[−0.95, +5]`), sin `leg_dudoso`, sin base de mercado y sobre `monthly_entries` — que para meses cerrados está al costo (`pnl_unrealized = 0`, documentado en `backend/main.py:15296-15298`). El slide dice literalmente **«Tu rendimiento TWR de {year}»** (`backend/wrapped.py:150`) y `backend/wrapped.py:327-335` lo resta contra el S&P 500 y el MERVAL, y contra la inflación (`backend/wrapped.py:378`). Es un número contable comparado contra índices medidos a mercado, presentado como TWR y diseñado para compartirse.

**9. `applyMtmToMonthly` alimenta a `buildCumulativeReturnSeries`, y el guard de una lo desarma la otra.** [I, apoyado en el comentario del propio repo] `frontend/src/pages/Insights.jsx:535` construye `globalMonthly` con `applyMtmToMonthly`, y `frontend/src/pages/Insights.jsx:1779` se lo pasa a `buildCumulativeReturnSeries` **con `liveValue`**. Esa función cierra el último mes a valor live sin mirar `m.mtm` (`frontend/src/utils/insightsModel.js:106-108`). El comentario inmediatamente debajo (`frontend/src/pages/Insights.jsx:1780-1789`) lo documenta y por eso **el drawdown ya no sale de ahí**, sino de `drawdownFromPerf(perf)`. Pero `returnSeries` **sigue vivo** y sigue alimentando `computeMonthlyConsistency` (`frontend/src/pages/Insights.jsx:2112`) y `computeBestWorstMonth`: o sea, «% de meses positivos» y «mejor/peor mes» se calculan sobre una serie cuyo último punto mezcla bases, mientras el drawdown de la misma pantalla usa la serie saneada del backend.

**10. `computeMonthlyReturns` filtra meses y `computeCAGR` los cuenta igual.** [V] `frontend/src/utils/insightsMetrics.js:60-70` descarta meses con `start <= 100 && |netFlow| <= 100`, con `denom <= 100`, y con `|ret| > 3`. `computeCAGR` (`frontend/src/utils/insightsMetrics.js:410-415`) anualiza sobre `mesesEntre(primeraClave, últimaClave)` — el span calendario entre los **sobrevivientes**. El test `frontend/src/utils/computeCagrSpan.test.js:44-53` fija esa decisión a propósito (*"Contarlos bajaría el CAGR a ~12,6% y sería igual de falso"*). Es una elección declarada, no un bug — pero significa que un mes descartado por outlier **desaparece del numerador y sigue en el denominador** si está en el medio, y desaparece de los dos si está en la punta.

**11. `sumRowARS` despeja el costo del valor menos el P&L.** [V] `frontend/src/utils/valuation.js:939-941`: `costArs = valueArs - (pnlArs || 0)`. Si `pnlArs` es `null` para algún lote, el `|| 0` hace que ese costo quede igual al valor y el `pnlPct` de la fila se diluya. No pude determinar si ese caso ocurre en la práctica: no encontrado.

**12. El «acumulado» del KPI no es `perf.twr`, y está documentado que no debe serlo.** [V] `frontend/src/utils/insightsModel.js:947-953`: *"son dos números distintos y los dos están bien: `perf.twr` es de la ventana que el backend declara; este KPI es del RANGO VISIBLE, que cambia con los tabs 1A/2A/5A/MAX"*. Es coherente, pero implica que el usuario que cambia de tab ve cambiar «su rendimiento» sin que nada cambie en su cartera, y el chip de arriba (que sí muestra `ventana_desde` de `perf`) no se mueve.

**13. `_snapshot_delta` acepta `INDETERMINADO` y `_ytd_delta` exige `mtm_only`.** [V] `backend/main.py:32906-32908` acepta `(MEDICION, INDETERMINADO)` *"este chip no define el número principal de la pantalla"*; `backend/main.py:33005-33012` exige un cierre medido y fresco (`_border_is_fresh(..., max_lag_days=5)`). Dos exigencias distintas para dos chips que se muestran uno al lado del otro en el mismo strip (`frontend/src/pages/Dashboard.jsx:964-1001`). El comentario lo declara, pero el usuario no tiene cómo saber que «Hoy» y «Este mes» tienen distinto nivel de prueba.

**14. `MESES_MINIMOS = 3` para el asesor, medio año para el CAGR retail, 2 meses para el CAGR del Diagnóstico.** [V] `backend/advisor_twr.py:76` (`MESES_MINIMOS = 3`), `backend/twr.py:2171`, `frontend/src/utils/diagnostics.js:852`. Tres pisos distintos para «cuánta historia hace falta antes de publicar un rendimiento», en el mismo producto.

**15. No encontrado:** ninguna implementación de **IRR / MWR / XIRR** (money-weighted return con fechas), ni de **retorno bruto vs neto de comisiones** como par de números. El pie del informe público dice *"Retornos netos de comisiones"* (`frontend/src/pages/ReportPublic.jsx:255`) pero no hallé un cálculo que separe bruto de neto — las comisiones entran al costo (`frontend/src/utils/valuation.js:550-553`) y por esa vía al `pnlPct`, sin exponerse aparte.
