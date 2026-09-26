"""Lo que el MAIL promete tiene que ser lo que el plan DA.

Este archivo existe por el mismo bug que `test_promesas_vs_producto.py`, en
otra superficie. Los mails de bienvenida (`send_welcome_pro`), de regalo
(`send_gifted_plan`) y de vencimiento (`send_expiration_reminder`) tenían la
lista de cada plan escrita a mano, y se había quedado atrás de los límites:

  · Pro decía "60 análisis IA por semana (10× más que Free)": son 60×;
  · Plus decía "4 análisis de comportamiento" (son 6 detectores) y
    "diagnóstico completo (6 observaciones)", un tope que nadie aplica;
  · al vencer un Pro: "vas a quedar en 6" análisis. Al caer a Free queda 1.
  · al vencer un Asesor: la lista de lo que pierde un Pro.

Ninguno produce un error: el mail sale y miente. Ahora las listas las arma
`billing/plan_textos.py` con los límites que el backend aplica
(`ai.quota.LIMITS`, `ai.plan.PLAN_LIMITS`), y este archivo compara lo que el
mail DICE —el texto que le llega a la persona, no la función que lo arma—
contra el número que la BLOQUEA.

Tres capas:
  1. Por el camino de producción: el webhook de Rebill (bienvenida), el
     endpoint de regalo del admin y el job diario (los dos avisos de
     vencimiento). Llamar a `send_*` a mano certificaría la función y dejaría
     afuera que el que la llama le pase el plan que corresponde — que es
     justo lo que se rompió con el asesor.
  2. Cada número que dice el mail, contra su límite, para Plus y Pro.
  3. Con límites INVENTADOS (7, 53, 11…): si quedara un número escrito a mano,
     el mail lo seguiría diciendo y acá se vería. Es la prueba de que los
     textos derivan, y de que el 2026-10-15 (`git revert 78f43739`, que le
     cambia los límites al Plus) los mails acompañan solos.

Ningún número de plan está escrito en este archivo: el esperado siempre se
lee de las dos tablas. Los únicos números a mano son los inventados de la
capa 3, que no son de ningún plan a propósito.

Corre con: cd backend && python3 -m pytest tests/test_mails_vs_limites.py
"""
import html as _html
import os
import re
import sys
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main  # noqa: E402
from ai.plan import PLAN_LIMITS  # noqa: E402
from ai.quota import LIMITS  # noqa: E402
from billing import emails  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# Los que se compran. 'advisor' tiene su propia lista (sin cupos) y su propio
# test más abajo.
PLANES = ("plus", "pro")
FREE = "free"


# ─── Leer el mail como lo lee la persona ────────────────────────────────────

def _versiones(llamada) -> dict:
    """El texto plano y el HTML SIN etiquetas de una llamada a `_send`.

    Se leen las dos porque las dos le llegan a alguien, y se le sacan las
    etiquetas al HTML porque un `<b>` en el medio parte la frase y el patrón
    no la ve (pasó en `data/prueba.test.js`)."""
    args = llamada.args
    sin_tags = re.sub(r"<[^>]+>", "", args[2])
    sin_tags = _html.unescape(re.sub(r"\s+", " ", sin_tags))
    return {"texto": args[3], "html": sin_tags}


def _numero(v) -> str:
    return "sin tope" if v is None else str(v)


# Cada frase que el mail puede decir: (la forma con número, la forma "sin tope"
# o None si el cupo no la tiene, el límite que la respalda).
_LO_QUE_DICE = {
    "analisis": (r"(\d+) análisis IA por semana", None,
                 lambda p: LIMITS[p]["analyses_per_week"]),
    "chat": (r"(\d+) consultas? por semana a Rendi AI", None,
             lambda p: LIMITS[p]["chat_per_week"]),
    "brokers": (r"Hasta (\d+) brokers?\b", r"Brokers ilimitados",
                lambda p: PLAN_LIMITS[p]["brokers_max"]),
    "detectores": (r"(\d+) detector(?:es)? de comportamiento",
                   r"Todos los detectores de comportamiento",
                   lambda p: PLAN_LIMITS[p]["behavioral_tags_visible"]),
    "alertas": (r"Hasta (\d+) alertas?\b", r"Alertas sin tope",
                lambda p: PLAN_LIMITS[p]["alerts_max"]),
    "diagnostico": (r"Personalizar el diagnóstico (\d+) veces? por semana",
                    r"Personalizar el diagnóstico sin límite",
                    lambda p: LIMITS[p]["diag_dismiss_per_week"]),
}

