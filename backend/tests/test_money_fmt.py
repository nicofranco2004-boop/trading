"""El formateador de plata del backend. Es el único lugar donde se decide cómo se
escribe un número en un mail, un informe o una respuesta de la IA, así que un
cambio acá se ve en todas las superficies a la vez."""
import unittest

from money_fmt import fmt_money, fmt_num


class FmtNumTest(unittest.TestCase):
    def test_separadores_argentinos(self):
        # punto = miles, coma = decimales. El bug original mostraba los pesos
        # bien y los dólares a la inglesa en el MISMO mail.
        self.assertEqual(fmt_num(2145.3, 2), "2.145,30")
        self.assertEqual(fmt_num(1234, 0), "1.234")
        self.assertEqual(fmt_num(1234567.891, 2), "1.234.567,89")
        self.assertEqual(fmt_num(1e9, 0), "1.000.000.000")

    def test_decimales_chicos_y_cero(self):
        self.assertEqual(fmt_num(0, 2), "0,00")
        self.assertEqual(fmt_num(0.5, 2), "0,50")
        self.assertEqual(fmt_num(0.001, 3), "0,001")

    def test_negativos_y_signo_explicito(self):
        self.assertEqual(fmt_num(-8400, 0), "-8.400")
        self.assertEqual(fmt_num(10, 1, signed=True), "+10,0")
        self.assertEqual(fmt_num(-10, 1, signed=True), "-10,0")

    def test_sin_dato_va_guion(self):
        self.assertEqual(fmt_num(None, 2), "—")
        self.assertEqual(fmt_num("no es un número", 2), "—")

    def test_inf_y_nan_no_se_publican(self):
        # Sin este corte, una división por cero río arriba terminaba publicando
        # "US$ inf" en un mail a un usuario.
        self.assertEqual(fmt_num(float("inf"), 2), "—")
        self.assertEqual(fmt_num(float("-inf"), 2), "—")
        self.assertEqual(fmt_num(float("nan"), 2), "—")


class FmtMoneyTest(unittest.TestCase):
    def test_simbolo_por_moneda_pero_separadores_siempre_iguales(self):
        self.assertEqual(fmt_money(2145.3, "USD"), "US$ 2.145,30")
        self.assertEqual(fmt_money(7350, "ARS"), "$7.350")

    def test_sin_dato(self):
        self.assertEqual(fmt_money(None, "USD"), "—")


if __name__ == "__main__":
    unittest.main()
