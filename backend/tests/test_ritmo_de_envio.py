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
lo contesta `_Resend`, y el reloj de `emails` es `_Reloj` (su `sleep` avanza el
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
    for t in ("alert_symbol_state", "alert_events", "alerts", "advisor_brief_log",
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
            for i in range(2):
                emails.send_alert_email(to=f"{quien}{i}@{DOMINIO}", heading="h", detail="d")
        hilos = [threading.Thread(target=loop, args=(q,)) for q in ("ana", "beto")]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(10)
    assert len(resend.pedidos) == 4
    assert min(_separaciones(h for h, _ in resend.pedidos)) >= pausa * 0.6


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
    assert quien_postea == {"_send"}


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

        r2 = subs.run_lifecycle_job(conn)          # la corrida de mañana
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


def test_dos_corridas_a_la_vez_no_duplican_ni_con_reintentos(conn):
    """Dos crons a la vez, cada uno con su conexión: a cada persona le llega
    UN aviso. La marca se gana antes de mandar con un INSERT OR IGNORE."""
    nombres = ["ana", "beto", "caro", "dani"]
    for n in nombres:
        _en_prueba_hace(conn, _usuario(conn, n), tr.TRIAL_PRO_DAYS - 1)
    with _red_de_mentira(demora=0) as resend, patch.object(emails, "PAUSA_ENTRE_ENVIOS", 0.01):
        def corrida():
            c = main.get_db()
            try:
                tr.send_due_trial_emails(c)
            finally:
                c.close()
        hilos = [threading.Thread(target=corrida) for _ in range(2)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(30)
    for n in nombres:
        assert len(resend.a(f"{n}@{DOMINIO}")) == 1, n


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
        return conn.execute(
            "SELECT COUNT(*) n FROM subscriptions WHERE user_id=? "
            "AND expiration_reminder_sent_at IS NOT NULL", (uid,)).fetchone()["n"]

    with _red_de_mentira(_Reloj()) as resend:
        resend.respuestas[vera] = [429]
        r1 = subs.run_lifecycle_job(conn)
        assert r1[contador] == 0 and marcado() == 0
        r2 = subs.run_lifecycle_job(conn)
        assert r2[contador] == 1 and marcado() == 1
        r3 = subs.run_lifecycle_job(conn)
        assert r3[contador] == 0
    assert len(resend.a(vera)) == 2          # el rechazado y el que salió; nunca un tercero


def test_los_avisos_al_admin_de_las_bajas_salen_con_pausa():
    reloj = _Reloj()
    with _red_de_mentira(reloj) as resend:
        subs._notify_admin_downgrades(
            [(f"ana@{DOMINIO}", "pro"), (f"beto@{DOMINIO}", "plus"),
             (f"caro@{DOMINIO}", "pro")], "credit_expired")
    assert len(resend.pedidos) == 3
    assert all(s >= PAUSA - 1e-9 for s in _separaciones(h for h, _ in resend.pedidos))


# ─── 4. Alertas en segundo plano; una corrida a la vez ───────────────────────

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

    def job_lento():
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
