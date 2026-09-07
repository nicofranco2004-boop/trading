## Frontend — Home, Cartera, Posiciones

Auditado sobre `origin/main` `b74f450f` (2026-09-05). Todo lo marcado `[V]` está verificado leyendo el código con la cita a mano; `[I]` es inferencia mía y digo de qué me agarro.

---

## 0. Mapa de rutas: qué se monta REALMENTE en cada URL

Las rutas viven en `frontend/src/App.jsx:180-270`. Son **las mismas en desktop y mobile** — el árbol de rutas no cambia, cambia el *shell* (`App.jsx:337-362` mobile vs `App.jsx:368-390` desktop) y algunas páginas se bifurcan adentro con `useIsMobile()`.

| URL | Elemento en `App.jsx` | Componente que termina renderizando | Cita |
|---|---|---|---|
| `/` | `<Home />` | `Home.jsx` en desktop, `HomeMobile.jsx` si `useIsMobile()` | `App.jsx:186`, `Home.jsx:28-29` |
| `/posiciones` | `<Cartera />` | `Cartera.jsx` → tab `posiciones` → `Positions.jsx` → `PositionsMobile.jsx` si mobile | `App.jsx:190`, `Cartera.jsx:144`, `Positions.jsx:87-91` |
| `/posiciones?tab=objetivos` | `<Cartera />` | `Cartera.jsx` → `Goals.jsx` | `App.jsx:190`, `Cartera.jsx:145` |
| `/dashboard` | `<Dashboard />` | `Dashboard.jsx` → `AdvisorDashboard` si `tier==='advisor'` y no hay `clientCtx`, si no `PersonalDashboard` | `App.jsx:204`, `Dashboard.jsx:53-58` |
| `/objetivos` | `<Navigate to="/posiciones?tab=objetivos" replace />` | redirect | `App.jsx:205` |
| `/activo/:ticker` | `<AssetDetail />` | `AssetDetail.jsx` (responsive, una sola implementación) | `App.jsx:193` |
| `/posiciones/:id` | `<PositionDetailMobile />` | `PositionDetailMobile.jsx` (rotulado mobile-only pero la ruta existe en los dos shells) | `App.jsx:266` |
| `/buscar` | `<MobileSearch />` | `MobileSearch.jsx` | `App.jsx:265` |
| `*` | `<Navigate to="/" replace />` | catch-all a Home | `App.jsx:267` |

**Nada quedó huérfano entre Cartera / Positions / Dashboard, pero la historia dejó cicatrices** `[V]`:

- El comentario de cabecera de `Cartera.jsx:8-16` todavía describe **3 tabs** (`Posiciones` / `Evolución` / `Objetivos`) y explica por qué "Evolución" muestra el Dashboard entero. Esa tab ya no existe: `TABS` tiene sólo dos entradas (`Cartera.jsx:37-40`) y el Dashboard volvió a ser página propia (`Cartera.jsx:35-36`).
- Los links viejos `?tab=evolucion` / `?tab=composicion` se redirigen a `/dashboard` en un `useEffect` de mount (`Cartera.jsx:56-59`), con un guard extra en el efecto de sincronización de URL para que no le pise el `navigate` (`Cartera.jsx:71`) — la carrera de efectos está documentada en el propio comentario.
- `TAB_ALIASES` quedó como **objeto vacío** (`Cartera.jsx:47`) y se sigue consultando en tres lugares (`Cartera.jsx:62`, `:83`) sin poder matchear nada. Código muerto benigno.
- `App.jsx:194-196` tiene un comentario huérfano ("Dashboard vuelve a ser página propia…") flotando entre dos rutas que no son la del Dashboard.

**Redirect del asesor** `[V]`: `AdvisorLandingRedirect` (`App.jsx:161-178`) saca al `tier === 'advisor'` de `/` y lo manda a `/dashboard` **siempre** que caiga ahí sin `clientCtx`. O sea: para un asesor, `/` (la Home de mercado) es inalcanzable en su propio nivel; adentro de un cliente sí funciona.

---

## `/` → `frontend/src/pages/Home.jsx` (desktop)

- **Qué muestra** `[V]`: es un ensamblador de 85 líneas, sin lógica propia. Header con eyebrow "Mercado" + `AnalyzeButton` + `SearchBar` (`Home.jsx:34-43`), y después, en orden: `OnboardingChecklist` (`:49`), `IndicesStrip` (`:52`), `Heatmap` con `defaultMarket="sp500"` (`:56`), `PersonalLayer` (`:60`), `MoversRail` (`:66`), `Watchlist` (`:71`) y una grilla de 2 columnas con `NewsPreview` + `EventsPreview`, cada uno envuelto en `AskAIAbout` (`:74-81`).
- **De dónde saca los datos** `[V]`: **Home.jsx no hace ni una sola llamada a la API.** Cada hijo fetchea lo suyo:
  - `IndicesStrip` → `GET /home/indices` (`components/home/IndicesStrip.jsx:27`)
  - `Heatmap` → `GET /home/heatmap?market=<market>` (`components/home/Heatmap.jsx:170`)
  - `PersonalLayer` → `GET /home/personal` (`components/home/PersonalLayer.jsx:44`)
  - `MoversRail` → `GET /home/movers?market=<market>` (`components/home/MoversRail.jsx:57`)
  - `Watchlist` → `GET /watchlist`, `DELETE /watchlist/:symbol` (`components/home/Watchlist.jsx:32`, `:64`)
  - `NewsPreview` → `GET /news/market?limit=3` (`components/home/NewsPreview.jsx:31`)
  - `EventsPreview` → `GET /events/popular?days=14` (`components/home/EventsPreview.jsx:50`)
  - `OnboardingChecklist` → `GET /auth/investor-profile` + `GET /imports` (`components/home/OnboardingChecklist.jsx:105-108`)
  - `SearchBar` → `GET /positions`, `GET /watchlist`, `POST/DELETE /watchlist` (`components/home/SearchBar.jsx:72`, `:103`, `:185`, `:189`)
  - `AssetQuickView` (modal que abren Heatmap/Movers/Watchlist) → `GET /prices?symbols=…`, `GET /watchlist`, `POST/DELETE /watchlist` (`components/home/AssetQuickView.jsx:40-62`)
  - `AssetMiniChart` → `GET /prices/history?symbol=…&period=…` (`components/home/AssetMiniChart.jsx:48`)
- **⚠️ Cálculos en el cliente**: prácticamente ninguno en el eje plata. Lo único es formateo y colorización de porcentajes (`IndicesStrip.jsx:7-18`, `MoversRail.jsx:12-16`) y el **treemap del Heatmap**, que hace el squarify a mano sin librería (`Heatmap.jsx:1-8` documenta la decisión) con bins de color fijos (`Heatmap.jsx:17-32`). Los números de mercado vienen todos del backend.
- **Estado/contexto**: Home.jsx no consume ningún context directo. Sus hijos sí: `OnboardingChecklist` usa `AdvisorContext` y `CoachDrawerContext` (`OnboardingChecklist.jsx:37-39`, `:44-47`).
- **Gating por plan**: **no encontrado** en Home.jsx ni en `components/home/*` — grep de `usePlanFeatures|UpgradeModal|feature_blocked` sobre esa carpeta no devuelve nada. La Home no tiene paywall.
- **Variante mobile**: `Home.jsx:28-29` hace `if (isMobile) return <HomeMobile />`. **La divergencia es total: no comparten un solo cálculo.** Ver ficha de HomeMobile.
- **Rarezas** `[V]`: `OnboardingChecklist` se apaga entero adentro de la cuenta de un cliente (`OnboardingChecklist.jsx:139-141`), con el motivo escrito ("mezclaba estado del asesor con datos del cliente"). El comentario de cabecera de `Home.jsx:3-10` numera 7 bloques pero el render tiene 8 (agregó el checklist como "0" en `Home.jsx:46-49`).

---

## `/` (mobile) → `frontend/src/pages/HomeMobile.jsx`

Acá sí hay motor propio: 530 líneas que **recalculan la cartera entera en el browser**.

- **Qué muestra** `[V]`, en el orden del render: `OnboardingChecklist` (`:292`), hero de balance con toggle de moneda y ojo de privacidad (`:296-341`), panel de sparkline 30d con delta del período (`:344-392`), strip 2×2 de KPIs — P&L Día / P&L Mes / Capital aportado / Mejor activo (`:396-432`), `BenchmarksLine` (`:437-445`), "Hoy en tu cartera" = `PersonalLayer` (`:447-461`), Heatmap S&P (`:463-469`), Movers (`:471-477`), Watchlist (`:479-482`), Noticias y Eventos apilados (`:484-494`).
- **De dónde saca los datos** `[V]` — todo en `loadAll` (`HomeMobile.jsx:60-86`):
  - `GET /positions` (`:63`), `GET /monthly` (`:64`), `GET /brokers` (`:65`), `GET /dolar` (`:66`), `GET /snapshots?days=30` (`:67`) en un `Promise.all`.
  - Después `GET /prices?symbols=<lista>` (`:96`), con la lista armada por `buildPriceSymbols(pos, bkrs)` (`:94`).
  - `GET /benchmarks` **fuera del critical path**, fire-and-forget (`:85`), con el motivo documentado: 3 fetches externos que en cache miss tardan 20-45 s.
  - `usePfRollup()` agrega un `GET /plazos-fijos` (`hooks/usePfRollup.js:13`).
- **⚠️ Cálculos hechos en el cliente** — esto es el corazón del asunto:

