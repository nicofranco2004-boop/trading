# 1B — Monedas y cotizaciones

**Commit auditado:** `b74f450f2badf1a2b84e657551115a0595110e45` (`/tmp/rendi-main`) · verificado: `wc -l backend/main.py` = **38.029** ✅
**Alcance:** lo que 1A NO cubrió. Todo lo que 1A ya dictaminó (DIV-134…DIV-144 + X-1…X-5) queda fuera; donde mi lectura toca algo suyo lo digo y no lo re-cuento como hallazgo nuevo.
**Deriva `82fad6a0`:** ninguno de mis hallazgos cae en `backend/pricing/fci.py`, `frontend/src/components/AddPositionFlow.jsx` ni `backend/tests/test_fci_uala.py`. **`snapshots_job.py`** (rama `fix/snapshots-valuacion`) aparece en M-02/M-03 → marcados ⚠️ **zona de trabajo activa**.

---

## Método

**Qué ejecuté** (todo fuera de `/tmp/rendi-main`; ver nota de higiene al final):

1. **Python sobre una COPIA del backend** en el scratchpad (`cp -R /tmp/rendi-main/backend <scratch>/rb/`), Python 3.9:
   - `behavioral._position_size_usd` con dos operaciones idénticas de fechas distintas → hallazgo **M-07**.
   - `snapshots_job.compute_broker_value_usd` con el lote ALUA real que documenta `CurrencyContext.jsx:87-92` → hallazgo **M-02**.
   - `reporting.builder._pct_en_pesos` sobre una `fx_rates_daily` sintética de 2 filas → hallazgo **M-04**.
   - La query EXACTA de `GET /api/fx-rates` (`main.py:5185-5189`) sobre una serie diaria 2011-01-03 → 2026-09-06 → hallazgo **M-01**.
2. **Node 24 sobre código del frontend**, en el scratchpad:
   - `frontend/src/utils/fx.js` copiado tal cual (no tiene imports) y ejecutado → hallazgo **M-10**.
   - El cuerpo de `getRateForDate`/`getRateOrFallback` (`useFxHistory.js:149-167`) extraído **verbatim** a un módulo, cambiando sólo `fxIndex`→parámetro y `fallbackRef.current`→parámetro (el original vive dentro del hook y necesita React) → hallazgo **M-01**.
3. **Lectura + `grep -n`/`sed -n`** para todo lo demás. Cada cita de línea de este informe la verifiqué contra el archivo real.

**Qué NO pude ejecutar:**
- No tengo la base de producción. **Ninguna magnitud de este informe es una medición sobre datos reales de usuarios**: los "MEDIDO" son ejecuciones del código real con entradas que yo elegí (y las digo). Lo que necesita prod está en "Preguntas".
- No corrí la suite (`pytest tests/`) ni levanté la app.
- No pude verificar la fecha real más vieja de `fx_rates_daily` en prod (M-01 depende de eso para el tamaño del padrón afectado, no para la existencia del bug).

**Higiene:** no escribí nada dentro de `/tmp/rendi-main`. Verifiqué: existe ahí un `backend/trading.db` de las 17:44 de hoy, **anterior a esta sesión** (`find -newermt "-1 hour"` no lo devuelve) — es el que menciona el brief, no lo creé yo.

---

## Preguntas que necesito que contestes

Sólo estas cinco me bloquean para cerrar un veredicto. El resto de las 57 no las necesito.

1. **P-105 — ¿Cuál es la definición canónica de "lo invertido en dólares"?** El frontend (Cartera, default `'purchase'`) usa el `tc_compra` del lote; **TODO el backend** (snapshot nocturno, Reportes, packets de IA, libro del asesor, CSV) usa el dólar de HOY. Medí el mismo lote dando **−13,6 % en Cartera y +25,0 % en el backend** (M-02). No puedo decir "cuál está mal" sin saber qué querés que signifique el número.
2. **Nueva — ¿Cuántas posiciones abiertas tienen `tc_compra > 0`?** (`SELECT count(*) FROM positions WHERE is_cash=0 AND tc_compra > 0` y el mismo con `IS NULL`.) Es el tamaño exacto del padrón de M-02/M-03: donde `tc_compra` es NULL, `costBasisRate` cae al dólar de hoy y frontend y backend **coinciden**. Sólo 6 de 15 parsers emiten el TC (`importing/fx_migrate.py:419`), así que sospecho que la mayoría de los lotes importados no lo tienen — pero es un dato, no una deducción.
3. **Nueva — ¿Cuál es la fecha más vieja de `fx_rates_daily` y cuántos usuarios tienen operaciones o snapshots anteriores a los últimos 3.650 días?** El frontend pide `?days=3650` y el endpoint devuelve **las últimas 3.650 FILAS**, no días. Con la serie diaria que describe `backend/fx.py:35-37` eso deja afuera todo lo anterior a **~2016-09** y esas fechas se convierten al dólar de HOY, en silencio (M-01). La existencia del bug está medida; el padrón no.
4. **P-302 — ¿`config.tc_blue` es un override manual retirado o un dólar vivo que se dejó de actualizar?** Hoy vale **1415 fijo para toda cuenta nueva** (`main.py:3146`), nadie lo escribe (no hay UI, sólo `PUT /api/config`) y es el dólar con el que el motor de **Comportamiento** dolariza el cash en pesos y el notional de cada operación (M-06, M-07).
5. **P-246 — ¿`vs_sp500_pct` y `vs_inflation_pct` tienen que gatearse por moneda?** Hoy `delta_pct` cambia de moneda con el toggle y los dos benchmarks no: en modo USD el "vs Inflación AR" compara un retorno en dólares contra inflación en pesos, y en modo Pesos el "vs S&P 500" **cambia de signo** (M-05).

---

## Resumen ejecutivo

1A dejó dicho que hay **cuatro rieles de dólar** (blue, MEP-medio, MEP-punta-venta, CCL) y que ninguna capa decide cuál se usa. Lo que encontré yo es un eje distinto y, creo, más caro: **no hay una sola definición de "a qué dólar vale una tenencia vieja"** — hay dos, viven en lados opuestos del sistema, y ninguna de las dos sabe de la otra.

**Los tres que muerden de verdad:**

1. **🔴 La serie de dólares del frontend está capada en 3.650 FILAS, no en 3.650 días.** `useFxHistory.js:65` pide `?days=3650` y `main.py:5182-5189` responde con `ORDER BY date DESC LIMIT 3650`. Con la serie diaria completa desde 2011 que declara `backend/fx.py:36`, **el frontend no puede ver ninguna fecha anterior a ~2016-09**, y `getRateOrFallback` para una fecha fuera de ventana devuelve **el dólar de HOY** sin decir nada. MEDIDO: una venta con P&L de US$1.000 del 2013-05-02, vista con el toggle en Pesos, se dibuja como **$1.518.430** en vez de ~$9.500 — **160×**. Afecta a `/operaciones`, a la curva del Dashboard y a todo lector de `getRateOrFallback`.

2. **🔴 "Invertido en dólares" significa dos cosas distintas según qué pantalla lo muestre.** El frontend tiene un modo `costBasis` con default **`'purchase'`** (el `tc_compra` del lote) desde que un usuario reportó el bug del ALUA; el backend **no tiene ese concepto en ninguna parte** — `snapshots_job.compute_broker_value_usd` lo dice en su propio docstring (línea 168: *"cost basis al blue actual, no al tc_compra histórico"*) y ningún módulo de backend lee `positions.tc_compra` para valuar. MEDIDO con el lote exacto del comentario: **el mismo lote da −13,6 % en Cartera y +25,0 % en el snapshot nocturno / Reportes / IA / libro del asesor**. Signo opuesto, no diferencia de decimales.

3. **🔴 `snapshots.total_invested` tiene dos escritores con convenciones opuestas.** El cron escribe con `'today'` (`snapshots_job.py:754`) y el navegador escribe con `costBasis` = `'purchase'` (`Dashboard.jsx:478`, alimentado por `computeBrokerValue(..., costBasis)` en `Dashboard.jsx:211`). O sea: **la definición del costo histórico de un usuario depende de si ese día abrió la app antes que corriera el cron**. `/api/insights/gap-month` lee justamente el `Δtotal_invested` entre dos fotos (`main.py:11631`) y lo interpreta como movimiento del costo.

