# 1A — Veredicto: Valuación de cartera / valor de mercado

**Grupo:** Valuación de cartera / valor de mercado · 15 divergencias (DIV-145–DIV-159)
**Commit auditado:** `b74f450f` (`/tmp/rendi-main`, `backend/main.py` = 38.029 líneas ✅)
**Citas verificadas:** 22 de 22 abiertas y leídas · **13 corregidas** (ninguna cita del mapa era literalmente exacta en línea; ninguna era falsa en sustancia salvo DIV-146, ver abajo)
**Deriva `82fad6a0`:** ningún hallazgo de este grupo cae en `backend/pricing/fci.py`, `frontend/src/components/AddPositionFlow.jsx` ni `backend/tests/test_fci_uala.py`. Nada que descontar.

---

## Resumen ejecutivo

El motor canónico (`frontend/src/utils/valuation.js` → `valuePositionLot`) es correcto y está bien documentado. El problema es que **hay ocho reimplementaciones del mismo cálculo** y el port al backend (`snapshots_job.compute_broker_value_usd`) quedó a mitad de camino: le falta la rama "lote en pesos alojado en cuenta USD". Esa omisión no es cosmética — en un CEDEAR comprado en pesos dentro de un sub-broker `· USD`, el cron cuenta los pesos 1:1 como dólares, el guard anti-distorsión compara USD contra pesos, lo rechaza, y **persiste el costo en pesos como si fueran dólares: factor ≈1.360×**. Eso queda escrito en `snapshots.total_value`, que es la serie histórica, el denominador de la variación diaria, la base de Reportes/TWR, el AUM del libro del asesor y el contexto de la IA. El Dashboard, que calcula en el browser con el motor bueno, muestra el número correcto — así que el usuario ve el hero bien y **el gráfico, la variación del día y los reportes mal**.

El segundo agujero del mismo archivo (DIV-146) es peor por silencioso: `build_price_symbols` es parent-aware pero `compute_broker_value_usd` decide `· USD` con un regex sobre el nombre. Un sub-broker renombrado pide `PAMP.BA` y después lo busca por `prices['PAMP']` → no lo encuentra → cae a costo. El guard de cobertura del 95% usa la función parent-aware, así que **dice 100 % de cobertura y escribe el snapshot congelado al costo**.

Del lado frontend los tres que el usuario ve a diario: la ficha del activo (`/activo/:ticker`) publica *costo ÷ tc_compra* como "Valor actual" cuando no hay precio, en el modo por defecto (`purchase`) — hasta +45 % contra la Cartera (DIV-152); la fila de Cartera desktop no aplica el clamp en la rama pesos-en-cuenta-USD mientras el total del pie sí (DIV-151, la fila ×100 y el total clampeado); y los plazos fijos entran en el hero de Dashboard, Cartera desktop y Home mobile pero **no** en Análisis, **no** en Cartera mobile y **en ningún cálculo del backend** (DIV-149).

Lo cosmético de verdad son dos: el orden de ramas (DIV-153) y `tcValuacion` vs `cedearRate` (DIV-154) hoy dan delta 0 — pero DIV-154 es exactamente el bug que ya produjo "10 filas que sumaban US$ 64.147,88 sobre un TOTAL de US$ 56.582,51", corregido en Cartera desktop y **todavía vivo en seis reimplementaciones**.

---

## Tabla de veredictos

| DIV | versiones | ¿difieren de verdad? | cuál es la correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---:|---|---|---|---|---|
| DIV-145 | 2 | **SÍ — ×1.360** | `valuePositionLot` rama 2 | serie/gráfico Dashboard, Var. día, Reportes, libro asesor, chat IA | 🔴 | port incompleto al backend |
| DIV-146 | 2 | **SÍ — cae a costo (−72 % medido)** | `_broker_name_sets` (parent-aware) | ídem DIV-145 | 🔴 | fix aplicado en un solo lugar del mismo archivo |
| DIV-147 | 4 | **SÍ — ×100 en renta fija con override** | `valuation.js:448` | Comportamiento, todo el contexto IA, Reportes timeline | 🟠 | re-port perdiendo un parámetro |
| DIV-148 | 8 | **SÍ — 0,5–1 % sistemático** | `invested + commissions` | Comportamiento, IA, ficha activo mobile | 🟡 | falta de capa compartida |
| DIV-149 | 3 | **SÍ — el PF entero** | ninguna: falta un valuador de patrimonio | Análisis, Cartera mobile, todo el backend | 🟠 | activos fuera de `positions` sin dueño |
| DIV-150 | 1 | **SÍ — el no realizado de futuros no existe en el patrimonio** | ninguna | todas | 🟡 | ídem DIV-149 |
| DIV-151 | 2 | **SÍ — fila ×100 vs total clampeado** | el total (`computeBrokerValue`) | Cartera desktop | 🟠 | guard omitido en una rama |
| DIV-152 | 2 | **SÍ — +45 % con devaluación acumulada** | `valuePositionLot` (cae a `guardCost`) | `/activo/:ticker` (AssetDetail) | 🟠 | fix aplicado en un solo lugar |
| DIV-153 | 3 | **NO** (delta 0 hoy) | `valuePositionLot` | — | ⚪ | copiar y pegar |
| DIV-154 | 7 | **NO** (delta 0 hoy, latente) | `cedearRate` en TODO el path | — (riesgo: el bug 56.582 vs 64.147) | ⚪ | copiar y pegar |
| DIV-155 | 2 | **SÍ — −0,69 % diario** | el MEP MEDIO (`_current_cedear_rate`) | libro / informes / IA del asesor | 🟡 | fix aplicado en un solo lugar |
| DIV-156 | 2 | **SÍ** (los dos motores de DIV-145/146) | el del browser | serie histórica completa | 🟠 | dos escritores, un motor no portado |
| DIV-157 | 1 | **SÍ — ×1.450** | ninguna | ninguna (clave muerta) | ⚪ | parche documentado y dejado |
| DIV-158 | 1 | **SÍ — puede nombrar otro activo** | ordenar por valor de mercado | KPI "Top holding" de Reportes | 🟡 | parche parcial (moneda sí, valuación no) |
| DIV-159 | 1 | **SÍ** | `valuePositionLot` | modo demo (`/login` → "Ver demo") | ⚪ | fixture escrito a mano |

---

## Detalle por divergencia

### Bloque A — DIV-145 · DIV-146 · DIV-156 (MISMA RAÍZ)

Las tres son la misma cosa vista desde tres ángulos: **`snapshots.total_value` tiene dos escritores con dos motores distintos, y el del backend es un port incompleto del frontend.** Analizo el motor una vez y después qué aporta cada DIV.

---

### DIV-145 — La rama "lote en pesos alojado en cuenta USD" no existe en el backend

**Estado de las citas:** ⚠️ **corregida.** El mapa dice `valuation.js:578-604`; la rama arranca en **`valuation.js:573`** (`if (!p.is_cash && !isAR && costInPesos(p)) {`) y termina en 604. El resto de la afirmación es exacta.

**a. Implementaciones**

**A1 — Canónico: `/tmp/rendi-main/frontend/src/utils/valuation.js:573-604`** (rama 2 de `valuePositionLot`)

```js
if (!p.is_cash && !isAR && costInPesos(p)) {
  const invUsd = realCost / costBasisRate(p, cedearRate, costBasis)
  const invUsdHoy = realCost / cedearRate
  const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true, p.asset_type)]
  const mktArs = priceArs != null ? priceArs * (p.quantity || 0) : null
  const trustArs = mktArs != null &&
    trustMktValue(mktArs, realCost, p.asset_type, p.price_override != null)
  return salida({
    investedUsd: trustArs ? invUsd : invUsdHoy,
    valueUsd:    trustArs ? mktArs / cedearRate : invUsdHoy,
    guardCost: realCost,   // ← en PESOS, igual que mktArs
    ...
  })
}
```

**A2 — Backend: `/tmp/rendi-main/backend/snapshots_job.py:283-317`** (rama `else`, moneda base USD). No hay ninguna consulta a `p['currency']` en todo el bloque:

```python
else:
    # USDT / USD — moneda base USD
    if p.get('is_cash'): ...
    else:
        cf = _cb_factor(...)
        invested += real_cost * cf                       # ← pesos contados 1:1 como USD
        if (asset_type == 'CEDEAR' or ar_usd) and override is None ... :
            price_ars = prices.get(f"{p['asset']}.BA")
            mkt_usd = (price_ars * qty) / cedear_rate
            value += mkt_usd if _trust_mkt_value(mkt_usd, real_cost, asset_type) else real_cost
```

`_trust_mkt_value(mkt_usd, real_cost, …)` compara **USD contra pesos**. Es literalmente el error que el comentario de `valuation.js:568-571` dice haber arreglado en el frontend.

Y `position_price_key` (`snapshots_job.py:105-127`) tampoco mira `currency`:
```python
wants_ba = (broker in ars_names or broker in ar_usd_names
            or (p.get('asset_type') or '').upper() == 'CEDEAR')
```
mientras `valuationPriceKey` (`valuation.js:468-475`) sí: `if (isArUsdBroker(p.broker) || costInPesos(p)) return priceSymbol(p.asset, true, …)`.

**b. Fórmulas**

Sea el lote *i* con costo nativo `cᵢ` (ARS), cantidad `qᵢ`, precio local `p^BA ᵢ` (ARS), MEP `m`.

- **A1 (correcto):**  `valorᵢ = qᵢ·p^BAᵢ / m` , `costoᵢ = cᵢ / m` , guard sobre `(qᵢ·p^BAᵢ) / cᵢ` — adimensional.
- **A2 (backend):**  `costoᵢ = cᵢ` (¡ARS rotulado USD!) , guard sobre `(qᵢ·p^BAᵢ / m) / cᵢ` — **tiene unidades de 1/m** → siempre ≈ 1/1.450 → siempre fuera de `[0,002 , 50]` → `valorᵢ = cᵢ`.

**c. ¿Real o cosmética? — REAL, factor ≈1.360×**

