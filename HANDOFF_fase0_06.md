# Handoff — Fase 0.6: reportes, snapshot y cuota no ven el sub-broker

Rama: `fix/fase0-broker-unificado` · Nada pusheado ni deployado.
Contexto completo: `ANALISIS_broker_unificado_2026-09-04.md` (§5, FASE 0).

## Dónde quedó

5 de los 6 fixes de Fase 0 están commiteados y verificados:

| commit | qué |
|---|---|
| `b2751a8f` | borrar el broker padre fallaba con FOREIGN KEY constraint failed |
| `23b37e06` | "Ver lotes" por fila no expandía nada |
| `ed30f34f` | esa expansión se filtraba entre brokers |
| `1fcfe8a5` | Dashboard/Home no pedían el `.BA` del sub-broker → P&L 0 en la pata dólar |
| `9d563aab` | mobile: la fila agregada perdía el factor cripto del costo (~+5% fantasma) |
| `1795e1a1` | el test de cascade trababa la DB del resto de la suite |
| `ca649bf2` | `valueArsDisp`/`invArsDisp`: campos en pesos sumables entre brokers |

Estado de tests al cerrar:
- Frontend: **723 pasando**, build limpio.
- Backend: **24 fallas contra 25 del baseline** (cero nuevas). Las 24 son
  preexistentes: mayormente `database is locked` bajo carga, más `test_news`,
  `test_crypto_ars_price`, `test_billing`. Comando: `cd backend && python3 -m pytest tests/ -q -p no:randomly`.

## Antes de tocar nada: verificar 0.3 en la app

`1fcfe8a5` tiene un efecto observable al deployar. `priceCoverage`
(`Dashboard.jsx:279`) es el gate ≥0.95 del snapshot diario. Hoy las posiciones
del sub-broker no tienen precio y lo deprimen. Al arreglarlo, la cobertura sube,
el snapshot se destraba y se escribe con un `total_value` mayor → **un salto de
una sola vez** en la variación del día siguiente. Es el número correcto
apareciendo. Conviene confirmarlo en local antes de seguir.

Chequeo concreto: levantar la app, ir al Dashboard con una cuenta que tenga
sub-broker "· USD", y confirmar que su P&L dejó de ser exactamente 0.

---

## Lo que falta: 0.6

**16 parches en 5 archivos.** La spec completa y la revisión adversarial están en
el journal del workflow:
`~/.claude/projects/-Users-nicolaspussetto-Documents-trading/31c3240d-a851-49f8-8d88-e41036ed4a80/subagents/workflows/wf_7087215d-03a/journal.jsonl`
(buscar `FIX-0.6` en las entradas `type=result`).

### El problema

Cuando el usuario pide el reporte de "IOL", las operaciones de "IOL · USD"
quedan afuera: el filtro es por nombre exacto. El helper que devuelve el par es
`broker_pair` (`backend/importing/persister.py:64-90`), importable desde
`reporting` sin ciclo.

### Dos punteros del informe están MAL

El informe original apuntaba a lugares que no son:

- `builder.py:152` **no tiene** ningún `COUNT(DISTINCT ...)`. Es la línea
  `WHERE user_id=? AND broker=? AND year=? AND month=?` de `fetch_monthly_entry`.
  El único `COUNT(DISTINCT broker)` está en `main.py:17790`.
- `main.py:17777` es **una línea en blanco**. Lo roto en `_portfolio_snapshot_summary`
  (17738-17864) es `br_clause` (17749-17750), `cum_deposited` (17772-17776) y
  `brokers_count` (17789-17795).
- `_broker_clause` (`builder.py:93-97`) es **código muerto**: cero callers.

### La cuota es el bug más visible para el usuario

`ai/plan.py:138` (`check_broker_quota`) y `:176` (`get_plan_features`) hacen
`SELECT COUNT(*) FROM brokers WHERE user_id=?`. El sibling lo crea
`_ensure_usd_sibling` con un INSERT directo que **no pasa por la cuota**.

Resultado: un usuario **Plus** (`brokers_max=3`) con 2 brokers reales + 2
siblings cuenta 4 y **no puede agregar el tercer broker al que tiene derecho**.
Y un **Free** con 1 broker + sibling sale marcado `grandfather=True` siendo falso.

