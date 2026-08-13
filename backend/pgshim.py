"""Capa que hace que el código de Rendi hable Postgres sin reescribir sus queries.

POR QUÉ ESTO Y NO UNA REESCRITURA. El backend tiene 3.293 placeholders `?` en
~1.400 llamadas con SQL crudo y CERO ORM. Reescribirlas a mano es semanas de
trabajo mecánico sobre una app donde una diferencia sutil cambia el P&L de
alguien. Pero la mayoría de ese SQL YA es válido en Postgres: lo que rompe es una
lista corta y enumerable. Esta capa la traduce en un solo lugar, y así el 90% del
código no se toca.

Lo que emula de `sqlite3`:
  conn.execute(sql, params) → cursor con fetchone/fetchall/lastrowid/rowcount
  conn.executemany / executescript / commit / rollback / close
  `with conn:`               → commit al salir bien, rollback si hubo excepción
  row["col"] Y row[0]        → sqlite3.Row permite las dos, y el código usa ambas
  dict(row), row.keys()

Lo que traduce:
  ?                    → %s      (respetando los ? adentro de strings)
  %                    → %%      (psycopg usa % para bindear: un LIKE '%@x' sin
                                  escapar revienta o, peor, matchea mal)
  lastrowid            → RETURNING de la PK
  INSERT OR IGNORE     → ON CONFLICT DO NOTHING
  strftime('%Y', col)  → substr(col,1,4)   (las fechas están guardadas 'YYYY-MM-DD'
  strftime('%m', col)  → substr(col,6,2)    como TEXTO, así que cortar el string es
                                            EXACTAMENTE equivalente y no depende de
                                            que Postgres parsee la fecha)
  datetime('now')      → to_char(now() at time zone 'utc', …)  (devuelve TEXTO, con
                                            el mismo formato que venía guardando
                                            SQLite: si devolviera timestamptz, las
                                            comparaciones de string del código
                                            dejarían de funcionar en silencio)
  IFNULL               → COALESCE
  True/False en params → 1/0     (las columnas 0/1 quedaron smallint a propósito;
                                  psycopg mandaría boolean y Postgres lo rechaza)

Lo que NO traduce, a propósito:
  · INSERT OR REPLACE (24 sitios). Necesita saber por QUÉ columna hay conflicto y
    eso no se puede adivinar sin leer el índice único de cada tabla. Se convierten
    a mano, uno por uno, con su ON CONFLICT explícito.
  · rowid (3 sitios). No existe en Postgres. Se cambian por la PK.
  Ambos se detectan y LEVANTAN un error claro en vez de fallar raro.
"""
import re

import psycopg

# Los mismos nombres de excepción que el código ya captura en ~21 lugares.
OperationalError = psycopg.OperationalError
IntegrityError = psycopg.IntegrityError
DatabaseError = psycopg.DatabaseError
Error = psycopg.Error


class Row:
    """Igual que `sqlite3.Row`: se accede por nombre Y por posición.

    El código usa las dos formas —`r["email"]` y `r[0]`— muchas veces en el mismo
    archivo, así que devolver sólo un dict rompería la mitad de las lecturas.
    """
    __slots__ = ("_c", "_v")

    def __init__(self, cols, valores):
        self._c = cols
        self._v = valores

    def __getitem__(self, k):
        if isinstance(k, int):
            return self._v[k]
        try:
            return self._v[self._c.index(k)]
        except ValueError:
            raise IndexError(f"no existe la columna {k!r}") from None

    def __contains__(self, k):
        return k in self._c

    def keys(self):
        return list(self._c)

    def __iter__(self):
        return iter(self._v)

    def __len__(self):
        return len(self._v)

    def __repr__(self):
        return f"<Row {dict(zip(self._c, self._v))}>"


