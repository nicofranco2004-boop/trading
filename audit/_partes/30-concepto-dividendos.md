## Dividendos, cupones, rentas y amortizaciones

### Definición según el código

En Rendi esto **no es un concepto**: son **cinco cosas distintas** que comparten el nombre "renta" y que el código trata con reglas incompatibles entre sí. Lo que el código realmente implementa:

1. **"Renta" como ganancia realizada sin costo asociado.** [V] Un dividendo, un interés o un cupón entran a `operations` con `pnl_usd` = el monto cobrado y suman a `monthly_entries.pnl_realized` — o sea, se contabilizan como *ganancia cerrada*, igual que una venta, pero sin consumir cost-basis. `backend/main.py:11701-11705` lo dice explícito: `_SIN_COSTO = ("futuro", "dividendo", "interes", "interés", "cupon", "cupón", "renta")`, y la lectura del diagnóstico es *"futuros, dividendos e intereses suman P&L realizado sin mover el costo de la tenencia"* (`backend/main.py:11752-11753`).

2. **"Renta" como tercera pata del rendimiento por porción.** [V] `frontend/src/utils/assetPnl.js:12-14` define el resultado de una clase de activo como `no realizado + realizado + renta`, donde la renta *suma arriba pero no al denominador*: `backend/main.py:37515-37518` (`b["income_usd"] += pnl` … "no invertiste para cobrar el cupón"). Acá "renta" = `op_type` que contiene `DIVIDENDO`, `INTER` o `CUPON` (sin acentos) — **`AMORTIZACION` queda afuera** (`frontend/src/utils/assetPnl.js:202`, `backend/main.py:37503`).

3. **"Amortización" como devolución de capital, P&L-neutral.** [V] `backend/importing/persister.py:904-935`: si un `DIVIDEND`/`INTEREST` importado tiene `"amortiz"` en las notas y el activo es un bono, se re-etiqueta `op_type='Amortización'` con **`pnl_usd = 0`** y **no toca** `pnl_realized`. *"Una amortización devuelve TU capital: no es ingreso"* (`persister.py:911`).

4. **"Amortización" como ganancia bruta completa (el flujo manual).** [V] El endpoint manual `POST /api/bonds/cashflow` inserta `op_type='Amortización'` con **`pnl_usd = net_amount`** (el cash *entero*) — `backend/main.py:10479-10488`. El `cost_basis_consumed` se calcula y se guarda en su propia columna, pero **no se resta del `pnl_usd`**. La "ganancia realizada" (`net_amount − cost_basis_consumed`) sólo viaja en el *response* HTTP y se rotula "sólo para diagnóstico / response" (`backend/main.py:10505-10508`). O sea: la misma amortización vale 0, vale el cash completo, o vale el cash menos el costo, según qué camino la creó y quién la lea.

5. **"Cupón/amortización" como flujo TEÓRICO futuro (nunca persistido).** [V] `frontend/src/utils/bondSchedule.js:132` genera el cronograma completo por 100 de valor nominal desde metadata estática del frontend; nadie lo guarda. Es la fuente del inbox de pendientes (`frontend/src/utils/pendingCashflows.js:98`), del calendario (`frontend/src/utils/upcomingEvents.js:48`) y de la TIR.

**Lo no estándar, explícito:** la columna se llama `pnl_usd` pero **en `Cupón` y `Amortización` guarda el monto en la MONEDA DEL BROKER**, no en dólares. Está documentado como el bug de producción que originó el módulo canónico: *"un cupón de bono en pesos que el dashboard mostraba como US$100 y la IA, en el MISMO request, le contaba al usuario como US$125.000"* (`backend/realized_pnl.py:5-8`). El fix no es una migración de datos: es un `CASE WHEN` que cada lector tiene que aplicar (`backend/realized_pnl.py:97-108`).

**El vocabulario en la DB** (op_types que existen realmente en `operations.op_type`) [V]:

| op_type | quién lo escribe | `pnl_usd` en | ¿suma a `pnl_realized`? |
|---|---|---|---|
| `Cupón` | `POST /api/bonds/cashflow` (`main.py:10372`) | moneda del broker | no directo (ver zonas grises) |
| `Amortización` | `bond_cashflow` **y** el importador (`persister.py:976`) | broker / — | manual: no directo · import: **0** |
| `Dividendo` | importador (`persister.py:978`) | **USD** (÷ `tc_blue`) | sí (`persister.py:996-997`) |
| `Interés` | importador (`persister.py:978`) | **USD** (÷ `tc_blue`) | sí |
| `Interés PF` | `POST /api/pf/{id}/cobrar` (`main.py:9319`) | moneda nativa del PF | no directo |
| `Renta` | **nadie** — aparece sólo en guards de borrado | — | — |

### Dónde se calcula

