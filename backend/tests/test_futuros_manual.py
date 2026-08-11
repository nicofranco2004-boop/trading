"""Cargar a mano el resultado de un futuro cerrado.

REPORTE REAL (2026-08-11): un usuario cerró un futuro de BTC con +47 USDT de
ganancia. Buscó dónde cargarlo, no encontró una opción de futuros, y terminó
registrando SOLO el P&L. Resultado: el P&L quedó bien, pero su efectivo quedó
47 dólares corto — la plata está en Binance y Rendi no la veía.

Y la salida obvia era peor. Medido antes de este fix:

    solo P&L           cash=500  P&L=+47  aportado= 0  capital del mes=+47  ✓
    P&L + un depósito  cash=547  P&L=+47  aportado=47  capital del mes=+94  ✗

El depósito mete el resultado DOS VECES en el capital y ensucia el capital
aportado, que es el denominador del rendimiento: quedaría como si hubiera
puesto 47 dólares que en realidad ganó.

Lo llamativo es que el motor correcto ya existía: el import de Binance produce
FUTURES_PNL y `persister._persist_futures_pnl` acredita el efectivo desde
siempre. Lo que faltaba era poder invocarlo a mano.
"""
import unittest
import uuid

import main


def _cliente():
    from fastapi.testclient import TestClient
    return TestClient(main.app)


