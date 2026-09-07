## TIR / IRR / XIRR / retorno ponderado por dinero

### Definición según el código

En Rendi **el concepto está partido en dos cosas que no se hablan entre sí**, y ninguna de las dos es una TIR de cartera.

**1. «TIR» (la palabra, en la UI) = TIR de UN BONO, no de la cartera.** [V]
Es lo único del sistema que resuelve una tasa interna de retorno de verdad: dado un precio y un cronograma de flujos futuros, busca numéricamente la `r` que hace `Σ cf_i/(1+r)^t_i = precio sucio`. Vive entero en el frontend, en `frontend/src/utils/bondPricing.js:186` (`yieldToMaturity`), y se muestra con la etiqueta **"TIR"** o **"TIR real"** en dos lugares de Cartera. Es una TIR *prospectiva y por instrumento*: no mira lo que el usuario pagó ni cuándo compró — sólo el precio de mercado de hoy y los cupones que faltan. Ver `frontend/src/components/RentaFijaSections.jsx:306` y `frontend/src/components/BondDetail.jsx:112`.

**2. «Retorno ponderado por dinero» (MWR) = una resta, no una TIR.** [V]
Cuando el código dice "money-weighted", no está hablando de una IRR con fechas. Está hablando de:

```
totalReturnPct = (valor de mercado hoy − capital aportado neto) / capital aportado neto
```

`frontend/src/pages/Dashboard.jsx:265-266`. En la UI eso se llama **"Ganancia total"/"Pérdida total"**, con la nota literal `= valor actual − capital aportado neto` (`frontend/src/pages/Dashboard.jsx:857`). Es un *holding-period return sobre capital aportado*: no anualiza, no pondera por tiempo, no le importa si el aporte entró hace cinco años o ayer.

**El código lo dice explícito y además dice que lo abandonó**: `frontend/src/utils/evolution.js:469` — *"La fórmula simple (value - net_deposited) / net_deposited es MWR — se distorsiona cuando hay retiros/depósitos grandes"* — y a partir de ahí el gráfico de Métricas dejó de dibujar el MWR y pasó a TWR encadenado por Modified Dietz. **Pero el hero del Dashboard, el hero de Métricas y el móvil siguen mostrando el MWR.** O sea: la app decidió que el MWR estaba mal para la curva y lo dejó vivo para el número grande.

**3. Lo que NO existe.** [V]
- **No hay XIRR en ninguna parte del repo.** La única aparición de la palabra en todo el código es un comentario: `frontend/src/utils/insightsMetrics.js:15` — *"Aproximación buena vs alternativas más complejas (IRR/XIRR) cuando los flows son moderados"*. Es una nota que justifica **no** haberlo implementado.
- **No hay ninguna IRR/TIR en el backend.** Cero. `grep -rniE "\birr\b|xirr|tasa interna|internal rate" backend/` no devuelve nada; no hay `numpy_financial`, `scipy.optimize`, `brentq` ni `fsolve`. El único `bisect` del backend (`backend/twr.py:1269`, `backend/performance.py:57`, `backend/main.py:16204`) es `bisect.bisect_right` para buscar fechas en una serie, no para buscar una raíz.
- **No hay TIR de cartera de bonos**, aunque la landing la promete (ver Zonas grises).

**4. La familia adyacente que sí es IRR pero no se llama así.** [I — lo infiero de la forma algebraica, no del nombre]
Hay tres cosas más en el código que son técnicamente "la tasa que iguala dos flujos", o sea IRR de un caso degenerado:
- **Modified Dietz** (`backend/twr.py:559`): `r = (v1 − v0 − flujo)/(v0 + 0,5·flujo)`. La literatura lo clasifica como *money-weighted return de un período* (es la aproximación lineal de primer orden a la IRR del tramo). Rendi lo usa al revés de eso: lo **encadena** entre períodos para *neutralizar* los flujos y llamarle TWR. Es el motor que efectivamente decide casi todos los porcentajes de la app.
- **TNA↔TEA de plazo fijo** (`frontend/src/utils/valuation.js:828`): `teaEquiv = (1 + tp)^(365/P) − 1`. Es la TIR efectiva anual de un instrumento de dos flujos.
- **Tasa requerida de un objetivo** (`frontend/src/pages/Goals.jsx:266-268`, `backend/goals_diagnostic.py:101`): `(target/current)^(1/años) − 1`. Es la IRR que el usuario necesitaría, resuelta en forma cerrada porque hay un solo flujo. Y el **PMT** de `frontend/src/pages/Goals.jsx:623` es la misma ecuación despejada por el aporte en vez de por la tasa.

---

### Dónde se calcula

Orden: primero la única IRR real (bonos), después las familias que ocupan el lugar conceptual de la TIR.