Además: el motor de **Comportamiento** y el packet de IA de **Insights** valúan con **1415 congelado** (M-06, M-08) porque leen `config.tc_blue`/`config.tc_mep`, que nadie actualiza desde `main.py:3146`; el **Reportes en Pesos** publica un porcentaje en pesos al lado de un monto en dólares re-expresado a hoy — medido: **"+10,0 % · +US$0"** en el mismo hero (M-04); y el veredicto **"vs S&P 500" cambia de signo** con sólo tocar el selector de moneda (M-05).

Lo que está **bien hecho** y conviene usar como patrón: `frontend/src/utils/bondCashflowFx.js` (TC de la fecha del pago, las dos direcciones, `stale` declarado, `fxToUsdForRow` distinto del `tc` de display) y `backend/twr.serie_medible` en `moneda=ars` (cada punta al TC de SU fecha, y el punto se **descarta** si no hay TC en vez de inventarlo).

---

## Inventario de cotizaciones

### Fuentes (de dónde entra un número al sistema)

| # | cotización | fuente | punta | resolución | quién escribe |
|---|---|---|---|---|---|
| F1 | blue / MEP(bolsa) / CCL / cripto **vivos** | `dolarapi.com/v1/dolares/{casa}` | trae `compra` y `venta`; `_fetch_dolar` calcula **`medio`** | vivo, caché 5 min (`DOLAR_TTL`) | `main.py:4606` |
| F2 | blue **diario histórico** | `api.argentinadatos.com/…/dolares/blue` | **venta** (`item["venta"]`) | diario, desde 2011-01-03 (~5.685 filas) | `_backfill_fx_rates_if_empty` → `fx_rates_daily.blue_venta` |
| F3 | MEP **diario histórico** | `api.argentinadatos.com/…/dolares/bolsa` | **venta** | diario, desde 2018-10-29 (~2.829 filas) | `_backfill_mep_rates_if_missing` (`main.py:4791`), sólo `UPDATE … WHERE mep_venta IS NULL` |
| F4 | blue **del día** | caché F1 | **venta** (`_get_blue_for_scheduler`) | 1 fila/día | cron `snapshots_job.py:977-985` — **no escribe `mep_venta`** |
| F5 | blue **mensual** | `api.argentinadatos.com/…/dolares/blue`, última obs. del mes | **venta** | mensual | `_fetch_dolar_blue_monthly` (`main.py:5378`) → `bench.dolar_blue` |
| F6 | `config.tc_blue` / `config.tc_mep` | **ninguna** — seed `'1415'` (`main.py:3146`), sólo se escribe por `PUT /api/config`, que **no tiene UI** | n/a | congelado | nadie |
| F7 | `positions.tc_compra` | `fx.fx_for_date` en el alta manual (`main.py:8229`) y en el migrador FX (`fx_migrate.py:437`); 6 de 15 parsers | MEP de la fecha, red al blue | por lote | `main.py:8229/8424/8567`, `fx_migrate.py:442` |
| F8 | `operations.fx_to_usd` | `fx.fx_for_date_detail` (`main.py:10419`) en cuentas v2 | MEP de la fecha | por fila | motor de ventas / persister |
| F9 | `snapshots.fx_to_usd_blue` | `_get_blue_for_scheduler` | **blue venta** | 1/día | `snapshots_job.py:791` (ya dictaminado en 1A DIV-134) |
| F10 | inflación AR | `api.argentinadatos.com/…/indices/inflacion` | % mensual INDEC | mensual | `_fetch_inflation_ar` (`main.py:5276`) |

### Consumidores (quién lo usa y **a qué fecha**)

| consumidor | cotización | fecha que usa | nota |
|---|---|---|---|
| `pickFinancialRate` (todo el frontend) | F1 MEP o CCL, **medio** | **hoy** | SSoT del display |
| `_val_rate` / `_current_cedear_rate` (backend vivo) | F1 MEP, **medio**, cascada mep→ccl→**cripto** | **hoy** | la cripto en la cascada es un 4º riel silencioso |
| `_display_blue` | F1 blue, **venta** | hoy | 1A DIV-137 |
| `_current_cripto_rate` | F1 cripto, **venta** (deliberado, comentado) | hoy | numerador del factor cripto (M-13) |
| `fx.fx_for_date` (motor histórico) | F3→F2 | **la fecha del hecho** | el patrón correcto |
| `twr.serie_fx` | F3→F2 | fecha del punto; **`"hoy"` = última fila de la tabla** | M-14 |
| `useFxHistory.getRateOrFallback` | F2 (`r.blue`) | fecha de la fila, **capada a 3.650 filas** | **M-01** |
| `useFxHistory.getMepOrFallback` / `getMepDetail` | F3→F2, con `asOf` declarado | fecha de la fila | el único lector honesto del frontend; lo usa sólo la previa de depósito y `bondCashflowFx` |
| `lookupHistoricalDolar` | **F5 mensual** en meses cerrados, **F1 MEP medio** en el mes en curso | mes | **M-10** — cambia de riel al pasar el mes |
| `useMoneyFormat.fmtMoney` | F1 (`tcValuacion`) | **hoy**, sobre valores viejos | Reportes, asesor, MonthCard/WeekCard/Calendar |
| `useHistoricalMoney.sumConvertedAt` | F8 estampado → F2 → F1 | fecha de la fila | convert-then-sum |
| `compute_broker_value_usd` (cron) | `tc_mep` vivo | **hoy**, también para el COSTO | **M-02** |
| `computeBrokerValue` (frontend) | `tcValuacion` para el valor, **`tc_compra` para el costo** | hoy / **fecha de compra** | **M-02** |
| `analysis_prep.user_fx` | `tc_cedear` = F1 vivo; **`tc_blue` = F6 (1415)** | hoy / **congelado** | **M-06** |
| `behavioral._position_size_usd` | F6 (1415) | **ninguna** — ignora la fecha de la op | **M-07** |
| `ai/builders/insights.py` | **F6** (`config.tc_mep` = 1415) | congelado | **M-08** — el único builder que no pasa por `user_fx` |
| `_advisor_book_fx` | `fx_rates_daily` última fila (**punta venta**) | último cron | vs. el cliente que ve su MEP medio vivo |
| `alerts_engine.condition_met` | **ninguna** | n/a | compara umbral crudo contra precio nativo (**M-11**) |
| `pfUsd` (plazos fijos) | F1 | **hoy**, también para el capital | M-19 |

---

## Tabla de hallazgos

