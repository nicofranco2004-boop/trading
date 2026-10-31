"""La suite se NIEGA a arrancar contra una base con datos de personas.

POR QUÉ (audit/HANDOFF_MIGRACION_PG.md, 5.F). El primer archivo de prueba que
hace `import main` corre `init_db()` —esquema, reparaciones de arranque, la
migración de credenciales— contra la base del `DATABASE_URL` tal como vino, en
su esquema por defecto. Recién después el conftest muda cada módulo a su
esquema propio `t<pid>_…`. Con una base vacía eso sólo deja tablas vacías;
contra la base del pasaje ya cargada, o contra producción, la suite le
REPARARÍA los datos a la gente: renombrar cajas, pasar tokens a huella, marcar
admins… sin que nadie lo haya pedido.

QUÉ MIRA. `users` y `operations` en el esquema por defecto de esa conexión
(adonde iría `init_db`) y en `public`. Una fila en cualquiera = datos de
personas = no arranca. No hay forma de saltearlo: si hace falta correr la suite
contra esa base, la base equivocada es ésa.

Lo llama `tests/conftest.py` al cargarse, ANTES de que pytest junte los
archivos de prueba (que es cuando se importa `main`).
"""
TABLAS_DE_PERSONAS = ("users", "operations")


def filas_de_personas(dsn: str) -> list:
    """['esquema.tabla', …] de las tablas de personas que tienen al menos una fila."""
    import pgsesion
    con_filas = []
    with pgsesion.conectar(dsn, autocommit=True) as c:
        defecto = c.execute("SELECT current_schema()").fetchone()[0]
        for esquema in sorted({defecto or "public", "public"}):
            for tabla in TABLAS_DE_PERSONAS:
                existe = c.execute("SELECT to_regclass(%s)", (f'"{esquema}"."{tabla}"',)).fetchone()[0]
                if existe and c.execute(
                        f'SELECT EXISTS (SELECT 1 FROM "{esquema}"."{tabla}")').fetchone()[0]:
                    con_filas.append(f"{esquema}.{tabla}")
    return con_filas


def mensaje(con_filas: list) -> str:
    return ("\n🔴 LA SUITE NO ARRANCA: la base de DATABASE_URL tiene datos de personas "
            f"({', '.join(con_filas)}).\n"
            "   Al cargar `main`, el arranque (esquema + reparaciones) corre contra esa base\n"
            "   ANTES de que cada prueba se mude a su esquema propio, y le modificaría los\n"
            "   datos a la gente. Usá una base vacía (audit/HANDOFF_MIGRACION_PG.md, 5.F).\n")
