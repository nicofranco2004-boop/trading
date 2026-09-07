## Costo de adquisición, costo promedio y lotes FIFO

### Definición según el código

En Rendi **un "lote" es una fila de `positions`** — no hay tabla de lotes aparte. Cada COMPRA (importada o manual) inserta una fila nueva; una VENTA consume filas y las achica o las borra. El costo de adquisición de un lote es la columna `positions.invested`, y el costo **económico** que usa casi todo el sistema es `invested + commissions` [V] (`frontend/src/utils/valuation.js:552-554`, `backend/importing/persister.py:747`, `backend/snapshots_job.py:207-208`).

Cinco cosas que el código define de forma **no estándar** y conviene decir explícito:

1. **El costo y los ingresos salen de columnas distintas del archivo y nunca se reconcilian.** La compra toma el costo de `gross_amount` (la columna "monto" del extracto); la venta toma los ingresos de `unit_price × quantity` (la columna "precio" cruda). Está documentado como tesis verificada en el propio código: *"`gross_amount` no aparece NI UNA VEZ dentro de `_persist_sell_fifo`"* [V] (`backend/main.py:16566-16601`). Consecuencia declarada: un bono cotizado per-100 da `pnl = 99 × costo`.

2. **El FIFO no es FIFO puro sobre el pool.** Desde el "pool único" (2026-08-04) una venta consume PRIMERO todos los lotes de su misma moneda y solo después los de la otra, sin mirar `entry_date` [V] (`backend/importing/rebuild.py:379-384`). El propio comentario lo llama "LIMITACIÓN CONOCIDA — el orden dentro del día decide qué lote paga" [V] (`rebuild.py:367-375`).

3. **La moneda del lote define el costo, no la tenencia.** Un CEDEAR comprado en pesos y otro comprado por dólar-MEP son el MISMO activo y la misma cantidad; lo que cambia es en qué moneda está `invested` (`positions.currency`) [V] (`rebuild.py:340-343`).

4. **El "costo en dólares" de un lote en pesos es una preferencia de DISPLAY del frontend**, no un dato persistido. El toggle `costBasis` ('purchase' | 'today') decide si el costo en pesos se divide por `positions.tc_compra` o por el dólar de hoy [V] (`frontend/src/utils/valuation.js:263-269`, `frontend/src/pages/Config.jsx:690-726`). El backend **nunca** usa `tc_compra` para valuar: siempre divide por el MEP de hoy [V] (`backend/behavioral.py:475-480`).

5. **"Precio promedio" tiene DOS definiciones convivientes**: `positions.buy_price` (precio unitario del lote, que el importador muchas veces deja NULL) e `invested / quantity`. La grilla muestra una y el P&L calcula con la otra — hay un test dedicado a esa contradicción [V] (`backend/tests/test_costo_inconsistente.py:1-22`).

---

### Dónde se calcula