| Número en pantalla | Fórmula | Cita |
|---|---|---|
| **Hero "Tu cartera"** | `Σ computeBrokerValue(...).value` sobre todos los brokers, **más** `pf.valueUsd`; ×`tcValuacion` si el toggle está en ARS | `HomeMobile.jsx:110-117`, `:102`, `:329-333` |
| `% histórico` (chip arriba del hero) | `(Σvalue − Σinvested) / Σinvested` — **sin el PF** | `HomeMobile.jsx:114-115`, `:318-322` |
| `compareValue` (base de todas las comparaciones) | Se recalcula **todo al MEP estricto** cuando el riel del user es CCL, para no comparar live-CCL contra snapshot-MEP | `HomeMobile.jsx:125-131` |
| `aportado` (capital neto) | `capital_inicio` del primer `monthly` global + `Σ(deposits − withdrawals)` | `HomeMobile.jsx:135-142` |
| Sparkline 30d + su delta | `buildPortfolioValueSeries(snapshots, 30, live, aportado)`; delta = `Δ(value − netDeposited)` entre puntas; **`deltaPct` divide por `first.valueUsd`, no por el retorno inicial** | `HomeMobile.jsx:154-171` |
| P&L Mes | `computeReturnDelta(snapshots, {sinceDate: 1º del mes})` | `HomeMobile.jsx:187-192` |
| P&L Día | `computeDailyPnl(snapshots, …)` | `HomeMobile.jsx:198-204` |
| "Mejor activo" | Loop manual por posición con **5 ramas de valuación** (costInUsd en broker ARS, CEDEAR/·USD por `.BA÷MEP`, resto por ticker), factor cripto, clamp `trustMktValue`, y `% = (value − invested)/invested` | `HomeMobile.jsx:208-266` |

  Ese loop de "mejor activo" es una **sexta reimplementación de la matriz de valuación** (las otras: `computeBrokerValue`, `Positions.calcUSDT/calcARS`, `PositionsMobile.enriched`, `AssetDetail.valueLot`, `PositionDetailMobile`). Los comentarios (`:212-256`) documentan que se fue arreglando *a posteriori* cada vez que divergió de la Cartera.

- **Estado/contexto** `[V]`: `CurrencyContext` (`:47`) y `PrivacyContext` (`:48`). No usa Auth, Advisor ni Alerts.
- **Gating por plan**: **no encontrado**.
- **Divergencias contra el Home desktop** `[V]`:
  1. Desktop **no muestra ningún número de la cartera del usuario**: no hay hero de balance, ni P&L día/mes, ni capital aportado, ni sparkline, ni `BenchmarksLine`. Mobile sí. Es paridad **invertida**: el "chequeo rápido" mobile trae más datos personales que el desktop.
  2. Desktop no llama `/positions`, `/monthly`, `/brokers`, `/dolar`, `/snapshots`, `/prices` ni `/benchmarks`; mobile llama las siete.
  3. El toggle de moneda de mobile es un **botón propio en el hero** (`HomeMobile.jsx:334-340`), no el `CurrencySwitcher` del shell.
  4. El ojo de privacidad vive en el hero mobile (`:302-308`); en el Home desktop no hay.
- **Rarezas** `[V]`:
  - **Imports sin usar**: `fmtUsd`, `fmtArs` y `ars` de `utils/format` (`HomeMobile.jsx:40`) y el componente `Eyebrow` (`:31`) no se usan en ninguna parte del archivo — la home mobile define su propio `fmtNumber` local (`:527-530`), que formatea siempre en `en-US` incluso cuando la moneda es ARS (`:331`).
  - **Deps incompletas de `useMemo`** `[V]`: `totals` usa `costBasis` (`:111`) pero **no lo declara en las deps** (`:117`); idéntico en `totalsMep` (`:128` vs `:130`). Efecto: si el usuario cambia "Costo en dólares" en `/config`, el `% histórico` de la home mobile queda con el valor viejo hasta que cambie otra dep (precios, dólar, posiciones). `[I]` — el hero (valor) no se ve afectado porque `costBasis` sólo mueve el `invested`.
  - El mensaje de fallback del sparkline arrastra un aviso enorme (`:376-383`) explicando que el copy anterior era **falso para 168 de 174 usuarios** medidos en producción; el texto viejo sigue vivo como rama `else` (`:390`) para cuando `diagnosticoSinMedicion` no dictamina nada.
  - `pfUsd(usePfRollup(), tcValuacion)` llama el hook adentro de la expresión (`:102`). Es legal (top-level del componente) pero es fácil de romper.

---

## `/posiciones` → `frontend/src/pages/Cartera.jsx`

- **Qué muestra** `[V]`: un tab strip de **dos pills** (`Posiciones` / `Objetivos`, `Cartera.jsx:37-40`, `:110-132`) y abajo el componente de la tab activa, lazy (`Cartera.jsx:32-33`, `:137-146`). No dibuja nada más: no tiene hero, ni KPIs, ni datos.
- **De dónde saca los datos**: **ninguna llamada a la API.** Es sólo ruteo de tabs.
- **⚠️ Cálculos en el cliente**: ninguno.
- **Estado/contexto**: `useSearchParams` / `useLocation` / `useNavigate`. Ningún context de la app.
- **Gating por plan**: ninguno acá; el gating vive adentro de `Positions`/`Goals`.
- **Variante mobile**: **no hay** — `Cartera.jsx` no consulta `useIsMobile()`, así que **el tab strip de pills se dibuja igual en el celular**, arriba del header sticky de `PositionsMobile`.
- **Rarezas** `[V]`:
  - `page-shell-xwide` cuando la tab es `posiciones`, `page-shell-wide` si no (`Cartera.jsx:102`).
  - El comentario de cabecera describe una arquitectura de 3-4 tabs que ya no existe (`:8-23`).
  - `markPositionsDiscovered()` se dispara con sólo ver la tab (`:95-97`) — el paso 2 del onboarding se tilda por **descubrimiento**, no por cargar una posición.
  - Tres `useEffect` con `eslint-disable` de `exhaustive-deps` (`:59`, `:79`, `:89`) coordinando el mismo estado (`tab` ↔ `?tab=`).

---

## Tab "Posiciones" (desktop) → `frontend/src/pages/Positions.jsx` (4.484 líneas)

`Positions()` es un fork de 5 líneas: `if (isMobile) return <PositionsMobile />` (`Positions.jsx:87-91`). Todo lo que sigue es `PositionsDesktop` (`:93`).

### Secciones internas del render (en orden)

| # | Bloque | Cita |
|---|---|---|
| 0 | Early return: `brokers.length === 0` → `PageHeader` + `BrokerManager` + `EmptyState` "Sumá tu primer broker" | `:1674-1697` |
| 1 | `PageHeader` "Tu cartera en vivo" + 3 CTAs (Registrar compra / Registrar venta / Cash) + `ExportCsvButton` | `:1798-1835` |
| 2 | `PendingCashflowsBanner` — inbox de cobranzas de bonos pendientes | `:1840-1847` |
| 3 | `SplitRatioBanner` — CEDEARs con split sin ajustar | `:1851` |
| 4 | **HERO** "Tu cartera hoy": valor + ojo de privacidad + chips (P&L, Invertido, N brokers, "incluye renta fija / plazos fijos") | `:1858-1906` |
| 5 | Comentario: *"Banner de variación diaria deshabilitado"* | `:1908-1909` |
| 6 | `BrokerManager` — cards por broker con valor y P&L nativos | `:1914` |
| 7 | Barra de filtros: buscar activo, filtro por broker, orden, "Ver lotes", densidad Compacto/Cómodo, "Limpiar", contador "X de Y" | `:1920-1968` |
| 8 | Empty state FR-02 (hay brokers, no hay posiciones) con CTA a cargar o `/imports` | `:1972-1998` |
| 9 | `StalePricesNotice` (sólo si `hasAnyPosition`) | `:2002` |
| 10 | **Loop de secciones por cuenta/broker** — una card con header + tabla + `tfoot` por sección | `:2004-2777` |
| 11 | Empty state de filtros sin coincidencias | `:2784-2790` |
| 12 | `RentaFijaSections` — bonos/letras/FCI cross-broker | `:2794-2803` |
| 13 | `FuturosGroup` | `:2807` |
| 14 | `PlazosFijosGroup` + `PfFormModal` | `:2810-2817` |
| 15 | Modales: `add-flow`, `add`/`edit`, `edit-group`, `cashflow`, `sell`, `sell-empty`, `edit-picker`, `sell-selector`, `cash-menu`, `convert`, `BondCashflowModal` | `:2819`, `:2829`, `:2845`, `:2854`, `:2936`, `:2951`, `:2984`, `:3043`, `:3139`, `:3223`, `:3234` |

**No hay tabs adentro de Positions** — las "tabs" son las de `Cartera.jsx`. Lo que sí hay son **cuatro ejes de estado de vista**, todos client-side:

1. `filterAsset` (texto) / `filterBroker` (key de sección) / `sortBy` (6 opciones, `:78-85`).
2. `showAllLots` + `expandedTickers` — agregado por ticker vs desglose por lote (`:163-164`, `:1230-1241`).
3. `compact` — densidad de tabla, persistida en `rendi_pos_density` (`:167-176`).
4. `cuentasSeparadas` — unificar/separar el par `Broker` + `Broker · USD`, persistido en `rendi_cuentas_separadas` (`:189-200`).
5. `detailBrokers` — el toggle "Detalle" por sección, que agrega columnas auxiliares (`:145`, `:2033`).

### Estructura de una sección de broker

`displaySections` (`:1730-1779`) construye, sin `useMemo` **a propósito** (el comentario en `:1725-1729` explica que un hook ahí se saltearía en el primer render y rompería el orden de hooks):
- cuenta con dos patas no separada → **una** sección con `isPair: true` y `patas` = padre + sub-broker;
- si no → una sección por broker.

Cada sección dibuja `Header` (`:2138-2233`) con: nombre coloreado, badge(s) de moneda, badge "sub-broker", botón **unificar/separar** pegado al nombre (`:2170-2183`, con el motivo escrito: en la toolbar "era el sexto botón de una fila y no lo encontraba nadie"), botón "Crear sub-broker USD" para brokers ARS sin par (`:2189-2197` → `POST /brokers/:id/usd-sibling`, `:1016`), toggle "Detalle", botón "+ Agregar", y chips Valor / Invertido / P&L% / TC MEP.

