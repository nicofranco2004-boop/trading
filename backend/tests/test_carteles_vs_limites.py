"""Lo que el CARTEL de upgrade promete tiene que ser lo que el plan DA.

Mismo bug que `test_mails_vs_limites.py`, en la superficie que más gente ve:
los 403/429 de `main.py` traen `upgrade.benefits`, la lista que el frontend
muestra cuando alguien choca con un tope (UpgradePromoCard, UpgradeModal). Eran
diez listas escritas a mano y mentían:

  · "10× más análisis IA (60/sem vs 6/sem)" también a un Free, que tiene 1 por
    semana (son 60×), en cinco carteles;
  · "Diagnóstico completo + 4 detectores de comportamiento" para vender Plus:
    el Plus ve 6, y el diagnóstico completo ya lo ve el Free;
  · "Distribución por activo" y "AI Hub (próximamente)": la primera ya es de
    todos y la segunda no existe;
  · el 403 de brokers le decía "El plan Free permite 1 broker" también al Plus
    que llegaba a 3;
  · la voz mostraba la lista del Plus aunque el cartel ofreciera Pro.

Y el 15/10 (`git revert 78f43739`: Plus con 2 análisis, los 12 detectores y
alertas sin tope) todo "60/sem vs 6/sem" pasaba a ser falso y "comportamiento
completo" dejaba de separar al Pro del Plus.

Ahora cada cartel lo arma `billing/plan_textos.cartel()` con los límites que el
backend aplica, y este archivo compara lo que el cartel DICE —el JSON que le
llega al navegador, no la función que lo arma— contra el número que BLOQUEA.

Tres capas, como el de los mails:
  1. Por el camino de producción: cada endpoint real, con una cuenta en el
     estado que dispara el cartel (Free con su broker, cupo agotado, etc.).
  2. Cada renglón, contra su límite: el múltiplo tiene que ser exacto, el "vs"
     tiene que ser el plan de origen, lo que el destino no mejora no se nombra,
     y un renglón que este archivo no sabe leer es un renglón sin vigilar.
  3. Con límites INVENTADOS (patch.dict sobre las dos tablas): si quedara un
     número escrito a mano, el cartel lo seguiría diciendo y acá se vería.

Ningún número de plan está escrito en este archivo: el esperado siempre se lee
de LIMITS / PLAN_LIMITS. Los únicos números a mano son los inventados de la capa
3, que no son de ningún plan a propósito.

Corre con: cd backend && python3 -m pytest tests/test_carteles_vs_limites.py
"""
import os
import re
import sys
import unittest
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main  # noqa: E402
from ai import tts  # noqa: E402
from ai.plan import PLAN_LIMITS, PLANES_EN_VENTA  # noqa: E402
from ai.prompts import is_descriptive_tier  # noqa: E402
from ai.quota import LIMITS  # noqa: E402
from billing import plan_textos  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

FREE = "free"


# ─── Leer un renglón como lo lee la persona ─────────────────────────────────

def _cupo(clave: str, plan: str):
    """El límite que respalda cada clave, leído de la tabla en el momento."""
    if clave == "analisis":
        return LIMITS[plan]["analyses_per_week"]
    if clave == "chat":
        return LIMITS[plan]["chat_per_week"]
    if clave == "diagnostico":
        return LIMITS[plan]["diag_dismiss_per_week"]
    if clave == "voz":
        return LIMITS[plan]["listens_per_week"]
    if clave == "brokers":
        return PLAN_LIMITS[plan]["brokers_max"]
    if clave == "detectores":
        return PLAN_LIMITS[plan]["behavioral_tags_visible"]
    if clave == "alertas":
        return PLAN_LIMITS[plan]["alerts_max"]
    raise KeyError(clave)


def _accede(feature: str, plan: str) -> bool:
    return bool(PLAN_LIMITS[plan]["can_access"].get(feature))


def _gana(feature: str, origen: str, destino: str) -> bool:
    return _accede(feature, destino) and not _accede(feature, origen)


def _interpreta(origen: str, destino: str) -> bool:
    return is_descriptive_tier(origen) and not is_descriptive_tier(destino)


def _num(v):
    return None if v in (None, "") else int(v)


