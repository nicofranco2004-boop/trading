# 1A — Veredicto: P&L no realizado / ganancia latente

**Grupo:** P&L no realizado / ganancia latente · 9 divergencias (DIV-072–DIV-080)
**Commit auditado:** b74f450f (`/tmp/rendi-main`, `backend/main.py` = 38.029 líneas ✅)
**Citas verificadas:** 28 de 36 correctas · 8 corregidas
**Deriva `82fad6a0`:** ninguno de los hallazgos cae en `backend/pricing/fci.py`, `frontend/src/components/AddPositionFlow.jsx` ni `backend/tests/test_fci_uala.py`. No aplica.

---

## Resumen ejecutivo

El "cuánto gané" abierto se calcula en **tres universos que no se hablan**, y el usuario ve los tres.

1. **El universo `purchase`** (Dashboard KPI "P&L no realizado" + hero de Cartera): el costo de un lote en pesos se convierte al **tc_compra** del lote, así que el número incluye la devaluación.
2. **El universo `today`** (todo lo que se persiste y todo lo que muestra /mensual y /reportes): el costo se convierte al **dólar de hoy**, FX-neutral.
3. **El universo backend-IA** (`behavioral._position_value_usd` + `ai/builders/insights.py`): costo = `invested` **sin comisiones**, y en `insights.py` además **sin `asset_type`**, lo que desactiva la banda anti-distorsión de renta fija.

Los universos 1 y 2 pueden dar **signo opuesto** sobre exactamente la misma cartera: con lotes en pesos comprados a ~1.050 y un MEP de ~1.517, el Dashboard puede decir "−US$5.700" mientras /mensual y /reportes dicen "+US$11.900". No es un redondeo: es la devaluación del peso, y solamente una de las dos pantallas la cuenta.

Encima de eso, la columna `monthly_entries.pnl_unrealized` es un **stock** (el latente acumulado desde que se compró cada activo) que **el navegador postea** y que `backend/reporting/builder.py` lee como si fuera un **flujo del período**. El propio código lo admite por escrito en `builder.py:1545-1548` y en `Insights.jsx:1822` — y lo publica igual, con el subtítulo "mark-to-market", en la card de mes y de año de /reportes, en la fila del mes en curso de /mensual y en el "mejor mes" del Wrapped.

Y hay **dos escritores** de esa columna con **gates distintos**: el Dashboard escribe siempre (incluso con el usuario en CCL), /mensual sólo en MEP; el Dashboard exige `priceCoverage ≥ 0.95`, /mensual no exige nada y además **pide una lista de precios distinta** (le faltan el `.BA` de los lotes en pesos alojados en cuentas USD y le sobra un `BTC.BA` inexistente para la cripto de sub-brokers "· USD"), así que valúa esas posiciones **al costo** y persiste un latente subestimado. Gana el último que corra.

---

## Tabla de veredictos

| DIV | versiones | ¿difieren de verdad? | cuál es la correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---:|---|---|---|---|---|
| **DIV-072** | 2 | **SÍ — puede invertir el signo** | ninguna sola: hay que decidir *un* modo y aplicarlo a display **y** a persistencia, o guardar los dos | `/dashboard` KPI "P&L no realizado" y hero de `/cartera` (modo `purchase`) contra `/mensual` col. "No realizado" y `/reportes` KPI "P&L no realizado" (modo `today`) | 🔴 | preferencia de *display* filtrándose a un cálculo *persistido*; fix aplicado en un solo lado |
| **DIV-073** | 2 | **SÍ — pero no por la fórmula: por los gates y por la lista de precios** | ninguna: falta un único `syncUnrealized()` compartido | `/mensual` y `/reportes` (el valor guardado depende de qué pantalla abriste último) | 🔴 | dos escritores del mismo campo, sin capa común; `buildPriceSymbols` existe y /mensual no lo usa |
| **DIV-074** | 2 | SÍ (el interés devengado de plazos fijos) | el KPI del Dashboard (incluir PF es correcto); lo persistido debería incluirlo también o declararse "sin PF" | `/dashboard` KPI vs `/mensual`/`/reportes` — el PF aparece y desaparece | 🟡 | el rollup de PF se agregó al display y nunca al writer |
| **DIV-075** | 2 (Dashboard) + 2 (Insights) | SÍ (mismo delta que DIV-072) | las tortas/aiPositions (`today`) son las coherentes con lo guardado; el KPI es el desalineado | `/dashboard` hero vs sus tortas tipo/sector; `/analisis` card "P&L no realizado" vs `pnl_usd` por activo del snapshot IA | 🟠 | `costBasis` se pasó a `computeBrokerValue` y no a las memos hechas a mano al lado |
| **DIV-076** | 4 lecturas + 2 más no listadas | **SÍ — el número publicado no es del período** | ninguna: `unrealized_pnl` del período debe ser `Δ MtM del período`, no la columna | `/reportes` card de mes ("No realizado", sub "mark-to-market") y de año; `/mensual` fila del mes en curso y fila TOTAL; `/wrapped` mejor/peor mes | 🔴 | un stock guardado en una columna con nombre de flujo; `builder.py` lo documenta y lo publica igual |
| **DIV-077** | 3 motores backend | SÍ (comisiones + `asset_type` ausente + None-vs-0) | `compute_broker_value_usd` (suma comisiones); `insights.py` es el peor | snapshot del chat IA (`/ai`, `/analisis`), atribución por ticker, objetivos | 🟠 | tres ports independientes del mismo `computeBrokerValue`; el SELECT de `insights.py` no trae las columnas que su propio guard necesita |
| **DIV-078** | 2 | Parcial: el **P&L** coincide (0 vs "—"), el **VALOR** no | el total (`computeBrokerValue`) es el correcto; la fila debería mostrar el costo, no "—" | `/cartera` desktop: la columna "Valor" no suma el TOTAL | 🟡 | las filas no usan el motor canónico; sólo tres totales lo usan |
| **DIV-079** | 3 criterios | SÍ (hace desaparecer todo el latente de la tabla) | el calendario UTC del backend (`main.py:9702`) | `/mensual`: tabla mensual + fila TOTAL | 🟠 | criterio de "mes abierto" re-decidido en cada capa; ya hubo un fix idéntico en el backend (2026-05-30) que nunca se replicó al frontend |
| **DIV-080** | 9 re-implementaciones | Hoy **casi alineadas por parcheo repetido**; estructuralmente divergentes | `valuePositionLot` (`valuation.js:543`) — pero sólo la consume `computeBrokerValue` | todas las superficies de valuación; el riesgo es futuro, no actual | 🟠 | falta de capa compartida; migración a `valuePositionLot` empezada y abandonada |

---

## Detalle por divergencia

### DIV-072 — El número que se MUESTRA usa otro dólar que el que se GUARDA

**Estado de las citas:** ⚠️ corregidas.
- `frontend/src/pages/Dashboard.js` → el archivo es **`.jsx`** (`Dashboard.js` no existe). Ídem `CurrencyContext.js` → `.jsx`.
- `Dashboard.jsx:211-214` ✅ exacta.
- `CurrencyContext.jsx:102-109` ✅ exacta.
- `Dashboard.jsx:496-591` ✅ (el effect va de 496 a 591).
- `MonthlySummary.jsx:285` ⚠️ → la llamada a `computeBrokerValue` está en **`:284`**.

#### a. Implementaciones

**A1 · Lo que se MUESTRA — `frontend/src/pages/Dashboard.jsx:211-215`**
```js
const brokerTotals = brokers.map(b => ({ ...b, ...computeBrokerValue(positions, prices, b, tcValuacion, tcCedear, tcCripto, costBasis) }))
const totalValue = brokerTotals.reduce((s, b) => s + b.value, 0) + pf.valueUsd
const totalCostBasis = brokerTotals.reduce((s, b) => s + b.invested, 0) + pf.investedUsd
const totalPnl = totalValue - totalCostBasis
```
Se pinta en `Dashboard.jsx:903-906` (`<KpiCell label="P&L no realizado" value={fmtSigned(totalPnl)} …>`), con el tooltip *"= valor actual − costo de compra"*.

`costBasis` viene de `useCurrency()`. Su default (`CurrencyContext.jsx:102-109`):
```js
const [costBasis, setCostBasisRaw] = useState(() => {
  if (typeof window === 'undefined') return 'purchase'
  try { return localStorage.getItem(CB_STORAGE_KEY) === 'today' ? 'today' : 'purchase' }
  catch { return 'purchase' }
})
```
→ **`'purchase'` salvo que el usuario haya entrado a /config a elegir `'today'`**, que "es casi todo el mundo" según el propio comentario del archivo.

Con `costBasis='purchase'`, `valuePositionLot` (`valuation.js:660`, rama 4 — broker ARS) hace:
```js
const invUsd = realCost / costBasisRate(p, cedearRate, costBasis)
```
y `costBasisRate` (`valuation.js:263-269`) devuelve `p.tc_compra` cuando existe.

**A2 · Lo que se GUARDA — dos escritores, ambos FX-neutral**

- `Dashboard.jsx:497-591`: loop a mano, **no recibe ni consulta `costBasis`**. Para brokers ARS: `pnlForBroker = pnlArs / tcValuacion + pnlUsdDirect` (`:536`), donde `pnlArs = Σ(valArs − costArs)` con `costArs = invested + commissions` en pesos.
- `MonthlySummary.jsx:284-287`: `computeBrokerValue(pos, pricesData, b, tc, tcCedear, tcCripto)` — **6 argumentos, el 7º (`costBasis`) cae al default `'today'`**. El comentario en `:288-295` lo justifica explícitamente: *"`pnlUsd` depende del modo `costBasis`, que es una preferencia de DISPLAY: lo persistido no puede moverse con un toggle"*.

Ambos POSTean a `/api/monthly/sync-unrealized` (`main.py:11038`), que escribe `monthly_entries.pnl_unrealized` del mes calendario actual y recalcula `capital_final`.

#### b. Fórmulas

Sea, para cada lote `i` en un broker ARS:
- `C_i` = costo nativo en pesos = `invested_i + commissions_i`
- `V_i` = valor de mercado en pesos = `price_i × qty_i` (o `C_i` si el guard `trustMktValue` lo rechaza)
- `r_i` = `tc_compra_i` del lote
- `R` = dólar de valuación de hoy (MEP)

**Mostrado (Dashboard KPI, modo `purchase`):**
```
PnL_display = Σ_i ( V_i / R  −  C_i / r_i )   +   PnL_PF
```

**Guardado (`monthly_entries.pnl_unrealized`, modo `today`):**
```
PnL_persist = Σ_i ( V_i / R  −  C_i / R )  =  Σ_i (V_i − C_i) / R
```

