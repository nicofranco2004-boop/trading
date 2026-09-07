## Caja / cash / saldo disponible

### Definición según el código

**[V] En Rendi la caja NO es una tabla, ni un saldo derivado del libro de movimientos: es una FILA MÁS de `positions`, marcada con `is_cash=1`, cuyo monto vive en la columna `invested` (no en `quantity`).**

Concretamente, tal como lo implementa el código:

1. **Una fila de caja por broker.** Todos los escritores buscan la caja con la misma consulta: `SELECT ... FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1` (`backend/main.py:9767`, `:9835`, `:10060`, `:10832`, `backend/importing/persister.py:1026`, `:1081`). El `LIMIT 1` sin `ORDER BY` es la definición operativa: si por lo que sea hay dos filas de caja en el mismo broker, la segunda es **invisible para todos los escritores** pero **sí la suman los lectores agregados** (`SUM(invested) ... WHERE is_cash=1`, p. ej. `backend/main.py:32852`).

2. **El monto está en la MONEDA NATIVA del broker**, no en dólares. `brokers.currency` decide (`'ARS'` / `'USD'` / `'USDT'`). La conversión a USD la hace cada lector, y ahí es donde el concepto se rompe en varias implementaciones (ver la sección de divergentes).

3. **El nombre del activo es un centinela derivado de la moneda del broker**, no un dato:
   `'ARS' if currency == 'ARS' else ('USD' if currency == 'USD' else 'USDT')` (`backend/main.py:9779`, `:10076`, `:10168`, y el helper explícito `_cash_asset_for_currency` en `backend/main.py:10664`).
   `'USDT'` NO significa Tether cuando el broker es un sub-broker `«Padre · USD»` — ahí son dólares reales, y el frontend lo corrige **solo en el display** con `cashAssetLabel` (`frontend/src/utils/valuation.js:185`).

4. **La caja es un saldo VIVO que se muta en el lugar** (`UPDATE positions SET invested = invested ± delta`), no un saldo recalculado desde el ledger. Cada operación que mueve plata llama a un ajustador: compra debita, venta acredita, depósito/retiro, dividendo, interés, comisión, impuesto, cupón, amortización, conversión FX, P&L de futuros. El rebuild del FIFO **no** recompone la caja (`backend/importing/fx_migrate.py:22`: *"NO toca cash (`positions is_cash=1`): el rebuild no lo recompone"*).

5. **La caja no tiene P&L, por definición del código.** En todos los valuadores el valor de mercado y el costo de una fila cash son *el mismo número*: `investedUsd: cashUsd, valueUsd: cashUsd` (`frontend/src/utils/valuation.js:636-637`), `invested += cash_usd` (`backend/snapshots_job.py:224`), `if p.is_cash: return { value: p.invested, pnl: 0, pnlPct: 0 ... }` (`frontend/src/pages/Positions.jsx:1264`). No hay ganancia cambiaria por tener pesos quietos: costo y valor se dividen por el MISMO tipo de cambio de hoy.

6. **La caja PUEDE ser negativa, y es a propósito** — es la señal de "te falta cargar el estado inicial" o de overdraft/margen. `_adjust_broker_cash` lo dice literal: *"Se permiten balances negativos — señal visible de overdraft / margen"* (`backend/main.py:9762`). Pero **eso NO es uniforme**: hay tres ajustadores con tres políticas distintas (ver divergentes).

7. **La caja tiene DOS libros paralelos que hay que mover juntos.** El saldo (`positions.invested`, moneda nativa) y el capital aportado (`monthly_entries.deposits/withdrawals`, **siempre en USD**). Un depósito escribe los dos (`backend/main.py:10199-10205`). El `PUT /api/positions/{pid}` escribe **solo el primero** (`backend/main.py:8571-8580`), y el frontend documenta esa trampa: *"esta alta NO registra el aporte … cargar efectivo por acá subía el valor de la cartera sin subir el aportado, y Rendi lo leía como GANANCIA"* (`frontend/src/pages/Positions.jsx:4255-4262`).

8. **La caja se parte por moneda a nivel de CUENTA, no de lote.** A diferencia de las tenencias (donde un broker ARS puede tener un bono en dólares), la caja en dólares de un broker argentino vive en un **sub-broker sintético `«Padre · USD»`** con `currency='USDT'` (`_ensure_usd_sibling`, `backend/main.py:10776`). El chequeo de invariantes lo explicita: *"A diferencia de los activos … la caja SÍ vive separada por pata: por eso existe el sibling"* (`backend/importing/invariantes.py:174-176`).

9. **[I] Definición no estándar #1:** el "saldo disponible" de Rendi no distingue *disponible* de *liquidado a 24/48 h* ni de *comprometido en una orden*. No encontré ninguna noción de settlement ni de plata bloqueada en `positions`. Es un único número por broker/moneda. (Inferido de que la tabla `positions` solo tiene `invested` como magnitud de caja y de que ningún escritor guarda estado de liquidación.)

10. **[I] Definición no estándar #2:** el cash **sí cuenta como patrimonio** en el número grande de la cartera (`total_value` de `snapshots`, total del Dashboard, total por broker), pero **no cuenta** como "posición" en casi todos los denominadores de análisis (concentración, peso, top holdings, cobertura de precios, contador de activos). Es decir: el mismo dólar está adentro del numerador de patrimonio y afuera del denominador de exposición, y eso es deliberado (`backend/main.py:22929-22932`: *"El cash queda con weight_pct=None"*).

---

### Dónde se calcula