**Dos árboles de tabla**, no uno `[V]`:
- rama ARS **o** `isPair` (`:2242`) — superset de columnas: `Activo · 30D · Cantidad · Precio prom. · Actual · [Invertido] · [TC Compra] · [Inv. USD] · Valor · P&L · [P&L USD] · Var. día · ⋮` (`:2250-2262`). Las tres entre corchetes sólo salen con `showDetail` y, las de TC/USD, además con display en ARS.
- rama USD (`:2561`) — `Activo · 30D · Cantidad · Precio prom. · Actual · [Invertido] · Valor · P&L · Var. día · ⋮` (`:2569-2578`).

La columna `Activo` es sticky-left y la de acciones sticky-right (`:1566-1579`).

### De dónde saca los datos

`loadAll` (`Positions.jsx:454-478`) dispara un `Promise.all` de **siete** llamadas:

| Endpoint | Línea | Para qué |
|---|---|---|
| `GET /positions` | `:457` | las filas |
| `GET /config` | `:458` | fallback de `tc_mep`/`tc_blue` |
| `GET /brokers` | `:459` | secciones + `setBrokersRegistry` (`:468`) |
| `GET /dolar` | `:460` | `tcValuacion`, `tcCedear`, `tcCripto` |
| `GET /snapshots?days=30` | `:461` | **nada — ver Rarezas** |
| `GET /operations` | `:462` | se filtra a Cupón/Amortización para el detalle de bonos (`:471`) |
| `GET /bonds/cashflow/skips` | `:463` | pagos marcados "no aplica" |

Después `fetchPrices` (`:571-590`): `GET /prices?symbols=…` (`:580`) y, best-effort, `GET /prices/prev-close?symbols=…` (`:587`). Refresco cada **90 s** de precios + `/dolar` (`:424-440`, `REFRESH_MS` en `:47`), más un listener de `rendi:portfolio-changed` que recarga todo (`:434-435`).

Escrituras: `POST /bonds/cashflow` (`:343`), `POST /bonds/cashflow/skip` (`:392`), `PATCH /positions/group` (`:705`) con `POST /positions/group/undo/:token` (`:714`), `PUT/POST /positions` (`:777`, `:779`), `DELETE /positions/:id` (`:812`) con `POST /operations/undo/:token` (`:820`), `POST /positions/sell` (`:888`), `POST /conversions` (`:998`), `POST /brokers/:id/usd-sibling` (`:1016`), `POST /cash/flow` (`:1030`), `GET /bond-indices/CER` lazy al expandir un bono CER (`:276`), y `GET /prices?symbols=<uno>` dentro de `PositionFormModal` para autocompletar el precio (`:4076`).

### ⚠️ Cálculos hechos en el cliente

**Todo el eje plata de esta pantalla se computa en el browser.** El backend devuelve lotes crudos y precios; los números que el usuario lee salen de acá:

| Número | Fórmula | Cita |
|---|---|---|
| **`tcValuacion`** (el dólar de toda la pantalla) | `pickFinancialRate(dolar, valuationDollar) \|\| config.tc_mep \|\| config.tc_blue \|\| 1415` | `:241` |
| `tcCedear` | alias de `tcMep` = `tcValuacion` | `:242`, `:253` |
| `tcMepStrict` | `dolar.mep.medio ?? dolar.mep.venta ?? config.tc_mep ?? 1415` — **no sigue el toggle MEP/CCL**, para que el badge "MEP" de los bonos no mienta | `:249` |
| `tcCripto` | `dolar.cripto.venta` | `:257` |
| **`totals`** | `Σ_brokers computeBrokerValue(positions, prices, b, tcValuacion, tcCedear, tcCripto, costBasis)` | `:1587-1599` |
| `totalsToday` | lo mismo con `costBasis` forzado a `'today'` | `:1607-1615` |
| **`heroValue`** (el número grande) | `totals.value + pfValueUsd` | `:1652` |
| `heroValueArs` | `(totalsToday.value + pfValueUsd) × tcValuacion` — **no** `heroValue × tc` | `:1664` |
| `pfValueUsd` | `pfTotals.USD.valor + pfTotals.ARS.valor / tcValuacion`, reportado por `PlazosFijosGroup` vía `onTotals` | `:1650`, `PlazosFijosGroup.jsx:33-47` |
| Valor/P&L de una **fila** | `calcRowUSDT`/`calcRowARS`: si la fila agrega ≥2 lotes, **suma lote por lote** (`sumRowUSDT`/`sumRowARS`), si no `calcUSDT`/`calcARS` | `:1383-1393` |
| `calcUSDT` | 3 ramas: `costInPesos` → `.BA ÷ tcCedear`; CEDEAR/`·USD` → `.BA ÷ tcCedear`; resto → `prices[ticker]`, todo × `cryptoBrokerFactor` y clampeado por `trustMktValue` | `:1263-1311` |
| `calcARS` | `costInUsd` → `usdLotValue`; resto → `priceArs × qty`, con `invUsd` ruteado por `costBasisRate` | `:1321-1365` |
| `calcRowCuenta` | fila que **fusiona monedas**: suma `valuePos` lote por lote; `priceLocal = valueUsd / qty` (derivado, no leído de un símbolo) | `:1419-1477` |
| `routedInvUsd` | costo USD **por lote** (cada uno a su `tc_compra` en modo `purchase`) — no dividir el costo sumado por un solo TC | `:1248-1254` |
| `dayVarOf` / `dvFor` | `(precio actual − prev_close) × qty`, con ruteo `.BA` para CEDEAR/`·USD`/`costInPesos` y factor cripto | `:1528-1560` |
| Subtotal por sección | `computeBrokerValue` **por pata**, sumado en USD; la pata pesos se recompone tomando el peso **nativo** de las patas ARS y derivando ×tc sólo la pata dólar | `:2040-2063` |
| Var. día del broker | suma de `dvFor` por lote, acumulada en USD cuando la sección es un par | `:2069-2095` |
| Orden de filas | `_rowSortKeys` + `_posComparator`, con cash siempre al final | `:1043-1100` |
| Agregación por ticker | `aggregateAndSort` agrupa por `(asset, moneda)` — o sólo por `asset` en cuenta unificada — y arma `_buildAgg` | `:1198-1225`, `:1134-1179` |

### Estado/contexto

`useCurrency()` → `currency` (renombrado `displayCurrency`), `setTcValuacion`, `valuationDollar`, `costBasis` (`:96`). `usePrivacy()` → `hidden`, `toggle` (`:97`). `useToast()`, `useNavigate()`, `useFxHistory(tcValuacion)` (`:245`). **No** usa Auth, Advisor, Alerts ni CoachDrawer.

Publica su `tcValuacion` al `CurrencyContext` en un efecto (`:267-269`) para que las pantallas que sólo formatean no refetcheen `/dolar`.

### Gating por plan

- `ExportCsvButton resource="positions"` en el header (`:1832`): free ve el botón, el click abre `UpgradeModal` sin llamada de red (`components/plan/ExportCsvButton.jsx:30-36`).
- Alta de broker: no hay gate en el frontend — el backend responde 403 y `BrokerManager` abre el `UpgradeModal` (`components/BrokerManager.jsx:71-78`).
- El resto de la pantalla (posiciones, bonos, PF, futuros, renta fija) **no tiene gating**.

### Rarezas

- 🔴 **`GET /snapshots?days=30` es una llamada muerta** `[V]`: se fetchea (`:461`), se guarda (`:470`) y se usa sólo en el memo `daily` (`:1624-1645`), que **no se renderiza en ningún lado** — el banner que lo consumía está deshabilitado con un comentario (`:1908-1909`). `grep -n "\bdaily\b"` devuelve una sola línea, su propia declaración. Una request por page-load y un memo que corre en cada cambio de precio, para nada.
- **Imports sin usar** `[V]`: `pct` de `utils/format` (`:30`) y `flattenAccounts` de `utils/brokerAccounts` (`:16`) — ninguno aparece en el resto del archivo.
- **Import circular** `[V]`: `Positions.jsx:44` importa `PositionsMobile`, y `PositionsMobile.jsx:32` importa `{ PositionFormModal, SellModal, EMPTY_POS, today }` de `./Positions`. `[I]` — como el import de `PositionsMobile` es estático (no lazy), en mobile **se descarga y parsea el chunk de las 4.484 líneas del desktop igual**, aunque no se renderice: el chunk lazy de `Cartera` incluye los dos módulos.
- **`RentaFijaSections`, `FuturosGroup` y `PlazosFijosGroup` reciben `positions` SIN filtrar** (`:2794`): la barra de búsqueda y el filtro por broker no los tocan. Buscar "AL30" filtra las tablas por broker pero la zona Renta Fija sigue mostrando todo.
- El hero muestra un chip **"incluye renta fija / plazos fijos"** (`:1893-1904`) que existe porque *"un usuario nos reportó justamente esa diferencia"*: las tarjetas por broker excluyen la renta fija a propósito (`:2025`, `!isFixedIncome(p)`) y el hero sí la suma, así que **sumar las cards nunca da el número grande**.
- El TC del header en modo ARS se rotula literalmente **"TC MEP"** (`:2227-2231`, texto en `:2229`) aunque el usuario haya elegido CCL — el valor mostrado es `tcValuacion`, que sí sigue el toggle. El hero del Dashboard sí ternariza el label (`Dashboard.jsx:828`).
- `_ccyDeLote` (`:1111-1127`) documenta que **cinco `INSERT INTO positions` del backend omiten la columna `currency`**, así que todo el efectivo nace con `currency NULL` y hay que inferir la moneda por el broker real.
- Comentarios que son cicatrices de bugs de plata reales y verificables en el código: filas que sumaban `USD 64.147,88` sobre un total de `USD 56.582,51` por usar dos tipos de cambio distintos (`:1313-1320` y `:1376-1379`), un cupón de `$95.000` que se convertía en `US$118 millones` por multiplicar en vez de dividir el `fx_to_usd` (`:515-523`).

---

## Tab "Posiciones" (mobile) → `frontend/src/pages/PositionsMobile.jsx` (2.972 líneas)

### Secciones internas del render

