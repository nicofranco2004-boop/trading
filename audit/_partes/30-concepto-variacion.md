## Variación diaria / periódica y evolución

### Definición según el código

En Rendi «variación» **no es una sola cosa**: el código implementa cuatro conceptos distintos que comparten vocabulario y que en la UI se muestran uno al lado del otro.

**1. Variación de CARTERA (día / mes / N días / período) — la definición canónica del repo.**
No es `Δvalor`. Es **Δ(Total Return) ajustado por flujos**, donde Total Return = `total_value − net_deposited`:

```
variación_usd = (value − net_deposited)_hoy − (value − net_deposited)_referencia
variación_pct = variación_usd / value_referencia
```

[V] `frontend/src/utils/evolution.js:363-365`. El docstring lo dice explícito (`frontend/src/utils/evolution.js:277-289`): el cálculo viejo era `Δtotal_value` y un retiro de US$110 se publicaba como «−$110» de pérdida. Ojo con la **asimetría deliberada**: el numerador es Δ(total return) pero el **denominador es el VALOR anterior**, no el total-return anterior. El backend repite exactamente la misma asimetría y la comenta: *"Pct sobre el VALOR base (no Total Return — ese podría ser 0 o negativo)"* (`backend/main.py:32940`).

**2. Variación diaria POR POSICIÓN («Var. día» / «Hoy» en Cartera).**
Otra cosa completamente distinta: es de **mercado**, no de snapshots, y NO se ajusta por flujos (no hace falta: es precio × cantidad):

```
Δunitario = precio_actual − cierre_anterior
monto     = Δunitario × cantidad     ·     pct = Δunitario / cierre_anterior
```

[V] `frontend/src/pages/Positions.jsx:1534-1535` y `frontend/src/pages/PositionsMobile.jsx:824-838`. El `cierre_anterior` viene de un endpoint aparte (`/api/prices/prev-close`) y es *best-effort*: sin él la celda muestra `—` (`frontend/src/pages/Positions.jsx:584-587`).

**3. `change_pct` de un INSTRUMENTO de mercado (índices, heatmap, movers, watchlist, alertas %).**
La definición de manual, sin ajuste de nada: `((último_cierre / cierre_anterior) − 1) × 100` sobre la serie de yfinance. [V] `backend/home/market.py:224`, `:315`, `:349`.

**4. «Evolución» = la curva dibujada.**
Hay dos objetos distintos que se llaman así:
- **Curva de VALOR** (Dashboard, home mobile): serie de `total_value` por fecha, con un punto «hoy» sintético al final. [V] `frontend/src/utils/evolution.js:173-245`.
- **Curva de RENDIMIENTO %** (Insights / Métricas): índice encadenado (chain-link) de Modified Dietz entre puntos consecutivos. Existe en **dos motores paralelos**: uno en JS (`frontend/src/utils/evolution.js:407-602`) y el canónico en Python (`backend/twr.py:1611`, servido por `/api/insights/performance`).

**Lo no estándar, dicho en voz alta:**
- El **denominador del %** no es homogéneo entre sitios: unos usan `value_anterior` puro, otros Modified Dietz (`v0 + 0,5·flujos`), otros `capital_inicio` pelado. Ver §Implementaciones divergentes.
- Una fila de `snapshots` **no vale automáticamente** como punta de una variación. Todo el sistema gira alrededor de dos predicados: `apto` (¿esta fila puede ser pico, borde o denominador?) y `clase ∈ ACEPTA_LINEA` (¿este punto entra a la línea dibujada?). Colapsarlos es, según el propio comentario del repo, «el error que hizo volver este bug once veces» (`frontend/src/utils/evolution.js:3-19`).
- El «piso de −99 %» y la **ausencia de techo** son decisiones explícitas y repetidas: `backend/twr.py:559-577` (`dietz`), `frontend/src/utils/evolution.js:544`, `:582`.

---

### Dónde se calcula

