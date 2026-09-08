# 1A — Veredicto: Tipo de cambio y conversión de moneda

**Grupo:** Tipo de cambio (blue, MEP, CCL, cripto) y conversión de moneda · 11 divergencias (DIV-134–DIV-144)
**Commit auditado:** b74f450f2badf1a2b84e657551115a0595110e45 (`/tmp/rendi-main`, `backend/main.py` = 38.029 líneas ✅)
**Citas verificadas:** 38 de 42 correctas · 4 corregidas · 1 afirmación del mapa refutada por el código
**Deriva `82fad6a0`:** ninguno de los hallazgos cae en `backend/pricing/fci.py`, `frontend/src/components/AddPositionFlow.jsx` ni `backend/tests/test_fci_uala.py`. Nada de este informe está corregido por ese commit.

---

## Resumen ejecutivo

El sistema tiene **cuatro rieles de dólar simultáneos** (blue, MEP-medio, MEP-punta-venta, CCL) y **tres resoluciones temporales** (vivo, diario, mensual), y ninguna capa decide cuál se usa: lo decide cada call site. Los tres hallazgos que mueven plata de verdad son:

1. **🔴 `POST /api/brokers/reconcile-cash` divide por 1415 hardcodeado.** Su único caller (`ImportWizard.jsx:2721`) no manda `tc_blue`, así que `data.tc_blue` cae al default de Pydantic (`main.py:10020`) y `main.py:10100` hace `magnitude / 1415`. Ese número va a `monthly_entries.deposits/withdrawals` = **capital aportado = el denominador del rendimiento**, y encima se bookea en el mes MÁS VIEJO del broker. Con MEP ~1.518, un ajuste de 5.000.000 ARS entra como US$3.534 en vez de US$3.293: **+7,3 % de capital aportado fantasma**, permanente, en cada reconciliación de caja post-import.
2. **🔴 La curva del Dashboard en Pesos usa el BLUE y los KPIs de arriba usan el MEP.** El valor USD del snapshot se obtuvo dividiendo por el MEP (`snapshots_job.py:715`) y el frontend lo re-multiplica por el blue (`Dashboard.jsx:608` → `evolution.js:156-171`), mientras el hero multiplica por `tcValuacion` = MEP (`CurrencyContext.jsx:214-229`). Dos números en la MISMA pantalla, separados por la brecha blue−MEP entera (~3,7 % hoy, histórico hasta 15 %). Lo mismo pasa en `/operaciones` (`useHistoricalMoney` → blue) y en `/mensual` (blue MENSUAL).
3. **🔴 Una conversión ARS→USD importada CREA capital de la nada; la manual no registra nada.** `persister._persist_fx:1139` saca la pata ARS al **blue de hoy** y mete la pata USD a face value, mientras `POST /api/conversions` (`main.py:10870-11005`) **no llama a `_update_monthly_flow` ni una vez**. Dos caminos para el mismo hecho con efectos opuestos sobre el mismo número. Peor: dentro del propio importador, `usd_to_ars` tampoco escribe flujo, así que la asimetría existe incluso entre las dos direcciones de la misma función.

Además hay dos divergencias que el mapa no nombra y que valen tanto como las que sí: **`fx_rates_daily` guarda punta-VENTA** (blue y MEP, de dolarapi y argentinadatos) mientras la valuación viva usa el **MEDIO** (`_val_rate`, `main.py:4630`) → toda comparación "hoy vs. serie" arrastra medio spread (~0,74 % medido con el spread real 1.507,14/1.529,71); y **el modal de venta en mobile no recibe `fxHist`** (`PositionsMobile.jsx:1642-1650`), así que una venta retroactiva en pesos desde el celular se estampa con el MEP de HOY aunque el usuario elija una fecha vieja — el desktop sí lo corrige (`Positions.jsx:3760-3776`).

Nada de esto es cosmético salvo DIV-144 (que son convergencias correctas) y DIV-142 (hoy contenida por guards).

---

## Tabla de veredictos

| DIV | versiones | ¿difieren de verdad? | cuál es la correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---:|---|---|---|---|---|
| **DIV-134** | 3 | **SÍ** — el gráfico en Pesos vs. el KPI de arriba difieren en la brecha blue−MEP (≈3,7 %) | Ninguna: hay que convertir con el MISMO riel con que se dolarizó (MEP), o guardar `fx_to_usd_mep` | `/dashboard` (curva Evolución en Pesos vs. hero), `/` home mobile (sparkline), `/operaciones` | 🔴 | Migración a medio hacer: `fx_to_usd_blue` es Fase C (2026-05-31); la valuación pasó al MEP después y nadie renombró/reemplazó la columna |
| **DIV-135** | 6 | **SÍ** — "rendimiento en pesos" de `/analisis` (blue MENSUAL) vs. Reportes (MEP diario): ~4 pp sobre la misma cartera quieta | `twr.serie_fx` (MEP diario con red al blue) | `/analisis` (gráfico Evolución, cards Comparativa), `/mensual` (tabs ARS) | 🔴 | Falta de capa compartida: 6 series de FX, ninguna importa `fx.py`; el frontend recalcula lo que el backend ya sabe |
| **DIV-136** | 5 lectores + 1 escritor | **SÍ** cuando `mep_venta` está NULL en la fila más nueva (todo fin de semana): libro del asesor ~3,6 % abajo si el parche falta | `fx.py._lookup` (IS NOT NULL dentro del WHERE) | `/clientes` (libro del asesor), brief diario por email | 🟠 | Fix aplicado en un solo lugar y después copiado a mano 3 veces; `fx.py` existe pero ningún lector del asesor lo usa |
| **DIV-137** | 5 | **SÍ** — `medio` vs `venta` = 0,74 % con el spread real; importador vs. pantalla | `_val_rate` (medio con fallback a venta) | Importador (todo flujo ARS), `/analisis?tab=reportes` con caché frío, snapshot nocturno con caché frío | 🟠 | Copy-paste + fix parcial: `_val_rate` se creó como SSoT pero `_display_blue`, `_get_blue_for_scheduler` y la rama fría de `_get_mep_for_scheduler` quedaron en `venta` |
| **DIV-138** | 2 (en el mismo archivo) | **SÍ** — mismo import, dos dólares: `gross_amount_usd` al blue live y `monthly_entries` al config stale (default 1415, medido ~143 en cuentas de 2021) | `_read_tc_blue` (live-first) — y mejor aún `fx_for_date` | `/dashboard` "Capital Aportado" tras cualquier import con flujos ARS | 🔴 | Fix aplicado en un solo lugar: `_read_tc_blue` se escribió para arreglar exactamente esto y `persist_batch` nunca se migró |
| **DIV-139** | 3 | **SÍ** — `/cash/flow` usa el TC de la FECHA; `reconcile-cash` divide por **1415 hardcodeado**; `_revert_cash_flow` usa el número del navegador | `fx_for_date(conn, fecha)` (el de `/cash/flow`) | Asistente de import → "Reconciliar caja"; deshacer transferencia | 🔴 | Migración a medio hacer: `fx_for_date` se aplicó a `/cash/flow` y los otros dos hermanos quedaron atrás |
| **DIV-140** | 2 (+1 asimetría interna) | **SÍ** — el import crea capital (+US$236 por conversión de 10 M ARS); el manual no registra nada | Ninguna: las dos patas deben ir al MISMO TC (el de la conversión, `tx.unit_price`) y las dos direcciones deben escribir | `/dashboard` y `/analisis` "Capital Aportado" / rendimiento total | 🔴 | Falta de capa compartida: dos implementaciones del mismo hecho de negocio, ninguna delega en la otra |
| **DIV-141** | 3 | **SÍ** — en cuenta v1 sin `tc_venta`, `pnl_usd` guarda PESOS (~1.518× inflado) | La rama v2 (`fx_for_date` de la fecha de la operación) | `/operaciones`, `/analisis` P&L realizado; y **mobile** manda el TC de HOY en ventas retroactivas | 🟠 | Parche por accidente: el `or 1` sólo no explota porque el frontend actual siempre manda `tc_venta` en ARS |
| **DIV-142** | 2 significados / 1 columna | **NO hoy** (todos los lectores guardan `is_cash`), **SÍ** estructuralmente | Separar la columna: `tc_compra` (lote) vs. `tc_cash_avg` (cash USD) | Ninguna hoy | 🟡 | Sobrecarga de esquema: se reusó una columna existente para un concepto nuevo |
| **DIV-143** | 2 | **SÍ** con la preferencia en CCL: Cartera y snapshot valúan a dólares distintos (~2,7 %) | Ninguna: la preferencia debe viajar al backend, o el frontend debe anclar al MEP para comparar | `/posiciones`, `/dashboard`, `/analisis` (P&L Día fantasma) — parcheado SOLO en el home mobile | 🟠 | Parche puntual: `HomeMobile.jsx:125` resuelve el síntoma en una pantalla y las otras tres quedan rotas |
| **DIV-144** | — | **NO** — convergencias reales, verificadas | (n/a) | (ninguna) | ⚪ | (n/a) |

---

## Detalle por divergencia

### DIV-134 — La curva en Pesos usa el blue; el KPI de arriba usa el MEP

**Estado de las citas:** ⚠️ corregidas. `snapshots_job.py:791` ✅, `snapshots_job.py:715` ✅, `CurrencyContext.jsx:214-229` ✅ (es `fmtMoneyRaw`). El mapa escribe el archivo como `frontend/src/contexts/CurrencyContext.js` — **el archivo es `.jsx`** (error sistemático del mapa en toda la columna "sitios"). Falta en el mapa el eslabón que cierra la cadena: `Dashboard.jsx:596-608` + `evolution.js:156-171`.

#### a. Implementaciones

**A1 — El snapshot se dolariza al MEP** (`backend/snapshots_job.py:715`, verificado):
```python
tc_cedear = tc_mep if (tc_mep and tc_mep > 0) else _user_tc_cedear(conn, uid, tc_blue)
```
`tc_mep` viene de `_get_mep_for_scheduler()` (`main.py:32016`) → `_current_cedear_rate()` → `_val_rate` = **MEP medio**. Ese `tc_cedear` es el `cedear_rate` que recibe `compute_broker_value_usd` (`snapshots_job.py:751-752`).

**A2 — Pero se estampa el BLUE** (`backend/snapshots_job.py:771-791`, verificado):
```python
# Phase C: stampamos fx_to_usd_blue (= tc_blue del día) ...
INSERT INTO snapshots (..., fx_to_usd_blue, ...) VALUES (...)
""", (uid, target_date, total_value, total_invested, net_deposited, tc_blue, holdings_json))
```
`tc_blue` = `_get_blue_for_scheduler()` (`main.py:32009-32013`) = `_fetch_dolar("blue")["venta"]`, **punta venta del blue**.

