"""El interruptor del aviso «Ajustar» nuevo (`aviso_ratio_nuevo`).

El aviso nuevo de cambio de ratio (la lista única, cambios_ratio.py) llegó a
producción sin que nadie lo prendiera. Nico pidió que quede APAGADO hasta
revisar la lista y medir cuánta gente lo vería, con un botón en /admin.

  · APAGADO (de entrada) = producción hasta el 22/10/2026 (24dadbd5): el aviso
    ofrece lo que anota Yahoo para la especie en pesos —aunque la lista diga
    otra cosa—, siempre con evidencia 'fecha', y la foto de tenencia siembra el
    hueco entero como compra al precio del día.
  · ENCENDIDO = la lista (las pruebas de tests/test_cambios_ratio.py).
  · El botón lo toca sólo un admin y queda guardado en la base.

Entra por el camino de producción: lotes en la base, /split-check, /adjust-ratio
y los imports por HTTP. Lo único reemplazado es la respuesta de Yahoo
(`main._splits_de_yahoo`), con lo que Yahoo anota de verdad (medido el
22/10/2026): nada para XLE.BA, 1:3 para DDD.BA, ×10 para NVDA.BA.

Corre con: cd backend && python3 -m pytest tests/test_interruptor_ratio.py
"""
import io
import os
import sys
import unittest
import uuid
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import pandas as pd
from fastapi.testclient import TestClient

import main
from tests.test_cambios_ratio import FOTO_XLE, MOV_XLE, _armar_lista, _interruptor

YAHOO = {"DDD.BA": [("2026-06-24", 1 / 3)], "NVDA.BA": [("2024-06-10", 10.0)]}


def _yahoo(sym):
    sp = YAHOO.get(sym, [])
    return pd.Series([f for _, f in sp], index=pd.to_datetime([d for d, _ in sp]), dtype=float)


class InterruptorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _armar_lista()     # la lista ARMADA: apagado, igual no se usa

    def setUp(self):
        _interruptor(False)
        main._splits_cache.clear()
        self._p = [mock.patch("main._splits_de_yahoo", _yahoo), mock.patch("main._check_rate_limit")]
        for p in self._p:
            p.start()
        self.http = TestClient(main.app)
        conn = main.get_db()
        try:
            tag = uuid.uuid4().hex[:8]
            self.uid = conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                                    (f"int-{tag}@rendi.test", "x")).lastrowid
            self.admin = conn.execute(
                "INSERT INTO users (email, password_hash, approved, is_admin) VALUES (?,?,1,1)",
                (f"int-adm-{tag}@rendi.test", "x")).lastrowid
            for b in ("IOL", "Cocos"):
                conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,'ARS')", (self.uid, b))
            conn.commit()
        finally:
            conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.h_admin = {"Authorization": f"Bearer {main.create_token(self.admin)}"}

    def tearDown(self):
        for p in self._p:
            p.stop()
        _interruptor(False)

    def _lote(self, asset, qty, precio, fecha):
        conn = main.get_db()
        try:
            pid = conn.execute(
                """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity, invested,
                       entry_date, asset_type, currency) VALUES (?,?,?,0,?,?,?,?,'CEDEAR','ARS')""",
                (self.uid, "IOL", asset, precio, qty, precio * qty, fecha)).lastrowid
            conn.commit()
            return pid
        finally:
            conn.close()

    def _aviso(self):
        r = self.http.get("/api/positions/split-check", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _boton(self, encendido, h=None):
        return self.http.post("/api/admin/cambios-ratio/interruptor", json={"encendido": encendido},
                              headers=h or self.h_admin)

    # ── Apagado = producción ────────────────────────────────────────────────

    def test_apagado_de_entrada(self):
        r = self.http.get("/api/admin/cambios-ratio", headers=self.h_admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["interruptor"]["encendido"])
        self.assertIn("XLE", {c["cedear"] for c in r.json()["lista"]}, "la lista está, para revisarla")
        self.assertFalse(self._aviso()["aviso_nuevo"])

    def test_apagado_el_aviso_es_el_de_yahoo(self):
        xle = self._lote("XLE", 10, 62925.0, "2025-10-15")    # la lista lo confirma ×2; Yahoo no anota nada
        ddd = self._lote("DDD", 10, 30000.0, "2026-01-15")    # Yahoo anota 1:3 (nadie lo confirma)
        nvda = self._lote("NVDA", 5, 9000.0, "2024-03-15")    # Yahoo anota ×10
        av = {s["pid"]: s for s in self._aviso()["suggestions"]}
        self.assertNotIn(xle, av, "apagado, la lista no ofrece nada")
        self.assertEqual((av[ddd]["factor"], av[ddd]["ex_date"], av[ddd]["evidence"]),
                         (round(1 / 3, 6), "2026-06-24", "fecha"))
        self.assertEqual((av[nvda]["factor"], av[nvda]["ex_date"], av[nvda]["evidence"]),
                         (10.0, "2024-06-10", "fecha"))
        # Y el botón «Ajustar» tampoco aplica lo de la lista.
        r = self.http.post(f"/api/positions/{xle}/adjust-ratio", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["already_applied"])

    def test_encendido_el_aviso_es_el_de_la_lista(self):
        xle = self._lote("XLE", 10, 62925.0, "2025-10-15")
        ddd = self._lote("DDD", 10, 30000.0, "2026-01-15")
        self.assertEqual(self._boton(True).status_code, 200)
        r = self._aviso()
        self.assertTrue(r["aviso_nuevo"])
        av = {s["pid"]: s for s in r["suggestions"]}
        self.assertEqual((av[xle]["factor"], av[xle]["evidence"]), (2.0, "fecha"))
        self.assertEqual(av[ddd]["evidence"], "sin_confirmar")

    def test_apagado_la_foto_siembra_como_antes(self):
        # 10 XLE comprados en octubre; la foto de hoy dice 20. Antes de la lista,
        # la foto completaba los 10 que faltan como una compra al precio del día,
        # con su aporte. Apagado, sigue así (la lista no se usa para plata).
        def imp(ruta, nombre, contenido):
            r = self.http.post(ruta, files={"file": (nombre, io.BytesIO(contenido.encode()), "text/csv")},
                               data={"broker": "Cocos", "format": "cocos"}, headers=self.h)
            self.assertEqual(r.status_code, 200, r.text)
            r = self.http.post("/api/imports/confirm", json={"session_id": r.json()["session_id"]},
                               headers=self.h)
            self.assertEqual(r.status_code, 200, r.text)
        imp("/api/imports/preview", "mov.csv", MOV_XLE)
        imp("/api/imports/tenencia/preview", "portfolio_report_20261021.csv", FOTO_XLE)
        conn = main.get_db()
        try:
            txs = [dict(r) for r in conn.execute(
                "SELECT n.operation_type, n.quantity, n.unit_price, n.gross_amount, n.notes "
                "FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id "
                "WHERE b.user_id=? AND n.notes LIKE 'Tenencia%'", (self.uid,))]
            invertido = conn.execute(
                "SELECT SUM(invested) s FROM positions WHERE user_id=? AND asset='XLE' AND is_cash=0",
                (self.uid,)).fetchone()["s"]
        finally:
            conn.close()
        compras = [t for t in txs if t["operation_type"] == "BUY"]
        self.assertEqual([(t["quantity"], t["unit_price"]) for t in compras], [(10.0, 55800.0)],
                         "el hueco entero como compra al precio del día; nada a $0")
        self.assertFalse(any("cambio de ratio" in (t["notes"] or "") for t in txs))
        self.assertAlmostEqual(invertido, 629250.0 + 558000.0)

    # ── El botón ────────────────────────────────────────────────────────────

    def test_solo_un_admin_lo_toca_y_queda_guardado(self):
        self.assertEqual(self._boton(True, h=self.h).status_code, 403)
        self.assertEqual(self.http.get("/api/admin/cambios-ratio", headers=self.h).status_code, 403)
        self.assertFalse(main.interruptor(main.AVISO_RATIO_NUEVO))
        r = self._boton(True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["encendido"])
        self.assertTrue(main.interruptor(main.AVISO_RATIO_NUEVO))
        self.assertTrue(self.http.get("/api/admin/cambios-ratio", headers=self.h_admin)
                        .json()["interruptor"]["encendido"])
        self.assertFalse(self._boton(False).json()["encendido"])
        self.assertFalse(self._aviso()["aviso_nuevo"])


if __name__ == "__main__":
    unittest.main()
