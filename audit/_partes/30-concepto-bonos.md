## Bonos: escala per-100, paridad, vencimiento y flujos

### Definición según el código

En Rendi «un bono» no es un concepto único: son **cinco conceptos separados que casi nunca se hablan entre sí**, y cada uno tiene su propia definición operativa.

**1. La escala canónica interna es PER-1 VN (por un nominal), no per-100.** [V]
Esto es una decisión de Rendi, no del mercado. El mercado argentino cotiza renta fija "por cada 100 valores nominales" (paridad); Rendi decidió que en `positions`, en `import_normalized_tx`, en `/api/prices` y en toda la valuación el precio sea **por 1 nominal**, para que la aritmética de la cartera sea universal (`valor = quantity × price`, igual que una acción). El docstring lo dice literal: *"Factor para llevar el cost basis de un bono a per-1 VN (canónico del sistema)"* (`backend/importing/recompute_backfill.py:157-166`).

Consecuencia directa: **todo el sistema está lleno de traductores per-100 → per-1**, en el parser, en el normalizador, en el persister, en el rebuild, en el resolver de precio y en un backfill retroactivo. Cada uno usa un criterio distinto para decidir "esto vino per-100":

| capa | criterio para detectar per-100 |
|---|---|
| parser Bull Market | `\|q·p − 100·monto\| < \|q·p − monto\|` |
| persister / normalizer / rebuild | `ratio = (precio×cant)/monto` ∈ [98, 102] **y** `asset_type ∈ {BOND, OTHER, ''}` |
| resolver de precio (data912) | `usd_equiv ≥ 3.0 USD` |
| backfill de costo | `10 < costo_unitario/precio_mercado_per1 < 1000` **y** `costo_usd ≥ 3.0` |
| foto de tenencia | `\|q·cotiz/100 − importe\| ≤ tol` (y el precio se re-deriva como `importe/qty`, así la escala se auto-resuelve) |

**2. La única capa que trabaja EN per-100 es el motor de cronograma del frontend.** [V]
`bondSchedule.js` genera el cronograma "por 100 de face original" (`frontend/src/utils/bondSchedule.js:26-28`) y `bondPricing.js` declara el mismo contrato de unidad (`frontend/src/utils/bondPricing.js:8-12`). Por eso el consumidor tiene que hacer **el viaje de ida y vuelta**: multiplica el precio per-1 ×100 para calcular la TIR (`BondDetail.jsx:108-110`) y divide los flujos ÷100 ×quantity para mostrar montos (`bondSchedule.js:374-376`).

**3. "Paridad" NO se calcula en ningún lado como métrica.** [V]
No hay ninguna función que compute `precio / valor_técnico` ni `precio / 100`. La palabra aparece solo (a) en comentarios que explican la escala (`backend/main.py:7185`, `7353-7354`), (b) en textos de marketing y del prompt de IA (`frontend/src/pages/keywords/BonosAR.jsx:8`, `backend/main.py:20481`), y (c) con un significado COMPLETAMENTE DISTINTO en el parser de Bull Market, donde "compra/venta paridad" es la **pata dólar de una operación MEP** (`backend/importing/parsers/bullmarket.py:49`, `556-575`). El landing promete "paridad" como feature; el código no la muestra.

**4. "Vencimiento" tiene DOS definiciones que no comparten fuente.** [V]
- **Frontend**: `bondMeta.maturity`, una tabla estática de 41 tickers (`frontend/src/utils/bondMeta.js:90-161`). Sirve para el cronograma, la TIR y el label "vence AAAA-MM-DD".
- **Backend**: se **decodifica del ticker** (`S31O5` → 2025-10-31) o se **parsea del nombre del instrumento** (`"...V.14/02/25..."`), en `backend/importing/maturity.py:73-124`. Sirve para BORRAR la posición cuando venció.
Son dos universos disjuntos: el backend no conoce `bondMeta`, el frontend no conoce `letra_maturity`.

**5. "Flujos" (cupón / amortización) tiene TRES semánticas de P&L distintas** según por dónde entró el cobro. Ver §Implementaciones divergentes.

**6. La amortización se modela como reducción de CANTIDAD, no de precio.** [V]
El mercado cotiza el bono amortizante "por nominal residual"; Rendi guarda el nominal comprado. Para reconciliar, un sweep multiplica la cantidad por un `residual_factor(ticker, fecha) ∈ [0,1]` (`backend/pricing/bond_amortization.py:125-142`) y baja `quantity`, `invested` y `commissions` proporcionalmente (`backend/importing/maturity.py:379-402`). El factor sale de una tabla hardcodeada que **hoy solo cubre 4 tickers** (AL29/GD29/AL30/GD30).

---