#### Familia A — TIR de un bono (la única IRR resuelta numéricamente)

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `frontend/src/utils/bondPricing.js:186` | `yieldToMaturity({dirtyPrice, cashflows, bracket, newtonRelTol})` | **CANÓNICO.** Resuelve la TIR: bracket → bisect grueso (10 iter) → Newton (50 iter) → bisect fino (80 iter). Devuelve `{ytm, converged, method, iterations}` | (ver filas 2-3) | **FUENTE** |
| 2 | `frontend/src/utils/bondPricing.js:206-209` | `npv` (closure) | La función objetivo cuya raíz es la TIR | `let s = -dirtyPrice; for (const x of validCf) s += x.amount / Math.pow(1 + r, x.t)` | fuente |
| 3 | `frontend/src/utils/bondPricing.js:211-215` | `dnpv` (closure) | Derivada analítica para Newton | `s -= x.t * x.amount / Math.pow(1 + r, x.t + 1)` | fuente |
| 4 | `frontend/src/utils/bondPricing.js:217-247` | bracket auto-expand | Si no hay cambio de signo en `[-0.5, 5.0]`, expande `hi *= 2` (tope 100 = 10.000 %) o `lo` hacia `-0.9999`. Máx 8 expansiones; si falla → `method:'bracket_failed'`, `ytm:null` | `lo = Math.max(-0.9999, lo - (1 + lo) * 0.5)` / `hi = hi * 2` | fuente |
| 5 | `frontend/src/utils/bondPricing.js:256-277` | paso Newton | Newton con proyección de vuelta al bracket si se escapa | `let next = r - f / df` | fuente |
| 6 | `frontend/src/utils/bondPricing.js:278-289` | bisect fallback | Si Newton no convergió: 80 bisecciones. Si tampoco → `{ytm: (lo+hi)/2, converged:false, method:'max_iter'}` — **devuelve un número igual, marcado** | `const mid = (lo + hi) / 2` | fuente |
| 7 | `frontend/src/utils/bondSchedule.js:314` | `estimateYieldDetailed(ticker, priceInput, from, options)` | Orquestador: `getBondMeta` → `generateSchedule` (con CER si aplica) → filtra pagos futuros → `computeAccrued` → clean→dirty → llama `yieldToMaturity`. Devuelve `{ytm, converged, method, iterations, accrued, clean, dirty, dayCount}` | `const result = yieldToMaturity({ dirtyPrice: dirty, cashflows })` | **FUENTE** (la API que usa la UI) |
| 8 | `frontend/src/utils/bondSchedule.js:339-343` | construcción de cashflows | Convierte cada pago futuro a `{t, amount}` con el day-count del prospecto | `t: dayCountFraction(base, p.date, dayCount), amount: p.total` | fuente |
| 9 | `frontend/src/utils/bondSchedule.js:333-337` | clean/dirty | Por defecto el precio de entrada se trata como **clean** y se le suma el accrued | `const dirty = priceIsDirty ? priceInput : (priceInput + accrued)` | fuente |
| 10 | `frontend/src/utils/bondPricing.js:133-156` | `computeAccrued(schedule, asOfDate, convention, issueDate)` | Interés corrido lineal del cupón corriente, capado a `[0,1]` del período | `const frac = Math.max(0, Math.min(1, elapsed / totalPeriod)); return nextCoupon * frac` | fuente |
| 11 | `frontend/src/utils/bondPricing.js:112` (switch en `:59`) | `dayCountFraction(from, to, convention)` | 30/360-US, 30E/360, ACT/360, ACT/365, ACT/365.25, ACT/ACT-ISDA. **Convención desconocida → `días/365` silencioso** | `default: return diffDaysUTC(from, to) / 365` | fuente |
| 12 | `frontend/src/utils/bondSchedule.js:356-363` | `estimateYield(ticker, pricePer100, from)` | Wrapper legacy que devuelve sólo el número. **No lo llama ningún componente** (sólo `bondSchedule.test.js`) | `const r = estimateYieldDetailed(...); return r.ytm` | fuente **huérfana** |
| 13 | `frontend/src/components/RentaFijaSections.jsx:296-307` | `BondCardRow` | TIR de la card de la zona Renta Fija. Cross-currency por MEP; **si no hay MEP → `pBond = null` → no muestra TIR** | `tir = estimateYieldDetailed(p.asset, pBond * 100, todayIso(), cerOpts)?.ytm ?? null` | consumidor |
| 14 | `frontend/src/components/BondDetail.jsx:96-114` | `BondDetailBody` | TIR del panel "Rendimiento" del detalle expandido. Cross-currency por MEP; **si no hay MEP usa el precio SIN convertir y avisa** | `estimateYieldDetailed(p.asset, pricePer100Clean, today, cerOpts)` | consumidor |
| 15 | `frontend/src/utils/bondSchedule.js:132-160` | `generateSchedule(ticker, {cerSeries})` | Ajusta cada flujo por CER: `factor(date) = CER(date)/CER(emisión)`, LOCF. Es lo que convierte la TIR nominal en "TIR real" | `if (!val) return 1; return val / cerBase` | fuente |
| 16 | `frontend/src/utils/bondPricing.js:311-314` | `semiAnnualToEffectiveAnnual(rSemi)` | TIR semestral → efectiva anual. **Exportada, cero consumidores fuera de tests** | `return Math.pow(1 + rSemi, 2) - 1` | fuente **muerta** |
| 17 | `frontend/src/utils/bondPricing.js:316-319` | `effectiveAnnualToSemiAnnual(rEar)` | Inversa de la anterior. **Cero consumidores** | `return Math.pow(1 + rEar, 0.5) - 1` | fuente **muerta** |
| 18 | `frontend/src/utils/bondSchedule.js:387-395` | `getAccruedInterest(ticker, asOfDate)` | Helper "para BondDetailRow". **Cero consumidores**, y además llama `generateSchedule(ticker)` **sin `cerSeries`** | `return computeAccrued(sched, base, dayCount, meta.issueDate)` | fuente **muerta y sin CER** |