Primero los tres ajustadores canónicos (los que ESCRIBEN el saldo), después los valuadores (los que lo convierten a USD), después los productores de la caja sintética.

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `backend/main.py:9750` | `_adjust_broker_cash(conn, uid, broker, delta)` | **EL escritor canónico.** Suma `delta` (moneda nativa) al saldo; si no hay fila de caja la CREA con `delta` como saldo inicial (puede quedar negativo). Se exporta a los helpers del importador (`backend/main.py:29427`). | `new_invested = (cash['invested'] or 0) + delta` | fuente |
| 2 | `backend/main.py:10818` | `_adjust_cash(conn, uid, broker, asset, delta, tc_for_basis)` | Variante ESTRICTA: si el saldo quedaría < −1e−6 tira `HTTPException(400, "Saldo insuficiente…")` y además clampea `max(0.0, new_invested)`. Mantiene un `tc_compra` promedio ponderado del cash USD para el P&L cambiario. | `new_invested = existing + delta` … `new_invested = max(0.0, new_invested)` ; `new_tc = (existing * existing_tc + delta * tc_for_basis) / new_invested` | fuente |
| 3 | `backend/importing/persister.py:1074` | `_adjust_cash_permissive(...)` | Copia de #2 **sin** el rechazo ni el clamp: *"Overdraft permitido — NO clamp a 0"*. La usa el import de conversiones FX. | `new_invested = existing + delta` (sin guard) | fuente |
| 4 | `backend/main.py:9809` | `_autodeposit_if_overdraw(conn, uid, broker, cost_native, date_iso, meta_out)` | En un alta MANUAL que debitaría de más: sube la caja por el faltante Y lo asienta como depósito (capital aportado) al MEP de la fecha, para que el P&L no invente ganancia. | `shortfall = round(cost_native - current, 6)` ; `amount_usd = (shortfall / tcb) if (currency == "ARS" and tcb > 0) else shortfall` | fuente |
| 5 | `backend/main.py:9803` | `_autodeposit_rate(conn, uid, date_iso)` | El dólar del autodepósito: MEP de la FECHA de la compra, con cascada. | `_fx.fx_for_date(conn, date_iso, fallback=fallback) or fallback` | fuente |
| 6 | `backend/main.py:10126` | `POST /api/cash/flow` | Depósito/retiro manual. **Rechaza** un retiro que dejaría negativo; permite el depósito siempre. Si no hay fila de caja y es retiro, 400. Escribe también `monthly_entries` en USD al dólar de la FECHA. | `new_invested = (cash_pos['invested'] or 0) + sign * data.amount` ; `if data.direction == 'withdraw' and new_invested < 0: raise HTTPException(400, f"Saldo insuficiente. Disponible: …")` | fuente |
| 7 | `backend/main.py:10028` | `POST /api/brokers/reconcile-cash` | Pisa el saldo con el valor real declarado por el usuario y asienta la diferencia como depósito/retiro sintético **en el mes MÁS VIEJO del broker**. | `diff = round(data.target_cash - current_cash, 6)` ; `amount_usd = magnitude / data.tc_blue if currency == 'ARS' else magnitude` | fuente |
| 8 | `backend/main.py:10216` | `_revert_cash_flow(...)` | Deshace un `cash_flow`: repone el saldo y **resta de la misma columna** de `monthly_entries` (no suma a la opuesta). | `sign = 1.0 if direction == "withdraw" else -1.0` ; `_adjust_broker_cash(conn, uid, broker_name, sign * amount)` | fuente |
| 9 | `backend/main.py:8250-8257` | `_insert_manual_position` | Alta manual de posición: autodeposita el faltante y después debita el costo. | `cost = _manual_position_cost(p.invested, p.buy_price, p.quantity, p.commissions)` (= `invested ?? buy_price*quantity`, `+ commissions`, `backend/main.py:8198`) ; `_adjust_broker_cash(conn, uid, p.broker, -cost)` | fuente |
| 10 | `backend/main.py:11379` | Venta manual (`create_operation`) | Acredita el neto de la venta a la caja del broker. | `if total_proceeds_native > 0: _adjust_broker_cash(conn, uid, data.broker, total_proceeds_native)` | fuente |
| 11 | `backend/main.py:12362` | Cierre manual de futuro | Acredita el P&L a la caja, convertido a la moneda del broker. | `_adjust_broker_cash(conn, uid, pos["broker"], _pnl_en_moneda_del_broker(conn, uid, pos["broker"], pnl, fecha))` | fuente |
| 12 | `backend/main.py:9143-9144` | Alta de plazo fijo | Autodeposita si falta y debita el capital del PF de la caja del broker origen. | `_adjust_broker_cash(conn, uid, p.source_broker, -float(p.capital))` | fuente |
| 13 | `backend/main.py:9306` | Cierre/cobro de plazo fijo | Devuelve el monto a la caja. | `_adjust_broker_cash(conn, uid, data.broker, monto)` | fuente |
| 14 | `backend/main.py:10231` | `create_conversion` (`POST /api/conversions`) | Conversión ARS↔USD entre padre y sibling: debita una pata, acredita la otra (vía `_adjust_cash`, con `tc_compra` ponderado). | `_adjust_broker_cash(conn, uid, broker_name, sign * amount)` | fuente |
| 15 | `backend/main.py:13010` / `:13076` | Borrar movimiento importado / manual | Reversa el efecto del movimiento sobre la caja. La rama DEPOSIT/DIVIDEND/INTEREST hace el `UPDATE` **a mano** (y no hace nada si no hay fila de caja); la rama `me-` usa `_adjust_broker_cash`. | `((cash["invested"] or 0) - amount, cash["id"], uid)` ; `_adjust_broker_cash(conn, uid, broker, -native if direction == "dep" else native)` | fuente |
| 16 | `backend/main.py:13865`, `:13923-13926`, `:14065`, `:14072`, `:14150`, `:14249`, `:14377`, `:14428`, `:14569`, `:14694`, `:14803`, `:14953`, `:15095` | Edición/borrado en cascada de operaciones, cupones, amortizaciones, lotes y brokers | Cada camino de undo/edición re-ajusta la caja del broker (y del `cash_broker` cuando la plata salió de la pata dólar). | `_adjust_broker_cash(conn, uid, cash_broker, -cash)` (varias firmas) | fuente |
| 17 | `backend/main.py:24687` | Undo del trade registrado por el Coach IA | Devuelve a la caja lo que debitó el alta. | `_adjust_broker_cash(conn, uid, br["name"], info["cash_debited"])` | fuente |
| 18 | `backend/main.py:36657` | Undo de la operación GRUPAL del asesor | Re-acredita el costo a la caja de cada cliente. | `_adjust_broker_cash(conn, cid, pos["broker"], credit)` | fuente |
| 19 | `backend/importing/persister.py:596` | `_persist_buy` (import) | Debita el costo total de la caja de la cuenta de la que salió la plata (`cash_broker`, no necesariamente el broker de la tenencia). | `helpers._adjust_broker_cash(conn, uid, tx.cash_broker or tx.broker, -cost_total)` | fuente |
| 20 | `backend/importing/persister.py:848` | `_persist_sell_fifo` (import) | Acredita el neto de la venta. | `helpers._adjust_broker_cash(conn, uid, tx.cash_broker or tx.broker, total_proceeds_native)` | fuente |
| 21 | `backend/importing/persister.py:891` | `_persist_futures_pnl` | Acredita el P&L de futuros. | `helpers._adjust_broker_cash(conn, uid, tx.broker, pnl)` | fuente |
| 22 | `backend/importing/persister.py:968` | `_persist_dividend_or_interest` | Acredita dividendo/interés/amortización. | `helpers._adjust_broker_cash(conn, uid, tx.broker, amount)` | fuente |
| 23 | `backend/importing/persister.py:1005` | `_apply_cash_flow` (DEPOSIT/WITHDRAW/FEE/IMPUESTO del import) | Escribe el saldo **directo** (no vía `_adjust_broker_cash`) y permite negativo explícitamente. El asset name de la fila nueva es `'ARS'` o `'USDT'` — **nunca `'USD'`**. | `new_invested = (cash_pos["invested"] or 0) + sign * amount` ; `asset_name = "ARS" if currency == "ARS" else "USDT"` | fuente |
| 24 | `backend/importing/persister.py:1440`, `:1522`, `:1563`, `:1633` | `revert_batch` | Reversa por tipo de operación cada efecto sobre la caja del batch. | `helpers._adjust_broker_cash(conn, uid, _cb, cost_total)` / `(..., -total_proceeds)` / `(..., -pnl)` | fuente |
| 25 | `backend/importing/persister.py:278-288` | Routing por moneda dentro de `persist_batch` | Al crear el sibling `· USD` siembra su caja en 0. *"Sin esto, los BUYs USD que aterrizan en un sibling recién creado no descuentan cash … y el saldo queda inflado."* | `INSERT INTO positions (user_id, broker, asset, is_cash, invested) VALUES (?,?,?,1,0)` con `"USDT"` | fuente |
| 26 | `backend/importing/persister.py:68` | `cash_broker_for(conn, uid, broker, currency, asset_type)` | **De qué cuenta sale la plata.** Un CEDEAR comprado con dólares consolida la tenencia en el padre pero debita el sibling `· USD`. Derivable a propósito, no persistido. | `if (currency or "").upper() not in ("USD","USDT"): return broker` … `for name in broker_pair(...): if name != broker: return name` | fuente |
| 27 | `backend/importing/tenencia.py:670` | `build_cash_trueup_txs(adjustments, seed_date, start_idx=-21000)` | Ante una foto de tenencia, emite DEPOSITO/RETIRO sintético para llevar la caja al saldo del resumen del broker. Silencioso. | `diff = round(target - cur, 2)` ; `operation_type=(OP_DEPOSIT if diff > 0 else OP_WITHDRAW)`, `gross_amount=abs(diff)` | fuente |
| 28 | `backend/main.py:30177-30208` | Confirm de foto de tenencia | Arma los `adjustments` del true-up: ARS contra el padre (eps 1.0), USD contra el sibling (eps 0.01). Se SALTEA si la foto es parcial. | `_adj.append((broker, "ARS", _cur_cash(broker), snap.cash_ars, 1.0))` ; `_adj.append((_sib, "USD", _cur_cash(_sib), snap.cash_usd, 0.01))` | fuente |
| 29 | `backend/main.py:31163` | `_wallbit_reconcile_positions` | True-up de la caja de Wallbit contra la foto de la API (broker USD, sin sibling). | `build_cash_trueup_txs([("Wallbit", "USD", cur_cash, cash_usd, 0.01)], seed_date)` | fuente |
| 30 | `backend/main.py:31044` | `_wallbit_ensure_broker` | Crea el broker Wallbit **con su caja en 0 y asset `'USD'`**. | `INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity) VALUES (?,?, 'USD', 1, 0, 0)` | fuente |
| 31 | `backend/importing/seed.py:307-330` | `seed_state_to_txs` | El "estado inicial" del wizard: un DEPOSIT (o WITHDRAW) sintético por moneda = cash declarado + costo de las compras sintéticas. | `total = user_cash + covered_cost` ; `op_type = OP_DEPOSIT if total > 0 else OP_WITHDRAW` | fuente |
| 32 | `frontend/src/components/import/ImportWizard.jsx:629-636` | `buildSeedPayload` | El usuario tipea su **saldo de HOY**; el ajuste que se manda al backend es la resta contra el saldo que dio el CSV. | `return [cur, Number(v) - F]   // ajuste = saldo_real − estimado (+ o −)` | fuente |
| 33 | `backend/importing/cash_sim.py:40` | `simulate(...)` | **Simulador de caja en memoria** para el preview: recorre las txs en orden (BUY primero dentro del día) y avisa qué fila cruza a negativo. No bloquea. | `new = prev + delta` ; warning `if delta < 0 and new < 0 and prev >= 0` | fuente (proyección) |
| 34 | `backend/importing/pipeline.py:793-801` | Preview del import | Carga el saldo de arranque de la simulación desde la caja real. | `starting_cash[(r["broker"], r["currency"])] = float(r["invested"] or 0)` | consumidor→fuente |
| 35 | `backend/ledger_replay.py:93` | `cash_en(conn, uid, fecha)` | **Reconstruye la caja histórica desde el ledger de imports** (no desde `positions`). Es un motor PARALELO al saldo vivo. | `_CASH_MAS = ("DEPOSIT","SELL","DIVIDEND","INTEREST","FUTURES_PNL")` / `_CASH_MENOS = ("WITHDRAW","BUY","FEE","IMPUESTO")` ; `saldos[k] -= float(r["fees"] or 0) + float(r["taxes"] or 0)` | fuente (histórico) |
| 36 | `backend/ledger_replay.py:254-258` | `valor_en` | Inyecta la caja replayeada como posición sintética `is_cash=1` para pasarla al motor canónico de valuación. | `{"asset": ccy, "broker": broker, "asset_type": None, "is_cash": 1, "quantity": 0.0, "invested": saldo, ...}` | fuente |
| 37 | `frontend/src/utils/valuation.js:626-641` | `valuePositionLot` — rama 1, broker ARS | **Valuador canónico del frontend.** Caja en pesos → USD por el **dólar-MEP** (`cedearRate`), igual que las tenencias. Valor = costo. | `const cashArs = p.invested || 0` ; `const cashUsd = cashArs / cedearRate` ; `salida({ investedUsd: cashUsd, valueUsd: cashUsd, invArs: realCost, valueArs: cashArs })` | fuente |
| 38 | `frontend/src/utils/valuation.js:675-679` | `valuePositionLot` — rama 1, broker USD | Caja en dólares → tal cual. `invArs`/`valueArs` quedan en 0. | `const v = p.invested || 0` ; `salida({ investedUsd: v, valueUsd: v, invArs: 0, valueArs: 0 })` | fuente |
| 39 | `frontend/src/utils/valuation.js:740` | `computeBrokerValue` | Total por broker = suma de `valuePositionLot` sobre TODOS los lotes, cash incluido. | `value += r.valueUsd; invested += r.investedUsd` | consumidor |
| 40 | `backend/snapshots_job.py:213-224` | `compute_broker_value_usd` — rama ARS | Port Python del anterior. Caja ARS al **MEP** (`cedear_rate`), no al blue. Comentario: *"acá se dividía por el BLUE genuino del cron → snapshot de 'sabor mixto' … 'P&L Día' fantasma PERMANENTE proporcional al cash"*. | `cash_usd = cash_ars / cedear_rate if cedear_rate > 0 else 0` ; `value += cash_usd` ; `invested += cash_usd` | fuente |
| 41 | `backend/snapshots_job.py:285-288` | `compute_broker_value_usd` — rama USD/USDT | Caja USD directo. | `v = p.get('invested') or 0` ; `value += v` ; `invested += v` | fuente |
| 42 | `backend/behavioral.py:442-447` | `_position_value_usd` | **Valuador canónico del backend.** Caja: si la moneda NATIVA (`_native_ccy`) es ARS, divide por `rate_holdings` (= `tc_cedear` si vino, si no `tc_blue`); si no, devuelve `invested` crudo. | `if cost_ccy == "ARS": return invested_native / rate_holdings if rate_holdings > 0 else 0.0` ; `return invested_native` | fuente |
| 43 | `backend/behavioral.py:195-215` | `_native_ccy(p)` | La moneda REAL de la fila de caja: `currency` explícita > asset en `_USD_CASH_TOKENS` (`USD/USDT/USDC/USDD/DAI`) o `'ARS'` > sub-broker `· USD` > broker AR > default USD. | `_USD_CASH_TOKENS = frozenset({"USD","USDT","USDC","USDD","DAI"})` | fuente |
| 44 | `frontend/src/pages/Positions.jsx:1264` | `calcUSDT` (fila desktop, broker USD) | Caja de la fila: valor = costo = `invested`, P&L 0. | `if (p.is_cash) return { value: p.invested, pnl: 0, pnlPct: 0, price: null, investedUsd: p.invested }` | fuente (fila) |
| 45 | `frontend/src/pages/Positions.jsx:1322-1323` | `calcARS` (fila desktop, broker ARS) | Caja de la fila: pesos crudos + USD por `tcCedear`. | `return { valueArs: p.invested, valueUsd: p.invested / tcCedear, pnlArs: 0, pnlUsd: 0, pnlPct: 0, priceArs: null }` | fuente (fila) |
| 46 | `frontend/src/pages/PositionsMobile.jsx:684-696` | Fila mobile | Igual que arriba pero dividiendo por `tcValuacion` (que en ese archivo es el MISMO número que `tcCedear`, líneas 629-630). Devuelve `investedUsd = valueUsd` para que el pie del broker no infle el P&L. | `valueUsd = isAR ? cashInvested / tcValuacion : cashInvested` | fuente (fila) |
| 47 | `frontend/src/pages/AssetDetail.jsx:39-42` | `valueLot` (detalle de activo, desktop) | Caja → `invested`, `/tcValuacion` si broker ARS. | `const v = isAR ? cashInvested / tcValuacion : cashInvested` | fuente (fila) |
| 48 | `frontend/src/pages/PositionDetailMobile.jsx:112-113` | Detalle de posición mobile | Idem. | `valueUsd = isAR ? invested / tcValuacion : invested` | fuente (fila) |
| 49 | `frontend/src/pages/Dashboard.jsx:398-407` | `cashForComposition` | Caja para la torta de distribución: pesos → USD por `tcCedear`. | `value_usd: arsBrokerNames.has(p.broker) ? (p.invested \|\| 0) / tcCedear : (p.invested \|\| 0)` | fuente |
| 50 | `frontend/src/pages/Insights.jsx:1838-1846` | `cashUsd` / `cashRatio` | % de la cartera en caja. Divide por `tcValuacion` (mismo `pickFinancialRate` que `tcCedear` en ese archivo). | `s + cashPositions.reduce((sum, p) => sum + (p.invested \|\| 0) / tcValuacion, 0)` ; `cashRatio = totalPortfolio > 0 ? (cashUsd / totalPortfolio) * 100 : 0` | fuente |
| 51 | `frontend/src/pages/Insights.jsx:495-505` | `positionsWithValue` | Estampa `value_usd` en las filas de caja para las cards de perfil. Comentario histórico: *"antes leíamos `quantity` directamente y caía a 0"*. | `const val = broker?.currency === 'ARS' ? amount / tcValuacion : amount` | fuente |
| 52 | `frontend/src/pages/Insights.jsx:2075-2081` | `aiCash` | Bloque de caja del snapshot que se le manda a la IA. | `value_usd: arsBrokerSet.has(p.broker) ? +((p.invested \|\| 0) / tcValuacion).toFixed(2) : +(p.invested \|\| 0).toFixed(2)` | fuente |
| 53 | `backend/main.py:22848-22930` | `_valuate_positions_for_chat` | Valuación server-side AUTORITATIVA del snapshot del chat: valúa lote por lote con `compute_broker_value_usd`, agrupa por holding y le pone `weight_pct = None` a la caja. | `if h["is_cash"]: h["weight_pct"] = None` ; `total_holdings_value` suma solo `not h["is_cash"]` | fuente |
| 54 | `backend/main.py:37292` | `_advisor_cash_usd(conn, ids, tc_mep)` | Caja del libro del asesor, por cliente. **Descarta los saldos ≤ 0** y los brokers huérfanos. | `if v <= 0: continue` ; `"value_usd": v / tc_mep if (r["ccy"] or "").upper() == "ARS" else v` | fuente |
| 55 | `backend/advisor_groups.py:228-236` | Perfil de grupo del asesor | Caja por cliente al MEP; también descarta ≤ 0. | `usd = amt / tc_mep if (r["c"] == "ARS" and tc_mep) else amt` ; `if usd > 0 and r["u"] in prof: prof[r["u"]]["cash_usd"] += usd` | fuente |
| 56 | `backend/main.py:35493-35499` | Contexto del chat del asesor | Caja por cliente al MEP, también `if _usd > 0`. | `_usd = _amt / tc_mep if _cr["c"] == "ARS" and tc_mep else _amt` | fuente |
| 57 | `backend/main.py:32847-32855` | `_portfolio_snapshot_summary` → `cash_value` | **Suma `invested` de TODAS las filas de caja SIN convertir moneda.** El propio código lo marca como defecto preexistente y no lo arregla porque *"nadie lo consume"*. | `SELECT COALESCE(SUM(invested), 0) AS cash FROM positions WHERE user_id = ? AND COALESCE(is_cash, 0) = 1{_cash_clause}` | fuente (rota, ver zonas grises) |
| 58 | `backend/ai/builders/dashboard.py:129-135` | Packet IA del Dashboard | Suma la caja al total y calcula `cash_pct`, delegando en `_position_value_usd`. | `cash_usd += value_usd` ; `cash_pct = (cash_usd / total_value_usd) if total_value_usd > 0 else 0` | consumidor |
| 59 | `backend/ai/builders/insights.py:435-443` | Packet IA de Análisis | Bucket geográfico: la caja va a `geo_value["cash"]` usando el **costo** (no el valor de mercado), convertido al MEP. | `if cost_is_ars: cost_usd = invested / _rate` … `if p.get("is_cash"): geo_value["cash"] += cost_usd; continue` | consumidor |
| 60 | `backend/ai/builders/profile_card.py:277-281` + `:44` | Cards del perfil del inversor (IA) | La caja alimenta el bucket `cash` con `_invested_usd` (MEP para ARS). | `bucket_totals["cash"] += _invested_usd(p, tc_blue, tc_mep)` | consumidor |
| 61 | `backend/behavioral.py:1163-1217` | `detect_cash_drag` | % de la cartera en caja, separando ARS de USD por `_native_ccy`. Si el neto es negativo devuelve un caso especial en vez de un % absurdo. | `cash_total = cash_usd + cash_ars_usd_equiv` ; `cash_pct = (cash_total / total) * 100` ; `if cash_total < 0: … "Cash neto negativo"` | consumidor |
| 62 | `backend/reporting/detectors.py:216-230` | `detect_large_cash_drag` (informe del período) | > 30 % en caja → insight. | `cash_value = sum(float(p.get("value_usd") or 0) for p in positions if p.get("is_cash"))` ; `cash_pct = cash_value / total * 100` | consumidor |
| 63 | `frontend/src/utils/diagnostics.js:383-397` y `:400-414` | Diagnósticos `cash_heavy` / `cash_low` | ≥ 30 % o muy poco. Convierte ARS por `tcValuacion`. | `(arsBrokerSet.has(p.broker) ? (p.invested \|\| 0) / tcValuacion : (p.invested \|\| 0))` | consumidor |
| 64 | `frontend/src/utils/diagnostics.js:466-476` | `fx_cash_ars_exposure` | Cuánta caja hay en pesos. | `const cashUsd = cashArs / tcValuacion` | consumidor |
| 65 | `backend/importing/invariantes.py:172` | `check_cash_moneda` | Invariante: la caja de un broker dólar no puede ser pesos ni al revés. **Gatea por `quantity`, no por `invested`.** | `WHERE p.is_cash=1 AND UPPER(COALESCE(p.asset,'')) IN ('ARS','USD','USDT') AND (…) AND ABS(COALESCE(p.quantity,0))>0.005` | consumidor (chequeo) |
| 66 | `backend/importing/invariantes.py:199` | `check_caja_concilia` | Mide cuánto tuvo que corregir la foto al efectivo reconstruido (lee los `Ajuste de cash a Estado de Cuenta`). Aviso, no error. | `WHERE n.notes LIKE 'Ajuste de cash a Estado de Cuenta%' AND b.status='confirmed'` | consumidor (chequeo) |
| 67 | `backend/importing/persister.py:447-462` | `cash_health` de `persist_batch` | Snapshot del saldo por broker tocado, para que el wizard avise si quedó negativo. | `"balance": float(r["invested"] or 0)` | consumidor |
| 68 | `backend/importing/recompute_backfill.py:127` | Backfill de recomputación | Suma la caja de todos los brokers, **sin convertir moneda**. | `SELECT COALESCE(SUM(invested),0) c FROM positions WHERE user_id=? AND is_cash=1` | consumidor |
| 69 | `backend/sim_import.py:84-88` | Simulador de import (script) | Reporta el saldo por broker post-import. | `WHERE p.user_id=? AND p.is_cash=1` | consumidor |
| 70 | `frontend/src/utils/demo.js:212-217` | Fixture de demo | Valúa la caja **por `quantity`**, no por `invested` (en el fixture ambos coinciden). | `v = p.broker === 'Cocos' ? (p.quantity \|\| 0) / _DEMO_TC_BLUE : (p.invested \|\| 0)` | fuente (solo demo) |

