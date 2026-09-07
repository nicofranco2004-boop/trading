## Frontend — Análisis: Métricas, Comportamiento, Reportes, Perfil, Objetivos

Alcance: las pantallas del grupo "Análisis" del sidebar y todo lo que cuelga de
ellas. Todas las citas son contra `origin/main` @ `b74f450f`.

---

### Mapa de rutas (quién monta qué)

| URL | Componente | Nota |
|---|---|---|
| `/analisis` | `frontend/src/pages/Analisis.jsx` | wrapper de 3 tabs |
| `/analisis?tab=diagnostico` (default) | `Insights.jsx` con `_embeddedTab="diagnostico"` | `Analisis.jsx:123` |
| `/analisis?tab=comportamiento` | `Behavioral.jsx` | `Analisis.jsx:124` |
| `/analisis?tab=reportes` | `Reports.jsx` | `Analisis.jsx:125` |
| `/insights` | `<Navigate to="/analisis?tab=diagnostico">` | `App.jsx:206` |
| `/comportamiento` | `<Navigate to="/analisis?tab=comportamiento">` | `App.jsx:207` |
| `/reportes` | `<Navigate to="/analisis?tab=reportes">` | `App.jsx:208` |
| `/analisis?tab=perfil` | redirect a `/perfil-inversor` | `Analisis.jsx:48-50` |
| `/perfil-inversor` | `PerfilInversor.jsx` → `Insights.jsx` con `_embeddedTab="perfil"` | `PerfilInversor.jsx:24` |
| `/fundamentals` | `Fundamentals.jsx` ("Calidad de cartera") | `App.jsx:192` |
| `/objetivos` | redirect a `/posiciones?tab=objetivos` → `Goals.jsx` | `App.jsx:205`, `Cartera.jsx:145` |
| `/mensual` | `Monthly.jsx` → `MonthlySummary.jsx` | `App.jsx:209` — **huérfana** |
| `/wrapped` | `Wrapped.jsx` | `App.jsx:224` — **huérfana** |
| `/bienvenida` | `FirstInsight.jsx` | `App.jsx:231` (post-import) |
| `/i/:token` | `ReportPublic.jsx` | `App.jsx:199` (auth) y `App.jsx:294` (no-auth) |

**[V] Qué quedó huérfano.** El sidebar del grupo "Análisis" tiene exactamente 3
ítems: `/analisis` ("Métricas"), `/fundamentals` y `/perfil-inversor`
(`frontend/src/components/Sidebar.jsx:61-68`). No hay ningún link a `/wrapped`
ni a `/mensual` en toda la app: el único match fuera de `App.jsx` es el
prefetcher (`frontend/src/utils/routePrefetch.js:29` y `:36`) y el interceptor
del modo demo. `/mensual` importa a ese componente sin lector, y `MonthlySummary`
**escribe en la base al montar** (ver más abajo). `/wrapped` también quedó fuera
de `More.jsx` (el drawer de mobile).

**[V] Doble `<h1>` en las 3 tabs y en el Perfil.** `Analisis.jsx:83-87` monta un
`PageHeader` ("Métricas"), y cada hijo monta el suyo: `Insights.jsx:2704`
("Insights"), `Behavioral.jsx:148` ("Comportamiento"), `Reports.jsx:169`
("Performance histórica"). `PageHeader` renderiza un `<h1>`
(`frontend/src/components/PageHeader.jsx:31`). Lo mismo en `/perfil-inversor`:
`PerfilInversor.jsx:18-22` pone "Perfil de inversor" y el `Insights` embebido
agrega "Insights" con su `AnalyzeButton screen="insights"`
(`Insights.jsx:2704-2717`, fuera del guard `showDiagnostico` que arranca en
`:2725`).

---

## `/analisis` → `frontend/src/pages/Analisis.jsx` (129 líneas)

- **Qué muestra**: `PageHeader` + tira de 3 pills (Diagnóstico / Comportamiento /
  Reportes, `Analisis.jsx:32-36`) + el tab activo dentro de un `<Suspense>`
  (`:122-126`). Cada tab es un `lazy()` propio (`:25-27`).
- **De dónde saca los datos**: **ninguno**. No hace un solo `api.*`. Es puro
  ruteo/estado.
- **Estado/contexto**: `useSearchParams` / `useNavigate` / `useLocation`. No
  consume ningún context propio de Rendi.
- **Gating por plan**: ninguno acá; vive dentro de cada tab.
- **Variante mobile**: no hay. Las mismas 3 pills.
- **Rarezas**:
  - `[V]` Tres `useEffect` que sincronizan `?tab=` ↔ state (`:48`, `:59`, `:72`),
    los tres con `eslint-disable react-hooks/exhaustive-deps`. El de `:59`
    dispara `track('analisis_tab_viewed')` en cada cambio de `tab`, incluido el
    montaje inicial.
  - `[V]` El comentario de cabecera (`:9-17`) todavía describe una pestaña
    "Métricas Pro" y una de "Perfil" que ya no existen; el de `:115-119` dice
    que "Comportamiento y el detalle de Reportes todavía no [respetan la
    moneda]: sus cifras llegan formateadas en USD desde el backend" — verificado
    como cierto para Comportamiento, y **parcialmente falso** para Reportes (ver
    la sección de Reportes: hoy hay dos convenciones conviviendo en la misma
    pantalla).

---

## `/analisis?tab=diagnostico` → `frontend/src/pages/Insights.jsx` (4783 líneas)

Es la pantalla más grande del repo. `Insights` (`:152`) es un shim que delega en
`InsightsDesktop` (`:168`); no hay componente mobile separado.

### Qué muestra (secciones, en orden de render)

Todo el bloque va envuelto en `{showDiagnostico && (<>…</>)}` (`:2725`…`:3503`).

| # | Sección | Línea |
|---|---|---|
| 0 | `InsightDelDiaHero` — solo mobile | `:2728` |
| 1 | Banner "Cargando cotizaciones de mercado" (faltan precios) | `:2730-2737` |
| 2 | Banner "Esperá unos días" (`monthly.length < 2`) | `:2739-2746` |
| 3 | "Desde tu última visita" (`DeltaSinceVisit`) | `:2748-2759` |
| 4 | "Tu lectura personalizada (IA)" (`DiagnosticoSummaryBlock`) | `:2762` |
| 5 | Veredicto AR (`ArAlternativesVerdict`) — puede ir antes o después del KPI | `:2765` / `:2849` |
| 6 | `InsightsKpiStrip` (5 celdas) | `:2768-2844` |
| 7 | `DiagnosisSection` — 1 destacado + grilla 3×3 | `:2858-2860` |
| 8 | "Distribución de activos" (`CompositionByAsset`) + chip de cash % | `:2865-2875` |
| 9 | 2 donas: por tipo de activo y por sector (`CompositionDonut`) | `:2882-2940` |
| 10 | Alertas críticas (`level==='danger'`) | `:2943-2951` |
| 11 | Sección **Performance**: chart cartera vs benchmark | `:2957-3337` |
| 12 | "Reconstrucción contable" (banda gris, solo USD) | `:3339-3378` |
| 13 | "Curva de drawdown" | `:3383-3442` |
| 14 | "Atribución del crecimiento" (`PerformanceAttribution`) | `:3445-3452` |
| 15 | "Atribución por activo" (`#atribucion`) | `:3457-3468` |
| 16 | "Distribución por broker" (torta, solo con ≥2 brokers) | `:3472-3497` |
| 17 | **Perfil de inversor** (`showPerfil`) | `:3516-3538` |

### De dónde saca los datos

Todo por `api.*`; ningún endpoint se comparte con otras pantallas vía cache.