# Lo que queda al caer a Free, en el paréntesis de cada renglón que se pierde.
_LO_QUE_QUEDA = {
    # "con" o "en": el texto viejo decía "(vas a quedar en 6)", y si vuelve
    # tiene que caer acá con su número, no pasar por no reconocerlo.
    "analisis": (r"análisis IA por semana \(vas a quedar (?:con|en) (\d+)\)",
                 lambda: LIMITS[FREE]["analyses_per_week"]),
    "chat": (r"por semana a Rendi AI \(vas a quedar con (\d+)\)",
             lambda: LIMITS[FREE]["chat_per_week"]),
    "brokers": (r"(?:brokers?|Brokers ilimitados) \(en Free el tope es (\d+);",
                lambda: PLAN_LIMITS[FREE]["brokers_max"]),
    "detectores": (r"de comportamiento \(vas a quedar con (\d+)\)",
                   lambda: PLAN_LIMITS[FREE]["behavioral_tags_visible"]),
    "alertas": (r"(?:alertas?|Alertas sin tope)[^()]*\(en Free el tope es (\d+)",
                lambda: PLAN_LIMITS[FREE]["alerts_max"]),
    "diagnostico": (r"Personalizar el diagnóstico [^()]*\(vas a quedar con (\d+) veces? por semana\)",
                    lambda: LIMITS[FREE]["diag_dismiss_per_week"]),
}

# Accesos sí/no: el renglón está si y sólo si el plan lo tiene.
_ACCESOS = {
    "Follow-ups": "ai.followup",
    "Reportes históricos completos": "reportes.historicos",
    "Export CSV": "export.csv",
    "de % sobre tu cartera": "alerts.pct_move",
}

# Lo que ya se prometió y no es cierto para NINGÚN plan. Cada uno con su porqué.
_NO_SE_PROMETE = {
    "observaciones": "el tope de puntos del diagnóstico (`insights_diagnostic_visible`) "
                     "no lo aplica ninguna pantalla: todos ven el diagnóstico entero",
    "Distribución por activo": "`insights.distribucion_activo` no lo aplica ninguna "
                               "pantalla: la distribución se abrió para todos",
    "análisis de comportamiento": "son DETECTORES; «análisis» es el cupo de IA, y "
                                  "mezclarlos es cómo el mail dijo 4 donde eran 6",
}


