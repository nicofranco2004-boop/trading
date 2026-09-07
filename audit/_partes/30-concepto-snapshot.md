## Snapshot / foto histórica de la cartera

### Definición según el código

En Rendi un **snapshot** es *una fila por (usuario, día) que dice cuánto valía TODA la cartera de esa persona ese día, en dólares*. No es por broker, no es por activo: es un único número global por día, con `UNIQUE(user_id, date)`.

`[V]` La tabla `snapshots` (`backend/main.py:1368-1381`, `backend/schema_pg.sql:1525-1538`) tiene estas columnas y cada una significa algo distinto:

| columna | qué es REALMENTE |
|---|---|
| `total_value` | Σ posiciones × precio de mercado + cash, todo convertido a USD **al dólar-MEP** (`backend/snapshots_job.py:640-644`). En las filas fabricadas por el import NO es un valor de mercado: es `monthly_entries.capital_final`, o sea la cadena contable (`backend/importing/persister.py:1292-1296`). |
| `total_invested` | cost basis (legacy). En las filas del import es el `net_deposited` acumulado, no un costo (`backend/importing/persister.py:1296`). |
| `net_deposited` | Σ(depósitos − retiros) **más el `capital_inicio` del primer mes** (baseline) — `backend/snapshots_job.py:388-403`. |
| `fx_to_usd_blue` | el blue del día, estampado SOLO para display (curva en pesos). NO es el rate con el que se valuó (`backend/snapshots_job.py:634-638`). |
| `holdings_json` | `[{asset, value_usd}]` — la composición por activo, sin cash (`backend/snapshots_job.py:759-765`). |
| `mtm_coverage` | qué fracción del valor NO-CASH se pudo valuar a precio real. Sólo la escribe el reconstructor (`backend/main.py:1409-1421`). |
| `source` | quién escribió la fila: `'cron'`, `'browser'`, `'import'`, `'mtm_backfill'`, o NULL (legacy). |
| `base` | `'mercado'` o `'costo'` — con qué REGLA está valuado `total_value` (`backend/twr.py:243-245`). |
| `apto` | 0/1 — si esa fila puede ser PICO, BORDE de período y DENOMINADOR (`backend/twr.py:247-258`). |

**La definición no estándar y central del sistema:** `[V]` Rendi NO trata a todos los snapshots como el mismo dato. El código separa explícitamente **tres preguntas distintas sobre la misma fila** (`backend/twr.py:59-88`, `frontend/src/utils/evolution.js:1-20`):

1. **¿el punto entra a la línea dibujada?** → `ACEPTA_LINEA = (MEDICION, RECONSTRUIDO, INTRADIA)` (`backend/twr.py:88`)
2. **¿puede ser PICO o DENOMINADOR?** → `BASE_MERCADO = (MEDICION, RECONSTRUIDO)` **y** `base == 'mercado'` → `es_apto()` (`backend/twr.py:87`, `:258`)
3. **¿con qué regla está valuado?** → `base` ∈ {`'mercado'`, `'costo'`} (`backend/twr.py:243-244`)

`[V]` Y clasifica cada fila en cinco clases (`backend/twr.py:51-57`):

```
MEDICION = "medicion"                # cierre real a mercado — sirve de borde
RECONSTRUIDO = "reconstruido"        # tenencia histórica valuada a precio real de mercado
INTRADIA = "intradia"                # foto de media rueda escrita por un browser
SINTETICO_COSTO = "sintetico_costo"  # fabricado por el import: contabilidad, no mercado
INDETERMINADO = "indeterminado"      # no se puede afirmar cuál es — no se usa de borde
```

`[V]` **Hay CUATRO escritores distintos** de la misma tabla, y sólo uno de ellos escribe algo que el propio código considere una medición:

| escritor | `source` | qué mete en `total_value` | `base`/`apto` |
|---|---|---|---|
| cron nocturno | `'cron'` | posiciones × precio real al MEP | `'mercado'` / `1` |
| Dashboard del browser | `'browser'` | lo que el frontend calculó a media rueda | `'mercado'` / `0` |
| import histórico | `'import'` | `monthly_entries.capital_final` (contabilidad) | `'costo'` / `0` |
| reconstructor MtM | `'mtm_backfill'` | costo + unrealized histórico | según `mtm_coverage ≥ 0.90` |

`[V]` Todo el andamiaje existe por un caso concreto documentado en el código, el "caso 452": una foto `source='import'` de 196.631,56 (costo) encadenada contra una medición del cron de 67.214,75 (mercado) publicaba **−65,82%** de pérdida que nunca existió (`frontend/src/hooks/useMonthlyData.js:415-427`, `backend/twr.py:290-296`).

---

### Dónde se calcula

| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |
|---|---|---|---|---|---|
| 1 | `backend/snapshots_job.py:623` | `take_snapshot_for_user` | **EL CANÓNICO.** Valúa la cartera entera y hace UPSERT de la fila del día | `total_value += r['value']` por broker con `compute_broker_value_usd(bpos, prices, b['currency'], tc_blue, broker_name=b['name'], cedear_rate=tc_cedear)` | fuente |
| 2 | `backend/snapshots_job.py:778-791` | `take_snapshot_for_user` (INSERT) | escribe la fila del cron | `VALUES (?, ?, ?, ?, ?, ?, ?, 'cron', 'mercado', 1)` … `ON CONFLICT(user_id, date) DO UPDATE SET … source = 'cron', base = 'mercado', apto = 1` | fuente |
| 3 | `backend/snapshots_job.py:734-742` | guard de cobertura | NO escribe si faltan precios | `coverage = (priced_cost / total_cost) if total_cost > 0 else 1.0` ; `MIN_COVERAGE = 0.95` ; `if non_cash and coverage < MIN_COVERAGE: return {'ok': False, 'reason': 'low_price_coverage'}` | fuente |
| 4 | `backend/snapshots_job.py:759-765` | composición por activo | arma `holdings_json` reusando la misma valuación posición por posición | `by_asset[p['asset']] += rp['value']` ; `holdings = [{'asset': a, 'value_usd': round(v, 2)} …]` | fuente |
| 5 | `backend/snapshots_job.py:388-403` | `compute_net_deposited` | el `net_deposited` que estampa el cron | `baseline = globals_sorted[0].get('capital_inicio') or 0` ; `flows = sum((m.get('deposits') or 0) - (m.get('withdrawals') or 0) …)` ; `return baseline + flows` | fuente |
| 6 | `backend/snapshots_job.py:328-386` | `compute_net_deposited_db` | SSoT del aportado, con `as_of_date` (trunca a MES) | `SELECT COALESCE(SUM(deposits) - SUM(withdrawals), 0) AS net FROM monthly_entries WHERE {where}` + `baseline` | fuente |
| 7 | `backend/snapshots_job.py:158` | `compute_broker_value_usd` | el motor de valuación que usan cron, reconstructor y live | (posiciones × precio, con `_trust_mkt_value` y conversión ARS→USD por `cedear_rate`) | fuente |
| 8 | `backend/snapshots_job.py:605` | `apply_last_known_prices` | completa faltantes con el último precio conocido (no con el costo) | — | fuente |
| 9 | `backend/snapshots_job.py:910` | `run_daily_snapshot` | el job diario: itera todos los usuarios, commit por usuario | fail-closed: `if not tc_mep or tc_mep <= 0: return {'ok': False, 'reason': 'invalid_mep'}` | fuente |
| 10 | `backend/main.py:32036` / `:32534` | `_run_daily_snapshot_job` + scheduler | dispara el cron in-process | `CronTrigger(hour=2, minute=59)` (= 23:59 ART) | fuente |
| 11 | `backend/main.py:33647` | `POST/GET /api/snapshots/run-cron` | cron EXTERNO (cron-job.org), en thread; auth por `SNAPSHOT_CRON_TOKEN` | `if _snapshot_cron_running: return {"ok": True, "status": "already_running"}` | fuente |
| 12 | `backend/main.py:5004` | `POST /api/snapshots` | el snapshot que escribe el BROWSER con los totales del Dashboard | `VALUES (?, ?, ?, ?, ?, ?, 'browser', 'mercado', 0)` (`backend/main.py:5072-5085`) | fuente |
| 13 | `backend/main.py:5054-5069` | `post_snapshot` (guard) | si ya hay `source='cron'` NO pisa el valor, sólo `net_deposited` y `fx` | `if _prev is not None and _prev["source"] == "cron": UPDATE snapshots SET net_deposited = ?, fx_to_usd_blue = COALESCE(?, …)` | fuente |
| 14 | `frontend/src/pages/Dashboard.jsx:463-478` | efecto de snapshot 1×/día | dispara el POST, con guard propio de cobertura y de riel de dólar | `if (valuationDollar !== 'mep') return` ; `if (!(priceCoverage >= PRICE_COVERAGE_MIN)) return` ; `PRICE_COVERAGE_MIN = 0.95` | fuente |
| 15 | `frontend/src/pages/Dashboard.jsx:440-458` | `priceCoverage` | espejo frontend del guard del cron | `const priced = nonCash.reduce((s, p) => s + (hasPrice(p) ? costUsd(p) : 0), 0)` ; `return priced / total` | fuente |
| 16 | `backend/importing/persister.py:1230` | `_backfill_snapshots_from_monthly` | fabrica una foto por FIN DE MES desde la contabilidad | `total_value = capital_final del mes` ; `total_invested = cumulative net_deposited` ; `net_deposited = Σ (deposits - withdrawals)` | fuente |
| 17 | `backend/importing/persister.py:1292-1296` | idem (INSERT) | INSERT-only, no pisa nada | `VALUES (?,?,?,?,?,'import','costo',0) ON CONFLICT(user_id, date) DO NOTHING` | fuente |
| 18 | `backend/importing/persister.py:1260-1261` | idem (limpieza) | borra las fotos con fecha futura antes de rellenar | `DELETE FROM snapshots WHERE user_id=? AND date > ?` | fuente |
| 19 | `backend/scripts/backfill_historical_mtm.py:435` | `backfill_user` | reconstruye la tenencia a fin de mes y la valúa a precio HISTÓRICO | `cobertura = val_mkt / base_cob` ; `new_cf = cost + u` ; `if new_cf < 0: new_cf = max(cost, new_cf)` | fuente |
| 20 | `backend/scripts/backfill_historical_mtm.py:341` | `_persist_mtm_snapshots` | UPSERT de las fotos reconstruidas, sin pisar una MEDICION | `if existentes.get(d) == MEDICION: continue` ; `_base, _apto = _twr_base_apto(info["coverage"])` | fuente |
| 21 | `backend/scripts/backfill_historical_mtm.py:414-427` | idem (INSERT) | escribe con `source='mtm_backfill'` | `ON CONFLICT(user_id, date) DO UPDATE SET total_value = excluded.total_value, … mtm_coverage = excluded.mtm_coverage, base = excluded.base, apto = excluded.apto` | fuente |
| 22 | `backend/scripts/backfill_historical_mtm.py:378-382` | `net_dep_por_mes` | el aportado de la foto reconstruida, con baseline (para no divergir del cron) | `cum += (r["deposits"] or 0) - (r["withdrawals"] or 0)` ; `net_dep_por_mes[…] = baseline + cum` | fuente |
| 23 | `backend/scripts/backfill_historical_mtm.py:520-537` | guard anti-distorsión | degrada a costo un precio no confiable | `_lo, _hi = (0.02, 4.0) if _fixed else (0.002, 50.0)` ; `if not trusted: u = 0.0` | fuente |
| 24 | `backend/main.py:30639` | `_reconstruir_mtm` | corre el reconstructor después de un import confirmado | `res = backfill_user(conn, uid, _dt.utcnow().date())` | fuente |
| 25 | `backend/main.py:30715` | `_reconstruir_mtm_post_import` | lo manda a un thread daemon (yfinance tarda minutos) | — | fuente |
| 26 | `backend/main.py:15889` | `POST /api/admin/backfill-mtm` | el disparador manual del reconstructor | — | fuente |
| 27 | `backend/twr.py:181` | `clasificar_fila` | clasifica UNA fila | `_POR_SOURCE = {"cron": MEDICION, "browser": INTRADIA, "import": SINTETICO_COSTO, "mtm_backfill": RECONSTRUIDO}` ; sin `source`: `if tiene_holdings: return MEDICION` ; `if tiene_fx: return INTRADIA` ; `if _es_fin_de_mes(row["date"]): return SINTETICO_COSTO` | fuente |
| 28 | `backend/twr.py:365` | `clasificar_serie` | **el clasificador canónico**: agrega la CADENCIA para rescatar las filas legacy | `RACHA_CRON_MINIMA = 7` ; `if (i - ini) >= RACHA_CRON_MINIMA: … if clases[j] == INTRADIA and _legacy(filas[j]): clases[j] = MEDICION` | fuente |
| 29 | `backend/twr.py:293` | `base_de` | deduce la base cuando no está estampada | `if clase in (MEDICION, INTRADIA): return VALUADO_A_MERCADO` ; `if clase == RECONSTRUIDO: return VALUADO_A_MERCADO if cobertura >= COBERTURA_MEDICION else VALUADO_AL_COSTO` ; `COBERTURA_MEDICION = 0.90` | fuente |
| 30 | `backend/twr.py:247` | `es_apto` | la segunda pregunta | `return clase in BASE_MERCADO and base == VALUADO_A_MERCADO` | fuente |
| 31 | `backend/twr.py:1152` | `base_y_apto_para` | la función que TODOS los escritores deben usar | `b = base_de(clase, cobertura)` ; `return b, (1 if es_apto(clase, b) else 0)` | fuente |
| 32 | `backend/twr.py:1163` / `:1205` | `estampar_base` | migración: estampa `base`/`apto` en las filas viejas | `UPDATE snapshots SET base=?, apto=? WHERE id=?` ; `solo_faltantes=True` es el CONTRATO | fuente |
| 33 | `backend/main.py:32167` | `_migrate_estampar_base` (startup hook) | corre `estampar_base` en background con reintentos | `r = _run_with_lock_retry(_estampar, attempts=5, base_delay=2.0)` | fuente |
| 34 | `backend/twr.py:1109` / `:1135` | `bases_de_serie` / `aptos_de_serie` | **el estampo manda; si falta, se deduce** | `if estampada in (VALUADO_A_MERCADO, VALUADO_AL_COSTO): out.append(estampada) else: out.append(base_de(c, _col(r, "mtm_coverage")))` | fuente |
| 35 | `backend/twr.py:1283` | `serie_medible` | parte la serie en tramos, separa medibles / no-medibles / banda contable | `("value" if _apto else "value_no_medible"): _val` | fuente |
| 36 | `backend/twr.py:1611` | `curva_indexada` | encadena Dietz sobre `serie_medible` → curva, drawdown, CAGR | `idx *= (1.0 + ret)` (`backend/twr.py:1876`) | fuente |
| 37 | `backend/twr.py:1014` | `_aportado_por_punto` | corrige `net_deposited` por punto anclando el borde de mes al canónico | `aportado(d) = clamp( canon(M) − (estampa(rn) − estampa(d)), min(canon(M−1), canon(M)), max(canon(M−1), canon(M)) )` | fuente |
| 38 | `backend/main.py:15516` | `_recompute_snapshots_netdep_for_user` | reescribe `net_deposited` de todas las fotos del usuario | `_fn = _twr._aportado_por_punto(conn, uid, _filas_tw)` ; fallback: `_cnd(conn, uid, as_of_date=r["date"], broker_filter='global', include_baseline=True)` | fuente |
| 39 | `backend/main.py:15413` | `_detect_and_remove_corrupt_snapshots` | borra fotos con forma de V (fetch parcial de yfinance) | Track 1: `if drop_from_prev < -0.15 and recovery_to_next > 0.20` ; Track 2: `-0.15 <= drop_from_prev < -0.05` + `flows_consistent` + `recovery_abs >= 0.80 * drop_abs` | fuente |
| 40 | `backend/main.py:15623` | `_remove_trajectory_outlier_snapshots` | borra fotos fuera de banda contra `capital_final` del mes | `ratio = tv / capf` ; `if ratio < 0.10 or ratio > 20.0` ; guard: `if n_tot >= 3 and len(ids) / n_tot >= 0.8: (mes protegido)` | fuente |
| 41 | `backend/main.py:15687` | `_repair_user_snapshots` | orquesta recalc + backfill + netdep + los dos detectores | `changed: before != after` | fuente |
| 42 | `backend/main.py:12883` | `_cascade_after_movement_delete` | borra sólo las SINTÉTICAS de fin de mes + la de hoy tras borrar un movimiento | `DELETE FROM snapshots WHERE user_id=? AND date >= ? AND fx_to_usd_blue IS NULL AND COALESCE(TRIM(holdings_json), '') = '' AND date = date(date, 'start of month', '+1 month', '-1 day')` | fuente |
| 43 | `backend/main.py:4339` (`:4508-4520`) | `delete_broker` | purga snapshots desde la primera actividad del broker y re-backfillea | `DELETE FROM snapshots WHERE user_id=? AND date >= ?` | fuente |
| 44 | `backend/main.py:20162` (`:20262-20266`) | `_wipe_broker_data` | borra sólo el intradiario de hoy y re-backfillea | `DELETE FROM snapshots WHERE user_id=? AND date=?` | fuente |
| 45 | `backend/importing/persister.py:1694-1702` | revert de batch | purga desde la fecha más vieja del batch | `DELETE FROM snapshots WHERE user_id=? AND date >= ?` | fuente |
| 46 | `backend/main.py:9414` (`:9636-9637`) | `_recalc_pnl_realized_from_ops` | si el usuario quedó 100% vacío, borra TODOS sus snapshots | `conn.execute("DELETE FROM snapshots WHERE user_id=?", (uid,))` | fuente |
| 47 | `backend/main.py:17315` | `admin_cleanup_future_snapshots` | borra fotos con fecha futura de TODAS las cuentas | `DELETE FROM snapshots WHERE date > ?` | fuente |
| 48 | `backend/main.py:18591` | `admin_delete_snapshot` | borra una foto puntual del admin logueado | `DELETE FROM snapshots WHERE user_id=? AND date=?` | fuente |
| 49 | `backend/snapshots_job.py:810` | `compute_live_portfolio_value` | valor "de hoy" SIN persistir, con las mismas 3 defensas del cron; caché 60s | `_LIVE_VALUE_TTL_SEC = 60` | fuente (efímera) |
| 50 | `backend/scripts/base_sintetica.py:212-217` | generador de base sintética | fabrica snapshots de prueba a escala | `VALUES (?,?,?,?,?,?,?,?,?)` con `"cron"` y `'{"h":[]}'` | fuente (dev) |
| 51 | `frontend/src/utils/demo.js:1606-1643` | `SNAPSHOTS` (modo demo) | interpola 4 puntos por mes entre `capital_inicio` y `capital_final` | `const valueT = capStart + (capEnd - capStart) * frac + (Math.random() - 0.5) * 200` | fuente (demo) |