| Endpoint | Línea | Notas |
|---|---|---|
| `GET /monthly` | `:358` | la cadena contable (`monthly_entries`) |
| `GET /positions` | `:359` | |
| `GET /brokers` | `:360` | |
| `GET /benchmarks` | `:361` | `sp500`, `shv`, `gld`, `merval`, `uva`, `inflation_ar`, `dolar_blue` |
| `GET /snapshots?days=3650` | `:365` | 10 años de fotos diarias, en un solo request |
| `GET /dolar` | `:366` | |
| `GET /operations` | `:367` | |
| `GET /insights/commissions` | `:368` | |
| `GET /auth/investor-profile` | `:369` | |
| `GET /insights/performance[?moneda=ars]` | `:370` | **primer fetch** |
| `GET /prices?symbols=…` | `:387` | segunda ola, después de resolver símbolos |
| `GET /insights/performance?bench=…&modo=…&valor_live=…[&moneda=ars]` | `:349` | efecto separado |
| `GET /ai/usage` | `:3806` | solo Free, dentro de `DiagnosisSection` |
| `POST /diagnostics/dismiss` | `:3859` | "No me interesa" (cuota Free) |
| `POST /ai/analyze` | vía `useAIAnalysis`/`AskAIAbout`/`AnalyzeButton` | topics: `insights` (botón del header, `:2711`), `insights.summary`, `insights.evolution` (`:2966`), `insights.drawdown` (`:3385`), `insights.attribution` (`:3447`), `insights.observation` (`:4060`), `portfolio.distribution_type` (`:2885`), `portfolio.distribution_sector` (`:2912`), `profile.summary`, `profile.card` |
| `GET /behavioral/insights` | `frontend/src/components/mobile/InsightDelDiaHero.jsx:36` | solo mobile |

**[V] `/insights/performance` se pide 2–3 veces por carga.** `loadAll()` lo pide
sin `bench` ni `modo` (`:370`) y, en paralelo, el efecto de `:339` lo pide con
`bench`/`modo`. Ese efecto depende de `liveKeyPerf` (`:335`), que arranca en `0`
mientras `loading` es true y salta al valor real cuando terminan de llegar
precios → tercera llamada. Las tres escriben el mismo `perfRaw`.

### ⚠️ Cálculos hechos en el cliente

Esta pantalla es, con diferencia, la que más matemática financiera hace en el
browser. Lo que sigue **no viene del backend**:

**Valuación por tenencia — `holdingValueUsd(p)` (`:421-464`).** Reimplementa en
el frontend la cascada de valuación (rama broker-ARS, rama costo-en-USD, rama
CEDEAR/`.BA` ÷ MEP, rama cripto con `cryptoBrokerFactor`, clamp `trustMktValue`).
Alimenta `assetPieData` (`:466`), `positionsWithValue` (`:495`), `aiPositions`
(`:2010`) y por lo tanto la concentración, la atribución y el snapshot que se le
manda a la IA.

**Totales del hero.**
- `totalPortfolio = Σ computeBrokerValue(...).value` (`:410-413`)
- `totalCostBasis = Σ computeBrokerValue(...).invested` (`:525-527`)
- `unrealizedPnl = totalPortfolio − totalCostBasis` (`:528`)
- `capitalContributed = netCapitalContributed(globalMonthly)` (`:550`)
- `realizedPnl = Σ m.pnl_realized` (`:552`)
- `totalResult = totalPortfolio − capitalContributed` (`:554`)
- `totalResultPct = totalResult / capitalContributed × 100` (`:555`)

**Serie mensual re-anclada — `applyMtmToMonthly` (`:535-545`).** La cadena
contable de `monthly_entries` se corrige contra los snapshots y el mes en curso
se cierra con `totalPortfolio` (valor de mercado). De esa `globalMonthly` cuelga
*todo* lo mensual de abajo.

**TWR mensual Modified Dietz en JS (`:657-717`)**, con heurísticas:
```
isImportInitial = isFirst && ci===0 && net>0
flowRatio       = |net| / ci
isBigWithdraw   = net<0 && flowRatio>0.3
avgCap = isImportInitial ? net : (isBigWithdraw ? ci : ci + 0.5·net)
r      = max((cf − ci − net)/avgCap, −0.99)      // sin techo, piso −99%
cumIdx *= (1+r)
```
y un denominador "estable" para el realizado (`safeDenom`, `:654-655`):
`net ≥ 0.6·peak && net > 1000 ? net : peak`.
Punto "Hoy": `rLive = (totalPortfolio − lastCf)/lastCf` (`:724`).

**Versión ARS de lo mismo (`:697-716`, `:917-1023`)**, con el FX del mes anterior
para que la devaluación no se cancele (`monthlyReturnArs`, `insightsModel.js:551`).
El "Hoy" en pesos usa `dolar_blue` en las dos puntas a propósito (`:1004-1006`).

**Retorno mensual del inflación/benchmark en el browser** — `buildInflationCumPct`
(`:1591-1630`): `cum = Π(1 + ipc_m/100)` mes a mes sobre el rango completo del
usuario, incluso los meses que el usuario no cargó.

**Shadow del benchmark (`buildShadowFromSim` `:1484-1502`, versión ARS
`buildShadowFromSimArs` `:1510-1580`)**: `pct[k] = (price[k]/price[first] − 1)·100`,
y para los benchmarks ARS-nativos (Merval / plazo fijo / pesos cash) un método
flow-matched con clamp `[-99, 200]` (`:1568`, `:1578`) — el código lo marca como
`TODO: portarlos a índice simple` (`:1548`).

**Rebase de la ventana (`:1724-1735`)**: `rebased = ((100+cur)/(100+base) − 1)·100`
para las 3 líneas, con el ancla del benchmark tomada de la **primera fila con
dato**, no de la primera fila (`:1721-1722`).

**Métricas de trader (todas en JS):**
- filtro de trades: `isTradeOp` excluye Dividendo/Interés/Compra/Conversión (`:1881-1887`)
- micro-trades: se descartan los de `|pnl_usd| < 1.5` (`:1896-1898`)
- win rate + avgWin/avgLoss/ratio (`:1907-1923`)
- profit factor (`computeProfitFactor`, `:1924`)
- hold time promedio en días entre `entry_date` y `date` (`:1927-1946`)
- concentración top-3 con clamp a 100% (`:1970-1981`)
- `discipline` = aportes netos vs P&L, con `pnlShare = pnl/|total|·100` (`:1815-1834`)
- `gainConcentration` = share del top contribuidor sobre las ganancias (`:2094-2106`)
- `cashRatio = cashUsd/totalPortfolio·100` (`:1838-1846`)
- `snapChart` / `dailyVariation` sobre los últimos 7 snapshots (`:1987-2004`)

**Métricas "Pro" (Sharpe, Sortino, Vol, Alpha, Beta, IR, CAGR, Calmar)** —
`computeProMetrics(globalMonthly, bench, drawdown?.max)` (`:2181`), implementadas
en `frontend/src/utils/insightsMetrics.js`:
- retornos mensuales Modified Dietz con `denom = start + 0.5·netFlow` y descarte
  de meses con `start ≤ 100` o `|ret| > 3` (`insightsMetrics.js:51-76`)
- `σ_anual = stdev_muestral × √12` (`:86-94`)
- `downsideDev = √(Σ min(r−rf,0)²/n) × √12` (`:129`)
- `CAGR = (1+totalGrowth)^(12/span) − 1`, donde `span` son los meses
  **transcurridos** entre la primera y la última clave conservada (`:411-415`)
- `rf` derivada de SHV, con clamp `[0, 30%]` y fallback (`:150-166`)
- Alpha/Beta/IR contra S&P sólo con ≥6 meses (`:503-508`)

