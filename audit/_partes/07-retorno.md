## 07 · Motores de retorno: TWR, performance, P&L realizado, flujos

Auditoría del commit `b74f450f` (origin/main, 2026-09-05). Todo lo marcado `[V]` está leído en el código con archivo:línea; `[I]` es inferencia mía y digo de qué me agarré.

---

### Resumen ejecutivo (leelo aunque no leas el resto)

1. **`backend/twr.py` es el único motor con disciplina.** Tiene UN primitivo (`dietz`, `backend/twr.py:559`), tres cotas de plausibilidad, separación explícita entre "lo que se dibuja" y "lo que se publica", y un contrato de datos estampado en la fila (`snapshots.base` / `snapshots.apto`). `[V]`
2. **Hay al menos NUEVE fórmulas de retorno distintas vivas en el repo**, seis de las cuales tienen su propio piso/techo y su propia heurística de flujo. La sección **⚠️ Duplicación** las pone lado a lado. `[V]`
3. **Dos de los siete archivos que me pidieron auditar son código muerto en producción**: `backend/ledger_replay.py` y `backend/flujos.py` no tienen un solo call-site fuera de `backend/tests/`. `[V]`
4. **`backend/flujos.py` no es el motor de flujos del TWR.** El flujo del TWR sale de `snapshots_job.compute_net_deposited_db` y de `twr.netdep_canonico`. `flujos.py` es un desambiguador de traspasos entre brokers que nunca se enchufó. `[V]`
5. **El motor del asesor (`twr.tramos` → `twr_periods` → `twr_de`) y el motor de la app retail (`twr.curva_indexada`) miden lo mismo con reglas distintas** y ninguno de los dos lee al otro. Sección "Duplicación #1". `[V]`

---

## 1 · `backend/twr.py` — el núcleo (2213 líneas)

### 1.1 Qué es y qué produce

Dos motores en un archivo, con primitivo compartido:

| | Motor A — "el sellado" | Motor B — "la curva" |
|---|---|---|
| Entrada | `twr.tramos()` (`backend/twr.py:740`) | `twr.serie_medible()` (`backend/twr.py:1283`) |
| Granularidad | **mensual** (último borde de cada mes) | **por snapshot** (diaria) |
| Persiste | sí — tabla `twr_periods`, append-only con `revision` | no, todo en lectura |
| Salida | `twr.twr_de()` (`backend/twr.py:848`) → TWR encadenado | `twr.curva_indexada()` (`backend/twr.py:1611`) → curva + drawdown + CAGR |
| Consumidor | `advisor_twr.twr_por_cliente` → `GET /api/advisor/twr` (`backend/main.py:33698`) | `performance.performance` → `GET /api/insights/performance` (`backend/main.py:11789`), Reportes, `/api/goals/cagr` |
| Bordes que acepta | **sólo `MEDICION`** (`backend/twr.py:718-729`) | `ACEPTA_LINEA` + modo (ver 1.5) |
| Modos | ninguno | `certero` / `estimado` × `usd` / `ars` |

`[V]` `backend/twr.py:718-729`, `backend/twr.py:740-793`, `backend/twr.py:848-928`, `backend/twr.py:1283`, `backend/twr.py:1611`.

### 1.2 El primitivo: `dietz` — la fórmula literal

```python
# backend/twr.py:559-576
def dietz(v0: float, v1: float, flow: float):
    denom = v0 + 0.5 * flow
    if denom <= 0:
        return None
    return max((v1 - v0 - flow) / denom, -1.0)
```

- Modified Dietz con el flujo ponderado a mitad de tramo. `[V]`
- **Piso −1,0, sin techo.** El docstring lo justifica: el clamp de +50 % del lado retail no se le aplica al benchmark, así que el sesgo va sistemáticamente contra el usuario. `[V]` `backend/twr.py:566-572`
- Devuelve `None` cuando `denom <= 0` — no cero, `None`. `[V]`

### 1.3 Estructura interna: las TRES preguntas que el módulo separa

Esto es lo que hace que `twr.py` no sea "un motor más". El archivo define explícitamente tres preguntas que el resto del repo confundía en una sola:

| Pregunta | Función | Constante |
|---|---|---|
| ¿quién ESCRIBIÓ esta fila? | `clasificar_fila` / `clasificar_serie` (`backend/twr.py:181`, `:365`) | `MEDICION` · `RECONSTRUIDO` · `INTRADIA` · `SINTETICO_COSTO` · `INDETERMINADO` |
| ¿con qué REGLA está valuado el `total_value`? | `base_de` (`backend/twr.py:293`) | `VALUADO_A_MERCADO` / `VALUADO_AL_COSTO` (`:243-244`) |
| ¿puede ser PICO y DENOMINADOR? | `es_apto` (`backend/twr.py:247`) → `clase in BASE_MERCADO and base == VALUADO_A_MERCADO` (`:258`) | `BASE_MERCADO = (MEDICION, RECONSTRUIDO)` (`:87`) |

Listas de aceptación `[V]` `backend/twr.py:87-91`:
```python
BASE_MERCADO  = (MEDICION, RECONSTRUIDO)
ACEPTA_LINEA  = BASE_MERCADO + (INTRADIA,)
BORDE_PERIODO = BASE_MERCADO          # alias explícito
```

**Cómo se decide la clase** (`clasificar_fila`, `backend/twr.py:181-212`) `[V]`:
1. `source='mtm_backfill'` → `RECONSTRUIDO` si hay `mtm_coverage` no-NULL, si no `SINTETICO_COSTO`.
2. `_POR_SOURCE` (`:177`): `cron→MEDICION`, `browser→INTRADIA`, `import→SINTETICO_COSTO`.
3. Sin `source` (filas legacy): `holdings_json` no vacío → `MEDICION`; `fx_to_usd_blue` y **sin posiciones no-cash a esa fecha** → `MEDICION`; `fx` con posiciones → `INTRADIA`; fin de mes pelado → `SINTETICO_COSTO`; resto → `INDETERMINADO`.
4. `clasificar_serie` (`:365-437`) agrega la **cadencia**: una racha de ≥ `RACHA_CRON_MINIMA = 7` días calendario CONSECUTIVOS asciende las filas legacy de `INTRADIA` a `MEDICION`. Sólo toca filas legacy (`_legacy`, `:391`). `[V]` `backend/twr.py:362`, `:420-427`

**El estampo manda sobre la deducción**: `bases_de_serie` (`backend/twr.py:1109-1133`) y `aptos_de_serie` (`:1135-1149`) leen `snapshots.base` / `snapshots.apto` si existen y sólo deducen si no. Los cuatro escritores pasan por `base_y_apto_para` (`:1152`). `[V]`

Escritores estampando: cron `backend/snapshots_job.py:778-779` (`'cron','mercado',1`), browser `backend/main.py:5072-5073` (`'browser','mercado',0`), import `backend/importing/persister.py:1292`, reconstructor `backend/scripts/backfill_historical_mtm.py:412-425`. `[V]`

### 1.4 Motor A — el sellado (asesor)

**Qué es un "período" en `twr_periods`**: un tramo de UN MES CALENDARIO, entre el **último borde `MEDICION` del mes M−1** y el **último borde `MEDICION` del mes M**. `[V]` `backend/twr.py:754-762`

Fórmula del tramo (`backend/twr.py:763-768`):
```python
v0, v1 = float(b0["total_value"]), float(b1["total_value"])
flow = _flujo(conn, uid, b0["date"], b1["date"])
r = dietz(v0, v1, flow)
```
donde `_flujo` (`backend/twr.py:731-738`) es
```python
compute_net_deposited_db(conn, uid, as_of_date=hasta)
  - compute_net_deposited_db(conn, uid, as_of_date=desde)
```
— o sea diferencia de dos lecturas de `monthly_entries` con resolución **MENSUAL**. `[V]` `backend/snapshots_job.py:328-386`

Reglas del motor A `[V]`:
- El mes de alta **no se mide**: el bucle arranca en `i = 1` (`backend/twr.py:756`) porque con `capital_inicio = 0` el 0,5 de Dietz infla ese mes.
- El mes en curso no se sella: `if mes >= tope: continue` (`:760`).
- `quality` ∈ `ok` / `dudoso` (`leg_dudoso`, `:778`) / `flujo_sospechoso` (`|flow| > v0 * FLUJO_SOSPECHOSO`, `FLUJO_SOSPECHOSO = 0.5`, `:556`, `:780`) / `plano` (`:781`).
- `fx_basis` estampado como `"mep_medio"` — **hardcodeado** (`:788`). `[I]` No hay ninguna comprobación de que el snapshot se haya valuado a MEP medio; el string es una afirmación, no una medición. `ledger_replay.FX_BASIS` dice `"mep_venta"` (`backend/ledger_replay.py:31`) y su docstring advierte exactamente por el spread (`backend/ledger_replay.py:20-25`).

