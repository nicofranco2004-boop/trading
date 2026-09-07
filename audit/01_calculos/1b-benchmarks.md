# 1B — Benchmarks y objetivos

**Tanda 1B · 2 conceptos que NO estaban mapeados** (están entre los 8 de 24 sin mapear).
**Commit auditado:** `b74f450f2badf1a2b84e657551115a0595110e45` — copia de solo lectura `/tmp/rendi-main`.
Verificación de integridad: `wc -l /tmp/rendi-main/backend/main.py` → **38029** ✅

**Deriva `82fad6a0` (FCI Ualá):** ninguno de los 29 hallazgos cae en `backend/pricing/fci.py`, `frontend/src/components/AddPositionFlow.jsx` ni `backend/tests/test_fci_uala.py`. **Nada "posiblemente ya corregido".**
**Rama `fix/snapshots-valuacion` (`backend/snapshots_job.py`):** ningún hallazgo cae ahí. **Nada "zona de trabajo activa".**

---

## Método

### Qué EJECUTÉ (todo lo etiquetado MEDIDO sale de acá)

Copié `performance.py`, `twr.py` y `goals_diagnostic.py` a un directorio temporal propio
(`…/scratchpad/lab/`) y los corrí ahí con `python3`. **No escribí una sola línea dentro de
`/tmp/rendi-main`** — precisamente para no repetir el `trading.db` que contaminó la copia de
referencia en una tanda anterior.

Tres scripts, con la traza real pegada en el detalle de cada hallazgo:

| script | qué prueba | hallazgos que sostiene |
|---|---|---|
| `t1.py` | `performance.benchmark_recortado` con la caché real del backend, para `plazo_fijo` y para `sp500` | B-01, B-13 |
| `t2.py` | la misma función con una curva DIARIA de 62 puntos, comparando la serie diaria (`sp500_d`) contra la mensual (`merval`) | B-03 |
| `t3.py` | `goals_diagnostic.build_goal_diagnostic`, `_required_monthly_rate`, `_months_between`, `_project_value` | O-01, O-04, O-07, O-08 |

### Qué NO pude ejecutar

- **No tengo base de producción ni copia de datos.** Nada de "N usuarios afectados" sale de una
  query mía. Donde cito magnitudes de producción (los 484 usuarios del S&P, los 417 del CAGR) es
  **cita textual de un comentario del código**, y lo digo explícitamente.
- **No pude correr `performance.performance` ni `twr.curva_indexada` end-to-end**: necesitan una
  conexión y esquema reales. Todo lo que depende de eso es DEDUCIDO sobre código leído.
- **No corrí el frontend.** Todo lo de `Insights.jsx` / `Goals.jsx` / `BenchmarksLine.jsx` es
  ESTRUCTURAL: cadena de llamadas leída con `grep -n` / `sed -n` y citada.
- **No corrí la suite de tests** (no era el encargo y habría gastado presupuesto en algo que ya
  tiene su propio informe).

### Sobre el mapa y el informe previo

- **No leí `00-mapa-sistema.md` entero** (3,4 MB). Lo consulté con `grep -n 'benchmark'` — 30 líneas.
  Los dos conceptos de esta tanda **no estaban mapeados**, así que el mapa aporta poco: sólo el
  inventario de fetchers (§4081-4094) y dos rarezas del endpoint. **Verifiqué las 4 citas del mapa
  que uso** y las 4 son correctas (detalle en "Citas del mapa").
- `AUDIT_benchmark_2026-09-01.md` (working tree, rama vieja) **no lo leí**: el propio código de
  `/tmp/rendi-main` cita sus mediciones textualmente en los docstrings de
  `_fetch_yf_daily` y `_benchmark_diario`, que es la versión que sí corresponde a este commit.

### Nota sobre 1A

1A dejó dicho que "`perf.benchmark` no lo lee nadie". **En este commit eso ya no es cierto:**
`Insights.jsx:1696` lee `s.bench` (que sale de `perf.benchmark` vía `benchSeriesUsd`, línea 878)
para USD y para pesos-con-motor. La afirmación describía el estado anterior a los fixes del 02-03/09.
**El código gana.**

---

## Preguntas que necesito que contestes

De las 29 pre-filtradas me sirven **cinco**. Agrego **cuatro propias** que el código no puede responder.

### Del filtro automático

1. **P-247 🔴 — Cuando el CAGR no se puede anualizar (ventana < medio año), ¿qué tiene que decir el
   diagnóstico del objetivo?** Hoy dice "**Al ritmo actual, no llegás a la meta**". No es una
   licencia poética: `user_cagr_pct=None` se convierte en `0` y el motor concluye que el usuario
   rinde cero. `_historical_cagr_global` ya devuelve `total_return_pct` + `dias` para poder decirlo
   bien, y `goals_diagnostic` no los mira. **Esto bloquea O-01, que es el peor hallazgo de esta tanda.**

2. **P-058 — ¿El diagnóstico del objetivo tiene que respetar `modo` y `moneda`?** Hoy la card de
   arriba (`/api/goals/cagr?modo=…`) obedece el toggle Certero/Estimado y la card de abajo
   (`/api/goals/{id}/diagnostic`) queda clavada en certero/USD. El usuario mueve el toggle y ve
   cambiar un número y no el otro.

3. **P-237 — ¿Se mata una de las dos "tasas requeridas"?** "Solo con rendimiento" (frontend) y
   "Necesario · X%/año" (backend) están a 15 píxeles, se calculan sobre **capitales distintos** y
   cuentan los meses con **fórmulas distintas**. Confirmado y detallado en O-03 y O-11.

4. **P-159 — ¿`insights.benchmarks` se cablea o se borra?** Confirmé que **no tiene ningún
   consumidor en la UI real** (`grep -rn 'topic="insights' frontend/src` devuelve 4 topics y ése no
   está; sólo aparece en `demo.js`). Importa porque el packet publica un veredicto booleano
   `outperform.inflation` construido cruzando monedas (B-06). Si se borra, el bug se va con él; si se
   cablea, hay que arreglarlo antes.

5. **P-253 — ¿El veredicto "Le ganás / Le perdés" se unifica al motor del gráfico?** Está a medias:
   `verdictItems` (`Insights.jsx:2578-2603`) ya lleva su `nota` con la base escrita — eso está bien
   hecho y es una decisión de producto legítima. Pero sigue siendo un motor distinto
   (`compareToMine`: patrimonio de hoy vs simulación al último cierre mensual) del que dibuja la
   línea de arriba (`perf.benchmark`, diario, indexado). Y arrastra B-09.

### Mías

6. **¿El objetivo tiene que poder llevar un plan de aportes?** La tabla `goals` guarda
   `target_usd`, `target_date`, `expected_return_pct` y `label` — **nada más** (`main.py:1498-1506`).
   Todo el motor de diagnóstico proyecta **sin aportes**, y el packet de IA publica
   `monthly_contribution: 0.0` porque lee una columna que no existe. Mientras tanto el empty state
   de la pantalla promete literalmente *"vamos a calcular cuánto necesitás aportar por mes"*. Es la
   decisión de producto que destraba O-02.

7. **¿El objetivo tiene que poder definirse en pesos?** Hoy es `target_usd` y punto. Un objetivo a
   5 años en dólares para alguien que ahorra en pesos y compra en pesos es una pregunta distinta de
   la que la app contesta, y no hay ajuste por inflación en ningún lado.

8. **En Reportes con el selector global en Pesos, ¿contra qué se compara?** Hoy se resta el retorno
   **en pesos** menos el S&P **en dólares** y se publica "Le ganaste al S&P 500". Las opciones son
   (a) pasar el S&P a pesos como ya hace `performance._en_pesos`, o (b) ocultar el vs-S&P en modo
   pesos. Es una decisión de producto, no una limpieza. **Bloquea B-04.**

9. **P-145 (te la reenvío porque toca el benchmark) — ¿el "P&L realizado" del usuario incluye
   dividendos y cupones?** `_fetch_sp500_monthly` eligió `^SP500TR` **asumiendo que sí**
   (`main.py:5337-5342`). Si en algún camino no los incluye, el benchmark está sistemáticamente
   1,5-2 pp/año arriba de lo que corresponde.

---

## Resumen ejecutivo

**El motor de benchmark del backend está bien construido.** `performance.py` recorta el índice al
rango exacto del usuario, lo indexa a 1,0 en la misma fecha, lo resuelve por día cuando tiene serie
diaria, y lo pasa a pesos multiplicando por el TC de cada fecha y re-anclando. Está documentado con
las mediciones que lo justifican. **El problema no es el motor: es que el producto tiene otros seis
lugares que comparan contra un benchmark y ninguno pasa por ahí.**

Lo concreto que el usuario ve mal, hoy:

1. **Dos de las cinco opciones del selector en pesos no funcionan.** "Plazo fijo UVA" dibuja
   **nada**: el frontend pide `bench=plazo_fijo` y el backend nunca produjo esa serie — baja `uva`
   (MEDIDO: `benchmark_recortado` devuelve `[]`). "Pesos cash (blue)" es peor: no tiene mapeo a
   clave de API, el `useEffect` del fetch hace `if (!k) return` y **el gráfico se queda con el
   benchmark anterior mientras la leyenda cambia al nombre nuevo**. Alguien que viene de mirar
   "Inflación AR" y toca "Pesos cash" ve la línea de la inflación rotulada como pesos cash.

2. **En Reportes, una de las dos comparaciones tiene siempre la moneda cruzada, y el veredicto sale
   con el signo dado vuelta.** `vs_sp500_pct` y `vs_inflation_pct` se calculan restando el retorno
   del usuario menos el del benchmark, y `benchmark_return_for_period` **nunca recibe el parámetro
   `moneda`**. Con el selector global en Pesos, el retorno del usuario incluye la devaluación y el
   S&P no: una cartera quieta en dólares con un mes de 5 % de devaluación y un S&P de +2 % publica
   *"Le ganaste al S&P 500 · +3,0 puntos"* cuando la verdad es −2,0. Con el selector en Dólares pasa
   lo simétrico contra la inflación. **Y el modo pesos de Reportes se deployó el 03/09** — o sea que
   esto es una regresión reciente sobre una pantalla que acababa de auditarse.

3. **El Merval quedó afuera del fix del ancla diaria.** El audit del 01/09 midió que resolver el
   benchmark por MES sobre una curva diaria daba 2 valores distintos en 44 filas y el signo invertido
   en 21 de 484 usuarios; el remedio fue bajar series diarias. Se bajaron para `sp500`, `shv` y `gld`
   — los tres benchmarks del selector **en dólares**. Los dos que sólo existen en el selector **en
   pesos** (Merval, Plazo fijo UVA) no la tienen. MEDIDO sobre una curva de 62 días: la línea del
   S&P toma 44 valores distintos y la del Merval **3**, ancladas al cierre de fin de mes.

4. **El "vs S&P 500" del Dashboard y el de Insights no son el mismo número.** El chip del Dashboard
   (`BenchmarksLine`) recibe `monthly` **crudo** y un total que **incluye plazos fijos**; Insights
   usa la cadena corregida a mercado (`applyMtmToMonthly`) y un total que **los excluye**. El propio
   `Dashboard.jsx` importa `applyMtmToMonthly` en la línea 43 y **no lo usa en ninguna parte** — el
   import muerto es la firma del olvido.

5. **Crear un plazo fijo desde un broker te hace perder contra todos los benchmarks a la vez.**
   `create_plazo_fijo` debita el cash del broker de origen (`main.py:9144`) y **no registra ningún
   retiro** en `monthly_entries`. El simulador del benchmark conserva ese flujo; el patrimonio del
   usuario pierde el monto entero. La comparación castiga al usuario por el 100 % del PF.

Del lado de **Objetivos** el diagnóstico es peor, porque el concepto entero está construido sobre
dos supuestos que el producto contradice:

6. **"No puedo anualizar" se publica como "rendís 0 %".** El fix canónico de `twr` —correcto— dejó
   de anualizar ventanas menores a medio año y devuelve `cagr: None` con el acumulado al lado.
   `goals_diagnostic` hace `(user_cagr_pct or 0) / 100`. MEDIDO: el mismo usuario, mismo objetivo,
   `cagr=None` → **"Atrasado · Al ritmo actual, no llegás a la meta"**; con su acumulado real de
   +54 % → **"Adelantado · ETA 20 meses"**. El dato para decirlo bien viaja en la misma respuesta
   (`total_return_pct`) y nadie lo mira.

7. **El objetivo no tiene aportes.** Ni la tabla, ni el motor, ni el packet de IA. `goals` tiene
   cuatro columnas y ninguna es el aporte mensual; `_required_monthly_rate` y `_project_value` están
   documentados como "SIN aportes"; el builder de IA lee `monthly_contribution` de una **columna que
   no existe** y publica `0.0` mientras el prompt le pide al modelo razonar sobre "la sensibilidad a
   los aportes". Un ahorrista disciplinado —el usuario objetivo de la pantalla— queda marcado
   "Atrasado" por construcción.

