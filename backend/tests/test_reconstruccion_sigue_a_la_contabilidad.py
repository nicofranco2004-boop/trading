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
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from tests.test_reconstruccion_aportado_canonico import _Cuenta  # noqa: E402

# AAPL a fin de mes: 200 en marzo de 2025 y +10 por mes hasta 270 en octubre;
# de ahí en adelante, 270.
PRECIOS = {f"{y}-{m:02d}": (200.0 + 10 * min(max((y - 2025) * 12 + m - 3, 0), 7))
           for y in (2025, 2026) for m in range(1, 13)}

IBKR = (
    "2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
    "2025-03-04,COMPRA,IBKR,AAPL,20,200,4000,,,0,USD,",
    "2025-07-10,DEPOSITO,IBKR,,,,5000,,,0,USD,",
    "2025-09-15,RETIRO,IBKR,,,,1000,,,0,USD,",
)
# Lo mismo, como (fecha, efectivo que entra/sale, aportado que entra/sale).
MOV_IBKR = [("2025-03-03", 10000, 10000), ("2025-03-04", -4000, 0),
            ("2025-07-10", 5000, 5000), ("2025-09-15", -1000, -1000)]


def esperado(movs, fecha):
    """(valor, aportado) de la foto de `fecha`, escrito a mano: el efectivo que
    quedó + 20 AAPL al precio de ese mes, y lo aportado hasta ese día.

    ⚠️ Las pruebas comparan CADA foto contra esta cuenta y piden que estén los
    meses que importan, en vez de fijar la lista entera de fechas: qué meses
    reciben foto es decisión de la reconstrucción (otra rama arma también los
    meses sin movimientos), y lo que este archivo vigila es que ninguna foto
    describa una contabilidad que ya no existe."""
    efectivo = sum(c for f, c, _ in movs if f <= fecha)
    aportado = sum(a for f, _, a in movs if f <= fecha)
    return (round(efectivo + 20 * PRECIOS[fecha[:7]], 2), round(float(aportado), 2))


class _Despues(_Cuenta):

    def setUp(self):
        super().setUp()
        bf._fetch_monthly_close = lambda price_key, start_iso: dict(PRECIOS)

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

    def _cada_foto_describe(self, movs, deben_estar=()):
        """Toda foto que ve el Dashboard coincide con `esperado`, y están las de
        `deben_estar`. Devuelve {fecha: (valor, aportado)}."""
        filas = self._filas()
        self.assertTrue(filas)
        for d, v, n in filas:
            self.assertEqual((v, n), esperado(movs, d), d)
        fotos = {d: (v, n) for d, v, n in filas}
        for d in deben_estar:
            self.assertIn(d, fotos)
        return fotos

    def _reconstruccion_nueva(self):
        """{fecha: (valor, aportado)} que escribiría una reconstrucción hecha ahora,
        calculada sin escribir nada."""
        capt = {}
        conn = main.get_db()
        try:
            with mock.patch.object(bf, "_persist_mtm_snapshots",
                                   side_effect=lambda c, u, pm: capt.update(pm) or 0):
                bf.backfill_user(conn, self.uid, date.today())
        finally:
            conn.rollback()
            conn.close()
        return {i["date"]: (round(i["value"], 2), round(i["net_dep"], 2)) for i in capt.values()}

    def _libro(self, fecha):
        """El % del libro del asesor si la última foto fuera la de `fecha`."""
        conn = main.get_db()
        try:
            fila = conn.execute(
                "SELECT date, total_value, net_deposited, source, apto, base, mtm_coverage "
                "FROM snapshots WHERE user_id=? AND date=?", (self.uid, fecha)).fetchone()
            mx = main._max_net_deposited(conn, [self.uid])[self.uid]
            return round(main._retorno_vs_aportado(fila, mx), 2)
        finally:
            conn.close()


