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

    def importar(self, archivos, formato, tipo="text/csv", seed_state=None):
        r = self.client.post(
            "/api/imports/preview", headers=self.h,
            files=[("files", (nombre, io.BytesIO(datos), tipo)) for nombre, datos in archivos],
            data={"format": formato})
        assert r.status_code == 200, r.text
        prev = r.json()
        cuerpo = {"session_id": prev["session_id"]}
        if seed_state is not None:
            cuerpo["seed_state"] = seed_state
        c = self.client.post("/api/imports/confirm", headers=self.h, json=cuerpo)
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

    def saldos_anteriores(self):
        """(fecha, moneda, monto) de cada «Saldo anterior» que entró."""
        conn = main.get_db()
        try:
            return sorted((r["date"], r["currency"], r["gross_amount"]) for r in conn.execute(
                "SELECT n.date, n.currency, n.gross_amount FROM import_normalized_tx n "
                "JOIN import_batches b ON b.id = n.batch_id "
                "WHERE b.user_id=? AND b.status='confirmed' AND n.notes='Saldo anterior'",
                (self.uid,)))
        finally:
            conn.close()

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


def _inviu(filas, preambulo=True):
    """Con preámbulo (título arriba, como el real) la hoja no llega a las filas;
    sin preámbulo, el conversor le pega a CADA fila el nombre de la hoja."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Reporte"
    if preambulo:
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


def test_inviu_titulos_con_saldo_o_con_relleno_siguen_siendo_titulos():
    """No sabemos si el Excel real deja el título solo en su fila o le pone el
    saldo de la sección al lado, o guiones de relleno. El filtro ignora el saldo
    para comparar: un título con saldo distinto en cada archivo (cada uno arranca
    otro día) quedaba igual al del primero y se borraba. Auditoría del 06/11."""
    def con_saldo(texto, saldo):
        return [texto] + [None] * (len(INVIU_HDR) - 2) + [saldo]

    def con_relleno(texto):
        return [texto] + ["-"] * (len(INVIU_HDR) - 2) + [0]

    def con_ceros(texto):
        return [texto, None, None, None, None, None, 0, 0, 0, None]

    ggal = ["2/6/2024", "4/6/2024", "Boleto / 500 / CPRA / 1 / GGAL / $", "CPRA",
            "GGAL", 10, 5000, -50000, -50000, 250000]
    cobro_mep_nuevo = ["3/6/2024", "3/6/2024", "Recibo de Cobro / 69600", "Recibo de Cobro",
                       "-", "-", 0, 50, 50, 150]
    for titulo in (lambda t, s: con_saldo(t, s), lambda t, s: con_relleno(t),
                   lambda t, s: con_ceros(t)):
        viejo = _inviu([titulo("PESOS - $", 500), COBRO_PESOS,
                        titulo("Dólar MEP - U$S", 3), COBRO_MEP])
        nuevo = _inviu([titulo("PESOS - $", 1000), COBRO_PESOS, ggal,
                        titulo("Dólar MEP - U$S", 7), COBRO_MEP, cobro_mep_nuevo])
        for orden in ((viejo, nuevo), (nuevo, viejo)):
            cuenta = _Cuenta()
            cuenta.importar([(f"inviu-{i}.xlsx", a) for i, a in enumerate(orden)], "inviu", XLSX)
            assert cuenta.moneda_de("GGAL", "BUY") == ["ARS"]
            assert cuenta.efectivo("ARS") == 250000.0
            assert cuenta.efectivo("USD") == 150.0


def test_inviu_sin_preambulo_el_titulo_trae_la_hoja_y_sigue_siendo_titulo():
    """Sin preámbulo, el conversor de Excel le pega el nombre de la hoja a cada
    fila, títulos incluidos: el título tiene DOS celdas llenas. La hoja no dice
    qué operación es, así que no cuenta (revisión independiente del 06/11)."""
    ggal = ["2/6/2024", "4/6/2024", "Boleto / 500 / CPRA / 1 / GGAL / $", "CPRA",
            "GGAL", 10, 5000, -50000, -50000, 250000]
    cobro_mep_nuevo = ["3/6/2024", "3/6/2024", "Recibo de Cobro / 69600", "Recibo de Cobro",
                       "-", "-", 0, 50, 50, 150]
    viejo = _inviu([MONETARIA, PESOS, COBRO_PESOS, MEP, COBRO_MEP], preambulo=False)
    nuevo = _inviu([MONETARIA, PESOS, COBRO_PESOS, ggal, MEP, COBRO_MEP, cobro_mep_nuevo],
                   preambulo=False)
    for orden in ((viejo, nuevo), (nuevo, viejo)):
        cuenta = _Cuenta()
        cuenta.importar([(f"inviu-{i}.xlsx", a) for i, a in enumerate(orden)], "inviu", XLSX)
        assert cuenta.moneda_de("GGAL", "BUY") == ["ARS"]
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


def test_bull_market_una_fecha_ilegible_no_tira_el_saldo_de_un_archivo_solo():
    """Una fecha que el lector no entiende queda como texto crudo, y comparar
    «19/01/2023 10:00» con «2022-12-31» como texto da «es anterior»: el saldo
    de apertura de un archivo subido SOLO se descartaba. Auditoría del 06/11."""
    solo = (BM_HDR
            + "31/12/22;Ant.;;-61000;-61000;;S.ANTERIOR\n"
            + "19/01/2023 10:00;COBA;59999;-5000;-66000;;CREDITO CTA. CTE.\n"
            + "10/02/23;COBA;60001;-20000;-86000;;CREDITO CTA. CTE.\n"
            + BM_PIE + ";Total;;-86000;;;\n").encode()
    cuenta = _Cuenta()
    cuenta.importar([("bm-2023.csv", solo)], "bullmarket")
    # 61.000 de apertura + 20.000; la fila de fecha ilegible no entra (error).
    assert cuenta.efectivo("ARS") == 81000.0

def test_bull_market_de_a_uno_con_una_venta_cargada_a_mano_antes():
    """Subiendo de a uno, una venta cargada A MANO antes del período del archivo
    también cuenta como historia previa (`drop_saldo_anterior_ya_contado` mira
    la tabla de operaciones). Nadie lo probaba: sacarlo pasaba todas las pruebas.
    Ojo, medido el 06/11: esa tabla sólo tiene las VENTAS. Un depósito o una
    compra cargados a mano no van ahí, y esta regla no los ve."""
    cuenta = _Cuenta()
    r = cuenta.client.post("/api/brokers", headers=cuenta.h,
                           json={"name": "Bull Market", "currency": "ARS"})
    assert r.status_code == 200, r.text
    r = cuenta.client.post("/api/positions", headers=cuenta.h, json={
        "broker": "Bull Market", "asset": "YPFD", "currency": "ARS", "quantity": 1,
        "buy_price": 1000, "invested": 1000, "entry_date": "2022-06-01"})
    assert r.status_code == 200, r.text
    r = cuenta.client.post("/api/positions/sell", headers=cuenta.h, json={
        "broker": "Bull Market", "asset": "YPFD", "quantity": 1, "exit_price": 1200,
        "currency": "ARS", "date": "2022-07-01"})
    assert r.status_code == 200, r.text
    antes = cuenta.efectivo("ARS")
    cuenta.importar([("bm-2023.csv", BM_2023)], "bullmarket")
    # Sólo entra el cobro de 20.000; los 61.000 de apertura no.
    assert cuenta.efectivo("ARS") - antes == 20000.0


def test_historico_compacto_saldo_anterior_en_dolares():
    """Con `Mda` lleno el saldo es de la cuenta en DÓLARES y la plata es la de
    `Dolares` (US$100), no el equivalente en pesos de `Importe` (150.000).
    Ninguna prueba tenía un saldo en dólares (revisión independiente)."""
    hc = (HC_HDR + ";S.ANT;ERIOR;-150000;-100;DOLAR;\n"
          + "02/01/23;COBA;6668;-500000;;;CREDITO CTA. CTE.\n").encode()
    cuenta = _Cuenta()
    cuenta.importar([("hc.csv", hc)], "bullmarket")
    assert cuenta.efectivo("USD") == 100.0
    assert cuenta.efectivo("ARS") == 500000.0


def test_bull_market_de_a_uno_la_subida_anterior_cruza_la_fecha_del_saldo():
    """Lo ya importado empieza ANTES del saldo y termina DESPUÉS: alcanza con
    que algo sea de ese día o de antes (con «el último» en vez de «el primero»
    entraba dos veces; revisión independiente)."""
    temprano = (BM_HDR
                + "10/01/22;Ant.;;-1000;-1000;;S.ANTERIOR\n"
                + "19/01/22;COBA;53066;-100000;-101000;;CREDITO CTA. CTE.\n"
                + "24/01/22;CPRA;251989;40000;-61000;GGAL;100                       400.0000\n"
                + "10/02/23;COBA;60001;-20000;-81000;;CREDITO CTA. CTE.\n"
                + BM_PIE + ";Total;;-81000;;;\n").encode()
    cuenta = _Cuenta()
    cuenta.importar([("temprano.csv", temprano)], "bullmarket")
    cuenta.importar([("bm-2023.csv", BM_2023)], "bullmarket")
    assert cuenta.efectivo("ARS") == 81000.0


def test_bull_market_de_a_uno_una_fecha_vieja_mal_escrita_no_tapa_las_demas():
    """Si en la cuenta quedó una fila vieja con la fecha en otro formato
    («15/06/2022»), como texto es la «más chica» y tapaba a las buenas: el
    control de subidas anteriores no veía nada (revisión independiente)."""
    cuenta = _Cuenta()
    r = cuenta.client.post("/api/brokers", headers=cuenta.h,
                           json={"name": "Bull Market", "currency": "ARS"})
    assert r.status_code == 200, r.text
    for fecha in ("2022-06-02", "2022-07-01"):
        r = cuenta.client.post("/api/positions", headers=cuenta.h, json={
            "broker": "Bull Market", "asset": "YPFD", "currency": "ARS", "quantity": 1,
            "buy_price": 1000, "invested": 1000, "entry_date": "2022-06-01"})
        assert r.status_code == 200, r.text
        r = cuenta.client.post("/api/positions/sell", headers=cuenta.h, json={
            "broker": "Bull Market", "asset": "YPFD", "quantity": 1, "exit_price": 1200,
            "currency": "ARS", "date": fecha})
        assert r.status_code == 200, r.text
    # Una fila heredada con la fecha escrita a la argentina.
    conn = main.get_db()
    conn.execute("UPDATE operations SET date='15/06/2022' WHERE user_id=? AND date='2022-06-02'",
                 (cuenta.uid,))
    conn.commit()
    conn.close()
    antes = cuenta.efectivo("ARS")
    cuenta.importar([("bm-2023.csv", BM_2023)], "bullmarket")
    assert cuenta.efectivo("ARS") - antes == 20000.0


def test_confirmar_con_estado_inicial_no_trae_de_vuelta_el_saldo():
    """Confirmar con «Estado inicial» vuelve a leer las filas crudas del lote, y
    no pasaba por el control del saldo: el que la vista previa había sacado
    volvía a entrar (142.000 en vez de 81.000; revisión independiente)."""
    cuenta = _Cuenta()
    cuenta.importar([("bm-2022.csv", BM_2022)], "bullmarket")
    cuenta.importar([("bm-2023.csv", BM_2023)], "bullmarket",
                    seed_state={"seed_date": "2022-12-30", "brokers": []})
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



def test_bull_market_el_periodo_viejo_sin_movimientos():
    """Revisión independiente del 06/11: si el período viejo no tuvo movimientos,
    ninguno queda «antes» del saldo del nuevo, y los dos saldos entraban. Son la
    misma plata (nada se movió en el medio): entra sólo el más viejo."""
    quieto = (BM_HDR + "31/12/21;Ant.;;-1000;-1000;;S.ANTERIOR\n"
              + BM_PIE + ";Total;;-1000;;;\n").encode()
    nuevo = (BM_HDR + "31/12/22;Ant.;;-1000;-1000;;S.ANTERIOR\n"
             + "10/02/23;COBA;60001;-20000;-21000;;CREDITO CTA. CTE.\n"
             + BM_PIE + ";Total;;-21000;;;\n").encode()
    for orden in ((quieto, nuevo), (nuevo, quieto)):
        cuenta = _Cuenta()
        cuenta.importar([(f"bm-{i}.csv", a) for i, a in enumerate(orden)], "bullmarket")
        assert cuenta.efectivo("ARS") == 21000.0
        # El que entra es el más viejo: la plata ya estaba el 31/12/21.
        assert cuenta.saldos_anteriores() == [("2021-12-31", "ARS", 1000.0)]


def test_bull_market_dos_cuentas_distintas_en_la_misma_subida():
    """Revisión independiente (2ª pasada, 06/11): dos cuentas de Bull Market
    subidas juntas. Sin movimientos entre los dos saldos, si fueran de la MISMA
    cuenta darían igual; distintos, son de cuentas distintas y entran los dos.
    «Sólo el más viejo» a secas tiraba el de la segunda: 13.000 en vez de
    18.000."""
    x = (BM_HDR + "31/12/22;Ant.;;-1000;-1000;;S.ANTERIOR\n"
         + "10/08/23;COBA;1;-10000;-11000;;CREDITO CTA. CTE.\n"
         + BM_PIE + ";Total;;-11000;;;\n").encode()
    y = (BM_HDR + "30/06/23;Ant.;;-5000;-5000;;S.ANTERIOR\n"
         + "10/07/23;COBA;2;-2000;-7000;;CREDITO CTA. CTE.\n"
         + BM_PIE + ";Total;;-7000;;;\n").encode()
    # Y el mismo día, con montos distintos: también son dos cuentas.
    y_mismo_dia = (BM_HDR + "31/12/22;Ant.;;-5000;-5000;;S.ANTERIOR\n"
                   + "10/07/23;COBA;2;-2000;-7000;;CREDITO CTA. CTE.\n"
                   + BM_PIE + ";Total;;-7000;;;\n").encode()
    for otra in (y, y_mismo_dia):
        for orden in ((x, otra), (otra, x)):
            cuenta = _Cuenta()
            cuenta.importar([(f"bm-{i}.csv", a) for i, a in enumerate(orden)], "bullmarket")
            assert cuenta.efectivo("ARS") == 18000.0


def test_bull_market_el_segundo_arranca_antes_del_primer_movimiento_del_primero():
    """Revisión independiente del 06/11: el segundo archivo arranca el 10/01/22,
    antes del primer movimiento del primero (19/01/22). Su saldo es la misma
    apertura del primero, que ya entró."""
    temprano = (BM_HDR
                + "10/01/22;Ant.;;-1000;-1000;;S.ANTERIOR\n"
                + "19/01/22;COBA;53066;-100000;-101000;;CREDITO CTA. CTE.\n"
                + "24/01/22;CPRA;251989;40000;-61000;GGAL;100                       400.0000\n"
                + "10/02/23;COBA;60001;-20000;-81000;;CREDITO CTA. CTE.\n"
                + BM_PIE + ";Total;;-81000;;;\n").encode()
    for orden in ((BM_2022, temprano), (temprano, BM_2022)):
        cuenta = _Cuenta()
        cuenta.importar([(f"bm-{i}.csv", a) for i, a in enumerate(orden)], "bullmarket")
        assert cuenta.efectivo("ARS") == 81000.0
        assert cuenta.tenencia("GGAL") == 100


def test_bull_market_se_compara_por_liquidacion_no_por_concertacion():
    """Una compra concertada el 29/12/22 que se liquida el 03/01/23 es del
    período 2023, aunque su concertación caiga antes del saldo del 31/12/22. Por
    concertación, el archivo SOLO perdía su saldo de apertura (revisión
    independiente del 06/11: efectivo −40.000 en vez de 60.000)."""
    hdr = "Liquida;Operado;Cpbt.;Numero;Importe;Saldo;Especie;Referencia/Cantidad/Precio\n"
    solo = (hdr
            + "31/12/22;;Ant.;;-100000;-100000;;S.ANTERIOR\n"
            + "03/01/23;29/12/22;CPRA;1;40000;-60000;GGAL;100                       400.0000\n"
            + ";;;;;;CPRA;COMPRA\n").encode()
    cuenta = _Cuenta()
    cuenta.importar([("bm-2023.csv", solo)], "bullmarket")
    assert cuenta.efectivo("ARS") == 60000.0
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
    los dos layouts, y vale igual subiendo los archivos juntos o de a uno: hasta
    la revisión independiente del 06/11, de a uno se comparaba con «<» y el
    saldo entraba dos veces. Los dos cobros de ese día suman el saldo pero no son
    iguales a él, para que no los tape el filtro de filas ya importadas."""
    # Histórico compacto: el saldo se fecha el día anterior al primer movimiento
    # que tiene abajo (02/01/23 → 01/01/23).
    hc_dia_antes = (HC_HDR + "01/01/23;COBA;1;-600;;;CREDITO CTA. CTE.\n"
                    + "01/01/23;COBA;2;-400;;;CREDITO CTA. CTE.\n").encode()
    # Movimientos: el saldo viene fechado (31/12/22).
    bm_dia_antes = (BM_HDR + "31/12/22;COBA;1;-60000;-60000;;CREDITO CTA. CTE.\n"
                    + "31/12/22;COBA;2;-1000;-61000;;CREDITO CTA. CTE.\n"
                    + BM_PIE + ";Total;;-61000;;;\n").encode()
    for anterior, siguiente, esperado in ((hc_dia_antes, HC_2023, 501000.0),
                                          (bm_dia_antes, BM_2023, 81000.0)):
        for orden in ((anterior, siguiente), (siguiente, anterior)):
            cuenta = _Cuenta()
            cuenta.importar([(f"p-{i}.csv", a) for i, a in enumerate(orden)], "bullmarket")
            assert cuenta.efectivo("ARS") == esperado, "juntos"
        cuenta = _Cuenta()
        cuenta.importar([("anterior.csv", anterior)], "bullmarket")
        cuenta.importar([("siguiente.csv", siguiente)], "bullmarket")
        assert cuenta.efectivo("ARS") == esperado, "de a uno"


