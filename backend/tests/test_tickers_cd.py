"""La pata dólar/cable (D/C) se consolida al ticker base.

EL CASO REAL (reportado por un usuario el 2026-08-01): hacer "dólar MEP" son DOS
operaciones el mismo día sobre el mismo instrumento — se compra AL30 en pesos y
se vende AL30D en dólares. El broker las exporta con tickers DISTINTOS, y el
replay FIFO arma un ledger por símbolo EXACTO (`rebuild.py _full_events` filtra
`n.asset_symbol = ?`), así que quedan dos libros que nunca se ven:

  · la compra de AL30 queda ABIERTA → activo fantasma que el usuario no tiene
  · la venta de AL30D no encuentra stock → lote semilla al precio de venta, P&L 0

Textual del reporte: "puede registrarse una ganancia irreal o que te tome venta
de un activo que no tenías registro inicial y posterior comprar, dejando un
activo en la cartera que no existe".

NO es un problema de ORDEN: el BUY-first ya existe en los dos motores
(`persister.py` `_BUY_FIRST_KEY`, `rebuild.py` ORDER BY con CASE). Se verificó
que con el MISMO ticker en las dos patas el sistema lo resuelve solo, neto cero.
La única diferencia entre el caso sano y el roto es la letra final.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from importing.tickers_cd import (  # noqa: E402
    consolidate_cd, strip_cd_suffix, KNOWN_CD_TICKERS, CD_ASSET_TYPES,
)


class PataDolarTest(unittest.TestCase):
    """Lo que SÍ se consolida: bonos, acciones AR y CEDEARs."""

    def test_el_caso_del_reporte(self):
        self.assertEqual(consolidate_cd("AL30D", "BOND"), "AL30")
        self.assertEqual(consolidate_cd("AL30", "BOND"), "AL30")   # ya base, no cambia

    def test_cable_tambien(self):
        self.assertEqual(consolidate_cd("GD30C", "BOND"), "GD30")

    def test_cedear_y_accion(self):
        self.assertEqual(consolidate_cd("GGALD", "CEDEAR"), "GGAL")
        self.assertEqual(consolidate_cd("PAMPD", "STOCK"), "PAMP")

    def test_sufijo_de_moneda(self):
        self.assertEqual(strip_cd_suffix("AL30 US$"), "AL30")
        self.assertEqual(strip_cd_suffix("GD30 U$S"), "GD30")

    def test_normaliza_espacios_y_mayusculas(self):
        self.assertEqual(consolidate_cd("  al30d  ", "BOND"), "AL30")


class NoSeToquenTest(unittest.TestCase):
    """Lo que NO se toca. Consolidar de más parte en dos el historial de un
    activo que estaba bien — es peor que el bug que se está arreglando."""

    def test_tickers_que_terminan_en_CD_de_verdad(self):
        # Sin la lista de excepciones: AMD→AM, GOLD→GOL, INTC→INT.
        for t in ("AMD", "GOLD", "INTC", "YPFD", "MCD", "BAC", "WFC"):
            self.assertEqual(consolidate_cd(t, "STOCK"), t, t)

    def test_la_lista_cubre_los_de_tickers_js(self):
        # Si alguien agrega un ticker terminado en C/D al allowlist del frontend
        # sin agregarlo acá, se le parte el historial en silencio.
        for t in ("AMD", "GOLD", "INTC", "USDC", "BTC", "LTC", "ETC"):
            self.assertIn(t, KNOWN_CD_TICKERS)

    def test_fci_nunca(self):
        # El ticker de un FCI termina en D/C legítimamente (IOLDOLD) y truncarlo
        # lo desalinea de la foto de tenencia.
        self.assertEqual(consolidate_cd("IOLDOLD", "FUND"), "IOLDOLD")
        self.assertEqual(strip_cd_suffix("IOLDOLD", is_fci=True), "IOLDOLD")

    def test_cripto_y_fiat_no_tienen_pata_dolar(self):
        self.assertEqual(consolidate_cd("USDC", "CRYPTO"), "USDC")
        self.assertEqual(consolidate_cd("BTC", "CRYPTO"), "BTC")
        self.assertEqual(consolidate_cd("USD", "FIAT"), "USD")

    def test_sin_tipo_no_se_arriesga(self):
        # Si el parser no clasificó el activo, no hay con qué decidir: intacto.
        self.assertEqual(consolidate_cd("AL30D", None), "AL30D")
        self.assertEqual(consolidate_cd("AL30D", ""), "AL30D")
        self.assertEqual(consolidate_cd("AL30D", "OTHER"), "AL30D")
        self.assertEqual(consolidate_cd("AL30D", "ETF"), "AL30D")

    def test_el_punto_marca_la_clase(self):
        # BA.C, BR.K: el punto ya separa la clase, la letra final es del símbolo.
        self.assertEqual(consolidate_cd("BA.C", "STOCK"), "BA.C")

    def test_tickers_muy_cortos(self):
        # Con menos de 3 caracteres no queda ticker si le sacás una letra.
        self.assertEqual(consolidate_cd("AD", "STOCK"), "AD")
        self.assertEqual(consolidate_cd("C", "STOCK"), "C")

    def test_vacio_no_rompe(self):
        self.assertEqual(consolidate_cd("", "BOND"), "")
        self.assertEqual(consolidate_cd(None, "BOND"), None)
        self.assertEqual(strip_cd_suffix(None), "")

    def test_los_tipos_gateados_son_los_esperados(self):
        self.assertEqual(CD_ASSET_TYPES, {"BOND", "STOCK", "CEDEAR"})


class NormalizerAplicaLaConsolidacionTest(unittest.TestCase):
    """El chokepoint: un solo lugar decide el símbolo de toda fila importada."""

    def test_normalizer_llama_a_consolidate_cd(self):
        import inspect
        import importing.normalizer as nz
        src = inspect.getsource(nz)
        self.assertIn("consolidate_cd(asset_raw, asset_type)", src)

    def test_el_fci_sigue_teniendo_prioridad(self):
        # La rama FUND resuelve el símbolo del catálogo y NO pasa por la
        # consolidación: son excluyentes.
        import inspect
        import importing.normalizer as nz
        src = inspect.getsource(nz)
        i = src.index('if asset_type == "FUND" and asset_raw:')
        bloque = src[i:i + 600]
        self.assertIn("resolve_fci_symbol", bloque)
        self.assertIn("else:", bloque)


class ElBuyFirstYaExistiaTest(unittest.TestCase):
    """Guarda de contexto: el fix NO es de ordenamiento. Si alguien borra el
    BUY-first pensando que este cambio lo reemplaza, rompe el caso mismo-ticker
    que hoy funciona."""

    def test_persister_ordena_buy_primero(self):
        import inspect
        import importing.persister as ps
        src = inspect.getsource(ps)
        self.assertIn("_BUY_FIRST_KEY", src)

    def test_rebuild_ordena_buy_primero(self):
        import inspect
        import importing.rebuild as rb
        src = inspect.getsource(rb)
        self.assertIn("CASE n.operation_type WHEN ? THEN 0 ELSE 1 END", src)


if __name__ == "__main__":
    unittest.main()
