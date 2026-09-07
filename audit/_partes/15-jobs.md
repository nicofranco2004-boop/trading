## Jobs, tareas programadas, alertas y procesos en segundo plano

Auditoría sobre `origin/main` (commit `b74f450f`, 2026-09-05). Todo lo marcado `[V]` está verificado leyendo el código con la cita al lado; `[I]` es inferencia mía y digo de qué me agarré.

---

### 15.1 Mapa general: hay TRES mecanismos distintos, y no se solapan del todo

`[V]` En este repo conviven tres formas de que corra trabajo sin que un usuario lo pida, y hay que separarlas porque fallan distinto:

| Mecanismo | Dónde vive | Qué lo dispara | Sobrevive a un restart |
|---|---|---|---|
| **Scheduler in-process (APScheduler)** | `backend/main.py:32095` + `backend/main.py:32524-32584` | El propio proceso web de uvicorn | No — si el proceso está caído/frío a la hora exacta, la corrida se saltea |
| **Crons EXTERNOS por HTTP** | 4 endpoints `run-cron` / `evaluate` en `backend/main.py` | cron-job.org / UptimeRobot (fuera del repo) | Sí, pero **la configuración no está versionada en ningún lado** |
| **Hooks de `@app.on_event("startup")`** | `backend/main.py:32097-32584` (8 hooks) | Cada arranque del proceso (o sea, cada deploy de Railway) | Corren de nuevo en cada boot |

`[V]` Los imports del scheduler están en `backend/main.py:77-78`:

```
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
```

`[V]` La dependencia está pinneada: `apscheduler==3.10.4` (`backend/requirements.txt`).

---

### 15.2 Inventario de jobs del scheduler in-process

`[V]` El scheduler se crea con **timezone UTC explícito** (`backend/main.py:32095`):

```python
_scheduler = BackgroundScheduler(timezone='UTC')
```

y arranca dentro de `_start_scheduler()` (`backend/main.py:32524-32584`). Los cinco jobs, con cron exacto:

| id | Función | Definido en | Cron (UTC) | Equivalente ART (UTC-3) | Qué hace | Qué escribe |
|---|---|---|---|---|---|---|
| `daily_snapshot` | `_run_daily_snapshot_job` | `backend/main.py:32534-32540` (`CronTrigger(hour=2, minute=59)`) | 02:59 | 23:59 del día anterior | Snapshot de cartera de TODOS los usuarios | `snapshots`, `fx_rates_daily`, `asset_last_price` |
| `iol_lab_refresh` | `_iol_lab_refresh_job` | `backend/main.py:32542-32547` (`CronTrigger(minute=7)`) | **cada hora al minuto :07** | ídem | Renueva refresh tokens del IOL Lab | `user_broker_credentials`, `iol_lab_token_log` |
| `subscription_lifecycle` | `_run_subscription_lifecycle_job` | `backend/main.py:32551-32557` (`CronTrigger(hour=3, minute=30)`) | 03:30 | 00:30 | Downgrades, trials, recordatorios, borrado de cuentas sin verificar, sync con MP | `users`, `subscriptions`, `email_verification_codes`, `brokers` + manda **emails** |
| `backup_db` | `_run_backup_db_job` | `backend/main.py:32560-32566` (`CronTrigger(hour=3, minute=45)`) | 03:45 | 00:45 | Dump gzip de la SQLite + subida opcional a S3 + prune | `./backups/` en disco + bucket S3 |
| `fci_refresh` | `_run_fci_refresh_job` | `backend/main.py:32569-32574` (`CronTrigger(hour=12, minute=10)`) | 12:10 | 09:10 | Refresca VCP de FCIs desde ArgentinaDatos | `fci_prices` |

`[V]` Los cinco usan `replace_existing=True`, así que un re-registro no duplica.

`[V]` Además, `_start_scheduler` dispara **`_fci_bootstrap_async()`** (`backend/main.py:32576-32579` + `backend/main.py:32507-32522`): un thread daemon que crea las tablas de FCI, seedea el catálogo y hace el primer refresh. Es el que le enseñó al proyecto que producción tiene 60 tablas y no 58 (ver §15.10).

#### Cuánto tardan (pistas del propio código)

`[V]` No hay instrumentación de duración, pero hay tres pistas explícitas:

- `daily_snapshot`: «El job tarda (itera todos los users + fetch de precios), MÁS que el timeout del gateway/cron» (`backend/main.py:33656-33658`). Y hay guarda anti-doble-corrida porque «el job itera TODOS los usuarios (minutos)» (`backend/main.py:33630-33634`).
- `iol_lab_refresh`: «barato (0-3 cuentas)» (`backend/main.py:32541`), «son 1-3 cuentas, un POST cada una» (`backend/main.py:31562`).
- `backup_db`: sin pista; hace `sqlite3.backup` + gzip sobre una base descripta en la doc como de ~933 MB (`MIGRACION_POSTGRES.md`).

#### 🔴 Hallazgo J-1 — El scheduler no tiene ningún job de ALERTAS ni de BRIEF

`[V]` De los 4 endpoints `run-cron`/`evaluate`, **solo el de snapshots y el de IOL Lab tienen respaldo in-process**:

- `daily_snapshot` respalda a `/api/snapshots/run-cron` ✅
- `iol_lab_refresh` respalda a `/api/iol/lab/run-cron` ✅ («Red de respaldo del cron externo», `backend/main.py:31597-31599`)
- `/api/alerts/evaluate` (`backend/main.py:33590`) → **sin respaldo**
- `/api/advisor/brief/run-cron` (`backend/main.py:33936`) → **sin respaldo**

`[I]` Consecuencia: si el cron externo de cron-job.org se cae, se le vence la cuenta, o alguien borra los tokens (que es literalmente el paso 1 del plan de mantenimiento — ver `backend/mantenimiento.py`, sección «LO QUE NO GARANTIZA»: *«No frena los crons EXTERNOS: eso lo hace el paso 1 del día, borrando los tres tokens»*), **las alertas de precio y los briefs del asesor dejan de existir sin ninguna señal**. Nadie recibe un error; simplemente no llega el mail. Me agarro de que no hay `add_job` para ninguno de los dos y de que ambos endpoints devuelven 503 si falta el token.

---

### 15.3 ¿Dónde corre el scheduler? La fragilidad, documentada por el propio repo

`[V]` **Corre in-process, dentro del proceso web de uvicorn.** El comando de arranque es (`nixpacks.toml`, sección `[start]`):

```
. /opt/venv/bin/activate && cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT
```

Sin `--workers`, o sea **un solo proceso**. `[I]` Con un solo worker no hay duplicación de jobs dentro de la misma instancia; me agarro de que uvicorn con `--workers` ausente corre un proceso.

`[V]` `railway.toml` solo declara:

```toml
[deploy]
restartPolicyType = "on_failure"
```

No hay `numReplicas`, ni volumen declarado, ni healthcheck.

#### Lo que dice el propio código sobre la fragilidad

`[V]` Tres lugares distintos la documentan, y uno la trata como hecho consumado:

1. `backend/main.py:32004-32007`: «Si el server se reinicia justo a la hora del cron, se saltea esa corrida (in-process scheduler). Trade-off aceptable para una app personal».
2. `backend/main.py:33651-33655` (docstring del endpoint externo): «disparado por un cron EXTERNO para que no dependa de que el proceso de Railway esté despierto — el scheduler interno se saltea la ventana si el proceso está frío, y ahí la "variación diaria" termina siendo de varios días».
3. `backend/main.py:17812-17815` (endpoint de diagnóstico): «Si el cron no está escribiendo (**ver memoria: APScheduler in-process no es confiable en Railway**), un montón de cuentas pasan de ver un número malo a ver "—"».

`[V]` El respaldo elegido fue el cron externo HTTP: `/api/snapshots/run-cron` (`backend/main.py:33647`), que «Lo pega un cron externo (cron-job.org) 1x/día ~03:00 UTC» (`backend/main.py:33662`).

#### 🔴 Hallazgo J-2 — Con 2+ réplicas, TODOS los jobs se duplican

`[I]` No hay ningún lock distribuido, ni tabla de leader-election, ni `SELECT ... FOR UPDATE` que decida quién corre. El único lock que existe es `_snapshot_cron_lock` (`backend/main.py:33634`), que es un `threading.Lock()` **in-memory, por proceso**. Me agarro de eso y de que el mismo patrón se repite en `_brief_cron_lock` (`backend/main.py:33681`) y `_iol_lab_runs_lock`. Si Railway levanta 2 réplicas:

- Se mandan **dos backups** al mismo key de S3 (idempotente por nombre de día, así que se pisa — daño bajo).
- Se corre **dos veces `run_lifecycle_job`**, que manda emails. La idempotencia ahí depende de columnas tipo `expiration_reminder_sent_at` (`backend/billing/subscriptions.py:337-...`), o sea de un check-then-act sin transacción → **carrera posible de mail doble**.
- Se corren **dos snapshots** simultáneos sobre la misma SQLite de un solo escritor.