**[I] Divergencia latente:** `computeProMetrics` corre sobre `globalMonthly`
(cadena contable re-anclada), mientras que el gráfico y el KPI de Performance
corren sobre `perf.curva` (motor del backend). El Calmar (`:511`) mezcla las dos:
CAGR del frontend ÷ drawdown del backend. Me apoyo en que `drawdownMaxPct` entra
por parámetro desde `Insights.jsx:2181` con `drawdown?.max`, que sale de
`drawdownFromPerf(perf)` (`:1796`).

**Benchmarks "Comparativa" (`:2166-2197`)**: `simulateSp500/Shv/Gold/DolarCash/
Merval/PlazoFijoUva/ArsCash` corren en el browser sobre `globalMonthly`
(`frontend/src/utils/benchmarkSim.js:76-110`: se compran "unidades" del índice al
precio del mes con los flujos reales). El delta contra el usuario es
`compareToMine` (`:2185-2190`): `(totalPortfolio − benchFinal)/benchFinal·100`.
Esos valores alimentan **el veredicto AR** (`verdictItems`, `:2578-2604`) y los
diagnósticos `vsSp500`/`vsArs`.

**Conversión de moneda del display — `amt()` (`:2516-2525`)**: multiplica el USD
por `tcValuacion` **de hoy** cuando `currency==='ARS'`. Se usa en las dos donas
(`:2893`, `:2920`), en la atribución (`:3450`, `:3464-3465`) y en el tooltip de
la torta por broker (`:3491`). O sea: en modo Pesos esos montos son
"USD × dólar de hoy", no pesos históricos.

### El benchmark contra S&P / inflación — dónde se arma la serie

Es un híbrido y el detalle importa:

- `[V]` **La línea del portfolio** sale de `perf.curva` (backend) vía
  `benchSeriesUsd` (`:828-905`). El motor viejo en JS quedó como **respaldo**:
  `benchSeriesArs` (`:917-1023`) sólo se usa si `currency !== 'USD'` **y** el
  backend no devolvió curva (`usaPerfEnPesos`, `:1240-1241`). El comentario dice
  que eso son 196 de 758 usuarios con broker en pesos (`:1236-1237`).
- `[V]` **La línea del benchmark**: en USD (y en ARS cuando `usaPerfEnPesos`)
  sale del backend, **por fecha**, alineada por posición con la curva
  (`:864-870` la lee, `:1695-1696` la usa: `benchPct = (s.bench − 1)·100`). El
  comentario mide el bug que eso vino a arreglar: "con el shadow mensual la
  línea del S&P tenía 2 valores distintos sobre 44 filas y en 21 usuarios el
  signo dado vuelta" (`:1690-1694`).
- `[V]` **El shadow mensual del frontend sigue vivo** para: (a) ARS con el motor
  viejo, (b) el "esqueleto" cuando no hay línea de usuario (`:1697-1709`). Ahí el
  anclaje es **mensual** (`monthKeyOf(key) = key.slice(0,7)`, `:1433`) con
  fallback al último mes `≤ mk` (`:1704-1708`), y el punto del mes es el
  **último punto del mes** (`:1360-1366`).
- `[V]` **La inflación** siempre se compone en el frontend
  (`buildInflationCumPct`, `:1591-1630`) — no hay rama que la traiga del backend.
- `[V]` **La comparativa de las cards / el veredicto** (`vsSp500`, `vsPlazoFijo`,
  `vsDolar`) **siempre** se calcula en el browser, flow-matched, sobre
  `globalMonthly`. Es decir: en la misma pantalla el S&P del gráfico viene del
  backend y el S&P del diagnóstico `underperform_benchmark` viene de otro motor.

### El modo "Certero" vs "Estimado"

- `[V]` **Quién lo determina**: el usuario, con el toggle de `:3002-3041`
  (`modoPerf`, `useState('certero')` en `:294`). Viaja al backend como
  `&modo=` (`:349`). El backend responde con `base_del_twr`; `_perfContable =
  perf?.base_del_twr === 'contable'` (`:290`) es lo que gobierna la UI.
- `[V]` **Umbral / gate**: `togglePerfDeshabilitado = currency !== 'USD' &&
  !(perf?.curva || []).length` (`:304`). En pesos el toggle **se dibuja pero
  queda apagado** si el motor no devolvió curva; el motivo va en el `title`
  (`MOTIVO_TOGGLE_ARS`, `:134-135`).
- `[V]` **Qué cambia el usuario al cambiar de modo**:
  - el rótulo de la serie: `claveCartera` pasa de `"<Nombre> P/L total"` a
    `"<Nombre> P/L vendido"` (`:1429-1431`)
  - desaparece la segunda línea (P/L realizado) porque sería un sinónimo
    (`:3329-3331`)
  - el chip pasa a "Recreado de tu contabilidad · desde <fecha> · …" (`:1057-1097`)
  - **la card de drawdown se oculta entera**: `showDrawdown = slots.includes
    ('drawdown') && perf?.base_del_twr !== 'contable'` (`:2689-2690`)
  - el KPI acumulado se lee distinto: en estimado por `acumuladoPublicado(...,
    {contable:true})` con fallback a `acumuladoDeVentana` (`:2793-2799`); en
    certero por `acumuladoPublicado` a secas (`:2809-2810`), y en ARS-con-motor-
    viejo cae a `lastRow[_kTotal]` (`:2813`).
  - `InsightsKpiStrip` recibe `acumuladoEstimado` y agrega " · recreado" al
    label (`InsightsKpiStrip.jsx:122`).
- `[V]` **La parte no medida se dibuja punteada** en su propia clave
  (`partirMedidoYEstimado`, `:1766-1767`) y la línea se **corta** donde cambia el
  `segmento` (`cortarPorTramo`, `:1417`), no donde cambia el `tramo`.
- `[V]` **Resolución del eje**: `resolucionDeSerie` mira sólo los puntos que NO
  son `base === 'costo'` (`:1332-1338`), y si no hay ninguno medido no filtra
  (guarda explícita, `:1323-1331`). Umbral: `insightsModel.js:926-933`.

### Estado / contexto que consume

- `useAuth()` (`:170`) — `user.name` para el rótulo de la serie (`:190-194`),
  `user.email` como clave de `useLastVisit` (`:181`) y de `DiagnosisSection`
  (`:2859`).
- `useCurrency()` (`:171`) — `valuationDollar`, `currency`, `costBasis`.
- `usePlanFeatures()` (`:172`) — sólo `plan.isFree`, que entra a
  `selectDiagnostics` (`:2344`) y a `DiagnosisSection` (`:2859`).
- `usePfRollup()` (`:178`) — plazos fijos, para que las donas sumen el mismo
  patrimonio que el Dashboard.
- `useLastVisit()` (`:181`) — localStorage `rendi_lastvisit_diagnostico:<email>`.
- `useIsMobile()` (`:169`).
- **No consume** `AdvisorContext`, `AlertsContext`, `PrivacyContext`,
  `ThemeContext` ni `CoachDrawerContext`.

### Gating por plan

- `[V]` **La grilla 3×3 la ven todos los tiers.** El comentario de
  `:3814-3816` lo dice explícitamente: "antes era Pro/Admin only".
  Consecuencia: el límite `insights_diagnostic_visible` que el backend sigue
  publicando (`backend/ai/plan.py:48`, `:68`) **ya no lo lee nadie en el
  frontend** — sólo aparece en `frontend/src/utils/demo.js` y en el comentario
  de `frontend/src/hooks/usePlanFeatures.js:11`.
- `[V]` **Lo que sí se le oculta a Free**: las 6 métricas de riesgo marcadas
  `premium` en `frontend/src/utils/diagnostics.js` (Sharpe `:874`, Sortino
  `:888`, Beta `:900`, Alpha `:917`, Information Ratio `:931`, Calmar `:943`).
  `selectDiagnostics` les pone `locked=true` y **reemplaza el texto por el
  `lockedLabel`** (`diagnostics.js:982-987`), y `DiagnosisCard` dibuja el teaser
  con badge "Métrica · Plus" y link a `/planes` (`Insights.jsx:4025-4049`).
  CAGR (`:845`) y Volatilidad (`:858`) **no** son premium.
