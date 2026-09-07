# 1B — Fechas, períodos y zonas horarias

Commit auditado: `b74f450f2badf1a2b84e657551115a0595110e45` (copia de solo lectura `/tmp/rendi-main`, verificada: `backend/main.py` = 38.029 líneas).
Deriva conocida: ningún hallazgo de este informe cae en `backend/pricing/fci.py`, `frontend/src/components/AddPositionFlow.jsx`, `backend/tests/test_fci_uala.py` ni `backend/snapshots_job.py`… **con una excepción: H-1 cae en `snapshots_job.py`. Ver la nota de "zona de trabajo activa" en su detalle.**

---

## Método

**Lo que ejecuté** (scripts en `/private/tmp/claude-501/…/scratchpad/`, fuera del repo; el backend se copió a un directorio propio para no ensuciar `/tmp/rendi-main` con `trading.db`):

| # | qué medí | cómo |
|---|---|---|
| **M1** | `snapshots_job.run_daily_snapshot` REAL, con el reloj congelado en 2026-09-05 02:59:00 UTC (= viernes 2026-09-04 23:59 ART, el instante exacto en que corre el cron), contra una sqlite con la tabla `users` vacía | `m1_fechas.py` — patch de `snapshots_job.datetime` |
| **M2** | los cinco helpers de "hoy" del backend (`twr._hoy_art`, `advisor_brief._today_art`, `advisor_alerts._today_art`, `reporting.builder._hoy_iso`) con el MISMO reloj | ídem |
| **M3** | `reporting.builder.is_period_current` en los tres bordes (día, mes, año) con relojes congelados | ídem |
| **M4** | `reporting.builder.parse_period_bounds` sobre 8 claves de período | ídem |
| **M5** | `reporting.builder.fetch_snapshot_at_or_before` + `_dia_anterior` REALES sobre una serie de snapshots armada con la etiqueta que produce el cron | `m5_borde.py` |
| **M6** | `reporting.timeline._weeks_in_month` y `_months_back` REALES, 5 meses distintos | `m6_semanas.py` |
| **M7** | `main._ytd_delta` REAL — la función se extrae **verbatim** de `main.py:32949-33037` (sin importar `main` entero) y se ejecuta contra una sqlite sintética | `m7_ytd.py` |
| **M8** | los 4 helpers de clave de período de `/reportes` (`todayIso`, `isoWeekKey`, `monthKey`, `yearKey`), extraídos **verbatim** con `sed` de `Reports.jsx:31-51`, con `TZ=America/Argentina/Buenos_Aires` y 5 relojes congelados | `js/m2_reports.js` (node 24) |
| **M9** | `utils/evolution.js::computeReturnDelta` REAL (módulo copiado tal cual) sobre una serie con hueco | `js/m3_estemes.mjs` |

**Lo que NO pude ejecutar:**
- No hay base de producción disponible, así que **ninguna magnitud de este informe es un conteo de usuarios reales**. Los escenarios de M5/M7/M9 son series sintéticas; lo medido es *el comportamiento de la función*, no su frecuencia.
- No pude verificar la variable `TZ` del contenedor de Railway. `railway.toml` y `nixpacks.toml` no la setean (verificado), y las imágenes de nixpacks default a UTC — pero es una **deducción**, y de ella dependen los 77 call sites de `date.today()`. Está en las preguntas.
- No pude verificar a qué hora UTC pega efectivamente el cron externo de cron-job.org. El scheduler interno sí está fijado (`CronTrigger(hour=2, minute=59)` con `BackgroundScheduler(timezone='UTC')`, `main.py:32095` y `:32536`).
- No corrí la suite de tests.

**Sobre el mapa:** usé sólo `grep` sobre `audit/00-mapa-sistema.md`. **El mapa ya tiene mi H-1 como hallazgo J-6** (línea 15823 y 16260) — le doy el crédito y aporto la medición, las consecuencias río abajo y una contradicción interna del propio mapa. También ya tenía "tres relojes" (14821) y `_weeks_in_month` (27588). Lo que sigue está señalado hallazgo por hallazgo.

---

## Preguntas que necesito que contestes

Sólo estas seis. El resto de `_preguntas/fechas.md` es ruido para mi tema o ya está contestado por el código.

1. **¿A qué hora UTC pega el cron externo de cron-job.org contra `/api/snapshots/run-cron`?** De eso depende el tamaño de H-1: si pega entre 00:00 y 02:59 UTC, TODA la serie de snapshots está fechada un día ART adelante. (El scheduler in-process ya está fijado a las 02:59 UTC, así que al menos por esa vía el desfasaje es seguro.)
2. **¿Está seteada la variable `TZ` en Railway?** Si no está (mi supuesto), `date.today()` = UTC en producción y = ART en tu Mac. Son 77 call sites que se comportan distinto en dev que en prod.
3. **Producto: "hoy" ¿es el día calendario argentino o el día UTC?** Hoy el código responde las dos cosas y las dos están escritas a propósito, con comentario: `main._iso_today()` dice ART ("target users son argentinos"), `sync_unrealized` dice "MES CALENDARIO ACTUAL (UTC)" en el docstring. Sin una decisión, cualquier arreglo mueve un número de un lado y lo rompe del otro.
4. **Si se arregla H-1, ¿qué se hace con las filas de `snapshots` ya escritas?** Re-etiquetarlas mueve TODA la serie histórica un día; no re-etiquetarlas deja la serie partida en dos convenciones en la fecha del deploy. (Y ojo con el orden: ver H-2, que hoy se está tapando con H-1.)
5. **¿La semana que `/reportes` anida bajo un mes tiene que cubrir ese mes?** Medido: bajo *septiembre 2026* las semanas empiezan el **7 de septiembre** — los días 1 al 6 no están en ninguna semana de septiembre; bajo *diciembre 2026* faltan los días 1 al 6 y sobra hasta el 3 de enero.
6. **¿Cuántas filas de `snapshots` tienen `source='browser'` con fecha posterior a que el cron entró en producción?** Si son ~0, eso confirma H-11 (la foto intradía del browser no llega nunca a escribirse porque el cron ya ocupó esa fecha).

---

## Resumen ejecutivo

**Hay tres calendarios corriendo al mismo tiempo en la misma app** — ART (`utcnow() − 3h`), UTC (`utcnow()`) y "hora local del proceso" (`date.today()`) en el backend; y en el frontend, UTC (`toISOString`) y hora local del navegador (`getFullYear/getMonth/getDate`). Ninguno de los cinco está mal en sí mismo. El problema es que **conviven dentro del mismo endpoint, del mismo archivo y hasta de la misma función**, y que varios de ellos llevan un comentario afirmando que están alineados con otro cuando no lo están.

Los tres resultados que más pesan:

1. **El cron sella cada snapshot con el día UTC, o sea un día ART adelante** (MEDIDO: `target_date = '2026-09-05'` corriendo a las 02:59 UTC del 5, que en Argentina es el viernes 4 a las 23:59). La rama que convierte a ART existe, está a 280 líneas de distancia y **nunca se ejecuta**. Esto ya está en el mapa como J-6; lo nuevo es que **el desfasaje llega a los bordes de período**: medido, el reporte de septiembre arranca en el cierre del 30 de agosto y **el reporte anual de 2026 cierra con la rueda del 30 de diciembre**. Y hay **tres comentarios en el código** (`advisor_book`, `advisor_brief`, `advisor_alerts`) que afirman textualmente "los snapshots se estampan con fecha ART" y construyen su lógica sobre esa premisa falsa.

2. **"Este mes" tiene cuatro definiciones y dos de ellas no tienen el piso de antigüedad del borde.** MEDIDO sobre la misma serie: el KPI del Dashboard publica **+35,24 % (US$ 3.700)** donde el motor del backend y `/mensual` no publican nada ("sin base para medir") y donde el mes real fue **+2,90 % (US$ 400)**. El comentario de `useMonthlyData.js:585-593` explica ese bug y dice "es el mismo `_border_is_fresh` que el backend ya aplica… mismo número a propósito: si se separan, uno de los dos está mal". Se separaron: `computeReturnDelta` —el motor del Dashboard y del home mobile— no tiene piso.

3. **El YTD de Métricas toma como borde de apertura la foto del propio 1 de enero, que ya tiene adentro el aporte de ese día, y después le resta los flujos del año entero.** MEDIDO ejecutando `main._ytd_delta` verbatim: publica **−22,86 % / −US$ 4.000** sobre una cartera que ganó **+US$ 1.000**. Signo invertido. `reporting/builder.py:1146-1155` documenta exactamente ese defecto y lo arregla con `_dia_anterior` para el período 'year' de `/reportes`; el KPI de Métricas quedó sin migrar. **⚠️ Y hoy está tapado por H-1**: como la fila etiquetada `2026-01-01` es en realidad el cierre ART del 31/12, el borde sale accidentalmente bien. **Arreglar H-1 solo, sin tocar `_ytd_delta`, hace aparecer este bug.**

Un dato transversal que ordena todo lo demás: **de los 27 lugares del frontend que calculan "hoy" con `toISOString()` (UTC), exactamente UNO tiene el arreglo a hora local**, y lleva un comentario que dice por qué: `AdvisorDashboard.jsx:745-747` — *"Fecha LOCAL (audit: toISOString es UTC — de noche en Argentina devolvía la fecha de mañana en un documento con matrícula CNV)"*. O sea: **el bug está diagnosticado y arreglado en 1 de 28 lugares.** El mismo patrón que 1A llamó "fix aplicado en un solo lugar".

**Total: 17 hallazgos** — 3 🔴, 7 🟠, 5 🟡, 2 ⚪.

---

## Inventario de períodos

### A · "Hoy"

