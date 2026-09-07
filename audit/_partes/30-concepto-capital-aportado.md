## Capital aportado, flujos de fondos, depósitos y retiros

### Definición según el código

**[V] En Rendi, "capital aportado" NO es un campo: es una suma sobre la tabla `monthly_entries`, y su fórmula canónica es:**

```
capital aportado (net_deposited) = capital_inicio de la PRIMERA fila del broker 'global'
                                 + Σ (deposits − withdrawals) de TODAS las filas de 'global'
```

Está escrita literal en `backend/snapshots_job.py:369-385` (`compute_net_deposited_db`) y replicada en `backend/snapshots_job.py:398-402` (`compute_net_deposited`).

Cinco cosas que hay que saber para leer cualquier número de esta familia:

1. **[V] `monthly_entries` vive SIEMPRE en USD.** Lo dice el código en `backend/main.py:10175-10177` ("Ambas entradas (broker + global) se guardan en USD. Toda la tabla monthly_entries usa USD como unidad"). Cada depósito en pesos se dolariza al escribirlo, y el TC con el que se dolarizó **no se guarda en ninguna parte** (`backend/main.py:18368` lo declara como gap de auditoría).

2. **[V] Hay una fila sintética `broker='global'` que NO es un broker.** Es el agregado cross-broker y se escribe en paralelo a la fila del broker real: todos los call sites llaman dos veces a `_update_monthly_flow`, una con el broker y otra con `'global'` (p. ej. `backend/main.py:10242-10245`). `'global'` es nombre reservado (`backend/main.py:4187-4194`).

3. **[V] El "baseline" (`capital_inicio` de la primera fila) cuenta como aportado.** Es la plata que ya estaba cuando el usuario empezó a trackear. Sin él el % "sobre lo aportado" se infla (comentario en `frontend/src/utils/insightsModel.js:33-38`). **Pero no todos los lectores lo incluyen** — ver divergencias.

4. **[V] Los flujos tienen DOS fuentes y la columna las mezcla:**
   - importados (`import_normalized_tx` con `operation_type IN ('DEPOSIT','WITHDRAW')` de batches `confirmed` y sin `excluded_at`),
   - manuales (botón Cash de Cartera, reconcile-cash, form /mensual, autodepósito, chat).

   El recalc autoritativo reconstruye: `deposits = imports_confirmados + manual` (`backend/main.py:9584`: `new_deposits = round(imp_deposits + manual_dep, 4)`). Lo manual vive aparte en `manual_deposits` / `manual_withdrawals` justo para que el recalc pueda pisar `deposits` sin borrarlo.

5. **[V] Definición NO estándar #1: un dividendo/interés NO es aporte, pero un "ajuste de foto" SÍ.** El dividendo va a `pnl_realized` (`backend/importing/persister.py:938-997`), pero:
   - el **autodepósito** que Rendi inventa cuando cargás una posición sin saldo se registra como DEPÓSITO (`backend/main.py:9809-9872`),
   - el **true-up de cash contra una foto de tenencia** emite DEPOSIT/WITHDRAW sintéticos (`backend/importing/tenencia.py:670-697`),
   - el **seed de apertura** de una foto de tenencia emite un DEPOSIT sintético (`backend/importing/tenencia.py:626-631`),
   - el **reconcile-cash** contra el saldo real del broker emite un depósito o retiro sintético (`backend/main.py:10078-10105`),
   - una **conversión ARS→USD importada** escribe un retiro en la pata ARS y un depósito en la pata USD (`backend/importing/persister.py:1139-1143`).

   O sea: el "capital aportado" de Rendi incluye ajustes contables sintéticos, no solo transferencias reales del bolsillo del usuario.

6. **[V] Definición NO estándar #2: `capital_final` no es una valuación, es una identidad contable.**
   `capital_final = capital_inicio + deposits − withdrawals + pnl_realized (+ pnl_unrealized solo en el mes en curso)` — `backend/main.py:9717-9719` y `backend/main.py:9737-9739`. Por eso `end − start − flows ≡ pnl_realized` para un mes cerrado, y el `basis: "contable"` del reporte lo dice explícito (`backend/reporting/schema.py:88-96`).

---

