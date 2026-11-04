"""Los planes SIN TOPE tienen que poder crear. Auditoría 23/10/2026.

🔴 QUÉ VIGILA, y por qué este archivo existe aparte. `plan.condicion_de_tope()`
devuelve el `WHERE` que hace cumplir el tope del plan, y para los planes que NO
tienen tope (Plus y Pro en alertas; Pro, asesor y admin en brokers) el tope llega
como `None`. La primera versión preguntaba eso en SQL:

    (? IS NULL OR (SELECT COUNT(*) …) < ?)      ← con `limit` en los dos `?`

En SQLite anda perfecto. En Postgres revienta con

    IndeterminateDatatype: could not determine data type of parameter $1

porque psycopg manda `None` sin decir de qué tipo es y en `$1 IS NULL` Postgres
no tiene de dónde inferirlo. Efecto medido: **el único que seguía funcionando era
el plan Free**, el único con tope numérico. Todo el que paga perdía crear
alertas, y el Pro perdía además crear brokers.

⚠️ POR QUÉ NO LO ENCUENTRA LA SUITE DE SQLITE, que es la razón de ser de este
archivo: allá `NULL IS NULL` no necesita que nadie infiera nada y pasa en verde.
Un bug que sólo existe en un motor necesita un test que lo diga, y este test está
escrito para dar VERDE EN SQLITE Y ROJO EN POSTGRES si alguien vuelve a preguntar
el «sin tope» en SQL. Si lo corrés sólo contra SQLite y da verde, no probaste
nada: hace falta `DATABASE_URL`.

Y por qué los tests de tope no lo habían agarrado: todos usan el plan Free, que
es justamente el único que no se rompe. Un tope de 1 y un tope de ninguno son
dos casos, no uno.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main
from ai import plan as _plan


def _nuevo_user(conn, tier):
    uid = conn.execute(
        "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,?)",
        (f"sintope-{os.urandom(5).hex()}@rendi.test", "x", tier)).lastrowid
    conn.commit()
    return uid


class LaCondicionCorreEnLaBase(unittest.TestCase):
    """El nivel más bajo: la condición, ejecutada por el motor de verdad.

    No alcanza con mirar el string que devuelve: el bug no estaba en el texto,
    estaba en cómo el motor trata un parámetro sin tipo. Así que se ejecuta.
    """

    def setUp(self):
        self.conn = main.get_db()

    def tearDown(self):
        try:
            self.conn.rollback()
        except Exception:
            pass
        self.conn.close()

    def _corre(self, cap, limit):
        cond, params = _plan.condicion_de_tope(cap, 1, limit)
        fila = self.conn.execute(f"SELECT 1 AS ok WHERE {cond}", params).fetchone()
        return fila is not None

    def test_sin_tope_deja_pasar_y_no_revienta(self):
        for cap in ("brokers", "alerts"):
            with self.subTest(cap=cap):
                # Si esto levanta IndeterminateDatatype, volvió el bug.
                self.assertTrue(
                    self._corre(cap, None),
                    f"el plan sin tope de {cap} tiene que dejar pasar")

    def test_con_tope_sigue_filtrando(self):
        # El contraste: que arreglar el None no haya desactivado el tope.
        # El usuario 1 no tiene brokers ni alertas en esta base, así que con
        # tope 1 pasa y con tope 0 no.
        for cap in ("brokers", "alerts"):
            with self.subTest(cap=cap):
                self.assertTrue(self._corre(cap, 1), f"{cap}: 0 < 1 tiene que pasar")
                self.assertFalse(self._corre(cap, 0), f"{cap}: 0 < 0 NO tiene que pasar")

    def test_el_tope_desconocido_revienta_aca(self):
        with self.assertRaises(ValueError):
            _plan.condicion_de_tope("inventado", 1, 5)


class ElQuePagaPuedeCrear(unittest.TestCase):
    """El nivel de arriba: los endpoints de verdad, con un plan sin tope.

    `LaCondicionCorreEnLaBase` prueba la pieza; esto prueba que el camino
    completo la usa bien. Sin el arreglo, acá el endpoint tira la excepción de
    Postgres y el usuario Pro no puede crear nada.
    """

    def setUp(self):
        self.conn = main.get_db()
        self.uid = _nuevo_user(self.conn, "pro")
        self.tope_brokers = _plan.PLAN_LIMITS["pro"]["brokers_max"]
        self.tope_alertas = _plan.PLAN_LIMITS["pro"].get("alerts_max")

    def tearDown(self):
        try:
            for t in ("alerts", "positions", "brokers"):
                self.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
            self.conn.commit()
        except Exception:
            try: self.conn.rollback()
            except Exception: pass
        self.conn.close()

    def test_el_plan_pro_no_tiene_tope_de_brokers(self):
        # Si algún día Pro pasa a tener tope, este test tiene que cambiar a
        # propósito y no pasar de casualidad: por eso lo afirma.
        self.assertIsNone(
            self.tope_brokers,
            "este test existe para el caso SIN tope; si Pro ahora tiene uno, "
            "hay que buscar otro tier sin tope o reescribirlo")

    def test_un_pro_crea_tres_brokers_seguidos(self):
        for i in range(3):
            main.create_broker(
                main.BrokerIn(name=f"SinTope{i}", currency="ARS"), uid=self.uid)
        self.conn.rollback()
        quedaron = self.conn.execute(
            "SELECT COUNT(*) c FROM brokers WHERE user_id=?", (self.uid,)).fetchone()["c"]
        self.assertEqual(quedaron, 3, "el que no tiene tope tiene que poder crear")

    def test_un_pro_crea_cuatro_alertas_seguidas(self):
        self.assertIsNone(self.tope_alertas, "este test es para el caso sin tope")
        import unittest.mock as _mock
        import alerts_engine as _ae
        # El sondeo de precio por un número fijo: acá no se está midiendo red.
        with _mock.patch.object(_ae, "price_for_alert", return_value=1.0):
            for i in range(4):
                main.alerts_create(
                    main.AlertCreateIn(kind="price_target", symbol=f"NOTOP{i}",
                                       scope="ticker", direction="above",
                                       threshold=999999.0, currency="USD"),
                    uid=self.uid)
        self.conn.rollback()
        quedaron = self.conn.execute(
            "SELECT COUNT(*) c FROM alerts WHERE user_id=?", (self.uid,)).fetchone()["c"]
        self.assertEqual(quedaron, 4, "el que no tiene tope tiene que poder crear")


if __name__ == "__main__":
    unittest.main()