`[V]` El mismo problema está reconocido para el rate limiting: «Per-process. Para multi-worker o multi-host conviene migrar a Redis» (`backend/main.py:306-307`). El scheduler tiene exactamente la misma forma y **no** tiene ese comentario.

#### ⚠️ Hallazgo J-3 — La marca de que el cron corrió no existe

`[I]` No hay ninguna tabla `job_runs` ni columna de «última corrida OK» para los jobs del scheduler. La única evidencia de que el snapshot corrió es la fila en `snapshots` con `source='cron'`, y la única evidencia de que el backup corrió es el log. Me agarro de que grepeé todo `main.py` por `add_job` y por el resultado del job y solo encontré `_snapshot_log.info(f"Daily snapshot result: {result}")` (`backend/main.py:32045`). Eso significa que «¿corrió anoche el cron?» solo se contesta mirando logs de Railway o consultando la base a mano.

---

### 15.4 Crons externos (HTTP): los cuatro endpoints

`[V]` Los cuatro comparten el mismo patrón de auth: header `X-Cron-Token` **o** query param `?token=`, comparado contra una env var. **Sin la env var configurada devuelven 503** (fail-closed).

| Endpoint | Línea | Env var del token | Cadencia documentada | Sincrónico o thread | Guarda anti-doble |
|---|---|---|---|---|---|
| `GET/POST /api/snapshots/run-cron` | `backend/main.py:33647` | `SNAPSHOT_CRON_TOKEN` | 1×/día ~03:00 UTC | **Thread** (`backend/main.py:33677`), devuelve `{"status":"started"}` | Sí — `_snapshot_cron_lock` + flag global (`backend/main.py:33670-33676`) |
| `GET/POST /api/alerts/evaluate` | `backend/main.py:33590` | `ALERTS_CRON_TOKEN` | cada ~10 min | **Sincrónico** | **No** |
| `GET/POST /api/advisor/brief/run-cron` | `backend/main.py:33936` | `ADVISOR_BRIEF_TOKEN` (fallback: `SNAPSHOT_CRON_TOKEN`) | 2×/día hábil (`kind=open` ~11:00 ART, `kind=close` ~17:15 ART) | **Thread** (`backend/main.py:33975`) | Sí — `_brief_cron_lock` por `kind` (`backend/main.py:33959-33963`) |
| `GET/POST /api/iol/lab/run-cron` | `backend/main.py:31559` | `IOL_LAB_CRON_TOKEN` | cada hora | **Sincrónico** («son 1-3 cuentas») | **No** |

`[V]` Detalle relevante del token por query param: el docstring de `backend/mantenimiento.py` explica que para el bypass de mantenimiento se eligió header y NO query param «porque un token en la URL queda en los logs del proxy, en el historial del navegador y en el `Referer`». `[V]` Los cuatro crons **aceptan igual el `?token=`** (`backend/main.py:33600-33601`, `:33668-33669`, `:33951-33952`, `:31567`). `[I]` O sea: el criterio de seguridad que se aplicó al bypass de mantenimiento no se aplicó a los tokens de cron, que valen lo mismo (disparan trabajo global sobre todos los usuarios). Además la comparación es `!=` de strings, no `hmac.compare_digest` como en `bypass_valido` (`backend/mantenimiento.py:112`).

#### 🔴 Hallazgo J-4 — Ninguno de estos tokens está en `.env.example`

`[V]` Los nombres declarados en `backend/.env.example` son: `ADMIN_EMAIL_HASH`, `ANTHROPIC_API_KEY`, `EMAIL_FROM`, `EMAIL_FROM_NOREPLY`, `EMAIL_FROM_SUPPORT`, `IOL_LAB_CRON_TOKEN`, `IOL_LAB_EMAILS`, `MP_*`, `REBILL_*`, `RESEND_API_KEY`, `SECRET_KEY`, `VAPID_*`.

Faltan: **`SNAPSHOT_CRON_TOKEN`, `ALERTS_CRON_TOKEN`, `ADVISOR_BRIEF_TOKEN`**, y todo el bloque `BACKUP_S3_*` / `BACKUP_LOCAL_*` (documentado aparte en `backend/scripts/BACKUP_SETUP.md`), y también `RENDI_MANTENIMIENTO*`, `RENDI_RESET_DATA_ENABLED`, `RENDI_FORCE_SNAPSHOT_MIGRATION`, `DATABASE_URL`, `DB_PATH`.

`[I]` Consecuencia: el único inventario de qué crons hay que dar de alta vive en los docstrings y en la cabeza del founder. Nada en el repo dice «estos son los 4 jobs de cron-job.org y estos sus horarios». Me agarro de haber grepeado `cron-job.org` en todo el repo: solo aparece en docstrings de `backend/main.py` y en `PLAN_iol_sync.md`.

#### ⚠️ Hallazgo J-5 — El `/api/health` documenta un horario que ya no existe

`[V]` `backend/main.py:34274-34276`: «Configurá un cron en cron-job.org que pingue esta URL ~5 min antes del horario del daily snapshot (**01:00 UTC**) y la app se levanta antes». `[V]` El cron real es 02:59 UTC (`backend/main.py:32536`). El bloque de comentario de `backend/main.py:32001-32002` también quedó con «Schedule: 01:00 UTC = 22:00 ART», contradiciendo al comentario de 30 líneas más abajo (`backend/main.py:32525-32533`) que explica el cambio a 02:59. `[I]` Si el ping de despertar está configurado a las 00:55 UTC, la app puede volver a estar dormida a las 02:59 — que es justo el modo de falla que ese ping intentaba prevenir.

---

### 15.5 `snapshots_job.py` (1049 líneas)

#### Qué es un snapshot

`[V]` Es la **foto diaria del valor de la cartera de un usuario**, valuada server-side, sin necesidad de que el usuario abra la app. Docstring de `backend/snapshots_job.py:1-15`: «Resuelve el gap actual donde los snapshots solo se crean cuando el usuario visita el Dashboard».

#### Qué campos guarda

`[V]` El UPSERT está en `backend/snapshots_job.py:775-800`:

```sql
INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited,
                       fx_to_usd_blue, holdings_json, source, base, apto)
VALUES (?, ?, ?, ?, ?, ?, ?, 'cron', 'mercado', 1)
ON CONFLICT(user_id, date) DO UPDATE SET ...
```

| Campo | Contenido | Definido en |
|---|---|---|
| `total_value` | Valor USD de toda la cartera (holdings + cash), suma por broker | `backend/snapshots_job.py:744-762` |
| `total_invested` | Cost basis | ídem |
| `net_deposited` | Σ depósitos − Σ retiros, desde `monthly_entries` | `backend/snapshots_job.py:764` + `compute_net_deposited` (`:388`) |
| `fx_to_usd_blue` | El **blue**, solo para display de la curva en ARS | `backend/snapshots_job.py:768-770` |
| `holdings_json` | `[{asset, value_usd}]` — foto por activo, para atribución MtM | `backend/snapshots_job.py:762-763` |
| `source` | Fijo `'cron'` | `backend/snapshots_job.py:780` |
| `base` | Fijo `'mercado'` | ídem |
| `apto` | Fijo `1` (sirve de pico y de denominador) | ídem |

`[V]` La tabla y sus columnas se crean/migran en `backend/main.py:1367-1476`. `mtm_coverage` la escribe **solo** el backfill histórico (`backend/main.py:1409-1412`): una fila del cron la deja en NULL por construcción.

`[V]` **Un cierre del cron pisa una foto intradía del browser** (`backend/snapshots_job.py:791-796`: `source = 'cron'`, `base = 'mercado'`, `apto = 1` en el `DO UPDATE`), pero al revés no: el `POST /api/snapshots` del browser tiene un guard explícito en Python que, si ya hay una fila `source='cron'`, **solo actualiza `net_deposited` y `fx_to_usd_blue`** y deja el `total_value` del cron intacto (`backend/main.py:5043-5067`).

#### A qué hora corre

`[V]` 02:59 UTC = 23:59 ART, y el comentario explica el porqué (`backend/main.py:32525-32533`): antes corría 01:00 UTC = 22:00 ART y «capturaba el portfolio 2 horas ANTES de fin del día Argentina».

#### Qué dólar usa

`[V]` **La valuación va TODA al dólar-MEP; el blue es solo un sello de display.** Docstring de `take_snapshot_for_user` (`backend/snapshots_job.py:635-641`): «CONVENCIÓN DE VALUACIÓN: TODO al dólar-MEP (holdings .BA, cash ARS y costos) […] El blue genuino (tc_blue) queda SOLO para el stamp display fx_to_usd_blue».

`[V]` La resolución del MEP la hace el job (no el usuario) vía `_get_mep_for_scheduler` (`backend/main.py:32016-32033`): primero `_current_cedear_rate()` (caché live), y si está frío hace fetch DIRECTO a dolarapi (`bolsa`, después `contadoconliqui`). Si no resuelve, **levanta y el job ABORTA (fail-closed)** — `backend/snapshots_job.py:958-968`. El comentario dice por qué: con caché frío caía a `config.tc_mep` (default 1415) y «TODOS los holdings .BA se valuaban a un rate stale […] snapshot −15% en un día plano + "P&L Día +17%" fantasma a la mañana».

