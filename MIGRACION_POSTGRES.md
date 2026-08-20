# Migración SQLite → Postgres (Supabase) — estado y prompt de continuación

Última sesión: 2026-08-14 (sesión 8). Pegá el bloque de abajo en una sesión nueva.

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

    ~/rendi-worktrees/migracion          ← worktree (durable, NO /tmp)
    ~/rendi-worktrees/pg_uri.txt         ← DSN del Postgres local

Rama **`spike/postgres`**. **NO se deploya** — es un spike.
Producción va por `main` y está estable (`7949209a`).

⚠️ macOS purga `/private/tmp` en sesiones largas — **ya pasó el 18/08**: se perdió
el worktree viejo y con él el Postgres local. Los commits sobreviven en el repo:
`git worktree add <ruta> spike/postgres`. Por eso el worktree ahora vive en
`~/rendi-worktrees/`, que sí sobrevivió.

**Postgres local (reinstalado 18/08):** Postgres.app, **PostgreSQL 18.6**, base
`rendi_test`, `max_connections=100`. ⚠️ La migración se había validado contra
**16.2**; si aparece una falla rara, la versión es sospechosa.
⚠️ Postgres.app 18 pide **confirmar un cartel de permisos** la primera vez que una
app se conecta; si no se acepta, `psycopg` falla con
`failed to verify "trust" authentication`, que no parece un problema de permisos.
⚠️ `extra_float_digits` = **1** en local y **0** en los poolers de Supabase (el
shim lo fuerza a 3). Un local en verde NO garantiza Supabase en verde.

## 🔴 BLOQUEANTE DEL DÍA DEL PASAJE: el backup real NO pasa el guardián del `-wal`

**Medido el 18/08, reproduciendo el pipeline exacto.** El guardián de
`abrir_origen()` (`copiar_a_postgres.py:75`) rechaza toda base "en WAL y sin
`-wal`" con el mensaje «el archivo se copió a medias». Su premisa está escrita
así: *"un `wal_checkpoint(TRUNCATE)` seguido de cerrar limpio deja el `-wal`
presente y en 0 bytes… o sea que 'en WAL y sin -wal' no es el estado normal de
nada"*.

**Esa premisa es falsa para el camino que importa.** `scripts/backup_db.py` hace
`src.backup(dst)` (la API oficial de backup en caliente, consistente aun con
writers), cierra, y comprime **sólo el `.db`**. Reproducido:

    tras .backup() + close():
      byte 18 del header: 2   (modo WAL)
      ¿existe el -wal?:   False
      abrir con mode=ro:  OperationalError: unable to open database file
    ¿la copia está COMPLETA? SÍ  (users/operations/positions/snapshots idénticos)
    ¿el guardián la aceptaría? NO

O sea: **un backup perfecto y completo cae exactamente en el estado que el
guardián llama "copiado a medias"**, y encima da el error críptico que el propio
docstring identifica como el que empuja al operador a sacarle el `mode=ro`.
El día del pasaje, con la app abajo, el remedio que sugiere el mensaje —"copiá
los dos archivos"— **es imposible: el `-wal` nunca existió**.

**ARREGLO PROPUESTO (verificado, 1 línea, NO aplicado todavía).** Arreglar el
PRODUCTOR, no el guardián — tocar el guardián lo dejaría ciego ante la copia
truncada de verdad, que tiene la misma firma. En `dump_sqlite_consistent()`,
antes de cerrar el destino:

    dst.execute("PRAGMA journal_mode=DELETE")

Medido: byte 18 pasa a 1, abre con `mode=ro`, los datos quedan completos y el
guardián acepta. El archivo de archivo no necesita WAL.

## Estado 18/08 — la rama al día con main (`0c47aff0`)

Mergeados los 22 commits que `main` había avanzado. **Los dos motores fallan en el
MISMO set, test por test: 46 y 46** (SQLite 3033 pasan, Postgres 3034).

⚠️ **NUNCA mergear `main` con `-X ignore-all-space`.** `init_db()` está envuelto en
`with db_abierta() as conn:`, o sea 1.792 líneas corridas 4 espacios: git ve como
distinto todo lo que `main` toca ahí (de 3.228 cambios de la rama sobre `main.py`,
~2.900 son sólo sangría). Esa opción acierta el CONTENIDO y **miente con la
sangría**: dejó `brief_open`/`brief_close` anidados adentro del `if` de
`logo_data` — hermanos vueltos hijos, **compila igual** — reintroduciendo en
silencio el bug de "la migración no corre nunca" que arreglaba `87ab966c`.
Se resuelve a mano: tomar el lado de la rama en los bloques en conflicto y
re-aplicar las ediciones reales de `main` (fueron 4, todas en `init_db`).
Detector: líneas dentro de `init_db` con sangría 4 en vez de 8.

Lo que trajo esta tanda de `main`, como muestra de la deuda que se acumula sola:
· 2 `INSERT OR REPLACE` nuevos en `test_bonds` → `ON CONFLICT (date) DO UPDATE`.
  **`DO NOTHING` NO sirve**: 2026-05-08 tiene que quedar con `mep_venta` NULL o
  `test_fx_stamped_walks_back_when_date_has_no_mep` pasa en verde por el camino
  equivocado.
· 2 endpoints sin `db_abierta()` (`edit_position_group` y su undo) que cazó el
  guardián de conexiones — en Postgres quedaban `idle in transaction`.
· `test_advisor_schema_migration.py` quedó **sólo-SQLite**: prueba las migraciones
  incrementales de `init_db()`, que en Postgres no existen a propósito.
  **NO portarlo.**

`schema_pg.sql` NO hay que regenerarlo: los 22 commits no agregaron tablas ni
columnas nuevas, y las 4 de `advisor_op_batch_items` + las 3 de `advisor_profile`
ya estaban (el `CREATE TABLE` siempre las tuvo; el bug era que el ALTER no corría
sobre tablas ya existentes).

⚠️ El test inestable sigue: `test_ai_register_trade.py::TestE2EQuestion...::
test_explicit_undo_message_is_deterministic` dio ERROR en 1 de 3 corridas de la
suite completa en Postgres, y pasa 5/5 aislado. **No se descuenta del 46.**

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
  donde no van.
  ⚠️ **CORRECCIÓN (sesión 7): ese audit NO miró los datos NUEVOS, así que "el riesgo
  grande está descartado" es más chico de lo que dice.** `pg_type_audit.py` muestrea
  las tablas de más de 200.000 filas con `SELECT * FROM tabla LIMIT 200000` **sin
  `ORDER BY`** (`:73-74`), y SQLite sin `ORDER BY` devuelve las filas en orden de
  `rowid`: o sea **las más VIEJAS**. Las tres tablas de import (~1M de filas cada
  una) cayeron justo en ese muestreo — y son las que llenan los parsers. Todo lo que
  escribieron los parsers nuevos (PPI, inviu, Balanz Internacional, Bull Market,
  Binance) está en la cola y **nunca se auditó**. Un `''` o un texto en una columna
  numérica ahí no molesta hoy —SQLite lo acepta— y haría fallar al copiador **a mitad
  de la ventana**. Hay que re-correrlo sobre la copia restaurada sin muestreo, o
  muestreando la cola (`ORDER BY rowid DESC`), y esperar el mismo LIMPIO.
- **Medición**: **98,4%** (2.854 de 2.900 en Postgres; 2.846 de 2.892 en SQLite) y
  **0 fallas propias de la migración** — las 46 que quedan **son EXACTAMENTE EL
  MISMO SET en los dos motores**, test por test. Suite COMPLETA en **1 minuto**,
  **y el número significa algo**: cero timeouts y cero errores de infraestructura
  (ver la sección del aislamiento). Antes de arreglar eso el porcentaje no era ni
  reproducible — la misma suite en el mismo commit daba 77,4% en una corrida y
  71,9% en otra, según qué se trababa con qué.
  Verificado por afuera con 3 corridas de Postgres y 2 de SQLite: el mismo set las
  cinco veces.

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

⚠️ **FALTA EL COPIADOR** ✅ **YA NO: escrito, probado y cronometrado (sesión 9).**
Ver la sección del copiador. Lo que falta ahora es medir contra el Supabase real.

**CERO fallas propias de la migración** (sesión 6). Postgres queda en **46 fallas y
las 46 fallan IGUAL en SQLite** — son las preexistentes de siempre. Medido con la
suite COMPLETA en los dos motores y comparado test por test.

| | antes (`bf5226a`) | ahora |
|---|---|---|
| Postgres | 57 fallas (2.790 pasan) | **46 fallas** (+2 dependientes de fecha = 48) |
| SQLite | 46 fallas (2.795 pasan) | **46 fallas** (+2 dependientes de fecha = 48) |
| **¿el mismo SET de fallas en los dos motores?** | — | **SÍ, exactamente iguales** |
| fallas SÓLO de Postgres | 11 | **0** (salteadas, no arregladas) |
| regresiones | — | **0 en los dos motores** |

**El número a usar es 46**, y lo más fuerte que se puede decir no es el total: es que
**el SET de fallas de Postgres y el de SQLite son EXACTAMENTE el mismo**. Los dos
motores fallan en los mismos tests, uno por uno. Verificado con 3 corridas de
Postgres y 2 de SQLite, comparando conjuntos y no totales.

### 🔴 LA BASELINE AHORA ES 48, no 46 — y los 2 nuevos dependen del DÍA

`tests/test_reports_variaciones_f4.py`, dos casos:
`test_b1_migracion_startup_no_rompe_delta_chips` y
`test_h7_delta_chips_netdep_con_baseline`.

**No son de la migración.** El archivo es del 09/07 y ningún commit del spike lo
tocó — verificado sacando todos los cambios y corriendo en el commit anterior:
fallan igual. Lo que pasa es que usan `datetime.utcnow()` y
`today - today.weekday()`, mientras que la app usa **el día ART** a propósito
(`_iso_today()`, para que "hoy" sea el del usuario argentino). **Los dos relojes
discrepan según el día de la semana y la hora**: aparecieron un sábado a las 21:29
ART, cuando en UTC ya era domingo.

Misma familia que `test_cedear_usd_price::test_snapshot_converts_bac`, que es
inestable **entre entornos**. Éstos son inestables **entre fechas**.

**La baseline pasa a 48.** Si en tu corrida da 46, **no restes**: fijate si esos dos
pasaron y decilo. Anotarlos acá es lo que impide que la próxima sesión los lea como
una regresión del spike — que es exactamente el error que este proyecto persigue.

⚠️ **NO restes el test inestable de la cuenta.** Una versión anterior de esta tabla
decía "45-46" y proponía usar 45 "sin el flaky"
(`test_cedear_usd_price::SnapshotsJobCedearTest::test_snapshot_converts_bac`).
Medido de nuevo: en 3 corridas seguidas **falló las 3 veces, en los DOS motores** —
nunca flipeó. Es inestable **entre entornos**, no entre corridas: depende de la
máquina, no del azar.

Restarlo hacía que el número dependiera de dónde corrés la suite, que es
exactamente cómo este proyecto ya se comió cinco conteos mal hechos. **Contalo
adentro de los 46 y anotalo como preexistente inestable.** Si en tu entorno da 45,
no restes: fijate si ESE test pasó, y decilo.

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