8. **El mismo payload publica dos anualizaciones distintas de la misma tasa.**
   `required_annual_pct` compone (`(1+r)^12−1`) y `delta_pct_required` multiplica (`r×12`), tres
   líneas más abajo. MEDIDO: 28,6 pp de brecha en un caso de duplicar el capital en 12 meses; 41,1 pp
   en uno de +50 % en 6.

9. **La card "Expectativa de retorno" compara un acumulado contra una tasa anual.** El piso
   (`floorReal: 10` para "crecer fuerte") es %/año; `realReturnPct` es el retorno real **acumulado**
   de la ventana medida. `monthsCounted` se pasa a la card y **el gauge no lo muestra ni lo usa**.
   Un usuario de dos meses con +1,5 % real lee "por debajo de esa expectativa".

**29 hallazgos: 5 🔴, 11 🟠, 8 🟡, 5 ⚪.** Ninguno es cosmético salvo los cinco ⚪, y de esos, tres son
código muerto que miente en sus propios comentarios.

---

## Mapa del concepto

> Este mapa no existía. Lo que sigue es el inventario que armé leyendo el código, no una copia del
> mapa previo.

### BENCHMARKS

#### Qué hay — inventario de series

`_benchmarks_fetch_and_cache` (`backend/main.py:5215`) lanza **10 futures** sobre un
`ThreadPoolExecutor(max_workers=4)` con `timeout=25` por future y fallback al caché stale por clave:

| clave | qué es | fuente | frecuencia | período bajado | `_d`? |
|---|---|---|---|---|---|
| `inflation_ar` | IPC INDEC, **% mensual** | `api.argentinadatos.com` | mensual | todo | no |
| `sp500` | `^SP500TR` (total return), fallback `^GSPC` | yfinance | mensual | **`max`** (llega a 1988) | **sí** |
| `dolar_blue` | blue venta, último del mes | `api.argentinadatos.com` | mensual | todo | no |
| `shv` | T-Bills USD vía ETF SHV | yfinance | mensual | `max` | **sí** |
| `gld` | Oro vía ETF GLD | yfinance | mensual | `max` | **sí** |
| `merval` | `^MERV`, en ARS | yfinance | mensual | `max` | **no** |
| `uva` | coeficiente UVA (≈ IPC/CER) | `api.argentinadatos.com` | mensual | todo | **no** |
| `sp500_d`, `shv_d`, `gld_d` | los mismos, cierre DIARIO | yfinance | diaria | **`5y`** | — |

**Lo que NO existe:** `plazo_fijo` (el docstring lo lista, el código baja `uva` en su lugar),
`merval_d`, `uva_d`, y cualquier serie de tasa nominal de plazo fijo tradicional (el docstring de
`_fetch_uva_monthly` explica por qué: argentinadatos no publica la TNA minorista histórica — es una
decisión documentada y correcta).

**Caché:** `_bench_cache`, TTL 1 h, SWR con lock (`_bench_refresh_inflight`). **In-process**: con más
de un worker cada uno tiene el suyo.

#### Dónde vive el cálculo

| capa | archivo | qué hace |
|---|---|---|
| **Fetch + caché** | `main.py:5202-5551` | las 10 series y `GET /api/benchmarks` (que **strippea las `_d`**: al frontend no le llegan) |
| **Motor canónico** | `performance.py` (285 líneas) | recorte al rango, indexado a 1,0 en la fecha del usuario, resolución diaria, conversión a pesos |
| **Endpoint** | `main.py:11789` `GET /api/insights/performance` | wrapper delgado sobre `performance.performance` |
| **Simuladores flow-matched** | `utils/benchmarkSim.js` (375 líneas) | 7 simuladores "la misma plata en otro lado", **granularidad mensual, siempre en USD-equivalente** |
| **Métricas relativas** | `utils/insightsMetrics.js` | Alpha/Beta/R²/Information Ratio vs S&P, risk-free desde SHV |
| **Reportes** | `reporting/builder.py:749` `benchmark_return_for_period` | S&P mes-a-mes e inflación mensual, **sólo `period_type == "month"`** |
| **IA — packet dedicado** | `ai/builders/insights_benchmarks.py` | migrado al motor canónico (el único que se migró) |
| **IA — chat** | `main.py:23026` `_build_chat_benchmarks` | bloque pre-calculado + `_note` con las reglas de comparación |
| **IA — reportes/mensual** | `ai/builders/reports.py:113`, `monthly.py:81` | su propia resta contra `_bench_cache` |
| **Wrapped** | `main.py:13721` + `wrapped.py:314,372` | S&P YTD calendario e inflación YTD |

#### Quién lo consume

| pantalla | qué benchmark ve | de qué motor sale |
|---|---|---|
| `/analisis` (Métricas) — **gráfico** | el del selector, línea sobre la curva | `perf.benchmark` (motor) en USD y en pesos-con-motor; `shadowPctByMonth` (simuladores) en el resto |
| `/analisis` — **KPI strip** | mismo, entre las mismas dos fechas | `acumuladoPublicado` sobre las filas dibujadas |
| `/analisis` — **veredicto AR** | Plazo fijo UVA · Dólar · Inflación | `compareToMine` (simuladores) + retorno-pesos |
| `/analisis` — **diagnósticos** | `underperform_benchmark` / `outperform_benchmark` (S&P) y `beat/lose_inflation_ars` | `vsSp500`, `vsArs`, `inflationCumArsWindow` |
| `/analisis` — **Métricas Pro** | Alpha/Beta/IR **siempre vs S&P** | `insightsMetrics.js` sobre su propia serie de retornos |
| `/dashboard` y `/` mobile | chip "vs el S&P 500 / vs el dólar quieto" | `BenchmarksLine` (simuladores, **datos crudos**) |
| `/reportes` | "Quedaste X puntos por encima del S&P 500" + chip BEAT/UNDERPERFORM | `reporting/builder.py` |
| `/wrapped` | slides `vs_benchmark` y `vs_inflation` | `wrapped.py` |
| Chat IA | `summary.benchmarks` | `_build_chat_benchmarks` |
| Informe del asesor (`/i/{token}`) | "Suba del dólar MEP en el período" | **con la advertencia escrita** de que no es comparable — el mejor de todos |

#### Lo que NO existe

- **Ninguna validación del parámetro `bench`** en `/api/insights/performance`: cualquier string
  devuelve benchmark vacío en silencio.
- **Ningún campo `benchmark_error`**: yfinance caído ⇒ la curva se sirve sin benchmark y sin
  declararlo.
- **Ningún benchmark sub-mensual en Reportes**: semana y día devuelven `None` por diseño (declarado).
- **Ninguna homogeneización de moneda** en Reportes, Wrapped, el packet `insights.benchmarks`, ni la
  regla de pareo del Merval en el `_note` del chat.

### OBJETIVOS

#### Qué hay — dos conceptos distintos con el mismo nombre

1. **Objetivo de patrimonio** (`/objetivos`): la tabla `goals` con `target_usd`, `target_date`,
   `expected_return_pct`, `label`. Es un objetivo **de patrimonio en dólares**, con una tasa esperada
   como supuesto de proyección.
2. **Expectativa de retorno del perfil** (`/analisis?tab=perfil`): la respuesta del test de perfil
   (`preserve` / `beat_inflation` / `grow` / `aggressive`) cruzada contra el retorno real neto de
   inflación. Es un objetivo **de rendimiento**, y no toca la tabla `goals`.
3. (Y un tercero homónimo: `ObjectiveStat.jsx`, "% de la cartera alineado con tu objetivo", que es
   composición, no avance.)

#### Dónde vive

| capa | archivo | qué hace |
|---|---|---|
| CRUD | `main.py:15162-15220` | 4 endpoints + `GoalIn` (`expected_return_pct` acotado a `[-50, 200]`) |
| Diagnóstico | `goals_diagnostic.py` (270 líneas) | status/ETA/proyección/tasa requerida + sugerencia por sesgo |
| Endpoint diagnóstico | `main.py:15223` | valúa con `behavioral._position_value_usd` y pide el CAGR a `_historical_cagr_global` |
| Velocidad del usuario | `main.py:15320` `_historical_cagr_global` | **motor canónico** (`twr.curva_indexada`) ✅ |
| Fallback muerto | `main.py:15293` `_cagr_from_monthly_rows` | **no lo llama nadie** (`grep` fuera de tests: 0 call sites) |
| Pantalla | `pages/Goals.jsx` (677 líneas) | progreso, 3 escenarios, 3 escenarios alternativos, trayectoria mensual |
| Packet IA | `ai/builders/goal.py` | tercer "capital actual" + escenarios sin aportes |
| Objetivo de rendimiento | `utils/profileMatch.js:611-676` + `ReturnGauge.jsx` | piso anual vs retorno acumulado |

#### Numerador y denominador del avance

- **Numerador (capital actual): tres implementaciones distintas.**
  `Goals.jsx:81` → `computeBrokerValue` (frontend, live, sin `costBasis`, **sin plazos fijos**).
  `main.py:15265` → `behavioral._position_value_usd` (backend, live, otra implementación).
  `ai/builders/goal.py:45` → último `snapshots_medibles` (la foto medida, potencialmente de ayer).
- **Denominador:** `goal.target_usd`, siempre.
- **Velocidad:** `_historical_cagr_global(...).cagr` — el motor canónico, sin `modo` ni `moneda`.

#### Lo que NO existe

- **Aporte mensual** en el modelo (ni columna, ni campo del form, ni parámetro de proyección).
- **Objetivo en pesos** ni ajuste por inflación.
- **Techo en la proyección** (`_project_value` compone sin cota).
- **Plazos fijos** en ninguno de los tres "capital actual".
- Un **motivo** cuando el status es `behind` por falta de dato en vez de por ritmo insuficiente.

---

## Tabla de hallazgos