#### Familia B — «Retorno ponderado por dinero» tal como lo implementa Rendi (la resta)

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 19 | `frontend/src/pages/Dashboard.jsx:265-266` | `Dashboard` | El MWR del hero. **Es el número más visible de la app** | `const totalReturnUsd = totalValue - netDeposited` / `const totalReturnPct = netDeposited > 0 ? totalReturnUsd / netDeposited : 0` | **FUENTE** |
| 20 | `frontend/src/utils/insightsModel.js:41-52` | `netCapitalContributed(globalMonthly)` | El denominador: `capital_inicio` del primer mes (prefiere `capital_inicio_costo`) + Σ(deposits−withdrawals) | `return baseline + flows` | fuente |
| 21 | `frontend/src/pages/Insights.jsx:550-555` | `Insights` (Métricas) | El mismo MWR en el hero de Métricas | `const totalResult = totalPortfolio - capitalContributed` / `totalResultPct = ... (totalResult / capitalContributed) * 100` | fuente |
| 22 | `frontend/src/pages/HomeMobile.jsx:135-142` | `HomeMobile` | Reimplementa `netCapitalContributed` **inline**, sin el fallback a `capital_inicio_costo` | `const baseline = sorted[0]?.capital_inicio \|\| 0` … `return baseline + flows` | fuente **duplicada** |
| 23 | `frontend/src/utils/evolution.js:363-366` | `computeReturnDelta` | Δ del MWR entre dos fotos, pero **el % se divide por el VALOR de la punta, no por lo aportado** | `const usd = (todayValue - todayNetDep) - ((prev.total_value \|\| 0) - netDepositedOf(prev))` / `const pct = prevValue > 0 ? usd / prevValue : 0` | fuente |
| 24 | `frontend/src/utils/evolution.js:467-472` | `buildEvolutionFromSnapshots` (comentario) | Declara por qué el MWR se sacó de la curva | *"La fórmula simple (value - net_deposited) / net_deposited es MWR — se distorsiona…"* | — |
| 25 | `backend/reporting/builder.py:1533-1536` | `build_period_report` | `delta_pct_over_contrib` — el P&L del período sobre el aportado acumulado. La versión backend del MWR | `delta_pct_over_contrib = ((delta_usd / cum_aportado) * 100 if cum_aportado > 0 else None)` | **FUENTE** |
| 26 | `backend/reporting/builder.py:716-744` | `fetch_cum_deposits_until` | El denominador de la fila anterior. **Delega en `compute_net_deposited_db` con `include_baseline=False`** — o sea, SIN la baseline que el frontend sí usa | `compute_net_deposited_db(..., include_baseline=False)` | fuente |
| 27 | `backend/snapshots_job.py:328` / `:388` | `compute_net_deposited_db` / `compute_net_deposited` | SSoT del "aportado" que se persiste en `snapshots.net_deposited` | — | fuente |

#### Familia C — Modified Dietz (MWR de UN período, encadenado como si fuera TWR)

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 28 | `backend/twr.py:559-576` | `dietz(v0, v1, flow)` | **SSoT declarada del backend.** Docstring: *"Es EL primitivo: si alguna pantalla calcula el retorno de otra forma, vuelve a haber dos motores"*. Piso −100 %, sin techo | `denom = v0 + 0.5 * flow` / `return max((v1 - v0 - flow) / denom, -1.0)` | **FUENTE** |
| 29 | `backend/twr.py:623-648` | `leg_dudoso(v0, v1, flow)` | Cota de cordura del tramo: ×3 sin flujo que lo explique, o desborde del denominador | `r = dietz(v0, v1, flow)` | consumidor |
| 30 | `backend/twr.py:740-793` | `tramos(conn, uid, hasta_mes)` | Los tramos mensuales medibles del motor del asesor | `r = dietz(v0, v1, flow)` | consumidor |
| 31 | `backend/twr.py:1738-1768` / `:1845` / `:1858` / `:2061` | `curva_indexada` | La curva indexada, drawdown y CAGR, encadenando `dietz` | `ret = dietz(_a, _b, flow)` | consumidor |
| 32 | `backend/reporting/builder.py:783-794` | `_modified_dietz_pct(start_value, end_value, flows)` | Motor de % de Reportes. **Reimplementa `twr.dietz` con otras reglas: devuelve `None` si `avg<=0` y NO clampa a −100 %** | `avg = start_value + 0.5 * flows` / `pnl = end_value - start_value - flows` / `return (pnl / avg) * 100` | **FUENTE paralela** |
| 33 | `backend/main.py:11871-11873` | `dietz(ci, cf, net)` anidada en `/api/insights/mtm-audit` | **Tercera** implementación, en un endpoint de auditoría | `den = ci + 0.5 * net` / `return round((cf - ci - net) / den, 6) if den > 0 else None` | fuente |
| 34 | `backend/main.py:35695-35702` | informe del asesor | **Cuarta** implementación, inline. Además exige `dietz_base > 100` para publicar | `dietz_base = v0 + flows_usd / 2.0` / `ret_pct = round(market_usd / dietz_base * 100, 2)` | fuente |
| 35 | `backend/main.py:15305-15315` | `_cagr_from_monthly_rows` | **Quinta**, y ésta **NO es Modified Dietz**: divide por `ci` pelado (sin el ½·flujo) y clampa a `[-0.95, +5.0]` | `ret_m = max(-0.95, min(5.0, (cf - ci - net) / ci))` | fuente **divergente** |
| 36 | `frontend/src/utils/insightsModel.js:110-131` | `buildCumulativeReturnSeries` | Dietz del frontend con la excepción "primer mes de import" | `const avgCapital = isImportInitialMonth ? net : capInicio + 0.5 * net` | fuente |
| 37 | `frontend/src/utils/insightsMetrics.js:63-66` | `computeMonthlyReturns` | Dietz para Sharpe/volatilidad | `const denom = start + netFlow * 0.5` | fuente |
| 38 | `frontend/src/pages/Insights.jsx:675-682` | `Insights` (fallback mensual) | Dietz **con heurística big-withdrawal** (`\|net\|/ci > 0.3 y net<0` → denom = `ci`) | `const avgCap = isImportInitial ? net : (isBigWithdraw ? ci : ci + 0.5 * net)` / `rRaw = avgCap > 0 ? (cf - ci - net) / avgCap : 0` | fuente |
| 39 | `frontend/src/utils/evolution.js:536-543` (USD) y `:575-582` (ARS) | `buildEvolutionFromSnapshots` | Dietz entre snapshots, misma heurística big-withdrawal | `const avgCap = isBigWithdraw ? prevValueUsd : (prevValueUsd + 0.5 * flows)` | fuente |
| 40 | `frontend/src/hooks/useMonthlyData.js:379`, `:438`, `:616` | `useMonthlyData` | Tres denominadores Dietz más, en el hook de Resumen Mensual | `const avgCapital = (startUsd \|\| 0) + 0.5 * flows` / `const avgMtm = mtmStart + 0.5 * flows` / `const avgCap = _start + 0.5 * flows` | fuente |

