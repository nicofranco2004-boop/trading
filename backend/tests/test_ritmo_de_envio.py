"""Ritmo de los mails y avisos que no se pierden.

Resend (el servicio de mail) acepta un número acotado de pedidos por segundo y
rechaza los que pasan. Lo que estos tests protegen:

  1. Que entre un pedido a Resend y el siguiente pasen PAUSA_ENTRE_ENVIOS
     segundos, para TODO el proceso: lo pone `emails._send`, el único lugar
     por el que pasan todos los mails. Antes pausaban dos loops y el resto
     (avisos de la prueba, de vencimiento, alertas, brief del asesor, aviso al
     admin) mandaba de un tirón.
  2. Que un aviso automático que Resend RECHAZÓ se reintente en la corrida
     siguiente. Antes quedaba anotado como enviado y no llegaba nunca.
  3. Que uno que QUIZÁS llegó (se cortó esperando la respuesta) NO se
     reintente: un aviso repetido es peor que uno perdido.
  4. Que el cron de alertas conteste al instante y corra en segundo plano, y
     que el job de las 03:30 y `/api/billing/run-cron` no corran a la vez.
  5. Que mientras se manda no quede tomada la base (el resto de la app no puede
     comer 'database is locked' porque un loop espera su turno con Resend).

⚠️ POR EL MISMO CAMINO QUE PRODUCCIÓN. Los crons corren de verdad
(`run_lifecycle_job`, `evaluate_alerts`, `run_briefs`) y los mails pasan por
los `send_*` y el `_send` reales. Lo único de mentira es Resend: `httpx.post`
lo contesta `Resend` de tests/_resend_falso.py, y el reloj de `emails` es `Reloj` (su `sleep` avanza el
tiempo en vez de esperar), para medir la separación entre pedidos sin que la
suite tarde. Para que `_send` llegue a pedir, se apaga su guarda de pytest; la
clave es de mentira, así que aunque un pedido se escapara, Resend lo rechazaría.
"""
from __future__ import annotations

import inspect
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import patch

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main                                   # noqa: E402  (conftest ya apuntó DB_PATH a un temporal)
import alerts_engine as ae                    # noqa: E402
import advisor_brief                          # noqa: E402
from billing import emails                    # noqa: E402
from billing import subscriptions as subs     # noqa: E402
from billing import trial as tr               # noqa: E402

PAUSA = emails.PAUSA_ENTRE_ENVIOS
DOMINIO = "buzon-de-prueba.com"   # NO reservado: `_send` sólo pide para direcciones reales


# ─── Resend y reloj de mentira (tests/_resend_falso.py) ──────────────────────
from tests._resend_falso import (                               # noqa: E402
    Reloj as _Reloj, red_de_mentira as _red_de_mentira, separaciones as _separaciones)


# ─── La base ─────────────────────────────────────────────────────────────────

@pytest.fixture
def conn():
    c = main.get_db()
    try:
        c.rollback()
    except Exception:
        pass
    # Las que referencian a `users` van antes (claves foráneas activas): si no,
    # el DELETE de users falla callado y el usuario de un test choca con el
    # del siguiente.
    for t in ("alert_symbol_state", "alert_events", "alerts", "advisor_brief_log",
              "push_subscriptions", "iol_lab_token_log", "user_broker_credentials",
              "credit_ledger", "subscriptions", "trial_consumed", "trial_email_log",
              "operations", "positions", "brokers", "ai_usage_daily", "users"):
        try:
            c.execute(f"DELETE FROM {t}")
        except Exception:
            pass
    c.commit()
    os.environ.pop("TRIALS_ENABLED", None)
    os.environ.pop("TRIALS_MONTHLY_CAP", None)
    yield c
    try:
        c.rollback()
    except Exception:
        pass
    c.close()


