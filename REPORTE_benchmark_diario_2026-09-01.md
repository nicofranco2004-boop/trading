# REPORTE — Benchmark diario + KPI publicado + cota de cordura (ronda implementada)

> ✅ **DEPLOYADO 2026-09-02**: commit `7043b503` + merge con `origin/main` (`32670ae8`, IOL Lab) = `057b8a43`, pusheado a `main` con autorización explícita del dueño. Audit previo del diff sin hallazgos; suites verdes sobre el árbol mergeado.

Implementado por el mismo chat que auditó, con el "dale" del dueño (punto 3 aprobado).
**Dónde**: worktree `/Users/nicolaspussetto/rendi-worktrees/benchmark-diario`, rama
`fix/benchmark-diario` creada desde `origin/main` = `dde8ee55`, **sin commitear ni pushear**
(upstream desvinculado: un `git push` pelado no deploya). El diff entero está también en
`…/scratchpad/benchmark_diario.patch` (775 líneas).

```
git -C /Users/nicolaspussetto/rendi-worktrees/benchmark-diario diff --stat
 backend/main.py                          |  92 ++++-
 backend/performance.py                   |  86 +++-
 backend/twr.py                           | 118 ++++++-
 frontend/src/pages/Insights.jsx          |  83 +++-
 frontend/src/utils/insightsModel.js      |  49 +++
 frontend/src/utils/insightsModel.test.js |  59 +++
 backend/tests/test_benchmark_diario.py   | (nuevo, 15 tests)
```

Para probarlo ya: `.claude/launch.json` tiene `bench-backend` (:8002, copia de la demo con AAPL
repuesto a 132,26 y sin la foto del 30/08) y `bench-frontend` (:5212, proxy a :8002). Están
levantados. Usuario demo `demo.metricas@rendi.test / demo1234` → Análisis → Métricas.

---

## 1 · QUÉ CAMBIÓ, por archivo

### `backend/main.py`
- `_fetch_yf_daily(ticker, period="5y")` + `_fetch_sp500_daily()` (^SP500TR, fallback ^GSPC):
  cierres `{YYYY-MM-DD: close}`. Tres futures nuevos en `_benchmarks_fetch_and_cache` →
  claves `sp500_d`, `shv_d`, `gld_d`. El mensual sigue igual (cards "Comparativa", IA mensual,
  porcentuales).
- Si el S&P vuelve vacío del fetch, `log.error(...)` explícito (antes moría en silencio: el
  backend local llevaba días con `sp500: {}` por un `tkr-tz.db` corrupto).
- `/api/benchmarks` devuelve el caché **sin** las claves `_d` (~100 KB que el frontend no usa;
  `/insights/performance` las lee del caché directo).
- `/api/admin/diagnose-reportes-basis`: nueva lista `mediciones_dudosas` (+ `_total`,
  `salto_max_veces`): por cada usuario con snapshots, los `cortes_dudosos` de `serie_medible`
  en los dos modos, ordenados por ratio. Es la cola de revisión del punto 3.

### `backend/performance.py`
- `_benchmark_diario(datos, fechas)`: un punto por fecha de la curva, cierre de ese día o del
  último hábil anterior, índice 1,0 en la **primera fecha de la curva con cierre**; antes del
  primer cierre `index: None`. `benchmark_recortado` deriva ahí cuando las claves son fechas y
  la clave no es porcentual.
- `performance()` prefiere `<bench>_d`; si el diario no cubre ninguna fecha cae al mensual.
  Campos nuevos: `benchmark_resolucion` ('diaria'/'mensual') y `cortes_dudosos`.

### `backend/twr.py`
- `leg_dudoso(v0, v1, flow)` → `'desborde'` (dietz ≤ −1: el cero absorbente) o `'salto'`
  (ratio fuera de `[1/5, 5]` con `|flujo| < 10 %` del valor) o None. `SALTO_MAX_VECES = 5.0`,
  `SALTO_FLUJO_TOL = 0.10`.
- `serie_medible`: el corte del tramo usa `leg_dudoso` en los legs **apto→apto** (antes sólo
  el desborde) y, **sólo en ESTIMADO**, en los legs **contable→contable** (la cadena del
  `idx_est`, donde vivía el −100 % de uid 193). Devuelve `cortes_dudosos`.
- `curva_indexada`: la cadena de **dibujo** (`idx_por_base`) no corta el tramo: ante un leg
  dudoso abre un **segmento nuevo** (la línea se corta, el número no se toca — el caso de la
  intradía rota de uid 745). Cada punto trae `index_publicado` (= `idx`, apto→apto). Motivo
  nuevo `medicion_dudosa` con su `MOTIVO_TEXTO`.

### `frontend/src/pages/Insights.jsx`
- Manda `valor_live` (la cartera de hoy) en `/insights/performance`, recién cuando terminó de
  cargar (`liveUsdPerf` + `liveKeyPerf`): la curva y el S&P terminan el mismo día.
- `benchSeriesUsd`: cada punto lleva `bench` (el índice del backend, alineado por posición),
  `apto` e `ip` (`index_publicado`).
- `chartData`: en USD el benchmark sale de `s.bench` (por fecha). El shadow mensual queda
  para ARS y para el esqueleto sin cartera. El ancla del rebase es la **primera fila con
  dato**, no `first.benchPct ?? 0`.
- KPI: en certero + USD, `acumuladoPublicado(chartData, benchmarkKey)` → rebasea `ip` entre
  el primer y el último punto apto de la ventana, null si hay un corte en el medio; el
  "vs S&P · mismo período" sale de esas MISMAS dos filas. Estimado y ARS: sin cambios.

### `frontend/src/utils/insightsModel.js`
- `acumuladoPublicado(filas, benchKey)` (+ 5 tests).

---

## 2 · VERIFICACIÓN — ejecutada, con el instrumento al lado

**Suites**
```
backend  python3 -m pytest tests/  (a archivo, ^FAILED anclado, conjuntos)
   origin/main sin tocar : 34 fallas       con los cambios : 34 fallas       diferencia de NOMBRES: ∅ / ∅
   (5 de esas 34 NO están en tests/fallas_conocidas.txt — fallan también en la base:
    test_borde_de_cierre·MesEnCursoSinMedicion, test_quota_window_corte ×2, test_reports_variaciones_f4 ×2)
   test_benchmark_diario.py: 15/15 · test_performance_endpoint + test_modo_certero_estimado + test_twr_serie_medible: 40/40
frontend npx vitest run: 52 archivos · 1411 pasan · 0 fallan   ·   npx vite build: OK
```

