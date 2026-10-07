"""La historia reconstruida a mercado sigue a la contabilidad DESPUÉS del import.

Las fotos de fin de mes que arma la reconstrucción (`source='mtm_backfill'`)
llevan el valor de la cartera y lo aportado. Sólo se armaban al confirmar un
import: lo que la persona cambiaba después las dejaba describiendo una
contabilidad que ya no existía. Medido con esta misma cuenta de laboratorio
(antes del arreglo):

  · borrar el depósito de julio → la cascada bajaba el aportado de las fotos y
    dejaba el valor con los US$ 5.000 adentro: Dashboard +US$ 5.800 de marzo a
    julio (real +800) y libro del asesor +62 % (real +12 %);
  · revertir el segundo import (o borrar ese broker) → las fotos desde la primera
    fecha del lote se borraban y nadie las volvía a armar: curva y libro vacíos
    hasta el próximo import;
  · cargar a mano un depósito con fecha pasada → la foto no lo veía y la curva
    del servidor (que ancla lo aportado a la contabilidad de hoy) daba −5,6 %
    donde lo real era +13 %.

Todo entra por las puertas reales: `POST /api/imports/preview` + `/confirm`,
`DELETE /api/movements/…`, `POST /api/imports/{lote}/revert`, `POST /api/cash/flow`.
La reconstrucción corre en su hilo, como en producción. Sólo se reemplaza lo que
sale a internet (Yahoo y data912), así el resultado correcto de cada mes se
puede escribir a mano.

⚠️ La reconstrucción se pide cuando el pedido TERMINÓ, no adentro de la
transacción: con los precios ya en memoria tarda una décima de segundo y,
lanzada antes del commit, leería la contabilidad vieja y la volvería a escribir.
Los resultados de arriba NO alcanzan para vigilar eso: probado moviendo el
disparo adentro, siguen en verde porque el motor de contabilidad anota varias
veces por pedido y la segunda vuelta (`_MTM_PENDIENTE`) llega con todo
commiteado. Es suerte de este caso, no garantía. Por eso
`ElDisparoLlegaConTodoGuardado` mira directamente si, en el momento del pedido
de reconstrucción, el cambio ya se ve desde otra conexión.
"""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from tests.test_reconstruccion_aportado_canonico import _Cuenta  # noqa: E402

# AAPL a fin de mes: marzo 200, mayo 220, junio 230, julio 240, septiembre 260.
IBKR = (
    "2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
    "2025-03-04,COMPRA,IBKR,AAPL,20,200,4000,,,0,USD,",
    "2025-07-10,DEPOSITO,IBKR,,,,5000,,,0,USD,",
    "2025-09-15,RETIRO,IBKR,,,,1000,,,0,USD,",
)
# Lo que la reconstrucción arma para IBKR sola: (fecha, valor, aportado).
#   marzo:      6.000 + 20×200 = 10.000   aportado 10.000
#   julio:     11.000 + 20×240 = 15.800   aportado 15.000
#   septiembre: 10.000 + 20×260 = 15.200  aportado 14.000
SOLO_IBKR = [("2025-03-31", 10000.0, 10000.0), ("2025-07-31", 15800.0, 15000.0),
             ("2025-09-30", 15200.0, 14000.0)]


class _Despues(_Cuenta):

    def _esperar(self):
        limite = time.time() + 60
        while time.time() < limite:
            with main._MTM_RUNNING_LOCK:
                if self.uid not in main._MTM_RUNNING:
                    return
            time.sleep(0.02)
        self.fail("la reconstrucción no terminó en 60 s")

    def _pedir(self, metodo, url, **kw):
        r = getattr(self.http, metodo)(url, headers=self.h, **kw)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar()
        return r

    def _filas(self):
        return [(f["date"], f["total_value"], f["net_deposited"]) for f in self._fotos()]

    def _libro(self):
        conn = main.get_db()
        try:
            ultima = main._latest_snapshots(conn, [self.uid])[self.uid]
            mx = main._max_net_deposited(conn, [self.uid])[self.uid]
            return round(main._retorno_vs_aportado(ultima, mx), 2)
        finally:
            conn.close()