Delta:
```
PnL_display − PnL_persist  =  − Σ_i  C_i · ( 1/r_i − 1/R )
```
Es decir: **el KPI del Dashboard resta la devaluación acumulada del peso sobre el costo de cada lote; el número guardado no.** Con `r_i < R` (devaluación normal), el término es positivo y `PnL_display < PnL_persist`.

#### c. ¿Real o cosmética? — **REAL**

Ejemplo numérico, con los números del caso ALUA que documenta `CurrencyContext.jsx:87-92`:

| | costo ARS | tc_compra | MEP hoy | costo USD |
|---|---:|---:|---:|---:|
| lotes en pesos | 60.000.000 | 1.050 | 1.517 | — |
| modo `purchase` | | | | **US$ 57.143** |
| modo `today` | | | | **US$ 39.551** |

Valor de mercado hoy: ARS 78.000.000 → **US$ 51.417**.

| pantalla | modo | P&L no realizado | % |
|---|---|---:|---:|
| `/dashboard` KPI + hero de `/cartera` | `purchase` | **−US$ 5.726** | −10,0 % |
| `/mensual` col. "No realizado" · `/reportes` KPI | `today` | **+US$ 11.866** | +30,0 % |

**Diferencia: US$ 17.592 y signo opuesto**, sobre la misma cartera, el mismo día, sin ningún dato distinto.

#### d. Dictamen

**Ninguna de las dos es "la correcta" en abstracto** — son dos preguntas legítimas ("cuántos dólares puse" vs "cuánto rindió el activo, neto de FX"). Lo que está mal es que **una preferencia de display per-device decida la mitad de las pantallas y no la otra mitad**, sin ninguna etiqueta que lo diga.

Lo correcto:
1. `pnl_unrealized` persistido debe seguir siendo **`today`** (FX-neutral) — un dato guardado no puede moverse con un toggle de localStorage, y `MonthlySummary.jsx:288-295` ya tomó esa decisión bien.
2. El **KPI del Dashboard y el hero de Cartera** deben (a) etiquetar el modo activo junto al número ("costo al dólar de compra"), y (b) exponer los dos valores, o al menos alinearse con el modo que /mensual y /reportes muestran, porque hoy no hay nada en pantalla que explique la diferencia.
3. El toggle vive en `/config`, tres clicks lejos de la pantalla donde cambia el signo del número.

#### e. Qué ve mal el usuario y dónde

| superficie | ruta / endpoint | número | modo |
|---|---|---|---|
| Dashboard, KPI "P&L no realizado" | `/dashboard` → `Dashboard.jsx:903-906` | `totalPnl` | `purchase` |
| Cartera, hero "Tu cartera hoy" | `/cartera` → `Positions.jsx:1588-1598` (`totals`) | `pnl` | `purchase` |
| Análisis, card de P&L abierto | `/analisis` → `Insights.jsx:525-528` | `unrealizedPnl` | `purchase` |
| Mensual, columna "No realizado" | `/mensual` → `MonthlySummary.jsx:590` | `m.pnl_unrealized` | `today` |
| Reportes, KPI "P&L no realizado" | `GET /api/reports/...` → `builder.py:894` → `Reports.jsx:569-575` | `unrealized_pnl` | `today` |
| Reportes, grid técnico "No realizado" | `MonthCard.jsx:226` | `unrealized_pnl` | `today` |

#### f. Causa raíz

**Fix aplicado en un solo lugar + una preferencia de display filtrándose a un cálculo persistido.** El default de `costBasis` se cambió de `'today'` a `'purchase'` (documentado en `CurrencyContext.jsx:87-99`) para arreglar la columna "Invertido USD" de Cartera. Ese cambio se propagó por `useCurrency()` a **todos** los call sites que pasan el 7º argumento — incluidos KPIs agregados que no eran el objetivo del fix — y no llegó (a propósito, y bien) a los escritores. Nadie revisó qué pantallas quedaban de cada lado.

#### g. Fuente única de verdad

Un `usePortfolioTotals(mode)` en `frontend/src/hooks/` que devuelva **ambos**:
```js
{ valueUsd, investedUsdToday, investedUsdPurchase, pnlToday, pnlPurchase, pfPnl }
```
construido sobre `valuePositionLot`. El writer consume siempre `pnlToday`; el display elige, y **el componente que pinta imprime la etiqueta del modo**. Se elimina: la memo `brokerTotals`+`totalPnl` de `Dashboard.jsx:211-215`, `totals`/`totalsToday` de `Positions.jsx:1588-1614`, `totalCostBasis`/`unrealizedPnl` de `Insights.jsx:525-528`.

---

### DIV-073 — Los dos escritores de la misma columna no escriben lo mismo

**Estado de las citas:** ✅ verificadas (`Dashboard.jsx:496-591`, `:499`, `:536`; `MonthlySummary.jsx:241-306`, `:282`, `:287`, `:298`, `:300`) · ⚠️ `MonthlySummary.jsx:285` → la llamada real está en `:284`.

**⚠️ EL MAPA SE EQUIVOCA EN EL DIAGNÓSTICO.** La afirmación *"Dashboard usa un loop a mano … MonthlySummary usa computeBrokerValue … calculan distinto"* **ya no es cierta a nivel aritmético**: verifiqué rama por rama y las dos implementaciones son **algebraicamente equivalentes** (ver §b). Lo que difiere son **los gates y los insumos**, y eso sí produce escrituras distintas.

#### a. Implementaciones

**B1 · `frontend/src/pages/Dashboard.jsx:497-591`** (loop a mano, ~90 líneas)
```js
useEffect(() => {
  if (loading || !lastUpdated || totalValue <= 0) return
  if (!(priceCoverage >= PRICE_COVERAGE_MIN)) return   // :499  — PRICE_COVERAGE_MIN = 0.95
  …
  pnlForBroker = pnlArs / tcValuacion + pnlUsdDirect   // :536
  …
  api.post('/monthly/sync-unrealized', { broker: b.name, pnl_unrealized_usd: +pnlForBroker.toFixed(4) })  // :588
}, [loading, lastUpdated])
```
Precios: `buildPriceSymbols(pos, bkrs)` (`Dashboard.jsx:183`), el helper canónico.
**No hay ningún guard de `valuationDollar`.**

**B2 · `frontend/src/components/MonthlySummary.jsx:241-306`**
```js
const persistMep = valuationDollar === 'mep'                                   // :282
for (const b of bkrs) {
  const result = computeBrokerValue(pos, pricesData, b, tc, tcCedear, tcCripto) // :284
  const pnlForBroker = b.currency === 'ARS' ? result.pnlArs / tc : result.pnlUsd // :287
  globalPnlUsd += pnlForBroker
  if (persistMep) syncs.push(api.post('/monthly/sync-unrealized', …))           // :298
}
```
Precios: lista **inline**, no `buildPriceSymbols` (`MonthlySummary.jsx:267-272`):
```js
const arsSyms = [...new Set(pos.filter(p => arsBrokerSet.has(p.broker) && !p.is_cash)
  .map(p => priceSymbol(p.asset, true, p.asset_type)))]
const usdSyms = [...new Set(pos.filter(p => !arsBrokerSet.has(p.broker) && !p.is_cash && p.asset !== 'USDT')
  .map(p => isArUsdBroker(p.broker) ? priceSymbol(p.asset, true, p.asset_type)
                                    : priceSymbol(p.asset, false, p.asset_type)))]
const pricesData = allSyms ? await api.get(`/prices?symbols=${allSyms}`).catch(() => ({})) : {}
```
**Sin guard de cobertura de precios.** Si `/prices` falla, `pricesData = {}` y escribe igual.

#### b. Fórmulas

Para un broker ARS, `computeBrokerValue` acumula `valueArs`/`invArs` sobre `valuePositionLot`. Sumando las ramas:
- rama 4 (holdings ARS nativos): `invArs = C_i`, `valueArs = V_i` → aporta `V_i − C_i`
- rama 3 (`costInUsd` en broker ARS): `invArs = inv_i^USD · R`, `valueArs = val_i^USD · R` → aporta `(val_i^USD − inv_i^USD)·R`
- rama 1 (cash ARS): `invArs = valueArs` → aporta 0

```
result.pnlArs / R  =  [ Σ_nativos (V_i − C_i) ] / R  +  Σ_usd (val_i^USD − inv_i^USD)
```
que es **literalmente** `pnlArs / tcValuacion + pnlUsdDirect` de `Dashboard.jsx:536`. Para brokers USD verifiqué las cuatro ramas (cash, `costInPesos`, CEDEAR/`· USD`, USD nativo) y son idénticas: mismos condicionales, mismo `trustMktValue`, mismo factor cripto. **Aritméticamente equivalentes** (dado `tc === tcValuacion === tcCedear`, que hoy es cierto: los tres salen de `pickFinancialRate(dolar, valuationDollar)`).

Las diferencias reales son tres gates:

| | Dashboard (B1) | MonthlySummary (B2) |
|---|---|---|
| cobertura de precios | exige `≥ 0,95` | **ninguna** |
| riel de dólar | **escribe siempre** (MEP o CCL) | escribe sólo si `valuationDollar === 'mep'` |
| lista de símbolos | `buildPriceSymbols` (canónica) | inline, con dos agujeros |

Los dos agujeros de la lista inline, que `buildPriceSymbols` documenta como ya arreglados en otras pantallas (`valuation.js:477-482`):
1. **Falta el `.BA` de los lotes `costInPesos` en brokers USD.** `valuationPriceKey` (`valuation.js:469-475`) devuelve `.BA` para `costInPesos(p)`; la lista inline sólo lo hace para `isArUsdBroker(p.broker)`. Un lote en pesos en una cuenta USD que no sea sub-broker "· USD" → el símbolo pedido es el ticker US, la valuación lee `.BA`, **no lo encuentra y cae a costo → P&L 0**.
2. **Pide `BTC.BA` para la cripto de sub-brokers "· USD".** `priceSymbol('BTC', true)` = `'BTC.BA'`, pero `valuePositionLot` rama 5 excluye la cripto (`!isCrypto(p.asset)`) y la manda a la rama 6, que lee `priceSymbol('BTC', false)` = `'BTC'`. **No está en el fetch → cae a costo → P&L 0.**

#### c. ¿Real o cosmética? — **REAL**

Ejemplo A — riel CCL. Usuario con CCL 2 % arriba del MEP, ARS 40.000.000 de tenencias en Cocos con costo ARS 30.000.000:
- Abre `/mensual` en MEP (1.517): persiste `(40M − 30M)/1.517 = +US$ 6.592`.
- Abre `/dashboard` en CCL (1.547): persiste `(40M − 30M)/1.547 = +US$ 6.464`.
- Δ = **US$ 128** por sesión, y arrastra `capital_final` (`main.py:11072-11083`) → el punto de la curva y el "P&L del mes" de /reportes. Gana el último que corra.

