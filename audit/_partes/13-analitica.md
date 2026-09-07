## Motores de análisis: reporting, behavioral, wrapped, objetivos, home

Alcance: `backend/reporting/` (builder + detectors + timeline + schema), `backend/behavioral.py`,
`backend/wrapped.py`, `backend/goals_diagnostic.py`, `backend/home/briefing.py`, `backend/home/market.py`.
Se compara además contra `backend/twr.py` y `backend/performance.py` (los dos motores "canónicos" de retorno).

Convención: `[V]` = verificado leyendo el código (con cita), `[I]` = inferencia mía (digo de qué me agarré).

---

### 0. Mapa de un vistazo

| Motor | Archivo | Produce | Endpoint | Pantalla |
|---|---|---|---|---|
| Reporte de período | `backend/reporting/builder.py` (2141 L) | `PeriodReport` (métricas + headline + narrativa + drivers + movers + highlights) | `GET /api/reports/timeline`, `GET /api/reports/period/{type}/{key}` | `/analisis?tab=reportes` |
| Detectores narrativos | `backend/reporting/detectors.py` (457 L) | `Insight[]` (chips con evidencia) | los dos de arriba | idem |
| Composición cronológica | `backend/reporting/timeline.py` (253 L) | últimos N meses con semanas anidadas | `GET /api/reports/timeline` | idem |
| Sesgos de comportamiento | `backend/behavioral.py` (1880 L) | 12 cards `{code, severity, score, value_label, one_liner, evidence, references}` | `GET /api/behavioral/insights` | `/analisis?tab=comportamiento` + `InsightDelDiaHero` mobile |
| Wrapped anual | `backend/wrapped.py` (533 L) | slides tipo "stories" | `GET /api/wrapped/{year}` | `/wrapped` |
| Diagnóstico de objetivo | `backend/goals_diagnostic.py` (270 L) | `{status, projected, eta, delta_pct_required, diagnostic, suggestion}` | `GET /api/goals/{gid}/diagnostic` | `/posiciones?tab=objetivos` |
| Home: cards personales | `backend/home/briefing.py` (184 L) | `PersonalCard[]` | `GET /api/home/personal` | `/` (Home) |
| Home: mercado | `backend/home/market.py` (480 L) | índices / heatmap / movers | `GET /api/home/indices`, `/heatmap`, `/movers` | `/` (Home) |

`[V]` Endpoints: `backend/main.py:33072` (timeline), `backend/main.py:33136` (period detail),
`backend/main.py:13760` (behavioral), `backend/main.py:13682` (wrapped), `backend/main.py:15223` (goal diagnostic),
`backend/main.py:34181` (home personal), `backend/main.py:33235`/`33241`/`33249` (home market).

Consumidores extra (IA): `backend/ai/builders/monthly.py:104` (usa `build_period_report`),
`backend/ai/builders/behavioral.py:59` y `backend/ai/builders/behavioral_card.py:67` (usan `build_behavioral_insights`),
`backend/ai/builders/goal.py:89` (usa `build_goal_diagnostic`), `backend/ai/builders/dashboard.py:220`.

---

## 1. `reporting/builder.py` — el reporte de período

> Convención de esta sección: una cita suelta del tipo `` `:1234` `` refiere a
> **`backend/reporting/builder.py`**. Cualquier otro archivo va con su ruta completa.

### 1.1 Qué es un "reporte de período"

`[V]` El struct está en `backend/reporting/schema.py:113-133`. Un `PeriodReport` es:

```
period_type ∈ {day, week, month, year}   ← backend/reporting/builder.py:33-66 (parse_period_bounds)
period_key  '2026-05-13' | '2026-W19' | '2026-05' | '2026'
metrics     PeriodMetrics                ← el bloque de números
headline / subheadline                   ← 1-2 líneas generadas (determinístico, no LLM)
narrative                                ← párrafo de 2-5 oraciones
drivers[]   AssetContribution            ← atribución por activo (ops cerradas)
movers[]    HoldingMover                 ← mejor/peor holding por MtM (snapshots.holdings_json)
highlights[] Highlight                   ← mejor/peor operación
insights[]  Insight                      ← se llena en un pase aparte (detectors.py)
children[]  PeriodReport                 ← las semanas dentro del mes
is_relevant                              ← false = "sin actividad", el frontend lo colapsa
```

`[V]` Punto de entrada único: `backend/reporting/builder.py:2053` `build_period_report()`. Orden de armado:
bounds (`:2063`) → label (`:2064`) → `compute_metrics_for_period` (`:2075`) → drivers (`:2080`) →
highlights (`:2081`) → movers (`:2097-2107`) → headline (`:2108`) → narrativa (`:2109`) →
`is_relevant` (`:2115-2121`). Los insights NO se computan acá: quedan en `[]` (`:2134`) y los
llenan `backend/reporting/timeline.py:223`/`:231` o `backend/main.py:33199`.

### 1.2 Secciones internas del archivo

| Bloque | Líneas | Qué hace |
|---|---|---|
| Parseo de período | 33-97 | `parse_period_bounds`, `period_label`, `is_period_current` (usa `datetime.utcnow()`, `:94`) |
| Queries primitivas | 102-245 | `brokers_del_filtro` (par padre ↔ `· USD`), memo `pair_cache`, `capital_vigente`, `fetch_operations_in_range` |
| Lectura de snapshots | 248-431 | `fetch_snapshot_at_or_before` (con clasificación por `twr`), `fetch_latest_measured_snapshot` |
| Guards de base | 434-503 | `_basis_is_incomparable`, `_border_is_fresh`, `_ventana_cubre` |
| Bordes a mercado | 506-658 | `bordes_mercado_periodo`, `_pct_en_pesos` |
| Contabilidad mensual | 661-744 | `fetch_monthly_entry`, `fetch_cum_deposits_until` |
| Benchmarks | 747-778 | `benchmark_return_for_period` |
| **Métricas del período** | 783-1676 | `_modified_dietz_pct` + `compute_metrics_for_period` (850 líneas, el corazón) |
| Drivers | 1681-1700 | `compute_drivers` |
| Movers | 1705-1766 | `compute_movers` |
| Highlights | 1771-1806 | `compute_highlights` |
| Headline | 1811-1917 | `generate_headline` (+ concordancia de género) |
| Narrativa | 1922-2048 | `generate_narrative` |
| Entrada | 2053-2141 | `build_period_report` |

### 1.3 El par padre ↔ `<Padre> · USD`

`[V]` `brokers_del_filtro` (`backend/reporting/builder.py:102-131`) devuelve `["global"]` para el filtro global y,
para un broker, el **par** que resuelve `importing.persister.broker_pair` por `parent_broker_id`
(`:127-128`). Motivo documentado en el propio docstring: `positions`/`operations`/`monthly_entries`
referencian el broker por NOMBRE, así que un `AND broker = ?` con el nombre del padre dejaba afuera
todo lo del sibling (`backend/reporting/builder.py:105-116`).

`[V]` Memo con alcance de una construcción: `_PAIR_CACHE` (`threading.local`, `backend/reporting/builder.py:146`) +
`@contextmanager pair_cache()` (`:149-159`). El timeline lo abre en `backend/reporting/timeline.py:166-171`; el endpoint
de detalle en `backend/main.py:33186-33187`.

`[V]` `capital_vigente` (`backend/reporting/builder.py:167-211`) arrastra por pata su último cierre conocido en vez de
hacer un `SUM` del mes: `monthly_entries` es rala por broker y sumar dos cadenas de cobertura distinta
rompe el invariante `ci(m+1) = cf(m)`.

### 1.4 De dónde salen los números del período

`[V]` `compute_metrics_for_period` (`backend/reporting/builder.py:826-1676`) tiene **cinco ramas** mutuamente excluyentes:

| Rama | Condición | `start_value` | `end_value` | `deposits`/`withdrawals` | Línea |
|---|---|---|---|---|---|
| Mes CERRADO con dos bordes medidos | `bordes_mercado_periodo` devuelve par | snapshot medido del día ANTERIOR al período | snapshot medido dentro del período | de `monthly_entries` | 1020-1035 |
| Mes CERRADO sin bordes, global | fallback | `monthly_entries.capital_inicio` | `.capital_final` | `monthly_entries` | 890-893 + 1058-1089 (`twr.curva_indexada` pisa el %) |
| Mes EN CURSO | `is_period_current` y `live_value is not None` | snapshot MtM del día anterior si es fresco, si no `capital_inicio` / `capital_vigente` del mes previo | `live_value` | `monthly_entries` o Δ `net_deposited` | 913-989 |
| Año | `period_type == "year"` | `capital_inicio` del primer mes (o `capital_vigente`) | `capital_final` del último mes, o `live_value` | Σ de los meses | 1090-1399 |
| Día / semana | resto | snapshot MtM (`mtm_only=True`) del `period_start` | `live_value` o snapshot del `period_end` | Δ `net_deposited` entre snapshots | 1408-1465 |

