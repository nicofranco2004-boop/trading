"""¿La verificación de la copia sabe detectar una copia rota?

Es el test que decide si el copiador se puede escribir. Una verificación que no
sabe fallar no verifica nada: da verde y uno le cree.

**Se prueba rompiendo una copia a propósito, de a UNA cosa por vez.** Las cinco
roturas son las cinco formas conocidas de perder plata en este paso:

  1. una fila de menos
  2. un número cambiado en el ÚLTIMO decimal
  3. un `Decimal` con otro valor donde iba un `float` (tipos distintos tapando
     valores distintos)
  4. una secuencia sin `setval()`  → el próximo alta choca contra un id existente
  5. `raw_json` vaciado con DELETE en vez de UPDATE → cascadea y se lleva el ledger

Y dos que NO tienen que saltar, porque son diferencias legítimas entre motores y
si saltaran la verificación sería ruido que uno aprende a ignorar:

  6. el `int` 1500 de SQLite contra el `float` 1500.0 de psycopg (mismo número)
  7. `raw_json` vaciado BIEN, con UPDATE

Los tests de Postgres se saltean solos si no hay `PG_DSN_VERIF` en el ambiente.
Es una variable APARTE de `DATABASE_URL` a propósito: la suite mata todos los
backends de SU base al cambiar de módulo, así que estos tests apuntan a una base
distinta y no se pisan.
"""
import os
import sqlite3
import unittest
from decimal import Decimal

import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import verificar_copia as vc  # noqa: E402


# El mini-esquema usa los MISMOS tipos declarados que el real (que sólo tiene
# text, bigint y double precision — verificado sobre schema_pg.sql).
ESQUEMA = {
    "users": [("id", "bigint"), ("email", "text")],
    "positions": [("id", "bigint"), ("user_id", "bigint"), ("broker", "text"),
                  ("asset", "text"), ("is_cash", "bigint"),
                  ("quantity", "double precision"), ("invested", "double precision"),
                  ("commissions", "double precision")],
    "operations": [("id", "bigint"), ("user_id", "bigint"), ("asset", "text"),
                   ("pnl_usd", "double precision")],
    "import_raw_rows": [("id", "bigint"), ("batch_id", "text"), ("raw_json", "text")],
}

DDL = """
CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);
CREATE TABLE positions (id INTEGER PRIMARY KEY, user_id INTEGER, broker TEXT,
    asset TEXT, is_cash INTEGER, quantity REAL, invested REAL, commissions REAL);
CREATE TABLE operations (id INTEGER PRIMARY KEY, user_id INTEGER, asset TEXT,
    pnl_usd REAL);
CREATE TABLE import_raw_rows (id INTEGER PRIMARY KEY, batch_id TEXT, raw_json TEXT);
"""

DATOS = [
    ("INSERT INTO users VALUES (?,?)", [(1, "ana@x.test"), (2, "beto@x.test")]),
    ("INSERT INTO positions VALUES (?,?,?,?,?,?,?,?)", [
        (1, 1, "Cocos", "AAPL", 0, 10.0, 1500.0, 3.5),
        (2, 1, "Cocos", "GGAL", 0, 200.0, 88000.25, 0.0),
        (3, 1, "Cocos", "USD", 1, 0.0, 4200.75, 0.0),
        (4, 2, "IOL", "AL30", 0, 1000.0, 62000.0, 12.125),
        (5, 2, "IOL", "USD", 1, 0.0, 900.0, 0.0),
    ]),
    ("INSERT INTO operations VALUES (?,?,?,?)", [
        (1, 1, "AAPL", 123.45), (2, 1, "GGAL", -67.89), (3, 2, "AL30", 4200.01),
    ]),
    ("INSERT INTO import_raw_rows VALUES (?,?,?)", [
        (1, "b1", '{"fila": "el CSV entero, 3 kB"}'),
        (2, "b1", '{"fila": "otra"}'),
        (3, "b2", '{"fila": "y otra mas"}'),
    ]),
]


def _base(path=":memory:"):
    c = sqlite3.connect(path)
    c.executescript(DDL)
    for sql, filas in DATOS:
        c.executemany(sql, filas)
    c.commit()
    return c


def _cur(conn):
    return vc.CursorSqlite(conn)


