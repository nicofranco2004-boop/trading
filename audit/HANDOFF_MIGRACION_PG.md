# HANDOFF — Migración SQLite → Postgres (Supabase)

> Escrito el 28/10/2026 por la sesión «Rendi SQLite a Postgres migración», para
> que otra sesión siga **toda** la migración sin depender de ningún chat.
> Este archivo vive en la rama a propósito: un handoff en un mensaje se pierde.
>
> **Leelo entero antes de tocar nada.** La sección 1 tiene un paso que, si se
> saltea, puede pisar en silencio arreglos de plata que costó una semana medir.

---

## 0 · En dos líneas

> **🆕 30/10/2026 22h — leé primero la sección 11 (estado al día).** Postgres dio
> 7.246/0 por primera vez; lo de abajo es historia útil pero parte quedó superada.

La migración está **técnicamente casi lista y operativamente no**. Los arreglos de
concurrencia están hechos y medidos, pero apareció **un mecanismo compartido por 24
operaciones destructivas** que sólo protege en SQLite, y **la suite contra el
Supabase real no se corre desde agosto**. Nada está publicado.

Quien lee los resultados es **Nico, que no programa**. Las reglas de cómo hablarle
están en `~/.claude/CLAUDE.md` y te llegan solas: seguilas al pie, especialmente
«empezá por el efecto», «decime cómo sabés que funciona» y «separá lo que hago yo
de lo que hacés vos».

---

## 1 · 🔴 LO PRIMERO, ANTES DE CUALQUIER OTRA COSA

### `origin/main` se movió 6 commits, y tocan JUSTO la zona de los arreglos

Al 28/10 a las 20:00, desde el último merge:

    a63de45c fix(brokers): quinta auditoría — sin la regla de "dólares directo a la sub-cuenta"
    d4af3407 fix(brokers): cuarta auditoría — la sub-cuenta en dólares no tiene sub-cuenta
    fd5b1fd1 fix(brokers): tercera auditoría de la sub-cuenta en dólares
    2a765492 fix(brokers): segunda auditoría de la sub-cuenta en dólares
    e8d8507c fix(brokers): la sub-cuenta en dólares, cerrada en todas las puertas
    c65247e7 fix(brokers): adoptar «X · USD» mueve su caja, y con pesos adentro se rechaza

Tocan `backend/efectivo.py` (2), `backend/importing/persister.py` (3) y
`backend/main.py` (3). **Es la sub-cuenta en dólares y su caja de efectivo**, que es
exactamente donde viven tres arreglos de esta rama: `caja()` que pide el turno,
`asegurar_caja()` como puerta única, y el importador que dejó de crear la caja por
su cuenta. Y `_ensure_usd_sibling` —que esos commits tocan— es uno de los 24 que
pide `_tomar_turno`.

**Un merge sin conflictos igual pisa un arreglo.** Está medido en este repo más de
una vez. Por eso el procedimiento es este, y en este orden:

1. **Antes de mergear**, correr el guardián y ver su verde de referencia:

       cd backend && python3 -m pytest tests/test_los_arreglos_sobrevivieron.py -q

   Tiene que dar **12 passed**. Si no da 12 ANTES del merge, el problema es el
   guardián y no el merge: arreglalo primero.

2. Mergear **sin** `-X ignore-all-space` (junta bien el contenido y miente sobre la
   indentación: ya metió un bug que compilaba y cambiaba el significado):

       git fetch origin && git merge origin/main --no-edit

   La app no puede hacer este merge por vos: esta copia no la creó ella.

3. Volver a correr el guardián: **12 passed** otra vez. Si da menos, cada rojo
   nombra qué pieza se llevó el merge.

4. Correr los tests de COMPORTAMIENTO (el guardián sólo mira piezas):

       python3 -m pytest tests/test_auditoria_pg_carrera.py tests/test_caja_una_sola_puerta.py \
         tests/test_tope_sin_tope.py tests/test_turno_por_la_conexion.py \
         tests/test_caja_orden_de_candados.py tests/test_dos_pedidos_a_la_vez.py \
         tests/test_tope_facts_simultaneos.py -q -p no:randomly

   Al 28/10 daba **55 passed, 5 skipped, 0 failed** contra SQLite.

5. Las dos suites completas (sección 3). **Una por vez, nunca las dos juntas.**

⚠️ Mirá con atención `asegurar_caja()` y `caja()` en `efectivo.py` después del
merge: si los commits nuevos agregaron una puerta que crea la caja de la pata
'· USD' («adoptar mueve su caja»), **esa puerta tiene que ir por
`asegurar_caja()`**, o vuelve el bug de las dos cajas. El guardián `test_4c` mira
el importador; no mira puertas nuevas.

---

## 2 · Dónde está todo

| | |
|---|---|
| **Rama** | `claude/migracion-pg-oct` |
| **Copia** | `/Users/nicolaspussetto/Documents/trading/.claude/worktrees/verif-pg` |
| **Publicada** | **NO.** No existe en `origin`. Pushear = deployar (Railway + Vercel). |
| **Commits sin publicar** | 28 (más el merge de 48 commits de main del 28/10) |
| **Informe técnico** | `audit/HALLAZGOS_MIGRACION_PG.md` — 12 hallazgos, con sus correcciones EN LÍNEA |
| **Barrido de los 24** | `audit/BARRIDO_TOMAR_TURNO_24.md` |
| **Barrido de 7 lentes** | `audit/BARRIDO_7_LENTES.md` (21 hallazgos, casi todos sin verificar) |
| **Sondas rescatadas** | `audit/sondas/` — leé su `LEEME.md` antes de usarlas |
| **Plantillas de workflow** | `audit/workflows/` |
| **Postgres de prueba** | `scripts/pg_de_prueba.py` |
| **Memoria del proyecto** | `~/.claude/projects/-Users-nicolaspussetto-Documents-trading/memory/project_postgres_migration.md` |

---

