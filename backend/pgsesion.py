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

# ── ¿Esta conexión habla Postgres? ───────────────────────────────────────────
# 🔴 SE PREGUNTA POR LA CONEXIÓN Y NO POR LA BANDERA GLOBAL, y esto costó 13
# tests rojos que SQLite no podía ver.
#
# La primera versión preguntaba `main.USANDO_PG`, que es una bandera de proceso:
# dice «este proceso arrancó con DATABASE_URL puesta». Pero el turno se pide
# sobre UNA conexión concreta, y las dos cosas no son lo mismo. Hay código que
# abre una base SQLite propia aunque el proceso tenga DATABASE_URL —los tests
# con `sqlite3.connect(":memory:")` son el caso evidente, y un script suelto es
# el caso que importa—. Ahí la bandera decía «Postgres», el turno mandaba
# `pg_advisory_xact_lock` por una conexión de SQLite, y el resultado era:
#
#     sqlite3.OperationalError: no such function: pg_advisory_xact_lock
#
# O sea: reventaba, no fallaba callado. Lo encontró la suite de Postgres con 13
# rojos en `test_ai_plan`, `test_ai_quota`, `test_alerts` y
# `test_efectivo_una_puerta`, y la de SQLite no podía verlo porque allá la
# bandera está en falso y el turno no se pide nunca.
#
# La pregunta correcta es sobre el objeto que se tiene en la mano.
#
# 🔴 SEGUNDA VUELTA, porque la primera versión de esta función tenía un agujero
# que costó dos cajas de efectivo. Miraba SÓLO `type(conn).__module__` y
# devolvía «no» para cualquier cosa que no reconociera, con el argumento de que
# fallar cerrada es más seguro. **Acá fallar cerrada es perder la protección en
# silencio**, y eso es justo el bug de plata que el candado existe para tapar.
#
# Lo que lo destapó: un ENVOLTORIO. `tests/test_dos_pedidos_a_la_vez.py` hace
# `main.get_db = lambda: _Conexion(real(), cruce)` para forzar que dos pedidos
# lean antes de que nadie escriba. Ese envoltorio no es `pgshim.Connection`
# —su módulo es el del test—, así que la primera versión decía «no es Postgres»,
# no pedía el candado, y los dos primeros depósitos simultáneos volvían a crear
# DOS cajas: medido, quedaron una con 200 y otra con 300. Como todo el código
# lee «la más vieja», los 200 no los movía nadie más.
#
# Y no es un problema del test: cualquier envoltorio —uno de registro, uno de
# pool, uno de medición— perdía la protección sin que nada avisara.
#
# POR ESO SE PREGUNTA EN TRES PASOS, y el orden importa:
#   1. ¿Es SQLite? Dos formas, porque un envoltorio NO es una
#      `sqlite3.Connection` pero SÍ reenvía sus atributos por `__getattr__`.
#      `total_changes` lo tiene sqlite3 y no lo tiene psycopg.
#   2. ¿Es Postgres, directo? Por el módulo, como antes.
#   3. Ninguna de las dos: ahí sí vale la bandera del proceso, que es la mejor
#      información que queda. Un envoltorio sigue el motor de la app.
# Así el caso que arreglamos (una base SQLite de verdad con el proceso apuntando
# a Postgres) lo caza el paso 1, y el que rompimos (un envoltorio sobre una
# conexión buena) lo caza el paso 3.
from contextlib import contextmanager


def tomar_turno(conn, uid: int) -> None:
    """El turno de escritura de la cuenta, EN LOS DOS MOTORES (`main._tomar_turno`
    es esto). Vive acá porque `importing/` también lo necesita y no puede importar
    `main`: la vista previa del import lo toma justo antes de escribir para que un
    renombre de broker no se meta entre lo que leyó y lo que escribe.

    `tier` y no `id`: reescribir la clave primaria hacía 14 chequeos de claves
    foráneas por borrado. En SQLite toma la base entera; en Postgres, la fila de
    `users` (espera quien también la escriba).
    """
    conn.execute("UPDATE users SET tier=tier WHERE id=?", (uid,))


@contextmanager
def si_falla_se_deshace_solo_esto(conn, nombre: str):
    """Un punto de guardado: si lo de adentro revienta, se deshace SÓLO eso y la
    excepción sigue su camino; lo escrito antes queda en pie.

    🔴 POR QUÉ HACE FALTA, y por qué sólo se nota en Postgres. Dos formas, el
    mismo mecanismo:

      · «try: escribir → except: log → commit». Supone que un error deja la
        transacción como estaba. En SQLite es así. En Postgres un error de SQL
        deja la transacción ENTERA abortada y el `commit()` de después es un
        ROLLBACK: se descarta también lo de ANTES del `try`. Medido el 28/10/2026
        en `create_operation`: contestaba 200 con el id de una operación que ya no
        existía (`test_pnl_del_mes_dos_pedidos`).
      · «try: la consulta nueva → except: la consulta vieja» (el PLAN B). En
        Postgres el plan B no falla por el motivo original: falla con
        `InFailedSqlTransaction`, un error de otra familia que el `except` de
        afuera no reconoce. Medido el 29/10/2026 en `register`: un email repetido
        devolvía 500 en vez del 409 «ese email ya está registrado»
        (`test_email_verification`). Son 9 sitios, barridos con AST; el guardián
        `tests/test_plan_b_tiene_punto_de_guardado.py` vigila que no entre el
        décimo.

    Con esto los dos motores hacen lo mismo: lo que falló no se aplica y lo demás
    se guarda.

    ⚠️ **Y NO alcanza con `conn.rollback()`**, que es la salida obvia: el rollback
    descarta TODO lo que haya sin guardar en la transacción, no sólo la sentencia
    que falló. `ai/quota.py` se llama desde el medio de las reservas de cuota, que
    ya escribieron: ahí un rollback se llevaría plata ya anotada.

    El `except` lo sigue poniendo quien llama: es el que sabe si el error se puede
    tragar (un recálculo que se rearma solo después) o tiene que llegar al usuario.

    📌 POR QUÉ VIVE ACÁ Y NO EN `main.py`, donde nació. Porque `ai/quota.py` y
    `snapshots_job.py` también lo necesitan y no pueden importar `main` (main los
    importa a ellos: sería un círculo). Éste es el módulo de «lo que toda conexión
    necesita», el mismo lugar que `turno_exclusivo`. `main.py` lo delega.
    """
    conn.execute(f"SAVEPOINT {nombre}")
    try:
        yield
    except BaseException:
        conn.execute(f"ROLLBACK TO SAVEPOINT {nombre}")
        conn.execute(f"RELEASE SAVEPOINT {nombre}")
        raise
    conn.execute(f"RELEASE SAVEPOINT {nombre}")


