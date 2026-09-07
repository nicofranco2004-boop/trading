## Suite de tests y cobertura real

> Todo lo de acá se leyó sobre la copia de `origin/main` (`b74f450f`). **No se corrió nada**:
> ni pytest, ni vitest, ni la app. Los conteos de tests son conteos de `def test_` (backend) y
> de `it(` / `test(` (frontend), no de tests *ejecutados* — un `@skipIf` o un parametrize
> cambia el número real y eso sólo lo sabe una corrida.

### 0. Los números de arriba

| Cosa | Valor | Cómo se midió |
|---|---|---|
| Archivos de test backend | **237** `test_*.py` | `ls backend/tests/` (241 entradas − `__init__.py`, `conftest.py`, `fallas_conocidas.txt`, `fixtures/`) `[V]` |
| Funciones `def test_` backend | **~3.720** | `grep -cE "^\s*def test_"` sobre los 237 `[V]` |
| Líneas de test backend | **69.561** | `cat backend/tests/test_*.py \| wc -l` `[V]` |
| Archivos de test frontend | **55** | `find frontend/src -name "*.test.js" -o -name "*.test.jsx"` `[V]` |
| `it(`/`test(` frontend | **~1.354** | `grep -cE "^\s*(it\|test)\s*\("` `[V]` |
| Líneas de test frontend | **12.509** | `[V]` |
| Fixtures en disco | **5 CSVs** | `backend/tests/fixtures/` `[V]` |
| Fallas conocidas declaradas | **26** | `backend/tests/fallas_conocidas.txt` `[V]` |
| CI | **no encontrado** | ver §1.4 `[V]` |
| Rutas `@app.*` en `backend/main.py` | 260 decoradores / **231 paths únicos** | `[V]` |
| Paths únicos sin **ninguna** mención literal en tests | **108** (47 %) | ver §7.1 `[V]` |

Contexto de tamaño: `backend/main.py` tiene **38.029 líneas** (`wc -l`, `[V]`). No hay `APIRouter`
en ningún lado — todas las rutas cuelgan del `app` de `main.py` `[V]`.

---

### 1. Cómo se corren

#### 1.1 Backend — el comando exacto

Config única: **`backend/pytest.ini`** (`backend/pytest.ini:29-31`) `[V]`:

```ini
[pytest]
testpaths = tests
norecursedirs = scripts .git node_modules __pycache__ .pytest_cache venv .venv
```

No hay `pyproject.toml`, ni `setup.cfg`, ni `tox.ini`, ni ningún otro `pytest.ini` en el repo
(`find` sobre todo el árbol: sólo aparecen `backend/pytest.ini` y `backend/tests/conftest.py`) `[V]`.

Los comandos están documentados en `MIGRACION_POSTGRES.md:2265-2285` `[V]`:

```bash
# SQLite (baseline)
cd backend && python3 -m pytest tests -q

# Postgres
cd backend && DATABASE_URL="$(cat ../../pg_uri.txt)" python3 -m pytest tests -q --timeout=20

# relojes apretados (CI / máquina dedicada)
RENDI_TEST_IDLE_TX_S=3 RENDI_TEST_LOCK_S=7 python3 -m pytest tests -q --timeout=10
```

**La misma suite corre contra los dos motores.** El que decide es `main.USANDO_PG`, y el
`conftest` bifurca el aislamiento según eso (`backend/tests/conftest.py:324-346`) `[V]`.

#### 1.2 ⚠️ Lo que `pytest` a secas colecta y no debería

El propio `pytest.ini` es, en su mayor parte, un comentario de 28 líneas explicando el
problema que resuelve (`backend/pytest.ini:1-28`) `[V]`. Resumido y verificado:

Hay **tres archivos `test_*.py` en `backend/scripts/` que NO son tests**, son scripts para
correr a mano `[V]`:

| Archivo | Líneas | `def test_` | Qué pasa si pytest lo colecta |
|---|---|---|---|
| `backend/scripts/test_emails.py` | 73 | 0 | **A import-time hace `load_dotenv(backend/.env, override=True)`** (`backend/scripts/test_emails.py:22-23`). Con sólo *colectarlo*, el `.env` real pisa el entorno de toda la corrida. El envío de 3 mails reales por Resend está bajo `if __name__ == "__main__"` (`:71-72`), así que la colección no manda mail — pero sí pisa credenciales. `[V]` |
| `backend/scripts/test_bot_profile_boundaries.py` | 2.062 | 40 | Su helper `fail()` hace `sys.exit(1)` (`:33-35`) — mata el proceso de pytest. `[V]` |
| `backend/scripts/test_proration_edge_cases.py` | 335 | 7 | Escenarios de proration que se corren con `python -m scripts.test_proration_edge_cases`. `[V]` |

Son **47 pseudo-tests**. `pytest.ini` los tapa con las dos líneas (`testpaths` para la
invocación sin argumentos, `norecursedirs` para la que sí lleva argumentos) `[V]`.

**🔴 El agujero que queda: `pytest.ini` vive en `backend/`, no en la raíz.**
`pytest` resuelve su `rootdir`/inifile **hacia arriba** desde los argumentos, nunca hacia abajo.
O sea: `cd /repo && pytest` no encuentra `backend/pytest.ini`, corre sin `testpaths` ni
`norecursedirs`, y vuelve a colectar `backend/scripts/test_*.py` — incluido el que hace
`load_dotenv(override=True)` con el `.env` de producción. `[I]` — inferido de que (a) el ini
está en `backend/` y no hay ninguno en la raíz `[V]`, y (b) el algoritmo de rootdir de pytest
busca hacia arriba. **No lo verifiqué corriendo pytest** (regla read-only). Es la clase de cosa
que cuesta 3 líneas cerrar: un `pytest.ini`/`pyproject.toml` en la raíz con el mismo
`norecursedirs`.

#### 1.3 Frontend — el comando exacto

`frontend/package.json:10-11` `[V]`:

```json
"test": "vitest run",
"test:watch": "vitest"
```

O sea: `cd frontend && npm test`. No hay `vitest.config.js` separado — la config vive dentro
de `frontend/vite.config.js:68-70` `[V]`:

```js
test: {
  environment: 'node',
},
```

**Consecuencias verificadas de `environment: 'node'`:**
- No hay `jsdom`. No hay `@testing-library/*` en `devDependencies` (`frontend/package.json:21-28`) `[V]`.
- **Cero tests de render de componentes React en todo el repo.** Los tres archivos que
  parecerían serlo son, en realidad, tests de funciones puras exportadas al lado del componente:
  - `frontend/src/contexts/CurrencyContext.test.jsx:1-18` lo dice explícito: *"Los helpers
    `fromUsd` y `fromArs` son funciones puras — no requieren montar componentes React"* `[V]`.
  - `frontend/src/hooks/useFxHistory.test.js:3`: *"El hook React `useFxHistory` no se testea acá
    (requiere @testing-library)"* `[V]`.
  - `frontend/src/utils/shareCard.test.js:2` y `frontend/src/utils/valuation.test.js:988`
    dicen lo mismo para Canvas y para el entorno sin jsdom `[V]`.

No hay archivo de setup (`setupTests.*` no existe) `[V]`.

#### 1.4 CI

**No encontrado.** `find` sobre todo el árbol (excluyendo `node_modules`) por `.github/`,
`.gitlab-ci.yml`, `.circleci/`, `Jenkinsfile`, `.travis.yml`, `azure-pipelines*`, `*.yml`,
`*.yaml`: **cero resultados** `[V]`.

Los dos pipelines de deploy que sí existen **no corren tests**:
- `railway.toml` + `nixpacks.toml`: `install` = `pip install -r backend/requirements.txt`,
  `start` = `uvicorn main:app`. Ni una línea de pytest `[V]`.
- `frontend/vercel.json:2`: `"buildCommand": "npm run build"`. No `npm test` `[V]`.

O sea: **nada bloquea un deploy con la suite en rojo.** El propio backlog del proyecto lo
tiene anotado desde mayo: `AUDIT_REPORT_2026-05-25.md:329` — *"GitHub Actions con pytest +
vitest gating"*, Sprint 5, sin hacer `[V]`.

#### 1.5 Dependencias de test: no declaradas

`backend/requirements.txt` **no incluye `pytest`, `pytest-timeout`, `numpy`, `pandas`,
`pgserver` ni `openpyxl` para test** — y **no existe `requirements-dev.txt`** (`ls
backend/requirements*` devuelve un solo archivo) `[V]`.

Esto está *reconocido en el código*: `backend/tests/test_dependencias_declaradas.py:55-58`
dice literalmente *"⚠️ Que no haya `requirements-dev.txt` es un hueco real — quien clone el
repo no sabe qué instalar para correr la suite"* `[V]`. Ese test vigila lo inverso (que
producción no importe algo no declarado) y excluye a propósito `tests/` y `scripts/test_`
(`:59`) `[V]`.

Caso concreto de la consecuencia: el comando documentado usa `--timeout=20`, que es de
**`pytest-timeout`**, plugin que nadie declara. Si no está instalado, `pytest_configure` hace
`config.getoption("timeout", None)` → `None` (`backend/tests/conftest.py:206-213`) y la
validación del orden de relojes **degrada en silencio** a comprobar sólo `idle < lock`, sin
el tercer reloj `[V]`.

---

### 2. Aislamiento de la base — el `conftest.py`