## 3 · Cómo medir (y las cuatro trampas que ya nos mordieron)

### Levantar Postgres

    python3 scripts/pg_de_prueba.py

Imprime `DSN=...` y **no termina a propósito** (el servidor muere con el proceso).
Correlo como comando en segundo plano y leé el DSN de su salida. Para apagarlo,
matá ese proceso **por su pid** — nunca con `pkill -f` y un patrón corto (la regla
del repo cuenta que eso cerró apps de la Mac).

Verificado el 28/10: crea la base, da el DSN, y un test real pasó contra ese
servidor.

### Correr las suites

    cd backend
    python3 -m pytest tests/ -q -p no:randomly                                          # SQLite
    DATABASE_URL='<DSN>' python3 -m pytest tests -q -p no:randomly --timeout=90         # Postgres

### 🔴 Las cuatro trampas

1. **Nunca dos suites a la vez.** El 24/10 dos corridas del mismo código dieron 14
   y 16 fallas y parecían probar que el número varía solo. Se habían solapado 415
   segundos. Esperá la notificación de una antes de largar la otra.

2. **Un número de fallas sin su DURACIÓN no se puede interpretar.** Con la máquina
   quieta la suite de Postgres tarda **~513 s**. Si tardó 1,5× o más, la máquina
   estaba ocupada y el número viene inflado. El `conftest.py:114-121` ya lo tenía
   medido: 46 fallas en 68 s, **49 en 133 s**, 46 en 71 s.

3. **No edites código mientras corre una suite.** Invalida el número. Y tampoco
   mientras corre un workflow que está leyendo ese archivo: un agente lee un
   archivo a mitad de escritura y reporta un fantasma.

4. **`/private/tmp` se purga.** El fin de semana del 24-28/10 se llevó el script del
   pgserver y los resultados de las suites. Todo lo que tenga que sobrevivir va al
   repo. Guardá los resultados de las suites en el scratchpad para leerlos en el
   momento, pero no confíes en encontrarlos al día siguiente.

---

## 4 · El estado medido (28/10, después del merge de 48 commits)

| motor | resultado | duración |
|---|---|---|
| **SQLite** | **7.157 pasados, 0 fallas** | 319 s |
| **Postgres** | 7.119 pasados, **14 fallas** | 768 s ⚠️ (máquina cargada) |

Las 14 de Postgres tienen dueño, una por una:

**12 PREEXISTENTES** — ya estaban antes de los arreglos (medido restaurando los
archivos a `b0bd5c6b` y contra la corrida de la auditoría sobre `4fe75445`):

    test_admin_ingresos.py::UltimoLoginAtrasado::test_el_arranque_completa_la_columna_desde_el_historial
    test_admin_uso.py::Poda::test_el_arranque_borra_lo_de_mas_de_13_meses
    test_alerts.py::test_el_ciclo_no_tiene_tomada_la_base_mientras_espera_a_yahoo
    test_alerts.py::test_los_dias_de_byma_se_piden_sin_la_base_tomada
    test_audit_bloqueantes.py::B5_CoberturaSinPreciosTest::test_no_hay_cobertura_1_sin_haber_consultado_un_precio
    test_audit_bloqueantes.py::B5_CoberturaSinPreciosTest::test_tenencia_sin_costo_conocido_no_es_afirmable
    test_cupon_importado_bandeja.py::CuponImportadoBandejaTest::test_lo_que_lee_la_pantalla_es_el_fixture
    test_cupones_contrato.py::CuponesContratoTest::test_lo_que_lee_la_pantalla_es_el_fixture
    test_efectivo_una_puerta.py::LasCajasViejasSeRenombranAlArrancar::test_al_arrancar_quedan_USD_y_lo_demas_no_se_toca
    test_efectivo_una_puerta.py::LasCajasVaciasPierdenElPrecioAlArrancar::test_al_arrancar_quedan_sin_precio_y_lo_demas_no_se_toca
    test_email_verification.py::RegisterEmailVerificationTest::test_register_email_already_registered_returns_409_with_code
    test_no_mail_tras_borrar.py::NoLleganMailsTrasBorrar::test_la_direccion_no_queda_en_ninguna_tabla

**1 ROJA A PROPÓSITO** — es el bug del punto 5.B, escrita por la auditoría para que
el arreglo tenga su prueba antes de escribirse:

    test_pnl_del_mes_dos_pedidos.py::PrimeraOperacionDelMesALaVez::test_dos_primeras_del_mes_no_dan_500

**1 QUE FLAQUEA POR CARGA** — pasa 3 de 3 aislada:

    test_cupones_bandeja.py::BonoSinCronogramaEnElServidorTest::test_la_cantidad_importada_es_nominal_original

### 🔴 «La suite de Postgres está en N» todavía NO es un criterio

Hay **tres tests que entran y salen según la carga** de la máquina:
`cupones_bandeja` (dos tests distintos de ese archivo), `cupones_bandeja_azar` y
`ritmo_de_envio` (mide con reloj de pared). Mientras sigan así, un número de
fallas no sirve como semáforo para el pasaje. Ver el punto 5.E.

---

## 5 · Lo que falta, en orden

### A · El merge de los 6 commits de main → ver sección 1

### B · 🔴 El bug del mes: cargar una operación puede contestar «guardada» y no guardar nada

**Medido**, con test rojo listo (`test_pnl_del_mes_dos_pedidos.py`, hallazgo 11).

`_update_monthly_pnl_realized` (`main.py`, buscala por nombre) es la **función
hermana** de `_update_monthly_flow`: misma tabla, misma fila, 47 líneas de
distancia. El arreglo de concurrencia `d4742484` se aplicó a una y **no a la
otra**. Es la causa raíz número uno de este repo, y esta vez en el propio trabajo
de la migración.

**La secuencia completa, verificada paso a paso** (`main.py`, `create_operation`):

