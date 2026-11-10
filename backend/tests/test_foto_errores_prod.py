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
import json
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


# ── Lo que encontró la revisión independiente del 2026-11-10 ───────────────

def _wb_trade(symbol, shares, usd, date, uid_):
    return {"uuid": uid_, "type": "TRADE", "status": "COMPLETED",
            "source_currency": {"code": "USD"}, "dest_currency": {"code": symbol},
            "trade_info": {"direction": "BUY", "symbol": symbol, "share_price": usd / shares},
            "source_amount": usd, "dest_amount": shares,
            "created_at": date + "T12:00:00.000000Z", "comment": None}


class _Wallbit:
    """Una cuenta con Wallbit conectado; las tres llamadas a la red, reemplazadas."""

    def __init__(self, trades, balances, precios):
        import wallbit as W
        self.W = W
        self.c = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) VALUES (?, 'x', 1, 1)",
            (f"errores-prod-wb-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
        conn.execute("INSERT INTO user_broker_credentials (user_id, broker, api_key_enc, scope) "
                     "VALUES (?, 'wallbit', ?, 'read')", (self.uid, main._wallbit_encrypt("k")))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self._orig = (W.fetch_trades, W.fetch_stock_balances, W.fetch_asset_price)
        W.fetch_trades = lambda api_key, from_date=None: list(trades)
        W.fetch_stock_balances = lambda api_key: list(balances)
        W.fetch_asset_price = lambda api_key, symbol: precios.get(symbol, 0.0)

    def cerrar(self):
        self.W.fetch_trades, self.W.fetch_stock_balances, self.W.fetch_asset_price = self._orig

    def sync(self):
        main._rate_store.clear()
        r = self.c.post("/api/wallbit/sync", headers=self.h)
        assert r.status_code == 200, r.text

    def qty(self, asset):
        conn = main.get_db()
        try:
            return round(float(conn.execute(
                "SELECT COALESCE(SUM(quantity),0) s FROM positions WHERE user_id=? "
                "AND broker='Wallbit' AND is_cash=0 AND asset=?", (self.uid, asset)).fetchone()["s"]), 6)
        finally:
            conn.close()


def test_wallbit_no_junta_spyd_con_spy_y_no_lo_recompra_en_cada_sincronizacion():
    """Juntar la pata dólar es una regla de la Bolsa argentina: en Nueva York SPYD
    (un ETF) no es SPY. Con la traducción argentina en la cartera de Wallbit, cada
    sincronización volvía a comprar SPYD (5 → 10 → 15)."""
    wb = _Wallbit([_wb_trade("SPY", 10, 5000.0, "2026-09-10", "s1"),
                   _wb_trade("SPYD", 5, 200.0, "2026-09-10", "s2")],
                  [{"symbol": "SPY", "shares": 10}, {"symbol": "SPYD", "shares": 5},
                   {"symbol": "USD", "shares": 100}],
                  {"SPY": 500.0, "SPYD": 40.0})
    try:
        wb.sync()
        wb.sync()
        assert (wb.qty("SPY"), wb.qty("SPYD")) == (10, 5)
    finally:
        wb.cerrar()


def test_plazo_fijo_de_un_broker_borrado_y_recreado_no_le_acredita_al_nuevo():
    movs = [_cobro(1, 9, 100000, 100000)]
    cu = _Cuenta(pesos=movs)
    pid = _plazo_fijo(cu, 50000, source_broker=BM)
    bid = cu.q("SELECT id FROM brokers WHERE user_id=? AND name=?", cu.uid, BM)[0]["id"]
    assert cu.c.delete(f"/api/brokers/{bid}?force=true", headers=cu.h).status_code == 200
    cu.importar(movs, [])                        # vuelve a crear «Bull Market»
    caja_nueva = cu.caja()
    r = cu.c.delete(f"/api/plazos-fijos/{pid}", headers=cu.h)
    assert r.status_code == 200, r.text
    assert cu.caja() == caja_nueva               # antes del arreglo: + $50.000 de la nada


def test_plazo_fijo_vencido_borrado_no_devuelve_la_plata():
    """Vencido, la plata pudo volver por el import del broker: devolverla otra vez
    la contaría dos veces (para eso está «Cobrar»)."""
    cu = _Cuenta(pesos=[_cobro(1, 9, 1000000, 1000000)])
    pid = _plazo_fijo(cu, 300000, fecha_inicio="2026-09-02", source_broker=BM)
    conn = main.get_db()
    with conn:                                   # así queda si se cargó el 02/09, vivo hasta el 02/10
        meta = json.loads(conn.execute("SELECT undo_meta_json m FROM plazos_fijos WHERE id=?",
                                       (pid,)).fetchone()["m"])
        meta["vivo_al_cargar"] = True
        conn.execute("UPDATE plazos_fijos SET created_at='2026-09-02 15:00:00', undo_meta_json=? "
                     "WHERE id=?", (json.dumps(meta), pid))
    conn.close()
    lista = cu.c.get("/api/plazos-fijos", headers=cu.h).json()
    assert lista[0]["plata_al_borrar"] == {"broker": BM, "vuelve": False}   # la pantalla lo avisa
    cu.importar([_cobro(3, 10, 307397.26, 1007397.26, 40)], [])   # la vuelta, importada
    caja1 = cu.caja()
    r = cu.c.delete(f"/api/plazos-fijos/{pid}", headers=cu.h)
    assert r.status_code == 200, r.text
    assert cu.caja() == caja1 and r.json()["devuelto"] is None


def test_plazo_fijo_cargado_ya_vencido_por_error_si_devuelve():
    """Cargado con fechas del pasado y borrado enseguida: nunca estuvo vivo en
    Rendi, así que su plata no pudo volver por otro lado. Borrarlo corrige la carga."""
    cu = _Cuenta(pesos=[_cobro(1, 9, 1000000, 1000000)])
    caja0 = cu.caja()
    pid = _plazo_fijo(cu, 200000, fecha_inicio="2026-08-01", source_broker=BM)
    assert cu.caja() == caja0 - 200000
    lista = cu.c.get("/api/plazos-fijos", headers=cu.h).json()
    assert lista[0]["plata_al_borrar"] == {"broker": BM, "vuelve": True}
    r = cu.c.delete(f"/api/plazos-fijos/{pid}", headers=cu.h)
    assert r.status_code == 200, r.text
    assert cu.caja() == caja0


def test_una_compra_de_otro_activo_posterior_a_la_foto_no_frena_el_confirmar():
    """La tanda del asesor con dos archivos del mismo cliente: el segundo trae una
    compra de KO POSTERIOR a la foto, que no cambia ninguna diferencia de la foto."""
    cu = _Cuenta(pesos=[_cobro(1, 9, 326495.16, 326495.16), _compra(3, 9, "AVGO", 23, 14173.7, 500)])
    j = cu.subir_foto(_foto("20/10/2026", [("Cedears", "ARS", [("AVGO", 28, 12650)])],
                            pesos=500), confirmar=False)
    cu.importar([_cobro(1, 11, 60000, 60500, 20), _compra(2, 11, "KO", 10, 6000, 500, 21)], [])
    c = cu.c.post("/api/imports/confirm", headers=cu.h, json={"session_id": j["session_id"]})
    assert c.status_code == 200, c.text
    assert cu.qty("AVGO") == 28


def test_si_la_cartera_cambia_entre_la_vista_previa_y_confirmar_la_foto_se_frena():
    """23 AVGO, foto 28 → «completar 5». Antes de confirmar entra un archivo con esa
    compra (fechada antes de la foto). Aplicar el «completar 5» viejo dejaba 33."""
    cu = _Cuenta(pesos=[_cobro(1, 9, 326495.16, 326495.16), _compra(3, 9, "AVGO", 23, 14173.7, 500)])
    j = cu.subir_foto(_foto("20/10/2026", [("Cedears", "ARS", [("AVGO", 28, 12650)])],
                            pesos=500), confirmar=False)
    assert [s["qty"] for s in j["to_seed"]] == [5.0]
    cu.importar([_cobro(9, 10, 70868.5, 71368.5, 20), _compra(10, 10, "AVGO", 5, 14173.7, 500, 21)], [])
    c = cu.c.post("/api/imports/confirm", headers=cu.h, json={"session_id": j["session_id"]})
    assert c.status_code == 409, c.text
    assert cu.qty("AVGO") == 28


def test_renombrar_el_broker_entre_la_vista_previa_y_confirmar_no_frena_nada():
    cu = _Cuenta(pesos=[_cobro(1, 9, 326495.16, 326495.16), _compra(3, 9, "AVGO", 23, 14173.7, 500),
                        _cobro(20, 10, 1000000, 1000500, 3)])
    j = cu.subir_foto(_foto("01/11/2026", [("Cedears", "ARS", [("AVGO", 23, 12650)])],
                            pesos=900000), confirmar=False)
    bid = cu.q("SELECT id FROM brokers WHERE user_id=? AND name=?", cu.uid, BM)[0]["id"]
    r = cu.c.put(f"/api/brokers/{bid}", headers=cu.h, json={"name": "Bull Market 2", "currency": "ARS"})
    assert r.status_code == 200, r.text
    c = cu.c.post("/api/imports/confirm", headers=cu.h, json={"session_id": j["session_id"]})
    assert c.status_code == 200, c.text
    assert cu.caja("Bull Market 2") == 900000.0 and not c.json().get("caja_sin_ajustar")


def test_la_cuenta_en_dolares_que_la_foto_adopta_cuenta_en_el_par():
    """«Bull Market · USD» creada a mano, sin padre, con AVGO 5; la foto la adopta.
    Sin releer el par después de adoptarla, esos 5 eran «no los tenías»."""
    cu = _Cuenta(pesos=[_cobro(1, 9, 500, 500)])
    conn = main.get_db()
    with conn:
        conn.execute("UPDATE users SET tier='pro' WHERE id=?", (cu.uid,))
    conn.close()
    r = cu.c.post("/api/brokers", headers=cu.h, json={"name": BMU, "currency": "USD"})
    assert r.status_code == 200, r.text
    cu.posicion_a_mano(broker=BMU, asset="AVGO", quantity=5, buy_price=200,
                       entry_date="2026-09-10", asset_type="CEDEAR", currency="USD")
    cu.subir_foto(_foto("20/10/2026", [("Cedears", "U$S", [("AVGOD", 5, 200)])],
                        pesos=cu.caja(), dolares=cu.caja(BMU)))
    assert cu.qty("AVGO") == 5


def test_lo_guardado_con_otro_nombre_no_se_vende_solo():
    """Importado antes de que existiera el renombre GOLD→B: la cartera dice GOLD,
    la comparación B. La venta se escribiría como B, que no tiene lotes. Sin datos a
    mano, ni otra cuenta, ni el freno del 50%: sólo esta guarda lo para."""
    otros = [("KO", 10, 6000), ("MSFT", 10, 40000), ("NVDA", 10, 15000)]
    cu = _Cuenta(pesos=[_cobro(1, 9, 3000000, 3000000), _compra(3, 9, "GOLD", 10, 30000, 2700000, 2)]
                 + [_compra(3, 9, tk, q, p, 0, 10 + i) for i, (tk, q, p) in enumerate(otros)])
    conn = main.get_db()
    with conn:                                   # así quedó lo importado antes del renombre
        conn.execute("UPDATE positions SET asset='GOLD' WHERE user_id=? AND asset='B'", (cu.uid,))
        conn.execute("UPDATE import_normalized_tx SET asset_symbol='GOLD' WHERE asset_symbol='B' "
                     "AND batch_id IN (SELECT id FROM import_batches WHERE user_id=?)", (cu.uid,))
    conn.close()
    assert cu.qty("GOLD") == 10
    j = cu.subir_foto(_foto("20/10/2026", [("Cedears", "ARS", [("GOLD", 6, 30000)] + otros)],
                            pesos=cu.caja()))
    assert cu.ventas_de_ajuste() == 0 and cu.qty("GOLD") == 10
    assert j["todo_coincide"] is False and "B" in j["message"]   # queda a la vista


def test_lo_que_sobra_en_dolares_si_la_foto_lo_lista_en_pesos_se_pregunta():
    """28 AVGO sólo en «· USD»; la foto no trae sección en dólares y dice 23 en pesos.
    En el par sobran 5, pero sacarlos de la cuenta en dólares cruza de moneda (puede
    que el resumen no traiga esa cuenta): se arma la venta y se pregunta."""
    cu = _Cuenta(pesos=[_cobro(1, 9, 500, 500)], dolares=_cedears_en_dolares())
    j = cu.subir_foto(_foto("20/10/2026",
                            [("Cedears", "ARS", [("AVGO", 23, 12650), ("KO", 10, 6000),
                                                 ("MSFT", 10, 40000), ("NVDA", 10, 15000)])],
                            pesos=cu.caja(), dolares=cu.caja(BMU)), confirmar=False)
    a_decidir = [d for d in j["no_reconciliable"] if d.get("requiere_aprobacion")]
    assert [d["ticker"] for d in a_decidir] == ["AVGO"]
    c = cu.c.post("/api/imports/confirm", headers=cu.h, json={"session_id": j["session_id"]})
    assert c.status_code == 200, c.text
    assert cu.qty("AVGO", BMU) == 28             # sin aprobar, no se vende
    assert c.json()["skipped_pending_approval"] == 1


def test_lo_archivado_sin_fecha_tampoco_se_recompra_y_al_restaurar_coincide():
    cu = _Cuenta(pesos=[_cobro(1, 9, 100500, 100500), _compra(3, 9, "AL30", 1000, 80, 20500)])
    q0 = cu.qty("AL30")
    assert cu.c.post("/api/sections/archive", headers=cu.h,
                     json={"section": "BONO|ARS"}).status_code == 200
    texto = _foto("20/10/2026", [("Titulos Publicos", "ARS", [("AL30", q0, 80)])],
                  pesos=cu.caja()).replace("Tenencias al 20/10/2026", "Tenencias al día")
    aporte0 = cu.aportes_sinteticos()
    j = cu.subir_foto(texto)
    assert j["fecha_origen"] == "fallback_hoy"
    assert cu.qty("AL30") == 0 and cu.aportes_sinteticos() == aporte0
    arch = cu.c.get("/api/sections/archived", headers=cu.h).json()["archived"]
    assert cu.c.post("/api/sections/restore", headers=cu.h,
                     json={"archive_id": arch[0]["id"]}).status_code == 200
    cu.subir_foto(texto)
    assert cu.qty("AL30") == q0