| # | Bloque | Cita |
|---|---|---|
| 1 | Header **sticky** (`top-[88px]`): número grande + toggle USD/ARS propio + punto pulsante de "precios cargando" | `:1184-1217` |
| 2 | Chips de P&L no realizado + Invertido | `:1226-1240` |
| 3 | Fila de búsqueda + botón "Ver y ordenar" (con badge de ajustes activos) + botón `+` (acciones rápidas) | `:1242-1277` (cierra el `<header>` en `:1278`) |
| 4 | `SplitRatioBanner` | `:1280-1283` |
| 5 | Resumen de ajustes activos + "Quitar" | `:1288-1305` |
| 6 | **Rama A — sin filtro de broker**: `BrokerSection` por cuenta (`:1330`) + `RentaFijaSections` (`:1355`) + `PlazosFijosGroup` (`:1362`) | `:1321-1364` |
| 7 | **Rama B — con filtro de broker**: lista plana `PositionsTable` + `PieDelBroker` | `:1365-1387` |
| 8 | Modales: agregar/editar broker, `add-flow` (lazy), `add`/`edit` (`PositionFormModal` importado del desktop), `sell` (`SellModal` del desktop), `cashflow`, `PfFormModal`, `UpgradeModal`, `ActionsSheet`, sheet "Ver y ordenar", selector de venta | `:1390-1830`, `:2825` |

La tabla mobile es **flex, no grid, y con ancla sticky**: columna `Activo` fija de 118 px y 5 columnas deslizables de 108 px — `Valor · P&L · Hoy · Cantidad · Precio prom.` (`:2079-2087`, geometría explicada en `:2043-2067`). Hay un aviso de una sola vez, `PistaDeScroll` (`:2128-2135`), montado desde `PositionsTable` (`:2207`), persistido en `rendi_cartera_scroll_descubierto` (`:89`), porque medieron que el "asomo" de la próxima columna se ve vacío al estar alineada a la derecha.

Acciones por fila: **pulsación larga** (no swipe — `:2052-2058` documenta que el `overflow-hidden`+`transform` del `SwipeRow` rompía el sticky del ancla). Tap corto navega: `/posiciones/:id` si es lote o cash, `/activo/:ticker` si no (`:2455-2457`).

### De dónde saca los datos

`loadAll` (`PositionsMobile.jsx:510-546`): **tres** llamadas — `GET /positions` (`:517`), `GET /brokers` (`:518`), `GET /dolar` (`:519`). Después, en background y sin bloquear el primer render (`:539-540`): `GET /prices?symbols=…` (`:558`) y `GET /prices/prev-close?symbols=…` (`:560`).

Escrituras: `POST /positions/sell` (`:349`), `POST /cash/flow` (`:377`), `PUT /positions/:id` (`:453`), `DELETE /positions/:id` (`:475`), `POST /brokers` (`:567`), `PUT /brokers/:id` (`:589`), `DELETE /brokers/:id` (`:599`, con `?force=true` en `:618`), `POST /positions` (`:1823`).

### ⚠️ Cálculos hechos en el cliente

| Número | Fórmula | Cita |
|---|---|---|
| `enriched[i]` (valor y P&L de cada lote) | **6 ramas** de valuación escritas a mano, + factor cripto + `trustMktValue`, + `investedUsdDisplay` ruteado por `costBasisRate` | `:653-862` |
| `pnlPct` de una fila | **si el broker es ARS**: `pnlUsdToday / investedUsd` (nativo, mode-independent); si no: `pnlUsd / investedUsdDisplay` | `:791-793` |
| Var. día por fila | `(priceLocal − prev) × qty × f`, con 3 ruteos de símbolo distintos (`.BA`, spot, USD-en-broker-ARS) | `:797-840` |
| **Hero** `total` | `Σ enriched[i].valueUsd` **sobre TODAS las posiciones**, incluida la renta fija | `:1113` |
| `heroValor` | `(total + pfValueUsd)`, ×`tcValuacion` si ARS | `:1131` |
| `heroInvertido` | en ARS suma `investedUsdToday`; en USD suma `investedUsd` (que ya refleja el modo) | `:1126-1130` |
| Pie de sección | `Σ` de las filas **no-lote** (`!p._isLot`) para no doblar el conteo al expandir | `:1927-1936` |
| Pie de vista filtrada | mismo criterio | `:1100-1111` |

### Estado/contexto

Sólo `useCurrency()` (`:104`) y `useToast()`. **No consume `PrivacyContext`** — grep de `usePrivacy|PrivacyMask` sobre el archivo no devuelve nada.

### Gating por plan

`UpgradeModal` en dos lugares: alta de broker (403 del backend, `:573-580`, modal en `:1487`) y export CSV desde el `ActionsSheet` (`:2853-2854`, modal en `:2964`).

### Divergencias desktop ↔ mobile (esto es lo que se pidió explícito)

| Aspecto | `Positions.jsx` (desktop) | `PositionsMobile.jsx` | Cita |
|---|---|---|---|
| **Motor del número grande** | `Σ computeBrokerValue(...)` por broker | `Σ enriched[i].valueUsd` por posición | `:1587-1599` vs `:1113` |
| **Qué entra al total** | `computeBrokerValue` recorre `positions` filtradas por `broker.name` → una posición de un broker borrado/renombrado **no suma** | `enriched` recorre **todas** las posiciones → una posición huérfana **sí suma** | `utils/valuation.js:741` vs `PositionsMobile.jsx:654` |
| **Privacidad (ojo)** | `hidden` + `PrivacyMask` en hero, headers, filas y footers | **no existe**: los importes se muestran siempre, aunque el usuario haya activado "ocultar saldos" en Home o en desktop (el flag es global y persistido en `rendi_privacy`) | `Positions.jsx:1864-1866` vs. ausencia en `PositionsMobile.jsx`; `contexts/PrivacyContext.jsx:5-16` |
| **`StalePricesNotice`** | sí | **no** — mobile ni siquiera lee `prices.__meta` | `Positions.jsx:2002` vs. grep vacío en mobile |
| **Snapshots / variación diaria** | fetchea `/snapshots?days=30` (muerto) | no lo fetchea | `:461` vs. grep vacío |
| **Bonos** | inbox de pendientes (`PendingCashflowsBanner`), detalle expandible (`BondDetailRow`), serie CER lazy, `BondCashflowModal`, skips | **nada de eso**: no fetchea `/operations` ni `/bonds/cashflow/skips` | `:1840`, `:2505`, `:2733`, `:276` vs. grep vacío |
| **Futuros** | `FuturosGroup` | **no se renderiza** — grep de `FuturosGroup` en mobile: vacío | `:2807` |
| **Renta fija** | siempre visible, cross-broker | visible **sólo** en la vista "Todos"; con filtro de broker, la rama `flatList` no excluye `isFixedIncome`, así que los bonos aparecen **inline en la lista** y la zona desaparece | `:2794` vs `PositionsMobile.jsx:1044` (excluye) y `:1080-1087` (no excluye); zona en `:1355` |
| **Plazos fijos** | siempre | sólo en la vista "Todos" — pero `pfValueUsd` **sigue sumando al hero** aunque la sección no se dibuje | `:2810` vs `:1362` y `:1114` |
| **Conversión ARS↔USD** | `ConvertModal` (`POST /conversions`) | no existe | `:3250` |
| **Edición grupal de lotes** | `EditGroupModal` + `PATCH /positions/group` + undo | no existe | `:3492`, `:705` |
| **Toggle de moneda** | usa el `CurrencySwitcher` del shell | tiene **su propio** par de botones USD/ARS en el header sticky | `:1199-1215` |
| **Densidad de tabla** | toggle Compacto/Cómodo persistido | no existe | `:167-176` |
| **Columnas** | 9-12 columnas (superset ARS con TC Compra / Inv. USD / P&L USD) | 5 columnas fijas + ancla | `:2250-2262` vs `:2079-2087` |
| **Refresco automático** | `setInterval` de 90 s (precios + dólar) + listener `rendi:portfolio-changed` | **ninguno**: `useEffect(() => { loadAll() }, [])` y nada más | `:424-440` vs `:215` |
| **Registry de brokers** | `setBrokersRegistry` en `loadAll` | también (`:527`), con un comentario que dice que antes **no se llamaba nunca** y el número dependía de si el usuario había pasado antes por otra pantalla | `:468` vs `:521-529` |

Lo que **sí** comparten `[V]`: la clave de localStorage `rendi_cuentas_separadas` (a propósito, `PositionsMobile.jsx:133-140`), los modales `PositionFormModal`/`SellModal` (importados del desktop, `:32`), `RentaFijaSections`, `PlazosFijosGroup`, `SplitRatioBanner`, `TcMissingBadge` y `buildPriceSymbols`.

---

## `/dashboard` → `frontend/src/pages/Dashboard.jsx` (1.550 líneas)

- **Fork por tier** `[V]`: `Dashboard()` devuelve `<AdvisorDashboard />` si `user.tier === 'advisor'` y no hay `clientCtx`; si no, `<PersonalDashboard />` (`:53-58`). El wrapper existe para que los efectos de carga de cartera **ni se monten** en el caso del asesor.
- **Qué muestra** (`PersonalDashboard`):

| # | Bloque | Cita |
|---|---|---|
| 1 | `PageHeader` "Estado de la cartera" + ojo + `AnalyzeButton` + `ExportCsvButton resource="transactions"` | `:728-762` |
| 2 | `AIDiscoveryBanner` | `:765` |
| 3 | Card "Empezá importando tu historial" si no hay posiciones no-cash | `:767-795` |
| 4 | **HERO**: "Valor actual · USD/ARS" + pill Ganancia/Pérdida total + chip ≈ conversión + chip Aportado + línea de insight | `:802-845` |
| 5 | "¿De dónde sale la ganancia?" — 3-4 `KpiCell`: Capital aportado, P&L realizado, P&L no realizado, y `Diferencia sin explicar` / `Dividendos e intereses` | `:852-956` |
| 6 | "Rendimiento" por horizonte (Hoy / Este mes / Anual) + `ModoRendimiento` + fallback "Todavía no podemos medirlo" | `:964-1033` |
| 7 | `BenchmarksLine` | `:1039-1044` |
| 8 | Chart de evolución (Recharts `AreaChart`) + `RangeTabs` + chip de `periodChange` | `:1046-1201` |
| 9 | `AssetBreakdownBar` + `TopHoldingsPanel` | `:1204-1230` |
| 10 | Dos `CompositionDonut`: por tipo de activo y por sector | `:1242-1299` |
| 11 | Grilla de `BrokerCard` + link "Ir a Cartera" | `:1302-1331` |
| 12 | `UpcomingEventsCard` + `TopNewsCard` | `:1336-1345` |
| 13 | `MonthlyTeaser` | `:1347` |

