"""F6 — UN solo rendimiento acumulado, y que diga de dónde sale.

EL BUG
──────
Cuatro superficies —el Wrapped y los paquetes `insights_evolution`, `reports` y
`dashboard` de la IA— publicaban el rendimiento componiendo `monthly_entries` por
su cuenta, sin pasar por el motor.

MEDIDO sobre la copia de producción del 2026-08-16 (673 usuarios):

    publicaban un acumulado > 100 %      121 usuarios
    el peor                              +129.544 %   (uid 118)
    lo que el MOTOR dice del uid 118          +0,7 %

El motor no se equivocaba: no lo estaban llamando.

⚠️ Y AGREGARLE `leg_dudoso` A LA COMPOSICIÓN NO ALCANZABA — bajaba el peor a
+30.300 % — porque el defecto no es un mes malo suelto: la composición SALTEA el
mes que no puede medir y sigue encadenando desde la base ya achicada. Medido: al
uid 826 el guard SOLO le SUBÍA el número, de 884 % a 3.983 %. Un leg no creíble
CORTA EL TRAMO; estos lectores lo salteaban.

LA REGLA, decidida con el dueño: se mide a mercado cuando se puede; cuando no, se
publica la contabilidad **diciendo que es contabilidad** (`base`). Es el mismo
patrón que Reportes ya usa con su campo `basis`. Nadie pierde su número y nadie ve
un número sin saber de dónde sale.

LOS CUATRO GUARDS DE LA RAMA CONTABLE YA EXISTÍAN. No se inventó ninguno; faltaba
usarlos juntos: `retorno_mensual`, `leg_dudoso` (cortando el tramo),
`PISO_DENOMINADOR_USD` y `MAX_PNL_PCT`.

RESULTADO MEDIDO sobre los mismos 673 usuarios:

    rama          usuarios   el peor
    mercado            438     +96,6 %    (todos por debajo de 100 %)
    contable           170    +892,0 %    (cero por encima de 1000 %)
    sin número          65     —          (con `motivo` y `motivo_texto`)

Publican **608 contra los 575 de hoy**: el motor RESCATA a 65 que hoy no tienen
número, y los 65 que lo pierden son los de capital bajo el piso o porcentaje sobre
el techo — casos donde el número no significaba nada.

CUÁLES MIDEN
────────────
`ElPrimitivoTest` NO mide el bug (la función es nueva: contra el código viejo falla
con AttributeError). Miden los de `LosLectoresLoUsanTest`, que verifican que las
cuatro superficies dejaron de componer por su cuenta.

Corre con: cd backend && python3 -m pytest tests/test_rendimiento_publicable.py
"""
import unittest
import uuid

import main
import twr
from realized_pnl import MAX_PNL_PCT


