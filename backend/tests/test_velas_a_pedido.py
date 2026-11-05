"""La descarga a pedido de velas (`main._velas_a_pedido`): quién paga el cupo y
qué queda tomado mientras se espera a Yahoo.

Los dos los encontró la auditoría de seguridad del backtesting (04/11/2026,
hallazgos 3 y 4) en la ficha, y venían de antes:
  · La que PIDE paga el cupo de descargas y el freno: la asesora mirando la
    cuenta de Ana gasta los suyos. Antes gastaba los de Ana, que se quedaba sin
    descargas esa hora. Quién pide lo decide el freno (`main._freno_paga`): así
    ninguna entrada lo tiene que repetir (la quinta, el ✦ de la ficha, se había
    olvidado; auditoría del 05/11).
  · Mientras la ficha espera a Yahoo (o a data912) no queda ninguna conexión a
    la base tomada. En Postgres hay 10 por copia de la app; medido antes del
    arreglo (audit/_scripts/medir_conexion_esperando_yahoo.py), 8 fichas
    esperando a Yahoo tenían 8 tomadas. La corrida de la noche, en cambio, se
    queda con la suya a propósito (`velas_diarias.actualizar`, `soltar_la_base`).

Entra por HTTP, como la pantalla: la ficha, el comparador, las velas por hora,
la lectura técnica del chat y el ✦ de la ficha (con el modelo de mentira en la
frontera, con y sin `stream`, que es como lo pide la app). Yahoo, data912 y los
splits se reemplazan en su punto más bajo.

⚠️ Lo de `pgshim` (el pozo de verdad) sólo lo vigila la corrida contra Postgres:
`DATABASE_URL=<un Postgres de prueba> python3 -m pytest tests/test_velas_a_pedido.py`.

Corre con: cd backend && python3 -m pytest tests/test_velas_a_pedido.py
"""
import ast
import os
import sys
import tempfile
import threading
import unittest
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import pandas as pd
from fastapi.testclient import TestClient

import main
import pgsesion
import velas_diarias
import velas_horarias
from fechas import hoy_art_date
from tests.test_lectura_tecnica_chat import BUENO, ClaudeDelChat
from tests.test_tecnico import YahooFalso, _ruedas
from velas_diarias import PERIODO_COMPLETO, PERIODO_INCREMENTAL


def _prestadas_en_postgres() -> int:
    """Cuántas conexiones del pozo de Postgres están prestadas ahora (0 en SQLite)."""
    if not main.USANDO_PG:
        return 0
    import pgshim
    pozo = pgshim._POZOS.get(main.DATABASE_URL)
    return 0 if pozo is None else pozo._maximo - pozo._cupo._value