**Sellado** (`sellar`, `backend/twr.py:800-832`): idempotente por comparación de `_CAMPOS_SELLO = ("period_start","period_end","v0_usd","v1_usd","flow_usd","quality")` con tolerancia 0,005; si cambió, `revision+1`, nunca pisa. `[V]`

**Encadenado** (`twr_de`, `backend/twr.py:848-928`):
```python
idx = 1.0
for f in filas:
    idx *= (1.0 + float(f["ret"]))      # backend/twr.py:883-884
return {"twr": idx - 1.0, ...}
```
Con **cualquier** mes `quality == 'dudoso'` NO publica: devuelve `twr=None` y `motivo='medicion_dudosa'`. `[V]` `backend/twr.py:864-884`

### 1.5 Motor B — `serie_medible` + `curva_indexada`

#### `serie_medible` (`backend/twr.py:1283-1609`) — qué hace, en orden

1. Trae los snapshots del rango con `_sel_estampo` (guarda de columna: si la migración no corrió pide `NULL AS base, NULL AS apto`, `backend/twr.py:1094-1099`). `[V]`
2. Clasifica **por serie**, calcula `bases` y `aptos`. `[V]` `:1330-1333`
3. Si `modo == MODO_ESTIMADO`, agrega `SINTETICO_COSTO` e `INDETERMINADO` a `aceptar` (`:1328-1329`). `[V]`
4. `_fx` = `serie_fx()` sólo si `moneda == ARS`; en USD es `None` y **nada del camino multiplica** (`:1338`). `[V]`
5. `_nd` = `_aportado_por_punto()` (ver 1.6). `[V]` `:1339`
6. **La contabilidad se apaga en la primera medición real** (sólo estimado): toda fila `VALUADO_AL_COSTO` con fecha ≥ `_primer_apto` sale de la línea y cuenta en `contable_superado` (`:1346-1348`, `:1388-1390`). `[V]`
7. **Realineado contable** (sólo estimado): si la foto `SINTETICO_COSTO` de fin de mes difiere de `monthly_entries.capital_final` de su propio mes, se usa el valor de LA CADENA y la foto vieja queda en `valor_foto` (`:1393-1398`). Cuenta en `contable_realineado`. `[V]`
8. **Disciplina de clave**: un punto apto trae `value`; uno no apto trae `value_no_medible` — nunca las dos. `:1409-1410`. La única puerta al número crudo es `valor_para_dibujar` (`:1073-1082`). `[V]`
9. La banda gris `contable` se llena **por BASE, no por clase** (`:1442-1449`). `[V]`

#### El corte de tramos (dónde se parte la serie) — `backend/twr.py:1487-1551`

| Condición | Tope / regla | Línea |
|---|---|---|
| Hueco contable→contable | `> MAX_HUECO_CONTABLE_DIAS = 400` días | `:912`? no — `:927`, uso en `:1493-1496` |
| Cualquier otro hueco | `> max_hueco_dias` (default `MAX_HUECO_DIAS = 45`) | `:912`, uso `:1496-1497` |
| Traspaso contable→mercado (sólo estimado) | ratio `v1 / (v0 + flujo)` fuera de `[1/3, 3]` → `cadena_implausible` | `:1498-1521` |
| Leg mercado→mercado (apto→apto) | `leg_dudoso()` | `:1522-1535` |
| Leg contable→contable (sólo estimado) | `leg_dudoso()` | `:1536-1546` |

El hueco se mide **siempre contra el punto anterior** (mida o no) y el desborde **entre puntos aptos**. `[V]` `:1496`, `:1522`

Salida (`:1577-1609`): `medibles`, `no_medibles`, `tramos` (lista de listas), `contable`, `por_clase`, `cobertura`, `cobertura_reconstruccion`, `instrumentos_al_costo`, `modo`, `cortes_dudosos`, `contable_superado`, `contable_realineado`, `moneda`, `riel_fx`, `medido_desde/hasta`, `motivo`, `motivo_texto`. **No hay clave `puntos`** — decisión explícita para forzar al lector a elegir. `[V]` `:1567-1580`

#### `curva_indexada` (`backend/twr.py:1611-2213`) — CUATRO índices en paralelo

Esto es lo más denso del archivo. Dentro de cada tramo corren simultáneamente:

| Índice | Qué es | Qué encadena | Línea |
|---|---|---|---|
| `idx` | el número del modo **CERTERO** | sólo apto→apto, `ancla` = último punto apto | `:1876` |
| `idx_por_base[b]` (`idx_dib`) | la **FORMA** dibujada | punto→punto **de la misma base**, incluye INTRADIA | `:1847` |
| `idx_est` | el número del modo **ESTIMADO** | apto + cadena contable, **por base** | `:1860` |
| `pico` / `dd_max` | drawdown | sólo puntos aptos, con el índice `idx` | `:1918-1926` |

Fórmula de cada leg (todas pasan por `_leg_en_moneda` + `dietz`):
```python
# CERTERO, backend/twr.py:1767-1768
_a, _b, flow = _leg_en_moneda(ancla, p, ancla["value"], p["value"])
ret = dietz(_a, _b, flow)
```
```python
# DIBUJO, backend/twr.py:1836-1847
_v0d, _v1d, _flow_dib = _leg_en_moneda(_prev, p, valor_para_dibujar(_prev), valor_para_dibujar(p))
if leg_dudoso(_v0d, _v1d, _flow_dib):
    segmento += 1; idx_por_base[_b] = 1.0        # corta la LÍNEA, no el número
else:
    idx_por_base[_b] *= (1.0 + dietz(_v0d, _v1d, _flow_dib))
```
```python
# ESTIMADO, backend/twr.py:1855-1860
_v0e, _v1e, _fe = _leg_en_moneda(_prev_est, p, valor_para_dibujar(_prev_est), valor_para_dibujar(p))
idx_est *= (1.0 + dietz(_v0e, _v1e, _fe))
```

**El traspaso entre bases no mide retorno pero arrastra el FX** (`_factor_fx`, `backend/twr.py:650-664`): en modo estimado, al abrir una base nueva, `idx_por_base[_b] = ultimo_idx_dib * _factor_fx(ultimo_p_dib, p)` (`:1824`) y `idx_est *= _ffx` (`:1865-1868`). En USD `_factor_fx` devuelve 1,0 y no cambia nada. `[V]`

**Publicación** (`:1975-2014`):
```python
partida    = len(s["tramos"]) > 1                        # :1981
publicable = (len(con_legs) == 1 and not partida)        # :1982
```
Si no es publicable, `twr`, `drawdown_actual`, `drawdown_maximo` y `cagr` van todos en `None` — no en 0. `[V]` `:2012-2014`

**Pata live** (`:2024-2101`): del último punto APTO al `valor_live`, con `_flujo_live = compute_net_deposited_db(conn, uid) - ultimo_apto["net_deposited"]` (`:2049-2050`). Una foto intradía al final NO apaga el cierre live: la pata salta la intradía. `[V]` `:2032-2043`

**En modo ESTIMADO** (`:2141-2160`):
- `est_publicable` con **≥ 1** tramo con legs (no exige tramo único, a diferencia del certero): publica la **ventana continua más reciente**. `[V]` `:2141-2147`
- **Siempre se apagan drawdown y pico**, publique o no (`:2158-2159`). `[V]`

**CAGR** (`:2166-2172`):
```python
años = _dias(ventana_desde, _c1) / 365.25
if años >= 0.5:                       # bajo medio año, anualizar es propaganda
    cagr = idx ** (1.0 / años) - 1.0
```
`[V]`

### 1.6 De dónde sale el flujo — DOS fuentes distintas dentro del mismo archivo

Este es un punto fino y money-critical.

| Consumidor | Fuente del flujo | Resolución |
|---|---|---|
| `twr.tramos` (motor A) | `_flujo` → `compute_net_deposited_db` × 2 (`backend/twr.py:731-738`) | mensual |
| `twr.serie_medible` (motor B) | `_aportado_por_punto` (`backend/twr.py:1014-1071`) | diaria, con ancla mensual |
| pata live de `curva_indexada` | `compute_net_deposited_db` directo (`backend/twr.py:2049`) | acumulado a hoy |

