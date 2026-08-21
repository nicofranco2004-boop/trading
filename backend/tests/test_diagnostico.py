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

    def _link(self, bid, raw_id, op_id):
        """Liga una operación a la fila importada que la generó.

        Sin el link no hay forma de saber si el motor tomó el precio crudo o el
        escalado — y esa es justo la diferencia entre una fila per-100 sana y
        un número roto."""
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO import_op_links (batch_id,raw_row_id,operation_id) "
                "VALUES (?,?,?)", (bid, raw_id, op_id))
            conn.commit()
        finally:
            conn.close()

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

    def _conducto_espejo(self):
        """El MISMO conducto, con la pata en pesos del otro lado: la COMPRA.

        Calcado de uid 92 en prod (T661O, compra 1,08 contra venta 0,00076 =
        ratio 1.416 ≈ el dólar). El detector viejo pedía venta/compra > 300, así
        que a estas cuentas no las veía: 679, 92 y 520 salían "sin causa
        conocida" con −13,9M / −10,8M / −4,8M de daño.
        """
        bid = self._batch()
        self._tx(bid, "BUY", asset="T661O", qty=1314184, price=1.08,
                 gross=1419318.72, gross_usd=1419318.72)
        self._tx(bid, "SELL", asset="T661O", qty=1314184, price=0.00076,
                 gross=998.78, gross_usd=998.78, notes="MEP")
        return bid

    def test_detecta_el_conducto_con_la_COMPRA_en_pesos(self):
        # ⭐ El espejo del caso de arriba. Un detector que sólo mira una
        # dirección no es medio detector: es uno que además manda la regla de
        # corrección contra la pata SANA.
        self._conducto_espejo()
        self._op("T661O", 1.08, 0.00076, 1314184, -1_418_319.0)
        r1 = next(c for c in self._diag()["causas"]
                  if c["causa"] == "R1_conducto_mep_cocos")
        self.assertEqual(r1["pares_buy_en_pesos"], 1)
        self.assertEqual(r1["pares_sell_en_pesos"], 0)
        self.assertEqual(r1["muestra"][0]["pata_peso"], "buy")

    def test_cada_par_dice_CUAL_pata_esta_en_pesos(self):
        # La `regla` es direccional. Si el par no dice de qué lado está el
        # peso, aplicarla es adivinar — y adivinar mal re-etiqueta la pata que
        # ya estaba bien.
        self._conducto()
        self._op("DHS9O", 0.00072, 1.095, 3473097, 1_211_379.0)
        r1 = next(c for c in self._diag()["causas"]
                  if c["causa"] == "R1_conducto_mep_cocos")
        self.assertEqual(r1["muestra"][0]["pata_peso"], "sell")
        self.assertIn("pata_peso", r1["regla"])

    def test_el_par_SIN_dano_no_es_una_cuenta_rota(self):
        # uid 456 en prod: tiene el par recíproco y capital_declarado == cartera
        # al centavo. El mislabel existe pero nunca llegó a una operación.
        # Hacer simétrico el detector sin esta guarda cambia un falso negativo
        # por un falso positivo, que no es progreso.
        self._conducto_espejo()          # el par existe…
        # …pero no hay ninguna operación con la escala rota.
        self.assertNotIn("R1_conducto_mep_cocos", self._causas(self._diag()))

    # ── R3 y R4: los que se arreglan solos ──────────────────────────────────
    def test_per100_se_puede_arreglar_solo(self):
        bid = self._batch(parser="ieb", broker="IEB")
        # unit_price × qty / gross_amount == 100 exacto = la firma del per-100.
        rid = self._tx(bid, "SELL", asset="AL30", qty=32100, price=89797.07,
                       gross=28824859.47, gross_usd=20370.90, ccy="ARS")
        # …y la operación que el motor construyó tomando el precio CRUDO
        # (89797,07) en vez del escalado (gross/qty = 897,97). Ahí vive el daño:
        # la fila per-100 por sí sola es la convención de cotización del bono,
        # no un defecto.
        oid = self._op("AL30", 850.00, 89797.07, 32100, 2_882_485.0)
        self._link(bid, rid, oid)
        c = next(x for x in self._diag()["causas"] if x["causa"] == "R3_per100")
        self.assertEqual(c["auto_arreglable"], "si_deterministico")
        self.assertIn("gross_amount/quantity", c["regla"])
        self.assertEqual(c["ops_afectadas"], 1)

    def test_la_fila_per100_SIN_operacion_no_es_un_numero_roto(self):
        # uid 733 en prod: 1 fila con la firma per-100 y CERO operaciones
        # ligadas. Contar filas en vez de daño lo metía en la cola de trabajo.
        bid = self._batch(parser="ieb", broker="IEB")
        self._tx(bid, "SELL", asset="AL30", qty=32100, price=89797.07,
                 gross=28824859.47, gross_usd=20370.90, ccy="ARS")
        self.assertNotIn("R3_per100", self._causas(self._diag()))

    def test_el_bono_per100_bien_construido_no_es_un_hallazgo(self):
        # Misma fila, pero el motor SÍ tomó gross/qty. La firma per-100 está
        # igual —es la convención del bono— y acá no hay nada que corregir.
        bid = self._batch(parser="ieb", broker="IEB")
        rid = self._tx(bid, "SELL", asset="AL30", qty=32100, price=89797.07,
                       gross=28824859.47, gross_usd=20370.90, ccy="ARS")
        oid = self._op("AL30", 850.00, 897.9707, 32100, 1_540.0)
        self._link(bid, rid, oid)
        self.assertNotIn("R3_per100", self._causas(self._diag()))

    def test_r4_marca_las_filas_que_NO_hay_que_tocar(self):
        # 🔴 27 filas que este detector agarra en prod están BIEN: son dólares
        # con la moneda INFERIDA a ARS porque el parser no supo la divisa
        # (`divisa=OTHER`). Aplicarles la regla las achica ~1.200× y borra renta
        # real. El diagnóstico las cuenta, pero avisa que la reparación no las
        # toca — un selector de diagnóstico más ancho que el de reparación es
        # correcto sólo si dice dónde está la diferencia.
        bid = self._batch(parser="ieb", broker="IEB")
        rid = self._tx(bid, "DIVIDEND", asset="AL30", qty=1, price=25.36,
                       gross=25.36, gross_usd=0.0179, ccy="ARS",
                       notes="IEB:RTA · divisa=OTHER")
        oid = self._op("AL30", 0, 0, 1, 25.36)
        self._link(bid, rid, oid)
        c = next(x for x in self._diag()["causas"]
                 if x["causa"] == "R4_renta_moneda_ignorada")
        self.assertEqual(c["filas_moneda_inferida"], 1)
        self.assertIn("divisa=OTHER", c["ojo"])
        self.assertIn("no se tocan", c["ojo"])

    def test_r4_marca_el_sello_1415(self):
        # El otro subconjunto que la reparación no puede tratar igual: TC
        # sellado a 1415,00 en cuenta fx v1. Pasar el P&L al MEP histórico
        # dejando los flujos al sello es migrar UNA sola pata del FX — el
        # patrón que en este repo ya llevó un error de 1,23× a 9,1×.
        bid = self._batch(parser="ieb", broker="IEB")
        rid = self._tx(bid, "INTEREST", asset="AL30", qty=1, price=141500.0,
                       gross=141500.0, gross_usd=100.0, ccy="ARS")
        oid = self._op("AL30", 0, 0, 1, 141500.0)
        self._link(bid, rid, oid)
        c = next(x for x in self._diag()["causas"]
                 if x["causa"] == "R4_renta_moneda_ignorada")
        self.assertEqual(c["filas_con_sello_1415"], 1)
        self.assertIn("1415", c["ojo"])

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

    def test_el_barrido_dice_a_quien_NO_miro(self):
        # 🔴 Tres filtros descartaban gente en silencio, y un barrido que no
        # dice a quién no miró se lee como censo. El peor era el piso de
        # `cap > 1.000.000`: ordena por tamaño de CLIENTE, no de ERROR, así que
        # dejaba afuera a 37 usuarios con ratio>10 — uid 859 está 2.062× mal
        # sobre una cartera de US$390.
        self._monthly(9_000_000.0)      # global, y este usuario no tiene snapshot
        j = self.http.get("/api/admin/diagnostico", params={"limite": 5},
                          headers=self.h).json()
        self.assertIn("no_mirados", j)
        self.assertIn(self.uid, j["no_mirados"]["no_rankeables"]["uids"])
        self.assertIn("SÍNTOMA", j["no_mirados"]["no_rankeables"]["por_que"])
        self.assertEqual(j["umbrales"]["cap_min_usd"], 1000.0)

    def test_el_piso_de_dano_se_puede_mover(self):
        # Poder mirar a los que quedan justo afuera de la banda sin editar
        # código es lo que evita que el umbral se vuelva incuestionable.
        r = self.http.get("/api/admin/diagnostico",
                          params={"limite": 5, "cap_min": 50, "ratio_min": 2},
                          headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["umbrales"], {"cap_min_usd": 50.0, "ratio_min": 2.0})

    def test_requiere_admin(self):
        r = self.http.get("/api/admin/diagnostico",
                          headers={"Authorization": f"Bearer {main.create_token(self.uid)}"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
