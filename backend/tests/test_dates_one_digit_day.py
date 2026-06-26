"""Fix sistémico: las fechas con día/mes de UN dígito (1-9) ya no se rechazan.

Bug: todos los parseos de fecha exigían \\d{2} (día/mes de exactamente 2
dígitos). Con "1/6/2026" fallaban → "Fecha inválida" (vacía en Cocos/Schwab,
que devuelven None→""). Ahora aceptan \\d{1,2} y normalizan a 2 dígitos.
IOL ya era resiliente (es el patrón de referencia).
"""
import unittest

from importing.normalizer import parse_date
from importing.parsers.cocos import _parse_date_ddmmyyyy
from importing.parsers.schwab import _parse_date as schwab_parse_date


class OneDigitDayDateTest(unittest.TestCase):
    def test_normalizer_parse_date_one_digit(self):
        # DD/MM/YYYY con día/mes de 1 dígito → ISO normalizado a 2 dígitos
        self.assertEqual(parse_date("1/6/2026"), "2026-06-01")
        self.assertEqual(parse_date("01/6/2026"), "2026-06-01")
        self.assertEqual(parse_date("1/06/2026"), "2026-06-01")
        self.assertEqual(parse_date("9-6-2026"), "2026-06-09")
        # ISO con 1 dígito — cubre la salida de _fix_date de Binance ("2025-6-9")
        self.assertEqual(parse_date("2025-6-9"), "2025-06-09")
        self.assertEqual(parse_date("2026/1/6"), "2026-01-06")  # YYYY/M/D = 6 de enero
        # 2 dígitos sigue funcionando (no hay regresión)
        self.assertEqual(parse_date("01/06/2026"), "2026-06-01")
        self.assertEqual(parse_date("2026-06-01"), "2026-06-01")
        # inválidas siguen rechazadas
        self.assertIsNone(parse_date("1/13/2026"))   # mes 13
        self.assertIsNone(parse_date("32/6/2026"))   # día 32
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date("garbage"))

    def test_cocos_one_digit_day(self):
        # Cocos: DD-MM-YYYY (su _parse_date_ddmmyyyy) — el del bug reportado
        self.assertEqual(_parse_date_ddmmyyyy("1-6-2026"), "2026-06-01")
        self.assertEqual(_parse_date_ddmmyyyy("9/6/2026"), "2026-06-09")
        self.assertEqual(_parse_date_ddmmyyyy("01-06-2026"), "2026-06-01")  # 2 díg OK
        self.assertIsNone(_parse_date_ddmmyyyy(""))

    def test_schwab_one_digit_day(self):
        # Schwab: MM/DD/YYYY
        self.assertEqual(schwab_parse_date("6/1/2026"), "2026-06-01")    # jun 1
        self.assertEqual(schwab_parse_date("06/01/2026"), "2026-06-01")  # 2 díg OK
        # respeta el "as of" (fecha efectiva), también con 1 dígito
        self.assertEqual(schwab_parse_date("1/2/2026 as of 1/5/2026"), "2026-01-05")


if __name__ == "__main__":
    unittest.main()
