## P&L realizado

### Definición según el código

En Rendi «P&L realizado» **no es** lo que diría un libro de finanzas (resultado de posiciones cerradas). Lo que el código implementa es esto:

> **P&L realizado = todo lo que la app escribió en la columna `operations.pnl_usd`.**

Y `operations.pnl_usd` es un cajón de sastre en el que caen cinco cosas distintas, escritas por seis rutas distintas:

| Qué evento | `op_type` | Qué guarda `pnl_usd` |
|---|---|---|
| Venta FIFO (manual, import o rebuild) | `Venta` | resultado de la venta **en USD** (`precio_venta·qty − costo − comisión`, dividido por el TC de la venta si fue en pesos) |
| Cierre de futuro | `Futuros` | resultado del cierre, en USD |
| Dividendo / interés importado | `Dividendo`, `Interés` | **el monto cobrado entero** (no un resultado), convertido a USD con el blue del momento del import |
| Cupón / amortización de bono cargado a mano | `Cupón`, `Amortización` | **el monto cobrado entero, en la MONEDA DEL BROKER** (pesos si el broker es ARS) |
| Interés de plazo fijo | `Interés PF` | **el interés entero, en moneda nativa** |
| Conversión de moneda USD→ARS | `CONVERSION …`, `Conversión …` | resultado del FX de la pata dólar, en USD |
| Compra | `Compra` | 0 (o NULL) |

[V] `backend/realized_pnl.py:1-69` lo dice con todas las letras: *"La columna se llama `pnl_usd`, pero en las cobranzas de renta fija NO guarda USD: guarda el monto en la MONEDA DEL BROKER (`bond_cashflow` inserta `net_amount` tal cual)"*.

Encima de ese cajón conviven **dos definiciones de negocio distintas**, y las dos se llaman «P&L realizado» en la UI:

- **Universo A — «todo lo que entró»**: la suma de `pnl_usd` de *todas* las filas, sin filtrar por tipo. Es lo que vive en `monthly_entries.pnl_realized` y lo que muestran Dashboard, /mensual y Reportes. Incluye dividendos, intereses, cupones y el resultado de las conversiones de moneda. [V] `backend/main.py:9532-9541` (el recalc no filtra por `op_type`), [V] `backend/reporting/builder.py:842`.
- **Universo B — «trades cerrados»**: la suma de `pnl_usd` excluyendo `Compra`, `Dividendo`, `Interés`, `''` y todo lo que empieza con `CONVERSION`/`Conversión`. Es lo que consumen la IA, el libro del asesor y las stats de operatoria. [V] `backend/realized_pnl.py:74` y `:85-94`.

Sobre las dos capas se aplica **una tercera regla**, la normalización de moneda: `pnl_usd` se divide por `fx_to_usd` **solo** si `op_type ∈ ('Cupón','Amortización')` **y** `currency='ARS'` **y** `fx_to_usd > 0`. Las filas viejas sin FX sellado se dejan como están, a propósito. [V] `backend/realized_pnl.py:97-107` y el razonamiento en `:20-32`.

Dos consecuencias que el código asume explícitamente y conviene decir en voz alta:

1. **Una amortización de bono se cuenta como ganancia realizada por su monto entero** cuando se carga a mano, aunque sea devolución de capital. [V] `backend/main.py:10479-10484` inserta `net_amount` en `pnl_usd`. El mismo evento, cuando llega por importador, se guarda con `pnl_usd = 0`. [V] `backend/importing/persister.py:980`.
2. **Un cupón nunca puede ser negativo**, así que cada cobranza suma una "operación ganada" al win rate. El propio módulo lo lista como *Pendiente #1*. [V] `backend/realized_pnl.py:34-53`.

---

### Dónde se calcula