**A/B sobre la copia de producción** (`work.db` estampada, 670 usuarios, `perf_all.json` viejo
vs `perf_new.json` nuevo, `valor_live=None`):
```
CERTERO   publicaban 480 → publican 451 · usuarios con cortes dudosos 33 · twr cambió en 29
          cambios en usuarios SIN corte dudoso: 0   ← los 437 restantes bit-idénticos
          twr > +100 %: 6 → 2 (uid 821 +367 %, uid 1147 +316 %: legs ×3–4, bajo el umbral ×5)
          twr < −50 %: 31 → 9 · twr == −100 %: 5 → 0
ESTIMADO  publicaban 655 → publican 652 · con cortes 107 · twr cambió en 81 · sin corte: 0
          twr == −100 %: 10 → 0 · > +300 %: 45 → 28 (uid 393: +493.614 % → +132 %)
```

**El pipeline del frontend nuevo** (port fiel `port2.mjs`, mismos 670 usuarios, "hoy" = 16/08):
```
CERTERO 1A   |S&P app − S&P real mismas fechas| : mediana 0,00 · máx 0,01 pp · >0,1 pp: 0/493 · signo distinto: 0
             valores distintos del S&P: mediana 31 (antes 2) · plano en 0 %: 0 (antes 64) · ancla en otro mes: 0 (antes 14)
             KPI == perf.twr (±0,05 pp): 451/451 · KPI con twr=None: 0 (antes 11)
CERTERO 1M   S&P exacto en 493/493 · KPI ≠ twr en 97 (ventana distinta: NO es bug) · KPI con twr=None: 29 (ver §3.2)
ESTIMADO     S&P exacto en 664/664 · KPI y chip sin cambios (fuera de esta ronda)
```

**API del preview** (`:8002`, copia de la demo):
```
/api/benchmarks → sp500 61 · shv 61 · gld 61 · merval 61 (sin claves _d)
/api/insights/performance?bench=sp500&modo=certero&valor_live=18100 → benchmark_resolucion 'diaria' · 46 puntos · 34 valores distintos del S&P · cortes_dudosos []
```

**Browser** (`:5212`, leído del fiber de React y del DOM del `.recharts-wrapper`, porque el
panel deja de pintar después del primer screenshot — trampa 10 del handoff):
```
Certero · 1A   46 filas · S&P: 34 valores distintos, path con 45 segmentos C (una curva, no 2 escalones) · ticks 15/07…01/09
               KPI: "Acumulado 1A · USD −8,7 % · vs S&P 500: +0,9 % · mismo período"   (capturado en pantalla)
Estimado · 1A  60 filas · 3 cortes · S&P: 44 valores distintos · chip "Recreado de tu contabilidad · desde 30/09/2025 …"
               KPI: "−8,7 % · de tu contabilidad · desde el último corte de la serie"
1M             25 filas · S&P 19 valores distintos · certero "−6,2 % · vs S&P 500: +2,0 % · mismo período"
```
El −8,7 % de la demo es el cierre a valor de HOY (`valor_live` = US$16.595 contra la última
foto sintética de 18.077): la demo tiene fotos inventadas, no precios reales.

**Corte inyectado** (foto ×10 el 15/07 en la copia de la demo, después restaurada) — lo que
mostró el browser, leído del DOM y con captura de página entera:
```
Certero · 1A   47 filas · 2 cortes · chip "Medido desde 11/07/2026 · con un hueco"
               KPI: "Acumulado 1A · USD — · vs S&P 500: +1,5 % · mismo período"       ← el "—" hereda el corte
               aviso: "Hay una foto que no cierra. … Por eso el porcentaje de punta a punta no se publica y la línea aparece cortada."
Certero · 1M   24 filas (desde 02/08) · 0 cortes
               KPI: "Acumulado 1m · USD +2,2 % · vs S&P 500: +2,6 % · mismo período"   ← la ventana no cruza el corte: se mide
               aviso: "… En el rango que estás viendo no cae ningún corte: el acumulado de esta ventana sí se mide. El de punta a punta, no."
```

---

## 3 · LAS DOS DECISIONES — tomadas por el auditor con el "hacé lo que creas correcto"

### 3.1 Umbral ×3 (era ×5) — `twr.SALTO_MAX_VECES = 3.0`
Sensibilidad medida sobre la serie vieja (legs apto→apto con el índice ya neto de flujo):
```
umbral ×2 : cortaría 46 de 480 · quedan con twr>+100 %: 0 · con twr<−50 %: 0
umbral ×3 : cortaría 39        · 0                       · 2      ← ELEGIDO
umbral ×4 : cortaría 34        · 0                       · 6
umbral ×5 : cortaría 31        · 2 (uid 821, 1147)       · 7
```
Por qué ×3 y no ×2: un ×2 en una rueda sin flujo lo puede dar una cartera cripto concentrada
en un día malo; un ×3 ya no es una cartera, es una foto. El porqué está escrito al lado de la
constante en `twr.py`, con la tabla.

A/B final con ×3 (mismo instrumento que §2):
```
CERTERO   publicaban 480 → 445 · cortados 39 · cambios en usuarios sin corte: 0 (los otros 441 bit-idénticos)
          twr > +100 %: 6 → 0 · twr < −50 %: 31 → 6 (uid 57 −71 %, 68 −72 %, 581 −52 %, 839 −57 %: legs ×2–3 en varias ruedas, no una foto)
          twr == −100 %: 0 · máximo publicado +96,6 %
ESTIMADO  publicaban 655 → 651 · cortados 126 · cambios sin corte: 0 · == −100 %: 0 · > +100 %: 84 → 58
port2     S&P exacto 493/493 · signo distinto 0 · KPI == perf.twr 445/445 · KPI con twr=None (1A) 0 · KPI > +100 %: 0
suites    backend 34/34 mismos nombres que la base · frontend 1411/0 · build OK · test_benchmark_diario 15/15
```

### 3.2 En 1M el KPI publica cuando la ventana visible no cruza ningún corte — se mantiene, y el aviso lo dice
El corte dice "no confío en ESE leg", no "no confío en nada". Si el rango visible cae entero
dentro de un tramo, el acumulado de esa ventana es un cociente entre dos puntos aptos del mismo
tramo: se mide. Lo que había que evitar era la contradicción en pantalla — el aviso de
`serie_partida` decía "por eso el porcentaje del período no se publica" al lado de un KPI con
número. Ahora el aviso mira si el corte cae en la ventana visible:
- con corte adentro: *"Por eso el porcentaje de punta a punta no se publica y la línea aparece cortada."*
- sin corte adentro: *"En el rango que estás viendo no cae ningún corte: el acumulado de esta ventana sí se mide. El de punta a punta, no."*
Y el titular distingue una foto dudosa (*"Hay una foto que no cierra."*) de un hueco.