MELI, `asset_type='CEDEAR'`, `currency='ARS'`, 100 nominales, `invested = ARS 1.500.000`, broker `Cocos · USD`. MEP = 1.450. `MELI.BA` = ARS 16.000.

| | costo | valor | P&L |
|---|---:|---:|---:|
| A1 Dashboard/Cartera | US$ 1.034,48 | **US$ 1.103,45** | +6,7 % |
| A2 cron/snapshot | US$ 1.500.000 | **US$ 1.500.000** | 0 % |

Ratio de valor: **1.359,3×**. Y el cron **no falla ni loguea**: `_has_price` usa `position_price_key`, que para un `· USD` devuelve `MELI.BA`, que sí está en `prices` → cobertura 100 % → snapshot escrito.

Segundo caso, broker USD genuino (Schwab) con un lote `currency='ARS'` mal ruteado: `position_price_key` pide el ticker US pelado, `valuationPriceKey` pide el `.BA`. Los dos motores ni siquiera están mirando el mismo instrumento.

**d. Dictamen** — Correcta: **A1**. El backend necesita, textualmente, el espejo de la rama 2. Ya tiene el espejo de la rama 3 (`_cost_in_usd`, `snapshots_job.py:245-265`): se portó una mitad del par y no la otra.

**e. Qué ve mal el usuario y dónde**
- Gráfico de evolución y "Var. día" del **Dashboard** (`/` — `GET /api/snapshots`) y de **Home mobile**.
- **Reportes** (`/reportes` — `GET /api/reports/period/{type}/{key}` y `/api/reports/timeline`), incluido `portfolio_snapshot.latest_value`.
- **TWR** y todo lo que lee `snapshots` (`backend/twr.py`).
- **Chat IA**: `main.py:22818 _valuate_positions_for_chat` llama a `compute_broker_value_usd` posición por posición.
- **Libro del asesor**: `main.py:36924` y `main.py:37689/37825`; **brief diario**: `advisor_brief.py:152`.
- **Backfill MtM histórico**: `backend/scripts/backfill_historical_mtm.py:520`.
- **Replay del ledger**: `backend/ledger_replay.py:273`.
- **Alertas de precio**: `alerts_engine.py:75` usa `build_price_symbols` (que sí es correcto) — ahí no rompe.

**f. Causa raíz** — **Port incompleto.** El docstring de `compute_broker_value_usd` dice "port fiel, incluida la rama CEDEAR". No lo es: le falta la rama 2 de seis. Cada fix posterior del frontend (rama 3 `costInUsd`, guard de cripto, exclusión de FCI) se fue portando de a uno, y este quedó.

**g. Fuente única de verdad** — Un solo valuador por lote en el backend, espejo 1:1 de `valuePositionLot`, con **tests de paridad que le pasen el mismo lote a las dos implementaciones** (hoy los tests de `snapshots_job` sólo comparan contra sí mismo). Mientras existan dos, la única defensa real es un test de golden-vector compartido frontend↔backend.

---

### DIV-146 — `_is_ar_usd_subbroker` por regex vs `_broker_name_sets` parent-aware, en el MISMO archivo

**Estado de las citas:** ⚠️ **corregida.** El mapa cita `snapshots_job.py:158-160`; la línea 158 es la **firma** de `compute_broker_value_usd`. La decisión está en **`snapshots_job.py:185`**: `ar_usd = _is_ar_usd_subbroker(broker_name)`. La función auxiliar es `snapshots_job.py:60-67`; la parent-aware es `_broker_name_sets`, **`snapshots_job.py:70-86`**.

**a. Implementaciones**

**B1 — `snapshots_job.py:70-86` (parent-aware, usada por `build_price_symbols` y `position_price_key`):**
```python
for b in brokers:
    parent = by_id.get(b.get('parent_broker_id'))
    if parent and (parent.get('currency') or '').upper() == 'ARS':
        ar_usd_names.add(b['name'])
    elif _is_ar_usd_subbroker(b.get('name')):
        ar_usd_names.add(b['name'])
```

**B2 — `snapshots_job.py:185` (sólo nombre, usada por la valuación):**
```python
ar_usd = _is_ar_usd_subbroker(broker_name)   # re.compile(r'·\s*usd$')
```

El frontend usa la versión parent-aware para las dos cosas (`valuation.js:191-201`, `isArUsdBroker` → `_brokersById.get(b.parent_broker_id)`).

**b. Fórmulas** — No es aritmética, es **ruteo de símbolo**. B1 decide qué se *pide*; B2 decide qué se *lee*. Cuando difieren, la lectura falla y el lote cae a costo.

**c. ¿Real o cosmética? — REAL, y silenciosa**

Sub-broker renombrado a `"Cocos Dólares"` (pierde el `·`) con `parent_broker_id` → Cocos (ARS). PAMP, 1.000 nominales, costo US$ 800, `PAMP.BA` = ARS 4.200, MEP 1.450.

1. `build_price_symbols` → parent-aware → pide `PAMP.BA` → `prices = {'PAMP.BA': 4200}`.
2. `compute_broker_value_usd`: `ar_usd = False`, `asset_type != 'CEDEAR'` (PAMP es acción AR, no CEDEAR) → rama `else` → `prices.get('PAMP')` → **`None`** → `value += real_cost = 800`.
3. `_has_price` usa `position_price_key` (**parent-aware**) → `PAMP.BA` está → **cobertura 100 %** → el snapshot se escribe.

| | valor |
|---|---:|
| Dashboard (canónico) | **US$ 2.896,55** |
| snapshot del cron | **US$ 800,00** |

**−72,4 %**, todos los días, sin una sola línea en el log. El guard de integridad que existe justamente para no persistir un snapshot subvaluado está mirando la función *buena* y por eso no lo ve.

Un **CEDEAR** en el mismo broker se salva por la condición `asset_type == 'CEDEAR'`; una **acción argentina** (PAMP, YPFD, TXAR) o un **bono** no.

**d. Dictamen** — Correcta: **B1**. B2 es una regresión: el propio archivo ya tiene la resolución robusta.

**e. Qué ve mal el usuario y dónde** — Idéntica lista que DIV-145 (mismo motor, mismos consumidores). Se manifiesta como una posición congelada al costo (P&L 0 permanente) en el gráfico, en Reportes y en el libro del asesor, mientras el Dashboard la muestra viva.

**f. Causa raíz** — **Fix aplicado en un solo lugar.** El parent-aware se agregó a `_broker_name_sets` para arreglar el fetch de símbolos y no se propagó a la valuación, a 100 líneas de distancia en el mismo archivo.

**g. Fuente única de verdad** — `compute_broker_value_usd` no debería recibir `broker_name: str` sino el **dict del broker** (o el par `(ars_names, ar_usd_names)` que ya calcula el caller): la firma actual obliga a re-derivar la decisión con menos información de la disponible.

---

### DIV-156 — Dos escritores de `snapshots.total_value` con motores distintos

**Estado de las citas:** ✅ (el mapa no da cita; ubicaciones reales abajo).

**a. Implementaciones**

**C1 — Browser:** `frontend/src/pages/Dashboard.jsx:478`
```js
api.post('/snapshots', { total_value: totalValuePositions, total_invested: totalCostBasisPositions, ... })
```
con `totalValuePositions = Σ computeBrokerValue(...).value` (`Dashboard.jsx:210, 417`), motor canónico, `costBasis` = el modo del usuario.
Recibido en `backend/main.py:5004 post_snapshot` → `INSERT … source='browser', base='mercado', apto=0` (`main.py:5072-5083`).

**C2 — Cron:** `backend/snapshots_job.py:751` → `compute_broker_value_usd`, `INSERT … source='cron', base='mercado', apto=1` (`snapshots_job.py:775-791`).

**b. Precedencia (verificada)**
- El cron **pisa** al browser: `ON CONFLICT DO UPDATE SET total_value = excluded.total_value, … source='cron'` sin condición.
- El browser **no** pisa al cron: `main.py:5054-5064` lee `source` primero y, si es `'cron'`, sólo actualiza `net_deposited`/`fx`.

**c. ¿Real o cosmética? — REAL, por dos vías**
1. **El valor**: C1 y C2 difieren exactamente por DIV-145 y DIV-146. Una serie diaria puede alternar entre el número bueno (día en que el usuario abrió el Dashboard antes del cron y el cron falló) y el número corrupto.
2. **Hallazgo adicional no listado en el mapa — `total_invested` tiene dos definiciones.** `computeBrokerValue(..., costBasis)` rutea el costo por `costBasisRate` → en modo `'purchase'` (que es **el default**, `CurrencyContext.jsx:102-109`) el browser escribe el costo al `tc_compra` de cada lote; el cron escribe siempre el costo al MEP de hoy. La misma columna, en días consecutivos, mide dos cosas distintas.

**d. Dictamen** — Correcta: **C1**. Y `post_snapshot` no debería aceptar totales del cliente en absoluto: el backend ya sabe valuar (`compute_live_portfolio_value`, `snapshots_job.py:809`). Aceptar el número del browser es lo que obliga a mantener dos motores en paridad.

**e. Qué ve mal el usuario y dónde** — Saltos inexplicables en el gráfico de evolución del Dashboard y en el "P&L del período" de Reportes, sin operación que los justifique.

**f. Causa raíz** — **Migración a medio hacer.** El snapshot nació client-side; el cron se agregó después para cubrir a los usuarios que no abren la app, y en vez de reemplazar al escritor viejo se le sumó, con un motor nuevo.

**g. Fuente única de verdad** — Que `POST /api/snapshots` sea un *trigger* sin payload: valúa el backend y escribe. Elimina `SnapshotIn.total_value` / `total_invested` y el motor duplicado del cliente en el camino de escritura (el cliente sigue calculando para *mostrar*, que es su trabajo).

---

### DIV-147 — `trustMktValue` tiene CUATRO versiones, no tres

**Estado de las citas:** ⚠️ **corregida.** `behavioral.py:47` ✅. El mapa dice "retorna con el `price_override` ANTES del guard (`behavioral.py:449-457`)"; el bloque real es **`behavioral.py:452-459`** y `_position_value_usd` arranca en **`behavioral.py:391`** (el mapa dice 412 en DIV-148). **El mapa dice "tres versiones"; hay cuatro** — falta `backend/scripts/backfill_historical_mtm.py:532-543`.