`_aportado_por_punto` es un híbrido explícito (`backend/twr.py:1018-1021`):
```
aportado(d) = clamp( canon(M) − (estampa(rn) − estampa(d)),
                     min(canon(M−1), canon(M)),
                     max(canon(M−1), canon(M)) )       rn = última fila de M
```
donde `canon` = `netdep_canonico` (`backend/twr.py:937-991`), recalculado AHORA desde `monthly_entries` (`baseline = capital_inicio` de la primera fila + Σ deposits − withdrawals), y `estampa` = `snapshots.net_deposited`. Si no hay `monthly_entries`, `netdep_canonico` devuelve `None` y `_aportado_por_punto` cae a la estampa pelada (`:1040-1042`). `[V]`

⚠️ **Divergencia dentro del mismo repo, documentada en el propio código**: `netdep_canonico._en` atribuye el `baseline` a TODA fecha anterior a la primera fila (`backend/twr.py:972-991`), mientras `compute_net_deposited_db` lo atribuye al primer mes (`backend/snapshots_job.py:379-386`). El comentario de `twr.py:975-984` lo declara a propósito. **Consecuencia `[I]`**: el motor A (que usa `compute_net_deposited_db`) y el motor B (que usa `netdep_canonico`) NO ven el mismo flujo para el mismo tramo cuando el borde cae antes/dentro del primer mes de contabilidad. Nadie los reconcilia.

### 1.7 Moneda: `_leg_en_moneda` y `serie_fx`

```python
# backend/twr.py:666-706
f0 = p0.get("fx");  f1 = p1.get("fx")
flow = p1["net_deposited"] - p0["net_deposited"]
if not f0 or not f1:
    return v0, v1, flow                          # USD: idéntico bit a bit
return v0 * f0, v1 * f1, flow * ((f0 * f1) ** 0.5)
```
- Cada punta al TC de SU fecha; el flujo al **TC medio geométrico**. `[V]`
- **El stock no se convierte, el FLUJO sí**: primero se resta en dólares y después se convierte, para no leer la revaluación de todo lo aportado en la vida como un aporte del período. `[V]` `backend/twr.py:696-706`
- `serie_fx` (`backend/twr.py:1220-1281`): `mep_venta` con fallback a `blue_venta`, arrastre del último hábil por `bisect`, `"hoy"` o fecha futura → último valor. Devuelve `(fn, riel)` con `riel ∈ {mep, blue, mixto}`. **Antes de la primera fecha devuelve `None` y el punto NO entra a la línea en pesos** (`:1404-1408`). `[V]`

### 1.8 Casos borde

| Caso | Comportamiento | Cita |
|---|---|---|
| capital cero o negativo | `dietz` devuelve `None` (`denom <= 0`); el leg no aporta | `backend/twr.py:573-575` |
| retiro que desborda el denominador | `leg_dudoso` → `'desborde'`, corta el tramo | `backend/twr.py:637-643` |
| salto ×3 sin flujo | `leg_dudoso` → `'salto'`, corta | `backend/twr.py:644-647` |
| período sin datos | `curva_indexada` devuelve la MISMA FORMA con todo en `None`/`[]` | `backend/twr.py:1634-1656` |
| serie partida | `publicable=False`, `motivo='serie_partida'` | `backend/twr.py:1981-1982`, `:2176-2184` |
| traspaso entre brokers | **no encontrado** en `twr.py` — el TWR no distingue traspasos; ve el `net_deposited` de `monthly_entries`. Lo que sí existe es `flujos.cruce_entre_brokers`, que no lo llama nadie (§4) | — |
| cambio de moneda (conversión ARS↔USD) | **no encontrado** en `twr.py`. Se registra como op `CONVERSION …` (`backend/main.py:10953`) que sí escribe `pnl_usd` (`:10969`) y sí toca `monthly_entries.pnl_realized` (`:10976-10980`), o sea entra al TWR por la vía del `capital_final` contable, no como flujo | `backend/main.py:10951-10985` |
| serie plana (precio congelado) | `_tramos_planos` con `PLANO_RUEDAS = 3` y `PLANO_TOL = 0.0001`; sólo se REPORTA en `diagnosticar`, no corta nada | `backend/twr.py:159-160`, `:450-464`, `:494` |
| columna faltante (deploy a medio migrar) | `_tiene_columna` + `_sel_estampo` piden `NULL AS base/apto` | `backend/twr.py:1084-1099` |

---

## 2 · `backend/performance.py` (285 líneas)

**Qué calcula**: nada propio de retorno de cartera. Es un **compositor**: llama a `twr.curva_indexada` y le pega al lado el benchmark **recortado al mismo rango**. `[V]` `backend/performance.py:199-200`

**Output de negocio**: la respuesta de `GET /api/insights/performance` — la sección Performance/Métricas del frontend, y la fuente del drawdown de toda la app (`drawdownFromPerf`, `frontend/src/utils/insightsModel.js:684-691`). `[V]`

**Lo que sí calcula**: el índice del benchmark.

- `_benchmark_diario` (`backend/performance.py:39-85`): para cada fecha de la curva del usuario toma el cierre de ese día o del último hábil anterior (`bisect`); ancla en 1,0 en la primera fecha CON cierre; antes de eso `index: None`. `[V]`
- `benchmark_recortado` (`:88-154`): resuelve diario si las claves son `YYYY-MM-DD` y la clave no es porcentual; si no, mensual. Para `BENCH_PORCENTUAL = ("inflation_ar","plazo_fijo")` (`:20`) compone `idx *= (1 + v/100)`; para los de precio hace `v / base_val`. Sin dato de un mes **arrastra** el último conocido. `[V]`
- `_en_pesos` (`:157-179`): `precio × TC` re-anclado a 1,0. `BENCH_EN_ARS = ("merval","uva","plazo_fijo","inflation_ar")` no se convierten (ya están en pesos). `[V]` `:25`

**Prioridad de resolución** (`:207-218`): primero `f"{bench_key}_d"` (serie diaria); si no cubre ninguna fecha, cae al mensual. `[V]`

⚠️ **El contrato es una LISTA BLANCA explícita** (`:225-284`). Un campo nuevo de `curva_indexada` no llega solo al JSON. El propio comentario dice que `base_del_twr` y `excluye_no_realizado` salían `None` mientras el motor los calculaba bien (`:263-268`). `[I]` Riesgo estructural repetible: cualquier campo nuevo del motor queda invisible hasta que alguien lo agregue a mano acá.

⚠️ **`twr.serie_fx` se llama hasta TRES veces por request** en el mismo handler: `:222` para el benchmark y `:243` **dentro de una comprensión de lista, una vez por punto de la banda contable**. `[V]` `backend/performance.py:241-244`. `[I]` `serie_fx` hace un `SELECT` completo de `fx_rates_daily` cada vez (`backend/twr.py:1247-1252`), así que la banda contable con N puntos dispara N queries de tabla completa. Es correcto pero caro.

---

## 3 · `backend/realized_pnl.py` (141 líneas)

**Qué calcula**: NO es un motor de matcheo FIFO. Es el **criterio único de conversión de moneda** de la columna `operations.pnl_usd`, que a pesar del nombre no siempre guarda USD. `[V]` `backend/realized_pnl.py:9-17`

**El problema que resuelve** (del propio docstring): `bond_cashflow` inserta `net_amount` tal cual, así que un cupón de $125.000 ARS entra a `pnl_usd` como 125000. `[V]` `:11-14`

**Las tres fórmulas literales**:

```python
# backend/realized_pnl.py:85-94 — qué es una "operación cerrada"
f"{p}pnl_usd IS NOT NULL AND {p}op_type NOT IN ('Compra','Dividendo','Interés','') "
f"AND {p}op_type NOT LIKE 'CONVERSION%' AND {p}op_type NOT LIKE 'Conversión%'"
```
```python
# backend/realized_pnl.py:97-107 — el pnl en USD de verdad
f"CASE WHEN {p}op_type IN ('Cupón','Amortización') AND {p}currency = 'ARS' "
f"AND {p}fx_to_usd > 0 THEN {p}pnl_usd / {p}fx_to_usd ELSE {p}pnl_usd END"
```
```python
# backend/realized_pnl.py:118-141 — el equivalente Python
```
`[V]`

### 3.1 ¿Cómo se matchea una venta contra el costo? — **acá no**

`realized_pnl.py` NO matchea nada: **lee** `operations.pnl_usd`, que alguien más ya calculó. `[V]` (no hay ninguna query a `positions` ni lógica de lotes en el archivo; 141 líneas, todas leídas). El FIFO vive fuera de los siete archivos de este encargo — **no encontrado** en el alcance auditado.

