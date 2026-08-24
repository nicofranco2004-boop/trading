"""Los tickers de la FOTO se canonicalizan igual que los de los movimientos.

🔴 EL BUG. `compute_reconcile` matchea por IGUALDAD EXACTA DE STRING contra
`positions.asset`, que viene del normalizador y sí pasa por `consolidate_cd`
(`normalizer.py:372`). La foto no pasaba por ahí. Con AL30D en la foto y AL30 en
Rendi, el reconcile reportaba DOS problemas del mismo activo:

  · `not_in_snapshot` FALSO — "AL30 está en Rendi y no está en la foto"
  · `to_seed` FALSO — "AL30D está en la foto y falta en Rendi"

El primero es el peligroso: con el override prendido, cerrar ese ausente con una
venta sintética BORRA una tenencia que el cliente SÍ tiene. En prod ya hay 7
tickers con sufijo D grabados en `positions` de 4 usuarios.
"""
import unittest

from importing.tenencia import (Holding, TenenciaSnapshot, compute_reconcile,
                                normalizar_tickers)


def _snap(*holdings):
    return TenenciaSnapshot(holdings=list(holdings), date="2026-06-30")


def _h(ticker, qty, tipo="BOND", ccy="ARS", value=None, price=None):
    v = value if value is not None else qty * (price or 1.0)
    return Holding(ticker=ticker, asset_type=tipo, quantity=qty, value=v,
                   currency=ccy, price_per1=(v / qty if qty else 0.0))


class NormalizarTickersTest(unittest.TestCase):
    # ── el caso que motivó todo ─────────────────────────────────────────────
    def test_la_pata_dolar_deja_de_inventar_un_activo_fantasma(self):
        # Antes: Rendi tiene AL30, la foto dice AL30D → un not_in_snapshot falso
        # (AL30) y un to_seed falso (AL30D). Con override, el primero borraba
        # una tenencia real.
        snap = _snap(_h("AL30D", 1000))
        normalizar_tickers(snap)
        rec = compute_reconcile({"AL30": 1000.0}, snap)
        self.assertEqual(rec.matched, ["AL30"])
        self.assertEqual(rec.not_in_snapshot, [])
        self.assertEqual(rec.to_seed, [])

    def test_sin_normalizar_el_bug_se_reproduce(self):
        # El control negativo: si no se normaliza, aparecen los dos falsos. Sin
        # este test el de arriba podría pasar por casualidad.
        snap = _snap(_h("AL30D", 1000))
        rec = compute_reconcile({"AL30": 1000.0}, snap)
        self.assertEqual([t for t, _ in rec.not_in_snapshot], ["AL30"])
        self.assertEqual(len(rec.to_seed), 1)

    def test_reporta_lo_que_cambio(self):
        # Una transformación silenciosa sobre los datos de alguien es lo que
        # este flujo existe para no hacer.
        snap = _snap(_h("AL30D", 1000))
        cambios = normalizar_tickers(snap)
        self.assertEqual(len(cambios), 1)
        self.assertEqual(cambios[0]["de"], "AL30D")
        self.assertEqual(cambios[0]["a"], "AL30")
        self.assertEqual(cambios[0]["motivo"], "sufijo_dolar")

    # ── la fusión ───────────────────────────────────────────────────────────
    def test_las_dos_patas_en_la_misma_foto_se_FUSIONAN(self):
        # Pasa mientras el conducto MEP está abierto. Dejarlas como dos holdings
        # después de consolidar es PEOR que no normalizar: compute_reconcile
        # itera holdings y compararía cada uno contra la cantidad TOTAL de Rendi.
        snap = _snap(_h("AL30", 600, price=1.0), _h("AL30D", 400, price=1.0))
        normalizar_tickers(snap)
        self.assertEqual(len(snap.holdings), 1)
        self.assertEqual(snap.holdings[0].ticker, "AL30")
        self.assertEqual(snap.holdings[0].quantity, 1000)
        rec = compute_reconcile({"AL30": 1000.0}, snap)
        self.assertEqual(rec.matched, ["AL30"])
        self.assertEqual(rec.over, [])
        self.assertEqual(rec.to_seed, [])

    def test_la_fusion_re_deriva_el_precio_del_total(self):
        snap = _snap(_h("AL30", 100, value=200.0), _h("AL30D", 100, value=300.0))
        normalizar_tickers(snap)
        h = snap.holdings[0]
        self.assertEqual(h.value, 500.0)
        self.assertEqual(h.quantity, 200)
        self.assertAlmostEqual(h.price_per1, 2.5)

    def test_la_fusion_NO_cruza_monedas(self):
        # El camino de PPI particiona la foto por moneda y concilia cada parte
        # contra SU sub-broker. Fusionar entre monedas mezclaría magnitudes.
        snap = _snap(_h("AL30", 100, ccy="ARS"), _h("AL30D", 100, ccy="USD"))
        normalizar_tickers(snap)
        self.assertEqual(len(snap.holdings), 2)
        self.assertEqual({h.currency for h in snap.holdings}, {"ARS", "USD"})

    def test_la_fusion_se_reporta(self):
        snap = _snap(_h("AL30", 600), _h("AL30D", 400))
        cambios = normalizar_tickers(snap)
        self.assertTrue(any(c["motivo"] == "fusion" for c in cambios))

    # ── lo que NO se toca ───────────────────────────────────────────────────
    def test_no_toca_los_tickers_que_terminan_en_D_de_verdad(self):
        # AMD, GOLD, HD… sin la allowlist quedarían AM, GOL, H.
        for t in ("AMD", "GOLD", "HD"):
            snap = _snap(_h(t, 10, tipo="STOCK"))
            normalizar_tickers(snap)
            self.assertEqual(snap.holdings[0].ticker, t)

    def test_no_toca_los_tipos_fuera_del_gate(self):
        # consolidate_cd sólo actúa sobre BOND/STOCK/CEDEAR. Un FCI que termina
        # en D es un nombre real, y truncarlo lo desalinea de la foto.
        snap = _snap(_h("PIONERO D", 10, tipo="FUND"))
        normalizar_tickers(snap)
        self.assertEqual(snap.holdings[0].ticker, "PIONERO D")

    def test_una_foto_ya_canonica_no_cambia_nada(self):
        snap = _snap(_h("AL30", 100), _h("GD30", 50))
        self.assertEqual(normalizar_tickers(snap), [])
        self.assertEqual(len(snap.holdings), 2)

    def test_es_idempotente(self):
        snap = _snap(_h("AL30D", 1000))
        normalizar_tickers(snap)
        self.assertEqual(normalizar_tickers(snap), [])



