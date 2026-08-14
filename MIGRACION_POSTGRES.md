# Migración SQLite → Postgres (Supabase) — estado y prompt de continuación

Última sesión: 2026-08-14 (sesión 6). Pegá el bloque de abajo en una sesión nueva.

---

Estoy migrando Rendi (app de tracking de inversiones, ~1.084 usuarios reales, plata
de verdad) de SQLite a Supabase/Postgres. Soy founder, no programador: explicame en
palabras simples y mostrame los cambios antes de aplicarlos.

Hay una sesión previa que dejó trabajo hecho. NO empieces de cero.

## Por qué migramos

No es por espacio: es porque **SQLite tiene un solo escritor para toda la base**.
Los días 12 y 13 de agosto la app se cayó dos veces con `database is locked`
masivo, con usuarios adentro. Ya arreglamos los tres culpables (abajo), pero el
techo es estructural: con más usuarios vuelve. Postgres lo resuelve de raíz.

## Dónde está el trabajo

    /private/tmp/claude-501/-Users-nicolaspussetto-Documents-trading/adc4a925-dbdb-4165-a5e3-826b55c1200c/scratchpad/mainwt

Rama **`spike/postgres`**. **NO se deploya** — es un spike.
Producción va por `main` y está estable (`8f4edfe`).

⚠️ macOS purga `/private/tmp` en sesiones largas. Si el worktree no está, los
commits sobreviven en el repo: `git worktree add <ruta> spike/postgres`.

## Qué ya está hecho y medido

- **`backend/pgshim.py`** — capa que traduce SQLite→Postgres en UN lugar, así el
  90% de las ~1.400 llamadas con SQL crudo no se toca. Traduce `?`→`%s` (respetando
  los `?` adentro de strings), `%`→`%%`, `lastrowid`→`RETURNING`, `strftime`→`substr`,
  `datetime('now')`→`to_char`, `INSERT OR IGNORE`→`ON CONFLICT DO NOTHING`,
  `True/False`→`1/0`. 13 tests en `tests/test_pgshim.py`, todos verdes.
- **`backend/schema_pg.sql`** — 58 tablas, 62 índices, 12 FKs. Aplicado en Postgres
  16: 132/132 sentencias OK. Generado por `../mkschema.py` desde el schema FINAL de
  SQLite (no traduciendo las 46 migraciones incrementales: son la historia, Postgres
  sólo necesita el resultado).
- **Interruptor `DATABASE_URL`** en `main.py`: sin la variable, todo sigue en SQLite
  y no cambia nada. Con ella, la MISMA suite corre contra Postgres.
- **Audit de datos sobre PRODUCCIÓN** (`GET /api/admin/pg-type-audit`, ya deployado):
  425 columnas, 60 tablas → **LIMPIO**. No hay texto en columnas numéricas ni nulls
  donde no van. El riesgo grande de la migración está descartado con datos reales.
- **Medición**: **98,4%** (2.850 de 2.896) y **0 fallas propias de la migración**
  (las 46 que quedan fallan igual en SQLite). Suite COMPLETA en
  **1 minuto**, **y el número significa algo**: cero timeouts y cero errores de
  infraestructura (ver la sección del aislamiento). Antes de arreglar eso el
  porcentaje no era ni reproducible — la misma suite en el mismo commit daba
  77,4% en una corrida y 71,9% en otra, según qué se trababa con qué.

## Sesión 13/08 (tarde) — hecho y medido

Commit `36a2974`. De 68,8% a 77,4% (+271 tests). **Cero regresiones en SQLite**:
verificado corriendo la suite con y sin los cambios y comparando falla por falla —
las mismas 46 preexistentes, ni una más.

- **Los 15 de `PRAGMA table_info` + `sqlite_master`: en UN lugar, no en 15.** Se
  revisó uno por uno: ninguno de los 9 de `main.py` necesita más que el NOMBRE de la
  columna (todos hacen `r[1]` o `c["name"]`). El único que lee el tipo es
  `scripts/pg_type_audit.py`, que corre contra SQLite a propósito. Verificado contra
  el esquema real: 58 tablas, 0 diferencias de columnas ni de orden.
- **Con caché, y el caché no es opcional.** La primera versión andaba pero BAJÓ el
  resultado (1960→1734). En SQLite preguntar las columnas es gratis; en Postgres es
  una consulta, y `_table_cols()` se llama ~20 veces por request. Era un problema de
  PRODUCCIÓN disfrazado de problema de tests: contra Supabase serían ~20 viajes por
  pantalla. Se invalida con cualquier DDL — sin eso `init_db()` creería que una
  columna ya está y se la saltearía.
- **Fechas con modificador: 15 sitios, no 12.** `datetime('now')` ya se traducía;
  `datetime('now','-7 days')` no. Faltaban en la cuenta a mano: `date(MIN(x),'+7
  days')` (el paréntesis cortaba el match) y dos `date(columna)` que Postgres ACEPTA
  pero devolviendo un objeto fecha en vez del texto `'YYYY-MM-DD'`. Probado corriendo
  la misma expresión en las dos bases: **15 de 15 idénticos**, con bisiesto y fines
  de mes. Lo que no sabe traducir, LEVANTA error explícito.
- **`MIN(a,b)`/`MAX(a,b)` → `LEAST`/`GREATEST`** (2 sitios). En Postgres son
  agregados de UN argumento: no dan otro resultado, no existen. Se cuentan paréntesis
  y no se usa regex: confundir `MIN(COALESCE(a,0))` con dos argumentos cambiaría una
  consulta en silencio.
- **Fechas mal formadas** (3 sitios). SQLite daba NULL y la fila se salteaba sola;
  Postgres corta con error. Se filtran ANTES del `CAST` con un `LIKE '____-__-__%'`
  que se comporta igual en los dos motores. Uno de los 3 no tenía ni el filtro de
  nulos y agrupaba por año/mes: una sola fecha rota tiraba abajo el agregado entero.
- **FCI `price REAL` → `DOUBLE PRECISION`.** Esa tabla se crea fuera del esquema
  (`pricing/fci.py:177`) así que no pasa por el traductor de tipos; en Postgres `REAL`
  son 4 bytes y redondeaba los precios. En SQLite es idéntico.

## La incógnita del plazo: RESUELTA

Las `AssertionError` **no eran diferencias semánticas**. Verificado, no asumido:
bajaron de 42 a 27 **sin tocar un solo test**, sólo arreglando los errores de fecha.
De las 38 originales: 15 eran cascada visible, 14 ya fallaban en SQLite
(preexistentes: parsers, clasificación de noticias, un test de threads), 9 eran
cascada silenciosa. **No apareció ninguna diferencia semántica real.**

El mecanismo de las 9 silenciosas es el que hay que tener presente: el error de
Postgres cae adentro de un `try/except Exception` (ej. `billing/subscriptions.py`),
se traga, y la función devuelve un default. **El usuario ve un número equivocado, no
un error.**

## Lo que falta

**CERO fallas propias de la migración** (sesión 6). Postgres queda en **46 fallas y
las 46 fallan IGUAL en SQLite** — son las preexistentes de siempre. Medido con la
suite COMPLETA en los dos motores y comparado test por test.

| | antes (`bf5226a`) | ahora |
|---|---|---|
| Postgres | 57 fallas (2.790 pasan) | **45-46 fallas (2.854 pasan)** |
| SQLite | 46 fallas (2.795 pasan) | **45-46 fallas (2.847 pasan)** |
| **fallas estables, sin el flaky** | — | **45 en los DOS motores, idénticas** |
| fallas SÓLO de Postgres | 11 | **0** (salteadas, no arregladas) |
| regresiones | — | **0 en los dos motores** |

⚠️ **El "45-46" es UN test preexistente que flipea, y flipea en los DOS motores:**
`test_cedear_usd_price::SnapshotsJobCedearTest::test_snapshot_converts_bac`.
Sacándolo de la cuenta, los dos motores dan **exactamente las mismas 45 fallas**, y
"propias de Postgres" da 0 sin ninguna aclaración. Si una corrida lo muestra como
"propia de Postgres" es porque SQLite lo acertó esa vez, no porque haya una
diferencia de motor.