**A3 — El frontend re-multiplica por ese blue** (`frontend/src/utils/evolution.js:156-171`, verificado):
```js
export function convertSeriesToArs(series, getFxForDate) {
  return series.map(p => {
    const stamped = p.fxToUsdBlue
    const fx = (stamped && stamped > 0) ? stamped : getFxForDate(p.date)
    const safeFx = (fx && fx > 0) ? fx : 1
    return { ...p, valueUsd: p.valueUsd * safeFx, netDeposited: p.netDeposited * safeFx, _fxUsed: safeFx }
```
Consumido en `frontend/src/pages/Dashboard.jsx:608`: `convertSeriesToArs(evoSeries, getHistoricalFx)`, con `getHistoricalFx = useFxHistory(tcValuacion).getRateOrFallback` (`Dashboard.jsx:208`) — que lee `r.blue` (`useFxHistory.js:138-140, 149-167`). O sea: **stamped = blue, y el fallback también es blue.**

**A4 — El KPI de la misma pantalla usa el MEP** (`frontend/src/contexts/CurrencyContext.jsx:214-229`, verificado):
```js
export function fmtMoneyRaw(usdValue, currency, tcValuacion, opts = {}) {
  const isArs = currency === 'ARS' && tcValuacion > 0
  const v = isArs ? usdValue * tcValuacion : usdValue
```
con `tcValuacion = pickFinancialRate(dolar, valuationDollar)` (`CurrencyContext.jsx:46-54, 137`) = **MEP medio** (o CCL según preferencia).

#### b. Fórmulas

Sea `V_ars` el valor nativo en pesos de las tenencias .BA, `M_d` el MEP medio del día *d*, `B_d` el blue venta del día *d*, `M_hoy` el MEP medio vivo.

- Snapshot: `V_usd(d) = V_ars(d) / M_d`
- Curva en Pesos (A3): `V_display(d) = V_usd(d) × B_d = V_ars(d) × (B_d / M_d)`
- KPI hero en Pesos (A4): `V_hero = V_usd(hoy) × M_hoy = V_ars(hoy)`

#### c. ¿Real o cosmética? — **REAL**

Con el toggle en USD las dos son byte-idénticas (el FX no entra). Con el toggle en **Pesos** difieren en el factor `B/M`.

Ejemplo con cotizaciones realistas (spread MEP real citado en `test_dolar_medio.py`: compra 1.507,14 / venta 1.529,71 → medio **1.518,43**; blue venta **1.575**):

| | cálculo | resultado |
|---|---|---|
| Hero "Valor total" en Pesos | US$50.000 × 1.518,43 | **$75.921.500** |
| Último punto de la curva | US$50.000 × 1.575 | **$78.750.000** |
| Diferencia | | **$2.828.500 (+3,73 %)** |

En 2020-2023 la brecha blue−MEP superó el 15 % en varios tramos: la misma pantalla habría mostrado $75,9 M arriba y $87,3 M en el gráfico.

Peor: como `B_d/M_d` **varía en el tiempo**, la FORMA de la curva en pesos también miente. Un día en que la brecha se abre 2 pp con la cartera quieta dibuja un +2 % que no existió.

#### d. Dictamen

**Ninguna implementación es correcta.** El invariante que hay que respetar es: *el TC que devuelve un valor a pesos tiene que ser el mismo con el que se lo sacó de pesos*. Como el snapshot dolariza al MEP, la curva tiene que multiplicar por el MEP de esa fecha:

```
V_display(d) = V_usd(d) × MEP_medio(d)
```

Para eso hace falta una columna `snapshots.fx_to_usd_mep` (o renombrar la existente y estampar `tc_mep` en vez de `tc_blue`, que es literalmente cambiar el argumento en `snapshots_job.py:791` — el valor ya está en scope en la variable `tc_mep`). La red `getRateOrFallback` debe pasar a `getMepOrFallback` (ya existe, `useFxHistory.js:204-208`).

#### e. Qué ve mal el usuario y dónde

- **`/dashboard`** con el selector de moneda en **Pesos**: la curva "Evolución" y el eje Y sobreestiman ~3,7 % respecto del hero de arriba. El chip de variación del período también, porque se calcula sobre esa serie.
- **`/` (home mobile)**: mismo helper `buildPortfolioValueSeries` (`HomeMobile.jsx:157`); el rótulo "Hace 30d · $X" sale del mismo riel.
- **`/operaciones`**: `useHistoricalMoney` (`useHistoricalMoney.js:52`) usa el mismo `getRateOrFallback` = blue. Y es MIXTO: las filas con `fx_to_usd` estampado (ventas v2) usan el MEP de su fecha y las que no, el blue → **dos rieles dentro de la misma lista**, y por lo tanto el total no es la suma visual de las filas convertidas.
- **`GET /api/snapshots`** (`main.py:5096-5112`) es el endpoint que sirve `fx_to_usd_blue`.

#### f. Causa raíz

**Migración a medio hacer.** `fx_to_usd_blue` se creó en "Phase C (2026-05-31)" cuando la app valuaba al blue; el comentario de `CurrencyContext.jsx:6-9` documenta la migración posterior ("UNIFICACIÓN FX (2026-06): la conversión USD↔ARS usa el dólar MEP … NO el blue"). Se migró el lado de display y **no se migró el lado del stamp**. La columna sigue nombrada `blue` y sigue recibiendo `tc_blue`.

#### g. Fuente única de verdad propuesta

Una sola función `fxParaMostrar(fecha) → {tc, riel}` en `frontend/src/hooks/useFxHistory.js`, alimentada por una columna `snapshots.fx_valuacion` estampada por `snapshots_job` con **el mismo `tc_cedear` que usó para valuar**. Eliminar `convertSeriesToArs`'s preferencia por `fxToUsdBlue` y `lookupHistoricalDolar` (ver DIV-135).

---

### DIV-135 — Seis series de dólar histórico, tres rieles, dos resoluciones

**Estado de las citas:** ✅ verificadas, con una corrección de alcance. `useFxHistory.js:149-167` ✅ (`getRateForDate`+`getRateOrFallback`, blue). `useFxHistory.js:201-208` ✅ (`getMepOrFallback`). `main.py:5378-5392` ✅ (`_fetch_dolar_blue_monthly`, def en 5378). `Insights.jsx:588-599` ✅ (`lookupDolar` sobre `bench.dolar_blue`). `twr.py:1242-1266` ✅ (cuerpo de `serie_fx`, def en 1220). `ledger_replay.py:185-192` ✅ (`_fx_en`). `fx.py:76-97` ✅ (`fx_for_date_detail`).

#### a. Implementaciones

| # | Sitio verificado | Riel | Resolución | Red |
|---|---|---|---|---|
| S1 | `frontend/src/hooks/useFxHistory.js:149-167` `getRateOrFallback` | **blue** | diaria (`fx_rates_daily.blue_venta`) | `tcValuacion` vivo |
| S2 | `frontend/src/hooks/useFxHistory.js:177-208` `getMepDetail`/`getMepOrFallback` | **MEP** | diaria | blue del día → `getRateOrFallback` |
| S3 | `backend/main.py:5378-5392` `_fetch_dolar_blue_monthly` → `bench.dolar_blue` → `frontend/src/utils/fx.js:26-48` `lookupHistoricalDolar` | **blue** | **MENSUAL** (última obs. del mes) | `liveTc` |
| S4 | `backend/twr.py:1220-1280` `serie_fx` | **MEP → blue** | diaria | ninguna (devuelve `None`) |
| S5 | `backend/ledger_replay.py:185-192` `_fx_en` | **MEP puro** | diaria | ninguna (`None`) |
| S6 | `backend/fx.py:76-97` `fx_for_date_detail` | **MEP → blue** | diaria | `fallback` explícito del caller |

S4 y S6 son la misma cascada escrita dos veces (`serie_fx` no importa `fx.py`; hace su propio `SELECT date, mep_venta, blue_venta` en `twr.py:1242`). S5 es una tercera copia sin red.

#### b. Fórmulas

Rendimiento en pesos de un tramo [d0, d1] con valor USD `V`:

- **Reportes / motor TWR** (S4, vía `reporting/builder.py:645-653` que delega en `twr._leg_en_moneda`):
  `R_ars = (V1 × MEP_d1) / (V0 × MEP_d0) − 1`, con `MEP_d` = `mep_venta` del día d (punta venta), red al `blue_venta` del día.
- **`/analisis` gráfico Evolución** (S3, `evolution.js:519,565` + `Insights.jsx:587-599`):
  `R_ars = (V1 × BLUE_mes(d1)) / (V0 × BLUE_mes(d0)) − 1`, con `BLUE_mes(d)` = **último blue del mes calendario de d** (o `liveTc` si el mes es el corriente, `fx.js:29`).

#### c. ¿Real o cosmética? — **REAL**

Ejemplo: cartera **quieta en dólares** (rendimiento USD exactamente 0 %) entre 2025-09-15 y 2026-09-05, con la brecha blue−MEP abriéndose del 1 % al 3,7 %:

| | MEP inicial | MEP final | blue inicial (mes) | blue final (mes) | "Rendimiento en pesos" |
|---|---|---|---|---|---|
| Reportes (S4) | 1.000 | 1.518,43 | — | — | **+51,84 %** |
| `/analisis` (S3) | — | — | 1.010 | 1.575 | **+55,94 %** |

**4,10 puntos porcentuales de diferencia sobre la misma cartera y el mismo período.** A eso se le suma el error de anclaje mensual de S3: para una ventana que termina el 5 de septiembre, `lookupHistoricalDolar` devuelve `liveTc` si el mes es el corriente (`fx.js:29`) pero el cierre de **agosto** si no lo es — un salto discreto de hasta un mes de devaluación al pasar de mes.

Y S3 se usa incluso cuando hay granularidad diaria: `buildEvolutionFromSnapshots` (`evolution.js:407,519,565`) tiene un punto por DÍA y lo convierte con el blue **del mes**. Todos los días de un mes comparten el mismo TC → la curva en pesos es una escalera.

#### d. Dictamen

**S4/S6 (`serie_fx` / `fx_for_date`) es la correcta**: riel MEP (que es el dólar al que el usuario realmente sale de la inversión y el mismo con que se valúa la tenencia), resolución diaria, red histórica declarada al blue, determinística. El docstring de `fx.py:1-45` documenta la cobertura medida (MEP diario completo desde 2018-10-29; blue desde 2011-01-03) que hace innecesaria la serie mensual.

**S3 debe morir.** `bench.dolar_blue` no existe para esto — existe para el benchmark "Pesos cash (blue)" (`Insights.jsx:1276`), donde el blue SÍ es el activo simulado.

#### e. Qué ve mal el usuario y dónde

- **`/analisis`** (ex `/insights`, `App.jsx:206` redirige a `?tab=diagnostico`): el gráfico de Evolución con el toggle en Pesos y las cards "Comparativa" (`Insights.jsx:700-753`, `797-804`, `1001-1004`).
- **`/mensual`** (`MonthlySummary.jsx:165`): las tabs de brokers ARS convierten cada mes con `lookupHistoricalDolar` = blue mensual.
- **`/analisis?tab=reportes`** (`GET /api/reports/timeline`, `main.py:33073`): MEP diario. **Es el número correcto, pero contradice al de la pestaña de al lado.**