- **De dónde saca los datos** `[V]` — `loadAll` (`:137-174`):
  - `GET /positions` (`:140`), `GET /monthly` (`:141`), `GET /config` (`:142`), `GET /brokers` (`:143`), `GET /dolar` (`:144`), **`GET /snapshots?days=3650`** (`:145`), `GET /operations` (`:150`).
  - `GET /benchmarks` fire-and-forget (`:173`).
  - `GET /prices?symbols=…` en `loadPrices` (`:186`).
  - `GET /goals/cagr?modo=<certero|estimado>&moneda=<usd|ars>` en su propio efecto, re-disparado al cambiar el modo o la moneda (`:129-135`).
  - `usePfRollup()` → `GET /plazos-fijos`.
  - Refresco cada 90 s de precios + `/dolar` (`:97-105`), y `loadAll` completo en `rendi:portfolio-changed` y en `window.focus` (`:112-121`).
- 🔴 **El Dashboard ESCRIBE en la base** `[V]` — es la única pantalla de esta sección que lo hace sin que el usuario apriete nada:
  - `POST /snapshots` una vez por día (`:478`), gateado por: no estar cargando, tener `lastUpdated`, `totalValuePositions > 0`, **`valuationDollar === 'mep'`** (`:471`), y `priceCoverage >= 0.95` (`:472`, constante en `:461`). Marca el día en `localStorage['rendi_snapshot_date']`. El `catch` marca el día igual ante cualquier `status >= 400` (`:492`), con un comentario que cuenta que el 12/08, con el disco lleno, el reintento sin techo *"convirtió una falla del servidor en una tormenta de escrituras"*.
  - `POST /monthly/sync-unrealized` **una vez por broker más una global** en cada `loadAll` (`:588`, `:590`), con el mismo guard de cobertura. O sea: abrir el Dashboard recalcula y persiste el `pnl_unrealized` del mes en curso.
- **⚠️ Cálculos hechos en el cliente** — el Dashboard es el que más tiene:

| Número | Fórmula | Cita |
|---|---|---|
| **`totalValue`** (el número grande) | `Σ computeBrokerValue(...).value + pf.valueUsd` | `:211-212` |
| `totalCostBasis` | `Σ ....invested + pf.investedUsd` | `:213` |
| `netDeposited` | `capital_inicio` del primer `monthly` global + `Σ(deposits − withdrawals)` + `pf.investedUsd` | `:222-232` |
| **`totalReturnUsd`** (el pill "Ganancia total") | `totalValue − netDeposited` | `:265` |
| `realizedPnl` | `Σ monthly[global].pnl_realized` (suma cruda en USD) | `:242-244` |
| `realizedPnlDisp` (en ARS) | **convert-then-sum**: cada asiento × el FX del último día de su mes (`getHistoricalFx`) | `:250-262` |
| **`accountingGap`** | `(realizedPnl + totalPnl) − totalReturnUsd`, mostrado si `|gap| > 500` | `:291-293` |
| `positionsForInsight` | 5 ramas de valuación por posición + `auditPositions` en dev | `:302-390` |
| `cashForComposition` | cash ARS ÷ `tcCedear`, cash USD tal cual | `:398-408` |
| `priceCoverage` | fracción del **cost basis en USD** de posiciones no-cash que tiene precio real, medida contra `valuationPriceKey` | `:440-459` |
| `evoSeries` | `buildPortfolioValueSeries(snapshots, rangeDays, live, netDepositedPositions)` | `:595-597` |
| `evoSeriesDisplay` | en ARS, cada punto × **su propio FX histórico** (`convertSeriesToArs`) | `:606-609` |
| `periodChange` | `Δ(value − netDeposited)` entre las puntas del rango visible; `%` divide por `first.valueUsd` | `:626-633` |
| `dailyVar` / `monthlyVar` | `computeDailyPnl` / `computeReturnDelta(sinceDate = 1º del mes)` | `:641-650` |
| `cagrVar` | del backend (`/goals/cagr`), **dividido por 100** porque el endpoint devuelve porcentaje y `pctSigned` espera fracción | `:676-693` |
| `AssetBreakdownBar` | consolida por ticker, top 5 + "Otros" | `:1413-1442` |
| `TopHoldingsPanel` | consolida por ticker y **recalcula el `%` agregado** como `pnl/(value−pnl)`, para no quedarse con el `%` del primer lote | `:1491-1513` |
| `compFmt` | los breakdowns siempre vienen en USD; el formateo respeta el toggle × `tcValuacion` | `:430` |

- **Estado/contexto**: `AuthContext` (`:54`), `AdvisorContext` (`:55`), `CurrencyContext` (`:83`), `PrivacyContext` (`:84`). Migración soft del key viejo `rendi_dashboard_currency` al context (`:85-94`).
- **Gating por plan**: `ExportCsvButton resource="transactions"` (`:750-755`) — free ve el botón y le abre el `UpgradeModal`. Nada más.
- **Variante mobile**: **no hay.** `Dashboard.jsx` no usa `useIsMobile()`; el mismo árbol se renderiza en el celular, con las grillas colapsando por Tailwind (`grid-cols-2 lg:grid-cols-4` en `:870`). El chart de Recharts va a `height={300}` fijo (`:1099`).
- **Rarezas** `[V]`:
  - El chip de `periodChange` está **hardcodeado en USD** (`:1070`: `+USD ${usd(...)}`) mientras el resto del bloque respeta el toggle. Si el usuario está en pesos, ese chip queda en dólares.
  - Los colores del chart están hardcodeados en hex (`#1B2230`, `#7C8698`, `#10151F`…, `:1096-1143`) en vez de tokens del design system — el tooltip queda oscuro en tema claro `[I]` (deduzco del `background: '#10151F'` fijo en `contentStyle`).
  - `brokerTotals` se recalcula **en cada render** sin `useMemo` (`:211`), a diferencia de casi todos los otros derivados de la página.
  - El efecto de `sync-unrealized` tiene `eslint-disable exhaustive-deps` con deps `[loading, lastUpdated]` (`:591`) aunque lee `positions`, `prices`, `brokers` y los TCs por closure.
  - El label "P&L realizado" usa `fmtSignedDirect` (valor **ya** en la moneda de display) mientras "P&L no realizado" usa `fmtSigned` (convierte) — dos formateadores contiguos con contratos opuestos (`:889` vs `:905`, definidos en `:711-724`).
  - `MonthlyTeaser` formatea siempre con `usd()` (`components/MonthlyTeaser.jsx:22`) — **no respeta el toggle**.
  - El KPI de descuadre está documentadísimo (`:268-293`): antes decía "Ganancias retiradas" y era **falso**, porque `netDeposited` ya resta los retiros.

---

## `/posiciones/:id` → `frontend/src/pages/PositionDetailMobile.jsx`

- **Qué muestra** `[V]`: top bar con back + logo + ticker + broker (`:205-220`); hero "Valor actual" + P&L (`:222-249`); chart 30 d `AssetMiniChart` (`:252-267`); panel "Detalle" con Cantidad / Precio promedio / Precio actual / Invertido / P/L, o Tipo / Saldo / Equivalente USD si es cash (`:270-326`); historial de operaciones del mismo `(asset, broker)` (`:329-366`). Tres bloques envueltos en `AskAIAbout` con topics `position`, `position.chart`, `position.lots`.
- **De dónde saca los datos** `[V]`: `GET /positions` (`:44`), `GET /brokers` (`:45`), `GET /dolar` (`:46`), `GET /operations` (`:47`), y **un solo** `GET /prices?symbols=<sym>` con la key exacta que la valuación va a leer (`valuationPriceKey`, `:68-70`). La posición se encuentra filtrando el array completo por `id` en el cliente (`:49`) — no hay endpoint por id.
- **⚠️ Cálculos hechos en el cliente**: **la matriz de valuación entera, por sexta vez** (`:110-175`): 6 ramas (`is_cash`, `costInPesos && !isAR`, `costInUsd && isAR`, `isAR`, CEDEAR/`·USD`, else) con `trustMktValue` y `costBasisRate`. Además `avgPriceDisp` = `investedDisp / qty` con ruteo del costo por `costBasisRate` (`:185-189`), y `lotShowsUsd` que decide el rótulo de moneda por la moneda del **costo del lote**, no por la del broker (`:191-197`).
- **Estado/contexto**: `useCurrency()` pero **sólo para `valuationDollar` y `costBasis`** (`:29`).
- 🔴 **No respeta el toggle de moneda** `[V]`: los importes están hardcodeados en dólares — `${Math.round(valueUsd)...}` + `<span>USD</span>` en el hero (`:233-234`), P/L en `USD` (`:300`), "Equivalente USD" (`:317`). Un usuario que puso "Pesos" en el shell ve esta pantalla en dólares.
- **Gating por plan**: ninguno.
- **Variante desktop**: no hay una equivalente — el desktop resuelve el detalle con la fila expandible / `BondDetailRow` en la tabla (comentario en `:3`). Igual **la ruta resuelve en desktop** (`App.jsx:266` está en el árbol común), así que un link pegado en un browser ancho la muestra tal cual, con layout mobile.
- **Rarezas**: sólo es alcanzable para **lotes** y **cash** — el tap de una fila normal en mobile va a `/activo/:ticker` (`PositionsMobile.jsx:2455-2457`).

---