class _Base(unittest.TestCase):
    """Ana (Free) y su asesora, con vínculo activo. Yahoo, de mentira."""

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            # `splits_yahoo`: lo que ya se le preguntó a Yahoo hoy no se vuelve a preguntar.
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "splits_yahoo", "watchlist", "positions",
                      "brokers", "fx_rates_daily", "advisor_clients", "resumenes_tecnicos", "ai_usage_daily"):
                conn.execute(f"DELETE FROM {t}")

            def usuario(nombre, tier):
                return conn.execute("INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                                    "VALUES (?, 'x', 1, 1, ?)", (f"{nombre}-{tag}@rendi.test", tier)).lastrowid
            self.ana = usuario("ana", "free")
            self.asesora = usuario("asesora", "advisor")
            conn.execute("INSERT INTO advisor_clients (advisor_uid, client_uid, link_type, permission, status) "
                         "VALUES (?, ?, 'linked', 'read_write', 'active')", (self.asesora, self.ana))
            conn.commit()
        self.h_ana = {"Authorization": f"Bearer {main.create_token(self.ana)}"}
        self.h_asesora_en_ana = {"Authorization": f"Bearer {main.create_token(self.asesora)}",
                                 "X-Rendi-Client-Id": str(self.ana)}
        self.hoy = hoy_art_date()
        self.yahoo = YahooFalso(self.hoy)
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("main._kick_bench_refresh", lambda: None),
                   mock.patch("pricing.yahoo._historia", self._yahoo),
                   mock.patch("cambios_ratio._splits_de_yahoo", self._splits),
                   mock.patch("cambios_ratio._historia_byma", self._byma),
                   mock.patch("main._fetch_data912_equities", self._data912)]
        for p in self._p:
            p.start()
        # Los cupos y el freno viven en memoria: cada prueba arranca vacía.
        velas_diarias._a_pedido_hechos.clear()
        main._freno_reiniciar()

    def tearDown(self):
        for p in self._p:
            p.stop()

    # Las puertas a la red, de mentira. Las pruebas de la conexión las miran.
    def _yahoo(self, ticker, period, interval, auto_adjust, timeout):
        return self.yahoo(ticker, period, interval, auto_adjust, timeout)

    def _splits(self, ticker):
        return []

    def _byma(self, papel):
        return {}

    def _data912(self):
        return {}

    def _ficha(self, activo, h, query=""):
        r = self.client.get(f"/api/tecnico/{activo}{query}", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _chat(self, h, *, stream=False, ticker=None, boton=None):
        """POST /api/ai/chat como la app. `ticker`: el modelo pide la lectura
        técnica (`get_technical_reading`). `boton`: los `params` del ✦ de la
        ficha (screen 'tecnico'), que el servidor arma antes de llamar al modelo."""
        claude = ClaudeDelChat([BUENO], herramienta=("get_technical_reading", {"ticker": ticker})
                               if ticker else None)
        cuerpo = {"messages": [{"role": "user", "content": f"¿Cómo viene {ticker or 'esto'}?"}],
                  "snapshot": {"summary": {}, "positions": [], "operations": [], "monthly": [], "brokers": []},
                  "stream": stream}
        if boton is not None:
            cuerpo["analisis"] = {"screen": "tecnico", "params": boton}
        with mock.patch.object(main, "_get_anthropic_client", return_value=claude):
            r = self.client.post("/api/ai/chat", headers=h, json=cuerpo)
        self.assertEqual(r.status_code, 200, r.text)
        return claude


class LaQuePidePagaTest(_Base):
    """Hallazgo 3, con un cupo de UNA descarga por persona por hora: la asesora
    abre un activo nuevo adentro de la cuenta de Ana y después se mira quién
    se quedó sin cupo."""

    def setUp(self):
        super().setUp()
        for t in ("AMD", "INTC", "ORCL"):
            self.yahoo.precios[t] = lambda i, d: 10.0
        self._cupo = mock.patch.object(velas_diarias, "A_PEDIDO_POR_PERSONA_HORA", 1)
        self._cupo.start()

    def tearDown(self):
        self._cupo.stop()
        super().tearDown()

    def _gasto_la_asesora(self):
        f = self._ficha("INTC", self.h_ana)
        self.assertTrue(f["disponible"], f"la descarga de la asesora salió del cupo de Ana ({f.get('motivo')})")
        f = self._ficha("ORCL", self.h_asesora_en_ana)
        self.assertEqual((f["disponible"], f.get("motivo")), (False, "tope"),
                         "la asesora ya gastó SU descarga de la hora, mire la cuenta que mire")

    def test_la_ficha(self):
        self.assertTrue(self._ficha("AMD", self.h_asesora_en_ana)["disponible"])
        self._gasto_la_asesora()

    def test_el_comparador(self):
        r = self.client.get("/api/comparar/precio?activos=AMD&plazo=1a", headers=self.h_asesora_en_ana)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("AMD", {f["clave"] for f in r.json()["faltan"]}, r.json()["faltan"])
        self._gasto_la_asesora()

    def test_la_lectura_tecnica_del_chat(self):
        claude = self._chat(self.h_asesora_en_ana, ticker="AMD")
        self.assertTrue(claude.lectura_enviada().get("available"), claude.lectura_enviada())
        self._gasto_la_asesora()

    def test_la_lectura_tecnica_del_chat_en_vivo(self):
        # La app pide el chat con `stream: true` (frontend/src/utils/api.js): otra rama de ai_chat.
        claude = self._chat(self.h_asesora_en_ana, ticker="AMD", stream=True)
        self.assertTrue(claude.lectura_enviada().get("available"), claude.lectura_enviada())
        self._gasto_la_asesora()

    def test_el_boton_de_la_ficha(self):
        # «✦ ¿Está en tendencia?»: el armador técnico baja el activo antes de llamar al modelo.
        self._chat(self.h_asesora_en_ana, boton={"asset": "AMD"})
        self._gasto_la_asesora()

    def test_el_boton_de_la_ficha_en_vivo(self):
        self._chat(self.h_asesora_en_ana, boton={"asset": "AMD"}, stream=True)
        self._gasto_la_asesora()

    def test_el_navegador_no_elige_quien_paga(self):
        # `paga` lo pone el servidor desde el token: si lo manda el navegador, no cuenta.
        self._chat(self.h_asesora_en_ana, boton={"asset": "AMD", "paga": self.ana})
        self._gasto_la_asesora()

    def test_si_se_puede_pedir_lo_decide_la_cuenta_que_se_mira(self):
        # ZZZZ no está en ninguna lista de la app: se baja porque ANA lo tiene, no la asesora.
        r = self.client.post("/api/brokers", json={"name": "Schwab", "currency": "USD"}, headers=self.h_ana)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/positions", json={"broker": "Schwab", "asset": "ZZZZ", "quantity": 10,
                                                     "buy_price": 5, "asset_type": "STOCK"}, headers=self.h_ana)
        self.assertIn(r.status_code, (200, 201), r.text)
        self.yahoo.precios["ZZZZ"] = lambda i, d: 5.0
        self.assertTrue(self._ficha("ZZZZ", self.h_asesora_en_ana)["disponible"])
        self._gasto_la_asesora()

    def test_sola_en_su_cuenta_paga_ella(self):
        # El cupo sigue frenando a cada persona en su propia cuenta.
        self.assertTrue(self._ficha("AMD", self.h_ana)["disponible"])
        self.assertEqual(self._ficha("INTC", self.h_ana).get("motivo"), "tope")

    def test_la_llamada_de_tres_argumentos_la_paga_quien_pide(self):
        # Así llama la ruta del backtesting (en su rama): `_velas_a_pedido(conn, …, uid)`
        # adentro de `_freno_tecnico(request, uid, …)`. Paga quien puso el token.
        pedido = SimpleNamespace(state=SimpleNamespace(rendi_auth_uid=self.asesora))
        with main._freno_tecnico(pedido, self.ana, "uno"), main.db_abierta() as conn:
            tickers, motivo = main._velas_a_pedido(conn, [("AMD", False)], self.ana)["AMD"]
        self.assertEqual((tickers, motivo), (["AMD"], None))
        self._gasto_la_asesora()

    def test_fuera_de_un_freno_paga_la_cuenta(self):
        with main.db_abierta() as conn:
            main._velas_a_pedido(conn, [("AMD", False)], self.ana)
        self.assertEqual(self._ficha("INTC", self.h_ana).get("motivo"), "tope")