Ejemplo B — símbolo faltante. 0,3 BTC en `Balanz · USD`, costo US$ 18.000, spot US$ 92.000 → valor US$ 27.600, latente **+US$ 9.600**.
- Dashboard escribe **+US$ 9.600**.
- /mensual pide `BTC.BA` (no existe), no obtiene `BTC` → cae a costo → escribe **US$ 0** para ese lote.
- Δ = **US$ 9.600**, o sea la posición entera desaparece del latente guardado y de `capital_final`.

Ejemplo C — `/prices` caído. Dashboard no escribe (guard de cobertura). /mensual escribe `pnl_unrealized ≈ 0` para todos los brokers y **recalcula `capital_final` al costo**, borrando el mark-to-market del mes en curso hasta la próxima visita.

#### d. Dictamen

**Ninguna es correcta.** La correcta es una sola función:
- gate de cobertura de precios: **sí** (el del Dashboard, alineado con el cron);
- gate de riel: **sí** (el de /mensual — la serie histórica vive en MEP, es la decisión de scope declarada);
- lista de símbolos: **`buildPriceSymbols`, sin excepción**;
- fórmula: `computeBrokerValue(..., 'today')` con `pnlArs/tc` para ARS, que es lo que ya hace /mensual.

O sea: la fórmula de B2, los gates de B1 ∪ B2, la lista de B1.

#### e. Qué ve mal el usuario y dónde

Todo lo que lea `monthly_entries.pnl_unrealized`: `/mensual` (columna "No realizado", `MonthlySummary.jsx:590`; columna "Retorno", `:545`; fila TOTAL, `:367-376`), `/reportes` (`builder.py:894` y `:1130` → `MonthCard.jsx:226` y `Reports.jsx:569-575`), `/wrapped` (`wrapped.py:144,167,192`), y **la curva de evolución**, porque `capital_final` se recalcula con ese número (`main.py:11069-11083`) y `_repair_monthly_chain` lo propaga hacia adelante (`main.py:9660+`).

#### f. Causa raíz

**Falta de una capa compartida** + **copiar y pegar**. El escritor nació en el Dashboard como loop inline; /mensual necesitó lo mismo y se escribió de nuevo usando el motor canónico. Cuando se detectó que divergían (comentario `MonthlySummary.jsx:288-295`) se alineó **la aritmética** y no se tocó lo que las alimenta. `buildPriceSymbols` se creó exactamente para este problema (su docstring lista los tres agujeros históricos por pantalla) y /mensual quedó afuera de la migración.

#### g. Fuente única de verdad

`frontend/src/utils/syncUnrealized.js`:
```js
export async function syncUnrealized({ positions, brokers, prices, tc, tcCedear, tcCripto,
                                       valuationDollar, priceCoverage }) { … }
```
con los tres gates adentro y `buildPriceSymbols` como única fuente del fetch. Se elimina: `Dashboard.jsx:497-591` completo (~95 líneas) y el cuerpo de `MonthlySummary.jsx:241-306`.

---

### DIV-074 — El KPI del Dashboard incluye plazos fijos; el número persistido no

**Estado de las citas:** ✅ `Dashboard.jsx:212-214`, `usePfRollup.js:36-38` · ⚠️ `Dashboard.jsx:508 y 539` (`if (p.is_cash) continue`) → los reales son **`:511`** y **`:540`**.

#### a. Implementaciones

`frontend/src/hooks/usePfRollup.js:34-39`:
```js
export function pfUsd(totals, tcValuacion) {
  const tc = tcValuacion || 1415
  const valueUsd    = (totals?.USD?.valor   || 0) + (totals?.ARS?.valor   || 0) / tc
  const investedUsd = (totals?.USD?.capital || 0) + (totals?.ARS?.capital || 0) / tc
  return { valueUsd, investedUsd, pnlUsd: valueUsd - investedUsd }
}
```
`Dashboard.jsx:209`: `const pf = pfUsd(usePfRollup(), tcValuacion)` → suma a `totalValue` y `totalCostBasis` (`:212-213`).

El loop del sync (`:497-591`) itera **`brokers` × `positions`**. Los plazos fijos no son posiciones: ni los recorre. El cash sí lo saltea explícitamente (`:511`, `:540`), aunque eso es inocuo (ver §c).

#### b. Fórmulas

```
PnL_KPI     = Σ_brokers (value_b − invested_b)  +  (PF_valor − PF_capital)
PnL_persist = Σ_brokers (value_b − invested_b)
Δ = PF_valor − PF_capital = interés devengado de los plazos fijos
```
El `computePf` que alimenta el rollup (`valuation.js:797`) devenga con `i = tasa × días/365` (TNA) o `(1+tasa)^(días/365) − 1` (TEA).

**Sobre el cash:** el mapa dice que el KPI incluye cash y el persistido no. Es cierto que el loop del sync hace `continue`, pero `valuePositionLot` rama 1 devuelve `investedUsd === valueUsd` para el cash → aporta **exactamente 0** al P&L. **En cash la diferencia es nula.** Lo único que realmente diverge es el PF.

#### c. ¿Real o cosmética? — **REAL, pero acotada al PF**

Ejemplo: PF de ARS 20.000.000 al 32 % TNA, colocado hace 90 días, MEP 1.517.
```
interés = 20.000.000 × 0,32 × 90/365 = ARS 1.578.082  →  US$ 1.040
```
- KPI del Dashboard: incluye **+US$ 1.040**.
- `pnl_unrealized` guardado: **no lo incluye**.
- Al mes siguiente, cuando el PF vence y el capital+interés entra como cash, el interés **reaparece** en `pnl_realized`.

O sea: mientras el PF está vivo, el KPI del Dashboard y la fila de /mensual difieren en el devengado; cuando vence, el número salta de una columna a la otra sin que nada lo explique.

#### d. Dictamen

**El KPI del Dashboard es el correcto** — el interés devengado de un plazo fijo *es* ganancia latente, y omitirlo subestima el patrimonio. Lo que hay que arreglar es el writer: el sync debe sumar `pf.pnlUsd` al `global` (nunca a un broker, porque el PF no pertenece a ninguno) **o** el Dashboard debe declarar explícitamente que el KPI incluye PF y /mensual que no.

Ojo con el orden: si se suma el PF al `global` sin sumarlo a ningún broker, `Σ brokers ≠ global` en `monthly_entries`, que es un invariante que `_repair_monthly_chain` no valida pero que /mensual expone en la pestaña por broker.

#### e. Qué ve mal el usuario y dónde

- `/dashboard`, KPI "P&L no realizado" (`Dashboard.jsx:903-906`): **incluye** el devengado del PF.
- `/mensual`, columna "No realizado" (`MonthlySummary.jsx:590`) y "Retorno" (`:545`): **no lo incluye**.
- `/reportes`, KPI "P&L no realizado" y grid "No realizado": **no lo incluye**.
- El banner de Conciliación de `/mensual` (`MonthlySummary.jsx:808+`) compara `live` (que **tampoco** trae PF: sale de `computeBrokerValue`) contra `capital_final`, así que ni siquiera surfacea el gap.

#### f. Causa raíz

**Feature agregada al display y no al writer.** `usePfRollup`/`pfUsd` se sumaron a los totales del Dashboard (`:209-213`) y a `HomeMobile.jsx:102` e `Insights.jsx:2147`. El effect de snapshots de al lado **sí** se acordó del problema y usa deliberadamente los totales *positions-only* (`totalValuePositions`, `Dashboard.jsx:235-237`, con el comentario "para que el PF no aparezca como un salto"); el effect de `sync-unrealized`, treinta líneas más abajo, no recibió el mismo tratamiento ni en un sentido ni en el otro.

#### g. Fuente única de verdad

El mismo `usePortfolioTotals` de DIV-072, devolviendo `pnl` y `pnlPositionsOnly` como campos separados y explícitos, para que cada consumidor elija a sabiendas en vez de por omisión.

---

### DIV-075 — Dentro de la misma pantalla, el hero y las tortas usan modos de costo distintos

**Estado de las citas:** ✅ `Dashboard.jsx:327-330` (la rama ARS de `positionsForInsight` va de `:322` a `:331`; `invUsd = realCost / tcValuacion` está en **`:329`**), ✅ `Insights.jsx:526-528`, ✅ `Insights.jsx:2028`.

#### a. Implementaciones

**C1 · Dashboard, KPI** — `computeBrokerValue(..., costBasis)` (`:211`) → modo del usuario (`purchase` por default).

**C2 · Dashboard, `positionsForInsight`** — `Dashboard.jsx:302-389`, rama broker ARS (`:322-331`):
```js
const mktArs = priceArs * (p.quantity || 0)
const trust  = trustMktValue(mktArs, realCost, p.asset_type, p.price_override != null)
valueUsd = (trust ? mktArs : realCost) / tcValuacion
// FX-phantom fix: cost basis USD al blue actual (no al tc_compra)
const invUsd = realCost / tcValuacion       // :329
pnlUsd = valueUsd - invUsd
```
La memo **no recibe `costBasis`** — ni siquiera está en su array de dependencias (`:389`). Alimenta `AssetBreakdownBar` y `TopHoldingsPanel` (`Dashboard.jsx:1204-1230`) y `buildDashboardInsight` (`:432`).

**C3 · Insights, card de P&L abierto** — `Insights.jsx:525-528`:
```js
const totalCostBasis = brokers.reduce((s, b) =>
  s + computeBrokerValue(positions, prices, b, tcValuacion, tcCedear, tcCripto, costBasis).invested, 0)
const unrealizedPnl = totalPortfolio - totalCostBasis
```
→ modo del usuario.

**C4 · Insights, `aiPositions`** — `Insights.jsx:2010-2050`:
```js
} else if (isARS) {
  investedUsd = realCost / tcValuacion      // :2028
} else if (costInPesos(p)) {
  investedUsd = pesoLotUsd(p, prices, tcCedear).investedUsd   // default costBasis='today'
}
```
→ siempre `today`. Se serializa como `invested_usd` / `pnl_usd` por activo en el snapshot que consume el motor de diagnóstico (`Insights.jsx:2340` pasa además `unrealizedPnl`, el número C3, **en el mismo objeto**).

#### b. Fórmulas

```
C1 = C3 = Σ_i ( V_i/R − C_i/r_i )      (modo purchase)
C2 = C4 = Σ_i ( V_i/R − C_i/R  )      (modo today)
Δ    = − Σ_i C_i (1/r_i − 1/R)
```
Es **el mismo delta que DIV-072**.

