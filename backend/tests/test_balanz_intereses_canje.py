"""Las tres filas de un canje de ON que Balanz nombra distinto.

Un export real dejaba 3 filas afuera con "Movimiento de Balanz no reconocido":

    Contraprestación período temprano - Canje MR44O / MR44O   Pesos   +1.333,73
    Intereses corridos / 21030                                Pesos      −36,29
    Intereses corridos / 21030                                Dólares    +10,18

Ninguna era un caso nuevo: el MISMO archivo ya importaba bien
"Intereses devengados canje Petro. Aconcagua PECBO", que es lo mismo con otras
dos palabras — los intereses que el bono acumuló hasta la fecha del canje, en dos
patas (el cobro en dólares y su retención en pesos). Y la "contraprestación por
período temprano" es el premio por entrar temprano al canje: cash que entra.

`21030` no es un número de comprobante: es el TICKER del certificado provisorio
del canje, que entra en uno y sale en el siguiente (ver `test_balanz_canje_on.py`).

Corre con: cd backend && python3 -m pytest tests/test_balanz_intereses_canje.py
"""
import unittest

from importing.parsers.balanz_movimientos import BalanzMovimientosParser

HDR = ("Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,"
       "Liquidacion,Moneda,Importe")

# Las patas del canje ya soportado y las que faltaban, tal como vienen.
YA_ANDABA = [
    "Intereses devengados canje Petro. Aconcagua PECBO / PECBO,PECBO,Corporativos,"
    "2025-08-25,0,-1,2025-08-25,Pesos,-5.14",
    "Intereses devengados canje Petro. Aconcagua PECBO / PECBO,PECBO,Corporativos,"
    "2025-08-25,0,-1,2025-08-25,Dólares,1.1",
]
FALTABAN = [
    "Contraprestación período temprano - Canje MR44O / MR44O,MR44O,Corporativos,"
    "2026-07-21,0,-1,2026-07-21,Pesos,1333.73",
    "Intereses corridos / 21030,21030,Corporativos,2024-11-08,0,-1,2024-11-08,Pesos,-36.29",
    "Intereses corridos / 21030,21030,Corporativos,2024-11-08,0,-1,2024-11-08,"
    "Dólares C.V. 7000,10.18",
]


def _parse(filas):
    return BalanzMovimientosParser().parse(HDR + "\n" + "\n".join(filas) + "\n")


class LasTresFilasEntran(unittest.TestCase):
    def test_ninguna_queda_afuera(self):
        res = _parse(FALTABAN)
        self.assertEqual(res.parse_errors, [],
                         [e.message for e in res.parse_errors])
        self.assertEqual(len(res.raw_rows), 3)

    def test_el_premio_por_entrar_temprano_es_un_ingreso(self):
        d = _parse([FALTABAN[0]]).raw_rows[0].data
        self.assertEqual(d["tipo"], "DIVIDENDO")
        self.assertEqual(float(d["monto"]), 1333.73)
        self.assertEqual(d["activo"], "MR44O")

    def test_los_intereses_corridos_van_como_los_devengados(self):
        # Mismo evento, distinto nombre → mismo tratamiento. Es la garantía de
        # que no se inventó un criterio nuevo para el caso nuevo.
        nuevo = [(r.data["tipo"], r.data["moneda"]) for r in _parse(FALTABAN[1:]).raw_rows]
        viejo = [(r.data["tipo"], r.data["moneda"]) for r in _parse(YA_ANDABA).raw_rows]
        self.assertEqual(sorted(nuevo), sorted(viejo))
        self.assertEqual(sorted(nuevo), [("DIVIDENDO", "USD"), ("IMPUESTO", "ARS")])

    def test_el_cash_reconcilia_con_el_archivo(self):
        # Σ de lo que emite Rendi = Σ Importe del archivo, por moneda.
        res = _parse(FALTABAN)
        caja = {}
        for r in res.raw_rows:
            d = r.data
            m = float(d["monto"])
            caja[d["moneda"]] = caja.get(d["moneda"], 0.0) + (
                m if d["tipo"] in ("DIVIDENDO", "INTERES") else -m)
        self.assertAlmostEqual(caja["ARS"], 1333.73 - 36.29, places=2)
        self.assertAlmostEqual(caja["USD"], 10.18, places=2)


if __name__ == "__main__":
    unittest.main()
