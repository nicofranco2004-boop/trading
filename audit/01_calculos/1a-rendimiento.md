# 1A — Veredicto: Rendimiento / retorno (simple, TWR, anualizado, CAGR)

**Grupo:** Rendimiento / retorno · 9 divergencias (DIV-092–DIV-100)
**Commit auditado:** `b74f450f2badf1a2b84e657551115a0595110e45` (copia de solo lectura `/tmp/rendi-main`, `backend/main.py` = 38.029 líneas ✅)
**Citas verificadas:** 31 de 33 correctas · 2 corregidas (+ 1 typo de path)
**Deriva `82fad6a0`:** ninguno de los hallazgos cae en `backend/pricing/fci.py`, `frontend/src/components/AddPositionFlow.jsx` ni `backend/tests/test_fci_uala.py`. No hay nada "posiblemente ya corregido".

---

## Resumen ejecutivo

El motor canónico (`backend/twr.py`) está bien construido, documentado y guardado: Modified Dietz con piso de −100 %, cota de salto ×3, corte por desborde del denominador, y la regla de oro "bajo medio año, anualizar es propaganda". El problema no es el motor: es que **cinco superficies del producto no lo usan y publican otro número con el mismo rótulo**.

Lo concreto que el usuario ve mal, hoy:

1. **El slide del Wrapped que se comparte como imagen** (`/wrapped`) dice literalmente «Tu rendimiento TWR de {year}» sobre un número que **no es TWR**: divide por `capital_inicio` en vez de `capital_inicio + 0,5·flujos`. Con la cuenta del test canónico (ci=1000, cf=2100, dep=1000) el motor da **+6,67 %** y el slide dice **+10,0 %**. Compuesto doce meses: **+115,7 % vs +213,8 %**. Y los tres packets de IA que alimentan el chat (`insights`, `insights.evolution`, `reports`) tienen exactamente la misma fórmula.
2. **El mismo día, la misma cuenta, dos pantallas se contradicen sobre si se puede anualizar**: el Diagnóstico (`/analisis?tab=diagnostico`) publica «Tu CAGR anualizado es +74,9 %» con 3 meses de historia, mientras el Dashboard y Objetivos —que leen el motor canónico— se niegan a anualizar y muestran el acumulado. Es el mismo defecto que ya produjo el +16.841 % anual documentado en `_historical_cagr_global`, sobreviviendo en el frontend.
3. **La curva "en pesos" de Insights inventa aportes del tamaño de la devaluación.** `evolution.js:571` convierte el STOCK acumulado (`net_deposited`) a pesos en cada punta y resta — exactamente lo que el docstring de `twr.py:692-698` prohíbe por escrito. Con 1.000 USD aportados, FX 500→1.500 y la cartera quieta en 1.200 USD, la línea correcta marca **+200 %** y ésta marca **+18,2 %**.
4. **El asesor tiene cuatro retornos distintos para el mismo cliente**, y el único sellado y auditado (`/api/advisor/twr`) **no lo consume ninguna pantalla**. Peor: el filtro `_es_base_de_mercado` que se agregó para que un cliente no aparezca con "+39,6 %" cuando su propia pantalla dice "—" se aplicó en `main.py:37073` (dashboard) y **no** en `main.py:35516` (contexto del chat del libro). El mismo bug, arreglado en un lado.
5. **El veredicto "¿le ganás a la inflación?" se calcula dos veces en la misma pantalla con números distintos** (`Insights.jsx:2281` vs `:2595`), y la segunda versión sólo cubre los brokers en pesos.

Nada de esto es cosmético salvo DIV-095, que es un problema de rotulado (dos preguntas legítimas presentadas como si fueran la misma).

---

## Tabla de veredictos

| DIV | versiones | ¿difieren de verdad? | cuál es la correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---:|---|---|---|---|---|
| DIV-092 | 5 (+1 ya migrada) | **SÍ** — +10,0 % vs +6,67 % en un mes; +213,8 % vs +115,7 % en doce | `twr.dietz` / `twr.curva_indexada` | `/wrapped` (slide compartible «Tu rendimiento TWR»), chat IA de Insights, Insights→Evolución y Reportes | 🔴 | migración a medio hacer (`insights_benchmarks` sí, los otros cuatro no) |
| DIV-093 | 2 | **SÍ** — un depósito del 30 % del capital publica ese 30 % como "TWR" | `twr.curva_indexada` sobre la ventana de 30 d | packet del chat IA del Dashboard; brief diario del asesor (email) | 🟠 | falta de capa compartida + rótulo mentiroso ("TWR" a una resta de valores) |
| DIV-094 | 3 | **SÍ** — +74,9 % anual en una tab vs "no se anualiza" en otra, mismo día | B1 `twr.py:2164-2172` (piso de medio año sobre DÍAS) | Diagnóstico (`/analisis?tab=diagnostico`, card `metric_cagr`) | 🔴 | fix aplicado sólo en el backend; el frontend conservó su motor |
| DIV-095 | 2 | Los números difieren pero **cada uno responde otra pregunta**; el defecto es el rótulo (+ falta el guard de denominador peak) | ambas, con etiqueta explícita; el guard peak falta en "Total" | `/dashboard` (strip "Total" vs "Anual") | 🟡 | frontend recalculando lo que el backend ya calcula, sin nomenclatura común |
| DIV-096 | 2 | **SÍ** — +18,2 % vs +200 % con FX 500→1.500 | `twr._leg_en_moneda` (stock a su TC, flujo al TC medio geométrico) | Insights → curva de evolución diaria en pesos | 🔴 | copiar y pegar la rama USD y "convertir todo" por simetría; el comentario de :560-562 documenta la premisa falsa |
| DIV-097 | 2 con guards / 8 sin | **SÍ** — sin `leg_dudoso` vuelven el ×5 fantasma y el desborde (+4.439 % en un leg, medido) | los guards de `twr.py` (612-647) | todas las de arriba + `_snapshot_delta` (chips Δ1d/7d/30d) | 🔴 | los guards nacieron dentro del motor; no hay barrera que impida calcular retorno fuera de él |
| DIV-098 | 2 | **SÍ** — una usa `perf.twr` (toda la cartera, motor canónico) y la otra un índice viejo sólo de brokers ARS | `perf.twr` del motor | Insights: la card "Expectativa de retorno" y el veredicto "Inflación" del comparativo | 🟠 | un fix aplicado en un solo call site de la misma pantalla |
| DIV-099 | 4 | **SÍ** — el sellado no se muestra; el del chat no filtra base de mercado y el del dashboard sí | `advisor_twr.twr_por_cliente` (sellado, con cobertura) | Dashboard del asesor (Mejor/Peor), chat del libro, informe firmado, email diario | 🔴 | un fix aplicado en un solo lugar (`_es_base_de_mercado`) + motor correcto sin consumidor |
| DIV-100 | 5 | **SÍ** — el "big withdraw" y el "import inicial" son heurísticas que ningún otro motor aplica | `twr.dietz` como primitivo único | Insights, Dashboard, Reportes, `/mensual`, teaser del Dashboard | 🟠 | copiar y pegar + parches locales que nunca volvieron a la capa común |

---

## Detalle por divergencia

---

### DIV-092 — Cuatro superficies llaman "TWR" a una cuenta que divide por el capital de inicio

**Estado de las citas:** ⚠️ 5 de 6 exactas. `backend/tests/test_cagr_snapshots.py:63` → la línea real es **:62** (`# r_mes = (2100-1000-1000)/(1000+0.5*1000) = 100/1500 = 6.67% → no +110%`). El resto ✅.

#### a. Implementaciones

**(1) `backend/ai/builders/insights.py:259`** — packet `insights` del chat IA:
```python
ci = float(r["capital_inicio"] or 0); cf = float(r["capital_final"] or 0)
dep = float(r["deposits"] or 0);      wd = float(r["withdrawals"] or 0)
denom = ci
if denom <= 0: continue
ret = ((cf - dep + wd) / denom) - 1
if ret < -0.95 or ret > 5: continue        # ← DESCARTA el mes entero
compound *= (1 + ret)
```

**(2) `backend/ai/builders/insights_evolution.py:59`** — packet `insights.evolution` (consumido desde `Insights.jsx:2966`). Byte por byte lo mismo, con `ci` en vez de `denom`.

**(3) `backend/ai/builders/reports.py:75`** — packet `reports` (consumido desde `Reports.jsx:175`). Idéntico. Publica `twr_year_pct`.

**(4) `backend/wrapped.py:62`** — `_twr_for_period`, docstring «Time-weighted return geométrico»:
```python
ret = (cf - ci - net) / ci                 # net = deposits − withdrawals
ret = max(-0.95, min(5.0, ret))            # ← CLAMPEA (no descarta)
prod *= (1 + ret)
```
Alimenta `_slide_pnl` (`wrapped.py:150`), cuyo subtítulo es literalmente `f'Tu rendimiento TWR de {year}'`.

**(5) `backend/ai/builders/insights_benchmarks.py:54`** — el que **sí** se migró. Su docstring dice textual: «Este packet calculaba un TERCER rendimiento: la cadena contable de `monthly_entries` con los meses fuera de [−95 %, +500 %] descartados en silencio… Ahora sale de `performance.performance`, la MISMA fuente que el gráfico».

**(6) Referencia canónica — `backend/twr.py:559` (`dietz`)**, fijada en `backend/tests/test_cagr_snapshots.py:62`.

**Hallazgo extra no listado en el mapa:** `wrapped.py:_slide_best_month` (≈ l. 166) usa una **quinta** fórmula para elegir el "mejor mes": `ret = (pnl_realized + pnl_unrealized) / ci`, sin restar los flujos. Un mes con un depósito grande y P&L realizado grande puede ganar el slide sin haber rendido nada.

#### b. Fórmulas

| | fórmula | denominador | outliers |
|---|---|---|---|
| Canónica (`twr.dietz`) | `r = (V₁ − V₀ − F) / (V₀ + 0,5·F)` | capital medio expuesto | piso −100 %; sin techo; `leg_dudoso` corta el tramo |
| Packets (1)(2)(3) | `r = ((cf − dep + wd) / ci) − 1 ≡ (cf − ci − F) / ci` | capital de INICIO | mes fuera de [−0,95; 5] → **se salta** (equivale a afirmar r = 0) |
| Wrapped (4) | idéntica a la de los packets | capital de INICIO | mes fuera de rango → **se clampea al borde** |