Orden: primero lo canónico (los dos motores que el repo declara SSoT), después el resto.

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `frontend/src/utils/evolution.js:305` | `computeReturnDelta` | **SSoT frontend** de la variación de cartera (día y mes). Filtra las DOS puntas por `esApto` | `const usd = (todayValue - todayNetDep) - ((prev.total_value \|\| 0) - netDepositedOf(prev))` · `const pct = prevValue > 0 ? usd / prevValue : 0` (`:363-365`) | fuente |
| 2 | `frontend/src/utils/evolution.js:375` | `computeDailyPnl` | Wrapper de #1 sin `sinceDate` (modo diario) | `return computeReturnDelta(snapshots, { ...opts, sinceDate: null })` | fuente (delegador) |
| 3 | `backend/twr.py:559` | `dietz` | **EL primitivo** del retorno de un tramo. Sin techo, piso en −100 % | `denom = v0 + 0.5 * flow` · `return max((v1 - v0 - flow) / denom, -1.0)` | fuente |
| 4 | `backend/twr.py:1611` | `curva_indexada` | **Motor canónico backend**: encadena `dietz` sobre `serie_medible`, produce `curva`, `twr`, `cagr`, drawdown, y tres índices distintos (`idx` publicado, `idx_dib` dibujado, `idx_est` estimado) | `idx *= (1.0 + ret)` (`:1876`) · `idx_por_base[_b] *= (1.0 + _rp)` (`:1845`) · `idx_est *= (1.0 + _re)` (`:1863`) | fuente |
| 5 | `backend/twr.py:623` | `leg_dudoso` | Cota de cordura de UN leg: `desborde` (Dietz toca −1) o `salto` (×3 sin flujo). No arregla el dato, **corta el tramo** | `ratio = v1 / v0` · `if ratio > SALTO_MAX_VECES or ratio < 1.0 / SALTO_MAX_VECES` (`:643-645`), `SALTO_MAX_VECES = 3.0` (`:612`) | fuente |
| 6 | `backend/main.py:32873` | `_snapshot_delta` | Δ1d / Δ7d / Δ30d del summary de Reportes. Cashflow-adjusted, mismo criterio que #1 | `delta_usd = (latest_value - cur_netdep) - (prev_v - prev_netdep)` · `"pct": round((delta_usd / prev_v) * 100, 2)` (`:32939-32943`) | fuente |
| 7 | `backend/main.py:32755-32757` | `_portfolio_snapshot_summary` | Llama a #6 tres veces (1/7/30 días). **Solo para `broker_filter == "global"`** | `delta_1d = _snapshot_delta(conn, uid, latest_value, latest_date, days=1, latest_netdep=_latest_netdep) if broker_filter == "global" else None` | fuente |
| 8 | `frontend/src/utils/evolution.js:173` | `buildPortfolioValueSeries` | Serie de VALOR para la curva. Filtra por `esDibujable` **antes** del recorte de ventana, y hace *prepend* del ancla anterior al corte | `const dibujables = (snapshots \|\| []).filter(esDibujable)` (`:188`) · `const cutoff = Date.now() - days * 86400000` (`:222`) | fuente |
| 9 | `frontend/src/utils/evolution.js:407` | `buildEvolutionFromSnapshots` | Curva de rendimiento % de Insights (chain-link JS). Filtra por `esApto` (no `esDibujable`) | `const flows = netDep - prevNetDep` · `const pnl = (value - prevValueUsd) - flows` · `const avgCap = isBigWithdraw ? prevValueUsd : (prevValueUsd + 0.5 * flows)` · `const rRaw = avgCap > 0 ? pnl / avgCap : 0` · `cumUsd *= (1 + r)` (`:532-545`) | fuente |
| 10 | `frontend/src/pages/Positions.jsx:1528` | `dayVarOf` | Var. día por posición (desktop) | `const perUnit = currentPrice - prev` · `return { amount: perUnit * (p.quantity \|\| 0), pct: perUnit / prev }` | fuente |
| 11 | `frontend/src/pages/Positions.jsx:1542` | `dvFor` | Ruteo CEDEAR/cripto de #10: elige el símbolo (`.BA` vs US) y escala el monto | `if (local) return { amount: dv.amount / tcCedear, pct: dv.pct }` (`:1553`) · `if (f !== 1) return { amount: dv.amount * f, pct: dv.pct }` (`:1558`) | fuente |
| 12 | `frontend/src/pages/Positions.jsx:2065-2094` | agregado por broker | Suma los Δ por posición; `hasDay` distingue «0» de «sin data» | `brokerDay += dv.amount` (`:2074`) · par bimonetario: `dayUsd += pEsArs ? dv.amount / tcCedear : dv.amount` y `brokerDay = dayUsd * tcCedear` (`:2088-2094`) | fuente |
| 13 | `frontend/src/pages/PositionsMobile.jsx:797-840` | `enriched` (useMemo) | Var. día por posición (mobile). Gatea por `priceTrusted` — algo que el desktop **no** hace | `const perUnit = priceLocal - prev` · `dayVarLocal = perUnit * qty * f` · `dayVarUsd = isAR ? dayVarLocal / tcValuacion : dayVarLocal` · `dayVarPct = perUnit / prev` (`:824-838`) | fuente |
| 14 | `frontend/src/pages/PositionsMobile.jsx:947-963` | agregado por ticker (mobile) | Recalcula el % del agregado sobre el valor de AYER, no sobre el de hoy | `dayVarPct = dayVarLocal / (curLocalValue - dayVarLocal)` (`:962`) | fuente |
| 15 | `backend/main.py:7867` | `get_prev_close` (`GET /api/prices/prev-close`) | El cierre anterior por símbolo — base de #10/#13. Tres caminos: data912 (`.BA`), batch yfinance `iloc[-2]`, y `fast_info.previous_close` | data912: `result[sym] = (float(c) / (1.0 + pctv / 100.0)) if pctv else float(c)` (`:7917`) · yfinance: `prev = float(ser.iloc[-1] if _stale else ser.iloc[-2])` (`:8001`) | fuente |
| 16 | `backend/main.py:7154` | `_fetch_prev_close_one` | Fallback per-símbolo con `fast_info.previous_close` (CEDEARs ilíquidos) | `pc = getattr(fi, "previous_close", None)` (`:7165`) | fuente |
| 17 | `backend/home/market.py:214` | `_fetch_daily_quote` | Quote diaria de UN símbolo | `change_pct = ((last_close / prev_close) - 1) * 100 if prev_close > 0 else 0` (`:224`) | fuente |
| 18 | `backend/home/market.py:267` | `_fetch_batch_quotes` | Versión batched + cacheada 60 s. **Dos copias** de la misma fórmula (batch + fallback individual) | `"change_pct": round(((last / prev) - 1) * 100, 2)` (`:315` y `:349`) | fuente |
| 19 | `backend/home/market.py:376`, `:402`, `:425` | `get_indices_strip`, `_build_heatmap`, `_build_movers` | Arman strip / heatmap / top-5 gainers-losers desde #18 | `sorted_by_change = sorted(with_data, key=lambda x: x["change_pct"], reverse=True)` (`:440`) | consumidor |
| 20 | `backend/alerts_engine.py:139` | `pct_move_side` | Alertas de variación %: qué lado disparó | `if up_pct is not None and change_pct >= up_pct: return "up"` · `if down_pct is not None and change_pct <= -abs(down_pct): return "down"` (`:145-148`) | fuente |
| 21 | `backend/alerts_engine.py:400-412` | `evaluate` (rama `pct_move`) | Dos baselines: `set_price` (vs ancla) y `prev_close` (vs el `change_pct` del quote) | `change = (price - anchor) / anchor * 100.0` (`:407`) · `change = quote.get("change_pct") if quote else None` (`:414`) | fuente |
| 22 | `backend/advisor_alerts.py:280-290` | `evaluate` (asesor) | «La cartera de X se movió Y % hoy». Cashflow-adjusted en el numerador, denominador = valor base | `pct = ((now_v - _flow) - base) / base * 100.0` (`:289`) | fuente |
| 23 | `backend/main.py:36998-37023` | `_delta` (dentro de `GET /api/advisor/book`) | Δ7d del LIBRO agregado. **Bruto**, sin descontar flujos | `d = now_v - then_v` · `return round(d, 2), (round(d / then_v * 100, 2) if then_v > 0 else None)` (`:37020-37021`) | fuente |
| 24 | `backend/main.py:37995-38011` | `GET /api/advisor/book/detail` | Δ7d por cliente. **Bruto también**, pero publica `flows_7d_usd` y `market_7d_usd` aparte | `d = tv - then_v` · `"delta_7d_usd": round(d, 2)` · `"market_7d_usd": round(d - flows, 2)` (`:38001-38011`) | fuente |
| 25 | `backend/reporting/builder.py:826` | `compute_metrics_for_period` | El delta del período de Reportes (día/semana/mes/año) | `delta_usd = end_value - start_value - flows` · `delta_pct_val = _modified_dietz_pct(start_value, end_value, flows)` (`:1468-1469`) | fuente |
| 26 | `backend/reporting/builder.py:783` | `_modified_dietz_pct` | El % del período. **NO clampa** (a diferencia de `twr.dietz`) | `avg = start_value + 0.5 * flows` · `pnl = end_value - start_value - flows` · `return (pnl / avg) * 100` (`:790-794`) | fuente |
| 27 | `backend/reporting/builder.py:1717` | `compute_movers` | Mejor/peor holding por variación MtM del período, diferenciando `holdings_json` entre los dos bordes | `d = v_end - v_start` · `pct = (d / v_start) if v_start > 0 else None` (`:1747-1749`) | fuente |
| 28 | `backend/reporting/builder.py:757-772` | benchmark del período | Variación mensual del S&P para el veredicto | `return ((cur / prev) - 1) * 100` (`:772`) | fuente |
| 29 | `frontend/src/hooks/useMonthlyData.js:378-392` | `buildMonthlyReports` (rama contable) | Delta del mes desde `monthly_entries` | `const flows = deposits - withdrawals` · `const avgCapital = (startUsd \|\| 0) + 0.5 * flows` · `deltaUsd = endUsd - startUsd - flows` · `deltaPct = avgCapital > 0 ? (deltaUsd / avgCapital) * 100 : 0` | fuente |
| 30 | `frontend/src/hooks/useMonthlyData.js:406-447` | rama `isLiveMonth` | Recomputa el mes en curso puro-MtM desde snapshots, exigiendo `esApto` en las dos puntas | `deltaUsd = mtmEnd - mtmStart - flows` · `deltaPct = avgMtm > 0 ? (deltaUsd / avgMtm) * 100 : 0` (`:439-440`) | fuente |
| 31 | `frontend/src/hooks/useMonthlyData.js:594-630` | re-cálculo del mes con `liveValue` | Pisa el delta del #30 con el valor live, con piso de antigüedad de 5 días para la base | `newestWithCapital.deltaUsd = liveValue - _start - flows` · `newestWithCapital.deltaPct = avgCap > 0 ? (newestWithCapital.deltaUsd / avgCap) * 100 : 0` (`:619-622`) | fuente |
| 32 | `frontend/src/hooks/useMonthlyData.js:636-700` | YTD del año | `ytdUsd` punta a punta, `ytdPct` por TWRR chain-link de los meses | `ytdUsd = endUsd - _ytdStart - flowsYear` (`:684`) · `ytdPct = (∏ (1 + deltaPct_mes / 100)) - 1) * 100` (docstring `:653`) | fuente |
| 33 | `frontend/src/pages/Dashboard.jsx:626-633` | `periodChange` | El chip pegado al gráfico de evolución («+USD X · +Y% en el mes») | `const delta = (last.valueUsd - last.netDeposited) - (first.valueUsd - first.netDeposited)` · `const dPct = first.valueUsd > 0 ? delta / first.valueUsd : 0` | consumidor de #8, fuente del chip |
| 34 | `frontend/src/pages/Dashboard.jsx:641-651` | `dailyVar` / `monthlyVar` | Las cards «Hoy» y «Este mes» | `computeDailyPnl(snapshots, { liveValue: totalValuePositions, liveNetDeposited: netDepositedPositions })` · `computeReturnDelta(..., { sinceDate: monthStart })` | consumidor de #1/#2 |
| 35 | `frontend/src/pages/HomeMobile.jsx:154-170` | `series30d` | Sparkline + delta 30 d del home mobile | `const deltaUsd = (last.valueUsd - last.netDeposited) - (first.valueUsd - first.netDeposited)` · `const deltaPct = first.valueUsd > 0 ? deltaUsd / first.valueUsd : 0` (`:161-162`) | consumidor de #8 |
| 36 | `frontend/src/pages/HomeMobile.jsx:189-203` | `kpis` | «P&L Mes» y «P&L Día» del home mobile | `computeReturnDelta(snapshots, { liveValue: compareValue, liveNetDeposited: aportado, sinceDate: monthStart })` · `computeDailyPnl(snapshots, {...})` | consumidor de #1/#2 |
| 37 | `frontend/src/utils/insightsModel.js:93` | `buildCumulativeReturnSeries` | Serie de rendimiento acumulado mensual (Insights). Tiene un **caso especial de import inicial** que ningún otro motor tiene | `const isImportInitialMonth = isFirst && capInicio === 0 && net > 0` · `const avgCapital = isImportInitialMonth ? net : capInicio + 0.5 * net` · `const rawReturn = avgCapital > 0 ? (capFinal - capInicio - net) / avgCapital : 0` · `const monthlyReturn = Math.max(rawReturn, -0.99)` (`:126-136`) | fuente |
| 38 | `frontend/src/utils/insightsModel.js:551` | `monthlyReturnArs` | El mismo retorno pero en pesos, con el flujo al TC medio geométrico | `const netArs = _net * Math.sqrt(fxPrev * fx)` · `const raw = (cfArs - ciArs - netArs) / avgArs` · `return Math.max(raw, -0.99)` (`:561-568`) | fuente |
| 39 | `frontend/src/utils/insightsModel.js:225` | `computeBestWorstMonth` | Mejor/peor mes. **Denominador `capInicio` pelado**, no Dietz | `const pnl = capFinal - capInicio - net` · `const pct = capInicio > 0 ? (pnl / capInicio) * 100 : null` (`:240-241`) | fuente |
| 40 | `frontend/src/utils/insightsModel.js:170` / `:373` | `computeDrawdownOnReturns` / `buildDrawdownTimeSeries` | Drawdown sobre la serie de retorno (no sobre valor absoluto) | ver docstring `:162-168` | fuente (hoy desplazada por `drawdownFromPerf`) |
| 41 | `frontend/src/utils/insightsModel.js:968` | `acumuladoDeVentana` | El acumulado de la ventana visible del gráfico | `pct = (((100 + v1) / (100 + v0)) - 1) * 100` (fallback, `:1019`) — con `total` presente usa `tFin` directo | fuente |
| 42 | `frontend/src/utils/insightsModel.js:1063` | `acumuladoPublicado` | KPI «Acumulado» leyendo `index_publicado` entre dos puntas aptas | `const pct = +((b.ip / a.ip - 1) * 100).toFixed(2)` (`:1084`) | fuente |
| 43 | `frontend/src/utils/insightsModel.js:600` | `applyMtmToMonthly` | Reemplaza `capital_inicio`/`capital_final` por snapshots MtM antes de calcular retornos | `if (s?.sintetico) continue` (`:626`) · mes en curso: `capital_final: valorMercadoLive` (`:655`) | fuente (pre-proceso) |
| 44 | `backend/performance.py:178` | `performance` | El endpoint `/api/insights/performance`: curva + benchmark **recortado al mismo rango** | delega en `twr.curva_indexada` (`:194`) | fuente |
| 45 | `backend/performance.py:38` | `_benchmark_diario` | Benchmark indexado a 1,0 en la primera fecha de la curva | `out.append({"date": f, "index": round(c / base, 6)})` (`:82`) | fuente |
| 46 | `backend/performance.py:86` | `benchmark_recortado` | Benchmarks porcentuales (inflación, plazo fijo) se **componen**; los de precio se rebasean | `idx *= (1.0 + float(datos[ym]) / 100.0)` (`:113`) · `por_mes[ym] = v / base_val` (`:129`) | fuente |
| 47 | `backend/ai/builders/dashboard_evolution.py:32` | `build` (topic `dashboard.evolution`) | Packet IA de la curva. **Delta bruto, sin flujos** | `delta_usd = value_end - value_start` · `delta_pct = (value_end - value_start) / value_start if value_start > 0 else 0` (`:87-88`) | fuente |
| 48 | `backend/ai/builders/dashboard_evolution.py:108-115` | mejor/peor mes del packet | Denominador `ci` pelado, clamp `[-0.95, 5.0]` | `ret = (cf - ci - net) / ci` · `ret = max(-0.95, min(5.0, ret))` | fuente |
| 49 | `backend/ai/builders/insights_evolution.py:29` | `build` (topic `insights.evolution`) | Retornos mensuales + TWR compuesto para la IA. **Descarta** el mes fuera de banda en vez de clampearlo | `ret = ((cf - dep + wd) / ci) - 1` · `if ret < -0.95 or ret > 5: continue` · `compound *= (1 + ret)` (`:59-62`) | fuente |
| 50 | `backend/ai/builders/dashboard.py:150-163` | `twr_30d_pct` / `delta_30d_usd` | Δ30d para el packet del Dashboard. **Bruto**, sobre `snapshots_medibles` | `twr_30d_pct = (end_val - start_val) / start_val` · `delta_30d_usd = end_val - start_val` | fuente |
| 51 | `backend/ai/builders/home.py:96-113` | `portfolio_today` | «Cuánto se movió tu cartera hoy» para la IA del Home. **Bruto**, últimos 2 `snapshots_medibles` | `portfolio_today["delta_usd_today"] = round(latest - prev, 2)` · `portfolio_today["delta_pct_today"] = round((latest / prev - 1) * 100, 2)` | fuente |
| 52 | `backend/ai/builders/home.py:188-224` | `change_pct_today` por ticker | Mapea el `change_pct` de `_fetch_batch_quotes` a cada holding | `ticker_change[base] = round(float(q["change_pct"]), 2)` (`:215`) | consumidor de #18 |
| 53 | `backend/main.py:15413` | `_detect_and_remove_corrupt_snapshots` | Usa la variación día-a-día para **borrar** snapshots corruptos (V-shape) | `drop_from_prev = (cur_v - prev_v) / prev_v` · `recovery_to_next = (next_v - cur_v) / cur_v` (`:15475-15476`) | fuente (mantenimiento) |
| 54 | `backend/main.py:15320` | `_historical_cagr_global` (`/api/goals/cagr`) | El rendimiento histórico / anual. Delega en `twr.curva_indexada`; solo anualiza si la ventana ≥ medio año | `"total_return_pct": (round(c["twr"] * 100, 2) if ...)` (`:15381`) | consumidor de #4 |
| 55 | `frontend/src/pages/Dashboard.jsx:676-693` | `cagrVar` | Card «Anual» / «Desde que medimos» | `return { pct: rendHist.cagr / 100, ... }` (`:684`) | consumidor de #54 |
| 56 | `frontend/src/pages/Positions.jsx:1624-1645` | `daily` (useMemo) | ⚠️ **CÓDIGO MUERTO**: delta bruto vs el último snapshot, sin `esApto` ni ajuste de flujos. Nadie lo lee | `const delta = totals.value - lastClose.total_value` · `const pct = delta / lastClose.total_value` (`:1629-1630`) | huérfano |
| 57 | `frontend/src/components/home/AssetMiniChart.jsx:58` | `AssetMiniChart` | Delta del período del mini-chart (1S/1M/3M/1A) del quick-view | `const delta = (first != null && last != null) ? ((last / first - 1) * 100) : null` | fuente |
| 58 | `frontend/src/components/Sparkline.jsx:46` | `Sparkline` | Autodetección de color por «variación» de la serie | `const autoPos = values[values.length - 1] >= values[0]` | consumidor |
| 59 | `frontend/src/utils/demo.js:173-187` | `PREV_CLOSE` (modo demo) | **Fabrica** el cierre anterior con un hash determinístico y sesgo positivo | `const dailyChange = ((hash % 450) - 200) / 10000` · `const prev = price / (1 + dailyChange)` | fuente (demo) |
| 60 | `frontend/src/utils/demo.js:657-662` | `delta_1d` (modo demo) | Δ1d sintético del summary demo | `const r = ((seed % 13) - 6) * 0.0008` · `return { usd: +(nowVal * r).toFixed(2), pct: +(r * 100).toFixed(2) }` | fuente (demo) |