1. Dos operaciones entran a la vez y son las **primeras del mes**.
2. Las dos ven que la fila del mes no existe y las dos la insertan.
3. La segunda choca con `UNIQUE (user_id, year, month, broker)`.
4. En Postgres eso **deja la transacción entera abortada**.
5. Un `try/except Exception` alrededor **se traga el error** y sólo escribe
   `log.error("Recalc tras create_operation falló: …")`.
6. `conn.commit()` sobre una transacción abortada **es un ROLLBACK**: se descarta
   también el `INSERT INTO operations`, y el movimiento de caja si lo había.
7. Como `row` se leyó ANTES del `try`, el endpoint devuelve **200 con el id de una
   fila que ya no existe**. La app la muestra, cualquier acción posterior sobre ese
   id pega contra nada, y al recargar desaparece.

**Por qué ningún recálculo lo salva**, que es lo que tardó en entenderse: hay un
`_recalc_pnl_realized_from_ops` que rearma la contabilidad y tapa casi todo. Pero
**el error pasa antes de que el recálculo exista** — se lleva el pedido entero. Es
el mismo bug partido por la rama: si la fila del mes ya existe, el recálculo salva
la suma; si no existe, no la salva nada.

**El arreglo, con su jerarquía escrita en el código:**

1. `ON CONFLICT (user_id, year, month, broker) DO UPDATE` en el INSERT de
   `_update_monthly_pnl_realized`, igual que la hermana → **esto arregla el bug
   medido**.
2. La suma en la base (`pnl_realized = pnl_realized + ?`) en vez de en Python. Hoy
   lo tapa el recálculo — y con el tipo de cambio, en este repo, «lo tapa el
   recálculo» terminó siendo un arreglo que **nunca funcionó un solo día**. Hay 30
   llamadores: el día que alguien agregue una puerta sin recálculo, se destapa.
3. `capital_final` se recalcula desde el `deposits` que la función LEYÓ. Si en el
   medio la hermana sumó un depósito en la base, éste lo borra. **El arreglo de la
   hermana volvió a esta función más peligrosa**, no menos.
4. El `except` que se traga el error: cuando la transacción quedó abortada, tiene
   que hacer `rollback()` y **contestar error**, no 200. Y el mensaje del registro
   tiene que distinguir «falló el recálculo pero se guardó» de «se descartó el
   pedido»: hoy los dos dicen «falló un recálculo», que suena a nada.

**Propagación** (regla del repo: un arreglo en 1 de N no está terminado):
`update_operation` tiene **la forma exacta**, con su `row` leído antes del `try` y
su `_adjust_broker_cash` adentro de lo que se descarta. Y la forma «try que escribe
→ except que se traga el error → commit» aparece en **22 sitios del backend, 15
alcanzables por un usuario** (medido con AST el 28/10, contando `commit()`
explícito Y `with conn:`, que también confirma al salir): `register` ×2,
`update_position`, `snapshots_job.run_daily_snapshot` ×2, `billing/trial.py` ×2,
`advisor_alerts.evaluate`, entre otros. La lista completa sale de re-correr ese
análisis; el criterio está descrito en el hallazgo 11.

### C · 🔴 El mecanismo de los 24: `_tomar_turno` sólo protege en SQLite

Hallazgo 12 + `audit/BARRIDO_TOMAR_TURNO_24.md`. **Es lo más grande que queda.**

`_tomar_turno(conn, uid)` hace `UPDATE users SET tier=tier WHERE id=?`. En SQLite
eso toma la base entera; en Postgres, sólo la fila de ese usuario en `users`, así
que sólo espera quien también escriba esa fila. Lo usan **24 sitios**, casi todos
operaciones destructivas.

**Estado del barrido:**

| | |
|---|---|
| sitios mapeados | 24 |
| ✅ **confirmados por 3 escépticos** (todos de PLATA) | **6** — la familia de los borrados y sus deshacer |
| ❌ refutados | 1 (`create_monthly`) |
| ❓ **sin verificar** (los escépticos murieron por el límite de uso) | **14** |
| protegidos también en Postgres | 3 |

**El caso típico de los 6:** borrar una operación cargada a mano lee el capital
aportado con `_foto_contable` (0,8 a 1,65 s medidos por el propio código), y
reescribe `snapshots.net_deposited` en **hasta ~1.100 fotos históricas** con la
diferencia entre las dos lecturas. Un depósito por `/api/cash/flow` en esa
ventana —que no escribe la fila de `users`— queda adjudicado al borrado. El capital
aportado es el **denominador del rendimiento**: toda la curva queda deformada hacia
atrás, y el propio código avisa que una foto reescrita mal «no tiene vuelta». Peor:
la corrección queda anotada foto por foto, así que el «Deshacer» devuelve la misma
corrección contaminada.

**Y apareció una tercera categoría: «lo toma A VECES»** — y la protección aparece
justo en el caso **menos** frecuente:

| operación | protegida | **SIN protección** |
|---|---|---|
| vender un lote (`sell_position_fifo`) | en dólares, dentro de un broker en pesos | **en pesos** — el caso común |
| editar un lote (`update_position`) | moverlo a otro broker | **cambiarle el precio** |

No es casualidad: el turno vive adentro de ayudantes para casos especiales (crear
la pata '· USD', validar un broker nuevo). El camino común no pasa por ninguno.

**Lo que hay que hacer:**

1. **Verificar los 14 sitios pendientes.** Con un workflow sólo de refutación,
   reusando `audit/workflows/barrido_tomar_turno_24.js` como plantilla (ver la
   sección «Cómo volver a correr» del barrido: **no se puede reanudar desde otra
   sesión**). En tandas: la primera vez el límite de uso mató 44 de 71 agentes.
   ⚠️ «Sin verificar» NO es «probablemente cierto»: de los hallazgos de lentes
   verificados a mano, uno tenía el mecanismo bien y la gravedad inflada al doble.
