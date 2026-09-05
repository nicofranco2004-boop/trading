"""Reportes por broker: el par padre ↔ "<Padre> · USD" es UNA cuenta.

Un broker argentino bimonetario tiene DOS filas en `brokers`: el padre y el
sub-broker "<Padre> · USD" (U+00B7) que crea `_ensure_usd_sibling`. Como
`positions`/`operations`/`monthly_entries` referencian al broker por NOMBRE,
un filtro `AND broker = ?` con el nombre del padre deja AFUERA todo lo que
vive en el sibling: capital aportado, P&L realizado, posiciones y
concentración salen sistemáticamente por debajo y sin ningún error visible.

Estos tests pinnean que los LECTORES de reportes miran el PAR (vía
`importing.persister.broker_pair`) y que la agregación se hace COLAPSANDO por
mes — no con un `IN` pelado, que rompe distinto en cada motor:

  · un `LIMIT 1`/`rows[0]`/`fetchone()` sobre dos filas del mismo mes elige una
    fila ARBITRARIA (el capital queda partido al medio);
  · `_meses_con_fila` pasa a [1,1,2,2,…] y `_hay_agujero` da True SIEMPRE, con
    lo cual la composición geométrica del año se APAGA en silencio;
  · un `SELECT SUM(...)` sin GROUP BY devuelve UNA fila de NULLs aunque no
    matchee nada — y ese `None` es carga útil (dispara el fallback AUDIT C-3).
"""
import os
import sys
import unittest
import uuid
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402
from reporting import builder, timeline  # noqa: E402
from importing.persister import broker_pair  # noqa: E402

PADRE = "IOL"
SIB = "IOL · USD"          # U+00B7, igual que _ensure_usd_sibling


def _mk_par(conn) -> int:
    """User con el par IOL / IOL · USD (linkeado por parent_broker_id)."""
    email = f"par-{uuid.uuid4().hex[:12]}@rendi.test"
    uid = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
        (email,),
    ).lastrowid
    pid = conn.execute(
        "INSERT INTO brokers (user_id, name, currency) VALUES (?, ?, 'ARS')",
        (uid, PADRE),
    ).lastrowid
    conn.execute(
        "INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
        "VALUES (?, ?, 'USDT', ?)",
        (uid, SIB, pid),
    )
    return uid