---

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `frontend/src/pages/Positions.jsx:2346-2359` | Cartera (desktop): fila de efectivo con logo, chip y fondo distinto | badge **`CASH`** (ícono Wallet) + el nombre del activo (`ARS` / `USD` / `USDT`) vía `cashAssetLabel` |
| `frontend/src/pages/Positions.jsx:1046`, `:1096-1097`, `:1199-1200` | Ordenamiento: el efectivo va SIEMPRE al final de cada bloque | — |
| `frontend/src/pages/Positions.jsx:3695-3713` | Menú contextual de la fila de efectivo | **Depositar / Retirar / Comprar USD / Vender USD a ARS / Editar posición / Eliminar** |
| `frontend/src/pages/Positions.jsx:995`, `:1027` | Validación de retiro/conversión en el cliente | *"Saldo insuficiente. Disponible: X CCY."* |
| `frontend/src/pages/Positions.jsx:4263-4276` | Form de posición | checkbox **"Es cash"** (solo al EDITAR) + aviso *"¿Querés registrar efectivo? … usá **Movimiento de cash**"* |
| `frontend/src/pages/PositionsMobile.jsx:2514` | Cartera mobile: etiqueta de contexto de la fila | **"Efectivo"** |
| `frontend/src/pages/PositionsMobile.jsx:2590-2629` | Cartera mobile: columnas Precio / Var. día / Precio prom. de una fila cash | se renderizan como `<Vacio />` (guion) |
| `frontend/src/pages/PositionsMobile.jsx:887-888`, `:909-910` | Orden mobile: el cash último | — |
| `frontend/src/pages/PositionsMobile.jsx:374`, `:2893` | Modal de cash mobile | *"Saldo insuficiente. Disponible: …"*, *"Modificar saldo en alguno de tus brokers"* |
| `frontend/src/pages/PositionDetailMobile.jsx:213`, `:307` | Detalle de una fila de efectivo | logo Wallet + bloque exclusivo de cash |
| `frontend/src/pages/Dashboard.jsx:414-435` | Torta de distribución (clase y sector) | porción **"Efectivo"** (`frontend/src/utils/assetClass.js:103`) |
| `frontend/src/pages/Dashboard.jsx:440-478` | `priceCoverage` — guard de snapshot | el cash se EXCLUYE del denominador (`nonCash`) |
| `frontend/src/pages/Insights.jsx:1846` | Análisis: ratio de caja | usado por cards y alertas |
| `frontend/src/pages/Insights.jsx:2614-2616` | Análisis: agrupación por activo para la torta | nombre **"Efectivo"** |
| `frontend/src/components/profile/LiquidityBar.jsx:3-4`, `:60` | Card "Colchón de liquidez" del perfil | *"verde = cash + renta fija (disponible/estable)"* |
| `frontend/src/components/profile/ProfileDashboard.jsx:39` | Card del perfil | **"Colchón de liquidez"** |
| `frontend/src/components/advisor/GroupsBar.jsx:145` | Filtro de grupos del asesor | **"Sin invertir (liquidez) — % o más"** |
| `frontend/src/utils/insightsModel.js:452` | Clasificación de posición | bucket **`'Cash'`** |
| `frontend/src/utils/assetClass.js:220`, `:227` | `assetClass(position)` | `is_cash` → `'cash'`; además las stablecoins NO marcadas (`STABLECOINS`) también caen en `'cash'` |
| `frontend/src/utils/profileAllocations.js:278`, `:293` | `classifyAssetBucket` | `'cash'`; `['USDT','USDC','DAI']` no marcadas también |
| `frontend/src/utils/profileAllocations.js:104-123` | Mezcla objetivo por perfil | `cash: 30 / 15 / 5` según perfil |
| `frontend/src/components/import/ImportWizard.jsx:2367-2375` | Wizard de import: aviso de overdraft | *"El sistema permite saldos negativos en imports (overdraft)… · saldo BROKER: CCY X"* |
| `frontend/src/components/import/ImportWizard.jsx:2536` | Wizard: campo del saldo inicial | *"Solo la plata **disponible sin invertir** — **no** el total de la cuenta"* |
| `frontend/src/components/import/ImportWizard.jsx:1025-1031` | Wizard: bloqueo de confirmación | obliga a confirmar el saldo de HOY de las cuentas con saldo negativo |
| `frontend/src/pages/RendiAI.jsx:167` y `frontend/src/components/ai/AICoachDrawer.jsx:174` | Snapshot que va al chat | `totalCashPositions` |
| `frontend/src/components/RentaFijaSections.jsx:82` | Zona de renta fija cross-broker | el cash se saltea |
| `frontend/src/components/AssetLogo.jsx:6-9` | Logo de la fila | `is_cash` sin archivo de logo → ícono Wallet genérico |
| `frontend/src/utils/demo.js:2031` | Catálogo de métricas (demo) | **"Caja Total"** — *"Efectivo y equivalentes disponibles."* |
| `backend/main.py:13394-13407` | `GET /api/export/positions.csv` | columna **"Es cash"** |
| `backend/main.py:22977-22983` | Snapshot del chat | `total_cash_positions`, `cash_lines_count` |
| `backend/main.py:22993-23000` | `valuation_note` que se le manda al modelo | *"weight_pct = % del valor de los holdings (excluye cash; el cash tiene weight_pct null)"* |
| `backend/goals_diagnostic.py:52-60` | Diagnóstico de objetivos | **"Demasiado cash sin invertir"**, *"El cash en ARS pierde por inflación"* |
| `backend/reporting/detectors.py:216-238` | Informe del período | **"X% de tu portfolio está en cash"** |