#### c. ¿Real o cosmética? — **REAL** (mismo ejemplo numérico que DIV-072: US$ 17.592 sobre una cartera con ARS 60M de costo)

Lo específico de esta divergencia es que las dos versiones **conviven en la misma pantalla, a pocos píxeles**: el hero dice −US$ 5.726 y el desglose de "Top holdings" de abajo suma +US$ 11.866. Y en el payload de Insights (`:2335-2341`) van juntos `unrealizedPnl` (purchase) y `aiPositions[].pnl_usd` (today): **`Σ aiPositions.pnl_usd ≠ unrealizedPnl`** en el mismo objeto que consume el motor de diagnóstico.

#### d. Dictamen

**Las versiones `today` (C2, C4) son las coherentes** — con lo persistido, con /reportes y con el backend. El desalineado es el par C1/C3.

Nota adicional: C2 usa `tcValuacion` donde `valuePositionLot` usa `cedearRate`. Hoy son el mismo número (`Dashboard.jsx:192-193`, ambos `pickFinancialRate(dolar, valuationDollar)`), pero es la misma clase de bug que ya explotó en el desktop de Cartera y está documentada en `Positions.jsx:1312-1319` ("10 filas que sumaban USD 64.147,88 sobre un TOTAL de USD 56.582,51"). Es una bomba con la espoleta puesta.

#### e. Qué ve mal el usuario y dónde

- `/dashboard`: el KPI (purchase) contra la barra de composición por tipo y el panel de Top Holdings (today) — `Dashboard.jsx:1204-1230`. Los porcentajes de cada activo no reconcilian con el total del hero.
- `/analisis`: la card de P&L abierto (purchase) contra las cifras por activo del snapshot y todo lo que el motor de diagnóstico deduzca de `aiPositions` (today) — `Insights.jsx:2010-2341`.

#### f. Causa raíz

**Frontend recalculando lo que el motor ya calcula.** `positionsForInsight` y `aiPositions` son re-implementaciones a mano de `valuePositionLot` que existen porque necesitan el desglose **por activo** y `computeBrokerValue` sólo devuelve el agregado **por broker**. Cuando se agregó el parámetro `costBasis` a `computeBrokerValue`, se propagó a los llamadores directos y **no** a las memos que espejan su lógica al lado. Es exactamente la falta de `valuePositionLot` como API pública: la función que devuelve el lote ya existe (`valuation.js:543`) y **nadie más que `computeBrokerValue` la usa**.

#### g. Fuente única de verdad

`valuePositionLot(p, ctx)` como API por-lote de consumo directo. `positionsForInsight` y `aiPositions` pasan a ser un `.map()` de dos líneas sobre ella, recibiendo el `costBasis` del contexto igual que todos. Se eliminan ~90 líneas de `Dashboard.jsx:302-389` y ~30 de `Insights.jsx:2010-2040`.

---

### DIV-076 — "No realizado del período" en Reportes son cuatro cosas distintas (y hay dos más)

**Estado de las citas:** ✅ `builder.py:894`, `:1130`, `:1529`, `:1531`, `schema.py:68`, `MonthCard.jsx:226` · ⚠️ `Reports.jsx:571` → el bloque real es **`:569-575`** (`label` en `:571`, `value` en `:572`).

#### a. Implementaciones

Todas escriben `PeriodMetrics.unrealized_pnl` (`backend/reporting/schema.py:68`), que se pinta idéntico en las dos superficies.

**D1 · Mes — `backend/reporting/builder.py:889-894`**
```python
me = fetch_monthly_entry(conn, uid, y, m, broker_filter)
if me:
    …
    unrealized = float(me.get("pnl_unrealized") or 0)
```
`fetch_monthly_entry` (`:663-695`) hace `COALESCE(SUM(pnl_unrealized), 0)` sobre las filas del par de brokers del mes, y su docstring afirma: *"`pnl_realized` y `pnl_unrealized` son flujos DEL MES"*. **Es falso para `pnl_unrealized`.**

**D2 · Año — `builder.py:1112-1130`**
```python
rows = conn.execute("""SELECT month, …, COALESCE(SUM(pnl_unrealized),0) AS pnl_unrealized
                       FROM monthly_entries WHERE user_id=? … AND year=?
                       GROUP BY month ORDER BY month ASC""")
if rows:
    …
    unrealized = float(rows[-1]["pnl_unrealized"] or 0)
```
El **último mes con filas**, no la suma.

**D3 · Día/semana global — `builder.py:1524-1531`**
```python
if period_type in ("day", "week"):
    if broker_filter != "global":
        delta_usd = realized
        unrealized = 0.0          # :1529
    else:
        unrealized = delta_usd - realized    # :1531
```
Residuo: todo el delta que no es realizado.

**D4 · Día/semana con filtro de broker — `builder.py:1529`** → forzado a `0.0`.

**D5 (no listado en el mapa) · `/mensual` — `MonthlySummary.jsx:544-545, 367-376, 590`**
```js
const isCurrent = idx === tabData.length - 1
const ret = snap((m.pnl_realized || 0) + (isCurrent ? (m.pnl_unrealized || 0) : 0))
```
La fila del mes en curso suma el latente **entero** a su "Retorno", y la fila TOTAL compone `retCompound *= (1 + retPct)` con ese número adentro.

**D6 (no listado) · `/wrapped` — `backend/wrapped.py:167` y `:192`**
```python
ret = ((r.get('pnl_realized') or 0) + (r.get('pnl_unrealized') or 0)) / ci
```
Para elegir "tu mejor mes" y "tu peor mes" del año.

#### b. Fórmulas

Sea `U(t)` = latente acumulado de la cartera en el instante `t` (sobre **todos** los lotes abiertos, desde la fecha de compra de cada uno), y `[a,b]` el período.

| | fórmula publicada | lo que el nombre promete |
|---|---|---|
| D1 (mes) | `U(hoy)` si el mes es el calendario actual; `0` si no | `U(b) − U(a)` |
| D2 (año) | `U(hoy)` si el último mes con filas es el actual; `0` si no | `U(b) − U(a)` |
| D3 (día/semana global) | `Δ_valor − realizado` | `U(b) − U(a)` ✅ *(correcta)* |
| D4 (día/semana por broker) | `0` | `U(b) − U(a)` |
| D5 (/mensual) | `U(hoy)` en la fila "actual" | `U(fin mes) − U(inicio mes)` |
| D6 (/wrapped) | `U(hoy)` en el mes actual, `0` en los demás | `U(fin mes) − U(inicio mes)` |

Que la columna es un **stock** está probado por los dos escritores (`Dashboard.jsx:497-591` y `MonthlySummary.jsx:284-287` recorren **todas** las posiciones abiertas, sin filtro de fecha) y por el endpoint `main.py:11038`, cuyo docstring dice: *"pone en 0 pnl_unrealized en todas las demás entradas"*, más `_repair_monthly_chain` (`main.py:9702, 9728`) que fuerza `pnl_unrealized = 0` en todo mes que no sea el calendario actual.

**Y el propio código lo sabe.** `builder.py:1545-1548`:
> *"`unrealized` de monthly_entries es el latente ACUMULADO desde que se compró cada activo (lo postea el navegador en /api/monthly/sync-unrealized), no la variación del período."*

E `Insights.jsx:1822`:
> *"(NO sumar pnl_unrealized mes a mes: es snapshot acumulado, se cuenta N veces)"*

Ese conocimiento se usa para **no** reemplazar `delta_usd` por `realized + unrealized`… y a renglón seguido el mismo `unrealized` se publica como `unrealized_pnl` del período.

#### c. ¿Real o cosmética? — **REAL, y es la peor del grupo**

Usuario que empezó en 2023, con **US$ 40.000 de latente acumulado** en cuatro años. Septiembre 2026: cerró dos ventas por **+US$ 900** y sus posiciones abiertas **subieron US$ 1.200** en el mes.

| celda | lo que publica | lo cierto |
|---|---:|---:|
| `/reportes` mes de septiembre, "No realizado" (sub: *mark-to-market*) | **+US$ 40.000** | +US$ 1.200 |
| `/reportes` mes de agosto (cerrado), "No realizado" | **US$ 0** | el MtM de agosto |
| `/reportes` año 2026, "No realizado" | **+US$ 40.000** | el MtM del año |
| `/reportes` año 2025 (cerrado), "No realizado" | **US$ 0** | el MtM de 2025 |
| `/reportes` semana, "No realizado" | `Δ − realizado` ✅ | ✅ |
| `/reportes` semana filtrada por broker | **US$ 0** | el MtM de esa semana |
| `/mensual` fila septiembre, "Retorno" | **+US$ 40.900** | +US$ 2.100 |
| `/wrapped` "mejor mes" | **septiembre**, siempre | el mes que más rindió |

El error de la celda del mes es de **33×**, y crece con la antigüedad de la cuenta: cuanto más viejo el usuario, más falso el número. La celda dice literalmente "mark-to-market" abajo.

Y no es sólo cosmético: `/mensual` compone `retCompound` con ese retorno (`MonthlySummary.jsx:377`), así que el "retorno total" de la tabla también queda inflado por el latente contado como si fuera del mes.

#### d. Dictamen

**Ninguna es correcta salvo D3** (día/semana global, `delta_usd − realized`), que es la única que mide una diferencia entre dos instantes.

La fórmula correcta, en general:
```
unrealized_pnl(a,b) = U(b) − U(a)
```
Con la infraestructura que ya existe, se calcula así:
```
unrealized_pnl(a,b) = ( V(b) − V(a) )  −  depósitos(a,b) + retiros(a,b)  −  realizado(a,b)
```
donde `V(t)` sale de `fetch_snapshot_at_or_before(..., mtm_only=True)` — la misma función que `builder.py` ya usa para los bordes MtM del mes y del año (`:936-960`, `:1155-1165`). Para meses cerrados sin snapshot MtM válido, lo honesto es **`None` y "—"**, que es la política que el propio `builder.py` ya aplica a `delta_pct` bajo `basis_incomparable`.

**El nombre de la columna es parte del bug.** `monthly_entries.pnl_unrealized` debería llamarse `unrealized_snapshot_usd`, y `PeriodMetrics.unrealized_pnl` sólo debería poblarse con un delta.

#### e. Qué ve mal el usuario y dónde

| superficie | archivo:línea |
|---|---|
| `/reportes`, KPI "P&L no realizado" (sub "mark-to-market") | `Reports.jsx:569-575` ← `builder.py:894` / `:1130` |
| `/reportes`, grid técnico celda "No realizado" | `MonthCard.jsx:226` |
| `/reportes`, mismo número para el filtro de broker en día/semana | `builder.py:1529` |
| `/mensual`, columna "Retorno" del mes en curso y fila TOTAL | `MonthlySummary.jsx:545`, `:367-377` |
| `/wrapped`, slides "mejor mes" / "peor mes" / "P&L total" | `wrapped.py:144`, `:167`, `:192` |
| `/api/reports/...` (endpoint) | `PeriodMetrics.unrealized_pnl`, `schema.py:68` |

