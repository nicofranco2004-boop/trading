# AUDIT — Rendimiento vs benchmark (certero · estimado · benchmarks) — 2026-09-01

> ✅ Ronda implementada el mismo día (puntos 1, 2 y 3 del §8): ver `REPORTE_benchmark_diario_2026-09-01.md`. Sin commitear.

Auditor: chat AUDITOR (Fable). Código auditado: **`origin/main` = `dde8ee55`** (lo que sirve
rendi.finance hoy), extraído con `git archive` a un scratchpad — no se tocó ningún árbol.
Datos: copia de producción `~/Downloads/trading-2026-08-16.db` copiada al scratchpad, con las
columnas `mtm_coverage/base/apto` agregadas y **estampada con el `twr.estampar_base` de
`origin/main`** (40.717 filas · 822 usuarios: `costo/apto=0` 13.265 · `mercado/apto=0` 249 ·
`mercado/apto=1` 27.203). Todo lo de abajo está **ejecutado, no leído**. Cada número tiene su
instrumento en §1.

---

## 0 · RESUMEN — por qué se ve raro

1. **El benchmark del gráfico no lo calcula el backend: lo calcula `Insights.jsx` con cierres
   MENSUALES del S&P y lo ancla en el CIERRE DE FIN DE MES del primer mes visible.** La curva del
   usuario es diaria. Resultado en el modo por defecto (Certero · 1A): la línea del S&P tiene
   **2 valores distintos (mediana) sobre 44 filas**; en **64 usuarios es una recta en 0 %**; en
   **1M es un solo escalón para los 484**. Contra el S&P real entre las mismas fechas, el número
   que la app muestra difiere **>1 pp en 220 de 484 usuarios, >2 pp en 152, y con el SIGNO
   dado vuelta en 21** ("le ganás al S&P" / "te gana"). §2.
2. **El ancla del benchmark depende de `monthly_entries`, no de la curva.** 348 de 673 usuarios
   tienen huecos en su cadena mensual, y el ancla cae en "el último mes cargado antes del hueco":
   uid 878 y 437 ven **"S&P +35,1 %"** sobre una ventana donde el S&P hizo **+3,8 % / +5,9 %**.
   Al revés, 15 usuarios en Estimado ven el S&P arrancar en 0 % diez meses DESPUÉS de su propia
   línea (173/203: S&P +3,8 % dibujado, +20,5 % real). §2.3.
3. **`perf.benchmark` —el "benchmark recortado al mismo rango" que el endpoint calcula y que el
   docstring de `/api/insights/performance` vende como el arreglo— NO LO LEE NADIE.** Cero
   referencias en el frontend. Y aunque lo leyera, tiene el mismo ancla de fin de mes. §2.4.
4. **El KPI "Acumulado · vs S&P · mismo período" en Certero no publica el TWR: publica el
   índice DIBUJADO**, que encadena las fotos intradía y no tiene el guard del cero absorbente.
   20 de 480 usuarios ven un número >5 pp distinto del que el backend publica (uid 745:
   **+642,9 %** en el KPI, **+6,6 %** en `perf.twr`; uid 865: **−100 %** vs −7,5 %), y **11
   usuarios ven un número donde el backend se niega** (uid 486: +217,8 % con la serie partida). §4.
5. **Certero publica números imposibles**: 46 de los 480 tienen UN salto diario ×>2 o ×<0,5 entre
   dos cierres del cron sin flujo; esos 46 son **exactamente** los 6 con más de +100 % (uid 282:
   +25.757 %) y los 31 con menos de −50 % (uid 513: −100 %). El clamp de plausibilidad existe
   sólo para las alertas del asesor (`main.py:35715`); Insights no lo tiene. §3.