Probado end-to-end inyectando en la copia de la demo una foto ×10 el 15/07
(`update snapshots set total_value=total_value*10 … date='2026-07-15'`):
```
API   twr None · motivo medicion_dudosa · 3 tramos · cortes [(14/07→15/07 salto), (15/07→16/07 salto)] · último tramo twr −1,31 %
```
(lo que mostró el browser en 1A y 1M está en §2, bloque "corte inyectado").

## 4 · 🔴 QUÉ NO VERIFIQUÉ

- ~~El gráfico con los ojos~~ → **SÍ se vio**, con un truco que conviene anotar: el panel
  pinta una sola vez tras `navigate` y sólo lo que entra en el viewport, así que
  `resize_window 1280×3900` + `navigate` + `screenshot` devuelve la página ENTERA (800×2449) con
  el gráfico adentro: la línea del S&P (punteada celeste) es una curva diaria que sube y baja
  entre 15/07 y 01/09, no dos escalones. Lo que NO vi con los ojos: Estimado y 1M (esos los
  verifiqué por fiber/DOM, §2). **Mirarlo vos**: `http://localhost:5212` → Análisis → Métricas.
- **Producción**: nada. Ni yfinance en Railway ni la pantalla real. Al deployar, mirar el log
  por `benchmarks: el S&P volvió vacío`.
- **ARS**: no toqué `benchSeriesArs`; en pesos el gráfico sigue con el shadow mensual.
- El costo del loop de `mediciones_dudosas` en el endpoint admin (670 usuarios × 2 modos ≈ 3 s
  en local); es un endpoint de admin manual.
- `valor_live` con precios a medio cargar: lo gateé por `loading`; observé el fetch espurio
  (`valor_live=70983`) una sola vez antes del gate, no lo re-medí después.
- Los 5 tests que fallan en base y no están en `fallas_conocidas.txt` no los investigué.

---

## 5 · LA NOCHE — auto-auditoría del trabajo, y lo que salió de ella

Con el "auditá lo que hiciste y avanzá" del dueño. Misma disciplina: cada afirmación medida sobre
la copia de producción; nada commiteado; el patch actualizado en el scratchpad.

### 5.1 Lo que encontré revisando mi propio diff — y arreglé

- **La misma familia vivía en el motor del ASESOR.** `twr.tramos()` (los meses que `sellar` sella y
  `twr_de` compone en el TWR del libro, "el número que justifica el fee") no tenía ninguna cota:
  **34 meses sellables en 33 clientes** tenían un leg dudoso con calidad `'ok'` (uid 282: US$4,6 →
  US$1.133 entre dos cierres, **+24.323 % en un mes**, listo para componerse). Prod no tiene
  `twr_periods` todavía (0 filas), pero `twr_por_cliente` sella al leer: el primer asesor que
  abriera el libro lo sellaba así. Ahora `tramos()` marca `quality='dudoso'` con `leg_dudoso`,
  `sellar()` incluye la calidad en el sello (cambia → revisión nueva) y `twr_de()` **no publica**
  mientras haya un mes dudoso en la cadena (`motivo='medicion_dudosa'`, `meses_dudosos=[…]`);
  cuando la foto se corrige, `sellar` lo revisa y el número vuelve solo (con test).
  `advisor_twr.twr_por_cliente` decía `"pocos_meses"` para cualquier `twr None` con meses: ahora
  el motivo del motor manda.
- **El informe FIRMADO del asesor componía por encima del corte.** `_advisor_report_payload`
  resta base contra fin sobre `medibles`, que es plano (todos los tramos). Medido para agosto en
  la copia: **3 cuentas publicaban +472,9 %, −100 % y −90,3 %** con un salto o un desborde entre
  la base y el fin. Ahora, si hay un `corte_dudoso` dentro de la ventana, `ret_pct` y
  `market_usd` van en None, `base_note='dudosa'`, y `ReportPublic.jsx` lo explica con el texto
  del motor. Re-medido: **416 publican · 3 tapados · 0 con |ret| > 100 %**.
- **Tres lectores decían "hueco" para una foto que no cierra**: el endpoint del CAGR
  (`main.py`, `reason`), `ai/builders/insights.py` e `insights_drawdown.py` tenían
  `MOTIVO_TEXTO["serie_partida"]` fijo. Ahora toman `motivo_texto` del motor.
- **El packet de IA `insights.benchmarks` era un tercer motor** (cadena contable con meses fuera
  de [−95 %, +500 %] descartados en silencio, contra el S&P desde el primer cierre mensual ≥ cutoff).
  Reescrito sobre `performance.performance`: el TWR de Certero (si no hay, el de Estimado con
  `basis='contable'`), el S&P entre las **mismas dos fechas** del benchmark diario, inflación y
  blue sobre esa ventana, y `window_from/to` declarados. Ventanas de menos de 28 días no publican
  número (`basis='ventana_corta'`): el fallback al Estimado devolvía ventanas de DOS días. El prompt
  del topic ahora exige nombrar la ventana y declarar `basis` antes de comparar. Sobre 400 usuarios
  de la copia: 268 mercado · 119 contable · 13 sin número.
- **Las cards "Comparativa" regalaban índice.** `lookupMonthly` devolvía el PRIMER precio
  disponible para cualquier mes anterior a la serie de 5 años: un aporte de 2015 "compraba" S&P al
  precio de septiembre de 2021 — **56 de 673 usuarios** tienen `monthly_entries` anteriores. Dos
  cambios: el mensual se baja con `period="max"` (^SP500TR llega a 1988) y `lookupMonthly`
  devuelve `null` antes del primer dato (la card dice "Datos insuficientes" en vez de inventar).
  El test que codificaba el defecto ("falls back to oldest") se reescribió con el porqué.
- **yfinance con autocura.** `_yf_history()` envuelve `history()`: si viene vacío o explota,
  reapunta el TzCache a un directorio nuevo y reintenta UNA vez (a lo sumo una vez por hora). Es
  exactamente el modo de falla del backend local (`tkr-tz.db` corrupto → `disk I/O error` →
  `sp500: {}` durante días). Dos tests con mocks.

