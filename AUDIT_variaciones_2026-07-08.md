# Audit de variaciones — por qué mobile ≠ desktop y por qué la var. diaria/30d/mensual está mal

**Repo auditado:** `/private/tmp/rendi-varaudit` · **Fecha:** 2026-07-08 · 20 hallazgos confirmados (3 critical, 8 high, 7 medium, 3 low tras merge de duplicados), todos verificados adversarialmente con recálculo numérico.

---

## 1. TL;DR

Los síntomas reportados salen de **tres causas raíz que se combinan**: (1) la clase C1 conocida — la cadena `monthly_entries` vive **a COSTO** y todo lo que la compara contra un valor a MERCADO (el "P&L Mes" mobile, los reportes de mes/año/YTD, el CAGR, el TWRR de Insights) fabrica el unrealized **acumulado de toda la vida** como si fuera "variación del período"; (2) la clase FX conocida — el cron de snapshots valúa el **cash ARS al BLUE** mientras el live compara al **MEP**, así que el "P&L Día" tiene un fantasma permanente proporcional al cash; y (3) **cada superficie re-implementa el fetch de símbolos y la fórmula de delta por su cuenta** — Dashboard pide tickers crudos, PositionsMobile no pide `.BA` para lotes `costInPesos`, HomeMobile no descuenta flujos — y por eso el mismo lote, el mismo instante, da números distintos en cada pantalla. Mobile no está "peor calculado": está calculado **con otras fuentes y otras fórmulas** que desktop.

---

## 2. La divergencia mobile↔desktop, explicada

Mismo user, mismo instante, y estas son las cadenas causales exactas:

**a) "P&L Mes":** HomeMobile lee `pnl_realized + pnl_unrealized` de la última entry de `monthly_entries` (`HomeMobile.jsx:139-141`). Pero `pnl_unrealized` lo escribe el sync del Dashboard **desktop** con Σ(valor−costo) de TODAS las posiciones = unrealized **lifetime** (los meses cerrados nunca absorben MtM: `_repair_monthly_chain`, `main.py:7042-7058`, los deja a costo con `pnl_unrealized=0`). El desktop en cambio muestra "Este mes" con `computeReturnDelta` sobre **snapshots a mercado** desde el 1° del mes (`Dashboard.jsx:509-514`). Dos fuentes sin ninguna relación: mobile muestra la ganancia histórica rotulada como "del mes", desktop el MTD real.

**b) "Últimos 30 días":** mobile hace `last.total_value − first.total_value` crudo (`HomeMobile.jsx:121-131`) — un depósito cuenta como ganancia. Desktop hace `Δ(value − net_deposited)` (`Dashboard.jsx:490-497`). Encima `days=30` en el backend es **LIMIT 30 filas**, no 30 días (`main.py:3474-3478`) → con huecos del cron la ventana mobile abarca 40+ días mientras desktop filtra por fecha real.

**c) Valuación del mismo lote:** Dashboard pide símbolos **crudos** (`Dashboard.jsx:137-139`) → CEDEARs/`.BA` en cuentas USD caen **a costo en desktop** pero a mercado en mobile. PositionsMobile no pide `.BA` para lotes `costInPesos` (`PositionsMobile.jsx:395`) → **a costo en mobile** pero a mercado en desktop. Cada pantalla arma el fetch a mano y cada una tiene un agujero distinto.

**d) La referencia del "P&L Día":** los snapshots tienen **doble escritor con FX distinto** — el cron escribe cash ARS ÷ BLUE (`snapshots_job.py:189`), el POST del Dashboard escribe todo-MEP. HomeMobile **nunca postea** → un user mobile-only compara siempre live-MEP contra snapshot-blue → fantasma diario permanente. Un user desktop-diario lo pisa con MEP → el fantasma desaparece. **El mismo bug se manifiesta distinto según el device.**

**e) Reportes:** tercera versión de todo — `capital_inicio` a costo vs `live_value` a mercado, más un `tc_blue` **estático de config (default 1415)** para el end_value live (`main.py:20547-20551`) contra snapshots al blue live del día.