6. **Estimado publica tres números distintos en la misma pantalla**: el chip dice el PRODUCTO de
   la cadena contable por la de mercado (uid 118: **+125.654 %**), el gráfico dibuja dos
   segmentos que arrancan cada uno en 0 %, y el KPI lee el último segmento (**+0,7 %**). 223 de
   637 difieren >5 pp entre chip y KPI. Además: **10 usuarios en −100 % exacto** (cero absorbente
   en la cadena contable, que el corte del denominador no protege), 45 con más de +300 %, y 8
   con solapamiento de fechas entre la parte contable y la de mercado. §5.
7. **En el backend local yfinance está muerto** (`tkr-tz.db` corrupto → `disk I/O error`) →
   `sp500/shv/gld/merval` vacíos → **no hay línea de benchmark y el botón "S&P 500" sale
   deshabilitado**. Si lo que estás mirando es localhost, ésa es la mitad de "lo raro". Prod:
   **no verificado** (necesita login). §6.
8. **Si mirás la cuenta demo local: el +318 % de Certero es la posición AAPL que pasó de 132 a
   3.703 unidades sin depósito** (la demo.db la modificó otro chat hoy a las 21:11). No es prod. §6.

---

## 1 · INSTRUMENTO — con qué se midió cada cosa

```
scratchpad = /private/tmp/claude-501/-Users-nicolaspussetto-Documents-trading/f2be2945-3c85-4448-b831-b108865c5f56/scratchpad
  main/            git archive origin/main (dde8ee55)
  work.db          copia de prod 2026-08-16 + columnas + twr.estampar_base()  (abierta mode=ro después)
  perf_all.json    performance.performance(conn, uid, {}, modo=…) para los 670 uid con snapshots>0, ambos modos
  monthly_all.json monthly_entries broker='global' por uid
  sp.json          ^SP500TR mensual + ^GSPC/SPY diario (yfinance 1.2.0, corrido hoy)
  port.mjs         PORT del pipeline benchSeriesUsd → resolucionChart → windowSeries →
                   cortarPorTramo → shadow S&P → rebase → partirMedidoYEstimado → KPI,
                   usando los módulos REALES insightsModel.js y benchmarkSim.js (vite-node) y
                   una transcripción literal de Insights.jsx:779-1665 y :2663-2685.
                   "hoy" = 2026-08-16 (la fecha de la copia); S&P mensual = último cierre ≤ fin de mes
                   (agosto = cierre del 14/08), para no comparar contra un cierre que la app no tenía.
  port_out.json    670 uid × {certero, estimado} × {1M, 3M, 1A, MAX}
```

⚠️ Trampas nuevas de esta sesión (además de las 17 del handoff):
- `sqlite3.connect('file:…?mode=ro')` sobre la copia falla con "unable to open database file":
  hace falta `&immutable=1` (la copia trae `-shm` de otro proceso).
- `git archive` no trae `node_modules`; los utils del frontend importan sin extensión → Node pelado
  falla; `npx vite-node` desde `frontend/` del repo principal resuelve.
- El rollover de `/api/monthly` avanza **36 meses POR LLAMADA**; simularlo con el cap da anclas
  falsas (me pasó: atribuí 3 usuarios a un bug que era mi simulación).
- `math.log(0)` con un índice en 0 (uid 513) mata el script de saltos: usar `max(x, 1e-9)`.

Baselines de la suite: **no se corrieron** (no hay cambios de código en esta ronda).

---

## 2 · EL BENCHMARK

### 2.1 Qué dibuja la app, de verdad

`Insights.jsx:1595-1665`: cada fila de la curva del usuario recibe `benchPct =
shadowPctByMonth.get(key.slice(0,7))`, donde `shadowPctByMonth` sale de
`buildShadowFromSim(simulateSp500(globalMonthly, bench.sp500))` (`:1402`, `benchmarkSim.js:67`):
`(price[mes] / price[primer mes de monthly_entries] − 1)`, con `bench.sp500 = {YYYY-MM: cierre}`
(`main.py:5145-5176`, `yf.history(period="5y", interval="1mo")`). Después se rebasea contra
`first.benchPct ?? 0` (`:1624`).

