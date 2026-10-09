"""La bandeja de dividendos de Cartera: confirmar un cobro y todo lo que toca.

Decisiones que estos tests fijan (Nico, 2026-10-09):
  · lo confirmado entra al efectivo del broker — los dólares a la cuenta en
    dólares, la comisión en pesos a la cuenta en pesos;
  · aparece en Movimientos como "Dividendo" (no como "Venta");
  · cuenta como GANANCIA REALIZADA, neta de impuesto y comisiones, y NO como
    depósito: el capital aportado no se mueve;
  · si después se importa el archivo del broker con el mismo dividendo, el dato
    del broker REEMPLAZA al confirmado: no se cuenta dos veces.

Todo entra por las MISMAS puertas HTTP que la app (confirmar, Movimientos, borrar
un movimiento, deshacer, importar). Lo único reemplazado es el login
(`dependency_overrides`) y Yahoo.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

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

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"
TC = 1450.0
CORTE = "2026-09-15"
COBRO = "2026-10-06"
# Coca-Cola: 150 CEDEARs (5 por acción) = 30 acciones × US$ 0,53 = US$ 15,90.
KO = dict(broker="Balanz", asset="KO", ex_date=CORTE, fecha=COBRO,
          bruto=15.90, impuesto=4.77, otros=0.80, comision_pesos=62.0, cedears=150)
NETO = 10.33


def _csv(*rows: str) -> bytes:
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


class _Base(unittest.TestCase):

    def setUp(self):
        self.conn = main.get_db()
        # `fx_rates_daily` es GLOBAL: primero y en su propio try (ver
        # reference_tests_una_base_por_modulo).
        try:
            self.conn.execute("DELETE FROM fx_rates_daily")
        except Exception:
            pass
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "deleted_ops_journal", "dividendos_salteados",
                  "dividendos_pagados", "dividendos_emisor", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        for d in ("2026-09-15", "2026-10-01", "2026-10-06", "2026-10-07"):
            self.conn.execute(
                "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source, fetched_at) "
                "VALUES (?,?,?,?,datetime('now'))", (d, TC, TC, "test"))
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("dividendos@rendi.test", "x")).lastrowid
        padre = self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, "Balanz", "ARS")).lastrowid
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency, parent_broker_id) VALUES (?,?,?,?)",
            (self.uid, "Balanz · USD", "USDT", padre))
        # La tenencia: 150 CEDEARs de KO en la cuenta en pesos, comprados en agosto.
        self.conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                   invested, entry_date, asset_type, currency)
               VALUES (?,?,?,0,?,?,?,?,?,?)""",
            (self.uid, "Balanz", "KO", 14000, 150, 2100000, "2026-08-01", "CEDEAR", "ARS"))
        # Efectivo de partida, para ver los movimientos.
        self.conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested) "
                          "VALUES (?,?,?,1,?)", (self.uid, "Balanz", "ARS", 100000.0))
        self.conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested) "
                          "VALUES (?,?,?,1,?)", (self.uid, "Balanz · USD", "USDT", 1240.50))
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        self.conn.close()

    # ── lecturas ─────────────────────────────────────────────────────────────
    def caja(self, broker):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(invested),0) FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
            (self.uid, broker)).fetchone()
        return round(float(r[0]), 4)

    def dividendos(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM operations WHERE user_id=? AND op_type='Dividendo' ORDER BY id",
            (self.uid,))]

    def mes(self, broker="global", y=2026, m=10):
        r = self.conn.execute(
            "SELECT pnl_realized, deposits, withdrawals FROM monthly_entries "
            "WHERE user_id=? AND broker=? AND year=? AND month=?",
            (self.uid, broker, y, m)).fetchone()
        return dict(r) if r else {"pnl_realized": 0.0, "deposits": 0.0, "withdrawals": 0.0}

    def aportado(self):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(deposits),0) - COALESCE(SUM(withdrawals),0) FROM monthly_entries "
            "WHERE user_id=? AND broker='global'", (self.uid,)).fetchone()
        return round(float(r[0]), 4)

    def movimientos(self):
        r = self.client.get("/api/movements")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        return body if isinstance(body, list) else (body.get("movements") or body.get("items") or [])

    def confirmar(self, **cambios):
        r = self.client.post("/api/dividendos/cobro", json={**KO, **cambios})
        return r

    def importar(self, csv_bytes: bytes, broker="Balanz"):
        r = self.client.post(
            "/api/imports/preview",
            files=[("files", ("x.csv", io.BytesIO(csv_bytes), "text/csv"))],
            data={"format": "rendi_generic", "broker": broker})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/imports/confirm", json={
            "session_id": r.json()["session_id"], "skip_row_indices": [], "aprobar_tickers": []})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