Primero el criterio canónico y sus cuatro entradas; después los escritores (los que producen el número); después los agregadores; después los lectores que tienen su propia versión de la regla.

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `backend/realized_pnl.py:97` | `realized_usd_sql(prefix)` | **CANÓNICO (SQL).** Expresión SELECT que devuelve el pnl de la fila en USD de verdad | `CASE WHEN {p}op_type IN ({quoted}) AND {p}currency = 'ARS' AND {p}fx_to_usd > 0 THEN {p}pnl_usd / {p}fx_to_usd ELSE {p}pnl_usd END` | criterio (lo usan 9 lectores) |
| 2 | `backend/realized_pnl.py:118` | `realized_usd(row)` | **CANÓNICO (Python).** Mismo criterio para filas ya cargadas en memoria | `return raw / fx if fx > 0 else raw` (con guardas `op_type ∈ _NATIVE_CCY_OPS`, `currency=='ARS'`) | criterio |
| 3 | `backend/realized_pnl.py:85` | `closed_filter_sql(prefix)` | **CANÓNICO.** El WHERE de "operaciones cerradas" (Universo B) | `{p}pnl_usd IS NOT NULL AND {p}op_type NOT IN ({quoted}) AND {p}op_type NOT LIKE 'CONVERSION%' AND {p}op_type NOT LIKE 'Conversión%'` | criterio |
| 4 | `backend/realized_pnl.py:110` | `is_closed_op(op_type)` | Equivalente Python de (3), sin el chequeo de NULL | `if t in _NOT_A_TRADE: return False` / `return not t.startswith(("CONVERSION", "Conversión"))` | criterio |
| 5 | `backend/realized_pnl.py:74` | `_NOT_A_TRADE` | La lista que define "no es un trade" | `('Compra', 'Dividendo', 'Interés', '')` | dato del criterio |
| 6 | `backend/realized_pnl.py:78` | `_NATIVE_CCY_OPS` | Los `op_type` cuyo `pnl_usd` está en moneda del broker | `('Cupón', 'Amortización')` | dato del criterio |
| 7 | `backend/importing/persister.py:793` | `_persist_sell` (rama ARS) | Venta importada en pesos: P&L nativo / TC de la fecha de venta | `pnl_usd = pnl_ars_chunk / tc_venta if tc_venta else 0` (con `pnl_ars_chunk = exit_price * take - (entry_invested or 0) - chunk_commission`) | **fuente** |
| 8 | `backend/importing/persister.py:799` | `_persist_sell` (rama USD) | Venta importada en dólares | `pnl_usd = (exit_price * take) - cost - chunk_commission` | **fuente** |
| 9 | `backend/importing/persister.py:787` | `_persist_sell` (`transfer_out`) | Retiro de activo (no venta): cierra el lote a costo | `pnl_usd = 0.0` | **fuente** |
| 10 | `backend/importing/persister.py:818-828` | `_persist_sell` | El INSERT: estampa `currency` + `fx_to_usd` (`fx_stamp = tc_venta if sell_currency == "ARS" else None`) | `INSERT INTO operations (… pnl_usd, pnl_pct, entry_date, commissions, currency, fx_to_usd) …` | **fuente** |
| 11 | `backend/main.py:11288` | `sell()` (venta manual, rama ARS) | Igual que (7) pero desde el form de Posiciones | `pnl_usd = pnl_ars_chunk / tc_venta` | **fuente** |
| 12 | `backend/main.py:11295` | `sell()` (rama USD) | | `pnl_usd = (data.exit_price * take) - cost - chunk_commission_native` | **fuente** |
| 13 | `backend/importing/rebuild.py:466` | replay FIFO (rama ARS) | Reconstrucción completa del historial | `pnl_usd = pnl_ars_chunk / tc_venta if tc_venta else 0` | **fuente** |
| 14 | `backend/importing/rebuild.py:470` | replay FIFO (rama USD) | | `pnl_usd = (exit_price * take) - cost - chunk_commission` | **fuente** |
| 15 | `backend/main.py:10479-10484` | `bond_cashflow` (`POST /api/bonds/cashflow`) | Cupón / amortización cargado a mano. **Guarda el monto NETO ENTERO en moneda nativa** | `net_amount = data.amount - commissions` → `INSERT INTO operations (… op_type, pnl_usd, …) VALUES (…, net_amount, …)` | **fuente** |
| 16 | `backend/importing/persister.py:979-980` | `_persist_dividend_or_interest` | Dividendo / interés importado. **Todo el cobro es "ganancia"**; la amortización detectada va en 0 | `amount_usd = (amount / tc_blue) if currency == "ARS" else amount` · `pnl_usd = 0.0 if is_amort else round(amount_usd, 2)` | **fuente** |
| 17 | `backend/main.py:9315-9322` | `cobrar_plazo_fijo` | Interés de plazo fijo. `op_type='Interés PF'`, monto en moneda nativa, `fx_to_usd = None` si es ARS | `fx = 1.0 if moneda in ("USD", "USDT") else None` → `INSERT … 'Interés PF', interes, moneda, fx …` | **fuente** |
| 18 | `backend/importing/persister.py:875` | `_persist_futures_pnl` | Cierre de futuro importado | `pnl = float(tx.gross_amount or 0)` | **fuente** |
| 19 | `backend/main.py:12335-12336` | `close_futuro` | Cierre de futuro manual | `bruto = (data.exit_price - float(pos["entry_price"])) * float(pos["quantity"]) * direccion` · `pnl = round(bruto - float(data.commissions or 0), 2)` | **fuente** |
| 20 | `backend/main.py:10943` | `convert_currency` (USD→ARS) | El FX realizado de la pata dólar entra a `operations` como `CONVERSION …` | `pnl_usd_realized = pnl_ars_realized / data.tc if data.tc > 0 else 0.0` (con `pnl_ars_realized = data.ars_amount - cost_basis_ars`) | **fuente** |
| 21 | `backend/importing/persister.py:1170` | `_persist_fx_conversion` | Idem, desde el importador | `op_pnl_usd = pnl_ars / tc if tc > 0 else 0.0` | **fuente** |
| 22 | `backend/main.py:13854-13859` | `create_operation` (`POST /api/operations`) | Operación manual: el usuario **tipea** el `pnl_usd` | `INSERT INTO operations (… pnl_usd, pnl_pct, commissions, currency, fx_to_usd, undo_meta_json) …` con `op.pnl_usd` crudo del body | **fuente** |
| 23 | `backend/main.py:9414-9600` | `_recalc_pnl_realized_from_ops` | **El agregador SSoT.** Reescribe `monthly_entries.pnl_realized` desde `operations`. **Sin filtro por `op_type`** | `SELECT COALESCE(SUM({realized_pnl.realized_usd_sql('o')}), 0) AS s FROM operations o WHERE o.user_id=? AND strftime('%Y', o.date)=? AND strftime('%m', o.date)=? {broker_filter_sql}` (`main.py:9532-9541`) | **fuente** (Universo A) |
| 24 | `backend/main.py:9875-9915` | `_update_monthly_pnl_realized` | Suma incremental al mes + recalcula `capital_final`. Lo llaman ~14 sitios | `new_pnl_realized = round((row['pnl_realized'] or 0) + pnl_amount, 4)` · `new_cap_final = round(capital_inicio + deposits - withdrawals + new_pnl_realized + pnl_unrealized, 4)` | **fuente** (cache, después lo pisa (23)) |
| 25 | `backend/reporting/builder.py:842` | `compute_metrics_for_period` | **El realizado de Reportes** (mes/semana/día/año). **Sin filtro por tipo** | `realized = sum(float(o.get("pnl_usd") or 0) for o in ops)` | **fuente** (Universo A) |
| 26 | `backend/reporting/builder.py:233-243` | `fetch_operations_in_range` | El embudo del módulo: normaliza `pnl_usd` en el SELECT y de ahí salen realized, win/loss, drivers y highlights | `SELECT id, date, broker, asset, op_type, quantity, entry_price, exit_price, {realized_usd_sql()} AS pnl_usd, pnl_pct FROM operations WHERE user_id = ? AND date >= ? AND date <= ?{br_sql}` | consumidor→fuente |
| 27 | `backend/reporting/builder.py:845-853` | `_is_trade` (local) | Copia a mano del filtro de trades, para win/loss y `trades_count` | `if t in ("Compra", "Dividendo", "Interés"): return False` / `if t.startswith("Conversión") or t.startswith("CONVERSION"): return False` | consumidor (Universo B, copia) |
| 28 | `backend/reporting/builder.py:1528-1531` | `compute_metrics_for_period` (día/semana per-broker) | Cuando no hay snapshots per-broker, **el delta ES el realizado** | `delta_usd = realized` · `unrealized = 0.0` — y en la rama global `unrealized = delta_usd - realized` | consumidor |
| 29 | `backend/main.py:25412-25425` | AI tool `get_realized_vs_unrealized` | El número que la IA le dice al usuario en el chat | `CLOSED_FILTER = realized_pnl.closed_filter_sql()` · `REALIZED = realized_pnl.realized_usd_sql()` · `SELECT COALESCE(SUM({REALIZED}),0) AS realized, COUNT(*) AS n FROM operations WHERE user_id=? AND {CLOSED_FILTER}` | consumidor (Universo B) |
| 30 | `backend/ai/builders/insights.py:285-323` | `insights.build` | `realized_pnl_usd` del packet de Análisis | `closed = [{**o, "pnl_usd": _realized_pnl.realized_usd(o)} for o in ops if o.get("pnl_usd") is not None and _realized_pnl.is_closed_op(o.get("op_type"))]` · `realized_pnl_usd = round(sum(float(o.get("pnl_usd") or 0) for o in closed), 2) if closed else None` | consumidor (Universo B) |
| 31 | `backend/ai/builders/insights_attribution.py:70-76` | `insights_attribution.build` | Atribución realized por ticker | `if not realized_pnl.is_closed_op(o["op_type"]): continue` · `realized_by_ticker[ticker] = realized_by_ticker.get(ticker, 0) + realized_pnl.realized_usd(o)` | consumidor (Universo B) |
| 32 | `backend/ai/builders/operations.py:50-54` | `operations.build` | P&L total, avg_win/avg_loss, payoff, expectancy de la pantalla Operaciones para la IA | `SELECT date, asset, broker, op_type, entry_price, exit_price, quantity, {realized_usd_sql()} AS pnl_usd, pnl_pct FROM operations WHERE user_id = ? AND pnl_usd IS NOT NULL` + `closed = [o for o in ops if _is_trade(o)]` | consumidor (Universo B) |
| 33 | `backend/ai/builders/operation_trade.py:54-58` y `:108-113` | `operation_trade.build` | Ficha de UNA operación + su rank en el año | `{realized_usd_sql()} AS pnl_usd` (dos veces, a propósito: el rank compara floats por igualdad exacta) + `AND {closed_filter_sql()}` | consumidor (Universo B) |
| 34 | `backend/ai/builders/position_lots.py:26-38` | `position_lots.build` | Lotes + ventas de un activo para la IA | `{realized_usd_sql()} AS pnl_usd` (dos queries) | consumidor |
| 35 | `backend/ai/builders/reports.py:97-99` | `reports.build` | `realized_pnl_year_usd` / `pnl_year_usd` | `pnl_year_usd = round(sum(float(e.get("pnl_realized") or 0) for e in entries), 2)` | consumidor (Universo A) |
| 36 | `backend/ai/builders/reports.py:99-107` | `reports.build` | `trades_year` con el filtro **copiado a mano** | `op_type NOT IN ('Compra', 'Dividendo', 'Interés', '') AND op_type NOT LIKE 'CONVERSION%' AND op_type NOT LIKE 'Conversión%'` | consumidor (copia de (3)) |
| 37 | `backend/main.py:37460-37473` | `_advisor_realized_raw` | Realized + renta por (cliente, activo) del libro del asesor | `SELECT user_id, broker, asset, op_type, {realized_pnl.realized_usd_sql()} AS pnl_usd, pnl_pct FROM operations WHERE user_id IN ({ph}) AND pnl_usd IS NOT NULL` · luego `if "DIVIDENDO" in tipo or "INTER" in tipo or "CUPON" in tipo: b["income_usd"] += pnl` else `b["realized_usd"] += pnl` | consumidor (universo propio) |
| 38 | `backend/main.py:37497-37504` | `_advisor_realized_raw` (costo) | Despeja el costo del par `(pnl_usd, pnl_pct)` | `cost = (pnl / (float(pct) / 100)) if (pct is not None and float(pct) != 0) else None` | consumidor |
| 39 | `backend/behavioral.py:1841-1844` | `build_behavioral_insights` | Normaliza UNA vez antes de los 12 detectores | `ops = [{**o, "pnl_usd": _realized_usd(o)} if o.get("pnl_usd") is not None else o for o in (operations or [])]` | consumidor |
| 40 | `backend/behavioral.py:63-71` | `_is_trade` (behavioral) | Copia del filtro | `if op_type in ("Compra", "Dividendo", "Interés", ""): return False` … `return op.get("pnl_usd") is not None` | consumidor (copia de (4)) |
| 41 | `backend/behavioral.py:890-902` | `detect_winrate_payoff` | win rate / avg_win / payoff / expectancy | `win_rate = len(winners) / total * 100` · `avg_win = sum(o["pnl_usd"] for o in winners) / len(winners)` · `expectancy = (win_rate/100)*avg_win - ((100-win_rate)/100)*avg_loss` | consumidor |
| 42 | `backend/wrapped.py:83-87` | `_operations_for_year` | Normaliza las ops del año antes de los slides del Wrapped | `out.append({**op, 'pnl_usd': realized_usd(op)} if op.get('pnl_usd') is not None else op)` | consumidor |
| 43 | `backend/wrapped.py:213-217` | `_slide_best_trade` | "Tu mejor trade del año". **Sin filtro de tipo** | `closed = [o for o in ops if (o.get('exit_price') or o.get('pnl_usd'))]` · `closed_sorted = sorted(closed, key=lambda o: o.get('pnl_usd') or 0, reverse=True)` | consumidor |
| 44 | `backend/reporting/timeline.py:60-76` | `_compute_user_historical_win_rate` | Win rate lifetime. Lee `pnl_usd` **crudo** (solo importa el signo) + filtro copiado a mano | `SELECT pnl_usd, op_type FROM operations WHERE user_id = ? AND pnl_usd IS NOT NULL` · `wins = sum(1 for r in trades if r["pnl_usd"] > 0)` | consumidor (copia) |
| 45 | `backend/main.py:13351-13362` | `export_operations_csv` | El CSV que el usuario le manda al contador. **Sin filtro de tipo** pese al docstring | `SELECT … {realized_pnl.realized_usd_sql()} AS pnl_usd … FROM operations WHERE user_id = ? ORDER BY date DESC` | consumidor |
| 46 | `backend/main.py:32764-32773` | KPI "última operación cerrada" de Reportes | Convierte, pero solo filtra `pnl_usd IS NOT NULL` | `SELECT date, broker, asset, op_type, {realized_pnl.realized_usd_sql()} AS pnl_usd FROM operations WHERE user_id = ? AND pnl_usd IS NOT NULL{br_clause} ORDER BY date DESC, id DESC LIMIT 1` | consumidor |
| 47 | `backend/main.py:12486-12487` | `_build_movements` | Normaliza el pnl de cada fila para la timeline de Movimientos | `pnl = (realized_pnl.realized_usd(d) if d.get("pnl_usd") is not None else 0)` | consumidor |
| 48 | `frontend/src/utils/assetPnl.js:76-84` | `opPnlUsd(op)` | **Espejo JS del criterio canónico** | `if (!NATIVE_CCY_OPS.includes(String(op.op_type||'').trim())) return raw` · `if (String(op.currency||'').toUpperCase() !== 'ARS') return raw` · `return raw / fx` | criterio (frontend) |
| 49 | `frontend/src/utils/assetPnl.js:200-211` | `computePnlByKey` | Separa renta de realizado por porción (clase / sector) | `const esRenta = tipo.includes('DIVIDENDO') \|\| tipo.includes('INTER') \|\| tipo.includes('CUPON')` → `b.income += pnl` else `b.realized += pnl` | consumidor |
| 50 | `frontend/src/utils/assetPnl.js:220-236` | `computePnlByKey` (costo) | Despeja el costo del par | `const cost = pnl / (pct / 100)` | consumidor |
| 51 | `frontend/src/utils/tradeStats.js:45-75` | `esTradeCerrado` / `computeTradeStats` | Win rate de la pantalla Operaciones. Espejo declarado de `builder.py` | `const TIPOS_NO_TRADE = ['Compra', 'Dividendo', 'Interés']` · `if (op.pnl_usd > 0) wins += 1; else if (op.pnl_usd < 0) losses += 1` | consumidor (copia) |
| 52 | `frontend/src/hooks/useMonthlyData.js:259-266` | `buildMonthlyReports` | Realizado por mes **derivado en el navegador** cuando no hay fila mensual | `const tradeOps = opsForBroker.filter(isTradeOp)` · `realizedByPeriod.set(period, prev + (op.pnl_usd || 0))` | consumidor (universo propio) |
| 53 | `frontend/src/hooks/useMonthlyData.js:48-54` | `isTradeOp` | Otra copia del filtro | `if (t === 'Dividendo' \|\| t === 'Interés' \|\| t === 'Compra') return false` … | consumidor (copia) |
| 54 | `frontend/src/pages/Insights.jsx:1881-1888` | `isTradeOp` (local) | Otra copia más, con `if (!t) return false` en vez de `''` en la lista | `if (t === 'Dividendo' \|\| t === 'Interés' \|\| t === 'Compra') return false` | consumidor (copia) |
| 55 | `frontend/src/pages/AssetDetail.jsx:169-175` | ficha de activo | "P&L realizado" del activo. **`pnl_usd` crudo, sin filtro de tipo** | `const closed = operations.filter(o => o.pnl_usd != null)` · `const realizedTotal = closed.reduce((s, o) => s + (o.pnl_usd || 0), 0)` | consumidor (universo propio) |
| 56 | `frontend/src/pages/Positions.jsx:512-556` | `bondCashflowsByKey` | "Ya cobraste" / "P&L con cupones" de la zona de renta fija. **Conversión propia, con fallback inventado** | `let fx = op.fx_to_usd; if (fx == null \|\| fx <= 0) { if (op.currency === 'ARS' \|\| (op.currency == null && amt > 1000)) fx = tcValuacion \|\| 1; else fx = 1.0 }` · `const amtUsd = amt / fx` · para amort `pnlContrib = amt - cbConsumed` | consumidor (universo propio) |
| 57 | `frontend/src/utils/insightsModel.js:271-278` | `computeAssetContribution` | Contribución por activo. **`pnl_usd` crudo** | `cur.realized += (op.pnl_usd || 0)` | consumidor |
| 58 | `frontend/src/utils/insightsModel.js:505-516` | `computeProfitFactor` | Profit factor | `if (o.pnl_usd > 0) grossWin += o.pnl_usd; else if (o.pnl_usd < 0) grossLoss += Math.abs(o.pnl_usd)` | consumidor |
| 59 | `frontend/src/utils/bookComposition.js:219-245` | `realizedToOps` | Convierte el agregado del asesor a "operaciones" sintéticas para reusar `computePnlByKey` | `const op = { ...base, op_type: 'Venta', pnl_usd: r.realized_usd \|\| 0 }` · `ops.push({ ...base, op_type: 'Dividendo', pnl_usd: r.income_usd })` | consumidor |
| 60 | `frontend/src/pages/Operations.jsx:268-270` | KPI "P&L total" de Operaciones | Convierte fila por fila al FX de su propia fecha (convert-then-sum). **Sin filtro de tipo** | `histMoney.sumConvertedAt(ops, o => (o.pnl_usd \|\| 0))` sobre `ops` ya normalizadas con `opPnlUsd` | consumidor |

