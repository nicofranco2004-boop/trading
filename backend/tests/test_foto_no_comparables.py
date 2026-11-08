"""Lo que NO se puede comparar contra la foto no se toca — tampoco «completándolo».

Revisión del 2026-11-08 (dos rondas independientes, casos corridos por
/api/imports/preview → /confirm → /api/imports/tenencia/preview → /confirm):
`proyectar` deja afuera de su lista los activos que no puede llevar a la fecha
de la foto (algo cargado a mano después, un split, un vencimiento). La
comparación (`compute_reconcile`) no recibía esa lista: un activo que faltaba lo
trataba como «tenías 0» y lo mandaba a `to_seed`, el único balde que se aplica
solo. Resultado: la foto volvía a COMPRAR el activo entero y anotaba un «aporte
inicial sintético» que lo pagaba — el doble de tenencia y de capital aportado.

Pasaba con una compra a mano posterior, con una posición cargada sin fecha (que
se fecha hoy) y con CUALQUIER operación a mano posterior aunque no cambie la
cantidad: un dividendo o un cupón (el bono amortizante se recompraba sin pedir
aprobación). Ahora esos activos salen de la comparación y van a «no se pudo
comparar», y los mensajes no dicen «coincide» cuando algo no se comparó o no se
ajustó.
"""
import io
import os
import tempfile
import uuid
from datetime import datetime, date, timedelta

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ.setdefault("DB_PATH", _TMP.name)

import openpyxl                              # noqa: E402
from fastapi.testclient import TestClient    # noqa: E402

import main                                  # noqa: E402

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _ar(n):
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _foto(fecha, pesos, filas, total_cedears=None):
    """filas: [(ticker, qty, precio)] en la sección Cedears."""
    tot = sum(q * p for _, q, p in filas)
    hdr = total_cedears if total_cedears is not None else tot
    lines = ["Tenencia valorizada",
             f"Tenencias al {fecha} ARS {_ar(tot)}",
             f"Cuenta Corriente ARS {_ar(pesos)}",
             f"Pesos 1 1,00 {_ar(pesos)}",
             f"Cedears ARS {_ar(hdr)}",
             "Ticker Nombre de la Especie Cantidad Precio Importe Total"]
    for tk, q, p in filas:
        lines.append(f"{tk} CEDEAR {tk} INC. {_ar(q)} {_ar(p)} {_ar(q * p)}")
    return "\n".join(lines) + "\n"


