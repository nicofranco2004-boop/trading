# 1B — Casos borde

Commit auditado: `b74f450f2badf1a2b84e657551115a0595110e45` (copia de solo lectura `/tmp/rendi-main`, verificada: `backend/main.py` = 38.029 líneas).
Deriva verificada: `origin/main` = `82fad6a0` toca `backend/pricing/fci.py`, `frontend/src/components/AddPositionFlow.jsx`, `backend/tests/test_fci_uala.py`. **Un solo hallazgo mío cae en un archivo de la deriva (B-02, `pricing/fci.py`); lo verifiqué contra `82fad6a0` y NO está corregido** (el diff sólo agrega el allowlist de Ualá y `EMISOR_OVERRIDES`; no toca `refresh_prices`).
Ningún hallazgo cae en `backend/snapshots_job.py` como zona de trabajo activa que haya que marcar — los dos que lo citan (`_trust_mkt_value`, `read_last_prices`) son lecturas de funciones, no de la lógica del job de la rama `fix/snapshots-valuacion`.

---

## Método

**Qué ejecuté.**

1. **Motor de valuación del frontend, aislado y corrido de verdad.** Copié `frontend/src/utils/` a `/tmp/borde-1b/utils` (NO ejecuté nada dentro de `/tmp/rendi-main`) y llamé `valuePositionLot`, `computeBrokerValue`, `trustMktValue`, `avgCostUsdPerUnit`, `sumRowUSDT`, `sumRowARS`, `buildPriceSymbols`, `computeReturnDelta`, `computeMonthlyConsistency`, `computeBrokerConcentration`, `computeAssetTypeBreakdown`, `computeAllocationBuckets` con entradas degeneradas (precio 0, precio negativo, precio NaN, cantidad 0/negativa/null, invested 0/negativo, MEP 0/null/undefined, listas vacías). Node v24, ESM con un resolve-hook propio para los imports sin extensión. Trazas pegadas abajo.
2. **Backend, con la app real levantada.** Copié `backend/` a `/tmp/borde-1b/backend`, seteé `DB_PATH=/tmp/borde-1b/borde.db` **antes** de `import main` (por eso no se creó ningún `trading.db` dentro de `/tmp/rendi-main` — verificado listando el directorio después de importar) y levanté `fastapi.testclient.TestClient(main.app)`. Con eso hice E2E real: alta de usuario, brokers, posiciones, operaciones, ventas, y lectura de 25 endpoints.
3. **Motores Python puros**, importados desde la copia: `twr.dietz`, `twr.leg_dudoso`, `twr.clasificar_serie`, `snapshots_job.compute_broker_value_usd`, `snapshots_job._trust_mkt_value`, `snapshots_job.apply_last_known_prices`, `main._rollover_to_current_month`.
4. **Verificación de citas**: todas las líneas que cito las abrí con `sed -n` sobre `/tmp/rendi-main`. Las del mapa que uso las re-verifiqué una por una (ver sección "Citas del mapa").

**Qué NO pude ejecutar.**

- **Nada del frontend por encima de `utils/`.** Los `.jsx` (Dashboard, Positions, Insights) los leí y cité, pero no los rendericé: no monté React. Todo lo que digo de "qué ve el usuario" en esas pantallas es **ESTRUCTURAL** (la línea existe / falta), no medido.
- **El cron real (`run_daily_snapshots`)** contra una base con datos de producción: no tengo la base. Medí `take_snapshot_for_user` por partes (el guard de cobertura y `compute_broker_value_usd`), no la corrida completa.
- **La frecuencia real de cada caso borde en producción.** No hay copia de la base en este entorno. Cuando digo "cuántos usuarios", es cita de un comentario del propio código que ya trae la medición, y lo marco como tal.
- **`/api/prices` con más de 60 símbolos contra las fuentes reales**: el truncado lo verifiqué leyendo el código (`sym_list[:MAX_SYMBOLS]`), no disparando 61 tickers a data912/yfinance.

**Ambiente.** macOS, Python 3.9.6, Node v24.13.1. Red disponible (los tests de `/api/dolar` trajeron cotizaciones vivas). Todo el scratch en `/tmp/borde-1b/`.

---

## Preguntas que necesito que contestes

De las 49 pre-filtradas, **estas cinco me bloquean para cerrar un veredicto**. Las demás no las necesito.

1. **P-236** — El hero del Dashboard publica `0,00 %` cuando el aportado neto es ≤ 0, mientras `evolution.js` (mismo repo, mismo concepto) devuelve `null` con un comentario que dice literalmente que *un cero falso es peor que un vacío*. **¿El hero tiene que mostrar `—` cuando `netDeposited ≤ 0`?** Si la respuesta es sí, el fix es una línea y cambia lo que ven los 192 usuarios con `net_deposited` negativo que el propio código cuenta. Si es no, quiero saber por qué el criterio difiere entre las dos pantallas.

2. **P-288** — Hoy un activo **delistado** (o cualquier ticker cuya fuente dejó de publicar) se sigue valuando con su último precio conocido **sin límite de edad**: `read_last_prices` no mira `updated_at`, y esa posición **cuenta como "con precio" para el guard de cobertura del 95 %** que decide si el snapshot nocturno se escribe. **¿Querés un TTL (los 48 h que ya usa `register_trade`), o preferís que se congele para siempre y sólo se avise?** No puedo decidirlo yo: congelar un precio es a veces lo correcto (un bono que no cotizó hoy) y a veces es lo peor posible (una empresa que dejó de existir).

3. **Fecha futura — dónde tiene que estar el corte.** Hoy el guard existe en **un solo** endpoint (`/api/bonds/cashflow`, `main.py:10384`) y en el registro por chat (`main.py:23912`). `POST /api/positions`, `POST /api/operations`, `POST /api/positions/sell`, `POST /api/futures` y `POST /api/plazos-fijos` **aceptan 2030 sin decir nada** (medido). **¿La regla "una fecha futura no es un dato, es una estimación" vale para todas las escrituras, o hay alguna donde la fecha futura sea legítima?** (Sospecho que `plazos_fijos.fecha_inicio` sí lo es —un PF contratado que arranca la semana que viene— y que el resto no.)

4. **P-290 / cartera grande** — `/api/prices` trunca a 60 símbolos **en silencio** y **ninguno de los 12+ call sites del frontend chunkea**. El workaround existe sólo del lado asesor, y su comentario dice exactamente por qué (`main.py:37264-37268`). **¿Hay usuarios retail con más de 60 símbolos distintos hoy?** Si los hay, están viendo parte de la cartera al costo sin ningún cartel.

5. **Venta con la moneda equivocada** — Medí que vender un lote en pesos declarando la venta en USD produce `pnl_usd = +19.989,40` y `pnl_pct = +188.566,67 %` sobre un lote cuyo costo entero es US$106. El comentario del código dice que una venta en USD *"se RECHAZA si no alcanzan"* los lotes USD, pero la línea siguiente cae a **todos** los lotes cuando no hay ninguno de esa moneda (`main.py:11202`). **¿Ese fallback es la red de seguridad que querías (data legacy con `currency` NULL) o quedó cubriendo también el caso "el usuario eligió mal la moneda"?** De la respuesta depende si esto es un bug de una línea o un rediseño.

---

## Resumen ejecutivo

**Lo primero, porque es lo que cambia el orden de prioridades:** el sistema está **mucho mejor defendido de lo que esperaba en los bordes "obvios"** y **mucho peor en los bordes "de segundo orden"**.

- **Cartera vacía: impecable.** Medí 25 endpoints con un usuario recién creado: ninguno rompe, ninguno divide por cero, y los motores de rendimiento devuelven `null` con un `motivo` legible (`sin_historia`, `sin_mediciones`, `una_sola_medicion`). Las seis funciones de composición (`assetClass`, `assetSector`, `bookComposition`, `profileAllocations`, `insightsModel` ×2) tienen todas su guard `total <= 0 → []`. **No hay hallazgo acá.** Es el caso mejor cubierto de los nueve.
- **Cantidades y montos negativos en la entrada: bien cerrado.** `quantity=-5` e `invested=-1000` los rechaza Pydantic con 422 (medido).
- **Primer día / sin snapshot previo: bien cerrado.** Con un solo snapshot el motor devuelve `twr=null, motivo='sin_mediciones'`; con dos, `'una_sola_medicion'`. `computeReturnDelta` devuelve `null` con base ≤ 0 o con una sola fila apta (medido). Es el ejemplo de cómo debería verse todo lo demás.

**Y ahora lo que sí duele.** Los tres 🔴:

1. **El guard anti-distorsión confía en el peor valor posible: el cero.** `trustMktValue` / `_trust_mkt_value` arrancan con `if !(mktValue > 0) return True`. Un precio de `0,0001` se rechaza (múltiplo fuera de la banda) pero un precio de **exactamente 0 se acepta** y la posición vale 0, con P&L −100 %. Un precio **negativo** también se acepta y la posición vale **menos que nada**. Medido en los DOS motores. Y tiene una vía de entrada real: `pricing/fci.py:284` acepta `vcp = 0` porque sólo chequea `isinstance(vcp, (int, float))` — y `0` es un `int`.
2. **La fecha futura sigue abierta en casi todas las escrituras, y encima congela el calendario mensual.** Medido: `POST /api/operations` con `date=2030-06-15` y `pnl_usd=50000` entra con 200, escribe `monthly_entries` en 2030-06 con `capital_final = 51.200`, y a partir de ahí **`_rollover_to_current_month` devuelve 0 filas creadas para siempre** (`main.py:11468`: *"Ya tiene row del current month (o futura)"*). O sea: una sola operación mal fechada deja al usuario sin la fila del mes en curso —la que `sync-unrealized` necesita— hasta 2030. El incidente de los cupones de AL35 se arregló en el endpoint de cupones, no en la causa.
3. **La venta no tiene ninguna cota de plausibilidad.** El valor NO realizado está protegido por una banda de ×50; el REALIZADO no tiene absolutamente nada. Medido: `+188.566,67 %` en una sola fila de `operations`.