class LaHistoriaSigueALaContabilidad(_Despues):

    def test_borrar_un_deposito_despues_de_reconstruir(self):
        self._importar(*IBKR)
        self.assertEqual(self._filas(), SOLO_IBKR)
        self._pedir("delete", f"/api/movements/tx-{self._tx('DEPOSIT', '2025-07-10')}")
        # Septiembre sin los 5.000: 5.000 de cash + 20×260 = 10.200, aportado 9.000.
        # Julio se queda sin movimientos y su foto (que valía 15.800 con el depósito
        # adentro) se va, como cualquier mes que la contabilidad saltea.
        self.assertEqual(self._filas(), [("2025-03-31", 10000.0, 10000.0),
                                         ("2025-09-30", 10200.0, 9000.0)])
        # Lo que ganó: 20 AAPL de 200 a 260. Antes del arreglo, +5.800 y −4.600.
        self.assertEqual([r[2] for r in self._resultados(self._fotos())], [1200.0])
        # Libro del asesor: 1.200 sobre el mayor aportado (10.000). Antes, 62 %.
        self.assertEqual(self._libro(), 12.0)

    def test_borrar_el_unico_movimiento_de_un_mes_borra_su_foto(self):
        self._importar(*IBKR)
        self._pedir("delete", f"/api/movements/tx-{self._tx('WITHDRAW', '2025-09-15')}")
        # Sin el retiro, septiembre no tiene movimientos: su foto se va. Antes
        # quedaba con valor 15.200 (sin los 1.000) y aportado 15.000 (con ellos).
        self.assertEqual(self._filas(), SOLO_IBKR[:2])
        conn = main.get_db()
        try:
            self.assertIsNone(conn.execute(
                "SELECT 1 FROM snapshots WHERE user_id=? AND date='2025-09-30'",
                (self.uid,)).fetchone())
        finally:
            conn.close()

    def test_revertir_el_segundo_import_devuelve_la_historia_del_primero(self):
        conn = main.get_db()
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "Schwab", "USDT"))
        conn.commit()
        conn.close()
        self._importar(*IBKR)
        self._importar("2025-05-05,DEPOSITO,Schwab,,,,3000,,,0,USD,",
                       "2025-05-06,COMPRA,Schwab,AAPL,10,220,2200,,,0,USD,")
        self.assertIn("2025-05-31", [f[0] for f in self._filas()])
        conn = main.get_db()
        try:
            lote = conn.execute(
                "SELECT id FROM import_batches WHERE user_id=? AND status='confirmed' "
                "ORDER BY rowid DESC LIMIT 1", (self.uid,)).fetchone()["id"]
        finally:
            conn.close()
        self._pedir("post", f"/api/imports/{lote}/revert")
        # El revert borra a propósito las fotos desde la primera fecha del lote
        # (mayo). Antes ahí terminaba: quedaba sólo marzo. Ahora vuelve la de IBKR.
        self.assertEqual(self._filas(), SOLO_IBKR)
        # Libro: 1.200 de ganancia sobre el mayor aportado de IBKR (15.000).
        self.assertEqual(self._libro(), 8.0)

    def test_un_deposito_cargado_a_mano_con_fecha_pasada(self):
        self._importar(*IBKR)
        self._pedir("post", "/api/cash/flow", json={
            "broker_name": "IBKR", "direction": "deposit", "amount": 2000, "date": "2025-06-10"})
        # Junio aparece (8.000 de cash + 20×230) y los meses siguientes llevan los
        # 2.000 en el valor Y en lo aportado.
        self.assertEqual(self._filas(), [
            ("2025-03-31", 10000.0, 10000.0), ("2025-06-30", 12600.0, 12000.0),
            ("2025-07-31", 17800.0, 17000.0), ("2025-09-30", 17200.0, 16000.0)])
        self.assertEqual([r[2] for r in self._resultados(self._fotos())],
                         [600.0, 200.0, 400.0])

    def test_una_operacion_cerrada_cargada_a_mano_en_el_pasado(self):
        self._importar(*IBKR)
        self._pedir("post", "/api/operations", json={
            "date": "2025-06-15", "broker": "IBKR", "asset": "TSLA", "op_type": "LONG",
            "entry_price": 100, "exit_price": 130, "quantity": 10, "pnl_usd": 300,
            "currency": "USD"})
        # Los 300 de ganancia realizada entran desde junio.
        filas = self._filas()
        self.assertEqual([(d, v) for d, v, _ in filas],
                         [("2025-03-31", 10000.0), ("2025-06-30", 10900.0),
                          ("2025-07-31", 16100.0), ("2025-09-30", 15500.0)])
        self.assertEqual([n for _, _, n in filas], [10000.0, 10000.0, 15000.0, 14000.0])