### Dónde se calcula

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `backend/importing/persister.py:492-546` | `reconciled_unit_price` | **EL guard canónico de escala.** Si `precio×cant` contradice al `monto` por exactamente ×100 (renta fija) o ×1000 (FCI), deriva el precio del monto | `ratio = (up * q) / ga` → `if at in ("BOND","OTHER",""): if abs(ratio / _ESCALA_PER_100 - 1) <= _TOL_ESCALA: return ga / q` | **fuente canónica** |
| 2 | `backend/importing/persister.py:487-489` | constantes | Declara las dos únicas convenciones reconocidas y la tolerancia | `_ESCALA_PER_100 = 100.0` · `_ESCALA_VCP_1000 = 1000.0` · `_TOL_ESCALA = 0.02` | fuente |
| 3 | `backend/importing/normalizer.py:554-557` | `normalize_rows` | Aplica el guard #1 al normalizar (imports nuevos) | `tx.unit_price = round(reconciled_unit_price(p, q, a, tx.asset_type), 8)` | consumidor de #1 |
| 4 | `backend/importing/persister.py:566` | `_persist_buy` | Aplica el guard al persistir la compra | `unit = float(reconciled_unit_price(tx.unit_price, qty, tx.gross_amount, tx.asset_type) or 0)` | consumidor de #1 |
| 5 | `backend/importing/persister.py:665` | `_persist_sell_fifo` | Idem en la venta (sin esto el P&L se inflaba ×99) | `unit_eff = float(reconciled_unit_price(tx.unit_price, qty_to_sell, tx.gross_amount, ...))` | consumidor de #1 |
| 6 | `backend/importing/rebuild.py:268` | `_replay_asset` (BUY) | Re-aplica el guard sobre tx YA guardadas → el rebuild se auto-sana | `unit = _num(reconciled_unit_price(ev["unit_price"], ev["quantity"], ev["gross_amount"], ev.get("asset_type")))` | consumidor de #1 |
| 7 | `backend/importing/rebuild.py:309` | `_replay_asset` (SELL) | Idem en la venta del replay | `exit_price = _num(reconciled_unit_price(ev["unit_price"], ev["quantity"], ev["gross_amount"], ev.get("asset_type")))` | consumidor de #1 |
| 8 | `backend/main.py:14564-14566` | borrado de una venta importada | Espeja la fórmula del persister para revertir el cash con precisión byte a byte | `_ueff = _import_persister.reconciled_unit_price(...)` · `proceeds_native = float(_ueff or 0) * float(src["quantity"] or 0) - float(src["fees"] or 0)` | consumidor de #1 |
| 9 | `backend/main.py:14689`, `14969`, `14974` | undo / journal de borrado | Mismo guard en los caminos de deshacer | `invested = float(_import_persister.reconciled_unit_price(...))` | consumidor de #1 |
| 10 | `backend/main.py:7329-7356` | `_resolve_ar_bond_price` | **La otra fuente canónica de escala**: precio live de data912 → per-1 | `usd_equiv = raw if not is_ars else (raw / _data912_peso_per_usd(prices))` · `return raw / 100.0 if usd_equiv >= 3.0 else raw` | **fuente canónica (pricing)** |
| 11 | `backend/main.py:7245-7256` | `_data912_peso_per_usd` | MEP implícito para poder comparar un quote ARS contra el umbral de 3 USD | `if a and d and a > 0 and 0 < d < 1000: return a / d` (refs: AL30, GD30, AL35, AE38, GD35); fallback `1450.0` | fuente |
| 12 | `backend/main.py:7350` | `_resolve_ar_bond_price` | Mapeo de sufijos: `.BA` → ticker base (ARS); sin sufijo → base+`D` (USD MEP) | `raw = prices.get(base) if is_ars else prices.get(base + 'D')` | fuente |
| 13 | `backend/main.py:7359-7369` | `_bond_price_per1` | Precio per-1 en la moneda pedida; referencia de mercado del backfill | `if (currency or "").upper() == "ARS": return _resolve_ar_bond_price(str(symbol) + ".BA")` | consumidor de #10 |
| 14 | `backend/main.py:7372-7383` | `_is_data912_bond` | Universo de renta fija SIN lista curada (arg_bonds + arg_corp) | `return bool(d) and (t in d or (t + "D") in d)` | fuente (tipado) |
| 15 | `backend/importing/recompute_backfill.py:157-168` | `bond_per100_factor` | **Tercera** detección de escala: por ratio costo/mercado | `ratio = unit_cost / market_per1` · `return 0.01 if 10.0 < ratio < 1000.0 else 1.0` | fuente (backfill) |
| 16 | `backend/importing/recompute_backfill.py:171-222` | `normalize_bond_units` | Aplica ÷100 al cost basis guardado per-100, con guard anti-distressed por magnitud absoluta | `if usd_cost < 3.0: continue` · `new_inv = round((inv or 0) * factor, 6)` | consumidor de #15 |
| 17 | `backend/pricing/bond_amortization.py:125-142` | `residual_factor` | Fracción del nominal ORIGINAL viva a una fecha | `paid = sum(frac for (d, frac) in sched if d <= ref)` · `r = 1.0 - paid` | **fuente canónica (amortización backend)** |
| 18 | `backend/pricing/bond_amortization.py:54-93` | `_AMORT_SCHEDULES` | Cronogramas verificados: AL29/GD29 (10×10%), AL30/GD30 (4% + 12×8%) | `("2024-07-09", 0.04), ("2025-01-09", 0.08), …` | fuente (datos) |
| 19 | `backend/pricing/bond_amortization.py:105-122` | `is_amortizing_bond` / `_lookup_schedule` | Resuelve por ticker base o, si falla, por substring del NOMBRE | `for tk, s in _AMORT_SCHEDULES.items(): if tk in up: return s` | fuente |
| 20 | `backend/importing/maturity.py:296-411` | `sweep_bond_amortizations` | Baja el nominal a `(comprado−vendido)×R`, proporcional en todos los lotes | `target = original * r` · `factor = target / current` · `new_qty = lot_qty * factor` | **fuente canónica (escritura)** |
| 21 | `backend/importing/maturity.py:250-291` | `_bond_genuine_net` | Base "original" del sweep: Σ BUY − Σ SELL sobre el PAR de brokers, cancelando conductos MEP y excluyendo las VENTAS-amortización | `net += q if e["operation_type"] == OP_BUY else -q` | fuente |
| 22 | `backend/importing/maturity.py:73-97` | `letra_maturity` | **Vencimiento decodificado del ticker** (letra/LECAP AR) | `_LETRA_RX = ^([A-Z])(\d{1,2})([EFMAYJLGSOND])(\d)$` · `d = date(2020 + int(yy), month, int(dd))` | **fuente canónica (vto. backend)** |
| 23 | `backend/importing/maturity.py:100-124` | `maturity_from_name` | Vencimiento parseado del nombre; prefiere las fechas marcadas con "V"/"V." y de ésas la ÚLTIMA | `v_matches = _VENC_DATE_RX.findall(name)` · `matches = v_matches or _BARE_DATE_RX.findall(name)` · `dd, mm, yy = matches[-1]` | fuente |
| 24 | `backend/importing/maturity.py:136-147` | `synth_letra_ticker` | Ticker sintético prefijo `X` para letras exportadas sin ticker | `return f"X{int(d)}{code}{int(y) % 10}"` | fuente |
| 25 | `backend/importing/maturity.py:182-247` | `sweep_matured_letras` | **Borra** posiciones de letras/bonos vencidos dentro de la ventana de datos importada | `mat = letra_maturity(p["asset"]) or maturity_from_name(name_map.get(...))` · `if mat > ref_date: continue` · `DELETE FROM positions …` | consumidor de #22/#23 |
| 26 | `backend/importing/proyeccion.py:151-159` | `proyectar` | Corrige hacia atrás la cantidad de un bono amortizante y marca las letras vencidas como no reconciliables | `qty[a] = qty[a] * (rf_d / rf_hoy)` | consumidor de #17 |
| 27 | `frontend/src/utils/bondSchedule.js:132-272` | `generateSchedule` | **EL motor de flujos.** Arma el cronograma completo por 100 de face, con step-up, amort y ajuste CER | `couponPerPeriod = rateAnnual / (12 / months)` · `couponAmountNominal = couponPerPeriod * face / 100` · `face = Math.max(0, face - amortNominal)` | **fuente canónica (flujos)** |
| 28 | `frontend/src/utils/bondSchedule.js:161-175` | rama zero-cupón | Pago único = 100 × factor CER al vencimiento | `const amortAjustado = +(100 * factor).toFixed(6)` | fuente |
| 29 | `frontend/src/utils/bondSchedule.js:154-159` | `adjFactor` | Factor CER = CER(fecha)/CER(emisión), con LOCF | `return val / cerBase` | fuente |
| 30 | `frontend/src/utils/bondSchedule.js:262-269` | sanity de face | Si sobró face por redondeo de `100/N`, lo tira al último pago | `last.amort = +(last.amort + face).toFixed(6)` | fuente |
| 31 | `frontend/src/utils/bondSchedule.js:314-353` | `estimateYieldDetailed` | TIR: arma cashflows con el day-count del prospecto y resuelve | `const dirty = priceIsDirty ? priceInput : (priceInput + accrued)` · `cashflows = rest.map(p => ({ t: dayCountFraction(base, p.date, dayCount), amount: p.total }))` | fuente |
| 32 | `frontend/src/utils/bondSchedule.js:369-380` | `nextPaymentForPosition` | **Traductor per-100 → posición** | `coupon: +(next.coupon * quantity / 100).toFixed(2)` | fuente |
| 33 | `frontend/src/utils/bondPricing.js:52-119` | `dayCountFraction` | 30/360 US, 30E/360, ACT/360, ACT/365, ACT/365.25, ACT/ACT-ISDA | `const days = 360 * (y2 - y1) + 30 * (m2 - m1) + (d2 - d1); return days / 360` | fuente |
| 34 | `frontend/src/utils/bondPricing.js:135-156` | `computeAccrued` | Intereses corridos, lineales sobre el período | `const frac = Math.max(0, Math.min(1, elapsed / totalPeriod)); return nextCoupon * frac` | fuente |
| 35 | `frontend/src/utils/bondPricing.js:186-290` | `yieldToMaturity` | TIR: bracket → bisect coarse → Newton → bisect fine | `let s = -dirtyPrice; for (const x of validCf) s += x.amount / Math.pow(1 + r, x.t)` | fuente |
| 36 | `frontend/src/utils/bondSchedulesAR.js:63-192` | `CANJE_2020_*` | Cronogramas de los 11 soberanos: step-up + amortSchedule | `amortSchedule: evenAmorts('2024-07-09', 13, 100 / 13)` (AL30/GD30) | **fuente (datos frontend)** |
| 37 | `frontend/src/utils/bondSchedulesAR.js:205-270` | `validateBondSchedule` | Invariantes: amorts suman 100, fechas ISO, orden, cobertura del cupón | `if (Math.abs(sum - 100) > 0.01) errors.push(...)` | fuente |
| 38 | `frontend/src/utils/bondMeta.js:90-161` | `BOND_META` | Tabla estática de 41 tickers (11 soberanos, 6 CER, 16 ONs, 8 ETFs) | `TX26: { currency: 'ARS', …, cerEmissionDate: '2020-08-04' }` | **fuente (datos frontend)** |
| 39 | `frontend/src/utils/bondMeta.js:218-241` | `formatCouponLabel` | Label del cupón: TNA + cupón por período | `const perPeriod = +(rate / ppy).toFixed(4)` | consumidor |
| 40 | `frontend/src/utils/pendingCashflows.js:98-161` | `detectPendingCashflows` | Inbox: pagos teóricos pasados sin operation ni skip | `const factor = p.quantity / 100` · `total: +(pmt.total * factor).toFixed(2)` | consumidor de #27 |
| 41 | `frontend/src/utils/upcomingEvents.js:48-96` | `upcomingBondEvents` | Eventos futuros de bonos (calendario) | `const totalAmt = pmt.total * p.quantity / 100` · `const isMaturity = pmt.date === maturityDate` | consumidor de #27 |
| 42 | `frontend/src/utils/bondCashflowFx.js:58-106` | `suggestBrokerAmount` | Convierte el flujo teórico a la moneda del broker con el TC de la fecha del pago | `amount: round2(theoreticalAmount * tc), operacion: 'multiplicar', fxToUsdForRow: tc` | consumidor |
| 43 | `backend/main.py:10346-10534` | `POST /api/bonds/cashflow` | Registra el cobro: operation + cash + (opcional) decrementa VN | `net_amount = data.amount - commissions` · `face_to_decrement = data.face_amortized if … else net_amount` | **fuente canónica (persistencia de flujos)** |
| 44 | `backend/main.py:10588-10659` | `_amortize_position_fifo` | Reduce FIFO qty/invested/commissions por el face amortizado | `ratio = take / lot_qty` · `new_invested = (lot['invested'] or 0) * (1 - ratio)` | fuente |
| 45 | `backend/main.py:10552-10585` | `_compute_amort_cost_basis_fifo` | Versión read-only: cuánto cost basis consumiría | `total_consumed += (lot['invested'] or 0) * ratio` | fuente |
| 46 | `backend/importing/persister.py:904-935` | `_is_amort_capital_return` | Detecta la amortización cash-only (sin cantidad) → devolución de capital P&L-neutral | `if "amortiz" not in (notes or "").lower(): return False` | fuente |
| 47 | `frontend/src/utils/valuation.js:437-454` | `trustMktValue` | **Guard anti per-100**: renta fija se clampea a [0.02×, 4×] del costo, incluso con override manual | `return fixed ? (mult <= 4 && mult >= 0.02) : (mult <= 50 && mult >= 0.002)` | fuente (frontend) |
| 48 | `backend/snapshots_job.py:42-54` | `_trust_mkt_value` | Port backend del anterior (curva de snapshots) | `return (0.02 <= mult <= 4) if fixed else (0.002 <= mult <= 50)` | port de #47 |
| 49 | `backend/behavioral.py:47-62` | `_trust_mkt_value_usd` | Tercer port (Análisis / IA) — **sin** el parámetro `has_override` | `if (asset_type or '').upper() in _FIXED_INCOME_TYPES: return 0.02 <= mult <= 4` | port de #47 |
| 50 | `backend/importing/tenencia.py:786-804` | parser foto Bull Market | Detecta per-100 en la foto y **re-deriva el precio del importe** | `elif abs(prod / 100.0 - value) <= tol: per100 = True` · `price_per1=value / qty` | fuente (foto) |
| 51 | `backend/importing/tenencia.py:912-932` | parser foto IOL | Idem, con la vuelta de que en USD el importe viene en ARS | `per100 = (abs(prod / 100.0 - importe) <= tol and abs(prod - importe) > tol)` | fuente (foto) |
| 52 | `backend/importing/tenencia.py:1489-1510` | parser foto Balanz | Idem ("en este export Balanz cotiza los bonos per-1; la detección queda por robustez") | `elif abs(prod / 100.0 - value) <= tol: per100 = True` | fuente (foto) |
| 53 | `backend/importing/tenencia.py:404-491` | `marcar_bonos_amortizantes` | **Freno**: un `to_seed` sobre bono amortizante no se auto-aplica (escalas incomparables) | `if abs(float(qty_actual.get(h.ticker, 0.0))) <= eps: continue` → si no, `rec.requieren_aprobacion.add(h.ticker)` | fuente |
| 54 | `backend/importing/parsers/bullmarket.py:687-690` | parser movimientos BMB | Cuarta detección per-100, por comparación de residuos | `if q and p and monto and abs(q * p - 100 * monto) < abs(q * p - monto): p = p / 100.0` | fuente |
| 55 | `backend/importing/parsers/iol.py:699-712` | parser movimientos IOL | Esquiva el problema: **ignora la columna Precio** y deriva `precio = |Monto|/cantidad` | `precio = repr(monto_cash / qty_val)` | fuente |
| 56 | `backend/main.py:16336-16346` | `/api/admin/diagnose-sell-fx` | Bucket `B7_ESCALA_PER_100`: ventas cuya firma delata un bono per-100 | `elif abs(s / 100.0 - 1) <= 0.02: bucket = "B7_ESCALA_PER_100"` | consumidor (diagnóstico) |
| 57 | `backend/main.py:16617-16663` | `/api/admin/diagnose-scale` | Mide `k = precio×cant/monto` en la FUENTE y lo bandea por parser | `elif 90 <= k <= 110: banda = "k~100 (per-100)"` | consumidor (diagnóstico) |
| 58 | `frontend/src/components/BondDetail.jsx:108-115` | `BondDetailBody` | **El viaje de vuelta**: precio per-1 ×100 para alimentar el motor per-100 | `const pricePer100Clean = priceInBondCurrency != null && priceInBondCurrency > 0 ? priceInBondCurrency * 100 : null` | consumidor de #27/#31 |
| 59 | `frontend/src/components/RentaFijaSections.jsx:294-307` | `BondCardRow` | Mismo ×100 para la TIR de la card | `tir = estimateYieldDetailed(p.asset, pBond * 100, todayIso(), cerOpts)?.ytm ?? null` | consumidor de #31 |
| 60 | `backend/realized_pnl.py:78-107` | `realized_usd_sql` | Cupón/Amortización guardan el monto en moneda NATIVA → se divide por `fx_to_usd` | `CASE WHEN op_type IN ('Cupón','Amortización') AND currency = 'ARS' AND fx_to_usd > 0 THEN pnl_usd / fx_to_usd ELSE pnl_usd END` | fuente |
| 61 | `frontend/src/pages/Positions.jsx:496-560` | `bondCashflowsByKey` | Suma cobros y calcula el **aporte al P&L** restando el cost basis del amort | `pnlContrib = amt - cbConsumed` | fuente (frontend) |