#### f. Causa raíz

**Migración a medio hacer + un campo con nombre de flujo que guarda un stock.** `monthly_entries` nació como una planilla contable donde cada fila era un mes; `pnl_unrealized` se agregó después como "el live del mes en curso" (el docstring de `main.py:11040` lo dice: *"live snapshot"*), y `_repair_monthly_chain` lo zerea en el resto para que `capital_final` cierre. `reporting/builder.py` llegó todavía más tarde, leyó la columna con la semántica que sugiere su nombre y su vecina (`pnl_realized`, que **sí** es un flujo), y las cuatro ramas se escribieron cada una con la aproximación que a esa rama le resultó posible. Nunca hubo una definición escrita de qué significa la columna.

#### g. Fuente única de verdad

Una sola función en `backend/reporting/`:
```python
def unrealized_delta(conn, uid, period_start, period_end, broker_filter) -> Optional[float]:
    """U(fin) − U(inicio), con bordes MtM medidos. None si no hay con qué medir."""
```
sobre `fetch_snapshot_at_or_before(..., mtm_only=True)` + `_border_is_fresh`, que ya existen. Se eliminan las cuatro asignaciones de `unrealized` en `builder.py` (`:894`, `:1130`, `:1529`, `:1531`), y `MonthlySummary` / `wrapped.py` dejan de sumar la columna a ningún retorno mensual.

---

### DIV-077 — Tres motores de valuación en el backend, y difieren en el costo

**Estado de las citas:** ✅ `snapshots_job.py:158` (+ `:207-208` para las comisiones), ✅ `behavioral.py:391` y `:426`, ✅ `insights.py:508-511`, ✅ `main.py:25449` · ⚠️ `insights_attribution.py:91-92` → **`:91` es el `import`**; el cálculo citado está en **`:99-100`**.

#### a. Implementaciones

**E1 · `backend/snapshots_job.py:158-319` — `compute_broker_value_usd`** (port fiel del frontend)
```python
comm = p.get('commissions') or 0                      # :207
real_cost = (p.get('invested') or 0) + comm           # :208
```
Devuelve `{value, invested}`. **Suma comisiones.**
Consumidores: el cron de snapshots, y `main.py:25469-25483` (`get_realized_vs_unrealized`, herramienta del chat IA).

**E2 · `backend/behavioral.py:391-482` — `_position_value_usd`**
```python
invested_native = float(p.get("invested") or 0)       # :426
```
**Nunca lee `commissions`.** Devuelve **un solo float**; el costo se obtiene llamándola de nuevo con `prices={}, honor_override=False`.
Consumidores (verificados por grep): `behavioral.py` (6 detectores), `reporting/timeline.py:144`, `main.py:15263`, y **ocho builders del snapshot de IA**: `dashboard.py:69-70`, `dashboard_brokers.py:52-53`, `dashboard_top_holdings.py:58,94-95`, `dashboard_events.py:80`, `dashboard_composition.py:45`, `position.py:76-101`, `insights_attribution.py:99-100`.

**E3 · `backend/ai/builders/insights.py:422-511` — loop inline**
```python
invested = float(p.get("invested") or 0)              # :433
…
if not _trust_mkt_value_usd(mv, cost_usd, p.get("asset_type")):   # :460
    mv = cost_usd
…
if not has_any_live_price:                            # :508
    unrealized_pnl_total_usd = None                   # :509
```
Ni comisiones, ni `price_override`, **ni `asset_type`** — porque su SELECT (`:337`) es:
```sql
SELECT asset, broker, quantity, invested, is_cash, currency FROM positions WHERE …
```
`asset_type` y `price_override` **no están en el SELECT**, así que `p.get("asset_type")` es siempre `None` y `p.get("price_override")` siempre `None`.

**E4 · `backend/main.py:25445-25483` — `get_realized_vs_unrealized`** (delega en E1)
```python
unrealized_usd = 0.0                                  # :25449
…
unrealized_usd = market_value_usd - invested_usd       # :25483
```

#### b. Fórmulas

Para un lote con costo nativo `I` (invested), comisiones `K`, valor de mercado USD `M`:

| motor | costo USD | latente |
|---|---|---|
| E1 / E4 | `(I + K) / R` (ARS) o `I + K` (USD) | `M − (I+K)` |
| E2 | `I / R` o `I` | `M − I` |
| E3 | `I / R` o `I` | `M − I`, con banda de guard equivocada |

**Δ(E1, E2) = K** por lote — el latente de E2/E3 está **inflado exactamente en el total de comisiones de compra**.

Segundo eje, sólo E3 — el guard `_trust_mkt_value_usd` (`behavioral.py:47-60`):
```python
if (asset_type or '').upper() in _FIXED_INCOME_TYPES:   # {'BOND','BONO','ON','LETRA','LECAP'}
    return 0.02 <= mult <= 4
return 0.002 <= mult <= 50
```
Con `asset_type = None`, la renta fija cae siempre en la banda ancha **[0,002×, 50×]** en vez de **[0,02×, 4×]**. El bono per-100 leído per-1 (×100) que la banda estrecha rechaza **pasa** en el snapshot del chat IA.

Tercer eje — sin precios live: **E3 devuelve `None`**, **E4 devuelve `0`** (`main.py:25449` nunca se sobreescribe si `brokers`/`positions` está vacío o si el fetch falla y todo cae a costo).

#### c. ¿Real o cosmética? — **REAL en los tres ejes**

**Eje comisiones.** Posición: `invested = US$ 10.000`, `commissions = US$ 60` (0,6 %, típico AR), valor hoy `US$ 12.000`.

| motor | costo | latente | Δ |
|---|---:|---:|---:|
| E1 (snapshots, `get_realized_vs_unrealized`) | 10.060 | **+US$ 1.940** | — |
| E2 (Análisis, atribución IA, objetivos) | 10.000 | **+US$ 2.000** | **+US$ 60 (+3,1 %)** |

En una cartera de US$ 200.000 con 0,6 % de comisiones acumuladas, el sesgo es de **~US$ 1.200** de latente fantasma, siempre en la misma dirección (a favor).

**Eje `asset_type`.** ON con nominal 100.000, precio real 95 (per-100) → valor real US$ 95.000; el importador la deja con precio 9.500 (per-1 mal leído). Costo US$ 90.000, `mult = 105,6`… no, tomemos el caso ×100 real: costo US$ 900, precio leído per-1 → `mkt = US$ 9.500`, `mult = 10,6`.
- `insights_attribution.py` (que **sí** trae `asset_type`): banda RF [0,02, 4] → **rechaza**, cae a costo, latente **US$ 0**.
- `insights.py` (que no lo trae): banda ancha [0,002, 50] → **acepta**, latente **+US$ 8.600**.
Dos builders del **mismo snapshot de IA**, sobre la **misma posición**, con una diferencia de US$ 8.600 y contradiciéndose entre sí en el mismo payload.

**Eje None vs 0.** Sin precios live: el chat IA recibe `unrealized_pnl_total_usd: null` de `insights.py` y `unrealized_pnl_usd: 0.0` de `get_realized_vs_unrealized`. La primera es honesta ("no lo sé"), la segunda afirma "no tenés ganancia latente".

#### d. Dictamen

**E1 (`compute_broker_value_usd`) es la correcta** en el eje del costo: las comisiones de compra **son** parte del cost basis — es la definición que sostiene el frontend entero (`valuation.js:363-366`, `:558-560`) y `importing/persister.py`. E2 y E3 están mal.

En el eje del guard, la correcta es la que trae `asset_type`. En el eje None-vs-0, la correcta es `None` (E3): afirmar 0 es peor que decir "no sé".

**E3 no debería existir**: es un tercer port de la misma lógica, con un SELECT que no trae las columnas que su propio código consulta.

#### e. Qué ve mal el usuario y dónde

| superficie | motor | qué está mal |
|---|---|---|
| curva de evolución / snapshots nocturnos | E1 | ✅ correcto |
| chat IA, `get_realized_vs_unrealized` (`main.py:25385`) | E1 (+E4) | ✅ costo; ❌ devuelve 0 en vez de null sin precios |
| `/analisis` (Comportamiento, detectores) | E2 | latente inflado en las comisiones |
| `/analisis`, atribución por ticker de la IA | E2 (`insights_attribution.py:99-100`) | ídem |
| `/goals` (objetivos) | E2 (`main.py:15263`) | ídem |
| chat IA, snapshot de cartera (`ai/builders/insights.py`) | E3 | comisiones **+** guard de renta fija desactivado **+** `price_override` ignorado |
| chat IA, cards de dashboard (7 builders) | E2 | comisiones |

Concretamente: **el chat IA puede decirle al usuario que gana US$ 8.600 en un bono donde /reportes dice US$ 0**, en la misma sesión.

#### f. Causa raíz

**Tres ports independientes del mismo `computeBrokerValue` del frontend, escritos en momentos distintos por necesidades distintas**, sin que ninguno sea declarado canónico. `snapshots_job.compute_broker_value_usd` se anuncia como *"port fiel"*; `behavioral._position_value_usd` nació para los detectores de comportamiento (donde una comisión no cambiaba nada) y **después** se lo reusó como valuador general — su firma lo delata: devuelve **un float**, no `{value, invested}`, así que "el costo" hay que fabricarlo con un segundo llamado y un flag (`honor_override=False`). `insights.py` se escribió a mano para poder agregar por ticker, y su SELECT se armó pensando en lo que necesitaba la agregación, no en lo que necesita el guard que copió de `behavioral`.

#### g. Fuente única de verdad

`backend/valuation.py` (nuevo módulo) con la firma del frontend:
```python
def value_position_lot(p, *, broker_currency, broker_name, prices, tc_blue, cedear_rate,
                       tc_cripto=None, honor_override=True) -> LotValue:
    """→ LotValue(value_usd, invested_usd, guard_cost, price_local, price_trusted)"""
```
`compute_broker_value_usd` pasa a ser su suma. Se elimina `behavioral._position_value_usd` (18 call sites migran) y el loop inline de `insights.py:422-485`. Requisito previo: **todos** los SELECT de positions deben traer `asset_type`, `commissions`, `price_override` y `currency` — hoy hay al menos dos que no.

---

### DIV-078 — Cartera desktop: la fila dice "—" y el total cuenta al costo

**Estado de las citas:** ✅ `Positions.jsx:1346`, ✅ `Positions.jsx:1591`.