- `[V]` **Cuota del "No me interesa"**: Free tiene cuota semanal server-side.
  El flujo está en `:3853-3879`: `POST /diagnostics/dismiss` → 200 rota; 429 con
  `detail.error === 'diag_dismiss_quota_exceeded'` abre `UpgradeModal` y **no**
  rota; 429 sin ese payload no rota ni abre modal; error de red → **fail-open**,
  rota igual. Guard anti doble-click con `inflightRef` (`:3799`, `:3856`).
  El contador se muestra con `GET /ai/usage` (`:3806`) y sólo si hay algún tier
  rotable (`:3920`).
- `[I]` El botón "No me interesa" sólo aparece cuando el tier tiene **más de 3**
  candidatos (`canRotate: pool.length > 3`, `:3889`) — o sea, un usuario con
  pocos hallazgos no ve el gancho de conversión aunque sea Free.

### Variante mobile

- `[V]` **No hay una implementación separada.** La única diferencia es
  `{isMobile && <InsightDelDiaHero />}` (`:2728`), que agrega un **fetch extra**
  a `GET /behavioral/insights` (`InsightDelDiaHero.jsx:36`). Ese mismo endpoint
  lo vuelve a pedir `Behavioral.jsx:114` al cambiar de tab: no hay cache
  compartido.
- `[V]` **El comentario miente**: `:153-156` dice "en mobile … ocultamos la curva
  de drawdown (decisión del producto: demasiado denso para mobile)". `isMobile`
  aparece dos veces en el archivo (`:169` y `:2728`) y no toca el drawdown.

### Rarezas de `Insights.jsx`

- `[V]` **~700 líneas de código muerto.** Estas funciones están definidas y
  **nadie las llama** (verificado: una sola ocurrencia del identificador en todo
  el archivo, la de su propia definición):
  `BenchmarkCard` (`:3545-3574`), `InflationCard` (`:3576-3599`),
  `AccordionSection` (`:4245-4289`), y toda la familia de cards del perfil que
  fue reemplazada por `ProfileDashboard`: `ProfileAllocationCard` (`:4293`),
  `ProfileObjectiveCard` (`:4354`), `ProfileReturnExpectationCard` (`:4410`),
  `ProfileHorizonCard` (`:4450`), `ProfileDrawdownCard` (`:4504`),
  `ProfileConcentrationCard` (`:4559`), `ProfileStyleCard` (`:4621`),
  `ProfileLiquidityCard` (`:4672`) y sus dos helpers `InsightCard` (`:4143`) y
  `AllocationRow` (`:4746`). `ProfileInvestorBlock` (`:4168`) ya delega en
  `<ProfileDashboard>` (`:4210`).
- `[V]` **Imports sin usar** (arrastrados por ese código muerto):
  `StatCard` (`:10`), `CollapsibleSection` (`:25`), `usd` / `fmtArs` /
  `pctSigned` / `colorClass` de `utils/format` (`:28`), `lookupHistoricalDolar`
  (`:43`), `buildDrawdownTimeSeries` (`:60`), y los íconos `Trophy`,
  `Stethoscope`, `BarChart3`, `PiggyBank`, `Wallet`, `CircleDollarSign`,
  `Building2`, `BarChart2` (`:9`) y `LineChart` (`:5`). También el helper local
  `monthName` (`:98`).
- `[V]` **El motor de layout adaptativo se usa a un 25%.**
  `buildDiagnosticoLayout` (`frontend/src/utils/diagnosticoTemplate.js`) calcula
  12 slots ordenados y con visibilidad. `Insights.jsx` sólo consulta
  `slots.includes('verdict')` (`:2670`), la posición relativa de `verdict` vs
  `kpi` (`:2672`) y `slots.includes('drawdown')` (`:2689`). Los otros 9
  (`data_integrity`, `delta`, `ai_reading`, `featured`, `diagnosis`,
  `attribution`, `composition`, `benchmark`, `checklist`) se computan y se
  tiran: el JSX está en orden fijo. **`checklist` no tiene renderer en ningún
  lado** (`diagnosticoTemplate.js:61`, sin consumidor).
- `[V]` `aiSnapshot.summary.pnl_total_usd` y `pnl_total_pct` reciben **el mismo
  valor** — el % acumulado de `seriesUsd` (`:2446-2447`). El campo que dice
  "usd" lleva un porcentaje.
- `[V]` `topAsset` (`:1857-1874`) se calcula sumando `op.pnl_usd` por activo y el
  propio comentario (`:1854-1856`) explica que el `pct` no se computa porque
  mezclaría monedas — pero el valor sí se publica en el snapshot para la IA
  (`:2460-2461`).
- `[V]` El early-return de "sin posiciones" (`:2540-2564`) devuelve un
  `PageHeader` "Insights" propio. En `/perfil-inversor` eso da **tres** bloques
  de título encima del empty state.
- `[V]` `NOTA` de código borrado a mano en `:2527-2534` (la variable `aiSuggested`
  y su advertencia sobre `_FREE_QUESTIONS_WHITELIST`).
- `[V]` `positionsWithValue` (`:495-508`), `assetPieData` (`:466`), `chartData`
  (`:1432`), `benchSeriesUsd` (`:828`) y compañía **no están memoizados**: son
  IIFE que se recalculan en cada render del componente (que re-renderiza con
  cada `setPerf`, cada cambio de moneda y cada `setState` de los hijos que
  vivan arriba). El único `useMemo` del archivo es `liveUsdPerf` (`:323`).
- `[V]` El chart usa colores **hardcodeados** en hex para grid/ejes/tooltip
  (`#1B2230`, `#7C8698`, `#10151F`, `:3277`, `:3291-3296`), no tokens de tema.

---

## `/analisis?tab=comportamiento` → `frontend/src/pages/Behavioral.jsx` (860 líneas)

- **Qué muestra**: `PageHeader` + `AnalyzeButton screen="behavioral"` (`:153`) +
  KPI strip de 5 celdas (detectados / alta / media / sanos / detectores,
  `:161-167`) + grilla de 12 cards de sesgo + footer educativo (`:213-217`) +
  modal de detalle (`BehavioralModal`, `:300`) con evidencia, muestras y botón
  de compartir (`ShareCardModal`).
- **De dónde saca los datos**: **un solo** `GET /behavioral/insights` (`:114`).
  Todo lo demás sale de esa respuesta (`data.summary`, `data.cards`). El
  frontend no calcula ningún número financiero acá — el mapeo `code → ícono +
  copy educativo` está en `CARD_META` (`:35-88`) y los tonos en `SEVERITY_TONE`
  (`:90-96`).
- **⚠️ Cálculos en el cliente**: prácticamente ninguno. Lo único derivado es
  `allInsufficient = cards.every(c => c.insufficient_data)` (`:144`) y el
  formato de las muestras (`SamplesPanel`, `:842-860`).
- **Estado/contexto**: `usePlanFeatures()` (`:661`) y nada más. **No consume
  `CurrencyContext`.**
- **Gating por plan** (`BehavioralCards`, `:660-732`):
  - `hasFullAccess` (Pro/Admin) → las 12 cards con su análisis.
  - Free/Plus → `limit('behavioral_tags_visible') || 1` visibles (`:686`) y el
    resto como *preview educativo* (`BehavioralCardLockedPreview`, `:763`) que
    muestra QUÉ detecta el sesgo sin exponer el dato del usuario, con badge
    Plus/Pro según `absoluteIdx < PLUS_VISIBLE_COUNT` (`:693`, `:715`).
  - **Fail-closed durante el loading** (`:663-666`): mientras el plan carga se
    muestra la versión gateada.
  - `[V]` `PLUS_VISIBLE_COUNT = 6` está **hardcodeado en el frontend** (`:693`) y
    tiene que coincidir a mano con `backend/ai/plan.py` (Plus:
    `behavioral_tags_visible: 6`, `plan.py:69`). El propio comentario lo admite
    (`:690-692`).
  - CTA final `LockedCtaFooter` (`:814-840`) que navega a `/planes` y trackea
    `feature_blocked_clicked`.
