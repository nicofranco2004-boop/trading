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


# Copia TEXTUAL de la rama de la migración (`arranque-planb`, 29/10), que la mudó
# acá desde main.py: la usan las alertas (auditoría C1). Al juntar las ramas,
# queda una sola.
from contextlib import contextmanager


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
