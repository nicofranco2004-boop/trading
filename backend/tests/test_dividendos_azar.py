"""La bandeja de dividendos contra secuencias AL AZAR (regla del repo: las sondas
armadas no alcanzan — 242 casos "limpios" no vieron lo que 1.000 al azar sí).

Mezcla, por las MISMAS puertas HTTP que la app: confirmar un cobro (con montos y
comisión al azar), borrarlo desde Movimientos, deshacer ese borrado, importar un
archivo con un dividendo (con o sin activo, con monto parecido o no), revertir
ese import y "No lo cobré". Después de CADA paso revisa que:

  1. La plata cierra: lo que hay en las dos cuentas (dólares + pesos al TC) menos
     lo que había al empezar es exactamente lo que dicen las filas 'Dividendo'
     vivas (lo que llegó − la comisión en pesos, para las confirmadas; el monto,
     para las importadas). Un borrado que no devuelve, un reemplazo que no saca
     el confirmado o una comisión colgada rompen esto.
  2. La ganancia realizada del mes es la suma de esas filas (el recálculo no se
     quedó atrás ni contó dos veces).
  3. Nada es un depósito: el capital aportado sigue en cero.
  4. Nunca conviven un dividendo confirmado desde la bandeja y uno importado de la
     misma empresa para el mismo corte (sería cobrarlo dos veces), ni dos
     confirmados del mismo corte.
"""
import io
import json
import os
import random
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from fastapi.testclient import TestClient  # noqa: E402

import dividendos  # noqa: E402
import main  # noqa: E402

TC = 1450.0
HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"
CORTES = {"KO": ["2026-06-15", "2026-09-15"], "PEP": ["2026-06-05", "2026-09-04"]}
BASE_USD, BASE_ARS = 1240.50, 100000.0
SEMILLAS = [int(s) for s in os.environ.get("SEMILLAS_DIVIDENDOS", "1,2,3,4,5,6").split(",")]
PASOS = int(os.environ.get("PASOS_DIVIDENDOS", "35"))


def _csv(fecha, activo, monto):
    return (HDR + f"{fecha},DIVIDENDO,Balanz,{activo},,,{monto},,,0,USD,\n").encode()


