## Frontend — el núcleo: `utils/`, `hooks/`, `contexts/`, `App.jsx`

Ámbito auditado: `frontend/src/utils/` (49 módulos + 39 archivos `.test.js`), `frontend/src/hooks/` (14 hooks + 4 tests), `frontend/src/contexts/` (7 contexts + 2 tests) y `frontend/src/App.jsx`. Todo verificado sobre la copia de `origin/main` (commit `b74f450f`).

Titular de la sección: **esta carpeta es el motor financiero de Rendi, no una capa de presentación**. `frontend/src/utils/valuation.js` (945 líneas) decide cuánto vale cada lote, `frontend/src/utils/insightsModel.js` (1087) calcula el TWR/Modified Dietz, `frontend/src/utils/diagnostics.js` (1010) genera 58 diagnósticos, `frontend/src/utils/bondPricing.js` resuelve TIR por Newton+bisección, y `frontend/src/utils/demo.js` (3223) es un backend entero hardcodeado. El backend tiene su propia versión de varias de estas cuentas y los comentarios del propio código lo dicen ("Espejo de…", "si esto y el backend divergen, el que está mal es esto").

---

## 1. `utils/api.js` — el único cliente HTTP

`frontend/src/utils/api.js` (394 líneas). Exporta `api` (`get/post/put/patch/delete/upload/getBlob/chatStream`), `errorMessage` y `gatewayMessage`, más las tres funciones del contexto de cliente del Plan Asesor. **89 archivos lo importan** — es el módulo más importado del frontend después de nada.

### 1.1 Base URL y credenciales [V]

- No hay base URL configurable ni variable de entorno: todo request es `fetch('/api' + path, …)` — `frontend/src/utils/api.js:106`, `:228` (upload), `:265` (getBlob), `:304` (chatStream). Same-origin siempre.
- Quien traduce ese `/api` al backend es el rewrite de Vercel: `frontend/vercel.json` → `{ "source": "/api/(.*)", "destination": "https://trading-production-143b.up.railway.app/api/$1" }`. En dev lo hace el proxy de Vite (`frontend/vite.config.js:46-49`, `'/api': 'http://localhost:8000'` en `:48`).
- Auth por **cookie HttpOnly** (`rendi_token`): todos los fetch llevan `credentials: 'include'` (`frontend/src/utils/api.js:109`, `:230`, `:267`, `:307`). El JS nunca ve el token. Hay una limpieza one-time de la cookie legacy en localStorage al importar el módulo (`frontend/src/utils/api.js:13-17`).
- Header propio: `X-Rendi-Client-Id` cuando hay contexto de cliente del Plan Asesor. Se inyecta en los **cuatro** caminos: `req` (`:104`), `upload` (`:227`), `getBlob` (`:264`) y `chatStream` (`:303`). Los comentarios dicen que las dos últimas se agregaron después de bugs reales ("el import caía SILENCIOSAMENTE en la cuenta del asesor", "el export CSV bajaba la cartera del ASESOR presentada como la del cliente").
- El header se manda **siempre** que haya contexto, incluso a `/auth/*` y `/billing/*`; el filtrado es responsabilidad del backend (comentario en `:22-25`).

### 1.2 Manejo de 401 [V]

`frontend/src/utils/api.js:119-128`:

```js
if (res.status === 401) {
  const hadUser = !!localStorage.getItem('rendi_user')
  localStorage.removeItem('rendi_user')
  if (hadUser) { window.location.href = '/' }
  throw new Error('Unauthorized')
}
```

- Redirige a `/` (hard navigation, no SPA) solo si había un `rendi_user` en localStorage. La misma lógica está en `chatStream` (`:312-317`).
- **Asimetría [V]**: `upload` (`:241-245`) y `getBlob` (`:270-274`) redirigen **incondicionalmente**, sin el guard `hadUser`. Son tres implementaciones del mismo bloque con dos comportamientos.
- El 401 no pasa por `buildHttpError`: el mensaje siempre es el literal `'Unauthorized'`, así que `errorMessage()` sobre un 401 devuelve eso en inglés.
- No hay refresh de token ni cola de reintento post-401.

### 1.3 Errores HTTP: `buildHttpError` + `errorMessage`

- `buildHttpError` (`frontend/src/utils/api.js:142-160`) parsea `detail` de FastAPI: string → mensaje; dict → `.error || .message || .detail || JSON.stringify`. Adjunta `err.status` y `err.payload`.
- `errorMessage` (`:174-189`) existe porque `buildHttpError` no cubre bien el 422 de Pydantic, donde `detail` es una **lista** por campo: ahí arma `"campo: qué pasa"` con `d.loc.slice(1).join('.')`. Devuelve `''` si no hay nada legible, para que el caller ponga su propio fallback.

### 1.4 Reintentos: `gatewayRetry` (no existe `apiRetry.js`) [V]

Ojo con el nombre: **no hay `utils/apiRetry.js`**. Existe `frontend/src/utils/apiRetry.test.js` (158 líneas), pero la implementación vive en `frontend/src/utils/gatewayRetry.js` (53 líneas). El propio test lo explica (`frontend/src/utils/apiRetry.test.js:13-16`): antes el test se copiaba la función y probaba a la copia, así que un bug real (el de `AbortError`) pasaba en verde.

Política (`frontend/src/utils/gatewayRetry.js`):

| Elemento | Valor | Línea |
|---|---|---|
| Códigos que se reintentan | `[502, 503, 504]` | `:11` |
| Delays | `[800, 2500, 5000]` ms (≈8,3 s en total, 4 intentos) | `:12` |
| Jitter | ±20 % (`ms * (0.8 + rnd()*0.4)`) | `:20-22` |
| Cancelación | `AbortError` / `code===20` / `signal.aborted` → **no** reintenta | `:30-32` |
| Falla de red (fetch rechaza) | también reintenta con el mismo esquema | `:42-48` |

Quién lo usa (`frontend/src/utils/api.js`):
- **GET sí** (`:115-117`), porque es idempotente.
- **POST/PATCH/PUT/DELETE no** — el comentario dice "repetirlo podría duplicar un alta".
- `upload`: reintenta **solo** si la ruta matchea `/\/preview(\?|$)/` (`:238-239`); el `confirm` de la importación no se reintenta.
- `getBlob` y `chatStream`: **sin retry**.

### 1.5 Backend frío (Railway cold start) [V]/[I]

Lo que el código hace realmente:

1. Un GET a un backend dormido devuelve 502/503/504 → `withGatewayRetry` hace hasta 3 reintentos con ~8,3 s de presupuesto total (`frontend/src/utils/gatewayRetry.js:12`). Si el arranque tarda más, el usuario ve el mensaje de gateway. **[I]** El presupuesto está calibrado para un redeploy, no para un cold start largo.
2. El mensaje NO promete duración y distingue lectura de escritura (`frontend/src/utils/api.js:207-213`). El comentario `:196-206` documenta por qué: el 2026-08-10 el backend estaba colgado (lock de escritura de SQLite), no reiniciando, y "probá de nuevo" sobre una escritura hizo que un usuario reintentara una cancelación de suscripción que ya había ocurrido.
3. **Keep-alive**: `frontend/src/contexts/AuthContext.jsx:118-122` pinga `fetch('/api/health')` cada 4 minutos mientras haya usuario logueado y no sea demo. Es el anti-dormida del lado del cliente. No pasa por `api` (no lleva el header de cliente ni retry), y solo corre con una pestaña abierta.
4. **[I]** Sobre POST/PATCH/DELETE no hay red alguna: un 502 en el primer POST tras el despertar del servicio llega crudo al usuario con el texto de "no sabemos si se completó".

### 1.6 `chatStream` (SSE)

`frontend/src/utils/api.js:288-383`. Fetch propio a `/api/ai/chat` con `stream:true`, lectura por `ReadableStream`, frames SSE separados por `\n\n`, eventos `delta` / `reset` / `done` / `error`. Detalles con historia:
- `sawTerminal` (`:334`, `:377-381`): sin un frame terminal (`done`/`error`) la respuesta se considera **truncada** y se lanza `err.truncated`. El comentario dice que antes un stream cortado a los 30 s se devolvía como si estuviera completo.
- `reset` (`:353-357`): el turno anterior terminó en `tool_use` → lo streameado era preámbulo; el caller limpia la burbuja.
- En demo hace `req('POST','/ai/chat',{stream:false})` y respeta el `signal.aborted` a mano (`:288-298`), porque el mock resuelve por `setTimeout` (inabortable).

---

## 2. Inventario completo de `utils/`

`✓` = tiene `.test.js` propio. La columna "quién lo usa" lista importadores reales (no tests), verificados con grep por ruta de import.