#### a. Implementaciones

**F1 · La fila — `Positions.jsx:1346`**
```js
const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true)]
if (priceArs == null) return { valueArs: null, valueUsd: null, pnlArs: null, pnlUsd: null, pnlPct: null, priceArs: null }
```
(idem `calcUSDT`: `:1276` y `:1301`). Se renderiza en `:2466` (Valor) y `:2480` (P&L USD) como `<span className="text-ink-3">—</span>`.

**F2 · El total del pie — `Positions.jsx:1588-1598`**
```js
const totals = useMemo(() => {
  for (const b of brokers) {
    const r = computeBrokerValue(positions, prices, b, tcValuacion, tcCedear, tcCripto, costBasis)
    value += r.value || 0; invested += r.invested || 0
  } …
})
```
`valuePositionLot` sin precio (`valuation.js:672-679`, rama 4): `valueUsd = invUsdHoy`, `investedUsd = invUsdHoy` → aporta **el costo al valor** y **0 al P&L**.

#### b. Fórmulas

Para un lote sin precio:
```
Fila:  valor = null ("—")   ,  P&L = null ("—")
Total: valor = C/R           ,  P&L = 0
```

#### c. ¿Real o cosmética? — **Mixta: el P&L es cosmético, el VALOR es real**

En el **P&L** las dos versiones dicen lo mismo (0 vs "no sé, no aporto") — el número del pie no cambia. **Cosmético.**

En el **VALOR** sí divergen. Ejemplo: broker con 4 posiciones cotizadas que suman US$ 30.000 y una ON de costo US$ 8.000 sin cotización.
- Suma de la columna "Valor" que el usuario ve: **US$ 30.000** (la ON muestra "—").
- TOTAL del pie: **US$ 38.000**.
- **US$ 8.000 que aparecen en el total y en ninguna fila.** Es literalmente el mismo síntoma que ya se reportó con captura y se arregló por otro motivo (`Positions.jsx:1377-1380`: *"10 filas que sumaban USD 64.147,88 sobre un TOTAL de USD 56.582,51"*), sólo que en la otra dirección.

#### d. Dictamen

**El total (F2) es el correcto**: una posición sin cotización sigue valiendo algo, y valuarla al costo es la política declarada de la casa (`trustMktValue` hace exactamente eso cuando rechaza un precio).

La fila debería mostrar **el costo con una marca visual** (el valuador ya expone `priceTrusted` y `guardCost` justamente para esto — `valuation.js:530-542`), no "—". Un "—" en la columna Valor le dice al usuario que la posición no vale nada, y hace que su suma mental no cierre con el pie.

Nota: hoy la fila `calcARS` sin precio devuelve `pnlPct: null` mientras la rama con guard rechazado (`:1339-1342`) devuelve `pnlPct: 0` y `valueArs: realCostArs`. **Dentro de la misma función, dos "no confío en el precio" con dos salidas distintas.**

#### e. Qué ve mal el usuario y dónde

`/cartera` desktop, tabla por broker: la columna "Valor" (`Positions.jsx:2466`) muestra "—" en las posiciones sin cotización, y el `<tfoot>` (`:2532`) muestra un TOTAL que las incluye al costo. Afecta sobre todo a ONs, bonos ilíquidos y FCIs sin NAV del día — que es justamente lo que más pesa en las carteras argentinas.

#### f. Causa raíz

**El desktop no usa el motor canónico para sus filas, sólo para tres totales.** `valuation.js:505-507` lo dice literalmente. `calcARS`/`calcUSDT` son una re-implementación que nació antes y que decidió su propio contrato de "sin dato" (`null`) mientras el motor decidió el suyo (fallback a costo).

#### g. Fuente única de verdad

Las filas deben salir de `valuePositionLot`, que ya devuelve `priceTrusted: null | false | true` para que la UI distinga "no hay precio" de "hay precio y lo rechacé" y de "hay precio bueno", **sin cambiar el número**. Se eliminan `calcARS` (`:1321-1381`) y `calcUSDT` (`:1263-1319`).

---

### DIV-079 — "Mes abierto" se decide con dos criterios distintos

**Estado de las citas:** ⚠️ `main.py:9701` → la línea real es **`main.py:9702`** (`:9701` es el comentario que la precede) · ✅ `MonthlySummary.jsx:544`.

#### a. Implementaciones

**G1 · Backend — calendario UTC (`main.py:9700-9702`, dentro de `_repair_monthly_chain`)**
```python
# "Open" SOLO cuando coincide con el calendario actual. Filas
# futuras (ej: Jul 2099 cargado por error) se tratan como
# cerradas — propagan el chain pero zero-ean pnl_unrealized.
is_open = (row['year'] == current_year and row['month'] == current_month)
```
Mismo criterio en `sync_unrealized` (`main.py:11055-11058`: `WHERE … year=? AND month=?` con `now.year, now.month`).
El docstring documenta que **este ya fue un bug arreglado**: *"HISTORIA (bug fix 2026-05-30): antes el 'mes abierto' se detectaba como la ÚLTIMA row del query (i == len(rows) - 1). Si el user tenía gaps … su pnl_unrealized stale quedaba sin zero-ear"*.

**G2 · Frontend, tabla — posición en el array (`MonthlySummary.jsx:544`)**
```js
const isCurrent = idx === tabData.length - 1
```
donde `tabData` (`:184-190`) es `entries.filter(broker===tab).sort(asc por year,month)`, opcionalmente recortado a los últimos N.
Ídem en la fila TOTAL (`:367`).

**G3 · Frontend, banner de Conciliación — calendario local (`MonthlySummary.jsx:816`)**
```js
const isCurrentMonth = (e) => e.year === todayY && e.month === todayM
const current = sorted.find(isCurrentMonth) || sorted[sorted.length - 1]
```

Tres criterios en dos archivos, dos de ellos en el **mismo componente**.

#### b. Fórmulas

```
G1: abierto(fila) ⟺ (fila.year, fila.month) == (hoy.year, hoy.month)   [UTC]
G2: abierto(fila) ⟺ fila == max(filas ordenadas por (year,month))
G3: G1 con fallback a G2                                                [local]
```
`G1 ≡ G2` **sólo si** existe fila del mes actual **y** ninguna fila es futura. Cualquiera de las dos condiciones que falle, divergen.

#### c. ¿Real o cosmética? — **REAL, y hace desaparecer el número entero**

**Caso 1 — fila futura.** El usuario cargó a mano un cierre de "Dic 2026" (o un import fabricó una fila adelantada; `importing/persister.py:1256` menciona ese escenario). Hoy es septiembre 2026 y hay latente de **+US$ 12.400**.
- Backend: septiembre es el calendario actual → conserva `pnl_unrealized = 12.400`. Diciembre no lo es → lo zerea.
- `/mensual`: `tabData[last]` = diciembre → `isCurrent` es diciembre. Septiembre se pinta como **cerrado**:
  - columna "No realizado" de septiembre → `fmtMoney(0)` (`:590`, la rama `isCurrent ? m.pnl_unrealized : 0`) → **US$ 0**
  - columna "Retorno" de septiembre → sólo `pnl_realized` (`:545`) → le faltan **US$ 12.400**
  - fila TOTAL → `pnl_unrealized` acumulado = **US$ 0** (`:375`) y `retCompound` sin el latente
  - diciembre se pinta con badge de "live" (`:557`, `:573`, `:617`) mostrando US$ 0
- **Los US$ 12.400 desaparecen de la pantalla completa.**

**Caso 2 — hueco de calendario.** Filas en marzo y mayo, hoy es junio, sin fila de junio (el rollover es lazy y sólo corre al visitar /mensual).
- Backend: mayo no es el mes actual → `pnl_unrealized = 0`.
- `/mensual`: mayo es el último → `isCurrent = true` → se pinta como mes vivo (badge "live"), su "Retorno" suma un `pnl_unrealized` que vale 0, y la línea `:599` (`{!isCurrent && retPct !== 0 && …}`) **oculta el % de retorno de mayo**, que es un mes cerrado con retorno real.

**Caso 3 — recorte por `RECENT_MONTHS_DEFAULT`.** `tabData` es `allTabData.slice(-N)`; el último sigue siendo el máximo, así que este caso **no** rompe. ✅

**Caso 4 — borde de mes en UTC.** El backend usa `datetime.utcnow()`; el usuario está en UTC−3. Entre las 21:00 del último día del mes y la medianoche local, el backend ya cambió de mes y el frontend no. Ventana de 3 h por mes en la que `sync-unrealized` escribe en el mes siguiente y `_repair_monthly_chain` zerea el que el usuario ve como actual.

#### d. Dictamen

**El criterio del backend (G1) es el correcto**, y además es el que decide dónde vive el dato: `sync_unrealized` **sólo** escribe en la fila `(now.year, now.month)`. Cualquier otra fila tiene `pnl_unrealized = 0` por construcción. El frontend tiene que preguntar lo mismo, o directamente dejar de adivinar: el backend puede devolver `is_open` en el payload de `/monthly`.

El detalle fino: G1 usa UTC. Para una app argentina el mes debería cerrarse en **America/Argentina/Buenos_Aires**, no en UTC — o al menos el frontend debería usar el mismo reloj que el backend.

#### e. Qué ve mal el usuario y dónde

`/mensual`, tabla mensual (`MonthlySummary.jsx:527-630`): columna "No realizado" (`:590`), columna "Retorno" (`:545`), el badge de mes vivo (`:557`, `:573`, `:617`), el % oculto de un mes cerrado (`:599`) y la fila TOTAL (`:367-377`, `:632`). En el caso 1 el latente entero desaparece de la pantalla.

#### f. Causa raíz

**Un fix aplicado en un solo lugar.** El bug es *exactamente* el mismo que `main.py:9673-9679` documenta como arreglado el 2026-05-30 en el backend (`i == len(rows) - 1` → calendario). El frontend tiene la misma línea, sin arreglar, en el mismo componente que consume ese backend. Nadie buscó las otras ocurrencias del patrón cuando se arregló la primera.

#### g. Fuente única de verdad

`GET /api/monthly` devuelve `is_open: bool` por fila, calculado con el **mismo** reloj que `sync_unrealized` y `_repair_monthly_chain` (idealmente `America/Argentina/Buenos_Aires`, no UTC). El frontend nunca vuelve a calcularlo: se eliminan `MonthlySummary.jsx:367`, `:544` y el fallback de `:818`.

---

### DIV-080 — Nueve re-implementaciones frontend de la valuación por lote

**Estado de las citas:** ⚠️ **cinco de nueve rangos están corridos**, y la cita del comentario está **en el archivo correcto pero a 260 líneas de distancia**.