`[V]` Con **filtro de broker** en día/semana no se calcula nada: `dw_incomplete = True`, `delta = realized`,
`unrealized = 0`, `%` = None (`backend/reporting/builder.py:1400-1407` + `1524-1531`). Motivo: los snapshots son globales.

`[V]` Fórmulas finales (`backend/reporting/builder.py:1467-1470`):
```python
flows      = deposits - withdrawals
delta_usd  = end_value - start_value - flows
delta_pct  = _modified_dietz_pct(start_value, end_value, flows)
```

`[V]` Modified Dietz (`backend/reporting/builder.py:783-794`):
```python
avg = start_value + 0.5 * flows
if avg <= 0: return None
return ((end_value - start_value - flows) / avg) * 100     # SIN clamp
```

`[V]` `delta_pct_over_contrib = delta_usd / Σ(deposits−withdrawals) hasta period_end × 100`
(`backend/reporting/builder.py:1533-1536`); el denominador sale de `snapshots_job.compute_net_deposited_db` con
`include_baseline=False`, sumado por pata (`backend/reporting/builder.py:716-744`).

`[V]` Orden de precedencia del `%` publicado (importante — el último que escribe gana):
1. Dietz punta a punta (`:1469`)
2. si `moneda=ars`, el mismo tramo convertido a pesos (`_pct_puntas_ars`, `:1488-1500`)
3. si es mes y el motor canónico midió: `month_twr_pct` **y también** `month_twr_usd` pisa el monto (`:1509-1512`)
4. si es año y el motor midió y el mes vivo no quedó sin medir: `year_twr_pct` (`:1513-1514`)
5. si `dw_incomplete`: `None` (`:1518-1519`)
6. si el motor se negó con motivo de dato ROTO: `delta_pct=None`, `delta_usd=0`, `basis_incomparable=True` (`:1608-1620`)
7. si `basis_incomparable`: `delta_pct=None`, `delta_usd=0` (`:1621-1629`)

### 1.5 "Certero" vs "estimado" — qué lo determina y qué ve el usuario

`[V]` Los dos controles llegan por query-string: `modo=certero|estimado` y `moneda=usd|ars`
(`backend/main.py:33076-33077`, `33140-33141`) y viajan hasta `compute_metrics_for_period`
(`backend/reporting/builder.py:830`). El frontend los manda desde `useReportsTimeline`
(`frontend/src/hooks/useReportsTimeline.js:34-35`) y desde `usePeriodItems`
(`frontend/src/pages/Reports.jsx:43-46`). El toggle es `ModoRendimiento`
(`frontend/src/components/ModoRendimiento.jsx:15-21`): *certero* = "sólo lo valuado a precio real";
*estimado* = "además la contabilidad reconstruida … sólo se mueve cuando vendés".

`[V]` **Dónde `modo` cambia algo de verdad: sólo en dos lugares**, ambos delegando en `twr.curva_indexada`:
- mes cerrado + `broker_filter == "global"` → `backend/reporting/builder.py:1058-1064`
- año + `broker_filter == "global"` → `backend/reporting/builder.py:1231-1236`

`[V]` **Hallazgo — `modo` se estampa aunque no se haya usado.** `PeriodMetrics.modo` se escribe
siempre con lo que pidió el caller (`backend/reporting/builder.py:1673`), incluso cuando el número salió del Dietz de
`monthly_entries` sin pasar por el motor. Un mes con filtro de broker, una semana, un día y el mes
EN CURSO devuelven `modo: "estimado"` si el toggle está ahí, pero calcularon exactamente lo mismo que
en "certero". El toggle en esos casos es decorativo.

`[V]` Lo que sí distingue el reporte es `basis`, un campo APARTE (`backend/reporting/schema.py:95`):
- `basis = "mercado"` — las dos puntas salieron de cierres medidos (`backend/reporting/builder.py:1030`, `:1183`) o el
  motor devolvió `base_del_twr != "contable"` (`:1067`, `:1255`).
- `basis = "contable"` — default (`:872`); las puntas son `capital_inicio`/`capital_final`.

`[V]` Por qué importa: para un mes cerrado la cadena contable cumple
`capital_final = capital_inicio + flujos + pnl_realized`, así que `end − start − flows` **es** el
realizado y no sabe nada del mercado (docstring en `backend/reporting/builder.py:527-538` y `backend/reporting/schema.py:88-95`).
Consecuencias visibles, todas verificadas en el código:
- `detect_streak` y `detect_reversal` se apagan con `basis == "contable"`
  (`backend/reporting/detectors.py:261-262`, `:332-333`). El comentario dice que sobre producción del 16/08,
  marzo-julio, 88 rachas y 29 reversals disparaban en contable y **cero** en mercado.
- la narrativa agrega la advertencia de sesgo al "vs S&P" (`backend/reporting/builder.py:2042-2045`).

`[V]` **Qué ve el usuario cuando NO se puede medir.** Tres campos viajan al frontend:
`basis_incomparable` (bool), `motor_motivo` y `motor_motivo_texto` (`backend/reporting/schema.py:87`, `:102-103`).
`frontend/src/components/reports/MonthCard.jsx:66-68` los lee y pone `deltaPct`/`deltaUsd` en `null`.
El headline sale de `generate_headline` que evalúa `basis_incomparable` **primero**
(`backend/reporting/builder.py:1853-1863`): *"Mes sin base para medir el rendimiento."* + el motivo real. La narrativa
hace lo mismo (`backend/reporting/builder.py:1938-1957`) y cuenta sólo lo que sí es medible (realizado y flujos).

`[V]` Los dos textos canónicos de motivo están en `backend/reporting/builder.py:813-823`
(`_MOTIVO_MES_DUDOSO`, `_MOTIVO_PUNTAS_DUDOSAS`), y la lista de motivos que CORTAN es
`MOTIVOS_DATO_ROTO = ("medicion_dudosa", "cadena_implausible")` (`backend/reporting/builder.py:811`). El comentario de
arriba (`:797-810`) distingue explícitamente "no hay con qué medir" (se publica contable) de
"el dato está roto" (no se publica).

`[V]` La cota de cordura se importa de `twr`, no se copia: `twr.leg_dudoso` se usa en la composición
mensual del año (`backend/reporting/builder.py:1368-1373`) y en las puntas del Dietz contable (`backend/reporting/builder.py:1578-1607`),
con `twr.SALTO_MAX_VECES` (`backend/reporting/builder.py:1594`). Definiciones en `backend/twr.py:612-620` y `backend/twr.py:623-647`.

### 1.6 Benchmarks del reporte

`[V]` `benchmark_return_for_period` (`backend/reporting/builder.py:749-778`):
- `sp500`: `((close[mes] / close[mes anterior]) − 1) × 100`, serie mensual keyed `YYYY-MM` (`:764-773`).
- `inflation_ar`: el valor mensual tal cual (`:774-777`).
- **devuelve `None` para todo `period_type != "month"`** (`:760-761`).

`[V]` `vs_sp500_pct` y `vs_inflation_pct` son el EXCESO en puntos porcentuales
(`backend/reporting/builder.py:1646-1647`); el retorno propio del benchmark va en `sp500_return_pct` / `inflation_pct`
(`:1665-1666`). El comentario de `backend/reporting/schema.py:75-84` documenta que hasta "AUDIT D-2" el campo guardaba
el retorno del benchmark y la narrativa lo leía como diferencia.

`[V]` `frontend/src/components/reports/MonthCard.jsx:229-233` los renderiza como celdas "vs S&P 500" y "vs Inflación AR" con
sufijo `%` (son pp, no %).

### 1.7 Drivers, movers y highlights

`[V]` `compute_drivers` (`backend/reporting/builder.py:1681-1700`): agrupa `pnl_usd` por activo y ordena por `|pnl|`,
top 5. La contribución es
```python
contribution_pct = abs(pnl) / Σ|pnl| × 100      # backend/reporting/builder.py:1691, :1697
```
o sea, **% del movimiento bruto absoluto**, no % del P&L neto.

`[V]` `compute_movers` (`backend/reporting/builder.py:1717-1766`): diferencia `snapshots.holdings_json` entre el día
anterior al `start` y el `end`. Sólo cuenta activos presentes en AMBOS bordes (`:1743-1745`),
descarta deltas `< US$0,50` (`:1747`), devuelve el mejor y el peor. `movers_available=False` si falta
alguna foto o si las dos fotos son la misma fila (`:1731-1734`).

`[V]` Con filtro de broker los movers se apagan salvo que el filtro cubra TODOS los brokers del
usuario (`backend/reporting/builder.py:2097-2107`): `holdings_json` no guarda el broker por activo.