Ordenado: primero los motores que ESCRIBEN `positions`/`operations` (canónicos), después los valuadores y los derivados.

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `backend/importing/rebuild.py:232` | `_replay_asset` | **Motor FIFO canónico**: replaya TODO el historial confirmado del par (broker padre + `· USD`) y reconstruye lotes abiertos + ventas. Sobrescribe lo que escribió el persister. | (ver filas 2-8) | fuente |
| 2 | `backend/importing/rebuild.py:268-270` | `_replay_asset` (BUY) | Costo del lote nuevo | `unit = _num(reconciled_unit_price(ev["unit_price"], ev["quantity"], ev["gross_amount"], ev.get("asset_type")))` · `invested = _num(ev["gross_amount"]) if ev["gross_amount"] is not None else unit * qty` | fuente |
| 3 | `backend/importing/rebuild.py:315-322` | `_replay_asset` (SELL) | Parte el pool en lotes de la moneda de la venta vs la otra | `_same = [l for l in lots if (l["currency"] or currency) == currency]` · `oversell_same = qty_to_sell - _same_total` | fuente |
| 4 | `backend/importing/rebuild.py:376-384` | `_replay_asset` (pool único) | Decide qué lotes paga la venta y cuánto se "fabrica" | `spill_qty = min(max(0.0, oversell_same), _other_total)` · `_consume_from = list(_same)` · `if spill_qty > _EPS: _consume_from = _consume_from + _other` · `seed_qty = max(0.0, oversell_same) - spill_qty` | fuente |
| 5 | `backend/importing/rebuild.py:325-336` | `_seed` (dentro de `_replay_asset`) | Lote SEMILLA "history-as-truth": si no hay nada que consumir, fabrica un lote **al precio de venta** ⇒ P&L 0 | `"qty": qty, "invested": qty * exit_price, "buy_price": exit_price` | fuente |
| 6 | `backend/importing/rebuild.py:413` | `_replay_asset` | Cost basis consumido por chunk (incluye comisión de compra) | `base_invested = (lot["invested"] or 0) + pos_buy_commissions` · `entry_invested = base_invested * ratio` (`:444`) | fuente |
| 7 | `backend/importing/rebuild.py:415-442` | `_replay_asset` cross-currency | Convierte el costo del lote a la moneda de la venta | lote USD → venta ARS: `base_invested = base_invested * (tc_venta or tc_blue)` · lote ARS → venta USD: `base_invested = base_invested / (_pfx or tc_blue)` con `_pfx = fx_for_date(conn, lot["entry_date"])` | fuente |
| 8 | `backend/importing/rebuild.py:451-471` | `_replay_asset` | P&L y costo-USD de la venta | ARS: `pnl_ars_chunk = exit_price * take - (entry_invested or 0) - chunk_commission` ; `pnl_usd = pnl_ars_chunk / tc_venta` ; `invested_usd = (entry_invested or 0) / tc_venta` — USD: `cost = entry_invested ... ; pnl_usd = (exit_price * take) - cost - chunk_commission` | fuente |
| 9 | `backend/importing/rebuild.py:490-507` | `_replay_asset` | Achica el lote parcialmente consumido | `lot["invested"] = round((lot["invested"] or 0) * remaining_ratio, 6)` · `lot["commissions"] = round(pos_buy_commissions * remaining_ratio, 6)` | fuente |
| 10 | `backend/importing/persister.py:563` | `_persist_buy` | Compra incremental (durante el import, antes del rebuild) | `invested = float(tx.gross_amount) if tx.gross_amount is not None else (unit * qty)` (`:567`) | fuente |
| 11 | `backend/importing/persister.py:601` | `_persist_sell_fifo` | Venta FIFO incremental. **Sin spill cross-currency a propósito** (lo hace el rebuild) | `same = [p for p in rows if _nccy(dict(p)) == currency]` · `return same if same else rows` (`:633-640`) | fuente |
| 12 | `backend/importing/persister.py:747-774` | `_persist_sell_fifo` | Mismo cost basis y misma conversión cross-currency que el rebuild | `base_invested = (p["invested"] or 0) + pos_buy_commissions` · `base_invested = base_invested * (tc_venta or tc_blue)` · `base_invested = base_invested / (purchase_fx or tc_blue)` · `entry_invested = base_invested * ratio` | fuente |
| 13 | `backend/importing/persister.py:676-696` | `_persist_sell_fifo` | Seed lot cuando la venta excede lo disponible | `missing_qty = qty_to_sell - total_avail` · `seed_invested = missing_qty * seed_price` con `seed_price = unit_eff` | fuente |
| 14 | `backend/importing/persister.py:492` | `reconciled_unit_price` | Guard de escala per-100 (bonos) y VCP-1000 (FCI). **Solo corrige el PRECIO, nunca el monto** | `ratio = (up * q) / ga` · `if abs(ratio / _ESCALA_PER_100 - 1) <= _TOL_ESCALA: return ga / q` | fuente |
| 15 | `backend/main.py:11149` | `sell_position_fifo` (`POST /positions/sell`) | **Venta MANUAL**. Misma aritmética, pero NO hace spill: una venta en USD consume solo lotes USD y se rechaza si no alcanzan | `_same_ccy = [p for p in all_positions if _native_ccy(dict(p)) == sell_ccy]` · `positions = _same_ccy if _same_ccy else all_positions` (`:11201-11202`) | fuente |
| 16 | `backend/main.py:11235-11252` | `sell_position_fifo` | Cost basis del chunk manual | `base_invested = ((p["invested"] or 0) + pos_buy_commissions)` · `base_invested = base_invested * (data.tc_venta or cur_blue)` · `base_invested = base_invested / (purchase_blue or cur_blue)` · `entry_invested = base_invested * ratio` | fuente |
| 17 | `backend/main.py:11287-11296` | `sell_position_fifo` | P&L manual | `pnl_ars_chunk = data.exit_price * take - (entry_invested or 0) - chunk_commission_native` ; `pnl_usd = pnl_ars_chunk / tc_venta` — USD: `cost = entry_invested if entry_invested is not None else ((buy_price or 0) * take)` | fuente |
| 18 | `backend/main.py:8198` | `_manual_position_cost` | Costo cash de un alta manual (débito de cash + undo) | `cost = invested if invested is not None else (buy_price or 0) * (quantity or 0)` · `return (cost or 0) + (commissions or 0)` | fuente |
| 19 | `backend/main.py:8206` | `_insert_manual_position` | Alta manual: guarda `invested`, `buy_price`, `commissions`, `tc_compra` (auto-completado con `fx_for_date` si el lote es ARS y el usuario lo dejó vacío) | `tc_compra = _fx.fx_for_date(conn, entry_date)` (`:8230`) | fuente |
| 20 | `backend/main.py:8334` / `:8388-8413` | `_edit_position_group` (`PATCH /positions/group`) | Cambiar el "precio promedio" de N lotes **escalando** cada uno (preserva la forma del FIFO) | `k = (float(p.avg_price) * total_qty) / total_inv` · `new_inv = float(l["invested"] or 0) * k` · `new_price = float(l["buy_price"]) * k` | fuente |
| 21 | `backend/main.py:10587` | `_amortize_position_fifo` | Amortización de bonos: **FIFO por lote**, reduce `quantity`, `invested` y `commissions` | `ratio = take / lot_qty` · `new_invested = (lot['invested'] or 0) * (1 - ratio)` · `invested_taken = (lot['invested'] or 0) * ratio` | fuente |
| 22 | `backend/main.py:10549` | `_compute_amort_cost_basis_fifo` | Versión READ-ONLY del anterior — calcula `cost_basis_consumed` sin tocar los lotes. **NO suma comisiones** | `total_consumed += (lot['invested'] or 0) * ratio` | fuente |
| 23 | `backend/main.py:10507-10508` | endpoint `bond_cashflow` | Ganancia realizada de una amortización | `realized_gain = round(net_amount - cost_basis_consumed, 6)` | fuente |
| 24 | `backend/importing/maturity.py:386-400` | `sweep_bond_amortizations` | Amortización automática de bonos AR: reducción **PROPORCIONAL, no FIFO**, sobre todos los lotes import-linked | `factor = target / current` · `new_inv = (l["invested"] or 0) * factor` · `new_com = (l["commissions"] or 0) * factor` | fuente |
| 25 | `backend/importing/recompute_backfill.py:155-166` | `bond_per100_factor` | Detecta un cost basis de bono guardado per-100 y lo lleva a per-1 | `ratio = unit_cost / market_per1` · `return 0.01 if 10.0 < ratio < 1000.0 else 1.0` | fuente |
| 26 | `backend/importing/recompute_backfill.py:167-222` | `normalize_bond_units` | Aplica ese factor a `invested` y `buy_price` (con guard anti-distressed: `usd_cost < 3.0` → no tocar) | `unit_cost = (inv / qty) if inv else (r["buy_price"] or 0)` · `new_inv = round((inv or 0) * factor, 6)` | fuente |
| 27 | `backend/importing/recompute_backfill.py:226-257` | `normalize_usd_commissions` | Comisión en pesos guardada en un lote USD infla el cost basis → la convierte | `if inv > 0 and com > inv and com >= 100.0: ... round(com / tc_blue, 6)` | fuente |
| 28 | `backend/main.py:8944-8945` | `POST` ajuste de split | Split: multiplica cantidad y divide `buy_price`. **No toca `invested`** (correcto: el costo total no cambia) | `new_qty = float(row["quantity"] or 0) * combined` · `new_buy = (float(row["buy_price"]) / combined)` | fuente |
| 29 | `backend/importing/tenencia.py:598-643` | `build_tenencia_seed_txs` | Foto de tenencia: fabrica COMPRAS sintéticas al **precio de la foto** (P&L 0 en la apertura) | `unit_price=h.price_per1, gross_amount=round(gap * h.price_per1, 4)` | fuente |
| 30 | `backend/main.py:29975-29989` | confirm de foto de tenencia | Herencia del **costo unitario** de la partición hermana para bonos amortizantes | `unit = (oth_inv / oth_q) if oth_q > 1e-9 else 0.0` · `h.price_per1 = unit` · fallback `h.price_per1 /= _mep` | fuente |
| 31 | `backend/importing/seed.py:334-343` | wizard "Estado inicial" | El usuario declara `cost_basis_unit` por activo → compra sintética | `invested = a["qty"] * a["cost_unit"]` · `gross_amount=round(invested, 4)` | fuente |
| 32 | `frontend/src/utils/valuation.js:543` | `valuePositionLot` | **Valuador por lote canónico del frontend** (6 ramas). Costo económico y costo-display | `const comm = p.commissions \|\| 0` · `const realCost = (p.invested \|\| 0) + comm` (`:552-554`) · `const invUsd = realCost / costBasisRate(p, cedearRate, costBasis)` (`:574`, `:650`) | fuente |
| 33 | `frontend/src/utils/valuation.js:263` | `costBasisRate` | **Chokepoint del divisor del costo**: decide si el costo en pesos va al `tc_compra` del lote o al dólar de hoy | `return (costBasis === 'purchase' && p?.tc_compra > 0) ? p.tc_compra : currentRate` | fuente |
| 34 | `frontend/src/utils/valuation.js:868` | `avgCostUsdPerUnit` | Costo promedio por unidad en USD, **por lote** (multi-lote independiente del orden). **SIN comisiones a propósito** | `cost += costIsPesos ? inv / costBasisRate(l, rate, costBasis) : inv` · `return cost > 0 ? cost / qty : null` | fuente |
| 35 | `frontend/src/utils/valuation.js:293` | `pesoLotUsd` | Lote en pesos alojado en cuenta USD | `const realCost = (p.invested \|\| 0) + (p.commissions \|\| 0)` · `const investedUsd = realCost / costBasisRate(p, tcCedear, costBasis)` | fuente |
| 36 | `frontend/src/utils/valuation.js:338` | `usdLotValue` | Lote de costo YA en dólares dentro de un broker ARS (no se divide por el MEP) | `const investedUsd = (p.invested \|\| 0) + (p.commissions \|\| 0)` | fuente |
| 37 | `frontend/src/utils/valuation.js:360` | `valueEquityLot` | Valuador por lote de "Calidad de cartera". Distingue costo-display (`investedUsd`) de costo-guard (`guardCost`) | `investedUsd = invested / costBasisRate(p, cedearRate, costBasis)` · `guardCost = invested / cedearRate` | fuente |
| 38 | `frontend/src/utils/valuation.js:740` | `computeBrokerValue` | Suma de `valuePositionLot` sobre los lotes crudos del broker | `invested += r.investedUsd` | consumidor de #32, fuente de los totales |
| 39 | `frontend/src/pages/Positions.jsx:1134` | `_buildAgg` | Fila agregada por ticker: suma cantidades y costos, y **calcula un buy_price agregado** | `buy_price: (multiCcy \|\| !(totalQty > 0)) ? null : totalInv / totalQty` · `_lots: lots` | fuente (vista) |
| 40 | `frontend/src/pages/Positions.jsx:1248` | `routedInvUsd` | Costo USD de una fila agregada, **sumando lote por lote** (cada uno a su `tc_compra`) | `lots.reduce((s, l) => s + ((l.invested \|\| 0) + (l.commissions \|\| 0)) / costBasisRate(l, rate, costBasis), 0)` | fuente (vista) |
| 41 | `frontend/src/pages/Positions.jsx:1321-1366` | `calcARS` | Costo y P&L de una fila en broker ARS | `const realCostArs = (p.invested \|\| 0) + (p.commissions \|\| 0)` · `const invUsd = routedInvUsd(p, tcCedear)` | fuente (vista) |
| 42 | `frontend/src/pages/AssetDetail.jsx:34` | `valueLot` | Sexta copia del valuador por lote (ficha de activo) | `const invested = cashInvested + (p.commissions \|\| 0)` · `const investedUsd = invested / costBasisRate(p, tcCedear, costBasis)` | fuente (vista) |
| 43 | `frontend/src/pages/PositionsMobile.jsx:775-784` | memo por lote | Costo-display mobile | `const investedUsdDisplay = !priceTrusted ? investedUsd : (isAR && costInUsd(p)) ? invested * f : isAR ? (invested / costBasisRate(p, tcValuacion, costBasis)) * f : ...` | fuente (vista) |
| 44 | `frontend/src/pages/PositionsMobile.jsx:2810` | `avgPriceUsdDe` | Precio promedio USD mobile (espejo del desktop) | `return p.buy_price ?? (p.invested ? p.invested / p.quantity : null)` (rama broker USD) | fuente (vista) |
| 45 | `frontend/src/components/fundamentals/DetailPortfolioBlocks.jsx:26-39` | `lotCostUsd` | Costo USD de un lote para los bloques de "Calidad de cartera" | `if (costInPesos(p) \|\| isAR) return invested / costBasisRate(p, tc, costBasis)` | fuente (vista) |
| 46 | `backend/behavioral.py:391` | `_position_value_usd` | Valuador por posición del backend. **Con `prices={}` y `honor_override=False` devuelve el COST BASIS** | `invested_native = float(p.get("invested") or 0)` (`:425`) · `return invested_native / rate_holdings` (`:478`) | fuente |
| 47 | `backend/snapshots_job.py:158` | `compute_broker_value_usd` | Port Python de `computeBrokerValue` para el cron de snapshots | `real_cost = (p.get('invested') or 0) + comm` (`:208`) · `inv_usd = real_cost / cedear_rate` (`:270`) | fuente |
| 48 | `backend/scripts/backfill_historical_mtm.py:265` | `_holdings_asof` | Tenencia histórica: **costo PROMEDIO PONDERADO sobre `import_normalized_tx`, sin FIFO** | `avg_cost = (r["buy_amt"] / buy_qty) if buy_qty > 0 else 0` · `"invested": avg_cost * qty` con `qty = Σ BUY − Σ SELL` | fuente |
| 49 | `backend/scripts/backfill_historical_mtm.py:154-261` | `_tenencia_no_vista` | Costo de lo que el replay no ve (posiciones manuales + ops abiertas) | `usd = _a_usd(q * pe, r["currency"], r["fx_to_usd"])` con `pe = entry_price` | fuente |
| 50 | `frontend/src/utils/assetPnl.js:139` | `computePnlByKey` | **Despeja** el costo de una venta cerrada del par (pnl_usd, pnl_pct) — no lo lee de ninguna columna | `const cost = pnl / (pct / 100)` (`:222`) · abiertas: `const cost = (p.value_usd ?? 0) - p.pnl_usd` (`:158`) | fuente |
| 51 | `backend/main.py:37409` / `:37511` | `_advisor_realized_raw` | Espejo backend del anterior, para el libro del asesor | `cost = (pnl / (float(pct) / 100)) if (pct is not None and float(pct) != 0) else None` | fuente |
| 52 | `backend/ai/builders/position_lots.py:69-73` | `build` (topic `position.lots`) | Precio promedio de compra para la IA, sobre `operations` con `op_type='Compra'` | `total_buy_value += entry * qty` · `avg_buy_price = (total_buy_value / total_buy_qty) if total_buy_qty > 0 else None` | fuente |
| 53 | `backend/ai/builders/position.py:84` | `build` (topic `position`) | Precio promedio para la IA, sobre `positions` | `avg_price = (invested / qty) if (qty > 0 and currency != "MIXED") else None` | fuente |
| 54 | `backend/ai/builders/insights.py:433-440` | `build` | Costo USD por posición para el packet de insights. **Sin comisiones** (ni las selecciona) | `invested = float(p.get("invested") or 0)` · `cost_usd = invested / _rate if _rate > 0 else invested` | fuente |