| archivo | qué hace | exports | quién lo usa | test |
|---|---|---|---|---|
| `api.js` (394) | cliente HTTP único + contexto de cliente asesor | `api`, `errorMessage`, `gatewayMessage`, `getClientContext`, `setClientContext`, `clearClientContext` | 89 archivos | vía `apiRetry.test.js`, `errorMessage.test.js`, `gatewayMessage.test.js`, `chatStream.test.js` |
| `gatewayRetry.js` (53) | política de reintento 502/503/504 | `GATEWAY_ERRORS`, `RETRY_DELAYS_MS`, `conJitter`, `fueCancelado`, `withGatewayRetry` | `api.js` | ✓ (como `apiRetry.test.js`) |
| `demo.js` (3223) | backend simulado completo del modo demo | `getDemoOverlay`, `isDemoMode`, `enableDemoMode`, `disableDemoMode`, `handleDemoRequest` | `api.js`, `AuthContext`, `chatSession.js`, `pages/Login.jsx` | ✗ |
| `valuation.js` (945) | valuación por lote y por broker (SSoT) | 22 (ver ficha) | 28 archivos | ✓ (+`sumRow.test.js`, `buildPriceSymbols.test.js`) |
| `valuationGuards.js` (96) | % canónico + detector de filas inconsistentes | `positionPct`, `checkPositionRow`, `auditPositions` | `Insights.jsx`, `Dashboard.jsx` | ✓ |
| `insightsModel.js` (1087) | TWR/Modified Dietz, drawdown, MtM, KPIs de ventana | 25 | `useMonthlyData.js`, `Insights.jsx`, `Dashboard.jsx` | ✓ (+`applyMtmToMonthly.test.js`, `monthlyReturnArs.test.js`) |
| `insightsMetrics.js` (523) | Sharpe/Sortino/vol/alfa-beta/IR/CAGR/Calmar | 11 | **solo** `Insights.jsx` | ✓ (+`computeCagrSpan.test.js`) |
| `insights.js` (59) | frase narrativa del Dashboard | `buildDashboardInsight` | **solo** `Dashboard.jsx` | ✗ |
| `diagnostics.js` (1010) | 58 generadores de diagnóstico + selector con rotación diaria | `DIAGNOSTIC_GENERATORS`, `selectDiagnostics`, `hashString`, `dayOfYearKey` | **solo** `Insights.jsx` | ✓ |
| `diagnosticsRotation.js` (70) | grilla 3×3 con slots estables y "no me interesa" | `resolveTierShown`, `computeDismiss` | **solo** `Insights.jsx` | ✓ |
| `diagnosticoTemplate.js` (96) | arquetipo del usuario + orden de slots del tab Diagnóstico | `ARCHETYPES`, `classifyArchetype`, `buildDiagnosticoLayout` | **solo** `Insights.jsx` | ✓ |
| `evolution.js` (602) | serie de valor del portfolio, aptitud de snapshots, P&L del día | 10 | `HomeMobile`, `Dashboard`, `Insights`, `useMonthlyData` | ✓ |
| `assetPnl.js` (273) | P&L por clase/sector (no realizado + realizado + renta) | `opPnlUsd`, `ratePct`, `computePnlByKey`, `mergePnl` | `assetClass.js`, `assetSector.js`, `Operations.jsx` | ✓ |
| `assetClass.js` (355) | clasificador único de CLASE de activo | 9 | `assetPnl`, `assetSector`, `bookComposition`, `Insights`, `Dashboard`, `advisor/BookComposition` | ✓ |
| `assetSector.js` (269) | clasificador de SECTOR económico | `SECTOR_META`, `SECTOR_ORDER`, `classifySector`, `computeSectorBreakdown` | `Insights`, `Dashboard`, `advisor/BookComposition` | ✓ |
| `tradeStats.js` (76) | win rate de Operaciones (espejo del backend) | `esTradeCerrado`, `computeTradeStats` | **solo** `Operations.jsx` | ✓ |
| `bondPricing.js` (319) | day-count, accrued, TIR (Newton+bisección) | 7 | **solo** `bondSchedule.js` | ✓ |
| `bondSchedule.js` (399) | genera el cronograma y estima TIR por ticker | 10 | `pendingCashflows`, `upcomingEvents`, `RentaFijaSections`, `BondCashflowModal`, `BondDetail`, `Positions` | ✓ (+`bondScheduleCER.test.js`) |
| `bondSchedulesAR.js` (270) | cronogramas del canje 2020 (AL/GD) | 8 | **solo** `bondMeta.js` | ✓ |
| `bondCashflowFx.js` (114) | sugerir monto de cupón en la moneda del broker | `sameCurrency`, `suggestBrokerAmount` | **solo** `BondCashflowModal.jsx` | ✓ |
| `bondMeta.js` (273) | catálogo estático de bonos + labels | 6 | 8 archivos | ✗ |
| `fx.js` (48) | dólar blue histórico por (año, mes) | `lookupHistoricalDolar` | `evolution.js`, `MonthlySummary`, `Insights` | ✓ |
| `fxPanel.js` (55) | filtro/orden del panel admin de migración FX | `deltaRendimiento`, `filtrarFilas`, `contarCaen`, `contarFrenadas` | **solo** `pages/Admin.jsx` | ✓ |
| `crypto.js` (53) | universo cripto + premium dólar-cripto | `CRYPTO_SYMBOLS`, `isCrypto`, `cryptoBrokerFactor` | 10 archivos | ✓ |
| `benchmarkSim.js` (375) | simula "la misma plata en otro lado" (S&P, blue, MEP, SHV, oro, Merval, PF UVA) | 10 | `BenchmarksLine.jsx`, `Insights.jsx` | ✓ |
| `bookComposition.js` (411) | composición del libro del asesor | 8 | **solo** `advisor/BookComposition.jsx` | ✓ |
| `brokerAccounts.js` (140) | agrupa brokers padre+hijo en CUENTAS | `groupBrokersIntoAccounts`, `brokerLegLabel`, `accountForBrokerName`, `flattenAccounts` | `BrokerManager`, `Positions`, `PositionsMobile`, `reports/BrokerSelector` | ✓ |
| `pendingCashflows.js` (175) | cupones teóricos pendientes de registrar | `detectPendingCashflows`, `groupPendingByBond` | **solo** `Positions.jsx` | ✓ |
| `upcomingEvents.js` (244) | agenda: earnings del backend + cupones del frontend | 11 | `UpcomingEventsCard`, `EventBadge`, `Events`, `AdvisorNovedades` | ✓ |
| `profileMatch.js` (679) | cruces perfil declarado vs cartera real | 9 | **solo** `Insights.jsx` | ✗ |
| `profileAllocations.js` (334) | tablas de referencia perfil → asignación | 9 | `profileMatch.js`, `profileDashboard.js` | ✗ |
| `profileDashboard.js` (299) | relevancia y orden de módulos del tablero de perfil | 4 | **solo** `profile/ProfileDashboard.jsx` | ✓ |
| `fundamentalsCompare.js` (256) | quién gana cada métrica en "Comparar" | 5 | **solo** `fundamentals/CompareView.jsx` | ✓ |
| `sections.js` (66) | secciones de renta fija (Bonos/Letras/FCI × USD/ARS) | 9 | `RentaFijaSections`, `AddPositionFlow`, `Positions`, `PositionsMobile` | ✓ |
| `positionsDiscovered.js` (31) | flag "vio la pantalla de posiciones" (onboarding) | `POSITIONS_DISCOVERED_KEY`, `isPositionsDiscovered`, `markPositionsDiscovered` | `Cartera.jsx`, `home/OnboardingChecklist.jsx` | ✗ |
| `tickers.js` (629) | catálogo/allowlist de tickers + tipos de activo | 29 | 19 archivos | ✓ |
| `format.js` (147) | formateo de números/moneda/% + color | 13 | 26 archivos | ✓ |
| `autoUpdate.js` (227) | recarga proactiva a bundle nuevo | `checkForUpdate`, `applyUpdateIfPending`, `useAutoUpdate` | **solo** `App.jsx` | ✗ |
| `safeUrl.js` (52) | sanea URLs externas y de pago | `safeExternalUrl`, `isSafePaymentUrl` | `TopNewsCard`, `News`, `Planes`, `home/NewsPreview` | ✗ |
| `track.js` (160) | telemetría interna (+ reenvío whitelisted al backend) | `track`, `trackRoute` | 39 archivos | ✗ |
| `analytics.js` (154) | GA4 | `initAnalytics`, `trackPageView`, `trackEvent`, `setUserId`, `setUserProperties` | 9 archivos | ✗ |
| `metaPixel.js` (117) | Meta Pixel | `initMetaPixel`, `trackMetaEvent`, `trackMetaPageView` | `main.jsx`, `App.jsx`, `AuthContext`, `Login` | ✗ |
| `routePrefetch.js` (53) | prefetch de chunks al hover | `prefetchRoute` | `Sidebar`, `mobile/MobileTabBar` | ✗ |
| `watchlistEvents.js` (27) | CustomEvent para sincronizar watchlist | `notifyWatchlistChanged`, `subscribeWatchlistChanged` | 6 archivos | ✗ |
| `chatSession.js` (93) | persistencia del chat en sessionStorage | `MAX_STORED`, `MAX_SENT`, `loadChatSession`, `saveChatSession`, `clearChatSession`, `sendWindow` | `AICoach.jsx`, `RendiAI.jsx` | ✓ |
| `aiStructured.js` (199) | parser del bloque `---RENDI---` de la IA | `RENDI_DELIM`, `parseStructured` | **solo** `AICoach.jsx` | ✓ |
| `stripMarkdown.js` (22) | markdown → texto plano | `stripMarkdown` | **solo** `AICoach.jsx` | ✓ |
| `distributionAi.js` (48) | arma el packet de distribución que va al modelo | `toDistributionAiParams` | `bookComposition`, `Insights`, `Dashboard` | ✓ |
| `shareCard.js` (425) | tarjetas 1080×1350 en Canvas | 9 | `MonthlySummary`, `ShareCardModal`, `Behavioral`, `mobile/InsightDelDiaHero` | ✓ |
| `support.js` (17) | número + link de WhatsApp de soporte | `SUPPORT_WHATSAPP`, `SUPPORT_MESSAGE`, `whatsappUrl`, `SUPPORT_WHATSAPP_DISPLAY` | 8 archivos | ✗ |

**Ningún archivo de `utils/` está huérfano** 💀 — los 49 tienen al menos un importador real. Lo que sí hay son **exports muertos**; ver §9.

---

## 3. Fichas de los utils con lógica financiera

### 3.1 `valuation.js` — la valuación (945 líneas, 28 importadores)

Es el SSoT declarado. Estado de módulo: `_brokersByName` / `_brokersById`, poblados con `setBrokersRegistry(brokers)` (`frontend/src/utils/valuation.js:132-137`). Ese registro se limpia en login y logout (`frontend/src/contexts/AuthContext.jsx:137` y `:222`) porque, dice el comentario, en una máquina compartida "el usuario B podía valuar con los brokers del usuario A".

**Ruteo de precio** — `priceSymbol(asset, isARS, assetType)` (`:81-102`):
- `FCI:*` → tal cual (el backend lo resuelve por `fci_prices`).
- `assetType === 'CEDEAR'` → `${asset}.BA` **siempre**, aunque esté en broker USD.
- `isARS` → `${asset}.BA`.
- resto → ticker US con clases normalizadas a guión: `(asset||'').replace(/[\s.]+/g, '-')` — `'BRK B'`/`'BRK.B'` → `'BRK-B'`.
- `isArStock` (`:14`) **ya no rutea nada**; su docstring explica que forzaba `.BA` y rompía los ADR (GGAL/BMA en Schwab).

**Sub-broker dólar de padre argentino** — `isArUsdBroker(brokerName)` (`:191-201`): decide por `parent_broker_id` (padre `ARS`, hijo no) y solo cae al sufijo `/·\s*USD$/` si el registro no está poblado.

**Guard anti-distorsión** — `trustMktValue(mktValue, realCost, assetType, hasOverride)` (`:448-454`):

```
mult = mktValue / realCost
renta fija (BOND|BONO|ON|LETRA|LECAP) → 0.02 ≤ mult ≤ 4
resto                                  → 0.002 ≤ mult ≤ 50
hasOverride && !fixed                  → siempre true
!(realCost>0) || !(mktValue>0)         → true
```

Si no confía, el valor cae al costo (P&L = 0). El override manual se respeta salvo en renta fija, "caso real: una ON con precio manual en convención per-100 (97 en vez de 0,97) → +9775 %".

**Costo en dólares** — `costBasisRate(p, currentRate, costBasis)` (`:263-269`):

```
(costBasis === 'purchase' && p.tc_compra > 0) ? p.tc_compra : currentRate
```

