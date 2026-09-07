# 1A — Veredicto: Tenencia / posición / holding

**Grupo:** Tenencia / posición / holding · 13 divergencias (DIV-121–DIV-133)
**Commit auditado:** `b74f450f` (copia de sólo lectura `/tmp/rendi-main`, `backend/main.py` = 38.029 líneas ✅)
**Citas verificadas:** 26 de 31 correctas · 5 corregidas
**Deriva `82fad6a0`:** ninguno de los hallazgos cae en `backend/pricing/fci.py`, `frontend/src/components/AddPositionFlow.jsx` ni `backend/tests/test_fci_uala.py`. No aplica.

---

## Resumen ejecutivo

La cantidad (`positions.quantity`) **no** diverge: hay una sola tabla `positions`, una fila por lote, y todos los motores leen la misma cantidad. Lo que diverge es **qué moneda tiene esa tenencia y con qué símbolo se la cotiza**, y ahí sí hay números incompatibles.

El agujero grande es uno solo, con dos caras: **el port Python de la valuación (`snapshots_job.compute_broker_value_usd`) nunca recibió la rama "lote en pesos alojado en una cuenta USD"** que el frontend tiene desde hace tiempo (DIV-124), y **su resolutor de símbolo (`position_price_key`) no mira `positions.currency`** (DIV-125). Consecuencia medida sobre el código: un CEDEAR comprado en pesos y ruteado a un sub-broker `· USD` entra al **snapshot nocturno** con su costo en PESOS contado como DÓLARES, el guard anti-distorsión lo rechaza por el mismo motivo, y el snapshot registra **US$ 707.000 donde el Dashboard muestra US$ 517** (×1.367). Si el mismo lote está en un broker USD genuino (no `· USD`), el snapshot lo cotiza por el **ADR de NYSE** en vez del `.BA` y el guard **no lo atrapa** (el múltiplo cae dentro de la banda) → publica un P&L de **−US$ 695.500** que no existe. Ese snapshot es la curva del Dashboard, el AUM del libro del asesor, el capital de Reportes y el rendimiento del período.

Segundo: en la **Cartera de escritorio**, la rama `costInPesos` de la fila (`Positions.jsx:1269-1280`) es la única de todo el sistema **sin guard anti-distorsión**, y está declarado a propósito en el comentario. En la misma pantalla, la fila muestra el valor inflado y el pie del broker lo clampea a costo: con un bono per-100 leído per-1 la fila dice **US$ 5.172** y el total dice **US$ 69**.

Tercero, sistemático y chico: **las comisiones son costo en 8 implementaciones y no lo son en 2** (DIV-122). Todo lo que pasa por `behavioral._position_value_usd` — Comportamiento, Rendi AI, Reportes, Objetivos, brief del asesor — reporta un costo más bajo y por lo tanto un P&L **siempre más optimista** que la Cartera, exactamente por la comisión de compra.

Y hay **cinco defectos que el mapa no tenía** (sección "Hallazgos nuevos"), de los cuales el más caro es que `reporting/timeline.py` pisa `positions.currency` con `brokers.currency`: un bono/ON en dólares dentro de Balanz **colapsa a 1/MEP** en la concentración y los detectores de Reportes.

---

## Tabla de veredictos

| DIV | versiones | ¿difieren de verdad? | cuál es la correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---:|---|---|---|---|---|
| DIV-121 | 9 | Sí (habilita a las demás) | `valuePositionLot` (valuation.js:543) | ninguna por sí sola — es el vector de todas | ⚪→🟠 | migración a medio hacer (SSoT escrita, sin migrar lectores) |
| DIV-122 | 10 | Sí, ~comisión/costo | con comisiones (`valuePositionLot`) | Comportamiento, Rendi AI, Reportes, Objetivos, brief asesor, detalle de posición mobile | 🟡 | fix aplicado en un solo lado (frontend) |
| DIV-123 | 4 | Sí, hasta ×75 | con guard (`valuePositionLot`) | **Cartera desktop** (`/posiciones`): fila ≠ pie en la misma tabla | 🟠 | omisión deliberada + copiar y pegar |
| DIV-124 | 2 | Sí, ×MEP (≈×1.450) | `valuePositionLot` (JS, 6 ramas) | curva del Dashboard, Reportes, libro del asesor, variación diaria | 🔴 | port incompleto (5 de 6 ramas) |
| DIV-125 | 3 | Sí, cotiza otro instrumento | `valuationPriceKey` (parent-aware + `currency`) | snapshot/curva; Comportamiento y Rendi AI en el caso sin `_byma` | 🔴 | falta de capa compartida + port incompleto |
| DIV-126 | 2 | Sí (unidades distintas) | ninguna: debe ser valor de mercado y por activo | Reportes (KPI "Top holdings") vs respuesta de Rendi AI | 🟡 | copiar y pegar + falta de SSoT |
| DIV-127 | 2 | Sí (lotes vs activos) | la de Cartera (activo·moneda) | Reportes → KPI "# posiciones" | 🟡 | falta de SSoT (SQL suelto) |
| DIV-128 | 4 | Sí (agrupa distinto) | `(broker, asset, currency)` con base canónica de especie | Home (briefing) suma CEDEAR + acción US como una tenencia | 🟡 | copiar y pegar, cada consumidor eligió su clave |
| DIV-129 | 8 (no 7) | Sí (de descartar a ×MEP) | descartar y reportar (chat IA / libro del asesor) | AUM del asesor, top holdings de Reportes, grupos del asesor | 🟠 | falta de SSoT: el "broker sin fila" nunca se definió |
| DIV-130 | 2 | Sí, y está documentado | ambas (miden cosas distintas) | ninguna hoy (replay no llega a pantalla) | ⚪ | por diseño (con `verificar_contra_hoy` como testigo) |
| DIV-131 | 2 | Sí, ~9% con caché frío | la del frontend (mep→ccl→blue, al medio) | curva/snapshot vs hero cuando `dolarapi` está frío | 🟠 | fix aplicado en un solo lado |
| DIV-132 | 4 | Sí (denominadores distintos) | ninguna: excluir debe ser explícito y reportado | pesos % de Rendi AI; días sin snapshot | 🟡 | cada capa eligió su política de faltantes |
| DIV-133 | 2 | Sí, por el monto del PF | ninguna: el PF debe entrar al snapshot | hero Dashboard/Home ≠ Cartera ≠ curva ≠ AUM asesor | 🟡 | migración a medio hacer (PF en tabla aparte) |

---

## Detalle por divergencia

### DIV-121 — La SSoT existe y no la consume nadie

**Estado de las citas:** ✅ verificadas.
`frontend/src/utils/valuation.js:543` = `export function valuePositionLot(p, ctx = {})` ✅.
El docstring que admite las cinco implementaciones está en `valuation.js:502-512` (el mapa dijo 503-509 — ✅ dentro del rango).
Consumidores reales, verificados con `grep -rn "valuePositionLot" frontend/src`: **sólo** `valuation.js:747` (dentro de `computeBrokerValue`) y `utils/valuation.test.js`. ✅ La afirmación del mapa es exacta.

**a. Implementaciones** (9, no 7 — el mapa subcuenta)

| # | Ubicación (verificada) | Qué valúa |
|---|---|---|
| 1 | `frontend/src/utils/valuation.js:543` `valuePositionLot` | **la canónica**; 6 ramas |
| 2 | `frontend/src/utils/valuation.js:360` `valueEquityLot` | 5 ramas, sin cash, sin cripto-factor |
| 3 | `frontend/src/pages/Positions.jsx:1263` `calcUSDT` + `:1321` `calcARS` | filas de la Cartera desktop |
| 4 | `frontend/src/pages/PositionsMobile.jsx:653` `enriched` | filas de la Cartera mobile |
| 5 | `frontend/src/pages/AssetDetail.jsx:34` `valueLot` | ficha del activo |
| 6 | `frontend/src/pages/PositionDetailMobile.jsx:101…176` (inline) | detalle de posición mobile |
| 7 | `frontend/src/pages/Dashboard.jsx:302` `positionsForInsight` + `:512-580` (2º chain) | insight + P&L por broker |
| 8 | `frontend/src/pages/Insights.jsx:421` `holdingValueUsd` | tortas y atribución de Análisis |
| 9 | `frontend/src/pages/HomeMobile.jsx:210-260` (inline) + `frontend/src/pages/FirstInsight.jsx:112-160` | "mejor activo" del Home / primer insight |

A eso se suman los dos motores backend: `snapshots_job.compute_broker_value_usd:158` y `behavioral._position_value_usd:391`. **Once motores de valuación por lote en total.**

**b. Fórmulas** — todas tienen la misma forma; lo que cambia es la partición del dominio y qué constantes entran:

```
V(p) = f_rama(p) ,  con  rama = ramaSegún( is_cash, ccy(broker), ccy(lote), asset_type, isCrypto, isFci, override )
```

`valuePositionLot` particiona en 6 ramas en este orden **y el orden importa**:
1. `is_cash`
2. `¬is_cash ∧ ¬isAR ∧ costInPesos(p)` — lote en pesos en cuenta USD
3. `¬is_cash ∧ isAR ∧ costInUsd(p)` — lote en dólares en broker ARS
4. `isAR` nativo
5. `(asset_type='CEDEAR' ∨ arUsd) ∧ ¬crypto ∧ ¬FCI ∧ override=∅`
6. else — USD nativo × factor cripto

**c. ¿Real o cosmética?** Por sí sola es **estructural, no numérica**: cada copia da lo mismo *hasta que una se queda atrás*. Las diferencias numéricas concretas están en DIV-122, DIV-123, DIV-124 y en los hallazgos nuevos X-2 / X-4 / X-5 — todos son "la copia N no recibió el fix K".

**d. Dictamen.** `valuePositionLot` es la correcta y ya está escrita. El defecto es no haberla enchufado.

**e. Qué ve mal el usuario y dónde.** Nada directamente por DIV-121; indirectamente, todo lo listado en las divergencias hijas.

**f. Causa raíz.** **Migración a medio hacer**, y el propio código lo dice: *"Todavía NO la consume nadie más: migrar a los cinco lectores sólo es delta 0 después de alinear los comportamientos que hoy difieren (comisiones, modo 'purchase')"* (`valuation.js:507-510`). Se escribió la SSoT, se difirió la migración, y las copias siguieron divergiendo mientras tanto.

**g. Fuente única de verdad propuesta.** `valuePositionLot` en `valuation.js`, consumida por los 9 sitios del frontend; `compute_broker_value_usd` como su port Python **generado desde la misma tabla de ramas** (hoy es una transcripción a mano de 5 de 6 ramas). Eliminar: `valueEquityLot`, `AssetDetail.valueLot`, los chains inline de `Positions/PositionsMobile/PositionDetailMobile/Dashboard/Insights/HomeMobile/FirstInsight`.

---

### DIV-122 — Las comisiones son costo en 8 lugares y no en 2

**Estado de las citas:** ⚠️ **corregida una.**
`backend/behavioral.py:426` = `invested_native = float(p.get("invested") or 0)` ✅ exacto.
`frontend/src/pages/PositionDetailMobile.js` → **la extensión real es `.jsx`**, y la línea es `PositionDetailMobile.jsx:101` (`const invested = p.invested || 0`) ✅.
El mapa dice "3 de sus 5 ramas" — verificado: el archivo tiene 6 ramas (cash + 5). Las que **omiten** comisiones son 3 (`isAR`, BYMA-en-broker-USD, `else`); las 2 que sí las suman lo hacen delegando en `pesoLotUsd` / `usdLotValue`. ✅ correcto.