---

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `frontend/src/components/BondDetail.jsx:191` | Ficha del bono | «Vencimiento» |
| `frontend/src/components/BondDetail.jsx:195` | Ficha | «Cupón» + tooltip `formatCouponTooltip` |
| `frontend/src/components/BondDetail.jsx:200` | Ficha | «Cronograma aproximado — verificar contra prospecto.» (solo si `_verificationLevel === 'approx'`) |
| `frontend/src/components/BondDetail.jsx:204-211` | Ficha CER | «Capital ajustado por CER · factor hoy ≈ X×» / «Serie CER no disponible — flujos en nominal sin ajuste.» |
| `frontend/src/components/BondDetail.jsx:227-236` | Tu inversión | «cobrado en total», «% del capital recuperado», «Cupones», «Amortizaciones», «De eso es ganancia real», «Devolución de tu capital» |
| `frontend/src/components/BondDetail.jsx:272-283` | Rendimiento | «TIR efectiva anual a precio de hoy» / «TIR real (sobre CER) a precio de hoy» · «· aproximada» si no convergió |
| `frontend/src/components/BondDetail.jsx:295-301` | Rendimiento | «Próximo pago · fecha», «~USD X», «por tus N nominales» |
| `frontend/src/components/BondDetail.jsx:310-344` | Timeline | «Cronograma de cobros» con estados `cobrado / sin confirmar / sin registro / estimado` y `cupón / amortización / cupón + amort` |
| `frontend/src/components/RentaFijaSections.jsx:353-395` | Card de renta fija | «Nominales», «Valor», «TIR» / «TIR real», «Cobrás <fecha> ~USD X» |
| `frontend/src/components/RentaFijaSections.jsx:447-450` | Card | barra «% del capital recuperado» |
| `frontend/src/components/RentaFijaSections.jsx:320-322` | Card | tags «ARS/USD», «CER», «Ley AR» / «Ley NY» |
| `frontend/src/components/PendingCashflowsBanner.jsx:52-56` | Banner Cartera | «Tenés N cobros para confirmar» |
| `frontend/src/components/PendingCashflowsBanner.jsx:114` | Banner | «USD X cupón + USD Y amort» |
| `frontend/src/components/PendingCashflowsBanner.jsx:147` | Banner | «Las amortizaciones pueden reducir tus nominales — revisá antes de registrar.» |
| `frontend/src/components/BondCashflowModal.jsx:276` | Modal de cobro | «<emisor> · vence <fecha>» |
| `frontend/src/components/BondCashflowModal.jsx:287-296` | Modal | «Pre-llenado según cronograma: <fecha> · estimado <ccy> X por N VN» + warning cross-currency |
| `frontend/src/pages/Positions.jsx:4189` | Detalle de activo | «Vence <fecha>» / «Sin vencimiento (ETF)» |
| `frontend/src/pages/Events.jsx:57,68` | Agenda | filtro «Bonos» |
| `frontend/src/pages/Events.jsx:746,895-908` | Agenda | «Vencimiento de <ticker>» / «Pago de <ticker>» / «Amortización <ccy> X» |
| `frontend/src/components/UpcomingEventsCard.jsx:94-100` | Card de próximos eventos | «cobrás ~+<ccy> X» |
| `frontend/src/utils/upcomingEvents.js:177,192` | labels | «Vencimiento de bono» 🏁 |
| `backend/advisor_brief.py:195-198` | Email del asesor | «Cupón de bono», «Amortización», «Cupón + amortización», «Vencimiento de bono» |
| `frontend/src/pages/PositionsMobile.jsx:2802` | Cartera mobile | unidad «nominales» |
| `frontend/src/pages/Insights.jsx:1182` | Análisis | «Los bonos y los FCI no tienen serie histórica…» |
| `frontend/src/pages/Insights.jsx:2931` | Análisis | «Bonos, letras, FCI, plazos fijos y efectivo no tienen sector» |
| `frontend/src/components/AddPositionFlow.jsx:812-816` | Alta de posición | «✓ Letra válida — vencimiento: <fecha>» + tabla de códigos de mes |
| `backend/main.py:20477-20482` | Prompt del sistema de la IA | bloque «BONOS ARGENTINOS» (menciona «paridad (% de valor nominal al que cotiza)») |
| `backend/main.py:25707-25760` | Tool `get_ar_bond_metadata` | devuelve `maturity`, `law`, `indexed_by`, `step_up` al LLM |
| `backend/ai/builders/insights.py:631-655,704` | Packet de IA | campo `ar_bond_holdings` |
| `frontend/src/pages/keywords/BonosAR.jsx:8` | Landing SEO | promete «vencimiento, cupón actual, próxima amortización, paridad, TIR implícita» |