`[V]` El blue también es fail-closed: si `fetch_tc_blue()` falla o da ≤0, el job entero aborta antes de tocar a nadie (`backend/snapshots_job.py:939-949`).

#### Guardas de calidad antes de escribir

`[V]` Hay tres, en orden:

1. **Retry de precios faltantes** — segunda pasada sobre los símbolos sin precio (`backend/snapshots_job.py:684-691`).
2. **Último precio conocido** — `apply_last_known_prices` completa lo que sigue sin precio con el último valor real de `asset_last_price`, «así una posición sin precio hoy queda "igual que ayer" en vez de saltar a su costo» (`backend/snapshots_job.py:693-697` + `:558-620`).
3. **Piso de cobertura del 95%** — `MIN_COVERAGE = 0.95` ponderado por cost basis en USD. Si no llega, **no escribe la fila** y devuelve `{'ok': False, 'reason': 'low_price_coverage'}` (`backend/snapshots_job.py:699-720`). Razón: «Preferimos NO escribir ese día antes que escribir un dato corrupto».

`[V]` También saltea usuarios sin brokers o sin posiciones (`backend/snapshots_job.py:672-676`) y excluye shadows de asesor revocados (`backend/snapshots_job.py:993-1006`) porque «acumulaban un snapshot por noche para siempre (audit)».

#### 🔴 Hallazgo J-6 (el gordo de esta sección) — el cron fecha el snapshot en día UTC, no en día ART, y el código que arregla eso está muerto

`[V]` `take_snapshot_for_user` tiene, en `backend/snapshots_job.py:648-656`, la conversión a día ART:

```python
if target_date is None:
    # Audit follow-up (2026-05-31): fecha del snapshot = día ART, no UTC.
    # Si el cron corre a las 02:59 UTC del sábado (= 23:59 ART del viernes),
    # la fecha debe ser "viernes", no "sábado" ...
    art_dt = datetime.utcnow() - _td(hours=3)
    target_date = art_dt.strftime('%Y-%m-%d')
```

`[V]` Pero el runner **siempre pasa una fecha**, y esa fecha es UTC. `backend/snapshots_job.py:937`:

```python
target = target_date or datetime.utcnow().strftime('%Y-%m-%d')
```

y `backend/snapshots_job.py:1021-1022` la pasa como 5º argumento posicional (que es `target_date`):

```python
result = take_snapshot_for_user(conn, uid, tc_blue, crypto_yf, target, tc_mep=tc_mep)
```

`[V]` El único caller de producción es `_run_daily_snapshot_job` (`backend/main.py:32036-32047`), que **no pasa `target_date`**. Lo mismo el endpoint admin `/api/admin/snapshots/run-now` (`backend/main.py:34259-34264`) y el cron externo (`backend/main.py:33641`).

`[V]` Corriendo a las 02:59 UTC, `datetime.utcnow().date()` es el día **siguiente** al día ART que se está midiendo. O sea: **la rama ART de `take_snapshot_for_user` nunca se ejecuta desde el cron**, y el cierre del viernes queda fechado sábado.

`[V]` Esto además es **asimétrico con el otro escritor de la misma serie**: el `POST /api/snapshots` del browser usa `_iso_today()`, que sí resta 3 horas (`backend/main.py:27750-27756`, y el comentario en `backend/main.py:5017-5019`: «Día ART, no UTC: después de las 21:00 de acá ya es "mañana" en UTC y el snapshot quedaba fechado un día adelante, pisando al del cierre real»). **Los dos escritores de `snapshots` usan calendarios distintos.**

`[V]` Los tests no lo cubren: las cuatro invocaciones de `run_daily_snapshot` en `backend/tests/test_snapshots_job.py` pasan `target_date` explícito (`:407, :443, :457, :552`), así que la rama nunca se ejercita.

`[I]` Consecuencias que se siguen de esto (me agarro del guard de `post_snapshot` en `backend/main.py:5058-5067`):
- El día calendario ART **D no tiene fila del cron**; la tiene el día D+1, con los precios del cierre de D.
- Como la fila de D+1 ya nace con `source='cron'`, el browser **no puede escribir su foto intradía de D+1**: solo le actualiza `net_deposited` y el fx. Toda la jornada D+1 el usuario ve, en la fila fechada D+1, el valor del cierre de D.
- El `fx_rates_daily` del día también queda estampado con la fecha UTC (`backend/snapshots_job.py:983-995` usa `target`), o sea el blue del cierre de D queda guardado bajo la fecha D+1.

Nota: esto no rompe una diferencia día-a-día (el corrimiento es constante), pero sí rompe cualquier lectura que ancle en una fecha concreta —arranque de mes, cierre de año, `date <= when`— y explica por qué una fila puede parecer «de hoy» siendo de ayer.

#### Qué pasa si un día NO corrió

`[V]` **No hay relleno de huecos. El hueco queda.** No existe ninguna función que detecte fechas faltantes y las reconstruya para el cron; lo verifiqué grepeando: el único mecanismo que fabrica filas retroactivas es `scripts/backfill_historical_mtm.py`, que escribe con `source='mtm_backfill'`, solo meses **cerrados**, y solo para cuentas con import confirmado (§15.8).

`[V]` Lo que sí hay es **tolerancia al hueco en la lectura**: `fetch_snapshot_at_or_before` (`backend/reporting/builder.py:296-330`) toma «el último snapshot con `date <= when`». O sea, un día sin foto se «rellena» hacia atrás con la última que haya.

`[V]` Y hay un lugar donde el hueco fue tan real que hubo que poner una **cota dura**: en las alertas del libro del asesor (`backend/advisor_alerts.py:240-244`):

> «La base tiene que ser un cierre RECIENTE: sin cota, **un cliente con el cron frenado** (o recién importado, con un snapshot sintético al costo) se comparaba contra semanas atrás y el "% del día" era un invento (audit). 4 días cubre un finde largo.»

`[I]` O sea: el propio repo ya midió que el cron se frena y que, sin cota, el gap se convierte en un número inventado que **se manda por mail**.

#### Cómo afecta a la «variación diaria» que ve el usuario

Hay que separar dos variaciones distintas, porque no salen del mismo lado:

`[V]` **(a) Variación diaria POR POSICIÓN (la tabla de Cartera)** — NO usa snapshots. Sale de `GET /api/prices/prev-close` (`backend/main.py:33865-33879`), que compara el precio actual contra el cierre del día hábil anterior por símbolo. Un hueco de snapshots no la toca.

`[V]` **(b) Variación / P&L de PERÍODO (Dashboard, Reportes, chips de 1/7/30 días)** — sale de la serie de `snapshots`, y ahí el hueco sí pega. Los mecanismos que lo amortiguan:
- `fetch_snapshot_at_or_before` (carry-forward hacia atrás).
- El guard que exige que el borde del período sea una MEDICION real (`mtm_only=True`, `backend/reporting/builder.py:303-313`) — cuando no lo hay, el número **no se publica** (se muestra «—»). Eso está explicado en el endpoint de diagnóstico `admin_diagnose_reportes_basis` (`backend/main.py:17808-17817`): si el cron no escribe, «un montón de cuentas pasan de ver un número malo a ver "—"».

`[I]` Traducido: un día sin cron no le muestra al usuario una variación mal calculada, le muestra un guion o una variación acumulada de varios días. El propio docstring del cron externo lo dice: «ahí la "variación diaria" termina siendo de varios días» (`backend/main.py:33654-33655`).

`[V]` Y el otro camino de degradación está tapado: la posición sin precio no cae más a cost basis, cae al último precio conocido (`backend/snapshots_job.py:558-562`) — «lo que inventa un salto fantasma en la variación diaria».

---

### 15.6 `alerts_engine.py` — alertas de precio y de variación

#### Tipos de alerta

`[V]` Dos `kind` (`backend/alerts_engine.py:27`, `VALID_KINDS = ("price_target", "pct_move")`), y el schema en `backend/main.py:1657-1681`:

| Tipo | Qué mira | Campos que usa |
|---|---|---|
| `price_target` | El precio cruza un umbral | `symbol`, `direction` (`above`/`below`), `threshold`, `currency` |
| `pct_move` | El activo se mueve X% | `up_pct`, `down_pct` (asimétricos, en la MISMA alerta), `baseline` (`prev_close` = «en el día», `set_price` = «desde ahora»), `anchor_price` |

`[V]` Cada una tiene además `scope` (`ticker` = un símbolo; `holdings` = **todas** las tenencias del usuario, `backend/alerts_engine.py:176-186`), `channel` (`push`/`email`/`both`), `repeat` (`once`/`daily`/`always`) y `cooldown_min` (default 360).

`[V]` Y hay un **tercer motor**, el del libro del asesor (`backend/advisor_alerts.py`), que mira la CARTERA COMPLETA de cada cliente en vez de un activo. Se evalúa en el **mismo ciclo** que las de precio (`backend/main.py:33619-33625`), «así el asesor no tiene que dar de alta ningún cron nuevo».

