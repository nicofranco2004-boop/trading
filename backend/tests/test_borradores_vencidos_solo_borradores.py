"""Las dos limpiezas de borradores vencidos borran SÓLO borradores, en los dos motores.

La vista previa borra los borradores vencidos de SU cuenta (`cleanup_stale_previews`)
y el reloj de cada hora los de todas (`barrer_borradores_vencidos`); ver
test_vista_previa_no_espera_a_otra_cuenta.py por qué se separaron.

🔴 POR QUÉ ESTE ARCHIVO. Un revisor que no vio las pruebas plantó errores en ese
arreglo (sesión «tope a las esperas», 07/11/2026) y uno pasaba todo: sacar
`status='preview'` del barrido. Eso borra, cada hora, TODAS las importaciones
confirmadas de más de una hora de todas las cuentas — y en cascada sus filas. El
código estaba bien; lo que no había era una prueba que lo exigiera. Acá cada borde:
  · lo confirmado no se toca, ni por la vista previa ni por el reloj;
  · la vista previa no toca los borradores de OTRA cuenta (ése era el candado);
  · un borrador de menos de una hora no se toca;
  · el reloj corre cada hora (una vez por día dejaba los borradores un día entero).

Corre en SQLite y en Postgres: el barrido tiene una rama por motor.
"""
import io
import os
import tempfile
import uuid
from datetime import datetime, timedelta

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ.setdefault("DB_PATH", _TMP.name)

import openpyxl                              # noqa: E402
from fastapi.testclient import TestClient    # noqa: E402

import main                                  # noqa: E402
from importing import pipeline               # noqa: E402

HDR = ["Liquida", "Operado", "Comprobante", "Numero", "Cantidad",
       "Especie", "Precio", "Importe", "Saldo", "Referencia"]


def _cuenta_corriente(numero):
    """Un Excel de Bull Market distinto por `numero` (no es el mismo archivo dos veces)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cuenta Corriente PESOS 06-11-26"
    ws.append(HDR)
    filas = [
        [datetime(2026, 9, 1), datetime(2026, 9, 1), "RECIBO DE COBRO", 700000 + numero, 0, None, 0, 3000000],
        [datetime(2026, 9, 3), datetime(2026, 9, 3), "COMPRA NORMAL", 800000 + numero, 1 + numero, "AVGO", 14173.7,
         -round(14173.7 * (1 + numero), 2)],
    ]
    saldo = 0.0
    for f in filas:
        saldo += f[7]
        ws.append(list(f) + [round(saldo, 2), None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cuenta():
    conn = main.get_db()
    try:
        uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?, 'x', 1, 1)", (f"borradores-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        conn.commit()
    finally:
        conn.close()
    return uid, {"Authorization": f"Bearer {main.create_token(uid)}"}


_N = [0]


def _vista_previa(h):
    _N[0] += 1
    r = TestClient(main.app).post(
        "/api/imports/preview", headers=h,
        files=[("files", (f"Cuenta Corriente PESOS {_N[0]}.xlsx", io.BytesIO(_cuenta_corriente(_N[0])),
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        data={"format": "bullmarket"})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def _confirmada(h):
    sid = _vista_previa(h)
    r = TestClient(main.app).post("/api/imports/confirm", headers=h, json={"session_id": sid})
    assert r.status_code == 200, r.text
    return sid


def _de_hace(batch_id, minutos):
    """La base guarda la hora al segundo: uno «de recién» y el que se crea después
    caen en el mismo segundo y ningún corte los separa. Por eso se les pone la edad."""
    conn = main.get_db()
    try:
        conn.execute("UPDATE import_batches SET created_at=? WHERE id=?",
                     ((datetime.utcnow() - timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M:%S"),
                      batch_id))
        conn.commit()
    finally:
        conn.close()
    return batch_id


def _de_hace_dos_horas(batch_id):
    return _de_hace(batch_id, 120)


def _estado(batch_id):
    conn = main.get_db()
    try:
        r = conn.execute("SELECT status FROM import_batches WHERE id=?", (batch_id,)).fetchone()
        return r["status"] if r else None
    finally:
        conn.close()


def _barrer():
    conn = main.get_db()
    try:
        return pipeline.barrer_borradores_vencidos(conn)
    finally:
        conn.close()


def test_la_vista_previa_borra_solo_los_borradores_vencidos_de_su_cuenta():
    uid, h = _cuenta()
    _, h_otra = _cuenta()
    confirmada_vieja = _de_hace_dos_horas(_confirmada(h))
    mio_vencido = _de_hace_dos_horas(_vista_previa(h))
    de_otra_vencido = _de_hace_dos_horas(_vista_previa(h_otra))
    mio_fresco = _de_hace(_vista_previa(h), 30)     # otra pestaña, otro archivo

    nuevo = _vista_previa(h)          # corre `cleanup_stale_previews(conn, uid)`

    assert _estado(confirmada_vieja) == "confirmed", "una importación confirmada NO es un borrador"
    assert _estado(mio_vencido) is None, "el borrador vencido de la cuenta se borra"
    assert _estado(mio_fresco) == "preview", "un borrador de menos de una hora no se toca"
    assert _estado(de_otra_vencido) == "preview", (
        "la vista previa no toca los borradores de otra cuenta: eso la hacía esperar "
        "a la importación a medio camino de cualquiera")
    assert _estado(nuevo) == "preview"


def test_el_reloj_de_cada_hora_borra_solo_borradores_vencidos_de_todas():
    _, h_a = _cuenta()
    _, h_b = _cuenta()
    confirmada_vieja = _de_hace_dos_horas(_confirmada(h_a))
    vencido_a = _de_hace_dos_horas(_vista_previa(h_a))
    vencido_b = _de_hace_dos_horas(_vista_previa(h_b))
    fresco = _de_hace(_vista_previa(h_b), 30)

    assert _barrer() >= 2

    assert _estado(confirmada_vieja) == "confirmed", (
        "el reloj borró una importación CONFIRMADA: sin `status='preview'` se lleva "
        "las de todas las cuentas cada hora")
    assert _estado(vencido_a) is None
    assert _estado(vencido_b) is None
    assert _estado(fresco) == "preview", "uno de menos de una hora no se toca"


class _SchedulerQueAnota:
    """Lo que registra `_start_scheduler`, sin arrancar nada (como en test_ritmo_de_envio)."""

    def __init__(self):
        self.jobs = {}

    def add_job(self, func, trigger, id, replace_existing=True):
        self.jobs[id] = (func, trigger)

    def start(self):
        pass


def test_el_reloj_corre_cada_hora(monkeypatch):
    sched = _SchedulerQueAnota()
    monkeypatch.setattr(main, "_scheduler", sched)
    monkeypatch.setattr(main, "_fci_bootstrap_async", lambda: None)
    main._start_scheduler()
    func, trigger = sched.jobs["borradores_vencidos"]
    assert func is main._job_borradores_vencidos
    campos = {f.name: str(f) for f in trigger.fields}
    assert (campos["hour"], campos["minute"]) == ("*", "23"), campos