| # | hallazgo | evidencia | severidad | dónde muerde | causa raíz |
|---|---|---|---|---|---|
| **M-01** | `GET /api/fx-rates` devuelve las últimas 3.650 **FILAS**, no días → toda fecha anterior a ~2016-09 se convierte al dólar de **HOY**, en silencio (160×) | **MEDIDO** | 🔴 | `/operaciones` en Pesos, curva del Dashboard, `/mensual`, todo lector de `getRateOrFallback` | `LIMIT ?` sobre filas con un parámetro que se llama `days`; el fallback del hook es el TC vivo y no distingue "no hay dato" de "está fuera de ventana" |
| **M-02** | "Invertido en dólares" tiene dos definiciones: `'purchase'` (frontend, default) vs `'today'` (todo el backend). Mismo lote: **−13,6 % vs +25,0 %** | **MEDIDO** | 🔴 ⚠️ zona activa | Cartera vs snapshot nocturno / Reportes / packets IA / libro del asesor / CSV | el toggle `costBasis` se implementó **sólo en el frontend**; ningún módulo de backend lee `positions.tc_compra` |
| **M-03** | `snapshots.total_invested` tiene dos escritores con convención opuesta (cron `'today'` / navegador `'purchase'`) | **ESTRUCTURAL** | 🔴 ⚠️ zona activa | serie histórica de costo; `Δtotal_invested` de `/api/insights/gap-month` y `/mtm-audit` | consecuencia directa de M-02: la misma columna la escriben dos motores que no comparten definición |
| **M-04** | Reportes en Pesos: el **%** va al TC de cada punta y el **monto** va al TC de hoy → hero **"+10,0 % · +US$0"** | **MEDIDO** | 🟠 | `/analisis?tab=reportes` y `/reportes` (MonthCard, WeekCard, MetricsGrid) | división de tareas declarada en `_pct_en_pesos:635-638` que el frontend cumple con el TC equivocado (hoy en vez de per-fecha) |
| **M-05** | `vs_sp500_pct` y `vs_inflation_pct` se calculan contra un `delta_pct` que cambia de moneda; **el veredicto vs S&P cambia de signo** con el toggle | **DEDUCIDO** | 🟠 | tarjeta de Reportes ("vs S&P 500", "vs Inflación AR") y la narrativa/IA que la lee | `vs_x = delta_pct − bench_ret` sin gate de moneda (`builder.py:1646-1647`); los benchmarks no tienen versión en la otra moneda |
| **M-06** | `config.tc_blue` = **1415 congelado** para toda cuenta (nadie lo escribe, no hay UI) y es el dólar del cash en pesos del motor de Comportamiento | **MEDIDO** (el 1415 en la ejecución) + **ESTRUCTURAL** (ningún escritor) | 🟠 | `/analisis?tab=comportamiento`, `detect_inflation_loss`, `detect_cash_drag`, wrapped, cards de IA | override manual retirado sin retirar a sus lectores; el seed quedó de valor de producción |
| **M-07** | `behavioral._position_size_usd` **ignora la fecha** de la operación: notional de una op en pesos siempre `/1415`. 2021: US$707 en vez de US$6.061 (**8,6×**) | **MEDIDO** | 🟠 | turnover / overtrading / loss-aversion — mezcla ops en pesos con ops en dólares en la misma comparación | es exactamente la clase de bug para la que se escribió `fx.py`; `behavioral.py` nunca se migró |
| **M-08** | `ai/builders/insights.py:363-374` lee `config.tc_mep` persistido (=1415) en vez de `analysis_prep.user_fx` (live-first). La IA lee la cartera **+7,3 %** más grande | **ESTRUCTURAL** + aritmética declarada | 🟠 | packet de Rendi AI de la sección Análisis | es el único builder que resuelve el FX a mano; los otros ocho llaman `currency_context` |
| **M-09** | Depósito/retiro desde el **celular** no manda `date` → se asienta en el **mes en curso** y al **dólar de hoy**; desktop sí manda fecha y el backend usa `fx_for_date` | **ESTRUCTURAL** | 🟠 | capital aportado (= denominador del rendimiento) de todo el que carga desde el teléfono | gemelo exacto del X-2 de 1A (`SellModal` sin `fxHist` en mobile): la paridad mobile/desktop se cerró en un campo y no en el otro |
| **M-10** | `lookupHistoricalDolar`: el mes **en curso** va al MEP medio vivo y en cuanto cambia el mes salta al **blue venta mensual** → **+3,73 %** de escalón sin mercado | **MEDIDO** | 🟡 | `/mensual` (tabs ARS), `evolution.js:519/565` | el parámetro se llama `liveTc` y los callers le pasan `tcValuacion` (MEP), mientras el mapa histórico es blue |
| **M-11** | Alertas de precio: el `currency` que elige el usuario **nunca se usa para comparar**; sólo formatea el mensaje | **ESTRUCTURAL** | 🟡 | alerta sobre un `.BA` con el default USD → dispara al instante o nunca | el campo se agregó para el copy y el comparador quedó igual |
| **M-12** | `positions.csv` (el archivo que va al contador) exporta `invested`/`commissions` **sin columna de moneda**: suma pesos con dólares. `monthly.csv` no declara unidad | **ESTRUCTURAL** | 🟡 | declaración impositiva de un tercero | el fix se aplicó a `operations.csv` (comentario explícito en `main.py:13343-13353`) y no se propagó a sus dos hermanos |
| **M-13** | Factor cripto de broker = `cripto.venta / mep.medio`: numerador punta, denominador medio | **ESTRUCTURAL** | 🟡 | valor (no el %) de la cripto en broker AR, front y back por igual | decisión comentada (`main.py:4959-4963`) que preserva la paridad FE/BE pero deja el ratio no homogéneo |
| **M-14** | `serie_fx(...)("hoy")` = última fila de `fx_rates_daily` (punta venta del último cron). Un lunes, el punto "hoy" de la curva en pesos va al TC del **viernes** | **ESTRUCTURAL** | 🟡 | último punto de `curva_indexada` en `moneda=ars` (Métricas, Reportes, brief) | el valor "hoy" es vivo y el TC "hoy" es de la serie: dos relojes distintos en el mismo punto |
| **M-15** | El packet del Coach manda `tc_blue_ars: tcValuacion` — el **MEP** (o el CCL) rotulado como "blue" | **ESTRUCTURAL** | ⚪ | lo que la IA cree que es el dólar blue | renombre `tcBlue`→`tcValuacion` que no llegó a la clave del payload |
| **M-16** | `config.display_currency` lo **lee** `metrics_pro_card.py:126-130` y no lo **escribe** nadie (vive en `localStorage`) → la IA siempre cree que la pantalla está en USD | **ESTRUCTURAL** | ⚪ | Rendi AI hablando en dólares a un usuario que mira pesos | preferencia per-device que un lector de servidor asumió persistida |
| **M-17** | `Goals.jsx` ignora el selector de moneda (todo `fmtUsd`) y llama `computeBrokerValue` **sin** `costBasis` | **ESTRUCTURAL** | ⚪ | `/objetivos` | pantalla que quedó fuera del rollout del toggle |
| **M-18** | Vender dólares **importados**: `tc_compra` del cash es NULL → `tc_avg = data.tc` → el P&L cambiario da exactamente **0**, sin aviso | **ESTRUCTURAL** | ⚪ | P&L realizado de conversiones en cuentas importadas | el cost-basis del cash USD sólo lo llena la conversión manual (`main.py:10846`) |
| **M-19** | Plazo fijo en pesos: `capital / TC de hoy` → el "invertido" del PF se mueve todos los días con el dólar, junto a lotes que van a `tc_compra` en la misma pantalla | **ESTRUCTURAL** | ⚪ | Dashboard / Home / Métricas (totales con PF) | el PF no tiene dónde guardar su TC de constitución |

---

## Detalle por hallazgo

### M-01 🔴 — La ventana de FX del frontend está capada en FILAS, y afuera de la ventana se usa el dólar de hoy

**Cadena, verificada línea por línea:**

- `frontend/src/hooks/useFxHistory.js:65` → `api.get('/fx-rates?days=3650')`
- `backend/main.py:5182` → `days = max(1, min(int(days or 3650), 3650))` — el tope es **3650** y el frontend ya pide el tope.
- `backend/main.py:5185-5189` →
  ```sql
  SELECT date, blue_venta, mep_venta FROM fx_rates_daily ORDER BY date DESC LIMIT ?
  ```
  **`LIMIT` sobre filas.** El parámetro se llama `days` pero la unidad es fila. (1A lo anotó como X-5 y lo llamó *"benigno hoy, el frontend pide el cap"* — es al revés: **pedir el cap es exactamente lo que dispara el problema**, porque la serie tiene más filas que el cap.)
- `backend/fx.py:36` (documentación del propio repo, medida sobre prod): *"blue: diario COMPLETO desde 2011-01-03 — 5.685 filas sobre 5.686 días"*.
- `useFxHistory.js:149-162` (`getRateForDate`): binary search del último `date <= dateIso`; si no hay ninguno devuelve `null`.
- `useFxHistory.js:164-167` (`getRateOrFallback`): `null` → **`fallbackRef.current` = `tcValuacion` = el MEP medio de HOY**.

**MEDIDO — traza real.** Query exacta del endpoint sobre una serie diaria 2011-01-03 → 2026-09-06:

```
filas en la tabla: 5726 (fx.py declara 5.685 blue desde 2011-01-03)
days efectivo = 3650 | filas devueltas = 3650
fecha MAS VIEJA que el frontend puede ver: 2016-09-09
fecha mas nueva: 2026-09-06
```

Y el lookup del hook sobre esa ventana (cuerpo copiado verbatim de `useFxHistory.js:149-167`):

```
2013-05-02 getRateForDate = null | getRateOrFallback = 1518.43
2015-11-20 getRateForDate = null | getRateOrFallback = 1518.43
2016-09-08 getRateForDate = null | getRateOrFallback = 1518.43
2016-09-09 getRateForDate = 15   | getRateOrFallback = 15
2021-06-15 getRateForDate = 763.19… | getRateOrFallback = 763.19…

Una venta con P&L US$1.000 del 2013-05-02, vista con el toggle en Pesos:
  lo que muestra Rendi: $ 1.518.430
  blue real de mayo 2013 ~ 9,5 -> $ 9.500
  factor de error: 160 x
```

