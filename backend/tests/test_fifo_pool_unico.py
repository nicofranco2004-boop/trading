"""BANCO DE ACEPTACIÓN del FIFO cross-currency. Se escribe ANTES del cambio.

QUÉ DEFINE ESTE ARCHIVO
───────────────────────
Un CEDEAR/bono/acción es UN activo. Si comprás 100 nominales en pesos, tenés 100
— podés venderlos en pesos o en dólares, es la misma tenencia. La moneda importa
para el COSTO de cada lote, no para CUÁNTOS tenés.

El motor de hoy modela cada activo como DOS carteras separadas por moneda, y para
mover nominales de una a otra usa un "presupuesto de spill" calculado sobre el
NETO de todo el historial. Cuando ese presupuesto no alcanza, FABRICA un lote
semilla al precio de venta (P&L 0). De ahí salen los dos síntomas que reportaron
los usuarios: nominales abiertos que no existen, y ganancia inflada.

CÓMO SE USA ESTE BANCO
──────────────────────
Cada caso declara el resultado CORRECTO, no el actual. Los que hoy fallan están
marcados con `expectedFailure` y su motivo; cuando el motor pase al pool único
tienen que ponerse en verde SIN que ninguno de los demás se caiga.

Los casos GUARD (tenencia genuina dual-currency) son los que tumbaron los tres
intentos anteriores. Están escritos con los números exactos de los contraejemplos
que los verificadores midieron. Si uno solo de ellos se rompe, el cambio no va:
es preferible dejar el caso de Nubank roto que romperle el número a un usuario
que hoy lo tiene bien.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from test_rebuild_fifo import _Base, _csv  # noqa: E402


class _PoolBase(_Base):
    """Broker en pesos con sibling USD — el escenario de todos los brokers AR."""
    BROKER = "IOL"
    BROKER_CCY = "ARS"

    def setUp(self):
        super().setUp()
        self._set_tc_blue(1000.0)

    def _abierto(self, asset="NU"):
        return self._open_qty(asset)

    def _semillas(self, asset="NU"):
        """Ventas con entry_price == exit_price: la firma del lote fabricado."""
        r = self.conn.execute(
            "SELECT COUNT(*) c FROM operations WHERE user_id=? AND asset=? "
            "AND op_type='Venta' AND ABS(entry_price-exit_price)<1e-9",
            (self.uid, asset)).fetchone()
        return int(r["c"] or 0)


# ─────────────────────────────────────────────────────────────────────────────
# CASOS QUE HOY FALLAN — son el objetivo del cambio
# ─────────────────────────────────────────────────────────────────────────────

class CasoNubankTest(_PoolBase):
    """El reporte del usuario, reducido a su esqueleto.

    Compró en las dos monedas y vendió en las dos. Los nominales netean a cero.
    Medido sobre su archivo real (113 ops): compras 29.996, ventas 29.996, y el
    motor deja 650 abiertos + 4 semillas + 489,72 USD de ganancia fantasma.

    Lo esencial del caso: el flujo cruzado es BIDIRECCIONAL en el tiempo —
    primero se vende de más en pesos (y hay dólares al lado), y un año después
    se vende de más en dólares (y hay pesos al lado). El neto de todo el
    historial borra la primera pata.
    """

    def test_netea_a_cero(self):
        self._import(_csv(
            "2025-05-30,COMPRA,IOL,NU,551,10,5510,,,0,USD,",
            "2025-06-01,COMPRA,IOL,NU,1000,5000,5000000,,,0,ARS,",
            "2025-06-24,VENTA,IOL,NU,1551,5200,8065200,,,0,ARS,",
            "2026-06-01,COMPRA,IOL,NU,1305,6000,7830000,,,0,ARS,",
            "2026-06-17,VENTA,IOL,NU,1305,12,15660,,,0,USD,",
        ), rebuild=True)
        self.assertEqual(self._abierto(), 0.0,
                         "compras y ventas netean a cero: no puede quedar nada abierto")

    def test_no_fabrica_lotes(self):
        self._import(_csv(
            "2025-05-30,COMPRA,IOL,NU,551,10,5510,,,0,USD,",
            "2025-06-01,COMPRA,IOL,NU,1000,5000,5000000,,,0,ARS,",
            "2025-06-24,VENTA,IOL,NU,1551,5200,8065200,,,0,ARS,",
            "2026-06-01,COMPRA,IOL,NU,1305,6000,7830000,,,0,ARS,",
            "2026-06-17,VENTA,IOL,NU,1305,12,15660,,,0,USD,",
        ), rebuild=True)
        self.assertEqual(self._semillas(), 0,
                         "había lotes reales disponibles: no hay por qué inventar uno")


class VentaCruzadaSimpleTest(_PoolBase):
    """Lo más básico del pool único: comprar en pesos, vender en dólares.

    No es MEP ni conducto: el CEDEAR cotiza en las dos monedas y el usuario
    eligió vender en dólares. Con un solo pool esto no necesita ninguna
    maquinaria especial.
    """

    def test_compra_pesos_venta_dolares_cierra(self):
        self._import(_csv(
            "2025-03-01,COMPRA,IOL,NU,100,5000,500000,,,0,ARS,",
            "2025-06-01,VENTA,IOL,NU,100,10,1000,,,0,USD,",
        ), rebuild=True)
        self.assertEqual(self._abierto(), 0.0)
        self.assertEqual(self._semillas(), 0)


# ─────────────────────────────────────────────────────────────────────────────
# GUARDS — tumbaron los tres intentos anteriores. NO se pueden romper.
# ─────────────────────────────────────────────────────────────────────────────

class GuardTenenciaGenuinaTest(_PoolBase):
    """Contraejemplo medido por el verificador (el que mató el último fix).

    La venta en dólares es el PRIMER evento del archivo: no hay lotes de ninguna
    moneda, así que la semilla ahí es correcta (history-as-truth: el usuario tenía
    esos títulos de antes del export). Después compra 100 en dólares, que son
    tenencia GENUINA y deben sobrevivir enteros.

    El fix rechazado dejaba 90: se comía 10 nominales para cubrir una venta en
    pesos que era anterior a esa compra.
    """

    def _armar(self):
        self._import(_csv(
            "2025-01-10,VENTA,IOL,NU,10,12,120,,,0,USD,",
            "2025-02-10,COMPRA,IOL,NU,100,10,1000,,,0,USD,",
            "2025-03-10,COMPRA,IOL,NU,20,5000,100000,,,0,ARS,",
            "2025-04-10,VENTA,IOL,NU,30,5200,156000,,,0,ARS,",
            "2025-05-10,COMPRA,IOL,NU,50,5500,275000,,,0,ARS,",
        ), rebuild=True)

    def test_la_pata_dolar_genuina_sobrevive_entera(self):
        self._armar()
        # Con pool único: la venta de 30 en pesos tiene 20 en pesos + 100 en
        # dólares disponibles al momento, y consume 10 de la pata dólar. Quedan
        # 90 USD + 50 ARS = 140. Antes daba 150 porque fabricaba un lote por los
        # 10 faltantes.
        #
        # Lo que SÍ se conserva: la venta del 2025-01-10 es el primer evento del
        # archivo y no hay lotes de ninguna moneda, así que ahí la semilla sigue
        # siendo correcta — ver GuardVentaSinHistorialTest.
        self.assertEqual(self._abierto(), 140.0)


class GuardDualCurrencyParcialTest(_PoolBase):
    """El guard del audit 2026-06-26, con dos filas posteriores.

    5 en pesos + 5 en dólares, vende 7 en pesos. Los 5 USD son tenencia genuina.
    El verificador mostró que el fix rechazado no preservaba el principio: lo
    POSPONÍA hasta que el usuario vendiera esa pata, lo cual además introduce
    retroactividad (una fila futura cambiando una venta pasada).
    """

    def test_no_se_toca_la_pata_dolar(self):
        self._import(_csv(
            "2025-01-05,COMPRA,IOL,NU,5,5000,25000,,,0,ARS,",
            "2025-01-06,COMPRA,IOL,NU,5,10,50,,,0,USD,",
            "2025-02-01,VENTA,IOL,NU,7,5500,38500,,,0,ARS,",
        ), rebuild=True)
        # DECISIÓN TOMADA (2026-08-04): pool único.
        #
        # Tenía 10 nominales del mismo CEDEAR —5 comprados en pesos, 5 en dólares—
        # y vendió 7. Le quedan 3. La moneda determina el COSTO de cada lote, no
        # cuántos nominales tenés.
        #
        # Esto reemplaza el criterio del audit 2026-06-26, que dejaba 5 y fabricaba
        # un lote por los 2 faltantes para no tocar la pata dólar. Ese criterio
        # protegía a quien importó un período parcial, pero es el que deja los 650
        # abiertos de Nubank y la ganancia inflada de 489 dólares.
        self.assertEqual(self._abierto(), 3.0)


class GuardConductoMepTest(_PoolBase):
    """El MEP puro tiene que seguir neteando: compra ARS + venta USD, mismo día,
    mismo nominal. Ya funciona hoy y no se puede regresionar."""

    def test_mep_mismo_dia_netea(self):
        self._import(_csv(
            "2026-03-10,COMPRA,IOL,AL30,100,1000,100000,,,0,ARS,",
            "2026-03-10,VENTA,IOL,AL30,100,0.7,70,,,0,USD,",
        ), rebuild=True)
        self.assertEqual(self._open_qty("AL30"), 0.0)


class GuardTenenciaPreviaTest(_PoolBase):
    """Lo que el usuario YA tenía antes del período importado no se toca."""

    def test_la_tenencia_vieja_sobrevive(self):
        self._import(_csv(
            "2024-01-05,COMPRA,IOL,NU,50,3000,150000,,,0,ARS,",
        ), rebuild=True)
        self._import(_csv(
            "2026-03-10,COMPRA,IOL,NU,100,5000,500000,,,0,ARS,",
            "2026-03-10,VENTA,IOL,NU,100,10,1000,,,0,USD,",
        ), rebuild=True)
        self.assertEqual(self._abierto(), 50.0)


class GuardVentaSinHistorialTest(_PoolBase):
    """History-as-truth: una venta sin ninguna compra previa SÍ debe generar el
    lote semilla. Es el caso legítimo (el usuario tenía los títulos de antes del
    export) y el cambio no puede eliminarlo."""

    def test_venta_sin_compras_genera_semilla(self):
        self._import(_csv(
            "2025-01-10,VENTA,IOL,NU,10,5000,50000,,,0,ARS,",
        ), rebuild=True)
        self.assertEqual(self._semillas(), 1,
                         "sin compras previas la semilla es correcta, no un bug")


if __name__ == "__main__":
    unittest.main()