#### f. Causa raíz

**Falta de una capa compartida + frontend recalculando lo que el backend ya calculó.** `fx.py` fue escrito explícitamente como "la fuente única para dolarizar cualquier cosa histórica" (docstring, `fx.py:1`) y **ninguna de las otras cinco series lo importa**. `twr.serie_fx` y `ledger_replay._fx_en` son reimplementaciones backend; S1/S3 son reimplementaciones frontend que además eligen otro riel.

#### g. Fuente única de verdad propuesta

`backend/fx.py` como único lector de `fx_rates_daily`. `twr.serie_fx` debe llamarlo (conservando su índice `bisect` como caché). `ledger_replay._fx_en` debe ser `fx.fx_for_date(conn, fecha, fallback=None)`. El frontend debe recibir la serie **MEP** desde `GET /api/fx-rates` (que ya la devuelve, `main.py:5185-5197`) y `getRateOrFallback` debe pasar a leer `mep` con red a `blue` — o sea, colapsar S1 dentro de S2. Eliminar `frontend/src/utils/fx.js` (`lookupHistoricalDolar`) y `_fetch_dolar_blue_monthly` fuera del contexto de benchmark.

---

### DIV-136 — `mep_venta` es NULLABLE y el cron no lo escribe: cinco parches distintos

**Estado de las citas:** ⚠️ una **refutada**.
- `snapshots_job.py:981-987` ✅ verificado: el INSERT del cron nombra **sólo** `blue_venta`.
- `useFxHistory.js:169-176` ⚠️ **corregida**: 169-176 es el bloque de comentario; la función `getMepDetail` va de **177 a 199**.
- `main.py:36832-36840` ✅ verificado (`_advisor_book_fx`, def en 36820).
- `advisor_brief.py:164-165` ⚠️ **el mapa dice que es "copia del anterior" y el código lo desmiente.** `advisor_brief._fx` (líneas **160-185**) tiene una rama que `_advisor_book_fx` **no tiene**: prueba primero `main._current_cedear_rate()` (MEP **medio vivo**) y sólo si eso falla hace el mismo parche. No son copias: **dan MEPs distintos**.
- `fx.py:53-58` ✅ verificado (el `IS NOT NULL` en el WHERE está en `fx.py:62-63`, documentado en el docstring 53-58).

**Lectores que el mapa no cuenta:** `main.py:35723-35733` (variación % del MEP para el asesor) es un **sexto** lector con su propia query, y usa el patrón correcto (`WHERE date <= ? AND mep_venta IS NOT NULL`) sin pasar por `fx.py`.

#### a. Implementaciones

**Escritor único del hueco** (`backend/snapshots_job.py:978-988`):
```sql
INSERT INTO fx_rates_daily (date, blue_venta, source) VALUES (?, ?, 'snapshot_cron')
ON CONFLICT(date) DO UPDATE SET blue_venta = excluded.blue_venta, ...
```
No menciona `mep_venta` → todas las noches nace una fila con `mep_venta = NULL`. (El otro escritor, `_persist_blue_for_date`, `main.py:4675-4681`, SÍ escribe el MEP — pero sólo corre cuando alguien postea un snapshot desde el browser con el caché de `/api/dolar` caliente.)

**L1 — `fx.py:59-73`** (correcto): `IS NOT NULL` dentro del WHERE → agarra el MEP del último día que lo tenga.
**L2 — `useFxHistory.js:177-199`** (correcto y honesto): recorre hacia atrás `mepByDate` y devuelve `{tc, source, asOf}` para poder declarar la degradación al usuario.
**L3 — `main.py:36826-36841`** (`_advisor_book_fx`): toma la fila más nueva; si su `mep_venta` es NULL, segunda query "última fila CON mep"; si tampoco, **`tc_mep = tc_blue`**.
**L4 — `advisor_brief.py:166-185`**: **primero** `main._current_cedear_rate()` (MEP medio vivo) y recién si falla replica L3.
**L5 — `main.py:35723-35729`**: query propia con el patrón correcto.

#### b. Fórmulas

- L1/L2/L5: `MEP(d) = último mep_venta con fecha ≤ d` (arrastre correcto).
- L3: `MEP = mep_venta[fila_max_fecha]` si no es NULL; **si no**, `último mep_venta global`; **si no**, `blue_venta[fila_max_fecha]`.
- L4: `MEP = _val_rate(caché.mep) = (compra+venta)/2` si el caché está caliente; **si no**, L3.

#### c. ¿Real o cosmética? — **REAL, en dos ejes**

**Eje 1 (el que el mapa nombra):** si el parche de L3 no estuviera, `tc_mep = tc_blue`. Valuar tenencias en pesos dividiendo por el blue (1.575) en vez del MEP (1.518,43) baja el libro **3,6 %**. El comentario del código dice "~5 % abajo un fin de semana cualquiera" — consistente. El parche funciona, así que este eje está **contenido**.

**Eje 2 (que el mapa no ve, y sí está roto hoy):** L3 y L4 valúan **el mismo libro del mismo asesor** con dos MEPs distintos.

| | fuente del MEP | valor |
|---|---|---|
| `/clientes` — libro (L3 vía `main.py:35462, 35961, 36983, 37689, 37825`) | `fx_rates_daily.mep_venta` (punta **venta**, último día con dato) | 1.529,71 |
| Brief diario por email (L4 vía `advisor_brief.py:143`) | `_current_cedear_rate()` (**medio** vivo) | 1.518,43 |

Un libro de 700.000.000 ARS: 457.605 USD en la pantalla vs. 461.007 USD en el mail. **US$3.402 (0,74 %) de diferencia entre dos vistas del mismo libro el mismo día** — exactamente el bug que el docstring de `_advisor_book_fx` dice estar evitando ("dos pantallas del asesor mostrando el mismo libro a tipos de cambio distintos es el bug clásico de esta app"). El docstring es correcto sobre la intención y falso sobre el resultado: la deduplicación se hizo entre tres endpoints y dejó afuera al cuarto consumidor.

#### d. Dictamen

**La correcta es `fx.py._lookup` para lo histórico y `_val_rate`/`_current_cedear_rate` (medio vivo) para "hoy"** — que es lo que hace L4. `_advisor_book_fx` (L3) debe reescribirse como:
```python
tc_mep = main._current_cedear_rate() or _fx.fx_for_date(conn, hoy) or tc_blue
```
Y la causa de fondo se cierra escribiendo `mep_venta` en el cron: `snapshots_job` **ya tiene** `tc_mep` en scope (`snapshots_job.py:955-964`) y no lo persiste. Es una línea.

#### e. Qué ve mal el usuario y dónde

- **`/clientes`** (libro del asesor, `GET` en `main.py:35462`, `35961`, `36983`, `37689`, `37825`): el valuado del libro y el AUM total salen 0,74 % por debajo del brief.
- **Brief diario por email** (`advisor_brief.py:143`): el otro número.
- Ninguno de los dos es visiblemente absurdo — por eso nadie lo reportó. Es el tipo de desvío que sólo aparece cuando un asesor compara el mail con la pantalla.

#### f. Causa raíz

**Fix aplicado en un solo lugar, después copiado a mano.** El comentario de `main.py:36823-36826` ("Estaba copiado VERBATIM en tres endpoints del asesor") documenta una deduplicación **parcial**: se unificaron tres call sites de `main.py` y quedó afuera `advisor_brief.py`, que además ya había evolucionado. La causa estructural es que `mep_venta` sea NULLABLE con un escritor que no la escribe.

#### g. Fuente única de verdad propuesta

1. `snapshots_job.py:978-988` debe incluir `mep_venta` (el valor ya está en `tc_mep`) → el hueco desaparece y los cinco parches quedan sin sentido.
2. Un solo helper `fx.fx_hoy(conn)` que devuelva `(blue, mep)` con la política medio-vivo→serie→blue. `_advisor_book_fx` y `advisor_brief._fx` deben ser `return _fx.fx_hoy(conn)`.

---

### DIV-137 — `medio` vs `venta`: el mismo dólar con dos definiciones

**Estado de las citas:** ⚠️ una corregida.
- `main.py:4630-4644` ✅ `_val_rate` (def en 4630, cierra en 4644).
- `main.py:4896` ✅ exacto: dentro de `_display_blue` (def en 4880), la línea es `v = blue_obj.get("venta") if isinstance(blue_obj, dict) else blue_obj`.
- `main.py:32011` ✅ (`_get_blue_for_scheduler`, def en 32009): `if blue and blue.get("venta")`.
- `main.py:32024-32032` ⚠️ **corregida**: 32017-32024 es el docstring. La primera rama (medio) está en **32025-32027** y el fetch directo con punta **venta** en **32031-32034** (`return float(d["venta"])`).
- `importing/pipeline.py:55` ✅ (`live = _main._display_blue(conn, uid)` dentro de `_read_user_tc_blue`, def en 40).
- `importing/persister.py:1308` ✅ (`live = _main._display_blue(conn, uid)` dentro de `_read_tc_blue`, def en 1299).

#### a. Implementaciones

```python
# main.py:4630-4644 — SSoT declarada
def _val_rate(obj):
    v = obj.get("medio") or obj.get("venta")      # MEDIO
# main.py:4880-4901 — _display_blue
    v = blue_obj.get("venta") if isinstance(blue_obj, dict) else blue_obj   # VENTA
# main.py:32009-32013 — _get_blue_for_scheduler
    if blue and blue.get("venta"): return float(blue["venta"])              # VENTA
# main.py:32025-32034 — _get_mep_for_scheduler
    mep = _current_cedear_rate()                  # MEDIO (rama caliente)
    ...
    if d and d.get("venta") ...: return float(d["venta"])                   # VENTA (rama fría)
```
Consumidores de `_val_rate` (medio): `_display_ccl` (4904), `_current_ccl` (4923), `_current_cedear_rate` (4939) → y de ahí `analysis_prep.user_fx`, `snapshots_job`, `advisor_brief._fx`, `_live_valuation_rate`, `_autodeposit_rate`.
Consumidores de `_display_blue` (venta): `pipeline._read_user_tc_blue:55` y `persister._read_tc_blue:1308` — **el TC de fallback de todo el importador**.

#### b. Fórmulas

`medio = (compra + venta)/2` cuando hay `compra` (`_fetch_dolar`, `main.py:4626`), si no `venta`.
Con el spread real medido y citado en `backend/tests/test_dolar_medio.py:5-6` (compra **1.507,14** / venta **1.529,71**): `medio = 1.518,43`, `venta/medio = 1,00743`.

#### c. ¿Real o cosmética? — **REAL**