---

### Dónde se lee / se muestra

| archivo:línea | quién lo consume | cómo se llama en la UI |
|---|---|---|
| `backend/main.py:5093` | `GET /api/snapshots` — la lista que lee todo el frontend. Clasifica por SERIE y agrega `clase`, `apto`, `sintetico` | (no visible; alimenta todos los gráficos) |
| `backend/main.py:5153-5164` | idem: `d["apto"] = _twr.es_apto(_clase, _base)` ; `d["sintetico"] = not d["apto"]` ; **borra `holdings_json`, `source` y `mtm_coverage` del payload** | — |
| `backend/reporting/builder.py:296` | `fetch_snapshot_at_or_before` — el borde de APERTURA de todo período | "P&L del mes / del año" |
| `backend/reporting/builder.py:399` | `fetch_latest_measured_snapshot` — el borde de CIERRE | idem |
| `backend/reporting/builder.py:523` | `bordes_mercado_periodo` — las dos puntas de un período cerrado | Reportes → Mes / Año |
| `backend/reporting/builder.py:248` | `fetch_snapshots_in_range` — snapshots del rango, **sin filtro de clase** | — |
| `backend/reporting/builder.py:1418-1429` | `compute_metrics_for_period` (week/day) — `snap_start` con `mtm_only=True`, `snap_end` sin filtro | Reportes → Día / Semana |
| `backend/reporting/builder.py:1705` | `fetch_holdings_snapshot_at_or_before` — la foto por activo | Reportes → "quién movió la aguja" |
| `backend/reporting/builder.py:1717` | `compute_movers` — diffea `holdings_json` entre bordes | Reportes → mejores/peores del período |
| `backend/main.py:32635` | `_portfolio_snapshot_summary` — capital, deltas 1d/7d/30d, YTD | Reportes (`portfolio_snapshot`) |
| `backend/main.py:32873` | `_snapshot_delta` — el chip de variación a N días | "Δ último cierre", "vs vie 15 may" |
| `backend/main.py:32949` | `_ytd_delta` — YTD | "YTD 2026" |
| `backend/main.py:33211` | `/api/reports/period` inyecta `out["portfolio_snapshot"]` | Reportes |
| `backend/main.py:11788` | `GET /api/insights/performance` → `performance.performance` → `twr.curva_indexada` | Métricas → Performance (curva + benchmark + banda gris) |
| `backend/performance.py:185-285` | arma la respuesta: `curva`, `contable`, `cobertura`, `drawdown_*`, `twr`, `cagr` | idem |
| `backend/main.py:15320` / `:15394` | `_historical_cagr_global` / `GET /api/goals/cagr` | "Rendimiento histórico" en Objetivos y Dashboard |
| `backend/main.py:11562` | `GET /api/insights/gap-month` — dos fotos de mes con heurística PROPIA de "sintético" | Admin / diagnóstico del mes |
| `backend/main.py:11838` | `GET /api/insights/mtm-audit` — reconcilia costo vs mercado mes a mes, heurística PROPIA | Admin → "Meses con snapshot / snapshots SINTÉTICOS" |
| `backend/main.py:11665-11683` | diff de composición entre dos fotos (`holdings_json`) | "qué activo se movió" |
| `backend/twr.py:466` | `diagnosticar` — semáforo de calidad de datos por usuario | Asesor → "clientes medibles" |
| `backend/twr.py:718` | `bordes_medibles` — sólo `MEDICION` | TWR sellado del asesor |
| `backend/advisor_twr.py:40-70` | expone `snapshots`, `por_clase`, `tramos_planos` por cliente | Asesor → TWR del libro |
| `backend/advisor_brief.py:289-311` | Δ del día del cliente vs último cierre **filtrando por `apto`** | mail diario del asesor |
| `backend/advisor_alerts.py:251-274` | alerta de caída del día, mismo filtro `apto` + piso de frescura de 4 días | alertas del asesor |
| `backend/advisor_groups.py:238-244` | `snap_value` y `net_deposited` del ÚLTIMO snapshot, **sin filtro** | grupos de clientes |
| `backend/main.py:36790` | `_latest_snapshots` — MAX(date) sin filtro (a propósito: es el AUM) | Asesor → AUM del libro |
| `backend/main.py:36814` | `_snapshots_asof` — idem con cutoff | serie histórica del libro |
| `backend/main.py:36757` | `_es_base_de_mercado` — el filtro que aplican los CONSUMIDORES de las dos de arriba | delta del libro |
| `backend/main.py:37162` | `MAX(total_value - COALESCE(net_deposited, 0))` sobre `snapshots_medibles` → el PICO | "su ganancia cayó X% desde el mejor momento" |
| `backend/main.py:36737` / `:37217` | `_pico_es_plausible` — cota de cordura sobre el pico | silencia la alerta de drawdown |
| `backend/main.py:34515-34521` | último snapshot por cliente (AUM + fecha) | Asesor → lista de clientes |
| `backend/main.py:37884` (`:37913-37919`) | `advisor_book_history` — serie de AUM con forward-fill, **sin filtro de clase** | Asesor → gráfico de AUM |
| `backend/main.py:35487` | `MAX(net_deposited)` por cliente | contexto de la IA del asesor |
| `backend/ai/builders/home.py:97-99` | `SELECT date, total_value FROM snapshots_medibles … LIMIT 2` → `delta_pct_today` | Home / primer pantallazo |
| `backend/ai/builders/dashboard.py:106-108` | `snapshots_medibles … LIMIT 90` → `twr_30d_pct`, `drawdown_30d_high` | packet de IA del Dashboard |
| `backend/ai/builders/goal.py:46-56` | `snapshots_medibles` primero, **fallback a `snapshots` crudo** | "capital actual" contra el objetivo |
| `backend/main.py:17804` | `admin_diagnose_reportes_basis` — clase del borde, picos implausibles, cortes dudosos | Admin → diagnóstico |
| `backend/main.py:18116` | `admin_diagnose_flujo_implausible` | Admin |
| `backend/main.py:18668` | `SELECT COUNT(*) FROM snapshots` | Admin → "Snapshots almacenados" |
| `backend/importing/proyeccion.py:232-236` | verifica la proyección contra el `holdings_json` de un snapshot `source='cron'` | verificación de reconstrucción |
| `backend/importing/fx_migrate.py:93-95` | último `total_value` como valor de cartera antes/después de migrar el TC | migrador FX |
| `backend/importing/tenencia.py:560` | comentario: `holdings_json` guarda `value_usd`, **no cantidades** → el balde `over` no tiene respaldo | reconciliación de foto de tenencia |
| `frontend/src/pages/Dashboard.jsx:145` | `api.get('/snapshots?days=3650')` | Dashboard (desktop) |
| `frontend/src/pages/HomeMobile.jsx:67` | `api.get('/snapshots?days=30')` | Home (mobile) |
| `frontend/src/pages/Insights.jsx:365` | `api.get('/snapshots?days=3650')` | Métricas |
| `frontend/src/hooks/useMonthlyData.js:173` | `api.get('/snapshots?days=3650')` | Reportes mensuales |
| `frontend/src/pages/Positions.jsx:461` | `api.get('/snapshots?days=30')` | Cartera |
| `frontend/src/utils/evolution.js:31` | `esApto(s)` → `s.apto !== undefined ? !!s.apto : !s.sintetico` | — |
| `frontend/src/utils/evolution.js:43` | `esDibujable(s)` → `ACEPTA_LINEA.includes(s.clase)` | — |
| `frontend/src/utils/evolution.js:173` | `buildPortfolioValueSeries` — filtra `esDibujable` ANTES del recorte de ventana | curva "Evolución del portfolio" |
| `frontend/src/utils/evolution.js:254-269` | `netDepositedOf` — `(nd != null && nd !== 0) ? nd : (s?.total_invested \|\| 0)` | baseline del Total Return |
| `frontend/src/utils/evolution.js:305` | `computeReturnDelta` — sólo `esApto` | "HOY", "Este mes" |
| `frontend/src/utils/evolution.js:375` | `computeDailyPnl` | "P&L del día" |
| `frontend/src/utils/evolution.js:407-445` | `buildEvolutionFromSnapshots` — `snapshots.filter(esApto)` | Métricas → evolución diaria |
| `frontend/src/utils/evolution.js:88` | `diagnosticoSinMedicion` | copy del estado vacío ("Sin medición") |
| `frontend/src/utils/evolution.js:156` | `convertSeriesToArs` | curva en pesos |
| `frontend/src/utils/insightsModel.js:600-621` | `applyMtmToMonthly` — `if (s?.sintetico) continue` | corrige la cadena contable con MtM |
| `frontend/src/hooks/useMonthlyData.js:308-317` | `snapsByMonth` con `esDibujable` (regla floja: dibujo) | sparkline por mes |
| `frontend/src/hooks/useMonthlyData.js:428-437` | `baseSnap`/`lastSnap` con `esApto` (regla exigente: medición) | "rendimiento del mes en curso" |
| `frontend/src/pages/Positions.jsx:1624-1645` | `snapshots.find(s => s.date < today)` — **sin `esApto`** | banner de variación diaria de Cartera |
| `frontend/src/pages/Reports.jsx:503` | `period.portfolio_snapshot` | Reportes → capital actual |
| `frontend/src/pages/Admin.jsx:1718-1762` | "Meses con snapshot", "snapshots SINTÉTICOS", "meses sin cobertura" | Admin |
| `frontend/src/pages/Admin.jsx:1968-2039` | limpieza de snapshots con fecha futura | Admin |
| `frontend/src/utils/demo.js:2660-2668` | mock de `GET /snapshots` con soporte de `?days=` | modo demo |