Ordenado: primero lo canónico (el módulo único de conversión), después las fuentes (escritores), después los cálculos derivados.

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `backend/realized_pnl.py:97` | `realized_usd_sql(prefix)` | **Criterio canónico** SQL: convierte `pnl_usd` a USD real sólo en Cupón/Amortización ARS con FX sellado | `CASE WHEN {p}op_type IN ('Cupón','Amortización') AND {p}currency = 'ARS' AND {p}fx_to_usd > 0 THEN {p}pnl_usd / {p}fx_to_usd ELSE {p}pnl_usd END` | canónico (consumidor) |
| 2 | `backend/realized_pnl.py:118` | `realized_usd(row)` | El mismo criterio en Python | `raw / fx if fx > 0 else raw` (previo: `if op_type not in _NATIVE_CCY_OPS: return raw`) | canónico |
| 3 | `backend/realized_pnl.py:78` | `_NATIVE_CCY_OPS` | La lista de los que NO están en USD | `_NATIVE_CCY_OPS = ('Cupón', 'Amortización')` | canónico |
| 4 | `backend/realized_pnl.py:74` / `:85` / `:110` | `_NOT_A_TRADE`, `closed_filter_sql`, `is_closed_op` | Qué es un "trade cerrado" | `_NOT_A_TRADE = ('Compra', 'Dividendo', 'Interés', '')` — **`Cupón`/`Amortización`/`Interés PF` SÍ cuentan como trade** | canónico |
| 5 | `frontend/src/utils/assetPnl.js:76` | `opPnlUsd(op)` | Espejo JS del #2 | `return raw / fx` con `NATIVE_CCY_OPS = ['Cupón', 'Amortización']` (`:70`) | canónico (frontend) |
| 6 | `backend/main.py:10346-10530` | `bond_cashflow` (`POST /api/bonds/cashflow`) | **Fuente #1**: registra un cupón/amortización cobrado a mano | `op_type = 'Cupón' if data.flow_type == 'coupon' else 'Amortización'` (`:10372`); `net_amount = data.amount - commissions` (`:10374`); INSERT con `pnl_usd = net_amount` (`:10484`) | fuente |
| 7 | `backend/main.py:10409-10416` | `bond_cashflow` — resolución de FX | Sella `currency` + `fx_to_usd` (nativa por USD) | `if currency in ('USD','USDT'): fx_to_usd = 1.0` · `elif data.fx_to_usd is not None: fx_to_usd = data.fx_to_usd` · `else: fx_to_usd, fx_source = _fx.fx_for_date_detail(conn, data.date)` | fuente |
| 8 | `backend/main.py:10384-10388` | `bond_cashflow` — guard de fecha | Rechaza cobros con fecha futura | `if data.date[:10] > date.today().isoformat(): raise HTTPException(400, ...)` | fuente |
| 9 | `backend/main.py:10587-10659` | `_amortize_position_fifo` | Baja FIFO `quantity`/`invested`/`commissions` de los lotes por el face amortizado | `ratio = take / lot_qty` · `new_qty = lot_qty - take` · `new_invested = (lot['invested'] or 0) * (1 - ratio)` · `new_commissions = (lot['commissions'] or 0) * (1 - ratio)` | fuente |
| 10 | `backend/main.py:10549-10584` | `_compute_amort_cost_basis_fifo` | Versión read-only del #9: cuánto cost-basis se consumiría | `total_consumed += (lot['invested'] or 0) * ratio` con `qty_to_take = min(amort_amount, total_qty)` | fuente |
| 11 | `backend/main.py:10505-10508` | `bond_cashflow` — `realized_gain` | Ganancia real del amort — **sólo en el response, no se persiste** | `realized_gain = round(net_amount - cost_basis_consumed, 6)` | fuente (efímero) |
| 12 | `backend/main.py:10450-10457` | `bond_cashflow` — sanity cross-currency | Aborta el decrement si el face pedido es desproporcionado | `if total_qty > 0 and face_to_decrement > total_qty * 1.5: cross_currency_skipped = True` | fuente |
| 13 | `backend/main.py:10537-10547` | `_bond_total_qty` | Suma de nominales del par (broker, activo) | `SELECT COALESCE(SUM(quantity), 0) ... WHERE ... is_cash=0 AND quantity > 0` | fuente |
| 14 | `backend/importing/persister.py:938-999` | `_persist_dividend_or_interest` | **Fuente #2**: dividendos/intereses/cupones importados | `op_label = "Dividendo" if tx.operation_type == OP_DIVIDEND else "Interés"` (`:978`); `amount_usd = (amount / tc_blue) if currency == "ARS" else amount` (`:979`); `pnl_usd = 0.0 if is_amort else round(amount_usd, 2)` (`:980`) | fuente |
| 15 | `backend/importing/persister.py:904-935` | `_is_amort_capital_return` | Detecta amortización sin cantidad → P&L-neutral | `if "amortiz" not in (notes or "").lower(): return False` + `asset_type == "BOND"` o `is_known_ar_bond(asset_symbol)` | fuente |
| 16 | `backend/importing/persister.py:995-998` | `_persist_dividend_or_interest` | Actualiza el mensual (salvo amort) | `if not is_amort: helpers._update_monthly_pnl_realized(conn, uid, tx.broker, y, m, amount_usd)` (+ `'global'`) | fuente |
| 17 | `backend/main.py:9276-9331` | `cobrar_plazo_fijo` | **Fuente #3**: interés de plazo fijo → `op_type='Interés PF'` en moneda nativa | `interes = round(val["interes_hoy"], 2)` · `fx = 1.0 if moneda in ("USD","USDT") else None` · INSERT `'Interés PF'` (`:9319`) | fuente |
| 18 | `backend/main.py:13823-13886` | `create_operation` | **Fuente #4**: alta manual libre de `operations` (cualquier `op_type` tipeado) | INSERT directo + `_recalc_pnl_realized_from_ops(conn, uid)` (`:13879`) | fuente |
| 19 | `backend/importing/normalizer.py:180-182` | `_OP_KEYWORD_FALLBACKS` | **Clasificador**: colapsa 4 conceptos en uno | `(("DIVIDEN", "COUPON", "RENTA", "AMORTIZA"), OP_DIVIDEND)` · `(("INTERES","INTERÉS","INTEREST","STAKING","REWARD","EARN"), OP_INTEREST)` | fuente |
| 20 | `backend/importing/schema.py:91-105` | `OP_TYPE_ALIASES` | ~30 alias → `OP_DIVIDEND` | `"COUPON": OP_DIVIDEND, "RENTA": OP_DIVIDEND, "AMORTIZACION": OP_DIVIDEND, "AMORTIZACIÓN": OP_DIVIDEND` … `"PIL": OP_DIVIDEND` | fuente |
| 21 | `backend/importing/normalizer.py:514-518` | `normalize_rows` | Un dividendo con monto negativo se convierte en FEE | `tx.operation_type = OP_WITHDRAW if op_type == OP_DEPOSIT else OP_FEE` | fuente |
| 22 | `backend/main.py:9517-9536` | `_recalc_pnl_realized_from_ops` | Recompone `monthly_entries.pnl_realized` desde `operations` con el criterio canónico | `SELECT COALESCE(SUM({realized_pnl.realized_usd_sql('o')}), 0) AS s FROM operations o WHERE ...` | consumidor (y escritor del mensual) |
| 23 | `frontend/src/utils/bondSchedule.js:132-272` | `generateSchedule(ticker, options)` | **Fuente teórica**: cronograma completo por 100 de face | `couponPerPeriod = rateAnnual / (12 / months)` · `couponAmountNominal = couponPerPeriod * face / 100` · `face = Math.max(0, face - amortNominal)` | fuente (teórica) |
| 24 | `frontend/src/utils/bondSchedule.js:242-248` | `generateSchedule` — ajuste CER | Multiplica cupón y amort por `CER(pago)/CER(emisión)` | `const factor = adjFactor(date)` · `couponAmount = +(couponAmountNominal * factor).toFixed(6)` · `amortOnThisDate = +(amortNominal * factor).toFixed(6)` | fuente (teórica) |
| 25 | `frontend/src/utils/bondSchedule.js:369-380` | `nextPaymentForPosition` | Escala el próximo pago a los nominales del lote | `coupon: +(next.coupon * quantity / 100).toFixed(2)` · `amort: +(next.amort * quantity / 100).toFixed(2)` | consumidor |
| 26 | `frontend/src/utils/bondPricing.js:136-155` | `computeAccrued` | Intereses corridos, lineal sobre el período corriente | `frac = Math.max(0, Math.min(1, elapsed / totalPeriod))` · `return nextCoupon * frac` | consumidor |
| 27 | `frontend/src/utils/bondSchedule.js:314-353` | `estimateYieldDetailed` | TIR sobre los flujos futuros (cupón+amort) | `cashflows = rest.map(p => ({ t: dayCountFraction(base, p.date, dayCount), amount: p.total }))` | consumidor |
| 28 | `frontend/src/utils/bondSchedulesAR.js:63-190` | `CANJE_2020_*` | Cronogramas hardcodeados (step-up + amort) de los 11 soberanos del canje | `amortSchedule: evenAmorts('2024-07-09', 13, 100 / 13)` (AL30/GD30) | fuente (dato) |
| 29 | `backend/pricing/bond_amortization.py:54-93` | `_AMORT_SCHEDULES` | Cronogramas de amortización **del backend** (sólo AL29/GD29/AL30/GD30) | AL30: `[("2024-07-09", 0.04), ("2025-01-09", 0.08), … 12 × 0.08]` | fuente (dato) |
| 30 | `backend/pricing/bond_amortization.py:125-142` | `residual_factor` | Fracción del nominal original todavía viva | `paid = sum(frac for (d, frac) in sched if d <= ref)` · `r = 1.0 - paid` | consumidor |
| 31 | `backend/importing/maturity.py:296-400` | `sweep_bond_amortizations` | Baja el nominal de los bonos amortizantes post-import | `target = original * r` sobre `_bond_genuine_net(...)`; no toca cash ni `monthly_entries` | consumidor (escribe `positions`) |
| 32 | `frontend/src/utils/pendingCashflows.js:98-161` | `detectPendingCashflows` | Inbox: pagos teóricos pasados sin `operation` ni skip | `const factor = p.quantity / 100` · `total: +(pmt.total * factor).toFixed(2)` · match por `diffDaysAbs(o.date, theoreticalDate) <= 14` | consumidor |
| 33 | `frontend/src/utils/upcomingEvents.js:48-96` | `upcomingBondEvents` | Eventos futuros de bonos (calendario) | `couponAmt = pmt.coupon * p.quantity / 100` · `eventType = 'bond_coupon_amort' \| 'bond_amort' \| 'bond_coupon' \| 'bond_maturity'` | consumidor |
| 34 | `frontend/src/pages/Positions.jsx:496-570` | `bondCashflowsByKey` | Agrega cobranzas por `broker:asset`, separa **cash recibido** de **aporte al P&L** | `let pnlContrib = amt; if (op.op_type === 'Amortización') { pnlContrib = amt - cbConsumed }` (`:540-552`) · `const amtUsd = amt / fx` (`:533`) | consumidor |
| 35 | `frontend/src/pages/Positions.jsx:524-532` | `bondCashflowsByKey` — fallback FX | Inventa un FX cuando la fila es legacy | `if (op.currency === 'ARS' \|\| (op.currency == null && amt > 1000)) { fx = tcValuacion \|\| 1 } else { fx = 1.0 }` | consumidor |
| 36 | `frontend/src/utils/assetPnl.js:139-245` | `computePnlByKey` | Rendimiento por clase/sector: 3 patas | `b.total = b.realized + b.unrealized + b.income` (`:241`) · `esRenta` → `b.income += pnl` (`:202-207`) | consumidor |
| 37 | `frontend/src/utils/assetPnl.js:122-126` | `ratePct` | Oculta la tasa cuando el denominador se evaporó | `if (Math.abs(total) > cost * MAX_PNL_TO_COST) return null` con `MAX_PNL_TO_COST = 10` | consumidor |
| 38 | `backend/main.py:37391-37403` | `_rate_pct` | Espejo Python del #37, misma constante `MAX_PNL_TO_COST = 10` (`:37388`) | `if abs(total) > cost * MAX_PNL_TO_COST: return None` | consumidor |
| 39 | `backend/main.py:37406-37516` | `_advisor_realized_raw` | Cerrado + renta por cliente (libro del asesor) | `if "DIVIDENDO" in tipo or "INTER" in tipo or "CUPON" in tipo: b["income_usd"] += pnl; continue` (`:37503-37507`) · `tipo = _strip_accents((r["op_type"] or "").upper())` | consumidor |
| 40 | `backend/main.py:37383-37386` | `_strip_accents` | `'CUPÓN' → 'CUPON'` — sin esto los cupones caían en "venta" | `unicodedata.normalize("NFD", s)` filtrando combinantes | consumidor |
| 41 | `frontend/src/utils/bookComposition.js:238-241` | `realizedToOps` | Convierte el agregado del asesor en pseudo-ops para reusar `computePnlByKey` | `ops.push({ ...base, op_type: 'Dividendo', pnl_usd: r.income_usd })` | consumidor |
| 42 | `backend/reporting/builder.py:218-246` | `fetch_operations_in_range` | Embudo del módulo de reportes: convierte en el SELECT | `SELECT ... {realized_usd_sql()} AS pnl_usd, pnl_pct FROM operations WHERE user_id = ? AND date >= ? AND date <= ?` | consumidor |
| 43 | `backend/reporting/builder.py:845-853` | `_is_trade` (métricas del período) | Win rate del período | `if t in ("Compra", "Dividendo", "Interés"): return False` — **Cupón/Amortización cuentan** | consumidor |
| 44 | `backend/reporting/detectors.py:357-383` | `detect_dividend_heavy` | Insight "los dividendos explicaron el X%" | `div_int = sum(... if (o.get("op_type") or "") in ("Dividendo", "Interés"))` · `pct = div_int / total_realized * 100` | consumidor |
| 45 | `backend/reporting/timeline.py:61-90` | `_compute_user_historical_win_rate` | Win rate lifetime | `if (r["op_type"] or "") not in ("Compra", "Dividendo", "Interés")` | consumidor |
| 46 | `backend/behavioral.py:63-71` + `:1840-1844` | `_is_trade` + normalización única | 12 detectores de sesgos | `ops = [{**o, "pnl_usd": _realized_usd(o)} if o.get("pnl_usd") is not None else o for o in (operations or [])]` | consumidor |
| 47 | `backend/wrapped.py:72-89` | `_operations_for_year` | Wrapped anual (el "mejor trade del año") | `out.append({**op, 'pnl_usd': realized_usd(op)} if op.get('pnl_usd') is not None else op)` | consumidor |
| 48 | `backend/main.py:5889-5960` | `_fetch_yf_events` | Trae `ex_dividend` + `dividend_per_share` de yfinance | `ex_div = info.get('exDividendDate')` · `div_amount = info.get('lastDividendValue')` · `details['dividend_per_share'] = round(float(div_amount), 4)` | fuente |
| 49 | `backend/home/briefing.py:126-155` | `detect_dividends_soon` | Card "Dividendo de X en Nd" | `if ev.get("event_type") != "ex_dividend": continue` · ventana `today <= ev_date <= today+7d` | consumidor |
| 50 | `frontend/src/pages/Events.jsx:934-946` | `eventCobro` | Cobro estimado del evento | bono: `details.total` · dividendo: `details.dividend_per_share * shares` (currency hardcodeada `'USD'`) | consumidor |
| 51 | `frontend/src/utils/bondCashflowFx.js:58-105` | `suggestBrokerAmount` | Convierte el teórico (moneda del bono) a la del broker con el TC del día del pago | `haciaPesos` → `amount: round2(theoreticalAmount * tc), fxToUsdForRow: tc` · inversa → `theoreticalAmount / tc, fxToUsdForRow: 1` | consumidor |
| 52 | `frontend/src/components/RentaFijaSections.jsx:310-315` | `BondCardRow` | P&L "con cupones" de la card de renta fija | `pnlAdjUsd = (v.pnlUsd \|\| 0) + (summary?.pnlContributionUsd \|\| 0)` · `pnlAdjPct = pnlAdjUsd / investedUsd` · `recovery = (summary?.total \|\| 0) / p.invested` | consumidor |
| 53 | `frontend/src/components/BondDetail.jsx:66` | `BondDetail` | Ganancia atribuible al amort | `const amortRealizedGain = pnlContribution - coupons` | consumidor |
| 54 | `backend/main.py:9414-9760` | `_recalc_pnl_realized_from_ops` | Reconstruye `capital_final` de la cadena mensual | `capital_final = capital_inicio + deposits − withdrawals + pnl_realized` (`:9667`) | consumidor |

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `frontend/src/pages/Dashboard.jsx:889-898` | KPI "P&L realizado" (viene de `monthly_entries`) | *"Ganancia (o pérdida) que ya está cerrada — ventas concretadas, dividendos cobrados, intereses"* |
| `frontend/src/pages/Dashboard.jsx:919-950` | KPI del gap contable | **"Dividendos e intereses"** (cuando `accountingGap < 0`), sub: *"no cargados como P&L"* |
| `frontend/src/pages/Dashboard.jsx:141-152` | carga `/operations` para las tortas | *"sin las ventas y la renta (cupones/dividendos) el % sería el de las posiciones abiertas nada más"* |
| `frontend/src/components/CompositionDonut.jsx:281-292` | fila "Resultado" de cada porción | *"Suma no realizado + realizado + renta (cupones/dividendos)"* |
| `frontend/src/pages/Positions.jsx:2270-2300` | tabla ARS de Cartera | P&L de la fila del bono aumentado con `pnlContribution` |
| `frontend/src/pages/Positions.jsx:2582-2600` | tabla USD de Cartera | ídem |
| `frontend/src/pages/Positions.jsx:1046-1062` | `_rowSortKeys` | el orden de la tabla usa el P&L aumentado |
| `frontend/src/components/RentaFijaSections.jsx:400-407` | badge de la card de renta fija | `{pct} con cupones` |
| `frontend/src/components/BondDetail.jsx:232-233` | detalle del bono | **"Cupones"** / **"Amortizaciones"** |
| `frontend/src/components/BondDetail.jsx:254-261` | botones del detalle | **"Cupón cobrado"** / **"Amortización"** |
| `frontend/src/components/BondDetail.jsx:296-302` | próximo pago | *"amortización" / "cupón" / "cupón + amortización" · por tus N nominales* |
| `frontend/src/components/BondDetail.jsx:140-160` + `:172-175` | timeline del bono | estados **cobrado · sin confirmar · sin registro · estimado** |
| `frontend/src/components/BondDetail.jsx:364` | historial de cobranzas | badge verde `Cupón` / violeta `Amortización` |
| `frontend/src/components/BondCashflowModal.jsx:172` | modal de alta | **"Registrar cupón cobrado"** / **"Registrar amortización"** |
| `frontend/src/components/BondCashflowModal.jsx:388-427` | toggle del modal | *"Una amortización devuelve capital → tu VN remanente decrece"* |
| `frontend/src/components/PendingCashflowsBanner.jsx:92-99` | inbox de pendientes | **Cupón** / **Amortización** / **Cupón + amortización**; botón directo sólo para `kind === 'cupon'` same-currency |
| `frontend/src/pages/Events.jsx:6` | KPI strip de Novedades | *"próximo, total, cupones, confirmados"* |
| `frontend/src/pages/Events.jsx:228` | subtítulo de Novedades | *"Próximos cupones, earnings, dividendos y eventos macro."* |
| `frontend/src/pages/Events.jsx:56` | filtro de tipo | **"Dividendos"** |
| `frontend/src/pages/Events.jsx:897-901` | detalle del evento | `Cupón {cur} X + amort {cur} Y` |
| `frontend/src/utils/upcomingEvents.js:168-180` | `eventTypeLabel` | `Ex-dividendo` · `Pago dividendo` · `Cupón de bono` · `Amortización` · `Cupón + amortización` · `Vencimiento de bono` |
| `frontend/src/utils/upcomingEvents.js:212-218` | `eventCategoryLabel` | badges **DIVIDENDO** (azul) / **BONO** (ámbar) |
| `frontend/src/components/home/EventsPreview.jsx:40` | preview de Home | `ex_dividend: 'Dividendo'` |
| `frontend/src/components/UpcomingEventsCard.jsx:3` | card de próximos eventos | *"cupones, amortizaciones, earnings, dividendos"* |
| `frontend/src/pages/Operations.jsx:1397-1406` | KPI de Movimientos | **"Cobrado"**, sub *"dividendos + intereses"* = `sumByType('DIVIDEND') + sumByType('INTEREST')` |
| `frontend/src/pages/Operations.jsx:1380-1383` | KPI filtrado | *"Total dividendos" / "Total intereses" · N pagos* |
| `frontend/src/pages/Operations.jsx:1067` | etiqueta del movimiento | `DIVIDEND: 'dividendo', INTEREST: 'interés'` |
| `frontend/src/pages/Operations.jsx:134-140` | carga de `/operations` | normaliza con `opPnlUsd` y guarda el nativo en `pnl_usd_native` |
| `frontend/src/pages/Insights.jsx:3097` | leyenda del gráfico | *"solo lo cobrado (ventas + dividendos + intereses)"* |
| `frontend/src/pages/Insights.jsx:4628` | nota de trades | *"No incluye depósitos, retiros, dividendos ni compras"* |
| `frontend/src/pages/More.jsx:31` | nav mobile | *"Movimientos — Trades + depósitos + dividendos"* |
| `backend/main.py:13340-13360` | `GET /api/export/operations.csv` | columna **"P&L USD"** (convertida acá a propósito) |
| `backend/main.py:13420-13612` | `GET /api/export/transactions.csv` | columna **"Tipo"** con `DIVIDENDO` / `INTERÉS` (sólo los importados) |
| `backend/main.py:32764-32780` | tarjeta de Reportes | "última operación cerrada" |
| `backend/main.py:25411-25516` | payload de la IA | `realized_pnl_usd` |
| `backend/ai/builders/insights.py:273-289` | builder `insights` | normaliza una vez y de ahí salen winners/losers/`pnl_by_ticker` |
| `backend/ai/builders/operations.py:46-60` | builder `operations` | P&L total, avg_win/avg_loss, payoff, expectancy |
| `backend/ai/builders/position_lots.py:19-40` | builder `position.lots` | *"en un bono los Cupón/Amortización aparecen como «lotes»"* |
| `backend/ai/builders/operation_trade.py:49-59` | builder `operation.trade` | rank del trade dentro del año |
| `backend/ai/builders/insights_attribution.py:55-68` | builder de atribución | realized por ticker |
| `backend/ai/builders/reports.py:100-111` | builder `reports` | `trades_year` (cuenta, sin conversión) |
| `backend/advisor_brief.py:190-203` | email del asesor | `_EVENT_LABELS` (incluye los `bond_*`, que nunca llegan — ver zonas grises) |
| `backend/main.py:35793-35809` | informe del período del asesor | `_CASHLIKE` → oculta `quantity` porque *"para rentas, operations.quantity guarda el MONTO"* |
| `backend/main.py:11701-11766` | endpoint de diagnóstico admin | *"P&L sin contrapartida de costo"* |
| `frontend/src/pages/Admin.jsx:1816` | panel admin | *"futuros, dividendos e intereses suman P&L realizado…"* |

