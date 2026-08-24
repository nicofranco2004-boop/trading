"""La fecha que el broker pone en el NOMBRE del export.

POR QUÉ EXISTE. `parse_cocos_tenencia` no puede leer la fecha del contenido: el
CSV es un header exacto de 5 columnas (instrumento;cantidad;precio;moneda;total),
sin preámbulo ni columna de fecha. Por eso las 47 fotos de Cocos en producción
caen todas al fallback de "hoy".

Y Cocos es justo el broker que más importa — tres cosas distintas apuntan al
mismo lugar: 42% de cobertura de foto (la peor), el 53% de todos los usuarios que
quedan sin verificar, y el único parser de foto que no lee la fecha.

La fecha SÍ está: 82 de 82 exports de Cocos se llaman
`portfolio_report_YYYYMMDD.csv`. Balanz igual (`ResumenDeCuenta_20260706.pdf`).

⚠️ Es evidencia MÁS DÉBIL que el contenido —el nombre lo cambia cualquiera— así
que viaja con su propio `fecha_origen` ('nombre_archivo') y no disfrazada de
'archivo'.
"""
import unittest

from importing.tenencia import fecha_de_nombre_archivo as fecha


class FechaDeNombreArchivoTest(unittest.TestCase):
    def test_el_formato_real_de_cocos(self):
        # 82 de 82 exports en producción tienen esta forma.
        self.assertEqual(fecha("portfolio_report_20260801.csv"), "2026-08-01")
        self.assertEqual(fecha("portfolio_report_20260628.csv"), "2026-06-28")

    def test_el_sufijo_de_descarga_duplicada_no_molesta(self):
        # El navegador agrega " (1)" cuando ya existe el archivo. En prod hay
        # varios así — y es también la prueba de que el nombre lo tocan terceros,
        # que es por qué esta fecha vale menos que la del contenido.
        self.assertEqual(fecha("portfolio_report_20260802 (1).csv"), "2026-08-02")

    def test_el_formato_real_de_balanz(self):
        self.assertEqual(fecha("ResumenDeCuenta_20260706.pdf"), "2026-07-06")
        self.assertEqual(fecha("ResumenDeCuenta_20260722 (8).pdf"), "2026-07-22")

    def test_acepta_separadores(self):
        self.assertEqual(fecha("tenencia_2026-06-30.csv"), "2026-06-30")
        self.assertEqual(fecha("tenencia_2026_06_30.csv"), "2026-06-30")

    def test_descarta_lo_que_no_puede_ser_una_fecha(self):
        # Devolver un ISO invalido seria peor que devolver None: ordena mal en
        # cualquier `date <= ?` y nadie se entera.
        self.assertIsNone(fecha("reporte_20261301.csv"))   # mes 13
        self.assertIsNone(fecha("reporte_20260732.csv"))   # dia 32
        self.assertIsNone(fecha("reporte_20260600.csv"))   # dia 0

    def test_sin_fecha_devuelve_None(self):
        # El nombre por defecto que pone el endpoint cuando no hay filename.
        self.assertIsNone(fecha("EstadoDeCuenta.csv"))
        self.assertIsNone(fecha("Consolidada Balanz.pdf"))
        self.assertIsNone(fecha(""))
        self.assertIsNone(fecha(None))

    def test_no_confunde_un_numero_largo_con_una_fecha(self):
        # Un id de cuenta de 8 digitos que no empieza en 20xx no matchea.
        self.assertIsNone(fecha("reporte_98765432.csv"))


if __name__ == "__main__":
    unittest.main()