| definición | dónde vive | quién lo consume | ¿coincide? |
|---|---|---|---|
| **ART** `(utcnow() − 3h).strftime('%Y-%m-%d')` | `main.py:27750-27756` (`_iso_today`) | `POST /api/snapshots` (`:5019`), `/reports/period` rama *day* (`:33165`), gap-month (`:11875`), cierre de bono (`:12337`), mtm-audit (`:17921`), diagnose-reportes (`:18195`), billing (`:27733`, `:27771`), marca de estampado (`:32367`), `latest_date` de Métricas (`:32682`) | **NO** — ver B |
| **ART**, helper propio por módulo | `twr.py:713-715`, `advisor_brief.py:37-39`, `advisor_alerts.py:31-32`, `ledger_replay.py:143`, `importing/proyeccion.py:83`, `main.py:36987` (hero del libro), `main.py:35860`/`:35867` | TWR, brief del asesor, alertas del asesor, replay del ledger, proyección de renta fija, `GET /api/advisor/book` | sí entre ellos |
| **UTC** `utcnow()` | `snapshots_job.py:937` (cron), `reporting/builder.py:94` (`is_period_current`) y `:511-512` (`_hoy_iso`), `main.py:11452` (rollover mensual), `:11054` (`sync_unrealized`), `:28512` (prompt de la IA), `:37970` (`advisor_book_detail`), `:15913` (backfill MtM), `:12926`, `:17335`, `:20261`, `:21223`, `:23805`, `:23905`, `:31140`, `:35340` | cron de snapshots, Reportes, /mensual, chat de la IA, detalle del libro | **NO** |
| **hora local del proceso** `date.today()` | 77 call sites no-test. Los que definen período: `reporting/timeline.py:24` (`_months_back`) y `:251` (`wrpt_is_current_check`), `main.py:33165` (rama week/month/year de `/reports/period`), `main.py:10384` (guard de fecha futura), `ai/quota.py:348`/`:430`/`:486`/`:526`, `ai/builders/*` | timeline de Reportes, cuota de IA, eventos, builders de IA | = UTC en prod (deducido); = ART en dev |
| **UTC** frontend `new Date().toISOString().slice(0,10)` | **27 sitios** en 18 archivos (sin tests ni `demo.js`) | defaults de todos los formularios de operación, tab "Hoy" de Reportes, `computeReturnDelta`, variación diaria de `/posiciones`, TIR de bonos, cashflows pendientes, eventos próximos | **NO** |
| **LOCAL** frontend `getFullYear/getMonth/getDate` | `AdvisorDashboard.jsx:747` (**el único arreglado, con comentario de audit**), `Reports.jsx:45-51` (`monthKey`, `yearKey`, `isoWeekKey`), `Dashboard.jsx:648`, `HomeMobile.jsx:188`, `useMonthlyData.js:407`/`:518`, `MonthlySummary.jsx:119`/`:196`/`:811`, `DateField.jsx:17`, `DateInput.jsx:8` | KPI "Este mes", rollover del frontend, pickers de fecha, informe firmado del asesor | **NO** |

### B · "Este mes"

| definición | archivo:línea | consume | piso de antigüedad del borde |
|---|---|---|---|
| Mes calendario `[1º .. último]`, inclusivo en las dos puntas; borde de apertura = `_dia_anterior(start)` con `mtm_only` | `reporting/builder.py:33-66` (`parse_period_bounds`), `:913-989`, `:1146-1155`, `:461-472` | `/reportes` tab Mes, timeline, `ai/builders/monthly.py` | **SÍ — 5 días** (`_BORDER_MAX_LAG_DAYS`) |
| `sinceDate` = 1º del mes **LOCAL**; referencia = último snapshot `apto` con `date < sinceDate`; si no hay, **el más antiguo de la serie** | `Dashboard.jsx:647-649`, `HomeMobile.jsx:187-190` → `evolution.js:305-367` | KPI "Este mes" del Dashboard y del home mobile | **NO** |
| `isLiveMonth` = año/mes **LOCAL**; base = último `apto` con `date < ${period}-01` | `hooks/useMonthlyData.js:406-432` | `/mensual`, banner del mes en curso | **NO** |
| ídem pero con `_pisoBase` = arranque del mes − 5 días | `hooks/useMonthlyData.js:594-600` | `/mensual`, rama `newestWithCapital` | **SÍ — 5 días** |
| Mes calendario **UTC** | `main.py:11452-11453` (`_rollover_to_current_month`), `:11054` (`sync_unrealized`) | `GET /api/monthly` crea la fila del mes; `sync-unrealized` escribe el latente | n/a |
| Mes calendario **ART**, base = último día del mes anterior | `main.py:36987`, `:36995` | `flows_month` del hero del libro del asesor | n/a |
| `utcnow().strftime("%Y-%m-01")` | `billing/trial.py:74`, `:382` | cupo mensual de trials | n/a |

### C · YTD / "este año"

| definición | archivo:línea | consume | coincide |
|---|---|---|---|
| `year = latest_date[:4]`; arranque = snapshot `at_or_before('YYYY-01-01')` **INCLUSIVO**, `mtm_only`, con `_border_is_fresh(max_lag=5)`; Modified Dietz contra los flujos del año | `main.py:32949-33037` (`_ytd_delta`) | KPI "YTD" de Métricas / snapshot de Reportes; y de ahí al `_bench_cache` y al prompt del chat | **NO** — ver H-2 |
| Período 'year' = `['YYYY-01-01','YYYY-12-31']`; arranque = `_dia_anterior(period_start)` **EXCLUSIVO** | `reporting/builder.py:64-66`, `:1146-1155` | `/reportes` tab Año | — |
| `_yrStart = ${year}-01-01`; base = último `apto` con `date < _yrStart` (exclusivo), sin piso de antigüedad; `ytdSinBaseMedida` si no hay | `hooks/useMonthlyData.js:668-690` | `/mensual` KPI YTD | parcial |
| `start = 1 ene LOCAL`, `end = hoy LOCAL` | `AdvisorDashboard.jsx:755` | informe firmado del asesor, período "Este año" | — |
| `sp500_ytd = last_close / prev_dec − 1`; `inflation_ytd` = composición geométrica de los meses publicados por INDEC | `main.py:13721-13754` | `/wrapped` | — |
| `_pct_move(serie, mes_actual, dec_anterior)` | `main.py:23098-23103` | benchmarks del chat de IA | — |

`since_date` de `_ytd_delta` (`main.py:33033`) es **el primer mes con fila en `monthly_entries`**, no el 1 de enero: un usuario que empezó en mayo ve un "YTD" que arranca en mayo, y el propio código lo documenta (`is_partial_year`). Es una decisión deliberada, no un bug — pero significa que "YTD" en Métricas y "Año" en Reportes miden ventanas distintas para el mismo usuario.

### D · "Desde el inicio", "últimos N días"

| definición | archivo:línea | notas |
|---|---|---|
| `min(positions.entry_date, operations.COALESCE(entry_date, date))`, con centinela `'0000-01-01'` si hay posiciones sin fecha | `twr.py:312-348` | ✅ maneja bien los NULL (`MIN` los ignora; el centinela es conservador y está documentado) |
| `Δ1d/7d/30d` = ancla en la fecha del **último snapshot** − N; `date <= target` inclusivo | `main.py:32873-32948` (`_snapshot_delta`) | ancla en el snapshot, **no** en hoy |
| ventana del gráfico = `Date.now() − days·86400000`, comparada contra `new Date(p.date).getTime()` | `evolution.js:213-215` | `new Date('2026-09-04')` parsea como medianoche **UTC**, y el cutoff sale de un `Date.now()` local: los dos lados de la comparación están en calendarios distintos |
| `cutoff = new Date(Date.now() − days·86400000).toISOString().slice(0,10)`, comparación de **strings** `p.date >= cutoff` | `AdvisorDashboard.jsx:446`, `:475` | |
| `GET /api/snapshots?days=N` → `ORDER BY date DESC LIMIT N` | `main.py:5111-5116` | **`days` es un límite de FILAS, no una ventana de fechas.** Ya es la pregunta abierta P-118 |
| serie del libro: `date > cutoff` **exclusivo** + seed `date <= cutoff` | `main.py:37904`, `:37913` | la partición cierra bien |

### E · Bordes de período — inclusivo / exclusivo

| consulta | operador | archivo:línea |
|---|---|---|
| operaciones del período | `date >= start AND date <= end` (inclusivo ambos) | `reporting/builder.py:241-242` |
| snapshots del rango | `date >= start AND date <= end` | `reporting/builder.py:252-253` |
| borde de apertura | `date <= when` | `reporting/builder.py:326`, `:362` |
| apertura del período 'year'/'month' en `/reportes` | `_dia_anterior(period_start)` → **exclusivo** | `reporting/builder.py:1155` |
| apertura del YTD en Métricas | `'YYYY-01-01'` → **inclusivo** | `main.py:33006` |
| base del mes del libro del asesor | `today.replace(day=1) − 1 día` → **exclusivo** | `main.py:36995` |
| base del brief / de las alertas | `s.date < hoy_ART` → **exclusivo de hoy** | `advisor_brief.py:290`, `advisor_alerts.py:250` |

Ninguna fila de `operations` ni de `snapshots` puede llevar hora: todos los modelos Pydantic usan `Field(..., max_length=10)` (`main.py:8149`, `:9390`, `:10270`, `:10311`, `:10685`, `:11115`, `:12064`, `:15150`, `:36079`) y el importador normaliza a `YYYY-MM-DD` con regex (`importing/normalizer.py:45-68`). **La comparación lexicográfica es segura hoy** — con la salvedad de H-16.

---

## Tabla de hallazgos