Los tres 🟠 que siguen tienen todos la misma forma: **un guard que existe, aplicado a un solo call site de varios.**
- `POST /api/monthly` valida que el broker exista; `POST /api/positions` y `POST /api/operations` no → medí una **pérdida fantasma de −US$9.999** (aportado 10.999 vs. valuación 1.000).
- `SellIn`, `OperationIn` y `MonthlyIn` aplican `_FINITE_BOUND = 1e12`; `PositionIn` **no** → medí una posición de `invested = 1e308` aceptada, propagada a `monthly_entries.capital_final` y devuelta por `compute_broker_value_usd`.
- `register_trade` rechaza un last-known de más de 48 h; `read_last_prices` (que alimenta el snapshot nocturno, el Dashboard y el libro del asesor) **no mira la edad** → medí que un precio con `updated_at = 2019-01-01` se sirve igual.

**Total: 3 🔴, 5 🟠, 6 🟡, 3 ⚪.**

---

## Matriz de casos borde

| caso | qué hace hoy | evidencia | qué debería hacer | qué ve el usuario | severidad |
|---|---|---|---|---|---|
| **1. Cartera vacía** — 25 endpoints con usuario nuevo | Todos 200. `twr=null`, `motivo='sin_historia'`, `cards:[]`, `[]`. Ninguna división por cero. | **MEDIDO** (`e1.py`, `e2.py`) | lo que hace | Estados vacíos correctos | — sin hallazgo |
| **1b.** Composición (6 funciones de torta) | Las 6 tienen `if (total <= 0) return []` / `return null` | **MEDIDO** (`t3.mjs`) | lo que hace | — | — sin hallazgo |
| **2. Precio = 0 del feed** | `trustMktValue(0, cost) = true` → **valor 0**, P&L −100 % | **MEDIDO**, ambos motores | Un 0 es "no hay dato", no "vale cero": caer a costo o marcar sin precio | La posición desaparece del total y la fila dice −100 % | 🔴 |
| **2b. Precio negativo** | `trustMktValue(-500, 1000) = true` → **valor −100 USD** | **MEDIDO** | Rechazar: un activo no puede valer menos que nada | Cartera con una fila en negativo | 🔴 |
| **2c. `vcp = 0` de ArgentinaDatos** | `refresh_prices` sólo chequea `isinstance(vcp,(int,float))` → escribe `price = 0.0` | **ESTRUCTURAL** (`pricing/fci.py:284-287`) | `if not (vcp > 0): missing` | El FCI vale 0 y la torta lo saca | 🔴 (es la vía de entrada de 2/2b) |
| **2d.** Denominadores en `%` (P&L, composición, consistencia) | Todos guardados: `investedUsd > 0 ? ... : null`, `total <= 0 → []`, `denom <= 0 → None` | **MEDIDO** | lo que hace | — | — sin hallazgo |
| **2e. `sumRowUSDT` / `sumRowARS` con costo 0** | `pnlPct = 0` (no `null`) con `pnl = 500` | **MEDIDO** | `null` → `—`. Es el criterio que `evolution.js:356` documenta | Fila que dice "+US$500 · 0,00 %" | 🟡 |
| **2f. MEP = 0 / null** | Frontend → `Infinity` en valor y costo, `NaN` en P&L. Backend → **0** | **MEDIDO** (`t2.mjs`, `snapshots_job.py:222`) | Los dos motores igual, y ninguno debería publicar | Cron: fail-closed ✅. Dashboard: `Infinity` | 🟡 (el cron está protegido) |
| **3. Venta > tenencia** | Manual: 400 atómico ✅. Import: sintetiza lote semilla. Ya dictaminado por 1A | **cita 1A** + `main.py:11206`, `importing/validator.py:11` | — | — | (ver 1A) |
| **3b. Venta con moneda ≠ la del lote** | Cae a **todos** los lotes y no convierte el `exit_price` → `pnl_usd = +19.989,40`, `pnl_pct = +188.566,67 %` sobre un lote de US$106 | **MEDIDO** (`e11.py`) | Cota de plausibilidad sobre el realizado (el no-realizado ya tiene ×50), o rechazar | "P&L realizado" +US$19.989 en una cartera de US$100 | 🔴 |
| **3c. Venta con `exit_price = 0`** | Aceptada, `pnl_pct = −100 %` | **MEDIDO** | Probablemente correcto (baja de un delistado) | Pérdida del 100 % de ese lote | ⚪ decisión defendible |
| **4. Fecha futura** — 7 escrituras probadas | 5 de 7 la aceptan con 200: positions, operations, sell, futures, plazos-fijos. Sólo `/api/bonds/cashflow` rechaza | **MEDIDO** (`e3.py`) | La misma regla del cupón en todas las escrituras | Nada. 200 y silencio | 🔴 |
| **4b.** Efecto de una fila mensual futura | `_rollover_to_current_month` → **0 filas creadas**, para siempre | **MEDIDO** (`e9.py`) + `main.py:11468` | Ignorar filas futuras al elegir la última | El mes en curso deja de existir; `sync-unrealized` no-opea en silencio | 🔴 |
| **4c.** FX de una fecha futura | `fx_for_date` devuelve la fila **más nueva que exista** (el dólar de hoy), sin avisar | **ESTRUCTURAL** (`fx.py:60-64`) — cita del mapa verificada | `None`, como con una fecha pre-serie | Un cupón de 2027 sellado con el MEP de hoy | 🟠 |
| **5. Activo sin precio** | Cae a costo, P&L 0, fila muestra `—`. No se excluye del total | **MEDIDO** + mapa 14.5 verificado | lo que hace | Total anclado al costo, Var. día 0 | — decisión documentada |
| **5b. Activo delistado / fuente muerta** | Último precio conocido **sin límite de edad**; medí que sirve un precio de 2019 | **MEDIDO** (`e8.py`) + `snapshots_job.py:589` | TTL (los 48 h de `register_trade`) o al menos `as_of` en `__meta` | Nada: el número parece de hoy | 🟠 |
| **5c.** El precio congelado **cuenta para la cobertura del 95 %** | `apply_last_known_prices` corre **antes** del guard (`snapshots_job.py:697` vs `:734`) | **ESTRUCTURAL**, verificado | Un precio congelado no es cobertura | Snapshot escrito con un activo muerto valuado a su precio final | 🟠 |
| **5d.** El aviso de precio viejo existe en **una sola pantalla** | `StalePricesNotice` sólo en `Positions.jsx:2002` | **ESTRUCTURAL** | Dashboard, Insights, Reportes y los packets de IA leen los mismos precios | En `/cartera` avisa; en el resto no | 🟡 |
| **6. Splits** | `quantity *= F`, `buy_price /= F`, `invested` intacto, idempotente por watermark, `F > 0` filtrado, atómico | **ESTRUCTURAL**, leído entero | lo que hace | — | — bien resuelto |
| **6b.** El histórico no se ajusta por el split | Documentado como deliberado ("no borra snapshots históricos") | **ESTRUCTURAL** (`main.py:8893`) | — | Un escalón de un día en la curva | ⚪ decisión documentada |
| **6c. Cambio de ticker** | Cascadea a `positions`, `import_normalized_tx`, `operations`. **NO** a `snapshots.holdings_json` ni a `asset_last_price` | **ESTRUCTURAL** (`main.py:8431-8447`) | Al menos `holdings_json`: es la atribución MtM histórica | Los movers de Reportes siguen mostrando el ticker viejo | 🟡 |
| **6d. Split + precio congelado** | La cantidad queda en escala nueva y el last-known en escala vieja | **DEDUCIDO** (composición de 5b + 6) | Invalidar el last-known al aplicar un split | Valor ×F o ÷F sin aviso | 🟡 |
| **7. Cantidad / monto negativo (alta)** | 422 de Pydantic (`ge=0`) | **MEDIDO** | lo que hace | Error claro | — sin hallazgo |
| **7b. Aportado neto negativo** | Hero del Dashboard publica **`0,00 %`** junto a un monto real en dólares | **ESTRUCTURAL** (`Dashboard.jsx:266` + `:823`) | `—`. El mismo archivo ya lo hace bien en `:668` | "Ganancia total +US$2.026,35 · 0,00 %" | 🟠 |
| **7c. Montos sin techo en `PositionIn`** | `invested = 1e308` y `quantity = 1e308` aceptados; `_FINITE_BOUND=1e12` no se aplica acá | **MEDIDO** (`e7.py`) | `le=_FINITE_BOUND` como en `SellIn`/`OperationIn`/`MonthlyIn` | `capital_final = 1e+308` en la base | 🟠 |
| **8. Primer día / sin snapshot previo** | `twr=null` + `motivo` legible; `computeReturnDelta` → `null` | **MEDIDO** (`e8.py`, `t3.mjs`) | lo que hace | "Todavía no hay historia de esta cuenta" | — sin hallazgo |
| **8b. Fuera de rueda (`pct = 0`)** | `previo = actual` → todas las filas `.BA` muestran `+0,00 %` | **ESTRUCTURAL** (`main.py:7917`) | `—` | "+0,00 %", que se lee como "no se movió" | 🟡 (P-153) |
| **9. Broker inexistente** | `POST /api/positions` y `POST /api/operations` lo aceptan; `POST /api/monthly` lo rechaza | **MEDIDO** (`e4.py`) | El mismo guard en las tres | Nada. La plata desaparece del total y queda en el aportado | 🟠 |
| **9b.** Efecto medido de 9 | Aportado 10.999 vs. valuación 1.000 → **−US$9.999** de pérdida fantasma | **MEDIDO** (`e5.py`) | — | Pérdida permanente que no se explica con nada | 🟠 |
| **9c. `broker="   "` / `asset="   "`** | Pasan `min_length=1` (corre antes del `.strip()`) y se guardan como `""` | **MEDIDO** (`e4.py`, `e6.py`) | Validador `mode='before'` o `min_length` sobre el valor limpio | Un broker sin nombre en `monthly_entries` | 🟡 |
| **9d. `quantity` / `invested` NULL** | Aceptados; el motor los lee como 0 (`p.invested \|\| 0`) | **MEDIDO** | lo que hace (el `\|\| 0` es correcto) | Fila a cero | ⚪ |
| **9e. `currency=""` / `"XYZ"`** | Se normaliza a `None` y el backend infiere del broker | **MEDIDO** | lo que hace | — | — sin hallazgo |
| **9f. Cartera > 60 símbolos** | `/api/prices` trunca en silencio; ningún call site del frontend chunkea | **ESTRUCTURAL** (`main.py:7139`, `:7637`) | Chunkear en el cliente | Parte de la cartera al costo, sin ningún cartel | 🟠 |
| **9g. `computeBrokerValue(undefined)`** | `TypeError` sin capturar | **MEDIDO** | Guard de una línea | Pantalla en blanco si el fetch falla raro | ⚪ |
| **9h. Rename de broker** | **Sí cascadea** a positions, operations y monthly | **MEDIDO** (`e6.py`) | lo que hace | — | — sin hallazgo |
| **9i. Delete de broker con datos** | 409 con `code: broker_has_data` y el conteo por tabla | **MEDIDO** (`e7.py`) | lo que hace | Error claro | — sin hallazgo |