`[V]` `compute_highlights` (`backend/reporting/builder.py:1771-1806`): mejor y peor operación entre `trade_ops`,
con umbrales `pnl > 1` y `pnl < −1` (`:1790`, `:1798`).

### 1.8 Headline y narrativa

`[V]` `generate_headline` (`backend/reporting/builder.py:1837-1917`), en orden de evaluación:

| # | Condición | Salida |
|---|---|---|
| 0 | `basis_incomparable` | "{Período} sin base para medir el rendimiento." + `motor_motivo_texto` (`:1853-1863`) |
| 1 | `realized ≥ 50` y `delta < −0,5%` y `trades > 0` | "Cerraste con ganancia (+US$ X), pero el portfolio bajó Y%." (`:1869-1873`) |
| 2 | `realized ≤ −50` y `delta > 0,5%` y `trades > 0` | "Operaciones con pérdida …, pero el portfolio subió Y%." (`:1875-1879`) |
| 3 | `delta_pct is None` y `|delta_usd| < 100` | "{Período} sin grandes movimientos." (`:1885-1886`) |
| 4 | `delta_pct is None` | "{Período}: ±US$ X." + "Sin base suficiente para calcular el %" (`:1887-1891`) |
| 5 | `|delta| < 0,5%` y `|delta_usd| < 100` | "{Período} sin grandes movimientos." (`:1894-1895`) |
| 6 | `delta < −3%` | "{Período} difícil — X%" + driver negativo (`:1898-1904`) |
| 7 | `delta > 3%` | "{Período} sólido/sólida — +X%" + driver ≥30% (`:1907-1913`) |
| 8 | resto | "{Período} mixto/mixta — ±X%" (`:1915-1917`) |

`[V]` Concordancia de género vía `_PERIOD_WORD` (`:1814-1819`) y `_ADJ_FEMININE` (`:1822-1827`);
"difícil" queda invariable a propósito.

`[V]` `generate_narrative` (`backend/reporting/builder.py:1922-2048`) arma hasta 5 oraciones: balance, drivers
(umbral `|pnl| ≥ 50`, `:1998`/`:2002`), flujos (`|neto| ≥ 100`, `:2011`), trades + win rate (`:2018`),
y vs S&P (umbral `|vs| ≥ 0,5pp`, `:2039`) con la advertencia de sesgo si `basis == "contable"`
(`:2042-2045`). Devuelve `None` si el período es plano y sin trades (`:1958-1959`).

### 1.9 `is_relevant`

`[V]` `backend/reporting/builder.py:2115-2121`:
```python
is_relevant = trades_count > 0 or |delta_usd| >= 100 or deposits > 0
              or withdrawals > 0 or basis_incomparable
```
El último término está para que un período impublicable no se colapse como "sin actividad"
(comentario `:2112-2114`).

---

## 2. `reporting/detectors.py` — catálogo completo

> Convención de esta sección: `` `:1234` `` = **`backend/reporting/detectors.py`**.

`[V]` 12 detectores, ejecutados por `run_detectors` (`backend/reporting/detectors.py:417-457`) y ordenados
`warning → positive → info` (`:455-456`). Cada uno devuelve `None` ante la duda (`:10`).

| # | `code` | Función:línea | Umbral | Severidad | Frase (título) |
|---|---|---|---|---|---|
| 1 | `CONCENTRATION_RISK` | `:31` | top-1 no-cash ≥ 40 % del total; total ≥ US$100 (`:47`, `:53`) | `warning` si ≥60 %, si no `info` (`:55`) | "Tu portfolio depende mucho de {ASSET}" |
| 2 | `DRIVER_OF_PERIOD` | `:68` | `contribution_pct ≥ 40` y `|pnl| ≥ 50` (`:73-76`) | `info` | "{ASSET} fue el motor del período" |
| 3 | `HIGH_TURNOVER` | `:92` | `trades ≥ 5` y `trades / promedio ≥ 2` (`:94`, `:99`) | `info` | "Operaste más que tu promedio" |
| 4 | `DEPOSITS_DRIVE_GROWTH` | `:114` | `deposits ≥ 500`, `|delta| < 0,3·deposits`, `deposits ≥ 3·|delta|` (`:125-131`); apagado si `basis_incomparable` (`:121`) | `info` | "El crecimiento vino de aportes, no de rendimiento" |
| 5 | `WIN_RATE_UP` / `WIN_RATE_DOWN` | `:145` | `trades ≥ 4` y `|wr − wr_histórico| ≥ 10 pp` (`:148`, `:153`) | `positive` / `warning` | "Tu acierto subió/bajó este período" |
| 6 | `BEAT_BENCHMARK` / `UNDERPERFORM_BENCHMARK` | `:178` | sólo `month`; `|exceso| ≥ 1,0 pp` (`:180`, `:191`) | `positive` / `info` | "Le ganaste al S&P 500" / "El S&P 500 te ganó" |
| 7 | `LARGE_CASH_DRAG` | `:216` | cash ≥ 30 % del total; total ≥ US$1.000 (`:223`, `:226`) | `info` | "{X}% de tu portfolio está en cash" |
| 8 | `STREAK_POSITIVE` / `STREAK_NEGATIVE` | `:241` | sólo `month`; **apagado si `basis == "contable"`** (`:261`); `|delta| ≥ 0,5 %` y racha ≥ 3 meses del mismo signo (`:264`, `:275`) | `positive` / `warning` | "Vas N meses positivos/negativos seguidos" |
| 9 | `REALIZED_VS_UNREALIZED_GAP` | `:294` | sólo `month`; `realized ≥ 500`, `unrealized ≤ −0,5·realized`, `|unrealized| ≥ 500` (`:301-306`) | `warning` | "Cerraste ganancias pero arrastrás pérdidas abiertas" |
| 10 | `REVERSAL` | `:320` | sólo `month`; **apagado si `basis == "contable"`** (`:332`); signos opuestos y `|ambos| ≥ 2 %` (`:339-342`) | `info` | "Cambio de tendencia respecto del mes anterior" |
| 11 | `DIVIDEND_HEAVY` | `:357` | dividendos+intereses ≥ US$50 y ≥ 50 % del realizado (`:368`, `:371`) | `info` | "Los dividendos explicaron el X% del rendimiento" |
| 12 | `CONSISTENT_POSITIVE` / `CONSISTENT_NEGATIVE` | `:386` | sólo `month` con ≥2 semanas relevantes; TODAS >+0,2 % o TODAS <−0,2 % (`:390-394`) | `positive` / `warning` | "Mes consistente" / "Mes con caídas sostenidas" |

`[V]` **Qué detectores nunca corren en cada superficie**:
- Semanas dentro del timeline: `run_detectors(..., positions=[], avg_trades_per_period=0, ...)`
  (`backend/reporting/timeline.py:223-226`) → se apagan 1, 3, 7 (positions vacías), 8, 9, 10, 11, 12 (por `period_type`
  o por falta de contexto). Sobreviven 2, 4, 5.
- Endpoint de detalle (`day`/`week`/`year` de la pantalla): `backend/main.py:33199-33204` **no** pasa
  `prior_monthly_deltas` ni `period_operations` → nunca disparan 8 (racha), 10 (reversal) ni 11
  (dividend heavy).
- Tab "Año": como `benchmark_return_for_period` devuelve `None` fuera de mes (`backend/reporting/builder.py:760`),
  `vs_sp500_pct` es siempre `None` y el detector 6 no existe para el año; 8, 9, 10, 12 exigen
  `period_type == "month"`. **El reporte anual queda prácticamente sin insights** salvo 1, 2, 3, 4, 5, 7.

---

## 3. `reporting/timeline.py` — el eje temporal

> Convención de esta sección: `` `:1234` `` = **`backend/reporting/timeline.py`**.

`[V]` `build_timeline` (`backend/reporting/timeline.py:149-171`) abre el memo del par y delega en `_build_timeline`
(`:174-243`).

Construcción:
1. `[V]` `_months_back(months)` (`:21-33`) genera N `period_key` `YYYY-MM` **hacia atrás desde
   `date.today()`**, sin mirar la DB. No hay "meses sin datos" que saltear: **siempre se devuelven
   los N meses**, tengan o no filas.
2. `[V]` Se recorren de más viejo a más nuevo (`:193`) para poder pasarle a los detectores
   `prior_monthly_deltas` en orden ascendente (`:235`).
3. `[V]` Por mes: `build_period_report` (`:200`), luego `fetch_operations_in_range` para
   `DIVIDEND_HEAVY` (`:207-210`), luego las semanas (`:213-227`), luego los detectores del mes
   (`:231-237`).
4. `[V]` Se devuelve descendente (`:243`).