donde `V₀ = capital_inicio`, `V₁ = capital_final`, `F = deposits − withdrawals`.

La distancia algebraica entre las dos es exacta:

    r_packet / r_canónico = (V₀ + 0,5·F) / V₀ = 1 + 0,5·F/V₀

Es decir: **el error es proporcional al ritmo de aportes**. Una cuenta que no aporta nada (F=0) da igual en los dos. Una cuenta que crece —la de un usuario activo, justo la que más mira el número— se infla sistemáticamente **para arriba**.

#### c. ¿Real o cosmética? — REAL

Ejemplo del test canónico (`test_cagr_snapshots.py:62`): `ci = 1000`, `dep = 1000`, `cf = 2100`.
- Canónica: `(2100 − 1000 − 1000) / (1000 + 500) = 100/1500 = **+6,67 %**`
- Packets/Wrapped: `(2100 − 1000)/1000 − 1 = **+10,00 %**`
- Distancia: **+3,33 pp en UN mes** (el packet reporta 1,5× el retorno real).

Compuesto sobre doce meses con el mismo patrón: `1,0667¹² − 1 = **+115,7 %**` vs `1,10¹² − 1 = **+213,8 %**`. **98 pp de aire** en el número que se comparte como imagen.

**Y hay un segundo error, más grande, encima del primero.** Los cinco sitios leen `monthly_entries` CRUDO. Para todo mes cerrado el backend fuerza `pnl_unrealized = 0` (`main.py:9728`, `main.py:11066`, y el docstring de `_cagr_from_monthly_rows` en `main.py:15296-15298` lo dice: «monthly_entries de meses cerrados está al COSTO → este path subestima el retorno»). Sustituyendo `cf = ci + F + pnl_realized`:

    r_packet   = pnl_realized / ci
    r_canónico = pnl_realized / (ci + 0,5·F)

O sea que lo que publican **no es rendimiento de mercado en absoluto: es P&L realizado sobre capital de inicio**. Una cartera que se duplicó sin vender nada marca ~0 %. El frontend resuelve esto con `applyMtmToMonthly` (`insightsModel.js:571+`), que re-ancla la cadena contra los snapshots; **ninguno de los cinco sitios de backend la tiene**.

Los dos errores van en direcciones opuestas y no se cancelan: el denominador infla, la base al costo desinfla. El resultado es un número sin signo predecible, presentado con dos decimales.

**El descarte silencioso es su propio bug.** `if ret < -0.95 or ret > 5: continue` no excluye el mes de la ventana — lo excluye de la **productoria**, que es afirmar que ese mes rindió exactamente 0 %. Si el mes malo era real (una devaluación, un crash cripto), el número publicado es el de una historia que no ocurrió. Wrapped al menos clampea, que es menos falso pero igual inventado.

#### d. Dictamen

**Ninguna de las cinco es correcta. La correcta es `twr.curva_indexada`** (vía `performance.performance`), que ya está escrita, testeada, con guards, y con la cobertura y la ventana pegadas al número. `insights_benchmarks.py` demuestra que la migración es factible: son ~15 líneas.

Mientras tanto, el rótulo debe cambiar hoy: llamar «TWR» a `(cf−ci−F)/ci` sobre una base al costo es una afirmación falsa en una imagen que el usuario comparte con terceros.

#### e. Qué ve mal el usuario y dónde

| superficie | ruta / endpoint | qué ve |
|---|---|---|
| Wrapped | `/wrapped` → `GET /api/wrapped/{year}` → `wrapped.build_wrapped` | Slide `pnl`: título = el % grande, subtítulo «Tu rendimiento TWR de {year}». **Exportable como PNG con `shareCard.js`.** |
| Chat IA de Insights | `/analisis?tab=diagnostico` → `POST /api/ai/analyze {screen:"insights"}` | El modelo razona sobre `twr_pct` del packet |
| Chat IA de Evolución | `Insights.jsx:2966`, topic `insights.evolution` | `twr_pct`, `monthly_returns`, `best_month`, `worst_month`, `consistency_pct` — todos de la misma cuenta |
| Chat IA de Reportes | `/analisis?tab=reportes` → `Reports.jsx:175`, `screen="reports"` | `twr_year_pct` — **y contradice al propio Reportes**, que sirve `/reports/period/...` calculado por `reporting/builder.py` CON los guards canónicos |

El caso de Reportes es el más grave del grupo después del Wrapped: en la misma pantalla, el número impreso sale del motor con guards y el número del que habla la IA sale de la cadena contable sin guards.

#### f. Causa raíz

**Migración a medio hacer.** `insights_benchmarks.py` fue migrado explícitamente por este motivo y lo documenta en su docstring. Los otros cuatro quedaron. No hubo barrido: se arregló el packet que produjo el reclamo (AUDIT_benchmark_2026-09-01 §2.6) y no se buscó el resto de los `((cf - dep + wd) / ci)`.

#### g. Fuente única de verdad

`backend/twr.py` (`curva_indexada` / `twr_de`), expuesto por `backend/performance.py:performance(conn, uid, data, modo=, moneda=)`.

**A eliminar:** los bloques de compounding de `insights.py:245-268`, `insights_evolution.py:44-71`, `reports.py:60-95`, y `wrapped._twr_for_period` completa. `wrapped._slide_best_month` debe pedirle los retornos mensuales al motor en lugar de derivarlos.

---

### DIV-093 — `twr_30d_pct` no es un TWR: es `(V₁−V₀)/V₀`, y viaja en el mismo packet que el TWR de verdad

**Estado de las citas:** ✅ verificadas (`dashboard.py:162`, `dashboard.py:171`, `advisor_brief.py:321`).

#### a. Implementaciones

**`backend/ai/builders/dashboard.py:158-163`:**
```python
in_window = [s for s in sorted_snaps if s["date"] >= cutoff]
if len(in_window) >= 2 and in_window[0]["total_value"]:
    start_val = float(in_window[0]["total_value"])
    end_val   = float(in_window[-1]["total_value"])
    if start_val > 0:
        twr_30d_pct  = (end_val - start_val) / start_val
        delta_30d_usd = end_val - start_val
```

**Catorce líneas abajo, `dashboard.py:170-171`:**
```python
from main import _historical_cagr_global
twr_lifetime_pct = _historical_cagr_global(conn, user_id).get("total_return")
```
`total_return` sale de `main.py:15380` = `round(c["twr"], 6)` — el motor canónico, en fracción. Las unidades coinciden (los dos son fracciones), así que **no hay bug de escala**; el problema es de metodología.

Los dos salen en el mismo dict (`dashboard.py:249-250`), bajo `"portfolio"`, con nombres hermanos. El prompt (`ai/prompts.py:render_dashboard_prompt`) le dice al modelo que el packet trae «valor actual, **TWR del período**» y le pide «Cómo se compara **el TWR** con el benchmark relevante».

**`backend/advisor_brief.py:321`** — mismo patrón en el email diario del asesor:
```python
per.append({"cid": cid, "label": labels.get(cid), "now": now_v,
            "delta": now_v - base, "pct": (now_v - base) / base * 100})
```
Aquí hay un atenuante real: la ventana es de **un día** y el query que la alimenta (`advisor_brief.py:286-311`) sí filtra por `snapshots.apto`, o sea exige base de mercado en la punta vieja. A un día, un aporte es raro, pero cuando ocurre entra entero como "rendimiento del día" del cliente y decide quién sale como «el mejor del día» y quién como «el que más cayó» en el email.

#### b. Fórmulas

- `twr_30d_pct = (V₁ − V₀) / V₀` — money-weighted crudo, **cero neutralización de flujos**, sin `leg_dudoso`, sin exigir que las dos puntas estén en la misma base de valuación.
- `twr_lifetime_pct = twr` de `curva_indexada` — Modified Dietz encadenado, con guards y ventana declarada.
- `advisor_brief.pct = (V_live − V_snapshot) / V_snapshot` — ídem, ventana 1 día, punta vieja filtrada por `apto`.

#### c. ¿Real o cosmética? — REAL

Cartera de US$10.000. Durante los 30 días el usuario deposita US$3.000 y el mercado no se mueve: `V₁ = 13.000`.
- `twr_30d_pct = 3.000/10.000 = **+30,0 %**`
- Canónico: `(13.000 − 10.000 − 3.000) / (10.000 + 1.500) = 0 / 11.500 = **0,0 %**`

Y el efecto se propaga: `dashboard.py:190-197` calcula `vs_sp500_30d_pp = twr_30d_pct − sp_30d_pct` y `vs_inflation_ar_30d_pp` con ese mismo valor. Con el ejemplo de arriba, el packet le dice al modelo que el usuario **le ganó al S&P por ~28 puntos porcentuales en un mes** porque depositó plata. El modelo lo dirá con toda confianza: es el único dato que tiene.

`dashboard.py:242-243` también dispara la anomalía `drawdown_30d_high` cuando `twr_30d_pct < -0.05`, así que un **retiro** del 5 % del capital se le reporta al modelo como un drawdown.

#### d. Dictamen

**La correcta es `twr_lifetime_pct`** (el motor). `twr_30d_pct` no debe existir con ese nombre: o se calcula con `curva_indexada` restringida a la ventana de 30 días, o se renombra a `valor_30d_delta_pct` y se documenta en el packet que **incluye flujos**, para que el prompt no le pida al modelo compararlo contra un benchmark.

Para `advisor_brief`, dada la ventana de un día, la solución mínima honesta es restar los flujos del día: `(V₁ − V₀ − F)/V₀`. `net_deposited` ya está en el snapshot base.

#### e. Qué ve mal el usuario y dónde

- **Chat IA del Dashboard** (`/dashboard` → `POST /api/ai/analyze {screen:"dashboard"}`): el modelo afirma rendimientos de 30 días y comparaciones contra S&P/inflación construidas sobre depósitos. No aparece impreso en pantalla — aparece en prosa, que es peor: nadie puede auditarlo.
- **Brief diario del asesor** (email, `advisor_brief.py`): ranking «Cómo cerraron tus clientes», con el mejor y el peor del día por `pct`.

