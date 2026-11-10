"""Errores de la «foto» del broker que ya estaban en producción.

Los encontraron tres revisiones independientes del 07-08/11/2026 corriendo casos
por la API, y quedaron afuera del arreglo de la foto de fecha pasada a propósito.
Cada prueba pasa por el mismo camino que la persona: sube los movimientos
(/api/imports/preview → /confirm), sube la foto (/api/imports/tenencia/preview)
y la confirma (/api/imports/confirm). Ninguna llama al comparador directo.

  1. Un CEDEAR repartido entre la cuenta en pesos y la «· USD»: la partición en
     dólares veía «Rendi tiene de más» contra la mitad de la foto y vendía.
  2. Un ticker escrito distinto de cada lado (GOLD/B, AL30D/AL30): la foto pasaba
     por la traducción y la cartera no, así que la foto volvía a comprar.
  3. «Todo coincide» ciego a las diferencias entre monedas.
  4. Borrar un plazo fijo no le devolvía la plata al broker de donde salió.
  5. Lo archivado (`/api/sections/archive`) se leía como «no lo tenías» y la foto
     lo volvía a comprar con un aporte que nunca existió.
  6. El ajuste de efectivo se calculaba en la vista previa y se aplicaba al
     confirmar sin volver a mirar si entró plata entre medio.
"""
import io
import os
import tempfile
import uuid
from datetime import datetime

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ.setdefault("DB_PATH", _TMP.name)

import openpyxl                              # noqa: E402
from fastapi.testclient import TestClient    # noqa: E402

import main                                  # noqa: E402

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
BM, BMU = "Bull Market", "Bull Market · USD"


def _ar(n):
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _d(dia, mes):
    return datetime(2026, mes, dia)


def _cobro(dia, mes, monto, saldo, n=1):
    return [_d(dia, mes), _d(dia, mes), "RECIBO DE COBRO", n, 0, None, 0, monto, saldo, None]


def _compra(dia, mes, tk, q, precio, saldo, n=2):
    return [_d(dia, mes), _d(dia, mes), "COMPRA NORMAL", n, q, tk, precio, -q * precio, saldo, None]


def _xlsx(pesos, dolares):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for titulo, filas in (("Cuenta Corriente PESOS 06-11-26", pesos),
                          ("Cuenta Corriente DOLARES 06-11-26", dolares)):
        if not filas:
            continue
        ws = wb.create_sheet(titulo)
        ws.append(["Liquida", "Operado", "Comprobante", "Numero", "Cantidad",
                   "Especie", "Precio", "Importe", "Saldo", "Referencia"])
        for f in filas:
            ws.append(f)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _foto(fecha, secciones, pesos=0.0, dolares=None):
    """La «Tenencia valorizada» de Bull Market. secciones: [(nombre, moneda,
    [(ticker, cantidad, precio)])], p. ej. ("Cedears", "U$S", [("AVGOD", 5, 200)])."""
    tot = sum(q * p for _, _, fs in secciones for _, q, p in fs)
    lines = ["Tenencia valorizada", f"Tenencias al {fecha} ARS {_ar(tot)}",
             f"Cuenta Corriente ARS {_ar(pesos)}", f"Pesos 1 1,00 {_ar(pesos)}"]
    if dolares is not None:
        lines.append(f"U$S {_ar(dolares)} 1.450,00 {_ar(dolares * 1450)}")
    for nombre, moneda, filas in secciones:
        lines.append(f"{nombre} {moneda} {_ar(sum(q * p for _, q, p in filas))}")
        lines.append("Ticker Nombre de la Especie Cantidad Precio Importe Total")
        for tk, q, p in filas:
            lines.append(f"{tk} {nombre.upper()} {tk} INC. {_ar(q)} {_ar(p)} {_ar(q * p)}")
    return "\n".join(lines) + "\n"