class ElFrenoLoPagaQuienPreguntaTest(_Base):
    """Lo mismo con el freno de las lecturas pesadas, con UNA lectura por minuto
    por persona: lo que pide la asesora adentro de Ana no frena a Ana."""

    def setUp(self):
        super().setUp()
        self.yahoo.precios["AMD"] = lambda i, d: 10.0
        self._freno = mock.patch.dict(main.FRENO_TECNICO, {"uno": (1, 3)})
        self._freno.start()

    def tearDown(self):
        self._freno.stop()
        super().tearDown()

    def _freno_de_la_asesora(self):
        self.assertTrue(self._ficha("AMD", self.h_ana)["disponible"], "el freno de Ana está entero")
        r = self.client.get("/api/tecnico/AMD", headers=self.h_asesora_en_ana)
        self.assertEqual(r.status_code, 429, "la asesora ya usó SU lectura del minuto")

    def test_la_lectura_tecnica_del_chat(self):
        self._chat(self.h_asesora_en_ana, ticker="AMD", stream=True)
        self._freno_de_la_asesora()

    def test_el_boton_de_la_ficha(self):
        self._chat(self.h_asesora_en_ana, boton={"asset": "AMD"}, stream=True)
        self._freno_de_la_asesora()


class ElFrenoSinPedidoDiceQuienPagaTest(unittest.TestCase):
    """Sin el pedido web (`request=None`), el freno no puede leer quién pide: hay
    que decírselo, y a esa persona se le cobran después las descargas
    (`main._freno_paga`). En el servidor, toda llamada `_freno_tecnico(None, …)`
    lo nombra `paga`, que pone el servidor desde el token. Se olvidó una vez: el
    ✦ de la ficha le cobraba al cliente (auditoría del 05/11)."""

    def test_las_llamadas_sin_pedido_dicen_quien_paga(self):
        vistas, malas = 0, []
        for raiz, dirs, archivos in os.walk(BACKEND):
            dirs[:] = [d for d in dirs if d not in ("tests", "scripts", "__pycache__", "venv", ".venv")]
            for nombre in archivos:
                if not nombre.endswith(".py"):
                    continue
                ruta = os.path.join(raiz, nombre)
                with open(ruta, encoding="utf-8") as f:
                    arbol = ast.parse(f.read(), ruta)
                for nodo in ast.walk(arbol):
                    if not isinstance(nodo, ast.Call) or not nodo.args:
                        continue
                    funcion = getattr(nodo.func, "id", None) or getattr(nodo.func, "attr", None)
                    primero = nodo.args[0]
                    if funcion != "_freno_tecnico" or not (isinstance(primero, ast.Constant)
                                                           and primero.value is None):
                        continue
                    vistas += 1
                    segundo = nodo.args[1] if len(nodo.args) > 1 else None
                    if not (isinstance(segundo, ast.Name) and segundo.id == "paga"):
                        malas.append(f"{os.path.relpath(ruta, BACKEND)}:{nodo.lineno}")
        self.assertGreaterEqual(vistas, 2, "no encontró las del chat y el ✦: la guarda no estaría mirando nada")
        self.assertEqual(malas, [], "freno sin pedido que no dice quién paga")


