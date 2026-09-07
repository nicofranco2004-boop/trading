# FASE 1 — Parar lo que sangra

Sos el chat IMPLEMENTADOR. Este prompt lo escribió el chat auditor, que verificó **ejecutando**
todo lo que vas a leer acá: cada número tiene detrás un comando que se corrió contra la copia
de producción del 16/08 o contra el código real del worktree.

---

## 0 · DÓNDE TRABAJÁS Y QUÉ NO PODÉS HACER

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama:     fix/reportes-guard-benchmark
```

**Prohibido, sin excepción:**
- ❌ NO commitees, NO pushees. Pushear a `main` ES DEPLOYAR A PRODUCCIÓN (Vercel + Railway).
- ❌ NO uses `git stash`. Hay trabajo sin commitear de tres rondas en ese árbol.
- ❌ NO abras `backend/trading.db` en escritura.
- ❌ NO toques la Fase 2. El toggle contable/certero es una decisión ya tomada del dueño y NO
  va en esta fase. Si tu arreglo te tienta a construir un toggle, parate: no es acá.

**Para datos reales**: la copia de producción está en `~/Downloads/trading-2026-08-16.db`
(933 MB). Copiala al scratchpad y usá la copia. No la abras con `?mode=ro` (está en WAL);
sobre la copia se abre normal. La `backend/trading.db` del worktree **no sirve para verificar
nada**: no tiene al uid 452 y tiene 56 filas de snapshots.

---

## 1 · EL BUG — UNA SOLA FAMILIA

> Comparar un valor medido a **PRECIO DE MERCADO** contra un valor calculado **AL COSTO
> CONTABLE**, y publicar la diferencia como rendimiento.

La app tiene dos formas de saber cuánto vale una cartera:

- **MERCADO** — posiciones × precio real. Sale del cron (`source='cron'`), del browser, o de
  la reconstrucción histórica.
- **COSTO** — la cadena contable `monthly_entries`
  (`capital_final = capital_inicio + depósitos − retiros + pnl_realizado`, con
  `pnl_unrealized = 0`). Nunca se re-ancla al mercado. Llega a `snapshots` como
  `source='import'`.

Cuando un cálculo toma una punta de cada lado, la diferencia **no es rendimiento**: es el
escalón entre dos reglas de medición.

Once rondas lo arreglaron once veces y volvió once veces, **siempre** porque el fix cambió una
propiedad de la que dependía otro lector que nadie miró.

---

## 2 · EL TAMAÑO REAL (medido, no estimado)

Corriendo `twr.clasificar_serie` + `twr.es_apto` reales sobre los **822 usuarios** de la copia
de producción:

| | |
|---|---|
| filas `sintetico_costo` (base = costo) | **13.265 de 40.717 (32,6 %)** |
| **usuarios con base al costo Y punta medida** | **603 de 822 (73 %)** |
| usuarios sin **ninguna** fila apta | **178** |
| usuarios sin **ninguna** fila dibujable | **173** |
| filas `source='import'` / legacy `NULL` / `cron` | 475 / 34.205 / 6.029 |
| filas `mtm_backfill` en producción | **0** (y `mtm_coverage` ni existe) |

**No es un usuario que reportó un bug: son 603 publicando un % que mezcla reglas.**

Y ojo con lo último: toda la maquinaria de cobertura / mediana / piso 0,90 de las rondas 7-10
es para una feature **apagada**. Lo que sangra hoy son las filas `import` y las legacy.
No inviertas un minuto ahí.

---

## 3 · LA REGLA QUE NO PODÉS COLAPSAR

Son **dos preguntas distintas**. Unificarlas es el error que hizo volver el bug once veces:

| pregunta | alcance | qué la responde |
|---|---|---|
| ¿este punto se puede **DIBUJAR**? | por **SERIE** (continuidad) | `clase ∈ ACEPTA_LINEA` = `medicion`, `reconstruido`, `intradia` |
| ¿este punto puede ser **PICO o DENOMINADOR**? | por **FILA** (hecho de medición) | `apto` |

Una foto INTRADIA está valuada **a mercado** (posiciones × precio) pero no es un cierre:
**sostiene la línea, no puede fijar un pico**. Son 249 filas en 99 usuarios.

- La ronda 9 separó las dos por fila → la curva se hizo polvo.
- La ronda 10 las unificó por serie → volvió el pico fabricado.
- **La respuesta correcta: continuidad del dibujo por SERIE, hecho de medición por FILA.**

⚠️ **Trampa de nombres**: `main.py:5020` hace `d["sintetico"] = not d["apto"]`. O sea `sintetico`
**colapsa las dos preguntas**: una foto INTRADIA sale marcada `sintetico=True` cuando NO es
fabricada — está medida a mercado. No uses `sintetico` para decidir si dibujar.

✅ **Buena noticia: no necesitás tocar el backend para esto.** `/api/snapshots` ya manda
`clase`, `base` **y** `apto` por fila (`main.py:4988-5020`). El frontend tiene todo el material
para separar las dos preguntas.

---

## 4 · EL INVENTARIO — verificado con file:line

### 4.1 🔴 EL NÚMERO QUE EL USUARIO REPORTÓ NO ESTÁ DONDE DECÍA EL PLAN

El plan atribuía el **−65,82 % / −US$129.416,82** a `evolution.js`. **Es falso.** Reproducido
al centavo contra la copia de producción:

```
useMonthlyData.js:404-420 (bloque isLiveMonth)
  baseSnap = 2026-07-31   196.631,56   source='import'   ← AL COSTO
  lastSnap = 2026-08-16    67.214,75   source='cron'     ← A MERCADO
  deltaUsd = 67.214,75 − 196.631,56 − 0 = −129.416,82
  deltaPct = −129.416,82 / 196.631,56  = −65,82 %        ← COINCIDE EXACTO