**Caso 1 — importador con caché frío.** Un flujo de 10.000.000 ARS:
- `_display_blue` con caché caliente → blue **venta** 1.575 → US$6.349
- `_display_blue` con caché **frío** → `_user_tc_blue(conn, uid)` = `config.tc_blue`, **default 1415** sembrado al signup (`seed.py:30`, `main.py:3146`) y nunca refrescado → **US$7.067**

La diferencia entre las dos ramas de la MISMA función es **11,3 %**, y el usuario no tiene forma de saber cuál le tocó. (Este es el mismo motor que produjo los "80.868 de 84.123 flujos en pesos al mismo 1415" que documenta `fx.py:12`.)

**Caso 2 — Reportes con caché frío.** `_live_valuation_rate` (`main.py:33051-33063`) devuelve `_get_mep_for_scheduler()`. Con caché caliente: **medio 1.518,43**. Con caché frío: **`bolsa.venta` 1.529,71**. El `start_value` del período es un snapshot escrito al medio. Sobre una cartera de US$50.000 quieta, el `end_value` frío da 49.631 → el reporte publica **−0,74 % de pérdida que no existió**, exactamente el síntoma que el propio docstring de `_live_valuation_rate` dice haber arreglado (lo arregló para el config estático, no para el medio-vs-punta).

**Caso 3 — snapshot nocturno con caché frío.** Idéntico: la serie de snapshots tiene un escalón de 0,74 % el día que el cron corrió con caché frío. Ese escalón entra a `twr` y a la variación diaria como P&L.

#### d. Dictamen

**`_val_rate` (medio) es la correcta** y está bien argumentada: el broker (Cocos/IOL/Balanz) valúa al medio, y usar la punta produjo el reporte de usuario documentado en `test_dolar_medio.py:2-7` (US$6.884 en Rendi vs. US$6.933 en Cocos).

Los tres sitios que leen `venta` deben pasar a `_val_rate`:
- `_display_blue:4896` → `_val_rate(cached.get("blue"))`
- `_get_blue_for_scheduler:32011` → `_val_rate(_fetch_dolar("blue"))`
- rama fría de `_get_mep_for_scheduler:32034` → `_val_rate(d)`

**Excepción legítima que NO hay que tocar:** `_current_cripto_rate` (`main.py:4957-4970`) se queda en `venta` **a propósito** y lo documenta (el frontend lee `dolar.cripto.venta` crudo en ~8 lugares; moverlo solo en el backend partiría la paridad `crypto_broker_factor` ↔ `cryptoBrokerFactor` de DIV-144).

#### e. Qué ve mal el usuario y dónde

- **Importador** (`POST /api/import/confirm`): "Capital Aportado" tras cualquier import con flujos en pesos, con un error de 0,74 % (caché caliente) a **11,3 %** (caché frío).
- **`/analisis?tab=reportes`** (`GET /api/reports/timeline`): pérdida fantasma de 0,74 % en el período cuando el server viene de un reinicio sin tráfico.
- **`/dashboard`** "P&L Día": escalón de 0,74 % la noche que el cron corrió frío.

#### f. Causa raíz

**Copy-paste + fix parcial.** `_val_rate` se creó específicamente como SSoT ("`_val_rate` es la SSoT de esa tasa", `test_dolar_medio.py:9`) y se aplicó a las tres funciones `_current_*`/`_display_ccl`. `_display_blue` y las dos del scheduler eran código anterior que no se revisó porque su nombre no contenía "ccl" ni "cedear".

#### g. Fuente única de verdad propuesta

`_val_rate` como **única** forma de extraer un número de una casa de dólar. Un test de guardia que grepee `.get("venta")` en `main.py` y falle salvo en `_current_cripto_rate` cerraría la clase entera.

---

### DIV-138 — Un import, dos dólares: `persist_batch` lee el config crudo

**Estado de las citas:** ✅ verificadas y exactas. `persister.py:343-351` ✅ (bloque literal). `persister.py:1299-1320` ✅ (`_read_tc_blue`, def en 1299).

#### a. Implementaciones

**P1 — `persist_batch`** (`backend/importing/persister.py:343-351`, verificado literal):
```python
    tc_blue_row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key='tc_blue'", (uid,),
    ).fetchone()
    try:
        tc_blue = float(tc_blue_row["value"]) if tc_blue_row else 1415.0
        if tc_blue <= 0:
            tc_blue = 1415.0
    except (TypeError, ValueError):
        tc_blue = 1415.0
```
Este `tc_blue` se propaga a `_persist_sell_fifo` (368), `_persist_cash_in` (372), `_apply_cash_flow` (379), `_persist_cash_out` (385) y `_persist_fx` (390, 396).

**P2 — `_read_tc_blue`** (`backend/importing/persister.py:1299-1320`), del MISMO archivo, con el docstring que nombra el bug:
> "así el import no depende de un `tc_blue` guardado que en cuentas viejas quedaba stale (~143 de 2021) e inflaba el 'aportado' ~10× con pérdida fantasma"

Se usa sólo en `revert_batch` (línea **1406**) y en el migrador FX. **`persist_batch` nunca lo llama.**

**P3 — el stamp** (`pipeline.py:97`): `tc = fx_for_date(conn, date, fallback=tc_blue)` con `tc_blue = _read_user_tc_blue` (live-first). O sea, el stamp usa el **MEP de la fecha del flujo**.

#### b. Fórmulas

Para un flujo ARS de monto `A` con fecha `d`, en el mismo batch:
- `import_normalized_tx.gross_amount_usd = A / MEP(d)`  (P3)
- El `tc_blue` que P1 pasa a `_apply_cash_flow`/`_persist_fx`/`_persist_sell_fifo` = `config.tc_blue` (default **1415**, valor de hoy en el mejor caso).

#### c. ¿Real o cosmética? — **REAL, con un mitigante parcial**

`_apply_cash_flow` (`persister.py:1063-1066`) **prefiere el stamp**:
```python
if getattr(tx, "gross_amount_usd", None) is not None:
    amount_usd = float(tx.gross_amount_usd)
else:
    amount_usd = (amount / tc_blue) if currency == "ARS" else amount
```
→ para DEPOSIT/WITHDRAW el `tc_blue` stale queda de **fallback**. Bien.

Pero **`_persist_fx` (línea 1139) no consulta el stamp** y **`_persist_sell_fifo` (762, 771-772) lo usa como fallback de `fx_for_date` en cuentas v1** (`persister.py:736`: `else: tc_venta = tc_blue`).

Ejemplo, cuenta **v1** (todas las cuentas con historia previa a la migración, `fx.py:126-131`), venta de 2021 por 500.000 ARS de ganancia:
- Correcto (MEP 2021 ≈ 180): US$2.778
- `persist_batch` con `config.tc_blue` = 1415: **US$353**
- `persist_batch` con un config stale de 143 (caso medido y citado en el docstring): **US$3.497**

Y en `_persist_fx` el `tc_blue` stale entra **sin ningún mitigante** (ver DIV-140).

#### d. Dictamen

**`_read_tc_blue` (P2) es mejor que P1, pero la correcta es ninguna de las dos: es `fx.fx_for_date(conn, tx.date)`.** El propio `fx.py:20-27` explica por qué el dólar vivo (aunque sea el live y no el config) rompe el determinismo del replay: "replayar el MISMO `import_normalized_tx` en dos momentos distintos da P&L distinto — medido: 1.490 contra 1.433,33".

`persist_batch` no debe resolver **un** TC para todo el batch: debe resolverlo **por fila**, con la fecha de la fila.

#### e. Qué ve mal el usuario y dónde

- **`/dashboard`** "Capital Aportado" y el rendimiento total (que lo tiene de denominador), después de importar un CSV con conversiones ARS→USD o ventas en pesos en una cuenta v1.
- **`/operaciones`**: el `pnl_usd` de las ventas en pesos de cuentas v1.
- El endpoint es `POST /api/import/batches/{id}/confirm` → `persister.persist_batch`.

#### f. Causa raíz

**Fix aplicado en un solo lugar.** `_read_tc_blue` fue escrito exactamente para arreglar esto (su docstring lo dice), se cableó en `revert_batch` y en el migrador, y **no se cableó en el camino principal**. Es el caso de libro: el fix vive en el mismo archivo, 950 líneas más abajo, y la función que importa no lo usa.

#### g. Fuente única de verdad propuesta

Eliminar el parámetro `tc_blue` de `_persist_*` por completo. Cada persister debe llamar `fx.fx_for_date(conn, tx.date)` con la fecha de SU fila, y el fallback (para bases vacías en tests) debe ser explícito y ruidoso. Borrar P1 (`persister.py:343-351`) y `_read_tc_blue`.

---

### DIV-139 — Tres maneras de dolarizar un movimiento de caja manual (una divide por 1415)

**Estado de las citas:** ✅ `main.py:10195-10197` exacto. ✅ `main.py:10100` exacto. **El mapa cuenta dos versiones; hay tres**, y la tercera es la peligrosa.

#### a. Implementaciones

**C1 — `POST /api/cash/flow`** (`main.py:10190-10197`, verificado):
```python
if currency == 'ARS':
    _rate = _fx.fx_for_date(conn, data.date, fallback=data.tc_blue) or data.tc_blue
    amount_usd = data.amount / _rate if _rate else data.amount
```
Resuelve el TC **en el servidor, por la fecha del movimiento**. Correcto.

**C2 — `POST /api/brokers/reconcile-cash`** (`main.py:10028` def; línea **10100**, verificado):
```python
amount_usd = magnitude / data.tc_blue if currency == 'ARS' else magnitude
```
con `class BrokerReconcileCashIn` (`main.py:10014-10020`):
```python
tc_blue: float = Field(1415, gt=0, le=1_000_000)    # ARS→USD para monthly_entries global
```
**El único caller del endpoint en toda la app es `frontend/src/components/import/ImportWizard.jsx:2721`, y NO manda `tc_blue`:**
```js
await api.post('/brokers/reconcile-cash', {
  broker_name: c.broker, target_cash: target,
})
```
→ **el valor efectivo en producción es siempre 1415,0 literal.**

**C3 — `_revert_cash_flow`** (`main.py:10218` def; línea **10240**, verificado):
```python
amount_usd = amount / tc_blue if currency == "ARS" else amount
```
Usa el `tc_blue` que le pasa el caller (el número del navegador), **sin `fx_for_date`**, aunque la función SÍ recibe `date` y la usa para elegir el mes (`main.py:10233-10238`).

#### b. Fórmulas

- C1: `USD = A / fx_for_date(fecha)` — MEP del día del movimiento, red al blue del día, red al TC del cliente.
- C2: `USD = |target − cash_actual| / 1415`, bookeado en el **mes más antiguo del broker** (`main.py:10083-10090`).
- C3: `USD = A / tc_cliente`, bookeado en el mes de `date`.

#### c. ¿Real o cosmética? — **REAL, y C2 es la peor del grupo**

Reconciliación de caja de un broker ARS: el usuario importa un CSV parcial de Cocos, Rendi calcula 3.000.000 ARS de cash y el usuario tipea el real, 8.000.000. `diff = 5.000.000 ARS`.