class ElDisparoLlegaConTodoGuardado(_Despues):

    def _visto_desde_otra_conexion_al_disparar(self, sql, accion):
        """Corre `accion` y devuelve lo que `sql` leía desde OTRA conexión en el
        instante en que se pidió cada reconstrucción."""
        vistos = []
        real = main._reconstruir_mtm_post_import

        def mirar(uid):
            conn = main.get_db()
            try:
                vistos.append(conn.execute(sql, (self.uid,)).fetchone()[0])
            finally:
                conn.close()
            return real(uid)
        with mock.patch.object(main, "_reconstruir_mtm_post_import", side_effect=mirar):
            accion()
        self._esperar()
        return vistos

    def test_borrar_un_deposito(self):
        self._importar(*IBKR)
        tx = self._tx("DEPOSIT", "2025-07-10")
        vistos = self._visto_desde_otra_conexion_al_disparar(
            f"SELECT COUNT(*) FROM import_normalized_tx WHERE excluded_at IS NOT NULL "
            f"AND id={int(tx)} AND ?>0",
            lambda: self._pedir("delete", f"/api/movements/tx-{tx}"))
        self.assertEqual(vistos, [1])          # un solo pedido, y ya con el borrado adentro

    def test_cargar_un_deposito_a_mano(self):
        self._importar(*IBKR)
        vistos = self._visto_desde_otra_conexion_al_disparar(
            "SELECT COALESCE(SUM(deposits),0) FROM monthly_entries "
            "WHERE user_id=? AND broker='global' AND year=2025 AND month=6",
            lambda: self._pedir("post", "/api/cash/flow", json={
                "broker_name": "IBKR", "direction": "deposit", "amount": 2000,
                "date": "2025-06-10"}))
        self.assertEqual(vistos, [2000.0])


class CuandoNoSeReconstruye(_Despues):

    def test_leer_no_dispara_nada(self):
        self._importar(*IBKR)
        with mock.patch.object(main, "_reconstruir_mtm_post_import") as disparo:
            for url in ("/api/snapshots", "/api/movements", "/api/monthly"):
                self.http.get(url, headers=self.h)
        disparo.assert_not_called()

    def test_una_cuenta_sin_import_no_recibe_fotos_reconstruidas(self):
        # Cuenta cargada a mano: no hay nada que reconstruir. El pedido anda igual.
        self._pedir("post", "/api/cash/flow", json={
            "broker_name": "IBKR", "direction": "deposit", "amount": 1000, "date": "2025-06-10"})
        conn = main.get_db()
        try:
            self.assertIsNone(conn.execute(
                "SELECT 1 FROM snapshots WHERE user_id=? AND source='mtm_backfill'",
                (self.uid,)).fetchone())
        finally:
            conn.close()

    def test_el_import_pide_una_sola_reconstruccion(self):
        # El confirm ya la pide él mismo, con todo commiteado: el middleware no
        # tiene que pedir otra al terminar el mismo pedido.
        llamadas = []
        real = main._reconstruir_mtm_post_import

        def contar(uid):
            llamadas.append(uid)
            return real(uid)
        with mock.patch.object(main, "_reconstruir_mtm_post_import", side_effect=contar):
            self._importar(*IBKR)
        self.assertEqual(llamadas, [self.uid])