class ElPrimitivoTest(unittest.TestCase):
    """`twr.rendimiento_publicable` — la regla. NO mide el bug (es nueva)."""

    def setUp(self):
        self.conn = main.get_db()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"pub-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
        self.conn.commit()

    def tearDown(self):
        try:
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM snapshots WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
        except Exception:
            pass
        self.conn.commit()
        self.conn.close()

    def me(self, y, m, ci, cf, dep=0.0, wd=0.0):
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio,"
            " capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized)"
            " VALUES (?,'global',?,?,?,?,?,?,0,0)", (self.uid, y, m, ci, cf, dep, wd))
        self.conn.commit()

    def test_devuelve_un_dict_con_la_procedencia_no_un_float(self):
        """LA FORMA es el arreglo. El informe lo pide así: "un primitivo que
        devuelva (r, motivo) y no un float pelado" — con un float, el llamador no
        tiene con qué decidir si publicarlo ni cómo etiquetarlo."""
        r = twr.rendimiento_publicable(self.conn, self.uid)
        self.assertIsInstance(r, dict)
        for k in ("pct", "base", "motivo", "motivo_texto", "meses"):
            self.assertIn(k, r)

    def test_sin_fotos_de_mercado_cae_a_CONTABLE_y_lo_DICE(self):
        """El caso mayoritario: 168 de los 202 que el motor no puede medir son
        `importado_sin_mediciones`. No se les saca el número: se etiqueta."""
        self.me(2025, 1, 1000, 1100)
        self.me(2025, 2, 1100, 1210)
        r = twr.rendimiento_publicable(self.conn, self.uid)
        self.assertEqual(r["base"], "contable")
        self.assertAlmostEqual(r["pct"], 21.0, places=0)     # 1,1 × 1,1 − 1
        self.assertIsNotNone(r["motivo"], "tiene que decir por qué no fue a mercado")
        self.assertIsNotNone(r["motivo_texto"], "y decirlo en castellano")

    def test_EL_TRAMO_SE_CORTA_no_se_saltea(self):
        """EL CORAZÓN DEL ARREGLO, con el caso real del uid 826.

        Una caída de 9.200 a 2.217 SIN flujo que la explique: `leg_dudoso` la marca.
        Saltear ese mes y seguir encadendo desde 2.217 da un acumulado INFLADO —
        medido en producción, le subía el número de 884 % a 3.983 %. Cortar el
        tramo publica sólo lo que pasó DESPUÉS de la caída, que es lo único que se
        puede afirmar.
        """
        self.me(2025, 1, 1000, 1100)          # +10 %
        self.me(2025, 2, 1100, 1210)          # +10 %
        self.me(2025, 3, 9200, 2217)          # la caída sin flujo → corta acá
        self.me(2025, 4, 2217, 2439)          # +10 %  ← el tramo que se publica
        self.me(2025, 5, 2439, 2683)          # +10 %
        r = twr.rendimiento_publicable(self.conn, self.uid)
        self.assertEqual(r["base"], "contable")
        # El ÚLTIMO tramo: 1,1 × 1,1 − 1 = 21 %. No los cuatro meses juntos (46 %).
        self.assertAlmostEqual(r["pct"], 21.0, places=0)
        self.assertEqual(r["meses"], 2, "publica sólo el tramo posterior al corte")

    def test_con_menos_de_cien_dolares_no_se_publica_un_porcentaje(self):
        """`PISO_DENOMINADOR_USD`, el guard que F4 ya había creado.

        Caso real (uid 956): la cartera va de US$13 a US$93 con todos los meses
        entre +1 % y +12 % —ninguno "dudoso"— y compone **+14.063 %**. Es
        aritméticamente correcto y no describe nada.
        """
        self.assertEqual(twr.PISO_DENOMINADOR_USD, 100)
        v = 13.0
        for m in range(1, 13):
            self.me(2025, m, v, v * 1.4)
            v *= 1.4
        r = twr.rendimiento_publicable(self.conn, self.uid)
        self.assertIsNone(r["pct"], "con US$13 de capital el % no significa nada")

    def test_y_con_capital_de_verdad_SI_se_publica(self):
        """El piso no puede tapar a quien sí tiene capital medible."""
        self.me(2025, 1, 5000, 5500)
        self.me(2025, 2, 5500, 6050)
        r = twr.rendimiento_publicable(self.conn, self.uid)
        self.assertIsNotNone(r["pct"])
        self.assertAlmostEqual(r["pct"], 21.0, places=0)

    def test_por_encima_del_techo_de_credibilidad_no_se_publica(self):
        """`MAX_PNL_PCT` — el mismo 1000 % que F4 propagó a las otras siete
        superficies. Acá se reusa la constante, no se copia el número."""
        self.assertEqual(MAX_PNL_PCT, 1000)
        v = 1000.0
        for m in range(1, 13):                 # +100 % por mes, todos creíbles solos
            self.me(2025, m, v, v * 2)
            v *= 2
        r = twr.rendimiento_publicable(self.conn, self.uid)
        self.assertIsNone(r["pct"], "4.095 % no es un rendimiento publicable")

    def test_sin_nada_cargado_no_inventa(self):
        r = twr.rendimiento_publicable(self.conn, self.uid)
        self.assertIsNone(r["pct"])
        self.assertIsNone(r["base"])

    def test_el_mes_de_alta_no_cuenta(self):
        """Lo hereda de `retorno_mensual`: con `capital_inicio` en 0 el 0,5 del
        flujo INFLA el mes (medido: 23,71 % contra 20,10 % real)."""
        self.me(2025, 1, 0, 1000, dep=1000)    # alta: no se mide
        self.me(2025, 2, 1000, 1100)           # +10 %
        r = twr.rendimiento_publicable(self.conn, self.uid)
        self.assertAlmostEqual(r["pct"], 10.0, places=0)
        self.assertEqual(r["meses"], 1)


class LosLectoresLoUsanTest(unittest.TestCase):
    """GUARD ESTRUCTURAL — lee CÓDIGO.

    El bug no fue que el cálculo estuviera mal: fue que cuatro superficies tenían
    el suyo. Un test de comportamiento pasa igual el día que aparezca la quinta.
    """

    LECTORES = ("wrapped.py", "ai/builders/insights_evolution.py",
                "ai/builders/reports.py", "ai/builders/dashboard.py")

    def test_ninguno_compone_monthly_entries_por_su_cuenta(self):
        import pathlib
        raiz = pathlib.Path(__file__).resolve().parent.parent
        culpables = []
        for rel in self.LECTORES:
            txt = (raiz / rel).read_text(encoding="utf-8", errors="ignore")
            for i, linea in enumerate(txt.splitlines(), 1):
                s = linea.strip()
                if s.startswith("#"):
                    continue
                # La firma de "me armo el acumulado yo": multiplicar (1 + retorno).
                if ("*= (1 + " in s or "*= (1+" in s) and "ret" in s:
                    culpables.append(f"{rel}:{i}  {s[:60]}")
        self.assertEqual(
            culpables, [],
            "estas superficies componen el rendimiento por su cuenta en vez de "
            "pedírselo a `twr.rendimiento_publicable`:\n" + "\n".join(culpables))

    def test_los_cuatro_piden_el_rendimiento_al_primitivo(self):
        import pathlib
        raiz = pathlib.Path(__file__).resolve().parent.parent
        faltan = [rel for rel in self.LECTORES
                  if "rendimiento_publicable" not in
                  (raiz / rel).read_text(encoding="utf-8", errors="ignore")]
        self.assertEqual(faltan, [],
                         "no usan el primitivo: " + ", ".join(faltan))


