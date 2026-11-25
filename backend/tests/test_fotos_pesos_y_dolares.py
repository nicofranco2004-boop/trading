"""Un mismo CEDEAR comprado en pesos Y en dólares no hace estallar las fotos.

Caso real (25/11/2026): una cuenta de Cocos con TSLA comprado muchas veces en
pesos y una vez con «Compra Dolar Mep». La reconstrucción de la historia a mercado
(`scripts/backfill_historical_mtm.py`) sumaba el costo en pesos y el costo en
dólares en UN monto y lo etiquetaba 'USD' si alguna compra había sido en dólares:
la foto del 31/10 tomó 1.304.277 PESOS como dólares. El tablero comparó el valor
de hoy (US$ 5.960) contra esa foto y mostró −99,6 % en «Últimos 25 días» y
«Este mes».

Por el camino de producción: el archivo de Cocos por /api/imports/preview y
/confirm, la reconstrucción que dispara el confirm, y las fotos por /api/snapshots.
Los precios históricos se apagan (`_fetch_monthly_close` → nada): es justo el
camino que falló, el que valúa al COSTO cuando no hay precio o no se confía en él.

Corre con: cd backend && python3 -m pytest tests/test_fotos_pesos_y_dolares.py
"""
import io
import json
import os
import sys
import time
import unittest
import uuid
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")
import main  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_HDR = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;instrumento;moneda;"
        "mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total")
_TSLA = "CEDEAR TESLA, INC. (TSLA)"
_FILAS = [
    "1;1;03-08-2026;03-08-2026;Recibo De Cobro;;ARS;;;;1.000.000;0;0;0;0;1.000.000",
    # 10 en pesos a $ 30.000 = $ 300.000
    f"2;2;05-08-2026;05-08-2026;Compra;{_TSLA};ARS;BYMA;10;30.000;300.000;0;0;0;0;-300.000",
    # 10 en dólares (MEP) a US$ 25,50 = US$ 255
    f"3;3;10-09-2026;11-09-2026;Compra Dolar Mep;{_TSLA};USD;BYMA;10;25,5;-255,00;0;0;0;0;-255,00",
]
_VENTA = f"4;4;15-10-2026;15-10-2026;Venta;{_TSLA};ARS;BYMA;-5;31.000;155.000;0;0;0;0;155.000"


def _csv(*filas):
    return ("\n".join([_HDR, *filas]) + "\n").encode()