### Dónde se calcula

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `backend/snapshots_job.py:328` | `compute_net_deposited_db` | **SSoT declarada.** Σ flujos + baseline opcional, con corte temporal y filtro por broker | `SELECT COALESCE(SUM(deposits) - SUM(withdrawals), 0) AS net FROM monthly_entries WHERE {where}` … `return baseline + flows` | fuente (lectura canónica) |
| 2 | `backend/snapshots_job.py:388` | `compute_net_deposited` | gemela in-memory de (1) para el cron | `baseline = globals_sorted[0].get('capital_inicio') or 0` ; `flows = sum((m.get('deposits') or 0) - (m.get('withdrawals') or 0) …)` ; `return baseline + flows` | fuente |
| 3 | `backend/main.py:9414` | `_recalc_pnl_realized_from_ops` | **El escritor autoritativo.** Reconstruye `deposits`/`withdrawals`/`pnl_realized` de cada fila desde las fuentes y re-repara la cadena | `new_deposits = round(imp_deposits + manual_dep, 4)` (`:9584`) | fuente (escribe) |
| 4 | `backend/main.py:589` | `_import_flows_for_period` | suma DEPOSIT/WITHDRAW importados del período, en USD | `CASE WHEN n.gross_amount_usd IS NOT NULL THEN n.gross_amount_usd WHEN UPPER(n.currency)='ARS' AND ? > 0 THEN n.gross_amount / ? ELSE n.gross_amount END` | fuente |
| 5 | `backend/main.py:9918` | `_update_monthly_flow` | suma/resta un flujo puntual a la fila del mes y mueve `capital_final` en la misma dirección | `sets = [f"{col_amt} = {col_amt} + ?", f"capital_final = capital_final {cap_sign} ?"]` | fuente (escribe) |
| 6 | `backend/main.py:9661` | `_repair_monthly_chain` | encadena `capital_inicio[N+1] = capital_final[N]` y recalcula meses cerrados | `new_cap_final = round(new_cap_inicio + deposits - withdrawals + pnl_realized, 4)` | fuente (escribe) |
| 7 | `backend/main.py:9809` | `_autodeposit_if_overdraw` | si cargás una posición sin saldo, sube el cash y **registra el faltante como capital aportado** | `amount_usd = (shortfall / tcb) if (currency == "ARS" and tcb > 0) else shortfall` (`:9859`) | fuente (escribe) |
| 8 | `backend/main.py:661` | `_derive_manual_flows` | del form /mensual saca la porción manual = lo que excede los imports | `return (max(0.0, float(deposits or 0) - imp_dep), max(0.0, float(withdrawals or 0) - imp_wit))` | fuente |
| 9 | `backend/main.py:629` | `_backfill_manual_flows` | migración one-time: separa el residual manual hacia `manual_*` | `man_dep = max(0.0, float(r["deposits"] or 0) - imp_dep)` | fuente (escribe, migración) |
| 10 | `backend/main.py:10126` | `POST /api/cash/flow` | botón Depositar/Retirar. Dolariza con el MEP de la **fecha del movimiento** resuelto en el servidor | `_rate = _fx.fx_for_date(conn, data.date, fallback=data.tc_blue) or data.tc_blue` ; `amount_usd = data.amount / _rate` | fuente (escribe) |
| 11 | `backend/main.py:10078` | `POST /api/brokers/reconcile-cash` | ajusta el cash al real del broker y **registra la diferencia como depósito/retiro** en el mes MÁS VIEJO del broker | `diff = round(data.target_cash - current_cash, 6)` ; `amount_usd = magnitude / data.tc_blue if currency == 'ARS' else magnitude` | fuente (escribe) |
| 12 | `backend/main.py:10216` | `_revert_cash_flow` | deshace un cash flow restando de la MISMA columna | `_update_monthly_flow(conn, uid, broker_name, _fy, _fm, direction, -amount_usd, is_manual=True)` | fuente (escribe) |
| 13 | `backend/main.py:11981` / `:12013` | `POST/PUT /api/monthly` | el form de /mensual escribe `deposits`/`withdrawals` a mano | `man_dep, man_wit = _derive_manual_flows(conn, uid, e.broker, e.year, e.month, e.deposits, e.withdrawals)` | fuente (escribe) |
| 14 | `backend/main.py:11433` | `_rollover_to_current_month` | crea las filas de meses vacíos arrastrando `capital_final` | `clean_cap_final = cap_inicio_last + deposits_last - withdrawals_last + pnl_realized_last` | fuente (escribe) |
| 15 | `backend/main.py:11038` | `POST /api/monthly/sync-unrealized` | recalcula `capital_final` del mes vivo con la fórmula completa | `new_cap_final = round((current['capital_inicio'] or 0) + (current['deposits'] or 0) - (current['withdrawals'] or 0) + (current['pnl_realized'] or 0) + pnl, 4)` | fuente (escribe) |
| 16 | `backend/importing/persister.py:1005` | `_apply_cash_flow` | aplica DEPOSIT/WITHDRAW/FEE/TAX de un import: cash + monthly flow | `amount_usd = float(tx.gross_amount_usd)` si está estampado, si no `(amount / tc_blue) if currency == "ARS" else amount` (`:1063-1066`) | fuente (escribe) |
| 17 | `backend/importing/persister.py:1108` | `_persist_fx` | conversión ARS↔USD importada: **saca la pata ARS al blue y mete la pata USD a valor face** | `_ars_as_usd = (ars_amount / tc_blue) if tc_blue else 0.0` ; luego `withdraw(_ars_as_usd)` + `deposit(usd_amount)` (`:1139-1143`) | fuente (escribe) |
| 18 | `backend/importing/persister.py:1442` | revert de DEPOSIT | resta de `deposits` (no suma a `withdrawals`) | `helpers._update_monthly_flow(conn, uid, tx["broker"], y, m, "deposit", -amount_usd)` (`:1481`) | fuente (escribe) |
| 19 | `backend/importing/persister.py:1512` | revert de WITHDRAW/FEE/IMPUESTO | resta de `withdrawals` | `_update_monthly_flow(… "withdraw", -amount_usd)` (`:1526`) | fuente (escribe) |
| 20 | `backend/importing/persister.py:1230` | `_backfill_snapshots_from_monthly` | fabrica snapshots de fin de mes desde la cadena contable | `cum_dep += r["deposits"] or 0` ; `net_dep = cum_dep - cum_wd` (**sin baseline**) | fuente (escribe snapshots) |
| 21 | `backend/importing/seed.py:260` | `build_seed_txs` | estado inicial declarado en el wizard → 1 DEPOSIT por (broker, moneda) | `total = user_cash + covered_cost` ; `op_type = OP_DEPOSIT if total > 0 else OP_WITHDRAW` | fuente |
| 22 | `backend/importing/tenencia.py:602` | `build_tenencia_seed_txs` | apertura desde una foto: DEPÓSITO sintético que financia las compras | `total = round(sum(gap * h.price_per1 for h, gap in reconcile.to_seed), 4)` | fuente |
| 23 | `backend/importing/tenencia.py:670` | `build_cash_trueup_txs` | ajusta el efectivo al de la foto con DEPOSIT/WITHDRAW sintético | `diff = round(target - cur, 2)` ; `OP_DEPOSIT if diff > 0 else OP_WITHDRAW` | fuente |
| 24 | `backend/importing/normalizer.py:184` y `:298-310` | mapeo de tipos | decide qué fila cruda se vuelve DEPOSIT/WITHDRAW (por vocabulario y por signo del monto) | `(("INGRESO", "DEPOSIT", "APORTE", "ACREDIT", "RECIB", "FUNDING", "TOPUP", "TOP_UP", "MONEYLINK_DEP"), OP_DEPOSIT)` | fuente |
| 25 | `backend/main.py:15508` | `_recompute_snapshots_netdep_for_user` | re-estampa `snapshots.net_deposited` de todos los snapshots del user (corre en cada arranque) | `new_net = float(_nuevo_por_fila.get(snap["id"], 0.0) or 0)` (viene de `twr._aportado_por_punto`) | fuente (escribe) |
| 26 | `backend/twr.py:937` | `netdep_canonico` | `date → aportado`, recalculado AHORA desde `monthly_entries` (no lee la estampa) | `cum += float(r["deposits"] or 0) - float(r["withdrawals"] or 0)` ; `acum.append((ym, baseline + cum))` | fuente |
| 27 | `backend/twr.py:1014` | `_aportado_por_punto` | mezcla el canónico (bordes de mes) con la estampa (resolución diaria), con clamp | `v = c_m - (float(rn["net_deposited"] or 0) - float(r["net_deposited"] or 0))` ; `return max(lo, min(hi, v))` | fuente |
| 28 | `backend/twr.py:731` | `_flujo` | aportes netos entre dos fechas, delegando en la SSoT | `compute_net_deposited_db(conn, uid, as_of_date=hasta) - compute_net_deposited_db(conn, uid, as_of_date=desde)` | consumidor de (1) |
| 29 | `backend/twr.py:666` | `_leg_en_moneda` | convierte a pesos: **el flujo se convierte, el stock no** | `flow = p1["net_deposited"] - p0["net_deposited"]` ; `return v0*f0, v1*f1, flow * ((f0*f1) ** 0.5)` | consumidor |
| 30 | `backend/snapshots_job.py:766` | `take_snapshot_for_user` | el cron estampa `net_deposited` del día | `net_deposited = compute_net_deposited(monthly)` | fuente (escribe) |
| 31 | `backend/main.py:5008` / `:5028` | `SnapshotIn` + `POST /api/snapshots` | el navegador estampa su propio `net_deposited` | `net_deposited: float = Field(0, ge=0)` | fuente (escribe) |
| 32 | `backend/main.py:32635` | `_portfolio_snapshot_summary` | `cum_deposited` del reporte — **suma el PAR padre + "· USD", SIN baseline** | `cum_deposited = sum(compute_net_deposited_db(conn, uid, broker_filter=b, include_baseline=False) for b in brokers_del_filtro(conn, uid, broker_filter))` | consumidor |
| 33 | `backend/main.py:32873` | `_snapshot_delta` | Δ1d/7d/30d ajustado por flujos | `delta_usd = (latest_value - cur_netdep) - (prev_v - prev_netdep)` | consumidor |
| 34 | `backend/main.py:32949` | `_ytd_delta` | YTD Modified Dietz descontando flujos del año | `SELECT COALESCE(SUM(deposits - withdrawals), 0) AS net FROM monthly_entries WHERE user_id=? AND broker=? AND year=?` ; `pnl = latest_value - start - net_flows` ; `avg = start + 0.5 * net_flows` | consumidor |
| 35 | `backend/reporting/builder.py:716` | `fetch_cum_deposits_until` | denominador de "% sobre aportado", **sin baseline**, sumando el par | `sum(compute_net_deposited_db(conn, uid, as_of_date=end_date, broker_filter=b, include_baseline=False) for b in brokers_del_filtro(...))` | consumidor de (1) |
| 36 | `backend/reporting/builder.py:661` | `fetch_monthly_entry` | flujos del mes con el par colapsado (los flujos se SUMAN; los stocks salen de `capital_vigente`) | `COALESCE(SUM(deposits), 0) AS deposits, COALESCE(SUM(withdrawals), 0) AS withdrawals` | consumidor |
| 37 | `backend/reporting/builder.py:1451` | `compute_metrics_for_period` (rama día/semana) | deriva los flujos sub-mensuales de la diferencia de `net_deposited` entre snapshots | `deposits = max(0.0, end_netdep - start_netdep)` ; `withdrawals = max(0.0, start_netdep - end_netdep)` | consumidor |
| 38 | `backend/reporting/builder.py:1467` | idem | delta del período | `flows = deposits - withdrawals` ; `delta_usd = end_value - start_value - flows` | consumidor |
| 39 | `backend/reporting/builder.py:783` | `_modified_dietz_pct` | % del período | `avg = start_value + 0.5 * flows` ; `pnl = end_value - start_value - flows` | consumidor |
| 40 | `backend/reporting/builder.py:443` | `_basis_is_incomparable` | corta el número cuando el período está dominado por dinero nuevo | `base_total = start_value + max(0.0, deposits - withdrawals)` | consumidor |
| 41 | `backend/reporting/builder.py:623` | `_pct_en_pesos` | el mismo leg en pesos | `p0, {"fx": f1, "net_deposited": float(deposits or 0)}, v0, v1` | consumidor |
| 42 | `backend/main.py:12431` (builder de `/api/movements`) | `_movements_rows` | **recalcula el residual manual por su cuenta** para no doble-contar los importados | `deposits_manual = max(0.0, deposits_total - imp_dep)` (`:12711`) | consumidor |
| 43 | `backend/main.py:12955` | `_delete_one_movement`, rama `me-…` | borra el depósito/retiro manual del mes poniendo `manual_* = 0` | `UPDATE monthly_entries SET {col}=0, {nat_col}=0 WHERE id=? AND user_id=?` | fuente (escribe) |
| 44 | `backend/main.py:14247-14265` | `delete_position` | revierte el autodepósito que financió la compra | `_update_monthly_flow(conn, uid, broker, ay, am, 'deposit', -float(autodep["usd"]), is_manual=True, native_amount=-autodep_native)` | fuente (escribe) |
| 45 | `backend/main.py:36657-36674` | operación grupal del asesor | mismo autodepósito, per-cliente | `_update_monthly_flow(conn, cid, pos["broker"], _ay, _am, …)` | fuente (escribe) |
| 46 | `backend/main.py:37026-37051` | `flows_month` del libro del asesor | captación del mes = Δ`net_deposited` entre snapshots | `net_dep = round(dep_now - dep_then, 2)` ; `"market_effect_usd": round((v_now - v_then) - net_dep, 2)` | consumidor |
| 47 | `backend/main.py:38004-38011` | delta 7d por cliente | idem por cliente | `flows = (float(snap["net_deposited"] or 0) - float(then["net_deposited"] or 0))` ; `"market_7d_usd": round(d - flows, 2)` | consumidor |
| 48 | `backend/main.py:35695-35700` | informe firmado del asesor | flujos y efecto mercado del período | `flows_usd = round(nd1 - nd0, 2)` ; `market_usd = round((v1 - v0) - flows_usd, 2)` ; `dietz_base = v0 + flows_usd / 2.0` | consumidor |
| 49 | `backend/importing/fx_migrate.py:88-92` | panel del migrador FX | **replica a mano** la fórmula del Dashboard para mostrar el antes/después | `aportado = baseline + float(mon["dep"] or 0) - float(mon["ret"] or 0)` | consumidor (copia) |
| 50 | `backend/main.py:15293` | `_cagr_from_monthly_rows` | CAGR fallback sin snapshots | `net = (r["deposits"] or 0) - (r["withdrawals"] or 0)` ; `ret_m = max(-0.95, min(5.0, (cf - ci - net) / ci))` | consumidor |
| 51 | `backend/wrapped.py:50-59` | `_twr_for_period` | TWR del Wrapped anual | `net = (r.get('deposits') or 0) - (r.get('withdrawals') or 0)` ; `ret = (cf - ci - net) / ci` | consumidor |
| 52 | `backend/ai/builders/insights.py:235-256` | packet IA de Insights | TWR mensual para el modelo | `ret = ((cf - dep + wd) / denom) - 1` | consumidor |
| 53 | `backend/ai/builders/dashboard_evolution.py:113-116` | packet IA del Dashboard | mejor/peor mes | `net = (m.get("deposits") or 0) - (m.get("withdrawals") or 0)` ; `ret = (cf - ci - net) / ci` | consumidor |
| 54 | `backend/ai/builders/monthly.py:183` / `insights_evolution.py:55` / `reports.py:71` / `metrics_pro_card.py:98` | packets IA | pasan `deposits`/`withdrawals` crudos al modelo | `"deposits": round(float(m.get("deposits") or 0), 2)` | consumidor |
| 55 | `backend/reporting/detectors.py:114` | `detect_deposits_vs_gains` | insight "creciste por aportes, no por mercado" | `deps = report.metrics.deposits` | consumidor |
| 56 | `backend/main.py:11848-11930` | `/api/admin/diagnose-…` (cadena costo vs mercado) | reconcilia mes a mes | `net = (f["deposits"] or 0) - (f["withdrawals"] or 0)` ; `dietz(ci, cf, net)` | consumidor (diagnóstico) |
| 57 | `backend/main.py:18196-18320` | diagnóstico de flujos | triangula `deposits` global vs imports vs manual | `gap = round(dep_glob - suma_imports - manual_total, 2)` → veredicto `MANUAL` / `IMPORT` / `DRIFT_SIN_FUENTE` / `MIXTO` | consumidor (diagnóstico) |
| 58 | `backend/sim_import.py:79` | simulador de import | mide el Δ aportado de una migración | `SELECT COALESCE(SUM(deposits),0) dep, COALESCE(SUM(withdrawals),0) wd, …` | consumidor |
| — | **FRONTEND** | | | | |
| 59 | `frontend/src/utils/insightsModel.js:41` | `netCapitalContributed` | fórmula única declarada del front | `const baseline = sorted[0].capital_inicio_costo ?? sorted[0].capital_inicio ?? 0` ; `const flows = sorted.reduce((s, m) => s + (m.deposits \|\| 0) - (m.withdrawals \|\| 0), 0)` ; `return baseline + flows` | fuente (front) |
| 60 | `frontend/src/pages/Dashboard.jsx:222-232` | `netDepositedBase` / `netDeposited` | **reimplementa (59) inline** y le SUMA el capital de los plazos fijos | `const baseline = globals[0].capital_inicio \|\| 0` ; `return baseline + flows` ; luego `const netDeposited = netDepositedBase + pf.investedUsd` | fuente (front) |
| 61 | `frontend/src/pages/HomeMobile.jsx:135-142` | `aportado` | **tercera copia inline**, SIN plazos fijos | `const baseline = sorted[0]?.capital_inicio \|\| 0` ; `return baseline + flows` | fuente (front) |
| 62 | `frontend/src/utils/evolution.js:254` | `netDepositedOf` | baseline de Total Return de un snapshot; ausente ≠ negativo | `const nd = s?.net_deposited` ; `return (nd != null && nd !== 0) ? nd : (s?.total_invested \|\| 0)` | consumidor |
| 63 | `frontend/src/utils/evolution.js:194` | `buildPortfolioValueSeries` | **cuarta copia de la misma regla**, en el mismo archivo | `netDeposited: +(s.net_deposited \|\| s.total_invested \|\| 0)` | consumidor |
| 64 | `frontend/src/utils/evolution.js:305` | `computeReturnDelta` | Δ(Total Return) hoy vs referencia | `const usd = (todayValue - todayNetDep) - ((prev.total_value \|\| 0) - netDepositedOf(prev))` (`:363`) | consumidor |
| 65 | `frontend/src/utils/evolution.js:508-540` | `buildEvolutionFromSnapshots` | TWRR chain-linked entre snapshots | `const flows = netDep - prevNetDep` ; `const pnl = (value - prevValueUsd) - flows` ; `const avgCap = isBigWithdraw ? prevValueUsd : (prevValueUsd + 0.5 * flows)` | consumidor |
| 66 | `frontend/src/hooks/useMonthlyData.js:344-380` | armado de meses | delta y % del mes | `const flows = deposits - withdrawals` ; `const avgCapital = (startUsd \|\| 0) + 0.5 * flows` ; `deltaUsd = endUsd - startUsd - flows` | consumidor |
| 67 | `frontend/src/hooks/useMonthlyData.js:526-529` | `cumNetDepByYear` | aportado acumulado al cierre de cada año, **sin baseline** | `cumNetDep += (m.deposits \|\| 0) - (m.withdrawals \|\| 0)` | consumidor |
| 68 | `frontend/src/hooks/useMonthlyData.js:637` | `flowsYear` | flujos netos del año | `sorted.reduce((s, m) => s + (m.deposits \|\| 0) - (m.withdrawals \|\| 0), 0)` | consumidor |
| 69 | `frontend/src/components/MonthlySummary.jsx:30-31` | `calcFinal` | el "Capital Final" que el form propone | `+(f.capital_inicio + f.deposits - f.withdrawals + f.pnl_realized + f.pnl_unrealized).toFixed(2)` | consumidor |
| 70 | `frontend/src/components/MonthlySummary.jsx:366-379` | `totals` | totales de la tabla, convertidos mes a mes | `deposits: acc.deposits + conv(m.deposits)` | consumidor |
| 71 | `frontend/src/pages/Operations.jsx:1358-1408` | `computeMovementKpis` | KPI "Aportado neto" de Movimientos | `const neto = dep - wit` (sobre las filas de `/api/movements`, no sobre `monthly_entries`) | consumidor |
| 72 | `frontend/src/pages/Insights.jsx:550` | hero de Insights | capital aportado + resultado total | `const capitalContributed = netCapitalContributed(globalMonthly)` ; `const totalResult = totalPortfolio - capitalContributed` | consumidor |
| 73 | `frontend/src/pages/Insights.jsx:644-665` | serie MWR | acumulado con baseline y peak | `let cumNetDeposits = baseline` ; `cumNetDeposits += net` ; `safeDenom = (netDep, peakDep) => netDep >= peakDep * 0.6 && netDep > 1000 ? netDep : peakDep` | consumidor |
| 74 | `frontend/src/pages/Insights.jsx:834-842` | denominador del `realized %` del chart | **arranca `cumNet` en 0 pero `peakNet` en el baseline** | `let cumNet = 0, peakNet = globalMonthly[0]?.capital_inicio \|\| 0` | consumidor |
| 75 | `frontend/src/pages/Insights.jsx:772-786` | `arsMonthly` | agrega los flujos de los brokers ARS aparte | `byMk[k].deposits += m.deposits \|\| 0` | consumidor |
| 76 | `frontend/src/pages/Insights.jsx:1558-1562` | benchmarks ARS-nativos | flujos convertidos al blue de SU mes | `netFlowsPesos += ((m.deposits \|\| 0) - (m.withdrawals \|\| 0)) * fx` | consumidor |
| 77 | `frontend/src/pages/Insights.jsx:1818-1830` | insight "disciplina de aportes" | aportes vs P&L | `const netDeposits = totalDeposits - totalWithdrawals` ; `s + ((m.capital_final\|\|0) - (m.capital_inicio\|\|0) - net)` | consumidor |
| 78 | `frontend/src/utils/benchmarkSim.js:85-96`, `:157-168`, `:269-280`, `:335-356` | simuladores S&P / dólar / Merval / plazo fijo | portafolio paralelo con los MISMOS flujos | `let units = (sorted[0].capital_inicio \|\| 0) / firstPrice` ; `const net = (m.deposits \|\| 0) - (m.withdrawals \|\| 0)` | consumidor |
| 79 | `frontend/src/utils/insightsMetrics.js:58-64` | `computeMonthlyReturns` | vol / Sharpe / Sortino | `const denom = start + netFlow * 0.5` ; `const gain = end - start - netFlow` | consumidor |
| 80 | `frontend/src/components/ai/AICoachDrawer.jsx:178-179` | `buildSummary` | lo que ve el Coach IA | `const sumDeposits = (monthly \|\| []).reduce((acc, m) => acc + (m.deposits \|\| 0), 0)` | consumidor |
| 81 | `frontend/src/utils/demo.js:588-595` | `_demoPortfolioSnapshot` | quinta copia (demo) | `const rawCum = baseline + deposits` ; `const cumDeposited = Math.min(rawCum, Math.round(MONTHLY_LAST_VALUATION * 0.85))` | consumidor (demo) |