def _xlsx(filas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cuenta Corriente PESOS 06-11-26"
    ws.append(["Liquida", "Operado", "Comprobante", "Numero", "Cantidad",
               "Especie", "Precio", "Importe", "Saldo", "Referencia"])
    for f in filas:
        ws.append(f)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cc_base():
    return [
        [datetime(2026, 9, 1), datetime(2026, 9, 1), "RECIBO DE COBRO", 1, 0, None, 0,
         326495.16, 326495.16, None],
        [datetime(2026, 9, 3), datetime(2026, 9, 3), "COMPRA NORMAL", 2, 23, "AVGO",
         14173.7, -325995.16, 500, None],
        [datetime(2026, 10, 20), datetime(2026, 10, 20), "RECIBO DE COBRO", 3, 0, None, 0,
         1000000, 1000500, None],
    ]


class _Cuenta:
    def __init__(self, filas=None):
        self.c = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) VALUES (?, 'x', 1, 1)",
            (f"no-comparables-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.importar(filas or _cc_base())

    def importar(self, filas):
        r = self.c.post("/api/imports/preview", headers=self.h,
                        files=[("files", ("cc.xlsx", _xlsx(filas), XLSX))],
                        data={"format": "bullmarket"})
        assert r.status_code == 200, r.text
        c = self.c.post("/api/imports/confirm", headers=self.h,
                        json={"session_id": r.json()["session_id"]})
        assert c.status_code == 200, c.text

    def q(self, sql, *a):
        conn = main.get_db()
        try:
            return conn.execute(sql, a).fetchall()
        finally:
            conn.close()

    def caja(self):
        rows = self.q("SELECT invested FROM positions WHERE user_id=? AND broker='Bull Market' "
                      "AND is_cash=1", self.uid)
        return round(float(rows[0]["invested"] or 0), 2) if rows else 0.0

    def qty(self, asset):
        r = self.q("SELECT COALESCE(SUM(quantity),0) s FROM positions WHERE user_id=? "
                   "AND is_cash=0 AND asset=?", self.uid, asset)
        return round(float(r[0]["s"] or 0), 6)

    def aportes_sinteticos(self):
        r = self.q(f"SELECT COALESCE(SUM(n.gross_amount),0) s FROM {main.TX_VIVAS} "
                   "WHERE b.user_id=? AND n.notes=?", self.uid,
                   main._import_tenencia.TENENCIA_SEED_DEPOSIT_NOTE)
        return round(float(r[0]["s"] or 0), 2)

    def subir_foto(self, texto, confirmar=True):
        orig = main._import_excel.is_pdf, main._import_excel.pdf_to_text
        main._import_excel.is_pdf = lambda b: True
        main._import_excel.pdf_to_text = lambda b: texto
        try:
            t = self.c.post("/api/imports/tenencia/preview", headers=self.h,
                            data={"broker": "Bull Market"},
                            files={"file": ("Tenencia valorizada.pdf", b"%PDF-1.4", "application/pdf")})
        finally:
            main._import_excel.is_pdf, main._import_excel.pdf_to_text = orig
        assert t.status_code == 200, t.text
        j = t.json()
        if confirmar and j.get("session_id"):
            c = self.c.post("/api/imports/confirm", headers=self.h,
                            json={"session_id": j["session_id"]})
            assert c.status_code == 200, c.text
        return j




def _operacion_a_mano(cu, fecha, activo, tipo):
    """Una operación cargada desde la pantalla (sin vínculo a un import)."""
    conn = main.get_db()
    with conn:
        conn.execute("INSERT INTO operations (user_id,date,broker,asset,op_type,quantity,pnl_usd) "
                     "VALUES (?,?,'Bull Market',?,?,0,1)", (cu.uid, fecha, activo, tipo))
    conn.close()


def test_compra_a_mano_posterior_de_un_activo_que_la_foto_lista_no_se_recompra():
    cu = _Cuenta()
    r = cu.c.post("/api/positions", headers=cu.h, json={
        "broker": "Bull Market", "asset": "AVGO", "quantity": 5, "buy_price": 12650,
        "entry_date": "2026-10-21", "asset_type": "CEDEAR", "currency": "ARS"})
    assert r.status_code == 200, r.text
    aporte0 = cu.aportes_sinteticos()
    j = cu.subir_foto(_foto("20/10/2026", 1000500, [("AVGO", 23, 12650)]))
    assert cu.qty("AVGO") == 28                      # antes: 51
    assert cu.aportes_sinteticos() == aporte0        # antes: + $290.950
    assert not j.get("to_seed")
    assert "AVGO" in {d["ticker"] for d in j["no_reconciliable"]}


def test_posicion_cargada_sin_fecha_no_se_duplica_con_la_foto_de_ayer():
    cu = _Cuenta()
    r = cu.c.post("/api/positions", headers=cu.h, json={
        "broker": "Bull Market", "asset": "KO", "quantity": 10, "buy_price": 20000,
        "asset_type": "CEDEAR", "currency": "ARS"})
    assert r.status_code == 200, r.text
    hoy = cu.q("SELECT entry_date d FROM positions WHERE user_id=? AND asset='KO'", cu.uid)[0]["d"]
    ayer = date.fromisoformat(hoy) - timedelta(days=1)
    cu.subir_foto(_foto(ayer.strftime("%d/%m/%Y"), cu.caja(),
                        [("AVGO", 23, 12650), ("KO", 10, 20000)]))
    assert cu.qty("KO") == 10                        # antes: 20


def test_un_dividendo_a_mano_posterior_no_hace_recomprar_el_activo():
    """Ya pasaba antes de este trabajo: cualquier operación a mano posterior."""
    cu = _Cuenta()
    _operacion_a_mano(cu, "2026-10-25", "AVGO", "Dividendo")
    cu.subir_foto(_foto("20/10/2026", 1000500, [("AVGO", 23, 12650)]))
    assert cu.qty("AVGO") == 23                      # antes: 46


def test_un_cupon_a_mano_posterior_no_hace_recomprar_el_bono_amortizante():
    from pricing.bond_amortization import is_amortizing_bond
    assert is_amortizing_bond("AL30")
    filas = _cc_base()[:1] + [
        [datetime(2026, 9, 3), datetime(2026, 9, 3), "COMPRA NORMAL", 2, 1000, "AL30",
         80, -80000, 246495.16, None]]
    cu = _Cuenta(filas)
    q0 = cu.qty("AL30")
    _operacion_a_mano(cu, "2026-10-25", "AL30", "Cupón")
    texto = ("Tenencia valorizada\nTenencias al 20/10/2026 ARS 80.000,00\n"
             "Cuenta Corriente ARS 246.495,16\nPesos 1 1,00 246.495,16\n"
             f"Titulos Publicos ARS {_ar(q0 * 80)}\n"
             "Ticker Nombre de la Especie Cantidad Precio Importe Total\n"
             f"AL30 BONO AL30 {_ar(q0)} 80,00 {_ar(q0 * 80)}\n")
    j = cu.subir_foto(texto, confirmar=False)
    assert not j.get("to_seed")                      # antes: 640 AL30 sin aprobación


def test_el_mensaje_no_dice_que_no_se_comparo_lo_que_si_se_comparo():
    """Foto parcial con un activo ausente (GS): se comparó y no está en la foto."""
    filas = _cc_base()[:2] + [
        [datetime(2026, 9, 4), datetime(2026, 9, 4), "RECIBO DE COBRO", 4, 0, None, 0,
         671700, 672200, None],
        [datetime(2026, 9, 4), datetime(2026, 9, 4), "COMPRA NORMAL", 5, 6, "GS",
         111950, -671700, 500, None]]
    cu = _Cuenta(filas)
    j = cu.subir_foto(_foto("20/10/2026", 500, [("AVGO", 23, 12650)], total_cedears=999999),
                      confirmar=False)
    msg = j.get("message") or ""
    assert "No comparamos GS" not in msg               # GS se comparó: no está en la foto
    if j.get("nothing_to_do"):
        assert j["todo_coincide"] is False
        assert "GS" in msg and "incompleta" in msg      # diferencia + foto leída a medias


def test_el_mensaje_no_dice_coinciden_si_hay_una_diferencia_que_no_se_ajusto():
    """Rendi tiene 28 AVGO a la fecha de la foto (5 a mano ANTES), la foto 23: una
    diferencia que el freno de lo manual no deja ajustar no es «coinciden»."""
    cu = _Cuenta()
    r = cu.c.post("/api/positions", headers=cu.h, json={
        "broker": "Bull Market", "asset": "AVGO", "quantity": 5, "buy_price": 12650,
        "entry_date": "2026-09-10", "asset_type": "CEDEAR", "currency": "ARS"})
    assert r.status_code == 200, r.text
    j = cu.subir_foto(_foto("01/10/2026", 500, [("AVGO", 23, 12650)]), confirmar=False)
    assert "coincide" not in (j.get("message") or "")


def test_un_dividendo_a_mano_de_un_activo_que_rendi_no_tiene_no_frena_completarlo():
    """Un dividendo no cambia la cantidad: KO se compara (0 contra 10) y se completa."""
    cu = _Cuenta()
    _operacion_a_mano(cu, "2026-10-25", "KO", "Dividendo")
    cu.subir_foto(_foto("20/10/2026", 1000500, [("AVGO", 23, 12650), ("KO", 10, 20000)]))
    assert cu.qty("KO") == 10


def test_una_letra_que_vencio_despues_de_la_foto_no_se_recompra():
    """El barrido de vencimientos ya la borró de la cartera: la foto no la ve en
    Rendi, y sin esto la «completaba» con un aporte sintético que nunca existió."""
    from importing.maturity import letra_maturity
    assert (letra_maturity("S30S6") or "")[:10] == "2026-09-30"
    filas = [
        [datetime(2026, 9, 1), datetime(2026, 9, 1), "RECIBO DE COBRO", 1, 0, None, 0,
         100500, 100500, None],
        [datetime(2026, 9, 3), datetime(2026, 9, 3), "COMPRA NORMAL", 2, 1000, "S30S6",
         100, -100000, 500, None],
        [datetime(2026, 9, 30), datetime(2026, 9, 30), "RENTA Y AMORTIZACION", 3, 0, "S30S6",
         0, 102000, 102500, None]]
    cu = _Cuenta(filas)
    assert cu.qty("S30S6") == 0                      # el barrido ya la sacó
    aporte0 = cu.aportes_sinteticos()
    texto = ("Tenencia valorizada\nTenencias al 20/09/2026 ARS 100.500,00\n"
             "Cuenta Corriente ARS 500,00\nPesos 1 1,00 500,00\n"
             "Letras ARS 100.000,00\n"
             "Ticker Nombre de la Especie Cantidad Precio Importe Total\n"
             "S30S6 LECAP 30/09/26 1.000,00 10.000,00 100.000,00\n")
    j = cu.subir_foto(texto)
    assert not j.get("to_seed")
    assert cu.aportes_sinteticos() == aporte0        # antes: + $100.000
    assert "S30S6" in {d["ticker"] for d in (j.get("no_reconciliable") or [])}