---

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `frontend/src/components/reports/MonthCard.jsx:225` | grilla de métricas del mes en Reportes | **"Realizado"** |
| `frontend/src/components/reports/MonthCard.jsx:226` | idem | "No realizado" (el contrapunto) |
| `frontend/src/components/reports/WeekCard.jsx:85` | tarjeta de semana en Reportes | **"Realizado"** |
| `frontend/src/components/reports/PerformanceCalendar.jsx:63` y `:109` | KPI strip del calendario | **"P&L Realizado · 12M"** (`realizedSum = last12.reduce((s, m) => s + (m.metrics.realized_pnl \|\| 0), 0)`) |
| `frontend/src/pages/Reports.jsx:560-566` | KPI del período | **"P&L realizado"**, con subtítulo "N ops cerradas" |
| `frontend/src/components/reports/InsightEvidence.jsx:53` y `:171` | evidencia de un insight | "P&L realizado de este activo en el período." / **"Realizado"** |
| `frontend/src/components/MonthlySummary.jsx:727` | formulario de /mensual — **editable a mano** | **"P&L Realizado"** |
| `frontend/src/pages/AssetDetail.jsx:269-270` | ficha del activo (desktop) | **"P&L realizado"** |
| `frontend/src/pages/AssetDetail.jsx:278` | idem | "Mejor trade" |
| `frontend/src/pages/PositionDetailMobile.jsx:356-358` | ficha del activo (mobile) | lista "Operaciones de este activo", con el `pnl_usd` a la derecha |
| `frontend/src/pages/Operations.jsx:466` y `:509-510` | KPI de Operaciones | "P&L total" |
| `frontend/src/pages/Operations.jsx:489-494` | KPI de Operaciones | "Mejor trade" |
| `frontend/src/pages/Positions.jsx:512-556` (vía `bondCashflowsByKey`) | zona de renta fija | "Ya cobraste" / aporte al "P&L con cupones" |
| `frontend/src/components/RentaFijaSections.jsx:310` | fila de bono | `pnlAdjUsd = (v.pnlUsd \|\| 0) + (summary?.pnlContributionUsd \|\| 0)` → **"P&L con cupones"** |
| `frontend/src/components/CompositionDonut.jsx:283-291` | desglose de la torta | **"Resultado"** (no realizado + realizado + renta) |
| `frontend/src/components/advisor/BookComposition.jsx` (vía `bookComposition.js:219`) | torta del libro del asesor | "Resultado" por porción |
| `frontend/src/components/ai/AICoachDrawer.jsx:177` y `:186` | snapshot que va al chat de la IA | campo `realized_pnl_usd_lifetime` (suma de `monthly.pnl_realized`) |
| `frontend/src/pages/RendiAI.jsx:170` y `:179` | idem, página /ai | `realized_pnl_usd_lifetime` |
| `frontend/src/pages/Insights.jsx:1858-1873` | card "Activo estrella" / top asset | contribución por activo |
| `frontend/src/pages/Insights.jsx:1888-1910` | cards de win rate / profit factor / mejor-peor operación | "Win rate", "Profit factor" |
| `frontend/src/utils/diagnostics.js:528-539` | Diagnóstico | "Tu mejor operación cerrada fue…" / "Tu peor operación cerrada fue…" |
| `backend/main.py:13351` (`GET /api/export/operations.csv`) | export para el contador | columna **"P&L USD"** |
| `backend/reporting/builder.py:2023` | narrativa del informe | *"…sumando US$ X de P&L realizado."* |
| `backend/reporting/detectors.py:299-300` | insight `REALIZED_VS_UNREALIZED_GAP` | "Cerraste ganancias pero arrastrás pérdidas abiertas" |
| `backend/reporting/detectors.py:360-370` | insight `DIVIDEND_HEAVY` | `pct = div_int / total_realized * 100` |
| `backend/ai/prompts.py:1022-1040` | system prompt de la IA | `realized_pnl_usd`, `realized_avg_pct_per_trade`; regla explícita de *"JAMÁS expresar realized_pnl_usd como porcentaje sobre capital invertido"* |
| `backend/ai/builders/monthly.py:154` y `:185` | packet mensual de la IA | `metrics.realized_pnl` — documentado como *"USD de trades CERRADOS en el mes. Solo realized."* |
| `backend/ai/builders/reports.py:160` y `:173` | packet de Reportes de la IA | `realized_pnl_year_usd` + alias `pnl_year_usd` |
| `backend/ai/builders/insights.py:648` y `:663` | packet de Análisis de la IA | `realized_pnl_usd` |
| `backend/ai/builders/insights_attribution.py:173-185` | packet de atribución | `total_realized_usd`, `top_contributors[].realized_usd` |
| `backend/main.py:25504-25516` | tool `get_realized_vs_unrealized` | `realized_pnl_usd` + `_note` explicativa |
| `backend/main.py:11761-11767` | admin `realizado_triangulado` | `implicito_por_la_cadena` / `guardado_en_monthly` / `suma_de_operaciones` |
| `backend/main.py:17893` | admin "lo que ve el usuario" | `realized_mes` |
| `backend/wrapped.py:225-233` | Wrapped anual | "X fue tu mejor trade" |
| `backend/main.py:37552` y `:37626` | `/advisor/book/composition` y el spread de retornos | `realized_usd`, `income_usd` |

