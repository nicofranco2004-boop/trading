"""La lista al costado del gráfico (pestaña «Gráfico» de Análisis técnico, como
en TradingView; Nico, 10/11): banderas, nombres de bandera y «como los
acomodás», guardados en la cuenta.

Entra por HTTP, como la pantalla. Lo que importa:
  · cada activo de tu lista tiene UNA bandera (una de las siete) o ninguna, y
    lo que agregás mirando una bandera entra con esa bandera;
  · el nombre de cada bandera es tuyo (otra persona no lo ve), sin espacios de
    más y con tope; vacío la deja sin nombre;
  · «como los acomodás»: la lista entera en el orden nuevo; lo nuevo va al final;
  · GET /api/watchlist trae, además de lo de siempre, la variación en plata (de
    la MISMA lectura que el %), la rueda, si está en horario y a qué hora cierra
    en hora argentina, y las siete banderas con su nombre;
  · sobre una base VIEJA (la tabla `watchlist` de antes, sin las dos columnas),
    el arranque las agrega y lo que ya seguías queda sin bandera ni lugar.

Corre con: cd backend && python3 -m pytest tests/test_lista_del_grafico.py
"""
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from fastapi.testclient import TestClient

import main
from home.market import cierre_en_hora_argentina


def _usuario(conn, quien):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, email_verified) VALUES (?, 'x', 1, 1)",
        (f"{quien}-{uuid.uuid4().hex[:8]}@rendi.test",))
    return cur.lastrowid


# Lo que contestaría la variación del día (`_fetch_batch_quotes`), sin Yahoo.
COTIZACIONES = {
    "AAPL": {"symbol": "AAPL", "price": 268.47, "prev_close": 267.35, "change_pct": 0.42,
             "mercado": "us", "as_of": "2026-11-10", "is_today": True},
    "AAPL.BA": {"symbol": "AAPL.BA", "price": 17850.0, "prev_close": 17700.0, "change_pct": 0.85,
                "mercado": "byma", "as_of": "2026-11-10", "is_today": True},
}


class ListaDelGraficoTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        with main.db_abierta() as conn:
            self.uid = _usuario(conn, "lista")
            self.otro = _usuario(conn, "otra")
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.h_otro = {"Authorization": f"Bearer {main.create_token(self.otro)}"}
        self._p = mock.patch.object(main, "_fetch_batch_quotes",
                                    lambda syms, *a, **k: {s: dict(COTIZACIONES[s]) for s in syms if s in COTIZACIONES})
        self._p.start()

    def tearDown(self):
        self._p.stop()
        with main.db_abierta() as conn:
            for t in ("watchlist", "watchlist_banderas"):
                conn.execute(f"DELETE FROM {t} WHERE user_id IN (?, ?)", (self.uid, self.otro))
            conn.commit()

    def lista(self, h=None):
        r = self.client.get("/api/watchlist", headers=h or self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def por_simbolo(self, h=None):
        return {it["symbol"]: it for it in self.lista(h)["items"]}

    def agregar(self, simbolo, **extra):
        r = self.client.post("/api/watchlist", json={"symbol": simbolo, **extra}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    # ─── Banderas ───────────────────────────────────────────────────────────

    def test_las_siete_banderas_vienen_en_orden_y_sin_nombre(self):
        b = self.lista()["banderas"]
        self.assertEqual([x["id"] for x in b], list(main.BANDERAS_DE_LA_LISTA))
        self.assertEqual(len(b), 7)
        self.assertTrue(all(x["nombre"] is None for x in b))

    def test_lo_que_agregas_mirando_una_bandera_entra_con_ella(self):
        self.agregar("AAPL")
        self.agregar("AAPL.BA", bandera="naranja")
        it = self.por_simbolo()
        self.assertIsNone(it["AAPL"]["bandera"])
        self.assertEqual(it["AAPL.BA"]["bandera"], "naranja")

    def test_agregar_con_una_bandera_que_no_existe_no_entra(self):
        r = self.client.post("/api/watchlist", json={"symbol": "AAPL", "bandera": "dorada"}, headers=self.h)
        self.assertEqual(r.status_code, 422)
        self.assertNotIn("AAPL", self.por_simbolo())

    def test_poner_cambiar_y_sacar_la_bandera(self):
        self.agregar("AAPL")
        r = self.client.patch("/api/watchlist/AAPL", json={"bandera": "azul"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.por_simbolo()["AAPL"]["bandera"], "azul")
        # UNA por activo: poner otra reemplaza la anterior.
        self.client.patch("/api/watchlist/aapl", json={"bandera": "rojo"}, headers=self.h)
        self.assertEqual(self.por_simbolo()["AAPL"]["bandera"], "rojo")
        self.client.patch("/api/watchlist/AAPL", json={"bandera": None}, headers=self.h)
        self.assertIsNone(self.por_simbolo()["AAPL"]["bandera"])

    def test_bandera_invalida_o_de_algo_que_no_esta(self):
        self.agregar("AAPL")
        self.assertEqual(self.client.patch("/api/watchlist/AAPL", json={"bandera": "dorada"}, headers=self.h).status_code, 422)
        self.assertEqual(self.client.patch("/api/watchlist/KO", json={"bandera": "azul"}, headers=self.h).status_code, 404)
        # La lista de otra persona no se toca.
        r = self.client.patch("/api/watchlist/AAPL", json={"bandera": "azul"}, headers=self.h_otro)
        self.assertEqual(r.status_code, 404)
        self.assertIsNone(self.por_simbolo()["AAPL"]["bandera"])

    # ─── Nombres ────────────────────────────────────────────────────────────

    def test_el_nombre_de_una_bandera_es_tuyo(self):
        r = self.client.put("/api/watchlist/banderas/azul", json={"nombre": "  EE.UU.\n "}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        nombres = {x["id"]: x["nombre"] for x in self.lista()["banderas"]}
        self.assertEqual(nombres["azul"], "EE.UU.")
        self.assertIsNone(nombres["naranja"])
        # Otra persona no lo ve.
        self.assertIsNone({x["id"]: x["nombre"] for x in self.lista(self.h_otro)["banderas"]}["azul"])
        # Cambiarlo lo reemplaza; vacío lo deja sin nombre.
        self.client.put("/api/watchlist/banderas/azul", json={"nombre": "Para comprar"}, headers=self.h)
        self.assertEqual({x["id"]: x["nombre"] for x in self.lista()["banderas"]}["azul"], "Para comprar")
        self.client.put("/api/watchlist/banderas/azul", json={"nombre": "   "}, headers=self.h)
        self.assertIsNone({x["id"]: x["nombre"] for x in self.lista()["banderas"]}["azul"])

    def test_el_nombre_tiene_tope_y_la_bandera_tiene_que_existir(self):
        largo = "x" * 80
        self.client.put("/api/watchlist/banderas/verde", json={"nombre": largo}, headers=self.h)
        self.assertEqual({x["id"]: x["nombre"] for x in self.lista()["banderas"]}["verde"], "x" * main.NOMBRE_DE_BANDERA_MAX)
        self.assertEqual(self.client.put("/api/watchlist/banderas/dorada", json={"nombre": "a"}, headers=self.h).status_code, 400)

    # ─── «Como los acomodás» ────────────────────────────────────────────────

    def test_ordenar_y_lo_nuevo_va_al_final(self):
        for s in ("AAPL", "KO", "MSFT"):
            self.agregar(s)
        r = self.client.put("/api/watchlist/orden", json={"simbolos": ["msft", "AAPL", "KO", "NOESTA"]}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        it = self.por_simbolo()
        self.assertEqual([it[s]["orden"] for s in ("MSFT", "AAPL", "KO")], [0, 1, 2])
        self.assertNotIn("NOESTA", it)
        self.agregar("NVDA")
        self.assertEqual(self.por_simbolo()["NVDA"]["orden"], 3)

    def test_el_orden_de_items_sigue_siendo_el_de_siempre(self):
        # El inicio muestra la lista como viene: lo último agregado primero.
        with main.db_abierta() as conn:
            for i, s in enumerate(("AAPL", "KO", "MSFT")):
                conn.execute("INSERT INTO watchlist (user_id, symbol, added_at) VALUES (?, ?, ?)",
                             (self.uid, s, f"2026-11-0{i + 1} 10:00:00"))
            conn.commit()
        self.client.put("/api/watchlist/orden", json={"simbolos": ["AAPL", "KO", "MSFT"]}, headers=self.h)
        self.assertEqual([x["symbol"] for x in self.lista()["items"]], ["MSFT", "KO", "AAPL"])

    def test_el_orden_de_otra_persona_no_se_toca(self):
        self.agregar("AAPL")
        self.client.put("/api/watchlist/orden", json={"simbolos": ["AAPL"]}, headers=self.h_otro)
        self.assertEqual(self.por_simbolo()["AAPL"]["orden"], 0)

    def test_el_orden_tiene_el_tope_de_la_lista(self):
        r = self.client.put("/api/watchlist/orden", json={"simbolos": [f"T{i}" for i in range(main.WATCHLIST_TOPE + 1)]},
                            headers=self.h)
        self.assertEqual(r.status_code, 422)

    # ─── Lo que trae cada activo ────────────────────────────────────────────

    def test_variacion_en_plata_rueda_y_cierre(self):
        self.agregar("AAPL")
        self.agregar("AAPL.BA")
        self.agregar("KO")   # sin cotización
        it = self.por_simbolo()
        # Precio − cierre anterior: la misma lectura del %.
        self.assertAlmostEqual(it["AAPL"]["change"], 268.47 - 267.35, places=6)
        self.assertAlmostEqual(it["AAPL.BA"]["change"], 150.0, places=6)
        self.assertIsNone(it["KO"]["change"])
        self.assertEqual((it["AAPL"]["mercado"], it["AAPL.BA"]["mercado"]), ("us", "byma"))
        self.assertEqual(it["AAPL.BA"]["cierra"], "17:00")
        self.assertIn(it["AAPL"]["cierra"], ("17:00", "18:00"))
        self.assertIsInstance(it["AAPL"]["en_horario"], bool)
        self.assertTrue(it["AAPL"]["is_today"])
        self.assertFalse(it["KO"]["is_today"])


class CarteraDelGraficoTest(unittest.TestCase):
    """La opción «Cartera» de la lista (Nico, 10/11): GET /api/watchlist/cartera.
    La cartera se carga por HTTP, como la carga la persona; la cotización, por
    el mismo `_fetch_batch_quotes` que la lista (simulado en el borde)."""

    COTIZA = {
        "NVDA": {"price": 167.51, "prev_close": 178.67, "change_pct": -6.25, "mercado": "us", "as_of": "2026-11-10", "is_today": True},
        "TSLA.BA": {"price": 39960.0, "prev_close": 38500.0, "change_pct": 3.79, "mercado": "byma", "as_of": "2026-11-10", "is_today": True},
        "GGAL.BA": {"price": 4900.0, "prev_close": 5005.0, "change_pct": -2.1, "mercado": "byma", "as_of": "2026-11-10", "is_today": True},
        # El ADR de Nueva York: si apareciera, la cartera estaría cotizando lo que no es.
        "GGAL": {"price": 30.0, "prev_close": 31.0, "change_pct": -3.2, "mercado": "us", "as_of": "2026-11-10", "is_today": True},
        "TSLA": {"price": 375.89, "prev_close": 378.05, "change_pct": -0.57, "mercado": "us", "as_of": "2026-11-10", "is_today": True},
    }

    def setUp(self):
        self.client = TestClient(main.app)
        with main.db_abierta() as conn:
            self.uid = _usuario(conn, "cartera")
            self.otro = _usuario(conn, "otra-cartera")
            # Pro: el plan gratis deja un solo broker.
            conn.execute("UPDATE users SET tier='pro' WHERE id=?", (self.uid,))
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.h_otro = {"Authorization": f"Bearer {main.create_token(self.otro)}"}
        self.pedidos = []

        def cotizar(syms, *a, **k):
            self.pedidos.append(list(syms))
            return {s: {"symbol": s, **self.COTIZA[s]} for s in syms if s in self.COTIZA}
        self._p = [mock.patch.object(main, "_fetch_batch_quotes", cotizar), mock.patch("main._check_rate_limit")]
        for p in self._p:
            p.start()
        for nombre, moneda in (("Schwab", "USD"), ("IOL", "ARS")):
            r = self.client.post("/api/brokers", json={"name": nombre, "currency": moneda}, headers=self.h)
            self.assertEqual(r.status_code, 200, r.text)

    def tearDown(self):
        for p in self._p:
            p.stop()

    def posicion(self, broker, asset, asset_type, h=None, **extra):
        r = self.client.post("/api/positions", json={"broker": broker, "asset": asset, "quantity": 10,
                                                     "buy_price": 100, "asset_type": asset_type, **extra},
                             headers=h or self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def cartera(self, h=None):
        r = self.client.get("/api/watchlist/cartera", headers=h or self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_cada_activo_se_cotiza_con_la_regla_de_la_valuacion(self):
        self.posicion("Schwab", "NVDA", "STOCK")
        self.posicion("IOL", "TSLA", "CEDEAR")          # el CEDEAR cargado como «TSLA»
        self.posicion("IOL", "GGAL", "ACCION")          # la acción argentina, en BYMA
        it = {x["symbol"]: x for x in self.cartera()["items"]}
        self.assertEqual({s: (x["cotiza"], x["local"]) for s, x in it.items()},
                         {"NVDA": ("NVDA", False), "TSLA": ("TSLA.BA", False), "GGAL": ("GGAL.BA", True)})
        # El precio y la variación son los del símbolo con que se cotiza: el
        # CEDEAR en pesos, no la TSLA de Nueva York; GGAL de BYMA, no el ADR.
        self.assertEqual(it["TSLA"]["price"], 39960.0)
        self.assertAlmostEqual(it["TSLA"]["change"], 1460.0, places=6)
        self.assertEqual(it["GGAL"]["change_pct"], -2.1)
        self.assertEqual((it["TSLA"]["mercado"], it["NVDA"]["mercado"]), ("byma", "us"))
        self.assertEqual(it["GGAL"]["cierra"], "17:00")
        self.assertNotIn("GGAL", self.pedidos[-1])
        self.assertNotIn("TSLA", self.pedidos[-1])

    def test_uno_por_ticker_sin_efectivo_ni_fondos_y_solo_lo_tuyo(self):
        self.posicion("Schwab", "NVDA", "STOCK")
        self.posicion("Schwab", "NVDA", "STOCK")       # dos lotes, un renglón
        self.posicion("IOL", "FCI:Balanz Ahorro", "FCI")
        with main.db_abierta() as conn:
            conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested) VALUES (?, 'Schwab', 'USD', 1, 500)",
                         (self.uid,))
            conn.commit()
        self.assertEqual([x["symbol"] for x in self.cartera()["items"]], ["NVDA"])
        # La de otra persona no aparece (ni siquiera tiene brokers).
        self.assertEqual(self.cartera(self.h_otro)["items"], [])

    def test_sin_cartera_vacia_y_sin_pedir_cotizaciones(self):
        self.assertEqual(self.cartera()["items"], [])
        self.assertEqual(self.pedidos, [])


class CierreEnHoraArgentinaTest(unittest.TestCase):
    """Nueva York cierra a las 16 de allá: 18 de acá en noviembre (sin horario de
    verano allá) y 17 en julio (con)."""

    def test_nueva_york_cambia_de_hora_y_la_argentina_no(self):
        self.assertEqual(cierre_en_hora_argentina("us", datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)), "18:00")
        self.assertEqual(cierre_en_hora_argentina("us", datetime(2026, 7, 10, 15, 0, tzinfo=timezone.utc)), "17:00")
        self.assertEqual(cierre_en_hora_argentina("byma", datetime(2026, 7, 10, 15, 0, tzinfo=timezone.utc)), "17:00")
        self.assertIsNone(cierre_en_hora_argentina("cripto"))


# La tabla `watchlist` como está en producción hoy (antes de esta pieza).
_WATCHLIST_VIEJA = """
    CREATE TABLE watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        asset_type TEXT,
        added_at TEXT DEFAULT (datetime('now')),
        UNIQUE(user_id, symbol)
    );
    CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);
"""


@unittest.skipIf(getattr(main, "USANDO_PG", False),
                 "Sólo SQLite: prueba la migración de init_db(); Postgres aplica schema_pg.sql, "
                 "que trae las columnas (test_schema_pg_al_dia).")
class BaseViejaTest(unittest.TestCase):
    """Un test que deja que init_db cree la tabla desde cero no puede fallar
    nunca: la tabla nace completa. Se FABRICA la de producción y recién ahí se
    arranca (dos veces: el arranque tiene que poder repetirse)."""

    def test_el_arranque_agrega_las_columnas_y_lo_de_antes_queda_sin_bandera(self):
        client = TestClient(main.app)
        with main.db_abierta() as conn:
            uid = _usuario(conn, "vieja")
            conn.execute("DROP TABLE IF EXISTS watchlist")
            conn.execute("DROP TABLE IF EXISTS watchlist_banderas")
            conn.executescript(_WATCHLIST_VIEJA)
            conn.execute("INSERT INTO watchlist (user_id, symbol) VALUES (?, 'GGAL.BA')", (uid,))
            conn.commit()
            cols = {r[1] for r in conn.execute("PRAGMA table_info(watchlist)")}
            self.assertNotIn("bandera", cols, "el test dejó de reproducir la base vieja")
        main.init_db()
        main.init_db()
        with main.db_abierta() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(watchlist)")}
            self.assertTrue({"bandera", "orden"} <= cols)
        h = {"Authorization": f"Bearer {main.create_token(uid)}"}
        with mock.patch.object(main, "_fetch_batch_quotes", lambda *a, **k: {}):
            r = client.post("/api/watchlist", json={"symbol": "AAPL", "bandera": "azul"}, headers=h)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(client.put("/api/watchlist/banderas/azul", json={"nombre": "EE.UU."}, headers=h).status_code, 200)
            it = {x["symbol"]: x for x in client.get("/api/watchlist", headers=h).json()["items"]}
        self.assertEqual((it["GGAL.BA"]["bandera"], it["GGAL.BA"]["orden"]), (None, None))
        # Lo de antes no tiene lugar: lo nuevo va al final igual (0, el primero con lugar).
        self.assertEqual((it["AAPL"]["bandera"], it["AAPL"]["orden"]), ("azul", 0))


if __name__ == "__main__":
    unittest.main()