#### Familia D — Tasa requerida y PMT (IRR despejada, en Objetivos)

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 41 | `frontend/src/pages/Goals.jsx:623-631` | `requiredMonthly(pv, fv, rAnnual, months)` | PMT de una anualidad: cuánto aportar por mes para llegar. Es la ecuación de NPV despejada por el flujo | `const pmt = (fv - pv * factor) / ((factor - 1) / r)` | **FUENTE** |
| 42 | `frontend/src/pages/Goals.jsx:266-268` | `GoalCard` | "Rendimiento anual requerido sin aportes" | `(Math.pow(target / currentValue, 1 / yearsLeft) - 1) * 100` | fuente |
| 43 | `frontend/src/pages/Goals.jsx:635-650` | `buildAltScenarios` | Repite el PMT para 6 % / CAGR del usuario / 15 % | `const monthly = requiredMonthly(currentValue, target, r, monthsLeft)` | consumidor |
| 44 | `backend/goals_diagnostic.py:96-101` | `_required_monthly_rate(current, target, months)` | La misma tasa requerida, **en mensual**, explícitamente "SIN aportes" | `return (target_value / current_value) ** (1 / months) - 1` | **FUENTE paralela** |
| 45 | `backend/goals_diagnostic.py:267` | `build_goal_diagnostic` | La anualiza para publicarla | `round(((1 + required_monthly) ** 12 - 1) * 100, 2)` | fuente |
| 46 | `backend/goals_diagnostic.py:104-115` | `_eta_months` | Despeja `n` en vez de `r` (misma ecuación) | `n = math.log(target_value / current_value) / math.log(1 + monthly_rate)` | fuente |
| 47 | `backend/goals_diagnostic.py:117-121` | `_project_value` | Capitaliza al ritmo del usuario | (interés compuesto simple) | fuente |
| 48 | `backend/ai/builders/goal.py:100-118` | `build_goal_packet` | Escenarios "objetivo" vs "histórico" para el LLM, **también sin aportes** | `const monthly = (1 + float(annual_pct)/100) ** (1/12) - 1` → `_project_value(...)` | consumidor |

#### Familia E — TEA de plazo fijo (IRR de dos flujos)

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 49 | `frontend/src/utils/valuation.js:781-784` | `_pfPeriodRate(tasa, dias, isTea)` | Tasa del período: simple si TNA, compuesta si TEA | `return isTea ? Math.pow(1 + tasa, dias / 365) - 1 : tasa * dias / 365` | **FUENTE** |
| 50 | `frontend/src/utils/valuation.js:827-828` | `computePf` (modalidad vencimiento) | TNA↔TEA equivalentes del PF | `if (isTea) tnaEquiv = (tp * 365) / P` / `else teaEquiv = Math.pow(1 + tp, 365 / P) - 1` | fuente |
| 51 | `frontend/src/utils/valuation.js:819-820` | `computePf` (modalidad periódica) | Idem con capitalización cada `f` meses | `tnaEquiv = iPer * (12 / f)` / `teaEquiv = Math.pow(1 + iPer, 12 / f) - 1` | fuente |
| 52 | `backend/main.py:9203-9239` | `_pf_value(row, as_of_iso)` | Espejo backend de `computePf`. **No calcula `tnaEquiv`/`teaEquiv`** | `return ((1 + r) ** (days / 365) - 1) if is_tea else (r * days / 365)` | fuente **parcial** |

#### Familia F — anualización (CAGR: la tasa geométrica, no la ponderada por dinero)

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 53 | `backend/twr.py:2165-2172` | `curva_indexada` | CAGR sobre la ventana que el índice midió. **Piso de medio año**: *"bajo medio año, anualizar es propaganda"* | `cagr = idx ** (1.0 / años) - 1.0` | **FUENTE** |
| 54 | `backend/main.py:15315` | `_cagr_from_monthly_rows` | Fallback sin snapshots | `cagr = prod ** (12 / len(factors)) - 1` | fuente |
| 55 | `backend/main.py:15320` | `_historical_cagr_global` | El wrapper canónico que consumen `/api/goals/cagr`, el diagnóstico de objetivos y los packets de IA | — | consumidor |