**Cobertura tapada: ninguna, y la cuenta cierra exacta.** En Postgres los +41 que
pasan son los cuatro archivos nuevos; los +7 skips son los tests de
`test_verificar_copia` que piden `PG_DSN_VERIF`. En SQLite los +9 skips son los 9
tests nuevos de `test_pgshim_pk_cache`, que ahí no aplican (el caché de PKs sólo
existe en modo Postgres). Ningún test que pasaba antes se volvió skip.

⚠️ **Los 11 de `Connection.backup` NO se arreglaron: se SALTEARON.** Están marcados
`skipIf(USANDO_PG)` porque la herramienta quedó sólo-SQLite por decisión. La
diferencia importa al leer la tabla: "propias: 11 → 0" no quiere decir que ahora
anden, quiere decir que ya no se cuentan.

⚠️ **Comparar SIEMPRE contra la baseline de SQLite antes de llamar "nueva" a una
falla.** El total de Postgres arrastra las 46 preexistentes y da una sensación de
deuda que no existe.

### 🔴 El número no era reproducible, y eso era más grave que las fallas

**Medido:** la misma suite, en el mismo commit, dio **46, 47 y 49** fallas en
corridas distintas, **con víctimas distintas cada vez** (una vez un test del
asesor, otra los 3 de `test_orden_filas_pool` con `NotNullViolation` en
`brokers.user_id`). Nueve corridas aisladas dieron 46 las nueve.

**La causa NO era una fuga adentro de la suite: era otra suite corriendo al mismo
tiempo contra la misma base.** La firma quedó en el traceback:
`AdminShutdown: terminating connection due to administrator command`. El único
lugar del proyecto que llama a `pg_terminate_backend` es `conftest.py:150`, y lo
hacía sobre **TODOS** los pids de la base. Dos cosas se pisaban:

- el `pg_terminate_backend` mataba las conexiones de la corrida de al lado, en
  medio de un test;
- los nombres de esquema salían del nombre del módulo, o sea que las dos corridas
  **usaban el mismo** y una dropeaba el esquema que la otra estaba usando.

**Arreglado**: el pid va en el `application_name` de cada conexión **y** adelante
de cada nombre de esquema, más un barrido de los esquemas que dejó una corrida
muerta (con `os.kill(pid, 0)` para no borrarle los suyos a la corrida de al lado).

**Verificado con el detector, no con una corazonada.** Lanzando a propósito un
segundo pytest contra la misma base mientras corre la suite completa:

| | antes | después |
|---|---|---|
| fallas | **49** | **46** |
| `AdminShutdown` en el log | 10 | **0** |

Test: `tests/test_aislamiento_entre_corridas.py`.

**Por qué importa más que tres fallas:** este proyecto se pasó tres sesiones
logrando que el número de la suite SIGNIFIQUE algo (antes daba 77,4% y 71,9% en el
mismo commit según qué se trabara con qué). Un número que cambia según lo que corra
en otra terminal es el mismo problema disfrazado, y arruina la única herramienta
que tenemos para decir "esto no rompió nada".

### 🔴 Y adentro apareció un bug de PRODUCCIÓN: `lastrowid` = None en silencio

El `NotNullViolation` en `brokers.user_id` no lo causaba el broker: lo causaba el
`lastrowid` del INSERT anterior, que volvía `None`. Reproducido de forma
determinística, fuera de los tests.

`pgshim` emula `lastrowid` agregando `RETURNING "<pk>"`, y para eso lee la PK del
catálogo y la cachea. Dos defectos juntos:

1. **La invalidación era asimétrica.** Un `CREATE TABLE` limpiaba `_COLS_CACHE`
   pero **no** `_PKS_CACHE` (`:868`). Una tabla creada después del primer INSERT
   del proceso quedaba "sin PK" para siempre.
2. **"No la encontré" y "no tiene PK" eran el mismo `None`.** Y como se creía que
   había tablas sin PK, `None` parecía normal.

Y el caso peor: si el catálogo devolvía CERO tablas (esquema equivocado, o recién
dropeado por el otro proceso), se cacheaba ese vacío y **todas** las tablas
quedaban sin PK. A partir de ahí cada INSERT devolvía `lastrowid=None` **sin
ningún error**, y las claves foráneas entraban en NULL.

**El modo de falla es el que más caro sale en este proyecto: el error se convierte
en un número equivocado.** Con `NOT NULL` se ve como un error una fila más tarde;
sin `NOT NULL`, queda una fila colgada de nada.

**¿Muerde en producción?** Medido: en un arranque real el caché **ni se carga**
durante `init_db` — en Postgres `init_db` no pasa por el shim, usa psycopg crudo
(`main.py:539-549`). O sea que el caché se llena en el primer INSERT de la primera
request, con las 58 tablas ya creadas. **Pero hay tablas que se crean EN CALIENTE,
fuera de `init_db`** (`pricing/fci.py:177` y `:188`), y ésas caen justo en la
ventana.

**Arreglado**: un fallo de caché **relee el catálogo una vez** antes de concluir
"no tiene PK", el negativo se memoiza en `_SIN_PK` (para no pagar una consulta por
INSERT), el DDL invalida **los tres** cachés, y un catálogo vacío **levanta** en vez
de cachearse.

Test: `tests/test_pgshim_pk_cache.py`. **Verificado que falla con el comportamiento
viejo**: con el `_pk_de` original, `lastrowid` vuelve `None` y 3 de los 5 tests se
caen.

#### ⚠️ Las dos defensas se TAPABAN entre sí en los tests

Es la lección más reusable de todo esto. El arreglo tiene **dos** mecanismos
independientes, y el "verificado que falla con el comportamiento viejo" se había
hecho sacando **los dos a la vez**. Mutando cada uno por separado:

| se muta | resultado |
|---|---|
| sólo A (el DDL limpia sólo `_COLS_CACHE`) | **5 passed** — no lo agarra |
| sólo B (sin la relectura del catálogo) | **5 passed** — no lo agarra |
| las dos juntas | 2 failed ✅ |

O sea: alguien podía borrar **una** de las dos y el CI quedaba verde. Y las dos
existen por motivos distintos, así que perder cualquiera es perder cobertura real.

**Ahora hay un test por defensa**, y mutando cada una por separado caen 3 y 3:

- **Defensa A** — `DefensaA_ElDDLInvalidaLosTresCachesTest`. Assertea sobre el
  **ESTADO del caché**, no sobre `lastrowid`: un test que mirara `lastrowid` no
  puede aislar A, porque la relectura de B lo rescata igual. Y **no llama a
  `limpiar_caches()`**: ése es el camino manual que usan los fixtures, y usarlo
  tapaba exactamente lo que se quiere medir.
- **Defensa B** — `DefensaB_LaRelecturaAnteUnFalloDeCacheTest`. La tabla la crea
  **OTRA conexión**. Ése es el escenario de PRODUCCIÓN y el que la suite no cubría:
  en los tests viejos el `CREATE TABLE` pasaba por el shim, así que la invalidación
  de A limpiaba el caché y la relectura no hacía falta nunca. En producción el DDL
  lo corre otro proceso (`pricing/fci.py:ensure_tables`, los workers), nuestro
  proceso no se entera, y lo único que evita el `lastrowid=None` es la relectura.

**La regla, para la próxima: si un arreglo tiene N defensas, mutá las N por
separado.** Mutarlas juntas prueba que el arreglo *entero* sirve, no que cada parte
haga falta — y es justo lo que hace que una se pueda borrar sin que nadie se entere.

#### La misma forma apareció en OTROS TRES lugares de esta sesión

Se la buscó a propósito, como categoría, en todo lo que se tocó. Los tres estaban
igual: dos mecanismos, un solo test, y el test lo satisfacía cualquiera de los dos.