**a. Implementaciones**

**D1 — Canónica, `valuation.js:448-454`:**
```js
export function trustMktValue(mktValue, realCost, assetType, hasOverride = false) {
  if (!(realCost > 0) || !(mktValue > 0)) return true
  const fixed = isFixedIncome(assetType)
  if (hasOverride && !fixed) return true       // override no-RF: se respeta
  const mult = mktValue / realCost
  return fixed ? (mult <= 4 && mult >= 0.02) : (mult <= 50 && mult >= 0.002)
}
```

**D2 — `snapshots_job.py:42-54`:** port fiel, **con** `has_override`. ✅

**D3 — `behavioral.py:47-60`:** **sin** el parámetro `has_override`. Y peor, `_position_value_usd` **nunca la llama cuando hay override** (`behavioral.py:452-459`):
```python
override = p.get("price_override") if honor_override else None
if override is not None:
    value_native = float(override) * float(qty)
    if cost_ccy == "ARS" and rate_holdings > 0:
        return value_native / rate_holdings
    return value_native            # ← sale sin pasar por _trust_mkt_value_usd
```

**D4 — `backfill_historical_mtm.py:532-543`:** guard inline, con una regla extra (`val < 0 → no confiar`), sin `has_override`, aplicado **encima** del resultado de `compute_broker_value_usd`, que ya guardeó.

**b. Fórmulas**
- D1/D2: `confiar ⟺ (override ∧ ¬RF) ∨ (mult ∈ B(tipo))`, con `B(RF)=[0,02 ; 4]`, `B(resto)=[0,002 ; 50]`.
- D3: `confiar ⟺ override ∨ mult ∈ B(tipo)` — **la excepción del override se extendió a la renta fija**.
- D4: `confiar ⟺ val ≥ 0 ∧ mult ∈ B(tipo)` — **la excepción del override desapareció**.

**c. ¿Real o cosmética? — REAL, ×100 en un caso documentado**

ON con `quantity = 1.000`, `invested = US$ 970`, `price_override = 97` (convención per-100 mal cargada; debería ser 0,97).

| | valor |
|---|---:|
| D1/D2 (Dashboard, Cartera, snapshot) | `mult = 100 > 4` → **US$ 970** |
| D3 (Comportamiento, IA, Reportes timeline) | sale antes del guard → **US$ 97.000** |

**Factor 100×** para el mismo lote, en la misma sesión. Es exactamente el caso que el comentario de `valuation.js:444-447` dice haber cazado ("una ON sin precio live con un precio manual cargado en convención per-100 (97 en vez de 0,97) → valor ×100 (+9775%)").

Y en el otro sentido: un CEDEAR con override legítimo (activo iliquido cargado a mano) que multiplicó ×60 **se respeta** en D1/D2 y **se clampea** en D3, porque D3 sí llega al guard cuando el flujo no toma la rama de override — caso `honor_override=False`, que es como los builders de IA calculan el cost basis (`dashboard.py:70`, `insights_attribution.py:100`).

**d. Dictamen** — Correcta: **D1**. D3 debe recibir `has_override` **y** el override debe pasar por el guard, no saltarlo. D4 debe borrarse (es un guard duplicado sobre un valor ya guardeado, ver Parches).

**e. Qué ve mal el usuario y dónde**
- **Comportamiento** (`/comportamiento`): `behavioral.py:987, 1086, 1095, 1176, 1559, 1715`.
- **Todo el contexto de la IA**: `ai/builders/dashboard.py`, `dashboard_brokers.py`, `dashboard_composition.py`, `dashboard_top_holdings.py`, `dashboard_events.py`, `insights_attribution.py`, `position.py`.
- **Reportes → timeline**: `reporting/timeline.py:144`.
- **Ventas / P&L**: `main.py:15263`.

**f. Causa raíz** — **Re-port perdiendo un parámetro.** El guard se escribió una vez y se copió tres. El `has_override` se agregó después al original y a uno de los ports; el tercero no lo tenía y el cuarto ni siquiera es una función.

**g. Fuente única de verdad** — Una función `trust_mkt_value(mkt, cost, asset_type, has_override)` en un módulo `backend/valuation_core.py` importada por `snapshots_job`, `behavioral`, `insights` y los scripts. Eliminar `behavioral._trust_mkt_value_usd` y el bloque inline de `backfill_historical_mtm.py`.

---

### DIV-148 — El costo sin comisiones en el backend (y en la ficha del activo mobile)

**Estado de las citas:** ⚠️ **corregida.** `behavioral.py:412` → real **`behavioral.py:391`** (def) / **`:426`** (`invested_native = float(p.get("invested") or 0)`). `insights.py:432` → real **`ai/builders/insights.py:433`**. **Hallazgo adicional:** una séptima implementación que el mapa no lista, `frontend/src/pages/PositionDetailMobile.jsx:101`.

**a. Implementaciones**

**Con comisiones (correcto), 6 sitios verificados:**
| ubicación | línea |
|---|---|
| `valuation.js` `valuePositionLot` | 556-557 (`const comm = p.commissions \|\| 0; const realCost = (p.invested \|\| 0) + comm`) |
| `valuation.js` `pesoLotUsd` / `usdLotValue` / `valueEquityLot` | 302, 339, 364 |
| `snapshots_job.compute_broker_value_usd` | 207-208 |
| `Positions.jsx` `calcUSDT` / `calcARS` | 1298, 1348 |
| `PositionsMobile.jsx` | 663 |
| `AssetDetail.jsx` `valueLot` | 46 |

**Sin comisiones (incorrecto), 3 sitios:**
| ubicación | línea | fragmento |
|---|---|---|
| `backend/behavioral.py` | **426** | `invested_native = float(p.get("invested") or 0)` |
| `backend/ai/builders/insights.py` | **433** | `invested = float(p.get("invested") or 0)` |
| `frontend/src/pages/PositionDetailMobile.jsx` | **101** | `const invested = p.invested \|\| 0` |

En `PositionDetailMobile` las ramas `costInPesos` y `costInUsd` sí suman comisiones (delegan en `pesoLotUsd`/`usdLotValue`), pero las **otras cuatro** (cash, `isAR`, `CEDEAR/·USD`, `else`) usan `invested` pelado. Es incoherente consigo misma.

**b. Fórmulas**
- Correcta: `costoᵢ = (investedᵢ + commissionsᵢ) / fxᵢ`
- Divergente: `costoᵢ = investedᵢ / fxᵢ`
- Y como el **fallback de valor** también es el costo: `valorᵢ` sin precio queda subvaluado por `commissionsᵢ`.

**c. ¿Real o cosmética? — REAL, 0,5–1 % sistemático y siempre en el mismo sentido**

AAPL, `invested = US$ 10.000`, `commissions = US$ 150`, precio hoy = US$ 10.000.

| | costo | valor | P&L |
|---|---:|---:|---:|
| canónico | 10.150 | 10.000 | **−150 (−1,48 %)** |
| behavioral / insights | 10.000 | 10.000 | **0 (0,00 %)** |

Sin precio (fallback): canónico 10.150, behavioral 10.000 → **−US$ 150 en el total**.

El sesgo es **siempre optimista**: infla el P&L y desinfla el patrimonio. Con comisiones típicas de 0,5–1 % del nominal, la métrica "¿le estás ganando al mercado?" de Comportamiento y las respuestas de la IA vienen ~0,5–1 pp por arriba de lo que muestra la Cartera.

**d. Dictamen** — Correcta: **`invested + commissions`**. Lo dice el propio código en seis lugares y `persister.py:747` lo persiste así.

**e. Qué ve mal el usuario y dónde**
- **Comportamiento** (`/comportamiento`) — capital promedio, P&L por posición, ranking.
- **Chat IA y Rendi AI** (`/ai`) — `invested_usd` y `unrealized_pnl_usd` de cada holding.
- **Análisis** (`/analisis`) — `geo_value` y `holdings_agg` de `insights.py`.
- **Ficha del activo en mobile** (`/posicion/:id` — `PositionDetailMobile`), que además contradice a la ficha desktop (`AssetDetail`, que sí las suma) para la misma posición.

**f. Causa raíz** — **Falta de una capa compartida.** Ocho sitios calculan "el costo de un lote" y la definición se corrigió en seis. No hay una función `realCost(p)` exportada.

**g. Fuente única de verdad** — Exportar `realCost(p)` de `valuation.js` y su espejo `real_cost(p)` en el backend, y prohibir `p.invested` pelado fuera de esa función (grep de CI).

---

### DIV-149 — Los plazos fijos entran en tres pantallas y en ninguna otra

**Estado de las citas:** ⚠️ **corregida.** `Dashboard.jsx:212` → real **`Dashboard.jsx:209-211`** (`const pf = pfUsd(usePfRollup(), tcValuacion)` en 209, la suma en 210-211). `Positions.jsx:1652` ✅ (`heroValue = totals.value + pfValueUsd`). `Insights.jsx:413` ✅.

**a. Implementaciones**

| superficie | ubicación | ¿PF? |
|---|---|---|
| Dashboard hero | `Dashboard.jsx:209-211` | ✅ vía `pfUsd(usePfRollup(), tcValuacion)` |
| Home mobile | `HomeMobile.jsx:102` | ✅ vía `pfUsd(...)` |
| Cartera **desktop** hero | `Positions.jsx:1650-1653` | ✅ pero con **conversión inline propia**, no `pfUsd` |
| Cartera **mobile** | `PositionsMobile.jsx` | ❌ **cero referencias a PF** (verificado por grep) |
| Análisis `totalPortfolio` | `Insights.jsx:413` | ❌ (sólo entra en `classBreakdown`/`sectorBreakdown`, `Insights.jsx:2147-2158`) |
| `snapshots` (browser y cron) | `Dashboard.jsx:478`, `snapshots_job.py` | ❌ por diseño explícito |
| todo el backend | — | ❌ `plazos_fijos` sólo tiene su propio CRUD (`main.py:9104-9260`) |