---

### Dónde se persiste

`[V]` **Tabla `snapshots`**, una fila por `(user_id, date)`:

- SQLite (migración de startup): `backend/main.py:1368-1381` (CREATE) + `backend/main.py:1389-1440` (los `ALTER TABLE` de `source`, `net_deposited`, `fx_to_usd_blue`, `holdings_json`, `mtm_coverage`, `base`, `apto`).
- Postgres: `backend/schema_pg.sql:1525-1561`.
- Índices: `idx_snapshots_user_date` y `idx_snapshots_apto (user_id, apto, date)` (`backend/main.py:1443-1444`, `backend/schema_pg.sql:1976-1978`).
- **Vista `snapshots_medibles`** (`backend/main.py:1459-1471`, `backend/schema_pg.sql:1997-2007`): `SELECT * FROM snapshots WHERE CASE WHEN apto IS NOT NULL THEN apto WHEN source = 'import' THEN 0 WHEN source = 'browser' THEN 0 WHEN source = 'mtm_backfill' THEN (CASE WHEN COALESCE(mtm_coverage, -1) >= 0.90 THEN 1 ELSE 0 END) ELSE 1 END = 1`.

`[V]` **Lo que NO se persiste**: la CLASE (`medicion`/`intradia`/…) se calcula en cada lectura — es una decisión explícita documentada en `backend/twr.py:406-433` ("LA CLASIFICACIÓN ES READ-TIME, NO ESTÁ MATERIALIZADA"), tras haber borrado un `backfill_source_legacy` que nunca tuvo call-site.