### 5.2 Verificación de la noche
```
backend  python3 -m pytest tests/ : 30 fallas (base 34) · NUEVAS: ∅ · desaparecidas: 4
         (test_quota_window_corte ×2 y test_reports_variaciones_f4 ×2: pasan al cambiar el día — dependen de la fecha, no de mí)
         test_benchmark_diario.py: 20/20 · AI builders + prompts: verdes
frontend npx vitest run: 52 archivos · 1411 pasan · build OK
prod     asesor: 34 meses 'dudoso' en 33 clientes (los mismos 34) · informe agosto: 416 publican · 3 tapados · 0 fantasmas
         packet IA (400 uid): 268 mercado · 119 contable · 13 sin número
```

### 5.3 Lo que miré y decidí NO tocar
- **Estimado: chip = producto, gráfico = segmentos, KPI = último segmento.** Sigue siendo la
  decisión de diseño de la Fase 2 ("lo que las une es el PRODUCTO de dos retornos"). Cambiar la
  semántica del `twr` del Estimado de noche, sin el dueño, es más de lo que corresponde. Queda
  como la decisión abierta más grande del tema.
- **Modo ARS** (`benchSeriesArs` + shadow mensual): fuera de alcance, sin cambios.
- **`reporting/builder.py`**: usa `curva_indexada` con `_ventana_cubre` y cae a la composición
  mensual si el TWR es None; con los cortes nuevos sigue ese camino. No lo toqué.

### 5.4 🔴 Qué no verifiqué esta noche
- El informe del asesor con `base_note='dudosa'` **en el browser** (sólo el payload y el JSX).
- El packet de IA con el modelo de verdad (sólo la forma y los números del builder).
- Producción, igual que antes.

---

## 6 · EL ESTIMADO SIN CORTES — lo que el dueño vio en pantalla, medido y arreglado

**El reporte del dueño (2026-09-02):** en Estimado la línea tenía huecos que en Certero no
existían. "El estimado tendría que arrancar desde un período más antiguo, pero tampoco tener
cortes."

**Medido en la copia de producción (modo Estimado, 670 usuarios con curva):**
```
usuarios con la línea partida en ≥2 segmentos : 535   · en ≥3 : 300   · máximo 22 segmentos
cortes por CAMBIO DE REGLA contable→mercado   : 385
cortes por la regla de 45 días de silencio     : 1.001   ← aplicada a saldos contables MENSUALES
usuarios con corte dudoso                      : 126
legs contable→contable: n=10.295 · mediana 31 días · >45 días: 744 (meses faltantes en monthly_entries)
legs mercado→mercado : n=19.203 · máximo 14 días  (el cron no tiene UN hueco)
traspaso último contable → primera medición: mediana 26 días · >45 días: 58 de 420
usuarios con fotos contables fechadas DESPUÉS de su primera medición: 12 (la demo también: la del 31/07)
```

**Tres causas, tres reglas nuevas (`twr.py`):**
1. **El cambio de regla no corta: encadena por producto.** El crimen de la Fase 1 era RESTAR dos
   valuaciones de reglas distintas (139.571 al costo contra 73.604 a mercado = −47 %). Encadenar
   dos RETORNOS, cada uno medido bajo su regla, no resta nada — y es exactamente lo que `idx_est`
   ya publicaba como `twr`. Ahora el dibujo hace lo mismo: la cadena de mercado arranca donde
   quedó la contable y multiplica sólo sus propios legs. Un segmento, una línea, y el chip aparece
   en el gráfico.
2. **Un mes contable faltante no es silencio de mercado.** La cadena contable es un saldo mensual;
   un leg de 59 días es un mes que falta en `monthly_entries`, no un hueco de medición. Tope
   contable→contable: `MAX_HUECO_CONTABLE_DIAS = 400` (un año perdido sí parte). El traspaso
   contable→mercado y los legs de mercado siguen con los 45 días.
3. **La contabilidad se apaga en la primera medición real.** Desde que hay un cierre a mercado,
   la reconstrucción contable de esa misma fecha es información estrictamente peor y encadenarla en
   paralelo contaba el mismo mes dos veces. Esas filas siguen en la banda gris (`contable`),
   no en la línea ni en el número (`contable_superado` en la respuesta).

**Y dos que salieron de medir el arreglo:**
- El punto **"hoy"** del Estimado usaba `idx` (la cadena del certero, que arranca en 1,0 en la
  primera medición): un escalón al final de una línea que ahora es continua (demo: 1,149 → 0,913).
  Ahora continúa la línea dibujada y su `index_publicado` es `idx_est × (1+r)`.
- **`index_publicado` en Estimado = `idx_est`** (la cadena del chip), y el KPI de Estimado lo lee
  entre la primera y la última punta —contable o medida— de la ventana (`acumuladoPublicado` con
  `{contable: true}`). Antes leía `total` (la FORMA, que encadena la intradía): 85 de 655 tenían
  el fin de la línea ≠ el chip.

**Resultado (A/B sobre la copia, `perf_new3.json`):**
```
CERTERO   cambios en twr / index / index_publicado: 0 de 670   (bit-idéntico, tres A/B seguidos)
ESTIMADO ⊇ CERTERO (fechas de la curva): 670/670
ESTIMADO segmentos por usuario: ≥2 → 535 → 220 · ≥3 → 300 → 67 · UNA línea: 135 → 450
          los 220 que siguen partidos: 141 con foto dudosa · 58 con traspaso >45 días · 45 con un año contable perdido · 3 por intradía rota
ESTIMADO publica 655 · KPI (cadena publicada) == chip (twr) en 443 de 443 sin serie partida · distintos: 0
suites    backend 30 fallas (base 34, 0 nuevas) · 27 tests en test_benchmark_diario · frontend 1412 · build OK
DEMO      estimado: 1 tramo · 1 segmento · contable 30/09→30/06 (1,000→1,155) · mercado 11/07→hoy sigue desde 1,155 · contable_superado = 1 (la del 31/07)
```

**Copy:** el chip del Estimado dice ahora *"Recreado de tu contabilidad · desde 30/09/2025 ·
medido a mercado desde 11/07/2026"* (antes: "sólo se mueve cuando vendés", que era falso para la
mitad de la línea); el tooltip explica punteada = contable, llena = medida; el KPI dice
*"contable hasta 11/07/2026 · medido después"*.

### 6.1 Tres cosas más, del mismo rato en pantalla

