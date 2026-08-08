"""El precio cargado a mano, ¿sobrevive a un import posterior?

QUÉ SE PROMETE
──────────────
El campo "Precio actual" del formulario de posición (deployado 2026-08-06) le
dice al usuario: "Completalo sólo si es un activo que no seguimos, para que la
cartera muestre su valor real" y "Podés actualizarlo cuando quieras desde la
posición".

POR QUÉ PUEDE NO CUMPLIRSE
──────────────────────────
`rebuild._write_rebuilt` reconstruye las posiciones desde cero y escribe
`price_override = None` (rebuild.py:706, el INSERT). El rebuild corre después de
CADA import. Sólo respeta un (broker, activo) cuando `_is_safe_to_rebuild`
devuelve False, o sea cuando hay alguna posición o venta MANUAL sin vincular.

Entonces hay dos situaciones bien distintas:
  · posición cargada a mano  → el par tiene filas manuales → se saltea → el
    precio sobrevive;
  · posición IMPORTADA a la que el usuario le puso precio a mano → todas sus
    filas están vinculadas → el rebuild la reescribe → el precio SE BORRA.

La segunda es justo el caso que motivó el feature: un activo que vino de un
import y que la app no cotiza (como le pasó a un usuario con SID). Le ponés el
precio, importás el mes siguiente, y lo perdés sin ningún aviso.

ARREGLADO (2026-08-06). `_capturar_precio_manual` / `_restaurar_precio_manual` en
rebuild.py guardan el override antes del DELETE y lo reponen después del INSERT.
Medido antes del fix, con los tres escenarios de abajo:
  · sólo compras            → sobrevivía (el rebuild no reconstruye, sólo agrega)
  · el activo tiene 1 venta → SE BORRABA
  · el import trae 1 venta  → SE BORRABA
O sea alcanzaba con que el activo tuviera UNA venta para perder el precio en el
siguiente import. Estos tests fijan los tres casos.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from test_rebuild_fifo import _Base, _csv  # noqa: E402


class _OverrideBase(_Base):
    BROKER = "IOL"
    BROKER_CCY = "ARS"

    def setUp(self):
        super().setUp()
        self._set_tc_blue(1000.0)

    def _poner_precio(self, asset, precio):
        """Lo que hace el form al guardar: setea price_override en los lotes."""
        self.conn.execute(
            "UPDATE positions SET price_override=? WHERE user_id=? AND asset=? AND is_cash=0",
            (precio, self.uid, asset))
        self.conn.commit()

    def _precio(self, asset):
        r = self.conn.execute(
            "SELECT price_override FROM positions WHERE user_id=? AND asset=? AND is_cash=0 "
            "ORDER BY id LIMIT 1", (self.uid, asset)).fetchone()
        return None if not r else r["price_override"]


class PosicionImportadaTest(_OverrideBase):
    """El caso que motivó el feature: activo que vino de un import y no cotiza."""

    def test_el_precio_a_mano_sobrevive_al_siguiente_import(self):
        # 1. El usuario importa su historial.
        self._import(_csv(
            "2025-01-10,COMPRA,IOL,XXNOCOTIZA,100,5000,500000,,,0,ARS,",
        ), rebuild=True)

        # 2. Ve que el activo no tiene precio y se lo carga a mano.
        self._poner_precio("XXNOCOTIZA", 7500.0)
        self.assertEqual(self._precio("XXNOCOTIZA"), 7500.0, "precondición: quedó guardado")

        # 3. Al mes siguiente importa el resumen nuevo, que incluye una compra más
        #    del mismo activo.
        self._import(_csv(
            "2025-02-10,COMPRA,IOL,XXNOCOTIZA,50,5200,260000,,,0,ARS,",
        ), rebuild=True)

        self.assertEqual(
            self._precio("XXNOCOTIZA"), 7500.0,
            "el import le borró el precio que había cargado a mano — la cartera "
            "vuelve a mostrar el activo valuado a su costo, sin avisar nada")


class ConVentasTest(_OverrideBase):
    """Los dos escenarios que SÍ se rompían: alcanza con que el activo tenga una
    venta para que el rebuild lo reconstruya entero."""

    def test_venta_previa_en_el_historial(self):
        self._import(_csv(
            "2025-01-10,COMPRA,IOL,ZZ,100,5000,500000,,,0,ARS,",
            "2025-01-20,VENTA,IOL,ZZ,30,5500,165000,,,0,ARS,",
        ), rebuild=True)
        self._poner_precio("ZZ", 7500.0)
        self._import(_csv(
            "2025-02-10,COMPRA,IOL,ZZ,50,5200,260000,,,0,ARS,",
        ), rebuild=True)
        self.assertEqual(self._precio("ZZ"), 7500.0,
                         "con una venta en el historial el rebuild reconstruye todo — "
                         "el precio a mano tiene que reponerse")

    def test_el_import_nuevo_trae_la_venta(self):
        self._import(_csv(
            "2025-01-10,COMPRA,IOL,ZZ,100,5000,500000,,,0,ARS,",
        ), rebuild=True)
        self._poner_precio("ZZ", 7500.0)
        self._import(_csv(
            "2025-02-10,VENTA,IOL,ZZ,30,5500,165000,,,0,ARS,",
        ), rebuild=True)
        self.assertEqual(self._precio("ZZ"), 7500.0)


class PosicionManualTest(_OverrideBase):
    """Contraste: si la posición se cargó a mano, el rebuild la saltea entera y el
    precio sí sobrevive. Esto YA funciona — el test lo fija para que se note si
    alguna vez deja de andar."""

    def test_una_posicion_cargada_a_mano_conserva_su_precio(self):
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity, "
            "invested, price_override, currency, asset_type) "
            "VALUES (?,?,?,0,?,?,?,?,?,?)",
            (self.uid, "IOL", "YYMANUAL", 5000.0, 100.0, 500000.0, 7500.0, "ARS", "BOND"))
        self.conn.commit()

        # Importa OTRO activo del mismo broker (dispara el rebuild igual).
        self._import(_csv(
            "2025-02-10,COMPRA,IOL,OTROACT,50,5200,260000,,,0,ARS,",
        ), rebuild=True)

        self.assertEqual(self._precio("YYMANUAL"), 7500.0,
                         "una posición manual no la toca el rebuild")


if __name__ == "__main__":
    unittest.main()