---

### Dónde se persiste

Sí, se persiste — **en dos capas**, y las dos son escrituras reales, no cache derivado en memoria.

1. **`operations.pnl_usd`** (`double precision DEFAULT 0`) — la fila-evento. [V] `backend/schema_pg.sql:1292` y la base SQLite de dev (`sqlite3 backend/trading.db ".schema operations"`: `pnl_usd REAL DEFAULT 0`). Columnas de apoyo en la misma tabla:
   - `operations.currency` (`text`) y `operations.fx_to_usd` (`double precision`) — [V] `backend/schema_pg.sql:1298-1299`. Son lo que permite normalizar; se sellan desde 2026-08-15 según [V] `backend/realized_pnl.py:16-17`.
   - `operations.cost_basis_consumed` (`double precision`) — [V] `backend/schema_pg.sql:1300`. Solo la escribe `bond_cashflow` ([V] `backend/main.py:10484`) y **el propio código dice que está 100% NULL en las filas reales** ([V] `frontend/src/utils/assetPnl.js:18`, [V] `backend/main.py:37436`). El único lector vivo es `frontend/src/pages/Positions.jsx:542`.
2. **`monthly_entries.pnl_realized`** (`double precision DEFAULT 0`) — el agregado por (usuario, año, mes, broker). [V] `backend/schema_pg.sql:1199`. Es **derivado y reescribible**: `_recalc_pnl_realized_from_ops` lo recomputa entero desde `operations` ([V] `backend/main.py:9589-9596`).
   - Además entra en la identidad de la cadena de capital: `capital_final = capital_inicio + deposits − withdrawals + pnl_realized (+ pnl_unrealized)`. [V] `backend/main.py:9885-9892`, [V] `backend/reporting/schema.py:91-92`.
   - `broker='global'` es una fila sintética con el rollup cross-broker. [V] `backend/main.py:9526-9528`.