El default del parámetro es `'purchase'`, alineado a propósito con el default del contexto (`frontend/src/contexts/CurrencyContext.jsx:102-109`) — el comentario explica que cuando eran distintos, cualquier caller que se olvidara del argumento volvía en silencio al dólar de hoy (bug reportado con números: ALUA comprado a 880 con TC 1048 mostraba US$0,58 en vez de 0,84).

**El motor por lote** — `valuePositionLot(p, ctx)` (`:543-734`), 6 ramas en orden estricto:

| # | condición | costo → USD | valor → USD | línea |
|---|---|---|---|---|
| 1 | `p.is_cash` (broker ARS) | `invested / cedearRate` | igual al costo (sin FX gain) | `:626-641` |
| 1' | `p.is_cash` (broker USD) | `invested` | igual | `:675-679` |
| 2 | `!isAR && costInPesos(p)` | `realCost / costBasisRate(...)` | `precio.BA × qty / cedearRate` | `:573-592` |
| 3 | `isAR && costInUsd(p)` | ya en USD (sin ÷MEP) | `usdLotValue` (por tipo) | `:601-621` |
| 4 | `isAR` nativo | `realCost / costBasisRate(...)` | `precio.BA × qty / cedearRate` | `:642-670` |
| 5 | `(CEDEAR ∥ arUsd) && !cripto && !FCI && sin override` | `realCost × f` | `precio.BA × qty / cedearRate` | `:687-711` |
| 6 | resto (USD nativo) | `realCost × f` | `precio × qty × f` | `:713-733` |

`f = cryptoBrokerFactor(...)` (`frontend/src/utils/crypto.js:47-52`) = `tcCripto / tcMep` para cripto en broker no-exchange, `1` en todo lo demás — se aplica a costo **y** valor para que el P&L% quede invariante.

Regla repetida en 3 ramas: **sin precio confiable el modo `'purchase'` no aplica** — valor y costo van los dos al dólar de hoy y el P&L queda exactamente 0. El comentario dice que antes se publicaba `costo/tc_compra` como valor de mercado (`:580-582`, `:659-661`, `:410-415`).

`computeBrokerValue` (`:740-762`) es hoy **solo la suma** de `valuePositionLot` sobre los lotes del broker.

**Duplicación admitida en el propio código** [V]: el docstring de `valuePositionLot` (`:504-509`) dice que había **cinco** implementaciones de la valuación por lote (`computeBrokerValue`, `valueEquityLot`, `AssetDetail.valueLot`, `PositionDetailMobile`, `PositionsMobile`) y que "todavía NO la consume nadie más". `valueEquityLot` (`:360-421`) sigue viva y la usan `fundamentals/CarteraList.jsx` y `fundamentals/DetailPortfolioBlocks.jsx`.

**Cobertura de precios** — `valuationPriceKey` (`:469-475`) y `buildPriceSymbols(positions, brokers)` (`:484-494`) son la lista canónica de símbolos a pedir. El docstring dice que cada pantalla que lo reimplementaba tenía un agujero distinto. Lo consumen `Dashboard.jsx:183`, `Positions.jsx:577`, `PositionsMobile.jsx:556`, `HomeMobile.jsx:94`.

**Otras piezas**: `computePf` (`:797-841`) valúa plazos fijos (TNA simple / TEA compuesta / capitalización periódica); `avgCostUsdPerUnit` (`:868-881`) hace el promedio ponderado por lote e independiente del orden; `sumRowUSDT` / `sumRowARS` (`:905`, `:925`) suman filas agregadas a partir de lotes ya valuados porque "una fila agregada NO se puede re-valuar como si fuera una posición sola".

### 3.2 `valuationGuards.js`

- `positionPct(valueUsd, pnlUsd)` (`frontend/src/utils/valuationGuards.js:33-39`): `invested = value − pnl; pct = invested>0 ? pnl/invested : null`. Antídoto contra el "% del primer lote".
- `checkPositionRow(row, {pct})` (`:50-75`): dos chequeos — (a) el `pnl_pct` reportado vs el derivado, con tolerancia `max(0.01·escala, 3 % relativo)`; (b) `value/invested > 50` → "posible inflado".
- `auditPositions(rows, label)` (`:80-94`): en DEV loguea; en prod es no-op (`isDev()` mira `import.meta.env.DEV`, `:16-23`). **Es el único uso de `import.meta.env` en todo `frontend/src/`.**

### 3.3 `insightsModel.js` — el motor de rendimiento (1087)

- `netCapitalContributed` (`:41-52`): `baseline + Σ(deposits − withdrawals)`, donde `baseline = sorted[0].capital_inicio_costo ?? capital_inicio`. El fallback a `_costo` existe porque `applyMtmToMonthly` puede pisar `capital_inicio` con el snapshot a mercado, y "el Capital aportado del hero se infla en silencio con la ganancia latente".
- `buildCumulativeReturnSeries(globalMonthly, liveValue)` (`:93-153`) — Modified Dietz:
  ```
  net       = deposits − withdrawals
  avgCap    = capInicio + 0.5·net           (o `net` si es primer mes con capInicio=0 y net>0)
  rawReturn = (capFinal − capInicio − net) / avgCap
  monthly   = max(rawReturn, −0.99)
  index_t   = index_{t−1} · (1 + monthly)
  ```
  El caso "import inicial" (`:114-119`) evita duplicar la pérdida cuando el primer mes trae todo el histórico como depósito. El clamp a −0,99 (`:129-131`) evita que un `capital_final` negativo invierta el índice.
- `computeDrawdownOnReturns` (`:170`), `buildDrawdownTimeSeries` (`:373`): drawdown sobre la serie TWR, no sobre valor absoluto.
- `computeProfitFactor` (`:504-518`): `grossWin/grossLoss`, con `Infinity` si no hubo pérdidas.
- `monthlyReturnArs({ci, cf, net, fxPrev, fx, isImportInitial})` (`:551-575`) — **la corrección que más pesa del módulo**. El comentario `:520-550` documenta que la serie ARS convertía las tres puntas con el FX del mismo mes y el factor se cancelaba exacto: "el retorno en pesos ERA el retorno en dólares con otra etiqueta". La versión buena:
  ```
  ciArs  = ci · fxPrev
  cfArs  = cf · fx
  netArs = net · √(fxPrev·fx)      ← media GEOMÉTRICA
  avgArs = isImportInitial ? netArs : ciArs + 0.5·netArs
  raw    = (cfArs − ciArs − netArs) / avgArs ; piso −0.99, sin techo
  ```
  Si falta `fx` o `fxPrev` devuelve **null** — deliberado, "caer al retorno USD sería volver al bug".
- `applyMtmToMonthly` (`:600-…`): reemplaza `capital_inicio/final` por snapshots MtM. Regla explícita: un mes cerrado solo se convierte si existen **los dos** snapshots; mezclar (ci a costo, cf a mercado) "es exactamente lo que fabrica el fantasma".
- `resolucionDeSerie(keys)` (`:926-933`): `diaria` si el span medido ≤ `RESOLUCION_DIARIA_DIAS = 92` (`:902`), si no `mensual`.
- `acumuladoDeVentana(filas, claveMedida, claveEstimada)` (`:968-1031`): el KPI usa `total` (`(index−1)·100`) y **no** el cociente primera/última fila. Caso borde documentado: `total===0` con una sola fila devuelve `null` (es el arranque de un segmento, "0,0 %" se leería como "no se movió"); con varias filas en 0 sí publica 0.
- `acumuladoPublicado(filas, benchKey, opts)` (`:1063-1087`): lee `ip` (índice publicado del backend) entre el primer y el último punto **apto**, y devuelve `null` si en el medio hay una fila `corte-…`. El comentario cita medición en producción: 20 de 480 usuarios leían acá un número >5 pp distinto del que el backend afirma (uid 745: +642,9 % vs +6,6 %).

### 3.4 `insightsMetrics.js` (523) — solo lo consume `Insights.jsx`

| función | fórmula | línea |
|---|---|---|
| `computeMonthlyReturns` | Modified Dietz por mes, descarta meses con `start ≤ 100` y outliers | `:51` |
| `computeAnnualizedVolatility` | `σ(mensual) · √12` | `:86` |
| `computeSortino` | exceso / desvío de la semivarianza negativa | `:113` |
| `estimateRiskFreeRate` | de la serie SHV del backend | `:150` |
| `computeSharpe` | `(ret − rf) / vol` | `:180` |
| `computePriceMapReturns` | retornos mensuales de un mapa de precios | `:205` |
| `computeAlphaBeta` | regresión contra el benchmark | `:250` |
| `computeInformationRatio` | exceso / tracking error | `:322` |
| `computeCAGR` | `(1+totalGrowth)^(12/n) − 1`, **con `n` = meses transcurridos entre la primera y la última clave**, no la cantidad de meses que sobrevivieron los filtros | `:380-420` |
| `computeCalmar` | `CAGR / |maxDD|` | `:450` |
| `computeProMetrics` | orquestador que llama a todas | `:486` |

El comentario de `computeCAGR` (`:397-408`) mide el defecto que corrige: un usuario 12 meses afuera del mercado veía +26,8 % anual cuando sobre 30 meses reales rindió +10,0 % (16,9 pp de aire).

### 3.5 `insights.js` (59)

`buildDashboardInsight({totalValue, netDeposited, positions})` (`frontend/src/utils/insights.js:16-59`): `totalReturn = totalValue − netDeposited`; `pct = netDeposited>0 ? totalReturn/netDeposited : 0`. Tres narrativas: ≤ −10 % nombra los 2 peores, ≥ +10 % los 2 mejores, resto resume. Es el único módulo de `utils/` con textos en inglés en el docstring y español en el output.

### 3.6 `evolution.js` (602)

El módulo con la advertencia más fuerte del repo (`frontend/src/utils/evolution.js:3-19`): **dos preguntas distintas, dos predicados distintos**.

- `esApto(s)` (`:31-34`): `s.apto !== undefined ? !!s.apto : !s.sintetico`. ¿Puede ser pico, borde o denominador?
- `esDibujable(s)` (`:43-47`): `ACEPTA_LINEA = ['medicion','reconstruido','intradia']` (`:20`) sobre `s.clase`. ¿Entra a la línea?
- `baseIncomparable(inicioEsMedido, inicioValor, depositos, retiros)` (`:113-118`): con `_TOL_BASE_SIN_MEDIR = 0.10` (`:59`) — portado literal de `_UNMEASURED_BASE_TOL` de `backend/reporting/builder.py`. Devuelve true si más del 10 % de la base del período viene de capital contable sin medir.
- `convertSeriesToArs(series, getFxForDate)` (`:156-171`): FX por punto, prioridad `p.fxToUsdBlue` estampado → lookup por fecha → **1** (no convertir).
- `computeReturnDelta(snapshots, {liveValue, liveNetDeposited, sinceDate})` (`:305-368`): filtra por `esApto` en **las dos puntas** (el comentario dice que 180 usuarios, 22 %, tenían la última fila al costo). `usd = (todayValue − todayNetDep) − (prev.total_value − netDepositedOf(prev))`; `pct = prevValue > 0 ? usd/prevValue : 0`; y devuelve `null` si `!(prev.total_value > 0)` o si sin `liveValue` las dos puntas son la misma fila.
- `computeDailyPnl` (`:375-377`) es `computeReturnDelta` sin `sinceDate`.
- `buildEvolutionFromSnapshots` (`:407-…`): `total % = (value − baseline)/baseline·100`, con `baseline = net_deposited` o, en snapshots legacy con `net_deposited === 0`, `total_invested`.