```

La ironía: ese bloque **se escribió para matar este bug** ("Quick-win C1 … esa mezcla de bases
produce un rendimiento fantasma (ej. −64.9%)"). Elige `baseSnap` = último snapshot anterior al
mes **sin mirar `apto`**, y el comentario asume que ese snapshot es MtM. Para 603 usuarios no lo es.

⚠️ **PERO CUÁL DE LOS DOS BLOQUES GANA DEPENDE DE `source` — medilo antes de tocar nada.**
Verificado con fixture no-degenerado (`capital_inicio=100.000` ≠ la foto de 196.631,56):

| caso | `source` | con foto al costo | sin foto al costo |
|---|---|---|---|
| D1 / D2 | `manual` | −32.100 / −32,10 % | −32.100 / −32,10 % ← **idéntico** |
| D3 / D4 | `partial` | −128.731,56 / **−65,47 %** | +685,25 / **+1,02 %** ← **el signo se da vuelta** |

O sea: en el camino `manual` el bloque `:407-411` es **INALCANZABLE** (lo pisa `:539`), y la foto
al costo no cambia nada. El `:407` sólo manda cuando `source='partial'` (`capital_inicio` o
`capital_final` en 0), porque el clobber de `:539` busca `m.source === 'manual'` (`:514`) y no
encuentra nada. **Ahí sí flipea el signo**, y llega a `MonthlyTeaser.jsx:88-99` sin guard
(`showPct` sólo excluye `source==='derived'`, `:60`).

Los dos bloques están rotos, pero por caminos distintos. **Determiná empíricamente cuál aplica
al usuario que estés mirando antes de declarar nada arreglado.**

### 4.2 🔴 LA TRAMPA: FILTRAR POR `apto` EN `:407` NO ARREGLA EL CASO NORMAL

`useMonthlyData.js:539-551` **pisa** lo que calculó el bloque anterior:

```js
if (isCurrentYear && endSource === 'live' && newestWithCapital) {
  newestWithCapital.deltaUsd = liveValue - (newestWithCapital.startUsd || 0) - flows
  newestWithCapital.deltaPct = ...
}
```

`startUsd` es `capital_inicio` de `monthly_entries` = **la cadena contable**. `liveValue`
(`:473`) es el snapshot más nuevo **sin filtrar por `apto`**. O sea: 130 líneas después, el
mismo archivo vuelve a restar mercado − contabilidad y **sobrescribe** el resultado cuidado.

Probado: el número publicado en el camino `manual` es **−32.100 = liveValue(67.900, mercado) −
capital_inicio(100.000, contable) − flows**, y es **insensible** a que la foto al costo esté o
no esté. El bloque de arriba se computa y se tira.

**Los dos bloques hay que arreglarlos juntos o el fix es invisible en pantalla.**
Éste es exactamente el patrón que hizo fallar las once rondas: arreglar un lugar mientras otro,
más abajo, lo sobrescribe.

Y `liveValue` (`:473`) tiene exposición real medida en producción: **197 usuarios con `source`
NULL y 8 con `source='import'`** (de 822) tienen su fila **más nueva** fuera de base de mercado.
Para ellos el "valor live" ES la cadena contable.

### 4.3 Los tres helpers de `evolution.js` (el reclamo original, pero da OTRO número)

| línea | helper | filtra | consumidores |
|---|---|---|---|
| `:56` | `buildPortfolioValueSeries` | ❌ no | `Dashboard.jsx:521`, `HomeMobile.jsx:156` |
| `:159` | `computeReturnDelta` | ❌ no | `Dashboard.jsx:574`, `HomeMobile.jsx:186` |
| `:202` | `computeDailyPnl` | ❌ no | `Dashboard.jsx:567`, `HomeMobile.jsx:195` |
| `:234` | `buildEvolutionFromSnapshots` | ✅ **sí** (`:244`) | `Insights.jsx:481` |

El filtro correcto ya existe diez líneas más arriba, en el mismo archivo.

Medido con la serie real de 452 (`computeReturnDelta`, `sinceDate='2026-08-01'`):

```
sin live values    Este mes: −208.001,38   −105,78 %   base=2026-07-31
con live values    Este mes: −125.479,82    −63,81 %   base=2026-07-31
con filtro apto    Este mes:     −761,60     −1,13 %   base=2026-08-14
```

⚠️ **El número exacto depende de qué le pasás como `liveValue`/`liveNetDeposited`, y Dashboard
SÍ se los pasa** (`Dashboard.jsx:574`, desde las posiciones vivas). Lo que **no** depende de eso
—y es el bug— es que `prev` sea la fila del import: `desc.find(s => s.date < sinceDate)`
(`:179`) no mira `apto`, y el denominador es literalmente `prev.total_value` (`:192`).
**No persigas el número: perseguí la fila que hace de base.**

Ese **−1,13 %** es la "pérdida mínima" que el usuario veía en la otra pantalla. El arreglo es correcto.

⚠️ Y ojo con el framing temporal: cuando la fila más nueva no es apta, `computeDailyPnl` puede
publicar bajo el rótulo **"Hoy" / "P&L Día"** una diferencia de **27 días** (`dayDiff=27`,
`Dashboard.jsx:900` recién ahí dice "Últimos N días"). Caso real en prod: **uid 185**.

### 4.4 🔴 UN SEGUNDO POZO DENTRO DEL MISMO HELPER — el filtro `apto` NO lo tapa

```js
// evolution.js:122-124
function netDepositedOf(s) {
  return (s.net_deposited && s.net_deposited > 0) ? s.net_deposited : (s.total_invested || 0)
}
```

El `> 0` lee un `net_deposited` **negativo** (retiros netos > aportes, perfectamente legítimo)
como **faltante**, y cae a `total_invested`, que es **costo**. El de 452 es −5.726,38.

Medido en producción: **4.744 filas (11,7 %) en 192 usuarios** tienen `net_deposited < 0`.

Es la misma familia en otro lugar. Arreglalo: distinguí *ausente* (`null`/`undefined`) de
*negativo*. Un `net_deposited` negativo es un dato válido, no un hueco.

### 4.5 Consumidores a DOS SALTOS y superficies que el plan no listaba

| file:line | qué publica |
|---|---|
| `Dashboard.jsx:551` → render `:962-966` | `periodChange`: chip de variación **pegado al gráfico**. No nombra `snapshots`; llega vía `buildPortfolioValueSeries`. Denominador = `first.valueUsd` (la fila al costo). |
| `Dashboard.jsx:542` → `domain` en `:1018` | `chartMax`/`chartMin`: **la fila al costo fija el techo del eje Y**. Es el acantilado que el usuario ve dibujado. |
| `Dashboard.jsx:533` | `convertSeriesToArs` consume la salida de `buildPortfolioValueSeries` (se arregla solo si arreglás el productor). |
| `HomeMobile.jsx:153` → `:351,355,367-368` | sparkline 30d + los rótulos literales "Hace 30d · $196.631" vs "Hoy · $67.214". **Agravante**: `buildPortfolioValueSeries:94-95` hace *prepend* del último punto anterior al corte como ancla → **re-inyecta el punto al costo aunque quede fuera de la ventana de 30 días**. Acortar la ventana no lo salva. |
| `useMonthlyData.js:473` | `liveValue` toma el snapshot más nuevo sin mirar `apto` → el día que importás, el "valor live" ES la cadena contable. |
| `Positions.jsx:1350-1371` | variación diaria: `totals.value` (mercado) − `snapshots.find(s => s.date < today)` (puede ser `import`). ⚠️ `:1568` dice que el banner está *deshabilitado* — **verificá si renderiza antes de tocarlo**; si no publica, no es Fase 1. |
| `Insights.jsx:1643` (`snapChart`), `:1651` (`dailyVariation`) | no filtran; calculan vsYesterday/vsWeek sobre `total_value` crudo. |
| `Insights.jsx:867-878` | 🔴 **la vista en PESOS corre sobre un motor viejo distinto**: `arsMonthly` (`:674-687`) lee `monthly` crudo y nunca pasa por `applyMtmToMonthly` (el único llamado es `:437`, y arma `globalMonthly`, que `arsMonthly` nunca toca). En `:867-871`, `lastCfArs` = `capital_final × fx` (contable) contra `valueNowArs` = Σ posiciones × precio × fx (mercado). Afecta el veredicto "¿le ganaste a la inflación?". ⚠️ **La estructura está verificada; cualquier % concreto que hayas leído de este renglón es inventado — medilo vos.** |
| `insightsModel.js:621` | 🔴 **El guard se auto-desactiva justo para las cuentas que tienen el bug.** `applyMtmToMonthly` hace `if (s?.sintetico) continue`, descartando las fotos sintéticas **antes** de armar `ultimoDelMes`: para un usuario cuyas fotos de fin de mes son **todas** sintéticas, el re-anclaje es un **no-op** y la cadena contable pasa entera. |

### 4.6 Superficies del asesor — el asesor se lo dice al cliente

| file:line | la frase que publica |
|---|---|
| `main.py:35545` → `AdvisorDashboard.jsx:596-600` | **"Su ganancia cayó 167% desde el mejor momento"**. `max_snap` hace `SELECT MAX(total_value − net_deposited) … GROUP BY user_id` **sin `apto`, sin `base`, sin `source`**. Un pico que salió de una fila al costo **nunca fue un precio: nadie le pagó eso nunca**. |
| `main.py:35464` → `AdvisorDashboard.jsx:208-209` | **"el mercado restó US$65.967"**. `v_then` = último snapshot ≤ fin del mes anterior (la foto del import, al costo); `v_now` = cierre del cron a mercado. Es el único delta del libro que las rondas 9-11 NO filtraron. |
| `main.py:35484` → `AdvisorDashboard.jsx:702-706` | **"+39,6%"** para un cliente cuya propia pantalla dice "—". `latest` es `MAX(date)` sin filtro. |
| `main.py:34039` (`_advisor_book_chat_context`) | El mismo +39,6 % entra al **prompt de la IA del libro** como `ret_pct`, y el prompt (`main.py:27914`) le ordena **rankear clientes** con ese número. |
| `main.py:34001` | `weight_pct`: numerador a mercado, denominador al costo → la única posición de un cliente aparece como 53 % de su cartera en vez de 100 %. |
| `main.py:35670` | La curva del libro; el pie del gráfico dice *"la brecha entre las dos es lo que puso (o sacó) el mercado"* — convierte el escalón de reglas en una afirmación sobre el mercado. |

**Lectores del asesor que YA están sanos** (las rondas 9-11 los arreglaron — **no los toques**):
`advisor_alerts.py:250-274`, `advisor_brief.py:288-312` (el email de cierre),
`main.py:35213-35244` (`_es_base_de_mercado`), `main.py:35430-35443` (`_delta` del hero),
`main.py:35746-35749` (`advisor_book_detail`), `main.py:34152-34160` (el informe **firmado**).

### 4.6.1 🔴 LOS LECTORES DEL BACKEND — y la asimetría que nadie vio

**No son 52: son 56 sitios** que leen `snapshots` / `snapshots_medibles` fuera de tests
(33 en `main.py`, 4 en `twr.py`, 4 en `reporting/builder.py`, resto repartido). El número
heredado estaba mal; éste está contado.

**⚠️ EL HALLAZGO ESTRUCTURAL — todas las rondas miraron la punta equivocada:**

> Los guards que las rondas 9-11 agregaron filtran el **BORDE DE APERTURA** (la base).
> **Ninguno filtra el BORDE DE CIERRE** (la punta). Y la punta también puede ser una fila al costo.

Cuando el último snapshot del usuario es la foto del import (el día que importa, y para los
603 usuarios con base al costo), el número sale **invertido**: en vez de un −65 % fantasma
publica un **+96 % fantasma**. Mismo crimen, signo opuesto, y por eso nadie lo buscó.

| file:line | qué publica |
|---|---|
| `main.py:31698` | 🔴 Motor de KPIs de Reportes: **YTD +96,63 %**, Δ1d **+177,66 %**, Δ7d/Δ30d +86,63 % sobre una cartera cuya última medición real es 67.214,75 contra 100.000 al arranque (o sea **−33 %**). Filtra la base, **no la punta**. |
| `main.py:22532` | 🔴 Ese YTD fabricado entra al chat de la IA **con la orden explícita de citarlo**: `_note: "Retornos REALES precalculados — citalos, NO hagas aritmética nueva"`. El modelo le dice al usuario que le ganó al S&P y a la inflación. |
| `main.py:32071` | P&L del mes en curso: cierra contra el último snapshot **crudo**. Headline *"Mes sólido — +96.6%"*, `basis_incomparable: false`, con **0 operaciones y 0 flujos**. |
| `ai/builders/monthly.py:100` | Segundo call-site de `_latest_snapshot_value`: el mismo *"Mes sólido — +96.6%"* al prompt del LLM. |
| `main.py:35546` | 🔴 Pico del drawdown del libro = `MAX(total_value)` sobre toda la tabla → *"Su ganancia cayó 121 % desde el mejor momento"* sobre una serie medida **perfectamente plana**. **Termina en el mail del asesor.** |
| `advisor_groups.py:238` + `:273-277` | La regla `losing` de los **grupos del asesor** decide **pertenencia** comparando el último snapshot crudo contra el aportado. No es un % publicado: es qué clientes entran a un grupo. |
| `ai/builders/goal.py:52` | El **fallback** del packet de metas publica `progress_pct: 85,52` y `required_return_pct` desde una fila al costo, para un usuario **sin ninguna fila medible**. (El fallback es el agujero: el camino principal usa `snapshots_medibles` y está bien.) |
| `main.py:17598` | (BAJO, admin) `pico_cartera` = `MAX(total_value)` crudo como denominador del barrido de flujos absurdos. |

**Lectores del backend que YA están sanos** — 25 verificados. **No los toques**:
`main.py:4970` (`/api/snapshots`, es el ejemplar), `main.py:35435-35437` (`_delta`),
`main.py:31920` (`_ytd_delta`, con `mtm_only=True` + `_border_is_fresh`),
`main.py:17355`/`17457` (diag), `twr.py:477/591/1002/1066`,
`reporting/builder.py:209/232` y `888-899`.

**⚠️ NO toques `main.py:33405` (el AUM del asesor).** Parece el mismo bug y **no lo es**: el repo
ya se niega a "arreglarlo" y lo documenta como contrato deliberado en `main.py:1377-1381` —
*"Los que legítimamente quieren TODO —el AUM del asesor, que MUESTRA un valor y no lo resta—
siguen usando `snapshots`"*— y `main.py:35745-35749` lo repite palabra por palabra. **Mostrar**
un valor no es **restar** dos valores. Ése es el guard, está puesto a propósito, dejalo.

⚠️ **Calibración**: estos números salen de un fixture propio del auditor, no de producción — son
**reales del lector real**, pero miden el mecanismo, no cuántos usuarios lo sufren hoy.
Exposición medida en prod: de 822 usuarios, **644 tienen su última fila MEDIDA** (no afectados)
y **178 la tienen al costo**. Cuando arregles cada uno, medí vos el impacto contra la copia.

**Dos superficies más del asesor que ningún hallazgo citaba:**
- `main.py:34064` — `exposure[].clients[].weight_pct` arrastra el mismo denominador al costo, y
  el prompt lo nombra textualmente como *"TU fuente para ¿a quiénes afecta X? y concentraciones"*
  (`main.py:20106`).
- `main.py:33960-33964` — `_advisor_book_chat_context` **re-emite `queues`, `flows_month` y
  `distribution` TAL CUAL** al prompt de la IA del asesor. O sea: cada bug de arriba llega a la
  IA por una cuarta puerta, y arreglar la pantalla no lo tapa.

### 4.7 Reportes y los builders de la IA

**La IA es una superficie de publicación.** Un drawdown o un TWR que llega al prompt sale por
la boca del modelo aunque la pantalla lo tape. Verificado: hay packets donde la pantalla dice
*"Mes sin base para medir el rendimiento"* y el packet de la IA dice **−63,0 %** para el mismo dato.

| file:line | qué publica |
|---|---|
| `reporting/builder.py:1061` (`fetch_holdings_snapshot_at_or_before`) | 🔴 **Los movers**. `SELECT date, holdings_json … ORDER BY date DESC LIMIT 1`: **sin `source`, sin `base`, sin `apto`, sin `mtm_coverage`** — estructuralmente ciega. Publica `AAPL −US$65.967 · −47,3 %` bajo el titular "Mes sin grandes movimientos" (`Reports.jsx:716-728`), con `movers_available=True`, o sea la UI lo presenta como dato bueno. **Es exactamente el síntoma reportado.** |
| `ai/builders/reports.py:75` | Al prompt: `twr_year_pct: −63.0`, `worst_month: −63.0`, `winrate_monthly: 0.0` — con `trades_year: 0` y `realized_pnl_year_usd: 0.0`. El mes en curso trae `capital_final` reescrito por `/api/monthly/sync-unrealized` (`main.py:10799-10812`) con MtM vivo, contra un `capital_inicio` contable. |
| `ai/builders/insights.py:256` | `twr_pct: −63.0` **en el mismo packet** donde `drawdown: {insufficient_data: true}`. El mismo builder se niega a afirmar un drawdown por falta de mediciones y a tres campos de distancia afirma un retorno de −63 %. |
| `reporting/detectors.py:178` | `BEAT_BENCHMARK`: *"Le ganaste al S&P 500 — Tu portfolio: +1,2 %"* sobre un mes con `basis='contable'`. `basis_incomparable` lo apaga, pero `basis=='contable'` **no**. |
| `reporting/detectors.py:241` | `STREAK_POSITIVE`: *"Vas 4 meses positivos seguidos"* sobre deltas contables (= `pnl_realized/capital_inicio`). El mercado no entró nunca en la cuenta. |
| `reporting/builder.py:1374` | *"Quedaste 1,0 puntos por encima del S&P 500"* con `metrics.basis == 'contable'`: retorno contable restado contra un benchmark de mercado. |

Los dos últimos y `detectors.py:178` son **literalmente lo que la Fase 2 va a prohibir en modo
estimado** (comparación vs benchmark, rachas). Hoy se publican sin gate de `basis`.
`detect_reversal` (mismo archivo) tiene el mismo defecto — verificado con fixture propio.

🔴 **Los movers NO se arreglan con un filtro por fila.** El reconstructor **marca cada activo al
costo dentro del propio `holdings_json`** (`scripts/backfill_historical_mtm.py:629-631` escribe
`holdings: [{asset, value_usd, at_cost…}]`) y `compute_movers` **ignora esa marca**. Un filtro a
nivel de fila deja pasar la fila entera con activos al costo adentro. Hay que mirar la marca
por activo, o no publicar movers cuando el borde no es de mercado.

**Builders de la IA que YA están sanos** (usan `snapshots_medibles` / `serie_medible` — no los toques):
`ai/builders/home.py:97`, `dashboard.py:106`, `insights_drawdown.py:52-69`,
`insights.py:193-212` (la sección del drawdown), `dashboard_evolution.py:43`.
También sanos: `builder.py:227-266` (el guard clase+base de la ronda 11) y
`builder.py:600-635` + `968-1000` (`_basis_is_incomparable`).

**⚠️ DOS CALIBRACIONES — medilas antes de actuar, no las tomes de un reporte:**

1. **`vs_sp500_pct` YA está arreglado.** La creencia de que "guarda el retorno del S&P y no el
   exceso" es **vieja**: `schema.py:79-84` dice que el retorno del benchmark vive ahora en
   `sp500_return_pct` / `inflation_pct`, y `vs_sp500_pct` es el exceso. No lo "arregles" de nuevo.

2. **El agujero `INDETERMINADO` del chip Δ1d/7d/30d es REAL pero son 4 filas en producción.**
   `main.py:31856` (`_snapshot_delta`) pide `accept=(MEDICION, INDETERMINADO)`, y el guard de
   `builder.py:266` sólo rechaza `c in BASE_MERCADO and b != VALUADO_A_MERCADO` — `INDETERMINADO`
   no está en `BASE_MERCADO`, así que pasa entero con `base='costo'`.
   **Pero eso es deliberado y está documentado**: el docstring de `builder.py` dice
   *"EL GUARD ES ESTRECHO A PROPÓSITO, NO ES `es_apto`… endurecerlas acá le borraría el chip a
   los usuarios legacy"*. Censo real de producción: `medicion` 27.203 · `sintetico_costo` 13.261 ·
   `intradia` 249 · **`indeterminado` 4**. Antes de romper un guard que el repo escribió a
   propósito con el motivo adentro, medí a cuántos afecta. Acá: cuatro filas.

### 4.8 Postgres — mucho menos grave de lo que decía el plan, salvo UNA cosa

**⚠️ LEÉ ESTO ANTES QUE NADA: el pánico del plan ("el día que se prenda `DATABASE_URL` no se
escribe un solo snapshot") es FALSO.** Se verificó ejecutando y se cayó por tres lados:

1. **El cron NO rompe.** `run_daily_snapshot` abre `sqlite3.connect(db_path)`
   (`snapshots_job.py:951`) y le pasa esa conexión a `take_snapshot_for_user` (`:1006`, único
   call-site). El INSERT de `:763` **no ve Postgres nunca**, ni con `DATABASE_URL` puesta. No es
   un descuido: está en la allowlist `PERMITIDOS` de `tests/test_escritores_solo_sqlite.py:52`
   con el motivo escrito, y el test pasa. (Su modo de falla real es el opuesto: sigue
   escribiendo en un SQLite congelado reportando éxito — ya anotado en el plan de pasaje.)
2. **EL GUARD QUE NADIE BUSCÓ.** `copiar_a_postgres.preflight()` (`scripts/copiar_a_postgres.py:276`,
   chequeo P2 en `:305-313`) compara las columnas origen-vs-destino y el copiador hace
   `raise NoSePuedeCopiar` con **un solo** hallazgo (`:641-645`). Corrido de verdad contra el
   `schema_pg.sql` commiteado, nombra exactamente `['apto','base','mtm_coverage']`.
   **El estado que el plan describe es un estado que el repo se NIEGA a crear.**
3. Y mientras `DATABASE_URL` esté puesta sin `RENDI_PASAJE_COMPLETO`,
   `mantenimiento.en_mantenimiento()` (`mantenimiento.py:88`, enchufado en `main.py:303`)
   devuelve True y toda ruta que no sea `/api/health` contesta 503.

**LO QUE SÍ SOBREVIVE — y es lo único irreducible:**

🔴 **La vista `snapshots_medibles` no existe en Postgres y ningún guard la ve.**
`mkschema.py:167` sólo enumera `type='table'` e `type='index'` → **estructuralmente nunca la va
a generar**, y `verificar_copia.tablas_sqlite()` (`scripts/verificar_copia.py:191`) filtra
`type='table'`, así que la vista **ni entra al catálogo del origen**: el preflight es ciego a
las vistas. Es la primera vista del repo. Los **tres** lectores de la vista rompen
(`home.py:97`, `dashboard.py:106`, `goal.py:46`), y ⚠️ **`goal.py` NO tiene fallback real**:
el `if snap is None` de `:50` se dispara con un resultado **vacío**, no con una excepción.

Lo demás, con su gravedad ya corregida:
- `/api/snapshots:4969` pide `mtm_coverage, base, apto` **sin guarda de columna**, mientras
  `reporting/builder.py:224-228` y `twr._sel_estampo` (`twr.py:914-918`) **sí la tienen**.
  Son **seis** SELECT sin guarda, no uno: sumá `twr.py:476`, `twr.py:590`, `twr.py:1064`,
  `main.py:17354` y `main.py:17456` (los dos últimos dentro de `/api/admin/diagnose-reportes-basis`).
- `schema_pg.sql` ya venía stale **desde antes de la rama** (6 columnas más, todo el free-trial).
  PREEXISTENTE en su raíz.
- Los dos escritores que sí pasan por `get_db()`/pgshim (`main.py:4939`, el POST del browser, y
  `persister.py:1292`, el import) romperían **sólo** si alguien arrancara la app contra un
  Postgres vacío salteando el copiador. Es un bloqueante **del día del pasaje**, no de hoy.

**Tres riesgos del plan quedaron REFUTADOS al verificarlos — no pierdas tiempo:**
- ✅ *"la migración repite la caída del 2026-08-02"*: **NO**. `main.py:1368-1402` hace
  `ALTER TABLE` → re-lee columnas → `CREATE INDEX` → vista. El orden está bien.
- ✅ *"la vista deja pasar el 32 %"*: el número real es **peor** — la rama `ELSE 1` deja pasar
  el **100 %** de las filas legacy sin estampar, no el 32 %. (Pero se cierra sola: después de
  `estampar_base` la query de `home.py:97` pasa de publicar 0,91 % a devolver `None`.)
- ✅ *"el estampado degrada las 34.205 filas legacy"*: **NO**. Probado: una fila `source=NULL`
  con `holdings_json` sale `base='mercado'`, `apto=1` (`twr.py:200-204`). No hay que rescatarlas.

⚠️ **Orden obligatorio en cualquier migración que toques**: `ALTER TABLE` → re-leer las
columnas → `CREATE INDEX` → vista. Un `CREATE INDEX` antes de su columna tiró producción
20 minutos el 2026-08-02.

---

### 4.9 ⛔ LO QUE **NO** HAY QUE ARREGLAR (verificado — no gastes trabajo acá)

Todo esto se atacó adversarialmente y **se cayó**. Si te dan ganas de tocarlo, releé este bloque:

- **El AUM del asesor** (`main.py:33405`) — contrato deliberado, documentado (§4.6.1).
- **`vs_sp500_pct`** — ya guarda el exceso, no el retorno del S&P (§4.7).
- **El orden de la migración** (`main.py:1368-1402`) — está bien, no repite el 2026-08-02.
- **El cron contra Postgres** — no rompe, escribe SQLite por diseño (§4.8).
- **`estampar_base` no degrada las legacy** — una fila NULL con `holdings_json` sale apta.
- **Dos consumidores de `globalMonthly`** que mezclan mercado con costo pero **no llegan a
  ninguna pantalla** (`buildCumulativeReturnSeries` y compañía): refutados por inalcanzables.
- **El chip Δ1d/7d/30d con `INDETERMINADO`** — mecanismo real, **4 filas** en producción (§4.7).
- **Los lectores sanos** listados en §4.6, §4.6.1 y §4.7 — 25 en el backend, 7 en el frontend,
  8 en el asesor. Están bien y varios son el modelo a copiar.

**Origen, verificado byte a byte** contra `61c9e5da` y `origin/main`: **ninguno de los hallazgos
del asesor es una REGRESIÓN** — los bloques salen idénticos en las tres refs. Casi todo el
inventario es **PREEXISTENTE**. Lo único marcado REGRESIÓN es lo de Postgres (§4.8), porque las
columnas y la vista las agregó esta rama.

---

## 5 · LO QUE TENÉS QUE DECIDIR BIEN: LOS 173 QUE SE QUEDAN EN BLANCO

Éste es el punto donde un arreglo apurado se convierte en una regresión peor que el bug.

Medido corriendo los helpers reales sobre series reales de producción:

```
uid 452  (60 filas, 3 aptas)
  HOY              curva=5 pts   Este mes: −208.001,38  −105,78 %
  con filtro       curva=3 pts   Este mes:     −761,60    −1,13 %   ✅ arreglado