**Predicados que gobiernan todo lo anterior:**

| archivo:línea | qué decide |
|---|---|
| `frontend/src/utils/evolution.js:31` `esApto` | ¿esta fila puede ser PICO, BORDE o DENOMINADOR? — `s.apto !== undefined ? !!s.apto : !s.sintetico` |
| `frontend/src/utils/evolution.js:43` `esDibujable` | ¿entra a la línea? — `ACEPTA_LINEA.includes(s.clase)`, con `ACEPTA_LINEA = ['medicion','reconstruido','intradia']` (`:20`) |
| `frontend/src/utils/evolution.js:113` `baseIncomparable` | ¿la resta mide el período o la brecha entre dos formas de medir? — `(inicioValor / baseTotal) > 0.10` (`:117`) |
| `backend/twr.py:181` `clasificar_fila` / `:365` `clasificar_serie` | Asigna `medicion` / `reconstruido` / `intradia` / `sintetico_costo` / `indeterminado` |
| `backend/twr.py:247` `es_apto` | La versión backend del mismo predicado |
| `backend/reporting/builder.py:295` `fetch_snapshot_at_or_before` | Borde de APERTURA; `mtm_only=True` exige `MEDICION`, `accept=` afloja |
| `backend/reporting/builder.py:394` `fetch_latest_measured_snapshot` | Borde de CIERRE (el espejo que faltaba) |
| `backend/main.py:1461` vista `snapshots_medibles` | «Un lector nuevo que escriba `FROM snapshots_medibles` hace lo correcto por default» |