| # | hallazgo | evidencia | severidad | dónde muerde | causa raíz |
|---|---|---|---|---|---|
| **B-01** | "Plazo fijo UVA" pide `bench=plazo_fijo`, una serie que el backend nunca produjo → benchmark vacío, línea ausente, KPI en "—", opción marcada como disponible | **MEDIDO** | 🔴 | `/analisis` en Pesos | el frontend mapeó a la clave del docstring, no a la que baja el fetcher (`uva`) |
| **B-02** | "Pesos cash (blue)" no tiene entrada en `BENCH_API_KEY` → `if (!k) return` **cancela el refetch**: la línea sigue siendo la del benchmark anterior con la leyenda nueva | **ESTRUCTURAL** | 🔴 | `/analisis` en Pesos | dos listas de claves (`VALID_ARS_BENCH` y `BENCH_API_KEY`) que nadie obliga a coincidir |
| **B-03** | Merval y UVA se resuelven por MES sobre una curva DIARIA — el defecto exacto que el fix del 01/09 vino a matar, aplicado sólo a los tres benchmarks en dólares | **MEDIDO** | 🟠 | `/analisis` en Pesos | el fix se hizo por serie (`sp500_d`, `shv_d`, `gld_d`) en vez de por regla |
| **B-04** | Reportes resta un retorno en PESOS menos el S&P en DÓLARES (y en modo dólares, menos la inflación en pesos): `benchmark_return_for_period` nunca recibe `moneda` | **DEDUCIDO** | 🔴 | `/reportes` — frase, chip e insight | el modo pesos se agregó al retorno y no al benchmark |
| **B-05** | Reportes llama `_fetch_inflation_ar()` + `_fetch_sp500_monthly()` **en cada request**, salteando `_bench_cache`/SWR; si fallan, el "vs S&P" desaparece sin log ni fallback | **ESTRUCTURAL** | 🟠 | latencia de `/reportes` + benchmark que aparece y desaparece | dos call sites que no conocen la caché que el módulo ya tiene |
| **B-06** | `insights.benchmarks` publica `outperform.inflation` cruzando un retorno USD contra inflación ARS, y el prompt instruye "si user < inflation, hay pérdida real" | **ESTRUCTURAL** | 🟠 | chat IA (topic sin UI, pero invocable) | la migración al motor canónico arregló el retorno y no la moneda de los otros dos benchmarks |
| **B-07** | El `_note` del chat da la regla de pareo para S&P e inflación y **no para el Merval**, que se publica en pesos junto a un retorno en dólares | **ESTRUCTURAL** | 🟠 | chat IA | un benchmark agregado después de escribir la regla |
| **B-08** | El "vs S&P" del Dashboard usa `monthly` crudo + total CON plazos fijos; el de Insights usa la cadena MtM + total SIN plazos fijos | **ESTRUCTURAL** | 🟠 | `/dashboard`, `/` mobile vs `/analisis` | `applyMtmToMonthly` importado y no usado en `Dashboard.jsx:43` |
| **B-09** | Crear un plazo fijo desde un broker saca la plata del patrimonio y **no** del flujo del simulador → el usuario "pierde" contra todos los benchmarks por el monto entero del PF | **DEDUCIDO** | 🟠 | veredicto AR, chips del Dashboard, diagnósticos | `create_plazo_fijo` debita cash sin registrar retiro |
| **B-10** | Wrapped compara un pseudo-TWR en USD contra la inflación ARS y contra un S&P de YTD calendario, en un slide **compartible como imagen** | **ESTRUCTURAL** | 🟡 | `/wrapped` | decisión documentada ("el dato cultural"), pero contradice la regla escrita del propio chat |
| **B-11** | La serie diaria es `5y` y la mensual `max`, y **el diario gana con cobertura parcial**: >5 años de historia medida pierden la línea del índice al principio. El docstring afirma que las dos son 5y | **ESTRUCTURAL** | 🟡 | `/analisis` con historia larga | el chequeo es "¿algún punto tiene índice?" en vez de "¿cubre el rango?" |
| **B-12** | `bench` no tiene allowlist en `/api/insights/performance`: cualquier clave da benchmark vacío en silencio; `?bench=dolar_blue&moneda=ars` multiplicaría el blue por el MEP | **ESTRUCTURAL** | ⚪ | endpoint | falta de validación en el borde |
| **B-13** | `BENCH_PORCENTUAL` y `BENCH_EN_ARS` declaran `plazo_fijo` (rama muerta) y el docstring del fetcher dice "plazo_fijo — TNA Minorista BCRA" cuando baja `uva` | **MEDIDO** | ⚪ | mantenimiento | el nombre de producto quedó en el código después de cambiar la fuente |
| **B-14** | `vsShv`, `vsGold`, `vsMerval` e `inflationCum` se calculan en cada render de Insights y **no los consume nadie**; el comentario de `:2315` afirma que sí | **ESTRUCTURAL** | ⚪ | mantenimiento | cards de "Comparativa" retiradas sin limpiar |
| **B-15** | Los simuladores ejecutan TODO el flujo del mes al cierre de FIN de mes, y `compareToMine` contrasta el patrimonio de HOY contra el valor del benchmark al ÚLTIMO CIERRE MENSUAL | **ESTRUCTURAL** | 🟡 | veredicto AR, chips del Dashboard | granularidad mensual declarada ("para MVP es suficiente") que sobrevivió al MVP |
| **B-16** | `reports.py` publica `vs_sp500_pp` como el **promedio aritmético** de los excesos mensuales, rotulado como puntos porcentuales del período | **ESTRUCTURAL** | 🟡 | packet IA de Reportes | promediar en vez de componer |
| **B-17** | `BenchmarksLine` esconde el chip si `|pct| > 500` o el benchmark vale ≤ US$1, sin decir por qué | **ESTRUCTURAL** | ⚪ | `/dashboard` | **PARCHE** sobre el denominador chico del simulador |
| **B-18** | `/api/insights/performance` no chequea `BENCH_TTL`: sólo pregunta si el dict está vacío. Si nadie pega a `/api/benchmarks`, la curva se compara contra un índice arbitrariamente viejo, sin señal | **ESTRUCTURAL** | 🟡 | `/analisis` | dos lecturas de la misma caché con criterios de frescura distintos |
| **O-01** | `cagr: None` (ventana < medio año) se convierte en **0 %**: `(user_cagr_pct or 0)`. El diagnóstico publica "Atrasado · Al ritmo actual, no llegás a la meta" para un usuario que rinde +54 % | **MEDIDO** | 🔴 | `/objetivos`, packet IA `goal` | `or 0` sobre un `None` que significa "no se puede anualizar", no "cero" |
| **O-02** | El objetivo no tiene aportes: ni columna, ni campo, ni parámetro. El packet IA publica `monthly_contribution: 0.0` leyendo una **columna inexistente**, y el prompt razona sobre ella | **ESTRUCTURAL** | 🔴 | `/objetivos`, chat IA sobre objetivos | el modelo de datos nunca incorporó el aporte que la propia pantalla promete calcular |
| **O-03** | Tres "capital actual" distintos para el mismo objetivo (frontend live / backend live con otra valuación / último snapshot medible), y ninguno incluye plazos fijos | **ESTRUCTURAL** | 🟠 | `/objetivos` (barra vs card vs IA) | tres consumidores, tres valuadores |
| **O-04** | `delta_pct_required` anualiza ×12 lineal y `required_annual_pct` compone, **en el mismo return** | **MEDIDO** (28,6 pp y 41,1 pp de brecha) | 🟠 | packet IA `goal` | dos convenciones a tres líneas de distancia |
| **O-05** | El objetivo es siempre `target_usd`, sin opción de pesos ni ajuste por inflación; el selector global de moneda no lo toca | **ESTRUCTURAL** | 🟠 | `/objetivos` | el modelo nació en dólares y el toggle global llegó después |
| **O-06** | `/api/goals/{id}/diagnostic` llama `_historical_cagr_global(conn, uid)` sin `modo` ni `moneda`: la card de arriba obedece el toggle Certero/Estimado y la de abajo no | **ESTRUCTURAL** | 🟠 | `/objetivos` | el toggle se cableó a un endpoint y no al otro |
| **O-07** | `_months_between` ignora el día: con hoy 07/09, un objetivo al 30/09 da **0 meses** → "La fecha objetivo ya llegó". Y el frontend cuenta los meses con otra fórmula | **MEDIDO** | 🟡 | `/objetivos` | aritmética de calendario por (año, mes) |
| **O-08** | `_project_value` compone el CAGR sin cota superior, y `twr` no capa el CAGR por arriba (sólo se niega a anualizar bajo medio año) | **MEDIDO** | 🟡 | `/objetivos`, packet IA | el guard del motor es sobre la VENTANA, no sobre la magnitud |
| **O-09** | El chip "Tu CAGR (X %)" prellena `expected_return_pct` sin clamp; `GoalIn` valida `le=200` → un CAGR mayor devuelve 422 y el usuario ve "Ocurrió un error" | **ESTRUCTURAL** | 🟡 | `/objetivos` (alta) | validación en el servidor sin espejo en el cliente |
| **O-10** | "Expectativa de retorno" compara un retorno real **acumulado** contra un piso **anual**; `monthsCounted` llega a la card y el gauge no lo usa ni lo muestra | **ESTRUCTURAL** | 🟠 | `/analisis?tab=perfil` | una constante en %/año usada como umbral de un acumulado |
| **O-11** | Dos "tasa requerida" a 15 px: frontend (`requiredReturnNoContrib`) y backend (`required_annual_pct`), sobre capitales distintos y con dos formas de contar meses | **ESTRUCTURAL** | 🟡 | `/objetivos` | la card del diagnóstico se agregó sin retirar el escenario que ya lo decía |
| **O-12** | `_cagr_from_monthly_rows` (`main.py:15293`) es código muerto: 0 call sites fuera de tests | **ESTRUCTURAL** | ⚪ | mantenimiento | fallback que sobrevivió a la migración al motor canónico |

---

## Detalle por hallazgo

---

### B-01 🔴 — "Plazo fijo UVA" dibuja nada

**Cadena completa, verificada línea por línea:**

`Insights.jsx:1275` publica la opción como disponible:
```js
{ key: 'plazo_fijo', label: 'Plazo fijo UVA',  available: hasData(bench?.uva) && hasData(bench?.dolar_blue) },
```
El `available` mira `uva` y `dolar_blue`, que **sí** llegan. Pero `Insights.jsx:236-239` traduce a
la clave de API:
```js
const BENCH_API_KEY = {
  sp500: 'sp500', tbill: 'shv', gold: 'gld',
  inflation: 'inflation_ar', merval: 'merval', plazo_fijo: 'plazo_fijo',
}
```
→ `plazo_fijo` viaja tal cual a `/insights/performance?bench=plazo_fijo` (`Insights.jsx:349`).
En el backend, `performance.py:209` hace `bd.get("plazo_fijo_d")` y `:217` `bd.get("plazo_fijo")`.
**Ninguna de las dos existe:** `_benchmarks_fetch_and_cache` (`main.py:5253-5265`) escribe
`inflation_ar, sp500, dolar_blue, shv, gld, merval, uva, sp500_d, shv_d, gld_d, fetched_at`.

**MEDIDO** — traza real de `t1.py`:

```
== A. bench_key='plazo_fijo' con la caché REAL del backend (no existe la serie) ==
 bd.get('plazo_fijo') -> None
 bd.get('plazo_fijo_d') -> None
 benchmark_recortado({}, fechas, 'plazo_fijo') -> []

== B. el mismo pedido con sp500 (sí existe) ==
  [{'date': '2026-06-15', 'index': 1.0}, {'date': '2026-07-15', 'index': 1.04}, {'date': '2026-08-15', 'index': 1.06}, {'date': 'hoy', 'index': 1.06}]
```

`benchmark` vacío ⇒ `benchSeriesUsd` pone `bench: null` en todos los puntos
(`Insights.jsx:871`: `const bp = benchPts[i]` → `undefined` → `benchIdx = null`) ⇒
`Insights.jsx:1696` deja `benchPct = null` en toda la serie ⇒ **la línea no se dibuja** y
`acumuladoPublicado` devuelve `benchPct: null` ⇒ el KPI muestra "—" **con la etiqueta "Plazo fijo
UVA" al lado**.

**Con una salvedad importante:** esto sólo pasa por el camino del motor
(`usaPerfEnPesos === true`). Si la cuenta no tiene curva en pesos, `Insights.jsx:1652` cae al
simulador `simulatePlazoFijoUva`, que **funciona**. O sea: **la opción anda para las cuentas peor
medidas y se rompe para las mejor medidas.** Y el comentario de `Insights.jsx:1236-1238` dice que
las cuentas sin curva son 196 de 758 — es decir, se rompe para las otras ~562.

**Causa raíz:** el frontend mapeó al nombre de producto (`plazo_fijo`, el que figura en el docstring
del fetcher) y no al nombre de la fuente (`uva`, el que el fetcher realmente escribe). El arreglo
mínimo es `plazo_fijo: 'uva'` — pero ojo: `uva` está en `BENCH_EN_ARS`, así que en pesos no se
convertiría (correcto), y el índice UVA en pesos ES el plazo fijo UVA (correcto). Es una línea.

---

### B-02 🔴 — "Pesos cash (blue)" muestra la línea del benchmark anterior

`VALID_ARS_BENCH` (`Insights.jsx:215`) tiene **cinco** claves:
```js
const VALID_ARS_BENCH = ['inflation', 'merval', 'plazo_fijo', 'pesos_cash', 'sp500']
```
`BENCH_API_KEY` (`:236`) tiene **seis** entradas y **ninguna es `pesos_cash`**. Y el efecto que
dispara el fetch empieza así (`Insights.jsx:340-341`):

```js
const k = BENCH_API_KEY[selectedBench]
if (!k) return
```

**`return` sin `setPerf`.** No hay estado de carga, no hay limpieza, no hay error: `perf` conserva
la respuesta del benchmark anterior. Mientras tanto:

- `benchmarkKey` (`:1254`) ya vale `'Pesos cash (blue)'`;
- `usaPerfEnPesos` (`:1240`) sigue en `true` porque `benchSeriesUsd` no se vació;
- `Insights.jsx:1696` sigue leyendo `s.bench`, que son los índices del benchmark **viejo**;
- `chartData` los escribe bajo la clave `[benchmarkKey]` (`:1758`), o sea **con el rótulo nuevo**.

**El caso más probable no es ni siquiera el cambio de selector:** `benchArs` se persiste en
`localStorage` (`:226`), así que un usuario que dejó "Pesos cash" seleccionado vuelve a entrar, el
`loadAll()` inicial pide `/insights/performance?moneda=ars` **sin `bench`** (`Insights.jsx:370`) —
que por default del endpoint es `sp500` (`main.py:11790`) — y el gráfico dibuja **el S&P 500 pasado
a pesos, rotulado "Pesos cash (blue)"**. Y el KPI publica ese número como el rendimiento del peso
cash.

**Causa raíz:** dos listas de claves que describen el mismo conjunto y nadie obliga a que coincidan.
El `if (!k) return` es el guard correcto para un valor inválido de `localStorage` — pero acá el
valor es *válido según la otra lista*.

---

### B-03 🟠 — El fix del ancla diaria no llegó al selector en pesos

El docstring de `_fetch_yf_daily` (`main.py:5418-5432`) explica por qué existe la serie diaria, con
las mediciones de producción del audit del 01/09:

> «la línea del S&P sobre una curva diaria tenía 2 valores distintos (mediana) en 44 filas, 64
> usuarios la veían plana en 0%, y contra el índice real entre las mismas fechas el número difería
> más de 1 pp en 220 de 484 — con el SIGNO dado vuelta en 21.»

El remedio fue bajar `sp500_d`, `shv_d` y `gld_d`. Esos son **exactamente** los tres benchmarks del
selector en dólares (`VALID_USD_BENCH = ['sp500','tbill','gold']`). Los dos que existen sólo en el
selector en pesos —Merval y Plazo fijo UVA— no tienen serie diaria, y `merval` es un índice que
cotiza todos los días: no hay ninguna razón de fuente para que sea mensual.