class DividendosAlAzar(unittest.TestCase):

    def setUp(self):
        self.conn = main.get_db()
        try:
            self.conn.execute("DELETE FROM fx_rates_daily")
        except Exception:
            pass
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows", "import_batches",
                  "operations", "positions", "monthly_entries", "snapshots", "deleted_ops_journal",
                  "dividendos_salteados", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        import datetime as dt
        d = dt.date(2026, 6, 1)
        while d <= dt.date(2026, 10, 9):
            self.conn.execute(
                "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source, fetched_at) "
                "VALUES (?,?,?,?,datetime('now'))", (d.isoformat(), TC, TC, "test"))
            d += dt.timedelta(days=1)
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("azar@rendi.test", "x")).lastrowid
        padre = self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                                  (self.uid, "Balanz", "ARS")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency, parent_broker_id) VALUES (?,?,?,?)",
                          (self.uid, "Balanz · USD", "USDT", padre))
        for a, q in (("KO", 150), ("PEP", 90)):
            self.conn.execute(
                """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                       invested, entry_date, asset_type, currency)
                   VALUES (?,?,?,0,1000,?,?, '2026-01-01','CEDEAR','ARS')""",
                (self.uid, "Balanz", a, q, 1000 * q))
        self.conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested) VALUES (?,?,?,1,?)",
                          (self.uid, "Balanz", "ARS", BASE_ARS))
        self.conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested) VALUES (?,?,?,1,?)",
                          (self.uid, "Balanz · USD", "USDT", BASE_USD))
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        self.conn.close()

    # ── lecturas ─────────────────────────────────────────────────────────────
    def caja(self, broker):
        return float(self.conn.execute(
            "SELECT COALESCE(SUM(invested),0) FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
            (self.uid, broker)).fetchone()[0])

    def filas(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM operations WHERE user_id=? AND op_type='Dividendo'", (self.uid,))]

    def invariantes(self, paso, historia):
        donde = f"paso {paso}: " + " → ".join(historia[-6:])
        self.conn.commit()
        efecto = 0.0
        confirmados, importados = [], []
        for f in self.filas():
            meta = json.loads(f["undo_meta_json"]) if f.get("undo_meta_json") else {}
            if meta.get("src") == dividendos.SRC:
                efecto += float(meta["cash"]) - float(meta.get("comision_pesos") or 0) / TC
                confirmados.append((f["asset"], meta["ex_date"], f))
            else:
                efecto += float(f["pnl_usd"])
                importados.append(f)
        real = (self.caja("Balanz · USD") - BASE_USD) + (self.caja("Balanz") - BASE_ARS) / TC
        self.assertAlmostEqual(real, efecto, places=2, msg=f"la plata no cierra — {donde}")
        pnl = self.conn.execute(
            "SELECT COALESCE(SUM(pnl_realized),0), COALESCE(SUM(deposits),0) FROM monthly_entries "
            "WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()
        suma_filas = sum(float(f["pnl_usd"]) for f in self.filas())
        self.assertAlmostEqual(float(pnl[0]), suma_filas, places=2,
                               msg=f"la ganancia realizada no es la suma de los cobros — {donde}")
        self.assertAlmostEqual(float(pnl[1]), 0.0, places=6, msg=f"un dividendo quedó como depósito — {donde}")
        vistos = set()
        for a, ex, _ in confirmados:
            self.assertNotIn((a, ex), vistos, f"dos confirmados del mismo corte — {donde}")
            vistos.add((a, ex))
            desde, hasta = dividendos._ventana(ex)
            for imp in importados:
                if (imp["asset"] or "").upper() == a and desde <= imp["date"][:10] <= hasta:
                    self.fail(f"{a} {ex} confirmado E importado a la vez — {donde}")

    # ── acciones ─────────────────────────────────────────────────────────────
    def confirmar(self, rnd):
        asset = rnd.choice(list(CORTES))
        ex = rnd.choice(CORTES[asset])
        bruto = round(rnd.uniform(1, 30), 2)
        impuesto = round(bruto * rnd.choice([0.3, 0.3, 0.15, 0]), 2)
        otros = round(bruto * rnd.choice([0.05, 0, 0.02]), 2)
        com = round(rnd.choice([0, 0, 25.5, 66.75, 140]), 2)
        # Fechas dentro y FUERA de la ventana del corte: las de afuera tienen que
        # rebotar (400) y no dejar nada a medias.
        fecha = rnd.choice(["2026-10-06", "2026-10-01", ex])
        r = self.client.post("/api/dividendos/cobro", json=dict(
            broker="Balanz", asset=asset, ex_date=ex, fecha=fecha,
            bruto=bruto, impuesto=impuesto, otros=otros, comision_pesos=com))
        self.assertIn(r.status_code, (200, 400, 409), r.text)
        return f"confirmar {asset} {ex} → {r.status_code}"

    def borrar(self, rnd):
        movs = self.client.get("/api/movements").json()
        movs = movs if isinstance(movs, list) else movs.get("movements", [])
        divs = [m for m in movs if m["type"] == "DIVIDEND" and str(m["id"]).startswith("op-")]
        if not divs:
            return "borrar (nada)"
        m = rnd.choice(divs)
        r = self.client.delete(f"/api/movements/{m['id']}")
        self.assertIn(r.status_code, (200, 400, 409), r.text)
        if r.status_code == 200 and r.json().get("undo_token"):
            self.tokens.append(r.json()["undo_token"])
        return f"borrar {m['asset']} → {r.status_code}"

    def deshacer(self, rnd):
        if not self.tokens:
            return "deshacer (nada)"
        tok = self.tokens.pop()
        r = self.client.post(f"/api/operations/undo/{tok}")
        self.assertIn(r.status_code, (200, 400, 404, 409), r.text)
        return f"deshacer → {r.status_code}"

    def importar(self, rnd):
        asset = rnd.choice(list(CORTES) + [""])
        base = rnd.choice(CORTES["KO"] + CORTES["PEP"])
        import datetime as dt
        fecha = (dt.date.fromisoformat(base) + dt.timedelta(days=rnd.choice([3, 21, 30, 60]))).isoformat()
        monto = round(rnd.uniform(1, 30), 2)
        r = self.client.post("/api/imports/preview",
                             files=[("files", ("x.csv", io.BytesIO(_csv(fecha, asset, monto)), "text/csv"))],
                             data={"format": "rendi_generic", "broker": "Balanz"})
        self.assertEqual(r.status_code, 200, r.text)
        sid = r.json()["session_id"]
        r = self.client.post("/api/imports/confirm", json={"session_id": sid, "skip_row_indices": [],
                                                           "aprobar_tickers": []})
        self.assertIn(r.status_code, (200, 400, 409), r.text)
        if r.status_code == 200:
            self.lotes.append(sid)
        return f"importar {asset or '—'} {fecha} {monto} → {r.status_code}"

    def revertir(self, rnd):
        if not self.lotes:
            return "revertir (nada)"
        sid = self.lotes.pop(rnd.randrange(len(self.lotes)))
        r = self.client.post(f"/api/imports/{sid}/revert")
        self.assertIn(r.status_code, (200, 400, 409), r.text)
        return f"revertir → {r.status_code}"

    def saltear(self, rnd):
        asset = rnd.choice(list(CORTES))
        r = self.client.post("/api/dividendos/saltear",
                             json={"broker": "Balanz", "asset": asset, "ex_date": rnd.choice(CORTES[asset])})
        self.assertEqual(r.status_code, 200, r.text)
        return f"saltear {asset}"

    def test_secuencias_al_azar(self):
        acciones = [self.confirmar] * 4 + [self.borrar] * 3 + [self.deshacer] * 2 + \
                   [self.importar] * 2 + [self.revertir] + [self.saltear]
        for semilla in SEMILLAS:
            with self.subTest(semilla=semilla):
                self.setUp()
                rnd = random.Random(semilla)
                self.tokens, self.lotes, historia = [], [], []
                for paso in range(PASOS):
                    historia.append(rnd.choice(acciones)(rnd))
                    self.invariantes(paso, historia)
                self.tearDown()


if __name__ == "__main__":
    unittest.main()