**Lectores que EXCLUYEN la caja por SQL** (`is_cash=0`), es decir: superficies donde el saldo simplemente no existe — `backend/main.py:5819`, `:6075`, `:6991`, `:8983`, `:12758`, `:13538`, `:17671`, `:18413`, `:19040`, `:19160`, `:29572`, `:29860`, `:29950`, `:30027`, `:30133`, `:31790`, `:32709`, `:32818`, `:34194`, `:34228`, `:34527`, `:34817`, `:35288`, `:35748`, `:35815`, `:36136`, `:36371`, `:36878`, `:37105`; `backend/twr.py:329`, `:344`, `:447`; `backend/price_history.py:166`; `backend/home/briefing.py:46`; `backend/alerts_engine.py:77`; `backend/analysis_prep.py:58`; `backend/reporting/builder.py:282`; `backend/importing/pipeline.py:210`; `backend/importing/proyeccion.py:90`, `:143`; `backend/importing/maturity.py:221`, `:350`; `backend/importing/rebuild.py:573`, `:620`, `:635`, `:656`; `backend/importing/recompute_backfill.py:119`, `:140`, `:183`, `:243`, `:270`, `:540`, `:568`, `:620`; `backend/ai/builders/events.py:39`, `home.py:121`, `:142`, `news.py:43`, `insights_summary.py:111`, `insights_attribution.py:82`, `dashboard_events.py:39`.