| | rate | capital aportado registrado |
|---|---|---|
| C2 (lo que corre hoy) | **1415** hardcodeado | **US$3.533,57** |
| Correcto a hoy (MEP medio) | 1.518,43 | US$3.293,17 |
| Diferencia | | **+US$240,40 = +7,30 %** |

Y no termina ahí: C2 bookea ese depósito en el **mes más antiguo del broker**, que puede ser 2021. Si la lógica fuera coherente con C1 (TC de la fecha del asiento), el rate sería el MEP de 2021 (~180) y el monto US$27.778. O sea que C2 no sólo usa un número inventado: usa un número de **hoy** para un asiento que declara ser de **hace cuatro años**. Las dos decisiones están mal y se compensan de forma impredecible.

C3 tiene el mismo defecto que C1 tenía antes de su fix: revierte un movimiento retroactivo con el dólar del navegador, así que **aplicar y deshacer no se cancelan** si el movimiento era viejo. El propio C1 documenta el bug ("cargar un depósito de 2024 lo habría dolarizado al dólar de hoy y deformado el capital aportado") y su hermano de 40 líneas más abajo lo sigue teniendo.

#### d. Dictamen

**C1 es la correcta.** C2 y C3 deben usar `_fx.fx_for_date(conn, fecha_del_asiento, fallback=...)`, con la fecha que efectivamente se bookea (para C2, la del mes más antiguo; o mejor, bookear en el mes corriente al TC de hoy — pero decidirlo, no dejarlo implícito).

El `Field(1415, ...)` de `BrokerReconcileCashIn` y de `CashFlowIn` (`main.py:9385`) debe ser `Optional[float] = None`: un default silencioso de 1415 es la definición de un valor hardcodeado que tapa un caller incompleto.

#### e. Qué ve mal el usuario y dónde

- **Asistente de importación → paso "Reconciliar caja"** (`ImportWizard.jsx`, componente que postea a `/api/brokers/reconcile-cash`): el "Capital Aportado" del `/dashboard` queda 7,3 % arriba (o mucho más, según la brecha entre 1415 y el MEP del momento) por cada broker ARS reconciliado.
- **Deshacer una transferencia fallida** (`_revert_cash_flow`): el mes queda con un residuo de capital aportado.

#### f. Causa raíz

**Migración a medio hacer.** `fx_for_date` se cableó en `/cash/flow` (con un comentario largo explicando por qué) y los otros dos escritores de `monthly_entries.deposits/withdrawals` quedaron atrás. El agravante es el **default de Pydantic**: `Field(1415)` hace que un caller que no manda el campo no falle — el error es silencioso por diseño.

#### g. Fuente única de verdad propuesta

Un helper `_flujo_a_usd(conn, uid, monto, currency, fecha, tc_cliente=None) -> float` en `main.py`, único autorizado a escribir el `amount_usd` de `_update_monthly_flow`. Los tres endpoints lo llaman. `_autodeposit_rate` (`main.py:9840-9851`) — que hoy es una **cuarta** implementación, correcta pero separada — debería colapsarse dentro.

---

### DIV-140 — La conversión ARS→USD: el import crea capital, el manual no registra nada

**Estado de las citas:** ✅ `persister.py:1139-1143` exacto. ✅ `main.py:10898-10914` cae dentro de `create_conversion` (def en **10871**, `@app.post("/api/conversions")` en **10870**), rama `ars_to_usd`. **Verificado con `awk` sobre las 190 líneas del endpoint: cero llamadas a `_update_monthly_flow`.**

#### a. Implementaciones

**M1 — importada** (`backend/importing/persister.py:1136-1143`, verificado literal):
```python
        _y, _m = int(tx.date[:4]), int(tx.date[5:7])
        _ars_as_usd = (ars_amount / tc_blue) if tc_blue else 0.0
        helpers._update_monthly_flow(conn, uid, ars_broker["name"], _y, _m, "withdraw", _ars_as_usd)
        helpers._update_monthly_flow(conn, uid, "global", _y, _m, "withdraw", _ars_as_usd)
        helpers._update_monthly_flow(conn, uid, usd_broker["name"], _y, _m, "deposit", usd_amount)
        helpers._update_monthly_flow(conn, uid, "global", _y, _m, "deposit", usd_amount)
```
`tc_blue` = el config crudo de `persist_batch:343-351` (ver DIV-138). `usd_amount` = face value.

**M2 — manual** (`main.py:10870-11005`, `POST /api/conversions`): mueve el cash con `_adjust_cash`, actualiza el `tc_compra` promedio del cash USD, inserta una fila en `operations`, y para `usd_to_ars` llama a `_update_monthly_pnl_realized`. **No toca `monthly_entries.deposits/withdrawals`.**

**M3 — asimetría interna de M1**: en `_persist_fx`, la rama `usd_to_ars` (`persister.py:1146-1176`) **tampoco** llama a `_update_monthly_flow`. Sólo `_update_monthly_pnl_realized`. O sea que dentro del importador, comprar dólares mueve el capital aportado y venderlos no lo devuelve.

#### b. Fórmulas

Conversión de `A` pesos a `U` dólares al TC efectivo `T = A/U` (el que el usuario realmente pagó, típicamente el MEP):

- **M1**: `Δcapital = U − A/blue_config = U − U·T/blue_config = U·(1 − T/blue_config)`
- **M2**: `Δcapital = 0`
- **Correcto**: `Δcapital = 0` **y** la base debe re-anclarse a la moneda destino (que es lo que M1 intenta y erra el rate).

#### c. ¿Real o cosmética? — **REAL**

Usuario convierte 10.000.000 ARS al MEP 1.518,43 → recibe **US$6.585,72**.

| camino | pata ARS (withdraw) | pata USD (deposit) | Δ capital aportado |
|---|---|---|---|
| M1 (import), `tc_blue` = blue live 1.575 | −US$6.349,21 | +US$6.585,72 | **+US$236,51** |
| M1 (import), `tc_blue` = config 1415 | −US$7.067,14 | +US$6.585,72 | **−US$481,42** |
| M2 (manual, `POST /api/conversions`) | — | — | **0** |
| Correcto (ambas al MEP 1.518,43) | −US$6.585,72 | +US$6.585,72 | 0 |

Con el config stale el signo se **invierte**: el mismo hecho de negocio destruye US$481 de capital aportado en vez de crear US$236. Un usuario que convierte pesos a dólares todos los meses acumula el error linealmente en el denominador de su rendimiento.

El comentario del propio código (`persister.py:1128-1135`) dice: "el criterio: valuar el capital a la MISMA tasa que las tenencias (ARS→blue, USD→face), así una conversión no inventa ni P&L ni capital nuevo". **La premisa "las tenencias en pesos se valúan al blue" es falsa desde la unificación FX de 2026-06** (`valuation.js:626-637`: "el cash en pesos → USD por el dólar-MEP (cedearRate) … Antes iba al blue y quedaba inconsistente"). El fix es correcto sobre una premisa que ya no vale.

#### d. Dictamen

**Ninguna de las dos es correcta.** La fórmula correcta:

```
withdraw(broker_ARS) = A / T          # T = tx.unit_price, el TC efectivo de la conversión
deposit(broker_USD)  = U             # = A / T por construcción
Δ capital aportado   = 0             # exactamente cero, por identidad
```

y **simétricamente** para `usd_to_ars`: `withdraw(USD) = U`, `deposit(ARS) = U` (el mismo número, porque el capital no cambia de tamaño, sólo de moneda). El TC correcto es `tx.unit_price` / `data.tc` — el TC que el usuario realmente obtuvo, que ya está en la fila y que ninguna de las dos implementaciones usa para esto.

M2 (`POST /api/conversions`) debe escribir el par; hoy no escribe nada, así que la base de capital se queda anclada al peso mientras la plata ya está en dólares.

#### e. Qué ve mal el usuario y dónde

- **`/dashboard`** — "Capital Aportado" y el "Rendimiento total" (que lo tiene de denominador).
- **`/analisis`** — todas las series que arrancan de `net_deposited`.
- **`/posiciones`** → botón "Comprar/Vender USD" (`POST /api/conversions`): el usuario ve el cash moverse y el capital aportado **no** moverse. Después importa el mismo mes desde el CSV del broker y el capital aportado **sí** se mueve. Mismo hecho, dos números.

#### f. Causa raíz

**Falta de una capa compartida.** Dos implementaciones completas del mismo hecho de negocio (`persister._persist_fx` y `main.create_conversion`) que comparten el modelo de datos y ninguna línea de código. La divergencia dentro de M1 (`ars_to_usd` escribe, `usd_to_ars` no) muestra que ni siquiera hubo un criterio explícito.

#### g. Fuente única de verdad propuesta

Un módulo `backend/conversions.py` con `aplicar_conversion(conn, uid, *, broker_ars, broker_usd, ars, usd, tc, fecha, direccion)` que haga las cuatro cosas (cash, `tc_compra` promedio, `operations`, `monthly_entries`) en una transacción. `create_conversion` y `_persist_fx` pasan a ser adaptadores de 10 líneas. Es el mismo patrón que `reporting/builder.py:645-653` ya aplica bien al importar `_leg_en_moneda` del motor (ver DIV-144).

---

### DIV-141 — `tc_venta = data.tc_venta or 1` en cuentas v1

**Estado de las citas:** ✅ `main.py:11282-11286` exacto (dentro de `POST /api/positions/sell`, `@app.post` en **11147**). ✅ `Positions.jsx:866` exacto (el mapa lo escribe `Positions.js`; el archivo es `.jsx`).

#### a. Implementaciones

**V1/V2 — `POST /api/positions/sell`** (`main.py:11282-11286`, verificado literal):
```python
                        if _fx.fx_version(conn, uid) == _fx.FX_V2:
                            tc_venta = data.tc_venta or _fx.fx_for_date(
                                conn, op_date, fallback=_user_tc_blue(conn, uid)) or 1
                        else:
                            tc_venta = data.tc_venta or 1
```

**V3 — el chat de la IA** (`main.py:24157-24166`, verificado) — **tercera** implementación, que el mapa no lista:
```python
            if currency == "ARS":
                if _fx.fx_version(conn, uid) == _fx.FX_V2 and not date_is_today:
                    tc_venta = (_fx.fx_for_date(conn, date)
                                or _current_cedear_rate() or _user_tc_blue(conn, uid))
                else:
                    tc_venta = _current_cedear_rate() or _user_tc_blue(conn, uid)
```
El chat **nunca** cae a 1 (siempre resuelve un rate) — es la implementación más segura de las tres, y es distinta de las otras dos.

**Frontend:** `Positions.jsx:883` y `PositionsMobile.jsx:340` sólo incluyen `tc_venta` en el body cuando `sellForm.currency === 'ARS' && sellForm.tc_venta` (verificado). Con el prefill de `Positions.jsx:866` (`tc_venta: isARS ? +tcValuacion.toFixed(2) : ''`), en la práctica siempre viaja un número en ventas ARS.