_RE_STRFTIME_Y = re.compile(r"strftime\(\s*'%Y'\s*,\s*([^)]+?)\s*\)", re.I)
_RE_STRFTIME_M = re.compile(r"strftime\(\s*'%m'\s*,\s*([^)]+?)\s*\)", re.I)
_RE_STRFTIME_YM = re.compile(r"strftime\(\s*'%Y-%m'\s*,\s*([^)]+?)\s*\)", re.I)
_RE_DATETIME_NOW = re.compile(r"datetime\(\s*'now'\s*\)", re.I)
_RE_DATE_NOW = re.compile(r"\bdate\(\s*'now'\s*\)", re.I)
_RE_IFNULL = re.compile(r"\bIFNULL\s*\(", re.I)

# ── Fechas con modificadores: date(x, '-7 days') ─────────────────────────────
# LA CATEGORÍA QUE MÁS CALLADA FALLA. `datetime('now')` (un argumento) ya se
# traducía; `datetime('now', '-7 days')` NO, y Postgres la rechaza con
# "function datetime(unknown, unknown) does not exist". Como varios de los sitios
# que la usan están adentro de un `try/except Exception`, el error se traga y la
# función devuelve un DEFAULT en vez de romper: el usuario ve un número
# equivocado, no un error. En la corrida completa esto explicaba 146 fallas.
#
# Se traducen SÓLO las formas que existen hoy en el código y se verificaron
# contra SQLite corriendo las dos bases y comparando. Cualquier otra forma
# LEVANTA un error explícito: es preferible a adivinar mal en silencio.
# La base admite UN nivel de paréntesis: `date(MIN(date), '+7 days')` existe
# (ai/quota.py:250, el "cuándo se te resetea la cuota de IA"). Sin esto el
# paréntesis del MIN cortaba el match y la expresión llegaba cruda a Postgres.
#
# Los modificadores son OPCIONALES: `date(columna)` sin modificador también hay
# que traducirlo. Postgres lo acepta —no rompe— pero devuelve un objeto `date` en
# vez del texto 'YYYY-MM-DD' que devolvía SQLite, y ese valor a veces sale
# derecho al usuario. Es de las diferencias que no avisan.
_RE_FECHA_MOD = re.compile(
    r"\b(date|datetime)\s*\(\s*((?:[^,()]|\([^()]*\))+?)\s*"
    r"((?:,\s*(?:'[^']*'|\?|%s)\s*)*)\)", re.I)
_RE_MOD_INTERVALO = re.compile(
    r"^([+-]?\d+)\s+(day|days|hour|hours|minute|minutes|second|seconds|"
    r"month|months|year|years)$", re.I)


def _traducir_fecha(m: re.Match) -> str:
    """`date(base, mod, mod, …)` de SQLite → la expresión equivalente en Postgres.

    Devuelve TEXTO en el mismo formato que venía guardando SQLite ('YYYY-MM-DD' o
    'YYYY-MM-DD HH:MM:SS'). Eso NO es un detalle: las columnas de fecha son `text`
    y el código las compara y ordena como strings. Si esto devolviera un timestamp
    de Postgres, las comparaciones seguirían "funcionando" pero con otro criterio.
    """
    fn, base, mods_txt = m.group(1).lower(), m.group(2).strip(), m.group(3)
    es_ahora = base.lower() in ("'now'", "now")

    # `date('now')` y `datetime('now')` sin modificadores ya los traducen las dos
    # reglas de abajo, que están puestas y testeadas desde antes. Las dejamos
    # pasar para no cambiar algo que ya funciona.
    if es_ahora and not mods_txt.strip():
        return m.group(0)

    expr = "(now() at time zone 'utc')" if es_ahora else f"({base})::timestamp"

    for mod in re.findall(r"'[^']*'|\?|%s", mods_txt):
        if mod in ("?", "%s"):
            # El modificador llega como dato (ej: "-7 days", "+30 days"). Se
            # verificó que en TODOS los sitios es de la forma '±N unidad', que
            # Postgres entiende como intervalo tal cual.
            expr = f"({expr} + ({mod})::interval)"
            continue
        val = mod.strip("'").strip()
        bajo = val.lower()
        if bajo.startswith("start of "):
            unidad = bajo[len("start of "):].strip()
            if unidad not in ("month", "year", "day"):
                raise NotImplementedError(
                    f"modificador de fecha no soportado: 'start of {unidad}'. "
                    "Agregalo a _traducir_fecha con su test.")
            expr = f"date_trunc('{unidad}', {expr})"
            continue
        mi = _RE_MOD_INTERVALO.match(val)
        if not mi:
            raise NotImplementedError(
                f"modificador de fecha no soportado: {val!r}. SQLite acepta muchas "
                "formas y traducirlas a ojo es justo como se cambia un número sin "
                "que nadie se entere. Agregalo a _traducir_fecha con su test.")
        signo, unidad = mi.group(1), mi.group(2).lower().rstrip("s")
        # En SQLite '5 days' sin signo es +5.
        if not signo.startswith(("+", "-")):
            signo = "+" + signo
        expr = f"({expr} + interval '{signo} {unidad}')"

    fmt = "YYYY-MM-DD" if fn == "date" else "YYYY-MM-DD HH24:MI:SS"
    if fn == "date":
        expr = f"({expr})::date"
    return f"to_char({expr}, '{fmt}')"