**Lo que NO se persiste**: el "realizado del período" de Reportes (`PeriodMetrics.realized_pnl`) se calcula al vuelo en cada request desde `operations` — [V] `backend/reporting/builder.py:842` + `:1655`. Y `realized_pnl_usd` de la IA también se computa al vuelo.

---

### ⚠️ Implementaciones divergentes

**No hay una sola implementación.** Hay una capa canónica (`realized_pnl.py`) que resolvió *la conversión de moneda* en 9 lectores, y por debajo siguen conviviendo **al menos ocho definiciones de negocio distintas** del mismo número.

#### D-1 · El universo: «todo lo que entró» vs «trades cerrados»

| | Universo A | Universo B |
|---|---|---|
| Definición | Σ `pnl_usd` de **todas** las filas | Σ `pnl_usd` excluyendo `Compra`/`Dividendo`/`Interés`/`''`/`CONVERSION*` |
| Dónde | `monthly_entries.pnl_realized` ([V] `main.py:9532-9541`), `PeriodMetrics.realized_pnl` ([V] `builder.py:842`), `export/operations.csv` ([V] `main.py:13357-13362`) | tool `get_realized_vs_unrealized` ([V] `main.py:25412-25425`), `insights.build` ([V] `insights.py:286-288`), `insights_attribution` ([V] `:70`), `operations.build` ([V] `operations.py:53`), `operation_trade` ([V] `:113`) |
| Qué pantalla ve cuál | **Dashboard, /mensual, Reportes (mes/semana/día/año), el CSV del contador** | **Chat de Rendi AI, packets de Análisis, ficha de operación** |
| Incluye dividendos e intereses | **Sí** | No |
| Incluye el FX de las conversiones USD→ARS | **Sí** | No |

Que A incluya dividendos no es accidental: [V] `backend/main.py:5340-5342` elige `^SP500TR` como benchmark precisamente *"porque los portfolios del user sí acumulan dividendos vía `monthly_entries.pnl_realized`"*, y [V] `backend/reporting/detectors.py:360-370` computa `div_int / total_realized * 100` — un cociente que solo tiene sentido si el denominador incluye el numerador.

**Consecuencia concreta**: un usuario con US$1.000 de ventas y US$10.000 de dividendos ve **"P&L realizado +US$11.000"** en Reportes y **"realized_pnl_usd: 1.000"** en el chat de la IA, en la misma sesión.

#### D-2 · El mismo card se contradice solo