---

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `frontend/src/pages/Positions.jsx:2253` | Cartera desktop, tabla broker ARS | columna **"Precio prom."** |
| `frontend/src/pages/Positions.jsx:2315-2319` | ídem | `avgPriceArs` / `avgPriceUsdDisp` (`routedAvgPriceUsd`) |
| `frontend/src/pages/Positions.jsx:2572` | Cartera desktop, tabla broker USD | columna **"Precio prom."** |
| `frontend/src/pages/Positions.jsx:2609-2614` | ídem | `p.buy_price ?? (p.invested / p.quantity)` salvo que algún lote tenga costo en pesos |
| `frontend/src/pages/Positions.jsx:1591-1599` | Cartera, totales del pie | **"Invertido"** (vía `computeBrokerValue`) |
| `frontend/src/pages/Positions.jsx:1942` | Cartera | toggle **"desglosar cada compra (lote)"** |
| `frontend/src/pages/Positions.jsx:3536` | modal Editar posición entera | **"Precio promedio (ARS/USD) — hoy …"** |
| `frontend/src/pages/Positions.jsx:3565` | ídem, preview | columnas **"Antes" / "Después"** por lote |
| `frontend/src/pages/Positions.jsx:2394-2405` | Cartera | badge **"TC?"** (`lotMissingPurchaseRate`) |
| `frontend/src/components/TcMissingBadge.jsx:12` | Cartera / mobile | badge **"TC?"** |
| `frontend/src/pages/AssetDetail.jsx:285-320` | ficha del activo | sección **"Lotes abiertos · orden FIFO"**, columnas Fecha / Cantidad / **Costo** / P&L, con la marca **"próximo"** en el primero y el texto *"el más viejo se vende primero"* |
| `frontend/src/pages/AssetDetail.jsx:163` | ídem | orden: `.sort((a,b) => (a.entry_date \|\| '').localeCompare(b.entry_date \|\| ''))` |
| `frontend/src/pages/AssetDetail.jsx:166` | ficha del activo | `avgCostUsd = qty > 0 ? investedUsd / qty : null` |
| `frontend/src/pages/PositionsMobile.jsx:859`, `:989` | Cartera mobile | `avgPriceUsd` (fila por lote y fila agregada) |
| `frontend/src/pages/PositionDetailMobile.jsx:124`, `:148`, `:187` | detalle de posición mobile | `investedUsdDisplay` |
| `frontend/src/pages/Dashboard.jsx:211` | Dashboard | **"Invertido"** / P&L no realizado |
| `frontend/src/pages/Insights.jsx:526` | Análisis | total invertido |
| `frontend/src/pages/FirstInsight.jsx:92` | primer insight | `computeBrokerValue(..., costBasis)` |
| `frontend/src/pages/HomeMobile.jsx:111`, `:128` | Home mobile | totales |
| `frontend/src/components/MonthlySummary.jsx:288-296` | Resumen mensual | `pnl_unrealized` persistido (usa `pnlArs/tc`, **no** el modo `costBasis`) |
| `frontend/src/components/operations/TradesTable.jsx:148` | Operaciones | columna **"Entrada"** = `op.entry_price` crudo |
| `frontend/src/pages/Operations.jsx:153`, `:169` | Operaciones, form de edición | campo **"Precio entrada"** (se re-escribe crudo a la DB) |
| `frontend/src/components/BondCashflowModal.jsx:424` | modal de cobranza de bono | *"el sistema reduce automáticamente la quantity y el cost basis del lote (FIFO)"* |
| `frontend/src/pages/Positions.jsx:488-548` | Cartera, filas de bono | `pnlContribution = amt - cost_basis_consumed` (aporte al P&L de una amortización) |
| `backend/main.py:13333` (`/api/export/operations.csv`) | export para el contador | columnas **"Precio entrada" / "Precio salida" / "P&L USD"** |
| `backend/main.py:13385` (`/api/export/positions.csv`) | export | columnas **"Costo invertido" / "Comisiones" / "TC compra (ARS)"** |
| `frontend/src/pages/guia/InsightsYReportes.jsx:127`, `:233-236` | Guía | *"costo base FIFO"*, *"Cada venta se matchea con FIFO"* |
| `frontend/src/components/guide/ReturnsDiagram.jsx:70` | Guía | *"FIFO arma la ganancia"* |
| `frontend/src/pages/Landing.jsx:470-471`, `:646`, `:674` | Landing | *"FIFO automático"*, *"P&L FIFO real en USD, listo para AFIP"* |
| `frontend/src/pages/blog/articles/FifoCedearsArgentina.jsx` | Blog SEO | artículo entero sobre FIFO vs LIFO vs promedio |
| `frontend/src/components/landing/FAQ.jsx:39`, `:46` | FAQ | *"FIFO automático para AFIP"* |
| `frontend/src/pages/Terminos.jsx:138` | Términos | *"Calcula P&L realizado y no realizado en USD con criterio FIFO"* |
| `frontend/src/data/planCatalog.js:94` | catálogo de planes | *"Tax helper AFIP: cálculo FIFO + reporte fiscal"* |
| `backend/ai/builders/position.py:133-135` | packet IA `position` | `avg_price`, `invested_usd`, `lots_count` |
| `backend/ai/builders/position_lots.py:91-99` | packet IA `position.lots` | `avg_buy_price`, `pattern` (`averaging_down`/`averaging_up`/`mixed`), `lots[:15]` |
| `backend/ai/builders/position_chart.py:45` | packet IA | `avg_price` |
| `backend/ai/builders/dashboard.py:66-73`, `dashboard_top_holdings.py:89-96`, `insights_attribution.py:100` | packets IA | `invested_usd` vía `_position_value_usd(p, {}, ..., honor_override=False)` |
| `backend/behavioral.py:754-760` | Comportamiento | `detect_averaging_down` lee `entry_price` de `operations` con `op_type` que contenga "compra"/"buy" |
| `backend/reporting/builder.py:238-244` | Reportes | trae `entry_price`/`exit_price` de `operations` |
| `frontend/src/utils/bookComposition.js:216` | libro del asesor | `realizedToOps` inyecta `cost_usd` explícito |