- **"2A, 5A y MAX no cambian nada."** No es un bug: el rango es un tope, no un estiramiento, y con
  11 meses de historia 1A ya lo muestra todo. Lo que faltaba era decirlo. Ahora el gráfico calcula
  el rango más chico que ya contiene la primera fecha de la serie y, desde ahí, muestra debajo de
  los tabs *"1A ya muestra todo tu historial · desde 30/09/2025"* (o *"Igual que 1A: tu historial
  empieza el …"* si elegiste uno más grande), y esos tabs llevan el mismo texto en el `title`.
  En Certero: *"Igual que 3M: tu historial empieza el 11/07/2026"*.
- **La leyenda no decía cuál era la punteada.** Las dos series de la cartera comparten color y el
  ícono de la leyenda es el mismo punto verde. Ahora dice *"Demo estimado (línea punteada)"*
  (`Legend formatter`, sin tocar las claves de las series).
- **La foto intradía del final apagaba el "hoy".** El Dashboard escribe una foto de media rueda
  cada vez que se abre, así que durante el día todo usuario activo termina en una intradía
  (`source='browser'`, no apta). `curva_indexada` exigía que el ÚLTIMO punto fuera apto para
  cerrar con el valor live, y por eso el número se quedaba en el cierre de anoche mientras la
  línea seguía hasta la foto de hoy — medido en la demo después de que mi propia sesión escribió la
  foto del 02/09: chip y KPI +14,9 % con la línea terminando en +5,5 %. Ahora la pata live sale
  siempre del último punto APTO del último tramo (la intradía del medio es dibujo, no número), y
  en Estimado el índice del "hoy" parte del índice dibujado en ese apto — no del de la intradía,
  que ya traía la caída y la habría contado dos veces. Dos tests nuevos.
  A/B sin `valor_live`: 0 cambios en los dos modos (los tres A/B anteriores siguen valiendo).
  Suite: 30 fallas (base 34, 0 nuevas). Frontend 1412 · build OK.

---

## 7 · LA CAÍDA DEL −25 % EN LA CUENTA DEL DUEÑO — fotos contables desactualizadas

**El reporte:** en Estimado, la cuenta `nicolas` abría con −25,2 % entre el 31/10/2024 y el
31/12/2024, cuando sus operaciones de 2024 son dos (AMZN +10,87 en noviembre, INTC −36,66 en
diciembre).

**La causa, medida en la copia de producción:**
```
mes       foto contable (valor)   cadena monthly_entries (capital_final)   ratio
2024-10   334,28                  390,65                                   0,856
2024-11   573,85                  689,37                                   0,832
2024-12   824,12                  1.031,03                                 0,799
```
El motor tomaba el VALOR de la foto (`SINTETICO_COSTO`, copia de la cadena hecha por el import
en su momento) y los APORTES de la cadena ACTUAL (287,85 y 378,32). Las fotos quedaron al tipo de
cambio viejo cuando el migrador de TC reescribió la cadena, y el import no re-estampa
(`persister.py`: DO NOTHING). Valor de un momento contra flujos de otro: el Dietz lee la
diferencia como pérdida (−10,1 % y −16,8 %). La cadena real decía +2,0 % y −4,2 %.

**No era sólo esa cuenta:** 6.402 de 10.348 fotos contables difieren >1 % del `capital_final`
de su propio mes, en 367 usuarios; 5.133 >5 %; 3.236 >15 %; 250 usuarios con tres o más
desfasadas. 5.420 de las 6.402 están POR DEBAJO de la cadena → pérdidas fabricadas.

**El arreglo (`serie_medible`, sólo Estimado):** el valor de una foto `SINTETICO_COSTO` de fin
de mes sale de `monthly_entries.capital_final` del mismo mes; la foto vieja queda como
`valor_foto` y la respuesta cuenta `contable_realineado`. La banda gris usa el mismo valor. Con
eso el leg contable vuelve a ser exactamente `realizado_M / (capital_inicio_M + flujo_M/2)`.

**Y una segunda cota que apareció al medir el arreglo:** con retiros cercanos al capital el
denominador del Dietz se achica hasta casi cero y el cociente explota hacia ARRIBA (uid 50:
401 → 335 con un retiro de 770 → base US$16 → +4.439 % en un leg). `leg_dudoso` ahora también
devuelve `desborde` cuando `v0 + flujo/2 < 25 % de v0` (`DENOM_MIN_FRACCION`).

**Resultado (A/B, `perf_new5.json`):**
```
CERTERO   cambios: 0 de 670 (quinto A/B bit-idéntico)
ESTIMADO  usuarios con fotos realineadas: 458 · twr cambió en 395 · publican 655 → 657
          < −50 %: 34 → 17 · < −25 %: 73 → 36 (las pérdidas fabricadas) · > +100 %: 82 → 89 · > +300 %: 40 → 36
          uid 2 (dueño): −25,2 % al arranque → +2,0 % / −2,2 % · acumulado +2,1 % → +34,4 %
          uid 50: +26,6 % → +6.570 % (realineado) → +46,2 % con el corte por desborde
suites    backend 30 fallas (base 34, 0 nuevas) · test_benchmark_diario 33/33
```
Los > +100 % que quedan (uid 791 +30.300 %, 118 +17.517 %, 956 +14.064 %) son la cadena misma:
meses con realizado enorme sobre capital chico registrados en `monthly_entries` (791: +22.964
sobre 35.222 en 2023-06; 956: legs de +66 % sobre US$0,70). El Estimado reproduce la contabilidad
que hay; si la contabilidad está inflada, el número lo está. Es la familia "cadena inflada" del
audit de Reportes, no de este motor.

### 7.1 La tercera cota: el traspaso contable→mercado tiene que cerrar

Medido sobre los 361 usuarios cuyo tramo publicado tiene contabilidad y mediciones: el cociente
`primera medición / (último saldo contable + flujos)` tiene **mediana 1,000** — la cadena
realineada coincide con la realidad el día que ésta aparece, lo que confirma el §7 — y **37
usuarios fuera de [1/3, 3]**: uid 118 decía US$1,85 M de contabilidad contra US$55 k medidos
(ratio 0,03); uid 613, US$44 M contra US$2,6 k. Encadenar esas cadenas al producto publicaba
+17.517 % y +201 %. Regla nueva en `serie_medible` (sólo Estimado): si el traspaso no cierra
dentro de ×3, la cadena contable **no se encadena** (corte con `motivo='cadena_implausible'`,
cadena `'traspaso'`), el número es el del tramo medido y la pantalla lo dice: *"Tu contabilidad
no coincide con lo medido."* (`MOTIVO_TEXTO['cadena_implausible']`).

**A/B final (`perf_new6.json`):**
```
CERTERO   cambios: 0 de 670 (sexto A/B bit-idéntico)
ESTIMADO  publica 657 · cortes por cadena implausible 38 · partidos 236/670
          > +100 %: 82 → 78 · > +300 %: 40 → 31 · < −50 %: 34 → 14 · < −25 %: 73 → 33
          uid 2 (dueño) +34,4 % (arranque +2,0 % / −2,2 %) · uid 50 +46,2 % · uid 118 +17.517 % → +0,7 %
suites    backend 30 fallas (base 34, 0 nuevas) · test_benchmark_diario 35/35 · frontend 1412 · build OK
```
Los que siguen arriba (uid 791 +30.300 %, 956 +14.064 %) son cadenas **sin ninguna medición a
mercado** (`importado_sin_mediciones`): no hay contra qué contrastarlas. 791 registra +22.964 de
realizado sobre 35.222 en un mes y un promedio de ~15 %/mes durante tres años y medio; 956
encadena legs de +66 % sobre US$0,70. El Estimado reproduce esa contabilidad; corregirla es
trabajo del reconstructor, no de este motor.

**Estado:** ✅ **DEPLOYADO 2026-09-02** — commit `f15dcd4d` + merge `e40623b0` pusheado a `main` con OK
explícito del dueño. Suites verdes sobre el árbol mergeado (backend 30 fallas = las preexistentes, 0
nuevas; frontend 1416; build OK). El arreglo es de lectura: no hay migración, re-import ni
estampado; se aplica solo en la próxima carga de Métricas.

---

## 8 · EL MODO PESOS — la misma cartera, medida en pesos

Pedido del dueño: *"encará el modo pesos de la misma manera (seguro tengas que agregar la data
del TC)"*. La data ya estaba: `fx_rates_daily` tiene **`mep_venta` con 2.847 fechas desde
2018-10-29 y CERO huecos de más de 4 días en los últimos dos años**, y `blue_venta` con 5.704
desde 2011. No hubo que bajar nada: había que usarla.

