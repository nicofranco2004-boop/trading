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
         "BONO AL30 (AL30);200;600;ARS;120000\n"
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
        conn = main.get_db()
        try:
            al30_antes = float(conn.execute("SELECT SUM(quantity) FROM positions WHERE user_id=? AND asset='AL30'", (self.c1,)).fetchone()[0] or 0)
        finally:
            conn.close()
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
        # La aserción de arriba era VACÍA con la foto anterior (AL30 100 = 100 →
        # nada que aprobar). Con AL30 200 contra 100 en Rendi, el bono amortizante
        # con hueco SÍ queda marcado — y tiene que quedar afuera sin aprobarlo.
        self.assertIn("AL30", requiere, j)
        conn = main.get_db()
        try:
            al30 = conn.execute("SELECT SUM(quantity) FROM positions WHERE user_id=? AND asset='AL30'", (self.c1,)).fetchone()[0]
        finally:
            conn.close()
        self.assertAlmostEqual(float(al30 or 0), al30_antes, places=3, msg="AL30 requería aprobación y entró igual")
        # El ajuste de caja YA NO es invisible: la respuesta lo trae.
        self.assertIn("cash_ajustes", j)

    def test_dos_fotos_en_la_fila_se_ven_las_dos(self):
        cls = self.http.post("/api/imports/classify-tenencia",
                             files=[("files", ("a.csv", io.BytesIO(_FOTO), "text/csv")), ("files", ("b.csv", io.BytesIO(_FOTO), "text/csv"))],
                             headers=self._h(self.c1))
        self.assertEqual(cls.status_code, 200, cls.text)
        self.assertEqual([x["file_name"] for x in cls.json()["files"]], ["a.csv", "b.csv"])
        self.assertEqual(cls.json()["file_name"], "a.csv")   # compat con el asistente

    def test_deshacer_la_tanda_tambien_revierte_la_foto(self):
        # tanda → movimientos con tanda_id → foto con tanda_id → aplicar → revert
        t = self.http.post("/api/advisor/tandas", json={"rows": [{"id": 1, "client_uid": self.c1, "label": "Juan P", "platform": "cocos", "archivos": ["mov.csv"], "estado": "pendiente"}]}, headers=self._h())
        self.assertEqual(t.status_code, 200, t.text); tid = t.json()["id"]
        p = self.http.post("/api/imports/preview", files=[("files", ("mov.csv", io.BytesIO(_MOV), "text/csv"))],
                           data={"format": "cocos", "tanda_id": tid}, headers=self._h(self.c1))
        self.assertEqual(p.status_code, 200, p.text)
        c = self.http.post("/api/imports/confirm", json={"session_id": p.json()["session_id"], "skip_row_indices": [], "aprobar_tickers": []}, headers=self._h(self.c1))
        self.assertEqual(c.status_code, 200, c.text)
        tp = self.http.post("/api/imports/tenencia/preview", files=[("file", ("portfolio_report_20240120.csv", io.BytesIO(_FOTO), "text/csv"))],
                            data={"broker": "Cocos", "format": "cocos", "tanda_id": tid}, headers=self._h(self.c1))
        self.assertEqual(tp.status_code, 200, tp.text)
        sid = tp.json()["session_id"]
        c2 = self.http.post("/api/imports/confirm", json={"session_id": sid, "skip_row_indices": [], "aprobar_tickers": []}, headers=self._h(self.c1))
        self.assertEqual(c2.status_code, 200, c2.text)
        conn = main.get_db()
        try:
            self.assertEqual({r["tanda_id"] for r in conn.execute("SELECT tanda_id FROM import_batches WHERE user_id=?", (self.c1,))}, {tid})
            self.assertIn("GGAL", {r["asset"] for r in conn.execute("SELECT asset FROM positions WHERE user_id=? AND is_cash=0", (self.c1,))})
        finally:
            conn.close()
        rv = self.http.post(f"/api/advisor/tandas/{tid}/revert", headers=self._h())
        self.assertEqual(rv.status_code, 200, rv.text)
        self.assertEqual(rv.json()["fallidos"], 0, rv.json())
        self.assertEqual(rv.json()["revertidos"], 2, rv.json())   # la foto Y los movimientos
        conn = main.get_db()
        try:
            self.assertEqual([r["status"] for r in conn.execute("SELECT status FROM import_batches WHERE user_id=?", (self.c1,))], ["reverted", "reverted"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM positions WHERE user_id=? AND is_cash=0 AND quantity>0", (self.c1,)).fetchone()[0], 0)
        finally:
            conn.close()

    def test_el_borrador_de_la_foto_no_se_aplica_si_los_movimientos_se_revirtieron(self):
        t = self.http.post("/api/advisor/tandas", json={"rows": [{"id": 1, "client_uid": self.c1, "label": "Juan P", "platform": "cocos", "archivos": ["mov.csv"], "estado": "pendiente"}]}, headers=self._h())
        tid = t.json()["id"]
        p = self.http.post("/api/imports/preview", files=[("files", ("mov.csv", io.BytesIO(_MOV), "text/csv"))], data={"format": "cocos", "tanda_id": tid}, headers=self._h(self.c1))
        self.http.post("/api/imports/confirm", json={"session_id": p.json()["session_id"], "skip_row_indices": [], "aprobar_tickers": []}, headers=self._h(self.c1))
        tp = self.http.post("/api/imports/tenencia/preview", files=[("file", ("portfolio_report_20240120.csv", io.BytesIO(_FOTO), "text/csv"))],
                            data={"broker": "Cocos", "format": "cocos", "tanda_id": tid}, headers=self._h(self.c1))
        sid = tp.json()["session_id"]; self.assertTrue(sid)
        # Deshacer la tanda: el borrador de la foto se borra en la misma pasada
        rv = self.http.post(f"/api/advisor/tandas/{tid}/revert", headers=self._h())
        self.assertEqual(rv.status_code, 200, rv.text)
        c2 = self.http.post("/api/imports/confirm", json={"session_id": sid, "skip_row_indices": [], "aprobar_tickers": ["GGAL"]}, headers=self._h(self.c1))
        self.assertEqual(c2.status_code, 400, c2.text)
        conn = main.get_db()
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM positions WHERE user_id=? AND is_cash=0 AND quantity>0", (self.c1,)).fetchone()[0], 0)
        finally:
            conn.close()

    def test_un_borrador_de_foto_no_se_aplica_si_se_revirtio_desde_la_cuenta_del_cliente(self):
        # Sin tanda: el revert individual de los movimientos también invalida el borrador
        p = self.http.post("/api/imports/preview", files=[("files", ("mov.csv", io.BytesIO(_MOV), "text/csv"))], data={"format": "cocos"}, headers=self._h(self.c1))
        bid = p.json()["session_id"]
        self.http.post("/api/imports/confirm", json={"session_id": bid, "skip_row_indices": [], "aprobar_tickers": []}, headers=self._h(self.c1))
        tp = self.http.post("/api/imports/tenencia/preview", files=[("file", ("portfolio_report_20240120.csv", io.BytesIO(_FOTO), "text/csv"))],
                            data={"broker": "Cocos", "format": "cocos"}, headers=self._h(self.c1))
        sid = tp.json()["session_id"]; self.assertTrue(sid)
        rv = self.http.post(f"/api/imports/{bid}/revert", headers=self._h(self.c1))
        self.assertEqual(rv.status_code, 200, rv.text)
        c2 = self.http.post("/api/imports/confirm", json={"session_id": sid, "skip_row_indices": [], "aprobar_tickers": ["GGAL"]}, headers=self._h(self.c1))
        self.assertEqual(c2.status_code, 400, c2.text)
        self.assertIn("revirti", c2.text)

    def test_tanda_ajena_en_la_foto_es_400_sin_lote(self):
        tp = self.http.post("/api/imports/tenencia/preview", files=[("file", ("portfolio_report_20240120.csv", io.BytesIO(_FOTO), "text/csv"))],
                            data={"broker": "Cocos", "format": "cocos", "tanda_id": "no-existe"}, headers=self._h(self.c1))
        self.assertEqual(tp.status_code, 400, tp.text)
        self.assertEqual(self._batches(self.c1), [])

    def test_solo_lectura_no_puede_comparar_la_foto(self):
        conn = main.get_db(); conn.execute("UPDATE advisor_clients SET permission='read' WHERE advisor_uid=?", (self.advisor,)); conn.commit(); conn.close()
        tp = self.http.post("/api/imports/tenencia/preview", files=[("file", ("portfolio_report_20240120.csv", io.BytesIO(_FOTO), "text/csv"))],
                            data={"broker": "Cocos", "format": "cocos"}, headers=self._h(self.c1))
        self.assertEqual(tp.status_code, 403, tp.text)
        self.assertEqual(self._batches(self.c1), [])


if __name__ == "__main__":
    unittest.main()
