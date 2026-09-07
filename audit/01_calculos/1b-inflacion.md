# 1B — Inflación, UVA y CER

> Auditor externo · tanda 1B · 2026-09-07
> Código leído: copia de sólo lectura `/tmp/rendi-main` (`b74f450f`, `backend/main.py` = 38.029 líneas, verificado).
> **No se modificó ni una línea de código del proyecto.** Lo único escrito es este archivo.

---

## Método

**Qué ejecuté (y de dónde salen los números etiquetados MEDIDO):**

1. **Verificación de la copia de referencia.**
   `wc -l /tmp/rendi-main/backend/main.py` → `38029`. ✅

2. **Llamadas HTTP reales a las tres fuentes externas que el código usa**, desde el scratchpad, `curl` + `python3`:
   - `GET https://api.argentinadatos.com/v1/finanzas/indices/inflacion` → **200**, 1.001 puntos, 1943-03 … **2026-07**.
   - `GET https://api.argentinadatos.com/v1/finanzas/indices/uva` → **200**, 3.813 puntos diarios, 2016-03-31 … **2026-09-07**.
   - `GET https://api.argentinadatos.com/v1/finanzas/indices/cer` → **404 `{"error":"Not found"}`**.
   - Sondas de control sobre el mismo host: `/finanzas/cer` 404, `/finanzas/indice-cer` 404, `/finanzas/cer-diario` 404, `/finanzas/indices/cer` 404, `/finanzas/indices/inflacionInteranual` **200**.

3. **Ejecución del código real del backend, aislado.** Copié `backend/performance.py` a un directorio temporal propio con un `twr.py` stub (para NO importar `main` y NO crear `trading.db` dentro de `/tmp/rendi-main`) y corrí `benchmark_recortado()` sobre la serie IPC verdadera.

4. **Reimplementación literal, en un script, de las funciones de agregación** (`_fetch_inflation_ar`, `_fetch_uva_monthly`, la ventana de 12 meses de `detect_inflation_loss`, la composición YTD de `_build_chat_benchmarks` y de `wrapped`) alimentadas con las series reales bajadas en el paso 2.

**Qué NO pude ejecutar (y por qué):**

- No corrí nada que importe `backend/main.py` — importar `main` crea `trading.db` adentro del árbol de referencia y lo contamina (ya pasó una vez en esta auditoría).
- **No tengo acceso a la base de producción.** Por eso no puedo decir cuántas filas tiene hoy `bond_indices_daily`, ni cuántos usuarios tienen bonos CER, ni cuántos tienen cash en pesos. Todo lo que dependa de eso queda como DEDUCIDO o ESTRUCTURAL, nunca como MEDIDO.
- No corrí la suite de tests.
- No abrí la UI: todo lo de frontend es lectura de código + `grep`.

**Verificación de citas.** Toda cita a archivo:línea de este informe fue confirmada con `grep -n`/`sed -n` sobre `/tmp/rendi-main`. Las citas del mapa que toqué (7) resultaron **todas correctas** — ver la sección correspondiente.

**Deriva conocida.** Ningún hallazgo de este informe cae en `backend/pricing/fci.py`, `frontend/src/components/AddPositionFlow.jsx`, `backend/tests/test_fci_uala.py` ni `backend/snapshots_job.py`. No hay marcas "posiblemente ya corregido" ni "zona de trabajo activa".

---

## Preguntas que necesito que contestes

De las 11 pre-filtradas necesito **tres**, y agrego **tres propias**. El resto (P-162/163/164/183/184/185/186/187) son de facturación y no tocan este tema.

1. **P-051 — `/api/bond-indices` acepta `UVA` y `A3500` pero no tiene fetcher para ninguno de los dos.** ¿Son features planeadas o restos? Lo pregunto porque **la respuesta cambia la severidad del hallazgo #1**: si `UVA` estuviera implementado, sería el reemplazo natural y verificado-vivo de la serie CER que hoy da 404.

2. **P-246 — ¿`vs_inflación` debe publicarse cuando la moneda es USD?** Hoy se publica siempre, y el retorno que se le resta está en dólares. Necesito saber si la respuesta correcta es *gatear* (no mostrar) o *convertir* (medir el retorno en pesos), porque son dos arreglos distintos en 6 lugares.

3. **P-260 — ¿mobile tiene que tener paridad de renta fija con desktop?** Confirmo que en el celular los bonos CER van sin ajuste **y sin el cartel de aviso** que el desktop sí muestra.

4. **(propia) ¿`bond_indices_daily` tiene filas de CER en producción hoy?** Si la fuente funcionó en algún momento del pasado, el síntoma no es "factor 1" sino "factor congelado en la fecha en que murió la fuente", que se ve distinto y se arregla distinto. No tengo cómo mirar la base.

5. **(propia) ¿Cuántos usuarios tienen hoy un bono CER (TX26/TX28/T2X5/TZX26/TZX27/TZX28) en cartera, y cuántos tienen cash en pesos > 0?** Es el multiplicador de blast radius de los hallazgos #1-#3 y #7-#8.

6. **(propia) ¿El "vs inflación" que querés publicar es el retorno REAL (`(1+r)/(1+π)−1`) o la diferencia en puntos porcentuales (`r−π`)?** Hoy conviven las dos definiciones bajo rótulos casi idénticos: Insights usa la primera, los otros 6 sitios la segunda. Si la respuesta es "puntos porcentuales", el arreglo es de rótulo; si es "retorno real", es de fórmula.

---

## Resumen ejecutivo

**El concepto existe, pero está partido en dos mitades de calidad opuesta.**

**La mitad buena** es la de Insights + el packet de benchmarks del chat. Ahí la inflación se compone geométricamente, el retorno real usa Fisher (`(1+r)/(1+π)−1`), se gatea explícitamente por moneda ("NUNCA mezclar retorno-USD con inflación-pesos"), la ventana de inflación se recorta a exactamente la misma ventana del retorno, y el packet del chat hasta publica `ytd_through` para que el modelo declare el rezago del INDEC. Está bien pensado y bien comentado.

**La mitad mala son todos los demás lugares**, que son la mayoría de las superficies del producto: Reportes, Wrapped, y los cuatro packets de IA. Ahí `vs_inflación` es literalmente `retorno_en_dólares − inflación_en_pesos`. Dos errores apilados: mezcla de monedas y aproximación aditiva de Fisher. **Verificado con `grep`: son exactamente 6 call sites y ninguno tiene gate de moneda.**

**Y hay una tercera pieza que directamente no funciona: el CER.** `_fetch_cer_series` (`backend/main.py:5572`) pega a un endpoint que **hoy devuelve 404** (medido, con controles del mismo host devolviendo 200). Sin serie CER, los bonos CER de la app calculan sus flujos con factor de ajuste **1,00**, cuando el factor real medido es **7,72×** para los TZX y **37,44×** para TX26/TX28/T2X5. La pantalla del bono dice las dos cosas contradictorias en la misma tarjeta: "Serie CER no disponible — flujos en nominal sin ajuste" en el panel de arriba, y doce líneas abajo rotula el número grande como **"TIR real (sobre CER)… es lo que ganás POR ENCIMA de la inflación"**.

**Lo que SÍ está bien y conviene no romper:** nadie suma inflaciones mensuales. Busqué el patrón explícitamente (`grep -rn 'infl.*+=|+= *infl|sum(.*infl'`) y **no hay un solo sitio** que sume en vez de componer. Los 9 lugares que agregan inflación mensual a acumulada lo hacen con `Π(1 + ipc/100)`. Ese error clásico argentino no está.

**Índice usado:** IPC INDEC mensual, vía `api.argentinadatos.com`. **Fecha base:** no hay una sola — cada consumidor ancla en la suya (primer mes de la serie del usuario, o los últimos 12 keys, o enero del año). **Mes en curso:** el INDEC publica con ~2 meses de rezago (medido hoy: el último publicado es **2026-07**), y el código elige **arrastrar plano** el último valor conocido. Eso sesga sistemáticamente **a favor del usuario** (le descuenta menos inflación de la que hubo) y sólo un lugar de la app lo declara.

---

## Mapa del concepto

*(este concepto no estaba mapeado — lo que sigue es mapeo nuevo, todo verificado con `grep -n`/`sed -n`)*

### A · Las cuatro fuentes de dato

| índice | fetcher | URL | verificado hoy | dónde se cachea |
|---|---|---|---|---|
| **IPC INDEC** mensual (% del mes) | `_fetch_inflation_ar` · `backend/main.py:5276` | `api.argentinadatos.com/v1/finanzas/indices/inflacion` | **200** · 1.001 pts · hasta `2026-07` | `_bench_cache` en memoria del proceso, TTL 1 h, patrón SWR (`main.py:5202`, `:5231`) |
| **UVA** (nivel, último día del mes) | `_fetch_uva_monthly` · `backend/main.py:5474` | `.../indices/uva` | **200** · 3.813 pts diarios · hasta `2026-09-07` | idem `_bench_cache` |
| **CER** (nivel, diario) | `_fetch_cer_series` · `backend/main.py:5572` | `.../indices/cer` | **404 `{"error":"Not found"}`** | tabla `bond_indices_daily`, TTL 4 h en `_indices_fetched` (`main.py:5569`) |
| **A3500** | *no existe fetcher* | — | — | `fetcher_map = {"CER": _fetch_cer_series}` (`main.py:5600`) |