| dónde | las dos defensas | ahora |
|---|---|---|
| **el tope del backfill** | el corte de TANDA (`return`) y el salteo POR USUARIO (`continue`) | 2 tests nuevos: una tanda MIXTA (un usuario que pasa el tope adentro de una tanda abortada) y una con UN solo frenado (donde la tanda no aborta). Mutando cada freno cae **su** test |
| **el hash de fila** de la verificación | el prefijo de largo y el separador `\x1f` | 2 tests con colisiones reales: `('1','abcdefghi1k')` vs `('11abcdefghi','k')` colisiona sin separador; `('a\x1fb','c')` vs `('a','b\x1fc')` colisiona sin prefijo |
| **el aviso 501 del ensayo por clon** | el `exigir_clon_soportado` y el pase-directo del `except` | ver abajo: era peor que un tapón, era un agujero |

⚠️ **Del tope del backfill, el detalle que importa:** los tests que había armaban 4
usuarios y a los 4 les hacían borrar 10 de 10 — o sea que los 4 quedaban frenados y
el salteo individual los cubría uno por uno. **El corte de tanda nunca era lo que
salvaba nada**, y sacándolo la suite quedaba verde. Con una tanda MIXTA (un usuario
que borra 2 de 10, que pasa el tope, junto a tres que borran todo) el corte es lo
único que impide escribirle a ese usuario mientras el resumen dice "no se escribió
nada". Ahora hay un test para eso.

#### 🔴 Y el aviso 501 era CÓDIGO MUERTO para 6 de los 7 endpoints

El docstring del handler afirmaba —lo escribí yo— que *"el único endpoint que
necesita además una línea propia es `admin_backfill_recompute`"*. **Falso.** Son
SIETE los endpoints admin que pueden llegar a un clon, y **seis** tenían un
`except Exception` que se tragaba la excepción antes de que llegara al handler:
`admin_backfill_mtm` y `admin_backfill_currency` (clonan a través de sus scripts) y
los tres `admin_fx_migrate_*` (clonan directo). Seguían devolviendo el mismo 500
críptico que el arreglo decía haber eliminado.

Arreglado en los 8 `except Exception` de esos endpoints, más un **barrido con AST**
(`NingunEndpointSeTragaElAvisoTest`) que falla si aparece el octavo — porque
arreglar seis a mano deja el problema esperando al séptimo. Verificado sacando el
pase de UN endpoint: el barrido lo nombra.

#### ⚠️ Y un dato falso más: "18 tablas sin PK" era CERO

El comentario de `pgshim` decía que había 18 tablas sin clave primaria, y eso
sostenía la idea de que un `None` de `_pk_de` era "a veces normal". **Es falso.**
Verificado por tres caminos independientes:

    schema_pg.sql (texto)          58 tablas, 0 sin PK
    catálogo real de Postgres      58 tablas, 0 sin PK
    init_db de SQLite              58 tablas, 0 sin PK

Y las 2 que `pricing/fci.py` crea en caliente también tienen PK (`symbol TEXT
PRIMARY KEY` las dos). **El 18 salió de contar tablas sin columna `id`**, que es
otra cosa: `config` tiene `PRIMARY KEY (key, user_id)`, `fx_rates_daily` la tiene
en `date`, `asset_last_price` en `symbol`. Es el quinto conteo mal hecho del
proyecto, y del mismo tipo que los otros cuatro: **medir una cosa y nombrarla como
otra.**

**Y la corrección importa más que el número.** Si ninguna tabla puede quedarse sin
PK, entonces un `None` de `_pk_de` es **siempre** un bug, no "a veces normal" — y
tratarlo como caso esperado es justamente lo que hacía que el bug se escondiera tan
bien. Se tradujo a tres cosas:

- **Un test estructural** (`TodasLasTablasTienenPKTest`) que exige PK en todas las
  tablas del esquema. Si mañana alguien agrega una sin PK, tiene que decidirlo a
  propósito y no colarse haciendo que `lastrowid=None` vuelva a parecer normal.
- **La decisión escrita** de qué hace `_pk_de` cuando no encuentra la tabla después
  de releer: **devuelve `None` y LOGUEA un warning, no levanta.** El motivo está en
  el código: una migración futura podría agregar legítimamente una tabla sin PK, y
  convertir eso en "la app no arranca" es peor que un `lastrowid=None` en una tabla
  a la que nadie le pide el lastrowid. El riesgo que importaba —una tabla que SÍ
  tiene PK devolviendo `None`— ya lo cierra la relectura.
- **Un bug que apareció por el camino:** 11 de las 58 tablas tienen **PK
  compuesta**, así que el catálogo devuelve varias filas por tabla. La consulta no
  tenía `ORDER BY`, o sea que se quedaba con "la que llegara primero" —no
  determinístico— y mi primera versión del arreglo cambió `setdefault` por
  asignación directa, que la volvía "la última". Ahora se **elige**: gana la columna
  de identidad (que es la que de verdad emula el `lastrowid` de SQLite) y, si no
  hay, la de menor `attnum`. Con sus dos tests.

**Las DOS víctimas observadas eran el mismo bug**, y eso es lo que cierra el caso:
`test_advisor_plan` hace `INSERT INTO brokers (user_id, …)` con el id que devolvió
el INSERT anterior (`test_advisor_plan.py:57-60`) — la misma forma exacta que
`test_orden_filas_pool`. Las dos fallas de más son "el id que devolvió un INSERT
vino `None`".

### ⚠️ Quedaban DOS tests flaky más, y ninguno era de la migración

Arreglado lo del conftest, cinco corridas seguidas dieron **46, 46, 46, 47 y 47** —
pero las dos de 47 fallaron en tests DISTINTOS, y ninguno tenía que ver con
Postgres. Eran dos defectos independientes de tests, los dos escondidos detrás del
mismo síntoma ("a veces da 47").

**El del RELOJ — arreglado.**
`test_pgshim::test_las_fechas_con_modificador_dan_LO_MISMO_que_sqlite`. Comparaba
con `==` exacto dos lecturas de `now()` tomadas en **instantes distintos**: una a
Postgres por la red y otra a un SQLite en memoria. Cuando el borde de segundo caía
entre las dos:

    AssertionError: assert '2026-08-14 10:35:47' == '2026-08-14 10:35:48'

Era culpa del test, no de la traducción. Ahora exige lo que de verdad quiere probar
y **con más dureza que antes**: el FORMATO carácter por carácter (una `T` de más o
unos microsegundos romperían las comparaciones de string del código) y el MOMENTO
con 2 segundos de gracia — que es la distancia entre las dos lecturas, no una
tolerancia sobre el resultado. **Dos segundos no pueden tapar nada**: el modificador
más chico que traducimos es de UNA HORA.
Verificado mutando la traducción en dos direcciones: con una hora de más → falla;
con formato ISO (`T` en vez de espacio) → 5 fallas con el mensaje del formato.

**El de la RED — NO se tocó, a propósito.**
`test_ai_builders_phase2::TestHomeBuilder::test_shape_with_empty_db` sale a
internet: `build()` → `get_indices_strip()` → `_fetch_batch_quotes()` →
`yf.download(['ETH-USD','BTC-USD','^GSPC','^MERV',…])`, una consulta real a Yahoo
Finance. Cuando Yahoo tarda más de 10s, el `--timeout=10` la mata:

    E   Failed: Timeout (>10.0s) from pytest-timeout
    /…/yfinance/multi.py:158: Failed

Corriendo el test solo pasa 8 de 8; sólo aparece con la suite completa, que es
cuando la máquina está cargada. **Es un defecto de diseño de un test preexistente**
—un test unitario no debería salir a la red— y no de la migración: parece de
Postgres nada más porque la corrida de Postgres es la que lleva `--timeout=10` y la
de SQLite no. Mockearlo es tocar un test ajeno por un motivo distinto del que
estamos trabajando, así que queda anotado y no cambiado.