---

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `frontend/src/pages/Dashboard.jsx:980-983` | card `VarCell` con `dailyVar` | **«Hoy»** (o «Últimos N días» si `dayDiff > 1`) |
| `frontend/src/pages/Dashboard.jsx:985-989` | card `VarCell` con `monthlyVar` | **«Este mes»** (+ subdato «realizado ±X») |
| `frontend/src/pages/Dashboard.jsx:991-1002` | card `VarCell` con `cagrVar` | **«Anual»** o **«Desde que medimos»** (el rótulo sigue al número) |
| `frontend/src/pages/Dashboard.jsx:966-974` | encabezado + tooltip del bloque | **«Rendimiento»** · *"Variación de tus posiciones, sin contar aportes/retiros"* |
| `frontend/src/pages/Dashboard.jsx:1068-1073` | chip pegado al gráfico (`periodChange`) | **«+USD X · +Y% en el mes»** (label de rango en `rangeLabel`, `:1352`) |
| `frontend/src/pages/Dashboard.jsx:1076-1079` | fallback del chip | **«Sin rendimiento medible en {rango}»** |
| `frontend/src/pages/Dashboard.jsx:1018-1030` | card de vacío explicado | **«Rendimiento del período — Todavía no podemos medirlo»** + `textoSinMedicion` |
| `frontend/src/pages/HomeMobile.jsx:388` | mismo texto en mobile | `textoSinMedicion(sinMedicion)` |
| `frontend/src/pages/Positions.jsx:2261`, `:2577` | encabezado de tabla desktop | **«Var. día»** |
| `frontend/src/pages/Positions.jsx:82` | opción de orden | **«Var. día %»** (`sortBy: 'day_pct'`) |
| `frontend/src/pages/Positions.jsx:2323`, `:2616` | celda por fila (`dvArs` / `dvUsd`) | monto + % del día |
| `frontend/src/pages/Positions.jsx:2065-2094` | pie/total de la tarjeta del broker | Var. día agregada; `—` si ningún símbolo tiene cierre previo |
| `frontend/src/pages/PositionsMobile.jsx:2082` | columna de la tabla mobile | **«Hoy»** |
| `frontend/src/pages/PositionsMobile.jsx:2605-2615` | celda mobile | monto (`dayDisp`) + `pctSigned(p.dayVarPct)` |
| `frontend/src/pages/PositionsMobile.jsx:2493-2496` | barrita de color de la fila | dirección del día (`bg-rendi-pos` / `bg-rendi-neg` / apagada) |
| `frontend/src/pages/Reports.jsx:628-638` | KPI de Reportes | **«Δ último cierre»** · sub `+X% · vs {fecha}` |
| `frontend/src/pages/Reports.jsx:641-649` | KPI de Reportes | **«Δ 7 días»** |
| `frontend/src/pages/Reports.jsx:652-660` | KPI de Reportes | **«Δ 30 días»** |
| `frontend/src/pages/Reports.jsx:853` | nota de movers | *"Mejor/peor activo por variación: se empieza a medir desde hoy"* |
| `frontend/src/pages/Insights.jsx:579-583` | serie del gráfico | curva de rendimiento acumulado (USD/ARS) |
| `frontend/src/pages/Insights.jsx:2794-2810` | KPI de la ventana visible | `acumuladoPublicado` / `acumuladoDeVentana` |
| `frontend/src/pages/Insights.jsx:1796` | tira de KPIs + card | drawdown (`drawdownFromPerf`) |
| `frontend/src/components/MonthlyTeaser.jsx:37-60` | banner del Dashboard | rendimiento del mes en curso, o **«en curso»** sin número |
| `frontend/src/components/home/IndicesStrip.jsx:57-66` | strip del Home | **«▲/▼ X,XX%»** por índice |
| `frontend/src/components/mobile/MobileTopBar.jsx:113-118` | ticker bar mobile | mismo `change_pct`, 6 ítems |
| `frontend/src/components/home/Heatmap.jsx:245`, `:272` | heatmap | color + `fmtPct(b.change_pct)` |
| `frontend/src/components/home/MoversRail.jsx:27-38` | riel de movers | gainers / losers del día |
| `frontend/src/components/home/Watchlist.jsx:107-134` | watchlist | `change_pct` por símbolo |
| `frontend/src/pages/AdvisorDashboard.jsx:209-214` | hero del libro | Δ7d del AUM (`delta_7d_usd` + `delta_7d_pct`) |
| `frontend/src/pages/AdvisorDashboard.jsx:344-370` | fila por cliente | Δ7d + barra proporcional; `«… · todo mercado»` cuando no hubo flujos |
| `frontend/src/components/advisor/ClientMoveAlert.jsx:2` | config de alertas del asesor | «avisame si la cartera de un cliente se mueve X%» |
| `frontend/src/components/alerts/AlertsManager.jsx:223`, `:266` | form de alertas | **«Variación %»**, con baseline **«En el día»** (`prev_close`) vs «Desde ahora» (`set_price`) |
| `frontend/src/pages/Alertas.jsx:1`, `:39` | página | *"Avisos de precio objetivo y variación sobre tus activos"* |
| `frontend/src/pages/guia/Novedades.jsx:134` | guía pública | *"Variación % (Plus y Pro): asimétrica…"* |
| `frontend/src/components/LazySparkline.jsx` + `frontend/src/pages/Positions.jsx:2251`, `:2570` | columna de tabla | **«30D»** (sparkline de precio, 1 mes) |
| `frontend/src/components/home/AssetMiniChart.jsx:79-` | quick-view de activo | delta del período (1S/1M/3M/1A) |
| `backend/home/briefing.py:72-76` | brief por email | selecciona holdings con `abs(change_pct) >= 1.5` |
| `backend/main.py:23106-23113` | contexto del chat IA | `user_30d` sale de `delta_30d.pct` del summary |