`[V]` **Persistencia secundaria derivada**: la tabla `twr_periods` (`backend/schema_pg.sql:1644`) guarda los tramos SELLADOS que salen de los bordes medibles (`backend/twr.py:800` `sellar`). No es el snapshot, pero es su derivado congelado.

`[V]` **La copia de dev NO tiene el esquema nuevo**: `sqlite3 backend/trading.db ".schema snapshots"` devuelve sólo `id, user_id, date, total_value, total_invested, net_deposited, fx_to_usd_blue` — sin `source`, `holdings_json`, `mtm_coverage`, `base`, `apto`, y sin la vista `snapshots_medibles`. Confirma que esa base viene de una rama vieja; el código manda.

---

### ⚠️ Implementaciones divergentes

**NO hay una sola implementación.** Hay al menos **cinco criterios distintos** conviviendo hoy en `main` para responder la misma pregunta ("¿esta foto sirve?"), más divergencias de ventana, de rate y de fórmula.

#### D-1. Cinco formas de decidir si una foto es usable

| # | criterio | dónde | qué acepta |
|---|---|---|---|
| A | `twr.clasificar_serie` + `bases_de_serie` + `aptos_de_serie` (**el canónico**) | `backend/twr.py:365`, `:1109`, `:1135`; `GET /api/snapshots` (`backend/main.py:5137-5164`); `reporting/builder.fetch_snapshot_at_or_before` (`backend/reporting/builder.py:346-397`); `serie_medible` (`backend/twr.py:1334-1338`); `_persist_mtm_snapshots` (`backend/scripts/backfill_historical_mtm.py:394-397`) | usa el ESTAMPO si existe, si no deduce por clase+cobertura, y rescata las filas legacy por CADENCIA |
| B | vista SQL `snapshots_medibles` | `backend/main.py:1459-1471`; leída por `ai/builders/home.py:97`, `ai/builders/dashboard.py:106`, `ai/builders/goal.py:46`, `main.py:18024`, `main.py:37162` | igual que A **pero sin la cadencia**: una fila legacy sin `source` cae en la rama `ELSE 1` y queda apta |
| C | `COALESCE(s.apto, CASE WHEN COALESCE(s.source,'') IN ('import','mtm_backfill') THEN 0 ELSE 1 END) = 1` — SQL inline duplicado | `backend/advisor_brief.py:291`+`:311`, `backend/advisor_alerts.py:253`+`:273` | rechaza TODA reconstrucción, incluso la de cobertura 0,99, cuando no hay estampo |
| D | `_es_base_de_mercado(row)` en Python | `backend/main.py:36757-36788` | `apto` si está; si no, `src not in ("import","mtm_backfill")` |
| E | heurística vieja "sin blue Y sin holdings" | `backend/main.py:11603-11607` (`gap-month`), `backend/main.py:11862-11866` (`mtm-audit`), `backend/main.py:12929-12933` (cascada de borrado) | `d["sintetico"] = (fx_to_usd_blue is None and not holdings_json)` — **no mira `source` ni `base`** |