### Dónde se persiste

**Tabla `operations`** (`backend/main.py:1200`, `backend/schema_pg.sql:1282-1301`; verificado también con `sqlite3 backend/trading.db ".schema operations"`):

| columna | qué guarda para renta | notas |
|---|---|---|
| `op_type` | `'Cupón'`, `'Amortización'`, `'Dividendo'`, `'Interés'`, `'Interés PF'` | texto libre, sin constraint |
| `pnl_usd` | **el monto** — en USD si vino del importador, en moneda del broker si vino de `bond_cashflow` o del PF | el nombre miente; ver `backend/realized_pnl.py:10-15` |
| `quantity` | el **monto** en el caso importado (`persister.py:983` pasa `round(amount, 4)`), `NULL` en el manual | por eso `_CASHLIKE` lo oculta en el informe del asesor (`main.py:35793`) |
| `currency` | moneda del flujo (manual/PF); **`NULL`** en el importado | `main.py:10484` |
| `fx_to_usd` | nativa por USD, sellado al alta (manual/PF); **`NULL`** en el importado | `main.py:1200` documenta *"NULL para cupones (no aplica) y para amorts viejas (legacy, pre Phase 3D)"* |
| `cost_basis_consumed` | **sólo** amortizaciones vía `bond_cashflow` | `main.py:10480`; en `main.py:37437` se afirma que *"está 100% NULL en las filas reales"* |
| `undo_meta_json` | foto de reverso: `{"src":"bond_cashflow","cash":…,"flow_type":…,"qty_decremented":…,"invested_decremented":…,"amort_lots":[…],"fx_source":…,"cross_currency_skipped":…}` | `main.py:10486-10500` |
| `entry_price`/`exit_price` | `NULL` | por eso el CSV del contador los clasifica como "futuros" (ver zonas grises) |
| `pnl_pct` | `NULL` | rompe el despeje del costo en `assetPnl.js:220-235` |

