# Censo F6 — medido contra el árbol el 2026-09-11

Worktree limpio `fix/f6-un-solo-motor` desde `origin/main` (`446f3868`).
**Baseline propio: backend 4295 passed / 0 failed · frontend 1559 passed / 0 failed.**

El handoff avisa que los números del informe son de junio y que hay que re-censar.
Esto es el re-censo. Cada línea se verificó con grep contra el código de hoy.

---

## 6.1 · El valuador canónico — 4 copias vivas (el informe decía 5, una ya está)

`frontend/src/utils/valuation.js:637` define `valuePositionLot`. Único caller:
`computeBrokerValue` (:842), en el mismo archivo. El docstring (:598) nombra las cinco:

| copia | dónde | estado |
|---|---|---|
| `computeBrokerValue` | valuation.js:835 | ✅ ya es la suma de `valuePositionLot` |
| `valueEquityLot` | valuation.js:360 | ❌ copia viva — la consumen `CarteraList.jsx:116` y `DetailPortfolioBlocks.jsx:144` |
| `valueLot` | pages/AssetDetail.jsx:34 | ❌ copia viva — local al archivo, caller en :164 |
| PositionDetailMobile | pages/PositionDetailMobile.jsx | ❌ copia viva |
| PositionsMobile | pages/PositionsMobile.jsx | ❌ copia viva |

**Además hay copias INLINE que el informe no contaba**, marcadas en su propio comentario
como "espejo de computeBrokerValue": `Dashboard.jsx:533` y `:588`, `HomeMobile.jsx:252`,
`FirstInsight.jsx:139` y `:155`, `Insights.jsx:418-422`, `PositionsMobile.jsx:666` y `:778`,
`Positions.jsx:1407`. **El censo real es 4 funciones + ~9 espejos inline, no 5.**

El docstring dice que migrar es delta 0 **sólo después** de alinear comisiones y modo
`'purchase'`. Eso no está hecho.

---

## 6.2 · Retorno fuera del motor — **once** lectores, no cinco (DIV-097)

`twr.leg_dudoso` (twr.py:692) es el guard. Lo llaman HOY sólo `twr.py` y
`reporting/builder.py`. Los once lectores del informe **siguen todos sin él**:

| lector | tiene `leg_dudoso` | importa twr |
|---|---|---|
| `backend/wrapped.py` | ❌ | sí (F2/F5 lo migró a `vs_inflacion_ar`, no al guard) |
| `backend/ai/builders/insights.py` | ❌ | sí |
| `backend/ai/builders/insights_evolution.py` | ❌ | sí |
| `backend/ai/builders/reports.py` | ❌ | sí |
| `backend/ai/builders/dashboard.py` | ❌ | no |
| `backend/advisor_brief.py` | ❌ | no |
| `backend/main.py::_snapshot_delta` | ❌ | — |
| `frontend/utils/evolution.js` | ❌ (sólo piso −0,99) | — |
| `frontend/pages/Insights.jsx:679,721,742` | ❌ (sólo `Math.max(r,-0.99)`) | — |
| `frontend/hooks/useMonthlyData.js` | ❌ (tiene `esApto`, no el guard) | — |
| `frontend/utils/insightsModel.js:135,567` | ❌ (sólo piso −0,99) | — |

**Lo que el piso de −0,99 NO cubre**, y es la mitad cara del problema: el desborde
hacia ARRIBA por denominador chico (`DENOM_MIN_FRACCION`). El repo lo midió:
`uid 50: 401 → 335 con un retiro de 770 → denominador US$16 → +4.439 % en un leg`.
Once lectores creen estar protegidos y no lo están.

En el frontend `leg_dudoso` no existe en ninguna forma — grep de
`legDudoso|leg_dudoso|SALTO_MAX|DENOM_MIN` sobre `frontend/src` da **cero**.

---

## 6.3 · Benchmark fuera de `performance.py`

`import performance` sólo aparece en `main.py:12594` y `ai/builders/insights_benchmarks.py:90`.

