"""GET /api/config no puede perder la config del usuario por una clave no numérica.

El endpoint hacía `{r["key"]: float(r["value"]) for r in rows}` con UN try/except
alrededor de toda la comprehension. Desde que existe `fx_version` (fx.py escribe
'v1'/'v2' en la MISMA tabla config), esa fila hacía saltar el ValueError y el
except devolvía `cfg = {}` — o sea, el usuario perdía su tc_mep/tc_blue guardado
y los `setdefault` le reponían 1415.

Y la fila `fx_version` no es rara: `fx_version()` la persiste con INSERT OR
REPLACE en la primera resolución (fx.py), que ocurre al importar, al registrar
una venta (main.py) o al registrar por chat — y `set_fx_version` la escribe para
TODA cuenta que migre el migrador FX. Migrar 503 cuentas habría dejado a las 503
con el TC pisado en 1415.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _leer_config(rows):
    """Réplica exacta del cuerpo de get_config (main.py) sobre filas dadas."""
    cfg = {}
    for r in rows:
        try:
            cfg[r["key"]] = float(r["value"])
        except (ValueError, TypeError):
            continue
    cfg.setdefault("tc_mep", 1415)
    cfg.setdefault("tc_blue", 1415)
    return cfg


def _rows(pairs):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE config (key TEXT, value TEXT, user_id INT)")
    conn.executemany("INSERT INTO config VALUES (?,?,1)", pairs)
    return conn.execute("SELECT key, value FROM config WHERE user_id=1").fetchall()


class ConfigConFxVersionTest(unittest.TestCase):

    def test_fx_version_no_se_lleva_puesto_el_tc_del_usuario(self):
        rows = _rows([("tc_mep", "1200"), ("tc_blue", "1300"), ("fx_version", "v1")])
        cfg = _leer_config(rows)
        self.assertEqual(cfg["tc_mep"], 1200.0)   # antes daba 1415
        self.assertEqual(cfg["tc_blue"], 1300.0)  # antes daba 1415

    def test_v2_tampoco(self):
        cfg = _leer_config(_rows([("tc_mep", "980.5"), ("fx_version", "v2")]))
        self.assertEqual(cfg["tc_mep"], 980.5)

    def test_la_clave_no_numerica_no_se_expone(self):
        # El endpoint es el de los tipos de cambio; fx_version se lee por su
        # módulo. No exponerla mantiene el contrato que el frontend ya consume.
        cfg = _leer_config(_rows([("tc_mep", "1200"), ("fx_version", "v1")]))
        self.assertNotIn("fx_version", cfg)

    def test_defaults_cuando_no_hay_nada(self):
        cfg = _leer_config(_rows([]))
        self.assertEqual(cfg, {"tc_mep": 1415, "tc_blue": 1415})

    def test_solo_fx_version_cae_a_defaults(self):
        cfg = _leer_config(_rows([("fx_version", "v2")]))
        self.assertEqual(cfg, {"tc_mep": 1415, "tc_blue": 1415})

    def test_el_endpoint_real_ya_no_usa_la_comprehension_envuelta(self):
        import re
        main_py = os.path.join(os.path.dirname(__file__), "..", "main.py")
        src = open(main_py, encoding="utf-8").read()
        cuerpo = src[src.index('@app.get("/api/config")'):][:1600]
        self.assertNotIn('cfg = {r["key"]: float(r["value"]) for r in rows}', cuerpo)
        self.assertIn("continue", cuerpo)


if __name__ == "__main__":
    unittest.main()
