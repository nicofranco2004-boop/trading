"""«Precio viejo»: UNA regla en todas las pantallas (`tecnico.es_vieja`).

LA DECISIÓN (Nico, 06/11/2026). Sin precios de la última semana —más de 7 días
contados desde hoy, el día argentino— un precio ya no describe hoy, en TODAS las
pantallas, y lo decide el servidor. Hasta ese día había siete lugares con su
propia cuenta: 7 días (Comparar, el Backtesting, el botón del resumen ✦, el
diario de operaciones), 7 desde las 9 de la mañana con el reloj de la compu (el
aviso de la ficha), 10 (la Cartera, Tu lista, el % de tu plata en tendencia
alcista, el mail de los sábados y el termómetro) y 5 (la fecha en ámbar del
termómetro). El mismo papel salía «viejo» en una pantalla y «al día» en otra
(auditoría de «1 año» 06/11, H2 y H7).

MEDIDO ANTES DE ELEGIR (copia de producción del 04/11, 1.186 series, 5 años): con
la noche andando, ninguna acción de Nueva York, cripto, el S&P ni acción
argentina pasó 7 días sin precio. El margen decide sólo cuando un papel deja de
llegar o la noche se cae más de una semana
(~/Documents/rendi-archivo/precio-viejo-una-regla-2026-11-06/).

POR EL CAMINO DE PRODUCCIÓN, en cada borde. MU deja de llegar después de un
miércoles: la corrida de la noche lo guarda (Yahoo reemplazado en su punto más
bajo) y cada pantalla se pide por HTTP 7 días después (adentro: «al día») y 8
(afuera: «viejo»), con «hoy» fijado donde lo lee toda la app (`fechas.ahora_art`):
  · la ficha (el aviso y el botón del resumen ✦): GET /api/tecnico/{activo}
  · la Cartera y el % de tu plata en tendencia alcista: POST /api/tecnico/cartera
  · Tu lista: POST /api/tecnico/lista
  · «Tus señales» y el mail de los sábados (la misma cuenta, `armar_semana`):
    GET /api/tus-senales
  · el diario de operaciones (la tendencia del día de una operación):
    POST /api/tecnico/en-fechas
Comparar y el Backtesting tienen sus bordes en `test_ultimos_n_anios.py`, y el
termómetro en `test_termometro.py` (necesita su universo de prueba).

Corre con: cd backend && python3 -m pytest tests/test_precio_viejo.py
"""
import os
import re
import sys
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
RAIZ = os.path.dirname(BACKEND)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from fastapi.testclient import TestClient

import main
import tecnico
import velas_diarias
from tests.test_ultimos_n_anios import MIERCOLES, Yahoo, _el_ultimo, _habiles, _precio


