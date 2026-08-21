"""El diagnosticador del reconstructor — por qué el número de alguien está roto.

Los casos están calcados de producción (copia del 2026-08-16), no inventados.
El que más importa es el de las DOS PATAS: tres de cuatro agentes de la revisión
sólo veían la positiva, y arreglar sólo esa deja el número PEOR.
"""
import unittest
import uuid

import main
from fastapi.testclient import TestClient


def _mk_user(conn, email, is_admin=0):
    return conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin) "
        "VALUES (?, 'x', 1, ?)", (email, is_admin)).lastrowid


class DiagnosticoTest(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(main.app)
        tag = uuid.uuid4().hex[:10]
        conn = main.get_db()
        self.admin = _mk_user(conn, f"adm-{tag}@rendi.test", is_admin=1)
        self.uid = _mk_user(conn, f"cli-{tag}@rendi.test")
        conn.commit(); conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.admin)}"}

    # ── helpers ─────────────────────────────────────────────────────────────
    def _batch(self, parser="cocos", broker="Cocos"):
        bid = uuid.uuid4().hex[:12]
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO import_batches (id,user_id,broker,parser_format,"
                "file_hash,status) VALUES (?,?,?,?,?,'confirmed')",
                (bid, self.uid, broker, parser, bid))
            conn.commit()
        finally:
            conn.close()
        return bid

    def _tx(self, bid, op, asset=None, qty=None, price=None, gross=None,
            gross_usd=None, ccy="USD", notes=None, date="2025-09-22"):
        conn = main.get_db()
        try:
            rid = conn.execute(
                "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
                "VALUES (?,0,'{}','valid')", (bid,)).lastrowid
            conn.execute(
                "INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,"
                "operation_type,asset_symbol,quantity,unit_price,gross_amount,"
                "gross_amount_usd,currency,notes) VALUES (?,?,?,'Cocos',?,?,?,?,?,?,?,?)",
                (bid, rid, date, op, asset, qty, price, gross, gross_usd, ccy, notes))
            conn.commit()
            return rid
        finally:
            conn.close()

    def _op(self, asset, entry, exit_, qty, pnl, broker="Cocos · USD",
            date="2025-09-22"):
        conn = main.get_db()
        try:
            return conn.execute(
                "INSERT INTO operations (user_id,date,broker,asset,op_type,"
                "entry_price,exit_price,quantity,pnl_usd,currency) "
                "VALUES (?,?,?,?,'Venta',?,?,?,?,'USD')",
                (self.uid, date, broker, asset, entry, exit_, qty, pnl)).lastrowid
        finally:
            conn.commit(); conn.close()

    def _monthly(self, capital_final, manual_dep=0.0, broker="global", ym=(2025, 9)):
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO monthly_entries (user_id,year,month,broker,deposits,"
                "withdrawals,pnl_realized,pnl_unrealized,capital_inicio,capital_final,"
                "manual_deposits,manual_deposits_native) VALUES (?,?,?,?,0,0,0,0,0,?,?,0)",
                (self.uid, ym[0], ym[1], broker, capital_final, manual_dep))
            conn.commit()
        finally:
            conn.close()

    def _diag(self):
        r = self.http.get("/api/admin/diagnostico",
                          params={"target_uid": self.uid}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _causas(self, d):
        return {c["causa"] for c in d["causas"]}

    # ── R1: el conducto, y sus DOS patas ────────────────────────────────────
    def _conducto(self):
        # El par espejo real de Cocos: misma cantidad, mismo activo, mismo
        # batch, y un precio 1.466× el otro porque una pata quedó en pesos.
        bid = self._batch()
        self._tx(bid, "BUY", asset="DHS9O", qty=3473097, price=0.00072,
                 gross=2500.0, gross_usd=2500.0)
        self._tx(bid, "SELL", asset="DHS9O", qty=3473097, price=1.095,
                 gross=3803291.0, gross_usd=3803291.0, notes="MEP")
        return bid

    def test_detecta_el_conducto_por_pareja_espejo(self):
        self._conducto()
        self._op("DHS9O", 0.00072, 1.095, 3473097, 3_800_541.0)
        d = self._diag()
        self.assertIn("R1_conducto_mep_cocos", self._causas(d))

    def test_reporta_LAS_DOS_PATAS(self):
        # ⭐ EL CASO QUE IMPORTA (uid 358 en prod). La pata negativa sale con
        # pnl_pct = −100 EXACTO —costo peso-escala, ingresos USD— así que
        # ningún umbral sobre pnl_pct la ve, y parece una pérdida total normal.
        # Medido en prod: positiva +1.211.379, negativa −2.644.736. Arreglar
        # sólo la positiva deja el pico PEOR (1.436.162 → 2.643.283).
        self._conducto()
        self._op("DHS9O", 0.00072, 1.095, 3473097, 1_211_379.0)
        self._op("DHS9O", 1.038, 0.00078, 1013974, -2_644_736.0)
        r1 = next(c for c in self._diag()["causas"]
                  if c["causa"] == "R1_conducto_mep_cocos")
        self.assertAlmostEqual(r1["pnl_pata_positiva"], 1_211_379.0, places=2)
        self.assertAlmostEqual(r1["pnl_pata_negativa"], -2_644_736.0, places=2)
        self.assertLess(r1["pnl_neto"], 0)       # el NETO es negativo
        self.assertIn("DOS PATAS", r1["ojo"])

    def test_una_venta_normal_no_es_conducto(self):
        # Una compra y una venta del mismo papel sin ratio imposible no puede
        # dispararlo: sería proponer "corregir" una operación sana.
        bid = self._batch()
        self._tx(bid, "BUY", asset="AL30", qty=100, price=1.00,
                 gross=100.0, gross_usd=100.0)
        self._tx(bid, "SELL", asset="AL30", qty=100, price=1.15,
                 gross=115.0, gross_usd=115.0)
        self.assertNotIn("R1_conducto_mep_cocos", self._causas(self._diag()))

    # ── R3 y R4: los que se arreglan solos ──────────────────────────────────
    def test_per100_se_puede_arreglar_solo(self):
        bid = self._batch(parser="ieb", broker="IEB")
        # unit_price × qty / gross_amount == 100 exacto = la firma del per-100.
        self._tx(bid, "SELL", asset="AL30", qty=32100, price=89797.07,
                 gross=28824859.47, gross_usd=20370.90, ccy="ARS")
        c = next(x for x in self._diag()["causas"] if x["causa"] == "R3_per100")
        self.assertEqual(c["auto_arreglable"], "si_deterministico")
        self.assertIn("gross_amount/quantity", c["regla"])

    def test_renta_balanz_NO_se_puede_arreglar_sola(self):
        # No hay dato bueno en ninguna parte: la columna "Moneda Venta" del
        # Excel no se guardó, y el formato está bloqueado.
        bid = self._batch(parser="balanz_resultados", broker="Balanz")
        self._tx(bid, "INTEREST", gross=613597.68, gross_usd=613597.68, ccy="USD")
        c = next(x for x in self._diag()["causas"]
                 if x["causa"] == "R2_renta_balanz_resultados")
        self.assertEqual(c["auto_arreglable"], "no_hace_falta_humano")
        self.assertIsNone(c["regla"])

    # ── R5: distinguir SÍNTOMA de CAUSA ─────────────────────────────────────
    def test_el_manual_que_refleja_la_pnl_inflada_es_SINTOMA(self):
        # En 8 de 11 cuentas de prod el manual gigante era el reflejo de R1: la
        # P&L infló el cash y un seed bookeó el retiro espejo. Tratarlo como
        # causa propia lleva a "arreglar" dos veces el mismo daño.
        self._conducto()
        self._op("DHS9O", 0.00072, 1.095, 3473097, 1_000_000.0)
        self._monthly(1_000_000.0, manual_dep=1_010_000.0, broker="Cocos")
        c = next(x for x in self._diag()["causas"] if x["causa"] == "R5_manual_huerfano")
        self.assertTrue(c["es_sintoma_de_otra_causa"])

    def test_el_manual_sin_import_que_lo_explique_es_CAUSA(self):
        self._monthly(5_202_666.0, manual_dep=5_202_666.0, broker="Cocos")
        c = next(x for x in self._diag()["causas"] if x["causa"] == "R5_manual_huerfano")
        self.assertFalse(c["es_sintoma_de_otra_causa"])
        self.assertEqual(c["auto_arreglable"], "no_hace_falta_humano")

    # ── La falla que NO puede ser silenciosa ─────────────────────────────────
    def test_una_sonda_rota_no_se_lee_como_cuenta_sana(self):
        # 🔴 Un `try/except → return []` convierte una query ROTA en "no
        # encontré nada", indistinguible de "está sana". Un diagnosticador que
        # falla en silencio da de alta a un enfermo.
        import diagnostico
        orig = diagnostico.r3_per100

        def rota(conn, uid, fallas=None):
            if fallas is not None:
                fallas.anotar("R3_test", RuntimeError("boom"))
            return {}
        diagnostico.r3_per100 = rota
        try:
            d = self._diag()
        finally:
            diagnostico.r3_per100 = orig
        self.assertTrue(d["sondas_fallidas"])
        self.assertIn("INCOMPLETO", d["veredicto"])

    def test_sin_causa_no_inventa_una(self):
        d = self._diag()
        self.assertEqual(d["causas"], [])
        self.assertIn("no inventes", d["veredicto"])

    # ── Contrato ────────────────────────────────────────────────────────────
    def test_no_escribe_nada(self):
        self._conducto()
        self._op("DHS9O", 0.00072, 1.095, 3473097, 3_800_541.0)
        self._monthly(3_800_541.0)
        tablas = ("operations", "monthly_entries", "import_normalized_tx", "snapshots")
        conn = main.get_db()
        try:
            antes = [conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] for t in tablas]
        finally:
            conn.close()
        self._diag()
        conn = main.get_db()
        try:
            despues = [conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] for t in tablas]
        finally:
            conn.close()
        self.assertEqual(antes, despues)

    def test_el_barrido_declara_si_trunco(self):
        r = self.http.get("/api/admin/diagnostico", params={"limite": 5}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("truncado", r.json())
        self.assertIn("1415", r.json()["caveat"])   # el caveat del FX viaja siempre

    def test_requiere_admin(self):
        r = self.http.get("/api/admin/diagnostico",
                          headers={"Authorization": f"Bearer {main.create_token(self.uid)}"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