class LosChipsDelDashboardTest(unittest.TestCase):
    """`main._snapshot_delta` — los chips Δ1d / Δ7d / Δ30d, que el usuario ve TODOS
    LOS DIAS y que no tenian UN SOLO guard.

    MEDIDO sobre la copia de produccion del 2026-08-16, 794 usuarios con cinco o
    mas fotos:

                antes            despues
        Δ 1d      -8.093,1 %       100,0 %
        Δ 7d  -9.346.280,6 %       100,7 %
        Δ30d  -9.170.283,9 %       110,5 %

    No eran rendimientos: eran datos rotos. Al uid 329 el `net_deposited` le salta
    de -1.055.894 a +1.699.812.606 de un dia para el otro con la cartera quieta en
    18.400; el uid 412 tiene una foto donde la cartera vale -805.744.

    El costo: 3 o 4 usuarios por ventana se quedan sin chip. A cambio, nadie ve
    nueve millones por ciento.
    """

    def setUp(self):
        self.conn = main.get_db()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"chip-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
        self.conn.commit()

    def tearDown(self):
        try:
            self.conn.execute("DELETE FROM snapshots WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
        except Exception:
            pass
        self.conn.commit(); self.conn.close()

    def snap(self, d, valor, nd=0.0):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested,"
            " net_deposited, source, fx_to_usd_blue, holdings_json)"
            " VALUES (?,?,?,?,?,'cron',1200.0,'[]')", (self.uid, d, valor, valor, nd))
        self.conn.commit()

    def test_el_caso_del_uid_329_reproducido(self):
        """El `net_deposited` salta 1.700 millones con la cartera quieta. Antes
        publicaba -9.346.280,6 %."""
        self.snap("2026-08-01", 18499.68, nd=-1055894.40)
        self.snap("2026-08-08", 18323.55, nd=1699812606.06)
        r = main._snapshot_delta(self.conn, self.uid, 18323.55, "2026-08-08", 7,
                                 latest_netdep=1699812606.06)
        self.assertIsNone(r, "un salto de 1.700 millones sin cartera que lo explique")

    def test_el_caso_del_uid_412_reproducido(self):
        """La cartera pasa a valer -805.744. Antes publicaba -8.093,1 %."""
        self.snap("2026-07-14", 10080.49, nd=-827856.22)
        self.snap("2026-07-15", -805744.19, nd=-827856.22)
        r = main._snapshot_delta(self.conn, self.uid, -805744.19, "2026-07-15", 1,
                                 latest_netdep=-827856.22)
        self.assertIsNone(r, "una cartera no puede valer menos que nada")

    def test_un_dia_NORMAL_sigue_publicando(self):
        """El guard no puede tapar lo que esta bien: 10.000 -> 10.200 es +2 %."""
        self.snap("2026-07-14", 10000.0, nd=9000.0)
        self.snap("2026-07-15", 10200.0, nd=9000.0)
        r = main._snapshot_delta(self.conn, self.uid, 10200.0, "2026-07-15", 1,
                                 latest_netdep=9000.0)
        self.assertIsNotNone(r, "un dia normal tiene que seguir publicando")
        self.assertAlmostEqual(r["pct"], 2.0, places=1)

    def test_un_APORTE_grande_no_se_lee_como_rendimiento(self):
        """Lo que el chip ya hacia bien y tiene que seguir haciendo: descontar los
        flujos. Un deposito de 5.000 sobre 10.000 no es +50 %."""
        self.snap("2026-07-14", 10000.0, nd=9000.0)
        self.snap("2026-07-15", 15000.0, nd=14000.0)
        r = main._snapshot_delta(self.conn, self.uid, 15000.0, "2026-07-15", 1,
                                 latest_netdep=14000.0)
        if r is not None:
            self.assertLess(abs(r["pct"]), 5.0, "el aporte no es rendimiento")

    def test_usa_LA_MISMA_funcion_del_motor_no_una_copia(self):
        """GUARD: si el umbral cambia, tiene que cambiar en un solo lugar."""
        import pathlib as _pl
        src = (_pl.Path(__file__).resolve().parent.parent / "main.py").read_text(
            encoding="utf-8")
        i = src.index("def _snapshot_delta(")
        cuerpo = src[i:i + 6000]
        self.assertIn("leg_dudoso", cuerpo, "el chip perdió la cota de cordura")
        self.assertNotIn("SALTO_MAX_VECES =", cuerpo, "copió el umbral en vez de importarlo")


if __name__ == "__main__":
    unittest.main()
