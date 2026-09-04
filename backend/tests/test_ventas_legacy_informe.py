"""Informe read-only: qué pasaría con las ventas viejas sin moneda sellada.

Las ventas registradas antes del 2026-08-15 no sellaron `currency` ni
`fx_to_usd`, así que Movimientos no puede convertirlas y muestra el bruto en
PESOS con cartel de dólares. Lo que falta NO es el TC (está desde 2011): falta
saber si la venta fue en pesos.

La deducción propuesta es la MISMA regla que ya aplica /positions/sell cuando el
cliente no manda moneda: la `currency` propia del broker. Estos tests fijan que
el informe la aplique bien y que NO ESCRIBA NADA — es el paso previo a activarla.

Corre con: cd backend && python3 -m pytest tests/test_ventas_legacy_informe.py
"""
import unittest
import uuid

import main


TC_2022 = 269.39
TC_2021 = 161.33


def _cliente():
    from fastapi.testclient import TestClient
    return TestClient(main.app)


class InformeVentasLegacy(unittest.TestCase):
    def setUp(self):
        self.client = _cliente()
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, is_admin) "
            "VALUES (?, 'x', 1, 1)",
            (f"leg-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        # Un broker en pesos y uno en dólares — la regla tiene que separarlos.
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,'Cocos','ARS')",
                     (self.uid,))
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,'Binance','USDT')",
                     (self.uid,))
        for f, tc in (("2021-06-03", TC_2021), ("2022-09-12", TC_2022)):
            conn.execute(
                "INSERT OR REPLACE INTO fx_rates_daily (date, blue_venta, mep_venta) "
                "VALUES (?,?,?)", (f, tc, tc))
        # Venta vieja en un broker ARS: 485 × 283,43 = 137.463 pesos.
        conn.execute(
            """INSERT INTO operations
                 (user_id, date, broker, asset, op_type, entry_date, entry_price,
                  exit_price, quantity, pnl_usd, commissions, currency, fx_to_usd)
               VALUES (?,'2022-09-12','Cocos','AUSO','Venta','2021-06-03',67.0,
                       283.43,485.0,100.0,964.73,NULL,NULL)""",
            (self.uid,),
        )
        # Venta vieja en un broker USD: no se toca.
        conn.execute(
            """INSERT INTO operations
                 (user_id, date, broker, asset, op_type, entry_date, entry_price,
                  exit_price, quantity, pnl_usd, commissions, currency, fx_to_usd)
               VALUES (?,'2022-09-12','Binance','BTC','Venta',NULL,20000.0,
                       30000.0,0.5,5000.0,12.0,NULL,NULL)""",
            (self.uid,),
        )
        conn.commit()
        conn.close()
        main.app.dependency_overrides[main.get_admin_user] = lambda: self.uid

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_admin_user, None)

    def _informe(self):
        r = self.client.get(f"/api/admin/ventas-legacy-debug?user_id={self.uid}")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_no_escribe_nada(self):
        """La garantía central: es un informe, no una reparación."""
        conn = main.get_db()
        antes = conn.execute(
            "SELECT currency, fx_to_usd FROM operations WHERE user_id=?", (self.uid,)
        ).fetchall()
        conn.close()
        self.assertTrue(all(r["currency"] is None and r["fx_to_usd"] is None
                            for r in antes))
        self._informe()
        conn = main.get_db()
        despues = conn.execute(
            "SELECT currency, fx_to_usd FROM operations WHERE user_id=?", (self.uid,)
        ).fetchall()
        conn.close()
        self.assertTrue(all(r["currency"] is None and r["fx_to_usd"] is None
                            for r in despues),
                        "el informe NO puede tocar la base")

    def test_solo_cuenta_las_del_broker_en_pesos(self):
        """La de Binance (USD) no entra: no hay nada que convertir."""
        inf = self._informe()
        self.assertEqual(inf["cambiarian"], 1)
        self.assertIn("Cocos", inf["por_broker"])
        self.assertNotIn("Binance", inf["por_broker"])

    def test_muestra_el_antes_y_el_despues(self):
        """485 × 283,43 = 137.463 pesos → US$510 al TC de esa fecha."""
        fila = self._informe()["detalle"][0]
        self.assertEqual(fila["moneda_deducida"], "ARS")
        self.assertAlmostEqual(fila["venta_hoy_muestra"], 137463.55, places=2)
        self.assertAlmostEqual(fila["venta_pasaria_a"], 137463.55 / TC_2022, places=2)

    def test_cada_pata_con_su_propio_dolar(self):
        """La compra usa el TC de 2021, no el de la venta de 2022."""
        fila = self._informe()["detalle"][0]
        self.assertAlmostEqual(fila["tc_compra"], TC_2021, places=2)
        self.assertAlmostEqual(fila["compra_pasaria_a"], (67.0 * 485) / TC_2021, places=2)

    def test_tambien_proyecta_las_comisiones(self):
        fila = self._informe()["detalle"][0]
        self.assertAlmostEqual(fila["comision_pasaria_a"], 964.73 / TC_2022, places=2)

    def test_un_broker_que_ya_no_existe_se_reporta_sin_resolver(self):
        """Renombrar/borrar un broker deja la operación huérfana: se avisa."""
        conn = main.get_db()
        conn.execute(
            """INSERT INTO operations
                 (user_id, date, broker, asset, op_type, entry_price, exit_price,
                  quantity, pnl_usd, currency, fx_to_usd)
               VALUES (?,'2022-09-12','BrokerBorrado','XXX','Venta',1.0,2.0,3.0,
                       1.0,NULL,NULL)""",
            (self.uid,),
        )
        conn.commit()
        conn.close()
        inf = self._informe()
        self.assertEqual(inf["no_se_pueden_resolver"], 1)
        self.assertIn("broker no existe", inf["sin_resolver"][0]["motivo"])


if __name__ == "__main__":
    unittest.main()