#### Cómo se evalúan

`[V]` `evaluate_alerts(conn, only_user=None)` (`backend/alerts_engine.py:332-461`):

1. Levanta todas las `alerts WHERE active=1`.
2. Expande a unidades `(alerta, símbolo)`; para `scope='holdings'` usa `build_price_symbols` del snapshot job — «Reusa build_price_symbols para no divergir de la valuación» (`backend/alerts_engine.py:69-84`).
3. Separa en dos buckets según qué dato necesita cada una: `_prices_for` (mismo resolver que el snapshot, `backend/alerts_engine.py:36-49`) o `_quotes_for` (`change_pct` vs cierre previo, vía `home.market._fetch_batch_quotes`, `backend/alerts_engine.py:52-62`).
4. Evalúa unidad por unidad.
5. Al final: `UPDATE alerts SET last_evaluated_at=?` + `conn.commit()`.

`[V]` **Ventana de mercado**: `_market_open_now(now)` (`backend/alerts_engine.py:113-120`) es «L-V, ~13:00–21:00 UTC (cubre US 9:30–16 ET + BYMA 11–17 ART)». Fuera de esa ventana **solo dispara cripto** (`tradeable = (sym in _crypto_symbols()) or market_open`, `backend/alerts_engine.py:381`). Razón: «así no saltan de madrugada/finde sobre el `change_pct` congelado del último cierre».

`[V]` **Nunca dispara sin precio**: `condition_met` devuelve `None` si `price is None` y el loop hace `continue` — «sin precio → no adivinar» (`backend/alerts_engine.py:384-387`).

`[V]` **Normalización cripto**: `_norm_sym` traduce `BTC.BA` → `BTC` porque «cripto en broker AR se representa como 'BTC.BA' […] pero NO cotiza así en yfinance» (`backend/alerts_engine.py:99-109`).

#### Cada cuánto

`[V]` **Cada ~10 minutos, y solo por cron externo**: `/api/alerts/evaluate` (`backend/main.py:33590-33596`). No hay job in-process (hallazgo J-1). El docstring aclara que «el mismo ping despierta la app en Railway».

`[V]` El endpoint envuelve cada motor en su propio `try` porque «una excepción en las alertas de PRECIO tiraba 500 y las del LIBRO no se evaluaban en esa corrida, sin log propio ni señal de que habían quedado sin correr» (`backend/main.py:33607-33625`).

#### Cómo se notifica

`[V]` `_deliver` (`backend/alerts_engine.py:263-297`) manda **push (Web Push VAPID) y/o email (Resend)** según `channel`:
- Push: `main._send_push_to_user(uid, {...})` con `tag: f"alert-{alert['id']}-{symbol or ''}"`.
- Email: `billing.emails.send_alert_email(...)`.

`[V]` **Redirección al asesor**: `_delivery_target` (`backend/alerts_engine.py:246-261`) — si la cuenta es un shadow administrado (`users.managed_by`), la alerta le llega **al asesor**, no al shadow, «el shadow no tiene devices de push ni un email real (@shadow.rendi.internal, casilla muerta)». El mensaje se prefija con `[{label del cliente}]`.

#### `alert_symbol_state`: qué es y para qué

`[V]` Tabla `(alert_id, symbol, armed, last_fired_date, updated_at)` con PK compuesta (`backend/main.py:1698-1711`). Es el **estado de edge-trigger POR PAR (alerta, símbolo)**. Existe porque una alerta `scope='holdings'` cubre N símbolos y la columna `alerts.armed` (una sola) no alcanza:

> «Edge-trigger POR (alerta, símbolo) para pct_move "En el día": una alerta de toda la cartera tiene N símbolos, cada uno con su propio estado armado.» (`backend/main.py:1698-1701`)

`[V]` Se manipula con `_sym_state` / `_set_sym_armed` / `_set_sym_fired` (`backend/alerts_engine.py:168-199`). Se borra en cascada al borrar la alerta (`backend/main.py:33572`).

#### Cómo se evita repetir la misma alerta — hay TRES mecanismos distintos

`[V]`

| Caso | Mecanismo | Dónde |
|---|---|---|
| `price_target` | **Edge-trigger global** con `alerts.armed`: dispara solo en la transición no-cumplida→cumplida; se re-arma cuando el precio vuelve del otro lado (a cualquier hora) | `backend/alerts_engine.py:383-395` |
| `pct_move` con `baseline='set_price'` («desde ahora») | **Re-ancla**: tras disparar, si `repeat != 'once'`, `anchor_price` se mueve al precio actual → «avisar CADA X%» | `backend/alerts_engine.py:415-427` |
| `pct_move` con `baseline='prev_close'` («en el día») | **Edge-trigger por símbolo + tope de 1 aviso por día UTC**: `alert_symbol_state.armed` + `last_fired_date`; **no se re-arma el mismo día que disparó** | `backend/alerts_engine.py:428-455` |

`[V]` Y transversal: `repeat='once'` apaga la alerta entera (`active=0`) y la mete en el set `deactivated` para que no vuelva a disparar en el MISMO ciclo (`backend/alerts_engine.py:378-380, 424-426, 452-455`).

#### ⚠️ Hallazgo J-7 — `_recently_fired` y `cooldown_min` son código muerto

`[V]` `_recently_fired(conn, alert_id, symbol, cooldown_min, now)` está definida en `backend/alerts_engine.py:152-165`, con su docstring («¿Ya disparó esta (alerta, símbolo) dentro del cooldown? (para pct_move)»)… y **no la llama nadie**. Grepeado en todo `backend/`: las únicas apariciones son la definición misma y menciones de `cooldown` en el schema, el modelo Pydantic y los tests.

`[V]` La columna `alerts.cooldown_min INTEGER NOT NULL DEFAULT 360` existe (`backend/main.py:1673`), se acepta y valida en la API (`backend/main.py:33347`, `:33400`, `:33507`, `:33532`) y se persiste — pero **el motor nunca la lee**. El docstring del módulo ya lo dice a medias: «el anti-spam es por COOLDOWN por (alerta, símbolo) vía la tabla alert_events» (`backend/alerts_engine.py:11-13`), pero eso describe una implementación anterior; la actual usa `alert_symbol_state`.

`[I]` O sea: hay un campo de configuración que el usuario puede setear en la UI (validado `ge=0, le=100000`) y que **no cambia absolutamente nada**. Me agarro de que el único lector posible era `_recently_fired`, que no tiene call site.

#### ⚠️ Hallazgo J-8 — `alert_events` crece para siempre

`[V]` `alert_events` solo se borra cuando se borra la alerta que lo generó (`backend/main.py:33570-33571`). No hay purga por antigüedad. Contraste directo: las del asesor **sí** se purgan — `advisor_alerts.purge_old(conn, days=3)` corre en cada evaluación (`backend/advisor_alerts.py:91-97`, llamado en `:180`) porque «el historial es un feed, no un archivo». La misma decisión no se tomó para `alert_events`.

#### ⚠️ Hallazgo J-9 — Dos cleanups documentados que no existen

`[V]` En `backend/main.py:1955`: «`-- Cleanup: cron diario borra rows > 7 días.`» para `yfinance_cache`. **No existe.** El único `DELETE FROM yfinance_cache` del repo (`backend/main.py:2666-2670`) es una purga de arranque acotada a `ticker LIKE '%.BA' AND kind IN ('fundamentals','analysts')` — otra cosa, y corre en cada boot, no en un cron.

`[V]` En `backend/main.py:2093`: «`-- Cleanup en cron de codes > 30 días.`» para `email_verification_codes`. **No existe.** El único `DELETE FROM email_verification_codes` (`backend/billing/subscriptions.py:377`) es la cascada al borrar una cuenta sin verificar, no una purga por edad.

`[I]` Ambas tablas crecen monótonamente. Peso bajo por fila, pero en una base que ya es el cuello de botella (SQLite de un solo escritor, ~933 MB) el comentario que promete una limpieza que nadie hace es exactamente la clase de premisa falsa contra la que el repo se advierte a sí mismo en otros lados.

---

### 15.7 Trabajo disparado por REQUEST: threads, executors y `BackgroundTasks`

#### `BackgroundTasks` de FastAPI: hay UNO solo

`[V]` La única inyección es en `register` (`backend/main.py:3097`) y el único `add_task` es `backend/main.py:3159` — el envío asíncrono del mail de verificación (worker en `backend/main.py:5930-5946`). Riesgo bajo: corre después de devolver la response, y su excepción se loguea.

#### `threading.Thread` disparados por request