| # | hallazgo | evidencia | severidad | dónde muerde | causa raíz |
|---|---|---|---|---|---|
| H-1 | El cron sella cada snapshot con el día **UTC**; la rama que convierte a ART es código muerto. Corriendo a las 02:59 UTC, el cierre del viernes queda fechado sábado | **MEDIDO** (M1) | 🔴 | serie histórica entera, bordes de todos los períodos, Δ1d/7d/30d, curva, TWR, libro del asesor, packets de IA | el horario del cron se movió a 02:59 UTC y la etiqueta no; `run_daily_snapshot` pasa `target` no-None y mata la rama ART |
| H-2 | El YTD de Métricas toma la foto del **propio 1 de enero** como borde de apertura y después resta los flujos del año entero: el aporte del 1/1 se descuenta dos veces. **Hoy lo tapa H-1** | **MEDIDO** (M7): −22,86 % / −US$ 4.000 donde la verdad es +US$ 1.000 | 🔴 | KPI "YTD" de Métricas → y de ahí al `_bench_cache` y al prompt del chat de IA | fix `_dia_anterior` aplicado en `builder.py:1155` y no en el KPI hermano |
| H-3 | "Este mes" tiene 4 definiciones; 2 no aplican el piso de antigüedad de 5 días del borde | **MEDIDO** (M9): +35,24 % vs "sin base" vs +2,90 % real | 🔴 | Dashboard y home mobile KPI "Este mes"; `/mensual` banner | `computeReturnDelta` no recibió el `_border_is_fresh` que su propio archivo documenta 250 líneas más abajo |
| H-4 | `/reportes`: la clave del tab "Hoy" se arma en **UTC** y las de Semana / Mes / Año en **hora local** | **MEDIDO** (M8) | 🟠 | `/reportes` de 21:00 a 23:59 ART: el tab Hoy pide un día que en Argentina todavía no empezó, y que puede caer fuera de la semana/mes/año que muestran los otros tabs | cuatro helpers escritos por separado en el mismo archivo |
| H-5 | El mismo endpoint `/api/reports/period/{type}/{key}` usa **dos relojes**: ART para la rama `day`, local/UTC para `week`/`month`/`year`, y UTC adentro de `is_period_current` | ESTRUCTURAL + **MEDIDO** (M3) | 🟠 | la rama "período en curso" se apaga sola durante 3 h/día: sin valor live, el reporte del día en curso cierra con el último snapshot | dos helpers de "hoy" en 8 líneas de código |
| H-6 | `is_period_current` usa UTC con un comentario que dice *"Usar UTC para consistencia con `_iso_today()` del endpoint principal"* — y `_iso_today()` es **ART** | ESTRUCTURAL | 🟠 | mes/año marcados como cerrados 3 h antes de que terminen en Argentina; el guard `basis_incomparable` cambia de rama | comentario escrito sobre una premisa falsa |
| H-7 | El rollover mensual corre en **UTC** en el backend (`_rollover_to_current_month`, `sync_unrealized`) y en **hora local** en el frontend (`autoRolloverIfNeeded`) | ESTRUCTURAL | 🟠 | último día de cada mes, 21:00-23:59 ART: `/mensual` muestra el mes local como "en curso" con `pnl_unrealized=0`, y el latente vivo se escribe en la fila del mes siguiente, que el usuario no ve | Fase 7 movió el rollover al backend sin unificar el calendario |
| H-8 | Brief y alertas del asesor excluyen "hoy ART" (`s.date < _today_art()`) para no comparar contra la foto intradía — pero por H-1 esa exclusión se lleva puesta **la fila del cierre de anoche**, y la base pasa a ser el cierre de anteayer | ESTRUCTURAL (H-1 MEDIDO) | 🟠 | "Δ del día" del brief de apertura y de cierre, y el disparo de las alertas de drawdown — los dos salen por mail | los 3 comentarios que afirman "los snapshots se estampan con fecha ART" |
| H-9 | Las semanas que `/reportes` anida bajo un mes no cubren el mes | **MEDIDO** (M6): septiembre 2026 → faltan los días 1-6; diciembre 2026 → faltan 1-6 y sobra hasta el 3 de enero | 🟠 | `/reportes` tab Semana, `detect_consistency` ("Mes consistente") sobre una partición incompleta | regla "la semana pertenece al mes de su lunes" sin contraparte que cierre el hueco |
| H-10 | 27 sitios del frontend calculan "hoy" en UTC. El bug está **diagnosticado y arreglado en exactamente 1** (`AdvisorDashboard.jsx:745-747`, con comentario de audit) | ESTRUCTURAL (conteo verificado) | 🟠 | defaults de fecha de compra / venta / cash / cupón / PF / futuro, tab Hoy de Reportes, variación diaria de `/posiciones` | fix aplicado en un solo lugar |
| H-11 | La foto intradía del browser no se escribe nunca en un día en que el cron ya corrió: el cron ocupa esa fecha con `source='cron'` y el guard de `main.py:5058-5067` protege esa fila | ESTRUCTURAL (consecuencia de H-1) | 🟡 | punto de "hoy" en la curva del Dashboard | H-1 |
| H-12 | La IA recibe `HOY es {utcnow()}` y puede **escribir operaciones** por chat | ESTRUCTURAL | 🟡 | `register_trade`: de 21:00 a 23:59 ART el modelo resuelve "hoy" y "ayer" corridos un día, y la fila queda persistida | `main.py:28512` |
| H-13 | Seis tolerancias distintas para "cuán viejo puede ser un dato arrastrado hacia atrás": 4, 5, 7, 14 días, y dos sin tope | ESTRUCTURAL | 🟡 | findes largos y feriados: cada pantalla decide distinto si el dato de la punta sirve | cada superficie eligió su número |
| H-14 | `_market_open_now` es una ventana UTC fija (L-V 13-21) sin calendario de feriados y sin DST de EE.UU. | ESTRUCTURAL | 🟡 | alertas de precio: ~1,5 h de pre-market cada día en horario EST, y feriados de BYMA/NYSE en los que se evalúa contra el `change_pct` congelado — justo lo que el docstring dice querer evitar | `alerts_engine.py:113-120` |
| H-15 | `date.today()` (77 call sites) es la hora local del proceso: UTC en Railway, ART en tu Mac | DEDUCIDO (no pude leer `TZ` de Railway) | 🟡 | los tests y el dev local miden un día distinto que producción durante 3 h/día | no hay un helper único de "hoy" |
| H-16 | Los campos de fecha se validan sólo con `max_length=10`, sin formato. Un `'2026-9-4'` entraría y rompería el orden lexicográfico de todos los filtros de período | ESTRUCTURAL | ⚪ | ningún cliente actual lo produce (`<input type=date>` y `DateInput.fmtISO` zero-padean) | validación por longitud en vez de por formato |
| H-17 | El docstring de `GET /api/ai/usage` dice *"SEMANA en curso (ISO week, lunes-domingo)"*; la implementación es una ventana **móvil de 7 días** y así está documentada en `ai/quota.py` | ESTRUCTURAL | ⚪ | copy de la cuota de IA ("X/6 esta semana") | docstring que quedó atrás de un cambio deliberado |

---

## Detalle por hallazgo

### H-1 🔴 · El cron fecha el snapshot en día UTC; la conversión a ART es código muerto

> ⚠️ **Zona de trabajo activa.** Este hallazgo cae en `backend/snapshots_job.py`, sobre el que hay una rama `fix/snapshots-valuacion` en curso. Al momento de lanzarme esa rama no tenía commits ni cambios sobre el archivo, pero verificá antes de tocar.
>
> **Crédito:** el mapa ya lo tiene como hallazgo **J-6** (`00-mapa-sistema.md:15823-15860`, `:16260`, `:27074`). Confirmo la cita y la mecánica. Lo que agrego acá es la **medición** y las **consecuencias río abajo** que J-6 no desarrolla.

`snapshots_job.py:648-657`:

```python
    if target_date is None:
        # Audit follow-up (2026-05-31): fecha del snapshot = día ART, no UTC.
        # Target users son argentinos. Si el cron corre a las 02:59 UTC del
        # sábado (= 23:59 ART del viernes), la fecha debe ser "viernes",
        # no "sábado" (que es lo que utcnow().date() devolvería).
        # Conversión: UTC - 3h = ART.
        from datetime import timedelta as _td
        art_dt = datetime.utcnow() - _td(hours=3)
        target_date = art_dt.strftime('%Y-%m-%d')
```

`snapshots_job.py:937` y `:1021-1022`:

```python
    target = target_date or datetime.utcnow().strftime('%Y-%m-%d')
    ...
                result = take_snapshot_for_user(conn, uid, tc_blue, crypto_yf, target,
                                                tc_mep=tc_mep)
```

`target` nunca es `None` cuando llega a `take_snapshot_for_user` (es el 5º posicional = `target_date`), así que `if target_date is None` es siempre falso. Los dos disparadores de producción llaman `run_daily_snapshot` **sin** `target_date`: el wrapper del scheduler (`main.py:32036-32043`) y el endpoint del cron externo vía `_run_daily_snapshot_bg` (`main.py:33638-33641`, `:33646-33677`). El scheduler está fijado a las **02:59 UTC** (`main.py:32536`) con `BackgroundScheduler(timezone='UTC')` (`main.py:32095`), y el docstring del endpoint externo dice *"1x/día ~03:00 UTC"* (`main.py:33660`).

**MEDIDO** (`m1_fechas.py`, reloj congelado en 2026-09-05 02:59:00 UTC = viernes 2026-09-04 23:59 ART):