**Por qué es peor de lo que parece.** El bug es **mudo y discontinuo**: dentro de la ventana el número está bien; el 2016-09-09 vale 15 y el 2016-09-08 vale 1.518,43. En `/operaciones` con el toggle en Pesos, una lista ordenada por fecha muestra un salto vertical de 100× a mitad de la tabla, y `sumConvertedAt` suma los dos mundos en el mismo total. En la curva del Dashboard, los snapshots reconstruidos por `_backfill_snapshots_from_monthly` (que **no** estampan `fx_to_usd_blue`, por eso `twr.py:200-211` los clasifica por ese NULL) caen a `getHistoricalFx` = `getRateOrFallback` → los puntos pre-ventana se dibujan al dólar de hoy, o sea una meseta gigante a la izquierda del gráfico.

**Qué lo tapa hoy:** que casi nadie tenga historia anterior a 2016. Eso no es una defensa — `fx.py:12` dice *"80.868 de 84.123 flujos en pesos (96 %) al mismo 1415, **desde 2013**"*, o sea que hay usuarios con flujos de 2013 en la base.

**Fix:** `LIMIT` por fecha (`WHERE date >= current_date - interval days`) o sacar el cap; y que `getRateOrFallback` **no** caiga al TC vivo para fechas fuera de ventana — el mismo criterio que `getMepDetail` (`useFxHistory.js:175-176`) ya aplica y que su propio comentario justifica: *"sugerir un monto con el dólar de HOY para un cupón de hace dos años es peor que no sugerir nada"*.

---

### M-02 🔴 — "Invertido en dólares" tiene dos definiciones y viven en lados opuestos

Este es **el eje central del tema 5** (¿TC de hoy o TC de la operación?) y la respuesta del sistema es: **las dos, según quién pregunte**.

**Lado frontend — `'purchase'`, el TC de la compra:**
- `CurrencyContext.jsx:102-109`: `costBasis` default **`'purchase'`**. El comentario (líneas 87-97) documenta el reporte del usuario: *"una compra de ALUA a 880 pesos el 7/5/24 (tc_compra 1048…) le mostraba US$ 0,58 en vez de 0,84"*, y cierra: *"EL DEFAULT ERA 'today' Y ESTABA MAL"*.
- `valuation.js:263-268`:
  ```js
  export function costBasisRate(p, currentRate, costBasis = 'purchase') {
    return (costBasis === 'purchase' && p?.tc_compra > 0) ? p.tc_compra : currentRate
  }
  ```
- Lo consumen `valueEquityLot` (:379, :393), `pesoLotUsd` (:295), `computeBrokerValue` (:574, :650), `avgCostUsdPerUnit` (:878), `AssetDetail.jsx:54/72`, `PositionDetailMobile.jsx:124/148`, `DetailPortfolioBlocks.jsx:39`.

**Lado backend — `'today'`, siempre:**
- `snapshots_job.py:168` (docstring de `compute_broker_value_usd`): *"Maneja FX-phantom fix para brokers ARS (**cost basis al blue actual, no al tc_compra histórico**)"*.
- `grep -rn "tc_compra" backend/*.py` sobre los módulos de cálculo: **cero lecturas para valuar**. `tc_compra` sólo se escribe (`main.py:8229/8424/8567/8502/8572`, `fx_migrate.py:442`) y se exporta (`main.py:13411`). Ni `snapshots_job`, ni `behavioral`, ni `reporting`, ni `twr`, ni `advisor_*`, ni ningún `ai/builders/*` lo leen.

**MEDIDO — el lote exacto del comentario, ejecutando `compute_broker_value_usd` real:**

```
BACKEND (snapshot nocturno / reportes / IA / asesor): {'value': 725.1153592617007, 'invested': 580.0922874093606}

FRONTEND Cartera, modo purchase (default):  invested USD = 839.69
BACKEND / modo today:                        invested USD = 580.09
brecha = 44.75 %

valor de mercado USD (igual en los dos): 725.12
P&L que ve el usuario en Cartera: -114.58  ( -13.6 % )
P&L que publica el backend:        145.02  (  25.0 % )
```

*(Entradas: 1.000 ALUA, `invested` 880.000 ARS, `tc_compra` 1048, precio `.BA` 1100, MEP hoy 1517 — los números del comentario de `CurrencyContext.jsx:87-92`.)*

**Dónde se ve la contradicción, en la misma sesión de un usuario:** Cartera dice **−13,6 %** y, a dos clics, la tarjeta de Reportes / el informe del asesor / la respuesta de Rendi AI sobre esa misma posición dicen **+25,0 %**.

**Matiz importante que no puedo resolver sin prod (pregunta 2):** `costBasisRate` cae al `currentRate` cuando `tc_compra` no es `> 0`. Sólo 6 de 15 parsers emiten el TC (`fx_migrate.py:419`) y el relleno retroactivo corre **sólo** dentro del migrador FX y **sólo** para lotes ligados a un batch que no sea foto de tenencia (`fx_migrate.py:426-434`). Así que el padrón afectado son los lotes **con** `tc_compra`. Peor: dentro de **la misma tabla de Cartera**, en modo `'purchase'`, las filas con `tc_compra` usan el TC de compra y las que no lo tienen usan el de hoy — y el total es la suma de las dos convenciones. Que exista `TcMissingBadge`/`lotMissingPurchaseRate` (`valuation.js:284-290`) para marcar esas filas confirma que se sabe; no cambia que el total mezcla.

---

### M-03 🔴 — La misma columna, dos escritores, dos definiciones

- **Escritor A (cron):** `snapshots_job.py:747-754` acumula `total_invested += r['invested']` de `compute_broker_value_usd` → convención **`'today'`**. Insert en `snapshots_job.py:778-791`.
- **Escritor B (navegador):** `Dashboard.jsx:478` →
  ```js
  api.post('/snapshots', { total_value: totalValuePositions, total_invested: totalCostBasisPositions, net_deposited: netDepositedPositions })
  ```
  con `totalCostBasisPositions` ← `totalCostBasis` (`Dashboard.jsx:213`) ← `brokerTotals` (`Dashboard.jsx:211`, que **sí** pasa `costBasis`) → convención **`'purchase'`**. Recibe `main.py:5072-5084`, que hace `ON CONFLICT DO UPDATE SET total_invested = excluded.total_invested`.

O sea: **qué significa `total_invested` en la fila del 3 de septiembre depende de si ese día el usuario abrió el Dashboard antes de que corriera el cron.** Los guards del POST (`Dashboard.jsx:465-472`) filtran por cobertura de precios y por CCL, no por convención de costo.

**Lectores:** `reporting/builder.py:251, 324, 359`, `twr.py:1310`, y sobre todo `main.py:11631`:
```python
d_costo = ((sc["total_invested"] - sp["total_invested"]) if …)
```
`/api/insights/gap-month` lee la **diferencia** entre dos fotos como si fuera movimiento del costo. Con una foto `'purchase'` y otra `'today'`, ese delta es puramente la brecha de convención — en el ejemplo de M-02, **+US$259 por lote** que nadie invirtió ni retiró.

**Nota de coherencia:** `MonthlySummary.jsx:288-297` ya resolvió este problema para OTRA columna (`monthly_entries.pnl_unrealized`), y su comentario dice literalmente por qué: *"`pnlUsd` depende del modo `costBasis`, que es una preferencia de DISPLAY: **lo persistido no puede moverse con un toggle**"*. Esa regla está escrita, es correcta, y `snapshots.total_invested` no la cumple.

---

### M-04 🟠 — En Reportes-Pesos el porcentaje y el monto viven en mundos distintos

`reporting/builder._pct_en_pesos` (`builder.py:623-657`) convierte **sólo el porcentaje**, con cada punta al TC de su fecha vía `twr._leg_en_moneda`. Su comentario lo declara (:635-638): *"Los montos publicados siguen en dólares a propósito: Reportes los pasa por `useMoneyFormat`, que ya hace USD→ARS en el frontend"*.

El problema es **con qué TC** lo hace el frontend: `MonthCard.jsx:73` toma `useMoneyFormat()` y `CurrencyContext.jsx:313-315` multiplica por `tcValuacion` = **el MEP de hoy**. Entonces el % describe "cuántos pesos más tengo, con la devaluación adentro" y el monto describe "cuántos dólares más tengo, re-expresados a hoy". No son el mismo período ni la misma pregunta.

**MEDIDO** — `_pct_en_pesos` real sobre una `fx_rates_daily` de dos filas (31/12 MEP 1000, 31/01 MEP 1100 = 10 % de devaluación), cartera quieta en US$10.000 y sin flujos:

```
delta_pct (moneda=ars) = 10.0
delta_usd que publica el backend = end-start-flujos = 0.0
lo que el frontend imprime al lado: fmtMoney(0) x TC_hoy = 0
celdas: valor inicio 11000000  valor cierre 11000000
```