---

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `frontend/src/pages/Dashboard.jsx:872-885` | `KpiCell` del hero | **"Capital aportado"** · sub "depósitos netos" · tooltip `= depósitos − retiros (+ saldo inicial si ya tenías plata al empezar)` |
| `frontend/src/pages/Dashboard.jsx:834` | chip del hero | **"Aportado"** |
| `frontend/src/pages/Dashboard.jsx:857` | tooltip del resultado total | `= valor actual − capital aportado neto` |
| `frontend/src/pages/Dashboard.jsx:1196` | leyenda del gráfico | **"Capital aportado"** (línea punteada) |
| `frontend/src/pages/HomeMobile.jsx:418-419` | KPI mobile | **"Capital aportado"** |
| `frontend/src/pages/Insights.jsx:550` | hero de Insights | capital aportado / "Resultado total" |
| `frontend/src/pages/Reports.jsx:591-607` | KPI del tab Año | **"Capital aportado"** · sub "Retorno sobre aportes: ±X%" |
| `frontend/src/pages/Reports.jsx:709-717` | KPI de período | **"Flujos netos"** · sub "Aportes US$ …" |
| `frontend/src/components/reports/MonthCard.jsx:223-224` | tarjeta de mes | **"Depósitos"** / **"Retiros"** |
| `frontend/src/components/reports/MonthCard.jsx:235-236` | tarjeta de mes | **"Sobre aportado"** (`delta_pct_over_contrib`) |
| `frontend/src/components/MonthlySummary.jsx:586-587`, `:640-648`, `:725-726` | tabla /mensual + form | **"Depósitos"**, **"Retiros"**, fila TOTAL |
| `frontend/src/pages/Operations.jsx:1401` | KPI de Movimientos (vista "Todos") | **"Aportado neto"** · sub "N depósitos · N retiros" |
| `frontend/src/pages/Operations.jsx:1362-1379` | KPI filtrando por tipo | **"Total depositado"** / **"Total retirado"** (bruto histórico) + "Promedio" |
| `frontend/src/pages/Operations.jsx:923`, `:931` | copy de ayuda | "No suma al capital aportado — esa plata no la pusiste, la ganaste" |
| `frontend/src/pages/AdvisorDashboard.jsx:220` | libro del asesor | **"Aportes − retiros (este mes)"** |
| `frontend/src/pages/AdvisorDashboard.jsx:572` | gráfico del libro | **"Aportado neto"** |
| `frontend/src/pages/ReportPublic.jsx:134` | informe firmado público | **"Aportes netos"** |
| `frontend/src/utils/shareCard.js:301-318` | share card | **"Capital inicial"**, **"Capital final"**, **"Aportes netos"/"Retiros netos"** |
| `frontend/src/pages/Admin.jsx:2220`, `:2461`, `:2484` | panel del migrador FX | **"Aportado neto US$ …"**, columna **"Δ Aportado"** |
| `frontend/src/pages/guia/InsightsYReportes.jsx:173-179` | guía | "Todo arranca con el capital aportado…" |
| `frontend/src/components/FuturosGroup.jsx:485` | copy | "No suma al capital aportado" |
| `frontend/src/utils/insights.js:16-51` | insight del Dashboard | "Tu cartera rinde X% sobre el capital aportado" |
| `backend/main.py:13674` (`/api/export/monthly.csv`) | export al contador | columna **"Depósitos"** / **"Retiros"** |
| `backend/main.py:13570-13595` (`/api/export/transactions.csv`) | export al contador | filas **"DEPÓSITO"** / **"RETIRO"** con nota "Total depósitos YYYY-MM (fecha aproximada al 15)" |
| `backend/reporting/builder.py:1953-1956`, `:2010-2015` | narrativa del reporte | "Aportaste US$ X en el período." / "Retiraste US$ X del portfolio." |
| `backend/advisor_brief.py:357-362` | brief diario del asesor | métrica de captación del mes |