### 3.7 `diagnostics.js` (1010) + `diagnosticsRotation.js` (70)

- **58 generadores** (`DIAGNOSTIC_GENERATORS`, `frontend/src/utils/diagnostics.js:56`), cada uno `(data) => null | string`. Severidades: `urgent` / `warn` / `positive` / `info` (`SEVERITY_RANK`, `:960`).
- `selectDiagnostics(data, maxBullets=5, today)` (`:972-1006`): corre todos dentro de try/catch, marca los `premium` como locked si `data.isFree` (reemplazando el texto por el `lockedLabel`, así el valor no viaja), ordena por severidad y desempata con `hashString(id) ^ hashString(dayOfYearKey(today))` — rotación estable dentro del día, cambia a las 00:00 **UTC** (`:947-953`). **[I]** En Argentina (UTC−3) eso significa que los diagnósticos rotan a las 21:00 hora local.
- `diagnosticsRotation.js`: `resolveTierShown(pool, poolIds, savedIds, dismissed)` (`:26-44`) preserva la identidad de slot; `computeDismiss` (`:58-69`) reemplaza **en su lugar** y, al agotar el tier, limpia los descartados de ese tier y cicla. El comentario cuenta el bug original: `pool.filter(!dismissed).slice(0,3)` corría toda la ventana y cambiaban las 3 tiles.

### 3.8 `assetPnl.js` / `assetClass.js` / `assetSector.js`

- `opPnlUsd(op)` (`frontend/src/utils/assetPnl.js:76-84`): para `Cupón`/`Amortización` con `currency='ARS'` y `fx_to_usd>0` devuelve `pnl_usd / fx`; el resto pasa crudo. Es un **parche de lectura**, no de datos: el comentario (`:60-70`) explica que convertirlo en el endpoint haría que editar un cupón le reescriba el monto en la DB, y que de 276 cupones marcados ARS sin FX ~125 ya están bien.
- `ratePct(total, cost, costIncomplete)` (`:122-126`): devuelve `null` (no un número inventado) si no hay costo, si está incompleto, o si `|total| > cost·MAX_PNL_TO_COST`.
- `computePnlByKey(positions, operations, brokers, classify)` (`:139`): suma no realizado + realizado + renta. El costo de una venta se **despeja** de `pnl_usd / (pnl_pct/100)` porque `cost_basis_consumed` está 100 % NULL y `entry_price` está en moneda nativa con un bug abierto de monedas cruzadas (`:17-25`).
- `assetClass.js`: `classifyAsset(position, brokers)` (`:218`) resuelve **primero el mercado** (BYMA vs exterior, con el mismo criterio estructural que la valuación) y recién después el ticker, porque `CEDEARS_LIST` solapa 96 símbolos con `STOCKS_US`. `'otro'` es un resultado válido. El encabezado (`:6-12`) enumera los 4 clasificadores que se contradecían antes: `classifyAssetType` (insightsModel), `classifyAssetBucket` (profileAllocations), `inferType` (tickers) — **los tres siguen existiendo y siguen exportados**.
- `assetSector.js`: `classifySector` (`:164`) apoya el sector sobre la clase; solo acciones/CEDEARs/ETFs pasan por `SECTOR_META`. "Sin dato" es una porción explícita, no un relleno.

### 3.9 `tradeStats.js` (76)

`esTradeCerrado(op)` (`:45-53`): excluye `['Compra','Dividendo','Interés']` y los prefijos `['Conversión','CONVERSION']`, y exige `pnl_usd != null`. `computeTradeStats(ops)` (`:64-76`) devuelve `winRate` como **fracción** (0..1) y **`null` con 0 trades**, nunca 0.

El propio encabezado (`:16-22`) declara que **no es la única definición viva del frontend**. Las cuatro, re-verificadas una por una (las líneas que cita ese comentario quedaron desactualizadas):

| dónde | predicado de tipo | denominador | línea real hoy |
|---|---|---|---|
| `utils/tradeStats.js` | excluye Compra/Dividendo/Interés/Conversión, exige `pnl_usd != null` | **todos** los trades cerrados (los ceros cuentan) | `:45-53`, `:64-76` |
| `pages/Insights.jsx` | mismo predicado, copiado a mano (`isTradeOp`) **+ descarta micro-trades (`Math.abs(pnl_usd) < 1,5`)** | `wins + losses` (los ceros NO cuentan) | `:1880-1886`, `:1896`, `:1907-1921` |
| `pages/AssetDetail.jsx` | **ninguno** — `operations.filter(o => o.pnl_usd != null)` | `wins + losses` | `:168-173` |
| `hooks/useMonthlyData.js` | `isTradeOp` copiado a mano (sin exigir `pnl_usd != null`) | no calcula win rate, alimenta `pnlRealized` | `:48-54` |
| `utils/profileMatch.js` | mismo predicado copiado a mano, sobre `sells` | `computeStyleCoherence` | `:446-453` |

El número de `Insights.jsx` es el que viaja en el payload de la IA, así que unificarlo cambia lo que dice el análisis — el comentario lo marca como decisión de producto, no limpieza.

### 3.10 Renta fija: `bondPricing` → `bondSchedule` → `bondMeta`/`bondSchedulesAR`

- `bondPricing.js` es matemática pura con contratos de unidad estampados (`:9-16`): precio y cashflows siempre "por 100 VN". `dayCountFraction` (`:52`), `computeAccrued` (`:135`), `yieldToMaturity` (`:186-291`) — bracket `[-0.5, 5.0]` con auto-expansión (máx 8), 10 iteraciones de bisección gruesa, 50 de Newton acotado al bracket, 80 de bisección fina; devuelve `{ytm, converged, method, iterations}` y `converged:false` con `method:'bracket_failed'` / `'max_iter'` en vez de un número inventado.
- `bondSchedule.js` orquesta: `generateSchedule(ticker, options)` (`:132`) soporta forma rica (`couponSchedule` step-up, `amortSchedule`, `issueDate`, `dayCount`) y legacy (`couponRate` escalar + `amortStart`/`amortCount`), default de day-count `'ACT/365.25'`.
- `bondSchedulesAR.js` tiene los 6 cronogramas del canje 2020 (`CANJE_2020_2029/30/35/38/41/46`) con la advertencia de que los períodos **se solapan** en el endpoint y `Array.find` matchea el primero a propósito.
- `bondCashflowFx.js`: `suggestBrokerAmount` (`:58`) convierte el pago teórico del bono a la moneda del broker con el TC **de la fecha del pago**, y el encabezado aclara que "es el BRUTO teórico convertido a un dólar de referencia" y por eso se ofrece editable, nunca como default.

### 3.11 `fx.js` / `fxPanel.js` / `crypto.js`

- `lookupHistoricalDolar(bench, year, month, liveTc, now)` (`frontend/src/utils/fx.js:26-48`): cascada de 5 pasos — mes actual → `liveTc`; match exacto `YYYY-MM`; mes más reciente ≤ target (sin fuga de FX futuro); mes más antiguo conocido; `liveTc`. Lee **`bench.dolar_blue`**, o sea el riel BLUE, mientras que la valuación va por MEP (ver §11.4).
- `fxPanel.js`: `deltaRendimiento(sim)` = `rendimiento_despues_pct − rendimiento_antes_pct`; el filtro `'caen'` marca `|Δ| ≥ 50` puntos porcentuales (`:23`, `:48`).
- `crypto.js`: `CRYPTO_SYMBOLS` (`:14-27`, 108 símbolos) está **portado de `backend/main.py:4863`** y `crypto.test.js` garantiza la paridad. `cryptoBrokerFactor` (`:47-52`) devuelve 1 con override, sin cripto, en exchange, o con cualquier rate ≤ 0.

### 3.12 `benchmarkSim.js` (375)

`simulateBenchmark(globalMonthly, priceLookup)` (`:76`) es el núcleo; las variantes lo envuelven: `simulateSp500` (`:117`), `simulateDolarCash` (`:130`, `priceLookup = () => 1`), `simulateArsCash` (`:147`), `computeInflationCumulative` (`:193`), `simulateShv` (`:231`), `simulateGold` (`:241`), `simulateMerval` (`:257`), `simulatePlazoFijoUva` (`:320`). Granularidad **mensual**; devuelven `null` cuando faltan datos.

### 3.13 `bookComposition.js` / `brokerAccounts.js`

- `bookComposition.js`: traduce `/api/advisor/book/composition` al shape de posiciones para reusar **el mismo** `computeClassBreakdown`/`computeSectorBreakdown` del retail (`:6-12`). Lo propio es la torta **por activo**: `assetSlicesFromRows(rows, extraSlices, topN = DEFAULT_TOP_ASSETS /* 12 */)` (`:36`, `:67`), porque un libro de 100 clientes toca ~486 tickers y todos caen bajo el 1,5 % del donut.
- `brokerAccounts.js`: `groupBrokersIntoAccounts` (`:46-83`) arma cuentas **solo por `parent_broker_id`**, nunca parseando el sufijo " · USD"; soporta N patas y emite los huérfanos (hijo con padre borrado) como cuenta propia al final, "igual que hacía `sortBrokersForDisplay`" (nota: **`sortBrokersForDisplay` ya no existe en el repo** [V] — grep sin resultados fuera de ese comentario).

### 3.14 `pendingCashflows.js` / `upcomingEvents.js`

- `detectPendingCashflows(positions, bondOps, skips, options)` (`:98`): cruza cronograma teórico × operaciones registradas × skips manuales, con matching por `(broker, asset)` y tolerancia de fecha `DATE_TOLERANCE_DAYS`. Montos = estimación (cronograma × qty **actual**).
- `upcomingEvents.js`: mezcla los eventos del backend (`normalizeBackendEvents`, `:101`) con los cupones generados en el cliente (`upcomingBondEvents`, `:48`), ventana default 90 días.

### 3.15 Perfil de inversor: `profileMatch` / `profileAllocations` / `profileDashboard`