El hero de `MonthCard` (`:117-122`) queda: **`+10,0 %`** y, pegado, **`+US$0`** (o `+$0` con el toggle en Pesos). Y el detalle técnico (`MetricsGrid`, `:222-223`) muestra **Valor inicio $11.000.000 = Valor cierre $11.000.000**, o sea contradice al +10 % que está tres líneas arriba en la misma tarjeta.

Lo mismo pasa con `Depósitos`, `Retiros`, `Realizado` y `No realizado`: son flujos y resultados **del período**, expresados al dólar de **hoy**.

**Contraste — la app ya sabe hacerlo bien en otro lado:** `Operations.jsx:269` usa `histMoney.sumConvertedAt` (convert-then-sum, cada fila con su propio FX) y `useHistoricalMoney.js:88-95` explica por qué: *"Sumar los USD y convertir el total al FX de hoy (convert-after-sum) re-expresa ganancias viejas al dólar actual → infla un resultado que ya ocurrió"*. Reportes hace exactamente eso que ese comentario prohíbe.

---

### M-05 🟠 — El veredicto "vs S&P 500" cambia de signo con el selector de moneda

`reporting/builder.py:1638-1647`:
```python
sp500_ret     = benchmark_return_for_period(bench, period_type, …, "sp500")
inflation_ret = benchmark_return_for_period(bench, period_type, …, "inflation_ar")
vs_sp500     = (delta_pct - sp500_ret)     if …
vs_inflation = (delta_pct - inflation_ret) if …
```
`benchmark_return_for_period` (`:749-778`) **no recibe `moneda`**: el S&P sale siempre de `series[YYYY-MM]` en dólares y la inflación siempre en pesos. Pero `delta_pct` sí cambia de moneda (`:1498`, `:1509`).

**DEDUCIDO.** Supuestos declarados: mes con la cartera **quieta en dólares** (`delta_pct_usd = 0,00 %`), peso que se devalúa **3,00 %**, inflación AR del mes **2,20 %**, S&P **+1,50 %**.

| | `delta_pct` | `vs_sp500_pct` | `vs_inflation_pct` |
|---|---:|---:|---|
| `moneda=usd` | 0,00 % | **−1,50 pp** ✅ | −2,20 pp ❌ (retorno en dólares menos inflación en pesos) |
| `moneda=ars` | +3,00 % | **+1,50 pp** ❌ (dice que le ganaste al S&P; en dólares empataste en 0 contra +1,5) | +0,80 pp ✅ |

**En cada modo exactamente uno de los dos está mal**, y el "vs S&P" no sólo se corre: **invierte el signo** (−1,5 → +1,5) por tocar un selector que el usuario entiende como "en qué unidad me lo mostrás". Los dos números los pinta `MonthCard.jsx:234-239` y los consume la narrativa (y `ai/builders/reports.py`).

**Fix estructural:** o el benchmark viaja a la moneda pedida (S&P en pesos = S&P × devaluación del período, que es la comparación honesta), o el campo no se publica en la moneda donde no aplica.

---

### M-06 🟠 — `config.tc_blue` es 1415 congelado y sigue siendo el dólar de un motor entero

**Nadie lo escribe.** Verificado:
- `main.py:3145-3146`: al crear la cuenta, `INSERT OR IGNORE INTO config VALUES ('tc_blue', '1415', ?)`.
- `PUT /api/config` (`main.py:4587-4595`) es el único writer.
- `grep -rn "put('/config'" frontend/src` → **cero**. `Config.jsx` no manda `tc_blue`/`tc_mep`. Es el endpoint sin UI que menciona P-302.
- `GET /api/config` (`main.py:4560-4561`) además hace `cfg.setdefault("tc_mep", 1415)` / `setdefault("tc_blue", 1415)`.

**Quién lo lee para valuar plata:**
- `analysis_prep.user_fx` (`:39`): `tc_blue = _config_float(conn, uid, "tc_blue", 1415.0)` — y el docstring lo dice sin eufemismo: *"`tc_cedear` … es LIVE-FIRST … **`tc_blue` sigue saliendo del config**"*.
- `currency_context` se lo pasa a `build_behavioral_insights` desde `main.py:13717`, `:13803`, `:15277`, `ai/builders/behavioral.py:64`, `ai/builders/behavioral_card.py:72`, `wrapped_year`, `reporting/timeline.py:156/181`.
- Dentro de `behavioral.py`, `tc_blue` es el dólar de `_position_size_usd` (:105) y de `detect_inflation_loss` (:1325: `loss_usd = loss_pesos / tc_blue`).

**Consecuencia.** El card "Pérdida grande por inflación" divide el cash en pesos por **1415** mientras la Cartera lo divide por el MEP medio vivo. Con MEP 1.518,43 eso es **+7,3 %** de dólares fantasma en el mismo saldo, y los umbrales del card (`loss_usd >= 500` / `>= 100`, `:1327` y `:1334`) se cruzan antes de tiempo.

**Mitigante real:** `_position_value_usd` (`behavioral.py:411`) usa `rate_holdings = tc_cedear` (vivo) para el cash y los holdings — o sea, la valuación de posiciones ya se migró. Lo que quedó atrás son `_position_size_usd` (M-07) y `detect_inflation_loss`. Es el mismo patrón que 1A describe en DIV-137/DIV-138: **el fix se aplicó en un lugar y los hermanos quedaron**.

---

### M-07 🟠 — El notional de una operación no sabe en qué año ocurrió

`backend/behavioral.py:92-107`:
```python
def _position_size_usd(op, tc_blue: float = 1415.0) -> float:
    ...
    notional = float(ep) * float(qty)
    if _native_ccy(op) == "ARS" and tc_blue > 0:
        return notional / tc_blue
    return notional
```
`op["date"]` está a mano en el dict y no se usa.

**MEDIDO** — dos operaciones idénticas de fechas distintas:
```
notional 2021 (ARS 1.000.000): 706.7137809187279
notional 2026 (ARS 1.000.000): 706.7137809187279
MEP real 2021 ~165 -> 6060.606060606061
MEP real 2026 ~1518.43 -> 658.5749754680821
```

Como el divisor es una constante, las operaciones **en pesos** conservan su proporción entre sí; lo que se rompe es la comparación **peso contra dólar**. Una op de 2021 en pesos entra 8,6× subvaluada al lado de una op de 2021 en dólares que entra exacta. Eso alimenta:
- `detect_overtrade` (`:607`, `total_notional`) → turnover,
- `detect_loss_aversion` (`:685-686`, `win_sizes` vs `loss_sizes`) → el veredicto "cortás las ganancias y bancás las pérdidas" se decide comparando tamaños medios de ganadoras y perdedoras. Si las ganadoras del usuario fueron en pesos viejas y las perdedoras en dólares recientes, el veredicto puede salir invertido.

El propio docstring de `_position_size_usd` explica por qué convertir (*"turnover y loss-aversion daban veredictos invertidos"*) — el arreglo se hizo a mitad: se convirtió, pero al dólar equivocado.

---

### M-08 🟠 — El packet de IA de Análisis valúa al 1415 mientras la pantalla valúa al MEP vivo

`backend/ai/builders/insights.py:353-375` resuelve el FX **a mano**:
```python
tc_row = conn.execute("SELECT value FROM config WHERE user_id=? AND key='tc_blue'", …)
tc_blue = float(...) if ... else 1415.0
mep_row = conn.execute("SELECT value FROM config WHERE user_id=? AND key='tc_mep'", …)
tc_mep  = float(...) if ... else tc_blue
tc_cedear = tc_mep if tc_mep > 0 else tc_blue
```
Los otros ocho builders (`dashboard.py:117`, `dashboard_brokers.py:41`, `dashboard_top_holdings.py:47/79`, `dashboard_composition.py:34`, `dashboard_events.py:74`, `behavioral.py:47`, `behavioral_card.py:56`) llaman `currency_context` → `user_fx`, que es **live-first** para `tc_cedear`. Éste no.

Como `config.tc_mep` vale 1415 para todo el mundo (M-06), **todo holding `.BA` del packet se divide por 1415 en vez de por el MEP vivo**: con MEP 1.518,43, `1518,43 / 1415 = 1,0731` → la IA lee una cartera **7,31 % más grande en dólares** que la que el usuario tiene delante. La IA razona sobre concentración, exposición y montos con ese número.