def _me(conn, uid, broker, y, m, *, ci, cf, dep=0.0, wit=0.0, pnl=0.0, unre=0.0):
    conn.execute(
        """INSERT INTO monthly_entries
           (user_id, year, month, broker, deposits, withdrawals, pnl_realized,
            pnl_unrealized, capital_inicio, capital_final)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (uid, y, m, broker, dep, wit, pnl, unre, ci, cf),
    )


def _op(conn, uid, broker, d, asset, pnl, op_type="Venta"):
    conn.execute(
        """INSERT INTO operations
           (user_id, date, broker, asset, op_type, quantity, entry_price,
            exit_price, pnl_usd, pnl_pct)
           VALUES (?,?,?,?,?,1,10,20,?,10)""",
        (uid, d, broker, asset, op_type, pnl),
    )


def _pos(conn, uid, broker, asset, qty, invested, is_cash=0):
    conn.execute(
        """INSERT INTO positions
           (user_id, broker, asset, is_cash, buy_price, quantity, invested)
           VALUES (?,?,?,?,?,?,?)""",
        (uid, broker, asset, is_cash, 1.0, qty, invested),
    )


class BrokerPairFixtureTest(unittest.TestCase):
    """Sanidad del fixture: el par se resuelve por FK, no por el sufijo."""

    def test_broker_pair_resuelve_las_dos_puntas(self):
        conn = main.get_db()
        uid = _mk_par(conn)
        conn.commit()
        self.assertEqual(broker_pair(conn, uid, PADRE), [PADRE, SIB])
        self.assertEqual(broker_pair(conn, uid, SIB), [PADRE, SIB])
        conn.close()


class OperacionesDelSiblingTest(unittest.TestCase):
    """El reporte del PADRE tiene que incluir las operations del sibling."""

    def test_fetch_operations_in_range_incluye_el_sibling(self):
        conn = main.get_db()
        uid = _mk_par(conn)
        _op(conn, uid, PADRE, "2026-03-05", "AL30", 100.0)
        _op(conn, uid, SIB, "2026-03-06", "AAPL", 250.0)
        conn.commit()

        ops = builder.fetch_operations_in_range(
            conn, uid, "2026-03-01", "2026-03-31", PADRE)
        self.assertEqual(len(ops), 2, f"faltan ops del sibling: {ops}")
        self.assertAlmostEqual(sum(float(o["pnl_usd"] or 0) for o in ops), 350.0, places=2)
        conn.close()

    def test_realized_del_periodo_suma_las_dos_patas(self):
        conn = main.get_db()
        uid = _mk_par(conn)
        _me(conn, uid, PADRE, 2026, 3, ci=1000, cf=1100, pnl=100)
        _me(conn, uid, SIB, 2026, 3, ci=500, cf=750, pnl=250)
        _op(conn, uid, PADRE, "2026-03-05", "AL30", 100.0)
        _op(conn, uid, SIB, "2026-03-06", "AAPL", 250.0)
        conn.commit()

        rep = builder.build_period_report(
            conn, uid, "month", "2026-03", broker_filter=PADRE,
            today=date(2026, 6, 15))
        self.assertAlmostEqual(rep.metrics.realized_pnl, 350.0, places=2)
        self.assertEqual(rep.metrics.trades_count, 2)
        conn.close()

    def test_un_broker_sin_sibling_no_cambia(self):
        """Guard: el fix no puede mover el número de un broker suelto."""
        conn = main.get_db()
        email = f"solo-{uuid.uuid4().hex[:12]}@rendi.test"
        uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
            (email,),
        ).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) "
                     "VALUES (?, 'Binance', 'USDT')", (uid,))
        conn.execute("INSERT INTO brokers (user_id, name, currency) "
                     "VALUES (?, 'Otro', 'USDT')", (uid,))
        _op(conn, uid, "Binance", "2026-03-05", "BTC", 42.0)
        _op(conn, uid, "Otro", "2026-03-06", "ETH", 999.0)
        conn.commit()

        ops = builder.fetch_operations_in_range(
            conn, uid, "2026-03-01", "2026-03-31", "Binance")
        self.assertEqual(len(ops), 1)
        self.assertAlmostEqual(float(ops[0]["pnl_usd"]), 42.0, places=2)
        conn.close()


class MonthlyEntryDelParTest(unittest.TestCase):
    """fetch_monthly_entry colapsa el par — y sigue devolviendo None sin filas."""

    def test_suma_las_dos_filas_del_mes(self):
        conn = main.get_db()
        uid = _mk_par(conn)
        _me(conn, uid, PADRE, 2026, 3, ci=760, cf=900, dep=40, wit=10, pnl=110, unre=100)
        _me(conn, uid, SIB, 2026, 3, ci=500, cf=620, dep=20, wit=0, pnl=0, unre=100)
        conn.commit()

        me = builder.fetch_monthly_entry(conn, uid, 2026, 3, PADRE)
        self.assertIsNotNone(me)
        self.assertAlmostEqual(me["capital_inicio"], 1260.0, places=2)
        self.assertAlmostEqual(me["capital_final"], 1520.0, places=2)
        self.assertAlmostEqual(me["deposits"], 60.0, places=2)
        self.assertAlmostEqual(me["withdrawals"], 10.0, places=2)
        self.assertAlmostEqual(me["pnl_realized"], 110.0, places=2)
        self.assertAlmostEqual(me["pnl_unrealized"], 200.0, places=2)
        conn.close()

    def test_sin_filas_devuelve_None_no_un_dict_de_ceros(self):
        """⚠️ Un SELECT agregado SIN GROUP BY devuelve SIEMPRE una fila (NULLs).

        Ese `None` es carga útil: es el que dispara el fallback AUDIT C-3
        (builder.py `if not me:` hereda el capital_final del mes anterior) y
        el `_hay_algo` del mes en curso. Sin el COUNT(*), el mes en curso de
        una cuenta sin fila arranca en 0 y publica la cartera entera como
        "P&L del mes".
        """
        conn = main.get_db()
        uid = _mk_par(conn)
        conn.commit()
        self.assertIsNone(builder.fetch_monthly_entry(conn, uid, 2026, 3, PADRE))
        self.assertIsNone(builder.fetch_monthly_entry(conn, uid, 2026, 3, "global"))
        conn.close()

    def test_mes_en_curso_hereda_el_cierre_del_PAR_no_de_una_pata(self):
        """AUDIT C-3 sobre el par: el `LIMIT 1` tiene que ir DESPUÉS del GROUP BY."""
        conn = main.get_db()
        uid = _mk_par(conn)
        _me(conn, uid, PADRE, 2026, 2, ci=700, cf=760, dep=0, wit=0, pnl=60)
        _me(conn, uid, SIB, 2026, 2, ci=450, cf=500, dep=0, wit=0, pnl=50)
        conn.commit()

        # Marzo NO tiene fila → hereda el cierre de febrero del PAR = 1260.
        rep = builder.build_period_report(
            conn, uid, "month", "2026-03", broker_filter=PADRE,
            live_value=1400.0, today=date(2026, 3, 15))
        self.assertAlmostEqual(rep.metrics.start_value, 1260.0, places=2,
                               msg="el capital de arranque quedó partido al medio")
        conn.close()


class CapitalDelAnioTest(unittest.TestCase):
    """T1 — la rama 'year' con dos filas por mes."""

    def _fixture(self, conn):
        uid = _mk_par(conn)
        # padre: 600→700, 700→760, 760→900 (dep 200 en enero)
        _me(conn, uid, PADRE, 2026, 1, ci=600, cf=700, dep=100, pnl=0)
        _me(conn, uid, PADRE, 2026, 2, ci=700, cf=760, pnl=60)
        _me(conn, uid, PADRE, 2026, 3, ci=760, cf=900, dep=40, pnl=100, unre=100)
        # sibling: 400→450, 450→500, 500→620
        _me(conn, uid, SIB, 2026, 1, ci=400, cf=450, dep=50, pnl=0)
        _me(conn, uid, SIB, 2026, 2, ci=450, cf=500, pnl=50)
        _me(conn, uid, SIB, 2026, 3, ci=500, cf=620, dep=70, pnl=50, unre=100)
        conn.commit()
        return uid

    def test_capital_del_anio_no_se_parte_al_medio(self):
        conn = main.get_db()
        uid = self._fixture(conn)
        rep = builder.build_period_report(
            conn, uid, "year", "2026", broker_filter=PADRE,
            today=date(2027, 2, 1))          # año CERRADO
        m = rep.metrics
        # start = capital_inicio del PAR en enero (600 + 400)
        self.assertAlmostEqual(m.start_value, 1000.0, places=2,
                               msg="rows[0] agarró una pata sola")
        # end = capital_final del PAR en marzo (900 + 620)
        self.assertAlmostEqual(m.end_value, 1520.0, places=2,
                               msg="rows[-1] agarró una pata sola")
        self.assertAlmostEqual(m.deposits, 260.0, places=2)
        conn.close()

    def test_la_composicion_geometrica_del_anio_sigue_viva(self):
        """⚠️ Con `IN` pelado, `_meses_con_fila` = [1,1,2,2,3,3] → `_hay_agujero`
        da True SIEMPRE y el TWR del año se apaga EN SILENCIO (queda None).
        No hay pantalla ni log donde se vea: el año se cae al Dietz punta a
        punta y nadie se entera."""
        conn = main.get_db()
        uid = self._fixture(conn)
        rep = builder.build_period_report(
            conn, uid, "year", "2026", broker_filter=PADRE,
            today=date(2027, 2, 1))
        # `assertIsNotNone(delta_pct)` NO sirve acá y es una trampa: cuando
        # `_hay_agujero` se dispara el año no se queda sin número — se saltea la
        # composición geométrica y cae al Dietz punta a punta, que devuelve un
        # float perfectamente truthy. O sea que el modo de falla que este test
        # dice cuidar es justo el que un assert de "no es None" no puede ver.
        # Hay que pinnear el VALOR: con el `IN` pelado da −32,88 % en vez de
        # +23,01 %, o sea el titular del año dado vuelta de signo.
        self.assertIsNotNone(rep.metrics.delta_pct)
        self.assertAlmostEqual(
            rep.metrics.delta_pct, 23.01, places=1,
            msg="si esto da negativo, la composición geométrica se apagó y el "
                "año cayó al Dietz punta a punta sobre filas duplicadas")
        conn.close()


class CapitalAportadoDelParTest(unittest.TestCase):
    """T3 — el denominador de '% sobre aportado' suma las dos patas."""

    def test_cum_deposits_suma_el_par(self):
        conn = main.get_db()
        uid = _mk_par(conn)
        _me(conn, uid, PADRE, 2026, 1, ci=0, cf=120, dep=120)
        _me(conn, uid, PADRE, 2026, 2, ci=120, cf=240, dep=120)
        _me(conn, uid, SIB, 2026, 1, ci=0, cf=80, dep=80)
        _me(conn, uid, SIB, 2026, 2, ci=80, cf=160, dep=80)
        conn.commit()

        got = builder.fetch_cum_deposits_until(conn, uid, "2026-12-31", PADRE)
        self.assertAlmostEqual(got, 400.0, places=2, msg="240 del padre + 160 del sibling")
        # Comparar contra 'global' acá era una tautología: el fixture no escribe
        # ninguna fila broker='global', así que devolvía 0.0 → falsy → el
        # `glob if glob else 400.0` caía al literal y comparaba 400 contra 400.
        # Lo que corresponde chequear es que el sibling entre de verdad, o sea
        # que el número NO sea el del padre solo.
        self.assertNotAlmostEqual(
            got, 240.0, places=2, msg="240 es el padre solo: el sibling no entró")
        conn.close()

    def test_portfolio_snapshot_summary_capital_aportado(self):
        conn = main.get_db()
        uid = _mk_par(conn)
        _me(conn, uid, PADRE, 2026, 1, ci=0, cf=120, dep=120)
        _me(conn, uid, SIB, 2026, 1, ci=0, cf=80, dep=80)
        conn.commit()

        s = main._portfolio_snapshot_summary(conn, uid, broker_filter=PADRE)
        self.assertAlmostEqual(s["cum_deposited"], 200.0, places=2)
        conn.close()


class PosicionesDelParTest(unittest.TestCase):
    """positions_count / top_holdings / concentración cuentan el sibling."""

    def _fixture(self, conn):
        uid = _mk_par(conn)
        _pos(conn, uid, PADRE, "AL30", 100, 5000.0)
        _pos(conn, uid, SIB, "AAPL", 10, 2000.0)
        _pos(conn, uid, SIB, "ON YPF", 5, 1000.0)
        conn.commit()
        return uid

    def test_positions_count_incluye_el_sibling(self):
        conn = main.get_db()
        uid = self._fixture(conn)
        s = main._portfolio_snapshot_summary(conn, uid, broker_filter=PADRE)
        self.assertEqual(s["positions_count"], 3)
        conn.close()

    def test_top_holdings_incluye_el_sibling(self):
        conn = main.get_db()
        uid = self._fixture(conn)
        s = main._portfolio_snapshot_summary(conn, uid, broker_filter=PADRE)
        assets = {h["asset"] for h in s["top_holdings"]}
        self.assertIn("AAPL", assets)
        self.assertIn("AL30", assets)
        conn.close()

    def test_brokers_count_colapsa_el_par(self):
        """El sibling es plumbing: 'en N brokers' no puede contarlo aparte.

        Misma definición que `ai/plan.py:count_broker_accounts` (raíces +
        huérfanos), que es la SSoT de "cuántas CUENTAS tiene el user".
        """
        conn = main.get_db()
        uid = self._fixture(conn)
        s = main._portfolio_snapshot_summary(conn, uid, broker_filter="global")
        self.assertEqual(s["brokers_count"], 1,
                         "el sub-broker '· USD' se contó como un broker más")
        conn.close()

    def test_concentracion_incluye_el_sibling(self):
        conn = main.get_db()
        uid = self._fixture(conn)
        pos = timeline._fetch_positions_for_concentration(conn, uid, PADRE, {}, 1000.0)
        self.assertEqual(len(pos), 3)
        conn.close()

    def test_last_op_mira_el_par(self):
        conn = main.get_db()
        uid = _mk_par(conn)
        _op(conn, uid, PADRE, "2026-03-05", "AL30", 100.0)
        _op(conn, uid, SIB, "2026-03-20", "AAPL", 250.0)   # la ÚLTIMA
        conn.commit()
        s = main._portfolio_snapshot_summary(conn, uid, broker_filter=PADRE)
        self.assertEqual(s["last_op"]["asset"], "AAPL")
        conn.close()


class NoHayDobleConteoTest(unittest.TestCase):
    """Sumar el par no puede dar un número distinto del de 'global'.

    ⚠️ ESTO NO ES UN TEST DEL NETEO T4, y no puede serlo: la fila 'global' la
    escribe el fixture a mano, así que la igualdad sale por construcción, no
    por ninguna propiedad de `_persist_fx` ni del recalc — que son los que
    producirían (o no) el doble conteo del bruto. Lo que SÍ pinnea es que
    `fetch_cum_deposits_until` sume las dos patas: pre-fix daba 706,71.
    Un test de verdad de T4 tiene que pasar por el importador completo.
    """

    def test_suma_las_dos_patas(self):
        conn = main.get_db()
        uid = _mk_par(conn)
        _me(conn, uid, PADRE, 2026, 1, ci=0, cf=706.71, dep=706.71)
        _me(conn, uid, SIB, 2026, 1, ci=0, cf=5000, dep=5000)
        conn.commit()

        par = builder.fetch_cum_deposits_until(conn, uid, "2026-12-31", PADRE)
        self.assertAlmostEqual(par, 5706.71, places=2)
        conn.close()

    def test_dietz_y_pct_sobre_aportado_iguales_en_padre_y_sibling(self):
        """Filtrar por el padre o por el sibling da EL MISMO reporte."""
        conn = main.get_db()
        uid = _mk_par(conn)
        _me(conn, uid, PADRE, 2026, 3, ci=1000, cf=1100, dep=0, pnl=100)
        _me(conn, uid, SIB, 2026, 3, ci=500, cf=750, dep=0, pnl=250)
        conn.commit()

        a = builder.build_period_report(conn, uid, "month", "2026-03",
                                        broker_filter=PADRE, today=date(2026, 6, 1))
        b = builder.build_period_report(conn, uid, "month", "2026-03",
                                        broker_filter=SIB, today=date(2026, 6, 1))
        self.assertAlmostEqual(a.metrics.start_value, b.metrics.start_value, places=2)
        self.assertAlmostEqual(a.metrics.end_value, b.metrics.end_value, places=2)
        self.assertAlmostEqual(a.metrics.start_value, 1500.0, places=2)
        self.assertAlmostEqual(a.metrics.end_value, 1850.0, places=2)
        conn.close()


if __name__ == "__main__":
    unittest.main()


class CadenaRalaPorPataTest(unittest.TestCase):
    """`monthly_entries` es RALA por broker, y sumar dos cadenas ralas de
    cobertura distinta NO da una cadena válida.

    El GC de `_recalc_pnl_realized_from_ops` borra toda fila con
    deposits = withdrawals = pnl = 0 sin mirar `capital_final`, y
    `_repair_monthly_chain` encadena por broker SALTEANDO los huecos. El
    sibling '· USD' sólo tiene fila en los meses donde vendió o cobró.

    Un `SUM(capital_final)` agrega únicamente las filas que EXISTEN → el
    capital de la pata sin fila se evapora, mientras `pnl_realized` (que mira
    el par entero) lo sigue contando. Los tres casos de abajo son los tres
    lugares donde eso se publica en pantalla.

    Nota sobre el invariante: se conserva el INTRA-mes
    (`cf = ci + dep − wit + pnl`) pero se rompe el INTER-mes
    (`ci(m+1) = cf(m)`), que es el que usan las puntas del período.
    """

    def test_cierre_del_anio_no_pierde_la_pata_sin_fila_en_el_ultimo_mes(self):
        """BLOQUEANTE. El padre opera todo el año, el sibling sólo en junio.

        `rows[-1]` es diciembre, mes en el que el sibling no tiene fila: su
        capital desaparecía del cierre y la tarjeta quedaba diciendo
        'Valor cierre' < 'Realizado' con no-realizado en cero.
        """
        conn = main.get_db()
        uid = _mk_par(conn)
        # Padre: cadena densa ene→dic, arranca en 1000 y suma 100 por mes.
        cap = 1000.0
        for m in range(1, 13):
            _me(conn, uid, PADRE, 2026, m, ci=cap, cf=cap + 100, pnl=100)
            _op(conn, uid, PADRE, f"2026-{m:02d}-10", "GGAL", 100)
            cap += 100
        # Sibling: UNA sola fila, en junio. Su capital (500) queda vivo
        # después, pero sin fila propia en jul→dic.
        _me(conn, uid, SIB, 2026, 6, ci=0.0, cf=500.0, pnl=500)
        _op(conn, uid, SIB, "2026-06-15", "AAPL", 500)
        conn.commit()

        rep = builder.build_period_report(
            conn, uid, "year", "2026", broker_filter=PADRE,
            today=date(2027, 3, 1))

        self.assertAlmostEqual(
            rep.metrics.end_value, 2700.0, places=2,
            msg="el cierre tiene que incluir los 500 del sibling, que siguen "
                "vivos aunque su última fila sea de junio")

        # EL invariante que el bug rompía, y el que se ve en pantalla: el
        # capital ganado en el período tiene que ser el P&L que el mismo
        # reporte publica al lado. Sin el fix daba 1200 contra 1700 realizado,
        # o sea "Valor cierre" y "Realizado" contándose distinto en la misma
        # tarjeta. No se compara contra 'global' a propósito: el fixture
        # tendría que escribir esa fila a mano y la igualdad saldría por
        # construcción en vez de por el comportamiento.
        ganado = (rep.metrics.end_value - rep.metrics.start_value
                  - rep.metrics.deposits + rep.metrics.withdrawals)
        self.assertAlmostEqual(
            ganado, rep.metrics.realized_pnl, places=2,
            msg=f"el capital dice {ganado} y el realizado "
                f"{rep.metrics.realized_pnl}: las dos patas no se están "
                f"contando en los dos lados")

    def test_denominador_del_mes_no_se_achica_cuando_falta_una_pata(self):
        """ALTO. En un mes donde sólo el padre tiene fila, `capital_inicio` del
        par salía sin el capital que el sibling ya había acumulado → el
        denominador de Modified Dietz quedaba chico y el % del mes inflado."""
        conn = main.get_db()
        uid = _mk_par(conn)
        _me(conn, uid, PADRE, 2026, 1, ci=0.0, cf=1000.0, pnl=1000)
        _me(conn, uid, SIB,   2026, 1, ci=0.0, cf=500.0,  pnl=500)
        # Marzo: sólo el padre. El sibling sigue teniendo sus 500.
        _me(conn, uid, PADRE, 2026, 3, ci=1000.0, cf=1100.0, pnl=100)
        conn.commit()

        me = builder.fetch_monthly_entry(conn, uid, 2026, 3, broker_filter=PADRE)
        self.assertIsNotNone(me)
        self.assertAlmostEqual(
            me["capital_inicio"], 1500.0, places=2,
            msg="el arranque de marzo es 1000 del padre + 500 que el sibling "
                "traía de enero")
        self.assertAlmostEqual(me["capital_final"], 1600.0, places=2)
        # El flujo del mes NO arrastra: es del mes.
        self.assertAlmostEqual(me["pnl_realized"], 100.0, places=2)

    def test_arranque_del_mes_no_lo_fija_una_pata_sola(self):
        """ALTO — era una REGRESIÓN respecto del código pre-fix.

        Consolidar 'el último mes con filas del par' elige un mes que puede
        pertenecer a UNA sola pata. Con el padre parado desde agosto y el
        sibling vendiendo en noviembre, el arranque pasaba a ser el capital
        del sibling solo (200) — peor que el `LIMIT 1` pelado de antes, que
        al menos traía los 8.000 del padre. La verdad es 8.200.
        """
        conn = main.get_db()
        uid = _mk_par(conn)
        cap = 0.0
        for m in range(1, 9):                     # padre: ene→ago
            _me(conn, uid, PADRE, 2026, m, ci=cap, cf=cap + 1000, pnl=1000)
            cap += 1000
        _me(conn, uid, SIB, 2026, 11, ci=0.0, cf=200.0, pnl=200)
        conn.commit()

        rep = builder.build_period_report(
            conn, uid, "month", "2026-12", broker_filter=PADRE,
            live_value=12000.0, today=date(2026, 12, 15))
        self.assertAlmostEqual(
            rep.metrics.start_value, 8200.0, places=2,
            msg="cada pata aporta SU último cierre, aunque sean de meses "
                "distintos: 8.000 del padre (agosto) + 200 del sibling (nov)")

    def test_una_sola_pata_da_exactamente_lo_de_antes(self):
        """Gate de merge: un broker sin sibling no puede moverse ni un peso."""
        conn = main.get_db()
        uid = _mk_par(conn)
        conn.execute("DELETE FROM brokers WHERE user_id=? AND name=?", (uid, SIB))
        _me(conn, uid, PADRE, 2026, 1, ci=0.0,    cf=1000.0, pnl=1000)
        _me(conn, uid, PADRE, 2026, 3, ci=1000.0, cf=1100.0, pnl=100)
        conn.commit()

        me = builder.fetch_monthly_entry(conn, uid, 2026, 3, broker_filter=PADRE)
        self.assertAlmostEqual(me["capital_inicio"], 1000.0, places=2)
        self.assertAlmostEqual(me["capital_final"], 1100.0, places=2)
        # Y un mes sin ninguna fila sigue devolviendo None (fallback AUDIT C-3).
        self.assertIsNone(
            builder.fetch_monthly_entry(conn, uid, 2026, 2, broker_filter=PADRE))

    def test_capital_vigente_devuelve_None_si_no_hubo_nunca_nada(self):
        """None ≠ 0.0: el `if not me` de C-3 depende de poder distinguirlos."""
        conn = main.get_db()
        uid = _mk_par(conn)
        conn.commit()
        self.assertIsNone(
            builder.capital_vigente(conn, uid, [PADRE, SIB], 2026, 12))


class FugasCrossBrokerTest(unittest.TestCase):
    """Lo que el reporte NO puede seguir afirmando cuando hay filtro de broker.

    Con el reporte ya exacto al par, cualquier bloque que siga siendo
    cross-broker deja de ser ruido tolerable y pasa a ser una afirmación falsa
    pegada a números correctos.
    """

    def test_los_movers_no_se_publican_con_filtro_de_broker(self):
        """`snapshots.holdings_json` no guarda el broker por activo: no hay con
        qué desagregarlos. El reporte de 'IOL' llegaba a decir 'Mejor activo:
        NVDA' sobre un activo que el usuario tiene en Binance."""
        conn = main.get_db()
        uid = _mk_par(conn)
        conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?, 'Binance', 'USD')",
            (uid,))
        _me(conn, uid, PADRE, 2026, 3, ci=1000.0, cf=1100.0, pnl=100)
        for d, al30, nvda in (("2026-02-28", 1000, 1000), ("2026-03-31", 1010, 3000)):
            conn.execute(
                """INSERT INTO snapshots (user_id, date, total_value,
                                         total_invested, holdings_json, source)
                   VALUES (?,?,?,?,?,'cron')""",
                (uid, d, al30 + nvda, al30 + nvda,
                 f'[{{"asset":"AL30","value_usd":{al30}}},'
                 f'{{"asset":"NVDA","value_usd":{nvda}}}]'))
        conn.commit()

        rep = builder.build_period_report(
            conn, uid, "month", "2026-03", broker_filter=PADRE,
            today=date(2026, 6, 1))
        self.assertFalse(
            rep.movers_available,
            "con filtro de broker no hay dato para desagregar los movers")
        self.assertEqual(rep.movers, [])

        # Sin filtro sí se publican: el fix no los apagó para todos.
        glob = builder.build_period_report(
            conn, uid, "month", "2026-03", broker_filter="global",
            today=date(2026, 6, 1))
        self.assertTrue(glob.movers_available)
        conn.close()

    def test_top_holdings_ordena_en_usd_no_mezclando_monedas(self):
        """`invested` está en la moneda NATIVA del broker. Ordenar crudo hace
        que las filas del padre (pesos) ganen por ~1400× y el holding más
        grande de la cuenta — el de la pata dólar — no entre nunca al top 3."""
        conn = main.get_db()
        uid = _mk_par(conn)
        _pos(conn, uid, PADRE, "AL30", 10, 1_000_000)   # ≈ US$707 al MEP
        _pos(conn, uid, PADRE, "GGAL", 10, 900_000)     # ≈ US$636
        _pos(conn, uid, PADRE, "YPFD", 10, 800_000)     # ≈ US$565
        _pos(conn, uid, SIB,   "AAPL", 10, 50_000)      # US$50.000 ← el más grande
        conn.commit()

        s = main._portfolio_snapshot_summary(conn, uid, broker_filter=PADRE)
        assets = [h["asset"] for h in s["top_holdings"]]
        self.assertEqual(
            assets[0], "AAPL",
            f"el holding más grande de la cuenta es AAPL (US$50.000); salió {assets}")
        conn.close()