`Positions.jsx:1650-1651` reimplementa lo que `usePfRollup.js:34-38` (`pfUsd`) ya hace, línea por línea.

**b. Fórmulas** — `pfUsd`: `V = Σ_{USD} valorHoy + (Σ_{ARS} valorHoy)/tc` , `C = Σ_{USD} capital + (Σ_{ARS} capital)/tc`, con `valorHoy` de `computePf` (`valuation.js:800-870`, TNA simple / TEA compuesta / periódico capitalizado). La versión inline de `Positions.jsx` es idéntica; la ausencia en las demás es literalmente `+0`.

**c. ¿Real o cosmética? — REAL, por el monto entero del PF**

Usuario con US$ 50.000 en posiciones y un plazo fijo de ARS 20.000.000 al 30 % TNA constituido hace 180 días. MEP 1.450.
`valorHoy = 20.000.000 × (1 + 0,30×180/365) = ARS 22.958.904` → **US$ 15.833,73**.

| pantalla | patrimonio |
|---|---:|
| Dashboard hero / Home mobile / Cartera desktop | **US$ 65.833,73** |
| Cartera mobile | **US$ 50.000** |
| Análisis (`totalPortfolio`) | **US$ 50.000** |
| gráfico y Reportes (snapshots) | **US$ 50.000** |

**−24 %** entre dos pantallas de la misma app. Y en Análisis la inconsistencia es interna: la **torta** incluye la porción "Plazo fijo" pero el **denominador** de "% de la cartera", `cashRatio` (`Insights.jsx:1846`), la concentración top-3 (`:1971-1978`), `unrealizedPnl` (`:528`), `totalResult` (`:554`), la comparación contra benchmarks (`:2186-2196`) y el `total_usd` que va a la IA (`:2445`) no.

**d. Dictamen** — Ninguna es correcta. La fórmula debería ser: **un único valuador de patrimonio** `patrimonio = Σ posiciones + Σ plazos fijos + Σ futuros abiertos`, en el **backend**, del que todas las superficies (y el snapshot) leen. Hoy el PF es un parche client-side que cada pantalla decide si aplica.

**e. Qué ve mal el usuario y dónde** — El patrimonio en **Cartera mobile** (`/cartera` en celular) y en **Análisis** (`/analisis`) está corto por el valor íntegro del plazo fijo; y su rendimiento histórico (gráfico + Reportes) nunca incluyó el PF, así que un usuario que puso plata en un plazo fijo ve su curva "aplanarse" sin causa.

**f. Causa raíz** — **Migración a medio hacer / activo sin dueño.** Los PF viven en su propia tabla, se agregaron después del motor de valuación, y se sumaron a mano en las pantallas donde alguien se acordó.

**g. Fuente única de verdad** — Un `GET /api/portfolio/value` en el backend que devuelva el patrimonio completo, o —si se prefiere seguir en el cliente— un hook `useNetWorth()` que sea el **único** lugar donde se suman posiciones + PF + futuros, y borrar la conversión inline de `Positions.jsx:1650-1651`.

---

### DIV-150 — Los futuros no existen para ningún valor de cartera

**Estado de las citas:** ✅ (el mapa no da cita; verificado por grep exhaustivo).

**a. Implementaciones** — `futures_positions` aparece **sólo** en su propio CRUD: `main.py:1551` (DDL), `12232-12345` (list/create/update/delete/close), `14138`, `14373` (reapertura). **Cero** referencias en `snapshots_job.py`, `behavioral.py`, `valuation.js`, `Dashboard.jsx`, `Insights.jsx`, `Positions.jsx`.

El único valuador es `frontend/src/components/FuturosGroup.jsx:40-45`, con su **propio** fetch de precios (`:51-64`) y su propia fórmula:
```js
export function noRealizado(pos, precio) {
  if (precio == null || !isFinite(precio)) return null
  const pnl = (precio - pos.entry_price) * pos.quantity * dir
  return { pnl, pct: base > 0 ? pnl / base : null, precio }
}
```
Se muestra sólo dentro de **Operaciones** (`Operations.jsx`).

**b. Fórmulas** — `pnlᵢ = (pₜ − p_entryᵢ)·qᵢ·dirᵢ` con `dir = +1 long / −1 short`. La contribución al patrimonio (`margen + pnl`, o el mark-to-market de la posición) **no se calcula en ningún lado**.

**c. ¿Real o cosmética? — REAL.** Un usuario con un long de 2 BTC abierto a US$ 60.000 y BTC hoy en US$ 75.000 tiene **+US$ 30.000** no realizados que no aparecen en el hero del Dashboard, ni en Cartera, ni en Análisis, ni en el snapshot, ni en el libro del asesor, ni en la IA. Sólo los ve si entra a Operaciones y baja hasta el bloque "Futuros". Cuando el futuro se **cierra**, el P&L sí se acredita al efectivo del broker (`Operations.jsx:178`, `kind: 'futures'`) → el patrimonio pega un **salto discreto** de US$ 30.000 el día del cierre, que el gráfico y Reportes van a leer como "rendimiento del día".

**d. Dictamen** — Ninguna implementación es correcta a nivel patrimonio. La fórmula debería ser la misma que DIV-149: un valuador de patrimonio que sume `Σᵢ (margenᵢ + (pₜ − p_entryᵢ)·qᵢ·dirᵢ)`.

**e. Qué ve mal el usuario y dónde** — Todas las superficies de patrimonio, y en particular la **variación diaria** del Dashboard el día que se cierra un futuro.

**f. Causa raíz** — Misma que DIV-149: **activos fuera de `positions` sin dueño en la capa de valuación**.

**g. Fuente única de verdad** — Idem DIV-149.

---

### DIV-151 — La rama `costInPesos` de la fila de Cartera desktop no clampea; el total sí

**Estado de las citas:** ⚠️ **corregida.** El mapa dice `Positions.jsx:1265-1280`; la rama real es **`Positions.jsx:1269-1280`** (`if (costInPesos(p)) {` en 1269).

**a. Implementaciones**

**E1 — La fila, `Positions.jsx:1269-1280`:**
```js
if (costInPesos(p)) {
  // ... "No hay guard en esta rama → sin flip."   ← el comentario lo dice
  const realCost = routedInvUsd(p, tcCedear)
  const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true, p.asset_type)]
  if (priceArs == null) return { value: null, ..., investedUsd: realCost }
  const value = (priceArs * p.quantity) / tcCedear
  const pnl = value - realCost
  return { value, pnl, ... }
}
```
Ninguna llamada a `trustMktValue`. Las otras dos ramas de `calcUSDT` (`:1307-1310`) sí la llaman.

**E2 — El total del pie, `computeBrokerValue` → `valuePositionLot:573-604`:** llama a `trustMktValue(mktArs, realCost, p.asset_type, p.price_override != null)` y cae a `invUsdHoy` si no confía.

**b. Fórmulas**
- E1: `valorᵢ = qᵢ·p^BAᵢ / m` — **incondicional**.
- E2: `valorᵢ = 𝟙[mult ∈ B] · qᵢ·p^BAᵢ/m + (1−𝟙[mult ∈ B]) · cᵢ/m`

**c. ¿Real o cosmética? — REAL, ×100 en la fila contra el total**

Bono AL30, `asset_type='BONO'`, `currency='ARS'`, 10.000 nominales, `invested = ARS 12.000.000`, en broker `Balanz · USD`. MEP 1.450. `AL30.BA` cargado con precio per-100 leído per-1: ARS 12.500 en vez de 125.

- `mktArs = 12.500 × 10.000 = ARS 125.000.000` ; `mult = 125.000.000 / 12.000.000 = 10,4`
- Renta fija → banda `[0,02 ; 4]` → **10,4 > 4** → no confiar.

| | AL30 |
|---|---:|
| **fila** (E1, sin guard) | **US$ 86.206,90** |
| **total del pie** (E2, con guard) | **US$ 8.275,86** |

**Factor 10,4×**, en la misma tabla, con la fila arriba del total. Es exactamente el patrón "la suma de las filas no da el TOTAL del broker" que ya se corrigió una vez (commit `ad4295ca`) para el caso multi-lote y que sigue vivo por esta otra vía.

**d. Dictamen** — Correcta: **E2**. La fila debe llamar a `trustMktValue(priceArs * qty, realCostArs, asset_type, override != null)` con el costo en **pesos**, como hace la rama 2 del canónico.

**e. Qué ve mal el usuario y dónde** — **Cartera desktop** (`/cartera`): la fila del activo y su P&L%. El total del broker y el hero están bien → la tabla no cierra consigo misma.

**f. Causa raíz** — **Guard omitido en una rama.** El comentario `"No hay guard en esta rama → sin flip"` sugiere que fue deliberado (evitar que la celda parpadee entre valor y costo), pero el precio de esa decisión es que la fila y el pie muestran números distintos.

**g. Fuente única de verdad** — Que `calcUSDT`/`calcARS` **desaparezcan** y las filas llamen a `valuePositionLot`, que ya expone `valueUsd`, `investedUsdDisplay`, `priceLocal` y `priceTrusted` para exactamente este caso. El docstring de `valuePositionLot:502-509` dice que nadie la consume todavía: éste es el consumidor que falta.

---

### DIV-152 — La ficha del activo publica *costo ÷ tc_compra* como "Valor actual"

**Estado de las citas:** ⚠️ **corregida.** `AssetDetail.jsx:52-59` → real **`AssetDetail.jsx:50-59`**; `:70-79` → real **`AssetDetail.jsx:68-77`** (la rama `isAR` arranca en 70, el `mkt` está en 74).

**a. Implementaciones**