---

### Dónde se persiste

**[V] Tabla y columna:**

| Qué | Dónde |
|---|---|
| Bandera | `positions.is_cash` — `bigint DEFAULT 0` en Postgres (`backend/schema_pg.sql:1436` y el `ALTER … ADD COLUMN IF NOT EXISTS` de `:1457`), `INTEGER DEFAULT 0` en SQLite (`backend/main.py:928`, `:945`; verificado también en la base de dev: `sqlite3 backend/trading.db ".schema positions"` devuelve `is_cash INTEGER DEFAULT 0`) |
| **El monto** | `positions.invested` — `double precision`. En la moneda NATIVA del broker |
| Etiqueta de moneda | `positions.asset` — centinela `'ARS'` / `'USD'` / `'USDT'` |
| Moneda explícita (opcional) | `positions.currency` — la mayoría de los INSERT de caja **no la setean** (queda NULL); `_native_ccy` la infiere |
| TC de compra del cash USD | `positions.tc_compra` — solo lo escribe `_adjust_cash` / `_adjust_cash_permissive` con `tc_for_basis` (compra de dólares) |
| `quantity` | **normalmente 0 o NULL** para la caja. Los INSERT de caja casi nunca la setean (`backend/main.py:9782`, `:10078`, `:10170`, `:10864`, `persister.py:1041`, `:1102`). Excepciones: `backend/main.py:31044` (Wallbit, `quantity=0` explícito) y `backend/seed.py` |