---

## Detalle por caso

### 1. Cartera vacía — sin hallazgo, y vale decirlo

Usuario recién insertado (`approved=1`), sin brokers ni posiciones. 25 endpoints, todos 200 (los 404 de la primera pasada eran rutas que yo inventé mal; los corregí contra `app.routes`).

```
/api/positions                 200  []
/api/brokers                   200  []
/api/monthly                   200  []
/api/snapshots                 200  []
/api/goals                     200  []
/api/movements                 200  []
/api/fx-rates                  200  []
/api/plazos-fijos              200  []
/api/futures                   200  []
/api/home/personal             200  {"cards":[]}
/api/home/heatmap              200  {"market":"sp500","label":"S&P 500","blocks":[]}
/api/events/portfolio          200  {"events":[],"refreshed_tickers":0}
/api/insights/commissions      200  {"total_usd":0.0,"count":0,"taxes_usd":0.0,"taxes_count":0}
/api/insights/performance      200  {"curva":[],"twr":null,"cagr":null,"cobertura":0.0,
                                     "motivo":"sin_historia","motivo_texto":"Todavía no …"}
/api/goals/cagr                200  {"total_return_pct":null,"cagr":null,
                                     "reason":"Todavía no hay historia de esta cuenta."}
/api/behavioral/insights       200  {"cards":[{"code":"disposition_effect",
                                     "title":"Datos insuficientes","insufficient_data":true, …}]}
/api/reports/timeline          200  {…"delta_pct":null,"headline":"Mes sin grandes movimientos."}
```

Y las funciones de composición del frontend, corridas con lista vacía:

```
computeReturnDelta([])              -> null
computeMonthlyConsistency([])       -> null
computeBrokerConcentration([])      -> null
computeAssetTypeBreakdown([],[])    -> []
computeAllocationBuckets([],[])     -> {"cash":0,"fixed_income":0,"equity":0,"alternative":0,"totalUsd":0}
computeBrokerValue([], …)           -> {"value":0,"invested":0,"valueArs":0,"invArs":0,"pnlUsd":0,"pnlArs":0}
buildPriceSymbols([],[])            -> []
buildPriceSymbols(null,null)        -> []
```

Los seis guards verificados con `grep -n`, todos con la misma forma:

- `frontend/src/utils/assetClass.js:317` — `if (total <= 0) { return { items: [], total: 0, unclassified: {…} } }`
- `frontend/src/utils/bookComposition.js:93` — idéntico
- `frontend/src/utils/assetSector.js` — idéntico
- `frontend/src/utils/profileAllocations.js:324` — `if (total === 0) { return { cash: 0, … } }`
- `frontend/src/utils/insightsModel.js:418` — `if (total === 0) return null`
- `frontend/src/utils/insightsModel.js:487` — `if (total === 0) return []`

**Único detalle menor:** `/api/config` de un usuario nuevo devuelve `{"tc_mep":1415,"tc_blue":1415}` — el default hardcodeado — mientras el MEP vivo del mismo momento era 1.533,7 (`/api/dolar`, misma corrida). No es un bug por sí solo (el frontend usa `/api/dolar`), pero es el mismo 1415 hardcodeado que 1A reportó en A-6, y confirma que el default sigue vivo en el camino de configuración.

---

### 2. 🔴 El guard anti-distorsión confía en el cero (y en los negativos)

**La cita, verificada literal** — `frontend/src/utils/valuation.js:448-449`:

```js
export function trustMktValue(mktValue, realCost, assetType, hasOverride = false) {
  if (!(realCost > 0) || !(mktValue > 0)) return true  // sin costo no hay con qué comparar
```

El espejo, `backend/snapshots_job.py:48-49`:

```python
    if not (real_cost and real_cost > 0) or not (mkt_value and mkt_value > 0):
        return True  # sin costo no hay con qué comparar
```

El comentario justifica **una** de las dos condiciones ("sin costo no hay con qué comparar" — correcto: si `realCost = 0` no hay múltiplo que calcular). Pero la condición está pegada con un `or` a `!(mktValue > 0)`, y ahí el razonamiento no aplica: **si el valor de mercado es 0 o negativo, sí hay con qué comparar, y el resultado es que el múltiplo es absurdo.** El guard existe justamente para rechazar múltiplos absurdos, y éste es el único que deja pasar.

**Traza de ejecución** (`node --import ./hook.mjs t1.mjs`):

```
=== trustMktValue con entradas degeneradas ===
  trustMktValue(mkt=0, cost=1000) = true
  trustMktValue(mkt=-500, cost=1000) = true
  trustMktValue(mkt=1000, cost=0) = true
  trustMktValue(mkt=1000, cost=-1000) = true
  trustMktValue(mkt=0, cost=0) = true
  trustMktValue(mkt=NaN, cost=1000) = true
  trustMktValue(mkt=1000, cost=NaN) = true

=== valuePositionLot: precio 0 en el feed (broker USD, accion US) ===
precio 150 (normal)     {"valueUsd":1500,"investedUsd":1000,"priceTrusted":true,"pnlUsd":500,"pnlPct":0.5}
precio 0 en el feed     {"valueUsd":0,   "investedUsd":1000,"priceTrusted":true,"pnlUsd":-1000,"pnlPct":-1}
precio null (ausente)   {"valueUsd":1000,"investedUsd":1000,"priceTrusted":null,"pnlUsd":0,   "pnlPct":0}
precio negativo -10     {"valueUsd":-100,"investedUsd":1000,"priceTrusted":true,"pnlUsd":-1100,"pnlPct":-1.1}
precio NaN              {"valueUsd":null,"investedUsd":1000,"priceTrusted":true,"pnlUsd":null,"pnlPct":null}
```

Y el mismo comportamiento en el motor del snapshot (`python3 e8.py`):

```
=== PRECIO 0 / OVERRIDE 0 (motor backend) ===
  precio 150 (normal)      -> {'value': 1500.0, 'invested': 1000.0}
  precio 0 en el feed      -> {'value': 0.0,    'invested': 1000.0}
  precio -10 en el feed    -> {'value': -100.0, 'invested': 1000.0}
  sin precio               -> {'value': 1000.0, 'invested': 1000.0}
  price_override=0         -> {'value': 0.0,    'invested': 1000.0}
  _trust_mkt_value(0, 1000, 'ACCION') = True
  _trust_mkt_value(-500, 1000, 'ACCION') = True
```

**La asimetría que lo delata:** un precio de `0,0001` da múltiplo `1e-7`, cae fuera de `[0.002, 50]` y **se rechaza** → la posición va a costo. Un precio de `0` da valor 0 y **se acepta**. El guard es más estricto con un precio casi-cero que con el cero exacto.

**Nota justa sobre `price_override = 0`:** ese caso lo dictaminó 1A y es deliberado — hay un `is not None` explícito con comentario (`snapshots_job.py:273-275`) para que un override de cero no caiga al precio de mercado. Lo dejo fuera del hallazgo. Lo que reporto es el precio **del feed**.