class FuturosManualTest(unittest.TestCase):
    CASH_INICIAL = 500.0

    def setUp(self):
        self.client = _cliente()
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
            (f"fut-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,'Binance','USDT')",
                     (self.uid,))
        conn.execute("""INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity)
                        VALUES (?,'Binance','USDT',1,?,?)""",
                     (self.uid, self.CASH_INICIAL, self.CASH_INICIAL))
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,'Bybit','USDT')",
                     (self.uid,))
        conn.execute("""INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity)
                        VALUES (?,'Bybit','USDT',1,0,0)""", (self.uid,))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    # ── helpers ──────────────────────────────────────────────────────────────

    def _cash(self, broker="Binance"):
        conn = main.get_db()
        r = conn.execute(
            "SELECT COALESCE(invested,0) c FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
            (self.uid, broker)).fetchone()
        conn.close()
        return float(r["c"]) if r else 0.0

    def _pnl_realizado(self):
        conn = main.get_db()
        r = conn.execute(
            "SELECT COALESCE(SUM(pnl_realized),0) p FROM monthly_entries "
            " WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()
        conn.close()
        return float(r["p"])

    def _aportado(self):
        conn = main.get_db()
        r = conn.execute(
            "SELECT COALESCE(SUM(deposits),0) d FROM monthly_entries "
            " WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()
        conn.close()
        return float(r["d"])

    def _cargar(self, pnl=47, kind="futures", broker="Binance", asset="BTCUSDT"):
        r = self.client.post("/api/operations", headers=self.h, json={
            "date": "2026-08-11", "broker": broker, "asset": asset,
            "op_type": "Futuros", "entry_price": None, "exit_price": None,
            "quantity": None, "pnl_usd": pnl, "pnl_pct": None,
            "commissions": 0, "currency": "USDT", "kind": kind,
        })
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ── el caso del usuario ──────────────────────────────────────────────────

    def test_una_ganancia_de_futuros_suma_al_efectivo_y_al_pnl(self):
        self._cargar(47)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL + 47, places=2)
        self.assertAlmostEqual(self._pnl_realizado(), 47, places=2)

    def test_y_NO_ensucia_el_capital_aportado(self):
        """Lo que hacía mal el workaround del depósito. El aportado es el
        denominador del rendimiento: si sube, la ganancia se diluye sola."""
        self._cargar(47)
        self.assertAlmostEqual(self._aportado(), 0, places=2)

    def test_una_perdida_DESCUENTA_del_efectivo(self):
        self._cargar(-30)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL - 30, places=2)
        self.assertAlmostEqual(self._pnl_realizado(), -30, places=2)

    # ── el comportamiento viejo no se movió ──────────────────────────────────

    def test_sin_kind_sigue_siendo_solo_PL_y_NO_toca_el_efectivo(self):
        """Todo lo que ya existía manda `kind` vacío. Si esto cambiara, cada
        operación vieja del formulario empezaría a mover plata."""
        self._cargar(47, kind=None)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL, places=2)
        self.assertAlmostEqual(self._pnl_realizado(), 47, places=2)

    def test_el_texto_libre_del_tipo_NO_mueve_plata(self):
        """El campo "Tipo" es libre y su placeholder sugiere "Futuros". Escribirlo
        no puede acreditar efectivo: si se dedujera de ahí, una grafía movería
        plata y otra no."""
        for texto in ("Futuros", "FUTUROS", "futuro", "LONG"):
            antes = self._cash()
            self._cargar(10, kind=None, asset=f"X{texto}")
            self.assertAlmostEqual(self._cash(), antes, places=2,
                                   msg=f'op_type="{texto}" movió el efectivo')

    # ── borrado y deshacer ───────────────────────────────────────────────────

    def test_borrarla_devuelve_el_efectivo(self):
        op = self._cargar(47)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL + 47, places=2)
        r = self.client.delete(f"/api/operations/{op['id']}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL, places=2)
        self.assertAlmostEqual(self._pnl_realizado(), 0, places=2)

    def test_borrar_una_PERDIDA_tambien_revierte(self):
        op = self._cargar(-30)
        r = self.client.delete(f"/api/operations/{op['id']}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL, places=2)

    def test_deshacer_el_borrado_vuelve_a_acreditar(self):
        op = self._cargar(47)
        r = self.client.delete(f"/api/operations/{op['id']}", headers=self.h)
        token = r.json()["undo_token"]
        r2 = self.client.post(f"/api/operations/undo/{token}", headers=self.h)
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL + 47, places=2)
        self.assertAlmostEqual(self._pnl_realizado(), 47, places=2)

    def _id_viva(self):
        """El undo re-inserta la operación con un id NUEVO (la fila se re-crea, no
        se resucita la original), así que para el segundo borrado hay que releerlo."""
        conn = main.get_db()
        r = conn.execute("SELECT id FROM operations WHERE user_id=? ORDER BY id DESC LIMIT 1",
                         (self.uid,)).fetchone()
        conn.close()
        return r["id"] if r else None

    def test_el_ciclo_completo_no_deja_deriva(self):
        """alta → borrar → deshacer → borrar. Tiene que cerrar en el saldo inicial:
        es donde se ven los errores de signo, que dejan plata fabricada."""
        op = self._cargar(47)
        r = self.client.delete(f"/api/operations/{op['id']}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        r2 = self.client.post(f"/api/operations/undo/{r.json()['undo_token']}", headers=self.h)
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL + 47, places=2)

        r3 = self.client.delete(f"/api/operations/{self._id_viva()}", headers=self.h)
        self.assertEqual(r3.status_code, 200, r3.text)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL, places=2)
        self.assertAlmostEqual(self._pnl_realizado(), 0, places=2)

    # ── edición ──────────────────────────────────────────────────────────────

    def _editar(self, oid, pnl, broker="Binance"):
        r = self.client.put(f"/api/operations/{oid}", headers=self.h, json={
            "date": "2026-08-11", "broker": broker, "asset": "BTCUSDT",
            "op_type": "Futuros", "entry_price": None, "exit_price": None,
            "quantity": None, "pnl_usd": pnl, "pnl_pct": None,
            "commissions": 0, "currency": "USDT",
        })
        self.assertEqual(r.status_code, 200, r.text)

    def test_editar_el_resultado_mueve_el_efectivo_por_la_diferencia(self):
        op = self._cargar(47)
        self._editar(op["id"], 100)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL + 100, places=2)

    def test_y_despues_de_editar_el_borrado_devuelve_el_monto_NUEVO(self):
        """Si la foto de reverso no se actualizara, borrar devolvería los 47
        viejos y quedarían 53 dólares fabricados en la cuenta."""
        op = self._cargar(47)
        self._editar(op["id"], 100)
        r = self.client.delete(f"/api/operations/{op['id']}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL, places=2)

    def test_mover_la_operacion_de_broker_mueve_la_plata(self):
        op = self._cargar(47)
        self._editar(op["id"], 47, broker="Bybit")
        self.assertAlmostEqual(self._cash("Binance"), self.CASH_INICIAL, places=2)
        self.assertAlmostEqual(self._cash("Bybit"), 47, places=2)

    def test_editar_una_operacion_COMUN_sigue_sin_tocar_el_efectivo(self):
        op = self._cargar(47, kind=None)
        self._editar(op["id"], 100)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL, places=2)


if __name__ == "__main__":
    unittest.main()