class LaQuePidePagaLasVelasPorHoraTest(_Base):
    """Lo mismo en las velas de 1 hora (`velas_horarias`), que tienen su propio
    cupo de primeras descargas: una por persona por hora en esta prueba."""

    def setUp(self):
        super().setUp()
        from tests.test_velas_horarias import AHORA, YahooFalso as YahooDeHoras, _horas_ny
        from datetime import date
        import fuera_de_horario
        self.yahoo_horas = YahooDeHoras(self.hoy)
        dias = [date(2026, 10, 27), date(2026, 10, 28), date(2026, 10, 29)]
        for t in ("AAPL", "MSFT", "NVDA"):
            self.yahoo_horas.horas[t] = _horas_ny(dias, hasta_ultimo=13)
        fuera_de_horario._vaciar_cache()
        self._p2 = [mock.patch("pricing.yahoo._historia", self.yahoo_horas),
                    mock.patch("velas_horarias._ahora", lambda: AHORA),
                    mock.patch("fuera_de_horario._pedir_yahoo",
                               lambda simbolos: [{"symbol": s, "marketState": "REGULAR"} for s in simbolos]),
                    mock.patch.object(velas_horarias, "NUEVOS_POR_PERSONA_HORA", 1)]
        for p in self._p2:
            p.start()
        for memoria in (velas_horarias._CACHE, velas_horarias._ARMADAS, velas_horarias._FALLAS,
                        velas_horarias._NUEVOS):
            memoria.clear()

    def tearDown(self):
        for p in reversed(self._p2):
            p.stop()
        super().tearDown()

    def _horas(self, activo, h):
        # Como la pantalla: el gráfico diario primero, después 1H.
        self.assertTrue(self._ficha(activo, h)["disponible"])
        r = self.client.get(f"/api/tecnico/{activo}/horas?cada=1h", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_las_velas_por_hora(self):
        self.assertTrue(self._horas("AAPL", self.h_asesora_en_ana)["disponible"])
        h = self._horas("MSFT", self.h_ana)
        self.assertTrue(h["disponible"], f"la descarga de la asesora salió del cupo de Ana ({h.get('motivo')})")
        h = self._horas("NVDA", self.h_asesora_en_ana)
        self.assertEqual((h["disponible"], h.get("motivo")), (False, "tope"))


class _Contada:
    """Una conexión de verdad, contada como cuenta el pozo de Postgres
    (`pgshim._Pozo`): «tomada» desde que se abre hasta que se cierra o se suelta
    (`soltar`, el mismo nombre que en pgshim.Connection), y otra vez al volver a
    usarla. En SQLite no hay pozo y sin esto la prueba no tendría dónde mirar; en
    Postgres, además, se mira el pozo de verdad (`_prestadas_en_postgres`). Todo
    lo demás pasa de largo a la conexión de verdad."""

    def __init__(self, real, tomadas: set):
        self.__dict__.update(_real=real, _tomadas=tomadas)
        tomadas.add(self)

    def __getattr__(self, nombre):
        return getattr(self._real, nombre)

    def __setattr__(self, nombre, valor):
        setattr(self._real, nombre, valor)

    def __enter__(self):
        self._real.__enter__()
        return self

    def __exit__(self, *exc):
        return self._real.__exit__(*exc)

    def _usar(self, que, *a):
        self._tomadas.add(self)
        return getattr(self._real, que)(*a)

    def execute(self, *a):
        return self._usar("execute", *a)

    def executemany(self, *a):
        return self._usar("executemany", *a)

    def executescript(self, *a):
        return self._usar("executescript", *a)

    def cursor(self, *a):
        return self._usar("cursor", *a)

    def soltar(self):
        de_verdad = getattr(self._real, "soltar", None)
        suelta = de_verdad() if de_verdad else not self._real.in_transaction
        if suelta:
            self._tomadas.discard(self)
        return suelta

    def close(self):
        self._tomadas.discard(self)
        self._real.close()


class SinLaConexionTomadaTest(_Base):
    """Hallazgo 4: cada vez que la descarga a pedido espera algo de afuera —Yahoo
    (las velas, el último mes, la historia entera de nuevo, el canario, los
    splits) o data912 (qué es cada activo, la historia de BYMA)— se anota cuántas
    conexiones a la base estaban tomadas en ese momento. Tienen que ser 0."""

    def setUp(self):
        super().setUp()
        self.tomadas, self.esperas = set(), []
        self.splits, self.vacia_entera = {}, set()
        de_verdad = main.get_db
        self._p_db = mock.patch.object(main, "get_db", lambda: _Contada(de_verdad(), self.tomadas))
        self._p_db.start()
        self._antes = 0

    def tearDown(self):
        self._p_db.stop()
        super().tearDown()

    def _anotar(self, que, *detalle):
        self.esperas.append((que, *detalle, len(self.tomadas), _prestadas_en_postgres() - self._antes))

    def _yahoo(self, ticker, period, interval, auto_adjust, timeout):
        self._anotar("yahoo", ticker, period)
        if period == PERIODO_COMPLETO and ticker in self.vacia_entera:
            return pd.DataFrame()
        return self.yahoo(ticker, period, interval, auto_adjust, timeout)

    def _splits(self, ticker):
        self._anotar("splits", ticker)
        return list(self.splits.get(ticker, []))

    def _byma(self, papel):
        self._anotar("byma", papel)
        return {}

    def _data912(self):
        self._anotar("data912")
        return {}

    def _mirando(self, url):
        del self.esperas[:]
        self._antes = _prestadas_en_postgres()
        r = self.client.get(url, headers=self.h_ana)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self.esperas, "no esperó nada: la prueba no prueba nada")
        tomadas = [e for e in self.esperas if e[-2] or e[-1]]
        self.assertEqual(tomadas, [], "esperas con una conexión tomada (…, tomadas, prestadas en Postgres)")
        return r.json()

    def _ficha_mirando(self, activo, query=""):
        return self._mirando(f"/api/tecnico/{activo}{query}")

    def _hace(self, horas):
        return (velas_diarias._ahora_utc() - timedelta(hours=horas)).strftime("%Y-%m-%d %H:%M:%S")

    def test_un_activo_nuevo(self):
        self.yahoo.precios["NVDA"] = lambda i, d: 100.0
        self.assertTrue(self._ficha_mirando("NVDA")["disponible"])
        self.assertIn(("yahoo", "NVDA", PERIODO_COMPLETO), [e[:3] for e in self.esperas])
        self.assertIn("data912", [e[0] for e in self.esperas], "qué es cada activo")

    def test_la_historia_cambiada_se_vuelve_a_bajar_entera(self):
        self.yahoo.precios["NVDA"] = lambda i, d: 100.0
        self._ficha("NVDA", self.h_ana)
        dias = _ruedas(self.hoy, 760)
        with main.db_abierta() as conn:   # pasaron días, y hubo un split de 2 a 1
            conn.execute("DELETE FROM velas_diarias WHERE symbol='NVDA' AND date >= ?", (dias[-3].isoformat(),))
            conn.execute("UPDATE velas_estado SET ultima_corrida=? WHERE symbol='NVDA'", (self._hace(30),))
            conn.commit()
        self.yahoo.precios["NVDA"] = lambda i, d: 50.0
        self.assertTrue(self._ficha_mirando("NVDA")["disponible"])
        self.assertEqual([e[2] for e in self.esperas if e[:2] == ("yahoo", "NVDA")],
                         [PERIODO_INCREMENTAL, PERIODO_COMPLETO])

    def test_la_bajada_entera_vacia_pide_el_ultimo_mes(self):
        # AMD tiene velas, nunca se bajó entera (le toca) y Yahoo no la da entera.
        dias = _ruedas(self.hoy, 30)
        with main.db_abierta() as conn:
            conn.executemany("INSERT INTO velas_diarias (symbol, date, open, high, low, close, volume) "
                             "VALUES ('AMD', ?, 10, 10, 10, 10, 1000)", [(d.isoformat(),) for d in dias[:-5]])
            conn.execute("INSERT INTO velas_estado (symbol, ultima_corrida, ok, filas) VALUES ('AMD', ?, 1, 25)",
                         (self._hace(30),))
            conn.commit()
        self.yahoo.precios["AMD"] = lambda i, d: 10.0
        self.vacia_entera.add("AMD")
        self.assertTrue(self._ficha_mirando("AMD")["disponible"])
        self.assertEqual([e[2] for e in self.esperas if e[:2] == ("yahoo", "AMD")],
                         [PERIODO_COMPLETO, PERIODO_INCREMENTAL])

    def test_el_canario(self):
        # Yahoo no devuelve nada de SNAP: se le pregunta al S&P 500 si anda.
        with main.db_abierta() as conn:
            conn.execute("INSERT INTO velas_estado (symbol, ultima_corrida, ok, filas) VALUES (?, ?, 1, 1)",
                         (velas_diarias.SP500, self._hace(30)))
            conn.commit()
        self.assertEqual(self._ficha_mirando("SNAP").get("motivo"), "sin_datos")
        self.assertIn(("yahoo", velas_diarias.SP500), [e[:2] for e in self.esperas])

    def test_una_accion_argentina_nueva(self):
        # Al bajarla se arma su lista de cambios de cantidad: los splits que anota
        # Yahoo y, si hay uno que el precio no muestra, la historia de BYMA.
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000.0
        self.splits["GGAL.BA"] = [(_ruedas(self.hoy, 200)[0].isoformat(), 10.0)]
        self._ficha_mirando("GGAL.BA", "?moneda=ars&local=1")
        lugares = [e[0] for e in self.esperas]
        self.assertIn("splits", lugares)
        self.assertIn("byma", lugares)

    def test_dos_acciones_argentinas_nuevas_en_el_comparador(self):
        # Para las dos Yahoo anota un 10 a 1 que el precio no muestra: se pide la
        # historia de BYMA de cada una. Antes, la segunda la esperaba con la
        # escritura de la primera abierta, y entonces con la conexión tomada.
        primera = _ruedas(self.hoy, 200)[0].isoformat()
        for papel in ("GGAL", "YPFD"):
            self.yahoo.precios[f"{papel}.BA"] = lambda i, d: 5000.0
            self.splits[f"{papel}.BA"] = [(primera, 10.0)]
        self._mirando("/api/comparar/precio?activos=GGAL,YPFD&local=GGAL,YPFD&plazo=1a")
        self.assertEqual(sorted(e[1] for e in self.esperas if e[0] == "byma"), ["GGAL", "YPFD"])

    def test_la_noche_se_queda_con_su_conexion(self):
        # A propósito (velas_diarias.actualizar, `soltar_la_base`): un trabajo de
        # fondo que soltara en cada tanda se cortaría entero si al volver el pozo
        # siguiera lleno 30 s. Es una conexión de 10, y no hay nadie esperando.
        r = self.client.post("/api/brokers", json={"name": "Schwab", "currency": "USD"}, headers=self.h_ana)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/positions", json={"broker": "Schwab", "asset": "MSFT", "quantity": 10,
                                                     "buy_price": 100, "asset_type": "STOCK"}, headers=self.h_ana)
        self.assertIn(r.status_code, (200, 201), r.text)
        self.yahoo.precios["MSFT"] = lambda i, d: 400.0
        del self.esperas[:]
        main._run_velas_diarias_job()
        de_yahoo = [e for e in self.esperas if e[0] == "yahoo"]
        self.assertIn("MSFT", [e[1] for e in de_yahoo])
        self.assertTrue(all(e[-2] >= 1 for e in de_yahoo), de_yahoo)


