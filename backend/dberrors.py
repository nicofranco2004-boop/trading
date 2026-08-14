"""Los errores de base que hay que capturar para que ANDE EN LOS DOS MOTORES.

EL PROBLEMA. El código tiene 21 lugares con `except sqlite3.IntegrityError` o
`except sqlite3.OperationalError`. Con Postgres esas excepciones NO SE LEVANTAN
NUNCA: el error viene de psycopg y pasa de largo por el `except`. El síntoma no es
"no anda": es que un 409 amable ("ese email ya está registrado") se convierte en un
500, o que un camino que sabía recuperarse deja de recuperarse.

Se resuelve capturando una TUPLA con los tipos de los dos motores. Una tupla y no
un `if USANDO_PG`, por dos motivos: el mismo `except` sirve durante toda la
migración sin bifurcar el código, y la suite corre contra los dos motores con las
mismas líneas.

⚠️ `psycopg` NO está en requirements.txt todavía —la migración es un spike—, así
que la importación va protegida. Sin psycopg instalado, esto queda exactamente
igual que antes y producción no se entera.

⚠️ LA EQUIVALENCIA NO ES UNO A UNO, y esa es la parte que se puede escribir mal:

    error                      SQLite                 psycopg
    -------------------------  ---------------------  ---------------------
    UNIQUE / FK violada        IntegrityError         IntegrityError      ✓ igual
    "no such table/column"     OperationalError       ProgrammingError    ✗ DISTINTO
    error de sintaxis SQL      OperationalError       ProgrammingError    ✗ DISTINTO
    base trabada / sin espacio OperationalError       OperationalError    ✓ igual

Por eso `ERR_OPERACIONAL` incluye también `ProgrammingError`: en SQLite esos casos
YA caían adentro del `except OperationalError`, así que sumarlo no ensancha lo que
se traga — lo deja igual que estaba. Sacarlo sí cambiaría el comportamiento: un
"no such column" que hoy se maneja pasaría a reventar sólo en Postgres.
"""
import sqlite3

try:
    import psycopg as _pg
except ImportError:                      # sin psycopg (producción hoy): SQLite solo
    ERR_INTEGRIDAD = (sqlite3.IntegrityError,)
    ERR_OPERACIONAL = (sqlite3.OperationalError,)
    ERR_BASE = (sqlite3.DatabaseError,)
else:
    ERR_INTEGRIDAD = (sqlite3.IntegrityError, _pg.IntegrityError)
    ERR_OPERACIONAL = (sqlite3.OperationalError,
                       _pg.OperationalError, _pg.ProgrammingError)
    ERR_BASE = (sqlite3.DatabaseError, _pg.DatabaseError)


# ── Los mensajes también cambian, y hay código que los lee ───────────────────
# Varios `except` no alcanzan con capturar: miran el TEXTO del error para decidir
# qué contestar. Ese texto es distinto en cada motor:
#     SQLite    "UNIQUE constraint failed: users.email"
#     Postgres  "duplicate key value violates unique constraint \"users_email_key\""
# Estos helpers preguntan por el HECHO en vez de por el texto.
def es_unique(ex) -> bool:
    """¿El error es 'esa fila ya existe'? (y no otra violación de integridad)."""
    t = str(ex).lower()
    return ("unique constraint failed" in t          # SQLite
            or "duplicate key value" in t            # Postgres
            or "unique constraint" in t)


def es_columna_duplicada(ex) -> bool:
    """¿El ALTER TABLE falló porque la columna YA ESTÁ?

    Lo usa una migración idempotente: se traga ese caso y deja aflorar cualquier
    otro. Si el texto no matchea, la migración deja de ser idempotente y el boot
    revienta — en Postgres, donde el mensaje es otro.
        SQLite    "duplicate column name: mep_venta"
        Postgres  "column \"mep_venta\" of relation \"fx_rates_daily\" already exists"
    """
    t = str(ex).lower()
    return "duplicate column" in t or ("already exists" in t and "column" in t)


def es_base_trabada(ex) -> bool:
    """¿Es el 'database is locked' de SQLite, o su equivalente en Postgres?

    En Postgres no hay un lock global de escritura —es justamente el motivo de la
    migración—, así que el equivalente más cercano es un timeout de lock de fila.
    """
    t = str(ex).lower()
    return ("database is locked" in t or "database is busy" in t   # SQLite
            or "lock timeout" in t or "deadlock detected" in t)    # Postgres


# ── El ensayo por clon: SÓLO SQLITE, a propósito ─────────────────────────────
# Tres herramientas de admin simulan de una forma muy particular: NO calculan qué
# pasaría, sino que clonan la base ENTERA a un archivo temporal con
# `sqlite3.Connection.backup()`, corren el proceso de verdad sobre la copia y
# comparan la foto de antes contra la de después.
#
# En Postgres esa fotocopia no existe, y no hay reemplazo de una línea: la copia
# está adentro del camino de aplicar, no sólo del de simular.
#
# DECISIÓN TOMADA (sesión 6): no se migra ahora. Son herramientas de admin, no
# están en el camino de ningún usuario, y son el único ítem que le queda a la
# migración. En vez de fallar con un error críptico de psycopg cuando
# `DATABASE_URL` está puesta, avisan claro. El diseño del reemplazo está escrito
# en MIGRACION_POSTGRES.md para retomarlo sin apuro.
class EnsayoPorClonNoDisponible(RuntimeError):
    """El ensayo por clon pedía una conexión sqlite3 y recibió otra cosa."""


def exigir_clon_soportado(conn, herramienta: str) -> None:
    """Corta ANTES de intentar el clon si el motor no lo soporta.

    Pregunta por la CAPACIDAD (¿es una conexión sqlite3 de verdad?) y no por la
    variable de entorno: es exactamente la precondición que hace falta, y así
    tampoco se cuela una conexión del shim por un camino que no mire `DATABASE_URL`.
    """
    if isinstance(conn, sqlite3.Connection):
        return
    raise EnsayoPorClonNoDisponible(
        f"«{herramienta}» todavía no funciona con Postgres/Supabase. Esta "
        f"herramienta simula clonando la base entera con la copia de SQLite "
        f"(Connection.backup), y en Postgres esa fotocopia no existe. Está "
        f"marcada como sólo-SQLite a propósito: es de admin, no está en el camino "
        f"de ningún usuario, y se migra aparte. Para usarla, corré el backend sin "
        f"la variable DATABASE_URL."
    )