---

### Dónde se persiste

**[V] Tablas y columnas:**

| tabla | columna | qué guarda | quién escribe |
|---|---|---|---|
| `monthly_entries` | `deposits` (REAL) | depósitos del mes **en USD**, imports + manual | `_update_monthly_flow`, `_recalc_pnl_realized_from_ops`, POST/PUT `/api/monthly` |
| `monthly_entries` | `withdrawals` (REAL) | ídem retiros | ídem |
| `monthly_entries` | `manual_deposits` / `manual_withdrawals` | **solo** la porción manual, en USD — es la que sobrevive al recalc | `_update_monthly_flow(is_manual=True)`, `_backfill_manual_flows` |
| `monthly_entries` | `manual_deposits_native` / `manual_withdrawals_native` | el mismo flujo en la moneda NATIVA del broker, para revertir exacto | `_update_monthly_flow(native_amount=…)` |
| `monthly_entries` | `capital_inicio` | stock de apertura del mes; el de la PRIMERA fila es el **baseline** del aportado | `_repair_monthly_chain`, `_rollover_to_current_month` |
| `monthly_entries` | `capital_final` | `ci + dep − wit + pnl_realized (+ unrealized si es el mes en curso)` | `_repair_monthly_chain`, `sync-unrealized`, `_update_monthly_flow` |
| `snapshots` | `net_deposited` (NOT NULL DEFAULT 0) | el aportado **estampado** al momento de escribir la foto | cron (`snapshots_job.py:766`), navegador (`POST /api/snapshots`), `_recompute_snapshots_netdep_for_user`, `_backfill_snapshots_from_monthly` |
| `snapshots` | `total_invested` | cost basis legacy; se usa como fallback cuando `net_deposited == 0` | ídem |
| `twr_periods` | `flow_usd` | el flujo del tramo sellado | motor TWR |
| `import_normalized_tx` | `operation_type` = `DEPOSIT`/`WITHDRAW`, `gross_amount`, `gross_amount_usd`, `currency`, `excluded_at` | la fila fuente de un flujo importado | pipeline de import |

