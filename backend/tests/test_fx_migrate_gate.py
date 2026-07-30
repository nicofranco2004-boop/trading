"""El gate server-side del migrador FX: la verificación FRENA, no solo informa.

Antes, `migrate_user_fx` calculaba `delta_pnl_implausible` / `cash_intacto` /
`ventas_con_tc_distinto` y los escribía SOLO en `resultado["verificacion"]`,
dejando `ok=True`. El endpoint tiene el rollback (`if not out.get("ok")`), pero
nunca se disparaba: el único freno era que el operador viera el semáforo rojo y
destildara la fila a mano — y el apply masivo permite aplicar sin simular.

Además el umbral de implausibilidad era `>US$100k Y >US$1.000/venta`: en el
dry-run masivo de 2026-07-29 una cuenta con 1.203 ventas y Δ P&L de US$ 339.593
(282/venta) salía en VERDE por no llegar al segundo umbral.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import importing.fx_migrate as fxm  # noqa: E402


class UmbralImplausibleTest(unittest.TestCase):
    """El umbral nuevo es OR, no AND. Replica la aritmética del módulo."""

    @staticmethod
    def _implausible(d_pnl, n_ventas):
        n = max(int(n_ventas), 1)
        return d_pnl > 100_000 or ((d_pnl / n) > 1_000 and d_pnl > 10_000)

    def test_caza_el_falso_negativo_medido_en_prod(self):
        # Cuenta #499 del dry-run: 1.203 ventas, Δ P&L US$ 339.593 → 282/venta.
        # Con el umbral viejo (AND) pasaba en verde.
        viejo = 339_593 > 100_000 and (339_593 / 1203) > 1_000
        self.assertFalse(viejo, "el umbral viejo la dejaba pasar (por eso el fix)")
        self.assertTrue(self._implausible(339_593, 1203))

    def test_sigue_cazando_las_corruptas_por_venta(self):
        # #834: 62 ventas, Δ 21,5M → 347k/venta.
        self.assertTrue(self._implausible(21_546_698, 62))

    def test_no_marca_las_sanas(self):
        # Rango medido de cuentas sanas: 0-378 por venta, magnitudes chicas.
        self.assertFalse(self._implausible(4_775, 1245))   # #595
        self.assertFalse(self._implausible(332, 2689))     # #762
        self.assertFalse(self._implausible(29_112, 593))   # #587: 49/venta
        self.assertFalse(self._implausible(0, 1))

    def test_una_venta_con_delta_chico_no_dispara_por_venta(self):
        # Sin el piso de 10k, una sola venta con 1.500 de delta marcaría.
        self.assertFalse(self._implausible(1_500, 1))


class GateFrenaTest(unittest.TestCase):
    """El gate arma `frenos` y apaga `ok` — salvo force=True."""

    def test_el_modulo_expone_force_y_lo_respeta(self):
        import inspect
        sig = inspect.signature(fxm.migrate_user_fx)
        self.assertIn("force", sig.parameters)
        self.assertIs(sig.parameters["force"].default, False)

    def test_el_codigo_apaga_ok_con_frenos(self):
        src = inspect_source()
        self.assertIn('resultado["ok"] = False', src)
        self.assertIn("_frenos", src)
        # Las tres señales que frenan
        self.assertIn("cash_intacto", src)
        self.assertIn("mal_tc", src)
        self.assertIn("_implausible", src)

    def test_el_aportado_se_reporta_pero_NO_frena(self):
        """Un salto grande del aportado es la FIRMA DE LA REPARACIÓN (un flujo de
        2013 dolarizado a 1415 y re-derivado a ~5 lo multiplica ×280), así que no
        puede frenar. Se muestra con el 'antes' al lado para que se juzgue."""
        src = inspect_source()
        self.assertIn("aportado_antes_usd", src)
        self.assertIn("aportado_delta_pct", src)
        self.assertNotIn("_aportado_implausible", src)


def inspect_source():
    import inspect
    return inspect.getsource(fxm)


class DenominadorRotoTest(unittest.TestCase):
    """El freno que sí es objetivo: el aportado es el denominador del rendimiento.

    Los números vienen del dry-run real de 2026-07-30 sobre 503 cuentas.
    """

    def test_cruza_a_negativo_con_cartera_positiva(self):
        # #826: aportado 2.820 → −1.477.984. El hero mostraría "Ganancia total"
        # en dólares (inflada) con "+0,0%" al lado.
        m = fxm.denominador_roto(50_000, 2_820, -1_477_984, None)
        self.assertIsNotNone(m)
        self.assertIn("deja de tener sentido", m)

    def test_cruza_a_negativo_aunque_sea_chico(self):
        # #946: 394 → −264. Chico en dólares, pero el % igual deja de existir.
        self.assertIsNotNone(fxm.denominador_roto(9_000, 394, -264, None))

    def test_denominador_casi_cero_explota_el_porcentaje(self):
        # Sin clamp en pctSigned: US$1 de aportado con US$50.000 de cartera.
        self.assertIsNotNone(fxm.denominador_roto(50_000, 20_000, 1, 4_999_900.0))

    def test_no_frena_la_reparacion_normal(self):
        # #595: 79.311 → 874.375 (×11). Es la corrección funcionando.
        self.assertIsNone(fxm.denominador_roto(120_000, 79_311, 874_375, -86.3))
        # #719: 39 → 606 (×15,7), cuenta chica.
        self.assertIsNone(fxm.denominador_roto(700, 39, 606, 15.5))

    def test_no_frena_si_ya_venia_negativo(self):
        # #808: −509.588 → −509.652. Ya era negativo ANTES; la migración no lo
        # rompió y frenarla no arregla nada — es un problema aparte.
        self.assertIsNone(fxm.denominador_roto(30_000, -509_588, -509_652, None))

    def test_sin_snapshot_no_opina(self):
        # Sin valor de cartera no hay con qué juzgar: no se inventa un freno.
        self.assertIsNone(fxm.denominador_roto(None, 2_820, -1_477_984, None))

    def test_cartera_vacia_no_frena(self):
        # Cuenta sin cartera: el rendimiento no le importa a nadie.
        self.assertIsNone(fxm.denominador_roto(0, 2_820, -1_477_984, None))


class RendimientoVisibleTest(unittest.TestCase):
    """El panel tiene que mostrar el número que el usuario va a ver."""

    def test_metricas_expone_el_rendimiento_del_dashboard(self):
        import inspect
        src = inspect.getsource(fxm._metricas)
        # La fórmula del hero: (totalValue − netDeposited) / netDeposited, con
        # netDeposited = capital_inicio del primer mes + Σ(deposits − withdrawals).
        self.assertIn("capital_inicio", src)
        self.assertIn("aportado_dashboard_usd", src)
        self.assertIn("valor_cartera_usd", src)
        self.assertIn("rendimiento_pct", src)

    def test_el_resultado_reporta_antes_y_despues(self):
        src = inspect_source()
        for campo in ("rendimiento_antes_pct", "rendimiento_despues_pct",
                      "aportado_dashboard_antes_usd", "baseline_borrada_usd"):
            self.assertIn(campo, src)


class SnapshotsNoSePisanTest(unittest.TestCase):
    """El backfill de snapshots desde monthly no puede pisar una medición real."""

    def test_el_upsert_es_do_nothing(self):
        import inspect
        import importing.persister as ps
        src = inspect.getsource(ps._backfill_snapshots_from_monthly)
        self.assertIn("DO NOTHING", src)
        self.assertNotIn("total_value = excluded.total_value", src)


if __name__ == "__main__":
    unittest.main()
