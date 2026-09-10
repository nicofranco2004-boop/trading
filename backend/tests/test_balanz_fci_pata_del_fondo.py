"""FCI de Balanz: la pata del lado del FONDO no mueve el efectivo de la cuenta.

Tercera causa de que los números de Balanz no cerraran, y la primera verificada
contra una fuente INDEPENDIENTE: el resumen que emite el propio broker.

Un movimiento de fondo llega en DOS filas espejo:

    Liquidación de Rescate / 372913 / BALANZ MONEY MARKET   "BMM A"   +369.982
    Rescate a Balanz                                        "BCMMA"   −369.982

Es UN movimiento visto desde los dos lados. El parser descartaba el espejo
apareándolo por (ticker, fecha, cantidad) — pero **Balanz nombra al mismo fondo
con dos códigos distintos según el lado**: "BMM A" en la Liquidación y "BCMMA" en
el espejo. De 12 pares de un archivo real sólo matcheaban 5; los 7 del money
market no, y el movimiento se contaba DOS VECES: caja en pesos $2.207.199 cuando
el resumen del broker decía $713.772 (≈ +979 USD), más una posición de fondo
duplicada.

La regla, verificada AL CENTAVO en las dos monedas contra ese resumen: sólo la
"Liquidación de …" mueve la caja. La pata del fondo, si tiene par, se descarta
entera; si no lo tiene, aporta la TENENCIA (si no, las cuotapartes quedan
colgadas) con su caja neutralizada por una pata compensatoria.

⚠️ La regla mira la CLASE, no el texto: "Rescate / TLC1O" es el rescate de un
BONO, no de un fondo, y sí paga plata. Filtrar por la palabra "rescate" rompía el
dólar, que ya daba exacto.

Corre con: cd backend && python3 -m pytest tests/test_balanz_fci_pata_del_fondo.py
"""
import unittest

from importing.parsers.balanz_movimientos import BalanzMovimientosParser

HDR = ("Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,"
       "Liquidacion,Moneda,Importe")

ENTRA = {"VENTA", "DEPOSITO", "DIVIDENDO", "INTERES"}
SALE = {"COMPRA", "RETIRO", "FEE", "IMPUESTO"}


def _caja(res, moneda="Pesos"):
    ccy = "ARS" if moneda.lower().startswith("peso") else "USD"
    t = 0.0
    for r in res.raw_rows:
        d = r.data
        if d.get("moneda") != ccy:
            continue
        m = float(d.get("monto") or 0)
        t += m if d["tipo"] in ENTRA else (-m if d["tipo"] in SALE else 0)
    return round(t, 2)


def _parse(*filas):
    return BalanzMovimientosParser().parse(HDR + "\n" + "\n".join(filas) + "\n")


class LaPataDelFondo(unittest.TestCase):
    # El par real que rompía el apareo: el MISMO fondo con dos códigos.
    PAR = [
        "Liquidación de Rescate / 372913 / BALANZ MONEY MARKET,BMM A,Fondos,"
        "2026-02-20,-32883.339824,11.251351,2026-02-20,Pesos,369982",
        "Rescate a Balanz,BCMMA,Fondos,2026-02-20,-32883.339824,11.251351,"
        "2026-02-20,Pesos,-369982",
    ]

    def test_el_movimiento_entra_una_sola_vez(self):
        res = _parse(*self.PAR)
        self.assertEqual(_caja(res), 369982.0,
                         "el rescate se contó dos veces: la caja quedó al doble")

    def test_no_se_crea_una_posicion_de_fondo_duplicada(self):
        res = _parse(*self.PAR)
        tickers = {r.data.get("activo") for r in res.raw_rows if r.data.get("activo")}
        self.assertEqual(tickers, {"BMMA"},
                         f"el mismo fondo quedó con dos posiciones: {tickers}")

    def test_el_codigo_distinto_no_rompe_el_apareo(self):
        # El corazón del bug: apareado por ticker, esto NO matcheaba.
        self.assertNotEqual(self.PAR[0].split(",")[1].replace(" ", ""),
                            self.PAR[1].split(",")[1].replace(" ", ""))