**a. Implementaciones**

*(i) Con comisiones — `valuation.js:558-559`:*
```js
const comm = p.commissions || 0
const realCost = (p.invested || 0) + comm
```
Igual en `valueEquityLot:367`, `pesoLotUsd:294`, `usdLotValue:339`, `Positions.jsx:1251/1300/1343`, `PositionsMobile.jsx:662`, `AssetDetail.jsx:47`, `Dashboard.jsx:305`, `Insights.jsx:423`, `HomeMobile.jsx:240`, y en el backend `snapshots_job.py:207-208` (`real_cost = (p.get('invested') or 0) + comm`) y `advisor_groups.py:219`.

*(ii) Sin comisiones — `behavioral.py:426`:*
```python
invested_native = float(p.get("invested") or 0)
```
`grep -n "commissions" backend/behavioral.py` devuelve **una sola línea** (la 13, un comentario del docstring del módulo). El campo nunca se lee. La función usa `invested_native` como (a) valor de mercado de fallback, (b) `cost_usd` del guard anti-distorsión, y (c) el "cost basis puro" cuando la llaman con `prices={}, honor_override=False`.

*(iii) Sin comisiones — `PositionDetailMobile.jsx:101`* — ver arriba.

**b. Fórmulas**

- Casa: `C = invested + commissions`
- `behavioral` / `PositionDetailMobile` (3 ramas): `C' = invested`
- Diferencia: `C − C' = commissions`, y por lo tanto `P&L' − P&L = +commissions` y `P&L%' − P&L% ≈ commissions / invested`.

**c. ¿Real o cosmética?** **REAL.** Ejemplo: 100 AAPL, `invested = US$ 10.000`, `commissions = US$ 50`, valor de mercado US$ 11.000.

| motor | costo | P&L | P&L% |
|---|---:|---:|---:|
| Cartera (`valuePositionLot`) | 10.050 | +950 | **+9,45 %** |
| Análisis/IA (`_position_value_usd`) | 10.000 | +1.000 | **+10,00 %** |

Diferencia: US$ 50 y 0,55 pp por lote. El sesgo es **siempre en el mismo sentido** (la IA y el asesor siempre más optimistas) y se acumula sobre toda la cartera. Con comisiones argentinas típicas (0,5-1 % + derechos de mercado), sobre una cartera de US$ 100.000 son US$ 500-1.000 de P&L fantasma.

Además: `_position_value_usd` usa `invested_native` como denominador del guard (`cost_usd`). Con costo subvaluado, el múltiplo `mkt/cost` sube y el guard **se afloja** — un precio marginalmente absurdo pasa en Análisis y se clampea en la Cartera.

**d. Dictamen.** Correcta la versión **con** comisiones. La comisión de compra es costo de adquisición: sale del cash (`persister._manual_position_cost` en `main.py:8199-8203` la debita) y no puede desaparecer del cost basis. Nueve de once motores ya lo hacen así.

**e. Qué ve mal el usuario y dónde.**
- `GET /api/behavioral` → pantalla **Comportamiento** (concentración, home bias, cash drag, recency, sector) — `behavioral.py:987/1086/1095/1176/1559/1715`.
- `backend/ai/builders/dashboard.py:67-73` y `dashboard_top_holdings.py:58/96-97` → **Rendi AI** (`/ai`, chat, packets de Dashboard) — `pnl_pct` inflado.
- `backend/reporting/timeline.py:144` → **Reportes** (concentración, top holdings del período).
- `main.py:15263` (dentro de `GET /api/goals/{gid}/diagnostic`) → **Objetivos**: el valor actual del portfolio.
- `PositionDetailMobile.jsx` → **detalle de una posición en mobile**: la misma posición muestra distinto P&L% que en desktop.

**f. Causa raíz.** **Fix aplicado en un solo lado.** El fix "las comisiones son costo" recorrió el frontend archivo por archivo (los comentarios lo narran: *"este archivo era el último que no la seguía, y por eso la MISMA posición mostraba distinto P&L% en el celular que en la computadora"*, `PositionsMobile.jsx:657-661`) y **nunca cruzó a `behavioral.py`**, que es el motor de la mitad del backend. `PositionDetailMobile` quedó a mitad de camino: sus dos ramas nuevas delegan en helpers que sí suman, las tres viejas no.

**g. Fuente única de verdad propuesta.** Una función `lot_cost_basis(p) = invested + commissions` en `behavioral.py` (o mejor: en un módulo `valuation.py` compartido por `behavioral` y `snapshots_job`), usada en las tres posiciones donde hoy está `invested_native`. En el frontend, reemplazar el chain de `PositionDetailMobile.jsx:112-176` por `valuePositionLot`.

---

### DIV-123 — El guard anti-distorsión falta en una rama de la Cartera desktop

**Estado de las citas:** ✅ verificadas (el mapa no daba archivo:línea en la columna de sitios, pero sí en el texto).
`valuation.js:578-579` → la rama 2 arranca en `:578` (`if (!p.is_cash && !isAR && costInPesos(p))`) y el guard está en `:583-584` (`const trustArs = mktArs != null && trustMktValue(...)`). ⚠️ **cita del mapa levemente corrida**: el guard está en 583-584, no en 578-579.
`Positions.jsx:1267-1279` → verificado: `calcUSDT` en `:1263`, la rama `costInPesos` en `:1269-1280`, y el comentario literal **"No hay guard en esta rama → sin flip"** en `:1272`. ✅
`Insights.jsx:447-449` ✅ (`return trustMktValue(valueUsd, investedUsd, ...) ? valueUsd : investedUsd`).
`Dashboard.jsx:333-340` ✅.

**a. Implementaciones**

*(i) `Positions.jsx:1269-1280` — SIN guard:*
```js
if (costInPesos(p)) {
  const realCost = routedInvUsd(p, tcCedear)
  const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true, p.asset_type)]
  if (priceArs == null) return { value: null, ..., investedUsd: realCost }
  const value = (priceArs * p.quantity) / tcCedear
  const pnl = value - realCost
  return { value, pnl, ... }
}
```
No hay `trustMktValue` en ningún punto de esta rama. Las otras dos ramas de `calcUSDT` (`:1305-1307`) y las de `calcARS` (`:1350`) sí lo tienen.

*(ii) `valuation.js:578-590` — CON guard:*
```js
const trustArs = mktArs != null && trustMktValue(mktArs, realCost, p.asset_type, p.price_override != null)
return salida({ valueUsd: trustArs ? mktArs / cedearRate : invUsdHoy, ... })
```

*(iii) `Insights.jsx:440-449` y `Dashboard.jsx:331-340`:* misma rama, con guard.

**b. Fórmulas**

- Con guard: `V = [ 0,002 ≤ P_BA·q / C ≤ 50 ] ? P_BA·q/MEP : C/MEP` (banda `[0,02 ; 4]` si `asset_type ∈ {BOND, BONO, ON, LETRA, LECAP}`)
- Sin guard: `V = P_BA·q / MEP` siempre

donde `P_BA` = precio local en ARS, `q` = cantidad, `C` = `invested + commissions` en ARS, `MEP` = `tcCedear`.

**c. ¿Real o cosmética?** **REAL, y visible en la misma pantalla.** Caso del propio código (`valuation.js:429-433`: ON con precio manual en convención per-100):

100 nominales de una ON en pesos, cargada en un sub-broker `· USD`, `invested = ARS 100.000`, precio `.BA` leído en convención per-100 → ARS 75.000 en vez de ARS 750. MEP = 1.450. `asset_type = 'ON'` → banda `[0,02 ; 4]`.

| lugar | cuenta | número |
|---|---|---:|
| **fila** de la Cartera (`calcUSDT`, sin guard) | `75.000 × 100 / 1.450` | **US$ 5.172,41** |
| **pie del broker** (`computeBrokerValue` → `valuePositionLot`) | `mult = 7.500.000/100.000 = 75 > 4` → clampea | **US$ 68,97** |

**×75 de diferencia entre la fila y el total, en la misma tabla.** El mismo comentario del archivo (`Positions.jsx:1377-1381`) narra un incidente idéntico: *"10 filas que sumaban USD 64.147,88 sobre un TOTAL de USD 56.582,51"*.

**d. Dictamen.** Correcta la versión **con** guard. El comentario "No hay guard en esta rama → sin flip" describe una decisión de UX (evitar que la fila "salte" a costo) que no puede ganarle a la consistencia con el total que se dibuja tres centímetros abajo. Si se quiere evitar el flip, la solución es mostrar el clamp explícitamente (badge "precio no confiable"), no calcular distinto.

**e. Qué ve mal el usuario y dónde.** **`/posiciones` (Cartera, desktop)** — columna "Valor" y "P&L" de cualquier lote con `currency='ARS'` alojado en un broker USD (típicamente el sibling `<Padre> · USD`) cuyo precio `.BA` sea absurdo. La suma de las filas no da el total del pie. En **mobile** (`PositionsMobile.jsx:743-750`) esa misma rama **sí** guardea (`priceTrusted = u.priceUsd != null && trustMktValue(...)`) → desktop y mobile muestran distinto para el mismo lote.

**f. Causa raíz.** **Copiar y pegar + una omisión deliberada.** El guard se fue agregando rama por rama a medida que aparecían bugs; esta rama recibió el comentario que documenta la ausencia en lugar del guard.

**g. Fuente única de verdad propuesta.** `valuePositionLot` para las filas de la Cartera. Con eso, fila y pie salen literalmente de la misma función y el invariante "Σfilas = pie" es aritmético, no una convención que hay que sostener a mano en 4 archivos.

---

### DIV-124 — El port Python del motor no tiene la rama "lote en pesos en cuenta USD" 🔴

**Estado de las citas:** ✅ verificadas.
`backend/snapshots_job.py:158` = `def compute_broker_value_usd(` ✅.
`snapshots_job.py:284-306` = el brazo `else` (moneda base USD); el `else` **arranca en `:283`** con el comentario `# USDT / USD — moneda base USD` en `:284`. ⚠️ **corrección menor**: el brazo es `:283-306`.
Verificado con `grep`: en todo `compute_broker_value_usd` la palabra `currency` sólo aparece dentro de `_cost_in_usd(p)` (`:195-200`), y ese helper **sólo se invoca en el brazo ARS** (`:243`). El brazo USD no consulta `p['currency']` en ninguna línea. ✅ El mapa acierta.

**a. Implementaciones**

*(i) `valuation.js:578-596` — rama 2 (JS, existe):*
```js
if (!p.is_cash && !isAR && costInPesos(p)) {
  const invUsd = realCost / costBasisRate(p, cedearRate, costBasis)
  const invUsdHoy = realCost / cedearRate
  const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true, p.asset_type)]
  const mktArs = priceArs != null ? priceArs * (p.quantity || 0) : null
  const trustArs = mktArs != null && trustMktValue(mktArs, realCost, p.asset_type, ...)
  return salida({ investedUsd: trustArs ? invUsd : invUsdHoy,
                  valueUsd:    trustArs ? mktArs / cedearRate : invUsdHoy, ... })
}
```

