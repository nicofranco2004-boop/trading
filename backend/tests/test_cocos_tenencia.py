"""Estado de Cuenta / portfolio_report de Cocos → TenenciaSnapshot + reconcile.

La FOTO de tenencia de Cocos (CSV ';' instrumento;cantidad;precio;moneda;total)
completa/reconcilia las posiciones que los Movimientos reconstruyen. Reusa el
_extract_ticker y la clasificación asset_type del parser de Movimientos → el
ticker y el tipo coinciden, así reconcile() no inventa huecos falsos.

Corre con: cd backend && python3 -m pytest tests/test_cocos_tenencia.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.tenencia import (
    looks_like_cocos_tenencia, parse_cocos_tenencia, compute_reconcile,
)

# Números fake (no son de un usuario real) — solo ejercitan el formato.
_CSV = (
    "instrumento;cantidad;precio;moneda;total\n"
    "Dólar estadounidense ();0,18;0;0;0\n"
    "CEDEAR NVIDIA CORPORATION (NVDA);28;12450;ARS;348600\n"
    "BANCO MACRO S.A. B  1 V. ESCRIT (BMA);39;14110;ARS;550290\n"
    "GRUPO FINANCIERO GALICIA S.A ESCRIT.  B  1 V (GGAL);86;7715;ARS;663490\n"
    "FCI COCOS RENDIMIENTO CL. A $ ESC (COCORMA);1000,5;1,05;ARS;1050525\n"
    "ARS;48763,5;1;ARS;48763,5\n"
    "USD;2,03;1;USD;2,03\n"
)


class CocosTenenciaTest(unittest.TestCase):
    def test_detects_header(self):
        self.assertTrue(looks_like_cocos_tenencia(_CSV))
        self.assertFalse(looks_like_cocos_tenencia("fecha;tipo;broker\n2026-01-01;COMPRA;Cocos"))
        self.assertFalse(looks_like_cocos_tenencia("Tenencias al 26/06/2026 ARS 1.000,00"))
        # CRÍTICO: el header de Movimientos de Cocos CONTIENE los 5 tokens como
        # SUBCONJUNTO (instrumento/moneda/cantidad/precio/total) → un match de
        # subconjunto lo confundiría con la foto y rutearía mal los Movimientos.
        # Debe ser match EXACTO → False.
        mov_header = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;"
                      "instrumento;moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total")
        self.assertFalse(looks_like_cocos_tenencia(mov_header))

    # El FCI se canonicaliza al símbolo del catálogo (resolve_fci_symbol) para que
    # matchee lo que los Movimientos escriben ('FCI:<slug>'); antes la foto lo dejaba
    # crudo ('COCORMA') → mismatch → duplicado en to_seed + falso 'vendido?'.
    _FCI = "FCI:COCOS-RENDIMIENTO-A"

    def test_parses_holdings_and_cash(self):
        snap = parse_cocos_tenencia(_CSV)
        by = {h.ticker: h for h in snap.holdings}
        self.assertEqual(set(by), {"NVDA", "BMA", "GGAL", self._FCI})
        # cantidades + valuación
        self.assertAlmostEqual(by["NVDA"].quantity, 28)
        self.assertAlmostEqual(by["NVDA"].value, 348600)
        self.assertAlmostEqual(by["NVDA"].price_per1, 348600 / 28, places=2)
        # asset_type igual que movimientos: CEDEAR / acción AR ("") / FCI (FUND)
        self.assertEqual(by["NVDA"].asset_type, "CEDEAR")
        self.assertEqual(by["BMA"].asset_type, "")     # acción argentina → .BA
        self.assertEqual(by["GGAL"].asset_type, "")
        self.assertEqual(by[self._FCI].asset_type, "FUND")
        # cash: ARS + USD (el 'Dólar estadounidense ()' de 0,18 va al cash USD)
        self.assertAlmostEqual(snap.cash_ars, 48763.5)
        self.assertAlmostEqual(snap.cash_usd, 2.03 + 0.18, places=2)

    def test_reconcile_matched(self):
        snap = parse_cocos_tenencia(_CSV)
        # 'current' usa el símbolo canónico (así lo guarda el normalizer de Movimientos).
        current = {"NVDA": 28, "BMA": 39, "GGAL": 86, self._FCI: 1000.5}
        rec = compute_reconcile(current, snap)
        self.assertEqual(set(rec.matched), {"NVDA", "BMA", "GGAL", self._FCI})
        self.assertEqual(rec.to_seed, [])
        self.assertEqual(rec.over, [])
        self.assertEqual(rec.not_in_snapshot, [])

    def test_reconcile_flags_over_and_gap(self):
        snap = parse_cocos_tenencia(_CSV)
        # Rendi tiene NVDA DUPLICADO (56 vs 28 en la foto) → over (anti-duplicación);
        # le falta BMA (la foto tiene 39, Rendi 0) → to_seed; y tiene un AAPL fantasma.
        current = {"NVDA": 56, "GGAL": 86, self._FCI: 1000.5, "AAPL": 10}
        rec = compute_reconcile(current, snap)
        over = {t: (rq, tq) for t, rq, tq in rec.over}
        self.assertIn("NVDA", over)                      # Rendi 56 > foto 28 → flag
        self.assertEqual(over["NVDA"], (56, 28))
        seeded = {h.ticker: gap for h, gap in rec.to_seed}
        self.assertAlmostEqual(seeded.get("BMA"), 39)    # hueco a completar
        nis = {t for t, q in rec.not_in_snapshot}
        self.assertIn("AAPL", nis)                       # en Rendi, no en la foto


if __name__ == "__main__":
    unittest.main()