#### 2c. Por dónde entra un cero: `pricing/fci.py`

`backend/pricing/fci.py:281-287` (verificado, y **verificado también contra `origin/main` = `82fad6a0`: el fix de Ualá no toca esta función**):

```python
            f = idx.get((row["ad_name"] or "").strip().lower())
            vcp = f.get("vcp") if f else None
            if not isinstance(vcp, (int, float)):
                missing.append(row["symbol"])
                continue
            price = round(vcp / 1000.0, 6)
```

`isinstance(0, (int, float))` es `True`. Un `vcp` de `0` —o negativo— pasa el filtro, se escribe en `fci_prices.price` como `0.0`, y `get_prices_detail_for` (`:337-338`) sólo filtra `price is not None`. `/api/prices` lo devuelve, `trustMktValue(0, cost)` dice `true`, y el FCI vale cero.

Comparalo con los otros tres proveedores de precio, que **sí** filtran:

| fuente | guard | cita |
|---|---|---|
| yfinance | `if not math.isnan(val) and val > 0:` | `main.py:7784` |
| data912 acciones | `return px if px and px > 0 else None` | `main.py:7326` |
| data912 bonos | `if raw is None or raw <= 0: return None` | `main.py:7347` |
| **FCI** | **`isinstance(vcp, (int, float))` — nada más** | `pricing/fci.py:284` |

Tres de cuatro tienen el guard. Es el patrón de "guard en un solo call site", con el agujero justo en la fuente que ya se cayó tres semanas seguidas en 2026 (lo dice el docstring de `get_prices_detail_for`).

---

### 3b. 🔴 La venta no tiene cota de plausibilidad

**Traza** (`python3 e11.py`). Lote: 100 GGAL en Cocos (broker ARS), `invested = ARS 150.000`, `currency='ARS'`. O sea: US$106 al MEP del día.

```
VENTA CON MONEDA QUE NO ES LA DEL LOTE (lote ARS, venta declarada USD):
  -> 200 {"ok":true,"operations":[{"id":11,…,"exit_price":2000.0,"quantity":10.0,
          "pnl_usd":19989.4,"pnl_pct":188566.6667,…}]}
  positions:  [('GGAL', 80.0, 120000.0, 'ARS'), ('ARS', None, 20000.0, None)]
  operations: [('GGAL', 10.0, 2000.0, 19989.4, 188566.6667), …]
```

**Qué pasó, línea por línea.** `main.py:11199-11203`:

```python
                _same_ccy = [p for p in all_positions if _native_ccy(dict(p)) == sell_ccy]
                positions = _same_ccy if _same_ccy else all_positions
```

El comentario inmediatamente anterior (`:11195-11198`) dice:

> *"Venta MANUAL: respeta la moneda explícita del user. […] una venta en USD consume SOLO lotes USD y se **RECHAZA si no alcanzan** — NO hace spill a los lotes ARS"*

**El código hace lo contrario cuando no hay NINGÚN lote de esa moneda.** `_same_ccy` queda vacío → `positions = all_positions` → consume el lote ARS. La justificación está una línea más abajo (*"Fallback a todos solo si NO hay lotes de esa moneda (data legacy NULL)"*), así que es deliberado; el problema es lo que pasa después.

La conversión cross-currency del **costo** sí existe y funciona (`main.py:11245-11247`): `base_invested = base_invested / purchase_blue` → US$106 para el lote entero, US$10,60 para el chunk de 10. Pero el **`exit_price` no se convierte nunca**: la rama `else` de `:11296-11299` hace

```python
                        cost = entry_invested if entry_invested is not None else ((buy_price or 0) * take)
                        pnl_usd = (data.exit_price * take) - cost - chunk_commission_native
```

`2000 × 10 = 20.000` se toma como dólares. `20.000 − 10,60 = 19.989,40`.

**Por qué esto es un hallazgo y no "el usuario se equivocó":** el sistema **ya tiene** el concepto de cota de plausibilidad para exactamente este problema, y lo aplica al valor NO realizado (`trustMktValue`, banda `[0.002×, 50×]`) con un comentario que cuenta el caso real que lo motivó (una ON con precio manual en convención per-100 → +9775 %). El **P&L realizado**, que es plata que entra a `monthly_entries`, a la curva y a los packets de IA, **no tiene ninguna**. `pnl_pct = 188.566,67` se escribe sin más; ni siquiera lo alcanza el `le=1e6` de `OperationIn.pnl_pct`, porque este INSERT no pasa por el modelo.

Esto es el mismo hilo que el ítem abierto de tu memoria (*"entry_price en ventas cruzadas — entry y exit en monedas distintas en la misma fila"*). Lo que agrego es la **magnitud medida** y la observación de que la asimetría con `trustMktValue` es la que da la forma del fix.

---

### 4. 🔴 Fecha futura: el guard está en un endpoint de siete

**El guard que sí existe**, `backend/main.py:10377-10387` (verificado literal):

```python
        # Un cobro se registra cuando se COBRÓ: una fecha futura no es un dato, es una
        # estimación. Medido en producción (usuario 3, 2026-08): el modal pre-llenaba la
        # fecha con el PRÓXIMO pago del cronograma (09/01/2027) y el usuario cargó 25
        # cupones de AL35 con esa fecha, en pesos y sin TC sellado […] → +US$3,9M de
        # "P&L realizado", un mes 2027 en monthly_entries y el Dashboard con +US$500k.
        # Se rechaza acá y no solo en el frontend […]
        if data.date[:10] > date.today().isoformat():
            raise HTTPException(400, …)
```

La lección está bien escrita: *"Se rechaza acá y no solo en el frontend: el chat de la IA y cualquier cliente viejo pasan por este endpoint."* **Pero se aplicó sólo a este endpoint.**

**Traza** (`python3 e3.py`, hoy = 2026-09-07, fecha usada = 2030-06-15):

```
POST /api/positions   entry_date=2030-06-15        200  {"id":2,…,"entry_date":"2030-06-15",…}
POST /api/operations  date=2030-06-15              200  {"id":1,…,"pnl_usd":50000.0,…}
POST /api/positions/sell date=2030-06-15           200  {"ok":true,…,"pnl_usd":200.0,…}
POST /api/plazos-fijos fecha_inicio=2030-06-15     200  {"ok":true,"fecha_vencimiento":"2030-07-15"}
POST /api/futures     opened_at=2030-06-15         200  {…,"opened_at":"2030-06-15",…}
POST /api/bonds/cashflow date=2030-06-15           (rechazado por el guard de :10384)

--- ¿qué quedó en la base? ---
positions:        {'entry_date': '2030-06-15', 'asset': 'AAPL', 'quantity': 9.0, 'invested': 900.0}
operations:       {'date': '2030-06-15', 'asset': 'MSFT', 'op_type': 'Venta', 'pnl_usd': 50000.0}
                  {'date': '2030-06-15', 'asset': 'AAPL', 'op_type': 'Venta', 'pnl_usd': 200.0}
monthly_entries:  {'year': 2030, 'month': 6, 'broker': 'IBKR',   'deposits': 1000.0,
                   'pnl_realized': 50200.0, 'capital_final': 51200.0}
                  {'year': 2030, 'month': 6, 'broker': 'global', 'deposits': 1000.0,
                   'pnl_realized': 50200.0, 'capital_final': 51200.0}
```

Los cinco modelos, verificados: **ninguno** valida el tope superior de la fecha.

| modelo | línea | validador de fecha |
|---|---|---|
| `PositionIn.entry_date` | `main.py:8156-8163` | sólo `_DATE_RE` |
| `CashFlowIn.date` | `main.py:9400-9406` | sólo `_DATE_RE` |
| `ConversionIn.date` | `main.py:10272-10278` | sólo `_DATE_RE` |
| `SellIn.date` | `main.py:11137-11143` | sólo `_DATE_RE` |
| `OperationIn.date` | `main.py:12099-12104` | sólo `_DATE_RE` |
| `FuturoIn.opened_at` | `main.py:12159-12163` | sólo `_DATE_RE` |
| `MonthlyIn.year` | `main.py:11416` | `ge=2000, le=2100` |

(La cita del mapa en 9596 — *"`entry_date` solo se valida contra `_DATE_RE`: no hay tope superior"* — es **correcta**. Lo que agrego es que son siete escrituras, no una, y el efecto de 4b.)

#### 4b. 🔴 Una fila mensual futura congela el rollover para siempre

`backend/main.py:11466-11468` (verificado literal):

```python
    last_year, last_month = int(last["year"]), int(last["month"])
    if (last_year, last_month) >= (target_year, target_month):
        return 0  # Ya tiene row del current month (o futura)
```

El paréntesis *"(o futura)"* dice que el autor vio el caso. Lo que la línea hace con él es salir sin crear nada.

**Traza** (`python3 e9.py`):

```
=== ROLLOVER MENSUAL vs UNA FILA FUTURA ===
  antes: [(2026, 8, 'IBKR'), (2026, 8, 'global')]
  _rollover_to_current_month -> creo 1 filas ; [(2026, 8), (2026, 9)]

  ahora cargamos UNA operacion con fecha 2030-06-15 …
  filas: [(2026, 8), (2030, 6)]
  _rollover_to_current_month (con la fila 2030 presente) -> creo 0 filas
  filas finales: [(2026, 8), (2030, 6)]
```