*(ii) `snapshots_job.py:283-306` — brazo USD (Python, no existe la rama):*
```python
else:
    # USDT / USD — moneda base USD
    if p.get('is_cash'): ...
    else:
        cf = _cb_factor(p['asset'], broker_name, override is not None, _cripto_rate, cedear_rate)
        invested += real_cost * cf          # ← real_cost EN PESOS contado como USD
        if (asset_type == 'CEDEAR' or ar_usd) and override is None and ...:
            price_ars = prices.get(f"{p['asset']}.BA")
            if price_ars is not None:
                mkt_usd = (price_ars * (p.get('quantity') or 0)) / cedear_rate
                value += mkt_usd if _trust_mkt_value(mkt_usd, real_cost, asset_type) else real_cost
```
`real_cost` viene de `:207-208` sin ninguna conversión: `real_cost = (p.get('invested') or 0) + comm`.

**b. Fórmulas**

Sea `C_ars` el costo del lote en pesos, `P_BA` su precio local, `q` la cantidad, `M` el MEP.

- **JS (correcto):** `Inv = C_ars/M` ; `V = [guard(P_BA·q , C_ars)] ? P_BA·q/M : C_ars/M`
- **Python (roto):** `Inv = C_ars` (¡en USD!) ; `V = [guard(P_BA·q/M , C_ars)] ? P_BA·q/M : C_ars`

El guard del Python compara **dólares contra pesos**. El múltiplo que evalúa es `(P_BA·q/M)/C_ars ≈ 1/M ≈ 0,00069`, que cae **por debajo** del piso 0,002 → **siempre rechaza el precio** y devuelve `C_ars` como valor en dólares.

**c. ¿Real o cosmética?** **REAL y del tamaño del MEP.** Ejemplo: 100 CEDEARs de AAPL en `Balanz · USD` con `currency='ARS'` (compra en pesos mal ruteada), `invested = ARS 700.000`, `commissions = ARS 7.000`, `AAPL.BA = ARS 7.500`, MEP = 1.450.

| motor | invested | value | P&L |
|---|---:|---:|---:|
| Dashboard / Cartera (`valuePositionLot`) | US$ 487,59 | US$ 517,24 | +US$ 29,65 (+6,1 %) |
| **Snapshot nocturno** (`compute_broker_value_usd`) | **US$ 707.000** | **US$ 707.000** | US$ 0 |

**El snapshot registra US$ 707.000 donde el Dashboard muestra US$ 517: ×1.367.** El mismo día en que ese lote aparece, la curva de patrimonio da un salto vertical y el "rendimiento del período" de Reportes queda destruido.

Nota: el guard de cobertura de precios (`snapshots_job.py:718-733`) **no protege**: su `_cost_usd(p)` decide la moneda por `broker_ccy[p['broker']]`, no por `p['currency']` → cuenta ese lote como US$ 707.000 de costo con precio disponible, y con eso la cobertura da 100 %.

**d. Dictamen.** Correcta la versión JS. Falta portar la rama 2 al Python:
```
si  broker.currency ∈ {USD, USDT}  ∧  p.currency = 'ARS'  ∧  ¬crypto(p.asset):
    Inv = (invested + commissions) / MEP
    V   = guard(P_BA·q , invested+commissions) ? P_BA·q/MEP : Inv
```
(el guard comparando en **pesos**, como hace el JS).

**e. Qué ve mal el usuario y dónde.**
- **Gráfico de patrimonio del Dashboard** y **`/reportes`** → escritos por `snapshot_user` (`snapshots_job.py:745-760`), tabla `snapshots`.
- **`GET /api/advisor/book`** (`main.py:36945+`) → AUM, distribución y motor estrella del **libro del asesor**: usa `compute_broker_value_usd` por posición (`main.py:36926-36930`).
- **Chat de Rendi AI**: `_valuate_positions_for_chat` (`main.py:22879-22881`) llama al mismo motor por lote.
- **Variación diaria / "P&L Día"**: se calcula contra el último snapshot (`Dashboard.jsx:641-644`, `HomeMobile.jsx:197-203`) — un snapshot inflado ×1.367 produce una "pérdida" del mismo tamaño al día siguiente.

**f. Causa raíz.** **Port incompleto.** El docstring del Python dice *"Equivalente Python de frontend `computeBrokerValue` (port fiel, incluida la rama CEDEAR)"* (`:169-170`) — el port se hizo a mano, rama por rama, y se transcribieron 5 de 6. El JS tiene un comentario que documenta exactamente el bug que el Python todavía tiene: *"Sin esto el costo en pesos se contaba como dólares (invertido inflado ~MEP×) y el guard de confianza comparaba USD vs pesos"* (`valuation.js:572-576`).

**g. Fuente única de verdad propuesta.** Cortar el port a mano: extraer la tabla de ramas a un contrato compartido (mismo JSON de casos de prueba corriendo en Jest y en pytest, con los mismos fixtures) para que una rama nueva en JS **falle** el test de Python hasta que se porte. Mientras tanto: agregar la rama faltante y un test de paridad `valuePositionLot` ↔ `compute_broker_value_usd` sobre las 6 ramas × {con precio, sin precio, precio absurdo}.

---

### DIV-125 — Tres definiciones de "con qué símbolo se cotiza esta tenencia" 🔴

**Estado de las citas:** ✅ verificadas.
`snapshots_job.py:105` = `def position_price_key(...)` ✅
`behavioral.py:166` = `def _price_is_ars(p)` ✅
`behavioral.py:229-234` — el bloque que admite la lista incompleta está en `:230-236` dentro de `stamp_positions_currency` (que arranca en `:225`); `_AR_BROKER_HINTS` se define en `:112`. ⚠️ **cita del mapa corrida 1-2 líneas**; el contenido es exacto: *"esa lista (`_AR_BROKER_HINTS`) NO cubre todos los brokers AR (ej. 'Santander', 'Galicia', 'PPI', 'Mercado Pago')"*.
`valuation.js:469` = `export function valuationPriceKey(p, isArsBroker)` ✅

**a. Implementaciones**

*(i) `valuation.js:469-476` — frontend:*
```js
if (p.is_cash) return null
if (isArsBroker) return priceSymbol(p.asset, true, p.asset_type)
if (isCrypto(p.asset)) return priceSymbol(p.asset, false, p.asset_type)
if (isArUsdBroker(p.broker) || costInPesos(p)) return priceSymbol(p.asset, true, p.asset_type)
return priceSymbol(p.asset, false, p.asset_type)
```
`isArUsdBroker` (`:191-201`) es **parent-aware**: mira `parent_broker_id` en el registry y sólo cae al regex `/·\s*USD$/` si el broker no está registrado. `costInPesos` (`:214-219`) mira `p.currency === 'ARS'`.

*(ii) `snapshots_job.py:105-128` — snapshot:*
```python
if (asset or '').startswith('FCI:'): return asset
if asset in _crypto_symbol_set(): return asset
wants_ba = (broker in ars_names or broker in ar_usd_names
            or (p.get('asset_type') or '').upper() == 'CEDEAR')
return f"{asset}.BA" if wants_ba else asset
```
`ar_usd_names` sale de `_broker_name_sets` (`:74-87`), que **sí** es parent-aware. **Nunca consulta `p['currency']`.**

*(iii) `behavioral.py:166-193` — Análisis/IA:*
```python
if asset in CRYPTO_SYMBOLS: return False
if (p.get("asset_type") or "").upper() == "CEDEAR": return True
if "_byma" in p: return bool(p["_byma"])          # parent-aware, si fue estampado
broker = p.get("broker") or ""
if _is_ar_usd_subbroker(broker) or _is_ars_broker(broker): return True
return (p.get("currency") or "").strip().upper() == "ARS"
```
`_is_ars_broker` cae a `_AR_BROKER_HINTS = ("cocos","iol","bull","balanz","naranja","ppi","invertironline","ieb")` (`:112`) — **heurística por substring del nombre del broker**.

**b. Fórmulas** — la decisión es booleana (`usar .BA` vs `usar ticker US`), pero cambia el valor por un factor de decenas:

| condición del lote | JS `valuationPriceKey` | Python `position_price_key` | `behavioral._price_is_ars` |
|---|---|---|---|
| broker ARS | `.BA` | `.BA` | `.BA` (si `_byma` estampado o nombre en hints o `currency='ARS'`) |
| `asset_type='CEDEAR'` en cualquier lado | `.BA` | `.BA` | `.BA` |
| sub-broker `· USD` de padre AR | `.BA` (parent-aware) | `.BA` (parent-aware) | `.BA` (`_byma`) |
| **`currency='ARS'`, `asset_type=NULL`, broker USD genuino** | **`.BA`** | **ticker US** ❌ | `.BA` |
| broker AR sin hint (Santander/Galicia) y sin `_byma` estampado | `.BA` | `.BA` (por `ars_names`) | **ticker US** ❌ |

**c. ¿Real o cosmética?** **REAL, y el guard no la atrapa.** Ejemplo: 100 acciones de GGAL compradas en pesos (`currency='ARS'`, `asset_type=NULL`) que quedaron ruteadas a un broker USD genuino (`Charles Schwab`, sin padre AR). `invested = ARS 700.000`. `GGAL.BA = ARS 7.500`. ADR `GGAL` en NYSE = US$ 45. MEP = 1.450.

| motor | símbolo | invested | value | P&L |
|---|---|---:|---:|---:|
| Cartera / Dashboard | `GGAL.BA` | US$ 482,76 | US$ 517,24 | +US$ 34,48 |
| **Snapshot** | `GGAL` (ADR) | **US$ 700.000** | 100×45 = **US$ 4.500** | **−US$ 695.500** |

El guard del snapshot evalúa `mult = 4.500 / 700.000 = 0,0064`, que **cae dentro** de `[0,002 ; 50]` → **confía en el precio equivocado**. Los dos errores (moneda del costo y símbolo del precio) se combinan hasta un múltiplo plausible y el clamp no dispara. Es el peor de los dos mundos: el sistema no se da cuenta.

Segundo caso, simétrico: un CEDEAR en "Santander" (broker con `currency='ARS'` pero sin hint en el nombre) en un path que **no** llame `currency_context` → `_byma` ausente → `_is_ars_broker("Santander")` = False → si además `currency` está NULL, `_price_is_ars` devuelve False y **Comportamiento** lo cotiza por el ticker US: el propio código estima el daño en *"inflado 3-29×"* (`ai/builders/dashboard.py:53-55`).

**d. Dictamen.** Correcta la del frontend (`valuationPriceKey`): es la única que combina las tres señales que importan — `brokers.currency`, `parent_broker_id` y `positions.currency` — sin heurística de nombre. `position_price_key` debe agregar la condición `p['currency']=='ARS'` a `wants_ba`. `_price_is_ars` debe dejar de tener fallback por nombre: si `_byma` no está estampado, es un bug del caller, no algo que se adivine con una lista de 8 substrings.

**e. Qué ve mal el usuario y dónde.**
- **Snapshot / curva de patrimonio / Reportes / libro del asesor**: el caso `currency='ARS'` en broker USD genuino (arriba).
- **Comportamiento** (`/comportamiento`, `GET /api/behavioral`) y **Rendi AI** (`/ai`): el caso "broker AR sin hint y sin `_byma`".
- **Análisis** (`/analisis`): `Insights.jsx:421` usa su propia rama y no comparte esta decisión.