class _Comparador(unittest.TestCase):
    """Las comparaciones, compartidas por las tres capas."""

    def _dice_lo_que_da(self, mail: dict, plan: str, contexto: str, *,
                        pierde: bool = False,
                        obligatorias=("analisis", "brokers")):
        """`pierde`: el mail es la lista de lo que se PIERDE al volver a Free,
        así que un acceso que Free también tiene no va (no se pierde)."""
        # Cada versión en su subTest: que el texto plano falle no puede tapar
        # lo que diga el HTML (y al revés).
        for version, texto in mail.items():
            with self.subTest(contexto=contexto, version=version):
                self._dice_lo_que_da_en(texto, plan, f"{contexto} ({version})",
                                        pierde=pierde, obligatorias=obligatorias)

    def _dice_lo_que_da_en(self, texto, plan, contexto, *, pierde, obligatorias):
        # Primero lo que MIENTE, que es lo que importa leer si esto se pone rojo.
        self._no_miente(texto, plan, contexto)
        vistos = set()
        for clave, (patron, sin_tope, real) in _LO_QUE_DICE.items():
            esperado = real(plan)
            for m in re.finditer(patron, texto, re.I):
                vistos.add(clave)
                self.assertEqual(
                    m.group(1), _numero(esperado),
                    f"{contexto}: el mail dice «{m.group(0)}» y el plan {plan} "
                    f"aplica {_numero(esperado)}")
            if sin_tope and re.search(sin_tope, texto, re.I):
                vistos.add(clave)
                self.assertIsNone(
                    esperado,
                    f"{contexto}: el mail promete «{sin_tope}» y el plan {plan} "
                    f"tiene tope {esperado}")
        for frase, feature in _ACCESOS.items():
            tiene = bool(PLAN_LIMITS[plan]["can_access"].get(feature))
            if pierde:
                tiene = tiene and not PLAN_LIMITS[FREE]["can_access"].get(feature)
            self.assertEqual(
                frase in texto, tiene,
                f"{contexto}: «{frase}» {'falta' if tiene else 'aparece'} y el plan "
                f"{plan} {'lo' if tiene else 'no lo'} tiene ({feature})")
        # Contra el falso verde: un mail que dejó de nombrar los cupos pasaría
        # todas las comparaciones de arriba sin comparar nada.
        for clave in obligatorias:
            self.assertIn(clave, vistos,
                          f"{contexto}: el mail no dice su cupo de «{clave}» — "
                          f"revisar el patrón o el texto\n{texto}")

    def _dice_lo_que_queda(self, mail: dict, plan: str, contexto: str):
        for version, texto in mail.items():
            with self.subTest(contexto=contexto, version=version, parte="queda"):
                vistos = set()
                for clave, (patron, real) in _LO_QUE_QUEDA.items():
                    for m in re.finditer(patron, texto, re.I):
                        vistos.add(clave)
                        self.assertEqual(
                            m.group(1), str(real()),
                            f"{contexto} ({version}): «{m.group(0)}» pero en Free "
                            f"queda {real()}")
                # El que motivó todo: el Pro que vence decía "vas a quedar en 6".
                self.assertIn("analisis", vistos,
                              f"{contexto} ({version}): no dice con cuántos análisis "
                              f"queda\n{texto}")

    def _no_miente(self, texto: str, plan: str, contexto: str):
        # Si alguien vuelve a poner un múltiplo, que sea el de verdad. Va
        # primero: es el error que abrió este archivo ("10× más que Free").
        for m in re.finditer(r"(\d+)× más que (Free|Plus)", texto):
            otro = m.group(2).lower()
            real = LIMITS[plan]["analyses_per_week"] // LIMITS[otro]["analyses_per_week"]
            self.assertEqual(int(m.group(1)), real,
                             f"{contexto}: dice «{m.group(0)}» y el real es {real}×")
        for frase, porque in _NO_SE_PROMETE.items():
            self.assertNotIn(frase, texto, f"{contexto}: «{frase}» — {porque}")
        if not PLAN_LIMITS[plan]["can_access"].get("ai.hub"):
            self.assertNotIn("AI Hub", texto,
                             f"{contexto}: promete el AI Hub, que {plan} no tiene")


# ─── Capa 1: por el camino de producción ────────────────────────────────────

def _mk_user(conn, email, *, tier=None, is_admin=0, requires_plan=0):
    return conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin, name, tier, "
        "                   requires_plan) VALUES (?, 'x', 1, ?, 'Ana', ?, ?)",
        (email, is_admin, tier, requires_plan),
    ).lastrowid


def _mails_a(send, email, marca):
    """Las llamadas a `_send` dirigidas a `email` cuyo asunto contiene `marca`.
    El job diario recorre TODA la base, así que se filtra por destinatario."""
    return [c for c in send.call_args_list
            if c.args and c.args[0] == email and marca in str(c.args[1])]