### El doble conteo: más chico de lo que parecía

Mi advertencia inicial era imprecisa. La verdad:

- **El NETO no se infla.** `_persist_fx` (`persister.py:863-889`) escribe el
  `withdraw` en el padre y el `deposit` en el sibling, pero escribe **las mismas
  dos patas en 'global'**. Sumar el par reproduce exactamente lo que 'global' ya
  cree. O sea: capital aportado, flows de Modified Dietz y `delta_pct_over_contrib`
  dan idéntico. **No hay riesgo ahí.**
- **Lo que sí se infla es el BRUTO**: `metrics.deposits` / `metrics.withdrawals`,
  que se muestran como "Aportes US$ X" (`Reports.jsx:614-619`), gatillan
  `is_relevant` (`builder.py:629-634`) y alimentan `detect_deposits_vs_gains`
  (`reporting/detectors.py:114-134`).
- **Netear exacto es IMPOSIBLE** con lo guardado: la pata ARS se valuó con el
  `tc_blue` de config al momento del import (`persister.py:275-283` → `885`) y ese
  escalar no se persiste. De la fila de `operations` solo se reconstruye la pata USD.
  La salida es restar **el mismo monto de los dos lados**: net-neutral por
  construcción, desinfla el bruto sin mover capital, Dietz ni % sobre aportado.
  El match tiene que ser `'CONVERSION IMPORT %→USDT'` y **no** `'CONVERSION%'`:
  el endpoint manual `/api/conversions` (`main.py:7578-7688`) no escribe monthly
  flows, solo `pnl_realized`.

### Cuatro trampas si solo cambiás `=` por `IN`

1. **`builder.py:287-292`** (rama `year`): con dos filas por mes,
   `rows[0]["capital_inicio"]` y `rows[-1]["capital_final"]` agarran una fila
   **arbitraria** → capital del año partido al medio. Necesita `GROUP BY month` + `SUM`.
2. **`main.py:17930-17936`** (`_ytd_delta`): mismo problema con
   `ORDER BY month ASC LIMIT 1`. Necesita `GROUP BY month` + `SUM(capital_inicio)`.
   Ojo: hoy es **inalcanzable** — `main.py:17757` deja `latest_value = None` cuando
   `broker_filter != 'global'`. Se activa recién cuando la vista unificada pase un
   valor per-broker.
3. **`compute_net_deposited_db` con `include_baseline=True`** + lista de brokers
   sería un campo minado (el `ORDER BY year, month LIMIT 1` del baseline elegiría
   una fila arbitraria). Los dos únicos callers con broker no-global
   (`builder.py:169`, `main.py:17772`) pasan `include_baseline=False`, así que el
   fix suma broker por broker desde el caller y **no toca `snapshots_job.py`**.
4. **`backend/tests/test_ai_plan.py`** (`_make_db`, ~29-35) crea la tabla `brokers`
   **sin la columna `parent_broker_id`** → el parche de `plan.py` revienta 6 tests
   con "no such column". Hay que agregar la columna al fixture. No es opcional.

### Criterio de "listo"

- El reporte de "IOL" incluye las operaciones de "IOL · USD".
- La cuota cuenta 2, no 4, para un usuario con 2 brokers reales + 2 siblings.
- "Aportes US$" deja de contar dos veces las conversiones internas del par,
  **y** el capital aportado / Dietz / % sobre aportado no se mueven ni un peso
  (es el chequeo de que el neteo fue net-neutral).
- `pytest tests/ -q -p no:randomly` no suma fallas nuevas sobre las 24 actuales.

---

## Cómo NO hacerlo

Dos cosas que me salieron mal en la sesión anterior y conviene no repetir:

- **No hagas DDL sobre la DB de tests.** Es una sola para toda la sesión
  (`tests/conftest.py`). Reconstruir una tabla por test dispara `database is locked`
  en archivos que no tienen nada que ver. Si hace falta, una vez por clase y
  revertido en `tearDownClass` (ver `test_broker_delete_cascade.py`).
- **No confíes en `git stash` para verificar un test de regresión** si el fix ya
  está commiteado: no hay nada que stashear y `stash` sale con código 0 igual, así
  que parece que revirtió y no revirtió nada. Revertí el archivo a mano.