class FotosConPesosYDolares(unittest.TestCase):

    def setUp(self):
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) VALUES (?, 'x', 1, 1)",
            (f"pesos-y-dolares-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.http = TestClient(main.app)
        # Sin precios históricos: la foto valúa al costo (el camino que falló).
        self._sin_precios = mock.patch.object(bf, "_fetch_monthly_close", return_value={})
        self._sin_precios.start()

    def tearDown(self):
        self._esperar_reconstruccion()
        self._sin_precios.stop()

    def _esperar_reconstruccion(self):
        limite = time.time() + 60
        while time.time() < limite:
            with main._MTM_RUNNING_LOCK:
                if self.uid not in main._MTM_RUNNING:
                    return
            time.sleep(0.02)
        self.fail("la reconstrucción no terminó en 60 s")

    def _importar(self, contenido):
        p = self.http.post("/api/imports/preview",
                           files=[("files", ("movimientos.csv", io.BytesIO(contenido), "text/csv"))],
                           data={"format": "cocos"}, headers=self.h)
        self.assertEqual(p.status_code, 200, p.text)
        c = self.http.post("/api/imports/confirm",
                           json={"session_id": p.json()["session_id"], "skip_row_indices": [],
                                 "aprobar_tickers": []}, headers=self.h)
        self.assertEqual(c.status_code, 200, c.text)
        self._esperar_reconstruccion()

    def _foto(self, fecha):
        fotos = {f["date"]: f for f in self.http.get("/api/snapshots?days=3650", headers=self.h).json()}
        self.assertIn(fecha, fotos, f"no hay foto del {fecha}: {sorted(fotos)}")
        return fotos[fecha]

    def _tsla_en(self, fecha):
        conn = main.get_db()
        try:
            r = conn.execute("SELECT holdings_json FROM snapshots WHERE user_id=? AND date=?",
                             (self.uid, fecha)).fetchone()
        finally:
            conn.close()
        partes = [x for x in json.loads(r["holdings_json"] or "[]") if "TSLA" in str(x.get("asset"))]
        return sum(float(x.get("value_usd") or 0) for x in partes)

    # ─────────────────────────────────────────────────────────────────────────
    def test_la_foto_no_toma_los_pesos_como_dolares(self):
        self._importar(_csv(*_FILAS))
        for fecha in ("2026-09-30", "2026-10-31"):
            foto = self._foto(fecha)
            # Lo aportado son $ 1.000.000 (unos US$ 700): una foto de cientos de
            # miles de dólares es la de los pesos tomados como dólares.
            self.assertLess(foto["total_value"], 3 * max(foto["net_deposited"], 1.0),
                            f"{fecha}: la foto vale {foto['total_value']:.0f} con "
                            f"{foto['net_deposited']:.0f} aportados")
            # TSLA, al costo: $ 300.000 al dólar del mes (cientos de dólares) + US$ 255.
            tsla = self._tsla_en(fecha)
            self.assertGreater(tsla, 255, fecha)
            self.assertLess(tsla, 1000, f"{fecha}: TSLA vale {tsla:.0f} en la foto")

    def test_la_tenencia_del_mes_lleva_cada_costo_en_su_moneda(self):
        self._importar(_csv(*_FILAS))
        conn = main.get_db()
        try:
            partes = {h["currency"]: h for h in bf._holdings_asof(conn, self.uid, "2026-09-30")
                      if "TSLA" in h["asset"]}
        finally:
            conn.close()
        self.assertEqual(set(partes), {"ARS", "USD"}, partes)
        self.assertAlmostEqual(partes["ARS"]["quantity"], 10)
        self.assertAlmostEqual(partes["ARS"]["invested"], 300000, places=0)
        self.assertAlmostEqual(partes["USD"]["quantity"], 10)
        self.assertAlmostEqual(partes["USD"]["invested"], 255, places=2)

    def test_una_venta_baja_la_tenencia_y_el_costo_queda_en_su_unidad(self):
        self._importar(_csv(*_FILAS, _VENTA))
        conn = main.get_db()
        try:
            partes = [h for h in bf._holdings_asof(conn, self.uid, "2026-10-31") if "TSLA" in h["asset"]]
        finally:
            conn.close()
        self.assertAlmostEqual(sum(h["quantity"] for h in partes), 15)   # 20 − 5
        for h in partes:
            precio_promedio = h["invested"] / h["quantity"]
            if h["currency"] == "USD":
                self.assertAlmostEqual(precio_promedio, 25.5, places=2)
            else:
                self.assertAlmostEqual(precio_promedio, 30000, places=0)
        self.assertLess(self._tsla_en("2026-10-31"), 1000)

    def test_lo_que_no_mezcla_monedas_queda_igual_que_antes(self):
        """Sólo pesos: una sola parte, con su moneda y su costo de siempre."""
        self._importar(_csv(_FILAS[0], _FILAS[1]))
        conn = main.get_db()
        try:
            partes = [h for h in bf._holdings_asof(conn, self.uid, "2026-08-31") if "TSLA" in h["asset"]]
        finally:
            conn.close()
        self.assertEqual(len(partes), 1)
        self.assertEqual(partes[0]["currency"], "ARS")
        self.assertAlmostEqual(partes[0]["quantity"], 10)
        self.assertAlmostEqual(partes[0]["invested"], 300000, places=0)


if __name__ == "__main__":
    unittest.main()