#### f. Causa raíz

**Falta de capa compartida + rótulo heredado.** El packet se escribió antes de que `curva_indexada` existiera (el propio comentario de `dashboard.py:165-168` cuenta que `twr_lifetime_pct` "antes se computaba inline desde monthly_entries" y **fue migrado**). Se migró el de lifetime y se dejó el de 30 días, en el mismo bloque, sin tocar el nombre.

#### g. Fuente única de verdad

`twr.curva_indexada` con ventana parametrizable. Si el motor no soporta hoy "últimos N días", eso es lo que hay que agregar — no otro cálculo local. `advisor_brief` debería consumir el mismo primitivo `twr.dietz(v0, v1, flow)`.

---

### DIV-094 — Tres anualizaciones distintas; dos conviven en la misma pantalla y se contradicen

**Estado de las citas:** ✅ verificadas. `twr.py:2165-2172` → el bloque real es **2164-2172** (`cagr = None` en 2164; `años` en 2170, gate en 2171, `cagr` en 2172) — el rango del mapa lo cubre. `insightsMetrics.js:415` ✅, `:185` ✅, `:291` ✅, `diagnostics.js:851-854` ✅ (el generador `metric_cagr` empieza en 845), `Dashboard.jsx:683` ✅, `Goals.jsx:183` ✅.

#### a. Implementaciones

**B1 — `backend/twr.py:2164-2172`** (canónica, geométrica sobre DÍAS, piso de medio año):
```python
cagr = None
if publicable and legs > 0 and idx > 0 and ventana_desde:
    _c1 = ventana_hasta
    if curva and curva[-1]["date"] == "hoy":
        _c1 = _hoy_art()
    años = _dias(ventana_desde, _c1) / 365.25
    if años >= 0.5:                # bajo medio año, anualizar es propaganda
        cagr = idx ** (1.0 / años) - 1.0
```
El comentario de arriba (2160-2163) aclara además que el exponente va sobre **la ventana que el índice midió**, no sobre las fechas extremas de la curva, «que pueden ser tramos huérfanos».

**B2 — `frontend/src/utils/insightsMetrics.js:388-420`** (geométrica sobre MESES DE CALENDARIO, piso de 2 meses):
```python
export function computeCAGR(monthlyReturns) {
  if (!monthlyReturns || monthlyReturns.length < 2) return null
  const totalGrowth = returns.reduce((prod, r) => prod * (1 + r), 1) - 1
  ...
  const span = mesesEntre(monthlyReturns[0].key, monthlyReturns[at.length-1].key)
  const n = span || monthlyReturns.length
  const cagr = Math.pow(1 + totalGrowth, 12 / n) - 1
```
Justo es decir que esta función **ya recibió su propio fix** (el `span` en vez de `length`, documentado en 396-408: «un usuario que estuvo 12 meses afuera veía +26,8 % anual cuando su plata rindió +10,0 %»). El fix es correcto y no cierra el hueco de fondo: sigue sin piso temporal.

**B3 — `insightsMetrics.js:185` y `:291`** (aritmética `×12`):
```javascript
const returnAnnual = mean * 12          // :185, dentro de computeSharpe
const alphaAnnual  = alpha * 12         // :291, dentro de computeAlphaBeta
```

**Publicadores:**
- `frontend/src/utils/diagnostics.js:845-856`, generador `metric_cagr`:
  ```javascript
  if (!c || c.cagr == null || !isFinite(c.cagr) || (c.months || 0) < 2) return null
  return `Tu CAGR anualizado es **${...}%**. Es el ritmo de crecimiento compuesto de tu
  cartera proyectado a un año, sobre ${c.months} meses de historial.`
  ```
- `Dashboard.jsx:676-693` (B1, vía `GET /api/goals/cagr`)
- `Goals.jsx:183-206` (B1, mismo endpoint)

#### b. Fórmulas

| | fórmula | unidad del período | piso para publicar |
|---|---|---|---|
| B1 | `CAGR = (1+R)^(365,25/D) − 1` | días medidos por el índice | **D ≥ 182,6 días** (medio año) |
| B2 | `CAGR = (1+R)^(12/M) − 1` | meses de calendario entre la primera y la última clave | **M ≥ 2** |
| B3 | `R_anual = μ_mensual × 12` | meses con dato | 3 meses (`MIN_MONTHS_FOR_STATS`) |

#### c. ¿Real o cosmética? — REAL, y visible el mismo día en dos tabs

**Caso 1 — B1 vs B2.** Usuario con 3 meses de historia y +15 % acumulado (≈ 91 días):
- **B2 (Diagnóstico):** `1,15^(12/3) − 1 = 1,15⁴ − 1 = **+74,9 % anual**`
- **B1 (Dashboard / Objetivos):** `91/365,25 = 0,249 años < 0,5` → `cagr = None` → se muestra el **acumulado +15,0 % con la ventana al lado**

Mismo usuario, mismo día, dos tabs del mismo producto: uno publica +74,9 % anual, el otro dice explícitamente que anualizar eso «amplificaría el ruido hasta un número que no significa nada».

Con 2 meses y +15 %, B2 llega a `1,15⁶ − 1 = **+131,3 %**`. Con 2 meses y +40 % (perfectamente posible en cripto o post-devaluación): `1,4⁶ − 1 = **+652,6 %**`. Es la misma familia de números que produjo el +16.841 % documentado en `_historical_cagr_global` (`main.py:15325-15340`) y en `Goals.jsx:175-182` — el defecto fue erradicado del backend y **sigue vivo en el frontend**.

**Caso 2 — B2 vs B3, en la misma card grid.** Retornos mensuales `+10 %, −5 %, +10 %`:
- B2: `1,10 × 0,95 × 1,10 = 1,1495` → `^4 − 1 = **+74,6 %**` (card `metric_cagr`)
- B3: `μ = 0,05` → `× 12 = **+60,0 %**` (es el `returnAnnual` que va al numerador del Sharpe y se publica como `return_annual_pct` en el packet de IA, `Insights.jsx:2473`)

14,6 pp de diferencia entre dos "rendimientos anualizados" de la misma pantalla y de la misma serie de datos.

#### d. Dictamen

**B1 es la correcta**, por dos razones independientes:
1. El período se mide en **días reales**, no en meses de calendario. Un "mes" de `monthly_entries` puede cubrir 3 días de historia real (el mes de alta).
2. El **piso de medio año** es la única defensa contra la extrapolación. Sin él, la anualización es un amplificador de ruido, y el repo ya lo midió: 417 usuarios con 1-2 meses de historia leyendo un CAGR.

B3 (`×12`) es aceptable **sólo** dentro de Sharpe/alpha, donde es la convención de la industria. Su pecado es publicarse como `return_annual_pct` en el packet de IA junto al CAGR geométrico, sin distinguirlos.

**B2 debe morir** y `computeCAGR` debe leer `GET /api/goals/cagr`, que ya expone `cagr`, `total_return_pct`, `dias`, `months` y `reason`.

#### e. Qué ve mal el usuario y dónde

- **`/analisis?tab=diagnostico`**, card `metric_cagr`: «Tu CAGR anualizado es +74,9 %… sobre 3 meses de historial». Es gratuita (no premium), o sea que la ve todo el mundo.
- Ese mismo valor entra al packet de IA (`Insights.jsx:2470-2483`, `pro_metrics.return_annual_pct` desde B3), así que el chat también lo repite.
- `/dashboard` y `/posiciones?tab=objetivos` muestran B1, que para el mismo usuario devuelve `null` y publica el acumulado. La contradicción es visible sin salir de la app.

#### f. Causa raíz

**Un fix aplicado en un solo lugar.** El arreglo del "anualizar un mes" se hizo en el backend (`_historical_cagr_global` + `twr.py` + `Goals.jsx` como consumidor) y está documentado con la medición de producción. `insightsMetrics.computeCAGR` no estaba en la lista porque vive en el frontend y no comparte una línea de código con el motor.

#### g. Fuente única de verdad

`twr.curva_indexada` → `_historical_cagr_global` → `GET /api/goals/cagr?modo=&moneda=`. Ya existe, ya tiene los tres controles (modo, moneda, ventana), y ya devuelve `reason` cuando no publica.

**A eliminar:** `insightsMetrics.computeCAGR` completa. Los `×12` de Sharpe/alpha se quedan pero deben renombrarse (`returnAnnualLinear`) para que nadie los publique como "rendimiento anual".

---

### DIV-095 — El strip del Dashboard pone "Total" y "Anual" al lado sin decir que responden preguntas distintas (y "Total" no tiene el guard de denominador que sus tres primos sí tienen)

**Estado de las citas:** ✅ verificadas. `format.js:142` ✅ (`// Dashboard —que es toda la historia Y anualizado— y parecen contradecirse cuando`). `Dashboard.jsx:265-266` ✅. `Dashboard.jsx:683` ✅.

#### a. Implementaciones

**`Dashboard.jsx:265-266`** — el "Total":
```javascript
const totalReturnUsd = totalValue - netDeposited
const totalReturnPct = netDeposited > 0 ? totalReturnUsd / netDeposited : 0
```

**`Dashboard.jsx:676-693`** — el "Anual" (`cagrVar`), del motor canónico vía `/api/goals/cagr`, con la corrección de escala `/100` documentada in situ.

**`frontend/src/utils/format.js:135-141`** — el reconocimiento por escrito:
> «…por defecto son los últimos 12 meses y cambia en silencio con los tabs 1A/2A/5A/MAX. Sin el rótulo, ese número se compara mentalmente contra el "Rendimiento anual" del Dashboard —que es toda la historia Y anualizado— y **parecen contradecirse** cuando en realidad miden cosas distintas.»

#### b. Fórmulas

- **Total:** `R_total = (V_hoy − ND) / ND` — money-weighted, denominador = aportado neto acumulado. Responde «¿cuánto ganó la plata que puse?».
- **Anual:** `CAGR = (∏(1+rₜ))^(365,25/D) − 1` — time-weighted anualizado. Responde «¿a qué tasa rindió mi capital, sin contar cuándo aporté?».