@unittest.skipUnless(main.USANDO_PG, "el pozo de conexiones existe sólo en Postgres")
class SoltarEnPostgresTest(unittest.TestCase):
    """`pgshim.Connection.soltar` contra el pozo de verdad."""

    def test_devuelve_el_lugar_y_lo_vuelve_a_pedir_al_usarla(self):
        antes = _prestadas_en_postgres()
        conn = main.get_db()
        try:
            cur = conn.execute("SELECT 1 AS n UNION ALL SELECT 2 ORDER BY n")
            self.assertEqual(_prestadas_en_postgres(), antes + 1)
            self.assertTrue(pgsesion.soltar(conn))
            self.assertEqual(_prestadas_en_postgres(), antes)
            self.assertEqual([r["n"] for r in cur.fetchall()], [1, 2], "lo leído antes sigue en el cursor")
            conn.commit()
            self.assertEqual(_prestadas_en_postgres(), antes, "confirmar sin nada abierto no la pide")
            self.assertEqual(conn.execute("SELECT 3 AS n").fetchone()["n"], 3)
            self.assertEqual(_prestadas_en_postgres(), antes + 1, "al usarla, la vuelve a pedir")
        finally:
            conn.close()
        self.assertEqual(_prestadas_en_postgres(), antes)

    def test_con_una_escritura_abierta_no_la_suelta(self):
        conn = main.get_db()
        try:
            conn.execute("UPDATE users SET tier=tier WHERE id=-1")
            self.assertTrue(conn.in_transaction)
            self.assertFalse(pgsesion.soltar(conn), "soltarla perdería lo escrito")
            self.assertTrue(conn.in_transaction)
            conn.rollback()
        finally:
            conn.close()

    def test_con_ajustes_propios_no_la_suelta(self):
        conn = main.get_db()
        try:
            conn.execute("SET statement_timeout = 600000")
            conn.commit()      # el SET abre una transacción: sin esto se negaría por eso y no por el ajuste
            self.assertFalse(conn.in_transaction)
            self.assertFalse(pgsesion.soltar(conn), "la próxima sería otra conexión, sin el ajuste")
        finally:
            conn.close()

    def test_suelta_ni_confirmar_ni_deshacer_la_vuelven_a_pedir(self):
        antes = _prestadas_en_postgres()
        conn = main.get_db()
        try:
            self.assertTrue(pgsesion.soltar(conn))
            conn.rollback()
            with conn:
                pass
            self.assertFalse(conn.in_transaction)
            self.assertEqual(_prestadas_en_postgres(), antes, "no había nada abierto: no hace falta otra")
        finally:
            conn.close()
        self.assertEqual(_prestadas_en_postgres(), antes)

    def test_cerrada_no_se_suelta_ni_se_usa(self):
        antes = _prestadas_en_postgres()
        conn = main.get_db()
        conn.close()
        self.assertFalse(pgsesion.soltar(conn))
        with self.assertRaises(Exception):
            conn.execute("SELECT 1")
        self.assertEqual(_prestadas_en_postgres(), antes, "usar una cerrada no pide un lugar")

    def test_dos_hilos_con_la_misma_suelta_no_pierden_lugares(self):
        antes = _prestadas_en_postgres()
        conn = main.get_db()
        try:
            self.assertTrue(pgsesion.soltar(conn))
            # Sin conexiones libres en el pozo, volver a pedir abre una nueva: tarda,
            # y en ese rato otro hilo puede entrar (con una libre, es tan rápido que
            # la carrera casi nunca se da y la prueba pasaría sin el candado).
            pozo = conn._pozo
            with pozo._lock:
                libres, pozo._libres = pozo._libres, []
            for c, _ in libres:
                c.close()
            barrera = threading.Barrier(8)

            def usar():
                barrera.wait()
                conn.execute("SELECT 1").fetchone()
            hilos = [threading.Thread(target=usar) for _ in range(8)]
            for h in hilos:
                h.start()
            for h in hilos:
                h.join()
            self.assertEqual(_prestadas_en_postgres(), antes + 1, "una sola conexión para los cuatro")
        finally:
            conn.close()
        self.assertEqual(_prestadas_en_postgres(), antes, "ningún lugar perdido")

    def test_vuelve_a_pedir_al_pozo_vigente(self):
        # Las pruebas cierran los pozos al cambiar de esquema o de tope (`cerrar_pozos`).
        import pgshim
        conn = main.get_db()
        try:
            self.assertTrue(pgsesion.soltar(conn))
            viejo = conn._pozo
            pgshim.cerrar_pozos()
            conn.execute("SELECT 1").fetchone()
            self.assertIsNot(conn._pozo, viejo)
            self.assertIs(conn._pozo, pgshim._POZOS.get(main.DATABASE_URL))
        finally:
            conn.close()
        self.assertEqual(_prestadas_en_postgres(), 0)


class SoltarEnSQLiteTest(unittest.TestCase):

    @unittest.skipIf(main.USANDO_PG, "esto es lo que pasa en SQLite")
    def test_en_sqlite_no_hace_nada(self):
        with main.db_abierta() as conn:
            self.assertFalse(pgsesion.soltar(conn))
            self.assertEqual(conn.execute("SELECT 1").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
