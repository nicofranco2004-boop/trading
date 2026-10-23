"""El resumen de Mervall-E de la ficha: a pedido, uno por activo y por día, de todos.

Entra por el camino de producción: las velas las guarda el trabajo nocturno real
(`main._run_velas_diarias_job`) con Yahoo reemplazado en su punto más bajo, la
ficha y el botón se piden por HTTP, y el modelo se simula en la FRONTERA (el
cliente de Anthropic que usa ai/llm.analyze), así que pasan de verdad el armado
del pedido, la revisión del texto, el candado y el guardado.

Los casos que importan:
  · sin resumen → botón; el primero lo genera; el segundo usuario lo ve sin
    llamar al modelo; con otra vela vuelve el botón;
  · tope diario entre todos y por persona; dos pedidos a la vez = uno;
  · las proporciones y los precios que dice salen de la cuenta de Rendi, no de
    la IA (y un número inventado por la IA no se publica);
  · nada del usuario viaja a la IA; no descuenta el cupo Free; /admin ve el costo.

Corre con: cd backend && python3 -m pytest tests/test_resumen_tecnico.py
"""
import json
import os
import sys
import tempfile
import threading
import time
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

from fastapi.testclient import TestClient

import main
import tecnico
from ai import resumen_tecnico
from fechas import hoy_art_date
from tests.test_tecnico import YahooFalso, _ruedas

# Un texto que pasa la revisión con cualquier serie: sin números salvo el 200
# del promedio, 4 oraciones, sin palabras prohibidas.
BUENO = ("Viene subiendo desde hace un tiempo. Está arriba del promedio de los últimos 200 días. "
         "La fuerza del precio viene ganando fuerza. El empuje de los últimos días es para arriba.")


class ClaudeFalso:
    """El cliente de Anthropic en la frontera: `textos` es lo que contesta en
    cada llamada (el último se repite). Guarda cada pedido."""

    def __init__(self, textos=(BUENO,), demora=0.0, falla=None):
        self.textos, self.demora, self.falla = list(textos), demora, falla
        self.pedidos, self.entro = [], threading.Event()
        self.messages = self

    def parse(self, **kw):
        self.pedidos.append(kw)
        self.entro.set()
        if self.demora:
            time.sleep(self.demora)
        if self.falla:
            raise self.falla
        texto = self.textos[min(len(self.pedidos) - 1, len(self.textos) - 1)]
        out = kw["output_format"](texto=texto)
        return SimpleNamespace(
            content=[SimpleNamespace(text=json.dumps({"texto": texto}))], parsed_output=out,
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1700, output_tokens=220,
                                  cache_creation_input_tokens=0, cache_read_input_tokens=0))


