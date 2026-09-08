"""El guard de cobertura pondera con la moneda del LOTE, no la de la cuenta.

CONTEXTO. Antes de escribir un snapshot, el cron chequea qué fracción del costo
de la cartera tiene precio: `Σ(costo de lo que tiene precio) / Σ(costo total)`.
Si baja de 95 % no escribe, para no persistir una cartera subvaluada.

EL BUG (D-4 del plan de remediación). El fix `86402f00` corrigió la VALUACIÓN
para que la moneda del costo la decida el lote (`_cost_in_pesos`), pero no tocó
la closure que PONDERA esa cobertura, que seguía mirando sólo `brokers.currency`.
Un lote comprado en pesos alojado en una cuenta dólar entraba a la suma con su
monto en pesos contado como dólares: pesaba ~MEP× de más.

Eso no hacía fallar el guard: lo hacía CIEGO. Una posición inflada ~1.400×
dentro de la suma empuja el cociente hacia 1 y tapa que a otras posiciones —de
peso real— les falte precio. El guard reportaba cobertura alta mientras el dato
que iba a escribir estaba mal.

Y la closure estaba duplicada byte por byte en `run_daily_snapshot` y en
`compute_live_portfolio_value`, así que había que arreglar la misma cuenta dos
veces. Ahora es una sola función.

Corre con: cd backend && python3 -m pytest tests/test_coverage_weight_currency.py
"""
import unittest

from snapshots_job import cost_usd_for_coverage

MEP = 1450.0
BROKER_CCY = {"Cocos": "ARS", "Cocos · USD": "USD", "Schwab": "USD"}


def lote(broker, currency, invested, asset="MELI", commissions=0):
    return {"broker": broker, "currency": currency, "invested": invested,
            "asset": asset, "commissions": commissions, "is_cash": 0}


class CoverageWeightCurrencyTest(unittest.TestCase):

    def test_lote_en_pesos_en_cuenta_dolar_pondera_en_usd(self):
        """REGRESIÓN D-4: es el caso que el fix de valuación corrigió y éste no."""
        p = lote("Cocos · USD", "ARS", 1_500_000)
        self.assertAlmostEqual(cost_usd_for_coverage(p, BROKER_CCY, MEP),
                               1_500_000 / MEP, places=2)

    def test_no_pondera_los_pesos_como_dolares(self):
        """Explícito: el número viejo era el monto en pesos tal cual."""
        p = lote("Cocos · USD", "ARS", 1_500_000)
        self.assertNotAlmostEqual(cost_usd_for_coverage(p, BROKER_CCY, MEP),
                                  1_500_000, places=2)

    def test_lote_en_pesos_en_broker_usd_genuino(self):
        """El caso A-2: ni el nombre ni el padre delatan que el costo está en
        pesos. Sólo lo dice `positions.currency`."""
        p = lote("Schwab", "ARS", 500_000, asset="GGAL")
        self.assertAlmostEqual(cost_usd_for_coverage(p, BROKER_CCY, MEP),
                               500_000 / MEP, places=2)

    def test_broker_ars_sigue_convirtiendo(self):
        """Lo que ya andaba tiene que seguir andando."""
        p = lote("Cocos", "ARS", 1_450_000)
        self.assertAlmostEqual(cost_usd_for_coverage(p, BROKER_CCY, MEP), 1000.0, places=2)

    def test_lote_en_dolares_no_se_convierte(self):
        p = lote("Cocos · USD", "USD", 1000)
        self.assertAlmostEqual(cost_usd_for_coverage(p, BROKER_CCY, MEP), 1000.0, places=2)

    def test_suma_comisiones(self):
        p = lote("Schwab", "USD", 1000, commissions=25)
        self.assertAlmostEqual(cost_usd_for_coverage(p, BROKER_CCY, MEP), 1025.0, places=2)

    def test_la_cobertura_deja_de_estar_sesgada(self):
        """El efecto que importa: con la ponderación vieja, un lote en pesos mal
        pesado hacía que un faltante REAL de precio pasara el umbral del 95 %."""
        con_precio = lote("Cocos · USD", "ARS", 1_500_000)   # ~US$1.034
        sin_precio = lote("Schwab", "USD", 5_000, asset="XYZ")  # US$5.000, sin cotización
        total = sum(cost_usd_for_coverage(p, BROKER_CCY, MEP)
                    for p in (con_precio, sin_precio))
        cubierto = cost_usd_for_coverage(con_precio, BROKER_CCY, MEP)
        cobertura = cubierto / total
        # Con la cuenta correcta, el 83 % del peso NO tiene precio → el guard frena.
        self.assertLess(cobertura, 0.95)



class CoberturaVsValuacionTest(unittest.TestCase):
    """La ponderación tiene que coincidir con el `invested` que produce el
    valuador REAL, no con un criterio reescrito a mano.

    Lo encontré auditando mi propio fix: la primera versión decía
    `_cost_in_pesos(p) or broker es ARS`, y eso divide por el MEP a la CRIPTO con
    lote en dólares dentro de un broker ARS — que el valuador NO divide (rama de
    cripto, snapshots_job.py:282). Comparar contra la función de verdad, en vez de
    contra el criterio que yo creía correcto, es lo que lo destapó.
    """

    CASOS = [
        # (broker, moneda del broker, currency del lote, asset)
        ("Cocos",       "ARS",  "ARS",  "MELI"),
        ("Cocos",       "ARS",  "USD",  "MELI"),   # bono/CEDEAR comprado por MEP
        ("Cocos",       "ARS",  None,   "MELI"),
        ("Cocos",       "ARS",  "USD",  "BTC"),    # ← el caso que fallaba
        ("Cocos",       "ARS",  "ARS",  "BTC"),
        ("Cocos · USD", "USD",  "ARS",  "MELI"),   # A-1
        ("Cocos · USD", "USD",  "USD",  "MELI"),
        ("Cocos · USD", "USD",  "ARS",  "BTC"),    # cripto: nunca por el MEP
        ("Schwab",      "USD",  "ARS",  "GGAL"),   # A-2
        ("Schwab",      "USD",  "USD",  "AAPL"),
    ]

    def test_pondera_igual_que_el_valuador(self):
        import snapshots_job as sj
        mep = 1450.0
        for broker, bccy, lccy, asset in self.CASOS:
            with self.subTest(broker=broker, lote=lccy, asset=asset):
                p = {"broker": broker, "currency": lccy, "asset": asset,
                     "invested": 100_000, "commissions": 0, "is_cash": 0,
                     "asset_type": None, "price_override": None, "quantity": 1}
                # `invested` del valuador canónico, sin precios: sólo el costo.
                real = sj.compute_broker_value_usd(
                    [p], {}, bccy, mep, broker_name=broker, cedear_rate=mep)["invested"]
                pond = sj.cost_usd_for_coverage(p, {broker: bccy}, mep)
                self.assertAlmostEqual(pond, real, places=6)

if __name__ == "__main__":
    unittest.main()
