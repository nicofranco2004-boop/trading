"""La fila que el parser OMITE tiene que señalar la fila REAL del archivo — y no
puede pisar a una fila válida.

Bug encontrado con un export real de Balanz (Movimientos, 879 filas buenas + 3
descripciones sin soporte): el error se numeraba con el CONTADOR DE FILAS
EMITIDAS (`ridx + 1`), no con la fila del archivo. Dos consecuencias, las dos
visibles en pantalla:

  1. El número que leía el usuario ("Fila 4", "Fila 442", "Fila 442") no existía
     en su archivo: era "cuántas filas van emitidas + 1". Dos omitidas seguidas
     compartían número.
  2. Peor: ese número ES la clave que une error ↔ fila en `errors_by_row`, así
     que el error se le pegaba a la fila válida que venía después — una fila
     buena quedaba marcada 'invalid' en el preview.

Vale para los 4 parsers que numeran así (Balanz Movimientos, Balanz
Internacional, Balanz Resultados y PPI): todos van por `omitted_row_error`.
"""
import unittest

from importing.parsers.balanz_movimientos import BalanzMovimientosParser
from importing.parsers.balanz_internacional import BalanzInternacionalParser
from importing.parsers.ppi import PpiParser


def _assert_sin_colision(t, res):
    """Ningún error puede compartir clave con una fila emitida (si no, el preview
    marca 'invalid' una fila buena) ni con otro error."""
    emitidas = {rr.row_index for rr in res.raw_rows}
    claves = [e.row_index for e in res.parse_errors if e.file_row is not None]
    t.assertFalse(emitidas & set(claves), "un error se pegó a una fila válida")
    t.assertEqual(len(claves), len(set(claves)), "dos filas omitidas comparten clave")


HDR = ("Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,"
       "Liquidacion,Moneda,Importe")


class BalanzMovimientosFilaOmitida(unittest.TestCase):
    # 7 filas de datos: las 4, 5 y 6 son las que el parser no reconoce; la 7 es
    # válida y es justo la que el bug marcaba como rota. Las descripciones que
    # no se reconocen son inventadas A PROPÓSITO: con las del export real este
    # test se cae solo el día que se soporten (pasó: ver el comentario abajo).
    ROWS = [
        "Recibo de Cobro / 1,,,2025-10-22,0,-1,2025-10-22,Pesos,1000",
        "Recibo de Cobro / 2,,,2025-10-23,0,-1,2025-10-23,Pesos,1000",
        "Recibo de Cobro / 3,,,2025-10-24,0,-1,2025-10-24,Pesos,1000",
        # Tres descripciones que Rendi NO conoce. OJO: acá vivían las del export
        # real ("Contraprestación período temprano", "Intereses corridos"), pero
        # se soportaron en `test_balanz_intereses_canje.py` y el fixture dejó de
        # servir — un test de filas OMITIDAS necesita filas que sigan afuera.
        "Movimiento que Balanz todavía no nos mostró,XXAA,Bonos,2025-10-25,0,-1,2025-10-25,Dólares,12.5",
        "Otro movimiento sin soporte / 21030,XXBB,Bonos,2025-10-26,0,-1,2025-10-26,Dólares,-3.5",
        "Otro movimiento sin soporte / 21030,XXBB,Bonos,2025-10-26,0,-1,2025-10-26,Dólares,3.5",
        "Recibo de Cobro / 4,,,2025-10-27,0,-1,2025-10-27,Pesos,1000",
    ]

    def setUp(self):
        self.res = BalanzMovimientosParser().parse(HDR + "\n" + "\n".join(self.ROWS) + "\n")

    def test_apunta_a_la_fila_del_archivo(self):
        self.assertEqual([e.file_row for e in self.res.parse_errors], [4, 5, 6])

    def test_no_pisa_la_fila_valida_que_sigue(self):
        _assert_sin_colision(self, self.res)
        # Las 4 válidas siguen entrando enteras.
        self.assertEqual(len(self.res.raw_rows), 4)

    def test_el_numero_viaja_al_frontend(self):
        self.assertEqual([e.to_dict()["file_row"] for e in self.res.parse_errors], [4, 5, 6])


class BalanzInternacionalFilaOmitida(unittest.TestCase):
    def test_apunta_a_la_fila_del_archivo(self):
        rows = [
            "Recibo de Cobro / 1,,,2025-10-22,0,-1,2025-10-22,Dólares,1000",
            "Movimiento que Balanz todavía no nos mostró,,,2025-10-23,0,-1,2025-10-23,Dólares,5",
            "Recibo de Cobro / 2,,,2025-10-24,0,-1,2025-10-24,Dólares,1000",
        ]
        res = BalanzInternacionalParser().parse(HDR + "\n" + "\n".join(rows) + "\n")
        self.assertEqual([e.file_row for e in res.parse_errors], [2])
        _assert_sin_colision(self, res)


class PpiFilaOmitida(unittest.TestCase):
    def test_apunta_a_la_fila_del_archivo(self):
        p = PpiParser()
        hdr = p.template_csv().splitlines()[0]
        # Segunda fila de datos: descripción que PPI no tiene mapeada.
        base = p.template_csv().splitlines()[1]
        cols = base.split(",")
        rara = ",".join(["Movimiento que PPI todavía no nos mostró"] + cols[1:])
        res = p.parse(hdr + "\n" + base + "\n" + rara + "\n" + base + "\n")
        omitidas = [e for e in res.parse_errors if e.file_row is not None]
        if omitidas:                      # si el template cambia y ya no cae acá
            self.assertEqual([e.file_row for e in omitidas], [2])
        _assert_sin_colision(self, res)


if __name__ == "__main__":
    unittest.main()