# Cada forma que puede tomar un renglón: (clave, patrón). El orden importa
# poco: los patrones no se pisan entre sí.
_FORMAS = (
    ("analisis", r"^(?:(\d+)× más|Más) análisis IA \((\d+)/sem vs (\d+)/sem\)$"),
    ("chat", r"^(?:(\d+)× más|Más) consultas a Rendi AI \((\d+)/sem vs (\d+)/sem\)$"),
    ("chat_libre_cupo", r"^Chat libre con Rendi AI \((\d+) consultas/sem vs (\d+) guiadas?\)$"),
    ("chat_cupo", r"^(\d+) consultas por semana sobre lo que quieras "
                  r"\(en (\w+): (\d+)(?:, eligiendo entre (\d+) preguntas guiadas)?\)$"),
    ("brokers", r"^(?:Hasta (\d+) brokers?|Brokers ilimitados) \(vs (\d+) en (\w+)\)$"),
    ("detectores", r"^(?:(\d+) detector(?:es)? de comportamiento|"
                   r"Todos los detectores de comportamiento) \(vs (\d+) en (\w+)\)$"),
    ("alertas", r"^(?:Hasta (\d+) alertas?|Alertas sin tope)(, también de % sobre tu cartera)?"
                r"(?: \(vs (\d+) en (\w+)(, sólo de precio)?\))?$"),
    ("diagnostico", r"^Personalizá tu diagnóstico (?:sin límite|(\d+) veces? por semana) "
                    r"\(en (\w+), (\d+) veces? por semana\)$"),
    ("voz_fichas", r"^Más respuestas habladas: cada audio usa 1 de las (\d+) consultas "
                   r"por semana \((?:en (\w+), (\d+) audios? por semana|vs (\d+) en (\w+))\)$"),
    ("voz_propia", r"^Hasta (\d+) respuestas? habladas? por semana(?: \(en (\w+), (\d+)\))?$"),
    ("followups", r"^Follow-ups: repreguntá sobre cualquier análisis$"),
    ("reportes", r"^Reportes históricos completos \(todos los meses\)$"),
    ("export", r"^Export CSV consolidado para tu contador$"),
    ("reportes_export", r"^Reportes históricos \+ Export CSV$"),
    ("chat_libre", r"^Chat libre con Rendi AI: preguntá lo que quieras$"),
    ("causalidad", r"^Respuestas con causalidad y (?:comparaciones|memoria persistente)$"),
)

# Qué renglón contesta cada motivo. El primero del cartel tiene que ser éste:
# si no, el cartel vende otra cosa que la que la persona fue a buscar.
_CONTESTA = {
    "brokers": {"brokers"},
    "export": {"export", "reportes_export"},
    "followups": {"followups"},
    "analisis": {"analisis"},
    "chat": {"chat", "chat_libre_cupo"},
    "diagnostico": {"diagnostico"},
    "chat_libre": {"chat_libre"},
    "voz": {"voz_fichas", "voz_propia"},
}

# Lo que se prometió y no es cierto para NINGÚN plan. Cada uno con su porqué.
_NO_SE_PROMETE = {
    "Distribución por activo": "`insights.distribucion_activo` no lo aplica ninguna "
                               "pantalla: la distribución se abrió para todos",
    "observaciones": "el tope de puntos del diagnóstico (`insights_diagnostic_visible`) "
                     "no lo aplica ninguna pantalla",
    "Diagnóstico completo": "todos ven el diagnóstico entero; lo que se limita es "
                            "personalizarlo (`diag_dismiss_per_week`)",
    "AI Hub": "no existe: es roadmap, y el roadmap no va mezclado con lo que se vende",
    "análisis de comportamiento": "son DETECTORES; «análisis» es el cupo de IA",
}