- **Variante mobile**: no hay. La grilla pasa de `md:grid-cols-2` a una columna.
- **Rarezas**:
  - `[V]` **Moneda ignorada por completo.** Los montos se pintan con `$` pelado y
    `toLocaleString('es-AR')` (`:853`), y el endpoint no acepta parámetro de
    moneda (`backend/main.py:13760-13761`). Con el selector global en Pesos, esta
    pantalla sigue mostrando dólares sin decirlo.
  - `[V]` `LockedSection` se importa (`:27`) y **nunca se usa**.
  - `[V]` `Panel` (`:19`) tampoco: sólo aparece en el import.

---

## `/analisis?tab=reportes` → `frontend/src/pages/Reports.jsx` (913 líneas)

- **Qué muestra**:
  1. `PageHeader` con `AnalyzeButton screen="reports"`, `ExportCsvButton
     resource="monthly"`, `ModoRendimiento` y `BrokerSelector` (`:169-184`).
  2. `PerformanceCalendar` — KPI strip 12M + heatmap anual (`:219`).
  3. Tabs Día / Semana / Mes / Año (`PeriodTabs`, `:306-326`).
  4. Tab **Mes** → `MonthDisclosure` (período en curso + "Ver más meses" del
     mismo año, `:365-410`). Otros tabs → `CurrentPeriodView` (`:239-244`).
  5. `CurrentPeriodView`: hero de 3-4 KPIs, narrativa, dos columnas
     Trading/Cartera, y un "Ver detalle técnico" colapsado que abre `MonthCard`
     (`:747-887`).
- **De dónde saca los datos**:
  - `GET /reports/timeline?broker=…&months=12&modo=…&moneda=…` — vía
    `useReportsTimeline` (`frontend/src/hooks/useReportsTimeline.js:34-35`),
    llamado en `Reports.jsx:156`.
  - `GET /reports/period/{day|week|year}/{key}?broker=…&modo=…&moneda=…`
    (`Reports.jsx:115-124`).
  - `GET /brokers` (`frontend/src/components/reports/BrokerSelector.jsx:31`).
  - `POST /ai/analyze` con topics `monthly` y `monthly.insight`
    (`components/reports/MonthCard.jsx:102`, `:154`).
- **⚠️ Cálculos hechos en el cliente**:
  - `[V]` **Retorno anual del heatmap**: producto geométrico de los `delta_pct`
    mensuales, en el browser —
    `frontend/src/components/reports/PerformanceCalendar.jsx:156-160`:
    `(Π(1 + delta_pct/100) − 1)·100`, saltando meses `!is_relevant`.
  - `[V]` **KPI strip 12M**: `realizedSum = Σ realized_pnl`, `trades = Σ
    trades_count`, `positiveCount` (`PerformanceCalendar.jsx:63-65`) sobre los
    **12 meses relevantes más recientes** (`:59-60`).
  - `[V]` **"Retorno sobre aportes"** del tab Año:
    `((capitalNow − cum_deposited)/cum_deposited)·100` (`Reports.jsx:602`),
    suprimido cuando `basis_incomparable` (`:601`).
  - `[V]` `isFlat` (`:524-528`) y la polaridad del color cuando falta el %
    (`isPos`, `:512`) se deciden en el browser.
  - `[V]` `isoWeekKey` / `addWeeks` / `addMonths` (`:35-76`) reimplementan la
    aritmética ISO del backend. De esos helpers, **cinco están muertos**: sólo
    se usa `todayIso` (`:116`) e `isoWeekKey` (`:115`). `monthKey` (`:45`),
    `yearKey` (`:49`), `addDays` (`:53`), `addWeeks` (`:59`) y `addMonths`
    (`:70`) no los llama nadie.
- **Estado/contexto**: `useCurrency()` para derivar `moneda` (`:153-154`),
  `usePlanFeatures()` (`:159`). `MonthCard`/`WeekCard`/`PerformanceCalendar`/
  `InsightEvidence` usan además `useMoneyFormat()`.
- **Gating por plan**:
  - `plan.can('reportes.historicos')` (`:221`). Si es false → `ReportsFreeTeaser`
    (`:258-295`): el **último** mes expandido + `LockedSection.Placeholder` con
    "Tenés N meses más en tu historial" (`:286-291`). Free **no ve las tabs**
    Día/Semana/Mes/Año.
  - `ExportCsvButton` tiene su propio gate interno.
  - Backend: `"reportes.historicos"` está en `backend/ai/plan.py:36` y en `:56`
    para Free.
- **Variante mobile**: no hay implementación separada; el hero pasa de
  `md:grid-cols-4` a `grid-cols-2` y varias columnas se ocultan con
  `hidden sm:inline` / `hidden md:inline` (`:442`, `:460`).

### 🔴 Bug de Rules of Hooks en `CurrentPeriodView`

`[V]` `CurrentPeriodView` (`Reports.jsx:484`) tiene **dos early-returns antes de
su único hook**:

```
484  function CurrentPeriodView({ period, loading, tab, broker = 'global' }) {
485    if (loading) { …return… }        // ← 0 hooks
493    if (!period) { …return… }        // ← 0 hooks
501    const [showTech, setShowTech] = useState(false)   // ← hook #1
```

Secuencia que lo dispara (usuario Plus/Pro, tab Mes → Día/Semana/Año):
1. Render con `tab='day'`: `items` todavía tiene los meses viejos y
   `loadingItems===false` (`usePeriodItems` arranca en `false`, `:89`), así que
   el componente monta y **llama al `useState`**.
2. El efecto de `usePeriodItems` (`:92-141`) corre: `setItems([])` (`:100`) y
   `setLoading(true)` (`:120`, síncrono antes del `await`).
3. Siguiente render: `loading===true` → sale por `:485` con **0 hooks**.

React 18 (`frontend/package.json:15`) lanza *"Rendered fewer hooks than
expected"* en la fase de render. Lo atrapa el `ErrorBoundary` de
`frontend/src/main.jsx:89`, que envuelve **toda** la app → la pantalla entera se
cae, no sólo el card. En el tab Mes no pasa porque `MonthDisclosure` siempre
pasa `loading={false}` (`:394`).

No hay ningún test de esta página (no existe `frontend/src/pages/*.test.*`).

### 🔴 Dos convenciones de moneda conviviendo en la misma pantalla

`[V]` `Reports.jsx` manda `moneda` al backend (`:154`, `:124`,
`useReportsTimeline.js:35`), pero **el backend sólo convierte el porcentaje**:
en `backend/reporting/builder.py` la rama ARS pisa `delta_pct` (`:1488-1500`)
mientras `delta_usd = end_value − start_value − flows` (`:1468`) y
`start_value`/`end_value`/`realized_pnl`/`deposits` (`:1652-1658`) se quedan en
dólares.

Del lado del frontend hay dos tratamientos distintos para esos mismos campos:

| Componente | Qué hace con el monto |
|---|---|
| `Reports.jsx` (hero, KVRow, PeriodRow) | lo imprime crudo con prefijo **`US$` hardcodeado** — 21 ocurrencias, p.ej. `:541`, `:553`, `:563`, `:634`, `:714`, `:770`, `:841` |
| `MonthCard` / `WeekCard` / `PerformanceCalendar` / `InsightEvidence` | lo pasa por `useMoneyFormat().fmtMoney`, que **multiplica por `tcValuacion` de hoy** cuando `currency==='ARS'` (`frontend/src/contexts/CurrencyContext.jsx:308-315`) |