---

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `frontend/src/components/RentaFijaSections.jsx:383-384` | Card de bono en la zona **Renta Fija** de Cartera (desktop **y** móvil) | **"TIR"**, o **"TIR real"** si el bono es CER |
| `frontend/src/components/BondDetail.jsx:272-277` | Panel **"Rendimiento"** del detalle expandido de un bono | **"TIR efectiva anual a precio de hoy"** / **"TIR real (sobre CER) a precio de hoy"** |
| `frontend/src/components/BondDetail.jsx:277` | mismo panel | sufijo **" · aproximada"** en ámbar cuando `converged === false` |
| `frontend/src/components/BondDetail.jsx:283` | mismo panel | **"Bono {X} en broker {Y} sin MEP — TIR puede estar distorsionada."** |
| `frontend/src/components/BondDetail.jsx:288-290` | mismo panel, estado vacío | **"Sin precio de mercado para estimar la TIR — cargá un precio override en la posición."** / **"No se pudo estimar la TIR — verificá que el precio esté en la moneda del bono."** |
| `frontend/src/pages/Positions.jsx:2505` y `:2733` | `BondDetailRow` dentro de las tablas por broker (**sólo desktop**) | mismo panel "Rendimiento" |
| `frontend/src/pages/Positions.jsx:2794-2803` | `RentaFijaSections` desktop — pasa `tcMep`, `cerSeries`, `priceFor`, `isArsFor` | — |
| `frontend/src/pages/PositionsMobile.jsx:1355-1361` | `RentaFijaSections` móvil — **NO pasa `tcMep`, `cerSeries`, `priceFor` ni `isArsFor`** | la TIR **nunca se muestra en móvil** (ver Divergencias) |
| `frontend/src/pages/Dashboard.jsx:819-823` | Hero del Dashboard | **"Ganancia total"/"Pérdida total"** + el % del MWR al lado |
| `frontend/src/pages/Dashboard.jsx:857` | tooltip/nota del hero | **"= valor actual − capital aportado neto"** |
| `frontend/src/pages/Dashboard.jsx:834-835` | chip del hero | **"Aportado"** (el denominador del MWR) |
| `frontend/src/pages/Insights.jsx:550-555` | Hero de **Métricas** | "Resultado total" sobre capital aportado |
| `frontend/src/components/reports/MonthCard.jsx:235-236` | Card de mes en **Reportes** | **"Sobre aportado"** (`delta_pct_over_contrib`) |
| `frontend/src/pages/Goals.jsx:336-340` | Card de objetivo, escenario 2 | **"Solo con rendimiento"** → "{X}% anual" |
| `frontend/src/pages/Goals.jsx:330-334` | Card de objetivo, escenario 1 | **"Con aportes mensuales"** → "USD X / mes" |
| `frontend/src/pages/Goals.jsx:476-479` | Chip de diagnóstico del objetivo | **"Necesario · {X}%/año"** (el del backend) |
| `frontend/src/pages/Goals.jsx:183-190` | Cabecera de Objetivos | **"Tu CAGR real"** |
| `frontend/src/components/PlazosFijosGroup.jsx:145-146` | Grupo de plazos fijos en Cartera | **"TNA {x}"** / **"TEA {y}"** |
| `frontend/src/components/PfFormModal.jsx:392` | Modal de alta de PF | **"Equivale a TNA … · TEA … (a N días)"** |
| `frontend/src/components/guide/ReturnsDiagram.jsx:114-118` | Diagrama de la **Guía** que explica los retornos | **"Modified Dietz · estándar de industria"**. **No nombra TIR, IRR ni MWR en ningún lado del diagrama** |
| `frontend/src/pages/keywords/BonosAR.jsx:8,28,36,50,51,55,56` | Landing SEO de bonos AR | **"TIR implícita"**, **"TIR real de la cartera"**, **"Dashboard con TIR de tu cartera de bonos"** — funcionalidad que **no existe** |
| `frontend/src/pages/keywords/IOL.jsx:24` | Landing SEO IOL | **"valor técnico, paridad"** — tampoco existen |

**Quién NO lo lee, y sorprende:** [V]
- El **backend** nunca ve la TIR de un bono. `backend/main.py:25740-25759` arma el contexto de bonos para el LLM con `maturity`, `law`, `indexed_by`, `step_up` y un `_interpretation_hint` que dice *"duration aproximada por maturity vs hoy"* — o sea le pide al modelo que estime a ojo lo que el frontend ya calculó exacto tres pantallas más allá.
- Los **Reportes**, el **informe del asesor** y los **packets de IA** no incluyen la TIR de ningún bono.

---

### Dónde se persiste

**La TIR de un bono NO se persiste en ningún lado.** [V] Se calcula al vuelo, en el navegador, en cada render de `BondCardRow` y `BondDetailBody`. No hay columna, no hay caché, no hay endpoint. Verificado contra `backend/schema_pg.sql` (`grep -niE "yield|ytm|tir"` → 0 hits fuera de `rate_type`/`tasa` de plazos fijos) y contra `backend/trading.db`.

**El MWR tampoco se persiste como porcentaje**, pero **sus dos operandos sí**:

| tabla | columna | qué guarda | quién la escribe |
|---|---|---|---|
| `snapshots` | `total_value` | numerador del MWR (valor de mercado) | `backend/snapshots_job.py:778-791` |
| `snapshots` | `net_deposited` | denominador del MWR (capital aportado neto) | `backend/snapshots_job.py:766-767` vía `compute_net_deposited` |
| `snapshots` | `total_invested` | costo — fallback legacy del denominador | idem |
| `monthly_entries` | `capital_inicio`, `capital_final`, `deposits`, `withdrawals` | los 4 insumos de todos los Dietz | el importador y los hooks de recálculo |

**Lo único de la familia que sí se persiste calculado es el Modified Dietz por mes** — y sólo para el producto de asesores:

| tabla | columna | qué guarda |
|---|---|---|
| `twr_periods` | `ret` | `dietz(v0_usd, v1_usd, flow_usd)` de ese mes (`backend/twr.py:768`, sellado en `backend/twr.py:800-830`) |
| `twr_periods` | `v0_usd`, `v1_usd`, `flow_usd` | los tres operandos, para poder auditar el número |
| `twr_periods` | `quality` | `ok` / `dudoso` / `flujo_sospechoso` / `plano` |
| `twr_periods` | `revision`, `sealed_at` | versionado: si la historia cambia se escribe `revision+1`, nunca se pisa |

Definición en `backend/schema_pg.sql:1644-1661`. **Ojo: `twr_periods` no existe en la copia de desarrollo `backend/trading.db`** (`.schema twr_periods` devuelve vacío) — la base local viene de una rama vieja, como avisa el enunciado; manda `schema_pg.sql`.

**Los plazos fijos guardan la tasa de entrada, no la derivada:** `plazos_fijos.tasa` + `plazos_fijos.rate_type ∈ {TNA, TEA}` (`backend/schema_pg.sql:1388-1389`). `teaEquiv`/`tnaEquiv` se derivan al vuelo en el frontend.

**Los objetivos guardan el supuesto, no el resultado:** `goals.expected_return_pct` y `goals.monthly_contribution` (leídas en `backend/ai/builders/goal.py:35-36`). La tasa requerida se recalcula en cada render.

---

### ⚠️ Implementaciones divergentes

#### D1 — La TIR de un bono existe en desktop y **no existe en móvil**. `[V]` 🔴

`frontend/src/pages/PositionsMobile.jsx:1355-1361` renderiza `RentaFijaSections` con seis props menos que el desktop:

```jsx
<RentaFijaSections positions={enriched}
  valuePos={p => ({...})}
  brokers={brokers} displayCurrency={currency} tcValuacion={tcValuacion} onChanged={loadAll} />
```

vs. `frontend/src/pages/Positions.jsx:2794-2803`, que además pasa `tcMep={tcMepStrict} cerSeries={cerSeries} cerStale={cerStale} isArsFor={...} priceFor={...} priceMeta={...}`.

Los defaults son `null` (`frontend/src/components/RentaFijaSections.jsx:64`), y la card hace `price={priceFor ? priceFor(p) : null}` (`:244`). Como el gate de la TIR es `if (meta?.maturity && price != null && price > 0)` (`:298`), en móvil **`tir` queda siempre `null` y la columna TIR nunca se renderiza**.

Peor: si el usuario expande la card en el móvil, `BondDetailBody` recibe `currentPrice={price}` = `null` (`:503`) y muestra el texto **"Sin precio de mercado para estimar la TIR — cargá un precio override en la posición."** (`frontend/src/components/BondDetail.jsx:289`) — le pide al usuario que cargue a mano un precio que la app **ya tiene** y que está mostrando dos líneas más arriba en la misma card.

Y `isArsFor` en `null` hace `isArs = false` (`frontend/src/components/RentaFijaSections.jsx:241`), así que aunque el precio llegara, un bono en un broker ARS se trataría como broker USD.

**Qué pantalla ve cuál:** Cartera desktop → TIR en la card, TIR en el detalle, y TIR también en el detalle expandible de las tablas por broker (`Positions.jsx:2505`, `:2733`). Cartera móvil → ninguna de las tres (`PositionsMobile.jsx` ni siquiera importa `BondDetail`).

#### D2 — Los dos call sites de la TIR discrepan cuando falta el MEP. `[V]`

Mismo bono, mismo instante, dos números distintos según si mirás la card o la abrís:

| | card (`RentaFijaSections.jsx:300-307`) | detalle (`BondDetail.jsx:96-114`) |
|---|---|---|
| bono USD en broker ARS **con** MEP | `price / tcMep` | `currentPrice / tcMep` — **coinciden** |
| bono USD en broker ARS **sin** MEP | `pBond = null` → **no muestra TIR** | `priceInBondCurrency = currentPrice` **sin convertir** → muestra una TIR calculada sobre un precio en pesos tratado como dólares, con el aviso "puede estar distorsionada" |

Es decir: la card se calla y el detalle publica un número que puede estar mal por un factor de ~1.400. El aviso está (`BondDetail.jsx:283`), pero el número grande en violeta también.

#### D3 — El accrued del CER queda fuera en el helper huérfano. `[V]`

`estimateYieldDetailed` genera el schedule **con** CER (`frontend/src/utils/bondSchedule.js:322`) y de ahí saca el accrued — correcto. Pero `getAccruedInterest` (`frontend/src/utils/bondSchedule.js:387-395`), pensado para que la UI muestre "dirty = clean + accrued", llama `generateSchedule(ticker)` **sin `cerSeries`** (`:390`): para un TX26/TX28 devolvería el accrued nominal, no el ajustado. Hoy **no rompe nada porque nadie la llama**, pero es una trampa armada.

#### D4 — Cinco motores de Modified Dietz, y uno de ellos no es Dietz. `[V]` 🔴

`backend/twr.py:559` se autoproclama SSoT (*"Es EL primitivo: si alguna pantalla calcula el retorno de otra forma, vuelve a haber dos motores"*). Hay cinco:

| motor | denominador | piso | techo | quién lo ve |
|---|---|---|---|---|
| `backend/twr.py:559` | `v0 + 0,5·flow` | **−100 %** | ninguno | Métricas (`/api/insights/performance`), motor del asesor, `twr_periods` |
| `backend/reporting/builder.py:783` | `start + 0,5·flows` | **ninguno** (comenta: *"si el portfolio cae -150%, devolvemos -150"*) | ninguno | **Reportes** |
| `backend/main.py:11871` | `ci + 0,5·net` | ninguno (el clamp está en el caller, `:11889`) | ninguno | `/api/insights/mtm-audit` (herramienta interna) |
| `backend/main.py:35700` | `v0 + flows/2` **y sólo publica si `> 100`** | ninguno | ninguno | **informe firmado del asesor** |
| `backend/main.py:15305` | **`ci` pelado — sin el ½·flujo** | −95 % | **+500 %** | fallback de CAGR cuando no hay snapshots |

El quinto es el que más preocupa: `ret_m = max(-0.95, min(5.0, (cf - ci - net) / ci))`. No es Modified Dietz, es "Dietz simple" con denominador de apertura, y alimenta el CAGR que después se usa como "tu ritmo" en el diagnóstico de Objetivos y en los packets de IA.

Y en el frontend hay al menos seis copias más (filas 36-40 de la tabla), tres de ellas con una heurística *big-withdrawal* (`|flow|/ci > 0,3 y flow < 0` → denominador = capital de apertura) que **el backend no tiene**: `Insights.jsx:675`, `evolution.js:536`, `evolution.js:575`. O sea que el mismo mes puede dar distinto en Métricas (frontend, con heurística) que en Reportes (backend, sin heurística).

#### D5 — Tres denominadores para "el % del período". `[V]`

Para la misma pregunta —"¿cuánto rindió?"— conviven tres divisores:

| convención | dónde | fórmula |
|---|---|---|
| capital aportado neto | Dashboard, Métricas, HomeMobile | `/ netDeposited` |
| valor de la punta de apertura | `evolution.js:365` (`computeReturnDelta` → P&L del día y del mes en Dashboard y HomeMobile) | `pct = usd / prevValue` |
| Dietz (`v0 + ½·flujo`) | todo lo demás | `/ (v0 + 0.5*flow)` |