import sqlite3 as _sqlite3

_MODULOS_QUE_HABLAN_POSTGRES = ("pgshim", "psycopg")


def habla_postgres(conn) -> bool:
    """¿ESTA conexión habla Postgres? Preguntándole al objeto, en tres pasos.

    Ver el comentario de arriba: cada paso está porque un bug lo pidió.
    """
    # 1 · SQLite, directo o a través de un envoltorio que reenvía atributos.
    try:
        if isinstance(conn, _sqlite3.Connection):
            return False
        if hasattr(conn, "total_changes"):
            return False
    except Exception:
        return False
    # 2 · Postgres, directo.
    try:
        if type(conn).__module__.split(".")[0] in _MODULOS_QUE_HABLAN_POSTGRES:
            return True
    except Exception:
        pass
    # 3 · Un envoltorio que no reenvía nada reconocible: el motor del proceso.
    #     Pero antes, que al menos PAREZCA una conexión: sin esto, un `None`
    #     —o cualquier cosa pasada por error— contestaba «sí habla Postgres» y
    #     el error salía recién en el `conn.execute`, lejos y disfrazado.
    if not callable(getattr(conn, "execute", None)):
        return False
    try:
        import main as _m
        return bool(getattr(_m, "USANDO_PG", False))
    except Exception:
        return False


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

      🔴 ACÁ ME EQUIVOQUÉ YO, y queda escrito porque el error es instructivo.
      El 22/10 anoté que el tope de la cuota de IA SÍ aguantaba «porque escribe
      sobre la fila de ese usuario (`ON CONFLICT (user_id, date) DO UPDATE`) y
      Postgres los hace esperar en esa fila». Lo medí con DOS pedidos y pasó.
      El 23/10 la auditoría lo midió con DIEZ: tope 1, entraron 8.

      El razonamiento estaba bien a medias. Los pedidos sí se esperan en la
      fila. Pero cuando les toca seguir, la SUBCONSULTA que suma la semana se
      evalúa con la foto que su transacción sacó al arrancar, así que
      re-chequean el tope contra un número que ya no existe. Con dos pedidos el
      segundo suele alcanzar a sacar foto nueva y rechaza bien: de ahí el falso
      negativo. Con ocho, no.

      ⚠️ LA REGLA QUE QUEDA: «choca en una fila compartida» NO es protección.
      Lo único que protege es que el NÚMERO comparado contra el tope se lea
      DESPUÉS de que el otro escribió — y eso acá sólo lo da el turno. Si un
      tope cuenta algo y después escribe, pedí el turno, no lo deduzcas.

      (El de pruebas gratis del mes es el caso evidente: cuenta filas de TODOS
      los usuarios e inserta una nueva, así que no hay ni fila donde chocar.
      Medido: NO aguanta. Pero «no hay fila compartida» nunca fue el criterio.)

    `pg_advisory_xact_lock` se suelta solo al terminar la transacción (commit o
    rollback), así que no hay forma de olvidarse de devolverlo — que es
    exactamente el error que deja una base trabada.

    En SQLite no hace NADA, a propósito: allá el motor ya serializa y agregar un
    candado propio sólo sumaría una forma nueva de trabarse.
    """
    if not habla_postgres(conn):
        return                          # SQLite ya serializa: no hay nada que pedir
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
#
# ⚠️ **NUNCA ARMAR UNA CLAVE SUMANDO** (`CLAVE + uid`). Para distinguir «sobre
# quién» está la forma de DOS claves, que es un espacio aparte. Sumando, el
# usuario 1 de un tope cae justo en la clave de otro, y el día que alguien
# agregue la de al lado dos cosas sin relación empiezan a esperarse sin que
# nada lo diga. Pasó: `TURNO_TOPE_FACTS_POR_USUARIO + 1` daba exactamente
# `TURNO_CAJA_DEL_BROKER`.
TURNO_TOPE_TRIALS_DEL_MES = 823471001
TURNO_TOPE_FACTS_POR_USUARIO = 823471002
TURNO_CAJA_DEL_BROKER = 823471003
TURNO_CUOTA_IA_POR_USUARIO = 823471004
TURNO_TOPE_DEL_PLAN_POR_USUARIO = 823471005
# El arranque (esquema + reparaciones). De sesión y no de transacción: abarca
# varias conexiones. Ver `main._de_a_un_arranque_por_vez`.
TURNO_ARRANQUE = 823471006