---

## 3. Hallazgos por severidad

### CRITICAL

#### C-1. "P&L Mes" mobile = unrealized acumulado DE TODA LA VIDA, no del mes `[known-class C1]`
`frontend/src/pages/HomeMobile.jsx:139-141` (display L342-348)

`pnlMonth = pnl_realized + pnl_unrealized` del último entry global. `pnl_unrealized` es Σ(valor−costo) de todas las posiciones abiertas (lo escribe `Dashboard.jsx:368-454` vía sync-unrealized, `main.py:8199-8247`), y como los meses cerrados quedan a costo, ese número es el unrealized **desde el inicio de la cuenta**.

- **Escenario:** costo US$50.000, mercado US$58.000 (+8.000 ganados en 2 años). Julio se movió +US$300, sin ventas. Desktop "Este mes" = **+US$300**. Mobile "P&L Mes" = **+US$8.000** (26× el real, en verde gigante).
- **Agravantes verificados:** (a) HomeMobile nunca sincroniza → el número además queda **stale** al último Dashboard desktop que corrió; (b) tras el rollover de mes (que SÍ es lazy backend-side, `main.py:8659-8676` — el rollover per-se está bien) el KPI muestra $0 hasta que algún device sincronice.
- **Fix:** calcular igual que desktop: `computeReturnDelta(snapshots, { liveValue: totals.totalValue, liveNetDeposited: aportado, sinceDate: '${Y}-${M}-01' })`. Ya se importa `computeDailyPnl` del mismo módulo; es agregar un import. Dejar de leer `monthly_entries` para este KPI.

#### C-2. Reportes: Mes/Año/YTD en curso = capital_inicio a COSTO vs live a MERCADO `[known-class C1]`
`backend/reporting/builder.py:267-317` + `main.py:20465-20486` (`_ytd_delta`)

`compute_metrics_for_period` toma `start_value = capital_inicio` (cadena a costo) y para el período en curso pisa `end_value` con `live_value` (MtM real, `main.py:20548-20558`). El delta del mes/año en curso = **todo el unrealized histórico**. Simétricamente, los meses **cerrados** muestran solo el realized → heatmap y MonthCards "flat" aunque el mercado se movió ±10%, y contradicen a los movers del MISMO card (que sí usan snapshots MtM). El año TWR concentra el fantasma en el Dietz del último mes. `_ytd_delta` idéntico: cuenta como "YTD" ganancias de años anteriores.

- **Escenario:** compra US$10.000 en feb, hoy vale US$13.000, julio flat → Julio: "+US$3.000 (+30,0%)" cuando julio real = 0%. Espejo negativo = el "−64,9% fantasma". Tab Día del mismo momento: ~0% → contradicción entre tabs visible.
- **Fix (patch pre-C1):** para el período en curso, `start_value` = snapshot MtM at-or-before del inicio (`fetch_snapshot_at_or_before` ya existe, `builder.py:135`), fallback `delta_pct=None` patrón `dw_incomplete`. Fix de raíz = plan C1 (ver H-8 y M-7 antes de mass-aplicar el backfill).

#### C-3. Mes en curso sin monthly_entry → "P&L del mes" = el portfolio ENTERO sobre "capital inicial de US$ 0"
`backend/reporting/builder.py:269-277`

Si `fetch_monthly_entry` da None para el mes actual, `start=0` y `end=live_value` → `delta_usd = live_value` completo. La fila global del mes solo la crean: `autoRolloverIfNeeded` (montado **solo en /mensual**, `MonthlySummary.jsx:118` — el MonthlyTeaser del Dashboard solo lee), una venta con P&L, o un flujo. Un holder pasivo que no visita /mensual ni opera ve su cartera entera como "ganancia del mes" **todo el mes**. (Ascendida de medium: la ventana de exposición es mayor de lo que parecía — el Dashboard NO crea la fila.)

