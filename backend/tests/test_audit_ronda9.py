"""Novena ronda: el bug vive en la ARISTA, no en el punto.

Las ocho rondas anteriores razonaron punto por punto: ¿esta FILA es medición o
contabilidad? El defecto no vivía ahí. Vivía en el SEGMENTO entre dos puntos.

Un tramo que une un punto valuado al costo con uno valuado a mercado no
representa un movimiento de la cartera: representa un CAMBIO DE REGLA. Da igual
cómo se etiqueten los extremos, cómo se pinten, o qué diga el header.

Y por eso estos tests miran EL ÍNDICE DIBUJADO. La ronda 8 dejó el header en "—"
—`dietz` y `serie_medible` sí respetaban la regla— mientras el gráfico dibujaba
la caída del 47,26% del caso 452 igual que antes. Un test que sólo mire `twr`
pasa con el gráfico roto: es exactamente lo que pasó.
"""
import datetime as _d
import json
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main
import twr


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
            (f"r9-{id(self)}@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,'IOL','AL30',0,1,100,'2026-01-01')",
            (self.uid,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def recon(self, d, v, cov):
        """Una foto RECONSTRUIDA. Con cobertura baja su `total_value` ES EL COSTO:
        lo que no se pudo precear entra con unrealized 0."""
        hold = json.dumps([{"asset": "AL30", "value_usd": v, "al_costo": cov < 0.9}])
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, mtm_coverage, holdings_json) "
            "VALUES (?,?,?,?,0,'mtm_backfill',?,?)",
            (self.uid, d, float(v), float(v), cov, hold))
        self.conn.commit()

    def cron(self, d, v):
        """Una MEDICIÓN real, a mercado."""
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,0,'cron',1200,'[]')", (self.uid, d, float(v), float(v)))
        self.conn.commit()

    def importado(self, d, v):
        """La cadena contable copiada por el import."""
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source) VALUES (?,?,?,?,0,'import')",
            (self.uid, d, float(v), float(v)))
        self.conn.commit()