**Qué se rompe río abajo**, según el docstring del propio endpoint que la necesita (`main.py:11039-11046`, verificado literal):

> *"Si no existe entrada para el mes calendario actual → **no-op silencioso**."*

y el de `_rollover_to_current_month` (`main.py:11443-11448`):

> *"Si el user dejaba de visitar la página varios meses, las métricas del current month no existían — `sync-unrealized` no-opeaba silenciosamente, el chart de evolución mostraba data stale, etc."*

O sea: **el modo de falla que el rollover vino a arreglar vuelve entero** en cuanto hay una fila futura. Y no hace falta un cupón de 2027: alcanza con una venta mal tipeada.

---

### 5. 🟠 Delistado: el precio se congela sin edad, y encima cuenta como cobertura

**Traza** (`python3 e8.py`):

```
=== ULTIMO PRECIO CONOCIDO: ¿tiene edad? ===
  asset_last_price fila: {'symbol': 'ZZDEAD', 'price': 42.0, 'updated_at': '2019-01-01T00:00:00'}
  apply_last_known_prices({'ZZDEAD': None}) -> {'ZZDEAD': 42.0}   (updated_at 2019, sin filtro de edad)
```

`backend/snapshots_job.py:589-600` (verificado literal) — la columna existe y no se lee:

```python
def read_last_prices(conn, symbols: list) -> dict:
    """Devuelve {symbol: price} para los símbolos con último precio guardado."""
    …
        rows = conn.execute(
            f"SELECT symbol, price FROM asset_last_price WHERE symbol IN ({placeholders})",
            tuple(syms),
        ).fetchall()
```

`persist_last_prices` (`:576-583`) **sí escribe `updated_at`**. Nadie lo lee de vuelta.

**Lo que agrego al hallazgo (esto no está en el mapa): el orden importa.** En `take_snapshot_for_user`:

- `snapshots_job.py:697` — `apply_last_known_prices(conn, prices)` ← rellena los huecos con precios congelados
- `snapshots_job.py:726-728` — `_has_price(p)` → `prices.get(position_price_key(...)) is not None`
- `snapshots_job.py:733-734` — `MIN_COVERAGE = 0.95`; `if non_cash and coverage < MIN_COVERAGE: return`

El relleno corre **antes** del guard. Entonces el guard —cuyo comentario dice *"Preferimos NO escribir ese día antes que escribir un dato corrupto"*— **ve 100 % de cobertura para una cartera cuyos precios pueden ser todos de hace un año.** El guard sólo mira si FALTA; y después del relleno nunca falta nada de lo que alguna vez tuvo precio.

**Lo que el sistema sí sabe hacer, en un solo lugar** — `main.py:23449-23456`, en el registro por chat:

```python
        if row and row["updated_at"]:
            _age = (datetime.utcnow()
                    - datetime.fromisoformat(str(row["updated_at"]).replace("Z", "")))
            if _age.total_seconds() > 48 * 3600:
                log.info("register_trade: precio de %s con last-known viejo (%s) → lo da el usuario", …)
                return None
```

Existe el criterio (48 h), existe el dato (`updated_at`), y se aplica en **un** call site de los cuatro que leen `asset_last_price`.

**Y del lado del usuario:** `/api/prices` **sí** marca `stale: true` en `__meta` cuando el precio salió del last-known (`main.py:7845-7855`, verificado) — pero **sin `as_of`**, porque el `updated_at` de la tabla nunca se lee. El usuario puede saber "esto es viejo" pero no "de cuándo". Y el aviso se muestra en **una sola pantalla**: `StalePricesNotice` aparece únicamente en `frontend/src/pages/Positions.jsx:2002` y `:2803`. Dashboard, Insights, Reportes, Home y los packets de IA leen los mismos precios sin decir nada.

---

### 6c. 🟡 Cambio de ticker: cascadea a tres tablas, no a la cuarta

`backend/main.py:8431-8447` (verificado). El rename actualiza:

1. `positions.asset` (por lote)
2. `import_normalized_tx.asset_symbol` (la fila de origen)
3. `operations.asset` — con un comentario que explica bien por qué: *"si no, quedan colgadas de un activo que ya no existe"*

**No toca `snapshots.holdings_json`**, que es la foto por activo de cada día y la base de la atribución MtM. Sus lectores, verificados con `grep -n`:

- `backend/main.py:11671` — `return {h["asset"]: h["value_usd"] for h in json.loads(sn["holdings_json"] or "[]")}`
- `backend/reporting/builder.py:360` — el `SELECT` de los movers del período
- `backend/reporting/schema.py:49` — *"Sale de diferenciar la foto por activo (`snapshots.holdings_json`)"*
- `backend/main.py:17844`, `:17946` — diagnósticos

Consecuencia: después de renombrar `SID` → `SI` (o cualquier cambio de especie), los movers de Reportes y la atribución histórica siguen hablando del ticker viejo, y el nuevo aparece "desde cero". Tampoco se toca `asset_last_price`, que está keyeada por símbolo: el ticker nuevo arranca sin last-known.

El razonamiento que justifica el fix es el mismo que el propio código ya escribió para `operations`.

---

### 7b. 🟠 El hero del Dashboard publica un 0,00 % que el resto del repo se niega a publicar

**Las dos líneas, en el mismo archivo.**

`frontend/src/pages/Dashboard.jsx:266`:

```js
  const totalReturnPct = netDeposited > 0 ? totalReturnUsd / netDeposited : 0
```

`frontend/src/pages/Dashboard.jsx:667-670` — el KPI por horizonte, **bien guardado**:

```js
  const totalVar = (totalValue > 0 && netDeposited > 0)
    ? { usd: totalReturnUsd, pct: totalReturnPct }
    : null
```

Y el render del hero, `Dashboard.jsx:820-824` — usa el de la línea 266, **sin el guard**:

```jsx
            <span>{totalReturnUsd >= 0 ? 'Ganancia total' : 'Pérdida total'}</span>
            <span>{hidden ? '••••••' : fmtSigned(totalReturnUsd)}</span>
            <span className="opacity-80">· {pctSigned(totalReturnPct)}</span>
```

O sea: la misma pantalla decide dos cosas distintas para el mismo número. El KPI dice "no lo sé"; el hero dice "0,00 %".

**Y el criterio correcto está escrito, con la medición, tres archivos más allá** — `frontend/src/utils/evolution.js:348-356` (verificado literal):

```js
  // ⚠️ `!prev.total_value` NO ALCANZA: deja pasar un `total_value` NEGATIVO
  // (truthy). Con base negativa, el `prevValue > 0 ? ... : 0` de más abajo cae al
  // CERO, y el resultado es lo peor de los dos mundos: un monto en dólares que se
  // publica junto a un "0,00%" que parece medido. Un cero falso es peor que un
  // vacío — el vacío se lee como "no lo sabemos" y el cero como "no se movió".
  // Medido en la copia del 16/08: 7 usuarios publicaban un monto contra 0,00%
  // (uid 1: +US$2.026,35 · 0,00% sobre una base de −11,92).
  // No hay porcentaje contra una base ≤ 0: no es 0, es indefinido.
  if (!prev || !(prev.total_value > 0)) return null
```

Traza que confirma que `evolution.js` sí lo respeta:

```
  base negativa   -> null
  base 0          -> null
  una sola fila   -> null
```

**Cuán frecuente es**: el propio repo trae la medición — `evolution.js:261-263`, *"Medido en la copia de producción del 16/08: 4.744 filas (11,7%) en 192 usuarios tienen `net_deposited < 0`"*. Es el caso de quien retiró más de lo que aportó, que es un dato perfectamente legítimo.

---

### 7c. 🟠 `PositionIn` es el único modelo sin techo, y es el que siembra la cadena

`backend/main.py:11096-11106` define el techo y el chequeo:

```python
_FINITE_BOUND = 1e12  # bound razonable para detectar inf/NaN/garbage

def _finite(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    if not math.isfinite(v):
        raise ValueError('Valor numérico inválido (NaN/Inf)')
    if abs(v) > _FINITE_BOUND:
        raise ValueError('Valor numérico fuera de rango')
    return v
```

Quién lo aplica y quién no:

| modelo | campos monetarios | `le=_FINITE_BOUND` |
|---|---|---|
| `SellIn` (`:11112-11116`) | quantity, exit_price, tc_venta, commissions | ✅ + `@field_validator … finite_check` |
| `OperationIn` (`:12067-12078`) | entry_price, exit_price, quantity, pnl_usd, commissions, fx_to_usd | ✅ |
| `MonthlyIn` (`:11419-11423`) | deposits, withdrawals, pnl_*, capital_* | ✅ + `finite_check` |
| `FuturoIn` (`:12142-12146`) | quantity, entry_price, margin_usd | ✅ |
| **`PositionIn` (`:8142-8147`)** | **buy_price, quantity, invested, price_override, commissions** | **❌ sólo `ge=0`** |

**Traza** (`python3 e7.py`):

```
=== MONTOS ENORMES (PositionIn no tiene tope superior) ===
  invested=1e308           -> 200 {"id":29,…,"quantity":1.0,"invested":1e+308,…}
  quantity=1e308           -> 200 {"id":31,…,"quantity":1e+308,"invested":1.0,…}
  invested=Infinity        -> EXC (rechazado por el serializador JSON, no por el modelo)
  positions: [('AAA', 1.0, 1e+308), ('USD', None, 0.0), ('BBB', 1e+308, 1.0)]
  monthly:   [('IBKR', 1e+308, 1e+308), ('global', 1e+308, 1e+308)]
  compute_broker_value_usd: {'value': 1e+308, 'invested': 1e+308}
  GET /api/positions -> 200
```

