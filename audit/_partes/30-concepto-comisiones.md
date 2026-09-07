## Comisiones, impuestos y costos de transacción

### Definición según el código

En Rendi **no hay un solo "costo de transacción"**: hay **tres materializaciones separadas** que casi nunca se hablan entre sí, más una cuarta que existe en el esquema pero está muerta.

| # | Dónde vive | Qué significa REALMENTE | Moneda |
|---|---|---|---|
| 1 | `positions.commissions` | Comisión **de compra** del lote. **No es un gasto: es COSTO.** Todo el sistema calcula `realCost = invested + commissions` y ese número es el denominador del P&L%. | Nativa del lote (`positions.currency`), **sin columna propia** |
| 2 | `operations.commissions` | Comisión **de venta** (prorrateada por chunk FIFO), o la retención de un cupón/amortización, o la comisión de cierre de un futuro. | Nativa de la operación (`operations.currency`), **sin columna propia** |
| 3 | `import_normalized_tx.fees` | Comisión **embebida** en una fila importada (float pelado). Es lo que después se copia a (1) o (2). | La de `currency` de la fila, **implícita** |
| 3b | `operation_type='FEE'` / `'IMPUESTO'` (filas enteras de `import_normalized_tx`) | Un cargo **suelto** (`FEE`) o una **retención impositiva** (`IMPUESTO`). El monto es el `gross_amount`, no `fees`. | `currency` de la fila |
| 4 | `import_normalized_tx.taxes` | **Columna muerta.** Existe en los dos esquemas y en el dataclass, y sólo un lector la usa (`ledger_replay.py:130`); **ningún parser ni el normalizer la escriben nunca** — siempre queda en su default 0. | — |

Definiciones **no estándar** que el código impone y conviene decir explícito:

- **[V] La comisión de compra se capitaliza al costo, no se gasta.** `realCost = invested + commissions` aparece idéntico en ≥20 sitios (backend y frontend). Consecuencia: la comisión **infla el cost basis** y por lo tanto **baja el P&L% mostrado**, no aparece como una línea de gasto en ningún P&L.
- **[V] `fees` viaja SIN MONEDA.** En `backend/importing/schema.py:224` `gross_amount` tiene `currency`/`settlement_currency` y hasta un `gross_amount_usd` estampado (`schema.py:229`+), pero `fees: float = 0.0` (`schema.py:220`) es un float pelado que se guarda tal cual en `positions.commissions`. Ésa es la causa raíz documentada del incidente de las 469 posiciones (ver ⚠️).
- **[V] "Comisiones" en la UI = FEE sueltos + embebidas, y los impuestos van a un total aparte** (`backend/main.py:13196-13236`). Pero esa separación **sólo la respetan 3 de los 12 parsers** (ver ⚠️).
- **[V] Un impuesto NO es una comisión para la métrica, pero SÍ para el cash**: `OP_TAX` se persiste con el mismo `_persist_cash_out` que `OP_FEE` (`backend/importing/persister.py:381-385`).

---

### Dónde se calcula