2. **El arreglo probablemente es UNO solo**: que `_tomar_turno` además pida un
   candado de verdad por usuario (`pgsesion.turno_exclusivo`), y que lo pidan
   también los endpoints que escriben las cuentas y hoy no llegan al turno. El
   propio docstring de `_foto_contable` ya lo proponía.
   🔴 **Cuidado con el orden de candados.** La caja de efectivo ya tiene su propio
   turno por usuario (`TURNO_CAJA_DEL_BROKER`). Si un camino toma «el de
   `_tomar_turno`» y después «el de la caja», y otro al revés, aparece un bloqueo
   mutuo — **ya se pagó dos veces en esta tanda**. La regla: un solo mecanismo por
   alcance, y pedido siempre primero. Medilo con `test_dos_pedidos_a_la_vez.py`
   (24 tests) en varias corridas: antes el bloqueo era 3 de 3 reproducible.
3. Los endpoints que **nunca llegan** al turno, según el cruce de la auditoría:
   `_edit_position_group`, `adjust_position_ratio`, `cobrar_plazo_fijo`,
   `create_operation`, `import_confirm`, `advisor_group_op_undo`, y los **seis
   `/api/admin/repair-*`** (reparación masiva: el peor momento para que otro
   escriba al mismo tiempo).

### D · Los 21 del barrido de 7 lentes

`audit/BARRIDO_7_LENTES.md`. Rescatados del journal el 28/10. Casi ninguno está
verificado. La tabla de arriba del archivo dice cuáles sí y qué dieron.
**Las lentes aciertan el DÓNDE y exageran el CUÁNTO.** Es trabajo nuevo: lo decide
Nico.

### E · Los 12 preexistentes y los 3 que flaquean

Ninguno es de los arreglos. Uno ya tiene dueño: el 500 al registrarse con un email
repetido (`test_email_verification`). Los 3 que flaquean hay que hacerlos
**deterministas** (el de `ritmo_de_envio` no puede medir con reloj de pared; los de
cupones, ver qué les falta) o sacarlos de la cuenta diciendo «N más 3».

### F · 🔴 La suite contra el SUPABASE REAL — no se corre desde agosto

Todo lo medido es contra un Postgres local en la Mac. Supabase tiene diferencias
que ya mordieron: `extra_float_digits=0` (lee floats redondeados; ver
`pgsesion.py`), y su pooler **se come 3 de cada 4 ajustes de `options=`** (sólo
sobrevive `search_path`; ver `tests/conftest.py`, `_forzar_ajustes_por_set`). La
conexión a Supabase la tiene Nico; **no le pidas la clave**: pedile que la ponga él
como variable de entorno, o que corra el comando.

#### 30/10 — corrida contra el Supabase real (sesión «suite contra el Supabase real», rama `supabase-real`)

**Resultado: 70 % corrido, ninguna falla nueva atribuible a la APP; dos hallazgos de INFRAESTRUCTURA que
sí importan para el pasaje.** Commit medido: `2b4098e7`. Lista completa por falla, con categoría:
`audit/supabase_real_fallas_2026-10-30.tsv`.

- **Base:** proyecto `fmxiqksahpzygvegteap`, región **sa-east-1 (São Paulo)**, session pooler :5432. `public`
  vacío antes de correr (lo miró Nico en Table Editor). La conexión vive en `~/.rendi-supabase-url`
  (permisos 600, fuera del repo); la puso Nico con un script que pide la clave oculta.
- **Duración:** 22:17 → 12:15, **50.316 s (14 h)**, y **se cortó al 70 %**: 5.596 de 7.325 (288 de 412
  módulos). Desde `test_plan_b_con_transaccion_abortada` en adelante NO corrió. Causa del corte: el reloj de
  90 s de pytest-timeout saltó MIENTRAS pytest armaba el traceback (parsea `main.py` entero, 46k líneas) →
  `INTERNALERROR` y fin de sesión. Instrumento, no app.
- **Latencia medida desde la Mac:** conectar 0,37 s; ida y vuelta 50 ms (local: ~0,03 ms). `schema_pg.sql` son
  797 sentencias mandadas de a una → ~40 s por módulo sólo en armar el esquema. ~2 % de CPU: la corrida es
  de red, así que la trampa «duración ≥1,5× = máquina cargada» NO aplica acá.
- **Números:** 5.084 pasaron · 300 fallaron · 80 errores · 118 salteadas · 12 xfail. Las 381 F/E:

  | categoría | n | veredicto |
  |---|---|---|
  | `Failed: Timeout (>90s)` | 301 | **instrumento (latencia)**. 198 son de `test_borrar_conserva_el_dia` (264 tests, 12.816 s, los que pasaron tardaron hasta 62 s); el resto, tests de borrar/deshacer en `operaciones_con_receta`, `cambios_ratio`, `flujos_a_mano`, etc. Mismo archivo solo contra Supabase (`test_borrar_broker_sueltos`): 30/30 verdes en 611 s. |
  | `connection is closed` en el teardown | 42 | **instrumento**: consecuencia del timeout (pytest corta el test y la limpieza encuentra la conexión cerrada). Todas en módulos con timeouts. |
  | `DeadlockDetected` en el setup (17: `test_pata_de_la_moneda` ×14, `test_ia_insights_sin_historia` ×3) | 17 | **instrumento, propio de Supabase (probable)**: el `DROP SCHEMA` del módulo anterior choca con una conexión de un hilo que sigue vivo del módulo anterior (`test_password_reset`, `test_ia_caida_medida`). En local `application_name` llega en el paquete de arranque y `pg_terminate_backend` la mata; en Supabase llega recién con el `SET`, así que una conexión recién abierta se llama `Supavisor` unos ms y se escapa del filtro. El backend bloqueante tiene el pid inmediatamente anterior al de la conexión del DROP (3217689/3217690), o sea que se abrió justo en el cambio de módulo. No es código de la app (la app no dropea esquemas). |
  | tiempos (`test_events_al_dia` ×5: «tardó 1,26 s esperando a Yahoo», tope 0,5-3 s) | 5 | **instrumento (latencia)**: miden cuánto tarda el endpoint y cada consulta cuesta 50 ms. |
  | `EMAXCONNSESSION max clients reached in session mode` (`test_envio_masivo`) | 1 | **🔴 real, de infraestructura** — ver abajo. |
  | conocidas de la lista local | 9 | `test_alerts` ×2, `test_audit_bloqueantes` ×2, `test_cupon_importado_bandeja`, `test_cupones_contrato`, `test_no_mail_tras_borrar` ×2; `test_cupones_bandeja`/`_azar` cayeron por timeout. `test_rendimientos_mensuales` no llegó a correr. |
  | interna de pytest | 1 | el corte de arriba. |