Es exactamente el bug que `user_fx` vino a cerrar — su docstring lo dice: *"para que el backend (Análisis/snapshots/IA) no diverja del Dashboard … en vez del `config.tc_mep` persistido (que podía quedar stale)"*. Este builder no se enganchó.

---

### M-09 🟠 — El depósito desde el celular no tiene fecha, así que va al mes en curso y al dólar de hoy

- **Desktop** (`Positions.jsx:1030-1037`) manda `date: cashFlowForm.date` **y** `tc_blue` de fallback, con el comentario correcto: *"El backend resuelve el dólar por la FECHA; esto queda de fallback"*.
- **Mobile** (`PositionsMobile.jsx:377-389`) **no manda `date`**. Manda `tc_blue: tcValuacion` y su comentario celebra un fix anterior (*"Mobile no lo mandaba … `tc_blue` caía a su default DURO de 1415 … Desktop siempre mandó el real; esto los empareja"*) — pero empareja el TC y **no** la fecha.
- **Backend** (`main.py:10178-10197`): sin `data.date`, `_fy,_fm = now.year, now.month` (mes en curso) y
  ```python
  _rate = _fx.fx_for_date(conn, data.date, fallback=data.tc_blue) or data.tc_blue
  ```
  con `data.date = None`, `fx.fx_for_date_detail` (`fx.py:82-83`) devuelve el `fallback` de una → **el TC de hoy que mandó el navegador**.

**Efecto.** Cargar desde el teléfono un depósito de ARS 1.000.000 hecho en enero de 2024 (MEP ~1.000 → US$1.000) lo asienta como **US$659** (MEP de hoy) y **en septiembre de 2026**. Los dos errores pegan en `monthly_entries.deposits`, que es el **capital aportado = el denominador del rendimiento**, y además desplazan el flujo de mes, lo que reescribe dos meses del TWR.

No hay selector de fecha en el flujo mobile, así que **desde el celular es imposible cargar un movimiento retroactivo bien** — no es que el usuario se olvide, es que la pantalla no ofrece el campo.

Es el gemelo exacto del X-2 de 1A (`PositionsMobile` sin `fxHist` para `SellModal`): la misma pantalla, el mismo tipo de omisión, el otro campo.

---

### M-10 🟡 — El mismo mes cambia de riel de dólar cuando pasa el mes

`frontend/src/utils/fx.js:26-30`:
```js
export function lookupHistoricalDolar(bench, year, month, liveTc, now = new Date()) {
  const todayY = now.getFullYear(), todayM = now.getMonth() + 1
  if (year === todayY && month === todayM) return liveTc
  const map = bench && bench.dolar_blue
  ...
```
El mapa es **blue venta mensual** (`_fetch_dolar_blue_monthly`, `main.py:5378-5389`), pero los tres callers pasan como `liveTc` el `tcValuacion` = **MEP medio vivo**: `MonthlySummary.jsx:165`, `evolution.js:519`, `evolution.js:565`.

**MEDIDO** (`fx.js` ejecutado tal cual, mapa `{2026-06: 1380, 2026-07: 1450, 2026-08: 1575}`, `tcValuacion` 1518,43):
```
2026-06 -> 1380
2026-07 -> 1450
2026-08 -> 1575
2026-09 -> 1518.43
AGO visto en agosto     -> 1518.43
AGO visto en septiembre -> 1575
salto = 3.7255586362229254 %
```

O sea: **el punto de agosto de la serie en pesos cambia de valor un 3,73 % el 1º de septiembre**, sin que se haya movido nada. Un usuario que mira `/mensual` el 31/08 y el 01/09 ve dos números distintos para el mismo mes cerrado. Y la serie completa es **discontinua por construcción**: el último punto usa un riel y los anteriores otro.

(1A ya reportó que Métricas usa el blue mensual mientras Reportes usa el MEP diario — DIV-135. Esto es una capa más: dentro de **esa misma serie** hay dos rieles.)

---

### M-11 🟡 — La moneda de una alerta de precio es decorativa

- El formulario ofrece elegir moneda del umbral: `AlertsManager.jsx:242-248`, con default `currency: 'USD'` (`:26`).
- El backend guarda ese `currency` y lo usa **sólo para formatear el mensaje**: `alerts_engine.py:215-227` (`_fmt`).
- La comparación (`alerts_engine.py:390` → `condition_met`, `:125-135`) es `price >= threshold` **a secas**, contra el precio en su riel nativo (`_prices_for` :38: *"Precio actual por símbolo en su RIEL (.BA→ARS, pelado→USD…)"*).

El formulario calcula `priceCcy` correctamente (`:97`, `.BA` → ARS) y lo usa para mostrar "precio ahora", pero **no lo sincroniza con `form.currency`**; sólo el prefill lo hace (`:83`). Entonces una alerta sobre `MSFT.BA` (≈ ARS 35.000) creada con el default `US$` y umbral `500` en "sube a" cumple `35000 >= 500` en la primera corrida → notificación inmediata y permanente. En "baja a" nunca dispara.

**Fix mínimo:** o forzar `form.currency = priceCcy` (la moneda la decide el símbolo, no el usuario), o convertir en `condition_met`.

---

### M-12 🟡 — El CSV para el contador suma pesos con dólares

`main.py:13384-13416` (`/api/export/positions.csv`) exporta:
```
("invested", "Costo invertido"), ("commissions", "Comisiones"), ("tc_compra", "TC compra (ARS)")
```
`positions.invested` está en la **moneda nativa del lote** (por eso existe `positions.currency`, `main.py:973`). El CSV exporta `tc_compra` pero **no exporta `currency`** y el encabezado no declara unidad: un lote ARS y uno USD caen en la misma columna y el contador los suma.

El repo **ya sabe** que esto importa: `main.py:13343-13353`, en `operations.csv`, dice textualmente *"este archivo se lo manda el usuario al contador … Es el único lector cuyo número sale de la app hacia un tercero: una vez que alguien lo usó para una declaración, Rendi ya no lo puede corregir"*, y ahí sí convierte con `realized_usd_sql()`. Y aclara que `transactions.csv` está bien *"porque exporta el monto apareado con su columna `moneda`"*. **`positions.csv` no tiene ninguna de las dos cosas** y quedó afuera del razonamiento.

`monthly.csv` (`main.py:13644-13678`) tiene el problema hermano y más chico: sus valores **sí** son homogéneos (toda `monthly_entries` está en USD, `main.py:10175-10177`) pero los encabezados dicen "Capital inicio", "Depósitos", "Retiros", "P&L realizado" **sin decir USD** — en un contexto fiscal argentino la lectura por defecto es pesos.

**PARCHE / no-parche:** agregar la columna `currency` a `positions.csv` y "USD" a los encabezados de `monthly.csv` es una línea cada uno.

---

### M-13 🟡 — El factor cripto mezcla una punta con un medio

`main.py:7096-7113` y su espejo `crypto.js:47-53`: `factor = cripto_rate / mep_rate`.
- Numerador: `_current_cripto_rate()` (`main.py:4955-4970`) → `cripto.**venta**`, y en el frontend `dolar?.cripto?.venta` en los 14 call sites.
- Denominador: `cedear_rate` / `tcCedear` = `pickFinancialRate` → `.**medio**` (`CurrencyContext.jsx:51`).

Un ratio entre dos dólares donde uno es la punta cara y el otro el punto medio **no es el premium cripto/MEP**: incluye media horquilla del cripto. Con el spread MEP real que cita `test_dolar_medio.py` (1.507,14 / 1.529,71 → medio 1.518,43) la asimetría es del orden de 0,7 pp sobre el factor; se aplica a valor **y** costo, así que el P&L % queda invariante (por eso no explota) pero **el valor absoluto de toda la cripto en broker AR queda inflado** en esa proporción, en pantalla, en el snapshot y en el libro del asesor.

**No es un descuido:** `main.py:4959-4963` lo justifica — *"La cripto NO pasa al medio: … el frontend lee `dolar.cripto.venta` crudo en ~8 lugares. Mover solo el backend partiría la valuación frontend↔backend"*. La decisión protege la paridad FE/BE, que es lo correcto; lo que quedó sin resolver es que el ratio no sea homogéneo. Se arregla moviendo **los dos lados a la vez** a `medio/medio`.

---

### M-14 🟡 — El punto "hoy" de la curva en pesos usa el dólar del último cron