#### b. Fórmulas

`pnl_usd = (exit_price × qty − invested − commissions) / tc_venta` (`main.py:11289-11291`).
- v2: `tc_venta = cliente ?? MEP(fecha) ?? config.tc_blue ?? 1`
- v1: `tc_venta = cliente ?? **1**`
- chat: `tc_venta = MEP(fecha) ?? MEP_vivo ?? config.tc_blue` (nunca 1)

#### c. ¿Real o cosmética? — **REAL**

**Riesgo A (el que el mapa nombra):** cliente v1 que no mande `tc_venta` → `pnl_usd` guarda **pesos**. Una ganancia de 1.000.000 ARS se persiste como `pnl_usd = 1.000.000` en vez de US$658,58: **1.518× inflado**, y queda escrito en `operations` para siempre (`/operaciones`, `/analisis` P&L realizado, y el "P&L realizado" del rendimiento). Hoy sólo lo alcanza un cliente viejo o un script; el frontend actual lo tapa.

**Riesgo B — este SÍ está vivo hoy, y el mapa no lo tiene.** El modal de venta (`SellModal`, `Positions.jsx:3742`) ajusta `tc_venta` a la fecha elegida:
```js
  function tcForDate(v) {
    const hoy = new Date().toISOString().slice(0, 10)
    if (!v || v >= hoy) return tcValuacion
    return (fxHist?.getMepOrFallback?.(v)) || tcValuacion
  }
```
El desktop le pasa `fxHist` (`Positions.jsx:245` crea el hook). **`PositionsMobile.jsx:1642-1650` renderiza el MISMO `SellModal` y NO le pasa `fxHist`:**
```jsx
        <SellModal
          form={sellForm}
          setForm={setSellForm}
          positions={positions}
          tcValuacion={pickFinancialRate(dolar, valuationDollar) || 1415}
          onClose={...} onConfirm={...}
        />
```
→ `fxHist?.getMepOrFallback?.(v)` es `undefined` → cae a `|| tcValuacion` = **el MEP de hoy**. Una venta retroactiva en pesos cargada desde el celular se dolariza con el dólar de hoy, aunque el usuario elija la fecha correcta.

Ejemplo: venta de 2023 con 500.000 ARS de ganancia. MEP de la fecha ≈ 480 → US$1.041,67. Desde mobile: 500.000 / 1.518,43 = **US$329,29**. **68 % de P&L realizado perdido**, sin ningún aviso.

#### d. Dictamen

**La correcta es la rama v2 con la mejora del chat**: nunca caer a 1, y para una venta de HOY preferir el MEP vivo sobre el último cierre de la serie (que el cron escribe a las 3 AM y suele estar un día atrás), que es exactamente lo que hace `main.py:24162-24166`.

El `or 1` de la rama v1 debe eliminarse: `fx_version == v1` significa "no reescribir el histórico", no "guardar pesos en una columna que dice USD". Un `raise HTTPException(400, "Falta el tipo de cambio de la venta")` es infinitamente mejor que un factor 1.

`PositionsMobile` debe pasar `fxHist`.

#### e. Qué ve mal el usuario y dónde

- **`/posiciones` en mobile** → vender en pesos con fecha pasada: el P&L en dólares de esa operación queda mal para siempre (queda en `operations.pnl_usd`).
- **`/operaciones`**, **`/analisis`** (P&L realizado, "mejores/peores operaciones"), y el rendimiento total: todos leen esa columna.
- **`POST /api/positions/sell`** (`main.py:11147`) es el endpoint.

#### f. Causa raíz

**Parche que funciona por accidente + fix aplicado en un solo cliente.** El `or 1` sobrevive porque el frontend siempre manda el campo — el comentario del propio código lo admite ("el `or 1` hacía que se dividiera por 1: correcto por accidente", `main.py:11265-11266`). Y `tcForDate` se agregó a `SellModal` sin revisar que el segundo caller del componente no le pasaba la dependencia — una prop opcional con `?.` que degrada en silencio.

#### g. Fuente única de verdad propuesta

Un helper `_tc_venta(conn, uid, fecha, tc_cliente)` en `main.py`, llamado por `/positions/sell` y por el chat, sin rama `or 1`. En el frontend, `SellModal` debe **exigir** `fxHist` (o crear el hook adentro) en vez de aceptar `undefined`.

---

### DIV-142 — `positions.tc_compra` significa dos cosas

**Estado de las citas:** ⚠️ una corregida.
- `frontend/src/utils/valuation.js:268` ⚠️ **corregida**: `costBasisRate` se define en **263** y su `return` está en **268**. La cita apunta a la línea del return, no a la función.
- `main.py:10864-10866` ⚠️ **corregida**: 10864-10866 es el `INSERT INTO positions (… tc_compra)` del else. El **promedio ponderado** que el mapa describe está en `main.py:10844-10852` (dentro de `_adjust_cash`, def en **10818**).
- `main.py:10939` ✅ exacto (`tc_avg = (cash_usd['tc_compra'] if cash_usd else None) or data.tc`).
- `persister.py:1167` ✅ exacto (misma línea, versión del importador).

#### a. Implementaciones

**Uso A — lote (`is_cash = 0`)**: `tc_compra` = el TC de la compra del lote en pesos. Escrito por `main.py:8227-8229` (`tc_compra = _fx.fx_for_date(conn, entry_date)` con guard `not p.is_cash`) y por el importador. Leído por `costBasisRate` (`valuation.js:263-269`) para la vista "Costo en dólares".

**Uso B — cash USD (`is_cash = 1`)**: `tc_compra` = promedio ponderado del TC al que el usuario compró los dólares que hay en la caja del sub-broker `· USD`. Escrito por `_adjust_cash` (`main.py:10844-10852`) y `_adjust_cash_permissive` (`persister.py:~1075`). Leído como cost basis del P&L cambiario en `main.py:10939` y `persister.py:1167`.

#### b. Fórmulas

- A: `costo_usd = invested / tc_compra` (modo `purchase`).
- B: `tc_compra_nuevo = (saldo_prev × tc_compra_prev + delta × tc_operación) / saldo_nuevo`; luego `cost_basis_ars = usd_vendidos × tc_compra`.

Son dimensionalmente iguales (ARS/USD) y semánticamente incompatibles: A es un dato de una compra puntual, B es un promedio móvil que se recalcula en cada operación.

#### c. ¿Real o cosmética? — **NO difieren hoy; es un riesgo estructural**

Verifiqué todos los lectores y **cada uno guarda `is_cash` de alguna forma**:

| lector | guard | resultado |
|---|---|---|
| `valuation.js` ramas 574, 650 | `!p.is_cash` explícito | ✅ |
| `valuation.js:626-637`, `675-679` | ramas dedicadas a cash, no llaman `costBasisRate` | ✅ |
| `main.py:12747` (`/api/movements`) | `AND p.is_cash = 0` en el SQL | ✅ |
| `main.py:8228`, `8558` | `and not p.is_cash` | ✅ |
| `lotMissingPurchaseRate` (`valuation.js:286`) | `if (p?.is_cash) return false` | ✅ |

Los que **no** guardan (`DetailPortfolioBlocks.jsx:39`, `PositionsMobile.jsx:782-783`, `PositionDetailMobile.jsx:148,187`, `Positions.jsx:1251-1253`) están protegidos por otro camino: el uso B sólo escribe `tc_compra` en la fila cash del sub-broker `· USD`, cuya `currency` queda NULL (el `INSERT` de `main.py:10864-10866` no la nombra) → `costInPesos(p)` es false (`valuation.js`: exige `currency === 'ARS'`) y el broker no es ARS → nunca entra a la rama que divide.

O sea: **el sistema no rompe porque la fila cash del uso B tiene `currency` NULL por omisión**. Eso no es un invariante: es una coincidencia. El día que alguien estampe `currency='USD'` en esa fila (cosa razonable y que ya se hace en otras filas cash: `asset_name = 'ARS' if currency == 'ARS' else ...`, `main.py:10075`), `costInUsd(p)` pasa a true y algunas de esas cinco ramas cambian de comportamiento.

#### d. Dictamen

**Ninguna implementación está mal; el ESQUEMA está mal.** La columna debe partirse:
- `positions.tc_compra` → sólo lotes (`is_cash = 0`), con un `CHECK (is_cash = 0 OR tc_compra IS NULL)`.
- `positions.tc_cash_avg` → sólo cash (`is_cash = 1`).

Mientras tanto, el guard mínimo es agregar `if (p?.is_cash) return currentRate` dentro de `costBasisRate` (`valuation.js:263`), que convierte cinco guards implícitos en uno explícito.

#### e. Qué ve mal el usuario y dónde

**Ninguno hoy.** El valor de la divergencia es preventivo.

#### f. Causa raíz

**Sobrecarga de esquema.** Se reusó una columna existente (`tc_compra`) para un concepto nuevo (cost basis del cash en dólares) en vez de agregar una. El comentario de `_adjust_cash` (`main.py:10823-10829`) documenta el uso B sin mencionar que la columna ya tenía dueño.

#### g. Fuente única de verdad propuesta

Migración de esquema con `tc_cash_avg`. Un test que verifique `SELECT COUNT(*) FROM positions WHERE is_cash=1 AND tc_compra IS NOT NULL` = 0 después de la migración.

---

### DIV-143 — Con la preferencia en CCL, frontend y backend valúan a dólares distintos

**Estado de las citas:** ✅ `CurrencyContext.jsx:53` (dentro de `pickFinancialRate`, def en 46). ✅ `main.py:4939-4954` (`_current_cedear_rate`, def en **4939**, cascada `mep→ccl→cripto` en 4949-4953). ✅ `HomeMobile.jsx:119-125` exacto (el comentario 119-124 + `const tcMep = pickFinancialRate(dolar, 'mep') || tcValuacion` en **125**). El mapa escribe `.js`; los archivos son `.jsx`.

#### a. Implementaciones

**F — frontend** (`CurrencyContext.jsx:46-54`):
```js
export function pickFinancialRate(dolar, pref) {
  const rate = c => c?.medio ?? c?.venta
  const mep = rate(dolar?.mep), ccl = rate(dolar?.ccl), blue = rate(dolar?.blue)
  return (pref === 'ccl' ? (ccl || mep) : (mep || ccl)) || blue
}
```
`pref` = `valuationDollar`, que vive **sólo en `localStorage`** (`CurrencyContext.jsx:69-76, 152-156`). Verificado con grep: `valuationDollar` no aparece en ningún body de request ni query param.

**B — backend** (`main.py:4939-4955`):
```python
def _current_cedear_rate():
    for casa in ("mep", "ccl", "cripto"):
        v = _val_rate(cached.get(casa))
        if v: return v
```
Cascada **fija** `mep→ccl→cripto`. No hay parámetro de preferencia. Lo consumen `snapshots_job` (vía `_get_mep_for_scheduler`), `analysis_prep.user_fx`, `advisor_brief._fx`, `_live_valuation_rate`, `_autodeposit_rate`, `behavioral`.

