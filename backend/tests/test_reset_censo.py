"""Censo del reset de ADMIN: toda tabla con `user_id` tiene una decisión escrita.

El reset de admin («como la primera vez», POST /api/admin/reset-user) borra con
una lista CERRADA a propósito: un barrido «todo lo que tenga user_id» (el del
borrado de cuenta) se llevaría un día una tabla de plata nueva y le resetearía el
plan a alguien que pagó. El costo de la lista cerrada es que una tabla nueva NO
se resetea sola, y eso pasó dos veces:
  · `futures_positions` (2026-09-09): el reset dejaba futuros abiertos en una
    cuenta «vaciada».
  · `dibujos_grafico` (2026-10-29, auditoría C hallazgo 3): el reset dejaba las
    líneas de tendencia, Fibonacci y Elliott de la persona. Y había 5 tablas
    viejas igual: `market_brief_prefs` (la hermana de `resumen_semanal_prefs`:
    una se borraba y la otra no), `market_brief_log`, `uso_diario`,
    `iol_lab_runs`, `iol_lab_token_log`.

La causa de proceso no era una tabla olvidada: era que NADA obligaba a decidir.
Este test es esa obligación. Cada tabla con `user_id` (o `advisor_uid`, las del
plan asesor) de la base tiene que estar
en exactamente UNO de estos lugares de main.py:
  · `_reset_admin_tablas()` → el reset la borra;
  · `_RESET_ADMIN_CONSERVADAS` → el reset la deja, con el motivo escrito;
  · `_RESET_ADMIN_OTRO_CAMINO` → la borra el reset, pero por otro camino
    (no por `user_id=?` en la lista).
Si alguien crea una tabla nueva con `user_id` y no la pone en ninguna, rojo, con
el nombre de la tabla y las dos opciones.

Mira la base REAL que arma `init_db` (en SQLite y, con DATABASE_URL, en
Postgres): no una lista copiada en el test, que envejecería igual que la otra.

Corre con: cd backend && python3 -m pytest tests/test_reset_censo.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
import main


# Las columnas con que una tabla dice «esto es de tal persona». `advisor_uid`
# también: las tablas del plan asesor no tienen `user_id`, y su decisión («son
# vínculos con OTRAS personas, el reset no las toca») estaba escrita sólo en un
# comentario y se perdió al pasarlo al diccionario (re-test de la auditoría C).
COLUMNAS_DE_PERSONA = ("user_id", "advisor_uid")


def _tablas_con_user_id() -> set:
    conn = main.get_db()
    try:
        esquema = main._esquema_por_tabla(conn)
    finally:
        conn.close()
    return {t for t, cols in esquema.items() if any(c in cols for c in COLUMNAS_DE_PERSONA)}


def _borra() -> set:
    return set(main._reset_admin_tablas())


def _conserva() -> dict:
    return dict(getattr(main, "_RESET_ADMIN_CONSERVADAS", {}))


def _otro_camino() -> dict:
    return dict(getattr(main, "_RESET_ADMIN_OTRO_CAMINO", {}))


class CensoDelReset(unittest.TestCase):

    def test_toda_tabla_con_user_id_tiene_una_decision(self):
        decididas = _borra() | set(_conserva()) | set(_otro_camino())
        sin_decidir = sorted(_tablas_con_user_id() - decididas)
        self.assertEqual(
            sin_decidir, [],
            "Estas tablas tienen user_id y nadie decidió qué hace con ellas el reset "
            "de admin («como la primera vez»). Para cada una, en main.py: si es algo "
            "que la persona cargó o configuró, va en _RESET_ADMIN_EXTRA_TABLES (o en "
            "_RESET_PORTFOLIO_TABLES si es cartera); si tiene que sobrevivir (plata, "
            "identidad, contadores de cuota, rastro de seguridad o de lo que Rendi "
            "mandó), va en _RESET_ADMIN_CONSERVADAS con su motivo: %s" % sin_decidir)

    def test_ninguna_tabla_tiene_dos_decisiones(self):
        """Borrar y conservar a la vez es no haber decidido."""
        b, c, o = _borra(), set(_conserva()), set(_otro_camino())
        self.assertEqual(b & c, set(), "en la lista del reset Y en las conservadas")
        self.assertEqual(b & o, set(), "en la lista del reset Y en «otro camino»")
        self.assertEqual(c & o, set(), "conservada Y borrada por otro camino")

    def test_cada_conservada_tiene_su_motivo(self):
        for t, motivo in {**_conserva(), **_otro_camino()}.items():
            self.assertTrue((motivo or "").strip(), f"{t}: falta el motivo")

    def test_no_hay_decisiones_sobre_tablas_que_no_existen(self):
        """Una entrada vieja (tabla renombrada o borrada) es una decisión que ya no
        protege nada: el día que vuelva a existir con otro sentido, nadie decidió."""
        existen = _tablas_con_user_id()
        sobran = sorted((set(_conserva()) | set(_otro_camino())) - existen)
        self.assertEqual(sobran, [], "decisiones sobre tablas sin user_id o inexistentes")


if __name__ == "__main__":
    unittest.main()