---

### Dónde se persiste

**La escala per-100 NO se persiste como flag en producción.** La única estructura que la modela explícitamente es `Holding.per100` (`backend/importing/tenencia.py:86`), un campo **efímero en memoria** del parser de fotos de tenencia: se usa para decidir si el importe cuadra, y el precio se guarda ya normalizado (`price_per1 = value / qty`). No hay columna `per100` en ninguna tabla. [V]

Lo que SÍ vive en la base:

| tabla | columna | qué guarda | escala |
|---|---|---|---|
| `positions` | `quantity` | nominales (VN). Para bonos amortizantes es el **nominal RESIDUAL** después del sweep | per-1 |
| `positions` | `buy_price` | precio unitario de compra ya reconciliado | **per-1** |
| `positions` | `invested`, `commissions` | costo, escalado ÷100 por `normalize_bond_units` si venía per-100 | moneda del lote |
| `positions` | `asset_type` | `'BOND'` (también `BONO/ON/LETRA/LECAP` en el guard) | — |
| `positions` | `price_override` | precio manual; **para renta fija se clampea igual** (`valuation.js:444-447`) | per-1 |
| `positions` | `split_adjusted_through` | watermark de splits (`backend/main.py:1036-1037`) — no aplica a bonos pero `proyeccion.py:141-146` lo mira | — |
| `import_normalized_tx` | `unit_price` | precio reconciliado por `reconciled_unit_price` | **per-1** |
| `import_normalized_tx` | `gross_amount` | monto bruto (la caja real) — es LA verdad de la que se deriva el precio | moneda |
| `operations` | `op_type` | `'Cupón'` / `'Amortización'` | — |
| `operations` | `pnl_usd` | monto NETO del cobro **en moneda del broker** (no en USD, pese al nombre) | nativa |
| `operations` | `currency`, `fx_to_usd` | moneda nativa y TC nativa-por-USD sellado (`backend/main.py:1190-1193`) | — |
| `operations` | `cost_basis_consumed` | costo del face devuelto por la amortización (`backend/main.py:1201-1203`) | moneda |
| `operations` | `undo_meta_json` | foto para deshacer: `qty_decremented`, `invested_decremented`, `amort_lots` por lote, `fx_source` | — |
| `bond_cashflow_skips` | `(user_id, broker, asset, date)` | pagos teóricos que el usuario marcó "no aplica" (`backend/main.py:1330-1341`) | — |
| `bond_indices_daily` | `(index_name, date, value)` | serie CER cacheada, cross-user (`backend/main.py:1232-1241`) | — |

