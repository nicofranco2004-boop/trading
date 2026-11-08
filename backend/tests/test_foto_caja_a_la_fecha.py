"""El ajuste de efectivo de la foto compara contra la caja A LA FECHA DE LA FOTO.

Medido el 2026-11-07, por el mismo camino que la pantalla: una persona cobra
$1.000.000 el 20/10 y después sube una Tenencia «al 05/09» que dice $500 de caja.
El ajuste comparaba la caja de HOY ($1.000.500) contra la de la foto ($500) y
retiraba $1.000.000 con fecha 05/09: el cobro desaparecía. Las tenencias no tenían
ese problema (`proyectar` deshace lo posterior a la foto); la plata sí, y en
todos los brokers con foto, porque el ajuste es uno solo.

Regla: con plata movida después de la fecha de la foto (importada, a mano, u
operaciones a mano), la caja no se ajusta y la respuesta dice por qué. Sin
movimientos posteriores, el ajuste sigue igual que siempre.

Por /api/imports/preview + /confirm (el Excel) y /api/imports/tenencia/preview +
/confirm (la foto). Lo único que se reemplaza es la extracción de texto del PDF.
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


def _foto(fecha, pesos):
    """Tenencia valorizada de Bull Market: 23 AVGO y `pesos` en la cuenta."""
    p = f"{pesos:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return (
        "Tenencia valorizada\n"
        f"Tenencias al {fecha} ARS 290.950,00\n"
        f"Cuenta Corriente ARS {p}\n"
        f"Pesos 1 1,00 {p}\n"
        "Cedears ARS 290.950,00\n"
        "Ticker Nombre de la Especie Cantidad Precio Importe Total\n"
        "AVGO CEDEAR BROADCOM INC. 23,00 12.650,00 290.950,00\n"
    )


def _cuenta_corriente():
    """Deposita, compra 23 AVGO (le quedan $500) y el 20/10 cobra $1.000.000."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cuenta Corriente PESOS 06-11-26"
    ws.append(["Liquida", "Operado", "Comprobante", "Numero", "Cantidad",
               "Especie", "Precio", "Importe", "Saldo", "Referencia"])
    ws.append([datetime(2026, 9, 1), datetime(2026, 9, 1), "RECIBO DE COBRO", 1, 0, None, 0,
               326495.16, 326495.16, None])
    ws.append([datetime(2026, 9, 3), datetime(2026, 9, 3), "COMPRA NORMAL", 2, 23, "AVGO",
               14173.7, -325995.16, 500, None])
    ws.append([datetime(2026, 10, 20), datetime(2026, 10, 20), "RECIBO DE COBRO", 3, 0, None, 0,
               1000000, 1000500, None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class _Cuenta:
    def __init__(self):
        self.c = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) VALUES (?, 'x', 1, 1)",
            (f"caja-fecha-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        r = self.c.post("/api/imports/preview", headers=self.h,
                        files=[("files", ("cc.xlsx", _cuenta_corriente(), XLSX))],
                        data={"format": "bullmarket"})
        assert r.status_code == 200, r.text
        c = self.c.post("/api/imports/confirm", headers=self.h,
                        json={"session_id": r.json()["session_id"]})
        assert c.status_code == 200, c.text

    def caja(self):
        conn = main.get_db()
        try:
            row = conn.execute("SELECT invested FROM positions WHERE user_id=? AND broker=? "
                               "AND is_cash=1", (self.uid, "Bull Market")).fetchone()
            return round(float(row["invested"] or 0), 2) if row else 0.0
        finally:
            conn.close()

    def subir_foto(self, texto):
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
        if j.get("session_id"):
            c = self.c.post("/api/imports/confirm", headers=self.h,
                            json={"session_id": j["session_id"]})
            assert c.status_code == 200, c.text
        return j


def test_foto_vieja_no_borra_la_plata_que_entro_despues():
    cu = _Cuenta()
    assert cu.caja() == 1000500.0
    j = cu.subir_foto(_foto("05/09/2026", 500))
    # Antes: retiro de $1.000.000 fechado el 05/09 → caja $500.
    assert cu.caja() == 1000500.0
    assert j["caja_sin_ajustar"]["motivo"] == "movimientos_posteriores"
    assert j["caja_sin_ajustar"]["hasta"] == "2026-10-20"
    # Las tenencias coinciden y la caja no se comparó: el mensaje no puede decir
    # que «la cartera ya coincide».
    assert j.get("nothing_to_do")
    assert "no lo comparamos" in j["message"]


def test_foto_del_dia_sigue_ajustando_la_caja():
    """Sin movimientos posteriores, el ajuste es el de siempre."""
    cu = _Cuenta()
    j = cu.subir_foto(_foto("06/11/2026", 500))
    assert j.get("caja_sin_ajustar") is None
    assert cu.caja() == 500.0


def test_un_deposito_a_mano_posterior_tambien_frena_el_ajuste():
    """La plata movida a mano después de la foto cuenta igual que la importada."""
    cu = _Cuenta()
    r = cu.c.post("/api/cash/flow", headers=cu.h,
                  json={"broker_name": "Bull Market", "direction": "deposit",
                        "amount": 20000, "date": "2026-11-05"})
    assert r.status_code == 200, r.text
    assert cu.caja() == 1020500.0
    j = cu.subir_foto(_foto("01/11/2026", 1000500))
    assert j["caja_sin_ajustar"]["motivo"] == "movimientos_posteriores"
    assert j["caja_sin_ajustar"]["hasta"] == "2026-11-05"
    assert cu.caja() == 1020500.0
