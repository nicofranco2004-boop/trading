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

---

# Auditoría completa pre-deploy (pedida por el dueño)

Lógica, cálculos, palabras e integridad con el resto de la app. **Dos bugs más, los
dos EN PRODUCCIÓN, ninguno mío.**

## 🔴 1. Un tipo de cambio NEGATIVO cruzaba el guard entero

Batería de 22 casos sobre `retorno_bench_en_moneda`, incluidos los bordes hostiles.
Veinte pasaron. Los dos que no:

    retorno_en_pesos_pct(2,0 %, fx0=−1000, fx1=1200)   →  −222,4 %
    vs_inflacion_ar(10 %, 5 %, fx0=−1000, fx1=1200)    →  (−232,0 · −237,0 pp)

El guard era `not fx0 or not fx1` — que pregunta *"¿tiene valor?"* y no *"¿es un
tipo de cambio?"*. `not (-1000)` es `False`, así que un negativo pasaba derecho.

**Es exactamente la corrección que `295b3d3e` (F5) hizo en el guard de al lado**
—"la guarda del TC era 'tiene valor' y no 'es positivo'"— y que a esta función no
había llegado. Un fix correcto aplicado a un call site de dos: C1 con nombre y
apellido. Y `vs_inflacion_ar` **ya está deployado** con el agujero.

Trampa aritmética que lo hacía difícil de ver: con las DOS puntas negativas el
cociente se normaliza solo y el número sale bien. El defecto sólo aparece cuando
**una sola** de las dos está rota — que es justo lo que produce una fuente con
errores, y la de este repo los tiene documentados (45 % de spread, 73 días con la
compra por encima de la venta).

✅ Arreglado en la RAÍZ (`twr.retorno_en_pesos_pct`), que cubre a los cuatro
call sites de una vez.

## 🔴 2. Un TERCER call site del bug del S&P, en la pantalla nueva del año

`/api/reports/years` publica un tramo PARCIAL cuando el año completo no se puede
medir ("+2,15 % desde el 30 de junio"). Ese `parcial_pct` sale de
`twr.curva_indexada`, que recibe `moneda` cuatro líneas antes y devuelve **pesos**
con el selector en Pesos. El S&P contra el que se restaba se pedía **sin `fx` ni
`moneda`**, o sea en dólares.

MEDIDO con la serie del tramo (S&P 100 → 110, el peso valiendo la mitad):

    S&P que se restaba (dólares)   =  10,0 %
    S&P que corresponde (pesos)    = 120,0 %

**110 puntos regalados al veredicto**, en el número que esa pantalla publica
*justo cuando* el del año completo no está disponible. Es código de hoy de la otra
sesión, **ya deployado**.

✅ Arreglado, y con un **guard estructural que lee código**: verifica que todo
caller de producción de `benchmark_entre_fechas` / `benchmark_return_for_period`
declare `moneda`. Contra el código viejo señala exactamente `main.py:34820`.

Tres call sites del mismo patrón en la misma pantalla, dos con el arreglo y uno
sin él — la forma exacta de C1, otra vez.

## 3. Todas mis citas de número de línea estaban corridas

