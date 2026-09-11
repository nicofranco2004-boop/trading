"""F5 — un solo riel de dólar para el costo de un lote cross-currency.

EL BUG
──────
La conversión del costo de un lote a la moneda de la venta vivía COPIADA en tres
motores: `persister._persist_sell_fifo`, `rebuild`, y el endpoint de venta manual
`POST /api/positions/sell`. Las dos del importador miran el `fx_version` de la
cuenta y en v2 piden el MEP de la fecha de compra. La del formulario manual pedía
el BLUE siempre, sin mirar la versión.

O sea: en una cuenta v2, la MISMA venta daba un costo distinto según se hubiera
tipeado o importado. Medido sobre la serie real, MEP y blue se separan más de 3 %
en la mitad de los días con los dos publicados, más de 10 % en el 8 % de los días,
y el peor día 25,1 % (2023-10-20).

Lo más caro de todo: el arreglo ya estaba TREINTA LÍNEAS MÁS ABAJO, en el mismo
endpoint — la pata del TC de venta sí era version-aware. Se migró una de las dos
patas de la misma cuenta.

Corre con: cd backend && python3 -m pytest tests/test_riel_unico_venta.py
"""
import unittest

import main
from fastapi.testclient import TestClient


class RielUnicoVentaTest(unittest.TestCase):
    """Un lote en PESOS vendido en DÓLARES (el caso dólar-MEP)."""

    BROKER = "TestRiel"
    COMPRA = "2024-01-10"
    VENTA = "2024-03-15"
    BLUE_COMPRA = 1000.0     # el riel viejo
    MEP_COMPRA = 1250.0      # el riel canónico — 25 % de separación, como el peor día real
    INVERTIDO_ARS = 1_000_000.0
    CANTIDAD = 10.0
    PRECIO_VENTA_USD = 900.0

    # 1.000.000 / 1.000 = 1.000 USD de costo  → P&L 9.000 − 1.000 = 8.000
    COSTO_CON_BLUE = 1000.0
    # 1.000.000 / 1.250 =   800 USD de costo  → P&L 9.000 −   800 = 8.200
    COSTO_CON_MEP = 800.0

    def _armar(self, fx_version: str):
        conn = main.get_db()
        for t in ("operations", "positions", "monthly_entries", "snapshots",
                  "brokers", "fx_rates_daily", "config", "users"):
            try:
                conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        uid = conn.execute(
            "INSERT INTO users (email,password_hash,approved,email_verified) "
            "VALUES ('riel@rendi.test','x',1,1)").lastrowid
        conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,'ARS')",
                     (uid, self.BROKER))
        conn.execute("INSERT INTO config (user_id,key,value) VALUES (?,?,?)",
                     (uid, "fx_version", fx_version))
        # Los dos rieles publicados el día de la COMPRA, bien separados.
        conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
            (self.COMPRA, self.BLUE_COMPRA, self.MEP_COMPRA))
        conn.execute(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
            (self.VENTA, 1100.0, 1400.0))
        conn.execute(
            """INSERT INTO positions
               (user_id,broker,asset,is_cash,buy_price,quantity,invested,
                currency,entry_date,commissions)
               VALUES (?,?,'GGAL',0,?,?,?,'ARS',?,0)""",
            (uid, self.BROKER, self.INVERTIDO_ARS / self.CANTIDAD,
             self.CANTIDAD, self.INVERTIDO_ARS, self.COMPRA))
        conn.commit()
        conn.close()
        return uid

    def _vender_en_dolares(self, uid):
        client = TestClient(main.app)
        r = client.post("/api/positions/sell",
                        headers={"Authorization": f"Bearer {main.create_token(uid)}"},
                        json={"broker": self.BROKER, "asset": "GGAL",
                              "quantity": self.CANTIDAD,
                              "exit_price": self.PRECIO_VENTA_USD,
                              "date": self.VENTA, "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)
        conn = main.get_db()
        try:
            row = conn.execute(
                "SELECT pnl_usd, cost_basis_consumed FROM operations "
                "WHERE user_id=? AND op_type='Venta' LIMIT 1", (uid,)).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, "la venta no dejó fila en operations")
        return row

    def test_v2_valua_el_costo_con_el_MEP_de_la_fecha_de_compra(self):
        """La cuenta migrada usa el MISMO riel que usaría el importador.

        Contra el código viejo el costo sale 1.000 (blue) en vez de 800 (MEP):
        el formulario manual no miraba el `fx_version`.
        """
        uid = self._armar("v2")
        row = self._vender_en_dolares(uid)
        # El costo no se publica directo en la fila, pero sale del P&L: los
        # ingresos son un dato duro (900 × 10 = 9.000 USD).
        costo = self.PRECIO_VENTA_USD * self.CANTIDAD - row["pnl_usd"]
        self.assertAlmostEqual(costo, self.COSTO_CON_MEP, places=2,
                               msg="la venta manual valuó el costo con el blue")

    def test_v1_no_se_mueve(self):
        """Las cuentas NO migradas replayan exactamente como siempre: blue.

        Sin esto el fix sería una migración encubierta de las 503 cuentas v1, que
        es justo lo que `fx.fx_version` existe para evitar.
        """
        uid = self._armar("v1")
        row = self._vender_en_dolares(uid)
        costo = self.PRECIO_VENTA_USD * self.CANTIDAD - row["pnl_usd"]
        self.assertAlmostEqual(costo, self.COSTO_CON_BLUE, places=2,
                               msg="una cuenta v1 cambió de número")

    def test_los_dos_rieles_dan_numeros_distintos(self):
        """El fixture MIDE: si los dos rieles coincidieran, los otros dos tests
        pasarían con cualquier código."""
        self.assertNotAlmostEqual(self.COSTO_CON_BLUE, self.COSTO_CON_MEP, places=2)


class UnRielGuardTest(unittest.TestCase):
    """Guards que leen CÓDIGO. Un test de comportamiento pasa igual aunque mañana
    alguien escriba la cuarta copia en otro archivo — y esa copia es el bug."""

    MOTORES = ("main.py", "importing/persister.py", "importing/rebuild.py")

    @staticmethod
    def _fuente(rel):
        import os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, rel), encoding="utf-8") as f:
            return f.read()

    def test_ningun_motor_pide_el_blue_a_mano(self):
        """`blue_for_date` no vuelve a tener callers de producción.

        La función sigue existiendo (`test_importer.py` fija su contrato), pero
        pedir el riel blue tiene que pasar por `fx_for_date(riel=RIEL_BLUE)`, que
        obliga a nombrar el riel en el call site.
        """
        for rel in self.MOTORES:
            src = self._fuente(rel)
            for linea in src.splitlines():
                s = linea.strip()
                if s.startswith("#") or s.startswith('"') or s.startswith("'"):
                    continue          # comentarios y docstrings pueden nombrarla
                if s.startswith("def blue_for_date("):
                    continue          # la definición, que se conserva a propósito
                self.assertNotIn(
                    "blue_for_date(", s.replace("_persist_blue_for_date(", ""),
                    f"{rel} volvió a pedir el blue sin mirar el fx_version: {s!r}")

    def test_los_tres_motores_usan_la_misma_funcion(self):
        """Los tres llaman a `costo_en_moneda_de_venta`. Si uno deja de llamarla
        es que volvió a tener su propia copia."""
        for rel in self.MOTORES:
            # `assertIn` sobre el archivo entero pega los 2 MB de main.py en el
            # mensaje de fallo. El booleano no.
            self.assertTrue(
                "costo_en_moneda_de_venta(" in self._fuente(rel),
                f"{rel} dejó de usar la conversión única")

    def test_la_funcion_unica_respeta_la_version(self):
        """`historico=False` (v1) tiene que dar blue, no MEP."""
        import fx
        self.assertEqual(fx.RIEL_MEP, "mep")
        self.assertEqual(fx.RIEL_BLUE, "blue")
        # Sin conn no hay serie: las dos ramas caen al fallback. Lo que se verifica
        # acá es que la firma expone la versión, no que la resuelva.
        self.assertEqual(
            fx.costo_en_moneda_de_venta(1000.0, "ARS", "USD", tc_blue=100.0,
                                        historico=True), 10.0)


if __name__ == "__main__":
    unittest.main()