#### ⚠️ LA REGLA ES MÁS ANCHA QUE "no corras dos pytest" (ampliada en sesión 8)

Una corrida del dueño dio **47 fallas + 8 errores** y el culpable no fue pytest: fue
**un script ad-hoc** que llamaba a `pg_terminate_backend` **sin filtro** mientras la
suite corría. El arreglo del conftest está bien y siguió estando bien —filtra por
`application_name` y sólo mata las suyas—, pero **un script suelto no hereda ese
filtro**. La regla enunciada como "no corras dos pytest a la vez" dejaba pasar
exactamente ese caso, porque el segundo proceso no era pytest.

> 🔴 **La regla es: NADA que llame a `pg_terminate_backend` sin filtro mientras algo
> más esté usando ese Postgres.** Ni pytest, ni un script suelto, ni un snippet de
> diagnóstico pegado en una terminal. Si tenés que matar conexiones, filtrá por
> `application_name` como hace el conftest, o hacelo cuando no corre nada más.

Y es la misma forma de siempre: se arregló **el sitio** (el conftest) y se enunció la
regla por **el síntoma** (dos pytest) en vez de por la **categoría** (quién más mata
conexiones). El segundo caso apareció solo, como siempre.

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
4. ~~El ensayo sin clon + el piso de cordura de `_apply_safe`~~ ✅ sesión 6. El
   ensayo por clon quedó **sólo-SQLite por decisión** (avisa con un 501, no se
   migró) y el tope de `_apply_safe` **está puesto y probado** (50% + piso de 5 por
   usuario; 25% + piso de 3 por tanda).
5. **PLAN DE PASAJE** ✅ escrito (abajo) — cómo movemos a los 1.084 sin romper
   nada. Va **antes** del copiador, por el mismo motivo por el que la verificación
   fue antes: escrito después, uno acepta lo que salió porque no tiene contra qué
   compararlo.
6. **Copiador de datos** SQLite→Postgres. La verificación ✅ está **escrita y
   probada** (`backend/scripts/verificar_copia.py` + `tests/test_verificar_copia.py`,
   44 casos). Falta el copiador.
7. ~~Los `get_db()` expuestos~~ ✅ sesión 6 — `main.db_abierta()` + barrido AST.
8. **Probar contra Supabase de verdad.** Todo lo medido hasta acá es Postgres local,
   sin red de por medio. Ahí se nota lo que hace demasiadas idas y vueltas — como el
   `_table_cols()` que hubo que cachear.
9. **`.env`** con los nombres de variable y `.gitignore`. Los valores los pone el
   dueño: no manejes contraseñas en texto plano.

## EL PLAN DE PASAJE — diseño, sesión 7

Todo lo anterior de este doc contesta **"¿el código anda contra Postgres?"**, y esa
pregunta ya está contestada: 46 fallas, las mismas en los dos motores, 0 propias de
la migración. Lo que sigue contesta otra pregunta, que es la que tiene el riesgo de
verdad: **"¿cómo movemos a los 1.084 usuarios sin romper nada?"**

⚠️ **NADA DE ESTO ESTÁ MEDIDO TODAVÍA**, y los huecos van marcados como
**`[A MEDIR]`** en vez de estimados. Este proyecto ya se comió cinco conteos mal
hechos, todos del mismo tipo: medir una cosa y nombrarla como otra. Un número
inventado acá sale caro: es el que decide cuánto tiempo la app está caída.

---

### 0. Tres cosas que el plan necesita y hoy no están (una es más chica de lo que parecía)

Antes que las cinco preguntas, porque cambian las respuestas. Las tres son de
diseño, no están implementadas, y **ninguna es grande**.

**a) No hay modo mantenimiento en el backend — pero el frontend ya se banca la
caída mejor de lo que yo esperaba, así que esto es más barato de lo que parecía.**

En el backend no hay ningún `MAINTENANCE`, read-only ni equivalente: las únicas
palancas de entorno que apagan algo son `RENDI_RESET_DATA_ENABLED`,
`ALERTS_CRON_TOKEN` y `SNAPSHOT_CRON_TOKEN`. Hoy "bajar la app" es apagar el backend
en Railway.

⚠️ **Corrijo lo que había escrito acá primero** ("el usuario ve errores crudos"):
fui a mirar y es falso. `frontend/src/utils/api.js` ya tiene, desde el incidente del
2026-08-08:

- **reintentos con backoff** ante 502/503/504 (~8 s en total, `:193-195`), que
  cubren un reinicio corto sin que el usuario se entere;
- y pasados esos 8 s, un **mensaje humano** que además **distingue leer de
  escribir** (`:208-214`). El de lectura dice *"No pudimos conectarnos con el
  servidor. Suele ser una actualización en curso: esperá un momento y recargá"* —
  que para una ventana de mantenimiento **ya es el mensaje correcto**.

O sea: **apagar el backend produce, hoy, una experiencia razonable.** Un modo
mantenimiento de verdad sólo agregaría poder decir *"estamos mudando la base,
volvemos a las 11"* en vez del mensaje genérico. **Es un "estaría bueno", no un
requisito** — y eso saca un bloqueante del camino.

Lo que sí conviene mirar es el mensaje de ESCRITURA, que dice *"no sabemos si la
operación llegó a completarse"*: es exactamente lo que hay que decirle a alguien que
apretó "vender" justo cuando bajaste la app. Está bien como está; sólo hay que saber
que existe y que algún usuario lo va a ver.

**b) Los seis escritores del arranque no se pueden apagar.** Cada boot dispara, en
threads de fondo y sin que nadie se lo pida:

    _backfill_fx_rates_on_boot      main.py:28877   escribe fx_rates_daily si está vacía
    _migrate_snapshots_netdep       main.py:28946   backfill de snapshots.net_deposited
    _migrate_fci_ticker_remap       main.py:29118   remapea tickers de FCI
    _migrate_fx_gross_usd           main.py:29166   migración del fix de FX
    _prewarm_news_cache             main.py:28925   pre-fetch de noticias
    _fci_bootstrap_async            main.py:29265   bootstrap del catálogo FCI

O sea: **en el instante en que se prende `DATABASE_URL` y arranca, seis procesos
empiezan a escribir en la base nueva antes de que nadie haya verificado nada.** Y
`_backfill_fx_rates_on_boot` es el peor de los seis, porque su condición de disparo
es *"si `fx_rates_daily` está vacía"* — exactamente lo que pasaría si el copiador se
salteó esa tabla. En vez de que la falta de datos se vea, la tapa sola.
Hace falta una palanca para que el **primer** arranque contra Postgres sea callado.

**c) DOS trabajos escriben SQLite por la ventana, y ninguno de los dos falla:
MIENTEN.** Hay código que abre `sqlite3.connect(...)` directo, salteando `get_db()`
— o sea salteando el interruptor que decide el motor. Después del pasaje le siguen
escribiendo al archivo congelado y **reportan éxito**. Es peor que romperse: un job
roto se ve, y éstos se ven *sanos*.

Barrido con AST de todo el backend: son **dos** los que tocan datos de producción.

**c-1) El backup nocturno** (`_run_backup_db_job`, 03:45 UTC → `run_backup`,
`backup_db.py:283`, que abre SQLite en `dump_sqlite_consistent:87` **y `:89`** — el
origen y el destino del dump). Seguiría guardando copias impecables de una base que
ya no usa nadie. Hay que decidir de dónde salen los backups de Postgres — los de
Supabase sirven, pero hay que **confirmar cuáles trae el plan contratado**
(`[A MEDIR]`) — y apagar o adaptar el job para que no dé una señal falsa.

**c-2) 🔴 LA FOTO DIARIA** (`snapshots_job.py:945`, `sqlite3.connect(db_path)`), que
es el peor de los dos y **no lo había visto**. Tiene **TRES disparadores** y los tres
caen en el mismo lugar: el APScheduler de las 02:59 UTC, el cron externo
`/api/snapshots/run-cron` y el botón "correr ahora" del panel admin.
La noche siguiente al pasaje, el job **lee** posiciones de la SQLite congelada,
**escribe** los snapshots en la SQLite congelada, y loguea que salió bien. La app,
que lee de Postgres, **se queda sin la foto de ayer** — y de ahí cuelgan la variación
diaria, los resúmenes mensuales, el TWR y los informes del asesor. Nadie ve un error:
ven números que no cierran.

⚠️ **Y LA LECCIÓN VALE MÁS QUE LOS DOS CASOS.** Al primero lo encontré a mano y me
quedé ahí; el segundo apareció en una revisión adversarial, no buscándolo.
**Encontré el patrón y no barrí la categoría** — el mismo error que este proyecto ya
pagó cinco veces. Ahora hay un barrido con AST que la cubre entera
(`tests/test_escritores_solo_sqlite.py`) y falla si aparece un sitio nuevo.

**Los números, contados corriendo el barrido y no a ojo** (una versión anterior de
esta línea decía "los 9 legítimos", y el 9 no salía de ningún lado):

| | |
|---|---|
| sitios que abren `sqlite3.connect` directo | **11** |
| entradas en `PERMITIDOS`, cada una con el motivo escrito | **8** |
| de esas 8, marcadas `PENDIENTE` | **2** |

Son 11 y 8 y no el mismo número porque **tres funciones abren dos veces**
(`admin_fx_migrate_user`, `admin_fx_migrate_batch` y `dump_sqlite_consistent`, que
abre el origen y el destino del backup). El permiso es por función, no por línea.

🔴 **Y LA PRECISIÓN QUE MÁS IMPORTA: LA FOTO DIARIA NO ESTÁ ARREGLADA, ESTÁ
MARCADA.** Es fácil leer el párrafo de arriba como si el barrido hubiera resuelto
algo, y no resolvió nada de esto. Lo único que hace el barrido es **impedir que
aparezca un sitio NUEVO**. El que ya está (`snapshots_job.py:945`) **sigue
escribiendo en SQLite**, y después del pasaje eso significa que la foto de ayer se
guarda en la base congelada y la app —que lee de Postgres— no la ve. De esa foto
cuelgan la variación diaria, los resúmenes mensuales, el TWR y los informes del
asesor. **Nadie ve un error: ven números que no cierran.** Estado real de los dos:
**detectados y anotados en el plan**, prerrequisitos del pasaje. Sin escribir.

---

### 1. Cómo es el día

**La recomendación es la ventana de mantenimiento, no la copia en caliente.** Y el
motivo es concreto, no una preferencia de estilo:

> La copia en caliente exige un segundo pase que traiga "lo que cambió mientras
> copiaba". Para saber qué cambió hace falta o una columna de fecha de modificación
> en cada tabla —que **no existe**— o replicación lógica, que SQLite no tiene. Sin
> ninguna de las dos, el "segundo pase" es volver a comparar todo, o sea la copia
> entera otra vez. No es un atajo: es el mismo trabajo dos veces, con la app
> abierta escribiendo en el medio.