---

### Dónde se persiste

| tabla | columna | qué guarda | dónde se escribe |
|---|---|---|---|
| `positions` | `invested` | **el costo de adquisición del lote**, en la MONEDA NATIVA del lote | `persister.py:585-593`, `rebuild.py:743-751`, `main.py:8232-8238` (manual), `main.py:8404-8413` (edición grupal), `main.py:10639-10647` (amortización), `maturity.py:400-406` (sweep), `recompute_backfill.py:220-222` |
| `positions` | `buy_price` | precio unitario del lote. **Frecuentemente NULL en imports** (`Positions.jsx:644-648` lo dice explícito) | mismos sitios |
| `positions` | `commissions` | comisiones de compra, parte del costo económico | ídem |
| `positions` | `currency` | moneda del costo ('ARS'/'USD'/NULL legacy). Es lo que parte el pool FIFO | `persister.py:571-575`, `main.py:8216-8221` |
| `positions` | `tc_compra` | TC ARS/USD de la compra. **Solo lo usa el frontend**, en modo `costBasis='purchase'` | `persister.py:578-582`, `rebuild.py:701` (`_lot_tc_compra`), `main.py:8227-8230`, `main.py:8416-8428` |
| `positions` | `entry_date` | fecha del lote = clave de orden FIFO (`ORDER BY COALESCE(entry_date,'9999-12-31') ASC, id ASC`) | ídem |
| `positions` | `split_adjusted_through` | watermark de splits aplicados (evita doble ajuste de `quantity`/`buy_price`) | `main.py:8950-8952` |
| `operations` | `entry_price` | precio del lote consumido, **en la moneda en que se COMPRÓ** | `persister.py:820-830`, `rebuild.py:757-768`, `main.py:11310-11321` |
| `operations` | `entry_date` | fecha del lote consumido | ídem |
| `operations` | `currency` + `fx_to_usd` | moneda de la VENTA y TC con el que se llevó el P&L a USD. `fx_to_usd` es NULL en ventas USD a propósito | ídem |
| `operations` | `cost_basis_consumed` | costo consumido por una **amortización** de bono | `main.py:10480-10486` |
| `operations` | `undo_meta_json` | foto del lote ANTES de consumirlo (`quantity`, `invested`, `buy_price`, `commissions`, `tc_compra`, `consumed`) — es lo único que permite deshacer una venta | `main.py:11333-11365` |
| `import_normalized_tx` | `gross_amount`, `unit_price`, `quantity`, `fees`, `tc_compra` | el **log de eventos reproducible**: la fuente desde la que el rebuild reconstruye TODO el FIFO | `persister.py` / `pipeline.py`; se re-escala en `main.py:8404-8413` |
| `snapshots` | `total_invested` | costo total de la cartera al cierre del día | `snapshots_job.py:778-791` |
| `futures_positions` | `entry_price` | precio de entrada de un futuro (no pasa por FIFO: es una posición única) | `main.py:12247` |

