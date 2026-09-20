"""F3 de la tanda del asesor: la FOTO de tenencia adentro de la fila, por HTTP.

La tanda no tiene endpoint propio para esto: usa /classify-tenencia (separar la
foto de los movimientos), /imports/preview + /confirm (movimientos), después
/imports/tenencia/preview (comparar) y /confirm con `aprobar_tickers` (aplicar).
Lo que se certifica: todo eso corre a nombre del CLIENTE (header), la foto
crea su lote en la cuenta del cliente y no del asesor, y lo dudoso no entra si
no se nombra (fail-closed).
"""
import io, os, sys, unittest, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_HDR = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;instrumento;moneda;"
        "mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total")
_MOV = ("\n".join([_HDR,
    "1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;100.000;0;0;0;0;100.000",
    "3;4;16-01-2024;16-01-2024;Compra;BONO AL30 (AL30);ARS;BYMA;100;500;50.000;0;0;0;0;-50.000"]) + "\n").encode()
_FOTO = ("instrumento;cantidad;precio;moneda;total\n"
         "BONO AL30 (AL30);100;600;ARS;60000\n"
         "GRUPO FINANCIERO GALICIA S.A ESCRIT.  B  1 V (GGAL);50;7715;ARS;385750\n"
         "ARS;50000;1;ARS;50000\n").encode()


class TandaFotoTest(unittest.TestCase):
    def setUp(self):
        conn = main.get_db(); tag = uuid.uuid4().hex[:10]
        self.advisor = conn.execute("INSERT INTO users (email,password_hash,approved,tier) VALUES (?,?,1,'advisor')", (f"a-{tag}@t.t", "x")).lastrowid
        self.c1 = conn.execute("INSERT INTO users (email,password_hash,approved) VALUES (?,?,0)", (f"c-{tag}@t.t", "x")).lastrowid
        conn.execute("UPDATE users SET managed_by=? WHERE id=?", (self.advisor, self.c1))
        conn.execute("INSERT INTO advisor_clients (advisor_uid,client_uid,link_type,permission,status,label) VALUES (?,?,'managed','read_write','active','Juan P')", (self.advisor, self.c1))
        conn.commit(); conn.close()
        self.http = TestClient(main.app)

    def tearDown(self):
        conn = main.get_db(); conn.execute("DELETE FROM advisor_clients WHERE advisor_uid=?", (self.advisor,)); conn.commit(); conn.close()

    def _h(self, client=None):
        h = {"Authorization": f"Bearer {main.create_token(self.advisor)}"}
        if client is not None: h["X-Rendi-Client-Id"] = str(client)
        return h

    def _batches(self, uid):
        conn = main.get_db()
        try: return conn.execute("SELECT id, status FROM import_batches WHERE user_id=? ORDER BY rowid", (uid,)).fetchall()
        finally: conn.close()

    def test_foto_en_la_fila_de_punta_a_punta(self):
        # 1) el clasificador aparta la foto de los movimientos (mismo header de cliente)
        cls = self.http.post("/api/imports/classify-tenencia",
                             files=[("files", ("mov.csv", io.BytesIO(_MOV), "text/csv")), ("files", ("portfolio_report_20240120.csv", io.BytesIO(_FOTO), "text/csv"))],
                             headers=self._h(self.c1))
        self.assertEqual(cls.status_code, 200, cls.text)
        self.assertEqual((cls.json()["file_name"], cls.json()["format"]), ("portfolio_report_20240120.csv", "cocos"))
        # 2) movimientos
        p = self.http.post("/api/imports/preview", files=[("files", ("mov.csv", io.BytesIO(_MOV), "text/csv"))], data={"format": "cocos"}, headers=self._h(self.c1))
        self.assertEqual(p.status_code, 200, p.text)
        c = self.http.post("/api/imports/confirm", json={"session_id": p.json()["session_id"], "skip_row_indices": [], "aprobar_tickers": []}, headers=self._h(self.c1))
        self.assertEqual(c.status_code, 200, c.text)
        # 3) la foto se compara contra lo importado, A NOMBRE DEL CLIENTE
        tp = self.http.post("/api/imports/tenencia/preview", files=[("file", ("portfolio_report_20240120.csv", io.BytesIO(_FOTO), "text/csv"))],
                            data={"broker": "Cocos", "format": "cocos"}, headers=self._h(self.c1))
        self.assertEqual(tp.status_code, 200, tp.text)
        j = tp.json()
        self.assertTrue(j.get("session_id"), j)                       # hay algo que decidir/aplicar (GGAL falta)
        self.assertIn("GGAL", [x.get("ticker") for x in (j.get("to_seed") or [])] + [x.get("ticker") for x in (j.get("no_reconciliable") or [])])
        self.assertEqual(self._batches(self.advisor), [])              # nada en la cuenta del asesor
        self.assertEqual([b["status"] for b in self._batches(self.c1)], ["confirmed", "preview"])
        # 4) aplicar: sin aprobar nada, lo marcado "requiere aprobación" no entra
        c2 = self.http.post("/api/imports/confirm", json={"session_id": j["session_id"], "skip_row_indices": [], "aprobar_tickers": []}, headers=self._h(self.c1))
        self.assertEqual(c2.status_code, 200, c2.text)
        self.assertEqual([b["status"] for b in self._batches(self.c1)], ["confirmed", "confirmed"])
        conn = main.get_db()
        try:
            tickers = {r["asset"] for r in conn.execute("SELECT asset FROM positions WHERE user_id=? AND is_cash=0", (self.c1,)).fetchall()}
        finally:
            conn.close()
        self.assertIn("AL30", tickers)
        # GGAL entra sólo si NO requería aprobación (gap-fill limpio) — si la
        # requería y no se nombró, tiene que quedar afuera. Lo que no puede pasar
        # es que un "requiere aprobación" entre sin aprobarse:
        requiere = {x.get("ticker") for x in (j.get("no_reconciliable") or []) if x.get("requiere_aprobacion")}
        for tk in requiere:
            self.assertNotIn(tk, tickers, f"{tk} requería aprobación y entró igual")

    def test_solo_lectura_no_puede_comparar_la_foto(self):
        conn = main.get_db(); conn.execute("UPDATE advisor_clients SET permission='read' WHERE advisor_uid=?", (self.advisor,)); conn.commit(); conn.close()
        tp = self.http.post("/api/imports/tenencia/preview", files=[("file", ("portfolio_report_20240120.csv", io.BytesIO(_FOTO), "text/csv"))],
                            data={"broker": "Cocos", "format": "cocos"}, headers=self._h(self.c1))
        self.assertEqual(tp.status_code, 403, tp.text)
        self.assertEqual(self._batches(self.c1), [])


if __name__ == "__main__":
    unittest.main()