class PalabrasTest(unittest.TestCase):
    """Las cuentas en palabras, con sus bordes."""

    def test_proporciones(self):
        casos = {0: "casi nada", 0.059: "casi nada", 0.06: "una parte chica", 0.25: "cerca de un cuarto",
                 0.33: "cerca de un tercio", 0.40: "algo menos de la mitad", 0.47: "casi la mitad",
                 0.49: "la mitad", 0.5: "la mitad", 0.519: "la mitad", 0.52: "un poco más de la mitad",
                 0.66: "cerca de dos tercios", 0.75: "cerca de tres cuartos", 0.9: "casi todo",
                 0.94: "prácticamente todo", 1.0: "prácticamente todo", 1.3: "todo, y más", -0.1: "casi nada"}
        for p, frase in casos.items():
            self.assertEqual(tecnico.proporcion_en_palabras(p), frase, p)

    def test_la_frase_con_lo_que(self):
        self.assertEqual(tecnico.parte_de(0.47, "había subido"), "casi la mitad de lo que había subido")
        self.assertEqual(tecnico.parte_de(0.9, "había subido"), "casi todo lo que había subido")
        self.assertEqual(tecnico.parte_de(1.2, "había caído"), "todo lo que había caído, y más")

    def test_numeros_redondeados_a_la_argentina(self):
        n = tecnico.numero_en_palabras
        self.assertEqual(n(84012.3), "84.000")
        self.assertEqual(n(75650), "75.700")        # media para arriba, no al par
        self.assertEqual(n(1855.4), "1.855")
        self.assertEqual(n(222.5), "223")
        self.assertEqual(n(13.454), "13,45")
        self.assertEqual(n(0.00041234), "0,000412")
        self.assertEqual(tecnico.pct_en_palabras(12.5), "un 13 %")
        self.assertEqual(tecnico.pct_en_palabras(-0.4), "menos de un 1 %")
        self.assertEqual(tecnico.precio_en_palabras(6015, "ars"), "6.015 pesos")

    def test_fechas_sin_hoy_ni_ayer(self):
        f = tecnico.fecha_en_palabras
        self.assertEqual(f("2026-10-20", "2026-10-21"), "el 20 de octubre")
        self.assertEqual(f("2025-12-15", "2026-10-21"), "el 15 de diciembre de 2025")
        self.assertEqual(f("2026-10-21", "2026-10-21", con_dia=True), "el miércoles 21 de octubre")

    def test_revision_del_texto(self):
        hechos = {"activo": "Apple", "moneda": "dólares", "ultimo_cierre": "el miércoles 21 de octubre: 344 dólares",
                  "hechos": ["Subió de 309 dólares (el 31 de julio) a 344 dólares (el 21 de octubre)."]}
        graves, largo = resumen_tecnico.problemas(
            "Apple subió de 309 a 344 dólares. Está arriba del promedio de 200 días. Viene firme. Sigue así.", hechos)
        self.assertEqual((graves, largo), ([], []))
        # Un número que la IA calculó (la diferencia, un porcentaje) no se publica.
        graves, _ = resumen_tecnico.problemas(
            "Apple subió 35 dólares. Ganó un 11 %. Está arriba del promedio. Viene firme.", hechos)
        self.assertTrue(any("35" in g and "11" in g for g in graves), graves)
        # «1.855» y «1855» son el mismo número.
        h2 = {**hechos, "hechos": ["Estaba en 1.855 dólares."]}
        self.assertEqual(resumen_tecnico.problemas("Cerró en 1855 dólares. A. B. C.", h2)[0], [])
        # Fechas relativas y jerga.
        graves, _ = resumen_tecnico.problemas("Ayer devolvió parte. A. B. C.", hechos)
        self.assertTrue(any("ayer" in g and "devolvió" in g for g in graves), graves)
        graves, _ = resumen_tecnico.problemas("Es un buen momento para comprar. A. B. C.", hechos)
        self.assertTrue(graves)
        # Largo: más de 100 palabras se rehace; en el segundo intento se toleran 120.
        largo_txt = " ".join(["palabra"] * 105) + ". B. C. D."
        self.assertTrue(resumen_tecnico.problemas(largo_txt, hechos)[1])
        self.assertFalse(resumen_tecnico.problemas(largo_txt, hechos, segunda=True)[1])
        self.assertTrue(resumen_tecnico.problemas("Una sola oración.", hechos)[1])


class ResumenTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions",
                      "brokers", "fx_rates_daily", "resumenes_tecnicos", "ai_usage_daily"):
                conn.execute(f"DELETE FROM {t}")
            ids = []
            for quien in ("a", "b", "adm"):
                cur = conn.execute(
                    "INSERT INTO users (email, password_hash, approved, email_verified, tier, is_admin) "
                    "VALUES (?, 'x', 1, 1, 'free', ?)", (f"res-{quien}-{tag}@rendi.test", int(quien == "adm")))
                ids.append(cur.lastrowid)
            conn.commit()
        self.uid, self.uid2, self.admin = ids
        self.h, self.h2, self.h_admin = ({"Authorization": f"Bearer {main.create_token(u)}"} for u in ids)
        self.hoy = hoy_art_date()
        self.yahoo = YahooFalso(self.hoy)
        self.claude = ClaudeFalso()
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   mock.patch("ai.llm._get_anthropic_client", lambda: self.claude)]
        for p in self._p:
            p.start()
        # Una acción de EE.UU. que se sigue: bajó de 130 a 100, subió a 200,
        # bajó a 150 (perdió la mitad de lo que había subido) y volvió a 175
        # (recuperó la mitad de lo que había perdido).
        self._posicion("Schwab", "USD", "MSFT")
        self.yahoo.precios["MSFT"] = self._serie
        main._run_velas_diarias_job()

    def tearDown(self):
        for p in self._p:
            p.stop()

    @staticmethod
    def _serie(i, d):
        if i <= 650:
            return 130 - 30 * i / 650
        if i <= 710:
            return 100 + 100 * (i - 650) / 60
        if i <= 740:
            return 200 - 50 * (i - 710) / 30
        return 150 + 25 * (i - 740) / 19

    def _posicion(self, broker, moneda, asset, tipo="STOCK", h=None):
        self.client.post("/api/brokers", json={"name": broker, "currency": moneda}, headers=h or self.h)
        r = self.client.post("/api/positions", json={"broker": broker, "asset": asset, "quantity": 10,
                                                     "buy_price": 123.45, "asset_type": tipo},
                             headers=h or self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _ficha(self, asset="MSFT", h=None, moneda="usd"):
        r = self.client.get(f"/api/tecnico/{asset}?moneda={moneda}", headers=h or self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _pedir(self, asset="MSFT", h=None, client=None):
        r = (client or self.client).post(f"/api/tecnico/{asset}/resumen?moneda=usd", headers=h or self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _fila(self, asset="MSFT"):
        with main.db_abierta() as conn:
            r = conn.execute("SELECT * FROM resumenes_tecnicos WHERE ticker = ?", (asset,)).fetchone()
        return dict(r) if r else None

    # ── El recorrido entero ──────────────────────────────────────────────────

    def test_sin_resumen_boton_el_primero_genera_y_el_segundo_lo_ve_gratis(self):
        f = self._ficha()
        self.assertEqual(f["resumen"]["estado"], "no_hay")
        self.assertEqual(self.claude.pedidos, [], "abrir la ficha no llama al modelo")

        r = self._pedir()
        self.assertEqual((r["estado"], r["texto"]), ("listo", BUENO))
        self.assertEqual(len(self.claude.pedidos), 1)
        kw = self.claude.pedidos[0]
        self.assertEqual(kw["model"], "claude-sonnet-5-5")
        self.assertEqual(kw["output_config"], {"effort": "low"})
        self.assertNotIn("cache_control", kw["system"][0], "uno por día: el caché de 1 h sólo encarecería")

        # Otro usuario: lo ve al abrir la ficha, y tocar el botón no lo regenera.
        f2 = self._ficha(h=self.h2)
        self.assertEqual((f2["resumen"]["estado"], f2["resumen"]["texto"]), ("listo", BUENO))
        self.assertEqual(f2["resumen"]["fecha"], f2["lectura"]["fecha"])
        self.assertEqual(self._pedir(h=self.h2)["texto"], BUENO)
        self.assertEqual(len(self.claude.pedidos), 1, "el segundo no llama al modelo")

        fila = self._fila()
        self.assertEqual((fila["estado"], fila["llamadas"], fila["pedido_por"]), ("listo", 1, self.uid))
        # 1700 tokens a US$ 2/M + 220 a US$ 10/M = US$ 0,0056 → 56 (1 = US$ 0,0001).
        self.assertEqual(fila["cost_usd_cents"], 56)

        # No descuenta el cupo Free de IA.
        with main.db_abierta() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ai_usage_daily").fetchone()[0], 0)

        # /admin ve cuántos y cuánto costaron.
        a = self.client.get("/api/admin/velas", headers=self.h_admin).json()["resumenes"]
        hoy = a["por_dia"][0]
        self.assertEqual((hoy["listos"], hoy["fallidos"], hoy["llamadas"], hoy["costo_usd"]), (1, 0, 1, 0.0056))

    def test_con_otra_vela_vuelve_el_boton(self):
        self.assertEqual(self._pedir()["estado"], "listo")
        antes = self._ficha()["lectura"]["fecha"]
        # La noche siguiente: el trabajo nocturno trae velas nuevas.
        manana = self.hoy + timedelta(days=3)
        self.yahoo.hoy = manana
        with mock.patch("fechas.hoy_art", lambda: manana.isoformat()):
            main._run_velas_diarias_job()
        f = self._ficha()
        self.assertGreater(f["lectura"]["fecha"], antes)
        self.assertEqual(f["resumen"]["estado"], "no_hay")
        self.assertEqual(self._pedir()["estado"], "listo")
        self.assertEqual(len(self.claude.pedidos), 2)

    def test_lo_que_se_le_manda_son_las_cuentas_de_rendi_y_nada_tuyo(self):
        self._pedir()
        msg = self.claude.pedidos[0]["messages"][0]["content"]
        datos = json.loads(msg[msg.index("```json") + 7:msg.rindex("```")])
        self.assertEqual(set(datos), {"activo", "moneda", "ultimo_cierre", "hechos"})
        self.assertEqual(datos["activo"], "Microsoft")
        texto = " ".join(datos["hechos"])
        # Las proporciones vienen hechas: subió de 100 a 200, bajó a 150, volvió a 175.
        self.assertIn("Subió de 100 dólares", texto)
        self.assertIn("a 200 dólares", texto)
        self.assertIn("perdió la mitad de lo que había subido", texto)
        self.assertIn("recuperó la mitad de lo que había perdido", texto)
        self.assertIn("Al último cierre estaba en 175 dólares", texto)
        # El pico de cierre del tramo es el máximo del año: un solo número.
        self.assertIn("fue el más alto del último año; al último cierre está un 13 % abajo", texto)
        self.assertNotIn("202", texto, "el pico del día (200 × 1,01) no aparece como si fuera un cierre")
        self.assertNotRegex(json.dumps(datos, ensure_ascii=False), r"\b(hoy|ayer)\b")
        # Nada del usuario: ni su precio de compra, ni su broker, ni su mail.
        todo = json.dumps(self.claude.pedidos[0], default=str, ensure_ascii=False)
        for propio in ("123", "Schwab", "rendi.test", "promedio de compra", "Ganás", "Perdés"):
            self.assertNotIn(propio, todo)

    # ── Topes ────────────────────────────────────────────────────────────────

    def test_tope_diario_entre_todos(self):
        self._posicion("Schwab", "USD", "KO", h=self.h2)
        self.yahoo.precios["KO"] = lambda i, d: 60 + i * 0.01
        main._run_velas_diarias_job()
        self.assertEqual(self._pedir()["estado"], "listo")
        with mock.patch.object(resumen_tecnico, "TOPE_DIARIO", 1):
            r = self._pedir("KO", h=self.h2)
            self.assertEqual(r["estado"], "tope")
            # El que ya existe se sigue viendo con el tope lleno.
            self.assertEqual(self._pedir(h=self.h2)["estado"], "listo")
        self.assertEqual(len(self.claude.pedidos), 1)

    def test_tope_por_persona(self):
        self._posicion("Schwab", "USD", "KO")
        self.yahoo.precios["KO"] = lambda i, d: 60 + i * 0.01
        main._run_velas_diarias_job()
        with mock.patch.object(resumen_tecnico, "TOPE_POR_PERSONA", 1):
            self.assertEqual(self._pedir()["estado"], "listo")
            self.assertEqual(self._pedir("KO")["estado"], "tope_persona")
            self.assertEqual(self._pedir("KO", h=self.h2)["estado"], "listo", "otra persona sí puede")

    # ── Dos a la vez ─────────────────────────────────────────────────────────

    def test_dos_pedidos_a_la_vez_generan_uno(self):
        """Los dos LEEN que no hay resumen al mismo tiempo (una barrera los
        hace coincidir ahí) y los dos intentan escribir: uno solo reclama la
        fila y el otro espera su texto."""
        self.claude.demora = 1.0
        barrera = threading.Barrier(2, timeout=10)
        original = resumen_tecnico._fila
        local = threading.local()

        def fila_con_barrera(conn, clave):
            r = original(conn, clave)
            if not getattr(local, "paso", False):
                local.paso = True
                barrera.wait()
            return r

        resultados = []

        def pedir(h):
            resultados.append(self._pedir(h=h, client=TestClient(main.app)))

        with mock.patch.object(resumen_tecnico, "_fila", fila_con_barrera):
            hilos = [threading.Thread(target=pedir, args=(h,)) for h in (self.h, self.h2)]
            for t in hilos:
                t.start()
            for t in hilos:
                t.join(30)
        self.assertEqual(len(self.claude.pedidos), 1, "un solo llamado al modelo")
        self.assertEqual([r["estado"] for r in resultados], ["listo", "listo"])
        self.assertEqual({r["texto"] for r in resultados}, {BUENO})

    def test_el_que_genera_se_colgo_y_otro_lo_toma(self):
        with main.db_abierta() as conn:
            clave = resumen_tecnico.clave_de(tecnico.para_la_ficha(conn, "MSFT", "usd"))
            viejo = "2000-01-01T00:00:00"
            conn.execute("""INSERT INTO resumenes_tecnicos (ticker, moneda, fecha_vela, estado, dia, empezado_at)
                            VALUES (?, ?, ?, 'generando', ?, ?)""", (*clave, self.hoy.isoformat(), viejo))
            conn.commit()
        self.assertEqual(self._ficha()["resumen"]["estado"], "no_hay")
        self.assertEqual(self._pedir()["estado"], "listo")

    # ── Revisión del texto y fallas ──────────────────────────────────────────

    def test_largo_de_mas_se_rehace_una_vez(self):
        largo = " ".join(["Viene subiendo"] * 60) + ". Sigue. Y sigue. Fin."
        self.claude.textos = [largo, BUENO]
        self.assertEqual(self._pedir()["texto"], BUENO)
        self.assertEqual(len(self.claude.pedidos), 2)
        self.assertIn("palabras", self.claude.pedidos[1]["messages"][0]["content"],
                      "el segundo pedido le dice qué estuvo mal")
        fila = self._fila()
        self.assertEqual((fila["llamadas"], fila["cost_usd_cents"]), (2, 112), "se registran los dos")

    def test_un_numero_inventado_no_se_publica(self):
        malo = "Subió 37 dólares. Ganó un 58 %. Está arriba del promedio de los últimos 200 días. Fin."
        self.claude.textos = [malo]
        self.assertEqual(self._pedir()["estado"], "error")
        self.assertEqual(len(self.claude.pedidos), 2)
        fila = self._fila()
        self.assertEqual((fila["estado"], fila["texto"], fila["llamadas"]), ("fallo", None, 2))
        self.assertIn("37", fila["error"])
        # La ficha sigue entera y el botón vuelve.
        f = self._ficha()
        self.assertTrue(f["disponible"])
        self.assertEqual(f["resumen"]["estado"], "no_hay")
        # Y después de tantos intentos, no se ofrece más ese día.
        self._pedir()
        self.assertIsNone(self._ficha()["resumen"])
        self.assertEqual(self._pedir()["estado"], "no_disponible")
        self.assertEqual(len(self.claude.pedidos), 4)

    def test_si_el_modelo_se_cae_nada_se_rompe(self):
        self.claude.falla = RuntimeError("se cayó Anthropic")
        self.assertEqual(self._pedir()["estado"], "error")
        self.assertEqual(self._fila()["estado"], "fallo")
        self.assertTrue(self._ficha()["disponible"])
        self.claude.falla = None
        self.assertEqual(self._pedir()["estado"], "listo")

    def test_sin_ia_configurada_no_se_ofrece(self):
        with mock.patch("ai.llm._get_anthropic_client", lambda: None):
            f = self._ficha()
            self.assertTrue(f["disponible"])
            self.assertIsNone(f["resumen"])
            self.assertEqual(self._pedir()["estado"], "no_disponible")

    def test_precios_viejos_no_se_ofrece(self):
        with mock.patch.object(resumen_tecnico, "DIAS_VELA_VIEJA", -5):
            self.assertIsNone(self._ficha()["resumen"])
            self.assertEqual(self._pedir()["estado"], "no_disponible")
        self.assertEqual(self.claude.pedidos, [])

    def test_lo_que_no_tiene_velas(self):
        f = self._ficha("NADA")
        self.assertFalse(f["disponible"])
        self.assertNotIn("resumen", f) if "resumen" not in f else self.assertIsNone(f["resumen"])
        self.assertEqual(self._pedir("NADA")["estado"], "no_disponible")


if __name__ == "__main__":
    unittest.main()
