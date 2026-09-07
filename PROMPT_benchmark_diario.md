> ✅ **IMPLEMENTADO 2026-09-01** en el worktree `benchmark-diario` (sin commitear). Informe: `REPORTE_benchmark_diario_2026-09-01.md`. Punto 3 aprobado por el dueño ("dale") e incluido.

# EL BENCHMARK ES UNA ESCALERA MENSUAL SOBRE UNA CURVA DIARIA — y el KPI no lee el número publicado

Sos el chat IMPLEMENTADOR. El audit completo, con cada número y su instrumento, está en
`AUDIT_benchmark_2026-09-01.md` (leelo entero antes de tocar nada; acá va sólo lo que necesitás
para esta ronda). Código de referencia: `origin/main` = `dde8ee55`.

---

## 0 · LO QUE ESTÁ VERIFICADO Y NO HAY QUE REHACER

- El motor del certero (`twr.curva_indexada`, `idx` apto→apto) publica lo que dice publicar; la
  Fase 1/2 sigue en pie. **Certero tiene que quedar bit-idéntico** en `perf.twr` para los 480 que
  hoy publican (salvo lo que el §3 saque a propósito, si el dueño lo aprueba).
- El invariante estimado ⊇ certero, el eje temporal y el clamp del asesor: intactos, no los toques.
- `perf.benchmark` (`performance.benchmark_recortado`) EXISTE, viaja en la respuesta y **nadie lo
  lee** (`grep -rn "perf?.benchmark\|perf\.benchmark" frontend/src` → 0). El gráfico arma el S&P en
  `Insights.jsx:1402-1665` con `simulateSp500(globalMonthly, bench.sp500)` sobre cierres MENSUALES.

## 1 · LOS DOS HALLAZGOS DE ESTA RONDA, MEDIDOS (copia de prod 2026-08-16, port fiel del pipeline)

**B · El benchmark.** `bench.sp500` es `{YYYY-MM: cierre}` (`main.py:5145`, `interval="1mo"`), la
curva del usuario es diaria, y el ancla es `first.benchPct ?? 0` = el cierre de FIN del primer mes
visible (`Insights.jsx:1624`). Certero · 1A, 484 usuarios con benchmark:

```
valores distintos del S&P en la ventana : mediana 2 (sobre 44 filas) · 64 usuarios lo ven PLANO en 0 %
1M                                       : 484/484 con ≤2 valores → un solo escalón
|S&P que muestra − S&P real mismas fechas| : mediana 0,81 pp · p90 2,05 pp · >1 pp en 220 · >2 pp en 152
signo dado vuelta ("le ganás" / "te gana") : 21 usuarios
ancla en OTRO mes (huecos de monthly_entries): 3 usuarios ven "S&P +35,1 %" donde hizo +3,8 % (uid 878, 437)
ancla null → 0                              : 11 usuarios ven el S&P en 0 % plano (uid 513, 1117)
```

Nadie tiene más de 3 meses medidos: un desfasaje de hasta un mes en el ancla ES la comparación.

**K · El KPI de certero.** `Insights.jsx:2684`: `cumulativeReturnPct = lastRow[_kTotal]`, que es
`(pt.index − 1)·100` rebaseado, y `pt.index` es `idx_por_base` (`twr.py:1425`): el índice DIBUJADO,
que encadena las fotos intradía y no tiene el guard del cero absorbente. El publicado es `idx`.

```
KPI == perf.twr : 403 de 480     KPI ≠ perf.twr por >5 pp : 20     KPI publica con twr=None : 11
uid 745  KPI +642,9 %   perf.twr +6,6 %    (intradía 06-26 US$3.329 → intradía 06-27 US$22.746)
uid 865  KPI −100 %     perf.twr −7,5 %    (flujo 2× el valor en un leg de dibujo → idx_por_base = 0)
uid 486  KPI +217,8 %   perf.twr None      (serie_partida: el rebase une el tramo 1 con el 2)
```

Y el sub de ese KPI dice «vs S&P: X % · mismo período» con el X de B. Las dos mitades están mal.

## 2 · QUÉ HACER

### 2.1 Benchmark diario, servido por el backend, anclado en la primera fecha de la curva

1. `_fetch_sp500_monthly` / `_fetch_yf_monthly`: agregar el DIARIO (`period="2y", interval="1d"`,
   `{YYYY-MM-DD: close}`) para `^SP500TR` (fallback `^GSPC`), `SHV`, `GLD`. El mensual se queda:
   lo usan las cards "Comparativa" y `monthly_insight`. Clave nueva, p.ej. `sp500_d`.
2. `performance.benchmark_recortado` pasa a resolver por FECHA: para cada fecha de la curva, el
   cierre de ese día o del último hábil anterior; índice 1,0 en la PRIMERA fecha de la curva (no en
   su fin de mes). Para `"hoy"`, el último cierre. Para los porcentuales (`inflation_ar`,
   `plazo_fijo`) el mensual sigue valiendo: son datos mensuales de verdad.
3. `Insights.jsx`: la línea del benchmark del gráfico sale de `perf.benchmark` (un punto por fila
   de `benchSeriesUsd`, misma clave). El rebase al inicio del rango visible (`:1631-1636`) se queda —
   es correcto — pero sobre el punto diario. `buildShadowFromSim`/`simulateSp500` dejan de
   alimentar el gráfico en USD (en ARS no toques nada: fuera de alcance).