- **Escenario:** 1-jul, cartera US$13.000, junio cerró en 10.000, fila 2026-07 no existe → hero "P&L del mes +US$13.000", narrativa literal "ganaste US$ 13.000 (+0.0%) sobre un capital inicial de US$ 0".
- **Fix:** en la rama month, heredar `start_value` del `capital_final` del mes anterior (query espejo de `main.py:7288-7301`) o marcar el período incompleto (`delta_usd=None`), como ya hace day/week.

---

### HIGH

#### H-1. "P&L Día" fantasma permanente: cron snapshotea cash ARS ÷ BLUE, el live compara ÷ MEP `[known-class FX]`
`backend/snapshots_job.py:189` + `backend/main.py:19863-19867` (consumido en `HomeMobile.jsx:151-155`, `Dashboard.jsx:506`)

El cron pasa `_get_blue_for_scheduler` = blue genuino y `compute_broker_value_usd` divide el cash ARS por eso; los holdings van a MEP → snapshot de **sabor mixto**. El live (mobile y desktop) valúa el cash con `pickFinancialRate` = MEP. `computeDailyPnl` resta ambos → el spread blue−MEP aparece TODOS los días como "P&L Día" sobre el cash, y se re-arma cada noche. El POST del Dashboard escribe todo-MEP → serie con doble escritor, serranito en el sparkline, y **el fantasma es sistemático solo en mobile-only** (HomeMobile nunca postea). El comentario de `Dashboard.jsx:346-349` ("el cron igual snapshotea en MEP") es **falso** para el cash. Bonus riel CCL: live todo ÷CCL vs snapshot MEP → phantom sobre todos los holdings ARS (ver M-6).

- **Escenario:** cash ARS 14.900.000, blue 1.490, MEP 1.415, mercado quieto → snapshot 10.000, live 10.530 → "+US$530 de P&L Día" **cada día**, sin que nada haya rendido.
- **Fix:** en `take_snapshot_for_user`, convertir el cash ARS con el mismo `tc_cedear`/user_fx (MEP) que ya usa para holdings; pasar el blue solo donde el producto lo pida. Verificar el doble-writer del mismo día.

#### H-2. Sparkline "Últimos 30 días" mobile NO descuenta flujos: un depósito es "ganancia"
`frontend/src/pages/HomeMobile.jsx:121-131` (display L293-321)

`deltaUsd = last.total_value − first.total_value` crudo. El snapshot **trae** `net_deposited` (el mismo archivo lo usa 20 líneas abajo para el P&L Día) y se ignora. Desktop ya lo corrigió (`periodChange`, `Dashboard.jsx:490-497`, con comentario que declara este patrón como bug fixeado).

- **Escenario:** base 10.000, depósito 5.000 el 20-jun, hoy 15.200 → mobile "**+US$5.200 (+52%)**"; real flow-adjusted (= lo que muestra desktop) **+US$200 (+2%)**. Con un retiro: pérdida fantasma.
- **Fix:** `Δ(total_value − net_deposited)` con fallback `netDepositedOf` (`evolution.js:122-124`). La serie cruda queda solo para el trazo.

#### H-3. Dashboard desktop pide símbolos crudos → CEDEARs en cuentas USD a COSTO en desktop, a MERCADO en mobile + escribe snapshots subvaluados
`frontend/src/pages/Dashboard.jsx:137-139`

`usdtSyms = map(p => p.asset)` sin `priceSymbol`, pero `computeBrokerValue` valúa esos lotes buscando `prices['X.BA']` (`valuation.js:340,420`) → undefined → costo, P&L 0. HomeMobile:94 y Positions:448-453 SÍ piden el `.BA`. Consecuencias: (1) total desktop ≠ hero mobile por todo el MtM de esos activos; (2) el **POST /snapshots del Dashboard persiste el total subvaluado** — el guard de cobertura no lo frena porque `hasPrice` chequea `prices[p.asset]` (el ticker US que sí llegó, L330) — y el cron lo pisa a la noche → salto fantasma en la serie; (3) el sync-unrealized omite esos lotes → alimenta el "P&L Mes" mobile con dato incompleto.