`[V]` Semanas de un mes: `_weeks_in_month` (`:36-58`) — **una semana ISO "pertenece" al mes si su
LUNES cae en ese mes** (`:52-56`). Consecuencia directa: una semana puede aportar días de otro mes,
y la suma de las semanas nunca reconstruye el mes.

`[V]` `live_value` sólo se le pasa a la semana en curso (`:219` + `wrpt_is_current_check`, `:246-253`).

`[V]` Qué pasa con un mes sin datos: `fetch_monthly_entry` devuelve `None` (por el `COUNT(*)`,
`backend/reporting/builder.py:697-698`), todas las métricas quedan en 0, `is_relevant=False` y el frontend lo colapsa
(comentario `backend/reporting/timeline.py:7-8`). No se saltea ni se interpola.

Contexto pre-computado una vez por request:

| Helper | Línea | Fórmula | Filtra por broker |
|---|---|---|---|
| `_compute_user_historical_win_rate` | `:61-77` | `wins / trades × 100` sobre TODAS las ops con `pnl_usd IS NOT NULL`, excluyendo Compra/Dividendo/Interés/Conversión | **no** |
| `_compute_avg_trades_per_month` | `:80-93` | `COUNT(*) / 12` sobre los últimos ~360 días (`day=1 − 12×30`) | **no** |
| `_fetch_positions_for_concentration` | `:96-146` | valúa cada posición con `behavioral._position_value_usd` | sí (`:119-125`) |

`[V]` **Hallazgo — el reporte mide concentración y cash AL COSTO.** Los dos endpoints llaman con
`prices={}`: `backend/main.py:33123` (timeline) y `backend/main.py:33198` (detalle). Con `prices` vacío,
`_resolve_price` devuelve `None` (`backend/behavioral.py:374-375`) y `_position_value_usd` cae al
`invested` (`backend/behavioral.py:475-481`). O sea: `CONCENTRATION_RISK` y `LARGE_CASH_DRAG` en Reportes se
calculan sobre el **cost basis**, mientras las cards equivalentes de Comportamiento
(`detect_concentration`, `detect_cash_drag`) se calculan a **precio de mercado**
(`backend/main.py:13790` pasa `prices` de `currency_context`). Dos pantallas, la misma pregunta, dos
denominadores.

`[V]` **Hallazgo — `_fetch_positions_for_concentration` no estampa `_byma`.** El SELECT trae
`br.currency` (`backend/reporting/timeline.py:127-133`) pero nunca llama a `stamp_byma`, que es la fuente de verdad
parent-aware que `_price_is_ars` prefiere (`backend/behavioral.py:187-188`). Con `prices={}` hoy no muerde;
si alguien alguna vez le pasa precios, la ruta `.BA` cae a las heurísticas por nombre.

---

## 4. `behavioral.py` — los 12 detectores de comportamiento

> Convención de esta sección: `` `:1234` `` = **`backend/behavioral.py`**.

`[V]` Orquestador `build_behavioral_insights` (`backend/behavioral.py:1805-1880`). Normaliza `pnl_usd` con
`realized_pnl.realized_usd` una sola vez, en la entrada (`:1841-1844`), corre las 12 cards
(`:1846-1863`) y arma el `summary` contando severidades (`:1865-1868`).

`[V]` **Doc drift**: el docstring dice "corre los 10 detectores" y "siempre las 10"
(`:1813`, `:1826`); son 12. El docstring del endpoint repite el error (`backend/main.py:13763`).

### 4.1 Tabla de métricas

| Métrica | Función:línea | Fórmula | Qué le dice al usuario |
|---|---|---|---|
| Disposition effect | `:487` | `ratio = días_prom(winners) / días_prom(losers)` (`:518-520`) | <0,5 `high`; <0,7 `medium`; <1,3 `positive`; <2,0 `medium`; ≥2 `low` "diamond hands" (`:522-553`). `score = min(100, |1−ratio|·100)` (`:560`) |
| Overtrade / rotación | `:583` | `turnover = Σ(entry_price×qty en USD) / capital_prom / años` (`:607-618`); `años = max(30 días, span)/365` (`:614`) | ≥4 `high`; ≥2 `medium`; ≥0,3 `positive`; resto "buy & hold" (`:621-642`). `score = min(100, turnover·25)` (`:649`) |
| Loss aversion (tamaños) | `:670` | `ratio = notional_prom(losers) / notional_prom(winners)` (`:685-693`) | ≥2 `high`; ≥1,5 `medium`; ≥0,7 `positive`; resto "sano" (`:695-719`). `score = min(100, max(0,(ratio−1)·50))` (`:726`) |
| Averaging down | `:745` | compras del mismo ticker con `precio < 0,95 × anterior` y gap ≤ 60 días (`:804-806`) | ≥5 instancias o caída prom ≥20 % → `high`; ≥2 → `medium`; 1 → `low` (`:840-857`). `score = min(100, n·15 + drop·1,5)` (`:864`) |
| Win rate + payoff | `:882` | `win_rate = W/(W+L)·100`; `payoff = avg_win/avg_loss`; `expectancy = wr·avg_win − (1−wr)·avg_loss` (`:898-902`) | `expectancy < 0` → `high` "tu estrategia pierde plata"; `wr≥60 y payoff<0,7` → `medium`; `wr<40 y payoff<1,5` → `medium`; `exp>0 y payoff≥1,5` → `positive` (`:905-940`) |
| Concentración por activo | `:969` | `top1_pct`, `top3_pct`, `top5_pct` sobre el total no-cash (`:1001-1003`) | top1≥40 → `high`; top1≥25 o top3≥70 → `medium`; top1<15 y top3<40 → `positive` (`:1005-1029`). `score = min(100, top1·2)` (`:1036`) |
| Home bias | `:1060` | `ar_pct = valor_AR / (AR+intl) × 100`, exposición ECONÓMICA (CEDEAR = internacional) (`:1082-1107`) | ≥80 `high`; ≥65 `medium`; `<5 y total>1000` `medium` (poco AR); 20–50 `positive` (`:1109-1137`). `score = |ar_pct − 35| × 1,5` (`:1144`) |
| Cash drag | `:1163` | `cash_pct = (cash_usd + cash_ars_usd)/total`; `cash_ars_pct` aparte (`:1216-1217`) | ≥30 % o ARS ≥15 % → `high`; ≥20 % → `medium`; <5 % → `low` "sin cushion"; resto `positive` (`:1219-1249`). Cash neto negativo → card especial "no aplica" (`:1194-1215`) |
| Pérdida por inflación | `:1276` | `infl_cum = Π(1+m/100) − 1` últimos 12 meses (`:1315-1321`); `loss = cash_ars × infl/(100+infl)` (`:1324`); `loss_usd = loss/tc_blue` (`:1325`) | ≥US$500 o infl ≥100 % → `high`; ≥US$100 → `medium` (`:1327-1340`). Fallback 60 % anual si no hay serie (`:1312-1313`) |
| Counterfactual (no-trade) | `:1369` | `hipotético = realizado + (precio_hoy − exit_price)·qty` (`:1442`); `delta = Σhipotético − Σrealizado` (`:1461`) | >US$1.000 `high` "hubieras ganado más NO vendiendo"; >300 `medium`; <−300 `positive` "vender fue acertado" (`:1463-1487`) |
| Recency bias (chase pump) | `:1516` | por posición `ratio = buy_price / precio_actual`; flag si ≥1,30; `chase_pct = Σinvested_flagged/Σinvested` (`:1564-1578`) | ≥50 % `high`; ≥25 % `medium`; >5 % `low` (`:1580-1597`). `score = min(100, chase_pct·1,5)` (`:1610`) |
| Concentración sectorial | `:1696` | mapea ticker→sector con `_SECTOR_MAP` (`:1630`) / `_sector_for` (`:1678`); `top_pct`, `top3_pct` (`:1730-1731`) | ≥50 % `high`; ≥35 % `medium`; <30 % `positive` (`:1733-1757`). `score = min(100, top_pct·1,5)` (`:1764`) |

`[V]` Mínimos de datos por card (si no, `_not_enough_data`, `:1788-1802`): disposition ≥5 ops válidas
y ≥2 winners y ≥2 losers (`:509`, `:515`); overtrade ≥3 trades (`:592`); loss aversion ≥3 y ≥3
(`:682`); winrate ≥5 (`:894`); counterfactual ≥3 trades + precios (`:1391`) y ≥3 ventas en USD
comparables (`:1454`).

`[V]` **Doc drift**: el docstring de `detect_disposition_effect` promete "≥10 ops cerradas"
(`:496`) y el código exige 5 (`:509`).

### 4.2 Guards de moneda (lo que sostiene todo lo anterior)