Notas verificadas:
- `_fetch_inflation_ar` mapea `fecha[:7] → float(valor)`. Las fechas de la API son fin de mes (`2026-07-31`), así que la clave sale `'2026-07'`. Correcto.
- `_fetch_uva_monthly` toma **el último valor de cada mes por sobre-escritura de dict**, apoyándose en que la API viene ordenada ascendente. Verificado: viene ordenada. Pero para el **mes en curso** eso significa "el valor del día 7", no "el cierre del mes" — ver hallazgo #11.
- `/api/benchmarks` (`main.py:5607`) sirve todo esto al frontend menos las series `_d`.

### B · Los 13 consumidores

| # | sitio | archivo:línea | índice | fecha base del ajuste | fórmula |
|---|---|---|---|---|---|
| 1 | Insights · diagnóstico `beat/lose_inflation_ars` | `frontend/src/utils/diagnostics.js:201`, `:218` | IPC | ventana ARS del usuario (`arsWindowFirstKey`+1 … último IPC) | `(1+r_ars)/(1+π)−1` ✅ **Fisher, gateado a `currency==='ARS'`** |
| 2 | Insights · card "¿Le ganás a las alternativas?" fila Inflación | `frontend/src/pages/Insights.jsx:2592-2601` | IPC | idem #1 | `(1+r_ars)/(1+π)−1` ✅ Fisher, **sin gate de moneda** |
| 3 | Insights · card "Expectativa de retorno" | `frontend/src/pages/Insights.jsx:2278-2295` | IPC | idem #1 | `(1+r)/(1+π)−1` ✅ Fisher, pero `r` sale de **otra** fuente que #2 (ver #12) |
| 4 | Insights · línea "Inflación AR" del gráfico | `backend/performance.py:88-154` vía `/api/insights/performance?bench=inflation_ar` | IPC | `fechas[0][:7]`, índice 1,0 (excluye el IPC del mes base) | `Π(1+ipc/100)` ✅ compone; arrastra plano los meses sin publicar |
| 5 | **Reportes · celda "vs Inflación AR"** | `backend/reporting/builder.py:1647` → `frontend/src/components/reports/MonthCard.jsx:232` | IPC del mes | mes del período | **`delta_pct − inflation_ret`** 🔴 resta, y `delta_pct` es USD por defecto |
| 6 | **Wrapped · slide "vs inflación"** | `backend/wrapped.py:378` (base en `backend/main.py:13742-13754`) | IPC | enero del año | **`twr_user − inflation_ytd`** 🔴 resta + `twr` es USD |
| 7 | **Packet IA dashboard** | `backend/ai/builders/dashboard.py:197` | IPC del último mes disponible | último key de la serie | **`twr_30d_pct − last_infl`** 🔴 resta + USD + ventana desalineada (30 d vs 1 mes) |
| 8 | **Packet IA insights** | `backend/ai/builders/insights.py:623` | IPC | `today − window_days` | **`twr_pct − inflation_pct`** 🔴 resta + USD |
| 9 | **Packet IA insights.benchmarks (`verdicts`)** | `backend/ai/builders/insights_benchmarks.py:151` | IPC | ventana que declara el motor | **`user_pct − inflation_pct`** 🔴 resta + USD (`performance(...)` sin `moneda=`) |
| 10 | **Packet IA monthly** | `backend/ai/builders/monthly.py:194` | reexporta `vs_inflation_pct` de #5 | — | hereda el error de #5 |
| 11 | Packet chat · `_build_chat_benchmarks` | `backend/main.py:23026-23180` | IPC | `{año}-01`, con `ytd_through` publicado | ✅ compone YTD, ✅ arma `ars_ytd_pct_approx = (1+r_usd)(1+dev_blue)−1`, ✅ el `_note` prohíbe explícitamente comparar USD contra inflación-pesos |
| 12 | Behavioral · `inflation_loss` | `backend/behavioral.py:1276-1362` | IPC | últimos 12 *keys de la serie* (hoy `2025-08…2026-07`) | `cash_ars × π/(100+π)` — ✅ fórmula de poder de compra correcta, ❌ fallback `60.0` hardcodeado |
| 13 | Renta fija · ajuste de capital de bonos CER | `frontend/src/utils/bondSchedule.js:138-173`, `:242-259` | **CER** | `meta.cerEmissionDate` por bono (`bondMeta.js:113-132`) | `CER(fecha_pago)/CER(emisión)`, LOCF · **hoy siempre 1,00 porque la fuente da 404** |

### C · Los tres consumidores que existen en el código y no llegan a ninguna pantalla

| sitio | archivo:línea | estado |
|---|---|---|
| `computeInflationCumulative` → `inflationCum` | `frontend/src/utils/benchmarkSim.js:193` · `Insights.jsx:2173` | se calcula y **no lo lee nadie**. El comentario de `Insights.jsx:2315` afirma que "se usa en otros lugares de la UI" — **es falso** |
| `InflationCard` | `frontend/src/pages/Insights.jsx:3576` | componente definido, **nunca renderizado** (`grep -rn 'InflationCard' frontend/src` → sólo la definición) |
| `computeDriversForMonth.vsInflation` / `vsInflationPending` | `frontend/src/hooks/useMonthlyData.js:119-126` | el único consumidor del hook es `MonthlyTeaser.jsx:37`, que lee `{loading, years, hasAnyData}`. `month.drivers` no lo lee ningún componente |

### D · Qué NO existe

- **No hay ajuste por inflación de series de patrimonio.** En ninguna parte se deflacta una curva, un capital aportado, ni un P&L. "Retorno real" en esta app significa siempre *un solo número comparado contra un solo número*, nunca una serie ajustada.
- **No hay retorno real anualizado.** Todos los "retorno real" son acumulados de la ventana.
- **No hay UVA como índice consultable** (`/api/bond-indices/UVA` responde `{}`), ni A3500.
- **No hay CER en el backend fuera de `bond_indices_daily`.** Ningún cálculo de performance usa CER.
- **No hay inflación en USD** (correcto — sería un sinsentido) ni ajuste de la cartera por CPI de EE.UU.
- **No hay extrapolación ni nowcast** del mes no publicado. La única política es arrastre plano.

---

## Tabla de hallazgos