- **Escenario:** 100 MELI en "Cocos · USD", costo US$1.150, mercado US$1.400 → mobile 1.400, desktop 1.150 (−18%); si desktop snapshotea, el sparkline mobile marca "Hoy · $1.150" bajo un hero de $1.400.
- **Fix:** copiar la construcción de símbolos de Positions.jsx:448-453; endurecer `hasPrice` para chequear la MISMA key con la que se valúa.

#### H-4. PositionsMobile no pide `.BA` para lotes costInPesos → fila a costo en mobile, a mercado en desktop
`frontend/src/pages/PositionsMobile.jsx:395`

Falta la pata `|| costInPesos(p)` que desktop (Positions.jsx:448-453, con comentario que documenta el caso "IOL sin sibling") y HomeMobile:94 sí tienen. Lote `currency='ARS'` no-CEDEAR en broker USD standalone → se pide el ticker US pelado, `pesoLotUsd` busca `prices['X.BA']` → undefined → valor = costo, P&L 0, Var. día "—".

- **Escenario:** GGAL 100 nominales, invested 600.000 ARS en "IOL USD". Desktop: 7.980×100/1.200 = **665 USD, +33%**. Mobile: **500 USD, 0%, "—"**. Misma fila, mismo instante, −25%.
- **Fix:** espejar `(isArUsdBroker(p.broker) || costInPesos(p)) ? priceSymbol(p.asset, true, p.asset_type) : ...`.

#### H-5. Var. día fantasma −90% en mobile: precio `.BA÷MEP` de hoy contra prev-close del ADR US de ayer
`frontend/src/pages/PositionsMobile.jsx:614`

Para lotes costInPesos, el lookup del cierre previo cae a `prevClose[p.asset]` (ADR NYSE en USD) mientras `priceLocal` es `.BA÷MEP` (~1/ratio del ADR). Cuando el `.BA` está disponible por otra posición, se computa `perUnit = (.BA÷MEP) − prev_ADR` → variación gigante. Aplica a tickers locales que coinciden con su ADR: GGAL, BMA, SUPV, CEPU, LOMA, TGS. Los casos hermanos (`usdSymBA`, comentario "daba ~-100%") fueron fixeados; esta rama quedó afuera.

- **Escenario:** GGAL priceLocal 6,65, prevClose ADR 64,40 → dayVar = **−89,7% / −5.775 USD** para 100 nominales. Esperado: −5,4 USD (−0,8%). Envenena la fila Y el agregado por ticker.
- **Fix:** tratar costInPesos como cedearUsd en el lookup (`prevClose[priceSymbol(..., true, ...)]` ÷ tcCedear). Requiere fixear el fetch (H-4) Y el lookup — solo el fetch da "—" (seguro pero incompleto).

#### H-6. useMonthlyData: el "CONSISTENCY FIX" viejo PISA el quick-win C1 → el mes en curso vuelve al fantasma `[known-class C1, regresión]`
`frontend/src/hooks/useMonthlyData.js:539-555` (pisa L402-426)

El quick-win C1 calcula el delta del mes vivo puro-MtM desde snapshots. Después, el paso 9 muta el mismo objeto si `|liveValue − capital_final| > 0.01` con `deltaUsd = liveValue − startUsd(costo) − flows` — la mezcla que el quick-win eliminaba. Dispara **casi siempre** (capital_final sync intradía vs snapshot del cron nunca coinciden al centavo; el test solo pasa porque eligió gap=0). Contamina el MonthlyTeaser del Dashboard ("Julio en curso +80.5%") y deja ytdPct/best/worstMonth latentes. Git confirma: CONSISTENCY FIX es anterior al quick-win; el fix nuevo olvidó neutralizar el overwrite viejo.

- **Escenario:** quick-win → +60 (+0,3%) correcto; paso 9 → 18.050−10.000 = **+8.050 (+80,5%)**, y el TWRR anual multiplica ×1.805.
- **Fix:** skipear la mutación de delta cuando el mes es el vivo (conservar el delta MtM, actualizar solo endUsd/isLive).