### 8.1 Lo que había, medido
```
usuarios con broker en pesos                      : 758
   ven una línea hoy (cadena contable de brokers ARS) : 562 · sin serie: 196
   con ≥2 snapshots aptos (o sea: el certero ERA posible) : 573   ← y no lo tenían
modo certero en pesos                             : 0 usuarios (el toggle se dibujaba apagado)
rango                                             : clavado en 12 meses
benchmark                                         : shadow MENSUAL sobre los meses de monthly_entries
cuánto de la cartera quedaba afuera (sólo brokers ARS): mediana 0 % · >20 % afuera en 19 usuarios
```
El toggle estaba apagado por una razón estructural real: `arsMonthly` es un SUBCONJUNTO (sólo
brokers ARS) y el re-anclaje a mercado usa snapshots GLOBALES, así que hacía falta desagregar
snapshots por broker — un cambio de modelo de datos.

### 8.2 La salida: no desagregar, convertir
La curva global ya tiene todo el trabajo hecho (certero/estimado, cortes, plausibilidad, cadena
realineada). Medirla **en pesos** no necesita snapshots por broker: necesita el TC por fecha. Y
para la mediana de los usuarios "sólo brokers ARS" ya ES toda la cartera, así que el cambio de
universo afecta a 19 personas — y para bien: el resto de la app (Cartera, Dashboard) también
muestra el total.

**La matemática, y el error que evita:** cada PUNTA va al TC de su fecha (si el TC se aplica a
las dos por igual se cancela y el "retorno en pesos" es el de dólares con otro rótulo), y el
FLUJO al TC medio geométrico del tramo. ⚠️ El flujo se convierte, el **stock no**:
`net_deposited` es un acumulado, y pasarlo a pesos en cada punta y restar daría `nd·(fx1−fx0)`,
o sea la revaluación de todo lo aportado en la vida leída como un aporte del período — con
US$10.000 aportados hace un año y el TC de 500 a 1.500, un "aporte" fantasma de un millón de
pesos en un tramo donde no entró nada. Se resta en dólares y se convierte el flujo.

- `twr.serie_fx(conn, …)` → `(fn(fecha) → tc, riel)`. MEP con fallback a blue (el MEP es el
  dólar al que realmente salís; `blue_venta` es NOT NULL en el esquema y `mep_venta` se agregó
  después, por eso el fallback va en ese orden). Un fin de semana arrastra el viernes.
- `twr._leg_en_moneda(p0, p1, v0, v1)` → las dos puntas y el flujo en la moneda. **En dólares
  devuelve lo que recibió, sin una sola multiplicación**, para que el camino USD quede idéntico
  bit a bit. Se usa en las cuatro cadenas (publicada, dibujo, estimado, pata live) y en los tres
  cortes de `leg_dudoso`.
- `serie_medible`/`curva_indexada`/`performance` toman `moneda`; el endpoint, `?moneda=ars`.
- El benchmark se pasa a pesos y se re-ancla (`_en_pesos`). **`BENCH_EN_ARS`**: Merval, UVA,
  plazo fijo e inflación NO se convierten — ya están en pesos, y multiplicarlos los contaría dos
  veces. La banda contable también va en pesos.

### 8.3 Frontend
El fetch manda `moneda=ars`; la serie en pesos sale de `perf.curva` igual que en dólares; el
toggle y los tabs de rango se encienden; el benchmark sale del backend; el veredicto de
inflación usa `perf.twr` (si no, compara contra la inflación un número que el gráfico no
muestra). **`benchSeriesArs` —el motor viejo— queda de RESPALDO** para las 177 cuentas a las que
el motor no le puede dar curva: perderles el gráfico sería cambiarlo por nada. Y el tooltip
explica que el número en pesos incluye la devaluación y por eso no coincide con el de dólares.

### 8.4 Verificación
```
USD          certero 0 cambios de 670 · estimado 0 (séptimo A/B bit-idéntico; los 34 que aparecían
             contra `perf_new5.json` eran la regla `cadena_implausible` del §7.1, no la moneda)
ARS          publican certero 445 · estimado 657   (antes: 0 en certero)
             177 usuarios sin curva del motor → siguen con el motor viejo, sin perder nada
             twr certero ARS: mediana +2,5 % · ninguno > +100 % · 6 < −50 % · máx +98 % · mín −82 %
comprobación |ars − (usd compuesto con la devaluación de la ventana)|: n=445 · mediana 0,00000 ·
             p90 0,00000 · máx 0,0004   ← el residuo son los tramos con flujo, donde el TC medio
             del tramo no es el cociente de puntas. Es la definición, no un error.
benchmark    S&P en pesos: 39 valores distintos en la demo · Merval e inflación sin convertir
             (verificado: idénticos en las dos monedas)
suites       backend 30 fallas (base 34, 0 nuevas) · 43 tests en test_benchmark_diario
             frontend 1416 · build OK
browser      demo en pesos: toggle ENCENDIDO, rangos 1M…MAX, línea continua de 57 puntos desde
             30/09/2025, chip "Recreado de tu contabilidad · desde 30/09/2025 · medido a mercado
             desde 11/07/2026", KPI "+6,8 % · contable hasta 11/07/2026 · medido después"
```

