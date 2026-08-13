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
_RE_INSERT_IGNORE = re.compile(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", re.I)
_RE_INSERT_REPLACE = re.compile(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", re.I)
_RE_ROWID = re.compile(r"\browid\b", re.I)
_RE_INSERT_TABLA = re.compile(r"INSERT\s+INTO\s+(\"?[A-Za-z_][\w]*\"?)", re.I)
_AHORA_TXT = "to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')"
_HOY_TXT = "to_char(now() at time zone 'utc', 'YYYY-MM-DD')"

# PK por tabla, leída del catálogo una vez por proceso (para emular lastrowid).
_PKS_CACHE: dict = {}


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
    sql = _RE_DATETIME_NOW.sub(_AHORA_TXT, sql)
    sql = _RE_DATE_NOW.sub(_HOY_TXT, sql)
    sql = _RE_IFNULL.sub("COALESCE(", sql)

    # INSERT OR IGNORE → INSERT … ON CONFLICT DO NOTHING. El DO NOTHING va al
    # final, después de los VALUES, y sólo si la query no traía ya un ON CONFLICT.
    if _RE_INSERT_IGNORE.search(sql):
        sql = _RE_INSERT_IGNORE.sub("INSERT INTO", sql)
        if "ON CONFLICT" not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"

    return _escapar_y_placeholders(sql)


def _normalizar_params(params):
    """bool → 1/0. Las columnas 0/1 quedaron smallint a propósito (el código
    compara `=1`), y psycopg mandaría un boolean que Postgres rechaza."""
    if params is None:
        return ()
    if isinstance(params, dict):
        return {k: (int(v) if isinstance(v, bool) else v) for k, v in params.items()}
    return tuple(int(v) if isinstance(v, bool) else v for v in params)


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

    def execute(self, sql, params=()):
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