**F1 — `AssetDetail.jsx:50-59` (rama `costInPesos && !isAR`) y `:70-77` (rama `isAR`):**
```js
if (isAR) {
  const priceLocal = p.price_override ?? prices[priceSymbol(p.asset, true)]
  const investedUsd = invested / costBasisRate(p, tcValuacion, costBasis)   // ← ruteado por el MODO
  const guardCost   = invested / tcValuacion
  const mkt = priceLocal != null ? (priceLocal * qty) / tcValuacion : investedUsd   // ← sin precio: investedUsd
  const valueUsd = trustMktValue(mkt, guardCost, ...) ? mkt : investedUsd            // ← el fallback también
  return { valueUsd, investedUsd, pnlUsd: valueUsd - investedUsd, priceLocal }
}
```

**F2 — Canónico, `valuePositionLot:643-671`:**
```js
const invUsdHoy = realCost / cedearRate
...
return salida({
  investedUsd: trustArs ? invUsd : invUsdHoy,
  valueUsd:    trustArs ? mktArs / cedearRate : invUsdHoy,   // ← guardCost, dólar de HOY
})
```
con el comentario explícito: *"Antes los dos iban al tc_compra, o sea publicaba costo/tc_compra como valor de mercado."* — el bug ya fue diagnosticado y corregido en el canónico, **y no en AssetDetail**.

**El modo por defecto es `'purchase'`:** `CurrencyContext.jsx:102-109`, `localStorage.getItem(CB_STORAGE_KEY) === 'today' ? 'today' : 'purchase'`. Es decir, esto le pega a **todo el mundo salvo quien haya cambiado la preferencia a mano en `/config`**.

**b. Fórmulas**

Sin precio confiable, lote en pesos con `tc_compra = t₀` y MEP hoy `m`:
- **F2 (correcto):** `valor = costo = c/m` → `P&L = 0`
- **F1:** `valor = c/t₀` , `costo = c/t₀` → `P&L = 0` **pero el valor publicado está inflado por `m/t₀`**

Y el guard no lo atrapa: `trustMktValue(c/t₀, c/m)` → `mult = m/t₀` ≈ 1,45 → dentro de `[0,002 ; 50]` → confía.

**c. ¿Real o cosmética? — REAL, +45 % y creciendo con la devaluación**

GGAL en Cocos, `invested = ARS 1.000.000`, `tc_compra = 1.000` (compra de hace un año), MEP hoy = 1.450, sin cotización disponible (feriado BYMA, ticker sin precio, o `.BA` en NaN — caso frecuente, ver el proyecto "Barra .BA en NaN").

| | "Valor actual" |
|---|---:|
| Cartera / Dashboard (F2) | **US$ 689,66** |
| Ficha del activo (F1) | **US$ 1.000,00** |

**+45,0 %**. El factor es exactamente `MEP_hoy / tc_compra`: para una compra de 2023 con el dólar a 350, el factor sería **4,14×**.

**d. Dictamen** — Correcta: **F2**. El fallback sin precio debe ser `guardCost` (el costo al dólar de hoy), nunca el costo ruteado por el modo. El modo `'purchase'` describe *cuánto pusiste*, no *cuánto vale*.

**e. Qué ve mal el usuario y dónde** — **`/activo/:ticker`** (ficha del activo, desktop): el "Valor actual" de cualquier lote en pesos sin cotización. `PositionDetailMobile.jsx:118-127` **sí** hace lo correcto (`investedUsdDisplay = priced ? ... : u.investedUsd`), así que la ficha mobile y la desktop del mismo activo dan números distintos.

**f. Causa raíz** — **Fix aplicado en un solo lugar.** El bug se identificó, se documentó con nombre y apellido en el comentario de `valuePositionLot`, se corrigió en `valuation.js`, en `pesoLotUsd`, en `valueEquityLot` y en `PositionDetailMobile` — y `AssetDetail.valueLot`, que es una copia anterior de esa misma matriz ("reusa la lógica de PositionDetailMobile", dice su encabezado en `AssetDetail.jsx:32`), quedó afuera.

**g. Fuente única de verdad** — Borrar `AssetDetail.valueLot` (`AssetDetail.jsx:34-98`) y llamar a `valuePositionLot`.

---

### DIV-153 — El orden de las ramas difiere entre las tres matrices

**Estado de las citas:** ✅ (el mapa no da cita; verificadas las tres).

**a. Implementaciones**

| # | `valuePositionLot` (`valuation.js:566-731`) | `Positions.calcUSDT` (`:1263-1311`) | `PositionsMobile` (`:684-761`) |
|---|---|---|---|
| 1 | cash | cash | cash |
| 2 | `costInPesos && !isAR` | `costInPesos` | `isAR && costInUsd` |
| 3 | `costInUsd && isAR` | `CEDEAR \|\| arUsd` | `isAR` |
| 4 | `isAR` | else | `CEDEAR \|\| arUsd` |
| 5 | `CEDEAR \|\| arUsd` | — | **`costInPesos`** |
| 6 | else | — | else |

El comentario del canónico (`valuation.js:511`) dice en mayúsculas *"EL ORDEN DE LAS RAMAS IMPORTA"*, y `PositionsMobile` lo invierte: pone `costInPesos` **después** de `CEDEAR || arUsd`.

**b. Fórmulas** — El conjunto de solapamiento es `{ costInPesos ∧ ¬isAR ∧ (CEDEAR ∨ arUsd) ∧ ¬cripto ∧ ¬FCI ∧ override = null }`. Para ese conjunto:
- Canónico rama 2: `valor = q·p^BA/m` , `costo = c/costBasisRate` , guard sobre `(q·p^BA)/c` (en ARS).
- Mobile rama 4: `valor = (p^BA/m)·q` , `costo = c/m` (línea 676), guard sobre `((p^BA/m)·q)/(c/m) = (q·p^BA)/c` (en USD).

**Los dos cocientes del guard son idénticos** (el `m` se cancela) y los dos valores también. El `costBasisRate` se aplica en mobile por separado en `investedUsdDisplay` (`PositionsMobile.jsx:780-784`), incluida la rama `costInPesos`.

**c. ¿Real o cosmética? — COSMÉTICA hoy.** Recorrí el conjunto de solapamiento caso por caso (con/sin override, FCI, cripto, multi-lote) y el delta es **0** en todos. Pero es frágil por construcción: cualquier asimetría futura entre las ramas 2 y 5 (por ejemplo, un tratamiento distinto del `price_override`, o excluir un tipo de activo de una sola) produce números distintos sin que nada lo señale.

**d. Dictamen** — Correcta: **`valuePositionLot`**, por ser la que declara el invariante. Las otras dos deberían dejar de existir.

**e. Qué ve mal el usuario y dónde** — Hoy, nada. Es deuda estructural.

**f. Causa raíz** — **Copiar y pegar.** Cinco matrices con el mismo esqueleto y ninguna designada como origen (el propio docstring de `valuePositionLot:495-509` lo admite: *"había CINCO implementaciones… y ninguna era la buena a la que volver"*).

**g. Fuente única de verdad** — `valuePositionLot`. Ya está escrita, ya está testeada y **todavía no la consume nadie**. Migrar `Positions.calcUSDT/calcARS`, `PositionsMobile`, `AssetDetail.valueLot` y `PositionDetailMobile` es delta-0 salvo por los tres comportamientos que hoy difieren de verdad (DIV-148 comisiones, DIV-151 guard, DIV-152 fallback) — que son, justamente, los tres bugs de este informe.

---

### DIV-154 — Seis reimplementaciones usan `tcValuacion` donde el canónico usa `cedearRate`

**Estado de las citas:** ⚠️ **parcialmente corregida.**

| cita del mapa | real | ✓ |
|---|---|---|
| `Dashboard.jsx:326` | `Dashboard.jsx:326-329` (`trustMktValue` + `/ tcValuacion`) | ✅ |
| `Dashboard.jsx:536` | `Dashboard.jsx:536` (`pnlForBroker = pnlArs / tcValuacion + …`) | ✅ |
| `Insights.jsx:438` | `Insights.jsx:438-439` | ✅ |
| `AssetDetail.jsx:71` | `AssetDetail.jsx:72-74` | ⚠️ −1/−3 |
| `PositionDetailMobile.jsx:113` | `:111` (cash) y `:141-152` (`isAR`) | ⚠️ |
| `PositionsMobile.jsx:722` | `PositionsMobile.jsx:721-722` (y `:675`, `:685`) | ✅ |

**a. Implementaciones** — El canónico `valuePositionLot` **nunca** usa `tcValuacion`: lo destructura sólo para el default `const cedearRate = tcCedear ?? tcValuacion` (`valuation.js:568`) y todas las ramas —cash ARS incluido— dividen por `cedearRate`. Las seis reimplementaciones usan `tcValuacion` en la rama ARS.

**b. Fórmulas**
- Canónico: `valorᵢ = qᵢ·p^BAᵢ / m_cedear` para **todo** el path ARS (tenencias **y** cash).
- Reimplementaciones: `valorᵢ = qᵢ·p^BAᵢ / m_valuacion`.

**c. ¿Real o cosmética? — COSMÉTICA hoy, con precedente sangriento.**

Verifiqué las seis definiciones de las dos variables:

| archivo | `tcValuacion` | `tcCedear` | ¿iguales? |
|---|---|---|---|
| `Dashboard.jsx:192-193` | `pick(dolar, vd) \|\| config.tc_blue \|\| 1415` | `pick(dolar, vd) \|\| tcValuacion` | **sí, siempre** |
| `Positions.jsx:241,253` | `pick(dolar, vd) \|\| config.tc_mep \|\| config.tc_blue \|\| 1415` | `tcMep` (= `tcValuacion`, línea 242) | **sí, siempre** |
| `PositionsMobile.jsx:629-630` | `pick(dolar, vd) \|\| 1415` | `pick(dolar, vd) \|\| tcValuacion` | **sí, siempre** |
| `Insights.jsx:407-408` | ídem | ídem | **sí** |
| `PositionDetailMobile.jsx:96-97` | ídem | ídem | **sí** |
| `AssetDetail.jsx:151` | ídem | ídem | **sí** |

Delta **0** en el estado actual del código. Pero este bug **ya ocurrió**: el comentario de `Positions.calcARS` (`Positions.jsx:1313-1320`) documenta el caso real —*"con un MEP ~13 % arriba del blue, 10 filas que sumaban USD 64.147,88 daban un TOTAL de USD 56.582,51"*, un **−11,8 %**— y se corrigió **sólo en `calcARS`**. Las otras seis siguen escritas de la forma que produjo ese número.