- ¿FIFO? — **no encontrado** en `realized_pnl.py`.
- ¿pool único o por broker? — **no encontrado** en `realized_pnl.py`.
- ¿ventas cross-currency? — lo único que hay es la conversión de arriba, que **excluye explícitamente `Venta`**: "En `Venta` el `pnl_usd` YA es USD y `fx_to_usd` guarda el tc_venta — dividir ahí rompería todo" (`backend/realized_pnl.py:22-24`). `[V]`

### 3.2 Los tres pendientes que el módulo declara y no resuelve `[V]`

1. **El win rate cuenta los cupones como operaciones ganadas** (`:34-53`). Un cupón nunca es negativo, así que suma una "ganada" al numerador Y al denominador. Afecta a `reporting/timeline.py:61`, `behavioral.py`, `reporting/builder.py:255`, `ai/builders/reports.py`. Declarado sin decidir desde 2026-08-18.
2. **398 filas viejas sin `fx_to_usd`** quedan infladas en los 4 lectores, incluido el dashboard (`:55-59`).
3. **`Interés PF`** guarda moneda nativa igual que un cupón, NO está en `_NATIVE_CCY_OPS` y NO está excluido de `closed_filter_sql` (`:61-68`). Hoy 0 filas en prod; el primer plazo fijo en pesos entra inflado en los 4.

### 3.3 Quién lo llama `[V]`

| Consumidor | Cómo |
|---|---|
| `backend/wrapped.py:30`, `:86` | `realized_usd(op)` |
| `backend/behavioral.py:35`, `:1842` | `_realized_usd(o)` |
| `backend/reporting/builder.py:21`, `:237` | `realized_usd_sql()` en `fetch_operations_in_range` — el embudo del módulo |
| `backend/main.py:9534`, `:12486`, `:13357`, `:25412-25413`, `:32767`, `:37472` | ambas variantes |

### 3.4 ⚠️ Divergencias del criterio "operación cerrada" — CUATRO copias

| Lugar | `''` (op_type vacío) | `CONVERSION%` | Cita |
|---|---|---|---|
| **canónico** `is_closed_op` | excluido | excluido | `backend/realized_pnl.py:74`, `:110-115` |
| `reporting/builder.py::_is_trade` | **NO excluido** | excluido | `backend/reporting/builder.py:845-851` |
| `reporting/builder.py:1780` (`compute_highlights`) | **NO excluido** | excluido | `backend/reporting/builder.py:1780` |
| `reporting/timeline.py::_compute_user_historical_win_rate` | **NO excluido** | excluido | `backend/reporting/timeline.py:68-73` |

**Consecuencia `[I]`**: una operación con `op_type = ''` y `pnl_usd` no nulo cuenta como trade cerrado en el win rate de Reportes y en el win rate lifetime de la timeline, y NO cuenta bajo el criterio canónico. El módulo existe literalmente para que los cuatro digan lo mismo (`backend/realized_pnl.py:2-4`).

**Y una segunda, más grande**: en `compute_metrics_for_period`,
```python
# backend/reporting/builder.py:842
realized = sum(float(o.get("pnl_usd") or 0) for o in ops)
```
suma **todas** las ops del rango, incluidas las `CONVERSION …`, que `closed_filter_sql` excluye a propósito y que **sí escriben `pnl_usd`** (`backend/main.py:10962-10970`). `[V]` El `realized_pnl` que publica Reportes incluye la ganancia de conversión de dólares; el `realized_pnl_usd` de `main.py:25504` (que usa `closed_filter_sql`) no. `[I]` Son dos números con el mismo nombre en dos pantallas.

---

## 4 · `backend/flujos.py` (169 líneas) — ⚠️ CÓDIGO MUERTO

**Qué dice que es**: "la pasada determinística" que responde si un movimiento ambiguo es un aporte del cliente o un traslado interno. `[V]` `backend/flujos.py:1-12`

**Qué NO es**: no es el motor de aportes/retiros del TWR. **No lo llama nadie en producción.** `[V]`

```
$ grep -rn "import flujos\|flujos\." backend --include="*.py" | grep -v tests/
→ sólo backend/flujos.py mismo. Los únicos `import flujos` están en
  backend/tests/test_advisor_plan.py:2487,2495,2511,2524,2536,2548,2559,2573,2587,2597
```

**Qué es un "flujo" acá** (a diferencia del TWR): un movimiento de TÍTULOS que el validator rechazó. `candidatos()` sale de `import_raw_rows` con `status != 'ok'` y `errors_json` conteniendo `"TRANSFER"` (`backend/flujos.py:54-71`). `[V]`

**Cómo distingue un aporte real de un movimiento interno** — dos vías, en orden (`resolver`, `:114-140`) `[V]`:
1. **`direccion_por_texto`** (`:75-82`): busca literales en el `raw_json` aplanado. `ENTRADA` (10 literales, `:28-30`) → `naturaleza='aporte'`; `SALIDA` (10 literales, `:31-33`) → `'retiro'`.
2. **`cruce_entre_brokers`** (`:85-111`): busca en `import_normalized_tx` de OTRO broker del mismo user, mismo `asset_symbol`, ventana `DIAS_CRUCE = 4` días, cantidad con tolerancia `TOL_CANTIDAD = 0.001` relativa. Si hay pata opuesta → `naturaleza='traslado_interno'` con el comentario `# NO es flujo: no se neutraliza`.

**Cómo trata una conversión de moneda**: **no encontrado**. `flujos.py` sólo mira `asset_symbol` y `quantity`; no hay ninguna rama de moneda.

⚠️ **Un problema de la lógica misma `[V]`+`[I]`**: `resolver` lee `cand.get("asset")`, `cand.get("fecha")` y `cand.get("cantidad")` (`:126`), pero `candidatos()` sólo devuelve las claves `raw_id`, `broker`, `texto`, `raw_json` (`:67-71`). Por lo tanto, en el flujo real `reconciliar → candidatos → resolver`, la segunda vía (`cruce_entre_brokers`) **nunca se ejecuta**: `asset`/`fecha`/`qty` son siempre `None`. `[I]` `reconciliar` puede resolver únicamente por texto crudo; la vía "que se lleva la mayoría de los casos sin gastar un token" (`:91`) está inalcanzable desde su único punto de entrada. Los tests la llaman directo con dicts armados a mano.

---

## 5 · `backend/ledger_replay.py` (314 líneas) — ⚠️ CÓDIGO MUERTO EN PRODUCCIÓN

**Qué es "reproducir el ledger"**: reconstruir la tenencia y el cash de una fecha pasada replayando `import_normalized_tx`, y valuarla a `price_history` para **fabricar un borde de período que falta**. `[V]` `backend/ledger_replay.py:1-6`

**Cuándo corre**: nunca, hoy.
```
$ grep -rn "ledger_replay" backend frontend/src | grep -v tests/
backend/twr.py:1232          ← una mención en un comentario
backend/importing/proyeccion.py:12  ← otra mención en un comentario
```
`[V]` No hay un solo `import ledger_replay` fuera de `backend/tests/test_advisor_plan.py`.

**Relación con el rebuild del importador** `[V]`:
- `tenencia_en` (`:35-82`) usa el **MISMO orden canónico** que el rebuild: `ORDER BY n.date ASC, (BUY antes que SELL) ASC, n.id ASC` (`:68-70`). El docstring lo dice: sin eso "el orden de las filas decide la P&L".
- Filtra `b.status = 'confirmed'` (o el `session_id` en preview) — el propio docstring documenta que sin ese filtro entraban **208.950 filas de batches revertidos en 313 usuarios** (`:42-53`).
- Nominal negativo se descarta: `{k: v for k, v in pos.items() if v > 1e-9}` (`:82`) — "no es una posición corta: es el ledger avisando que le falta la compra".
- `cash_en` (`:93-131`): `_CASH_MAS = ("DEPOSIT","SELL","DIVIDEND","INTEREST","FUTURES_PNL")`, `_CASH_MENOS = ("WITHDRAW","BUY","FEE","IMPUESTO")` (`:89-90`), y `fees + taxes` salen del efectivo en cualquier operación (`:130`).
- `verificar_contra_hoy` (`:134-167`): si el replay no reproduce `positions` de hoy con tolerancia 1 %, no se puede reconstruir el pasado. `motivo ∈ {sin_ledger, ledger_incompleto}`.

