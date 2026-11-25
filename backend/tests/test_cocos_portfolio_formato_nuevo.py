"""El portfolio de Cocos con el formato del 24/11/2026, por las puertas de la app.

Qué pasó: Cocos le agregó al export del portfolio tres columnas
(`precioAsOf` —en el medio, entre precio y moneda—, `usedFallbackPrice` y
`missingPrice`). Un usuario subió sus Movimientos junto con el portfolio, como pide
la guía, y el asistente le contestó «Los archivos no coinciden en formato…
tiene un header distinto al primero»: nadie reconocía el portfolio (la regla pedía
las 5 columnas EXACTAS) y se lo mandaba como si fuera otro archivo de Movimientos.

Acá se recorre lo que hace la pantalla: (1) le pregunta al servidor cuál de los
archivos es el portfolio (/classify-tenencia — la pantalla ya no tiene su propia
copia de la regla), (2) manda los Movimientos a /imports/preview + /confirm y
(3) el portfolio a /imports/tenencia/preview. Y se compara con el formato viejo:
los mismos datos tienen que dar la misma foto.

Corre con: cd backend && python3 -m pytest tests/test_cocos_portfolio_formato_nuevo.py
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

_HDR = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;instrumento;moneda;"
        "mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total")
_MOV = ("\n".join([
    _HDR,
    "1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;100.000;0;0;0;0;100.000",
    "3;4;16-01-2024;16-01-2024;Compra;BONO AL30 (AL30);ARS;BYMA;100;500;50.000;0;0;0;0;-50.000",
]) + "\n").encode()

_FILAS = [
    # (instrumento, cantidad, precio, moneda, total)
    ("BONO AL30 (AL30)", "100", "600", "ARS", "60000"),
    ("GRUPO FINANCIERO GALICIA S.A ESCRIT.  B  1 V (GGAL)", "50", "7715", "ARS", "385750"),
    ("ARS", "50000", "1", "ARS", "50000"),
]
_FOTO_VIEJA = ("instrumento;cantidad;precio;moneda;total\n" + "".join(
    f"{i};{c};{p};{m};{t}\n" for i, c, p, m, t in _FILAS)).encode()
# Como el archivo real: los activos con las 8 columnas, el efectivo con las 5 viejas.
_FOTO_NUEVA = ("instrumento;cantidad;precio;precioAsOf;moneda;total;usedFallbackPrice;missingPrice\n" + "".join(
    (f"{i};{c};{p};{m};{t}\n" if i in ("ARS", "USD") else f"{i};{c};{p};2026-11-24;{m};{t};0;0\n")
    for i, c, p, m, t in _FILAS)).encode()

_NOMBRE_FOTO = "portfolio_report_20261124.csv"


class PortfolioCocosFormatoNuevo(unittest.TestCase):

    def setUp(self):
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) VALUES (?, 'x', 1, 1)",
            (f"cocos-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.http = TestClient(main.app)

    def _clasificar(self, foto):
        r = self.http.post(
            "/api/imports/classify-tenencia",
            files=[("files", ("movimientos_cuenta-2.csv", io.BytesIO(_MOV), "text/csv")),
                   ("files", (_NOMBRE_FOTO, io.BytesIO(foto), "text/csv"))],
            headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _importar_movimientos(self):
        p = self.http.post("/api/imports/preview",
                           files=[("files", ("movimientos_cuenta-2.csv", io.BytesIO(_MOV), "text/csv"))],
                           data={"format": "cocos"}, headers=self.h)
        self.assertEqual(p.status_code, 200, p.text)
        c = self.http.post("/api/imports/confirm",
                           json={"session_id": p.json()["session_id"], "skip_row_indices": [], "aprobar_tickers": []},
                           headers=self.h)
        self.assertEqual(c.status_code, 200, c.text)

    def _comparar_foto(self, foto):
        r = self.http.post("/api/imports/tenencia/preview",
                           files=[("file", (_NOMBRE_FOTO, io.BytesIO(foto), "text/csv"))],
                           data={"broker": "Cocos", "format": "cocos"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_el_servidor_reconoce_el_portfolio_nuevo_entre_los_archivos(self):
        cls = self._clasificar(_FOTO_NUEVA)
        self.assertEqual((cls["file_name"], cls["format"]), (_NOMBRE_FOTO, "cocos"))
        self.assertEqual([x["file_name"] for x in cls["files"]], [_NOMBRE_FOTO],
                         "los Movimientos no pueden pasar por foto")

    def test_movimientos_y_portfolio_nuevo_de_punta_a_punta(self):
        self.assertEqual(self._clasificar(_FOTO_NUEVA)["file_name"], _NOMBRE_FOTO)
        self._importar_movimientos()
        j = self._comparar_foto(_FOTO_NUEVA)
        self.assertTrue(j.get("session_id"), j)
        # GGAL está en el portfolio y no en los Movimientos: es lo que la foto completa.
        faltan = [x.get("ticker") for x in (j.get("to_seed") or [])] + \
                 [x.get("ticker") for x in (j.get("no_reconciliable") or [])]
        self.assertIn("GGAL", faltan, j)

    def test_los_mismos_datos_en_los_dos_formatos_dan_la_misma_comparacion(self):
        self._importar_movimientos()
        vieja = self._comparar_foto(_FOTO_VIEJA)
        nueva = self._comparar_foto(_FOTO_NUEVA)
        # Precio, valor y moneda también: leer por posición tomaba la fecha
        # (precioAsOf) por la moneda y la moneda por el total → valor 0.
        campos = ("ticker", "qty", "price", "value", "currency", "type", "gap", "foto_qty", "rendi_qty")
        norm = lambda xs: sorted(tuple(str(x.get(c)) for c in campos) for x in (xs or []))
        self.assertTrue(vieja.get("to_seed"), "control: la foto vieja tiene algo que completar")
        self.assertTrue(any(float(x.get("value") or 0) > 0 for x in vieja["to_seed"]), "control: con valor")
        for clave in ("matched", "to_seed", "not_in_snapshot", "over", "no_reconciliable"):
            self.assertEqual(norm(vieja.get(clave)), norm(nueva.get(clave)), clave)
        self.assertEqual(vieja.get("cash_ajustes"), nueva.get("cash_ajustes"))
        # Con el efectivo a la vista, las dos son fotos COMPLETAS (sin eso no se
        # ajusta la caja ni se da por vendido lo que ya no está).
        self.assertTrue(vieja.get("foto_completa"), vieja.get("warnings"))
        self.assertEqual(vieja.get("foto_completa"), nueva.get("foto_completa"), nueva.get("warnings"))

    def test_subidos_juntos_al_paso_de_movimientos_el_aviso_nombra_el_portfolio(self):
        """Si igual llegan juntos a /imports/preview (una pantalla vieja en caché),
        el error dice qué hacer con el portfolio en vez de sólo «header distinto»."""
        r = self.http.post("/api/imports/preview",
                           files=[("files", ("movimientos_cuenta-2.csv", io.BytesIO(_MOV), "text/csv")),
                                  ("files", (_NOMBRE_FOTO, io.BytesIO(_FOTO_NUEVA), "text/csv"))],
                           data={"format": "cocos"}, headers=self.h)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("Estado de Cuenta (Portfolio) de Cocos", r.text)


if __name__ == "__main__":
    unittest.main()