class Caso452EnElGraficoTest(_Base):
    """B-1 · La ronda 8 reimprimió el caso 452 EN EL GRÁFICO.

    Los números son los reales de /api/admin/diagnose-reportes-basis?user_id=452:
    las fotos valen 139.571 porque es EL COSTO (cobertura 0,05) y la medición del
    cron vale 73.604 porque es MERCADO. La caída del 47% ES la diferencia entre
    las dos reglas — no es algo que le haya pasado a la cartera.
    """
    COSTO = 139570.56
    MERCADO = 73604.02

    def _cartera_452(self):
        for d in ("2026-04-30", "2026-05-31", "2026-06-30", "2026-07-31"):
            self.recon(d, self.COSTO, 0.05)
        self.cron("2026-08-24", self.MERCADO)
        return twr.curva_indexada(self.conn, self.uid)

    def test_la_linea_NO_cae_47_por_ciento(self):
        """EL CRITERIO DE ACEPTACIÓN. Mira el índice DIBUJADO, no el header.

        ⚠️ RONDA 10 · ESTE TEST AFIRMABA DE MENOS. Decía `assertGreaterEqual(index,
        0.99)`, que es un piso de UN SOLO LADO: lo satisface una implementación que
        rebasee TODO a 1,0 y dibuje plana una cartera que subió 20%. Ahora se
        afirma la forma EXACTA, que es lo que se quería decir.
        """
        c = self._cartera_452()
        # ⚠️ RONDA 11 · LOS 5 PUNTOS VUELVEN A LA CURVA. La ronda 10 filtraba la
        # curva a una sola base, y eso le borraba la historia al que tiene la
        # cartera mayormente al costo — con cobertura 0,61, la mediana real del
        # padrón, 12 meses desaparecían del gráfico. Esconder puntos nunca fue la
        # respuesta. Lo que impide leer el salto es que las dos series NO SE TOQUEN:
        # cada base tiene su propia cadena y su propio `segmento`.
        self.assertEqual(len(c["curva"]), 5, "el usuario perdió su historia")
        # NINGÚN punto dibuja la caída del 47%: cada base arranca en 1,0 y la
        # contable está plana.
        for p in c["curva"]:
            self.assertGreaterEqual(p["index"], 0.99)
            self.assertLessEqual(p["index"], 1.01)
        # las dos bases están en segmentos distintos
        self.assertEqual(len({p["segmento"] for p in c["curva"]}), 2)
        # …y en la banda tampoco: plana, la contabilidad no se movió
        self.assertEqual([round(p["value_no_medible"], 2) for p in c["contable"]],
                         [self.COSTO] * 4)

    def test_una_cartera_que_subio_NO_se_dibuja_plana(self):
        """La contracara del test de arriba, y la que faltaba: si la forma real
        sube, el índice dibujado tiene que subir. Sin esto, rebasear todo a 1,0
        pasaba el criterio."""
        for d, v in (("2026-01-31", 1000.0), ("2026-02-28", 1100.0),
                     ("2026-03-31", 1200.0)):
            self.recon(d, v, 0.97)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertEqual([round(p["index"], 4) for p in c["curva"]], [1.0, 1.1, 1.2])

    def test_el_header_sigue_diciendo_nada(self):
        c = self._cartera_452()
        self.assertIsNone(c["twr"])
        self.assertIsNone(c["drawdown_maximo"])
        self.assertIsNone(c["drawdown_maximo_pico"])

    def test_el_segmento_se_corta_donde_cambia_la_regla(self):
        """En ESTIMADO las dos bases están en la misma serie interna: los ids de
        segmento tienen que separarlas igual."""
        for d in ("2026-04-30", "2026-05-31", "2026-06-30", "2026-07-31"):
            self.recon(d, self.COSTO, 0.05)
        self.cron("2026-08-24", self.MERCADO)
        c = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_ESTIMADO)
        por_base = {}
        for t in c["tramos"]:
            for q in t:
                por_base.setdefault(q["base"], set())
        self.assertEqual(len(por_base), 2)          # hay dos reglas en juego
        # y ninguna serie dibujada mezcla las dos (ver NingunSegmentoUneDosBasesTest)

    def test_el_usuario_SIGUE_VIENDO_su_historia(self):
        """⚠️ NO se resuelve escondiendo los puntos: eso es la ronda 7 al revés.
        Las 4 fotos siguen en pantalla —en la banda, con su propio eje en dólares
        crudos— que hasta la ronda 9 salía VACÍA justo para el usuario que la
        necesitaba."""
        c = self._cartera_452()
        self.assertEqual([p["date"] for p in c["contable"]],
                         ["2026-04-30", "2026-05-31", "2026-06-30", "2026-07-31"])

    def test_y_la_banda_no_se_lee_como_una_caida_del_47(self):
        """La banda es SÓLO la cadena contable: la medición a mercado no entra, así
        que adentro de la banda no hay ningún escalón entre reglas."""
        c = self._cartera_452()
        # ⚠️ `value_no_medible`: en la banda el número crudo tampoco se llama `value`
        # (ronda 11). Es la colección que existe PARA lo que no mide.
        for q in c["contable"]:
            self.assertNotIn("value", q)
        valores = [p["value_no_medible"] for p in c["contable"]]
        self.assertEqual(valores, [self.COSTO] * 4)      # plana, en su propia escala
        self.assertNotIn(self.MERCADO, valores)