**[V] No hay tabla de caja, ni de saldos, ni de asientos de caja.** `grep` sobre `backend/schema_pg.sql` por `cash` solo devuelve `bond_cashflow_skips` (que es otra cosa: pagos de bono que el usuario decidió ignorar) y las dos líneas de `positions.is_cash`.

**[V] La caja NO se persiste como serie histórica.** `snapshots` guarda `total_value` (que SÍ incluye la caja, vía `compute_broker_value_usd`) y `holdings_json` (que **NO** la incluye — `backend/snapshots_job.py:757-762` la saltea explícitamente). O sea: la única traza histórica del saldo es indirecta y está mezclada con el resto del patrimonio.

**[V] El flujo de caja SÍ se persiste, aparte y en otra unidad:** `monthly_entries.deposits` / `withdrawals` / `manual_deposits` / `manual_withdrawals` (siempre en USD) y `manual_deposits_native` / `manual_withdrawals_native` (moneda nativa, para poder revertir exacto — `backend/main.py:13070-13076`).

**[V] Los ajustes sintéticos de caja quedan auditables** como filas en `import_normalized_tx` con `notes` `'Ajuste de cash a Estado de Cuenta (CCY)'` (`backend/importing/tenencia.py:694`) o `'Estado inicial — depósito/retiro sintético (Rendi)'` (`backend/importing/seed.py:328`), dentro de un `import_batch` revertible.

---

### ⚠️ Implementaciones divergentes

**NO hay una sola implementación.** Encontré divergencias en cinco ejes distintos.

#### D-1. Tres ajustadores del saldo con TRES políticas de negativo distintas

| variante | archivo:línea | ¿permite negativo? | ¿crea la fila si no existe? | ¿toca `tc_compra`? |
|---|---|---|---|---|
| `_adjust_broker_cash` | `backend/main.py:9750` | **SÍ**, a propósito | **SÍ**, con el delta (puede nacer negativa) | no |
| `_adjust_cash` | `backend/main.py:10818` | **NO** — `HTTPException(400)` si < −1e−6, y encima `max(0.0, …)` | solo si `delta > 0`; si `delta < 0` tira 400 | **sí** (promedio ponderado) |
| `_adjust_cash_permissive` | `backend/importing/persister.py:1074` | **SÍ** | **SÍ** | **sí** |
| `_apply_cash_flow` (import) | `backend/importing/persister.py:1029-1041` | **SÍ** (`UPDATE` directo) | **SÍ** | no |
| `POST /api/cash/flow` | `backend/main.py:10153-10165` | solo en depósito; **rechaza** el retiro que deje < 0 | solo en depósito | no |
| borrado de mov. DEPOSIT/DIVIDEND/INTEREST | `backend/main.py:12998-13008` | sí (`UPDATE` directo) | **NO** — si no hay fila de caja, **no hace nada y la plata se pierde en silencio** | no |

Qué pantalla ve cuál: la Cartera (alta manual, venta, cupón) va por `_adjust_broker_cash`; el modal de Depósito/Retiro va por el endpoint estricto; **el mismo movimiento cargado a mano y el mismo movimiento importado siguen políticas distintas**. Un CSV puede dejar el saldo en −200 y el modal de retiro después no te deja sacar ni un peso de ese broker.

#### D-2. Dos motores de caja: el saldo VIVO vs. el replay del ledger

| | saldo vivo | replay histórico |
|---|---|---|
| dónde | `positions.invested` (`is_cash=1`) | `backend/ledger_replay.py:93` `cash_en()` |
| de dónde sale | mutaciones acumuladas de cada endpoint/import | suma de `import_normalized_tx` por tipo de operación |
| qué operaciones cuenta | TODO lo que llame a un ajustador (incluye conversiones FX, transferencias, futuros, PF, autodepósitos, altas manuales) | **solo** `DEPOSIT, SELL, DIVIDEND, INTEREST, FUTURES_PNL` (+) y `WITHDRAW, BUY, FEE, IMPUESTO` (−) — `backend/ledger_replay.py:89-90` |
| **qué NO cuenta el replay** | — | **`FX_ARS_TO_USD`, `FX_USD_TO_ARS` y `TRANSFER` no están en ninguna de las dos listas** (constantes en `backend/importing/schema.py:23-25`) → una conversión de pesos a dólares es invisible para el replay: no baja los pesos ni sube los dólares |
| a qué broker imputa | al `cash_broker` derivado (`cash_broker_for`, sibling `· USD` para CEDEAR en dólares) | a `n.broker` crudo, **sin routing al sibling** (`backend/ledger_replay.py:122`) |
| filas con `gross_amount = 0` | las comisiones/impuestos se debitan igual | `if monto <= 0: continue` (`backend/ledger_replay.py:118`) → una fila de solo comisión no debita nada |

El propio archivo dice que existe para no tener dos motores (*"Tener un segundo motor de valuacion es como se vuelve a los ~15 motores de retorno"*, `backend/ledger_replay.py:200-207`) — y sin embargo para el CASH sí construye un segundo motor, con reglas distintas.

Hay además un TERCER motor de proyección: `backend/importing/cash_sim.py:40`, que sí rutea al sibling (`_route`, `:74`) y sí maneja FX (`:170-180`) — pero solo alimenta warnings del preview, nunca escribe.

