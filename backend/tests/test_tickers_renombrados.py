"""Block cambió de código (SQ → XYZ): lo que entra como SQ se guarda como XYZ.

Medido el 2026-10-19: Yahoo contesta "symbol may be delisted" para SQ y SQ.BA, y
BYMA (data912) sólo lista XYZ. Una posición guardada como SQ queda sin precio —la
pantalla la muestra al costo, la foto diaria la cuenta «sin precio»— y si la
misma persona tiene compras viejas como SQ y ventas nuevas como XYZ, son dos
libros FIFO: la venta no encuentra las compras, se le inventa un lote al precio
de venta (ganancia 0) y la compra queda abierta como un activo que ya no tiene.

La copia de producción del 16/08 no tenía ninguna fila con SQ, así que esto no
corrige datos: cierra las puertas. Entra por las MISMAS puertas HTTP que la app
(importar un archivo, cargar a mano, renombrar un grupo, la lista de
seguimiento, las alertas); lo único reemplazado es el login.
"""
import io
import os
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

import main  # noqa: E402
import snapshots_job  # noqa: E402
from ai.trade_tickers import resolve_asset  # noqa: E402
import tickers_renombrados  # noqa: E402
from tickers_renombrados import ticker_importado, ticker_vigente  # noqa: E402

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


def _csv(*rows: str) -> bytes:
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


class TestTickerVigente(unittest.TestCase):
    def test_traduce_el_viejo_y_respeta_byma(self):
        self.assertEqual(ticker_vigente("SQ"), "XYZ")
        self.assertEqual(ticker_vigente(" sq "), "XYZ")
        self.assertEqual(ticker_vigente("SQ.BA"), "XYZ.BA")

    def test_no_toca_nada_mas(self):
        # Ni otro activo, ni uno que EMPIEZA igual, ni las mayúsculas de lo que
        # no cambió: quien lo llama sigue igual para todo lo demás.
        for s in ("XYZ", "SQQQ", "AAPL.BA", "aapl", "FCI:COCOS-AHORRO-A", "", None):
            self.assertEqual(ticker_vigente(s), s)

    def test_el_chat_entiende_el_codigo_y_el_nombre_viejos(self):
        for dicho in ("SQ", "sq", "Block", "Square"):
            ticker, tipos = resolve_asset(dicho)
            self.assertEqual(ticker, "XYZ", dicho)
            self.assertIn("STOCK", tipos)


class TestGoldEsBSoloAlImportar(unittest.TestCase):
    """Barrick pasó de GOLD a B (mayo 2025). Bull Market compra "GOLD" en 2021 y
    vende "B" en 2023 en el MISMO archivo (cuenta de Agustín, 2026-10-22: GOLD 4
    quedaba abierto). Pero "GOLD" es también el indicador «Oro (spot)» de la
    pantalla, así que el renombre vale sólo para lo que manda un broker."""

    def test_lo_importado_pasa_a_b(self):
        self.assertEqual(ticker_importado("GOLD"), "B")
        self.assertEqual(ticker_importado("gold.ba"), "B.BA")
        self.assertEqual(ticker_importado("SQ"), "XYZ", "el renombre general sigue")

    def test_la_on_canjeada_entra_como_la_nueva(self):
        # Cresud Clase XXIII → XXXVIII (8/7/2022): ver RENOMBRADOS_AL_IMPORTAR.
        self.assertEqual(ticker_importado("CSDOO"), "CS38O")
        self.assertEqual(ticker_vigente("CSDOO"), "CSDOO")
        self.assertEqual(tickers_renombrados.codigos_anteriores("CS38O"), ["CSDOO"])

    def test_lo_que_la_persona_tipea_no_se_toca(self):
        self.assertEqual(ticker_vigente("GOLD"), "GOLD")
        self.assertEqual(main.WatchlistAddIn(symbol="GOLD").symbol, "GOLD")
        self.assertEqual(main.AlertCreateIn(kind="price_target", symbol="GOLD",
                                            threshold=90).symbol, "GOLD")