**Recomendación**: mockear `yf.download` ahí. Mientras tanto, si una corrida da 47 y
la falla de más es ésa, **es la red, no una regresión** — miralo en el traceback
antes de salir a buscar nada.

### Fuga entre módulos que SÍ existe pero hoy no muerde: `_rate_store`

Apareció en la revisión de código y conviene anotarla antes de que sorprenda. El
rate limiter guarda en un dict global con clave `f"{ip}|{suffix}"` (`main.py:301`).
En los tests la IP es siempre `"testclient"` y los uid **reinician con cada
esquema**, así que las cuentas se acumulan entre módulos y nadie las resetea (sólo
hay 4 `pop` y todos en un archivo). Hoy no rompe nada —ningún test pega
`/api/register` y ninguna de las fallas observadas está detrás de un límite— pero
es una fuga real: el día que un test nuevo caiga detrás de un rate limit, va a
fallar según qué módulo corrió antes. **No se tocó**: arreglarlo sin una falla que
lo demuestre sería cambiar código por una corazonada.

### `Connection.backup`: FUERA DEL CAMINO CRÍTICO — marcado sólo-SQLite

**DECISIÓN TOMADA (sesión 6): no se migra ahora.** Son herramientas de admin, no
están en el camino de ningún usuario, y eran el único ítem que le quedaba a la
migración. Se resuelve después del cambio, sin apuro. El diseño de las tres
opciones queda escrito más abajo para retomarlo.

Lo implementado es el aviso, no el reemplazo:

- `dberrors.exigir_clon_soportado(conn, herramienta)` corta ANTES de intentar el
  clon. Pregunta por la **capacidad** (¿es una conexión sqlite3 de verdad?) y no
  por la variable de entorno: es la precondición real, y así tampoco se cuela una
  conexión del shim por un camino que no mire `DATABASE_URL`.
- Puesto en los **4 sitios que clonan**: `recompute_backfill._clone_db` (el helper)
  y las 3 copias pegadas a mano en `main.py` (reparar snapshots, migrar TC, migrar
  TC en lote). El quinto `.backup()` del código —`scripts/backup_db.py`— **no se
  toca**: ese es el backup nocturno de verdad, no un ensayo.
- Un **handler de la app** lo convierte en **501** con el mensaje explicativo. 501
  y no 500 a propósito: no se rompió nada, es una capacidad que este motor no
  tiene. `admin_backfill_recompute` necesita además una línea propia
  (`except EnsayoPorClonNoDisponible: raise`) porque su `except Exception` se lo
  tragaría antes de llegar al handler.
- **Antes**: `500 "backfill falló: AttributeError: 'Connection' object has no
  attribute 'backup'"`. **Ahora**: `501` con qué pasa y qué hacer.
- Los 11 tests quedan `skipIf(USANDO_PG)` — son **7 métodos**, no 11: tres clases
  heredan de otra (`GuardEscalaTest`/`BatchDryRunTest` de `FxMigrateTest`,
  `SnapshotFuturoTest`/`CleanupFuturosEndpointTest` de `RepairUserHistoryTest`).
- Test nuevo `tests/test_ensayo_clon_solo_sqlite.py`, **verificado que FALLA con el
  comportamiento viejo**: sacando los guards, los dos tests de punta a punta se caen
  con el `AttributeError` de arriba.

⚠️ **Dato que apareció escribiendo el test y conviene saber:** `safe_backfill` corta
antes de clonar si **ningún usuario de la tanda tiene posiciones** (`with_pos`
vacío → `return`). O sea que el aviso sólo se dispara cuando hay trabajo real que
hacer. Un test con un usuario recién creado devuelve 200 y **pasaría por el motivo
equivocado**.

### El diseño del reemplazo, para retomarlo

El ensayo (dry-run) del backfill **no calcula qué pasaría: lo hace y lo mira.**
Clona la base entera a un archivo con `sqlite3.Connection.backup()`, corre el
backfill DE VERDAD sobre la copia, y resta la foto de antes contra la de después.
En Postgres esa fotocopia no existe. Son 9 call-sites (1 helper + 3 copias pegadas
a mano en `main.py` + los scripts).

**Tres hechos verificados que condicionan cualquier reemplazo:**

1. **El ensayo ESCRIBE**, y mucho: borra posiciones, borra operaciones de venta,
   reinserta, corrige unidades de bonos y comisiones, recalcula P&L. No existe
   ninguna versión "sólo lectura" de esto.
2. **`run_backfill` commitea SIEMPRE** (`recompute_backfill.py:413`), sea ensayo o
   no. El propio docstring dice: *"Para dry-run, pasar una conn a una COPIA — ahí
   el commit es inocuo"*. Todo el diseño se apoya en eso. Es lo que mata la idea
   obvia de "corré todo y hacé ROLLBACK al final".
3. **El clon está adentro del camino de APLICAR, no sólo del de simular.** En el
   modo `safe_only` el clon se usa como **PIZARRÓN**: `safe_backfill` calcula el
   estado ideal en la copia y, **si `apply=true`**, escribe los cambios seguros en
   la base real (`_apply_safe` → `real_conn.commit()`, `:568-571`). Por eso sacar
   el clon no es "perder el dry-run": también se lleva puesto el modo que ya corrió
   en producción sobre 830 cuentas.

> ⚠️ **CORRECCIÓN (sesión 6). Una versión anterior de este doc decía que el botón
> "Simular" «simula y escribe en la misma llamada». Es FALSO**, verificado en las
> tres capas. El error fue confundir DOS interruptores distintos:
> · **`safe_only`** elige QUÉ cambios se consideran (sólo los inequívocos vs. todos).
>   Su default es `true`.
> · **`apply`** elige SI se escribe. Su default es `false` (`main.py:14694`), y la
>   escritura entera está detrás de un `if apply:` (`recompute_backfill.py:568`).
> Con `safe_only=true, apply=false` —que es exactamente lo que manda el botón
> "Simular"— el código clasifica sobre la copia y **no toca la base real**.
> La UI ya tiene los dos botones separados (`Admin.jsx:1050` simular →
> `runChunks(false)`; `:1057` aplicar → `runChunks(true)` con `confirm()`), y el
> texto de la propia app ya lo dice bien: *"Simular corre sobre una copia (no toca
> nada); recién Aplicar modifica"*.
> **Lo que sí es cierto del mismo hallazgo es el tope que falta — ver abajo.**

**Las tres opciones evaluadas** (cada una atacada por un escéptico buscando la
secuencia exacta en que escribe de verdad):

| | garantía | en el peor momento | ¿sirve en los 2 motores? |
|---|---|---|---|
| **A.** Transacción + `ROLLBACK` | condicional | **escribe de verdad** | no en producción |
| **B.** Usuario sin permiso de escribir + tablas sombra | **estructural** (el motor rechaza cada sentencia) | el ensayo se cae a los gritos | **sí, sin bifurcar** |
| **C.** Esquema paralelo + usuario aparte | estructural, mal ubicada | puede dejar un clon vacío | no, bifurca |

- **A se cae.** El `rollback()` por usuario (`:361`) que el motor hace para seguir
  con el siguiente **desarma la propia red de seguridad**, porque la red también
  es una escritura que queda adentro de la transacción. Y la red es de un solo
  uso. El síntoma sería una línea más en "errores" del panel: el error sale como
  número equivocado, no como error.
- **C** pone la pared en el peor lugar: protege al backfill (código viejo y
  probado) y no a las ~80 líneas nuevas que arman el clon. Además el caché de
  `pgshim` es global al proceso e indexado sin esquema: es un túnel entre el
  ensayo y producción que ningún permiso puede tapar.
- **B** es la única que no pelea contra el código actual (los commits de adentro
  caen en la copia y son inocuos) y la única que se estrena en los tests contra
  los DOS motores, en vez de estrenarse en producción el día que se prenda
  `DATABASE_URL`. Necesita tres reglas no negociables: commitear las sombras
  apenas se crean (si no, el `rollback` del primer usuario que falla las borra y
  el resto de la tanda le pega a la tabla REAL), el canario ANTES de crearlas, y
  las sombras sin `ON COMMIT`.