**[V] Definición de esquema:** `backend/schema_pg.sql:1191-1209` (monthly_entries), `:1525-1539` (snapshots), `:1644-1661` (twr_periods). Migraciones SQLite en `backend/main.py:1092-1112`.

**[V] Un flujo MANUAL no tiene fila fuente en ninguna tabla.** Solo el agregado `manual_deposits`. Lo declara el propio código como gap de auditoría en `backend/main.py:18368`: *"los flujos MANUALES no tienen fila fuente en ninguna tabla: sólo el agregado manual_deposits (el único rastro parcial es positions.undo_meta_json.autodep)"*. Por eso `/api/movements` muestra esos depósitos con fecha **día 15 del mes** inventada (`backend/main.py:12712`: `approx_date = f"{y:04d}-{m:02d}-15"`).

**[V] Se calcula al vuelo, no se persiste:** el número "Capital aportado" que ve el usuario. Ningún lugar guarda un campo `capital_aportado` — de hecho el identificador `capital_aportado` **solo existe en nombres de tests** (`backend/tests/test_cash_autodeposit.py:194`, `test_futuros_manual.py:98`, `test_importer.py:3049`, `test_reportes_broker_par.py:285`). Lo más cercano a una materialización es `snapshots.net_deposited`.

---

### ⚠️ Implementaciones divergentes

