"""Cobros de bonos AL AZAR: confirmar, borrar, deshacer e importar mezclados.

Las pruebas armadas a mano (test_cupones_bandeja.py) cubren los caminos que uno
se imagina. Ésta tira secuencias al azar de las cuatro puertas que tocan un cobro
de bono —confirmar desde la bandeja (/api/bonds/cashflow/pago), borrar desde
Movimientos, deshacer el borrado, importar el archivo del broker con el mismo
pago— sobre cuentas al azar (bono importado o cargado a mano, en la cuenta en
pesos con cobro en dólares, o en una cuenta en dólares) y después de CADA paso
verifica que la contabilidad cierre:

  · nada devuelve 500;
  · un pago no queda anotado dos veces (a mano + importado, o dos confirmados);
  · el efectivo de cada cuenta = lo que tenía antes + lo que dicen los cobros vivos;
  · los nominales de un lote a mano bajan exactamente lo que amortizaron los cobros
    vivos, y los de un lote importado no los toca ningún cobro (los baja el barrido);
  · la ganancia realizada del mes = la suma de las operaciones (el recálculo cierra);
  · borrar y deshacer deja todo como estaba.

RENDI_AZAR=500 corre 500 escenarios (por defecto 40, para que la suite no tarde).
"""
import io
import json
import os
import random
import unittest

from fastapi.testclient import TestClient

import main
import realized_pnl

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"
N = int(os.environ.get("RENDI_AZAR", "40"))
SEMILLA = int(os.environ.get("RENDI_AZAR_SEMILLA", "20261009"))

# Pagos del cronograma (cupón, amortización) por 10.000 nominales originales.
PAGOS = {
    "AL30": {"2025-07-09": (33.0, 800.0), "2026-01-09": (30.0, 800.0), "2026-07-09": (27.0, 800.0)},
    "GD35": {"2025-07-09": (75.0, 0.0), "2026-01-09": (75.0, 0.0), "2026-07-09": (75.0, 0.0)},
}


def _csv(*rows):
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