| Qué | Dónde se lanza | Riesgo |
|---|---|---|
| **Reset de datos del usuario** | `backend/main.py:3802` (`name=f"reset-{uid}"`) | **⛔ El endpoint está DESACTIVADO** (`RENDI_RESET_DATA_ENABLED != "1"` → 503, `backend/main.py:3790-3795`). Motivo documentado en `backend/main.py:3779-3789`: no es un bug del reset, es que la SQLite single-writer «desborda» y «`database is locked` NO le aparece al que resetea: le aparece a TODOS» |
| **Reconstrucción MtM post-import** | `backend/main.py:30726-30729` (`name=f"mtm-backfill-{uid}"`) | Sale a yfinance con `timeout=8` **por ticker** → «una cartera de 20 símbolos puede tardar minutos». Corre con el import ya commiteado y en su propia conexión, así que si muere no arrastra al import |
| **IOL Lab probe** | `backend/main.py:31526` | Login + probe read-only contra IOL, con guard `_iol_lab_running` por uid (409 si ya hay uno) |
| **Snapshot por cron externo** | `backend/main.py:33677` | Con lock + flag global anti-doble-corrida |
| **Brief del asesor por cron externo** | `backend/main.py:33975` | Con lock por `kind` — «dos pings solapados mandaban el mail dos veces (el log es check-then-act)» (`backend/main.py:33680-33682`) |
| **Refresh de eventos (stale-while-revalidate)** | `backend/main.py:6755` | Abre su propia conexión; se dispara desde el path de lectura de eventos |
| **Refresh de noticias (stale-while-revalidate)** | `backend/main.py:6755` (`_refresh_news_in_background`, `:6742-6755`) | Idem |

`[I]` **Riesgo transversal de todos estos threads: son `daemon=True` sin excepción.** Verificado grepeando: los 12 `threading.Thread(...)` de `main.py` llevan `daemon=True`. En un redeploy de Railway el proceso muere y **el thread se corta a mitad**. Para el MtM eso es tolerable (escribe con `conn.commit()` al final y hace rollback si falla), pero para el reset de datos por tandas significaría dejar la cuenta a medio borrar — otra razón más para que esté apagado.

#### `ThreadPoolExecutor`: cuatro pools globales

`[V]`

| Pool | Línea | Workers | Para qué |
|---|---|---|---|
| `_bench_fetch_executor` | `backend/main.py:5212` | 4 | Fetch de benchmarks |
| `_news_fetch_executor` | `backend/main.py:6805` | 16 | Fetch paralelo de feeds de noticias |
| `_yf_executor` | `backend/main.py:21013` | 8 | Fetch de yfinance, con `BoundedSemaphore(8)` al lado y timeout de 10s |
| `_TRADE_PRICE_POOL` | `backend/main.py:23427-23428` | 2 | Precio de mercado al registrar un trade por chat, `timeout=8` |

`[V]` El de yfinance tiene un comentario que vale citar entero (`backend/main.py:21004-21013`): la primera implementación usaba `with ThreadPoolExecutor(...)`, que **bloquea en `__exit__` esperando al thread colgado**, anulando el timeout. La solución fue un pool global que nunca se cierra: «El thread que timea queda en bg, lo dejamos morir naturalmente».

`[I]` Los pools son globales de módulo y **no se cierran nunca** (ni en el hook de shutdown). Con `restartPolicyType = "on_failure"` y un solo proceso eso es intencional y benigno, pero un thread colgado en yfinance queda ocupando un slot del semáforo hasta que el proceso muera.

#### El buffer de últimos precios (escritura diferida)

`[V]` `backend/main.py:7481-7532`: `/api/prices` **escribía en cada llamada**, y el comentario lo llama por su nombre: «el volumen de escritura de Rendi escalaba con las VISITAS, no con las operaciones de la gente. Diez personas mirando su cartera generaban más escrituras que diez cargando movimientos».

`[V]` Ahora se acumula en `_last_price_buf` (dict + `threading.Lock`) y baja a disco como mucho **1 vez por minuto** (`_LAST_PRICE_FLUSH_S = 60`), en una sola transacción. Si la bajada falla, los precios **vuelven al buffer** (`backend/main.py:7527-7532`).

`[V]` Y hay un flush forzado en el `@app.on_event("shutdown")` (`backend/main.py:32595-32602`): «Railway redeploya seguido; sin esto, cada deploy tira hasta un minuto de últimos-precios».

`[I]` Es un buffer **in-memory por proceso**. Con múltiples réplicas cada una tendría el suyo y bajarían pisándose (aunque el UPSERT los hace convergentes). Y ante un `SIGKILL` (no un shutdown limpio) se pierde hasta un minuto de precios.

---

### 15.8 Hooks de `@app.on_event("startup")` — ocho, y todos escriben

`[V]` Ocho hooks de startup + uno de shutdown. Todos menos dos lanzan un `threading.Thread(daemon=True)` con un `sleep` escalonado, para no bloquear el boot:

| # | Hook | Línea | Sleep | Qué hace | Idempotente / se marca |
|---|---|---|---|---|---|
| 1 | `_backfill_fx_rates_on_boot` | `backend/main.py:32097-32116` | 0s | Si `fx_rates_daily` está vacía, pull de ~5 años de blue desde argentinadatos + relleno de MEP faltante | Sí — `if cnt > 0: return` (`backend/main.py:4718-4719`) |
| 2 | `_validate_rebill_config` | `backend/main.py:32119-32142` | — | Solo loguea. No escribe | N/A |
| 3 | `_prewarm_news_cache` | `backend/main.py:32145-32163` | 3s | Pre-fetch de noticias de mercado | Por TTL |
| 4 | `_migrate_estampar_base` | `backend/main.py:32166-32247` | 5s | Estampa `snapshots.base` / `snapshots.apto` en filas NULL | Sí (`solo_faltantes=True`), **con reintentos** ante lock |
| 5 | `_migrate_snapshots_netdep` | `backend/main.py:32249-32419` | 5s | Repara `net_deposited` corrupto + borra snapshots V-shape + resync `pnl_realized` | Sí, **y se marca hecha** (`migr_snapshots_netdep_v1` en `config`), forzable con `RENDI_FORCE_SNAPSHOT_MIGRATION=1` |
| 6 | `_migrate_fci_ticker_remap` | `backend/main.py:32421-32446` | 6s | Remapea tickers crudos de FCI (COCOA, CONIOLA…) al símbolo de catálogo | Sí (tras remap el ticker crudo ya no existe) |
| 7 | `_migrate_fx_gross_usd` | `backend/main.py:32469-32490` | 8s | Re-estampa `gross_amount_usd` de conversiones FX | Sí |
| 8 | `_start_scheduler` | `backend/main.py:32524-32584` | — | Registra los 5 jobs + FCI bootstrap async | `replace_existing=True` |

`[V]` **El hook #4 es el que más enseña.** Su docstring (`backend/main.py:32167-32191`) documenta dos lecciones de este repo:

> «⚠️ ESTE HOOK ES LA MITAD DEL FIX. Este repo ya tuvo un backfill que "corría en un thread daemon al startup" y ese thread **no existía** (`backfill_source_legacy`, ver el comentario largo en twr.py): **un backfill sin call-site es peor que no tenerlo**, porque instala la premisa falsa de que producción está materializada.»
>
> «⚠️ NO HAY endpoint de admin para forzarlo. El docstring decía que sí y era falso —enumeradas las 252 rutas de `app.routes`, ninguna estampa—.»

`[V]` Y explica por qué necesita reintentos (`backend/main.py:32202-32222`): basta con que otro escritor retenga el lock más que el `busy_timeout=15000` justo en boot+5s para que tire `database is locked`, se trague la excepción y las 40.717 filas queden en NULL. Y **no se reintenta nunca** porque `railway.toml` usa `restartPolicyType = "on_failure"`, así que el proceso sigue vivo. El impacto medido, textual: «169 alertas de drawdown con 81 picos `sintetico_costo` (peor caso −492.864%) contra 95 alertas y 0 picos contables una vez estampado. **Y esas alertas van POR MAIL.**»

`[V]` El hook #5 tiene el otro comentario de oro (`backend/main.py:32338-32354`): antes hacía **un solo commit al final** del loop de ~500 usuarios, o sea «el lock de escritura de SQLite tomado MINUTOS». Medido en producción el 2026-08-10: un usuario no pudo cancelar su suscripción. La solución fue commitear **por usuario**.

#### ⚠️ Hallazgo J-10 — Seis escritores compiten en cada boot y el propio repo los cuenta

`[V]` `backend/mantenimiento.py`, sección «LO QUE NO GARANTIZA»: «No frena **los seis escritores del arranque** (punto 0b del plan), que siguen siendo un problema aparte y **abierto**.»