#### H-7. Reportes: Δ1d/7d/30d restan net_deposited con convenciones distintas → delta inflado en exactamente el baseline
`backend/main.py:20328` (+20297-20302, 20427-20432)

`cum_deposited` se calcula con `include_baseline=False` y se pasa a `_snapshot_delta`, pero el `net_deposited` del snapshot (lado prev) viene CON baseline (`snapshots_job.py:643`). El delta queda sobreestimado en el `capital_inicio` del primer monthly_entry. **Es el mismo bug ya fixeado en `builder.py:336-337` (AUDIT B5/B7)** que quedó sin portar a esta segunda superficie. Afecta a todo usuario con historia seedeada.

- **Escenario:** baseline 50k, flows 10k, ayer 61.000, hoy 61.500 → Δ1d = **+US$50.500 (+82,8%)**. Esperado: +US$500. Error constante en los 3 chips.
- **Fix:** netdep separado con `include_baseline=True` para `_snapshot_delta`; `cum_deposited` intacto para el KPI "Capital aportado".

#### H-8. Reportes día/semana con filtro de broker muestran el delta del portfolio GLOBAL como si fuera del broker
`backend/reporting/builder.py:318-345 + 373-374`

`fetch_snapshot_at_or_before` no filtra por broker (snapshots son globales); las operations sí se filtran → WeekCard/tab Semana de "Binance" muestra el delta de TODO el portfolio, y `unrealized = delta_global − realized_broker` mezcla universos. El mismo feature demuestra la intención correcta en otros dos lugares (el summary anula snap_value con broker≠global; la rama month usa monthly per-broker) — esta rama es el hueco.

- **Escenario:** Binance US$2.000 flat, global +1.500 por Balanz → WeekCard "Binance" **+US$1.500 (+7,5%)**; con realized −100, unrealized mostrado = +1.600 en un broker de 2.000.
- **Fix:** con broker_filter en week/day: `delta_pct=None` + delta solo-realized (o `dw_incomplete=True`).

#### H-9. Reportes: end_value live valuado con `tc_blue` de config ESTÁTICO (default 1415) contra start al blue live
`backend/main.py:20547-20551` (+20495-20503)

`_user_tc_blue` = config con default hardcodeado 1415, sembrado al signup y **nunca refrescado**. El start del período sale del snapshot escrito con el blue live del día → las dos puntas en bases FX distintas; con caché MEP fría, la distorsión escala a TODOS los holdings AR.

- **Escenario:** cash 12,5M ARS: start 12,5M/1250 = 10.000; end 12,5M/1415 = 8.834 → "**−US$1.166 (−11,7%)**" fabricado; y Reports "Hoy" queda 15,2% abajo del Dashboard (MEP 1200 → 10.417) en el mismo instante.
- **Fix:** resolver el rate con la misma cascada live (`_current_cedear_rate`/`_display_blue`) y unificar con el rate del snapshot.

---

### MEDIUM

#### M-1. "P&L Mes" mobile queda stale para users mobile-only
`frontend/src/pages/HomeMobile.jsx:135-141` — Los únicos escritores de `pnl_unrealized` son Dashboard/MonthlySummary desktop; HomeMobile nunca sincroniza → el KPI queda congelado al último sync mientras hero y P&L Día del mismo screen son live. (Matiz verificado: el rollover SÍ es lazy backend-side — `main.py:8659-8676` crea la fila del mes y zero-ea la anterior — así que el modo de falla es "congelado / $0 en mes fresco", no "mes anterior sin zero-ear".) **Se resuelve gratis con el fix de C-1** (calcular desde snapshots).

#### M-2. Sparkline "Hoy" = cierre de ayer sin plazos fijos, el hero 3 líneas arriba es live + PF
`frontend/src/pages/HomeMobile.jsx:121-131` — La serie nunca appendea el punto live (desktop sí: `buildPortfolioValueSeries` con liveValue, `Dashboard.jsx:460`) y los snapshots son positions-only. Hero 21.000 arriba, "Hoy · $19.800" abajo (5,7% de gap sin explicación) — dos "hoy" distintos en la pantalla más mirada. **Fix:** usar `buildPortfolioValueSeries(snapshots, 30, totals.totalValue, aportado)`.