class NormalizacionTest(unittest.TestCase):
    """`canon` aislada. Es la pieza donde un bug haría que TODO parezca bien."""

    def test_los_tres_tipos_del_mismo_numero_dan_lo_mismo(self):
        """El `int` de SQLite, el `float` de psycopg y un `Decimal`: mismo valor,
        misma forma canónica. Sin esto, toda tabla numérica daría distinto y la
        verificación sería ruido."""
        for v in (1500, 1500.0, Decimal("1500"), Decimal("1500.00")):
            self.assertEqual(vc.canon(v, "double precision"), "1500", repr(v))

    def test_los_tipos_distintos_NO_pueden_tapar_valores_distintos(self):
        """Lo de arriba al revés, que es lo que de verdad importa."""
        self.assertNotEqual(vc.canon(Decimal("1500.01"), "double precision"),
                            vc.canon(1500.0, "double precision"))

    def test_la_diferencia_MAS_CHICA_POSIBLE_ya_cuenta(self):
        """Un float de diferencia, que es lo más fino que existe.

        ⚠️ Ojo con "cambiar el último decimal a mano": `1500.0000000000001` **es**
        `1500.0`. La distancia entre dos floats vecinos cerca de 1500 es
        2,27e-13, así que 1e-13 queda por debajo de medio paso y Python lo
        redondea al mismo número. No hay nada que detectar ahí porque no hay
        diferencia. `math.nextafter` da la diferencia mínima que SÍ existe.
        """
        import math
        vecino = math.nextafter(1500.0, 2000.0)          # 1500.0000000000002
        self.assertNotEqual(vecino, 1500.0)
        self.assertNotEqual(vc.canon(vecino, "double precision"),
                            vc.canon(1500.0, "double precision"))

    def test_una_diferencia_por_debajo_de_un_float_NO_existe(self):
        """La contracara, escrita para que nadie la reporte como bug."""
        self.assertEqual(vc.canon(1500.0000000000001, "double precision"),
                         vc.canon(1500.0, "double precision"))

    def test_null_no_se_confunde_con_el_texto_None(self):
        self.assertNotEqual(vc.canon(None, "text"), vc.canon("None", "text"))

    def test_cero_negativo_es_cero(self):
        """-0.0 y 0.0 son el mismo dinero. Distinguirlos sería ruido."""
        self.assertEqual(vc.canon(-0.0, "double precision"),
                         vc.canon(0.0, "double precision"))

    def test_texto_en_columna_numerica_LEVANTA_en_vez_de_adivinar(self):
        with self.assertRaises(vc.ValorRaro):
            vc.canon("1500", "double precision")

    def test_decimales_en_columna_entera_LEVANTAN(self):
        with self.assertRaises(vc.ValorRaro):
            vc.canon(1.5, "bigint")
        self.assertEqual(vc.canon(1.0, "bigint"), "1")

    def test_hash_de_fila_no_confunde_los_cortes_entre_campos(self):
        """('ab','c') y ('a','bc') no pueden dar el mismo hash."""
        self.assertNotEqual(vc.hash_fila(["ab", "c"], ["text", "text"]),
                            vc.hash_fila(["a", "bc"], ["text", "text"]))


class CopiaSanaTest(unittest.TestCase):
    """Antes de las roturas: dos copias idénticas no pueden dar hallazgos."""

    def test_dos_copias_iguales_no_dan_hallazgos(self):
        o, d = _base(), _base()
        r = vc.comparar(_cur(o), _cur(d), ESQUEMA, revisar_secuencias=False)
        self.assertEqual(r["hallazgos"], [], r["hallazgos"])
        self.assertTrue(r["ok"])
        self.assertEqual(r["tablas_comparadas"], 4)