class PorElCaminoDeProduccion(_Comparador):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_la_bienvenida_que_manda_el_alta_por_rebill(self):
        """Webhook `subscription.created` → `_notificar_alta_rebill` →
        `send_welcome_pro(plan=metadata.rendi_plan)`."""
        for plan in PLANES:
            with self.subTest(plan=plan):
                conn = main.get_db()
                email = f"bienvenida-{uuid.uuid4().hex[:10]}@rendi.test"
                uid = _mk_user(conn, email)
                # La fila que deja /api/billing/subscribe antes de que pague.
                conn.execute(
                    """INSERT INTO subscriptions (user_id, mp_subscription_id,
                           external_reference, period, status, amount_ars,
                           created_at, updated_at)
                       VALUES (?, ?, ?, 'monthly', 'pending', 0,
                               datetime('now'), datetime('now'))""",
                    (uid, f"link-{uuid.uuid4().hex[:8]}", f"rendi-{uid}-{plan}-monthly"))
                conn.commit()
                conn.close()
                sub_id = f"sub_{uuid.uuid4().hex[:10]}"
                payload = {
                    "webhook": {"event": "subscription.created"},
                    "data": {
                        "subscription": {
                            "id": sub_id, "status": "active",
                            "nextChargeDate": "2026-10-08",
                            "metadata": {"rendi_user_id": str(uid),
                                         "rendi_plan": plan,
                                         "rendi_period": "monthly"},
                        },
                        "payment": {"id": f"pay_{uuid.uuid4().hex[:8]}", "amount": 12100},
                    },
                }
                with patch.object(emails, "_send", return_value=True) as send:
                    r = self.client.post("/api/billing/rebill-webhook", json=payload)
                self.assertEqual(r.status_code, 200, r.text)
                mios = _mails_a(send, email, "Bienvenido")
                self.assertEqual(len(mios), 1, "no salió (o salió dos veces) la bienvenida")
                self._dice_lo_que_da(_versiones(mios[0]), plan, f"bienvenida {plan}")

    def test_el_regalo_que_manda_el_admin(self):
        """POST /api/admin/billing/grant-comp → `send_gifted_plan(plan=…)`."""
        conn = main.get_db()
        admin = _mk_user(conn, f"admin-{uuid.uuid4().hex[:10]}@rendi.test", is_admin=1)
        conn.commit()
        conn.close()
        h = {"Authorization": f"Bearer {main.create_token(admin)}"}
        for plan in PLANES:
            with self.subTest(plan=plan):
                conn = main.get_db()
                email = f"regalo-{uuid.uuid4().hex[:10]}@rendi.test"
                _mk_user(conn, email, tier="free")
                conn.commit()
                conn.close()
                with patch.object(main, "_notify_plan_change", return_value=None), \
                     patch.object(emails, "_send", return_value=True) as send:
                    r = self.client.post(
                        "/api/admin/billing/grant-comp",
                        params={"email": email, "plan": plan, "days": 30},
                        headers=h)
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(r.json().get("ok"), r.text)
                mios = _mails_a(send, email, "de regalo")
                self.assertEqual(len(mios), 1, "no salió el mail del regalo")
                self._dice_lo_que_da(_versiones(mios[0]), plan, f"regalo {plan}")

    def test_el_aviso_de_vencimiento_de_una_suscripcion_cancelada(self):
        """El job diario (`run_lifecycle_job`, el que dispara
        /api/billing/run-cron) → `_send_expiration_reminders` →
        `send_expiration_reminder(plan=users.tier)`. Cuenta vieja: vuelve a
        Free, así que el mail lista lo que pierde."""
        from billing import subscriptions
        for plan in PLANES:
            with self.subTest(plan=plan):
                conn = main.get_db()
                email = f"vence-{uuid.uuid4().hex[:10]}@rendi.test"
                uid = _mk_user(conn, email, tier=plan)
                fin = (datetime.utcnow() + timedelta(days=2)).isoformat()
                conn.execute(
                    """INSERT INTO subscriptions (user_id, mp_subscription_id,
                           external_reference, period, status, amount_ars,
                           current_period_end)
                       VALUES (?, ?, 'rendi-x-monthly', 'monthly', 'cancelled', 5990, ?)""",
                    (uid, f"sub-{uuid.uuid4().hex[:10]}", fin))
                conn.commit()
                try:
                    with patch.object(emails, "_send", return_value=True) as send:
                        subscriptions.run_lifecycle_job(conn)
                finally:
                    conn.close()
                mios = _mails_a(send, email, "vence en")
                self.assertEqual(len(mios), 1, "no salió el aviso de vencimiento")
                mail = _versiones(mios[0])
                self._dice_lo_que_da(mail, plan, f"vencimiento {plan}", pierde=True)
                self._dice_lo_que_queda(mail, plan, f"vencimiento {plan}")

    def test_el_aviso_de_vencimiento_del_asesor_no_es_el_de_un_pro(self):
        """El otro aviso del job: el crédito que se acaba
        (`_send_credit_expiring_reminders`, `plan=credit_anchor_plan`). Un
        Plan Asesor regalado por grant-comp termina acá con plan='advisor', y
        `_plan_loss_*` no tenía esa rama: le listaba lo que pierde un Pro."""
        from billing import subscriptions
        conn = main.get_db()
        email = f"asesor-{uuid.uuid4().hex[:10]}@rendi.test"
        uid = _mk_user(conn, email, tier="advisor")
        fin = (datetime.utcnow() + timedelta(days=2)).isoformat()
        conn.execute(
            "UPDATE users SET credit_active_until = ?, credit_anchor_plan = 'advisor' "
            "WHERE id = ?", (fin, uid))
        # Sin fila en subscriptions el aviso no sale (no tendría dónde marcar
        # que ya se mandó). Sin fecha de fin, para que la tome sólo este aviso.
        conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars)
               VALUES (?, ?, 'rendi-x-monthly', 'monthly', 'cancelled', 0)""",
            (uid, f"sub-{uuid.uuid4().hex[:10]}"))
        conn.commit()
        try:
            with patch.object(emails, "_send", return_value=True) as send:
                subscriptions.run_lifecycle_job(conn)
        finally:
            conn.close()
        mios = _mails_a(send, email, "vence en")
        self.assertEqual(len(mios), 1, "no salió el aviso del crédito que se acaba")
        mail = _versiones(mios[0])
        self.assertIn("Asesor", mios[0].args[1])
        for version, texto in mail.items():
            self.assertIn("panel de asesor", texto,
                          f"({version}) no le dice que pierde el panel de sus clientes")
        # Sus cupos son los del plan Asesor y lo que le queda es el Free.
        self._dice_lo_que_da(mail, "advisor", "vencimiento asesor", pierde=True)
        self._dice_lo_que_queda(mail, "advisor", "vencimiento asesor")


# ─── Capa 2: cada mail, cada plan, contra su límite ─────────────────────────

def _mandar(funcion, **kwargs) -> dict:
    with patch.object(emails, "_send", return_value=True) as send:
        funcion(to="ana@rendi.test", user_name="Ana", **kwargs)
    assert send.call_count == 1, f"{funcion.__name__} no mandó un mail"
    return _versiones(send.call_args)


def _bienvenida(plan):
    return _mandar(emails.send_welcome_pro, period="monthly", amount_ars=0,
                   next_charge_date=None, plan=plan)


def _regalo(plan):
    return _mandar(emails.send_gifted_plan, plan=plan, days=30,
                   active_until="2026-10-26T00:00:00")


def _vencimiento(plan, *, requiere_plan=False):
    return _mandar(emails.send_expiration_reminder, days_left=3,
                   expires_at="2026-09-29T00:00:00", plan=plan,
                   requiere_plan=requiere_plan)


class CadaMailContraSuLimite(_Comparador):

    def test_bienvenida_y_regalo_dicen_los_cupos_del_plan(self):
        for plan in PLANES:
            for nombre, mail in (("bienvenida", _bienvenida(plan)),
                                 ("regalo", _regalo(plan))):
                with self.subTest(mail=nombre, plan=plan):
                    self._dice_lo_que_da(mail, plan, f"{nombre} {plan}")

    def test_el_vencimiento_dice_con_cuanto_queda_en_free(self):
        for plan in PLANES:
            with self.subTest(plan=plan):
                mail = _vencimiento(plan)
                self._dice_lo_que_da(mail, plan, f"vencimiento {plan}", pierde=True)
                self._dice_lo_que_queda(mail, plan, f"vencimiento {plan}")

    def test_el_vencimiento_no_lista_lo_que_free_tambien_tiene(self):
        """La lista es de lo que se PIERDE: un cupo igual al de Free no se
        pierde, y nombrarlo ahí sería decir que sí.

        Con los límites de hoy ningún cupo de Plus es igual al de Free, así que
        se fuerza uno (el chat) para que la comparación compare algo."""
        igual = LIMITS[FREE]["chat_per_week"]
        patron = _LO_QUE_DICE["chat"][0]
        with patch.dict(LIMITS["plus"], {"chat_per_week": igual}):
            self.assertRegex(_bienvenida("plus")["texto"], patron,
                             "la bienvenida sí tiene que decir el cupo de chat")
            self.assertNotRegex(_vencimiento("plus")["texto"], patron,
                                "lista el chat como pérdida y en Free es el mismo")

    def test_el_mismo_plan_dice_lo_mismo_en_el_html_y_en_el_texto(self):
        """Las dos versiones salen de los mismos renglones: si una dijera otro
        número, alguien estaría leyendo una promesa distinta según su cliente
        de correo."""
        for plan in PLANES:
            for nombre, mail in (("bienvenida", _bienvenida(plan)),
                                 ("vencimiento", _vencimiento(plan))):
                with self.subTest(mail=nombre, plan=plan):
                    for clave, (patron, sin_tope, _real) in _LO_QUE_DICE.items():
                        self.assertEqual(
                            re.findall(patron, mail["html"]),
                            re.findall(patron, mail["texto"]),
                            f"{nombre} {plan}: «{clave}» distinto en HTML y texto")

    def test_a_quien_nacio_sin_plan_gratis_no_le_lista_nada(self):
        """No vuelve a Free: queda en pausa. La lista de pérdida, con sus
        "(vas a quedar con …)", describiría un plan que no tiene. (El camino
        de producción de este caso ya lo cubre `test_sin_plan_gratis_al_terminar`.)"""
        for plan in PLANES:
            with self.subTest(plan=plan):
                mail = _vencimiento(plan, requiere_plan=True)
                for version, texto in mail.items():
                    self.assertNotIn("vas a quedar con", texto, version)
                    self.assertNotIn("en Free el tope", texto, version)
                    self.assertIn("queda en pausa", texto, version)


# ─── Capa 3: con límites inventados ─────────────────────────────────────────

# Números que no son de ningún plan. Si el mail los dice, los está leyendo.
_INVENTADOS_LIMITS = {
    "free": {"analyses_per_week": 2, "chat_per_week": 3, "diag_dismiss_per_week": 4},
    "plus": {"analyses_per_week": 7, "chat_per_week": 11, "diag_dismiss_per_week": 13},
    "pro": {"analyses_per_week": 53, "chat_per_week": 29},
}
_INVENTADOS_PLAN = {
    "free": {"brokers_max": 2, "behavioral_tags_visible": 5, "alerts_max": 8},
    "plus": {"brokers_max": 4, "behavioral_tags_visible": 9, "alerts_max": 17},
}


class ConLimitesInventados(_Comparador):
    """Si quedara un número escrito a mano en cualquiera de los mails, con
    estos límites el mail lo seguiría diciendo — y la comparación contra la
    tabla (parcheada) lo cazaría."""

    def setUp(self):
        self._parches = []
        for plan, valores in _INVENTADOS_LIMITS.items():
            self._parches.append(patch.dict(LIMITS[plan], valores))
        for plan, valores in _INVENTADOS_PLAN.items():
            self._parches.append(patch.dict(PLAN_LIMITS[plan], valores))
        for p in self._parches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self._parches)])

    def test_los_parches_estan_puestos(self):
        """Contra el falso verde: si el parche no llegara al diccionario que
        leen los mails, todo lo de abajo compararía los valores de siempre."""
        from billing import plan_textos
        self.assertIs(plan_textos.LIMITS, LIMITS)
        self.assertIs(plan_textos.PLAN_LIMITS, PLAN_LIMITS)
        self.assertEqual(LIMITS["plus"]["analyses_per_week"], 7)

    def test_bienvenida_regalo_y_vencimiento_leen_los_limites(self):
        for plan in PLANES:
            with self.subTest(plan=plan):
                self._dice_lo_que_da(_bienvenida(plan), plan, f"bienvenida {plan}")
                self._dice_lo_que_da(_regalo(plan), plan, f"regalo {plan}")
                mail = _vencimiento(plan)
                self._dice_lo_que_da(mail, plan, f"vencimiento {plan}", pierde=True)
                self._dice_lo_que_queda(mail, plan, f"vencimiento {plan}")

    def test_los_numeros_inventados_estan_en_el_mail(self):
        """La otra mitad: no alcanza con que no haya un número equivocado,
        tiene que estar el nuevo."""
        texto = _vencimiento("plus")["texto"]
        for frase in ("Hasta 4 brokers (en Free el tope es 2;",
                      "9 detectores de comportamiento (vas a quedar con 5)",
                      "Hasta 17 alertas, también de % sobre tu cartera "
                      "(en Free el tope es 8, sólo de precio;",
                      "Personalizar el diagnóstico 13 veces por semana "
                      "(vas a quedar con 4 veces por semana)",
                      "7 análisis IA por semana (vas a quedar con 2)",
                      "11 consultas por semana a Rendi AI (vas a quedar con 3)"):
            self.assertIn(frase, texto)
        self.assertIn("53 análisis IA por semana (vas a quedar con 2)",
                      _vencimiento("pro")["texto"])

    def test_la_campania_de_la_prueba_lee_los_limites(self):
        """`send_trial_invite` decía "60 análisis por semana en vez de 1"."""
        junto = " ".join(emails._pro_ganchos())
        self.assertIn("53 análisis por semana en vez de 2", junto)

    def test_el_aviso_de_fin_de_prueba_lee_el_cupo_de_free(self):
        """`send_trial_ending_soon` decía "vuelve a Free: 1 análisis"."""
        mail = _mandar(emails.send_trial_ending_soon, days_left=2)
        for version, texto in mail.items():
            self.assertIn("vuelve a Free: 2 análisis por semana", texto, version)


if __name__ == "__main__":
    unittest.main()