**La secuencia:**

    1.  Apagar los tres crons EXTERNOS: borrar los TRES tokens, no uno (ver
        punto 4 — el del asesor tiene fallback).
    2.  Prender el modo mantenimiento → la app deja de aceptar escrituras.
    3.  Backup de la SQLite, a mano, ahí mismo. No el del cron: uno propio, con
        fecha, guardado FUERA del volumen de Railway.
    4.  ~~FOTO "ANTES" del nivel 0~~ ⬅️ **YA NO VA (decisión sesión 9).**
    5.  ~~Vaciar `raw_json`~~ ⬅️ **YA NO VA: se migra todo.** Vaciar apagaba
        CUATRO lectores, no uno. Ver la sección de la sesión 9.
    6.  ~~FOTO "DESPUÉS" + NIVEL 0~~ ⬅️ **YA NO VA: sin vaciado no hay nada que
        vigilar, y el día se queda SIN paso irreversible antes de los chequeos.**
    7.  Correr el copiador.
    8.  `setval()` en cada secuencia.
    9.  Correr la VERIFICACIÓN COMPLETA (niveles 1, 2 y 3) con `PG_DSN_VERIF`
        puesta. **Ya no hay que pasarle `tablas_origen`: la lee sola del origen**
        (sesión 8). Si hay UN hallazgo: no se sigue.
    10. Prender `DATABASE_URL` y reiniciar, con los escritores del arranque
        apagados (punto 0b).
    11. Los chequeos de los primeros 10 minutos (punto 3), con la app TODAVÍA en
        mantenimiento.
    12. Recién ahí, abrir. Y después prender los crons externos.

🔴 **Por qué los pasos 4 y 6 están separados y no al final.** La primera versión de
esta secuencia ponía el vaciado en el paso 4 y "la verificación completa" en el 7 —
y así **el nivel 0 no se puede correr nunca**. El nivel 0 compara una foto de ANTES
contra una de DESPUÉS del `UPDATE`; si el `UPDATE` ya pasó cuando llegás a
verificar, el "antes" no existe y no hay con qué comparar. Es el único nivel que
vigila el único paso irreversible del día, y estaba programado para no correr.

#### 🔴 Antes del paso 5: el esquema tiene 58 tablas y producción tiene 60

Las dos que faltan son **`fci_catalog` y `fci_prices`** — los precios de los FCI.
No están en `schema_pg.sql` porque `pricing/fci.py:ensure_tables` las crea **en
caliente**, así que nunca entraron al esquema generado. Verificado corriendo
`init_db()` y después `ensure_tables()`: 58 → 60.

**Y lo grave no era eso: era que la verificación no lo podía ver.** La lista de qué
comparar salía del catálogo del **DESTINO** (`esquema_pg`), y todo el nivel 1
iteraba sobre esa lista. Una tabla que no viajó no está en el catálogo del destino,
así que **no entraba al bucle, no generaba hallazgo, y la verificación devolvía "ok"
con dos tablas de datos sin copiar.**

> **Preguntarle al destino qué hay que verificar es preguntarle al sospechoso.** La
> lista de qué comparar tiene que salir del ORIGEN.

**Arreglado** (`verificar_copia.py`): `comparar()` ahora recibe `tablas_origen` y
compara los CONJUNTOS antes que nada — una tabla en el origen y no en el destino es
un hallazgo de nivel 1, y al revés también. Con sus tests, incluida la contraprueba
que fija el agujero viejo (`test_SIN_pasarle_las_tablas_del_origen_es_CIEGA`).

**Para el día del pasaje:** el copiador tiene que crear esas dos tablas, o
`ensure_tables` tiene que correr contra Postgres antes de copiar. Se decide al
escribir el copiador; lo que ya no puede pasar es que se olvide **en silencio**.

#### 🔴 El paso 4 NO es inocuo: hay que acotarlo, y yo lo había dado por seguro

Escribí acá que vaciar `raw_json` no le rompía el import a nadie que lo hubiera
dejado a medio confirmar, y lo apoyé en haber leído `load_session_for_confirm`
—que efectivamente usa sólo `row_index`—. **Estaba mal**: miré UN camino de confirm
y generalicé. Es el mismo error que cometí con los escritores de SQLite, en la misma
sesión.

**Hay DOS funciones que sí leen `raw_json`:**

**1. `load_session_with_seed_revalidate` (`pipeline.py:1112`) — y es la que usa el
confirm de verdad** (`main.py:27850`). Exige `status='preview'`, lee `raw_json`, y
hace `json.loads(r["raw_json"]) if r["raw_json"] else {}`. **Con la columna vacía
cada fila queda `{}`**, `normalize_rows` no saca ninguna transacción válida, y el
confirm del usuario **importa CERO operaciones sin dar un solo error.** El usuario
aprieta "confirmar", la pantalla dice que salió bien, y no entró nada.

**2. `reconstruct_csv_from_batch` (`pipeline.py:1216`)** — es "Editar y rehacer"
(`main.py:28730`). Vaciar `raw_json` **apaga esa función para siempre** en todos los
imports viejos.

**Las dos consecuencias, y las dos son decisiones, no detalles:**

- **El UPDATE va acotado a `status='confirmed'`. Nunca a un `preview`.** Un batch en
  preview es un import que alguien dejó a medio hacer; vaciarlo se lo convierte en
  una confirmación vacía. La regla queda: *`UPDATE … SET raw_json='' WHERE
  batch_id IN (SELECT id FROM import_batches WHERE status='confirmed')`* — y nunca
  `DELETE`, que era la regla que ya estaba.
- **"Editar y rehacer" se pierde para los imports viejos, y eso hay que decidirlo a
  propósito.** Es el precio de no migrar 3,1 millones de filas de andamio. Puede
  estar perfecto — pero es una función que hoy anda y que después no va a andar, y
  el usuario no se va a enterar hasta que la busque.

⚠️ **Lo que esto enseña, otra vez:** *"verifiqué que no rompe nada"* vale sólo para
los caminos que abriste. Antes de escribirlo, hay que barrer **todos** los lectores
de la columna que se toca — `grep raw_json` en `importing/` son ocho líneas y
contestaba la pregunta bien.

**El paso 4 es el que puede sorprender por otro lado.** La base son 933 MB y el 92%
de las filas es andamio de import. Vaciar `raw_json` achica muchísimo lo que copiar —
pero **el archivo SQLite no se achica solo**: sigue ocupando 933 MB hasta que se le
corra un `VACUUM`, que es una operación larga y que reescribe el archivo entero. Hay
que decidir si se corre (y cuánto tarda: `[A MEDIR]`) o si se acepta que el archivo
quede grande, que para el pasaje da igual.

**La condición explícita, que es lo que pediste:**

> La ventana de mantenimiento alcanza **si los pasos 4 a 7 tardan menos de X**,
> donde X es cuánta caída estás dispuesto a bancar. **X lo elegís vos; el tiempo
> real es `[A MEDIR]` y no lo sabe nadie todavía, porque el copiador no existe.**

Y la forma de medirlo **sin arriesgar nada**: correr el copiador entero contra una
**copia restaurada de producción**, cronometrando cada paso. Eso da el número real
antes de comprometer una fecha. Si diera un tiempo que no se banca, ahí —y sólo
ahí— tiene sentido discutir la copia en caliente.

**Cuándo.** Un domingo temprano ART: los mercados están cerrados, no hay precios que
actualizar, y el cron del brief del asesor no corre (es de días hábiles).

---

### 2. Cómo se vuelve atrás, y dónde está el punto de no retorno

**Volver atrás es barato y es una sola cosa:** sacar `DATABASE_URL` y reiniciar. La
SQLite queda intacta — el copiador la LEE, no la toca (salvo el vaciado de
`raw_json` del paso 4, que es irreversible pero no cambia ningún saldo).

**El punto de no retorno NO es un reloj: es el primer usuario que escribe.** Y por
eso la secuencia de arriba deja los chequeos ANTES de abrir: mientras la app está en
mantenimiento, volver atrás es gratis. En cuanto se abre, cada compra, cada venta,
cada import cargado queda en Postgres y **no está en la SQLite**. Volver atrás
después es perder eso, sin herramienta que lo traiga de vuelta.

    mantenimiento, antes de abrir  →  volver atrás es GRATIS
    abierto, N escrituras después  →  volver atrás CUESTA esas N, y no hay
                                      forma automática de recuperarlas

**Y hay tres cosas que son irreversibles apenas pasan, aunque vuelvas atrás la base:**

- **Los mails del brief del asesor.** Dos por día hábil, a los asesores, con los
  números de sus clientes. Si el cron corre contra una base a medio copiar, **manda
  mails con números equivocados y no hay forma de desmandarlos.** Es la razón número
  uno para apagar los crons externos primero.
- **Los mails de billing** (trial por vencer, suscripción caída) que dispara
  `subscription_lifecycle`.
- **Cualquier ida a Rebill** (cobros, cancelaciones): eso toca un sistema de
  terceros y no vuelve con un rollback de la base.

**La regla que sale de eso, y conviene escribirla como regla:** volver atrás sólo
antes de abrir. Después de abrir, se arregla para adelante. Un rollback con usuarios
adentro no es "volver al día anterior": es perder trabajo de gente que no se enteró
de nada.

---

### 3. Qué se mira en los primeros 10 minutos

Con la app **todavía en mantenimiento** y `DATABASE_URL` puesta. Lista corta, en
orden, y cada una tiene un criterio de "pasa / no pasa":

| # | qué | pasa si |
|---|---|---|
| 1 | `/api/health` | contesta 200 |
| 2 | Los logs del arranque | cero `NotNullViolation`, cero `relation does not exist`, cero `EnsayoPorClonNoDisponible` inesperado |
| 0 | **¿contra qué motor está corriendo la app?** | dice Postgres. **Es el primero de todos**: `/api/health` NO toca la base, así que sin esto los otros ocho pasan igual con la app sirviendo desde la SQLite de siempre |
| 3 | Entrar con la cuenta de prueba | login OK y la Cartera carga |
| 3b | **Que NO se haya deslogueado todo el mundo** | ver la nota de abajo |
| 4 | **El total de 3 cuentas elegidas a mano** | coincide con el snapshot de anoche, al centavo |
| 5 | Un import de punta a punta | con un export real de los que ya están guardados; queda igual que en SQLite |
| 6 | Las pantallas pesadas (Dashboard, Cartera, Análisis) | cargan, y sin timeouts |
| 7 | **Conexiones abiertas contra Supabase** | bien por debajo del límite del plan (`[A MEDIR]`) |
| 8 | Los seis escritores del arranque | prendidos DESPUÉS del resto, uno por uno, mirando los logs |

**El 4 es el que de verdad importa** y es distinto de la verificación del copiador:
aquélla compara las dos bases entre sí; ésta compara **lo que ve el usuario en
pantalla** contra lo que veía ayer. Un copiador puede estar perfecto y la app
mostrar otra cosa, porque en el medio hay valuación, FX y caché.

**El 7 es el riesgo nuevo que Supabase trae y el Postgres local no tenía.** Los 33
`get_db()` expuestos ya están arreglados (`db_abierta()`), pero eso se midió contra
un Postgres local con 100 conexiones de margen. **Cuántas da el plan contratado es
`[A MEDIR]`, y hay que saberlo ANTES, no ese día.**