# ═════════════════════════════════════════════════════════════════════════════
class ConfirmarElCobro(_Base):

    def test_entra_a_la_cuenta_en_dolares_y_la_comision_sale_de_la_de_pesos(self):
        r = self.confirmar()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self.caja("Balanz · USD"), 1240.50 + NETO, places=2)
        self.assertAlmostEqual(self.caja("Balanz"), 100000 - 62, places=2)
        divs = self.dividendos()
        self.assertEqual(len(divs), 1)
        d = divs[0]
        self.assertEqual((d["broker"], d["asset"], d["date"]), ("Balanz · USD", "KO", COBRO))
        meta = json.loads(d["undo_meta_json"])
        self.assertEqual(meta["src"], dividendos.SRC)
        self.assertEqual(meta["ex_date"], CORTE)

    def test_es_ganancia_realizada_neta_y_no_toca_el_capital_aportado(self):
        aportado_antes = self.aportado()
        self.assertEqual(self.confirmar().status_code, 200)
        ganancia = NETO - 62 / TC
        self.assertAlmostEqual(self.mes()["pnl_realized"], ganancia, places=2,
                               msg="el dividendo no quedó como ganancia realizada del mes")
        self.assertAlmostEqual(self.mes()["deposits"], 0.0, places=6,
                               msg="el dividendo se anotó como DEPÓSITO")
        self.assertAlmostEqual(self.aportado(), aportado_antes, places=6)

    def test_movimientos_lo_muestra_como_dividendo_y_no_como_venta(self):
        self.assertEqual(self.confirmar().status_code, 200)
        filas = [m for m in self.movimientos()
                 if (m.get("asset") or "") == "KO" and m["type"] != "BUY"]
        self.assertEqual([m["type"] for m in filas], ["DIVIDEND"], filas)
        m = filas[0]
        self.assertAlmostEqual(m["amount_usd"], NETO, places=2)
        # Comisiones: los otros descuentos + la comisión en pesos pasada a dólares.
        self.assertAlmostEqual(m["fees_usd"], 0.80 + 62 / TC, places=3)
        self.assertIn("impuesto EE.UU. US$ 4,77", m["notes"])

    def test_dos_clicks_no_lo_anotan_dos_veces(self):
        self.assertEqual(self.confirmar().status_code, 200)
        r = self.confirmar()
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(len(self.dividendos()), 1)
        self.assertAlmostEqual(self.caja("Balanz · USD"), 1240.50 + NETO, places=2)

    def test_editado_por_el_usuario_se_anota_su_numero(self):
        r = self.confirmar(bruto=16.00, impuesto=4.80, otros=0.0, comision_pesos=0)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self.caja("Balanz · USD"), 1240.50 + 11.20, places=2)
        self.assertAlmostEqual(self.caja("Balanz"), 100000, places=2)

    def test_rechaza_lo_que_no_es_un_cobro(self):
        for cambios, codigo in (
                (dict(fecha="2099-01-01"), 400),               # fecha futura
                (dict(ex_date="2026-10-20"), 400),             # cobro antes del corte
                (dict(impuesto=15.90), 400),                   # no llega nada
                (dict(broker="Inexistente"), 404)):
            r = self.confirmar(**cambios)
            self.assertEqual(r.status_code, codigo, (cambios, r.text))
        self.assertEqual(self.dividendos(), [])
        self.assertAlmostEqual(self.caja("Balanz · USD"), 1240.50, places=2)