Verificado contra la copia de dev: `bond_cashflow_skips`, `bond_indices_daily` y `operations.cost_basis_consumed` existen en el esquema real. [V]

**Se calcula al vuelo, sin persistir**: el cronograma completo (`generateSchedule` corre en el navegador en cada render), la TIR, el accrued, el factor CER, el `residual_factor` y la paridad (que directamente no existe).

---

### ⚠️ Implementaciones divergentes

#### D1 — El cronograma de amortización de AL30/GD30 está definido DOS VECES con números DISTINTOS [V]

| | backend `pricing/bond_amortization.py:70-84` | frontend `bondSchedulesAR.js:95` |
|---|---|---|
| cuotas | 13 | 13 |
| primera | 2024-07-09 = **4%** | 2024-07-09 = **7,6923%** |
| resto | 12 × **8%** | 12 × **7,6923%** |
| fuente citada | "Verificado (Rava/IOL)" | "Decreto 391/2020 + anexo AR-2030", `_verificationLevel: 'verified'` |

Las dos se declaran verificadas y se contradicen. Efecto medible: al 2026-09-05 el backend calcula `R = 1 − (0.04 + 4×0.08) = 0.64` (pagadas jul-24, ene-25, jul-25, ene-26, jul-26) y el frontend, sobre la misma fecha, muestra un cronograma donde ya se devolvió `5 × 7.6923 = 38.46%` → residual 61,54%. **La cantidad que ve el usuario en Cartera sale del backend (0,64) y el monto del "próximo cobro" sale del frontend (7,69 por 100 VN en vez de 8).** El error del próximo cupón es del orden del 4%.

#### D2 — El backend solo amortiza 4 tickers; el frontend cree que amortizan 11 [V]

`_AMORT_SCHEDULES` tiene AL29/GD29/AL30/GD30 (`bond_amortization.py:88-93`). El comentario de `bond_amortization.py:95-102` lo admite: *"GD46 — amortiza desde 2025 … AMORTIZA HOY → mientras no esté, GD46 queda sobrevaluado (R=1)"*.

`bondSchedulesAR.js` sí tiene `amortSchedule` para los 6 pares (2029, 2030, 2035, 2038, 2041, 2046). Para GD46 declara `evenAmorts('2024-07-09', 44, 100/44)` (línea 185) — o sea 10 cuotas ya pagadas al 2026-09.

Resultado para un tenedor de GD46: **Cartera muestra el nominal completo (sobrevaluado ~23%), el cronograma del detalle muestra 10 amortizaciones ya vencidas, y el inbox de cobranzas pendientes le pide confirmar 10 pagos que nunca se descontaron de su cantidad.** Lo mismo, con distinta magnitud, para AE38/GD38 (frontend: amort desde 2027-07-09) y AL41/GD41 (frontend: desde 2028-01-09) — hoy todavía futuros, así que la divergencia está latente pero no muerde.

#### D3 — CUATRO definiciones distintas de "escala per-100" que pueden discrepar [V]

| implementación | criterio | qué NO atrapa |
|---|---|---|
| `persister.reconciled_unit_price:535-546` | `ratio ∈ [98,102]` **y** `asset_type ∈ {BOND, OTHER, ''}` | un bono tipado `STOCK`/`CEDEAR` por el parser; y por diseño no toca `k = 1e4/1e5/1e13` (documentado en el docstring) |
| `recompute_backfill.bond_per100_factor:157-168` | `10 < costo/mercado < 1000` **y** `costo_usd ≥ 3` | un bono per-100 barato (< 3 USD equivalentes) |
| `main._resolve_ar_bond_price:7353-7356` | `usd_equiv ≥ 3.0` | un CER en pesos cuyo precio per-1 supere ~3 USD |
| `bullmarket.py:689-690` | `\|q·p − 100·monto\| < \|q·p − monto\|` | nada — es un desempate, siempre elige uno de los dos |

El más frágil es el tercero: el umbral está en **USD-equivalente fijo (3,00)** y depende de `_data912_peso_per_usd`, que a su vez tiene un **fallback hardcodeado de 1450 ARS/USD** (`main.py:7256`). Un CER en pesos que acumule suficiente coeficiente CER para pasar de 3 USD por nominal empezaría a dividirse por 100 — exactamente el bug de 2026-06-27 que el test `test_bond_unit_convention.py:36-40` pinnea, pero al revés. TX28 hoy vale 1,106 USD per-1 según el snapshot del test; le queda un factor 2,7× de margen.

