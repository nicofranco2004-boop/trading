"""Qué sentencias que ESCRIBEN corrieron mientras tanto, en los dos motores.

POR QUÉ EXISTE. «Este pedido no escribe» no se prueba contando filas antes y
después: un UPDATE no cambia ningún conteo, y una escritura sin commit desaparece
sola cuando `db_abierta` cierra la conexión (no commitea), antes de que la prueba
cuente. Las dos pruebas de la vista previa del pase («Mover a otro broker») se
quedaban en verde con un `UPDATE positions SET notes='sabotaje'` adentro, con y sin
commit (revisión adversarial de E4–E6).

Acá se mira la sentencia misma, al correr:
  · SQLite: `set_trace_callback` en cada conexión que abre `main.get_db`;
  · Postgres: lo que pasa por `pgshim.Connection._abrir_si_escribe`, la puerta por
    donde va toda sentencia que no es una lectura pura (la que abre la transacción).

Los puntos de guardado (`SAVEPOINT`/`RELEASE`/`ROLLBACK TO`) no cuentan: no escriben
nada (la lectura del muro de pausa usa uno).

Uso:
    with escrituras(main) as log:
        r = client.post(...)
    assert log == []
"""
import contextlib
import re
from unittest import mock

_ESCRIBE = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|MERGE|TRUNCATE|"
    r"BEGIN\s+(IMMEDIATE|EXCLUSIVE))\b", re.I)
_PUNTO_DE_GUARDADO = re.compile(r"^\s*(SAVEPOINT|RELEASE|ROLLBACK\s+TO)\b", re.I)


@contextlib.contextmanager
def escrituras(main):
    import pgshim
    log = []
    real_get_db = main.get_db

    def get_db_trazada(*a, **k):
        c = real_get_db(*a, **k)
        if hasattr(c, "set_trace_callback"):           # sqlite3
            c.set_trace_callback(
                lambda s: log.append(s.strip()[:200]) if _ESCRIBE.match(s or "") else None)
        return c

    real_abrir = pgshim.Connection._abrir_si_escribe

    def espia(self, q):
        if not pgshim.es_lectura_pura(q) and not _PUNTO_DE_GUARDADO.match(q or ""):
            log.append(str(q).strip()[:200])
        return real_abrir(self, q)

    with mock.patch.object(main, "get_db", get_db_trazada), \
            mock.patch.object(pgshim.Connection, "_abrir_si_escribe", espia):
        yield log