class ElMiddleware(unittest.TestCase):
    """Cuántas cuentas toca un pedido decide cómo se reconstruyen: pocas, cada una
    en su hilo; muchas (revertir una tanda del asesor, herramientas del admin), por
    una sola fila, de a una — decenas de hilos contra Yahoo a la vez no."""

    def _correr(self, uids):
        import asyncio

        async def app(scope, receive, send):
            for u in uids:
                main._contabilidad_tocada(u)
        mw = main._ReconstruirAlTerminar(app)
        with mock.patch.object(main, "_reconstruir_mtm_post_import") as solas, \
             mock.patch.object(main, "_reconstruir_en_fila") as fila:
            asyncio.run(mw({"type": "http", "method": "POST"}, None, None))
        return (sorted(c.args[0] for c in solas.call_args_list),
                [list(c.args[0]) for c in fila.call_args_list])

    def test_pocas_cuentas_cada_una_en_su_hilo(self):
        self.assertEqual(self._correr([7, 3, 7]), ([3, 7], []))

    def test_muchas_cuentas_van_a_la_fila(self):
        n = main._RECONSTRUIR_MAX_CUENTAS + 2
        self.assertEqual(self._correr(range(n, 0, -1)), ([], [list(range(1, n + 1))]))

    def test_fuera_de_un_pedido_anotar_no_hace_nada(self):
        main._contabilidad_tocada(42)          # cron, hilos, scripts: no revienta
        self.assertIsNone(main._CONTABILIDAD_TOCADA.get())


class LaFila(_Despues):
    """La fila de verdad, con dos cuentas cuya contabilidad cambió sin pasar por
    un pedido (como queda cada cliente después del revert de una tanda)."""

    def test_reconstruye_todas_de_a_una(self):
        otra = LaFila("test_reconstruye_todas_de_a_una")
        otra.setUp()
        # La segunda cuenta guardó como "Yahoo de verdad" al Yahoo de mentira de
        # la primera: que las dos devuelvan el de verdad, y que se cierren sus
        # reemplazos (data912) aunque el runner no la corra.
        otra._fetch_orig = self._fetch_orig
        self.addCleanup(otra.doCleanups)
        self.addCleanup(otra.tearDown)
        cuentas = (self, otra)
        for c in cuentas:
            c._importar(*IBKR)
        # Fuera de un pedido HTTP nada se anota: las fotos quedan viejas.
        for c in cuentas:
            conn = main.get_db()
            try:
                with conn:
                    since, brokers = main._delete_one_movement(
                        conn, c.uid, f"tx-{c._tx('DEPOSIT', '2025-07-10')}")
                    main._cascade_after_movement_delete(conn, c.uid, since, brokers)
            finally:
                conn.close()
            self.assertIn(("2025-07-31", 15800.0, 10000.0), c._filas())
        main._reconstruir_en_fila([self.uid, otra.uid])
        limite = time.time() + 60
        while time.time() < limite:
            with main._MTM_RUNNING_LOCK:
                if not main._MTM_FILA_ACTIVA and not main._MTM_RUNNING:
                    break
            time.sleep(0.02)
        else:
            self.fail("la fila no se vació en 60 s")
        for c in cuentas:
            self.assertEqual(c._filas(), [("2025-03-31", 10000.0, 10000.0),
                                          ("2025-09-30", 10200.0, 9000.0)])


if __name__ == "__main__":
    unittest.main()