class EnTodasLasPantallas(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions",
                      "brokers", "fx_rates_daily", "resumenes_tecnicos"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"viejo-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        # El último precio de MU: un miércoles de hace unas semanas (no vence con la fecha).
        self.ultimo = _el_ultimo(MIERCOLES)
        self.yahoo = Yahoo(self.ultimo + timedelta(days=1))
        desde = self.ultimo - timedelta(days=5 * 365 + 10)
        self.yahoo.series["MU"] = {d: _precio(d) for d in _habiles(desde, self.ultimo)}
        for t, f in (("^GSPC", lambda d: 4000 + d.toordinal() % 997), ("^IXIC", lambda d: 12000 + d.toordinal() % 613)):
            self.yahoo.series[t] = {d: float(f(d)) for d in _habiles(desde, self.ultimo)}
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   # Con la IA configurada, la ficha ofrece el botón del resumen ✦.
                   mock.patch("ai.llm._get_anthropic_client", lambda: object())]
        for p in self._p:
            p.start()
        velas_diarias._a_pedido_hechos.clear()
        tecnico.olvidar_lo_leido()
        r = self.client.post("/api/brokers", json={"name": "Schwab", "currency": "USD"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/positions", json={"broker": "Schwab", "asset": "MU", "quantity": 10,
                                                     "buy_price": 100, "asset_type": "STOCK"}, headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)
        # La noche después del último precio guarda las velas. Después no llega nada más.
        with self._el_dia(1):
            main._run_velas_diarias_job()

    def tearDown(self):
        for p in self._p:
            p.stop()
        with main.db_abierta() as conn:   # tablas globales (sin user_id)
            for t in ("fx_rates_daily", "velas_diarias", "velas_estado", "resumenes_tecnicos"):
                conn.execute(f"DELETE FROM {t}")
            conn.commit()

    @contextmanager
    def _el_dia(self, dias, hora=15, minuto=0):
        """Todo lo de adentro pasa `dias` días después del último precio, a esa hora de acá."""
        d = self.ultimo + timedelta(days=dias)
        with mock.patch("fechas.ahora_art", return_value=datetime(d.year, d.month, d.day, hora, minuto)):
            yield

    def _pedir(self, metodo, url, **kw):
        main._freno_reiniciar()
        r = getattr(self.client, metodo)(url, headers=self.h, **kw)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ─── La ficha: el aviso de arriba del gráfico y el botón del resumen ✦ ────

    def test_la_ficha_avisa_desde_el_octavo_dia(self):
        for dias, vieja in ((7, False), (8, True)):
            with self.subTest(dias=dias), self._el_dia(dias):
                f = self._pedir("get", "/api/tecnico/MU?moneda=usd")
                self.assertTrue(f["disponible"], f)
                self.assertEqual(f["lectura"]["fecha"], self.ultimo.isoformat())
                self.assertIs(f["vieja"], vieja)
                # El resumen ✦ no se ofrece con precios viejos: la misma regla.
                if vieja:
                    self.assertIsNone(f["resumen"])
                else:
                    self.assertEqual(f["resumen"]["estado"], "no_hay", "se ofrece el botón")

    def test_la_ficha_cuenta_con_el_dia_argentino_no_con_la_hora(self):
        # Antes la pantalla contaba desde las 9 de la mañana con el reloj de la compu:
        # el octavo día, hasta las 9, el Backtesting ya decía «viejo» y el gráfico no.
        # Y de 21:00 a medianoche de acá, en UTC ya es el día siguiente.
        for dias, hora, minuto, vieja in ((7, 21, 30, False), (7, 23, 59, False), (8, 0, 1, True)):
            with self.subTest(dias=dias, hora=hora), self._el_dia(dias, hora, minuto):
                self.assertIs(self._pedir("get", "/api/tecnico/MU?moneda=usd")["vieja"], vieja)

    # ─── La Cartera y el % de tu plata en tendencia alcista ─────────────────

    def test_la_cartera_y_el_porcentaje_alcista_desde_el_octavo_dia(self):
        for dias, vieja in ((7, False), (8, True)):
            with self.subTest(dias=dias), self._el_dia(dias):
                r = self._pedir("post", "/api/tecnico/cartera", json={"activos": [{"asset": "MU", "local": False}]})
                (mu,) = r["lecturas"]
                self.assertTrue(mu["disponible"], mu)
                self.assertIs(mu["vieja"], vieja, "la fila de la Cartera")
                rep = r["reparto"]
                if vieja:
                    self.assertIsNone(rep["pct"], "MU es lo único que tiene: nada se lee")
                    self.assertEqual(rep["motivos"], [{"porque": "vieja", "nombres": ["MU"]}])
                else:
                    self.assertIsNotNone(rep["pct"], rep)
                    self.assertNotIn("MU", rep["grupos"]["sin"]["nombres"])

    # ─── Tu lista ────────────────────────────────────────────────────────────

    def test_tu_lista_desde_el_octavo_dia(self):
        for dias, vieja in ((7, False), (8, True)):
            with self.subTest(dias=dias), self._el_dia(dias):
                r = self._pedir("post", "/api/tecnico/lista", json={"activos": []})
                mu = next(x for x in r["lecturas"] if x["asset"] == "MU")
                self.assertTrue(mu["disponible"], mu)
                self.assertIs(mu["vieja"], vieja)

    # ─── «Tus señales» y el mail de los sábados ─────────────────────────────

    def test_tus_senales_y_el_mail_desde_el_octavo_dia(self):
        # `armar_semana` es LA cuenta de la pestaña y del mail del sábado. Con algo
        # que sí se lee (AAPL, que sigue llegando cada noche), el % sale y MU va
        # «sin lectura» por vieja; sin nada que leer, la pestaña no muestra el %.
        r = self.client.post("/api/positions", json={"broker": "Schwab", "asset": "AAPL", "quantity": 10,
                                                     "buy_price": 100, "asset_type": "STOCK"}, headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)
        desde = self.ultimo - timedelta(days=5 * 365 + 10)
        self.yahoo.series["AAPL"] = {d: _precio(d) * 1.5 for d in _habiles(desde, self.ultimo + timedelta(days=8))}
        for dias, vieja in ((7, False), (8, True)):
            with self.subTest(dias=dias), self._el_dia(dias):
                self.yahoo.hoy = self.ultimo + timedelta(days=dias)
                main._run_velas_diarias_job()     # la noche de ese día: AAPL llega, MU no
                r = self._pedir("get", "/api/tus-senales")
                self.assertEqual(r["tenes"]["activos"], 1 if vieja else 2, r["tenes"])
                self.assertIsNotNone(r["alcista"], r)
                self.assertEqual({"porque": "vieja", "nombres": ["MU"]} in r["alcista"]["motivos"], vieja,
                                 r["alcista"])

    # ─── El diario de operaciones: la tendencia del día de una operación ─────

    def test_el_diario_usa_la_misma_regla_contra_el_dia_de_la_operacion(self):
        # Una operación 7 días después del último precio se lee con él; 8 días
        # después, ese precio ya no describe el día: «sin dato».
        fechas = {str(n): (self.ultimo + timedelta(days=n)).isoformat() for n in (7, 8)}
        with self._el_dia(9):
            r = self._pedir("post", "/api/tecnico/en-fechas", json={"items": [
                {"id": k, "asset": "MU", "fecha": f} for k, f in fechas.items()]})["resultados"]
        self.assertIsNotNone(r["7"]["tendencia"], r["7"])
        self.assertEqual(r["7"]["fecha"], self.ultimo.isoformat())
        self.assertEqual(r["8"], {"tendencia": None, "motivo": "sin_precio"})