`[V]` `_position_value_usd` (`:391-481`) es el valuador canónico del módulo y lo reusan 8 builders de
IA, `reporting/timeline.py:140` y `backend/main.py:15259`. Maneja dos ejes distintos: `cost_ccy`
(`_native_ccy`, `:195-222`) para el costo, y `price_is_ars` (`_price_is_ars`, `:166-192`) para el
precio live. Prioridad: cash → `price_override` → precio live con guard `_trust_mkt_value_usd`
(`:47-60`) → fallback a costo.

`[V]` `detect_counterfactual` descarta explícitamente todo lo que no puede confirmar como USD
(`:1413-1436`): brokers AR (por el ratio del CEDEAR) y ops cuyo FX implícito `pnl_usd/pnl_nativo`
no cae en `[0,5 ; 2,0]`. El contador de descartes viaja en `evidence.trades_skipped_fx` (`:1504`).

`[V]` `detect_recency_bias` omite la posición cuando el broker AR y la moneda nativa no coinciden
(`:1557-1558`) porque `buy_price` y `current_price` quedarían en monedas distintas.

### 4.3 Hallazgos

`[V]` **La paywall de Comportamiento es sólo de frontend.** `GET /api/behavioral/insights`
(`backend/main.py:13760-13803`) no consulta el plan: devuelve las 12 cards completas, con `evidence`.
El corte lo hace `BehavioralCards` en el cliente (`frontend/src/pages/Behavioral.jsx:661`,
`:686-693`: Free ve 3, Plus 6, Pro todas). Un `curl` al endpoint las trae todas.

`[V]` **`detect_overtrade` con capital 0 inventa un capital.** Si no hay `positions` o valen 0,
`capital_avg = Σ|pnl| × 5` (`:604`), un multiplicador arbitrario sin justificación en el código; el
turnover resultante y su severidad salen de ahí.

`[V]` **`detect_inflation_loss` usa `invested` crudo en pesos** (`:1295`) mientras el resto del
módulo pasa por `_position_value_usd`. Para cash eso coincide (`:442-447` devuelve `invested`), pero
la conversión a USD acá usa `tc_blue` (`:1325`) y en `_position_value_usd` usa `rate_holdings`
(MEP, `:446`). Dos dólares distintos para el mismo peso, en el mismo request.

---

## 5. `wrapped.py` — el resumen anual

> Convención de esta sección: `` `:1234` `` = **`backend/wrapped.py`**.

`[V]` **¿Vivo o estacional? Vivo, todo el año, y sin entrada en la navegación.**
- El endpoint `GET /api/wrapped/{year}` (`backend/main.py:13682-13757`) sólo valida `2000 ≤ year ≤ 2200`
  (`:13689-13690`). No hay gate de fecha ni de plan.
- La ruta `/wrapped` existe (`frontend/src/App.jsx:224`) y la página no tiene ningún chequeo de mes
  ni de plan (`frontend/src/pages/Wrapped.jsx`, 604 líneas; grep de `getMonth`/`plan`/`locked` = 0
  resultados).
- **No hay ningún link a `/wrapped` en la app**: las únicas referencias son `frontend/src/App.jsx:224`
  (la ruta) y `routePrefetch.js:36`. Se llega sólo tipeando la URL.
- La guía le promete al usuario otra cosa: *"En diciembre/enero se desbloquea Wrapped"*
  (`frontend/src/pages/guia/InsightsYReportes.jsx:284-286`). Ese desbloqueo estacional **no existe
  en el código**.

`[V]` `build_wrapped` (`backend/wrapped.py:427-533`) es pura: recibe `monthly`, `operations`,
`behavioral_cards`, `benchmarks`, `inflation_ytd` y no toca la DB.

`[V]` Slides, en orden (`:476-521`):

| Slide | Builder:línea | Cómo se calcula |
|---|---|---|
| `intro` | `:93` | teaser con `twr`, `pnl_usd`, `total_trades`, `best_month_label` (`:468-474`) |
| `pnl` | `:129` | `twr` de `_twr_for_period`; `pnl_usd = Σ(pnl_realized + pnl_unrealized)` (`:144`); capital inicio/final de la primera y última fila (`:142-143`) |
| `best_month` | `:161` | ordena por `(pnl_realized + pnl_unrealized) / capital_inicio` (`:167`) |
| `worst_month` | `:186` | misma fórmula, mínimo; se omite si el peor mes es positivo (`:198-200`) |
| `best_trade` | `:213` | `max(pnl_usd)` sobre ops con `exit_price` **o** `pnl_usd` (`:214`, `:217`) |
| `activity` | `:242` | `Counter` de activos, top 3 + total de ops (`:245-268`) |
| `vs_benchmark` | `:314` | `delta = twr_user − benchmarks['sp500_ytd' / 'merval_ytd']` (`:327`, `:335`); tono por el promedio de deltas (`:342`) |
| `vs_inflation` | `:372` | `delta = twr_user − inflation_ytd` (`:378`) |
| `dominant_bias` | `:272` | rank `high>medium>low>positive>neutral` sobre las cards de behavioral (`:278-282`) |
| `outro` | `:413` | fijo |

`[V]` `_twr_for_period` (`:50-69`) — el retorno anual del Wrapped:
```python
ret = (capital_final − capital_inicio − (deposits − withdrawals)) / capital_inicio
ret = max(-0.95, min(5.0, ret))          # CLAMP  ← backend/wrapped.py:64
prod *= (1 + ret)                        # composición geométrica
return prod - 1
```
`[V]` Filtra sólo las filas `broker == 'global'` de `monthly_entries` (`:41-47`), que son el agregado
cross-broker (`monthly_entries` tiene una fila por broker más una `'global'`;
ver `backend/main.py:25379` y `.schema monthly_entries`).

### 5.1 Hallazgos

`[V]` **Dos fórmulas de "retorno mensual" dentro del mismo archivo.** El TWR del año divide por
`capital_inicio` usando `capital_final − ci − flujos` (`:62`), pero los slides "mejor/peor mes"
rankean por `(pnl_realized + pnl_unrealized) / capital_inicio` (`:167`, `:192`). Para un mes cerrado
con `pnl_unrealized = 0` los dos coinciden; con `pnl_unrealized` posteado por el navegador
(el latente ACUMULADO, no del mes — ver `backend/reporting/builder.py:1546-1548`) divergen, y el "mejor mes" puede no
ser el que más aportó al número grande del slide anterior.

`[V]` **"Tu mejor trade" puede ser un cupón o un dividendo.** `_slide_best_trade` toma
`[o for o in ops if (o.get('exit_price') or o.get('pnl_usd'))]` (`:214`) — sin filtrar `op_type`. Un
`Cupón`, una `Amortización`, un `Dividendo` o una `CONVERSION IMPORT` entran al ordenamiento. El
comentario de `_operations_for_year` (`:73-80`) documenta que la normalización de moneda se agregó
justo porque un cupón de $125.000 ganaba el slide; la normalización arregla la MONEDA, no la
inclusión.

`[V]` **`merval_ytd` nunca llega.** `_slide_vs_benchmark` lo lee (`:321`) pero el endpoint sólo
puebla `sp500_ytd` (`backend/main.py:13738`) — el comentario lo reconoce (`backend/main.py:13723-13724`). La barra
"MERVAL" del slide es código muerto en producción.

`[V]` **`twr_user` en USD contra `inflation_ytd` en pesos.** `_slide_vs_inflation` (`:372-410`)
resta directo, sin declarar la unidad. Es el mismo problema que `vs_inflation_pct` del reporte
(sección 8).

---

## 6. `goals_diagnostic.py` — el progreso de un objetivo

> Convención de esta sección: `` `:1234` `` = **`backend/goals_diagnostic.py`**.

`[V]` `build_goal_diagnostic(goal, current_value, user_cagr_pct, behavioral_cards, now)`
(`backend/goals_diagnostic.py:147-269`). Entradas del endpoint (`backend/main.py:15223-15290`):
- `current_value` = Σ `_position_value_usd` de todas las posiciones (`backend/main.py:15260-15267`), a
  precios de mercado vía `currency_context` (`:15254`).
- `user_cagr_pct` = `_historical_cagr_global(conn, uid)["cagr"]` (`backend/main.py:15271`), que es el motor
  canónico `twr.curva_indexada` (`backend/main.py:15345-15391`).
- `behavioral_cards` = las 12 cards (`backend/main.py:15277-15279`).

`[V]` Fórmulas:

| Paso | Línea | Fórmula |
|---|---|---|
| Meses restantes | `:85-93` | `(td.year − now.year)·12 + (td.month − now.month)`, con piso 0 — **ignora el día** |
| Tasa mensual requerida | `:96-101` | `(target/current)^(1/meses) − 1`, **sin aportes** |
| Tasa mensual del usuario | `:216` | `(1 + cagr/100)^(1/12) − 1` |
| Proyección | `:117-121` | `current × (1 + mensual)^meses`, **sin aportes** |
| ETA | `:104-114` | `ceil( ln(target/current) / ln(1+mensual) )`, `None` si >600 meses |
| Brecha publicada | `:251` | `(requerida − usuario) × 12 × 100` (pp "anualizados" por ×12, no compuestos) |
| `required_annual_pct` | `:267` | `((1+requerida)^12 − 1) × 100` |

`[V]` Estados (`:222-230`):
- `current ≥ target` → `ahead` "¡Meta alcanzada!" (corta antes, `:170-178`)
- `current ≤ 0` o `target ≤ 0` → `unreachable` "Datos insuficientes" (`:182-191`)
- `months_left ≤ 0` → `behind` con la fecha vencida (`:195-211`)
- `usuario ≥ 0,95 × requerida` → `on_track` si `usuario ≤ 1,10 × requerida`, si no `ahead`
- resto → `behind`

`[V]` La sugerencia sale del sesgo dominante (`_pick_dominant_bias`, `:124-144`, rank
`high>medium>low`) mapeado por `SUGGESTION_MAP` (`:26-82`, 11 códigos), y **sólo** si el estado es
`behind` o `unreachable` (`:255`).

### 6.1 Hallazgos