#### D-3. Dos tipos de cambio para la MISMA caja en pesos

Casi todo el sistema ya convergió al **dólar-MEP** (`cedearRate` / `tc_cedear` / `pickFinancialRate`), y hay comentarios que documentan la migración desde el blue (`backend/snapshots_job.py:215-219`, `frontend/src/utils/valuation.js:628-632`). Pero quedan **comentarios que dicen blue sobre código que hace MEP**, y un lector que no convierte nada:

| sitio | qué dice el comentario | qué hace el código |
|---|---|---|
| `backend/reporting/timeline.py:100-101` | *"Cash en pesos → dólar-blue"* | llama a `_position_value_usd(p, prices, tc_blue, tc_cedear)` (`:143`) → convierte al **MEP** |
| `backend/ai/builders/insights.py:365-367` | *"El CASH en pesos sigue por tc_blue"* | `_rate = tc_cedear if (tc_cedear and tc_cedear > 0) else tc_blue` (`:437`) → **MEP** |
| `backend/ai/builders/profile_card.py:53-55` | *"el CASH en pesos se convierte por el dólar-blue"* | `rate = tc_cedear if (tc_cedear and tc_cedear > 0) else tc_blue` (`:61`) → **MEP** |
| `backend/ai/builders/dashboard.py:122-124` | *"cash en pesos al blue"* | delega en `_position_value_usd` con `tc_cedear` → **MEP** |
| `backend/main.py:32847-32855` (`cash_value`) | — | **NO convierte NADA**: suma pesos y dólares en el mismo número |
| `backend/importing/recompute_backfill.py:127` | — | **NO convierte NADA** |

El comportamiento efectivo converge al MEP (bien), pero **cuatro comentarios mienten** y **dos agregadores suman monedas distintas**.

#### D-4. La caja entra o no entra al total, según la pantalla

| superficie | ¿la caja suma al total? | evidencia |
|---|---|---|
| `snapshots.total_value` (cron) | **SÍ** | `compute_broker_value_usd` incluye la rama cash (`backend/snapshots_job.py:213`, `:285`) |
| `snapshots.holdings_json` | **NO** | `if p.get('is_cash'): continue` (`backend/snapshots_job.py:758`) |
| Total del Dashboard / pie por broker | **SÍ** | `computeBrokerValue` suma todos los lotes (`frontend/src/utils/valuation.js:744-751`) |
| Torta de distribución del Dashboard | **SÍ**, pero por una vía SEPARADA | `positionsForComposition = [...positionsForInsight, ...cashForComposition]` (`frontend/src/pages/Dashboard.jsx:414`) — `positionsForInsight` filtra el cash (`:303`) |
| `priceCoverage` (guard del snapshot) | **NO** | `const nonCash = positions.filter(p => !p.is_cash)` (`frontend/src/pages/Dashboard.jsx:441`) |
| `weight_pct` / concentración / top holdings | **NO** | `total_holdings_value` (`backend/main.py:22913-22932`); `backend/behavioral.py:982` |
| Torta del libro del asesor | **SÍ**, por una vía separada y con REGLA DISTINTA | `_advisor_positions_valued` excluye por SQL y `_advisor_cash_usd` la agrega aparte **descartando los saldos ≤ 0** (`backend/main.py:37292-37320`) |
| TWR | **NO** | *"holdings excluye el cash (`if p.get('is_cash'): continue`)"* (`backend/twr.py:26`) |

Consecuencia directa y verificable: **la suma de `holdings_json` de un snapshot NUNCA da `total_value` si el usuario tiene caja**, y la diferencia es exactamente el saldo.

#### D-5. El signo del saldo: retail lo cuenta, el asesor lo tira

- Retail: un saldo negativo se suma tal cual al patrimonio (todas las ramas cash de `valuation.js` / `snapshots_job.py` / `behavioral.py` usan `invested` sin filtro de signo), y `detect_cash_drag` incluso tiene un caso especial *"Cash neto negativo"* (`backend/behavioral.py:1194-1214`).
- Asesor: los tres lectores del libro descartan el negativo — `if v <= 0: continue` (`backend/main.py:37319`), `if usd > 0` (`backend/advisor_groups.py:236`), `if _usd > 0` (`backend/main.py:35498`).

O sea: **el mismo cliente vale distinto en su propia pantalla que en la del asesor** cuando tiene un broker en descubierto.

#### D-6. El nombre del activo de la caja: tres mapeos distintos

| escritor | mapeo |
|---|---|
| `backend/main.py:9779`, `:10076`, `:10168`, `_cash_asset_for_currency` (`:10664`) | `ARS → 'ARS'`, `USD → 'USD'`, resto → `'USDT'` |
| `backend/importing/persister.py:1038` (`_apply_cash_flow`) | `ARS → 'ARS'`, **todo lo demás → `'USDT'`** (nunca `'USD'`) |
| `backend/main.py:31044` (Wallbit) | siempre `'USD'` |

Un broker con `currency='USD'` (Schwab, Wallbit, Balanz Internacional) que reciba su primer depósito **por import** estrena una fila de caja llamada `'USDT'`; si lo recibe **por el modal**, se llama `'USD'`. El frontend parchea el display (`cashAssetLabel`, `frontend/src/utils/valuation.js:185-189`) solo para el caso `USDT` en un sub-broker `· USD` — **no** para un Schwab.

#### D-7. `invArs` de la caja incluye comisiones; `valueArs` no

En la rama de caja ARS del valuador canónico (`frontend/src/utils/valuation.js:626-640`):

```
const cashArs = p.invested || 0  // cash no tiene commissions
...
invArs: realCost,      // ← realCost = (p.invested||0) + (p.commissions||0)
valueArs: cashArs,     // ← sin comisiones
```

Si una fila de caja tiene `commissions != 0`, el P&L en **pesos** de ese broker sale `−commissions` mientras el P&L en **dólares** sale exactamente 0 (`investedUsd = valueUsd = cashUsd`). La rama USD (`:675-679`) no tiene el problema (usa `v = p.invested || 0` en los dos lados). El test que cubre esto (`frontend/src/utils/valuation.test.js:459-467`, *"Cash positions ignoran commissions"*) **solo prueba el caso USD**.

#### Lo que SÍ converge