**Tabla `positions`**: la amortización **muta** los lotes (`quantity`, `invested`, `commissions`) — `backend/main.py:10630-10641` — o los borra si quedan en cero (`:10634`). Lo mismo hace el sweep del importador (`backend/importing/maturity.py:296+`).

**Tabla `monthly_entries.pnl_realized`**: derivada, no fuente. Se recompone desde `operations` con el criterio canónico (`backend/main.py:9530-9536`), y el importador la incrementa directo en el alta (`persister.py:996-997`).

**Tabla `bond_cashflow_skips`** (`backend/main.py:1330-1341`): `(user_id, broker, asset, date, reason, created_at)` con `UNIQUE(user_id, broker, asset, date)`. Es el único estado propio del *inbox* de pendientes.

**Tabla `financial_events`** (`backend/main.py:1309-1321`): cache cross-user de `ex_dividend` (y `earnings`) con `details` JSON (`dividend_per_share`). El comentario declara `'payment_date' | 'split'` pero **nadie los escribe** (ver zonas grises).

**Tabla `import_normalized_tx`**: guarda la fila cruda importada con `operation_type IN ('DIVIDEND','INTEREST')` y `gross_amount` nativo — es lo que reversa el borrado (`backend/main.py:12997-13008`).

**No se persiste nunca**: el cronograma teórico (cupones/amortizaciones futuros). Se recalcula al vuelo en el navegador desde `frontend/src/utils/bondMeta.js` + `bondSchedulesAR.js` en cada render (`backend/main.py:5698`: *"Para BONOS (cupones / amorts): los genera el frontend desde bondSchedule.js"*). Tampoco se persiste `realized_gain` del amort (`main.py:10505-10508`).