_RE_INSERT_IGNORE = re.compile(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", re.I)
_RE_INSERT_REPLACE = re.compile(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", re.I)
_RE_ROWID = re.compile(r"\browid\b", re.I)
_RE_INSERT_TABLA = re.compile(r"INSERT\s+INTO\s+(\"?[A-Za-z_][\w]*\"?)", re.I)
_AHORA_TXT = "to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')"
_HOY_TXT = "to_char(now() at time zone 'utc', 'YYYY-MM-DD')"

# ── El catálogo: PRAGMA table_info y sqlite_master ───────────────────────────
# Las dos son de SQLite y no existen en Postgres, pero el equivalente devuelve LO
# MISMO si se le da la forma exacta que el código ya espera. Se traducen acá y no
# en los 15 sitios que las usan: los 9 de main.py están repartidos en un archivo
# de 17.800 líneas, y se revisó uno por uno que ninguno necesite más que el
# NOMBRE de la columna (todos hacen `r[1]` o `c["name"]`).
#
# El único que sí lee el tipo es scripts/pg_type_audit.py, que corre contra la
# SQLite de producción a propósito: ese no pasa por acá.
_RE_PRAGMA_TABLE_INFO = re.compile(
    r"^\s*PRAGMA\s+table_info\s*\(\s*[\"']?([A-Za-z_]\w*)[\"']?\s*\)\s*;?\s*$", re.I)
_RE_FROM_SQLITE_MASTER = re.compile(r"\bFROM\s+sqlite_master\b", re.I)

# Mismas columnas, mismo orden y mismos nombres que devuelve SQLite:
#   cid | name | type | notnull | dflt_value | pk
# Importa que sean iguales porque el código las lee de las dos formas —por
# posición y por nombre— a veces en el mismo archivo.
#
# Se lee de `pg_attribute` y NO de `information_schema.columns`. Las dos dan el
# mismo resultado, pero information_schema es una vista con muchos joins y
# `_table_cols()` se llama ~20 veces por request: contra una base remota esa
# diferencia se paga en cada carga de página.
#
# Una tabla que no existe devuelve CERO FILAS, no un error — igual que SQLite.
# main.py:1466 (`if _ac_cols and 'phone' not in _ac_cols`) depende de eso.
_TABLE_INFO_SQL = """SELECT (row_number() OVER (ORDER BY a.attnum) - 1)::int   AS cid,
       a.attname::text                                             AS name,
       format_type(a.atttypid, a.atttypmod)                        AS type,
       (CASE WHEN a.attnotnull THEN 1 ELSE 0 END)::int             AS notnull,
       pg_get_expr(d.adbin, d.adrelid)                             AS dflt_value,
       (CASE WHEN a.attnum = ANY(i.indkey) THEN 1 ELSE 0 END)::int AS pk
  FROM pg_attribute a
  JOIN pg_class c        ON c.oid = a.attrelid
  JOIN pg_namespace n    ON n.oid = c.relnamespace
  LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
  LEFT JOIN pg_index i   ON i.indrelid = c.oid AND i.indisprimary
 WHERE n.nspname = 'public' AND c.relname = '{tabla}'
   AND a.attnum > 0 AND NOT a.attisdropped
 ORDER BY a.attnum"""

# Los 5 sitios que usan sqlite_master piden `name` filtrando por `type='table'`.
# Va como subconsulta y no como una vista en el esquema, para que la base de
# producción no quede con una tabla de compatibilidad adentro.
#
# OJO: la columna `sql` (el DDL de la tabla) queda en NULL — Postgres no tiene un
# equivalente directo. Hoy no la usa nadie; si alguien la usa mañana va a ver
# NULL, que es visible, y no un valor equivocado, que no lo es.
_SQLITE_MASTER_SQL = """FROM (
  SELECT tablename::text AS name, 'table'::text AS type,
         tablename::text AS tbl_name, NULL::text AS sql
    FROM pg_tables  WHERE schemaname = 'public'
  UNION ALL
  SELECT indexname::text, 'index'::text, tablename::text, NULL::text
    FROM pg_indexes WHERE schemaname = 'public'
  UNION ALL
  SELECT viewname::text, 'view'::text, viewname::text, NULL::text
    FROM pg_views   WHERE schemaname = 'public'
) AS sqlite_master"""

# PK por tabla, leída del catálogo una vez por proceso (para emular lastrowid).
_PKS_CACHE: dict = {}

# Columnas por tabla. En SQLite `PRAGMA table_info` es instantáneo (lee memoria);
# acá es una consulta de verdad, y `_table_cols()` se llama ~20 veces por request.
# Sin este caché son ~20 viajes a la base en cada carga de página —y contra una
# base remota eso se siente. Medido: sin caché la suite pasó de 546 a 816
# timeouts.
#
# Se invalida sola cuando pasa un DDL (ver `_MUTA_ESQUEMA`): las migraciones de
# init_db() miran las columnas, hacen ALTER y vuelven a mirar, así que un caché
# que no se entera del ALTER haría que la migración se saltee una columna.
_COLS_CACHE: dict = {}
_RE_DDL = re.compile(r"\b(ALTER|CREATE|DROP)\s+(TABLE|VIEW)\b", re.I)


def _escapar_y_placeholders(sql: str) -> str:
    """`?` → `%s` y `%` → `%%`, sin tocar el contenido de los strings SQL.

    Las dos cosas van juntas y en un solo recorrido porque el orden importa: si
    primero se reemplazan los `?` por `%s` y después se escapan los `%`, se
    rompen los placeholders recién puestos.

    Los strings del SQL se respetan enteros. Hay queries con `LIKE '%@rendi.test'`
    (el `%` es del patrón, no un placeholder) y textos con signos de pregunta.
    """
    salida = []
    en_string = False
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if en_string:
            salida.append(ch)
            if ch == "'":
                # '' adentro de un string es una comilla escapada, no el cierre
                if i + 1 < n and sql[i + 1] == "'":
                    salida.append("'")
                    i += 2
                    continue
                en_string = False
            elif ch == "%":
                salida[-1] = "%%"      # el % del LIKE también hay que escaparlo
            i += 1
            continue
        if ch == "'":
            en_string = True
            salida.append(ch)
        elif ch == "?":
            salida.append("%s")
        elif ch == "%":
            salida.append("%%")
        else:
            salida.append(ch)
        i += 1
    return "".join(salida)


def traducir(sql: str) -> str:
    """SQL de SQLite → SQL de Postgres. Pura, sin estado: fácil de testear."""
    # PRAGMA table_info reemplaza la sentencia ENTERA, así que va antes que todo.
    # El regex sólo acepta un identificador adentro del paréntesis, así que el
    # nombre no puede traer comillas ni colarse en el SQL como otra cosa.
    m = _RE_PRAGMA_TABLE_INFO.match(sql)
    if m:
        return _TABLE_INFO_SQL.format(tabla=m.group(1))

    # `sub` con lambda y no con string: el texto de reemplazo tiene barras y
    # `re.sub` las interpretaría como grupos.
    sql = _RE_FROM_SQLITE_MASTER.sub(lambda _m: _SQLITE_MASTER_SQL, sql)

    if _RE_INSERT_REPLACE.search(sql):
        raise NotImplementedError(
            "INSERT OR REPLACE no se traduce solo: hay que decir por qué columna "
            "hay conflicto (ON CONFLICT (...) DO UPDATE). Convertí esta query a "
            "mano.\n  " + " ".join(sql.split())[:160])
    if _RE_ROWID.search(sql):
        raise NotImplementedError(
            "`rowid` no existe en Postgres. Usá la clave primaria de la tabla.\n  "
            + " ".join(sql.split())[:160])

    # Las fechas viven como TEXTO 'YYYY-MM-DD'. Cortar el string es exactamente
    # lo que hacía strftime sobre ese formato, y no depende de que Postgres
    # sepa parsear la columna (que es text, no date).
    sql = _RE_STRFTIME_YM.sub(r"substr(\1, 1, 7)", sql)
    sql = _RE_STRFTIME_Y.sub(r"substr(\1, 1, 4)", sql)
    sql = _RE_STRFTIME_M.sub(r"substr(\1, 6, 2)", sql)
    # Las de VARIOS argumentos primero: las de uno solo (abajo) no las matchean,
    # pero dejarlas después haría que el orden importe por accidente.
    sql = _RE_FECHA_MOD.sub(_traducir_fecha, sql)
    sql = _RE_DATETIME_NOW.sub(_AHORA_TXT, sql)
    sql = _RE_DATE_NOW.sub(_HOY_TXT, sql)
    sql = _RE_IFNULL.sub("COALESCE(", sql)
    sql = _traducir_minmax(sql)

    # INSERT OR IGNORE → INSERT … ON CONFLICT DO NOTHING. El DO NOTHING va al
    # final, después de los VALUES, y sólo si la query no traía ya un ON CONFLICT.
    if _RE_INSERT_IGNORE.search(sql):
        sql = _RE_INSERT_IGNORE.sub("INSERT INTO", sql)
        if "ON CONFLICT" not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"

    return _escapar_y_placeholders(sql)


_RE_MINMAX = re.compile(r"\b(MIN|MAX)\s*\(", re.I)


def _posiciones_en_string(sql: str) -> list:
    """Marca qué posiciones del SQL caen adentro de un literal de texto."""
    dentro, res, i, n = False, [False] * len(sql), 0, len(sql)
    while i < n:
        if sql[i] == "'":
            if dentro and i + 1 < n and sql[i + 1] == "'":
                res[i] = res[i + 1] = True
                i += 2
                continue
            dentro = not dentro
            res[i] = True
        else:
            res[i] = dentro
        i += 1
    return res


def _traducir_minmax(sql: str) -> str:
    """`MIN(a,b)`/`MAX(a,b)` de SQLite → `LEAST`/`GREATEST` de Postgres.

    En Postgres MIN y MAX son AGREGADOS de un solo argumento: `MAX(0, x-1)` no da
    otro resultado, directamente no existe. Son 2 sitios —el "nunca por debajo de
    cero" del contador de chat (ai/quota.py:401) y el registro de backfill de
    precios (price_history.py:143)— y los dos rompen de entrada.

    No se puede arreglar en el código: SQLite no tiene LEAST/GREATEST, y durante
    la migración el mismo código tiene que andar en los dos motores.

    Se cuentan paréntesis en vez de usar un regex a secas: `MIN(COALESCE(a,0))`
    tiene una coma pero es UN argumento —un agregado legítimo— y confundirlo
    cambiaría el resultado de una consulta en silencio.
    """
    if not _RE_MINMAX.search(sql):
        return sql
    marca = _posiciones_en_string(sql)
    salida, i = [], 0
    while True:
        m = _RE_MINMAX.search(sql, i)
        if not m:
            salida.append(sql[i:])
            break
        if marca[m.start()]:              # está adentro de un texto: no se toca
            salida.append(sql[i:m.end()])
            i = m.end()
            continue
        j, prof, comas, en_str = m.end(), 1, 0, False
        while j < len(sql) and prof:
            ch = sql[j]
            if en_str:
                en_str = ch != "'"
            elif ch == "'":
                en_str = True
            elif ch == "(":
                prof += 1
            elif ch == ")":
                prof -= 1
            elif ch == "," and prof == 1:
                comas += 1
            j += 1
        salida.append(sql[i:m.start()])
        nuevo = ("LEAST(" if m.group(1).upper() == "MIN" else "GREATEST(")
        salida.append((nuevo if comas else sql[m.start():m.end()]) + sql[m.end():j])
        i = j
    return "".join(salida)


def _normalizar_params(params):
    """bool → 1/0. Las columnas 0/1 quedaron smallint a propósito (el código
    compara `=1`), y psycopg mandaría un boolean que Postgres rechaza."""
    if params is None:
        return ()
    if isinstance(params, dict):
        return {k: (int(v) if isinstance(v, bool) else v) for k, v in params.items()}
    return tuple(int(v) if isinstance(v, bool) else v for v in params)


class CursorCacheado:
    """Un cursor sobre filas que ya tenemos en memoria (las del caché de columnas).

    Se comporta como el `Cursor` de abajo para lo único que el código hace con el
    resultado de `PRAGMA table_info`: recorrerlo y leer `r[1]` o `r["name"]`.
    """
    __slots__ = ("_filas", "_i", "lastrowid")

    def __init__(self, filas):
        self._filas = filas
        self._i = 0
        self.lastrowid = None

    rowcount = property(lambda self: len(self._filas))
    description = None

    def fetchone(self):
        if self._i >= len(self._filas):
            return None
        self._i += 1
        return self._filas[self._i - 1]

    def fetchall(self):
        resto = self._filas[self._i:]
        self._i = len(self._filas)
        return resto

    def fetchmany(self, size=None):
        n = len(self._filas) if size is None else size
        resto = self._filas[self._i:self._i + n]
        self._i += len(resto)
        return resto

    def __iter__(self):
        return iter(self.fetchall())

    def close(self):
        pass


class Cursor:
    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def _fila(self, t):
        if t is None:
            return None
        return Row([d.name for d in self._cur.description], t)

    def fetchone(self):
        if self._cur.description is None:
            return None
        return self._fila(self._cur.fetchone())

    def fetchall(self):
        if self._cur.description is None:
            return []
        cols = [d.name for d in self._cur.description]
        return [Row(cols, t) for t in self._cur.fetchall()]

    def fetchmany(self, size=None):
        cols = [d.name for d in self._cur.description]
        return [Row(cols, t) for t in self._cur.fetchmany(size)]

    def __iter__(self):
        return iter(self.fetchall())

    def close(self):
        self._cur.close()


class Connection:
    """Emula la conexión de sqlite3 sobre psycopg."""

    def __init__(self, dsn: str):
        # autocommit=False + commit/rollback explícitos = lo mismo que hace
        # sqlite3 con isolation_level=''.
        # Sin row_factory: el default de psycopg ya devuelve tuplas, y las
        # envolvemos nosotros en `Row` para poder leer por nombre Y por posición.
        self._c = psycopg.connect(dsn, autocommit=False)
        self.row_factory = None      # el código lo setea; acá siempre devolvemos Row

    # ── API de sqlite3 ────────────────────────────────────────────────────────
    def _pk_de(self, tabla: str):
        """Columna PK de una tabla, para poder emular `lastrowid`.

        Se lee del catálogo UNA vez por proceso. `lastrowid` se usa en 38 lugares
        —casi siempre para devolver el id del alta recién hecha— y en Postgres el
        equivalente es RETURNING, que necesita saber el nombre de la columna.
        """
        if _PKS_CACHE.get("__cargado__") is None:
            with self._c.cursor() as c:
                c.execute("""
                    SELECT c.relname, a.attname
                      FROM pg_index i
                      JOIN pg_class c ON c.oid = i.indrelid
                      JOIN pg_namespace n ON n.oid = c.relnamespace
                      JOIN pg_attribute a ON a.attrelid = c.oid
                                         AND a.attnum = ANY(i.indkey)
                     WHERE i.indisprimary AND n.nspname = 'public'
                """)
                for t, col in c.fetchall():
                    _PKS_CACHE.setdefault(t, col)
            _PKS_CACHE["__cargado__"] = True
            self._c.rollback()      # el SELECT abrió transacción; no la dejamos colgada
        return _PKS_CACHE.get(tabla.lower())

    def _cols_de(self, tabla: str):
        """Las columnas de una tabla, del caché. Ver `_COLS_CACHE`."""
        clave = tabla.lower()
        if clave not in _COLS_CACHE:
            with self._c.cursor() as c:
                c.execute(_TABLE_INFO_SQL.format(tabla=clave))
                cols = [d.name for d in c.description]
                _COLS_CACHE[clave] = [Row(cols, t) for t in c.fetchall()]
        return _COLS_CACHE[clave]

    def execute(self, sql, params=()):
        # `PRAGMA table_info` se sirve del caché: es la consulta más repetida de
        # todas y la única que se puede cachear sin riesgo (el esquema no cambia
        # salvo por un DDL, y el DDL invalida).
        m = _RE_PRAGMA_TABLE_INFO.match(sql)
        if m:
            return CursorCacheado(self._cols_de(m.group(1)))
        if _RE_DDL.search(sql):
            _COLS_CACHE.clear()

        q = traducir(sql)
        p = _normalizar_params(params)
        cur = self._c.cursor()

        m = _RE_INSERT_TABLA.match(q.lstrip())
        if m and "RETURNING" not in q.upper():
            pk = self._pk_de(m.group(1).strip('"'))
            if pk:
                cur.execute(f'{q} RETURNING "{pk}"', p)
                fila = cur.fetchone()
                return Cursor(cur, fila[0] if fila else None)

        cur.execute(q, p)
        return Cursor(cur)

    def executemany(self, sql, seq):
        q = traducir(sql)
        cur = self._c.cursor()
        cur.executemany(q, [_normalizar_params(p) for p in seq])
        return Cursor(cur)

    def executescript(self, sql):
        """Cada sentencia por separado: psycopg no acepta multi-statement con
        parámetros, y además así un fallo dice CUÁL sentencia falló."""
        if _RE_DDL.search(sql):
            _COLS_CACHE.clear()      # casi todo executescript es DDL de migración
        cur = self._c.cursor()
        for s in [x.strip() for x in sql.split(";") if x.strip()]:
            cur.execute(traducir(s))
        return Cursor(cur)

    def cursor(self):
        return Cursor(self._c.cursor())

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        try:
            self._c.close()
        except Exception:
            pass

    # `with conn:` — commit si salió bien, rollback si hubo excepción. Igual que
    # sqlite3, y es de lo que depende la atomicidad en todo el código.
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._c.commit()
        else:
            self._c.rollback()
        return False


def connect(dsn: str) -> Connection:
    return Connection(dsn)
