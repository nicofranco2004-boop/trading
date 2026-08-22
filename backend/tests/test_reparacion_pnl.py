"""La reparación de la renta con la moneda ignorada (R4).

El caso está calcado de uid 54 en producción (copia del 2026-08-16): 5 filas de
renta con el monto en PESOS metido en `operations.pnl_usd`, con TC per-fecha
REALES (1427,4 · 1426,4 · 1434,8 · 1532,4 · 1526,0 — no el sello plano de 1415).
Repararlas lleva la cuenta de un capital declarado de 5.749.322,73 contra una
cartera de 9.334,48 a un pico de 11.825,71.

Los tres tests que importan más que el resto:
  • el criterio de éxito NO es una tautología (los dos números llegan por
    caminos distintos),
  • el ensayo es IDÉNTICO al apply,
  • hay vuelta atrás.
"""
import json
import unittest
import uuid

import main
from fastapi.testclient import TestClient


def _mk_user(conn, email, is_admin=0):
    return conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin) "
        "VALUES (?, 'x', 1, ?)", (email, is_admin)).lastrowid


class ReparacionPnlTest(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(main.app)
        tag = uuid.uuid4().hex[:10]
        conn = main.get_db()
        self.admin = _mk_user(conn, f"adm-{tag}@rendi.test", is_admin=1)
        self.uid = _mk_user(conn, f"cli-{tag}@rendi.test")
        conn.commit(); conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.admin)}"}
        self.bid = self._batch()

    # ── fixtures ────────────────────────────────────────────────────────────
    def _batch(self, parser="iol", broker="IOL"):
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

    def _renta(self, date, ars, usd, op_type="Dividendo", notes=None, asset="S27F6"):
        """Una fila de renta rota: el pnl_usd quedó con el monto en PESOS."""
        conn = main.get_db()
        try:
            rid = conn.execute(
                "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
                "VALUES (?,0,'{}','valid')", (self.bid,)).lastrowid
            conn.execute(
                "INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,"
                "operation_type,asset_symbol,quantity,unit_price,gross_amount,"
                "gross_amount_usd,currency,notes) "
                "VALUES (?,?,?,'IOL',?,?,1,?,?,?,'ARS',?)",
                (self.bid, rid, date,
                 "DIVIDEND" if op_type == "Dividendo" else "INTEREST",
                 asset, ars, ars, usd, notes))
            oid = conn.execute(
                "INSERT INTO operations (user_id,date,broker,asset,op_type,"
                "entry_price,exit_price,quantity,pnl_usd) "
                "VALUES (?,?,'IOL',?,?,0,0,1,?)",
                (self.uid, date, asset, op_type, ars)).lastrowid
            conn.execute(
                "INSERT INTO import_op_links (batch_id,raw_row_id,operation_id) "
                "VALUES (?,?,?)", (self.bid, rid, oid))
            conn.commit()
            return oid
        finally:
            conn.close()

    def _caso_uid54(self):
        """Las 5 filas reales de uid 54, con sus TC per-fecha."""
        return [
            self._renta("2026-02-27", 1055645.75, 739.56),
            self._renta("2026-03-16", 2060827.59, 1444.78),
            self._renta("2026-05-29", 2579722.50, 1797.97),
            self._renta("2026-07-02", 303.89, 0.20, op_type="Interés"),
            self._renta("2026-07-03", 45009.28, 29.49, op_type="Interés"),
        ]

    def _run(self, apply=False, **kw):
        p = {"user_id": self.uid, "apply": str(apply).lower()}
        p.update(kw)
        r = self.http.post("/api/admin/repair-pnl-escala", params=p, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _u(self, res):
        return res["usuarios"][0]

    def _pnl(self, oid):
        conn = main.get_db()
        try:
            r = conn.execute("SELECT pnl_usd, currency, undo_meta_json FROM operations "
                             "WHERE id=?", (oid,)).fetchone()
            return dict(r) if r else None
        finally:
            conn.close()

    # ── ⭐ LOS TRES QUE IMPORTAN ─────────────────────────────────────────────
    def test_el_criterio_de_exito_NO_es_una_tautologia(self):
        """⭐ Los dos números tienen que llegar por caminos INDEPENDIENTES.

        `delta_esperado` sale del SELECTOR (operations + import_normalized_tx),
        antes de tocar nada. `delta_medido` sale de `monthly_entries.capital_final`
        DESPUÉS de correr la cadena de recomputo. Si los dos salieran del mismo
        código, el repair se estaría verificando contra sí mismo y cerraría
        siempre, incluso con la cadena rota.

        Este test lo prueba ROMPIENDO la cadena: si `delta_medido` fuera un alias
        de `delta_esperado`, seguiría cerrando. Tiene que dejar de cerrar.
        """
        self._caso_uid54()
        res = self._run(apply=True)
        u = self._u(res)
        self.assertTrue(u["cierra"], u["veredicto"])
        self.assertAlmostEqual(u["delta_esperado_usd"], u["delta_medido_usd"], places=0)

        # Y ahora la prueba de que NO es el mismo número: se ensucia
        # `monthly_entries` por afuera (el camino B) sin tocar `operations` (el
        # camino A). Un criterio tautológico no se enteraría.
        conn = main.get_db()
        try:
            conn.execute(
                "UPDATE monthly_entries SET pnl_realized = pnl_realized + 500000 "
                "WHERE user_id=? AND broker='global'", (self.uid,))
            conn.commit()
        finally:
            conn.close()
        otra = main.get_db()
        try:
            import reparacion_pnl
            m = reparacion_pnl.medir(otra, self.uid)
        finally:
            otra.close()
        # El camino B ahora dice otra cosa que el camino A. Son independientes.
        self.assertNotAlmostEqual(m["suma_pnl_realized"],
                                  u["despues"]["suma_pnl_realized"], places=0)

    def test_la_identidad_va_contra_la_SUMA_y_no_contra_el_PICO(self):
        """El pico es un MAX sobre meses: al reparar puede MUDARSE de mes, así
        que su delta no tiene por qué igualar la suma de las correcciones.
        Medido en uid 54 contra prod: el selector esperaba 5.737.497,01 y el
        pico se movió 5.736.345,48 — 1.151,53 de diferencia que no era ningún
        error, era la comparación mal planteada. `pnl_realized` sí es aditivo."""
        self._caso_uid54()
        u = self._u(self._run(apply=True))
        self.assertTrue(u["cierra"], u["veredicto"])
        # La identidad, exacta.
        self.assertAlmostEqual(u["delta_medido_usd"], u["delta_esperado_usd"], places=2)
        # Y el pico viaja al lado, como cifra de titular.
        self.assertIn("delta_pico_capital_final_usd", u)

    def test_el_ensayo_es_IDENTICO_al_apply(self):
        """⭐ Si el ensayo miente, el dry-run deja de ser una red.

        En R3 sabemos que NO sería idéntico (las cuentas fx v1 dolarizan al blue
        VIVO, así que el ensayo y el apply dan distinto según cuándo se corran).
        Acá los TC son per-fecha y está guardado en la fila, así que debería dar
        igual — pero se AFIRMA con el test, no se asume.
        """
        self._caso_uid54()
        ensayo = self._run(apply=False)
        real = self._run(apply=True)

        def _comparable(d):
            d = json.loads(json.dumps(d))
            d.pop("batch_ref", None)
            d.pop("aplicado", None)
            return d

        self.assertEqual(_comparable(ensayo), _comparable(real))

    def test_hay_vuelta_atras(self):
        """⭐ La reversibilidad fue el principio que sostuvo todo lo demás."""
        oids = self._caso_uid54()
        antes = {o: self._pnl(o)["pnl_usd"] for o in oids}
        res = self._run(apply=True)
        self.assertEqual(self._pnl(oids[0])["pnl_usd"], 739.56)

        conn = main.get_db()
        try:
            import reparacion_pnl
            vueltas = reparacion_pnl.revertir(conn, self.uid, res["batch_ref"])
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(vueltas, 5)
        for o, v in antes.items():
            fila = self._pnl(o)
            self.assertAlmostEqual(fila["pnl_usd"], v, places=2)
            # El undo se CONSUME: no queda basura en la columna.
            self.assertNotIn("pnl_escala_reparada", fila["undo_meta_json"] or "")

    # ── el selector angosto ─────────────────────────────────────────────────
    def test_no_toca_la_fila_con_la_moneda_INFERIDA(self):
        # 27 filas de uid 870 en prod: dólares rotulados ARS porque el parser no
        # supo la divisa. Están BIEN. "Corregirlas" las achica ~1.200×.
        oid = self._renta("2026-02-27", 25.36, 0.0179,
                          notes="IEB:RTA · divisa=OTHER")
        res = self._run(apply=True)
        u = self._u(res)
        self.assertEqual(u["filas_a_reparar"], 0)
        self.assertEqual(len(u["no_tocadas"]), 1)
        self.assertIn("moneda_inferida", u["no_tocadas"][0]["motivo"])
        self.assertAlmostEqual(self._pnl(oid)["pnl_usd"], 25.36, places=2)

    def test_no_toca_la_fila_con_el_SELLO_1415(self):
        # Mover sólo el P&L al MEP histórico dejando los flujos al sello plano
        # es migrar UNA sola pata del FX.
        oid = self._renta("2026-02-27", 141500.0, 100.0)
        res = self._run(apply=True)
        u = self._u(res)
        self.assertEqual(u["filas_a_reparar"], 0)
        self.assertIn("sello_1415", u["no_tocadas"][0]["motivo"])
        self.assertAlmostEqual(self._pnl(oid)["pnl_usd"], 141500.0, places=2)

    def test_lo_excluido_no_desaparece(self):
        # Descartar en silencio es lo único inaceptable: una corrida que repara
        # 5 y saltea 2 tiene que decir cuáles salteó y por qué.
        self._caso_uid54()
        self._renta("2026-04-01", 25.36, 0.0179, notes="divisa=OTHER")
        self._renta("2026-04-02", 141500.0, 100.0)
        u = self._u(self._run(apply=False))
        self.assertEqual(u["filas_a_reparar"], 5)
        self.assertEqual(len(u["no_tocadas"]), 2)

    # ── el contrato del dry-run ─────────────────────────────────────────────
    def test_el_dry_run_NO_escribe(self):
        oids = self._caso_uid54()
        self._run(apply=False)
        for o in oids:
            self.assertGreater(self._pnl(o)["pnl_usd"], 100.0)   # sigue en pesos

    def test_es_idempotente(self):
        self._caso_uid54()
        self._run(apply=True)
        segunda = self._u(self._run(apply=True))
        self.assertEqual(segunda["filas_a_reparar"], 0)

    # ── el invariante de FX ─────────────────────────────────────────────────
    def test_deja_currency_USD_para_que_nadie_lo_divida_dos_veces(self):
        """`realized_usd_sql` divide sólo si op_type ∈ _NATIVE_CCY_OPS Y
        currency='ARS'. Hoy Dividendo/Interés no están en esa tupla, pero el
        propio realized_pnl.py discute agregar tipos. Si dejáramos la fila en
        ARS con fx sellado, ese cambio la dividiría DOS veces."""
        import realized_pnl
        oids = self._caso_uid54()
        self._run(apply=True)
        fila = self._pnl(oids[0])
        self.assertEqual(fila["currency"], "USD")
        self.assertAlmostEqual(
            realized_pnl.realized_usd({"op_type": "Dividendo", "pnl_usd": fila["pnl_usd"],
                                       "currency": fila["currency"], "fx_to_usd": 1415.0}),
            739.56, places=2)

    # ── las causas que NO se corrigen desde acá ─────────────────────────────
    def test_R3_y_R1_se_RECHAZAN_con_400(self):
        for c in ("R3", "R1", "R4,R3"):
            r = self.http.post("/api/admin/repair-pnl-escala",
                               params={"user_id": self.uid, "causas": c},
                               headers=self.h)
            self.assertEqual(r.status_code, 400, f"{c}: {r.text}")
            self.assertIn("crimen perfecto" if "R3" in c else "undo",
                          r.json()["detail"])

    def test_requiere_admin(self):
        r = self.http.post("/api/admin/repair-pnl-escala",
                           headers={"Authorization": f"Bearer {main.create_token(self.uid)}"})
        self.assertEqual(r.status_code, 403)

    # ── el residuo que el repair NO puede arreglar ──────────────────────────
    def test_reporta_los_snapshots_que_quedan_sucios(self):
        # Un repair que arregla capital_final y calla que el gráfico sigue
        # mostrando el pico es cirugía con el paciente viéndose igual de enfermo.
        self._caso_uid54()
        conn = main.get_db()
        try:
            conn.execute("INSERT INTO snapshots (user_id,date,total_value,"
                         "total_invested,net_deposited) VALUES (?,?,?,?,?)",
                         (self.uid, "2026-05-31", 5703773.00, 0, 0))
            conn.commit()
        finally:
            conn.close()
        u = self._u(self._run(apply=True))
        self.assertTrue(u["sigue_sucio_en_pantalla"])
        self.assertGreaterEqual(u["snapshots_sin_reparar"]["cantidad"], 1)
        self.assertIn("no es recomputable",
                      u["snapshots_sin_reparar"]["por_que_no_se_arreglan"])


if __name__ == "__main__":
    unittest.main()