| # | hallazgo | evidencia | severidad | dónde muerde | causa raíz |
|---|---|---|---|---|---|
| 1 | La fuente de CER devuelve **404**: todos los bonos CER calculan con factor 1,00 en vez de 7,72×–37,44× | **MEDIDO** | 🔴 | cronograma, próximo pago, TIR y monto pre-llenado de cupón de TX26/TX28/T2X5/TZX26/27/28 | `_fetch_cer_series` apunta a una URL que la fuente ya no sirve, y devuelve `{}` en silencio |
| 2 | La TIR se rotula **"TIR real (sobre CER)"** aunque el ajuste CER no se haya aplicado | ESTRUCTURAL | 🔴 | pantalla de detalle del bono | el rótulo se decide por `meta.type==='cer'`; el cálculo, por `cerOpts` — dos condiciones distintas para el mismo hecho |
| 3 | El "próximo pago" y el monto pre-llenado del cupón **nunca** llevan el ajuste CER, ni con serie disponible | ESTRUCTURAL | 🔴 | inbox de cobranzas, Novedades, filas de Renta Fija, modal de registro de cupón | 6 de 8 call sites de `generateSchedule`/`nextPaymentForPosition` no reciben `cerSeries` |
| 4 | Los 6 `vs_inflación` del backend comparan **retorno en dólares contra inflación en pesos** | ESTRUCTURAL | 🔴 | Reportes, Wrapped, y los 4 packets que alimentan a la IA | ningún call site pasa `moneda`; el default de `performance()` y de los endpoints de reportes es `usd` |
| 5 | Los mismos 6 sitios usan la aproximación `r − π` en vez de Fisher | **MEDIDO** (error cuantificado con IPC real) | 🟠 | idem #4 | — |
| 6 | Los ~2 meses que el INDEC todavía no publicó se arrastran **planos** y sólo un sitio de la app lo declara | **MEDIDO** | 🟠 | gráfico de Insights, celda de Reportes, verdicts de la IA | política de arrastre correcta, comunicación ausente |
| 7 | `detect_inflation_loss` cae a **60 % anual hardcodeado** si la fuente falla; el real medido es 33,82 % | **MEDIDO** | 🟠 | card "Pérdida por inflación" (Comportamiento, Objetivos, Wrapped, packet IA) | número mágico en vez de "no hay dato" |
| 8 | `detect_inflation_loss` aplica **12 meses** de inflación al saldo en pesos **de hoy** | ESTRUCTURAL | 🟠 | misma card | la métrica no mira el historial del saldo |
| 9 | En **mobile** los bonos CER van sin ajuste **y sin el cartel de aviso** que sí muestra el desktop | ESTRUCTURAL | 🟠 | `PositionsMobile` → `RentaFijaSections` | 3 props (`cerSeries`, `cerStale`, `tcMep`) no se pasan |
| 10 | La opción **"Plazo fijo UVA"** del selector del gráfico queda habilitada y no dibuja nada | **MEDIDO** | 🟡 | gráfico de Insights en modo Pesos | el frontend pide `bench=plazo_fijo`; el backend produce la clave `uva` |
| 11 | `_fetch_uva_monthly` toma el **último día disponible** del mes en curso como si fuera el cierre | **MEDIDO** (2026-09 = +0,47 % con 7 días) | 🟡 | benchmark "Plazo fijo UVA" de las cards | el dict-overwrite no distingue mes cerrado de mes vivo |
| 12 | `RETURN_EXPECTATION_META.floorReal` (0/3/10/18) compara varas **anuales** contra un retorno real **acumulado** sin anualizar | DEDUCIDO | 🟡 | card "Expectativa de retorno" | falta la normalización temporal |
| 13 | `vs_inflation` de Reportes **no se gatea por exposición ARS** (el frontend sí lo hace en el hook muerto) | ESTRUCTURAL | 🟡 | Reportes de una cartera 100 % USA | el gate existe en JS y no se portó al backend |
| 14 | Sólo el reporte **mensual** tiene `vs_inflación`; año, semana y día devuelven `None` por diseño | ESTRUCTURAL | 🟡 | reporte anual (el más citado en Argentina) | `benchmark_return_for_period` corta en `period_type != "month"` |
| 15 | Código muerto de inflación en 3 lugares + un comentario que afirma un uso inexistente | ESTRUCTURAL | ⚪ | — | restos de iteraciones anteriores |
| 16 | `UVA` y `A3500` pasan la allowlist de `/api/bond-indices` sin fetcher → serie vacía y `stale:true` para siempre | ESTRUCTURAL | ⚪ | — | confirma P-051 |
| 17 | `benchmark_recortado` excluye el IPC del mes base — correcto para curva anclada a fin de mes, desalineado si el usuario arranca a mitad de mes | DEDUCIDO | ⚪ | gráfico de Insights | granularidad mensual del IPC contra curva diaria |
| 18 | La suite de tests **mockea** `_fetch_cer_series` → el 404 de #1 es invisible en verde | ESTRUCTURAL | ⚪ | CI | ningún test toca la URL real ni un canario de fuentes externas |
| 19 | `/api/reports/timeline` y `/period` llaman `_fetch_inflation_ar()` **en cada request**, ignorando `_bench_cache` | ESTRUCTURAL | ⚪ | latencia de Reportes | confirma el mapa (línea 27111) |
| 20 | `detect_inflation_loss` convierte con `tc_blue`; el resto del módulo con MEP | ESTRUCTURAL | ⚪ | monto en USD de la card | confirma el mapa (línea 14470) |
| 21 | `MonthCard` rotula con sufijo `%` un valor que está en **puntos porcentuales** | ESTRUCTURAL | ⚪ | celda "vs Inflación AR" y "vs S&P 500" | — |

---

## Detalle por hallazgo

### 🔴 #1 — La serie CER está muerta: el endpoint devuelve 404

**MEDIDO.** Traza de salida real:

```
--- CER ---
404
{"error":"Not found"}
--- listar indices ---
{"error":"Not found"}
--- inflacion (control) ---
200
--- uva (control) ---
200
```

Sondas adicionales sobre el mismo host (todas 404 salvo la última):

```
cer          -> 404
indice-cer   -> 404
cer-diario   -> 404
indices/cer  -> 404
inflacionInteranual -> 200
```

El código:

```python
# backend/main.py:5572
def _fetch_cer_series():
    ...
    r = requests.get("https://api.argentinadatos.com/v1/finanzas/indices/cer", timeout=10)
    if r.status_code != 200:
        return {}
```

Cadena de consecuencias, verificada línea por línea:

1. `_fetch_cer_series()` → `{}`.
2. `_ensure_index_cached` (`main.py:5594`): `if not series: return  # No actualizamos timestamp en caso de error` → la tabla `bond_indices_daily` no recibe filas nuevas **y** `_indices_fetched['CER']` queda en 0.
3. `GET /api/bond-indices/CER` (`main.py:5623`) devuelve lo que haya en la tabla y `stale = (time.time() - 0) > TTL+3600` → **`stale: true` permanente**.
4. `Positions.jsx:276` recibe `series: {}` → `setCerSeries({})`.
5. `BondDetail.jsx:79-81`: `cerOpts = (meta?.type === 'cer' && cerSeries && Object.keys(cerSeries).length > 0) ? { cerSeries } : {}` → **`{}`**.
6. `bondSchedule.js:143`: `const isCer = meta.type === 'cer' && meta.cerEmissionDate && cerSeries` → falso → `factor = 1` para todos los flujos (`:155`).

**La magnitud del factor que se pierde.** Lo medí con la serie UVA, que es el mismo coeficiente CER normalizado (`UVA_t / UVA_0 ≡ CER_t / CER_0` por construcción de la unidad), usando exactamente las `cerEmissionDate` que declara `bondMeta.js`:

```
UVA hoy 2026-09-07 2106.13
  TX26 / TX28 / T2X5:     UVA(2020-08-04)=56.25   factor a hoy = 37.44x   (el cronograma sin ajuste usa 1.00x)
  TZX26 / TZX27 / TZX28:  UVA(2023-06-30)=272.76  factor a hoy =  7.72x   (el cronograma sin ajuste usa 1.00x)
```

Los TZX son **cero-cupón** (`couponRate: 0`, `bondMeta.js:124-132`): su único flujo es el capital al vencimiento. Sin ajuste, el cronograma de un TZX28 dice que va a pagar **100 por nominal**; el número real de hoy ya va por ~772 y sigue creciendo con la inflación.

**Un matiz que no puedo cerrar sin la base de producción:** si la fuente funcionó alguna vez, `bond_indices_daily` puede tener CER histórico guardado. En ese caso el síntoma no es "factor 1" sino "factor congelado en la fecha de muerte de la fuente", y el ajuste se aplica pero se queda quieto. Es la pregunta #4 al founder.

**Causa raíz:** la app depende de un tercero gratuito sin ningún canario. La fuente cambió y nadie se enteró porque el único camino de error es `return {}` y ese `{}` se propaga en silencio hasta la pantalla.

---

### 🔴 #2 — "TIR real (sobre CER)" rotulando un número que no tiene ajuste CER

**ESTRUCTURAL.** En la **misma tarjeta**, `BondDetail.jsx` dice dos cosas incompatibles.

Panel "Bono", línea 206-212 — honesto:

```jsx
) : (
  <p className="text-[10.5px] text-rendi-warn pt-1">Serie CER no disponible — flujos en nominal sin ajuste.</p>
)
```

Panel "Rendimiento", línea 274-276 — no:

```jsx
{meta?.type === 'cer'
  ? <span … title="TIR REAL sobre la inflación: los flujos se descuentan al CER actual — es lo que ganás POR ENCIMA de la inflación.">TIR real (sobre CER) a precio de hoy</span>
  : 'TIR efectiva anual a precio de hoy'}
```

El rótulo se decide **sólo** por `meta?.type === 'cer'`. El cálculo (`:111-112`, `estimateYieldDetailed(p.asset, pricePer100Clean, today, cerOpts)`) usa `cerOpts`, que como vimos en #1 hoy es `{}`. Cuando el ajuste sí se aplica el rótulo es correcto y la decisión de proyectar el CER plano hacia el futuro (`bondSchedule.js:80-84`) es **deliberada y correcta**: proyectar CER plano hace que la TIR resultante sea efectivamente la TIR real. Pero cuando el ajuste no se aplica, el precio de mercado (que sí incorpora el CER acumulado) se descuenta contra flujos nominales sin ajustar, y el número que sale no es ni real ni nominal: es basura, rotulada como "lo que ganás POR ENCIMA de la inflación".

**Causa raíz:** el rótulo y el cálculo consultan condiciones distintas para el mismo hecho. La condición que gobierna el cálculo (`Object.keys(cerSeries).length > 0`) es la que debería gobernar el rótulo.

---

### 🔴 #3 — El "próximo pago" de un bono CER nunca lleva el ajuste

**ESTRUCTURAL.** `generateSchedule(ticker, options)` y `nextPaymentForPosition(ticker, quantity, from)` sólo aplican CER si reciben `options.cerSeries`. Barrido completo de call sites (`grep -rn 'generateSchedule(\|getNextPayment(\|getRemainingPayments(\|nextPaymentForPosition(\|totalRemainingPayout(' frontend/src backend`, excluyendo el propio módulo y los tests):