### 🔴 El que está VIVO, es visible y tiene plata: la pata del S&P en Reportes (B-04)

`reporting/builder.py` recibe `moneda` en su firma (:889) y la usa para la inflación:

    :1745  vs_inflacion_ar(delta_pct, inflation_ret, moneda=moneda, fx0=..., fx1=...)

y NO la usa para el S&P, treinta líneas antes, en la misma función:

    :808   def benchmark_return_for_period(bench, period_type, period_start, period_end, key)
    :1683  sp500_ret = benchmark_return_for_period(bench, period_type, ..., "sp500")
    :1688  vs_sp500  = delta_pct - sp500_ret

Con el selector en Pesos, `delta_pct` YA está en pesos (`:1544 delta_pct = _pct_puntas_ars`)
y `sp500_ret` sigue en dólares. **La resta le suma la devaluación entera al veredicto.**
Se publica en `MonthCard.jsx:230` y `Reports.jsx:700` como "vs S&P 500 +X %".

Es exactamente la asimetría que F5 encontró en el endpoint de venta: dos patas del mismo
`return`, una version-aware y la otra no. **F5 arregló la de inflación y dejó ésta.**

### Los otros

- **B-08 vivo**: `Dashboard.jsx:43` importa `applyMtmToMonthly` y **no lo usa en ninguna
  línea** (grep: una sola aparición en todo el archivo). El chip "vs S&P" del Dashboard
  compara con la cadena cruda y el de Insights con la corregida a mercado → dos números
  distintos para el mismo usuario. El import muerto es la firma del olvido.
- **Motor duplicado en el frontend**: `Insights.jsx:1581 buildInflationCumPct` compone la
  inflación por su cuenta. Es el que la nota de `performance.py:27-42` señala como el
  motivo por el que arreglar el gráfico sólo en el backend no alcanza.
- **B-01 / B-02 parecen ARREGLADOS** por el audit de benchmark del 01/09: `plazo_fijo` y
  `pesos_cash` ya tienen mapeo (`Insights.jsx:1642,1644`) y `available` exige `bench?.uva`.
  Confirmar antes de tocarlos.

---

## 6.4 · `cost_basis_consumed` en la venta

La columna existe (`main.py:1350`) y se escribe **sólo para amortizaciones**
(`main.py:11180-11192`). En la venta no se escribe.

⚠️ **Posible C12 — un comentario que hay que MEDIR antes de creerle.** Tres lugares afirman
que la columna "está 100 % NULL en las filas reales": `main.py:38967`,
`frontend/utils/bookComposition.js:210`, `frontend/utils/assetPnl.js:18`. Si las
amortizaciones la escriben desde `0c04dfa`, la afirmación es falsa hoy — y `Positions.jsx:531`
YA la lee (`op.cost_basis_consumed`) con una rama de fallback para "op legacy sin stampar".
Medir en prod antes de diseñar nada acá.

---

## 6.5 · Los dos lectores de «Capital aportado»

`twr.netdep_canonico` (twr.py:1006) recalcula desde `monthly_entries`; la columna estampada
`snapshots.net_deposited` la escriben el cron (`snapshots_job.py`) y
`_recompute_snapshots_netdep_for_user`. El docstring de `netdep_canonico` ya explica por qué
no se usa la estampada y se aparta a propósito de `compute_net_deposited_db` en el baseline.
`main.py` la toca en 98 lugares, `reporting/builder.py` en 27, `snapshots_job.py` en 13.

Depende de **D-2**: la divergencia está tapada mientras el recalc borre `capital_inicio`.
F1 arregló el borrado → **la divergencia debería estar destapada ahora**. Hay que medirlo.

---

## Orden propuesto (por números de pantalla tocados, no por líneas)

1. **La pata del S&P en Reportes** (6.3). Bug vivo, visible, con plata, y es una firma de
   función. Chico y con test que falla contra el código viejo.