class LaHistoriaSigueALaContabilidad(_Despues):

    def test_borrar_un_deposito_despues_de_reconstruir(self):
        self._importar(*IBKR)
        antes = self._cada_foto_describe(MOV_IBKR, ("2025-03-31", "2025-07-31", "2025-09-30"))
        self.assertEqual(antes["2025-07-31"], (15800.0, 15000.0))
        self._pedir("delete", f"/api/movements/tx-{self._tx('DEPOSIT', '2025-07-10')}")
        sin = [m for m in MOV_IBKR if m[0] != "2025-07-10"]
        fotos = self._cada_foto_describe(sin, ("2025-03-31", "2025-09-30"))
        # Septiembre sin los 5.000: 5.000 de cash + 20×260 = 10.200, aportado 9.000.
        # Antes del arreglo quedaba en 15.200 (valor viejo) con aportado 9.000.
        self.assertEqual(fotos["2025-09-30"], (10200.0, 9000.0))
        # Ganó 20 AAPL de 200 a 260; antes se publicaban +5.800 y −4.600.
        self.assertEqual((10200.0 - 9000.0) - (10000.0 - 10000.0), 1200.0)
        # Libro del asesor: 1.200 sobre el mayor aportado (10.000). Antes, 62 %.
        self.assertEqual(self._libro("2025-09-30"), 12.0)

    def test_la_foto_de_un_mes_que_ya_no_se_reconstruye_se_borra(self):
        # Borrar el primer depósito deja la contabilidad empezando en julio: la foto
        # de marzo ya no la produce nadie. Antes se quedaba para siempre con el
        # depósito borrado adentro.
        self._importar(*IBKR)
        self.assertIn("2025-03-31", [f[0] for f in self._filas()])
        self._pedir("delete", f"/api/movements/tx-{self._tx('DEPOSIT', '2025-03-03')}")
        fotos = {d: (v, n) for d, v, n in self._filas()}
        self.assertTrue(fotos)
        self.assertTrue(all(d >= "2025-07-01" for d in fotos), sorted(fotos))
        # Las que quedan son exactamente lo que arma una reconstrucción nueva. (No
        # se escriben a mano: al borrar el primer depósito la contabilidad deja los
        # 10.000 como capital inicial de julio — comportamiento del motor de
        # contabilidad, aparte de lo que se vigila acá.)
        self.assertEqual(fotos, self._reconstruccion_nueva())
        conn = main.get_db()
        try:
            self.assertIsNone(conn.execute(
                "SELECT 1 FROM snapshots WHERE user_id=? AND date='2025-03-31'",
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
        self._cada_foto_describe(MOV_IBKR, ("2025-03-31", "2025-07-31", "2025-09-30"))
        # Libro: 1.200 de ganancia sobre el mayor aportado de IBKR (15.000).
        self.assertEqual(self._libro("2025-09-30"), 8.0)

    def test_un_deposito_cargado_a_mano_con_fecha_pasada(self):
        self._importar(*IBKR)
        self._pedir("post", "/api/cash/flow", json={
            "broker_name": "IBKR", "direction": "deposit", "amount": 2000, "date": "2025-06-10"})
        # Junio aparece (8.000 de cash + 20×230 = 12.600, aportado 12.000) y los
        # meses siguientes llevan los 2.000 en el valor Y en lo aportado.
        fotos = self._cada_foto_describe(
            MOV_IBKR + [("2025-06-10", 2000, 2000)],
            ("2025-03-31", "2025-06-30", "2025-07-31", "2025-09-30"))
        self.assertEqual(fotos["2025-06-30"], (12600.0, 12000.0))

    def test_una_operacion_cerrada_cargada_a_mano_en_el_pasado(self):
        self._importar(*IBKR)
        self._pedir("post", "/api/operations", json={
            "date": "2025-06-15", "broker": "IBKR", "asset": "TSLA", "op_type": "LONG",
            "entry_price": 100, "exit_price": 130, "quantity": 10, "pnl_usd": 300,
            "currency": "USD"})
        # Los 300 de ganancia realizada entran al valor desde junio; lo aportado no.
        fotos = self._cada_foto_describe(
            MOV_IBKR + [("2025-06-15", 300, 0)],
            ("2025-03-31", "2025-06-30", "2025-07-31", "2025-09-30"))
        self.assertEqual(fotos["2025-06-30"], (10900.0, 10000.0))


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
    """Qué cuentas se reconstruyen al terminar un pedido: las que cambiaron. Pocas,
    cada una en su hilo; muchas (revertir una tanda del asesor, herramientas del
    admin), por una sola fila, de a una — decenas de hilos contra Yahoo no."""

    def _correr(self, uids, cambian=True):
        import asyncio
        vistas = {}

        def huella(uid):                    # 1ra vez: antes; 2da: al terminar
            vistas[uid] = vistas.get(uid, 0) + 1
            return f"{uid}-{vistas[uid] if cambian else 1}"

        async def app(scope, receive, send):
            for u in uids:
                main._contabilidad_tocada(u)
        mw = main._ReconstruirAlTerminar(app)
        with mock.patch.object(main, "_huella_reconstruccion", side_effect=huella), \
             mock.patch.dict(main._MTM_HUELLA_ESCRITA, {}, clear=True), \
             mock.patch.object(main, "_reconstruir_mtm_post_import") as solas, \
             mock.patch.object(main, "_reconstruir_en_fila") as fila:
            asyncio.run(mw({"type": "http", "method": "POST"}, None, None))
        return (sorted(c.args[0] for c in solas.call_args_list),
                [list(c.args[0]) for c in fila.call_args_list])

    def test_pocas_cuentas_cada_una_en_su_hilo(self):
        self.assertEqual(self._correr([7, 3, 7]), ([3, 7], []))

    def test_muchas_cuentas_van_a_la_fila(self):
        n = main._RECONSTRUIR_MAX_CUENTAS + 2
        self.assertEqual(self._correr(range(n, 0, -1)), ([], [list(range(1, n + 1))]))

    def test_si_no_cambio_nada_no_se_reconstruye(self):
        self.assertEqual(self._correr([3, 7], cambian=False), ([], []))

    def test_fuera_de_un_pedido_anotar_no_hace_nada(self):
        main._contabilidad_tocada(42)          # cron, hilos, scripts: no revienta
        self.assertIsNone(main._CONTABILIDAD_TOCADA.get())


class SoloCuandoCambia(_Despues):

    def _contar_disparos(self, accion):
        disparos = []
        real = main._reconstruir_mtm_post_import

        def contar(uid):
            disparos.append(uid)
            return real(uid)
        with mock.patch.object(main, "_reconstruir_mtm_post_import", side_effect=contar):
            accion()
        self._esperar()
        return disparos

    def test_el_refresco_del_dashboard_no_reconstruye(self):
        # El Dashboard manda esto cada 90 s y pasa por `_repair_monthly_chain`.
        # Medido en la primera versión: 3 refrescos → 6 reconstrucciones enteras.
        self._importar(*IBKR)
        disparos = self._contar_disparos(lambda: [
            self._pedir("post", "/api/monthly/sync-unrealized",
                        json={"broker": b, "pnl_unrealized_usd": 123.0})
            for b in ("IBKR", "global", "IBKR")])
        self.assertEqual(disparos, [])

    def test_editar_el_promedio_desde_cartera(self):
        # No pasa por el motor de contabilidad: la primera versión no lo veía.
        self._importar(*IBKR)
        antes = {d: (v, n) for d, v, n in self._filas()}
        disparos = self._contar_disparos(lambda: self._pedir(
            "patch", "/api/positions/group",
            json={"broker": "IBKR", "asset": "AAPL", "avg_price": 150}))
        self.assertEqual(disparos, [self.uid])
        despues = {d: (v, n) for d, v, n in self._filas()}
        self.assertNotEqual(despues, antes)
        self.assertEqual(despues, self._reconstruccion_nueva())


class LasHerramientasDelAdmin(_Despues):

    def _foto(self, fecha):
        conn = main.get_db()
        try:
            r = conn.execute("SELECT total_value FROM snapshots WHERE user_id=? AND date=?",
                             (self.uid, fecha)).fetchone()
            return None if r is None else r[0]
        finally:
            conn.close()

    def test_el_ensayo_no_escribe_en_la_base_real(self):
        """Los "Simular" del admin corren el motor sobre un CLON. La primera versión
        anotaba igual las cuentas y al terminar las reconstruía en la base REAL
        (medido por la auditoría: una foto borrada a mano volvía a aparecer)."""
        self._importar(*IBKR)
        conn = main.get_db()
        admin = conn.execute(
            "INSERT INTO users (email, password_hash, approved, is_admin) VALUES (?,?,1,1)",
            (f"admin-{self.uid}@rendi.test", "x")).lastrowid
        conn.execute("DELETE FROM snapshots WHERE user_id=? AND date='2025-07-31'", (self.uid,))
        conn.commit()
        conn.close()
        h = {"Authorization": f"Bearer {main.create_token(admin)}"}
        disparos = []
        real = main._reconstruir_mtm_post_import
        with mock.patch.object(main, "_reconstruir_mtm_post_import",
                               side_effect=lambda u: disparos.append(u) or real(u)):
            for url in ("/api/admin/backfill-recompute",
                        "/api/admin/backfill-recompute?safe_only=false",
                        "/api/admin/repair-snapshots-all"):
                r = self.http.post(url, headers=h)
                self.assertEqual(r.status_code, 200, (url, r.text))
        self._esperar()
        self.assertEqual(disparos, [])
        self.assertIsNone(self._foto("2025-07-31"))

    def test_el_ensayo_de_reconstruccion_cuenta_las_fotos_que_borraria(self):
        self._importar(*IBKR)
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
                "net_deposited, source) VALUES (?, '2025-02-28', 1.0, 1.0, 1.0, 'mtm_backfill')",
                (self.uid,))
            conn.commit()
            r = bf.backfill_summary(conn, [self.uid], date.today(), apply=False)
        finally:
            conn.close()
        # Febrero es anterior a toda la contabilidad (empieza en marzo).
        self.assertEqual(r["fotos_borradas"], 1)
        self.assertEqual(self._foto("2025-02-28"), 1.0)  # y el ensayo no la tocó


class _YahooDeMentira:
    """`yfinance.Ticker` reemplazado: así se usa el `_fetch_monthly_close` de
    verdad (con su memoria de precios). Caído, tira lo mismo que yfinance 1.2.0
    sin red (medido: TypeError); un ticker que no existe da vacío, sin error."""
    caido = False
    consultas = 0

    def __init__(self, sym):
        self.sym = sym

    def history(self, start, interval, auto_adjust, timeout):
        import pandas as pd
        _YahooDeMentira.consultas += 1
        if _YahooDeMentira.caido:
            raise TypeError("'NoneType' object is not subscriptable")
        if self.sym != "AAPL":
            return pd.DataFrame()
        return pd.DataFrame({"Close": list(PRECIOS.values())},
                            index=pd.to_datetime([f"{ym}-01" for ym in PRECIOS]))


class ConYahooCaido(_Despues):

    def setUp(self):
        super().setUp()
        bf._fetch_monthly_close = self._fetch_orig          # el de verdad
        _YahooDeMentira.caido = False
        _YahooDeMentira.consultas = 0
        p = mock.patch("yfinance.Ticker", _YahooDeMentira)
        p.start()
        self.addCleanup(p.stop)

    def test_una_caida_se_corrige_en_el_pedido_siguiente(self):
        self._importar(*IBKR)
        self.assertEqual(dict((d, (v, n)) for d, v, n in self._filas())["2025-09-30"],
                         (15200.0, 14000.0))
        # Reinicio del servidor (memoria de precios vacía) con Yahoo caído, y la
        # persona borra el depósito de julio.
        bf._HIST_CACHE.clear()
        _YahooDeMentira.caido = True
        self._pedir("delete", f"/api/movements/tx-{self._tx('DEPOSIT', '2025-07-10')}")
        # Se escribe la contabilidad nueva; AAPL, sin precio, al costo y declarado
        # (5.000 de cash + 4.000 de costo). Nunca la foto vieja con los 5.000 borrados.
        sep = {f["date"]: f for f in self._fotos()}["2025-09-30"]
        self.assertEqual((sep["total_value"], sep["net_deposited"]), (9000.0, 9000.0))
        self.assertEqual(main._MTM_HUELLA_ESCRITA.get(self.uid), main._MTM_FALLIDA)
        # La falla no quedó guardada como "sin datos": vuelve Yahoo y el próximo
        # pedido —uno que no cambia nada, como el refresco del Dashboard— la rehace.
        self.assertNotIn(("AAPL", "2025-03-01"), bf._HIST_CACHE)
        _YahooDeMentira.caido = False
        self._pedir("post", "/api/monthly/sync-unrealized",
                    json={"broker": "IBKR", "pnl_unrealized_usd": 0.0})
        sep = {f["date"]: f for f in self._fotos()}["2025-09-30"]
        self.assertEqual((sep["total_value"], sep["net_deposited"]), (10200.0, 9000.0))
        self.assertNotEqual(main._MTM_HUELLA_ESCRITA.get(self.uid), main._MTM_FALLIDA)

    def test_los_precios_guardados_se_vuelven_a_pedir_al_cambiar_el_mes(self):
        ck = ("AAPL", "2025-03-01")
        bf._HIST_CACHE[ck] = {"2025-03": 1.0}
        bf._HIST_CACHE_MES[ck] = "2025-03"          # pedidos hace meses
        self.addCleanup(bf._HIST_CACHE_MES.pop, ck, None)
        self.assertEqual(bf._fetch_monthly_close(*ck)["2025-09"], PRECIOS["2025-09"])
        self.assertEqual(_YahooDeMentira.consultas, 1)
        bf._fetch_monthly_close(*ck)                 # ahora sí, de la memoria
        self.assertEqual(_YahooDeMentira.consultas, 1)


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
            self.assertIn(("2025-09-30", 15200.0, 9000.0), c._filas())   # vieja
        main._reconstruir_en_fila([self.uid, otra.uid])
        limite = time.time() + 60
        while time.time() < limite:
            with main._MTM_RUNNING_LOCK:
                if not main._MTM_FILA_ACTIVA and not main._MTM_RUNNING:
                    break
            time.sleep(0.02)
        else:
            self.fail("la fila no se vació en 60 s")
        sin = [m for m in MOV_IBKR if m[0] != "2025-07-10"]
        for c in cuentas:
            fotos = c._cada_foto_describe(sin, ("2025-03-31", "2025-09-30"))
            self.assertEqual(fotos["2025-09-30"], (10200.0, 9000.0))


if __name__ == "__main__":
    unittest.main()