# ── Quién lee de a un archivo y quién no ─────────────────────────────────────

COCOS_HDR = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;"
             "instrumento;moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;"
             "otros;total\n")


def test_cocos_el_dolar_mep_partido_entre_dos_archivos_sigue_siendo_conversion():
    """Comprar un bono en pesos y venderlo por dólares (dólar MEP) es UNA
    conversión, aunque la compra caiga en el archivo de diciembre y la venta en
    el de enero. Cocos empareja las dos patas, y sólo puede si lee los archivos
    juntos: leído de a uno, quedaba una compra y una venta del bono."""
    dic = (COCOS_HDR
           + "1;;20-12-2025;20-12-2025;Recibo De Cobro;;ARS;;;;1.000.000;0;0;0;0;1.000.000\n"
           + "2;;30-12-2025;30-12-2025;Compra;BONO REP. ARGENTINA (AL30);ARS;BYMA;"
             "1000;800;-800.000;0;0;0;0;-800.000\n").encode()
    ene = (COCOS_HDR
           + "3;;02-01-2026;02-01-2026;Venta Dolar Mep;BONO REP. ARGENTINA (AL30);USD;BYMA;"
             "-1000;0,55;550;0;0;0;0;550\n").encode()
    cuenta = _Cuenta()
    cuenta.importar([("dic.csv", dic), ("ene.csv", ene)], "cocos")
    assert cuenta.moneda_de("AL30", "BUY") == []
    assert cuenta.tenencia("AL30") == 0
    assert cuenta.efectivo("ARS") == 200000.0
    assert cuenta.efectivo("USD") == 550.0