O sea, por construcción:
- **resolución mensual**: todos los días de un mes tienen el MISMO valor del S&P (el cierre del
  mes; para el mes en curso, el último cierre). La línea es una escalera que salta el día 1.
- **ancla = cierre de FIN del primer mes visible**, no del primer día visible. Lo que el S&P hizo
  entre el primer día medido y el fin de ese mes desaparece de la comparación.
- **cobertura = meses de `monthly_entries`**, no fechas de la curva.

### 2.2 Medido (port, Certero · 1A por defecto, 484 usuarios con benchmark)

| medición | valor |
|---|---|
| valores DISTINTOS del S&P en la ventana (mediana) sobre filas (mediana) | **2 sobre 44** |
| usuarios con ≤2 valores distintos | 274 |
| usuarios con el S&P **plano en 0 %** toda la ventana | **64** |
| tramo del primer mes que el ancla tira: mediana · p90 · máx | 0,74 pp · 1,98 pp · 3,95 pp |
| … usuarios con >1 pp tirado | 216 |
| \|bench APP − S&P real entre las mismas fechas\|: mediana · p90 · máx | **0,81 pp · 2,05 pp · 31,3 pp** |
| … >1 pp · >2 pp · >5 pp | **220 · 152 · 5** |
| … con **signo distinto** (la app dice que el S&P subió y bajó, o al revés) | **21** |

Certero · **1M**: **484 de 484** usuarios tienen ≤2 valores distintos (un solo escalón); 76 lo
ven plano; 26 con signo distinto. Estimado · 1A: 71 de 642 con >1 pp; 54 con >2 pp.

Contexto que hace que esto pese: **nadie tiene más de 3 meses medidos** (`apto=1` existe desde
2026-05-31: `select substr(date,1,7),count(*) … where apto=1`). Un desfasaje de hasta un mes en
el ancla, sobre una ventana de 6 semanas, no es ruido: es la comparación entera.

### 2.3 El ancla que cae en otro mes (huecos de `monthly_entries`)

```sql
-- 348 de 673 usuarios tienen meses faltantes ENTRE el primero y el último de broker='global'
-- (script en §1: meses = year*12+month; faltan = (max-min+1) - count distinct)
```

El rollover (`main.py:11174`) sólo camina hacia ADELANTE desde la última fila; los huecos internos
quedan. `simulateBenchmark` sólo emite meses que están en `globalMonthly`, y el fallback del
frontend toma "el último mes ≤ mk" (`Insights.jsx:1612-1616`):