## `/activo/:ticker` → `frontend/src/pages/AssetDetail.jsx`

- **Qué muestra** `[V]`: `BackBar` con logo + nombre + "N brokers" (`:225`); hero Valor actual + P&L no realizado (`:228-247`); chart 30 d (`:249-256`); "Tu operatoria en X" con Costo promedio / Cantidad / Invertido / P&L realizado / Win rate / Mejor trade (`:259-284`); tabla de **lotes abiertos en orden FIFO** con marca "próximo" en el más viejo (`:286-320`); historial de operaciones con badge ganada/perdida (`:322-360`); link a `/fundamentals?ticker=…` si es acción US o CEDEAR (`:362-374`).
- **De dónde saca los datos** `[V]`: `GET /positions`, `GET /brokers`, `GET /dolar`, `GET /operations` (`:127-132`), filtrados en el cliente por ticker (`:133`, `:140`); después `GET /prices?symbols=…` con el set de keys derivadas de `symbolFor` (`:142-145`).
- **⚠️ Cálculos hechos en el cliente**: `valueLot()` — **la séptima copia de la matriz de valuación**, definida como función módulo-level (`:34-97`). El agregado `agg` (`:156-183`) suma `valueUsd`/`investedUsd`/`qty` lote a lote, ordena FIFO por `entry_date`, y calcula `realizedTotal`, `wins`, `losses`, `winRate`, `best`, `worst` **filtrando `operations` por `pnl_usd != null`** (`:169-175`).
- **Estado/contexto**: `useCurrency()` sólo para `valuationDollar` y `costBasis` (`:113`).
- 🔴 **No respeta el toggle de moneda** `[V]`: hero en `$…USD` (`:234-235`), stats en USD (`:263-265`), lotes y ops en USD (`:308`, `:349`).
- **Gating por plan**: ninguno.
- **Variante mobile**: una sola implementación responsive (`:12-13`), `max-w-3xl` centrado (`:224`).
- **Rarezas** `[V]`: el default de `valueLot` es `costBasis = 'today'` (`:34`) aunque el default de la app es `'purchase'` (`contexts/CurrencyContext.jsx:102-109`); acá se pisa siempre pasándolo (`:160`), pero cualquier caller nuevo hereda el default equivocado. El chart usa el símbolo del **primer lote** (`:255`), que en un ticker con lotes en dos brokers puede ser el `.BA` o el US según cuál quedó primero.

---

## `/buscar` → `frontend/src/pages/MobileSearch.jsx`

- **Qué muestra** `[V]`: back + input autofocus + clear, chips de filtro, sección "EN TU PORTFOLIO" y sección de sugeridos, cada fila con logo, badge de tipo y estrella para watchlist.
- **De dónde saca los datos** `[V]`: `GET /positions` (`:54`) para armar los holdings consolidados por símbolo, y `GET /watchlist` (`:71`). El universo de tickers viene de constantes importadas: `POPULAR_TICKERS` de `components/home/SearchBar` y `CEDEAR_SEARCH`/`AR_STOCK_SEARCH`/`US_SEARCH` de `utils/tickers` (`:31-32`).
- **⚠️ Cálculos hechos en el cliente**: consolidación de cantidades por símbolo (`:56-65`) y el matching (`matchesQuery` por tokens, `:93-98`; `matchesFilter`, `:99-102`). Sin plata.
- **Estado/contexto**: `useToast()`. Ninguno de los contexts de la app.
- **Gating por plan**: ninguno.
- 🔴 **Dos bugs verificables** `[V]`:
  1. **El toast de watchlist nunca aparece.** `MobileSearch.jsx:134` y `:136` llaman `toast?.show?.({...})`, pero el context de Toast expone **`push(message, options)`**, no `show` (`components/Toast.jsx:7`, `:34`, `:48`). Con el optional-chaining, la llamada es un no-op silencioso: el usuario agrega a la watchlist y no ve confirmación ni error.
  2. **`pickTicker` no lleva a ningún lado útil.** Navega a `/posiciones#SYMBOL` (`:117`) o `/posiciones?search=SYMBOL` (`:121`), pero ni `Positions.jsx` ni `PositionsMobile.jsx` leen `?search=` ni el hash — `PositionsMobile` sólo parsea `?action=` (`:483-499`) y `Positions` no lee la URL en absoluto (grep de `search`/`useSearchParams`/`window.location` sobre el archivo: vacío). El resultado es que tocar un ticker en el buscador te deja en la Cartera sin filtro. El propio comentario admite que era provisorio: *"Navegar al home para ver detalle? por ahora, navega a posiciones"* (`:119-120`).

---

## El número grande: cuál es exactamente y dónde se computa

**Hay cuatro números grandes distintos, con cuatro fórmulas distintas, y ninguno lo calcula el backend** `[V]`:

| Pantalla | Expresión | Archivo:línea | ¿Suma PF? | ¿Suma renta fija? | ¿Refleja `costBasis`? |
|---|---|---|---|---|---|
| Cartera desktop | `totals.value + pfValueUsd`, con `totals = Σ computeBrokerValue(...)` | `Positions.jsx:1652` (memo en `:1587-1599`) | Sí | Sí (el motor recorre todos los lotes del broker) | El **valor** no; el invertido sí |
| Cartera desktop **en pesos** | `(totalsToday.value + pfValueUsd) × tcValuacion` — recomputado con `costBasis='today'` | `Positions.jsx:1664` (memo en `:1607-1615`) | Sí | Sí | Deliberadamente **no** |
| Cartera mobile | `(Σ enriched[i].valueUsd) + pfValueUsd` | `PositionsMobile.jsx:1131` (suma en `:1113`) | Sí | Sí | ídem |
| Dashboard | `Σ computeBrokerValue(...).value + pf.valueUsd` | `Dashboard.jsx:211-212`, render en `:816` | Sí | Sí | ídem |
| Home mobile | `totals.totalValue + pf.valueUsd` | `HomeMobile.jsx:329-333` (memo en `:110-117`) | Sí | Sí | ídem |

Los cuatro **deberían** dar lo mismo `[I]`. Las diferencias estructurales que encontré y que pueden separarlos:

1. **Desktop/Dashboard/Home usan `computeBrokerValue`** (`utils/valuation.js:740-762`), que filtra `allPositions` por `p.broker === broker.name` — una posición cuyo broker ya no está en la tabla `brokers` **desaparece del total**. **Mobile suma `enriched` completo** (`PositionsMobile.jsx:1113`), así que esa misma posición **sí cuenta**.
2. **El fallback del TC difiere**: desktop cae a `config.tc_mep || config.tc_blue || 1415` (`Positions.jsx:241`), el Dashboard cae a `config.tc_blue || 1415` (`Dashboard.jsx:192`), y mobile/HomeMobile caen directo a `1415` (`PositionsMobile.jsx:629`, `HomeMobile.jsx:99`). Mientras `/dolar` no responde, las cuatro pantallas convierten con números distintos. El comentario de `Positions.jsx:232-239` documenta exactamente este síntoma en su forma anterior (filas al 1.341,71 y pie al 1.521,10, 13,4 % de diferencia **dentro de la misma tabla**).
3. **En pesos, la Cartera desktop recalcula todo a `costBasis='today'`** (`:1607-1615`, `:1664`) y las demás simplemente multiplican por `tcValuacion`.
4. **El Dashboard suma el PF por `usePfRollup`** (su propio `GET /plazos-fijos`, `Dashboard.jsx:209`) mientras la Cartera lo recibe por callback desde `PlazosFijosGroup` (`Positions.jsx:1650`, `PlazosFijosGroup.jsx:33-47`). Son dos cálculos de `computePf` sobre la misma data — coinciden `[I]`, pero en mobile la sección PF sólo se monta en la vista "Todos" (`PositionsMobile.jsx:1357`), así que **filtrar por un broker cambia el número grande**: `pfTotals` queda con el valor del último render que sí montó el grupo, o vacío si el usuario entró filtrado.

---

## El toggle de moneda: dónde vive, cómo se propaga, qué convierte

### Dónde vive

- **La verdad** está en `contexts/CurrencyContext.jsx`, montado en `App.jsx:396` (arriba de todo, incluso del gate de sesión). Tres ejes independientes, los tres persistidos en localStorage:
  - `currency` = `'USD' | 'ARS'` → `rendi_display_currency` (`:24`, `:57-65`)
  - `valuationDollar` = `'mep' | 'ccl'` → `rendi_valuation_dollar` (`:25`, `:69-76`)
  - `costBasis` = `'today' | 'purchase'`, **default `'purchase'`** → `rendi_cost_basis` (`:26`, `:102-109`)
- **El control de todos los días** es `CurrencySwitcher`, fijo en el shell: sidebar desktop (`components/Sidebar.jsx:167`, variante `row` o `mini` según esté colapsada) y barra superior mobile (`components/mobile/MobileTopBar.jsx:86`, variante `chip`). Sólo dos opciones — **USD | Pesos** —, y el dólar de valuación se **informa** debajo con link a `/config?tab=fx` (`CurrencySwitcher.jsx:110-119`), nunca se pisa desde ahí.
- **El control de tres opciones** (`USD MEP · USD CCL · Pesos`) es `CurrencyRail`, y sólo se usa en `pages/Config.jsx:683`. El mapeo entre los dos ejes y las tres opciones vive en `hooks/useCurrencyChoice.js:39-65`, con la regla de que elegir "Pesos" **no pisa** `valuationDollar` (para que el round-trip a USD recupere la elección).

### Cómo se propaga

`[V]` El Provider fetchea `/dolar` al mount y cada 5 minutos (`CurrencyContext.jsx:129-144`) y publica `tcValuacion` + las cotizaciones crudas (`dolar`). Además, **cada página que fetchea `/dolar` por su cuenta le devuelve su TC al context** vía `setTcValuacion` en un efecto: `Dashboard.jsx:199-201`, `Positions.jsx:267-269`, `PositionsMobile.jsx:634-636`, `HomeMobile.jsx:106-108`. `[I]` — o sea que el `tcValuacion` del context es "el último que publicó alguien", y como todos usan el mismo `pickFinancialRate` sobre la misma respuesta, en la práctica coinciden; la ventana de divergencia es el primer render, donde el context vale el default `1415` (`:27`, `:115`).