**Estado:** ✅ **DEPLOYADO 2026-09-02** — commit `4d7b63e0` sobre `e258771b` (el selector de moneda
global que entró de otra sesión; fast-forward limpio, 11 archivos sin solape). Vercel y Railway
confirmados en `4d7b63e0` a los 105 s. Suites sobre el árbol mergeado: backend 30 fallas (base 34,
0 nuevas), frontend 1422, build OK.

⚠️ **Instrumento**: el worktree no tiene identidad de git configurada — `git commit` falla con
"Author identity unknown" y **deja los cambios staged**; el `git merge` siguiente hace
fast-forward y parece que se perdió todo. No se perdió: verificar con `git status` y grepear los
símbolos propios antes de rehacer nada. Commitear con `git -c user.name=… -c user.email=…`.

---

## 9 · EL VEREDICTO SE DABA VUELTA ENTRE MONEDAS

**El reporte del dueño (2026-09-02, ya con el modo pesos deployado):** *"en dólares le gano al
S&P por ~2 %, pero en pesos el S&P me gana"*. Sus capturas: USD cartera +38,0 % contra S&P
+36,9 %; ARS cartera +76,0 % contra S&P +87,1 %.

Eso es **imposible por construcción**: la devaluación multiplica a la cartera y al índice por el
mismo factor, así que el cociente entre los dos —y con él, quién gana— tiene que preservarse.

### 9.1 Dónde se separaba, medido
Reproducido en la copia de producción, uid 2, modo estimado, punto por punto:
```
factor implícito de la CARTERA (ARS/USD) : ×1,3019
factor implícito del S&P                 : ×1,3688
devaluación real 2024-10-31 → 2026-08-16 : ×1,3688   ← el benchmark la lleva entera
```
La tabla leg por leg mostró el gap en **0,00 % durante toda la parte contable** y saltando a
**−4,89 % exactamente en el punto donde la base pasa de `costo` a `mercado`** (31/05 → 29/06),
donde la devaluación fue +5,15 % (1434,8 → 1508,7). De ahí en adelante el gap queda clavado.

**La causa:** el traspaso entre reglas hereda el índice (`idx_por_base[_b] = ultimo_idx_dib`,
§6) pero **no produce leg**, así que en pesos se comía la devaluación de ese hueco. El retorno
de ese hueco no se puede medir —cruza el cambio de regla, que es lo que la Fase 1 cerró— pero
**el tipo de cambio sí se conoce**: ocurrió, y no depende de con qué regla esté valuada la
cartera.

**El fix:** `_factor_fx(p0, p1)` — el traspaso arrastra la devaluación del salto, en el dibujo y
en la cadena publicada del estimado. En dólares el factor es 1,0 y no cambia nada.

### 9.2 Un intento que se descartó midiendo
Probé acumular cada aporte a su TC histórico (`aportado_en_pesos`) en vez del TC medio
geométrico del tramo. Suena más exacto —"cuántos pesos puse de verdad"— y **es peor** para la
propiedad que importa:
```
                       distancia a "usd compuesto con la devaluación"
TC medio geométrico  : >1 % en  50 usuarios · p90 0,003 · máx 0,19
aporte a su TC       : >1 % en 246 usuarios · p90 0,054 · máx 2,03
```
Se revirtió, y el porqué quedó escrito en `_leg_en_moneda` con los números. El residuo que queda
es **intrínseco a Modified Dietz**: con el flujo ponderado a mitad de período, la identidad
`1+r_ars = (1+r_usd)·(f1/f0)` exigiría que el flujo entrara convertido a `f1` en el numerador y
a `f0` en el denominador a la vez. No hay un solo valor que lo cumpla. Con la serie diaria de
mercado el residuo es cero; sólo aparece en los legs contables, que son mensuales.

### 9.3 Verificación
```
veredicto vs S&P invertido entre monedas : 54 → 3   (los 3 son empates de < 1,3 pp, donde el
                                                     residuo del Dietz con flujos cruza el cero)
|twr ARS − twr USD × devaluación|        : mediana 0,000000 · p90 0,003 · máx 0,186 · >1 % en 50/1098
USD                                       : 0 cambios ajenos a `cadena_implausible` (octavo A/B)
demo, ventaja relativa cartera/S&P        : USD 0,90134 vs ARS 0,90134 (certero)
                                            USD 0,91062 vs ARS 0,91062 (estimado)  ← idéntica
suites                                    : backend 30 fallas (base 34, 0 nuevas) · 45 tests en
                                            test_benchmark_diario · frontend 1422 · build OK
```
Dos tests nuevos blindan el hallazgo: que el traspaso arrastre la devaluación entera, y que
quien gana en dólares gane en pesos con la misma ventaja relativa.

**Estado:** ✅ **DEPLOYADO 2026-09-02** — commit `99c3be2f` + merge `5d6f0c6d` (con `53b90dfd`,
las invitaciones del asesor). Vercel y Railway confirmados en `5d6f0c6d` a los 105 s. Suites
sobre el árbol mergeado: backend 30 fallas (base 34, 0 nuevas), frontend 1422, build OK.


---

## 10 · LA CARRERA AL CAMBIAR DE MONEDA

**El reporte del dueño:** *"hay veces que se buguea cuando cambio de verlo en ARS y en pesos"*.

**La causa, reproducida en el browser con 900 ms de latencia (la de Railway):** `currency` cambia
en el acto y el fetch de `/insights/performance` con la moneda nueva tarda lo que tarde el
backend. En el medio, `perf` sigue siendo el de la moneda anterior y la pantalla dibuja la curva
de DÓLARES con el título, el KPI y el eje en PESOS:
```
t=0    (click)   "Cartera vs S&P 500 (USD)"  total −8,23  bench 1,32
t=200            "Cartera vs S&P 500 (ARS)"  total −8,23  bench 1,32   ← rotulado ARS, datos USD
t=400            "Cartera vs S&P 500 (ARS)"  total −8,16  bench 1,40   ← recién acá los de pesos
```
En la demo la brecha es chica porque la devaluación del período medido es mínima; en una cuenta
con 37 % de devaluación acumulada son decenas de puntos, y el veredicto contra el benchmark
puede leerse al revés justo durante ese lapso.