### ⚠️ Implementaciones divergentes

**No convergen.** Encontré nueve divergencias distintas.

---

#### D1 — El mismo evento vale 0, vale el cash entero, o vale cash − costo, según quién lo creó

| | Amortización IMPORTADA | Amortización MANUAL (`/api/bonds/cashflow`) |
|---|---|---|
| `op_type` | `'Amortización'` (`persister.py:976`) | `'Amortización'` (`main.py:10372`) |
| `pnl_usd` | **`0.0`** (`persister.py:980`) | **`net_amount`** = el cash entero (`main.py:10484`) |
| `monthly_entries.pnl_realized` | no lo toca (`persister.py:995`) | lo toca vía recalc (`main.py:9530`) |
| `cost_basis_consumed` | `NULL` | calculado FIFO (`main.py:10480`) |
| baja el nominal | sí, por el sweep (`maturity.py:296`) o por la pata VENTA del parser | sí, sólo si `decrement_quantity=True` (`main.py:10460-10462`) |

El propio código lo reconoce: `backend/main.py:14894-14900` bloquea el borrado del historial de un activo *"porque su P&L hoy se guarda distinto que el importado (bug pre-existente de bond-cashflow)"*.

**Qué pantalla ve cuál:** Cartera (`Positions.jsx:540-552`) *sí* neteta el `cost_basis_consumed` → muestra la ganancia real. Dashboard/Insights/Composición (`assetPnl.js:202`, `esRenta` **no** incluye `AMORTIZACION`) mandan la amortización a `b.realized` con el cash entero. El libro del asesor hace lo mismo (`main.py:37503`). Reportes suma el cash entero al realizado del período (`builder.py:844`). Consecuencia: para un AL30 comprado a 70, la amort de US$76,92 vale US$23,08 en Cartera y US$76,92 en el Dashboard.

