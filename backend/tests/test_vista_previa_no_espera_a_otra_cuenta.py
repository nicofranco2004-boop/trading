"""La vista previa de una cuenta no espera a la importación a medio camino de otra.

Caso real (2026-11-06, Matias, Bull Market): «Generar vista previa» quedó girando
y nunca llegó a la vista previa. El archivo no era: los mismos dos archivos, en
local, hacen el ciclo entero en menos de 3 segundos.

EL MECANISMO, medido contra Postgres por /api/imports/preview:
  · La vista previa, antes de guardar el borrador, borraba los borradores
    vencidos (más de una hora) de TODAS las cuentas (`cleanup_stale_previews`).
  · Si otra cuenta estaba en el medio de su propia vista previa (ya había hecho
    ese mismo borrado y todavía no había terminado), Postgres hace esperar al
    segundo borrado hasta que el primero termine: son las mismas filas.
  · En producción `lock_timeout` vale 0 (el pooler de Supabase se come el ajuste
    del DSN), o sea que esa espera no tiene fin.
  · En SQLite no existía: la primera escritura de cualquiera ya tomaba la base
    entera, y `busy_timeout` la cortaba a los 15 s con un error.

Y la otra espera sin fin, la de la MISMA cuenta: si otro pedido suyo tiene el
turno (`pgsesion.tomar_turno`) y no lo suelta, la vista previa esperaba para
siempre. Ahora espera con tope y contesta qué pasa.

⚠️ POR QUÉ ESTAS PRUEBAS LE SACAN A LA CONEXIÓN LOS RELOJES DE LA SUITE. El
conftest pone `lock_timeout=12s` e `idle_in_transaction_session_timeout=6s` para
que una prueba trabada falle en vez de colgarse. Con ellos puestos el error de
producción NO SE VE: la espera se corta sola a los 12 s, o Postgres mata a la
transacción quieta que tiene el candado a los 6 s y la vista previa sigue. Acá
van en 0, como en producción; si algo vuelve a esperar, el hilo de la prueba se
corta solo a los `_TOPE_S` segundos y la prueba dice cuánto esperó y dónde.

Sólo mide con `DATABASE_URL` puesta (Postgres). Contra SQLite se saltea: el
mecanismo no existe allá, y un verde ahí no diría nada.
"""
import io
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ.setdefault("DB_PATH", _TMP.name)

import openpyxl                              # noqa: E402
import pytest                                # noqa: E402
from fastapi.testclient import TestClient    # noqa: E402

import main                                  # noqa: E402
import pgsesion                              # noqa: E402
import pgshim                                # noqa: E402
from importing import pipeline               # noqa: E402

CON_PG = bool(getattr(main, "USANDO_PG", False))
pytestmark = pytest.mark.skipif(
    not CON_PG, reason="el mecanismo es de Postgres (candados por fila); ver el docstring")

_TOPE_S = 15        # más que esto esperando = colgada (sin el arreglo, para siempre)

HDR = ["Liquida", "Operado", "Comprobante", "Numero", "Cantidad",
       "Especie", "Precio", "Importe", "Saldo", "Referencia"]
FILAS = [
    [datetime(2026, 9, 1), datetime(2026, 9, 1), "RECIBO DE COBRO", 765773, 0, None, 0, 3000000],
    [datetime(2026, 9, 3), datetime(2026, 9, 3), "COMPRA NORMAL", 8188607, 23, "AVGO", 14173.7, -325995.16],
    [datetime(2026, 9, 18), datetime(2026, 9, 18), "COMPRA NORMAL", 8758224, 6, "GS", 118156.13, -708936.79],
]