**Nunca se persiste**: el costo-USD de un lote (se calcula al vuelo en cada render, con `costBasisRate`), ni el "costo consumido" de una VENTA — `operations.cost_basis_consumed` existe pero **está 100% NULL en las filas reales**, y por eso tanto el frontend como el backend lo despejan de `pnl_usd / (pnl_pct/100)` [V] (`frontend/src/utils/assetPnl.js:18-19`, `frontend/src/utils/bookComposition.js:210`, `backend/main.py:37436-37442`).

---

### ⚠️ Implementaciones divergentes

**NO convergen.** Hay al menos **cuatro motores FIFO** y **siete valuadores de cost basis** distintos, más dos definiciones de "precio promedio". Lado a lado:

#### A. Los cuatro motores FIFO

| | `rebuild._replay_asset` | `persister._persist_sell_fifo` | `main.sell_position_fifo` | `_amortize_position_fifo` |
|---|---|---|---|---|
| archivo:línea | `backend/importing/rebuild.py:232` | `backend/importing/persister.py:601` | `backend/main.py:11149` | `backend/main.py:10587` |
| cuándo corre | después de cada import (pisa lo del persister) | durante el import (estado transitorio) | venta manual del usuario + chat IA | cobro de amortización de bono |
| universo de lotes | `import_normalized_tx` confirmadas, del PAR de brokers | `positions` del PAR de brokers | `positions` del PAR de brokers | `positions` de **UN SOLO broker** (`WHERE broker=?`, `main.py:10609`) |
| spill cross-currency | **SÍ** (pool único) | **NO** — explícitamente desactivado (`persister.py:634-639`) | **NO** — se rechaza la venta (`main.py:11190-11196`) | n/a |
| orden | `_same` primero, después `_other`, sin mirar `entry_date` (`rebuild.py:379-381`) | SQL `ORDER BY entry_date, id` sobre lotes de la misma moneda | ídem | SQL `ORDER BY entry_date, id` |
| comisiones en el costo | **SÍ** (`rebuild.py:413`) | **SÍ** (`persister.py:747`) | **SÍ** (`main.py:11235`) | **NO** en `_compute_amort_cost_basis_fifo` (`main.py:10584`); **SÍ** las reduce en `_amortize_position_fifo` |
| TC del costo cruzado ARS→USD | `fx_for_date(entry_date)` si v2, si no `blue_for_date` (`rebuild.py:436-441`) | `fx_for_date(entry_date)` si v2, si no `blue_for_date` (`persister.py:769-771`) | **siempre `blue_for_date`**, sin gate v2 (`main.py:11249`) | n/a |
| si falta stock | fabrica lote semilla al precio de venta | fabrica lote semilla al precio de venta | **HTTP 400**, no fabrica nada (`main.py:11205-11206`) | amortiza lo que haya |