**f. Causa raíz.** **Falta de una capa compartida.** Tres capas resuelven la misma pregunta y cada una tiene una historia distinta de parches: el JS ganó `costInPesos`, el Python ganó `parent_broker_id`, y `behavioral` ganó `_byma` con una heurística de nombre debajo que sus propios comentarios reconocen incompleta.

**g. Fuente única de verdad propuesta.** **Una** función, en el backend, que devuelva `(price_symbol, cost_currency)` para un lote a partir de `(positions.currency, brokers.currency, parent_broker_id, asset_type, asset)`, expuesta en el payload de `GET /api/positions` como dos campos estampados (`_price_symbol`, `_cost_ccy`). Así el frontend **deja de decidir** y las tres capas leen el mismo dato. Eliminar: `_price_is_ars`, `_AR_BROKER_HINTS`, `_is_ars_broker`, `position_price_key`, `valuationPriceKey`.

---

### DIV-126 — Dos "Top holdings" con unidades distintas

**Estado de las citas:** ✅ verificadas.
`backend/main.py:32810-32821` → el `SELECT` de `top_rows` arranca en `:32810` y `ORDER BY invested_usd DESC LIMIT 3` está en `:32819`; la materialización llega hasta `:32828`. ✅
`backend/ai/builders/dashboard_top_holdings.py:123-124` → `:123` = `enriched.sort(key=lambda x: x["value_usd"], reverse=True)`, `:124` = `top = enriched[:8]`. ✅

**a. Implementaciones**

*(i) Reportes — `main.py:32810-32828`:*
```sql
SELECT p.asset, p.broker, COALESCE(p.invested,0) AS invested,
       COALESCE(p.invested,0) / (CASE WHEN UPPER(COALESCE(br.currency,'')) = 'ARS' THEN ? ELSE 1 END) AS invested_usd
  FROM positions p LEFT JOIN brokers br ON br.user_id=p.user_id AND br.name=p.broker
 WHERE p.user_id=? AND COALESCE(p.is_cash,0)=0 AND COALESCE(p.quantity,0)>0
 ORDER BY invested_usd DESC LIMIT 3
```

*(ii) Rendi AI — `dashboard_top_holdings.py:86-124`:*
```python
value_usd = _position_value_usd(p, prices, tc_blue, tc_cedear)
...
enriched.sort(key=lambda x: x["value_usd"], reverse=True)
top = enriched[:8]
```

**b. Fórmulas**

- Reportes: `rank = invested_lote / (broker.currency='ARS' ? MEP : 1)`, top 3, **una fila por LOTE**.
- Rendi AI: `rank = V(lote)` con `V` = `_position_value_usd`, top 8, **una fila por LOTE**.

**c. ¿Real o cosmética?** **REAL, en tres ejes a la vez.**

1. **Costo vs valor.** Un lote comprado a US$ 1.000 que hoy vale US$ 3.000 y otro comprado a US$ 2.000 que hoy vale US$ 1.500: Reportes rankea el segundo primero; Rendi AI, el primero. Se contradicen en la misma sesión.
2. **Por lote, no por activo.** Tres compras de AAPL de US$ 5.000 cada una **llenan el top 3 entero de Reportes con "AAPL" tres veces**, y el activo que realmente es la segunda posición del usuario no aparece.
3. **Moneda decidida por el broker, no por el lote.** `CASE WHEN br.currency='ARS'` ignora `p.currency` → un bono en dólares dentro de Balanz se divide por el MEP (colapsa 1.450×) y desaparece del ranking; un lote en pesos en un `· USD` no se divide y lo copa.

Además `invested` en el SQL **no suma `commissions`** (DIV-122 otra vez) y `_position_value_usd` tampoco.

**d. Dictamen.** **Ninguna de las dos es correcta.** Debe ser: *valor de mercado, agregado por activo (con base canónica de especie), moneda resuelta por lote*. O sea `Σ_lotes V(lote)` agrupado por `cedearEspecieBase(asset)`, exactamente lo que hace `CarteraList.jsx:111-118`.

**e. Qué ve mal el usuario y dónde.**
- `GET /api/reports/period` → **`/reportes`**, tarjeta "Top holdings" del período: lista costos, puede repetir el mismo ticker 3 veces, y omite las tenencias en dólares dentro de brokers ARS.
- Packet `dashboard.top_holdings` → **Rendi AI** (`/ai` y chat): "tus mayores posiciones son…". El usuario pregunta lo mismo dos veces en la app y recibe dos listas distintas.

**f. Causa raíz.** **Copiar y pegar + falta de SSoT.** Dos equipos-momentos escribieron "top holdings"; uno lo resolvió en SQL (rápido, sin precios) y otro en Python (con el valuador). Nadie definió qué es un "holding".

**g. Fuente única de verdad propuesta.** Una función `top_holdings(conn, uid, *, n, broker_filter)` en `reporting/` que agrupe por activo, valúe con el motor canónico y devuelva `{asset, value_usd, invested_usd, weight_pct}`. Consumida por Reportes y por el builder de IA. Eliminar el SQL de `main.py:32810-32828`.

---

### DIV-127 — "# posiciones" cuenta lotes, la Cartera cuenta activos

**Estado de las citas:** ✅ verificada.
`backend/main.py:32706-32713` → el `SELECT COUNT(*)` arranca en `:32706` y `positions_count = int(pos_row["cnt"] or 0)` está en `:32713`. ✅

**a. Implementaciones**

*(i) Reportes — `main.py:32706-32713`:*
```sql
SELECT COUNT(*) AS cnt FROM positions
 WHERE user_id=? AND COALESCE(is_cash,0)=0 AND COALESCE(quantity,0)>0 {br_clause}
```

*(ii) Cartera — `Positions.jsx:1198-1224` (`aggregateAndSort`):*
```js
const k = unified ? p.asset : `${p.asset}::${ccy}`
if (!byAsset.has(k)) byAsset.set(k, { asset: p.asset, ccy, lots: [] })
byAsset.get(k).lots.push(p)
```
Una fila por `(asset, moneda)` dentro de un broker; en la tarjeta de cuenta unificada, una por `asset`.

**b. Fórmulas**

- Reportes: `N = |{ fila ∈ positions : ¬is_cash ∧ quantity > 0 }|`
- Cartera: `N' = |{ (broker, asset, ccy) : ∃ fila con quantity > 0 }|` (y `N'' = |{(cuenta, asset)}|` en la vista unificada)

Verificado en el esquema: `positions` (`schema_pg.sql:1431-1449`) **no tiene índice único** sobre `(user_id, broker, asset)` y tiene `entry_date` y `tc_compra` por fila → es una tabla **por lote**. ✅ La premisa del mapa es correcta.

**c. ¿Real o cosmética?** **REAL.** Un usuario con DCA mensual sobre 5 activos durante 12 meses tiene 60 filas: **Reportes dice "60 posiciones"**, la Cartera muestra **5 filas**. No es una diferencia de redondeo, es un factor 12.

Y hay un tercer conteo en la misma pantalla: `N'''` = cuentas activas (`main.py:32729-32731`), que sí se colapsa al padre con `COALESCE(pb.name, br.name)`. O sea que en Reportes conviven un conteo que colapsa lotes de cuenta (correcto) y uno que no colapsa lotes de activo.

**d. Dictamen.** Correcta la de la Cartera: "# posiciones" en el lenguaje del usuario es "cuántas cosas distintas tengo", no "cuántas veces compré". La misma decisión ya está tomada y documentada para el conteo de cuentas dos KPIs más abajo (`main.py:32717-32728`: *"Contarlo aparte hacía que un usuario con UN broker bimonetario leyera 'en 2 brokers'"*) — el argumento aplica idéntico acá.

**e. Qué ve mal el usuario y dónde.** `GET /api/reports/period` → **`/reportes`**, KPI "# posiciones" (y su gemelo en `portfolio_snapshot`, `main.py:32846+`). El número está inflado por el factor de fragmentación de lotes del usuario.

**f. Causa raíz.** **Falta de SSoT**: un `COUNT(*)` escrito directo contra la tabla sin pasar por ninguna definición de "posición".

**g. Fuente única de verdad propuesta.** `COUNT(DISTINCT (asset, COALESCE(currency, br.currency)))` con el mismo colapso padre↔sibling que ya usa el conteo de cuentas, encapsulado junto a `count_broker_accounts` en `ai/plan.py` (que ya es la SSoT de "cuántas cuentas").

---

### DIV-128 — Cuatro claves de agregación por activo

**Estado de las citas:** ⚠️ **dos corregidas.**
`main.py:22881` → **incorrecta**. En `:22881` está `continue` (el descarte del huérfano). La clave `(broker, asset)` está en **`main.py:22891`**: `key = (p.get('broker'), p.get('asset'))`, con el dict declarado en `:22871`.
`briefing.py:44` → **ruta incompleta**: el archivo es **`backend/home/briefing.py`**; `_user_holdings` se define en `:39` y el `GROUP BY asset` está en `:44-48`. ✅ el contenido es exacto.
`Positions.jsx:1207` ✅ (`const k = unified ? p.asset : \`${p.asset}::${ccy}\``).
`CarteraList.jsx:114-116` ✅ (`const base = onBA ? cedearEspecieBase(p.asset) : baseTicker(p.asset)` en `:115`).

**a. Implementaciones**

| # | Ubicación verificada | Clave |
|---|---|---|
| 1 | `Positions.jsx:1207` | `(asset, ccy)` por broker · `asset` en la tarjeta unificada |
| 2 | `main.py:22891` | `(broker, asset)` — chat de Rendi AI |
| 3 | `backend/home/briefing.py:44-48` | `asset` — **cross-broker y cross-moneda** |
| 4 | `CarteraList.jsx:115` | `cedearEspecieBase(asset)` si cotiza en BYMA, `baseTicker(asset)` si no |

**b. Fórmulas**

```
H₁(b,a,c) = Σ{ lotes con broker=b, asset=a, ccy=c }
H₂(b,a)   = Σ{ lotes con broker=b, asset=a }
H₃(a)     = Σ{ lotes con asset=a }                      ← suma cantidades de brokers y monedas distintas
H₄(base)  = Σ{ lotes con cedearEspecieBase(asset)=base } ← colapsa 'SI' (pesos) y 'SID' (dólar-MEP)
```

**c. ¿Real o cosmética?** **REAL, y `H₃` es la peligrosa.** `backend/home/briefing.py:44-48`:
```sql
SELECT asset, SUM(quantity) AS qty, SUM(invested) AS invested
  FROM positions WHERE user_id=? AND is_cash=0 GROUP BY asset HAVING SUM(quantity)>0
```
Suma **cantidades de instrumentos que no son la misma unidad**: 20 CEDEARs de AAPL en Cocos (ratio 20:1 → equivalen a 1 acción) + 5 acciones AAPL en Schwab = "25 AAPL". Y suma `invested` mezclando pesos con dólares en un solo número (ARS 700.000 + US$ 5.000 = "705.000").

Y `H₄` vs `H₁`: la pata pesos `SI` y la pata dólar-MEP `SID` del mismo CEDEAR son **dos filas** en la Cartera y **un holding** en Calidad de cartera.

Mitigante para `H₃`: en `briefing.py` el `invested` sumado **no se muestra** — sólo se cruza con `quotes` para el `change_pct` y el precio (`:54-63`, `:170-176`). O sea que hoy el daño está contenido a la card "AAPL subió hoy", que es correcta. Pero el helper está publicado y cualquier consumidor nuevo hereda el bug.