def test_solo_inviu_lee_cada_archivo_aparte():
    """Contrato: leer de a un archivo pierde los pares que cruzan de un archivo
    al otro. Bull Market, Cocos e IOL emparejan las patas de un dólar MEP. Un
    lector nuevo que quiera leerse de a uno tiene que no emparejar nada, y
    sumarse acá con su motivo."""
    from importing.parsers.registry import list_parsers
    assert {p.format_id for p in list_parsers()
            if getattr(p, "lee_cada_archivo_aparte", False)} == {"inviu"}


def test_los_titulos_quedan_tambien_en_un_csv_sin_hoja_ni_saldo():
    """La regla del título vale para cualquier formato, no sólo para los que
    traen hoja o saldo (revisión independiente del 06/11)."""
    from importing.pipeline import juntar_archivos
    a = "fecha;monto\nSECCION A;\n01-01-2026;100\nSECCION B;\n02-01-2026;200\n"
    b = "fecha;monto\nSECCION A;\n01-01-2026;100\nSECCION B;\n02-01-2026;200\n03-01-2026;300\n"
    _b, _n, err, partes = juntar_archivos([(a.encode(), "a.csv"), (b.encode(), "b.csv")])
    assert err is None
    assert partes[1].splitlines() == ["fecha;monto", "SECCION A;", "SECCION B;", "03-01-2026;300"]

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


def test_leidos_de_a_uno_un_numero_alto_o_cero_no_choca():
    """Un error con número más alto que la última fila, o una fila con número 0
    (el Histórico compacto emite así su saldo), tampoco puede chocar con el
    archivo siguiente (revisión independiente del 06/11)."""
    from importing.pipeline import _parsear
    from importing.schema import ParseResult, RawRow, RowError

    class _Lector:
        lee_cada_archivo_aparte = True

        def parse(self, content, file_name=None):
            r = ParseResult()
            filas = content.splitlines()[1:]
            if filas[0] == "cero":
                r.raw_rows.append(RawRow(row_index=0, data={"f": "cero"}))
                filas = filas[1:]
            for i, f in enumerate(filas, start=1):
                r.raw_rows.append(RawRow(row_index=i, data={"f": f}))
            if "alto" in content:
                r.parse_errors.append(RowError(len(filas) + 1, None, "ALTO", "alto"))
            return r

    r = _parsear(_Lector(), "", "x", ["h\na1\nalto", "h\ncero\nb1"])
    numeros = [x.row_index for x in r.raw_rows] + [e.row_index for e in r.parse_errors]
    assert len(numeros) == len(set(numeros)), numeros