Notá el absurdo: `monthly_entries.capital_final = 1e+308` está en la base, pero si el usuario intentara escribir ese mismo número por `POST /api/monthly` lo rechazaría el `le=_FINITE_BOUND` de `MonthlyIn`. **El modelo que valida es el que no puede escribir; el que escribe no valida.** Y `PositionIn` es la puerta de entrada de toda la cadena: alta → auto-depósito → `monthly_entries` → `capital_final` → curva.

---

### 9. 🟠 Broker inexistente: el guard está en un writer de tres

**Traza** (`python3 e4.py`):

```
== POSICION EN UN BROKER QUE NO EXISTE ==
  POST /api/positions broker='BrokerFantasma' -> 200 {"id":5,…,"broker":"BrokerFantasma",…}
  POST /api/operations broker='BrokerFantasma' -> 200 {"id":3,…,"pnl_usd":7777.0,…}
  POST /api/monthly   broker='BrokerFantasma' -> 400 {"detail":"Broker 'BrokerFantasma' no existe.
                                                      Agregalo en Config primero."}
  POST /api/positions broker=''               -> 422 {"detail":[{"type":"string_too_short",…}]}
  POST /api/positions broker='   '            -> 200 {"id":7,…,"broker":"",…}

  brokers:   [{'name': 'IBKR', 'currency': 'USD'}]
  positions: [('IBKR','USD',…), ('BrokerFantasma','AAPL',10.0,9999.0,'USD'),
              ('BrokerFantasma','USDT',…), ('','AAPL',1.0,1.0,'USD'), ('','USDT',…)]
  monthly:   [(2026,1,'BrokerFantasma',0.0,7777.0,7777.0), (2026,1,'global',0.0,7777.0,7777.0),
              (2026,9,'BrokerFantasma',9999.0,0.0,17776.0), (2026,9,'global',10000.0,0.0,17777.0),
              (2026,9,'',1.0,0.0,1.0)]
```

**La magnitud, medida** (`python3 e5.py`): mismo usuario, un lote legítimo de US$1.000 en IBKR y uno de US$9.999 en un broker que no existe.

```
  brokers:   [('IBKR', 'USD')]
  positions: [('BrokerFantasma','AAPL',9999.0), ('BrokerFantasma','USDT',0.0),
              ('IBKR','MSFT',1000.0), ('IBKR','USD',0.0)]
  compute_broker_value_usd(IBKR) = {'value': 1000.0, 'invested': 1000.0}
  TOTAL valuado por el motor de snapshots: 1000.0
  monthly_entries global: [{'year':2026,'month':9,'broker':'global',
                            'deposits':10999.0,'capital_final':10999.0}]

  -> lo aportado que el sistema contabiliza: 10999.0
  -> lo que el motor de valuacion ve:        1000.0
  -> DIFERENCIA (perdida fantasma):          -9999.0
```

**Por qué desaparece de la valuación y no del aportado.** Los dos motores iteran los BROKERS y filtran las posiciones por nombre; una posición cuyo broker no está en la lista simplemente no se visita:

- Frontend, `valuation.js:741` — `const bpos = allPositions.filter(p => p.broker === broker.name)`
- Frontend, `valuation.js:490` — `buildPriceSymbols`: `if (p.is_cash || … || !known.has(p.broker)) continue`
- Backend, `snapshots_job.py:749-751` — `bpos = [p for p in positions if p['broker'] == b['name']]`

Pero el **auto-depósito** del alta (`_autodeposit_if_overdraw`, llamado desde `_insert_manual_position`, `main.py:8248`) escribe a `monthly_entries` **sin comprobar nada**, y ahí sí entra a `global`. De ahí la asimetría exacta.

**El guard que sí existe**, para comparar — `POST /api/monthly` devuelve `400 "Broker 'X' no existe. Agregalo en Config primero."` Y del lado del asesor el guard también existe, con el razonamiento escrito (`main.py:36906-36911`, verificado literal):

```python
            if bccy is None:
                # Posición huérfana (broker borrado/renombrado sin cascada):
                # defaultear a USD contaría un costo en pesos 1:1 como
                # dólares y fabricaría pérdidas gigantes. Mismo guard que
                # _valuate_positions_for_chat.
                skipped += 1
```

O sea: el problema está identificado y resuelto **tres veces** (monthly, valuación del asesor, valuación del chat) y **no está resuelto en el alta**, que es el único punto donde se podría impedir que la fila exista.

**Qué NO es este hallazgo, para ser justo.** Verifiqué que los dos vectores obvios están cerrados:
- **Rename de broker: cascadea bien.** `PUT /api/brokers/{bid}` → medido: positions, operations y monthly_entries quedan todos con el nombre nuevo.
- **Delete de broker con datos: bloqueado.** `DELETE` → `409 {"code":"broker_has_data","counts":{"positions":2,"operations":1,"monthly_entries":2}}`.

Así que el vector real es la API directa y los integradores (chat, imports, cualquier cliente viejo) — el mismo argumento que el comentario del guard de cupones ya usó para rechazar en el backend y no sólo en el frontend.

#### 9c. 🟡 `min_length=1` no ve el `.strip()`

`main.py:8138-8183`:

```python
class PositionIn(BaseModel):
    broker: str = Field(..., min_length=1, max_length=MAX_STR)
    asset: str = Field(..., min_length=1, max_length=MAX_STR)
    …
    @field_validator('asset')
    @classmethod
    def clean_asset(cls, v):
        return v.strip().upper()

    @field_validator('broker')
    @classmethod
    def clean_broker(cls, v):
        return v.strip()
```

En Pydantic v2 los `Field` constraints corren **antes** que un `@field_validator` en modo `after` (el default). Medido:

```
  POST /api/positions broker=''    -> 422 string_too_short
  POST /api/positions broker='   ' -> 200 broker guardado: ""
  POST /api/positions asset='   '  -> 200 asset  guardado: ""
```

Con lo cual quedan filas con `broker=''` y `asset=''` que ningún `min_length` iba a permitir. La de `broker=''` además abre una fila en `monthly_entries` con broker `''`. La de `asset=''`: `build_price_symbols` la devuelve vacía y el valor cae al costo para siempre —lo verifiqué—, así que es una posición que nunca se va a valuar.

Mismo patrón en `SellIn` (`:11128-11136`) y `OperationIn` (`:12107-12112`).

---

### 2f. 🟡 MEP degenerado: el frontend da `Infinity`, el backend da `0`

**Traza frontend** (`t2.mjs`), lote 100 GGAL en broker ARS, `invested = 150.000`:

```
MEP=0          valueUsd=Infinity  investedUsd=Infinity  pnlUsd=NaN  pnlPct=NaN  valueArs=200000
MEP=null       valueUsd=Infinity  investedUsd=Infinity  pnlUsd=NaN  pnlPct=NaN  valueArs=200000
MEP=undefined  valueUsd=NaN       investedUsd=NaN       pnlUsd=NaN  pnlPct=null valueArs=200000
CASH MEP=0     valueUsd=Infinity  investedUsd=Infinity
CASH MEP=null  valueUsd=Infinity  investedUsd=Infinity
```

**Backend**, `snapshots_job.py:222`, `:236`, `:261`, `:271`, `:278` — el mismo cálculo lleva un guard en cada rama:

```python
                cash_usd = cash_ars / cedear_rate if cedear_rate > 0 else 0
```

Los dos motores son "port fiel" uno del otro (lo dice el docstring de `compute_broker_value_usd`, `:166`) y acá divergen: mismo input, `Infinity` contra `0`.

**Cuán alcanzable es.** Del lado del cron, **no lo es**: `run_daily_snapshots` es fail-closed (`snapshots_job.py:947-949`, `"Blue rate inválido (…), abortando job"`). Del lado del Dashboard, el guard de cobertura tiene la rama (`Dashboard.jsx:445-446`: `if (hasArs && !(tcValuacion > 0)) return 0`) que impide **escribir el snapshot**, pero **no impide mostrar**: las filas ya se calcularon con `valuePositionLot`. Por eso lo dejo en 🟡 y no más arriba: el dato no se persiste, pero se muestra.

Nota: el guard del backend (`… if cedear_rate > 0 else 0`) es defensivo y correcto — **no lo reporto como parche**. Lo que reporto es que el frontend no lo tiene.

---

### 9f. 🟠 Más de 60 símbolos: se trunca en silencio y nadie chunkea

`backend/main.py:7139` — `MAX_SYMBOLS = 60  # hard cap on number of symbols per request`
`backend/main.py:7637` — `sym_list = sym_list[:MAX_SYMBOLS]`
`backend/main.py:7881` — idem en `/api/prices/prev-close`

Del lado del cliente, **ninguno de los 12+ call sites chunkea** (verificado con `grep -rn "'/prices"` sobre `frontend/src`): `MonthlySummary.jsx:273`, `CarteraList.jsx:86`, `useMonthlyData.js:201`, `Insights.jsx:387`, `AssetDetail.jsx:144`, `HomeMobile.jsx:96`, `FirstInsight.jsx:77`, `PositionDetailMobile.jsx:70`, `FuturosGroup.jsx:63`, `AlertsManager.jsx:105`, `AssetQuickView.jsx:40`, `DetailPortfolioBlocks.jsx:88` — todos mandan la lista entera.