#### M-3. Cripto en sub-broker AR "· USD": se fetchea `BTC.BA` pero la valuación lee `prices['BTC']` → a costo en mobile, a mercado en desktop
`frontend/src/pages/HomeMobile.jsx:94` (+ `Positions.jsx:450`) — `computeBrokerValue` excluye la cripto de la rama `.BA` (`valuation.js:409`, comentario de diseño explícito) y lee la key pelada, que nunca se pidió. 0,1 BTC: correcto ≈ US$7.350; mobile muestra 5.250 (P&L 0). **Fix:** anteponer `!isCrypto(p.asset)` al ruteo `.BA`, espejo de la valuación (isCrypto ya está importado en ambos archivos).

#### M-4. Desktop `dvFor` no cubre costInPesos: Var. día "—" garantizado, o monto ×ratio si el ADR está priceado por otra posición
`frontend/src/pages/Positions.jsx:1017-1024` — `dvFor` omite `costInPesos(p)` en la condición del símbolo local mientras fetch (L450) y `calcUSDT` (L891) sí lo tratan como `.BA`. Con GGAL ADR en Schwab: `dv.amount = perUnit_ADR × nominales_locales` → **−40 USD mostrado vs −4 real (×10, el ratio)**, sumado al day-total del broker. **Fix:** agregar `|| costInPesos(p)` a `local` y convertir ÷tcCedear.

#### M-5. GET /api/snapshots: `days` es LIMIT de FILAS, no ventana de fechas
`backend/main.py:3467-3480` — Con huecos del cron (guard de cobertura + abort por blue), "Últimos 30 días" mobile abarca 40-60 días; desktop filtra por cutoff real → otra fuente de mobile≠desktop. Mismo patrón en Insights.jsx:227 y Positions.jsx:336. **Fix:** `WHERE date >= date('now', ?||' days')`, o como mínimo relabelear con el dayDiff real (patrón que el propio archivo ya usa en "P&L Nd").

#### M-6. Riel CCL: computeDailyPnl compara live-CCL contra snapshots que viven en MEP
`frontend/src/pages/HomeMobile.jsx:151-155` (también `Dashboard.jsx:509-514` y la curva L460) — Los snapshots son MEP por diseño (el POST del Dashboard hasta se auto-bloquea con riel≠mep) pero la **comparación** no tiene ese guard → brecha CCL/MEP como "P&L Día" permanente para users CCL, que desaparece al togglear. (Refutado en verificación: el banner de Positions es dead code y el delta 30d mobile no se contamina — es snapshot-vs-snapshot.) **Fix:** el liveValue de toda comparación contra snapshots siempre con cascada MEP fija; el riel gobierna solo display.

#### M-7. Cron con caché dólar frío: holdings valuados a config `tc_mep` (default 1415, sembrado al signup, nunca actualizado)
`backend/snapshots_job.py:122-131` — Post-restart sin tráfico en /api/dolar hasta las 23:59 ART, TODOS los holdings `.BA` de esa corrida van ÷1415 → snapshot −15,2% en un día plano + "P&L Día +17,9%" fantasma a la mañana; el detector de snapshots corruptos cae justo en su punto ciego. El path CCL SÍ fetchea directo con caché frío (`snapshots_job.py:361-363`) — el MEP nunca recibió el mismo tratamiento. **Fix:** fetch directo del MEP (o `fx_rates_daily`); sin MEP confiable, skipear el snapshot.

#### M-8. computeMonthlyReturns incluye el mes en curso (cf MtM vs ci costo) → CAGR del Dashboard y Sharpe/vol de Insights sobre distribución fabricada `[known-class C1]`
`frontend/src/utils/insightsMetrics.js:51-76` — returns = [0%×11, +80%] → CAGR "+80% anual" (real ≈ +34%), vol anualizada 80% para un buy-and-hold suave. `computeBestWorstMonth` ya excluye el mes actual con comentario explícito; esta función no. **Fix real:** derivar returns de snapshots EOM a mercado (excluir solo el mes actual dejaría 0% — también mal).