- 🔴 **Hallazgo 1 — región.** Supabase está en **São Paulo** y Railway en **US West** (memoria
  `project_deployment`). No lo medí desde Railway, pero esa ruta suele andar en ~170-200 ms de ida y vuelta,
  3-4× lo medido desde la Mac. Los tests de borrar una operación hacen del orden de mil viajes (60 s / 50 ms):
  en producción eso sería una pantalla de borrar que tarda minutos. El proyecto está VACÍO, así que crearlo de
  nuevo en la región de Railway es barato hoy y caro después del pasaje. **Decisión de Nico** (o mover Railway).
  Medir la latencia Railway→Supabase antes de decidir.
- 🔴 **Hallazgo 2 — cupo de conexiones del session pooler.** `get_db()` abre una conexión nueva por llamada
  (no hay pool, ver 5.C/memoria) y el session pooler tiene un cupo de clientes por tamaño de instancia; un
  envío masivo con hilos lo agotó en la suite. En prod el mismo patrón con varios usuarios a la vez puede dar
  errores. Opciones a decidir (sesión central): pool en la app, pooler transaccional :6543 con
  `prepare_threshold=None` (ver pgsesion/memoria: :6543 rompe las sentencias preparadas), o subir la instancia.
- **Riesgo anotado del instrumento:** `import main` corre `init_db()` + `reparaciones_de_arranque` +
  `_migrar_credenciales_a_credentials_key` contra el DSN CRUDO (esquema `public`) ANTES de que el conftest mude
  todo a `t<pid>_…`. Con `public` vacío no pasa nada (sólo quedan tablas vacías); **contra una base con datos
  reales la suite los modificaría**. El conftest en sí sólo dropea `t<pid>_…`. Nunca correr la suite contra la
  base del pasaje una vez cargada.
- **Para la próxima corrida:** `--timeout=600` (o más) y empezar en `test_plan_b_con_transaccion_abortada`
  para cubrir el 30 % que falta (~1.730 tests). Con esta latencia, ~6-8 h.

### G · Auditoría final, publicar, reposo, pasaje

**Con una sesión de auditoría nueva.** La conclusión de toda esta tanda:
**ninguno de los bugs grandes lo encontró quien lo escribió**. El tope de IA lo
tapaba una medición con dos pedidos; el `? IS NULL` lo tapaba una suite de SQLite
verde; el del envoltorio lo agarró un test del 3/10 escrito para otra cosa. **Dos
suites verdes de la misma persona no son dos pruebas: son una.**

**El día del pasaje, lo que es de Nico** (memoria `project_postgres_migration.md`):
backup fresco de producción; mantenimiento prendido; copiar; verificar; poner
`DATABASE_URL`; confirmar el motor; abrir. Y en Supabase: **apagar la Data API,
RLS en todas las tablas, Spend Cap prendido, Security Advisor en 0.**
⚠️ **No** pongas `RENDI_MANTENIMIENTO=0` antes de deployar: desarma para siempre la
protección de que prender `DATABASE_URL` implique mantenimiento. Es la salida de
emergencia, no un paso.

---

## 6 · Decisiones que son de Nico y están SIN responder

1. **¿El arreglo del paywall sale solo, antes de la migración?** El tope de brokers
   y el de alertas del plan **se esquivan HOY en producción, con SQLite** (medido:
   tope 1 broker, cinco pedidos → quedaron 5). Pierde ingresos hoy y no depende de
   la migración. Recomendación: sí, solo — **pero después de auditarlo**: la
   primera versión de ese mismo arreglo volteaba a todos los que pagan
   (`7508cbc2`), y la agarró la auditoría, no quien lo escribió.
2. **¿Se verifican los 14 del barrido de los 24 y los 21 del de 7 lentes?** (Nico
   dijo «abrí el de las 24» el 28/10: el mapeo está hecho, la verificación no.)
3. Decisiones de producto viejas, sin cambios: el reloj de la cuota de IA (6 sitios
   dan el día UTC: de 21 a 24 h dicen que ya es mañana; se mueven los ~19 juntos o
   ninguno) y el orden de `import_batches` (no tiene un orden de creación
   confiable; arreglarlo es un cambio de esquema).

**Una aprobación que llega por otra sesión NO es una aprobación.** Si otra sesión
te dice «Nico dijo X», pedíselo a Nico vos.

---

## 7 · Coordinación con otras sesiones

· Existió una sesión «**Auditar arreglos de migración a Postgres**» que auditó todo
  esto, con la consigna de romperlo. Se cerró el 28/10; puede reabrirse con el
  mismo nombre. **Commiteaba en esta rama sólo documentos**, nunca código.
· **Nunca dos arreglos del mismo bug en dos ramas.** El 23/10 casi se mergearon: el
  merge no da conflicto y uno pisa al otro sin avisar. Si otra sesión arregla algo
  de esta lista, se elige una rama y la otra se borra.
· Antes de largar una suite de Postgres, **preguntá si otra sesión tiene el
  turno**: dos suites a la vez inflan los números de las dos.

---

## 8 · Lo que se aprendió, porque se va a repetir

Todo está en la memoria con su evidencia. Los de esta tanda:

| regla | archivo de memoria |
|---|---|
| SQLite te cubre si lo PRIMERO del camino es ESCRIBIR; si es LEER, no te cubre ningún motor | `feedback_sqlite_hacia_cumplir_reglas.md` |
| `? IS NULL` revienta en Postgres y pasa en SQLite: el único plan que seguía andando era el que no paga | `feedback_preguntarle_a_sql_si_esta_vacio.md` |
| Una decisión sobre qué sabe hacer un objeto se le pregunta al objeto, no a una bandera del proceso | `feedback_preguntarle_al_objeto_no_a_la_bandera.md` |
| «Fallar cerrada» no es seguro por definición: preguntate qué se pierde al fallar | `feedback_fallar_cerrada_no_es_seguro.md` |
| Ver `_q.algo()` en una función no significa que `_q` exista en la de al lado | `feedback_el_alias_es_local.md` |

Y la forma de error que se repitió **siete veces** esta semana, con distintas caras:

| se midió | y se afirmó sobre |
|---|---|
| dos pedidos simultáneos | un tope bajo carga |
| un conteo de comillas par | el anidado de los bloques |
| un total de fallas que cierra | de dónde salía cada falla |
| una corrida | una trayectoria de cuatro |
| dos corridas que se solapan | la variabilidad del número |
| un grafo de llamadas («puede») | si el turno se toma («hace») |
| «está adentro de algún bloque» | si la llamada es condicional (un `try:` no es una rama) |

**Las siete son un agregado o una muestra puesta en lugar de la estructura.** En las
siete el número cerraba perfecto. El antídoto que funcionó todas las veces:
**cruzar contra un segundo método, o contra un caso cuya respuesta ya conocés.**

---

## 9 · Lo que NO hacer

· **No pushees.** Pushear es deployar. Nada sale sin la ronda de auditoría y el OK
  de Nico en tu propio canal.
· No mergees con `-X ignore-all-space`.
· No corras dos suites a la vez, ni edites mientras corre una.
· No le pidas a Nico claves, tokens ni contraseñas: decile dónde están y qué hacer.
· No des un número de fallas de Postgres sin su duración al lado.
· No trates un hallazgo «sin verificar» como un hallazgo.
· No borres `test_dos_pedidos_a_la_vez.py` ni ningún test viejo «porque molesta»:
  ése, escrito el 3/10 para otra cosa, fue el que agarró la regresión del envoltorio.

---

## 10 · Estado al 29/10 10:20 — 5.B medido y guarda de commit aplicada

| corrida | resultado | duración |
|---|---|---|
| Postgres sobre `28f0d20d` (sólo 5.B) | 7.152 pasados, **12 fallas = las 12 PREEXISTENTES**; la roja del mes en verde | 893 s (carga 13 al arrancar) |
| Postgres sobre `f1e43cd4` (con la guarda `22d6bb4e`) | 7.161 pasados, **11 fallas** = las 12 menos `test_email_verification` (lo arregló `035f3de4`) | 654 s (máquina quieta) |
| SQLite sobre la punta | **NO CORRIDA** (se acabó el uso): es lo primero que falta | — |

Los 28 rojos que agregaba la guarda eran **todos** el `commit()` de la limpieza de los propios tests
(`reset_admin:105` ×13, `reset_data:67` ×7, `tickers_renombrados:100` ×8). Ningún caso legítimo y
ninguno de la app: el primer borrado de cada limpieza falla en Postgres (`users` no tiene `user_id`;
`price_alerts` no existe) y la limpieza entera se tiraba callada. Arreglado en `fb3a1b9d` con un punto
de guardado por borrado. La guarda queda como estaba (`22d6bb4e`).

Latente, sin tocar (familia «plan B», hallazgo 13): `_reset_data_worker` cuenta cada tabla con
`except ERR_OPERACIONAL`; en Postgres una tabla ausente aborta la transacción y el resto del reset revienta.

---

## 11 · Estado al 30/10/2026 22h (sesión central + dos ayudantes)

**Medido sobre `425e77f6`** (la punta `771dbb4f` sólo suma pruebas): **Postgres 7.246 pasaron / 0
fallas en 566 s**, SQLite 7.240 / 0 en 317 s. Es la primera corrida de Postgres en cero. Nada
publicado.

### Qué entró hoy
| pieza | commit(s) | qué hace |
|---|---|---|
| Pozo de conexiones | `8ef519d0`, `7ee5af6c` | `pgshim._Pozo`: tope `RENDI_PG_POOL_MAX` (10), espera `RENDI_PG_POOL_ESPERA` (30 s) y `PozoAgotado`; vuelve al pozo sólo lo limpio (`_RE_ENSUCIA`: SET de sesión, candados de sesión, temporales). `tope_temporal(n)` para tests que toman la conexión antes de una barrera. |
| 4 rojos viejos | `6dfdce3e`, `45483cb2` | la limpieza borraba madres antes que hijas (`tests/_limpieza.vaciar` + guardián); el contrato de cupones fijaba ids de SQLite (`tests/_ids_relativos.py`). |
| Turno: PENDIENTES vacío | `3ebbe8da`, `e418cb59`, `ea0a8899`, `425e77f6` | reconstrucción (Yahoo sin transacción, turno antes de escribir), reparaciones del arranque, borrar cuenta, empezar de cero, migración FCI (una cuenta por transacción), alta del dueño. El censo ahora ve tablas en variables. |
| Arranque sin trabar | `4b2b1374` | huella del esquema en `esquema_aplicado` (saltea los ~800 DDL si coincide Y el catálogo lo confirma), `lock_timeout` 3 s × 20 reintentos, `/api/health` 503 hasta terminar, `healthcheckPath` en `railway.toml`. |
| Renombre durante import | `4b0379f9`, `4d3e4dd4` | la vista previa toma el turno y rehace si cambiaron los brokers; confirmar toma el turno real también en SQLite; «estado inicial» traducido al nombre de hoy. **Bug también en producción** → se publica aparte. |
| Tokens a huella | `425e77f6` | las dos reparaciones de tokens nunca corrían (NameError al cargar `main.py`). **También en producción** → se publica aparte. |
| Plan B (hallazgo 13) | `1af27ea5` | medidos los que quedaban: ninguno revienta; el censo ve los que pasan por otra función. |
| 3 cobros vs import | `d57f6e1d` | medido: el turno compartido impide el doble cobro en los dos motores. Guardián. |