`computeReturnDelta` es especialmente confuso: **el numerador es MWR** (`Δ(value − net_deposited)`, correcto y ajustado por flujos) pero **el denominador es el valor de mercado de la punta**, no lo aportado. El % que sale no es ni el MWR del hero ni el Dietz del gráfico.

#### D6 — El "aportado" se calcula distinto en frontend y backend. `[V]`

`netCapitalContributed` (`insightsModel.js:41-52`) **incluye la baseline** (`capital_inicio` del primer mes, prefiriendo `capital_inicio_costo`). `fetch_cum_deposits_until` (`builder.py:716-744`) explícitamente **la excluye** (`include_baseline=False`, *"para preservar la semántica histórica del endpoint /reportes"*).

Consecuencia: el denominador del "Sobre aportado" de Reportes es **más chico** que el "Aportado" del Dashboard para todo usuario que importó historia. El mismo mes va a dar un % más alto en Reportes.

Además `HomeMobile.jsx:135-142` **reimplementa** `netCapitalContributed` inline y se olvida del fallback a `capital_inicio_costo`, así que en móvil el denominador se contamina con la ganancia latente cuando `applyMtmToMonthly` re-ancló el primer mes.

#### D7 — La tasa requerida del objetivo se calcula dos veces, sobre tres capitales distintos. `[V]` 🔴

La **misma card de Objetivos** muestra dos números que dicen lo mismo:

- **"Solo con rendimiento · {X}% anual"** — frontend, `Goals.jsx:266-268`: `(target/currentValue)^(1/yearsLeft) − 1`, con `currentValue` = suma de `computeBrokerValue` sobre precios live (`frontend/src/pages/Goals.jsx:80-83`) y `yearsLeft = monthsLeft/12` donde `monthsLeft` sale de dividir por **30,4375 días** (`frontend/src/pages/Goals.jsx:255`).
- **"Necesario · {Y}%/año"** — backend, `goals_diagnostic.py:101` + `:267`: `((target/current_value)^(1/months))^12 − 1`, con `current_value` = Σ `_position_value_usd` (`backend/main.py:15258-15266`) y `months` = diferencia de calendario `(td.year−n.year)*12 + (td.month−n.month)` (`goals_diagnostic.py:92`).

Álgebra idéntica, **inputs distintos en los dos parámetros**. Y hay un tercer capital para el mismo objetivo: `backend/ai/builders/goal.py:44-55` usa el `total_value` del último snapshot de `snapshots_medibles`. Tres capitales → tres tasas requeridas para la misma meta, dos de ellas impresas a 15 píxeles de distancia.

**Y las tres ignoran `goals.monthly_contribution`**, que la tabla sí guarda: `backend/goals_diagnostic.py:97-98` lo dice literal (*"SIN aportes"*) y `backend/ai/builders/goal.py:98-99` también. Sólo `requiredMonthly` (`frontend/src/pages/Goals.jsx:623`) modela aportes, y lo hace para despejar el aporte, no la tasa. Así que si el usuario cargó un aporte mensual, el diagnóstico "vas atrasado" lo calcula como si no aportara nada nunca más.

#### D8 — TEA de plazo fijo: la conversión existe dos veces y una está muerta. `[V]`

`valuation.js:828` calcula `teaEquiv = (1 + tp)^(365/P) − 1` y se muestra en `PlazosFijosGroup.jsx:146`. `bondPricing.js:311` calcula exactamente la misma idea para bonos (`semiAnnualToEffectiveAnnual`), está exportada, tiene tests (`bondPricing.test.js:297-301`) y **no la llama nadie**. El backend `_pf_value` (`main.py:9203`) es espejo de `computePf` pero **no devuelve TEA ni TNA equivalente**, así que ese par de números sólo existe si el usuario abre la app en el browser.

#### D9 — Convergencia: la TIR se muestra igual cuando no convergió. `[V]`

`yieldToMaturity` devuelve `{ytm: (lo+hi)/2, converged: false, method:'max_iter'}` (`bondPricing.js:289`) — un número. El detalle lo distingue con un discreto **" · aproximada"** en ámbar (`BondDetail.jsx:277`). **La card de Renta Fija no chequea `converged` en absoluto** (`RentaFijaSections.jsx:306` hace `?.ytm ?? null`): muestra el número en violeta bold, sin ninguna marca.

---

### Zonas grises

**Z1 — La landing promete una TIR de cartera que el código no calcula.** `[V]`
`frontend/src/pages/keywords/BonosAR.jsx:36` — *"Ves TIR real + flujo proyectado … Dashboard con TIR de tu cartera de bonos"*; `:51` — *"TIR real de la cartera"*; `:28` pone en boca del usuario *"¿Cuál es la TIR de mi cartera de bonos?"*. **No existe ninguna agregación de TIR por cartera, por sección ni por broker.** La TIR es estrictamente por posición individual, y sólo en desktop. Las mismas páginas prometen **"paridad"** (`BonosAR.jsx:8`) y **"valor técnico"** (`IOL.jsx:24`): `grep -rni "paridad\|valor técnico"` no encuentra ninguna implementación (los hits de "paridad" en el código son "paridad frontend/backend" y "paridad con desktop", otra acepción).

**Z2 — "TIR real (sobre CER)": el nombre es correcto pero por un accidente.** `[V/I]`
El schedule multiplica cada flujo por `CER(fecha_pago)/CER(emisión)` con **LOCF** (`frontend/src/utils/bondSchedule.js:154-158`). Como la serie CER sólo tiene pasado, todo pago futuro se ajusta con el **último CER conocido** — o sea, los flujos quedan congelados en poder adquisitivo de hoy y la TIR que sale es efectivamente real. [I] Eso es lo correcto, pero **el código no lo dice en ningún lado**: no hay un comentario que explique que el LOCF sobre fechas futuras es lo que produce la tasa real. Si alguien "arreglara" el LOCF proyectando inflación, la TIR pasaría a ser nominal en silencio y el label seguiría diciendo "TIR real".