2. **B-08, el import muerto del Dashboard** (6.3). Dos números distintos para el mismo usuario.
3. **`leg_dudoso` a los 7 lectores del backend** (6.2). El guard existe; es propagarlo.
4. **`leg_dudoso` al frontend** (6.2), portado con guard estructural que compare las dos
   implementaciones — el patrón `test_la_version_de_SQL_y_la_de_PYTHON_dan_lo_mismo` de F5.
5. **Medir `cost_basis_consumed` en prod** (6.4) antes de escribir una línea.
6. **El valuador** (6.1). Es el más caro y el menos visible. Va último.

---

# Addendum — lo que apareció al ejecutar (2026-09-11, después del censo)

## ✅ HECHO: la pata del S&P (`b0553fa9`)

Medido por el camino de producción: en pesos publicaba **+18,0 pp ("le ganaste")**
sobre una cartera plana en dólares que en realidad perdió contra el índice por 2 puntos.
Ahora publica −2,4. Suite 4312/0 (baseline 4295 + 17 tests nuevos).

## ⚠️ B-08 NO ES LO QUE EL INFORME DICE, y la pantalla "buena" es la otra

El informe (1b-benchmarks §4) dice que el chip del Dashboard está mal porque usa
la cadena cruda mientras Insights usa la corregida a mercado, y señala el import
muerto de `applyMtmToMonthly` (`Dashboard.jsx:43`) como "la firma del olvido".

**El import muerto es real** (una sola aparición en todo el archivo, verificado).
**Pero casi no explica la diferencia**, y la diferencia que sí existe va para el
otro lado. Medido leyendo el código:

### Vía 1 — `applyMtmToMonthly`: efecto casi nulo sobre este número

`simulateBenchmark` (`benchmarkSim.js:76`) usa **solamente** `sorted[0].capital_inicio`,
`m.deposits` y `m.withdrawals`. `applyMtmToMonthly` reescribe `capital_inicio` y
`capital_final` y **no toca los flujos**. O sea que de toda la corrección a mercado,
al simulador le llega **un solo número**: el capital semilla del primer mes. El
`.sort()` que falta tampoco importa — `simulateBenchmark` ordena internamente.

### Vía 2 — los plazos fijos: ésta sí, y el informe la tiene al revés

    Dashboard.jsx:213   totalValue = Σ brokerTotals + pf.valueUsd     ← CON plazo fijo
    Insights.jsx:415    totalPortfolio = Σ pieData (brokers)          ← SIN plazo fijo

Las dos pantallas usan la MISMA fórmula (`(mío − bench) / bench`) contra totales
distintos. Y el simulador se alimenta de los flujos de `monthly_entries`, donde
**el plazo fijo no figura**: `create_plazo_fijo` debita el cash del broker y no
registra el retiro (es el B-09 del mismo informe).

Entonces, para un usuario con plazo fijo:

| | numerador (su cartera) | denominador (el sim) | efecto |
|---|---|---|---|
| Dashboard | incluye el PF | no lo descontó | ✅ consistente |
| Insights | **NO** incluye el PF | no lo descontó | ❌ lo castiga por el 100 % del PF |

**El número correcto es el del Dashboard.** Alinear Insights al Dashboard (no al
revés) es el fix — y "arreglar" el Dashboard copiándole a Insights, que es lo que
el informe sugiere, empeoraría el número bueno.

Y el fix ya está escrito tres líneas más abajo en el mismo archivo:
`Dashboard.jsx:236 totalValuePositions = totalValue - pf.valueUsd`, con el
comentario que explica exactamente cuándo usar cada total. Otra vez C1.

### Por qué NO se tocó en esta tanda

Cerrarlo bien exige decidir **si el "vs S&P" incluye los plazos fijos**, y esa
decisión depende de que el PF registre su flujo en `monthly_entries` — que es
literalmente un punto de **F7** ("Plazos fijos que no escriben `monthly_entries`").
Alinear las dos pantallas hoy, sin eso, elige entre dos números que los dos están
mal para el usuario con PF; sólo cambia a cuál de los dos.