Escribí `:1544`, `:238`, `:1486`, `:1760`, `:1762`. Después del merge, `:1544` es
`:1811` y `:238` es `:302`. **Ninguna apuntaba a lo que decía.** Es el mismo
problema que el handoff documenta del mapa ("~53 tenían el número de línea
corrido"), producido en una sola sesión.

✅ Reemplazadas por nombres de símbolo, que no se corren.

## 4. Un comentario de F5 que quedó incompleto

Decía que las superficies del veredicto "ya se migraron … falta este gráfico",
hablando sólo de la inflación. Tras este trabajo la pata del S&P tampoco está
pendiente, y quien lo leyera iba a buscar un fix ya hecho. ✅ Aclarado.

## 5. Integridad con el resto de la app — verificada, sin sorpresas

Censo de todo lo que consume los campos que cambié (`vs_sp500_pct`,
`sp500_return_pct`, `retorno_ars_pct`, `delta_pct`):

| consumidor | moneda | efecto |
|---|---|---|
| `/api/reports` (timeline) | propaga `moneda` | ✅ correcto |
| `/api/reports/years` | propaga `moneda` | ✅ correcto |
| `reporting/timeline.py` (mes y semana) | propaga `moneda` | ✅ correcto |
| `reporting/detectors.py` (la frase narrativa) | usa los campos del reporte | ✅ ahora consistente |
| `ai/builders/monthly.py` → `monthly_insight.py` | **sin `moneda`** → dólares | ✅ no lo afecta |
| `ai/builders/reports.py` | calcula el suyo, todo en USD | ✅ no lo afecta |
| `advisor_brief.py` (el mail del asesor) | no los usa | ✅ |
| `YearReturnLine.jsx` (pantalla nueva) | pide al backend, **no convierte** | ✅ sin doble conversión |
| `MonthCard.jsx` / `Reports.jsx` | muestran lo que viene | ✅ |
| `demo.js` | números inventados para la demo | — no pasa por el backend |

La frase de `detectors.py` ("Tu portfolio: X %. S&P 500: Y %. Diferencia: Z
puntos") ahora sale con los tres números en la misma moneda. Antes, en Pesos,
decía `+26,8 %` / `+104,0 %` / `−77,2 puntos`: aritméticamente consistente y
enteramente falsa.

**Anotado, no arreglado**: esa frase no dice en qué moneda está. Hoy el selector
global está a la vista y es el mismo diseño que el resto de la app, así que no se
tocó — pero `metrics.moneda` viaja al lado por si se decide decirlo.

## 6. Lo que NO es un problema, verificado

- `moneda` con espacios (`" ars "`) cae a dólares en silencio. **No alcanzable
  desde la app**: el frontend manda literales generados por código
  (`currency === 'ARS' ? 'ars' : 'usd'`). Y "arreglarlo" sólo acá lo dejaría
  inconsistente con los otros cinco lugares que usan el mismo patrón — sería
  crear justo la divergencia que F6 viene a cerrar.
- Mayúsculas (`"ARS"`) sí funcionan. Verificado en la batería.

---

# Tercera ronda: auditar el código escrito para las dos anteriores

El handoff avisa que cada ronda correctiva necesita su propia ronda. **Cinco
defectos más, los cinco MÍOS**, ninguno visible en la suite en verde.

## 🔴 1. Mi propia función reproducía el bug que vino a cerrar

`_pct_comp_en_pesos` no validaba la ventana. Y `twr.serie_fx` **arrastra** el
último cierre conocido para cualquier fecha que le pidas — así que con una ventana
rota las dos puntas devuelven **el mismo TC**, el cociente da 1, la conversión
queda en identidad, y la función **publica el número de DÓLARES con etiqueta de
pesos**. El defecto exacto de toda esta tanda, entrando por un camino nuevo.

MEDIDO antes de los guards, con `pct = 26,82` y la serie 1.000 → 2.000:

| entrada | devolvía | debía |
|---|---|---|
| ventana invertida `("2025-12-31","2025-06-30")` | **26,82** ← el de dólares | None |
| fechas basura `("x","y")` | **26,82** | None |
| un solo día `("2025-12-31","2025-12-31")` | **26,82** | None |
| formato no ISO `("2025-6-30", …)` | **26,82** | None |
| no es un par (`"abc"`, `5`) | **excepción sin capturar** | None |

**`benchmark_entre_fechas` YA tenía este guard escrito** para su propia ventana
("una ventana al revés no es una ventana"). Lo omití al escribir la hermana: la
forma exacta de C1, esta vez producida por mí, y a veinte minutos del original.

✅ Validación de par, de formato ISO y de orden. Los 11 casos hostiles dan None.

## 🔴 2. Mi guard estructural tenía FALSOS NEGATIVOS

Lo escribí con una expresión regular que sólo sabía balancear **un** nivel de
paréntesis. Una llamada con dos niveles (`_bef(b, f(g(x)), …)`) o partida en varias
líneas podía no matchear — y entonces **el guard no reportaba al culpable**.

Un guard con falsos negativos es peor que no tenerlo: da la tranquilidad sin la
garantía.

✅ Reescrito con `ast` (el parser de Python, que no tiene ese problema) **y con un
guard del guard**: se le da código que sí está mal, en las cuatro formas que el
regex se comía, y tiene que verlo. Contra el código viejo sigue señalando
exactamente `main.py:34820`.

## 3. Mis tests eran frágiles por el estado global

`fx_rates_daily.date` es **PRIMARY KEY** y la tabla es global (no lleva `user_id`).
Dos problemas:

- el `setUp` insertaba sin borrar: una fila que sobreviviera a un tearDown
  reventaba el test siguiente con `IntegrityError`, por una razón ajena a lo que
  mide;
- el `tearDown` borraba la tabla global **al final** del mismo `try` que los
  deletes por `user_id`: si uno de esos fallaba, la fecha quedaba sucia.

✅ `setUp` idempotente y la tabla global se limpia primero, en su propio `try`.

## 4. Conteo honesto de qué miden mis tests — contado, no afirmado

Contra el código viejo (los cuatro archivos de código revertidos, tests intactos):
**28 fallan, 6 pasan**. De los 28:

- **16** fallan con `AttributeError` / `unexpected keyword argument 'moneda'` →
  prueban que la función o el parámetro son NUEVOS. **No miden el bug.**
- **12** fallan con un **número distinto** → ésos son los que miden.

Los 6 que pasan verifican lo que NO tenía que cambiar (la rama de dólares), y
pasan a propósito. El conteo quedó escrito en la cabecera de cada archivo.

## 5. Una afirmación mía imprecisa (C12 propio, otra vez)

Escribí que "los tres call sites piden la conversión a `retorno_bench_en_moneda`".
Un grep del nombre devuelve **dos**: el tercero (el tramo parcial) llega por dentro
de `benchmark_entre_fechas`. Quien leyera eso iba a buscar una llamada que no
existe y a concluir que falta un call site. ✅ Aclarado en el propio comentario.

---

## Lo que se verificó y NO es problema

- **Doble conversión: no hay.** La rama de la composición sólo corre cuando el
  motor no publicó (`year_twr_pct is None`), así que un número nunca pasa por las
  dos. Comprobado además por el valor: con 100 % de devaluación el resultado es
  ×2, no ×4.
- **Performance: despreciable.** Las llamadas a `serie_fx` que agregué cuestan
  **0,69 ms** cada una; 60 reportes suman 41 ms.
- **Aislamiento entre archivos de test: no aplica.** Medido con dos módulos sonda:
  cada archivo recibe **su propia base** (`tmpjz9e0jaa.db` vs `tmpfen2ik35.db`),
  por el fixture `_db_por_modulo` del conftest. Las colisiones de fecha que tengo
  con `test_vs_inflacion_en_pesos.py` (F5) no pueden pisarse.
  ⚠️ **El handoff está desactualizado en este punto**: dice "toda la suite comparte
  UNA base". Ese conftest lo arregló. Corrido en los dos órdenes: 42 passed.
- **Mis tests atraviesan el camino de producción.** Comparé
  `compute_metrics_for_period` (lo que prueban) contra `build_period_report` (por
  donde entra el endpoint) **campo por campo y en las dos monedas**: coinciden. Y
  `build_period_report` sólo LEE las métricas para decidir `is_relevant` — no pisa
  ninguno de los campos que cambié.

## 🔴 6. Y auditando la auditoría: **borré 4 tests sin darme cuenta**

Al reescribir el guard estructural usé un corte por índices
(`archivo[:inicio] + nuevo + archivo[fin:]`) y entre esos dos puntos vivía la clase
`ElTCNegativoTest` entera. **Se fue con el reemplazo.**

Lo grave es cómo se detecta: **ningún test falló.** Los tests borrados no fallan,
simplemente dejan de existir. La suite quedó en verde, con 4359 passed.

**Lo único que lo cazó fue el CONTEO.** Venía de 4361, agregué 2 tests, y dio 4359
en vez de 4363. Cuatro de menos.

⚠️ **ESTO MATIZA UNA REGLA DEL HANDOFF.** Dice que "el conteo de fallos NO es
métrica (un usuario de más lo mueve)" — y es cierto para los FALLOS. Pero el conteo
de tests **que pasan** sí es métrica para una cosa concreta: detectar tests que
desaparecieron. Es la única señal que existe para eso, porque un test borrado no
produce ningún rojo.

Es la misma familia que la trampa de `cat > archivo` que destruyó 13 casos en F5,
con otra herramienta: un reemplazo por índices se lleva todo lo que hay en medio.
**Contar antes y después de cualquier reescritura de un archivo de tests.**

✅ Recuperada del último commit con `git show HEAD:<archivo>` y reinsertada. 29
tests en el archivo, las 6 clases.

---

# Cuarta ronda: el código que NO se modificó

Pedida explícitamente: auditar tanto lo tocado como lo no tocado. La regla de
propagación aplicada a los **defectos de la auditoría**, no sólo a los del
producto: si mi función tenía cinco agujeros de ventana y un guard de TC débil, su
hermana literal es la primera sospechosa. Lo era.

## 🔴 1. El guard del TC estaba en CUATRO lugares y yo había arreglado UNO

`not f0 or not f1` pregunta *"¿tiene valor?"*, no *"¿es un tipo de cambio?"*.
Censo completo:

| función | estado antes | qué hacía con un TC negativo |
|---|---|---|
| `twr.retorno_en_pesos_pct` | ✅ ronda 2 | — |
| `twr._factor_fx` | ❌ | devolvía un **factor de devaluación NEGATIVO** (−1,2) |
| `twr._leg_en_moneda` | ❌ | devolvía un flujo **COMPLEJO** |
| `reporting.builder._pct_en_pesos` | ❌ | dejaba pasar el negativo |

**Un fix que llega a 1 de 4 call sites no está terminado** — la causa raíz de este
proyecto, cometida mientras la cerraba.

✅ **Y no se cerró repitiendo la condición cuatro veces.** El primer intento fue
poner `float(f) <= 0` en cada uno — o sea dejar de nuevo cuatro copias de la misma
regla esperando a separarse, que es exactamente lo que esta tanda viene a evitar.
Quedó **una sola función, `twr.fx_usable`**, y un guard estructural que impide que
nazca la quinta copia.

Repetir la condición además **no alcanzaba**: `nan` e `inf` pasan cualquier
`<= 0` (`nan <= 0` es False) y salían por el otro lado convertidos en un
rendimiento `nan`. Y `"abc"` o una lista reventaban con un `ValueError` cuyo
mensaje no decía que el TC era la causa. La función cubre los cinco motivos —
None, cero, negativo, no-finito y no-numérico— y devuelve el float ya convertido.
Medido: 14 de 14 casos, y los cuatro consumidores degradan a "no sé" sin tirar.

### El número complejo, medido

`_leg_en_moneda` calcula el TC medio como `(f0·f1) ** 0.5`. Con el producto
negativo eso es la raíz de un negativo. Con f0=−1000, f1=1200 y flujo 500:

    flow → (3.35e-11 + 547722.5575j)

que revienta después en `_modified_dietz_pct` con *"'<=' not supported between
instances of 'complex' and 'int'"*. **No se publicaba un número malo** —el
try/except del caller lo vuelve None— pero el período se perdía por una excepción
en vez de por una decisión, y el log se llenaba de tracebacks sin causa visible.

## 🔴 2. `_pct_en_pesos` tenía los CINCO agujeros de ventana de su hermana

Es la que produce el `delta_pct` en pesos del **camino principal**, y ya está
deployada. MEDIDO sobre un tramo de +10 % en dólares con el TC duplicándose
(la respuesta correcta es +120 %):

| ventana | devolvía |
|---|---|
| invertida · un solo día · basura `("x","y")` · no ISO · una punta en None | **10,0 — el número de DÓLARES** |

Misma causa: `serie_fx` arrastra, las dos puntas dan el mismo TC, la conversión
queda en identidad.

⚠️ **HOY NO ES ALCANZABLE**, y eso hay que decirlo: los tres call sites arman las
fechas bien — `bordes_mercado_periodo` garantiza `fin > ini` con dos guards
propios, y el tercero protege con `if _d0c`. **No es un bug vivo.** Se cierra igual
porque el cuarto call site que alguien agregue no va a traer esos guards puestos:
es exactamente así como nació el defecto en la hermana, escrita el mismo día.

## 🔴 3. Un supuesto que sostiene TRES fixes y no tenía un solo test

*"`twr.curva_indexada` con `moneda=ARS` devuelve pesos"* es la premisa de:

- el fix de F5 (el mes de Reportes),
- el de la otra sesión (el año),
- el mío (el tramo parcial).

Los tres **restan** un benchmark convertido a pesos de un número que sale de ahí.
Si devolviera dólares, los tres estarían cruzados y ninguno se notaría.

**Cinco call sites de producción le pasan `moneda`. Ningún test lo hacía** — todos
usaban el default. ✅ Cerrado con cuatro tests, incluido uno que verifica la otra
mitad: que el motor convierta con **`serie_fx`, la misma fuente que el benchmark**
(`twr.py:1535`, verificado). Con fuentes distintas la devaluación no se cancelaría
entre los dos lados de la resta — el mismo defecto con un disfraz mucho peor.

## 4. Verificado y sano: el código que no toqué y está bien

- **`_dia_anterior`**: maneja bisiestos (2024-03-01 → 2024-02-29), fin de año, y
  devuelve None para `None`, `""`, `"x"` y `"2026-13-45"`. Sólido.
- **`bordes_mercado_periodo`**: ya tiene los dos guards que evitan `d0 >= d1`. Es
  la razón por la que el defecto #2 no es alcanzable.
- **`serie_fx` arrastra a propósito** — es su diseño documentado, no un bug. Lo que
  faltaba era que los lectores no confundieran "arrastró" con "midió".
- **`benchmark_entre_fechas`** (de la otra sesión) corta bien la ventana invertida
  y las fechas basura. ⚠️ **Asimetría observada, no tocada**: con un solo día
  devuelve `0,0` donde la hermana devuelve `None`. Para el año no es alcanzable
  (el motor mide tramos, no días). Se anota en vez de tocarles el código.

---

# F6 · los 11 lectores de rendimiento — MEDIDO sobre producción

Medido en **solo lectura** sobre la copia real `trading-2026-08-16.db`: 673 usuarios,
13.144 filas de `monthly_entries`.

## El censo, corregido: F2 ya migró tres, pero al primitivo EQUIVOCADO

| lector | qué usa hoy | qué le falta |
|---|---|---|
| `wrapped.py` | `twr.retorno_mensual` | el denominador chico y el salto |
| `ai/builders/insights_evolution.py` | `twr.retorno_mensual` | ídem |
| `ai/builders/reports.py` | `twr.retorno_mensual` | ídem |
| `ai/builders/insights.py` | **el motor** (`serie_medible`/`curva_indexada`) | ✅ cubierto |
| `ai/builders/dashboard.py` | `(end−start)/start` crudo | todo — ni resta flujos |
| `advisor_brief.py` | `(now−base)/base×100` crudo | todo |
| `main._snapshot_delta` | pct sobre valor base, con flujos | `leg_dudoso` |

`retorno_mensual` tiene DOS guards (`ci > 0` y el denominador ≤ 0 de `dietz`) y **no
tiene** los otros dos de `leg_dudoso`: el **denominador chico** (25 %) y el **salto ×3**.
Ésa es la mitad cara.

## ⚠️ Y propagar `leg_dudoso` NO ARREGLA EL PROBLEMA — medido

Lo que el guard taparía: **124 meses de 10.772 (1,15 %), 98 usuarios.** Ninguno es un
rendimiento real — el peor es `ci=575 → cf=4.035.223 con US$202 de flujo` (**+596.335 %**),
y los seis más chicos tienen el **capital final NEGATIVO**. Cero falsos positivos.

Pero lo que se publica no es el mes: es el **compuesto**. Y ahí:

| | >100 % | >1000 % | el peor |
|---|---|---|---|
| hoy | 121 | 25 | **+129.544 %** |
| con `leg_dudoso` (saltear el mes) | 113 | 21 | +39.439 % |
| con `leg_dudoso` + **cortar el tramo** | 98 | 19 | +30.300 % |

**Ninguna de las dos resuelve.** Y saltear tiene un efecto contraintuitivo: a algunos el
número les **sube** (uid 826: 884 % → 3.983 %), porque el guard saca el mes de la caída y
deja los que parten de la base ya achicada. El propio comentario de `leg_dudoso` dice que
un leg no creíble **corta el tramo**, no se saltea — y estos lectores lo saltean.

## ⭐ Lo que SÍ resuelve: el motor. Y está medido

Para los mismos usuarios:

| | hoy publica | el motor dice |
|---|---|---|
| uid 118 | **+129.544 %** | **+0,7 %** |
| uid 904 | +5.090 % | −0,3 % |
| uid 992 | +2.719 % | −3,5 % |
| uid 421 | +2.027 % | −0,0 % |

**De los 373 usuarios que tienen los dos números, los 373 quedan bajo 100 % con el motor.
Cero absurdos. El peor pasa de +129.544 % a +96,6 %.**

## El costo de migrar, sin maquillar

| | usuarios |
|---|---|
| publican hoy (compuesto contable) | 575 |
| el motor puede medir | 438 |
| **pierden el número** | **202** |
| ganan un número que hoy no tienen | 65 |

Por qué el motor no puede con esos 202: `importado_sin_mediciones` 168 · `medicion_dudosa`
31 · `una_sola_medicion` 2 · `serie_partida` 1.

Y de esos 202, **lo que están viendo hoy**:

| lo que ven hoy | cuántos |
|---|---|
| 0–50 % (razonable) | 117 (57,9 %) |
| 50–100 % (alto pero posible) | 27 (13,4 %) |
| 100–1000 % (dudoso) | 44 (21,8 %) |
| >1000 % (imposible) | 14 (6,9 %) |

Mediana: **33,6 %**.

→ **58 cambiarían un número imposible por "no se puede medir"** (puro beneficio) y
**144 cambiarían uno plausible por "no se puede medir"** — **ése es el costo real, y es
una decisión de producto, no técnica.**

## La tercera opción, que el repo ya usa en Reportes

`reporting/schema.py` tiene el campo `basis` (`'mercado'` vs `'contable'`) justamente para
esto: no quitar el número, sino **decir de dónde sale**. Combinado con `leg_dudoso` + corte
de tramo, nadie pierde el número y nadie ve basura sin aviso. Falta medirla.

---

# Auditoría de la migración — dos bugs vivos más, en código que no había tocado

## 🔴 1. Los chips Δ1d / Δ7d / Δ30d del Dashboard no tenían UN SOLO guard

Es el número que el usuario ve **todos los días**. MEDIDO sobre la copia de
producción, 794 usuarios con cinco o más fotos:

| | antes | después |
|---|---|---|
| Δ1d | −8.093,1 % | **100,0 %** |
| Δ7d | **−9.346.280,6 %** | **100,7 %** |
| Δ30d | −9.170.283,9 % | **110,5 %** |

No son rendimientos, son **datos rotos**: al uid 329 el `net_deposited` le salta de
−1.055.894 a **+1.699.812.606** de un día para el otro con la cartera quieta en
18.400; el uid 412 tiene una foto donde la cartera vale **−805.744**.

Costo: **3 o 4 usuarios por ventana** se quedan sin chip. A cambio, nadie ve nueve
millones por ciento.

## 🔴 2. El mail diario del asesor tampoco, y ahí el error se amplifica

Sus filtros cuidan la **calidad de la foto** (`apto`, ni import ni reconstrucción)
pero ninguno mira el número que sale. Y `movers` **ordena por ese %**: el cliente
con el dato roto sale primero y el mail lo anuncia como *«el mejor del día»*.

El informe lo marca como el caso más caro de los once: en el **informe firmado** el
guard sí existe (`_cortes_adentro`); en el **mail** no.

## 3. Mi propio parseo de fechas fallaba en silencio

Era `int(str(d)[:4]) * 100 + int(str(d)[5:7])`. Medido:

| entrada | devolvía |
|---|---|
| `"2025-1-1"`, `"20250101"`, `2025`, `["x"]` | **sin número, en silencio** |
| `"2025-13-99"` | lo aceptaba entero (el mes 13 no existe) |

El usuario se quedaba sin rendimiento por un error **del que llama**, indistinguible
de "esta cuenta no se puede medir", con un `log.exception` enterrado como única
pista. Ahora `twr.clave_mes` valida forma **y mes**, y una ventana inválida se
**declara** (`motivo='ventana_invalida'`) en vez de desaparecer.

## 4. Y yo mismo había duplicado la definición de "fecha ISO"

`reporting.builder` tenía su propio regex — lo escribí dos rondas atrás, en el
arreglo cuyo comentario dice *"no se copia acá: vive en el motor"*. Ahora le
pregunta a `twr.clave_mes`, que además valida el mes, cosa que un regex de forma
no mira.

---

## Estado de los 11 lectores

| | estado |
|---|---|
| `wrapped.py` | ✅ al motor, con etiqueta en el slide compartible |
| `ai/builders/insights_evolution.py` | ✅ al motor |
| `ai/builders/reports.py` | ✅ al motor |
| `ai/builders/dashboard.py` | ✅ al motor (+ el reloj UTC arreglado) |
| `ai/builders/insights.py` | ✅ ya usaba el motor |
| `main.py::_snapshot_delta` | ✅ `leg_dudoso` |
| `advisor_brief.py` | ✅ `leg_dudoso` |
| `frontend/utils/evolution.js` | ⬜ pendiente |
| `frontend/utils/insightsModel.js` | ⬜ pendiente |
| `frontend/pages/Insights.jsx` | ⬜ pendiente |
| `frontend/hooks/useMonthlyData.js` | ⬜ pendiente |

**7 de 11.** Los cuatro que faltan son del frontend, donde `leg_dudoso` no existe
en ninguna forma: o se porta a JS con un guard estructural que verifique que las
dos versiones no se separen (el patrón de F5), o esas pantallas pasan a consumir
`/insights/performance`, que es lo que el informe recomienda.