- `profileMatch.js` (679): 8 cruces (`computeAllocationMatch`, `computeObjectiveCoherence`, `computeHorizonComposition`, `computeDrawdownTolerance`, `computeConcentrationVsProfile`, `computeStyleCoherence`, `computeLiquidityRisk`, `computeReturnExpectation`). Regla declarada (`:11-14`): **nunca generan texto interpretativo** ("deberías", "te conviene"), solo datos crudos. Solo lo usa `Insights.jsx`. **Sin test.**
- `profileAllocations.js`: `deriveProfileCategory` (`:78`) con scoring multi-dimensional; `SUGGESTED_ALLOCATIONS` (`:109`) declarado como "mediana razonable" de Balanz/IOL/Cocos/BBVA/Santander/Galicia/ICBC. **Sin test**, y contiene un `isBondTicker` (`:246`) y un `classifyAssetBucket` (`:276`) que duplican `tickers.js` y `assetClass.js`.
- `profileDashboard.js`: `buildProfileDashboard({cards, positions})` (`:239`) ordena módulos por un score REL determinístico; el encabezado insiste en que "la IA no decide el layout".

### 3.16 `sections.js` / `fundamentalsCompare.js` / `format.js`

- `sections.js` es **espejo de `backend/importing/sections.py`**: `positionSection(assetType, symbol, currency)` (`:35-45`) — `FUND` → FCI; patrón `LETRA_RX = /^[A-Z]\d{1,2}[EFMAYJLGSOND]\d$/` (`:23`, espejo de `maturity._LETRA_RX`) → Letra; `BOND|BONO|ON|LETRA|LECAP` o catálogo → Bono; resto `null`. `normCcy` colapsa `USD`/`USDT` en `USD`.
- `fundamentalsCompare.js`: una métrica es comparable con ≥2 tickers no nulos; el ganador depende de `direction` (`'lower'`/`'higher'`); los empates no cuentan.
- `format.js`: dos convenciones vivas conviviendo — la legacy `fmtUsd`/`fmtArs` ("USD 1.037,74", negativos entre paréntesis, `:42`/`:47`) y la nueva `fmtMoney`/`fmtSigned` ("+$1.037,74 USD", `:62`/`:89`). `usd()` formatea en `en-US` y `ars()` en `es-AR` (`:18`, `:28`). Y una **tercera** familia vive en `contexts/CurrencyContext.jsx` (`fmtMoneyRaw` y compañía, símbolo `$`/`US$`, siempre `es-AR`).

---

## 4. Hooks (`frontend/src/hooks/`)

| hook | qué trae | endpoint(s) | cache / estado |
|---|---|---|---|
| `useMonthlyData.js` (757) | reportes mensuales consolidados | 8 GET en `Promise.all` (`:169-178`) + `/prices` (`:201`) | estado local; se re-dispara con `valuationDollar` (`:216`); `buildMonthlyReports` memoizado (`:227-233`) |
| `usePlanFeatures.js` (157) | tier, límites, `access`, `trial`, `client_ctx` | `GET /plan/features` (`:77`) | **cache módulo-level + localStorage `rendi_plan_features_v1`** (`:32`), dedupe por `_inflight`, invalidación por `refreshPlanFeatures()` (`:61`) con listeners |
| `useFxHistory.js` (220) | serie histórica de blue | `GET /fx-rates?days=3650` (`:65`) | cache módulo-level `_fxCacheData` + **cooldown de reintento de 30 s** ante fallo (`:47-84`); respuesta vacía cuenta como soft-failure |
| `useHistoricalMoney.js` (124) | formateo con FX de la fecha | (usa `useFxHistory` + `useCurrency`) | puro; expone `fxKey` para memoizar |
| `useAlerts.js` (50) | alertas propias + eventos | `GET/POST/PATCH/DELETE /alerts` | estado local; `refresh()` completo después de cada mutación |
| `useAIAnalysis.js` (146) | análisis IA de una pantalla | `POST /ai/analyze` (`:45`, `:92`), `DELETE /ai/cache/{screen}` (`:72`) | `autoload` al montar; cap **1** follow-up por análisis (`MAX_FOLLOWUPS_PER_ANALYSIS`, `:23`) |
| `usePfRollup.js` (39) | plazos fijos agregados por moneda | `GET /plazos-fijos` (`:13`) | recarga por `reloadKey`; `pfUsd(totals, tc)` convierte con fallback duro 1415 (`:35`) |
| `useReportsTimeline.js` (70) | timeline de reportes agrupada por año | `GET /reports/timeline?broker&months&modo&moneda` (`:34`) | re-fetch por cada dep; `yearGroups` memoizado (`:51-61`) |
| `usePushNotifications.js` (175) | Web Push end-to-end | `GET /push/vapid-public-key` (`:121`), `POST /push/subscribe` (`:134`), `DELETE /push/subscribe` (`:152`), `POST /push/test` | registra `/sw.js` con scope `/` (`:24`, `:91-100`) |
| `useLastVisit.js` (110) | delta "¿qué cambió desde tu última visita?" | ninguno | localStorage `rendi_lastvisit_<key>` (`:23`); escribe en un effect, nunca durante el render |
| `useCurrencyChoice.js` (70) | mapea los 2 ejes del contexto a 3 opciones (MEP/CCL/Pesos) | ninguno | puro sobre `useCurrency` |
| `useIsMobile.js` (35) | breakpoint | ninguno | `matchMedia(max-width: 767px)` (`MOBILE_BREAKPOINT_PX = 768`, `:12`) |
| `useCountUp.js` (71) | interpolación rAF del hero | ninguno | respeta `prefers-reduced-motion` (`:14-17`); arranca en 0 al montar |
| `usePullToRefresh.js` (99) | gesto pull-to-refresh | ninguno | `THRESHOLD 80` / `MAX_PULL 140` / `RESISTANCE 0.55` (`:19-21`) |

Notas verificadas:
- **`useMonthlyData` no usa `buildPriceSymbols`.** Construye su propia lista a mano (`frontend/src/hooks/useMonthlyData.js:191-198`): brokers ARS → `.BA`; brokers no-ARS → `.BA` si `isArUsdBroker`, si no ticker pelado. Es exactamente la reimplementación que `buildPriceSymbols` (`frontend/src/utils/valuation.js:478-494`) dice haber venido a matar; los otros 4 consumidores (`Dashboard.jsx:183`, `Positions.jsx:577`, `PositionsMobile.jsx:556`, `HomeMobile.jsx:94`) sí lo usan.
- `usePlanFeatures` documenta explícitamente que el tier en localStorage **no** sustituye el gate del backend (`:29-31`).
- `usePullToRefresh` mete `pullDistance` en el array de deps del effect (`:96`), o sea reengancha los tres listeners de touch en cada frame del gesto. **[I]** Funciona, pero es un add/removeEventListener por movimiento de dedo.
- Hay un hook más fuera de la carpeta: `frontend/src/components/fundamentals/useWatchlist.js`.

---

## 5. Contexts (`frontend/src/contexts/`)

Orden de anidamiento (`frontend/src/App.jsx:392-415`):
`ThemeProvider → AuthProvider → CurrencyProvider → PrivacyProvider → CoachDrawerProvider → [RouteTracker + Layout]`, y dentro de `Layout`, **solo para usuarios logueados**, `AlertsProvider → AdvisorProvider` (`:339-340` mobile, `:369-370` desktop).

### 5.1 `AuthContext.jsx` (291)

- `DEMO_USER` hardcodeado con `tier:'pro'`, `id:0`, `demo:true` (`:14-28`).
- `mapMeToUser(me)` (`:35-62`) centraliza el mapeo de `/auth/me`: tier, `subscription_*`, crédito (`credit_active_until`, `credit_days_remaining`, `credit_remaining_usd`, `credit_anchor_*`) y `access_mode` (`'authorized'|'credit_only'|'cancelled'|'free'`).
- Bootstrap: hidratación optimista desde `localStorage.rendi_user` (`:84`) + `GET /auth/me` en un effect con deps `[]` (`:90-114`). Si falla: limpia y `setUser(null)`.
- `login(_legacyToken, name, extra)` (`:127-181`): el primer argumento **se ignora** (la cookie ya la puso el backend). Limpia contexto de cliente (`:131`) y registro de brokers (`:137`), y termina **awaiteando `refreshUser()`** (`:176-180`) — el comentario `:155-175` explica por qué: el `user` optimista no traía `tier`, y Sidebar/Dashboard/RendiAI/Guia conmutan modo asesor con `user?.tier === 'advisor'`, así que un asesor entraba y veía la app de usuario común.
- `logout()` (`:210-274`): `trackEvent`, `clearClientContext`, `setBrokersRegistry([])`, `POST /auth/logout` (o `disableDemoMode` si era demo), barrido de **todas** las claves `rendi_*` de localStorage salvo `rendi_theme` y `rendi_ai_discovered` (`:246-259`), barrido de todas las `rendi_*` de sessionStorage (`:264-271`) — el comentario dice que ahí vivía el chat y "en un asesor: nombres de clientes, AUM, colas".
- Expone `{user, isDemo, login, logout, exitDemo, updateUser, refreshUser, bootstrapped}`.

### 5.2 `AdvisorContext.jsx` (64) — "estoy viendo a mi cliente X"

Es un **espejo React** del estado módulo-level de `api.js`; quien realmente inyecta el header es `api.js`. Hidrata de `getClientContext()` (`:26`), escucha `storage` para sincronizar pestañas (`:32-36`), y `enterClient`/`exitClient` llaman `refreshPlanFeatures()` porque **el tier efectivo cambia con el contexto** (lente Pro sobre el cliente vs tier real del asesor) (`:38-51`). Fuera del provider devuelve `FALLBACK` con no-ops (`:60-63`).

La persistencia real es `localStorage.rendi_client_ctx` escrita por `frontend/src/utils/api.js:42-49`, con un listener propio en `api.js:59-67` que **sí** contempla `e.key === null` (un `localStorage.clear()`), cosa que el de `AdvisorContext` no hace (ver §11.6).

### 5.3 `CurrencyContext.jsx` (354) — el toggle global

Guarda **tres** preferencias, todas per-device en localStorage:

| clave | valores | default | línea |
|---|---|---|---|
| `rendi_display_currency` | `'USD'` \| `'ARS'` | `USD` | `:24`, `:57-65` |
| `rendi_valuation_dollar` | `'mep'` \| `'ccl'` | `mep` | `:25`, `:69-76` |
| `rendi_cost_basis` | `'today'` \| `'purchase'` | **`purchase`** | `:26`, `:102-109` |

