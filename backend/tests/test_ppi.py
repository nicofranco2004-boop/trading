"""PpiParser — export de Movimientos de PPI (Portafolio Personal Inversiones).

PPI exporta multi-hoja (una por sub-cuenta de moneda) + hoja Instrumentos; el
conversor de Excel las une y agrega `_hoja`. Lo importante:
  • La dirección de trades sale del TOKEN COMPRA/VENTA (robusto al signo de Importe
    roto — un export anonimizado traía las VENTAS con Importe negativo).
  • `monto = abs(Importe)`; el tipo define la dirección del cash.
  • Moneda por columna/hoja: 'Pesos'→ARS, 'Dolar …'→USD.
  • FCI Suscripción→COMPRA, Rescate→VENTA (qty+precio reconstruyen la tenencia).
  • Caución → neto por moneda = INTERÉS. Bloqueo/Desbloqueo → skip (netean).
  • Instrumentos 'Retiro de Títulos' → transfer_out (cierra a costo).
"""
import unittest

from importing.parsers.ppi import PpiParser
from importing.parsers.registry import get_parser, autodetect
from importing.normalizer import normalize_rows
from importing.validator import validate

# Header unión tal como lo arma excel.xlsx_to_csv (cols de hojas $ + Instrumentos + _hoja).
HDR = "Fecha,Descripción,Cantidad,Precio,Importe,Saldo,Moneda,Especie,_hoja"
ROWS = [
    # ── hojas de moneda (Especie vacío) ──────────────────────────────────────
    "18/06/2026,Ingreso de Fondos,0,0,1000,1581.98,Dolar MEP,,Dolar MEP",                # +1000 USD depósito
    "29/05/2026,COMPRA NU,367,8730.42,-3204064.14,2446147.83,Pesos,,Pesos",              # compra ARS
    "08/04/2026,VENTA AL30,69152,0.93,-64311.36,51279.49,Dolar MEP,,Dolar MEP",          # VENTA con Importe NEGATIVO (signo roto)
    "03/06/2026,Retiro de Fondos,0,0,-204489.18,-987.05,Pesos,,Pesos",                   # retiro ARS
    "12/06/2026,Dividendo en efectivo / MSFT,0,0,5.48,10.67,DolarCV7000 Ext.,,DolarCV7000 Ext.",  # +5.48 USD dividendo
    "12/06/2026,Dividendo en efectivo / MSFT,0,0,-2.0,5.0,Pesos,,Pesos",                 # -2 ARS retención → FEE
    "24/04/2026,Liquidación de Suscripción / 860207 / Allaria Dolar Ahorro - Clase A,5607,1.52,-8522.64,0,Dolar MEP,,Dolar MEP",  # COMPRA fondo USD
    "22/05/2026,Liquidación de Rescate / 603074 / Balanz Capital Ahorro - Clase A,41610,241.53,10050063.3,4835226.32,Pesos,,Pesos",  # VENTA fondo ARS
    "20/05/2026,Bloqueo Monetario por Suscripción de FCI SCH.PLUS.A,0,0,-5000,0,Pesos,,Pesos",       # SKIP
    "21/05/2026,Desbloqueo Monetario por Liquidación de Suscripción / 1 / SCH.PLUS.A,0,0,5000,0,Pesos,,Pesos",  # SKIP
    "27/05/2026,Caución colocadora,0,0,-100000,12.34,Pesos,,Pesos",                      # caución (neto)
    "27/05/2026,Liquidación caución colocadora 5 días,0,0,105000,105012.34,Pesos,,Pesos",  # caución (neto) → +5000 INTERÉS
    "28/04/2026,COMPRA SPOT,170,18.11,-3078.7,9924.88,Dolar MEP,,Dolar MEP",             # FLAG (conducto dólar-MEP)
    "27/01/2026,Movimiento Manual / Canje de monedas USD7000/USD,0,0,158.34,0,Dolar MEP,,Dolar MEP",   # +158.34 USD → INTERÉS
    "25/06/2026,Movimiento Manual / Compensación de monedas,0,0,-9.4,0,DolarCV7000 Ext.,,DolarCV7000 Ext.",  # -9.4 USD → FEE
    # ── hoja Instrumentos (cols de moneda vacías, Especie con ticker) ─────────
    "02/06/2026,Retiro de Títulos,-787.9,0,,,,CEPU,Instrumentos",                        # transfer_out CEPU
    "29/05/2026,COMPRA NU,249.41,0,,,,CEPU,Instrumentos",                                # SKIP (redundante con hoja $)
]