### Supabase (5.F actualizado)
- El proyecto de São Paulo se **borró**. El nuevo: «RENDI 1», `phlsvhbdhkjbdfcjwaho`, **us-west-1
  (North California)**, Micro, Data API y exposición automática **desactivadas**, `public` vacío.
- Railway (lo leyó Nico): **US West, 1 réplica, Healthcheck Path vacío, Teardown apagado**, volumen
  `trading-volume` con un aviso ⚠ que **todavía nadie leyó** (mirar: ¿disco casi lleno?).
- La conexión vive en `~/.rendi-supabase-url` (session pooler, permisos 600), la guarda
  `scripts/conectar_supabase.py` sin que la clave pase por el chat. Desde la Mac: abrir 1,69 s,
  consulta 276 ms. **La suite contra Supabase no se corre desde la Mac** (serían días): hay que
  correrla desde un lugar cerca de us-west-1.
- El `EMAXCONNSESSION` de la corrida del 30/10 lo causaba `test_envio_masivo` (retenía ~30
  conexiones), no la app.

### Publicación aparte (antes de la mudanza)
Rama `claude/import-renombre-prod` (`77392079`, sale de `origin/main` y está al día): el renombre
durante import + los tokens. SQLite 7.278 / 0. **Falta:** la auditoría (tarjeta propuesta a Nico) y
su OK. Al publicarla, `claude/migracion-pg-oct` ya tiene los mismos cambios: el merge posterior no
duplica nada, pero mirá `_tomar_turno` y `pgsesion.tomar_turno`.

### Lo que falta para el pasaje
1. Suite completa contra el Supabase nuevo, desde cerca de us-west-1, con `--timeout` largo.
2. El aviso del volumen de Railway.
3. Decisiones de Nico (sección 6): backups (el nocturno sigue sólo-SQLite), los 21 de 7 lentes,
   paywall, `credit_ledger`/`_marcar_bienvenidas_previas`.
4. `drainingSeconds` en `railway.toml` (0 o 3 s según la página de la documentación; con 0, los
   pedidos en vuelo se cortan al publicar).
5. Auditoría final con una sesión nueva sobre `claude/migracion-pg-oct`, y el OK de Nico.

### Cómo se coordinó (para repetirlo)
- Las ayudantes trabajan en su rama, corren sólo los archivos afectados, nunca la suite completa
  ni push. La central mezcla y corre la suite completa **después de cada mezcla**: dos veces
  encontró rojos que las ayudantes no habían visto por elegir mal qué correr.
- Piezas compartidas (`pgshim`, `pgsesion`, funciones del turno, `conftest`, `_limpieza`) no se
  mudan ni cambian sin OK de la central: el único conflicto del día salió de dos ayudantes tocando
  `_tomar_turno` a la vez.

## 12 · Estado al 03/11/2026 (sesión central)

**Punta: `d3110a39`.** Medido sobre `6925830f` (la punta sólo suma un informe):
- Mac: **Postgres 7.291 / 0 en 590 s**, SQLite 7.277 / 0 en 350 s;
- **Railway → Supabase (us-west-1), suite entera: 7.286 / 0 en 1 h 49**, latencia mediana 2,7 ms
  (deployment `748fac9a`, 02/11 21:30 UTC). Primera corrida contra Supabase en cero (31/10: 239
  rojos; 02/11 mediodía: 4). Los 5 de diferencia con la Mac son `skip` (necesitan herramientas de
  la Mac), no fallas.

Nada publicado. Sin push.

### Qué entró desde la sección 11
| pieza | commit(s) | qué hace |
|---|---|---|
| Ensayo general del pasaje | `bbb8798e` | copia de prod del 16/08 (1.093 usuarios, 2,57 M filas) migrada y copiada a un PG local; paso a paso con tiempos en `audit/PASAJE_PASO_A_PASO.md`; secuencias que reusaban ids. |
| Backup nocturno con Postgres | `972e6e4c`, `2d48c653` | `pg_dump` con prueba de recuperación; «Backup OK» no miente; el motor se decide adentro. Ver `audit/BACKUPS_CON_POSTGRES.md`. |
| Empate del mismo día | `e801bdf9` | `orden_estable.py` copia el orden que SQLite da hoy (la última cargada primero) + guardián. **Si ese orden es el correcto es decisión de Nico (sección 6).** |
| Suite desde Railway | `2b7b63dd`, `36f85898` | servicio temporal `suite-supabase` con `Dockerfile.suite` (`RAILWAY_DOCKERFILE_PATH`); la URL con un Enter al final. Guía: `audit/SUITE_SUPABASE_DESDE_RAILWAY.md`. **El servicio se borró el 03/11.** |
| 239 rojos del 31/10 | `53a32d87` | ninguno de la app: un esquema por corrida (Supavisor deja 2 conexiones por cada `search_path` distinto), `RAILWAY_*` fuera del entorno de la suite, módulos «frozen» de Python 3.11, `-c search_path` con espacio, tests de hilos con tope de 15. |
| 3 rojos del 02/11 | `af185574` | las reconstrucciones de fondo (`mtm-backfill-*`) de una prueba pisaban la limpieza de la siguiente; `tests/_trabajo_de_fondo.esperar()` antes de cada prueba y de cada archivo. Medido con sondas, cadena de «por qué» en el commit. |
| Tarjeta del año | `c6ed50a3` | (cherry-pick de `e6ecc28c`) la cuenta esperada sigue al motor, no al almanaque. |
| Imagen de producción | merge `6925830f` (`1ce8abc5`, `696573cc`) | `Dockerfile` en la raíz (Python 3.11, `pg_dump` 17, venv, `exec uvicorn`); Railway deja de leer `railway.toml` el **2026-12-01**. **Probado en Railway el 03/11 (deployment `9067d027`): armó, arrancó, `imagen: Python 3.11.18 · pg_dump 17.11`.** Pasos de Nico antes de publicar: `audit/RAILWAY_SIN_CONFIG_AS_CODE.md` §7. |
| Tope de conexiones | merge `d3110a39` (`7bfb0f32`) | `audit/TOPE_CONEXIONES_SUPABASE.md`: con Pool Size 15 una publicación daba 69/80 errores 500. **Nico subió Pool Size a 24 el 03/11; medido: 24 de 24 a la vez.** |

