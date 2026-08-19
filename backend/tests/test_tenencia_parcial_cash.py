"""Una foto PARCIAL no puede tocar el efectivo, ni leerse como completa.

Dos cosas que se cruzan, las dos de Cocos:

1. `saw_cash_row` es la señal de "este archivo lista el efectivo" = lo leímos
   entero. Se prendía con la fila de saldo escrita como código ('USD', 'ARS')
   pero NO con la variante de nombre largo 'Dólar estadounidense ()', que el
   parser sí sumaba al cash. Un export COMPLETO cuyo único saldo viniera en esa
   forma se leía como recorte: warning, override en gap-fill, y una posición ya
   vendida se quedaba para siempre en la cartera.

2. El true-up del efectivo corría SIEMPRE, aunque la foto estuviera marcada como
   parcial. Los parsers dejan cash_ars/cash_usd en 0.0 (no None) cuando el
   archivo no trae filas de saldo → sobre un recorte, el ajuste llevaba el
   efectivo del usuario a CERO. Y en silencio: el true-up no se le muestra.

Corre con: cd backend && python3 -m pytest tests/test_tenencia_parcial_cash.py
"""
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["DB_PATH"] = _TMP.name

from fastapi.testclient import TestClient       # noqa: E402
from importing import tenencia as tn            # noqa: E402
import main                                     # noqa: E402


HDR = "Instrumento;Cantidad;Precio;Moneda;Total\n"


class SenalDeCompletitudTest(unittest.TestCase):
    """Unit del parser: qué fila cuenta como "vi el efectivo"."""

    def test_saldo_con_codigo_marca_completa(self):
        snap = tn.parse_cocos_tenencia(
            HDR + "MELI (MELI);10;100;ARS;1000\nARS;5000;1;ARS;5000\n")
        self.assertEqual(snap.warnings, [])
        self.assertEqual(snap.cash_ars, 5000)

    def test_saldo_con_nombre_largo_tambien_marca_completa(self):
        """EL bug: sumaba al cash pero no prendía la señal → foto 'parcial'."""
        snap = tn.parse_cocos_tenencia(
            HDR + "MELI (MELI);10;100;ARS;1000\nDólar estadounidense ();250;1;USD;250\n")
        self.assertEqual(snap.warnings, [], "una foto completa se leyó como recorte")
        self.assertEqual(snap.cash_usd, 250)

    def test_sin_ninguna_fila_de_saldo_sigue_siendo_parcial(self):
        """La contracara: el fix no puede volver 'completa' a cualquier cosa."""
        snap = tn.parse_cocos_tenencia(HDR + "MELI (MELI);10;100;ARS;1000\n")
        self.assertTrue(snap.warnings, "un recorte sin efectivo tiene que avisar")
        self.assertEqual(snap.cash_ars, 0.0)   # el 0.0 es justo el que NO hay que aplicar


class FotoParcialNoTocaElEfectivoTest(unittest.TestCase):
    """E2E por el endpoint real: el preview de un recorte no ajusta el cash."""

    BROKER = "Cocos"

    def setUp(self):
        self.client = TestClient(main.app)
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES ('parcial@rendi.test','x',1,1)").lastrowid
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,'ARS')",
            (self.uid, self.BROKER))
        # Efectivo real del usuario: lo que el true-up de un recorte pondría en 0.
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested, is_cash) "
            "VALUES (?,?,'ARS',1,750000,1)", (self.uid, self.BROKER))
        self.conn.commit()
        self.headers = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def _preview(self, csv_text):
        return self.client.post(
            "/api/imports/tenencia/preview",
            headers=self.headers,
            data={"broker": self.BROKER, "format": "cocos"},
            files={"file": ("portfolio_report.csv", io.BytesIO(csv_text.encode("utf-8")),
                            "text/csv")})

    def _cash(self):
        r = self.conn.execute(
            "SELECT invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
            (self.uid, self.BROKER)).fetchone()
        return float(r["invested"] or 0) if r else 0.0

    def _confirmar(self, sid):
        # El confirm de la foto es el genérico de imports (el preview es el propio).
        return self.client.post("/api/imports/confirm",
                                headers=self.headers, json={"session_id": sid})

    def test_un_recorte_no_pone_el_efectivo_en_cero(self):
        """Foto SIN filas de saldo → parcial. El efectivo del usuario no se toca."""
        r = self._preview(HDR + "MELI (MELI);10;100;ARS;1000\n")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertFalse(body.get("foto_completa", True))
        if body.get("session_id"):
            self._confirmar(body["session_id"])
        self.assertAlmostEqual(self._cash(), 750000, places=2,
                               msg="un export parcial le vació el efectivo")

    def test_una_foto_completa_si_ajusta_el_efectivo(self):
        """La contracara: si la foto trae el saldo, manda ella."""
        r = self._preview(HDR + "MELI (MELI);10;100;ARS;1000\nARS;900000;1;ARS;900000\n")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body.get("foto_completa"))
        self.assertIsNotNone(body.get("session_id"), body)
        self.assertEqual(self._confirmar(body["session_id"]).status_code, 200)
        self.assertAlmostEqual(self._cash(), 900000, places=2)


if __name__ == "__main__":
    unittest.main()