#### c. ¿Real o cosmética? — Los números difieren, pero **ninguno está mal**: es un defecto de rotulado. Con una excepción real, que sí es un bug.

**Los números difieren, y mucho.** Usuario que aporta US$1.000 en enero, ese capital crece a US$1.400 en noviembre (+40 %), y en diciembre aporta otros US$1.000. Valor final US$2.400.
- **Total:** `(2400 − 2000)/2000 = **+20,0 %**`
- **Anual:** TWR = +40 % en ~11 meses → `1,40^(365,25/334) − 1 ≈ **+44,3 %**`

El strip muestra «Total +20,0 %» y «Anual +44,3 %» pegados. Los dos son correctos. El usuario que resta o compara saca una conclusión falsa. **Veredicto: cosmética/rotulado.**

**La excepción que sí es un bug:** `totalReturnPct` sólo se protege con `netDeposited > 0`. **No tiene el guard de denominador-peak** que sus tres implementaciones hermanas sí tienen:
- `main.py:37058-37064` (asesor): `base_nd = max(_max_nd, nd)` con mínimo de US$100 — el comentario explica que sin eso «un cliente que retiró casi todo dejaba nd chico y el % explotaba (+1000 % falso secuestrando el Mejor/Peor)»
- `Insights.jsx:651-655`: `safeDenom(netDep, peakDep)`
- `evolution.js:497-498`: `Math.max(baselineUsd, peakValueUsd * 0.8)`

Ejemplo: usuario que aportó US$100.000 en total, retiró US$99.000 para impuestos (`ND = 1.000`) y le quedan US$5.000 en cartera. El Dashboard publica en el hero **`(5.000 − 1.000)/1.000 = +400,0 %`**. Con la regla del asesor: `base_nd = max(100.000, 1.000) = 100.000` → **−95,0 %**. Un signo de diferencia y 495 pp.

#### d. Dictamen

- El par Total/Anual es legítimo. Lo que falta es **una nomenclatura que los distinga en la UI**: «Ganancia sobre lo aportado (desde el inicio)» vs «Tasa anual equivalente (ajustada por aportes)». El comentario de `format.js:135-141` ya diagnosticó el problema y la solución que se aplicó fue rotular la card de *Insights*, no las del Dashboard.
- El guard de denominador-peak **debe aplicarse** a `totalReturnPct`. Es la misma regla, escrita ya tres veces en el repo, ausente justo en el titular de la app.

#### e. Qué ve mal el usuario y dónde

`/dashboard`, strip de rendimiento: «Total» y «Anual». El "Anual" está bien. El "Total" está bien salvo para usuarios con retiros grandes, donde publica un porcentaje de tres o cuatro cifras. Notar que **`/dashboard` es la pantalla con más tráfico del producto** y este es su número más grande.

#### f. Causa raíz

**Frontend recalculando lo que el backend ya calcula, sin capa de nomenclatura.** El "Anual" fue migrado al motor y el "Total" quedó como un cálculo inline de dos líneas —tan trivial que nadie lo consideró un motor—. Por eso los guards que se le fueron agregando a los otros tres nunca llegaron acá.

#### g. Fuente única de verdad

El motor debería exponer AMBOS con nombres explícitos: `retorno_sobre_aportado` (con denominador peak) y `cagr` / `total_return`, sobre la misma ventana, en la misma respuesta de `/api/goals/cagr` o `/insights/performance`. El Dashboard debería consumir, no calcular.

---

### DIV-096 — La curva en pesos de Insights inventa un aporte del tamaño de la devaluación

**Estado de las citas:** ⚠️ 2 de 3 exactas. `evolution.js:571` ✅ (`const flowsArs = baselineArs - prevBaselineArs`). `evolution.js:560-562` ✅ (el comentario termina en 562). **`backend/twr.py:696-703` → la cita real es `twr.py:692-698`** (el bloque «⚠️ EL FLUJO SE CONVIERTE, EL STOCK NO» empieza en 692 y cierra en 698; 699 es el `"""` de cierre).

#### a. Implementaciones

**`frontend/src/utils/evolution.js:565-585`** (rama ARS de `buildEvolutionFromSnapshots`):
```javascript
const fx = lookupHistoricalDolar(bench, y, mo, tcValuacion)
const valueArs    = value * fx
const baselineArs = netDep * fx                    // ← netDep es un STOCK acumulado
...
const flowsArs   = baselineArs - prevBaselineArs   // :571
const pnlArs     = (valueArs - prevValueArs) - flowsArs
const flowRatioArs = prevValueArs > 0 ? Math.abs(flowsArs) / prevValueArs : 0
const isBigWithdrawArs = flowsArs < 0 && flowRatioArs > 0.3
const avgArs = isBigWithdrawArs ? prevValueArs : (prevValueArs + 0.5 * flowsArs)
const rRawArs = avgArs > 0 ? pnlArs / avgArs : 0
```

Y el comentario que lo precede, **`evolution.js:560-562`**:
> «ARS: convertir value e invested al fx del snapshot — la conversión afecta tanto numerador como denominador del period_return, así que **técnicamente el % se mantiene**; sin embargo lo replicamos por simetría.»

**Canónica — `backend/twr.py:699-704`** (`_leg_en_moneda`), con el docstring de 692-698 que prohíbe explícitamente lo de arriba:
```python
f0 = p0.get("fx"); f1 = p1.get("fx")
flow = p1["net_deposited"] - p0["net_deposited"]        # ← se resta EN DÓLARES
if not f0 or not f1:
    return v0, v1, flow
return v0 * f0, v1 * f1, flow * ((f0 * f1) ** 0.5)      # ← el flujo va al TC medio geométrico
```

#### b. Fórmulas

Con `nd` = net_deposited (stock, USD), `v` = total_value (USD), `f` = FX:

| | flujo del tramo, en pesos |
|---|---|
| `evolution.js:571` | `F_ars = nd₁·f₁ − nd₀·f₀` |
| `twr._leg_en_moneda` | `F_ars = (nd₁ − nd₀) · √(f₀·f₁)` |

La diferencia entre las dos es exactamente `nd₀·(f₁ − f₀)` más un término de segundo orden: **la revaluación en pesos de todo lo aportado en la vida del usuario, contabilizada como si hubiera entrado plata en este tramo**.

El comentario de :560-562 es **falso** para el código que tiene debajo. Sería cierto si numerador y denominador se multiplicaran por el mismo escalar. No pasa: `f₀` y `f₁` son distintos, y el flujo entra con un tratamiento que no es ni `f₀` ni `f₁`.

#### c. ¿Real o cosmética? — REAL, y del tamaño de la devaluación

Usuario con `nd = 1.000 USD` (sin aportes nuevos en el tramo), cartera quieta en `v = 1.200 USD`, FX de 500 → 1.500 (la devaluación argentina de un año típico):

| | cálculo | resultado |
|---|---|---|
| `prevValueArs` | 1.200 × 500 | 600.000 |
| `valueArs` | 1.200 × 1.500 | 1.800.000 |
| `flowsArs` (evolution.js) | 1.000×1.500 − 1.000×500 | **+1.000.000** ← aporte fantasma |
| `pnlArs` | (1.800.000 − 600.000) − 1.000.000 | 200.000 |
| `avgArs` | 600.000 + 0,5×1.000.000 | 1.100.000 |
| **`rArs`** | 200.000 / 1.100.000 | **+18,2 %** |

Canónico: `F_ars = (1.000 − 1.000) · √(500·1.500) = 0` → `r = (1.800.000 − 600.000 − 0)/600.000 = **+200,0 %**`.

**+18,2 % contra +200 %.** El número que se publica es menos de una décima parte del real, y el error se **compone** tramo a tramo (`cumArs *= (1 + rArs)`).

Nota adicional: el aporte fantasma de 1.000.000 sobre un `prevValueArs` de 600.000 da `flowRatioArs = 1,67`, o sea que la heurística `isBigWithdrawArs` se evalúa contra un número inventado (aquí no dispara porque el flujo es positivo; con una revaluación a la baja del peso — o con `nd` negativo — sí dispararía, cambiando el denominador por una razón que no existe).

#### d. Dictamen

**La correcta es `twr._leg_en_moneda`.** No es opinión: el motor midió las alternativas contra la copia de producción y lo dejó escrito en `twr.py:678-691` (distancia del TC medio geométrico vs aporte a su TC histórico). El docstring de 692-698 nombra el bug de `evolution.js:571` casi palabra por palabra, un año antes de esta auditoría.

#### e. Qué ve mal el usuario y dónde

`buildEvolutionFromSnapshots` se importa en **`frontend/src/pages/Insights.jsx:44`** y se usa en `Insights.jsx:579` (`const dailyEvo = buildEvolutionFromSnapshots(snapshots, globalMonthly, bench, tcValuacion)`). Es la **curva de evolución diaria** de `/analisis?tab=diagnostico`, en su versión en pesos.

O sea: cuando el usuario prende el toggle de moneda a Pesos, la línea acumulada de su cartera se le achata sistemáticamente en la magnitud de la devaluación. Es justo la moneda en la que un usuario argentino quiere ver que le ganó a algo.

#### f. Causa raíz

**Copiar y pegar la rama USD, con una premisa falsa escrita como justificación.** El comentario de :560-562 («técnicamente el % se mantiene… lo replicamos por simetría») revela el razonamiento: alguien concluyó que la conversión era neutra, no la verificó, y copió el bloque. La premisa es cierta sólo si se usa UN solo FX para todo el tramo — que es lo que no hace.

#### g. Fuente única de verdad

`twr._leg_en_moneda` + `twr.dietz`, expuestos por `/insights/performance?moneda=ars`. La pantalla **ya consume ese endpoint** (`Insights.jsx:349, 370`) para la curva del motor. `buildEvolutionFromSnapshots` es una segunda curva sobre los mismos snapshots.

**A eliminar:** la rama ARS completa de `buildEvolutionFromSnapshots` (`evolution.js:560-596`). Si la curva diaria del motor no cubre algún caso que ésta sí, la respuesta es extender el motor.

---

### DIV-097 — Los guards viven adentro del motor, y ocho lectores calculan retorno afuera