**MEDIDO** — traza real de `t2.py`, con una curva de usuario de 62 días (20/06 → 20/08):

```
S&P (diario)  : puntos=62  valores_distintos=44  primero={'date': '2026-06-20', 'index': 1.0}  ultimo={'date': '2026-08-20', 'index': 1.089713}
Merval (mensual): puntos=62  valores_distintos=3  primero={'date': '2026-06-20', 'index': 1.0}  ultimo={'date': '2026-08-20', 'index': 1.25}

Ancla del Merval: el 2026-06-20 la curva arranca en index= 1.0 -> base = cierre de FIN de junio (1.200.000),
o sea que TODO lo que el Merval hizo entre el 20 y el 30 de junio (+ 20.0 % desde mayo) queda dentro del ancla.

Primeros 12 puntos del Merval: [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.125]
```

**3 valores contra 44.** Y el ancla es el cierre de **fin** del primer mes: lo que el índice hizo
entre el primer día medido y ese cierre desaparece de la comparación. Con nadie midiendo más de
tres meses (lo dice el mismo docstring), un desfasaje de hasta un mes en el ancla **es** la
comparación.

La inflación es un caso aparte y legítimo: INDEC publica mensual, así que la escalera es honesta.
El Merval no.

**Causa raíz:** el fix se aplicó por serie en vez de por regla. `performance.py:210` decide
`if serie_d and bench_key not in BENCH_PORCENTUAL and _es_diario(serie_d)` — la regla ya está
escrita y es correcta; lo que falta son los datos de dos series.

---

### B-04 🔴 — Reportes: una de las dos comparaciones tiene siempre la moneda cruzada

`reporting/builder.py:749`:
```python
def benchmark_return_for_period(bench, period_type, period_start, period_end, key):
```
**No recibe `moneda`.** Pero `compute_metrics_for_period` sí (`:830`), y en `:1499-1500`:
```python
if _pct_puntas_ars is not None:
    delta_pct = _pct_puntas_ars
```
o sea `delta_pct` pasa a estar **en pesos**. Y 140 líneas más abajo (`:1646-1647`):
```python
vs_sp500 = (delta_pct - sp500_ret) if (delta_pct is not None and sp500_ret is not None) else None
vs_inflation = (delta_pct - inflation_ret) if (...) else None
```

`sp500_ret` es siempre el `^SP500TR` en dólares. `inflation_ret` es siempre el IPC en pesos.

**DEDUCIDO** — supuestos: un mes en que el S&P total return hizo **+2,0 %**, el IPC **+2,5 %**, el
MEP se movió **+5,0 %**, y la cartera del usuario quedó **quieta en dólares (0 %)**.

| selector global | `delta_pct` que publica el motor | `vs_sp500_pct` publicado | verdad | `vs_inflation_pct` publicado | verdad |
|---|---|---|---|---|---|
| **Dólares** | 0,0 % (USD) | 0,0 − 2,0 = **−2,0 pp** ✅ | −2,0 pp | 0,0 − 2,5 = **−2,5 pp** ❌ | +2,5 pp (en pesos rindió 5,0 % contra 2,5 % de inflación) |
| **Pesos** | +5,0 % (ARS) | 5,0 − 2,0 = **+3,0 pp** ❌ | −2,0 pp | 5,0 − 2,5 = **+2,5 pp** ✅ | +2,5 pp |

**En los dos modos hay exactamente una comparación con el signo dado vuelta.** Y ese número no se
queda en un campo: `builder.py:2038-2040` lo convierte en prosa —

```python
if metrics.vs_sp500_pct is not None and abs(metrics.vs_sp500_pct) >= 0.5:
    sign = "encima" if metrics.vs_sp500_pct > 0 else "debajo"
    _frase = f"Quedaste {abs(metrics.vs_sp500_pct):.1f} puntos por {sign} del S&P 500."
```

— y `detectors.py:190-212` lo convierte en un chip con título **"Le ganaste al S&P 500"** cuyo
cuerpo pone los dos números uno al lado del otro:

```python
f"Tu portfolio: {report.metrics.delta_pct:+.1f}%. "
f"S&P 500: {sp:+.1f}%. Diferencia: +{delta:.1f} puntos."
```

Es decir: en modo pesos, la tarjeta muestra un retorno en pesos y un índice en dólares como si
fueran la misma unidad.

**Lo que hace este hallazgo especialmente sensible:** el bloque de comentario de `builder.py:2027-2037`
es un ejemplo de rigor — declara explícitamente el sesgo de `basis='contable'` y agrega una frase de
advertencia al copy. **Y no dice una palabra de la moneda**, porque cuando se escribió no había modo
pesos. El modo pesos de Reportes se deployó el 03/09 (`f6135693` según la memoria del proyecto):
esto es una **regresión reciente sobre una pantalla que acababa de auditarse**.

**Y el arreglo ya está escrito, en otro archivo:** `performance._en_pesos` (`performance.py:157-179`)
hace exactamente esto — pasa el índice a pesos por el TC de cada fecha y re-ancla — y
`BENCH_EN_ARS` ya lista cuáles no hay que tocar. Reportes no lo usa.

---

### B-05 🟠 — Reportes fetchea los benchmarks en cada request

`main.py:33096-33099` (`GET /api/reports/timeline`) y `main.py:33150-33153`
(`GET /api/reports/period/...`):

```python
bench_data = {
    "inflation_ar": _fetch_inflation_ar(),
    "sp500": _fetch_sp500_monthly(),
}
```

Llamadas **directas a los fetchers**, no a `_bench_cache`. Verifiqué que no hay caché intermedia:
`grep -n 'requests_cache\|yf.set_\|session=' backend/main.py` devuelve sólo los dos
`yf.set_tz_cache_location` (el TzCache, que no cachea respuestas). `_fetch_sp500_monthly` llama
`_yf_history(ticker, "max", "1mo")` — la serie completa desde 1988, ~450 filas, por HTTP, **en cada
carga de `/reportes`**, más un HTTP a `api.argentinadatos.com`.

Y ambos fetchers tragan la excepción y devuelven `{}` (`main.py:5286-5287`, `:5370-5371`), sin el
`_safe` que en `_benchmarks_fetch_and_cache` (`:5245-5250`) cae al caché stale. Resultado:
`benchmark_return_for_period` devuelve `None` en `:757` (`if not bench or key not in bench`) y la
comparación **desaparece de la tarjeta sin ningún rastro** — ni log, ni campo, ni copy.

Esto contradice frontalmente el diseño que el propio módulo documenta 27.000 líneas más arriba
(`main.py:5516-5520`): «Sin SWR, el primer user después del restart del worker bloqueaba 15-20s».

> **Confirmado independientemente por el mapa** (`00-mapa-sistema.md:8559`), que ya lo había marcado
> `[V]`. Es el único de mis hallazgos que el mapa ya tenía.

---

### B-06 🟠 — El packet `insights.benchmarks` publica un veredicto cruzando monedas

`ai/builders/insights_benchmarks.py` se migró al motor canónico y su docstring lo explica bien: el
`user_return_pct` ahora es «el TWR publicado del modo Certero» y el S&P sale «entre las MISMAS dos
fechas». Eso está bien.

Lo que la migración no tocó: `_perf.performance(conn, user_id, data, bench_key="sp500", modo=modo)`
(`:94`) **no pasa `moneda`**, así que `user_pct` es el TWR **en dólares**. Y a continuación
(`:131-142`) se calculan sobre la misma ventana:

- `inflation_pct` — el IPC compuesto, **en pesos**;
- `dolar_pct` — la variación del blue, que **es** la devaluación.

Y después (`:149-158`):
```python
deltas = {"vs_sp500": _delta(user_pct, sp500_pct),
          "vs_inflation": _delta(user_pct, inflation_pct),
          "vs_dolar_blue": _delta(user_pct, dolar_pct)}
outperform = {..., "inflation": (deltas["vs_inflation"] > 0) if ... else None, ...}
```

`vs_sp500` es correcto (USD contra USD). Los otros dos no. Y el prompt
(`ai/prompts.py:1200-1201`) le pide al modelo que lo afirme:

> «vs Inflación AR — el mínimo aceptable en Argentina es ganarle a la inflación. **Si user < inflation, hay pérdida real.**»

**Esto es exactamente lo que el `_note` del chat prohíbe por escrito** (`main.py:23172-23173`):
«NUNCA compares el retorno USD directo contra la inflación en pesos». Dos módulos del mismo
subsistema, con la regla opuesta.

**Atenuante — y es el que decide la severidad:** el topic **no tiene consumidor en la UI real**.
`grep -rn 'topic="insights' frontend/src --include='*.jsx'` devuelve `insights.evolution`,
`insights.drawdown`, `insights.attribution` e `insights.observation`. `insights.benchmarks` sólo
aparece en `frontend/src/utils/demo.js:1337` y `:2932`. Pero el topic **está registrado**
(`ai/registry.py:84`) y `/api/ai/analyze` lo acepta, así que es alcanzable. Por eso 🟠 y no 🔴, y
por eso es la pregunta 4.

---

### B-07 🟠 — El Merval del chat no tiene regla de pareo

`_build_chat_benchmarks` (`main.py:23026-23180`) es, de lejos, **el mejor trabajo de esta familia**:
pre-calcula server-side, declara el rezago del INDEC (`ytd_through`), ancla el blue a la ventana del
usuario en vez de a diciembre («el review demostró 23pts de error»), y cierra con un `_note` que le
da al modelo las reglas de comparación. Vale reconocerlo.

Pero el `_note` (`:23163-23178`) sólo cubre **dos** pares:

> «Comparaciones correctas: vs S&P 500 → `usd_ytd_pct` contra `sp500_total_return_usd.ytd_pct`
> (ambos USD…). Vs inflación → `ars_ytd_pct_approx` contra `inflation_ar.ytd_pct` (ambos pesos…)»

Y el payload publica **tres** benchmarks: `merval_ars.ytd_pct` (`:23144`) está ahí, en pesos, sin
ninguna instrucción de con qué campo aparearlo. El prompt del chat (`main.py:28492`) además lo
nombra explícitamente en la lista de lo que trae el bloque. Un modelo que compara
`usd_ytd_pct` contra `merval_ars.ytd_pct` está haciendo la resta prohibida, y nada se lo dice.

**Segundo defecto, más chico:** `sp_ytd = _pct_move(sp500, sp_cur_key, dec_prev)` (`:23100`) es YTD
**calendario**, mientras el `usd_ytd_pct` del usuario arranca en `ytd_since`, que puede ser marzo.
El `_note` lo delega al modelo («si `ytd_since` no es enero, la ventana del user es más corta que la
del índice — mencionalo»). Es honesto, pero es un desalineamiento de período resuelto con una
instrucción en lenguaje natural en vez de con aritmética. El packet `insights.benchmarks` demuestra
que se puede hacer bien (`window_from`/`window_to` y el benchmark entre esas dos fechas).

---

### B-08 🟠 — Dos "vs S&P 500" para el mismo usuario

`BenchmarksLine` (`frontend/src/components/BenchmarksLine.jsx`) vive en el Dashboard
(`Dashboard.jsx:1039`) y en el Home mobile (`HomeMobile.jsx:439`). Su cálculo (`:27-52`):

```js
const globalMonthly = useMemo(() => (monthly || []).filter(m => m.broker === 'global'), [monthly])
const sp500Sim = useMemo(() => simulateSp500(globalMonthly, bench?.sp500), [globalMonthly, bench])
...
const delta = totalPortfolio - benchFinal
const pct = (delta / benchFinal) * 100
```

Contra lo que hace Insights con las mismas dos funciones:

| | Dashboard / Home | Insights |
|---|---|---|
| serie mensual | `monthly.filter(broker==='global')` **crudo** | `applyMtmToMonthly(...)` (`Insights.jsx:535`) |
| `capital_inicio` del primer mes (= la semilla de unidades del benchmark) | el **contable** | el **snapshot de mercado** del mes anterior |
| patrimonio del usuario | `totalValue` = brokers **+ `pf.valueUsd`** (`Dashboard.jsx:212`) | `totalPortfolio` = sólo brokers (`Insights.jsx:413`) |

Las dos diferencias van en direcciones distintas y no se cancelan. La primera cambia el
**denominador** (el valor final del benchmark simulado); la segunda cambia el **numerador**.

**La prueba de que es un olvido y no una decisión:** `Dashboard.jsx:43` importa
`applyMtmToMonthly` y `grep -n 'applyMtmToMonthly' frontend/src/pages/Dashboard.jsx` devuelve **una
sola línea: el import.** Nunca se llama.

