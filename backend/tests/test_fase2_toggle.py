"""FASE 2 — el toggle honesto: qué puede afirmar cada modo.

La regla es UNA: ¿el número necesita el CAMINO de los precios, o le alcanza con
las PUNTAS?

  · Rendimiento acumulado / anualizado → le alcanzan las puntas. La contabilidad
    PUEDE afirmarlo: "aportaste 100.000 y figurás en 139.570" son sus dos puntas.
  · Drawdown / pico / volatilidad / rachas → necesitan el CAMINO. La cadena
    contable es un saldo mensual, no un recorrido de precios. Su máximo NUNCA FUE
    UN PRECIO —nadie pagó eso— y publicar una caída contra él es, literal, el bug
    de las once rondas.

EL PUNTO DE PARTIDA, MEDIDO sobre los 822 de la copia de producción del 16/08:
el toggle existía y no servía para nada —598 usuarios veían más LÍNEA, **0** veían
cambiar el NÚMERO, y 331 leían "—" en las dos posiciones—.

⚠️ LAS DOS MITADES VAN JUNTAS. Publicar el acumulado sin cortar el drawdown le da
a esos 331 una curva contable de la que el motor de drawdown saca un pico
fabricado, y vuelve "Su ganancia cayó 167% desde el mejor momento".
"""
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main  # noqa: E402
import twr  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "positions", "operations", "monthly_entries", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"f2-{id(self)}@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,'IBKR','AAPL',0,1,100,'2024-01-01')",
            (self.uid,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def snap(self, d, v, source, net_dep=0.0):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source) VALUES (?,?,?,?,?,?)",
            (self.uid, d, float(v), float(v), float(net_dep), source))
        self.conn.commit()

    def contable(self, d, v, net_dep=0.0):
        """Fin de mes fabricado por el import. ⚠️ SIEMPRE fin de mes: el importador
        y el reconstructor no escriben a mitad de mes, así que un fixture con una
        fila `import` el día 15 prueba algo que no se puede producir."""
        self.snap(d, v, "import", net_dep)

    def medido(self, d, v, net_dep=0.0):
        self.snap(d, v, "cron", net_dep)


class ElToggleAhoraDiceAlgoTest(_Base):

    def test_100pct_contable_gana_un_numero_que_el_certero_no_puede_dar(self):
        """El caso de los 331: sin una sola medición, el CERTERO no puede y el
        ESTIMADO sí. Es LA razón de existir de esta fase.
        """
        for d, v in (("2026-01-31", 100000.0), ("2026-02-28", 110000.0),
                     ("2026-03-31", 120000.0), ("2026-04-30", 130000.0)):
            self.contable(d, v)

        ce = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_CERTERO)
        es = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_ESTIMADO)

        self.assertIsNone(ce["twr"], "sin mediciones el CERTERO no puede afirmar nada")
        self.assertIsNotNone(es["twr"], "el ESTIMADO tiene las dos puntas: puede")
        # 100.000 → 130.000 sin flujos = +30%
        self.assertAlmostEqual(es["twr"], 0.30, places=4)
        self.assertEqual(es["base_del_twr"], "contable")
        self.assertTrue(es["excluye_no_realizado"])

    def test_y_ESE_numero_no_trae_drawdown_ni_pico(self):
        """La otra mitad. Si esto se cae, la fase reabre el bug de las 11 rondas.

        El fixture SUBE y después BAJA: si el motor de drawdown mirara esta serie,
        tendría material de sobra para publicar una caída del 25% desde el máximo.
        Ese máximo (200.000) nunca fue un precio.
        """
        for d, v in (("2026-01-31", 100000.0), ("2026-02-28", 200000.0),
                     ("2026-03-31", 150000.0)):
            self.contable(d, v)
        es = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_ESTIMADO)
        self.assertIsNotNone(es["twr"], "el fixture tiene que PODER publicar un twr")
        self.assertIsNone(es["drawdown_maximo"])
        self.assertIsNone(es["drawdown_actual"])
        self.assertIsNone(es["drawdown_maximo_fecha"])
        self.assertIsNone(es["drawdown_maximo_pico"])

    def test_el_CERTERO_sigue_dando_drawdown(self):
        """El espejo: lo que se le saca al estimado NO se le saca al certero."""
        for d, v in (("2026-01-31", 100000.0), ("2026-02-28", 200000.0),
                     ("2026-03-31", 150000.0)):
            self.medido(d, v)
        ce = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_CERTERO)
        self.assertIsNotNone(ce["twr"])
        self.assertIsNotNone(ce["drawdown_maximo"])
        self.assertLess(ce["drawdown_maximo"], 0.0)
        self.assertEqual(ce["base_del_twr"], "mercado")
        self.assertFalse(ce["excluye_no_realizado"])


