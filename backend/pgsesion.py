"""Toda conexión a Postgres de Rendi se abre POR ACÁ, con los ajustes de sesión.

EL PROBLEMA, medido contra el Supabase real y no razonado.

`extra_float_digits` vale **0** en los dos poolers de Supabase, y **1** en un
Postgres normal (es el default desde PG 12). Con 0, Postgres imprime los
`double precision` con **15 dígitos significativos**, que **no alcanzan** para
reconstruir un `double`: el cliente parsea ese texto y obtiene OTRO número.

Medido sobre 350 filas de `operations.pnl_usd` recién copiadas:

    filas cuyos BITS GUARDADOS difieren del origen:   0 de 350
    filas cuya LECTURA difiere del origen:           73 de 350
        y con extra_float_digits = 3:                 0 de 350

O sea: **el dato viajó perfecto y el que mentía era el lector.** Ejemplo real:
guardado `31.450000000000003`, leído `31.45`, bits en disco idénticos al origen.

⚠️ **POR QUÉ ESTO NO ES UN DETALLE DE LA VERIFICACIÓN, y es la parte que importa.**
Mientras sea sólo lectura, 1e-14 es invisible en pesos. Pero el rebuild hace
**leer → modificar → escribir** sobre estos mismos campos. Si un rebuild lee
`31.450000000000003`, recibe `31.45` y lo vuelve a escribir, **ahí los bits en
disco SÍ cambian** — y a partir de ese momento la verificación compara bien y no ve
nada, porque origen y destino coinciden en el valor redondeado. Ése es el camino de
"invisible" a "real", y es corto.

POR QUÉ UN `SET` Y NO `options=` EN EL DSN. Medido en los dos poolers:

    | mecanismo            | session (5432) | transaction (6543) |
    |----------------------|----------------|--------------------|
    | SET al conectar      | ✅             | ✅                 |
    | options= en el DSN   | 🔴 lo ignora   | ✅                 |

El `options=` anda sólo en el transaccional. Atar el arreglo al pooler que se use
hoy sería dejar una trampa para el día que se cambie de puerto — y **cuál de los
dos usar es justamente una decisión abierta**. El `SET` funciona en los dos.

📌 **ANOTADO Y NO TOMADO: el protocolo binario.** `psycopg` puede pedir los
resultados en binario, y ahí los `float8` viajan como los 8 bytes exactos: no
dependería de ningún estado de sesión, que es más elegante. Pero cambia cómo viajan
**todos** los tipos, no sólo los floats, y abrir ese frente a esta altura de la
migración no hace falta. Queda para cuando haya tiempo.
"""
from __future__ import annotations

# Los ajustes que TODA conexión de Rendi necesita. Es una tupla y no una línea
# suelta para que agregar el segundo no obligue a tocar cuatro lugares.
AJUSTES_DE_SESION = (
    # Sin esto, leer un float de Postgres puede devolver otro número. Ver arriba.
    "SET extra_float_digits = 3",
)


def ajustar(conn):
    """Aplica los ajustes a una conexión psycopg ya abierta. Devuelve la conexión.

    Existe aparte de `conectar()` porque hay un caso que no abre la conexión pero
    igual tiene que ajustarla: el `with psycopg.connect(...)` de un test, o
    cualquier conexión que venga de afuera.
    """
    for sql in AJUSTES_DE_SESION:
        conn.execute(sql)
    return conn


def conectar(dsn: str, **kw):
    """Abre una conexión a Postgres con los ajustes puestos.

    ⚠️ **Ésta es la única puerta.** `tests/test_conexiones_pg_ajustadas.py` barre el
    backend con AST y falla si aparece un `psycopg.connect` que no pase por acá:
    una conexión sin ajustar lee floats redondeados, y eso no da error — da un
    número distinto.
    """
    import psycopg
    conn = psycopg.connect(dsn, **kw)
    try:
        return ajustar(conn)
    except Exception:
        conn.close()
        raise

# ── El turno: serializar un chequeo de tope ──────────────────────────────────

def turno_exclusivo(conn, clave: int, clave2: int = None) -> None:
    """Pide el turno para un chequeo de tope. Las demás esperan acá.

    POR QUÉ EXISTE, y no es teórico — medido el 22/10/2026 contra Postgres real.

    Varios topes de Rendi se hacen cumplir contando y escribiendo en UNA sola
    sentencia (`INSERT … SELECT … WHERE (SELECT COUNT(*) …) < tope`). El
    comentario de esos sitios dice que así «el tope se respeta bajo carga», y en
    SQLite es CIERTO — pero no por la sentencia: porque SQLite deja escribir a
    UNO POR VEZ en toda la base. La garantía venía del motor, gratis, sin que
    nadie la pidiera.

    En Postgres cada transacción lee su propia foto del momento en que arrancó.
    Veinte altas simultáneas cuentan CERO las veinte y entran las veinte.
    Reproducido con tope 1 y dos conexiones: entraron las dos.

      ⚠️ No todos los topes se rompen, y la diferencia importa:
      · El de la cuota de IA escribe sobre LA FILA DE ESE USUARIO
        (`ON CONFLICT (user_id, date) DO UPDATE`). Dos pedidos chocan en esa
        fila, Postgres los hace esperar, y el tope AGUANTA. Medido: aguanta.
      · El de pruebas gratis del mes cuenta filas de TODOS los usuarios e
        inserta una fila nueva. No hay fila compartida donde chocar, así que
        nadie espera a nadie. Medido: NO aguanta.

    `pg_advisory_xact_lock` se suelta solo al terminar la transacción (commit o
    rollback), así que no hay forma de olvidarse de devolverlo — que es
    exactamente el error que deja una base trabada.

    En SQLite no hace NADA, a propósito: allá el motor ya serializa y agregar un
    candado propio sólo sumaría una forma nueva de trabarse.
    """
    try:
        import main as _m
        if not getattr(_m, "USANDO_PG", False):
            return                      # SQLite ya serializa: no hay nada que pedir
    except Exception:
        return
    if clave2 is None:
        conn.execute("SELECT pg_advisory_xact_lock(?)", (int(clave),))
    else:
        # Forma de dos claves: la primera dice QUÉ se está serializando y la
        # segunda SOBRE QUIÉN. Así dos usuarios distintos no se esperan.
        conn.execute("SELECT pg_advisory_xact_lock(?, ?)",
                     (int(clave), int(clave2)))


# Claves de turno. Fijas y acá juntas para que se vea de un vistazo quién
# compite con quién: dos topes distintos NO pueden compartir clave (se
# bloquearían sin motivo) y el mismo tope SÍ tiene que usar siempre la misma.
TURNO_TOPE_TRIALS_DEL_MES = 823471001
TURNO_TOPE_FACTS_POR_USUARIO = 823471002

TURNO_CAJA_DEL_BROKER = 823471003