#### D4 — La misma "Amortización" tiene TRES semánticas de P&L [V]

| camino | `pnl_usd` guardado | `cost_basis_consumed` | ¿decrementa VN? | dónde |
|---|---|---|---|---|
| Manual / inbox (`POST /bonds/cashflow`) | **el cash neto COMPLETO** | sí, calculado FIFO | opcional (`decrement_quantity`) | `main.py:10480-10486` |
| Import con cantidad | venta FIFO normal (P&L real) | n/a | sí (es una venta) | `persister._persist_sell_fifo` |
| Import cash-only (Balanz "Renta y Amortización" con cantidad 0) | **0** | n/a | no | `persister._is_amort_capital_return:904-935` |

Y encima los lectores discrepan sobre qué hacer con el primero:
- `frontend/src/pages/Positions.jsx:539-551` calcula `pnlContrib = amt - cbConsumed` → muestra solo la ganancia real.
- `backend/realized_pnl.py:97-107` incluye `'Amortización'` en el universo de trades cerrados y devuelve `pnl_usd` **entero** (solo lo divide por el TC si es ARS). O sea que Dashboard, Reportes, packets de IA y el trade-log cuentan **la devolución de capital como ganancia realizada**, mientras el detalle del bono en Cartera la descuenta. El propio módulo documenta el problema hermano (el win rate) en `realized_pnl.py:34-58` pero no éste.

Peor caso concreto: `Positions.jsx:378-383` registra un pago **mixto** (cupón + amortización) como `flow_type: 'coupon'` con `amount: item.total`. Al ser un cupón nunca lleva `cost_basis_consumed`, así que **la parte de capital del pago mixto se cuenta como ganancia en los dos lados**.

#### D5 — CINCO regex distintos para "ticker de letra" [V]

| archivo:línea | regex | ¿valida que la fecha exista? |
|---|---|---|
| `backend/importing/maturity.py:59` | `^([A-Z])(\d{1,2})([EFMAYJLGSOND])(\d)$` | **sí** (`date(...)` en un try/except, línea 93-96) |
| `frontend/src/utils/sections.js:23` | `^[A-Z]\d{1,2}[EFMAYJLGSOND]\d$` | no |
| `frontend/src/components/AddPositionFlow.jsx:32` | `^([A-Z])(\d{1,2})([EFMAYJLGSOND])(\d)$` | no |
| `frontend/src/utils/assetClass.js:84` | `^[STX]\d{1,2}[A-Z]\d{1,2}$` | no · solo prefijo S/T/X · **cualquier** letra de mes · año de 1-2 dígitos |
| `frontend/src/utils/profileAllocations.js:235` | `^[ST]\d{1,2}[A-Z]\d{1,2}$` | no · solo S/T |

`sections.js:22` dice "Espeja maturity._LETRA_RX del backend" — y lo espeja salvo por la validación de fecha. Un `S31F5` (31 de febrero) es LETRA para el frontend y **no** para el backend, así que la misma posición cae en la sección «Letras» en la UI y en «Bonos» en la clasificación server-side (`backend/importing/sections.py:57-58`).

#### D6 — `isKnownArBond` frontend ≠ `is_known_ar_bond` backend, aunque `sections.js` dice ser su espejo [V]

- Frontend (`sections.js:9-13`): lee `BOND_META` y acepta `type ∈ {sovereign, cer, corporate}` → **33 tickers** (11 soberanos + 6 CER + 16 ONs).
- Backend (`ai/ar_bonds_metadata.py:35-200`): **17 tickers** (11 soberanos + 6 CER). El propio docstring lo dice: *"Bonos corporativos / ONs se manejan vía AR_BONDS_DATA912 sin metadata detallada"* (línea 18-19).

`backend/importing/sections.py:1-3` declara ser el mismo clasificador que `sections.js`. No lo es: una ON como `YCA0O` sin `asset_type` es «Bonos USD» en el frontend y **null (renta variable)** en el backend.

#### D7 — DOS `isBondTicker` en el frontend con universos incompatibles [V]

- `frontend/src/utils/tickers.js:454-456`: allowlist curada (`BOND_TICKERS`). La usan `pendingCashflows.js:109` y `upcomingEvents.js:55` — o sea, **el inbox de cobranzas y el calendario**.
- `frontend/src/utils/profileAllocations.js:246-259`: heurística por prefijo (`AL, GD, AE, AY, TX, TY, TC, TG, TZ, BONAR, BPO, BP, LECAP, LEDES, LELIQ, S`) + `/\d/`. La usa `classifyAssetBucket:298` para el bucket «renta fija» del test de perfil.

El prefijo `'S'` con un dígito clasifica como bono cualquier ticker que empiece con S y tenga un número: `S&P500`, `SPY5`, etc. Y `'TC'`, `'TG'`, `'BP'` son prefijos de dos letras muy laxos. Al mismo tiempo, un `BPY26` (BOPREAL Serie 3, que está en `tickers.js`) sí es bono en las dos.

Hay además un TERCER clasificador: `assetClass.js:160-169` (`isBondLike`), que combina `isFixedIncome(assetType)` + `BOND_TICKERS` + sufijo D/C + `LETRA_DATE_RE` + `ON_RE = /^[A-Z]{2,4}\d?[A-Z]?O$/`. Ese es el que alimenta la torta de composición.

#### D8 — `normalize_bond_units` se llama con y sin `linked_ids` según el camino [V]

- `backend/main.py:30905`: `normalize_bond_units(conn, uid, bond_price_per1=_bond_price_per1)` — **sin** `linked_ids` → toca también posiciones cargadas a mano.
- `backend/importing/recompute_backfill.py:316-318`: `normalize_bond_units(conn, uid, ..., linked_ids=linked)` → solo posiciones de import.

El docstring de la función (`recompute_backfill.py:178-180`) dice: *"`linked_ids` (si se pasa) limita a posiciones creadas por imports (no toca manuales)"*. El camino de import lo omite. Un usuario que cargó un bono a mano en escala per-100 (97 en vez de 0,97) va a ver su costo dividido por 100 en el próximo import de ese broker, sin haberlo pedido.

#### D9 — La serie CER llega al detalle del bono pero NO al calendario ni al inbox [V]

| consumidor | ¿pasa `cerSeries`? |
|---|---|
| `BondDetail.jsx:79-83` | **sí** (`cerOpts`) |
| `RentaFijaSections.jsx:305` | **sí**, pero solo si el padre le pasó la prop |
| `pendingCashflows.js:113` | **no** — `generateSchedule(p.asset)` pelado |
| `upcomingEvents.js:58` | **no** — `generateSchedule(p.asset)` pelado |