**Estado de las citas:** ✅ verificadas por barrido (`grep -rn "leg_dudoso\|SALTO_MAX_VECES\|DENOM_MIN_FRACCION" backend/`).

#### a. Dónde están los guards y dónde no

**Definidos en `backend/twr.py:610-647`:**
```python
SALTO_MAX_VECES = 3.0        # :612
SALTO_FLUJO_TOL = 0.10       # :613
DENOM_MIN_FRACCION = 0.25    # :620

def leg_dudoso(v0, v1, flow):                    # :623
    r = dietz(v0, v1, flow)
    if r is not None and r <= -1.0 + 1e-12:  return "desborde"
    denom = v0 + 0.5 * flow
    if v0 > 0 and (denom <= 0 or denom < DENOM_MIN_FRACCION * v0):  return "desborde"
    if v0 > 0 and v1 > 0 and abs(flow) < SALTO_FLUJO_TOL * max(v0, v1):
        ratio = v1 / v0
        if ratio > SALTO_MAX_VECES or ratio < 1.0 / SALTO_MAX_VECES:  return "salto"
    return None
```
Más el piso de medio año (`twr.py:2171`) y el corte por serie partida.

**Consumidores reales:** `twr.py` (:779, :1528, :1540, :1840), `reporting/builder.py` (:1370, :1588, :1594). `main.py:18051-18092` sólo los **expone como configuración**; `performance.py:281` sólo los **menciona en un comentario**.

**Sin ningún guard (verificado archivo por archivo):**

| lector | qué calcula | qué le falta |
|---|---|---|
| `backend/wrapped.py:62` | TWR del año del slide compartible | todo; sólo clamp [−0,95; 5] |
| `backend/ai/builders/insights.py:259` | `twr_pct` | todo; descarte silencioso |
| `backend/ai/builders/insights_evolution.py:59` | `twr_pct`, mejor/peor mes | ídem |
| `backend/ai/builders/reports.py:75` | `twr_year_pct` | ídem |
| `backend/ai/builders/dashboard.py:162` | `twr_30d_pct` | todo; ni siquiera resta flujos |
| `backend/advisor_brief.py:321` | % del día por cliente | `leg_dudoso`; sí filtra `apto` |
| `backend/main.py:32873` `_snapshot_delta` | chips Δ1d / Δ7d / Δ30d | `leg_dudoso`; acepta `INDETERMINADO` a propósito |
| `frontend/src/utils/evolution.js:536,573` | curva diaria USD y ARS | `leg_dudoso`; sólo piso −0,99 |
| `frontend/src/pages/Insights.jsx:675,702` | curva mensual USD y ARS | ídem |
| `frontend/src/hooks/useMonthlyData.js:379,438,616` | % mensual, mes vivo, YTD | `leg_dudoso`; sí tiene `esApto` y `baseIncomparable` |
| `frontend/src/utils/insightsModel.js:127,561` | índice mensual USD y ARS | sólo piso −0,99 |

#### b. Qué protege cada guard (y qué vuelve sin él)

Los tres guards están calibrados **con mediciones de producción documentadas en el propio código**:

- **`desborde` por piso de −1:** sin él, un leg toca −100 % y el índice queda en cero absorbente para siempre. `twr.py:602` cita `uid 513: 16 millones → 109 → −100 %`.
- **`desborde` por denominador (`DENOM_MIN_FRACCION`):** el retiro que achica `v0 + 0,5·F` hasta casi cero explota **para arriba**. `twr.py:616-619` cita `uid 50: 401 → 335 con un retiro de 770 → denominador US$16 → +4.439 % en un leg`. **El piso de −1 no lo ve.** Ninguno de los once lectores de arriba tiene este guard, y todos tienen el piso de −0,99/−1: creen estar protegidos y no lo están contra la mitad del problema.
- **`salto` (×3):** `twr.py:583-609` documenta la calibración sobre 480 usuarios (×2 corta 46 · ×3 corta 39 · ×5 deja pasar +367 % y +316 %). Sin él vuelven `uid 282: +25.757 %`.
- **Piso de medio año:** `main.py:15325-15340`, `uid 966: +16.841 % anual`.

#### c. ¿Real o cosmética? — REAL

El repo ya midió el daño en cada caso; no hace falta un ejemplo hipotético. Lo relevante es la **asimetría**: la misma cuenta, el mismo día, muestra un número guardado en Reportes y uno sin guardar en Insights, el Wrapped, el chat y el email del asesor.

#### d. Dictamen

Los guards de `twr.py` son correctos y están bien calibrados. El problema es **arquitectónico**: `dietz()` es público y no impone nada; `leg_dudoso()` es una función aparte que hay que acordarse de llamar. Con once lectores, alguien siempre se olvida.

**Lo que debería existir:** un primitivo que devuelva `(r, motivo)` y **no** un float pelado — que sea imposible obtener el retorno de un leg sin recibir al mismo tiempo la razón por la que no se puede publicar. Que `dietz()` siga existiendo para el que la necesite es fine; que sea el camino de menor resistencia es el bug.

#### e. Qué ve mal el usuario y dónde

Cualquiera de las superficies del cuadro. El caso más caro es el **informe firmado del asesor** (`main.py:35700`), donde el guard SÍ existe (`_cortes_adentro`, `main.py:35705-35712`) — o sea que ahí se aprendió la lección; y el **email diario** del mismo asesor (`advisor_brief.py:321`), donde no.

#### f. Causa raíz

**Los guards nacieron dentro del motor y no hay barrera que impida calcular retorno fuera de él.** Cada guard se agregó como respuesta a un incidente concreto, en el archivo donde el incidente se manifestó. Nunca hubo un barrido de "quién más divide dos valuaciones".

#### g. Fuente única de verdad

`twr.leg_dudoso` como parte inseparable del primitivo. En el frontend: no reimplementar — consumir `/insights/performance` y `/api/goals/cagr`, que ya devuelven `motivo`, `motivo_texto`, `cortes_dudosos`, `serie_partida` y `base_del_twr`.

---

### DIV-098 — El veredicto de inflación se calcula dos veces en la misma pantalla, con números distintos

**Estado de las citas:** ✅ verificadas (`Insights.jsx:2281` y `Insights.jsx:2595`). ⚠️ El mapa escribe el path como `frontend/src/pages/Insights.js`; el archivo real es **`Insights.jsx`**.

#### a. Implementaciones

**Versión A — `Insights.jsx:2276-2292`** (card "Expectativa de retorno"):
```javascript
const ret = (usaPerfEnPesos && perf?.twr != null)
  ? perf.twr * 100 : portfolioReturnArsPctRaw
const infl = inflationCumArsWindow?.cumPct
const realReturnPct = (ret != null && isFinite(ret) && infl != null)
  ? ((1 + ret / 100) / (1 + infl / 100) - 1) * 100
  : null
```
El comentario de :2277-2279 explica por qué: «Con la serie del motor, el retorno en pesos es el que publica el motor (`perf.twr`), no el del armado viejo: **si no, el veredicto compara contra la inflación un número que el gráfico de arriba no muestra**».

**Versión B — `Insights.jsx:2593-2603`** (item "Inflación" de `verdictItems`):
```javascript
pct: (portfolioReturnArsPctRaw != null && isFinite(portfolioReturnArsPctRaw) && inflationCumArsWindow?.cumPct != null)
  ? ((1 + portfolioReturnArsPctRaw / 100) / (1 + inflationCumArsWindow.cumPct / 100) - 1) * 100
  : null,
nota: `retorno real de tus brokers en pesos...`
```
**Siempre** `portfolioReturnArsPctRaw`. Nunca `perf.twr`.

**Qué es `portfolioReturnArsPctRaw`** (`Insights.jsx:914`, poblado en `:968` y `:1016`): el TWR acumulado de `benchSeriesArs`, un índice armado a mano en el frontend que:
- sólo recorre `arsMonthly`, o sea **únicamente los brokers cuya `currency` es ARS** (`Insights.jsx:918`: `if (arsBrokerNames.size === 0 ...) return []`);
- se arma leyendo `monthly` crudo y **nunca pasa por `applyMtmToMonthly`** — lo dice el comentario de `:975-985`, que además reconoce que «la línea USD se arregló y la ARS quedó al costo»;
- usa `monthlyReturnArs` (`insightsModel.js:551`) con la heurística `isImportInitial`, que el motor no tiene.

`perf.twr`, en cambio, sale de `GET /insights/performance` = `twr.curva_indexada` sobre **toda** la cartera, con guards.

#### b. Fórmulas

Las dos aplican la misma deflación de Fisher:

    R_real = (1 + R) / (1 + π) − 1

La diferencia está entera en `R`:
- **A:** `R = perf.twr × 100` (cartera completa, motor canónico) — **pero sólo si `usaPerfEnPesos`**, es decir `currency !== 'USD' && benchSeriesUsd.length > 0` (`Insights.jsx:1240`). Si no, cae a `portfolioReturnArsPctRaw`.
- **B:** `R = portfolioReturnArsPctRaw` siempre (sub-cartera ARS, motor viejo, base al costo).

#### c. ¿Real o cosmética? — REAL

Usuario con 60 % de su patrimonio en Balanz USD / Schwab y 40 % en un broker en pesos. En la ventana, la cartera completa rindió **+90 %** en pesos (`perf.twr = 0,90`), la pata ARS rindió **+35 %** (`portfolioReturnArsPctRaw = 35`), y la inflación acumulada fue **+60 %**.

- **A (card "Expectativa de retorno"):** `(1,90/1,60) − 1 = **+18,75 %** real` → «le ganaste a la inflación»
- **B (item "Inflación" del comparativo):** `(1,35/1,60) − 1 = **−15,63 %** real` → «no le ganaste a la inflación»

**Veredicto opuesto, en la misma pantalla, para el mismo usuario, sobre la misma ventana.** Y el segundo entra además al packet de IA (`Insights.jsx:2325`: `portfolioReturnArsPct: portfolioReturnArsPctRaw`), así que el chat argumenta con el número perdedor.

Hay un tercer sesgo apilado en B: como `arsMonthly` no pasa por `applyMtmToMonthly`, su retorno es **realizado-only** (todo mes cerrado tiene `pnl_unrealized = 0`). Contra una inflación medida a mercado, la comparación está estructuralmente inclinada en contra del usuario.