# ═════════════════════════════════════════════════════════════════════════════
class BorrarYDeshacer(_Base):

    def test_borrar_desde_movimientos_devuelve_las_dos_cuentas_y_deshacer_las_vuelve(self):
        self.assertEqual(self.confirmar().status_code, 200)
        mid = [m for m in self.movimientos()
               if m.get("asset") == "KO" and m["type"] == "DIVIDEND"][0]["id"]
        r = self.client.delete(f"/api/movements/{mid}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.dividendos(), [])
        self.assertAlmostEqual(self.caja("Balanz · USD"), 1240.50, places=2)
        self.assertAlmostEqual(self.caja("Balanz"), 100000, places=2)
        self.assertAlmostEqual(self.mes()["pnl_realized"], 0.0, places=6)

        token = r.json().get("undo_token")
        self.assertTrue(token)
        r = self.client.post(f"/api/operations/undo/{token}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(self.dividendos()), 1)
        self.assertAlmostEqual(self.caja("Balanz · USD"), 1240.50 + NETO, places=2)
        self.assertAlmostEqual(self.caja("Balanz"), 100000 - 62, places=2)

    def test_borrado_vuelve_a_dejar_confirmarlo(self):
        self.assertEqual(self.confirmar().status_code, 200)
        mid = [m for m in self.movimientos()
               if m.get("asset") == "KO" and m["type"] == "DIVIDEND"][0]["id"]
        self.assertEqual(self.client.delete(f"/api/movements/{mid}").status_code, 200)
        self.assertEqual(self.confirmar().status_code, 200)
        self.assertEqual(len(self.dividendos()), 1)


# ═════════════════════════════════════════════════════════════════════════════
class ImportarDespuesDeConfirmar(_Base):
    """El usuario confirmó desde la bandeja y después sube el archivo de Balanz,
    que trae el MISMO dividendo. El del broker manda; no se suma."""

    def test_el_importado_reemplaza_al_confirmado(self):
        self.assertEqual(self.confirmar().status_code, 200)
        self.importar(_csv(f"2026-10-07,DIVIDENDO,Balanz,KO,,,10.40,,,0,USD,"))
        divs = self.dividendos()
        self.assertEqual(len(divs), 1, divs)
        self.assertNotIn(dividendos.SRC, divs[0]["undo_meta_json"] or "",
                         "quedó el confirmado en vez del importado")
        self.assertAlmostEqual(divs[0]["pnl_usd"], 10.40, places=2)
        # El efectivo: el importado (10,40) y nada del confirmado. La comisión en
        # pesos del confirmado también se devolvió (este archivo no trae la suya).
        self.assertAlmostEqual(self.caja("Balanz · USD") + self.caja("Balanz") / TC
                               - (1240.50 + 100000 / TC), 10.40, places=2)
        self.assertAlmostEqual(self.mes()["pnl_realized"], 10.40, places=2)

    def test_el_importado_sin_activo_reemplaza_si_el_monto_se_parece(self):
        """Cocos no dice de qué empresa es el dividendo."""
        self.assertEqual(self.confirmar(comision_pesos=0).status_code, 200)
        self.importar(_csv(f"2026-10-07,DIVIDENDO,Balanz,,,,10.20,,,0,USD,"))
        divs = self.dividendos()
        self.assertEqual(len(divs), 1, divs)
        self.assertAlmostEqual(divs[0]["pnl_usd"], 10.20, places=2)

    def test_un_dividendo_de_otra_empresa_no_reemplaza_nada(self):
        self.assertEqual(self.confirmar().status_code, 200)
        self.importar(_csv(f"2026-10-07,DIVIDENDO,Balanz,PEP,,,4.81,,,0,USD,"))
        self.assertEqual(sorted(d["asset"] for d in self.dividendos()), ["KO", "PEP"])

    def test_borrar_importar_y_deshacer_no_lo_cobra_dos_veces(self):
        """Lo encontró la prueba al azar: confirmado → borrado → llega el import →
        "Deshacer" del borrado volvía a poner el confirmado al lado del importado."""
        self.assertEqual(self.confirmar().status_code, 200)
        mid = [m for m in self.movimientos()
               if m.get("asset") == "KO" and m["type"] == "DIVIDEND"][0]["id"]
        token = self.client.delete(f"/api/movements/{mid}").json()["undo_token"]
        self.importar(_csv(f"2026-10-07,DIVIDENDO,Balanz,KO,,,10.40,,,0,USD,"))
        r = self.client.post(f"/api/operations/undo/{token}")
        self.assertEqual(r.status_code, 409, r.text)
        divs = self.dividendos()
        self.assertEqual(len(divs), 1, divs)
        self.assertAlmostEqual(self.caja("Balanz · USD") + self.caja("Balanz") / TC
                               - (1240.50 + 100000 / TC), 10.40, places=2)

    def test_con_el_importado_adentro_la_bandeja_ya_no_deja_confirmarlo(self):
        self.importar(_csv(f"2026-10-07,DIVIDENDO,Balanz,KO,,,10.40,,,0,USD,"))
        r = self.confirmar()
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(len(self.dividendos()), 1)


# ═════════════════════════════════════════════════════════════════════════════
class NoLoCobre(_Base):

    def test_saltear_y_deshacer(self):
        body = {"broker": "Balanz", "asset": "ko", "ex_date": CORTE}
        self.assertEqual(self.client.post("/api/dividendos/saltear", json=body).status_code, 200)
        self.assertEqual(self.client.post("/api/dividendos/saltear", json=body).status_code, 200)
        self.assertEqual(self.client.get("/api/dividendos/salteados").json(),
                         [{"broker": "Balanz", "asset": "KO", "ex_date": CORTE}])
        r = self.client.delete("/api/dividendos/saltear",
                               params={"broker": "Balanz", "asset": "KO", "ex_date": CORTE})
        self.assertEqual(r.json()["deleted"], 1)
        self.assertEqual(self.client.get("/api/dividendos/salteados").json(), [])


# ═════════════════════════════════════════════════════════════════════════════
class Historial(_Base):

    def test_trae_lo_que_pago_cada_empresa_y_las_reglas_y_usa_la_cache(self):
        llamadas = []

        def falso(pedido):
            llamadas.append(pedido)
            ticker, con_emisor = pedido
            return {"pagos": [("2020-01-01", 0.40), (CORTE, 0.53)],
                    "pais": "United States" if con_emisor else None,
                    "tipo": "EQUITY" if con_emisor else None}

        with mock.patch.object(dividendos, "_consultar_yahoo", falso):
            r = self.client.get("/api/dividendos/historial", params={"tickers": "KO, ko,bad ticker"})
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body["reglas"]["impuesto_eeuu"], 0.30)
            ko = body["tickers"]["KO"]
            self.assertEqual(ko["pais"], "United States")
            # Lo de 2020 queda fuera de la ventana.
            self.assertEqual(ko["pagos"], [{"ex_date": CORTE, "por_accion": 0.53}])
            # La segunda vez sale de la caché: Yahoo no se vuelve a llamar.
            self.client.get("/api/dividendos/historial", params={"tickers": "KO"})
        self.assertEqual(llamadas, [("KO", True)])


if __name__ == "__main__":
    unittest.main()