**Y el repo ya sabe que esto es un problema, del otro lado** — `main.py:37264-37268` (verificado literal):

```python
# /api/prices tiene un cap DURO de 60 símbolos y TRUNCA EN SILENCIO
# (sym_list[:MAX_SYMBOLS]) — un libro de 100 clientes toca ~486 tickers, así
# que valuar desde el navegador no daría un error, daría una torta incompleta
# con pinta de correcta. Acá se resuelve sin red: asset_last_price + el motor
# canónico del snapshot (compute_broker_value_usd).
```

La frase *"no daría un error, daría una torta incompleta con pinta de correcta"* describe exactamente lo que le pasa al retail con más de 60 símbolos. El workaround se construyó sólo para el asesor.

**Efecto DEDUCIDO** (supuesto: un usuario con 70 símbolos distintos, ninguno cacheado): 10 posiciones caen a costo con Var. día `—`. Si esas 10 pesan más del 5 % del cost basis, `priceCoverage < 0.95` y el Dashboard **no escribe el snapshot** (`Dashboard.jsx:459`) — pero el cron, que no tiene el cap, **sí lo escribe completo**. La curva y el live divergen, y al día siguiente la variación diaria muestra el salto. Es la clase de bug que el propio guard de cobertura dice querer evitar.

---

## Parches detectados

Aplico la regla que me diste: un guard defensivo no es un parche. Estos tres sí lo son.

**P-1 — El guard anti-distorsión aplicado al valor y no al P&L realizado.** `trustMktValue` clampea el valor de mercado con una banda de ×50 y una historia real detrás (la ON per-100, +9775 %). Pero la misma clase de error —una magnitud en la unidad equivocada— entra sin ningún filtro por el camino de la venta y se escribe como plata realizada (`pnl_pct = 188.566 %`, medido). **Causa real:** no hay una noción de "escala plausible de este lote" compartida entre los caminos; hay una banda ad-hoc en el lugar donde apareció el síntoma. **Dónde más sigue rompiendo:** `POST /api/operations` acepta un `pnl_usd` arbitrario con el único techo de 1e12; las amortizaciones y los cupones tampoco tienen cota contra el valor del bono.

**P-2 — El guard de fecha futura escrito para el endpoint donde apareció el incidente.** El comentario de `main.py:10377` razona correctamente sobre la causa ("un cobro se registra cuando se cobró") pero la implementación es un `if` en un solo handler, cuando la propiedad es de todas las escrituras con fecha. **Dónde más sigue rompiendo:** medido en cinco endpoints, y el efecto colateral en `_rollover_to_current_month` (4b) es peor que el incidente original, porque es silencioso y permanente.

**P-3 — El chequeo de edad del last-known en `register_trade` y en ningún otro lado.** `main.py:23451` calcula la antigüedad del precio y lo descarta a las 48 h. `read_last_prices`, que alimenta el snapshot nocturno, el Dashboard y el libro del asesor, ni siquiera hace el `SELECT updated_at`. **Causa real:** la edad del precio no es parte del contrato del dato; es un chequeo local de un caller. **Dónde más sigue rompiendo:** `apply_last_known_prices` (cron), `_fill_last_known_prices` (`/api/prices`), `_advisor_positions_valued` (`main.py:36892`).

**Lo que revisé y NO es parche** (por si ahorra trabajo en la próxima tanda):
- `if cedear_rate > 0 else 0` en las cinco ramas de `compute_broker_value_usd` — guard defensivo correcto y consistente.
- `if qty <= 0 return null` en `avgCostUsdPerUnit` (`valuation.js:870`) — correcto: sin cantidad no hay precio promedio.
- `positions = _same_ccy if _same_ccy else all_positions` — es una decisión de diseño con comentario ("data legacy NULL"); el problema es su alcance, no su existencia. Lo reporto como bug de alcance, no como parche.
- El `is not None` de `price_override` — deliberado y bien documentado (ya dictaminado por 1A).
- `_dedup_splits` con la ventana de 7 días — parece ad-hoc pero el comentario documenta el caso real (NVDA.BA logueado dos veces) y la alternativa (multiplicar factores) es peor.

**Los try/except mudos.** Conté 120 `except Exception:` a línea pelada en `main.py`. No los audito todos acá (no es mi tema), pero dos caen justo en mi camino y los señalo:
- `main.py:7568-7569` — `_fill_last_known_prices` termina en `except Exception: pass`. Si la lectura de `asset_last_price` falla, las posiciones caen a costo sin que nada quede registrado.
- `main.py:23455-23456` — el chequeo de 48 h termina en `except Exception: pass # sin metadata de edad → comportamiento previo (aceptar)`. Acá el comentario justifica el fail-open, así que es deliberado; lo dejo anotado, no reportado.

---

## Citas del mapa incorrectas

Verifiqué **11** afirmaciones del mapa relacionadas con mi tema. **10 son correctas.** Una tiene la línea corrida.

| # | mapa | dice | verificación |
|---|---|---|---|
| 1 | `:9596` | *"`entry_date` solo se valida contra `_DATE_RE`: no hay tope superior"* | ✅ correcto (`main.py:8156-8163`) |
| 2 | `:15032` | *"`read_last_prices` no filtra por `updated_at`"* | ✅ correcto (`snapshots_job.py:589-600`) |
| 3 | `:15037` | *"la única excepción que sí chequea edad es el flujo de registro por chat (48 h, `main.py:23451`)"* | ✅ correcto, línea exacta |
| 4 | `:19625` | Las cuatro cláusulas de `trustMktValue`, incluida `!(realCost>0) \|\| !(mktValue>0) → true` | ✅ correcto. **El mapa transcribe bien la condición pero no saca la conclusión** (que un precio de 0 o negativo pasa como confiable). Ese es mi hallazgo B-01, no una corrección al mapa |
| 5 | `:15253` | *"`date <= ?` con una fecha de 2027 devuelve la fila más nueva que exista"* (`fx.py:60-64`) | ✅ correcto |
| 6 | `:15256` | *"la defensa está río arriba, y solo en un endpoint: `POST /api/bonds/cashflow` (`main.py:10384-10387`)"* | ✅ correcto, y lo confirmé midiendo los otros cinco |
| 7 | `:14.5 §3` | *"la posición no se excluye — entra al total con su costo"* | ✅ correcto, medido |
| 8 | `:1772` | `persist_last_prices` en `snapshots_job.py:579`, `read_last_prices` en `:597` | ✅ el `INSERT` está en `:579` y el `SELECT` en `:596-599`. Correcto |
| 9 | `:5750` | `_rollover_to_current_month` en `main.py:11433` | ✅ correcto |
| 10 | `:37266` | El cap de 60 símbolos y su razón | ✅ correcto, verificado literal |
| **11** | **`:5471`** | ***"`_rollover_to_current_month` devuelve 0 si el broker no tiene ninguna fila previa (`backend/main.py:11468`)"*** | ⚠️ **cita del mapa incorrecta (línea).** El `return 0` por "sin historial" está en **`main.py:11464`**. La línea **11468** es un `return 0` **distinto**: el de *"Ya tiene row del current month (o futura)"*, que es justamente el que mide mi hallazgo B-05. El mapa apunta a la línea del segundo caso mientras describe el primero, y así **el caso de la fila futura queda sin documentar en el mapa** |

**Corrección propuesta para el mapa, línea 5471:**

> `_rollover_to_current_month` devuelve 0 en **dos** casos: (a) el broker no tiene ninguna fila previa — `backend/main.py:11463-11464`, un broker nuevo no arranca su cadena por acá; y (b) **la última fila del broker es del mes actual _o de un mes futuro_ — `backend/main.py:11467-11468`. En (b) el rollover queda inhabilitado mientras esa fila futura exista** (medido: una operación fechada 2030-06 deja al broker sin fila del mes en curso hasta 2030).

---

## URGENTE

Nada de esto lo toqué. Son los dos que, si tuviera que elegir, arreglaría antes que el resto — no porque sean los más grandes, sino porque los dos **escriben o publican datos falsos hoy, en silencio, y el arreglo es acotado**.

**U-1 — El guard de fecha futura que ya existe, replicado a las cinco escrituras que no lo tienen.**
`backend/main.py:8156` (`PositionIn.entry_date`), `:11137` (`SellIn.date`), `:12099` (`OperationIn.date`), `:12159` (`FuturoIn.opened_at`), `:9400` (`CashFlowIn.date`). Ya existe la línea exacta en `main.py:10384` y el `_DATE_RE` está compartido.
**Por qué urgente:** medido, una sola operación fechada en 2030 **deja al usuario sin la fila mensual del mes en curso, para siempre** (`main.py:11468`), y con eso `sync-unrealized` deja de escribir el P&L no realizado en silencio — que es el modo de falla que el rollover vino a arreglar. El daño no se detiene cuando el usuario corrige la fecha: la fila de 2030 hay que borrarla a mano.
**Ojo con el orden:** si sólo se agregan los validadores, las filas futuras **ya escritas** siguen congelando el rollover. Hace falta además ignorar las filas futuras al elegir `last` en `_rollover_to_current_month` (o un barrido, como el que ya existe para snapshots en `/api/admin/cleanup-future-snapshots`, `main.py:17336`).