class _Comparador(unittest.TestCase):
    """Las comparaciones, compartidas por las tres capas."""

    def _cartel_dice_lo_que_da(self, upgrade: dict, motivo: str, contexto: str,
                               usage: dict = None):
        """`upgrade` es el objeto `upgrade` del 403/429, tal cual llegó."""
        origen, destino = upgrade["current_tier"], upgrade["target_tier"]
        renglones = upgrade.get("benefits")
        contexto = f"{contexto} ({origen}→{destino})"
        # Contra el falso verde: un cartel vacío pasaría todo lo de abajo.
        self.assertTrue(renglones, f"{contexto}: el cartel no trae beneficios")
        self.assertLessEqual(len(renglones), plan_textos.TOPE_DEL_CARTEL, contexto)
        self.assertEqual(len(renglones), len(set(renglones)), f"{contexto}: repite renglones")
        claves = []
        for renglon in renglones:
            with self.subTest(contexto=contexto, renglon=renglon):
                claves.append(self._renglon_es_cierto(renglon, origen, destino,
                                                      contexto, usage))
        self.assertIn(
            claves[0], _CONTESTA[motivo],
            f"{contexto}: el primer renglón («{renglones[0]}») no contesta el tope "
            f"que se tocó ({motivo})")
        return claves

    def _origen_tiene(self, clave, origen, usage):
        """Lo que el origen tiene: el cupo del `usage` si vino (la persona puede
        tener uno propio, ver plan_textos._DEL_USO), si no la tabla."""
        campo = {"analisis": "analyses_limit", "chat": "chat_limit",
                 "diagnostico": "diag_dismiss_limit", "voz": "listens_limit"}.get(clave)
        if usage and campo in usage and usage.get("tier") == origen:
            return usage[campo]
        return _cupo(clave, origen)

    def _renglon_es_cierto(self, renglon, origen, destino, contexto, usage):
        # Primero lo que MIENTE, que es lo que importa leer si esto se pone rojo.
        for frase, porque in _NO_SE_PROMETE.items():
            self.assertNotIn(frase, renglon, f"{contexto}: «{renglon}» — {porque}")
        for clave, patron in _FORMAS:
            m = re.match(patron, renglon)
            if m:
                self._comparar(clave, m, origen, destino, contexto, usage)
                return clave
        self.fail(f"{contexto}: «{renglon}» no tiene una forma conocida — un renglón "
                  f"que este test no sabe leer es un número sin vigilar. Sumalo a "
                  f"_FORMAS con su comparación.")

    def _comparar(self, clave, m, origen, destino, contexto, usage):
        dice = f"{contexto}: «{m.group(0)}»"
        nombre_origen = plan_textos.nombre(origen)
        if clave in ("analisis", "chat"):
            veces, a, b = _num(m.group(1)), int(m.group(2)), int(m.group(3))
            self.assertEqual(a, _cupo(clave, destino), f"{dice}: el {destino} da {_cupo(clave, destino)}")
            self.assertEqual(b, self._origen_tiene(clave, origen, usage),
                             f"{dice}: el {origen} tiene {self._origen_tiene(clave, origen, usage)}")
            self.assertGreater(a, b, f"{dice}: no es más")
            if veces is None:
                self.assertTrue(b == 0 or a % b, f"{dice}: {a}/{b} es exacto y no dice el múltiplo")
            else:
                self.assertEqual(veces * b, a, f"{dice}: el múltiplo real es {a / b:g}×")
            if clave == "chat":
                self.assertFalse(_interpreta(origen, destino),
                                 f"{dice}: el destino tiene chat LIBRE y no lo dice")
        elif clave == "chat_libre_cupo":
            self.assertTrue(_interpreta(origen, destino), f"{dice}: el {destino} no tiene chat libre")
            self.assertEqual(int(m.group(1)), _cupo("chat", destino), dice)
            self.assertEqual(int(m.group(2)), self._origen_tiene("chat", origen, usage), dice)
        elif clave == "chat_cupo":
            self.assertTrue(_interpreta(origen, destino), f"{dice}: el {destino} no tiene chat libre")
            self.assertEqual(int(m.group(1)), _cupo("chat", destino), dice)
            self.assertEqual(m.group(2), nombre_origen, dice)
            self.assertEqual(int(m.group(3)), self._origen_tiene("chat", origen, usage), dice)
            if m.group(4):
                self.assertEqual(int(m.group(4)), len(main._FREE_QUESTIONS_WHITELIST),
                                 f"{dice}: no son las preguntas guiadas que acepta el chat")
        elif clave in ("brokers", "detectores"):
            a, b, de = _num(m.group(1)), int(m.group(2)), m.group(3)
            self.assertEqual(a, _cupo(clave, destino), f"{dice}: el {destino} da {_cupo(clave, destino)}")
            self.assertEqual(b, _cupo(clave, origen), f"{dice}: el {origen} tiene {_cupo(clave, origen)}")
            self.assertEqual(de, nombre_origen, dice)
            self.assertTrue(a is None or a > b, f"{dice}: no es más")
        elif clave == "alertas":
            a, pct, b, de, solo_precio = (_num(m.group(1)), m.group(2), _num(m.group(3)),
                                          m.group(4), m.group(5))
            self.assertEqual(a, _cupo("alertas", destino), dice)
            self.assertEqual(bool(pct), _gana("alerts.pct_move", origen, destino), dice)
            if b is not None:
                self.assertEqual(b, _cupo("alertas", origen), dice)
                self.assertEqual(de, nombre_origen, dice)
                self.assertEqual(bool(solo_precio), not _accede("alerts.pct_move", origen), dice)
        elif clave == "diagnostico":
            a, de, b = _num(m.group(1)), m.group(2), int(m.group(3))
            self.assertEqual(a, _cupo("diagnostico", destino),
                             f"{dice}: el {destino} tiene {_cupo('diagnostico', destino)}")
            self.assertEqual(de, nombre_origen, dice)
            self.assertEqual(b, self._origen_tiene("diagnostico", origen, usage), dice)
        elif clave == "voz_fichas":
            self.assertIsNone(_cupo("voz", destino),
                              f"{dice}: el {destino} tiene cupo propio de audios")
            self.assertEqual(int(m.group(1)), _cupo("chat", destino),
                             f"{dice}: el {destino} tiene {_cupo('chat', destino)} consultas")
            if m.group(2):
                self.assertEqual(m.group(2), nombre_origen, dice)
                self.assertEqual(int(m.group(3)), self._origen_tiene("voz", origen, usage), dice)
            else:
                self.assertEqual(int(m.group(4)), self._origen_tiene("chat", origen, usage), dice)
                self.assertEqual(m.group(5), nombre_origen, dice)
        elif clave == "voz_propia":
            self.assertEqual(int(m.group(1)), _cupo("voz", destino), dice)
        elif clave == "followups":
            self.assertTrue(_gana("ai.followup", origen, destino), f"{dice}: el {origen} ya los tiene")
        elif clave == "reportes":
            self.assertTrue(_gana("reportes.historicos", origen, destino), dice)
        elif clave == "export":
            self.assertTrue(_gana("export.csv", origen, destino), dice)
        elif clave == "reportes_export":
            self.assertTrue(_gana("reportes.historicos", origen, destino)
                            and _gana("export.csv", origen, destino), dice)
        elif clave in ("chat_libre", "causalidad"):
            self.assertTrue(_interpreta(origen, destino),
                            f"{dice}: el {origen} ya lo tiene o el {destino} no")
        else:  # pragma: no cover — _FORMAS y esto tienen que ir juntos
            self.fail(f"{dice}: clave {clave} sin comparación")