| call site | ¿pasa `cerSeries`? |
|---|---|
| `frontend/src/components/BondDetail.jsx:82` `generateSchedule(p.asset, cerOpts)` | ✅ |
| `frontend/src/components/BondDetail.jsx:83` `getRemainingPayments(p.asset, today, cerOpts)` | ✅ |
| `frontend/src/components/BondDetail.jsx:115` `nextPaymentForPosition(p.asset, p.quantity, today)` | ❌ |
| `frontend/src/components/RentaFijaSections.jsx:144` | ❌ |
| `frontend/src/components/RentaFijaSections.jsx:294` | ❌ |
| `frontend/src/components/BondCashflowModal.jsx:71` | ❌ |
| `frontend/src/utils/pendingCashflows.js:113` `generateSchedule(p.asset)` | ❌ |
| `frontend/src/utils/upcomingEvents.js:58` `generateSchedule(p.asset)` | ❌ |

**`nextPaymentForPosition` no acepta el parámetro** — su firma es `(ticker, quantity, from)` (`bondSchedule.js:377`) y llama a `getNextPayment(ticker, from)` sin opciones. O sea que ni siquiera es un olvido del caller: no hay por dónde pasarlo.

Los dos que más duelen:

- **`pendingCashflows.js:113`** arma el inbox de cobranzas pendientes con pagos **ya vencidos**, y para esos el coeficiente CER **es conocido** (no hay que proyectar nada). Aun así los propone sin ajustar.
- **`BondCashflowModal.jsx:71`** usa ese monto para **pre-llenar el campo del formulario** con el que el usuario registra el cobro. Ese número entra a `operations` y de ahí a la P&L, al capital aportado y a los reportes.

Para un cupón semestral de TX26 (2 % sobre 100 de face, `bondMeta.js:113-115`), el pre-llenado propone ~**1,0** por cada 100 nominales donde el pago real de hoy sería ~**37,4**. Un cupón cobrado en pesos registrado 37 veces más chico de lo que fue.

**Hoy el síntoma está tapado por #1** (con la serie muerta, el cronograma del detalle y el próximo pago coinciden — los dos mal). El día que la fuente vuelva, las dos mitades de la misma pantalla van a mostrar números distintos para el mismo cupón.

**Causa raíz:** el ajuste CER se agregó como un `options` opcional en el motor en vez de resolverse dentro de él. Un parámetro opcional que 6 de 8 callers no pasan no es un parámetro: es un default silencioso.

---

### 🔴 #4 — Retorno en dólares contra inflación en pesos, en 6 lugares

**ESTRUCTURAL.** Barrido exhaustivo (`grep -rn` de los 6 patrones de resta):

```
backend/wrapped.py:378:                    delta = twr_user - inflation_ytd
backend/reporting/builder.py:1647:         vs_inflation = (delta_pct - inflation_ret) if …
backend/ai/builders/insights_benchmarks.py:151:  "vs_inflation": _delta(user_pct, inflation_pct),
backend/ai/builders/insights.py:623:            round(twr_pct - inflation_pct, 2)
backend/ai/builders/dashboard.py:197:            vs_inflation_pp = twr_30d_pct - last_infl
frontend/src/hooks/useMonthlyData.js:124:       vsInflation = deltaPct - inflPct
```

En los seis casos verifiqué la **unidad del minuendo**:

- `backend/wrapped.py:378` — `twr` sale de `_twr_for_period(rows)` (`wrapped.py:50-69`), que compone `(cf − ci − net)/ci` sobre `monthly_entries`. Esa tabla está en USD. ⇒ **USD**.
- `backend/reporting/builder.py:1647` — `delta_pct` respeta `moneda`, pero el default de los dos endpoints es `usd`: `backend/main.py:33077` y `:33141` (`moneda: str = "usd"`). En modo Pesos el frontend sí manda `&moneda=ars` (`useReportsTimeline.js:35`, `Reports.jsx:123`), así que ahí la moneda coincide — el error de fórmula (#5) queda igual. ⇒ **USD por defecto**.
- `backend/ai/builders/insights_benchmarks.py:105` — `_perf.performance(conn, user_id, data, bench_key="sp500", modo=modo)`, **sin `moneda=`** → `MONEDA_USD`. ⇒ **USD**.
- `backend/ai/builders/insights.py:232-266` — compone `((cf − dep + wd)/ci) − 1` sobre `monthly_entries`. ⇒ **USD**.
- `backend/ai/builders/dashboard.py:151-163` — `twr_30d_pct` sale de `snapshots_medibles.total_value`, que es USD. ⇒ **USD**.
- `frontend/src/hooks/useMonthlyData.js:124` — `deltaPct` se calcula sobre `startUsd`/`endUsd` (las variables se llaman así, `:342-358`). ⇒ **USD**. *(mitigado: este cálculo es código muerto — ver #15)*

**Por qué es un sinsentido conceptual.** Un retorno en dólares mide *cuántos dólares más tengo*; la inflación argentina mide *cuánto poder de compra perdió el peso*. Restarlos produce un número que no responde ninguna pregunta. Numéricamente, además, le falta exactamente el factor de devaluación: la comparación honesta es `(1 + r_usd)(1 + devaluación) vs (1 + π)`.

**El único lugar del backend que lo hace bien** es `_build_chat_benchmarks` (`backend/main.py:23113-23127`), que arma explícitamente:

```python
user_ytd_ars = round(((1 + user_ytd / 100) * (1 + _blue_user_window / 100) - 1) * 100, 2)
```

y cuyo `_note` (`main.py:23158-23180`) le dice al modelo, textualmente, `"NUNCA compares el retorno USD directo contra la inflación en pesos"`. La regla está escrita en el prompt y **violada en los otros cuatro packets que alimentan al mismo modelo**.

Agrava el problema que `backend/ai/prompts.py:1069` instruye: `"PERFORMANCE SOLO desde 'verdicts' … NUNCA con twr_pct_low_confidence ni inventando un %"`. O sea que la IA tiene prohibido recalcular y está obligada a citar el número mezclado de #9.

**Causa raíz:** la moneda no viaja con el número. `performance()` y `build_period_report()` aceptan `moneda`, pero los packets de IA y Wrapped no la piden, y nadie chequea que el benchmark y el retorno estén en la misma unidad antes de restarlos. No hay un solo lugar donde se valide "estas dos series están en la misma moneda".

---

### 🟠 #5 — La aproximación `r − π` en vez de `(1+r)/(1+π) − 1`

**MEDIDO** — con la serie IPC real bajada hoy. La correcta es `real = (r − π)/(1 + π)`; la resta pelada **sobreestima el resultado por un factor `(1+π)`**, que en Argentina no es despreciable.

Los tres π son acumulados reales calculados sobre la serie del INDEC:

```
  pi=  33.82% (12m movil 2025-08..2026-07)  r_nom=   0.0% -> exacto   -25.27% | resta   -33.82% | error   -8.55 pp
  pi=  33.82%                               r_nom=  20.0% -> exacto   -10.33% | resta   -13.82% | error   -3.49 pp
  pi=  33.82%                               r_nom=  50.0% -> exacto    12.09% | resta    16.18% | error    4.09 pp
  pi=  33.82%                               r_nom= 100.0% -> exacto    49.46% | resta    66.18% | error   16.73 pp
  pi=  33.82%                               r_nom= 200.0% -> exacto   124.18% | resta   166.18% | error   42.00 pp

  pi= 117.68% (2024 completo)               r_nom=  50.0% -> exacto   -31.09% | resta   -67.68% | error  -36.59 pp
  pi= 117.68%                               r_nom= 100.0% -> exacto    -8.12% | resta   -17.68% | error   -9.56 pp
  pi= 117.68%                               r_nom= 200.0% -> exacto    37.81% | resta    82.32% | error   44.50 pp

  pi= 211.20% (2023 completo)               r_nom= 100.0% -> exacto   -35.73% | resta  -111.20% | error  -75.47 pp
  pi= 211.20%                               r_nom= 200.0% -> exacto    -3.60% | resta   -11.20% | error   -7.60 pp
```

Lectura práctica: **en el régimen de inflación de hoy (33,8 % en 12 meses) el error va de 3 a 17 pp** para retornos plausibles; en el régimen de 2023-2024 llegaba a **75-143 pp**. Con `π = 211 %` (2023) y `r = 100 %`, la resta publica **−111 %** — un retorno real por debajo de −100 %, que es aritméticamente imposible: no podés perder más que todo. Ese es el mismo patrón de "porcentajes imposibles" que el `AUDIT_benchmark_2026-09-01` ya cerró en las puntas del benchmark; acá sigue abierto por la vía de la inflación.

**El código ya sabe la fórmula correcta.** `diagnostics.js:207` la escribe en un comentario (`real = (1+rPortArs)/(1+infl) − 1`) y la implementa. No es un problema de conocimiento sino de que la implementación buena vive en una sola pantalla.

---

### 🟠 #6 — Los meses que el INDEC todavía no publicó se arrastran planos, en silencio

**MEDIDO.** Hoy es **2026-09-07** y el último IPC publicado es **2026-07**:

```
hoy: 2026-09-07 | ultimo IPC publicado: 2026-07 = 2.1 %
meses sin publicar (incl. en curso): ['2026-08', '2026-09']
```

El rezago real es de **~2 meses**, no de las "~2 semanas" del enunciado: el INDEC publica el IPC de un mes a mitad del mes siguiente, así que hasta el ~13-15 de septiembre el último dato disponible es julio. El código de la app lo sabe — `main.py:23093-23096` lo documenta: *"el rezago real es de ~2 meses (verificado con la serie viva: en julio lo último publicado era mayo)"*.

**Qué hace cada consumidor con eso:**

| consumidor | política | sesgo |
|---|---|---|
| gráfico de Insights (`performance.py:145-152`) | **arrastra plano** el último índice conocido | pro-usuario: la línea de inflación se queda quieta mientras la del usuario sigue |
| celda de Reportes (`builder.py:774-777`) | `series.get(end_mk)` → `None` → **la celda desaparece** | neutro, pero sin explicación visible |
| behavioral (`behavioral.py:1315`) | últimos 12 *keys de la serie*, no últimos 12 meses calendario | la ventana real es `2025-08…2026-07`, corrida 2 meses |
| chat (`main.py:23146-23180`) | **publica `ytd_through` y le pide al modelo que lo declare** ✅ | declarado |
| wrapped (`main.py:13744-13754`) | compone lo que haya del año | pro-usuario, sin declarar |
| packets IA insights / dashboard | componen lo que haya | pro-usuario, sin declarar |

Verifiqué el arrastre ejecutando el código real:

```
bench_key='inflation_ar' (BENCH_PORCENTUAL) sobre fechas del usuario:
   {'date': '2026-01-31', 'index': 1.0}
   {'date': '2026-02-28', 'index': 1.029}
   {'date': '2026-03-31', 'index': 1.063986}
   {'date': '2026-04-30', 'index': 1.09165}
   {'date': '2026-05-31', 'index': 1.114574}
   {'date': '2026-06-30', 'index': 1.135751}
   {'date': '2026-07-31', 'index': 1.159602}
   {'date': '2026-08-31', 'index': 1.159602}   ← plano
   {'date': 'hoy',        'index': 1.159602}   ← plano
```

**Magnitud del sesgo, DEDUCIDO** con los últimos valores medidos (2,1 % y 1,9 % mensual): la línea de inflación queda **~4,2 pp** por debajo de la real. Con la inflación de 2024 (promedio ~6,7 % mensual) serían ~13,8 pp. Es siempre a favor del usuario: la app le dice que le ganó a la inflación por más de lo que realmente le ganó.

La decisión de arrastrar es defendible y está justificada por escrito en `performance.py:97-99` (*"eso NO es interpolar un valor inventado, es decir 'el índice no publicó todavía', y el arrastre es plano y visible"*). El problema es que **"visible" no es cierto**: el gráfico no marca dónde termina el dato publicado, y ningún consumidor salvo el chat expone el equivalente de `ytd_through`. La política es correcta; la comunicación no existe.

---

### 🟠 #7 — El 60 % hardcodeado de `detect_inflation_loss`

**MEDIDO.**

```python
# backend/behavioral.py:1311-1313
if not inflation_monthly:
    # Fallback: estimación conservadora 60% anual si no hay benchmark
    inflation_cum_pct = 60.0
```

Contra la serie real:

```
ventana real usada: 2025-08 .. 2026-07
inflacion 12m acumulada MEDIDA = 33.82%
fallback hardcodeado del codigo  = 60.00%  -> ratio 1.77x
```

La pérdida se calcula como `loss_pesos = cash_ars × π/(100+π)` (`:1324`). Con π=60 el multiplicador es 0,375; con π=33,82 es 0,2527. **El fallback infla la "pérdida por inflación" reportada un 48 %.** Para un usuario con AR$ 10.000.000 en pesos: la card diría "perdiste AR$ 3.750.000" cuando lo real son AR$ 2.527.000.

Peor: `severity` se decide con umbrales duros sobre ese número (`:1327`, `if loss_usd >= 500 or inflation_cum_pct >= 100`). El 60 hardcodeado **también decide si la card se muestra en rojo** y si entra al ranking de "sesgo dominante" del packet de dashboard (`ai/builders/dashboard.py:222-232`), que es lo que la IA narra.

El comentario lo llama "estimación conservadora", pero **60 % anual no es conservador: es 1,77× la inflación real de hoy.** Fue conservador cuando se escribió (con inflación de 2024 al 117 % lo era, y por mucho), y quedó fijo mientras el régimen cambiaba. Es la definición de un número mágico que envejece mal.

En la misma función, `tc_blue: float = 1415.0` (`:1277`) es otro valor hardcodeado en la firma. Los callers sí lo pasan (verificado en `behavioral.py:1854`), así que hoy no muerde, pero es la misma clase de dato.

---

### 🟠 #8 — Se le cobra al usuario 12 meses de inflación sobre el saldo de hoy

**ESTRUCTURAL.**

```python
# backend/behavioral.py:1293-1298
for p in positions:
    if not p.get("is_cash"): continue
    if _native_ccy(p) == "ARS":
        cash_ars_pesos += p.get("invested") or 0
...
# :1324
loss_pesos = cash_ars_pesos * (inflation_cum_pct / (100 + inflation_cum_pct))
```

`positions` es la foto de **hoy**. La función no mira ni una sola fecha, ni un solo movimiento: asume que el saldo actual estuvo quieto los 12 meses. Un usuario que depositó pesos ayer recibe la frase completa: *"Tu cash en pesos perdió ~US$ X de poder de compra en los últimos 12 meses"*.

El resto del módulo `behavioral.py` sí tiene acceso a `ops` con fechas — `detect_inflation_loss` es la única detección que recibe sólo `positions`. La pérdida honesta requiere integrar el saldo en el tiempo: `Σ saldo_t × inflación_t`.

**Causa raíz:** la métrica se diseñó como "cuánto perdés por tener este saldo un año" y se comunica como "cuánto perdiste". Son dos afirmaciones distintas y sólo una necesita historial.

---

### 🟠 #9 — En mobile los bonos CER van sin ajuste y sin aviso

**ESTRUCTURAL.** Comparación de props del mismo componente:

```jsx
// frontend/src/pages/Positions.jsx:2794-2803 (desktop)
<RentaFijaSections positions={positions} … 
  tcMep={tcMepStrict} cerSeries={cerSeries} cerStale={cerStale} … />

// frontend/src/pages/PositionsMobile.jsx:1355-1361 (mobile)
<RentaFijaSections positions={enriched}
  valuePos={…} brokers={brokers} displayCurrency={currency}
  tcValuacion={tcValuacion} onChanged={loadAll} />
```

Faltan `cerSeries`, `cerStale`, `tcMep`, `bondCashflowsByKey`, `pendingDatesByKey`, `openBondCashflow`, `isArsFor`, `priceFor`, `priceMeta`. Los defaults de la firma (`RentaFijaSections.jsx:64`: `tcMep = null, cerSeries = null, cerStale = false`) hacen que todo degrade en silencio.

Y `cerSeries = null` cae en una rama distinta de `cerSeries = {}`: `BondDetail.jsx:208` muestra **"Cargando coeficiente CER…"** para `null` y **"Serie CER no disponible"** para `{}`. En mobile el usuario ve un "Cargando…" que nunca termina — porque nadie disparó el fetch. Confirma P-260.

---

### 🟡 #10 — "Plazo fijo UVA" en el selector del gráfico no dibuja nada

**MEDIDO.** El frontend mapea el nombre de producto a la clave del backend:

```js
// frontend/src/pages/Insights.jsx:237-240
const BENCH_API_KEY = {
  sp500: 'sp500', tbill: 'shv', gold: 'gld',
  inflation: 'inflation_ar', merval: 'merval', plazo_fijo: 'plazo_fijo',
}
```

pero `_benchmarks_fetch_and_cache` (`main.py:5252-5265`) produce la clave **`uva`**, no `plazo_fijo`:

```
   claves reales: ['inflation_ar', 'sp500', 'dolar_blue', 'shv', 'gld', 'merval', 'uva', 'sp500_d', 'shv_d', 'gld_d', 'fetched_at']
   'plazo_fijo' in claves -> False
```

Y `performance.benchmark_recortado` con la serie vacía, ejecutado de verdad:

```
bench_key='plazo_fijo' con la serie que el backend NO tiene (bd.get('plazo_fijo') -> {}):
   []
```

`performance.py:20` y `:25` sí listan `"plazo_fijo"` en `BENCH_PORCENTUAL` y `BENCH_EN_ARS`, o sea que el backend está preparado para una serie que nadie produce. Del otro lado, el gate de disponibilidad del selector mira la clave equivocada:

```js
// Insights.jsx:1277
{ key: 'plazo_fijo', label: 'Plazo fijo UVA',  available: hasData(bench?.uva) && hasData(bench?.dolar_blue) },
```

⇒ la opción aparece **habilitada** (porque `bench.uva` sí llega) y al elegirla `perf.benchmark` vuelve `[]`, con lo cual `benchPts[i]` es `undefined` y `bench: null` en cada punto (`Insights.jsx:864-869`): la línea simplemente no se dibuja, sin error ni mensaje.

**Vecino, fuera de mi tema pero del mismo defecto:** `pesos_cash` está en `VALID_ARS_BENCH` (`:215`) y en las opciones (`:1279`) pero **no está en `BENCH_API_KEY`** → `const k = BENCH_API_KEY[selectedBench]; if (!k) return` (`Insights.jsx:340-341`) → el fetch ni se dispara y **queda dibujado el benchmark anterior bajo el rótulo nuevo**. Eso es peor que vacío: es una línea de Inflación AR rotulada "Pesos cash (blue)".

**Causa raíz:** dos diccionarios de claves de benchmark (uno en JS, uno implícito en Python) que nadie cruza. Un `assert` de que todo valor de `BENCH_API_KEY` existe en la respuesta de `/api/benchmarks` habría cazado los dos.

---

### 🟡 #11 — El mes en curso entra al benchmark UVA como si estuviera cerrado

**MEDIDO.** `_fetch_uva_monthly` (`main.py:5474-5505`) mapea `fecha[:7] → valor` dejando ganar el último. Para meses cerrados eso es el cierre; para el mes vivo es **el valor de hoy**:

```
meses 127 ultimos [('2026-04', 1912.36), ('2026-05', 1969.47), ('2026-06', 2016.85), ('2026-07', 2057.99), ('2026-08', 2096.27), ('2026-09', 2106.13)]
```

Variación mes a mes de esa serie contra el IPC del mismo mes:

```
  2026-07  uva_mm= 2.04%  ipc= 2.10%  dif=-0.06 pp
  2026-08  uva_mm= 1.86%  ipc=  n/d
  2026-09  uva_mm= 0.47%  ipc=  n/d      ← 7 días de ajuste presentados como un mes
```

`simulatePlazoFijoUva` (`benchmarkSim.js:320`) capitaliza con `UVA_t/UVA_{t-1}`, así que el último mes del benchmark siempre está subvaluado en proporción a los días que faltan. La card "¿Le ganás a las alternativas? → Plazo fijo UVA" muestra al usuario ganándole al PF por un margen que incluye ese sobrante.

**Bonus verificado en la misma tabla:** el docstring de `_fetch_uva_monthly` (`main.py:5478-5479`) afirma que *"el ratio UVA_t / UVA_{t−1} es el factor de capitalización del mes (= inflación del mes)"*. **No es exacto**: el CER/UVA se construye con un rezago estructural de ~45 días respecto del IPC. Medido sobre 12 meses cerrados, la diferencia va de **−0,42 pp a +0,89 pp por mes** — chica, pero acumula y en meses de aceleración/desaceleración cambia de signo. El docstring debería decir "la inflación de ~mes y medio atrás", no "la inflación del mes".

---

### 🟡 #12 — Varas anuales contra un retorno real acumulado

**DEDUCIDO.**

```js
// frontend/src/utils/profileMatch.js:613-618
export const RETURN_EXPECTATION_META = {
  preserve:       { label: 'preservar capital',       floorReal: 0 },
  beat_inflation: { label: 'ganarle a la inflación',  floorReal: 3 },
  grow:           { label: 'crecer fuerte',           floorReal: 10 },
  aggressive:     { label: 'maximizar el retorno',    floorReal: 18 },
}
...
// :670-671
const gap = realReturnPct - meta.floorReal
const comparison = gap >= 2 ? 'above' : gap >= -2 ? 'in_line' : 'below'
```

`realReturnPct` llega desde `Insights.jsx:2280-2286` como `((1 + ret/100)/(1 + infl/100) − 1) * 100`, donde `ret` es el TWR **acumulado** de la ventana y `infl` la inflación **acumulada** de `monthsCounted` meses. No hay anualización en ninguno de los dos lados. Los pisos 0/3/10/18 sólo tienen sentido leídos como % anual (18 % acumulado en toda la historia no es "maximizar el retorno").

**Supuestos del cálculo:** que los pisos son anuales (lo sugieren fuertemente sus valores) y que `monthsCounted` ≠ 12 en la mayoría de los casos. Consecuencia: un usuario con 3 meses medidos y +2 % real queda `below` de un piso de 3 (cuando anualizado sería ~8,2 %); uno con 24 meses y +20 % real queda `above` de 18 (cuando anualizado es ~9,5 %). **El veredicto depende de cuánto tiempo lleva el usuario en la app, no de cómo le fue.**

El propio código pone un guard de plausibilidad `if (realReturnPct < -40 || realReturnPct > 150)` (`:658`) que ayuda a que el disparate no se vea en los extremos, pero no corrige el sesgo en el rango normal.

---

### 🟡 #13 y #14 — Cobertura del `vs_inflación` de Reportes

**ESTRUCTURAL, los dos.**

**#13 — sin gate de exposición ARS.** `builder.py:1647` publica `vs_inflation` para cualquier usuario. El gate correcto existe… en el frontend, y en código muerto:

```js
// frontend/src/hooks/useMonthlyData.js:288-297
if (selectedBroker === 'global') {
  showInflation = context.brokers.some(b => b.currency === 'ARS')
} else {
  showInflation = bObj?.currency === 'ARS'
}
```

Ese `showInflation` gobierna `vsInflation` en el hook, y el hook no lo usa nadie (#15). O sea: **la regla de negocio correcta está escrita, probada (`useMonthlyData.test.js:599`) y desconectada**, mientras el camino vivo (backend → `MonthCard`) no la tiene. Es P-246.

**#14 — sólo el mes.** `benchmark_return_for_period` (`builder.py:749-777`) empieza con:

```python
if period_type != "month":
    return None  # Phase 1: no soportamos benchmark sub-mensual
```

`parse_period_bounds` acepta `day`, `week`, `month`, `year` (`builder.py:33-66`). El comentario justifica bien el corte para día y semana (no se puede pro-ratear un IPC mensual sin data diaria), pero **el año se corta por el mismo `return None`** aunque componer 12 meses de IPC es trivial y la app ya lo hace en cuatro lugares. Resultado: el reporte anual —el que un argentino más quiere ver contra la inflación— no tiene la comparación.

---

### ⚪ #15 a #21 — El resto

**#15 · Código muerto + un comentario que miente.** Tres cálculos de inflación no llegan a ninguna pantalla (tabla C del mapa). El peor detalle es el comentario de `Insights.jsx:2315-2318`:

> `// inflationCum global (sobre globalMonthly) se usa en otros lugares de la UI,`

Es falso: `grep -n 'inflationCum\b' frontend/src/pages/Insights.jsx` da 5 hits y **todos** son la definición (`:2173`), tres comentarios y el paso de `inflationCumArsWindow` (no de `inflationCum`) al motor de diagnósticos. Un comentario que afirma un consumidor inexistente es peor que ningún comentario: el próximo que quiera borrar el cálculo no va a hacerlo.

**#16 · UVA/A3500 sin fetcher.** `main.py:5646` valida `index_name in ("CER","UVA","A3500")` pero `main.py:5600` es `fetcher_map = {"CER": _fetch_cer_series}`. Para UVA y A3500, `_ensure_index_cached` hace `return` sin setear `_indices_fetched[index_name]`, y `stale = (time.time() - 0) > TTL+3600` es **siempre `True`**. Confirma P-051. Irónico dado #1: la serie UVA que este endpoint no sirve es la única de las tres que sí está viva en la fuente.

**#17 · El IPC del mes base se excluye.** `benchmark_recortado` (`performance.py:107-116`) hace `if ym < base_ym: continue` / `if ym > base_ym: idx *= …`, o sea que el IPC del primer mes no entra. Es **correcto** si la curva del usuario está anclada a 1,0 al cierre del primer mes. Pero la curva es diaria y puede arrancar cualquier día: si arranca el 15 de enero, el usuario acumula medio enero de retorno y cero de inflación. Con los ~2,5 % mensuales de hoy son hasta ~1,2 pp de sesgo pro-usuario por comparación; con la inflación de 2024 eran ~3,3 pp.

**#18 · Los tests no atraviesan la fuente.** `backend/tests/test_bond_indices.py` declara en su cabecera *"NO hace fetch real al BCRA / argentinadatos — mockea el HTTP"*, y en efecto todo pasa por `patch.object(main, '_fetch_cer_series', …)` (`:161`, `:176`, `:198`) o por sembrar la tabla a mano (`_seed_cer`, `:41`). Hay incluso un test llamado *"fuente vacía"* (`:161-162`) que verifica que la app degrade bien con `{}` — o sea que **el escenario exacto de producción está testeado y pasa en verde**, porque el test valida la degradación y nadie valida que la fuente exista. Un canario que pegue la URL real (aunque sea en un job aparte, fuera del CI de PR) es lo único que cazaba #1.

**#19 · Reportes bypassea el caché de benchmarks.** `main.py:33096-33099` y `:33150-33153`:

```python
bench_data = {
    "inflation_ar": _fetch_inflation_ar(),
    "sp500": _fetch_sp500_monthly(),
}
```

Dos HTTP externos sincrónicos por request (timeout 8 s y `yfinance period="max"`), con `_bench_cache` disponible a 30.000 líneas de distancia y sin usar. Confirma el mapa. En este tema importa además porque significa que **Reportes y Insights pueden ver dos fotos distintas del IPC** si la fuente cambia entre dos requests.

**#20 · Dos dólares para el mismo peso.** `detect_inflation_loss` divide por `tc_blue` (`behavioral.py:1325`) mientras `_position_value_usd` (`:412`, `:446`) usa `rate_holdings` (MEP) para holdings. Para *cash* la elección del blue es defendible (el comentario de `:406-407` la justifica: *"tc_blue: para CASH en pesos (el dólar al que liquidarías efectivo)"*), así que lo dejo en ⚪. Confirma el mapa, línea 14470, y aclaro que **no es un bug de unidad**: verifiqué que `invested` de una posición de cash ARS está en pesos nativos (`_position_value_usd:427`, `invested_native`), con lo cual `cash_ars_pesos / tc_blue` es dimensionalmente correcto.

**#21 · `pp` rotulado como `%`.** `MonthCard.jsx:233`:

```jsx
<Cell label="vs Inflación AR" value={`${m.vs_inflation_pct >= 0 ? '+' : ''}${m.vs_inflation_pct.toFixed(1)}%`} accent />
```

`vs_inflation_pct` es el **exceso en puntos porcentuales** — el schema lo dice explícitamente (`reporting/schema.py:75-81`: *"estos dos son el EXCESO en puntos porcentuales"*, con el historial del AUDIT D-2 que ya arregló una versión peor de esto). Mostrarlo con `%` invita exactamente a la resta que `ArAlternativesVerdict.jsx:62` se toma el trabajo de prohibir en su pantalla hermana (*"Los tres porcentajes no se restan entre sí"*). Mismo dato, dos pantallas, criterios opuestos.

---

## Parches detectados

| parche | dónde | qué síntoma tapa | cuál es la causa real | dónde más sigue rompiendo |
|---|---|---|---|---|
| `inflation_cum_pct = 60.0` | `backend/behavioral.py:1313` | que la card quede vacía si argentinadatos falla | no hay contrato de "no hay dato" en este módulo: todas las demás detecciones tienen `_not_enough_data()` (`:1285`) y ésta no lo usa para el caso de benchmark ausente | cualquier otro consumidor que caiga a un default numérico en vez de a "no sé": el `tc_blue = 1415.0` de la misma firma (`:1277`) es el mismo patrón |
| `tc_blue: float = 1415.0` en la firma | `backend/behavioral.py:1277` | un caller que se olvide de pasar el TC | el TC debería venir siempre de `currency_context`, nunca de un default | hoy los callers lo pasan (`:1854`), así que está latente |
| `if (realReturnPct < -40 \|\| realReturnPct > 150) return { status: 'no_data' }` | `frontend/src/utils/profileMatch.js:658` | el "retorno fantasma" de la cadena TWR en pesos | el comentario lo admite textualmente: *"casi siempre viene del 'retorno fantasma' de la cadena TWR en pesos (usa cost-basis en vez de mark-to-market…). Ver backlog TWR/C1"* — la causa está diagnosticada y sin arreglar | es el mismo problema que la tanda 1A documentó en la curva en pesos de Insights. Cada consumidor del retorno-ARS necesita su propio clamp porque la fuente no es confiable: `Insights.jsx:1013` (`Math.max(rLiveArs, -0.99)`) es otro |
| `if period_type != "month": return None` | `backend/reporting/builder.py:760` | que día/semana publiquen un benchmark pro-rateado inventado | correcto para día y semana; **incorrecto para año**, que se lleva puesto de arrastre. El corte se escribió por resolución del dato y se aplica por tipo de período | el reporte anual |
| `except Exception: pass` alrededor de todo el bloque de benchmarks | `ai/builders/insights.py:612`, `insights_benchmarks.py:143`, `dashboard.py:199` | que un packet reviente por un benchmark | los tres dejan `inflation_pct = None` y el packet sale sin la comparación, sin registrar por qué | no es grave (degradación segura), pero significa que **si la serie IPC muriera como murió la de CER, nadie se entera**: mismo modo de falla silenciosa que #1 |

**Lo que NO es parche, y conviene dejar dicho para que nadie lo "arregle":**

- **`lookupCer` proyectando CER plano hacia el futuro** (`bondSchedule.js:80-84`). Es una decisión deliberada, comentada, y **correcta**: proyectar el coeficiente plano hace que la TIR resultante sea la TIR *real* (sobre CER), que es exactamente la convención con la que se cotizan estos bonos. El rótulo de `BondDetail.jsx:275` lo dice bien. El bug de #2 no es esto: es que el rótulo se pone igual cuando el ajuste **no** se aplicó.
- **El arrastre plano del último IPC** en `benchmark_recortado` (`performance.py:145-152`). Justificado por escrito. El problema es de comunicación (#6), no de política.
- **El gate de moneda de `diagnostics.js:209` y `:225`** (`if (currency !== 'ARS') return null`). Es la implementación correcta. Debería ser la referencia para los otros 6 sitios, no la excepción.

---

## Citas del mapa incorrectas

**Ninguna.** Este concepto estaba marcado como no mapeado, pero el mapa igual lo toca de refilón en 7 lugares. Verifiqué los 7 contra el código y **todos son correctos**, línea incluida:

| línea del mapa | afirmación | verificado |
|---|---|---|
| `4088` | `_fetch_inflation_ar` en `backend/main.py:5276` | ✅ exacto |
| `4423` | `_fetch_cer_series` en `backend/main.py:5572` | ✅ exacto |
| `4152` / `27291` | UVA y A3500 en la allowlist sin fetcher → serie vacía y `stale:true` para siempre | ✅ exacto (`main.py:5600`, `:5646`, `:5679`) |
| `4154` | `stale` mide frescura del *intento de fetch*, no del dato; con la fuente caída cada request reintenta 10 s | ✅ exacto — **y hoy la fuente está caída, así que esto ya no es hipotético** |
| `10039` | `benchmark_recortado` en `performance.py:88-154`, `BENCH_PORCENTUAL` en `:20` | ✅ exacto |
| `14470` | `detect_inflation_loss` usa `invested` crudo mientras el módulo usa `_position_value_usd`; dos dólares distintos | ✅ exacto. **Matizo**: no es un bug de unidad — `invested` de cash ARS está en pesos nativos y dividir por `tc_blue` es dimensionalmente correcto. Lo que el mapa señala bien es la inconsistencia de riel (blue vs MEP), que para cash es defendible |
| `19782` / `23454` | `computeInflationCumulative` en `benchmarkSim.js:193` | ✅ exacto |
| `27111` | `/api/reports/timeline` y `/period` llaman `_fetch_inflation_ar` sin caché en cada request | ✅ exacto (`main.py:33096`, `:33150`) |

**Lo que el mapa NO dice y es lo más importante del tema:** que la URL de CER devuelve 404. El mapa la documenta como fuente activa (`4148`: *"Servicios externos: `https://api.argentinadatos.com/v1/finanzas/indices/cer`, timeout 10s"*) sin haberla probado. No es un error de cita — es el límite de un mapeo estático.

---

## URGENTE

**Dos cosas de este informe afirman algo falso en pantalla y una tercera puede ensuciar datos del usuario. No las arreglé (regla de la auditoría); las dejo acá porque no aguantan a la próxima release.**

### U1 · La pantalla de un bono CER dice "TIR real (sobre CER) — es lo que ganás POR ENCIMA de la inflación" sobre un número calculado sin ajuste CER

Hallazgos #1 + #2. La fuente devuelve 404 **hoy** (medido), el factor de ajuste real es 7,72×–37,44× (medido), y el rótulo se pone igual porque depende de `meta.type === 'cer'` en vez de depender de si el ajuste se aplicó. La misma tarjeta, doce líneas más arriba, ya dice "Serie CER no disponible — flujos en nominal sin ajuste".

El arreglo mínimo que no toca la fuente de datos es de **una condición**: hacer que el rótulo de `BondDetail.jsx:274` use la misma condición que el cálculo (`Object.keys(cerSeries || {}).length > 0`), y caer a "TIR nominal — sin ajuste CER" cuando no. Eso convierte una mentira en un dato honesto mientras se resuelve la fuente.

### U2 · El monto pre-llenado del cupón de un bono CER puede entrar a `operations` hasta 37 veces más chico de lo que fue

Hallazgo #3. `BondCashflowModal.jsx:71` pre-llena el formulario de registro de cobro con `nextPaymentForPosition(...)`, que **no puede** recibir la serie CER (la firma no lo acepta). El inbox de cobranzas (`pendingCashflows.js:113`) propone pagos ya vencidos, para los cuales el coeficiente es conocido y no habría que proyectar nada.

Esto no es un número en pantalla: es un número que el usuario confirma y que después vive en `operations`, en la P&L y en los reportes. Dado el antecedente de "cupones con fecha futura" (25 cupones AL35 → US$3,9M fantasma), un pre-llenado sistemáticamente equivocado en un factor de 7 a 37 en el mismo formulario merece revisarse antes que el resto.

### U3 · La IA tiene prohibido recalcular y está obligada a citar un número que mezcla monedas

Hallazgo #4 + `backend/ai/prompts.py:1069` (*"PERFORMANCE SOLO desde `verdicts` … NUNCA con twr_pct_low_confidence ni inventando un %"*) y `:1196` (*"vs Inflación AR — el mínimo aceptable en Argentina es ganarle a la inflación. Si user < inflation, hay pérdida real"*).

El `verdicts.vs_inflation` que el prompt manda citar sale de `insights_benchmarks.py:151`, que resta una inflación en pesos a un retorno en dólares. El propio producto ya escribió la regla correcta en otro prompt del mismo archivo de origen (`main.py:23177`: *"NUNCA compares el retorno USD directo contra la inflación en pesos"*). Hoy el modelo obedece la instrucción equivocada porque es la que viaja con el dato.

El corte de menor riesgo, mientras se decide entre gatear o convertir (pregunta #2 al founder), es **no publicar `vs_inflation` en los packets cuando `moneda != 'ars'`**: la IA ya sabe qué hacer con un `null` (*"Cualquier campo null = no hay dato: decílo, no lo inventes"*, `main.py:23178`).

---

## BLOQUE-RESUMEN

| tema | # | hallazgo | evidencia | severidad | dónde muerde | causa raíz |
|---|---|---|---|---|---|---|
| 4. Inflación/UVA/CER | 1 | La fuente de CER (`api.argentinadatos.com/v1/finanzas/indices/cer`) devuelve **404**: los bonos CER calculan con factor 1,00 en vez de 7,72×–37,44× | MEDIDO | 🔴 | cronograma, próximo pago, TIR y pre-llenado de cupón de TX26/TX28/T2X5/TZX26/27/28 | dependencia de un tercero sin canario; el único camino de error es `return {}` silencioso |
| 4. Inflación/UVA/CER | 2 | La TIR se rotula "TIR real (sobre CER) — lo que ganás POR ENCIMA de la inflación" aunque el ajuste no se haya aplicado | ESTRUCTURAL | 🔴 | detalle del bono (`BondDetail.jsx:274`) | el rótulo mira `meta.type`, el cálculo mira `cerOpts`: dos condiciones para el mismo hecho |
| 4. Inflación/UVA/CER | 3 | El "próximo pago" y el monto pre-llenado del cupón nunca llevan ajuste CER (6 de 8 call sites sin `cerSeries`; `nextPaymentForPosition` ni acepta el parámetro) | ESTRUCTURAL | 🔴 | inbox de cobranzas, Novedades, filas de Renta Fija, modal de registro → `operations` → P&L | el ajuste se agregó como `options` opcional en vez de resolverse dentro del motor |
| 4. Inflación/UVA/CER | 4 | Los 6 `vs_inflación` del backend restan **inflación en pesos a un retorno en dólares** | ESTRUCTURAL | 🔴 | Reportes, Wrapped y los 4 packets que alimentan a la IA | la moneda no viaja con el número; nadie valida unidad antes de restar |
| 4. Inflación/UVA/CER | 5 | Los mismos 6 usan `r − π` en vez de `(1+r)/(1+π)−1`; error medido 3–17 pp hoy, 75–143 pp con la inflación de 2023 | MEDIDO | 🟠 | idem #4 | la fórmula correcta existe y vive en una sola pantalla (`diagnostics.js:207`) |
| 4. Inflación/UVA/CER | 6 | Los ~2 meses que el INDEC no publicó se arrastran planos (~4,2 pp hoy, ~13,8 pp con inflación 2024), sesgo pro-usuario, declarado sólo en el packet del chat | MEDIDO | 🟠 | gráfico de Insights, celda de Reportes, verdicts de la IA | política de arrastre correcta, comunicación inexistente |
| 4. Inflación/UVA/CER | 7 | `detect_inflation_loss` cae a **60 % anual hardcodeado**; el real medido es 33,82 % (1,77×) e infla la pérdida reportada un 48 % | MEDIDO | 🟠 | card "Pérdida por inflación" en Comportamiento, Objetivos, Wrapped y packet IA | número mágico en vez de `_not_enough_data()` |
| 4. Inflación/UVA/CER | 8 | `detect_inflation_loss` aplica 12 meses de inflación al saldo en pesos **de hoy**, sin mirar una sola fecha | ESTRUCTURAL | 🟠 | misma card | la métrica se diseñó como "por tener este saldo un año" y se comunica como "perdiste" |
| 4. Inflación/UVA/CER | 9 | En mobile los bonos CER van sin ajuste y con un "Cargando coeficiente CER…" que nunca termina | ESTRUCTURAL | 🟠 | `PositionsMobile.jsx:1355` | 3 props (`cerSeries`/`cerStale`/`tcMep`) no se pasan; los defaults degradan en silencio |
| 4. Inflación/UVA/CER | 10 | La opción "Plazo fijo UVA" del gráfico queda habilitada y no dibuja nada (el front pide `plazo_fijo`, el back produce `uva`) | MEDIDO | 🟡 | gráfico de Insights en Pesos | dos diccionarios de claves de benchmark que nadie cruza |
| 4. Inflación/UVA/CER | 11 | `_fetch_uva_monthly` toma el último día disponible del mes en curso como cierre (medido: 2026-09 = +0,47 % con 7 días) | MEDIDO | 🟡 | benchmark "Plazo fijo UVA" | el dict-overwrite no distingue mes cerrado de mes vivo |
| 4. Inflación/UVA/CER | 12 | `floorReal` (0/3/10/18) compara varas anuales contra un retorno real acumulado sin anualizar: el veredicto depende de cuánto tiempo lleva el usuario en la app | DEDUCIDO | 🟡 | card "Expectativa de retorno" | falta normalización temporal |
| 4. Inflación/UVA/CER | 13 | `vs_inflation` de Reportes no se gatea por exposición ARS; el gate correcto existe en JS pero en código muerto | ESTRUCTURAL | 🟡 | reportes de carteras 100 % USA | la regla se escribió del lado que se apagó |
| 4. Inflación/UVA/CER | 14 | Sólo el reporte mensual tiene `vs_inflación`; el **anual** cae por el mismo `return None` que día y semana | ESTRUCTURAL | 🟡 | reporte anual | el corte se pensó por resolución del dato y se aplica por tipo de período |
| 4. Inflación/UVA/CER | 15 | Tres cálculos de inflación no llegan a ninguna pantalla, y un comentario afirma un consumidor inexistente (`Insights.jsx:2315`) | ESTRUCTURAL | ⚪ | — | restos de iteraciones; el comentario impide que se limpien |
| 4. Inflación/UVA/CER | 16 | `UVA` y `A3500` pasan la allowlist de `/api/bond-indices` sin fetcher → serie vacía y `stale:true` permanente (P-051) | ESTRUCTURAL | ⚪ | — | validación y capacidad declaradas en lugares distintos |
| 4. Inflación/UVA/CER | 17 | `benchmark_recortado` excluye el IPC del mes base: correcto para curva anclada a fin de mes, sesgo pro-usuario de hasta ~1,2 pp si el usuario arranca a mitad de mes | DEDUCIDO | ⚪ | gráfico de Insights | IPC mensual contra curva diaria |
| 4. Inflación/UVA/CER | 18 | La suite mockea `_fetch_cer_series` y hasta testea el caso "fuente vacía": el 404 de #1 pasa en verde | ESTRUCTURAL | ⚪ | CI | no hay canario contra las URLs reales |
| 4. Inflación/UVA/CER | 19 | `/api/reports/*` llama `_fetch_inflation_ar()` en cada request ignorando `_bench_cache` (confirma el mapa) | ESTRUCTURAL | ⚪ | latencia de Reportes; dos fotos distintas del IPC entre pantallas | dos caminos a la misma fuente, uno cacheado y otro no |
| 4. Inflación/UVA/CER | 20 | `detect_inflation_loss` convierte con blue y el resto del módulo con MEP (confirma el mapa; **no** es bug de unidad) | ESTRUCTURAL | ⚪ | monto USD de la card | riel de FX elegido por función, no por concepto |
| 4. Inflación/UVA/CER | 21 | `MonthCard` rotula con `%` un valor que está en puntos porcentuales, invitando a la resta que la pantalla hermana prohíbe | ESTRUCTURAL | ⚪ | celda "vs Inflación AR" | — |