| uid | monthly global | primera fila visible | S&P que muestra | S&P real | 
|---|---|---|---|---|
| 878 | 2024-02, 2026-07, 2026-08 | 2026-06-30 | **+35,1 %** | +3,8 % |
| 437 | 2024-01…2024-07, 2026-07, 2026-08 | 2026-06-26 | **+35,1 %** | +5,9 % |
| 132 (estimado) | — | 2025-08-31 | +35,1 % | +20,5 % |
| 173 / 203 (estimado) | 2026-06..2026-08 (snapshots desde 2023) | 2025-08-31 | +3,8 % (arranca en 0 % en Jun '26) | +20,5 % |
| 513 / 1117 | monthly empieza 2026-08 | 2026-06-25 / 07-23 | **0 % plano** | +5,8 % / +5,1 % |

Conteo (port): Certero 1A → ancla `ok` 479 · `anterior` 3 · `null` 11. Estimado 1A → 647 · 8 · 15.
Los `null` son `first.benchPct ?? 0` (`:1624`): el S&P se dibuja relativo a un 0 que no es su valor.

### 2.4 `perf.benchmark` no lo lee nadie

```bash
grep -rn "perf?.benchmark\|perf\.benchmark" main/frontend/src   # → 0 resultados
```

`performance.benchmark_recortado` (`performance.py:27-79`) existe, viaja en la respuesta, y el
docstring del endpoint (`main.py:11529`) dice «un punto por cada fecha de `curva`, indexado a 1.0
en la MISMA fecha». El frontend sigue usando su propio motor mensual. Y `benchmark_recortado`
también ancla en el cierre del mes (`base_val = v` para `ym <= base_ym`, `:65`): arreglarlo es
más que cablearlo.

### 2.5 El frontend no manda `valor_live`

`Insights.jsx:300`: `/insights/performance?bench=…&modo=…` sin `valor_live` → la curva termina en
la última foto del cron (ayer) y no hay fila "Hoy"; el S&P del último mes es el cierre de hoy.
Un día de desfasaje al final, sistemático. Menor, pero es otra punta que no coincide.

### 2.6 Un tercer motor: el packet de la IA

`ai/builders/insights_benchmarks.py:41-77` calcula el retorno del usuario desde `monthly_entries`
(cadena contable, meses con `ret < −0,95 o > 5` DESCARTADOS en silencio) y el S&P como
`(último cierre − primer cierre ≥ cutoff_ym) / primer cierre` (`:96-98`). Ni certero ni estimado:
el chat puede afirmar "le ganaste al S&P" con un número que ninguna de las dos posiciones del
toggle muestra. No medido más a fondo; lo anoto.

---

## 3 · CERTERO — el número que "está bien" publica imposibles

`perf_all.json`, modo certero, 480 usuarios publican `twr`:

```
twr > +100 %  :  6   → 282 (+25.757 %) · 453 (+4.722 %) · 441 (+2.097 %) · 864 (+1.864 %) · 821 (+367 %) · 1147 (+316 %)
twr < −50 %   : 31   → 513 · 756 · 720 · 571 · 446 … (todos ≈ −100 %)
```

**Los 37 tienen la misma anatomía**: UN leg diario entre dos cierres aptos con ratio ×>2 o ×<0,5 y
el aportado estampado sin moverse. Medido sobre los 480: **46 usuarios tienen un leg así, y el
conjunto de los 46 contiene a los 37** (`set(>100%) ⊆ saltos == True`, `set(<−50%) ⊆ saltos == True`).

```
uid 282   2026-06-30  US$4,6        →  2026-07-01  US$1.116,1      nd 3,4 → 3,4      ×240
uid 453   2026-06-30  US$536,1      →  2026-07-01  US$23.043,7     nd 536 → 536      ×43
uid 441   2026-06-30  US$97,9       →  2026-07-01  US$2.064,2      nd 98 → 98        ×21
uid 35    2026-06-30  US$1.583.500  →  2026-07-01  US$1.906,8      nd 2.290 → 2.290  ×0,001
uid 513   2026-06-25  US$16.229.949 →  2026-06-26  US$109,0        nd 0 → 0          → −100 % ABSORBENTE
```

De los 11 saltos hacia arriba, **6 son el PRIMER leg medido**: la primera foto del cron tiene la
cartera sin valuar (o sólo el cash) y la segunda la tiene entera. El aportado canónico no ve
ningún flujo porque la plata nunca entró como depósito en `monthly_entries` (uid 441: una sola
fila, 2026-06, capital 98). Es la familia "el depósito se publica como ganancia" del audit
anterior, en su versión "la posición aparece de la nada".

Y el lado negativo es el pico implausible del prompt del clamp (uid 513/756/54): la foto de
16 millones pasa todos los filtros (`source=cron`, `base=mercado`, `apto=1`) y el leg siguiente
toca el piso de `dietz` (`twr.py:569`) → **`idx = 0` y la curva queda en −100 % para siempre**.
El corte del denominador (`twr.py:1176-1181`) sólo dispara cuando el FLUJO desborda; acá el flujo
es 0 y lo que desborda es el valor.

Todo esto llega a la pantalla de Certero, al KPI y al packet de la IA sin ninguna cota de cordura:
el clamp de plausibilidad de la ronda anterior vive **sólo** en las alertas del asesor.

---

## 4 · EL KPI DE CERTERO NO ES EL TWR

`Insights.jsx:2682-2685`:
```js
const cumulativeReturnPct = _modoEstimado ? (_acum ? _acum.pct : null) : (lastRow[_kTotal] ?? null)
const benchmarkReturnPct  = lastRow[benchmarkKey] ?? null
```
`lastRow[_kTotal]` es el `total` de la curva rebaseado, y `total = (pt.index − 1)·100` donde
`pt.index` es **`idx_por_base`, el índice DIBUJADO** (`twr.py:1425`), que por diseño
«encadena TODO, incluida la intradía». El número publicado (`idx`, `twr`) salta lo no-apto; el KPI
no.

Medido (port, Certero · 1A, 480 con `twr`):

```
KPI == perf.twr (±0,05 pp) : 403
KPI ≠ perf.twr por >5 pp   :  20
KPI publica y twr es None  :  11
```

| uid | KPI (pantalla) | `perf.twr` (chip / IA) | qué pasó |
|---|---|---|---|
| 745 | **+642,9 %** | +6,6 % | 06-26 intradía US$3.329 → 06-27 intradía US$22.746: el dibujo encadena ×6,8; el twr arranca el 07-01 |
| 865 | **−100 %** | −7,5 % | 06-29 intradía nd 3.276 → 07-01 cron nd 13.975: flujo 2× el valor, `dietz` toca −1 en la cadena de DIBUJO → cero absorbente |
| 681 | −66,0 % | +1,0 % | intradía 06-26 → cron 07-07 ×0,34 |
| 268 | −15,1 % | −83,9 % | al revés: el dibujo esconde la caída publicada |
| 486 | **+217,8 %** | **None** (`serie_partida`) | la primera fila es del tramo 1, la última del tramo 2; el rebase los une |
| 1 | −64,8 % | None (`serie_partida`) | ídem |
| 3, 40, 48, 396, 650, 842 | 0,0 % | None (`una_sola_medicion`) | un punto → "0,0 %" |

85 usuarios de certero tienen puntos no-aptos en la curva; en 20 el índice dibujado del último
punto difiere >5 pp del publicado. **Y el sub del KPI dice "vs S&P: X % · mismo período"** con
el X de §2 — las dos mitades del KPI están mal, cada una por su lado.

En 1M: KPI ≠ twr en 124 de 478 — eso NO es bug (la ventana es de 30 días y el twr de toda la
medición), lo anoto para que nadie lo "arregle".

---

## 5 · ESTIMADO — tres números y ninguno se parece al otro

### 5.1 El producto vs los segmentos

`twr.py:1437` encadena `idx_est` por base y publica el PRODUCTO de las dos cadenas; el dibujo
(`idx_por_base`) reinicia en 1,0 en cada cambio de base; el KPI (`acumuladoDeVentana`) lee la
última corrida homogénea. Medido (port, Estimado · 1A, 637 con KPI):

```
KPI == perf.twr : 307        KPI ≠ perf.twr por >5 pp : 223        KPI "parcial" : 426 de 670
```

| uid | chip `perf.twr` | gráfico | KPI |
|---|---|---|---|
| 118 | **+125.654 %** | segmento contable +125.654 % · corte · segmento mercado +0,7 % | +0,7 % "desde el último corte" |
| 659 | +45.783 % | dos segmentos | +9,2 % |
| 814 | +3.814 % | dos segmentos | +11,7 % |
| demo local | +389,2 % (= 1,1686 × 4,1862 − 1) | +16,9 % · corte · +318,6 % | +318,6 % |

El chip dice "Recreado de tu contabilidad · sólo se mueve cuando vendés" sobre un número que en
362 usuarios incluye una cadena de MERCADO completa (`tramo publicado mixto`: 362 de 655).

### 5.2 La cadena contable llega sin ninguna cota

```
estimado twr > +100 % : 84       > +300 % : 45      (393: +493.614 % · 118: +125.654 % · 43: +110.456 %)
de los 45:  mayor salto en la parte CONTABLE 38 · en la de mercado 7
            sin ninguna fila 'global' en monthly_entries 3   → _aportado_por_punto cae a la estampa (=0): TODO el valor es retorno
            net_deposited estampado en 0 en toda la parte contable 6
usuarios publicados con un leg contable mes-a-mes ×>2 o ×<0,5 : 153
```

uid 118, 2023-05: la cadena `global` pasa de 3.228 a 10.583 con depósitos 0 y `pnl_realized`
+7.355 (la pata "Balanz · USD" pasa de −247 a 6.910). Ésa es la contabilidad importada tal cual; el
estimado la reproduce fielmente y la multiplica.

### 5.3 El cero absorbente, otra vez

```
estimado twr == −100 % exacto : 10   → 193 · 235 · 271 · 480 · 584 · 585 · 622 · 675 · 899 · 1148
usuarios con algún punto index == 0 : 21
```

uid 193: `2020-11-30 US$18,9 (nd 269,7) → 2020-12-31 US$52,2 (nd 596,7)`: flujo 327 contra 18,9 →
`dietz = −1,0` → `idx_est = 0` (`twr.py:1437`) y nada lo levanta. El corte por desborde del
denominador de `serie_medible` (`:1176-1181`) **sólo mira legs apto→apto**; la cadena contable y la
de dibujo no lo tienen. Es el mismo bug que la ronda 5 cerró para el certero, reabierto en las dos
cadenas nuevas.

### 5.4 Solapamiento

8 usuarios tienen, dentro del tramo publicado, filas contables FECHADAS DESPUÉS de la primera
medición a mercado (uid 1: contable hasta 2026-06-30, mercado desde 2026-05-31). El producto
cuenta junio dos veces: una como realizado contable, otra como movimiento de mercado. Chico en
número; conceptualmente es lo que `ventana_desde/hasta` afirma que no pasa.

---

## 6 · LOCAL — lo que ves en localhost no es prod

**yfinance muerto en el backend local (`:8000`, cwd `rendi-worktrees/reportes-guard/backend`,
`DB_PATH=…/6c0ea710…/scratchpad/demo.db`)**:

```
GET /api/benchmarks (tras refresh SWR, fetched_at 2026-09-02T00:12Z): sp500 0 · shv 0 · gld 0 · merval 0 · inflation_ar 1001 · dolar_blue 188
python3 -c yfinance ^SP500TR 5y 1mo (shell, caché default)      → 61 filas, OK
mismo fetch con yf.set_tz_cache_location('/private/tmp/yf-cache') en thread → OperationalError('disk I/O error') ×4
sqlite3 /private/tmp/yf-cache/tkr-tz.db 'pragma integrity_check'         → disk I/O error   (archivo de 4 KB recreado hoy 14:29)
```

Consecuencia visible: **sin línea de benchmark, botón "S&P 500" deshabilitado, `perf.benchmark = []`**.
Causa local (purga de `/private/tmp`, memoria `project_worktree_tmp_purge`). Prod usa el mismo
`/tmp/yf-cache` efímero pero se recrea en cada deploy; **no lo verifiqué** (§7).

**La demo (`demo.metricas@rendi.test`)**: Certero `twr = +318,6 %` (07-11 → 08-30, 45 legs),
Estimado +389,2 %, CAGR 467 %. La foto del 30/08 vale US$76.070 contra US$18.077 el 25/08, `source=cron`,
`holdings: AAPL 61.820`; en `demo.db` la posición AAPL tiene **3.703,21 unidades** donde la copia
del 30/08 17:56 tenía 132,26, con `net_deposited` fijo en 13.000. Lo cambió otra sesión hoy a las
21:11. Si el "muy raro" es en localhost, empezá por acá.

---

## 7 · 🔴 QUÉ NO VERIFIQUÉ

- **Prod**: ni `/api/benchmarks` ni la pantalla en rendi.finance (los dos piden login; no entro
  con credenciales). Chequeo de 30 segundos para vos: Análisis → Métricas → si "S&P 500" está en
  gris o la línea del benchmark no aparece, prod tiene el mismo yfinance vacío que local.
- **El gráfico con los ojos**: todo el pipeline del frontend lo medí con el port (§1), no en el
  browser (local no tiene S&P para dibujar). El port usa los módulos reales y transcribe
  `Insights.jsx` línea por línea, pero es una transcripción.
- **El S&P "real"** lo tomé de `^GSPC` diario (precio); la app usa `^SP500TR` (total return). La
  diferencia de dividendos en 6 semanas es ~0,1 pp: no cambia ningún conteo de §2, pero el
  "signo distinto" en 21 usuarios lo contaría de nuevo con TR antes de citarlo como cifra final.
- **Reportes (`reporting/builder.py`) y el packet de IA** no los medí; sólo anoté (§2.6) que son
  otro motor.
- **Modo ARS** (`benchSeriesArs`, 89 % de los usuarios): fuera del alcance de este audit; el toggle
  ahí está apagado y la línea sale de la cadena contable en pesos.
- **La suite** no se corrió (no hubo cambios).

---

## 8 · QUÉ HACER — en orden, con el criterio de salida

1. **Benchmark DIARIO, servido por el backend, anclado en la PRIMERA FECHA de la curva.** Bajar
   `^SP500TR`/`SHV`/`GLD` con `interval="1d"` (2 años alcanza: nadie tiene más de 3 meses medidos),
   guardar `{YYYY-MM-DD: close}`, y que `benchmark_recortado` devuelva un punto por fecha de la
   curva con el cierre de ESA fecha (o el anterior hábil). Que `Insights.jsx` lea `perf.benchmark`
   y borre `buildShadowFromSim`/`simulateSp500` del gráfico (las cards "Comparativa" pueden seguir
   con el mensual: comparan patrimonios, no trazan). Criterio: |bench APP − S&P real| < 0,1 pp en
   los 484 y **0 con signo distinto**; en 1M, tantos valores distintos como ruedas.
2. **El KPI lee el índice PUBLICADO, no el dibujado.** Que la curva traiga `index_publicado`
   (`idx`) además de `index`; el KPI rebasea entre dos puntos APTOS de la ventana y da "—" si la
   ventana cruza un corte o tiene <2 aptos. Criterio: 480/480 con `KPI == perf.twr` en 1A y 0
   KPI con `twr None`.
3. **Cota de plausibilidad EN LA CURVA** (decisión del dueño, ya tomada para el asesor): un leg
   con ratio fuera de [1/5, 5] y |flujo| < 10 % del valor → corta el tramo como el desborde del
   denominador, marca `motivo='medicion_dudosa'` y manda el uid a la cola de
   `/api/admin/diagnose-reportes-basis`. Aplicarlo a las TRES cadenas (`idx`, `idx_por_base`,
   `idx_est`). Criterio: los 46 de §3 dejan de publicar; los otros 434 quedan bit-idénticos.
4. **Estimado: un solo número por pantalla.** O el chip y la IA publican lo que el gráfico dibuja
   (la última corrida homogénea, con "desde …"), o el gráfico dibuja el producto. Mi recomendación:
   lo primero; el producto de dos reglas no es un retorno de nada. Y el corte por `dietz ≤ −1`
   también en `idx_est`/`idx_por_base` (§5.3).
5. **Healthcheck del caché de benchmarks**: si `sp500` viene `{}` tras el fetch, loguear en
   ERROR y reintentar con un `tz_cache` nuevo; y `valor_live` en la llamada del frontend.

El prompt de la ronda que sigue, con el 1 y el 2 (y el 3 si el dueño lo aprueba):
**`PROMPT_benchmark_diario.md`**.