# ─── Capa 1: por el camino de producción ────────────────────────────────────

def _mk_user(tier: str) -> tuple:
    conn = main.get_db()
    try:
        uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, name, tier, requires_plan) "
            "VALUES (?, 'x', 1, 'Ana', ?, 0)",
            (f"cartel-{uuid.uuid4().hex[:10]}@rendi.test", tier)).lastrowid
        conn.commit()
    finally:
        conn.close()
    return uid, {"Authorization": f"Bearer {main.create_token(uid)}"}


def _agotar(uid: int, columna: str, cuanto: int):
    """Deja el contador de la semana en `cuanto`, con el MISMO reloj que usa
    `quota` (date.today(), no utcnow: de 21 a 24 son días distintos)."""
    conn = main.get_db()
    try:
        conn.execute(
            f"INSERT INTO ai_usage_daily (user_id, date, {columna}) VALUES (?, ?, ?) "
            f"ON CONFLICT(user_id, date) DO UPDATE SET {columna} = excluded.{columna}",
            (uid, date.today().isoformat(), cuanto))
        conn.commit()
    finally:
        conn.close()


def _brokers(uid: int, cuantos: int):
    conn = main.get_db()
    try:
        for i in range(cuantos):
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?, ?, 'USD')",
                         (uid, f"Broker {i} {uuid.uuid4().hex[:4]}"))
        conn.commit()
    finally:
        conn.close()


_CHAT_VACIO = {"summary": {}, "positions": [], "operations": [], "monthly": [], "brokers": []}
_GUIADA = main._FREE_QUESTIONS_WHITELIST[0]


