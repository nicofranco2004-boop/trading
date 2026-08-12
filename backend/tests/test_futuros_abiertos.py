"""Posiciones de futuros ABIERTAS (Fase 2).

La Fase 1 dejó cargar el resultado de un futuro YA cerrado. Esto es para el que
sigue abierto, donde lo que importa es el no realizado.

DOS DECISIONES DE DISEÑO QUE ESTOS TESTS FIJAN:

1. Viven en su propia tabla, NO en `positions`. En `positions` hay 116 lecturas
   en el backend y 7 consumidores en el front, y todas asumen que TENÉS el
   activo y que la exposición es POSITIVA. Un short vale al revés. Meterlo ahí
   ensuciaría en silencio cada cálculo de valor y de P&L de la app.

2. Abrir una posición NO toca el efectivo. En Binance mover plata del spot al
   wallet de futuros es interno —la USDT sigue en la cuenta— y el importador ya
   ignora esas transferencias. Descontar el margen haría que el saldo dejara de
   cerrar con el del broker.

Y el cierre no duplica nada: crea la MISMA operación `kind='futures'` de la
Fase 1, con su foto de reverso, para que se borre y se deshaga por el camino
que ya está probado.
"""
import unittest
import uuid

import main


class FuturosAbiertosTest(unittest.TestCase):
    CASH_INICIAL = 1000.0

    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
            (f"futab-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,'Binance','USDT')",
                     (self.uid,))
        conn.execute("""INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity)
                        VALUES (?,'Binance','USDT',1,?,?)""",
                     (self.uid, self.CASH_INICIAL, self.CASH_INICIAL))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    # ── helpers ──────────────────────────────────────────────────────────────

    def _cash(self):
        conn = main.get_db()
        r = conn.execute("SELECT COALESCE(invested,0) c FROM positions "
                         " WHERE user_id=? AND is_cash=1", (self.uid,)).fetchone()
        conn.close()
        return float(r["c"]) if r else 0.0

    def _pnl_realizado(self):
        conn = main.get_db()
        r = conn.execute("SELECT COALESCE(SUM(pnl_realized),0) p FROM monthly_entries "
                         " WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()
        conn.close()
        return float(r["p"])

    def _abrir(self, side="long", qty=0.5, entry=60000, symbol="BTCUSDT", **kw):
        cuerpo = {"broker": "Binance", "symbol": symbol, "side": side,
                  "quantity": qty, "entry_price": entry, "opened_at": "2026-08-01"}
        cuerpo.update(kw)
        r = self.client.post("/api/futures", headers=self.h, json=cuerpo)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _cerrar(self, fid, exit_price, **kw):
        r = self.client.post(f"/api/futures/{fid}/close", headers=self.h,
                             json={"exit_price": exit_price, "closed_at": "2026-08-11", **kw})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ── alta y listado ───────────────────────────────────────────────────────

    def test_abrir_una_posicion_NO_toca_el_efectivo(self):
        """El margen es interno del broker: la plata no salió de la cuenta."""
        self._abrir(margin_usd=300, leverage=10)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL, places=2)
        self.assertAlmostEqual(self._pnl_realizado(), 0, places=2)

    def test_el_listado_devuelve_solo_las_abiertas(self):
        a = self._abrir(entry=60000)
        self._abrir(entry=61000, symbol="ETHUSDT")
        self._cerrar(a["id"], 62000)
        abiertas = self.client.get("/api/futures", headers=self.h).json()
        self.assertEqual([p["symbol"] for p in abiertas], ["ETHUSDT"])
        todas = self.client.get("/api/futures?include_closed=true", headers=self.h).json()
        self.assertEqual(len(todas), 2)

    def test_el_par_se_traduce_al_subyacente_para_pedir_precio(self):
        """El feed cotiza BTC, no BTCUSDT. Si esto se rompe, el no realizado
        queda mudo (sin precio) en vez de mal — pero mudo igual no sirve."""
        casos = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSD": "SOL",
                 "BTCUSDC": "BTC", "ETHUSDT:USDT": "ETH", "SOL-PERP": "SOL"}
        for par, base in casos.items():
            self.assertEqual(main._base_asset_de(par), base, f"{par} → esperaba {base}")

    def test_expone_la_direccion_para_no_re_derivar_el_signo(self):
        self.assertEqual(self._abrir(side="long")["dir"], 1)
        self.assertEqual(self._abrir(side="short")["dir"], -1)

    def test_un_side_invalido_se_rechaza(self):
        r = self.client.post("/api/futures", headers=self.h, json={
            "broker": "Binance", "symbol": "BTCUSDT", "side": "arriba",
            "quantity": 1, "entry_price": 100, "opened_at": "2026-08-01"})
        self.assertEqual(r.status_code, 422)

    # ── el cierre: acá se mueve la plata ─────────────────────────────────────

    def test_cerrar_un_LONG_en_ganancia(self):
        p = self._abrir(side="long", qty=0.5, entry=60000)
        r = self._cerrar(p["id"], 62000)             # (62000−60000) × 0,5 = +1000
        self.assertAlmostEqual(r["pnl_usd"], 1000, places=2)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL + 1000, places=2)
        self.assertAlmostEqual(self._pnl_realizado(), 1000, places=2)

    def test_cerrar_un_LONG_en_perdida_DESCUENTA(self):
        p = self._abrir(side="long", qty=0.5, entry=60000)
        r = self._cerrar(p["id"], 59000)             # −500
        self.assertAlmostEqual(r["pnl_usd"], -500, places=2)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL - 500, places=2)

    def test_un_SHORT_GANA_cuando_el_precio_BAJA(self):
        """El corazón de la fase: el short vale al revés. Si el signo se
        invirtiera, un short ganador se registraría como pérdida y le sacaría
        plata al usuario del efectivo."""
        p = self._abrir(side="short", qty=0.5, entry=60000)
        r = self._cerrar(p["id"], 58000)             # (60000−58000) × 0,5 = +1000
        self.assertAlmostEqual(r["pnl_usd"], 1000, places=2)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL + 1000, places=2)

    def test_un_SHORT_PIERDE_cuando_el_precio_SUBE(self):
        p = self._abrir(side="short", qty=0.5, entry=60000)
        r = self._cerrar(p["id"], 62000)
        self.assertAlmostEqual(r["pnl_usd"], -1000, places=2)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL - 1000, places=2)

    def test_el_long_y_el_short_son_espejo_exacto(self):
        """Mismo movimiento de precio, resultado opuesto y de igual magnitud."""
        l = self._cerrar(self._abrir(side="long", qty=1, entry=100)["id"], 110)
        s = self._cerrar(self._abrir(side="short", qty=1, entry=100)["id"], 110)
        self.assertAlmostEqual(l["pnl_usd"], -s["pnl_usd"], places=2)

    def test_las_comisiones_restan_del_resultado(self):
        p = self._abrir(side="long", qty=0.5, entry=60000)
        r = self._cerrar(p["id"], 62000, commissions=25)
        self.assertAlmostEqual(r["pnl_usd"], 975, places=2)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL + 975, places=2)

    # ── el puente con la Fase 1 ──────────────────────────────────────────────

    def test_el_cierre_crea_la_MISMA_operacion_que_la_carga_a_mano(self):
        """No duplica el movimiento de efectivo: reusa el camino ya probado,
        con su foto de reverso, para que el borrado y el Deshacer funcionen."""
        import json
        p = self._abrir(side="long", qty=0.5, entry=60000)
        r = self._cerrar(p["id"], 62000)
        conn = main.get_db()
        op = conn.execute("SELECT * FROM operations WHERE id=?", (r["operation_id"],)).fetchone()
        conn.close()
        self.assertEqual(op["op_type"], "Futuros")
        self.assertEqual(op["asset"], "BTCUSDT")
        meta = json.loads(op["undo_meta_json"])
        self.assertEqual(meta["src"], "manual_futures")
        self.assertAlmostEqual(meta["cash"], 1000, places=2)

    def test_borrar_esa_operacion_devuelve_el_efectivo(self):
        p = self._abrir(side="long", qty=0.5, entry=60000)
        r = self._cerrar(p["id"], 62000)
        d = self.client.delete(f"/api/operations/{r['operation_id']}", headers=self.h)
        self.assertEqual(d.status_code, 200, d.text)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL, places=2)

    # ── bordes del cierre ────────────────────────────────────────────────────

    def test_no_se_puede_cerrar_dos_veces(self):
        """Sin esta guarda, cerrar dos veces acreditaría el resultado dos veces."""
        p = self._abrir(side="long", qty=0.5, entry=60000)
        self._cerrar(p["id"], 62000)
        r = self.client.post(f"/api/futures/{p['id']}/close", headers=self.h,
                             json={"exit_price": 62000})
        self.assertEqual(r.status_code, 400)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL + 1000, places=2)

    def test_cerrar_al_mismo_precio_no_mueve_nada(self):
        p = self._abrir(side="long", qty=0.5, entry=60000)
        r = self._cerrar(p["id"], 60000)
        self.assertAlmostEqual(r["pnl_usd"], 0, places=2)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL, places=2)

    # ── aislamiento: lo de siempre no se movió ───────────────────────────────

    def test_un_futuro_abierto_NO_aparece_en_las_posiciones_normales(self):
        """La decisión de diseño de la fase. Si apareciera, entraría en los 116
        lugares que asumen exposición positiva."""
        self._abrir(side="short", qty=2, entry=100, margin_usd=500)
        pos = self.client.get("/api/positions", headers=self.h).json()
        filas = pos if isinstance(pos, list) else pos.get("positions", [])
        simbolos = [str(p.get("asset", "")).upper() for p in filas]
        self.assertNotIn("BTCUSDT", simbolos)

    def test_borrar_una_posicion_abierta_no_mueve_plata(self):
        p = self._abrir(side="long", qty=1, entry=100, margin_usd=500)
        r = self.client.delete(f"/api/futures/{p['id']}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL, places=2)
        self.assertEqual(self.client.get("/api/futures", headers=self.h).json(), [])

    def test_borrar_una_CERRADA_se_rechaza_con_explicacion(self):
        """Su resultado ya se acreditó; borrarla acá dejaría el efectivo inflado."""
        p = self._abrir(side="long", qty=0.5, entry=60000)
        self._cerrar(p["id"], 62000)
        r = self.client.delete(f"/api/futures/{p['id']}", headers=self.h)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Movimientos", r.json()["detail"])
        self.assertAlmostEqual(self._cash(), self.CASH_INICIAL + 1000, places=2)

    # ── aislamiento entre usuarios ───────────────────────────────────────────

    def test_no_se_puede_ver_ni_cerrar_el_futuro_de_otro(self):
        p = self._abrir()
        conn = main.get_db()
        otro = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
            (f"otro-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
        conn.commit(); conn.close()
        h2 = {"Authorization": f"Bearer {main.create_token(otro)}"}
        self.assertEqual(self.client.get("/api/futures", headers=h2).json(), [])
        self.assertEqual(
            self.client.post(f"/api/futures/{p['id']}/close", headers=h2,
                             json={"exit_price": 1}).status_code, 404)
        self.assertEqual(
            self.client.delete(f"/api/futures/{p['id']}", headers=h2).status_code, 404)


if __name__ == "__main__":
    unittest.main()