⚠️ **Sobre el 3b — hay que confirmar `SECRET_KEY` ANTES, y es de un minuto.** El
pasaje incluye un reinicio, y si `SECRET_KEY` no está puesta en Railway, el arranque
**genera una al azar** (`main.py:111`) y con eso **se invalidan todos los tokens: se
desloguean los 1.084**. No se pierde plata, pero convierte un pasaje invisible en
"a todo el mundo se le cerró la sesión el mismo día que tocamos la base", que es
justo la clase de ruido que no querés mientras verificás otra cosa. Se confirma
mirando las variables de Railway; si está puesta, los tokens sobreviven el reinicio.

Dato lateral que juega a favor: los tokens llevan adentro el `password_changed_at`
del usuario y se validan contra la base. Si el copiador hubiera perdido esa columna,
**se desloguearía todo el mundo** — o sea que el 3b también funciona como chequeo
gratis de que esa columna viajó bien.

---

### 4. Los crons

Son **siete**, de tres clases distintas, y sólo una de las tres se apaga sola.

**Clase A — disparados desde AFUERA (un scheduler externo pega la URL).** Son los
peligrosos: siguen disparando aunque la app esté en mantenimiento, y si pasan el
gate de mantenimiento escriben.

    /api/alerts/evaluate          alertas de precio        ALERTS_CRON_TOKEN
    /api/snapshots/run-cron       foto diaria              SNAPSHOT_CRON_TOKEN
    /api/advisor/brief/run-cron   el brief del asesor      manda MAILS

**Se apagan en el scheduler externo** (donde estén configurados) **y son lo primero
del día.** No alcanza con el modo mantenimiento: si el gate los deja pasar por ser
crons, escriben; si no los deja pasar, el scheduler externo va a registrar fallas
—lo cual está bien, pero hay que saberlo de antemano para no asustarse.

🔴 **La palanca de respaldo NO funciona para el que manda mails, y eso lo había
escrito mal.** Puse que "borrar el token de entorno los desarma solos". Es cierto
para los dos primeros, y **falso justo para el brief del asesor**:

    expected = ((os.environ.get("ADVISOR_BRIEF_TOKEN") or "").strip()
                or (os.environ.get("SNAPSHOT_CRON_TOKEN") or "").strip())   # ← fallback

Borrar `ADVISOR_BRIEF_TOKEN` **lo deja armado** con el token de snapshots
(`main.py:30463-30464`, el fallback está puesto a propósito "para no multiplicar
secretos"). O sea que la red de seguridad que inventé no cubre **el único cron que
manda mails**, que es justo el que llamé "la razón número uno".

Para desarmarlo de verdad hay que borrar **los dos** tokens — y borrar
`SNAPSHOT_CRON_TOKEN` desarma también el cron de snapshots, que es lo que se quiere
ese día igual. Anotado así: **se borran los tres tokens, no uno.**

**Clase B — APScheduler adentro del proceso.** Arrancan con la app y mueren con
ella, así que apagar el backend los apaga. Pero **vuelven solos en el reinicio**:

    02:59 UTC   daily_snapshot            escribe snapshots
    03:30 UTC   subscription_lifecycle    baja planes, manda MAILS
    03:45 UTC   backup_db                 ⚠️ SÓLO-SQLITE (ver punto 0c)
    12:10 UTC   fci_refresh               precios de FCI

**La ventana conviene lejos de esos horarios.** Un domingo a la mañana ART (≈13-14
UTC) está después de los tres de la madrugada y después del de las 12:10.

**Clase C — los seis escritores del arranque** (punto 0b). No son crons pero se
comportan igual y son peores, porque disparan **exactamente cuando prendés
`DATABASE_URL`**.

**Quién los vuelve a prender:** los de la clase B vuelven solos con el reinicio, sin
que nadie haga nada — eso es un riesgo, no una comodidad: si el pasaje se hace de
noche, el `daily_snapshot` puede dispararse sobre una base a medio verificar. Los de
la clase A hay que prenderlos **a mano y al final**, después de los chequeos, y hay
que dejar anotado dónde están configurados: **`[A MEDIR]` — el doc no dice en qué
servicio corren.**

---

### 4-bis. Dos cosas que NO se van a ver hasta Supabase, y las dos están medidas acá

Aparecieron revisando el plan, y comparten una propiedad incómoda: **el Postgres
local no las puede mostrar**, así que todo lo verde que dice este doc no dice nada
sobre ellas. Van acá porque las dos se prueban el día que se conecta a Supabase, no
el día del pasaje.

**a) `psycopg` prepara sentencias solo, y el pooler de Supabase las rompe.**
Medido en este mismo Postgres local: `prepare_threshold` viene en **5**, y después
de 7 ejecuciones de la misma consulta hay **1 sentencia preparada en el servidor**.
Eso está perfecto contra una conexión directa. Pero Supabase ofrece **dos puertos**:
la conexión directa (5432) y el **pooler transaccional** (6543), que multiplexa
conexiones — y con multiplexado la sentencia preparada queda en un backend y la
consulta siguiente cae en otro. El síntoma es intermitente y tiene nombre:
`prepared statement "_pg3_0" does not exist`.

> **Es la peor forma de fallar para este proyecto**: no aparece en ningún test, no
> aparece con la conexión directa, aparece sólo bajo carga y de a ratos. Las dos
> salidas son elegir el puerto de sesión, o pasar `prepare_threshold=None` al
> conectar. **Hay que decidirlo antes de conectar, no después de ver el error.**

**b) No hay pool de conexiones: cada `get_db()` abre una conexión nueva.**
Verificado: `pgshim.connect()` llama a `psycopg.connect()` directo, sin pool, y hay
**267 `get_db()`** en el código. Medido acá, sobre socket unix y sin TLS:

    abrir una conexión:   Postgres 1,03 ms   SQLite 0,032 ms   (32×)

Contra Supabase hay que sumarle ida y vuelta de red **más handshake TLS, por cada
conexión** — `[A MEDIR]`. Es el mismo tipo de problema que el `_table_cols()` que
hubo que cachear en la sesión 13/08 (20 viajes por pantalla), pero más grande,
porque no es una consulta de más: es una conexión de más. Y pega dos veces: en la
latencia de cada pantalla y en el conteo de conexiones contra el límite del plan.

**Las dos se miden en el paso 8 del "Orden sugerido" (probar contra Supabase), y
ese paso pasa a ser BLOQUEANTE del pasaje, no un "estaría bueno".**

### 5. Probar que el techo se fue

Que el `database is locked` no vuelva está **argumentado** (Postgres no tiene un
escritor único para toda la base) pero **no medido**. Y la diferencia importa: los
tres culpables del 12 y 13/08 ya están arreglados en `main`, así que la SQLite de
hoy aguanta más que la de aquel día. Comparar contra el recuerdo del incidente
mediría lo que ya se arregló, no el techo.

**La prueba, simple y suficiente:**

- **Contra las dos bases, el mismo guion.** Es lo mismo que hace el resto del
  proyecto: correr la misma cosa en los dos motores y comparar.
- **Con ESCRITURAS, que es donde estaba el techo.** El lock era de escritura, y en
  esta app **cada carga de página escribe** (últimos precios, noticias). O sea que
  el guion no necesita inventar nada raro: alcanza con N usuarios cargando el
  Dashboard y la Cartera a la vez.
- **Subiendo la concurrencia hasta que rompa**, y anotando en qué número rompe cada
  uno. El resultado que buscamos no es "Postgres anda": es **"SQLite empieza a
  fallar en N y Postgres en M, con M mucho mayor"**. Si M no es mucho mayor, la
  migración no compró lo que creíamos y hay que saberlo antes.
- **Qué se anota:** errores por minuto, p95 de respuesta, y conexiones abiertas.
- **Contra Supabase, no contra el Postgres local.** El local no tiene red en el
  medio ni límite de conexiones apretado, que son justo las dos cosas nuevas.

**Y el número de usuarios de la prueba no se inventa:** sale de mirar cuántos
concurrentes hubo el 12 y el 13/08, que es el único momento en que se sabe que el
techo se tocó. **`[A MEDIR]`: ese dato está en los logs de Railway de esos días.**

---

### Siete cosas más que salieron de atacar este plan

El plan se pasó por una revisión adversarial cuando estaba escrito. Además de los
tres errores míos ya corregidos arriba (el snapshot sólo-SQLite, las 60 tablas, y
el vaciado de `raw_json`), salieron estas siete. Las siete están **verificadas por mí**, no sólo reportadas:
el ataque perdió 7 de sus 17 agentes por errores de infraestructura, así que varias
nunca pasaron por su propio escéptico y no se podían dar por buenas.

**1. 🔴 Ningún chequeo distingue "migramos" de "la variable no agarró".**
`/api/health` devuelve `ok`, `timestamp`, `service` y `commit` — **no toca la base**
(`main.py:30787-30812`). Así que si `DATABASE_URL` no tomó efecto, la app sigue
sirviendo feliz **desde la SQLite** y los ocho chequeos pasan: el login anda, los
totales coinciden (¡obvio, es la misma base de siempre!), las pantallas cargan.
Verificás una migración que no ocurrió.
**Falta un chequeo 0**: preguntarle a la app **contra qué motor está**. Sin eso, todo
lo demás mide otra cosa.

**2. 🔴 No es "falta `psycopg`": ES QUE EL CÓDIGO DE POSTGRES NO ESTÁ EN `main`.**
Verificado con `git cat-file` contra la rama de producción:

    backend/pgshim.py       en main: NO
    backend/dberrors.py     en main: NO
    backend/schema_pg.sql   en main: NO
    psycopg en requirements de main: NO

O sea que **el paso 10 —"prender `DATABASE_URL` y reiniciar"— es imposible**: no hay
qué prender. Yo lo había anotado como "un prerrequisito de una línea", y es un merge
más un deploy. Hacer eso el día del pasaje es hacerlo **con el reloj de la ventana
corriendo y después del vaciado irreversible.**

⚠️ **Y hay una trampa que lo vuelve invisible hasta el peor momento:** `get_db()`
importa `pgshim` **de forma perezosa y sólo si `USANDO_PG`** (`main.py:344-347`). Así
que si mergeás días antes **sin** la variable, el deploy sale verde y el faltante no
se nota. El día del pasaje, con la variable puesta y sin `psycopg` instalado,
`init_db()` corre al importar el módulo, uvicorn no levanta, y Railway lo deja en
crash-loop: la app no contesta ni `/api/health`.

**Va días antes, y en producción, sin `DATABASE_URL`** (o sea sin cambiar nada para
el usuario): agregar `psycopg[binary]` a `requirements.txt`, mergear y deployar, y
**confirmar por el `commit` que devuelve `/api/health`** que el bundle nuevo está
arriba — que para eso está ese campo.

**3. La verificación es una biblioteca sin programa.** `verificar_copia.py` tiene las
funciones y los tests, pero **no tiene un `main`**: el paso 9 dice "correr la
verificación completa" y no hay nada que correr. Hace falta el CLI que ate los cuatro
niveles, imprima los hallazgos y devuelva un código de salida distinto de cero si
hay alguno. Va junto con el copiador.

**4. Rebill entra DESDE AFUERA.** Apagamos los tres crons, que es lo que SALE. Pero
los webhooks de pagos **entran** cuando el proveedor los manda, no cuando nosotros
queremos. Alguien que pague ese domingo, con la app en mantenimiento, puede quedarse
sin su plan activado. **Hay que averiguar si Rebill reintenta los webhooks fallidos y
por cuánto tiempo** — `[A MEDIR]`. Si reintenta, no hay problema; si no, hay que
revisar los pagos del día a mano.