class _PorElCamino(_Comparador):
    """Cada método `_cartel_*` pone una cuenta en el estado que dispara el
    cartel, le pega al endpoint real y devuelve el `detail` que llega."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        # Lo que el cartel NO mide y en producción sale de afuera (la API de
        # Anthropic, la de OpenAI, los fundamentales de Yahoo): se simula que
        # está configurado. Los topes, los contadores y los carteles son los
        # de verdad.
        for p in (patch("ai.llm.is_configured", return_value=True),
                  patch.object(main, "_get_anthropic_client", return_value=MagicMock()),
                  patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-no-se-usa"})):
            p.start()
            self.addCleanup(p.stop)

    def _esperar(self, r, codigo):
        self.assertEqual(r.status_code, codigo, r.text[:600])
        return r.json()["detail"]

    def _cartel_brokers(self, tier):
        uid, h = _mk_user(tier)
        _brokers(uid, _cupo("brokers", tier))
        r = self.client.post("/api/brokers", json={"name": "Uno más", "currency": "USD"},
                             headers=h)
        return self._esperar(r, 403)

    def _cartel_export(self, tier):
        uid, h = _mk_user(tier)
        return self._esperar(self.client.get("/api/export/operations.csv", headers=h), 403)

    def _cartel_followups(self, tier):
        uid, h = _mk_user(tier)
        r = self.client.post("/api/ai/analyze", headers=h, json={
            "screen": "dashboard", "params": {}, "followup_question": "¿Y por qué?"})
        return self._esperar(r, 403)

    def _cartel_analisis(self, tier):
        uid, h = _mk_user(tier)
        _agotar(uid, "analyses_count", _cupo("analisis", tier))
        r = self.client.post("/api/ai/analyze", headers=h,
                             json={"screen": "dashboard", "params": {}})
        return self._esperar(r, 429)

    def _cartel_fundamentales(self, tier):
        uid, h = _mk_user(tier)
        _agotar(uid, "analyses_count", _cupo("analisis", tier))
        with patch.object(main, "_build_fundamentals_response",
                          return_value={"available": True, "ticker": "AAPL"}), \
             patch.object(main, "_build_fundamentals_ai_packet", return_value={"t": "AAPL"}):
            r = self.client.post("/api/fundamentals/ai-summary", headers=h,
                                 json={"ticker": "AAPL"})
        return self._esperar(r, 429)

    def _cartel_chat(self, tier):
        uid, h = _mk_user(tier)
        _agotar(uid, "chat_count", _cupo("chat", tier))
        r = self.client.post("/api/ai/chat", headers=h, json={
            "messages": [{"role": "user", "content": _GUIADA}], "snapshot": _CHAT_VACIO})
        return self._esperar(r, 429)

    def _cartel_boton_analizar(self, tier):
        """El botón ✦ del chat: se cobra del cupo de ANÁLISIS."""
        uid, h = _mk_user(tier)
        _agotar(uid, "analyses_count", _cupo("analisis", tier))
        r = self.client.post("/api/ai/chat", headers=h, json={
            "messages": [{"role": "user", "content": "✦"}], "snapshot": _CHAT_VACIO,
            "analisis": {"screen": "dashboard", "params": {}}})
        return self._esperar(r, 429)

    def _cartel_diagnostico(self, tier):
        uid, h = _mk_user(tier)
        _agotar(uid, "diag_dismiss_count", _cupo("diagnostico", tier))
        return self._esperar(self.client.post("/api/diagnostics/dismiss", headers=h), 429)

    def _cartel_chat_libre(self, tier):
        uid, h = _mk_user(tier)
        r = self.client.post("/api/ai/chat", headers=h, json={
            "messages": [{"role": "user", "content": "Contame un chiste"}],
            "snapshot": _CHAT_VACIO})
        return self._esperar(r, 403)

    def _cartel_voz(self, tier):
        uid, h = _mk_user(tier)
        propio = _cupo("voz", tier)
        if propio is None:          # paga cada audio con una consulta
            _agotar(uid, "chat_count", _cupo("chat", tier))
        else:
            _agotar(uid, "listen_count", propio)
        texto = f"Tu cartera viene bien este año. Referencia {uuid.uuid4().hex[:8]}."
        r = self.client.post("/api/ai/voz", headers=h,
                             json={"text": texto, "sig": tts.sign(texto)})
        return self._esperar(r, 429)


class PorElCaminoDeProduccion(_PorElCamino):

    def test_el_broker_de_mas_de_un_free_y_de_un_plus(self):
        for tier in ("free", "plus"):
            with self.subTest(tier=tier):
                d = self._cartel_brokers(tier)
                self._cartel_dice_lo_que_da(d["upgrade"], "brokers", "403 brokers")
                # El título del modal: decía "El plan Free permite 1 broker"
                # también al Plus que llegaba a 3.
                m = re.match(r"El plan (\w+) permite (\d+) brokers?\.", d["error"])
                self.assertTrue(m, d["error"])
                self.assertEqual(m.group(1), plan_textos.nombre(tier))
                self.assertEqual(int(m.group(2)), _cupo("brokers", tier))
                self.assertTrue(d["upgrade"]["available"],
                                f"el Pro le da más brokers al {tier}: el upgrade existe")

    def test_exportar_siendo_free(self):
        d = self._cartel_export(FREE)
        self._cartel_dice_lo_que_da(d["upgrade"], "export", "403 export")
        con_export = [plan_textos.nombre(p) for p in PLANES_EN_VENTA if _accede("export.csv", p)]
        for nombre in con_export:
            self.assertIn(nombre, d["error"])
        for p in PLANES_EN_VENTA:
            if not _accede("export.csv", p):
                self.assertNotIn(plan_textos.nombre(p), d["error"])

    def test_el_follow_up_de_un_free_y_de_un_plus(self):
        for tier in ("free", "plus"):
            with self.subTest(tier=tier):
                d = self._cartel_followups(tier)
                self._cartel_dice_lo_que_da(d["upgrade"], "followups", "403 follow-up",
                                            usage=d.get("usage"))

    def test_el_cupo_de_analisis_agotado_en_los_dos_endpoints(self):
        """/api/ai/analyze y el resumen de fundamentales comparten el 429."""
        for tier in ("free", "plus"):
            for nombre, pedir in (("analyze", self._cartel_analisis),
                                  ("fundamentales", self._cartel_fundamentales)):
                with self.subTest(tier=tier, endpoint=nombre):
                    d = pedir(tier)
                    self._cartel_dice_lo_que_da(d["upgrade"], "analisis", f"429 {nombre}",
                                                usage=d["usage"])
                    # "Llegaste al límite del plan X (N análisis…)" y el remate.
                    self.assertIn(f"plan {plan_textos.nombre(tier)} "
                                  f"({_cupo('analisis', tier)} análisis", d["error"])
                    self._remate_de_analisis(d["error"], tier)

    def _remate_de_analisis(self, texto, tier):
        m = re.search(r"Para (?:(\d+)× más análisis|más análisis \((\d+) por semana\))", texto)
        self.assertTrue(m, f"no dice cuánto más da el Pro: {texto}")
        a, b = _cupo("analisis", "pro"), _cupo("analisis", tier)
        if m.group(1):
            self.assertEqual(int(m.group(1)) * b, a, f"«{m.group(0)}»: el real es {a / b:g}×")
        else:
            self.assertEqual(int(m.group(2)), a)
            self.assertTrue(a % b, "el múltiplo es exacto y no lo dice")

    def test_el_cupo_de_chat_agotado(self):
        for tier in ("free", "plus"):
            with self.subTest(tier=tier):
                d = self._cartel_chat(tier)
                self.assertEqual(d["kind"], "chat")
                self._cartel_dice_lo_que_da(d["upgrade"], "chat", "429 chat", usage=d["usage"])

    def test_el_boton_analizar_del_chat_habla_de_analisis(self):
        """Antes el primer renglón era el chat aunque lo agotado fueran los
        análisis del botón ✦."""
        for tier in ("free", "plus"):
            with self.subTest(tier=tier):
                d = self._cartel_boton_analizar(tier)
                self.assertEqual(d["kind"], "analyses")
                self._cartel_dice_lo_que_da(d["upgrade"], "analisis", "429 botón ✦",
                                            usage=d["usage"])

    def test_personalizar_el_diagnostico_de_mas(self):
        d = self._cartel_diagnostico(FREE)
        self._cartel_dice_lo_que_da(d["upgrade"], "diagnostico", "429 diagnóstico",
                                    usage=d["usage"])
        destino = d["upgrade"]["target_tier"]
        tope = _cupo("diagnostico", destino)
        esperado = ("descartá sin límite" if tope is None
                    else f"descartá hasta {tope} ve")
        self.assertIn(esperado, d["message"])
        self.assertIn(f"pasate a {plan_textos.nombre(destino)}", d["message"])

    def test_el_chat_libre_de_un_free_y_de_un_plus(self):
        for tier in ("free", "plus"):
            with self.subTest(tier=tier):
                d = self._cartel_chat_libre(tier)
                self.assertEqual(d["error"], "free_chat_not_allowed")
                self._cartel_dice_lo_que_da(d["upgrade"], "chat_libre", "403 chat libre")

    def test_la_voz_del_free_ofrece_lo_que_da_el_plus(self):
        d = self._cartel_voz(FREE)
        self.assertEqual(d["error"], "voz_quota_exceeded")
        self._cartel_dice_lo_que_da(d["upgrade"], "voz", "429 voz", usage=d["usage"])

    def test_la_voz_del_que_paga_con_consultas_es_el_cartel_del_chat(self):
        """Sin cupo propio de audios, quedarse sin audio ES quedarse sin
        consultas: el cartel es el del chat (y del plan que se ofrece, no el
        del Plus a secas)."""
        d = self._cartel_voz("plus")
        self.assertEqual(d["error"], "chat_quota_exceeded")
        self._cartel_dice_lo_que_da(d["upgrade"], "chat", "429 voz de un Plus",
                                    usage=d["usage"])


class LosPlanesQueVeLaPantalla(_PorElCamino):
    """`/api/plan/features` manda los topes de los planes en venta para que la
    pantalla de Comportamiento sepa qué plan destraba cada carta (antes tenía
    `PLUS_VISIBLE_COUNT = 6` escrito)."""

    def test_los_topes_son_los_de_la_tabla_y_en_orden_de_precio(self):
        for tier in ("free", "plus", "pro"):
            with self.subTest(tier=tier):
                uid, h = _mk_user(tier)
                planes = self.client.get("/api/plan/features", headers=h).json()["planes"]
                self.assertEqual([p["tier"] for p in planes], list(PLANES_EN_VENTA))
                for p in planes:
                    for k, v in p["limits"].items():
                        self.assertEqual(v, PLAN_LIMITS[p["tier"]][k], f"{p['tier']}.{k}")
                    self.assertEqual(p["limits"]["behavioral_tags_visible"],
                                     _cupo("detectores", p["tier"]))
                    # El tope que nadie aplica no se manda: mandarlo es invitar
                    # a que alguien lo prometa.
                    self.assertNotIn("insights_diagnostic_visible", p["limits"])


# ─── Capa 2: cada motivo, cada origen, contra su límite ─────────────────────

# (motivo, origen, destino) de los diez carteles, como los arma main.py.
_LOS_CARTELES = (
    ("brokers", "free", "pro"), ("brokers", "plus", "pro"),
    ("export", "free", "plus"),
    ("followups", "free", "pro"), ("followups", "plus", "pro"),
    ("analisis", "free", "pro"), ("analisis", "plus", "pro"),
    ("analisis", "free", "plus"),                       # botón ✦ del chat
    ("chat", "free", "plus"), ("chat", "plus", "pro"),
    ("diagnostico", "free", "plus"),
    ("chat_libre", "free", "pro"), ("chat_libre", "plus", "pro"),
    ("voz", "free", "plus"),
)


def _upgrade(motivo, origen, destino, usage=None):
    return {"current_tier": origen, "target_tier": destino,
            "benefits": plan_textos.cartel(motivo, origen, destino, usage=usage,
                                           guiadas=len(main._FREE_QUESTIONS_WHITELIST))}


class CadaCartelContraSuLimite(_Comparador):

    def test_los_diez_carteles(self):
        for motivo, origen, destino in _LOS_CARTELES:
            with self.subTest(motivo=motivo, origen=origen):
                self._cartel_dice_lo_que_da(_upgrade(motivo, origen, destino), motivo,
                                            f"cartel {motivo}")

    def test_el_destino_de_cada_cartel_resuelve_lo_que_se_toco(self):
        """Si el plan que se ofrece no da más en lo que la persona chocó, el
        cartel le vende algo que no le arregla nada. Pasaría, por ejemplo, si el
        Plus igualara al Free en chat y el 429 del chat siguiera ofreciendo Plus."""
        for motivo, origen, destino in _LOS_CARTELES:
            with self.subTest(motivo=motivo, origen=origen):
                self.assertTrue(plan_textos.resuelve(motivo, origen, destino),
                                f"{destino} no le da a {origen} más «{motivo}»")

    def test_lo_que_el_destino_no_mejora_no_se_nombra(self):
        """El 15/10 el Plus pasa a ver los 12 detectores: "comportamiento
        completo" deja de separar al Pro y tiene que caerse SOLO de la lista."""
        with patch.dict(PLAN_LIMITS["plus"], {"behavioral_tags_visible": None}):
            for motivo in ("brokers", "chat"):
                with self.subTest(motivo=motivo):
                    texto = " | ".join(_upgrade(motivo, "plus", "pro")["benefits"])
                    self.assertNotIn("detectores", texto)

    def test_el_cupo_propio_le_gana_a_la_tabla(self):
        """Desde el 15/10 a los que ya pagaban Plus se les respeta su cupo
        (`quota.limites_del_usuario`) y el 429 les muestra ESE número. El
        cartel tiene que comparar contra lo mismo que dice arriba."""
        propio = LIMITS["plus"]["analyses_per_week"] + 1
        usage = {"tier": "plus", "analyses_limit": propio}
        up = _upgrade("analisis", "plus", "pro", usage=usage)
        self.assertIn(f"vs {propio}/sem", up["benefits"][0])
        self._cartel_dice_lo_que_da(up, "analisis", "Plus con cupo propio", usage=usage)
        # Y un usage de OTRO plan (la lente del asesor) no se mezcla.
        up2 = _upgrade("analisis", "plus", "pro", usage={"tier": "pro", "analyses_limit": 1})
        self.assertIn(f"vs {LIMITS['plus']['analyses_per_week']}/sem", up2["benefits"][0])

    def test_sin_multiplo_exacto_no_se_inventa_uno(self):
        """40 contra 9 no es "4× más": se dicen los dos números y nada más."""
        with patch.dict(LIMITS["pro"], {"analyses_per_week": LIMITS["plus"]["analyses_per_week"] * 3 + 1}):
            primero = _upgrade("analisis", "plus", "pro")["benefits"][0]
            self.assertTrue(primero.startswith("Más análisis IA ("), primero)
            self.assertNotIn("×", primero)

    def test_el_nombre_de_cada_plan(self):
        """Estaba escrito dos veces en main.py y sin el asesor: un Asesor que
        agotaba su cupo leía "Llegaste al límite del plan Free"."""
        self.assertEqual(plan_textos.nombre("advisor"), "Asesor")
        for tier in LIMITS:
            if tier != FREE:
                self.assertNotEqual(plan_textos.nombre(tier), "Free", tier)