class NingunSegmentoUneDosBasesTest(_Base):
    """EL INVARIANTE, sobre carteras distintas. Es la regla en una oración:
    un segmento vale cuando sus dos extremos están valuados con la MISMA regla."""

    def _assert_invariante(self, c, quien):
        prev = None
        for p in c["curva"]:
            if prev is not None and prev["segmento"] == p["segmento"]:
                self.assertEqual(
                    prev["base"], p["base"],
                    f"{quien}: el segmento {p['segmento']} une "
                    f"{prev['base']}({prev['date']}) con {p['base']}({p['date']})")
            prev = p

    def test_reconstruido_al_costo_y_despues_el_cron(self):
        self.recon("2026-04-30", 139570.56, 0.05)
        self.cron("2026-05-14", 73604.02)
        self._assert_invariante(twr.curva_indexada(self.conn, self.uid), "452")

    def test_la_cadena_contable_en_el_medio_de_las_mediciones(self):
        self.cron("2026-06-01", 100000.0)
        self.importado("2026-06-15", 180000.0)
        self.cron("2026-06-20", 98000.0)
        for modo in (twr.MODO_CERTERO, twr.MODO_ESTIMADO):
            with self.subTest(modo=modo):
                self._assert_invariante(
                    twr.curva_indexada(self.conn, self.uid, modo=modo), modo)

    def test_la_reconstruccion_SE_PARTE_por_la_cobertura(self):
        """⚠️ RONDA 11 · ESTE TEST AFIRMA UNA PÉRDIDA CONOCIDA, A PROPÓSITO.

        La ronda 10 hizo que la base saliera de la MEDIANA de la serie para no
        partir el gráfico cuando la cobertura oscila alrededor del piso. Arregló el
        dibujo y rompió algo peor: la MISMA fila de cobertura 0,05 —y también una de
        0,00— quedaba ASCENDIDA a 'mercado' si el resto de la serie tenía cobertura
        alta, y con eso volvían el pico fabricado, el "Mes difícil — −47.3%" de
        Reportes y el −47,26% del informe FIRMADO. Además la respuesta pasaba a
        depender de qué ventana pidió el lector y de si había llegado un mes nuevo.

        Así que la base volvió a ser POR FILA y ahora va ESTAMPADA. El precio es
        éste, y se afirma acá para que se vea cuánto cuesta y nadie lo "arregle"
        volviendo a la mediana sin saber qué se lleva puesto.

        La causa de la fragmentación NO es la base: es que al saltear un mes no-apto
        la distancia APTO-A-APTO pasa de ~30 a ~61 días y cruza `MAX_HUECO_DIAS`,
        así que la serie se parte. Ahí es donde habría que mirar si algún día se
        quiere recuperar esto — no en la base.
        """
        self.recon("2026-01-31", 1000.0, 0.95)
        self.recon("2026-02-28", 1100.0, 0.95)
        self.recon("2026-03-31", 1200.0, 0.10)
        self.recon("2026-04-30", 1300.0, 0.10)
        c = twr.curva_indexada(self.conn, self.uid)
        self._assert_invariante(c, "cobertura mixta")
        # las dos coberturas bajas NUNCA son aptas, esté donde esté la mediana
        bajas = [p for p in c["curva"] if p["date"] >= "2026-03-31"]
        self.assertTrue(all(not p["apto"] for p in bajas))
        self.assertTrue(all(p["base"] == twr.VALUADO_AL_COSTO for p in bajas))
        # y las cuatro se SIGUEN VIENDO
        self.assertEqual(len(c["curva"]), 4)

    def test_la_cartera_que_gano_30_por_ciento_paga_el_precio(self):
        """El costo medido de la decisión de arriba, con números.

        Con la mediana: 1 segmento, +30,00% dibujado y publicado.
        Sin la mediana: la serie se parte y no se publica. El usuario SIGUE VIENDO
        sus 7 puntos —eso no se negocia— pero la línea no cuenta la historia
        completa. Es una pérdida real y está acá para que se pueda medir.
        """
        for d, v, cob in (("2026-01-31", 10000, 0.95), ("2026-02-28", 10500, 0.93),
                          ("2026-03-31", 11000, 0.88), ("2026-04-30", 11500, 0.91),
                          ("2026-05-31", 12000, 0.94), ("2026-06-30", 12500, 0.87),
                          ("2026-07-31", 13000, 0.92)):
            self.recon(d, float(v), cob)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertEqual(len(c["curva"]), 7, "los 7 puntos se siguen viendo")
        self.assertIsNone(c["twr"])              # el precio
        self.assertEqual(c["motivo"], "serie_partida")
        # …pero ni una sola fila bajo el piso quedó apta
        for p in c["curva"]:
            if p["base"] == twr.VALUADO_AL_COSTO:
                self.assertFalse(p["apto"])