### Supavisor (pooler de Supabase, modo sesión), medido
- Pool Size = tope de clientes a la vez; el siguiente se rechaza en el acto (`EMAXCONNSESSION`).
- Una fila por cada `search_path` distinto del DSN, que no suelta sus conexiones.
- `-csearch_path=x` (pegado) se ignora; `-c search_path=x` llega.
- La app NO reintenta si la base rechaza abrir una conexión: da 500. Propuesta sin hacer (pgshim
  es compartido): que `_Pozo.tomar` reintente unos segundos ante ese rechazo.

### Lo que falta para el pasaje
1. **Auditoría final** con una sesión nueva sobre `claude/migracion-pg-oct`, y el OK de Nico.
2. **Publicación aparte** `claude/import-renombre-prod` (renombre durante import + tokens): sigue
   esperando su auditoría y el OK.
3. **Decisiones de Nico** (sección 6): orden del mismo día, los 21 de 7 lentes, paywall,
   `credit_ledger` / `_marcar_bienvenidas_previas`, PITR.
4. **Pasos de Nico en el panel de Railway** antes del 1/12 (`RAILWAY_SIN_CONFIG_AS_CODE.md` §7):
   Healthcheck Path, `RAILWAY_HEALTHCHECK_TIMEOUT_SEC`, `RAILWAY_DEPLOYMENT_DRAINING_SECONDS`.
5. El aviso ⚠ del volumen `trading-volume` en Railway: **sigue sin leerse.**
6. 1/12: `BACKUP_LOCAL_KEEP_DAYS=7`, después de comprobar que R2 tiene un archivo por noche.

### Deuda que se sabe y no se tocó
- **113 limpiezas `DELETE … except Exception: pass` en 102 archivos de pruebas.** En Postgres
  el primer error aborta la transacción y las demás fallan en silencio: esconden la causa real
  (así se ocultó lo de `af185574`). Arreglo propuesto: un helper único (`tests/_limpieza`) con
  punto de guardado, y un guardián que no deje volver el patrón.
- `main._imagen_del_proceso` y `backup_db._version_mayor` leen la versión de `pg_dump` cada uno
  a su manera (el registro muestra `17.11-1.pgdg12+2)`); el respaldo la entiende bien (17). Unificar.

## 13 · Estado al 03/11/2026 15h — lo publicado ya está adentro

**Punta: `fbb9a25c`.** Mac: **Postgres 8.051 / 0** (16 min 42 s), **SQLite 8.040 / 0** (8 min 11 s).
Nada publicado.

| pieza | commit(s) | qué hace |
|---|---|---|
| Auditoría final | `807824cb` (`a11353ee`) | `audit/AUDITORIA_FINAL_PG.md`: «se puede pasar después de 2 cosas» (P2, P3). P1 (candado del arranque) **descartado midiendo en Supabase**: Supavisor limpia los candados al soltar la conexión. Ojo: `pg_try_advisory_lock` es reentrante, así que la receta original daba «bien» aunque estuviera mal. |
| Merge de `origin/main` | `e94cad70` (`dd99cb0d`, 433 commits) | 12 choques, detalle en el commit. `_init_db_postgres` = tesis antes + `_esquema_pg_al_dia` + `_borrar_marcas_sueltas` después. `mkschema.py` regenerado aparte = `schema_pg.sql` mezclado, sin diferencias. |
| Guardianes después del merge | `787e536b`, `f866338f` | el censo del turno resuelve `_colgadas_de_alerts` (con prueba contra el esquema real); `sell_position_fifo` en `NO_APLICA` (medido; un punto de guardado ahí rompía SQLite: el RELEASE sin transacción la confirma). |
| Pasos 3 y 8 del día | `679f3d7e` (`d911dc25`) | `PASAJE_PASO_A_PASO.md` reescrito (P2, P3, A2). El respaldo con la app cerrada **necesita además la sesión de admin de Nico** (contraseña oculta en la terminal). |
| Script del día + motor en salud | `ccef4128` (`c1abba67`) | `scripts/pasaje_con_mantenimiento.py` con pruebas contra la app real; `/api/health` dice `"motor"`; una sola lectura de la versión de `pg_dump`. |
| Termómetro en las pruebas | `fbb9a25c` | el cron de alertas largaba el termómetro real (Yahoo, >4 min) y dejaba la corrida tomada: 8 rojos en `test_termometro` según la hora. Venía de main. |

### Lo que falta
1. Antes del pasaje, volver a mezclar `origin/main` si se publicó algo después de `dd99cb0d`, y correr las dos suites.
2. Opcional: suite contra Supabase desde Railway con este código (el servicio `suite-supabase` se borró; la guía está en `SUITE_SUPABASE_DESDE_RAILWAY.md`).
3. Nico: el aviso ⚠ del volumen; la ventana del día (paso 0); los pasos del panel de Railway antes del 1/12; las decisiones de §6; confirmar la URL de producción (paso A0).
4. Ensayar la bajada desde R2 (paso B del instructivo).