El comentario de `Dashboard.jsx:1035-1038` dice que esto «es solo el descubrimiento» y que el
detalle vive en `/insights` — o sea que el diseño asume que el usuario va a hacer clic en "Ver
comparativa" y encontrar el mismo número más grande. Encuentra otro.

---

### B-09 🟠 — El plazo fijo te hace perder contra todo

`create_plazo_fijo` (`main.py:9120-9145`), cuando el PF sale de un broker que ya está en Rendi:

```python
_autodeposit_if_overdraw(conn, uid, p.source_broker, float(p.capital), p.fecha_inicio)
_adjust_broker_cash(conn, uid, p.source_broker, -float(p.capital))
```

Leí `_adjust_broker_cash` completa (`main.py:9750-9790`): actualiza `positions.invested` de la fila
cash (o la crea). **No toca `monthly_entries` ni registra una operación de retiro.** Es correcto para
la contabilidad interna —el PF sigue siendo del usuario, no salió de su patrimonio— pero rompe la
comparación:

- **numerador:** `totalPortfolio` en Insights (`:413`) suma `computeBrokerValue` sobre `brokers`, o
  sea **posiciones**. El PF entra aparte, como porción sintética de la torta (`Insights.jsx:2149-2152`
  con `pfSliceUsd`). El PF **no está** en `totalPortfolio`.
- **denominador:** `simulateBenchmark` (`benchmarkSim.js:96`) hace
  `const net = (m.deposits || 0) - (m.withdrawals || 0)`. Como no se registró retiro, **el flujo del
  benchmark queda intacto**.

**DEDUCIDO** — supuestos: cartera de US$ 10.000, el usuario pone US$ 3.000 en un plazo fijo desde su
broker, todo lo demás quieto y el benchmark plano.

- Antes: `totalPortfolio = 10.000`, `benchFinal = 10.000` → **0,0 %**.
- Después: `totalPortfolio = 7.000`, `benchFinal = 10.000` → **−30,0 %**.

El usuario "perdió 30 puntos contra el S&P" por mover plata de un bolsillo al otro. Y peor:
`_autodeposit_if_overdraw` puede **agregar un depósito** si el PF supera el cash disponible, lo que
agranda el flujo del benchmark al mismo tiempo que achica el patrimonio.

Esto muerde en `vsPlazoFijo`, `vsDolar` y el veredicto de inflación (`verdictItems`, `:2578-2603`),
en `underperform_benchmark` / `outperform_benchmark` (`diagnostics.js:181-198`) y en el chip del
Dashboard — **que, por B-08, sí incluye el PF en el numerador y por eso no sufre este bug**. Las dos
pantallas se equivocan de maneras opuestas.

**Relacionado con P-003** («el alta de un plazo fijo debita el cash del broker y el borrado no lo
devuelve»): es la misma raíz — el PF entra y sale del patrimonio sin dejar rastro en el ledger de
flujos.

---

### B-10 🟡 — El Wrapped compara dólares contra pesos, en una imagen para compartir

`wrapped.py:372-376`:
```python
def _slide_vs_inflation(twr_user, inflation_ytd, year):
    """Sólo aplica cuando hay inflación AR del año disponible. La idea: aún
    rindiendo positivo en USD, el dato cultural es 'le ganaste a la inflación
    en ARS'. Lo dejamos opcional."""
    delta = twr_user - inflation_ytd
```

**El docstring admite la mezcla y la justifica.** Según la regla transversal de esta auditoría eso
la convierte en decisión de diseño, no en descuido — y por eso queda en 🟡. Pero la decisión es
publicar, en un slide compartible, la resta que el `_note` del chat prohíbe explícitamente. Y el
título del slide es literal: **"Le ganaste a la inflación AR"**. La cuenta correcta —componer el
retorno USD con la devaluación y recién ahí comparar contra el IPC— es la que
`_build_chat_benchmarks` ya hace (`main.py:23130-23133`, `ars_ytd_pct_approx`).

Dos defectos más en el mismo slide, éstos sin justificación escrita:

1. **`_slide_vs_benchmark` promedia deltas de monedas distintas** (`:344`):
   `avg_delta = sum(deltas)/len(deltas)`, donde `deltas` puede tener el delta contra el S&P (USD) y
   el delta contra el Merval (ARS). De ese promedio sale el título "Le ganaste a los índices" / "Los
   índices te ganaron". Hoy `merval_ytd` no se llena (el comentario de `main.py:13723-13724` dice
   «MERVAL queda pendiente de pipeline propio»), así que la rama está muerta — pero está escrita
   mal, y el docstring de la función afirma «vs MERVAL (en USD)», que sería falso el día que se
   llene.
2. **Ventanas distintas.** `benchmarks["sp500_ytd"]` (`main.py:13736-13738`) es
   `último_cierre_del_año / cierre_de_diciembre_anterior` — YTD **calendario completo**. `twr_user`
   sale de `_twr_for_period(_monthly_for_year(...))` (`wrapped.py:49`), que itera **sólo los meses
   que el usuario tiene cargados**. Un usuario que arrancó en junio ve su junio-diciembre comparado
   contra el enero-diciembre del índice.

Y encima de todo eso, `twr_user` **no es TWR** — es la fórmula que 1A documentó en DIV-092
(divide por `capital_inicio` en vez de `capital_inicio + 0,5·flujos`). No lo re-audito; lo anoto
porque es el número que este slide compara.

---

### B-11 🟡 — El diario gana con cobertura parcial

`_fetch_yf_daily` (`main.py:5418`) tiene `period: str = "5y"` por default y su docstring cierra con:

> «Mismo período que el mensual (5y) para que las dos series cubran lo mismo.»

**Es falso.** `_fetch_sp500_monthly` (`main.py:5344-5352`) y `_fetch_yf_monthly` (`:5391`) usan
`"max"`, y el comentario de `:5337-5342` explica por qué: «Medido en producción: 56 de 673 usuarios
tienen `monthly_entries` anteriores al arranque de la serie de 5 años».

La consecuencia está en `performance.py:210-215`:
```python
if serie_d and bench_key not in BENCH_PORCENTUAL and _es_diario(serie_d):
    bench = benchmark_recortado(serie_d, fechas, bench_key)
    if any(p.get("index") is not None for p in bench):
        resolucion = "diaria"
    else:
        bench = []
```
El chequeo es **"¿algún punto tiene índice?"**, no "¿cubre el rango?". Con una curva de 7 años, la
serie diaria cubre los últimos 5 y `_benchmark_diario` devuelve `index: None` para los dos primeros
(`performance.py:80`: comportamiento correcto y deliberado — «la línea no se dibuja ahí, en vez de
dibujarse relativa a un valor que no es suyo»). Pero como *algunos* puntos sí tienen índice, gana el
diario y **la serie mensual, que sí cubría los 7 años, no se consulta**.

Impacto hoy: bajo (nadie tiene más de tres meses medidos, según el propio código). Pero es una
trampa que se arma sola a medida que la base envejece, y el docstring que la tapa hace que no se vea.

---

### B-12 ⚪ — `bench` sin allowlist

`main.py:11789-11791`:
```python
def insights_performance(
    bench: str = "sp500",
```
Sin `Literal[...]`, sin `Query(pattern=...)`, sin chequeo contra las claves conocidas. Cualquier
string devuelve `benchmark: []` en silencio — que es, textualmente, el modo de falla de B-01.

Además, la conversión a pesos se decide por lista negra (`performance.py:221`):
```python
if moneda == twr.MONEDA_ARS and bench and bench_key not in BENCH_EN_ARS:
```
`dolar_blue` **no está** en `BENCH_EN_ARS`, así que `?bench=dolar_blue&moneda=ars` multiplicaría el
índice del blue por el MEP: la devaluación contada dos veces. No es alcanzable desde la UI (el
selector no ofrece esa clave) — de ahí ⚪ —, pero una allowlist explícita cierra las dos puertas de
una y convierte B-01 en un 400 en vez de en una línea que no aparece.

---

### B-13 ⚪ — Rama muerta y docstring falso alrededor de `plazo_fijo`

`_benchmarks_fetch_and_cache` (`main.py:5216-5230`) dice:
> «Fetch los **7** benchmarks externos… • `plazo_fijo` — TNA Minorista BCRA (% anual mensual)»

El código (`:5253-5265`) escribe 7 mensuales, y el séptimo es `uva`, no `plazo_fijo`. `_fetch_uva_monthly`
(`:5480-5495`) explica correctamente por qué se reemplazó («argentinadatos.com NO tiene una serie
histórica de TNA Minorista del BCRA»). El docstring del orquestador no se actualizó.

Y la clave fantasma se propagó a `performance.py`:
```python
BENCH_PORCENTUAL = ("inflation_ar", "plazo_fijo")
BENCH_EN_ARS = ("merval", "uva", "plazo_fijo", "inflation_ar")
```
**MEDIDO** (`t1.py`, sección C) — las dos tuplas se imprimieron tal cual. Ninguna de las dos
menciones puede activarse nunca. Peor: `plazo_fijo` en `BENCH_PORCENTUAL` significaría "se compone
como % mensual", cuando el UVA es un **nivel** que se rebasea. Si alguien arregla B-01 mapeando
`plazo_fijo: 'plazo_fijo'` y agregando el fetcher, hereda una clasificación equivocada.

---

### B-14 ⚪ — Simulaciones que nadie mira, y un comentario que dice lo contrario

`Insights.jsx:2166-2173` computa siete simulaciones y `:2191-2197` siete comparaciones. `grep`
sobre el archivo completo:

| variable | definida en | consumida en |
|---|---|---|
| `vsSp500` | 2191 | 2313 (diagnósticos) ✅ |
| `vsDolar` | 2194 | 2589 (veredicto) ✅ |
| `vsPlazoFijo` | 2196 | 2585 (veredicto) ✅ |
| `vsArs` | 2197 | 2314 (diagnósticos) ✅ |
| **`vsShv`** | 2192 | **— nunca** |
| **`vsGold`** | 2193 | **— nunca** |
| **`vsMerval`** | 2195 | **— nunca** |
| **`inflationCum`** | 2173 | **— nunca** |

Y el comentario de `Insights.jsx:2315-2318` afirma:
> «`inflationCum` global (sobre `globalMonthly`) **se usa en otros lugares de la UI**, pero para el
> diagnóstico… pasamos la inflación RECORTADA»

La segunda mitad es cierta y el fix que describe es bueno. La primera mitad es falsa: `inflationCum`
no se usa en ningún lado. Es una **cita del código incorrecta** dentro del propio código.

Costo: 4 simulaciones sobre toda la historia mensual en cada render, y un lector que cree que hay un
consumidor.

---

### B-15 🟡 — Los simuladores son mensuales y comparan contra el patrimonio de hoy

Dos desajustes de período, los dos declarados en el header de `benchmarkSim.js:11-13`
(«Granularidad: mensual… Para MVP es suficiente»):

1. **Todo el flujo del mes se ejecuta al cierre de fin de mes.** `simulateBenchmark:93-101`:
   `const price = priceLookup(k) ?? firstPrice; if (price > 0) units += net / price`. Un depósito
   del 2 compra al cierre del 31. En un mes en que el índice hizo +8 %, el benchmark simulado compra
   8 % más caro de lo que hubiera comprado el usuario.
2. **`compareToMine` mezcla dos fechas** (`Insights.jsx:2183-2189`):
   `const delta = totalPortfolio - benchmarkFinal`, donde `totalPortfolio` es el valor **live de
   hoy** y `benchmarkFinal` es `series[series.length-1].value`, o sea el valor del benchmark al
   **último mes de `globalMonthly`**. En la práctica el último mes es el mes en curso y las series
   mensuales de yfinance/argentinadatos traen la barra parcial al día de hoy, así que el desfasaje
   real es de horas y no de semanas — **pero eso es una coincidencia de las fuentes, no una garantía
   del código**. Con `inflation_ar`, que INDEC publica con 1-2 meses de rezago, la coincidencia no
   se da; por eso existe el parche `inflationCumArsWindow`.

El contraste que lo vuelve un hallazgo y no una nota: el motor del backend
(`performance.benchmark_recortado`) resuelve **por fecha**, con el cierre del día o del último hábil
anterior, y cierra en `"hoy"` con `valor_live`. Las dos cosas conviven en la misma pantalla: el
gráfico está bien y el veredicto de abajo está a un mes de resolución.

---

### B-16 🟡 — `vs_sp500_pp` es un promedio aritmético

`ai/builders/reports.py:113-143`:
```python
for md in monthly_deltas:
    ...
    if sp_val and sp_prev:
        sp_ret = (sp_val - sp_prev) / sp_prev * 100
        vs_sp500_values.append(md["delta_pct"] - sp_ret)
...
vs_sp500_avg = round(sum(vs_sp500_values) / len(vs_sp500_values), 2)
```

El campo se publica como `"vs_sp500_pp"` y el docstring del packet (`:30`) lo describe como
«promedio de `vs_sp500_pct` mensual». Es literal — pero el promedio aritmético de excesos mensuales
no es el exceso del período: con retornos compuestos, la diferencia crece con la volatilidad y con
el largo de la serie. El modelo lo va a citar como "quedaste X puntos abajo del S&P", que es lo que
el nombre del campo sugiere.