**El fix:** el backend ya estampa `moneda` en la respuesta, así que el frontend puede
preguntarlo en vez de asumirlo. `perf` sólo existe si su moneda es la de la vista; mientras no
coincida, `perfRecalculando` y el gráfico dice *"Midiendo tu cartera en pesos…"* en vez de
dibujar la serie de la otra moneda (o la del motor viejo de respaldo, que además tiene otra
forma). El fetch inicial de `loadAll` también pide la moneda de la vista, que antes siempre era
dólares.

**Verificado en las dos direcciones**, con el mismo instrumento:
```
USD → Pesos : t=250 y t=500 → recalculando, total null, bench null · t=800 → −8,25 / 1,43
Pesos → USD : t=300 y t=700 → recalculando, total null, bench null · t=1300 → −8,32 / 1,35
suites      : backend 30 fallas (base 34, 0 nuevas) · frontend 1422 · build OK
```

**Estado:** ✅ **DEPLOYADO 2026-09-02** — commit `6f6616fb`. Vercel y Railway confirmados.

⚠️ **El patrón, para la próxima:** cualquier respuesta que dependa de un selector de la pantalla
tiene que traer el selector adentro, para que el consumidor pueda descartarla cuando el selector
ya cambió. Asumir que la respuesta en mano corresponde al estado actual es una carrera esperando
a que el backend tarde.

---

## 11 · EL RENDIMIENTO ANUAL — un motor propio que anualizaba lo que hubiera

**Pedido del dueño:** *"fijate que los rendimientos de otras secciones se calculen igual que esto,
y que el cálculo del rendimiento anual también, que todos tengan el botón certero/estimado"*.

### 11.1 Lo que había, medido
Había **dos** motores del rendimiento anual, y ninguno era el canónico:

**a) El del Dashboard** (`computeMonthlyReturns` + `computeCAGR` en el frontend, sobre la cadena
mensual). Es el que el usuario ve. Portado y medido sobre la copia de producción:
```
publica "Anual" para 521 de 670 usuarios
  meses: mediana 22 · mínimo 3 · anualiza con <6 meses: 58 · con <12: 151
  |cagr| > 100 %: 57 · > 300 %: 25 · > 1.000 %: 10
  p10 −65,3 % · mediana +4,8 % · p90 +111,9 % · máximo +6.427 % (uid 498, sobre 4 meses)
```

**b) El de `/api/goals/cagr`** (backend), que reimplementaba Modified Dietz y después hacía
`cum ** (12 / meses_span)` con `meses_span = max(1, …)` — o sea elevaba el retorno de UN mes a la
doceava potencia:
```
publica para 417 de 670 · el 100 % con 1 o 2 meses de historia (mediana 1)
  39 con >+100 % · 10 con >+300 % · 2 con >+1.000 % · máximo +16.841 % (uid 966, sobre 44 días)
```
⚠️ **Corrección a lo que dije primero:** afirmé que `Goals.jsx` proponía ese número como retorno
esperado para proyectar metas. El código lo hace, pero **`Goals.jsx` está importado en `App.jsx`
sin `<Route>`**: es una pantalla inalcanzable. El daño que el usuario veía era el del Dashboard.

El motor canónico ya resolvía las dos cosas: encadena con el mismo Dietz que el resto y **sólo
anualiza cuando la ventana llega a medio año** ("bajo medio año, anualizar es propaganda").

### 11.2 Lo que se hizo
- `_historical_cagr_global` pasa a ser un envoltorio de `twr.curva_indexada`, con `modo` y
  `moneda`. Se eliminaron el Dietz duplicado, la heurística de retiro grande propia, la
  anualización sin piso y el fallback a `monthly_entries`.
- Cuando no se puede anualizar, la respuesta trae el **acumulado del período con su ventana**
  (`total_return_pct`, `desde`, `hasta`, `dias`), que es verdadero. Y `historia_meses` reporta el
  span de la historia medida aunque no se publique número — devolver "0 meses" a alguien con 19
  meses de historia sonaba a cuenta nueva.
- `GET /api/goals/cagr?modo=&moneda=`.
- **Dashboard**: se borró su motor propio; el número sale del endpoint. La card se rotula según
  lo que es: *"Anual +16,7 % · 11m · anualizado"* o *"Desde que medimos −0,5 % · 45 días · sin
  anualizar"* — decir "Anual" sobre 44 días es la misma mentira que anualizarlo.
- **`ModoRendimiento`**: el toggle Certero/Estimado como componente compartido, en Dashboard y
  en Goals. Duplicarlo a mano se desincroniza igual que se desincronizaron los motores.

### 11.3 Resultado
```
CERTERO   anualiza 0 · acumulado con ventana 445 · sin número 225 (con motivo)
ESTIMADO  anualiza 356 sobre una mediana de 654 días · mediana +11,3 % anual · acumulado 301
          → el toggle da valor REAL acá: el "rendimiento anual" existe, pero sólo con la
            historia contable detrás, y ahora se ve cuál de las dos cosas estás mirando
usuarios que dejan de ver un anualizado inventado: 417 (endpoint) + los 58 del Dashboard con
          menos de 6 meses; el máximo que desaparece es +16.841 % → +54 % en 44 días
```

**Once tests preexistentes fallaron** y se revisaron uno por uno: nueve codificaban el motor
viejo (esperaban `1,1 ** 12` con un mes, o `basis: "contable"` del fallback, o `months` contado
por pares de cierres en vez de span en días) y se actualizaron dejando escrito el porqué. Uno
detectó una pérdida real —`months: 0` para alguien con 19 meses de historia— y eso se arregló
(`historia_meses`). Y uno documenta una **pérdida consciente**: dos mediciones separadas 19 meses
publicaban +12,2 % anual y ahora no publican, porque el motor canónico no encadena a través de
un hueco de más de 45 días. Es el precio de que las pantallas digan lo mismo.

⚠️ **El browser cazó un bug que la suite no**: el Dashboard mostraba **−52,0 %** donde el dato
era −0,52 %. El endpoint devuelve porcentaje y `VarCell` pinta con `pctSigned`, que multiplica
por 100. Verificado después del fix: Certero −0,5 % / Estimado +16,7 %, coincidiendo con la API.

```
suites: backend 30 fallas (base 34, 0 nuevas) · frontend 1422 · build OK
```

**Falta para completar el pedido:** Reportes (`reporting/builder.py`) tiene su propio motor —el
mejor hecho de los viejos, con Dietz por mes/semana/día y año geométrico— y todavía no tiene el
toggle. Es la última superficie con número de rendimiento propio.

**Estado:** implementado y verificado, **sin commitear ni deployar**.
