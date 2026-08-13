# Migración SQLite → Postgres (Supabase) — estado y prompt de continuación

Sesión del 2026-08-13. Pegá el bloque de abajo en una sesión nueva.

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

Rama **`spike/postgres`**, commit `6020812`. **NO se deploya** — es un spike.
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
- **Medición**: **77,4%** (2.231 de 2.883), commit `36a2974`. Medida sobre la suite
  COMPLETA. Los números viejos de este doc (88%, después 74%) eran muestras
  parciales; la corrida entera daba 68,8% antes de la sesión del 13/08 a la tarde.

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

| Qué | Sitios | Estado |
|---|---|---|
| `sqlite3.<X>Error` → excepciones del shim | 21 | pendiente |
| `sqlite3.connect` → `get_db()` | 16 | pendiente |
| `INSERT OR REPLACE` → `ON CONFLICT` explícito | 9 | pendiente (avisa solo) |
| Placeholders con nombre `:user_id` | ~12 fallas | **NO estaba en los 80** |
| `rowid` → la clave primaria | 3 | pendiente (avisa solo) |
| `PRAGMA` varios | 16 | mayoría inerte: `get_db()` corta antes |

⚠️ **El plan original de 80 sitios subestimaba.** Ya aparecieron 4 categorías que no
estaban contadas: fechas con modificador (15), `MIN`/`MAX` de dos argumentos (2),
placeholders con nombre (~12 fallas) y fechas mal formadas (3). No es más difícil;
es más largo. Asumir que la lista está completa es el error a evitar.

## Los 472 timeouts NO son de la app

**Causa raíz encontrada y verificada con un experimento.** `tests/conftest.py` aísla
cada módulo con `DROP SCHEMA public CASCADE`. Con SQLite cada módulo tenía su propio
ARCHIVO; con Postgres los 58 comparten UNA base, y el `DROP SCHEMA` **se cuelga
indefinidamente** si un test anterior dejó una conexión abierta. Medido: se colgó 8s
y murió por timeout. Con `--timeout=10`, eso es exactamente un `Failed: Timeout`.

Mientras esto no se arregle, **el porcentaje miente**: mezcla "código roto" con "base
trabada". Es la brújula de todo lo demás y está desviada.

## Orden sugerido

1. **Arreglar el aislamiento de tests** (un esquema o una base por módulo, en vez de
   `DROP SCHEMA` sobre una compartida). Es lo que más mueve el número de una sola vez
   y lo que hace que las mediciones siguientes signifiquen algo.
2. Los sitios que quedan en la tabla de arriba.
3. **Copiador de datos** SQLite→Postgres. Verificación obligatoria: filas por tabla
   **y** totales de plata por usuario (invertido, P&L, efectivo). Contar filas no
   detecta un número mal convertido.
4. **Probar contra Supabase de verdad.** Todo lo medido hasta acá es Postgres local,
   sin red de por medio. Ahí se nota lo que hace demasiadas idas y vueltas — como el
   `_table_cols()` que en esta sesión hubo que cachear.
5. **`.env`** con los nombres de variable y `.gitignore`. Los valores los pone el
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

# suite contra Postgres  (--timeout es obligatorio: hay tests que cuelgan)
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