---

#### D2 — Dos catálogos de amortización del mismo bono, ambos rotulados "verificado"

| | `frontend/src/utils/bondSchedulesAR.js:95` | `backend/pricing/bond_amortization.py:70-84` |
|---|---|---|
| AL30 / GD30 | `evenAmorts('2024-07-09', 13, 100/13)` = **13 × 7,6923 %** | `[("2024-07-09", 0.04), ("2025-01-09", 0.08), … ]` = **4 % + 12 × 8 %** |
| nivel declarado | `_verificationLevel: 'verified'` (`:96`) | *"Verificado (Rava/IOL)"* (`:68`) |
| GD46 | `evenAmorts('2024-07-09', 44, 100/44)` (`:186`) | **ausente** → `residual_factor` devuelve 1,0 (`:97-98` lo admite: *"mientras no esté, GD46 queda sobrevaluado"*) |
| AL41/GD41, AE38/GD38, AL35/GD35 | cronogramas completos (`:165`, `:141`, `:117`) | ausentes (`:99-101`) |

El frontend le dice al usuario que en enero de 2026 cobró 7,69 % de amortización de su AL30; el sweep del backend le baja el nominal como si hubiera cobrado 8 %. En julio de 2024 la diferencia es al revés (7,69 % vs 4 %).

**Qué pantalla ve cuál:** el inbox de pendientes, el modal, el calendario, la TIR y el timeline del detalle → frontend. La cantidad de nominales de la posición (o sea el VALOR de la cartera) → backend.

---

#### D3 — El mismo broker, dos exports, dos `op_type` distintos para el mismo cupón

- `backend/importing/parsers/balanz_resultados.py:255-263`: `if mov.startswith("cupon"): ... "tipo": "INTERES"` → termina en `op_type='Interés'`.
- `backend/importing/parsers/balanz_movimientos.py:554-555`: la misma renta → `_emit(base("DIVIDENDO" ...))` → termina en `op_type='Dividendo'`.

Es el mismo cupón del mismo bono en el mismo broker. Como los dos caen en `_NOT_A_TRADE` (`realized_pnl.py:74`) el win rate no cambia, pero el KPI "Total dividendos" vs "Total intereses" de `Operations.jsx:1380` sí, y `detect_dividend_heavy` los suma a los dos (`detectors.py:365`) mientras que el inbox de bonos no ve ninguno de los dos (busca `op_type ∈ {'Cupón','Amortización'}`, `pendingCashflows.js:68`).

---

#### D4 — El FX de un cupón en pesos: cuatro reglas

| lector | regla | cita |
|---|---|---|
| canónico (`realized_pnl`) | divide **sólo** si `op_type ∈ ('Cupón','Amortización')` **y** `currency='ARS'` **y** `fx_to_usd > 0`. Fila vieja sin FX → **se deja como está**, a propósito | `backend/realized_pnl.py:97-108` |
| Cartera (`bondCashflowsByKey`) | si falta el FX: `if (op.currency === 'ARS' \|\| (op.currency == null && amt > 1000)) fx = tcValuacion` — **infiere** con el dólar de HOY y un umbral de 1000 | `frontend/src/pages/Positions.jsx:524-531` |
| importador (dividendo/interés ARS) | `amount_usd = amount / tc_blue` — el **blue del config del usuario al momento del import**, no el de la fecha del pago | `backend/importing/persister.py:979` |
| importador (depósito/retiro) | prefiere `tx.gross_amount_usd`, estampado con el **TC de la fecha del flujo** | `backend/importing/persister.py:1062-1063` + `backend/importing/pipeline.py:76-80` |

Las dos últimas conviven en el mismo archivo: un depósito de 2021 se dolariza al dólar de 2021 y un dividendo de 2021 al dólar de hoy. Y `realized_pnl.py:56-61` documenta que hay ~398 filas viejas que quedan infladas "en TODOS los lectores (incluido el dashboard)" — pero Cartera **sí** las convierte con su heurística. Mismo cupón, dos números.

---

#### D5 — `Interés PF` está fuera del criterio canónico

`backend/main.py:9319` inserta `'Interés PF'` con `pnl_usd` en moneda nativa y `fx_to_usd = None` cuando es ARS (`main.py:9313`). No está en `_NATIVE_CCY_OPS` (`realized_pnl.py:78`) ni en `_NOT_A_TRADE` (`:74`). El propio módulo lo documenta como "Pendiente #3" (`realized_pnl.py:63-71`): *"el primer plazo fijo en pesos que alguien cobre entra inflado en los 4"*. Efecto: cuenta como **trade ganado** en el win rate y su monto en pesos se lee como dólares.

---

#### D6 — `Cupón`/`Amortización` cuentan como "trade cerrado" en las 6 definiciones de win rate

| definición | excluye | cita |
|---|---|---|
| canónica backend | `Compra`, `Dividendo`, `Interés`, `''`, `CONVERSION*` | `backend/realized_pnl.py:74` |
| Reportes (período) | idem | `backend/reporting/builder.py:845-852` |
| Reportes (highlights) | idem | `backend/reporting/builder.py:1778-1785` |
| win rate lifetime | idem | `backend/reporting/timeline.py:70` |
| behavioral | idem | `backend/behavioral.py:63-71` |
| `tradeStats.js` (Operaciones) | idem | `frontend/src/utils/tradeStats.js:31` |
| Insights | idem | `frontend/src/pages/Insights.jsx:1882-1888` |
| profileMatch | idem | `frontend/src/utils/profileMatch.js:449` |
| `ai/builders/profile_card.py` | idem | `backend/ai/builders/profile_card.py:94` |

Las nueve convergen entre sí **y las nueve están equivocadas del mismo modo**: ninguna excluye `Cupón`, `Amortización` ni `Interés PF`. Un cupón nunca es negativo, así que cada uno suma una "ganada". `backend/realized_pnl.py:34-53` lo mide y lo declara "Pendiente #1 · sin decidir a propósito (2026-08-18)".

---

