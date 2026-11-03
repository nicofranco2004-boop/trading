"""Borrar una alerta se lleva sus marcas de `alert_symbol_state`, por todos los caminos.

`alert_symbol_state` guarda, por alerta y activo, «ya avisé hoy» y «ya miré las
velas hasta tal día» (alertas técnicas). No tiene `user_id`: cuelga de la alerta
por `alert_id`. Por eso los dos barridos que borran «todo lo de una persona» —el
reset de admin y el borrado de cuenta, que van por `user_id`— la salteaban, y sus
filas quedaban huérfanas (auditoría C, hallazgo 6: 1 tras el reset, 2 tras el
borrado). No hacía daño (los números de alerta no se reusan), pero era basura que
crecía con cada alerta técnica. «Eliminar alerta» ya la borraba.

El arreglo no es acordarse en cada camino: los dos barridos, después de borrar,
limpian toda tabla que cuelgue de `alerts` por `alert_id` sin tener `user_id`,
leída del esquema (`main._borrar_colgadas_de_alerts`). Una tabla nueva de ese tipo
queda cubierta sola. Las marcas de alertas de OTRA persona no se tocan.

Corre con: cd backend && python3 -m pytest tests/test_marcas_de_alertas.py
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
import alerts_engine as ae
from fastapi.testclient import TestClient


class MarcasDeAlertas(unittest.TestCase):
    _seq = 62000

    def setUp(self):
        MarcasDeAlertas._seq += 2
        self.UID, self.OTRO = MarcasDeAlertas._seq, MarcasDeAlertas._seq + 1
        self.cli = TestClient(main.app)
        with main.db_abierta() as c:
            for u in (self.UID, self.OTRO):
                c.execute("INSERT INTO users (id,email,password_hash,approved) VALUES (?,?,?,1)",
                          (u, f"marcas{u}@t.com", "x"))
            self.alertas = {u: self._alerta_con_marcas(c, u) for u in (self.UID, self.OTRO)}
            c.commit()

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        main._reset_progress.pop(self.UID, None)
        with main.db_abierta() as c:
            c.execute("DELETE FROM alert_symbol_state WHERE alert_id=987654321")
            for u in (self.UID, self.OTRO):
                c.execute("DELETE FROM alert_symbol_state WHERE alert_id IN "
                          "(SELECT id FROM alerts WHERE user_id=?)", (u,))
                c.execute("DELETE FROM alerts WHERE user_id=?", (u,))
                c.execute("DELETE FROM users WHERE id=?", (u,))
            c.commit()

    def _alerta_con_marcas(self, c, uid):
        """Una alerta técnica con sus dos marcas: «miré las velas hasta acá» y
        «ya avisé hoy». Las escriben las funciones del motor."""
        aid = c.execute(
            """INSERT INTO alerts (user_id, kind, symbol, scope, direction, currency, channel,
                                   repeat, cooldown_min, armed, active, senal, accion_local)
               VALUES (?,'tecnica','AAPL','ticker','either','USD','both','once',0,1,1,'sma200',0)""",
            (uid,)).lastrowid
        ae._marcar_visto(c, aid, "AAPL", "2026-10-28")
        ae._set_sym_fired(c, aid, "AAPL", "2026-10-28")
        return aid

    def _marcas(self, aid):
        with main.db_abierta() as c:
            return c.execute("SELECT COUNT(*) FROM alert_symbol_state WHERE alert_id=?",
                             (aid,)).fetchone()[0]

    def _huerfanas(self):
        with main.db_abierta() as c:
            return c.execute(
                "SELECT COUNT(*) FROM alert_symbol_state s WHERE NOT EXISTS "
                "(SELECT 1 FROM alerts a WHERE a.id = s.alert_id)").fetchone()[0]

    def _otro_intacto(self):
        self.assertEqual(self._marcas(self.alertas[self.OTRO]), 2,
                         "las marcas de la alerta de OTRA persona no se tocan")

    def test_las_marcas_existen_antes(self):
        self.assertEqual(self._marcas(self.alertas[self.UID]), 2)

    def test_reset_de_admin(self):
        main._reset_data_worker(self.UID, tablas=main._reset_admin_tablas(),
                                toda_la_config=True, borrar_perfil=True, pausa=0)
        self.assertEqual(main._reset_estado(self.UID).get("estado"), "listo",
                         main._reset_estado(self.UID).get("error"))
        self.assertEqual(self._marcas(self.alertas[self.UID]), 0)
        self.assertEqual(self._huerfanas(), 0)
        self._otro_intacto()

    def test_borrar_la_cuenta_por_la_app(self):
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.UID
        r = self.cli.delete("/api/me")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._marcas(self.alertas[self.UID]), 0)
        self.assertEqual(self._huerfanas(), 0)
        self._otro_intacto()

    def test_eliminar_alerta_por_la_app(self):
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.UID
        r = self.cli.delete(f"/api/alerts/{self.alertas[self.UID]}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._marcas(self.alertas[self.UID]), 0)
        self._otro_intacto()

    def test_el_arranque_limpia_las_sueltas_de_antes(self):
        """Las marcas que ya quedaron sueltas (de antes del arreglo) no las borra
        ningún barrido: el arranque las limpia una vez. Las de alertas vivas, no."""
        with main.db_abierta() as c:
            c.execute("INSERT INTO alert_symbol_state (alert_id, symbol, armed) VALUES (?,?,1)",
                      (987654321, "AAPL"))
            c.commit()
        self.assertEqual(self._huerfanas(), 1)
        main.init_db()
        self.assertEqual(self._huerfanas(), 0)
        self.assertEqual(self._marcas(self.alertas[self.UID]), 2)
        self._otro_intacto()

    def test_eliminar_la_alerta_de_otro_no_toca_sus_marcas(self):
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.UID
        self.cli.delete(f"/api/alerts/{self.alertas[self.OTRO]}")
        self._otro_intacto()


if __name__ == "__main__":
    unittest.main()