- **[V] El tipo de cambio efectivo**: frontend (`valuation.js:634`), snapshot (`snapshots_job.py:222`), backend de análisis (`behavioral.py:445`) y la valuación del chat (`main.py:22884`) convierten la caja ARS por el MISMO dólar-MEP que las tenencias, y hay tests que lo pinnean (`frontend/src/utils/valuation.test.js:259-264`: *"cash también al MEP, no al blue"*).
- **[V] Valor = costo, P&L 0**: verificado en las 8 implementaciones de fila/total listadas (#37-#48). Único desvío: D-7.

---

### Zonas grises

1. **[V] `LIMIT 1` sin `ORDER BY` en TODOS los escritores.** `SELECT ... WHERE is_cash=1 LIMIT 1` aparece en `backend/main.py:9767`, `:9835`, `:10060`, `:10145`, `:10832`, `:10936`, `:13001`, `:24080`, `:24172`, `:24184`, `:24260`, `:30179`, `:31159` y `persister.py:1026`, `:1081`, `:1164`, `:1466`, `:1495`. Nada en el esquema impide dos filas de caja en el mismo broker (**no hay UNIQUE** sobre `(user_id, broker, is_cash)` — verificado en `backend/schema_pg.sql:1435-1451` y en el `.schema` de la base de dev). Si aparecieran dos, los escritores tocarían siempre una y los lectores con `SUM` mostrarían las dos. No encontré ningún chequeo de invariantes para esto (`backend/importing/invariantes.py` tiene `check_cash_moneda` pero no un check de unicidad).

2. **[V] `PUT /api/positions/{pid}` te deja editar el saldo sin tocar el capital aportado.** `backend/main.py:8571-8580` escribe `invested` de una fila `is_cash=1` sin ningún asiento en `monthly_entries`. El propio frontend documenta el efecto (*"subía el valor de la cartera sin subir el aportado, y Rendi lo leía como GANANCIA"*, `frontend/src/pages/Positions.jsx:4255-4262`) y por eso escondió el checkbox al crear — pero **dejó la acción "Editar posición" disponible en el menú de la fila de efectivo** (`frontend/src/pages/Positions.jsx:3710`). O sea: el agujero sigue abierto, solo se movió de puerta.

3. **[V] `cash_value` suma pesos con dólares.** `backend/main.py:32832-32855`. El comentario del propio código admite el defecto y decide no arreglarlo argumentando que *"nadie lo consume"* — pero la clave **sí viaja en el payload** (`"cash_value": cash_value`, `:32869`). Si mañana alguien la pinta, un usuario de IOL ve pesos rotulados como dólares. Mismo patrón, sin comentario que lo advierta, en `backend/importing/recompute_backfill.py:127`.

4. **[V] `check_cash_moneda` gatea por `quantity`, no por `invested`.** `backend/importing/invariantes.py:186`: `AND ABS(COALESCE(p.quantity,0))>0.005`. Pero la caja guarda el monto en `invested` y casi siempre tiene `quantity` NULL o 0 (ver "Dónde se persiste"). **[I] El chequeo entonces no dispara casi nunca en datos reales** — los tests que lo cubren (`backend/tests/test_invariantes.py:146-157`) crean las filas con `qty=100000`, que no es la forma en que las crea producción (`_pos(db, "Schwab", "ARS", "ARS", qty=100000, invested=0, is_cash=1)`). Inferido de comparar el WHERE del chequeo con los INSERT de los escritores.

5. **[V] El borrado de un DEPOSIT/DIVIDEND/INTEREST importado pierde plata en silencio si no hay fila de caja.** `backend/main.py:12998-13008`: `if cash:` … y si no hay fila, **no hay `else`**. Los demás caminos usan `_adjust_broker_cash`, que la crea. **[I]** Es un caso de borde (borrar un depósito de un broker cuya caja ya se borró), pero el resultado es que el `monthly_entries` se corrige y el saldo no.

6. **[V] La caja del padre y la del sibling `· USD` son la MISMA cuenta para el usuario y dos filas para el sistema.** El comentario de `backend/main.py:32835-32840` lo llama por su nombre: *"Hoy, en 'IOL', ya devuelve pesos crudos rotulados como dólares — un defecto PREEXISTENTE"*. `broker_pair` (`backend/importing/persister.py:99`) existe justo para unificar el par en el FIFO, pero **explícitamente NO para la caja**: *"para que el FIFO las NETEE … sin romper el cash (que sí queda per-broker)"* (`:104-105`).

7. **[V] El true-up de la foto es silencioso y puede ser enorme.** `build_cash_trueup_txs` (`backend/importing/tenencia.py:670-696`) pisa el saldo con el de la foto sin avisarle al usuario (*"Silencioso: el usuario no ve la diferencia, la foto manda"*). El chequeo `check_caja_concilia` (`backend/importing/invariantes.py:199-231`) documenta la magnitud medida en la base: *"215 ajustes de 129 usuarios en cuentas que SÍ tienen movimientos, con un ajuste promedio de ARS 1,28 M"*. Ese ajuste entra como DEPOSIT/WITHDRAW sintético → **mueve el capital aportado**, que es el denominador del rendimiento.

8. **[V] `reconcile-cash` imputa la diferencia al MES MÁS VIEJO del broker.** `backend/main.py:10083-10096`. Es deliberado (*"preserva cronología — el ajuste representa historia pre-CSV"*), pero significa que corregir hoy un saldo mal importado **reescribe el rendimiento de un mes de hace años**. Además usa `data.tc_blue` que manda **el cliente** (`:10100`) — a diferencia de `/api/cash/flow`, que desde un fix explícito resuelve el dólar en el servidor por la fecha (`backend/main.py:10192-10197`). Dos endpoints hermanos, dos criterios de FX.

9. **[V] El costo de una compra debita la caja del `cash_broker`, pero el `cash_health` del import se arma sobre `brokers_touched`.** El test `backend/tests/test_cash_health_cash_broker.py` documenta que ese set se llenaba solo con `tx.broker` y que por eso *"si la compra lo dejaba en rojo, el aviso no salía justo en la cuenta que quedó en rojo"*. El test existe (o sea, está arreglado), pero es el mismo tipo de desincronización que sigue viva entre el saldo y el replay (D-2).

10. **[V] `demo.js` valúa la caja por `quantity`.** `frontend/src/utils/demo.js:215-216`. En el fixture `quantity == invested` para las filas cash (`:109`, `:116`, `:122`), así que no se nota — pero es una definición del concepto distinta de la de producción, viviendo en el mismo repo, y ya hubo un bug con exactamente esta confusión (documentado en `frontend/src/pages/Insights.jsx:490-494`: *"antes leíamos `quantity` directamente y caía a 0"*).

11. **[V] El autodepósito puede quedar huérfano.** `_autodeposit_if_overdraw` (`backend/main.py:9809`) sube caja Y aportado. El borrado del depósito manual por la ruta `me-` lo detecta y **bloquea con un 409** (`backend/main.py:13052-13058`) — pero solo esa ruta. **[I]** No verifiqué que todas las rutas de borrado de posición reversen el autodepósito; el código dice que guarda `undo_meta_json` para eso (`backend/main.py:8586-8595`), y `_month_has_autodeposit` existe como guard, así que parece cubierto — pero es un mecanismo de dos patas que hay que reversar junto y no hay un invariante que lo verifique.

12. **[V] `positions.currency` queda NULL en casi todas las filas de caja.** Ninguno de los INSERT de caja de `main.py` ni de `persister.py` la setea (verificado sobre `:9782`, `:10078`, `:10170`, `:10864`, `persister.py:1041`, `:1102`, `:1105`). Toda la resolución de moneda de la caja depende entonces del **fallback por nombre de activo y de broker** (`_native_ccy`, `backend/behavioral.py:195-220`) o de `brokers.currency` en el JOIN. Es la misma clase de dependencia que el código ya identificó como causa de bugs (*"NO inferir la moneda solo por el nombre del broker"*, `backend/behavioral.py:203-204`).

13. **No encontrado:** ninguna noción de saldo *comprometido* / *no liquidado* / *a liquidar T+1*; ningún endpoint que devuelva "la caja" como recurso propio (siempre viaja embebida en `GET /api/positions`, `backend/main.py:8186-8195`, que hace `SELECT *` sin filtrar); ningún índice sobre `(user_id, broker, is_cash)` (`backend/schema_pg.sql:1965` solo declara `idx_positions_user ON positions(user_id)`); y ningún test end-to-end que compare el saldo vivo contra el replay del ledger.