**Es una dependencia de F7, no un bug vivo de F6.** Va al plan, no a esta tanda.

---

# Lo que encontró auditarme (la ronda que el handoff pide, y por qué vale)

Cinco defectos, **cuatro míos**. Ninguno lo mostró la suite en verde.

## 1. ⭐ Otra sesión había implementado LA MISMA REGLA el mismo día

Mientras yo trabajaba, otra sesión pusheó 5 commits a `origin/main` tocando el
mismo archivo y la misma función. Uno de ellos (`benchmark_entre_fechas`) convierte
el índice a pesos con **la misma tabla `BENCH_EN_ARS`, la misma política de
faltantes y la misma aritmética** que yo escribí — pero sólo para el AÑO.

Verificado que son algebraicamente idénticas: con `pct = (i1−1)·100`,
`(1+pct/100)·(f1/f0) − 1` se reduce a `i1·f1/f0 − 1`.

**Apiladas habrían contado la devaluación DOS VECES para el año.** El merge las
unificó en un solo primitivo, al que ahora pasan las dos ramas. Los números
publicados no se movieron (sonda: 22,4 / −2,4 antes y después).

## 2. Mi primera resolución rompía la pata de inflación

Al unificar las puntas del TC en un par de variables, dejé la llamada a
`vs_inflacion_ar` referenciando variables que había borrado → `NameError`, o sea
el endpoint de Reportes caído. **Las dos patas no se pueden compartir**: necesitan
TC en el caso OPUESTO (la inflación en dólares, el S&P en pesos) y mueven cosas
distintas (una la cartera, otra el índice). Queda escrito al lado del código.

## 3. Una puerta sin guardia que sólo apareció al unificar

La conversión se decidía con `if fx is not None` — o sea "estoy en pesos" se
INFERÍA de que el TC estuviera disponible. Pero el caller envuelve `serie_fx` en
try/except: si falla, `fx` queda en None y el índice salía **en dólares contra una
cartera en pesos**. El bug entero, por la puerta de al lado. Ahora `moneda` viaja
declarada y aparte de `fx`, y sin TC no se publica.

## 4. ⭐ Mi primitivo devolvía None para la inflación, y mi test cristalizaba el error

`retorno_bench_en_moneda(4.5, "inflation_ar", moneda="usd")` devolvía `None`,
razonando que "la inflación en dólares no existe". Confundía dos cosas: la función
no contesta *"¿le ganaste?"* —eso es `vs_inflacion_ar`—, sólo **entrega el número
del índice**. Devolver None le sacaba el dato con el que compara, y **el veredicto
contra inflación desaparecía en dólares**: exactamente el defecto que F5 cerró,
reintroducido por mí.

**Lo cazaron cuatro tests ajenos** (`test_benchmark_anual.py`), no los míos — los
míos afirmaban el bug. Es la quinta vez en este repo que el test viejo tiene razón.
Se corrigió el primitivo, no el test, y se reescribió el mío.

## 5. Un comentario propio describiendo código que ya no estaba

Escrito treinta minutos antes. C12 se produce así de rápido.

---

# Hallazgos PREEXISTENTES que aparecieron de paso (no son míos, y uno es grave)

## 🔴 El % ANUAL en pesos publica el número de DÓLARES — y da vuelta dos veredictos

**MEDIDO contra `origin/main` PURO** (worktree aparte, sin ninguno de mis cambios),
con una cartera plana en dólares, un año, 100 % de devaluación, S&P +2 %,
inflación 50 %:

    moneda=usd  delta_pct=26,82  sp500=  2,0  vs_sp500=+24,82  retorno_ars=153,64  vs_infl=+103,64
    moneda=ars  delta_pct=26,82  sp500=104,0  vs_sp500=−77,18  retorno_ars= 26,82  vs_infl= −23,18
                             ↑ EL MISMO NÚMERO EN LAS DOS MONEDAS