```
==============================================================================
M1 · run_daily_snapshot: ¿qué fecha sella el cron?
==============================================================================
  run_daily_snapshot(...) -> target_date = '2026-09-05'
  users_processed = 0
  fila escrita en fx_rates_daily: [('2026-09-05', 1500.0, 'snapshot_cron')]
  esperado si la rama ART de take_snapshot_for_user() estuviera viva: '2026-09-04'

==============================================================================
M1b · la rama ART de take_snapshot_for_user (líneas 650-657) sí calcula el viernes
==============================================================================
  (datetime.utcnow() - 3h).strftime('%Y-%m-%d') = 2026-09-04
  pero run_daily_snapshot pasa target NO-None -> `if target_date is None` es False
```

El **otro escritor de la misma tabla** usa ART, y su comentario describe exactamente el bug del cron (`main.py:5017-5019`):

```python
    # Día ART, no UTC: después de las 21:00 de acá ya es "mañana" en UTC y el
    # snapshot quedaba fechado un día adelante, pisando al del cierre real.
    today = _iso_today()
```

**Consecuencia nueva — el desfasaje llega al borde de todos los períodos.** MEDIDO (`m5_borde.py`), con `fetch_snapshot_at_or_before` y `_dia_anterior` reales sobre una serie construida con la etiqueta que produce el cron:

```
Serie escrita (etiqueta que pone el cron  ->  cierre ART que representa  ->  valor):
   2026-08-30   ->   cierre ART del 2026-08-29   ->   10,500.00
   2026-08-31   ->   cierre ART del 2026-08-30   ->   10,600.00
   2026-09-01   ->   cierre ART del 2026-08-31   ->   10,700.00
   ...
Período 'month' 2026-09 -> start=2026-09-01  end=2026-09-30
_dia_anterior(start) = 2026-08-31   (el borde de apertura que pide builder.py)

fetch_snapshot_at_or_before(when=2026-08-31, mtm_only=True)
   -> fila date=2026-08-31  total_value=10,600.00
   -> esa fila es el cierre ART del 2026-08-30
   -> el borde de apertura de SEPTIEMBRE es el cierre del 2026-08-30, no el del 2026-08-31

P&L de septiembre publicado : 600.00
P&L de septiembre correcto  : 500.00
diferencia = 100.00  (una rueda entera: la del 31/08)
```

Aplicado al período anual: **el reporte de 2026 cierra con el snapshot etiquetado `2026-12-31`, que es la rueda del 30 de diciembre.** El cierre real del año (31 de diciembre ART) queda etiquetado `2027-01-01`, fuera del período `['2026-01-01','2026-12-31']`.

**Tres comentarios del código afirman lo contrario de lo medido** y construyen lógica encima:

- `main.py:36985-36987` — *"Fecha 'hoy' en ART (UTC-3): los snapshots se estampan con fecha ART (cron 23:59 ART) — cortar en UTC corría el mes 3 horas antes (audit)."*
- `advisor_brief.py:38` — *"Fecha de HOY en horario argentino (UTC-3) — los snapshots se estampan así."*
- `advisor_alerts.py:31-32` — mismo helper, misma premisa.

Y el propio mapa se contradice: la línea 21459 dice *"**[V]** La fecha del snapshot es el día ART (UTC−3), no UTC (`snapshots_job.py:647-653`)"* — es falso, y la línea 15850 del mismo documento dice lo correcto. Ver "Citas del mapa incorrectas".

---

### H-2 🔴 · El YTD de Métricas resta dos veces el aporte del 1 de enero (y hoy lo tapa H-1)

`reporting/builder.py:1146-1155` documenta el defecto y lo arregla **para `/reportes`**:

```python
                # `_dia_anterior`: el borde de apertura del año es el cierre del
                # 31/12 ANTERIOR. Con `<= period_start` agarraba la foto del propio
                # 1/1 —que ya tiene adentro el aporte de ese día— mientras
                # `deposits` seguía siendo el del año entero: el aporte se restaba
                # dos veces. Mismo defecto que ya se cerró en el período cerrado y
                # en el mes en curso; faltaba acá.
                _prev_y = _dia_anterior(period_start)
```

`main.py:33005-33012` (`_ytd_delta`, el KPI de Métricas) no recibió el arreglo:

```python
        _yr_start = f"{year:04d}-01-01"
        snap = fetch_snapshot_at_or_before(conn, uid, _yr_start, mtm_only=True)
```

y después, `main.py:33018-33026`, resta los flujos del año **entero**:

```python
    frow = conn.execute(
        """SELECT COALESCE(SUM(deposits - withdrawals), 0) AS net
             FROM monthly_entries
            WHERE user_id = ? AND broker = ? AND year = ?""", ...)
    net_flows = float(frow["net"] or 0) if frow else 0.0
    pnl = latest_value - start - net_flows
```

**MEDIDO** (`m7_ytd.py`, ejecutando `_ytd_delta` extraída verbatim de `main.py:32949-33037`):

```
Función extraída VERBATIM de backend/main.py:32949-33037 y ejecutada.

Serie:
   2025-12-31  valor=10,000.00  aportado=10,000.00
   2026-01-01  valor=15,000.00  aportado=15,000.00
   2026-09-04  valor=16,000.00  aportado=15,000.00
   flujos 2026 (monthly_entries): deposits=5.000 en enero
   VERDAD: arranca en 10.000 (cierre 31/12), entran 5.000, termina en 16.000 -> ganó 1.000

main._ytd_delta(...) -> {"usd": -4000.0, "pct": -22.86, "since_year": 2026, "since_month": 1, "since_date": "2026-01-01", "is_partial_year": false}

  El borde que eligió es la foto del 2026-01-01 (15.000), que YA incluye el aporte.
  pnl = 16.000 − 15.000 − 5.000 = −4.000   ← el aporte se restó DOS veces
  correcto (borde = 31/12/2025):  16.000 − 10.000 − 5.000 = +1.000

  builder.py:1155 usa _dia_anterior('2026-01-01') = 2025-12-31
     -> borde 2025-12-31 valor 10,000.00  ->  pnl = 1,000.00
```

**El acoplamiento, que es lo importante:** con H-1 vivo, la fila etiquetada `2026-01-01` es en realidad el cierre ART del 31/12 y **no** contiene el aporte del 1/1, así que el borde inclusivo sale accidentalmente bien. Los dos bugs se cancelan.

- Arreglar **H-1 solo** → la fila `2026-01-01` pasa a ser el cierre ART del 1/1 → **este bug aparece**, con el signo invertido en el KPI YTD.
- Arreglar **H-2 solo** (usar `_dia_anterior`) con H-1 vivo → el borde pasa a ser el cierre ART del 30/12: se pierde una rueda más, pero el signo no se invierte.
- Los dos van juntos, en el mismo deploy.

Este número no se queda en la pantalla: `_portfolio_snapshot_summary` lo publica en la clave `ytd` (`main.py:32760`, `:32867`), y el bloque de comentario de `main.py:32665-32673` documenta que de ahí lo toma el `_bench_cache` / chat con el flag *"Retornos REALES precalculados — citalos, NO hagas aritmética nueva"*.

---

### H-3 🔴 · "Este mes" no significa lo mismo en el Dashboard que en `/mensual` ni que en el backend

`utils/evolution.js:337-341`:

```js
  if (sinceDate != null) {
    // Cierre más reciente ANTES del inicio del período (ej: último día del mes pasado).
    prev = desc.find(s => s.date < sinceDate)
    // Empezaste dentro del período → no hay cierre previo: usamos el más antiguo.
    if (!prev) prev = desc[desc.length - 1]
```

No hay tope de antigüedad. Y el archivo **hermano** lo documenta explícitamente (`hooks/useMonthlyData.js:585-596`):

> *"⚠️ Y TIENE QUE ESTAR PEGADA AL ARRANQUE DEL MES. Sin el piso de antigüedad, este loop agarraba la medición más reciente ANTERIOR al mes por vieja que fuera: si la última era del 31 de diciembre, el delta de 'este mes' arrancaba en diciembre y se comía dos meses de mercado ajeno presentándolos como el mes en curso. Es el mismo `_border_is_fresh` / `_BORDER_MAX_LAG_DAYS = 5` que el backend ya aplica… **Mismo número a propósito: si se separan, uno de los dos está mal.**"*

Se separaron: el piso está en `useMonthlyData.js:594-600` y en `reporting/builder.py:461-472`, y **no** está en `computeReturnDelta`, que es lo que consumen `Dashboard.jsx:647-649` y `HomeMobile.jsx:187-190` — ni en la rama `isLiveMonth` de `useMonthlyData.js:428`.

**MEDIDO** (`js/m3_estemes.mjs`, ejecutando `computeReturnDelta` real; corrida del 2026-09-07). Serie: mediciones del cron hasta el 20 de junio, el usuario se ausenta y vuelve el 10 de septiembre.

```
Dashboard.jsx:648 / HomeMobile.jsx:188  — computeReturnDelta(sinceDate="2026-09-01")
  -> {"usd":3700,"pct":0.3523809523809524,"prevDate":"2026-06-20","dayDiff":79}
  prevDate = 2026-06-20  dayDiff = 79
  el KPI "Este mes" arranca el 2026-06-20 — 73 días antes del 1 de septiembre
  pct publicado = 35.24%

Con el piso de 5 días (backend builder._border_is_fresh / useMonthlyData:594):
  piso = 2026-08-27 -> candidatos a borde de apertura: 0
  -> sin borde fresco: el número NO se publica (null / "sin base para medir")

Control (existe cierre del 2026-08-31):
  -> {"usd":400,"pct":0.028985507246376812,"prevDate":"2026-08-31","dayDiff":7}  pct = 2.90%
```

**+35,24 % / US$ 3.700** publicado por el Dashboard, contra **US$ 400** de mes real y contra **nada** en `/mensual` y en `/reportes`. Y el helper devuelve `dayDiff: 79` — o sea, el propio dato para no publicarlo está ahí, calculado, y nadie lo mira.