Ejemplo de qué pasaría si mañana alguien separa los rieles (p. ej. "CEDEARs al CCL, cash al MEP"), con CCL 1.640 y MEP 1.450: US$ 100.000 de tenencias .BA valuadas a MEP en el canónico y a CCL en Dashboard/Análisis → **US$ 88.415 vs US$ 100.000, −11,6 %**.

**d. Dictamen** — Correcta: **`cedearRate` para todo el path ARS**. `tcValuacion` no debería existir como parámetro separado de la valuación: la firma `computeBrokerValue(pos, prices, broker, tcValuacion, cedearRate = tcValuacion, …)` mantiene viva una distinción que el cuerpo de la función ya no usa.

**e. Qué ve mal el usuario y dónde** — Hoy, nada. Es una **divergencia latente** con precedente medido.

**f. Causa raíz** — **Copiar y pegar de una versión anterior del motor**, cuando `tcValuacion` (blue) y `cedearRate` (MEP) sí eran distintos. La unificación se hizo en `valuation.js` y en `calcARS` y no se propagó.

**g. Fuente única de verdad** — Borrar el parámetro `tcValuacion` de `computeBrokerValue`/`valuePositionLot` (dejar sólo `cedearRate`) para que la distinción no se pueda reintroducir por accidente, y migrar las seis reimplementaciones a `valuePositionLot`.

---

### DIV-155 — El libro del asesor valúa a la punta de venta; todo lo demás al MEP medio

**Estado de las citas:** ⚠️ **corregida.** `main.py:36806` → real **`backend/main.py:36820`** (`def _advisor_book_fx(conn):`); el cuerpo va hasta 36841. `advisor_brief.py:163` → real **`backend/advisor_brief.py:160`** (`def _fx(conn):`).

**a. Implementaciones**

**G1 — `main.py:36820-36841`:**
```python
fx = conn.execute(
    "SELECT blue_venta, mep_venta FROM fx_rates_daily ORDER BY date DESC LIMIT 1").fetchone()
tc_mep = float(fx["mep_venta"]) if fx and fx["mep_venta"] else None
```
`fx_rates_daily.mep_venta` se escribe desde `main.py:5034` → `(_dolar_cache["data"].get("mep") or {}).get("venta")` → **la punta de venta cruda**.

**G2 — `advisor_brief.py:160-171`:**
```python
_live = main._current_cedear_rate()   # medio, misma fuente que el snapshot
if _live and float(_live) > 0:
    return (blue, float(_live))
```
`_current_cedear_rate` (`main.py:4939-4955`) → `_val_rate` (`main.py:4630-4644`) → `obj.get("medio") or obj.get("venta")`.

**G3 — Frontend, `CurrencyContext.jsx:46-54`:** `const rate = c => c?.medio ?? c?.venta`.

**b. Fórmulas** — `valor_USD = valor_ARS / m`, con `m = mep_venta` (G1) vs `m = mep_medio = (compra+venta)/2` (G2/G3).

**c. ¿Real o cosmética? — REAL, −0,69 % diario y estructural**

MEP compra 1.440 / venta 1.460 → medio 1.450. Spread típico ~1,4 %.

Cliente con US$ 100.000 de tenencias denominadas en pesos:

| | AUM del cliente |
|---:|---:|
| Dashboard del cliente / brief del asesor (medio 1.450) | **US$ 100.000,00** |
| Libro del asesor (venta 1.460, `_advisor_book_fx`) | **US$ 99.315,07** |

**−US$ 684,93 (−0,69 %)**, todos los días, sin causa de mercado. El comentario de `advisor_brief._fx:161-165` lo dice literal: *"si no, el valor vivo y el snapshot se valúan con dólares distintos y aparece una pérdida fantasma de ~0,7 % todos los días"*.

Sobre un libro de US$ 5.000.000 son **US$ 34.250** de AUM que desaparecen — y el asesor los ve como pérdida atribuible a su gestión.

**d. Dictamen** — Correcto: **el MEP MEDIO** (G2/G3). Es lo que valúa el broker (Cocos/IOL) y lo que ya usa `_current_cedear_rate` en snapshots, Análisis, IA y frontend. `_advisor_book_fx` es el único que quedó en la punta.

Nota: hay un problema subyacente más serio — **`fx_rates_daily` sólo guarda una punta** (`ledger_replay.py:21,31`: *"lo único disponible por fecha es `mep_venta`, una sola punta"*). Cualquier consumidor histórico de esa columna hereda el sesgo.

**e. Qué ve mal el usuario y dónde** — **El asesor**, en tres pantallas que comparten `_advisor_book_fx`:
- **Libro** (`main.py:35462`, `36983`)
- **Informes** (`main.py:37689`)
- **Contexto de la IA del asesor** (`main.py:37825`, `35961`)

Y el número no coincide con el que el **brief diario** (`advisor_brief.py`) le manda por mail sobre el mismo cliente el mismo día.

**f. Causa raíz** — **Fix aplicado en un solo lugar.** El cambio "punta → medio" se hizo en `_fetch_dolar`/`_val_rate`/`_current_cedear_rate`/`pickFinancialRate`, y `_advisor_book_fx` —que no pasa por el caché sino directo por la tabla— quedó del lado viejo. La ironía es que su propio docstring dice haber sido creada para eliminar exactamente este tipo de divergencia: *"dos pantallas del asesor mostrando el mismo libro a tipos de cambio distintos es el bug clásico de esta app. Una sola copia = no puede pasar."* Pasó, pero un nivel más arriba.

**g. Fuente única de verdad** — `_advisor_book_fx` debe delegar en `_current_cedear_rate()` con fallback a `fx_rates_daily`, es decir, ser idéntica a `advisor_brief._fx`. Mejor todavía: que `advisor_brief` importe `_advisor_book_fx` y quede una sola.

---

### DIV-157 — `cash_value` suma pesos y dólares sin convertir

**Estado de las citas:** ⚠️ **corregida.** `main.py:32833` → el bloque de comentario arranca en **`main.py:32832`** y la asignación real está en **`main.py:32855`**. La query está en `:32849-32854`.

**a. Implementación** — `backend/main.py:32847-32855`, dentro de `_portfolio_snapshot_summary` (`main.py:32635`):
```python
_cash_clause = "" if broker_filter == "global" else " AND broker = ?"
cash_row = conn.execute(
    f"""SELECT COALESCE(SUM(invested), 0) AS cash
          FROM positions
         WHERE user_id = ? AND COALESCE(is_cash, 0) = 1{_cash_clause}""", (uid, *_cash_args)).fetchone()
cash_value = float(cash_row["cash"] or 0) if cash_row else 0.0
```

**b. Fórmula** — `cash_value = Σᵢ investedᵢ` sobre todas las filas `is_cash`, **sin `/fxᵢ`**, publicado en un payload cuyos demás campos están en USD.

**c. ¿Real o cosmética? — REAL (×1.450) pero sin consumidor.**

Usuario con ARS 5.000.000 en Cocos y US$ 2.000 en Schwab. `cash_value = 5.002.000`, rotulado dólares. El valor correcto sería `5.000.000/1450 + 2.000 = US$ 5.448,28`. **Factor 918×**.

Verifiqué el consumo: `cash_value` no aparece en `frontend/src/` salvo como literal de fixture en `utils/demo.js`. El `cash_value` de `reporting/detectors.py:221` es una **variable local homónima** que sí convierte correctamente (`p.get("value_usd")`). Es una clave muerta del payload de `GET /api/reports/period/{type}/{key}`.

**d. Dictamen** — Ninguna implementación es correcta. La fórmula debería ser `Σᵢ investedᵢ / fx(_native_ccy(pᵢ))`, como hace `behavioral._position_value_usd`.

**e. Qué ve mal el usuario y dónde** — **Nada hoy.** Pero la clave viaja en la respuesta de `/api/reports/period/…` y cualquiera que la lea mañana (la IA, un dashboard nuevo, un asesor consumiendo la API) va a leer pesos como dólares.

**f. Causa raíz** — **PARCHE documentado y dejado a propósito.** El comentario (`main.py:32832-32846`) explica el defecto, explica el arreglo correcto, y decide no hacerlo: *"nadie lo consume… se deja exactamente como estaba (sin mejorar ni empeorar) en vez de escribir deuda nueva a propósito sobre una métrica muerta"*. Es honesto, pero deja una bomba de relojería en un contrato público.

**g. Fuente única de verdad** — **Borrar la clave del payload.** Si nadie la consume, no hay motivo para publicarla; si algún día se necesita, que se calcule con `_native_ccy`.

---

### DIV-158 — `top_holdings` ordena por COSTO con un MEP estático

**Estado de las citas:** ⚠️ **corregida (−1).** `main.py:32809` → la query arranca en **`main.py:32810`**; el `_mep` del config se lee en `:32796-32803`; el resultado se arma en `:32823-32830`.

**a. Implementación** — `backend/main.py:32796-32830`:
```python
_mep_row = conn.execute("SELECT value FROM config WHERE key='tc_mep' AND user_id=?", (uid,)).fetchone()
_mep = float(_mep_row["value"]) if ... else 0.0
if not _mep > 0:
    _mep = 1415.0                      # default hardcodeado
top_rows = conn.execute(f"""
    SELECT p.asset, p.broker, COALESCE(p.invested, 0) AS invested,
           COALESCE(p.invested, 0) / (CASE WHEN UPPER(COALESCE(br.currency,'')) = 'ARS'
                                           THEN ? ELSE 1 END) AS invested_usd
      FROM positions p LEFT JOIN brokers br ON …
     WHERE … ORDER BY invested_usd DESC LIMIT 3""", (_mep, uid, *br_args)).fetchall()
```

**b. Fórmulas**
- Actual: `rankᵢ = investedᵢ / (currency=ARS ? tc_mep_config : 1)` — **costo**, con un MEP **estático del `config`** (default 1415), sin comisiones, sin `_native_ccy` (mira el broker, no el lote), y sin el sub-broker `· USD`.
- Debería ser: `rankᵢ = valor_de_mercadoᵢ`, es decir `valuePositionLot(pᵢ).valueUsd`.