def _csv():
    return HDR + "\n" + "\n".join(ROWS) + "\n"


OUT = {"COMPRA", "RETIRO", "FEE"}
IN = {"VENTA", "DEPOSITO", "DIVIDENDO", "INTERES"}


class PpiParserTest(unittest.TestCase):
    def setUp(self):
        self.res = PpiParser().parse(_csv())
        self.rows = [rr.data for rr in self.res.raw_rows]

    # ── Detección ────────────────────────────────────────────────────────────
    def test_autodetect_picks_ppi(self):
        self.assertEqual(autodetect(HDR.split(",")).format_id, "ppi")

    def test_autodetect_does_not_steal_balanz_or_bullmarket(self):
        # Balanz Movimientos NO trae 'saldo' → PPI no lo agarra.
        balanz = "Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,Liquidacion,Moneda,Importe"
        self.assertNotEqual((autodetect(balanz.split(",")) or get_parser("ppi")).format_id, "ppi")
        # Bull Market no trae 'descripcion'/'moneda' → PPI no lo agarra.
        bm = "Liquida,Operado,Comprobante,Numero,Cantidad,Especie,Precio,Importe,Saldo,Referencia"
        bm_auto = autodetect(bm.split(","))
        self.assertNotEqual((bm_auto.format_id if bm_auto else ""), "ppi")

    # ── Trades ───────────────────────────────────────────────────────────────
    def test_trade_direction_by_token_robust_to_sign(self):
        # VENTA AL30 con Importe NEGATIVO igual sale VENTA (dirección por token),
        # con monto = abs(Importe) y moneda USD.
        venta = [r for r in self.rows if r["tipo"] == "VENTA" and r.get("activo") == "AL30"]
        self.assertEqual(len(venta), 1)
        self.assertEqual(venta[0]["moneda"], "USD")
        self.assertAlmostEqual(float(venta[0]["monto"]), 64311.36, places=2)

    def test_compra_currency_routing(self):
        compra = [r for r in self.rows if r["tipo"] == "COMPRA" and r.get("activo") == "NU"
                  and r["moneda"] == "ARS"]
        self.assertEqual(len(compra), 1)
        self.assertAlmostEqual(float(compra[0]["monto"]), 3204064.14, places=2)

    # ── FCI ──────────────────────────────────────────────────────────────────
    def test_fci_suscripcion_is_buy_rescate_is_sell(self):
        sub = [r for r in self.rows if r["tipo"] == "COMPRA" and r.get("asset_type") == "FUND"]
        red = [r for r in self.rows if r["tipo"] == "VENTA" and r.get("asset_type") == "FUND"]
        self.assertEqual(len(sub), 1)
        self.assertEqual(len(red), 1)
        self.assertIn("ALLARIA DOLAR AHORRO", sub[0]["activo"])
        self.assertEqual(sub[0]["moneda"], "USD")
        self.assertIn("BALANZ CAPITAL AHORRO", red[0]["activo"])

    # ── Cash flows ───────────────────────────────────────────────────────────
    def test_deposit_and_withdraw(self):
        self.assertTrue(any(r["tipo"] == "DEPOSITO" and r["moneda"] == "USD" for r in self.rows))
        self.assertTrue(any(r["tipo"] == "RETIRO" and r["moneda"] == "ARS" for r in self.rows))

    def test_dividend_sign(self):
        divs = [r for r in self.rows if r["tipo"] == "DIVIDENDO"]
        fees = [r for r in self.rows if r["tipo"] == "FEE"]
        self.assertTrue(any(r.get("activo") == "MSFT" for r in divs))   # +5.48 → DIVIDENDO
        self.assertTrue(any(abs(float(r["monto"]) - 2.0) < 1e-6 for r in fees))  # -2 → FEE

    def test_manual_by_sign(self):
        # Canje +158.34 → INTERES ; Compensación -9.4 → FEE (ambos USD)
        self.assertTrue(any(r["tipo"] == "INTERES" and abs(float(r["monto"]) - 158.34) < 1e-6
                            for r in self.rows))
        self.assertTrue(any(r["tipo"] == "FEE" and abs(float(r["monto"]) - 9.4) < 1e-6
                            for r in self.rows))

    # ── Caución / holds ──────────────────────────────────────────────────────
    def test_caucion_nets_to_single_interes(self):
        interes_caucion = [r for r in self.rows if r["tipo"] == "INTERES"
                           and "cauci" in (r.get("notas") or "").lower()]
        self.assertEqual(len(interes_caucion), 1)
        self.assertAlmostEqual(float(interes_caucion[0]["monto"]), 5000.0, places=2)
        self.assertEqual(interes_caucion[0]["moneda"], "ARS")

    def test_bloqueo_desbloqueo_skipped(self):
        self.assertFalse(any("bloqueo" in (r.get("notas") or "").lower() for r in self.rows))

    # ── Instrumentos ─────────────────────────────────────────────────────────
    def test_retiro_titulos_is_transfer_out(self):
        to = [r for r in self.rows if r.get("_transfer_out")]
        self.assertEqual(len(to), 1)
        self.assertEqual(to[0]["activo"], "CEPU")
        self.assertEqual(to[0]["tipo"], "VENTA")
        self.assertEqual(to[0]["precio"], "0")
        self.assertAlmostEqual(float(to[0]["cantidad"]), 787.9, places=2)

    def test_instrumentos_trade_skipped(self):
        # La COMPRA NU de Instrumentos (precio 0, redundante) NO se emite ni se
        # marca como error — el trade real viene de la hoja de moneda.
        instr_compras = [r for r in self.rows if r.get("activo") == "NU"
                         and r["tipo"] == "COMPRA" and r.get("precio") == "0"]
        self.assertEqual(instr_compras, [])

    # ── SPOT flagging ────────────────────────────────────────────────────────
    def test_spot_flagged_not_emitted(self):
        self.assertTrue(any(e.code == "PPI_SPOT_REVIEW" for e in self.res.parse_errors))
        self.assertFalse(any(r.get("activo") == "SPOT" for r in self.rows))

    # ── Reconciliación self-consistente del cash emitido ─────────────────────
    def test_emitted_cash_totals(self):
        emit = {"ARS": 0.0, "USD": 0.0}
        for r in self.rows:
            c = r.get("moneda")
            if c not in emit:
                continue
            m = float(r.get("monto") or 0)
            emit[c] += (-m if r["tipo"] in OUT else (m if r["tipo"] in IN else 0))
        # ARS: -3204064.14 -204489.18 -2 +10050063.3 +5000(interés) = 6646507.98
        self.assertAlmostEqual(emit["ARS"], 6646507.98, places=2)
        # USD: +1000 +64311.36 +5.48 -8522.64 +158.34 -9.4 = 56943.14
        self.assertAlmostEqual(emit["USD"], 56943.14, places=2)

    # ── End-to-end: normaliza y valida sin errores ───────────────────────────
    def test_normalizes_and_validates_clean(self):
        norm, nerr = normalize_rows(self.res.raw_rows)
        self.assertEqual(nerr, [])
        user_brokers = {"PPI": {"id": 1, "currency": "ARS", "parent_broker_id": None}}
        valid, verr = validate(norm, user_brokers=user_brokers, existing_positions={})
        self.assertEqual(verr, [])
        self.assertEqual(len(valid), len(norm))


if __name__ == "__main__":
    unittest.main()