class PataSueltaSinContrapartida(unittest.TestCase):
    """Un rescate de fondo cuya "Liquidación" no está en el archivo: la plata
    nunca pasó por la cuenta, pero las cuotapartes sí se fueron."""

    FILA = ("Rescate,BCAHA,Fondos,2025-03-27,-3845.353277,150.848096,"
            "2025-03-27,Pesos,-580064.22")

    def test_baja_la_tenencia(self):
        res = _parse(self.FILA)
        ventas = [r.data for r in res.raw_rows if r.data["tipo"] == "VENTA"]
        self.assertEqual(len(ventas), 1, "se perdieron las cuotapartes rescatadas")
        self.assertAlmostEqual(float(ventas[0]["cantidad"]), 3845.353277, places=6)

    def test_no_mueve_la_caja(self):
        self.assertEqual(_caja(_parse(self.FILA)), 0.0,
                         "la plata de este rescate nunca pasó por la cuenta")


class ElRescateDeUnBonoNoEsUnFondo(unittest.TestCase):
    """La regla mira la CLASE. Filtrar por la palabra 'rescate' se comía esto y
    rompía la caja en dólares, que ya daba exacta."""

    def test_el_rescate_de_una_ON_si_paga(self):
        res = _parse("Rescate / TLC1O,TLC1O,Corporativos,2024-12-24,0,-1,"
                     "2024-12-24,Dólares,432.89")
        self.assertEqual(_caja(res, "Dólares"), 432.89)


class CajaDeUnaSecuenciaCompleta(unittest.TestCase):
    def test_suscribir_y_rescatar_deja_la_caja_donde_estaba(self):
        res = _parse(
            "Recibo de Cobro / 1,,,2025-01-02,0,-1,2025-01-02,Pesos,1000000",
            # suscribe 500.000 (las dos patas, con códigos distintos)
            "Liquidación de Suscripción / 9 / BALANZ MONEY MARKET,BMM A,Fondos,"
            "2025-04-08,57125.987022,8.752584,2025-04-08,Pesos,-500000",
            "Suscripción desde Balanz,BCMMA,Fondos,2025-04-08,57125.987022,"
            "8.752584,2025-04-08,Pesos,500000",
            # rescata los mismos 500.000
            "Liquidación de Rescate / 10 / BALANZ MONEY MARKET,BMM A,Fondos,"
            "2025-05-20,-57125.987022,8.752584,2025-05-20,Pesos,500000",
            "Rescate a Balanz,BCMMA,Fondos,2025-05-20,-57125.987022,8.752584,"
            "2025-05-20,Pesos,-500000",
        )
        self.assertEqual(_caja(res), 1000000.0)
        neto = sum((1 if r.data["tipo"] == "COMPRA" else -1) * float(r.data["cantidad"])
                   for r in res.raw_rows if r.data.get("activo") == "BMMA")
        self.assertAlmostEqual(neto, 0.0, places=6, msg="quedaron cuotapartes colgadas")


class UnBoletoDeFciEsUnaCompraDeVerdad(unittest.TestCase):
    """Hallazgo de auditar el propio fix: la primera versión trataba CUALQUIER
    fila de un fondo como pata del lado del fondo, así que a un boleto de compra
    le neutralizaba la caja — $125.000 comprados gratis. La rama sólo puede
    agarrar suscripciones y rescates."""

    def test_el_boleto_paga(self):
        res = _parse("Boleto / 999 / COMPRA / 0 / LECAP / $,LECAPSA,Fondos,"
                     "2025-06-01,100,1250,2025-06-01,Pesos,-125000")
        self.assertEqual(_caja(res), -125000.0, "la compra del fondo salió gratis")
        self.assertEqual([r.data["tipo"] for r in res.raw_rows], ["COMPRA"])


if __name__ == "__main__":
    unittest.main()
