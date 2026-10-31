"""Mervall-E entiende el análisis técnico en el chat («¿cómo viene MSFT?»).

Entra por el camino de producción: las velas las guarda el trabajo nocturno real
(`main._run_velas_diarias_job`) con Yahoo reemplazado en su punto más bajo, la
pregunta va por POST /api/ai/chat, la herramienta `get_technical_reading` se
ejecuta DE VERDAD (no se simula) y sólo el modelo es de mentira, en la frontera
(el cliente de Anthropic). Así pasan de verdad: el armado de los hechos, lo que
viaja al modelo, la revisión del texto y lo que le llega a la persona.

Lo que tiene que valer siempre:
  · los números que recibe el chat son los de la ficha (GET /api/tecnico), de la
    misma función que el resumen de la ficha;
  · lo que le llega a la persona no trae jerga técnica, ni una certeza sobre lo
    que viene, ni un consejo de compra o venta: si el modelo lo escribe, se pide
    de nuevo; si insiste, no se publica;
  · la revisión es sólo para los turnos que hablan de cómo viene un activo.

Corre con: cd backend && python3 -m pytest tests/test_lectura_tecnica_chat.py
"""
import json
import os
import sys
import tempfile
import unittest
import uuid
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
from ai import lectura_tecnica_chat as ltc
from ai import resumen_tecnico_hechos as rh
from fechas import hoy_art_date
from tests._ia_falsa import eventos
from tests.test_tecnico import YahooFalso

BUENO = ("Microsoft viene bajando desde su último pico, pero de fondo sigue para arriba. "
         "Lo que se mira es si vuelve a cerrar arriba del último pico: si pasa, podría ser una señal "
         "de que la bajada está perdiendo fuerza.")
CON_JERGA = "Microsoft tiene el RSI en zona neutral y el precio rebotó en el soporte de la media móvil."
CON_CERTEZA = "Microsoft viene firme y va a subir: seguramente pase su máximo del año."
CON_CONSEJO = "Microsoft viene firme de fondo. Es un buen momento para entrar: te conviene comprar."


class _Txt:
    type = "text"

    def __init__(self, t):
        self.text = t

    def model_dump(self):
        return {"type": "text", "text": self.text}


class _Tool:
    type = "tool_use"

    def __init__(self, nombre, entrada):
        self.name, self.input, self.id = nombre, entrada, "tu-lectura"

    def model_dump(self):
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


class ClaudeDelChat:
    """El cliente de Anthropic en la frontera. Si `herramienta`, la 1ra vuelta
    pide la lectura técnica; después contesta `textos` en orden (el último se
    repite). Guarda cada pedido para ver qué viajó."""

    def __init__(self, textos, herramienta=("get_technical_reading", {"ticker": "MSFT"})):
        self.textos, self.herramienta = list(textos), herramienta
        self.pedidos = []
        self.messages = self

    def _respuesta(self, kw):
        self.pedidos.append(kw)
        if self.herramienta and len(self.pedidos) == 1:
            return SimpleNamespace(content=[_Tool(*self.herramienta)], stop_reason="tool_use", usage=None)
        n = len(self.pedidos) - (2 if self.herramienta else 1)
        t = self.textos[min(n, len(self.textos) - 1)]
        return SimpleNamespace(content=[_Txt(t)], stop_reason="end_turn", usage=None)

    def create(self, **kw):
        return self._respuesta(kw)

    def stream(self, **kw):
        r = self._respuesta(kw)

        class _S:
            def __iter__(s):
                return eventos([b.text for b in r.content if b.type == "text"])

            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

            def get_final_message(s):
                return r
        return _S()

    def lectura_enviada(self):
        """Lo que la herramienta le devolvió al modelo (el tool_result)."""
        for kw in self.pedidos:
            for m in kw["messages"]:
                if m["role"] == "user" and isinstance(m["content"], list):
                    for b in m["content"]:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            return json.loads(b["content"])
        return None