`pickFinancialRate` (`CurrencyContext.jsx:46-54`) cascadea **el elegido → el otro financiero → el blue**, y toma `medio` antes que `venta` porque *"es lo que muestran los brokers (Cocos/IOL valúan al medio, no a la punta de compra); antes usábamos `.venta` y la cartera daba ~0,7 % menos que el broker"*.

### Qué convierte y qué NO

El propio componente lo documenta (`CurrencySwitcher.jsx:31-44`), y lo verifiqué contra el código de esta sección:

**Convierte** `[V]`: Cartera desktop y mobile (hero, headers, filas, footers), Dashboard (hero, KPIs, chart con FX **histórico** por punto vía `convertSeriesToArs`, donuts, breakdown, top holdings), Home mobile (hero, KPI strip, sparkline).

**NO convierte** `[V]` — hardcodeado en USD:
- `PositionDetailMobile.jsx:233-234`, `:300`, `:317`
- `AssetDetail.jsx:234-235`, `:263-265`, `:308`, `:349`
- `Dashboard.jsx:1070` (el chip de `periodChange` del chart)
- `components/MonthlyTeaser.jsx:22` (usa `usd()` directo)
- `components/FuturosGroup.jsx:24-25` (define su propio `usd()` local)
- Y, según el comentario del switcher (`:34-38`), Métricas → Comportamiento y el detalle del período de Reportes, porque *"esos textos llegan YA FORMATEADOS en USD desde el backend"* (`backend/behavioral.py`, `backend/reporting/builder.py`). **No verifiqué esos dos archivos** — quedan fuera de mi sección.

**Asimetría de rótulo** `[V]`: el Dashboard ternariza el nombre del dólar en el hero (`Dashboard.jsx:828`: `valuationDollar === 'ccl' ? 'CCL' : 'MEP'`), pero el header de sección de la Cartera desktop dice **"TC MEP"** fijo (`Positions.jsx:2229`) aunque el valor mostrado sea el CCL.

**Prop fantasma** `[V]`: `MobileTopBar.jsx:86` pasa `align="right"` a `CurrencySwitcher`, que sólo acepta `variant` y `className` (`CurrencySwitcher.jsx:52`).

---

## `StalePricesNotice` y `TcMissingBadge`: dónde el sistema admite que le falta un dato

### `components/StalePricesNotice.jsx` (52 líneas)

- **Condición que lo dispara** `[V]`: recibe `meta` (= `prices.__meta`, estampado por `/api/prices`) y lista las entradas donde **`m.stale === true`** (`:24-26`). Si `symbols` viene, además filtra a los que están efectivamente en pantalla (`:23`, `:25`). Si no queda ninguno, no renderiza (`:27`).
- **Qué dice**: *"N activos con precio del DD/MM"* + los primeros 6 símbolos (sin el sufijo `.BA`, `:26`) + *"El mercado todavía no publicó su cotización de hoy… así que el total puede quedar corto"* (`:40-48`).
- **Por qué existe** `[V]`, del propio docstring (`:6-13`): yfinance devuelve barras de `.BA` **con volumen pero con el cierre en NaN**; Rendi cae al último cierre válido (que puede ser de dos ruedas antes) y lo mostraba igual que uno de hoy. *"Eso lo descubrió un usuario comparando contra su broker, no nosotros: el número EXISTÍA, sólo que era viejo, y nada en pantalla lo distinguía."*
- **Dónde se usa**: **un solo lugar** — `Positions.jsx:2002`, gateado por `hasAnyPosition`, y **sin pasarle `symbols`** (el comentario en `:2000-2001` argumenta que `__meta` ya viene acotado a los símbolos pedidos, así que filtrar de nuevo sería redundante). Consecuencia: si el usuario filtró por un broker, igual se le avisa por activos que no está viendo — justo lo que el parámetro `symbols` fue diseñado para evitar.
- **Ausente en**: `PositionsMobile.jsx` (grep de `StalePricesNotice`/`__meta`: vacío), `Dashboard.jsx`, `HomeMobile.jsx`. En mobile el precio viejo se muestra sin ninguna marca. `RentaFijaSections` sí recibe `priceMeta={prices?.__meta}` (`Positions.jsx:2803`) — sólo en desktop.

### `components/TcMissingBadge.jsx` (22 líneas)

- **Condición que lo dispara** `[V]`: `lotMissingPurchaseRate(p, costBasis, isArsBroker)` (`:13`, helper en `utils/valuation`). Traducido por el docstring (`:4-8`): el modo **"Costo en dólares" está en `'purchase'`** *y* **ese lote no tiene `tc_compra` registrado** → cae en silencio al dólar de hoy. En modo `'today'` **nunca** aparece.
- **Qué muestra**: una pill ámbar **"TC?"** con el `title` *"Sin tipo de cambio de compra registrado — este lote usa el dólar de hoy para el costo en USD"* (`:15-20`).
- **Dónde se usa** `[V]`: `Positions.jsx:2654` (columna `Inv. USD` de la rama ARS/par) e importado también en `PositionsMobile.jsx:42`.
- **Por qué importa**: es el reconocimiento explícito de que el default de la app cambió. `CurrencyContext.jsx:87-97` cuenta el caso que lo motivó, con números: una compra de ALUA a 880 pesos el 7/5/24 (con `tc_compra` 1048 bien estampado) mostraba **US$ 0,58 en vez de 0,84**, porque 880/1517 usa el MEP de hoy. Y el síntoma es textual: *"en Positions.jsx la columna 'TC Compra' imprime 1048 y la de al lado divide por 1517. Dos celdas contiguas, dos tipos de cambio distintos."*

### Otros "el dato falta" de la sección `[V]`

- `diagnosticoSinMedicion` / `textoSinMedicion` (`utils/evolution`): reemplazan el vacío por una explicación en el sparkline de Home mobile (`HomeMobile.jsx:384-391`), en los KPIs (`:400-411`) y en el Dashboard, tanto en la grilla de Rendimiento (`Dashboard.jsx:1018-1030`) como en el chip del chart (`:1074-1080`). El comentario de `Dashboard.jsx:1013-1017` dice que sin esto `.filter(Boolean)` hacía **desaparecer** las cards "Hoy" y "Este mes" sin decir nada, y que eran **173 usuarios** en la copia de producción.
- `ReturnFxHint` (`components/ReturnFxHint.jsx`): el `(?)` al lado del P&L del TOTAL cuando el retorno en pesos y en dólares difieren en **más de medio punto** (`:28`). Deriva cuánto se movió el dólar como `(1+rArs)/(1+rUsd) − 1` (`:30`). Se usa en `Positions.jsx:2540-2542`. El docstring cita el reporte literal del usuario: *"en dólares me aparece +49 y en pesos +580.000, tiene un error sí o sí"*.
- `priceTrusted` en mobile (`PositionsMobile.jsx:850`): sube a la fila para que la card diga *"al costo" / "sin cotización"* en vez de publicar un 0 que se lee como "no ganaste".
- `brokerHasDay` (`Positions.jsx:2070`): distingue "sin movimiento" (0) de "sin data" (`—`).

---

## Componentes de `components/home/` (11 archivos)

| Archivo | Qué es | Endpoint | Cita |
|---|---|---|---|
| `IndicesStrip.jsx` (72) | grid de 6 índices con precio y % | `GET /home/indices` | `:27` |
| `Heatmap.jsx` (289) | treemap tipo Finviz, squarify a mano, 9 bins de color; click abre `AssetQuickView` | `GET /home/heatmap?market=` | `:170` |
| `MoversRail.jsx` (97) | dos columnas gainers/losers con `DataRow` | `GET /home/movers?market=` | `:57` |
| `PersonalLayer.jsx` (100) | "Lo que te afecta" — cards por `kind` (`holding_move`, `earnings_soon`, `dividend_soon`), iconos lucide reemplazando los emojis que mandaba el backend | `GET /home/personal` | `:44`, `:19-30` |
| `NewsPreview.jsx` (88) | top 3 noticias, con `safeExternalUrl` | `GET /news/market?limit=3` | `:31`, `:8` |
| `EventsPreview.jsx` (115) | 5 próximos eventos, tipados macro/earnings/ex_dividend/payment_date | `GET /events/popular?days=14` | `:50`, `:29-42` |
| `Watchlist.jsx` (160) | tickers seguidos, con quitar | `GET/DELETE /watchlist` | `:32`, `:64` |
| `SearchBar.jsx` (465) | buscador desktop; **exporta `POPULAR_TICKERS`, `FILTERS`, `inferType`** que reusa `MobileSearch` | `GET /positions`, `GET /watchlist`, `POST/DELETE /watchlist` | `:72`, `:103`, `:185`, `:189` |
| `AssetQuickView.jsx` (161) | modal mini-ficha desde Heatmap/Movers/Watchlist | `GET /prices`, `GET/POST/DELETE /watchlist` | `:40-62` |
| `AssetMiniChart.jsx` (158) | sparkline/chart de precio; lo usa también `PositionDetailMobile` y `AssetDetail` | `GET /prices/history?symbol=&period=` | `:48` |
| `OnboardingChecklist.jsx` (314) | 4 pasos: import, descubrir posiciones, quiz de perfil, probar IA | `GET /auth/investor-profile`, `GET /imports` | `:105-108` |

`[V]` **Ninguno de estos 11 componentes consume `CurrencyContext`** — son todos números de mercado en su moneda nativa, no plata del usuario. El único que toca datos del usuario en plata es `PersonalLayer`, y muestra lo que el backend le manda ya formateado (`:11-15`, mapa de `TONE`).

`OnboardingChecklist` tiene dos flags puramente locales (`rendi_ai_discovered`, `rendi_positions_discovered`) y un dismiss permanente (`rendi_checklist_dismissed`, `:41`, `:58-60`); un comentario documenta que el endpoint del perfil estaba mal (`/investor-profile` en vez de `/auth/investor-profile`) y por eso `hasProfile` daba siempre false (`:96-98`).