**Qué pantalla ve cuál**: todo lo importado ve el resultado de `rebuild` (que sobrescribe al persister); las ventas hechas desde el botón "Registrar venta" de Cartera y desde el Coach IA ven `sell_position_fifo`; las amortizaciones de bonos ven `_amortize_position_fifo`. Los tres escriben a la MISMA tabla `operations`, así que Reportes / Operaciones / el CSV para el contador mezclan filas de los tres criterios sin ninguna marca que las distinga.

Divergencia adicional dentro del mismo par: `sweep_bond_amortizations` (`maturity.py:386-400`) reduce los lotes **proporcionalmente, no FIFO**, y lo dice: *"Reducción PROPORCIONAL (no FIFO)"*. Convive con `_amortize_position_fifo`, que sí es FIFO, sobre los mismos bonos.

#### B. Los valuadores de cost basis (el mismo lote, siete números posibles)

| implementación | comisiones | `tc_compra` (modo purchase) | lote ARS en broker USD | lote USD en broker ARS |
|---|---|---|---|---|
| `valuation.js:543` `valuePositionLot` (canónico frontend) | SÍ | SÍ | rama 2: `/cedearRate` | rama 3: sin dividir |
| `valuation.js:360` `valueEquityLot` | SÍ | SÍ | SÍ | SÍ |
| `AssetDetail.jsx:34` `valueLot` | SÍ | SÍ | SÍ | SÍ |
| `PositionsMobile.jsx:775` | SÍ | SÍ | SÍ | SÍ |
| `PositionDetailMobile.jsx:124-187` | SÍ | SÍ | SÍ | SÍ |
| `snapshots_job.py:158` `compute_broker_value_usd` | SÍ | **NO** (siempre dólar de hoy) | **NO EXISTE LA RAMA** — un lote `currency='ARS'` en broker USD se suma como si fueran dólares | SÍ (`_cost_in_usd`, `:199-203`) |
| `behavioral.py:391` `_position_value_usd` | **NO** (`invested_native = p["invested"]`, `:425`) | **NO** | vía `_native_ccy` → `/rate_holdings` | vía `_native_ccy` |
| `ai/builders/insights.py:433` | **NO** (ni selecciona la columna, `:337`) | **NO** | vía `_native_ccy` | vía `_native_ccy` |
| `avgCostUsdPerUnit` (`valuation.js:868`) | **NO, a propósito** (docstring `:857-859`: *"SIN comisiones, igual que la columna en pesos"*) | SÍ, por lote | SÍ | SÍ |