**P — el parche** (`HomeMobile.jsx:119-131`):
```js
  const tcMep = pickFinancialRate(dolar, 'mep') || tcValuacion
  const totalsMep = useMemo(() => {
    if (tcMep === tcCedear) return null
    const bt = brokers.map(b => ({ ...b, ...computeBrokerValue(positions, prices, b, tcMep, tcMep, tcCripto, costBasis) }))
    return { totalValue: bt.reduce((s, b) => s + b.value, 0) }
  }, [...])
  const compareValue = totalsMep ? totalsMep.totalValue : totals.totalValue
```
Verificado con grep: **`HomeMobile.jsx:125` es el único sitio en todo el frontend que llama `pickFinancialRate(dolar, 'mep')` con el literal**. `Dashboard.jsx:192-193`, `Positions.jsx:241`, `Insights.jsx:404-405`, `PositionsMobile.jsx:629-630`, `AssetDetail.jsx:151-152`, `Goals.jsx:66-68`, `Events.jsx:149-150`, `FirstInsight.jsx:84-85`, `PositionDetailMobile.jsx:97-98` usan todos `valuationDollar`.

#### b. Fórmulas

Para una cartera con `V_ars` en tenencias .BA:
- Cartera / Dashboard (F, `pref = 'ccl'`): `V_usd = V_ars / CCL`
- Snapshot de esa noche (B): `V_usd = V_ars / MEP`
- Home mobile (P): muestra `V_ars / CCL` pero compara contra el snapshot con `V_ars / MEP`.

#### c. ¿Real o cosmética? — **REAL** (sólo para usuarios con la preferencia en CCL)

Brecha CCL/MEP típica 1–3 %. Con MEP medio 1.518,43 y CCL medio 1.560 (2,74 %), cartera de 50.000.000 ARS en CEDEARs:

| | rate | valor |
|---|---|---|
| `/posiciones` (preferencia CCL) | 1.560 | **US$32.051,28** |
| Snapshot de esa noche | 1.518,43 | **US$32.928,81** |
| Diferencia | | **US$877,53 (2,74 %)** |

A la mañana siguiente, `/dashboard` compara el valor vivo (CCL) contra el snapshot (MEP) y publica **−2,74 % de "P&L Día"** con la cartera intacta. Ese es exactamente el bug que `HomeMobile.jsx:119-124` documenta y arregla — **en una sola pantalla**.

Además, la serie de snapshots del usuario CCL queda permanentemente en una base distinta de la que ve en Cartera: todo `/analisis` y `/analisis?tab=reportes` (que leen snapshots) hablan MEP mientras la Cartera habla CCL.

#### d. Dictamen

**Ninguna es correcta, porque el problema no es la fórmula sino la arquitectura**: una preferencia de valuación que cambia el número que se compara contra una serie persistida **no puede vivir sólo en `localStorage`**.

Dos soluciones válidas, en orden de preferencia:
1. **Persistir `valuation_dollar` en `config`** (como ya se hace con `tc_mep`/`tc_blue`) y hacer que `_current_cedear_rate` acepte `uid` y respete la preferencia. La serie de snapshots pasa a estar en el riel del usuario. Requiere recomputar snapshots al cambiar la preferencia (o aceptar el escalón, declarándolo).
2. **Declarar el MEP como el riel canónico de la SERIE** (que es lo que ya es de hecho) y generalizar el parche de `HomeMobile`: el CCL gobierna sólo el DISPLAY; toda comparación contra snapshots va anclada al MEP. Es más barato y no toca el backend.

La opción 2 es lo que el comentario de `HomeMobile.jsx:119-124` ya razonó bien; el error fue no llevarlo a las otras cuatro pantallas.

#### e. Qué ve mal el usuario y dónde

Sólo usuarios con "Dólar de valuación = CCL" en `/config`:
- **`/posiciones`**: el total de la Cartera difiere del snapshot de esa noche.
- **`/dashboard`**: "P&L Día" / "P&L Mes" con un desvío del tamaño de la brecha CCL/MEP, todos los días, con la cartera quieta. **`Dashboard.jsx:192-193` no tiene el parche.**
- **`/analisis`**: las series de snapshots y el valor vivo están en rieles distintos.
- **`/`** (home mobile): correcto — es el único.

#### f. Causa raíz

**Parche puntual.** El fix existe, está bien razonado, está comentado, y se aplicó a una pantalla. La causa de fondo es *frontend recalculando lo que el backend ya calculó*: el frontend tiene una preferencia que el backend no puede conocer, y ambos valúan la misma cartera.

#### g. Fuente única de verdad propuesta

Un helper compartido `useTcComparacion()` que devuelva siempre el MEP (el riel de la serie) junto a `tcValuacion` (el riel de display), y una regla explícita: *`tcValuacion` para mostrar, `tcComparacion` para comparar contra snapshots*. Aplicado en `Dashboard`, `Positions`, `PositionsMobile`, `Insights`. Idealmente, mover `valuation_dollar` a `config` para que el backend pueda alinearse.

---

### DIV-144 — Convergencias verificadas

**Estado de las citas:** ✅ 5 de 5 verificadas.

| convergencia | cita del mapa | verificación |
|---|---|---|
| `crypto_broker_factor` ↔ `cryptoBrokerFactor` | `main.py:7096-7113` / `crypto.js:47-53` | ✅ `def crypto_broker_factor` en **main.py:7096**; `export function cryptoBrokerFactor` en **crypto.js:47**. Espejos exactos, mismo orden de guards, misma división `cripto/mep`. |
| `_leg_en_moneda` importado, no reimplementado | `reporting/builder.py:639-641` | ✅ `builder.py:644-653`: `import twr as _twr_fx; _fxfn, _ = _twr_fx.serie_fx(...); _twr_fx._leg_en_moneda(...)`. El comentario 639-641 lo declara y el código lo cumple. |
| `computeBrokerValue` ↔ `compute_broker_value_usd` | `snapshots_job.py:166` | ✅ `def compute_broker_value_usd` en **158**, docstring "Equivalente Python de frontend `computeBrokerValue` (port fiel…)" en **166-168**. |
| `_val_rate` ↔ `pickFinancialRate` leen `medio` | `tests/test_dolar_medio.py:9-11` | ✅ verificado: "`_val_rate` es la SSoT de esa tasa … La regla de oro es que frontend (`pickFinancialRate`) y backend (`_current_*`) lean el MISMO campo". **Nota: la regla se cumple entre `_val_rate` y `pickFinancialRate`, pero NO la cumplen `_display_blue`, `_get_blue_for_scheduler` ni la rama fría de `_get_mep_for_scheduler` — ver DIV-137.** El test fija la SSoT, no cubre a los tres desertores. |
| `realized_usd_sql` en un solo lugar | `realized_pnl.py:98-107` | ✅ `def realized_usd_sql` en **97**, cuerpo 99-107. |

**Veredicto:** las cinco son convergencias reales. La cuarta merece un asterisco: el test protege la SSoT pero no impide que existan tres lectores que no pasan por ella.

**Sugerencia:** el patrón de `reporting/builder.py` (importar la función del motor en vez de reimplementarla, con un comentario que explica por qué) es el que hay que replicar en DIV-135 (`serie_fx` debería importar `fx.py`) y DIV-140 (las dos conversiones deberían compartir módulo).

---

## Divergencias adicionales encontradas (no listadas en el mapa)

| # | hallazgo | evidencia | severidad |
|---|---|---|---|
| **X-1** | **`fx_rates_daily` guarda punta VENTA; la valuación viva usa MEDIO.** `blue_venta` viene de `_fetch_dolar("blue")["venta"]` (`snapshots_job.py:987` vía `main.py:32011`) y de argentinadatos `item["venta"]` (`main.py:4770`); `mep_venta` de `_dolar_cache["mep"]["venta"]` (`main.py:5033`) y de argentinadatos `/bolsa` `venta` (`main.py:4818`). Toda la serie está en la punta cara mientras `_val_rate` valúa al medio → 0,74 % de escalón sistemático entre "hoy" y "la serie". | `main.py:4770, 4818, 5031-5033`, `snapshots_job.py:978-988` | 🟠 |
| **X-2** | **`PositionsMobile` no le pasa `fxHist` a `SellModal`** → venta retroactiva en pesos desde mobile se dolariza al MEP de hoy. Detalle completo en DIV-141.c. | `PositionsMobile.jsx:1642-1650` vs `Positions.jsx:245, 3760-3776` | 🟠 |
| **X-3** | **`_autodeposit_rate` es una cuarta forma de dolarizar un aporte**: `fx_for_date(conn, fecha, fallback=_current_cedear_rate())` — mezcla la serie (punta) con el vivo (medio) en la misma expresión. | `main.py:9840-9851` | 🟡 |
| **X-4** | **`main.py:17204`: `"usd_hoy": round(gross_amount / 1415.0, 2)`** — un 1415 literal, sin variable, en un endpoint de diagnóstico del migrador FX. Si alguien usa ese número para decidir una migración, decide sobre una ficción. | `main.py:17204` | 🟡 |
| **X-5** | `GET /api/fx-rates` (`main.py:5178-5197`) hace `ORDER BY date DESC LIMIT ?` con `days`: devuelve las últimas N **filas**, no los últimos N **días**. Con huecos en la serie, la ventana real es más larga que la pedida. Benigno hoy (el frontend pide 3650 = el cap), pero es una trampa. | `main.py:5185-5189` | ⚪ |

---

## Parches detectados

