"""Dos Excel de la MISMA cuenta que se pisan en fechas, subidos juntos.

Caso real (2026-11-06, Bull Market): la persona subió tres Cuenta Corriente de
PESOS bajadas en días distintos (06/11, 30/10 y 28/06) para tener más historia.
Cada operación que estaba en dos archivos entró dos veces, y las que estaban en
los tres, tres veces: 130 de 297 filas de más en la vista previa.

`combine_csv_files` ya descartaba la fila repetida entre archivos, pero sólo si
era idéntica letra por letra. En un Excel nunca lo es:
  - el conversor de Excel le agrega a cada fila el nombre de la hoja (`_hoja`) y
    Bull Market nombra la hoja con la fecha de descarga ("Cuenta Corriente
    PESOS 06-11-26"), así que la misma operación dice "…06-11-26" en un archivo
    y "…30-10-26" en el otro;
  - el saldo acumulado de cada fila depende de desde qué fecha se bajó.
Ninguna de las dos cosas dice qué operación es. El filtro ahora las ignora; todo
lo demás (fechas, comprobante, número, especie, cantidad, precio, importe) tiene
que seguir siendo igual.

La prueba de punta a punta sube los archivos por /api/imports/preview y confirma
por /api/imports/confirm: el mismo camino que la pantalla.
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
from importing.pipeline import combine_csv_files   # noqa: E402

HDR = ["Liquida", "Operado", "Comprobante", "Numero", "Cantidad",
       "Especie", "Precio", "Importe", "Saldo", "Referencia"]

# Las operaciones, con el número de comprobante real de Bull Market.
DEPOSITO = [datetime(2026, 9, 1), datetime(2026, 9, 1), "RECIBO DE COBRO",
            765773, 0, None, 0, 3000000]
AVGO = [datetime(2026, 9, 3), datetime(2026, 9, 3), "COMPRA NORMAL",
        8188607, 23, "AVGO", 14173.7, -325995.16]
GS = [datetime(2026, 9, 18), datetime(2026, 9, 18), "COMPRA NORMAL",
      8758224, 6, "GS", 118156.13, -708936.79]
MA = [datetime(2026, 10, 26), datetime(2026, 10, 26), "COMPRA NORMAL",
      9972711, 25, "MA", 31568.70, -789217.52]
TSM = [datetime(2026, 11, 5), datetime(2026, 11, 5), "COMPRA NORMAL",
       10380700, 12, "TSM", 52000.0, -624000.0]


def _cuenta_corriente(hoja, filas, saldo_inicial=0.0):
    """Un Excel como el que baja Bull Market: el saldo de cada fila arranca en el
    saldo del día en que empieza la descarga, y la hoja lleva la fecha."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = hoja
    ws.append(HDR)
    saldo = saldo_inicial
    for f in filas:
        saldo += f[7]
        ws.append(list(f) + [round(saldo, 2), None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class _Cuenta:
    def __init__(self):
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?, 'x', 1, 1)", (f"solapados-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def importar(self, archivos):
        r = self.client.post(
            "/api/imports/preview", headers=self.h,
            files=[("files", (nombre, io.BytesIO(datos),
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
                   for nombre, datos in archivos],
            data={"format": "bullmarket"})
        assert r.status_code == 200, r.text
        prev = r.json()
        c = self.client.post("/api/imports/confirm", headers=self.h,
                             json={"session_id": prev["session_id"]})
        assert c.status_code == 200, c.text
        return prev

    def cantidad(self, activo):
        conn = main.get_db()
        try:
            r = conn.execute(
                "SELECT COALESCE(SUM(quantity), 0) q FROM positions "
                "WHERE user_id=? AND asset=? AND COALESCE(is_cash, 0)=0",
                (self.uid, activo)).fetchone()
            return float(r["q"] or 0)
        finally:
            conn.close()

    def filas_del_lote(self, batch_id):
        conn = main.get_db()
        try:
            return conn.execute(
                "SELECT COUNT(*) n FROM import_normalized_tx WHERE batch_id=?",
                (batch_id,)).fetchone()["n"]
        finally:
            conn.close()


def test_dos_cuentas_corrientes_de_pesos_que_se_pisan_no_duplican():
    cuenta = _Cuenta()
    # Bajada el 30/10: arranca el 01/09.
    del_30_10 = _cuenta_corriente("Cuenta Corriente PESOS 30-10-26",
                                  [DEPOSITO, AVGO, GS, MA])
    # Bajada el 06/11: arranca después del depósito, así que su saldo
    # acumulado es distinto para las mismas operaciones.
    del_06_11 = _cuenta_corriente("Cuenta Corriente PESOS 06-11-26",
                                  [AVGO, GS, MA, TSM], saldo_inicial=3000000)
    prev = cuenta.importar([("Cuenta Corriente PESOS 30-10-26.xlsx", del_30_10),
                            ("Cuenta Corriente PESOS 06-11-26.xlsx", del_06_11)])

    assert cuenta.cantidad("AVGO") == 23
    assert cuenta.cantidad("GS") == 6
    assert cuenta.cantidad("MA") == 25
    assert cuenta.cantidad("TSM") == 12
    # 1 depósito + 4 compras: cada operación una sola vez.
    assert cuenta.filas_del_lote(prev["session_id"]) == 5


def test_tres_archivos_la_misma_operacion_entra_una_vez():
    """Lo que hizo Matias: tres exportaciones, la del medio pisa a las otras dos."""
    cuenta = _Cuenta()
    a = _cuenta_corriente("Cuenta Corriente PESOS 28-06-26", [DEPOSITO, AVGO])
    b = _cuenta_corriente("Cuenta Corriente PESOS 30-10-26", [DEPOSITO, AVGO, GS, MA])
    c = _cuenta_corriente("Cuenta Corriente PESOS 06-11-26", [GS, MA, TSM],
                          saldo_inicial=2674004.84)
    cuenta.importar([("PESOS 06-11-26.xlsx", c), ("PESOS 30-10-26.xlsx", b),
                     ("PESOS 28-06-26.xlsx", a)])
    assert [cuenta.cantidad(t) for t in ("AVGO", "GS", "MA", "TSM")] == [23, 6, 25, 12]


def _movimientos_ppi(filas):
    """Un Excel de movimientos de PPI: sin número de operación, con saldo."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Pesos"
    ws.append(["Fecha", "Descripción", "Cantidad", "Precio", "Importe", "Saldo", "Moneda"])
    for f in filas:
        ws.append(list(f) + ["Pesos"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


INGRESO = ("12/06/2026", "Ingreso de Fondos", 0, 0, 2000000, 2000000)
NU_1 = ("12/06/2026", "COMPRA NU", 100, 8730, -873000, 1127000)
NU_2 = ("12/06/2026", "COMPRA NU", 100, 8730, -873000, 254000)


def _importar_ppi(cuenta, archivos):
    r = cuenta.client.post(
        "/api/imports/preview", headers=cuenta.h,
        files=[("files", (n, io.BytesIO(d),
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
               for n, d in archivos],
        data={"format": "ppi"})
    assert r.status_code == 200, r.text
    c = cuenta.client.post("/api/imports/confirm", headers=cuenta.h,
                           json={"session_id": r.json()["session_id"]})
    assert c.status_code == 200, c.text


def test_dos_compras_iguales_del_mismo_dia_sin_numero_entran_las_dos():
    """Hallazgo de la revisión (06/11): sin número de operación, dos compras
    iguales del mismo día sólo se distinguen por el saldo. Si un archivo se bajó
    a media mañana (tiene una) y el otro a la tarde (tiene las dos), son DOS
    compras, en cualquier orden. Con una lista sin conteo, la segunda del
    archivo de la tarde se descartaba porque "ya había venido" una igual."""
    for orden in ("manana_primero", "tarde_primero"):
        cuenta = _Cuenta()
        manana = ("manana.xlsx", _movimientos_ppi([INGRESO, NU_1]))
        tarde = ("tarde.xlsx", _movimientos_ppi([INGRESO, NU_1, NU_2]))
        _importar_ppi(cuenta, [manana, tarde] if orden == "manana_primero" else [tarde, manana])
        assert cuenta.cantidad("NU") == 200, orden


# ── El filtro solo, sobre el texto ya convertido ─────────────────────────────

HDR_CSV = "Liquida,Operado,Comprobante,Numero,Cantidad,Especie,Precio,Importe,Saldo,Referencia,_hoja"


def _combinar(*archivos):
    out, _n, err = combine_csv_files([(a.encode(), f"{i}.csv") for i, a in enumerate(archivos)])
    assert err is None
    return out.decode().splitlines()[1:]


def test_la_hoja_de_otra_subcuenta_no_se_confunde():
    """Pesos y dólares son cuentas distintas: la misma línea en las dos NO es la
    misma operación. Lo que se ignora de la hoja es la fecha, no la moneda."""
    fila = "2026-09-03,2026-09-03,RECIBO DE COBRO,1,0,,0,1000,1000,,"
    pesos = f"{HDR_CSV}\n{fila}Cuenta Corriente PESOS 06-11-26\n"
    dolares = f"{HDR_CSV}\n{fila}Cuenta Corriente DOLARES 06-11-26\n"
    assert len(_combinar(pesos, dolares)) == 2


def test_de_la_hoja_se_ignora_la_fecha_no_cualquier_numero():
    """"Comitente 1234" y "Comitente 5678" son cuentas distintas: un número
    suelto no es la fecha de descarga y sigue distinguiendo (revisión del 06/11)."""
    fila = "2026-09-03,2026-09-03,RECIBO DE COBRO,1,0,,0,1000,{s},,"
    a = f"{HDR_CSV}\n{fila.format(s=1000)}Comitente 1234\n"
    b = f"{HDR_CSV}\n{fila.format(s=5000)}Comitente 5678\n"
    assert len(_combinar(a, b)) == 2


def test_la_fecha_cortada_por_el_limite_de_excel_tambien_se_ignora():
    """Excel corta el nombre de la hoja en 31 letras: "Cuenta Corriente DOLARES
    06-11-26" queda "Cuenta Corriente DOLARES 06-11-"."""
    fila = "2026-09-03,2026-09-03,DIVIDENDOS,7,0,AAPL,0,0.18,{s},,{h}"
    a = f"{HDR_CSV}\n" + fila.format(s=1, h="Cuenta Corriente DOLARES 06-11-") + "\n"
    b = f"{HDR_CSV}\n" + fila.format(s=9, h="Cuenta Corriente DOLARES 30-10-") + "\n"
    assert len(_combinar(a, b)) == 1


def test_la_cuenta_se_hace_por_archivo_no_por_conjunto():
    """Una vez en el primero, dos veces en el segundo → dos (la segunda del
    segundo es otra operación). Al revés, también dos."""
    fila = "12/06/2026,COMPRA NU,100,8730,-873000,{s},Pesos,,Pesos"
    hdr = "Fecha,Descripción,Cantidad,Precio,Importe,Saldo,Moneda,Especie,_hoja"
    uno = f"{hdr}\n{fila.format(s=1127000)}\n"
    dos = f"{hdr}\n{fila.format(s=1127000)}\n{fila.format(s=254000)}\n"
    for archivos in ((uno, dos), (dos, uno)):
        out, _n, err = combine_csv_files([(a.encode(), f"{i}.csv") for i, a in enumerate(archivos)])
        assert err is None
        assert len(out.decode().splitlines()[1:]) == 2


def test_dentro_de_un_mismo_archivo_no_se_toca_nada():
    fila = "2026-09-03,2026-09-03,COMPRA NORMAL,5,1,AL30,100,-100,{s},,Cuenta Corriente PESOS 06-11-26"
    uno = f"{HDR_CSV}\n{fila.format(s=-100)}\n{fila.format(s=-200)}\n"
    otro = f"{HDR_CSV}\n" + fila.format(s=-50).replace("06-11-26", "30-10-26") + "\n"
    # Las dos del primer archivo quedan (distinto saldo, mismo archivo); la del
    # segundo es la misma operación que ya vino → afuera.
    assert len(_combinar(uno, otro)) == 2


def test_lo_que_dice_que_operacion_es_sigue_contando():
    """Si cambia el número de comprobante, el importe o la fecha, son
    operaciones distintas aunque el saldo y la hoja coincidan."""
    base = "2026-09-03,2026-09-03,COMPRA NORMAL,{n},1,AL30,100,{imp},0,,Hoja"
    a = f"{HDR_CSV}\n{base.format(n=5, imp=-100)}\n"
    b = f"{HDR_CSV}\n{base.format(n=6, imp=-100)}\n{base.format(n=5, imp=-101)}\n"
    assert len(_combinar(a, b)) == 3


def test_csv_sin_columnas_que_cambien_sigue_igual():
    """Un CSV sin `_hoja` ni saldo: la regla de siempre (línea idéntica)."""
    a = "fecha;monto\n01-01-2026;100\n02-01-2026;200\n"
    b = "fecha;monto\n02-01-2026;200\n03-01-2026;300\n"
    assert _combinar(a, b) == ["01-01-2026;100", "02-01-2026;200", "03-01-2026;300"]