Además el comentario lo llama «heurística» (`:113`), lo cual es honesto, y `md["delta_pct"]` sale del
motor de Reportes — que hereda B-04 si el reporte está en pesos.

---

### B-17 ⚪ — PARCHE: el chip que se esconde

`BenchmarksLine.jsx:23-24, 42-48`:
```js
const MIN_SIGNIFICANT_BENCH_USD = 1
const MAX_DISPLAY_PCT = 500
...
if (benchFinal <= MIN_SIGNIFICANT_BENCH_USD) return null
if (Math.abs(pct) > MAX_DISPLAY_PCT) return null
```
Documentado en el header como «Outliers del cálculo (pct > 500% o bench ≤ $1) → ese benchmark se
omite».

**Es un parche, no un guard.** Un `benchFinal` de US$ 0,50 no es un outlier de mercado: es el
simulador arrancando de un `capital_inicio` de casi cero (o de la semilla contable cruda de B-08) y
recibiendo flujos que no lo levantan. El síntoma se esconde; la causa —el denominador del simulador
puede ser cualquier cosa— sigue viva en `compareToMine` (Insights), que **no tiene estos límites** y
publica el número igual.

**Dónde más muerde la misma causa:** `verdictItems` (los tres veredictos AR), `diagnostics.js`
`underperform_benchmark` / `outperform_benchmark`, y el packet de IA de Insights.

---

### B-18 🟡 — Dos criterios de frescura sobre la misma caché

`main.py:11817` (`/api/insights/performance`):
```python
data = _bench_cache["data"] or {}
if not data:
    try:
        data = _benchmarks_fetch_and_cache()
```
Sólo pregunta si el dict está **vacío**. `GET /api/benchmarks` (`main.py:5523`, `:5531`) sí compara
`cache_age < BENCH_TTL` y dispara el refresh SWR. Si nadie pega a `/api/benchmarks`, la curva de
Métricas se compara contra un índice arbitrariamente viejo, y la respuesta **no trae ningún campo
que lo declare** — hay `benchmark_resolucion` pero no `benchmark_fetched_at`.

En la práctica `Insights.jsx:365` pide `/benchmarks` en el mismo `loadAll()`, así que la caché se
calienta — pero por orden de llegada, no por diseño, y el fetch del benchmark
(`useEffect` de `:338`) puede resolver antes.

Y el `except Exception: data = {}` de `:11821-11822` cierra el círculo: yfinance caído ⇒ curva sin
benchmark ⇒ ningún campo lo dice.

> Confirmado por el mapa (`00-mapa-sistema.md:5432-5433`), cuyas dos citas verifiqué.

---

### O-01 🔴 — "No puedo anualizar" se publica como "rendís 0 %"

Éste es el peor hallazgo de la tanda, y es la continuación directa del trabajo que 1A elogió.

`_historical_cagr_global` (`main.py:15320-15391`) es el motor canónico y está bien: cuando la
ventana no llega a medio año devuelve `cagr: None` **con el acumulado al lado** y una razón redactada:

```python
if c.get("cagr") is None:
    return {**base, "cagr": None,
            "reason": ("El período medido es más corto que medio año: anualizarlo "
                       "amplificaría el ruido hasta un número que no significa nada. "
                       "Te mostramos lo que rindió en el período, que sí es exacto.")}
```

`base` incluye `total_return_pct`, `dias`, `desde`, `hasta`. Todo lo necesario para decirlo bien.

`GET /api/goals/{gid}/diagnostic` (`main.py:15271`) hace:
```python
user_cagr_pct = _historical_cagr_global(conn, uid).get("cagr")
```
**Sólo `.cagr`.** Y `goals_diagnostic.py:215`:
```python
user_cagr_frac = (user_cagr_pct or 0) / 100
```

`None or 0` → `0`. Un `None` que significa "no se puede anualizar esta ventana" se convierte en la
afirmación "este usuario rinde cero por ciento".

**MEDIDO** — traza real de `t3.py`, sección A. Mismo objetivo (US$ 20.000 al 2028-09-01), mismo
capital actual (US$ 10.000), lo único que cambia es el CAGR:

```
== A. el CAGR None (ventana < medio año) se convierte en 'rendís 0 %' ==
  user_cagr_pct=None -> {'status': 'behind', 'eta_months_at_current_rate': None, 'projected_value_at_target_date': 10000.0, 'required_annual_pct': 41.42, 'delta_pct_required': 35.16}
  diagnostic: Al ritmo actual, no llegás a la meta sin aportes adicionales.
  el MISMO usuario con su acumulado real (+54 %) -> ahead | ETA 20
```

**"Atrasado · Al ritmo actual, no llegás a la meta" contra "Adelantado · ETA 20 meses".** Y
`projected_value_at_target_date` sale exactamente igual al capital de hoy — la proyección afirma que
en dos años el usuario va a tener los mismos US$ 10.000.

El `+54 %` no es inventado: es el número que el docstring de `_historical_cagr_global`
(`main.py:15352`) usa como ejemplo real («el uid 966 leía +16.841 % anual donde el motor canónico
mide **+54,0 % sobre 44 días**»). O sea: el usuario cuyo caso motivó el fix es exactamente el que
hoy recibe "no llegás a la meta".

**Y el efecto en cascada:** `status = 'behind'` dispara `_pick_dominant_bias` (`:255-259`), así que
el usuario recibe además una sugerencia correctiva sobre su sesgo dominante ("Operás demasiado",
"Vendés ganadoras muy rápido") **por un diagnóstico que se basa en un cero fabricado**. La misma
cadena la repite el packet de IA (`ai/builders/goal.py:77, 90-94`), que llama a las dos funciones
igual.

**Ésta es la P-247, y es la pregunta que más necesito contestada.**

---

### O-02 🔴 — El objetivo no tiene aportes, en ningún lado

Tres capas, la misma ausencia:

**1. El modelo de datos.** `main.py:1498-1506`:
```sql
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    target_usd REAL NOT NULL,
    target_date TEXT NOT NULL,
    expected_return_pct REAL NOT NULL DEFAULT 10,
    label TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```
No hay aporte. `GoalIn` (`:15149-15153`) tampoco, y el formulario (`Goals.jsx:527-612`) tiene cuatro
campos: etiqueta, objetivo USD, fecha y rendimiento esperado.

**2. El motor.** `goals_diagnostic.py:96-101` y `:117-121` lo declaran:
```python
def _required_monthly_rate(current_value, target_value, months):
    """Tasa mensual compuesta requerida para ir de current → target en `months` meses,
    SIN aportes. …"""
def _project_value(current_value, monthly_rate, months):
    """Valor proyectado a `months` con rate compuesto mensual y sin aportes."""
```
Está declarado, sí. Pero el **veredicto** (`on_track` / `behind` / `unreachable`) se construye sobre
ese modelo, y el veredicto es lo que el usuario lee. Para cualquier ahorrista que aporta todos los
meses —el usuario objetivo declarado de la pantalla— `required_monthly` está sobreestimado y el
status es "Atrasado" por construcción.

**3. El packet de IA lee una columna que no existe.** `ai/builders/goal.py:35`:
```python
monthly_contribution = float(g.get("monthly_contribution") or 0)
```
`g = dict(row)` sobre una fila de `goals`, que no tiene esa columna → `.get` devuelve `None` → `0.0`.
Se publica en el payload (`:128`) y el prompt (`ai/prompts.py:1337-1338`) se lo anuncia al modelo,
le pide como foco *«Sensibilidad a los aportes — qué pasa si suspenden / aumentan / mantienen»* y le
da como ejemplo de insight *«el aporte mensual de US$ 500»*. **El modelo tiene siempre US$ 0,00 y una
instrucción para razonar sobre él.** La única definición de `monthly_contribution` en el repo está en
`backend/tests/test_ai_builders_phase2.py:106`, que crea la tabla con esa columna — o sea que el
test pasa y producción no.

**Y la contradicción está escrita en la pantalla.** El empty state de `/objetivos`
(`Goals.jsx:217-218`):
> «Creá tu primer objetivo (por ejemplo, USD 8.000 en 1 año) y **vamos a calcular cuánto necesitás
> aportar por mes** para alcanzarlo.»

Lo calcula (`requiredMonthly`, `Goals.jsx:623-633` — y la fórmula está bien, ver O-12) y lo muestra
en la card "Con aportes mensuales". **Y después no lo guarda, y el diagnóstico de abajo lo ignora.**

---

### O-03 🟠 — Tres capitales actuales para el mismo objetivo

| consumidor | de dónde saca el capital | características |
|---|---|---|
| **Barra de progreso** (`Goals.jsx:81-85`) | `brokers.reduce((s,b) => s + computeBrokerValue(positions, pr, b, tcValuacion, tcCedear, tcCripto).value, 0)` | live, frontend, **sin el parámetro `costBasis`** (P-251), sin plazos fijos |
| **Card de diagnóstico** (`main.py:15258-15268`) | `Σ behavioral._position_value_usd(p, prices, tc_blue, tc_cedear)` | live, backend, **otra implementación**, sin plazos fijos |
| **Packet de IA** (`ai/builders/goal.py:45-55`) | `SELECT total_value FROM snapshots_medibles … ORDER BY date DESC LIMIT 1` | la **última foto medida**, potencialmente de ayer o de la semana pasada |

Los tres alimentan el mismo objetivo, y de los tres salen:
- el **% de la barra** (`progressPct`, `Goals.jsx:288`),
- el **status y la ETA** de la card de abajo,
- el **`progress_pct`** que la IA cita.

El tercero está bien pensado y su comentario lo explica (`goal.py:39-44`: preferir
`snapshots_medibles` para que una foto al costo no acerque falsamente la meta) — pero es una tercera
respuesta a la misma pregunta, en la misma pantalla.

**Y ninguno de los tres incluye plazos fijos.** Un usuario con la mitad del patrimonio en PF ve su
objetivo a la mitad de camino de donde está.

---

### O-04 🟠 — Dos anualizaciones de la misma tasa, en el mismo `return`

`goals_diagnostic.py:249-251`:
```python
delta_pp = None
if required_monthly is not None:
    delta_pp = (required_monthly - user_monthly) * 12 * 100  # diferencia anualizada en pp
```
y 16 líneas más abajo, `:267`:
```python
'required_annual_pct': round(((1 + required_monthly) ** 12 - 1) * 100, 2) if required_monthly is not None else None,
```

Una multiplica por 12. La otra compone. Las dos salen en el mismo diccionario, y las dos llegan a la
UI: `required_annual_pct` es el chip "**Necesario · X %/año**" (`Goals.jsx:475-479`) y
`delta_pct_required` viaja al packet de IA (`ai/builders/goal.py:143`).

**MEDIDO** — traza real de `t3.py`, sección B:

```
== B. el mismo payload publica DOS anualizaciones distintas de la misma tasa ==
  10000->20000 en 12 meses: mensual=5.946%  required_annual_pct(compuesto)=100.0%  delta_pct_required(x12)=71.4%  brecha=28.6 pp
  10000->15000 en 6 meses: mensual=6.991%  required_annual_pct(compuesto)=125.0%  delta_pct_required(x12)=83.9%  brecha=41.1 pp
```

**28,6 y 41,1 puntos porcentuales de brecha entre dos campos que describen la misma cosa.** El
comentario en línea dice «diferencia anualizada en pp», que es exactamente lo que el otro campo
también dice ser.

---

### O-05 🟠 — El objetivo es siempre en dólares

`target_usd REAL NOT NULL` y nada más. `grep -rn 'target_ars\|goal_currency' backend/` → **0 resultados.**

Consecuencias:
- El **selector global de moneda** (que vive en el shell y controla Dashboard, Métricas y Reportes)
  no toca `/objetivos`: la pantalla está fija en USD.
- No hay **ajuste por inflación**. `expected_return_pct` es una tasa nominal en dólares, así que un
  objetivo a 5 años dice cuántos dólares nominales hacen falta, no cuánto poder de compra.
- Un usuario que ahorra y gasta en pesos —el usuario argentino, que es el usuario— no puede expresar
  "quiero tener el equivalente a un auto".

Es una decisión de producto tanto como técnica (pregunta 7). Lo pongo en 🟠 y no ⚪ porque el resto de
la app **ya** resolvió esta misma pregunta: `twr` mide en pesos con el TC de cada fecha,
`performance._en_pesos` pasa un índice a pesos, Reportes tiene modo pesos. Objetivos es la única
superficie que se quedó afuera del trabajo de monedas.

---

### O-06 🟠 — El diagnóstico ignora el toggle que está 200 píxeles más arriba

`Goals.jsx:53` (la card grande):
```js
api.get(`/goals/cagr?modo=${modoRend}`).catch(() => null),
```
con `modoRend` del componente `<ModoRendimiento>` (`:174`).