Para un TZX26 (cero-cupón CER), el detalle muestra `100 × factor_CER` y el calendario / el inbox muestran **100 nominal**. Con el CER acumulado desde 2023-06-30, la diferencia es de varias veces. El usuario ve dos montos distintos para el mismo pago en dos pantallas de la misma app.

#### D10 — Mobile no recibe la mitad del plumbing de renta fija [V]

`frontend/src/pages/PositionsMobile.jsx:1355-1361` monta `RentaFijaSections` con `positions / valuePos / brokers / displayCurrency / tcValuacion / onChanged`. **No pasa** `bondCashflowsByKey`, `pendingDatesByKey`, `openBondCashflow`, `tcMep`, `cerSeries`, `isArsFor`, `priceFor` ni `priceMeta` — todos los que sí pasa el desktop (`Positions.jsx:2794-2803`).

Efecto en mobile: sin `priceFor` → `price` es `undefined` → **la TIR nunca se muestra** (`RentaFijaSections.jsx:298`); sin `bondCashflowsByKey` → no hay «capital recuperado», ni cupones/amortizaciones cobrados, ni historial; sin `openBondCashflow` → **no se puede registrar un cupón desde el celular**; sin `cerSeries` → los CER van en nominal. Además `PositionsMobile.jsx` no importa `PendingCashflowsBanner` ni `detectPendingCashflows`: **el inbox de cobranzas pendientes no existe en mobile.**

#### D11 — Tres ports del guard anti-per-100, uno sin el parámetro de override [V]

`valuation.js:448` y `snapshots_job.py:42` aceptan `has_override`; `behavioral.py:47` **no lo tiene** (firma `(mkt_usd, cost_usd, asset_type)`). Para renta fija da igual (el override se clampea igual en las tres), pero para el resto de los activos Análisis/IA aplica el cap ×50 a posiciones con precio manual que Dashboard y la curva de snapshots respetan.

#### D12 — El step-up de AL29 está escrito distinto en el frontend y en el prompt de la IA [V]

- `bondSchedulesAR.js:68-72`: tres tramos → 0,500% → 1,000% → 1,750%.
- `ai/ar_bonds_metadata.py:46`: *"Cupón step-up (0.5%→1.0%→1.5%→1.75%)"* — cuatro tramos.

El cálculo usa el primero; el LLM narra el segundo.

#### D13 — Convergencias verificadas (no divergen)

- **`_FIXED_INCOME_TYPES`**: `{BOND, BONO, ON, LETRA, LECAP}` idéntico en `valuation.js:437`, `snapshots_job.py:39`, `behavioral.py:40`, `recompute_backfill.py:146` y `sections.py:18`. ✅
- **La banda del guard** (`0.02 ≤ mult ≤ 4` para renta fija) es idéntica en las tres implementaciones. ✅
- **El traductor per-100 → posición** (`× quantity / 100`) es idéntico en `bondSchedule.js:374-376`, `pendingCashflows.js:138`, `upcomingEvents.js:67-69` y `BondDetail.jsx:144,154`. ✅
- **`reconciled_unit_price` es una sola implementación** consumida por los 8 call sites (persister buy/sell, normalizer, rebuild buy/sell, borrado, undo). ✅

---

### Zonas grises

**Z1 — La foto de tenencia y el sweep de amortización miden en escalas que nadie reconcilia, y el código lo sabe.** `backend/importing/tenencia.py:437-457` lo escribe con todas las letras: *"`positions` guarda el nominal RESIDUAL … La foto trae lo que el broker haya decidido reportar … las dos puntas de la comparación están en escalas distintas y nadie las reconcilia"*. La medición que hicieron (líneas 423-431) dio **16 de 16 casos que no son ni una cosa ni la otra**. El paliativo es mandar esos tickers a aprobación manual (`requiere_aprobacion`), no resolver la escala. Es honesto, pero significa que **para todo bono amortizante la conciliación contra el resumen del broker está suspendida**.

**Z2 — El sweep de amortización pisa la cantidad de una posición que la foto ya declaró correcta… salvo por una lista de excepciones.** `maturity.py:319-325` exime los lotes sembrados por 'Tenencia — apertura' (`seed_pids`), y `_bond_genuine_net` excluye tanto los seeds como las VENTAS-amortización. Son tres exclusiones acumuladas sobre la misma base. Si un usuario tiene la misma posición mitad importada por movimientos y mitad sembrada por foto, `original` (que sale del ledger) y `current` (que sale de los lotes linkeados no-seed) miden universos distintos y `factor = target/current` no tiene una interpretación clara. No encontré test que cubra esa mezcla.

**Z3 — `_lookup_schedule` matchea por substring del nombre.** `bond_amortization.py:117-122`: `if tk in up` sobre el nombre del instrumento. Un instrumento llamado, por ejemplo, "FONDO AL30 CAPITAL" o cualquier nombre que contenga "AL29"/"GD30" como subcadena recibiría el cronograma de amortización de ese bono y **le bajarían la cantidad**. El comentario dice que es para Cocos, que trae el ticker en el nombre. No hay guard de límite de palabra.

**Z4 — `_resolve_ar_bond_price` y los tickers que ya terminan en `D`.** [I] La regla es "sin sufijo `.BA` → buscá `base + 'D'`" (`main.py:7350`). `AR_BONDS_DATA912` incluye `BB37D` y `BA37D`, que ya llevan la D del USD-MEP en su nombre. Para una posición `BB37D` en un broker USD el lookup sería `BB37DD` → probablemente None → cae a yfinance. Y en un broker ARS (`BB37D.BA`) el lookup es `BB37D`, que **es el quote en dólares**, y como `usd_equiv = raw / MEP` daría un número diminuto (< 3), se devolvería tal cual: **un precio en USD servido como si fueran pesos**. No pude verificar el payload real de data912 desde acá, así que lo dejo como inferencia a partir de la fórmula. Ningún test cubre un ticker terminado en D.

**Z5 — `bondMeta` cubre 41 tickers; `AR_BONDS_DATA912` cubre otros; `tickers.js` cubre otros más.** `tickers.js` ofrece en el buscador `AO28, AO29, BPY26, BPOA7, BPOB7, BPOC7, BPOD7, BA37D, CS49O, TLCMO` (líneas 330-386) que **no están en `BOND_META`**. Para esas posiciones `getBondMeta` devuelve null → sin cronograma, sin TIR, sin próximo pago, sin ficha ("Sin metadata configurada para este ticker", `BondDetail.jsx:216`), y `sections.js:isKnownArBond` devuelve false (aunque igual entran a «Bonos» si el importador les puso `asset_type='BOND'`). El comentario de `ar_bonds_metadata.py:13-14` pide mantener las dos listas sincronizadas; no lo están.