class UnaSolaRegla(unittest.TestCase):
    """Nadie más cuenta días para decir «viejo»: ni el servidor (otra constante
    con su margen) ni la pantalla (con el reloj de la compu). Las siete copias de
    hasta el 06/11 eran siete respuestas para el mismo papel."""

    COPIAS = ("DIAS_LECTURA_VIEJA", "DIAS_VELA_VIEJA", "DIAS_SIN_VELA", "DIAS_VIEJO", "diasViejo")

    def _fuentes(self, carpeta, extensiones):
        for base, dirs, archivos in os.walk(carpeta):
            dirs[:] = [d for d in dirs if d not in ("tests", "node_modules", "__pycache__", "dist", "scripts")]
            for a in archivos:
                if a.endswith(extensiones) and ".test." not in a:
                    ruta = os.path.join(base, a)
                    with open(ruta, encoding="utf-8") as f:
                        yield os.path.relpath(ruta, RAIZ), f.read()

    def test_ninguna_otra_constante_de_viejo(self):
        # Una constante con «VIEJ» en el nombre y un número es un margen propio.
        margen = re.compile(r"\b[A-Z_]*VIEJ[A-Z_]*\s*=\s*\d")
        for ruta, fuente in self._fuentes(BACKEND, (".py",)):
            for m in margen.finditer(fuente):
                self.assertEqual((ruta, m.group().split("=")[0].strip()), ("backend/tecnico.py", "DIAS_VIEJA"),
                                 f"{ruta}: «viejo» se decide con tecnico.es_vieja")
        for ruta, fuente in self._fuentes(os.path.join(RAIZ, "frontend", "src"), (".js", ".jsx")):
            self.assertIsNone(margen.search(fuente), f"{ruta}: «viejo» lo dice el servidor (`vieja`)")

    def test_las_copias_de_antes_no_vuelven(self):
        for carpeta, ext in ((BACKEND, (".py",)), (os.path.join(RAIZ, "frontend", "src"), (".js", ".jsx"))):
            for ruta, fuente in self._fuentes(carpeta, ext):
                for nombre in self.COPIAS:
                    # En un comentario que cuenta la historia («hasta el 06/11 tenía
                    # su propio margen (`DIAS_SIN_VELA`)») el nombre va entre comillas.
                    usos = [m for m in re.finditer(rf"(?<![`\w]){nombre}\b", fuente)]
                    self.assertEqual(usos, [], f"{ruta}: {nombre} era una copia de la regla")

    def test_los_textos_dicen_la_ultima_semana(self):
        # Las pantallas dicen «la última semana», no el número. Si `DIAS_VIEJA` deja de
        # ser 7, estos textos mienten: cambialos en el mismo commit.
        self.assertEqual(tecnico.DIAS_VIEJA, 7, "cambiá los textos de abajo junto con el número")
        textos = {
            "frontend/src/utils/radiografia.js": "antes de la última semana",
            "frontend/src/utils/backtesting.js": "la última semana",
        }
        for ruta, frase in textos.items():
            with open(os.path.join(RAIZ, ruta), encoding="utf-8") as f:
                self.assertIn(frase, f.read(), ruta)


if __name__ == "__main__":
    unittest.main()
