"""Censo de flujos ambiguos — Fase 1 del agente reconstructor.

Lo que estos tests fijan es el DIAGNÓSTICO del proyecto, no una feature: que la
cola de `flujos.candidatos()` está vacía (P1=0) mientras que hay traspasos YA
CONTADOS COMO APORTE del cliente (P2b>0). Si alguna vez este par se invierte,
el plan de las fases 2 y 5 deja de aplicar y hay que releerlo.
"""
import unittest
import uuid

import main
from fastapi.testclient import TestClient


def _mk_user(conn, email, is_admin=0):
    return conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin) "
        "VALUES (?, 'x', 1, ?)", (email, is_admin)).lastrowid


class CensoFlujosTest(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:10]
        conn = main.get_db()
        self.admin_uid = _mk_user(conn, f"admin-{self.tag}@rendi.test", is_admin=1)
        self.uid = _mk_user(conn, f"cli-{self.tag}@rendi.test")
        conn.commit()
        conn.close()
        self.admin_h = {"Authorization": f"Bearer {main.create_token(self.admin_uid)}"}

    # ── helpers: reproducen lo que el parser escribe DE VERDAD ──────────────
    def _batch(self, broker="Balanz", status="confirmed"):
        bid = uuid.uuid4().hex[:12]
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO import_batches (id,user_id,broker,parser_format,"
                "file_hash,status) VALUES (?,?,?,'test',?,?)",
                (bid, self.uid, broker, bid, status))
            conn.commit()
        finally:
            conn.close()
        return bid

    def _tx(self, bid, op, broker="Balanz", notes=None, qty=None,
            gross=None, transfer_out=0, asset="AAPL"):
        conn = main.get_db()
        try:
            rid = conn.execute(
                "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
                "VALUES (?,0,'{}','valid')", (bid,)).lastrowid
            conn.execute(
                "INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,"
                "operation_type,asset_symbol,quantity,gross_amount,notes,transfer_out) "
                "VALUES (?,?,'2026-04-12',?,?,?,?,?,?,?)",
                (bid, rid, broker, op, asset, qty, gross, notes, transfer_out))
            conn.commit()
        finally:
            conn.close()

    def _censo(self, **kw):
        r = self.http.get("/api/admin/censo-flujos",
                          params={"target_uid": self.uid, "incluir_p3": False, **kw},
                          headers=self.admin_h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ── El hallazgo que ordena todo el proyecto ─────────────────────────────
    def test_el_traspaso_ya_esta_contado_como_aporte_y_la_cola_esta_vacia(self):
        # Lo que emite balanz_movimientos.py:429-437 ante una entrada de título:
        # DOS filas, la COMPRA y un DEPOSITO compensatorio por el mismo monto.
        bid = self._batch()
        self._tx(bid, "BUY", qty=12, gross=1000.0, notes="Transferencia Externa")
        self._tx(bid, "DEPOSIT", gross=1000.0,
                 notes="Transferencia Externa (entrada de título)")

        c = self._censo()
        t = c["totales"]
        # El depósito está: ese peso ya viajó a monthly_entries → net_deposited → TWR.
        self.assertEqual(t["p2b_deposito_compensatorio"], 1)
        self.assertEqual(t["p2b_monto"], 1000.0)
        # Y la cola del agente está vacía: no hay NADA que resolver esperando.
        self.assertEqual(t["p1_rechazadas"], 0)
        self.assertIn("CONFIRMADO", c["lectura"])

    def test_desglosa_por_broker(self):
        # La tasa por broker es lo que dice dónde conviene una regla
        # determinística en vez de un agente.
        b1 = self._batch(broker="Balanz")
        self._tx(b1, "DEPOSIT", broker="Balanz", gross=500.0,
                 notes="Transferencia Externa (entrada de título)")
        b2 = self._batch(broker="IEB")
        self._tx(b2, "DEPOSIT", broker="IEB", gross=300.0,
                 notes="TRANSF RECIBIDA (cash compensatorio)")

        por = {r["broker"]: r for r in self._censo()["por_broker"]}
        self.assertEqual(por["Balanz"]["p2b_deposito_compensatorio"], 1)
        self.assertEqual(por["IEB"]["p2b_deposito_compensatorio"], 1)
        self.assertEqual(por["IEB"]["p2b_monto"], 300.0)

    def test_la_firma_numerica_caza_lo_que_el_texto_no_dice(self):
        # Cantidad sin plata = movimiento de títulos, sin depender del idioma
        # del broker ni de que el vocabulario conozca su string.
        bid = self._batch(broker="Schwab")
        self._tx(bid, "BUY", broker="Schwab", qty=12, gross=0,
                 notes="Journaled Shares XYZ")
        self.assertEqual(self._censo()["totales"]["p2c_firma_numerica"], 1)

    def test_transfer_out_es_la_marca_estructurada(self):
        bid = self._batch(broker="PPI")
        self._tx(bid, "SELL", broker="PPI", qty=787.9, gross=0,
                 notes="Retiro de Títulos", transfer_out=1)
        self.assertEqual(self._censo()["totales"]["p2a_transfer_out"], 1)

    # ── Higiene: qué NO tiene que contar ────────────────────────────────────
    def test_un_batch_en_preview_no_cuenta(self):
        # Los previews mueren por TTL a la hora: no son la contaminación de nadie.
        bid = self._batch(status="preview")
        self._tx(bid, "DEPOSIT", gross=1000.0,
                 notes="Transferencia Externa (entrada de título)")
        self.assertEqual(self._censo()["totales"]["p2b_deposito_compensatorio"], 0)

    def test_una_fila_excluida_no_cuenta(self):
        # excluded_at es el tombstone del borrado: esa fila ya no está en ningún
        # cálculo, así que tampoco contamina.
        bid = self._batch()
        self._tx(bid, "DEPOSIT", gross=1000.0,
                 notes="Transferencia Externa (entrada de título)")
        conn = main.get_db()
        try:
            conn.execute("UPDATE import_normalized_tx SET excluded_at=datetime('now') "
                         "WHERE batch_id=?", (bid,))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self._censo()["totales"]["p2b_deposito_compensatorio"], 0)

    def test_un_deposito_de_verdad_no_se_confunde(self):
        # Plata nueva del cliente: no lleva nota compensatoria y no tiene que
        # aparecer en ninguna población. Contarlo sería proponer "corregir" un
        # aporte real — el error más caro que puede cometer este proyecto.
        bid = self._batch()
        self._tx(bid, "DEPOSIT", gross=5000.0, notes="Transferencia recibida")
        t = self._censo()["totales"]
        self.assertEqual(t["p2b_deposito_compensatorio"], 0)
        self.assertEqual(t["p2c_firma_numerica"], 0)

    # ── Contrato: read-only y gate de admin ─────────────────────────────────
    def test_no_escribe_nada(self):
        bid = self._batch()
        self._tx(bid, "DEPOSIT", gross=1000.0,
                 notes="Transferencia Externa (entrada de título)")
        conn = main.get_db()
        try:
            antes = [conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                     for t in ("import_raw_rows", "import_normalized_tx",
                               "import_batches", "snapshots")]
        finally:
            conn.close()
        self._censo()
        conn = main.get_db()
        try:
            despues = [conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                       for t in ("import_raw_rows", "import_normalized_tx",
                                 "import_batches", "snapshots")]
        finally:
            conn.close()
        self.assertEqual(antes, despues)

    def test_requiere_admin(self):
        r = self.http.get("/api/admin/censo-flujos",
                          headers={"Authorization": f"Bearer {main.create_token(self.uid)}"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
