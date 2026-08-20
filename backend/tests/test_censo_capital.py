"""Censo de capital — quiénes tienen el número roto HOY.

La mitad de estos tests existen porque la v1 del módulo los fallaba. El patrón
que se repite —y que ya había mordido dos veces en censo_flujos— es aplicar un
umbral de plata sin mirar la moneda: con 1e6 parejo salían "350 usuarios con
costo imposible" y 349 eran cuentas normales en pesos.
"""
import unittest
import uuid

import main
from fastapi.testclient import TestClient


def _mk_user(conn, email, is_admin=0):
    return conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin) "
        "VALUES (?, 'x', 1, ?)", (email, is_admin)).lastrowid


class CensoCapitalTest(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:10]
        conn = main.get_db()
        self.admin_uid = _mk_user(conn, f"adm-{self.tag}@rendi.test", is_admin=1)
        self.uid = _mk_user(conn, f"cli-{self.tag}@rendi.test")
        conn.commit()
        conn.close()
        self.admin_h = {"Authorization": f"Bearer {main.create_token(self.admin_uid)}"}

    # ── helpers ─────────────────────────────────────────────────────────────
    def _monthly(self, capital_final, pnl=0.0, broker="global", ym=(2026, 7)):
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO monthly_entries (user_id,year,month,broker,deposits,"
                "withdrawals,pnl_realized,pnl_unrealized,capital_inicio,capital_final) "
                "VALUES (?,?,?,?,0,0,?,0,0,?)",
                (self.uid, ym[0], ym[1], broker, pnl, capital_final))
            conn.commit()
        finally:
            conn.close()

    def _snap(self, total_value, net_dep=0.0, date="2026-08-01"):
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO snapshots (user_id,date,total_value,total_invested,"
                "net_deposited,source) VALUES (?,?,?,?,?,'cron')",
                (self.uid, date, total_value, total_value, net_dep))
            conn.commit()
        finally:
            conn.close()

    def _pos(self, asset, invested, ccy="ARS", is_cash=0, buy_price=None):
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO positions (user_id,broker,asset,is_cash,buy_price,"
                "quantity,invested,currency) VALUES (?,'Cocos',?,?,?,1,?,?)",
                (self.uid, asset, is_cash, buy_price, invested, ccy))
            conn.commit()
        finally:
            conn.close()

    def _censo(self):
        r = self.http.get("/api/admin/censo-capital",
                          params={"target_uid": self.uid}, headers=self.admin_h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ── C1: la señal principal ──────────────────────────────────────────────
    def test_capital_declarado_muy_por_encima_de_la_cartera(self):
        # El caso uid 329 en miniatura: capital de millones, cartera de miles.
        self._monthly(capital_final=1_700_920_416.0)
        self._snap(total_value=18_323.55)
        c1 = self._censo()["c1_capital_vs_cartera"]
        self.assertEqual(c1["usuarios"], 1)
        self.assertEqual(c1["graves_ratio_100x"], 1)
        self.assertEqual(c1["detalle"][0]["causa"], "OTRA_COSA")

    def test_una_cuenta_sana_no_aparece(self):
        self._monthly(capital_final=50_000.0)
        self._snap(total_value=48_000.0)
        self.assertEqual(self._censo()["c1_capital_vs_cartera"]["usuarios"], 0)

    def test_atribuye_al_seed_cuando_el_seed_lo_explica(self):
        # Si el depósito sintético cubre la mayor parte del capital declarado,
        # el arreglo pasa por re-derivar su moneda. Si no, hay que buscar en
        # otro lado — y esa distinción es la que ordena el trabajo.
        bid = uuid.uuid4().hex[:12]
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO import_batches (id,user_id,broker,parser_format,"
                "file_hash,status) VALUES (?,?,'Cocos','test',?,'confirmed')",
                (bid, self.uid, bid))
            rid = conn.execute(
                "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
                "VALUES (?,0,'{}','valid')", (bid,)).lastrowid
            conn.execute(
                "INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,"
                "operation_type,gross_amount,gross_amount_usd,currency,notes) "
                "VALUES (?,?,'2026-07-01','Cocos','DEPOSIT',9e6,9e6,'USD',?)",
                (bid, rid, "Tenencia — aporte inicial sintético (Rendi)"))
            conn.commit()
        finally:
            conn.close()
        self._monthly(capital_final=10_000_000.0)
        self._snap(total_value=5_000.0)
        c1 = self._censo()["c1_capital_vs_cartera"]
        self.assertEqual(c1["explicados_por_seed"], 1)
        self.assertEqual(c1["detalle"][0]["causa"], "seed_sintetico")

    # ── C3: los tres defectos de la v1 ──────────────────────────────────────
    def test_un_costo_normal_en_PESOS_no_es_imposible(self):
        # ⭐ EL DEFECTO. Un millón de pesos son ~US$700. Con umbral único de 1e6
        # esto salía como "costo imposible" y ahogaba la señal real: 349 de 350
        # usuarios reportados eran cuentas sanas en pesos.
        self._pos("AL30", invested=5_000_000.0, ccy="ARS")
        self.assertEqual(self._censo()["c3_posicion_imposible"]["filas"], 0)

    def test_el_mismo_numero_en_DOLARES_si_es_imposible(self):
        self._pos("AAPL", invested=5_000_000.0, ccy="USD")
        self.assertEqual(self._censo()["c3_posicion_imposible"]["filas"], 1)

    def test_una_posicion_de_CASH_corrupta_no_se_excluye(self):
        # El peor caso de la base (uid 160, 1e17) vive en una fila is_cash=1,
        # que la v1 filtraba con COALESCE(is_cash,0)=0.
        self._pos("USD", invested=1.01e17, ccy="USD", is_cash=1)
        d = self._censo()["c3_posicion_imposible"]
        self.assertEqual(d["filas"], 1)
        self.assertEqual(d["detalle"][0]["is_cash"], 1)

    def test_un_precio_imposible_con_costo_chico_igual_se_ve(self):
        # La corrupción de PRECIO deja el costo chico —a veces negativo— así
        # que mirando sólo `invested` es invisible. Caso real: SPY a 3,66e14
        # con invested de −1.977.
        self._pos("SPY", invested=-1_977.0, ccy="USD", buy_price=3.662e14)
        d = self._censo()["c3_posicion_imposible"]
        self.assertEqual(d["filas"], 1)
        self.assertEqual(d["detalle"][0]["señal"], "precio")

    # ── C2 y C4 ─────────────────────────────────────────────────────────────
    def test_pnl_imposible_con_filtro_por_usuario(self):
        # Cubre además el orden de params: el uid va en el WHERE y el umbral en
        # el HAVING. Invertirlos no da error de SQL, da un resultado mal.
        self._monthly(capital_final=1000.0, pnl=73_900_000.0)
        self.assertEqual(self._censo()["c2_pnl_imposible"]["usuarios"], 1)

    def test_los_negativos_de_redondeo_no_cuentan(self):
        # Debajo de cero hay una cola larga de centavos: 247 usuarios contra 88
        # exigiendo −100. Sin piso, la señal real se ahoga.
        self._snap(total_value=-0.03, date="2026-08-02")
        self.assertEqual(self._censo()["c4_snapshots_negativos"]["usuarios"], 0)

    def test_un_negativo_de_verdad_si_cuenta(self):
        self._snap(total_value=-1_064_093.49, date="2026-08-03")
        self.assertEqual(self._censo()["c4_snapshots_negativos"]["usuarios"], 1)

    # ── Contrato ────────────────────────────────────────────────────────────
    def test_no_escribe_nada(self):
        self._monthly(capital_final=1_700_920_416.0)
        self._snap(total_value=18_323.55)
        self._pos("AAPL", invested=5_000_000.0, ccy="USD")
        tablas = ("monthly_entries", "snapshots", "positions", "import_normalized_tx")
        conn = main.get_db()
        try:
            antes = [conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] for t in tablas]
        finally:
            conn.close()
        self._censo()
        conn = main.get_db()
        try:
            despues = [conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] for t in tablas]
        finally:
            conn.close()
        self.assertEqual(antes, despues)

    def test_el_blast_radius_se_declara_como_piso(self):
        # El detalle está capeado por señal, así que la unión puede quedar
        # corta. Reportarlo como total exacto sería mentir por omisión.
        self.assertIn("PISO", self._censo()["blast_radius"]["caveat"].upper())

    def test_requiere_admin(self):
        r = self.http.get("/api/admin/censo-capital",
                          headers={"Authorization": f"Bearer {main.create_token(self.uid)}"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