`Goals.jsx:437` (la card del diagnóstico, dentro de cada `GoalCard`):
```js
api.get(`/goals/${goalId}/diagnostic`)
```
sin parámetros. Y el endpoint (`main.py:15271`) llama `_historical_cagr_global(conn, uid)` sin
`modo` ni `moneda`, o sea **certero/USD siempre** (`:15321-15322`).

El usuario mueve el toggle a "Estimado", el número grande de arriba cambia, y el "Atrasado · ETA · 
Necesario X %/año" de abajo se queda quieto. Peor: en Estimado el motor suele **sí** publicar un
CAGR donde en Certero devuelve `None`, así que el toggle podría ser justamente el remedio de O-01 —
y el diagnóstico no lo ve.

Es la **P-058**, confirmada.

---

### O-07 🟡 — Los meses se cuentan de dos formas, y ninguna mira el día

`goals_diagnostic.py:85-93`:
```python
months = (td.year - n.year) * 12 + (td.month - n.month)
return max(0, months)
```

**MEDIDO** — traza real de `t3.py`, sección C (hoy = 2026-09-07):
```
  hoy=2026-09-07  target=2026-09-30  -> months_left = 0
  hoy=2026-09-07  target=2026-10-01  -> months_left = 1
  hoy=2026-09-07  target=2026-09-08  -> months_left = 0
```

Un objetivo al **30 de septiembre**, con 23 días por delante, da 0 meses → la rama `months_left <= 0`
(`:195-211`) publica **"La fecha objetivo ya llegó y todavía estás a US$ X de la meta"**. Y un
objetivo al 1º de octubre, un día después, da 1.

El frontend cuenta distinto (`Goals.jsx:253`):
```js
const monthsLeft = Math.max(0, Math.round((targetDate - now) / (1000*60*60*24*30.4375)))
```
Para el 30/09 esto da `Math.round(23/30.4375) = 1`. Así que **la misma tarjeta dice "1 mes" arriba
(en la línea del header) y "la fecha ya llegó" abajo (en el diagnóstico)**.

---

### O-08 🟡 — La proyección compone sin techo

`goals_diagnostic.py:117-121`:
```python
def _project_value(current_value, monthly_rate, months):
    if monthly_rate is None or current_value <= 0:
        return current_value
    return current_value * ((1 + monthly_rate) ** months)
```
Sin cota. Y el motor que provee la tasa **tampoco capa por arriba** — `twr.py:2165-2172`:
```python
cagr = None
if publicable and legs > 0 and idx > 0 and ventana_desde:
    ...
    if años >= 0.5:                # bajo medio año, anualizar es propaganda
        cagr = idx ** (1.0 / años) - 1.0
```
El guard es sobre la **ventana**, no sobre la **magnitud**. Una cuenta cripto con 6 meses medidos y
+150 % acumulado publica un CAGR de `2,5² − 1 = +525 %`, legítimamente anualizado.

**MEDIDO** — traza real de `t3.py`, sección D, con una tasa anual de +500 % compuesta 120 meses:
```
  _project_value(10000, (1+5.0)**(1/12)-1, 120) = 604,661,760,000 USD
```
Seiscientos mil millones de dólares como `projected_value_at_target_date`, que va derecho al copy
(`:237`: `f'Vas por encima del ritmo necesario. Proyección: US$ {projected:,.0f}…'`) y al packet de
IA (`goal.py:111-117`, campo `projected_value_usd`).

`_eta_months` sí tiene un guard (`> 600` meses → `None`, `:112-113`), pero es un guard por el lado
lento: no ayuda con un ritmo absurdamente rápido.

**Contexto honesto:** el fix del 16/08 mató el caso grave (el +16.841 % anual sobre 44 días ya no se
publica). Lo que queda es el residuo: un CAGR grande pero legítimo, compuesto sin límite sobre un
horizonte largo.

---

### O-09 🟡 — El chip "Tu CAGR" puede generar un objetivo que no se puede guardar

`Goals.jsx:565-568`:
```jsx
<button onClick={() => setForm(f => ({ ...f, expected_return_pct: cagr }))}>
  Tu CAGR ({cagr.toFixed(1)}%)
</button>
```
y `Goals.jsx:92`:
```js
setForm({ ..., expected_return_pct: cagr?.cagr ?? 10, ... })
```

Sin clamp. El slider va de −10 a 50 (`:595-597`) pero el `<input type="number">` de al lado
(`:602-608`) es libre, y el chip escribe directo. El backend valida
`expected_return_pct: float = Field(10, ge=-50, le=200)` (`main.py:15149`).

Con el residuo de O-08 (un CAGR de +525 % es alcanzable), tocar "Tu CAGR" y guardar devuelve un 422
que el `catch` traduce a `toast.push('Ocurrió un error: ' + e.message)` (`Goals.jsx:123`) — un
mensaje de validación de Pydantic en un toast.

---

### O-10 🟠 — Un piso anual comparado contra un acumulado

`utils/profileMatch.js:615-620`:
```js
export const RETURN_EXPECTATION_META = {
  preserve:       { label: 'preservar capital',       floorReal: 0 },
  beat_inflation: { label: 'ganarle a la inflación',  floorReal: 3 },
  grow:           { label: 'crecer fuerte',           floorReal: 10 },
  aggressive:     { label: 'maximizar el retorno',    floorReal: 18 },
}
```
Un piso de **10 % real** para "crecer fuerte" sólo tiene sentido como tasa **anual**: nadie llama
"crecer fuerte" a +10 % real en una década ni a +10 % real en un mes.

Y `:665-666`:
```js
const gap = realReturnPct - meta.floorReal
const comparison = gap >= 2 ? 'above' : gap >= -2 ? 'in_line' : 'below'
```

`realReturnPct` viene de `Insights.jsx:2277-2296`:
```js
const realReturnPct = (ret != null && isFinite(ret) && infl != null)
  ? ((1 + ret / 100) / (1 + infl / 100) - 1) * 100
  : null
```
donde `ret` es `perf.twr * 100` — el **acumulado del período medido**, no anualizado (por diseño: el
motor se niega a anualizar bajo medio año) — e `infl` es `inflationCumArsWindow.cumPct`, la
inflación **acumulada de esa misma ventana**. Los dos están bien y son consistentes entre sí. Lo que
está mal es compararlos contra un número que es %/año.

**`monthsCounted` llega y no se usa.** Se pasa a `computeReturnExpectation` (`Insights.jsx:2295`),
se guarda en `actual.monthsCounted` (`:673`), y `ProfileDashboard.jsx:80-88` **no se lo pasa al
gauge**:
```jsx
<ReturnGauge
  realPct={card.actual.realReturnPct}
  floorPct={card.declared.floorReal}
  expectationLabel={(card.declared.expectationLabel || '').toLowerCase()}
  comparison={card.comparison}
/>
```
Y `ReturnGauge.jsx:82-91` cierra con:
> «Buscás **crecer fuerte**. Tu retorno real (neto de inflación) es **+1,5 %** · por debajo de esa
> expectativa.»

**Sin una palabra sobre el período.** Los dos errores posibles:
- ventana corta → un usuario de 2 meses con +1,5 % real (≈ +9,3 % anualizado, casi en línea) lee
  "por debajo";
- ventana larga → un usuario de 3 años con +30 % real acumulado (≈ +9,1 %/año, casi en línea) lee
  "por encima".

El guard de plausibilidad de `:661-663` (`realReturnPct < -40 || > 150` → `no_data`) tapa los casos
extremos de ventana larga, que es otra forma de decir que el defecto ya se manifestó.

---

### O-11 🟡 — Dos tasas requeridas a quince píxeles

Confirmo P-237, con las tres bases:

| card | fórmula | capital | meses |
|---|---|---|---|
| "**Solo con rendimiento**" (`Goals.jsx:264-266`) | `(target/currentValue)^(1/yearsLeft) − 1` | `computeBrokerValue` (frontend) | `Math.round(días/30.4375)/12` |
| "**Necesario · X %/año**" (`Goals.jsx:475-479` ← `goals_diagnostic.py:267`) | `(1 + required_monthly)^12 − 1` con `required_monthly = (target/current)^(1/months) − 1` | `_position_value_usd` (backend) | `(y2−y1)*12 + (m2−m1)` |

La fórmula subyacente es la misma; lo que difiere es **el capital** (dos valuadores distintos, O-03)
y **los meses** (dos formas de contar, O-07). Con las dos discrepancias juntas los números no
coinciden, y están uno arriba del otro en la misma tarjeta.

Y hay un tercer capital en la misma pantalla: el que `twr` usó para calcular el CAGR de la card de
arriba.

---

### O-12 ⚪ — `_cagr_from_monthly_rows` es código muerto

`main.py:15293-15318`. `grep -rn '_cagr_from_monthly_rows' backend/ | grep -v test` devuelve **una
sola línea: la definición.** Sobrevivió a la migración de `_historical_cagr_global` al motor
canónico. Su docstring todavía se presenta como «Fallback cuando no hay snapshots», que ya no ocurre.

Importa porque es el motor que la **P-230** describe («divide por `ci` pelado sin el ½·flujo y clampa
a +500 %») como si alimentara el diagnóstico de Objetivos y los packets de IA. **Ya no alimenta
nada.** Corrijo esa premisa: hoy los dos leen `_historical_cagr_global`, que es el motor canónico. El
problema de Objetivos ya no es qué motor calcula el CAGR — es qué hace el consumidor cuando el motor
dice `None` (O-01).

---

## Parches detectados

| parche | dónde | qué síntoma tapa | causa real | dónde más sigue rompiendo |
|---|---|---|---|---|
| `if (Math.abs(pct) > MAX_DISPLAY_PCT) return null` y `benchFinal <= 1` | `BenchmarksLine.jsx:44,47` | porcentajes absurdos del simulador | el denominador del simulador es `capital_inicio` del primer mes, que puede ser ~0 (y en el Dashboard es el **contable crudo**, B-08) | `compareToMine` (`Insights.jsx:2183`) **no tiene los límites** y publica igual: veredicto AR, diagnósticos, packet de IA |
| `inflationCumArsWindow` (`Insights.jsx:2255-2276`) | recorta la inflación a la ventana de `benchSeriesArs` | el `inflationCum` global se computaba sobre otro rango y el veredicto comparaba dos períodos | **no hay una capa que garantice "mismo período" en las comparaciones**: cada call site lo resuelve o no | Reportes (B-04), Wrapped (B-10), `_build_chat_benchmarks` (B-07) — los tres comparan ventanas distintas sin recorte |
| `if (!k) return` (`Insights.jsx:341`) | valores viejos de `localStorage` | dos listas de claves que nadie obliga a coincidir | **causa B-02**: para `pesos_cash` la clave es *válida según la otra lista*, y el guard la trata como basura |
| `if (realReturnPct < -40 \|\| realReturnPct > 150) return no_data` (`profileMatch.js:661`) | retornos reales extremos | el comentario culpa al «retorno fantasma» de la cadena TWR en pesos — pero también los produce la comparación acumulado-vs-anual (O-10) | O-10: la banda esconde el caso de ventana larga y deja pasar el de ventana corta, que es el más común |
| `except Exception: data = {}` (`main.py:11821`) + `return {}` en los fetchers | yfinance/argentinadatos caídos | falta de un campo `benchmark_error` en el contrato | B-05: en Reportes ni siquiera hay caché stale de la que caer |
| `sp500_ret`/`inflation_ret` sin `moneda` (`builder.py:1639-1642`) | — | **no es un parche: es una omisión.** El modo pesos se agregó al retorno del usuario (`:1499-1500`) y no al benchmark | B-04 |

**El patrón, que es el mismo que 1A encontró en rendimiento:** cuando un fix se aplica, se aplica en
**un call site**. `inflationCumArsWindow` recorta la ventana en Insights y no en Reportes.
`_es_base_de_mercado` (1A, DIV-099) se aplicó en el dashboard del asesor y no en el chat. El ancla
diaria se aplicó a tres series y no a las otras dos. `_en_pesos` existe en `performance.py` y no lo
usa `reporting/builder.py`.

---

## Citas del mapa incorrectas

Los dos conceptos **no estaban mapeados**, así que hay poco que corregir. Verifiqué las 4 citas del
mapa que uso y **las 4 son correctas**:

| cita del mapa | qué afirma | verificación |
|---|---|---|
| `00-mapa-sistema.md:4087` | `_benchmarks_fetch_and_cache` lanza **10** futures con `timeout=25` y fallback stale por clave; loguea error si el S&P vuelve vacío | ✅ exacto (`main.py:5232-5271`) |
| `:4094` | `_fetch_yf_daily` es diario, default 5y | ✅ exacto (`main.py:5418`) |
| `:5432` | `/api/insights/performance` **no respeta `BENCH_TTL`**: sólo pregunta si el dict está vacío (`main.py:11817`), mientras `/api/benchmarks` sí chequea (`:5523`, `:5531`) | ✅ las tres líneas verificadas una por una |
| `:8559` | «Ninguno de los dos fetch de benchmark tiene caché… existe un `_bench_cache` pero estos dos call-sites no lo usan» | ✅ exacto (`main.py:33096`, `:33150`) — es mi B-05, confirmado independientemente |

