# Migración SQLite → Postgres (Supabase) — estado y prompt de continuación

Última sesión: 2026-08-14 (madrugada). Pegá el bloque de abajo en una sesión nueva.

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

Rama **`spike/postgres`**, commit `18fa17f`. **NO se deploya** — es un spike.
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
- **Medición**: **98,0%** (2.790 de 2.847), commit `18fa17f`. Suite COMPLETA en
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

**Quedan 57 fallas — pero 46 de ellas fallan IGUAL en SQLite.** Son las
preexistentes de siempre, no son de la migración. **Lo propio de Postgres son 11**,
y son TODAS el mismo ítem: **`Connection.backup`**, el ensayo por clon. Está
diseñado (ver abajo) y esperando que el dueño elija camino.

⚠️ **Comparar SIEMPRE contra la baseline de SQLite antes de llamar "nueva" a una
falla.** El total de Postgres arrastra las 46 preexistentes y da una sensación de
deuda que no existe: 57 suena mucho, 11 es lo que hay.

### `Connection.backup`: DISEÑADO, sin implementar — falta que el dueño elija

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
3. ⚠️ **El botón por defecto ("Simular", `safe_only=true`) usa el clon como
   PIZARRÓN, no como garantía**: `safe_backfill` calcula el estado ideal en la
   copia y después **escribe en la base real en la misma llamada**
   (`_apply_safe` → `real_conn.commit()`, `:571`). El clon está adentro del camino
   de APLICAR. Es el modo que ya corrió en producción sobre 830 cuentas.

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
`:512`) y **no hay ningún tope de cordura en todo el archivo**. Si la copia queda
vacía o incompleta, `_classify_safe` lee "esto tenía cantidad y ahora es cero", lo
marca como fantasma y `_apply_safe` **borra la fila real**. Lo que ve el usuario:
abre la app y no están sus acciones. Recuperable sólo desde backup.

Eso, más que el botón por defecto simule y escriba en la misma llamada, **es el
riesgo más grande y el más barato de arreglar**: partir `safe_backfill` en dos
caminos (uno que sólo lee y reporta, otro que aplica) y poner un piso del tipo "no
borres más del X% de las posiciones de la tanda". **Vale más que cualquiera de las
tres opciones y no depende de la migración.**

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

## Hallazgo para el punto 4 (Supabase): ~36 conexiones sin proteger

⚠️ **Corrección de una versión anterior de este doc, que decía "277 conexiones sin
cerrar".** Ese número era cierto pero engañoso: contaba que no hay ningún `with`, y
`with` no es la única forma de cerrar. Medido de nuevo sobre el AST, no con grep:

| | sitios | |
|---|---|---|
| `conn = get_db()` en código de app | 277 | |
| …que cierran con `try/finally` | **233 (84%)** | hace lo mismo que un `with`, escrito distinto |
| …expuestos (el `close()` se saltea si salta una excepción) | 44 | |
| …de esos, en scripts de dev/one-off | 8 | no los ve un usuario |
| **…en código servido a usuarios (todos en `main.py`)** | **36** | esto es lo que hay que arreglar |

Por qué importa igual: cuando uno de esos 36 se salta el `close()`, en SQLite casi no
se nota; en Postgres la conexión queda **`idle in transaction`** reteniendo los locks
de todo lo que tocó. **Es exactamente la misma traba que tiró la app el 12 y el 13/08**,
y es el mismo mecanismo que colgaba la suite de tests.

En local hay 100 conexiones de margen. **Supabase da bastante menos.** Conviene
arreglarlo ANTES de ir a Supabase — pero es una tarea chica y acotada (36 sitios en un
archivo), no el riesgo grande que sugería el número viejo. La forma prolija es que
`get_db()` sea un context manager; la barata es envolver esos 36 en `try/finally`.

Nota: los relojes (`lock_timeout`, `idle_in_transaction_session_timeout`) que tapan
esto en la suite son **de TESTS**, están en `conftest.py`. En producción no hay nada
equivalente puesto.

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
5. **Copiador de datos** SQLite→Postgres. Verificación obligatoria: filas por tabla
   **y** totales de plata por usuario (invertido, P&L, efectivo). Contar filas no
   detecta un número mal convertido.
6. **Los 36 `get_db()` expuestos** (ver la sección de más arriba). Va ACÁ y no
   después: es la misma traba que tiró la app el 12 y 13/08, y Supabase da mucho
   menos margen de conexiones que los 100 del Postgres local.
7. **Probar contra Supabase de verdad.** Todo lo medido hasta acá es Postgres local,
   sin red de por medio. Ahí se nota lo que hace demasiadas idas y vueltas — como el
   `_table_cols()` que hubo que cachear.
8. **`.env`** con los nombres de variable y `.gitignore`. Los valores los pone el
   dueño: no manejes contraseñas en texto plano.

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