Resultado con el selector global en Pesos: el hero dice `US$ 1.234` y el
"Detalle técnico" que se abre justo debajo (`Reports.jsx:882` →
`MonthCard.jsx:207` → `MetricsGrid`) dice `$1.745.000` para el mismo campo. Y el
`%` grande del período ya viene medido en pesos (incluye devaluación) al lado de
un monto que sigue en dólares (`:766-771`).

### Otras rarezas de Reportes

- `[V]` `PerformanceCalendar.computeKpis` calcula `best` y `worst` y los devuelve
  (`:67-73`) pero el strip sólo dibuja 3 celdas (`:107-127`): código muerto. El
  comentario de cabecera (`:4`) todavía promete "mejor/peor".
- `[V]` `PeriodList` sólo se usa desde `MonthDisclosure` (`:404`).
- `[V]` `usePeriodItems` (`:87`) para los tabs no-mes pide **un solo período** (el
  actual), aunque el comentario de `:84-85` diga "últimos 7 días" / "años
  visibles".
- `[V]` El aviso "Vista filtrada por broker" (`:786-791`) es correcto pero el
  `sub` de "Posiciones" cuenta *todos* los brokers del usuario a propósito
  (`:615-622`).
- `[V]` `Fragment` se importa (`:12`) y no se usa.
- `[V]` `LABELS` (`:299`) se lee desde el render de `Reports` (`:177`), 122
  líneas antes de su declaración. Funciona porque el módulo ya está evaluado
  cuando corre el render, pero es frágil de leer.

---

## `/perfil-inversor` → `frontend/src/pages/PerfilInversor.jsx` (28 líneas)

- **Qué muestra**: su propio `PageHeader` + `<Insights _embeddedTab="perfil" />`
  dentro de un `Suspense` (`:23-25`).
- **De dónde saca los datos**: `[V]` **monta el `Insights` completo**. Aunque
  sólo renderiza la sección "Perfil de inversor" (`Insights.jsx:3516-3538`),
  `loadAll()` se ejecuta igual: los 10 endpoints de `:357-371` + `/prices`
  (`:387`) + los 2-3 `/insights/performance`. Y todo el pipeline de cálculo
  (TWR, benchmarks, drawdown, diagnósticos, simuladores) corre y se descarta,
  porque los IIFE están en el cuerpo del componente y no detrás de
  `showDiagnostico`.
- **⚠️ Cálculos en el cliente**: los 8 cruces perfil-vs-cartera, en
  `frontend/src/utils/profileMatch.js`, invocados desde `Insights.jsx`:
  `computeAllocationMatch` (`:515`), `computeObjectiveCoherence` (`:516`),
  `computeHorizonComposition` (`:517`), `computeConcentrationVsProfile` (`:518`),
  `computeLiquidityRisk` (`:522`), `computeDrawdownTolerance` (`:1807-1810`, con
  el `drawdown.max` del backend), `computeStyleCoherence` (`:1813`, sobre
  `operations`) y `computeReturnExpectation` (`:2277-2293`).
  El retorno real de esa última card es geométrico y se arma acá:
  `realReturnPct = ((1+ret/100)/(1+infl/100) − 1)·100` (`Insights.jsx:2284-2286`),
  con `ret = perf.twr·100` si el motor dio curva en pesos y si no
  `portfolioReturnArsPctRaw` (`:2281-2282`), e `infl` recortada a la ventana ARS
  (`inflationCumArsWindow`, `:2254-2269`).
- **Renderiza**: `ProfileSummaryBlock` (IA, topic `profile.summary`, sólo si hay
  test hecho — `Insights.jsx:3523-3525`) + `ProfileInvestorBlock` (`:3526`) →
  `ProfileDashboard` (`components/profile/ProfileDashboard.jsx:210`), que arma 9
  módulos con `buildProfileDashboard` (`utils/profileDashboard.js`) y los envuelve
  en `AskAIAbout topic="profile.card"` salvo `radar` y `return_exp`, que no
  tienen code en el backend (`ProfileDashboard.jsx:9-12`, `:33`, `:36`).
- **Sin test de inversor**: `noProfileAtAll` (`Insights.jsx:4174-4177`) → un solo
  CTA a `/config?tab=test` (`:4193-4198`). El cuestionario **no vive acá**.
- **Gating por plan**: `[V]` ninguno. `plan` no se consulta en esta rama.
- **Variante mobile**: no hay.
- **Rarezas**: `[V]` el guard de `useLastVisit` está bien puesto (`:2648-2650`,
  sólo graba la huella en la tab Diagnóstico), pero el `AnalyzeButton
  screen="insights"` del header sí se dibuja acá (`:2710-2714`) — desde el Perfil
  se dispara el análisis IA de *Insights*.

---

## `/fundamentals` → `frontend/src/pages/Fundamentals.jsx` (170 líneas)

- **Qué muestra**: "Calidad de cartera". Tres modos derivados de la URL, sin
  pestañas (`:40`): `home` (tu cartera + seguidas, `CarteraList`), `detail`
  (`?ticker=X` → `AnalyzeView`), `compare` (`?cmp=A,B` → `CompareView`, lazy).
  Buscador como overlay tipo command-palette con ⌘K (`:47-56`, `:157-167`).
- **De dónde saca los datos** (todo en los hijos):
  - `GET /positions`, `GET /brokers`, `GET /dolar` — `components/fundamentals/CarteraList.jsx:54-56`
  - `GET /prices?symbols=…` — `CarteraList.jsx:86`, `DetailPortfolioBlocks.jsx:88`
  - `GET /fundamentals/{ticker}` — `CarteraList.jsx:149`, `AnalyzeView.jsx:149`, `CompareView.jsx:70`
  - `POST /fundamentals/ai-summary` — `AISummaryCard.jsx:39`
  - `GET /tickers/search?q=` — `TickerSearch.jsx:59`
  - `GET /watchlist` / `POST /watchlist` — `useWatchlist.js:23`, `:56`
  - `GET /plazos-fijos` — `DetailPortfolioBlocks.jsx:100`
- **⚠️ Cálculos en el cliente**: los ejes de calidad viven en
  `components/fundamentals/axes.js` y se aplican en el browser.
- **Estado/contexto**: sólo `useSearchParams`. No consume ningún context.
- **Gating por plan**: `[V]` **cero**. `usePlanFeatures` no se importa en ningún
  archivo de `components/fundamentals/`.
- **Variante mobile**: no hay.
- **Rarezas**: `[V]` `components/fundamentals/FavoritesView.jsx` (4.8 KB) **no lo
  importa nadie** — código muerto. `[V]` El límite de comparación (5 tickers)
  está hardcodeado en tres lugares distintos: `parseCmp` (`:28`), `openCompare`
  (`:72`) y `setCmpTickers` (`:87`).

---

## `/posiciones?tab=objetivos` → `frontend/src/pages/Goals.jsx` (677 líneas)

- **Qué muestra**: card de CAGR con el toggle `ModoRendimiento` (`:151-210`),
  lista de objetivos (`GoalCard`, `:250`) con progreso, proyección, escenarios y
  `GoalDiagnostic`, y un modal de alta/edición.
- **De dónde saca los datos**: `GET /goals` (`:52`), `GET /goals/cagr?modo=`
  (`:53`), `GET /positions` (`:54`), `GET /brokers` (`:55`), `GET /dolar`
  (`:56`), `GET /prices?symbols=` (`:79`), `GET /goals/{id}/diagnostic` (`:436`).
  Escrituras: `POST /goals` (`:118`), `PUT /goals/{id}` (`:116`),
  `DELETE /goals/{id}` (`:129`).