**Lo que sí corrijo son dos afirmaciones que NO vienen del mapa:**

1. **1A / la memoria del proyecto: «`perf.benchmark` no lo lee nadie».** **Falso en este commit.**
   `Insights.jsx:868-878` construye `bench: benchIdx` a partir de `perf.benchmark`, y `:1696` lo usa
   como la fuente del benchmark del gráfico cuando `(!isArs || usaPerfEnPesos) && !skeleton`. La
   afirmación describía el estado previo a los fixes del 02-03/09.

2. **P-230: «`_cagr_from_monthly_rows` alimenta el diagnóstico de Objetivos y los packets de IA».**
   **Falso.** `grep -rn '_cagr_from_monthly_rows' backend/ | grep -v test` → sólo la definición
   (`main.py:15293`). Los dos consumidores citados leen `_historical_cagr_global`, que es el motor
   canónico. Ver O-12.

**Y una cita incorrecta dentro del propio código** (no del mapa):
`Insights.jsx:2315-2316` afirma que «`inflationCum` global (sobre `globalMonthly`) se usa en otros
lugares de la UI». No se usa en ninguno (B-14).

Y un **comentario falso** en `main.py:5432` (docstring de `_fetch_yf_daily`): «Mismo período que el
mensual (5y)» — el mensual usa `max` (B-11).

Y un **docstring desactualizado** en `main.py:5226`: «`plazo_fijo` — TNA Minorista BCRA» cuando el
código baja `uva` (B-13).

**Un no-hallazgo que vale reportar** (porque parecía uno y no lo es): el comentario de
`Goals.jsx:243-245` dice `FV = PV*(1+r/12)^n`, tasa nominal dividida por 12. Fui a buscar la
inconsistencia contra `noContribValue`, que usa `(1+r)^años` (efectiva). **La implementación real de
`requiredMonthly` (`Goals.jsx:623-633`) usa la mensual EFECTIVA** (`Math.pow(1+rAnnual, 1/12) - 1`) y
su propio comentario de encabezado lo declara. La trayectoria del gráfico (`:271`) usa la misma. **El
código está bien y es consistente; el comentario de arriba está stale.** Lo dejo en O-12 como ⚪ de
documentación, no como bug.

---

## URGENTE

**Nada de lo encontrado exige tocar código hoy.** Ningún hallazgo corrompe datos, borra nada, ni
expone información. Todos son números publicados mal.

Dicho eso, si hubiera que elegir tres para el próximo deploy, en este orden:

1. **B-04 — Reportes con el selector en Pesos publica el veredicto vs S&P con el signo dado vuelta.**
   Es el único hallazgo que (a) afecta a una pantalla central, (b) se activa con un control que el
   usuario tiene siempre a mano, (c) produce una afirmación **invertida** y no sólo imprecisa
   ("Le ganaste al S&P 500" cuando le perdió), y (d) es una **regresión de hace cuatro días**. Y el
   arreglo ya está escrito en `performance._en_pesos`.

2. **O-01 — "Al ritmo actual, no llegás a la meta" para usuarios que están adelantados.** El
   `(user_cagr_pct or 0)` es una línea. Lo que no es una línea es decidir qué decir en su lugar —
   por eso es la pregunta 1 y no un fix directo.

3. **B-01 + B-02 — dos de las cinco opciones del selector en pesos.** B-01 es un mapeo de una línea
   (`plazo_fijo: 'uva'`). B-02 es peor de lo que parece porque no falla ruidosamente: **muestra la
   línea equivocada con el rótulo correcto**, que es la clase de error que nadie reporta porque nadie
   lo puede ver.

---

## BLOQUE-RESUMEN

| tema | # | hallazgo | evidencia | severidad | dónde muerde | causa raíz |
|---|---|---|---|---|---|---|
| Benchmarks | B-01 | "Plazo fijo UVA" pide una serie (`plazo_fijo`) que el backend nunca produjo → benchmark vacío con la opción marcada disponible | MEDIDO | 🔴 | `/analisis` en Pesos | el frontend mapeó al nombre de producto, no al de la fuente (`uva`) |
| Benchmarks | B-02 | "Pesos cash (blue)" no está en `BENCH_API_KEY` → `if(!k) return` cancela el refetch: la línea anterior queda con la leyenda nueva | ESTRUCTURAL | 🔴 | `/analisis` en Pesos | dos listas de claves que nadie obliga a coincidir |
| Benchmarks | B-03 | Merval y UVA se resuelven por MES sobre una curva DIARIA — el fix del ancla diaria sólo se aplicó a los tres benchmarks en dólares | MEDIDO | 🟠 | `/analisis` en Pesos | el fix se hizo por serie en vez de por regla |
| Benchmarks | B-04 | Reportes resta retorno en PESOS menos S&P en DÓLARES (y viceversa contra inflación): `benchmark_return_for_period` nunca recibe `moneda` | DEDUCIDO | 🔴 | `/reportes` — frase, chip e insight | el modo pesos se agregó al retorno y no al benchmark |
| Benchmarks | B-05 | Reportes fetchea inflación y S&P en **cada request**, salteando `_bench_cache`/SWR; si fallan, la comparación desaparece sin log | ESTRUCTURAL | 🟠 | latencia + benchmark intermitente | dos call sites que no conocen la caché del módulo |
| Benchmarks | B-06 | `insights.benchmarks` publica `outperform.inflation` cruzando USD contra ARS, y el prompt instruye a afirmar "pérdida real" | ESTRUCTURAL | 🟠 | chat IA (topic sin UI, invocable) | la migración arregló el retorno y no la moneda |
| Benchmarks | B-07 | El `_note` del chat da la regla de pareo para S&P e inflación y no para el Merval, que se publica en pesos junto a un retorno en dólares | ESTRUCTURAL | 🟠 | chat IA | benchmark agregado después de escribir la regla |
| Benchmarks | B-08 | El "vs S&P" del Dashboard usa `monthly` crudo + total CON plazos fijos; el de Insights usa MtM + total SIN | ESTRUCTURAL | 🟠 | `/dashboard`, `/` mobile vs `/analisis` | `applyMtmToMonthly` importado y nunca llamado |
| Benchmarks | B-09 | Crear un plazo fijo saca la plata del patrimonio y no del flujo del simulador → el usuario pierde contra todo por el monto del PF | DEDUCIDO | 🟠 | veredicto AR, chips, diagnósticos | `create_plazo_fijo` debita cash sin registrar retiro |
| Benchmarks | B-10 | Wrapped compara un pseudo-TWR USD contra inflación ARS y contra un S&P de YTD calendario, en un slide compartible | ESTRUCTURAL | 🟡 | `/wrapped` | decisión documentada que contradice la regla escrita del chat |
| Benchmarks | B-11 | La serie diaria es 5y y la mensual `max`, y el diario gana con cobertura parcial; el docstring afirma que las dos son 5y | ESTRUCTURAL | 🟡 | `/analisis` con historia larga | el chequeo es "¿algún punto?" en vez de "¿cubre el rango?" |
| Benchmarks | B-12 | `bench` sin allowlist: cualquier clave da benchmark vacío en silencio; `?bench=dolar_blue&moneda=ars` contaría la devaluación dos veces | ESTRUCTURAL | ⚪ | endpoint | falta de validación en el borde |
| Benchmarks | B-13 | `BENCH_PORCENTUAL`/`BENCH_EN_ARS` declaran `plazo_fijo` (rama muerta) y el docstring del fetcher dice "TNA Minorista BCRA" cuando baja `uva` | MEDIDO | ⚪ | mantenimiento | el nombre de producto quedó tras cambiar la fuente |
| Benchmarks | B-14 | `vsShv`, `vsGold`, `vsMerval` e `inflationCum` se computan en cada render y no los consume nadie; el comentario de `:2315` afirma lo contrario | ESTRUCTURAL | ⚪ | mantenimiento | cards retiradas sin limpiar |
| Benchmarks | B-15 | Los simuladores ejecutan el flujo del mes al cierre de fin de mes, y `compareToMine` contrasta el patrimonio de HOY contra el benchmark al último cierre mensual | ESTRUCTURAL | 🟡 | veredicto AR, chips del Dashboard | granularidad "MVP" que sobrevivió al MVP |
| Benchmarks | B-16 | `vs_sp500_pp` es el **promedio aritmético** de los excesos mensuales, rotulado como pp del período | ESTRUCTURAL | 🟡 | packet IA de Reportes | promediar en vez de componer |
| Benchmarks | B-17 | **PARCHE**: `BenchmarksLine` esconde el chip si `\|pct\|>500` o el benchmark vale ≤US$1, sin decir por qué | ESTRUCTURAL | ⚪ | `/dashboard` | denominador del simulador sin guard; `compareToMine` no tiene ni el parche |
| Benchmarks | B-18 | `/api/insights/performance` no chequea `BENCH_TTL`: sólo si el dict está vacío. Benchmark arbitrariamente viejo, sin campo que lo declare | ESTRUCTURAL | 🟡 | `/analisis` | dos lecturas de la misma caché con criterios distintos |
| Objetivos | O-01 | `cagr: None` (ventana < medio año) se vuelve **0 %** por un `or 0`: "Atrasado · no llegás a la meta" para quien rinde +54 % | MEDIDO | 🔴 | `/objetivos`, packet IA `goal` | un `None` que significa "no se puede anualizar" tratado como "cero" |
| Objetivos | O-02 | El objetivo no tiene aportes: ni columna, ni campo, ni parámetro. El packet IA publica `monthly_contribution: 0.0` de una columna inexistente y el prompt razona sobre ella | ESTRUCTURAL | 🔴 | `/objetivos`, chat IA | el modelo de datos nunca incorporó el aporte que la pantalla promete calcular |
| Objetivos | O-03 | Tres "capital actual" distintos (frontend live / backend live con otro valuador / último snapshot medible), ninguno con plazos fijos | ESTRUCTURAL | 🟠 | `/objetivos` | tres consumidores, tres valuadores |
| Objetivos | O-04 | `delta_pct_required` anualiza ×12 lineal y `required_annual_pct` compone, en el mismo `return` | MEDIDO (28,6 y 41,1 pp) | 🟠 | packet IA `goal` | dos convenciones a tres líneas de distancia |
| Objetivos | O-05 | El objetivo es siempre `target_usd`, sin pesos ni ajuste por inflación; el selector global no lo toca | ESTRUCTURAL | 🟠 | `/objetivos` | la única superficie que quedó fuera del trabajo de monedas |
| Objetivos | O-06 | El diagnóstico llama `_historical_cagr_global` sin `modo` ni `moneda`: el toggle Certero/Estimado mueve la card de arriba y no la de abajo | ESTRUCTURAL | 🟠 | `/objetivos` | el toggle se cableó a un endpoint y no al otro |
| Objetivos | O-07 | `_months_between` ignora el día: hoy 07/09 con objetivo al 30/09 → 0 meses → "la fecha ya llegó". Y el frontend cuenta con otra fórmula (dice "1 mes") | MEDIDO | 🟡 | `/objetivos` | aritmética de calendario por (año, mes) |
| Objetivos | O-08 | `_project_value` compone sin cota y `twr` no capa el CAGR por arriba (sólo se niega bajo medio año): 6,0e11 USD proyectados en el caso medido | MEDIDO | 🟡 | `/objetivos`, packet IA | el guard del motor es sobre la ventana, no sobre la magnitud |
| Objetivos | O-09 | "Tu CAGR (X %)" prellena `expected_return_pct` sin clamp; el backend valida `le=200` → 422 traducido a "Ocurrió un error" | ESTRUCTURAL | 🟡 | `/objetivos` (alta) | validación en el servidor sin espejo en el cliente |
| Objetivos | O-10 | "Expectativa de retorno" compara un retorno real **acumulado** contra un piso **anual**; `monthsCounted` llega a la card y el gauge no lo usa ni lo muestra | ESTRUCTURAL | 🟠 | `/analisis?tab=perfil` | una constante %/año usada como umbral de un acumulado |
| Objetivos | O-11 | Dos "tasa requerida" a 15 px, sobre capitales distintos y con dos formas de contar meses | ESTRUCTURAL | 🟡 | `/objetivos` | la card del diagnóstico se agregó sin retirar el escenario que ya lo decía |
| Objetivos | O-12 | `_cagr_from_monthly_rows` es código muerto (0 call sites fuera de tests); refuta la premisa de P-230 | ESTRUCTURAL | ⚪ | mantenimiento | fallback que sobrevivió a la migración al motor canónico |

**Totales: 29 hallazgos · 5 🔴 · 11 🟠 · 8 🟡 · 5 ⚪.**
