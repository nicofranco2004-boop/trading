"""El botón que mide el alcance real de la auditoría en producción.

Corre 13 consultas contra la base de PRODUCCIÓN. Los tests que importan no son
los de "devuelve algo": son los de que **no puede escribir** y **no puede filtrar
datos de nadie**.

Corre con: cd backend && python3 -m pytest tests/test_alcance_auditoria.py
"""
from __future__ import annotations
import os
import re
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from fastapi.testclient import TestClient

import alcance_auditoria as alc
import main


class TestNoPuedeEscribir(unittest.TestCase):
    """Corre contra producción: el guard es lo único que separa una medición de
    un accidente."""

    def test_las_13_consultas_son_select(self):
        secs = alc.secciones()
        self.assertEqual(len(secs), 14, "cambió la cantidad de consultas")
        alc._verificar_solo_lectura(secs)   # no tira

    def test_un_update_infiltrado_aborta_TODO(self):
        """Y aborta antes de ejecutar, no en la mitad."""
        con_bicho = alc.secciones() + [("Qx", "malicia", "UPDATE users SET is_admin=1")]
        with self.assertRaises(ValueError) as cm:
            alc._verificar_solo_lectura(con_bicho)
        self.assertIn("Qx", str(cm.exception))

    def test_tampoco_pasa_escondido_en_un_SELECT(self):
        for veneno in (
            "SELECT 1; DROP TABLE users",
            "WITH x AS (SELECT 1) INSERT INTO users VALUES (1)",
            "SELECT * FROM users; PRAGMA writable_schema=1",
        ):
            with self.assertRaises(ValueError, msg=veneno):
                alc._verificar_solo_lectura([("Qx", "t", veneno)])

    def test_una_palabra_prohibida_DENTRO_de_un_string_no_es_un_falso_positivo(self):
        # `op_type = 'Interés PF'` no tiene nada malo; `'... update ...'` tampoco.
        alc._verificar_solo_lectura(
            [("Qx", "t", "SELECT COUNT(*) FROM operations WHERE notes = 'update pendiente'")])


class TestElParserNoSeComeFiltros(unittest.TestCase):
    """El bug que publicó 679 usuarios donde había ~20: un `-- comentario` al
    final de una línea se tragaba el resto de la sentencia al unir líneas."""

    def test_un_comentario_inline_no_borra_lo_que_sigue(self):
        sql = ("-- Q9 · prueba\n"
               "SELECT COUNT(*) AS n FROM t\n"
               "WHERE a = 1   -- el lote se pagó en pesos\n"
               "  AND b = 2;  -- la cuenta es en dólares\n")
        (_sid, _t, sentencia), = alc.secciones(sql)
        self.assertIn("AND b = 2", sentencia)
        self.assertNotIn("--", sentencia)

    def test_Q1a_conserva_el_filtro_de_broker_en_dolares(self):
        q1a = next(q for sid, _t, q in alc.secciones() if sid == "Q1a")
        self.assertIn("IN ('USD','USDT')", q1a)
        # Y NO escondido detrás de un comentario: con el parser viejo el texto
        # seguía ahí, pero después de un `--`, o sea inerte.
        self.assertNotIn("--", q1a)


class TestNoFiltraDatosDeNadie(unittest.TestCase):
    """Las consultas devuelven agregados. Si alguien agrega una columna con un
    email o un user_id, esto se pone en rojo."""

    PROHIBIDAS = ("email", "password", "token", "nombre", "name")

    def test_ninguna_columna_publicada_identifica_a_una_persona(self):
        for sid, _t, sql in alc.secciones():
            for col in re.findall(r"AS\s+(\w+)", sql, re.I):
                for mala in self.PROHIBIDAS:
                    self.assertNotIn(mala, col.lower(), f"{sid} publica `{col}`")

    def test_cada_consulta_devuelve_UNA_fila_de_agregados(self):
        """La garantía es por CONSULTA, no por sección: Q4 y Q5 tienen dos cada
        una. Lo que no puede pasar es que una devuelva un listado —ahí habría una
        fila por usuario, que es justo lo que estas consultas no pueden publicar."""
        from collections import Counter
        por_seccion = Counter(sid for sid, _t, _q in alc.secciones())
        conn = main.get_db()
        self.addCleanup(conn.close)
        r = alc.informe(conn)
        for sid, filas in r["crudo"].items():
            if sid == "Q6b":
                continue   # agrupa por broker a propósito: una fila por broker, no por persona
            self.assertEqual(len(filas), por_seccion[sid],
                             f"{sid}: {len(filas)} filas para {por_seccion[sid]} consulta(s)")


