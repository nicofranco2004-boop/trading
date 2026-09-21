"""El revert SEGURO de un lote pregunta si hubo VENTAS después, no las adivina.

Historia del chequeo (persister.revert_batch, pre-check 2):
  · v1 comparaba `positions.quantity` contra la cantidad comprada. Con bonos
    amortizantes (AL30/GD30) `positions.quantity` guarda el nominal RESIDUAL
    que deja `sweep_bond_amortizations`, así que TODA cartera con soberanos
    daba "parcialmente vendida" sin venta alguna: no se podía revertir nada.
  · v2 escalaba la cantidad comprada por `residual_factor(hoy)`. Cerró el
    rechazo falso y abrió el contrario: si entre el import y el revert cayó
    una cuota, la posición quedó con el factor del último sweep y el chequeo
    usaba el de hoy → una venta chica (menor a esa diferencia) pasaba, el
    revert borraba la posición y la venta quedaba huérfana en `operations`.
  · v3 (esta) busca la fila 'Venta' en `operations` fuera del lote. Es la
    pregunta directa; no depende de ninguna escala.

Los tres casos de abajo son los que discriminan entre las tres versiones:
  1. AL30 sin venta → revert 200 (v1 lo rechazaba).
  2. AL30 con venta manual DESPUÉS del import → revert 400 (v1 y v3 lo
     rechazan; v2 sólo si la venta supera la amortización acumulada).
  3. El hueco de v2, forzado: la posición con MÁS nominal del que dice el
     factor de hoy (como si el sweep hubiera corrido con una cuota menos) y
     una venta chica → revert 400. v2 lo dejaba pasar.
  4. GGAL (no amortizante) con venta → 400, como siempre.
Y el caso de control: AL30 con venta en el MISMO lote lo frena el pre-check 1
("incluye ventas"), no este.
"""
import io
import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_H = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;instrumento;"
      "moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total")
_DEP = "1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;1.000.000;0;0;0;0;1.000.000"
_AL30 = "3;4;16-01-2024;16-01-2024;Compra;BONO AL30 (AL30);ARS;BYMA;100;500;50.000;0;0;0;0;-50.000"
_GGAL = ("5;6;16-01-2024;16-01-2024;Compra;GRUPO FINANCIERO GALICIA S.A ESCRIT.  B  1 V (GGAL);"
         "ARS;BYMA;50;7000;350.000;0;0;0;0;-350.000")
_AL30_SELL = "7;8;17-01-2024;17-01-2024;Venta;BONO AL30 (AL30);ARS;BYMA;40;510;20.400;0;0;0;0;20.400"


def _csv(*rows):
    return ("\n".join([_H] + list(rows)) + "\n").encode()


class RevertVentaPosteriorTest(unittest.TestCase):

    def setUp(self):
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"rv-{uuid.uuid4().hex[:10]}@rendi.test", "x")).lastrowid
        conn.commit(); conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.http = TestClient(main.app)

    def _import(self, data):
        p = self.http.post("/api/imports/preview",
                           files=[("files", ("mov.csv", io.BytesIO(data), "text/csv"))],
                           data={"format": "cocos"}, headers=self.h)
        self.assertEqual(p.status_code, 200, p.text)
        sid = p.json()["session_id"]
        c = self.http.post("/api/imports/confirm",
                           json={"session_id": sid, "skip_row_indices": [], "aprobar_tickers": []},
                           headers=self.h)
        self.assertEqual(c.status_code, 200, c.text)
        return sid

    def _sell(self, asset, qty, price):
        r = self.http.post("/api/positions/sell",
                           json={"broker": "Cocos", "asset": asset, "quantity": qty,
                                 "exit_price": price, "date": "2026-09-01", "currency": "ARS"},
                           headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def _revert(self, sid):
        return self.http.post(f"/api/imports/{sid}/revert", headers=self.h)

    def _qty(self, asset):
        conn = main.get_db()
        try:
            r = conn.execute("SELECT quantity FROM positions WHERE user_id=? AND asset=? AND is_cash=0",
                             (self.uid, asset)).fetchone()
            return float(r["quantity"]) if r else None
        finally:
            conn.close()

    def test_bono_amortizante_sin_venta_se_revierte(self):
        sid = self._import(_csv(_DEP, _AL30, _GGAL))
        # el sweep deja el nominal residual (< 100): la v1 leía eso como venta
        self.assertLess(self._qty("AL30") or 0, 100.0)
        rv = self._revert(sid)
        self.assertEqual(rv.status_code, 200, rv.text)
        self.assertIsNone(self._qty("AL30"))

    def test_venta_manual_posterior_frena_el_revert(self):
        sid = self._import(_csv(_DEP, _AL30, _GGAL))
        self._sell("AL30", 10, 600)
        rv = self._revert(sid)
        self.assertEqual(rv.status_code, 400, rv.text)
        self.assertIn("vendida", rv.json()["detail"])

    def test_el_hueco_del_factor_de_hoy_ya_no_pasa(self):
        sid = self._import(_csv(_DEP, _AL30, _GGAL))
        # Como si el último sweep hubiera corrido con una cuota menos: la
        # posición tiene MÁS nominal del que el factor de hoy le asigna.
        conn = main.get_db()
        conn.execute("UPDATE positions SET quantity = quantity + 8 WHERE user_id=? AND asset='AL30' AND is_cash=0",
                     (self.uid,))
        conn.commit(); conn.close()
        self._sell("AL30", 0.5, 600)          # venta chica, menor a la "cuota"
        rv = self._revert(sid)
        self.assertEqual(rv.status_code, 400, rv.text)
        # y la venta sigue ahí, con su posición: nada quedó huérfano
        self.assertIsNotNone(self._qty("AL30"))

    def test_accion_comun_con_venta_frena_el_revert(self):
        sid = self._import(_csv(_DEP, _AL30, _GGAL))
        self._sell("GGAL", 10, 8000)
        rv = self._revert(sid)
        self.assertEqual(rv.status_code, 400, rv.text)

    def test_venta_en_el_mismo_lote_la_frena_el_precheck_uno(self):
        sid = self._import(_csv(_DEP, _AL30, _AL30_SELL))
        rv = self._revert(sid)
        self.assertEqual(rv.status_code, 400, rv.text)
        self.assertIn("ventas", rv.json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
