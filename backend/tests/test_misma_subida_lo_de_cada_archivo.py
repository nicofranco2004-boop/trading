"""Varios archivos en UNA subida: lo que cada archivo dice sobre sí mismo.

La subida de varios archivos los pega uno abajo del otro (`combine_csv_files`) y
el lector del broker lee el resultado como si fuera un solo archivo. Eso anda
cuando cada fila se entiende sola. Hay formatos donde no:

  - inviu: la MONEDA de cada operación la dice un título de sección que está
    arriba («PESOS - $», «Dólar MEP - U$S»), no la fila. El filtro entre
    archivos borraba los títulos del segundo archivo (son iguales a los del
    primero) y sus operaciones nuevas en pesos quedaban bajo el último título
    del primero: GGAL $50.000 entraba como US$ 50.000.
  - inviu «Consolidada»: el lector deja de leer al llegar a «Disponible -
    Instrumentos» (el resto del archivo repite los títulos en nominales). Con
    dos archivos pegados, dejaba de leer en el PRIMERO y todo el segundo
    quedaba afuera.
  - Bull Market (Movimientos / Histórico en CSV): cada archivo abre con su
    «Saldo anterior». Con dos períodos en la misma subida, el del segundo es el
    cierre del primero, que ya está contado movimiento por movimiento.

Las pruebas suben los archivos por /api/imports/preview y confirman por
/api/imports/confirm: el mismo camino que la pantalla.
"""
import io
import os
import tempfile
import uuid

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ.setdefault("DB_PATH", _TMP.name)

import openpyxl                              # noqa: E402
from fastapi.testclient import TestClient    # noqa: E402

import main                                  # noqa: E402

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class _Cuenta:
    def __init__(self):
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?, 'x', 1, 1)", (f"cada-archivo-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def importar(self, archivos, formato, tipo="text/csv"):
        r = self.client.post(
            "/api/imports/preview", headers=self.h,
            files=[("files", (nombre, io.BytesIO(datos), tipo)) for nombre, datos in archivos],
            data={"format": formato})
        assert r.status_code == 200, r.text
        prev = r.json()
        c = self.client.post("/api/imports/confirm", headers=self.h,
                             json={"session_id": prev["session_id"]})
        assert c.status_code == 200, c.text
        return prev

    def _uno(self, sql, *args):
        conn = main.get_db()
        try:
            return conn.execute(sql, (self.uid,) + args).fetchone()
        finally:
            conn.close()

    def tenencia(self, activo):
        r = self._uno("SELECT COALESCE(SUM(quantity), 0) q FROM positions "
                      "WHERE user_id=? AND asset=? AND COALESCE(is_cash, 0)=0", activo)
        return float(r["q"] or 0)

    def efectivo(self, moneda):
        """El efectivo de una cuenta vive en positions.invested de la fila is_cash.
        La caja en dólares de la cuenta hermana se guarda como USDT."""
        nombres = ("USD", "USDT") if moneda == "USD" else (moneda,)
        r = self._uno("SELECT COALESCE(SUM(invested), 0) v FROM positions "
                      "WHERE user_id=? AND is_cash=1 AND UPPER(asset) IN (?, ?)",
                      *(nombres * 2)[:2])
        return round(float(r["v"] or 0), 2)

    def moneda_de(self, activo, tipo):
        filas = []
        conn = main.get_db()
        try:
            filas = [r["currency"] for r in conn.execute(
                "SELECT n.currency FROM import_normalized_tx n "
                "JOIN import_batches b ON b.id = n.batch_id "
                "WHERE b.user_id=? AND n.asset_symbol=? AND n.operation_type=?",
                (self.uid, activo, tipo))]
        finally:
            conn.close()
        return filas


# ── inviu ────────────────────────────────────────────────────────────────────
# El «Reporte de cuenta corriente» es un Excel con título arriba (el conversor
# busca el encabezado real más abajo) y la moneda en filas de título de sección.

INVIU_HDR = ["Fecha de Concertación", "Fecha de Liquidación", "Descripción",
             "Tipo de Operación", "Ticker", "Cantidad VN", "Precio",
             "Import Bruto", "Importe Neto", "Saldo"]


def _titulo(texto):
    return [texto] + [None] * (len(INVIU_HDR) - 1)