`backend/tests/conftest.py` tiene **423 líneas, de las cuales la enorme mayoría son
comentario forense**. Es, con diferencia, el archivo mejor documentado del repo. Lo que hace,
verificado:

| Mecanismo | Dónde | Qué hace |
|---|---|---|
| `DB_PATH` por defecto a un tempfile | `conftest.py:23-34` | `main.py` lee `DB_PATH` a import-time y por defecto apuntaba a **`backend/trading.db`, la DB de desarrollo real**. 24 de 41 archivos no lo seteaban → escribían cuentas `@rendi.test` en la base real. Ahora el default es un temp con `atexit` que lo borra. `[V]` |
| Una base **por módulo** (SQLite) | `conftest.py:324-346`, fixture `_db_por_modulo(autouse=True, scope="module")` | Crea un tempfile por módulo, **reapunta `main.DB_PATH`** (no sólo el env var, que main ya no relee), corre `main.init_db()`, y al terminar borra `.db`/`-wal`/`-shm`. `[V]` |
| Un **esquema** por módulo (Postgres) | `conftest.py:252-291` | `DROP/CREATE SCHEMA "t<pid>_<modulo>"`, `search_path` sin `public` de respaldo, y mata las conexiones de *su propia* corrida vía `application_name = rendi_suite_<pid>` (`:229`). `[V]` |
| Barrido de esquemas huérfanos | `conftest.py:293-321` | Al arrancar dropea `t<pid>_…` de pids que ya no viven (`os.kill(pid, 0)`). `[V]` |
| Tres relojes con orden validado | `conftest.py:147-213` | `idle_in_transaction (6s) < lock_timeout (12s) < --timeout de pytest (20s)`. `pytest_configure` levanta `pytest.UsageError` si el orden se rompe — **la suite no arranca mal configurada**. `[V]` |
| Apagar mantenimiento | `conftest.py:145` | `os.environ.setdefault("RENDI_MANTENIMIENTO", "0")`. Sin esto, con `DATABASE_URL` puesta, la app levanta cerrada y **~460 tests dan 503**. `[V]` |

**El aislamiento es por MÓDULO, no por test.** Dentro de un archivo, los tests comparten base
y se pisan si no limpian. Por eso el patrón dominante en la suite es un `setUp` que hace
`DELETE FROM users/brokers/positions/...` a mano (ej. `test_fx_capital.py:28-38`,
`test_reconstruccion_e2e.py:32-39`) `[V]`. Hay al menos un archivo que **depende del orden
alfabético de sus tests** para funcionar: `test_wallbit.py` los numera
`test_1_initial_sync…` / `test_2_resync_is_idempotent` (`:112`, `:131`) `[V]`.

#### 2.1 Andamio muerto: 64 archivos siguen con el patrón viejo

**65 archivos** hacen `os.environ["DB_PATH"] = <tempfile>` a nivel de módulo (uno es el
propio `conftest.py`) `[V]`. Ejemplo canónico: `test_events.py:24-26`, `test_wallbit.py:29-31`.