#### d. Dictamen

**La correcta es A, y sólo cuando `perf.twr` está disponible.** El motor mide toda la cartera, con guards, sobre una ventana declarada (`ventana_desde`/`ventana_hasta`) que se puede alinear con la de la inflación.

`portfolioReturnArsPctRaw` no debería usarse para ningún veredicto: mide una sub-cartera, con otra metodología, sobre otra ventana. Si se quiere conservar la pregunta «¿le ganó la pata en pesos a la inflación?», hay que rotularla así explícitamente — la `nota` del item B ya lo intenta («sólo cubre los brokers en pesos») pero el número grande que se lee es el `pct`, y la nota es letra chica.

#### e. Qué ve mal el usuario y dónde

`/analisis?tab=diagnostico` (Insights):
- Card **"Expectativa de retorno"** (perfil de inversor) — versión A.
- Bloque comparativo **`verdictItems` / `ArAlternativesVerdict`**, tercera celda **"Inflación"** — versión B.
- El chat IA de esa pantalla — versión B, vía `Insights.jsx:2325`.

Las dos primeras se renderizan en la misma vista scrolleable.

#### f. Causa raíz

**Un fix aplicado en un solo call site de la misma pantalla.** El comentario de `:2277-2279` documenta el fix («si no, el veredicto compara contra la inflación un número que el gráfico de arriba no muestra»). Se aplicó en `returnExpectationCard` y no en `verdictItems`, que está 300 líneas más abajo y usa la misma variable.

#### g. Fuente única de verdad

Una sola const en `Insights.jsx` — `retornoParaVeredicto` — derivada de `perf.twr` con su ventana, consumida por A, por B y por el packet de IA. `portfolioReturnArsPctRaw` y todo `benchSeriesArs` deberían salir de `/insights/performance?moneda=ars`, que ya existe y ya se llama (`Insights.jsx:370`).

---

### DIV-099 — El asesor tiene cuatro retornos para el mismo cliente, y el sellado no lo consume ninguna pantalla

**Estado de las citas:** ✅ verificadas (`advisor_twr.py:98`, `main.py:35700-35702`, `main.py:37080`, `main.py:35516`, `advisor_brief.py:321`). Precisión sobre «que nadie consume»: **el endpoint existe** (`main.py:33698 GET /api/advisor/twr`), pero `grep -rn "advisor/twr" frontend/src` no devuelve **ningún** resultado. La afirmación es correcta a nivel de producto: el número sellado no llega a ninguna pantalla.

#### a. Implementaciones

**(1) TWR sellado — `backend/advisor_twr.py:79-124`**, línea 98 = `r = twr.twr_de(conn, cid)`. Sella los meses cerrados (idempotente), exige `MESES_MINIMOS = 3`, y publica `twr`, `meses`, `desde`, `hasta`, `motivo`, `motivo_texto`, `meses_dudosos`, más `resumen.cobertura_pct`. Es, por lejos, la implementación más cuidada del grupo.
→ Expuesto en `GET /api/advisor/twr`. **Sin consumidor en el frontend.**

**(2) Dietz reimplementado a mano — informe firmado, `main.py:35698-35702`:**
```python
flows_usd  = round(nd1 - nd0, 2)
market_usd = round((v1 - v0) - flows_usd, 2)
dietz_base = v0 + flows_usd / 2.0
if dietz_base > 100:
    ret_pct = round(market_usd / dietz_base * 100, 2)
```
Tiene un guard propio (`_cortes_adentro`, `:35705-35712`) que anula el número si hay un corte dudoso dentro de la ventana, y una lógica de base cuidada (`base_note`: `stale` / `onboarding` / `dudosa`). Le falta `DENOM_MIN_FRACCION`: `dietz_base > 100` no es lo mismo que `dietz_base ≥ 0,25·v0`.

**(3) Total return vs aportado — dashboard del libro, `main.py:37073-37080`:**
```python
if not _es_base_de_mercado(r):          # :37073  ← el filtro
    continue
nd = float(r["net_deposited"] or 0)
base_nd = max(_max_nd.get(i, 0.0), nd)  # denominador PEAK
if base_nd >= 100:
    perf.append((i, (float(r["total_value"] or 0) - nd) / base_nd * 100))
```

**(3b) La MISMA cuenta, sin el filtro — contexto del chat del libro, `main.py:35513-35517`:**
```python
base_nd = max(_max_nd_chat.get(cid, 0.0), nd)
ret = (round((float(snap["total_value"]) - nd) / base_nd * 100, 1)
       if snap and base_nd >= 100 else None)
```
Tiene el denominador peak. **No tiene `_es_base_de_mercado`.**

**(4) Variación del día sin ajuste de flujos — `advisor_brief.py:321`** (ver DIV-093).

#### b. Fórmulas

| | fórmula | ventana | guards |
|---|---|---|---|
| (1) sellado | Modified Dietz encadenado sobre meses sellados | la que el motor declara | todos + `MESES_MINIMOS=3` + cobertura |
| (2) informe | `(V₁−V₀−F)/(V₀+0,5F)` | `base_date` → `as_of` | `_cortes_adentro`, base ≥ 100 |
| (3)/(3b) ranking y chat | `(V − ND)/max(ND_peak, ND)` | **ninguna** (es lifetime) | (3): base de mercado + peak · **(3b): sólo peak** |
| (4) brief | `(V_live − V_snap)/V_snap` | 1 día | `apto` en la punta vieja |

Notar que (3) ni siquiera es un retorno del mismo tipo: es **money-weighted lifetime sobre el aportado**, no time-weighted. Compararlo mentalmente con (1) o (2) no tiene sentido, y las cuatro se presentan al asesor como "el rendimiento del cliente".

#### c. ¿Real o cosmética? — REAL, y una de las dos diferencias es un bug puro

**Diferencia 1 — el filtro que falta en (3b). Es el bug.**
`main.py:37065-37071` documenta exactamente el incidente que el filtro vino a matar:
> «Con `latest[i]` sin filtrar, un cliente cuya última fila es la foto del import aparecía con "+39,6 %" mientras su propia pantalla decía "—": el mismo cliente, dos respuestas.»

El fix se aplicó en :37073. **La misma lectura, en `_advisor_book_chat_context` (:35513-35517), no lo tiene.** Y ese `ret_pct` viaja al prompt del chat del libro (el comentario de :37066-37069 dice que `ret_pct` «entra al prompt de la IA del libro… donde el prompt le ORDENA al modelo rankear clientes con él»).

Resultado hoy: el asesor abre el dashboard y el cliente X no aparece en Mejor/Peor (correctamente filtrado). Le pregunta al chat «¿quién rindió mejor?» y el chat le contesta X con +39,6 %. Mismo producto, misma sesión, mismo cliente.

**Diferencia 2 — metodología.** Cliente que aportó US$50.000 hace tres años, hoy vale US$65.000, con un aporte de US$10.000 el mes pasado:
- (3) ranking/chat: `(65.000 − 50.000)/50.000 = **+30,0 %**` (lifetime, money-weighted)
- (2) informe del período (último mes, `v0 = 54.000`, `F = 10.000`): `(65.000 − 54.000 − 10.000)/(54.000 + 5.000) = 1.000/59.000 = **+1,69 %**`
- (1) sellado: el TWR encadenado de los tres años, otra cosa distinta de las dos
- (4) brief: el % del día

Cuatro números para «¿cómo le fue a este cliente?», ninguno etiquetado con su ventana en la superficie donde se muestra.

#### d. Dictamen

**La correcta es (1), `advisor_twr.twr_por_cliente`**, y hay que consumirla. Es la que sella, la que exige cobertura, la que trae el motivo cuando no publica y la que ya está escrita.

(2) es defendible como **retorno del período** —es otra pregunta, legítima— pero debe salir del mismo primitivo (`twr.dietz` + `twr.leg_dudoso`) en vez de estar reimplementada, y le falta `DENOM_MIN_FRACCION`.

(3) es defendible como **"cuánto ganó sobre lo que puso"**, con esa etiqueta y no como "rendimiento". Su versión (3b) **es un bug y hay que aplicarle el mismo filtro que a (3)**.

#### e. Qué ve mal el usuario y dónde

| superficie | ruta / endpoint | número |
|---|---|---|
| Dashboard del asesor, card Mejor/Peor | `AdvisorDashboard.jsx:702` ← `GET /api/advisor/book` | (3), filtrado ✅ |
| Chat de la IA del libro | `POST /api/ai/chat` (book-mode) ← `_advisor_book_chat_context` | **(3b), SIN filtrar 🔴** — el modelo rankea clientes con él |
| Informe del período que el asesor firma | `main.py:35700` | (2) |
| Email diario del asesor | `advisor_brief.py:321` | (4), sin ajuste de flujos |
| — | `GET /api/advisor/twr` | (1), **sin consumidor** |

#### f. Causa raíz

Dos causas apiladas:
1. **Un fix aplicado en un solo lugar** (`_es_base_de_mercado` en :37073 y no en :35516). El propio código llama a esto «el barrido de la ronda 10» en el docstring de `_es_base_de_mercado` (`main.py:36760-36766`) y advierte que `_latest_snapshots` «elige por MAX(date) y no pregunta en qué BASE está la fila». El barrido cubrió `advisor_book` y no `_advisor_book_chat_context`.
2. **Motor correcto sin consumidor.** (1) se construyó como "Fase 1" del TWR del libro. La Fase 2 (el composite ponderado) nunca llegó, y mientras tanto las pantallas siguieron con lo que ya tenían.

#### g. Fuente única de verdad

`advisor_twr.twr_por_cliente` para el retorno del cliente; `twr.dietz` + `twr.leg_dudoso` para cualquier retorno de período. `_advisor_book_chat_context` y `advisor_book` deben leer **la misma función**, no dos copias de la misma query con un filtro de diferencia.

---

### DIV-100 — Cinco Modified Dietz, dos con heurísticas que ningún otro motor aplica