**No hay una sola implementación. Hay al menos seis definiciones distintas de "capital aportado" conviviendo, y la diferencia entre ellas es visible en pantalla.**

#### D1 — Con baseline vs sin baseline (afecta el KPI de Reportes contra el de Dashboard)

| variante | fórmula | quién la usa |
|---|---|---|
| **CON baseline** | `capital_inicio[primera fila global] + Σ(dep − wit)` | `compute_net_deposited_db(include_baseline=True)` → cron de snapshots, `_snapshot_delta` (`main.py:32760-32762`), `twr.netdep_canonico`, Dashboard, HomeMobile, Insights |
| **SIN baseline** | `Σ(dep − wit)` | `fetch_cum_deposits_until` (`builder.py:735-742`), `_portfolio_snapshot_summary.cum_deposited` (`main.py:32700-32703`), `useMonthlyData.cumNetDepByYear` (`useMonthlyData.js:526-529`), `_backfill_snapshots_from_monthly` (`persister.py:1250-1253`) |

**[V] Es deliberado y está documentado** ("Mantenemos `include_baseline=False` para preservar la semántica histórica de este endpoint", `main.py:32690-32692`). **[I] Pero el efecto de usuario es que el KPI "Capital aportado" del tab Año de Reportes (`Reports.jsx:594`, lee `cum_deposited`) y el KPI "Capital aportado" del Dashboard (`Dashboard.jsx:872`) muestran, con el mismo nombre, dos números que difieren exactamente en el baseline** — para un usuario que importó historia con saldo inicial, esa diferencia es todo el capital previo. Y el sub-label de Reportes divide por ese denominador chico: `Retorno sobre aportes: (capitalNow − cum_deposited) / cum_deposited` (`Reports.jsx:602`), o sea el mismo error de denominador que el comentario de `insightsModel.js:33-38` dice haber arreglado.

#### D2 — El Dashboard suma los plazos fijos; el mobile y todo el backend, no

- `frontend/src/pages/Dashboard.jsx:232`: `const netDeposited = netDepositedBase + pf.investedUsd`
- `frontend/src/pages/HomeMobile.jsx:141`: `return baseline + flows` (sin PF)
- backend: crear un plazo fijo **debita cash y no registra ningún flujo** (`backend/main.py:9144`: `_adjust_broker_cash(conn, uid, p.source_broker, -float(p.capital))`, sin `_update_monthly_flow`). Si el PF se crea SIN `source_broker` la plata "viene de afuera de Rendi" (`main.py:9124-9125`) y nada la registra.

**[V] Resultado medible:** un usuario con plazos fijos ve un "Capital aportado" en el Dashboard y **otro más chico** en el Home mobile y en Reportes, con la diferencia exacta del capital de los PF.

#### D3 — El baseline del Dashboard puede venir contaminado con valor de mercado

`insightsModel.netCapitalContributed` usa `sorted[0].capital_inicio_costo ?? sorted[0].capital_inicio` (`insightsModel.js:49`) porque `applyMtmToMonthly` **reemplaza `capital_inicio` por el valor del snapshot** y deja el original en `capital_inicio_costo` (`insightsModel.js:653-657`). El Dashboard reimplementa la fórmula inline y usa `globals[0].capital_inicio || 0` **sin el fallback a `_costo`** (`Dashboard.jsx:227`).

**[V] Hoy no explota porque el Dashboard nunca llama a `applyMtmToMonthly`: lo importa (`Dashboard.jsx:43`) y no lo usa** — `grep -n "applyMtmToMonthly(" frontend/src/pages/Dashboard.jsx` no devuelve nada. **[I] Es un import muerto que deja armada la trampa: el día que alguien conecte el MtM al Dashboard, el "Capital aportado" del hero se infla en silencio con la ganancia latente — que es exactamente el bug que el comentario de `insightsModel.js:44-48` dice haber cerrado.**

#### D4 — Una conversión ARS→USD cambia el capital aportado si vino por import, y no lo cambia si la hiciste desde la app

| camino | escribe flujos | fórmula |
|---|---|---|
| **importada** (`_persist_fx`, `persister.py:1136-1143`) | SÍ: `withdraw(ars/blue)` en la pata ARS + `deposit(usd_amount)` en la pata USD, y las dos también en `'global'` | `_ars_as_usd = (ars_amount / tc_blue)` |
| **manual** (`POST /api/conversions`, `main.py:10870-11010`) | NO. Solo `_update_monthly_pnl_realized` en la rama `usd_to_ars` | — |

**[V]** El mismo evento económico mueve el aportado en un caso (por la brecha MEP-vs-blue: `usd_amount − ars/blue`) y no lo mueve en el otro.

**[V] Y hay algo peor: el efecto del import no sobrevive.** `_recalc_pnl_realized_from_ops` reescribe `deposits = imports_confirmados + manual`, y `_import_flows_for_period` solo mira `operation_type IN ('DEPOSIT','WITHDRAW')` (`main.py:604`) — las filas `FX_ARS_TO_USD` no entran, y el flujo se escribió con `is_manual=False` así que tampoco quedó en `manual_*`. O sea: **el ajuste de capital que hace `_persist_fx` se borra en el primer recalc** (y el recalc corre después de casi todo: revert de batch `persister.py:1677-1679`, borrado de broker `main.py:4495`, borrado de movimiento `main.py:12925`, backfills, etc.).

#### D5 — Cuatro escritores de `snapshots.net_deposited`, con tres convenciones

| escritor | fórmula | baseline | resolución |
|---|---|---|---|
| cron (`snapshots_job.py:766-767`) | `compute_net_deposited(monthly)` | SÍ | mensual, **sin corte por fecha** (suma TODO el historial aunque el snapshot sea de una fecha pasada) |
| navegador (`main.py:5075-5079`) | lo que mande el front (`netDepositedPositions`) | SÍ (Dashboard) | live |
| import (`persister.py:1250-1253`) | `cum_dep − cum_wd` acumulado hasta ese mes | **NO** | fin de mes |
| re-estampa de arranque (`main.py:15546-15551`) | `twr._aportado_por_punto` (canónico anclado por mes + estampa vieja para el día) | SÍ | diaria, con clamp |

**[V]** El propio código dice que restar dos estampas escritas en momentos distintos "no mide un flujo: mide cuánto cambió la contabilidad entre los dos momentos" (`backend/twr.py:938-948`), con un caso medido de −US$50.000 / −37,04% en un mes plano. `netdep_canonico` existe justamente para no leer la columna. **Pero `reporting/builder.py:1439-1451`, `main.py:37040-37048`, `main.py:38004-38011` y `frontend/src/utils/evolution.js:508` SÍ restan estampas.**