def _inviu(filas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Reporte"
    ws.append(["Reporte de cuenta corriente"])
    ws.append(["Comitente: 99999"])
    ws.append(INVIU_HDR)
    for f in filas:
        ws.append(f)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


MONETARIA = _titulo("Disponible - Cartera monetaria")
PESOS = _titulo("PESOS - $")
MEP = _titulo("Dólar MEP - U$S")
COBRO_PESOS = ["13/3/2024", "13/3/2024", "Recibo de Cobro / 103382", "Recibo de Cobro",
               "-", "-", 0, 300000, 300000, 300000]
COBRO_MEP = ["16/2/2024", "16/2/2024", "Recibo de Cobro / 69500", "Recibo de Cobro",
             "-", "-", 0, 100, 100, 100]


def test_inviu_lo_nuevo_del_segundo_archivo_queda_en_su_moneda():
    """El caso de la revisión del 06/11: GGAL $50.000 entraba como US$ 50.000."""
    ggal = ["2/6/2024", "4/6/2024", "Boleto / 500 / CPRA / 1 / GGAL / $", "CPRA",
            "GGAL", 10, 5000, -50000, -50000, 250000]
    # Y un cobro nuevo en la sección de dólares: con los títulos borrados entraba
    # bien de casualidad en un orden y mal en el otro.
    cobro_mep_nuevo = ["3/6/2024", "3/6/2024", "Recibo de Cobro / 69600", "Recibo de Cobro",
                       "-", "-", 0, 50, 50, 150]
    viejo = _inviu([MONETARIA, PESOS, COBRO_PESOS, MEP, COBRO_MEP])
    nuevo = _inviu([MONETARIA, PESOS, COBRO_PESOS, ggal, MEP, COBRO_MEP, cobro_mep_nuevo])
    for orden in ((viejo, nuevo), (nuevo, viejo)):
        cuenta = _Cuenta()
        cuenta.importar([(f"inviu-{i}.xlsx", a) for i, a in enumerate(orden)], "inviu", XLSX)
        assert cuenta.moneda_de("GGAL", "BUY") == ["ARS"]
        assert cuenta.tenencia("GGAL") == 10
        # Pesos: 300.000 del cobro − 50.000 del GGAL. Dólares: 100 + 50.
        assert cuenta.efectivo("ARS") == 250000.0
        assert cuenta.efectivo("USD") == 150.0


INSTRUMENTOS = _titulo("Disponible - Instrumentos")
COBRO_GRANDE = ["13/3/2024", "13/3/2024", "Recibo de Cobro / 1", "Recibo de Cobro",
                "-", "-", 0, 500000, 500000, 500000]
NVDA = ["13/3/2024", "15/3/2024", "Boleto / 1 / CPRA / 2 / NVDA / $", "CPRA",
        "NVDA", 4, 39316.5, -157266, -159321.15, 340678.85]
YPFD = ["1/6/2026", "2/6/2026", "Boleto / 9 / CPRA / 1 / YPFD / $", "CPRA",
        "YPFD", 2, 83000, -166000, -166000, 174678.85]
# En «Disponible - Instrumentos» los mismos boletos se repiten en NOMINALES.
NVDA_NOMINAL = ["13/3/2024", "15/3/2024", "Boleto / 1 / CPRA / 2 / NVDA / $", "CPRA",
                "NVDA", 4, 39316.5, -157266, 4, 4]
YPFD_NOMINAL = ["1/6/2026", "2/6/2026", "Boleto / 9 / CPRA / 1 / YPFD / $", "CPRA",
                "YPFD", 2, 83000, -166000, 2, 2]


def test_inviu_consolidada_el_segundo_archivo_se_lee_entero():
    """Revisión del 06/11: el lector cortaba en el «Disponible - Instrumentos» del
    PRIMER archivo y lo nuevo del segundo (la compra de YPFD) no entraba."""
    viejo = _inviu([PESOS, COBRO_GRANDE, NVDA, INSTRUMENTOS,
                    _titulo("CEDEAR NVIDIA CORPORATION - NVDA /8469"), NVDA_NOMINAL])
    nuevo = _inviu([PESOS, COBRO_GRANDE, NVDA, YPFD, INSTRUMENTOS,
                    _titulo("CEDEAR NVIDIA CORPORATION - NVDA /8469"), NVDA_NOMINAL,
                    _titulo("YPF S.A. - YPFD /1234"), YPFD_NOMINAL])
    for orden in ((viejo, nuevo), (nuevo, viejo)):
        cuenta = _Cuenta()
        cuenta.importar([(f"consolidada-{i}.xlsx", a) for i, a in enumerate(orden)], "inviu", XLSX)
        assert cuenta.tenencia("YPFD") == 2
        # Y los nominales de «Instrumentos» siguen sin entrar: NVDA una vez.
        assert cuenta.tenencia("NVDA") == 4
        assert cuenta.efectivo("ARS") == 174678.85
        assert cuenta.efectivo("USD") == 0.0


# ── Bull Market: Movimientos / Histórico en CSV ──────────────────────────────

BM_HDR = "Liquida;Cpbt.;Numero;Importe;Saldo;Especie;Referencia/Cantidad/Precio\n"
BM_PIE = (";;;;;COBA;RECIBO DE COBRO\n"
          ";;;;;CPRA;COMPRA\n")

# 2022: abre con $1.000, entra un cobro de $100.000 y compra GGAL por $40.000.
# Cierra con $61.000 (en este layout el signo va invertido: negativo = plata).
BM_2022 = (BM_HDR
           + "31/12/21;Ant.;;-1000;-1000;;S.ANTERIOR\n"
           + "19/01/22;COBA;53066;-100000;-101000;;CREDITO CTA. CTE.\n"
           + "24/01/22;CPRA;251989;40000;-61000;GGAL;100                       400.0000\n"
           + BM_PIE + ";Total;;-61000;;;\n").encode()
# 2023: abre con el cierre de 2022 ($61.000) y entra otro cobro de $20.000.
BM_2023 = (BM_HDR
           + "31/12/22;Ant.;;-61000;-61000;;S.ANTERIOR\n"
           + "10/02/23;COBA;60001;-20000;-81000;;CREDITO CTA. CTE.\n"
           + BM_PIE + ";Total;;-81000;;;\n").encode()


def test_bull_market_dos_periodos_juntos_el_saldo_anterior_cuenta_una_vez():
    """Revisión del 06/11: el «Saldo anterior» de 2023 ($61.000) es el cierre de
    2022, que ya está contado movimiento por movimiento. Sumarlo inflaba el
    efectivo y el capital aportado en $61.000."""
    for orden in ((BM_2022, BM_2023), (BM_2023, BM_2022)):
        cuenta = _Cuenta()
        cuenta.importar([(f"bm-{i}.csv", a) for i, a in enumerate(orden)], "bullmarket")
        # 1.000 de apertura + 100.000 − 40.000 + 20.000.
        assert cuenta.efectivo("ARS") == 81000.0
        assert cuenta.tenencia("GGAL") == 100


def test_bull_market_un_periodo_solo_el_saldo_anterior_entra():
    """Sin otro período en la subida ni en la cuenta, el saldo de apertura es
    plata real: si no entra, el efectivo arranca corrido."""
    cuenta = _Cuenta()
    cuenta.importar([("bm-2023.csv", BM_2023)], "bullmarket")
    assert cuenta.efectivo("ARS") == 81000.0


def test_bull_market_dos_periodos_que_se_pisan():
    """El segundo arranca a mitad del primero: su saldo de apertura es lo que
    el primero ya trae hasta ese día, y las operaciones compartidas van una vez."""
    medio = (BM_HDR
             + "20/01/22;Ant.;;-101000;-101000;;S.ANTERIOR\n"
             + "24/01/22;CPRA;251989;40000;-61000;GGAL;100                       400.0000\n"
             + "10/02/23;COBA;60001;-20000;-81000;;CREDITO CTA. CTE.\n"
             + BM_PIE + ";Total;;-81000;;;\n").encode()
    for orden in ((BM_2022, medio), (medio, BM_2022)):
        cuenta = _Cuenta()
        cuenta.importar([(f"bm-{i}.csv", a) for i, a in enumerate(orden)], "bullmarket")
        assert cuenta.efectivo("ARS") == 81000.0
        assert cuenta.tenencia("GGAL") == 100


# El layout «Histórico compacto» (el que Bull Market manda por mail) ya tenía
# esta regla adentro de su lector; ahora la comparte con el de arriba.
HC_HDR = "F.Liquid;Cpbt;N.Cpbt;Importe;Dolares;Mda;Ref./Cantidad\n"
HC_2021 = (HC_HDR
           + "11/04/21;COBA;145726;-5000;;;CREDITO CTA. CTE.\n"
           + "15/04/21;PAGA;145727;4000;;;TRANSFERENCIA VIA MEP\n").encode()
HC_2023 = (HC_HDR
           + ";S.ANT;ERIOR;-1000;;;\n"
           + "02/01/23;COBA;6668;-500000;;;CREDITO CTA. CTE.\n").encode()


def test_historico_compacto_dos_periodos_juntos():
    for orden in ((HC_2021, HC_2023), (HC_2023, HC_2021)):
        cuenta = _Cuenta()
        cuenta.importar([(f"hc-{i}.csv", a) for i, a in enumerate(orden)], "bullmarket")
        # 5.000 − 4.000 de 2021 + 500.000 de 2023; los 1.000 de apertura de 2023
        # son el cierre de 2021.
        assert cuenta.efectivo("ARS") == 501000.0



def test_el_periodo_anterior_con_movimientos_justo_el_dia_del_saldo():
    """El saldo anterior es el de AL CIERRE de su día: un movimiento de ese mismo
    día del otro archivo ya está adentro. Es el borde de la regla (≤, no <), en
    los dos layouts: es la que el Histórico compacto tenía antes de compartirla."""
    # Histórico compacto: el saldo se fecha el día anterior al primer movimiento
    # que tiene abajo (02/01/23 → 01/01/23).
    hc_dia_antes = (HC_HDR + "01/01/23;COBA;1;-1000;;;CREDITO CTA. CTE.\n").encode()
    # Movimientos: el saldo viene fechado (31/12/22).
    bm_dia_antes = (BM_HDR + "31/12/22;COBA;1;-61000;-61000;;CREDITO CTA. CTE.\n"
                    + BM_PIE + ";Total;;-61000;;;\n").encode()
    for anterior, siguiente, esperado in ((hc_dia_antes, HC_2023, 501000.0),
                                          (bm_dia_antes, BM_2023, 81000.0)):
        for orden in ((anterior, siguiente), (siguiente, anterior)):
            cuenta = _Cuenta()
            cuenta.importar([(f"p-{i}.csv", a) for i, a in enumerate(orden)], "bullmarket")
            assert cuenta.efectivo("ARS") == esperado

# ── Leídos de a uno: cada fila sigue unida a SUS errores ─────────────────────

def test_leidos_de_a_uno_las_filas_y_sus_errores_no_se_pisan():
    """El número de fila une cada fila con sus errores. Leídos de a uno, los dos
    archivos arrancan en 1: sin renumerar, el error de la fila 1 del segundo se
    le pegaba a la fila 1 del primero."""
    from importing.pipeline import _parsear
    from importing.schema import ParseResult, RawRow, RowError

    class _Lector:
        lee_cada_archivo_aparte = True

        def parse(self, content, file_name=None):
            r = ParseResult()
            filas = content.splitlines()[1:]
            for i, f in enumerate(filas, start=1):
                r.raw_rows.append(RawRow(row_index=i, data={"f": f}))
            r.parse_errors.append(RowError(1, None, "MALA", f"fila {filas[0]}", file_row=1))
            r.parse_errors.append(RowError(-1, None, "OMITIDA", "omitida", file_row=2))
            r.parse_errors.append(RowError(0, None, "ARCHIVO", "aviso del archivo"))
            return r

    r = _parsear(_Lector(), "", "x", ["h\na1\na2", "h\nb1"])
    assert [(x.row_index, x.data["f"]) for x in r.raw_rows] == [(1, "a1"), (2, "a2"), (3, "b1")]
    errores = {(e.code, e.row_index): (e.message, e.file_row) for e in r.parse_errors}
    assert errores[("MALA", 1)] == ("fila a1", 1)
    assert errores[("MALA", 3)] == ("fila b1", 3)
    assert ("OMITIDA", -1) in errores and ("OMITIDA", -2) in errores
    # El aviso del archivo entero, una sola vez.
    assert [e.code for e in r.parse_errors].count("ARCHIVO") == 1