| ubicación | qué síntoma tapa | causa real | dónde más sigue rompiendo |
|---|---|---|---|
| `main.py:36836-36840` (`_advisor_book_fx`, 2ª query "última fila CON mep") | El libro del asesor valuado al blue todo fin de semana | `snapshots_job.py:978-988` no escribe `mep_venta`, teniendo `tc_mep` en scope | `advisor_brief.py:180-184` (copia), `useFxHistory.js:189-197` (3ª copia), `main.py:35723-35726` (4ª). Y `fx.py:59-73` ya resolvió el problema bien: nadie lo usa |
| `HomeMobile.jsx:125-131` (`tcMep` + `compareValue`) | "P&L Día" fantasma del tamaño de la brecha CCL/MEP | `valuationDollar` vive en `localStorage` y el backend valúa siempre en MEP | `Dashboard.jsx:192-193`, `Positions.jsx:241`, `Insights.jsx:404-405`, `PositionsMobile.jsx:629-630` — las cuatro pantallas grandes siguen rotas |
| `main.py:11286` (`else: tc_venta = data.tc_venta or 1`) | Que una venta ARS sin `tc_venta` explote por división por cero | No hay validación de que una venta en pesos traiga su TC; el frontend siempre lo manda "por casualidad" (el propio código lo llama "correcto por accidente", `main.py:11265-11266`) | Cualquier cliente que no sea el frontend actual: el chat de la IA (que tiene su propia versión, `main.py:24157`), clientes móviles viejos, scripts |
| `main.py:10020` / `main.py:9385` (`tc_blue: float = Field(1415, ...)`) | Que un request sin `tc_blue` falle con 422 | El TC no debería venir del cliente en absoluto | `reconcile-cash` corre **siempre** con 1415 porque su único caller no manda el campo (`ImportWizard.jsx:2721`). El default silencioso es lo que hace que nadie se entere |
| `persister.py:1136-1143` (el "FIX bug #1" del FX) | Capital aportado subvaluado tras una conversión ARS→USD | Las dos patas de una conversión deben ir al TC de la conversión (`tx.unit_price`), no una al blue y la otra a face | La rama `usd_to_ars` de la misma función no escribe nada; `POST /api/conversions` tampoco. El parche corrige un tercio del problema y, con `tc_blue` stale, **invierte el signo del error** |
| `_apply_cash_flow:1063-1065` (preferir `tx.gross_amount_usd` sobre la conversión runtime) | Drift entre el preview y el persist | `persist_batch` resuelve **un** TC para todo el batch en vez de uno por fila | `_persist_fx:1139` y `_persist_sell_fifo:762,772` **no** consultan el stamp: el `tc_blue` stale entra sin mitigante |
| `evolution.js:163` (`const safeFx = (fx && fx > 0) ? fx : 1`) | NaN en el gráfico cuando no hay FX | La serie en pesos no debería existir sin FX | Con `safeFx = 1`, un punto sin FX se dibuja **en dólares dentro de una curva en pesos** — 1.518× abajo, un pozo vertical que parece una pérdida catastrófica |

---

## Citas del mapa incorrectas

| DIV | cita del mapa | ubicación real | qué decía mal |
|---|---|---|---|
| **todas** | `frontend/src/contexts/CurrencyContext.js`, `frontend/src/pages/Insights.js`, `frontend/src/pages/HomeMobile.js`, `frontend/src/pages/Positions.js` | `.jsx` en los cuatro casos | Error **sistemático** en la columna "sitios": ningún archivo `.js` de esos existe. La columna en prosa sí usa `.jsx` |
| DIV-136 | `useFxHistory.js:169-176` | `useFxHistory.js:177-199` | 169-176 es el bloque de comentario; `getMepDetail` empieza en 177 |
| DIV-136 | "`advisor_brief.py:164-165` (copia del anterior)" | `advisor_brief.py:160-185` | **Refutado por el código.** `_fx` tiene una rama previa (`main._current_cedear_rate()`, MEP **medio vivo**) que `_advisor_book_fx` no tiene. No son copias: dan MEPs distintos (0,74 % de brecha) sobre el mismo libro. Es una divergencia REAL que el mapa clasificó como redundancia |
| DIV-137 | `main.py:32024-32032` | docstring 32017-32024; rama medio 32025-32027; **rama punta-venta 32031-32034** | El `return float(d["venta"])` —el punto de la divergencia— está en 32034, fuera del rango citado |
| DIV-142 | `main.py:10864-10866` ("escrito") | `main.py:10844-10852` | 10864-10866 es el `INSERT` del caso "no existe la fila"; el **promedio ponderado** que el mapa describe está en 10844-10852 |
| DIV-142 | `frontend/src/utils/valuation.js:268` | def en 263, return en 268 | Apunta al return, no a la función |
| DIV-139 | "Dos maneras de dolarizar un movimiento de caja manual" | tres: `main.py:10196`, `main.py:10100`, `main.py:10240` | Falta `_revert_cash_flow` (`main.py:10218-10248`), que usa el TC del navegador teniendo la fecha a mano |
| DIV-141 | "Dos" (v1 / v2) | tres: `main.py:11282-11286` + `main.py:24157-24166` | Falta la implementación del chat de la IA, que es distinta de las dos y **nunca cae a 1** |
| DIV-140 | "la conversión MANUAL … no llama a `_update_monthly_flow` en absoluto" | ✅ correcto | Falta agregar que **la rama `usd_to_ars` del importador tampoco** (`persister.py:1146-1176`): la asimetría existe también dentro de M1 |

---

## URGENTE

**U-1 — `POST /api/brokers/reconcile-cash` escribe capital aportado dividiendo por 1415 literal.**

- `main.py:10020`: `tc_blue: float = Field(1415, gt=0, le=1_000_000)`
- `main.py:10100`: `amount_usd = magnitude / data.tc_blue if currency == 'ARS' else magnitude`
- `ImportWizard.jsx:2718-2721`: el **único** caller de la app, y no manda `tc_blue`.

O sea: **en producción, ese endpoint siempre divide por 1415**, sin importar el dólar real. El resultado va a `monthly_entries.deposits/withdrawals` (`main.py:10102-10105`), que es el **capital aportado**, o sea el **denominador del rendimiento**, y se bookea en el mes más antiguo del broker — donde queda invisible.

Con el MEP en ~1.518 el error es **+7,3 % de capital aportado por cada reconciliación de caja de un broker ARS**, y se acumula por broker. Es dinero fantasma permanente en el denominador de todo lo que la app llama "rendimiento", y crece cada vez que el dólar se aleja de 1415. El fix es de una línea (`_fx.fx_for_date`), pero **no lo apliqué: la auditoría no toca código.**

Riesgo colateral a considerar antes de arreglarlo: cambiar el rate cambia los números ya publicados de quien haya usado esa función, así que necesita el mismo tratamiento por-cuenta que tuvo la migración FX v1→v2 (`fx.py:100-135`).

**U-2 — `PositionsMobile` deforma el P&L de ventas retroactivas en pesos.** `PositionsMobile.jsx:1642-1650` renderiza `SellModal` sin la prop `fxHist`, así que `tcForDate` (`Positions.jsx:3760-3765`) degrada en silencio al MEP de hoy. Una venta de 2023 cargada desde el celular puede quedar con 68 % menos de P&L realizado, escrito en `operations` para siempre. Es una prop faltante (dos líneas) y no requiere migración de datos, pero sí un backfill para las ventas ya cargadas desde mobile.

---

## BLOQUE-RESUMEN

| concepto | DIV | versiones | difieren | correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---|---:|---|---|---|---|---|
| Tipo de cambio y conversión de moneda | DIV-134 | 3 | Sí (3,7 % con brecha actual; hasta 15 % histórica) | Ninguna: convertir con el mismo riel con que se dolarizó (MEP de la fecha) | `/dashboard` curva Evolución en Pesos vs. hero; `/` home mobile; `/operaciones` | 🔴 | Migración a medio hacer (`fx_to_usd_blue` es de cuando se valuaba al blue) |
| Tipo de cambio y conversión de moneda | DIV-135 | 6 | Sí (4,1 pp entre `/analisis` y Reportes sobre la misma cartera quieta) | `twr.serie_fx` / `fx.fx_for_date` (MEP diario con red al blue) | `/analisis` gráfico Evolución y cards Comparativa; `/mensual` tabs ARS | 🔴 | Falta de capa compartida; `fx.py` existe y ninguna de las otras 5 series lo importa |
| Tipo de cambio y conversión de moneda | DIV-136 | 5 lectores + 1 escritor | Sí (0,74 % entre el libro del asesor y su propio brief diario) | `fx.py._lookup` para histórico + `_val_rate` medio vivo para hoy | `/clientes` (libro del asesor) vs. brief diario por email | 🟠 | Fix aplicado en un lugar y copiado a mano 3 veces; `mep_venta` NULLABLE con un escritor que no la escribe |
| Tipo de cambio y conversión de moneda | DIV-137 | 5 | Sí (0,74 % medio-vs-punta; 11,3 % en el importador con caché frío) | `_val_rate` (medio con fallback a venta) | Importador (Capital Aportado); `/analisis?tab=reportes` con caché frío; snapshot nocturno frío | 🟠 | Copy-paste + fix parcial: la SSoT se aplicó a 3 funciones y quedaron 3 leyendo `venta` |
| Tipo de cambio y conversión de moneda | DIV-138 | 2 (mismo archivo) | Sí (mismo import, dos dólares; hasta 10× con config stale) | Ninguna: `fx.fx_for_date` por fila, no un TC por batch | `/dashboard` "Capital Aportado" tras importar; `/operaciones` P&L de ventas ARS v1 | 🔴 | Fix aplicado en un solo lugar: `_read_tc_blue` existe 950 líneas abajo y `persist_batch` no lo llama |
| Tipo de cambio y conversión de moneda | DIV-139 | 3 | Sí (`reconcile-cash` divide por 1415 literal: +7,3 % de aportado) | `fx_for_date(conn, fecha_del_asiento)` (la de `/cash/flow`) | Asistente de import → "Reconciliar caja"; deshacer transferencia | 🔴 | Migración a medio hacer + default de Pydantic que oculta un caller incompleto |
| Tipo de cambio y conversión de moneda | DIV-140 | 2 (+1 asimetría interna) | Sí (import crea +US$236 por conversión de 10 M ARS; manual escribe 0) | Ninguna: ambas patas al TC de la conversión (`tx.unit_price`), Δcapital = 0, simétrico en ambas direcciones | `/dashboard` y `/analisis` "Capital Aportado" y rendimiento total | 🔴 | Falta de capa compartida: dos implementaciones completas del mismo hecho, cero código en común |
| Tipo de cambio y conversión de moneda | DIV-141 | 3 | Sí (`or 1` = 1.518× en v1; mobile pierde 68 % del P&L en ventas retroactivas) | La rama v2 con la mejora del chat (nunca caer a 1; MEP vivo para hoy) | `/posiciones` mobile (venta ARS con fecha pasada); `/operaciones`; `/analisis` P&L realizado | 🟠 | Parche que funciona por accidente + prop opcional que degrada en silencio en el 2º caller |
| Tipo de cambio y conversión de moneda | DIV-142 | 2 significados / 1 columna | No hoy (todos los lectores guardan `is_cash`), sí estructuralmente | Partir la columna: `tc_compra` (lote) vs. `tc_cash_avg` (cash USD) | Ninguna hoy | 🟡 | Sobrecarga de esquema: se reusó una columna para un concepto nuevo |
| Tipo de cambio y conversión de moneda | DIV-143 | 2 | Sí con preferencia CCL (2,7 %: Cartera vs. snapshot de esa noche) | Ninguna: la preferencia debe viajar al backend, o anclar toda comparación al MEP | `/posiciones`, `/dashboard` (P&L Día fantasma), `/analisis`; parcheado SOLO en `/` home mobile | 🟠 | Parche puntual: el fix existe, está comentado, y se aplicó a 1 de 5 pantallas |
| Tipo de cambio y conversión de moneda | DIV-144 | — | No (convergencias reales, 5/5 verificadas) | (n/a) | (ninguna) | ⚪ | (n/a) |