**d. Dictamen.** La correcta depende del propósito, y ése es el punto: hay que **nombrar** los dos conceptos en vez de tener cuatro claves anónimas.
- "Tenencia" (lo que se valúa y se muestra en la Cartera) = `(broker, asset, currency)` — `H₁`.
- "Exposición a una empresa" (lo que se analiza y se reporta) = `cedearEspecieBase(asset)` cross-broker, **valuada** (nunca cantidades sumadas crudas) — `H₄`.

`H₂` es un caso particular de `H₁` que ignora la moneda → un ticker con pata pesos y pata dólar se fusiona mal en el chat. `H₃` es directamente incorrecta.

**e. Qué ve mal el usuario y dónde.**
- **Home** (`/`, tarjetas de novedades personales, `briefing.py:170-176`): la cantidad de un activo que está en dos brokers con ratios distintos.
- **Chat de Rendi AI** (`main.py:22891`): "tu posición más grande" fusiona pata pesos y pata dólar del mismo ticker en el mismo broker sin distinguir la moneda del costo.
- **Cartera** vs **Calidad de cartera** (`/calidad`): mismo usuario, dos conteos de "cuántos activos tengo".

**f. Causa raíz.** **Copiar y pegar**: cada consumidor escribió su `GROUP BY` con lo que necesitaba en ese momento; no existe un tipo "Holding" en el sistema.

**g. Fuente única de verdad propuesta.** Dos funciones explícitas en el backend: `holdings_por_tenencia(uid)` → `(broker, asset, ccy)` y `exposicion_por_empresa(uid)` → `cedearEspecieBase`, ambas devolviendo **valor**, nunca cantidades sumadas cross-instrumento. Borrar `_user_holdings` de `briefing.py`.

---

### DIV-129 — Ocho defaults distintos para una tenencia huérfana

**Estado de las citas:** ⚠️ **dos corregidas.**
`advisor_groups.py:203-205` → **corrida**: el `COALESCE(b.currency,'ARS') bc` está en **`:202`** y su uso en **`:219-221`**. ✅ contenido exacto.
`main.py:22874-22880` → **corrida**: `if bccy is None:` está en **`:22875`** y el `continue` en **`:22881`**. ✅ contenido exacto.
`main.py:36906-36914` ✅ (`if bccy is None:` en `:36907`, `continue` en `:36914`).
`valuation.js:741` ✅ (`const bpos = allPositions.filter(p => p.broker === broker.name)`).
`valuation.js:191-202` ✅ (`isArUsdBroker`; el fallback por sufijo está en `:200`).
"USDT en el persister" → el anclaje real que encontré es `backend/importing/persister.py:613` (`broker_currency = br["currency"] if br else "USDT"`) y `:1039` (`asset_name = "ARS" if currency == "ARS" else "USDT"`). El mapa no daba línea; queda anclado.

**a. Implementaciones** — qué hace cada capa cuando `positions.broker` no tiene fila en `brokers`:

| # | Ubicación verificada | Default |
|---|---|---|
| 1 | `importing/persister.py:613` | `'USDT'` |
| 2 | `main.py:32812` (`CASE WHEN UPPER(COALESCE(br.currency,''))='ARS' THEN ? ELSE 1`) | **USD** (no divide) |
| 3 | `advisor_groups.py:202, 229` (`COALESCE(b.currency,'ARS')`) | **ARS** (divide por MEP) |
| 4 | `main.py:22875-22881` | **descarta** (con comentario explicando por qué) |
| 5 | `main.py:36907-36914` | **descarta** + cuenta en `stats['orphan_broker']` |
| 6 | `valuation.js:741` + callers que iteran `brokers` | **descarta** (nunca entra a ningún broker) |
| 7 | `valuation.js:200` | **fallback por sufijo del nombre** (`/·\s*USD$/`) |
| 8 | **`snapshots_job.py:751-753`** (no estaba en el mapa) | **descarta en silencio**: `for b in brokers: bpos = [p for p in positions if p['broker']==b['name']]` |

**b. Fórmulas** — para una tenencia huérfana de costo `C` (nominalmente en pesos):

```
persister   → se persiste como si el broker fuera USDT
Reportes    → invested_usd = C                    (pesos contados como dólares, ×MEP inflado)
advisor_gr. → val = C / MEP                       (si el broker era USD, colapsa 1/MEP)
chat IA     → ∅
libro ases. → ∅  (contabilizado)
frontend    → ∅
snapshot    → ∅  (silencioso, ni siquiera contado)
```

**c. ¿Real o cosmética?** **REAL, y con signo opuesto según la pantalla.** Un lote huérfano de `ARS 1.450.000` (= US$ 1.000 al MEP 1.450):

| pantalla | número que publica |
|---|---:|
| Reportes → top holdings | **US$ 1.450.000** |
| Grupos del asesor | **US$ 1.000** |
| Dashboard / Cartera / curva / chat IA / libro | **US$ 0** (no existe) |

Tres respuestas para la misma tenencia, con un rango de ×1.450. Y el caso #8 es el más traicionero: `snapshot_user` **no reporta** las posiciones que descarta (a diferencia del libro, que las cuenta en `stats`), así que el total del snapshot puede estar corto sin ninguna señal. El guard de cobertura de precios (`:718-733`) tampoco lo detecta porque itera `positions`, no `brokers`.

**d. Dictamen.** Correctas las #4/#5 (**descartar y reportar el conteo**). El resto son inventos: sin `brokers.currency` no hay información para decidir la moneda, y cualquier default fabrica un número. Pero descartar en silencio (#6, #8) tampoco alcanza: el usuario tiene que enterarse de que hay tenencia que no se está valuando.

La causa de fondo está catalogada aparte (memoria "Broker Data Model": los brokers se linkean **por NOMBRE, no por FK** en 6 tablas, así que un rename sin cascada crea huérfanos). Mientras el link sea por nombre, esto se va a seguir produciendo.

**e. Qué ve mal el usuario y dónde.**
- **`/reportes`** → "Top holdings": un huérfano en pesos aparece primero con un monto ×MEP.
- **Vista de grupos del asesor** (`advisor_groups.py`): un cliente puede caer en el grupo de patrimonio equivocado — es exactamente el bug que el comentario `:189-192` dice haber arreglado para otro caso (*"US$ 15.000 se leían como US$ 45.000 y el cliente entraba a un grupo 'más de US$ 20.000' que no le corresponde"*).
- **Dashboard / Cartera / curva**: la tenencia simplemente no está, sin aviso.

**f. Causa raíz.** **Falta de SSoT + modelo de datos sin FK.** Nunca se definió qué es una posición huérfana, así que cada call site improvisó; y el modelo permite que se creen.

**g. Fuente única de verdad propuesta.** Una función `resolve_position_ccy(conn, uid, p) -> str | None` que devuelva `None` para el huérfano, y **una política única**: excluir + contar + exponer el conteo en un endpoint de salud que el frontend muestre como banner ("N tenencias sin cuenta asociada"). En paralelo: FK real `positions.broker_id → brokers.id` (fuera del alcance de este grupo, pero es la cura).

---

### DIV-130 — `positions` vs `ledger_replay.tenencia_en`

**Estado de las citas:** ✅ verificada.
`backend/ledger_replay.py:35` = `def tenencia_en(conn, uid, fecha, *, session_id=None) -> dict:` ✅

**a. Implementaciones**

*(i) `positions`* — estado materializado. Contiene: importaciones confirmadas, **altas manuales** (`main.py:_insert_manual_position`), **semillas de foto de tenencia** (`importing/tenencia.py`, `seed.py`), ajustes de split, y los efectos de los rebuild FIFO.

*(ii) `ledger_replay.tenencia_en:35-82`:*
```python
SELECT n.broker, n.asset_symbol, n.operation_type, n.quantity
  FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id
 WHERE b.user_id=? AND n.excluded_at IS NULL
   AND (b.status='confirmed' OR b.id=?) AND n.date<=? AND n.asset_symbol IS NOT NULL
   AND n.operation_type IN (BUY, SELL)
 ORDER BY n.date ASC, CASE n.operation_type WHEN BUY THEN 0 ELSE 1 END ASC, n.id ASC
...
return {k: v for k, v in pos.items() if v > 1e-9}      # descarta negativos
```

**b. Fórmulas**

```
T_pos(b,a)      = positions.quantity                                (estado, todas las fuentes)
T_replay(b,a,d) = Σ_{tx ≤ d, batch confirmado} (+q si BUY, −q si SELL)   , si > 1e-9
```

`T_replay` **no aplica FIFO** (no hay pool ni matching de lotes; sólo suma neta de nominales) y descarta los negativos.

**c. ¿Real o cosmética?** **REAL y conocida.** El módulo lo dice en su propio encabezado (`ledger_replay.py:9-19`): *"Un replay sobre un ledger incompleto devuelve una cartera MÁS CHICA que la real — y eso, encadenado, se lee como una pérdida que nunca existió."* Fuentes de desvío enumeradas por el propio código: transferencias de títulos filtradas por el validator, altas manuales fuera del ledger, y (hasta el fix documentado en `:44-56`) los batches revertidos.

El dato de campo que el propio módulo registra es contundente: sin el filtro `b.status`, el replay metía **208.950 filas de batches revertidos en 313 usuarios (59 %)**, y a un usuario con **cero posiciones** le devolvía **82 activos**.

**d. Dictamen.** **Las dos son correctas para lo que miden** y no hay que unificarlas: `positions` es "qué tenés", `tenencia_en` es "qué explica el ledger". La divergencia **es la métrica**, y `verificar_contra_hoy` (`:134-166`) existe justamente para medirla: `reproducible = (no hay diferencias > 1 %)`.

Lo que sí es un defecto: `verificar_contra_hoy` compara contra `SELECT broker, asset, SUM(quantity) GROUP BY broker, asset` (`:147-151`) — o sea `H₂` de DIV-128, **sin moneda**. Un activo con pata pesos y pata dólar suma bien por casualidad (mismos nominales), pero si el ledger tiene una sola de las dos patas el diagnóstico "ledger_incompleto" no dice cuál.

**e. Qué ve mal el usuario y dónde.** **Nada hoy**: `tenencia_en` no llega a ninguna pantalla; alimenta la reconstrucción de bordes históricos (`_simbolo_de:169+`) y el diagnóstico. El riesgo es futuro: si un valor reconstruido se publica sin chequear `verificar_contra_hoy`, se publica una pérdida que no existió.

**f. Causa raíz.** **Por diseño**, y bien documentada. No es deuda.

**g. Fuente única de verdad propuesta.** Ninguna unificación. Sí: (a) que `verificar_contra_hoy` agrupe por `(broker, asset, currency)`, y (b) que **ningún** consumidor de `ledger_replay` pueda publicar un valor sin pasar antes por `verificar_contra_hoy` (hoy es una convención, no un gate).

---

### DIV-131 — El dólar de una tenencia en pesos difiere entre capas

**Estado de las citas:** ✅ verificadas (el mapa no daba línea).
Frontend: `pickFinancialRate` en `frontend/src/contexts/CurrencyContext.jsx:46-54`.
Backend: `_current_cedear_rate` en `backend/main.py:4939-4954`.

**a. Implementaciones**