**c. ¿Real o cosmética? — REAL: puede nombrar otro activo.**

Cartera: AAPL en Schwab (`invested = US$ 5.000`, hoy vale US$ 8.500) y GGAL en Cocos (`invested = ARS 6.000.000`, hoy `GGAL.BA` da US$ 3.400 a MEP real 1.550).

| criterio | ranking |
|---|---|
| actual (costo, `_mep`=1.415 del default) | GGAL **US$ 4.240** > AAPL US$ 5.000 → **AAPL** gana… por poco |
| actual con `_mep` real 1.550 | GGAL US$ 3.871 → **AAPL** |
| correcto (valor de mercado) | AAPL **US$ 8.500** vs GGAL **US$ 3.400** → **AAPL**, con el doble de distancia |

Y con los números invertidos (GGAL `invested` ARS 12.000.000 = US$ 7.742 al costo pero hoy vale US$ 4.100 tras una caída del 47 %, contra AAPL US$ 5.000 → US$ 8.500): el KPI dice **GGAL** y la realidad es **AAPL**. El "Top holding" de Reportes nombra el activo equivocado.

Además, un CEDEAR en `Cocos · USD` (broker `currency='USDT'`) toma el `ELSE 1` del CASE → su costo en pesos, si el lote es `currency='ARS'`, entra 1:1 como dólares y gana siempre (el mismo bug que DIV-145, por otra vía).

**d. Dictamen** — Ninguna implementación es correcta. Debería usar el valuador (`compute_broker_value_usd` o `behavioral._position_value_usd`, que ya existen y ya están importados en ese archivo) y ordenar por `value_usd`.

**e. Qué ve mal el usuario y dónde** — KPI **"Top holding"** de **Reportes** (`/reportes` → `Reports.jsx:689-695`, `snap.top_holdings[0]`), alimentado por `GET /api/reports/period/{period_type}/{period_key}` (`main.py:33136`) → `portfolio_snapshot.top_holdings` (`main.py:33211`).

**f. Causa raíz** — **PARCHE parcial.** El comentario (`main.py:32784-32795`) documenta que se arregló *la moneda* ("un `ORDER BY invested` crudo compara pesos contra dólares y las filas del padre ganan siempre por ~1400×"), pero se resolvió con un `CASE` en SQL en vez de con el valuador — así que quedó arreglada la moneda y sin arreglar la *magnitud* (costo ≠ valor) ni la *fuente del FX* (config estático ≠ MEP del día) ni el sub-broker.

**g. Fuente única de verdad** — Que `_portfolio_snapshot_summary` reutilice el mismo valuador que ya usa `_valuate_positions_for_chat` (`main.py:22818`), que devuelve `value_usd`/`invested_usd` por holding ya agregado y ordenado.

---

### DIV-159 — El modo demo no comparte nada con el motor real

**Estado de las citas:** ⚠️ **corregida.** El mapa dice `demo.js:200-260`; el motor real está en **`frontend/src/utils/demo.js:210-226`** (`_BROKER_LIVE_USD`); las líneas 189-208 son los dos bloques de comentario que **declaran** la equivalencia.

**a. Implementación** — `frontend/src/utils/demo.js:210-226`:
```js
const _DEMO_TC_BLUE = 1415
for (const p of POSITIONS) {
  let v = 0
  if (p.is_cash) {
    v = p.broker === 'Cocos' ? (p.quantity || 0) / _DEMO_TC_BLUE : (p.invested || 0)
  } else if (p.broker === 'Cocos') {
    const priceArs = PRICES[p.asset + '.BA']
    v = priceArs != null ? (priceArs * (p.quantity || 0)) / _DEMO_TC_BLUE : (p.invested || 0) / _DEMO_TC_BLUE
  } else {
    const priceUsd = PRICES[p.asset]
    v = priceUsd != null ? priceUsd * (p.quantity || 0) : (p.invested || 0)
  }
  ...
}
```
El comentario de arriba (`demo.js:189-208`, repetido dos veces) dice *"el mismo algoritmo que `computeBrokerValue` del frontend"*.

**b. Fórmulas** — Diferencias verificadas contra `valuePositionLot`:

| pieza del canónico | demo |
|---|---|
| discriminador de moneda: `broker.currency` | **`p.broker === 'Cocos'` hardcodeado** |
| `trustMktValue` | **ausente** |
| rama 2 `costInPesos && !isAR` | ausente |
| rama 3 `costInUsd && isAR` | ausente |
| rama 5 `CEDEAR \|\| arUsd` → `.BA ÷ MEP` | ausente (un CEDEAR fuera de "Cocos" se precia por el ticker US) |
| `cryptoBrokerFactor` | ausente |
| comisiones (`+ p.commissions`) | ausente |
| cash: `p.invested` | **`p.quantity`** para el cash ARS |
| tasa: `pickFinancialRate` (MEP del día) | `1415` fijo |
| `priceSymbol` (FCI, `BRK-B`, override) | `p.asset + '.BA'` literal |

**c. ¿Real o cosmética? — REAL pero acotada al fixture.** Como el fixture está armado a medida (un solo broker ARS llamado "Cocos", sin CEDEARs en cuenta USD, sin cripto de broker, sin comisiones), los números *hoy* cierran. Pero el motor no es el mismo, y cualquier posición nueva que se agregue al fixture (un CEDEAR, una cripto, un bono, un lote en pesos) se va a valuar mal **sólo en demo**.

Concreto: si el fixture agrega BTC en un broker no-exchange, el demo lo precia a spot y la app real le aplica el factor cripto/MEP (~+5 %). Si agrega un bono per-100, el demo lo muestra ×100 (no hay guard) y la app real lo clampea.

**d. Dictamen** — Ninguna es "correcta": el demo debería **importar `computeBrokerValue`** de `valuation.js` y pasarle `BROKERS`, `POSITIONS`, `PRICES` y `_DEMO_TC_BLUE`. La función es pura y no tiene ninguna dependencia de red.

**e. Qué ve mal el usuario y dónde** — **Modo demo** (`/login` → "Ver demo", `AuthContext.jsx:4`). Es la primera impresión de un prospecto, y el total del portfolio del demo (`_COMPUTED_PORTFOLIO_TOTAL_USD`) además **deriva los pesos por broker de `MONTHLY`** (`demo.js:249-254`), así que un error acá se propaga al gráfico de evolución del demo.

**f. Causa raíz** — **Fixture escrito a mano**, con un comentario que *afirma* la equivalencia en vez de garantizarla por construcción.

**g. Fuente única de verdad** — `import { computeBrokerValue } from './valuation'` en `demo.js`. Cuatro líneas reemplazan diecisiete y el comentario deja de mentir.

---

## Parches detectados

| ubicación | qué síntoma tapa | causa real | dónde más sigue rompiendo |
|---|---|---|---|
| `snapshots_job.py:245-265` (`_cost_in_usd`) | "la tenencia dólar en Balanz colapsa ~1/MEP" | falta el par completo de ramas de moneda-del-lote: se portó `costInUsd` y **no** `costInPesos` (DIV-145) | chat IA (`main.py:22882`), libro asesor (`36924`), brief (`advisor_brief.py:152`), `ledger_replay.py:273`, `backfill_historical_mtm.py:520`, `main.py:25468` |
| `main.py:32832-32855` (`cash_value`) | ninguno: **documenta** el bug y lo deja | no hay conversión por `_native_ccy` en `_portfolio_snapshot_summary` | latente en el contrato de `GET /api/reports/period/…`; el día que alguien lea la clave |
| `main.py:32796-32821` (`top_holdings`) | "las filas del padre ARS ganan siempre por ~1400×" | se arregló la **moneda** con un `CASE` de SQL en vez de usar el valuador → quedan sin arreglar magnitud (costo≠valor), FX (config estático) y sub-broker `· USD` | KPI "Top holding" de Reportes; el mismo `CASE` reaparecería en cualquier ranking nuevo |
| `behavioral.py:452-459` (return del override antes del guard) | "el precio manual del usuario se respeta" | el guard se re-portó sin `has_override`, así que la única forma de "respetar" el override era saltearlo → se perdió el clamp de renta fija | Comportamiento, los 8 builders de IA, `reporting/timeline.py:144`, `main.py:15263` |
| `backfill_historical_mtm.py:532-543` (guard inline) | "capital_final negativo gigante (485 → −592.944)" | el negativo lo produce la valuación cross-currency, no el precio; el guard duplicado lo esconde | el valor cross-currency mal calculado sigue mal en `compute_broker_value_usd`; acá sólo se lo pone en 0 |
| `Positions.jsx:1650-1651` | ninguno; reimplementa `pfUsd` inline | no hay un valuador de patrimonio único (DIV-149) | el día que `pfUsd` cambie (p. ej. TC de la fecha de constitución), Cartera desktop no lo sigue |
| `Positions.jsx:1269-1280` (`"No hay guard en esta rama → sin flip"`) | el parpadeo de la celda entre valor y costo | el guard debería correr una vez, en el motor, no por rama de UI | la fila muestra ×10 a ×100 contra su propio total (DIV-151) |
| `demo.js:210-226` (`p.broker === 'Cocos'`) | "el demo tiene que dar el mismo total que el gráfico" | el demo no usa el motor | cualquier posición nueva en el fixture |

---

## Citas del mapa incorrectas