class TestLaTraduccion(unittest.TestCase):
    """Cada número tiene que llegar como una pregunta que se entienda."""

    def setUp(self):
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        self.r = alc.informe(self.conn)

    def test_cada_hallazgo_trae_pregunta_numero_y_veredicto(self):
        self.assertEqual(len(self.r["hallazgos"]), len(alc.LECTURA))
        for h in self.r["hallazgos"]:
            self.assertTrue(h["pregunta"].endswith("?"), h["id"])
            self.assertIn(h["veredicto"], ("urgente", "mirar", "ok", "sin_dato"))
            self.assertTrue(h["que_significa"])

    def test_ninguna_columna_apunta_a_un_nombre_que_no_existe(self):
        """El bug que tuvo la primera versión: Q6 apuntaba a `usuarios`, que en
        esa consulta no existe, y el hallazgo salía 'sin dato' para siempre."""
        for h in self.r["hallazgos"]:
            self.assertNotEqual(h["veredicto"], "sin_dato",
                                f"{h['id']}: la columna que manda no existe en su consulta")

    def test_un_SUM_vacio_se_lee_como_cero_y_no_como_sin_dato(self):
        for h in self.r["hallazgos"]:
            self.assertIsNotNone(h["numero"], h["id"])

    def test_el_capital_tipeado_a_mano_es_el_urgente(self):
        """Es el único dato que no se recalcula: si se perdió, sólo vuelve de un
        backup. Tiene que salir como urgente apenas haya uno."""
        q2 = next(h for h in self.r["hallazgos"] if h["id"] == "Q2")
        self.assertIn("capital inicial", q2["pregunta"])
        veredicto = next(u for i, _c, _p, u, _s in alc.LECTURA if i == "Q2")
        self.assertEqual(veredicto(1), "urgente")
        self.assertEqual(veredicto(0), "ok")


class TestElEndpoint(unittest.TestCase):
    """Por HTTP, como lo usa el panel: el camino de producción entero."""

    def setUp(self):
        self.client = TestClient(main.app)
        conn = main.get_db()
        tag = str(id(self))
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, approved, is_admin) VALUES (?,'x',1,1)",
            (f"alcance-admin-{tag}@rendi.test",))
        self.admin = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, approved, is_admin) VALUES (?,'x',1,0)",
            (f"alcance-pelado-{tag}@rendi.test",))
        self.pelado = cur.lastrowid
        conn.commit(); conn.close()
        self.addCleanup(self._limpiar)

    def _limpiar(self):
        conn = main.get_db()
        conn.execute("DELETE FROM users WHERE id IN (?,?)", (self.admin, self.pelado))
        conn.commit(); conn.close()

    def _hdr(self, uid):
        return {"Authorization": f"Bearer {main.create_token(uid)}"}

    def test_un_usuario_comun_no_puede_verlo(self):
        r = self.client.get("/api/admin/alcance-auditoria", headers=self._hdr(self.pelado))
        self.assertIn(r.status_code, (401, 403))

    def test_sin_sesion_tampoco(self):
        r = self.client.get("/api/admin/alcance-auditoria")
        self.assertIn(r.status_code, (401, 403))

    def test_el_admin_recibe_las_preguntas_traducidas(self):
        r = self.client.get("/api/admin/alcance-auditoria", headers=self._hdr(self.admin))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(len(body["hallazgos"]), len(alc.LECTURA))
        self.assertEqual(
            set(body["resumen"]), {"urgentes", "a_mirar", "ok"})
        for h in body["hallazgos"]:
            self.assertTrue(h["pregunta"].endswith("?"))
            self.assertIsNotNone(h["numero"])

    def test_la_respuesta_no_lleva_datos_de_nadie(self):
        r = self.client.get("/api/admin/alcance-auditoria", headers=self._hdr(self.admin))
        cuerpo = r.text.lower()
        for mala in ("@rendi.test", "@gmail", "password", "user_id"):
            self.assertNotIn(mala, cuerpo, f"la respuesta filtra `{mala}`")

    def test_pide_admin(self):
        import inspect
        src = inspect.getsource(main.admin_alcance_auditoria)
        self.assertIn("get_admin_user", src, "el endpoint no exige admin")

    def test_el_sql_canonico_existe_donde_el_modulo_lo_busca(self):
        self.assertTrue(os.path.exists(alc.SQL_PATH),
                        f"no está el .sql en {alc.SQL_PATH} — el endpoint daría 500")

    def test_el_sql_vive_en_UN_solo_lugar(self):
        """No hay una segunda copia embebida en el módulo. Cuando había dos —el
        .sql y una copia en `1a-medir-alcance.py`— ya habían divergido."""
        src = open(os.path.join(BACKEND, "alcance_auditoria.py"), encoding="utf-8").read()
        self.assertNotIn("COUNT(DISTINCT", src, "el módulo tiene su propia copia del SQL")


if __name__ == "__main__":
    unittest.main()