`twr.py:2056`:
```python
_fx_hoy = (serie_fx(conn, None, None)[0]("hoy")) if ultimo_apto.get("fx") else None
```
`serie_fx._en` (`twr.py:1275-1279`) con `"hoy"` devuelve `vals[-1]` = **la última fila de `fx_rates_daily`**. Esa fila la escribe el cron nocturno con `blue_venta` (`snapshots_job.py:977-985`) y **sin `mep_venta`**, así que `serie_fx` para esa fecha cae al blue (o arrastra el último MEP no nulo, que puede ser de días antes).

Mientras tanto `valor_live` es un valor **vivo**, calculado al MEP **medio** del momento. El punto "hoy" de la curva en pesos es entonces `valor_vivo(MEP medio de ahora) × TC_de_la_última_fila_escrita`.

Un lunes a la mañana, con el cron del domingo sin correr (o con el fin de semana sin cotización), ese TC es el del **viernes**: si el peso se movió entre medio, el último punto de la curva en pesos ignora el movimiento entero. Es la misma familia que el X-1 de 1A (la serie en punta-venta vs la valuación al medio); lo específico acá es que el **último punto** mezcla dos relojes.

---

### M-15 ⚪ — `tc_blue_ars` no es el blue

`Insights.jsx:2465`: `tc_blue_ars: tcValuacion`. `tcValuacion` es el MEP medio, o el **CCL** si el usuario lo eligió. El snapshot va al contexto del Coach; el modelo lee la clave literalmente. `CurrencyContext.jsx:6-9` documenta el renombre `tcBlue`→`tcValuacion` justamente porque *"la variable se llamaba `tcBlue` sin contener el blue, lo que confundía a cualquiera que la leyera y escondía bugs de FX"* — la clave del payload quedó con el nombre viejo.

### M-16 ⚪ — La IA siempre cree que la pantalla está en dólares

`ai/builders/metrics_pro_card.py:126-130` lee `config.display_currency` y default `"USD"`. Nadie escribe esa clave: la moneda vive en `localStorage` (`CurrencyContext.jsx:24`, `'rendi_display_currency'`). `grep -rn "display_currency"` sobre todo el repo devuelve exactamente esas dos líneas. Un usuario que mira todo en pesos recibe respuestas redactadas para dólares.

### M-17 ⚪ — Objetivos quedó fuera del toggle

`Goals.jsx` formatea todo con `fmtUsd` y rotula "Objetivo (USD)" (`:543`), sin leer `currency`. Además llama `computeBrokerValue(positions, pr, b, tcValuacion, tcCedear, tcCripto)` **sin** `costBasis` (`:82`) → `'today'`. Como sólo usa `.value` (no `.invested`), la omisión de `costBasis` es hoy inocua; el resto de los callers sin `costBasis` son `MonthlySummary.jsx:284`, `CarteraList.jsx:95`, `useMonthlyData.js:509`, `Events.jsx:155/167`.

### M-18 ⚪ — Vender dólares importados no genera P&L cambiario, y no avisa

`main.py:10934-10943`: al vender USD, `tc_avg = (cash_usd['tc_compra'] if cash_usd else None) or data.tc`. El `tc_compra` del cash USD sólo lo escribe `_adjust_cash(..., tc_for_basis=data.tc)` desde la **conversión manual** (`main.py:10846-10852`, y sólo en compras). Un cash USD que llegó por importación tiene `tc_compra` NULL → `tc_avg = data.tc` → `cost_basis_ars = usd_amount * data.tc` → `pnl_ars_realized = ars_amount - usd_amount*tc ≈ 0`. El resultado cambiario de esa venta se publica como **cero exacto**, indistinguible de una venta que efectivamente no ganó nada.

### M-19 ⚪ — El plazo fijo en pesos no tiene TC de constitución

`usePfRollup.js:34-38`:
```js
export function pfUsd(totals, tcValuacion) {
  const tc = tcValuacion || 1415
  const valueUsd    = (totals?.USD?.valor  || 0) + (totals?.ARS?.valor  || 0) / tc
  const investedUsd = (totals?.USD?.capital|| 0) + (totals?.ARS?.capital|| 0) / tc
```
El **capital** de un PF en pesos (los pesos que el usuario efectivamente puso, hace meses) se divide por el dólar de hoy. El P&L no se rompe (valor y capital van al mismo `tc`, así que el devengado sobrevive), pero el "Invertido" del PF **se mueve todos los días con el dólar** y se suma, en el mismo total del Dashboard, a lotes cuyo invertido va al `tc_compra` (M-02). Es la tercera convención de costo en la misma cifra. Además, el `|| 1415`.

---

## Parches detectados

| ubicación | qué síntoma tapa | causa real | dónde más sigue rompiendo |
|---|---|---|---|
| `valuation.js:263-268` (`costBasisRate` con default `'purchase'`) + `TcMissingBadge` | El costo en dólares de un lote ARS medido al dólar de hoy (el bug del ALUA) | El "costo en dólares" nunca se definió a nivel sistema: es una preferencia de display que sólo el frontend conoce | Todo el backend (M-02), `snapshots.total_invested` (M-03), el CSV, los informes del asesor, los packets de IA. Y **dentro de la misma tabla**, las filas sin `tc_compra` siguen al dólar de hoy |
| `Positions.jsx:1607-1615` (`totalsToday`, un segundo cálculo del total en modo `'today'` sólo para el hero en pesos) | Que el hero en pesos publicara "un número que el usuario nunca aportó" | El costo en pesos y el costo en dólares son dos magnitudes distintas y no hay una capa que lo modele: se resuelve con un `if` de display | Las filas de la tabla siguen en modo `'purchase'` → el hero en pesos y la suma de las filas responden preguntas distintas (el propio comentario en `:2101-2105` admite que `pnlArs` y `pnlUsd` **pueden tener signo opuesto**) |
| `Dashboard.jsx:500-590` (reimplementación inline de la valuación por lote para el `sync-unrealized`) | Que el `pnl_unrealized` persistido se moviera con el toggle de display | El mismo cálculo existe en `computeBrokerValue`, que la misma pantalla ya llama en `:211`. Se copió el ruteo de moneda (`tcValuacion`/`tcCedear`/`tcCripto`, CEDEAR→`.BA`, `costInPesos`, `costInUsd`, factor cripto) en vez de parametrizarlo | Es un **cuarto** ruteo de moneda por lote (con `valuation.js`, `snapshots_job.compute_broker_value_usd` y `behavioral._position_value_usd`). Cualquier fix de FX hay que aplicarlo en los cuatro |
| `ai/builders/insights.py:353-375` (resolución de TC a mano) | Nada — es el estado previo que `analysis_prep.user_fx` vino a reemplazar | El builder no se migró cuando se creó la SSoT | M-08: la IA de Análisis lee la cartera 7,3 % más grande |
| `_backfill_mep_rates_if_missing` (`main.py:4791-4800`) | El hueco de `mep_venta` que deja el cron | El cron **tiene** `tc_mep` en scope y escribe sólo el blue (`snapshots_job.py:977-985`) | Como el cron mete una fila nueva sin MEP cada noche, `COUNT(*) WHERE mep_venta IS NULL` nunca es 0 → el backfill pega a argentinadatos **en cada arranque**. Y los 4 parches de "buscar la última fila CON mep" que 1A ya listó siguen ahí |
| `AlertsManager.jsx:97` (`priceCcy` calculado para mostrar, no para decidir) | Que el usuario no supiera en qué moneda cotiza el ticker | La moneda del umbral la decide el símbolo, no el usuario; el selector no debería existir | M-11: el comparador nunca convierte |

---

## Citas del mapa incorrectas

No leí el mapa entero (3,4 MB, por instrucción). Verifiqué por `grep` sólo las citas que tocan mis hallazgos. Las que estaban mal:

