"""Qué brokers tienen foto de tenencia — la verdad vive en el backend.

POR QUÉ EXISTE. La reconciliación contra la foto del broker es el mejor chequeo
del sistema: no depende de conocer el bug, porque la referencia es el broker. Un
error de escala, de moneda, de parser o uno nuevo aparece igual, porque el número
no cuadra con la foto.

Pero sólo corre para el 57,8% de la gente elegible (160 de 277 usuarios midiendo
contra la copia de prod del 2026-08-16). Al 42,2% restante no se le verifica
nada. Cocos es el que más pierde: 68 usuarios elegibles sin foto — el 53% de todo
lo que se pierde — con 42% de cobertura.

🔴 Y LA VERDAD ESTABA EN EL FRONTEND. El único mapeo movimientos→foto era
`TENENCIA_BROKER_BY_FORMAT`, un dict a mano en `ImportWizard.jsx`, que YA se
desincronizó: tiene entrada para `balanz_internacional`, cuya foto no existe. Un
aviso manejado por ese dict le pediría al usuario un archivo que ningún parser
sabe leer — que es peor que no avisar, porque lo manda a buscar algo que no va a
poder usar.
"""
import unittest

from importing.parsers.registry import list_parsers, get_parser
from importing.pipeline import parser_options_grouped, TENENCIA_LABELS

# Los siete brokers con parser de foto, y el formato que produce cada uno.
# Si alguien agrega un parser de foto nuevo y no toca esta lista, el test avisa.
CON_FOTO = {
    "cocos": "cocos_tenencia",
    "balanz": "balanz_tenencia",
    "iol": "iol_tenencia",
    "bullmarket": "bullmarket_tenencia",
    "ppi": "ppi_tenencia",
    "ieb": "ieb_tenencia",
    "inviu": "inviu_tenencia",
}
SIN_FOTO = {"generic", "binance", "schwab", "balanz_internacional"}


class TenenciaCapabilityTest(unittest.TestCase):
    def test_cada_plataforma_declara_si_tiene_foto(self):
        for g in parser_options_grouped():
            p = g["platform"]
            if p in CON_FOTO:
                self.assertEqual(g["tenencia_format"], CON_FOTO[p], p)
            elif p in SIN_FOTO:
                self.assertIsNone(g["tenencia_format"], p)
            else:
                self.fail(f"plataforma '{p}' sin clasificar: decidí si tiene "
                          f"foto de tenencia y agregala a CON_FOTO o SIN_FOTO")

    def test_balanz_internacional_NO_pide_una_foto_que_no_existe(self):
        # El caso que tenía mal el dict del frontend. Mandar a alguien a buscar
        # un archivo que ningún parser sabe leer es peor que no avisarle.
        g = next(x for x in parser_options_grouped()
                 if x["platform"] == "balanz_internacional")
        self.assertIsNone(g["tenencia_format"])
        self.assertIsNone(g["tenencia_label"])

    def test_los_tres_exports_de_balanz_comparten_la_misma_foto(self):
        # Balanz tiene tres formatos de movimientos y UNA sola foto. Por eso la
        # capacidad va a nivel plataforma y no de export — mismo criterio que
        # el `allowPdf` que el wizard ya usa.
        for fid in ("balanz", "balanz_movimientos", "balanz_resultados"):
            self.assertEqual(get_parser(fid).tenencia_format, "balanz_tenencia", fid)

    def test_toda_foto_declarada_tiene_instrucciones(self):
        # Un aviso que dice "traé la foto" sin decir de dónde bajarla no sirve.
        for g in parser_options_grouped():
            if g["tenencia_format"]:
                self.assertTrue(g["tenencia_label"],
                                f"{g['platform']} declara foto pero no tiene "
                                f"instrucciones en TENENCIA_LABELS")

    def test_no_sobran_instrucciones(self):
        # Al revés: una etiqueta para un formato que nadie declara es letra
        # muerta que alguien va a leer como si estuviera vivo.
        declarados = {p.tenencia_format for p in list_parsers() if p.tenencia_format}
        self.assertEqual(set(TENENCIA_LABELS) - declarados, set())

    def test_el_default_del_contrato_es_sin_foto(self):
        # Falla CERRADO: un parser nuevo no pide una foto que nadie escribió.
        from importing.parsers.base import Parser
        self.assertIsNone(Parser.tenencia_format)


if __name__ == "__main__":
    unittest.main()