Ese patrón **ya no hace nada**: es exactamente el que el docstring del conftest declara
inútil (`conftest.py:37-50` — *"el PRIMER archivo que hace `import main` fija la base para
todo el proceso: los otros 57 setean su temp y no tiene ningún efecto"*) `[V]`.

Y **los 64 usan `NamedTemporaryFile(delete=False)` sin `atexit` ni `os.unlink`** `[V]`
(verificado: de los 64, cero tienen cleanup). O sea: **cada corrida completa de la suite deja
64 archivos `.db` huérfanos en `/tmp`**. No rompe nada, pero es basura acumulativa y ruido
que hace difícil leer el archivo.

---

### 3. La red de fallas conocidas

`backend/tests/conftest.py:348-423` implementa un guard propio: compara el **conjunto de
nombres** de tests fallidos contra `backend/tests/fallas_conocidas.txt` `[V]`.

- Grita en rojo por las **NUEVAS** (`:406-417`).
- Avisa en verde por las que **ya no fallan** pero siguen listadas (`:418-423`) — y sólo si
  ese test *realmente corrió* (`:399`), para que un subconjunto no dé falsos "arreglada".
- **No toca `exitstatus`** (`:416`) — pytest ya sale ≠ 0 solo.

`fallas_conocidas.txt` tiene **26 entradas**, generado el 2026-08-28 (`:2`) `[V]`. Verifiqué
que **las 26 siguen existiendo** como archivo/clase/método en el árbol actual — ninguna quedó
huérfana `[V]`.

Distribución de las 26:

| Archivo | Fallas conocidas | Pinta de |
|---|---|---|
| `tests/test_events.py` | 9 (`EventsPortfolioTest` ×4, `PopularEventsTest` ×5) | El archivo dice que mockea yfinance (`test_events.py:3`), así que **no** es red — el motivo real no está escrito en ningún lado `[I]` |
| `tests/test_news.py` | 7 | idem `[I]` |
| `tests/test_billing.py` | 3 (subscribe ×2, cancel ×1) | **billing de verdad: crear y cancelar suscripción** |
| `tests/test_bond_conduit.py` | 3 (amortización de bonos) | motor de cálculo |
| `tests/test_importer.py` | 2 (`reimport_after_revert_does_not_duplicate`, aliases) | importación |
| `tests/test_billing_lifecycle.py` | 1 (el cron diario, "corre los 3 pasos") | billing |
| `tests/test_cedear_usd_price.py` | 1 | valuación |
| `tests/test_backfill_recompute.py` | 1 | backfill |

**Lo que me preocupa de esta lista:** el archivo dice explícitamente *"ESTO NO ES UNA LISTA DE
PERDÓN"* (`:4`), pero **6 de las 26 son de billing** — `test_subscribe_creates_preapproval_and_saves_to_db`,
`test_subscribe_reuses_pending_subscription`, `test_cancel_marks_subscription_cancelled`,
`test_runs_all_three_steps_and_returns_counts` `[V]`. Son los caminos por donde entra y sale
la plata, y llevan en rojo declarado desde el 28/08. Sin CI, nadie los ve pasar de largo.

---

### 4. Inventario backend por subsistema

Agrupación **mía** `[I]` (por nombre de archivo y docstring; un archivo cae en un solo grupo).
Los conteos de tests son `grep -cE "^\s*def test_"` `[V]`.

| Subsistema | Archivos | `def test_` |
|---|---:|---:|
| Importación (parsers + pipeline + tenencia + reconciliación) | 61 | ~968 |
| Reporting / TWR / benchmark / snapshots / insights | 55 | ~902 |
| Cálculo (FIFO, FX, bonos, valuación, splits, futuros) | 54 | ~523 |
| IA | 12 | ~360 |
| Asesor | 3 | ~301 |
| Billing / trial / cuota | 15 | ~252 |
| Infra (Postgres, shim, conexiones, backup, meta-suite) | 19 | ~213 |
| Auth / seguridad / admin / borrado | 16 | ~192 |
| Sin clasificar | 2 | 9 |

#### 4.1 Importación

| Archivo | Qué cubre | Tests |
|---|---|---:|
| `backend/tests/test_importer.py` | El pipeline de import entero (parsers, normalizer, validator, persister, revert, seed state, routing de moneda) — **el archivo más grande de la suite** | 271 |
| `backend/tests/test_balanz_movimientos.py` | Export de Movimientos de Balanz (el libro de caja) | 42 |
| `backend/tests/test_bullmarket.py` | Parser Bull Market + lectura de `.xlsx` (xlsx sintético en memoria) | 40 |
| `backend/tests/test_tenencia.py` | Parser de la Tenencia valorizada de Bull Market (texto de PDF) | 31 |
| `backend/tests/test_inviu.py` | Parser inviu (Reporte de cuenta corriente) | 24 |
| `backend/tests/test_cocos_optypes.py` | Tipos de operación de Cocos que antes se dropeaban | 22 |
| `backend/tests/test_balanz.py` | Balanz "Resultados" — **19 tests, la mayoría `@unittest.skip`** (ver §9) | 19 |
| `backend/tests/test_tenencia_tickers.py` | Canonicalización de tickers de la foto | 16 |
| `backend/tests/test_ieb.py` / `test_ieb_labels.py` / `test_ieb_completeness.py` / `test_ieb_portfolio.py` | Parser IEB: códigos, etiquetas largas del export real, guards de completitud, portafolio | 15 / 12 / 10 / 3 |
| `backend/tests/test_ppi.py` | Export de Movimientos de PPI | 15 |
| `backend/tests/test_tenencia_override_all.py` | Modo OVERRIDE de la foto para PPI/Cocos/Bull Market | 14 |
| `backend/tests/test_miles_ambiguo.py` | Separador de miles es-AR ("150.000" ≠ 150,0) | 14 |
| `backend/tests/test_balanz_tenencia.py` | Foto de tenencia de Balanz (Resumen PDF) | 14 |
| `backend/tests/test_rebuild_balanz_tenencia_e2e.py` | E2E foto Balanz en OVERRIDE sobre el historial | 14 |
| `backend/tests/test_conducto_no_bonos.py` | Conducto MEP cross-día con acciones/CEDEARs | 14 |
| `backend/tests/test_normalizer_triangle.py` | Reconciliar cantidad×precio=monto (canilla del bug per-100) | 12 |
| `backend/tests/test_fci_import_mapping.py` | Valuación live de FCI propietarios importados | 12 |
| `backend/tests/test_tenencia_redondeo.py` | El redondeo de la foto no es un veredicto | 12 |
| `backend/tests/test_split_corporate_lote.py` | Split informado como lote en Movimientos | 13 |
| `backend/tests/test_iol.py` | Parser IOL + lectura de tablas HTML (`.xls`) | 61 |
| `backend/tests/test_iol_tenencia.py` | Resumen de Cuenta de IOL (PDF) | 10 |
| `backend/tests/test_invariantes.py` | Chequeos de invariantes post-import | 18 |
| `backend/tests/test_ledger_replay_status.py` | El replay sólo cuenta batches CONFIRMADOS | 9 |
| `backend/tests/test_cocos_tenencia.py`, `test_binance_transaction.py`, `test_balanz_internacional.py`, `test_reconcile_e2e.py`, `test_proyeccion.py`, `test_sections.py`, `test_tenencia_*` (8 archivos), `test_split_vs_foto.py`, `test_split_ars_gate.py`, `test_format_base_currency.py`, `test_fci_*` (3), `test_dates_one_digit_day.py`, `test_reimport_dedup.py`, `test_import_tc_compra.py`, `test_import_confirm_lock.py`, `test_comision_implausible.py`, `test_rebuild_ppi_e2e.py`, `test_rebuild_bullmarket_e2e.py`, `test_over_gate_asesor.py`, `test_reconstruccion_e2e.py`, `test_seed_fx_hoy.py`, `test_tickers_cd*.py` | resto | 3–18 c/u |

#### 4.2 Cálculo (motor)

| Archivo | Qué cubre | Tests |
|---|---|---:|
| `backend/tests/test_delete_operation_cascade.py` | Borrado de operación con cascada TOTAL | 45 |
| `backend/tests/test_bonds.py` | `POST /api/bonds/cashflow` — cupón / amortización | 43 |
| `backend/tests/test_fx_migrate_gate.py` | El gate server-side del migrador FX **frena**, no informa | 34 |
| `backend/tests/test_bond_unit_normalization.py` | Costo per-100 → per-1 | 21 |
| `backend/tests/test_futuros_abiertos.py` / `test_futuros_manual.py` / `test_futuros_audit.py` | Futuros abiertos, carga manual, audit | 19 / 13 / 9 |
| `backend/tests/test_fx_for_date.py` | El TC de cada operación sale de su FECHA | 17 |
| `backend/tests/test_monto_venta_ars.py` | El "Monto" de una venta en pesos no puede figurar como USD | 16 |
| `backend/tests/test_scale_guard.py` | Guard de escala en el MOTOR (persister + rebuild) | 16 |
| `backend/tests/test_bond_amortization.py` / `test_bond_amort_capital_return.py` / `test_bond_skips.py` / `test_bond_indices.py` / `test_bond_unit_convention.py` / `test_bond_conduit.py` | Sweep de amortización, devolución de capital, inbox de cobranzas, índices CER/UVA/A3500, convención de unidad, conductos | 15 / 11 / 11 / 10 / 8 / 7 |
| `backend/tests/test_diagnose_sell_fx.py` | Clasificador de ventas del diagnóstico admin | 14 |
| `backend/tests/test_broker_value_usd.py` | `snapshots_job.compute_broker_value_usd` | 13 |
| `backend/tests/test_letra_maturity.py` | Cierre de letras/LECAPs al vencer | 13 |
| `backend/tests/test_realized_pnl_cupon.py` | `operations.pnl_usd` no siempre está en USD — los 4 lectores | 13 |
| `backend/tests/test_crypto_premium.py` / `test_crypto_ars_price.py` | Premium dólar-cripto, cripto en broker ARS | 12 / 8 |
| `backend/tests/test_xbroker_mep_netting.py` | Neteo cross-broker del par padre ↔ `· USD` | 11 |
| `backend/tests/test_position_group_edit.py` | Edición a nivel GRUPO de posición multi-lote | 11 |
| `backend/tests/test_fx_gross_usd.py` | Una conversión no puede figurar ×1400 en Movimientos | 10 |
| `backend/tests/test_fifo_pool_unico.py` | Banco de aceptación del FIFO cross-currency | 8 |
| `backend/tests/test_rebuild_fifo.py` / `test_rebuild_fifo_edge.py` | Rebuild global de FIFO + casos borde adversariales | 6 / 6 |
| `backend/tests/test_currency_lots.py` | Lote = (broker, asset, currency) | 6 |
| `backend/tests/test_dolar_medio.py` | El dólar de valuación es (compra+venta)/2 | 6 |
| `backend/tests/test_mep_fantasma.py` | El MEP no deja activos fantasma (import → rebuild → cartera) | 5 |
| `backend/tests/test_orden_filas_pool.py` / `test_orden_mismodia.py` | ¿El orden de las filas cambia la plata? | 3 / 2 |
| `backend/tests/test_fx_capital.py` | Conversión ARS→USD corrige el Capital Aportado | 2 |

#### 4.3 Reporting / TWR / benchmark / snapshots

| Archivo | Qué cubre | Tests |
|---|---|---:|
| `backend/tests/test_behavioral.py` | Behavioral insights con fixtures de casos conocidos | 63 |
| `backend/tests/test_news.py` | Feature de noticias (**7 de sus tests están en `fallas_conocidas`**) | 54 |
| `backend/tests/test_benchmark_diario.py` | Benchmark por FECHA, índice publicado por punto, cota de cordura | 49 |
| `backend/tests/test_reporting.py` | Módulo `reporting/` | 41 |
| `backend/tests/test_snapshots_job.py` | Job de snapshots diarios (funciones puras de valuación) | 40 |
| `backend/tests/test_wrapped.py` | `backend/wrapped.py` | 33 |
| `backend/tests/test_audit_ronda11.py` / `ronda2` / `ronda10` / `ronda9` / `ronda3` / `ronda7` / `ronda5` / `bloqueantes` / `ronda4` | Las 9 rondas del audit de reportes/TWR | 28/26/24/15/14/14/12/19/7 |
| `backend/tests/test_reportes_broker_par.py` | El par padre ↔ `· USD` es UNA cuenta en Reportes | 25 |
| `backend/tests/test_home.py` | Módulo `home/` | 25 |
| `backend/tests/test_events.py` | `/api/events/portfolio` (**9 en `fallas_conocidas`**) | 21 |
| `backend/tests/test_goals_diagnostic.py` | `goals_diagnostic.py` (puro, sin endpoint) | 23 |
| `backend/tests/test_backfill_historical_mtm.py` | Backfill de valuación histórica a mercado | 19 |
| `backend/tests/test_reports_variaciones_f4.py` | Motor de variaciones (Fase 4 del audit) | 19 |
| `backend/tests/test_alerts.py` | Alertas: gating por plan, edge-trigger, cooldown (**motor, no endpoint**) | 19 |
| `backend/tests/test_fundamentals_metrics_detail.py` / `test_fundamentals_scoring.py` | Builder puro de métricas + scoring | 19 / 9 |
| `backend/tests/test_twr_serie_medible.py` | `twr.serie_medible` / `twr.curva_indexada` | 18 |
| `backend/tests/test_pnl_crudo_otros_lectores.py` / `test_pnl_crudo_csv_y_builders.py` | Los lectores de `pnl_usd` crudo | 14 / 7 |
| `backend/tests/test_export_csv.py` | `/api/export/*.csv` — gate Pro + formato | 13 |
| `backend/tests/test_modo_certero_estimado.py` | El switch CERTERO/ESTIMADO y la cobertura | 12 |
| `backend/tests/test_repair_user_history.py` / `test_repair_comisiones.py` | Repair de histórico y de comisiones falsas | 12 / 12 |
| `backend/tests/test_backfill_recompute.py` / `test_backfill_tope_cordura.py` / `test_backfill_cost_guards.py` / `test_backfill_currency_fix.py` | Backfills + sus guards | 13/11/8/6 |
| `backend/tests/test_performance_endpoint.py`, `test_borde_de_cierre.py`, `test_ba_nan_bar.py`, `test_corrupt_snapshot_detector.py`, `test_clamp_pico.py`, `test_consumidores_base_mercado.py`, `test_reportes_base_mercado.py`, `test_cagr_snapshots.py`, `test_fase2_toggle.py`, `test_cota_puntas_reportes.py`, `test_reconstruccion_e2e.py`, `test_dashboard_global_recalc.py`, `test_contrato_clasificacion.py`, `test_reports_live_value_month.py` | resto | 2–10 c/u |

#### 4.4 Billing / trial / cuota

| Archivo | Qué cubre | Tests |
|---|---|---:|
| `backend/tests/test_billing_trial.py` | Free trial 15 días (7 Pro + 8 Plus encadenados) | 45 |
| `backend/tests/test_ai_quota.py` | `ai/quota.py` — cap semanal + tiers + reset | 35 |
| `backend/tests/test_trial_cierre.py` | Cierre del trial, tope mensual, largo de la etapa Pro | 26 |
| `backend/tests/test_billing_trial_anchor_null.py` | Los 3 caminos con `credit_anchor_plan` NULL | 22 |
| `backend/tests/test_pro_upsell.py` | Probar Pro sin dejar el Plus que ya se paga | 22 |
| `backend/tests/test_plan_change_email.py` | Email al admin en cada cambio de plan | 19 |
| `backend/tests/test_trial_funnel_smoke.py` | Smoke del embudo del trial (población de 90 días) | 17 |
| `backend/tests/test_billing_trial_paga.py` | El usuario en prueba gratis que PAGA | 15 |
| `backend/tests/test_grant_comp_advisor.py` | Regalar el Plan Asesor desde admin | 13 |
| `backend/tests/test_quota_window_corte.py` | La ventana de cuota y los cambios de plan | 13 |
| `backend/tests/test_billing.py` | Endpoints de billing sin tocar la API de MP (**3 en `fallas_conocidas`**) | 12 |
| `backend/tests/test_billing_lifecycle.py` | `billing/subscriptions.py` — cron diario (**1 en `fallas_conocidas`**) | 11 |
| `backend/tests/test_credit_realtime_gating.py` | `quota.get_tier` corta el acceso pago en tiempo real | 11 |
| `backend/tests/test_trial_invite_campaign.py` | Campaña por tandas | 11 |
| `backend/tests/test_billing_emails.py` / `test_billing_cancel_resiliente.py` / `test_plan_events.py` | 5 emails transaccionales / cancelar resiliente / `/api/plan/track` | 9 / 6 / 6 |

#### 4.5 Asesor

Sólo 3 archivos, pero **301 tests** — es la concentración más alta del repo `[V]`:

| Archivo | Qué cubre | Tests |
|---|---|---:|
| `backend/tests/test_advisor_plan.py` | Plan Asesor F0–F2: **`get_effective_user`**, contexto de cliente, TWR, data-health, grupos, group-op, informes, radar, brief | 216 |
| `backend/tests/test_advisor_composition.py` | `GET /api/advisor/book/composition` | 79 |
| `backend/tests/test_advisor_report_revoke.py` | Cortar el link público de un informe | 13 |

Más, fuera de ese grupo por nombre: `test_over_gate_asesor.py` (8), `test_tenencia_gate_asesor.py` (6),
`test_ai_book_composition.py` (18), `test_advisor_schema_migration.py` (6) `[V]`.

**Cobertura de rutas del asesor:** de las 28 rutas `@app.*("/api/advisor…")` únicas, **26 aparecen
literalmente en algún test**; las 2 que no: `/api/advisor/alerts/events/seen` y
`/api/advisor/groups/preview` `[V]`.

**El header de suplantación `X-Rendi-Client-Id`** — el mecanismo por el que un asesor opera en
la cuenta de un cliente — aparece en sólo **4 archivos**: `test_advisor_plan.py`,
`test_advisor_composition.py`, `test_over_gate_asesor.py`, `test_tenencia_gate_asesor.py` `[V]`.

#### 4.6 IA

| Archivo | Qué cubre | Tests |
|---|---|---:|
| `backend/tests/test_ai_register_trade.py` | `register_trade` / `undo_last_trade` — el **write-path** conversacional del Coach | 125 |
| `backend/tests/test_ai_builders_phase2.py` | Los 6 builders de Phase 2 (Monthly + Position + Goals) | 53 |
| `backend/tests/test_ai_builders_integration.py` | Smoke de TODOS los builders **contra `backend/trading.db` real** (ver §6.4) | 26 |
| `backend/tests/test_ai_cache.py` / `test_ai_quota.py` / `test_ai_plan.py` / `test_ai_prompts.py` | `ai/cache.py`, `ai/quota.py`, `ai/plan.py`, `ai/prompts.py` | 19 / 35 / 17 / 17 |
| `backend/tests/test_ai_book_composition.py`, `test_ai_chat_benchmarks.py`, `test_ai_tools_quickwins.py`, `test_ai_distribution.py`, `test_ai_chat_snapshot_valuation.py`, `test_ai_final_fixes.py`, `test_ai_tool_market_news.py`, `test_ai_snapshot_hardening.py`, `test_ai_profile_crosses.py`, `test_ai_insights_summary.py` | resto | 7–18 c/u |

El cliente de Anthropic siempre está mockeado (`patch.object(main, "_get_anthropic_client", …)`,
`test_ai_register_trade.py:532`, `:555`, `:1599`, `:1626`) `[V]`. **No hay ningún test que
llame al LLM real** `[V]`.

#### 4.7 Auth / seguridad / admin / borrado

| Archivo | Qué cubre | Tests |
|---|---|---:|
| `backend/tests/test_security_fixes_2026_05_31.py` | Fixes de seguridad del 31/05 — incluye `rebill.verify_webhook_auth` (6 casos, `:218-273`) | 31 |
| `backend/tests/test_client_ip_xff.py` | De qué entrada de `X-Forwarded-For` sale la IP | 17 |
| `backend/tests/test_mantenimiento.py` | Modo mantenimiento cierra al público, deja pasar al operador | 15 |
| `backend/tests/test_admin_broadcast.py` / `test_admin_user_search.py` | Broadcast de email admin / buscar usuarios | 14 / 10 |
| `backend/tests/test_email_verification.py` / `test_password_reset.py` / `test_email_guard.py` | Verificación de email, reset con magic link, guarda anti-envío | 11 / 8 / 5 |
| `backend/tests/test_reset_data.py` / `test_reset_chunked.py` | "Empezar de cero" y que no tome el lock de punta a punta | 9 / 4 |
| `backend/tests/test_broker_rename.py` / `test_broker_delete_prod_schema.py` | Cascade de rename / borrar broker padre contra schema real | 9 / 3 |
| `backend/tests/test_config_fx_version.py` / `test_verificacion_no_es_opt_in.py` / `test_500_logging.py` / `test_delete_account.py` | resto | 6 / 6 / 4 / 1 |

**La guarda de emails funciona y está testeada**: `billing/emails._send` corta bajo pytest y
hacia dominios reservados, verificado incluso con `httpx.post` mockeado
(`test_email_guard.py:33-45`) `[V]`. El motivo está escrito: *"la suite mandaba alertas de
'nuevo usuario' REALES al inbox del fundador"* (`test_email_guard.py:3-6`) `[V]`.

#### 4.8 Infra / meta-suite

Un bloque entero de tests que testean **la suite y la migración**, no el producto `[V]`:

| Archivo | Qué cubre | Tests |
|---|---|---:|
| `backend/tests/test_verificar_copia.py` | ¿La verificación de la copia sabe detectar una copia rota? | 44 |
| `backend/tests/test_pgshim.py` + `test_pgshim_pk_cache.py` + `test_pgshim_ambiguas.py` + `test_pgshim_no_pierde_escrituras.py` | El traductor SQLite→Postgres | 32 / 14 / 10 / 2 |
| `backend/tests/test_copiar_a_postgres.py` | El copiador copia todo y falla cuando debe | 26 |
| `backend/tests/test_relojes_del_conftest.py` | **El orden de los 3 relojes del `conftest`** | 13 |
| `backend/tests/test_backup_db.py` | Script de backup | 11 |
| `backend/tests/test_aislamiento_entre_corridas.py` | Dos corridas simultáneas no se pisan | 6 |
| `backend/tests/test_esquema_pg_reaplicable.py` / `test_dependencias_declaradas.py` / `test_conexiones_cerradas.py` / `test_conexiones_pg_ajustadas.py` / `test_ensayo_clon_solo_sqlite.py` / `test_escritores_solo_sqlite.py` / `test_endpoints_no_bloquean.py` / `test_db_lock_retry.py` / `test_conn_leak_write_lock.py` / `test_price_write_buffer.py` / `test_iol_lab.py` | resto | 3–8 c/u |

---

### 5. Inventario frontend

Comando: `cd frontend && npm test` → `vitest run`, entorno `node` `[V]`.

| Archivo | Qué cubre | `it(` |
|---|---|---:|
| `frontend/src/utils/valuation.test.js` | El motor de valuación del cliente (el más grande del front) | 217 |
| `frontend/src/utils/insightsModel.test.js` | Modelo de Insights | 99 |
| `frontend/src/utils/evolution.test.js` | Serie de evolución | 65 |
| `frontend/src/utils/diagnostics.test.js` | Diagnóstico adaptativo | 63 |
| `frontend/src/utils/bookComposition.test.js` | Composición del libro (asesor) | 62 |
| `frontend/src/hooks/useMonthlyData.test.js` | Hook de datos mensuales (lógica, no render) | 54 |
| `frontend/src/utils/assetClass.test.js` / `assetSector.test.js` | Clasificador único tipo/sector | 44 / 18 |
| `frontend/src/utils/bondPricing.test.js` / `bondSchedule.test.js` / `bondSchedulesAR.test.js` / `bondScheduleCER.test.js` / `bondCashflowFx.test.js` | Precio, cronograma, cronogramas AR, CER, FX de cupones | 43 / 43 / 19 / 10 / 19 |
| `frontend/src/utils/assetPnl.test.js` | P&L por activo | 39 |
| `frontend/src/contexts/CurrencyContext.test.jsx` | Helpers puros `fromUsd`/`fromArs`/formatters | 37 |
| `frontend/src/utils/upcomingEvents.test.js` | Próximos eventos | 40 |
| `frontend/src/utils/applyMtmToMonthly.test.js` (→ `insightsModel`) | MtM sobre mensual + capital neto aportado | 27 |
| `frontend/src/utils/pendingCashflows.test.js` | Cobranzas pendientes | 27 |
| `frontend/src/utils/benchmarkSim.test.js` | Simulación de benchmark | 23 |
| `frontend/src/hooks/useHistoricalMoney.test.js` | Plata histórica | 23 |
| `frontend/src/utils/shareCard.test.js` | Share card (Canvas queda fuera por falta de jsdom) | 22 |
| `frontend/src/utils/profileDashboard.test.js` | Dashboard de perfil | 20 |
| `frontend/src/utils/aiStructured.test.js` / `brokerAccounts.test.js` | Salida estructurada de IA / cuentas de broker | 19 / 19 |
| `frontend/src/utils/assetSector.test.js`, `tradeStats.test.js`, `fxPanel.test.js`, `diagnosticoTemplate.test.js`, `plan/TrialCta.test.js` | resto | 16–18 |
| `frontend/src/utils/apiRetry.test.js` (→ `gatewayRetry`) | Retry del gateway con jitter | 14 |
| `frontend/src/utils/monthlyReturnArs.test.js`, `diagnosticsRotation.test.js`, `valuationGuards.test.js`, `fx.test.js`, `hooks/useFxHistory.test.js` | resto | 12–14 |
| `frontend/src/utils/insightsMetrics.test.js`, `sections.test.js`, `sumRow.test.js`, `computeCagrSpan.test.js`, `fundamentalsCompare.test.js`, `bondScheduleCER.test.js` | resto | 10–11 |
| `frontend/src/__design__/design-contract.test.js` | **El contrato del sistema visual** (baseline ruta→conteo, falla si sube *y* si baja) | 9 |
| `frontend/src/utils/buildPriceSymbols.test.js`, `crypto.test.js`, `chatStream.test.js`, `gatewayMessage.test.js`, `stripMarkdown.test.js`, `currencyFormat.test.js`, `faltaTenencia.test.js`, `chatSession.test.js`, `errorMessage.test.js`, `distributionAi.test.js`, `useCurrencyChoice.test.js`, `tickers.test.js`, `AddPositionFlow.test.js`, `errorBoundaryStorage.test.js` | resto | 4–9 c/u |

**El `design-contract.test.js` merece mención aparte.** Es el guard de deuda visual: un mapa
ruta→conteo por categoría (`frontend/src/__design__/design-baseline.json`, 8.113 bytes) que el
test recorre iterando el árbol, no el JSON — *"una ruta ausente vale 0, así que un archivo nuevo
con 40 font-mono falla aunque nadie lo haya agregado"* (`design-contract.test.js:20-25`) `[V]`.
Falla tanto si sube como si baja, y el regenerador (`frontend/scripts/gen-design-baseline.mjs`)
avisa que correrlo para "arreglar" un SUBIÓ es desarmar el guard (`:8-11`) `[V]`.

#### 5.1 Cobertura frontend: qué queda afuera

- **154 componentes `.jsx`** y **48 páginas `.jsx`**: **cero tests de render** `[V]`.
- **14 hooks, 4 con test** (`useCurrencyChoice`, `useFxHistory`, `useHistoricalMoney`,
  `useMonthlyData`) — y ninguno testea el hook *como hook*, sólo sus funciones puras `[V]`.
  Sin test: `useAIAnalysis`, `useAlerts`, `useCountUp`, `useIsMobile`, `useLastVisit`,
  `usePfRollup`, `usePlanFeatures`, `usePullToRefresh`, `usePushNotifications`,
  `useReportsTimeline` `[V]`.
- **8 contexts, 1 con test parcial** (`CurrencyContext`, sólo helpers). Sin test:
  `AdvisorContext`, `AlertsContext`, **`AuthContext`**, `CoachDrawerContext`, `PrivacyContext`,
  `ThemeContext` `[V]`.
- **`frontend/src/utils/` sin test**: `analytics.js`, `autoUpdate.js`, `bondMeta.js`, `demo.js`,
  `insights.js`, `metaPixel.js`, `positionsDiscovered.js`, `profileAllocations.js`,
  `profileMatch.js`, `routePrefetch.js`, **`safeUrl.js`**, `support.js`, `track.js`,
  `watchlistEvents.js` `[V]`.

**`safeUrl.js` sin un solo test es el que más me llama la atención.** Son 52 líneas que
implementan (a) el bloqueo de `javascript:` / `data:` en hrefs que vienen del backend y de
feeds RSS, y (b) la **allowlist de hosts de pago** para `window.location.href` hacia Rebill
(`frontend/src/utils/safeUrl.js:19-52`) `[V]`. Lo consumen 4 archivos: `TopNewsCard.jsx`,
`home/NewsPreview.jsx`, `News.jsx` y `pages/Planes.jsx` `[V]`. Un typo en el `Set` de hosts o
un `return url` mal puesto no lo caza nadie.

#### 5.2 Skips frontend

Sólo **2** `it.todo` en todo el frontend, ambos en
`frontend/src/utils/bondSchedule.test.js:339-340` (AL30 step-up real, `amortSchedule` con
fechas no regulares) `[V]`. **Cero** `.skip`, cero `.only` `[V]`.

---

### 6. ⚠️ Tests que no atraviesan la ruta real

Esta es la sección importante. La ruta de producción del import es larga y **el 99 % de la
suite la reconstruye a mano, salteándose pasos**.

#### 6.1 La ruta real, medida

`POST /api/imports/confirm` → `main.import_confirm` (`backend/main.py:30738`). Después de la
transacción atómica que llama a `persist_batch` (`:30801`), corren **ocho post-procesos**, cada
uno en su propio `try/except` best-effort (`backend/main.py:30840-30960`) `[V]`:

| # | Paso | Línea |
|---|---|---|
| 1 | `rebuild_fifo_after_import` | `backend/main.py:30843` |
| 2 | `sweep_matured_letras` | `backend/main.py:30861` |
| 3 | `sweep_bond_amortizations` | `backend/main.py:30872` |
| 4 | `tag_bonds_from_data912` | `backend/main.py:30893` |
| 5 | `normalize_bond_units` | `backend/main.py:30905` |
| 6 | `normalize_usd_commissions` | `backend/main.py:30915` |
| 7 | **`_recalc_pnl_realized_from_ops`** | `backend/main.py:30930` |
| 8 | `_backfill_snapshots_from_monthly` | `backend/main.py:30940` |
| 9 | FCI `price_override` de la foto (va al final a propósito) | `backend/main.py:30952-30960` |

**Cuántos tests recorren eso entero:**

| Vía | Archivos | Tests |
|---|---|---:|
| HTTP real (`/api/imports/preview` → `/api/imports/confirm`) | `backend/tests/test_over_gate_asesor.py:94-101` | 8 |
| Llamada directa a `main.import_confirm(...)` | `backend/tests/test_rebuild_skip_bug.py:82-83` | 1 |
| **Total** | **2 archivos** | **9** |

Verificado: `grep -rn "main.import_confirm(" backend/tests/` devuelve **una sola línea**
(`test_rebuild_skip_bug.py:83`), y `/api/imports/confirm` como literal aparece sólo en
`test_over_gate_asesor.py` `[V]`.

Los otros **28 archivos** que llaman a `persist_batch` arman la cadena a mano y **cada uno
elige qué pasos poner**:

| Archivo | `persist_batch` | `rebuild_fifo_after_import` | `_recalc_pnl_realized_from_ops` |
|---|---:|---:|---:|
| `backend/tests/test_importer.py` | 46 | **0** | 16 |
| `backend/tests/test_fx_migrate.py` | 2 | 3 | 10 |
| `backend/tests/test_delete_operation_cascade.py` | 2 | 3 | 5 |
| `backend/tests/test_rebuild_fifo.py` | 1 | 6 | 6 |
| `backend/tests/test_backfill_recompute.py` | 2 | **0** | 1 |
| `backend/tests/test_bond_amortization.py` | 1 | **0** | 1 |
| `backend/tests/test_bond_conduit.py` | 1 | **0** | 2 |
| `backend/tests/test_cash_health_cash_broker.py` | 2 | **0** | 1 |
| `backend/tests/test_balanz.py` | 1 | **0** | **0** |
| `backend/tests/test_bond_amort_capital_return.py` | 1 | **0** | **0** |
| `backend/tests/test_fx_capital.py` | 1 | **0** | **0** |
| `backend/tests/test_iol.py` | 1 | **0** | **0** |

(el resto — `test_balanz_cedear_usd_e2e`, `test_binance_transaction`, `test_ieb_tenencia_override_e2e`,
`test_import_tc_compra`, `test_rebuild_*_e2e`, `test_reimport_dedup`, `test_scale_guard`,
`test_split_*`, `test_tenencia_override_all`, `test_xbroker_mep_netting` — sí encadena
persist + rebuild + recalc) `[V]`.

**Ningún archivo llama a los pasos 2 a 6 y 9 después de un `persist_batch`** — los sweeps de
vencimiento y amortización, el tagging por data912, las normalizaciones de unidad y comisión y
el `price_override` de FCI se testean **cada uno por separado**, nunca en la secuencia y el
orden en que producción los corre `[V]`. Como los 8 están en `try/except` que se tragan la
excepción, **si uno rompe, producción sigue de largo y ningún test lo nota**.

#### 6.2 🔴 El caso concreto: `test_fx_capital.py`

**`backend/tests/test_fx_capital.py:40-51`** — 2 tests, verde, y **afirma lo contrario de lo
que hace producción**:

```python
def _import(self, csv):
    conn = main.get_db()
    with conn:
        payload = pl.run_preview(conn, uid=self.uid, file_bytes=csv, ...)
    sid = payload['session_id']
    with conn:
        txs, raw = pl.load_session_for_confirm(conn, uid=self.uid, session_id=sid)
        ps.persist_batch(conn, uid=self.uid, batch_id=sid, txs=txs,
                         raw_row_ids_by_index=raw, helpers=_helpers())
    return conn
```

Termina en `persist_batch`. **No corre el rebuild ni el recalc.** Y lo que el test asserta es
justamente `monthly_entries.deposits − withdrawals == 1000` para el broker `global`
(`test_fx_capital.py:60-65`) `[V]`.

Pero `_recalc_pnl_realized_from_ops` — paso 7 de la ruta real — **reescribe `deposits` y
`withdrawals` desde `import_normalized_tx` filtrando
`operation_type IN ('DEPOSIT','WITHDRAW')`** (`backend/main.py:9414-9420` y `:9471-9476`) `[V]`.
Una `CONVERSION_ARS_USD` no es ninguno de los dos. O sea: **el número que el test fija en 1000
es el que el recalc pisa un paso después, en producción, en cada confirm.** El test es verde y
la app hace otra cosa.

Ese patrón ya está identificado en la memoria del proyecto ("Capital FX: el recalc pisaba el
fix" — el fix nunca corrió un día en prod), y **el código del test sigue exactamente igual en
`main` hoy** `[V]`.

#### 6.3 🔴 El helper de test al que le falta una pata

Producción arma el objeto de helpers con **siete** funciones
(`backend/main.py:29424-29433`) `[V]`:

```python
_import_helpers._adjust_broker_cash = _adjust_broker_cash
_import_helpers._adjust_cash = _adjust_cash
_import_helpers._update_monthly_pnl_realized = _update_monthly_pnl_realized
_import_helpers._update_monthly_flow = _update_monthly_flow
_import_helpers._repair_monthly_chain = _repair_monthly_chain
_import_helpers._ensure_usd_sibling = _ensure_usd_sibling
_import_helpers._recalc_pnl_realized_from_ops = _recalc_pnl_realized_from_ops   # ← la séptima
```

El helper de `backend/tests/test_importer.py:64-72` tiene **seis** — le falta exactamente esa `[V]`.

Y `revert_batch` la consume con `getattr(..., None)`
(`backend/importing/persister.py:1677-1679`) `[V]`:

```python
recalc_fn = getattr(helpers, "_recalc_pnl_realized_from_ops", None)
if recalc_fn:
    recalc_fn(conn, uid)
```

**Un helper sin ese atributo hace que el revert salte el self-heal en silencio.** No hay
error, no hay warning: el `if` simplemente no entra.

Conteo verificado: **26 archivos definen su propio `_helpers()`**; **11 le cablean el recalc**;
**15 no** `[V]`. Y de los que no, dos llaman a `revert_batch`:
`backend/tests/test_bond_amort_capital_return.py` y `backend/tests/test_iol.py` `[V]`.

En `test_importer.py` hay **24 usos de `revert_batch` en la suite**, 15 de ellos en ese archivo,
y **sólo uno** cablea el recalc a mano (`test_importer.py:1462`) `[V]`. Ese único test dice en
su docstring, textual (`test_importer.py:1450-1456`) `[V]`:

> *"Los tests de revert existentes NO lo agarran porque su `_helpers()` mock no incluye el recalc."*

O sea: **el proyecto ya diagnosticó el problema, escribió un test para ESE caso, y dejó los
otros 14 reverts corriendo con el helper incompleto.** Y para completar el cuadro, hay una
tercera convención en el mismo archivo: `test_importer.py:5615` pasa
`helpers=main` — el módulo entero, que sí tiene todo `[V]`. Tres convenciones distintas para
lo mismo, en un archivo.

#### 6.4 🔴 `test_reconstruccion_e2e.py`: E2E sólo en el nombre

Docstring (`backend/tests/test_reconstruccion_e2e.py:1-5`) `[V]`:

> *"La cadena completa: import → reconstrucción a mercado → serie medible."*

Lo que hace el `setUp` (`:47-61`) `[V]`: **`INSERT INTO import_batches`, `INSERT INTO
import_raw_rows`, `INSERT INTO import_normalized_tx` y `INSERT INTO monthly_entries` a mano.**
No hay parser, ni normalizer, ni validator, ni `persist_batch`, ni rebuild, ni recalc. La
"cadena completa" arranca **después** del import, con las filas ya escritas con la forma que el
test asume.

Si el persister empieza a escribir `import_normalized_tx` con otro `operation_type`, otra
moneda o sin `gross_amount`, este test sigue verde.

#### 6.5 Los agregados se siembran a mano en 45 archivos

**45 archivos de test hacen `INSERT INTO snapshots` o `INSERT INTO monthly_entries`
directamente** `[V]` — entre ellos todos los grandes de reporting: `test_twr_serie_medible.py`,
`test_reporting.py`, `test_reportes_base_mercado.py`, `test_reportes_broker_par.py`,
`test_performance_endpoint.py`, `test_modo_certero_estimado.py`, `test_fase2_toggle.py`,
`test_cota_puntas_reportes.py`, `test_contrato_clasificacion.py`, `test_export_csv.py`,
`test_proyeccion.py`, `test_corrupt_snapshot_detector.py` `[V]`.

Es legítimo como unit test. Pero significa que **el TWR, Reportes y el benchmark se validan
sobre datos que un humano escribió con la forma correcta**, no sobre los que produce el
pipeline. La costura "lo que el persister/recalc escribe" ↔ "lo que TWR lee" **no la cruza
ningún test**.

#### 6.6 🟡 26 tests que dependen de la cartera del founder

`backend/tests/test_ai_builders_integration.py` abre **`backend/trading.db` — la base de
desarrollo real** — con `sqlite3.connect`, exige `uid=2` con `is_admin=1`, y si no está,
`pytest.skip` (`:28-49`) `[V]`.

- Es **read-only** (verificado: cero `INSERT`/`UPDATE`/`DELETE`/`commit()` en el archivo) `[V]`.
  No corrompe nada.
- Pero **26 tests** cuyas aserciones son "este campo del packet no viene vacío para *esta*
  cuenta". En la máquina del founder pasan; en cualquier otra (o en un CI) **se saltean
  enteros**, y el docstring lo asume (`:19-20`) `[V]`.
- Además hay 5 `pytest.skip` internos más (`:310`, `:325`, `:355`, `:418`, `:483`) que se
  disparan si el admin no tiene posiciones / goals / trades cerrados `[V]`. Un test que se
  auto-saltea cuando el dato no está es un test que **no puede fallar por la razón que dice
  vigilar**.

#### 6.7 🟡 12 archivos testean la FORMA DEL CÓDIGO, no el comportamiento

`inspect.getsource(...)` + `assertIn`/`assertNotIn` sobre el texto fuente `[V]`:

| Archivo | Usos |
|---|---:|
| `backend/tests/test_tickers_cd.py` | 6 |
| `backend/tests/test_fx_migrate_gate.py` | 5 |
| `backend/tests/test_seed_fx_hoy.py` | 3 |
| `backend/tests/test_endpoints_no_bloquean.py` | 2 |
| `test_reconstruccion_e2e`, `test_fx_for_date`, `test_conducto_no_bonos`, `test_clamp_pico`, `test_billing_trial`, `test_audit_ronda5`, `test_audit_ronda4`, `test_advisor_composition` | 1 c/u |

Ejemplo (`backend/tests/test_tickers_cd.py:145-152`) `[V]`:

```python
src = inspect.getsource(iol._clean_ticker)
self.assertIn("strip_cd_suffix", src)
...
self.assertNotIn("_KNOWN_CD_TICKERS = {", src)
```

En este caso está **acompañado** de un test de comportamiento real
(`test_iol_produce_el_mismo_resultado`, `:154-157`) `[V]`, así que es un guard arquitectural
razonable. Lo anoto igual: un `assertIn` sobre texto fuente pasa a verde con un comentario y
falla con un rename inocuo. Vale como red anti-regresión estructural, **no** como cobertura.
`test_endpoints_no_bloquean.py:110-124` es el caso extremo: compara *posiciones de substring*
dentro del código de `run_preview` `[V]`.

#### 6.8 🟡 8 archivos importan los helpers de otro archivo de test

`from test_rebuild_fifo import _Base, _csv` `[V]`, en:
`test_diagnose_sell_fx_eje_s.py:42`, `test_entry_price_moneda.py:58`,
`test_fifo_pool_unico.py:35`, `test_fx_auto_migrate_import.py:32`, `test_mep_fantasma.py:25`,
`test_orden_filas_pool.py:39`, `test_orden_mismodia.py:41`,
`test_price_override_sobrevive.py:44`.

Es bueno que compartan el arnés (y `test_rebuild_fifo._helpers()` **sí** cablea el recalc,
`test_rebuild_fifo.py:47`) `[V]`. Pero acopla 8 módulos al orden de import de uno, y en un
`conftest` que aísla **por módulo** eso es exactamente donde aparecen los "pasan solos, fallan
juntos". Lo natural sería que `_Base`/`_csv` vivan en `conftest.py` o en un `tests/_arnes.py`.

---

### 7. Agujeros de cobertura concretos

#### 7.1 Rutas HTTP sin ninguna mención en tests

**108 de 231 paths únicos (47 %)** no aparecen literalmente en ningún archivo de test `[V]`.
Es una cota conservadora: un test que arme la URL con f-string no lo cuento. Los que más
importan:

**Billing / plata:**

| Ruta | Estado |
|---|---|
| **`/api/billing/rebill-webhook`** | 🔴 Sin ningún test funcional. Ver §7.2 |
| `/api/billing/sync` | sin test |
| `/api/billing/trial`, `/api/billing/trial/start`, `/api/billing/trial/pro-upsell` | sin test por ruta (la lógica sí se testea vía `billing/trial.py`) |

**Auth:**

| Ruta | Estado |
|---|---|
| **`/api/auth/change-password`** | 🔴 cero tests |
| `/api/auth/investor-profile` | cero tests |
| `/api/auth/logout` | cero tests |
| `/api/auth/claim/preview` | cero tests (`/api/auth/claim` sí) |
| `/api/auth/link-request/preview` | cero tests (`/respond` sí) |

(los que sí: `login` ×2, `register` ×2, `verify-email` ×2, `me`, `forgot-password`,
`reset-password`, `resend-verification`, `claim`, `link-request/respond`) `[V]`.

**Superficie de producto sin ninguna ruta testeada:**
`/api/alerts` + `/api/alerts/{alert_id}` + `/api/alerts/events/seen` (el motor sí, el endpoint
no), `/api/goals` + `/api/goals/{gid}` + `/api/goals/cagr` + `/api/goals/{gid}/diagnostic`,
`/api/plazos-fijos*` (5 rutas, incluidas `cobrar` y `renovar`), `/api/wallbit/*` (4 rutas),
`/api/push/*` (4), `/api/home/*` (4), `/api/positions/group*` (3), `/api/sections/*` (3),
`/api/ai/facts*`, `/api/ai/remember`, `/api/ai/analyze`, `/api/ai/topics`, `/api/ai/usage`,
`/api/behavioral/insights`, `/api/wrapped/{year}`, `/api/fundamentals/{ticker}`,
`/api/reports/period/{period_type}/{period_key}`, `/api/tickers/search`, `/api/conversions`,
`/api/benchmarks`, `/api/fx-rates`, `/api/dolar`, `/api/public/dolar`, `/api/stats/public`,
**33 rutas `/api/admin/*`** `[V]`.

Matiz honesto: varios de esos endpoints son cáscaras finas sobre módulos que **sí** están
testeados (`alerts_engine`, `goals_diagnostic`, `wrapped`, `behavioral`, `home`). Lo que **no**
cubre ningún test es la capa del endpoint: auth, `get_effective_user`, gating por plan,
serialización y códigos de error.

#### 7.2 🔴 El webhook de cobro de Rebill

`@app.post("/api/billing/rebill-webhook")` → `rebill_webhook`, `backend/main.py:26809`. Va
desde ahí hasta el siguiente decorador en `:27306` — **~495 líneas** que:
verifican la firma, activan el tier en `subscription.activated/created`, marcan cancelada en
`subscription.cancelled`, registran el pago en `payment.succeeded/subscription.renewed` y
flaguean `payment.failed` (`backend/main.py:26811-26822`) `[V]`.

**Cobertura:**

| Qué | Cobertura |
|---|---|
| `rebill.verify_webhook_auth` (HMAC / token de URL / fail-closed en prod) | ✅ 6 aserciones en `backend/tests/test_security_fixes_2026_05_31.py:218-273` |
| El handler `rebill_webhook` (activar tier, cancelar, registrar pago) | 🔴 **ningún test lo invoca**. Lo único que lo nombra es `backend/tests/test_endpoints_no_bloquean.py:75-81`, que sólo verifica que **no sea `async def`** |
| `billing/pricing.py` (todos los precios: `PRO_ARS_MONTHLY_TOTAL`, `PLUS_*`, `IVA_PCT`, `get_pricing`, `get_all_plans`) | 🔴 **cero archivos de test lo importan** |

El propio backlog del repo lo tiene escrito desde mayo: `AUDIT_REPORT_2026-05-25.md:338` —
*"Tests del módulo Rebill (proration, webhooks, cancelación)"* `[V]`. Sigue ahí.

Y el único lugar donde existen tests de proration es
`backend/scripts/test_proration_edge_cases.py` (7 escenarios) — que **`pytest.ini` excluye a
propósito** y sólo corre a mano `[V]`.

#### 7.3 Lo que SÍ está bien cubierto (para no pintar un cuadro falso)

| Área | Evidencia |
|---|---|
| **TWR** | `import twr` en **17 archivos**; `test_twr_serie_medible.py` (18), `test_benchmark_diario.py` (49), las 9 rondas de audit, `test_borde_de_cierre.py`, `test_fase2_toggle.py`, `test_modo_certero_estimado.py`, `test_cota_puntas_reportes.py` `[V]` |
| **FIFO** | 30 archivos lo tocan; `test_rebuild_fifo.py` + `test_rebuild_fifo_edge.py` (casos adversariales) + `test_fifo_pool_unico.py` ("banco de aceptación escrito ANTES del cambio") + `test_orden_filas_pool.py` / `test_orden_mismodia.py` (el desempate por fecha) `[V]` |
| **Autorización del asesor** | `test_advisor_plan.py` (216) cubre `get_effective_user` y el contexto de cliente; 26 de 28 rutas `/api/advisor/*` mencionadas; `test_over_gate_asesor.py` y `test_tenencia_gate_asesor.py` cubren el gate de aprobación con **control positivo explícito** (`test_over_gate_asesor.py:145-155`) `[V]` |
| **Cuota / trial / gating** | 15 archivos, ~252 tests, incluido un smoke de embudo con población de 90 días `[V]` |
| **Aislamiento y migración PG** | 19 archivos que testean la propia infraestructura, incluido `test_relojes_del_conftest.py` que testea el `conftest` `[V]` |

#### 7.4 Módulos backend sin ningún test que los importe

| Módulo | Archivos de test que lo importan | Nota |
|---|---:|---|
| `backend/advisor_twr.py` | **0** | Se llega por `/api/advisor/twr` y `/api/advisor/data-health` (`backend/main.py:33708`, `:33724`), y esas rutas sí las toca `test_advisor_plan.py:3187`, `:3195`, `:3310`, `:3328`. O sea: **4 llamadas HTTP** para las 3 funciones del módulo `[V]` |
| `backend/sim_import.py` | **0** | Es el simulador de import (`sim_import.py:67-70` hace persist + rebuild). Nada lo testea `[V]` |
| `backend/advisor_alerts.py`, `backend/advisor_groups.py`, `backend/analysis_prep.py`, `backend/flujos.py`, `backend/iol_api.py`, `backend/mantenimiento.py`, `backend/price_history.py`, `backend/pgsesion.py`, `backend/dberrors.py`, `backend/goals_diagnostic.py`, `backend/wallbit.py` | 1 c/u | `[V]` |

Y en `backend/importing/`: `cash_sim.py` y `preview.py` no los importa ningún test **directamente**,
pero sí se ejercitan vía `run_preview` (`backend/importing/pipeline.py:27`) — cobertura
indirecta real `[V]`.

#### 7.5 🟡 La capa PDF no se testea nunca

`backend/importing/excel.py` tiene tres extractores de formato binario. Dos están cubiertos
end-to-end, uno no `[V]`:

| Extractor | Test | Cómo |
|---|---|---|
| `.xlsx` (`xlsx_to_csv`, `is_xlsx`) | ✅ `backend/tests/test_bullmarket.py:26-59` | Construye un `.xlsx` sintético con `openpyxl` y pasa **los bytes** por `is_xlsx` → `xlsx_to_csv` → parser |
| `.xls` HTML (`is_html_table`, `html_table_to_csv`) | ✅ `backend/tests/test_iol.py:21`, `:41-73` | Arma el HTML y lo pasa por `to_csv_text` |
| **PDF (`is_pdf`, `pdf_to_text`)** | 🔴 **cero tests** | `grep -rn "pdf_to_text\|is_pdf" backend/tests/` → vacío |

Los tres parsers de foto en PDF (Bull Market, IOL Resumen, Balanz Resumen) se testean **desde
el texto ya extraído**: `backend/tests/test_tenencia.py:11-31` define un `SAMPLE` string a mano
y se lo da a `parse_bullmarket_tenencia(SAMPLE)` `[V]`. El propio archivo lo dice: *"Texto
sintético con la MISMA estructura del PDF real (no incluimos el PDF del usuario)"* `[V]`.

O sea: **si `pdfplumber` cambia el orden de columnas, mete un salto de línea distinto o falla
en un PDF con layout raro, ningún test se entera** — y esa capa es la que corre en producción
en `backend/main.py:29524-29525` y `:29763-29766` `[V]`. La decisión de no meter el PDF de un
usuario en el repo es correcta; falta un PDF sintético generado en el test.

---

### 8. Fixtures

`backend/tests/fixtures/` tiene **5 archivos, todos CSV, 4.238 bytes en total** `[V]`:

| Fixture | Bytes | Quién la usa |
|---|---:|---|
| `cocos_export.csv` | 1.569 | `test_importer.py:500` |
| `schwab_export.csv` | 1.709 | `test_importer.py:5636` |
| `generic_errors.csv` | 373 | `test_importer.py:1010` |
| `generic_basic.csv` | 298 | `test_importer.py:672`, `:970`, `:1550` |
| `ibkr_export.csv` | 289 | `test_importer.py:1604`, `:1611`, `:1679` |

**Las cinco las usa un solo archivo: `test_importer.py`** `[V]`. Todos los demás parsers
(Balanz, Balanz Movimientos, Balanz Internacional, IEB, IOL, PPI, inviu, Bull Market, Binance,
Binance Futures) embeben su input como string/bytes literal dentro del test `[V]`.

Eso no es malo per se (evita subir datos de usuarios), pero tiene dos costos verificables:
1. **El export real no queda pinneado.** El caso `test_ieb_labels.py` existe precisamente porque
   *"el export REAL de la web trae etiquetas largas (no códigos del demo)"* — la ficción del
   fixture inline había rechazado 305 de 305 filas `[V]`.
2. **Ningún fixture binario.** No hay ni un `.xlsx`, ni un `.xls` HTML, ni un `.pdf` en el repo `[V]`.

#### 8.1 ¿Alguna base real en riesgo?

| Riesgo | Estado |
|---|---|
| Escribir en `backend/trading.db` | **Cubierto.** `conftest.py:23-34` fuerza `DB_PATH` a un tempfile si nadie lo seteó, y `:324-346` da una base por módulo. `test_escritores_solo_sqlite.py` (4 tests) vigila que nadie abra SQLite "por la ventana" `[V]` |
| **Leer** `backend/trading.db` | **Ocurre.** `test_ai_builders_integration.py:28-49`, 26 tests, read-only (§6.4) `[V]` |
| Escribir en Postgres compartido | **Cubierto.** Esquema por módulo con pid en el nombre + `application_name` propio para no matar la corrida de al lado (`conftest.py:229`, `:269-285`) `[V]` |
| Mandar emails reales | **Cubierto** por la guarda de `billing/emails` bajo pytest (`test_email_guard.py`) `[V]` — salvo la puerta de `backend/scripts/test_emails.py` si se corre pytest desde la raíz (§1.2) |
| Salir a la red | **Parcial.** 20 archivos referencian `requests`/`httpx`/`yfinance`/`urlopen`; sólo **51 de 237 archivos** usan `monkeypatch`/`mock` en algún lado `[V]`. Los grandes (`test_events.py:372-387`, `test_alerts.py:30-33`) mockean explícito, pero no hay ningún guard global tipo `socket` bloqueado |

---

### 9. Skips, xfail y tests de código muerto

**`xfail`: cero en todo el backend** (`grep -rn "xfail" backend/tests/` → vacío) `[V]`.

#### 9.1 Skips condicionales por motor (legítimos)

~28 decoradores `@unittest.skipIf(main.USANDO_PG)` / `@skipUnless(main.USANDO_PG)` en 12
archivos — la mitad de la suite del shim/migración sólo corre en uno de los dos motores `[V]`.
Más 4 archivos con `@skipUnless(os.environ.get("PG_DSN_VERIF"))`
(`test_copiar_a_postgres.py:249`, `test_conexiones_pg_ajustadas.py:128`,
`test_esquema_pg_reaplicable.py:137`, `test_verificar_copia.py:567`) — **no corren nunca a
menos que se setee esa variable a mano** `[V]`.

#### 9.2 🟡 `test_balanz.py`: 3 clases enteras skippeadas sobre código muerto

`backend/tests/test_balanz.py` — 19 tests, de los cuales una mayoría está apagada `[V]`:

| Línea | Qué se apaga |
|---|---|
| `:83` | `@unittest.skip` sobre toda la clase `ZeroCostLotsTest` (4 tests) |
| `:137`, `:146`, `:161`, `:169` | 4 métodos de `CapitalReductionTest` |
| `:204` | `@unittest.skip` sobre toda `LowSeverityFixesTest` |
| `:254` | otra clase entera |

El motivo está escrito y es bueno (`:83-91`): el parser de Balanz "Resultados" está **bloqueado
a propósito desde `e4eed6c`** porque ese export no trae depósitos ni retiros y dejaba el capital
aportado negativo con P&L inflado ~78×; `parse()` corta con `BALANZ_RESULTADOS_NO_SOPORTADO`.
*"todo lo que estos tests ejercitan es código muerto. Se dejan (no se borran) porque documentan
el comportamiento a restaurar"* `[V]`.

Es una decisión defendible. Lo anoto porque **el archivo cuenta 19 tests y ejecuta bastante
menos**: cualquier lectura de "cobertura de Balanz" por conteo de archivos está inflada.

#### 9.3 🟡 Skips de datos que convierten un fallo en un no-evento

| Archivo | Skip | Efecto |
|---|---|---|
| `backend/tests/test_ai_builders_integration.py` | 8 `pytest.skip` (`:37`, `:46`, `:48`, `:310`, `:325`, `:355`, `:418`, `:483`) | 26 tests que se saltean si falta la DB de dev o si el admin no tiene posiciones/goals/trades |
| `backend/tests/test_contrato_clasificacion.py:151`, `:155` | `self.skipTest("el endpoint de diagnóstico no respondió")` / `"sin snapshots_recientes"` | Un endpoint que devuelve 500 hace que el **test de contrato** se saltee en vez de fallar |
| `backend/tests/test_endpoints_no_bloquean.py:140` | `self.skipTest("no levantó el server de prueba")` | idem |

`test_contrato_clasificacion.py:151` es el que más me molesta: se llama "EL TEST DE CONTRATO:
los cinco lectores del mismo dato, obligados a coincidir" (`:1-2`), y si el endpoint no
contesta 200, **se saltea** `[V]`. Un contrato que se salta cuando la otra parte no aparece no
es un contrato.

#### 9.4 Sin código comentado

No encontré bloques de tests comentados con `#` a escala. Los apagados usan `@unittest.skip`
con motivo escrito, que es la forma correcta `[V]`.

---

### 10. Olores sueltos, con cita

1. **`test_importer.py` tiene 271 tests y cero rebuilds.** Es el archivo que más pesa de la
   suite y el que menos se parece a producción en su costura más cara (`backend/tests/test_importer.py`,
   46 `persist_batch`, 0 `rebuild_fifo_after_import`) `[V]`.

2. **`conftest.py` es más largo y mejor documentado que la mayoría de los tests.** 423 líneas,
   de las cuales ~300 son comentario forense con mediciones reales (46/49/46 fallas según la
   carga de la máquina, `:111-121`) `[V]`. Es un activo enorme; también es la señal de cuánto
   costó llegar a que la suite dé un número estable.

3. **La suite es el único gate y nadie la corre automáticamente.** Sin CI (§1.4), la garantía
   de que los 3.720 tests pasen antes de un deploy es que alguien se acuerde. Con 26 fallas
   conocidas de base, "¿esto ya estaba roto?" es una pregunta que hay que contestar a mano en
   cada sesión.

4. **`fallas_conocidas.txt` sólo protege si se corre la suite ENTERA.** El propio guard lo
   advierte (`conftest.py:366-369`) `[V]`: con un subconjunto, las que faltan "no están
   arregladas, no se ejecutaron". Es correcto — pero significa que el flujo real de trabajo
   (`pytest tests/test_x.py`) **no tiene red**.

5. **Tres convenciones de helper conviviendo en `test_importer.py`**: `_helpers()` sin recalc
   (`:64`), `_helpers()` + recalc a mano (`:1462`), y `helpers=main` (`:5615`) `[V]`.

6. **64 archivos `.db` filtrados por corrida** (§2.1) `[V]`.

7. **`--timeout` depende de un plugin no declarado** (§1.5) `[V]`.

8. **El `.gitignore` no aparece cubriendo `trading.db`** — la base de desarrollo está
   **comiteada en el repo** (`backend/trading.db`, `backend/trading.db-shm`,
   `backend/trading.db-wal` existen en el árbol de `origin/main`) `[V]`. Eso es lo que hace
   que `test_ai_builders_integration.py` funcione, y también lo que hace que el default de
   `DB_PATH` fuera peligroso en primer lugar. No es materia de esta sección, pero es la causa
   raíz del §6.4.

---

### Apéndice — comandos verificados

```bash
# Backend, SQLite (baseline). Desde backend/ para que tome pytest.ini.
cd backend && python3 -m pytest tests -q

# Backend, Postgres.
cd backend && DATABASE_URL="…" python3 -m pytest tests -q --timeout=20   # requiere pytest-timeout (no declarado)

# Un archivo (⚠️ sin red de fallas_conocidas)
cd backend && python3 -m pytest tests/test_rebuild_fifo.py -q

# Los 3 scripts que NO son tests, a mano
python3 backend/scripts/test_emails.py alguien@ejemplo.com   # 🔴 manda 3 mails REALES
cd backend && python3 -m scripts.test_bot_profile_boundaries
cd backend && python3 -m scripts.test_proration_edge_cases

# Frontend
cd frontend && npm test          # vitest run
cd frontend && npm run test:watch

# Baseline del contrato visual
cd frontend && node scripts/gen-design-baseline.mjs          # dry-run
cd frontend && node scripts/gen-design-baseline.mjs --write  # sólo si BAJÓ deuda a propósito
```

**⚠️ No corras `pytest` desde la raíz del repo** (§1.2): no encuentra `backend/pytest.ini` y
vuelve a colectar `backend/scripts/test_*.py`.