**Estado de las citas:** ✅ verificadas. `twr.py` → `dietz` en **:559**. `builder.py:790` ✅ (`avg = start_value + 0.5 * flows`, dentro de `_modified_dietz_pct` que empieza en :783). `evolution.js:536` ✅. `Insights.jsx:675` ✅. `insightsModel.js:127` ✅ (`: capInicio + 0.5 * net`, el bloque empieza en :124). `insightsModel.js:561` ✅ (`const avgArs = isImportInitial ? netArs : ciArs + 0.5 * netArs`). `useMonthlyData.js:379` ✅, `:438` ✅, `:616` ✅, `:703` ✅.

#### a. Implementaciones

**V1 — canónica, `backend/twr.py:559-577`:** `denom = v0 + 0.5*flow`; `if denom <= 0: return None`; `return max((v1-v0-flow)/denom, -1.0)`. Sin techo, con `leg_dudoso` al lado.

**V2 — Reportes, `backend/reporting/builder.py:783-793`:** misma fórmula, `× 100`, **sin clamp** — y lo declara: «NO clampa: si el portfolio cae −150 %, devolvemos −150 (raro pero real para shorts/leverage)». Sus llamadores sí aplican `leg_dudoso` (`builder.py:1370`, `:1588`).

**V3 — heurística "big withdraw", `evolution.js:535-536` + `Insights.jsx:674-675`:**
```javascript
const isBigWithdraw = flows < 0 && flowRatio > 0.3
const avgCap = isBigWithdraw ? prevValueUsd : (prevValueUsd + 0.5 * flows)
```

**V4 — heurística "import inicial", `insightsModel.js:124-127` + `:561` + `Insights.jsx:672-675`:**
```javascript
const isImportInitialMonth = isFirst && capInicio === 0 && net > 0
const avgCapital = isImportInitialMonth ? net : capInicio + 0.5 * net
```

**V5 — `useMonthlyData.js`**, tres denominadores + un chain-link:
- `:379` `const avgCapital = (startUsd || 0) + 0.5 * flows` (% del mes)
- `:438` `const avgMtm = mtmStart + 0.5 * flows` (mes en curso, re-anclado a snapshots aptos)
- `:616` `const avgCap = _start + 0.5 * flows` (mes más nuevo con valor live)
- `:703` `ytdPct = (cum - 1) * 100` sobre `∏(1 + deltaPct_mes/100)`

#### b. Fórmulas

Todas comparten `r = (V₁ − V₀ − F)/D`. La divergencia es `D` y el post-proceso:

| | D | piso | techo | `leg_dudoso` |
|---|---|---|---|---|
| V1 | `V₀ + 0,5F` | −100 % | — | **sí** |
| V2 | `V₀ + 0,5F` | — | — | sí (en el llamador) |
| V3 | `V₀` si `F < 0` y `\|F\|/V₀ > 0,3`; si no `V₀ + 0,5F` | −99 % | — | no |
| V4 | `F` si primer mes y `V₀ = 0` y `F > 0`; si no `V₀ + 0,5F` | −99 % | — | no |
| V5 | `V₀ + 0,5F` (con `V₀` re-anclado a snapshot apto) | — | — | no; pero `esApto` + `baseIncomparable` |

#### c. ¿Real o cosmética? — REAL. Las heurísticas cambian el signo y la magnitud.

**V3 vs V1 — el "big withdraw".** El comentario de `evolution.js:526-533` cuenta el caso: capital US$100.000, retiro de US$70.000, cierre de una posición con +US$20.000.
- V1: `20.000/(100.000 − 35.000) = 20.000/65.000 = **+30,8 %**`
- V3: `20.000/100.000 = **+20,0 %**`

Como se compone, la brecha crece. El comentario dice «la verdad operativa: ganó $20 sobre $100 ≈ +20 %», que es **una definición de retorno distinta** (retorno sobre capital inicial, no sobre capital medio expuesto). No es un bug de cálculo: es una segunda metodología, adoptada en un archivo, para un caso que el motor resuelve de otra forma — el motor **corta el leg** (`DENOM_MIN_FRACCION`: `65.000 ≥ 0,25 × 100.000`, así que aquí no cortaría; con un retiro de US$80.000 sí).

**V4 vs V1 — el "import inicial".** El propio comentario de `insightsModel.js:115-123` da el ejemplo: `cap = 0`, `dep = 123k`, `final = 111k`.
- V1: `(111 − 0 − 123)/61,5 = **−19,5 %**`
- V4: `(111 − 0 − 123)/123 = **−9,8 %**`

Casi el doble. V4 tiene razón en el fondo —un depósito de apertura no entró a mitad de mes— pero la solución correcta es **no medir ese mes** (el motor: `v0 = 0` → `denom = 0,5F`, y `leg_dudoso` con `v0 = 0` no puede medir un ratio; `builder.py:1573-1594` maneja ese caso explícitamente con una regla escrita). V4 lo mide igual, con otro denominador, y nadie más lo hace.

**Consecuencia observable:** la línea acumulada del **gráfico** de Insights (V3/V4) y el % del mes en **Reportes** (V2) sobre el mismo mes de la misma cuenta dan distinto. No hay ninguna pantalla que los muestre pegados, así que el usuario lo nota como «los números no me cierran entre pestañas», que es exactamente lo más difícil de reportar.

**V5 — nota de justicia.** Es la implementación **frontend mejor hecha** del grupo: re-ancla `V₀` a un snapshot `esApto` con `_BORDER_MAX_LAG_DAYS = 5` (el mismo número que el backend, y lo dice: «Mismo número a propósito: si se separan, uno de los dos está mal»), aplica `baseIncomparable`, y devuelve `null` con `sinBaseMedida` en vez de inventar. Su chain-link de YTD (`:703`) es metodológicamente correcto. Lo que le falta es `leg_dudoso`: un mes con un `deltaPct` de +400 % por una foto mala entra entero a la productoria del YTD.

#### d. Dictamen

**V1 es el primitivo.** V2 es V1 sin el clamp, con una justificación válida (shorts/leverage) — pero como sus llamadores sí aplican `leg_dudoso`, en la práctica converge; **es la única duplicación defendible del grupo**, y aun así debería ser `twr.dietz(clamp=False)`.

**V3 y V4 deben desaparecer.** Ninguna de las dos es una corrección: son metodologías alternativas para casos que el motor resuelve **no publicando**. Un caso raro se maneja negándose a medirlo, no cambiando el denominador en silencio — porque el usuario no puede distinguir un mes calculado con `V₀` de uno calculado con `V₀ + 0,5F`.

**V5 debe consumir el motor** en vez de reimplementarlo. Su trabajo real —elegir bordes aptos, decidir cuándo no hay número— ya está en `twr.bordes_medibles` y `reporting/builder.py`.

#### e. Qué ve mal el usuario y dónde

| versión | pantalla |
|---|---|
| V2 | `/analisis?tab=reportes` (números impresos) — **la referencia buena del frontend** |
| V3 | `/analisis?tab=diagnostico`, curva de evolución diaria (`buildEvolutionFromSnapshots`) |
| V4 | `/analisis?tab=diagnostico`, curva mensual USD y ARS (`insightsModel` + `Insights.jsx:675`) |
| V5 | `/mensual` (`MonthlySummary`), teaser del Dashboard (`MonthlyTeaser`, `Dashboard.jsx:1347`) — % del mes, mes en curso, YTD |

#### f. Causa raíz

**Copiar y pegar seguido de parches locales que nunca volvieron a la capa común.** La evidencia está en el propio código: `evolution.js:496-508` documenta que «acá vivía un segundo `(s.net_deposited > 0) ? ... : s.total_invested` — el mismo `> 0` de §4.4 que se arregló en `netDepositedOf` y que quedó vivo en esta línea», y cierra con: **«Dos copias de la misma regla en un archivo es el defecto de fondo de este proyecto»**. El diagnóstico ya está escrito por el propio autor. Lo que falta es aplicarlo entre archivos, no dentro de uno.

#### g. Fuente única de verdad

`twr.dietz` (con `leg_dudoso` acoplado) como único primitivo del backend, y **ninguno** en el frontend: las pantallas deben consumir `/insights/performance`, `/reports/period/...` y `/api/goals/cagr`, que ya publican curva, ventana, motivo y base.

**A eliminar:** `evolution.js` (bloques de retorno de :508-596), la curva mensual de `Insights.jsx:657-730`, `insightsModel.buildMonthlyIndex` y `monthlyReturnArs`, y los tres denominadores de `useMonthlyData.js`.

---

## Parches detectados

| ubicación | qué síntoma tapa | causa real | dónde más sigue rompiendo |
|---|---|---|---|
| `evolution.js:535-536` + `Insights.jsx:674-675` — `isBigWithdraw ? prevValueUsd : ...` | El spike del retiro grande: «papá retira $70k de $100k» → Dietz da +30,7 % y compone a +91 % | El denominador de Dietz se desploma cuando `F ≈ −V₀`. El motor lo trata como **`desborde` y corta el leg** (`DENOM_MIN_FRACCION = 0,25`) | Todo lector sin `DENOM_MIN_FRACCION`: `wrapped.py:62`, los 3 packets de IA, `_snapshot_delta`, `useMonthlyData:379/438/616`, `main.py:35700` (`dietz_base > 100` no es `≥ 0,25·v0`). El repo tiene la medición: `uid 50 → +4.439 % en un leg`, y el piso de −1 no lo ve |
| `insightsModel.js:124-127` + `:561` + `Insights.jsx:672` — `isImportInitial ? net : ...` | El primer mes de un import (`ci = 0`, `dep` grande) duplicaba la pérdida | Un mes con `V₀ = 0` **no tiene retorno medible**. La respuesta correcta es no publicarlo (lo que hace `builder.py:1573-1594`), no cambiar el denominador | La misma condición existe en la rama ARS (`insightsModel.js:561`) y en `Insights.jsx:954`. Toda cuenta importada arranca su curva con un mes calculado con otra fórmula que el resto, sin marca visible |
| `insights.py:260` / `insights_evolution.py:60` / `reports.py:76` — `if ret < -0.95 or ret > 5: continue` | Meses absurdos que rompían el compounding | Los datos rotos (foto al costo contra foto a mercado) no se arreglan salteando el mes: saltearlo **afirma que ese mes rindió 0 %** | El mismo patrón, con `clamp` en vez de `continue`, en `wrapped.py:63` y `main.py:15308` (`_cagr_from_monthly_rows`). El motor los trata como **corte de serie** y declara `serie_partida` |
| `dashboard.py:161-162` — `twr_30d_pct = (end_val − start_val)/start_val` | Que el packet no tuviera un "retorno del período" para el prompt | No había un motor con ventana parametrizable cuando se escribió | Se propaga a `vs_sp500_30d_pp`, `vs_inflation_ar_30d_pp` y a la anomalía `drawdown_30d_high`, todas en el mismo packet |
| `main.py:37073` — `if not _es_base_de_mercado(r): continue` | «un cliente aparecía con +39,6 % mientras su propia pantalla decía —» | `_latest_snapshots` elige por `MAX(date)` sin preguntar la base de la fila | **`main.py:35516`** (contexto del chat del libro) hace la misma lectura y **no tiene el filtro**. Es un PARCHE en el sentido literal: se arregló el call site que produjo el reclamo |
| `Dashboard.jsx:266` — `netDeposited > 0 ? ... : 0` | División por cero | El denominador correcto es `max(ND_peak, ND)`, ya escrito **tres veces** (`main.py:37059`, `Insights.jsx:653`, `evolution.js:497`) | El titular de `/dashboard`: con retiros grandes publica +400 % donde la regla del asesor daría −95 % |
| `Insights.jsx:2281` — `usaPerfEnPesos && perf?.twr != null ? perf.twr*100 : portfolioReturnArsPctRaw` | El veredicto de inflación comparaba contra un número que el gráfico no mostraba | Hay dos motores de retorno en pesos en la misma pantalla | `Insights.jsx:2595` (item "Inflación") y `Insights.jsx:2325` (packet de IA) siguen con el viejo |