#### M-9. buildCumulativeReturnSeries inyecta liveValue como capital_final del último entry → spike en TWRR/drawdown de Insights `[known-class C1]`
`frontend/src/utils/insightsModel.js:88-148` — El último punto concentra todo el unrealized (−40% de "max drawdown" en un punto para un declive gradual). Verificación: el sub-claim "liveValue atribuido a un mes viejo" está **refutado** (rollover lazy garantiza la fila del mes), y la causa raíz ni siquiera es la inyección — sync-unrealized ya mete el lifetime en el cf del mes vivo. **Fix correcto = plan C1**, no el patch de calendario.

#### M-10. Movers MtM: comprar más de una posición existente = "Mejor activo"; trim = "Peor pérdida"
`backend/reporting/builder.py:468-477` — `v_end − v_start` por activo no descuenta trades del período (solo excluye posiciones NUEVAS). DCA de US$5.000 sobre AAPL con precio flat → "Mejor activo AAPL +US$5.000 (+100%)". El delta del MISMO card sí descuenta flujos — inconsistencia interna. **Fix:** ajustar por neto BUY−SELL per-asset, o excluir del ranking activos con trades (criterio conservador ya usado).

#### M-11. compute_live_portfolio_value sin retry / last-known / guard de cobertura → posiciones sin precio caen a costo en silencio y fabrican pérdida del período
`backend/snapshots_job.py:677-731` — El cron tiene las 3 defensas (con comentario explícito sobre "ganancia/pérdida fantasma"); el live de Reportes hace UN fetch y suma. yfinance flaky (la razón de ser del retry) → "P&L del día −US$2.000 (−10%)" fantasma, cacheado 60s. **Fix:** replicar las 3 defensas; si no alcanza cobertura, devolver None (el fallback al snapshot ya existe).

#### M-12. El backfill MtM (fix C1 planeado) es incompatible con el motor actual: se auto-deshace y mientras vive rompe los reportes `[known-class C1 — landmine, no bug activo]`
`backend/scripts/backfill_historical_mtm.py:262-288` vs `main.py:7037-7058` — Escribe solo `capital_final` → cada mes cerrado mostraría el unrealized ACUMULADO (+30% ×4 meses → año TWR +185% para +30% real), y la primera `_repair_monthly_chain` (18 call sites) lo revierte todo a costo en silencio (documentado en `main.py:10167-10175`). **Prerequisito del mass-fix C1:** backfillear también `capital_inicio` en cadena Y sellar meses MtM ante el repair.

---

### LOW

#### L-1. "Hoy en tu cartera": CEDEARs cotizados por el ticker US padre
`backend/main.py:20918-20927` — Assets crudos a `_fetch_batch_quotes` sin ruteo `.BA` → % del subyacente (en días de salto de brecha hasta invierte el signo) y context "US$2.412" cuando la unidad del user vale ~US$40. Bonos/FCI se caen en silencio. **Fix:** rutear por `position_price_key`/`fetch_ba_aware_prices` de analysis_prep (la SSoT existe justo para esto).

#### L-2. Precio actual stale (last-known fill) vs prev-close fresco → Var. día fantasma en ilíquidos
`backend/main.py:5753-5755` — `/api/prices` rellena con last-known sin marcar frescura; prev-close tiene fallback distinto (`fast_info`) que puede resolver fresco → el drift multi-día se muestra como movimiento de HOY (COIN.BA: −9,5% un día que no operó). **Fix:** exponer la fecha del last-known y skipear la Var. día cuando el actual no es del día.

#### L-3. Ventana de movers corrida un día vs las métricas del mismo card
`backend/reporting/builder.py:453-457` — El cron fecha el snapshot D con el cierre de D−1 (02:59 UTC); movers usa `period_start − 1` → cierre de DOS días antes. Un salto del 30-jun aparece como "Mejor activo" de JULIO mientras el delta del mes da 0. El corrimiento es sistemático y uniforme (solo el cron escribe holdings_json) → **fix seguro:** usar `at_or_before(period_start)`, mismo borde que las métricas.