| citado | real | nota |
|---|---|---|
| `valuePositionLot (valuation.js:545-564)` | **`:543-735`** | el rango citado (20 líneas) es el destructuring; la función tiene 193 |
| `valueEquityLot (:355-420)` | **`:360-421`** | |
| `calcUSDT/calcARS de Positions (:1262-1365)` | **`:1263-1319`** y **`:1321-1381`** | |
| `PositionsMobile (:770-792)` | **`:653-862`** (memo `enriched`) | el rango citado está adentro, pero es un fragmento |
| `PositionDetailMobile (:111-174)` | **`:111-176`** | ✅ |
| `AssetDetail.valueLot (:34-164)` | **`:34-97`** | la función termina en 97 |
| `positionsForInsight de Dashboard (:302-381)` | **`:302-389`** | |
| `aiPositions de Insights (:2010-2036)` | **`:2010-2050`** | |
| `el loop del sync (:504-586)` | **`:497-591`** | |
| `«había CINCO implementaciones» en valuation.js:761-773` | **`valuation.js:503-509`** | ❌ **cita del mapa incorrecta**: en `:761-773` está `computePf`/`_pfDate` (plazos fijos), nada que ver |

#### a. Implementaciones

Las nueve existen y las verifiqué una por una. El texto que el mapa cita, en su ubicación real (`valuation.js:503-509`):
> *"POR QUÉ EXISTE: había CINCO implementaciones de la valuación por lote (computeBrokerValue, valueEquityLot, AssetDetail.valueLot, PositionDetailMobile y PositionsMobile) y ninguna era 'la buena a la que volver' — el desktop tampoco usa el motor canónico para sus filas, sólo para tres totales. Esta es la que va a serlo. **Todavía NO la consume nadie más**: migrar a los cinco lectores sólo es delta 0 después de alinear los comportamientos que hoy difieren (comisiones, modo 'purchase')."*

**Ese comentario está desactualizado en un punto**: `computeBrokerValue` (`:740-767`) **sí** la consume — de hecho es ahora sólo un `for` que suma `valuePositionLot`. Pero es exacto en lo esencial: **ningún otro lector la usa**, y `computeBrokerValue` es el consumidor original refactorizado, no una migración.

#### b. Fórmulas — el mapa de divergencias reales

Comparé las nueve rama por rama contra `valuePositionLot`. Lo que queda hoy:

| # | implementación | rate del path ARS | comisiones | modo `purchase` | guard | veredicto |
|---|---|---|---|---|---|---|
| 0 | `valuePositionLot` `:543` | `cedearRate` | ✅ | ✅ | ARS nativo | **canónica** |
| 1 | `valueEquityLot` `:360` | `tcValuacion` | ✅ | ✅ (con `guardCost` separado) | mixto | ≡ |
| 2 | `Positions.calcUSDT` `:1263` | — | ✅ | ✅ (`routedInvUsd`) | USD | ≡ salvo el `null` de DIV-078 |
| 3 | `Positions.calcARS` `:1321` | `tcCedear` | ✅ | ✅ | ARS nativo | ≡ salvo el `null` de DIV-078 |
| 4 | `PositionsMobile.enriched` `:653` | **`tcValuacion`** | ✅ | ✅ (`investedUsdDisplay`) | USD | ≡ *hoy* |
| 5 | `PositionDetailMobile` `:111` | **`tcValuacion`** | ✅ | ✅ | mixto | ≡ *hoy* |
| 6 | `AssetDetail.valueLot` `:34` | **`tcValuacion`** | ✅ | ✅ | mixto | ≡ *hoy* |
| 7 | `Dashboard.positionsForInsight` `:302` | **`tcValuacion`** | ✅ | ❌ **siempre `today`** | ARS nativo | **DIV-075** |
| 8 | `Insights.aiPositions` `:2010` | **`tcValuacion`** | ✅ | ❌ **siempre `today`** | vía `holdingValueUsd` | **DIV-075** |
| 9 | `Dashboard` loop del sync `:497` | `tcValuacion` | ✅ | ❌ (a propósito) | ARS/USD | **DIV-073** (gates) |

#### c. ¿Real o cosmética? — **Hoy CASI cosmética; estructuralmente REAL**

La aritmética de 1–6 es hoy equivalente a la canónica, después de ~8 rondas de parcheo (las comisiones se agregaron una por una: `valuation.js:361-367`, `PositionsMobile.jsx:658-662`, `AssetDetail.jsx:43-47`, cada una con su propio comentario diciendo *"este archivo era el último que no la seguía"*).

Lo que **sí** es real hoy: **7, 8 y 9** (cubiertos por DIV-073 y DIV-075).

Lo que es una bomba: **`tcValuacion` vs `cedearRate`**. Seis de las nueve implementaciones usan `tcValuacion` donde la canónica usa `cedearRate`. Hoy son el mismo número (`pickFinancialRate(dolar, valuationDollar)` en las tres páginas). El día que se separen —y ya se separaron una vez: `Positions.jsx:1312-1319` documenta que `calcARS` usaba `tcValuacion` y por eso **10 filas sumaban US$ 64.147,88 sobre un TOTAL de US$ 56.582,51**, un 13 % de desfase, exactamente el spread MEP/blue de ese día— vuelven a divergir las seis a la vez, cada una con un síntoma distinto en una pantalla distinta.

Ejemplo del costo de mantener nueve copias: `Dashboard.jsx:192-193` deja `tcValuacion = pickFinancialRate(...) || config.tc_blue || 1415` y `tcCedear = pickFinancialRate(...) || tcValuacion`. Si `/dolar` falla, ambos caen al **blue** de config. `PositionsMobile.jsx:629-630` cae a **1415 hardcodeado**. La misma posición, en el mismo momento, con `/dolar` caído: desktop la valúa al blue guardado, mobile a 1415.

#### d. Dictamen

**`valuePositionLot` es la correcta** y es la única que documenta su contrato completo (`valuation.js:497-542`: seis ramas, orden, `guardCost` vs `investedUsdDisplay` vs `priceLocal`). El problema no es cuál gana: es que la migración se hizo (la función existe, con tests: `valuation.test.js:1118-1143`) y **no se completó**.

#### e. Qué ve mal el usuario y dónde

Hoy, en números: sólo lo de DIV-073 y DIV-075. Estructuralmente: **cualquier fix futuro a la valuación por lote hay que aplicarlo nueve veces**, y ocho de esas nueve no tienen tests propios. Los últimos cuatro bugs de este grupo (comisiones ×4, `costInUsd` ×5, CEDEAR en broker USD ×5, key normalizada `BRK.B` ×4) se arreglaron así — de a un archivo por vez, cada uno con su comentario admitiendo que quedaban otros.

#### f. Causa raíz

**Falta de capa compartida + migración a medio hacer.** Las copias 2–8 nacieron porque `computeBrokerValue` devuelve el agregado **por broker** y todas ellas necesitan el desglose **por lote/activo**. La función que faltaba se escribió (`valuePositionLot`) pero se dejó con un único consumidor, y el propio comentario explica por qué se frenó: *"migrar a los cinco lectores sólo es delta 0 después de alinear los comportamientos que hoy difieren (comisiones, modo 'purchase')"*. **Esos dos comportamientos ya están alineados** en 1–6, así que el bloqueo declarado ya no existe.

#### g. Fuente única de verdad

`valuePositionLot(p, ctx)` para las nueve. El orden de migración con menor riesgo, por delta esperado:
1. `valueEquityLot` (delta 0 verificable con sus tests existentes)
2. `AssetDetail.valueLot` y `PositionDetailMobile` (`:111-176`) — misma matriz
3. `PositionsMobile.enriched` (`:653-862`) — extraer la parte de valuación, dejar `dayVar` afuera
4. `Positions.calcARS`/`calcUSDT` — **cambia comportamiento**: cierra DIV-078
5. `Dashboard.positionsForInsight` e `Insights.aiPositions` — **cambia comportamiento**: cierra DIV-075
6. el loop del sync (`Dashboard.jsx:497-591`) → reemplazado por el `syncUnrealized()` compartido de DIV-073

Se eliminan ~500 líneas de lógica duplicada.

---

## Parches detectados

| ubicación | qué síntoma tapa | causa real | dónde más sigue rompiendo |
|---|---|---|---|
| `builder.py:1529` — `unrealized = 0.0` cuando `broker_filter != "global"` en día/semana | que no hay snapshots por broker para medir MtM sub-mensual | los snapshots sólo existen a nivel `global` (`main.py` POST `/snapshots`) | `builder.py:1626-1629` (mismo 0 bajo `basis_incomparable`); toda métrica por broker sub-mensual; `useMonthlyData.js:493-503` tiene que usar `computeBrokerValue` live porque tampoco puede desglosar el snapshot |
| `main.py:11062-11067` — `UPDATE monthly_entries SET pnl_unrealized=0 WHERE … id != current` | que el latente es un stock y quedaba stale en meses cerrados | la columna guarda un stock con nombre de flujo | `builder.py:894` publica ese stock como "no realizado del mes"; `wrapped.py:167,192`; `MonthlySummary.jsx:545` |
| `_repair_monthly_chain` (`main.py:9660+`) — recalcular toda la cadena en cada sync | que `capital_final` deriva porque `pnl_unrealized` se pisa desde el navegador | la contabilidad mensual se alimenta de un cálculo del cliente, no del servidor | corre en **cada** POST a `sync-unrealized`, o sea 2× por carga de Dashboard × N brokers |
| `Dashboard.jsx:461` — `PRICE_COVERAGE_MIN = 0.95` | que el POST se dispare con precios a medio cargar | no hay señal de "el fetch terminó y valuó todo"; se aproxima con un ratio | `MonthlySummary.jsx:241-306` **no tiene** el guard → escribe igual (DIV-073) |
| `MonthlySummary.jsx:282` — `persistMep` | que un usuario en CCL escriba latente CCL-flavored | el riel de dólar es un estado de display que se cuela al cálculo | `Dashboard.jsx:497-591` **no tiene** el guard → escribe CCL igual (DIV-073) |
| `MonthlySummary.jsx:267-272` — lista de símbolos inline | (no tapa nada: es la versión previa a `buildPriceSymbols` que quedó) | duplicación del fetch de precios | dos posiciones (cripto en "· USD", `costInPesos` en broker USD) se persisten al costo |
| `builder.py:1621-1629` — `basis_incomparable → delta_usd = 0.0` | bases incomparables (start contable vs end a mercado) | `capital_inicio` de la cadena contable es un costo, no una medición | 180 usuarios (22 %) según el propio comentario de `useMonthlyData.js:494-499`; el parche tapa el síntoma, la cadena contable sigue mezclando costo y mercado |
| `behavioral._position_value_usd(p, {}, …, honor_override=False)` como forma de obtener el costo | que la función devuelve un float y no `{value, invested}` | firma incorrecta desde el diseño | 18 call sites; y por el camino se pierde `commissions`, que la función nunca lee (DIV-077) |
| `insights.py:508-511` — `if not has_any_live_price: … = None` | que sin precios el latente daría 0 y sonaría a "no tenés ganancia" | falta un contrato de "no medible" común | `main.py:25449` devuelve `0.0` en el mismo caso, en la misma herramienta de IA |