Además, ninguna de las cuatro definiciones usa el mismo calendario para el 1º del mes: `Dashboard`/`HomeMobile`/`useMonthlyData` usan hora **local**; el backend (`_rollover_to_current_month`, `sync_unrealized`) usa **UTC**; el libro del asesor usa **ART**.

---

### H-4 🟠 · `/reportes` mezcla UTC y hora local entre sus propios tabs

`pages/Reports.jsx:31-51` — cuatro helpers, dos calendarios:

```js
function todayIso() {
  return new Date().toISOString().slice(0, 10)          // ← UTC
}
function isoWeekKey(d = new Date()) {
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))   // ← LOCAL
  ...
}
function monthKey(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`      // ← LOCAL
}
function yearKey(d = new Date()) { return String(d.getFullYear()) }             // ← LOCAL
```

consumidos en `Reports.jsx:113-117`:

```js
      if (tab === 'week')      endpoint = `/reports/period/week/${isoWeekKey()}`
      else if (tab === 'day')  endpoint = `/reports/period/day/${todayIso()}`
      else if (tab === 'year') endpoint = `/reports/period/year/${new Date().getFullYear()}`
```

**MEDIDO** (`js/m2_reports.js`, funciones extraídas con `sed` de esas mismas líneas, `TZ=America/Argentina/Buenos_Aires`):

```
── lunes 2026-08-31 22:00 ART (ÚLTIMO día de agosto)
   reloj local del browser : Mon Aug 31 2026 22:00:00 GMT-0300
   tab "Hoy"     todayIso()   = 2026-09-01    [UTC]
   tab "Semana"  isoWeekKey() = 2026-W36   [LOCAL]
   tab "Mes"     monthKey()   = 2026-08     [LOCAL]
   tab "Año"     yearKey()    = 2026        [LOCAL]

── domingo 2026-09-06 23:00 ART (fin de semana ISO)
   tab "Hoy"     todayIso()   = 2026-09-07    [UTC]     ← lunes, semana 37
   tab "Semana"  isoWeekKey() = 2026-W36   [LOCAL]      ← termina el domingo 6

── jueves 2026-12-31 22:00 ART (fin de AÑO)
   tab "Hoy"     todayIso()   = 2027-01-01    [UTC]
   tab "Año"     yearKey()    = 2026        [LOCAL]
```

Es decir: entre las 21:00 y las 23:59 ART, el tab "Hoy" pide un día que en Argentina todavía no empezó, que puede pertenecer a otra semana, a otro mes y a otro **año** que los que muestran los demás tabs de la misma pantalla.

---

### H-5 🟠 · Dos relojes dentro del mismo endpoint

`main.py:33161-33175`:

```python
        from datetime import date as _date
        live_value = None
        is_current_period_for_live = False
        if broker == "global":
            live_value = _latest_snapshot_value(conn, uid)
            today = _date.today()                                        # ← reloj A
            if period_type == "day" and period_key == _iso_today():      # ← reloj B (ART)
                is_current_period_for_live = True
            elif period_type == "week":
                iy, iw, _wd = today.isocalendar()                        # ← reloj A
                ...
            elif period_type == "month" and period_key == today.strftime("%Y-%m"):
                is_current_period_for_live = True
            elif period_type == "year" and period_key == str(today.year):
                is_current_period_for_live = True
```

Y `build_period_report` se llama **sin** `today` (`main.py:33189-33193`), así que `is_period_current` cae en su propio `utcnow()` — un tercer camino. El propio comentario de `builder.py:2067-2074` advierte que *"`today` VIAJA"* y que dejarlo caer en `utcnow()` *"deja los guards del período EN CURSO sin forma determinista de testearse"*; el endpoint principal es justamente el que no se lo pasa.

Efecto: de 00:00 a 02:59 UTC (21:00-23:59 ART), `period_key == _iso_today()` es falso para el día que el frontend pidió (que viene en UTC, H-4), así que `is_current_period_for_live` queda en `False` y **no se computa el valor live del portfolio**: el reporte del "día en curso" cierra con `_latest_snapshot_value`, no con precios de mercado.

---

### H-6 🟠 · `is_period_current` en UTC, con un comentario que afirma lo contrario

`reporting/builder.py:89-97`:

```python
def is_period_current(period_type: str, period_start: str, period_end: str,
                     today: Optional[date_cls] = None) -> bool:
    # Usar UTC para consistencia con _iso_today() del endpoint principal.
    # Sin esto, servidores con TZ no-UTC pueden divergir del frontend cerca
    # de medianoche, marcando un período como "no current" cuando sí lo es.
    today = today or datetime.utcnow().date()
```

`_iso_today()` (`main.py:27750-27756`) es **ART**, no UTC. El comentario es una premisa falsa y el resultado es exactamente el fallo que dice querer evitar.

**MEDIDO** (`m1_fechas.py`):

```
M2 · los 'hoy' del backend con el MISMO reloj  [2026-09-05 02:59 UTC = 2026-09-04 23:59 ART]
  advisor_brief._today_art()     = 2026-09-04
  advisor_alerts._today_art()    = 2026-09-04
  reporting.builder._hoy_iso()   = 2026-09-05
  (main._iso_today() es ART: (utcnow-3h) -> 2026-09-04 )
  date.today() en Railway (TZ=UTC) -> 2026-09-05

M3b · borde de MES: 2026-08-31 23:30 ART (= 2026-09-01 02:30 UTC)
  ART real = 2026-08-31 23:30 (agosto todavía)
  is_period_current('month','2026-08-01','2026-08-31') = False
  is_period_current('month','2026-09-01','2026-09-30') = True

M3c · borde de AÑO: 2026-12-31 22:00 ART (= 2027-01-01 01:00 UTC)
  is_period_current('year','2026-01-01','2026-12-31') = False
  is_period_current('year','2027-01-01','2027-12-31') = True
```

Agosto queda marcado como cerrado 30 minutos antes de que termine agosto en Argentina; 2026 queda cerrado dos horas antes de fin de año. Eso cambia la rama que corre en `compute_metrics_for_period` (`builder.py:913-916`: `month_is_current = _period_is_current and live_value is not None`) — el mes pasa de medirse contra el valor live a medirse contra la cadena contable de `monthly_entries`, que es la mezcla de bases que ese mismo bloque documenta como productora de "%" fantasma.

Nota: `_hoy_iso()` (`builder.py:511-512`, UTC) alimenta `_ventana_cubre` (`:487-503`), el guard que decide si la ventana medida cubre el período que se publica. Mismo desfasaje.

---

### H-7 🟠 · El rollover mensual corre en UTC en el backend y en hora local en el frontend

Backend, `main.py:11452-11453`:

```python
    now = datetime.utcnow()
    target_year, target_month = now.year, now.month