#### D7 — Qué es "renta" para el bucket `income`: dos listas y un olvido

- `frontend/src/utils/assetPnl.js:202` y `backend/main.py:37503`: `DIVIDENDO` ∨ `INTER` ∨ `CUPON` (sin acentos). **Convergen** entre sí — hay un test de paridad que lo pinnea (`backend/tests/test_advisor_composition.py:710-720`).
- `backend/reporting/detectors.py:365`: `op_type in ("Dividendo", "Interés")` — igualdad exacta, **sin** `Cupón` ni `Interés PF`.

Consecuencia: una cartera 100 % bonos AR nunca dispara el insight "Los dividendos explicaron el X% del rendimiento", aunque toda su ganancia sean cupones. Y `Amortización` no está en **ninguna** de las dos (ver D1).

---

#### D8 — `/api/movements` pierde el `op_type` de todo lo manual

`backend/main.py:12473` calcula `op_type = (d.get("op_type") or "").upper()` y **no lo usa nunca más** (verificado: es la única aparición en todo el bloque `12470-12585`). Cada fila de `operations` sale como par `BUY`+`SELL` con `"type": "SELL"` hardcodeado (`main.py:12559`). O sea: un cupón cargado a mano aparece en "Todos los movimientos" como una **VENTA**, y por lo tanto:

- no entra en el KPI **"Cobrado · dividendos + intereses"** (`Operations.jsx:1397`, que suma `sumByType('DIVIDEND') + sumByType('INTEREST')`);
- no se puede borrar desde ahí: `_DELETABLE_CASHFLOW_TYPES = {"DEPOSIT","WITHDRAW","DIVIDEND","INTEREST","FEE","IMPUESTO"}` (`main.py:12827`) y un `SELECT` cae en el bloqueo de trades (`main.py:12829-12832`).

Los cupones **importados** sí salen como `DIVIDEND` (vienen por la rama de `import_normalized_tx`, `main.py:12584+`) y sí se pueden borrar. Mismo hecho económico, dos comportamientos según el origen.

---

#### D9 — El CSV del contador clasifica los cupones manuales como "futuros"

`backend/main.py:13481-13484`:
```
is_futuros = ("Futuros" in op_type or "futuros" in op_type
              or (r["quantity"] is None and r["entry_price"] is None and r["exit_price"] is None))
```
Un `Cupón` de `bond_cashflow` tiene los tres campos en `NULL` → entra por esa rama y se exporta con `"tipo": "VENTA"`, `monto = pnl_usd` (nativo) y `notas = "Cupón · P&L cerrado"` (`:13489-13500`). En cambio `operations.csv` (`main.py:13355`) sí lo convierte a USD y conserva el `op_type` real. Dos exports del mismo dato con clasificación distinta.

---

### Zonas grises

**G1 — `bond_cashflow` no recalcula el mensual.** [V] El endpoint (`backend/main.py:10346-10530`) hace exactamente dos cosas: `INSERT` en `operations` y `_adjust_cash`. No llama a `_recalc_pnl_realized_from_ops` ni a `_update_monthly_pnl_realized` (verificado leyendo el cuerpo completo y con `grep -n "_recalc_pnl_realized_from_ops" backend/main.py`, cuyas 12 llamadas están todas en otros endpoints: `delete_broker:4495`, `close_futuro:12370`, `_cascade_after_movement_delete:12925`, `create_operation:13879`, `update_operation:13946`, `_repair_user_snapshots:15705`, `_wipe_broker_data:20252`, y los backfills de admin). [I] Deduzco que un cupón registrado con el botón **no aparece en el "P&L realizado" del Dashboard** (que lee `monthly_entries`) hasta que algo *no relacionado* dispare un recalc — un import, un borrado, un cambio de broker. Sí aparece de inmediato en Cartera y en el detalle del bono, que leen `operations` directo. No encontré ninguna nota en el código que reconozca esto.

**G2 — El pago "mixto" se registra como Cupón por el total.** [V] `frontend/src/pages/Positions.jsx:377-386`: `const flowType = item.kind === 'amortizacion' ? 'amortization' : 'coupon'` y para `'mixto'` manda `amount: item.total` (cupón + amortización juntos), con el comentario *"'mixto' se registra como Cupón (comportamiento existente) → el monto es el crédito completo que recibió el user"*. Efecto: la parte de capital devuelto queda contabilizada como renta pura y el nominal no baja. Es exactamente el bug que `persister._is_amort_capital_return` arregla del lado del importador.

**G3 — El evento `payment_date` está declarado pero nadie lo escribe.** [V] Aparece en el comentario del esquema (`backend/main.py:1312`), en `_EVENT_LABELS` del asesor (`backend/advisor_brief.py:193`) y en `eventTypeLabel` (`frontend/src/utils/upcomingEvents.js:171`). Pero `_fetch_yf_events` (`backend/main.py:5889-5960`) sólo emite `'earnings'` y `'ex_dividend'` — pese a que su propio docstring dice *"Trae earnings + ex-dividend + dividend payment dates"* (`:5890`). Ningún otro escritor de `financial_events` existe (`grep -rn "payment_date" backend/ --include="*.py"` sólo devuelve billing y ese label). O sea: la app promete "Pago dividendo" y nunca lo muestra.

**G4 — Los labels `bond_*` del asesor son código muerto.** [V] `backend/advisor_brief.py:195-198` define `bond_coupon`, `bond_amort`, `bond_coupon_amort`, `bond_maturity`, pero el brief los busca en `financial_events` (`advisor_brief.py:249`), tabla en la que *por diseño* nunca entran eventos de bonos: *"Para eventos de BONOS … NO usamos esta tabla — esos se generan runtime en frontend"* (`backend/main.py:1305-1307`). El email del asesor no puede avisar un cupón: en el radar cross-cliente los bonos AR se filtran explícitamente (`backend/main.py:35320-35321`).

**G5 — `op_type='Renta'` no lo escribe nadie, pero tres guards lo buscan.** [V] Aparece en `backend/main.py:14528`, `:14666` y `:14889` dentro de `op_type IN ('Cupón','Cupon','Amortización','Amortizacion','Renta', …)`. Grepeé todos los `INSERT INTO operations` (`main.py:10479`, `:11312`, `:12352`, `:13854`, `:15109`, `:9319`) y ninguno escribe `'Renta'`; el importador mapea `RENTA → OP_DIVIDEND → 'Dividendo'` (`schema.py:99`, `persister.py:978`). Las variantes sin tilde (`'Cupon'`, `'Amortizacion'`) tampoco las escribe nadie. Los guards funcionan igual por las variantes con tilde, pero la lista da una falsa sensación de cobertura.