class _Base(unittest.TestCase):
    BROKER = "IBKR"

    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "watchlist", "price_alerts", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("renombrados@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, self.BROKER, "USD"))
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        self.conn.close()

    def _import(self, csv_bytes: bytes) -> dict:
        r = self.client.post(
            "/api/imports/preview",
            files=[("files", ("x.csv", io.BytesIO(csv_bytes), "text/csv"))],
            data={"format": "rendi_generic", "broker": self.BROKER})
        self.assertEqual(r.status_code, 200, r.text)
        prev = r.json()
        r = self.client.post("/api/imports/confirm", json={"session_id": prev["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)
        return prev

    def _abiertas(self) -> dict:
        out = {}
        for r in self.conn.execute(
                "SELECT asset, SUM(quantity) q FROM positions WHERE user_id=? AND is_cash=0 "
                "AND quantity > 0 GROUP BY asset", (self.uid,)):
            out[r["asset"]] = r["q"]
        return out


class TestImportar(_Base):
    def test_compra_vieja_sq_y_venta_nueva_xyz_son_el_mismo_libro(self):
        """El caso que rompe: el extracto de 2024 dice SQ, el de 2025 dice XYZ.

        Sin la traducción, la compra quedaba abierta como SQ (un activo que la
        persona ya vendió, y sin precio) y la venta de XYZ salía con ganancia 0.
        Con ella, la venta encuentra la compra: posición cerrada y ganancia real.
        """
        self._import(_csv(
            "2024-06-03,DEPOSITO,IBKR,,,,1000,,,0,USD,",
            "2024-06-10,COMPRA,IBKR,SQ,10,60,600,,,0,USD,",
            "2025-03-10,VENTA,IBKR,XYZ,10,80,800,,,0,USD,",
        ))
        self.assertEqual(self._abiertas(), {}, "quedó algo abierto: la venta no encontró la compra")
        venta = self.conn.execute(
            "SELECT asset, pnl_usd FROM operations WHERE user_id=? AND asset IN ('SQ','XYZ') "
            "AND pnl_usd IS NOT NULL", (self.uid,)).fetchall()
        self.assertEqual([(r["asset"], round(r["pnl_usd"], 2)) for r in venta], [("XYZ", 200.0)])

    def test_lo_importado_como_sq_se_guarda_xyz_en_todas_las_tablas(self):
        prev = self._import(_csv(
            "2024-06-03,DEPOSITO,IBKR,,,,1000,,,0,USD,",
            "2024-06-10,COMPRA,IBKR,SQ,10,60,600,,,0,USD,",
        ))
        # La vista previa ya lo muestra con el código que cotiza.
        self.assertNotIn('"SQ"', str(prev).replace("'", '"'))
        self.assertEqual(self._abiertas(), {"XYZ": 10})
        for tabla, col in (("positions", "asset"), ("operations", "asset"),
                           ("import_normalized_tx", "asset_symbol")):
            n = self.conn.execute(
                f"SELECT COUNT(*) FROM {tabla} WHERE UPPER({col}) IN ('SQ','SQ.BA')").fetchone()[0]
            self.assertEqual(n, 0, f"{tabla}.{col} guardó SQ")
        # Y la valuación le pide precio a XYZ, que es lo que cotiza.
        fila = dict(self.conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND asset='XYZ'", (self.uid,)).fetchone())
        self.assertEqual(snapshots_job.position_price_key(fila, set(), set()), "XYZ")

    def test_reimportar_el_mismo_archivo_no_duplica(self):
        """La huella anti-duplicados tiene que salir igual en la vista previa y en
        el confirm (que relee las filas de la base, sin el código crudo). Con el
        crudo en "SQ" la vista previa decía «ya estaba importada» y el confirm la
        cargaba otra vez: 20 en vez de 10."""
        archivo = _csv(
            "2024-06-03,DEPOSITO,IBKR,,,,1000,,,0,USD,",
            "2024-06-10,COMPRA,IBKR,SQ,10,60,600,,,0,USD,",
        )
        self._import(archivo)
        self._import(archivo)
        self.assertEqual(self._abiertas(), {"XYZ": 10})


class TestImportarGold(_Base):
    def test_compra_gold_y_venta_b_son_el_mismo_libro(self):
        self._import(_csv(
            "2021-07-01,DEPOSITO,IBKR,,,,1000,,,0,USD,",
            "2021-07-20,COMPRA,IBKR,GOLD,4,20,80,,,0,USD,",
            "2023-05-11,VENTA,IBKR,B,4,25,100,,,0,USD,",
        ))
        self.assertEqual(self._abiertas(), {}, "la venta de B no encontró la compra de GOLD")

    def test_reimportar_lo_guardado_como_gold_no_lo_duplica(self):
        """Las cuentas que importaron ANTES del renombre tienen la compra
        guardada como GOLD. Al volver a subir el archivo, esa fila hoy entra como
        B y da otra huella: sin probar el código viejo, la compra (y su débito de
        caja) entraba dos veces."""
        archivo = _csv(
            "2021-07-01,DEPOSITO,IBKR,,,,1000,,,0,USD,",
            "2021-07-20,COMPRA,IBKR,GOLD,4,20,80,,,0,USD,",
        )
        guardado = dict(tickers_renombrados.RENOMBRADOS_AL_IMPORTAR)
        tickers_renombrados.RENOMBRADOS_AL_IMPORTAR.clear()   # como antes del arreglo
        try:
            self._import(archivo)
        finally:
            tickers_renombrados.RENOMBRADOS_AL_IMPORTAR.update(guardado)
        self.assertEqual(self._abiertas(), {"GOLD": 4})
        self._import(archivo)
        self.assertEqual(self._abiertas(), {"GOLD": 4}, "la compra entró otra vez como B")


class TestCargaAMano(_Base):
    def test_cargar_sq_a_mano_guarda_xyz(self):
        r = self.client.post("/api/positions", json={
            "broker": self.BROKER, "asset": "sq", "quantity": 5, "buy_price": 70,
            "currency": "USD", "entry_date": "2026-10-01"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._abiertas(), {"XYZ": 5})

    def test_renombrar_el_grupo_a_sq_lo_deja_en_xyz(self):
        r = self.client.post("/api/positions", json={
            "broker": self.BROKER, "asset": "BLOK", "quantity": 5, "buy_price": 70,
            "currency": "USD", "entry_date": "2026-10-01"})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.patch("/api/positions/group", json={
            "broker": self.BROKER, "asset": "BLOK", "currency": "USD", "new_asset": "SQ"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._abiertas(), {"XYZ": 5})

    def test_lista_de_seguimiento_y_alertas(self):
        self.assertEqual(main.WatchlistAddIn(symbol="sq").symbol, "XYZ")
        self.assertEqual(main.WatchlistAddIn(symbol="SQ.BA").symbol, "XYZ.BA")
        self.assertEqual(main.AlertCreateIn(kind="price_target", symbol="SQ",
                                            threshold=90).symbol, "XYZ")


if __name__ == "__main__":
    unittest.main()