**Valuación** (`valor_en`, `:195-314`) `[V]`:
- **Delega en `snapshots_job.compute_broker_value_usd`**, el mismo motor del cron (`:273-275`). Explícitamente para no tener un segundo motor de valuación.
- `asset_type` histórico sale del LEDGER, no de `positions` (`:234-242`) — porque un CEDEAR vendido ya no está en `positions` y pediría el ticker US en vez del `.BA` (el bug C1, "15-100x inflado").
- FX: `_fx_en` = `mep_venta` más reciente ≤ fecha (`:185-192`). Sin FX y con broker ARS → `motivo='sin_fx'`, no se inventa tasa.
- **Cobertura por VALOR, no por conteo** (`:279-301`): lo que no tiene precio se pesa por su costo (`SUM(gross_amount)` de los BUY); si no hay ni precio ni costo, `peso_desconocido = True` y no se publica.
- Umbral: `COBERTURA_MINIMA = 0.98` (`:32`). `ok = (not faltan) or (pct >= 0.98 and not peso_desconocido)` (`:301`).

⚠️ **Los dos límites que el propio archivo declara** (`:9-25`) `[V]`:
1. El ledger puede estar incompleto (transferencias filtradas por el validator, posiciones cargadas a mano) → replay más chico que la realidad → se lee como pérdida.
2. **La base de cambio no es la misma**: el cron valúa al MEP MEDIO y acá sólo hay `mep_venta`. Encadenar un borde reconstruido a la venta con uno medido al medio fabrica ~0,7 % de retorno de la nada.

`[I]` El límite 2 sigue vivo aunque `ledger_replay` esté dormido: el que SÍ escribe las fotos `mtm_backfill` es `backend/scripts/backfill_historical_mtm.py`, y su docstring dice "FX histórico: BLUE de fx_rates_daily … MEP: blue-proxy" (`backend/scripts/backfill_historical_mtm.py:22-24`), o sea una TERCERA base de cambio. Y `twr.tramos` estampa `fx_basis='mep_medio'` sin verificarlo (`backend/twr.py:788`). Tres bases de cambio, un solo campo que las declara y nadie que las compare.

`price_history.precio_en` (`backend/price_history.py:54-62`): último precio ≤ fecha dentro de `MAX_DIAS_ATRAS = 7` (`:23`); `None` significa "no se puede valuar", nunca 0. `[V]`

---

## 6 · `backend/advisor_twr.py` (124 líneas)

**Qué calcula**: nada propio. Es la capa de agregación del libro del asesor sobre `twr.py`. El docstring lo dice explícitamente: "Todo lo que sea cálculo por persona vive en `twr.py` y NO acá". `[V]` `backend/advisor_twr.py:1-8`

Dos funciones `[V]`:

| Función | Qué hace | Endpoint |
|---|---|---|
| `salud_del_libro` (`:32-70`) | `twr.diagnosticar(conn, client_uids)` + resumen con `cobertura_pct` | `GET /api/advisor/data-health` (`backend/main.py:33716`) |
| `twr_por_cliente` (`:79-124`) | `twr.sellar()` + `twr.twr_de()` por cliente | `GET /api/advisor/twr` (`backend/main.py:33698`) |

**Reglas propias**:
- `MESES_MINIMOS = 3` (`:76`): debajo de ese piso no se muestra porcentaje, se muestra el motivo. `[V]`
- `publicable = r["twr"] is not None and meses >= MESES_MINIMOS` (`:100`). `[V]`
- **El motivo del motor manda** sobre `"pocos_meses"` (`:101-111`): un cliente con 6 meses y uno dudoso salía como "pocos meses", el aviso equivocado. `[V]`
- Un cliente roto no tumba el libro: `sellar` va en `try/except` con log warning (`:94-97`). `[V]`

⚠️ **Sesgo de supervivencia declarado y NO resuelto** (`_clientes_vigentes`, `:16-29`) `[V]`:
> "Para el TWR de un período histórico esto NO alcanza: hay que usar el roster VIGENTE en cada mes (`created_at` / `revoked_at`), o el que se da de baja hoy desaparece de toda la historia y el retorno del año pasado mejora solo."

El código usa `status='active'` de HOY. Para `salud_del_libro` ("de quién puedo hablar AHORA") está bien; **`twr_por_cliente` usa el mismo roster** (`:87`) y ése sí publica historia. `[I]` El TWR por cliente no tiene sesgo (es por cliente), pero cualquier agregación futura sobre esa lista sí. El propio docstring reconoce que el composite ponderado es "la Fase 2" y que "NO se puede sacar promediando estos números" (`:84-85`).

---

## 7 · `backend/analysis_prep.py` (102 líneas)

**Qué calcula**: no es un motor de retorno. Es el **prep de moneda** compartido: estampa `brokers.currency` en `positions`/`operations`, arma los símbolos `.BA` y devuelve `(prices, tc_blue, tc_cedear)`. `[V]` `backend/analysis_prep.py:1-13`

Tres funciones `[V]`:
- `user_fx` (`:31-48`): `tc_blue` de `config` (default **1415.0** hardcodeado, `:39`); `tc_cedear` **live-first** desde `main._current_cedear_rate()`, con fallback a `config.tc_mep` y después a `tc_blue`.
- `fetch_ba_aware_prices` (`:51-75`): pide `<asset>.BA` cuando `behavioral._price_is_ars(p)` es verdadero. Sin esto "toda posición AR cae a costo de compra".
- `currency_context` (`:78-102`): estampa currency + `stamp_byma` (parent-aware) y devuelve la terna.

**Quién lo llama** `[V]`: `backend/main.py:13693`, `:13778`, `:15235` (`currency_context`); `backend/snapshots_job.py:151` y `backend/reporting/timeline.py:105` (`user_fx`).

⚠️ **Import circular en caliente** (`:42`): `from main import _current_cedear_rate` dentro de un `try/except Exception` que traga todo. `[I]` Si el import falla (o `main` no está cargado, p. ej. en un worker), `live_mep = None` en silencio y la valuación cae a `config.tc_mep` o al blue — sin log, sin señal. Es exactamente la clase de fallback silencioso que el resto del repo persigue.

⚠️ **El `1415.0` hardcodeado** aparece también en `backend/main.py:_user_tc_blue` (dos veces) y como default de `config`. `[V]` `backend/analysis_prep.py:39`, `backend/main.py:32986-32989`.

---

## 8 · CLAMPS Y COTAS — inventario completo

### 8.1 Backend, motor canónico

| Cota | Valor | Qué pasa cuando se activa | Cita |
|---|---|---|---|
| Piso de `dietz` | **−1,0** | el leg queda en −100 % → el índice va a CERO (absorbente). Por eso `leg_dudoso` lo caza antes | `backend/twr.py:576` |
| Techo de `dietz` | **ninguno** — decisión explícita | — | `backend/twr.py:566-572` |
| `SALTO_MAX_VECES` | **3,0** | ratio `v1/v0` fuera de `[1/3, 3]` con `|flujo| < 10 % · max(v0,v1)` → `'salto'` → **corta el tramo**; el leg no se encadena y la serie queda partida | `backend/twr.py:612`, `:644-647` |
| `SALTO_FLUJO_TOL` | **0,10** | por encima el leg puede ser un depósito real; el salto no se evalúa | `backend/twr.py:613`, `:644` |
| `DENOM_MIN_FRACCION` | **0,25** | si `v0 + 0,5·flujo < 0,25·v0` → `'desborde'` → corta | `backend/twr.py:620`, `:640-642` |
| `FLUJO_SOSPECHOSO` | **0,5** | marca el mes sellado como `quality='flujo_sospechoso'`; **no** impide publicar | `backend/twr.py:556`, `:780` |
| `MAX_HUECO_DIAS` | **45** | parte la serie; el índice y el pico se reinician en el tramo siguiente | `backend/twr.py:912`, `:1496` |
| `MAX_HUECO_CONTABLE_DIAS` | **400** | idem, sólo entre dos puntos contables | `backend/twr.py:927`, `:1493` |
| Cota del traspaso contable→mercado | ratio fuera de `[1/3, 3]` | `motivo='cadena_implausible'` → corta y **Reportes deja de publicar** | `backend/twr.py:1513-1521` |
| `COBERTURA_MEDICION` | **0,90** | debajo, una foto `mtm_backfill` es `VALUADO_AL_COSTO`: entra a la línea pero **nunca es pico ni denominador** | `backend/twr.py:127`, `:302-306` |
| `PLANO_RUEDAS` / `PLANO_TOL` | **3** / **0,0001** | sólo se REPORTA en `diagnosticar.tramos_planos` y en `quality='plano'`; no corta nada | `backend/twr.py:159-160`, `:781` |
| `RACHA_CRON_MINIMA` | **7** | asciende filas legacy `INTRADIA` → `MEDICION` | `backend/twr.py:362`, `:422` |
| Piso de anualización | **0,5 años** | `cagr = None` y la respuesta trae el acumulado con su ventana | `backend/twr.py:2171` |
| `MESES_MINIMOS` (asesor) | **3** | sin porcentaje, con motivo | `backend/advisor_twr.py:76`, `:100` |
| Mes `dudoso` en el sellado | cualquiera | `twr_de` devuelve `twr=None` + `motivo='medicion_dudosa'` para TODO el período | `backend/twr.py:864-884` |
| `est_publicable` | ≥ 1 tramo con legs | el ESTIMADO publica la ventana continua más reciente (el CERTERO exige tramo único) | `backend/twr.py:2141-2147` |
| ESTIMADO: drawdown/pico | siempre | `dd_actual = dd_max = pico = None` publique o no | `backend/twr.py:2158-2159` |