class LaEtiquetaEsDelSegmentoTest(_Base):
    """B-3 · la medición real salía marcada como estimada."""

    def test_la_medicion_del_cron_no_es_una_estimacion(self):
        """`twr.py` marcaba `estimado=True` en el punto del cron porque el tramo
        ANTERIOR no medía. Que el tramo no se pueda medir no convierte la foto en
        estimada: la etiqueta es del SEGMENTO, no del punto."""
        for d in ("2026-04-30", "2026-05-31", "2026-06-30", "2026-07-31"):
            self.recon(d, 139570.56, 0.05)
        self.cron("2026-08-24", 73604.02)
        c = twr.curva_indexada(self.conn, self.uid)
        medicion = c["curva"][-1]
        self.assertEqual(medicion["clase"], twr.MEDICION)
        self.assertTrue(medicion["apto"])
        self.assertFalse(medicion["estimado"])

    def test_pero_ningun_punto_no_apto_deja_de_estar_marcado(self):
        """Lo que la ronda 7 ganó no se toca."""
        for d in ("2026-04-30", "2026-05-31"):
            self.recon(d, 139570.56, 0.05)
        self.cron("2026-08-24", 73604.02)
        self.importado("2026-08-31", 180000.0)
        for modo in (twr.MODO_CERTERO, twr.MODO_ESTIMADO):
            c = twr.curva_indexada(self.conn, self.uid, modo=modo)
            malos = [p["date"] for p in c["curva"] if not p["apto"] and not p["estimado"]]
            self.assertEqual(malos, [], f"{modo}: {malos}")


class ElSextoLectorTest(_Base):
    """El barrido "quién MÁS lee este dato". `/api/snapshots` se había quedado con
    `clase in BASE_MERCADO` pelado, sin el piso de cobertura."""

    def test_la_lista_y_la_curva_coinciden_con_cobertura_baja(self):
        from fastapi.testclient import TestClient
        self.recon("2026-04-30", 139570.56, 0.05)
        self.recon("2026-05-31", 139570.56, 0.05)
        self.cron("2026-06-30", 73604.02)
        _s = twr.serie_medible(self.conn, self.uid)
        curva = {p["date"]: True for p in _s["medibles"]}
        curva.update({p["date"]: False for p in _s["no_medibles"]})
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        try:
            filas = TestClient(main.app).get("/api/snapshots?days=3650").json()
        finally:
            main.app.dependency_overrides.clear()
        lista = {f["date"]: f["apto"] for f in filas}
        self.assertEqual(curva, lista)
        # Y en concreto: la foto valuada 95% al costo no es apta en NINGUNO.
        self.assertFalse(lista["2026-04-30"])

    def test_una_reconstruccion_a_precio_real_si_es_apta_en_los_dos(self):
        """⚠️ RONDA 10 · decía "en los dos" y sólo consultaba `/api/snapshots`.
        Ahora consulta LOS DOS, que es lo que el nombre promete."""
        from fastapi.testclient import TestClient
        self.recon("2026-04-30", 1000.0, 0.97)
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        try:
            filas = TestClient(main.app).get("/api/snapshots?days=3650").json()
        finally:
            main.app.dependency_overrides.clear()
        self.assertTrue(filas[0]["apto"])
        self.assertFalse(filas[0]["sintetico"])
        # …y LA CURVA, que es la otra mitad de "los dos".
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual([p["date"] for p in s["medibles"]], ["2026-04-30"])
        self.assertEqual(s["no_medibles"], [])


class LaBaseEsUnaFuncionSolaTest(_Base):
    """La tabla completa, para que se lea de un vistazo y no haya que deducirla."""

    def test_la_tabla(self):
        M, C = twr.VALUADO_A_MERCADO, twr.VALUADO_AL_COSTO
        for clase, cob, esperado in (
            (twr.MEDICION,        None, M),   # el cron: posiciones × precio
            (twr.INTRADIA,        None, M),   # el browser: media rueda, pero precio
            (twr.RECONSTRUIDO,    1.00, M),
            (twr.RECONSTRUIDO,    0.90, M),   # justo en el piso
            (twr.RECONSTRUIDO,    0.89, C),
            (twr.RECONSTRUIDO,    0.05, C),   # el caso 452
            (twr.RECONSTRUIDO,    None, C),   # sin cobertura no se puede afirmar
            (twr.SINTETICO_COSTO, None, C),
            (twr.INDETERMINADO,   None, C),
        ):
            with self.subTest(clase=clase, cobertura=cob):
                self.assertEqual(twr.base_de(clase, cob), esperado)


if __name__ == "__main__":
    unittest.main()