---

## 4. Plan de fix sugerido

Orden pensado para matar los síntomas reportados primero, con el menor riesgo (display-only antes que datos persistidos, frontend antes que cron/backfill):

**Fase 1 — HomeMobile (1 archivo, display-only, mata lo más reportado):**
1. C-1/M-1: "P&L Mes" → `computeReturnDelta(sinceDate=1° del mes)`, igual desktop. Dos pájaros: fantasma 26× + staleness.
2. H-2: delta 30d flow-adjusted con `net_deposited`.
3. M-2: serie con `buildPortfolioValueSeries(..., liveValue)` → un solo "hoy" en la pantalla.
4. M-6: liveValue de comparaciones contra snapshots siempre en MEP (también en Dashboard monthlyVar/curva).

**Fase 2 — Unificar el fetch de símbolos (helper compartido, mata mobile≠desktop por-activo):**
Extraer UNA función `buildPriceSymbols(positions)` (la versión correcta ya existe en Positions.jsx:448-453 + exclusión cripto) y usarla en los 4 sitios: `Dashboard.jsx:137` (H-3), `PositionsMobile.jsx:395` (H-4), `HomeMobile.jsx:94` y `Positions.jsx:450` (M-3). En el mismo pass: lookup de prev-close en `PositionsMobile.jsx:614` (H-5) y `dvFor` desktop (M-4), y endurecer `hasPrice` del guard de snapshots para chequear la key de valuación. Esto además deja de escribir snapshots subvaluados.

**Fase 3 — Cron de snapshots (backend, corta el fantasma diario de raíz):**
1. H-1: cash ARS al MEP (mismo user_fx que holdings) en `take_snapshot_for_user`.
2. M-7: MEP directo con caché frío (copiar el patrón CCL de `snapshots_job.py:361-363`); sin MEP, skipear.
3. Resolver el doble-writer cron/POST del mismo día (una sola convención).
*Nota: los snapshots viejos quedan con sabor blue — el fantasma muere hacia adelante; evaluar si vale un repair de la serie.*

**Fase 4 — Reportes backend (quirúrgicos, independientes entre sí):**
1. H-7: netdep `include_baseline=True` para `_snapshot_delta` (espejo exacto del fix B5/B7 ya hecho).
2. C-3: heredar start del capital_final anterior cuando falta la fila del mes.
3. H-8: guard broker_filter en week/day (`delta_pct=None`).
4. H-9: tc_blue por cascada live.
5. C-2 (patch): start_value del período en curso desde snapshot MtM (`fetch_snapshot_at_or_before`), patrón `dw_incomplete` de fallback.
6. M-11: las 3 defensas del cron en `compute_live_portfolio_value`.

**Fase 5 — Frontend residual:**
H-6 (skipear la mutación del paso 9 en el mes vivo — 3 líneas), M-5 (days como ventana de fechas), M-8 (returns desde snapshots EOM), M-10, L-1/L-2/L-3.

**Fase 6 — C1 de raíz (el más riesgoso, al final):**
El plan C1 (sellar `capital_final` con MtM) **no se puede mass-aplicar tal cual**: primero M-12 (backfillear `capital_inicio` en cadena + enseñar a `_repair_monthly_chain` a respetar meses sellados), si no el backfill rompe los reportes mensuales primero y se auto-deshace después. Las fases 1-5 dejan las superficies visibles correctas sin depender de esto; C1 queda como fix estructural para que `monthly_entries` deje de ser una fuente mentirosa.

**Criterio de verificación post-fix:** mismo user, mismo instante → hero mobile = total Dashboard = "Hoy" de Reports (±PF rotulado); "P&L Mes" mobile = "Este mes" desktop; P&L Día ≈ 0 con mercado y FX quietos; un depósito no mueve ningún delta de período.