- `pickFinancialRate(dolar, pref)` (`:46-54`): `rate = c => c?.medio ?? c?.venta`; `pref==='ccl' ? (ccl||mep) : (mep||ccl)` y como último recurso `blue`. Usa el **medio** porque "Cocos/IOL valúan al medio, no a la punta de compra; antes usábamos `.venta` y la cartera daba ~0,7 % menos que el broker".
- Fetch propio de `/dolar` al montar y **cada 5 minutos** (`:129-144`), con dep `[valuationDollar]`. Publica `dolar` crudo y `tcValuacion`.
- `DEFAULT_TC_VALUACION = 1415` (`:27`) es el valor con el que se renderiza ARS hasta que llega el primer `/dolar`.
- Cómo se propaga: `useCurrency()` (`:189-203`, con fallback USD si se usa fuera del provider), `useMoneyFormat()` (`:304-325`), y los helpers puros `fmtMoneyRaw` (`:214`), `fmtConvertedRaw` (`:234`), `fmtConvertedCompactRaw` (`:248`), `fmtMoneyCompactRaw` (`:270`), `fromUsd` (`:338`), `fromArs` (`:350`).
- **Qué convierte**: el input canónico es **USD**; `isArs && tcValuacion>0 → usdValue × tcValuacion`. Símbolo `$` para ARS y `US$` para USD. Es conversión al TC **actual**: el propio encabezado (`:11-14`) avisa que la línea del chart en ARS se recalcula al TC de hoy, no al de cada snapshot, y que eso es "limitación conocida del MVP". Para histórico hay que usar `useHistoricalMoney()`.
- Consumidores: 20 archivos usan `useCurrency`.

### 5.4 `AlertsContext.jsx` (81)

Envuelve `useAlerts()` y le suma los avisos del libro del asesor: `GET /advisor/alerts` (`:28`) para todos los usuarios, con `catch → 0` ("401/403 = no es asesor: sin badge"). `unseenCount` = propios + del libro (`:68`). `markSeen()` pega a los dos endpoints (`:39`, `:45`). Refresh al volver a la pestaña con throttle de 60 s (`:53-65`). Fuera del provider degrada a `{unseenCount: 0, markSeen: noop}` (`:80`).

### 5.5 `PrivacyContext.jsx` (35) — sí, es el modo "ocultar montos"

Estado booleano `hidden` persistido en `localStorage.rendi_privacy` (`:5`, `:8-17`). Expone `usePrivacy()` y un componente `<PrivacyMask>` que reemplaza el hijo por `••••••` (`:31-35`); para strings el patrón es `{hidden ? '••••••' : value}`.

**Alcance real [V]**: solo lo consumen **tres** páginas — `pages/Dashboard.jsx` (`:27`, `:84`, `:816`, `:822`), `pages/Positions.jsx` (`:36`, `:97`, `:1862`, `:2216-2224`) y `pages/HomeMobile.jsx` (`:35`, `:48`, `:359-419`). Ver §11.5.

### 5.6 `ThemeContext.jsx` (47) — bloqueado en dark

`LIGHT_MODE_LOCKED = true` (`:20`). El provider siempre expone `dark: true` y un `toggle` que es no-op (`:36-41`); ni siquiera persiste `rendi_theme` mientras el lock esté puesto (`:30-32`). El comentario `:5-19` documenta que el barrido de tokens V2 eliminó las clases `dark:` y que reabrir light mode exige paleta light en Tailwind + reintroducir prefijos + validar WCAG AA. Único consumidor de `useTheme`: `frontend/src/components/Sidebar.jsx`.

### 5.7 `CoachDrawerContext.jsx` (49)

Ya no hay drawer: `open(question)` guarda la pregunta en el contexto, llama `markAIDiscovered()` y **navega a `/ai`** (`:29-33`). `toggle` es alias de `open` por back-compat (`:37`). La página consume la pregunta una sola vez con `consumeInitialQuestion()`. 10 archivos usan `useCoachDrawer`.

---

## 6. `App.jsx` (416) y `main.jsx`

- **Split eager/lazy** (`:26-123`): eager solo el flujo no autenticado (`Login`, `Landing`, `VerifyEmail`, `ResetPassword`, `ClaimAccount`, `AdvisorAccessRequest`, `ReportPublic`); todo lo demás es `React.lazy`. El comentario dice que el bundle main bajó de ~600 KB a ~150 KB gzip.
- **Dos árboles de rutas**: uno para `!user` (`:276-332`, público: landing, legales, SEO landings, blog, guía, `/planes`, `/i/:token`, `/claim`, `/acceso`, catch-all → `Login`) y otro autenticado (`AppRoutes`, `:180-270`, catch-all → `/`). Tres rutas están duplicadas a propósito en ambos árboles (`/i/:token`, `/acceso`, legales/SEO/blog/guía) porque tienen que resolver con y sin sesión.
- **Redirects de la reestructuración**: `/objetivos`, `/insights`, `/comportamiento`, `/reportes`, `/eventos`, `/noticias`, `/config/notificaciones` (`:205-230`).
- `RouteTracker` (`:131-159`) vive **fuera** del gate de sesión para que GA4/Meta midan también al visitante sin login; monta `useAutoUpdate(location.pathname)` (`:143`).
- `AdvisorLandingRedirect` (`:161-178`): si `user.tier === 'advisor'` y no hay `clientCtx`, `/` redirige a `/dashboard`.
- Dos shells (mobile `:337-362`, desktop `:368-389`) con el mismo contenido: `AlertsProvider > AdvisorProvider > [ClientContextBar, DemoBanner, TrialBanner, Suspense(AppRoutes)]`. El comentario `:346-351` cuenta que `TrialBanner` había quedado solo en el shell desktop.
- `main.jsx` monta `ErrorBoundary > HelmetProvider > BrowserRouter > ToastProvider > App` e instala el handler **reactivo** de chunk viejo (`:41-86`): 7 patrones de error, reload con cache-buster `?_t=` y loop guard de 10 s en `sessionStorage.rendi_chunk_reload_at`.

---

## 7. `utils/demo.js` (3223) — el modo demo

### Qué es [V]

Un backend completo hardcodeado en el cliente. `api.js:78-99` intercepta **todo** request cuando `isDemoMode()`; `handleDemoRequest(method, path, body)` (`frontend/src/utils/demo.js:2646`) devuelve fixtures. El fixture cubre ~18 meses: `BROKERS` (`:94`), `POSITIONS` (`:102`), `OPERATIONS` (`:126`), `PRICES` (`:153`), `PREV_CLOSE` (`:173`), `MONTHLY` (`:255`), `REPORTS_TIMELINE` (`:343`), `BEHAVIORAL_INSIGHTS` (`:697`), `WRAPPED` (`:938`), `DEMO_AI_RESULTS` (`:1070`), `SNAPSHOTS` (`:1606`), `WATCHLIST_BASE` (`:1647`), `BENCHMARKS` (`:1660`), `DOLAR` (`:1715`), `INDICES_STRIP` (`:1724`), `MOVERS` (`:1734`), noticias, eventos, fundamentals, heatmap (`buildHeatmapBlocks`, `:3163`) y un generador de sparkline con `Math.random()` (`buildPriceHistory`, `:3216-3223`). TC demo: `_DEMO_TC_BLUE = 1415` (`:199`).

### Cómo se activa [V]

1. `?demo=1` o `?demo=true` en cualquier URL → `AuthContext` lo detecta en el **inicializador de `useState`** (`frontend/src/contexts/AuthContext.jsx:66-80`), llama `enableDemoMode()`, trackea `demo_mode_started` y limpia el query param con `history.replaceState`.
2. Botón "Probar sin cuenta · Modo demo" en `frontend/src/pages/Login.jsx:251-263`: `enableDemoMode()` + `window.location.href = '/'`.

`enableDemoMode()` escribe `localStorage.rendi_demo_mode = '1'` y borra el overlay (`frontend/src/utils/demo.js:67-72`). `isDemoMode()` (`:62-65`) es simplemente esa lectura. `disableDemoMode()` (`:74-80`) borra el flag, `rendi_token`, `rendi_user` y el overlay.

### Qué se puede modificar [V]

Overlay en `localStorage.rendi_demo_overlay` (`:22`, estructura `{watchlist, positions}`, `:25-31`): agregar/quitar de watchlist y agregar posición manual (ids sintéticos ≥ 9000). Todo lo demás devuelve `blocked()` → `{__demoBlocked:true, message}` (`:84-88`), que `api.js:83-87` convierte en `Error` con `err.demoBlocked = true`. `upload` y `getBlob` tiran error propio antes de tocar la red (`frontend/src/utils/api.js:218-222`, `:256-260`).

### ¿Puede filtrarse a un usuario real? [V] + [I]

**Sí, hay un camino concreto, y es el `return null` de la rama GET.**

- `handleDemoRequest` devuelve `null` en **exactamente un lugar**: `frontend/src/utils/demo.js:2961`, al final de la rama `method === 'GET'`. Todas las demás salidas son objetos, incluido el default `return { ok: true }` de `:3158`.
- `api.js:80` trata `null` como "no hay mock → seguir al fetch real". Y ese fetch real lleva `credentials:'include'` (`:109`).
- Consecuencia: **cualquier GET no mockeado se ejecuta contra producción con la cookie de sesión que el browser tenga**. POST/PUT/PATCH/DELETE no tienen esa salida (nunca devuelven `null`), así que las escrituras sí están cerradas.

Endpoints mockeados: 37 (`/positions`, `/brokers`, `/operations`, `/monthly`, `/snapshots`, `/watchlist`, `/dolar`, `/benchmarks`, `/config`, `/plan/features`, `/alerts`, `/prices*`, `/home/*`, `/events/*`, `/news/*`, `/ai/topics`, `/ai/usage`, `/behavioral/insights`, `/goals*`, `/imports*`, `/reports/timeline`, `/fundamentals/*`, `/insights*`, `/wrapped/*`, `/auth/investor-profile`).

Endpoints que la app pide y **no** están mockeados (verificado cruzando `api.get(...)` de todo `frontend/src` contra la lista de mocks): `/auth/me`, `/advisor/alerts`, `/advisor/clients`, `/advisor/book`, `/advisor/book/composition`, `/advisor/book/detail`, `/advisor/book/history`, `/advisor/book/asset-clients`, `/advisor/groups`, `/advisor/profile`, `/advisor/reports`, `/advisor/radar/events`, `/advisor/radar/news`, `/advisor/data-health`, `/advisor/brief/*`, `/advisor/group-op/prep`, `/plazos-fijos`, `/movements`, `/fx-rates`, `/futures`, `/sections/archived`, `/bonds/cashflow/skips`, `/bond-indices/CER`, `/fci/catalog`, `/pf/banks`, `/tickers/search`, `/me/advisor`, `/me/reset-data/status`, `/wallbit/status`, `/iol/lab/status`, `/push/vapid-public-key`, y los 7 de `/admin/*`.

Los dos escenarios:

1. **Visitante anónimo en demo** → esos GET salen sin cookie, vuelven 401, `api.js:119-128` no redirige porque no hay `rendi_user`, y cada caller los traga (`usePfRollup` catch → `{}`, `useFxHistory` catch → `[]`, `AlertsContext` catch → 0). Sin filtración; solo pantallas vacías y ruido de red contra producción. Esto también significa que **el demo pega al backend real** en cada carga.

2. **Usuario logueado que entra a `?demo=1`** → `enableDemoMode()` corre en el inicializador de `useState`, el bootstrap de `/auth/me` se saltea (`AuthContext.jsx:91`) y el usuario pasa a ser `DEMO_USER`. Pero la cookie sigue viva, así que esos ~30 GET no mockeados devuelven **sus datos reales** dentro de una pantalla que dice "modo demo". Para un asesor es lo más filoso: `/advisor/clients`, `/advisor/book` y `/advisor/radar/*` no tienen mock, o sea que un asesor mostrando el demo en su propia máquina (o compartiendo pantalla) puede exponer el roster real de sus clientes en las superficies que leen esos endpoints. **[I]** — el mecanismo está verificado línea por línea; no verifiqué qué renderiza cada pantalla con esa mezcla.

No hay ningún guard del tipo "si hay sesión, no entres en demo" ni "salí de demo antes de loguear": grep de `isDemoMode` da 6 usos en `frontend/src` (`api.js` ×4, `AuthContext` ×3, `chatSession.js`, `track.js`) y ninguno es ese guard.

**Contención que sí existe [V]**: `track.js:135-136` no reenvía telemetría al backend en demo; `chatSession.js:29` usa una clave de sessionStorage separada (`rendi_chat_demo_v1`) para que el chat del demo no aparezca cuando vuelve el usuario real; `AuthContext:119` desactiva el keep-alive; `enableDemoMode` limpia el overlay al entrar.

---

## 8. `utils/tickers.js` (629) — el catálogo

No es un allowlist de *validación*, es un **catálogo de autocompletado y clasificación**. Composición verificada:

| lista | línea | entradas |
|---|---|---|
| `CRYPTO` | `:5` | 108 |
| `STOCKS_US` | `:45` | 160 |
| `ETFS` | `:104` | 56 |
| `INDICES` | `:139` | 30 |
| `CEDEARS_LIST` | `:162` | 168 |
| `ARG_LIDER` | `:261` | 25 |
| `ARG_GENERAL` | `:278` | 39 |
| `BONDS_AR_SOV_USD` | `:324` | 19 |
| `BONDS_AR_CER` | `:352` | 6 |
| `BONDS_AR_ONS` | `:364` | 18 |
| `BONDS_US_ETF` | `:388` | 8 |
| `POPULAR_TICKERS` | `:470` | 104 |

Derivados: `ARS_TICKERS` (`:402`), `USDT_TICKERS` (`:406`), `BOND_TICKERS` (`:411`), `ARG_STOCK_TICKERS` (`:420`), `CEDEAR_TICKERS` (`:427`), `CEDEAR_ESPECIE_ALIAS = { SI: 'SID' }` (`:435`).

**Dónde manda de verdad** [V]:
- `ARG_STOCK_TICKERS` y `CEDEAR_TICKERS` son las dos únicas listas que consume `valuation.js:2`. `CEDEAR_TICKERS` gatea `holdingHasReliableFundamentals` (`frontend/src/utils/valuation.js:239-243`): en contexto BYMA, si el símbolo no es un CEDEAR reconocido (vía `cedearEspecieBase`), **no se analizan sus fundamentals** — porque yfinance devolvería una empresa homónima al azar (`SID` → Companhia Siderúrgica, `SI` → Shoulder Innovations).
- `BOND_TICKERS` → `isBondTicker` (`:454`), y `isBondPosition` (`:460`) lo amplía con `asset_type === 'BOND'` para bonos importados fuera del catálogo.
- `POPULAR_TICKERS` + `inferType` (`:589-598`) alimentan los buscadores. `inferType` tiene su propio orden: lista corta de cripto hardcodeada → `.BA` = cedear → regex de bonos `/^(AL\d|GD\d|AE\d|TX\d|TZ|T2X|S\d|T\d{2}|PARY|DICY|PAR|DIC)/` → `POPULAR_TICKERS` → **`'stock_us'` por defecto**.
- `ASSET_TYPE_META` (`:606`) y `assetTypeMeta` (`:618`) son la fuente única del badge de tipo en las 5 superficies de búsqueda.

**Qué pasa con un ticker que no está** [V]:
- **No se rechaza nada.** `frontend/src/components/AddPositionFlow.jsx:56` y `:64` definen dos categorías `freeText: true` — "Letras" (validada por el patrón `isLetraTicker`) y **"Otro"** con el hint literal *"No está en la lista — lo cargás vos"*, que abre `StepOtroPicker` (`:678`), un formulario donde el usuario describe el activo (`TIPOS_OTRO`, `:667`).
- La consecuencia se paga después: `classifyAsset` devuelve `'otro'` (decisión explícita, `frontend/src/utils/assetClass.js:30-35`); `inferType` cae a `'stock_us'` en silencio; y si es un símbolo BYMA que no es CEDEAR reconocido, `holdingHasReliableFundamentals` lo excluye del análisis de calidad.
- El **precio** no depende del catálogo: depende de `priceSymbol` + `broker.currency`, así que un ticker desconocido en broker ARS se pide como `TICKER.BA` a yfinance. Si no cotiza, cae a costo (P&L 0) por el camino de `trustMktValue`.

---

## 9. `utils/autoUpdate.js` (227) — recarga a bundle nuevo

Mecánica [V]: Vite inyecta `__BUILD_ID__` (SHA del commit de Vercel, `frontend/vite.config.js:11-19`, `:43-45`) y un plugin escribe `dist/version.json` con el mismo id (`:25-41`, `writeBundle` en `:30`); `vercel.json` sirve ese archivo con `no-store`. El cliente pollea `/version.json?t=<now>` con `cache:'no-store'` y `credentials:'omit'` (`frontend/src/utils/autoUpdate.js:42-59`) y compara.

| parámetro | valor | línea |
|---|---|---|
| throttle de chequeo | 60 s | `:25` |
| guard de reload por versión | 60 s | `:26` |
| intentos máximos por versión | 2 | `:27` |
| "reapertura" | pestaña oculta > 10 min | `:28` |
| poll de fondo | 15 min | `:29` |
| gracia de arranque | 20 s | `:30` |
| rutas donde nunca recarga | `/login`, `/verify-email`, `/reset-password`, `/onboarding`, `/billing` | `:33` |

Momentos seguros (`applyUpdateIfPending`, `:147-163`): no si el usuario está escribiendo (`isUserBusy`, `:93-104`), no en ruta crítica, no dentro de los 20 s de vida salvo `immediate`, y no si se agotó el budget. El guard vive en `sessionStorage.rendi_update_guard` y es **fail-closed**: si sessionStorage tira (iOS privado), `reloadBudgetOk` devuelve `false` y no recarga (`:139-141`). El reload navega con `?_v=<now>` (`:154-158`).

Disparadores (`useAutoUpdate`, `:169-226`): al montar, `visibilitychange`, `focus`, `pageshow` con `e.persisted` (el resume de la PWA en iOS), poll cada 15 min, y cada cambio real de `pathname` (`:221-226`). En dev (`BUILD_ID === 'dev'`) todo es no-op.

Complementa —no reemplaza— el handler reactivo de `frontend/src/main.jsx:41-86`.

---

## 10. `utils/safeUrl.js` (52) — para qué se creó

El propio encabezado lo dice (`frontend/src/utils/safeUrl.js:1-16`): **React no escapa el esquema de un `href`**, así que una URL que viene del backend o de un feed externo (RSS de noticias, links de tickers) con `javascript:alert(...)` o `data:text/html,...` ejecuta al hacer click. O sea: se creó por un vector de XSS por URL en contenido no controlado.

- `safeExternalUrl(url)` (`:26-39`): parsea con `new URL`, deja pasar solo `http:` y `https:`, y devuelve `'#'` (link inerte) ante cualquier otra cosa o URL inválida.
- `isSafePaymentUrl(url)` (`:41-51`): exige `https:` **y** hostname en allowlist cerrada de Rebill — `app.rebill.com`, `checkout.rebill.com`, `pay.rebill.com`, `app.rebill.dev`, `checkout.rebill.dev` (`:18-24`). Se usa antes de `window.location.href = initPoint`, o sea protege contra un open-redirect hacia el checkout.

Consumidores: `components/TopNewsCard.jsx`, `pages/News.jsx`, `pages/Planes.jsx`, `components/home/NewsPreview.jsx`. **Sin test propio.**

---

## 11. Hallazgos, rarezas y contradicciones

### 11.1 🔴 Demo mode: la puerta de atrás del `return null` [V]
`frontend/src/utils/demo.js:2961` deja pasar **todo GET no mockeado** al backend real con la cookie de sesión (`frontend/src/utils/api.js:80`, `:109`). Son ~30 endpoints, incluidos los 15 de `/advisor/*`. Y nada impide activar el demo estando logueado (`frontend/src/contexts/AuthContext.jsx:66-80`). Las escrituras sí están cerradas (ninguna rama de POST/PUT/DELETE devuelve `null`).

### 11.2 🔴 `useMonthlyData` no usa el constructor canónico de símbolos [V]
`frontend/src/hooks/useMonthlyData.js:191-198` reimplementa la lista de `/prices` a mano, en vez de `buildPriceSymbols` (`frontend/src/utils/valuation.js:484`). Los agujeros que el docstring de `buildPriceSymbols` enumera (lotes `costInPesos` en cuenta USD que la valuación lee por `.BA`; cripto en sub-broker "· USD" que la valuación lee spot pero esa lista pide `.BA`) siguen abiertos ahí. El síntoma esperable es el ya conocido: la posición cae a costo **en silencio** (P&L 0, variación "—") solo en Reportes mensuales.

### 11.3 🟠 Cinco valuaciones por lote conviviendo [V]
El docstring de `valuePositionLot` (`frontend/src/utils/valuation.js:504-509`) admite que existían cinco implementaciones y que la nueva "todavía NO la consume nadie más". Hoy `valuePositionLot` lo usa `Positions.jsx`, `valueEquityLot` lo usan los dos componentes de Fundamentals, y `AssetDetail.jsx` (`valueLot`, ver `:160`) / `PositionDetailMobile.jsx` / `PositionsMobile.jsx` siguen con las suyas. Lo mismo pasa con el win rate (§3.9): cinco lugares, tres denominadores distintos.