4. Mandá `valor_live` en la llamada (`:300`), para que la curva y el benchmark terminen el mismo día.

Criterio de salida B: con el port de `scratchpad/port.mjs` (o el tuyo, si mide lo mismo),
**|bench APP − S&P real entre las mismas fechas| < 0,1 pp en los 484 y 0 con signo distinto**; en
1M tantos valores distintos como ruedas; los 3 "anterior" y los 11 "null" en 0.

### 2.2 El KPI lee el índice publicado

1. `curva_indexada` emite además `index_publicado` por punto = `idx` vigente (sólo cambia en los
   aptos; en los no-aptos arrastra el último). `apto` ya viaja.
2. El KPI de certero rebasea `index_publicado` entre el PRIMER y el ÚLTIMO punto apto de la ventana
   visible, y da `"—"` si hay <2 aptos o si la ventana cruza un corte (`serie_partida` dentro del
   rango). En estimado no cambia nada esta ronda (ver §4).
3. El sub «vs S&P: X % · mismo período» toma X del benchmark diario entre esas mismas dos fechas.

Criterio de salida K: en 1A, `KPI == perf.twr` (±0,05 pp) en los 480 y **0** KPI con `twr None`.
En 1M puede diferir (ventana distinta): eso NO es un bug, no lo "arregles".

### 2.3 Sólo si el dueño lo aprueba: cota de plausibilidad en la curva

46 de los 480 certero publicados tienen UN leg diario ×>2 o ×<0,5 entre cierres aptos con el aportado
quieto, y son exactamente los 6 de más de +100 % y los 31 de menos de −50 % (uid 282 +25.757 %,
uid 513 −100 %). La regla ya decidida para el asesor (pico > 5× la cartera → no publicar, a la cola)
aplicada al leg: ratio fuera de [1/5, 5] con |flujo| < 10 % del valor → cortar el tramo como el
desborde del denominador (`twr.py:1176-1181`), `motivo='medicion_dudosa'`, uid a
`/api/admin/diagnose-reportes-basis`. En las TRES cadenas (`idx`, `idx_por_base`, `idx_est`).
Criterio: los 46 dejan de publicar; los otros 434 bit-idénticos.

## 3 · 🔴 LO QUE NO SE PUEDE ROMPER

- `perf.twr` certero bit-idéntico en los 480 (A/B con `perf_all.json` del scratchpad o el tuyo).
- El invariante estimado ⊇ certero (puntos de la curva).
- Las cards "Comparativa con benchmarks" y `ai/builders/monthly_insight` siguen con el mensual.
- El modo ARS no se toca.

## 4 · FUERA DE ESTA RONDA (anotado en el audit, decisión del dueño)

- Estimado publica tres números (chip = producto de dos cadenas, gráfico = segmentos desde 0, KPI =
  último segmento): 223 de 637 difieren >5 pp; uid 118 chip +125.654 % / KPI +0,7 %.
- Cero absorbente en `idx_est` e `idx_por_base` (10 usuarios en −100 % exacto, 21 con un punto en 0).
- 8 usuarios con solapamiento contable/mercado dentro del tramo publicado.
- El packet `ai/builders/insights_benchmarks.py` es un tercer motor (cadena contable con meses
  descartados + S&P desde el primer cierre ≥ cutoff).
- yfinance vacío en el backend LOCAL (`/private/tmp/yf-cache/tkr-tz.db` corrupto). Si en prod
  `/api/benchmarks` trae `sp500: {}`, va primero que todo lo demás.

## 5 · REGLAS

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard   (HEAD f50beefb, 17 commits detrás de origin/main)
```
- ⚠️ **Antes de empezar, mergeá `origin/main`** (`git merge-tree` primero; resolvé EN EL LUGAR,
  nunca copiando archivos de un sandbox). Los 3 commits del cobro sin pushear quedan como están.
- ❌ NO pushees. Pushear a `main` ES DEPLOYAR A PRODUCCIÓN. ❌ NO uses `git stash`. ❌ Ninguna `.db`
  en escritura: copiala y abrila con `mode=ro&immutable=1`.
- La suite: `python3 -m pytest tests/` (escribí la salida a archivo; `timeout` no existe en macOS;
  compará CONJUNTOS de `^FAILED `). Baseline: `tests/fallas_conocidas.txt`.
- Datos: copia estampada y `perf_all.json` / `port.mjs` en el scratchpad del audit (ruta en el
  AUDIT §1). Copiá el harness a un directorio tuyo antes de usarlo.

## 6 · QUÉ ENTREGAR

1. Los cambios (sin commitear), con `file:line`.
2. El A/B: `perf.twr` certero antes/después (0 diferencias), y la tabla de §1 recalculada.
3. Conjuntos de tests que fallan, antes y después.
4. Capturas del browser: Certero 1M y 1A, Estimado MAX, con un usuario medido (demo, después de
   reponerle la posición AAPL a 132,26 o con otra cuenta) — y decí si el S&P se ve como curva o
   como escalera.
5. 🔴 **"QUÉ NO VERIFICASTE"** al final, explícito.
