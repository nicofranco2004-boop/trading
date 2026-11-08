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
from datetime import date, datetime, timedelta
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
from ai import resumen_tecnico_hechos as rh
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

    def create(self, **kw):
        self.pedidos.append(kw)
        self.entro.set()
        if self.demora:
            time.sleep(self.demora)
        if self.falla:
            raise self.falla
        texto = self.textos[min(len(self.pedidos) - 1, len(self.textos) - 1)]
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=texto)], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=1700, output_tokens=220))


class PalabrasTest(unittest.TestCase):
    """Las cuentas en palabras (resumen_tecnico_hechos), con sus bordes."""

    def test_proporciones(self):
        casos = {0: "casi nada", 0.119: "casi nada", 0.12: "más o menos un cuarto", 0.33: "más o menos un tercio",
                 0.42: "más o menos la mitad", 0.5: "más o menos la mitad", 0.58: "casi dos tercios",
                 0.75: "más o menos tres cuartos", 0.9: "casi todo", 0.976: "casi todo", 1.0: "todo", 1.03: "todo",
                 1.2: "todo y un poco más"}
        for q, frase in casos.items():
            self.assertEqual(rh.proporcion(q), frase, q)

    def test_numeros_redondeados_a_la_argentina(self):
        self.assertEqual(rh.num(84012.3), "84.000")
        self.assertEqual(rh.num(1855.4), "1.855")
        self.assertEqual(rh.num(222.4), "222")
        self.assertEqual(rh.num(37.42), "37,4")
        self.assertEqual(rh.num(4.564), "4,56")
        self.assertEqual(rh.num(0.00041234), "0,000412", "una cripto chica no dice «0 dólares»")
        self.assertEqual(rh.plata(6015, "ars"), "6.015 pesos")
        self.assertEqual(rh.pct(-0.4), "menos de 1 %")

    def test_fechas_sin_hoy_ni_ayer(self):
        self.assertEqual(rh.fecha("2026-10-20", "2026-10-21"), "20 de octubre")
        self.assertEqual(rh.fecha("2025-12-15", "2026-10-21"), "15 de diciembre del año pasado")
        self.assertEqual(rh.fecha("2024-12-15", "2026-10-21"), "15 de diciembre de 2024")

    @staticmethod
    def _ficha(cierres, en_curso):
        """Una respuesta de la ficha con estos cierres (el último es el último dato)."""
        hoy = date(2026, 10, 21)
        dias = [(hoy - timedelta(days=len(cierres) - 1 - i)).isoformat() for i in range(len(cierres))]
        pts = [{"d": d, "c": c} for d, c in zip(dias, cierres)]
        return {"disponible": True, "moneda": "usd", "puntos": pts,
                "lectura": {"fecha": dias[-1], "precio": cierres[-1]},
                "fibonacci": {"disponible": False, "en_curso": {**en_curso, "desde": {"fecha": dias[0], "precio": cierres[0]}}}}

    def test_en_su_maximo_no_se_cuenta_otro_pico_del_dia(self):
        # Cierra en 344, el cierre más alto del año; el 13 de octubre había
        # TOCADO 348 durante el día. No se dicen los dos.
        cierres = [300 + i * 0.1 for i in range(400)] + [344.0]
        f = self._ficha(cierres, {"dir": "suba", "hasta": {"fecha": "2026-10-13", "precio": 348.0}})
        h = rh.para_el_resumen(f, "Apple")
        self.assertIn("y cerró en su precio más alto del año", h["para_el_titular"])
        self.assertIn("hasta el último cierre", h["movimientos_recientes"]["el_movimiento_de_ahora"])
        self.assertNotIn("348", json.dumps(h, ensure_ascii=False))

    def test_un_cedear_estimado_en_pesos_lo_dice(self):
        # En pesos, un CEDEAR sin su serie en pesos: la ficha manda `escala` y sus
        # precios son un estimado (tecnico.serie). El resumen y el chat lo saben,
        # como el pie del gráfico; lo demás no cambia.
        cierres = [300 + i * 0.1 for i in range(400)]
        en_curso = {"dir": "suba", "hasta": {"fecha": "2026-10-13", "precio": 340.0}}
        f = {**self._ficha(cierres, en_curso), "moneda": "ars"}
        estimada = {**f, "escala": 20.0}
        for de in (rh.para_el_resumen, rh.para_el_chat):
            h, he = de(f, "Apple"), de(estimada, "Apple")
            self.assertNotIn("los_precios_en_pesos_son", h)
            self.assertIn("estimado del CEDEAR", he["los_precios_en_pesos_son"])
            self.assertEqual({k: v for k, v in he.items() if k != "los_precios_en_pesos_son"}, h)

    def test_con_menos_de_un_anio_de_historia_no_se_rompe(self):
        # Una acción o una cripto nueva: no hay «en un año», el titular sale de
        # los tres meses. Comparar el año (que no existe) con 0 tiraba el pedido.
        cierres = [100 + i * 0.5 for i in range(150)] + [160.0 - i for i in range(20)]
        f = self._ficha(cierres, {"dir": "bajada", "hasta": {"fecha": "2026-10-21", "precio": 140.0},
                                  "se_rompe_si_cierra": {"encima_de": 175.0, "fecha": "2026-10-01"}})
        h = rh.para_el_resumen(f, "Nueva")
        self.assertTrue(h["para_el_titular"].startswith("En tres meses"))

    def test_despues_de_un_hueco_de_precios_no_dice_en_un_anio_como_la_ficha(self):
        # Sin precios del 25/09 al 31/10/2025, el cierre de «hace un año» (21/10/2025)
        # sería el del 24/09, 27 días antes: la ficha no daba la ganancia de 12 meses y
        # su resumen decía «En un año subió…» (auditoría 06/11 del precio de arranque,
        # H1). Con LA misma regla (`tecnico.base_vieja`), callan los dos.
        hoy = date(2026, 10, 21)
        todos = [hoy - timedelta(days=k) for k in range(800, -1, -1)]
        hueco = [d for d in todos if not date(2025, 9, 25) <= d <= date(2025, 10, 31)]
        for dias, dice_el_anio in ((todos, True), (hueco, False)):
            n = len(dias)
            # Sube y en las últimas 20 ruedas baja: lejos del máximo y del mínimo del año.
            cierres = [100 + i * 0.1 for i in range(n - 20)] + [100 + (n - 21) * 0.1 - 0.5 * (k + 1) for k in range(20)]
            velas = [{"date": d.isoformat(), "close": c} for d, c in zip(dias, cierres)]
            pts = [{"d": v["date"], "c": v["close"]} for v in velas]
            ficha = {"disponible": True, "moneda": "usd", "puntos": pts,
                     "lectura": {"fecha": pts[-1]["d"], "precio": pts[-1]["c"]},
                     "fibonacci": {"disponible": False, "en_curso": {
                         "dir": "suba", "hasta": {"fecha": pts[-21]["d"], "precio": pts[-21]["c"]},
                         "desde": {"fecha": pts[0]["d"], "precio": pts[0]["c"]}}}}
            with self.subTest(hueco=not dice_el_anio):
                self.assertEqual(tecnico.lectura(velas)["rend_12m"] is not None, dice_el_anio)
                titular = rh.para_el_resumen(ficha, "Nueva")["para_el_titular"]
                self.assertEqual(titular.startswith("En un año"), dice_el_anio, titular)
                if not dice_el_anio:
                    self.assertTrue(titular.startswith("En tres meses"), titular)

    def test_cerca_del_maximo_no_dice_que_es_el_maximo(self):
        # El día anterior cerró en 30.420 y el último en 30.300 (0,4 % abajo).
        cierres = [20000 + i * 25 for i in range(399)] + [30420.0, 30300.0]
        f = self._ficha(cierres, {"dir": "suba", "hasta": {"fecha": "2026-10-20", "precio": 30600.0}})
        h = rh.para_el_resumen(f, "Coca-Cola")
        self.assertIn("y cerró muy cerca de su precio más alto del año", h["para_el_titular"])
        self.assertNotIn("el último cierre es ese mismo", h["cierre_mas_alto_del_año"])

    def test_revision_del_texto(self):
        hechos = {"activo": "Apple", "moneda": "dólares", "ultimo_cierre": "21 de octubre",
                  "movimientos_recientes": {"el_movimiento_de_ahora": "subió de 309 dólares (31 de julio) a 344 dólares"}}
        graves, largo = resumen_tecnico.problemas(
            "Apple subió de 309 a 344 dólares. Está arriba del promedio de 200 días. Tiene fuerza. Sigue así.", hechos)
        self.assertEqual((graves, largo), ([], []))
        # Un número que la IA calculó (la diferencia, un porcentaje) no se publica.
        graves, _ = resumen_tecnico.problemas(
            "Apple subió 35 dólares. Ganó un 11 %. Está arriba del promedio. Viene firme.", hechos)
        self.assertTrue(any("35" in g and "11" in g for g in graves), graves)
        # «1.855» y «1855» son el mismo número.
        h2 = {**hechos, "precio_al_ultimo_cierre": "1.855 dólares"}
        self.assertEqual(resumen_tecnico.problemas("Cerró en 1855 dólares. A. B. C.", h2)[0], [])
        # Fechas relativas y jerga.
        graves, _ = resumen_tecnico.problemas("Ayer devolvió parte. A. B. C.", hechos)
        self.assertTrue(any("ayer" in g and "devolvió" in g for g in graves), graves)
        graves, _ = resumen_tecnico.problemas("Es un buen momento para comprar. A. B. C.", hechos)
        self.assertTrue(graves)
        # El cierre es neutro (decisión de Nico, 23/10): la primera persona o un
        # consejo se rehace, y si vuelve, no se publica.
        for consejo in ("Yo miraría los 344 dólares.", "Te conviene esperar.", "Yo compraría acá.",
                        "Te sugiero mirar los 309.", "Vendería en 344."):
            graves, _ = resumen_tecnico.problemas(consejo + " A. B. C.", hechos)
            self.assertTrue(graves, consejo)
        neutro = ("Lo que se mira es si cierra abajo de 309 dólares: si pasa, podría ser una señal de que "
                  "la suba está perdiendo fuerza. A. B. C.")
        self.assertEqual(resumen_tecnico.problemas(neutro, hechos)[0], [])
        # Y como posibilidad, no como certeza (Nico, 23/10). El pasado sí se cuenta.
        for certeza in ("Ahí se terminaría la suba.", "Ahí se termina la suba.", "Eso confirmaría la bajada.",
                        "La suba se cortaría.", "Seguramente vuelve a subir."):
            self.assertTrue(resumen_tecnico.problemas(certeza + " A. B. C.", hechos)[0], certeza)
        self.assertEqual(resumen_tecnico.problemas("La suba terminó el 31 de julio. A. B. C.", hechos)[0], [])
        # Largo (decisión de Nico, 23/10): 120 es un tope, no una meta. Hasta 120
        # pasa; más se rehace; en el segundo intento se toleran 130.
        de_116 = " ".join(["palabra"] * 113) + ". B. C. D."
        self.assertFalse(resumen_tecnico.problemas(de_116, hechos)[1])
        de_125 = " ".join(["palabra"] * 122) + ". B. C. D."
        self.assertTrue(resumen_tecnico.problemas(de_125, hechos)[1])
        self.assertFalse(resumen_tecnico.problemas(de_125, hechos, segunda=True)[1])
        self.assertTrue(resumen_tecnico.problemas(" ".join(["palabra"] * 135) + ". B. C. D.", hechos, segunda=True)[1])
        self.assertTrue(resumen_tecnico.problemas("Una sola oración.", hechos)[1])
        con_fuerza = {**hechos, "indicador_que_suma": {resumen_tecnico.FRASE_DE_FUERZA: "La bajada se quedó sin fuerza"}}
        # Con la frase del ADX + Squeeze el tope es 130 (Nico, 23/10); en el
        # segundo intento, 141. Sin ella, 120 y 130: el de 125 se rehace.
        self.assertFalse(resumen_tecnico.problemas(de_125, con_fuerza)[1])
        de_134 = " ".join(["palabra"] * 131) + ". B. C. D."
        self.assertTrue(resumen_tecnico.problemas(de_134, con_fuerza)[1])
        self.assertFalse(resumen_tecnico.problemas(de_134, con_fuerza, segunda=True)[1])
        self.assertTrue(resumen_tecnico.problemas(" ".join(["palabra"] * 142) + ". B. C. D.", con_fuerza, segunda=True)[1])
        # Y si se pasa igual, el aviso no le pide sacar esa frase (lo que hacía).
        aviso = resumen_tecnico.problemas(de_134, con_fuerza)[1][0]
        self.assertIn("el tope es 130", aviso)
        self.assertIn("oración 2", aviso)
        self.assertNotIn("sacá la oración 4", aviso)
        # Una corrección a la vista (vuelta 7 de la redacción) o un salto de línea.
        graves, largo = resumen_tecnico.problemas("Subió a 344. Corrijo: a 309. A. B.", hechos)
        self.assertTrue(graves)
        self.assertTrue(resumen_tecnico.problemas("Subió a 344. A.\nB. C.", hechos)[1])


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
        self._posicion("Schwab", "USD", "MSFT")
        self.yahoo.precios["MSFT"] = self._serie
        main._run_velas_diarias_job()

    def tearDown(self):
        for p in self._p:
            p.stop()

    # Una acción de EE.UU. que se sigue: después de unas idas y vueltas, una
    # suba de 100 a 200 que terminó, y una bajada que ya deshizo la mitad.
    PUNTOS = [(0, 120), (150, 140), (200, 125), (250, 145), (300, 120), (400, 130), (500, 100), (600, 110),
              (620, 105), (650, 160), (665, 150), (700, 200), (730, 140), (745, 165), (759, 150)]

    @classmethod
    def _serie(cls, i, d):
        for (a, va), (b, vb) in zip(cls.PUNTOS, cls.PUNTOS[1:]):
            if a <= i <= b:
                return va + (vb - va) * (i - a) / (b - a)

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

    def test_un_cedear_estimado_en_pesos_no_muestra_el_resumen_de_antes_y_dice_que_es_estimado(self):
        # Apple a pedido, en pesos: el gráfico es el CEDEAR estimado (× el MEP ÷ 20).
        # Antes era la acción entera, y un resumen escrito ese día con aquella
        # cuenta («cerró en 546.700 pesos») se seguía mostrando al lado del gráfico
        # nuevo hasta la vela siguiente: la clave era la misma (auditoría 06/11, H2
        # de la pantalla). Y el texto nuevo dice que es un estimado sin depender del
        # modelo (H3).
        with main.db_abierta() as conn:
            for d in _ruedas(self.hoy, 760):
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?, 1100.0, 1000.0) "
                             "ON CONFLICT(date) DO NOTHING", (d.isoformat(),))
            conn.commit()
        self.yahoo.precios["AAPL"] = self._serie
        f = self._ficha("AAPL", moneda="ars")
        self.assertEqual((f["ticker"], f["escala"]), ("AAPL", 20))
        fecha = f["lectura"]["fecha"]
        with main.db_abierta() as conn:          # lo que dejó el código de antes ese día
            conn.execute("INSERT INTO resumenes_tecnicos (ticker, moneda, fecha_vela, estado, texto, dia) "
                         "VALUES ('AAPL', 'ars', ?, 'listo', 'El 5 de noviembre cerró en 546.700 pesos.', ?)",
                         (fecha, self.hoy.isoformat()))
            conn.commit()
        self.assertEqual(self._ficha("AAPL", moneda="ars")["resumen"]["estado"], "no_hay")
        r = self.client.post("/api/tecnico/AAPL/resumen?moneda=ars", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["estado"], "listo")
        self.assertEqual(r.json()["texto"], f"{BUENO} {tecnico.NOTA_ESTIMADO}")
        self.assertIn("los_precios_en_pesos_son", self.claude.pedidos[0]["messages"][0]["content"])
        self.assertEqual(self._fila("AAPL÷20")["estado"], "listo")
        self.assertEqual(self._ficha("AAPL", moneda="ars")["resumen"]["texto"], f"{BUENO} {tecnico.NOTA_ESTIMADO}")
        # En dólares, la clave de siempre y el texto del modelo, sin la frase.
        self.assertEqual(resumen_tecnico.clave_de(self._ficha("AAPL"))[0], "AAPL")

    def test_sin_resumen_boton_el_primero_genera_y_el_segundo_lo_ve_gratis(self):
        f = self._ficha()
        self.assertEqual(f["resumen"]["estado"], "no_hay")
        self.assertEqual(self.claude.pedidos, [], "abrir la ficha no llama al modelo")

        r = self._pedir()
        self.assertEqual((r["estado"], r["texto"]), ("listo", BUENO))
        self.assertEqual(len(self.claude.pedidos), 1)
        kw = self.claude.pedidos[0]
        self.assertEqual(kw["model"], "claude-sonnet-5-5")
        self.assertEqual(kw["extra_body"], {"output_config": {"effort": "low"}})
        self.assertEqual(kw["system"], resumen_tecnico.SISTEMA, "el pedido del archivo, sin caché")
        self.assertIn("Sos Mervall-E", kw["system"])
        # La forma del cierre que pidió Nico el 30/10 (antes «Lo que se mira es si… : si pasa,…»).
        self.assertIn("Lo que se mira:", kw["system"])
        self.assertNotRegex(kw["system"], r"[Yy]o miraría|mirarías vos")
        # 120 es un tope, no una meta (Nico, 23/10): nada de «entre 60 y 80».
        self.assertIn("Nunca más de 120 (130 si los datos traen «fuerza_del_movimiento»)", kw["system"])
        self.assertNotIn("entre 60 y 80", kw["system"])
        self.assertNotRegex(kw["system"], r"se terminar[íi]a|se termina\b", "lo que se mira, como posibilidad")
        self.assertIn("podría ser una señal de que", kw["system"])

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
        self.assertTrue(msg.startswith("Datos del activo:\n"))
        datos = json.loads(msg.split("\n", 1)[1])
        self.assertEqual(datos["activo"], "Microsoft")
        self.assertEqual(list(datos)[0], "para_el_titular", "el titular va primero")
        movs = datos["movimientos_recientes"]
        # La proporción viene hecha: subió de 99 a 202 (lo que tocó) y al último
        # cierre (150) había perdido 52 de 103 → «más o menos la mitad».
        ultima = movs["la_ultima_suba_o_bajada_terminada"]
        self.assertIn("subió de 99 dólares", ultima)
        self.assertIn("a 202 dólares", ultima)
        self.assertIn("de esa suba había perdido más o menos la mitad", ultima)
        self.assertEqual(datos["precio_al_ultimo_cierre"], "150 dólares")
        # Lo que se mira, como posibilidad y con la misma forma que la tarjeta de Fibonacci.
        # «la caída», como pidió Nico el 30/10 (la tarjeta de Fibonacci dice lo mismo).
        self.assertIn("podría ser una señal de que la caída está perdiendo fuerza", movs["lo_que_se_mira"])
        self.assertNotRegex(json.dumps(datos, ensure_ascii=False), r"terminar[íi]a")
        # El cierre más alto del año cae el día del pico: no se repite su precio.
        self.assertIn("no repitas su precio", datos["cierre_mas_alto_del_año"])
        # Un solo indicador, elegido por regla (o ninguno): nunca la lista entera.
        self.assertNotIn("indicadores", datos)
        self.assertLessEqual(len(datos.get("indicador_que_suma") or {}), 1)
        # El último dato va con su fecha, nunca como «ayer».
        self.assertRegex(datos["ultimo_cierre"], r"^\d+ de [a-z]+ \(es el último dato")
        self.assertNotIn("ayer", msg)
        # Nada del usuario: ni su precio de compra, ni su broker, ni su mail.
        todo = json.dumps(self.claude.pedidos[0], default=str, ensure_ascii=False)
        for propio in ("123", "Schwab", "rendi.test", "Ganás", "Perdés", "Contra lo que pagaste"):
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
        # El segundo no se queda esperando (auditoría final E2): «generando» al
        # instante, y la pantalla vuelve a preguntar.
        self.assertEqual(sorted(r["estado"] for r in resultados), ["generando", "listo"])
        self.assertEqual({r.get("texto") for r in resultados}, {BUENO, None})
        self.assertEqual(self._pedir(h=self.h2)["texto"], BUENO, "al volver a preguntar, está")
        self.assertEqual(len(self.claude.pedidos), 1)

    def test_mientras_uno_genera_los_demas_no_esperan_fuera_del_freno(self):
        """Auditoría final E2 (31/10): el segundo pedido esperaba hasta 30 s a que
        el primero terminara, fuera del freno de la ficha: una sola cuenta tuvo
        30 pedidos esperando a la vez. Ahora el que encuentra la fila tomada
        contesta «generando» en el momento."""
        self.claude.demora = 4.0
        primero = []
        t = threading.Thread(target=lambda: primero.append(self._pedir(client=TestClient(main.app))))
        t.start()
        self.assertTrue(self.claude.entro.wait(10))
        for _ in range(8):
            t0 = time.monotonic()
            r = self._pedir()
            self.assertEqual(r["estado"], "generando")
            self.assertLess(time.monotonic() - t0, 2.0, "contesta al instante, no espera al otro")
        t.join(30)
        self.assertEqual(primero[0]["estado"], "listo")
        self.assertEqual(self._pedir()["texto"], BUENO)
        self.assertEqual(len(self.claude.pedidos), 1, "un solo llamado al modelo")

    def _dos_activos_mas(self):
        for asset, base in (("KO", 60), ("PEP", 150)):
            self._posicion("Schwab", "USD", asset)
            self.yahoo.precios[asset] = lambda i, d, b=base: b + i * 0.01
        main._run_velas_diarias_job()

    def test_el_tope_por_persona_toma_el_turno_antes_de_contar(self):
        """Auditoría final E3 (31/10): con tope 1, tres pedidos juntos de la misma
        persona (activos distintos) contaban todos «0» y generaban dos o tres. El
        turno de la cuenta (`main._tomar_turno`, el arreglo E5 de los demás
        topes) se toma antes de contar: uno genera, los otros ven el tope."""
        self._dos_activos_mas()
        barrera = threading.Barrier(3, timeout=10)
        original = resumen_tecnico._vela_vieja

        def vieja(f):
            try:
                barrera.wait()
            except threading.BrokenBarrierError:
                pass
            return original(f)

        res = []
        with mock.patch.object(resumen_tecnico, "TOPE_POR_PERSONA", 1), \
                mock.patch.object(resumen_tecnico, "_vela_vieja", vieja):
            hilos = [threading.Thread(target=lambda a=a: res.append(self._pedir(a, client=TestClient(main.app))["estado"]))
                     for a in ("MSFT", "KO", "PEP")]
            for h in hilos:
                h.start()
            for h in hilos:
                h.join(30)
        self.assertEqual(sorted(res), ["listo", "tope_persona", "tope_persona"])
        self.assertEqual(len(self.claude.pedidos), 1)

    def test_el_asesor_gasta_su_tope_y_con_solo_lectura_puede_pedirlo(self):
        """Auditoría final E3: el tope contaba la cuenta que se mira, no a quien
        pide: el asesor gastaba el cupo de su cliente (y esquivaba el suyo). Y un
        asesor de sólo lectura recibía 403: el resumen no escribe nada en la
        cuenta del cliente (se guarda para todos, a nombre del que lo pidió)."""
        self._dos_activos_mas()
        with main.db_abierta() as conn:
            ase = conn.execute("INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                               "VALUES (?, 'x', 1, 1, 'advisor')", (f"res-ase-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
            conn.execute("INSERT INTO advisor_clients (advisor_uid, client_uid, link_type, permission, status, label) "
                         "VALUES (?, ?, 'linked', 'read', 'active', 'C')", (ase, self.uid2))
            conn.commit()
        h_ase = {"Authorization": f"Bearer {main.create_token(ase)}"}
        mirando = {**h_ase, "X-Rendi-Client-Id": str(self.uid2)}
        with mock.patch.object(resumen_tecnico, "TOPE_POR_PERSONA", 1):
            r = self.client.post("/api/tecnico/MSFT/resumen?moneda=usd", headers=mirando)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["estado"], "listo")
            self.assertEqual(self._fila("MSFT")["pedido_por"], ase, "a nombre del asesor, no del cliente")
            # El asesor ya gastó el suyo, mire lo que mire.
            self.assertEqual(self._pedir("KO", h=h_ase)["estado"], "tope_persona")
            self.assertEqual(self._pedir("KO", h=mirando)["estado"], "tope_persona")
            # El cliente tiene el suyo entero.
            self.assertEqual(self._pedir("PEP", h=self.h2)["estado"], "listo")
        self.assertEqual(len(self.claude.pedidos), 2)

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
        segundo = self.claude.pedidos[1]["messages"]
        self.assertEqual(segundo[1], {"role": "assistant", "content": largo}, "ve lo que escribió")
        self.assertIn("palabras", segundo[2]["content"], "y qué estuvo mal")
        fila = self._fila()
        self.assertEqual((fila["llamadas"], fila["cost_usd_cents"]), (2, 112), "se registran los dos")

    def test_en_primera_persona_se_rehace_con_el_cierre_neutro(self):
        self.claude.textos = ["Viene subiendo. Está arriba del promedio de los últimos 200 días. "
                              "Empuja para arriba. Yo miraría el precio de cerca.", BUENO]
        self.assertEqual(self._pedir()["texto"], BUENO)
        self.assertEqual(len(self.claude.pedidos), 2)
        self.assertIn("yo", self.claude.pedidos[1]["messages"][2]["content"].lower())

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
        # LA regla de «precio viejo» (`tecnico.es_vieja`, 7 días contados desde el día
        # argentino), la misma del aviso de la ficha: con el último precio de hace 7
        # días todavía se ofrece; con 8, no (antes tenía su propia copia del margen).
        with main.db_abierta() as conn:
            ultima = date.fromisoformat(conn.execute(
                "SELECT MAX(date) FROM velas_diarias WHERE symbol = 'MSFT'").fetchone()[0])
        el_dia = lambda n: mock.patch("fechas.ahora_art", return_value=datetime.combine(
            ultima + timedelta(days=n), datetime.min.time()).replace(hour=15))
        with el_dia(7):
            f = self._ficha()
            self.assertFalse(f["vieja"])
            self.assertEqual(f["resumen"]["estado"], "no_hay")
        with el_dia(8):
            f = self._ficha()
            self.assertTrue(f["vieja"])
            self.assertIsNone(f["resumen"])
            self.assertEqual(self._pedir()["estado"], "no_disponible")
        self.assertEqual(self.claude.pedidos, [])

    def test_lo_que_no_tiene_velas(self):
        f = self._ficha("NADA")
        self.assertFalse(f["disponible"])
        self.assertNotIn("resumen", f) if "resumen" not in f else self.assertIsNone(f["resumen"])
        self.assertEqual(self._pedir("NADA")["estado"], "no_disponible")


if __name__ == "__main__":
    unittest.main()