def _cuenta_corriente():
    """Un Excel como el que baja Bull Market (Cuenta Corriente PESOS)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cuenta Corriente PESOS 06-11-26"
    ws.append(HDR)
    saldo = 0.0
    for f in FILAS:
        saldo += f[7]
        ws.append(list(f) + [round(saldo, 2), None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


XLSX = _cuenta_corriente()


@pytest.fixture(autouse=True)
def como_en_produccion():
    """Las conexiones nuevas, sin los relojes de la suite (ver el docstring)."""
    previos = pgsesion.AJUSTES_DE_SESION
    pgsesion.AJUSTES_DE_SESION = previos + (
        "SET lock_timeout = 0", "SET idle_in_transaction_session_timeout = 0")
    pgshim.cerrar_pozos()
    try:
        yield
    finally:
        pgsesion.AJUSTES_DE_SESION = previos
        pgshim.cerrar_pozos()


def _cuenta(etiqueta):
    conn = main.get_db()
    try:
        uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?, 'x', 1, 1)", (f"{etiqueta}-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        conn.commit()
    finally:
        conn.close()
    return uid, {"Authorization": f"Bearer {main.create_token(uid)}"}


def _vista_previa(h):
    return TestClient(main.app).post(
        "/api/imports/preview", headers=h,
        files=[("files", ("Cuenta Corriente PESOS 06-11-26 (1).xlsx", io.BytesIO(XLSX),
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
        data={"format": "bullmarket"})


def _borrador_vencido_de(uid, h):
    """Una vista previa de verdad que nunca se confirmó, de hace dos horas (los
    de Matias eran de las 16:33 y 16:37 UTC y seguían ahí a las 22:34)."""
    r = _vista_previa(h)
    assert r.status_code == 200, r.text
    conn = main.get_db()
    try:
        conn.execute(
            "UPDATE import_batches SET created_at=? WHERE id=?",
            ((datetime.utcnow() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
             r.json()["session_id"]))
        conn.commit()
    finally:
        conn.close()
    return r.json()["session_id"]


def _existe(batch_id):
    conn = main.get_db()
    try:
        return conn.execute("SELECT 1 FROM import_batches WHERE id=?", (batch_id,)).fetchone() is not None
    finally:
        conn.close()


def _barrer():
    conn = main.get_db()
    try:
        return pipeline.barrer_borradores_vencidos(conn)
    finally:
        conn.close()


def _en_un_hilo(fn):
    out = {}

    def correr():
        t0 = time.perf_counter()
        try:
            out["r"] = fn()
        except Exception as ex:          # que la prueba diga qué pasó, no que se cuelgue
            out["ex"] = repr(ex)
        out["seg"] = time.perf_counter() - t0
    hilo = threading.Thread(target=correr, daemon=True)
    hilo.start()
    return hilo, out


def _que_espera():
    """Lo que dice Postgres de los pedidos que esperan un candado ahora."""
    with pgsesion.conectar(main.DATABASE_URL, autocommit=True) as c:
        return [r[0] for r in c.execute(
            """SELECT left(regexp_replace(query, '\\s+', ' ', 'g'), 90)
                 FROM pg_stat_activity
                WHERE datname = current_database() AND wait_event_type = 'Lock'
                  AND pid <> pg_backend_pid()""").fetchall()]


def _otra_vista_previa_a_medio_camino(uid_otro):
    """La vista previa de OTRA cuenta, por el mismo código que la de producción,
    parada después de escribir y antes de confirmar: lo que dura cualquier vista
    previa mientras inserta sus filas."""
    conn = main.get_db()
    pipeline.run_preview(conn, uid=uid_otro, file_bytes=XLSX,
                         file_name="otra.xlsx", broker_hint=None,
                         parser_format="bullmarket")
    assert conn.in_transaction, "la vista previa de la otra cuenta tiene que quedar abierta"
    return conn


@pytest.mark.parametrize("de_quien_es_el_vencido", ["de una tercera cuenta", "de la misma persona"])
def test_la_vista_previa_no_espera_a_la_de_otra_cuenta(de_quien_es_el_vencido):
    uid, h = _cuenta("matias")
    uid_otro, _ = _cuenta("otra")
    if de_quien_es_el_vencido == "de la misma persona":
        vencido = _borrador_vencido_de(uid, h)
    else:
        vencido = _borrador_vencido_de(*_cuenta("tercera"))

    otra = _otra_vista_previa_a_medio_camino(uid_otro)
    try:
        hilo, out = _en_un_hilo(lambda: _vista_previa(h))
        hilo.join(_TOPE_S)
        esperando = _que_espera() if hilo.is_alive() else []
    finally:
        otra.rollback()
        otra.close()
    hilo.join(30)

    assert not esperando, (
        f"la vista previa de una cuenta se quedó esperando a la de otra más de {_TOPE_S} s "
        f"(en producción, para siempre). Esperaba en: {esperando}")
    r = out.get("r")
    assert r is not None, out.get("ex")
    assert r.status_code == 200, r.text
    assert out["seg"] < 5, f"tardó {out['seg']:.1f} s"
    # El vencido de la misma persona se borra en su propia vista previa; el de
    # otra cuenta lo deja para el barrido de cada hora.
    assert _existe(vencido) == (de_quien_es_el_vencido != "de la misma persona")


def test_el_turno_tomado_de_la_misma_cuenta_contesta_en_vez_de_girar(monkeypatch):
    """Otro pedido de la MISMA persona tiene su turno y no lo suelta (una
    importación suya colgada, por ejemplo). Esa espera es a propósito —dos
    escrituras de la misma cuenta van de a una—, pero no puede ser eterna."""
    # 1 s y no los 10 de producción, para que la prueba no tarde ~30 s: la
    # espera sin fin es la que se mide (sin el tope, el hilo no vuelve nunca);
    # el valor del tope no cambia el mecanismo.
    monkeypatch.setattr(pipeline, "ESPERA_MAX_VISTA_PREVIA_S", 1)
    uid, h = _cuenta("matias")
    colgado = main.get_db()
    pgsesion.tomar_turno(colgado, uid)
    try:
        hilo, out = _en_un_hilo(lambda: _vista_previa(h))
        hilo.join(_TOPE_S)
        esperando = _que_espera() if hilo.is_alive() else []
    finally:
        colgado.rollback()
        colgado.close()
    hilo.join(30)

    assert not esperando, (
        f"con el turno de la cuenta tomado, la vista previa esperó más de {_TOPE_S} s "
        f"(en producción, para siempre). Esperaba en: {esperando}")
    r = out.get("r")
    assert r is not None, out.get("ex")
    assert r.status_code == 409, r.text
    assert "otra operación de tu cuenta en curso" in r.json()["detail"]
    assert "No se guardó nada" in r.json()["detail"]
    conn = main.get_db()
    try:
        n = conn.execute("SELECT COUNT(*) n FROM import_batches WHERE user_id=?", (uid,)).fetchone()["n"]
    finally:
        conn.close()
    assert n == 0, "con el 409 no tiene que quedar ningún borrador a medias"

    # Suelto el turno, la misma vista previa entra.
    r2 = _vista_previa(h)
    assert r2.status_code == 200, r2.text


def test_el_barrido_de_cada_hora_borra_los_de_todos_sin_esperar_a_nadie():
    """Los vencidos de las cuentas que no vuelven los borra el reloj, y no se
    queda esperando a una fila que otro tiene agarrada: la salta."""
    a = _borrador_vencido_de(*_cuenta("a"))
    b = _borrador_vencido_de(*_cuenta("b"))
    fresco = _vista_previa(_cuenta("c")[1]).json()["session_id"]

    agarrado = main.get_db()
    agarrado.execute("SELECT 1 FROM import_batches WHERE id=? FOR UPDATE", (b,))
    try:
        hilo, out = _en_un_hilo(_barrer)
        hilo.join(_TOPE_S)
        assert not hilo.is_alive(), f"el barrido esperó a una fila agarrada: {_que_espera()}"
    finally:
        agarrado.rollback()
        agarrado.close()

    assert "ex" not in out, out.get("ex")
    assert not _existe(a), "el vencido libre se tenía que borrar"
    assert _existe(b), "el agarrado se salta (lo levanta la próxima hora)"
    assert _existe(fresco), "uno de menos de una hora no se toca"
    assert _barrer() >= 1
    assert not _existe(b)