Consecuencia concreta: la columna **"Precio prom."** de Cartera y la columna **"Invertido"** de la MISMA fila no son consistentes entre sí — una excluye las comisiones y la otra las incluye. Y el snapshot nocturno (`total_invested`) puede diferir del "Invertido" que el usuario ve en pantalla por dos motivos independientes: el modo `costBasis` (que el cron no conoce) y la rama faltante del lote-en-pesos-en-cuenta-USD.

#### C. Las dos definiciones de "precio promedio"

| | fórmula | dónde |
|---|---|---|
| (1) `positions.buy_price` | lo que grabó el importador/el usuario | `Positions.jsx:2614` (tabla USD), `PositionsMobile.jsx:2815`, `EditGroupModal` preview (`Positions.jsx:3565`) |
| (2) `invested / quantity` | derivado | `_buildAgg` (`Positions.jsx:1170`), `EditGroupModal` `avgNow` (`Positions.jsx:3496`), `ai/builders/position.py:84`, fallback de (1) |
| (3) `Σ(invested_i / tc_i) / Σqty_i` | ponderado por lote, en USD | `avgCostUsdPerUnit` (`valuation.js:868`) |
| (4) `Σ(entry_price × qty) / Σqty` sobre `operations` con `op_type='Compra'` | promedio de las OPERACIONES, no de los lotes | `ai/builders/position_lots.py:69-73` |

(1) y (2) se contradicen cuando el dato viene torcido — es exactamente el caso NFLX documentado en `backend/tests/test_costo_inconsistente.py:1-22`: la grilla mostraba compra ARS 2.473 y el P&L calculaba con un costo de ARS 4.935/unidad, dando −48% en una fila que decía estar ganando.

(4) tiene un problema distinto: **`operations` prácticamente no tiene filas con `op_type='Compra'`** — las compras crean `positions`, no `operations`. El único INSERT de operaciones que encontré con ese tipo está en un test (`backend/tests/test_reset_data.py:51`) y en fixtures. Los tres consumidores (`position_lots.py:69`, `position.py:110`, `position.py:124`) filtran por ese tipo, así que `avg_buy_price`, `days_held` y `lots_count` del packet de IA quedan en `None`/`0` para el flujo normal [I — inferido de que no encontré ningún `INSERT INTO operations` con `op_type='Compra'` fuera de tests; grep sobre todo `backend/`].

#### D. El costo de una venta cerrada: tres fuentes que no coinciden

| fuente | fórmula | consumidor |
|---|---|---|
| despejado del par | `pnl_usd / (pnl_pct/100)` | `assetPnl.js:222`, `main.py:37511` (libro del asesor) |
| explícito | `cost_usd` calculado en el backend | solo el libro del asesor (`bookComposition.js:232`) |
| `entry_price × quantity` | moneda nativa del lote | `backfill_historical_mtm.py:251-256`, `admin/diagnose-sell-fx` |
| `cost_basis_consumed` | columna real | **NULL en producción** — descartada por los tres lectores |

#### E. El costo histórico: promedio ponderado, no FIFO

`backend/scripts/backfill_historical_mtm.py:265` reconstruye la tenencia de un mes cerrado como `qty = ΣBUY − ΣSELL` y `invested = (Σbuy_amt / Σbuy_qty) × qty` [V] (`:293-303`). Eso es **costo promedio ponderado**, no FIFO, y no coincide con lo que el rebuild dejó en `positions` salvo por casualidad. Alimenta `snapshots` con `source='mtm_backfill'`, que después consume Reportes.

---

### Zonas grises

1. **`entry_price` sirve a dos amos y no puede a los dos.** En una venta cruzada `entry_price` está en la moneda de COMPRA y `exit_price` en la de VENTA, en la misma fila, sin ningún campo que lo diga. Caso real citado en el repo: GD30 comprado a 0,3430 USD y vendido a 68,6415 ARS, que la app muestra como "US$0,34 → US$68,64" con −82% [V] (`backend/tests/test_entry_price_moneda.py:1-40`). El arreglo obvio se implementó, se midió y se revirtió el mismo día porque rompe `/api/admin/diagnose-sell-fx`, que usa justamente esa asimetría como discriminador. Los tests quedan en `expectedFailure` a propósito. **Esto contamina el CSV que el usuario le manda al contador** (`main.py:13366-13376`, columnas "Precio entrada"/"Precio salida").

2. **El orden de las filas del archivo decide la plata.** `import_normalized_tx.date` no tiene hora (`schema.py:205`: `date: str  # YYYY-MM-DD`), así que todas las operaciones de un día empatan y el desempate lo fija `n.id ASC` = el orden en que llegó la fila [V] (`rebuild.py:367-373`, `rebuild.py:556-559`). Medición del propio repo: sobre un export real de IOL de 5.002 ventas, permutando filas dentro de cada día, **la P&L total va de 4.725,92 a 21.577,00 USD** [V] (`backend/tests/test_orden_filas_pool.py:24-27`). Los tests están en rojo a propósito.

3. **El costo sale de una columna y los ingresos de otra.** Documentado como tesis verificada en `main.py:16572-16585`. Los parsers que reenvían el precio crudo (`ieb`, `balanz`, `balanz_movimientos`, `ppi`, `bullmarket`) son vulnerables; los que derivan `precio = monto/cantidad` (`iol`, `cocos`) son inmunes. El guard `reconciled_unit_price` solo cubre dos convenciones (per-100 y VCP-1000) y **deliberadamente deja intacto todo lo demás**, incluidos los `k` de 1e4/1e5/1e13 que se sabe que existen [V] (`persister.py:513-527`).

4. **`_amortize_position_fifo` no usa `broker_pair`.** Filtra `WHERE broker=?` (`main.py:10609`, `main.py:10561`) mientras los tres motores de venta consumen del par padre↔`· USD`. Un bono amortizante partido entre las dos patas se amortiza solo del lado desde el que se registró el cobro. No encontré nada que lo compense.