*(i) Frontend — `CurrencyContext.jsx:46-54`:*
```js
const rate = c => c?.medio ?? c?.venta          // al MEDIO (compra+venta)/2
const mep = rate(dolar?.mep), ccl = rate(dolar?.ccl), blue = rate(dolar?.blue)
return (pref === 'ccl' ? (ccl || mep) : (mep || ccl)) || blue
```
Cascada: **elegido → el otro → BLUE**, todo **al medio**.

*(ii) Backend — `main.py:4939-4954`:*
```python
for casa in ("mep", "ccl", "cripto"):
    v = _val_rate(cached.get(casa))
    if v: return v
return None
```
Cascada: **mep → ccl → CRIPTO**. Si las tres están frías devuelve `None` y el caller cae a `config.tc_mep` / `tc_blue` persistidos (potencialmente stale de meses).

*(iii) Tercera variante en el snapshot* — `snapshots_job.py:715`: `tc_cedear = tc_mep if (tc_mep and tc_mep>0) else _user_tc_cedear(conn, uid, tc_blue)`, donde `_user_tc_cedear` (`:146-155`) delega en `analysis_prep.user_fx` (lee `config.tc_mep` del usuario). El cron pasa un `tc_mep` fetcheado directo (`main.py:36901-36903` documenta por qué: *"con cache frío caía al config.tc_mep PER-CLIENTE (potencialmente stale de años)"*).

**b. Fórmulas**

```
R_front(pref)  = medio(pref) ?? medio(otro) ?? medio(blue) ?? config.tc_blue ?? 1415
R_back()       = venta_o_medio(mep) ?? …(ccl) ?? …(cripto) ?? config.tc_mep ?? tc_blue
```
`_val_rate` es la que decide medio-vs-venta en el backend; la cascada difiere en el **tercer** escalón: `blue` vs `cripto`.

**c. ¿Real o cosmética?** **REAL cuando el caché de `dolarapi` está frío para MEP y CCL** (que es exactamente cuando importa). El dólar cripto cotiza típicamente **5-9 % por encima** del MEP y el blue puede estar por debajo. Con `blue.medio = 1.400` y `cripto.venta = 1.530`, una tenencia de `ARS 1.450.000`:

| capa | rate | valor |
|---|---:|---:|
| Dashboard / Cartera | 1.400 | **US$ 1.035,71** |
| Snapshot / Análisis / IA | 1.530 | **US$ 947,71** |

**8,5 % de diferencia** en la misma tenencia el mismo día — y esa diferencia entra a la curva de patrimonio como un movimiento de mercado que no existió. Es la misma clase de bug que el propio código llama "pérdida fantasma" (`ledger_replay.py:20-26`, memoria "Reportes: pérdida fantasma").

Agravante: `_current_cripto_rate` (`main.py:4957-4974`) devuelve **`venta`, no `medio`**, con un comentario que lo justifica para el premium cripto. Pero `_current_cedear_rate` reusa esa misma casa como tercer fallback **para valuar tenencias en pesos**, donde la punta de venta no corresponde: el resto del sistema pasó al medio (`CurrencyContext.jsx:47-50`: *"antes usábamos `.venta` y la cartera daba ~0,7% menos que el broker"*).

**d. Dictamen.** Correcta la del frontend: `mep → ccl → blue`, **al medio**. El cripto **no puede** ser fallback del dólar financiero: es otro mercado con otro premium, y usarlo mete un sesgo sistemático de +5-9 % en la valuación de todo lo que esté en pesos. Y cuando no hay ningún dato del día, la respuesta correcta es **no valuar** (o marcar el dato como no medido), no caer a un `config.tc_mep` que puede tener meses.

**e. Qué ve mal el usuario y dónde.** Cualquier día en que MEP y CCL fallen: **curva del Dashboard** y **Reportes** (snapshot escrito al cripto o a un config stale) contra el **hero del Dashboard** y la **Cartera** (blue del día). También **Comportamiento** y **Rendi AI**, que van por `analysis_prep.user_fx` → `config.tc_mep`.

**f. Causa raíz.** **Fix aplicado en un solo lado.** El paso a "al medio" y la cascada `mep→ccl→blue` se hicieron en `CurrencyContext` con un comentario explicando el porqué; el backend quedó con la cascada vieja que incluía cripto.

**g. Fuente única de verdad propuesta.** **Un solo endpoint** que devuelva el rate resuelto del día (`GET /api/fx/valuation` → `{rate, casa, basis:'medio', fecha}`) y que **el frontend lo consuma en vez de recalcular**. La cascada vive en un solo lugar del backend; el snapshot, `behavioral`, los builders de IA y el frontend leen el mismo número, y queda estampado en `snapshots.fx_basis` (el campo ya existe conceptualmente en `ledger_replay.FX_BASIS`).

---

### DIV-132 — Cuatro políticas incompatibles para "no puedo valuar esto"

**Estado de las citas:** ✅ verificadas.
`dashboard_top_holdings.py:56` ✅ (`if invested <= 0 or qty <= 0:`) y `:90` ✅ (idéntico en `build`).
`ai/builders/dashboard.py:67` ✅ (`if invested <= 0 or qty <= 0:` dentro de `_position_pnl_pct`).
`main.py:36916-36923` ✅ (`has_price = ...` en `:36916-36918`, `if not has_price: … continue` en `:36919-36923`).
`snapshots_job.py:729-742` ✅ (`MIN_COVERAGE = 0.95` en **`:733`**, el `return {'ok': False, …}` en `:739-743`).

**a. Implementaciones**

| # | Ubicación | Política |
|---|---|---|
| 1 | `dashboard_top_holdings.py:56` y `:90`, `dashboard.py:67` | **excluye** todo lote con `invested ≤ 0 ∨ qty ≤ 0` |
| 2 | `main.py:36916-36923` | **excluye** lo que no tiene precio; lo cuenta en `stats['no_price']` y lo publica en `star.skipped_no_price` |
| 3 | `snapshots_job.py:718-743` | si la **cobertura ponderada por costo** < 95 %, **no escribe el snapshot del día** |
| 4 | `valuation.js` (todas las ramas) | **nunca excluye**: cae a costo, `P&L = 0` |

**b. Fórmulas**

```
#1: AUM_ia   = Σ{ V(p) : invested(p) > 0 ∧ qty(p) > 0 ∧ ¬is_cash }
#2: AUM_ases = Σ{ V(p) : ∃ precio(p) }                          (+ conteo de excluidos)
#3: escribir ⟺  Σ{C(p) : ∃precio} / Σ{C(p)} ≥ 0,95
#4: V_front  = Σ_p ( ∃precio ? mkt : C(p) )                      (sin exclusión)
```

**c. ¿Real o cosmética?** **REAL, en el denominador de todos los porcentajes.**

*(i) `invested ≤ 0` excluye tenencia legítima.* Una acción recibida por transferencia de títulos (el validator las filtra y no crean costo — `ledger_replay.py:11-14`), un bono totalmente amortizado, o una posición cuyo costo aún no se recomputó, tienen `invested = 0` y **desaparecen del AUM de Rendi AI**.

*(ii) El cash no entra al denominador de la IA.* `dashboard_top_holdings.build:86-88` hace `continue` en `is_cash` y `grand` se acumula sólo sobre no-cash (`:97`), pero `weight_pct = value_usd / grand` (`:130`) se presenta como **peso en la cartera**. Usuario con 40 % en efectivo: la IA le dice que su mayor posición pesa **25 %** cuando la torta del Dashboard le muestra **15 %**. Factor 1/(1−0,40) = **1,67×** sobre *todos* los pesos.

*(iii) El snapshot que no se escribe.* Con cobertura < 95 % el cron devuelve `{'ok': False, 'reason': 'low_price_coverage'}` y no hay fila ese día. La curva salta al día siguiente sin señal, y `computeDailyPnl` compara contra un cierre de hace 2-3 días rotulado "Hoy" (`Dashboard.jsx:982`: `dailyVar.dayDiff === 1 ? 'Hoy' : ...` — el frontend sí lo rotula bien, es el único que se salva).

*(iv) El frontend nunca excluye* → sus totales incluyen tenencia sin precio a costo con `P&L = 0`, mientras el libro del asesor la saca. **El AUM que ve el asesor es menor que el patrimonio que ve el cliente**, por el monto exacto de lo que no cotiza.

**d. Dictamen.** **Ninguna es correcta por sí sola.** La política correcta tiene tres reglas:
1. **Nunca excluir por `invested ≤ 0`**: la tenencia existe aunque no sepamos su costo. Si `invested = 0`, el peso se calcula igual y el `pnl_pct` se devuelve `null`, no se borra la posición.
2. **El denominador de un porcentaje incluye todo el patrimonio**, cash incluido (o el porcentaje se rotula "% de la cartera invertida").
3. **Excluir por falta de precio es aceptable, pero debe reportarse siempre** — la única implementación que lo hace es la del libro del asesor (`star.skipped_no_price`). Ése es el patrón a copiar.

**e. Qué ve mal el usuario y dónde.**
- **Rendi AI** (`/ai`, chat, packet `dashboard.top_holdings`): pesos inflados por 1/(1−%cash) y tenencias sin costo desaparecidas.
- **Libro del asesor** (`GET /api/advisor/book`): AUM menor que la suma de los Dashboards de sus clientes.
- **Curva del Dashboard / `/reportes`**: días faltantes en la serie, sin explicación en pantalla.

**f. Causa raíz.** **Cada capa eligió su política de faltantes** en el momento en que le dolió: el frontend eligió "no romper la pantalla", el snapshot "mejor nada que un dato corrupto", el asesor "no inventar P&L 0", y los builders de IA copiaron un `if` defensivo de otro builder.

**g. Fuente única de verdad propuesta.** Un tipo de retorno único para la valuación: `{value, invested, priced: bool, reason: str|null}` (que `valuePositionLot` **ya devuelve** vía `priceTrusted`, sólo que nadie lo propaga al backend). Cada consumidor decide qué hacer, pero **sobre el mismo dato**, y el conteo de no-valuadas viaja en todos los payloads.

---

### DIV-133 — Los plazos fijos son tenencia en el frontend y no existen en el backend

**Estado de las citas:** ⚠️ **una afirmación del mapa es incorrecta.**
`Dashboard.jsx:209` ✅ (`const pf = pfUsd(usePfRollup(), tcValuacion)`).
`Dashboard.jsx:418-421` ✅ (`classBreakdown` / `sectorBreakdown` con la porción sintética `plazo_fijo` / `renta_fija`).
`grep -n "plazos_fijos\|futures_positions" backend/snapshots_job.py` → **0 resultados** ✅ el mapa acierta.
❌ **"La variación diaria se calcula contra ese snapshot"** — **falso**. `Dashboard.jsx:235-237` define `totalValuePositions = totalValue - pf.valueUsd` y `totalCostBasisPositions = totalCostBasis - pf.investedUsd`, y **todo** lo que toca la serie temporal usa esas variables: el POST del snapshot (`:478`), la serie del gráfico (`:596`), `dailyVar` (`:642`) y `monthlyVar` (`:646-651`). El comentario en `:476-477` lo dice explícito: *"Snapshots positions-only (sin PF) → la historia/gráfico/daily se mantienen consistentes; el PF solo entra en las métricas estáticas del titular."* Lo mismo en `HomeMobile.jsx:131` (`compareValue = totalsMep.totalValue`, sin PF) vs `:329-332` (el hero, con PF).