**U-2 — `pricing/fci.py:284`: exigir `vcp > 0`.**
Una línea: `if not isinstance(vcp, (int, float)) or vcp <= 0:`. Es la única de las cuatro fuentes de precio que no lo tiene (las otras tres sí: `main.py:7784`, `:7326`, `:7347`).
**Por qué urgente:** es la vía de entrada **real** al agujero del guard (B-01). Un `vcp` de 0 de ArgentinaDatos —una fuente que ya se cayó tres semanas en 2026, lo documenta el propio `get_prices_detail_for`— hace que el FCI **valga cero** en las dos valuaciones, se lo lleve puesto de la torta de composición, y quede escrito así en el snapshot nocturno. No cae a costo: cae a cero.
**Está en zona de deriva** (`origin/main` = `82fad6a0` toca este archivo): verifiqué el diff y **no toca `refresh_prices`**, así que el hallazgo aplica igual sobre la versión más nueva.

Nota: **no pongo en URGENTE el agujero del `trustMktValue` en sí** (`!(mktValue > 0) → true`), aunque sea 🔴, porque cambiar ese guard toca los dos motores de valuación a la vez y hay que pensar qué significa "0" en cada rama (un `price_override = 0` deliberado tiene que seguir dando 0). Tapar la vía de entrada (U-2) es seguro; arreglar el guard merece diseño.

---

## BLOQUE-RESUMEN

| tema | # | hallazgo | evidencia | severidad | dónde muerde | causa raíz |
|---|---|---|---|---|---|---|
| borde | B-01 | `trustMktValue` / `_trust_mkt_value` devuelven `true` con `mktValue = 0` y con `mktValue < 0` → la posición vale 0 (P&L −100 %) o vale negativo. Un precio de 0,0001 sí se rechaza | **MEDIDO** — `valuation.js:449`, `snapshots_job.py:48` | 🔴 | Cartera, Dashboard, snapshot nocturno, torta de composición, packets de IA | El `or` pega "sin costo no hay con qué comparar" (correcto) con "sin valor tampoco" (falso): con valor 0 sí hay con qué comparar, y el múltiplo es absurdo |
| borde | B-02 | `pricing/fci.py:284` acepta `vcp = 0` (sólo chequea `isinstance`) y escribe `price = 0.0`. Las otras 3 fuentes de precio filtran `> 0` | **ESTRUCTURAL** — verificado también contra `origin/main` `82fad6a0`: no corregido | 🔴 | FCI en Cartera, Renta Fija, snapshot | Guard de "precio positivo" aplicado en 3 de 4 fuentes |
| borde | B-03 | La venta no tiene cota de plausibilidad: lote ARS vendido declarando USD → `pnl_usd = +19.989,40`, `pnl_pct = +188.566,67 %` sobre un lote de US$106. El comentario de `:11195` dice que se rechaza; el código de `:11202` cae a todos los lotes | **MEDIDO** | 🔴 | P&L realizado, `monthly_entries`, curva, Reportes, IA | El no-realizado tiene banda ×50 (`trustMktValue`); el realizado no tiene ninguna. El `exit_price` nunca se convierte de moneda |
| borde | B-04 | Fecha futura aceptada por 5 de 7 escrituras (`positions`, `operations`, `sell`, `futures`, `plazos-fijos`). El único guard vive en `/api/bonds/cashflow` | **MEDIDO** — `main.py:8156`, `:11137`, `:12099`, `:12159` vs `:10384` | 🔴 | Toda la cadena contable | Guard escrito para el endpoint donde apareció el incidente, no para la propiedad |
| borde | B-05 | Una fila mensual futura hace que `_rollover_to_current_month` devuelva 0 filas **para siempre** → el mes en curso deja de existir y `sync-unrealized` no-opea en silencio | **MEDIDO** — `main.py:11467-11468` | 🔴 | Cuadro mensual, evolución, P&L no realizado | `last` se elige con `ORDER BY year DESC` sin excluir el futuro |
| borde | B-06 | `POST /api/positions` y `POST /api/operations` aceptan un broker inexistente; `POST /api/monthly` lo rechaza. Medido: aportado 10.999 vs valuación 1.000 = **−US$9.999** de pérdida fantasma | **MEDIDO** | 🟠 | Dashboard (ganancia total, aportado), snapshot, Reportes | El guard existe en 3 lugares (monthly, asesor, chat) y falta en el alta, que es donde se crea la fila |
| borde | B-07 | `PositionIn` es el único modelo monetario sin `le=_FINITE_BOUND`: `invested = 1e308` y `quantity = 1e308` aceptados y propagados a `monthly_entries.capital_final` | **MEDIDO** — `main.py:8142-8147` vs `:11112`, `:12067`, `:11419` | 🟠 | Toda la cadena contable | Guard aplicado a 4 modelos de 5, y falta justo en el que siembra la cadena |
| borde | B-08 | `read_last_prices` no lee `updated_at` (que sí se escribe): un precio de 2019 se sirve como si fuera de hoy. `register_trade` sí lo chequea, con 48 h | **MEDIDO** — `snapshots_job.py:589` vs `main.py:23451` | 🟠 | Delistados, fuentes muertas, feriados largos | La edad del precio es un chequeo local de un caller, no parte del contrato del dato |
| borde | B-09 | `apply_last_known_prices` corre **antes** del guard de cobertura del 95 % → un precio congelado cuenta como "con precio" y habilita el snapshot | **ESTRUCTURAL** — `snapshots_job.py:697` vs `:734` | 🟠 | Snapshot nocturno, curva histórica | El guard mira si FALTA el precio, no si SIRVE |
| borde | B-10 | El hero del Dashboard publica `0,00 %` con aportado ≤ 0, junto a un monto real. El KPI del mismo archivo (`:668`) y `evolution.js` (`:356`, con la medición: 192 usuarios) devuelven `null` | **ESTRUCTURAL** — `Dashboard.jsx:266` + `:823` | 🟠 | Hero del Dashboard | Dos lecturas del mismo concepto en el mismo archivo, con criterios opuestos |
| borde | B-11 | `/api/prices` trunca a 60 símbolos en silencio y **ningún** call site del frontend chunkea. El workaround existe sólo del lado asesor, con el razonamiento escrito | **ESTRUCTURAL** — `main.py:7139`, `:7637`, `:37264` | 🟠 | Carteras grandes: parte al costo, sin cartel | El cap se puso en el endpoint y el chunking nunca se puso en el cliente |
| borde | B-12 | `sumRowUSDT` / `sumRowARS` devuelven `pnlPct = 0` cuando el costo es 0, con `pnl != null` | **MEDIDO** — `valuation.js:919`, `:941` | 🟡 | Filas de Cartera | Mismo "cero falso" que `evolution.js:356` documenta y evita |
| borde | B-13 | MEP `0`/`null` → frontend `Infinity`/`NaN`; backend `0`. Los dos son "port fiel" uno del otro | **MEDIDO** — `valuation.js` vs `snapshots_job.py:222` | 🟡 | Display del Dashboard con FX caído (el cron es fail-closed) | El guard `if rate > 0 else 0` existe sólo del lado Python |
| borde | B-14 | `min_length=1` corre antes del `.strip()`: `broker="   "` y `asset="   "` se guardan como `""` | **MEDIDO** — `main.py:8139-8140` + `:8177-8184` | 🟡 | Fila de `monthly_entries` con broker `''`; posición que nunca se valúa | Orden de validadores de Pydantic v2 |
| borde | B-15 | El cambio de ticker cascadea a `positions`, `import_normalized_tx` y `operations`, pero **no** a `snapshots.holdings_json` ni a `asset_last_price` | **ESTRUCTURAL** — `main.py:8431-8447` | 🟡 | Movers de Reportes, atribución MtM histórica | El mismo razonamiento que justificó cascadear a `operations` no se extendió a la foto histórica |
| borde | B-16 | Fuera de rueda `pct = 0` → `previo = actual` → todas las filas `.BA` muestran `+0,00 %`, que se lee como "no se movió" | **ESTRUCTURAL** — `main.py:7917` (P-153) | 🟡 | Variación diaria de Cartera | No se distingue "no hay dato" de "no se movió" |
| borde | B-17 | `StalePricesNotice` sólo se monta en `/cartera`; Dashboard, Insights, Reportes, Home y los packets de IA leen los mismos precios sin avisar | **ESTRUCTURAL** — `Positions.jsx:2002` | 🟡 | Todas las pantallas menos una | El aviso se hizo donde se reportó el síntoma |
| borde | B-18 | Split + precio congelado: la cantidad queda en escala nueva y el last-known en la vieja → valor ×F o ÷F | **DEDUCIDO** (composición de B-08 y `main.py:8879`) | 🟡 | Cualquier CEDEAR con split cuyo feed se cae | El ajuste de split no invalida el precio cacheado |
| borde | B-19 | `computeBrokerValue(undefined, …)` lanza `TypeError` sin capturar | **MEDIDO** | ⚪ | Pantalla en blanco si el fetch de posiciones falla raro | Falta un `|| []` |
| borde | B-20 | Un `asset = ''` nunca se valúa: `build_price_symbols` lo omite y el valor queda anclado al costo | **MEDIDO** | ⚪ | Posición invisible para el motor de precios | Consecuencia de B-14 |
| borde | B-21 | Venta con `exit_price = 0` aceptada (`pnl_pct = −100 %`) | **MEDIDO** | ⚪ | — | Probablemente correcto: es cómo se da de baja un delistado. Lo dejo anotado para que lo confirmes |