### 8.2 Backend, fuera del motor

| Cota | Valor | Efecto | Cita |
|---|---|---|---|
| `PICO_MAX_VECES_LA_CARTERA` | **8,0** | la alerta de drawdown del libro NO se emite si `pico / cartera_hoy > 8`. Lo silenciado se lista en `/api/admin/diagnose-reportes-basis → picos_implausibles` | `backend/main.py:36734`, `:36752`, `:37216` |
| piso de drawdown del libro | `adj_mx >= 500` USD, `dd <= -15 %` | no se grita drawdown sobre resultados chiquitos | `backend/main.py:37207`, `:37216` |
| `_UNMEASURED_BASE_TOL` | **0,10** | si > 10 % de la base es contabilidad sin medir → `basis_incomparable` → Reportes publica `delta_pct=None` y `delta_usd=0` | `backend/reporting/builder.py:440`, `:443-459` |
| `_BORDER_MAX_LAG_DAYS` | **5** (y **1** en `bordes_mercado_periodo`) | sin borde fresco no hay período medido | `backend/reporting/builder.py:293`, `:566`, `:590` |
| `_BORDER_SCAN_LIMIT` | **90** filas | `fetch_snapshot_at_or_before` sólo mira 90 snapshots hacia atrás | `backend/reporting/builder.py:290`, `:364` |
| gap día/semana | día > 4 d, semana > 10 d | `dw_incomplete` → `delta_pct=None` | `backend/reporting/builder.py:1459-1462` |
| `_modified_dietz_pct` | **NO clampa** (declarado) | −150 % sale como −150 | `backend/reporting/builder.py:783-795` |
| cota de las puntas en Reportes | `leg_dudoso` + (con `v0=0`) `end_value / flujo > SALTO_MAX_VECES` | `_motor_nego = 'medicion_dudosa'` → `delta_pct=None`, `delta_usd=0`, `basis_incomparable=True` | `backend/reporting/builder.py:1578-1601` |
| `MOTIVOS_DATO_ROTO` | `('medicion_dudosa','cadena_implausible')` | **sólo** estos dos cortan; los motivos de falta de datos dejan publicar la contabilidad | `backend/reporting/builder.py:809` |
| `_cagr_from_monthly_rows` | `max(-0.95, min(5.0, r))` | **techo de +500 % mensual** | `backend/main.py:15308` |
| `/api/insights/mtm-audit` | `max(r, -0.99)` | piso distinto al del motor | `backend/main.py:11891-11892` |
| `COBERTURA_MINIMA` (replay) | **0,98** | `valor=None`, `motivo='cobertura_insuficiente'` | `backend/ledger_replay.py:32`, `:301` |
| `MIN_COVERAGE` (backfill MTM) | ver `backend/scripts/backfill_historical_mtm.py` | no escribe snapshot si la cobertura no llega | `backend/scripts/backfill_historical_mtm.py:395-402` |
| `MAX_DIAS_ATRAS` (precio) | **7** | `precio_en` devuelve `None` | `backend/price_history.py:23` |
| `factor` (diagnóstico flujos) | **20,0** | barrido admin de flujos > 20× el pico de la cartera | `backend/main.py:18119` |

### 8.3 Frontend

| Cota | Valor | Dónde | Cita |
|---|---|---|---|
| piso mensual | **−0,99** | `buildCumulativeReturnSeries` | `frontend/src/utils/insightsModel.js:135` |
| piso mensual | **−0,99** | `monthlyReturnArs` | `frontend/src/utils/insightsModel.js:563` |
| piso mensual | **−0,99** | `buildEvolutionFromSnapshots` (USD y ARS) | `frontend/src/utils/evolution.js:544`, `:588` |
| piso mensual + live | **−0,99** | serie de Insights | `frontend/src/pages/Insights.jsx:683`, `:725`, `:749` |
| **techo +50 %** | **eliminado** en las 4 series de cartera | comentarios "SIN TECHO" | `frontend/src/utils/evolution.js:538-543`, `frontend/src/pages/Insights.jsx:677-682` |
| **`[−99, +200]`** | **VIVO** | sólo en el fallback flow-matched de benchmarks ARS-nativos (Merval / plazo fijo / pesos cash) | `frontend/src/pages/Insights.jsx:1568`, `:1578` |
| `stableInv` / `safeDenom` | `cur >= peak·0,6 && cur > 1000` ? `cur` : `peak` | denominador "estable" del realized % y del benchmark ARS | `frontend/src/pages/Insights.jsx:661`, `:1476` |
| `peakValue·0,8` | denominador del realized % | `frontend/src/utils/evolution.js:552` (`Math.max(baselineUsd, peakValueUsd * 0.8)`) | `frontend/src/utils/evolution.js:552`, `:575` |
| `_UNMEASURED_BASE_TOL` portado | **0,10** | `baseIncomparable` | `frontend/src/utils/evolution.js:113` |

⚠️ **La asimetría que quedó**: el clamp `[−99, +200]` se le aplica al benchmark ARS-nativo y **no** a la cartera. `[V]` `frontend/src/pages/Insights.jsx:1568`. `[I]` Es el mismo sesgo que el repo eliminó del lado de la cartera, con el signo dado vuelta: un Merval que hizo +350 % en pesos se dibuja en +200 % contra una cartera sin techo.

---

## 9 · ⚠️ DUPLICACIÓN — el hallazgo principal

Nueve fórmulas de retorno vivas. Las pongo lado a lado.

### 9.1 Las nueve

| # | Dónde | Denominador | Piso / techo | Metodología |
|---|---|---|---|---|
| **1** | `backend/twr.py:573-576` (canónico) | `v0 + 0,5·flow` | −1,0 / — | TWR (chain-link Dietz) |
| **2** | `backend/reporting/builder.py:792-795` | `start + 0,5·flows` | ninguno | Dietz punta a punta o compuesto mensual |
| **3** | `backend/main.py:11871-11873` (`/api/insights/mtm-audit`) | `ci + 0,5·net` | **−0,99** en el compuesto (`:11891`) | Dietz mensual × 2 cadenas (costo y MtM) |
| **4** | `backend/main.py:15308` (`_cagr_from_monthly_rows`) | **`ci` pelado** — *sin* `0,5·flow` | **`[−0,95, +5,0]`** | retorno simple mensual, media geométrica anualizada |
| **5** | `backend/main.py:33025-33026` (`_ytd_delta`) | `start + 0,5·net_flows` | ninguno | Dietz punta a punta anual |
| **6** | `backend/main.py:35700-35702` (`_advisor_report_payload`) | `v0 + flows/2`, **con guard `> 100`** | ninguno | Dietz punta a punta del período |
| **7** | `backend/main.py:32939-32945` (`_snapshot_delta`) | **`prev_v`** — *sin* medio flujo | ninguno | `((v1−nd1)−(v0−nd0)) / v0` |
| **8** | `backend/advisor_alerts.py:288` | **`base`** — *sin* medio flujo | ninguno | `((now−flow)−base)/base` |
| **9** | `frontend/…` (3 variantes, ver 9.3) | híbrido (ver abajo) | −0,99 / — | TWR chain-link con heurísticas |

### 9.2 Duplicación #1 — el mismo TWR, dos motores que no se hablan

**A · Motor del asesor** (`backend/twr.py:740-793` + `:848-884`)
```python
bordes = bordes_medibles(conn, uid)              # SOLO clase == MEDICION
cierre = {b["date"][:7]: b for b in bordes}      # último borde de cada mes
flow   = _flujo(conn, uid, b0["date"], b1["date"])   # compute_net_deposited_db × 2
r      = dietz(v0, v1, flow)
TWR    = Π(1 + r_mes) − 1
```