`[V]` **`user_cagr_pct = None` se convierte silenciosamente en 0 %.** `backend/goals_diagnostic.py:215`:
`user_cagr_frac = (user_cagr_pct or 0) / 100`. `_historical_cagr_global` devuelve `cagr: None`
justamente en dos casos legítimos y frecuentes: cuando el motor se negó (`backend/main.py:15383-15385`) y
cuando la ventana medida es menor a medio año (`backend/main.py:15386-15390`, "anualizarlo amplificaría el
ruido"). En ambos, el objetivo publica `user_monthly = 0` → `status='behind'` →
*"Al ritmo actual, no llegás a la meta sin aportes adicionales"* (`:247`). Un usuario con 3 meses de
historia recibe un veredicto negativo que no salió de ningún dato suyo. El propio
`_historical_cagr_global` devuelve `total_return_pct` y la ventana para poder decirlo bien, y este
motor no los mira.

`[V]` **El diagnóstico proyecta SIN aportes y después recomienda aportar.** `_project_value` y
`_required_monthly_rate` son explícitamente "sin aportes" (`:98`, `:118`), y el texto de `behind`
dice "Necesitás acelerar o aumentar aportes" (`:245`). La tabla `goals` no tiene columna de aporte
mensual (`.schema goals`: `target_usd`, `target_date`, `expected_return_pct`, `label`), y
`backend/ai/builders/goal.py:35` lee `g.get("monthly_contribution")` — **un campo que no existe**, así que el
packet de IA siempre publica `monthly_contribution: 0` (`backend/ai/builders/goal.py:128`).

`[V]` **La card y el diagnóstico responden preguntas distintas, y encima cuentan los meses
distinto.** `GoalCard` en el frontend proyecta con `goal.expected_return_pct` (la tasa que el usuario
eligió, `frontend/src/pages/Goals.jsx:252`, `:264`) y **con** aportes mensuales
(`requiredMonthly`, `:261`); tiene además su propia "tasa requerida sin aportes"
`(target/current)^(1/años) − 1` (`:266-268`). El `GoalDiagnostic` de abajo (`frontend/src/pages/Goals.jsx:427`, `:436`)
proyecta con el CAGR histórico y **sin** aportes. Los dos van en la misma tarjeta.

`[V]` **`_months_between` ignora el día, y el frontend no.** El backend hace
`(td.year−now.year)·12 + (td.month−now.month)` (`backend/goals_diagnostic.py:92`); el frontend hace
`round(días / 30.4375)` (`frontend/src/pages/Goals.jsx:255`). Para una fecha a fin de mes los dos dan números distintos:
un objetivo con fecha 30/09 consultado el 05/09 da `months_left = 0` en el backend → rama "la fecha
objetivo ya llegó" (`:195-211`), y `1` en la card.

`[V]` `backend/ai/builders/goal.py:88-95` llama a `build_goal_diagnostic` **sin** `behavioral_cards`, así que
el packet de IA de Objetivos nunca trae `suggestion`.

---

## 7. `home/briefing.py` y `home/market.py`

### 7.1 `briefing.py` — "Lo que te afecta"

> Convención: `` `:1234` `` = **`backend/home/briefing.py`**.

`[V]` `build_personal_cards(conn, uid, all_quotes, portfolio_events)` (`backend/home/briefing.py:161-184`).
Devuelve hasta 8 `PersonalCard` (`:183`), en orden movers → earnings → dividendos.

| Detector | Línea | Umbral | Card |
|---|---|---|---|
| `detect_holdings_movers` | `:68-88` | `|change_pct| ≥ 1,5 %`, top 6 por magnitud | 🚀/📉 "{ASSET} subió/bajó hoy" + "US${price}" + CTA `/posiciones?asset=` |
| `detect_earnings_soon` | `:91-123` | `event_type == 'earnings'` de un holding, `hoy ≤ fecha ≤ hoy+7`; cap 2 | 📊 "Earnings de {TICKER}" + "hoy/mañana/en N días" |
| `detect_dividends_soon` | `:126-156` | `event_type == 'ex_dividend'`, misma ventana; cap 2 | 💰 "Dividendo de {TICKER}" |

`[V]` Holdings: `SUM(quantity) > 0` agrupado por activo, cross-broker, `is_cash = 0`
(`backend/home/briefing.py:43-50`). Si no hay holdings, devuelve `[]` y la sección no se renderiza (`:171-172`).

`[V]` Los quotes los arma el endpoint: `SELECT DISTINCT asset … AND asset NOT LIKE '%-%' LIMIT 100`
(`backend/main.py:34192-34197`) → `_fetch_batch_quotes` (`backend/main.py:34201`). Los eventos vienen de
`_get_portfolio_events_cached` (`backend/main.py:34220-34249`), ventana de 14 días sobre la tabla `events`.

`[V]` **Hallazgo — los CEDEARs no llegan a "Lo que te afecta".** El endpoint pide el quote con el
ticker crudo (`backend/main.py:34200`), no `.BA`. `_fetch_batch_quotes` sólo traduce cripto
(`backend/home/market.py:250-255`). Un `AAPL` en Cocos resuelve al precio del ticker US, no al del CEDEAR: el
`change_pct` es el de la acción en dólares, no el del papel que el usuario tiene. El módulo
`analysis_prep.fetch_ba_aware_prices` (`backend/analysis_prep.py:51-75`) existe justo para eso y el Home no
lo usa. `[I]` Además el `NOT LIKE '%-%'` filtra `BRK-B` y cualquier ticker con guion —
me agarro del literal SQL en `backend/main.py:34196`.

`[V]` **El `context` de un mover dice `US$` siempre** (`backend/home/briefing.py:84`), aunque el precio venga de
un `.BA` o de un ticker con precio en otra moneda.

### 7.2 `market.py` — índices, heatmap, movers

> Convención: `` `:1234` `` = **`backend/home/market.py`**.

`[V]` Datos estáticos hardcodeados: `SP500_TOP_50` (`:38-49`) + `SP500_META` con market caps
"Q1 2026" (`:55-81`), `MERVAL_TOP_25` (`:88-94`) + `MERVAL_META` (`:96-110`), `CRYPTO_TOP_30`
(`:114-121`) + `CRYPTO_META` (`:123-139`), `INDICES` de 6 símbolos (`:144-151`).
Los market caps son sólo peso visual del heatmap y se actualizan a mano (`:51-54`).

`[V]` Caché stale-while-revalidate `_cached(key, ttl_s)` (`:160-...`): fresco → directo; stale →
devuelve viejo y dispara refresh en background sobre `_swr_executor` (`:26`) con lock por key
(`:31-32`). TTLs: índices 900 s (`:375`), heatmap sp500/merval 1800 s (`:448`, `:451`), heatmap
crypto 900 s (`:454`), movers 1800/1800/900 (`:458`, `:461`, `:464`).

`[V]` Quotes: `_fetch_batch_quotes` (`:267-355`) — un `yf.download(period="5d")` para todo lo que no
esté en `_QUOTE_CACHE` (TTL 60 s, `:263-264`), con fallback individual `yf.Ticker.history` para lo
que el batch no devolvió (`:328-354`). Fórmula del día: `change_pct = (last/prev − 1) × 100` con
`prev`/`last` = los dos últimos `Close` no nulos (`:307-315`).

`[V]` `_build_heatmap` (`:402-422`) devuelve `{symbol, name, price, change_pct, market_cap}`;
`_build_movers` (`:425-444`) ordena por `change_pct` y toma top-5 y bottom-5.

`[V]` **Código muerto**: `_fetch_daily_quote` (`backend/home/market.py:214-233`) y `_invalidate_quote_cache`
(`backend/home/market.py:358-365`) no tienen ningún caller en el repo.

`[V]` **Hallazgo — "los movers del día" pueden ser de otro día.** `_fetch_batch_quotes` compara los
dos últimos cierres disponibles, sin verificar que el último sea de hoy (`:304-315`). Un lunes
feriado, o con el mercado AR cerrado y el US abierto, el heatmap del Merval muestra la variación del
viernes rotulada como "hoy" (el mismo `change_pct` alimenta `detect_holdings_movers`, que escribe
literalmente "subió hoy", `backend/home/briefing.py:81`).

---

## 8. ⚠️ Duplicación: la misma métrica calculada de más de una forma

### 8.1 Modified Dietz — dos primitivos

| Dónde | Línea | Fórmula | Piso |
|---|---|---|---|
| `twr.dietz` | `backend/twr.py:559-576` | `(v1−v0−flujo)/(v0+0,5·flujo)`, fracción | `max(..., −1.0)` |
| `builder._modified_dietz_pct` | `backend/reporting/builder.py:783-794` | idem × 100 | **ninguno** (`:788-789`: "NO clampa") |

`[V]` `backend/twr.py:571` justifica el piso ("no se puede perder más que todo"); el de Reportes lo omite a
propósito ("raro pero real para shorts/leverage"). Consecuencia: el mismo tramo puede publicar −150 %
en Reportes y −100 % en Métricas. `builder` sí importa `twr.leg_dudoso` para acotar
(`backend/reporting/builder.py:1370`, `:1588`), pero la acotación es un corte ("no publico"), no un piso.

`[V]` `builder._pct_en_pesos` (`:623-658`) sí reusa `twr._leg_en_moneda` y lo dice explícitamente
(`:639-641`): "Reimplementar esas dos líneas acá es exactamente cómo se desincronizan dos motores".
Es el único lugar del módulo que reusa el motor para la conversión.

### 8.2 Retorno anual — cinco caminos

| # | Dónde | Fórmula | Clamp | Anualiza |
|---|---|---|---|---|
| 1 | `twr.curva_indexada` (motor canónico) | encadena Dietz sobre bordes medidos | `dietz` piso −1; corta con `leg_dudoso` | sólo si la ventana ≥ medio año (`backend/main.py:15340-15343`) |
| 2 | `builder` año, rama motor | delega en (1) (`backend/reporting/builder.py:1234-1236`) y exige `_ventana_cubre` (`:1251-1253`) | el de (1) | no |
| 3 | `builder` año, composición contable | `Π(1 + dietz_mes)` sobre `monthly_entries` (`backend/reporting/builder.py:1305-1399`) | sin clamp; se apaga si `leg_dudoso` marca un mes (`:1368-1373`, `:1392-1398`) o hay agujero (`:1299-1305`) | no |
| 4 | `wrapped._twr_for_period` | `Π(1 + (cf−ci−flujo)/ci)` (`backend/wrapped.py:50-69`) | **`max(−0,95; min(5,0; ret))`** | no |
| 5 | `main._cagr_from_monthly_rows` | mismos factores que (4), `prod^(12/n) − 1` (`backend/main.py:15301-15317`) | mismo clamp | sí, siempre |

`[V]` (4) y (5) comparten el clamp `[−0,95; +5,0]`, que ningún otro motor tiene. (4) divide por `ci`
puro, no por el denominador de Dietz `ci + 0,5·flujo` — con un aporte grande a mitad de mes los dos
números difieren. (5) está declarado como fallback y su propio docstring admite que subestima
(`backend/main.py:15296-15298`), pero `_historical_cagr_global` ya no lo llama: hoy delega en (1)
(`backend/main.py:15345-15391`).

`[I]` Camino más probable de contradicción visible: el mismo año en `/wrapped` (motor 4) y en el
tab "Año" de Reportes (motor 2 o 3). Me agarro de que los dos leen `monthly_entries` broker='global'
del mismo usuario y aplican fórmulas distintas sin ninguna nota de reconciliación.

### 8.3 Win rate — tres definiciones

| Dónde | Línea | Denominador | `pnl` normalizado | Filtro de broker |
|---|---|---|---|---|
| Período (`PeriodMetrics.win_rate`) | `backend/reporting/builder.py:853-856` | trades con `pnl_usd` no nulo (los `pnl == 0` cuentan en el denominador y en ningún numerador) | sí (`realized_usd_sql`, `:239`) | sí |
| Histórico (para `WIN_RATE_UP/DOWN`) | `backend/reporting/timeline.py:61-77` | mismo criterio | **no** — `SELECT pnl_usd` crudo (`:64`) | **no** |
| Behavioral | `backend/behavioral.py:897-898` | `len(winners) + len(losers)` — los `pnl == 0` se excluyen | sí (`:1841-1844`) | n/a |

`[V]` `detect_win_rate_delta` (`backend/reporting/detectors.py:145-175`) compara el primero contra el segundo y publica
la diferencia en puntos como un hecho.

`[V]` `backend/realized_pnl.py:34-53` ya documenta el defecto de fondo bajo "Pendiente #1": los
cupones nunca son negativos y suman una "ganada" al numerador y al denominador de los tres. El propio
archivo nombra `reporting/timeline.py:61` y `behavioral.py detect_winrate_payoff` como afectados.

### 8.4 Concentración y cash — dos motores, dos umbrales, dos bases

| Métrica | Reportes | Comportamiento |
|---|---|---|
| Concentración | `detectors.detect_concentration_risk:31` — dispara ≥40 %, `warning` ≥60 %, mínimo US$100 | `behavioral.detect_concentration:969` — `high` ≥40 %, `medium` ≥25 % o top3 ≥70 % |
| Cash | `detectors.detect_large_cash_drag:216` — dispara ≥30 %, mínimo US$1.000, siempre `info` | `behavioral.detect_cash_drag:1163` — `high` ≥30 % o ARS ≥15 %, `medium` ≥20 %, `low` <5 % |
| **Base de valuación** | **costo** (`prices={}` en `backend/main.py:33123` y `:33198`) | **mercado** (`prices` de `currency_context`, `backend/main.py:13790`) |

`[V]` Los dos usan la misma función de valuación (`behavioral._position_value_usd`), lo que hace la
divergencia más difícil de ver: no es un motor distinto, es el mismo motor con la entrada vacía.

### 8.5 Benchmark vs S&P — dos resoluciones

`[V]` Reportes: serie **mensual** (`_fetch_sp500_monthly`, `backend/main.py:5337`), close-a-close de meses
(`backend/reporting/builder.py:764-773`), y `None` para cualquier período que no sea mes (`:760`).
`[V]` Métricas/Performance: serie **diaria** primero (`sp500_d`, `backend/main.py:5241`, `:5260`), recortada
punto a punto sobre la curva y sólo cae al mensual si el diario no cubre
(`backend/performance.py:202-218`).
`[V]` Wrapped: un tercer cálculo YTD hecho a mano en el endpoint —
`last_close_del_año / close_de_diciembre_anterior − 1` (`backend/main.py:13730-13738`).

Tres respuestas posibles a "¿cuánto hizo el S&P en el período?" para el mismo usuario.

### 8.6 Sesgo dominante — dos ranking

`[V]` `wrapped._slide_dominant_bias` (`backend/wrapped.py:272-311`) rankea
`high:4, medium:3, low:2, positive:1, neutral:0`, incluye `positive` y devuelve un slide "Operaste
con cabeza" cuando gana un positivo (`:285-299`).
`[V]` `goals_diagnostic._pick_dominant_bias` (`backend/goals_diagnostic.py:124-144`) rankea sólo
`high:4, medium:3, low:2`, y además exige que el `code` esté en `SUGGESTION_MAP` (`:137-139`).
Con las mismas 12 cards, los dos pueden elegir sesgos distintos.

---

## 9. Otros hallazgos verificados

`[V]` **9.1 — `realized_pnl` del período incluye conversiones.**
`fetch_operations_in_range` (`backend/reporting/builder.py:237-244`) trae TODAS las ops del rango sin filtrar
`op_type`, y `realized = sum(pnl_usd)` corre sobre esa lista completa (`backend/reporting/builder.py:842`). Las filas
`CONVERSION IMPORT X→Y` se insertan con `pnl_usd` no nulo
(`backend/importing/persister.py:1178-1187`). Resultado: el `realized_pnl` del reporte incluye el P&L
de conversiones, mientras `trades_count`, `win_rate` y `highlights` las excluyen
(`backend/reporting/builder.py:849-850`, `:1782-1783`). Y `compute_drivers` **también las incluye**
(`backend/reporting/builder.py:1684-1688`, sin filtro de `op_type`), así que el "activo motor del período" puede ser
un `USD→ARS` — que es el `asset` con el que se guarda la fila (`backend/importing/persister.py:1185`).
Nada de esto pasa por `realized_pnl.closed_filter_sql`, que existe justamente para eso
(`backend/realized_pnl.py:85-94`).

`[V]` **9.2 — `best_trade`/`worst_trade` del packet mensual de IA son SIEMPRE `null`.**
`backend/ai/builders/monthly.py:113` hace `highlights = full.get("highlights") or {}` y `:117`
`highlights.get(side) if isinstance(highlights, dict) else None`. Pero `report_to_dict` serializa
`PeriodReport.highlights`, que es una **lista** (`backend/reporting/schema.py:128`), así que el `isinstance` es siempre
falso. Y aunque fuera dict, el shape que espera (`asset`, `pnl_usd`, `pnl_pct`, `:120-123`) no existe
en `Highlight`, que tiene `kind`, `icon`, `label`, `value_label`, `context` (`backend/reporting/schema.py:27-34`).
Los campos se publican igual en el packet (`backend/ai/builders/monthly.py:198-199`) y están documentados
para el LLM (`:157-158`) como si trajeran datos.

`[V]` **9.3 — `HIGH_TURNOVER` compara dos universos distintos.** El numerador
(`report.metrics.trades_count`) exige `pnl_usd` no nulo y respeta el filtro de broker
(`backend/reporting/builder.py:853`). El denominador (`_compute_avg_trades_per_month`, `backend/reporting/timeline.py:80-93`) cuenta
`COUNT(*)` sin exigir `pnl_usd` y **sin filtro de broker**. Con un filtro de broker activo, el
detector compara los trades de ese broker contra el promedio global del usuario. Lo mismo aplica a
`historical_win_rate` (`backend/reporting/timeline.py:61-77`).

`[V]` **9.4 — `contribution_pct` no es "% de la ganancia".** Es
`|pnl| / Σ|pnl| × 100` (`backend/reporting/builder.py:1691`, `:1697`). Pero `detect_driver_of_period` lo narra como
*"{ASSET} explicó el X% de la ganancia (US$Y)"* (`backend/reporting/detectors.py:83-86`) y `generate_headline` como
*"explicó el X% del rendimiento"* (`backend/reporting/builder.py:1912`). En un mes con +100 y −100 en dos activos, cada
uno "explica el 50 % de la ganancia" de un P&L neto de cero.

`[V]` **9.5 — `vs_inflation_pct` mezcla monedas.** Se calcula como `delta_pct − inflación_AR`
(`backend/reporting/builder.py:1647`) sin mirar `moneda`. Con `moneda=usd` (el default) se le resta al retorno en
dólares la inflación en pesos. Igual `vs_sp500_pct` con `moneda=ars`: el retorno viene en pesos
(`:1499-1500`) y el S&P sigue en dólares. Los dos se renderizan como celdas del card
(`frontend/src/components/reports/MonthCard.jsx:229-233`).

`[V]` **9.6 — Formato de miles inconsistente en la misma tarjeta.** `generate_headline` y
`generate_narrative` hacen `.replace(",", ".")` para el formato AR (`backend/reporting/builder.py:1871`, `:1990`,
`:2013`…). `compute_highlights` (`backend/reporting/builder.py:1795`, `:1803`) y todos los `body` de `detectors.py`
(p. ej. `:85`, `:233`, `:378`) usan `{:,.0f}` sin reemplazo. En una misma tarjeta conviven
"US$ 1.234" (narrativa) y "US$1,234" (highlight/chip).

`[V]` **9.7 — Tres relojes distintos.** `builder.is_period_current` y `_hoy_iso` usan
`datetime.utcnow()` (`backend/reporting/builder.py:94`, `:512`); `timeline._months_back` y
`_compute_avg_trades_per_month` usan `date.today()` local (`backend/reporting/timeline.py:24`, `:82`);
`briefing.detect_earnings_soon`/`detect_dividends_soon` también `date.today()`
(`backend/home/briefing.py:95`, `:133`). El comentario de `backend/reporting/builder.py:91-93` explica por qué eligió UTC ahí, pero
el timeline que lo llama arranca en local.

`[V]` **9.8 — `generate_narrative` recibe dos parámetros que no usa.** `highlights` y `period_type`
(`backend/reporting/builder.py:1923`) no aparecen en el cuerpo (`:1925-2048`). El caller se los pasa igual
(`backend/reporting/builder.py:2109`).

`[V]` **9.9 — El endpoint de detalle usa un `live_value` distinto al del timeline.** El timeline
calcula `compute_live_portfolio_value` y sólo cae al snapshot si falla (`backend/main.py:33113-33119`); el
detalle arranca con `_latest_snapshot_value` y sólo lo pisa con el live si el período es el actual
(`backend/main.py:33164-33182`). `[I]` Para el mes en curso los dos convergen; para un mes cerrado el detalle
pasa un `live_value` que el builder ignora (la rama de mes cerrado no lo lee, `backend/reporting/builder.py:1016-1089`),
así que no muerde — me agarro de la estructura del `if/elif/else` de esas ramas.

`[V]` **9.10 — El packet mensual de IA ignora `modo`/`moneda`.** `backend/ai/builders/monthly.py:104-107`
llama a `build_period_report` sin esos dos argumentos → siempre `certero`/`usd`, aunque el usuario
esté mirando la pantalla en pesos y en estimado.

`[V]` **9.11 — Citas cruzadas desactualizadas en los comentarios.**
`backend/realized_pnl.py:48` dice "reporting/builder.py:255 wins/losses del período" — la línea 255
está adentro de `fetch_snapshots_in_range`; el código real está en `backend/reporting/builder.py:853-856`.
`backend/ai/builders/monthly.py:70-71` dice "compute_drivers (reporting/builder.py:355)" —
`compute_drivers` está en `backend/reporting/builder.py:1681`.

---

## 10. Código muerto / sin callers

`[V]` Verificado con grep sobre `backend/` + `frontend/src/`:

| Símbolo | Ubicación | Estado |
|---|---|---|
| `fetch_snapshots_in_range` | `backend/reporting/builder.py:248` | 0 callers (sólo su propia definición) |
| `import math` | `backend/reporting/builder.py:15` | `math` no aparece más en el archivo |
| `Insight` (import) | `backend/reporting/builder.py:26` | importado y nunca usado — los insights los arma `detectors.py` |
| `highlights` (parámetro) | `backend/reporting/builder.py:1923` | recibido y nunca leído |
| `period_type` (parámetro) | `backend/reporting/builder.py:1924` | recibido y nunca leído |
| `_fetch_daily_quote` | `backend/home/market.py:214` | 0 callers — lo reemplazó `_fetch_batch_quotes` |
| `_invalidate_quote_cache` | `backend/home/market.py:358` | 0 callers |
| `merval_ytd` | `backend/wrapped.py:321`, `:334-341`, `:355-356` | el endpoint nunca lo puebla (`backend/main.py:13725-13740`) |
| `monthly_contribution` | `backend/ai/builders/goal.py:35`, `:128` | la tabla `goals` no tiene esa columna |
| `_trade()` → `best_trade`/`worst_trade` | `backend/ai/builders/monthly.py:116-127`, `:198-199` | siempre `None` por el `isinstance(highlights, dict)` (ver 9.2) |
| Ruta `/wrapped` | `frontend/src/App.jsx:224` | sin ningún link entrante en la app |

---

## 11. Lo que no encontré

- **Gate estacional de Wrapped**: no encontrado. Ni en `backend/main.py:13682-13757` ni en
  `frontend/src/pages/Wrapped.jsx`. La guía lo promete (`frontend/src/pages/guia/InsightsYReportes.jsx:284`).
- **Gate de plan en `/api/behavioral/insights`, `/api/wrapped/{year}` y `/api/reports/timeline`**:
  no encontrado. El único corte por plan que vi es de frontend
  (`frontend/src/pages/Behavioral.jsx:661`, `frontend/src/pages/Reports.jsx:221`).
- **Benchmark sub-mensual en Reportes**: no existe — `benchmark_return_for_period` corta explícito
  (`backend/reporting/builder.py:760-761`).
- **Serie MERVAL en el backend**: no encontrada más allá del símbolo `^MERV` del strip
  (`home/market.py:147`) y el heatmap. `wrapped` la espera pero nadie la produce.
- **Un lugar único donde se defina "retorno del período"**: no existe. Es la duplicación de la
  sección 8.
- **`monthly_contribution` en el esquema de `goals`**: no encontrado (`.schema goals` y
  `backend/schema_pg.sql:929-937`).