---

### Dónde se persiste

**La variación en sí NUNCA se persiste. Siempre se calcula al vuelo.** Lo que se persiste son los *insumos*.

| tabla | columnas | qué aporta |
|---|---|---|
| `snapshots` | `date`, `total_value`, `total_invested`, `net_deposited`, `fx_to_usd_blue`, `holdings_json`, `source`, `mtm_coverage`, `base`, `apto` | [V] `backend/schema_pg.sql:1525-1539`. Es LA materia prima de toda variación de cartera. `net_deposited` es `NOT NULL DEFAULT 0` y el 0 significa «no lo tengo» (`frontend/src/utils/evolution.js:254-268`); `apto`/`base` los estampa `twr.estampar_base` (`backend/twr.py:1163`). ⚠️ La copia de dev `backend/trading.db` está vieja: su `snapshots` no tiene `source`, `holdings_json`, `mtm_coverage`, `base` ni `apto`. |
| vista `snapshots_medibles` | (proyección de `snapshots` con `apto=1`) | [V] creada en el arranque, `backend/main.py:1459-1471`, y también en `backend/schema_pg.sql:1997`. Filtra por `apto`, con COALESCE heurístico mientras la migración no estampó |
| `monthly_entries` | `capital_inicio`, `capital_final`, `deposits`, `withdrawals`, `pnl_realized`, `pnl_unrealized` | La cadena CONTABLE: base del delta mensual/YTD cuando no hay snapshots medidos |
| `alerts` | `baseline text DEFAULT 'prev_close'`, `up_pct`, `down_pct`, `anchor_price` | [V] `backend/schema_pg.sql:472`, `:504`. Define contra qué se mide la variación de una alerta |
| `advisor_alerts` / `advisor_alert_state` | `up_pct`, `down_pct`, `armed` | El umbral y el edge-trigger de la alerta del asesor |
| `asset_last_price` | `symbol`, `price`, `updated_at` | Último precio real conocido; evita que una posición sin precio caiga a costo e invente un salto en la variación del día siguiente (`backend/snapshots_job.py:558-563`) |
| `fx_rates_daily` | `date`, `blue_venta`, `mep_venta` | TC por fecha para las curvas en pesos |
| `alert_events` | `fired_at`, `symbol`, `price` (o `change_pct` si no hay precio) | Historial de disparos; `backend/alerts_engine.py:320` mete `change_pct` **en la columna de precio** cuando `price is None` |