Primero lo que parece canónico (la definición del costo y la métrica), después los motores, después los guards y las reparaciones.

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `backend/main.py:13177-13236` | `get_commissions_total` (`GET /api/insights/commissions`) | **LA métrica.** Suma sobre `_build_movements`: FEE sueltos por `amount_usd` + embebidas por `fees_usd`; `IMPUESTO` va a un total separado | `if tipo == "FEE": total_usd += v` / `fee = float(m.get("fees_usd") or 0)` / `if tipo == "IMPUESTO": taxes_usd += v` | **Fuente canónica de la métrica** |
| 2 | `frontend/src/pages/Operations.jsx:1165-1172` | `commTotalUsd` (useMemo) | Espejo declarado del #1, pero **recalculado en el cliente** para respetar los filtros de broker/año | `const loose = scoped.reduce((s, m) => m.type === 'FEE' ? s + (m.amount_usd \|\| 0) : s, 0)` + `(m.type !== 'FEE' && m.type !== 'IMPUESTO') ? s + (m.fees_usd \|\| 0) : s` | Fuente paralela (duplicada a propósito) |
| 3 | `backend/main.py:12488` y `:12577` | `_build_movements` — patas de `operations` | La comisión de la venta se convierte a USD con **el FX sellado de la venta** | `fees = _safe_float_or_none(d.get("commissions")) or 0` → `"fees_usd": fees / gross_fx` (con `gross_fx = op_fx if (op_ccy == "ARS" and op_fx > 0) else 1.0`) | Fuente |
| 4 | `backend/main.py:12601-12617` | `_build_movements` — filas de import | Las fees comparten el TC **implícito de su propia fila** (`gross_amount / gross_amount_usd`); último recurso el blue de hoy | `_rate_row = (amt / stamped) if (stamped and stamped > 0 and amt) else None` … `fees_usd = (fees / _fee_rate) if _fee_rate else fees` | Fuente |
| 5 | `backend/main.py:12771-12781` | `_build_movements` — posiciones abiertas manuales | La comisión del lote abierto se convierte por el **mismo dólar que su `invested`** (`tc_compra`, o blue) | `fees_pos = fees_pos / div` (con `div = tc_compra ?? tc_blue`) | Fuente |
| 6 | `frontend/src/utils/valuation.js:552-553` | `valuePositionLot` (motor canónico declarado) | Cost basis económica de UN lote | `const comm = p.commissions \|\| 0` / `const realCost = (p.invested \|\| 0) + comm` | **Fuente canónica del costo (frontend)** |
| 7 | `frontend/src/utils/valuation.js:294` | `pesoLotUsd` | Costo de un lote en pesos alojado en cuenta USD | `const realCost = (p.invested \|\| 0) + (p.commissions \|\| 0)` | Fuente |
| 8 | `frontend/src/utils/valuation.js:339` | `usdLotValue` | Costo de un lote con costo YA en USD dentro de un broker ARS | `const investedUsd = (p.invested \|\| 0) + (p.commissions \|\| 0)` | Fuente |
| 9 | `frontend/src/utils/valuation.js:367` | `valueEquityLot` | Costo de un lote equity/CEDEAR | `const invested = (p.invested \|\| 0) + (p.commissions \|\| 0)` | Fuente |
| 10 | `frontend/src/utils/valuation.js:633` | `valuePositionLot` rama cash ARS | **El cash NO lleva comisión** (excepción explícita) | `const cashArs = p.invested \|\| 0  // cash no tiene commissions` | Fuente |
| 11 | `frontend/src/utils/valuation.js:868-880` | `avgCostUsdPerUnit` | Costo promedio por unidad en USD — **deliberadamente SIN comisiones** | (docstring `valuation.js:859`: "· SIN comisiones, igual que la columna en pesos") | Fuente **divergente** |
| 12 | `backend/snapshots_job.py:207-208` | `_compute_broker_value_py` (port del `computeBrokerValue`) | Costo por lote en el snapshot diario | `comm = p.get('commissions') or 0` / `real_cost = (p.get('invested') or 0) + comm` | **Fuente canónica del costo (backend)** |
| 13 | `backend/snapshots_job.py:718` | `_cost_usd` (cobertura de precios) | Costo USD por lote para ponderar `mtm_coverage` | `c = (p.get('invested') or 0) + (p.get('commissions') or 0)` | Consumidor |
| 14 | `backend/snapshots_job.py:873` | `_cost_usd` (2ª copia, otra función del mismo archivo) | Idem #13 | `c = (p.get('invested') or 0) + (p.get('commissions') or 0)` | Consumidor (duplicado) |
| 15 | `backend/main.py:8198-8203` | `_manual_position_cost` | Costo cash del alta manual: es lo que se **debita del efectivo** | `cost = invested if invested is not None else (buy_price or 0) * (quantity or 0)` / `return (cost or 0) + (commissions or 0)` | **Fuente canónica del débito de cash manual** |
| 16 | `backend/main.py:11217-11255` | `sell_position_fifo` (`POST /api/positions/sell`) | Prorratea la comisión de venta por chunk FIFO | `total_commission_native = float(data.commissions or 0)` / `chunk_commission_native = total_commission_native * (take / data.quantity) if data.quantity else 0` | Fuente |
| 17 | `backend/main.py:11232-11235` | `sell_position_fifo` | El cost basis consumido **incluye las comisiones de COMPRA** del lote | `base_invested = ((p["invested"] or 0) + pos_buy_commissions)` | Fuente |
| 18 | `backend/main.py:11287` | `sell_position_fifo` — rama ARS | P&L en pesos neto de comisión de venta | `pnl_ars_chunk = data.exit_price * take - (entry_invested or 0) - chunk_commission_native` | Fuente |
| 19 | `backend/main.py:11295` | `sell_position_fifo` — rama USD | Idem en dólares | `pnl_usd = (data.exit_price * take) - cost - chunk_commission_native` | Fuente |
| 20 | `backend/main.py:11300` | `sell_position_fifo` | El cash que entra es **neto** | `total_proceeds_native += data.exit_price * take - chunk_commission_native` | Fuente |
| 21 | `backend/main.py:11370` | `sell_position_fifo` | Venta parcial: la comisión de compra remanente se prorratea | `new_commissions = round(pos_buy_commissions * remaining_ratio, 6)` | Fuente |
| 22 | `backend/importing/persister.py:568,594` | `_persist_buy` | Compra importada: la fee se guarda en el lote y se debita del cash | `fees = float(tx.fees or 0)` / `cost_total = invested + fees` | Fuente |
| 23 | `backend/importing/persister.py:705,776` | `_persist_sell_fifo` | Venta importada: prorrateo por chunk (espejo de #16) | `sell_commissions = float(tx.fees or 0)` / `chunk_commission = sell_commissions * (take / qty_to_sell) if qty_to_sell else 0` | Fuente |
| 24 | `backend/importing/persister.py:792,796` | `_persist_sell_fifo` — rama ARS | P&L y proceeds netos | `pnl_ars_chunk = exit_price * take - (entry_invested or 0) - chunk_commission` / `proceeds_native = exit_price * take - chunk_commission` | Fuente |
| 25 | `backend/importing/persister.py:799,801` | `_persist_sell_fifo` — rama USD | Idem | `pnl_usd = (exit_price * take) - cost - chunk_commission` | Fuente |
| 26 | `backend/importing/persister.py:840` | `_persist_sell_fifo` | Prorrateo del remanente de comisión de compra | `new_commissions = round(pos_buy_commissions * remaining_ratio, 6)` | Fuente |
| 27 | `backend/importing/persister.py:1427` | reverso de batch (`revert`) | Devuelve al cash **lo mismo** que debitó la compra | `cost_total = (invested or 0) + (tx["fees"] or 0)` | Consumidor |
| 28 | `backend/importing/rebuild.py:276,311,445,465,470,486,505` | `rebuild` FIFO | Motor de reconstrucción — **replica byte a byte** #22-#26 | `"commissions": fees` / `chunk_commission = sell_commissions * (take / qty_to_sell) if qty_to_sell else 0` | Fuente (3ª copia del mismo FIFO) |
| 29 | `backend/importing/normalizer.py:349` | `normalize_rows` | Lee la columna mapeada `comisiones` | `fees = _num("comisiones") or 0.0` | **Embudo de los 18 parsers** |
| 30 | `backend/importing/normalizer.py:31,396-406` | `normalize_rows` — guard | **Una "comisión" >5% del monto se pone en CERO** (no descarta la fila) y deja nota | `_FEE_MAX_FRAC = 0.05` / `if _base > 0 and abs(fees) / _base > _FEE_MAX_FRAC: … fees = 0.0` | Fuente (guard) |
| 31 | `backend/importing/normalizer.py:187-189` | `_OP_KEYWORD_FALLBACKS` | Fallback por keyword: `IMPUEST`/`RETENC`/`TAX` → **`OP_FEE`**, no `OP_TAX` | `(("COMISION", …, "IMPUEST", "RETENC", "TAX", "MARGIN_INT", "BORROW_F"), OP_FEE)` | Fuente **contradictoria con `schema.py:142-146`** |
| 32 | `backend/importing/schema.py:133-147` | `OP_TYPE_ALIASES` | Alias exactos: `IMPUESTO/IIBB/RETENCION/WITHHOLDING → OP_TAX`; `ARANCEL/DERECHO_DE_MERCADO → OP_FEE` | `"IMPUESTO": OP_TAX, "IMPUESTOS": OP_TAX, "RETENCION": OP_TAX` | Fuente |
| 33 | `backend/importing/cash_sim.py:126,135` | `simular_cash` (proyección del preview) | Compra debita `gross+fees`, venta acredita `gross−fees` | `cost = (invested or 0) + float(tx.fees or 0)` / `net = (proceeds or 0) - float(tx.fees or 0)` | Consumidor |
| 34 | `backend/importing/cash_sim.py:147-155` | `simular_cash` | `WITHDRAW`, `FEE` e `IMPUESTO` debitan igual | `elif op in (OP_WITHDRAW, OP_FEE, OP_TAX):` | Consumidor |
| 35 | `backend/ledger_replay.py:130` | `saldos_en` | **Único lector de `taxes`.** Resta fees+taxes de TODA operación con monto | `saldos[k] -= float(r["fees"] or 0) + float(r["taxes"] or 0)` | Consumidor |
| 36 | `backend/main.py:10373-10374` | `bond_cashflow` (`POST /api/bonds/cashflow`) | Cupón/amortización: se acredita el **neto** | `commissions = data.commissions or 0` / `net_amount = data.amount - commissions` | Fuente |
| 37 | `backend/main.py:12336` | `close_futuro` (`POST /api/futures/{id}/close`) | Resultado del futuro neto de comisiones | `pnl = round(bruto - float(data.commissions or 0), 2)` | Fuente |
| 38 | `backend/main.py:10640-10651` | `_amortize_position_fifo` | La amortización baja `commissions` proporcionalmente al face amortizado | `new_commissions = (lot['commissions'] or 0) * (1 - ratio)` / `com_taken = (lot['commissions'] or 0) * ratio` | Fuente |
| 39 | `backend/importing/maturity.py:401-406` | vencimiento/amortización de bonos importados | Idem #38 desde el pipeline | `new_com = (l["commissions"] or 0) * factor` | Fuente |
| 40 | `backend/main.py:14022,14035` | `_undo_operation` (`fifo_sell`) | El undo **devuelve la comisión de compra** prorrateada al lote | `com_back = float(lot.get("commissions") or 0) * frac` / `float(live["commissions"] or 0) + com_back` | Consumidor |
| 41 | `backend/main.py:14398,14412` | reverso del undo | Se la vuelve a quitar | `float(_live["commissions"] or 0) - float(_l.get("com") or 0)` | Consumidor |
| 42 | `backend/importing/recompute_backfill.py:228-257` | `normalize_usd_commissions` | Backfill: comisión en **pesos** guardada en un lote **USD** → se divide por `tc_blue`. Sólo si `com > invested` **y** `com >= 100` | `if inv > 0 and com > inv and com >= 100.0: … UPDATE positions SET commissions=?` con `round(com / tc_blue, 6)` | Fuente (reparación) |
| 43 | `backend/main.py:17633-17634,17681,17731` | `admin_repair_comisiones` (`POST /api/admin/repair-comisiones`) | Pone en 0 las comisiones implausibles ya escritas. Mismo 5% del import **+ un piso absoluto por moneda** | `_PISO_COMISION_USD = 25.0` / `_PISO_COMISION_ARS = 35_000.0` / `if base <= 0 or comm / base <= 0.05: continue` | Fuente (reparación) |
| 44 | `backend/main.py:18428` | `admin_costo_inconsistente` | Diagnóstico: compara `buy_price×qty` contra **el costo que usa el P&L** | `real = float(r["invested"]) + float(r["commissions"] or 0)` | Consumidor |
| 45 | `backend/main.py:17562-17583` | `admin_commissions_debug` | Total "exacto como `get_commissions_total`" — pero con **`tc_blue` de hoy** y **sólo lo importado** | `fac = (1.0 / tc_blue) if (r["c"] or "").upper() == "ARS" else 1.0` | Consumidor **divergente** |
| 46 | `backend/main.py:16181,16216,16282` | `admin_diagnose_sell_fx` | Reconstruye el TC perdido de las ventas usando la comisión sellada | `T_rec = (exit_price*quantity - commissions) / (pnl_usd + invested_engine)` | Consumidor |
| 47 | `backend/main.py:30318` | seed de tenencia — guard de plausibilidad | Base de comparación del depósito de apertura | `SELECT COALESCE(SUM(COALESCE(invested,0) + COALESCE(commissions,0)), 0)` | Consumidor |
| 48 | `backend/advisor_groups.py:219` | perfil de clientes del asesor | Fallback a costo cuando no hay valor de mercado | `cost = float(r["invested"] or 0) + float(r["commissions"] or 0)` | Consumidor |
| 49 | `frontend/src/pages/Positions.jsx:1300` | `calcUSDT` | Costo de la fila en broker USD | `const realCost = ((p.invested \|\| 0) + (p.commissions \|\| 0)) * f` | Fuente (fila desktop) |
| 50 | `frontend/src/pages/Positions.jsx:1348` | `calcARS` | Costo de la fila en broker ARS | `const realCostArs = (p.invested \|\| 0) + (p.commissions \|\| 0)` | Fuente (fila desktop) |
| 51 | `frontend/src/pages/Positions.jsx:1251-1253` | `routedInvUsd` | Costo USD ruteado por modo, **lote por lote** | `lots.reduce((s, l) => s + ((l.invested \|\| 0) + (l.commissions \|\| 0)) / costBasisRate(l, rate, costBasis), 0)` | Fuente |
| 52 | `frontend/src/pages/Positions.jsx:1137,1168-1170` | `_buildAgg` | Fila agregada multi-lote: **suma las comisiones aunque anule `invested` por multi-moneda** | `const totalComm = lots.reduce((s, x) => s + (x.commissions \|\| 0), 0)` / `invested: multiCcy ? null : totalInv,` / `commissions: totalComm,` | Fuente **sospechosa** |
| 53 | `frontend/src/pages/Positions.jsx:3787` | preview FIFO del modal Vender | Cost basis del preview incluye comisión de compra… | `const baseInvested = (p.invested \|\| 0) + (p.commissions \|\| 0)` | Fuente |
| 54 | `frontend/src/pages/Positions.jsx:3793,3796` | preview FIFO del modal Vender | …pero **NO resta la comisión de VENTA del P&L** | `const pnlArs = (priceNum * take) - investedPart` / `pnlUsd = (priceNum * take) - investedPart` | Fuente **divergente del backend** |
| 55 | `frontend/src/pages/Positions.jsx:3947` | modal Vender — "Neto recibido" | Ahí sí la resta (pero sólo del cash mostrado) | `{(qtyNum * priceNum - (+form.commissions \|\| 0))…}` | Consumidor |
| 56 | `frontend/src/pages/Positions.jsx:4166-4169` | modal Agregar posición | Feedback en vivo del costo total | `const com = +form.commissions \|\| 0` (→ `realCost`, hint en `:4332-4333`) | Consumidor |
| 57 | `frontend/src/pages/Dashboard.jsx:306,452,526,558,576` | Dashboard (5 sitios) | Cost basis en cada rama de valuación | `const realCost = (p.invested \|\| 0) + (p.commissions \|\| 0)` (y `costArs` / `costUsd` idénticos) | Consumidor |
| 58 | `frontend/src/pages/HomeMobile.jsx:242` | Home mobile | Idem | `const realCost = (p.invested \|\| 0) + (p.commissions \|\| 0)` | Consumidor |
| 59 | `frontend/src/pages/AssetDetail.jsx:47` | `valueLot` (ficha del activo) | Idem, con el cash exceptuado | `const invested = cashInvested + (p.commissions \|\| 0)` | Consumidor |
| 60 | `frontend/src/pages/PositionsMobile.jsx:663` | fila mobile | Idem | `const invested = cashInvested + (p.commissions \|\| 0)` | Consumidor |
| 61 | `frontend/src/pages/FirstInsight.jsx:106` | primer insight | Idem | `const cost = (p.invested \|\| 0) + (p.commissions \|\| 0)` | Consumidor |
| 62 | `frontend/src/pages/Insights.jsx:423,2013` | Insights (2 sitios) | Idem | `const realCost = (p.invested \|\| 0) + (p.commissions \|\| 0)` | Consumidor |
| 63 | `frontend/src/components/RentaFijaSections.jsx:31,43` | agregado de renta fija | Suma comisiones de los lotes del grupo | `const totalComm = lots.reduce((s, x) => s + (x.commissions \|\| 0), 0)` | Consumidor |
| 64 | `frontend/src/utils/diagnostics.js:631-637` | regla `fees_drag` | **Otra** definición del total: Σ `positions.commissions` con conversión ARS→USD al `tcValuacion` | `return s + (arsBrokers.has(p.broker) ? comm / tc : comm)` | Fuente **divergente** |
| 65 | `frontend/src/utils/diagnostics.js:704` | regla de concentración AR | Usa `invested + commissions` como proxy de exposición | `const arsAmt = (p.invested \|\| 0) + (p.commissions \|\| 0)` | Consumidor |
| 66 | `frontend/src/pages/Insights.jsx:1952-1966` | `commissionsStats` | Empaqueta el endpoint + calcula el % sobre ganancias brutas | `const pctOfGrossWin = grossWin && grossWin > 0 ? (total / grossWin) * 100 : null` | Consumidor |

**Extracción de la comisión en los parsers** (el origen del dato — 12 formatos, 5 criterios distintos):

| archivo:línea | parser | cómo obtiene la comisión | fórmula literal |
|---|---|---|---|
| `backend/importing/parsers/cocos.py:44,554-559,590` | Cocos | Suma 4 columnas del CSV (comisión + derechos de mercado + IVA + otros) y las llama todas "comisiones" | `fees = _sum_fees(G(row,"comision"), G(row,"ddmm"), G(row,"iva"), G(row,"otros"))` |
| `backend/importing/parsers/balanz_movimientos.py:482-492` | Balanz Movimientos | **Deriva la comisión del gap bruto−neto**, sólo en pesos y sólo si ≤3% | `comision = abs(gross - abs(importe))` con `embebida_ok = ((moneda or "ARS").upper() == "ARS" and gross > 0 and 0 < comision <= 0.03 * gross)` |
| `backend/importing/parsers/inviu.py:253-257` | inviu | Mismo gap bruto−neto, **sin guard de moneda ni de tasa** | `comision = abs((abs(neto) - gross)) if (neto is not None and gross) else 0.0` |
| `backend/importing/parsers/schwab.py:245,350,383` | Schwab | Columna `Fees & Comm` del CSV | `fees = _abs_str(fees_raw) if fees_raw else "0"` |
| `backend/importing/parsers/binance_transaction.py:213-218,267` | Binance | Fees en stablecoin → `comisiones`; fees pagadas **en cripto** → se emiten como **una VENTA aparte** | `stable_fee = sum(abs(v) for c, v in fee_by_coin.items() if _is_stable_quote(c))` |
| `backend/importing/parsers/balanz_resultados.py:324,352` | Balanz Resultados | `Gastos` va **entero al lote de compra**; la venta sale con comisión vacía | `"comisiones": gastos or ""` (compra) / `"comisiones": ""` (venta) |
| `backend/importing/parsers/iol.py:541,704-711` | IOL | **Calcula `fees` y después lo DESCARTA**: usa `Monto` (neto) como bruto y emite `comisiones="0"` | `fees = _num(G(row,"comis")) + _num(G(row,"ivacom")) + _num(G(row,"otrosimp"))` … `comisiones = "0"` |
| `backend/importing/parsers/ieb.py:444` | IEB | Nunca extrae comisión embebida; los cargos llegan como filas `ND` → `FEE` | `"comisiones": "0"` |
| `backend/importing/parsers/bullmarket.py:61,249,439,462,484` | Bull Market | Idem: `Importe = cantidad × precio` sin desglose | `"comisiones": "0"` |
| `backend/importing/parsers/ppi.py:169-170` | PPI | No extrae embebida; clasifica descripciones | `if (d.startswith("retencion") or d.startswith("ret ganancias") … or d.startswith("comision")): return "fee"` |
| `backend/importing/parsers/balanz_internacional.py:225,286,325,333` | Balanz Internacional | Comisión ~US$10 embebida en el cash (no se extrae); las retenciones sí van a `IMPUESTO` | `_emit(base("DIVIDENDO" if cash_in else "IMPUESTO", monto=str(abs(importe))))` |
| `backend/wallbit.py:154,169-171` | Wallbit (API) | Comisión embebida en el precio all-in; `fees` y `taxes` explícitamente en 0 | `unit = gross / qty  # precio all-in (comisión embebida)` / `fees=0.0, taxes=0.0` |
| `backend/importing/mapper.py:42,77-78` | CSV propio del usuario | Alias aceptados para la columna | `"comisiones": ["comisiones","commission","fee","fees","comm","comisión","comision","costos","charges","broker fee"]` |

---

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `frontend/src/pages/Operations.jsx:1407` | KPI de la vista "Todos" de /operaciones | **"Comisiones"**, sub: *"fees totales (incl. embebidas)"* |
| `frontend/src/pages/Operations.jsx:1387` | KPI cuando el chip de filtro es FEE | **"Total comisiones"**, sub: *"N explícitas + embebidas en trades"* |
| `frontend/src/components/operations/shared.js:38-39` | fila del feed/tabla de movimientos | **"Comisión"** (icono Receipt, tono negativo) y **"Impuesto"** |
| `frontend/src/components/operations/shared.js:63` | chip de filtro | **"Comisiones"** (id `FEE`) — **no hay chip para `IMPUESTO`** |
| `frontend/src/pages/Operations.jsx:1067` | texto del diálogo de borrado | `FEE: 'comisión', IMPUESTO: 'impuesto'` |
| `frontend/src/pages/Operations.jsx:875-876` | form de operación manual | **"Comisiones"** (input libre) |
| `frontend/src/utils/diagnostics.js:357-363` | insight `commissions_high` (severidad warn) | *"Pagaste **X** en comisiones — el **Y%** de tus ganancias brutas"* |
| `frontend/src/utils/diagnostics.js:367-377` | insight `commissions_summary` | *"Comisiones acumuladas: **X** sobre N operaciones"* |
| `frontend/src/utils/diagnostics.js:617-640` | insight `fees_drag` | *"Las comisiones acumuladas suman **X** (**Y%** del portfolio)"* |
| `frontend/src/pages/Positions.jsx:3898,3938-3947` | modal Vender | **"Comisiones (ARS/USD)"** + línea **"Neto recibido"** |
| `frontend/src/pages/Positions.jsx:4327-4333` | modal Agregar posición | **"Comisiones (moneda)"**, hint *"Costo total: … (invertido + comisión)"* |
| `frontend/src/pages/PositionsMobile.jsx:419,442,1816` | alta/edición mobile | mismo campo `commissions` |
| `frontend/src/pages/PositionsMobile.jsx:327,339` | venta mobile | `commissions` en el form de venta (**sin preview de P&L**) |
| `frontend/src/components/BondCashflowModal.jsx:373,438` | modal de cupón/amortización | **"Comisiones / retenciones (moneda) — opcional"** + neto acreditado |
| `frontend/src/components/FuturosGroup.jsx:471` | cierre de futuro | **"Comisiones"**, ayuda *"Opcional — restan del resultado"* |
| `frontend/src/components/import/ImportWizard.jsx:56-57` | mapeo de columnas del CSV | **"Comisiones"** — *"Reducen tu P&L. Si no tenés el dato dejalo en cero."* |
| `backend/importing/preview.py:25` | preview del import | **"Comisión"** (`OP_FEE`) — **`OP_TAX` no está en el mapa de etiquetas** |
| `backend/main.py:13378,13410` | export CSV de operaciones y de posiciones | columna **"Comisiones"** |
| `backend/main.py:13466,13497,13526,13553` | export `transactions.csv` | columna **`comisiones`** (la pata COMPRA de un trade manual sale en **0**, `:13515`) |
| `backend/main.py:17504+` | `GET /api/admin/commissions-debug` | JSON admin: `comisiones_usd`, `impuestos_usd`, `suma_comision_embebida_native` |
| `frontend/src/pages/ReportPublic.jsx:128,255` | informe público del asesor | texto **"· neto de comisiones"** y **"Retornos netos de comisiones"** |
| `backend/reporting/detectors.py:108` / `backend/goals_diagnostic.py:30` / `backend/behavioral.py:633,642` / `backend/ai/prompts.py:643,650` | copys de rotación/overtrading | mencionan comisiones **sin leer ningún número de comisiones** |

---

### Dónde se persiste

| Tabla | Columna | Tipo / default | Qué guarda | Evidencia |
|---|---|---|---|---|
| `positions` | `commissions` | `double precision DEFAULT 0` | Comisión de compra del lote, **en la moneda de `positions.currency`** | `backend/schema_pg.sql:1444`, `:1473`; migración SQLite en `backend/main.py:962-965` |
| `operations` | `commissions` | `double precision DEFAULT 0` | Comisión de venta prorrateada, retención de cupón, comisión de cierre de futuro | `backend/schema_pg.sql:1295`, `:1325`; migración SQLite en `backend/main.py:1156-1159` |
| `import_normalized_tx` | `fees` | `double precision DEFAULT 0` | Comisión embebida de la fila importada (**sin moneda propia**) | `backend/schema_pg.sql:1033`, `:1070`; `backend/main.py:2492` |
| `import_normalized_tx` | `taxes` | `double precision DEFAULT 0` | **Nunca se escribe.** Sólo lo lee `ledger_replay.py:130` | `backend/schema_pg.sql:1034`, `:1072`; `backend/main.py:2493`; `backend/importing/schema.py:221` |
| `import_normalized_tx` | `operation_type` | `text` | Los valores `'FEE'` y `'IMPUESTO'` **son** el cargo (el monto está en `gross_amount`) | `backend/importing/schema.py:26-27` |
| `positions.undo_meta_json` | clave `comision_reparada` | JSON | El valor viejo que borró `repair-comisiones`, para poder revertir | `backend/main.py:17657-17659`, `:17731` |

**No se persiste en ningún lado:**
- **[V]** El **total** de comisiones. `GET /api/insights/commissions` lo recalcula en cada request recorriendo `_build_movements(uid)` (`backend/main.py:13205`), que a su vez corre 4 queries.
- **[V]** Una versión **en USD** de la comisión. `gross_amount_usd` está estampado con el TC de la fecha (`backend/importing/pipeline.py:71-100`), pero **no hay `fees_usd` en la base**: cada lector la re-convierte con su propio criterio.
- **[V]** La **moneda** de `fees` / `commissions`. Se infiere de `currency` de la fila hermana.
- **[V]** Los snapshots diarios (`snapshots`, `backend/schema_pg.sql:1525-1539`) guardan `total_value`/`total_invested` ya con la comisión adentro del costo, pero **no la comisión por separado**.

---

### ⚠️ Implementaciones divergentes

**Hay al menos 7 definiciones distintas del mismo concepto conviviendo en producción.**

#### D1 — Tres totales de "Comisiones" que no dan lo mismo

| Variante | Universo | Conversión ARS→USD | Incluye impuestos | Quién la ve |
|---|---|---|---|---|
| `backend/main.py:13205-13231` (`/api/insights/commissions`) | Importado **+ manual** (`operations` + `positions` + `import_normalized_tx`) | Por fila, con **el dólar de SU fecha** (FX sellado o el implícito de `gross_amount_usd`) | No — van a `taxes_usd` aparte | Insights (cards `commissions_high` / `commissions_summary`) |
| `frontend/src/pages/Operations.jsx:1165-1172` | El mismo, **filtrado por broker/año** | La que ya viene en `fees_usd`/`amount_usd` del endpoint de movimientos | No | KPI "Comisiones" de /operaciones |
| `frontend/src/utils/diagnostics.js:625-637` (`fees_drag`) | **Sólo `positions.commissions`** — ninguna venta, ningún FEE suelto | `comm / tcValuacion` (**dólar de HOY**, para todo el histórico) | n/a | Insight "Las comisiones acumuladas suman X (Y% del portfolio)" |
| `backend/main.py:17562-17583` (`/api/admin/commissions-debug`) | **Sólo lo importado** | `1 / tc_blue` (**dólar de hoy**) | Separados | Sólo admin |

Consecuencia **[I]** (inferida de comparar los cuatro criterios): en la **misma pantalla de Insights** pueden aparecer dos números de comisiones distintos — el de las cards `commissions_*` (endpoint, per-date, incluye ventas) y el de `fees_drag` (sólo posiciones abiertas, al dólar de hoy). Para una cartera argentina con historia larga, la conversión al dólar de hoy **subvalúa** las comisiones viejas por un factor de hasta ~8× (es exactamente la misma clase de bug que `backend/main.py:16160-16190` documenta para las ventas).

**[V]** El comentario de `frontend/src/pages/Insights.jsx:247-250` y `:1949-1951` sigue diciendo que el endpoint *"suma operation_type='FEE' de import_normalized_tx"* y que *"No usamos op.commissions … porque queda contaminado por imports viejos con bugs"* — eso **dejó de ser cierto** el 2026-09-04 (el propio docstring del endpoint, `backend/main.py:13178-13199`, cuenta el cambio). Los comentarios del frontend quedaron desactualizados.

#### D2 — Impuesto vs comisión: 3 parsers los separan, 3 los mezclan, el fallback los mezcla

| Camino | Retención (Ganancias/IIBB/BBPP) termina como | Evidencia |
|---|---|---|
| Balanz Movimientos | `IMPUESTO` | `backend/importing/parsers/balanz_movimientos.py:184-192`, `:567-568` |
| Balanz Internacional | `IMPUESTO` | `backend/importing/parsers/balanz_internacional.py:283-286`, `:333` |
| inviu | `IMPUESTO` | `backend/importing/parsers/inviu.py:275`, `:283` |
| **PPI** | **`FEE`** | `backend/importing/parsers/ppi.py:168-170` (`retencion`, `ret ganancias`, `ret. ganancias` → `"fee"`) → `:368-369` `_emit(base("FEE", …))` |
| **IEB** | **`FEE`** | `backend/importing/parsers/ieb.py:102` (`"DEBITO RET DIVIDENDOS": "ND"`), `:155-157` (`"RETENCION" in lab → "ND"`), `:72` (`"ND": "FEE"`), `:251-252` (`if code.startswith("ND"): return "FEE"`) |
| **Fallback por keyword del normalizer** | **`FEE`** | `backend/importing/normalizer.py:187-189`: `"IMPUEST"`, `"RETENC"`, `"TAX"` están en la tupla que mapea a `OP_FEE` |
| Alias exacto (`IMPUESTO`, `IIBB`, `RETENCION`, `TAX`…) | `IMPUESTO` | `backend/importing/schema.py:143-146` |

**[V]** El orden de resolución es: exacto → alias → keyword (`backend/importing/normalizer.py:196-208`). O sea que `"IMPUESTO"` pelado cae en `OPERATION_TYPES` y queda `IMPUESTO`, pero cualquier variante que no esté en el mapa exacto (`"IMPUESTO DE SELLOS"`, `"RETENCION IIGG"`, `"TAX WITHHOLDING"`) **cae al keyword y se convierte en comisión**.

**[I]** Efecto neto: un usuario de PPI o IEB ve `impuestos_usd = 0` y su KPI "Comisiones" **infla** con las retenciones; uno de Balanz ve los dos separados. Los dos usan la misma card.

#### D3 — El costo promedio por unidad ignora las comisiones; el P&L de la misma fila no

| Función | Fórmula | Pantalla |
|---|---|---|
| `frontend/src/pages/Positions.jsx:1348` (`calcARS`) | `realCostArs = invested + commissions` | Columnas *Invertido* / *P&L* / *P&L %* |
| `frontend/src/utils/valuation.js:868-880` (`avgCostUsdPerUnit`) | **sin comisiones** (docstring `:859`; test-invariante `frontend/src/utils/valuation.test.js:973-979`: `prom * qty ≈ invested / rate`) | Columna **"Precio prom."** en desktop (`Positions.jsx:1258-1260`) y mobile (`PositionsMobile.jsx:2812-2814`) |

**[V]** Es una decisión deliberada y testeada ("igual que la columna en pesos, para que ambas vistas midan lo mismo"), pero produce una fila que **no cierra consigo misma**: `Precio prom. × Cantidad ≠ Invertido` cuando hay comisión. Con el caso del propio test (MELI, `invested` 216.732,82 + `commissions` 1.432,83) la diferencia es 0,66%.

#### D4 — El preview de venta del frontend no descuenta la comisión de venta; el backend sí

| Sitio | P&L del chunk |
|---|---|
| `frontend/src/pages/Positions.jsx:3793` (preview, ARS) | `const pnlArs = (priceNum * take) - investedPart` |
| `frontend/src/pages/Positions.jsx:3796` (preview, USD) | `pnlUsd = (priceNum * take) - investedPart` |
| `backend/main.py:11287` (lo que realmente se guarda, ARS) | `pnl_ars_chunk = data.exit_price * take - (entry_invested or 0) - chunk_commission_native` |
| `backend/main.py:11295` (lo que realmente se guarda, USD) | `pnl_usd = (data.exit_price * take) - cost - chunk_commission_native` |

**[V]** El modal muestra "Neto recibido" ya con la comisión descontada (`Positions.jsx:3947`), pero el **P&L previsualizado por lote** no. El usuario ve un P&L y se le guarda otro, más chico por exactamente la comisión.
**[V]** En mobile **no hay preview FIFO** (grep de `fifoPreview` en `frontend/src/pages/PositionsMobile.jsx`: **no encontrado**), así que ahí no hay divergencia — hay ausencia.

#### D5 — Una operación manual guarda la comisión pero no la usa para nada

| Camino de alta | ¿La comisión resta del P&L? | ¿Resta del cash? | ¿Entra al KPI Comisiones? |
|---|---|---|---|
| `POST /api/positions/sell` (`backend/main.py:11217-11321`) | **Sí** | **Sí** (`:11300`) | Sí |
| `POST /api/bonds/cashflow` (`backend/main.py:10373-10374`) | Sí (el `pnl_usd` guardado **es** el neto, `:10484`) | Sí | Sí |
| `POST /api/futures/{id}/close` (`backend/main.py:12336`) | **Sí** | Sí | Sí |
| **`POST /api/operations`** (`backend/main.py:13853-13858`) | **NO** — inserta `op.commissions or 0` junto al `pnl_usd` que mandó el cliente, sin tocarlo | **NO** (sólo mueve cash si `kind == "futures"`, `:13836`) | Sí (vía `fees_usd` en `_build_movements`) |

**[V]** Es el formulario "Nueva operación" de `frontend/src/pages/Operations.jsx:875-876` + `:177`. La comisión que se tipea ahí **infla el total de comisiones sin bajar ninguna ganancia**.

#### D6 — Tres copias del mismo motor FIFO con la misma aritmética de comisión

`backend/main.py:11217-11373` (venta manual), `backend/importing/persister.py:705-840` (venta importada) y `backend/importing/rebuild.py:311-505` (rebuild) implementan **la misma** fórmula línea por línea. Hoy **convergen** (verifiqué las cuatro expresiones: prorrateo, rama ARS, rama USD, remanente del lote), pero son tres textos separados que hay que tocar juntos.

#### D7 — El guard de plausibilidad tiene dos umbrales distintos para entrada y limpieza

| Sitio | Umbral |
|---|---|
| `backend/importing/normalizer.py:31,398` (entrada) | `abs(fees)/base > 0.05` → `fees = 0.0`. **Sin piso absoluto.** |
| `backend/main.py:17679-17692` (limpieza retroactiva) | `comm/base > 0.05` **Y además** `comm >= _PISO_COMISION_USD (25)` / `_PISO_COMISION_ARS (35.000)` |
| `backend/importing/recompute_backfill.py:255` (backfill ARS→USD) | `com > invested` **Y** `com >= 100.0` → `com / tc_blue` |

**[V]** El propio docstring de `admin_repair_comisiones` (`backend/main.py:17683-17693`) reconoce el hueco: *"las comisiones falsas de Cocos son de ~ARS 13.000 (≈USD 9), o sea POR DEBAJO del piso"*, y las reporta en `no_tocadas_por_el_piso`. Pero el guard de **entrada** no tiene ese piso, así que un fee fijo legítimo de Balanz (US$14 sobre una compra de US$12,22 = 115%) **sí se pone en cero al importar** mientras que la limpieza retroactiva lo respeta. Los dos criterios se declaran "el mismo a propósito" (`:17646-17649`) y no lo son.

#### Lo que SÍ converge (verificado)

- **[V] `realCost = invested + commissions`**: idéntico en `valuation.js:294/339/367/553`, `Positions.jsx:1300/1348`, `Dashboard.jsx:306/452/526/558/576`, `HomeMobile.jsx:242`, `AssetDetail.jsx:47`, `PositionsMobile.jsx:663`, `FirstInsight.jsx:106`, `Insights.jsx:423/2013`, `snapshots_job.py:207-208/718/873`, `advisor_groups.py:219`, `main.py:8203/11235/18428/30318`. **Una sola definición.**
- **[V] El cash nunca lleva comisión**: `valuation.js:633` y el `cashInvested` de `AssetDetail.jsx:47` / `PositionsMobile.jsx:663` la excluyen explícitamente.
- **[V] La comisión se prorratea por el mismo ratio que `invested`** en venta parcial (`main.py:11370`, `persister.py:840`, `rebuild.py:505`), amortización (`main.py:10640`, `maturity.py:401`) y undo (`main.py:14022`).

---

### Zonas grises

1. **[V] `import_normalized_tx.taxes` es una columna fantasma.** Existe en `schema_pg.sql:1034`, en el SQLite (`main.py:2493`), en el dataclass (`importing/schema.py:221`) y se escribe en los 4 INSERT (`persister.py:220`, `pipeline.py:760/1034/1198`) — pero **ningún parser ni el normalizer le asignan nunca un valor** (grep de `taxes` en `backend/importing/parsers/`: **no encontrado**; `normalizer.py:455-470` construye el `NormalizedTx` con `fees=` y sin `taxes=`). El único lector es `ledger_replay.py:130`, que suma `fees + taxes` — o sea que suma un cero. **No entiendo por qué se agregó.** El `wallbit.py:171` la pasa explícitamente en `0.0`.

2. **[V] El docstring de `/api/movements` miente sobre lo que excluye.** `backend/main.py:12421` dice *"NO incluye: Cobranzas de bonos (sub-tipo de operations.notes con kind '_bond_*')"*, pero la query de `_build_movements` (`:12463-12468`) **no tiene ningún filtro por `op_type` ni por `notes`**. Un cupón cargado con el modal (`op_type='Cupón'`, con su `commissions`) entra a la lista. **[I]** Por lo tanto la retención de un cupón cuenta como comisión en el KPI, y aparece rotulada como **"Venta"**.

3. **[V] Toda operación manual se rotula BUY/SELL sin mirar su `op_type`.** En `_build_movements` la variable `op_type` se calcula en `backend/main.py:12473` y **no se usa en ninguna línea del resto del loop** (verificado con `awk` sobre las líneas 12471-12585). Las filas se emiten con `"type": "BUY"` (`:12520`) y `"type": "SELL"` (`:12557`) fijos. Un Cupón, una Amortización, un Futuros y un Dividendo manual salen todos como "Venta".

4. **[V] IOL calcula la comisión y la tira, y su docstring dice lo contrario.** `backend/importing/parsers/iol.py:76-79` promete *"Fees aparte en `comisiones`"*; el código en `:541` computa `fees = _num(G(row,"comis")) + _num(G(row,"ivacom")) + _num(G(row,"otrosimp"))` y en `:704-711` lo descarta con `comisiones = "0"` porque usa `Monto` (neto) como bruto. **[I]** Resultado: para un usuario 100% IOL, el costo del lote es correcto (viene neto) pero **el KPI "Comisiones" da ~0** aunque IOL le haya cobrado; y el `fees` calculado queda como variable muerta salvo en el fallback de `:716`.

5. **[V] `Positions.jsx:1168-1170` suma comisiones de monedas distintas.** En la fila agregada multi-moneda, `invested` se anula (`multiCcy ? null : totalInv`) y `buy_price` también, **pero `commissions: totalComm` suma pesos con dólares sin conversión**. **[I]** Como la fila multi-moneda se valúa lote por lote (dice el comentario `:1165-1167`), probablemente ese `commissions` no se lea; pero queda expuesto en el objeto y cualquier lector futuro que haga `invested + commissions` sobre el agregado obtiene una unidad mixta. Mismo patrón, sin el guard de multi-moneda, en `RentaFijaSections.jsx:31,43`.

6. **[V] `OP_TAX` está a medio integrar en el pipeline de import.**
   - `backend/importing/preview.py:15-27`: `_op_label` **no tiene entrada para `OP_TAX`** → el preview muestra el string crudo `"IMPUESTO"`.
   - `backend/importing/preview.py:76-78`: el contador `cash_movements` suma `DEPOSIT + WITHDRAW + FEE` y **no `IMPUESTO`** → un batch de retenciones se previsualiza como "0 movimientos de efectivo" aunque el persister las debite (`persister.py:381-385`).
   - `backend/importing/validator.py:156-159`: hay una regla para `OP_FEE` ("una comisión aislada necesita monto > 0") y **ninguna para `OP_TAX`**.
   - `frontend/src/components/operations/shared.js:55-64`: `MOVEMENT_TYPES` (los chips de filtro) **no tiene `IMPUESTO`**, aunque `DELETABLE_MOVEMENT_TYPES` (`:53`) y `TYPE_META` (`:39`) sí. Las retenciones se ven en "Todos" y no se pueden filtrar.

7. **[V] `commissionsStats.taxes` / `.taxesCount` se calculan y nadie los usa.** `frontend/src/pages/Insights.jsx:1963-1964` los arma desde el endpoint; grep de `commissionsStats` en todo el frontend devuelve sólo las dos reglas de `diagnostics.js:360-377`, que **leen únicamente `total`, `count` y `pctOfGrossWin`**. El total de impuestos que el backend calcula con cuidado (`main.py:13213-13218`) no se muestra en ninguna parte de la app.

8. **[V] La conversión de la fee importada depende de que la fila tenga bruto.** En `backend/main.py:12611-12614`, `_fee_rate` se deriva de `amt / stamped`; si `gross_amount` es 0/None (o el `gross_amount_usd` no está estampado, filas legacy) cae al `tc_blue` **de hoy**. **[I]** Para una fila vieja en pesos eso subvalúa la comisión por el mismo factor que el bug de las ventas que `main.py:16160` documenta.

9. **[V] `admin_commissions_debug` se declara "EXACTO como `get_commissions_total`" y no lo es.** `backend/main.py:17562` dice *"Total EXACTO como get_commissions_total"*, pero usa `tc_blue` de hoy (`:17568`) y **sólo mira `import_normalized_tx`** (`:17570-17573`), mientras el endpoint real usa TC por fecha e incluye lo manual. La herramienta de diagnóstico da un número distinto al que el usuario ve.

10. **[V] `ReportPublic.jsx:128,255` afirma "Retornos netos de comisiones"** y **[V]** en `backend/reporting/` la única aparición de la palabra es un copy (`detectors.py:108`); `backend/twr.py` y `backend/advisor_twr.py` **no leen `commissions` en ninguna línea** (grep: no encontrado). **[I]** La afirmación es cierta sólo de forma indirecta —las comisiones ya están dentro del cost basis y de los proceeds netos— pero no hay ninguna resta explícita de comisiones en el motor de retornos; si el parser no las extrajo (IOL, IEB, Bull Market), el retorno tampoco las tiene.

11. **[V] El `taxes` que el usuario ve y el que el ledger usa no son el mismo concepto.** `_build_movements` no lee la columna `taxes` en ningún momento (su SELECT, `main.py:12586-12591`, pide `t.fees` y no `t.taxes`); la métrica de impuestos sale de contar **filas** con `operation_type='IMPUESTO'`. `ledger_replay.py:106,130`, en cambio, sí lee la columna. Son dos caminos distintos para "impuesto" y sólo uno tiene datos.

12. **[V] Un tercio de la fórmula del guard de entrada nunca se ejerce en dólares.** `normalizer.py:398` compara `abs(fees)/_base` sin saber la moneda de ninguno de los dos. El propio docstring del test (`backend/tests/test_comision_implausible.py:9-16`) lo dice: *"`fees` viaja SIN MONEDA … Si un parser emite la comisión en PESOS sobre un lote en DÓLARES, nadie lo nota"*. El guard **no arregla la causa**, sólo corta a los que superan el 5%; una comisión en pesos que caiga **por debajo** del 5% del monto en dólares pasa intacta y queda ×MEP en el cost basis.

13. **[I] Cocos llama "comisión" a cuatro cosas.** `backend/importing/parsers/cocos.py:44` suma `comision + ddmm + iva + otros` en un solo `fees` — o sea que **derechos de mercado e IVA quedan dentro del total de "Comisiones"** y fuera del total de "Impuestos", aunque `schema.py:147` mapea `"ARANCEL"`/`"DERECHO_DE_MERCADO"` a `OP_FEE` (consistente) y `schema.py:143` mandaría el IVA a `OP_TAX` si viniera como fila suelta (inconsistente). El mismo peso puede terminar en un total o en el otro según venga como columna o como fila.

14. **[V] El export CSV de transacciones pone la comisión de un trade manual sólo en la pata VENTA.** `backend/main.py:13515` emite `"comisiones": 0` para la pata COMPRA y `:13525` la comisión completa en la VENTA. Coincide con `_build_movements` (`:12527` `"fees_usd": 0` en la pata BUY), pero significa que **la comisión de compra de una posición YA VENDIDA desaparece de todos los reportes**: se consumió dentro de `entry_invested` y nadie la vuelve a exponer.