[V] `frontend/src/pages/Reports.jsx:560-566` publica `label: 'P&L realizado'` con `value` = `m.realized_pnl` (Universo A) y `sub` = `${m.trades_count} ops cerradas` — donde `trades_count` sale de `_is_trade` (Universo B, [V] `builder.py:845-853`). Un mes con 0 ventas y 5 cupones muestra "+US$ X · **0 ops cerradas**".

#### D-3 · Cuatro tratamientos de la **amortización** de bono

| Ruta | Qué queda en `pnl_usd` | Cita |
|---|---|---|
| `POST /api/bonds/cashflow` (manual) | el monto neto **entero** (devolución de capital contada como ganancia) | [V] `main.py:10479-10484` |
| Importador, amortización sin cantidad | `0.0` — "una amortización devuelve TU capital: no es ingreso" | [V] `persister.py:940-980` |
| Importador, amortización **con** cantidad | se modela como `Venta` FIFO → resultado real | [V] `persister.py:793-799` (docstring en `persister.py:907-928`) |
| Frontend, zona de renta fija | `pnlContrib = amt - cost_basis_consumed`, o **0** si `cost_basis_consumed` es NULL | [V] `Positions.jsx:540-549` |

Los cuatro conviven sobre las mismas filas. Y `assetPnl.js` agrega un quinto matiz: `Amortización` **no** matchea `esRenta` (`'AMORTIZACION'` no contiene `DIVIDENDO`/`INTER`/`CUPON`), así que en la torta cae en `realized`, no en `income` — [V] `frontend/src/utils/assetPnl.js:200-211`.

#### D-4 · `Interés PF` se escapa de todos los filtros

[V] `backend/main.py:9315-9322` escribe `op_type='Interés PF'` con el interés **en moneda nativa** y `fx_to_usd = None` cuando el plazo fijo es en pesos.

- `_NOT_A_TRADE` contiene `'Interés'`, **no** `'Interés PF'` → [V] `realized_pnl.py:74` + `:113`: `is_closed_op('Interés PF')` devuelve **True**. Entra al Universo B como trade cerrado ganado.
- `_NATIVE_CCY_OPS` es solo `('Cupón','Amortización')` → nunca se convierte. Y aunque se lo agregara, `fx_to_usd` es NULL para ARS: no habría con qué dividir.
- El propio módulo lo lista como *Pendiente #3* y dice *"Hoy no muerde (0 filas en producción); el primer plazo fijo en pesos que alguien cobre entra inflado en los 4"* — [V] `realized_pnl.py:61-68`. Pero el docstring habla solo de la moneda; **no** menciona que además cuenta como trade ganado en el win rate.
- Del lado del frontend sí lo agarran los heurísticos por substring: `esRenta` de `assetPnl.js:202` (`tipo.includes('INTER')`) y `_advisor_realized_raw` (`"INTER" in tipo`, [V] `main.py:37504`) lo mandan a `income`. O sea: **para la torta es renta, para la IA y el win rate es un trade ganado.**

#### D-5 · Seis copias a mano del filtro de trades, cuatro con la lista distinta

| Dónde | Lista | ¿Cubre `''`? |
|---|---|---|
| `backend/realized_pnl.py:74` (canónico) | `('Compra','Dividendo','Interés','')` | Sí |
| `backend/behavioral.py:66` | `("Compra","Dividendo","Interés","")` | Sí |
| `backend/ai/builders/reports.py:101` | `('Compra','Dividendo','Interés','')` (SQL crudo) | Sí |
| `backend/reporting/builder.py:847` | `("Compra","Dividendo","Interés")` | **No** |
| `backend/reporting/builder.py:1780` | `("Compra","Dividendo","Interés")` | **No** |
| `backend/reporting/timeline.py:69-72` | `("Compra","Dividendo","Interés")` | **No** |
| `frontend/src/utils/tradeStats.js:31` | `['Compra','Dividendo','Interés']` | **No** |
| `frontend/src/hooks/useMonthlyData.js:48-54` | idem + `if (!t) return false` | Sí, por otra vía |
| `frontend/src/pages/Insights.jsx:1881-1887` | idem + `if (!t) return false` | Sí, por otra vía |

Una fila con `op_type` vacío (existe: el schema permite NULL, [V] `schema_pg.sql:1288`) cuenta como trade en Reportes y en `tradeStats.js`, y no cuenta en la IA ni en behavioral.

#### D-6 · Tres win rates vivos sobre las mismas filas

[V] `frontend/src/utils/tradeStats.js:13-22` lo documenta él mismo: *"había TRES definiciones vivas sobre los mismos datos. Sobre 495 ops reales de un usuario daban 93% (desktop), 100% (mobile) y 85% (backend)"*, y aclara que **sigue sin ser la única**:

- `tradeStats.js:64-76` — ceros al denominador, sin umbral.
- `Insights.jsx:1896-1910` — mismo predicado, denominador `wins + losses`, y descarta micro-trades `|P&L| < 1,50` ([V] `Insights.jsx:1896-1897`).
- `AssetDetail.jsx:171-173` — por activo, **sin filtro de tipo ninguno**.
- `reporting/builder.py:853-855` — `len(wins)/len(trade_ops)*100`.
- `reporting/timeline.py:75-76` — `wins/len(trades)*100`, lifetime.
- `behavioral.py:898` — otra más.

#### D-7 · Quién normaliza el cupón y quién no (frontend)

| Superficie | ¿Usa `opPnlUsd`? | Cita |
|---|---|---|
| Página Operaciones | **Sí**, en el borde del fetch | [V] `Operations.jsx:140` |
| Torta de composición (Dashboard, clase y sector) | **Sí**, vía `computePnlByKey` | [V] `assetPnl.js:170` |
| Torta del libro del asesor | **Sí** (el backend ya convirtió; `realizedToOps` no re-convierte) | [V] `bookComposition.js:233-243` |
| **Ficha de activo (`/activo/:asset`)** | **NO** — `pnl_usd` crudo, sin filtro de tipo | [V] `AssetDetail.jsx:169-175` |
| **Ficha de posición mobile** | **NO** — pinta `$${op.pnl_usd}` | [V] `PositionDetailMobile.jsx:356-358` |
| **Insights: "Activo estrella" / top asset** | **NO** | [V] `Insights.jsx:1860-1864` |
| **Insights: win rate / profit factor / mejor-peor** | **NO** (`tradeOps` sale de `operations` crudas) | [V] `Insights.jsx:1888`, `:1897`, `insightsModel.js:511-512` |
| **Zona renta fija (Positions)** | **NO** — conversión propia con fallback inventado | [V] `Positions.jsx:524-535` |