**Z3 — 16 obligaciones negociables corren con un day-count inventado.** `[V]`
De los 31 tickers con `maturity` en `frontend/src/utils/bondMeta.js`, sólo 6 declaran `dayCount` (`ACT/365`, los CER) y otros 6 lo traen de `bondSchedulesAR.js` (`30/360`, los soberanos del canje). **Las 16 ONs corporativas (YCA0O, YCAMO, TLC1O, PMCAO, MGC1O, …) no declaran ninguno** (`frontend/src/utils/bondMeta.js:135-150`), así que caen al default `'ACT/365.25'` (`frontend/src/utils/bondSchedule.js:331`), que el propio archivo describe como *"No-standard … backwards-compat"* (`frontend/src/utils/bondPricing.js:87-91`). Ninguna tiene `issueDate` tampoco, así que el accrued de la primera fecha del schedule generado sale 0 (`frontend/src/utils/bondPricing.js:146-147`: `const periodStart = prev ? prev.date : issueDate; if (!periodStart) return 0`). El impacto en la TIR es de decenas de puntos básicos, no de órdenes de magnitud — pero es sistemático y no está declarado en la UI.

**Z4 — El schedule de las ONs se fabrica retrocediendo desde el vencimiento.** `[V]`
`frontend/src/utils/bondSchedule.js:197-200` genera las fechas de pago desde `maturity` hacia atrás cada `months`, hasta `issueDate` / primera amortización / **5 años atrás**. Para una ON sin `issueDate` y sin `amortSchedule`, eso significa que las fechas de cupón son una *invención plausible*, no el prospecto. La TIR que sale es tan buena como esa grilla.

**Z5 — Ninguna TIR llega al LLM.** `[V]`
`backend/main.py:25740-25759` le entrega al modelo `maturity`, `law`, `indexed_by`, `step_up` y le pide *"duration aproximada por maturity vs hoy"*. El usuario ve "TIR 16,2 %" en pantalla, le pregunta al Coach IA por ese bono, y el modelo tiene que estimar a ojo un número que la app ya resolvió con Newton-Raphson dos componentes más allá. Es un candidato obvio a discrepancia usuario-vs-IA que nadie está midiendo.

**Z6 — `todayIso()` es UTC en los dos call sites.** `[V]`
`RentaFijaSections.jsx:22` (`new Date().toISOString().slice(0,10)`) y `BondDetail.jsx:78` (idem). En Argentina (UTC−3), después de las 21:00 hora local el "hoy" de la TIR salta al día siguiente. Efecto práctico: despreciable en la tasa, pero cambia qué pago cuenta como "próximo" el día exacto de un cupón.

**Z7 — El comentario que dice "no implementamos IRR" es de 2 líneas y nadie más lo sabe.** `[V]`
`frontend/src/utils/insightsMetrics.js:13-15` es el **único** lugar del repo donde se documenta la decisión de usar Modified Dietz en vez de IRR/XIRR, y está enterrado en el header del archivo de Sharpe ratio. El diagrama de la Guía (`frontend/src/components/guide/ReturnsDiagram.jsx`), que es la pieza pensada para explicarle al usuario cómo se mide su rendimiento, presenta "Modified Dietz · estándar de industria" (`:118`) y **no menciona nunca** que existe una alternativa ponderada por dinero ni por qué no se usa. Un usuario que viene de IBKR/Schwab y busca su "money-weighted return" no va a encontrar ni el número ni la explicación.

**Z8 — El MWR está declarado defectuoso en un archivo y sigue siendo el número grande en otro.** `[V]`
`evolution.js:469-472` documenta que el MWR se distorsiona con retiros grandes y por eso la curva pasó a TWR. `evolution.js:527-531` da el caso real: *"papá retira \$70k de \$100k … Con MD clásico: 20/65 = +30,7 % que compunde a +91 %"*. Pero `Dashboard.jsx:266` sigue dividiendo por `netDeposited`, que es exactamente la magnitud que colapsa cuando hay retiros. Con retiros netos por encima de los aportes, `netDeposited` puede ser **negativo** — el código lo sabe (`frontend/src/utils/evolution.js:261-263`: *"4.744 filas (11,7%) en 192 usuarios tienen `net_deposited < 0`"*) — y el guard del Dashboard es `netDeposited > 0 ? ... : 0`: publica **0,00 %** donde debería decir "no se puede medir". Es el mismo defecto que `computeReturnDelta` sí arregló (`evolution.js:348-356`: *"Un cero falso es peor que un vacío"*) y que en el hero quedó vivo.

**Z9 — `twr_periods.ret` es lo único de esta familia que se persiste, y el motor que lo escribe no es el que ve el usuario retail.** `[V]`
`backend/twr.py:800-830` (`sellar`) sella el Dietz mensual con `quality` y `revision` para el producto de asesores. La app retail no lee `twr_periods` para el hero ni para Reportes — recalcula con `_modified_dietz_pct` (`builder.py:783`), que como vimos en D4 tiene otras reglas de clamp. El número sellado y auditado existe; la pantalla que más se mira no lo usa.

**Z10 — No pude determinar (no encontrado):**
- Ninguna función que agregue TIR a nivel cartera, sección o broker. **no encontrado**.
- Ningún test —frontend o backend— que compare la TIR de la card contra la del detalle expandido. `frontend/src/utils/bondPricing.test.js` y `bondSchedule.test.js` testean el solver aislado; `bondSchedulesAR.test.js` y `bondScheduleCER.test.js` testean tickers canónicos (AL30, AL35, TZX26). **No hay test de los dos call sites.** **no encontrado**.
- Ningún test que cubra la ruta móvil de `RentaFijaSections` (props faltantes). **no encontrado**.
- Ninguna traza de que la divergencia D7 (dos tasas requeridas en la misma card) haya sido detectada: no hay comentario, TODO ni test al respecto. **no encontrado**.