`[V]` El propio código documenta que E se equivoca: `backend/main.py:12908-12913` dice textualmente que esa heurística se lleva puesta una MEDICIÓN real cuando el caché del dólar está frío, y por eso la cascada de borrado agrega el requisito de fin de mes. Pero `gap-month` y `mtm-audit` **siguen usándola pelada**. `[I]` Consecuencia: el panel de Admin puede rotular como "SINTÉTICO" un mes que `GET /api/snapshots` sirve como `apto=true` — y al revés, una foto `source='mtm_backfill'` con cobertura 0,05 (contable) tiene blue y holdings, así que E la llama "no sintética".

#### D-2. `apto` no filtra en todos los lectores del asesor

| lector | filtra | archivo:línea |
|---|---|---|
| Δ del día del brief | sí, criterio C | `backend/advisor_brief.py:291` |
| alerta de caída del día | sí, criterio C | `backend/advisor_alerts.py:253` |
| AUM del libro (`_latest_snapshots`) | **no** (a propósito: MUESTRA, no resta) | `backend/main.py:36795-36800` |
| delta del libro | sí, vía `_es_base_de_mercado` en el consumidor | `backend/main.py:36757` |
| perfil de grupos (`snap_value`, `net_deposited`) | **no** | `backend/advisor_groups.py:238-244` |
| serie histórica de AUM (`advisor_book_history`) | **no** | `backend/main.py:37913-37919` |
| `MAX(net_deposited)` del contexto de IA | **no** (`FROM snapshots`) | `backend/main.py:35487` |
| pico para el drawdown | sí (`snapshots_medibles`) + cota `_pico_es_plausible` | `backend/main.py:37162`, `:37217` |

`[I]` `advisor_book_history` hace forward-fill sobre `FROM snapshots` sin filtro: una foto `source='import'` del día del import entra a la serie de AUM del libro como si fuera una medición. El propio repo documenta el mismo defecto en la otra punta (`backend/reporting/builder.py:404-417`, "el borde de CIERRE que nadie miró").

#### D-3. La MISMA fila puede recibir `apto` distinto según quién la lea

`[V]` `bases_de_serie` prefiere el estampo (`backend/twr.py:1123-1129`); `aptos_de_serie` sólo respeta el estampo `apto` **si además `base` está estampada** (`backend/twr.py:1140-1143`):

```python
if estampado is not None and _col(r, "base") in (VALUADO_A_MERCADO, VALUADO_AL_COSTO):
    out.append(bool(estampado))
else:
    out.append(es_apto(c, b))
```

`[V]` Pero `snapshots_medibles` (criterio B) mira `apto` **solo**, sin exigir `base`. `[I]` En una fila con `apto` estampado y `base` NULL (estado imposible hoy porque `estampar_base` escribe las dos juntas, pero alcanzable por un escritor futuro o un UPDATE manual) los dos criterios se separan.

#### D-4. `bordes_medibles` y `diagnosticar` ignoran el estampo

`[V]` `backend/twr.py:718-729` y `backend/twr.py:474-478` seleccionan **sin** `base`/`apto`/`_sel_estampo` y filtran sólo por `c == MEDICION` (la clase re-derivada). No leen la columna estampada. `[I]` Para la clase MEDICION el resultado coincide (base siempre 'mercado'), así que hoy no diverge — pero son los dos únicos lectores del módulo que no pasan por `bases_de_serie`, y el test de contrato los cubre sólo con un fixture de filas legacy del cron (`backend/tests/test_contrato_clasificacion.py:85-92`).

#### D-5. Mobile ve 30 días y desktop 3.650

| pantalla | ventana | archivo:línea |
|---|---|---|
| Dashboard (desktop) | `?days=3650` | `frontend/src/pages/Dashboard.jsx:145` |
| Métricas | `?days=3650` | `frontend/src/pages/Insights.jsx:365` |
| Reportes mensuales | `?days=3650` | `frontend/src/hooks/useMonthlyData.js:173` |
| **Home (mobile)** | `?days=30` | `frontend/src/pages/HomeMobile.jsx:67` |
| **Cartera** | `?days=30` | `frontend/src/pages/Positions.jsx:461` |

`[V]` `GET /api/snapshots` implementa `days` como `LIMIT ?` sobre `ORDER BY date DESC` (`backend/main.py:5111-5116`), **no como filtro de fecha**: `?days=30` devuelve *las 30 filas más nuevas*, no *los últimos 30 días*. El propio `HomeMobile.jsx:149` lo dice: «`GET /snapshots?days=30` es LIMIT 30 filas, no ventana». `[I]` Para un usuario con una foto cada 3 días eso son 90 días de historia, no 30 — y la clasificación por CADENCIA (que necesita 7 días calendario consecutivos, `backend/twr.py:362`) opera sobre una ventana distinta en mobile que en desktop, con lo cual una fila legacy puede salir `apto=true` en Dashboard y `apto=false` en Home mobile.

#### D-6. `Positions.jsx` no filtra nada

`[V]` `frontend/src/pages/Positions.jsx:1627`:

```js
const lastClose = snapshots.find(s => s.date < today)  // snapshots vienen DESC
```

Sin `esApto`, sin `esDibujable`. Si el último snapshot anterior a hoy es la foto `source='import'` de un import reciente, este cálculo devuelve la brecha costo-vs-mercado como "variación diaria" — exactamente el defecto que `frontend/src/hooks/useMonthlyData.js:415-427` documenta haber arreglado en Reportes.

`[V]` **Pero hoy es código muerto**: el JSX que lo mostraba está comentado — `frontend/src/pages/Positions.jsx:1908-1909`: «Banner de variación diaria deshabilitado — requiere snapshots confiables (cron server-side) que aún no están implementados». `[V]` El `useMemo` sigue vivo y sigue corriendo en cada render (`:1624-1645`), y su comentario (`:1622-1623`: «Para variación diaria 100% confiable hace falta un cron server-side que tome snapshot automático cada noche (tarea spawneada aparte)») quedó desactualizado: ese cron EXISTE desde `backend/main.py:32534`. `[I]` O sea: hay una trampa armada para el día que alguien descomente el banner.

