"""La descarga a pedido de velas (`main._velas_a_pedido`): quién paga el cupo y
qué queda tomado mientras se espera a Yahoo.

Los dos los encontró la auditoría de seguridad del backtesting (04/11/2026,
hallazgos 3 y 4) en la ficha, y venían de antes:
  · La que PIDE paga el cupo de descargas, como en el freno y en el resumen: la
    asesora mirando la cuenta de Ana gasta el suyo. Antes gastaba el de Ana, que
    se quedaba sin descargas esa hora.
  · Mientras se espera a Yahoo (o a data912) no queda ninguna conexión a la base
    tomada. En Postgres hay 10 por copia de la app; medido antes del arreglo
    (audit/_scripts/medir_conexion_esperando_yahoo.py), 8 fichas esperando a
    Yahoo tenían 8 tomadas, y con otras 2 ocupadas un pedido liviano esperó 7,6 s.

Entra por HTTP, como la pantalla: la ficha, el comparador, las velas por hora y
la lectura técnica del chat (con el modelo de mentira en la frontera). Yahoo,
data912 y los splits se reemplazan en su punto más bajo.

Corre con: cd backend && python3 -m pytest tests/test_velas_a_pedido.py
"""
import os
import sys
import tempfile
import unittest
import uuid
from datetime import timedelta
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
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions",
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
        claude = ClaudeDelChat([BUENO], herramienta=("get_technical_reading", {"ticker": "AMD"}))
        cuerpo = {"messages": [{"role": "user", "content": "¿Cómo viene AMD?"}],
                  "snapshot": {"summary": {}, "positions": [], "operations": [], "monthly": [], "brokers": []}}
        with mock.patch.object(main, "_get_anthropic_client", return_value=claude):
            r = self.client.post("/api/ai/chat", headers=self.h_asesora_en_ana, json=cuerpo)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(claude.lectura_enviada().get("available"), claude.lectura_enviada())
        self._gasto_la_asesora()

    def test_sola_en_su_cuenta_paga_ella(self):
        # El cupo sigue frenando a cada persona en su propia cuenta.
        self.assertTrue(self._ficha("AMD", self.h_ana)["disponible"])
        self.assertEqual(self._ficha("INTC", self.h_ana).get("motivo"), "tope")

    def test_la_llamada_sin_quien_paga_sigue_cobrandole_a_la_cuenta(self):
        # Una ruta que todavía llama con tres argumentos (la del backtesting, en
        # su rama) no se rompe: paga la cuenta que se mira, como antes.
        with main.db_abierta() as conn:
            tickers, motivo = main._velas_a_pedido(conn, [("AMD", False)], self.ana)["AMD"]
        self.assertEqual((tickers, motivo), (["AMD"], None))
        self.assertEqual(self._ficha("INTC", self.h_ana).get("motivo"), "tope")


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
    lo demás pasa de largo a la conexión de verdad.

    Queda anotada en su hilo como una de pgshim (`pgsesion.anotar`): las puertas a
    la red la sueltan antes de esperar (`pgsesion.antes_de_esperar_afuera`)."""

    def __init__(self, real, tomadas: set):
        self.__dict__.update(_real=real, _tomadas=tomadas)
        tomadas.add(self)
        pgsesion.anotar(self)

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
        if de_verdad is None:            # SQLite: no hay pozo, se lo simula
            suelta = not self._real.in_transaction
        else:                            # Postgres: lo dice la de verdad (la puerta
            de_verdad()                  # pudo haberla soltado recién, antes que a ésta)
            suelta = self._real._suelta()
        if suelta:
            self._tomadas.discard(self)
        return suelta

    def close(self):
        self._tomadas.discard(self)
        pgsesion.olvidar(self)
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

    def _ficha_mirando(self, activo, query=""):
        del self.esperas[:]
        self._antes = _prestadas_en_postgres()
        f = self._ficha(activo, self.h_ana, query)
        self.assertTrue(self.esperas, "la ficha no esperó nada: la prueba no prueba nada")
        tomadas = [e for e in self.esperas if e[-2] or e[-1]]
        self.assertEqual(tomadas, [], "esperas con una conexión tomada (…, tomadas, prestadas en Postgres)")
        return f

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
            self.assertFalse(pgsesion.soltar(conn), "la próxima sería otra conexión, sin el ajuste")
        finally:
            conn.close()


class SoltarEnSQLiteTest(unittest.TestCase):

    @unittest.skipIf(main.USANDO_PG, "esto es lo que pasa en SQLite")
    def test_en_sqlite_no_hace_nada(self):
        with main.db_abierta() as conn:
            self.assertFalse(pgsesion.soltar(conn))
            self.assertEqual(conn.execute("SELECT 1").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
