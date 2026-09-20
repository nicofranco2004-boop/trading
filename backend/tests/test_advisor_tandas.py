"""Tandas de importación del asesor (Fase 2) — por el camino HTTP real.

Certifica: crear/listar/detalle/patch; que el preview estampa `tanda_id` en el
lote SÓLO si la tanda es del asesor autenticado; que "deshacer toda la tanda"
revierte cada lote en la cuenta de SU cliente respetando el vínculo (sólo
lectura → se informa, no se toca); idempotencia; y que otro asesor no ve nada.
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


def _new_user(conn, email, tier=None, approved=1):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,?,?)",
        (email, "x", approved, tier))
    return cur.lastrowid


def _link(conn, advisor_uid, client_uid, permission="read_write", label="Cliente"):
    conn.execute(
        """INSERT INTO advisor_clients
               (advisor_uid, client_uid, link_type, permission, status, label)
           VALUES (?,?,?,?,?,?)""",
        (advisor_uid, client_uid, "managed", permission, "active", label))


_HDR = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;"
        "tipoOperacion;instrumento;moneda;mercado;cantidad;precio;"
        "montoBruto;comision;ddmm;iva;otros;total")


def _csv(*rows):
    return ("\n".join([_HDR] + list(rows)) + "\n").encode("utf-8")


class AdvisorTandasTest(unittest.TestCase):

    def setUp(self):
        conn = main.get_db()
        tag = uuid.uuid4().hex[:10]
        self.advisor = _new_user(conn, f"asesor-{tag}@rendi.test", tier="advisor")
        self.otro = _new_user(conn, f"otro-{tag}@rendi.test", tier="advisor")
        self.c1 = _new_user(conn, f"c1-{tag}@rendi.test", approved=0)
        self.c2 = _new_user(conn, f"c2-{tag}@rendi.test", approved=0)
        for c in (self.c1, self.c2):
            conn.execute("UPDATE users SET managed_by=? WHERE id=?", (self.advisor, c))
        _link(conn, self.advisor, self.c1, label="Juan P")
        _link(conn, self.advisor, self.c2, label="Ana G")
        conn.commit()
        conn.close()
        self.http = TestClient(main.app)

    def tearDown(self):
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM advisor_clients WHERE advisor_uid IN (?,?)", (self.advisor, self.otro))
            conn.execute("DELETE FROM advisor_import_tandas WHERE advisor_uid IN (?,?)", (self.advisor, self.otro))
            conn.commit()
        finally:
            conn.close()

    def _h(self, who=None, client=None):
        h = {"Authorization": f"Bearer {main.create_token(who or self.advisor)}"}
        if client is not None:
            h["X-Rendi-Client-Id"] = str(client)
        return h

    def _row(self, cid, label, estado="pendiente", **kw):
        d = {"id": cid, "client_uid": cid, "label": label, "platform": "Cocos", "archivos": ["a.csv"], "estado": estado}
        d.update(kw)
        return d

    def _preview(self, client, csv_bytes, tanda_id=None, who=None):
        data = {"format": "cocos"}
        if tanda_id:
            data["tanda_id"] = tanda_id
        return self.http.post("/api/imports/preview",
                              files=[("files", ("c.csv", io.BytesIO(csv_bytes), "text/csv"))],
                              data=data, headers=self._h(who, client))

    def _confirm(self, client, sid):
        return self.http.post("/api/imports/confirm",
                              json={"session_id": sid, "skip_row_indices": [], "aprobar_tickers": []},
                              headers=self._h(None, client))

    def _batch(self, bid):
        conn = main.get_db()
        try:
            return conn.execute("SELECT status, tanda_id FROM import_batches WHERE id=?", (bid,)).fetchone()
        finally:
            conn.close()

    # ── CRUD ────────────────────────────────────────────────────────────────

    def test_crear_listar_detalle_patch(self):
        r = self.http.post("/api/advisor/tandas", json={"rows": [self._row(self.c1, "Juan P")]}, headers=self._h())
        self.assertEqual(r.status_code, 200, r.text)
        tid = r.json()["id"]
        lst = self.http.get("/api/advisor/tandas", headers=self._h()).json()["tandas"]
        self.assertEqual([t["id"] for t in lst], [tid])
        self.assertEqual(lst[0]["resumen"]["total"], 1)
        p = self.http.patch(f"/api/advisor/tandas/{tid}",
                            json={"rows": [self._row(self.c1, "Juan P", estado="completo", cargados=7)], "finished": True},
                            headers=self._h())
        self.assertEqual(p.status_code, 200, p.text)
        d = self.http.get(f"/api/advisor/tandas/{tid}", headers=self._h()).json()
        self.assertIsNotNone(d["finished_at"])
        self.assertEqual(d["resumen"]["movimientos"], 7)
        self.assertEqual(d["rows"][0]["estado"], "completo")

    def test_validaciones_de_filas(self):
        r = self.http.post("/api/advisor/tandas", json={"rows": []}, headers=self._h())
        self.assertEqual(r.status_code, 400)
        r = self.http.post("/api/advisor/tandas", json={"rows": [self._row(self.c1, "x", estado="raro")]}, headers=self._h())
        self.assertEqual(r.status_code, 400)
        r = self.http.post("/api/advisor/tandas", json={"rows": [self._row(self.c1, "x", client_uid="abc")]}, headers=self._h())
        self.assertEqual(r.status_code, 400)
        r = self.http.post("/api/advisor/tandas", json={"rows": [self._row(i, "x") for i in range(51)]}, headers=self._h())
        self.assertEqual(r.status_code, 400)

    def test_otro_asesor_no_ve_ni_toca(self):
        tid = self.http.post("/api/advisor/tandas", json={"rows": [self._row(self.c1, "Juan P")]}, headers=self._h()).json()["id"]
        self.assertEqual(self.http.get(f"/api/advisor/tandas/{tid}", headers=self._h(self.otro)).status_code, 404)
        self.assertEqual(self.http.patch(f"/api/advisor/tandas/{tid}", json={"finished": True}, headers=self._h(self.otro)).status_code, 404)
        self.assertEqual(self.http.post(f"/api/advisor/tandas/{tid}/revert", headers=self._h(self.otro)).status_code, 404)
        self.assertEqual(self.http.get("/api/advisor/tandas", headers=self._h(self.otro)).json()["tandas"], [])

    def test_sin_plan_asesor_es_403(self):
        self.assertEqual(self.http.get("/api/advisor/tandas", headers=self._h(self.c1)).status_code, 403)

    # ── El lote queda colgado de la tanda ───────────────────────────────────

    def test_preview_estampa_tanda_id_solo_si_es_mia(self):
        tid = self.http.post("/api/advisor/tandas", json={"rows": [self._row(self.c1, "Juan P")]}, headers=self._h()).json()["id"]
        csv1 = _csv("1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;100.000;0;0;0;0;100.000")
        p = self._preview(self.c1, csv1, tanda_id=tid)
        self.assertEqual(p.status_code, 200, p.text)
        self.assertEqual(self._batch(p.json()["session_id"])["tanda_id"], tid)
        # Tanda ajena: el otro asesor no puede colgar su lote de MI tanda.
        conn = main.get_db(); _link(conn, self.otro, self.c2, label="X"); conn.commit(); conn.close()
        p2 = self._preview(self.c2, csv1, tanda_id=tid, who=self.otro)
        self.assertEqual(p2.status_code, 400, p2.text)
        # Sin tanda_id: lote suelto, como siempre.
        p3 = self._preview(self.c1, csv1)
        self.assertEqual(p3.status_code, 200)
        self.assertIsNone(self._batch(p3.json()["session_id"])["tanda_id"])

    # ── Deshacer toda la tanda ──────────────────────────────────────────────

    def _tanda_cargada(self):
        """Dos clientes, dos lotes confirmados colgados de la misma tanda."""
        tid = self.http.post("/api/advisor/tandas", json={"rows": [self._row(self.c1, "Juan P"), self._row(self.c2, "Ana G")]}, headers=self._h()).json()["id"]
        bids = {}
        for c, monto in ((self.c1, "100.000"), (self.c2, "200.000")):
            p = self._preview(c, _csv(f"1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;{monto};0;0;0;0;{monto}"), tanda_id=tid)
            self.assertEqual(p.status_code, 200, p.text)
            sid = p.json()["session_id"]
            self.assertEqual(self._confirm(c, sid).status_code, 200)
            bids[c] = sid
        rows = [self._row(self.c1, "Juan P", estado="completo", batch_id=bids[self.c1], cargados=1),
                self._row(self.c2, "Ana G", estado="completo", batch_id=bids[self.c2], cargados=1)]
        self.http.patch(f"/api/advisor/tandas/{tid}", json={"rows": rows, "finished": True}, headers=self._h())
        return tid, bids

    def test_revert_revierte_cada_lote_en_su_cliente(self):
        tid, bids = self._tanda_cargada()
        r = self.http.post(f"/api/advisor/tandas/{tid}/revert", headers=self._h())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["revertidos"], r.json()["fallidos"]), (2, 0))
        for bid in bids.values():
            self.assertEqual(self._batch(bid)["status"], "reverted")
        d = self.http.get(f"/api/advisor/tandas/{tid}", headers=self._h()).json()
        self.assertEqual({x["estado"] for x in d["rows"]}, {"revertido"})
        # Segunda vez: idempotente, nada explota, nada cambia.
        r2 = self.http.post(f"/api/advisor/tandas/{tid}/revert", headers=self._h())
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["fallidos"], 0)

    def test_revert_respeta_el_vinculo_de_solo_lectura(self):
        tid, bids = self._tanda_cargada()
        conn = main.get_db()
        conn.execute("UPDATE advisor_clients SET permission='read' WHERE advisor_uid=? AND client_uid=?", (self.advisor, self.c2))
        conn.commit(); conn.close()
        r = self.http.post(f"/api/advisor/tandas/{tid}/revert", headers=self._h())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["revertidos"], r.json()["fallidos"]), (1, 1))
        self.assertEqual(self._batch(bids[self.c1])["status"], "reverted")
        self.assertEqual(self._batch(bids[self.c2])["status"], "confirmed")   # no se tocó
        d = self.http.get(f"/api/advisor/tandas/{tid}", headers=self._h()).json()
        por = {x["label"]: x["estado"] for x in d["rows"]}
        self.assertEqual(por, {"Juan P": "revertido", "Ana G": "revert_fallo"})

    def test_revert_usa_los_lotes_estampados_aunque_el_json_no_los_tenga(self):
        """Un PATCH que llegó tarde deja la fila 'cargando' sin batch_id. El lote
        igual está estampado con tanda_id → detalle lo reconcilia y revert lo
        revierte. rows_json es lo que el front vio; import_batches es la verdad."""
        tid, bids = self._tanda_cargada()
        rows = [self._row(self.c1, "Juan P", estado="completo", batch_id=bids[self.c1], cargados=1),
                self._row(self.c2, "Ana G", estado="cargando")]          # sin batch_id
        self.http.patch(f"/api/advisor/tandas/{tid}", json={"rows": rows, "finished": True}, headers=self._h())
        d = self.http.get(f"/api/advisor/tandas/{tid}", headers=self._h()).json()
        ana = next(x for x in d["rows"] if x["label"] == "Ana G")
        self.assertEqual(ana["batch_id"], bids[self.c2])
        self.assertEqual(ana["estado"], "completo")
        r = self.http.post(f"/api/advisor/tandas/{tid}/revert", headers=self._h())
        self.assertEqual((r.json()["revertidos"], r.json()["fallidos"]), (2, 0), r.text)
        self.assertEqual(self._batch(bids[self.c2])["status"], "reverted")

    def test_revert_seguro_que_el_persister_rechaza_queda_como_revert_fallo(self):
        """Un lote con VENTA no se revierte en modo seguro: la fila dice por qué,
        el lote sigue confirmado y los demás sí se revierten."""
        tid = self.http.post("/api/advisor/tandas", json={"rows": [self._row(self.c1, "Juan P"), self._row(self.c2, "Ana G")]}, headers=self._h()).json()["id"]
        p1 = self._preview(self.c1, _csv(
            "1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;100.000;0;0;0;0;100.000",
            "3;4;16-01-2024;16-01-2024;Compra;BONO AL30 (AL30);ARS;BYMA;100;500;50.000;0;0;0;0;-50.000",
            "5;6;17-01-2024;17-01-2024;Venta;BONO AL30 (AL30);ARS;BYMA;-100;600;60.000;0;0;0;0;60.000"), tanda_id=tid)
        self.assertEqual(p1.status_code, 200, p1.text)
        self.assertEqual(self._confirm(self.c1, p1.json()["session_id"]).status_code, 200)
        p2 = self._preview(self.c2, _csv("7;8;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;200.000;0;0;0;0;200.000"), tanda_id=tid)
        self.assertEqual(self._confirm(self.c2, p2.json()["session_id"]).status_code, 200)
        r = self.http.post(f"/api/advisor/tandas/{tid}/revert", headers=self._h())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["revertidos"], r.json()["fallidos"]), (1, 1), r.text)
        d = self.http.get(f"/api/advisor/tandas/{tid}", headers=self._h()).json()
        por = {x["label"]: x for x in d["rows"]}
        self.assertEqual(por["Juan P"]["estado"], "revert_fallo")
        self.assertTrue(por["Juan P"]["detalle"])                       # el motivo del persister, no vacío
        self.assertNotIn("database", por["Juan P"]["detalle"].lower())  # y no un error crudo de la base
        self.assertEqual(self._batch(p1.json()["session_id"])["status"], "confirmed")
        self.assertEqual(por["Ana G"]["estado"], "revertido")

    def test_valores_raros_en_el_patch_son_400_no_500(self):
        tid = self.http.post("/api/advisor/tandas", json={"rows": [self._row(self.c1, "Juan P")]}, headers=self._h()).json()["id"]
        for malo in ({"id": {"a": 1}}, {"client_uid": 2 ** 70}, {"client_uid": True}, {"cargados": "x"}, {"detalle": {"z": 1}}):
            r = self.http.patch(f"/api/advisor/tandas/{tid}", json={"rows": [{**self._row(self.c1, "Juan P"), **malo}]}, headers=self._h())
            self.assertEqual(r.status_code, 400, f"{malo}: {r.status_code} {r.text}")

    def test_detalle_no_lee_lotes_que_no_son_de_la_tanda(self):
        """Un batch_id ajeno metido por PATCH no devuelve su status."""
        tid, bids = self._tanda_cargada()
        # lote suelto (sin tanda) del mismo cliente
        p = self._preview(self.c1, _csv("9;9;01-02-2024;01-02-2024;Recibo De Cobro;;ARS;;;;5.000;0;0;0;0;5.000"))
        suelto = p.json()["session_id"]
        rows = [self._row(self.c1, "Juan P", estado="completo", batch_id=suelto)]
        self.http.patch(f"/api/advisor/tandas/{tid}", json={"rows": rows}, headers=self._h())
        d = self.http.get(f"/api/advisor/tandas/{tid}", headers=self._h()).json()
        self.assertIsNone(d["rows"][0]["batch_status"])

    def test_borrar_al_cliente_olvida_su_nombre_en_la_tanda(self):
        import advisor_tandas as at
        tid, bids = self._tanda_cargada()
        conn = main.get_db()
        try:
            n = at.olvidar_cliente(conn, self.c2)
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(n, 1)
        d = self.http.get(f"/api/advisor/tandas/{tid}", headers=self._h()).json()
        labels = [x["label"] for x in d["rows"]]
        self.assertNotIn("Ana G", labels)
        self.assertIn("Cliente eliminado", labels)
        eliminado = next(x for x in d["rows"] if x["label"] == "Cliente eliminado")
        self.assertIsNone(eliminado["client_uid"])

    def test_preview_con_tanda_ajena_no_deja_lote_huerfano(self):
        tid = self.http.post("/api/advisor/tandas", json={"rows": [self._row(self.c1, "Juan P")]}, headers=self._h()).json()["id"]
        conn = main.get_db(); _link(conn, self.otro, self.c2, label="X"); conn.commit(); conn.close()
        antes = self._n_batches(self.c2)
        p = self._preview(self.c2, _csv("1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;1.000;0;0;0;0;1.000"), tanda_id=tid, who=self.otro)
        self.assertEqual(p.status_code, 400)
        self.assertEqual(self._n_batches(self.c2), antes)

    def _n_batches(self, uid):
        conn = main.get_db()
        try:
            return conn.execute("SELECT COUNT(*) FROM import_batches WHERE user_id=?", (uid,)).fetchone()[0]
        finally:
            conn.close()

    def test_detalle_refleja_un_revert_hecho_desde_la_cuenta_del_cliente(self):
        tid, bids = self._tanda_cargada()
        r = self.http.post(f"/api/imports/{bids[self.c1]}/revert", headers=self._h(None, self.c1))
        self.assertEqual(r.status_code, 200, r.text)
        d = self.http.get(f"/api/advisor/tandas/{tid}", headers=self._h()).json()
        por = {x["label"]: x["estado"] for x in d["rows"]}
        self.assertEqual(por["Juan P"], "revertido")
        self.assertEqual(por["Ana G"], "completo")


if __name__ == "__main__":
    unittest.main()