`[I]` Contándolos en el código: los hooks 1, 4, 5, 6, 7 escriben a la base, más el FCI bootstrap del hook 8 = seis. Todos arrancan dentro de los primeros 8 segundos del boot, todos contra una SQLite de un solo escritor, y **solo uno (el #4) usa `_run_with_lock_retry`** (`backend/main.py:509-517`). Los otros cinco se tragan la excepción con `log.warning` y no vuelven a intentar hasta el próximo deploy.

---

### 15.9 Backfills — qué recompute cada uno, qué pisa, si es idempotente

`[V]` Hay **cuatro** backfills en `backend/scripts/`, y tres tienen doble puerta (CLI + endpoint admin). Todos tienen dry-run **sobre una COPIA del DB** (`_clone_db`, `backend/importing/recompute_backfill.py:74`), así que el dry-run nunca toca la base real.

| Script | Motor | Endpoint admin | Qué recomputa | Qué PISA | Idempotente | Automático |
|---|---|---|---|---|---|---|
| `backfill_recompute_positions.py` | `importing/recompute_backfill.py` | `POST /api/admin/backfill-recompute` (`backend/main.py:15818`) | Re-corre la secuencia post-import (rebuild FIFO por batch → sweep letras → sweep amortización → recalc) | `positions`, `operations` | Sí — «el rebuild es idempotente, NO toca cash y saltea cuentas con posiciones manuales» | **No**, a mano |
| `backfill_historical_mtm.py` | él mismo | `POST /api/admin/backfill-mtm` (`backend/main.py:15889`) | Valuación a MERCADO de meses CERRADOS | **Solo** `snapshots` con `source='mtm_backfill'` | Sí — «El primer término se RECOMPUTA de columnas estables cada corrida» | **SÍ, ver abajo** |
| `backfill_currency_fix.py` | él mismo | `POST /api/admin/backfill-currency` (`backend/main.py:15933`) | Corrige moneda envenenada (pesos contados como USD) en `import_normalized_tx` + re-rebuild | `import_normalized_tx` in-place | Sí — «re-correr no vuelve a tocar lo ya en ARS» | **No** |
| `backfill_bond_amortizations.py` | `importing/maturity.sweep_bond_amortizations` | — (solo CLI) | Aplica residual de amortización a bonos ya importados | Lotes import-linked de `positions` | Sí — «target recalculado desde los movimientos importados, estable» | **No** |

`[V]` Los tres endpoints admin procesan **por tandas** (`offset`/`limit`) «para que ningún request sea largo (clonar+recomputar a todos juntos timeout-eaba)» (`backend/main.py:15841-15843`).

#### `backfill_historical_mtm.py` en detalle

`[V]` Docstring (`backend/scripts/backfill_historical_mtm.py:1-44`). El problema que resuelve: «una cuenta importada nunca capturó el mark-to-market NO REALIZADO de los meses pasados […] el CAGR sale bajísimo (p.ej. +2.84% vs +22.43% del broker)».

`[V]` La regla cardinal, textual: «**si falta precio/FX/historia o hay split → AL COSTO (jamás infla)**».

`[V]` Lo que NO toca: «positions, operations, cash, import_normalized_tx NI monthly_entries». Y el porqué de esa última exclusión es interesante: «Escribir en `monthly_entries.capital_final` era inútil: para todo mes cerrado `_repair_monthly_chain` (main.py:9314-9318) lo recomputa al costo y se dispara desde ~20 lugares de main.py, así que el ancla se borraba sola».

`[V]` FX que usa: «BLUE de `fx_rates_daily` (último ≤ fin de mes, sin fuga al futuro). MEP: **blue-proxy** (Fase 1, sin schema nuevo)».

#### 🔴 Hallazgo J-11 — `backfill_historical_mtm` SÍ es automático: corre en cada import confirmado

`[V]` `_reconstruir_mtm_post_import` (`backend/main.py:30714-30732`) lanza un thread daemon que llama a `_reconstruir_mtm` (`backend/main.py:30639-30712`), que a su vez llama a `backfill_user` del script. El comentario lo dice: «Hasta acá el reconstructor existía y no lo llamaba nadie más que `POST /api/admin/backfill-mtm`. **Con esto, importar alcanza.**»

`[V]` Y el propio docstring admite que para el perfil argentino no sirve todavía:

> «⚠️ NO todo es reconstruible. El reconstructor saltea FCI, los bonos/ONs de data912 y los CEDEAR cotizados en USD porque no hay serie histórica confiable. Medido sobre una cartera AR típica (CEDEARs + bonos + FCI) la cobertura da **~50% y NO pasa el piso**; una cartera de exterior (acciones US + cripto) da 100%.»

`[I]` O sea: **para el usuario argentino típico, este thread sale a yfinance por cada ticker con `timeout=8`, tarda minutos, y termina descartando su propio resultado por no llegar al piso de cobertura.** Es trabajo de red por cada import confirmado que en el caso más común no produce nada. Me agarro del propio docstring más la nota de `backend/main.py:30719` sobre el timeout por ticker.

`[V]` También hay ahí una lección grabada a fuego (`backend/main.py:30673-30684`): en una ronda anterior se agregó re-estampar `net_deposited` y salió peor, porque `compute_net_deposited_db` **trunca la fecha a MES**: «Medido sobre una cuenta SANA, sin ningún problema previo: 19 de 59 filas reescritas y el chip "variación desde el 1 del mes" pasó de 0 a **+US$10.000 de ganancia inventada**. Y esto corría en el camino de TODO import confirmado, de toda cuenta.»

#### `recompute_backfill` — el motor compartido

`[V]` `backend/importing/recompute_backfill.py` expone tres modos que el endpoint elige (`backend/main.py:15835-15858`):

- `safe_backfill(...)` (default, `safe_only=True`): «SOLO cambios inequívocos (fantasmas dólar-MEP de acciones, letras vencidas, bonos 100% amortizados, amortizaciones limpias). Omite las inflaciones/reducciones dudosas de bonos-conducto».
- `run_backfill(...)` con `apply=True`: todo.
- `dry_run_summary(...)`: clasifica sobre el clon.

`[V]` Tiene un **tope de cordura por usuario**: `_excede_tope_usuario` (`backend/importing/recompute_backfill.py:558`), con test propio (`backend/tests/test_backfill_tope_cordura.py`).

`[V]` Cuando no se puede clonar (Postgres), levanta `dberrors.EnsayoPorClonNoDisponible` y el endpoint la deja subir para que conteste 501 con mensaje explicativo, en vez de un 500 opaco (`backend/main.py:15873-15879`).

---

### 15.10 Push notifications: vivas, Web Push con VAPID

`[V]` Está implementado con **`pywebpush`** (`pywebpush>=2.0.0` en `backend/requirements.txt`) y claves VAPID. No hay FCM ni APNs ni un servicio de terceros.

`[V]` Superficie (`backend/main.py:34028-34177`):

| Endpoint | Línea | Qué hace |
|---|---|---|
| `GET /api/push/vapid-public-key` | `34052` | Devuelve `VAPID_PUBLIC_KEY`. **Público, sin auth** — «la public key no es secreta» |
| `POST /api/push/subscribe` | `34062` | Guarda `(endpoint, p256dh, auth, user_agent)` en `push_subscriptions`, UPSERT por `(user_id, endpoint)` |
| `DELETE /api/push/subscribe` | `34085` | Borra la sub de ese device |
| `GET /api/push/status` | `34101` | Cuenta devices suscriptos |
| `POST /api/push/test` | `34167` | Manda un push de prueba al usuario actual |

`[V]` El envío es `_send_push_to_user(uid, payload)` (`backend/main.py:34115-34158`):
- Si `pywebpush` no está instalado → devuelve 0 (no rompe).
- Si faltan `VAPID_PUBLIC_KEY` o `VAPID_PRIVATE_KEY` → devuelve 0 **en silencio**.
- `ttl=86400` (24h).
- Si el gateway devuelve **404 o 410** → borra la subscripción muerta.
- Cualquier otro error → `log.warning`, no propaga.

`[V]` Env vars: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` (default `mailto:hola@rendi.finance`). Las tres SÍ están en `backend/.env.example`.

`[V]` Limitación documentada (`backend/main.py:34029-34031`): «Funciona en Chrome/Firefox/Edge desktop + Android. iOS Safari desde 16.4 PERO solo si la app está "instalada" como PWA».

`[I]` **Modo de falla silencioso**: si alguien borra `VAPID_PRIVATE_KEY` de Railway, `_send_push_to_user` devuelve 0 sin loguear nada, `push_ok` queda `False`, y `alert_events.delivered_push` se graba en 0. La alerta queda registrada como «disparada» aunque no llegó a ningún lado. El único síntoma sería un usuario diciendo «no me llegan las alertas».

---

### 15.11 `backend/mantenimiento.py` — modo mantenimiento

`[V]` 149 líneas, y es el archivo mejor razonado del lote. Middleware que devuelve **503** (no 500) con `Retry-After: 120`, instalado ÚLTIMO para quedar más externo (`backend/main.py:301-303`; verifiqué que los otros dos middlewares están antes, en `backend/main.py:258` y `:269`).

`[V]` Tres decisiones:
1. **No toca la base, ni para leer un flag** — «un modo mantenimiento que consulta una tabla se cae junto con la base de la que te protege».
2. **El default es CERRADO**: `en_mantenimiento()` (`backend/mantenimiento.py:85-101`) devuelve True si `RENDI_MANTENIMIENTO=1`, False si `=0`, y **si nadie dijo nada**: `bool(DATABASE_URL) and not RENDI_PASAJE_COMPLETO`. O sea, **prender Postgres implica mantenimiento** hasta que se marque el pasaje como terminado.
3. **Bypass por header** `x-rendi-bypass` contra `RENDI_MANTENIMIENTO_TOKEN`, comparado con `hmac.compare_digest`. Sin token configurado **no hay bypass posible**.

`[V]` Ruta libre: solo `/api/health` — «tiene que contestar o Railway mata el contenedor».

`[V]` El archivo también documenta un error propio corregido (el cuerpo del 503 iba bajo `error` y el frontend lee `detail`), y las tres cosas que NO garantiza: no frena los crons externos, no frena requests en vuelo, y no frena los seis escritores del arranque.

---

### 15.12 Backups

`[V]` `backend/scripts/backup_db.py` — corre por cron a las **03:45 UTC** (`backup_db`, `backend/main.py:32560-32566` → `_run_backup_db_job`, `backend/main.py:32051-32076`), y a mano por `POST /api/admin/backup-trigger` (`backend/main.py:18631`).

`[V]` Pipeline (`run_backup`, `backend/scripts/backup_db.py:310-391`): dump con la API `sqlite3.backup` (consistente aun con writers) → gzip → copia local a `BACKUP_LOCAL_DIR` (default `./backups`) → subida opcional a S3-compatible → prune local (30 días) y remoto (90 días).

`[V]` Sin las env vars de S3 **no falla**: devuelve `remote_skip_reason` y sigue. `boto3>=1.34.0` está declarado en `requirements.txt`.

#### 🔴 Hallazgo J-12 — El backup local, sin volumen, no sobrevive un deploy

`[V]` `railway.toml` **no declara ningún volumen**. `[V]` `BACKUP_SETUP.md` dice: «Sin configurar nada, los backups quedan en `./backups/` del disco Railway. Eso protege contra bugs propios […] pero NO protege si Railway pierde el disco entero».

`[I]` Con contenedores efímeros de Railway, «perder el disco» es lo que pasa en **cada redeploy**, no un evento raro. Si `BACKUP_S3_*` no está configurado en producción, la retención real de 30 días es en la práctica «hasta el próximo deploy». No puedo verificar si las variables están puestas (no leo `.env`), pero el hecho de que no estén ni en `.env.example` es una señal.

#### 🔴 Hallazgo J-13 — El backup del cron NO es restaurable por el copiador a Postgres

`[V]` Esto está medido y escrito en `MIGRACION_POSTGRES.md`, bajo el título «**🔴 BLOQUEANTE DEL DÍA DEL PASAJE: el backup real NO pasa el guardián del `-wal`**»:

> «`scripts/backup_db.py` hace `src.backup(dst)` […] cierra, y comprime **sólo el `.db`**. Reproducido: tras `.backup()` + `close()`: byte 18 del header: 2 (modo WAL); ¿existe el `-wal`?: False; abrir con `mode=ro`: `OperationalError: unable to open database file`. **¿la copia está COMPLETA? SÍ. ¿el guardián la aceptaría? NO.**»

`[V]` El arreglo está identificado, es de **una línea** (`dst.execute("PRAGMA journal_mode=DELETE")` antes de cerrar el destino en `dump_sqlite_consistent()`), está medido… y **no está aplicado**: grepeé `journal_mode` en `backend/scripts/backup_db.py` y no aparece.

`[I]` O sea: el backup diario produce archivos correctos y completos, pero la herramienta del pasaje los rechaza con un mensaje («el archivo se copió a medias») que empuja al operador a sacarle el `mode=ro` — el remedio equivocado. Y el remedio que sugiere el mensaje («copiá los dos archivos») es imposible porque el `-wal` nunca existió.

#### ⚠️ Hallazgo J-14 — Con Postgres prendido, el job de backup se rompe en silencio

`[V]` `_run_backup_db_job` llama a `run_backup(db_path=DB_PATH)`, y `DB_PATH` es siempre el path del archivo SQLite (`backend/main.py:118`), sin importar `USANDO_PG`. `[V]` `run_backup` arranca con `if not os.path.isfile(db_path): stats['errors'].append(f"db_path no existe: {db_path}")` (`backend/scripts/backup_db.py:337-339`).

`[I]` Dos escenarios el día del pasaje: (a) el archivo no existe → el job loguea un error y **no hay backups de nada**; (b) el archivo SÍ existe en la imagen (una SQLite vieja o vacía) → el job sube alegremente **backups de la base equivocada** con el nombre del día. El escenario (b) es el peligroso porque parece que funciona. No hay ningún `if USANDO_PG: skip` en el job.

---

### 15.13 `backend/scripts/test_*.py` — no son tests, y ya hicieron daño

`[V]` Hay tres archivos `test_*.py` en `backend/scripts/`, y **ninguno es un test de pytest**. El `backend/pytest.ini` existe exclusivamente por ellos, y su comentario de cabecera es el hallazgo:

> «⚠️ ESTE ARCHIVO EXISTE PARA QUE `pytest` A SECAS NO PUEDA MANDAR UN MAIL.»
>
> «`scripts/test_emails.py` 🔴 manda 3 mails REALES por Resend, y su import hace `load_dotenv(override=True)`: **con sólo COLECTARLO, las credenciales de producción pisan el entorno de toda la corrida**.»
>
> «Son 47 pseudo-tests. Con ellos la suite no terminaba; sin ellos corre entera en ~52 s. Durante siete rondas se dio por hecho que "la suite muere al 23-28%" y toda la verificación se hizo sobre ~44 archivos elegidos a mano. **Nunca fue la suite: era la colección.**»

`[V]` La defensa son dos líneas, y el comentario explica por qué hacen falta las dos:

```ini
[pytest]
testpaths = tests
norecursedirs = scripts .git node_modules __pycache__ .pytest_cache venv .venv
```

`testpaths` cubre `pytest` a secas; `norecursedirs` cubre `pytest .` / `pytest -k algo`, donde `testpaths` se ignora.

`[V]` Los tres, y cómo se corren:

| Archivo | Qué es | Cómo se corre | Efectos |
|---|---|---|---|
| `scripts/test_emails.py` | Manda 3 emails REALES por Resend | `python3 backend/scripts/test_emails.py alguien@ejemplo.com` | 🔴 red + `load_dotenv(override=True)` |
| `scripts/test_bot_profile_boundaries.py` | Verifica propiedades constructivas de los prompts del bot (sin llamar al LLM) | `cd backend && python3 -m scripts.test_bot_profile_boundaries` | Su helper `fail()` hace `sys.exit(1)` |
| `scripts/test_proration_edge_cases.py` | 7 escenarios del modelo de crédito de suscripción | `cd backend && python -m scripts.test_proration_edge_cases` | Idem; imprime «ALL TESTS PASS» |

`[I]` **¿Los corre alguien?** No hay CI en el repo (no hay `.github/workflows`, ni nada en `railway.toml`/`nixpacks.toml` que ejecute tests). Se corren a mano, cuando alguien se acuerda. `[I]` El de emails es el más riesgoso porque su nombre invita a que un tooling automático lo levante; hoy solo lo frena `pytest.ini`, que es una defensa local a la carpeta `backend/`.

---

### 15.14 Migración a Postgres: en qué estado está

`[V]` **Producción sigue en SQLite.** El interruptor es `DATABASE_URL` (`backend/main.py:423-424`): sin la variable, `USANDO_PG=False` y `get_db()` devuelve `sqlite3.connect(DB_PATH)` (`backend/main.py:427-431`). El propio comentario: «Es un interruptor y no una bifurcación a propósito: durante la migración hay que poder correr LA MISMA suite de tests contra los dos motores y comparar».

`[V]` `MIGRACION_POSTGRES.md` (última sesión documentada: 2026-08-14, sesión 8) dice: «Rama **`spike/postgres`**. **NO se deploya** — es un spike. Producción va por `main` y está estable».

Estado por herramienta:

| Script | Estado | Evidencia |
|---|---|---|
| `mkschema.py` | ✅ **Funcionando y ya corrido.** Genera `backend/schema_pg.sql` desde el schema FINAL de SQLite (corriendo `init_db()` sobre una SQLite vacía + `pricing.fci.ensure_tables()`). El output actual tiene **63 `CREATE TABLE` y 64 `CREATE INDEX`** e incluye `fci_catalog`/`fci_prices` → el bug del «58-vs-60» está arreglado | `backend/scripts/mkschema.py:44-56`, `backend/schema_pg.sql:788` |
| `copiar_a_postgres.py` | ⚠️ **Escrito y con 4 subcomandos** (`aplicar-esquema`, `preflight`, `preparar-destino`, `copiar`), pero **bloqueado**: rechaza el output de `backup_db.py` (hallazgo J-13) | `backend/scripts/copiar_a_postgres.py:569-731`, `MIGRACION_POSTGRES.md` |
| `verificar_copia.py` | ✅ **Escrito ANTES que el copiador, a propósito.** 4 niveles: (0) el vaciado de `raw_json` no tocó nada, (1) fila por fila, (2) la plata por usuario, (3) las secuencias. Suma en `Decimal` y hashea sin `ORDER BY` para que el orden no importe | `backend/scripts/verificar_copia.py:1-45` |
| `pg_type_audit.py` | ⚠️ **Corrido sobre producción (LIMPIO), pero el resultado vale menos de lo que parece.** El doc lo corrige a sí mismo: muestrea con `LIMIT 200000` **sin `ORDER BY`**, y SQLite sin `ORDER BY` devuelve por `rowid` → **las filas más VIEJAS**. Todo lo que escribieron los parsers nuevos (PPI, inviu, Balanz Internacional, Bull Market, Binance) está en la cola y **nunca se auditó** | `backend/scripts/pg_type_audit.py:25-27`, `MIGRACION_POSTGRES.md` |
| `pgshim.py` / `pgsesion.py` | ✅ En el repo de producción (`backend/pgshim.py`, 49 KB; `backend/pgsesion.py`). `psycopg[binary]==3.2.13` declarado y pinneado, deliberadamente **sin** `DATABASE_URL` para que «el deploy salga verde sin cambiar nada para el usuario» | `backend/requirements.txt` |
| `base_sintetica.py` | ✅ Fabrica una SQLite con la FORMA de producción (3,37M filas, 92% andamio, 60 tablas) para cronometrar la copia. Explícitamente «No sirve para verificar plata» | `backend/scripts/base_sintetica.py:1-30` |
| `vigilar_espacio.py` | ✅ Mide el **WAL que genera la copia**, no el tamaño final. Existe porque el 2026-08-15 una copia de 1 GB tumbó un Supabase Free con `DATABASE 553 MB · WAL 660 MB · SYSTEM 759 MB` — «el cuaderno de borrador pesaba MÁS que los datos» | `backend/scripts/vigilar_espacio.py:1-30` |

`[V]` `_init_db_postgres()` (`backend/main.py:684-695`) aplica `schema_pg.sql` sentencia por sentencia, tolerando `DuplicateObject`. Con Postgres **no se corren las 46 migraciones incrementales** de `init_db()` (`backend/main.py:699-707`).

`[I]` Riesgo del diseño anterior: **hay dos definiciones de schema que hay que mantener sincronizadas a mano**. `mkschema.py` las reconcilia, pero solo si alguien se acuerda de correrlo. Y el propio `mkschema.py` avisa (`:176`, `:233`) que reescribe `schema_pg.sql` en el lugar, «se lleva puesta cualquier edición a mano».

---

### 15.15 Scripts sueltos que NO son jobs (inventario para completar el mapa)

`[V]`

| Script | Qué es | ¿Corre? |
|---|---|---|
| `escala_foto_bonos.py` | Análisis one-off: «¿la foto reporta NOMINAL o RESIDUAL?». SOLO LECTURA | 🔴 **No corre en ningún lado**: `sys.path.insert(0, '/Users/nicolaspussetto/rendi-worktrees/import-asesor/backend')` (`:26`) y `sqlite3.connect('file:/Users/nicolaspussetto/Downloads/trading-2026-08-16.db?immutable=1')` (`:30`) — rutas absolutas de la máquina del founder, a un worktree y a un archivo que no están en el repo |
| `verificar_proyeccion.py` | Verifica la proyección hacia atrás contra `snapshots.holdings_json` del cron. SOLO LECTURA | 🔴 Mismo problema: `:19` y `:22` |
| `seed_cuenta_unificada.py` | Fixture manual: usuario con broker bimonetario (padre ARS + sibling `· USD`), incluyendo el mismo ticker en las dos patas. Idempotente (reusa el usuario si ya existe, para no cambiarle el id) | A mano, contra `trading.db` local |
| `iol_spike.py` | Spike de la API de IOL para que **el tester lo corra en su propia máquina**. Solo stdlib. Allowlist dura de paths GET, la contraseña se pide sin eco y se descarta | A mano, fuera de Rendi |
| `explore_yfinance.py` | Probe de qué campos devuelve yfinance de verdad por tipo de ticker | A mano |
| `iol_swagger_v2.json` | Spec de la API de IOL (96 KB), referencia | N/A |

`[I]` Los dos primeros son **código muerto committeado**: no se pueden correr desde una clonada limpia del repo. Valen como documentación de un razonamiento (y están bien escritos como tal), pero no como herramienta.

---

### 15.16 Resumen de hallazgos, ordenados por lo que le costaría al usuario

| # | Hallazgo | Severidad | Cita |
|---|---|---|---|
| J-6 | El cron fecha los snapshots en **día UTC** y la conversión a día ART es código muerto; el otro escritor de la misma tabla sí usa ART | 🔴 | `backend/snapshots_job.py:648-656` vs `:937` y `:1021`; `backend/main.py:27750-27756` |
| J-13 | El backup del cron **no pasa el guardián** del copiador a Postgres; arreglo de 1 línea identificado y no aplicado | 🔴 | `MIGRACION_POSTGRES.md`; `backend/scripts/backup_db.py` (sin `journal_mode`) |
| J-1 | Alertas y briefs del asesor dependen **solo** del cron externo; sin respaldo in-process y sin señal si dejan de correr | 🔴 | `backend/main.py:32524-32574` (5 jobs, ninguno de alertas) |
| J-12 | Backup local a `./backups/` sin volumen declarado en Railway | 🔴 | `railway.toml`; `backend/scripts/BACKUP_SETUP.md` |
| J-11 | El MtM automático post-import sale a la red por cada ticker (minutos) y para la cartera AR típica descarta su propio resultado (~50% cobertura, no pasa el piso) | 🔴 | `backend/main.py:30666-30672`, `:30714-30732` |
| J-4 | Los 3 tokens de cron y todo el bloque `BACKUP_S3_*` faltan en `.env.example`; no hay inventario versionado de los crons externos | ⚠️ | `backend/.env.example` |
| J-2 | Ningún lock distribuido: con 2+ réplicas todos los jobs se duplican, incluidos los que mandan email | ⚠️ | `backend/main.py:33634` (lock in-memory) |
| J-14 | Con `DATABASE_URL` puesta, el job de backup o falla o respalda la base equivocada — no hay guard | ⚠️ | `backend/main.py:32061`, `backend/scripts/backup_db.py:337-339` |
| J-7 | `cooldown_min` es configurable, validado y persistido, y **el motor nunca lo lee**; `_recently_fired` no tiene call site | ⚠️ | `backend/alerts_engine.py:152-165` |
| J-10 | Seis escritores compiten en cada boot contra una SQLite single-writer; solo uno reintenta ante lock | ⚠️ | `backend/mantenimiento.py` («LO QUE NO GARANTIZA»); `backend/main.py:32097-32521` |
| J-9 | Dos cleanups prometidos en comentarios (`yfinance_cache` > 7d, `email_verification_codes` > 30d) que no existen | ⚠️ | `backend/main.py:1955`, `:2093` |
| J-8 | `alert_events` crece para siempre; el equivalente del asesor sí se purga | ⚠️ | `backend/main.py:33570` vs `backend/advisor_alerts.py:91-97` |
| J-5 | `/api/health` y el comentario de cabecera documentan el horario viejo (01:00 UTC) del cron que ahora corre 02:59 | ℹ️ | `backend/main.py:34276` y `:32001` vs `:32536` |
| J-3 | No hay marca de «última corrida OK» de ningún job; solo logs | ℹ️ | grep de `add_job` en `backend/main.py` |
| — | Los 4 crons aceptan token por **query param**, y comparan con `!=` en vez de `compare_digest` — criterio opuesto al que `mantenimiento.py` documenta para el bypass | ℹ️ | `backend/main.py:33600-33601`, `:33668-33669`, `:33951-33952`, `:31567` vs `backend/mantenimiento.py:112` |
| — | `escala_foto_bonos.py` y `verificar_proyeccion.py` no corren desde una clonada limpia (rutas absolutas de la máquina del founder) | ℹ️ | `backend/scripts/escala_foto_bonos.py:26,30`; `backend/scripts/verificar_proyeccion.py:19,22` |

---

### 15.17 Lo que NO encontré

- Un **archivo de configuración de los crons externos** (horarios, URLs, tokens) versionado en el repo: **no encontrado**. Solo hay docstrings sueltos y un párrafo en `PLAN_iol_sync.md`.
- **CI / GitHub Actions** que corra la suite: **no encontrado** (no hay `.github/` en el repo).
- Un **healthcheck declarado en Railway** (`healthcheckPath`): **no encontrado** en `railway.toml`.
- Un **volumen persistente** declarado para el disco donde viven la SQLite y los backups: **no encontrado**.
- **Lock distribuido, leader election o tabla de ejecución de jobs**: **no encontrado**.
- **Relleno de huecos de snapshots** por el cron (detectar fechas faltantes y recuperarlas): **no encontrado**. Lo único que fabrica filas retroactivas es el backfill MtM, y solo para meses cerrados de cuentas con import confirmado.
- **Métricas o alertas de infra** (Sentry, Prometheus, healthcheck que avise si el cron no corrió): **no encontrado**.
- Un **job de limpieza** de `alert_events`, `yfinance_cache` o `email_verification_codes`: **no encontrado** (ver J-8, J-9).