**B · Motor de la app** (`backend/twr.py:1283-2213`)
```python
puntos = serie_medible(...)                      # ACEPTA_LINEA (incluye INTRADIA y RECONSTRUIDO)
flow   = _aportado_por_punto(...)                # netdep_canonico + estampa, con clamp
r      = dietz(*_leg_en_moneda(ancla, p, ...))   # apto→apto, saltea lo no-apto
TWR    = Π(1 + r_leg) − 1
```

Diferencias medibles `[V]`:

| | A (asesor) | B (app) |
|---|---|---|
| clases aceptadas | `MEDICION` sola | `MEDICION + RECONSTRUIDO + INTRADIA` (+ `SINTETICO_COSTO` en estimado) |
| granularidad | mensual | por snapshot |
| flujo | `compute_net_deposited_db` (baseline al 1er mes) | `netdep_canonico` (baseline hacia atrás) + clamp |
| mes de alta | **excluido** (`:756`) | incluido |
| cota de plausibilidad | `leg_dudoso` marca el mes, `twr_de` no publica si hay uno | `leg_dudoso` **corta el tramo** |
| moneda | **sólo USD** | USD / ARS |
| huecos | no se miran | parten la serie (45 / 400 días) |
| drawdown | no calcula | sí |
| CAGR | no calcula | sí, con piso de medio año |
| persistencia | `twr_periods` append-only con revisión | ninguna |

`[I]` **Nadie los reconcilia.** Un asesor mirando `GET /api/advisor/twr` y el mismo usuario mirando `GET /api/insights/performance` pueden ver dos TWR distintos del mismo período por al menos cinco razones estructurales de la tabla, y el sistema no tiene ningún test ni endpoint que los compare. El propio `advisor_twr.py:1-8` dice que existe para que eso no pase — pero lo que comparte es el archivo, no el resultado.

### 9.3 Duplicación #2 — la misma serie mensual, TRES variantes de Dietz en el frontend

**Canónico backend** (`backend/twr.py:573-576`):
```python
denom = v0 + 0.5 * flow
r = max((v1 - v0 - flow) / denom, -1.0)
```

**a) `insightsModel.js` — `buildCumulativeReturnSeries`** (`frontend/src/utils/insightsModel.js:123-137`):
```js
const isImportInitialMonth = isFirst && capInicio === 0 && net > 0
const avgCapital = isImportInitialMonth ? net : capInicio + 0.5 * net
const rawReturn  = avgCapital > 0 ? (capFinal - capInicio - net) / avgCapital : 0
const monthlyReturn = Math.max(rawReturn, -0.99)
```
→ heurística **`isImportInitialMonth`** (denominador = `net` completo, no medio) + piso **−0,99**.

**b) `evolution.js` — `buildEvolutionFromSnapshots`** (`frontend/src/utils/evolution.js:530-544`):
```js
const flowRatio     = prevValueUsd > 0 ? Math.abs(flows) / prevValueUsd : 0
const isBigWithdraw = flows < 0 && flowRatio > 0.3
const avgCap        = isBigWithdraw ? prevValueUsd : (prevValueUsd + 0.5 * flows)
const rRaw          = avgCap > 0 ? pnl / avgCap : 0
const r             = Math.max(rRaw, -0.99)
```
→ heurística **`isBigWithdraw`** (retiro > 30 % del capital ⇒ denominador = `v0`) + piso **−0,99**. **No** tiene `isImportInitialMonth`.

**c) `Insights.jsx` — la serie mensual del gráfico** (`frontend/src/pages/Insights.jsx:673-683`):
```js
const isImportInitial = isFirst && ci === 0 && net > 0
const flowRatio       = ci > 0 ? Math.abs(net) / ci : 0
const isBigWithdraw   = net < 0 && flowRatio > 0.3
const avgCap = isImportInitial ? net : (isBigWithdraw ? ci : ci + 0.5 * net)
const r      = Math.max(rRaw, -0.99)
```
→ **las DOS heurísticas juntas**, en un orden de precedencia que ninguna de las otras dos tiene.

**d) La pata "Hoy" de Insights** (`frontend/src/pages/Insights.jsx:724-725`):
```js
const rLive = (totalPortfolio - lastCf) / lastCf     // ← SIN ajuste por flujos
const rLiveClamped = Math.max(rLive, -0.99)
```
→ **no es Dietz**: no descuenta ningún flujo posterior al cierre del mes. El backend sí lo hace (`backend/twr.py:2044-2053`, `_flujo_live`). `[I]` Un depósito hecho hoy antes de que el cron escriba la foto entra entero como rendimiento en la línea del frontend, y no en el número del backend.

**Consecuencia `[I]`**: el mismo mes de la misma cuenta puede tener CUATRO retornos distintos según qué pantalla lo dibuje. Ninguna de las tres variantes JS aplica `leg_dudoso`, ni corta por hueco, ni distingue base mercado/costo por segmento — sólo `evolution.js:444` filtra por `esApto` y `insightsModel.js:618` saltea `sintetico`.

### 9.4 Duplicación #3 — el `-0,99` contra el `-1,0`

Cinco lugares usan `-0.99` y el canónico usa `-1.0`:
`frontend/src/utils/insightsModel.js:135`, `:563`; `frontend/src/utils/evolution.js:544`, `:588`; `frontend/src/pages/Insights.jsx:683`, `:725`, `:749`; `backend/main.py:11891-11892`. `[V]`

`[I]` No es cosmético. `-1.0` es el disparador de `leg_dudoso → 'desborde'` (`backend/twr.py:635-636`): `r <= -1.0 + 1e-12`. Con `-0.99` ese leg **nunca** toca el piso, así que la firma del desborde no existe en las series JS ni en el mtm-audit — la única señal que el motor canónico usa para detectar "el denominador no da para medir" se pierde por diseño en los otros cinco.

### 9.5 Duplicación #4 — el retorno de N días: dos fórmulas para la misma pregunta

| | `_snapshot_delta` (chips Δ1d/7d/30d) | `_ytd_delta` (chip YTD) |
|---|---|---|
| Fórmula | `delta = (v1−nd1) − (v0−nd0)`; `pct = delta / v0` | `pnl = v1 − start − flows`; `pct = pnl / (start + 0,5·flows)` |
| Ponderación del flujo | **ninguna** (flujo completo, cualquier día) | media (Dietz) |
| Cita | `backend/main.py:32939-32945` | `backend/main.py:33025-33031` |

Las dos salen del **mismo** `_portfolio_snapshot_summary` (`backend/main.py:32756-32762`), en la misma tarjeta. `[V]` `[I]` Un depósito grande en el período hace que el Δ30d y el YTD no sean comparables entre sí, en la misma pantalla.

Y `advisor_alerts.py:288` usa la variante sin ponderar (`((now_v − _flow) − base) / base`) para decidir si **manda un mail**. `[V]`

### 9.6 Duplicación #5 — la clasificación de snapshots, séptimo lector

`backend/main.py:5127-5133` (`GET /api/snapshots`) hace:
```python
_clases = _twr.clasificar_serie(rows, _primera, orden_desc=True)
_bases  = _twr.bases_de_serie(rows, _clases)
...
d["apto"] = _twr.es_apto(_clase, _base)          # backend/main.py:5148
```
o sea **RECALCULA** `apto` en vez de leer el estampo, mientras `twr.aptos_de_serie` (`backend/twr.py:1135-1149`) prefiere `snapshots.apto`. `[V]`

`[I]` **Esto reabre exactamente el defecto que `snapshots.apto` vino a cerrar**: `clasificar_serie` necesita ver una racha de 7 días CONSECUTIVOS dentro de las filas traídas (`backend/twr.py:420-427`), y esta query trae `LIMIT ?` = `days` (`backend/main.py:5114`). Una fila legacy que cae en los primeros días de la ventana de `?days=30` no ve su racha completa y queda `INTRADIA` → `apto=False`; con `?days=3650` la racha se completa y queda `MEDICION` → `apto=True`. La misma fila, dos respuestas según la ventana. `evolution.js:444` filtra por ese flag, así que el Dashboard y la vista de 30 días pueden encadenar conjuntos de puntos distintos. El comentario de `backend/twr.py:1109-1126` describe este mismo bug como resuelto.

---

## 10 · Hallazgos ordenados por gravedad

