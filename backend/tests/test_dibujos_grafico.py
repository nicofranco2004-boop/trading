"""Los dibujos a mano del gráfico de la ficha (líneas de tendencia y
horizontales), guardados en la cuenta para verlos en todos los dispositivos
(Nico, 24/10). Por HTTP, como los manda la pantalla (frontend/src/utils/dibujos.js):

  · se guardan y se leen por activo y moneda; la lista vacía los borra;
  · son de cada persona: otro no los ve, y un asesor mirando a un cliente
    guarda los SUYOS, no le escribe al cliente;
  · lo que no es un dibujo se rechaza (y una fila rota guardada no rompe la ficha);
  · el borrado de cuenta se los lleva (la columna se llama `user_id`).
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import uuid

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402  (conftest ya seteó DB_PATH temporal)

H = {"id": "h1", "tipo": "horizontal", "precio": 210.5}
T = {"id": "t1", "tipo": "tendencia",
     "a": {"d": "2026-03-02", "mas": 0, "precio": 180.25},
     "b": {"d": "2026-10-22", "mas": 7, "precio": 240.0}}


def _usuario(conn, email, tier=None):
    cur = conn.execute(
        "INSERT INTO users (email, name, password_hash, tier, approved) VALUES (?, ?, 'x', ?, 1)",
        (email, email.split("@")[0], tier))
    return cur.lastrowid


class DibujosGraficoTest(unittest.TestCase):

    def setUp(self):
        tag = uuid.uuid4().hex[:10]
        conn = main.get_db()
        try:
            self.yo = _usuario(conn, f"yo-{tag}@rendi.test")
            self.otro = _usuario(conn, f"otro-{tag}@rendi.test")
            conn.commit()
        finally:
            conn.close()
        self.http = TestClient(main.app)

    def _h(self, uid=None, cliente=None):
        h = {"Authorization": f"Bearer {main.create_token(uid or self.yo)}"}
        if cliente is not None:
            h["X-Rendi-Client-Id"] = str(cliente)
        return h

    def _leer(self, asset="AAPL", moneda="usd", **kw):
        r = self.http.get(f"/api/tecnico/{asset}/dibujos?moneda={moneda}", headers=self._h(**kw))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["dibujos"]

    def _guardar(self, lista, asset="AAPL", moneda="usd", notas=True, posiciones=True, **kw):
        # `notas` y `posiciones`: las marcas de la pantalla que las conoce (la de hoy).
        return self.http.put(f"/api/tecnico/{asset}/dibujos?moneda={moneda}",
                             json={"dibujos": lista, **({"notas": True} if notas else {}),
                                   **({"posiciones": True} if posiciones else {})}, headers=self._h(**kw))

    def _asesor_de_yo(self):
        conn = main.get_db()
        try:
            asesor = _usuario(conn, f"asesor-{uuid.uuid4().hex[:8]}@rendi.test", tier="advisor")
            conn.execute("UPDATE users SET managed_by = ? WHERE id = ?", (asesor, self.yo))
            conn.execute(
                "INSERT INTO advisor_clients (advisor_uid, client_uid, link_type, permission, status, label) "
                "VALUES (?, ?, 'managed', 'read_write', 'active', 'Yo')", (asesor, self.yo))
            conn.commit()
        finally:
            conn.close()
        return asesor

    def test_se_guardan_y_vuelven_tal_cual(self):
        self.assertEqual(self._leer(), [])
        r = self._guardar([H, T])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["dibujos"], 2)
        self.assertEqual(self._leer(), [H, T])
        # Guardar reemplaza la lista entera (la pantalla la manda completa).
        self._guardar([T])
        self.assertEqual(self._leer(), [T])

    def test_por_activo_y_por_moneda(self):
        self._guardar([H], asset="aapl")                   # el símbolo, en mayúsculas
        self.assertEqual(self._leer(asset="AAPL"), [H])
        self.assertEqual(self._leer(asset="AAPL", moneda="ars"), [])
        self.assertEqual(self._leer(asset="GGAL"), [])
        self._guardar([T], moneda="ars")
        self.assertEqual(self._leer(moneda="ars"), [T])
        self.assertEqual(self._leer(), [H])

    def test_la_lista_vacia_los_borra(self):
        self._guardar([H, T])
        self.assertEqual(self._guardar([]).status_code, 200)
        self.assertEqual(self._leer(), [])
        conn = main.get_db()
        try:
            n = conn.execute("SELECT COUNT(*) FROM dibujos_grafico WHERE user_id = ?", (self.yo,)).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(n, 0, "no queda una fila con []")

    def test_son_de_cada_persona(self):
        self._guardar([H])
        self.assertEqual(self._leer(uid=self.otro), [])
        self._guardar([T], uid=self.otro)
        self.assertEqual(self._leer(), [H])

    def test_un_asesor_mirando_a_un_cliente_guarda_los_suyos(self):
        asesor = self._asesor_de_yo()
        self._guardar([H])                                  # los del cliente, hechos por él
        r = self._guardar([T], uid=asesor, cliente=self.yo)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._leer(uid=asesor, cliente=self.yo), [T])
        self.assertEqual(self._leer(), [H], "el asesor le pisó los dibujos al cliente")

    def test_fibonacci_y_elliott_a_mano(self):
        fib = {"id": "f1", "tipo": "fibonacci", "a": T["a"], "b": T["b"]}
        ell = {"id": "e1", "tipo": "elliott",
               "puntos": [{"d": f"2026-0{m}-01", "mas": 0, "precio": 100.0 + m * 10} for m in range(1, 10)]}
        r = self._guardar([fib, ell])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._leer(), [fib, ell])
        # Un conteo que va por la onda 1 (dos toques) también vale.
        corto = {**ell, "id": "e2", "puntos": ell["puntos"][:2]}
        self.assertEqual(self._guardar([corto]).status_code, 200)
        for malo in ([{**ell, "puntos": ell["puntos"][:1]}],                       # sólo el 0
                     [{**ell, "puntos": ell["puntos"] + ell["puntos"][:1]}],       # más de A-B-C
                     [{"id": "f", "tipo": "fibonacci", "a": T["a"]}],              # sin el final del tramo
                     [{**ell, "puntos": [*ell["puntos"][:2], {"d": "x", "mas": 0, "precio": 1}]}]):
            self.assertEqual(self._guardar(malo).status_code, 422, malo)

    def test_extension_y_las_dos_formas_de_elliott(self):
        p = lambda m, x: {"d": f"2026-0{m}-01", "mas": 0, "precio": x}
        ext = {"id": "x1", "tipo": "extension", "a": p(1, 100.0), "b": p(2, 150.0), "c": p(3, 130.0)}
        imp = {"id": "i1", "tipo": "elliott", "forma": "impulso", "puntos": [p(m, 100.0 + m) for m in range(1, 7)]}
        cor = {"id": "c1", "tipo": "elliott", "forma": "correccion", "puntos": [p(m, 100.0 + m) for m in range(1, 5)]}
        self.assertEqual(self._guardar([ext, imp, cor]).status_code, 200)
        self.assertEqual(self._leer(), [ext, imp, cor])
        for malo in ([{**ext, "c": None}],                                          # le falta el retroceso
                     [{**imp, "puntos": imp["puntos"] + imp["puntos"][:1]}],        # un impulso con 7
                     [{**cor, "puntos": cor["puntos"] + cor["puntos"][:1]}],        # una corrección con 5
                     [{**imp, "forma": "triangulo"}]):
            self.assertEqual(self._guardar(malo).status_code, 422, malo)

    def test_canal_y_pincel(self):
        # El canal paralelo y el pincel (Nico, 29/10). El pincel lleva la
        # fracción del lugar (`f`) para que el trazo no quede en escalones.
        p = lambda m, x, **kw: {"d": f"2026-0{m}-01", "mas": 0, "precio": x, **kw}
        canal = {"id": "k1", "tipo": "canal", "a": p(1, 100.0), "b": p(2, 120.0), "ancho": -8.5}
        trazo = {"id": "p1", "tipo": "pincel", "puntos": [p(1, 100.0, f=0.25), p(1, 101.0, f=0.75), p(2, 99.0)]}
        self.assertEqual(self._guardar([canal, trazo]).status_code, 200)
        self.assertEqual(self._leer(), [canal, trazo])
        largo = {**trazo, "puntos": [p(1, 100.0 + k / 10) for k in range(200)]}
        self.assertEqual(self._guardar([largo]).status_code, 200, "200 puntos, el tope")
        for malo in ([{**canal, "ancho": 0}],                                       # sin ancho no es canal
                     [{**canal, "b": None}],
                     [{**trazo, "puntos": trazo["puntos"][:1]}],                    # un punto no es un trazo
                     [{**largo, "puntos": largo["puntos"] + largo["puntos"][:1]}],  # 201: más del tope
                     [{**trazo, "puntos": [p(1, 100.0, f=1.0), p(2, 99.0)]}]):      # la fracción es < 1
            self.assertEqual(self._guardar(malo).status_code, 422, malo)

    def test_el_color_de_cada_dibujo(self):
        # Nico, 29/10: el color que elegís queda guardado en el dibujo.
        con_color = {**H, "id": "c1", "color": "ambar"}
        self.assertEqual(self._guardar([con_color, H]).status_code, 200)
        self.assertEqual(self._leer(), [con_color, H])
        for malo in ("#ff0000", "magenta", ""):            # sólo los de la lista (un hex no sigue al tema)
            self.assertEqual(self._guardar([{**H, "color": malo}]).status_code, 422, malo)

    def test_las_notas_de_texto(self):
        # Nico, 30/10: «compré acá por el balance», en un día y un precio.
        nota = {"id": "n1", "tipo": "nota", "a": T["a"], "texto": "compré acá por el balance"}
        self.assertEqual(self._guardar([H, nota]).status_code, 200)
        self.assertEqual(self._leer(), [H, nota])
        # Lo que escribís vuelve tal cual: emojis, comillas, HTML (la pantalla lo
        # muestra como texto) y dos renglones.
        raro = {**nota, "id": "n2", "color": "rosa",
                "texto": 'Ojo 🚀👨‍👩‍👧 «el balance» "dijo" <b>no</b> & \'ya\'\nsegundo renglón'}
        self.assertEqual(self._guardar([raro]).status_code, 200)
        self.assertEqual(self._leer(), [raro])
        # Hasta 280 letras: un emoji cuenta una (como la pantalla).
        for ok in ("x" * 280, "🚀" * 280):
            self.assertEqual(self._guardar([{**nota, "texto": ok}]).status_code, 200, len(ok))
            self.assertEqual(self._leer()[0]["texto"], ok)
        for malo in ([{**nota, "texto": "x" * 281}],
                     [{**nota, "texto": ""}],                                       # sin texto no se guarda
                     [{**nota, "texto": "  \n\t "}],
                     [{k: v for k, v in nota.items() if k != "texto"}],
                     [{k: v for k, v in nota.items() if k != "a"}],                 # sin día ni precio
                     [{**nota, "texto": 5}],
                     [{**nota, "a": {**T["a"], "precio": 0}}]):
            self.assertEqual(self._guardar(malo).status_code, 422, malo)
        # Lo invisible se limpia: caracteres de control, el salto de Windows,
        # el tab, renglones vacíos de más y espacios en las puntas.
        self._guardar([{**nota, "texto": "  a\x00b\x07\r\nc\td\n\n\n\n\ne  "}])
        self.assertEqual(self._leer()[0]["texto"], "ab\nc d\n\ne")
        # Otro dibujo no guarda texto suelto.
        self._guardar([{**H, "texto": "no es una nota"}])
        self.assertEqual(self._leer(), [H])
        # Una nota que no se ve (sólo espacios raros o marcas invisibles) sería
        # una banderita vacía: no se guarda. El U+0085 (pegado de Windows o un
        # PDF) y la marca BOM se sacan, igual que en la pantalla.
        for invisible in ("\u200b", "\u200b \u2060", "\x85", "\ufeff", "\u00a0\u3000"):
            self.assertEqual(self._guardar([{**nota, "texto": invisible}]).status_code, 422, repr(invisible))
        self._guardar([{**nota, "texto": "\x85\ufeffhola\x85"}])
        self.assertEqual(self._leer()[0]["texto"], "hola")

    def test_una_nota_con_medio_emoji_no_rompe_la_ficha(self):
        # Un texto cortado a la mitad de un emoji llega con una «mitad» suelta.
        # Si se guardara así, la respuesta no se podría escribir y la ficha
        # perdería todos los dibujos de ese activo.
        cuerpo = ('{"dibujos": [{"id": "h1", "tipo": "horizontal", "precio": 210.5},'
                  ' {"id": "n1", "tipo": "nota", "a": {"d": "2026-03-02", "mas": 0, "precio": 180.25},'
                  ' "texto": "subió \\ud83d"}], "notas": true}')
        r = self.http.put("/api/tecnico/AAPL/dibujos?moneda=usd", content=cuerpo,
                          headers={**self._h(), "Content-Type": "application/json"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([d.get("texto") for d in self._leer()], [None, "subió"])

    def test_una_pantalla_vieja_no_borra_tus_notas(self):
        # Una pestaña abierta antes de que existieran las notas las descarta al
        # leer y manda la lista entera sin ellas: las guardadas se quedan.
        nota = {"id": "n1", "tipo": "nota", "a": T["a"], "texto": "compré acá"}
        self._guardar([H, nota])
        self.assertEqual(self._guardar([T], notas=False).status_code, 200)
        self.assertEqual(self._leer(), [T, nota])
        # Ni borrar todo desde ahí se lleva las notas; desde la de hoy, sí.
        self._guardar([], notas=False)
        self.assertEqual(self._leer(), [nota])
        self._guardar([])
        self.assertEqual(self._leer(), [])

    def test_la_posicion_con_su_objetivo_y_su_stop(self):
        # Como la de TradingView (Nico, 03/11): entrada, borde, objetivo y stop.
        compra = {"id": "p1", "tipo": "posicion", "lado": "compra", "a": T["a"],
                  "b": {"d": "2026-04-01", "mas": 0, "precio": 180.25}, "objetivo": 200.0, "stop": 170.5}
        venta = {**compra, "id": "p2", "lado": "venta", "objetivo": 170.5, "stop": 200.0}
        r = self._guardar([compra, venta])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._leer(), [compra, venta])
        # Al revés (el stop del lado del objetivo) o sin stop, no.
        for mala in ({**compra, "stop": 190.0}, {**venta, "objetivo": 210.0},
                     {k: v for k, v in compra.items() if k != "stop"}, {**compra, "lado": "larga"}):
            self.assertEqual(self._guardar([mala]).status_code, 422, mala)
        # El objetivo y el stop son de la posición: en otro dibujo no se guardan.
        self._guardar([{**H, "objetivo": 300.0, "lado": "compra"}])
        self.assertEqual(self._leer(), [H])

    def test_una_pantalla_vieja_no_borra_tus_posiciones(self):
        # Una pestaña abierta antes de que existieran las posiciones las
        # descarta al leer y manda la lista entera sin ellas: se quedan.
        pos = {"id": "p1", "tipo": "posicion", "lado": "compra", "a": T["a"],
               "b": {"d": "2026-04-01", "mas": 0, "precio": 180.25}, "objetivo": 200.0, "stop": 170.5}
        self._guardar([H, pos])
        self.assertEqual(self._guardar([T], posiciones=False).status_code, 200)
        self.assertEqual(self._leer(), [T, pos])
        self._guardar([], posiciones=False)
        self.assertEqual(self._leer(), [pos])
        self._guardar([])
        self.assertEqual(self._leer(), [])

    def test_mirando_a_un_cliente_tus_notas_no_se_ven_ni_se_tocan(self):
        asesor = self._asesor_de_yo()
        mia = {"id": "n1", "tipo": "nota", "a": T["a"], "texto": "Juan compró acá por el balance"}
        self._guardar([H, mia], uid=asesor)                      # en su propia cuenta
        # Mirando a un cliente: sus líneas sí, la nota no.
        self.assertEqual(self._leer(uid=asesor, cliente=self.yo), [H])
        # Lo que guarda ahí no borra la nota (ni agrega notas nuevas).
        otra = {**mia, "id": "n2", "texto": "nota sobre el cliente"}
        self.assertEqual(self._guardar([T, otra], uid=asesor, cliente=self.yo).status_code, 200)
        self.assertEqual(self._leer(uid=asesor), [T, mia])
        # Y el cliente no ve nada del asesor.
        self.assertEqual(self._leer(), [])

    def test_las_notas_son_tuyas_y_no_son_lineas_con_aviso(self):
        nota = {"id": "n1", "tipo": "nota", "a": T["a"], "texto": "mi idea"}
        self._guardar([nota, H])
        self.assertEqual(self._leer(uid=self.otro), [])
        # «Alertas → Una línea que dibujaste» no ofrece las notas.
        r = self.http.get("/api/tecnico/AAPL/lineas?moneda=usd", headers=self._h())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([x["id"] for x in r.json()["lineas"]], ["h1"])
        # Ni se les puede poner un aviso.
        r = self.http.post("/api/alerts", headers=self._h(), json={
            "kind": "tecnica", "senal": "linea", "symbol": "AAPL", "currency": "USD", "dibujo": "n1",
            "channel": "both", "repeat": "once"})
        self.assertNotEqual(r.status_code, 200, r.text)

    def test_lo_que_no_es_un_dibujo_se_rechaza(self):
        malos = [
            [{"id": "x", "tipo": "flecha", "precio": 1}],
            [{"id": "x", "tipo": "horizontal"}],                                   # sin precio
            [{"id": "x", "tipo": "horizontal", "precio": -5}],
            [{"id": "x", "tipo": "tendencia", "a": T["a"]}],                       # sin el segundo punto
            [{**T, "a": {"d": "ayer", "mas": 0, "precio": 1}}],
            [{**T, "b": {**T["b"], "mas": -1}}],
            [{"id": "<script>", "tipo": "horizontal", "precio": 1}],
            [{**H, "id": f"h{k}"} for k in range(61)],                             # más del tope
        ]
        for lista in malos:
            r = self._guardar(lista)
            self.assertEqual(r.status_code, 422, f"{lista[:1]} → {r.status_code}")
        # Infinito no entra como precio (el JSON de Python lo deja pasar como
        # «Infinity»). Se rechaza; la respuesta de error de FastAPI no sabe
        # escribir el Infinity que recibió y sale 500 (igual en toda la app):
        # lo que importa acá es que no se guarde.
        sin_explotar = TestClient(main.app, raise_server_exceptions=False)
        r = sin_explotar.put("/api/tecnico/AAPL/dibujos?moneda=usd", headers={**self._h(), "Content-Type": "application/json"},
                             content='{"dibujos": [{"id": "x", "tipo": "horizontal", "precio": Infinity}]}')
        self.assertNotEqual(r.status_code, 200)
        self.assertEqual(self._leer(), [])
        self.assertEqual(self.http.put("/api/tecnico/A%2FB/dibujos", json={"dibujos": [H]},
                                       headers=self._h()).status_code in (400, 404), True)

    def test_sin_sesion_no(self):
        self.assertEqual(self.http.get("/api/tecnico/AAPL/dibujos").status_code, 401)
        self.assertEqual(self.http.put("/api/tecnico/AAPL/dibujos", json={"dibujos": [H]}).status_code, 401)

    def test_una_fila_rota_guardada_no_rompe_la_ficha(self):
        conn = main.get_db()
        try:
            conn.execute("INSERT INTO dibujos_grafico (user_id, asset, moneda, datos) VALUES (?, 'AAPL', 'usd', ?)",
                         (self.yo, json.dumps([H, {"id": "x", "tipo": "flecha"}, "basura"])))
            conn.execute("INSERT INTO dibujos_grafico (user_id, asset, moneda, datos) VALUES (?, 'GGAL', 'usd', '{roto')",
                         (self.yo,))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self._leer(), [H])
        self.assertEqual(self._leer(asset="GGAL"), [])

    def test_el_borrado_de_cuenta_los_alcanza(self):
        conn = main.get_db()
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(dibujos_grafico)").fetchall()]
        finally:
            conn.close()
        self.assertIn("user_id", cols)


if __name__ == "__main__":
    unittest.main()