| origen | cita | ubicación / afirmación real | qué decía mal |
|---|---|---|---|
| 1A, X-5 | *"`GET /api/fx-rates` … Benigno hoy (el frontend pide 3650 = el cap), pero es una trampa"* | `main.py:5182-5189` + `useFxHistory.js:65` + `fx.py:36` | **Invertido.** Que el frontend pida el cap es lo que **dispara** el bug, no lo que lo evita: la serie tiene ~5.685 filas y el cap 3.650, así que ~2.035 días quedan afuera y `getRateOrFallback` los resuelve al dólar de hoy (M-01, medido). No es una trampa futura: está activa |
| P-047 (preguntas) | *"`reconcile-cash` … dolarizándolo con el `tc_blue` que manda el navegador (el de hoy)"* | `ImportWizard.jsx:2718-2721` **no manda `tc_blue`** | El navegador no manda nada: cae al default Pydantic **1415** (`main.py:10020`). Es lo que 1A ya corrigió en su U-1; lo anoto porque la pregunta abierta todavía describe el caso benigno |
| P-134 (preguntas) | *"`compute_broker_value_usd` no tiene la rama `costInPesos` que sí tiene el frontend"* | `snapshots_job.py:205-231` **sí** tiene la rama espejo (`_cost_in_usd`) | La rama existe. Lo que **no** existe en el backend es la rama `costBasis`/`tc_compra` — que es un problema distinto y mayor (M-02) |
| P-317 (preguntas) | *"Ningún parser llena `tc` ni `monto_usd` en filas de COMPRA, así que `tc_compra` sale siempre NULL desde el importador"* | `fx_migrate.py:419` dice *"**Solo 6 de 15 parsers** emiten el TC de compra"*, y `:426-442` lo completa retroactivamente para lotes de batches que no sean foto | "Siempre NULL" es más fuerte de lo que sostiene el código: hay 6 parsers que lo emiten y un relleno retroactivo dentro del migrador FX. La pregunta 2 de arriba es para medir cuántos quedaron |

---

## URGENTE

**U-1 — `GET /api/fx-rates` limita por FILAS: toda fecha anterior a ~2016-09 se muestra al dólar de hoy, en silencio (medido: 160×).**

- `frontend/src/hooks/useFxHistory.js:65` → `?days=3650`
- `backend/main.py:5182` → `days = max(1, min(int(days or 3650), 3650))`
- `backend/main.py:5185-5189` → `ORDER BY date DESC LIMIT ?` — **filas, no días**
- `backend/fx.py:36` → la serie blue tiene ~5.685 filas desde 2011-01-03
- `frontend/src/hooks/useFxHistory.js:164-167` → sin dato, devuelve `tcValuacion` (**hoy**) sin marcar la degradación

Es urgente por tres razones: (a) el error es de dos órdenes de magnitud, no de puntos porcentuales; (b) es **mudo** — no hay badge, log ni `asOf`, y el número se ve perfectamente plausible; (c) el arreglo del síntoma es una línea (`WHERE date >= ?` en vez de `LIMIT`) y no requiere ninguna decisión de producto. El arreglo de la causa —que `getRateOrFallback` deje de caer al TC vivo para fechas fuera de cobertura, como ya hace `getMepDetail`— sí requiere decidir qué dibujar en su lugar.

**No lo toqué.** Auditoría en curso, cero líneas modificadas.

---

## BLOQUE-RESUMEN

| tema | # | hallazgo | evidencia | severidad | dónde muerde | causa raíz |
|---|---|---|---|---|---|---|
| Monedas | M-01 | `/api/fx-rates` capa por FILAS (3.650): fechas anteriores a ~2016-09 se convierten al dólar de HOY, en silencio (160×) | MEDIDO | 🔴 | `/operaciones` en Pesos, curva del Dashboard, `/mensual` | `LIMIT` sobre filas con un parámetro llamado `days`; el fallback del hook es el TC vivo |
| Monedas | M-02 | "Invertido en dólares": `'purchase'` en el frontend vs `'today'` en todo el backend. Mismo lote: −13,6 % vs +25,0 % | MEDIDO | 🔴 ⚠️ zona activa | Cartera vs snapshot/Reportes/IA/asesor/CSV | el toggle `costBasis` se implementó sólo en el frontend; ningún backend lee `tc_compra` |
| Monedas | M-03 | `snapshots.total_invested` tiene dos escritores con convención opuesta (cron `'today'` / navegador `'purchase'`) | ESTRUCTURAL | 🔴 ⚠️ zona activa | serie de costo, `Δtotal_invested` de gap-month y mtm-audit | consecuencia de M-02: una columna, dos motores sin definición común |
| Monedas | M-04 | Reportes en Pesos: % al TC de cada punta, monto al TC de hoy → hero "+10,0 % · +US$0" | MEDIDO | 🟠 | `/reportes` y `/analisis?tab=reportes` | división de tareas declarada que el frontend cumple con el TC equivocado |
| Monedas | M-05 | `vs_sp500_pct` / `vs_inflation_pct` sin gate de moneda: el veredicto vs S&P cambia de signo con el toggle | DEDUCIDO | 🟠 | tarjeta de Reportes + narrativa/IA | `vs_x = delta_pct − bench_ret` y los benchmarks no tienen versión en la otra moneda |
| Monedas | M-06 | `config.tc_blue` = 1415 congelado (sin UI, sin escritor) y es el dólar del cash del motor de Comportamiento | MEDIDO + ESTRUCTURAL | 🟠 | `/analisis?tab=comportamiento`, wrapped, cards de IA | override manual retirado sin retirar a sus lectores |
| Monedas | M-07 | `_position_size_usd` ignora la fecha de la op: notional en pesos siempre `/1415` (8,6× en 2021) | MEDIDO | 🟠 | turnover, overtrading, loss-aversion | `behavioral.py` nunca se migró a `fx.fx_for_date` |
| Monedas | M-08 | `ai/builders/insights.py` lee `config.tc_mep` (1415) en vez de `user_fx` live → la IA ve la cartera +7,3 % | ESTRUCTURAL | 🟠 | packet de Rendi AI de Análisis | único builder que resuelve el FX a mano |
| Monedas | M-09 | Depósito desde mobile sin `date` → mes en curso + dólar de hoy; desktop usa `fx_for_date` | ESTRUCTURAL | 🟠 | capital aportado (denominador del rendimiento) | paridad mobile/desktop cerrada en el TC y no en la fecha |
| Monedas | M-10 | `lookupHistoricalDolar`: mes en curso al MEP medio vivo, mes cerrado al blue venta mensual → +3,73 % de salto | MEDIDO | 🟡 | `/mensual` (tabs ARS), `evolution.js` | el parámetro `liveTc` recibe MEP mientras el mapa es blue |
| Monedas | M-11 | Alertas: el `currency` del umbral no se usa para comparar, sólo para el mensaje | ESTRUCTURAL | 🟡 | alerta sobre `.BA` con default USD: dispara al instante o nunca | el campo se agregó para el copy; el comparador quedó igual |
| Monedas | M-12 | `positions.csv` (al contador) exporta `invested` sin columna de moneda; `monthly.csv` no declara unidad | ESTRUCTURAL | 🟡 | declaración impositiva de un tercero | el fix de `operations.csv` no se propagó a sus hermanos |
| Monedas | M-13 | Factor cripto = `cripto.venta / mep.medio`: punta sobre medio | ESTRUCTURAL | 🟡 | valor de la cripto en broker AR (FE, BE, snapshot, asesor) | decisión comentada de paridad FE/BE que deja el ratio no homogéneo |
| Monedas | M-14 | `serie_fx("hoy")` = última fila de `fx_rates_daily`: el punto "hoy" en pesos usa el TC del último cron | ESTRUCTURAL | 🟡 | último punto de `curva_indexada` en `moneda=ars` | valor vivo con TC de serie: dos relojes en el mismo punto |
| Monedas | M-15 | El packet del Coach manda `tc_blue_ars: tcValuacion` (el MEP, o el CCL) | ESTRUCTURAL | ⚪ | lo que la IA cree que es el blue | renombre `tcBlue`→`tcValuacion` que no llegó al payload |
| Monedas | M-16 | `config.display_currency` se lee y nadie lo escribe → la IA siempre cree que la pantalla está en USD | ESTRUCTURAL | ⚪ | Rendi AI hablando en dólares a un usuario en pesos | preferencia per-device que un lector de servidor asumió persistida |
| Monedas | M-17 | `Goals.jsx` ignora el selector de moneda y llama `computeBrokerValue` sin `costBasis` | ESTRUCTURAL | ⚪ | `/objetivos` | pantalla fuera del rollout del toggle |
| Monedas | M-18 | Vender dólares importados: `tc_compra` NULL → `tc_avg = data.tc` → P&L cambiario exactamente 0, sin aviso | ESTRUCTURAL | ⚪ | P&L realizado de conversiones en cuentas importadas | el cost-basis del cash USD sólo lo llena la conversión manual |
| Monedas | M-19 | PF en pesos: `capital / TC de hoy` — el "invertido" del PF se mueve con el dólar y se suma a lotes en `tc_compra` | ESTRUCTURAL | ⚪ | totales de Dashboard/Home/Métricas con PF | el PF no tiene dónde guardar su TC de constitución |