El módulo lo advierte: [V] `assetPnl.js:60-63` explica que la conversión **no** se hizo en `GET /api/operations` porque `Operations.jsx` reescribe `pnl_usd` al editar. La contrapartida es que cada consumidor del endpoint tiene que acordarse — y cinco no se acordaron.

#### D-8 · El fallback de FX que `realized_pnl.py` prohíbe, y `Positions.jsx` hace igual

[V] `backend/realized_pnl.py:26-32` es explícito: las filas viejas sin `fx_to_usd` **no** se convierten *"y esto es deliberado… convertirlos a todos haría 1250× más chicas a las que ya estaban bien"*. Los tests lo pinnean en los dos lados ([V] `backend/tests/test_realized_pnl_cupon.py:55-59`, [V] `frontend/src/utils/assetPnl.test.js:387-392`).

Pero [V] `frontend/src/pages/Positions.jsx:524-532` hace exactamente lo prohibido:

```
if (op.currency === 'ARS' || (op.currency == null && amt > 1000)) fx = tcValuacion || 1
```

Un cupón legacy de un bono **en dólares** con `currency` NULL y monto > 1.000 se divide por el dólar de HOY. La zona de renta fija muestra un número que el resto de la app (y el módulo canónico) se niega a producir.

#### D-9 · Frontend vs backend para el realizado mensual

[V] `frontend/src/hooks/useMonthlyData.js:329-361`: si el mes **tiene** fila en `monthly_entries`, `pnlRealized = entry.pnl_realized` (Universo A, backend, convertido). Si **no** la tiene, `pnlRealized = realizedFromOps` — computado en el navegador con `isTradeOp` (Universo B) y `pnl_usd` **crudo** ([V] `:265`). Dos definiciones en la misma columna de la misma tabla, según haya o no fila mensual.

#### D-10 · `realized_pnl_usd_lifetime` es una cuarta cosa

[V] `frontend/src/components/ai/AICoachDrawer.jsx:177` y [V] `frontend/src/pages/RendiAI.jsx:170`:

```
const sumPnlRealized = (monthly || []).reduce((acc, m) => acc + (m.pnl_realized || 0), 0)
```

`monthly` es la respuesta cruda de `GET /api/monthly` ([V] `backend/main.py:11971-11974`), que devuelve **todas** las filas: las de cada broker **y** las de `broker='global'`. Sumar todo cuenta el resultado **dos veces** (una por broker, otra en el rollup global). El campo se le manda al modelo rotulado `realized_pnl_usd_lifetime`.

#### D-11 · Documentación vs implementación en los packets de la IA

- [V] `backend/ai/builders/monthly.py:154`: `"metrics.realized_pnl": "USD de trades CERRADOS en el mes. Solo realized."` — pero `m` viene de `build_period_report` ([V] `monthly.py:76-77`), o sea de `builder.py:842`, que **no filtra por tipo**.
- [V] `backend/ai/builders/reports.py:160`: `"realized_pnl_year_usd": "…(suma pnl_realized de monthly_entries). Solo trades cerrados."` — y `monthly_entries.pnl_realized` es Universo A.
- El system prompt le dice al modelo que `twr_pct = realized_pnl_usd + unrealized_pnl_total_usd` ([V] `backend/ai/prompts.py:1022`), mezclando el `realized_pnl_usd` de Universo B con un TWR construido sobre la cadena contable de Universo A.

#### Lo que **sí** converge

- La **normalización de moneda** de `Cupón`/`Amortización` está unificada de verdad en 9 lectores del backend + el espejo JS, con test de paridad SQL↔Python ([V] `backend/tests/test_realized_pnl_cupon.py:82-104`) y test que lee el archivo JS desde Python ([V] `backend/tests/test_advisor_composition.py:707-720`).
- La **fórmula de la venta** es la misma en las tres rutas (manual, import, rebuild): `pnl_ars/tc_venta` en pesos, `precio·qty − costo − comisión` en dólares. [V] `main.py:11288/11295`, `persister.py:793/799`, `rebuild.py:466/470`.
- El **invariante contable** `capital_final = capital_inicio + deposits − withdrawals + pnl_realized (+ unrealized)` se aplica igual en el update incremental y en el repair. [V] `main.py:9885-9892`, `main.py:9717-9719`.

---

### Zonas grises

**G-1 · Un cupón cargado a mano no actualiza el P&L del mes.**
`POST /api/bonds/cashflow` inserta en `operations` y acredita cash, pero **no** llama a `_update_monthly_pnl_realized` ni a `_recalc_pnl_realized_from_ops` — verificado leyendo el endpoint entero ([V] `backend/main.py:10346-10534`) y el grep de callers de ambas funciones. `monthly_entries.pnl_realized` se entera recién cuando otra cosa dispara el recalc: un import, crear/editar/borrar una operación, cerrar un futuro, borrar un broker, o el botón manual `POST /api/imports/recalc-pnl` (`frontend/src/pages/Imports.jsx:131`). O sea: **Dashboard y Reportes pueden quedar atrás del cupón que el usuario acaba de cargar, por tiempo indefinido.** Reportes, en cambio, sí lo ve enseguida para semana/día (lee `operations` directo, `builder.py:842`) — con lo cual la misma pantalla puede mostrar el cupón en la semana y no en el mes.

**G-2 · El usuario puede editar `pnl_realized` a mano, y el recalc se lo pisa.**
`frontend/src/components/MonthlySummary.jsx:727` expone un input "P&L Realizado" que va a `POST/PUT /api/monthly` ([V] `backend/main.py:12011-12024`). El siguiente `_recalc_pnl_realized_from_ops` lo sobrescribe con `SUM(operations)` sin avisar. No encontré ningún guard ni advertencia en la UI.

**G-3 · `export/operations.csv` se rotula "Operaciones cerradas" y exporta todo.**
El docstring dice *"Operaciones cerradas → CSV. Pensado para el contador / reporte fiscal"* pero el `WHERE` es solo `user_id = ?` ([V] `backend/main.py:13358-13361`): salen `Compra` (pnl 0), `Dividendo`, `Interés`, `Cupón`, `Amortización` y `CONVERSION` bajo un encabezado "P&L USD". El propio comentario de arriba reconoce que *"es el único lector cuyo número sale de la app hacia un tercero"*.

**G-4 · Amortización manual = ganancia por el monto entero.**
Es la divergencia D-3, pero merece llamarse bug: `bond_cashflow` guarda `net_amount` en `pnl_usd` aun cuando **calcula** `cost_basis_consumed` en la misma request y hasta devuelve `realized_gain = net_amount − cost_basis_consumed` en la respuesta ([V] `backend/main.py:10505-10508`). El número correcto se computa, se devuelve al frontend… y no se guarda en la columna que después todos suman. Un bono amortizante que devuelve todo el capital termina declarando el 100% del face como P&L realizado.