| # | Hallazgo | Evidencia | Nivel |
|---|---|---|---|
| H1 | Nueve fórmulas de retorno vivas; seis con piso/techo propio; tres heurísticas de flujo mutuamente incompatibles en el frontend | §9 | `[V]` fórmulas · `[I]` consecuencia |
| H2 | `GET /api/snapshots` recalcula `apto` en vez de leer el estampo y la respuesta depende de `?days` | `backend/main.py:5127-5148` vs `backend/twr.py:1135-1149` | `[V]` código · `[I]` efecto |
| H3 | Motor del asesor y motor de la app miden el mismo TWR con 10 diferencias estructurales y nadie los reconcilia | §9.2 | `[V]` |
| H4 | `backend/flujos.py` y `backend/ledger_replay.py` son código muerto en producción (sólo tests) | grep §4, §5 | `[V]` |
| H5 | `flujos.resolver` nunca puede llegar a `cruce_entre_brokers` desde `reconciliar`: las claves `asset`/`fecha`/`cantidad` no las produce `candidatos` | `backend/flujos.py:67-71` vs `:126` | `[V]` claves · `[I]` alcance |
| H6 | El piso `-0,99` del frontend y del mtm-audit desactiva la detección de 'desborde' del motor | §9.4, `backend/twr.py:635-636` | `[V]` · `[I]` |
| H7 | La pata "Hoy" del gráfico de Insights no descuenta flujos; la del backend sí | `frontend/src/pages/Insights.jsx:724` vs `backend/twr.py:2044-2053` | `[V]` |
| H8 | `realized` de Reportes suma las ops `CONVERSION…` que `closed_filter_sql` excluye | `backend/reporting/builder.py:842` + `backend/main.py:10962-10970` | `[V]` · `[I]` |
| H9 | Tres criterios distintos de "operación cerrada": `''` no excluido en builder×2 ni en timeline | §3.4 | `[V]` |
| H10 | Tres bases de cambio distintas (`mep_medio` estampado sin verificar, `mep_venta` en el replay, blue-proxy en el backfill) y ningún comparador | `backend/twr.py:788`, `backend/ledger_replay.py:31`, `backend/scripts/backfill_historical_mtm.py:22-24` | `[V]` los tres strings · `[I]` la consecuencia |
| H11 | `_snapshot_delta` (sin Dietz) y `_ytd_delta` (con Dietz) conviven en la misma tarjeta | §9.5 | `[V]` |
| H12 | El clamp `[−99, +200]` sobrevive sólo del lado del benchmark ARS, no de la cartera | `frontend/src/pages/Insights.jsx:1568`, `:1578` | `[V]` · `[I]` |
| H13 | `_cagr_from_monthly_rows` es código muerto con un techo de +500 % mensual y denominador sin medio flujo | `backend/main.py:15293-15317`; sin callers fuera de tests | `[V]` |
| H14 | `performance.py` es lista blanca: un campo nuevo del motor no llega al JSON — ya pasó con `base_del_twr` | `backend/performance.py:263-268` | `[V]` |
| H15 | `serie_fx` se invoca una vez POR PUNTO de la banda contable, y cada llamada hace un SELECT completo | `backend/performance.py:241-244`, `backend/twr.py:1247-1252` | `[V]` · `[I]` costo |
| H16 | `netdep_canonico` y `compute_net_deposited_db` tratan el `baseline` distinto **a propósito**, y los dos motores de TWR usan uno cada uno | `backend/twr.py:975-991` vs `backend/snapshots_job.py:379-386` | `[V]` · `[I]` |
| H17 | `analysis_prep.user_fx` importa `main` en caliente dentro de un `except Exception` mudo | `backend/analysis_prep.py:41-46` | `[V]` · `[I]` |
| H18 | Roster del asesor con sesgo de supervivencia declarado y sin resolver | `backend/advisor_twr.py:16-29` | `[V]` |
| H19 | `fetch_snapshot_at_or_before` escanea sólo 90 filas y clasifica por serie sobre esa ventana truncada — misma familia que H2 | `backend/reporting/builder.py:290`, `:364`, `:378` | `[V]` · `[I]` |
| H20 | El win rate cuenta cupones como "operaciones ganadas" — declarado por el propio módulo y sin decidir | `backend/realized_pnl.py:34-53` | `[V]` |

---

## 11 · Cadena de llamadas — quién consume qué

```
GET /api/insights/performance   (main.py:11789)
  └─ performance.performance    (performance.py:182)
       ├─ twr.curva_indexada    (twr.py:1611)
       │    └─ twr.serie_medible (twr.py:1283)
       │         ├─ twr.clasificar_serie / bases_de_serie / aptos_de_serie
       │         ├─ twr._aportado_por_punto → twr.netdep_canonico → monthly_entries
       │         ├─ twr.serie_fx → fx_rates_daily
       │         └─ twr.leg_dudoso → twr.dietz
       │    └─ snapshots_job.compute_net_deposited_db   (pata live)
       └─ performance.benchmark_recortado / _en_pesos

GET /api/advisor/twr            (main.py:33698)
  └─ advisor_twr.twr_por_cliente (advisor_twr.py:79)
       ├─ twr.sellar  → twr.tramos → twr.bordes_medibles + twr._flujo + twr.dietz
       └─ twr.twr_de  → tabla twr_periods

GET /api/advisor/data-health    (main.py:33716)
  └─ advisor_twr.salud_del_libro → twr.diagnosticar

GET /api/goals/cagr             (main.py:15395)
  └─ main._historical_cagr_global → twr.curva_indexada

Reportes (reporting/builder.compute_metrics_for_period, builder.py:826)
  ├─ mes cerrado:   bordes_mercado_periodo → twr.BORDE_PERIODO   (builder.py:523)
  ├─ mes s/bordes:  twr.curva_indexada                            (builder.py:1060)
  ├─ año:           twr.curva_indexada                            (builder.py:1234)
  ├─ fallback:      _modified_dietz_pct + twr.leg_dudoso          (builder.py:1374, :1370)
  └─ puntas:        twr.leg_dudoso + twr.SALTO_MAX_VECES          (builder.py:1583, :1594)

Alertas del asesor (main.py:37156, advisor_alerts.py:249)
  └─ vista snapshots_medibles (main.py:1459-1471) + _pico_es_plausible (main.py:36737)

Frontend
  ├─ Insights.jsx:1779  buildCumulativeReturnSeries  (motor JS #a)
  ├─ Insights.jsx:579   buildEvolutionFromSnapshots  (motor JS #b)
  ├─ Insights.jsx:673   loop mensual propio          (motor JS #c)
  ├─ Insights.jsx:1808  drawdownFromPerf(perf)       ← el drawdown SÍ viene del backend
  ├─ Dashboard.jsx:642  computeDailyPnl / computeReturnDelta
  └─ HomeMobile.jsx:190 computeReturnDelta

MUERTOS: ledger_replay.py (sin callers), flujos.py (sin callers),
         main._cagr_from_monthly_rows (sin callers)
```
`[V]` todas las líneas verificadas con `grep -n`.

---

## 12 · Evidencia secundaria: la base de desarrollo

`backend/trading.db` está muy atrás del código y **eso mismo es evidencia de por qué existen los guards de columna**:

```
snapshots(id, user_id, date, total_value, total_invested, net_deposited, fx_to_usd_blue)
```
Faltan `holdings_json`, `source`, `mtm_coverage`, `base`, `apto`. `twr_periods` **no existe**. `fx_rates_daily` no tiene `mep_venta`. `[V]` (`sqlite3 backend/trading.db ".schema"`)

Contra esa base: `twr._sel_estampo` pide `NULL AS base, NULL AS apto` (`backend/twr.py:1094-1099`), `serie_fx` cae a `blue_venta` (`backend/twr.py:1265-1266`), `clasificar_fila` cae a la heurística legacy (`backend/twr.py:197-212`) y `sellar` **rompería** (no hay tabla). `[I]`

---

## 13 · Lo que NO encontré (dicho explícitamente)

- **El matcheo FIFO de una venta contra su costo**: no está en ninguno de los siete archivos. `realized_pnl.py` lee `operations.pnl_usd` ya calculado. — **no encontrado** en el alcance.
- **Tratamiento de traspasos entre brokers dentro del TWR**: `twr.py` no los distingue. — **no encontrado**.
- **Tratamiento de conversiones de moneda como flujo**: entran como `pnl_realized` en `monthly_entries`, no como flujo. — **no encontrado** un manejo específico en `twr.py`.
- **Un test o endpoint que compare el TWR del asesor contra el de la app** para el mismo usuario. — **no encontrado**.
- **Un escritor de `source='mtm_backfill'` en el servidor**: sólo el CLI `backend/scripts/backfill_historical_mtm.py`. No hay endpoint ni hook que lo dispare. — **no encontrado**.
- **Un endpoint de admin que fuerce `estampar_base`**: el docstring de `_migrate_estampar_base` dice explícitamente que no existe y que la única palanca es un redeploy (`backend/main.py:32177-32180`). `[V]`
