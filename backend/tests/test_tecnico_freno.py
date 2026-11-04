"""Una cuenta no puede trabar Rendi con «Tu lista» y la radiografía (auditoría E1, 29/10).

`POST /api/tecnico/lista`, `/cartera` y `/en-fechas` calculaban todo en cada
pedido: 200 activos ≈ 3 s de cálculo puro, y el servidor es UN proceso. 45
pedidos a la vez de una cuenta gratis lo dejaron sin contestar 5 minutos.

Lo que se prueba, por HTTP y con las velas que guarda la corrida de la noche
real (`main._run_velas_diarias_job`, con Yahoo reemplazado en su punto más bajo):
  · la lectura de un activo se calcula UNA vez mientras sus velas no cambien:
    el segundo pedido no recalcula nada y devuelve lo mismo;
  · si las velas cambian —una vela nueva, o Yahoo reescribe la historia por un
    split con la MISMA última fecha—, se recalcula y coincide con la ficha;
  · un freno por persona: 30 pedidos por minuto y 3 a la vez; el 31 da 429 y a
    otra persona no le pasa nada;
  · el tope de 200 es de lecturas, no de renglones del pedido: «Tu lista» suma
    lo que tenés, y el diario mandaba hasta 2000 activos distintos.

Corre con: cd backend && python3 -m pytest tests/test_tecnico_freno.py
"""
import os
import sys
import tempfile
import threading
import unittest
import uuid
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
import tecnico
from fechas import hoy_art_date
from tests.test_radiografia_tecnica import YahooFalso  # noqa: E402

ACTIVOS = ["AAPL", "MSFT", "NVDA", "KO", "TSLA"]


class FrenoTecnicoTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "watchlist", "positions", "brokers",
                      "fx_rates_daily"):
                conn.execute(f"DELETE FROM {t}")
            self.uids = []
            for quien in ("ana", "beto"):
                cur = conn.execute(
                    "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                    "VALUES (?, 'x', 1, 1, 'free')", (f"freno-{quien}-{tag}@rendi.test",))
                self.uids.append(cur.lastrowid)
            conn.commit()
        self.ana = {"Authorization": f"Bearer {main.create_token(self.uids[0])}"}
        self.beto = {"Authorization": f"Bearer {main.create_token(self.uids[1])}"}
        self.hoy = hoy_art_date()
        self.yahoo = YahooFalso(self.hoy)
        for k, a in enumerate(ACTIVOS):
            self.yahoo.precios[a] = (lambda k: lambda i, d: 100 + k * 10 + i * (0.05 + k * 0.01))(k)
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("main._fetch_data912_equities", lambda: {})]
        for p in self._p:
            p.start()
        getattr(main, "_freno_reiniciar", lambda: None)()
        getattr(tecnico, "olvidar_lo_leido", lambda: None)()
        for a in ACTIVOS:
            r = self.client.post("/api/watchlist", json={"symbol": a}, headers=self.ana)
            self.assertEqual(r.status_code, 200, r.text)
        main._run_velas_diarias_job()

    def tearDown(self):
        for p in self._p:
            p.stop()
        getattr(main, "_freno_reiniciar", lambda: None)()

    def _lista(self, h=None, activos=None, esperado=200):
        r = self.client.post("/api/tecnico/lista",
                             json={"activos": [{"asset": a} for a in (activos or ACTIVOS)]},
                             headers=h or self.ana)
        self.assertEqual(r.status_code, esperado, r.text)
        return r.json()

    def _contar_lecturas(self):
        return mock.patch("tecnico.lectura", wraps=tecnico.lectura)

    # ─── La lectura guardada ────────────────────────────────────────────────

    def test_la_segunda_vez_no_recalcula_y_da_lo_mismo(self):
        with self._contar_lecturas() as m:
            uno = self._lista()
            primera = m.call_count
            dos = self._lista()
            segunda = m.call_count - primera
        self.assertEqual(primera, len(ACTIVOS))
        self.assertEqual(segunda, 0, "el segundo pedido no tiene que recalcular nada")
        self.assertEqual(uno["lecturas"], dos["lecturas"])
        # La radiografía tiene su propia lectura guardada (otra forma de respuesta).
        with self._contar_lecturas() as m:
            for _ in range(2):
                r = self.client.post("/api/tecnico/cartera",
                                     json={"activos": [{"asset": a} for a in ACTIVOS]}, headers=self.ana)
                self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(m.call_count, len(ACTIVOS))

    def test_lo_guardado_sirve_a_otra_persona(self):
        self._lista()
        with self._contar_lecturas() as m:
            self._lista(self.beto)
        self.assertEqual(m.call_count, 0)

    def test_una_vela_nueva_recalcula(self):
        antes = {x["asset"]: x for x in self._lista()["lecturas"]}
        with main.db_abierta() as conn:
            conn.execute("INSERT INTO velas_diarias (symbol, date, open, high, low, close, volume) "
                         "VALUES ('KO', ?, 900, 910, 890, 900, 1000)", (self.hoy.isoformat(),))
            conn.commit()
        with self._contar_lecturas() as m:
            despues = {x["asset"]: x for x in self._lista()["lecturas"]}
        self.assertEqual(m.call_count, 1, "sólo KO cambió")
        self.assertNotEqual(antes["KO"]["lectura"], despues["KO"]["lectura"])
        self.assertEqual(despues["KO"]["lectura"]["fecha"], self.hoy.isoformat())
        self.assertEqual(antes["AAPL"], despues["AAPL"])

    def test_un_split_con_la_misma_ultima_fecha_recalcula(self):
        """Yahoo reescribe la historia entera (split) y la última fecha no cambia:
        guardar por «última vela» sola serviría la lectura de antes del split."""
        antes = {x["asset"]: x for x in self._lista()["lecturas"]}
        # Toda la historia vuelve dividida por 4, con la misma última fecha.
        self.yahoo.precios["NVDA"] = lambda i, d: (130 + i * 0.08) / 4
        with main.db_abierta() as conn:
            conn.execute("UPDATE velas_estado SET ultima_completa = '2000-01-01' WHERE symbol='NVDA'")
            conn.commit()
        main._run_velas_diarias_job()
        despues = {x["asset"]: x for x in self._lista()["lecturas"]}
        self.assertEqual(antes["NVDA"]["lectura"]["fecha"], despues["NVDA"]["lectura"]["fecha"])
        self.assertNotEqual(antes["NVDA"]["lectura"]["precio"], despues["NVDA"]["lectura"]["precio"])
        ficha = self.client.get("/api/tecnico/NVDA?moneda=usd", headers=self.ana).json()
        self.assertEqual(despues["NVDA"]["lectura"], ficha["lectura"])

    # ─── El freno por persona ───────────────────────────────────────────────

    def test_treinta_por_minuto_y_a_otra_persona_no_le_pasa_nada(self):
        reloj = [1000.0]
        with mock.patch("main._freno_reloj", lambda: reloj[0], create=True):
            for _ in range(getattr(main, "FRENO_TECNICO_POR_MINUTO", 30)):
                self._lista(activos=["AAPL"])
            r = self.client.post("/api/tecnico/lista", json={"activos": [{"asset": "AAPL"}]},
                                 headers=self.ana)
            self.assertEqual(r.status_code, 429, r.text)
            self.assertIn("Retry-After", r.headers)
            # Los tres pedidos caros comparten el freno.
            for ruta, cuerpo in (("/api/tecnico/cartera", {"activos": [{"asset": "AAPL"}]}),
                                 ("/api/tecnico/en-fechas",
                                  {"items": [{"id": "1", "asset": "AAPL", "fecha": self.hoy.isoformat()}]})):
                self.assertEqual(self.client.post(ruta, json=cuerpo, headers=self.ana).status_code, 429)
            self._lista(self.beto, activos=["AAPL"])          # Beto, normal
            reloj[0] += 61
            self._lista(activos=["AAPL"])                      # al minuto, Ana otra vez

    def test_tres_a_la_vez(self):
        """El cuarto pedido simultáneo de la misma persona no espera: 429 en el
        momento (esperar ocupaba otro de los 40 lugares del servidor)."""
        adentro, soltar = threading.Semaphore(0), threading.Event()
        original = tecnico.para_la_lista

        def lento(conn, activos):
            adentro.release()
            soltar.wait(10)
            return original(conn, activos)

        codigos = []
        with mock.patch("tecnico.para_la_lista", lento):
            hilos = [threading.Thread(target=lambda: codigos.append(self.client.post(
                "/api/tecnico/lista", json={"activos": [{"asset": "AAPL"}]}, headers=self.ana).status_code))
                for _ in range(getattr(main, "FRENO_TECNICO_A_LA_VEZ", 3))]
            for t in hilos:
                t.start()
            for _ in hilos:
                self.assertTrue(adentro.acquire(timeout=10))
            r = self.client.post("/api/tecnico/cartera", json={"activos": [{"asset": "AAPL"}]},
                                 headers=self.ana)
            self.assertEqual(r.status_code, 429, r.text)
            self.assertEqual(self.client.post("/api/tecnico/cartera", json={"activos": [{"asset": "AAPL"}]},
                                              headers=self.beto).status_code, 200)
            soltar.set()
            for t in hilos:
                t.join(10)
        self.assertEqual(codigos, [200] * getattr(main, "FRENO_TECNICO_A_LA_VEZ", 3))
        # Terminados, vuelve a entrar.
        self._lista(activos=["AAPL"])

    def test_tus_senales_y_la_ficha_tambien_frenan(self):
        """Re-test E1: «Tus señales» hace la misma lectura de muchos activos y la
        ficha lee 3 años de velas por activo; sin freno, 45 a la vez dejaron el
        «¿estás vivo?» en 44 s y 33 s."""
        reloj = [1000.0]
        with mock.patch("main._freno_reloj", lambda: reloj[0], create=True):
            for _ in range(main.FRENO_TECNICO_POR_MINUTO):
                self._lista(activos=["AAPL"])
            self.assertEqual(self.client.get("/api/tus-senales", headers=self.ana).status_code, 429)
            self.assertEqual(self.client.get("/api/tus-senales", headers=self.beto).status_code, 200)
            # Tus tesis: la misma lectura de muchos activos (re-test E1, ronda 2).
            self.assertEqual(self.client.get("/api/tesis", headers=self.ana).status_code, 429)
            self.assertEqual(self.client.get("/api/tesis", headers=self.beto).status_code, 200)
            por_minuto = main.FRENO_TECNICO["uno"][0]
            for i in range(por_minuto):
                r = self.client.get(f"/api/tecnico/{ACTIVOS[i % len(ACTIVOS)]}?moneda=usd", headers=self.ana)
                self.assertEqual(r.status_code, 200, f"ficha {i}: {r.text}")
            self.assertEqual(self.client.get("/api/tecnico/AAPL?moneda=usd", headers=self.ana).status_code, 429)
            self.assertEqual(self.client.get("/api/tecnico/AAPL/eventos?moneda=usd",
                                             headers=self.ana).status_code, 429)
            self.assertEqual(self.client.get("/api/tecnico/AAPL/peso", headers=self.ana).status_code, 429)
            # El backtesting comparte el cupo de la ficha (auditoría 04/11).
            self.assertEqual(self.client.get("/api/tecnico/AAPL/backtest?reglas=rsi&anios=1",
                                             headers=self.ana).status_code, 429)
            self.assertEqual(self.client.get("/api/tecnico/AAPL?moneda=usd", headers=self.beto).status_code, 200)
            reloj[0] += 61
            self.assertEqual(self.client.get("/api/tecnico/AAPL?moneda=usd", headers=self.ana).status_code, 200)

    def test_entre_todos_hay_tope_aunque_sean_muchas_cuentas(self):
        """Re-test E1: el freno por persona se esquivaba con más cuentas (14
        cuentas × 3 a la vez → «¿estás vivo?» 48,8 s). Entre todos corren hasta
        `PESADOS_A_LA_VEZ`; la que sigue contesta 503 en el momento, con
        Retry-After (la pantalla reintenta sola), y no ocupa un lugar."""
        with main.db_abierta() as conn:
            carla = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'free')", (f"freno-carla-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
            conn.commit()
        carla = {"Authorization": f"Bearer {main.create_token(carla)}"}
        adentro, soltar = threading.Semaphore(0), threading.Event()
        original = tecnico.para_la_lista

        def lento(conn, activos):
            adentro.release()
            soltar.wait(10)
            return original(conn, activos)

        codigos = []
        with mock.patch("tecnico.para_la_lista", lento), mock.patch("main.PESADOS_A_LA_VEZ", 2):
            hilos = [threading.Thread(target=lambda h=h: codigos.append(self.client.post(
                "/api/tecnico/lista", json={"activos": [{"asset": "AAPL"}]}, headers=h).status_code))
                for h in (self.ana, self.beto)]
            for t in hilos:
                t.start()
            for _ in hilos:
                self.assertTrue(adentro.acquire(timeout=10))
            r = self.client.get("/api/tecnico/AAPL?moneda=usd", headers=carla)
            self.assertEqual(r.status_code, 503, r.text)
            self.assertIn("Retry-After", r.headers)
            soltar.set()
            for t in hilos:
                t.join(10)
            self.assertEqual(sorted(codigos), [200, 200])
            self.assertEqual(self.client.get("/api/tecnico/AAPL?moneda=usd", headers=carla).status_code, 200)

    def test_con_el_servidor_cargado_una_por_persona(self):
        """Re-test E1, ronda 2: pasada la mitad del tope entre todos, cada
        persona tiene una sola lectura corriendo; el lugar que queda es para
        otro, no para la tercera de la misma cuenta."""
        adentro, soltar = threading.Semaphore(0), threading.Event()
        original = tecnico.para_la_lista

        def lento(conn, activos):
            adentro.release()
            soltar.wait(10)
            return original(conn, activos)

        codigos = []
        with mock.patch("tecnico.para_la_lista", lento), mock.patch("main.PESADOS_A_LA_VEZ", 4):
            hilos = [threading.Thread(target=lambda: codigos.append(self.client.post(
                "/api/tecnico/lista", json={"activos": [{"asset": "AAPL"}]}, headers=self.ana).status_code))
                for _ in range(2)]
            for t in hilos:
                t.start()
            for _ in hilos:
                self.assertTrue(adentro.acquire(timeout=10))
            # Ana ya tiene 2 y va la mitad: su tercera no entra aunque su tope sea 3…
            self.assertEqual(self.client.get("/api/tecnico/AAPL?moneda=usd", headers=self.ana).status_code, 503)
            # …y Beto, que no tiene ninguna, sí.
            self.assertEqual(self.client.get("/api/tecnico/AAPL?moneda=usd", headers=self.beto).status_code, 200)
            soltar.set()
            for t in hilos:
                t.join(10)
        self.assertEqual(codigos, [200, 200])

    # ─── El tope de 200, real ───────────────────────────────────────────────

    def test_tu_lista_no_pasa_de_200_lecturas_con_lo_que_tenes(self):
        r = self.client.post("/api/brokers", json={"name": "Schwab", "currency": "USD"}, headers=self.ana)
        self.assertEqual(r.status_code, 200, r.text)
        for a in ("AAPL", "MSFT", "KO"):
            r = self.client.post("/api/positions", json={"broker": "Schwab", "asset": a, "quantity": 1,
                                                         "buy_price": 100, "asset_type": "STOCK"},
                                 headers=self.ana)
            self.assertIn(r.status_code, (200, 201), r.text)
        pedido = [f"QV{i:04d}" for i in range(tecnico.MAX_ACTIVOS_CARTERA)]
        out = self._lista(activos=pedido)
        self.assertEqual(len(out["lecturas"]), tecnico.MAX_ACTIVOS_CARTERA)
        # Lo que tenés va primero: nunca queda afuera por lo que seguís.
        tuyas = {x["asset"] for x in out["lecturas"]}
        self.assertTrue({"AAPL", "MSFT", "KO"} <= tuyas)

    def test_el_diario_no_lee_mas_de_200_series(self):
        n = tecnico.MAX_ACTIVOS_CARTERA + 50
        items = [{"id": str(i), "asset": f"QV{i:04d}", "fecha": self.hoy.isoformat()} for i in range(n)]
        items.append({"id": "aapl", "asset": "AAPL", "fecha": self.hoy.isoformat()})
        with mock.patch("tecnico.serie", wraps=tecnico.serie) as m:
            r = self.client.post("/api/tecnico/en-fechas", json={"items": items}, headers=self.ana)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertLessEqual(m.call_count, tecnico.MAX_ACTIVOS_CARTERA)
        res = r.json()["resultados"]
        self.assertEqual(len(res), n + 1)          # todas contestan…
        self.assertEqual(res[str(n - 1)]["motivo"], "tope")   # …las de más, diciendo por qué
        self.assertEqual(res["0"]["motivo"], "sin_velas")


if __name__ == "__main__":
    unittest.main()