#### D6 — "Lo manual" se define de dos maneras y una decide qué se ve, la otra qué se borra

- **Lista** de movimientos (`main.py:12709-12714`): `deposits_manual = max(0.0, deposits_total - imp_dep)` — recalcula el residual contra los imports.
- **Borrado** de ese mismo movimiento (`main.py:13042-13046`): lee la columna `manual_deposits`, y si es `<= 0` devuelve **404 "No hay un movimiento manual para borrar en ese mes"**.

**[I]** Si las dos definiciones divergen (drift histórico, un import revertido que no restó exacto, la migración `_backfill_manual_flows` que corrió una sola vez), el usuario ve un depósito manual en Movimientos que **no puede borrar**, o borra un monto distinto al que la lista mostraba.

#### D7 — Movimientos resta los imports; el export al contador no

- `/api/movements` resta cuidadosamente el agregado de imports para no doble-contar (`main.py:12640-12662` explica el fix, `:12711` lo implementa).
- `/api/export/transactions.csv` **exporta las dos cosas enteras**: el paso 1 vuelca todas las filas `import_normalized_tx` incluyendo `DEPOSIT`/`WITHDRAW` humanizadas (`main.py:13445-13468` + `_humanize_tx_type` en `:13636-13637`), y el paso 4 vuelca `monthly_entries.deposits` completo (`main.py:13560-13595`), que ya contiene esos mismos imports.

**[V] El CSV "lo que mandás al contador" doble-cuenta todo depósito y retiro importado.**

#### D8 — El Coach IA recibe el aportado duplicado

`frontend/src/components/ai/AICoachDrawer.jsx:178`: `sumDeposits` reduce sobre **todas** las filas de `/api/monthly`, y `GET /api/monthly` devuelve `SELECT * FROM monthly_entries WHERE user_id=?` — o sea `'global'` **más** el desglose por broker (`main.py:11971-11974`).

**[V]** `deposits_lifetime` / `withdrawals_lifetime` que viajan al modelo son ~2× el valor real. El propio backend advierte de esto en la tool equivalente (`main.py:25377-25381`: *"NO sumes 'global' con las por-broker — duplicarías"*), pero el packet del drawer no aplica la regla.

#### D9 — Modified Dietz: cinco variantes del denominador

| sitio | denominador |
|---|---|
| `backend/reporting/builder.py:790` | `start_value + 0.5 * flows` |
| `backend/main.py:33026` (`_ytd_delta`) | `start + 0.5 * net_flows` |
| `backend/main.py:35700` (informe asesor) | `v0 + flows_usd / 2.0`, y **solo publica si `dietz_base > 100`** |
| `frontend/src/pages/Insights.jsx:672-675` | `isImportInitial ? net : (isBigWithdraw ? ci : ci + 0.5 * net)` — dos heurísticas extra |
| `frontend/src/utils/evolution.js:536` | `isBigWithdraw ? prevValueUsd : (prevValueUsd + 0.5 * flows)` |
| `frontend/src/hooks/useMonthlyData.js:378` | `(startUsd \|\| 0) + 0.5 * flows`, sin heurísticas |
| `frontend/src/utils/insightsMetrics.js:63-64` | `start + netFlow * 0.5`, con corte `denom <= 100 → skip` |

**[I]** La misma cartera, el mismo mes, medida por Insights (con heurística `isBigWithdraw`) y por /mensual (`useMonthlyData`, sin heurística) da porcentajes distintos.

#### D10 — El par padre ↔ "· USD": tres tratamientos

- `_portfolio_snapshot_summary` y `fetch_cum_deposits_until` **suman el par** llamando una vez por pata con `include_baseline=False` (`main.py:32700`, `builder.py:735`).
- `_ytd_delta` usa `broker = ?` a secas contra `monthly_entries` (`main.py:33019-33022`) → **no ve al sibling**. Hoy es inofensivo porque la función retorna `None` para `broker_filter != 'global'` (`main.py:32979`), y el código lo documenta como "dos trampas armadas" (`main.py:32964-32979`).
- `compute_net_deposited_db` **se niega explícitamente** a aceptar una lista de brokers con baseline prendido, porque "no hay respuesta correcta para un par" (`snapshots_job.py:348-362`).

#### D11 — Mobile vs desktop en la carga de un depósito

- `frontend/src/pages/Positions.jsx:1030-1038` manda `date` (hay un input de fecha en el modal, `:2875`).
- `frontend/src/pages/PositionsMobile.jsx:377-389` **no manda `date`** (el form mobile no tiene el campo: `PositionsMobile.jsx:211`, `:1674-1690`).

**[V]** Consecuencia: todo depósito/retiro cargado desde el celular se asienta en el **mes en curso**, aunque haya pasado antes; y se dolariza con el TC de hoy en vez del de su fecha (`main.py:10190-10197`). Desde desktop, no.

#### D12 — La regla "ausente ≠ negativo" está copiada en cuatro lugares

`frontend/src/utils/evolution.js:254` (`netDepositedOf`), `frontend/src/utils/evolution.js:194` (`buildPortfolioValueSeries`, con `||` en vez del helper), `backend/main.py:32932-32934` (`_snapshot_delta`) y el fallback de `twr._aportado_por_punto` (`twr.py:1047`). El propio comentario de `evolution.js:505-508` dice *"Dos copias de la misma regla en un archivo es el defecto de fondo de este proyecto, así que ahora hay UNA sola y es la de arriba"* — pero `:194` sigue teniendo la suya.

---

### Zonas grises

1. **[V] `SnapshotIn.net_deposited: float = Field(0, ge=0)` (`backend/main.py:5001`) rechaza el aportado negativo.** El mismo repo mide que *"4.744 filas (11,7%) en 192 usuarios tienen `net_deposited < 0`"* (`frontend/src/utils/evolution.js:261-263`), y el cron los escribe sin problema. Pero el `POST /api/snapshots` del navegador manda `netDepositedPositions` (`Dashboard.jsx:478`), que puede ser negativo → **422**. Y el `catch` del Dashboard marca el día como hecho igual (`Dashboard.jsx:490`: `if (e?.status >= 400) localStorage.setItem(key, today)`). **[I] Para esos usuarios el snapshot del navegador nunca se escribe, silenciosamente, todos los días.** `total_value` y `total_invested` tienen el mismo `ge=0`.

2. **[V] El cron estampa el aportado de TODA la historia en la foto del día, sin corte temporal.** `compute_net_deposited(monthly)` (`snapshots_job.py:388-402`) suma todas las filas `global`, y `take_snapshot_for_user` acepta un `target_date` arbitrario (`snapshots_job.py:648`). **[I]** Para el snapshot de hoy da lo mismo; para cualquier llamada con `target_date` pasado, la foto queda con un `net_deposited` del futuro.