class BonoAmortizanteTest(unittest.TestCase):
    """`to_seed` es el único balde que se auto-aplica, y sobre un bono
    amortizante su premisa no se cumple.

    `positions` guarda el nominal RESIDUAL (`sweep_bond_amortizations` lo
    re-escala en cada import). La foto reporta el nominal ORIGINAL — medido
    contra la copia de prod del 2026-08-16: de 26 casos medibles, 18 (69%)
    cierran con la hipótesis `gap = N × (1 − residual_factor)`, y es consistente
    en los cinco parsers con casos (Bull Market 3/3, IOL 3/3, PPI 1/1, Balanz
    8/12, Cocos 3/7).

    O sea que Rendi < foto SIEMPRE, y `to_seed` fabricaba una compra sintética
    que nunca pasó — con el sello de "esto lo confirma el resumen del broker".
    Ya pasó 35 veces sobre 25 usuarios antes de esta guarda.
    """

    def _h_bono(self, ticker, qty):
        return Holding(ticker=ticker, asset_type="BOND", quantity=qty,
                       value=qty * 0.6, currency="ARS", price_per1=0.6)

    def test_un_bono_amortizante_NO_se_auto_siembra(self):
        # La fila SE CONSTRUYE (asi el ruteo de moneda y la herencia de costo
        # siguen corriendo) pero queda marcada: el confirm no la aplica sola.
        from importing.tenencia import (marcar_bonos_amortizantes,
                                        build_tenencia_seed_txs,
                                        requiere_aprobacion)
        snap = _snap(self._h_bono("AL30", 1000))
        rec = compute_reconcile({"AL30": 720.0}, snap)      # positions = residual
        self.assertEqual(len(rec.to_seed), 1)
        self.assertEqual(marcar_bonos_amortizantes(rec), 1)
        # Sigue en to_seed: no perdemos la tx ni su logica.
        self.assertEqual(len(rec.to_seed), 1)
        self.assertEqual(rec.no_reconciliable[0]["motivo"], "escala_bono_amortizante")
        self.assertTrue(rec.no_reconciliable[0]["requiere_aprobacion"])
        # Y la tx sintetica sale marcada, que es lo que el confirm lee.
        txs = build_tenencia_seed_txs("Cocos", rec, "2026-06-30")
        compras = [t for t in txs if t.asset_symbol == "AL30"]
        self.assertEqual(len(compras), 1)
        self.assertTrue(requiere_aprobacion(compras[0].notes))

    def test_un_activo_normal_NO_queda_marcado(self):
        # La guarda es quirurgica: no puede apagar el gap-fill, que es la razon
        # de ser de la foto.
        from importing.tenencia import (marcar_bonos_amortizantes,
                                        build_tenencia_seed_txs,
                                        requiere_aprobacion)
        snap = _snap(_h("GGAL", 100, tipo="STOCK"))
        rec = compute_reconcile({"GGAL": 60.0}, snap)
        self.assertEqual(marcar_bonos_amortizantes(rec), 0)
        self.assertEqual(len(rec.to_seed), 1)
        txs = build_tenencia_seed_txs("Cocos", rec, "2026-06-30")
        self.assertFalse(any(requiere_aprobacion(t.notes) for t in txs))

    def test_el_motivo_explica_QUE_hacer(self):
        from importing.tenencia import marcar_bonos_amortizantes
        snap = _snap(self._h_bono("GD30", 500))
        rec = compute_reconcile({"GD30": 320.0}, snap)
        marcar_bonos_amortizantes(rec)
        d = rec.no_reconciliable[0]["detalle"]
        self.assertIn("RESIDUAL", d)
        self.assertIn("ORIGINAL", d)

if __name__ == "__main__":
    unittest.main()