---

## Citas del mapa incorrectas

| DIV | cita del mapa | ubicación real | qué decía mal |
|---|---|---|---|
| 072 | `frontend/src/pages/Dashboard.js` | `frontend/src/pages/Dashboard.jsx` | extensión; `Dashboard.js` no existe |
| 072 | `frontend/src/contexts/CurrencyContext.js` | `…/CurrencyContext.jsx` | ídem |
| 072/073 | `MonthlySummary.jsx:285` (`computeBrokerValue` con 6 args) | `MonthlySummary.jsx:284` | off-by-one |
| 074 | `Dashboard.jsx` `if (p.is_cash) continue` en `l. 508 y 539` | `:511` y `:540` | off-by-3 / off-by-1 |
| 076 | `Reports.jsx:571` | `Reports.jsx:569-575` (label `:571`, value `:572`) | el rango, no la línea |
| 077 | `insights_attribution.py:91-92` (valuación por ticker) | `:99-100`; `:91` es `from behavioral import _position_value_usd` | apunta al import, no al cálculo |
| 079 | `main.py:9701` (`is_open = …`) | `main.py:9702` (`:9701` es el comentario) | off-by-one |
| 080 | `valuePositionLot (valuation.js:545-564)` | `:543-735` | el rango cubre 20 de 193 líneas |
| 080 | `valueEquityLot (:355-420)` | `:360-421` | |
| 080 | `calcUSDT/calcARS de Positions (:1262-1365)` | `:1263-1319` y `:1321-1381` | |
| 080 | `AssetDetail.valueLot (:34-164)` | `:34-97` | la función termina en 97, no 164 |
| 080 | `Dashboard positionsForInsight (:302-381)` | `:302-389` | |
| 080 | `Insights aiPositions (:2010-2036)` | `:2010-2050` | |
| 080 | `el loop del sync (:504-586)` | `:497-591` | |
| 080 | **`valuation.js:761-773`** = *"había CINCO implementaciones…"* | **`valuation.js:503-509`** | ❌ en `:761-773` está `computePf`/`_pfDate` (plazos fijos). Además el comentario ya no es del todo cierto: `computeBrokerValue:747` **sí** consume `valuePositionLot` |
| 073 | *"Dashboard usa un loop a mano … MonthlySummary usa computeBrokerValue … calculan distinto"* | ambas son **algebraicamente equivalentes** (verificado rama por rama) | el diagnóstico del mapa es incorrecto: lo que diverge son los **gates** y la **lista de precios**, no la fórmula |
| 074 | *"El loop del sync saltea el cash … el KPI incluye cash"* | el cash aporta **exactamente 0** al P&L en las dos versiones (`valuation.js` rama 1: `investedUsd === valueUsd`) | la divergencia por cash es **nula**; sólo el PF diverge |

---

## URGENTE

Dos cosas que no deberían esperar a la siguiente iteración. **No toqué una línea de código; esto es diagnóstico.**

### U-1 · `/reportes` publica el latente acumulado de años como "P&L no realizado del mes", rotulado *mark-to-market*

`builder.py:894` (mes) y `:1130` (año). El error escala con la antigüedad de la cuenta: un usuario de 2023 con US$ 40.000 de latente ve **+US$ 40.000** en la card de septiembre de 2026 en vez de los ~US$ 1.200 que realmente se movieron. **33× de error**, con la etiqueta "mark-to-market" debajo.

Es urgente por tres razones: (a) el propio `builder.py:1545-1548` ya diagnostica el problema por escrito y publica el número igual — o sea que hay una decisión consciente en la mitad del archivo contradicha por la otra mitad; (b) la card de /reportes es la que el usuario descarga y comparte; (c) el mismo número alimenta `/wrapped` ("tu mejor mes" es **siempre** el mes en curso mientras el latente sea positivo).

**Mitigación mínima sin refactor:** si `unrealized_pnl` no puede derivarse como `U(fin) − U(inicio)` con bordes MtM medidos, devolver `None` y que la card muestre "—", que es exactamente la política que `builder.py` ya aplica a `delta_pct` bajo `basis_incomparable`. Un "—" es correcto; +US$ 40.000 no.

### U-2 · Dos escritores del mismo campo, con gates distintos, y el número guardado depende de qué pantalla abriste último

`Dashboard.jsx:497-591` escribe **siempre** (incluso con el usuario en CCL, incluso sin el guard de riel); `MonthlySummary.jsx:241-306` escribe **sin guard de cobertura de precios** y con una lista de símbolos que **le falta el `.BA` de los lotes en pesos alojados en cuentas USD** y **pide `BTC.BA` para la cripto de sub-brokers "· USD"** — ambos casos valúan al costo y persisten **P&L 0 para esas posiciones**.

No es sólo cosmético: `sync-unrealized` recalcula `capital_final` con ese número (`main.py:11069-11083`) y `_repair_monthly_chain` lo propaga hacia adelante por toda la cadena. Un usuario con 0,3 BTC en `Balanz · USD` puede perder **US$ 9.600** de su `capital_final` del mes por visitar `/mensual` en vez de `/dashboard` — y recuperarlos al revés.

**Mitigación mínima sin refactor:** que `MonthlySummary.jsx:267-272` use `buildPriceSymbols(pos, bkrs)` (una línea, el helper ya está importado en el archivo vecino) y que `Dashboard.jsx:498` gane el mismo `if (valuationDollar !== 'mep') return` que ya tiene el effect de snapshots treinta líneas más arriba (`:469`).

---

## BLOQUE-RESUMEN

| concepto | DIV | versiones | difieren | correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---|---:|---|---|---|---|---|
| P&L no realizado / ganancia latente | DIV-072 | 2 | SÍ — hasta invertir el signo (Δ = Σ C_i·(1/tc_compra − 1/MEP)) | ninguna sola: el persistido debe ser `today`; el display debe rotular el modo | `/dashboard` KPI "P&L no realizado" y hero de `/cartera` (modo `purchase`) vs `/mensual` col. "No realizado" y `/reportes` KPI (modo `today`) | 🔴 | preferencia de display (`costBasis`, default `purchase`) filtrándose a la mitad de los cálculos; fix aplicado en un solo lado |
| P&L no realizado / ganancia latente | DIV-073 | 2 | SÍ — no por la fórmula (son equivalentes) sino por gates y lista de precios | ninguna: fórmula de MonthlySummary + gates de ambos + `buildPriceSymbols` | `/mensual` y `/reportes`: el valor guardado depende de qué pantalla abriste último | 🔴 | dos escritores del mismo campo sin capa común; `buildPriceSymbols` existe y /mensual no lo usa |
| P&L no realizado / ganancia latente | DIV-074 | 2 | SÍ, sólo por el interés devengado de plazos fijos (el cash aporta 0 en ambas) | el KPI del Dashboard (incluir PF es lo correcto) | `/dashboard` KPI vs `/mensual` col. "No realizado" y `/reportes` | 🟡 | el rollup de PF se agregó al display y nunca al writer |
| P&L no realizado / ganancia latente | DIV-075 | 4 (2 en Dashboard, 2 en Insights) | SÍ — mismo delta que DIV-072, dentro de la misma pantalla | las versiones `today` (tortas y `aiPositions`) | `/dashboard` hero vs sus tortas tipo/sector y Top Holdings; `/analisis` card de P&L abierto vs `pnl_usd` por activo del snapshot IA | 🟠 | `costBasis` se pasó a `computeBrokerValue` y no a las memos hechas a mano al lado |
| P&L no realizado / ganancia latente | DIV-076 | 6 (4 en builder + /mensual + /wrapped) | SÍ — el número publicado es un stock acumulado de años, no del período (33× en el ejemplo) | ninguna salvo día/semana global; lo correcto es `U(fin) − U(inicio)` con bordes MtM, o `None` | `/reportes` card de mes y de año ("No realizado", sub "mark-to-market"); `/mensual` fila del mes en curso y fila TOTAL; `/wrapped` mejor/peor mes | 🔴 | un stock guardado en una columna con nombre de flujo; `builder.py:1545-1548` lo documenta y lo publica igual |
| P&L no realizado / ganancia latente | DIV-077 | 3 motores backend | SÍ — comisiones (Δ = K por lote), `asset_type` ausente (guard RF desactivado), None vs 0 | `compute_broker_value_usd` (`snapshots_job.py:158`) | snapshot del chat IA (`/ai`, `/analisis`), atribución por ticker, `/goals`, Comportamiento | 🟠 | tres ports independientes del mismo `computeBrokerValue`; el SELECT de `insights.py` no trae las columnas que su propio guard consulta |
| P&L no realizado / ganancia latente | DIV-078 | 2 | Parcial: el P&L coincide (0 vs "—"); el VALOR no (la fila muestra "—", el total cuenta el costo) | el total (`computeBrokerValue`); la fila debe mostrar el costo con marca, no "—" | `/cartera` desktop: la suma de la columna "Valor" no da el TOTAL del pie (ONs/bonos/FCIs sin cotización) | 🟡 | las filas no usan el motor canónico; sólo tres totales lo usan |
| P&L no realizado / ganancia latente | DIV-079 | 3 criterios | SÍ — con una fila futura, el latente entero desaparece de la tabla y del total | el calendario del backend (`main.py:9702`), idealmente en hora argentina y no UTC | `/mensual`: columnas "No realizado" y "Retorno", badge de mes vivo, % oculto de meses cerrados, fila TOTAL | 🟠 | criterio de "mes abierto" re-decidido en cada capa; fix idéntico ya hecho en el backend (2026-05-30) y nunca replicado al frontend |
| P&L no realizado / ganancia latente | DIV-080 | 9 | Hoy casi alineadas por parcheo repetido; 3 divergen de verdad (son DIV-073 y DIV-075) y 6 usan `tcValuacion` donde la canónica usa `cedearRate` | `valuePositionLot` (`valuation.js:543`), consumida sólo por `computeBrokerValue` | todas las superficies de valuación; el riesgo mayor es futuro (el día que MEP ≠ el rate de valuación, divergen las seis a la vez) | 🟠 | falta de capa compartida; migración a `valuePositionLot` empezada y abandonada — el bloqueo declarado (comisiones, modo `purchase`) ya está resuelto |