uid 107  (57 filas, 0 aptas)
  HOY              curva=2 pts   P&L día: +216.720,53  +502,91 %   ← fabricado
  con filtro       curva=0 pts   Este mes: null                    ← PANTALLA VACÍA
```

**173 usuarios no tienen ni una fila dibujable. 178 no tienen ni una fila apta.** Para ellos,
filtrar convierte un número falso en una pantalla en blanco, sin explicación.

**Qué tenés que hacer en la Fase 1** (y sólo esto):

1. **No publiques un número mezclado. Nunca.** Es la regla dura.
2. Donde no se pueda medir, poné un **estado vacío honesto**: decile al usuario *por qué* no
   hay número todavía (no tenemos mediciones a precio real de tu cartera antes de tal fecha),
   no un "—" mudo, no un 0, y no un `NaN`.
3. **NO construyas el toggle.** El modo contable/certero es la **Fase 2** y ya está decidido
   por el dueño: un toggle en el gráfico de rendimiento vs benchmarks donde el usuario elige
   entre *más historial pero aproximado* y *menos historial pero certero*. La Fase 2 reemplaza
   ese estado vacío. Si lo construís ahora, la Fase 2 arranca teniendo que deshacerlo.

---

## 6 · CRITERIO DE SALIDA

La Fase 1 sale cuando **las dos cosas** se cumplen:

1. **Ningún lector publica un porcentaje ni un delta en dólares con una punta al costo.**
   Ni en pantalla, ni por email, ni dentro del prompt de la IA (un drawdown que llega al
   prompt sale por la boca del modelo aunque la pantalla lo tape).
2. **Lo viste andando en el browser.** Once rondas sin abrir la app ni una vez. Levantá la app,
   entrá con datos que exhiban el caso, y sacá captura del Dashboard, del home mobile y de
   Reportes. Si no lo viste en pantalla, no está hecho.

---

## 7 · CÓMO VERIFICAR (esto no es opcional)

- **Verificá EJECUTANDO, nunca leyendo.** Toda afirmación tuya se sostiene con un comando que
  corriste y su salida real pegada.
- **Tu fixture tiene que PODER exhibir el bug.** Antes de declarar algo cerrado, preguntate:
  *¿este caso de prueba PODRÍA fallar?* Un fixture con una sola naturaleza de fila no puede
  disparar nada, y el test que pasa no prueba nada. Un auditor anterior declaró un grupo
  "cerrado" con un fixture así y el bug seguía vivo. Usá la serie real de 452:
  ```
  2026-07-31  total_value=196631.56  total_invested=-1789.39  net_deposited=-1789.39  source='import'
  2026-08-16  total_value= 67214.75  total_invested=76795.18  net_deposited=-5726.38  source='cron'
  ```
  (Fijate que `net_deposited` es **negativo** en las dos: ése es el caso que dispara §4.4.
  Un fixture con `net_deposited` positivo **no puede** exhibir ese bug — y es exactamente el
  error que cometió uno de los agentes del barrido.)
- **La suite NO es determinista.** El mismo commit da 46 o 50 fallas según el entorno
  (medido a 61c9e5da: 50/3472 en dos corridas). **NUNCA uses el conteo como reja de
  seguridad.** Corré antes y después y compará **CONJUNTOS de nombres de tests que fallan**.
  Lo que importa es que no aparezca un nombre nuevo.
- El reconstructor **sólo escribe fin de mes** (`backfill_historical_mtm.py:462`): un fixture
  con una fila reconstruida el día 20 no es producible en la realidad.
- Para comparar contra la ronda 8 sin ensuciar el árbol:
  `git archive 61c9e5da | tar -x -C <tmp>`.

---

## 8 · QUÉ TENÉS QUE ENTREGAR

1. Los cambios en el working tree (**sin commitear**), con un resumen `file:line` de cada uno.
2. Por cada arreglo: el repro **antes** (con su salida real) y **después** (con su salida real).
3. Los conjuntos de tests que fallaban antes y después, y la diferencia entre los dos conjuntos.
4. Las capturas del browser del criterio de salida §6.2.
5. 🔴 **Al final, una sección explícita: "QUÉ NO VERIFIQUÉ".** Todo lo que dejaste sin probar,
   lo que asumiste, y lo que no pudiste reproducir. Las rondas 10 y 11 lo hicieron y sirvió
   muchísimo. No lo omitas y no lo maquilles: un "no verifiqué X" vale más que un "X anda".

---

## 9 · ORDEN SUGERIDO

1. `useMonthlyData.js` — los **dos** bloques juntos (`:404-420` y `:539-551`) + `liveValue` (`:473`).
   Es el número que el usuario reportó.
2. Los 3 helpers de `evolution.js` (`:56`, `:159`, `:202`) — **dibujar por serie, medir por fila** —
   más `netDepositedOf` (`:122`).
3. Los consumidores a dos saltos del Dashboard y HomeMobile (§4.5), incluido el eje Y y el ancla.
4. Las superficies del asesor (§4.6) + los lectores del backend (§4.6.1) — empezá por el pico
   de `main.py:35545/35546` (va al mail) y por la **punta sin filtrar** de `main.py:31698`.
5. Reportes + los builders de la IA (§4.7) — los movers de `builder.py:1061` primero.
6. `schema_pg.sql` + la vista + la guarda de columna de `/api/snapshots` (§4.8).
7. La rama ARS de Insights (§4.5, último renglón).
8. Browser (§6.2).