**G-5 · `cost_basis_consumed` es una columna muerta.**
Dos comentarios independientes afirman que está *"100% NULL en las filas reales"* ([V] `frontend/src/utils/assetPnl.js:18`, [V] `backend/main.py:37436`). Pero `bond_cashflow` la escribe siempre que `flow_type='amortization'` ([V] `main.py:10456-10470`), y hay tests que la verifican ([V] `backend/tests/test_bonds.py:793-808`). No pude reconciliar las dos afirmaciones sin mirar datos de producción — **no verificado**. Si de verdad está NULL, el `pnlContrib = 0` de `Positions.jsx:546` significa que la zona de renta fija muestra **cero** aporte de todas las amortizaciones históricas.

**G-6 · `Interés PF` con `fx_to_usd = NULL` para pesos.**
[V] `backend/main.py:9315`: `fx = 1.0 if moneda in ("USD","USDT") else None`. La ruta que sella el TC existe y se usa en `bond_cashflow` (`_fx.fx_for_date_detail`, [V] `main.py:10419`) pero acá no se llama. Cuando alguien cobre un plazo fijo en pesos, la fila nace irreparable con el criterio actual (que se niega a inferir FX a posteriori).

**G-7 · `_recalc_pnl_realized_from_ops` incluye las conversiones de moneda, y `closed_filter_sql` las excluye.**
`convert_currency` USD→ARS escribe un `pnl_usd` real ([V] `main.py:10943`) y lo suma a `monthly_entries` ([V] `main.py:10977-10979`). El recalc lo vuelve a contar porque no filtra tipos. Pero el criterio canónico dice explícitamente que una conversión **no es un trade** ([V] `realized_pnl.py:92-93`). Las dos cosas son defendibles por separado; juntas significan que el FX del dólar-MEP es "P&L realizado" para el Dashboard y no lo es para la IA.

**G-8 · El "Realizado" en modo Pesos re-expresa ganancias viejas al dólar de hoy.**
`MonthCard`, `WeekCard` y `PerformanceCalendar` formatean `realized_pnl` con `useMoneyFormat().fmtMoney`, que hace `usdValue * tcValuacion` con el TC **actual** ([V] `frontend/src/contexts/CurrencyContext.jsx:309-311`). El propio repo tiene la alternativa correcta y documentada — `sumConvertedAt` / convert-then-sum, con el argumento *"un retiro de $1000 USD en 2024 no se muestra hoy como $1.466.000"* ([V] `frontend/src/hooks/useHistoricalMoney.js:88-96`) — y la usa en Operaciones ([V] `Operations.jsx:269`) pero no en Reportes.

**G-9 · Reportes: cuando no hay snapshots per-broker, el delta ES el realizado.**
[V] `backend/reporting/builder.py:1526-1531`: para día/semana con filtro de broker, `delta_usd = realized` y `unrealized = 0.0`. O sea: en esa vista, "cuánto ganaste esta semana" **es** el P&L realizado — con dividendos y cupones adentro y el mark-to-market afuera. Está comentado como decisión deliberada (AUDIT H-8), pero la UI no distingue.

**G-10 · Wrapped: "tu mejor trade del año" puede ser un dividendo.**
[V] `backend/wrapped.py:214`: `closed = [o for o in ops if (o.get('exit_price') or o.get('pnl_usd'))]` — sin `_is_trade`. La conversión de moneda sí se aplica ([V] `wrapped.py:83-87`, con test en `backend/tests/test_pnl_crudo_otros_lectores.py:57-68`), pero un dividendo o cupón grande sigue pudiendo ganarle a cualquier venta. El test que existe verifica que el **cupón convertido** no le gane a una venta de +500; no verifica que un cupón de US$5.000 no le gane.

**G-11 · El win rate cuenta cobranzas como operaciones ganadas — reconocido y sin arreglar.**
[V] `backend/realized_pnl.py:34-53` lo declara *Pendiente #1*, con los cuatro sitios afectados nombrados (`reporting/timeline.py:61`, `behavioral.py` `detect_winrate_payoff`, `reporting/builder.py:255`, `ai/builders/reports.py` `trades_year`) y la conclusión *"Sin decidir a propósito (2026-08-18)"*. Verifiqué los cuatro: siguen así. (La referencia a `reporting/builder.py:255` está desactualizada — hoy el `_is_trade` del período vive en `builder.py:845`.)

**G-12 · Las 398 filas viejas sin FX siguen infladas en todos los lectores.**
[V] `backend/realized_pnl.py:55-59` (*Pendiente #2*). No es una zona gris del código —es una decisión explícita y testeada— pero sí lo es del producto: hoy hay cupones que entran a `monthly_entries.pnl_realized`, al Dashboard, a Reportes y al CSV del contador como si los pesos fueran dólares, y no hay ningún marcador en la UI que lo diga.

**G-13 · `_advisor_realized_raw` descarta las filas con `pnl == 0`.**
[V] `backend/main.py:37477`: `if pnl == 0: continue`. Como el schema tiene `pnl_usd REAL DEFAULT 0`, una venta a resultado exactamente cero (caso real según [V] `frontend/src/utils/tradeStats.js:24-27`) desaparece del libro del asesor **con su costo**, mientras que en la cartera del cliente sí cuenta. El propio código se preocupa por el caso opuesto (neto cero por compensación entre clientes, `main.py:37541-37545`) pero no por éste.

**G-14 · La `pnl_pct` es el único camino al costo, y hay un bug abierto de monedas.**
Tanto el frontend ([V] `assetPnl.js:220-236`) como el asesor ([V] `main.py:37499`) despejan el costo como `pnl_usd / (pnl_pct/100)` porque *"`entry_price × quantity` está en la MONEDA NATIVA de la operación, y hay un bug abierto conocido donde entry y exit quedan en monedas distintas en la misma fila"* ([V] `assetPnl.js:19-21`). No encontré el fix de ese bug en el código; el workaround está en dos lugares y la causa raíz sigue viva.

**G-15 · `_recalc` recompone solo los meses que ya existen (más los que siembra).**
[V] `backend/main.py:9455-9485`: siembra desde `operations` y desde `import_normalized_tx` (DEPOSIT/WITHDRAW). Un cupón manual **sí** queda cubierto por la siembra desde `operations` — pero el recalc tiene que correr, y G-1 dice que nada lo dispara. El comentario de `rebuild.py:777-785` y los `_update_monthly_pnl_realized` defensivos regados por `main.py` (13876, 14366, 15131) existen justamente por esta fragilidad: cada ruta nueva tiene que acordarse de sembrar la fila del mes a mano.
