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

    def _guardar(self, lista, asset="AAPL", moneda="usd", **kw):
        return self.http.put(f"/api/tecnico/{asset}/dibujos?moneda={moneda}",
                             json={"dibujos": lista}, headers=self._h(**kw))

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
        self._guardar([H])                                  # los del cliente, hechos por él
        r = self._guardar([T], uid=asesor, cliente=self.yo)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._leer(uid=asesor, cliente=self.yo), [T])
        self.assertEqual(self._leer(), [H], "el asesor le pisó los dibujos al cliente")

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