| DIV | cita del mapa | ubicación real | qué decía mal |
|---|---|---|---|
| DIV-145 | `valuation.js:578-604` | **`valuation.js:573-604`** | la rama arranca 5 líneas antes (`if (!p.is_cash && !isAR && costInPesos(p))`) |
| DIV-146 | `snapshots_job.py:158-160` | **`snapshots_job.py:185`** (decisión) · `:60-67` (helper) · `:70-86` (versión parent-aware) | 158 es la **firma** de `compute_broker_value_usd`, no la decisión `ar_usd` |
| DIV-147 | `behavioral.py:449-457` | **`behavioral.py:452-459`** | +3 líneas. `behavioral.py:47` ✅ |
| DIV-147 | *"tres versiones"* | **cuatro** | falta `backend/scripts/backfill_historical_mtm.py:532-543` (guard inline con regla `val < 0` y sin `has_override`) |
| DIV-148 | `behavioral.py:412` | **`behavioral.py:391`** (def) · **`:426`** (`invested_native`) | −21 líneas |
| DIV-148 | `insights.py:432` | **`ai/builders/insights.py:433`** | −1 línea |
| DIV-148 | *"las otras cuatro implementaciones usan invested + commissions"* | **seis** con comisiones, **tres** sin | falta `PositionDetailMobile.jsx:101`, que tampoco las suma en 4 de sus 6 ramas |
| DIV-149 | `Dashboard.jsx:212` | **`Dashboard.jsx:209-211`** | −1/−3 |
| DIV-149 | (no lo menciona) | **`PositionsMobile.jsx`** | Cartera **mobile** tampoco incluye el PF (cero referencias) — el mapa sólo nombra Análisis, snapshots y backend |
| DIV-151 | `Positions.jsx:1265-1280` | **`Positions.jsx:1269-1280`** | la rama arranca en 1269 |
| DIV-152 | `AssetDetail.jsx:52-59` y `:70-79` | **`AssetDetail.jsx:50-59`** y **`:68-77`** | −2 en las dos |
| DIV-154 | `AssetDetail.jsx:71` | **`AssetDetail.jsx:72-74`** | la línea 71 es el `priceLocal`; el `tcValuacion` está en 72-74 |
| DIV-154 | `PositionDetailMobile.jsx:113` | **`:111`** (cash) y **`:141-152`** (`isAR`) | 113 es el `else if (costInPesos…)` |
| DIV-155 | `main.py:36806` | **`backend/main.py:36820`** | −14 líneas |
| DIV-155 | `advisor_brief.py:163` | **`backend/advisor_brief.py:160`** | −3 líneas |
| DIV-157 | `main.py:32833` | **`main.py:32855`** (asignación) · `:32832` (inicio del comentario) | −22 |
| DIV-158 | `main.py:32809` | **`main.py:32810`** | −1 |
| DIV-159 | `demo.js:200-260` | **`demo.js:210-226`** | el motor son 17 líneas; 189-208 son los comentarios que declaran la equivalencia |

**Ninguna cita del mapa era falsa en sustancia** salvo DIV-146, donde la línea apuntaba a la firma en vez de a la decisión, y DIV-147/DIV-148, donde el **conteo** de versiones estaba corto.

---

## URGENTE

**DIV-145 + DIV-146 corrompen datos persistidos e irreversibles.**

A diferencia de todo lo demás en este informe (que es un número mal *mostrado*, y se arregla el día que se corrige el código), estas dos escriben valores falsos en `snapshots.total_value` y `snapshots.total_invested`, **una fila por usuario por día, todas las noches**. Esa tabla es la memoria histórica de la app: alimenta el gráfico del Dashboard, la variación diaria, los reportes de período, el TWR, el AUM del libro del asesor y el contexto de la IA. Cada noche que pasa es una fila más que después hay que backfillear.

Los tres factores que lo hacen urgente y no meramente grave:

1. **La magnitud no es marginal.** DIV-145 escribe el costo en pesos como dólares: **×1.360** en el caso verificado. Una sola posición así puede convertir un patrimonio de US$ 50.000 en uno de US$ 1.500.000 en la serie.
2. **El guard de integridad no lo ve.** `snapshots_job.py:706-742` existe precisamente para no persistir un snapshot corrupto, y en los dos casos reporta **cobertura 100 %** porque mide con la función correcta (`position_price_key`, parent-aware) mientras la valuación usa la incorrecta. El sistema de defensa está mirando para otro lado.
3. **No hay señal.** Ninguno de los dos casos produce excepción, warning ni log. El usuario ve el hero bien (se calcula en el browser) y sólo el gráfico mal, que es exactamente el tipo de discrepancia que se atribuye a "el mercado" y no a un bug.

Además, DIV-156 hace que el cron **pise** cualquier snapshot correcto que el browser hubiera escrito ese día (`snapshots_job.py:786-790`, sin condición), mientras el browser **no** pisa al cron (`main.py:5060-5064`). O sea: el motor roto tiene prioridad de escritura sobre el motor bueno.

**No toqué una línea de código.** Recomiendo, en este orden: (a) medir cuántos lotes con `currency='ARS'` viven hoy en brokers `currency != 'ARS'`, y cuántos sub-brokers tienen `parent_broker_id` con padre ARS pero sin `·` en el nombre — eso dimensiona la población afectada antes de decidir nada; (b) portar la rama 2 y volver `ar_usd` parent-aware; (c) recién después, backfill de la serie.

---

## BLOQUE-RESUMEN

| concepto | DIV | versiones | difieren | correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---|---:|---|---|---|---|---|
| Valuación de cartera / valor de mercado | DIV-145 | 2 | SÍ — ×1.360 (pesos contados 1:1 como USD + guard cruzando monedas) | `valuation.js:573-604` (`valuePositionLot` rama 2) | gráfico y Var. día del Dashboard, Reportes, TWR, libro/brief del asesor, chat IA | 🔴 alta | port incompleto al backend (se portó `costInUsd` y no `costInPesos`) |
| Valuación de cartera / valor de mercado | DIV-146 | 2 | SÍ — cae a costo en silencio (−72 % medido) | `snapshots_job._broker_name_sets` (parent-aware) | ídem DIV-145 | 🔴 alta | fix aplicado en un solo lugar del mismo archivo (`build_price_symbols` sí, valuación no) |
| Valuación de cartera / valor de mercado | DIV-147 | 4 | SÍ — ×100 en renta fija con `price_override` | `valuation.js:448` `trustMktValue` | Comportamiento, los 8 builders de IA, Reportes timeline | 🟠 media-alta | re-port perdiendo el parámetro `has_override` + return antes del guard |
| Valuación de cartera / valor de mercado | DIV-148 | 8 (6 bien, 3 mal) | SÍ — 0,5–1 % sistemático, siempre optimista | `invested + commissions` | Comportamiento, chat IA, Análisis, ficha del activo mobile | 🟡 media | falta de una capa compartida (`realCost(p)` no existe) |
| Valuación de cartera / valor de mercado | DIV-149 | 3 (+3 ausencias) | SÍ — el valor íntegro del plazo fijo | ninguna: falta un valuador de patrimonio | Cartera mobile, Análisis, gráfico/Reportes, todo el backend | 🟠 media-alta | activos fuera de `positions` sin dueño en la capa de valuación |
| Valuación de cartera / valor de mercado | DIV-150 | 1 (aislada) | SÍ — el no realizado de futuros no está en ningún patrimonio | ninguna | todas las superficies de patrimonio; salto discreto al cerrar el futuro | 🟡 media | ídem DIV-149 |
| Valuación de cartera / valor de mercado | DIV-151 | 2 | SÍ — ×10 a ×100 entre la fila y el total | el total (`computeBrokerValue`) | Cartera desktop: fila y P&L% del activo | 🟠 media-alta | guard omitido a propósito en una rama de UI |
| Valuación de cartera / valor de mercado | DIV-152 | 2 | SÍ — +45 % (factor `MEP_hoy/tc_compra`) | `valuePositionLot` (fallback a `guardCost`) | `/activo/:ticker` — "Valor actual" sin cotización, en el modo por defecto | 🟠 media-alta | fix aplicado en un solo lugar (copia previa de la matriz) |
| Valuación de cartera / valor de mercado | DIV-153 | 3 | NO — delta 0 verificado caso por caso | `valuePositionLot` | ninguna hoy (deuda estructural) | ⚪ cosmética | copiar y pegar; ninguna designada como origen |
| Valuación de cartera / valor de mercado | DIV-154 | 7 | NO — hoy `tcValuacion === tcCedear` en las 6 páginas | `cedearRate` para todo el path ARS | ninguna hoy; precedente medido de −11,8 % (56.582 vs 64.147) | ⚪ cosmética | copiar y pegar de una versión previa del motor |
| Valuación de cartera / valor de mercado | DIV-155 | 2 | SÍ — −0,69 % diario (punta de venta vs medio) | el MEP MEDIO (`_current_cedear_rate`) | libro, informes y contexto IA del asesor; no coincide con su propio brief diario | 🟡 media | fix aplicado en un solo lugar (`_advisor_book_fx` lee la tabla, no el caché) |
| Valuación de cartera / valor de mercado | DIV-156 | 2 | SÍ — por DIV-145/146 en el valor, y `total_invested` con dos definiciones (modo `purchase` vs MEP de hoy) | el motor del browser (`computeBrokerValue`) | serie histórica completa: gráfico Dashboard, Reportes, TWR | 🟠 media-alta | migración a medio hacer (el cron se sumó al escritor viejo en vez de reemplazarlo) |
| Valuación de cartera / valor de mercado | DIV-157 | 1 | SÍ — ×918 en el ejemplo (pesos + USD sumados 1:1) | ninguna (debería ser `Σ invested/fx(_native_ccy)`) | ninguna hoy — clave muerta del payload de `/api/reports/period/…` | ⚪ cosmética | PARCHE documentado y dejado a propósito |
| Valuación de cartera / valor de mercado | DIV-158 | 1 | SÍ — puede nombrar el activo equivocado | ordenar por valor de mercado (`value_usd` del valuador) | KPI "Top holding" de Reportes | 🟡 media | PARCHE parcial: se arregló la moneda con un `CASE` de SQL, no la valuación |
| Valuación de cartera / valor de mercado | DIV-159 | 1 | SÍ — sin guard, sin `costInPesos/costInUsd`, sin factor cripto, sin rama CEDEAR, broker hardcodeado | `computeBrokerValue` (importable, función pura) | modo demo (`/login` → "Ver demo"), incluido su gráfico de evolución | ⚪ cosmética | fixture escrito a mano con un comentario que afirma una equivalencia que no existe |