---

## Citas del mapa incorrectas

| DIV | cita del mapa | ubicación real | qué decía mal |
|---|---|---|---|
| DIV-092 | `backend/tests/test_cagr_snapshots.py:63` | **`:62`** | Off-by-one. La línea 62 es `# r_mes = (2100-1000-1000)/(1000+0.5*1000) = 100/1500 = 6.67% → no +110%`; la 63 es `self.assertIsNone(r["cagr"])`. El contenido citado es correcto, la línea no. |
| DIV-096 | `backend/twr.py:696-703` | **`:692-698`** | El bloque «⚠️ EL FLUJO SE CONVIERTE, EL STOCK NO» del docstring de `_leg_en_moneda` va de 692 a 698 (699 cierra el docstring). Las líneas 699-704 son el **cuerpo** de la función, no el docstring. La cita apunta al lugar equivocado por ~4 líneas. |
| DIV-098 | `frontend/src/pages/Insights.js` | **`frontend/src/pages/Insights.jsx`** | Extensión errónea en la columna "sitios". Las líneas (2281, 2595) son correctas. |

**Verificadas y correctas (30):** `insights.py:259`, `insights_evolution.py:59`, `reports.py:75`, `wrapped.py:62`, `insights_benchmarks.py:54`, `dashboard.py:162`, `dashboard.py:171`, `advisor_brief.py:321`, `twr.py:2165-2172` (el bloque real es 2164-2172; el rango del mapa lo cubre), `insightsMetrics.js:415`, `insightsMetrics.js:185`, `insightsMetrics.js:291`, `diagnostics.js:851-854`, `Dashboard.jsx:683`, `Goals.jsx:183`, `format.js:142`, `Dashboard.jsx:265-266`, `evolution.js:571`, `evolution.js:560-562`, `Insights.jsx:2281`, `Insights.jsx:2595`, `Insights.jsx:675`, `advisor_twr.py:98`, `main.py:35700-35702`, `main.py:37080`, `main.py:35516`, `builder.py:790`, `evolution.js:536`, `insightsModel.js:127`, `insightsModel.js:561`, `useMonthlyData.js:379/438/616/703`.

**Afirmación del mapa que hay que matizar:** DIV-099 dice del TWR sellado «que nadie consume». El **endpoint sí existe** (`main.py:33698 GET /api/advisor/twr`); lo que no existe es un consumidor en `frontend/src` (`grep -rn "advisor/twr" frontend/src` → 0 resultados). La conclusión de producto del mapa es correcta.

---

## URGENTE

**1. `main.py:35516` — el chat del libro publica el retorno de clientes cuya última foto es el import.**

Es el único hallazgo del grupo que es un bug puro, de una línea, con el fix ya escrito catorce mil líneas más abajo en el mismo archivo, y con impacto en una superficie donde el asesor toma decisiones sobre plata de terceros. `main.py:37065-37071` documenta el síntoma exacto («un cliente cuya última fila es la foto del import aparecía con "+39,6 %" mientras su propia pantalla decía "—"»), el filtro se aplicó en `:37073`, y la misma lectura en `_advisor_book_chat_context` quedó sin él. El `ret_pct` resultante entra al prompt que **le ordena al modelo rankear clientes**. El asesor puede llamar a un cliente para felicitarlo por un rendimiento que es la brecha entre dos formas de valuar.

Recordatorio: **no toqué el código.** Esto es un reporte, no un fix.

**2. El slide del Wrapped dice «TWR» sobre un número que no lo es, y se exporta como imagen.**

No es urgente por magnitud del error (aunque es grande: +10,0 % donde el motor mide +6,67 %, y +213,8 % vs +115,7 % compuesto sobre doce meses) sino porque **sale de la app**: `shareCard.js` lo convierte en PNG y el usuario lo publica. Un porcentaje de rendimiento con el rótulo "TWR" en una imagen compartida por un usuario de un producto financiero argentino tiene un costo que no se recupera con un deploy. Si migrar el cálculo lleva tiempo, el rótulo se puede cambiar hoy.

---

## BLOQUE-RESUMEN

| concepto | DIV | versiones | difieren | correcta | pantalla que muestra mal | severidad | causa raíz |
|---|---|---:|---|---|---|---|---|
| Rendimiento / retorno | DIV-092 | 5 | SÍ — +10,0 % vs +6,67 % en un mes; +213,8 % vs +115,7 % en doce | `twr.dietz` / `twr.curva_indexada` | `/wrapped` (slide «Tu rendimiento TWR», exportable como PNG); chat IA de `/analisis?tab=diagnostico`, de la curva de evolución y de `?tab=reportes` | 🔴 alta | migración a medio hacer — `insights_benchmarks.py` se migró y los otros cuatro quedaron |
| Rendimiento / retorno | DIV-093 | 2 | SÍ — un depósito del 30 % del capital se publica como "TWR +30 %" | `twr.curva_indexada` sobre la ventana pedida | packet del chat IA de `/dashboard`; email diario del asesor (`advisor_brief`) | 🟠 media-alta | falta de capa compartida + rótulo heredado ("TWR" a `(V₁−V₀)/V₀`) |
| Rendimiento / retorno | DIV-094 | 3 | SÍ — +74,9 % anual en una tab vs "no se anualiza" en otra, mismo día y misma cuenta | B1 `twr.py:2164-2172` (geométrica sobre días, piso de medio año) | `/analisis?tab=diagnostico`, card `metric_cagr` (gratuita) | 🔴 alta | fix aplicado sólo en el backend; `insightsMetrics.computeCAGR` conservó su motor |
| Rendimiento / retorno | DIV-095 | 2 | Los números difieren (+20,0 % vs +44,3 %) pero responden preguntas distintas; el bug real es el denominador sin guard peak (+400 % vs −95 %) | ambas con etiqueta explícita; el denominador peak debe agregarse a "Total" | `/dashboard`, strip "Total" / "Anual" | 🟡 media | frontend recalculando lo que el backend ya calcula, sin nomenclatura común |
| Rendimiento / retorno | DIV-096 | 2 | SÍ — +18,2 % vs +200 % con FX 500→1.500 y cartera quieta | `twr._leg_en_moneda` (stock a su TC, flujo al TC medio geométrico) | `/analisis?tab=diagnostico`, curva de evolución diaria en pesos | 🔴 alta | copiar y pegar la rama USD con una premisa falsa escrita como justificación (`evolution.js:560-562`) |
| Rendimiento / retorno | DIV-097 | 2 con guards / 11 sin | SÍ — sin `DENOM_MIN_FRACCION` vuelve el +4.439 % en un leg; sin `SALTO_MAX_VECES` el +25.757 % | los guards de `twr.py:610-647` + el piso de medio año | todas las anteriores + chips Δ1d/Δ7d/Δ30d (`_snapshot_delta`) + email del asesor | 🔴 alta | los guards nacieron dentro del motor; nada impide calcular retorno afuera |
| Rendimiento / retorno | DIV-098 | 2 | SÍ — veredicto OPUESTO en la misma pantalla (+18,75 % real vs −15,63 % real) | `perf.twr` del motor (cartera completa, con guards) | `/analisis?tab=diagnostico`: card "Expectativa de retorno" vs celda "Inflación" del comparativo, + el packet de IA | 🟠 media-alta | un fix aplicado en un solo call site de la misma pantalla |
| Rendimiento / retorno | DIV-099 | 4 | SÍ — el sellado no se muestra; el del chat no filtra base de mercado y el del dashboard sí (+39,6 % vs "—") | `advisor_twr.twr_por_cliente` (sellado, con cobertura) | chat de la IA del libro (`main.py:35516`, sin filtro) 🔴; Mejor/Peor del dashboard del asesor; informe firmado; email diario | 🔴 alta | fix aplicado en un solo lugar (`_es_base_de_mercado`) + motor correcto sin consumidor (`/api/advisor/twr` no lo llama nadie) |
| Rendimiento / retorno | DIV-100 | 5 | SÍ — "big withdraw" +20,0 % vs +30,8 %; "import inicial" −9,8 % vs −19,5 % | `twr.dietz` como primitivo único (V2 defendible con `clamp=False`) | curvas de `/analisis?tab=diagnostico` (V3, V4); `/mensual` y el teaser del Dashboard (V5) | 🟠 media-alta | copiar y pegar + parches locales que nunca volvieron a la capa común (`evolution.js:506`: «dos copias de la misma regla es el defecto de fondo de este proyecto») |