class LasCincoRoturasTest(unittest.TestCase):
    """Cada rotura por separado. Si alguna no salta, el copiador no se escribe."""

    def setUp(self):
        self.o, self.d = _base(), _base()

    def _hallazgos(self):
        return vc.comparar(_cur(self.o), _cur(self.d), ESQUEMA,
                           revisar_secuencias=False)["hallazgos"]

    # ── 1 ────────────────────────────────────────────────────────────────────
    def test_1_una_fila_de_menos(self):
        self.d.execute("DELETE FROM operations WHERE id=3")
        self.d.commit()
        h = self._hallazgos()
        self.assertTrue(any(x["nivel"] == 1 and x["tabla"] == "operations" for x in h), h)
        # y tiene que verse TAMBIÉN como plata: es la ganancia de un usuario
        plata = [x for x in h if x["nivel"] == 2 and x["que"] == "ganancia"]
        self.assertEqual(len(plata), 1, h)
        self.assertEqual(plata[0]["uid"], 2)
        self.assertEqual(plata[0]["diferencia"], "-4200.01")

    # ── 2 ────────────────────────────────────────────────────────────────────
    def test_2_un_numero_cambiado_en_el_ultimo_decimal(self):
        """La diferencia más chica que puede existir entre dos floats.

        Se usa `nextafter` y no un literal con muchos decimales: por debajo de un
        paso de float los dos literales son EL MISMO número y no habría nada que
        detectar (ver test_una_diferencia_por_debajo_de_un_float_NO_existe).
        """
        import math
        self.d.execute("UPDATE positions SET invested=? WHERE id=2",
                       (math.nextafter(88000.25, 99999.0),))
        self.d.commit()
        h = self._hallazgos()
        self.assertTrue(any(x["nivel"] == 1 and x["tabla"] == "positions" for x in h), h)
        self.assertTrue(any(x["nivel"] == 2 and x["que"] == "invertido" and x["uid"] == 1
                            for x in h), h)

    # ── 3 ────────────────────────────────────────────────────────────────────
    def test_3_un_Decimal_con_otro_valor_donde_iba_float(self):
        """Los tipos distintos NO pueden tapar valores distintos.

        Se simula el destino devolviendo `Decimal` (que es lo que da psycopg en
        una columna `numeric`) con un valor apenas distinto.
        """
        class CursorQueDevuelveDecimal:
            def __init__(self, conn):
                self._c = conn

            def execute(self, sql, params=()):
                filas = self._c.execute(sql, params).fetchall()
                return [tuple(Decimal(str(v)) + Decimal("0.01")
                              if isinstance(v, float) and v > 1000 else v
                              for v in f) for f in filas]

        h = vc.comparar(_cur(self.o), CursorQueDevuelveDecimal(self.d), ESQUEMA,
                        revisar_secuencias=False)["hallazgos"]
        self.assertTrue(any(x["nivel"] == 2 and x["que"] == "invertido" for x in h), h)

    def test_3b_un_Decimal_con_el_MISMO_valor_NO_salta(self):
        """La contracara: si el valor es el mismo, el tipo distinto no importa."""
        class CursorQueDevuelveDecimal:
            def __init__(self, conn):
                self._c = conn

            def execute(self, sql, params=()):
                filas = self._c.execute(sql, params).fetchall()
                return [tuple(Decimal(repr(v)) if isinstance(v, float) else v
                              for v in f) for f in filas]

        h = vc.comparar(_cur(self.o), CursorQueDevuelveDecimal(self.d), ESQUEMA,
                        revisar_secuencias=False)["hallazgos"]
        self.assertEqual(h, [], h)

    # ── 5 (la 4 es de Postgres y va en su propia clase) ──────────────────────
    def test_5_raw_json_vaciado_con_DELETE_en_vez_de_UPDATE(self):
        """Borrar la fila cascadea y se lleva su movimiento del ledger. El NIVEL 0
        lo ve porque cambia la CANTIDAD de filas."""
        antes = vc.foto_para_vaciado(_cur(self.o), ESQUEMA)
        self.o.execute("DELETE FROM import_raw_rows WHERE batch_id='b1'")
        self.o.commit()
        despues = vc.foto_para_vaciado(_cur(self.o), ESQUEMA)
        h = vc.comparar_vaciado(antes, despues)
        self.assertEqual(len(h), 1, h)
        self.assertEqual(h[0]["tabla"], "import_raw_rows")
        self.assertIn("NUNCA DELETE", h[0]["que"])
        self.assertEqual((h[0]["antes"], h[0]["despues"]), (3, 1))

    # ── 7: lo que NO tiene que saltar ────────────────────────────────────────
    def test_7_raw_json_vaciado_BIEN_con_UPDATE_no_da_hallazgos(self):
        antes = vc.foto_para_vaciado(_cur(self.o), ESQUEMA)
        self.o.execute("UPDATE import_raw_rows SET raw_json=''")
        self.o.commit()
        despues = vc.foto_para_vaciado(_cur(self.o), ESQUEMA)
        self.assertEqual(vc.comparar_vaciado(antes, despues), [])

    def test_7b_pero_tocar_OTRA_columna_del_mismo_UPDATE_si_salta(self):
        """El nivel 0 no mira sólo la cantidad de filas: `import_raw_rows` se
        digestea SIN `raw_json` justamente para ver si se tocó algo más."""
        antes = vc.foto_para_vaciado(_cur(self.o), ESQUEMA)
        self.o.execute("UPDATE import_raw_rows SET raw_json='', batch_id='ROTO'")
        self.o.commit()
        despues = vc.foto_para_vaciado(_cur(self.o), ESQUEMA)
        h = vc.comparar_vaciado(antes, despues)
        self.assertEqual(len(h), 1, h)
        self.assertIn("no eran raw_json", h[0]["que"])

    # ── 6: lo que NO tiene que saltar ────────────────────────────────────────
    def test_6_el_int_de_sqlite_contra_el_float_de_postgres_no_salta(self):
        """SQLite guarda en una columna REAL el entero que le metieron. Postgres
        devuelve 1500.0. Es el MISMO dinero: si esto saltara, la verificación
        marcaría todas las tablas y se volvería inútil."""
        self.o.execute("UPDATE positions SET invested=1500 WHERE id=1")     # int
        self.d.execute("UPDATE positions SET invested=1500.0 WHERE id=1")   # float
        self.o.commit()
        self.d.commit()
        self.assertEqual(self._hallazgos(), [])

    # ── extras: cosas que el nivel 1 tiene que ver y el nivel 2 no ───────────
    def test_un_id_cambiado_lo_ve_el_nivel_1(self):
        """Cambiar un id no mueve ningún total: es exactamente lo que el nivel 2
        no puede ver y el nivel 1 sí."""
        self.d.execute("UPDATE operations SET id=99 WHERE id=3")
        self.d.commit()
        h = self._hallazgos()
        self.assertTrue(any(x["nivel"] == 1 and x["tabla"] == "operations" for x in h), h)
        self.assertFalse([x for x in h if x["nivel"] == 2], h)

    def test_un_email_cambiado_lo_ve_el_nivel_1(self):
        """Una columna que ningún total suma."""
        self.d.execute("UPDATE users SET email='otro@x.test' WHERE id=1")
        self.d.commit()
        h = self._hallazgos()
        self.assertTrue(any(x["nivel"] == 1 and x["tabla"] == "users" for x in h), h)

    def test_dos_errores_opuestos_NO_se_netean(self):
        """EL motivo de comparar por usuario y no en total.

        A ana le sacamos 1000 y a beto le agregamos 1000: el total global da
        idéntico. Si la verificación mirara el total, esto pasaría de largo.
        """
        self.d.execute("UPDATE positions SET invested=invested-1000 WHERE id=1")
        self.d.execute("UPDATE positions SET invested=invested+1000 WHERE id=4")
        self.d.commit()
        h = [x for x in self._hallazgos() if x["nivel"] == 2 and x["que"] == "invertido"]
        self.assertEqual(sorted(x["uid"] for x in h), [1, 2], h)
        self.assertEqual(sorted(x["diferencia"] for x in h), ["-1000", "1000"])