Con el selector en Pesos el usuario lee **"el S&P te ganó por 77 puntos"** y
**"la inflación te ganó por 23"**. Medido TODO en pesos, que es lo que el selector
promete: la cartera hizo +153,64 %, el S&P +104 % y la inflación 50 %, o sea
**le ganó al S&P por 49,6 puntos y a la inflación por 103,6**. En dólares el
veredicto es el mismo signo (+24,8 contra el S&P). **Los dos invertidos, en
cualquiera de las dos lecturas.**

⚠️ **ESTÁ EN PRODUCCIÓN**: `/api/health` y `version.json` devuelven `e9211ca5`,
que es `origin/main`. Llegó con el deploy de hoy, no es viejo.

CAUSA RAÍZ, y es de libro: para el AÑO, cuando el motor canónico no puede medir,
`delta_pct` cae a la composición geométrica de `monthly_entries` (`:1443`), que
está **en dólares y no se convierte** — y pisa al `_pct_puntas_ars` que sí estaba
en pesos (`:1544` vs `:1558`). El benchmark, en cambio, sí se convierte. Cruzados.

Y lo que lo vuelve evidente: **el número correcto ya está en la misma respuesta**.
Con el selector en dólares, `retorno_ars_pct` publica 153,64 — el año en pesos,
bien calculado. Con el selector en pesos, nadie lo mira. Es el patrón del hallazgo
O-01 del propio informe ("el dato para decirlo bien viaja en la misma respuesta y
nadie lo mira").

✅ **ARREGLADO** — decidido con el dueño, coordinando con la otra sesión (se mergeó
su último commit antes de tocar). Se CONVIERTE la composición, no se recalcula
(regla de F5), con las puntas de `_ventana_comp` — el tramo que esa composición
realmente cubre, que es **el mismo que ya recibe el benchmark del año**. Si se
midieran sobre tramos distintos, la devaluación no se cancelaría entre rendimiento
e índice y la resta volvería a mezclar unidades, con un disfraz más difícil de ver.

Y componer al final es EXACTO, no aproximado: convertir cada mes con su propia
devaluación y multiplicar da lo mismo, porque las puntas intermedias se cancelan
de a pares. Sin TC no se pisa nada y `delta_pct` se queda con el punta-a-punta,
que ya está en pesos.

Medido después:

    moneda=ars  delta_pct=153,64  sp500=104,0  vs_sp500=+49,64  vs_infl=+103,64

⭐ **La verificación cruzada más fuerte**: `vs_inflation_pct` da **103,64 idéntico
en las dos monedas**. Se llega por dos caminos independientes —en dólares lo
convierte `twr.vs_inflacion_ar` (F5), en pesos `delta_pct` ya viene convertido por
este arreglo— y coinciden. Si alguno de los dos se rompe, el test lo caza.

**PROPAGACIÓN** (grep de quién más compone Dietz de `monthly_entries`):
`ai/builders/reports.py:84`, `insights.py:272`, `insights_evolution.py:65`,
`insights_benchmarks.py:134` — ninguno recibe selector de moneda (miden siempre en
dólares), así que no hay cruce. `main.py:24361` compone la INFLACIÓN, que ya está
en pesos. El bug estaba acotado a `builder.py`.

**SOSPECHA NO MEDIDA**: para `day`/`week`, `_pct_puntas_ars` no se calcula (su
condición es `period_type in ("month","year")`), así que `delta_pct` podría quedar
en dólares con el selector en pesos. **No lo pude reproducir**: el fixture cae
antes en el guard `dw_incomplete` y `delta_pct` sale `None` en las dos monedas.
Queda como sospecha, no como hallazgo.

## `bench_desde` / `bench_hasta` se declaran y nunca se llenan

`schema.py` los documenta con un párrafo que explica que sin ellos "la ventana no
es observable — un test sobre el veredicto pasa igual midiendo el tramo
equivocado, que fue exactamente lo que pasó auditando esto". **Ningún lugar del
backend los escribe y ninguno del frontend los lee** (grep: cero). C12.