### ⚠️ Lo que hay que arreglar ANTES, y no es ninguna de las tres

Verificado en el código: **`_apply_safe` borra posiciones** (`DELETE FROM positions`,
`:516`) y **no hay ningún tope de cordura en todo el archivo**. Si la copia queda
vacía o incompleta, `_classify_safe` lee "esto tenía cantidad y ahora es cero", lo
marca como fantasma y `_apply_safe` **borra la fila real**. Lo que ve el usuario:
abre la app y no están sus acciones. Recuperable sólo desde backup.

**Es el riesgo más grande y el más barato de arreglar**, y sigue en pie aun sabiendo
que "Simular" no escribe: el camino de aplicar existe, ya corrió sobre 830 cuentas,
y hoy no tiene ningún freno. El arreglo es un piso del tipo "si esta tanda borraría
más del X% de las posiciones, abortá y reportá". **Vale más que cualquiera de las
tres opciones y no depende de la migración.**

(La otra mitad de la propuesta vieja —"partir `safe_backfill` en dos caminos"— **ya
está hecha**: el parámetro `apply` es exactamente esa partición.)

#### ✅ HECHO (sesión 6): el tope, con los números que eligió el dueño

**Por usuario:** frená a ese usuario si borrarías **más del 50%** de sus posiciones
**y** eso son **5 filas o más**.
**Por tanda:** abortá la tanda entera, sin escribir nada, si **más del 25%** de los
usuarios con cambios quedaron frenados **y** son **3 o más**.

- **Los pisos absolutos (5 y 3) no son decoración.** Sin ellos el porcentaje frena
  trabajo legítimo: alguien con 2 letras vencidas pierde el 100% de sus posiciones
  y está perfecto. Un freno que salta en casos buenos se vuelve ruido que uno
  aprende a ignorar, y entonces no protege de nada.
- **Los dos topes tienen trabajos distintos.** El de usuario protege a cada
  persona; el de tanda detecta que el problema es del PROCESO — si la copia salió
  mal, TODOS dan "borrá todo" a la vez, y eso no pasa por casualidad.
- **`safe_backfill` ahora corre en DOS PASADAS y el orden ES el arreglo**:
  planifica a todos sin escribir → revisa los topes → recién ahí escribe. Si
  escribiera a medida que avanza, el tope de tanda no serviría para nada: para
  cuando detectara el problema, los primeros usuarios ya estarían borrados. (Es
  el mismo error de orden que el de los relojes del `conftest`.)
- **El ensayo calcula los mismos planes y reporta los mismos frenos**, así
  "Simular" avisa ANTES de que aprietes "Aplicar".
- **`_apply_safe` se BORRÓ** en vez de dejarla "por compatibilidad": no la llamaba
  nadie de afuera (verificado con grep en todo el backend) y un segundo camino que
  borra posiciones sin pasar por el tope es justo el agujero que esto viene a
  tapar. Quedó partida en `_plan_safe` (calcula) + `_excede_tope_usuario` (revisa)
  + `_ejecutar_plan` (escribe, y es la única que borra).
- Test: `tests/test_backfill_tope_cordura.py`, 9 casos incluidos los bordes (50%
  justo pasa; 4 filas no alcanzan el piso). **Verificado que falla con el
  comportamiento viejo**: desactivando el tope, la cartera de los 4 usuarios queda
  en 0 y `test_no_vacia_la_cartera_de_nadie` se cae.

⚠️ **Dato que apareció escribiendo el test:** el backfill sólo toca posiciones
creadas por un IMPORT (`_import_linked_position_ids`) y respeta las cargadas a
mano. Un test que crea posiciones sueltas produce un plan VACÍO y **pasa por el
motivo equivocado**. Hay que insertar también la fila de `import_op_links`.

### La única `AssertionError` que queda sin causa visible

`test_suelta_el_lock_entre_tandas`: verifica que el reset por tandas suelte el lock
de escritura entre tanda y tanda. **En Postgres no hay un lock global de escritura**
— la premisa del test es de SQLite. No es una diferencia de resultado; es un test
que mide algo que en el motor nuevo no existe. Hay que decidir si se adapta o se
marca como sólo-SQLite.

⚠️ **CÓMO CONTAR, que es la lección que este proyecto ya dio dos veces.** El
docstring de `pgshim` decía "INSERT OR REPLACE (24 sitios)" y el plan original
decía 9: **ninguno de los dos era un conteo, eran estimaciones**. El número real
era 9 de app (2 de ellos código muerto) + 56 de tests, y 17 consultas distintas
sobre 6 tablas explicaban las 237 fallas. **Clasificá las fallas de la corrida
real; no cuentes sitios a ojo.** Del mismo modo, el plan de "80 sitios"
subestimaba: aparecieron fechas con modificador (15), `MIN`/`MAX` de dos
argumentos (2), placeholders con nombre (12) y fechas mal formadas (3).

## El aislamiento de tests: ARREGLADO (`49f6e90`)

Eran **618 tests** (527 errores + 91 timeouts) que no eran fallas de la app.

**La causa raíz era más grande que lo que decía este doc.** La sesión anterior
había identificado el `DROP SCHEMA public CASCADE` colgado; eso es la mitad.
Capturado en vivo con `pg_stat_activity` durante una corrida:

    estado                 consulta
    ---------------------  --------------------------------------------
    idle in transaction    (un test anterior que escribió y no cerró)
    active + Lock          INSERT INTO users (email, ...)   ← esperando

**No es sólo el armado de la base: son los tests normales entre sí.** Un test deja
la transacción abierta con un `users.email` adentro; el siguiente inserta ese mismo
email y espera a que la primera termine. Nunca termina.

Por qué en SQLite no pasaba, que es el dato que ordena todo: cada módulo tenía su
ARCHIVO, **y una conexión de sqlite3 sólo abre transacción al ESCRIBIR**. psycopg
con `autocommit=False` la abre hasta para un `SELECT`, y se queda con los locks de
todo lo que tocó. La misma línea de código se comporta distinto en cada motor.

El arreglo tiene tres partes y las tres hacen falta: un **esquema por módulo** (el
equivalente real del archivo por módulo), **cortar las conexiones huérfanas** al
empezar cada módulo (Postgres acepta 100, y cada traceback que pytest guarda para
el reporte final mantiene viva la conexión de ese test), y **dos relojes de
Postgres cuyo ORDEN es el arreglo**:

    idle_in_transaction (3s)  <  lock_timeout (7s)  <  --timeout de pytest (10s)

Al revés —que es como lo escribí la primera vez— el test que espera se rinde ANTES
de que Postgres mate a la conexión fugada: sigue fallando pudiendo pasar. Medido
con las dos configuraciones: con el orden malo corta a los 4,0s con `lock timeout`;
con el bueno espera 3,0s y **pasa**.

Resultado, comparado test por test contra la misma suite en el mismo Postgres:

| | antes | después |
|---|---|---|
| Postgres | 2.042/2.842 = **71,9%** | 2.525/2.842 = **88,8%** |
| errores de infraestructura | 527 | **0** |
| timeouts | 91 | **0** |
| duración | 19:41 | **6:21** |
| **regresiones** | — | **0** |

SQLite quedó idéntico (2.780/2.826, las mismas 46 preexistentes), verificado
corriendo la suite con y sin los cambios.

## Hallazgo para el punto 4 (Supabase): 33 conexiones sin proteger

⚠️ **Corrección de DOS versiones anteriores de este doc.** La primera decía "277
conexiones sin cerrar" (cierto pero engañoso: contaba que no hay ningún `with`, y
`with` no es la única forma de cerrar). La segunda decía 36 expuestos + 8 en
scripts. **Ninguno de los dos números resiste un recuento con AST.** El bueno:

| | sitios | |
|---|---|---|
| `conn = get_db()` en código de app | **267** | y son TODOS de la forma `X = get_db()`: no hay ninguna variante exótica |
| …que cierran con `try/finally` | **234 (88%)** | hace lo mismo que un `with`, escrito distinto |
| **…expuestos** (el `close()` se saltea si salta una excepción) | **33** | **esto es lo que hay que arreglar** |
| …en scripts de dev/one-off | **0** | el único fuera de `main.py` (`advisor_brief.py`) está protegido |

Los 33 están **todos en `main.py`** y son endpoints servidos a usuarios:
`get_current_user`, `login`, `register`, `get_positions`, `sell_position_fifo`,
`cash_flow`, `delete_operation`, … más 2 ramas de `_execute_ai_tool_inner`.

⚠️ **La trampa de medir esto, que ya hizo fallar dos conteos.** El criterio flojo
—"¿hay algún `try/finally` en la función que cierre esta variable?"— da **falsos
protegidos**: `_execute_ai_tool_inner` abre 6 conexiones y las 6 se llaman `conn`,
así que alcanza con que UNA esté protegida para que las 6 parezcan bien. El
criterio correcto mira la POSICIÓN en el bloque: el `try` que protege a esta
conexión es el que viene después de ESTA apertura, en ESTE bloque, y su `finally`
tiene que cerrar ESTA variable. Con el criterio flojo dan 31; con el estricto, 33.
Y el estricto de más —"el `try` tiene que ser el statement inmediatamente
siguiente"— da 35, con 2 falsos positivos: `get_movements` y
`export_transactions_csv` tienen un `movements: list = []` inocuo en el medio y
están bien protegidos. **El script del recuento está en el scratchpad
(`count_getdb2.py`) y clasifica sitio por sitio, no cuenta a ojo.**

Por qué importa igual: cuando uno de esos 36 se salta el `close()`, en SQLite casi no
se nota; en Postgres la conexión queda **`idle in transaction`** reteniendo los locks
de todo lo que tocó. **Es exactamente la misma traba que tiró la app el 12 y el 13/08**,
y es el mismo mecanismo que colgaba la suite de tests.

Nota: los relojes (`lock_timeout`, `idle_in_transaction_session_timeout`) que tapan
esto en la suite son **de TESTS**, están en `conftest.py`. En producción no hay nada
equivalente puesto.

### ✅ HECHO (sesión 6): `main.db_abierta()` + un barrido que impide el 34

⚠️ **LA TRAMPA, y es el motivo de que el helper se llame distinto.** En este código
`with conn:` **YA significa otra cosa**: confirmar o deshacer la TRANSACCIÓN.
`Connection.__exit__` hace commit/rollback y **NO cierra** (`pgshim.py:922`, igual
que `sqlite3` — y de eso depende la atomicidad de todo el código). O sea que
`with get_db() as conn:` **no cierra nada** y el arreglo parecería hecho sin
estarlo. Por eso hay un helper nuevo, con otro nombre, y un test que fija esa
diferencia para que nadie lo "simplifique" más adelante.

- **`db_abierta()`** (`main.py`, al lado de `get_db`). **No commitea**, a propósito:
  si commiteara al salir, convertiría en permanente el trabajo a medias de
  cualquier handler que hoy revienta antes de su commit — cambiaría el
  comportamiento de 33 endpoints en vez de arreglarles el cierre.
- **Los 33 convertidos** de una, con un transformador que verifica su propio
  trabajo: re-parsea el archivo y compara la cantidad de statements por función
  antes/después (tiene que bajar exactamente en la cantidad de `close()` que
  borró). 70 `close()` borrados, 0 statements perdidos de más.
- **`tests/test_conexiones_cerradas.py`** — dos cosas: que `db_abierta` cierre
  aunque el cuerpo explote, y un **barrido con AST de `main.py` que falla si
  aparece un sitio expuesto nuevo**. Ese es el que impide el 34, y no depende de
  que alguien se acuerde de escribir un test para su endpoint.
- El barrido tiene sus propios tests (que encuentre uno malo, que no marque los
  dos patrones buenos). ⚠️ **Su primera versión marcaba mal** los tres escritores
  de `fx_rates_daily`, que usan la forma `conn = None; try: conn = get_db() …
  finally: if conn is not None: conn.close()`. Un barrido con falsos positivos se
  vuelve ruido que uno aprende a ignorar: hay que probarlo en las dos direcciones.

📌 **Sobre el diff: son ~3.000 líneas, y 1.779 son sólo `init_db` re-indentada.**
Es la función que crea el esquema — una sola función larguísima con una conexión
que abre arriba y cierra abajo. No hay nada que revisar ahí más que el sangrado;
lo verifican el parseo, el conteo de statements y la suite (init_db corre en el
setup de todos los módulos de test, en los dos motores).

## `INSERT OR REPLACE` → `ON CONFLICT`: HECHO (`e7c3f1e`), y lo que enseñó

De 88,8% a **95,8%** (+187 tests), cero regresiones, suite de 6:21 a **1 minuto**.
SQLite quedó idéntico (2.784/2.830, las mismas 46 preexistentes).

**LA TRAMPA, para que no se pierda:** `INSERT OR REPLACE` en SQLite **no es un
upsert** — BORRA la fila y la reinserta. Entonces (1) las columnas que la query no
nombra se PIERDEN, y (2) se disparan los `ON DELETE CASCADE`. `ON CONFLICT DO
UPDATE` no hace ninguna de las dos, así que convertir "obvio" cambia comportamiento
**en las dos direcciones**.

- **Cascada: no aplicaba acá**, verificado. En todo el esquema hay 6 FKs con
  `ON DELETE CASCADE` (`brokers.parent_broker_id` y las de `import_*`), y ninguna
  apunta a las 6 tablas tocadas.
- **Columnas perdidas: sí aplicaba, y en UN lugar importaba.** `config`,
  `bond_indices_daily` y `asset_last_price` nombran todas sus columnas → conversión
  equivalente. El que cambia es `_backfill_fx_rates_if_empty` (main.py).

### El bug latente que apareció: el backfill del blue borraba el MEP histórico

> ⚠️ **CORRECCIÓN (misma sesión, más tarde).** Esta sección afirmaba dos cosas que
> se verificaron **FALSAS** al investigar si el bug explicaba el audit de FX:
> «un MEP borrado NO se auto-cura nunca» y «sin mep, `fx.py` cae al blue».
> · `_backfill_mep_rates_if_missing` hace `UPDATE … WHERE mep_venta IS NULL`, y un
>   borrado queda NULL: **entra en ese WHERE igual que uno que nunca se cargó** y se
>   re-rellena en el arranque siguiente.
> · `fx.py:_lookup` pone el `IS NOT NULL` **adentro del WHERE**, así que agarra el
>   MEP del día ANTERIOR. Para caer al blue habría que vaciar la serie entera.
> · Y `_backfill_fx_rates_if_empty` arranca con `if cnt > 0: return`: sólo escribe
>   con la tabla VACÍA, donde no hay mep que borrar. Hace falta una carrera, y el
>   daño máximo es UNA fila.
> **El arreglo es correcto y vale** —deja a ese escritor igual que sus dos hermanos
> y saca una forma de romper— **pero es defensa en profundidad, no un incendio.**
> Lo que sigue se deja como estaba escrito, con esta advertencia arriba.

Escribía `(date, blue_venta, source)` sobre una tabla de CINCO columnas, así que
cada re-escritura dejaba **`mep_venta` en NULL**. Que era bug y no intención se ve
en el mismo archivo, no en una corazonada:

- `_persist_blue_for_date` la protege: `COALESCE(excluded.mep_venta, fx_rates_daily.mep_venta)`
- el cron de `snapshots_job.py` ni la nombra
- `_backfill_mep_rates_if_missing` sólo rellena `WHERE mep_venta IS NULL` → **un MEP
  borrado NO se auto-cura nunca**