**Caches en memoria (no son persistencia, pero determinan qué número ve el usuario):**
- `_PREVCLOSE_CACHE` TTL 600 s (`backend/main.py:7579-7581`)
- `_QUOTE_CACHE` TTL 60 s (`backend/home/market.py:263-264`)
- `_history_cache` TTL 3600 s (`backend/main.py:8039-8040`)
- caches de `indices_strip` 900 s, heatmaps 1800 s / cripto 900 s (`backend/home/market.py:375`, `:447-455`)

---

### ⚠️ Implementaciones divergentes

**No convergen.** Hay al menos **siete** definiciones distintas conviviendo.

#### D-1 · «Variación del día de la cartera»: cinco fórmulas, cinco pantallas

| variante | fórmula literal | filtra puntas por `apto`? | descuenta flujos? | qué pantalla la ve |
|---|---|---|---|---|
| **A. Canónica** `computeReturnDelta` (`frontend/src/utils/evolution.js:363-365`) | `(todayValue - todayNetDep) - (prev.total_value - netDepositedOf(prev))`, `pct = usd / prev.total_value` | **Sí**, las dos (`:318`) | **Sí** | Dashboard «Hoy» (`Dashboard.jsx:641`), HomeMobile «P&L Día» (`HomeMobile.jsx:199`) |
| **B. Backend Reportes** `_snapshot_delta` (`backend/main.py:32939`) | `(latest_value - cur_netdep) - (prev_v - prev_netdep)`, `pct = delta_usd / prev_v` | Apertura sí (`accept=(MEDICION, INDETERMINADO)`), cierre vía `fetch_latest_measured_snapshot` | **Sí** | Reportes «Δ último cierre» (`Reports.jsx:628`) |
| **C. IA Home** (`backend/ai/builders/home.py:112-113`) | `latest - prev`, `pct = (latest/prev - 1)*100` | Sí, por la vista `snapshots_medibles` | **No** | packet `home` que se le manda al modelo |
| **D. Asesor por cliente** (`backend/main.py:38001-38011`) | `d = tv - then_v`, `pct = d / then_v * 100` | Sí (`_es_base_de_mercado` en las dos puntas, `:37993`) | **No** en el titular; los flujos van aparte en `flows_7d_usd` | AdvisorDashboard, fila por cliente |
| **E. Cartera desktop** `daily` (`frontend/src/pages/Positions.jsx:1629-1630`) | `totals.value - lastClose.total_value`, `pct = delta / lastClose.total_value` | **No** | **No** | ⚠️ **ninguna — es código muerto** (el banner está deshabilitado, `Positions.jsx:1908-1909`; `daily` no se referencia en ningún otro lado) |

La consecuencia práctica: **el mismo día, el mismo usuario, ve tres números distintos** para «cuánto se movió mi cartera hoy» según abra el Dashboard (A), Reportes (B) o le pregunte al chat (C). Con un depósito ese día, C y D lo cuentan como ganancia y A y B no.

#### D-2 · Denominador del % del período: cuatro criterios

| criterio | dónde | efecto |
|---|---|---|
| `value_anterior` pelado | `evolution.js:365`, `main.py:32943`, `advisor_alerts.py:289` | El % no es Dietz: con un aporte grande a mitad de período el % queda inflado respecto del Dietz |
| Modified Dietz `v0 + 0,5·flujos` | `twr.dietz` (`backend/twr.py:573`), `_modified_dietz_pct` (`backend/reporting/builder.py:790`), `useMonthlyData.js:378`, `evolution.js:536` | El estándar del repo |
| `capital_inicio` pelado | `insightsModel.js:241` (`computeBestWorstMonth`), `ai/builders/dashboard_evolution.py:112`, `ai/builders/insights_evolution.py:59` | Mejor/peor mes y packets de IA usan otro denominador que la curva |
| `net` (el depósito) como base completa | `insightsModel.js:127-129` (`isImportInitialMonth`), `insightsModel.js:566` | Caso especial que **solo** existe en `insightsModel.js`: `capInicio === 0 && net > 0` |

#### D-3 · Clamps del retorno de un tramo: cuatro políticas

| política | dónde |
|---|---|
| Piso −100 %, **sin techo** | `backend/twr.py:577` (`max(..., -1.0)`) |
| Piso −99 %, sin techo | `frontend/src/utils/evolution.js:544`, `:582`; `insightsModel.js:136`, `:568` |
| Clamp `[-0.95, +5.0]` | `backend/ai/builders/dashboard_evolution.py:113` |
| **Descarta** el mes fuera de `[-0.95, 5]` | `backend/ai/builders/insights_evolution.py:60-61` |
| **Sin clamp** | `backend/reporting/builder.py:783-794` (`_modified_dietz_pct`, documentado: *"NO clampa"*) |

Los dos motores de curva ya se pusieron de acuerdo en quitar el techo de +50 % (`backend/twr.py:565-571` y `frontend/src/utils/evolution.js:539-543` dicen literalmente lo mismo), pero los builders de IA quedaron atrás.

#### D-4 · Los DOS motores de la curva de evolución: JS vs Python

| | `buildEvolutionFromSnapshots` (JS) | `curva_indexada` (Python) |
|---|---|---|
| archivo | `frontend/src/utils/evolution.js:407` | `backend/twr.py:1611` |
| heurística big-withdraw | **Sí**: `isBigWithdraw = flows < 0 && flowRatio > 0.3` → `avgCap = prevValueUsd` (`:534-536`) | **No existe** |
| cota de leg (`leg_dudoso`) | **No** | **Sí** (`backend/twr.py:623`) |
| corta por hueco de días | **No** | **Sí** (`max_hueco_dias`) |
| corta por cambio de base | **No** | **Sí** (`seg_por_base`, `:1802`) |
| índices que produce | uno (`cumUsd`) | tres (`idx`, `idx_dib`, `idx_est`) |
| ARS | recalcula todo con `lookupHistoricalDolar` por punto (`:566-586`), reconociendo en el comentario que *"técnicamente el % se mantiene"* | `_leg_en_moneda` + `_factor_fx` para arrastrar la devaluación en el traspaso de base (`:1832-1840`) |
| quién lo ve | gráfico de Insights (`Insights.jsx:579`) | `/api/insights/performance` → curva + benchmark, KPI acumulado, drawdown, `/goals/cagr` → card «Anual» del Dashboard |