- **⚠️ Cálculos hechos en el cliente** — la proyección entera:
  - `currentValue = Σ computeBrokerValue(...).value` (`:81-84`)
  - `monthsLeft` con meses de 30.4375 días (`:255`)
  - `requiredMonthly(pv, fv, rAnnual, months)` (`:623-631`):
    `r = (1+rAnnual)^(1/12) − 1`; `pmt = (fv − pv·(1+r)^n)/(((1+r)^n − 1)/r)`
  - `noContribValue = currentValue·(1+r)^yearsLeft` (`:264`)
  - `requiredReturnNoContrib = ((target/currentValue)^(1/yearsLeft) − 1)·100` (`:266-268`)
  - trayectoria mes a mes con `rMonthly = (1+r)^(1/12) − 1` (`:272-282`)
  - `buildAltScenarios` con `histRate = userCagr ?? 10` (`:635-638`)
- **Estado/contexto**: `useCurrency()` sólo para `valuationDollar` (`:42`); el
  `loadAll` se re-dispara al cambiarlo (`:46`). **No usa `currency`**: todos los
  montos van en USD (`fmtUsd`, `usd`).
- **Gating por plan**: `[V]` ninguno.
- **Rarezas**: `[V]` `computeBrokerValue` se llama **sin** el parámetro
  `costBasis` (`:82`), a diferencia de `Insights.jsx:411` — o sea que el toggle
  "Costo en dólares" no afecta a Objetivos. `[V]` `GoalDiagnostic` linkea a
  `/comportamiento` (`:502`), que es un redirect: el usuario llega a
  `/analisis?tab=comportamiento` con un salto extra.

---

## `/mensual` → `frontend/src/pages/Monthly.jsx` (9 líneas) → `MonthlySummary.jsx` (894)

- **[V] Ruta huérfana** (ver mapa arriba): no hay link en el sidebar ni en
  `More.jsx`.
- **De dónde saca los datos**: `GET /monthly` (`MonthlySummary.jsx:82`, `:90`,
  `:115`), `GET /brokers` (`:87`), `GET /dolar` (`:88`), `GET /config` (`:89`),
  `GET /benchmarks` (`:91`), `GET /positions` (`:253`/`:255`),
  `GET /prices?symbols=` (`:273`).
- **🔴 [V] Escribe en la base al montar.** `syncUnrealizedForAll()` (`:241-306`)
  calcula el P&L no realizado por broker **en el browser**
  (`computeBrokerValue`, `:284`; `pnlForBroker = b.currency==='ARS' ?
  result.pnlArs/tc : result.pnlUsd`, `:287`) y lo persiste con
  `POST /monthly/sync-unrealized` **uno por broker** (`:298`) más uno global
  (`:300`). Sólo lo hace si `valuationDollar === 'mep'` (`persistMep`, `:282`);
  en CCL el número no se escribe y "se auto-corrige en la próxima sesión MEP"
  (`:278-281`). O sea: una preferencia de display del usuario decide si se
  escribe o no un campo contable, y una página sin entrada de navegación es uno
  de los escritores.
- **Rarezas**: `[V]` el comentario de `:288-295` documenta que el Dashboard es
  **otro escritor del mismo campo** con otra convención y que "ganaba el último
  que corriera".

---

## `/wrapped` → `frontend/src/pages/Wrapped.jsx` (604 líneas)

- **[V] Ruta huérfana**: no hay ningún link. Sólo la ruta (`App.jsx:224`) y el
  prefetcher.
- **Qué muestra**: carrusel tipo *stories* con barra de progreso, navegación por
  teclado (`:67-75`) y compartir por slide (`ShareCardModal`).
- **De dónde saca los datos**: `GET /wrapped/{year}` (`:53`). Un solo endpoint;
  los slides vienen armados del backend.
- **⚠️ Cálculos en el cliente**: ninguno financiero.
- **Gating por plan**: `[V]` ninguno.
- **Rarezas**: `[V]` `CURRENT_YEAR = new Date().getFullYear()` es constante de
  módulo (`:38`) — se congela en el bundle cargado; una pestaña abierta cuando
  cambia el año sigue pidiendo el anterior.

---

## `/bienvenida` → `frontend/src/pages/FirstInsight.jsx` (331 líneas)

- **Qué muestra**: el "primer insight" post-import. Valor de la cartera, mejor y
  peor posición, CTA al Dashboard y CTA al Coach IA.
- **De dónde saca los datos**: `GET /positions`, `GET /brokers`, `GET /dolar`
  (`:61-63`) + `GET /prices?symbols=` (`:77`).
- **⚠️ Cálculos en el cliente**: la valuación entera, con la misma cascada que
  `Insights` (`computeBrokerValue`, `pesoLotUsd`, `usdLotValue`, `trustMktValue`,
  `cryptoBrokerFactor` — imports de `:15-16`).
- **Estado/contexto**: `useCoachDrawer()` (`:26`), `useCurrency()` para
  `valuationDollar` y `costBasis` (`:27`).
- **Rarezas**: `[V]` el CTA al Coach navega a `/dashboard` y abre el drawer con
  un `setTimeout(300)` (`:40-41`) — carrera si el chunk del Dashboard tarda más.
  `[V]` El comentario de cabecera (`:8-9`) habla de un flag
  `rendi_first_import_done` que **no se lee ni se escribe** en este archivo; lo
  que sí se usa es `rendi_onboarding_pending` (`:50-52`).

---

## `/i/:token` → `frontend/src/pages/ReportPublic.jsx` (286 líneas)

**Sí, es un informe accesible sin login.** Está registrado en las **dos**
tablas de rutas: la autenticada (`App.jsx:199`) y la pública (`App.jsx:294`).

- **Qué muestra**: un "papel" con la marca del **asesor** (logo o monograma,
  nombre, matrícula CNV), el período, y del cliente: valor de la cartera,
  resultado del período (% y USD), descomposición mercado/aportes, nota del
  asesor, benchmark MEP, curva de evolución, **movimientos del período**
  (fecha/tipo/activo/cantidad), **principales tenencias con su peso %**,
  ganadores y perdedores por tenencia, y un pie con disclaimer. Botón
  "Descargar PDF" = `window.print()` (`:85`) con CSS de impresión (`:65-79`).
- **De dónde saca los datos**: `[V]` un `fetch()` **crudo**, no el helper `api`
  (`:29`): `GET /api/reports/public/{token}`. Sin header de Authorization: el
  token es la única credencial. Todo el payload viene **congelado** del backend;
  el frontend no calcula nada salvo las iniciales del monograma (`:59`), el
  máximo de pesos para escalar las barras (`:60`) y el path del SVG de evolución
  (`EvolutionSvg`, `:266-286`).
- **Cómo se protege el link** (verificado en el backend):
  - token `secrets.token_urlsafe(32)` (256 bits) — `backend/main.py:2945`, doc en
    `:2106`
  - rate-limit por IP: 30 llamadas / 300 s (`backend/main.py:36013`)
  - validación de longitud 10-40 antes de tocar la base (`:36014-36015`)
  - **revocable** por el asesor que lo generó (`POST /api/advisor/reports/{id}/revoke`,
    `:36039-36062`; el `WHERE` lleva `advisor_uid`)
  - **TTL por defecto 180 días**, configurable con `REPORTS_TTL_DAYS`, `0` = para
    siempre (`_report_ttl_days`, `:35990-36000`)
  - revocado y vencido devuelven **404, no 410**, a propósito, para no confirmar
    que el informe existe (`:36010-36012`)
  - `PageMeta … noindex={true}` (`ReportPublic.jsx:64`)
- **Qué expone si el link se filtra**: `[V]` el nombre/marca del asesor y su
  matrícula, la etiqueta del cliente (`r.client_label`), el patrimonio en USD, el
  TC MEP usado, el resultado del período, los movimientos, las tenencias con su
  peso, y los ganadores/perdedores con su P&L. Es la cartera del cliente
  completa menos las cantidades exactas de cada tenencia.