```

llamado desde `GET /api/monthly` (`main.py:11966-11967`, vía `_rollover_all_brokers`).

Backend, `main.py:11038-11041` y `:11054-11060` — el docstring lo declara:

> *"Actualiza pnl_unrealized del **MES CALENDARIO ACTUAL (UTC)** del broker… Si no existe entrada para el mes calendario actual → **no-op silencioso**."*

Frontend, `components/MonthlySummary.jsx:118-120`:

```js
  async function autoRolloverIfNeeded(currentEntries, bkrs) {
    const todayY = new Date().getFullYear()
    const todayM = new Date().getMonth() + 1
```

y `isCurrentMonth` en `:196-197` y `:811-813`, más `hooks/useMonthlyData.js:406-407`, todos en hora **local**.

El 31 de agosto a las 22:00 ART el usuario abre `/mensual`:

1. `GET /api/monthly` → el rollover **UTC** ve septiembre, cierra agosto (`pnl_unrealized = 0`, `capital_final` recalculado con la fórmula canónica, `main.py:11472-11481`) y crea la fila de septiembre.
2. `sync-unrealized` escribe el latente vivo en la fila de **septiembre**.
3. La UI marca **agosto** como el mes en curso (local) y muestra `pnl_unrealized = 0`.

Resultado: durante esas 3 horas, el mes que el usuario ve como "en curso" está cerrado y sin latente, y el número vivo está en una fila que la pantalla no destaca. El `ConciliationBanner` (`MonthlySummary.jsx:808-828`) va a reportar el drift contra el mes equivocado.

---

### H-8 🟠 · El brief y las alertas del asesor se comparan contra el cierre de anteayer

`advisor_brief.py:284-292`:

```python
            # Se excluye HOY: el snapshot intradiario que escribe el browser
            # haría que "cómo cerró hoy" se compare contra un valor de hoy.
            _hoy = _today_art()
            snaps = {r["user_id"]: r for r in conn.execute(
                f"""SELECT s.user_id, s.date, s.total_value FROM snapshots s
                    WHERE s.user_id IN ({ph}) AND s.date < ?
```

`advisor_alerts.py:244-250` hace lo mismo con un piso adicional de 4 días.

La intención es correcta. El problema es la premisa de `advisor_brief.py:37-39`:

```python
def _today_art() -> str:
    """Fecha de HOY en horario argentino (UTC-3) — los snapshots se estampan así."""
```

No se estampan así (H-1, MEDIDO). El brief de apertura corre a las ~11:00 ART del día D; `_today_art()` = D; y la fila del cierre de anoche está etiquetada **D**, no D−1. El `s.date < D` la excluye. La base pasa a ser la fila D−1 = el cierre ART de D−2. **El "Δ del día" del brief y el disparo de las alertas de drawdown miden contra dos ruedas atrás.** Los dos salen por mail.

Lo mismo, con otro operador, en el hero del libro (`main.py:36985-36995`):

```python
        # Fecha "hoy" en ART (UTC-3): los snapshots se estampan con fecha ART
        # (cron 23:59 ART) — cortar en UTC corría el mes 3 horas antes (audit).
        today = (_dt.utcnow() - _td(hours=3)).date()
        latest = _latest_snapshots(conn, ids)
        asof_7d = _snapshots_asof(conn, ids, (today - _td(days=7)).isoformat())
        ...
        asof_month = _snapshots_asof(conn, ids, (today.replace(day=1) - _td(days=1)).isoformat())
```

mientras `advisor_book_detail` (`main.py:37970`) usa `today = _dt.utcnow().date()` (UTC), pese a que su docstring promete *"MISMA fuente y MISMAS reglas que advisor_book, para que el total y el delta de acá cierren EXACTO con el hero"* (`main.py:37945-37948`). Esto ya es la pregunta abierta **P-087** y el mapa lo tiene en la línea 27492; lo confirmo con la cita y agrego que la premisa ART del hero también es falsa.

---

### H-9 🟠 · Las semanas que `/reportes` anida bajo un mes no cubren ese mes

`reporting/timeline.py:36-58`:

```python
def _weeks_in_month(year: int, month: int) -> List[str]:
    """Devuelve los period_keys de las ISO weeks que tocan el mes (Mon-Sun).
    Una semana "pertenece" al mes si el lunes está en ese mes."""
```

**MEDIDO** (`m6_semanas.py`, con `_weeks_in_month` y `parse_period_bounds` reales):

```
Mes 2026-09  [2026-09-01 .. 2026-09-30]
   2026-W37  [2026-09-07 .. 2026-09-13]
   2026-W38  [2026-09-14 .. 2026-09-20]
   2026-W39  [2026-09-21 .. 2026-09-27]
   2026-W40  [2026-09-28 .. 2026-10-04]  <- termina DESPUÉS del mes
   unión de las semanas: 2026-09-07 .. 2026-10-04
   ⚠ días del mes que NINGUNA semana cubre: 2026-09-01 .. 2026-09-06

Mes 2026-12  [2026-12-01 .. 2026-12-31]
   2026-W50  [2026-12-07 .. 2026-12-13]
   ...
   2026-W53  [2026-12-28 .. 2027-01-03]  <- termina DESPUÉS del mes
   ⚠ días del mes que NINGUNA semana cubre: 2026-12-01 .. 2026-12-06

Mes 2027-01  [2027-01-01 .. 2027-01-31]
   2027-W01  [2027-01-04 .. 2027-01-10]
   ...
   ⚠ días del mes que NINGUNA semana cubre: 2027-01-01 .. 2027-01-03
```

Seis días de septiembre y seis de diciembre 2026 no aparecen en ninguna semana de su mes; la última semana de cada mes se extiende al siguiente. `Reports.jsx:97-103` aplana esos children para armar el tab "Semana", así que el usuario navega una lista con huecos. Y `detectors.detect_consistency` saca conclusiones ("Mes consistente") sobre esa partición.

El mapa ya lo tiene (línea 27588); lo que agrego es la medición y la magnitud (hasta 6 días de hueco, no 1).

---

### H-10 🟠 · 27 sitios en UTC, uno solo arreglado

El arreglo existe y está justificado, en `pages/AdvisorDashboard.jsx:744-747`:

```js
  const today = new Date()
  // Fecha LOCAL (audit: toISOString es UTC — de noche en Argentina devolvía
  // la fecha de mañana en un documento con matrícula CNV).
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
```

Los 27 que quedaron (`grep -rn "new Date()\.toISOString()\.slice(0, 10)"`, sin tests ni `utils/demo.js`), en 18 archivos:

| archivo | qué default fija |
|---|---|
| `pages/Positions.jsx:49, :129, :909, :961, :1626, :2876, :2899, :3764` | `today()` exportado; fecha del **movimiento de caja** (dos modales); base de la **variación diaria**; el `max` del input; el gate `esHoy` que decide si dolarizar al TC de hoy o al histórico |
| `pages/Operations.jsx:51` | `EMPTY.date` — fecha de toda operación cargada a mano |
| `pages/Reports.jsx:32` | clave del tab "Hoy" (H-4) |
| `pages/Goals.jsx:25, :29` | fecha de objetivos |
| `pages/Dashboard.jsx:473` | — |
| `pages/PositionsMobile.jsx:2842` | nombre del CSV exportado |
| `components/PfFormModal.jsx:12` | `fecha_inicio` del plazo fijo |
| `components/BondCashflowModal.jsx:34` | fecha del **cupón / amortización** |
| `components/FuturosGroup.jsx:22` | fecha del futuro |
| `components/PlazosFijosGroup.jsx:14`, `hooks/usePfRollup.js:16` | vencimiento de PF |
| `components/RentaFijaSections.jsx:22, :125`, `components/BondDetail.jsx:78`, `utils/bondSchedule.js:67, :275` | "próximo pago", TIR |
| `components/plan/ExportCsvButton.jsx:51` | nombre del CSV |
| `utils/evolution.js:203, :307` | punto "hoy" de la curva; `today` de `computeReturnDelta` |
| `utils/pendingCashflows.js:46, :63, :104` | cashflows pendientes |
| `utils/upcomingEvents.js:23, :29, :226` | eventos próximos |
| `pages/AdvisorDashboard.jsx:446, :475` | cutoff de la ventana del gráfico del libro |

Dos consecuencias concretas:

1. **La fecha por defecto de una operación cargada a las 22:00 ART es la de mañana.** El backend la acepta: el guard de fecha futura (`main.py:10384`) compara contra `date.today()`, que en Railway es UTC — el mismo día. Es exactamente la clase de fila que el guard del cupón existe para impedir (ver el bloque de `main.py:10376-10383`, que documenta los 25 cupones de AL35 fechados en 2027 y los US$ 3,9M fantasma).
2. **Convive con pickers locales en el mismo archivo.** `PfFormModal.jsx` define `addDays`/`daysBetween` con el comentario *"Aritmética de fechas local (sin shift de timezone)"* (`:15-19`) y tres líneas más arriba siembra `fecha_inicio` con el `today()` en UTC (`:12`). `DateField.jsx:17` y `DateInput.jsx:8` formatean en local, así que el calendario resalta un día distinto del que trae el valor pre-cargado.

---

### H-11 🟡 · La foto intradía del browser no llega a escribirse

`main.py:5044-5067` protege la fila del cron, y con razón:

```python
        # ⚠️ UN CIERRE DEL CRON NO SE PISA — NI LA MARCA NI EL VALOR.
        _prev = conn.execute(
            "SELECT source FROM snapshots WHERE user_id=? AND date=?", (uid, today)
        ).fetchone()
        if _prev is not None and _prev["source"] == "cron":
            conn.execute(
                """UPDATE snapshots SET net_deposited = ?, fx_to_usd_blue = ... """)
```

Con H-1, la fila de la fecha ART **D** ya existe con `source='cron'` desde las 02:59 UTC de ese mismo día (contiene el cierre de D−1). Así que durante todo el día ART D, el `POST /api/snapshots` del Dashboard sólo actualiza `net_deposited` y el FX: **el `total_value` intradía nunca se persiste.** `esDibujable` acepta la clase `intradia` (`evolution.js:20`, `:44-46`), o sea que la curva perdió su punto de hoy sin que nada lo diga.

Verificable en un minuto sobre producción: `SELECT source, COUNT(*) FROM snapshots GROUP BY source` — si `browser` está en ~0 para fechas posteriores a que el cron entró, está confirmado. Es la pregunta 6.

---

### H-12 🟡 · La IA recibe el "hoy" en UTC y puede escribir operaciones

`main.py:28509-28512`:

```python
    # La fecha de HOY va en el contexto: sin esto el modelo no puede resolver
    # fechas relativas ('ayer hice un depósito') y las inventaba de su prior
    # (caso real: 'AYER' → 2025-01-08, año equivocado, mensual mal bookeado).
    _today_line = f"HOY es {datetime.utcnow().strftime('%Y-%m-%d')}."
```

El comentario explica que esta línea existe **precisamente** para que el modelo no fabrique fechas al registrar operaciones por chat. De 21:00 a 23:59 ART le dice que hoy es mañana, así que "ayer" resuelve al día ART en curso. Y `register_trade` persiste. Es el mismo archivo que ya tuvo el incidente del año equivocado.

---

### H-13 🟡 · Seis tolerancias distintas para el arrastre hacia atrás

Cuando un período empieza o termina en un día sin rueda, cada superficie decide por su cuenta cuánto puede retroceder:

| tope | dónde | qué arrastra |
|---|---|---|
| **4 días** | `advisor_alerts.py:244` (`_floor`, *"4 días cubre un finde largo"*) | base del "% del día" de las alertas |
| **5 días** | `reporting/builder.py:469-472` (`_BORDER_MAX_LAG_DAYS`) y `hooks/useMonthlyData.js:595` | borde de apertura de período |
| **7 días** | `price_history.py:24` (`MAX_DIAS_ATRAS`) | precio histórico por símbolo |
| **14 días** | `main.py:37004` (`_floor7`) | base del Δ7d del libro |
| **sin tope** | `fx.py:50-74` (`_lookup`) | TC ARS/USD por fecha |
| **sin tope** | `snapshots_job.apply_last_known_prices` — señalado por el propio comentario de `price_history.py:19-23`: *"Es la misma clase de bug que `apply_last_known_prices`, que completa desde una tabla global sin TTL y deja la serie PLANA (peor que un hueco: el hueco se ve)"* | precios faltantes del snapshot |

El de `fx._lookup` merece un renglón aparte: no tiene tope **hacia adelante** tampoco. `fx_for_date(conn, '2027-01-09')` devuelve la última fila de `fx_rates_daily`, o sea el TC de hoy, sin ninguna señal de que es una fecha futura. Es el mecanismo que dejó pasar los cupones fechados en 2027.

Los cuatro topes con número son defendibles por separado; el problema es que la misma pregunta ("¿este cierre sirve de punta?") se contesta con 4, 5, 7 o 14 según qué pantalla la haga, y el resultado es que un finde largo apaga un KPI y no el de al lado.

---

### H-14 🟡 · La ventana de mercado es un rango UTC fijo, sin feriados y sin DST

`alerts_engine.py:113-120`:

```python
def _market_open_now(now) -> bool:
    """Aproximado: L-V, ~13:00–21:00 UTC (cubre US 9:30–16 ET + BYMA 11–17 ART)."""
    if now.weekday() >= 5:
        return False
    return 13 <= now.hour < 21
```

Tres huecos:

- **DST de EE.UU.** Argentina no cambia de hora desde 2009; EE.UU. sí. En horario EDT (marzo-noviembre) NYSE abre 13:30 UTC, así que 13:00-13:29 es pre-market. En EST (noviembre-marzo) abre 14:30 UTC: hora y media diaria de pre-market dentro de la ventana, evaluando alertas contra el `change_pct` congelado del cierre anterior — justo lo que el docstring dice querer evitar.
- **Feriados.** No hay calendario. Un feriado de BYMA en día hábil deja los `.BA` congelados y las alertas de `price_target` se evalúan igual contra el precio del cierre previo.
- El gate es `market_open` global; `tradeable = (sym in _crypto_symbols()) or market_open` (`alerts_engine.py:386`), o sea un CEDEAR sigue el calendario de "cualquiera de los dos mercados", no el suyo.

Relacionado, y **ya abierto como P-153**: fuera de rueda `data912` manda `pct=0` y `/api/prices/prev-close` devuelve `previo = actual` (`main.py:7917`), así que todos los `.BA` muestran "+0,00 %" — indistinguible de "no se movió". No lo re-audito.

---

### H-15 🟡 · `date.today()` es la hora local del proceso

77 call sites no-test. En Railway no hay `TZ` en `railway.toml` ni en `nixpacks.toml` (verificado), así que el contenedor corre en UTC y `date.today() == utcnow().date()`. En tu Mac corre en ART. Los que definen período: `reporting/timeline.py:24` (`_months_back` → los 12 meses del timeline), `:251` (`wrpt_is_current_check`), `main.py:33165` (H-5), `main.py:10384` (guard de fecha futura del cupón), `ai/quota.py:348/430/486/526` (la ventana de cuota de IA), y todos los `ai/builders/*`.

Consecuencia operativa: durante 3 h/día un test que fija fechas se comporta distinto en local que en producción, en la dirección que hace pasar el test. El comentario de `builder.py:2069-2074` ya describe un caso real de esto (*"`test_sin_cierre_medido_...` fija `today=2026-08-16` y empezó a fallar solo el 1 de septiembre"*).

---

### H-16 ⚪ · Fechas validadas por longitud, no por formato

Todos los modelos de entrada usan `Field(..., max_length=10)` sin validador de formato. `'2026-9-4'` mide 8 caracteres y pasaría. Una vez adentro, rompe el orden lexicográfico de **todos** los filtros de período (`'2026-9-4' > '2026-12-31'`) y el orden `ORDER BY date` de los motores FIFO.

Hoy no es alcanzable desde la app: `<input type="date">` y `DateInput.fmtISO` (`components/DateInput.jsx:8`) siempre zero-padean, y el importador normaliza con regex (`importing/normalizer.py:56-68`, que además ya tuvo que aflojar a `\d{1,2}` para Excel y re-normaliza con `_validate_ymd`). Queda como deuda: la puerta está abierta para cualquier cliente que no sea el navegador (el chat de la IA, un script, un cliente viejo).

---

### H-17 ⚪ · "Esta semana" de la cuota de IA es una ventana móvil, no una semana ISO

`main.py:27788-27791`:

```python
def ai_usage(uid: int = Depends(get_effective_user)):
    """Usage de la SEMANA en curso (ISO week, lunes-domingo) — el frontend
    lo usa para mostrar 'X/6 esta semana' en Free, ...
```

`ai/quota.py:226-238` y `:341`:

```python
def _window_start(today: date, floor: date = None) -> date:
    """Inicio de la ventana móvil de 7 días: hoy − 6 días, nunca antes de `floor`.
    ... Si Pablo usó IA ayer (domingo) y hoy es lunes, ese análisis
    sigue contando — evita el surprise reset de los lunes."""
...
        "period": "rolling_7d",
```

**El código es deliberado y está bien razonado; el docstring del endpoint quedó atrás.** Lo dejo como ⚪ porque el riesgo real es el copy que ve el usuario: "X/6 esta semana" describe un reset de lunes que no existe.

---

## Parches detectados

| parche | dónde | causa real | dónde más sigue rompiendo |
|---|---|---|---|
| **La rama ART de `take_snapshot_for_user`** (`snapshots_job.py:648-657`) — se agregó la conversión adentro de la función per-usuario en vez de en el runner que fija la fecha | `snapshots_job.py:648-657` vs `:937` | no hay un helper único de "hoy" que el módulo entero use | H-1 completo: bordes de período, brief, alertas, hero del libro, curva |
| **`_iso_today()` en `main.py`** — el mismo arreglo, hecho de nuevo, en otro archivo | `main.py:27750-27756` | ídem: cuatro módulos definieron su propio `_hoy_art` (`twr.py:713`, `advisor_brief.py:37`, `advisor_alerts.py:31`, `main.py:27750`) y ninguno es el canónico | los 253 `utcnow()` y 77 `date.today()` restantes quedaron sin migrar |
| **El comentario "Usar UTC para consistencia con `_iso_today()`"** (`builder.py:91-93`) — se documentó una alineación en vez de verificarla | `reporting/builder.py:89-97` | ídem | H-6 |
| **El `iso()` local del `ReportModal`** (`AdvisorDashboard.jsx:745-747`) — el bug se diagnosticó por el peor síntoma (un documento con matrícula CNV con fecha de mañana) y se arregló sólo en ese formulario | `AdvisorDashboard.jsx:745-747` | `toISOString()` como forma default de escribir una fecha en el frontend | los otros 27 sitios (H-10) |
| **El `_floor7 = today − 14 días` del hero del libro** (`main.py:37004`) — se puso un piso porque *"un cliente con snapshots frenados 60 días metía su delta de 2 meses en 'últimos 7 días'"*; el número (14) no coincide con ninguno de los otros cuatro pisos del repo | `main.py:37004` | falta una regla única de frescura del borde | H-13 |
| **El `_pisoBase` de `useMonthlyData.js:594-600`** — el comentario dice explícitamente *"mismo número a propósito: si se separan, uno de los dos está mal"*, y se aplicó a una de las dos ramas del mismo archivo | `useMonthlyData.js:594` (con piso) vs `:428` (sin piso) | `computeReturnDelta` nunca recibió el guard | H-3 |
| **`_dia_anterior(period_start)` en `builder.py:1155`** — el comentario dice *"Mismo defecto que ya se cerró en el período cerrado y en el mes en curso; faltaba acá"*, y el hermano `_ytd_delta` siguió faltando | `reporting/builder.py:1155` vs `main.py:33006` | ídem | H-2 |

Lo que **no** es parche y sí es decisión deliberada, verificada leyendo el comentario antes de reportarla:

- La ventana **móvil** de 7 días de la cuota de IA (H-17): está razonada (`ai/quota.py:229-232`) y es mejor que la semana ISO. Lo que está mal es el docstring del endpoint.
- El horario **02:59 UTC** del cron (`main.py:32525-32533`): la elección de correr a la medianoche argentina es correcta. Lo que falta es que la etiqueta acompañe.
- El **centinela `'0000-01-01'`** de `primera_fecha_con_posiciones` (`twr.py:340-348`): es el lado conservador del error y está documentado.
- El `s.date < hoy` del brief y las alertas: la regla ("la base tiene que ser el cierre anterior, no la foto intradía") es correcta. Lo que la rompe es H-1.

---

## Citas del mapa incorrectas

1. **`00-mapa-sistema.md:21459`** — *"**[V]** La fecha del snapshot es el **día ART** (UTC−3), no UTC (`snapshots_job.py:647-653`)."*
   **Falso, y contradice al propio mapa.** La línea 15850 del mismo documento dice lo correcto (*"la rama ART de `take_snapshot_for_user` nunca se ejecuta desde el cron"*) y la 16260 lo lista como hallazgo 🔴 J-6. La línea 21459 lee la rama muerta (`:647-653`) sin mirar quién fija `target_date`. **Corrección: la fecha del snapshot es el día UTC (`snapshots_job.py:937`); la rama ART de `:648-657` es código muerto en todos los caminos de producción.** MEDIDO (M1).

2. **`00-mapa-sistema.md:23937`** — sobre `RentaFijaSections.jsx:22` y `BondDetail.jsx:78`: *"Efecto práctico: despreciable en la tasa, pero cambia qué pago cuenta como 'próximo' el día exacto de un cupón."*
   La cita del código es correcta y el veredicto sobre **esos dos** archivos también. Lo que falta es el alcance: **son 27 sitios, no 2**, y varios no son "despreciables" — `Operations.jsx:51` y `Positions.jsx:129/909/961` fijan la **fecha persistida** de una operación (H-10).

3. **`00-mapa-sistema.md:510`** — *"`daily_snapshot` | 02:59 | … El horario es 23:59 ART a propósito (`:32525-32533`)"*.
   La cita es correcta y el horario también, pero la tabla induce a leer que la **fecha** también es ART. No lo es. Sugiero agregar la aclaración en esa fila, que es donde el próximo lector va a mirar.

Verificadas y **correctas** (las abrí una por una): `00-mapa-sistema.md:15823-15860` (J-6, exacto), `:16260`, `:27074`, `:14821-14822` ("tres relojes"), `:27586`, `:27588` (`_weeks_in_month`), `:27492` (ART vs UTC entre `advisor_book` y `advisor_book_detail`), `:15916` (`_market_open_now`), `:6400` (`main.py:17335` en UTC), `:6132` (`main.py:15913`), `:15765` (el comentario del health check que todavía dice 01:00 UTC), `:1529`, `:1561`.

---

## URGENTE

Nada de este informe justifica tocar código antes de que decidas las preguntas 3 y 4. Lo que sí es urgente es **el orden del arreglo**, porque hoy hay dos bugs que se cancelan:

> **No deployés el fix de H-1 sin el de H-2 en el mismo commit.**
>
> Con el cron fechando en UTC, la fila etiquetada `2026-01-01` es el cierre ART del 31/12 y el borde inclusivo de `_ytd_delta` (`main.py:33006`) cae accidentalmente en el lugar correcto. En cuanto el cron pase a fechar en ART, esa misma línea va a tomar el cierre del 1/1 —que ya contiene el aporte de ese día— mientras sigue restando los flujos del año entero. **MEDIDO** (M7): sobre una cartera que ganó US$ 1.000, el KPI publica **−US$ 4.000 / −22,86 %**. Signo invertido, en un número que además viaja al prompt del chat marcado como *"Retornos REALES precalculados — citalos, NO hagas aritmética nueva"*.
>
> El arreglo de H-2 es una línea: `fetch_snapshot_at_or_before(conn, uid, _dia_anterior(_yr_start), mtm_only=True)`, exactamente lo que `builder.py:1155` ya hace.

Y una segunda cosa que no requiere decisión de producto y se puede verificar hoy mismo con una query: **si `SELECT source, COUNT(*) FROM snapshots WHERE date > '<fecha en que entró el cron>' GROUP BY source` devuelve ~0 filas `browser`, la foto intradía del Dashboard no se está guardando para nadie** (H-11), y eso significa que la curva de todos los usuarios perdió su punto de hoy desde que el cron entró.

---

## BLOQUE-RESUMEN

| tema | # | hallazgo | evidencia | severidad | dónde muerde | causa raíz |
|---|---|---|---|---|---|---|
| Fechas/períodos/TZ | H-1 | El cron sella el snapshot con el día UTC (= un día ART adelante); la rama que convierte a ART es código muerto. El desfasaje llega al borde de todos los períodos: septiembre arranca en el cierre del 30/08 y el año 2026 cierra con la rueda del 30/12 | **MEDIDO**: `target_date='2026-09-05'` corriendo 02:59 UTC del 5 (= viernes 4, 23:59 ART); borde de septiembre medido con `fetch_snapshot_at_or_before` real | 🔴 | serie de snapshots entera, Reportes, Δ1d/7d/30d, curva, TWR, libro y brief del asesor, packets de IA | horario del cron movido a 02:59 UTC sin mover la etiqueta; `run_daily_snapshot` pasa `target` no-None (`snapshots_job.py:937` vs `:648-657`) |
| Fechas/períodos/TZ | H-2 | El YTD de Métricas usa borde INCLUSIVO del 1/1 y resta los flujos del año entero → el aporte del 1/1 se descuenta dos veces. Hoy lo tapa H-1 | **MEDIDO**: `main._ytd_delta` verbatim publica −22,86 % / −US$ 4.000 donde la verdad es +US$ 1.000 | 🔴 | KPI YTD de Métricas → `_bench_cache` → prompt del chat de IA | fix `_dia_anterior` aplicado en `builder.py:1155` y no en `main.py:33006` |
| Fechas/períodos/TZ | H-3 | "Este mes" tiene 4 definiciones; 2 no aplican el piso de 5 días del borde de apertura | **MEDIDO**: +35,24 % (Dashboard) vs "sin base" (backend, `/mensual`) vs +2,90 % real | 🔴 | Dashboard y home mobile KPI "Este mes"; banner de `/mensual` | `computeReturnDelta` no recibió el `_border_is_fresh` que `useMonthlyData.js:585-593` documenta como obligatorio |
| Fechas/períodos/TZ | H-4 | `/reportes`: la clave del tab "Hoy" es UTC y las de Semana/Mes/Año son hora local | **MEDIDO**: 31/08 22:00 ART → Hoy=`2026-09-01`, Mes=`2026-08`; 31/12 22:00 ART → Hoy=`2027-01-01`, Año=`2026` | 🟠 | `/reportes` de 21:00 a 23:59 ART | cuatro helpers escritos por separado en `Reports.jsx:31-51` |
| Fechas/períodos/TZ | H-5 | Dos relojes dentro de `/api/reports/period/{type}/{key}`: ART para `day`, local/UTC para el resto, UTC adentro de `is_period_current` | ESTRUCTURAL + MEDIDO | 🟠 | la rama "período en curso" se apaga 3 h/día: el reporte del día cierra sin valor live | `main.py:33165` vs `:33166`; `build_period_report` llamado sin `today` |
| Fechas/períodos/TZ | H-6 | `is_period_current` usa UTC con un comentario que afirma consistencia con `_iso_today()`, que es ART | ESTRUCTURAL + MEDIDO (agosto cerrado a las 23:30 ART del 31/08; 2026 cerrado a las 22:00 ART del 31/12) | 🟠 | Reportes: cambia la rama que mide el período (live vs cadena contable) | comentario sobre una premisa falsa (`builder.py:91-94`) |
| Fechas/períodos/TZ | H-7 | Rollover mensual en UTC en el backend, en hora local en el frontend | ESTRUCTURAL | 🟠 | último día de cada mes 21:00-23:59 ART: `/mensual` muestra el mes local como en curso con latente 0, y el latente vivo va a la fila del mes siguiente | `main.py:11452` / `:11054` vs `MonthlySummary.jsx:118-120` |
| Fechas/períodos/TZ | H-8 | Brief y alertas del asesor excluyen "hoy ART" y por H-1 se llevan puesta la fila del cierre de anoche → miden contra el cierre de anteayer | ESTRUCTURAL (H-1 MEDIDO) | 🟠 | "Δ del día" de los dos briefs por mail y el disparo de las alertas de drawdown; y `advisor_book_detail` (UTC) no cierra con el hero (ART) | tres comentarios afirmando "los snapshots se estampan con fecha ART" |
| Fechas/períodos/TZ | H-9 | Las semanas anidadas bajo un mes no cubren el mes | **MEDIDO**: sep-2026 sin los días 1-6; dic-2026 sin 1-6 y con desborde al 3/1 | 🟠 | `/reportes` tab Semana; `detect_consistency` concluye sobre una partición incompleta | "la semana pertenece al mes de su lunes" sin regla que cierre el hueco (`timeline.py:52-56`) |
| Fechas/períodos/TZ | H-10 | 27 sitios del frontend calculan "hoy" en UTC; el bug está diagnosticado y arreglado en 1 solo | ESTRUCTURAL (conteo verificado; `AdvisorDashboard.jsx:745-747` lleva el comentario del audit) | 🟠 | fecha por defecto de compra/venta/cash/cupón/PF/futuro = mañana después de las 21:00 ART, y el backend la acepta | fix aplicado en un solo lugar |
| Fechas/períodos/TZ | H-11 | La foto intradía del browser no se escribe: el cron ya ocupó esa fecha con `source='cron'` y el guard la protege | ESTRUCTURAL (consecuencia de H-1) | 🟡 | punto de "hoy" en la curva del Dashboard | H-1 + `main.py:5058-5067` |
| Fechas/períodos/TZ | H-12 | La IA recibe `HOY es {utcnow()}` y puede persistir operaciones por chat | ESTRUCTURAL | 🟡 | `register_trade` fecha mal entre las 21:00 y las 23:59 ART | `main.py:28512` |
| Fechas/períodos/TZ | H-13 | Seis tolerancias distintas de arrastre hacia atrás (4, 5, 7, 14 días y dos sin tope) | ESTRUCTURAL | 🟡 | findes largos y feriados: un KPI se apaga y el de al lado no; `fx._lookup` además arrastra hacia adelante sin tope | cada superficie eligió su número |
| Fechas/períodos/TZ | H-14 | `_market_open_now` es un rango UTC fijo, sin feriados y sin DST de EE.UU. | ESTRUCTURAL | 🟡 | alertas de precio: ~1,5 h de pre-market diario en EST y feriados evaluando contra el cierre congelado | `alerts_engine.py:113-120` |
| Fechas/períodos/TZ | H-15 | `date.today()` (77 call sites) es la hora local del proceso: UTC en prod, ART en dev | DEDUCIDO (no pude leer `TZ` de Railway) | 🟡 | tests y dev local miden un día distinto que producción 3 h/día | no hay helper único de "hoy" |
| Fechas/períodos/TZ | H-16 | Fechas validadas sólo por `max_length=10`, sin formato: un `'2026-9-4'` rompería el orden lexicográfico de todos los filtros | ESTRUCTURAL | ⚪ | ningún cliente actual lo produce; puerta abierta para chat de IA / scripts / clientes viejos | validación por longitud |
| Fechas/períodos/TZ | H-17 | El docstring de `/api/ai/usage` dice "ISO week, lunes-domingo"; el código es una ventana móvil de 7 días (deliberada y bien razonada) | ESTRUCTURAL | ⚪ | copy "X/6 esta semana" sugiere un reset de lunes que no existe | docstring atrasado (`main.py:27789` vs `ai/quota.py:226-238`) |