Los otros dos escritores de esa tabla ya la cuidaban; el backfill era el único que
la borraba. Y sin `mep_venta`, `fx.py` se cae del riel MEP al **blue en silencio**
para todo el histórico: número equivocado, no error. Ahora **sobrevive**.
`fetched_at` sí se sigue refrescando —eso era correcto, la fila se reescribe con
dato recién traído— puesto explícito en el SET, porque el `DO UPDATE` si no se
quedaría con el viejo (el cambio silencioso al revés).

Tiene su test: `tests/test_fx_backfill_upsert.py`. Corre la CONSTANTE de main
(`SQL_BACKFILL_FX_BLUE`, extraída justo para eso) y **no una copia pegada**, así que
si alguien edita la consulta el test se entera. Verificado que **falla con el
comportamiento viejo y pasa con el nuevo**, en los dos motores.

**El guardarraíl del shim se queda puesto**: un `INSERT OR REPLACE` nuevo sigue
siendo rechazado con `NotImplementedError`, para que pase por el mismo análisis.

Dato lateral que confunde si no se sabe: 10 tests de `test_entry_price_moneda` y
`test_orden_*` pasaron de "falla" a **xfail**. No se están tapando — son defectos
ABIERTOS marcados `@unittest.expectedFailure` que antes ni llegaban a correr (el
`NotImplementedError` los mataba en el `setUp`). Postgres ahora coincide EXACTO
con SQLite en esos 12.

## Referencias ambiguas: la QUINTA categoría fuera del plan (`f5c0f8e`)

Adentro de un `ON CONFLICT … DO UPDATE SET` hay **dos filas a la vista**: la que ya
estaba en la tabla y la que se quiso insertar (`excluded`). Una columna **pelada**
no dice cuál. SQLite elige la de la tabla; **Postgres corta**:
`column reference "x" is ambiguous`.

    last_fired_date = COALESCE(excluded.last_fired_date, last_fired_date)
    count           = count + 1

**Son 8 sitios de app, no 1.** El barrido por `COALESCE(excluded.X, …)` encuentra
uno (`advisor_alerts.py`); la forma `x = x + 1` suma 6 en `ai/quota.py` y 1 en
`main.py`. **Buscá la categoría, no el patrón que la reveló.**

**Y es de las peores por CÓMO falla:** esos sitios viven adentro de un
`try/except Exception` que loguea y sigue. En Postgres las alertas del asesor **no
se mandan** y los contadores de IA **no suben**, sin ningún error — sólo una línea
en el log. No lo agarra ningún test que mire el resultado de la función.

El shim ahora **las detecta y las rechaza** con un mensaje que dice qué columna y
cómo calificarla. El test (`tests/test_pgshim_ambiguas.py`) además **barre todo el
backend con AST**: encuentra las que ningún test ejecuta — que es justo el caso de
las que están adentro de un try/except.

## Las 38 `AssertionError`, una por una: NINGUNA era semántica

Es el resultado que importa de esa revisión. Clasificadas contra la baseline de
SQLite y contra el traceback:

| | |
|---|---|
| (a) ya fallaban en SQLite → preexistentes | **22** |
| (b) cascada de un error de Postgres tapado más arriba | **16** |
| **(c) diferencia semántica real** | **0** |

Las 16 de cascada tenían tres causas, las tres arregladas: referencias ambiguas
(6, las alertas del asesor), `rowid` en el borrado por tandas del reset (8) y
`Connection.backup` (2, que queda como ítem de diseño).

**El método vale más que el número:** ante una `AssertionError` en Postgres,
primero fijate si ya falla en SQLite, después buscá un error de Postgres ANTES en
el mismo traceback. Recién si no hay ninguno de los dos es una diferencia real.

## Orden sugerido

1. ~~Arreglar el aislamiento de tests~~ ✅ `49f6e90`.
2. ~~`INSERT OR REPLACE` → `ON CONFLICT`~~ ✅ `e7c3f1e`.
3. ~~Referencias ambiguas, `rowid`, `printf`, `round`~~ ✅ `f5c0f8e`.
4. **Elegir el camino del ensayo sin clon** (`Connection.backup`) — son las 11
   fallas propias que quedan, y está diseñado y atacado, sólo falta decidir.
   **Antes de eso, el piso de cordura de `_apply_safe`**, que es más urgente y no
   depende de la migración.
5. **Copiador de datos** SQLite→Postgres. La verificación ✅ está **escrita y
   probada** (`backend/scripts/verificar_copia.py` + `tests/test_verificar_copia.py`,
   28 casos). Falta el copiador.
6. ~~Los `get_db()` expuestos~~ ✅ sesión 6 — `main.db_abierta()` + barrido AST.
7. **Probar contra Supabase de verdad.** Todo lo medido hasta acá es Postgres local,
   sin red de por medio. Ahí se nota lo que hace demasiadas idas y vueltas — como el
   `_table_cols()` que hubo que cachear.
8. **`.env`** con los nombres de variable y `.gitignore`. Los valores los pone el
   dueño: no manejes contraseñas en texto plano.

## El copiador: LA VERIFICACIÓN ✅ ESCRITA Y PROBADA (sesión 6)

`backend/scripts/verificar_copia.py` + `tests/test_verificar_copia.py` (28 casos).
Los cuatro niveles del diseño de abajo están implementados y **probados rompiendo
una copia a propósito, de a UNA cosa por vez**. Las cinco roturas saltan:

| se rompe | lo agarra |
|---|---|
| una fila de menos en `operations` | nivel 1 **y** nivel 2 (la ganancia de ese usuario) |
| un número a un float de distancia | nivel 1 y nivel 2 |
| un `Decimal` con otro valor donde iba `float` | nivel 2 |
| una secuencia sin `setval()` | nivel 3 |
| `raw_json` vaciado con DELETE en vez de UPDATE | nivel 0 |

Y —tan importante como lo anterior— **las que NO tienen que saltar, no saltan**: el
`int` 1500 de SQLite contra el `float` 1500.0 de psycopg, un `Decimal` con el MISMO
valor, y un `raw_json` vaciado bien con UPDATE. Una verificación que grita con
copias sanas es una que uno aprende a ignorar.

**Tres cosas que se aprendieron implementándola y no estaban en el diseño:**

1. **"Cambiar el último decimal" no siempre existe.** `1500.0000000000001` **es**
   `1500.0`: la distancia entre dos floats vecinos cerca de 1500 es 2,27e-13, así
   que 1e-13 queda por debajo de medio paso y Python lo redondea al mismo número.
   El primer test que escribí fallaba por eso, y el test estaba mal, no el código.
   Se usa `math.nextafter`, que da la diferencia mínima que SÍ existe.
2. **Los totales se suman en Python y en `Decimal`, no con `SUM()` en SQL.** La
   suma de floats no es asociativa: dos motores sumando las MISMAS filas en
   distinto orden pueden diferir en el último bit, y eso obligaría a inventar una
   tolerancia — que es exactamente donde se esconde un error de conversión. En
   `Decimal` es exacta y no depende del orden, así que se compara **sin tolerancia**.
3. **El digest de cada tabla es INDEPENDIENTE DEL ORDEN** (se hashea cada fila y se
   SUMAN los hashes). Así no hace falta un `ORDER BY` que se comporte igual en los
   dos motores — y no se comporta: con NULLs, SQLite los ordena primero y Postgres
   al final. Se suman y no se hace XOR para que dos filas idénticas no se cancelen.

**Verificado también contra el esquema REAL de 58 tablas**: usa exactamente tres
tipos (`text`, `bigint`, `double precision`) y la normalización los conoce a los
tres. Quedó como test: el día que alguien agregue una columna `numeric` o
`boolean`, avisa **antes** de que la verificación la normalice mal en silencio.