3. **[V] El GC del recalc borra filas con `capital_inicio` distinto de cero.** `main.py:9613-9622` borra toda fila con `deposits = withdrawals = pnl_realized = pnl_unrealized = 0` **sin mirar `capital_inicio` ni `capital_final`**. `builder.capital_vigente` (`builder.py:167-211`) existe precisamente para sobrevivir a eso. **[I] Si la fila borrada era la PRIMERA del broker `'global'`, el baseline del aportado se muda a la siguiente fila que quede** — y el "Capital aportado" del Dashboard cambia sin que el usuario haya hecho nada.

4. **[V] El baseline se toma con `ORDER BY year, month LIMIT 1` sin `GROUP BY`.** En `compute_net_deposited_db` (`snapshots_job.py:381-384`) y en `_ytd_delta` (`main.py:32982-32988`). El propio código admite que con dos patas eso "elegiría una fila arbitraria" (`main.py:32971-32974`).

5. **[V] `_recalc_pnl_realized_from_ops` clampea el manual a ≥ 0** (`main.py:9582-9583`: `manual_dep = max(0.0, ...)`), pero `_update_monthly_flow` **sí** puede dejar `manual_deposits` negativo (los reverts pasan `amount` negativo, `main.py:9948-9952`). **[I]** Entre el revert y el siguiente recalc, `deposits` puede leerse con un manual negativo; después del recalc ese negativo se pierde (se clampea a 0) y `deposits` **sube**. No es idempotente respecto del orden de operaciones.

6. **[V] `_backfill_manual_flows` es una migración one-time que corre SOLO si la columna no existía** (`main.py:1093-1100`). En Postgres el schema ya declara `manual_deposits` (`schema_pg.sql:1204`), así que `init_db` para PG **no replica las 46 migraciones incrementales** (`main.py:698-705`). **[I] En Postgres el backfill nunca corrió**: `manual_deposits` arranca en 0 para toda fila preexistente, y el primer recalc sobrescribe `deposits = imports + 0`, borrando el aportado manual histórico. No pude verificar si hubo un script aparte para eso — **no encontrado**.

7. **[V] `_import_flows_for_period` no filtra fechas mal formadas y el agregado de `/api/movements` sí.** Compará `main.py:604-611` (sin guard) con `main.py:12688-12689` (`AND t.date LIKE '____-__-__%'`, con el comentario "una sola fecha rota tiraba abajo el agregado completo"). **[I]** En Postgres, una fecha rota puede hacer fallar el `strftime`/CAST del recalc; el mismo cuidado se aplicó en `_recalc` (`main.py:9459-9466`) pero no en `_import_flows_for_period`.

8. **[V] Un traspaso entre dos brokers del usuario infla el bruto.** El chat lo implementa como retiro + depósito (`main.py:24326-24332`) y el botón Cash igual. El neto queda en 0, pero "Total depositado" y "Total retirado" de Movimientos suben los dos (`Operations.jsx:1362-1379`). El código lo reconoce para el caso P2P (`Operations.jsx:1350-1353`) pero no para el traspaso.

9. **[V] Cerrar un plazo fijo acredita cash sin registrar nada en `monthly_entries`** (`main.py:9306`: `_adjust_broker_cash(conn, uid, data.broker, monto)`; el interés va a `operations`). **[I]** Si el PF se había creado sin `source_broker` (plata de afuera), al cerrarlo entra capital al broker con el aportado sin tocar → ganancia fantasma del tamaño del capital del PF en todas las pantallas que no sean el Dashboard.

10. **[V] `_derive_manual_flows` reinterpreta lo que el usuario tipeó.** Si el usuario escribe `deposits = 500` en el form /mensual y el mes ya tenía 400 de imports, el manual queda en 100 (`main.py:679-680`), y el recalc reconstruye 400 + 100 = 500. Pero si el import se revierte después, `deposits` cae a 100 — el número que el usuario escribió a mano desaparece parcialmente. **[I]** No encontré test que pinnee este caso.

11. **[V] `capital_inicio` y `capital_final` están validados `ge=0` en `MonthlyIn`** (`main.py:11423-11424`) pero `_update_monthly_flow` puede dejar `capital_final` negativo a propósito (`main.py:9995-10001`: "SIN clamp a 0… Un capital_final negativo de mes abierto es honesto"). El form no puede reproducir un estado que el motor sí produce.

12. **[V] `_snapshot_delta` cae a `total_invested` cuando `prev_netdep == 0`** (`main.py:32933-32934`), o sea mete costo dentro de un chip de variación. Es el comportamiento deliberado para filas pre-Phase 6, pero **[I]** también se dispara para un usuario legítimo cuyo aportado neto sea exactamente 0 (depositó y retiró lo mismo).

13. **[V] `Insights.jsx:838` arranca `cumNet = 0` mientras `peakNet` arranca en el baseline** (`Insights.jsx:835`). El denominador del "realized %" del gráfico es `safeDenom(cumNet, peakNet)` (`Insights.jsx:873`), que con `cumNet` sin baseline y `peakNet` con baseline devuelve casi siempre el peak. **[I]** Es una sexta variante del aportado, y no coincide con la del hero de la misma pantalla (`Insights.jsx:550`, que sí usa baseline + flujos).

14. **[V] `backend/flujos.py` (la clasificación aporte / retiro / traslado interno) no la importa nadie en producción.** `grep "import flujos"` solo encuentra `backend/tests/test_advisor_plan.py`. Es la única pieza del repo que distingue un **traslado entre brokers** de un **aporte real** — y hoy esa distinción no llega a ningún número que el usuario vea.

15. **[V] El TC con el que se dolarizó cada flujo no se guarda.** `main.py:18368` y `main.py:18370` lo listan como gaps: *"el TC aplicado NO se persiste"*. Consecuencia: `importing/fx_migrate.py` tiene que **estimarlo** dividiendo (`fx_migrate.py:284-290`) y admite que "con `currency != 'ARS'` el cociente es 1.0 POR CONSTRUCCIÓN, así que no distingue 'no había que dividir' de 'había que dividir y no se dividió'".

16. **[V] `manual_deposits_native` solo existe desde una migración posterior**; el borrado de un depósito manual viejo aproxima el reverso del cash con el blue de HOY (`main.py:13070-13074`). El comentario dice "el capital APORTADO queda EXACTO porque abajo ponemos el manual del mes en 0" — **[I] pero el CASH queda desfasado**, y ese cash es el que después alimenta la valuación.

17. **[V] Los tests que pinnean la definición son pocos y no cubren la divergencia.** Los canónicos son `backend/tests/test_snapshots_job.py:246-279` (`compute_net_deposited`: baseline + flujos, ignora filas no-`global`, ordena cronológicamente) y `frontend/src/utils/insightsModel.test.js:35-55` (mismo contrato del lado del front). `backend/tests/test_reportes_broker_par.py:285-294` pinnea que `cum_deposited` suma el par (200 = 120 + 80). `backend/tests/test_cash_autodeposit.py:194-202` pinnea que el autodepósito usa el MEP de la fecha. **No encontrado**: ningún test que compare el "Capital aportado" del Dashboard contra el `cum_deposited` de Reportes, ni ninguno que cubra los plazos fijos, ni la conversión manual vs importada.