@unittest.skipUnless(os.environ.get("PG_DSN_VERIF"),
                     "necesita PG_DSN_VERIF (una base Postgres APARTE de la de la suite)")
class ContraPostgresDeVerdadTest(unittest.TestCase):
    """Los niveles que sólo existen en Postgres, y el cruce real entre motores."""

    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.psycopg = psycopg
        cls.dsn = os.environ["PG_DSN_VERIF"]

    def setUp(self):
        self.pg = self.psycopg.connect(self.dsn, autocommit=True)
        self.pg.execute("DROP SCHEMA IF EXISTS vtest CASCADE")
        self.pg.execute("CREATE SCHEMA vtest")
        self.pg.execute("SET search_path = vtest")
        self.pg.execute("""
            CREATE TABLE users (
              id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, email text)""")
        self.pg.execute("""
            CREATE TABLE positions (
              id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
              user_id bigint, broker text, asset text, is_cash bigint,
              quantity double precision, invested double precision,
              commissions double precision)""")
        self.pg.execute("""
            CREATE TABLE operations (
              id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
              user_id bigint, asset text, pnl_usd double precision)""")
        self.pg.execute("""
            CREATE TABLE import_raw_rows (
              id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
              batch_id text, raw_json text)""")
        for sql, filas in DATOS:
            for f in filas:
                self.pg.execute(sql.replace("?", "%s"), f)
        self.sq = _base()

    def tearDown(self):
        self.pg.execute("DROP SCHEMA IF EXISTS vtest CASCADE")
        self.pg.close()
        self.sq.close()

    def _setval_todas(self):
        for t in ("users", "positions", "operations", "import_raw_rows"):
            self.pg.execute(
                f"SELECT setval(pg_get_serial_sequence('{t}','id'), "
                f"COALESCE((SELECT MAX(id) FROM {t}), 1))")

    def test_el_esquema_se_lee_de_postgres_con_sus_tipos(self):
        esq = vc.esquema_pg(vc.CursorPg(self.pg))
        self.assertEqual(set(esq), set(ESQUEMA))
        self.assertEqual(dict(esq["positions"])["invested"], "double precision")
        self.assertEqual(dict(esq["positions"])["user_id"], "bigint")

    def test_copia_sana_entre_MOTORES_DISTINTOS_no_da_hallazgos(self):
        """El caso base de verdad: sqlite3 devuelve int/float, psycopg devuelve lo
        suyo, y la comparación tiene que dar limpia igual."""
        self._setval_todas()
        esq = vc.esquema_pg(vc.CursorPg(self.pg))
        r = vc.comparar(_cur(self.sq), vc.CursorPg(self.pg), esq)
        self.assertEqual(r["hallazgos"], [], r["hallazgos"])

    # ── 4 ────────────────────────────────────────────────────────────────────
    def test_4_secuencia_sin_setval(self):
        """Sin `setval()`, la secuencia arranca en 1 y el próximo alta choca contra
        un id que ya existe. No lo ve ningún digest ni ningún total."""
        esq = vc.esquema_pg(vc.CursorPg(self.pg))
        h = vc.comparar(_cur(self.sq), vc.CursorPg(self.pg), esq)["hallazgos"]
        n3 = [x for x in h if x["nivel"] == 3]
        self.assertEqual(sorted(x["tabla"] for x in n3),
                         ["import_raw_rows", "operations", "positions", "users"], h)
        self.assertTrue(all(x["proximo_id"] <= x["max_id"] for x in n3), n3)

    def test_4b_con_setval_el_nivel_3_queda_limpio(self):
        self._setval_todas()
        esq = vc.esquema_pg(vc.CursorPg(self.pg))
        h = vc.comparar(_cur(self.sq), vc.CursorPg(self.pg), esq)["hallazgos"]
        self.assertEqual([x for x in h if x["nivel"] == 3], [], h)

    def test_4c_y_el_proximo_alta_de_verdad_no_choca(self):
        """La prueba directa: después del setval, insertar sin id tiene que dar un
        id nuevo. Es lo que el nivel 3 predice."""
        self._setval_todas()
        nuevo = self.pg.execute(
            "INSERT INTO users (email) VALUES ('nuevo@x.test') RETURNING id").fetchone()[0]
        self.assertGreater(nuevo, 2)

    def test_el_esquema_REAL_de_58_tablas_no_tiene_ningun_tipo_desconocido(self):
        """La guarda contra el futuro.

        Hoy `schema_pg.sql` usa exactamente TRES tipos —text, bigint y double
        precision— y la normalización los conoce a los tres. El día que alguien
        agregue una columna `numeric`, `boolean` o `timestamptz`, este test avisa
        ANTES de que la verificación la normalice mal en silencio. Que es
        justamente el modo de falla que haría que una copia rota parezca sana.
        """
        import collections
        raiz = os.path.dirname(HERE)
        with self.psycopg.connect(self.dsn, autocommit=True) as c:
            c.execute("DROP SCHEMA IF EXISTS vreal CASCADE")
            c.execute("CREATE SCHEMA vreal")
            c.execute("SET search_path = vreal")
            sql = open(os.path.join(raiz, "schema_pg.sql"), encoding="utf-8").read()
            for s in [x.strip() for x in sql.split(";") if x.strip()]:
                c.execute(s)
            esq = vc.esquema_pg(vc.CursorPg(c))
            tipos = collections.Counter(t for cols in esq.values() for _, t in cols)
            c.execute("DROP SCHEMA IF EXISTS vreal CASCADE")

        self.assertEqual(len(esq), 58, f"cambió la cantidad de tablas: {len(esq)}")
        self.assertEqual(set(tipos), {"text", "bigint", "double precision"},
                         f"apareció un tipo nuevo en el esquema: {dict(tipos)}. "
                         f"Revisá que `canon` lo normalice bien ANTES de copiar.")
        for t in tipos:
            muestra = "x" if t == "text" else 1
            vc.canon(muestra, t)          # no puede levantar ValorRaro

    def test_una_fila_de_menos_en_postgres_se_ve_entre_motores(self):
        self._setval_todas()
        self.pg.execute("DELETE FROM operations WHERE id=3")
        esq = vc.esquema_pg(vc.CursorPg(self.pg))
        h = vc.comparar(_cur(self.sq), vc.CursorPg(self.pg), esq)["hallazgos"]
        self.assertTrue(any(x["nivel"] == 1 and x["tabla"] == "operations" for x in h), h)
        self.assertTrue(any(x["nivel"] == 2 and x["que"] == "ganancia" for x in h), h)


if __name__ == "__main__":
    unittest.main()