- **Rarezas**: `[V]` el logo se acepta sólo si es un `data:image/` (`:97`) —
  buena defensa contra un `src` remoto. `[V]` En print se ocultan
  `aside, nav, header` (`:72`) para el caso "abierto desde una sesión logueada".
  `[V]` `r.note` (la nota del asesor) se renderiza como texto (`:155`), no como
  HTML — bien.

---

## Componentes compartidos — notas sueltas

- `[V]` `components/InsightsKpiStrip.jsx`: las 5 celdas son Findings /
  Concentración / Drawdown actual / **Acumulado `<ventana>` · `<moneda>`** /
  (la quinta, win rate, más abajo del archivo). La etiqueta de la ventana sale
  de `labelVentanaMeses` (`:10`, `:43`) porque el número cambia en silencio con
  los tabs 1A/2A/5A/MAX (`:108-113`). La concentración top se **recalcula acá**
  a partir de `assetPieData` (`:53-60`) en vez de recibir el `concentration` que
  `Insights` ya computó (`Insights.jsx:1970`).
- `[V]` `components/ArAlternativesVerdict.jsx`: las 3 celdas tienen **bases
  distintas** y ahora lo dicen en la propia celda (`items[].nota`,
  `Insights.jsx:2586`, `:2590`, `:2601-2602`) y en el pie (`:55-64`): plazo fijo
  y dólar son comparación de **patrimonios** flow-matched; inflación es el
  **retorno real** de la pata en pesos. No se pueden restar entre sí.
- `[V]` `components/CompositionDonut.jsx` y `components/diagnostico/
  CompositionByAsset.jsx`: puramente presentacionales; los agregadores
  (`computeClassBreakdown`, `computeSectorBreakdown`) se comparten con el
  Dashboard a propósito (`Insights.jsx:2144-2159`).
- `[V]` `components/CompositionByRisk.jsx` **no lo usa ninguna pantalla de
  Análisis** — su único consumidor es `components/advisor/BookComposition.jsx:32`.
- `[V]` `components/RecommendationsModal.jsx` se usa desde `Sidebar.jsx:389` y
  `More.jsx:192`, no desde Análisis.
- `[V]` `components/BenchmarksLine.jsx` **tampoco** es de estas pantallas: lo
  montan `Dashboard.jsx` y `HomeMobile.jsx`. El benchmark de `/analisis` se
  dibuja inline con `ComposedChart` (`Insights.jsx:3270-3333`).
- `[V]` `components/reports/InsightEvidence.jsx`, `WeekCard.jsx`, `MonthCard.jsx`
  y `PerformanceCalendar.jsx` son los cuatro consumidores de `useMoneyFormat()`
  en Reportes; `Reports.jsx` no lo usa (ver el hallazgo de moneda).
- `[V]` `hooks/useLastVisit.js`: guarda en `localStorage` bajo
  `rendi_lastvisit_<key>` y **nunca escribe durante el render** (agenda en un
  `useEffect`, `:61-79`), con un fingerprint para no reescribir por render
  (`:67-70`). Todo en `try/catch` para modo privado.
- `[V]` `utils/diagnosticsRotation.js` + `Insights.jsx:3763-3778`: el estado del
  "No me interesa" vive en `localStorage` bajo `rendi_diag_dismissed_<userKey>`,
  con soporte de formato viejo (array plano) además del nuevo (`{dismissed,
  slots}`).

---

## Resumen de hallazgos (prioridad descendente)

| # | Hallazgo | Dónde |
|---|---|---|
| 1 | **Crash de Rules of Hooks**: `useState` después de dos early-returns; tocar los tabs Día/Semana/Año tira toda la app al ErrorBoundary | `frontend/src/pages/Reports.jsx:485-501` |
| 2 | **Dos convenciones de moneda en la misma pantalla**: el hero imprime `US$` crudo y el detalle técnico convierte ×TC de hoy | `frontend/src/pages/Reports.jsx:541` etc. vs `frontend/src/components/reports/MonthCard.jsx:73,218` |
| 3 | `/mensual` (ruta sin ningún link) **escribe `pnl_unrealized` en la base al montar**, y sólo si el toggle está en MEP | `frontend/src/components/MonthlySummary.jsx:282,298,300` |
| 4 | `Comportamiento` ignora por completo el selector de moneda (backend sin parámetro `moneda`) | `frontend/src/pages/Behavioral.jsx:114,853`; `backend/main.py:13760` |
| 5 | `/perfil-inversor` monta el `Insights` entero: 13 requests y todo el pipeline de cálculo para renderizar una sección | `frontend/src/pages/PerfilInversor.jsx:24` + `frontend/src/pages/Insights.jsx:355-394` |
| 6 | ~700 líneas de componentes muertos en `Insights.jsx` (las 8 `Profile*Card` + `InsightCard` + `AllocationRow` + `BenchmarkCard` + `InflationCard` + `AccordionSection`) | `frontend/src/pages/Insights.jsx:3545,3576,4143,4245,4293-4783` |
| 7 | El motor de layout adaptativo calcula 12 slots y se consultan 2; `checklist` no tiene renderer | `frontend/src/utils/diagnosticoTemplate.js:43-62` vs `frontend/src/pages/Insights.jsx:2670,2689` |
| 8 | Dos motores distintos para "¿le gano al S&P?" en la misma pantalla: gráfico = backend por fecha, diagnóstico/veredicto = simulador del browser sobre la cadena contable | `frontend/src/pages/Insights.jsx:1695-1696` vs `:2166-2197` |
| 9 | `insights_diagnostic_visible` sigue publicándose desde el backend y ya no lo lee nadie en el frontend | `backend/ai/plan.py:48,68` vs `frontend/src/pages/Insights.jsx:3814-3816` |
| 10 | `PLUS_VISIBLE_COUNT = 6` duplicado a mano entre frontend y `plan.py` | `frontend/src/pages/Behavioral.jsx:693` |
| 11 | Doble `<h1>` en las 3 tabs de `/analisis` y en `/perfil-inversor` (triple en el empty state) | `frontend/src/pages/Analisis.jsx:83` + los `PageHeader` de cada hijo |
| 12 | `/wrapped` y `/mensual` son rutas huérfanas; `components/fundamentals/FavoritesView.jsx` es un componente huérfano | `frontend/src/App.jsx:209,224`; `frontend/src/components/fundamentals/FavoritesView.jsx` |
| 13 | `aiSnapshot.summary.pnl_total_usd` lleva un porcentaje, no dólares | `frontend/src/pages/Insights.jsx:2446-2447` |
| 14 | `/insights/performance` se pide 2-3 veces por carga de página | `frontend/src/pages/Insights.jsx:349,370` |
| 15 | Calmar mezcla CAGR del browser (cadena contable) con drawdown del backend (curva medida) | `frontend/src/utils/insightsMetrics.js:511` + `frontend/src/pages/Insights.jsx:2181` |
| 16 | `best`/`worst` del KPI strip de Reportes se calculan y no se dibujan | `frontend/src/components/reports/PerformanceCalendar.jsx:67-73` |
| 17 | Comentario mobile desactualizado ("ocultamos la curva de drawdown") | `frontend/src/pages/Insights.jsx:153-156` |
| 18 | Goals llama `computeBrokerValue` sin `costBasis`: el toggle "Costo en dólares" no lo afecta | `frontend/src/pages/Goals.jsx:82` |
| 19 | Código muerto de arrastre: `LockedSection` (`:27`) y `Panel` (`:19`) en Behavioral; `Fragment` (`:12`) y 5 helpers de fecha (`:45,49,53,59,70`) en Reports; ~14 imports en Insights | ver detalle en cada sección |