---

## Componentes de Cartera

### `components/RentaFijaSections.jsx` (515)
`[V]` Agrupa bonos/letras/FCI de **todos los brokers** por `(categoría, moneda)` con `positionSection`/`sectionKey` de `utils/sections`. Cada bono es una card con vencimiento, TIR (`estimateYieldDetailed`), próximo cobro (`nextPaymentForPosition`), P&L con cupones y % de capital recuperado; se expande a `BondDetailBody`. Archivar/restaurar por sección: `GET /sections/archived` (`:74`), `POST /sections/archive` (`:157`), `POST /sections/restore` (`:169`). Tiene su **propio `buildAggregate`** (`:26-50`), *"espejo de `_buildAgg` de Positions.jsx"* — o sea, dos implementaciones que hay que mantener sincronizadas a mano.
Se monta en desktop (`Positions.jsx:2794`, con todo el plumbing de bonos) y en mobile (`PositionsMobile.jsx:1355`, **sin** `bondCashflowsByKey`, `openBondCashflow`, `cerSeries` ni `priceMeta` — todos tienen default y la card *"degrada con gracia"*, `RentaFijaSections.jsx:63-66`).

### `components/PlazosFijosGroup.jsx` (220)
`[V]` `GET /plazos-fijos` (`:25`), `DELETE /plazos-fijos/:id` (`:51`), `POST /plazos-fijos/:id/renovar` (`:57`), `POST /plazos-fijos/:id/cobrar` (`:67`). Valúa cada PF con `computePf` (devengado a hoy) y **reporta `{valor, capital}` por moneda al padre** vía `onTotals` (`:33-47`) — así es como el PF entra al hero de la Cartera. Formatea con su propio `moneyOf` (`:16`), que elige símbolo por la moneda del PF, no por el toggle.

### `components/FuturosGroup.jsx` (547)
`[V]` `GET /futures` (`:58`), `GET /prices?symbols=` **propio** (`:63`, porque el subyacente puede no estar en la cartera), `DELETE /futures/:id` (`:74`), `POST /futures` (`:250`), `POST /futures/:id/close` (`:443`). El no realizado se calcula acá: `(precio − entrada) × cantidad × dir` (`:42-47`), devolviendo **`null` y no `0`** cuando falta el precio, con el motivo escrito (`:31-34`). Formatea siempre en USD con un `usd()` local (`:24-25`). **Sólo desktop.**

### `components/BondDetail.jsx` (387)
`[V]` Dos exports: `BondDetailBody` (div-based, reusable) y `BondDetailRow` (wrapper `<tr colSpan>` para las tablas por broker). Tres columnas (Ficha / Tu inversión / Rendimiento) + el cronograma como **timeline** con tres estados: verde = cobrado, ámbar = venció sin confirmar (`pendingDates`), gris = futuro estimado. Respeta el toggle vía `isArsDisp` si se lo pasan, y cae a la moneda nativa del broker si no (`:43-45`).

---

## Hallazgos, en orden de qué tan caro es cada uno

1. 🔴 **La Cartera mobile no oculta saldos.** El flag de privacidad es global y persistido (`contexts/PrivacyContext.jsx:5-16`), la Home mobile tiene el ojo (`HomeMobile.jsx:302-308`) y el desktop lo respeta en todas las celdas — pero `PositionsMobile.jsx` no consume `usePrivacy` en ninguna línea. Alguien que activa "ocultar saldos" en el celular y entra a Cartera ve todo.
2. 🔴 **La Cartera mobile no avisa cuando un precio es viejo.** `StalePricesNotice` sólo se monta en desktop (`Positions.jsx:2002`); mobile ni siquiera lee `prices.__meta`. Es exactamente el bug que el componente vino a resolver, vivo en la mitad de las sesiones.
3. 🔴 **`PositionDetailMobile` y `AssetDetail` ignoran el toggle de moneda** y muestran USD hardcodeado (`PositionDetailMobile.jsx:233-234`, `AssetDetail.jsx:234-235`). Son las dos pantallas de drill-down: el usuario en pesos hace tap en una fila en pesos y aterriza en dólares.
4. 🔴 **`MobileSearch` está roto en sus dos acciones**: el toast usa `toast.show` cuando la API es `push` (`:134`, `:136` vs `components/Toast.jsx:34`), y `pickTicker` navega a `/posiciones?search=X` que nadie lee (`:117-121`).
5. 🟠 **`GET /snapshots?days=30` de la Cartera desktop es una request por page-load que no alimenta nada** (`Positions.jsx:461` → memo `daily` en `:1624-1645`, nunca renderizado; el banner está deshabilitado en `:1908-1909`).
6. 🟠 **Cinco reimplementaciones distintas de la matriz de valuación por lote**, cada una con sus propias ramas y sus propios comentarios de bugs pasados: `utils/valuation.computeBrokerValue`, `Positions.calcUSDT/calcARS` (`:1263`, `:1321`), `PositionsMobile.enriched` (`:653`), `HomeMobile` "mejor activo" (`:208-266`), `Dashboard.positionsForInsight` (`:302`) y `Dashboard` sync-unrealized (`:501-585`), `AssetDetail.valueLot` (`:34`), `PositionDetailMobile` (`:110-175`). Cada fix de FX hay que aplicarlo siete veces, y los comentarios muestran que históricamente se aplicó de a una.
7. 🟠 **Cuatro fallbacks distintos del tipo de cambio** mientras `/dolar` está en vuelo (`Positions.jsx:241` vs `Dashboard.jsx:192` vs `PositionsMobile.jsx:629` vs `HomeMobile.jsx:99`). El comentario de `Positions.jsx:232-239` documenta el mismo bug en su forma anterior, con un 13,4 % de diferencia dentro de una sola tabla.
8. 🟠 **El total de la Cartera mobile cambia al filtrar por broker**: `PlazosFijosGroup` (que es quien reporta `pfTotals` por callback) sólo se monta en la vista "Todos" (`PositionsMobile.jsx:1362`), pero `pfValueUsd` sigue sumando al hero (`:1114`, `:1131`).
9. 🟠 **La renta fija aparece en dos lugares distintos según el filtro en mobile**: excluida de las secciones (`:1044`) y mostrada en su zona (`:1355`) en la vista "Todos", pero **inline en la lista** cuando hay filtro de broker (`:1080-1087`, que no filtra `isFixedIncome`).
10. 🟡 **`costBasis` falta en las deps de dos `useMemo` de Home mobile** (`HomeMobile.jsx:117`, `:130`): cambiar "Costo en dólares" en `/config` deja el `% histórico` de la home con el valor anterior.
11. 🟡 **El chip de variación del período del Dashboard está hardcodeado en USD** (`Dashboard.jsx:1070`) dentro de un bloque que sí respeta el toggle.
12. 🟡 **"TC MEP" fijo** en el header de sección de la Cartera desktop (`Positions.jsx:2229`) aunque el usuario haya elegido CCL.
13. 🟡 **Import circular `Positions.jsx` ↔ `PositionsMobile.jsx`** (`:44` y `PositionsMobile.jsx:32`), con el import de mobile **estático**: `[I]` el celular baja y parsea las 4.484 líneas del desktop igual.
14. 🟡 **Búsqueda y filtro de la Cartera desktop no llegan a la renta fija, los futuros ni los plazos fijos** (`Positions.jsx:2794`, `:2807`, `:2810` reciben `positions` sin filtrar).
15. 🟡 **Imports sin usar**: `pct` y `flattenAccounts` en `Positions.jsx:30`, `:16`; `fmtUsd`, `fmtArs`, `ars` y `Eyebrow` en `HomeMobile.jsx:40`, `:31`. Prop inexistente `align` en `MobileTopBar.jsx:86`.
16. 🟡 **Comentarios desactualizados** que describen arquitecturas muertas: `Cartera.jsx:8-23` (3-4 tabs), `App.jsx:194-196` (comentario huérfano), `App.jsx:40-41` ("Positions 2481L" cuando son 4.484), `Home.jsx:3-10` (7 bloques, el render tiene 8), `TAB_ALIASES` vacío (`Cartera.jsx:47`).
17. 🟡 **El Dashboard escribe en la base al abrirlo** (`POST /snapshots` en `:478` y `POST /monthly/sync-unrealized` × (N brokers + 1) en `:588-590`). Está bien gateado hoy (cobertura ≥ 95 %, riel MEP, una vez por día), pero es la pantalla de inicio de todos los usuarios y el propio comentario documenta el incidente del 12/08.
18. ⚪ **Colores hardcodeados en el chart del Dashboard** (`:1096`, `:1107`, `:1110`, `:1117`, `:1134-1143`) en lugar de tokens; `[I]` el tooltip queda con fondo `#10151F` en tema claro.

---

## Lo que no pude cerrar

- **Si los cuatro "números grandes" efectivamente coinciden en producción**: identifiqué cinco diferencias estructurales verificadas en el código, pero no corrí la app ni la suite (regla de solo-lectura), así que no puedo cuantificar la brecha.
- **`AdvisorDashboard.jsx`**: es el fork del Dashboard para el tier `advisor` (`Dashboard.jsx:56`). Está fuera de los archivos que me tocaron.
- **`Goals.jsx`**: es la segunda tab de `/posiciones` (`Cartera.jsx:145`). No estaba en mi lista de archivos.
- **Métricas → Comportamiento y el detalle de Reportes**: el `CurrencySwitcher` afirma que no respetan el toggle porque el backend manda strings ya formateados (`CurrencySwitcher.jsx:34-38`). **No verifiqué** `backend/behavioral.py` ni `backend/reporting/builder.py`.
- **`utils/valuation.js` línea por línea**: leí `computeBrokerValue` (`:740-762`) y las firmas de los helpers que usan las pantallas, pero no audité `valuePositionLot`, `trustMktValue`, `costBasisRate`, `usdLotValue`, `pesoLotUsd` ni `buildPriceSymbols` por dentro.
