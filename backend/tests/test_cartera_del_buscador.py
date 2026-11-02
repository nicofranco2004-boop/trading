"""Lo que el servidor le da al buscador del gráfico (Análisis técnico → Gráfico
→ «Tu cartera»): una cartera GRANDE, de varios brokers, armada por las mismas
puertas que la app.

Un solo archivo, `fixtures/cartera_del_buscador.json`: la respuesta de
GET /api/positions y GET /api/brokers tal cual (sin lo que cambia de corrida en
corrida: ids, dueño, la marca para deshacer). Lo escribe ESTE test
(REGENERAR_FIXTURE=1) y lo lee frontend/src/pages/GraficoTecnico.test.jsx, que
abre el buscador con eso y mira que estén todos tus activos.

Por qué existe (02/11): «Tu cartera» del buscador quedaba vacía para Nico y la
prueba de la pantalla usaba dos lotes escritos a mano con la forma que el código
esperaba. Con esto la pantalla se prueba con lo que contesta el servidor: lotes
cargados a mano, importados de un broker (con su caja y su venta total), cajas
automáticas, bonos, CEDEARs, cripto, el mismo ticker en dos mercados.

Lo único reemplazado es el login.
"""
import io
import json
import os
import pathlib
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import main

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "cartera_del_buscador.json"
HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"

# Cargados a mano (POST /api/positions), uno por activo (un segundo lote del
# mismo broker el servidor lo junta con el primero). Son ~40 pedidos: con
# Postgres remoto cada uno va por la red.
A_MANO = {
    ("IOL", "ARS"): [(a, "ACCION") for a in ("GGAL", "YPFD", "PAMP", "TXAR", "ALUA", "BMA", "CEPU", "TGSU2")]
                    + [(a, "CEDEAR") for a in ("AAPL", "MSFT", "KO", "NVDA", "GOOGL", "AMZN", "SPY", "BRKB")]
                    + [(a, "BONO") for a in ("AL30", "GD30", "TX26")],
    ("Schwab", "USD"): [(a, "STOCK") for a in ("NVDA", "GGAL", "AGRO", "BRK.B")] + [("VOO", "ETF"), ("QQQ", "ETF")],
    ("Binance", "USD"): [(a, "CRYPTO") for a in ("BTC", "ETH", "SOL")],
}
# Importados de un broker (el archivo genérico): un depósito, compras y una
# venta TOTAL (LOMA: ya no la tenés).
IMPORTADO = ("Cocos", "ARS", [
    "2025-03-01,DEPOSITO,Cocos,,,,50000000,,,0,ARS,",
    "2025-03-03,COMPRA,Cocos,MELI,10,20000,200000,,,0,ARS,",
    "2025-03-03,COMPRA,Cocos,VIST,20,15000,300000,,,0,ARS,",
    "2025-03-03,COMPRA,Cocos,LOMA,100,2000,200000,,,0,ARS,",
    "2025-03-03,COMPRA,Cocos,AE38,1000,700,700000,,,0,ARS,",
    "2025-06-02,VENTA,Cocos,LOMA,100,2500,250000,,,0,ARS,",
])
# Lo que tenés y tiene gráfico, uno por ticker: lo que el buscador tiene que
# mostrar en «Tu cartera» (los bonos se muestran: la ficha los abre).
ESPERADO = sorted({a for lotes in A_MANO.values() for a, _ in lotes} | {"MELI", "VIST", "AE38"})


def _csv(rows):
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


# Lo que cambia de una corrida a otra (o entre SQLite y Postgres) y la pantalla
# no lee.
VOLATILES = {"id", "user_id", "undo_meta_json", "created_at", "updated_at"}


def _sin_volatiles(fila):
    return {k: v for k, v in fila.items() if k not in VOLATILES}


class CarteraDelBuscadorTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "deleted_ops_journal", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        self.conn.close()

    def _armar(self):
        uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,'pro')",
            ("cartera_del_buscador@rendi.test", "x")).lastrowid
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: uid
        client = TestClient(main.app)
        with mock.patch("main._check_rate_limit"):
            for (broker, moneda) in [*A_MANO, IMPORTADO[:2]]:
                r = client.post("/api/brokers", json={"name": broker, "currency": moneda})
                self.assertEqual(r.status_code, 200, r.text)
            for (broker, _), lotes in A_MANO.items():
                for asset, tipo in lotes:
                    r = client.post("/api/positions", json={
                        "broker": broker, "asset": asset, "quantity": 10, "buy_price": 100,
                        "asset_type": tipo, "entry_date": "2025-02-03"})
                    self.assertEqual(r.status_code, 200, f"{asset}: {r.text}")
            nombre, _, filas = IMPORTADO
            r = client.post("/api/imports/preview",
                            files=[("files", ("x.csv", io.BytesIO(_csv(filas)), "text/csv"))],
                            data={"format": "rendi_generic", "broker": nombre})
            self.assertEqual(r.status_code, 200, r.text)
            r = client.post("/api/imports/confirm", json={"session_id": r.json()["session_id"]})
            self.assertEqual(r.status_code, 200, r.text)
        return client

    def _lo_que_contesta(self, client):
        pos = client.get("/api/positions")
        brokers = client.get("/api/brokers")
        self.assertEqual((pos.status_code, brokers.status_code), (200, 200))
        return {
            "positions": [_sin_volatiles(p) for p in sorted(
                pos.json(), key=lambda p: (p["broker"], p["asset"], p.get("entry_date") or "", p.get("quantity") or 0))],
            "brokers": [_sin_volatiles(b) for b in sorted(brokers.json(), key=lambda b: b["name"])],
        }

    def _guardado(self):
        return json.loads(FIXTURE.read_text(encoding="utf-8")) if FIXTURE.exists() else {}

    def test_lo_que_lee_el_buscador_es_el_fixture(self):
        real = self._lo_que_contesta(self._armar())
        guardado = self._guardado()
        if os.environ.get("REGENERAR_FIXTURE"):
            guardado = {"esperado": ESPERADO, **real}
            FIXTURE.write_text(json.dumps(guardado, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        self.assertEqual(guardado.get("esperado"), ESPERADO)
        self.assertEqual(
            real, {k: guardado.get(k) for k in ("positions", "brokers")},
            "Lo que el servidor le da al buscador cambió. Si es a propósito: "
            "REGENERAR_FIXTURE=1 pytest tests/test_cartera_del_buscador.py")

    def test_el_fixture_es_una_cartera_grande_y_variada(self):
        """Que la prueba de la pantalla no se quede con dos lotes de juguete."""
        g = self._guardado()
        pos = g["positions"]
        self.assertGreaterEqual(len(pos), 35)
        self.assertGreaterEqual(len({p["broker"] for p in pos}), 4)
        self.assertTrue(any(p.get("is_cash") for p in pos), "sin cajas")
        tenidos = {p["asset"] for p in pos if not p.get("is_cash") and (p.get("quantity") or 0) > 0}
        self.assertEqual(sorted(tenidos), ESPERADO)
        # La venta total del archivo no deja a LOMA con cantidad.
        self.assertNotIn("LOMA", tenidos)