def _usuario(conn, nombre, **cols):
    cols = {"email": f"{nombre}@{DOMINIO}", "name": nombre.capitalize(),
            "password_hash": "x", "approved": 1, "email_verified": 1, **cols}
    cur = conn.execute(
        f"INSERT INTO users ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        tuple(cols.values()))
    conn.commit()
    return cur.lastrowid


def _en_prueba_hace(conn, uid, dias):
    """Activa la prueba de verdad (`trial.start`) y la corre `dias` hacia atrás.
    El mail de bienvenida sale acá, ANTES de abrir la red de mentira: bajo
    pytest `_send` no lo pide y no entra en las cuentas de los tests."""
    assert tr.start(conn, uid)["ok"]
    row = conn.execute("SELECT trial_started_at, credit_active_until, trial_ends_at "
                       "FROM users WHERE id=?", (uid,)).fetchone()
    d = timedelta(days=dias)
    conn.execute(
        "UPDATE users SET trial_started_at=?, credit_active_until=?, trial_ends_at=? "
        "WHERE id=?",
        ((datetime.fromisoformat(row["trial_started_at"]) - d).isoformat(),
         (datetime.fromisoformat(row["credit_active_until"]) - d).isoformat(),
         (datetime.fromisoformat(row["trial_ends_at"]) - d).isoformat(), uid))
    conn.commit()


def _marcados(conn, kind):
    return {r["user_id"] for r in conn.execute(
        "SELECT user_id FROM trial_email_log WHERE kind=?", (kind,)).fetchall()}


def _escribir_desde_otra_conexion():
    """¿Puede el resto de la app escribir en este momento? Otra conexión pide
    el lock de escritura con medio segundo de paciencia."""
    otra = sqlite3.connect(main.DB_PATH, timeout=0.5)
    try:
        otra.execute("BEGIN IMMEDIATE")
        otra.rollback()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        otra.close()


# ─── 1. La pausa vive en `_send` ─────────────────────────────────────────────

def test_mails_seguidos_salen_separados_por_la_pausa():
    reloj = _Reloj()
    with _red_de_mentira(reloj) as resend:
        for n in ("ana", "beto", "caro"):
            assert emails.send_alert_email(to=f"{n}@{DOMINIO}", heading="GGAL subió 5%",
                                           detail="GGAL subió 5% hoy.")
    assert len(resend.pedidos) == 3
    assert all(s >= PAUSA - 1e-9 for s in _separaciones(h for h, _ in resend.pedidos))


def test_un_mail_suelto_con_todo_tranquilo_no_espera():
    """La pausa se cuenta desde el pedido anterior: el código de verificación
    de alguien que se registra a la tarde no paga la pausa de la mañana."""
    reloj = _Reloj()
    with _red_de_mentira(reloj) as resend:
        emails.send_alert_email(to=f"ana@{DOMINIO}", heading="h", detail="d")
        reloj.ahora += 5
        emails.send_alert_email(to=f"beto@{DOMINIO}", heading="h", detail="d")
    assert len(resend.pedidos) == 2
    assert reloj.siestas == []


def test_con_la_pausa_en_cero_no_duerme():
    reloj = _Reloj()
    with _red_de_mentira(reloj) as resend, patch.object(emails, "PAUSA_ENTRE_ENVIOS", 0):
        for n in ("ana", "beto", "caro"):
            emails.send_alert_email(to=f"{n}@{DOMINIO}", heading="h", detail="d")
    assert len(resend.pedidos) == 3
    assert reloj.siestas == []


def test_dos_loops_a_la_vez_tambien_se_turnan():
    """El tope es de la CUENTA de Resend: dos crons mandando al mismo tiempo
    no pueden sumarse en el mismo segundo. Con hilos y reloj de verdad."""
    pausa = 0.15
    with _red_de_mentira(demora=0) as resend, patch.object(emails, "PAUSA_ENTRE_ENVIOS", pausa):
        def loop(quien):
            with emails.envio_masivo():
                for i in range(2):
                    emails.send_alert_email(to=f"{quien}{i}@{DOMINIO}", heading="h", detail="d")
        hilos = [threading.Thread(target=loop, args=(q,)) for q in ("ana", "beto")]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(10)
    assert len(resend.pedidos) == 4
    # 0,9 y no 0,6: con la pausa real (0,6 s), el 60 % son tres mails en un
    # segundo y Resend rechaza el tercero — el test tiene que verlo.
    assert min(_separaciones(h for h, _ in resend.pedidos)) >= pausa * 0.9


def test_solo_send_le_habla_a_resend():
    """La pausa vale porque `_send` es la ÚNICA puerta a Resend. Un mail que se
    mande por otro lado se saltea la pausa y la clasificación del resultado."""
    import ast
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    afuera = []
    for raiz, dirs, archivos in os.walk(backend):
        dirs[:] = [d for d in dirs if d not in ("tests", "node_modules", "venv", ".venv",
                                                "__pycache__", "scripts")]
        for a in archivos:
            if a.endswith(".py"):
                ruta = os.path.join(raiz, a)
                with open(ruta, encoding="utf-8") as f:
                    if "api.resend.com" in f.read():
                        afuera.append(os.path.relpath(ruta, backend))
    assert afuera == [os.path.join("billing", "emails.py")]
    arbol = ast.parse(inspect.getsource(emails))
    quien_postea = {
        fn.name for fn in ast.walk(arbol) if isinstance(fn, ast.FunctionDef)
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "post" and getattr(n.func.value, "id", None) == "httpx"}
    assert quien_postea == {"_pedir_a_resend"}
    # …y a `_pedir_a_resend` (que hace la fila) sólo lo llaman `_send` (los
    # masivos, desde su hilo) y el cartero (los sueltos).
    quien_pide = {
        fn.name for fn in ast.walk(arbol) if isinstance(fn, ast.FunctionDef)
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_pedir_a_resend"}
    assert quien_pide == {"_send", "_cartero"}


# ─── 2 y 3. Los avisos de la prueba, con el cron entero ──────────────────────

def test_el_cron_de_la_prueba_manda_con_pausa(conn):
    uids = [_usuario(conn, n) for n in ("ana", "beto", "caro")]
    for u in uids:
        _en_prueba_hace(conn, u, tr.TRIAL_PRO_DAYS - 1)      # víspera del paso a Plus
    reloj = _Reloj()
    with _red_de_mentira(reloj) as resend:
        res = subs.run_lifecycle_job(conn)
    assert res["trial_emails_sent"] == 3
    a_ellos = [h for h, to in resend.pedidos if to.split("@")[0] in ("ana", "beto", "caro")]
    assert len(a_ellos) == 3
    # TODOS los pedidos de la corrida (incluidos los avisos al admin, si hubo)
    assert all(s >= PAUSA - 1e-9 for s in _separaciones(h for h, _ in resend.pedidos))


@pytest.mark.parametrize("respuesta", [
    pytest.param(429, id="429-pasamos-el-tope-por-segundo"),
    pytest.param(422, id="422-resend-no-lo-acepta"),
    pytest.param(httpx.ConnectError("sin red"), id="sin-conexion"),
])
def test_un_aviso_rechazado_sale_en_la_corrida_siguiente(conn, respuesta):
    uids = {n: _usuario(conn, n) for n in ("ana", "beto", "caro")}
    for u in uids.values():
        _en_prueba_hace(conn, u, tr.TRIAL_PRO_DAYS - 1)
    beto = f"beto@{DOMINIO}"
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[beto] = [respuesta]
        r1 = subs.run_lifecycle_job(conn)
        # A Beto Resend se lo rechazó: no cuenta como enviado y NO queda marcado.
        assert r1["trial_emails_sent"] == 2
        assert uids["beto"] not in _marcados(conn, tr.MAIL_PRO_ENDING)
        assert len(resend.a(beto)) == 1

        r2 = subs.run_lifecycle_job(conn)          # la corrida siguiente (hay dos por día)
        assert r2["trial_emails_sent"] == 1
        assert len(resend.a(beto)) == 2
        assert uids["beto"] in _marcados(conn, tr.MAIL_PRO_ENDING)

        subs.run_lifecycle_job(conn)               # y no se repite nunca más
    assert len(resend.a(beto)) == 2
    assert len(resend.a(f"ana@{DOMINIO}")) == 1
    assert len(resend.a(f"caro@{DOMINIO}")) == 1


@pytest.mark.parametrize("respuesta", [
    pytest.param(httpx.ReadTimeout("no contestó"), id="se-corto-esperando-la-respuesta"),
    pytest.param(500, id="500-fallo-de-su-lado"),
])
def test_un_aviso_que_quizas_llego_no_se_reintenta(conn, respuesta):
    """Pasa también con el código viejo: protege que el reintento no se
    estire a los casos donde Resend pudo haberlo mandado."""
    uid = _usuario(conn, "beto")
    _en_prueba_hace(conn, uid, tr.TRIAL_PRO_DAYS - 1)
    beto = f"beto@{DOMINIO}"
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[beto] = [respuesta]
        subs.run_lifecycle_job(conn)
        assert uid in _marcados(conn, tr.MAIL_PRO_ENDING)
        subs.run_lifecycle_job(conn)
    assert len(resend.a(beto)) == 1


def test_si_el_mail_explota_al_armarse_se_reintenta(conn):
    """El mail ni llegó a pedirse: seguro que no salió."""
    uid = _usuario(conn, "beto")
    _en_prueba_hace(conn, uid, tr.TRIAL_TOTAL_DAYS + 1)       # terminó la prueba
    beto = f"beto@{DOMINIO}"
    real = tr._trial_stats
    veces = {"n": 0}

    def explota_la_primera(c, u):
        veces["n"] += 1
        if veces["n"] == 1:
            raise RuntimeError("se cayó armando el resumen")
        return real(c, u)

    with _red_de_mentira(_Reloj()) as resend, \
         patch.object(tr, "_trial_stats", explota_la_primera):
        tr.send_due_trial_emails(conn)
        assert uid not in _marcados(conn, tr.MAIL_ENDED)
        assert resend.a(beto) == []
        tr.send_due_trial_emails(conn)
    assert uid in _marcados(conn, tr.MAIL_ENDED)
    assert len(resend.a(beto)) == 1


def _dos_corridas_a_la_vez(corrida, cruzar_en, objeto):
    """Corre `corrida(conn)` en dos hilos, cada uno con su conexión, y los hace
    pasar JUNTOS por `objeto.cruzar_en` (una barrera): las dos llegan a querer
    la marca al mismo tiempo, que es el cruce contra el que existe la condición
    de la marca. Sin forzarlo, casi siempre la segunda ya ve la marca de la
    primera y el test pasaba aunque la condición no estuviera."""
    barrera = threading.Barrier(2, timeout=5)
    real = getattr(objeto, cruzar_en)

    def con_barrera(*a, **kw):
        r = real(*a, **kw)
        try:
            barrera.wait()
        except threading.BrokenBarrierError:
            pass
        return r

    def hilo():
        c = main.get_db()
        try:
            corrida(c)
        finally:
            c.close()

    with patch.object(objeto, cruzar_en, con_barrera):
        hilos = [threading.Thread(target=hilo) for _ in range(2)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(30)


def test_dos_corridas_que_llegan_juntas_a_la_marca_no_duplican(conn):
    """Las dos pasan el chequeo de "ya lo mandé" antes de que ninguna marque:
    el INSERT OR IGNORE de la marca es lo único que las separa."""
    nombres = ["ana", "beto"]
    for n in nombres:
        _en_prueba_hace(conn, _usuario(conn, n), tr.TRIAL_PRO_DAYS - 1)
    with _red_de_mentira(demora=0) as resend, patch.object(emails, "PAUSA_ENTRE_ENVIOS", 0):
        _dos_corridas_a_la_vez(tr.send_due_trial_emails, "_already_sent", tr)
    for n in nombres:
        assert len(resend.a(f"{n}@{DOMINIO}")) == 1, n


def test_un_mail_que_explota_no_hereda_el_enviado_del_anterior(conn):
    """A Ana le sale su aviso; al de Beto le explota el armado. Sin limpiar el
    resultado del envío anterior, Beto heredaba el "enviado" de Ana: quedaba
    marcado y no le llegaba nunca."""
    a = _usuario(conn, "ana")
    b = _usuario(conn, "beto")
    for u in (a, b):
        _en_prueba_hace(conn, u, tr.TRIAL_TOTAL_DAYS + 1)
    real = tr._trial_stats

    def stats(c, u):
        if u == b:
            raise RuntimeError("se cayó armando")
        return real(c, u)

    with _red_de_mentira(_Reloj()) as resend, patch.object(tr, "_trial_stats", stats):
        tr.send_due_trial_emails(conn)
    assert len(resend.a(f"ana@{DOMINIO}")) == 1
    assert _marcados(conn, tr.MAIL_ENDED) == {a}


def test_con_resend_caido_el_cron_se_frena_y_no_quema_a_todos(conn):
    """Resend no contesta: cada aviso queda "no se sabe si llegó" y marcado.
    Antes seguía con TODA la gente del día — todos marcados, ninguno con su
    mail, y sin reintento. Ahora frena a los INCIERTOS_PARA_FRENAR, y los
    demás quedan sin marca para la corrida siguiente. Una sola tanda para toda
    la corrida: tampoco siguen los avisos de vencimiento."""
    nombres = ["ana", "beto", "caro", "dani", "eli"]
    uids = {n: _usuario(conn, n) for n in nombres}
    for u in uids.values():
        _en_prueba_hace(conn, u, tr.TRIAL_PRO_DAYS - 1)
    vence = _con_credito_por_vencer(conn)
    caido = httpx.ReadTimeout("Resend no contesta")
    with _red_de_mentira(_Reloj()) as resend:
        for n in nombres + ["vera"]:
            resend.respuestas[f"{n}@{DOMINIO}"] = [caido]
        r1 = subs.run_lifecycle_job(conn)
        assert r1["avisos_frenados"] is True
        intentados = [to for _, to in resend.pedidos]
        assert len(intentados) == emails.INCIERTOS_PARA_FRENAR
        assert r1["trial_emails_sent"] == 0
        assert r1["credit_expiring_reminders_sent"] == 0
        assert len(_marcados(conn, tr.MAIL_PRO_ENDING)) == emails.INCIERTOS_PARA_FRENAR
        assert conn.execute(
            "SELECT COUNT(*) n FROM subscriptions WHERE user_id=? AND "
            "expiration_reminder_sent_at IS NOT NULL", (vence,)).fetchone()["n"] == 0

        resend.respuestas.clear()                  # en la vuelta siguiente Resend anda
        r2 = subs.run_lifecycle_job(conn)
    assert r2["trial_emails_sent"] == len(nombres) - emails.INCIERTOS_PARA_FRENAR
    assert r2["credit_expiring_reminders_sent"] == 1
    for n in nombres:                              # nadie dos veces
        assert len(resend.a(f"{n}@{DOMINIO}")) == 1, n


def test_la_bienvenida_rechazada_al_activar_la_manda_el_cron(conn):
    """El mail de bienvenida sale al activar la prueba. Antes se marcaba sin
    mirar si salió: si Resend lo rechazaba, no llegaba nunca."""
    uid = _usuario(conn, "ana")
    ana = f"ana@{DOMINIO}"
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[ana] = [429]
        assert tr.start(conn, uid)["ok"]
        assert len(resend.a(ana)) == 1
        assert uid not in _marcados(conn, tr.MAIL_STARTED)
        assert tr.send_due_trial_emails(conn) == 1         # la corrida de esa noche
        assert uid in _marcados(conn, tr.MAIL_STARTED)
        tr.send_due_trial_emails(conn)                     # y nunca más
    assert len(resend.a(ana)) == 2


def test_la_bienvenida_no_se_reintenta_pasados_los_primeros_dias(conn):
    uid = _usuario(conn, "ana")
    ana = f"ana@{DOMINIO}"
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[ana] = [429]
        assert tr.start(conn, uid)["ok"]
    row = conn.execute("SELECT trial_started_at FROM users WHERE id=?", (uid,)).fetchone()
    conn.execute("UPDATE users SET trial_started_at=? WHERE id=?",
                 ((datetime.fromisoformat(row["trial_started_at"])
                   - timedelta(days=tr.MAIL_BIENVENIDA_REINTENTO_DIAS, hours=1)).isoformat(),
                  uid))
    conn.commit()
    with _red_de_mentira(_Reloj()) as resend:
        tr.send_due_trial_emails(conn)
    assert resend.a(ana) == []


def test_mañana_termina_tu_pro_no_se_reintenta_ya_en_plus(conn):
    """Rechazado la víspera, se reintenta en la corrida siguiente — pero no
    días después del paso a Plus, cuando "mañana termina tu Pro" ya es falso."""
    uid = _usuario(conn, "ana")
    _en_prueba_hace(conn, uid, tr.TRIAL_PRO_DAYS - 1)
    ana = f"ana@{DOMINIO}"
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[ana] = [429, 429, 429]
        subs.run_lifecycle_job(conn)
    for _ in range(3):                            # las corridas de los días siguientes
        _en_prueba_hace_mas(conn, uid, 1)
        with _red_de_mentira(_Reloj()) as resend2:
            subs.run_lifecycle_job(conn)
        assert resend2.a(ana) == []
    assert len(resend.a(ana)) == 1
    assert conn.execute("SELECT tier FROM users WHERE id=?", (uid,)).fetchone()["tier"] == "plus"


def test_mañana_termina_tu_pro_sale_la_vispera_aunque_haya_arrancado_tarde(conn):
    """Medía por instante ("arrancó hace 9 días exactos") y el paso a Plus mide
    por fecha: a quien arrancó después de la hora del cron —casi todos— el
    aviso le salía en la corrida que YA lo había pasado a Plus. Ahora sale el
    día anterior, como dice el mail."""
    uid = _usuario(conn, "ana")
    assert tr.start(conn, uid)["ok"]
    hoy = datetime.utcnow().date()
    # Arrancó a última hora del día, hace TRIAL_PRO_DAYS − 1 días de calendario.
    ini = datetime.combine(hoy - timedelta(days=tr.TRIAL_PRO_DAYS - 1),
                           datetime.max.time().replace(microsecond=0))
    fin = ini + timedelta(days=tr.TRIAL_TOTAL_DAYS)
    conn.execute("UPDATE users SET trial_started_at=?, trial_ends_at=?, credit_active_until=? "
                 "WHERE id=?", (ini.isoformat(), fin.isoformat(), fin.isoformat(), uid))
    conn.commit()
    ana = f"ana@{DOMINIO}"
    with _red_de_mentira(_Reloj()) as resend:
        subs.run_lifecycle_job(conn)              # la corrida de hoy: la víspera
    asuntos = [a for to, a, _ in resend.mails if to == ana]
    assert len(asuntos) == 1, asuntos
    assert conn.execute("SELECT tier FROM users WHERE id=?", (uid,)).fetchone()["tier"] == "pro"


def test_la_bienvenida_dice_lo_que_pasa_al_terminar_segun_el_plan(conn):
    """Quien nació sin plan gratis no "vuelve a Free": queda en pausa. La
    bienvenida no pasaba `requiere_plan` (los otros avisos sí)."""
    uid = _usuario(conn, "ana", requires_plan=1)
    with _red_de_mentira(_Reloj()) as resend:
        assert tr.start(conn, uid)["ok"]
    (to, _, texto), = resend.mails
    assert "vuelve a Free" not in texto
    # Ni la comparación con "el plan Free" que no tiene (versión con formato).
    assert "Free" not in resend.htmls[to][0]


def _en_prueba_hace_mas(conn, uid, dias):
    d = timedelta(days=dias)
    row = conn.execute("SELECT trial_started_at, credit_active_until, trial_ends_at "
                       "FROM users WHERE id=?", (uid,)).fetchone()
    conn.execute(
        "UPDATE users SET trial_started_at=?, credit_active_until=?, trial_ends_at=? "
        "WHERE id=?",
        ((datetime.fromisoformat(row["trial_started_at"]) - d).isoformat(),
         (datetime.fromisoformat(row["credit_active_until"]) - d).isoformat(),
         (datetime.fromisoformat(row["trial_ends_at"]) - d).isoformat(), uid))
    conn.commit()


# ─── 2 bis. Los avisos de vencimiento, con el cron entero ────────────────────

def _con_credito_por_vencer(conn):
    uid = _usuario(conn, "vera", tier="plus",
                   credit_active_until=(datetime.utcnow() + timedelta(days=2)).isoformat())
    conn.execute(
        "INSERT INTO subscriptions (user_id, status, external_reference, period, "
        "amount_ars, created_at) VALUES (?, 'cancelled', ?, 'monthly', 10000, ?)",
        (uid, f"rendi-{uid}-monthly",
         datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    return uid


def _con_suscripcion_cancelada_por_vencer(conn):
    uid = _usuario(conn, "vera", tier="pro")
    conn.execute(
        "INSERT INTO subscriptions (user_id, mp_subscription_id, status, external_reference, "
        "period, amount_ars, current_period_end) "
        "VALUES (?, 'sub-vera', 'cancelled', ?, 'monthly', 10000, ?)",
        (uid, f"rendi-{uid}-monthly",
         (datetime.utcnow() + timedelta(days=2)).date().isoformat()))
    conn.commit()
    return uid


@pytest.mark.parametrize("preparar,contador", [
    pytest.param(_con_credito_por_vencer, "credit_expiring_reminders_sent",
                 id="fin-de-credito"),
    pytest.param(_con_suscripcion_cancelada_por_vencer, "expiration_reminders_sent",
                 id="suscripcion-cancelada"),
])
def test_el_aviso_de_vencimiento_rechazado_sale_en_la_corrida_siguiente(conn, preparar, contador):
    uid = preparar(conn)
    vera = f"vera@{DOMINIO}"

    def marcado():
        return int(bool(conn.execute("SELECT aviso_vencimiento_de m FROM users WHERE id=?",
                                     (uid,)).fetchone()["m"]))

    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[vera] = [429]
        r1 = subs.run_lifecycle_job(conn)
        assert r1[contador] == 0 and marcado() == 0
        r2 = subs.run_lifecycle_job(conn)
        assert r2[contador] == 1 and marcado() == 1
        r3 = subs.run_lifecycle_job(conn)
        assert r3[contador] == 0
    assert len(resend.a(vera)) == 2          # el rechazado y el que salió; nunca un tercero


@pytest.mark.parametrize("preparar,paso", [
    pytest.param(_con_credito_por_vencer, "_send_credit_expiring_reminders",
                 id="fin-de-credito"),
    pytest.param(_con_suscripcion_cancelada_por_vencer, "_send_expiration_reminders",
                 id="suscripcion-cancelada"),
])
def test_dos_corridas_que_llegan_juntas_al_aviso_de_vencimiento_no_duplican(
        conn, preparar, paso):
    from billing import plan_textos
    preparar(conn)
    with _red_de_mentira(demora=0) as resend, patch.object(emails, "PAUSA_ENTRE_ENVIOS", 0):
        # Las dos terminan de armar el mail (y pasaron los chequeos) juntas,
        # justo antes de pedir la marca.
        _dos_corridas_a_la_vez(getattr(subs, paso), "cupos_del_usuario", plan_textos)
    assert len(resend.a(f"vera@{DOMINIO}")) == 1


def test_los_avisos_al_admin_de_las_bajas_salen_con_pausa():
    reloj = _Reloj()
    with _red_de_mentira(reloj) as resend:
        subs._notify_admin_downgrades(
            [(f"ana@{DOMINIO}", "pro"), (f"beto@{DOMINIO}", "plus"),
             (f"caro@{DOMINIO}", "pro")], "credit_expired")
    assert len(resend.pedidos) == 3
    assert all(s >= PAUSA - 1e-9 for s in _separaciones(h for h, _ in resend.pedidos))


# ─── 4. Alertas en segundo plano; una corrida a la vez ───────────────────────

def _esperar(condicion, segundos=5):
    fin = time.time() + segundos
    while time.time() < fin:
        if condicion():
            return True
        time.sleep(0.01)
    return condicion()


def _esperar_que_termine(nombre, segundos=5):
    fin = time.time() + segundos
    while time.time() < fin:
        if nombre not in getattr(main, "_corridas_en_curso", set()):
            return True
        time.sleep(0.02)
    return False


def test_el_cron_de_alertas_contesta_al_instante_y_no_se_encima(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("ALERTS_CRON_TOKEN", "tok-alertas")
    sigue = threading.Event()
    corridas = []

    def evaluacion_lenta(c, only_user=None):
        corridas.append(1)
        sigue.wait(10)
        return {"alerts": 0, "evaluated": 0, "fired": 0}

    monkeypatch.setattr(ae, "evaluate_alerts", evaluacion_lenta)
    http = TestClient(main.app)
    respuestas = []
    pedido = threading.Thread(target=lambda: respuestas.append(
        http.get("/api/alerts/evaluate?token=tok-alertas")))
    pedido.start()
    pedido.join(3)
    try:
        # Antes evaluaba y mandaba DENTRO del pedido: con una evaluación que
        # tarda, el pedido no volvía (en producción, el proxy lo corta a ~30 s).
        assert respuestas, "el pedido se quedó esperando a que terminen las alertas"
        assert respuestas[0].json()["status"] == "started"
        assert _esperar(lambda: corridas == [1]), corridas   # el hilo arrancó
        # Un segundo ping mientras corre no encima otra corrida.
        assert http.get("/api/alerts/evaluate?token=tok-alertas").json()["status"] \
            == "already_running"
        assert len(corridas) == 1
    finally:
        sigue.set()
        pedido.join(10)
    assert _esperar_que_termine("alertas")
    # Terminada, el ping siguiente arranca otra.
    assert http.get("/api/alerts/evaluate?token=tok-alertas").json()["status"] == "started"
    assert _esperar_que_termine("alertas")
    assert len(corridas) == 2


class _SchedulerQueAnota:
    """Lo que registra `_start_scheduler`, sin arrancar nada."""

    def __init__(self):
        self.jobs = {}

    def add_job(self, func, trigger, id, replace_existing=True):
        self.jobs[id] = func

    def start(self):
        pass


@pytest.mark.parametrize("job_id,ruta,token,trabajo,bandera", [
    pytest.param("subscription_lifecycle", "/api/billing/run-cron", "BILLING_CRON_TOKEN",
                 "_run_subscription_lifecycle_job", "ciclo_de_vida", id="ciclo-de-vida-03:30"),
    pytest.param("daily_snapshot", "/api/snapshots/run-cron", "SNAPSHOT_CRON_TOKEN",
                 "_run_daily_snapshot_job", "snapshot_diario", id="fotos-02:59"),
])
def test_el_scheduler_no_corre_el_job_mientras_corre_el_del_cron_externo(
        monkeypatch, job_id, ruta, token, trabajo, bandera):
    """Lo que el scheduler REGISTRA (se arma con `_start_scheduler`, como al
    arrancar el servidor) tiene que respetar la misma bandera que el endpoint.
    Antes sólo la miraba el endpoint: las dos puertas corrían el job a la vez."""
    from fastapi.testclient import TestClient
    monkeypatch.setenv(token, "tok-cron")
    sigue = threading.Event()
    corridas = []

    def job_lento(**kw):
        corridas.append(1)
        sigue.wait(10)

    monkeypatch.setattr(main, trabajo, job_lento)
    sched = _SchedulerQueAnota()
    monkeypatch.setattr(main, "_scheduler", sched)
    monkeypatch.setattr(main, "_fci_bootstrap_async", lambda: None)
    main._start_scheduler()
    programado = sched.jobs[job_id]

    http = TestClient(main.app)
    try:
        assert http.get(f"{ruta}?token=tok-cron").json()["status"] == "started"
        fin = time.time() + 3
        while not corridas and time.time() < fin:
            time.sleep(0.01)
        assert corridas == [1]
        # Las 03:30 (o 02:59) llegan con la corrida del cron externo en curso.
        hilo = threading.Thread(target=programado)
        hilo.start()
        hilo.join(2)
        assert not hilo.is_alive(), "el scheduler se quedó corriendo el job en paralelo"
        assert corridas == [1]
    finally:
        sigue.set()
    assert _esperar_que_termine(bandera)
    # Y al revés: con nadie corriendo, el scheduler sí corre.
    programado()
    assert corridas == [1, 1]
    assert bandera not in main._corridas_en_curso


# ─── 5. Mientras se manda, la base queda libre ───────────────────────────────

def test_las_alertas_se_entregan_sin_tener_tomada_la_base(conn, monkeypatch):
    """Cada mail espera su turno con Resend; si mientras tanto el motor tiene
    abierta la transacción de lo que disparó, el resto de la app no puede
    escribir. Antes la entrega corría ANTES del commit."""
    uid = _usuario(conn, "ana", tier="plus")
    conn.execute(
        "INSERT INTO alerts (user_id,kind,symbol,scope,direction,threshold,currency,"
        "baseline,channel,repeat,cooldown_min,armed,active) "
        "VALUES (?,'price_target','AAPL','ticker','above',200,'USD','prev_close',"
        "'email','once',360,1,1)", (uid,))
    conn.commit()
    monkeypatch.setattr(ae, "_prices_for", lambda syms: {"AAPL": 210.0})
    monkeypatch.setattr(ae, "_market_open_now", lambda now: True)
    pudo = []

    def mail(**kw):
        pudo.append(_escribir_desde_otra_conexion())
        return True

    monkeypatch.setattr(emails, "send_alert_email", mail)
    assert ae.evaluate_alerts(conn, only_user=uid)["fired"] == 1
    assert pudo == [True]
    ev = conn.execute("SELECT delivered_email FROM alert_events WHERE user_id=?",
                      (uid,)).fetchall()
    assert [e["delivered_email"] for e in ev] == [1]


def _alerta(conn, uid, sym):
    conn.execute(
        "INSERT INTO alerts (user_id,kind,symbol,scope,direction,threshold,currency,"
        "baseline,channel,repeat,cooldown_min,armed,active) "
        "VALUES (?,'price_target',?,'ticker','above',200,'USD','prev_close',"
        "'email','once',360,1,1)", (uid, sym))
    conn.commit()


def test_entre_una_entrega_de_alertas_y_la_siguiente_la_base_queda_libre(conn, monkeypatch):
    """Con una sola alerta alcanza el commit de antes de entregar; con dos, la
    segunda se entregaba con la anotación de la primera abierta."""
    for n, sym in (("ana", "AAPL"), ("beto", "MSFT")):
        _alerta(conn, _usuario(conn, n, tier="plus"), sym)
    monkeypatch.setattr(ae, "_prices_for", lambda syms: {s: 210.0 for s in syms})
    monkeypatch.setattr(ae, "_market_open_now", lambda now: True)
    pudo = []
    monkeypatch.setattr(emails, "send_alert_email",
                        lambda **kw: (pudo.append(_escribir_desde_otra_conexion()), True)[1])
    assert ae.evaluate_alerts(conn)["fired"] == 2
    assert pudo == [True, True]


def test_si_no_se_puede_anotar_una_entrega_las_demas_alertas_salen_igual(conn, monkeypatch):
    """Otro escritor de la app (un import largo) tiene la base tomada más que
    el busy_timeout justo cuando se anota la primera entrega. Antes el error
    cortaba la entrega de las que faltaban — ya registradas como disparadas,
    no se reintentan nunca."""
    uids = [_usuario(conn, n, tier="plus") for n in ("ana", "beto")]
    for u, sym in zip(uids, ("AAPL", "MSFT")):
        _alerta(conn, u, sym)
    monkeypatch.setattr(ae, "_prices_for", lambda syms: {s: 210.0 for s in syms})
    monkeypatch.setattr(ae, "_market_open_now", lambda now: True)
    conn.execute("PRAGMA busy_timeout=300")   # en producción son 15 s
    otro = {}
    mandados = []

    def mail(**kw):
        mandados.append(kw["to"])
        if "c" not in otro:
            otro["c"] = sqlite3.connect(main.DB_PATH, timeout=1)
            otro["c"].execute("BEGIN IMMEDIATE")       # toma la base y no la suelta…
        else:
            otro["c"].rollback()                       # …hasta el segundo mail
        return True

    monkeypatch.setattr(emails, "send_alert_email", mail)
    try:
        assert ae.evaluate_alerts(conn)["fired"] == 2
    finally:
        if "c" in otro:
            otro["c"].close()
    assert sorted(mandados) == sorted(f"{n}@{DOMINIO}" for n in ("ana", "beto"))


def test_el_brief_del_asesor_se_manda_sin_tener_tomada_la_base(conn, monkeypatch):
    """Armar el brief persiste los precios que trajo (`persist_last_prices`):
    la transacción quedaba abierta durante el envío."""
    from snapshots_job import persist_last_prices
    uid = _usuario(conn, "asesora", tier="advisor")

    def armar(c, u, kind, price_cache=None, market_ctx=None):
        persist_last_prices(c, {"GGAL.BA": 6500.0})       # el escritor real
        return {"sections": [{"title": "Tu libro hoy", "items": []}]}

    pudo = []

    def mail(**kw):
        pudo.append(_escribir_desde_otra_conexion())
        return True

    monkeypatch.setattr(advisor_brief, "build_brief", armar)
    monkeypatch.setattr(emails, "send_advisor_brief", mail)
    res = advisor_brief.run_briefs("close", main.get_db, only_uid=uid)
    assert res["sent"] == 1
    assert pudo == [True]


def test_un_brief_salteado_no_deja_la_base_tomada_para_el_siguiente(conn, monkeypatch):
    """Armar persiste precios. Si ese asesor se salteaba (brief vacío), la
    escritura quedaba abierta mientras se armaba el siguiente, que sale a
    internet a buscar precios."""
    from snapshots_job import persist_last_prices
    u1 = _usuario(conn, "asesora1", tier="advisor")
    u2 = _usuario(conn, "asesora2", tier="advisor")
    pudo = []

    def armar(c, u, kind, price_cache=None, market_ctx=None):
        if u == u2:
            pudo.append(_escribir_desde_otra_conexion())
        persist_last_prices(c, {"GGAL.BA": 6500.0})
        return {} if u == u1 else {"sections": [{"title": "x", "items": []}]}

    monkeypatch.setattr(advisor_brief, "advisor_uids", lambda c: [u1, u2])
    monkeypatch.setattr(advisor_brief, "build_brief", armar)
    monkeypatch.setattr(emails, "send_advisor_brief", lambda **kw: True)
    res = advisor_brief.run_briefs("close", main.get_db)
    assert res["sent"] == 1 and res["skipped"] == 1
    assert pudo == [True]


# ─── 6. La bandera de "ya está corriendo", en todas las puertas ──────────────

def test_si_el_trabajo_explota_la_bandera_se_suelta():
    """Si no, un solo error dejaba el trabajo contestando "ya está corriendo"
    hasta el próximo reinicio, sin que nadie se enterara."""
    def explota():
        raise RuntimeError("boom")
    assert main._correr_en_fondo("prueba_explota", explota)["status"] == "started"
    assert _esperar_que_termine("prueba_explota")
    assert main._correr_si_esta_libre("prueba_explota", lambda: None) is True
    with pytest.raises(RuntimeError):
        main._correr_si_esta_libre("prueba_explota", explota)
    assert "prueba_explota" not in main._corridas_en_curso


def test_una_corrida_colgada_se_avisa(caplog):
    main._corridas_en_curso["prueba_colgada"] = time.monotonic() - 31 * 60
    try:
        with caplog.at_level("ERROR"):
            assert main._tomar_corrida("prueba_colgada") is False
        assert any("probablemente colgada" in r.getMessage() for r in caplog.records)
    finally:
        main._soltar_corrida("prueba_colgada")


def _puertas():
    """(bandera, cómo pegarle a cada puerta → lo que contesta, el trabajo a
    reemplazar por uno que se queda esperando)."""
    from fastapi.testclient import TestClient
    import market_brief
    http = TestClient(main.app)
    admin_hdr = {}

    def admin():
        if not admin_hdr:
            c = main.get_db()
            try:
                cur = c.execute(
                    "INSERT INTO users (email, password_hash, approved, email_verified, is_admin)"
                    " VALUES (?, 'x', 1, 1, 1)", (f"admin-{time.time_ns()}@rendi.test",))
                c.commit()
                admin_hdr["Authorization"] = f"Bearer {main.create_token(cur.lastrowid)}"
            finally:
                c.close()
        return admin_hdr

    return [
        ("brief_open", lambda: http.get("/api/advisor/brief/run-cron?kind=open&token=tok").json(),
         (advisor_brief, "run_briefs")),
        ("resumen_mercado", lambda: http.get("/api/market-brief/run-cron?token=tok").json(),
         (market_brief, "run_briefs")),
        ("snapshot_diario", lambda: http.post("/api/admin/snapshots/run-now",
                                              headers=admin()).json(),
         (main, "run_daily_snapshot")),
        ("iol_lab", lambda: main._iol_lab_refresh_all(), None),
    ]


@pytest.mark.parametrize("bandera", ["brief_open", "resumen_mercado", "snapshot_diario",
                                     "iol_lab"])
def test_con_una_corrida_en_curso_ninguna_puerta_corre_otra(monkeypatch, bandera):
    for var in ("ADVISOR_BRIEF_TOKEN", "MARKET_BRIEF_TOKEN", "SNAPSHOT_CRON_TOKEN"):
        monkeypatch.setenv(var, "tok")
    monkeypatch.setattr(main, "IOL_LAB_ESPERA_SEG", 0.3)   # espera de verdad, más corta
    monkeypatch.setattr(emails, "send_market_brief_run_admin", lambda **kw: True)
    puerta, trabajo = {b: (p, t) for b, p, t in _puertas()}[bandera]
    corridas = []
    if trabajo:
        monkeypatch.setattr(*trabajo, lambda *a, **kw: corridas.append(1) or {})
    assert main._tomar_corrida(bandera)          # otra puerta la está corriendo
    try:
        assert puerta()["status"] == "already_running"
        assert corridas == []
    finally:
        main._soltar_corrida(bandera)
    r = puerta()                                 # libre: corre
    assert r.get("status") != "already_running"
    if trabajo:
        assert _esperar(lambda: corridas == [1]), corridas
    assert _esperar(lambda: bandera not in main._corridas_en_curso)


def test_el_push_tiene_tiempo_limite(monkeypatch):
    """Sin tope, un servidor de push que no contesta colgaba la corrida de
    alertas para siempre (y quedaba "ya está corriendo" hasta el deploy)."""
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "priv")
    c = main.get_db()
    try:
        uid = c.execute("INSERT INTO users (email, password_hash) VALUES (?, 'x')",
                        (f"push-{time.time_ns()}@{DOMINIO}",)).lastrowid
        c.execute("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) "
                  "VALUES (?, 'https://push.example/x', 'k', 'a')", (uid,))
        c.commit()
    finally:
        c.close()
    llamadas = []
    import pywebpush                     # `_send_push_to_user` lo importa adentro
    monkeypatch.setattr(pywebpush, "webpush", lambda **kw: llamadas.append(kw))
    assert main._send_push_to_user(uid, {"title": "t", "body": "b"}) == 1
    assert llamadas and llamadas[0].get("timeout")


def test_el_aviso_de_vencimiento_no_dice_cero_dias(conn):
    """Con los reintentos, un aviso puede salir con horas por delante: el
    redondeo para abajo decía "vence en 0 días"."""
    uid = _usuario(conn, "vera", tier="plus",
                   credit_active_until=(datetime.utcnow() + timedelta(hours=10)).isoformat())
    conn.execute(
        "INSERT INTO subscriptions (user_id, status, external_reference, period, "
        "amount_ars, created_at) VALUES (?, 'cancelled', ?, 'monthly', 10000, ?)",
        (uid, f"rendi-{uid}-monthly", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    with _red_de_mentira(_Reloj()) as resend:
        assert subs.run_lifecycle_job(conn)["credit_expiring_reminders_sent"] == 1
    (_, asunto, _), = [m for m in resend.mails if m[0] == f"vera@{DOMINIO}"]
    assert "0 días" not in asunto and "1 día" in asunto, asunto


def test_un_dispositivo_lento_no_corta_el_push_a_los_demas(monkeypatch):
    import requests
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "priv")
    c = main.get_db()
    try:
        uid = c.execute("INSERT INTO users (email, password_hash) VALUES (?, 'x')",
                        (f"push2-{time.time_ns()}@{DOMINIO}",)).lastrowid
        for ep in ("https://push.example/lento", "https://push.example/ok"):
            c.execute("INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) "
                      "VALUES (?, ?, 'k', 'a')", (uid, ep))
        c.commit()
    finally:
        c.close()
    import pywebpush

    def push(**kw):
        if kw["subscription_info"]["endpoint"].endswith("lento"):
            raise requests.exceptions.ReadTimeout("no contestó a tiempo")
        return None

    monkeypatch.setattr(pywebpush, "webpush", push)
    assert main._send_push_to_user(uid, {"title": "t", "body": "b"}) == 1


def test_el_boton_de_renovar_de_iol_espera_a_la_renovacion_del_cron(monkeypatch):
    """El botón y el cron renovando el MISMO token a la vez: IOL anula el
    viejo al rotarlo y uno de los dos borraba la credencial como muerta."""
    from fastapi.testclient import TestClient
    renovando = []
    termino_el_cron = threading.Event()
    monkeypatch.setattr(main, "_iol_lab_gate", lambda uid: "x@y.z")
    monkeypatch.setattr(main, "_check_rate_limit", lambda *a, **kw: None)
    monkeypatch.setattr(main, "_iol_lab_refresh_one",
                        lambda c, uid: renovando.append(
                            (termino_el_cron.is_set(), "iol_lab" in main._corridas_en_curso))
                        or {"ok": True})
    monkeypatch.setattr(main, "_iol_lab_watch_info", lambda c, uid: {})

    def cron_termina():
        termino_el_cron.set()
        main._soltar_corrida("iol_lab")

    app = main.app
    app.dependency_overrides[main.get_current_user] = lambda: 1
    try:
        assert main._tomar_corrida("iol_lab")             # el cron está renovando
        threading.Timer(0.3, cron_termina).start()
        r = TestClient(app).post("/api/iol/lab/refresh")
    finally:
        app.dependency_overrides.pop(main.get_current_user, None)
    assert r.status_code == 200, r.text
    # Renovó DESPUÉS de que terminara el cron, y con la bandera tomada por él.
    assert renovando == [(True, True)]
    assert "iol_lab" not in main._corridas_en_curso


def test_si_la_base_no_abre_la_bandera_de_iol_se_suelta(monkeypatch):
    def no_abre():
        raise sqlite3.OperationalError("unable to open database file")
    monkeypatch.setattr(main, "get_db", no_abre)
    with pytest.raises(sqlite3.OperationalError):
        main._iol_lab_refresh_all()
    assert "iol_lab" not in main._corridas_en_curso


def test_al_apagar_se_espera_a_las_corridas_en_curso(monkeypatch):
    """Un deploy a mitad de una corrida: los avisos se marcan antes de salir,
    así que matarla a mitad deja sin mandar lo que faltaba."""
    monkeypatch.setattr(main, "_flush_last_prices_si_toca", lambda forzar=False: 0)
    assert main._tomar_corrida("prueba_apagado")
    threading.Timer(0.4, main._soltar_corrida, args=("prueba_apagado",)).start()
    t0 = time.monotonic()
    main._cerrar_al_apagar()
    assert time.monotonic() - t0 >= 0.35
    assert "prueba_apagado" not in main._corridas_en_curso


@pytest.mark.parametrize("del_medio", [200, 429], ids=["sale", "rechazado"])
def test_un_incierto_suelto_no_frena_la_corrida(conn, del_medio):
    """El freno es por inciertos SEGUIDOS: un ReadTimeout a la mañana y otro a
    la noche no pueden frenar la corrida (ni una campaña del panel)."""
    nombres = ["ana", "beto", "caro", "dani"]
    for n in nombres:
        _en_prueba_hace(conn, _usuario(conn, n), tr.TRIAL_PRO_DAYS - 1)
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[f"ana@{DOMINIO}"] = [httpx.ReadTimeout("x")]
        resend.respuestas[f"beto@{DOMINIO}"] = [del_medio]
        resend.respuestas[f"caro@{DOMINIO}"] = [httpx.ReadTimeout("x")]
        tr.send_due_trial_emails(conn)
    assert len(resend.a(f"dani@{DOMINIO}")) == 1, "frenó con dos inciertos NO seguidos"


def test_la_marca_se_devuelve_al_segundo_intento():
    intentos = []

    def desmarcar(m):
        intentos.append(m)
        if len(intentos) == 1:
            raise sqlite3.OperationalError("database is locked")

    def mandar():
        emails._anotar(emails.NO_SALIO)
        return False

    assert emails.Tanda().mandar("m", mandar, desmarcar, que="t") == emails.NO_SALIO
    assert intentos == ["m", "m"]


def test_la_corrida_colgada_se_mide_desde_que_arranco(caplog, monkeypatch):
    reloj = {"t": 10_000_000.0}                       # un servidor prendido hace meses
    monkeypatch.setattr(main, "_reloj_corridas", lambda: reloj["t"])   # sólo el de las corridas
    try:
        assert main._tomar_corrida("prueba_reloj")
        reloj["t"] += 60
        with caplog.at_level("ERROR"):
            assert main._tomar_corrida("prueba_reloj") is False      # 1 min: no avisa
        assert not any("colgada" in r.getMessage() for r in caplog.records)
        reloj["t"] += 30 * 60
        with caplog.at_level("ERROR"):
            assert main._tomar_corrida("prueba_reloj") is False      # 31 min: avisa
        assert any("colgada" in r.getMessage() for r in caplog.records)
    finally:
        monkeypatch.undo()
        main._soltar_corrida("prueba_reloj")


def test_el_status_del_lab_renueva_con_la_bandera_y_la_suelta(monkeypatch):
    from fastapi.testclient import TestClient
    c = main.get_db()
    try:
        uid = c.execute("INSERT INTO users (email, password_hash, approved, email_verified) "
                        "VALUES (?, 'x', 1, 1)", (f"lab-{time.time_ns()}@{DOMINIO}",)).lastrowid
        c.execute("INSERT INTO user_broker_credentials (user_id, broker, api_key_enc, scope, "
                  "last_sync_at, last_sync_status) VALUES (?, 'iol_lab', 'x', 'read', "
                  "datetime('now','-2 hours'), 'watch:0')", (uid,))
        c.commit()
    finally:
        c.close()
    durante = []
    monkeypatch.setattr(main, "_iol_lab_gate", lambda u: "x@y")
    monkeypatch.setattr(main, "_iol_lab_refresh_one",
                        lambda cn, u: durante.append("iol_lab" in main._corridas_en_curso) or {})
    r = TestClient(main.app).get("/api/iol/lab/status",
                                 headers={"Authorization": f"Bearer {main.create_token(uid)}"})
    assert r.status_code == 200, r.text
    assert durante == [True]
    assert "iol_lab" not in main._corridas_en_curso


def test_la_bienvenida_no_se_reintenta_si_el_credito_ya_no_es_el_de_la_prueba(conn):
    uid = _usuario(conn, "ana")
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[f"ana@{DOMINIO}"] = [429]
        assert tr.start(conn, uid)["ok"]
    conn.execute("UPDATE users SET credit_active_until=? WHERE id=?",
                 ((datetime.utcnow() + timedelta(days=60)).isoformat(), uid))   # pagó / regalo
    conn.commit()
    with _red_de_mentira(_Reloj()) as resend:
        tr.send_due_trial_emails(conn)
    assert resend.a(f"ana@{DOMINIO}") == []


def test_con_resend_caido_tampoco_sigue_el_aviso_de_suscripcion_cancelada(conn):
    for n in ("ana", "beto"):
        _en_prueba_hace(conn, _usuario(conn, n), tr.TRIAL_PRO_DAYS - 1)
    uid = _con_suscripcion_cancelada_por_vencer(conn)
    caido = httpx.ReadTimeout("caído")
    with _red_de_mentira(_Reloj()) as resend:
        for n in ("ana", "beto", "vera"):
            resend.respuestas[f"{n}@{DOMINIO}"] = [caido]
        r = subs.run_lifecycle_job(conn)
    assert r["avisos_frenados"] is True
    assert resend.a(f"vera@{DOMINIO}") == []
    assert conn.execute("SELECT expiration_reminder_sent_at m FROM subscriptions "
                        "WHERE user_id=?", (uid,)).fetchone()["m"] is None


def test_un_brief_que_explota_no_deja_la_base_tomada_para_el_siguiente(conn, monkeypatch):
    from snapshots_job import persist_last_prices
    u1 = _usuario(conn, "asesora1", tier="advisor")
    u2 = _usuario(conn, "asesora2", tier="advisor")
    pudo = []

    def armar(c, u, kind, price_cache=None, market_ctx=None):
        if u == u2:
            pudo.append(_escribir_desde_otra_conexion())
            return {"sections": [{"title": "x", "items": []}]}
        persist_last_prices(c, {"GGAL.BA": 6500.0})
        raise RuntimeError("se cayó armando el brief")

    monkeypatch.setattr(advisor_brief, "advisor_uids", lambda c: [u1, u2])
    monkeypatch.setattr(advisor_brief, "build_brief", armar)
    monkeypatch.setattr(emails, "send_advisor_brief", lambda **kw: True)
    res = advisor_brief.run_briefs("close", main.get_db)
    assert res["failed"] == 1 and res["sent"] == 1
    assert pudo == [True]


def test_si_las_alertas_de_precio_explotan_no_se_confirma_lo_que_quedo_a_medias(monkeypatch):
    """Las alertas del libro usan la misma conexión: su primer commit
    confirmaba alertas disparadas a medias por el motor que explotó."""
    import advisor_alerts
    c = main.get_db()
    try:
        uid = c.execute("INSERT INTO users (email, password_hash, tier) VALUES (?, 'x', 'plus')",
                        (f"alerta-{time.time_ns()}@{DOMINIO}",)).lastrowid
        # Un asesor con alertas del libro activas: su motor confirma al
        # arrancar (purge + commit), y ese commit es el que se llevaba lo de
        # las alertas de precio.
        asesor = c.execute("INSERT INTO users (email, password_hash, tier) VALUES (?, 'x', 'advisor')",
                           (f"asesor-{time.time_ns()}@{DOMINIO}",)).lastrowid
        c.commit()
        advisor_alerts.set_config(c, asesor, up_pct=5, down_pct=5, active=True)
        c.commit()
    finally:
        c.close()

    def explota(conn, only_user=None):
        conn.execute("INSERT INTO alert_events (alert_id, user_id, symbol, fired_at, price, "
                     "message, delivered_push, delivered_email) VALUES (0, ?, 'X', '2026', 1, "
                     "'a medias', 0, 0)", (uid,))
        raise RuntimeError("se cayó a mitad")

    monkeypatch.setattr(ae, "evaluate_alerts", explota)
    main._evaluar_alertas_job()
    c = main.get_db()
    try:
        assert c.execute("SELECT COUNT(*) n FROM alert_events WHERE user_id=?",
                         (uid,)).fetchone()["n"] == 0
    finally:
        c.close()


def test_las_renovaciones_del_lab_esperan_a_la_de_un_tester(monkeypatch):
    """Si un tester está renovando su token (botón o /status, ~1 s), la
    corrida del cron espera en vez de saltear a TODOS hasta la hora siguiente."""
    monkeypatch.setattr(main, "IOL_LAB_ESPERA_SEG", 3)
    assert main._tomar_corrida("iol_lab")
    threading.Timer(0.3, main._soltar_corrida, args=("iol_lab",)).start()
    r = main._iol_lab_refresh_all()
    assert r.get("status") != "already_running", r
    assert "iol_lab" not in main._corridas_en_curso


# ─── Auditoría 3 ─────────────────────────────────────────────────────────────

# ─── P05: el guard "el crédito vigente ES el de la prueba" del fin de Pro ────

@pytest.mark.parametrize("como", ["pago", "regalo"])
def test_fin_de_pro_no_le_llega_a_quien_tiene_pro_por_otra_via(conn, como):
    """Arrancó la prueba y después pagó Pro (o se lo regalaron): el crédito ya
    no es el de la prueba y el día 9 NO puede recibir "mañana terminan tus días
    de Pro". La consulta nueva (por día + tier='pro') conserva el guard, pero
    ningún test lo pinchaba: sacarlo pasaba en verde."""
    uid = _usuario(conn, "ana")
    _en_prueba_hace(conn, uid, tr.TRIAL_PRO_DAYS - 1)
    conn.execute("UPDATE users SET credit_active_until=? WHERE id=?",
                 ((datetime.utcnow() + timedelta(days=40)).isoformat(), uid))
    if como == "pago":
        conn.execute(
            "INSERT INTO subscriptions (user_id, status, external_reference, period, "
            "amount_ars, created_at) VALUES (?, 'authorized', ?, 'monthly', 10000, ?)",
            (uid, f"rendi-{uid}-monthly", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    with _red_de_mentira(_Reloj()) as resend:
        subs.run_lifecycle_job(conn)
    assert resend.a(f"ana@{DOMINIO}") == [], resend.mails
    assert uid not in {r["user_id"] for r in conn.execute(
        "SELECT user_id FROM trial_email_log WHERE kind=?", (tr.MAIL_PRO_ENDING,))}


# ─── D04: "vence en 0 días" en el aviso de suscripción cancelada ─────────────

def test_la_sub_cancelada_que_vence_mañana_no_dice_cero_dias(conn):
    """Canceló el día antes de la renovación: `current_period_end` es una FECHA
    (medianoche UTC de mañana), así que faltan menos de 24 h y el redondeo
    para abajo decía «vence en 0 días» en el PRIMER envío, sin reintento de por
    medio. El arreglo de HEAD (`_dias_que_quedan`) cubre este camino, pero el
    único test (`..._no_dice_cero_dias`) mira el aviso de fin de crédito."""
    uid = _usuario(conn, "vera", tier="pro")
    mañana = (datetime.utcnow() + timedelta(days=1)).date().isoformat()
    conn.execute(
        "INSERT INTO subscriptions (user_id, mp_subscription_id, status, external_reference, "
        "period, amount_ars, current_period_end) VALUES (?, 'sub-vera', 'cancelled', ?, "
        "'monthly', 10000, ?)", (uid, f"rendi-{uid}-monthly", mañana))
    conn.commit()
    with _red_de_mentira(_Reloj()) as resend:
        assert subs.run_lifecycle_job(conn)["expiration_reminders_sent"] == 1
    (_, asunto, _), = [m for m in resend.mails if m[0] == f"vera@{DOMINIO}"]
    assert "0 días" not in asunto and "1 día" in asunto, asunto


# ─── P07 / V02 / V05: el "día" es el día UTC, a CUALQUIER hora ───────────────

class _Fijo(datetime):
    """El `datetime` que ve billing/trial.py, con la hora congelada."""
    AHORA: datetime = None

    @classmethod
    def utcnow(cls):
        return cls.AHORA

    @classmethod
    def now(cls, tz=None):
        return cls.AHORA - timedelta(hours=3)


@pytest.mark.parametrize("hora_utc", [1, 12, 23])
def test_fin_de_pro_sale_el_dia_utc_anterior_al_paso_a_plus_a_cualquier_hora(
        conn, monkeypatch, hora_utc):
    """El diferencial de test_feedback_prueba arma las edades como "ahora −
    N,x días": según la hora a la que corre la suite, los casos caen en un día
    UTC u otro y el test pierde poder (a las 20:40 de Argentina no ve que la
    ventana se mida por instante, ni que el desde se corra 12 h, ni que el cron
    use el día de Argentina). Acá: hora congelada y arranques en los BORDES de
    cada día (00:00:01 y 23:59:59), por el job entero."""
    hoy = datetime.utcnow().date()
    ahora = datetime.combine(hoy, datetime.min.time()) + timedelta(hours=hora_utc)
    _Fijo.AHORA = ahora
    monkeypatch.setattr(tr, "datetime", _Fijo)
    casos = {}
    for hace in (8, 9, 10):
        for hh, mm, ss in ((0, 0, 1), (23, 59, 59)):
            ini = datetime.combine(hoy - timedelta(days=hace), datetime.min.time()).replace(
                hour=hh, minute=mm, second=ss)
            fin = ini + timedelta(days=tr.TRIAL_TOTAL_DAYS)
            uid = _usuario(conn, f"u{hace}{hh}", tier="pro",
                           trial_started_at=ini.isoformat(), trial_used_at=ini.isoformat(),
                           trial_ends_at=fin.isoformat(), credit_active_until=fin.isoformat())
            casos[uid] = (hace, ini, fin)
    with _red_de_mentira(_Reloj()) as resend:
        subs.run_lifecycle_job(conn)
    for uid, (hace, ini, fin) in casos.items():
        llego = bool(resend.a(f"u{hace}{ini.hour}@{DOMINIO}"))
        desde, hasta = tr.ventanas_de_aviso(ini.isoformat(), fin.isoformat())[tr.MAIL_PRO_ENDING]
        assert llego == (hace == tr.TRIAL_PRO_DAYS - 1), (hora_utc, hace, ini)
        assert llego == (desde <= ahora < hasta), (hora_utc, hace, ini, desde, hasta)


# ─── B02: la bienvenida a quien SÍ tiene plan gratis ────────────────────────

@pytest.mark.parametrize("requires_plan,dice_free", [(0, True), (1, False)])
def test_la_bienvenida_dice_free_solo_a_quien_tiene_free(conn, requires_plan, dice_free):
    """El test de HEAD mira sólo requires_plan=1: forzar requiere_plan=True le
    decía «queda en pausa» a una cuenta vieja que SÍ vuelve a Free."""
    uid = _usuario(conn, "ana", requires_plan=requires_plan)
    with _red_de_mentira(_Reloj()) as resend:
        assert tr.start(conn, uid)["ok"]
    (_, _, texto), = resend.mails
    assert ("vuelve a Free" in texto) is dice_free, texto


# ─── B09: el reintento de la bienvenida también frena con Resend caído ───────

def test_con_resend_caido_las_bienvenidas_reintentadas_tambien_frenan(conn):
    nombres = ["ana", "beto", "caro", "dani"]
    for n in nombres:
        uid = _usuario(conn, n)
        with _red_de_mentira(_Reloj()) as resend:
            resend.respuestas[f"{n}@{DOMINIO}"] = [429]      # la de la activación
            assert tr.start(conn, uid)["ok"]
    caido = httpx.ReadTimeout("Resend no contesta")
    with _red_de_mentira(_Reloj()) as resend:
        for n in nombres:
            resend.respuestas[f"{n}@{DOMINIO}"] = [caido]
        r = subs.run_lifecycle_job(conn)
    assert r["avisos_frenados"] is True
    assert len(resend.pedidos) == emails.INCIERTOS_PARA_FRENAR, resend.pedidos
    # Los que no se intentaron quedan SIN marca: los manda la corrida siguiente.
    marcados = {x["user_id"] for x in conn.execute(
        "SELECT user_id FROM trial_email_log WHERE kind=?", (tr.MAIL_STARTED,))}
    assert len(marcados) == emails.INCIERTOS_PARA_FRENAR


# ─── F03: el panel no espera un aviso que YA salió ───────────────────────────

def test_el_panel_no_espera_un_aviso_que_ya_salio(conn):
    """"Quedan pocos días" salió hace 30 h y su ventana sigue abierta hasta el
    final de la prueba. Si el panel no mirara `avisos_enviados` (nada lo
    pinchaba), lo contaría como pendiente y dejaría a la persona esperando
    hasta que se termine la prueba — o sea, sin el mail de feedback."""
    from fastapi.testclient import TestClient
    admin = conn.execute(
        "INSERT INTO users (email, password_hash, approved, email_verified, is_admin) "
        "VALUES (?, 'x', 1, 1, 1)", (f"admin-{time.time_ns()}@rendi.test",)).lastrowid
    conn.commit()
    uid = _usuario(conn, "ana", requires_plan=1)
    _en_prueba_hace(conn, uid, tr.TRIAL_TOTAL_DAYS - tr.MAIL_AVISO_DIAS_ANTES + 1.25)
    conn.execute("DELETE FROM trial_email_log WHERE user_id=?", (uid,))
    conn.execute("INSERT INTO trial_email_log (user_id, kind, sent_at) VALUES (?,?,?)",
                 (uid, tr.MAIL_ENDING_SOON,
                  (datetime.utcnow() - timedelta(hours=30)).isoformat()))
    conn.commit()
    r = TestClient(main.app).post("/api/admin/email/feedback-prueba",
                                  json={"confirm": False},
                                  headers={"Authorization": f"Bearer {main.create_token(admin)}"})
    assert r.status_code == 200, r.text
    fila, = [f for f in r.json()["nuevos"] if f["id"] == uid]
    assert fila["espera"] is None, fila["espera"]


# ─── L01 / L03: el login de prueba del lab toma la bandera y guarda con ella ─

def test_el_login_de_prueba_del_lab_guarda_el_token_con_la_bandera_tomada(monkeypatch):
    """El token nuevo del login no puede quedar pisado por una renovación del
    cron que arrancó con el viejo: el guardado va con la bandera (espera a
    que la renovación termine). Ningún test la pinchaba."""
    from fastapi.testclient import TestClient
    import iol_api
    durante = {}

    def login(u, p):
        durante["login"] = "iol_lab" in main._corridas_en_curso
        return {"access_token": "AT", "refresh_token": "RT", "expires_in": 900}

    def guardar(uid, keep, rt, tokens):
        durante["guardar"] = "iol_lab" in main._corridas_en_curso
        return 1

    monkeypatch.setattr(main, "_iol_lab_gate", lambda uid: "x@y.z")
    monkeypatch.setattr(main, "_check_rate_limit", lambda *a, **kw: None)
    monkeypatch.setattr(iol_api, "login", login)
    monkeypatch.setattr(main, "_iol_lab_guardar_probe", guardar)
    monkeypatch.setattr(main, "_iol_lab_run_bg", lambda *a, **kw: None)
    main.app.dependency_overrides[main.get_current_user] = lambda: 1
    try:
        r = TestClient(main.app).post("/api/iol/lab/probe",
                                      json={"username": "u", "password": "p", "keep_token": True})
    finally:
        main.app.dependency_overrides.pop(main.get_current_user, None)
        with main._iol_lab_runs_lock:
            main._iol_lab_running.discard(1)
    assert r.status_code == 200, r.text
    # El login con IOL (hasta 30 s) va SIN la bandera —si no, la renovación de
    # la hora salteaba a todos los testers—; el guardado, CON ella.
    assert durante == {"login": False, "guardar": True}
    assert "iol_lab" not in main._corridas_en_curso


# ─── S03 / S04: el apagado espera CON tope y DESPUÉS de bajar los precios ────

def test_al_apagar_la_espera_tiene_tope():
    import threading
    assert main._tomar_corrida("prueba_colgada_apagado")
    try:
        res = []
        t = threading.Thread(target=lambda: res.append(main._esperar_corridas(0.3)),
                             daemon=True)
        t.start()
        t.join(3)
        assert not t.is_alive(), "el apagado espera para siempre a una corrida colgada"
        assert res == [False]
    finally:
        main._soltar_corrida("prueba_colgada_apagado")


def test_al_apagar_los_precios_se_bajan_antes_de_esperar(monkeypatch):
    """Si el apagado se corta (SIGKILL), lo que no se puede perder son los
    últimos precios: van ANTES de la espera a las corridas."""
    import threading
    import time as _t
    orden = []
    monkeypatch.setattr(main, "_flush_last_prices_si_toca",
                        lambda forzar=False: orden.append(("precios", _t.monotonic())) or 0)
    assert main._tomar_corrida("prueba_apagado_orden")
    soltada = []

    def soltar():
        soltada.append(_t.monotonic())
        main._soltar_corrida("prueba_apagado_orden")

    threading.Timer(0.4, soltar).start()
    main._cerrar_al_apagar()
    assert orden and soltada and orden[0][1] < soltada[0], (orden, soltada)


def test_el_ciclo_de_vida_corre_dos_veces_por_dia_y_la_de_la_tarde_es_solo_avisos(monkeypatch):
    """"Mañana termina tu Pro" vale un solo día UTC y la bienvenida rechazada,
    pocas horas: con una sola corrida por día (03:30), un rechazo no tenía
    reintento. La vuelta de las 15:00 corre SÓLO los avisos (con la misma
    bandera): una baja de plan al mediodía le cobraba al plan nuevo la cuota de
    IA usada esa mañana con el viejo."""
    sched = _SchedulerQueAnota()
    with patch.object(main, "_scheduler", sched), \
         patch.object(main, "_fci_bootstrap_async", lambda: None):
        main._start_scheduler()
    corridas = []
    monkeypatch.setattr(main, "_run_subscription_lifecycle_job",
                        lambda **kw: corridas.append(kw.get("solo_avisos", False)))
    sched.jobs["subscription_lifecycle"]()
    sched.jobs["subscription_lifecycle_tarde"]()
    assert corridas == [False, True]


def test_la_vuelta_de_solo_avisos_no_baja_a_nadie(conn):
    """Por el job de verdad: un crédito vencido NO se baja en la vuelta de la
    tarde (sí en la de la madrugada), y los avisos sí salen."""
    vencida = _usuario(conn, "vencida", tier="plus",
                       credit_active_until=(datetime.utcnow() - timedelta(hours=2)).isoformat())
    nueva = _usuario(conn, "nueva")
    _en_prueba_hace(conn, nueva, tr.TRIAL_PRO_DAYS - 1)
    with _red_de_mentira(_Reloj()) as resend:
        r = subs.run_lifecycle_job(conn, solo_avisos=True)
    assert r["credit_expired_downgraded"] == 0 and r["trial_emails_sent"] == 1
    assert conn.execute("SELECT tier FROM users WHERE id=?", (vencida,)).fetchone()["tier"] == "plus"
    with _red_de_mentira(_Reloj()):
        r = subs.run_lifecycle_job(conn)
    assert r["credit_expired_downgraded"] == 1
    assert len(resend.a(f"nueva@{DOMINIO}")) == 1


def test_el_cron_externo_puede_pedir_solo_avisos(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("BILLING_CRON_TOKEN", "tok")
    corridas = []
    monkeypatch.setattr(main, "_run_subscription_lifecycle_job",
                        lambda **kw: corridas.append(kw.get("solo_avisos", False)))
    http = TestClient(main.app)
    assert http.get("/api/billing/run-cron?token=tok&solo_avisos=1").json()["solo_avisos"] is True
    assert _esperar(lambda: corridas == [True])
    assert _esperar_que_termine("ciclo_de_vida")
    assert http.get("/api/billing/run-cron?token=tok").json()["solo_avisos"] is False
    assert _esperar(lambda: corridas == [True, False])
    assert _esperar_que_termine("ciclo_de_vida")


def test_el_apagado_cierra_las_corridas_sin_romper_los_ejecutores_de_los_tests(monkeypatch):
    """`_stop_scheduler` llama a `_cerrar_al_apagar` (lo que prueban los tests
    de arriba). Acá se corre de verdad, con colas descartables: el apagado
    deja las de eventos/Yahoo/noticias sin servicio para siempre, y los tests
    que corrieran después en el mismo proceso fallaban."""
    from concurrent.futures import ThreadPoolExecutor
    colas = [ThreadPoolExecutor(max_workers=1) for _ in range(3)]
    llamadas = []
    monkeypatch.setattr(main, "_cerrar_al_apagar", lambda: llamadas.append(1))
    with patch.object(main, "_events_fetch_executor", colas[0]), \
         patch.object(main, "_yf_executor", colas[1]), \
         patch.object(main, "_news_fetch_executor", colas[2]):
        main._stop_scheduler()
    assert llamadas == [1]

def test_el_dia_del_mail_de_fin_de_pro_la_app_dice_mañana(conn, monkeypatch):
    """El mail sale a las 00:30 ART del día anterior al paso a Plus; la app
    contaba "10 días exactos desde la hora del botón" y ese día decía "2 días
    más" hasta la hora en que la persona había activado."""
    hoy = datetime.utcnow().date()
    ini = datetime.combine(hoy - timedelta(days=tr.TRIAL_PRO_DAYS - 1),
                           datetime.min.time()).replace(hour=15)        # 12:00 ART
    fin = ini + timedelta(days=tr.TRIAL_TOTAL_DAYS)
    uid = _usuario(conn, "ana", tier="pro", trial_started_at=ini.isoformat(),
                   trial_used_at=ini.isoformat(), trial_ends_at=fin.isoformat(),
                   credit_active_until=fin.isoformat())
    monkeypatch.setattr(tr, "datetime", _Fijo)
    _Fijo.AHORA = datetime.combine(hoy, datetime.min.time()).replace(hour=3, minute=30)
    with _red_de_mentira(_Reloj()) as resend:
        subs.run_lifecycle_job(conn)
    assert len(resend.a(f"ana@{DOMINIO}")) == 1                         # el mail salió
    for hora in (3, 10, 14, 16, 23):
        _Fijo.AHORA = datetime.combine(hoy, datetime.min.time()).replace(hour=hora, minute=45)
        st = tr.status(conn, uid)
        assert (st["stage"], st["days_to_switch"]) == ("pro", 1), (hora, st)


def test_al_apagar_se_vuelven_a_bajar_los_precios_despues_de_esperar(monkeypatch):
    """Las corridas que terminan durante la espera traen precios: se bajan
    otra vez al final."""
    bajadas = []
    monkeypatch.setattr(main, "_flush_last_prices_si_toca",
                        lambda forzar=False: bajadas.append(time.monotonic()) or 0)
    assert main._tomar_corrida("prueba_apagado_precios")
    soltada = []

    def soltar():
        soltada.append(time.monotonic())
        main._soltar_corrida("prueba_apagado_precios")

    threading.Timer(0.3, soltar).start()
    main._cerrar_al_apagar()
    assert len(bajadas) == 2 and bajadas[0] < soltada[0] < bajadas[1], (bajadas, soltada)


# ─── Auditoría 4 ─────────────────────────────────────────────────────────────

def test_dos_caminos_al_mismo_vencimiento_mandan_un_solo_aviso(conn):
    """Canceló su suscripción (vence en 2 días) y después abrió un pago que no
    terminó: el aviso de suscripción cancelada y el de fin de crédito cubren el
    MISMO vencimiento. Salían los dos en la misma corrida."""
    hasta = datetime.utcnow() + timedelta(days=2)
    uid = _usuario(conn, "vera", tier="plus", credit_active_until=hasta.isoformat())
    conn.execute(
        "INSERT INTO subscriptions (user_id, mp_subscription_id, status, external_reference, "
        "period, amount_ars, current_period_end, created_at) VALUES (?, 'sub-vieja', "
        "'cancelled', ?, 'monthly', 10000, ?, ?)",
        (uid, f"rendi-{uid}-a", hasta.date().isoformat(),
         (datetime.utcnow() - timedelta(days=28)).strftime("%Y-%m-%d %H:%M:%S")))
    conn.execute(
        "INSERT INTO subscriptions (user_id, mp_subscription_id, status, external_reference, "
        "period, amount_ars, created_at) VALUES (?, 'sub-nueva', 'pending', ?, 'monthly', "
        "10000, ?)", (uid, f"rendi-{uid}-b", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    with _red_de_mentira(_Reloj()) as resend:
        subs.run_lifecycle_job(conn)
        subs.run_lifecycle_job(conn, solo_avisos=True)
    assert len(resend.a(f"vera@{DOMINIO}")) == 1, resend.mails


def test_quien_recibio_un_aviso_hace_meses_recibe_el_del_vencimiento_nuevo(conn):
    """El aviso de fin de crédito miraba si la persona había recibido uno
    ALGUNA VEZ: a quien renovaba (o recibía un regalo) y volvía a vencer meses
    después no le llegaba nunca más."""
    uid = _con_credito_por_vencer(conn)
    conn.execute("UPDATE subscriptions SET expiration_reminder_sent_at=? WHERE user_id=?",
                 ((datetime.utcnow() - timedelta(days=120)).strftime("%Y-%m-%d %H:%M:%S"), uid))
    conn.commit()
    with _red_de_mentira(_Reloj()) as resend:
        assert subs.run_lifecycle_job(conn)["credit_expiring_reminders_sent"] == 1
        assert subs.run_lifecycle_job(conn)["credit_expiring_reminders_sent"] == 0
    assert len(resend.a(f"vera@{DOMINIO}")) == 1


def test_si_el_aviso_nuevo_no_sale_vuelve_la_marca_vieja(conn):
    uid = _con_credito_por_vencer(conn)
    conn.execute("UPDATE users SET aviso_vencimiento_de='2026-01-15' WHERE id=?", (uid,))
    conn.commit()
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[f"vera@{DOMINIO}"] = [429]
        assert subs.run_lifecycle_job(conn)["credit_expiring_reminders_sent"] == 0
    assert conn.execute("SELECT aviso_vencimiento_de m FROM users WHERE id=?",
                        (uid,)).fetchone()["m"] == "2026-01-15"

def test_a_la_noche_la_app_no_dice_mañana_un_dia_antes(conn, monkeypatch):
    """De 21 a 24 de Argentina el día UTC ya es el siguiente: contando contra
    ese día, la app decía "mañana pasás a Plus" 27 horas antes del cambio."""
    hoy = datetime.utcnow().date()
    ini = datetime.combine(hoy - timedelta(days=tr.TRIAL_PRO_DAYS - 2),
                           datetime.min.time()).replace(hour=15)
    fin = ini + timedelta(days=tr.TRIAL_TOTAL_DAYS)
    uid = _usuario(conn, "ana", tier="pro", trial_started_at=ini.isoformat(),
                   trial_used_at=ini.isoformat(), trial_ends_at=fin.isoformat(),
                   credit_active_until=fin.isoformat())
    monkeypatch.setattr(tr, "datetime", _Fijo)
    # Hoy a las 21:30 de Argentina (= 00:30 UTC de mañana): el cambio es pasado
    # mañana a las 00:30 de Argentina → faltan 2 días, no 1.
    _Fijo.AHORA = datetime.combine(hoy + timedelta(days=1), datetime.min.time()).replace(
        minute=30)
    assert tr.status(conn, uid)["days_to_switch"] == 2
    # Mañana a las 12:00 de Argentina: ahora sí, "mañana".
    _Fijo.AHORA = datetime.combine(hoy + timedelta(days=1), datetime.min.time()).replace(hour=15)
    assert tr.status(conn, uid)["days_to_switch"] == 1


# ─── La fila de la pausa bajo carga (auditoría 4) ───────────────────────────

def _esperar_al_cartero(segundos=10):
    assert emails.esperar_al_cartero(segundos), "el cartero no terminó"


def test_una_rafaga_de_mails_sueltos_no_congela_la_app_ni_se_saltea_la_fila():
    """Cada mail suelto sale del pedido de una persona, que ocupa un hilo de la
    app. Esperar la fila ADENTRO del pedido dejaba la app sin hilos (80
    "reenviar código": 24 s congelada); saltearla hacía que Resend rechazara
    por ritmo (76 de 80). Con el cartero: cada pedido contesta a lo sumo en
    ESPERA_RESULTADO_SUELTO y los mails salen todos, con su pausa."""
    tope = 0.25
    pausa = 0.1
    tardanzas = []
    with _red_de_mentira(demora=0) as resend, patch.object(emails, "PAUSA_ENTRE_ENVIOS", pausa), \
         patch.object(emails, "ESPERA_RESULTADO_SUELTO", tope):
        def pedido(i):
            t0 = time.monotonic()
            assert emails.send_alert_email(to=f"p{i}@{DOMINIO}", heading="h", detail="d")
            tardanzas.append(time.monotonic() - t0)
        hilos = [threading.Thread(target=pedido, args=(i,)) for i in range(20)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(10)
        _esperar_al_cartero()
    assert len(tardanzas) == 20
    assert max(tardanzas) < tope + 0.2, sorted(tardanzas)[-3:]
    assert len(resend.pedidos) == 20                          # salieron todos
    assert min(_separaciones(resend.horas())) >= pausa * 0.9  # y ninguno se coló


def test_los_envios_masivos_hacen_la_fila_completa():
    with _red_de_mentira(demora=0) as resend, patch.object(emails, "PAUSA_ENTRE_ENVIOS", 0.1):
        def loop(i):
            with emails.envio_masivo():
                emails.send_alert_email(to=f"m{i}@{DOMINIO}", heading="h", detail="d")
        hilos = [threading.Thread(target=loop, args=(i,)) for i in range(6)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(10)
    assert len(resend.pedidos) == 6
    assert min(_separaciones(resend.horas())) >= 0.1 * 0.9


def test_con_el_cartero_ocupado_el_pedido_contesta_y_el_mail_sale_despues():
    """Si al cartero no le llega el turno dentro del tope, el pedido no espera
    más: el mail ya está en la fila (EN_COLA, "va a salir") y sale después."""
    libre = threading.Event()
    with _red_de_mentira(demora=0) as resend, patch.object(emails, "ESPERA_RESULTADO_SUELTO", 0.2):
        post = resend.post

        def post_lento(url, **kw):
            libre.wait(5)                       # Resend tarda en contestar
            return post(url, **kw)

        with patch("httpx.post", post_lento):
            t0 = time.monotonic()
            assert emails.send_alert_email(to=f"ana@{DOMINIO}", heading="h", detail="d") is True
            assert time.monotonic() - t0 < 1
            assert emails.resultado_del_ultimo_envio() == emails.EN_COLA
            assert resend.pedidos == []
            libre.set()
            _esperar_al_cartero()
    assert len(resend.a(f"ana@{DOMINIO}")) == 1


def test_con_todo_tranquilo_el_pedido_recibe_la_respuesta_de_siempre():
    """El cartero no cambia lo que ve quien necesita saber si salió (la
    recomendación, la invitación del asesor): un rechazo sigue siendo un
    rechazo."""
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[f"ana@{DOMINIO}"] = [429]
        assert emails.send_alert_email(to=f"ana@{DOMINIO}", heading="h", detail="d") is False
        assert emails.resultado_del_ultimo_envio() == emails.NO_SALIO
        assert emails.send_alert_email(to=f"beto@{DOMINIO}", heading="h", detail="d") is True
        assert emails.resultado_del_ultimo_envio() == emails.ENVIADO


def test_nadie_duerme_con_la_fila_tomada():
    """Cada uno reserva su turno y espera AFUERA del candado: con el candado
    tomado mientras se dormía, los demás ni siquiera podían pedir turno."""
    reloj = _Reloj()
    tomada = []
    dormir = reloj.sleep

    def sleep_que_mira(s):
        tomada.append(emails._turno.locked())
        dormir(s)

    reloj.sleep = sleep_que_mira
    with _red_de_mentira(reloj):
        for n in ("ana", "beto", "caro"):
            emails.send_alert_email(to=f"{n}@{DOMINIO}", heading="h", detail="d")
    assert tomada and not any(tomada), tomada


def test_los_trabajos_de_fondo_y_el_panel_mandan_en_modo_masivo():
    vistos = []

    def mirar():
        vistos.append(getattr(emails._modo, "masivo", False))

    assert main._correr_en_fondo("prueba_masivo", mirar)["status"] == "started"
    assert _esperar_que_termine("prueba_masivo")
    main._correr_si_esta_libre("prueba_masivo", mirar)
    c = main.get_db()
    try:
        main._envio_masivo(c, [{"id": 1, "email": f"x@{DOMINIO}"}], [1],
                           marcar=lambda t: "m", desmarcar=lambda t, m: None,
                           mandar=lambda t: (mirar(), True)[1], campaña="prueba")
    finally:
        c.close()
    mirar()                                             # y afuera, no
    assert vistos == [True, True, True, False]


# ─── El aviso de vencimiento, uno por persona y con la fecha real (auditoría 5)

def _suscriptora(conn, nombre="vera", *, credito_en_dias=None, tier="plus", **cols):
    hasta = (datetime.utcnow() + timedelta(days=credito_en_dias)).isoformat() \
        if credito_en_dias is not None else None
    return _usuario(conn, nombre, tier=tier, credit_active_until=hasta, **cols)


def _sub(conn, uid, estado, fin_en_dias=None, ref=None):
    fin = (datetime.utcnow() + timedelta(days=fin_en_dias)).date().isoformat() \
        if fin_en_dias is not None else None
    conn.execute(
        "INSERT INTO subscriptions (user_id, mp_subscription_id, status, external_reference, "
        "period, amount_ars, current_period_end, created_at) VALUES (?, ?, ?, ?, 'monthly', "
        "10000, ?, ?)",
        (uid, ref or f"sub-{uid}-{estado}", estado, f"rendi-{uid}-{ref or estado}", fin,
         datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()


def test_quien_pago_en_la_prueba_y_cancela_recibe_un_aviso_con_su_fecha_real(conn):
    """Pagó el día 3 de la prueba: su acceso dura los días de prueba que le
    quedaban + el mes, pero Rebill cobra el mismo día del mes siguiente. El
    aviso de la suscripción cancelada anunciaba la fecha de Rebill (17 días
    antes) y, con el de fin de crédito, le llegaban dos."""
    uid = _suscriptora(conn, credito_en_dias=19)
    _sub(conn, uid, "cancelled", fin_en_dias=2)            # la fecha de Rebill
    vera = f"vera@{DOMINIO}"
    with _red_de_mentira(_Reloj()) as resend:
        subs.run_lifecycle_job(conn)
        assert resend.a(vera) == []                        # todavía no: le quedan 19 días
        # Pasan los días: el crédito vence en 2 (la fecha de Rebill ya pasó).
        nuevo = datetime.utcnow() + timedelta(days=2)
        conn.execute("UPDATE users SET credit_active_until=? WHERE id=?", (nuevo.isoformat(), uid))
        conn.execute("UPDATE subscriptions SET current_period_end=? WHERE user_id=?",
                     ((datetime.utcnow() - timedelta(days=15)).date().isoformat(), uid))
        conn.commit()
        subs.run_lifecycle_job(conn)
        subs.run_lifecycle_job(conn, solo_avisos=True)
    (to, asunto, texto), = [m for m in resend.mails if m[0] == vera]
    assert emails._fmt_date(nuevo.isoformat()) in texto, texto


def test_reactivar_no_deja_un_aviso_de_vencimiento_falso(conn):
    """"Reactivar" crea una suscripción nueva; la vieja queda cancelada con
    su fecha. Le llegaba "vence en N días" a alguien que se renueva solo."""
    uid = _suscriptora(conn, credito_en_dias=2)
    _sub(conn, uid, "cancelled", fin_en_dias=2, ref="vieja")
    _sub(conn, uid, "authorized", ref="nueva")
    with _red_de_mentira(_Reloj()) as resend:
        subs.run_lifecycle_job(conn)
    assert resend.a(f"vera@{DOMINIO}") == []


def test_un_regalo_sin_suscripcion_recibe_su_aviso(conn):
    """El que recibió un regalo no tiene fila en `subscriptions`: no había
    dónde marcar, y el aviso se salteaba (51 de 57 regalos en la foto del 16/08)."""
    _suscriptora(conn, credito_en_dias=2, tier="pro")
    with _red_de_mentira(_Reloj()) as resend:
        subs.run_lifecycle_job(conn)
        subs.run_lifecycle_job(conn, solo_avisos=True)
    assert len(resend.a(f"vera@{DOMINIO}")) == 1


def test_a_quien_ya_perdio_el_acceso_no_le_llega_el_aviso_al_mediodia(conn):
    """Canceló a la mañana de su último día: el acceso ya terminó y la baja
    recién la hace la corrida de la madrugada. La vuelta de las 12:00 le
    mandaba "vence en 0/1 días"."""
    uid = _suscriptora(conn, credito_en_dias=-0.1)
    _sub(conn, uid, "cancelled", fin_en_dias=0)
    with _red_de_mentira(_Reloj()) as resend:
        subs.run_lifecycle_job(conn, solo_avisos=True)
    assert resend.a(f"vera@{DOMINIO}") == []


def test_un_regalo_despues_de_vencer_tiene_su_propio_aviso(conn):
    """Se le avisó un vencimiento, venció, y le regalaron 7 días: el
    vencimiento nuevo se avisa (la guarda de 15 días lo tapaba)."""
    uid = _suscriptora(conn, credito_en_dias=2)
    hace = (datetime.utcnow() - timedelta(days=5)).date().isoformat()
    conn.execute("UPDATE users SET aviso_vencimiento_de=? WHERE id=?", (hace, uid))
    conn.commit()
    with _red_de_mentira(_Reloj()) as resend:
        subs.run_lifecycle_job(conn)
    assert len(resend.a(f"vera@{DOMINIO}")) == 1


def test_el_mismo_vencimiento_en_todas_las_vueltas_es_un_solo_aviso(conn):
    uid = _suscriptora(conn, credito_en_dias=2.5)
    _sub(conn, uid, "cancelled", fin_en_dias=2)
    with _red_de_mentira(_Reloj()) as resend:
        for _ in range(3):
            subs.run_lifecycle_job(conn)
            subs.run_lifecycle_job(conn, solo_avisos=True)
    assert len(resend.a(f"vera@{DOMINIO}")) == 1


def test_el_cartero_nunca_pide_de_verdad_bajo_pytest(monkeypatch):
    """Un mail que quedó en la fila del cartero después de que un test sacara
    sus parches no puede salir a Resend: `_pedir_a_resend` repite la guarda."""
    pedidos = []
    monkeypatch.setattr("httpx.post", lambda *a, **kw: pedidos.append(1))
    monkeypatch.setattr(emails, "_api_key", lambda: "re_de_mentira")
    assert emails._pedir_a_resend({"to": [f"x@{DOMINIO}"]}, f"x@{DOMINIO}", "s") is False
    assert pedidos == []


# ─── Auditoría 5 (los huecos de la suite que encontró la ronda 5) ───────────

# ─── La pausa: después de un rato quieto, una ráfaga igual se separa ─────────

def test_despues_de_un_rato_quieto_una_rafaga_igual_se_separa():
    """La reserva arranca en `max(ahora, último + pausa)`. Sin el `max`, el
    turno de después de un rato quieto queda EN EL PASADO y los mails que
    siguen salen pegados (los tests de arriba arrancan siempre de cero o con un
    solo mail después del rato quieto)."""
    reloj = _Reloj()
    with _red_de_mentira(reloj) as resend:
        emails.send_alert_email(to=f"a@{DOMINIO}", heading="h", detail="d")
        reloj.ahora += 60
        for n in ("b", "c", "d"):
            emails.send_alert_email(to=f"{n}@{DOMINIO}", heading="h", detail="d")
    horas = resend.horas()[1:]
    assert len(horas) == 3
    assert all(s >= PAUSA - 1e-9 for s in _separaciones(horas)), _separaciones(horas)


# ─── envio_masivo anidado ────────────────────────────────────────────────────

def test_un_envio_masivo_anidado_no_apaga_el_de_afuera():
    """Un trabajo de fondo (modo masivo) que adentro usa otro bloque masivo (el
    panel, un helper): al salir del de adentro, el de afuera sigue en fila
    completa; y al salir del de afuera, el hilo vuelve a suelto."""
    with emails.envio_masivo():
        with emails.envio_masivo():
            pass
        assert getattr(emails._modo, "masivo", False) is True
    assert getattr(emails._modo, "masivo", False) is False


# ─── Un solo aviso por vencimiento, A LO LARGO DE LOS DÍAS ───────────────────

def test_los_dos_caminos_en_dias_distintos_mandan_un_solo_aviso(conn, monkeypatch):
    """El aviso de la suscripción cancelada entra a su ventana por FECHA, y el
    de fin de crédito por HORA: los dos caminos al mismo vencimiento caían en
    corridas DISTINTAS. Acá se camina el reloj 5 días con las dos vueltas
    diarias (03:30 completa, 15:00 sólo avisos): un solo aviso."""
    ahora = datetime.utcnow()
    vence = ahora + timedelta(days=5)
    uid = _usuario(conn, "vera", tier="plus", credit_active_until=vence.isoformat())
    conn.execute(
        "INSERT INTO subscriptions (user_id, mp_subscription_id, status, external_reference, "
        "period, amount_ars, current_period_end, created_at) VALUES (?, 'sub-vieja', "
        "'cancelled', ?, 'monthly', 10000, ?, ?)",
        (uid, f"rendi-{uid}-a", vence.isoformat(timespec="seconds"),
         (ahora - timedelta(days=25)).strftime("%Y-%m-%d %H:%M:%S")))
    conn.execute(
        "INSERT INTO subscriptions (user_id, mp_subscription_id, status, external_reference, "
        "period, amount_ars, created_at) VALUES (?, 'sub-nueva', 'pending', ?, 'monthly', "
        "10000, ?)", (uid, f"rendi-{uid}-b", ahora.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()

    class _Reloj5(datetime):
        T = ahora

        @classmethod
        def utcnow(cls):
            return cls.T

    monkeypatch.setattr(subs, "datetime", _Reloj5)
    with _red_de_mentira(_Reloj()) as resend:
        for paso in range(10):              # 03:30 completa, 15:00 sólo avisos, ...
            subs.run_lifecycle_job(conn, solo_avisos=bool(paso % 2))
            _Reloj5.T += timedelta(hours=11.5 if paso % 2 == 0 else 12.5)
    assert len(resend.a(f"vera@{DOMINIO}")) == 1, resend.mails

def test_la_vuelta_de_la_tarde_no_hace_ningun_paso_que_no_sea_un_aviso(conn):
    """El test de la ronda 4 mira sólo la baja por crédito vencido. Acá, cada
    uno de los otros cuatro pasos que NO son avisos, con un caso que la vuelta
    completa sí toca (el control de abajo): la de la tarde no toca ninguno."""
    hace8 = (datetime.utcnow() - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")
    # 1. suscripción cancelada y vencida, sin crédito → _downgrade_expired_cancellations
    cancelada = _usuario(conn, "cancelada", tier="pro")
    conn.execute(
        "INSERT INTO subscriptions (user_id, mp_subscription_id, status, external_reference, "
        "period, amount_ars, current_period_end) VALUES (?, 'sub-c', 'cancelled', ?, "
        "'monthly', 10000, ?)",
        (cancelada, f"rendi-{cancelada}-m",
         (datetime.utcnow() - timedelta(hours=3)).isoformat(timespec="seconds")))
    # 2. pago abierto hace 8 días → _cancel_stale_pending
    pendiente = _usuario(conn, "pendiente")
    conn.execute(
        "INSERT INTO subscriptions (user_id, mp_subscription_id, status, external_reference, "
        "period, amount_ars, created_at, updated_at) VALUES (?, 'sub-p', 'pending', ?, "
        "'monthly', 10000, ?, ?)", (pendiente, f"rendi-{pendiente}-m", hace8, hace8))
    # 3. cuenta sin verificar de hace 8 días → _delete_unverified_accounts
    sin_verificar = _usuario(conn, "sinverificar", email_verified=0, created_at=hace8)
    # 4. prueba que hoy pasa de Pro a Plus → step_down_due_trials
    prueba = _usuario(conn, "prueba")
    assert tr.start(conn, prueba)["ok"]
    row = conn.execute("SELECT trial_started_at, credit_active_until, trial_ends_at "
                       "FROM users WHERE id=?", (prueba,)).fetchone()
    d = timedelta(days=tr.TRIAL_PRO_DAYS)
    conn.execute("UPDATE users SET trial_started_at=?, credit_active_until=?, trial_ends_at=? "
                 "WHERE id=?",
                 ((datetime.fromisoformat(row["trial_started_at"]) - d).isoformat(),
                  (datetime.fromisoformat(row["credit_active_until"]) - d).isoformat(),
                  (datetime.fromisoformat(row["trial_ends_at"]) - d).isoformat(), prueba))
    conn.commit()

    def foto():
        return (
            conn.execute("SELECT tier FROM users WHERE id=?", (cancelada,)).fetchone()["tier"],
            conn.execute("SELECT status FROM subscriptions WHERE mp_subscription_id='sub-p'"
                         ).fetchone()["status"],
            conn.execute("SELECT COUNT(*) c FROM users WHERE id=?", (sin_verificar,)
                         ).fetchone()["c"],
            conn.execute("SELECT tier FROM users WHERE id=?", (prueba,)).fetchone()["tier"],
        )

    antes = foto()
    assert antes == ("pro", "pending", 1, "pro")
    with _red_de_mentira(_Reloj()):
        r = subs.run_lifecycle_job(conn, solo_avisos=True)
    assert foto() == antes, r
    with _red_de_mentira(_Reloj()):
        r = subs.run_lifecycle_job(conn)                        # control: la completa sí
    despues = foto()
    assert despues[0] != "pro" and despues[1] == "cancelled" and despues[2] == 0 \
        and despues[3] == "plus", (despues, r)


# ─── El cron externo: "0" / "false" no es "sí" ──────────────────────────────

@pytest.mark.parametrize("valor,esperado", [("0", False), ("false", False), ("no", False),
                                            ("", False), ("1", True), ("true", True)])
def test_el_cron_externo_solo_avisos_lee_bien_el_valor(monkeypatch, valor, esperado):
    """Quien arme el cron de las 03:30 con `solo_avisos=0` (para dejarlo
    explícito) no puede apagar las bajas de plan."""
    from fastapi.testclient import TestClient
    monkeypatch.setenv("BILLING_CRON_TOKEN", "tok")
    corridas = []
    monkeypatch.setattr(main, "_run_subscription_lifecycle_job",
                        lambda **kw: corridas.append(kw.get("solo_avisos", False)))
    http = TestClient(main.app)
    assert http.get(f"/api/billing/run-cron?token=tok&solo_avisos={valor}"
                    ).json()["solo_avisos"] is esperado
    fin = time.time() + 5
    while not corridas and time.time() < fin:
        time.sleep(0.01)
    fin = time.time() + 5
    while "ciclo_de_vida" in main._corridas_en_curso and time.time() < fin:
        time.sleep(0.02)
    assert corridas == [esperado]


# ─── La vuelta de la tarde respeta la bandera del cron externo ───────────────

def test_la_vuelta_de_la_tarde_no_corre_mientras_corre_el_cron_externo(monkeypatch):
    """Mismo test que el de las 03:30 (`test_el_scheduler_no_corre_el_job_...`),
    para el trabajo de las 15:00: el comentario dice "misma bandera: nunca
    corren a la vez" y nada lo verificaba."""
    from fastapi.testclient import TestClient
    monkeypatch.setenv("BILLING_CRON_TOKEN", "tok-cron")
    sigue = threading.Event()
    corridas = []

    def job_lento(**kw):
        corridas.append(kw.get("solo_avisos", False))
        sigue.wait(10)

    monkeypatch.setattr(main, "_run_subscription_lifecycle_job", job_lento)
    sched = _SchedulerQueAnota()
    monkeypatch.setattr(main, "_scheduler", sched)
    monkeypatch.setattr(main, "_fci_bootstrap_async", lambda: None)
    main._start_scheduler()
    tarde = sched.jobs["subscription_lifecycle_tarde"]
    http = TestClient(main.app)
    try:
        assert http.get("/api/billing/run-cron?token=tok-cron").json()["status"] == "started"
        fin = time.time() + 3
        while not corridas and time.time() < fin:
            time.sleep(0.01)
        assert corridas == [False]
        hilo = threading.Thread(target=tarde)
        hilo.start()
        hilo.join(2)
        assert not hilo.is_alive(), "la vuelta de la tarde corrió en paralelo al cron externo"
        assert corridas == [False]
    finally:
        sigue.set()
    fin = time.time() + 5
    while "ciclo_de_vida" in main._corridas_en_curso and time.time() < fin:
        time.sleep(0.02)
    tarde()
    assert corridas == [False, True]


# ─── "Reciente" no puede tapar el vencimiento del mes siguiente ──────────────

def _credito_por_vencer_con_sub_cancelada(conn, marca_previa=None):
    uid = _usuario(conn, "vera", tier="plus",
                   credit_active_until=(datetime.utcnow() + timedelta(days=2)).isoformat())
    conn.execute(
        "INSERT INTO subscriptions (user_id, status, external_reference, period, amount_ars, "
        "created_at, expiration_reminder_sent_at) VALUES (?, 'cancelled', ?, 'monthly', 10000, ?, ?)",
        (uid, f"rendi-{uid}-monthly", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
         marca_previa))
    conn.commit()
    return uid


def test_quien_recibio_el_aviso_del_mes_pasado_recibe_el_de_este_mes(conn):
    """El test de la ronda 4 usa un aviso de hace 120 días: una ventana de 100
    (o de 60) lo pasa igual y le tapa el aviso a quien paga mes a mes con pagos
    sueltos. El ciclo más corto es un mes: 28 días."""
    hace28 = (datetime.utcnow() - timedelta(days=28)).strftime("%Y-%m-%d %H:%M:%S")
    _credito_por_vencer_con_sub_cancelada(conn, hace28)
    with _red_de_mentira(_Reloj()) as resend:
        assert subs.run_lifecycle_job(conn)["credit_expiring_reminders_sent"] == 1
    assert len(resend.a(f"vera@{DOMINIO}")) == 1


# ─── La vuelta de la tarde reintenta TODOS los avisos ────────────────────────

def test_la_vuelta_de_la_tarde_reintenta_el_aviso_de_fin_de_credito(conn):
    _credito_por_vencer_con_sub_cancelada(conn)
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[f"vera@{DOMINIO}"] = [429]
        assert subs.run_lifecycle_job(conn)["credit_expiring_reminders_sent"] == 0
        r = subs.run_lifecycle_job(conn, solo_avisos=True)
    assert r["credit_expiring_reminders_sent"] == 1


def test_la_vuelta_de_la_tarde_reintenta_el_aviso_de_suscripcion_cancelada(conn):
    uid = _usuario(conn, "vera", tier="pro")
    conn.execute(
        "INSERT INTO subscriptions (user_id, mp_subscription_id, status, external_reference, "
        "period, amount_ars, current_period_end) VALUES (?, 'sub-vera', 'cancelled', ?, "
        "'monthly', 10000, ?)",
        (uid, f"rendi-{uid}-monthly", (datetime.utcnow() + timedelta(days=2)).date().isoformat()))
    conn.commit()
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[f"vera@{DOMINIO}"] = [429]
        assert subs.run_lifecycle_job(conn)["expiration_reminders_sent"] == 0
        r = subs.run_lifecycle_job(conn, solo_avisos=True)
    assert r["expiration_reminders_sent"] == 1


def test_una_bienvenida_que_quedo_en_la_fila_no_se_manda_dos_veces(conn):
    """Activa la prueba durante una ráfaga: el pedido contesta antes de que el
    cartero mande la bienvenida (EN_COLA). La marca queda —va a salir—, y el
    reintento del cron no la manda otra vez."""
    uid = _usuario(conn, "ana")
    libre = threading.Event()
    with _red_de_mentira(demora=0) as resend, \
         patch.object(emails, "ESPERA_RESULTADO_SUELTO", 0.1):
        post = resend.post
        with patch("httpx.post", lambda url, **kw: (libre.wait(5), post(url, **kw))[1]):
            assert tr.start(conn, uid)["ok"]
            assert uid in _marcados(conn, tr.MAIL_STARTED)
            libre.set()
            _esperar_al_cartero()
        tr.send_due_trial_emails(conn)
    assert len(resend.a(f"ana@{DOMINIO}")) == 1


def test_al_apagar_se_espera_al_cartero(monkeypatch):
    """Los mails sueltos que el cartero tiene en la fila salen antes de que
    el proceso termine (con el mismo tope que las corridas)."""
    monkeypatch.setattr(main, "_flush_last_prices_si_toca", lambda forzar=False: 0)
    libre = threading.Event()
    with _red_de_mentira(demora=0) as resend, \
         patch.object(emails, "ESPERA_RESULTADO_SUELTO", 0.05):
        post = resend.post
        with patch("httpx.post", lambda url, **kw: (libre.wait(5), post(url, **kw))[1]):
            emails.send_alert_email(to=f"ana@{DOMINIO}", heading="h", detail="d")
            threading.Timer(0.3, libre.set).start()
            main._cerrar_al_apagar()
            assert resend.a(f"ana@{DOMINIO}"), "el apagado no esperó al cartero"


# ─── El mail de cancelación y la bienvenida de suscripción ──────────────────

def _con_plan_pago(conn, nombre="vera", *, plan="plus", dias=20):
    uid = _usuario(conn, nombre, tier=plan, credit_anchor_plan=plan,
                   credit_active_until=(datetime.utcnow() + timedelta(days=dias)).isoformat())
    _sub(conn, uid, "authorized", ref=f"sub-{nombre}")
    return uid


def _cancelar(uid, proximo_cobro_en_dias=2, barrera=None):
    """El botón "cancelar" de verdad (POST /api/billing/cancel), con Rebill
    de mentira: contesta la fecha del próximo cobro, que es la que Rebill
    devuelve y la que se guarda en current_period_end."""
    from fastapi.testclient import TestClient
    cobro = (datetime.utcnow() + timedelta(days=proximo_cobro_en_dias)).isoformat()

    def rebill_cancela(sub_id):
        if barrera:
            try:
                barrera.wait()
            except threading.BrokenBarrierError:
                pass
        return {"id": sub_id, "status": "cancelled", "nextChargeDate": cobro}

    with patch("billing.rebill.cancel_subscription", rebill_cancela):
        return TestClient(main.app).post(
            "/api/billing/cancel", headers={"Authorization": f"Bearer {main.create_token(uid)}"})


def test_cancelar_manda_un_mail_con_el_plan_y_la_fecha_reales(conn):
    """Decía siempre "Rendi Pro" (a quien cancelaba Plus) y la fecha del
    próximo cobro de Rebill, no la del fin real del acceso (el crédito)."""
    uid = _con_plan_pago(conn, plan="plus", dias=20)
    hasta = conn.execute("SELECT credit_active_until c FROM users WHERE id=?", (uid,)).fetchone()["c"]
    with _red_de_mentira(_Reloj()) as resend:
        assert _cancelar(uid).status_code == 200
    (to, asunto, texto), = [m for m in resend.mails if m[0] == f"vera@{DOMINIO}"]
    assert "Plus" in asunto and "Pro" not in asunto, asunto
    assert emails._fmt_date(hasta) in texto, texto


def test_un_doble_click_en_cancelar_manda_un_solo_mail(conn):
    """Los dos pedidos pasaban el "¿ya lo mandé?" antes de que el primero
    anotara. La marca se gana ANTES de mandar, con condición."""
    uid = _con_plan_pago(conn)
    # Dos cruces forzados: los dos pedidos pasan juntos por Rebill (si no, el
    # segundo ya ve la baja y contesta 409) y llegan juntos a mandar el mail
    # (con el código de antes, los dos ya habían pasado el "¿ya lo mandé?").
    en_rebill = threading.Barrier(2, timeout=5)
    al_mandar = threading.Barrier(2, timeout=1)
    real = emails.send_cancellation

    def mandar_cruzados(**kw):
        try:
            al_mandar.wait()
        except threading.BrokenBarrierError:
            pass                                    # con el arreglo, llega uno solo
        return real(**kw)

    with _red_de_mentira(demora=0) as resend, patch.object(emails, "PAUSA_ENTRE_ENVIOS", 0), \
         patch.object(emails, "send_cancellation", mandar_cruzados):
        hilos = [threading.Thread(target=_cancelar, args=(uid,), kwargs={"barrera": en_rebill})
                 for _ in range(2)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(30)
    assert len(resend.a(f"vera@{DOMINIO}")) == 1, resend.mails


def test_una_cancelacion_rechazada_la_manda_el_ciclo_de_vida(conn):
    """Se anotaba aunque Resend la rechazara: no llegaba nunca."""
    uid = _con_plan_pago(conn)
    vera = f"vera@{DOMINIO}"
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[vera] = [429]
        assert _cancelar(uid).status_code == 200            # la baja sale igual
        assert len(resend.a(vera)) == 1
        r = subs.run_lifecycle_job(conn, solo_avisos=True)
        assert r["cancellation_emails_sent"] == 1
        subs.run_lifecycle_job(conn)                        # y nunca más
    assert len(resend.a(vera)) == 2


def test_una_baja_por_falta_de_pago_no_recibe_cancelacion_confirmada(conn):
    """Rebill da de baja por cobro fallido ("defaulted"): "cancelaste, no te
    cobramos más" sería falso, aunque le queden días de crédito."""
    uid = _con_plan_pago(conn, dias=5)
    main._rebill_cancel(conn, uid, "sub-vera", {"status": "defaulted"})
    with _red_de_mentira(_Reloj()) as resend:
        subs.run_lifecycle_job(conn)
    assert not any("Cancelación" in a for _, a, _ in resend.mails), resend.mails


def test_un_alta_que_nunca_se_pago_no_recibe_cancelacion_confirmada(conn):
    """Quien está en la prueba (con crédito) abrió el pago y no lo terminó: a
    los 7 días la limpieza deja esa suscripción 'cancelled'. No canceló nada."""
    uid = _usuario(conn, "vera", tier="pro", credit_anchor_plan="pro",
                   credit_active_until=(datetime.utcnow() + timedelta(days=10)).isoformat())
    _sub(conn, uid, "pending", ref="sub-vera")
    with conn:
        conn.execute("UPDATE subscriptions SET created_at=? WHERE mp_subscription_id='sub-vera'",
                     ((datetime.utcnow() - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S"),))
    with _red_de_mentira(_Reloj()) as resend:
        assert subs.run_lifecycle_job(conn)["stale_pending_cancelled"] == 1
        subs.run_lifecycle_job(conn, solo_avisos=True)
        subs.run_lifecycle_job(conn)
    assert not any("Cancelación" in a for _, a, _ in resend.mails), resend.mails


def test_una_baja_hecha_desde_rebill_no_recibe_la_confirmacion(conn):
    """Decisión: desde Rebill llega igual una baja de la persona que una por
    falta de pago; el reintento sólo cubre las del botón de Rendi."""
    uid = _con_plan_pago(conn, dias=15)
    main._rebill_cancel(conn, uid, "sub-vera", {"status": "cancelled"})
    with _red_de_mentira(_Reloj()) as resend:
        subs.run_lifecycle_job(conn)
    assert not any("Cancelación" in a for _, a, _ in resend.mails), resend.mails


def test_la_cancelacion_rechazada_se_reintenta_solo_unos_dias(conn):
    """Pasados CANCELACION_REINTENTO_DIAS el "Cancelación confirmada" llegaría
    tarde y fuera de contexto: se deja de intentar."""
    uid = _con_plan_pago(conn, dias=40)
    vera = f"vera@{DOMINIO}"
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[vera] = [429]
        assert _cancelar(uid).status_code == 200
        hace = (datetime.utcnow() - timedelta(days=subs.CANCELACION_REINTENTO_DIAS, hours=1))
        with conn:
            conn.execute("UPDATE subscriptions SET cancelacion_pedida_at=? "
                         "WHERE mp_subscription_id='sub-vera'", (hace.strftime("%Y-%m-%d %H:%M:%S"),))
        subs.run_lifecycle_job(conn)
    assert len(resend.a(vera)) == 1                     # sólo el rechazado


def test_si_el_acceso_ya_termino_el_reintento_no_dice_mantenes_el_plan(conn):
    """Canceló el último día y Resend rechazó el mail; para el reintento el
    acceso ya terminó y "mantenés Plus hasta…" sería falso."""
    uid = _con_plan_pago(conn, dias=1)
    vera = f"vera@{DOMINIO}"
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[vera] = [429]
        assert _cancelar(uid).status_code == 200
        with conn:
            conn.execute("UPDATE users SET credit_active_until=? WHERE id=?",
                         ((datetime.utcnow() - timedelta(hours=1)).isoformat(), uid))
        subs.run_lifecycle_job(conn, solo_avisos=True)
    assert len(resend.a(vera)) == 1                     # sólo el rechazado


def test_quien_cancelo_y_volvio_a_suscribirse_no_recibe_la_confirmacion(conn):
    """Canceló y, antes del reintento, se volvió a suscribir: "cancelaste"
    ya no es cierto."""
    uid = _con_plan_pago(conn, dias=15)
    vera = f"vera@{DOMINIO}"
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[vera] = [429]
        assert _cancelar(uid).status_code == 200
        _sub(conn, uid, "authorized", ref="sub-vera-2")
        subs.run_lifecycle_job(conn)
    assert len(resend.a(vera)) == 1                     # sólo el rechazado


def test_el_vence_en_n_dias_no_sale_pegado_a_la_cancelacion(conn):
    """Canceló con 2 días por delante: "Cancelación confirmada… hasta el X" y,
    horas después, "vence en 2 días". Uno alcanza."""
    uid = _con_plan_pago(conn, dias=2)
    with _red_de_mentira(_Reloj()) as resend:
        assert _cancelar(uid).status_code == 200
        subs.run_lifecycle_job(conn)
        subs.run_lifecycle_job(conn, solo_avisos=True)
    asuntos = [a for to, a, _ in resend.mails if to == f"vera@{DOMINIO}"]
    assert asuntos == ["Cancelación confirmada · Rendi Plus"], asuntos


def test_la_bienvenida_de_suscripcion_re_entregada_sale_una_vez(conn):
    """Rebill re-entrega `subscription.created`: dos entregas a la vez
    pasaban el "¿ya la mandé?" y llegaban dos bienvenidas."""
    from billing import plan_textos
    uid = _con_plan_pago(conn)
    with _red_de_mentira(demora=0) as resend, patch.object(emails, "PAUSA_ENTRE_ENVIOS", 0):
        def entrega(c):
            main._maybe_send_welcome_email(c, "sub-vera", uid, "monthly", {}, plan="plus")
        _dos_corridas_a_la_vez(entrega, "cupos_del_usuario", plan_textos)
    assert len(resend.a(f"vera@{DOMINIO}")) == 1


def test_una_bienvenida_rechazada_no_queda_anotada(conn):
    uid = _con_plan_pago(conn)
    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[f"vera@{DOMINIO}"] = [429]
        main._maybe_send_welcome_email(conn, "sub-vera", uid, "monthly", {}, plan="plus")
        main._maybe_send_welcome_email(conn, "sub-vera", uid, "monthly", {}, plan="plus")
    assert len(resend.a(f"vera@{DOMINIO}")) == 2       # la re-entrega la manda
    assert conn.execute("SELECT welcome_email_sent_at m FROM subscriptions WHERE "
                        "mp_subscription_id='sub-vera'").fetchone()["m"]