**a. Implementaciones**

*(i) Frontend con PF:* `Dashboard.jsx:212-213` (`totalValue = Σ brokerTotals + pf.valueUsd`), `:418-421` (tortas), `HomeMobile.jsx:329-332` (hero), `Insights.jsx:2147`.
*(ii) Frontend sin PF:* `Dashboard.jsx:235-237` y todo el eje temporal; **`Positions.jsx` no importa `pfUsd` en absoluto** (verificado: `grep -rn "pfUsd" frontend/src` devuelve sólo Insights, Dashboard, HomeMobile y el propio hook).
*(iii) Backend:* `snapshots_job` no lee `plazos_fijos` ni `futures_positions`; tampoco lo hacen `behavioral.py`, los builders de IA, `reporting/timeline.py` ni `advisor_book`.

**b. Fórmulas**

```
Hero Dashboard / Home = Σ_b computeBrokerValue(b).value + pfUsd(rollup).valueUsd
Total Cartera         = Σ_b computeBrokerValue(b).value                        (sin PF)
snapshots.total_value = Σ_b compute_broker_value_usd(b).value                  (sin PF)
AUM del asesor        = Σ_clientes Σ_p compute_broker_value_usd([p]).value     (sin PF)
```

**c. ¿Real o cosmética?** **REAL, por el monto exacto del plazo fijo.** Usuario con US$ 10.000 en activos y un PF de `ARS 14.500.000` (US$ 10.000 al MEP):

| pantalla | patrimonio |
|---|---:|
| Hero del Dashboard / Home | **US$ 20.000** |
| Total de `/posiciones` (Cartera) | **US$ 10.000** |
| Último punto del gráfico del Dashboard | **US$ 10.000** |
| Capital de `/reportes` | **US$ 10.000** |
| AUM del cliente en el libro del asesor | **US$ 10.000** |

El usuario ve **el doble arriba que abajo, en la misma pantalla**. Lo que **no** pasa (contra lo que dice el mapa) es un salto en la variación diaria: eso está explícitamente evitado.

**d. Dictamen.** **Ninguna es correcta.** La actual es una decisión de contención razonable (positions-only en todo el eje temporal, para que la serie sea homogénea), pero deja un patrimonio partido: el número grande del hero no reconcilia con ninguna otra vista del sistema, y el asesor no ve el PF de su cliente. El PF **es** patrimonio y debe entrar al snapshot; el motivo por el que no entra es que vive en otra tabla y `snapshot_user` sólo sabe leer `positions`.

**e. Qué ve mal el usuario y dónde.**
- **`/` (Dashboard, hero "Patrimonio")** y **`/` mobile (Home)**: número que no coincide con `/posiciones`, con el gráfico de abajo ni con `/reportes`.
- **Libro del asesor** (`/asesor`): un cliente con la mitad de su plata en plazos fijos aparece con la mitad de su AUM real → cae en el grupo de patrimonio equivocado (`advisor_groups.py`).
- **Rendi AI**: "tu patrimonio es US$ 10.000" cuando la pantalla dice US$ 20.000.

**f. Causa raíz.** **Migración a medio hacer.** Los PF se agregaron como tabla propia y se enchufaron al frontend (hero + tortas) sin pasar por el motor de valuación ni por el snapshot. La exclusión del eje temporal es el **PARCHE** que evita el daño peor (el salto en la curva) sin arreglar la causa.

**g. Fuente única de verdad propuesta.** Que `snapshot_user` sume el rollup de `plazos_fijos` (y `futures_positions`) con la misma valuación determinística de `usePfRollup.js:34` portada a Python, y que el snapshot lleve un desglose `{positions, plazos_fijos, futuros}` para que la curva pueda mostrarse con o sin PF sin recalcular. Con eso desaparece `totalValuePositions` y hay un solo "patrimonio".

---

## Hallazgos nuevos (no estaban en el mapa)

### X-1 🔴 — `reporting/timeline.py` pisa la moneda del LOTE con la del BROKER

`backend/reporting/timeline.py:123-131`:
```sql
SELECT p.asset, p.asset_type, p.broker, p.quantity, p.invested,
       p.is_cash, p.price_override, br.currency          -- ← alias 'currency'
  FROM positions p JOIN brokers br ON br.name=p.broker AND br.user_id=p.user_id
```
El `dict(r)` resultante tiene `currency` = **moneda del broker**, y se lo pasa a `_position_value_usd` (`:144`), cuyo `_native_ccy` (`behavioral.py:195-207`) lee **esa** clave primero. `positions.currency` ni siquiera se selecciona: se perdió.

**Efecto medido sobre el código:** un bono/ON con `currency='USD'` dentro de Balanz (`brokers.currency='ARS'`) →
- `cost_ccy = 'ARS'` → `cost_usd = invested / MEP` (colapsa 1.450×)
- `price_is_ars = True` → `mkt_usd = P_BA·q / MEP` (correcto)
- guard: `mult = mkt_usd / (invested/MEP) ≈ 1.450 > 50` → **rechaza el precio**
- retorna `invested / MEP`

Un bono de US$ 10.000 aparece como **US$ 6,90** en la concentración y los detectores de Reportes. Es el bug "la tenencia dólar colapsaba (~1/MEP)" que `usdLotValue`/`costInUsd` arreglaron en el frontend y en `compute_broker_value_usd`, **todavía vivo acá**.

Consumidores verificados: `timeline.py:187` (`build_timeline`) y `main.py:33198` (`_fetch_positions_for_concentration(conn, uid, broker, {}, tc_blue)` → detectores del reporte de período).

### X-2 🟠 — `AssetDetail.valueLot` publica `costo/tc_compra` como valor de mercado

En modo "Costo en dólares → de la compra", cuando **no hay precio**, `AssetDetail.jsx:56/78` hace `const mkt = priceLocal != null ? … : investedUsd` con `investedUsd = invested / costBasisRate(p, ·, costBasis)` — o sea el costo dividido por el `tc_compra`. Ese es exactamente el bug que `valuation.js:414-419` documenta haber arreglado (*"Antes caían a `investedUsd`, que en modo 'purchase' está dividido por tc_compra: publicaba costo/tc_compra como valor de mercado"*) y que `valuePositionLot` (`:585-590`), `valueEquityLot` (`:417-420`), `pesoLotUsd` (`:300-305`) y `PositionDetailMobile.jsx:122-125` ya corrigieron cayendo a `guardCost` (costo a HOY). **`AssetDetail` es el único de los cinco que quedó sin el fix.** Superficie: `/activo/:ticker` (ficha del activo), fila y total, sólo en modo "purchase".

### X-3 🟠 — `compute_broker_value_usd` decide `ar_usd` por nombre; `position_price_key` lo decide por padre

`snapshots_job.py:184`: `ar_usd = _is_ar_usd_subbroker(broker_name)` — regex `/·\s*usd$/` sobre el nombre.
`snapshots_job.py:74-87` (`_broker_name_sets`, que alimenta el fetch de símbolos): **parent-aware** vía `parent_broker_id`, con el sufijo sólo como fallback.

Las dos decisiones tienen que coincidir o el símbolo que se pide no es el que se lee. Sub-broker de padre ARS **renombrado** sin `· USD` (ej. "Balanz dólares"), con un activo `asset_type=NULL` (una acción AR como YPFD):
- `build_price_symbols` pide `YPFD.BA` ✅
- `compute_broker_value_usd`: `ar_usd=False`, `asset_type≠CEDEAR` → lee `prices.get('YPFD')` → **`None`** → `value = real_cost`

La posición cae a costo con `P&L = 0` **en silencio**, y el guard de cobertura la cuenta como "con precio" (usa `position_price_key`, la versión parent-aware) → la cobertura da 100 % y el snapshot se escribe subvaluado. Es literalmente la causa raíz que el docstring de `valuationPriceKey` (`valuation.js:464-467`) describe: *"si el fetch pide una key distinta de la que la valuación lee, la posición cae a costo EN SILENCIO"*.

### X-4 🟡 — `HomeMobile` no tiene rama para broker ARS

El loop de "mejor activo" (`HomeMobile.jsx:210-260`) tiene 3 ramas: `isAR && costInUsd`, `CEDEAR/arUsd`, y `else`. **No hay rama `isAR` nativa.** Un lote en un broker ARS con `currency` NULL (legacy — `GET /api/positions` en `main.py:8186-8195` devuelve las filas **crudas, sin estampar** `currency` desde `brokers`) y `asset_type` NULL cae al `else`: `px = prices[ticker US]` e `invested = realCost` (pesos como dólares). Es el bug C1 que las otras siete pantallas ya no tienen.

### X-5 🟡 — `valueEquityLot` no excluye la cripto de la rama `.BA`

`valuation.js:395`: `(p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker)) && !isFciSym(p.asset) && p.price_override == null` — **falta `&& !isCrypto(p.asset)`**, que `valuePositionLot:687` sí tiene (con el comentario *"La cripto NUNCA entra acá (no es .BA) → va a la rama spot"*). Una cripto en un sub-broker `· USD` pide `BTC.BA` (inexistente) → `valueUsd = null` → cae a costo. Impacto acotado: los dos consumidores (`CarteraList.jsx:116`, `DetailPortfolioBlocks.jsx:144`) filtran por `isEquityLike`, así que hoy no llega cripto. Es una mina, no una herida.

### X-6 🟡 — `briefing._user_holdings` suma cantidades de instrumentos distintos

Ver DIV-128(c): `SUM(quantity) GROUP BY asset` cross-broker suma CEDEARs (con ratio) y acciones US como la misma unidad, y `SUM(invested)` mezcla pesos con dólares. Hoy sólo se usa para el `change_pct` de las tarjetas del Home, así que el número malo no se muestra — pero el helper está publicado.

---

## Parches detectados