class LecturaTecnicaChatTest(unittest.TestCase):

    PUNTOS = [(0, 120), (150, 140), (200, 125), (250, 145), (300, 120), (400, 130), (500, 100), (600, 110),
              (620, 105), (650, 160), (665, 150), (700, 200), (730, 140), (745, 165), (759, 150)]

    @classmethod
    def _serie(cls, i, d):
        for (a, va), (b, vb) in zip(cls.PUNTOS, cls.PUNTOS[1:]):
            if a <= i <= b:
                return va + (vb - va) * (i - a) / (b - a)

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions",
                      "brokers", "fx_rates_daily", "resumenes_tecnicos", "ai_usage_daily"):
                conn.execute(f"DELETE FROM {t}")
            ids = []
            for tier in ("pro", "free"):
                cur = conn.execute(
                    "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                    "VALUES (?, 'x', 1, 1, ?)", (f"lect-{tier}-{tag}@rendi.test", tier))
                ids.append(cur.lastrowid)
            conn.commit()
        self.uid, self.uid_free = ids
        self.h, self.h_free = ({"Authorization": f"Bearer {main.create_token(u)}"} for u in ids)
        self.yahoo = YahooFalso(hoy_art_date())
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("main._kick_bench_refresh", lambda: None),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {})]
        for p in self._p:
            p.start()
        # Alguien sigue Microsoft: el trabajo nocturno guarda sus velas.
        self.client.post("/api/brokers", json={"name": "Schwab", "currency": "USD"}, headers=self.h)
        self.client.post("/api/positions", json={"broker": "Schwab", "asset": "MSFT", "quantity": 10,
                                                 "buy_price": 123.45, "asset_type": "STOCK"}, headers=self.h)
        self.yahoo.precios["MSFT"] = self._serie
        main._run_velas_diarias_job()

    def tearDown(self):
        for p in self._p:
            p.stop()

    # ── el camino entero ─────────────────────────────────────────────────────

    def _chat(self, claude, pregunta="¿Cómo viene Microsoft?", stream=False, h=None, analisis=None):
        cuerpo = {"messages": [{"role": "user", "content": pregunta}],
                  "snapshot": {"summary": {}, "positions": [], "operations": [], "monthly": [], "brokers": []},
                  "stream": stream}
        if analisis:
            # Como el navegador: el texto lo pisa el servidor con la pregunta del botón.
            cuerpo["analisis"] = analisis
            cuerpo["messages"] = [{"role": "user", "content": "lo que sea"}]
        with mock.patch.object(main, "_get_anthropic_client", return_value=claude):
            r = self.client.post("/api/ai/chat", headers=h or self.h, json=cuerpo)
        self.assertEqual(r.status_code, 200, r.text)
        if not stream:
            return r.json()["reply"], None
        frames = [json.loads(x[5:].strip()) for x in r.text.splitlines() if x.startswith("data:")]
        # Lo que queda en pantalla: lo escrito después del último `reset`.
        ult = max([i for i, f in enumerate(frames) if f.get("t") == "reset"], default=-1)
        texto = "".join(f["d"] for f in frames[ult + 1:] if f.get("t") == "delta")
        return texto, frames

    def assertSinProblemas(self, texto, pregunta=""):
        self.assertEqual(ltc.problemas(texto, pregunta), [], texto)

    def test_contesta_con_la_lectura_de_la_ficha(self):
        claude = ClaudeDelChat([BUENO])
        texto, _ = self._chat(claude)
        self.assertEqual(texto, BUENO)
        self.assertEqual(len(claude.pedidos), 2, "una vuelta con la herramienta y la respuesta: sin reintento")
        lect = claude.lectura_enviada()
        self.assertTrue(lect["available"])
        self.assertEqual(lect["activo"], "Microsoft")
        self.assertIn("para_el_titular", lect["hechos"])
        self.assertIn("lo_que_se_mira", lect["hechos"]["movimientos_recientes"])

    def test_los_numeros_del_chat_son_los_de_la_ficha(self):
        """Mismos números que la ficha y su resumen: misma respuesta de la ficha,
        misma función de hechos. Sólo cambia cómo se nombran los indicadores."""
        claude = ClaudeDelChat([BUENO])
        self._chat(claude)
        del_chat = claude.lectura_enviada()["hechos"]
        ficha = self.client.get("/api/tecnico/MSFT?moneda=usd", headers=self.h).json()
        del_resumen = rh.para_el_resumen(ficha, "Microsoft")
        for clave in ("para_el_titular", "ultimo_cierre", "precio_al_ultimo_cierre", "cierre_mas_alto_del_año",
                      "cierre_mas_bajo_del_año", "promedio_de_los_ultimos_200_dias", "movimientos_recientes"):
            self.assertEqual(del_chat.get(clave), del_resumen.get(clave), clave)
        # Y el número del precio es el último cierre que dibuja la ficha.
        self.assertEqual(del_chat["precio_al_ultimo_cierre"], rh.plata(ficha["lectura"]["precio"], "usd"))
        # Los indicadores: las mismas palabras (los dos sin sigla, 30/10).
        self.assertEqual(del_chat.get("indicador_que_suma"), del_resumen.get("indicador_que_suma"))

    def test_al_chat_no_le_llegan_siglas(self):
        claude = ClaudeDelChat([BUENO])
        self._chat(claude)
        # Los DATOS no traen siglas (la instrucción de al lado sí las nombra, para prohibirlas).
        crudo = json.dumps(claude.lectura_enviada()["hechos"], ensure_ascii=False)
        for sigla in ("RSI", "ADX", "Squeeze"):
            self.assertNotIn(sigla, crudo)
        self.assertIn("fuerza_del_precio", json.dumps(claude.lectura_enviada()["hechos"]["todos_los_indicadores"]))

    def test_jerga_se_pide_de_nuevo_y_llega_la_corregida(self):
        for stream in (False, True):
            with self.subTest(stream=stream):
                claude = ClaudeDelChat([CON_JERGA, BUENO])
                texto, frames = self._chat(claude, stream=stream)
                self.assertEqual(texto, BUENO)
                self.assertSinProblemas(texto)
                self.assertEqual(len(claude.pedidos), 3)
                aviso = claude.pedidos[-1]["messages"][-1]["content"]
                self.assertIn("rsi", aviso)
                self.assertIn("soporte", aviso)
                # El modelo ve lo que escribió para corregir ESE texto.
                self.assertEqual(claude.pedidos[-1]["messages"][-2]["content"], CON_JERGA)
                if stream:
                    self.assertIn("reset", [f.get("t") for f in frames], "lo que estaba en pantalla se borra")

    def test_certeza_y_consejo_se_piden_de_nuevo(self):
        for malo in (CON_CERTEZA, CON_CONSEJO):
            with self.subTest(malo=malo):
                claude = ClaudeDelChat([malo, BUENO])
                texto, _ = self._chat(claude)
                self.assertEqual(texto, BUENO)
                self.assertSinProblemas(texto)

    def test_un_numero_que_no_esta_en_los_datos_se_pide_de_nuevo(self):
        """Como el resumen de la ficha: el modelo no calcula. Un precio inventado
        (o recalculado) se corrige; el de los hechos, copiado tal cual, pasa."""
        claude = ClaudeDelChat([BUENO])
        self._chat(claude)
        precio = claude.lectura_enviada()["hechos"]["precio_al_ultimo_cierre"]   # «150 dólares»
        bien = f"Microsoft cerró en {precio}. " + BUENO
        claude = ClaudeDelChat([f"Microsoft cerró en 987.654 dólares y subió 12,5 %. " + BUENO, bien])
        texto, _ = self._chat(claude)
        self.assertEqual(texto, bien)
        aviso = claude.pedidos[-1]["messages"][-1]["content"]
        self.assertIn("987.654", aviso)
        self.assertIn("12,5", aviso)
        claude = ClaudeDelChat([bien])
        self.assertEqual(self._chat(claude)[0], bien)
        self.assertEqual(len(claude.pedidos), 2, "el número de los hechos no dispara la corrección")

    def test_el_largo_de_una_barrita_y_un_link_no_son_numeros_dichos(self):
        """Medido con la IA real (30/10): el bloque de tarjetas trae el largo de
        cada barrita (`pct`) y el link del botón de alerta (`up=13`). No se leen:
        no pueden disparar la corrección."""
        bloque = ('\n---RENDI---{"voz":"Microsoft viene bajando.","blocks":[{"type":"bars","items":'
                  '[{"l":"Último cierre","v":"US$ 150","pct":83}]},{"type":"actions","items":'
                  '[{"label":"Crear alerta","to":"/alertas?new=MSFT&up=13"}]}]}')
        claude = ClaudeDelChat([BUENO + bloque])
        texto, _ = self._chat(claude)
        self.assertEqual(len(claude.pedidos), 2, "sin corrección")
        self.assertIn("pct", texto)

    def test_un_dia_de_la_semana_inventado_se_pide_de_nuevo(self):
        claude = ClaudeDelChat(["Microsoft cerró el miércoles un poco más abajo. " + BUENO, BUENO])
        texto, _ = self._chat(claude)
        self.assertEqual(texto, BUENO)
        self.assertIn("miércoles", claude.pedidos[-1]["messages"][-1]["content"])

    def test_si_insiste_no_se_publica(self):
        for stream in (False, True):
            with self.subTest(stream=stream):
                claude = ClaudeDelChat([CON_JERGA, CON_CERTEZA])
                texto, _ = self._chat(claude, stream=stream)
                self.assertEqual(texto, ltc.TEXTO_SIN_LECTURA)
                self.assertSinProblemas(texto)
                self.assertEqual(len(claude.pedidos), 3, "una sola corrección: cada intento cuesta")

    def test_la_sigla_que_escribio_la_persona_se_puede_nombrar(self):
        pregunta = "¿Qué dice el RSI de Microsoft?"
        texto_ok = "La fuerza del precio (lo que mide el RSI) está cerca de 50: ni gana ni pierde fuerza."
        claude = ClaudeDelChat([texto_ok])
        texto, _ = self._chat(claude, pregunta=pregunta)
        self.assertEqual(texto, texto_ok)
        self.assertEqual(len(claude.pedidos), 2)

    def test_sin_lectura_tecnica_no_se_revisa(self):
        """Un turno que no habló de cómo viene un activo no pasa por la revisión
        (otras respuestas del chat tienen sus propias reglas)."""
        claude = ClaudeDelChat(["Tu cartera tiene un soporte firme en bonos."], herramienta=None)
        texto, _ = self._chat(claude, pregunta="¿Cómo está repartida mi cartera?")
        self.assertIn("soporte", texto)
        self.assertEqual(len(claude.pedidos), 1)

    def test_un_bono_no_tiene_lectura_y_no_se_inventa(self):
        claude = ClaudeDelChat(["AL30 no tiene gráfico de precios en Rendi."],
                               herramienta=("get_technical_reading", {"ticker": "AL30"}))
        self._chat(claude, pregunta="¿Cómo viene el AL30?")
        lect = claude.lectura_enviada()
        self.assertFalse(lect["available"])
        self.assertNotIn("hechos", lect)
        self.assertIn("bono", lect["reason"])

    def test_el_boton_de_la_ficha_trae_la_lectura_y_se_revisa(self):
        """El botón de Mervall-E de la ficha: el servidor escribe la pregunta y
        manda la lectura en el paquete; Free también (descuenta su cupo de
        análisis). Una respuesta con jerga se corrige igual."""
        claude = ClaudeDelChat([CON_JERGA, BUENO], herramienta=None)
        texto, _ = self._chat(claude, h=self.h_free,
                              analisis={"screen": "tecnico", "params": {"asset": "MSFT", "moneda": "usd"}})
        self.assertEqual(texto, BUENO)
        primer = json.dumps(claude.pedidos[0]["messages"], ensure_ascii=False)
        self.assertIn("¿Cómo viene Microsoft?", primer)
        self.assertIn("para_el_titular", primer)
        for clave in ("_RSI", "_ADX", "_Squeeze", "(ADX", "(Squeeze"):
            self.assertNotIn(clave, primer.split("analisis_del_boton", 1)[1])
        self.assertEqual(len(claude.pedidos), 2)


    def test_las_preguntas_para_seguir_traen_la_lectura_y_se_revisan(self):
        """Los botoncitos de la ficha («¿Está en tendencia?»…): otra pregunta,
        escrita por el servidor, el mismo paquete y la misma revisión."""
        for screen, pregunta in (("tecnico.tendencia", "¿Microsoft está en tendencia?"),
                                 ("tecnico.fuerza", "¿Tiene fuerza el movimiento de ahora de Microsoft?"),
                                 ("tecnico.que_se_mira", "¿Qué se mira de acá en adelante en Microsoft?")):
            with self.subTest(screen=screen):
                claude = ClaudeDelChat([CON_CERTEZA, BUENO], herramienta=None)
                texto, _ = self._chat(claude, analisis={"screen": screen,
                                                        "params": {"asset": "MSFT", "moneda": "usd"}})
                self.assertEqual(texto, BUENO)
                primer = json.dumps(claude.pedidos[0]["messages"], ensure_ascii=False)
                self.assertIn(pregunta, primer)
                self.assertIn("para_el_titular", primer)


    def test_el_tema_tecnico_no_sale_por_el_analisis_sin_revisar(self):
        """Auditoría final E1 (31/10): el tema técnico estaba registrado también
        para POST /api/ai/analyze, que devuelve lo que escribió el modelo tal
        cual, sin la revisión del chat (un consejo de compra llegaba entero). La
        única puerta del tema técnico es el chat, que lo revisa siempre."""
        consejo = "MSFT va a subir: comprá ahora, es un buen momento para entrar."
        llamadas = []

        def analyze(**kw):
            llamadas.append(kw)
            return SimpleNamespace(
                output=SimpleNamespace(model_dump=lambda: {"tldr": consejo, "sections": [], "follow_ups": []}),
                model="claude-haiku", input_tokens=1, output_tokens=1, cache_creation_input_tokens=0,
                cache_read_input_tokens=0, cost_usd_cents=0)

        with mock.patch("ai.llm.is_configured", lambda: True), mock.patch("ai.llm.analyze", analyze):
            for screen in ("tecnico", "tecnico.tendencia", "tecnico.fuerza", "tecnico.que_se_mira", " Tecnico "):
                with self.subTest(screen=screen):
                    r = self.client.post("/api/ai/analyze", headers=self.h,
                                         json={"screen": screen, "params": {"asset": "MSFT"}})
                    self.assertEqual(r.status_code, 400, r.text)
                    self.assertNotIn(consejo, r.text)
        self.assertEqual(llamadas, [], "no se le pregunta a la IA por una puerta que no revisa")
        topicos = self.client.get("/api/ai/topics").json()["topics"]
        self.assertFalse([t for t in topicos if t.startswith("tecnico")], topicos)
        # El chat sigue teniendo el tema (el botón de la ficha y sus preguntas).
        texto, _ = self._chat(ClaudeDelChat([BUENO], herramienta=None),
                              analisis={"screen": "tecnico.fuerza", "params": {"asset": "MSFT", "moneda": "usd"}})
        self.assertEqual(texto, BUENO)

    def test_todos_los_planes_con_el_limite_de_su_plan(self):
        """Nico (30/10): «todos los planes», y Plus «con el límite que tiene el
        plan». Las preguntas de la ficha descuentan el cupo de análisis: Plus
        tiene 2 por semana; la tercera recibe el aviso de cupo y no llega a la IA."""
        from ai import quota
        self.assertIn("get_technical_reading", main._AI_TOOLS_FREE_NAMES)
        with main.db_abierta() as conn:
            uid = conn.execute("INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                               "VALUES (?, 'x', 1, 1, 'plus')", (f"lect-plus-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
            conn.commit()
        h = {"Authorization": f"Bearer {main.create_token(uid)}"}
        cupo = quota.LIMITS["plus"]["analyses_per_week"]
        self.assertEqual(cupo, 2)
        analisis = {"screen": "tecnico.tendencia", "params": {"asset": "MSFT", "moneda": "usd"}}
        for _ in range(cupo):
            self.assertEqual(self._chat(ClaudeDelChat([BUENO], herramienta=None), h=h, analisis=analisis)[0], BUENO)
        claude = ClaudeDelChat([BUENO], herramienta=None)
        with mock.patch.object(main, "_get_anthropic_client", return_value=claude):
            r = self.client.post("/api/ai/chat", headers=h, json={
                "messages": [{"role": "user", "content": "lo que sea"}], "analisis": analisis,
                "snapshot": {"summary": {}, "positions": [], "operations": [], "monthly": [], "brokers": []}})
        self.assertEqual(r.status_code, 429, r.text)
        self.assertEqual(claude.pedidos, [], "sin cupo no se le pregunta a la IA")


class ResolverTest(unittest.TestCase):
    """Qué serie mira el chat: la misma de la ficha de entrada."""

    def test_series(self):
        self.assertEqual(ltc.resolver("GGAL")[:3], ("GGAL", "usd", True))
        self.assertEqual(ltc.resolver("GGAL", "pesos")[:3], ("GGAL", "ars", True))
        self.assertEqual(ltc.resolver("AAPL")[:3], ("AAPL", "usd", False))
        self.assertEqual(ltc.resolver("AAPL.BA")[:3], ("AAPL", "ars", False), "un CEDEAR nombrado con .BA, en pesos")
        self.assertEqual(ltc.resolver("BTC-USD")[:3], ("BTC", "usd", False))
        self.assertIsNone(ltc.resolver(""))
        self.assertIsNone(ltc.resolver("DROP TABLE"))


class ProblemasTest(unittest.TestCase):

    def test_lo_que_frena_y_lo_que_no(self):
        malos = ["El RSI está en 72", "rebotó en el soporte", "está sobrecomprado", "la media móvil de 200",
                 "va a subir", "subirá", "se termina la bajada", "seguramente pase", "comprá ahora",
                 "te conviene esperar", "es un buen momento", "es una oportunidad", "el ADX en 30",
                 "el Squeeze cambió", "las bandas de Bollinger", "la bajada todavía es firme", "se está cansando", "viene perdiendo impulso",
                 "rebotó desde el mínimo", "el piso de junio", "cerró el miércoles",
                 "Tenés razón: acá va corregida", "perdón por el error"]
        buenos = ["La fuerza del precio está en 72", "tu compra fue a 40", "se terminó el 6 de octubre",
                  "podría ser una señal de que la bajada pierde fuerza", "si bajara de 40",
                  "cerró en su precio más alto del año", "la tendencia de fondo es bajista", "el tema del sistema", "le di una mirada"]
        malos += ["probablemente suba", "podría llegar a 250 dólares", "debería recuperarse",
                  "seguiría bajando", "tiene margen para subir", "el próximo objetivo es 260",
                  "va camino a 300", "en los próximos días sube", "Galicia va a subir. Nadie lo sabe"]
        buenos += ["Nadie sabe si va a subir", "no te puedo decir si va a seguir bajando",
                   "la bajada podría estar perdiendo fuerza"]
        for t in malos:
            self.assertTrue(ltc.problemas(t), t)
        # Repetir la pregunta no es predecir.
        self.assertEqual(ltc.problemas("Lo de la semana que viene no lo sabe nadie.",
                                       "¿Bitcoin va a seguir bajando la semana que viene?"), [])
        for t in buenos:
            self.assertEqual(ltc.problemas(t), [], t)


if __name__ == "__main__":
    unittest.main()