**Los dos alimentan la MISMA pantalla (Insights) al mismo tiempo**: la serie dibujada sale del motor JS (`Insights.jsx:579-583`) mientras el KPI de la ventana, el drawdown y el veredicto salen del motor Python (`Insights.jsx:1796`, `:2279-2282`, `:2794-2810`). El propio `performance.py:1-14` documenta que existe porque *había TRES motores independientes produciendo el mismo acantilado* — pero el tercero (`evolution.js`) sigue vivo y sigue dibujando.

#### D-5 · «Var. día» por posición: desktop ≠ mobile

| | desktop (`Positions.jsx:1528-1560`) | mobile (`PositionsMobile.jsx:797-840`) |
|---|---|---|
| gate por confianza del precio | solo `p.is_cash \|\| p.price_override` (`:1531`) | además `priceTrusted` — si el guard rechazó el precio y el valor cayó a costo, **no emite variación** (`:803`) |
| lote USD en broker ARS (`costInUsd`) | **no tiene rama**: usa `priceSymbol(p.asset, true, ...)` y compara USD contra un cierre en ARS | rama explícita `usdInArBroker` / `usdSymBA` que divide el previo por `tcCedear` (`:818-822`) — el comentario dice que sin eso daba «~-100 %» |
| rate para pasar el monto a la otra moneda | `dv.amount / tcCedear` (`:1553`) | `dayVarUsd * tcValuacion` en la rama USD-en-ARS (`:833`), `dayVarLocal / tcValuacion` en el resto (`:836`) |
| % del agregado | no recalcula: el orden usa `dv.pct` del primer lote (`:1064`) | recalcula sobre el valor de ayer: `dayVarLocal / (curLocalValue - dayVarLocal)` (`:962`) |
| agregado cross-moneda | acumula en USD y multiplica por `tcCedear` (`:2087-2094`) | `multiCcy ? dayVarUsd : Σ dayVarLocal` (`:958-959`) |

Es la **misma columna** («Var. día» en desktop, «Hoy» en mobile) con dos implementaciones y al menos una diferencia de comportamiento verificable: un lote de costo-en-USD dentro de un broker ARS.

#### D-6 · `prev_close`: tres fuentes que pueden discrepar

`backend/main.py:7867` resuelve el cierre anterior por **tres caminos distintos**, con esta prioridad:
1. **data912** para `.BA` no-cripto/no-CEDEAR-USD: `c / (1 + pct/100)`; con mercado cerrado (`pct=0`) devuelve `previo = actual` → variación 0 (`:7900-7917`).
2. **Batch yfinance** `period="1mo"`, `iloc[-2]` — salvo que la última barra del símbolo sea más vieja que la del lote, en cuyo caso toma `iloc[-1]` (`:7995-8001`).
3. **`fast_info.previous_close`** per-símbolo para los que el batch no resolvió (`:8008-8012`).

Mientras tanto `backend/home/market.py` usa un cuarto camino para el MISMO concepto: `period="5d"` + `closes.iloc[-2]`, con `auto_adjust=False` (`:307-315`) — contra el `auto_adjust=True` de `/api/prices/prev-close` (`:7969`). O sea: **el `change_pct` que ve el usuario en el heatmap del Home puede no coincidir con el `pct` de la fila de su cartera para el mismo ticker**, porque uno usa precios ajustados por dividendos y el otro no.

#### D-7 · Ventana de snapshots: 30 filas vs 3650 filas

`GET /api/snapshots?days=N` implementa `days` como **`LIMIT N` filas**, no como una ventana de días — el propio `HomeMobile.jsx:149-152` lo documenta.

| pantalla | pide | consecuencia |
|---|---|---|
| Dashboard (`Dashboard.jsx:145`) | `days=3650` | `computeReturnDelta` ve toda la historia |
| Insights (`Insights.jsx:365`) | `days=3650` | idem |
| `useMonthlyData` (`useMonthlyData.js:173`) | `days=3650` | idem |
| **HomeMobile** (`HomeMobile.jsx:67`) | `days=30` | las mismas funciones ven **solo 30 filas** |
| Positions (`Positions.jsx:461`) | `days=30` | alimenta el `daily` muerto |

En HomeMobile, si dentro de esas 30 filas no hay ninguna `apto` anterior al 1° del mes, `computeReturnDelta` cae al fallback `desc[desc.length - 1]` (`frontend/src/utils/evolution.js:346`) — que es la fila más vieja **de las 30**, no la del cierre del mes pasado. El «P&L Mes» de mobile y el «Este mes» de desktop pueden entonces medir períodos distintos, con el mismo rótulo.

---

### Zonas grises

**Z-1 · `AssetQuickView` promete variación diaria y no la muestra.**
El encabezado dice *"V1: precio, variación diaria, market cap"* (`frontend/src/components/home/AssetQuickView.jsx:3`), define `fmtPct` (`:16-20`) e importa `TrendingUp, TrendingDown` (`:10`) — pero el fetch solo guarda `{ price: prices[symbol], symbol }` (`:44`) y la única lectura de `quote` es `fmtPrice(quote.price)` (`:121`). `fmtPct` y los dos íconos **no se usan en ninguna línea del archivo**. [V] verificado con grep.

**Z-2 · La columna «30D» compara el ticker equivocado para los CEDEARs.**
`LazySparkline` recibe `symbol={(p.asset || '').toUpperCase()}` (`frontend/src/pages/Positions.jsx:2448`, `:2688`) — el ticker *pelado*, no el símbolo con el que se valúa la fila. Para un CEDEAR o un activo en broker ARS, la fila muestra precio y Var. día del `.BA` y la sparkline de 30 días del subyacente US. Todo el resto del archivo hace justo lo contrario: `dvFor` rutea explícitamente a `priceSymbol(p.asset, true, p.asset_type)` para evitar comparar GGAL local contra el ADR (`Positions.jsx:1543-1550`).

**Z-3 · El rango «1D» del gráfico no puede producir un día.**
`buildPortfolioValueSeries(snapshots, 1, ...)` corta en `Date.now() - 86400000` (`frontend/src/utils/evolution.js:222`). Con snapshots diarios eso deja típicamente 1 punto dentro de la ventana, y el código cae al *anchor* (`:236-240`) o a `points.slice(-Math.max(2, filtered.length))` (`:241`). El chip `periodChange` va a decir «en el día» sobre una resta que puede abarcar dos ruedas. Y `RangeTabs` no tiene un rango `3M`, pero `Dashboard.jsx:1046` pregunta `range === '3M' ? 90` — rama muerta.