| ubicación | qué síntoma tapa | causa real | dónde más sigue rompiendo |
|---|---|---|---|
| `Positions.jsx:1272` — comentario *"No hay guard en esta rama → sin flip"* | que la fila "salte" a costo cuando el precio es absurdo | no hay una capa que decida el clamp una sola vez y lo comunique a la UI | el pie del mismo broker sí clampea → Σfilas ≠ total; mobile clampea y desktop no |
| `Dashboard.jsx:235-237` + `:476-477` — `totalValuePositions = totalValue − pf.valueUsd` | el salto en la curva/variación diaria al sumar plazos fijos | el PF no está en el motor de valuación ni en el snapshot | hero ≠ Cartera ≠ curva ≠ Reportes ≠ AUM del asesor (DIV-133) |
| `snapshots_job.py:718-743` — no escribir el snapshot si la cobertura < 95 % | snapshots subvaluados que fabrican una pérdida al día siguiente | la valuación no distingue "cayó a costo" de "vale su costo" | días faltantes en la serie sin señal en pantalla; y no protege contra DIV-124/X-3, donde el costo mal denominado hace que la cobertura dé 100 % |
| `behavioral.py:225-246` — `stamp_positions_currency` | que `_native_ccy` adivine la moneda por el nombre del broker | `positions.currency` es NULL en filas legacy y `GET /api/positions` no la estampa | todo path que **no** llame `currency_context`: `reporting/timeline.py` (X-1) y `main.py:33198`; el propio comentario de `:230-236` admite que `_AR_BROKER_HINTS` está incompleta |
| `behavioral.py:172-193` — `_byma` estampado con fallback a `_AR_BROKER_HINTS` | CEDEARs valuados por el ticker US en brokers sin hint | la resolución `.BA` vive en 3 lugares (DIV-125) | Comportamiento y Rendi AI cuando `stamp_byma` no corrió |
| `main.py:36901-36903` — `tc_cedear = tc_mep` (rate del job, no per-cliente) | `config.tc_mep` stale por cliente en el libro del asesor | `_current_cedear_rate` devuelve `None` con caché frío y nadie definió el fallback (DIV-131) | `analysis_prep.user_fx` sigue leyendo el config per-usuario en Comportamiento, IA y `reporting/timeline` |
| `snapshots_job.py:105-118` — early-returns de FCI y cripto en `position_price_key` | `FCI:x.BA` y `BTC.BA` (símbolos inexistentes) | el ruteo `.BA` se decidía por broker en vez de por instrumento | el mismo par de excepciones está copiado en `valuationPriceKey`, `_price_is_ars` y en las 9 copias del frontend: **cuatro listas de excepciones que hay que mantener sincronizadas a mano** |
| `main.py:32838-32848` — comentario *"⚠️ ÚNICO LECTOR QUE SE DEJA CON EL BROKER SOLO, Y ES A PROPÓSITO… Mitigante: nadie lo consume"* (`cash_value`) | un KPI que suma pesos y dólares crudos | mismo defecto de moneda-por-lote de DIV-129 | el propio comentario dice que "hoy, en IOL, ya devuelve pesos crudos rotulados como dólares" — deuda declarada y viva |

---

## Citas del mapa incorrectas

| DIV | cita del mapa | ubicación real | qué decía mal |
|---|---|---|---|
| DIV-122 | `frontend/src/pages/PositionDetailMobile.js` | `frontend/src/pages/PositionDetailMobile.jsx:101` | extensión equivocada (`.js` en vez de `.jsx`); el archivo `.js` no existe |
| DIV-123 | `valuation.js:578-579` (guard `trustMktValue`) | `valuation.js:583-584` | `:578` es el `if` de entrada a la rama; el guard está 5 líneas más abajo |
| DIV-124 | `snapshots_job.py:284-306` (brazo `else`) | `snapshots_job.py:283-306` | el `else:` está en `:283`; `:284` es su comentario |
| DIV-125 | `behavioral.py:229-234` (`_AR_BROKER_HINTS` incompleta) | `behavioral.py:230-236`, con la constante en `:112` | bloque corrido 1-2 líneas |
| DIV-128 | `main.py:22881` (clave `(broker, asset)`) | `main.py:22891` | `:22881` es el `continue` del descarte de huérfanos, no la clave; 10 líneas de diferencia |
| DIV-128 | `briefing.py:44` | `backend/home/briefing.py:44-48` (función en `:39`) | ruta incompleta — hay un solo `briefing.py` y está bajo `backend/home/` |
| DIV-129 | `advisor_groups.py:203-205` | `advisor_groups.py:202` (SELECT) y `:219-221` (uso) | corrida; el default `'ARS'` está en el `COALESCE` de `:202` |
| DIV-129 | `main.py:22874-22880` | `main.py:22875-22881` | corrida 1 línea |
| DIV-132 | `snapshots_job.py:729-742` | `snapshots_job.py:718-743` (`MIN_COVERAGE` en `:733`) | el bloque de cobertura arranca en `:718`, no en `:729` |
| DIV-133 | *"La variación diaria se calcula contra ese snapshot"* | `Dashboard.jsx:235-237, 476-478, 596, 642, 646` · `HomeMobile.jsx:131` | **afirmación incorrecta**: el frontend excluye el PF (`totalValuePositions`) de todo el eje temporal, a propósito y con comentario. La divergencia real es hero vs Cartera/curva/Reportes/AUM, no un salto en la variación diaria |
| DIV-121 | *"Las 7 pantallas siguen con su copia"* | son **9** copias en el frontend (+2 motores backend) | faltan `HomeMobile.jsx:210-260`, `FirstInsight.jsx:112-160`, el segundo chain de `Dashboard.jsx:512-580` y `valueEquityLot` (`valuation.js:360`) |

---

## URGENTE

**Sí, hay algo que amerita atención inmediata: DIV-124 + DIV-125 + X-3, que son la misma herida.**

El motor que escribe la tabla `snapshots` (`snapshots_job.compute_broker_value_usd`) valúa mal cualquier lote con `positions.currency='ARS'` alojado en un broker de moneda USD, y el error es del orden del tipo de cambio (**×1.450** en el caso `· USD`, o un **P&L negativo fabricado de −US$ 695.500** sobre un lote de US$ 500 en el caso de broker USD genuino). No es un redondeo: es el número que alimenta

- la curva de patrimonio del Dashboard,
- el capital y el rendimiento de `/reportes`,
- el AUM, la distribución y el motor estrella del **libro del asesor** (dato que el asesor le muestra a su cliente),
- la variación diaria / "P&L Día" del día siguiente.

Tres agravantes:
1. **El guard anti-distorsión no protege**: en el caso `· USD` rechaza el precio *bueno* (compara USD contra pesos) y devuelve el costo en pesos como si fueran dólares; en el caso de broker USD genuino el múltiplo cae dentro de la banda y **confía en el precio equivocado**.
2. **El guard de cobertura del 95 % tampoco protege**: `_cost_usd` (`snapshots_job.py:718-721`) decide la moneda por `brokers.currency`, así que pondera el lote roto con su costo inflado y la cobertura da 100 %.
3. **Es silencioso**: no hay log, no hay conteo, no hay banner. Un snapshot corrupto queda escrito y la curva del usuario nunca se recupera sola.

No lo arreglé (regla de auditoría). Lo que hay que verificar antes que nada, en la copia de producción, es **cuántas filas de `positions` tienen `currency='ARS'` con un broker cuya `currency` no es `'ARS'`** — esa consulta dice si esto es un caso de borde o si hay snapshots corruptos en circulación:

```sql
SELECT p.user_id, count(*) AS lotes, sum(p.invested) AS invested_ars
  FROM positions p JOIN brokers b ON b.user_id=p.user_id AND b.name=p.broker
 WHERE upper(coalesce(p.currency,'')) = 'ARS'
   AND upper(coalesce(b.currency,'')) <> 'ARS'
   AND coalesce(p.is_cash,0)=0 AND coalesce(p.quantity,0)>0
 GROUP BY p.user_id ORDER BY invested_ars DESC;
```

Segundo urgente, menor pero del mismo orden: **X-1** (`reporting/timeline.py` pierde `positions.currency`) colapsa toda tenencia en dólares dentro de un broker ARS a **1/MEP** en la concentración y los detectores de Reportes. Afecta a cualquier usuario de Balanz/IEB/PPI con bonos u ONs en dólares, que es el caso típico de este mercado.

---

## BLOQUE-RESUMEN

| concepto | DIV | versiones | difieren | correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---|---:|---|---|---|---|---|
| Tenencia / posición / holding | DIV-121 | 9 (+2 backend) | sí — habilita a todas las demás | `valuation.js:543` `valuePositionLot` | ninguna por sí sola; es el vector | ⚪ | migración a medio hacer (SSoT escrita, lectores sin migrar) |
| Tenencia / posición / holding | DIV-122 | 10 | sí — el costo difiere en `commissions` (0,55 pp sobre 10.000/50) | la versión con comisiones (`valuePositionLot`) | Comportamiento, Rendi AI, Reportes, Objetivos, brief del asesor, detalle de posición mobile | 🟡 | fix aplicado en un solo lado (frontend; `behavioral.py` nunca lo recibió) |
| Tenencia / posición / holding | DIV-123 | 4 | sí — hasta ×75 entre fila y pie | la versión con `trustMktValue` | Cartera desktop `/posiciones`: la suma de las filas no da el total | 🟠 | omisión deliberada + copiar y pegar |
| Tenencia / posición / holding | DIV-124 | 2 | sí — ×MEP (US$ 707.000 vs US$ 517) | `valuePositionLot` (6 ramas) | curva del Dashboard, `/reportes`, libro del asesor, variación diaria | 🔴 | port Python incompleto (5 de 6 ramas) |
| Tenencia / posición / holding | DIV-125 | 3 | sí — cotiza otro instrumento (ADR vs `.BA`), P&L fantasma de −US$ 695.500 | `valuationPriceKey` (parent-aware + `positions.currency`) | snapshot/curva/Reportes/libro; Comportamiento y Rendi AI sin `_byma` | 🔴 | falta de capa compartida + port incompleto |
| Tenencia / posición / holding | DIV-126 | 2 | sí — costo vs valor, y por lote (3 lotes de AAPL copan el top 3) | ninguna: valor de mercado agregado por activo | `/reportes` "Top holdings" vs respuesta de Rendi AI | 🟡 | copiar y pegar + falta de SSoT |
| Tenencia / posición / holding | DIV-127 | 2 | sí — 60 lotes vs 5 activos | la de la Cartera (`asset`,`moneda`) | `/reportes` KPI "# posiciones" | 🟡 | falta de SSoT (`COUNT(*)` suelto) |
| Tenencia / posición / holding | DIV-128 | 4 | sí — `H₃` suma CEDEARs y acciones US como la misma unidad | `(broker, asset, currency)` para tenencia; `cedearEspecieBase` valuado para exposición | Home (tarjetas de briefing), chat de Rendi AI, Cartera vs Calidad de cartera | 🟡 | copiar y pegar; no existe un tipo "Holding" |
| Tenencia / posición / holding | DIV-129 | 8 (el mapa decía 7) | sí — rango ×1.450 entre pantallas | descartar y reportar (chat IA / libro del asesor) | `/reportes` top holdings (×MEP), grupos del asesor (÷MEP), Dashboard/Cartera/curva (ausente) | 🟠 | falta de SSoT + brokers linkeados por NOMBRE sin FK |
| Tenencia / posición / holding | DIV-130 | 2 | sí, y está documentado y medido | ambas (miden cosas distintas) | ninguna hoy: el replay no llega a pantalla | ⚪ | por diseño, con `verificar_contra_hoy` como testigo |
| Tenencia / posición / holding | DIV-131 | 2 (3 con el snapshot) | sí — 8,5 % con caché frío (blue 1.400 vs cripto 1.530) | la del frontend: mep→ccl→blue, al medio | curva/snapshot/Reportes vs hero y Cartera, los días que MEP y CCL fallan | 🟠 | fix aplicado en un solo lado (el paso "al medio" no cruzó al backend) |
| Tenencia / posición / holding | DIV-132 | 4 | sí — pesos de la IA inflados 1/(1−%cash) = 1,67× con 40 % en efectivo | ninguna: excluir sólo por falta de precio, y siempre reportarlo | Rendi AI (`weight_pct`), libro del asesor (AUM menor al del cliente), curva con días faltantes | 🟡 | cada capa eligió su política de faltantes |
| Tenencia / posición / holding | DIV-133 | 2 | sí — por el monto del PF (hero US$ 20.000 vs Cartera US$ 10.000) | ninguna: el PF debe entrar al snapshot | hero Dashboard/Home ≠ `/posiciones` ≠ gráfico ≠ `/reportes` ≠ AUM del asesor | 🟡 | migración a medio hacer (PF en tabla aparte, nunca portado al motor) |