**G6 — `getBondMeta` no normaliza el ticker; el backend sí.** [V] `frontend/src/utils/bondMeta.js:164-167`: `return BOND_META[ticker.toUpperCase()] || null`. Un `AL30D` (pata MEP) o `AL30.BA` no matchea → sin schedule → **sin cupones detectados, sin TIR, sin inbox**. El backend, en cambio, tiene `_strip_bond_suffix` que lleva `AL30D → AL30` (`backend/pricing/bond_amortization.py:37-48`) y por lo tanto *sí* le amortiza el nominal. Un mismo bono en su pata dólar: el backend le baja los nominales, el frontend no le muestra nunca un cupón. [I] Esto encaja con el patrón "AL30D es otro ticker que AL30" que ya está documentado en otros lados del repo.

**G7 — El cobro estimado del dividendo usa el ÚLTIMO dividendo pagado.** [V] `backend/main.py:5941`: `div_amount = info.get('lastDividendValue')`, guardado como `details['dividend_per_share']` (`:5948`). `frontend/src/pages/Events.jsx:941-944` lo multiplica por las acciones que tenés y rotula el resultado en `'USD'` hardcodeado. Para un CEDEAR el `shares` de Rendi son CEDEARs, no acciones subyacentes, y el ratio no se aplica en ningún lado de ese cálculo. [I] El número que ve el usuario ("vas a cobrar US$X") es el dividendo *pasado* por una cantidad que puede estar en otra unidad.

**G8 — `amortSchedule` está en el catálogo pero `bondMeta.amortStart` es el que habilita el toggle.** [V] `BondCashflowModal.jsx:133`: `const isAmortizingBond = !!(bondMeta?.amortSchedule || bondMeta?.amortStart)`. Los soberanos del canje sí traen `amortSchedule` (`bondSchedulesAR.js`), así que funciona; pero los TZX (cero-cupón, `bondMeta.js:124-133`) y las ONs corporativas (`bondMeta.js:135-150`) no tienen ninguno de los dos → para ellos el toggle "bajar nominales" queda deshabilitado aunque un rescate parcial sí devuelva capital.

**G9 — `_amortize_position_fifo` asume `1 VN = 1 USD face`.** [V] El docstring lo dice (`backend/main.py:10613-10617`) y agrega *"Para bonos CER con face ajustado, la math sería distinta — pero esos bonos son bullet, no amortizantes, así que este código nunca se invoca con ellos"*. No hay ningún guard que lo garantice: `bond_cashflow` acepta cualquier `asset` y sólo chequea la desproporción 1,5× (`main.py:10456`). El TX26 del test de producción (`backend/tests/test_bond_amort_capital_return.py:34`) es justamente un bono CER *con* amortización.

**G10 — Los mismos datos del canje 2020 viven en tres archivos con narrativas distintas.** [V] `backend/ai/ar_bonds_metadata.py:47` describe AL29 como *"Cupón step-up (0.5%→1.0%→1.5%→1.75%)"* (cuatro tramos) mientras `frontend/src/utils/bondSchedulesAR.js:68-72` define tres (`0.500 → 1.000 → 1.750`). La descripción de `ar_bonds_metadata` es lo que ve el LLM cuando el usuario le pregunta por el bono; el schedule es lo que se usa para calcular. Ninguno de los dos referencia al otro.

**G11 — La contribución al P&L de la tabla USD suma monedas sin convertir (probablemente inocuo).** [V] `frontend/src/pages/Positions.jsx:2589-2592` hace `adjPnl = c.pnl + pnlContrib`, donde `c.pnl` está en USD y `pnlContrib` en la moneda nativa del broker — a diferencia de la tabla ARS (`:2284-2291`), que usa `pnlContributionUsd`. [I] Como esa tabla sólo renderiza brokers USD/USDT, nativo == USD y el número coincide; pero es la misma clase de bug que ya mordió en `bondCashflowsByKey` y no hay nada que impida que una fila ARS caiga ahí.

**G12 — Lo que hace `preview.py` con la estimación.** [V] `backend/importing/preview.py:70-75` cuenta `OP_DIVIDEND` y `OP_INTEREST` dentro de `operations_to_create`, lo cual es correcto — pero `cash_movements` (`:76-77`) sólo suma `DEPOSIT + WITHDRAW + FEE`, cuando `_persist_dividend_or_interest` **también** mueve cash (`persister.py:975`). El preview le sub-declara al usuario cuántos movimientos de efectivo va a generar el import.

**G13 — El replay del ledger no ve los cupones manuales.** [V] `backend/ledger_replay.py:89`: `_CASH_MAS = ("DEPOSIT", "SELL", "DIVIDEND", "INTEREST", "FUTURES_PNL")`, y la query trabaja sobre `import_normalized_tx` (`:105+`). Un cupón cargado con el botón acreditó cash real (`main.py:10502`) pero no existe para el replay. [I] Cualquier reconciliación "saldo reconstruido vs saldo actual" va a reportar un faltante del tamaño de los cupones manuales del usuario.

**G14 — El win rate del período del asesor y el del usuario usan el mismo `_is_trade` roto, pero el informe del asesor además oculta `quantity` de las rentas.** [V] `backend/main.py:35793-35807` define `_CASHLIKE = ("Dividendo","Interés","Interes","Amortización","Amortizacion","Renta")` — nótese que **`Cupón` no está en la lista**. Un cupón cargado con el botón (que tiene `quantity=NULL`) sale bien igual; uno importado (que tiene `quantity` = el monto, `persister.py:983`) sólo sale bien si cayó en `Dividendo`/`Interés`. Es una cuarta lista de "qué es renta", distinta de las tres de D7.

**Lo que no pude determinar:**

- Si `positions.entry_date` es confiable como orden FIFO para amortizar (`main.py:10563` usa `ORDER BY COALESCE(entry_date,'9999-12-31') ASC, id ASC`, sin hora) — **no encontrado** un desempate documentado para lotes del mismo día.
- Cuántas filas reales tienen `cost_basis_consumed` no nulo. `backend/main.py:37437` afirma *"está 100% NULL en las filas reales"*, pero `Positions.jsx:541-552` construye toda su lógica de P&L de amortización sobre esa columna. No verifiqué contra datos (la regla dice no hacer SELECT de datos de usuarios) — pero si la afirmación del backend es cierta, la rama `cbConsumed != null` de Cartera nunca corre y **toda amortización aporta 0 al P&L** ahí, mientras aporta el cash entero en el Dashboard.
- Si el `fx_source` que se guarda en `undo_meta_json` (`main.py:10494`) lo lee alguien. `grep -rn "fx_source" backend/ frontend/src` sólo lo muestra en el escritor y en el response del endpoint — **no encontrado** ningún lector.