class NoReabrirLaFase1Test(_Base):
    """⚠️ EL TEST MÁS IMPORTANTE DE LA FASE.

    `dietz(v0, v1, flujo)` RESTA dos valuaciones. Si v0 sale de la cadena contable
    y v1 de una medición, esa resta no mide nada: es el escalón entre dos reglas —
    el −65,82% del caso 452, exactamente. El modo ESTIMADO agrega puntos contables
    a la cadena, así que es EL lugar donde ese cruce puede volver a colarse.
    """

    def test_la_cadena_contable_NO_se_encadena_contra_una_medicion(self):
        """Fixture diseñado para que el cruce, si existe, sea IMPOSIBLE de no ver.

        Dos bloques PLANOS a distinto nivel: contable en 100.000, mercado en
        50.000. Cada bloque, por su cuenta, rindió 0%. Si la cadena cruzara las
        bases, `dietz(100.000, 50.000, 0)` metería un −50% que ninguna de las dos
        series vivió.
        """
        for d in ("2026-01-31", "2026-02-28", "2026-03-31"):
            self.contable(d, 100000.0)
        for d in ("2026-04-05", "2026-04-06", "2026-04-07"):
            self.medido(d, 50000.0)

        es = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_ESTIMADO)
        self.assertIsNotNone(es["twr"], "el fixture tiene que publicar algo")
        # Las dos series están planas → el acumulado tiene que ser 0%, no −50%.
        self.assertAlmostEqual(es["twr"], 0.0, places=6,
                               msg="se cruzó la base: apareció el escalón como rendimiento")

    def test_el_punto_contable_no_puede_ser_el_pico_de_nadie(self):
        """La cartera está plana a mercado en 10.000 y el import fabricó un
        180.000. Es el fixture de la ronda 7, y tiene que seguir valiendo: en
        ninguno de los dos modos ese 180.000 fija un máximo.
        """
        for d in ("2026-06-30", "2026-07-31", "2026-08-31"):
            self.medido(d, 10000.0)
        self.contable("2026-05-31", 180000.0)
        for modo in (twr.MODO_CERTERO, twr.MODO_ESTIMADO):
            with self.subTest(modo=modo):
                c = twr.curva_indexada(self.conn, self.uid, modo=modo)
                self.assertIsNone(c["drawdown_maximo_pico"],
                                  "una fila fabricada no fija el pico de nadie")


class ElEstimadoNuncaPublicaMenosTest(_Base):
    """El invariante que hizo falta descubrir midiendo: la primera versión de esta
    fase exigía UN solo tramo continuo (igual que el certero) y el resultado fue
    que **232 usuarios PERDÍAN** el número que el certero sí les daba — la historia
    extra ABRE un hueco que en certero no existía. Más historial no puede costar el
    número.
    """

    def test_con_hueco_el_estimado_sigue_publicando(self):
        # Bloque contable viejo, 4 meses de silencio, bloque de mercado reciente.
        for d, v in (("2025-01-31", 100000.0), ("2025-02-28", 110000.0)):
            self.contable(d, v)
        for d, v in (("2026-01-05", 200000.0), ("2026-01-06", 220000.0)):
            self.medido(d, v)

        ce = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_CERTERO)
        es = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_ESTIMADO)
        self.assertTrue(es["serie_partida"], "el fixture tiene que tener el hueco")
        if ce["twr"] is not None:
            self.assertIsNotNone(
                es["twr"], "el ESTIMADO no puede publicar para menos gente que el CERTERO")
        # Y la ventana que publica se DECLARA, no se calla.
        if es["twr"] is not None:
            self.assertIsNotNone(es["ventana_desde"])
            self.assertIsNotNone(es["ventana_hasta"])


if __name__ == "__main__":
    unittest.main()