class _Cuenta:
    def __init__(self, pesos=None, dolares=None):
        self.c = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) VALUES (?, 'x', 1, 1)",
            (f"errores-prod-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.importar(pesos or [], dolares or [])

    def importar(self, pesos, dolares):
        r = self.c.post("/api/imports/preview", headers=self.h,
                        files=[("files", ("cc.xlsx", _xlsx(pesos, dolares), XLSX))],
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

    def caja(self, broker=BM):
        rows = self.q("SELECT invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
                      self.uid, broker)
        return round(float(rows[0]["invested"] or 0), 2) if rows else 0.0

    def qty(self, asset, broker=None):
        sql = ("SELECT COALESCE(SUM(quantity),0) s FROM positions WHERE user_id=? "
               "AND is_cash=0 AND asset=?")
        args = [self.uid, asset]
        if broker:
            sql += " AND broker=?"
            args.append(broker)
        return round(float(self.q(sql, *args)[0]["s"] or 0), 6)

    def aportes_sinteticos(self):
        r = self.q(f"SELECT COALESCE(SUM(n.gross_amount),0) s FROM {main.TX_VIVAS} "
                   "WHERE b.user_id=? AND n.notes=?", self.uid,
                   main._import_tenencia.TENENCIA_SEED_DEPOSIT_NOTE)
        return round(float(r[0]["s"] or 0), 2)

    def ventas_de_ajuste(self):
        r = self.q(f"SELECT COUNT(*) n FROM {main.TX_VIVAS} WHERE b.user_id=? "
                   "AND n.operation_type='SELL' AND n.notes LIKE 'Tenencia — ajuste%'", self.uid)
        return int(r[0]["n"] or 0)

    def subir_foto(self, texto, confirmar=True):
        orig = main._import_excel.is_pdf, main._import_excel.pdf_to_text
        main._import_excel.is_pdf = lambda b: True
        main._import_excel.pdf_to_text = lambda b: texto
        try:
            t = self.c.post("/api/imports/tenencia/preview", headers=self.h,
                            data={"broker": BM},
                            files={"file": ("Tenencia valorizada.pdf", b"%PDF-1.4", "application/pdf")})
        finally:
            main._import_excel.is_pdf, main._import_excel.pdf_to_text = orig
        assert t.status_code == 200, t.text
        j = t.json()
        if confirmar and j.get("session_id"):
            c = self.c.post("/api/imports/confirm", headers=self.h,
                            json={"session_id": j["session_id"]})
            assert c.status_code == 200, c.text
            j["_confirm"] = c.json()
        return j

    def posicion_a_mano(self, **kw):
        r = self.c.post("/api/positions", headers=self.h, json=kw)
        assert r.status_code == 200, r.text


def _cedears_en_dolares():
    """28 AVGO todos en «· USD», más otros tres CEDEARs en dólares que la foto lista
    igual (sin ellos el freno del 50% tapaba la venta y la prueba no veía nada)."""
    return [_cobro(1, 9, 20000, 20000, 10),
            _compra(3, 9, "AVGO", 28, 200, 14400, 11),
            _compra(3, 9, "KO", 10, 60, 13800, 12),
            _compra(3, 9, "MSFT", 10, 400, 9800, 13),
            _compra(3, 9, "NVDA", 10, 150, 8300, 14)]


_OTROS_USD = [("KO", 10, 60), ("MSFT", 10, 400), ("NVDA", 10, 150)]


# ── 1. CEDEAR repartido entre pesos y «· USD» ───────────────────────────────

def test_cedear_partido_entre_monedas_que_coincide_en_el_par_no_se_vende():
    cu = _Cuenta(pesos=[_cobro(1, 9, 500, 500)], dolares=_cedears_en_dolares())
    assert cu.qty("AVGO", BMU) == 28 and cu.qty("AVGO", BM) == 0
    j = cu.subir_foto(_foto("20/10/2026",
                            [("Cedears", "ARS", [("AVGO", 23, 12650)]),
                             ("Cedears", "U$S", [("AVGOD", 5, 200)] + _OTROS_USD)],
                            pesos=cu.caja(), dolares=cu.caja(BMU)))
    assert cu.qty("AVGO") == 28                  # antes: 5 (vendía 23 a costo)
    assert cu.ventas_de_ajuste() == 0
    assert not j.get("over")
    assert j.get("todo_coincide") is True


# ── 2. Una sola traducción de tickers para los dos lados ────────────────────

def test_gold_cargado_a_mano_y_la_foto_dice_gold_no_compra_b():
    cu = _Cuenta(pesos=[_cobro(1, 9, 1000000, 1000000)])
    cu.posicion_a_mano(broker=BM, asset="GOLD", quantity=10, buy_price=30000,
                       entry_date="2026-09-10", asset_type="CEDEAR", currency="ARS")
    assert cu.qty("GOLD") == 10
    aporte0 = cu.aportes_sinteticos()
    j = cu.subir_foto(_foto("20/10/2026", [("Cedears", "ARS", [("GOLD", 10, 30000)])],
                            pesos=cu.caja()))
    assert cu.qty("B") == 0                      # antes: 10 B comprados por la foto
    assert cu.qty("GOLD") == 10
    assert cu.aportes_sinteticos() == aporte0    # antes: + $300.000
    assert not j.get("to_seed")


def test_gold_contra_el_registro_diario_que_dice_gold_se_verifica():
    """El registro diario del cron guarda GOLD (el nombre de la cartera); la
    comparación usa B. Sin la misma traducción, «no pudimos verificar» falso."""
    cu = _Cuenta(pesos=[_cobro(1, 9, 1000000, 1000000)])
    cu.posicion_a_mano(broker=BM, asset="GOLD", quantity=10, buy_price=30000,
                       entry_date="2026-09-10", asset_type="CEDEAR", currency="ARS")
    conn = main.get_db()
    with conn:
        conn.execute("INSERT INTO snapshots (user_id, date, total_value, total_invested, holdings_json, source) "
                     "VALUES (?, '2026-10-19', 1, 1, ?, 'cron')",
                     (cu.uid, '[{"asset": "GOLD", "value_usd": 200.0}]'))
    conn.close()
    j = cu.subir_foto(_foto("20/10/2026", [("Cedears", "ARS", [("GOLD", 10, 30000)])],
                            pesos=cu.caja()), confirmar=False)
    assert not [d for d in j.get("no_reconciliable") or [] if not d.get("ticker")]
    assert j.get("todo_coincide") is True


def test_al30d_guardado_con_sufijo_y_la_foto_dice_al30d_no_compra_al30():
    cu = _Cuenta(pesos=[_cobro(1, 9, 500, 500)], dolares=[_cobro(1, 9, 1000, 1000, 10)])
    cu.posicion_a_mano(broker=BMU, asset="AL30D", quantity=1000, buy_price=0.6,
                       entry_date="2026-09-10", asset_type="BOND", currency="USD")
    assert cu.qty("AL30D") == 1000
    j = cu.subir_foto(_foto("20/10/2026", [("Titulos Publicos", "U$S", [("AL30D", 1000, 0.6)])],
                            pesos=cu.caja(), dolares=cu.caja(BMU)))
    assert not j.get("to_seed")                  # antes: 1000 AL30 SIN pedir aprobación
    assert cu.qty("AL30") == 0
    assert cu.qty("AL30D") == 1000


# ── 3. «Todo coincide» con diferencias entre monedas ────────────────────────

def test_rendi_tiene_dolares_de_mas_que_la_foto_no_lista_no_es_coincide():
    cu = _Cuenta(pesos=[_cobro(1, 9, 326495.16, 326495.16), _compra(3, 9, "AVGO", 23, 14173.7, 500)],
                 dolares=[_cobro(1, 9, 1000, 1000, 10), _compra(3, 9, "AVGO", 5, 200, 0, 11)])
    j = cu.subir_foto(_foto("20/10/2026", [("Cedears", "ARS", [("AVGO", 23, 12650)])],
                            pesos=cu.caja(), dolares=cu.caja(BMU)), confirmar=False)
    assert j.get("todo_coincide") is not True    # antes: «coincide» (28 contra 23)
    assert "AVGO" in (j.get("message") or "") or any(
        o["ticker"] == "AVGO" for o in j.get("over") or [])


def test_la_foto_trae_dolares_que_rendi_no_tiene_se_completan():
    cu = _Cuenta(pesos=[_cobro(1, 9, 326495.16, 326495.16), _compra(3, 9, "AVGO", 23, 14173.7, 500)])
    j = cu.subir_foto(_foto("20/10/2026",
                            [("Cedears", "ARS", [("AVGO", 23, 12650)]),
                             ("Cedears", "U$S", [("AVGOD", 5, 200)])],
                            pesos=cu.caja(), dolares=0.0))
    assert j.get("todo_coincide") is not True    # antes: «coincide» (23 contra 28)
    assert [(s["ticker"], s["qty"], s["currency"]) for s in j.get("to_seed") or []] == [
        ("AVGO", 5.0, "USD")]
    assert cu.qty("AVGO") == 28


# ── 4. Borrar un plazo fijo le devuelve la plata al broker ──────────────────

def _plazo_fijo(cu, capital, **kw):
    r = cu.c.post("/api/plazos-fijos", headers=cu.h, json={
        "banco": "Banco Prueba", "capital": capital, "moneda": "ARS", "tasa": 0.3,
        "fecha_inicio": "2026-10-25", "plazo_dias": 30, **kw})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_borrar_un_plazo_fijo_devuelve_la_plata_y_la_foto_no_la_repone():
    cu = _Cuenta(pesos=[_cobro(1, 9, 326495.16, 326495.16), _compra(3, 9, "AVGO", 23, 14173.7, 500),
                        _cobro(20, 10, 1000000, 1000500, 3)])
    caja0 = cu.caja()
    pid = _plazo_fijo(cu, 200000, source_broker=BM)
    assert cu.caja() == round(caja0 - 200000, 2)
    r = cu.c.delete(f"/api/plazos-fijos/{pid}", headers=cu.h)
    assert r.status_code == 200, r.text
    assert cu.caja() == caja0                    # antes: quedaba en caja0 − 200.000
    j = cu.subir_foto(_foto("01/11/2026", [("Cedears", "ARS", [("AVGO", 23, 12650)])],
                            pesos=caja0), confirmar=False)
    assert not j.get("cash_ajustes")             # antes: depósito sintético de $200.000


def test_borrar_un_plazo_fijo_con_autodeposito_revierte_el_autodeposito():
    cu = _Cuenta(pesos=[_cobro(1, 9, 100000, 100000)])
    pid = _plazo_fijo(cu, 300000, source_broker=BM)
    assert cu.caja() == 0.0
    vivos = lambda: cu.q("SELECT COUNT(*) n FROM flujos_a_mano WHERE user_id=? "   # noqa: E731
                         "AND ref=? AND anulado_at IS NULL", cu.uid, f"pf:{pid}")[0]["n"]
    assert vivos() == 1
    r = cu.c.delete(f"/api/plazos-fijos/{pid}", headers=cu.h)
    assert r.status_code == 200, r.text
    assert cu.caja() == 100000.0                 # ni 0 (sin devolver) ni 300.000 (fantasma)
    assert vivos() == 0


def test_plazo_fijo_sin_broker_de_origen_borrarlo_no_mueve_el_efectivo():
    cu = _Cuenta(pesos=[_cobro(1, 9, 100000, 100000)])
    pid = _plazo_fijo(cu, 50000)
    r = cu.c.delete(f"/api/plazos-fijos/{pid}", headers=cu.h)
    assert r.status_code == 200, r.text
    assert cu.caja() == 100000.0


# ── 5. Lo archivado no se vuelve a comprar ─────────────────────────────────

def test_una_seccion_archivada_no_se_recompra_con_la_foto():
    cu = _Cuenta(pesos=[_cobro(1, 9, 100500, 100500), _compra(3, 9, "AL30", 1000, 80, 20500)])
    q0 = cu.qty("AL30")                          # el residual (el bono amortiza)
    assert q0 > 0
    r = cu.c.post("/api/sections/archive", headers=cu.h, json={"section": "BONO|ARS"})
    assert r.status_code == 200, r.text
    assert cu.qty("AL30") == 0
    aporte0 = cu.aportes_sinteticos()
    j = cu.subir_foto(_foto("20/10/2026", [("Titulos Publicos", "ARS", [("AL30", q0, 80)])],
                            pesos=cu.caja()))
    assert cu.qty("AL30") == 0                   # antes: recomprados enteros
    assert cu.aportes_sinteticos() == aporte0    # antes: + $51.200
    assert "AL30" in {d.get("ticker") for d in j.get("no_reconciliable") or []}
    assert j.get("todo_coincide") is not True


# ── 6. El ajuste de efectivo se vuelve a mirar al confirmar ─────────────────

def test_si_entra_plata_entre_la_vista_previa_y_confirmar_no_se_aplica_el_ajuste_viejo():
    cu = _Cuenta(pesos=[_cobro(1, 9, 326495.16, 326495.16), _compra(3, 9, "AVGO", 23, 14173.7, 500),
                        _cobro(20, 10, 1000000, 1000500, 3)])
    j = cu.subir_foto(_foto("01/11/2026", [("Cedears", "ARS", [("AVGO", 23, 12650)])],
                            pesos=900000), confirmar=False)
    assert [round(a["diff"]) for a in j["cash_ajustes"]] == [-100500]
    r = cu.c.post("/api/cash/flow", headers=cu.h, json={
        "broker_name": BM, "direction": "deposit", "amount": 50000})
    assert r.status_code == 200, r.text
    caja1 = cu.caja()
    assert round(caja1) == 1050500
    c = cu.c.post("/api/imports/confirm", headers=cu.h, json={"session_id": j["session_id"]})
    assert c.status_code == 200, c.text
    assert cu.caja() == caja1                    # antes: 950.000 (se llevaba el depósito)
    assert c.json().get("caja_sin_ajustar")


def test_sin_nada_entre_medio_el_ajuste_de_efectivo_se_aplica():
    """La otra mitad: el control nuevo no frena el ajuste cuando nada cambió."""
    cu = _Cuenta(pesos=[_cobro(1, 9, 326495.16, 326495.16), _compra(3, 9, "AVGO", 23, 14173.7, 500),
                        _cobro(20, 10, 1000000, 1000500, 3)])
    j = cu.subir_foto(_foto("01/11/2026", [("Cedears", "ARS", [("AVGO", 23, 12650)])],
                            pesos=900000))
    assert cu.caja() == 900000.0
    assert not j["_confirm"].get("caja_sin_ajustar")
