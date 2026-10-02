"""Fase 4 del audit de variaciones (AUDIT_variaciones_2026-07-08.md) — motor de
reportes. Escenarios numéricos del audit como regresión:

- C-2: el período EN CURSO comparaba capital_inicio A COSTO contra un end MtM
  (live) → fabricaba el unrealized histórico como "P&L del mes/año".
- C-3: mes en curso SIN fila monthly → start 0 → "P&L del mes" = cartera entera.
- H-8: day/week con filtro de broker usaban snapshots GLOBALES → delta del
  portfolio entero mostrado como del broker.
- H-7: los Δ chips del summary pasaban netdep SIN baseline contra snapshots CON
  baseline → delta inflado en exactamente el baseline.
"""
import unittest
from datetime import datetime, timedelta

import main
from reporting.builder import compute_metrics_for_period, parse_period_bounds


def _new_user(conn, email):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)", (email, "x"),
    )
    return cur.lastrowid


def _iso(d):
    return d.strftime("%Y-%m-%d")


class VariacionesF4Test(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("monthly_entries", "snapshots", "operations", "positions", "brokers", "users"):
            self.conn.execute(f"DELETE FROM {t}")
        self.uid = _new_user(self.conn, f"f4-{id(self)}@rendi.test")
        # ⚠️ EL "HOY" LO DEFINE LA APP, NO EL RELOJ DE LA MÁQUINA. `_iso_today()`
        # (main.py:28044) devuelve el día ART (UTC−3) a propósito: los usuarios son
        # argentinos y "hoy" tiene que ser el día calendario que ELLOS ven. Este
        # setUp usaba `datetime.utcnow()`, que entre las 21:00 y la medianoche de
        # Argentina ya es el día siguiente: el snapshot "de ayer" caía en el día que
        # la app llama HOY, `delta_1d` no encontraba borde y volvía None. O sea que
        # estos tests estaban en rojo todas las noches y en verde a la mañana. Pedirle
        # la fecha a la app los deja bien a toda hora y en cualquier zona horaria.
        self.now = datetime.strptime(main._iso_today(), "%Y-%m-%d")
        self.y, self.m = self.now.year, self.now.month
        self.month_key = f"{self.y:04d}-{self.m:02d}"
        self.month_start = f"{self.y:04d}-{self.m:02d}-01"
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _metrics(self, period_type, period_key, broker="global", live=None):
        start, end = parse_period_bounds(period_type, period_key)
        m, _ops = compute_metrics_for_period(
            self.conn, self.uid, period_type, start, end, broker,
            bench=None, live_value=live)
        return m

    def _metrics_month(self, live, broker="global"):
        return self._metrics("month", self.month_key, broker, live)

    def test_c2_mes_en_curso_start_mtm_no_costo(self):
        """Compra en feb 10k que hoy vale 13k; el mes actual FLAT → delta ≈ 0
        (ANTES: capital_inicio a costo 10k vs live 13k → '+3.000 (+30%)')."""
        # Cadena monthly A COSTO: el mes actual arranca en 10.000 (costo).
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',0,0,0,0,10000,10000)""",
            (self.uid, self.y, self.m))
        # Snapshot MtM del cierre del mes pasado: la cartera YA valía 13.000.
        # AUDIT D-1: tiene que ser un cierre MEDIDO (`source='cron'`). Sin esa
        # marca, una fila de fin de mes es indistinguible de la que fabrica
        # `_backfill_snapshots_from_monthly` al costo — ver el test de abajo.
        prev_close = _iso(datetime(self.y, self.m, 1) - timedelta(days=1))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
            "VALUES (?,?,13000,10000,10000,'cron')", (self.uid, prev_close))
        self.conn.commit()
        m = self._metrics_month(live=13000.0)
        self.assertAlmostEqual(m.start_value, 13000.0, delta=1)   # MtM, no 10.000
        self.assertAlmostEqual(m.delta_usd, 0.0, delta=1)          # NO +3.000
        self.assertFalse(m.basis_incomparable)                     # base sana
        if m.delta_pct is not None:
            self.assertLess(abs(m.delta_pct), 1.0)                 # NO +30%

    def test_d1_snapshot_sintetico_no_sirve_de_borde(self):
        """AUDIT D-1: el caso del usuario — −63,37% / −US$127.486 con 0 ops.

        El único snapshot del borde lo fabricó el import copiando `capital_final`
        (la cadena AL COSTO). C-2 lo aceptaba como si fuera mercado, así que el
        parche quedaba sin efecto justo en las cuentas que más lo necesitaban:
        start 201.119 (contabilidad) − end 73.764 (mercado) − 131 de aportes
        = −127.486, y Modified Dietz lo publicaba como −63,37%.
        Ahora esa resta no se publica.
        """
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',131,0,0,-2233,201119,199017)""",
            (self.uid, self.y, self.m))
        prev_close = _iso(datetime(self.y, self.m, 1) - timedelta(days=1))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
            "VALUES (?,?,201119,201119,201119,'import')", (self.uid, prev_close))
        self.conn.commit()
        m = self._metrics_month(live=73764.0)
        self.assertTrue(m.basis_incomparable)
        self.assertIsNone(m.delta_pct)        # NO −63,37%
        self.assertEqual(m.delta_usd, 0.0)    # NO −US$127.486
        # Lo medible sigue publicándose tal cual.
        self.assertAlmostEqual(m.deposits, 131.0, delta=1)
        self.assertAlmostEqual(m.end_value, 73764.0, delta=1)

    def test_d1_sin_snapshot_de_borde_no_publica_el_delta(self):
        """Sin NINGÚN snapshot, start cae en la cadena contable (capital_inicio).
        Ese par costo-vs-mercado es el que fabricaba la pérdida fantasma."""
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',0,0,0,0,201119,201119)""",
            (self.uid, self.y, self.m))
        self.conn.commit()
        m = self._metrics_month(live=73764.0)
        self.assertTrue(m.basis_incomparable)
        self.assertIsNone(m.delta_pct)
        self.assertEqual(m.delta_usd, 0.0)

    def test_d1_borde_viejo_no_sirve(self):
        """Un cierre medido pero de hace 3 semanas mete mercado ajeno al período."""
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',0,0,0,0,10000,10000)""",
            (self.uid, self.y, self.m))
        viejo = _iso(datetime(self.y, self.m, 1) - timedelta(days=21))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
            "VALUES (?,?,13000,10000,10000,'cron')", (self.uid, viejo))
        self.conn.commit()
        m = self._metrics_month(live=13000.0)
        self.assertTrue(m.basis_incomparable)
        self.assertIsNone(m.delta_pct)

    def _fixture_del_bug(self):
        """monthly_entries del caso real + el único snapshot del borde, fabricado
        al costo por el import."""
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',131,0,0,-2233,201119,199017)""",
            (self.uid, self.y, self.m))
        prev_close = _iso(datetime(self.y, self.m, 1) - timedelta(days=1))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
            "VALUES (?,?,201119,201119,201119,'import')", (self.uid, prev_close))
        self.conn.commit()

    def test_d1_semana_y_dia_tampoco_publican(self):
        """El guard tiene que cubrir las CUATRO pestañas.

        Cubriendo sólo mes/año, el mes mostraba "—" y un click más allá la semana
        decía "perdiste US$127.486 (−63,4%)" — dentro de la misma tarjeta. Los dos
        escapes de la rama día/semana no alcanzan: `start_value > 0`, y el gap
        entre bordes da 0 porque snap_start y snap_end son la MISMA fila.
        """
        self._fixture_del_bug()
        iy, iw, _wd = self.now.isocalendar()
        for pt, pk in (("week", f"{iy}-W{iw:02d}"), ("day", self.now.strftime("%Y-%m-%d"))):
            with self.subTest(period=pt):
                m = self._metrics(pt, pk, live=73764.0)
                self.assertTrue(m.basis_incomparable)
                self.assertIsNone(m.delta_pct)
                self.assertEqual(m.delta_usd, 0.0)
                # `unrealized` de día/semana se deriva del delta → es el mismo
                # fantasma con otro nombre.
                self.assertEqual(m.unrealized_pnl, 0.0)

    # ── Sin NINGUNA foto antes del arranque (fecha FIJA, a propósito) ─────────
    # El test de arriba depende del almanaque: su fila del import cae el último
    # día del mes anterior, que según el día queda ANTES del lunes (lo caza el
    # respaldo crudo) o ADENTRO de la semana (el hueco). Medido con el motor
    # viejo: fallaba del 1 al 4 de octubre y pasaba el 5 y el 15. Estos fijan la
    # fecha para que el caso se pruebe todos los días, no sólo cuando cae.

    def _sembrar_cadena(self, y, m, capital_inicio, deposits, capital_final,
                        withdrawals=0, pnl_realized=0, pnl_unrealized=0):
        # capital_final = capital_inicio + deposits − withdrawals + pnl (el
        # invariante que garantiza `_repair_monthly_chain`).
        assert abs(capital_inicio + deposits - withdrawals + pnl_realized
                   + pnl_unrealized - capital_final) < 1, "cadena incoherente"
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',?,?,?,?,?,?)""",
            (self.uid, y, m, deposits, withdrawals, pnl_realized, pnl_unrealized,
             capital_inicio, capital_final))

    def test_d1_semana_sin_foto_antes_del_lunes_no_publica(self):
        """El caso real del 2026-10-01: la cadena arranca en octubre y la única
        fila es la que el import fabricó al costo el 30/9, ADENTRO de la semana
        28/9–4/10. Sin nada antes del lunes el motor suponía arranque 0 y contaba
        los 201.119 de capital como aporte: "Semana: −US$ 127.486" mientras el
        mes y el día de la misma cuenta decían "sin base"."""
        from datetime import date
        from reporting.builder import build_period_report
        self._sembrar_cadena(2026, 10, 201119, 131, 199017, pnl_unrealized=-2233)
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
            "VALUES (?,'2026-09-30',201119,201119,201119,'import')", (self.uid,))
        self.conn.commit()
        rep = build_period_report(self.conn, self.uid, "week", "2026-W40",
                                  broker_filter="global", bench=None,
                                  live_value=73764.0, today=date(2026, 10, 1))
        m = rep.metrics
        self.assertTrue(m.basis_incomparable)
        self.assertEqual(m.delta_usd, 0.0)                  # NO −127.486
        self.assertIsNone(m.delta_pct)
        self.assertEqual(m.unrealized_pnl, 0.0)
        self.assertAlmostEqual(m.deposits, 131.0, delta=1)  # NO 201.250
        self.assertNotIn("US$", rep.headline)
        self.assertNotIn("perdiste", rep.narrative or "")

    def test_d1_cuenta_con_capital_y_ninguna_foto_no_publica_dia_ni_semana(self):
        """Cualquier día del mes: 10.000 al costo que hoy valen 12.000 y todavía
        ninguna foto. El mes decía "sin base"; el día y la semana, "+US$ 2.000"
        con 10.000 de aportes — la ganancia de toda la vida de las posiciones
        presentada como la de hoy."""
        from datetime import date
        from reporting.builder import build_period_report
        self._sembrar_cadena(2026, 10, 10000, 0, 10000)
        self.conn.commit()
        for pt, pk in (("month", "2026-10"), ("week", "2026-W42"), ("day", "2026-10-15")):
            with self.subTest(period=pt):
                rep = build_period_report(self.conn, self.uid, pt, pk,
                                          broker_filter="global", bench=None,
                                          live_value=12000.0, today=date(2026, 10, 15))
                self.assertTrue(rep.metrics.basis_incomparable)
                self.assertEqual(rep.metrics.delta_usd, 0.0)
                self.assertEqual(rep.metrics.deposits, 0.0)
                self.assertNotIn("US$", rep.headline)

    def test_d1_sin_foto_previa_la_plata_nueva_sigue_midiendo(self):
        """El otro lado del guard: sin capital previo (o uno chico frente a lo
        aportado) no hay costo-vs-mercado que esconder. Una cuenta que entró con
        plata NUEVA en el período tiene que seguir viendo su número — igual que el
        primer mes de un usuario nuevo (`test_d1_usuario_nuevo_primer_mes...`).

        Los aportes van en OCTUBRE y la semana es la del 28/9 al 4/10 vista el
        3/10: lo que la cadena anota en octubre entró, seguro, adentro de la
        semana. A mitad de mes no se puede afirmar (un aporte del 2/10 visto en la
        semana del 12/10 sale igual como plata nueva: la cadena no tiene la fecha) y
        por eso este test no lo afirma."""
        from datetime import date
        casos = {
            # (capital_inicio, aportes, valor hoy) → resultado esperado
            "usuario nuevo, todo aportado este mes": (0, 5000, 5200, 200.0),
            "capital chico frente a lo aportado": (1230, 47756, 49100, 114.0),
        }
        for caso, (ci, dep, vivo, esperado) in casos.items():
            with self.subTest(caso=caso):
                self.conn.execute("DELETE FROM monthly_entries WHERE user_id = ?", (self.uid,))
                self._sembrar_cadena(2026, 10, ci, dep, ci + dep)
                self.conn.commit()
                start, end = parse_period_bounds("week", "2026-W40")
                m, _ops = compute_metrics_for_period(
                    self.conn, self.uid, "week", start, end, "global",
                    bench=None, live_value=float(vivo), today=date(2026, 10, 3))
                self.assertFalse(m.basis_incomparable)
                self.assertAlmostEqual(m.delta_usd, esperado, delta=1)

    def test_d1_semana_que_cruza_de_mes_y_sus_dos_anclas(self):
        """La cadena sabe el capital al arrancar cada mes, no el del lunes. En la
        semana del 28/9 al 4/10 hay dos anclas (1/9 y 1/10). Se publica si UNA lo
        permite; si las dos, sólo si dan la misma cuenta. Cada ancla sola se
        equivoca en un caso real:
        · sólo el 1/9: 100.000 en septiembre, retiro de 95.000 el 10/9, 100.000
          nuevos el 2/10 → el lunes había 5.000; el mes y el día publican y la
          semana decía "sin base".
        · sólo el 1/10: el que se registró el 29/9 con plata nueva veía su primera
          semana "sin base" (el 1/10 esa plata ya es capital), mientras el mes y el
          día, medidos desde la foto del cron del 30/9, publicaban."""
        from datetime import date
        with self.subTest(caso="retiro grande antes de la semana"):
            self._sembrar_cadena(2026, 9, 100000, 0, 5000, withdrawals=95000)
            self._sembrar_cadena(2026, 10, 5000, 100000, 105000)
            self.conn.commit()
            for pt, pk in (("month", "2026-10"), ("week", "2026-W40"), ("day", "2026-10-03")):
                rep = self._reporte(pt, pk, 106000.0, date(2026, 10, 3))
                self.assertFalse(rep.metrics.basis_incomparable, pt)
            self.assertAlmostEqual(
                self._reporte("week", "2026-W40", 106000.0, date(2026, 10, 3)).metrics.delta_usd,
                1000.0, delta=1)
        with self.subTest(caso="se registró el 29/9 con plata nueva"):
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id = ?", (self.uid,))
            self._sembrar_cadena(2026, 9, 0, 10000, 10000)
            self._sembrar_cadena(2026, 10, 10000, 0, 10000)
            for d, v in (("2026-09-29", 10000), ("2026-09-30", 10100)):
                self.conn.execute(
                    "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
                    "VALUES (?,?,?,10000,10000,'cron')", (self.uid, d, v))
            self.conn.commit()
            rep = self._reporte("week", "2026-W40", 10200.0, date(2026, 10, 1))
            self.assertFalse(rep.metrics.basis_incomparable)
            self.assertAlmostEqual(rep.metrics.delta_usd, 200.0, delta=1)
        with self.subTest(caso="las dos permiten pero no dan la misma cuenta"):
            # Entró el 29/9 con 10.000, ganó 500 en septiembre y metió 200.000 el
            # 2/10. Con la de hoy: "+US$ 500 sobre un capital inicial de US$
            # 10.500" (el lunes la cuenta no existía); con la del lunes metería
            # los 500 si hubieran sido antes. La cadena no sabe: no se publica. El
            # mes y el día miden OCTUBRE, que sí se sabe, y publican.
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id = ?", (self.uid,))
            self.conn.execute("DELETE FROM snapshots WHERE user_id = ?", (self.uid,))
            self._sembrar_cadena(2026, 9, 0, 10000, 10500, pnl_realized=500)
            self._sembrar_cadena(2026, 10, 10500, 200000, 210500)
            self.conn.commit()
            semana = self._reporte("week", "2026-W40", 211000.0, date(2026, 10, 3))
            self.assertTrue(semana.metrics.basis_incomparable)
            self.assertNotIn("capital inicial", semana.narrative or "")
            for pt, pk in (("month", "2026-10"), ("day", "2026-10-03")):
                rep = self._reporte(pt, pk, 211000.0, date(2026, 10, 3))
                self.assertFalse(rep.metrics.basis_incomparable, pt)
                self.assertAlmostEqual(rep.metrics.delta_usd, 500.0, delta=1)

    def test_d1_sin_foto_previa_se_mide_desde_el_capital_que_valido_el_ancla(self):
        """El ancla decide con el CAPITAL de la cadena (incluye la ganancia que
        quedó adentro). Si después se publicaba `valor − lo aportado`, esa ganancia
        histórica salía como de la semana: "Semana: +US$ 51.000" y "Día: +US$
        51.000" al lado de un mes que decía +1.000. Mes, semana y día de la misma
        cuenta tienen que dar el MISMO monto: los tres arrancan del capital del 1/10."""
        from datetime import date
        casos = {
            # sept: +50.000 realizados y retiro de 145.000 → arranca octubre con 5.000
            "ganancia realizada y retirada": (
                [(2026, 9, 100000, 0, 5000, 145000, 50000),
                 (2026, 10, 5000, 100000, 105000, 0, 0)], 106000.0, 1000.0, 100000.0),
            # sept: retira TODO (con ganancia) → octubre arranca en 0 y entran 10.000.
            # Publicaba "+US$ 50.100 · Retiraste US$ 40.000".
            "todo retirado y plata nueva": (
                [(2026, 9, 100000, 0, 0, 150000, 50000),
                 (2026, 10, 0, 10000, 10000, 0, 0)], 10100.0, 100.0, 10000.0),
        }
        for caso, (cadena, vivo, esperado, aportes) in casos.items():
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id = ?", (self.uid,))
            for y, m, ci, dep, cf, wit, pnl in cadena:
                self._sembrar_cadena(y, m, ci, dep, cf, withdrawals=wit, pnl_realized=pnl)
            self.conn.commit()
            for pt, pk in (("month", "2026-10"), ("week", "2026-W40"), ("day", "2026-10-03")):
                with self.subTest(caso=caso, period=pt):
                    rep = self._reporte(pt, pk, vivo, date(2026, 10, 3))
                    self.assertFalse(rep.metrics.basis_incomparable)
                    self.assertAlmostEqual(rep.metrics.delta_usd, esperado, delta=1)
                    self.assertAlmostEqual(rep.metrics.deposits, aportes, delta=1)
                    self.assertEqual(rep.metrics.withdrawals, 0.0)

    def test_d1_semana_pasada_sin_foto_previa_no_publica(self):
        """Un período PASADO sin ninguna foto previa es la semana de la primera
        foto de la cuenta. Su cierre es una foto y la cadena —mensual— no sabe qué
        flujos entraron antes o después de ella: con el ancla de octubre, el aporte
        del 2/10 (o uno del 20/10) entraba en la semana del 28/9 vista después,
        "Semana: +US$ 100.000 · Retiraste US$ 95.000", mientras septiembre y
        octubre decían 0. La foto la escribe el escritor REAL del import."""
        from datetime import date
        from importing.persister import _backfill_snapshots_from_monthly
        self._sembrar_cadena(2026, 9, 100000, 0, 5000, withdrawals=95000)
        self._sembrar_cadena(2026, 10, 5000, 100000, 105000)
        _backfill_snapshots_from_monthly(self.conn, self.uid)
        self.conn.commit()
        for hoy in (date(2026, 10, 20), date(2026, 11, 20)):
            with self.subTest(hoy=hoy):
                rep = self._reporte("week", "2026-W40", None, hoy)
                self.assertTrue(rep.metrics.basis_incomparable)
                self.assertEqual(rep.metrics.delta_usd, 0.0)
                self.assertEqual(rep.metrics.deposits, 0.0)
                self.assertEqual(rep.metrics.withdrawals, 0.0)

    def test_d1_primera_semana_del_usuario_nuevo_sigue_publicada_al_terminar(self):
        """Se registró el 29/9 con 10.000 de plata nueva y el cron lo mide desde ese
        día. Mientras la semana corría decía "+US$ 150"; terminada, decía "sin base"
        (main publicaba el +250 correcto). El arranque es 0 de verdad (cuenta sin
        historia que empieza el mes en 0) y la estampa del cierre es del cron: las
        dos puntas son exactas. Los otros dos casos fijan el límite de la regla."""
        from datetime import date
        from importing.persister import _backfill_snapshots_from_monthly

        def fotos(*filas):
            for d, v, nd in filas:
                self.conn.execute(
                    "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
                    "VALUES (?,?,?,?,?,'cron')", (self.uid, d, v, nd, nd))

        with self.subTest(caso="cuenta nueva, cierre del cron"):
            self._sembrar_cadena(2026, 9, 0, 10000, 10000)
            self._sembrar_cadena(2026, 10, 10000, 0, 10000)
            fotos(("2026-09-29", 10000, 10000), ("2026-09-30", 10100, 10000),
                  ("2026-10-01", 10150, 10000), ("2026-10-04", 10250, 10000))
            self.conn.commit()
            en_curso = self._reporte("week", "2026-W40", 10150.0, date(2026, 10, 2))
            self.assertFalse(en_curso.metrics.basis_incomparable)
            self.assertAlmostEqual(en_curso.metrics.delta_usd, 150.0, delta=1)
            for hoy in (date(2026, 10, 6), date(2026, 10, 20)):
                rep = self._reporte("week", "2026-W40", None, hoy)
                self.assertFalse(rep.metrics.basis_incomparable, hoy)
                self.assertAlmostEqual(rep.metrics.delta_usd, 250.0, delta=1)
                self.assertAlmostEqual(rep.metrics.deposits, 10000.0, delta=1)
        with self.subTest(caso="cuenta nueva, pero el cierre lo escribió el import"):
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id = ?", (self.uid,))
            self.conn.execute("DELETE FROM snapshots WHERE user_id = ?", (self.uid,))
            self._sembrar_cadena(2026, 9, 0, 10000, 10000)
            _backfill_snapshots_from_monthly(self.conn, self.uid)
            self.conn.commit()
            rep = self._reporte("week", "2026-W40", None, date(2026, 10, 6))
            self.assertTrue(rep.metrics.basis_incomparable)
        with self.subTest(caso="arranca el mes en 0 pero con historia (ganancia retirada)"):
            # Semilla 10.000, +2.000 realizados y retiro de 12.000 en julio: arranca
            # septiembre en 0 pero lo aportado canónico es −2.000, y la estampa del
            # cron lo arrastra → valor − estampa daba +2.100 por una semana de +100.
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id = ?", (self.uid,))
            self.conn.execute("DELETE FROM snapshots WHERE user_id = ?", (self.uid,))
            self._sembrar_cadena(2026, 7, 10000, 0, 0, withdrawals=12000, pnl_realized=2000)
            self._sembrar_cadena(2026, 9, 0, 5000, 5000)
            fotos(("2026-09-29", 5000, 3000), ("2026-10-04", 5100, 3000))
            self.conn.commit()
            rep = self._reporte("week", "2026-W40", None, date(2026, 10, 6))
            self.assertTrue(rep.metrics.basis_incomparable)
            self.assertEqual(rep.metrics.delta_usd, 0.0)

    def test_d1_semana_pasada_no_mide_desde_lo_aportado(self):
        """La cuenta se registró el 7/10 (cron desde ese día): septiembre con
        +50.000 realizados y retiro de 145.000, 100.000 nuevos el 2/10. Vista en
        curso la semana del 5/10 da +1.000, lo mismo que el mes; vista después,
        `valor − lo aportado` devolvía la ganancia histórica: "Semana: +US$ 51.000
        · Aportaste US$ 55.000"."""
        from datetime import date
        self._sembrar_cadena(2026, 9, 100000, 0, 5000, withdrawals=145000, pnl_realized=50000)
        self._sembrar_cadena(2026, 10, 5000, 100000, 105000)
        for d in ("2026-10-07", "2026-10-08", "2026-10-09", "2026-10-10", "2026-10-11"):
            self.conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
                "VALUES (?,?,106000,55000,55000,'cron')", (self.uid, d))
        self.conn.commit()
        en_curso = self._reporte("week", "2026-W41", 106000.0, date(2026, 10, 9))
        self.assertFalse(en_curso.metrics.basis_incomparable)
        self.assertAlmostEqual(en_curso.metrics.delta_usd, 1000.0, delta=1)
        despues = self._reporte("week", "2026-W41", None, date(2026, 10, 20))
        self.assertTrue(despues.metrics.basis_incomparable)
        self.assertEqual(despues.metrics.delta_usd, 0.0)
        self.assertNotIn("51.000", despues.narrative or "")

    def test_d1_sin_foto_previa_con_capital_cero_aplica_las_cotas_del_mes(self):
        """Con arranque 0 `_basis_is_incomparable` no tiene nada que medir, y el
        mes se apoya en dos cotas más: sin flujos no hay resultado, y un valor que
        supera `SALTO_MAX_VECES` lo aportado es plata que la contabilidad no
        registra. Sin ellas día y semana publicaban la cartera entera."""
        from datetime import date
        casos = {
            # cargó posiciones por 12.000 sin registrar aportes: "Semana: +US$ 12.000"
            "sin cadena ni aportes": [],
            # 1.000 aportados contra 12.000 de cartera: 12 veces (el mes: "sin base")
            "aportes que no explican la cartera": [(2026, 10, 0, 1000, 1000)],
            # una cadena rota no es un arranque: con −5.000 publicaba +US$ 17.000
            "capital negativo": [(2026, 10, -5000, 1000, -4000)],
            # ...ni siquiera cuando la cartera sí se explica por los aportes (las
            # otras cotas pasan): con el −5.000 como arranque salía +US$ 2.000 y
            # apoyándose en 0, −US$ 3.000. Ninguno es un resultado.
            "capital negativo con aportes que explican la cartera": [(2026, 10, -5000, 10000, 5000)],
        }
        vivo = {"capital negativo con aportes que explican la cartera": 7000.0}
        for caso, cadena in casos.items():
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id = ?", (self.uid,))
            for y, m, ci, dep, cf in cadena:
                self._sembrar_cadena(y, m, ci, dep, cf)
            self.conn.commit()
            for pt, pk in (("week", "2026-W42"), ("day", "2026-10-15")):
                with self.subTest(caso=caso, period=pt):
                    rep = self._reporte(pt, pk, vivo.get(caso, 12000.0), date(2026, 10, 15))
                    self.assertTrue(rep.metrics.basis_incomparable)
                    self.assertEqual(rep.metrics.delta_usd, 0.0)
                    self.assertNotIn("US$", rep.headline)

    def test_d1_fila_del_import_en_cero_no_aporta_su_estampa(self):
        """Semilla de 10.000 retirada en julio: la fila del import del 31/7 vale 0
        y su estampa es −10.000 (los flujos SIN la semilla). No prende el guard de
        la fila cruda (vale 0) y restarla publicaba "Semana: −US$ 9.500 ·
        Aportaste US$ 30.000". Ahora va por las anclas de la cadena, igual que sin
        ninguna fila: los 20.000 de septiembre son la plata de la semana."""
        from datetime import date
        from importing.persister import _backfill_snapshots_from_monthly
        self._sembrar_cadena(2026, 6, 10000, 0, 10000)
        self._sembrar_cadena(2026, 7, 10000, 0, 0, withdrawals=10000)
        self._sembrar_cadena(2026, 9, 0, 20000, 20000)
        _backfill_snapshots_from_monthly(self.conn, self.uid)
        self.conn.commit()
        fila = self.conn.execute(
            "SELECT total_value, net_deposited, source FROM snapshots "
            "WHERE user_id = ? AND date = '2026-07-31'", (self.uid,)).fetchone()
        self.assertEqual((fila["total_value"], fila["net_deposited"], fila["source"]),
                         (0, -10000, "import"))
        rep = self._reporte("week", "2026-W38", 20500.0, date(2026, 9, 16))
        self.assertFalse(rep.metrics.basis_incomparable)
        self.assertAlmostEqual(rep.metrics.delta_usd, 500.0, delta=1)
        self.assertAlmostEqual(rep.metrics.deposits, 20000.0, delta=1)

    def test_d1_sin_base_por_foto_vieja_del_cron_conserva_sus_aportes(self):
        """Sin base porque la foto del cron de arranque es vieja (hueco del cron),
        pero las DOS estampas son del cron: la resta de lo aportado sí vale y es
        diaria. Pasar a la cadena (mensual) borraba "Aportaste US$ 5.000" del 10/10
        porque octubre no entra entero en el día."""
        from datetime import date
        self._sembrar_cadena(2026, 10, 10000, 5000, 15000)
        for d in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06"):
            self.conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
                "VALUES (?,?,10000,10000,10000,'cron')", (self.uid, d))
        self.conn.commit()
        rep = self._reporte("day", "2026-10-10", 15100.0, date(2026, 10, 10))
        self.assertTrue(rep.metrics.basis_incomparable)
        self.assertAlmostEqual(rep.metrics.deposits, 5000.0, delta=1)

    def test_d1_fila_del_import_en_cero_y_cartera_en_cero_no_inventa_nada(self):
        """Cuenta vaciada en julio (fila del import del 31/7 en 0, estampa −10.000
        SIN la semilla) cuyo cron arranca el 15/9 también en 0. Con valor 0 al
        cierre la resta de estampas publicaba "Semana: −US$ 10.000 · Aportaste US$
        10.000" (y "−200,0%" en el día). No pasó nada: 0 y sin flujos."""
        from datetime import date
        from importing.persister import _backfill_snapshots_from_monthly
        self._sembrar_cadena(2026, 6, 10000, 0, 10000)
        self._sembrar_cadena(2026, 7, 10000, 0, 0, withdrawals=10000)
        _backfill_snapshots_from_monthly(self.conn, self.uid)
        for d in ("2026-09-15", "2026-09-16"):
            self.conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
                "VALUES (?,?,0,0,0,'cron')", (self.uid, d))
        self.conn.commit()
        rep = self._reporte("week", "2026-W38", 0.0, date(2026, 9, 16))
        self.assertEqual(rep.metrics.delta_usd, 0.0)
        self.assertEqual(rep.metrics.deposits, 0.0)
        self.assertEqual(rep.metrics.withdrawals, 0.0)
        self.assertNotIn("US$", rep.headline)

    def test_d1_primera_fila_adentro_del_periodo_en_cero_no_inventa_nada(self):
        """La PRIMERA fila de la cuenta cae adentro de la semana y vale 0 (la misma
        forma del caso original, con la cuenta vaciada). Sin ninguna fila antes y
        con valor 0 al cierre no entraba a ninguna rama y restaba estampas desde 0:
        · pasada: la fila del import del 30/9 (estampa −201.119, SIN semilla) →
          "Semana: +US$ 201.119 · Retiraste US$ 201.119";
        · en curso: el cron arrancó el 30/9 con la cuenta vacía → "Semana: +US$
          500 · Retiraste US$ 500", la ganancia realizada de septiembre."""
        from datetime import date
        from importing.persister import _backfill_snapshots_from_monthly
        with self.subTest(caso="pasada, fila del import"):
            self._sembrar_cadena(2026, 9, 201119, 131, 0, withdrawals=201250)
            _backfill_snapshots_from_monthly(self.conn, self.uid)
            self.conn.commit()
            rep = self._reporte("week", "2026-W40", None, date(2026, 10, 6))
            self.assertTrue(rep.metrics.basis_incomparable)
            self.assertEqual(rep.metrics.delta_usd, 0.0)
            self.assertEqual(rep.metrics.withdrawals, 0.0)
        with self.subTest(caso="en curso, cron que arranca con la cuenta vacía"):
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id = ?", (self.uid,))
            self.conn.execute("DELETE FROM snapshots WHERE user_id = ?", (self.uid,))
            self._sembrar_cadena(2026, 9, 10000, 0, 0, withdrawals=10500, pnl_realized=500)
            self._sembrar_cadena(2026, 10, 0, 0, 0)
            for d in ("2026-09-30", "2026-10-01"):
                self.conn.execute(
                    "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
                    "VALUES (?,?,0,-500,-500,'cron')", (self.uid, d))
            self.conn.commit()
            rep = self._reporte("week", "2026-W40", 0.0, date(2026, 10, 2))
            self.assertTrue(rep.metrics.basis_incomparable)
            self.assertEqual(rep.metrics.delta_usd, 0.0)
            self.assertEqual(rep.metrics.withdrawals, 0.0)

    def test_d1_cuenta_vacia_con_residuo_de_redondeo_no_pasa_a_sin_base(self):
        """Cuenta vaciada en julio con un residuo de redondeo en la cadena (capital
        0,004 los meses siguientes), sin fotos y con la cartera en 0. Con `<= 0`
        exacto el residuo contaba como capital: "Semana sin base…" y la semana
        pasaba a ocupar lugar en la línea de tiempo. No pasó nada."""
        from datetime import date
        self._sembrar_cadena(2026, 7, 10000, 0, 0.004, withdrawals=9999.996)
        for m in (8, 9, 10):
            self._sembrar_cadena(2026, m, 0.004, 0, 0.004)
        self.conn.commit()
        for vivo in (0.0, 0.03):   # 0,03: polvo de cripto que quedó en la cuenta
            with self.subTest(vivo=vivo):
                rep = self._reporte("week", "2026-W42", vivo, date(2026, 10, 15))
                self.assertFalse(rep.metrics.basis_incomparable)
                self.assertAlmostEqual(rep.metrics.delta_usd, vivo, delta=0.01)
                self.assertFalse(rep.is_relevant)

    def test_d1_cadena_negativa_nunca_es_un_arranque_ni_un_cero(self):
        """Una cadena con capital NEGATIVO es una cadena rota: no se sabe cuánto
        valía la cartera al arrancar. Ninguna de las tres reglas de "sin foto
        previa" puede publicar desde ahí (lo cazó la sesión del capital negativo):
        · cartera en 0 y cadena en −10.000 → decía "sin grandes movimientos";
        · semana pasada de una "cuenta nueva" cuya primera fila arranca en −5.000
          → publicaba valor − estampa (la estampa arrastra la semilla negativa).
        Y al revés: un residuo de redondeo (−0,004) NO es una cadena rota."""
        from datetime import date
        with self.subTest(caso="cartera en 0 con cadena negativa"):
            self._sembrar_cadena(2026, 10, -10000, 0, -10000)
            self.conn.commit()
            for pt, pk in (("week", "2026-W42"), ("day", "2026-10-15")):
                rep = self._reporte(pt, pk, 0.0, date(2026, 10, 15))
                self.assertTrue(rep.metrics.basis_incomparable, pt)
                self.assertNotIn("sin grandes movimientos", rep.headline.lower())
                # La causa real, con el MISMO texto que el mes (`_capital_roto`).
                self.assertIn("capital negativo", rep.narrative or "")
        with self.subTest(caso="cuenta 'nueva' con primera fila negativa"):
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id = ?", (self.uid,))
            self._sembrar_cadena(2026, 9, -5000, 10000, 5000)
            for d, v in (("2026-09-29", 5000), ("2026-10-04", 5100)):
                self.conn.execute(
                    "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
                    "VALUES (?,?,?,5000,5000,'cron')", (self.uid, d, v))
            self.conn.commit()
            rep = self._reporte("week", "2026-W40", None, date(2026, 10, 6))
            self.assertTrue(rep.metrics.basis_incomparable)
            self.assertEqual(rep.metrics.delta_usd, 0.0)
            self.assertIn("capital negativo", rep.narrative or "")
        with self.subTest(caso="semana en curso con el mes arrancando en negativo"):
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id = ?", (self.uid,))
            self.conn.execute("DELETE FROM snapshots WHERE user_id = ?", (self.uid,))
            self._sembrar_cadena(2026, 10, -5000, 1000, -4000)
            self.conn.commit()
            rep = self._reporte("week", "2026-W42", 12000.0, date(2026, 10, 15))
            self.assertTrue(rep.metrics.basis_incomparable)
            self.assertIn("capital negativo", rep.narrative or "")
        with self.subTest(caso="residuo de redondeo negativo con plata nueva"):
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id = ?", (self.uid,))
            self.conn.execute("DELETE FROM snapshots WHERE user_id = ?", (self.uid,))
            self._sembrar_cadena(2026, 10, -0.004, 5000, 4999.996)
            self.conn.commit()
            rep = self._reporte("week", "2026-W40", 5200.0, date(2026, 10, 3))
            self.assertFalse(rep.metrics.basis_incomparable)
            self.assertAlmostEqual(rep.metrics.delta_usd, 200.0, delta=1)

    def test_d1_capital_inicio_vacio_no_toma_el_del_mes_siguiente(self):
        """Fila de septiembre con `capital_inicio` NULL y ningún mes antes: el de
        octubre ya trae adentro los 10.000 de septiembre, y usarlo como arranque de
        septiembre los contaba dos veces (la semana quedaba "sin base" con 100 %
        de capital sin medir). El arranque es 0 y la plata, nueva."""
        from datetime import date
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,2026,9,'global',10000,0,0,0,NULL,10000)""", (self.uid,))
        self._sembrar_cadena(2026, 10, 10000, 0, 10000)
        self.conn.commit()
        rep = self._reporte("week", "2026-W40", 10200.0, date(2026, 10, 1))
        self.assertFalse(rep.metrics.basis_incomparable)
        self.assertAlmostEqual(rep.metrics.delta_usd, 200.0, delta=1)

    def test_d1_foto_del_cron_en_cero_conserva_su_estampa(self):
        """El otro lado: una foto del CRON en 0 es la medición de una cuenta vacía,
        y su estampa de lo aportado tiene resolución diaria. Ésa no va por la
        cadena (mensual), que ubicaría en la semana del 12/10 el aporte del 2/10 y
        el retiro del 5/10: "Aportaste US$ 15.000 · Retiraste US$ 10.000"."""
        from datetime import date
        self._sembrar_cadena(2026, 10, 0, 15000, 5000, withdrawals=10000)
        for d, v, nd in (("2026-10-04", 10000, 10000), ("2026-10-11", 0, 0)):
            self.conn.execute(
                "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
                "VALUES (?,?,?,?,?,'cron')", (self.uid, d, v, nd, nd))
        self.conn.commit()
        rep = self._reporte("week", "2026-W42", 5100.0, date(2026, 10, 15))
        self.assertAlmostEqual(rep.metrics.delta_usd, 100.0, delta=1)
        self.assertAlmostEqual(rep.metrics.deposits, 5000.0, delta=1)
        self.assertEqual(rep.metrics.withdrawals, 0.0)

    def _reporte(self, pt, pk, vivo, hoy):
        from reporting.builder import build_period_report
        return build_period_report(self.conn, self.uid, pt, pk, broker_filter="global",
                                   bench=None, live_value=vivo, today=hoy)

    def test_d1_sin_foto_previa_decide_con_el_capital_no_con_lo_aportado(self):
        """El capital que ya estaba se mide como lo mide el mes: con la cadena, que
        incluye la ganancia que quedó adentro. Con lo aportado solo, los tres casos
        publicaban un resultado en semana y día mientras el mes decía "sin base"."""
        from datetime import date
        casos = {
            # Aportó en agosto; ninguna foto. Lo aportado ANTES del mes del período
            # también es capital previo (no sólo el semilla).
            "entró depositando en agosto": (
                [(2026, 8, 0, 10000, 10000, 0, 0)], 12000.0),
            # Aportó 10.000, cobró 20.000 de ganancia y retiró 15.000: lo aportado
            # neto es −5.000, el capital 15.000. Publicaba "+US$ 23.000".
            "ganó y retiró": (
                [(2025, 6, 0, 10000, 30000, 0, 20000),
                 (2026, 8, 30000, 0, 15000, 15000, 0)], 18000.0),
            # 10.000 aportados + 40.000 de ganancia reinvertida, y 100.000 nuevos
            # este mes: lo aportado previo era el 9 % de la base (pasaba), el
            # capital previo es el 33 %. Publicaba "+US$ 50.000".
            "ganancia reinvertida y plata nueva": (
                [(2026, 9, 0, 10000, 50000, 0, 40000),
                 (2026, 10, 50000, 100000, 150000, 0, 0)], 200000.0),
        }
        for caso, (cadena, vivo) in casos.items():
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id = ?", (self.uid,))
            for y, m, ci, dep, cf, wit, pnl in cadena:
                self._sembrar_cadena(y, m, ci, dep, cf, withdrawals=wit, pnl_realized=pnl)
            self.conn.commit()
            for pt, pk in (("month", "2026-10"), ("week", "2026-W42"), ("day", "2026-10-15")):
                with self.subTest(caso=caso, period=pt):
                    rep = self._reporte(pt, pk, vivo, date(2026, 10, 15))
                    self.assertTrue(rep.metrics.basis_incomparable)
                    self.assertEqual(rep.metrics.delta_usd, 0.0)
                    self.assertNotIn("US$", rep.headline)

    def test_d1_sin_base_no_publica_aportes_que_no_puede_ubicar(self):
        """La cadena es mensual: no sabe qué día entró la plata. Un depósito del
        5/9 salía como "Aportaste US$ 50.000 en el período" en la semana del 28/9
        al 4/10. Sin base sólo se publica lo que cae ENTERO adentro del período."""
        from datetime import date
        self._sembrar_cadena(2026, 9, 10000, 50000, 60000)
        self._sembrar_cadena(2026, 10, 60000, 0, 60000)
        self.conn.commit()
        rep = self._reporte("week", "2026-W40", 70000.0, date(2026, 10, 1))
        self.assertTrue(rep.metrics.basis_incomparable)
        self.assertEqual(rep.metrics.deposits, 0.0)
        self.assertNotIn("Aportaste", rep.narrative or "")

    def test_d1_sin_base_los_aportes_no_salen_de_la_estampa_del_import(self):
        """La fila del import la escribe el escritor REAL
        (`persister._backfill_snapshots_from_monthly`), que estampa lo aportado SIN
        el capital semilla. Restarle lo aportado de hoy (CON semilla) publicaba el
        capital entero como aporte: "Aportaste US$ 201.250" donde fueron 131. Pasaba
        por los dos caminos: sin fila antes del arranque y con la fila cruda."""
        from datetime import date
        from importing.persister import _backfill_snapshots_from_monthly
        self._sembrar_cadena(2026, 9, 201119, 0, 201119)
        self._sembrar_cadena(2026, 10, 201119, 131, 199017, pnl_unrealized=-2233)
        _backfill_snapshots_from_monthly(self.conn, self.uid)
        self.conn.commit()
        # ⚠️ El escritor decide qué meses escribe con el reloj REAL de la máquina
        # (`utcnow()`, no `fechas`): desde el 31/10/2026 escribe además la fila de
        # octubre. Por eso se mira SÓLO la del 30/9, que es la que importa acá y la
        # que existe a cualquier fecha posterior. Esa fila de octubre no cambia
        # ninguno de los casos de abajo (todos cierran antes del 31/10).
        fila = self.conn.execute(
            "SELECT net_deposited, source FROM snapshots WHERE user_id = ? AND date = '2026-09-30'",
            (self.uid,)).fetchone()
        self.assertEqual(fila["source"], "import")
        self.assertEqual(fila["net_deposited"], 0)   # la estampa SIN el capital semilla
        casos = (
            # (período, clave, hoy, aportes publicables)
            ("week", "2026-W40", date(2026, 10, 1), 131.0),   # sin fila antes del lunes
            ("day", "2026-10-01", date(2026, 10, 1), 131.0),  # fila cruda del 30/9
            ("week", "2026-W41", date(2026, 10, 5), 0.0),     # fila cruda; octubre no
                                                              # entra entero en la semana
        )
        for pt, pk, hoy, aportes in casos:
            with self.subTest(period=pk):
                rep = self._reporte(pt, pk, 73764.0, hoy)
                self.assertTrue(rep.metrics.basis_incomparable)
                self.assertAlmostEqual(rep.metrics.deposits, aportes, delta=1)
                self.assertEqual(rep.metrics.withdrawals, 0.0)
                self.assertNotIn("201", rep.narrative or "")

    def test_d1_sin_base_la_foto_sin_aportado_no_inventa_un_retiro(self):
        """Semana pasada cuya única foto tiene lo aportado en 0 (el valor que la
        columna usa para "no lo tengo"). En main publicaba "Semana: +US$ 12.000"
        (la cartera entera); una versión intermedia de este arreglo, restándole el
        capital previo, "Retiraste US$ 10.000 en el período"."""
        from datetime import date
        self._sembrar_cadena(2026, 9, 10000, 0, 10000)
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
            "VALUES (?,'2026-09-16',12000,10000,0,'cron')", (self.uid,))
        self.conn.commit()
        rep = self._reporte("week", "2026-W38", None, date(2026, 10, 15))
        self.assertTrue(rep.metrics.basis_incomparable)
        self.assertEqual(rep.metrics.withdrawals, 0.0)
        self.assertEqual(rep.metrics.deposits, 0.0)
        self.assertNotIn("Retiraste", rep.narrative or "")

    def test_d1_over_contrib_no_publica_el_cero_fabricado(self):
        """`delta_pct_over_contrib` se calcula desde `delta_usd`. Con el guard
        tapando el monto a 0, publicaba "+0,0% sobre aportado": un número
        inventado más creíble que el anterior, no menos."""
        self._fixture_del_bug()
        m = self._metrics_month(live=73764.0)
        self.assertTrue(m.basis_incomparable)
        self.assertIsNone(m.delta_pct_over_contrib)

    def test_d1_anio_con_borde_medido_publica_aunque_falte_el_mes_vivo(self):
        """Falso positivo: el año se apagaba entero porque el mes VIVO no tenía
        borde medido, tirando un delta real punta a punta. El `continue` ya saca
        al mes vivo de la composición; el flag del año no debe prenderse."""
        for mm in range(1, self.m + 1):
            self.conn.execute(
                """INSERT INTO monthly_entries (user_id, year, month, broker,
                     deposits, withdrawals, pnl_realized, pnl_unrealized,
                     capital_inicio, capital_final)
                   VALUES (?,?,?,'global',0,0,0,0,100000,100000)""",
                (self.uid, self.y, mm))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source, holdings_json) "
            "VALUES (?,?,100000,90000,90000,'cron','{\"AAPL\":100000}')",
            (self.uid, f"{self.y - 1}-12-31"))
        self.conn.commit()
        m = self._metrics("year", str(self.y), live=112000.0)
        self.assertFalse(m.basis_incomparable)
        self.assertAlmostEqual(m.start_value, 100000.0, delta=1)
        self.assertAlmostEqual(m.delta_usd, 12000.0, delta=1)
        self.assertIsNotNone(m.delta_pct)

    def test_d1_detectores_no_afirman_con_base_incomparable(self):
        """El 0 del guard hacía disparar SIEMPRE a DEPOSITS_DRIVE_GROWTH (sus dos
        salidas comparan contra abs(0)) y afirmaba "el portfolio creció US$+0 por
        rendimiento de mercado" pegado al headline que dice que no se puede medir."""
        from reporting.detectors import run_detectors
        from reporting.builder import build_period_report
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',5000,0,0,0,201119,206119)""",
            (self.uid, self.y, self.m))
        self.conn.commit()
        rep = build_period_report(self.conn, self.uid, "month", self.month_key,
                                  broker_filter="global", bench=None, live_value=73764.0)
        self.assertTrue(rep.metrics.basis_incomparable)
        codes = [i.code for i in run_detectors(rep, positions=[], avg_trades_per_period=0,
                                               historical_win_rate=None)]
        self.assertNotIn("DEPOSITS_DRIVE_GROWTH", codes)
        # Y la narrativa no puede afirmar un resultado.
        self.assertNotIn("perdiste", (rep.narrative or ""))
        self.assertNotIn("ganaste", (rep.narrative or ""))
        # El período sigue siendo relevante: "no medible" no es "sin actividad".
        self.assertTrue(rep.is_relevant)

    def test_d2_vs_sp500_es_el_exceso_no_el_retorno(self):
        """El cambio de semántica no tenía NI UN test del lado que lo produce:
        ningún test pasaba un `bench` poblado, así que revertir
        `vs_sp500 = sp500_ret` dejaba la suite verde."""
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',0,0,0,0,10000,10000)""",
            (self.uid, self.y, self.m))
        prev_close = _iso(datetime(self.y, self.m, 1) - timedelta(days=1))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
            "VALUES (?,?,10000,10000,10000,'cron')", (self.uid, prev_close))
        self.conn.commit()
        py, pm = (self.y, self.m - 1) if self.m > 1 else (self.y - 1, 12)
        bench = {
            "sp500": {f"{py:04d}-{pm:02d}": 100.0, self.month_key: 102.5},
            "inflation_ar": {self.month_key: 1.9},
        }
        start, end = parse_period_bounds("month", self.month_key)
        m, _ops = compute_metrics_for_period(
            self.conn, self.uid, "month", start, end, "global", bench=bench, live_value=9000.0)
        self.assertAlmostEqual(m.sp500_return_pct, 2.5, delta=0.01)
        self.assertAlmostEqual(m.inflation_pct, 1.9, delta=0.01)
        self.assertIsNotNone(m.delta_pct)
        # El campo es el EXCESO, no el retorno del benchmark.
        self.assertAlmostEqual(m.vs_sp500_pct, round(m.delta_pct - 2.5, 2), delta=0.01)
        self.assertLess(m.vs_sp500_pct, 0)   # la cartera cayó: quedó por DEBAJO
        self.assertNotAlmostEqual(m.vs_sp500_pct, 2.5, delta=0.01)

    def test_d2_sin_delta_pct_no_hay_comparacion_contra_benchmark(self):
        """Sin resultado del período no se puede publicar un 'vs S&P': sería
        reintroducir el número tapado por la ventana."""
        self._fixture_del_bug()
        py, pm = (self.y, self.m - 1) if self.m > 1 else (self.y - 1, 12)
        bench = {"sp500": {f"{py:04d}-{pm:02d}": 100.0, self.month_key: 102.5}, "inflation_ar": {}}
        start, end = parse_period_bounds("month", self.month_key)
        m, _ops = compute_metrics_for_period(
            self.conn, self.uid, "month", start, end, "global", bench=bench, live_value=73764.0)
        self.assertIsNone(m.vs_sp500_pct)
        self.assertAlmostEqual(m.sp500_return_pct, 2.5, delta=0.01)  # el dato del S&P sigue

    def test_d1_base_chica_dominada_por_aportes_sigue_midiendo(self):
        """El guard mide cuánto capital SIN medir hay en juego, no si lo hay.

        Capital heredado 1.230 contra 47.756 de aportes nuevos: aunque el 1.230
        salga de la cadena, el error máximo que puede meter es el 2,5% de la base
        del período. Tapar ese número sería tan poco informativo como publicar el
        del bug — el umbral (`_UNMEASURED_BASE_TOL`) separa los dos casos.
        """
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',47756,0,0,0,1230,48986)""",
            (self.uid, self.y, self.m))
        self.conn.commit()
        m = self._metrics_month(live=48986.0)
        self.assertFalse(m.basis_incomparable)
        self.assertAlmostEqual(m.delta_usd, 0.0, delta=2)

    def test_d1_usuario_nuevo_primer_mes_sigue_midiendo(self):
        """Regresión: sin capital previo NO hay mezcla posible. El primer mes de
        un usuario nuevo (capital_inicio=0 con aportes) tiene que seguir
        mostrando su rendimiento — el guard no debe comerse el onboarding."""
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',5000,0,0,200,0,5200)""",
            (self.uid, self.y, self.m))
        self.conn.commit()
        m = self._metrics_month(live=5200.0)
        self.assertFalse(m.basis_incomparable)
        self.assertAlmostEqual(m.delta_usd, 200.0, delta=1)
        self.assertIsNotNone(m.delta_pct)

    def test_c3_mes_sin_fila_hereda_cierre_anterior(self):
        """Sin fila del mes actual (rollover no corrió): hereda capital_final del
        mes anterior (ANTES: start 0 → 'P&L del mes' = cartera ENTERA)."""
        py, pm = (self.y, self.m - 1) if self.m > 1 else (self.y - 1, 12)
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',0,0,0,0,10000,10000)""",
            (self.uid, py, pm))
        self.conn.commit()
        m = self._metrics_month(live=13000.0)
        self.assertGreater(m.start_value, 0)                       # heredó, no 0
        self.assertLess(abs(m.delta_usd), 13000 - 1)               # NO la cartera entera

    def test_c3_usuario_nuevo_sin_historia_periodo_incompleto(self):
        """Usuario nuevo sin monthly ni snapshots: período incompleto — delta 0
        honesto y % None (ANTES: '+US$13.000 (+0.0%) sobre capital inicial $0')."""
        m = self._metrics_month(live=13000.0)
        self.assertIsNone(m.delta_pct)
        self.assertAlmostEqual(m.delta_usd, 0.0, delta=1)

    def test_h8_week_con_broker_filter_solo_realized(self):
        """Week con filtro de broker: delta = SOLO el realized del broker, % None
        (ANTES: delta de snapshots GLOBALES atribuido al broker)."""
        # Snapshots globales que se movieron +1.500 esta semana (por OTRO broker).
        today = self.now
        monday = today - timedelta(days=today.weekday())
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
            "VALUES (?,?,20000,18000,18000)", (self.uid, _iso(monday - timedelta(days=1))))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited) "
            "VALUES (?,?,21500,18000,18000)", (self.uid, _iso(today)))
        # Una venta del broker filtrado con P&L −100 esta semana.
        self.conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type, pnl_usd)
               VALUES (?,?,'Binance','BTC','VENTA',-100)""",
            (self.uid, _iso(today)))
        self.conn.commit()
        iy, iw, _ = today.isocalendar()
        m = self._metrics("week", f"{iy}-W{iw:02d}", broker="Binance")
        self.assertIsNone(m.delta_pct)                             # no medible
        self.assertAlmostEqual(m.delta_usd, -100.0, delta=0.01)    # SOLO realized
        self.assertAlmostEqual(m.unrealized_pnl, 0.0, delta=0.01)  # sin universo mixto

    def _sembrar_cierre_de_ayer_con_baseline(self, estampa=60000, source="cron", ahora=None):
        """Cadena con baseline 50.000 + 10.000 aportados, y el cierre de AYER en
        61.000 con netdep CANÓNICO (baseline + flujos = 60.000). Lo comparten H-7
        y B1.

        Dos cosas que tienen que ser verdad CUALQUIER día, no sólo a mitad de mes
        (las dos fallaban el 1 de cada mes; medido el 2026-10-01):

        · La fila de la cadena va en el mes de AYER. Los 10.000 tienen que haber
          entrado ANTES de la foto que ya los cuenta. En el mes de hoy, el día 1
          eso es una contradicción: la foto del 30/9 dice 60.000 aportados y la
          cadena dice que los 10.000 llegaron en octubre. La migración de B1 le
          cree a la cadena, re-estampa 50.000 y el Δ1d da −9.500 — que es la
          cuenta correcta para esos datos, no un bug.
        · El cierre lleva la marca del cron, que es quien lo escribe. Una fila SIN
          marca fechada a fin de mes es, a propósito, la firma de lo que fabrica el
          import (`twr.clasificar_fila`), y el chip la descarta: el día 1 "ayer" es
          fin de mes y el Δ1d volvía None.
        """
        ayer = (ahora or self.now) - timedelta(days=1)
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',10000,0,0,1000,50000,61000)""",
            (self.uid, ayer.year, ayer.month))
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, source) "
            "VALUES (?,?,61000,60000,?,?)", (self.uid, _iso(ayer), estampa, source))
        self.conn.commit()

    def test_h7_delta_chips_netdep_con_baseline(self):
        """Δ1d del summary: con baseline 50k en la cadena, el delta de un día de
        +500 es +500 (ANTES: +50.500 — el baseline entero como 'ganancia')."""
        self._sembrar_cierre_de_ayer_con_baseline()
        s = main._portfolio_snapshot_summary(
            self.conn, self.uid, broker_filter="global", live_value_override=61500.0)
        d1 = s["delta_1d"]
        self.assertIsNotNone(d1)
        self.assertAlmostEqual(d1["usd"], 500.0, delta=1)          # NO 50.500

    def test_h7_chip_acepta_la_fila_vieja_sin_marca_salvo_a_fin_de_mes(self):
        """El chip acepta a propósito las filas legacy SIN `source` (anteriores a
        la columna): descartarlas le borraría el Δ1d a usuarios con fotos válidas
        (`main._snapshot_delta`, `accept=(MEDICION, INDETERMINADO)`). Pero sin marca
        y a fin de mes es la firma del import, y ésa no es un cierre. h7 y b1 cubrían
        la primera mitad de rebote, sólo del 2 al 31; ahora llevan la marca del cron
        y esto las prueba a las dos con el reloj FIJO."""
        import fechas
        self.addCleanup(setattr, fechas, "ahora_art", fechas.ahora_art)
        casos = {
            "mitad de mes": (datetime(2026, 10, 15, 12), 500.0),
            "día 1 (ayer = fin de mes)": (datetime(2026, 10, 1, 12), None),
        }
        for caso, (ahora, esperado) in casos.items():
            with self.subTest(caso=caso):
                fechas.ahora_art = lambda a=ahora: a
                self.conn.execute("DELETE FROM monthly_entries WHERE user_id = ?", (self.uid,))
                self.conn.execute("DELETE FROM snapshots WHERE user_id = ?", (self.uid,))
                self._sembrar_cierre_de_ayer_con_baseline(source=None, ahora=ahora)
                d1 = main._portfolio_snapshot_summary(
                    self.conn, self.uid, broker_filter="global",
                    live_value_override=61500.0)["delta_1d"]
                if esperado is None:
                    self.assertIsNone(d1)
                else:
                    self.assertIsNotNone(d1)
                    self.assertAlmostEqual(d1["usd"], esperado, delta=1)


    # ── Bloqueantes cazados por el review adversarial de F4 ──────────────────

    def test_b1_migracion_startup_no_rompe_delta_chips(self):
        """B1 (CRITICAL): la migración de startup re-estampa snapshots.net_deposited;
        debe usar la convención CANÓNICA (global + baseline). Antes re-escribía SIN
        baseline → tras cada deploy, Δ1d = −baseline entero como pérdida fantasma.

        La foto arranca con la estampa que dejaba la versión rota (10.000: los
        flujos SIN baseline). Con la estampa ya correcta, una migración que no
        hiciera NADA pasaba este test igual."""
        self._sembrar_cierre_de_ayer_con_baseline(estampa=10000)
        # Migración de startup ENTRE estampar y leer (el escenario del deploy).
        main._recompute_snapshots_netdep_for_user(self.conn, self.uid)
        self.conn.commit()
        estampa = self.conn.execute(
            "SELECT net_deposited FROM snapshots WHERE user_id = ?", (self.uid,)).fetchone()[0]
        self.assertAlmostEqual(estampa, 60000.0, delta=1)   # baseline + flujos
        s = main._portfolio_snapshot_summary(
            self.conn, self.uid, broker_filter="global", live_value_override=61500.0)
        d1 = s["delta_1d"]
        self.assertIsNotNone(d1)
        self.assertAlmostEqual(d1["usd"], 500.0, delta=1)   # NO −49.500

    def test_b2_primer_mes_usuario_nuevo_con_depositos(self):
        """B2 (HIGH): primer mes (capital_inicio=0, deposits>0, sin snapshots):
        delta = live − deposits. La versión rota pisaba start=end → −deposits."""
        self.conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                 deposits, withdrawals, pnl_realized, pnl_unrealized,
                 capital_inicio, capital_final)
               VALUES (?,?,?,'global',5000,0,0,0,0,5000)""",
            (self.uid, self.y, self.m))
        self.conn.commit()
        m = self._metrics_month(live=5200.0)
        self.assertAlmostEqual(m.delta_usd, 200.0, delta=1)   # NO −5.000

    def test_b3_narrativa_perdida_sin_pct_dice_perdiste(self):
        """B3 (HIGH): semana per-broker con pérdida realized → la narrativa dice
        'perdiste' (antes: pct None→0.0 → 'ganaste US$ 300 (+0.0%) sobre un
        capital inicial de US$ 0')."""
        from reporting.builder import generate_narrative, generate_headline
        from reporting.schema import PeriodMetrics
        m = PeriodMetrics(
            start_value=0.0, end_value=0.0, delta_usd=-300.0, delta_pct=None,
            delta_pct_over_contrib=None, realized_pnl=-300.0, unrealized_pnl=0.0,
            deposits=0.0, withdrawals=0.0, trades_count=1, win_count=0,
            loss_count=1, win_rate=0.0, vs_sp500_pct=None, vs_inflation_pct=None)
        txt = generate_narrative(m, [], [], "week", "Semana 28")
        self.assertIn("perdiste", txt)
        self.assertNotIn("+0.0%", txt)
        self.assertNotIn("capital inicial de US$ 0", txt)
        head, _sub = generate_headline(m, [], "week")
        self.assertNotIn("+0.0%", head)
        self.assertIn("−US$ 300", head)


if __name__ == "__main__":
    unittest.main()