# ─── Capa 3: con límites inventados ─────────────────────────────────────────

# Números que no son de ningún plan. Si el cartel los dice, los está leyendo.
_INVENTADOS_LIMITS = {
    "free": {"analyses_per_week": 2, "chat_per_week": 3, "diag_dismiss_per_week": 4,
             "listens_per_week": 5},
    "plus": {"analyses_per_week": 7, "chat_per_week": 11},
    "pro": {"analyses_per_week": 53, "chat_per_week": 29},
}
_INVENTADOS_PLAN = {
    "free": {"brokers_max": 2, "behavioral_tags_visible": 5, "alerts_max": 8},
    "plus": {"brokers_max": 4, "behavioral_tags_visible": 9, "alerts_max": 17},
}


class _ConLimitesInventados:
    def setUp(self):
        super().setUp()
        parches = [patch.dict(LIMITS[p], v) for p, v in _INVENTADOS_LIMITS.items()]
        parches += [patch.dict(PLAN_LIMITS[p], v) for p, v in _INVENTADOS_PLAN.items()]
        for p in parches:
            p.start()
            self.addCleanup(p.stop)


class ConLimitesInventados(_ConLimitesInventados, _PorElCamino):
    """Los mismos carteles, por los mismos endpoints, con otras tablas. Los
    topes que BLOQUEAN también son los inventados (leen el mismo diccionario):
    la cuenta se prepara con la tabla, no con números del plan de hoy."""

    def test_los_parches_llegan_a_quien_arma_y_a_quien_bloquea(self):
        """Contra el falso verde: si el parche no llegara al diccionario que
        leen los carteles o los topes, todo lo de abajo compararía lo de siempre."""
        from ai import plan, quota
        self.assertIs(plan_textos.LIMITS, LIMITS)
        self.assertIs(plan_textos.PLAN_LIMITS, PLAN_LIMITS)
        self.assertIs(quota.LIMITS, LIMITS)
        self.assertIs(plan.PLAN_LIMITS, PLAN_LIMITS)
        self.assertEqual(LIMITS["pro"]["analyses_per_week"], 53)

    def test_todos_los_carteles_leen_los_limites(self):
        casos = (
            ("brokers", lambda: self._cartel_brokers(FREE), False),
            ("brokers", lambda: self._cartel_brokers("plus"), False),
            ("export", lambda: self._cartel_export(FREE), False),
            ("followups", lambda: self._cartel_followups("plus"), True),
            ("analisis", lambda: self._cartel_analisis(FREE), True),
            ("analisis", lambda: self._cartel_fundamentales("plus"), True),
            ("analisis", lambda: self._cartel_boton_analizar(FREE), True),
            ("chat", lambda: self._cartel_chat(FREE), True),
            ("chat", lambda: self._cartel_chat("plus"), True),
            ("diagnostico", lambda: self._cartel_diagnostico(FREE), True),
            ("chat_libre", lambda: self._cartel_chat_libre(FREE), False),
            ("voz", lambda: self._cartel_voz(FREE), True),
        )
        for motivo, pedir, con_usage in casos:
            with self.subTest(motivo=motivo):
                d = pedir()
                self._cartel_dice_lo_que_da(d["upgrade"], motivo, f"inventado {motivo}",
                                            usage=d.get("usage") if con_usage else None)

    def test_los_numeros_inventados_estan_en_el_cartel(self):
        """La otra mitad: no alcanza con que no haya un número equivocado,
        tiene que estar el nuevo."""
        esperado = {
            "brokers Free": (lambda: self._cartel_brokers(FREE),
                             ("Brokers ilimitados (vs 2 en Free)",
                              "Más análisis IA (53/sem vs 2/sem)",
                              "Todos los detectores de comportamiento (vs 5 en Free)")),
            "brokers Plus": (lambda: self._cartel_brokers("plus"),
                             ("Brokers ilimitados (vs 4 en Plus)",
                              "Más análisis IA (53/sem vs 7/sem)",
                              "Todos los detectores de comportamiento (vs 9 en Plus)")),
            "export": (lambda: self._cartel_export(FREE),
                       ("Hasta 4 brokers (vs 2 en Free)",
                        "9 detectores de comportamiento (vs 5 en Free)")),
            "chat Free": (lambda: self._cartel_chat(FREE),
                          ("Más consultas a Rendi AI (11/sem vs 3/sem)",)),
            "chat Plus": (lambda: self._cartel_chat("plus"),
                          ("Chat libre con Rendi AI (29 consultas/sem vs 11 guiadas)",)),
            "diagnóstico": (lambda: self._cartel_diagnostico(FREE),
                            ("Personalizá tu diagnóstico sin límite (en Free, 4 veces por semana)",)),
            "voz": (lambda: self._cartel_voz(FREE),
                    ("Más respuestas habladas: cada audio usa 1 de las 11 consultas por "
                     "semana (en Free, 5 audios por semana)",)),
        }
        for nombre, (pedir, frases) in esperado.items():
            with self.subTest(cartel=nombre):
                benefits = pedir()["upgrade"]["benefits"]
                for frase in frases:
                    self.assertIn(frase, benefits)

    def test_los_textos_con_numeros_tambien(self):
        d = self._cartel_brokers("plus")
        self.assertTrue(d["error"].startswith("El plan Plus permite 4 brokers."), d["error"])
        d = self._cartel_analisis(FREE)
        self.assertIn("(2 análisis en los", d["error"])
        self.assertIn("Para más análisis (53 por semana)", d["error"])
        with patch.dict(LIMITS["pro"], {"analyses_per_week": 56}):
            self.assertIn("Para 28× más análisis", self._cartel_analisis(FREE)["error"])
        with patch.dict(LIMITS["plus"], {"diag_dismiss_per_week": 6}):
            d = self._cartel_diagnostico(FREE)
            self.assertIn("pasate a Plus y descartá hasta 6 veces por semana", d["message"])
            self.assertIn("Personalizá tu diagnóstico 6 veces por semana "
                          "(en Free, 4 veces por semana)", d["upgrade"]["benefits"])
        with patch.dict(PLAN_LIMITS["plus"]["can_access"], {"export.csv": False}):
            self.assertEqual(self._cartel_export(FREE)["error"],
                             "Export CSV está disponible en el plan Pro.")

    def test_la_pantalla_recibe_los_topes_inventados(self):
        uid, h = _mk_user(FREE)
        planes = self.client.get("/api/plan/features", headers=h).json()["planes"]
        plus = next(p for p in planes if p["tier"] == "plus")
        self.assertEqual(plus["limits"]["behavioral_tags_visible"], 9)
        self.assertEqual(plus["limits"]["brokers_max"], 4)


class CadaCartelConLimitesInventados(_ConLimitesInventados, CadaCartelContraSuLimite):
    """La capa 2 entera, con las tablas inventadas."""


if __name__ == "__main__":
    unittest.main()
