"""La fecha de la foto: cuándo se pudo leer, y qué pasa cuando no.

DOS COSAS DISTINTAS, MEDIDAS CONTRA LA COPIA DE PROD DEL 2026-08-16:

1. Tres de los parsers de foto exigían día y mes de DOS dígitos, así que un
   "Tenencias al 9/6/2026" no matcheaba y la fecha caía al fallback. Es el fix
   de `8cd5b120`, que se aplicó a todos los parsers de MOVIMIENTOS y nunca llegó
   a los de FOTO. `_IOL_DATE_RE` ya aceptaba 1-2 dígitos y es —no por
   casualidad— el único parser de foto con 0 fallbacks medidos (0 de 25).

2. Cuando no se pudo leer, el endpoint caía al reloj del servidor EN SILENCIO:
   93 de 152 fotos confirmadas están en esa situación, y `parse_cocos_tenencia`
   no setea fecha nunca (47 de 47 por código). `compute_reconcile` compara la
   foto contra el estado de HOY, lo cual sólo vale si la foto ES de hoy — con la
   fecha inventada esa premisa no se puede verificar.
"""
import unittest

from importing.tenencia import (Holding, TenenciaSnapshot, _to_iso,
                                compute_reconcile, parse_balanz_tenencia,
                                parse_bullmarket_tenencia)


class FechaUnDigitoTest(unittest.TestCase):
    def test_to_iso_acepta_un_digito(self):
        self.assertEqual(_to_iso("9/6/2026"), "2026-06-09")
        self.assertEqual(_to_iso("09/06/2026"), "2026-06-09")
        self.assertEqual(_to_iso("31/12/2025"), "2025-12-31")

    def test_to_iso_zero_paddea_de_verdad(self):
        # 🔴 El bug sutil: concatenando strings, "9/6/2026" daba "2026-6-9", que
        # NO es ISO — ordena mal contra cualquier otra fecha y rompe los
        # `date <= ?` del replay sin que nada avise.
        iso = _to_iso("9/6/2026")
        self.assertEqual(len(iso), 10)
        self.assertLess(iso, "2026-06-10")
        self.assertGreater(iso, "2026-06-08")

    def test_to_iso_sigue_rechazando_basura(self):
        self.assertIsNone(_to_iso(""))
        self.assertIsNone(_to_iso("no es una fecha"))
        self.assertIsNone(_to_iso(None))

    def test_bullmarket_lee_la_fecha_con_un_digito(self):
        texto = ("Tenencia valorizada a una fecha\n"
                 "Tenencias al 9/6/2026 ARS 1.000,00\n"
                 "Nombre de la Especie Cantidad Precio Importe\n"
                 "AL30 1.000,00 60,00 600,00\n")
        snap = parse_bullmarket_tenencia(texto)
        self.assertEqual(snap.date, "2026-06-09")

    def test_balanz_lee_la_fecha_con_un_digito(self):
        # `_BAL_DATE_RE` corre sobre el texto deacentuado y en minúsculas.
        texto = "resumen de cuenta\nfecha resumen 9/6/2026\n"
        snap = parse_balanz_tenencia(texto)
        self.assertEqual(snap.date, "2026-06-09")


class NoReconciliableTest(unittest.TestCase):
    def _snap(self):
        return TenenciaSnapshot(holdings=[
            Holding(ticker="AL30", asset_type="BOND", quantity=1000,
                    value=600.0, currency="ARS", price_per1=0.6)])

    def test_sin_motivo_reconcilia_normal(self):
        rec = compute_reconcile({"AL30": 1000.0}, self._snap())
        self.assertEqual(rec.matched, ["AL30"])
        self.assertEqual(rec.no_reconciliable, [])

    def test_con_motivo_NO_produce_ningun_veredicto(self):
        # ⭐ El punto: no es un quinto balde con información extra, es la
        # NEGATIVA a producir los otros cuatro. Mostrar un `over` calculado
        # contra una fecha inventada, y encima pedir que alguien decida si borra
        # una tenencia, es peor que no mostrar nada.
        rec = compute_reconcile({"AL30": 1000.0}, self._snap(),
                                no_reconciliable_motivo="fecha_desconocida")
        self.assertEqual(rec.matched, [])
        self.assertEqual(rec.to_seed, [])
        self.assertEqual(rec.over, [])
        self.assertEqual(rec.not_in_snapshot, [])
        self.assertEqual(len(rec.no_reconciliable), 1)
        self.assertEqual(rec.no_reconciliable[0]["motivo"], "fecha_desconocida")

    def test_el_motivo_alcanza_lo_que_esta_solo_en_RENDI(self):
        # El activo que hoy saldría como `not_in_snapshot` —el caso de Apple—
        # también tiene que quedar sin veredicto, porque es justo el que se
        # cerraría con una venta sintética.
        rec = compute_reconcile({"AL30": 1000.0, "AAPL": 5.0}, self._snap(),
                                no_reconciliable_motivo="fecha_desconocida")
        tickers = {x["ticker"] for x in rec.no_reconciliable}
        self.assertEqual(tickers, {"AL30", "AAPL"})
        self.assertEqual(rec.not_in_snapshot, [])

    def test_conserva_las_cantidades_de_los_dos_lados(self):
        # Sin las dos cantidades el asesor no puede juzgar nada por su cuenta.
        rec = compute_reconcile({"AL30": 400.0}, self._snap(),
                                no_reconciliable_motivo="fecha_desconocida")
        x = rec.no_reconciliable[0]
        self.assertEqual(x["rendi_qty"], 400.0)
        self.assertEqual(x["foto_qty"], 1000)

    def test_lo_que_esta_solo_en_rendi_no_trae_foto_qty(self):
        rec = compute_reconcile({"AAPL": 5.0},
                                TenenciaSnapshot(holdings=[]),
                                no_reconciliable_motivo="fecha_desconocida")
        self.assertIsNone(rec.no_reconciliable[0]["foto_qty"])


if __name__ == "__main__":
    unittest.main()