**Z-4 · `snapshots_medibles` no protege el `SELECT *`.**
La vista se crea con `SELECT * FROM snapshots` (`backend/main.py:1461`) y solo se crea **si** las columnas `base` y `apto` ya existen (`:1441`). En un deploy donde el código llega antes que la migración, la vista no existe y los lectores que la nombran (`ai/builders/home.py:97`, `ai/builders/dashboard.py:105`, `main.py:18024`, `:37162`) fallan. Hay un comentario que reconoce el riesgo en `main.py:18046` («Sin la vista `snapshots_medibles` (deploy a medio migrar)…») pero no lo vi mitigado en los builders de IA. [I] — inferido de que esos tres call sites no tienen `try` alrededor de la query; no verifiqué el stack completo de cada uno.

**Z-5 · El POST de snapshots lo dispara el navegador, y eso decide la variación de mañana.**
`Dashboard.jsx:466-495` escribe el snapshot del día desde el browser, con guardas: `valuationDollar === 'mep'` (si mirás en CCL no escribe), `priceCoverage >= 0.95`, y una marca en `localStorage`. El cron backend usa el mismo umbral (`backend/snapshots_job.py:733`). Pero el propio POST advierte que *"con solo abrir la lente de un cliente"* el asesor podía escribir la serie del cliente (`backend/main.py:5007-5011`) — el guard está ahí, pero el hecho de que la fila del día dependa de **quién abrió la app y con qué toggle** hace que la variación del día siguiente dependa de un evento de UI.

**Z-6 · `sintetico = not apto` colapsa dos preguntas y el código lo sabe.**
`backend/main.py:5164` define `d["sintetico"] = not d["apto"]`, y `frontend/src/utils/evolution.js:25-29` documenta que eso es incorrecto: una foto INTRADIA sale `sintetico=true` sin haber sido fabricada. `applyMtmToMonthly` (`insightsModel.js:626`) filtra por `s?.sintetico` — o sea que descarta también las intradías legítimas al convertir la cadena mensual a mercado. Los dos comentarios están escritos, la contradicción sigue en pie.

**Z-7 · La variación del asesor no descuenta flujos en el titular.**
`backend/main.py:37020` publica `d = now_v - then_v` como Δ7d del libro. Un cliente que depositó US$50.000 esa semana engorda el «cuánto se movió el libro». En la vista por cliente el código sí separa `flows_7d_usd` y `market_7d_usd` (`:38008-38011`) y el frontend rotula «todo mercado» cuando corresponde (`AdvisorDashboard.jsx:360`), pero el **agregado del hero** (`_delta`, `:37018-37021`) no tiene esa separación. Es la misma clase de defecto que `computeReturnDelta` documenta haber arreglado del lado retail (`evolution.js:280-284`).

**Z-8 · `alert_events` guarda `change_pct` en la columna de precio.**
`backend/alerts_engine.py:320`: `price if price is not None else change_pct`. Cuando no hay precio, el porcentaje queda escrito donde el esquema espera un precio. No parece romper nada hoy (el mensaje ya viene compuesto), pero cualquier lector posterior de esa columna va a leer un 3,2 como si fuera un precio.

**Z-9 · La `1D` del `/api/prices/prev-close` cuando data912 dice `pct=0`.**
`backend/main.py:7917`: con el mercado cerrado el feed manda `pct=0` y el código devuelve `previo = actual`, o sea variación exacta 0. Es una decisión deliberada y comentada (mejor 0 que un valor viejo de yfinance), pero significa que **fuera de rueda todas las filas `.BA` muestran «+0,00 %»**, que la UI pinta igual que «no se movió» — el mismo problema de «un cero falso es peor que un vacío» que `evolution.js:353-360` resolvió del otro lado.

**Z-10 · `_snapshot_delta` acepta `INDETERMINADO` en la apertura pero el cierre viene de otra función.**
`backend/main.py:32755-32757` pasa `latest_value`/`latest_date` que salen de `fetch_latest_measured_snapshot(conn, uid, accept=(_MED, _IND))` (`:32675`). El comentario de `:32662-32672` describe que *"acá nace la asimetría que nadie vio"* y dice que la query del cierre iba **sin filtrar** — pero la línea que sigue ya usa `fetch_latest_measured_snapshot`. [I] Leo eso como un comentario que sobrevivió al fix; no encontré una segunda query sin filtrar en esa función. Vale confirmarlo antes de creerle al comentario.

**Z-11 · `computeBestWorstMonth` y el packet de IA no comparten el pre-proceso MtM.**
`Insights.jsx:1773` llama a `computeBestWorstMonth(globalMonthly)` donde `globalMonthly` **sí** pasó por `applyMtmToMonthly` (`:535`). Pero `backend/ai/builders/insights_evolution.py:34-40` lee `monthly_entries` crudo. El propio comentario de `applyMtmToMonthly` (`insightsModel.js:589-598`) explica que en meses cerrados la cadena está al costo y el retorno mide *solo lo realizado*. O sea: el «mejor mes» que ve el usuario y el que ve el modelo pueden ser meses distintos.

**Z-12 · El modo demo fabrica la variación con sesgo positivo, a propósito.**
`frontend/src/utils/demo.js:171-172`: *"Drift -2% a +2.5% con bias hacia positivo (más symbols 'en verde' hoy = portfolio demo se ve más atractivo para marketing)"*. Está declarado, pero cualquiera que use el demo para validar la Var. día está midiendo un hash.

**Z-13 · Lo que NO encontré.**
- Un endpoint backend que sirva la variación diaria de cartera lista para consumir por el Dashboard: **no encontrado**. El Dashboard la calcula en el browser desde `/api/snapshots`.
- Snapshots por broker: **no encontrado**. `useMonthlyData.js:303-306` lo dice explícito y por eso la sparkline no se renderiza con filtro de broker; `_snapshot_delta` devuelve `None` para `broker_filter != "global"` (`backend/main.py:32755`).
- Un test que compare el resultado de `buildEvolutionFromSnapshots` (JS) contra `twr.curva_indexada` (Python) sobre los mismos datos: **no encontrado**.
- Un test frontend de `dayVarOf` / `dvFor` (Positions) o de la Var. día mobile: **no encontrado** — el único `.test.js` de esa familia es `frontend/src/utils/evolution.test.js`, que cubre `computeDailyPnl`/`computeReturnDelta`/`buildPortfolioValueSeries`/`buildEvolutionFromSnapshots`, y `frontend/src/hooks/useMonthlyData.test.js`.