### 11.4 🟠 Dos rieles de FX en el mismo frontend [V]
La valuación va por **MEP/CCL medio** (`pickFinancialRate`, `frontend/src/contexts/CurrencyContext.jsx:46-54`), pero el FX histórico va por **blue**: `useFxHistory` lee `rows[].blue` (`frontend/src/hooks/useFxHistory.js:26-36`) y `lookupHistoricalDolar` lee `bench.dolar_blue` (`frontend/src/utils/fx.js:31`). `monthlyReturnArs` avisa explícitamente que **el riel tiene que ser el mismo en toda la cadena** o "mete un salto espurio del tamaño del cambio de la brecha" (`frontend/src/utils/insightsModel.js:546-548`). Los nombres de las variables ya delatan la mezcla: `convertSeriesToArs` prioriza `p.fxToUsdBlue` (`frontend/src/utils/evolution.js:158`).

### 11.5 🟠 El modo privacidad no cubre la Cartera en mobile [V]
`usePrivacy` se consume en `Dashboard.jsx`, `Positions.jsx` y `HomeMobile.jsx` — nada más. Pero `/posiciones` renderiza `Cartera` → `Positions` → y `Positions.jsx:88-89` hace `if (isMobile) return <PositionsMobile />` **antes** de tocar el contexto. `PositionsMobile.jsx` no importa `PrivacyContext`. O sea: el usuario prende "ocultar saldos" en desktop, queda persistido en `rendi_privacy`, y en el celular la Cartera muestra todos los montos igual. Tampoco lo cubren Análisis, Reportes, Operaciones, Novedades ni Objetivos.

### 11.6 🟡 El listener de `storage` de `AdvisorContext` no cubre `clear()` [V]
`frontend/src/utils/api.js:61` contempla `e.key === null` (un `localStorage.clear()` desde otra pestaña) y suelta el header; `frontend/src/contexts/AdvisorContext.jsx:33` solo compara `e.key === 'rendi_client_ctx'`. Tras un `clear()` en otra pestaña, esta pestaña deja de mandar el header pero sigue mostrando la banda "estás viendo a <cliente>".

### 11.7 🟡 `1415` hardcodeado en 20 sitios [V]
`DEFAULT_TC_VALUACION` en `frontend/src/contexts/CurrencyContext.jsx:27`, y además: `utils/diagnostics.js:630`, `hooks/usePfRollup.js:35`, `hooks/useFxHistory.js:104`, `hooks/useMonthlyData.js:154`/`:156`/`:176`/`:188`, `components/MonthlySummary.jsx:60`/`:94`, `pages/Dashboard.jsx:64`/`:192`, `pages/Positions.jsx:104`/`:241`/`:249`, `pages/PositionsMobile.jsx:325`/`:629`/`:1617`/`:1635`/`:1647`, `pages/Insights.jsx:325`/`:404`, `pages/Goals.jsx:66`, `pages/AssetDetail.jsx:151`, `pages/FirstInsight.jsx:84`, `pages/Events.jsx:103`, `pages/Planes.jsx:129`, y **`pages/Landing.jsx:271`, que imprime el texto literal "al blue 1.415"** en la página pública. Con el dólar por encima de ese valor, cualquier render que caiga al fallback subvalúa los pesos y la landing muestra una cotización vieja como si fuera de hoy.

### 11.8 🟡 La suscripción push no se limpia al desloguear [V]
`logout()` (`frontend/src/contexts/AuthContext.jsx:210-274`) barre localStorage y sessionStorage pero **no** llama a `unsubscribe()` de `usePushNotifications` ni a `DELETE /push/subscribe`. La suscripción del service worker (`/sw.js`, scope `/`) queda viva en el browser, asociada server-side al usuario anterior. **[I]** En una máquina compartida, el siguiente usuario recibe las notificaciones del anterior hasta que alguien la revoque.

### 11.9 🟡 `refreshPlanFeatures()` en el logout dispara un GET que va a dar 401 [V]
`AuthContext.jsx:273` llama `refreshPlanFeatures()` al final del logout, y esa función termina en `return _fetch()` (`frontend/src/hooks/usePlanFeatures.js:72`), que hace `GET /plan/features` sin cookie. Es un 401 garantizado por cada logout. Inofensivo pero ruidoso.

### 11.10 🟡 Tres familias de formateo de plata [V]
`utils/format.js` legacy (`fmtUsd` → `"USD 1.037,74"`, negativos entre paréntesis), `utils/format.js` nueva (`fmtMoney` → `"+$1.037,74 USD"`) y `contexts/CurrencyContext.jsx` (`fmtMoneyRaw` → `"US$1.038"` / `"$1.500.000"`). Las tres están vivas y las tres se usan en pantallas distintas. Además `usd()` formatea en `en-US` (separador de miles `,`) y `ars()` en `es-AR` (separador `.`), así que en la misma pantalla conviven las dos convenciones de puntuación.

### 11.11 🟢 `CurrencyProvider` fetchea `/dolar` sin sesión [V]
El provider está fuera del gate `if (!user)` (`frontend/src/App.jsx:396`), así que su effect (`frontend/src/contexts/CurrencyContext.jsx:129-144`) pega a `/api/dolar` al montar y cada 5 min **también en la Landing pública**. Sumado al keep-alive de `/api/health` cada 4 min de los logueados, son dos timers permanentes contra Railway.

### 11.12 🟢 `RESOLUCION_DIARIA_DIAS` y la rotación en UTC [V]
`selectDiagnostics` rota los diagnósticos por `dayOfYearKey` calculado con `getUTC*` (`frontend/src/utils/diagnostics.js:947-953`): en Argentina la grilla cambia a las 21:00, no a la medianoche.

### 11.13 🟢 Comentarios que apuntan a código que ya no existe [V]
`frontend/src/utils/brokerAccounts.js:44` y `:80` citan `sortBrokersForDisplay` como referencia de comportamiento; esa función no existe en el repo. Y los punteros con número de línea envejecen mal: `frontend/src/utils/tradeStats.js:19-22` apunta a `Insights.jsx:1310-1325` (hoy es un comentario sobre la resolución del gráfico) y a `AssetDetail.jsx:158-160` (hoy es el bloque de agregados); los cálculos que describe están en `Insights.jsx:1907-1921` y `AssetDetail.jsx:168-173`. Ídem `frontend/src/utils/analytics.js:3` habla de `VITE_GA_MEASUREMENT_ID` pero el ID está hardcodeado en `:37` (`GA_ID = 'G-DQ8LV6YJPP'`), y `frontend/src/main.jsx:12-13` repite la afirmación falsa.

---

## 12. Código muerto verificado

Exports que **no referencia nadie** — ni otro módulo, ni su propio archivo, ni un test:

| símbolo | archivo:línea |
|---|---|
| `ARS_TICKERS` | `frontend/src/utils/tickers.js:402` |
| `USDT_TICKERS` | `frontend/src/utils/tickers.js:406` |
| `tickerName` | `frontend/src/utils/tickers.js:444` |
| `fmtCurrency` | `frontend/src/utils/format.js:52` |
| `groupEventsByAsset` | `frontend/src/utils/upcomingEvents.js:133` |
| `formatCouponFreq` | `frontend/src/utils/bondMeta.js:170` |
| `assetClassMeta` | `frontend/src/utils/assetClass.js:154` |

Exports **usados solo por sus tests** (no son basura, pero tampoco los toca la app):

| símbolo | archivo:línea |
|---|---|
| `isArStock` | `frontend/src/utils/valuation.js:14` — su propio docstring explica que dejó de rutear precios |
| `groupPendingByBond` | `frontend/src/utils/pendingCashflows.js:165` |
| `groupEventsByDate` | `frontend/src/utils/upcomingEvents.js:142` |
| `METRIC_ORDER` | `frontend/src/utils/fundamentalsCompare.js:31` |

**Ningún archivo de `utils/`, `hooks/` o `contexts/` está huérfano.** Los que tienen un solo importador (y por lo tanto son candidatos a moverse al lado de quien los usa): `insights.js`, `insightsMetrics.js`, `diagnostics.js`, `diagnosticsRotation.js`, `diagnosticoTemplate.js`, `profileMatch.js` (los seis → `pages/Insights.jsx`), `tradeStats.js` (→ `Operations.jsx`), `fxPanel.js` (→ `Admin.jsx`), `bookComposition.js` (→ `advisor/BookComposition.jsx`), `pendingCashflows.js` (→ `Positions.jsx`), `bondCashflowFx.js` (→ `BondCashflowModal.jsx`), `fundamentalsCompare.js` (→ `CompareView.jsx`), `profileDashboard.js` (→ `ProfileDashboard.jsx`), `aiStructured.js` y `stripMarkdown.js` (→ `AICoach.jsx`), `autoUpdate.js` (→ `App.jsx`).

## 13. Cobertura de tests

39 de los 49 módulos de `utils/` tienen `.test.js`. **Sin test**: `api.js` (cubierto parcialmente por 4 tests laterales: `apiRetry`, `errorMessage`, `gatewayMessage`, `chatStream`), `demo.js` (3223 líneas), `bondMeta.js`, `metaPixel.js`, `analytics.js`, `track.js`, `positionsDiscovered.js`, `profileAllocations.js`, `profileMatch.js` (679 líneas de lógica financiera), `routePrefetch.js`, `safeUrl.js`, `support.js`, `watchlistEvents.js`, `insights.js`, `autoUpdate.js`.

De los hooks solo 4 tienen test (`useMonthlyData`, `useFxHistory`, `useHistoricalMoney`, `useCurrencyChoice`); de los contexts, solo `CurrencyContext` (+ `currencyFormat.test.js`). `AuthContext`, `AdvisorContext`, `AlertsContext` y `PrivacyContext` no tienen ninguno — y son los cuatro que deciden identidad, contexto de cliente y qué se muestra.

`frontend/vite.config.js:68-70` fija `test.environment: 'node'` (`:69`): **no hay jsdom ni testing-library**, y por eso varios módulos documentan que la lógica se extrajo del componente justamente para poder testearla (`bondCashflowFx.js:10-14`, `diagnosticsRotation.js:8-10`, `useCurrencyChoice.js:5-7`).

## 14. Lo que no encontré

- `frontend/src/utils/apiRetry.js` — **no existe**. Solo está el test con ese nombre; la implementación es `gatewayRetry.js`.
- Un guard que impida activar el modo demo con sesión abierta, o que salga del demo al loguear — **no encontrado**.
- Un `unsubscribe` de push en el logout — **no encontrado**.
- Uso de `import.meta.env` para configuración (base URL, IDs de analytics, feature flags): **no encontrado** más allá de `import.meta.env.DEV` en `frontend/src/utils/valuationGuards.js:19`. GA4 y Meta Pixel tienen los IDs hardcodeados (`analytics.js:37`, `metaPixel.js:22`), con el motivo escrito en el código ("Vercel no inyectaba bien los env var VITE_").
- Cualquier lectura de `.env` desde el frontend — **no encontrado**.
