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
            gross=None, transfer_out=0, asset="AAPL", ccy="ARS"):
        conn = main.get_db()
        try:
            rid = conn.execute(
                "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
                "VALUES (?,0,'{}','valid')", (bid,)).lastrowid
            conn.execute(
                "INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,"
                "operation_type,asset_symbol,quantity,gross_amount,currency,notes,"
                "transfer_out) VALUES (?,?,'2026-04-12',?,?,?,?,?,?,?,?)",
                (bid, rid, broker, op, asset, qty, gross, ccy, notes, transfer_out))
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
        self._tx(bid, "DEPOSIT", gross=1000.0, ccy="ARS",
                 notes="Transferencia Externa (entrada de título)")

        c = self._censo()
        # El depósito está: ese peso ya viajó a monthly_entries → net_deposited → TWR.
        self.assertEqual(c["p2b_traspaso_como_aporte"]["filas"], 1)
        self.assertEqual(c["p2b_traspaso_como_aporte"]["usuarios"], 1)
        self.assertEqual(c["p2b_traspaso_como_aporte"]["por_moneda"]["ARS"]["suma"], 1000.0)
        # Y la cola del agente está vacía: no hay NADA que resolver esperando.
        self.assertEqual(c["p1_rechazadas"]["filas"], 0)

    # ── El defecto que hizo inútil la primera corrida ───────────────────────
    def test_la_semilla_de_una_foto_no_se_cuenta_como_traspaso(self):
        # Son DOS mecanismos distintos: el traspaso contado como aporte (P2b,
        # el objetivo) y la semilla que el import de una FOTO fabrica para que
        # cierre el costo (P2d, intencional y otro problema). La v1 los sumaba
        # en un solo número y sobredimensionaba el proyecto ~28× en usuarios.
        bid = self._batch(broker="Cocos")
        self._tx(bid, "DEPOSIT", broker="Cocos", gross=9000.0,
                 notes="Tenencia — aporte inicial sintético (Rendi)")
        self._tx(bid, "DEPOSIT", broker="Cocos", gross=7000.0,
                 notes="Estado inicial — depósito sintético (Rendi)")
        c = self._censo()
        self.assertEqual(c["p2b_traspaso_como_aporte"]["filas"], 0)
        self.assertEqual(c["p2d_semilla_sintetica"]["filas"], 2)

    def test_nunca_suma_plata_entre_monedas(self):
        # La v1 reportó "3.043 millones" sumando pesos y dólares. No significaba
        # nada. Los montos van SIEMPRE separados por moneda.
        bid = self._batch()
        self._tx(bid, "DEPOSIT", gross=1000.0, ccy="ARS",
                 notes="Transferencia Externa (entrada de título)")
        self._tx(bid, "DEPOSIT", gross=7.0, ccy="USD",
                 notes="Transferencia Externa (entrada de título)")
        por_m = self._censo()["p2b_traspaso_como_aporte"]["por_moneda"]
        self.assertEqual(por_m["ARS"]["suma"], 1000.0)
        self.assertEqual(por_m["USD"]["suma"], 7.0)
        self.assertNotIn(1007.0, [v["suma"] for v in por_m.values()])

    def test_una_suma_grande_que_es_una_sola_fila_se_ve(self):
        # Una familia cuya suma es enorme pero cuyo máximo es casi toda la suma
        # NO es un problema grande: es un dato roto. Sin max_fila, el censo
        # reporta una epidemia donde hay una fila corrupta.
        bid = self._batch()
        self._tx(bid, "DEPOSIT", gross=5.0, ccy="USD",
                 notes="Transferencia Externa (entrada de título)")
        self._tx(bid, "DEPOSIT", gross=1_700_854_139.09, ccy="USD",
                 notes="Transferencia Externa (entrada de título)")
        m = self._censo()["p2b_traspaso_como_aporte"]["por_moneda"]["USD"]
        self.assertEqual(m["max_fila"], 1_700_854_139.09)
        self.assertGreater(m["max_fila"] / m["suma"], 0.99)

    def test_un_monto_imposible_sale_por_derecha(self):
        # La fila de USD 1.700.854.139 de producción se encontró de casualidad,
        # porque un total no cerraba. Ahora el censo la denuncia sola.
        bid = self._batch(broker="Cocos")
        self._tx(bid, "DEPOSIT", broker="Cocos", gross=1_700_854_139.09, ccy="USD",
                 notes="Tenencia — aporte inicial sintético (Rendi)")
        al = self._censo()["alertas_monto_imposible"]
        self.assertEqual(len(al), 1)
        self.assertEqual(al[0]["currency"], "USD")
        self.assertEqual(al[0]["user_id"], self.uid)

    def test_p2c_reporta_su_concentracion(self):
        # 88% de P2c en producción es UN broker de 3 usuarios. Sin la
        # concentración al lado, el total parece una epidemia.
        bid = self._batch(broker="Binance")
        for _ in range(4):
            self._tx(bid, "BUY", broker="Binance", qty=1, gross=0, notes="trade")
        b2 = self._batch(broker="Balanz")
        self._tx(b2, "BUY", broker="Balanz", qty=1, gross=0, notes="otro")
        c = self._censo()["p2c_firma_numerica"]
        self.assertEqual(c["filas"], 5)
        self.assertIn("Binance", c["concentracion"])
        self.assertIn("80%", c["concentracion"])

    def test_desglosa_por_broker(self):
        # La tasa por broker es lo que dice dónde conviene una regla
        # determinística en vez de un agente.
        b1 = self._batch(broker="Balanz")
        self._tx(b1, "DEPOSIT", broker="Balanz", gross=500.0,
                 notes="Transferencia Externa (entrada de título)")
        b2 = self._batch(broker="IEB")
        self._tx(b2, "DEPOSIT", broker="IEB", gross=300.0,
                 notes="TRANSF RECIBIDA (cash compensatorio)")
        por = self._censo()["p2b_traspaso_como_aporte"]["por_broker"]
        self.assertEqual(por["Balanz"]["filas"], 1)
        self.assertEqual(por["IEB"]["filas"], 1)

    def test_la_firma_numerica_caza_lo_que_el_texto_no_dice(self):
        # Cantidad sin plata = movimiento de títulos, sin depender del idioma
        # del broker ni de que el vocabulario conozca su string.
        bid = self._batch(broker="Schwab")
        self._tx(bid, "BUY", broker="Schwab", qty=12, gross=0,
                 notes="Journaled Shares XYZ")
        self.assertEqual(self._censo()["p2c_firma_numerica"]["filas"], 1)

    def test_transfer_out_es_la_marca_estructurada(self):
        bid = self._batch(broker="PPI")
        self._tx(bid, "SELL", broker="PPI", qty=787.9, gross=0,
                 notes="Retiro de Títulos", transfer_out=1)
        self.assertEqual(self._censo()["p2a_transfer_out"]["filas"], 1)

    # ── Higiene: qué NO tiene que contar ────────────────────────────────────
    def test_un_batch_en_preview_no_cuenta(self):
        # Los previews mueren por TTL a la hora: no son la contaminación de nadie.
        bid = self._batch(status="preview")
        self._tx(bid, "DEPOSIT", gross=1000.0,
                 notes="Transferencia Externa (entrada de título)")
        self.assertEqual(self._censo()["p2b_traspaso_como_aporte"]["filas"], 0)

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
        self.assertEqual(self._censo()["p2b_traspaso_como_aporte"]["filas"], 0)

    def test_un_deposito_de_verdad_no_se_confunde(self):
        # Plata nueva del cliente: no lleva nota compensatoria y no tiene que
        # aparecer en ninguna población. Contarlo sería proponer "corregir" un
        # aporte real — el error más caro que puede cometer este proyecto.
        bid = self._batch()
        self._tx(bid, "DEPOSIT", gross=5000.0, notes="Transferencia recibida")
        c = self._censo()
        self.assertEqual(c["p2b_traspaso_como_aporte"]["filas"], 0)
        self.assertEqual(c["p2c_firma_numerica"]["filas"], 0)
        self.assertEqual(c["p2d_semilla_sintetica"]["filas"], 0)

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