#### D-7. Dos definiciones de `net_deposited` conviviendo en la misma columna

| escritor | fórmula | baseline | corte temporal |
|---|---|---|---|
| cron | `compute_net_deposited` (`backend/snapshots_job.py:388`) | sí (`capital_inicio` del primer mes) | **ninguno** — suma TODOS los meses, incluidos los posteriores a `target_date` |
| browser | lo que manda el frontend en el POST (`backend/main.py:5085`) | el que calculó el Dashboard | — |
| import | `net_dep` acumulado mes a mes (`backend/importing/persister.py:1250-1253`) | **no** | hasta ese mes |
| reconstructor | `baseline + cum` (`backend/scripts/backfill_historical_mtm.py:376-382`) | sí | hasta ese mes |
| recompute admin | `twr._aportado_por_punto` (`backend/main.py:15546-15551`) | canónico por mes, interpolado por día | por fila |

`[V]` El comentario de `backend/scripts/backfill_historical_mtm.py:363-372` documenta que la falta de baseline en el reconstructor publicaba *"Mes difícil −61,2% · Aportaste US$100.000 de capital nuevo"*. `[I]` La divergencia del cron (sin corte temporal) significa que, dentro de un mismo mes, todas las fotos del cron traen el aportado del mes ENTERO — incluida la plata que todavía no entró. `_aportado_por_punto` (`backend/twr.py:1014`) existe para corregir esto en lectura, pero **sólo lo usan `serie_medible` y el recompute admin**; los chips de `_snapshot_delta` (`backend/main.py:32932-32937`) leen la columna cruda.

#### D-8. Dos guards de cobertura, dos definiciones de cobertura

| guard | umbral | qué mide | archivo:línea |
|---|---|---|---|
| cron | `MIN_COVERAGE = 0.95` | fracción del **cost basis** no-cash con precio | `backend/snapshots_job.py:733-742` |
| Dashboard (POST) | `PRICE_COVERAGE_MIN = 0.95` | idem, recalculado en JS | `frontend/src/pages/Dashboard.jsx:459-462` |
| clasificador | `COBERTURA_MEDICION = 0.90` | fracción del **valor** no-cash valuada a precio real | `backend/twr.py:127` |
| vista SQL | `>= 0.90` hardcodeado | idem | `backend/main.py:1467` |
| reconstructor | `COBERTURA_REFERENCIA = 0.70`, **ya no filtra** | — | `backend/scripts/backfill_historical_mtm.py:320` |

`[V]` El 0,90 está duplicado como literal dentro de la vista SQL (`backend/main.py:1468`) y como constante en Python (`backend/twr.py:127`). Cambiar uno no cambia el otro.

#### D-9. El rate de valuación no es el que se estampa

`[V]` `backend/snapshots_job.py:634-638`: «TODO al dólar-MEP (holdings .BA, cash ARS y costos) […] El blue genuino (`tc_blue`) queda SOLO para el stamp display `fx_to_usd_blue`». O sea la columna se llama `fx_to_usd_blue` y **no es** el tipo de cambio con el que se calculó `total_value`. `[V]` El frontend la usa para convertir la curva a pesos (`frontend/src/utils/evolution.js:195-201`), es decir: la curva en pesos se dibuja con un rate distinto del que produjo el número en dólares.

`[V]` Y el POST del browser sólo escribe si el usuario está en MEP (`frontend/src/pages/Dashboard.jsx:466-470`); si mira en CCL, no snapshotea.

#### D-10. En modo ESTIMADO el valor de la foto se descarta y se usa la cadena

`[V]` `backend/twr.py:1381-1399`: la foto `SINTETICO_COSTO` de fin de mes se **reemplaza** por `monthly_entries.capital_final` del propio mes:

```python
if (modo == MODO_ESTIMADO and c == SINTETICO_COSTO and _base == VALUADO_AL_COSTO
        and _es_fin_de_mes(d) and _cf_mes.get(d[:7], 0) > 0
        and abs(_cf_mes[d[:7]] - _val) > 1e-6):
    _valor_foto, _val = _val, _cf_mes[d[:7]]
```

`[V]` Con el número medido al lado: «6.402 de 10.348 fotos contables difieren >1 % del `capital_final` de su propio mes». O sea: la foto persistida y la contabilidad **no coinciden en más del 60% de las filas contables**, y el motor elige la contabilidad.

#### D-11. Convergencias verificadas (donde SÍ hay una sola implementación)

- `[V]` Los 6 lectores del test de contrato coinciden sobre la misma fila legacy: `backend/tests/test_contrato_clasificacion.py:124-138` (`twr.serie_medible`, `twr.bordes_medibles`, `twr.diagnosticar`, `builder.fetch_snapshot_at_or_before`, `GET /api/snapshots`, `backfill._persist_mtm_snapshots`).
- `[V]` Los cuatro escritores pasan por `twr.base_y_apto_para` para el estampo (`backend/twr.py:1152-1161`), salvo el cron y el browser que lo escriben como literal (`'mercado', 1` y `'mercado', 0`) — equivalente por construcción pero no centralizado.
- `[V]` `_UNMEASURED_BASE_TOL = 0.10` está portado idéntico entre `backend/reporting/builder.py:440` y `frontend/src/utils/evolution.js:57` (`_TOL_BASE_SIN_MEDIR`), con el comentario que lo dice.

---

### Zonas grises

1. **`GET /api/snapshots` no expone `source`, `holdings_json` ni `mtm_coverage`.** `[V]` `backend/main.py:5156-5158` los hace `pop`. El frontend por lo tanto NO puede distinguir una reconstrucción de cobertura 0,95 de una del cron; sólo recibe `clase`, `apto` y `sintetico`. `[I]` Eso convierte a `esApto`/`esDibujable` en la única puerta, y cualquier lector frontend que quiera matizar (por ejemplo, mostrar "estimado") no tiene el dato.

2. **`sintetico = not apto` colapsa dos preguntas.** `[V]` `backend/main.py:5164`. El propio comentario de `frontend/src/utils/evolution.js:25-29` advierte: «una foto INTRADIA sale `sintetico=true` sin ser fabricada». Pero `applyMtmToMonthly` (`frontend/src/utils/insightsModel.js:621`) sigue filtrando por `s?.sintetico`, no por `apto`/`clase`. `[I]` O sea: el helper que corrige la cadena contable con MtM descarta las fotos intradía, que SON valores de mercado.

