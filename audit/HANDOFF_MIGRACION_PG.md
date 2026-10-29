# HANDOFF — Migración SQLite → Postgres (Supabase)

> Escrito el 28/10/2026 por la sesión «Rendi SQLite a Postgres migración», para
> que otra sesión siga **toda** la migración sin depender de ningún chat.
> Este archivo vive en la rama a propósito: un handoff en un mensaje se pierde.
>
> **Leelo entero antes de tocar nada.** La sección 1 tiene un paso que, si se
> saltea, puede pisar en silencio arreglos de plata que costó una semana medir.

---

## 0 · En dos líneas

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
