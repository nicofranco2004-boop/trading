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
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main  # noqa: E402
from ai.plan import PLAN_LIMITS  # noqa: E402
from ai import quota as _quota  # noqa: E402
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
    "chat": (r"por semana a Rendi AI(?: con preguntas guiadas)? \(vas a quedar con (\d+)\)",
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
    "variación %": "alerts.pct_move",
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


# Los cupos SEMANALES son de la persona (`plan_textos.cupos_del_usuario`); el
# resto sale siempre de la tabla del plan.
_CUPO_SEMANAL = {"analisis": "analyses_per_week", "chat": "chat_per_week",
                 "diagnostico": "diag_dismiss_per_week"}


def _real(clave: str, plan: str, cupos=None):
    """Lo que el plan (o la persona, si vienen sus `cupos`) tiene en `clave`."""
    if cupos and clave in _CUPO_SEMANAL:
        return cupos[_CUPO_SEMANAL[clave]]
    return _LO_QUE_DICE[clave][2](plan)


def _mas(a, b) -> bool:
    """El oráculo del test para "da más": None es sin tope. Escrito acá y no
    importado de plan_textos, para no certificar la función con ella misma."""
    if a is None:
        return b is not None
    if b is None:
        return False
    return a > b


def _obligatorias(plan: str, pierde: bool, cupos=None) -> set:
    """Los cupos que el mail TIENE que nombrar: todos los que el plan da (o,
    en la lista de pérdida, los que da más que Free). Contra el falso verde:
    si un renglón desaparece, las comparaciones no tendrían nada que comparar
    y pasarían igual."""
    claves = set()
    for clave in _LO_QUE_DICE:
        v = _real(clave, plan, cupos)
        if pierde:
            if _mas(v, _real(clave, FREE)):
                claves.add(clave)
        elif v is None or v > 0:
            claves.add(clave)
    return claves


def _lo_que_encuentra(texto: str) -> dict:
    """Por clave: (números que dice, si dice la forma "sin tope")."""
    return {clave: (re.findall(patron, texto, re.I),
                    bool(sin_tope and re.search(sin_tope, texto, re.I)))
            for clave, (patron, sin_tope, _real_) in _LO_QUE_DICE.items()}


class _Comparador(unittest.TestCase):
    """Las comparaciones, compartidas por las tres capas."""

    def _dice_lo_que_da(self, mail: dict, plan: str, contexto: str, *,
                        pierde: bool = False, cupos=None):
        """`pierde`: el mail es la lista de lo que se PIERDE al volver a Free,
        así que lo que Free también tiene no va (no se pierde).
        `cupos`: los de la persona, cuando el mail se armó con los suyos."""
        # Cada versión en su subTest: que el texto plano falle no puede tapar
        # lo que diga el HTML (y al revés).
        for version, texto in mail.items():
            with self.subTest(contexto=contexto, version=version):
                self._dice_lo_que_da_en(texto, plan, f"{contexto} ({version})",
                                        pierde=pierde, cupos=cupos)

    def _dice_lo_que_da_en(self, texto, plan, contexto, *, pierde, cupos):
        # Primero lo que MIENTE, que es lo que importa leer si esto se pone rojo.
        self._no_miente(texto, plan, contexto)
        vistos = set()
        for clave, (patron, sin_tope, _tabla) in _LO_QUE_DICE.items():
            esperado = _real(clave, plan, cupos)
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
        faltan = _obligatorias(plan, pierde, cupos) - vistos
        self.assertFalse(
            faltan, f"{contexto}: el mail no nombra {sorted(faltan)}, que el plan "
                    f"{plan} tiene — revisar el patrón o el texto\n{texto}")

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


@contextmanager
def _con_cupo_propio(uid, analisis):
    """Que `get_current_usage` —lo que la app le muestra a esa persona como su
    cupo— le dé otro número de análisis que el de su plan. Hoy eso pasa sólo
    así, parcheado; desde el 15/10 pasa de verdad con los que ya pagaban Plus
    (`quota.limites_del_usuario`)."""
    real = _quota.get_current_usage

    def falso(conn, user_id, tier_override=None):
        uso = real(conn, user_id, tier_override=tier_override)
        return {**uso, "analyses_limit": analisis} if user_id == uid else uso

    with patch.object(_quota, "get_current_usage", falso):
        yield


def _alta_rebill(client, uid, plan):
    """El alta por Rebill entera: la fila pendiente de /subscribe + el webhook."""
    conn = main.get_db()
    conn.execute(
        """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
               period, status, amount_ars, created_at, updated_at)
           VALUES (?, ?, ?, 'monthly', 'pending', 0, datetime('now'), datetime('now'))""",
        (uid, f"link-{uuid.uuid4().hex[:8]}", f"rendi-{uid}-{plan}-monthly"))
    conn.commit()
    conn.close()
    payload = {
        "webhook": {"event": "subscription.created"},
        "data": {
            "subscription": {
                "id": f"sub_{uuid.uuid4().hex[:10]}", "status": "active",
                "nextChargeDate": "2026-10-08",
                "metadata": {"rendi_user_id": str(uid), "rendi_plan": plan,
                             "rendi_period": "monthly"},
            },
            "payment": {"id": f"pay_{uuid.uuid4().hex[:8]}", "amount": 12100},
        },
    }
    return client.post("/api/billing/rebill-webhook", json=payload)


def _correr_el_job():
    from billing import subscriptions
    conn = main.get_db()
    try:
        subscriptions.run_lifecycle_job(conn)
    finally:
        conn.close()


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


    def test_los_cuatro_caminos_dicen_el_cupo_de_la_persona(self):
        """Bienvenida, regalo y los dos avisos de vencimiento se arman con los
        cupos de ESA persona (`plan_textos.cupos_del_usuario`), no con los del
        plan. El 41 no es el cupo de ningún plan: si aparece, lo leyó."""
        propio, free = 41, LIMITS[FREE]["analyses_per_week"]
        conn = main.get_db()
        admin = _mk_user(conn, f"admin-{uuid.uuid4().hex[:10]}@rendi.test", is_admin=1)
        conn.commit()
        conn.close()
        h = {"Authorization": f"Bearer {main.create_token(admin)}"}

        def nueva(tier=None):
            conn = main.get_db()
            email = f"propio-{uuid.uuid4().hex[:10]}@rendi.test"
            uid = _mk_user(conn, email, tier=tier)
            conn.commit()
            conn.close()
            return uid, email

        with self.subTest(camino="bienvenida (webhook de Rebill)"):
            uid, email = nueva()
            with _con_cupo_propio(uid, propio), \
                 patch.object(emails, "_send", return_value=True) as send:
                self.assertEqual(_alta_rebill(self.client, uid, "plus").status_code, 200)
            (mail,) = _mails_a(send, email, "Bienvenido")
            self.assertIn(f"{propio} análisis IA por semana", _versiones(mail)["texto"])

        with self.subTest(camino="regalo (grant-comp)"):
            uid, email = nueva(tier="free")
            with _con_cupo_propio(uid, propio), \
                 patch.object(main, "_notify_plan_change", return_value=None), \
                 patch.object(emails, "_send", return_value=True) as send:
                r = self.client.post("/api/admin/billing/grant-comp", headers=h,
                                     params={"email": email, "plan": "plus", "days": 30})
            self.assertEqual(r.status_code, 200, r.text)
            (mail,) = _mails_a(send, email, "de regalo")
            self.assertIn(f"{propio} análisis IA por semana", _versiones(mail)["texto"])

        with self.subTest(camino="vencimiento de la suscripción cancelada"):
            uid, email = nueva(tier="plus")
            conn = main.get_db()
            conn.execute(
                """INSERT INTO subscriptions (user_id, mp_subscription_id,
                       external_reference, period, status, amount_ars, current_period_end)
                   VALUES (?, ?, 'rendi-x-monthly', 'monthly', 'cancelled', 5990, ?)""",
                (uid, f"sub-{uuid.uuid4().hex[:10]}",
                 (datetime.utcnow() + timedelta(days=2)).isoformat()))
            conn.commit()
            conn.close()
            with _con_cupo_propio(uid, propio), \
                 patch.object(emails, "_send", return_value=True) as send:
                _correr_el_job()
            (mail,) = _mails_a(send, email, "vence en")
            self.assertIn(f"{propio} análisis IA por semana (vas a quedar con {free})",
                          _versiones(mail)["texto"])

        with self.subTest(camino="vencimiento del crédito, sin plan anotado"):
            # Sin `credit_anchor_plan` el aviso caía a "Pro" aunque la persona
            # tuviera Plus: ahora nombra el plan que tiene puesto.
            uid, email = nueva(tier="plus")
            conn = main.get_db()
            conn.execute("UPDATE users SET credit_active_until = ? WHERE id = ?",
                         ((datetime.utcnow() + timedelta(days=2)).isoformat(), uid))
            conn.execute(
                """INSERT INTO subscriptions (user_id, mp_subscription_id,
                       external_reference, period, status, amount_ars)
                   VALUES (?, ?, 'rendi-x-monthly', 'monthly', 'cancelled', 0)""",
                (uid, f"sub-{uuid.uuid4().hex[:10]}"))
            conn.commit()
            conn.close()
            with _con_cupo_propio(uid, propio), \
                 patch.object(emails, "_send", return_value=True) as send:
                _correr_el_job()
            (mail,) = _mails_a(send, email, "vence en")
            self.assertIn("Plus", mail.args[1])
            self.assertNotIn("Pro", mail.args[1])
            self.assertIn(f"{propio} análisis IA por semana (vas a quedar con {free})",
                          _versiones(mail)["texto"])

    @unittest.skipUnless(hasattr(_quota, "limites_del_usuario"),
                         "se activa sola con el revert de 78f43739 (2026-10-15)")
    def test_el_plus_que_ya_pagaba_lee_su_cupo_de_antes(self):
        """Desde el 15/10 a los que ya pagaban Plus se les respeta el cupo viejo
        de análisis. Si cancelan con la suba de precio, el aviso tiene que
        decir SU número, no el del plan nuevo."""
        conn = main.get_db()
        email = f"legacy-{uuid.uuid4().hex[:10]}@rendi.test"
        uid = _mk_user(conn, email, tier="plus")
        conn.execute("UPDATE users SET quota_plus_legacy = 1 WHERE id = ?", (uid,))
        conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id,
                   external_reference, period, status, amount_ars, current_period_end)
               VALUES (?, ?, 'rendi-x-monthly', 'monthly', 'cancelled', 5990, ?)""",
            (uid, f"sub-{uuid.uuid4().hex[:10]}",
             (datetime.utcnow() + timedelta(days=2)).isoformat()))
        conn.commit()
        conn.close()
        with patch.object(emails, "_send", return_value=True) as send:
            _correr_el_job()
        (mail,) = _mails_a(send, email, "vence en")
        viejo, free = _quota.ANALISIS_PLUS_ANTES_DEL_CAMBIO, LIMITS[FREE]["analyses_per_week"]
        self.assertIn(f"{viejo} análisis IA por semana (vas a quedar con {free})",
                      _versiones(mail)["texto"])


# ─── Capa 2: cada mail, cada plan, contra su límite ─────────────────────────

def _mandar(funcion, **kwargs) -> dict:
    with patch.object(emails, "_send", return_value=True) as send:
        funcion(to="ana@rendi.test", user_name="Ana", **kwargs)
    if send.call_count != 1:
        raise AssertionError(f"{funcion.__name__} mandó {send.call_count} mails, no 1")
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
                    html_, texto = (_lo_que_encuentra(mail["html"]),
                                    _lo_que_encuentra(mail["texto"]))
                    self.assertEqual(html_, texto,
                                     f"{nombre} {plan}: HTML y texto dicen distinto")
                    # Contra el falso verde: [] == [] también es "igual".
                    pierde = nombre == "vencimiento"
                    for clave in _obligatorias(plan, pierde):
                        numeros, sin_tope = texto[clave]
                        self.assertTrue(numeros or sin_tope,
                                        f"{nombre} {plan}: no dice «{clave}»")
                    for frase in _ACCESOS:
                        self.assertEqual(frase in mail["html"], frase in mail["texto"],
                                         f"{nombre} {plan}: «{frase}» en uno solo")

    def test_el_chat_sin_chat_libre_dice_que_son_preguntas_guiadas(self):
        """Plus no tiene chat libre (main.py, `is_premium`): "9 consultas" a
        secas se lee como "preguntale lo que quieras", y no es así."""
        self.assertIn("con preguntas guiadas", _bienvenida("plus")["texto"])
        self.assertNotIn("con preguntas guiadas", _bienvenida("pro")["texto"])

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


class LaTablaNoSeContradice(unittest.TestCase):
    """PLAN_LIMITS dice lo mismo de Comportamiento en DOS campos:
    `behavioral_tags_visible` (cuántos detectores, None = todos) y
    `can_access["comportamiento.full"]`. El mail y la grilla de la app leen el
    primero; el catálogo piensa en el segundo. Si alguien cambia uno sin el
    otro (el 15/10 el revert cambia los dos juntos), el mail prometería
    "Todos los detectores" y la pantalla mostraría otra cosa."""

    def test_sin_tope_de_detectores_si_y_solo_si_comportamiento_completo(self):
        for plan, limites in PLAN_LIMITS.items():
            with self.subTest(plan=plan):
                self.assertEqual(
                    limites["behavioral_tags_visible"] is None,
                    bool(limites["can_access"].get("comportamiento.full")),
                    f"{plan}: behavioral_tags_visible="
                    f"{limites['behavioral_tags_visible']} y comportamiento.full="
                    f"{limites['can_access'].get('comportamiento.full')} se contradicen")


    def test_el_chat_libre_se_nombra_en_los_planes_que_lo_tienen(self):
        """plan_textos dice "quién tiene chat libre" en dos lugares: `_PREMIUM`
        (la aclaración de las preguntas guiadas) y el renglón "Chat libre" de
        lo que se pierde. Si alguien cambia uno sin el otro, el mismo mail diría
        las dos cosas. La regla de fondo es `is_premium` en main.py."""
        from billing import plan_textos
        nombran = {p for p, renglones in plan_textos._SIN_NUMEROS_AL_PERDER.items()
                   if any("Chat libre" in r for r in renglones)}
        self.assertEqual(nombran, set(plan_textos._PREMIUM))


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
                      "Hasta 17 alertas: de precio objetivo y de variación % "
                      "(en Free el tope es 8, sólo de precio objetivo;",
                      "Personalizar el diagnóstico 13 veces por semana "
                      "(vas a quedar con 4 veces por semana)",
                      "7 análisis IA por semana (vas a quedar con 2)",
                      "11 consultas por semana a Rendi AI con preguntas guiadas (vas a quedar con 3)"):
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


class ConUnPlanQueCambiaDeForma(_Comparador):
    """Los números inventados de arriba no cubren lo que hace el 15/10: cupos
    que pasan a "sin tope" y accesos sí/no que cambian. Acá se da vuelta todo
    eso en el Plus, con valores que no son los de ningún día real."""

    def setUp(self):
        for parche in (
            patch.dict(PLAN_LIMITS["plus"], {"behavioral_tags_visible": None,
                                             "alerts_max": None}),
            patch.dict(PLAN_LIMITS["plus"]["can_access"], {"export.csv": False,
                                                           "ai.followup": True,
                                                           "comportamiento.full": True}),
            patch.dict(LIMITS["plus"], {"analyses_per_week": 5,
                                        "diag_dismiss_per_week": 7}),
        ):
            parche.start()
            self.addCleanup(parche.stop)

    def test_los_mails_acompanan(self):
        self._dice_lo_que_da(_bienvenida("plus"), "plus", "bienvenida plus")
        mail = _vencimiento("plus")
        self._dice_lo_que_da(mail, "plus", "vencimiento plus", pierde=True)
        self._dice_lo_que_queda(mail, "plus", "vencimiento plus")
        texto = mail["texto"]
        self.assertIn("Todos los detectores de comportamiento (vas a quedar con", texto)
        self.assertIn("Alertas sin tope", texto)
        self.assertIn("Follow-ups", texto)
        self.assertNotIn("Export CSV", texto)
        self.assertIn("Personalizar el diagnóstico 7 veces por semana", texto)


if __name__ == "__main__":
    unittest.main()