**Z6 — Los `_verificationLevel: 'approx'` se muestran al usuario, los datos backend "pendientes de verificar" no.** El frontend avisa «Cronograma aproximado — verificar contra prospecto» para AL29/AE38/AL41/GD46 (`BondDetail.jsx:199-201`). El backend, cuando le falta el cronograma de GD46, simplemente devuelve `R = 1.0` y el bono queda sobrevaluado **en silencio** (`bond_amortization.py:134`: *"sin schedule → no tocamos el nominal (no-op seguro)"*). El fail-safe elegido es "no tocar", que para un bono que ya devolvió el 23% del capital no es seguro, es sobrevaluar.

**Z7 — `estimateYield` cambió de semántica y el comentario lo admite.** `bondSchedule.js:356-361`: *"ATENCIÓN: en PR #8 cambiamos la semántica del input — antes se trataba como dirty …; ahora por default se trata como CLEAN"*. Los dos call sites del repo (`BondDetail.jsx:112`, `RentaFijaSections.jsx:306`) pasan el precio de mercado ×100. Un precio de pantalla de BYMA es **dirty** para bonos con cupón corrido en muchas convenciones; tratarlo como clean y sumarle el accrued sobreestima el precio y **subestima** la TIR. No encontré nada en el código que documente qué convención devuelve data912.

**Z8 — El default `dayCount` es `'ACT/365.25'`, una convención que el propio archivo llama no-estándar.** `bondPricing.js:87-91`: *"No-standard pero útil para promediar bisiestos sin armar el algoritmo ACT/ACT-ISDA completo. Lo dejamos como backwards-compat"*. Los 16 ONs de `bondMeta.js:135-150` **no declaran `dayCount`**, así que todas las TIR de obligaciones negociables se calculan con esa convención inventada. Los 11 soberanos sí traen `'30/360'` desde `bondSchedulesAR.js`.

**Z9 — Los ETFs de bonos están en `BOND_META` pero no son renta fija para `sections.js`.** `bondMeta.js:153-160` define TLT/IEF/SHY/AGG/BND/LQD/HYG/TIP con `type: 'etf'` y `maturity: null`; `sections.js:9` los excluye a propósito (*"Excluye ETFs … son renta variable aunque estén en BOND_META"*). Pero `tickers.js:411-414` los mete en `BOND_TICKERS`, así que `pendingCashflows.js:109` y `upcomingEvents.js:55` **sí los consideran bonos** — y después los descartan porque `generateSchedule` devuelve null sin maturity (`bondSchedule.js:135`). Funciona por accidente, no por diseño.

**Z10 — `couponRate` de los ETFs es un número inventado que se muestra como dato.** `bondMeta.js:153-160`: `TLT: couponRate: 4.5`, `HYG: 7.0`, etc. El comentario dice "proxy del yield distribuido". `formatCouponLabel` (`bondMeta.js:238`) lo renderiza como «cupón 4.5% TNA (0.375% por cupón, mensual)» — con una precisión que el número no tiene.

**Z11 — El pago mixto se registra como cupón.** `Positions.jsx:378-383` mapea `kind === 'mixto'` a `flowType: 'coupon'` con `amount: item.total`, y el comentario lo reconoce como "comportamiento existente". No hay `face_amortized`, así que el VN no baja y `cost_basis_consumed` queda NULL. Combinado con D4, es la ruta más directa a inflar el P&L realizado de un AL30.

**Z12 — Se cambió el default de la fecha del modal pero el cronograma sigue siendo la fuente.** `BondCashflowModal.jsx:88-93` documenta un incidente real: *"sembrar 09/01/2027 hacía que el usuario confirmara cupones con esa fecha (25 seguidos en una cuenta real)"*, y ahora el default cae a hoy si la fecha del cronograma es futura. Pero `estimate.amount` **sigue viniendo del pago futuro** (`nextPaymentForPosition`), así que el monto pre-llenado corresponde a una fecha distinta de la que se va a guardar. El backend solo valida que la fecha no sea futura (`main.py:10382-10386`), no que monto y fecha sean del mismo pago.

**Z13 — El comentario de `tenencia._num` acusa una inconsistencia de parsing que sigue viva.** `persister.py:513-515`: *"⚠️ `tenencia._num` usa la convención OPUESTA para la misma celda: una de las dos está mal por construcción"*. Verificado: `tenencia.py:70-71` hace `.replace(".", "").replace(",", ".")` (el punto es SIEMPRE separador de miles), mientras `normalizer.py:159` dice *"Si solo hay punto, asumimos que es decimal (no separador de miles)"*. Es la razón declarada por la que `reconciled_unit_price` se limita a dos convenciones: `k` no identifica cuál de los tres campos está corrupto.

**Z14 — La justificación del docstring de `reconciled_unit_price` puede estar desactualizada.** Ese docstring (`persister.py:501-509`) argumenta que no se puede reconciliar `k ≈ 1000` porque `parse_number("660.400")` devuelve 660,4 y una fila sana daría la misma firma que un FCI legítimo, citando *"normalizer.py:90"*. Dos cosas: (a) la cita de línea está corrida — la frase está en `normalizer.py:159`; (b) desde entonces existe `_desambiguar_por_triangulo` (`normalizer.py:89-134`), que corre **antes** del guard de escala (`normalizer.py:365-369` vs `:554-557`) y resuelve exactamente ese caso por aritmética (`_MILES_AMBIGUO_RE = ^-?[1-9]\d{0,2}\.\d{3}$` matchea "660.400"). O sea que el caso que el docstring usa como razón para no tocar `k=1000` ya está cubierto aguas arriba. No cambio nada — solo señalo que la premisa citada puede no ser la de hoy.

**Z15 — `_data912_peso_per_usd` puede devolver el MEP de un bono y clasificar la escala de otro.** `main.py:7247-7256` toma el primer par (`AL30`/`AL30D`, luego GD30, AL35, AE38, GD35) que exista y sea usable, y ese único número clasifica **todos** los quotes en pesos de la respuesta. Si data912 devuelve el par de referencia stale y el resto fresco (o viceversa), la clasificación per-100/per-1 de un bono depende del precio de otro bono. El guard `0 < d < 1000` descarta "D mal-denominados", pero no descarta un par stale.

**Z16 — No hay ningún test que compare el cronograma del backend contra el del frontend.** Busqué en `backend/tests/` y en `frontend/src/**/*.test.js`: `test_bond_amortization.py` testea `residual_factor` contra sí mismo, y `bondSchedulesAR.test.js` valida invariantes estructurales (suma 100, orden, cobertura) del lado frontend. Ninguno cruza las dos tablas. La divergencia D1 (4%+12×8% vs 13×7,69%) es exactamente el tipo de cosa que un test de paridad — como el que sí existe para `CRYPTO_SYMBOLS` (`frontend/src/utils/crypto.test.js:34`) o para `assetClass` — habría cazado.