3. **`snapshots_medibles` no conoce la cadencia.** `[V]` La vista (`backend/main.py:1459-1471`) tiene una rama `ELSE 1` para filas sin `source`. `[I]` Antes de que `estampar_base` corra, TODA foto legacy del browser entra a `snapshots_medibles` y puede fijar un pico — que es exactamente el defecto que el comentario de `backend/twr.py:66-75` dice haber arreglado. El propio `_migrate_estampar_base` lo advierte: «Con las filas sin estampar, la vista `snapshots_medibles` cae a su rama `ELSE 1` y el pico del asesor vuelve a salir de la cadena contable: medido, 169 alertas de drawdown con 81 picos `sintetico_costo` (peor caso −492.864%)» (`backend/main.py:32214-32220`). **Y esas alertas van por mail.**

4. **No hay endpoint para forzar el estampado.** `[V]` `backend/main.py:32175-32179`: «NO HAY endpoint de admin para forzarlo. […] Si el estampado falla, hoy la única palanca es un redeploy». Con `railway.toml` en `restartPolicyType = "on_failure"`, un fallo del hook deja la base sin estampar hasta el próximo deploy.

5. **La reconstrucción no sirve para la cartera argentina típica.** `[V]` `backend/main.py:30670-30674`: «el reconstructor saltea FCI, los bonos/ONs de data912 y los CEDEAR cotizados en USD […] una cartera AR típica […] da ~50% y NO pasa el piso». Y `backend/twr.py:129-152` estima que, con el piso en 0,90, la reconstrucción le devuelve un número a **entre 4 y 43 de los 172 usuarios** para los que se construyó.

6. **`compute_net_deposited` (cron) no corta por fecha.** `[V]` `backend/snapshots_job.py:396-402` suma `globals_sorted` entero, sin filtrar por `target_date`. `[I]` Para un backfill con `target_date` pasado (o para cualquier foto del mes en curso) el aportado estampado incluye flujos posteriores. `_aportado_por_punto` lo corrige en lectura, pero sólo para los lectores que pasan por `serie_medible`.

7. **`_detect_and_remove_corrupt_snapshots` borra sin distinguir clase.** `[V]` `backend/main.py:15450-15455` selecciona `FROM snapshots` sin filtro y borra por forma de la curva. `[I]` Un import que fabrica una foto de fin de mes al costo entre dos mediciones produce exactamente la V-shape que Track 1 caza — pero el que se borra puede ser la MEDICIÓN del medio, no la fila fabricada, dependiendo de las fechas.

8. **`_remove_trajectory_outlier_snapshots` compara mercado contra costo.** `[V]` `backend/main.py:15631-15656`: `ratio = tv / capf` donde `capf` es `monthly_entries.capital_final` (contabilidad). `[I]` Una cartera con mucho unrealized tiene `total_value` legítimamente lejos de `capital_final`; el guard del 80% del mes (`backend/main.py:15669-15675`) mitiga el caso masivo, pero no el de un mes con 1 o 2 fotos.

9. **`fetch_snapshots_in_range` no filtra nada.** `[V]` `backend/reporting/builder.py:248-257`. No encontré consumidor de producción para esta función — `grep` sólo la muestra definida. `[I]` Si algún camino la usa, devuelve fotos contables mezcladas con mediciones sin marca.

10. **`_BORDER_SCAN_LIMIT = 90` acota cuánto se retrocede.** `[V]` `backend/reporting/builder.py:290` y `:364`. `[I]` Un usuario cuya última medición está a más de 90 FILAS de distancia (no días) no consigue borde, aunque exista. Y como `days` en `GET /api/snapshots` también es `LIMIT`, hay dos "90 filas" distintos operando sobre la misma serie.

11. **La cascada de borrado usa SQL específico de SQLite.** `[V]` `backend/main.py:12931-12932`: `date = date(date, 'start of month', '+1 month', '-1 day')`. `[I]` Esa expresión no existe en Postgres; con la migración a Supabase en curso (memoria del proyecto) este `DELETE` fallaría o borraría cero filas.

12. **Homónimos de "snapshot" / "foto" que NO son este concepto** (los documento para que no se confundan en el índice):
    - `[V]` **el `snapshot` del chat de IA** — un JSON opaco que el frontend arma con posiciones + mensuales + brokers y manda a `/api/ai/chat` (`frontend/src/components/ai/AICoachDrawer.jsx:18-66`, `frontend/src/components/AICoach.jsx:90`, `frontend/src/pages/RendiAI.jsx:38`). No toca la tabla `snapshots`.
    - `[V]` **`portfolio_snapshot`** en la respuesta de Reportes — es el resumen estático de `_portfolio_snapshot_summary` (`backend/main.py:33211`, `frontend/src/pages/Reports.jsx:503`), no una fila de la tabla.
    - `[V]` **la "foto de tenencia"** — el PDF/CSV de tenencia valorizada que el usuario sube para completar posiciones (`backend/importing/tenencia.py:1-9`, `backend/importing/tenencia.py:150` `not_in_snapshot`). Es un import de posiciones, no un punto de la serie histórica. `[V]` El único cruce real: `backend/importing/tenencia.py:558-562` menciona que `snapshots.holdings_json` guarda `value_usd` (composición) y **no cantidades**, por lo que no sirve de respaldo independiente para el balde `over` de la reconciliación.
    - `[V]` **`MonthlySummary.jsx:873`** usa "snapshot al cierre" como copy para un mes cerrado de `monthly_entries`, no para una fila de `snapshots`.

13. **`ai/builders/goal.py` tiene un fallback que rompe su propia regla.** `[V]` `backend/ai/builders/goal.py:46-56`: si no hay ninguna fila en `snapshots_medibles`, cae a `SELECT total_value FROM snapshots … ORDER BY date DESC LIMIT 1`. El comentario lo justifica («un valor aproximado es mejor que un cero, y es un VALOR mostrado, no una resta»), pero `[I]` para un usuario recién importado esa fila es la del import, o sea el capital al costo, presentado como "capital actual" contra el objetivo.

14. **El `useMemo` `daily` de Cartera es código muerto que sigue ejecutándose.** `[V]` `frontend/src/pages/Positions.jsx:1624-1645` calcula la variación diaria sin ningún filtro de clase, y `frontend/src/pages/Positions.jsx:1908-1909` es el comentario JSX que lo deja fuera de la pantalla. No encontré ningún otro consumidor de `daily` en el archivo. `[I]` Es deuda dormida: el día que se reactive, entra sin el guard que el resto de la app ya tiene.

15. **No encontrado**: ningún lugar donde se guarde el rate MEP con el que efectivamente se valuó `total_value`. Sólo se estampa `fx_to_usd_blue`. Reconstruir a posteriori con qué dólar se calculó una foto vieja **no es posible** con lo que hay en la tabla.