⚠️ **EL NIVEL 3 NO CORRE EN LA SUITE NORMAL, y hay que saberlo.** Los 7 tests que
necesitan Postgres se saltean solos si no está `PG_DSN_VERIF` — una variable
**aparte** de `DATABASE_URL` a propósito, porque apuntan a otra base y así no se
pisan con la suite. El costo es que el nivel de las secuencias (el que evita que el
primer alta después de migrar choque contra un id existente) **queda salteado en las
dos corridas medidas**: los 21 tests locales corren con `revisar_secuencias=False`
porque SQLite no tiene secuencias.

Está verificado, pero hay que correrlo a mano y **antes de migrar de verdad hay que
correrlo sí o sí**:

```bash
PG_DSN_VERIF="postgresql://…/otra_base" python3 -m pytest tests/test_verificar_copia.py -q
```

Con la variable puesta: **28 pasan, 0 se saltean**.

## El diseño de la verificación (referencia)

Es el paso donde de verdad se juega la plata de 1.084 personas. **La verificación
va primero, y no es negociable el orden**: escrito el copiador antes, uno mira lo
que produjo y lo acepta, porque no tiene contra qué compararlo.

**Contar filas NO alcanza.** Un número mal convertido —un costo en pesos leído
como dólares, un `numeric` redondeado— deja exactamente la misma cantidad de
filas. Lo que hay que comparar es la PLATA, por usuario.

### Cuatro niveles, y hacen falta los cuatro

**Nivel 0 — vaciar `raw_json` no tocó nada más.**
El 92% de las filas (3,1 de 3,4 millones) es andamio de import. Se vacía ANTES de
copiar, con `UPDATE` y **nunca `DELETE`** (borrar la fila cascadea y se lleva su
movimiento real del ledger). Ese UPDATE es la primera oportunidad de perder plata,
y ocurre sobre la base REAL. Antes y después, sobre la misma SQLite:
- cantidad de filas de las 58 tablas, idéntica. Si bajó una sola, alguien usó DELETE.
- digest de `import_raw_rows` **sin** la columna `raw_json`, idéntico.

**Nivel 1 — fila por fila, exacto (la fuerte).**
Por tabla: cantidad de filas + un digest del contenido COMPLETO de cada fila,
ordenado por id. Atrapa una columna que ningún total suma.

⚠️ **La trampa que hay que resolver ANTES de escribir esto, y es donde un bug hace
que todo parezca bien:** los dos motores devuelven TIPOS distintos para la misma
columna. psycopg da `Decimal` donde `sqlite3` da `float`; un `text` con fecha puede
volver como objeto fecha. Si no se normaliza, TODO da distinto, la verificación se
llena de ruido y uno aprende a ignorarla — que es peor que no tenerla. **La
normalización lleva su propio test**: valores conocidos, los dos motores, mismo
digest. Es la pieza más delicada de todo el asunto.

**Nivel 2 — la plata, por usuario (la legible).**
Por cada uno de los ~1.084 usuarios, leyendo lo que está GUARDADO (no valuado a
mercado: eso depende de precios y FX, cambia cada minuto, y no es lo que puede
romper un copiador):
- **invertido** — Σ `positions.invested` con `is_cash=0`
- **efectivo** — Σ `positions.invested` con `is_cash=1`
- **ganancia realizada** — Σ `operations.pnl_usd`
- **nominales** — Σ `positions.quantity` por (broker, activo)

**Comparados EXACTO, sin tolerancia.** Si hiciera falta una tolerancia, es que algo
se convirtió mal: estamos copiando las MISMAS filas, no recalculando nada.

**POR USUARIO y no en total**, que es el punto: un total global neteo dos errores
opuestos —un usuario ×1400 para arriba y otro para abajo— y da bien. Ya pasó en
este proyecto con el FX.

**Nivel 3 — las secuencias.**
Las PK son `GENERATED BY DEFAULT` justamente para poder insertar cada fila con su
id original; después hay que correr `setval()` en cada una. Verificación: por cada
tabla con id, `last_value` de su secuencia **>** `max(id)`. Sin esto, el próximo
usuario que se registre choca contra un id que ya existe.

### Cómo se prueba que la verificación sirve

**Rompiendo una copia a propósito, de a una cosa por vez.** Tiene que saltar cada
una, y hasta que no salten todas el copiador no se escribe:

| se rompe | tiene que saltar |
|---|---|
| cambiar un `invested` en el decimal 15 | nivel 1 y 2 |
| borrar UNA fila de `operations` | nivel 1 y 2 |
| cambiar un id | nivel 1 |
| no correr `setval()` | nivel 3 |
| usar `DELETE` en vez de `UPDATE` en `raw_json` | nivel 0 |

Es la misma regla que el resto del proyecto —*todo test nuevo tiene que fallar con
el comportamiento viejo*— aplicada a la verificación misma.

**Y corre sobre una copia restaurada de producción, no sobre producción.**

## Decisiones ya tomadas — no las revisites sin motivo

- **Los `0/1` quedan `smallint`, NO `boolean`.** El código hace `WHERE is_cash=1` en
  decenas de lugares.
- **Las fechas quedan `text`.** Están en `'YYYY-MM-DD'` y el código las compara y
  ordena como strings, que para ese formato es correcto. Cambiarlas toca 122 sitios.
- **La migración no es el momento de mejorar el modelo de datos.**
- **Las PK son `GENERATED BY DEFAULT AS IDENTITY`, no `ALWAYS`.** Con `ALWAYS`,
  Postgres rechaza insertar una fila con su id original — que es justo lo que hace
  copiar los datos. Después de copiar hay que correr `setval()` en cada secuencia.
- **NO uses pgloader.** Infiere el esquema y deshace las dos decisiones de arriba.
- **NO actives RLS.** Sirve cuando el navegador habla directo con Supabase. Rendi
  tiene un backend FastAPI en el medio, usa autenticación propia (JWT + cookie), y
  la separación por usuario ya está en los filtros `user_id` / `get_effective_user`.
  Las políticas con `auth.uid()` no aplicarían y pueden bloquear al backend.

## Cómo correr las cosas

```bash
# Postgres local embebido (ya instalado: pip install pgserver "psycopg[binary]")
cd <scratchpad>
python3 -c "import pgserver,pathlib;print(pgserver.get_server(pathlib.Path('pgdata').absolute(),cleanup_mode=None).get_uri())" > pg_uri.txt

# suite contra Postgres. Tarda ~6:20 y NO debería dar ningún timeout: si aparece
# uno, es una regresión del aislamiento, no una falla de la app. El --timeout=10
# se deja puesto justamente como alarma (y porque los relojes del conftest —3s y
# 7s— están calibrados para cortar ANTES que él).
cd mainwt/backend
DATABASE_URL="$(cat ../../pg_uri.txt)" python3 -m pytest tests -q --timeout=10

# suite contra SQLite (baseline). Al comparar, usá SIEMPRE la baseline del commit
# padre: hay ~46 fallas preexistentes que no son tuyas.
python3 -m pytest tests -q
```

## Contexto de producción que conviene saber

- Railway + volumen de 10 GB (`/data/trading.db`, 933 MB). Se llenó el 12/08 al 97%
  de 5 GB y ahí empezó todo.
- **El 75% del volumen son backups** en el mismo disco que la base. Sin tocar la
  retención, vuelve al 97% entre el 8 y el 28 de septiembre. Si la migración llega
  antes, deja de importar; si no, `BACKUP_LOCAL_KEEP_DAYS=3` libera 2,5 GB.
- **El 92% de las filas (3,1 de 3,4 millones) son andamio de import**
  (`import_raw_rows` guarda el CSV entero, para siempre, sin retención). El negocio
  real son ~250 mil filas. **No migres la basura**: vaciar `raw_json` de los imports
  viejos antes de copiar. Ojo: **vaciar el campo con `UPDATE`, nunca `DELETE` la
  fila** — borrarla cascadea y se lleva su fila del ledger normalizado.
- Los tres dueños del lock ya arreglados en `main`: el reset (por tandas), el
  `import_confirm` (transacción de 177→56 líneas) y los precios (1 escritura por
  minuto en vez de 1 por visita). Cada uno con test estructural que impide que
  vuelvan.