**5. 🔴 El estado "arriba contra Postgres y cerrada al público" NO EXISTE.**
El único mecanismo de mantenimiento que el plan acepta es apagar el backend — y el
paso 10 lo prende. Entonces el paso 11 ("los chequeos con la app TODAVÍA en
mantenimiento") y el paso 12 ("recién ahí, abrir") **son el mismo momento**: hay dos
pasos y una sola palanca.

Y la consecuencia es justo la que el plan dice querer evitar: durante esos 10 minutos
de chequeos —que incluyen un import de punta a punta, o sea escrituras— los 1.084
pueden entrar y operar contra Postgres. **Se cruza el punto de no retorno mientras
estás decidiendo si la copia sirve**, y el chequeo 4 (los totales al centavo contra
el snapshot de anoche) deja de ser confiable si alguien operó en el medio.

Esto **asciende el modo mantenimiento de "estaría bueno" a REQUISITO** — contradice
lo que escribí en el punto 0a y hay que leerlo así. Necesita bypass: 503 para todos
salvo si viene un token nuestro. La alternativa sin código —sacarle el dominio
público al servicio en Railway y chequear por la URL interna— **se prueba antes, no
ese domingo.**

**6. Nadie dijo en qué máquina corre el copiador.** Los pasos 3 a 7 trabajan sobre
`/data/trading.db`, que vive en el volumen de Railway, y el paso 2 apaga el único
proceso que lo tiene montado. Las dos salidas rompen algo: dejar el backend prendido
para tener shell significa copiar una base que se mueve; bajarse el archivo a tu
máquina suma la bajada de ~933 MB y la subida a Supabase por tu internet — tiempo que
el hueco #1, medido en laboratorio, **no** mide. Además el paso 3 dice "backup
guardado FUERA del volumen" y hoy no hay mecanismo: el único endpoint que existe
(`POST /api/admin/backup-trigger`) escribe **adentro** del volumen, y el destino S3 de
`backup_db.py` es opcional (`BACKUP_S3_*`) y no se sabe si está configurado.

**7. Nadie mira el disco antes de copiar.** El paso 3 (backup a mano) y un eventual
`VACUUM` escriben archivos del tamaño de la base **en el mismo volumen de Railway**,
que ya está al 97% de ocupación con backups viejos según lo que dice este mismo doc
más abajo. Un backup que no entra es un backup que no existe. **Mirar el espacio
libre antes es gratis y evita el peor momento posible para descubrirlo.**

### Los huecos, juntos, para que no se pierdan

| # | qué falta medir | por qué importa |
|---|---|---|
| 1 | cuánto tarda copiar + verificar, sobre una copia restaurada de prod | decide si la ventana alcanza, y decide la fecha |
| 2 | cuánto tarda el `VACUUM` post-vaciado de `raw_json`, si se hace | puede ser el paso más largo del día |
| 3 | cuántas conexiones da el plan de Supabase contratado | es el límite nuevo. Son **267 `get_db()`** y cada uno abre una conexión (no hay pool); los **33** que se arreglaron eran los que además no la cerraban, y eso se midió contra un local con 100 de margen |
| 4 | qué backups trae ese plan | hoy el backup propio quedaría mintiendo (punto 0c) |
| 5 | dónde están configurados los tres crons externos | hay que apagarlos y volver a prenderlos |
| 6 | cuántos usuarios concurrentes hubo el 12 y 13/08 | es el piso de la prueba de carga |
| 7 | **latencia de abrir UNA conexión contra Supabase** (con red y TLS) | local da 1,03 ms y no hay pool: son 267 `get_db()`. Ver 4-bis(b) |
| 8 | **por qué puerto se conecta**: directo (5432) o pooler (6543) | con el pooler, las sentencias preparadas de `psycopg` fallan de a ratos. Ver 4-bis(a) |
| 9 | está puesta `SECRET_KEY` en Railway | si no, el reinicio del pasaje desloguea a los 1.084 |
| 10 | **¿Rebill reintenta los webhooks fallidos, y por cuánto?** | los pagos ENTRAN durante la ventana; si no reintenta, hay que revisarlos a mano |
| 11 | **espacio libre en el volumen** antes del backup y del VACUUM | el doc dice que el volumen ya está al 97%; un backup que no entra no existe |
| 12 | **re-correr el audit de tipos SIN muestreo** (o por la cola) sobre la copia restaurada | el audit original miró las filas más VIEJAS: los parsers nuevos nunca se auditaron |
| 13 | **¿está configurado `BACKUP_S3_*` en Railway?** | el paso 3 pide el backup FUERA del volumen y hoy no hay mecanismo si eso no está |

**Ninguno de los nueve se estima. Los nueve se miden antes de comprometer una fecha.**

Y hay un orden entre ellos: **el 7 y el 8 se miden ANTES que todo lo demás**, porque
si el 8 sale mal el pasaje no arranca, y si el 7 sale mal puede haber que meter un
pool antes de mover a nadie.

## Sesión 9 — el diseño del copiador, atacado antes de escribirlo

66 hallazgos en 5 barridos, 40 ataques desde 4 lentes, **5 bloqueantes**. Lo que
sigue son las decisiones tomadas y los dos bloqueantes que ya están arreglados. El
análisis completo quedó en `DISENO_COPIADOR.md` (fuera del repo, es material de
trabajo).

### DECISIÓN 1: `raw_json` NO se vacía. Se migra todo.

**Y la consecuencia es la más grande de la sesión: el día deja de tener un paso
irreversible antes de los chequeos.** El vaciado era el único, y todo el diseño de
la ventana giraba alrededor de protegerlo (la foto ANTES, el nivel 0, el orden de
los pasos 4-5-6). Sin vaciado, eso se cae solo: si algo sale mal, se saca
`DATABASE_URL` y no hay nada que deshacer sobre el origen.

El motivo de la decisión fue otro y apareció atacando: **vaciar `raw_json` apagaba
CUATRO lectores, no uno.** El doc tenía decidido perder "Editar y rehacer"; los
otros tres no estaban en la cuenta:

| lector | qué dejaba de andar |
|---|---|
| `reconstruct_csv_from_batch` | "Editar y rehacer" (el único que estaba contado) |
| `flujos.py:candidatos()` | decide si un traspaso de títulos es entrante o saliente. Lee filas rechazadas **dentro de batches confirmados** — justo la población que el vaciado tocaba. Con la columna vacía, todo flujo ambiguo quedaba **indecidible para siempre, sin error**. ⚠️ Corrección (Fase 1 del reconstructor): cuando se escribió esta fila el filtro era `status != 'ok'`, que era **siempre verdadero** (el pipeline escribe `'valid'`/`'invalid'`, nunca `'ok'`) y **no acotaba por batch**. Hoy sí: `r.status='invalid' AND b.status='confirmed'`. La conclusión de la fila no cambia — la población que el vaciado tocaba es exactamente ésa |
| `main.py:16039` `fila_original` | el diagnóstico de montos inflados: es lo que distingue "lo rompió el parser" de "vino mal del broker" |
| `main.py:28427` | la pantalla donde el usuario ve sus filas crudas |

Dos de los cuatro son herramientas de diagnóstico del propio equipo — las que se
usan justo cuando un import sale mal.

**Lo que cuesta:** viajan las 3,4M de filas con el andamio adentro, así que la
ventana es más larga. **Cuánto más largo es exactamente lo que el cronómetro tiene
que medir** — y ese número ahora es más importante que antes, porque es el único
costo de esta decisión.

### DECISIÓN 2: `fci_catalog` y `fci_prices` van en `schema_pg.sql`, arreglando el GENERADOR

No es ninguna de las tres opciones de la lista: es la (a) hecha un nivel más arriba.

**La raíz:** `mkschema.py` importa `main` (o sea corre `init_db()`) y lee
`sqlite_master`, pero **nunca llamaba a `ensure_tables()`**. El esquema tenía 58
porque le preguntó a `init_db()` cómo es producción, y producción es `init_db()`
**+** lo que `pricing/fci.py` crea en caliente. **Es la misma categoría que los
otros cuatro errores del proyecto: el artefacto se generó contra la fuente
equivocada.** Parchear la salida habría dejado la causa intacta.

Verificado en este orden, y el orden importa:

| chequeo | resultado |
|---|---|
| regenerar con `ensure_tables()` | **60 tablas**, 62 índices, 12 FKs |
| **control**: ¿la diferencia era mía? | corrí el generador SIN el parche: las diferencias de indentación **ya estaban**; `diff -w` da limpio |
| el diff clasificado línea por línea | 22 de las FCI + 12 renombres de FK + 41 de espacios preexistentes + **0 sin explicar** |
| aplicar el esquema de 60 en Postgres | **134/134 sentencias OK, 60 tablas** |
| ¿aparece un tipo que `canon` no conozca? | no: sigue siendo `{bigint, double precision, text}` |

**Con esto `saltear` queda VACÍO**: las dos tablas viajan como cualquier otra.

⚠️ **Y `mkschema.py` ahora vive en el repo** (`backend/scripts/mkschema.py`). Antes
estaba en `/private/tmp`, que macOS purga: arreglar la raíz en un archivo que se
puede evaporar no es arreglarla. De paso se le sacaron las dos rutas absolutas.

### 🔴 BLOQUEANTE 1 (arreglado): cada arranque DUPLICABA las 12 claves foráneas

`_init_db_postgres()` (`main.py:552`) re-aplica `schema_pg.sql` **entero en cada
arranque**. Su docstring decía *"idempotente: todo va con IF NOT EXISTS"* y era
falso para 12 de las 132 sentencias: las 12 `ALTER TABLE … ADD FOREIGN KEY`, que
iban **sin nombre**.

Y una FK sin nombre **no falla al repetirse**: Postgres le autogenera un nombre
libre y crea una segunda constraint idéntica. Medido, no razonado:

    arranque 1: NO dio error   arranque 2: NO dio error   arranque 3: NO dio error
    >>> FKs sobre brokers después de 3 arranques: 3
    >>> nombres: brokers_user_id_fkey, brokers_user_id_fkey1, brokers_user_id_fkey2

Lo que costaba: cada `ADD FOREIGN KEY` **valida la tabla hija entera** tomando
ACCESS EXCLUSIVE, y 5 de las 12 caen sobre tablas de ~1M de filas. Como `init_db()`
corre al IMPORTAR el módulo, uvicorn no llega a abrir el puerto → healthcheck rojo
→ Railway reinicia → otras 12. **Es la forma exacta del 502 del 2026-08-02.**

⚠️ **Y lo peor era la defensa que no defendía.** `main.py:561` tiene un
`except psycopg.errors.DuplicateObject: pass` con el comentario *"la FK ya existía
(ADD FOREIGN KEY no tiene IF NOT EXISTS)"*. Alguien vio el problema, lo escribió, y
puso la red para el error equivocado: sin nombre ese error **nunca se levanta**.

**Arreglado en la raíz**: las FKs salen con nombre desde `mkschema.py`. Con nombre,
repetir sí levanta `DuplicateObject` y el `except` recién hace lo que dice hacer.
Test: `tests/test_esquema_pg_reaplicable.py`, que revisa **todas** las sentencias
del archivo (la categoría, no las 12 FK) y además lo prueba aplicando el esquema dos
veces contra Postgres. Con el esquema viejo: **12 → 24 FKs**.

### 🔴 BLOQUEANTE 2 (arreglado): el NIVEL 0 era FAIL-OPEN — y es un error MÍO de esta misma sesión

`foto_para_vaciado` guardaba la tabla que no podía leer como `("ERROR", mensaje)`
**adentro del `try`**, y `comparar_vaciado` sólo denuncia cuando los valores
DIFIEREN. Dos ERROR idénticos comparan iguales. Medido:

    las 2 tablas fueron ILEGIBLES → hallazgos del NIVEL 0: []  →  "sin hallazgos"

El único nivel que vigilaba el único paso irreversible del día podía no leer nada e
imprimir que estaba todo bien. Y tenía **el mismo segundo agujero** que `comparar()`:
la lista de tablas salía del `esquema` del **DESTINO**, aunque las dos fotos son del
ORIGEN.

⚠️ **Esto estaba en el mismo archivo que se arregló a la mañana y no se barrió.**
El detector nuevo busca *parámetros opt-in*; esto es la otra forma de la misma
familia — *la red que devuelve verde cuando no pudo mirar* — y ahí no había ningún
parámetro: había un `except` que convertía el error en un dato comparable. **Se
eligió mal el borde de la categoría.** Es, otra vez, el error de barrer el patrón y
no la categoría.

**Arreglado, y barriendo los tres miembros que tenía el archivo:**

| sitio | era | ahora |
|---|---|---|
| `foto_para_vaciado`, tabla ilegible | la guardaba como valor | **levanta `FotoIlegible`** |
| `foto_para_vaciado`, lista de tablas | del DESTINO, por parámetro | de `catalogo_origen()`, **sin parámetro** |
| `secuencias_atrasadas`, identity sin secuencia | `continue` en silencio | **la denuncia** |
| `comparar()`, `tablas_comparadas` | contaba intenciones | **cuenta las que de verdad leyó**, más `tablas_en_el_origen` |

Cada uno con su test y **mutado por separado**: los tres caen cada uno con SU
mutante y sólo con el suyo.

### ✅ Los relojes del conftest: subidos, configurables, y el orden se VALIDA

Medido por el dueño, tres corridas seguidas **sin nada más corriendo**:

| corrida | fallas | tiempo |
|---|---|---|
| #1 | 46 | 68s |
| #2 | **49** | **133s** ← las 3 extra: `IdleInTransactionSessionTimeout` |
| #3 | 46 | 71s |

No era una fuga ni otra suite: era **la máquina**. Con `idle_in_transaction` en 3s,
cuando la máquina se pone lenta y la corrida tarda el doble, un test **legítimo**
pasa más de 3s con la transacción abierta y Postgres lo mata. O sea que el número de
la suite volvía a depender de la carga — el mismo problema que costó tres sesiones,
con otra cara.

**El orden sigue intacto y sigue siendo el arreglo**, sólo que con más aire:

    idle_in_transaction (6s)  <  lock_timeout (12s)  <  --timeout de pytest (20s)

Y se pueden ajustar sin tocar código: `RENDI_TEST_IDLE_TX_S` y `RENDI_TEST_LOCK_S`
(apretar en CI, aflojar en una máquina cargada). Un valor inválido **levanta**, no
cae al default en silencio: caer sería lo peor de los dos mundos, porque el que
quiso apretar los relojes creería que los apretó.

🔴 **El riesgo del arreglo era subir uno solo**, y por eso el orden dejó de ser un
comentario: `pytest_configure` lo valida y **la suite no arranca mal configurada**
(`pytest.UsageError`). Test: `tests/test_relojes_del_conftest.py`, 13 casos, con las
dos mitades del orden mutadas por separado **y** un mutante que deja la validación
escrita pero desconectada del arranque — que es la forma en que una red así se
vuelve decorativa.

### ✅ `fci_catalog` / `fci_prices`: 60 = 60, y `saltear` queda VACÍO

La pregunta que había quedado servida se contestó de rebote al arreglar
`mkschema.py`. Confirmado corriendo `comparar()` sobre la forma real:

    ORIGEN (init_db + ensure_tables): 60 tablas
    DESTINO (schema_pg.sql):          60 tablas
    tablas que no viajaron:           ninguna
    saltear necesario:                NO — vacío
    tablas_comparadas / en_el_origen: 60 / 60

Ese último renglón es el que importa y es nuevo: el informe ahora dice **cuántas
comparó de verdad** contra cuántas hay en el origen. Antes decía "60" aunque hubiera
leído 58.

### Lo que queda anotado y NO arreglado

- **`psycopg` no está en `backend/requirements.txt`** (verificado). Prender
  `DATABASE_URL` hoy hace crash-loop. Ya estaba anotado; sigue siendo prerrequisito.
- **No hay modo mantenimiento**, así que los pasos "chequear" y "abrir" son el mismo
  momento. El ataque lo confirma y lo asciende a requisito.
- ~~**`advisor_alerts.advisor_uid` / `advisor_profile.advisor_uid` salen como
  IDENTITY sin serlo**~~ ⬇️ **BAJADO DE PRIORIDAD: es traducción FIEL.** Verificado
  por el dueño: en SQLite `advisor_uid INTEGER PRIMARY KEY` **es el alias del
  rowid y también autoasigna**. Los dos motores se comportan igual, así que no es
  algo que introduzca la migración: es una rareza preexistente del modelo. Queda
  anotada, no bloquea.
- **Nadie compara los DEFAULT declarados** entre origen y destino, y ya hay uno
  divergente (`users.password_changed_at`: el CREATE tiene `datetime('now')`, el
  ALTER que aplicó a producción no).

## ✅ Sesión 11 — LA COPIA COMPLETA CONTRA SUPABASE REAL: ANDA

**3.368.336 filas, 60/60 tablas, CERO hallazgos en los cuatro niveles**, contra el
Supabase de verdad (São Paulo, PostgreSQL 17.6, plan Pro).

| | |
|---|---|
| la copia en sí | **122,6 s** — de los cuales `import_raw_rows` (3,1M) son 96,1 s |
| `copiar` completo (preflight + copia + setval + los 4 niveles) | **3 min 35 s** |
| local, para comparar | 34 s la copia / 61 s el comando |

O sea: **la red cuesta 3,6× el trabajo de CPU**, y la ventana de mantenimiento para
este paso es de **unos 4 minutos**, no de una hora. El hueco `[A MEDIR]` más
importante del plan queda cerrado con un número medido.

**Verificado desde afuera, con conexión nueva:** 3.368.336 filas exactas, 1168 MB,
**12 FKs sin duplicar**, 2.168 auto-referencias resueltas, y un alta nueva devuelve
id **1085** (el `setval` anduvo: no choca contra un id existente).

### Lo que pasó antes, y por qué el número de arriba existe

**El primer intento tumbó el proyecto.** Estaba en plan Free (500 MB de disco) y la
copia lo llenó: `DATABASE 553 MB · WAL 660 MB · SYSTEM 759 MB`. El disco al 100%, la
instancia en recuperación, y **no se levantó sola: hubo que reiniciarla a mano desde
el panel** — el upgrade a Pro por sí solo no la revive.

⚠️ Y una cosa que aparece después de un rollback y no es obvia: **la base quedó
pesando 800 MB con CERO filas.** El rollback borra las filas pero no achica los
archivos. `preparar-destino` (que hace `TRUNCATE`) los recrea vacíos y la dejó en 13
MB. Si no se limpia, la copia siguiente arranca con 800 MB de lastre.

### El dato que corrige el techo: Supabase comprime el WAL

    local:     wal_compression = off     → WAL medido 1.606 MB (1,33× los datos)
    Supabase:  wal_compression = zstd

Así que el **2,63× que mide `vigilar_espacio.py` es un TECHO** y contra Supabase el
pico real es menor. La copia entera entró sin problemas en el plan Pro (8 GB).

### El transaction pooler (6543), candidato para la app

Conecta, ve los datos, y `extra_float_digits=3` llega bien (o sea que el arreglo de
`pgsesion` funciona también por ahí). Latencia: **46,8 ms** por ida y vuelta.

⚠️ **Las sentencias preparadas NO rompieron — y eso NO es una garantía.** Se
probaron 12 consultas seguidas, incluso con el `prepare_threshold=5` que trae
psycopg por defecto, y ninguna falló. Pero el modo de falla conocido
(`prepared statement "_pg3_0" does not exist`) es **intermitente y aparece bajo
carga**, cuando el pooler te cambia de conexión de servidor entre transacciones —
que es justo lo que 12 consultas seguidas en una sola conexión no ejercitan.
**No convertir una no-reproducción en una garantía.** `prepare_threshold=None` no
cuesta nada y saca la pregunta del medio: se deja puesto.

## 🔴 Sesión 11 — EL WAL: el término que faltaba, y que tumbó el destino

**Copiando 1 GB a un Supabase Free, la instancia se cayó con el disco al 100%.** El
panel mostró el desglose, y ahí está el hallazgo entero:

    DATABASE 553 MB   ·   WAL 660 MB   ·   SYSTEM 759 MB

**El cuaderno de borrador pesaba MÁS que los datos.** Es consecuencia directa de una
decisión del copiador: todo va en UNA transacción, para que un corte no deje nada a
medias. El precio es que el WAL no se puede reciclar hasta el commit, así que crece
monótonamente. Los 62 índices lo multiplican: cada índice también escribe WAL.

⚠️ **Todo el dimensionamiento decía "1 GB de datos". El requisito real es datos +
WAL + sistema**, y nadie había contado el segundo.

### El número, medido (`scripts/vigilar_espacio.py`)

Se puede medir **sin el destino real**: cuánto WAL genera la copia depende de la
copia, no de dónde se copie.

| | |
|---|---|
| datos al final | **1.211 MB** |
| **WAL generado** | **1.606 MB** — 1,33× los datos |
| **pico total simultáneo** | **2.817 MB ≈ 2,8 GB** |
| en veces el `.db` de origen | **2,63×** |

    plan Free  500 MB  →  🔴 NO entra, ni cerca
    plan Pro     8 GB  →  ✅ entra, con ~5 GB de margen

⚠️ **Medido con `wal_compression=off` y `full_page_writes=on`.** Si el destino
tuviera `wal_compression=on`, el WAL sería bastante menor. O sea que 2,8 GB es un
**techo**, no un piso. Y la fixture es ~13% más grande que producción, así que el
número real debería ser algo menor.

**La regla para el futuro, que es lo reusable:** el disco del destino tiene que
aguantar **~2,6 veces el tamaño del archivo SQLite**, a la vez, aunque al final
ocupe la mitad.

### Si algún día no entrara

La palanca es **commitear por tabla** en vez de una sola transacción: el WAL se
recicla en el camino y el pico baja al de la tabla más grande. Se paga perdiendo el
todo-o-nada — que hoy es justo lo que hace inofensivo un corte (medido: matando el
copiador a los 12s quedaron 0 filas y el reintento anduvo directo). **Con 8 GB no
hace falta**, y por eso no se toca.

## Sesión 10 — las dependencias, el corte a mitad, y qué falta de verdad

### ✅ `psycopg` en `requirements.txt` — y apareció un SEGUNDO caso

`psycopg[binary]==3.2.13`, pinneado porque está en el camino crítico, y `[binary]`
porque esa variante trae libpq adentro del wheel (en Railway no está garantizado que
el sistema lo tenga). **Verificado de verdad, no por inspección**: venv limpio,
`pip install -r requirements.txt`, y `psycopg.connect()` contra Postgres 16.2.

**Buscando la CATEGORÍA en vez del paquete apareció `httpx`.** Lo importan
`billing/emails.py`, `billing/mercadopago.py` y `billing/rebill.py` —producción,
plata de verdad— y **no estaba declarado**: andaba porque lo arrastra `anthropic`
como dependencia suya. El día que anthropic cambie de cliente HTTP, los mails de
billing y los webhooks de pago dejan de andar sin que nadie toque ese código.
Declarado con piso (`httpx>=0.27,<1.0`) y no pinneado a propósito: pinnearlo puede
chocar con lo que pida anthropic, que está sin pinnear. Lo que hacía falta era
DECLARARLO, no congelarlo.

**Detector**: `tests/test_dependencias_declaradas.py`. Barre todos los imports de
producción y falla si alguno no está en `requirements.txt`. Mutado: sacar `psycopg`
(el estado de ayer) lo hace fallar, sacar `httpx` también, y desanclar o sacarle el
`[binary]` a psycopg tira su propio test.

⚠️ **El detector nació mal y vale anotarlo:** el primer barrido dio **48 falsos
positivos** porque usaba `sys.stdlib_module_names`, que **no existe en Python 3.9 y
devuelve vacío en silencio** — así `json`, `sqlite3` y `datetime` pasaban por
dependencias sin declarar. Ahora resuelve cada módulo a su ruta real. Un detector
que denuncia todo es ruido que se aprende a ignorar.

`starlette` queda en `PERMITIDOS` con el motivo escrito: FastAPI está construido
sobre él y `fastapi==0.115.0` pinnea el rango que acepta, así que declararlo con
otra versión rompería la resolución. Es el caso donde declarar es PEOR.
`pytest`/`numpy`/`pandas` son sólo de tests y no se deployan — pero **que no exista
`requirements-dev.txt` es un hueco real**: quien clone el repo no sabe qué instalar
para correr la suite.

### ✅ Qué pasa si se corta a mitad — y CORRIGE el plan

Medido matando el copiador con SIGKILL a los 12 segundos, en mitad de
`import_raw_rows`, sobre la base de 1 GB:

    filas en el destino después del corte:  0
    conexiones colgadas idle in transaction: 0
    reintento:                               anduvo DIRECTO, 55s, 0 hallazgos

Todo el copiado va en UNA transacción, así que el servidor rollbackea solo cuando la
conexión muere. **Eso corrige lo que decía el plan** (*"`preparar-destino` +
reintentar"*): después de un corte **no hace falta** `preparar-destino`, el destino
ya quedó vacío. Ese subcomando sirve para rehacer una copia que TERMINÓ bien.

Queda como test determinístico (se fuerza el fallo en el paso siguiente al COPY en
vez de matar un proceso, que sería lento y flaky), y el mutante que cambia el
`rollback()` por un `commit()` lo hace caer.

### ✅ El término que faltaba del cronómetro, medido y no estimado

No se puede medir Supabase sin Supabase, pero sí se puede medir **cuántos bytes
viajan**, que es lo único que faltaba para poder dividir:

| | |
|---|---|
| payload del COPY (formato texto) | **0,95 GB** |
| de los cuales `import_raw_rows` | **0,93 GB (97,8%)** |

    20 Mbps → 6,3 min     50 Mbps → 2,5 min     100 Mbps → 1,3 min     300 Mbps → 25 s

Sumado al piso de CPU y disco (32-34 s), **la ventana queda dimensionada por la
subida y nada más**. Y deja clarísimo dónde está la palanca si no alcanza: el 97,8%
es una sola tabla, y es la que el vaciado de `raw_json` habría achicado. La decisión
de no vaciar tiene ahora su precio exacto en bytes.

⚠️ Calculado sobre la base sintética, cuyo `raw_json` pesa 273 bytes por fila. El
promedio real de producción no se conoce, y el archivo real es ~13% más chico que la
fixture, así que **el número real probablemente sea algo menor**. Es un techo, no un
piso. Y no cuenta el overhead de TLS ni del protocolo.

### 🔴 Lo que NO se pudo hacer, y qué hace falta para hacerlo

Son las dos cosas que sólo se contestan corriendo, y las dos necesitan material que
no está en esta máquina:

| | qué falta |
|---|---|
| **Medir contra Supabase** | credenciales del proyecto real (DSN). Sin eso no se puede decidir puerto de sesión (5432) vs pooler (6543), ni medir la subida, ni probar el corte a mitad contra la red de verdad. |
| **Preflight sobre datos REALES** | una copia restaurada del backup de producción. La `trading.db` local está **vacía (0 bytes)**, y la sintética es gemela del generador del esquema: **no puede** devolver un hallazgo de esquema. El preflight todavía no vio nunca un dato que lo sorprenda. |

Las dos son de un comando cuando el material esté:

```bash
python3 scripts/copiar_a_postgres.py --origen /ruta/restaurada.db --destino "$DSN" preflight
```

### 📐 MODO MANTENIMIENTO — diseño propuesto, NO implementado

El agujero: hoy "chequear" y "abrir" son el mismo momento. Apenas deployás con
`DATABASE_URL`, los 1.084 ya están adentro — y los chequeos de los primeros 10
minutos incluyen un import de punta a punta, o sea escrituras. **Se cruza el punto
de no retorno mientras estás decidiendo si la copia sirve.**

**Qué tiene que garantizar, en una línea:** que ninguna escritura de usuario llegue
a Postgres antes de que vos digas que sí.

**La forma: un middleware, el PRIMERO de la cadena, que no toca la base.**

    si mantenimiento_prendido():
        si el request trae el header de bypass válido  -> pasa
        si es /api/health o el chequeo de motor        -> pasa
        si no                                          -> 503 + JSON "estamos mudando la base"

Cuatro decisiones y el motivo de cada una:

1. **Va primero y NO consulta la base.** Si el gate dependiera de leer una tabla, un
   problema de base —justo lo que puede pasar ese día— se llevaría puesto también al
   mecanismo que te protege.
2. **El bypass va por header, no por query param.** Un token en la URL queda en los
   logs del proxy, en el historial y en el `Referer`. Comparado con
   `hmac.compare_digest`.
3. **503 y no 500.** `frontend/src/utils/api.js` ya reintenta con backoff ante
   503 y, pasados ~8s, muestra *"No pudimos conectarnos con el servidor. Suele ser
   una actualización en curso"*. O sea que **el mensaje correcto ya existe** y sale
   gratis. Con 500 el usuario vería un error crudo.
4. 🔴 **El default tiene que ser CERRADO, y es la parte que más importa.** Si el modo
   mantenimiento es un flag que hay que acordarse de prender, **es una red opt-in — y
   una red opt-in no es una red**, que es la lección que este proyecto ya pagó dos
   veces esta semana. La forma correcta es que **arrancar contra un motor nuevo
   implique mantenimiento**: si hay `DATABASE_URL` y no está la marca explícita de
   "el pasaje terminó", la app levanta cerrada. Olvidarse el flag te deja afuera a
   vos (visible, se arregla en 30 segundos); olvidarse al revés deja entrar a 1.084
   personas a una base que todavía no verificaste.

**Qué pasa si falla, en las dos direcciones:**

| falla | consecuencia | qué tan grave |
|---|---|---|
| queda trabado en mantenimiento | nadie entra, todos ven el mensaje de "actualización en curso" | molesto y **visible**; se sale sacando una variable y reiniciando |
| deja pasar a todos | usuarios operando mientras verificás; el chequeo de totales contra el snapshot de anoche deja de ser confiable, y el punto de no retorno se cruza solo | **el peor**, y es silencioso |

Por eso el default cerrado: las dos fallas no cuestan lo mismo, así que el mecanismo
tiene que estar sesgado hacia la barata.

**Lo que NO garantiza, y hay que saberlo:** no frena los crons externos (eso lo hace
el paso 1 del día, borrando los tres tokens), ni los requests que ya estaban en
vuelo cuando se prendió, ni los seis escritores del arranque (punto 0b, que es un
problema aparte y sigue abierto).

**Sin código, la alternativa es sacarle el dominio público al servicio en Railway y
pegarle por la URL interna.** Garantiza más (no hay app pública que valga) y no tiene
riesgo de bug, pero el usuario ve un fallo de DNS en vez del mensaje lindo, y **hay
que ensayarlo antes, no ese domingo**. Sirve como plan B del plan A.

**Costo estimado:** ~40 líneas de middleware más sus tests (503 para uno normal, 200
con el token, health exento, y el que fija que el default es cerrado). Se prueba
entero sin base.

## ✅ EL COPIADOR: ESCRITO, PROBADO Y CRONOMETRADO (sesión 9)

`backend/scripts/copiar_a_postgres.py` + `tests/test_copiar_a_postgres.py`
(21 casos). Cuatro subcomandos, separados porque son distintos de reversibles:

    aplicar-esquema   crea las 60 tablas (idempotente)
    preflight         SÓLO LEE. Precondición dura de `copiar`.
    preparar-destino  ESCRIBE: vacía el destino, para reintentar
    copiar            ESCRIBE: copia + setval + verificación final

### El número que faltaba: **la copia tarda 34 segundos**

Medido sobre la base de forma real (1.071 MB, 3.368.336 filas, 92% andamio),
Postgres local por socket unix:

| paso | tiempo |
|---|---|
| `preflight` (lee las 3,4M filas buscando lo que rompe) | **5,9 s** |
| la copia en sí | **33,8 s** — de los cuales 28,4 s son `import_raw_rows` (3,1M) |
| `copiar` completo, con preflight + setval + los 4 niveles | **61,4 s** |

Resultado: **60/60 tablas comparadas, 0 hallazgos en los cuatro niveles.**
Verificado además desde afuera, con una conexión nueva: 3.368.336 filas, 1165 MB en
Postgres, 2.168 auto-referencias resueltas, **12 claves foráneas sin duplicar**.

⚠️ **QUÉ MIDE ESTE NÚMERO Y QUÉ NO, porque es la parte que engaña.** Mide el
trabajo de CPU y de disco: leer SQLite, armar el COPY, escribir en Postgres. **No
mide la red**, y contra Supabase la red es el término dominante: son ~1 GB que hay
que subir. A 50 Mbps de subida son ~3 minutos; a 100 Mbps, ~1,5. **El piso es 34 s
y el techo lo pone tu conexión, no el copiador.** Sigue `[A MEDIR]` contra el
Supabase real, y ahora se sabe qué medir: el ancho de banda de subida.

**Y esto abarata la decisión de no vaciar `raw_json`.** Las 3,1M filas de andamio
cuestan 28 de los 34 segundos en CPU, pero **el vaciado nunca iba a sacar filas,
sólo bytes** (las filas viajan igual). O sea que su ahorro era de red, no de
tiempo de proceso — y a cambio apagaba cuatro lectores. La decisión se sostiene
mejor con el número a la vista que sin él.

### Los cinco bloqueantes del ataque, resueltos en el código

| bloqueante | cómo quedó |
|---|---|
| `with destino.transaction()` **no commitea** si algo ya abrió transacción (el preflight): reportaría éxito sobre una base vacía | `destino.commit()` **explícito**, y la verificación final corre en una **conexión NUEVA abierta después del commit** |
| el `.db` sin su `-wal` se lee incompleto y en silencio | `abrir_origen` **aborta** si hay WAL con datos, y el mensaje dice qué hacer (`wal_checkpoint(TRUNCATE)`) y qué NO hacer (sacarle el `mode=ro`) |
| el NIVEL 0 fail-open | arreglado en `verificar_copia.py` (ver arriba) |
| P3 se salteaba las 57 columnas `NOT NULL DEFAULT`, que son las de la plata | mide **las 230**: el default no salva, porque el COPY manda todas las columnas y una columna presente con NULL inserta NULL |
| las FKs duplicadas por arranque | arreglado en `mkschema.py`, y **P7 ya no compara contra un `12` hardcodeado: busca el duplicado**, que es el modo de falla real y no necesita saber cuántas tiene que haber |

**Medido, no razonado**, que `with conn.transaction()` pierde todo: con una consulta
previa en la conexión, adentro del bloque se ven 3 filas y en la base quedan **0**.
Queda como test para que nadie lo "simplifique" de vuelta.

### Lo que aprendió el copiador corriéndose

- **P8 daba 8 falsos positivos** porque comparaba nombres de tabla contra tuplas
  `(tabla, columna)`: la resta daba todo. Un chequeo que denuncia siempre es ruido
  que se aprende a ignorar, que es peor que no tenerlo.
- **P7 tenía un `12` hardcodeado** y estaba midiendo lo equivocado. Ver la tabla.
- Las dos aparecieron **corriendo el copiador**, no leyéndolo.

### Lo que sigue `[A MEDIR]`

1. **El ancho de banda de subida contra el Supabase real.** Es el término
   dominante y el único que falta.
2. **El preflight sobre la copia RESTAURADA de producción**, no sobre la
   sintética: la sintética se construye con `init_db()`, la misma fuente que
   `schema_pg.sql`, así que **no puede** devolver un hallazgo de esquema. Por eso
   el copiador imprime la huella del origen (md5 del esquema + tamaño + mtime): si
   no es la de producción, el preflight midió otra cosa.
3. **Puerto de sesión (5432) vs pooler (6543)**, y si `prepare_threshold=None`
   alcanza. Se decide antes de conectar.

## El copiador: LA VERIFICACIÓN ✅ ESCRITA Y PROBADA (sesión 6)

### 🔴 Sesión 8: la red estaba puesta pero era OPT-IN, y eso la anulaba entera

El agujero de las 60-vs-58 tablas se había tapado **a medias**: `comparar()` recibía
la lista del origen por un parámetro opcional, `tablas_origen=None`, y el chequeo
vivía adentro de un `if tablas_origen is not None:`. O sea que **el que no lo pasaba
volvía a tener la ceguera entera, en silencio**. El docstring decía "pasalo
SIEMPRE" — y eso es una advertencia, no un mecanismo. Es la forma exacta de los
últimos cuatro errores del proyecto: la red existe y queda sin poner.

Y no era uno: era **dos**. `cols_origen` tenía el mismo default y el mismo `if`, un
piso más abajo.

**El arreglo es no tener el parámetro.** `comparar()` ya no lo recibe: lo lee sola
del cursor del origen con `catalogo_origen()`. Olvidarlo no es posible porque no hay
nada que pasar, y de paso se cierra el error de un nivel más arriba —**mirar desde
la fuente equivocada**— porque la lista ya no puede venir del destino ni de una
variable de hace diez líneas.

- Si el origen no se puede leer, **levanta `OrigenIlegible`**. Nunca devuelve "ok".
- Si el origen no tiene ninguna tabla, **también levanta**: comparar cero cosas y
  decir "sin hallazgos" es el falso verde más caro que existe.
- Un llamador viejo que todavía mande `tablas_origen=` se come un **`TypeError`** en
  la cara, en vez de que se lo ignoren.

**El momento fue el correcto y salió barato:** los llamadores de `comparar()` eran
**todos tests** (verificado: `grep` de `verificar_copia` fuera de `tests/` no
devuelve nada), porque el copiador todavía no existe. Con el copiador y su runner ya
escritos, el default peligroso habría quedado en el camino de producción.

**El detector, y busca la CATEGORÍA y no estos dos nombres:**
`tests/test_verificacion_no_es_opt_in.py` barre con AST **todo `scripts/`** —
incluido el copiador el día que exista— y falla si alguna función tiene un
parámetro que cumple las tres cosas: default apagado (`None`/`False`), gobierna un
`if`, y de ese `if` cuelga un hallazgo. Los tres juntos significan *si no me pasás
esto, no reporto*.

Corriéndolo aparecieron **dos candidatos más, y los dos eran falsos positivos** —
mirarlos uno por uno es lo que hizo que el detector sirva en vez de ser ruido:

| candidato | por qué NO es la categoría |
|---|---|
| `backup_db.run_backup(db_path=None)` | se reasigna en la línea siguiente (`db_path or os.environ…`): el default nunca llega al `if`. Descartado **mecánicamente** por el detector. |
| `pg_type_audit.auditar(incluir_ok=False)` | lo que agrega esa rama son las columnas que están **bien**; los problemas se reportan siempre. Es verbosidad, no un nivel. Va a `PERMITIDOS` **con el motivo escrito**. |

Y lo que el detector **no** marca, a propósito: `revisar_secuencias=True` también
apaga un nivel, pero su default lo deja **prendido**. La regla no es "no se puede
apagar nada", es **"lo que se apaga solo, no vale"**.

**Verificado mutando cada defensa POR SEPARADO** (en este proyecto ya pasó que dos
se taparan entre sí y el test quedara decorativo):

| mutante | qué cae |
|---|---|
| la derivación de **tablas** vuelve a mirar el destino | caen los 2 tests de tablas, **el de columnas sigue verde** |
| la derivación de **columnas** vuelve a mirar el destino | cae el de columnas, **los de tablas siguen verdes** |
| el parámetro opcional vuelve (comportamiento viejo entero) | caen 7, incluida la guarda AST |
| el detector deja de ver los defaults apagados | cae la sonda plantada |
| el detector deja de exigir que el hallazgo cuelgue del `if` | cae la sonda plantada |

**Y probado sobre la forma REAL, no sólo sobre el mini-esquema de 4 tablas:**
`init_db()` + `ensure_tables()` (60 tablas) contra `schema_pg.sql` (58), con
`comparar()` llamada **sin pasarle nada** → `ok=False` y los hallazgos nombran
`fci_catalog` y `fci_prices`. Salió de yapa que las 58 tablas compartidas tienen
**0 columnas de diferencia** entre el SQLite real y el esquema de Postgres.

**Medición**: **44 casos, 0 se saltean** con `PG_DSN_VERIF` puesta (eran 30).
⚠️ **Una versión anterior decía 45 y estaba MAL NOMBRADO**: ese número salía de
correr `test_verificar_copia.py` **junto con** su detector
(`test_verificacion_no_es_opt_in.py`), o sea 39 + 6, y se reportó como "la
verificación". Es la falta de siempre —medir una cosa y nombrarla como otra— y la
encontró el dueño contando por afuera. Los números separados, hoy:
`test_verificar_copia.py` **44**, `test_verificacion_no_es_opt_in.py` **6**,
`test_esquema_pg_reaplicable.py` **6**, `test_relojes_del_conftest.py` **13**. Suite
completa en los dos motores: **46 y 46, el mismo set exacto test por test**, y el
mismo set que la baseline de `a813deb` — cero regresiones.

---

`backend/scripts/verificar_copia.py` + `tests/test_verificar_copia.py` (44 casos).
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
primer alta después de migrar choque contra un id existente) **no se ejercita en la
corrida normal**.

✅ **PERO EL SCRIPT LO TRAE PRENDIDO.** `verificar_copia.py` declara
`revisar_secuencias: bool = True` por defecto, así que **el que corra la
verificación de verdad revisa las secuencias sin tener que acordarse de nada**. El
`revisar_secuencias=False` es sólo de los 21 tests locales, porque corren contra
SQLite y ahí no hay secuencias. (Una versión anterior de esta sección se leía como
si el nivel 3 estuviera apagado en general: no lo está. Lo que falta es cobertura
del nivel en la suite, no el nivel en el script.)

Igual hay que correrlo a mano, y **antes de migrar de verdad hay que correrlo sí o
sí**:

```bash
PG_DSN_VERIF="postgresql://…/otra_base" python3 -m pytest tests/test_verificar_copia.py -q
```

Con la variable puesta: **44 pasan, 0 se saltean** (verificado). Sin ella: 37 pasan
y 7 se saltean.

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

# suite contra Postgres. NO debería dar ningún timeout: si aparece uno, es una
# regresión del aislamiento, no una falla de la app. El --timeout se deja puesto
# como alarma, y los relojes del conftest están calibrados para cortar ANTES que
# él: idle (6s) < lock (12s) < --timeout (20s). Ese orden lo valida el arranque
# de la suite, así que no se puede correr mal configurada.
cd mainwt/backend
DATABASE_URL="$(cat ../../pg_uri.txt)" python3 -m pytest tests -q --timeout=20

# para apretarlos en una máquina dedicada (CI), o aflojarlos en una cargada:
RENDI_TEST_IDLE_TX_S=3 RENDI_TEST_LOCK_S=7 python3 -m pytest tests -q --timeout=10

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
  real son ~250 mil filas.
  🔴 **DESACTUALIZADO — este párrafo decía "no migres la basura: vaciá `raw_json`",
  y esa decisión SE DIO VUELTA en la sesión 9: se migra todo** (ver el paso 5 del
  día del pasaje, línea ~1099, y el detalle en "El paso 4 NO es inocuo"). Vaciar
  apagaba CUATRO lectores, entre ellos `flujos.py:candidatos()` — con la columna
  vacía, **todo flujo ambiguo quedaba indecidible para siempre, sin dar un error**
  (línea ~1542). Se deja el párrafo con la corrección encima en vez de borrarlo,
  porque la idea es tentadora y va a volver a proponerse sola: el costo real de
  migrarlas ya está medido (28 de 34 segundos de CPU, línea ~1992) y es barato.
  Si algún día se retoma, la única forma segura es **`UPDATE` acotado a
  `status='confirmed'`, nunca `DELETE` la fila** (cascadea y se lleva su fila del
  ledger normalizado) y **nunca a un batch en `preview`** (lo convierte en una
  confirmación vacía y silenciosa) — y exceptuando las filas `status='invalid'`,
  que son la cola de casos del agente reconstructor.
- Los tres dueños del lock ya arreglados en `main`: el reset (por tandas), el
  `import_confirm` (transacción de 177→56 líneas) y los precios (1 escritura por
  minuto en vez de 1 por visita). Cada uno con test estructural que impide que
  vuelvan.