5. **`_compute_amort_cost_basis_fifo` ignora las comisiones** (`main.py:10584`: `total_consumed += (lot['invested'] or 0) * ratio`) mientras `_amortize_position_fifo` sí las reduce (`main.py:10643`). Así, `cost_basis_consumed` es sistemáticamente MENOR al costo realmente consumido, y `realized_gain = net_amount − cost_basis_consumed` (`main.py:10508`) queda inflado por la comisión prorrateada. [I — inferido de leer las dos funciones lado a lado; no encontré test que cubra el caso con comisiones.]

6. **`snapshots_job.compute_broker_value_usd` se declara "port fiel" de `computeBrokerValue`** (`snapshots_job.py:166`) pero le falta la rama 2 del canónico (lote `currency='ARS'` alojado en un broker USD). En el path `else` (broker USD/USDT) el costo se suma crudo como dólares [V] (`snapshots_job.py:284-319` — no hay ninguna comprobación de `currency == 'ARS'` ahí). El frontend tiene esa rama explícita y con un comentario que dice que sin ella *"el costo en pesos se contaba como dólares"* (`valuation.js:569-573`). No encontré nada que reconcilie las dos.

7. **El modo `costBasis` es una preferencia de display que el backend no conoce.** Default `'purchase'` desde `CurrencyContext.jsx:102-109`. Todo lo que el backend calcula (snapshots, packets de IA, informes del asesor, Reportes, el CSV) usa implícitamente `'today'`. Un usuario que ve "Invertido US$ 14,96/unidad" en Cartera y "US$ 14,23" en un reporte no tiene forma de saber por qué difieren. `MonthlySummary.jsx:288-296` es el único lugar donde alguien lo notó y lo desactivó explícitamente para lo que se persiste.

8. **Los lotes semilla son invisibles.** Un lote fabricado al precio de venta (`rebuild.py:325-336`, `persister.py:676-696`) queda en `positions` sin ninguna marca — `is_seed` es una clave del dict en memoria, no una columna. La única forma de detectarlos que encontré es la firma indirecta que usa el test: `ABS(entry_price - exit_price) < 1e-9` en la venta que lo consumió [V] (`backend/tests/test_fifo_pool_unico.py:50-56`). El usuario ve un lote con costo = precio de venta y P&L 0 y no tiene cómo saber que Rendi se lo inventó.

9. **`AssetDetail` ordena los lotes distinto que el motor.** El frontend ordena por `entry_date` con `localeCompare` y sin desempate por `id` (`AssetDetail.jsx:163`), mientras los tres motores backend usan `COALESCE(entry_date,'9999-12-31') ASC, id ASC`. Los lotes con `entry_date` NULL van PRIMEROS en la vista (string vacío ordena antes) y ÚLTIMOS en el motor. La etiqueta **"próximo"** sobre el primer lote de la lista puede señalar el lote equivocado. [I — inferido de comparar el `sort` de JS con el `ORDER BY` del SQL; no encontré test que lo cubra.]

10. **La foto de tenencia puede fabricar compras que nunca existieron.** `to_seed` es el único balde que se auto-aplica sin preguntar (`tenencia.py:437-439`), y sobre un bono amortizante su premisa no se cumple porque `positions` guarda el nominal RESIDUAL y la foto puede traer el original. El código lo dice y lo desactiva para amortizantes, pero también dice que *"El camino de la foto NO aplica `residual_factor` en ningún lado"* (`tenencia.py:450-453`) — o sea que las dos puntas de la comparación siguen en escalas distintas para todo lo demás.

11. **El costo se puede editar retroactivamente y el rebuild lo respeta.** `_edit_position_group` escala `positions.invested` **y también** `import_normalized_tx.unit_price` / `gross_amount` (`main.py:8404-8413`), o sea que reescribe el log de eventos. Eso es coherente (si no, el próximo rebuild lo pisaría) pero significa que el "log reproducible" es mutable, y que una venta ya cerrada con el costo viejo queda con un `entry_price` que ya no corresponde a ningún lote. No encontré nada que re-corra el FIFO después de esa edición.

12. **`cost_basis_consumed` está en el esquema, tiene tests que lo verifican (`backend/tests/test_bonds.py:707-808`) y sin embargo tres lectores independientes afirman que está 100% NULL en producción** (`assetPnl.js:18`, `bookComposition.js:210`, `main.py:37436`). No pude resolver la contradicción desde el código: la ruta que lo escribe (`main.py:10480-10486`) existe y funciona en los tests. [I — la hipótesis más simple es que casi nadie usa el flujo de cobro de amortización con `decrement_quantity`, pero no tengo con qué verificarlo sin consultar datos de usuarios, que está fuera de alcance.]

13. **`_persist_sell_fifo` y `sell_position_fifo` tienen el mismo bug potencial pero solo uno lo tiene.** El comentario en `main.py:11265-11276` explica que la compuerta tiene que ser `sell_ccy` y no `currency` (la del broker), y que *"El persister y el rebuild no pueden tener este bug porque ahí `currency = sell_currency` es un alias (persister.py:531)"*. Verifiqué la cita: el alias está en `persister.py:624` (`currency = sell_currency  # alias usado abajo`), no en `:531`. La referencia de línea está corrida; el hecho es correcto.

14. **Dos convenciones opuestas de parseo numérico sobre la misma celda.** `reconciled_unit_price` lo documenta: *"`tenencia._num` usa la convención OPUESTA para la misma celda: una de las dos está mal por construcción"* (`persister.py:509-511`). Eso afecta directamente el costo sembrado por una foto de tenencia.

15. **La cripto de un broker AR escala costo Y valor por el mismo factor** (`crypto_broker_factor`), lo cual preserva el P&L% pero infla el "Invertido" nominal ~5% respecto de lo que el usuario realmente puso [V] (`valuation.js:684-685`, `behavioral.py:428-437`, `snapshots_job.py:294`). Es deliberado y está comentado, pero significa que el "costo de adquisición" que se muestra para cripto no es el costo de adquisición.