class CobrosDeBonosAlAzarTest(unittest.TestCase):

    def _limpiar(self):
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "bond_cashflow_skips", "deleted_ops_journal",
                  "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()

    def setUp(self):
        self.conn = main.get_db()

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        self.conn.close()

    # ── la cuenta ────────────────────────────────────────────────────────────
    def _armar(self, rng):
        self._limpiar()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("azar_bonos@rendi.test", "x")).lastrowid
        for name, ccy, parent in (("Cocos", "ARS", None), ("Cocos · USD", "USDT", "Cocos"),
                                  ("IOL", "USDT", None)):
            pid = None
            if parent:
                pid = self.conn.execute("SELECT id FROM brokers WHERE user_id=? AND name=?",
                                        (self.uid, parent)).fetchone()["id"]
            self.conn.execute("INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
                              "VALUES (?,?,?,?)", (self.uid, name, ccy, pid))
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.c = TestClient(main.app)
        self.bonos = {}          # asset → (broker del bono, cuenta del cobro, a_mano)
        if rng.random() < 0.5:
            self._importar("Cocos", "2024-01-02,DEPOSITO,Cocos,,,,20000000,,,0,ARS,",
                           "2024-01-15,COMPRA,Cocos,AL30,10000,600,6000000,,,0,ARS,")
            self.bonos["AL30"] = ("Cocos", "Cocos · USD", False)
        else:
            # Cargado a mano: ya registró las amortizaciones hasta enero 2025 (vivo 88 %).
            self.conn.execute(
                """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                       invested, tc_compra, entry_date, commissions, asset_type, currency)
                   VALUES (?, 'Cocos', 'AL30', 0, 600, 8800, 5280000, 1000, '2024-01-15', 0, 'BOND', 'ARS')""",
                (self.uid,))
            self.conn.commit()
            self.bonos["AL30"] = ("Cocos", "Cocos · USD", True)
        if rng.random() < 0.6:
            self._importar("IOL", "2024-01-02,DEPOSITO,IOL,,,,10000,,,0,USD,",
                           "2024-01-15,COMPRA,IOL,GD35,10000,0.5,5000,,,0,USD,")
            self.bonos["GD35"] = ("IOL", "IOL", False)

    def _importar(self, broker, *rows):
        r = self.c.post("/api/imports/preview",
                        files=[("files", ("x.csv", io.BytesIO(_csv(*rows)), "text/csv"))],
                        data={"format": "rendi_generic", "broker": broker})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.c.post("/api/imports/confirm", json={"session_id": r.json()["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)

    # ── la foto de la contabilidad ───────────────────────────────────────────
    def _foto(self):
        caja = {r["broker"]: round(float(r["invested"] or 0), 4) for r in self.conn.execute(
            "SELECT broker, invested FROM positions WHERE user_id=? AND is_cash=1", (self.uid,))}
        lotes = {(r["broker"], r["asset"]): round(float(r["q"] or 0), 4) for r in self.conn.execute(
            "SELECT broker, asset, SUM(quantity) q FROM positions WHERE user_id=? AND is_cash=0 "
            "GROUP BY broker, asset", (self.uid,))}
        ops = sorted((r["date"], r["broker"], r["asset"], r["op_type"], round(float(r["quantity"] or 0), 4),
                      round(float(r["pnl_usd"] or 0), 4)) for r in self.conn.execute(
            "SELECT * FROM operations WHERE user_id=?", (self.uid,)))
        return {"caja": caja, "lotes": lotes, "ops": ops}

    def _originales(self):
        """{(broker, bono): nominales originales según /api/positions}. Lo manda el
        servidor por lote: exacto si lo lleva el barrido; si no, la cantidad con
        que nació (se suman, que es lo que hace la pantalla con cada grupo)."""
        out = {}
        for p in self.c.get("/api/positions").json():
            if p.get("is_cash") or p["asset"] not in PAGOS:
                continue
            v = p.get("nominal_original", p.get("nominal_al_cargar"))
            out[(p["broker"], p["asset"])] = round(out.get((p["broker"], p["asset"]), 0) + float(v), 4)
        return out

    def _cobros(self):
        out = []
        for r in self.conn.execute(
                "SELECT o.*, (SELECT 1 FROM import_op_links l WHERE l.operation_id=o.id) imp "
                "FROM operations o WHERE o.user_id=? AND o.asset IN ('AL30','GD35')", (self.uid,)):
            d = dict(r)
            meta = json.loads(d["undo_meta_json"] or "{}") if d.get("undo_meta_json") else {}
            d["meta"] = meta
            d["a_mano"] = meta.get("src") == "bond_cashflow"
            out.append(d)
        return out

    # ── los invariantes ──────────────────────────────────────────────────────
    def _verificar(self, base, paso):
        cobros = self._cobros()
        # 1. Nada anotado dos veces: por bono y pago, o todo a mano (una fecha) o todo importado.
        for asset, pagos in PAGOS.items():
            for fecha in pagos:
                cerca = [o for o in cobros if o["asset"] == asset
                         and abs((_d(o["date"]) - _d(fecha)).days) <= 14]
                a_mano = {o["date"] for o in cerca if o["a_mano"]}
                importados = [o for o in cerca if not o["a_mano"]]
                self.assertFalse(a_mano and importados, f"{paso}: {asset} {fecha} a mano + importado")
                self.assertLessEqual(len(a_mano), 1, f"{paso}: {asset} {fecha} confirmado dos veces")
                tipos = [o["op_type"] for o in cerca if o["a_mano"]]
                self.assertEqual(len(tipos), len(set(tipos)), f"{paso}: {asset} {fecha} mismo tipo dos veces")
                self.assertLessEqual(len(importados), 1, f"{paso}: {asset} {fecha} importado dos veces")
        # 2. Efectivo = base + cobros vivos (a mano: lo que acreditó; importado: el monto).
        esperado = dict(base["caja"])
        for o in cobros:
            cuenta = o["broker"]
            monto = float(o["meta"].get("cash") or 0) if o["a_mano"] else float(o["quantity"] or 0)
            esperado[cuenta] = round(esperado.get(cuenta, 0) + monto, 4)
        real = self._foto()["caja"]
        for cuenta, v in esperado.items():
            self.assertAlmostEqual(real.get(cuenta, 0), v, places=2, msg=f"{paso}: efectivo de {cuenta}")
        # 3. Nominales: a mano bajan lo amortizado por los cobros vivos; importados, nada.
        for asset, (broker, _, a_mano) in self.bonos.items():
            antes = base["lotes"].get((broker, asset), 0)
            bajado = sum(float(o["meta"].get("qty_decremented") or 0) for o in cobros
                         if o["asset"] == asset and o["a_mano"])
            ahora = self._foto()["lotes"].get((broker, asset), 0)
            if a_mano:
                self.assertAlmostEqual(ahora, round(antes - bajado, 4), places=3, msg=f"{paso}: nominal {asset}")
            else:
                self.assertAlmostEqual(bajado, 0, places=6, msg=f"{paso}: cobro bajó nominal importado")
                self.assertAlmostEqual(ahora, antes, places=3, msg=f"{paso}: nominal {asset} importado")
        # 4. La ganancia realizada del mes cierra con las operaciones.
        main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        self.conn.commit()
        mensual = float(self.conn.execute(
            "SELECT COALESCE(SUM(pnl_realized),0) FROM monthly_entries WHERE user_id=? AND broker='global'",
            (self.uid,)).fetchone()[0])
        ops = float(self.conn.execute(
            f"SELECT COALESCE(SUM({realized_pnl.realized_usd_sql()}),0) FROM operations "
            f"WHERE user_id=? AND pnl_usd IS NOT NULL AND {realized_pnl.no_es_conversion_sql()}",
            (self.uid,)).fetchone()[0])
        self.assertAlmostEqual(mensual, ops, places=2, msg=f"{paso}: ganancia realizada")
        # 6. Los nominales ORIGINALES que ve la bandeja no cambian por confirmar,
        #    borrar, deshacer ni importar cobros: el pago que propone no depende del
        #    orden en que se hayan anotado los demás.
        orig = self._originales()
        self.assertEqual(set(orig), set(base["originales"]), f"{paso}: lotes de bonos")
        for k, v in base["originales"].items():
            self.assertAlmostEqual(orig[k], v, places=2, msg=f"{paso}: nominal original de {k}")
        # 5. Una amortización a mano nunca anota como ganancia más de lo que cobró.
        for o in cobros:
            if o["a_mano"] and o["op_type"] == "Amortización":
                self.assertLessEqual(float(o["pnl_usd"] or 0), float(o["quantity"] or 0) + 1e-6, paso)

    # ── las acciones ─────────────────────────────────────────────────────────
    def _ya_hay(self, asset, fecha):
        return any(o["asset"] == asset and abs((_d(o["date"]) - _d(fecha)).days) <= 14
                   for o in self._cobros())

    def _accion(self, rng, ultimo_token, paso):
        asset = rng.choice(sorted(self.bonos))
        broker, cuenta, _ = self.bonos[asset]
        fecha = rng.choice(sorted(PAGOS[asset]))
        cup, amo = PAGOS[asset][fecha]
        que = rng.choice(["pago", "pago", "formulario", "borrar", "deshacer", "importar"])
        if que == "formulario":
            # El formulario viejo carga cupón y amortización POR SEPARADO: se frena
            # lo del mismo tipo ya cargado a mano, o cualquier cobro importado.
            flujo = rng.choice(["coupon", "amortization"]) if amo else "coupon"
            tipo = "Cupón" if flujo == "coupon" else "Amortización"
            cerca = [o for o in self._cobros() if o["asset"] == asset
                     and abs((_d(o["date"]) - _d(fecha)).days) <= 14]
            choca = any((not o["a_mano"]) or o["op_type"] == tipo for o in cerca)
            r = self.c.post("/api/bonds/cashflow", json={
                "broker": broker, "asset": asset, "date": fecha, "flow_type": flujo,
                "amount": cup if flujo == "coupon" else amo, "cash_broker": cuenta,
                "decrement_quantity": flujo == "amortization"})
            self.assertEqual(r.status_code, 409 if choca else 200, f"{paso}: {r.text}")
            return None
        if que == "pago":
            habia = self._ya_hay(asset, fecha)
            r = self.c.post("/api/bonds/cashflow/pago", json={
                "broker": broker, "asset": asset, "date": fecha, "coupon_amount": cup,
                "amort_amount": amo, "cash_broker": cuenta,
                "commissions": rng.choice([0, 0, 1.5])})
            self.assertEqual(r.status_code, 409 if habia else 200, f"{paso}: {r.text}")
            return None
        if que == "borrar":
            a_mano = [o for o in self._cobros() if o["a_mano"]]
            if not a_mano:
                return ultimo_token
            o = rng.choice(a_mano)
            antes = self._foto()
            r = self.c.delete(f"/api/movements/op-{o['id']}-cobro")
            self.assertEqual(r.status_code, 200, f"{paso}: {r.text}")
            return (r.json().get("undo_token"), antes)
        if que == "deshacer":
            if not ultimo_token or not ultimo_token[0]:
                return None
            token, antes = ultimo_token
            r = self.c.post(f"/api/operations/undo/{token}")
            self.assertIn(r.status_code, (200, 409, 410), f"{paso}: {r.text}")
            if r.status_code == 200:
                ahora = self._foto()
                self.assertEqual(ahora["caja"], antes["caja"], f"{paso}: deshacer no devolvió el efectivo")
                self.assertEqual(ahora["lotes"], antes["lotes"], f"{paso}: deshacer no devolvió el nominal")
                self.assertEqual(ahora["ops"], antes["ops"], f"{paso}: deshacer no devolvió la operación")
            return None
        # importar el archivo con el mismo pago (el broker acredita al día siguiente)
        if self._ya_hay(asset, fecha) and any(
                not o["a_mano"] and o["asset"] == asset and abs((_d(o["date"]) - _d(fecha)).days) <= 14
                for o in self._cobros()):
            return ultimo_token         # ya importado: un segundo archivo igual es otro tema
        dia = fecha[:8] + "10"
        if asset == "AL30":
            self._importar("Cocos", f"{dia},RENTA Y AMORTIZACION,Cocos,AL30,,,{cup + amo},,,0,USD,")
        else:
            self._importar("IOL", f"{dia},RENTA,IOL,GD35,,,{cup},,,0,USD,")
        return None

    def test_al_azar(self):
        rng = random.Random(SEMILLA)
        for n in range(N):
            self._armar(rng)
            base = self._foto()
            base["originales"] = self._originales()
            token = None
            for k in range(rng.randint(4, 12)):
                paso = f"escenario {n} paso {k}"
                token = self._accion(rng, token, paso)
                self._verificar(base, paso)


def _d(iso):
    from datetime import date
    return date.fromisoformat(str(iso)[:10])


if __name__ == "__main__":
    unittest.main()
