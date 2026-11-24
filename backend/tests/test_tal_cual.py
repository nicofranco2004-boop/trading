"""«Mover a otro broker» → «Tal cual»: la posición estaba cargada en el broker equivocado.

EL CASO (24/11/2026, el primer usuario que probó el pase). Con el plan gratis (un solo
broker) cargó todo en Santander; ahora quiere poner MSFT en Galicia «tal cual», como
si siempre hubiera estado ahí. El pase no sirve: anota una salida a valor de mercado y
deja una pérdida en el broker viejo.

LA PRUEBA CENTRAL es un diferencial contra el camino canónico: una cuenta carga MSFT en
Cocos y la pasa tal cual a Balanz; su gemela la carga en Balanz desde el principio. Lo
que la persona ve —los lotes, el efectivo de cada broker, el resumen mensual de cada
broker y Movimientos— tiene que ser IDÉNTICO. Todo por las puertas de producción
(`POST /api/positions`, `POST /api/positions/tal-cual`, `GET /api/monthly`,
`GET /api/movements`), con un token real y el interruptor prendido en la base.

Corre con: cd backend && python3 -m pytest tests/test_tal_cual.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import main  # noqa: E402
from importing import traspaso_a_mano  # noqa: E402
from test_mover_entre_brokers import _Vista  # noqa: E402

FECHA = "2025-03-10"
_SIN = {"id", "user_id", "created_at", "updated_at"}


class TalCual(_Vista):
    maxDiff = None

    # ── las puertas ─────────────────────────────────────────────────────────────
    def _body(self, origen="Cocos", destino="Balanz", asset="MSFT", moneda="ARS"):
        return {"broker_origen": origen, "broker_destino": destino, "asset": asset,
                "moneda": moneda}

    def _vista_tc(self, **kw):
        return self.http.post("/api/positions/tal-cual/vista-previa", json=self._body(**kw),
                              headers=self.h)

    def _pasar(self, **kw):
        r = self.http.post("/api/positions/tal-cual", json=self._body(**kw), headers=self.h)
        self._esperar_reconstruccion()
        return r

    # ── lo que ve la persona ────────────────────────────────────────────────────
    def _efectivo(self):
        conn = main.get_db()
        try:
            return {r["broker"]: round(float(r["invested"] or 0), 4) for r in conn.execute(
                "SELECT broker, invested FROM positions WHERE user_id=? AND is_cash=1 "
                "AND ABS(COALESCE(invested, 0)) > 1e-9", (self.uid,))}
        finally:
            conn.close()

    def _mensual_limpio(self):
        """A 4 decimales: el alta anota el depósito automático en dólares redondeado a 4
        (371,3733) y el recálculo que corre al borrar lo reescribe sin redondear
        (371,3733075…). Pasa igual al borrar y cargar a mano; no es de esta función."""
        return {k: {c: (round(v, 4) if isinstance(v, float) else v)
                    for c, v in f.items() if c not in _SIN}
                for k, f in self._mensual().items()}

    def _movimientos(self):
        r = self.http.get("/api/movements", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        filas = r.json()
        filas = filas.get("movements", filas) if isinstance(filas, dict) else filas
        return sorted(
            [tuple(sorted((k, v) for k, v in f.items()
                          if k not in _SIN and not k.endswith("_id") and k != "key"
                          and not isinstance(v, (dict, list))))
             for f in filas], key=repr)

    def _estado(self, asset="MSFT"):
        return {"Cocos": self._sin_ids("Cocos", asset), "Balanz": self._sin_ids("Balanz", asset),
                "efectivo": self._efectivo(), "mensual": self._mensual_limpio(),
                "movimientos": self._movimientos()}

    def _como_gemela(self, fn):
        """Corre `fn` en una cuenta gemela (los mismos dos brokers) y devuelve su estado."""
        propio = (self.uid, self.h)
        self.uid, self.h = self._usuario_nuevo()
        try:
            fn()
            self._esperar_reconstruccion()
            return self._estado()
        finally:
            self._esperar_reconstruccion()
            self.uid, self.h = propio

    # ── las pruebas ─────────────────────────────────────────────────────────────
    def test_tal_cual_es_como_haberla_cargado_ahi_desde_el_principio(self):
        """El caso del usuario: 20 MSFT cargadas a mano en Cocos (sin depositar antes:
        Rendi anota solo el depósito que la paga). Pasadas tal cual a Balanz, la cuenta
        queda igual a la gemela que las cargó en Balanz: Cocos sin rastro, ni pérdida ni
        pase; Balanz con su fecha y su costo de compra."""
        gemela = self._como_gemela(
            lambda: self._lote_a_mano("Balanz", "MSFT", 20, 19200.0, FECHA))
        # Lo que se compara no está vacío: el lote, el depósito automático del mes y
        # sus renglones en Movimientos.
        self.assertEqual(len(gemela["Balanz"]), 1)
        self.assertGreater(gemela["mensual"][("Balanz", 2025, 3)]["deposits"], 300)
        self.assertGreaterEqual(len(gemela["movimientos"]), 2)
        self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA)

        v = self._vista_tc()
        self.assertEqual(v.status_code, 200, v.text)
        v = v.json()
        self.assertIsNone(v["freno"])
        self.assertEqual((v["origen"], v["destino"], v["cantidad"]), ("Cocos", "Balanz", 20))
        self.assertEqual(v["lotes"], [{"fecha_compra": FECHA, "cantidad": 20,
                                       "costo": 384000.0, "moneda": "ARS"}])

        r = self._pasar()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["mensaje"], traspaso_a_mano.MSG_TAL_CUAL_HECHO.format(
            cantidad="20", asset="MSFT", origen="Cocos", destino="Balanz"))
        self.assertEqual(self._estado(), gemela)
        self.assertEqual(self._estado()["Cocos"], [])

    def test_con_deposito_propio_la_plata_vuelve_al_broker_viejo(self):
        """Si la compra se pagó con un depósito cargado en Cocos, ese depósito sigue en
        Cocos (es lo que la persona anotó) y la plata vuelve a su efectivo; en Balanz la
        compra anota el depósito que la paga. Es lo mismo que borrar y cargar a mano."""
        r = self.http.post("/api/cash/flow", headers=self.h, json={
            "broker_name": "Cocos", "direction": "deposit", "amount": 500000,
            "currency": "ARS", "date": "2025-03-01", "tc_blue": 1100})
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA)
        self.assertEqual(self._efectivo()["Cocos"], 116000.0)
        r = self._pasar()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._efectivo(), {"Cocos": 500000.0})
        self.assertEqual(len(self._sin_ids("Balanz", "MSFT")), 1)

    def test_ida_y_vuelta_deja_todo_como_estaba(self):
        """Para volver atrás, lo mismo al revés: la cuenta queda como antes de pasarla."""
        self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA)
        self._lote_a_mano("Cocos", "MSFT", 5, 21000.0, "2025-05-02")
        antes = self._estado()
        self.assertEqual(self._pasar().status_code, 200)
        self.assertEqual(len(self._sin_ids("Balanz", "MSFT")), 2)
        r = self._pasar(origen="Balanz", destino="Cocos")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._estado(), antes)

    def test_despues_se_puede_borrar_y_el_borrado_interno_no_se_deshace_suelto(self):
        """La compra en Balanz queda con su receta: el tacho la borra (antes, cambiar el
        broker editando dejaba el borrado en 409 para siempre). Y el borrado de Cocos que
        hizo el «tal cual» no se puede deshacer solo: duplicaría la compra."""
        self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA)
        self.assertEqual(self._pasar().status_code, 200)
        conn = main.get_db()
        try:
            token = conn.execute(
                "SELECT token FROM deleted_ops_journal WHERE user_id=? AND kind='manual_position'",
                (self.uid,)).fetchone()["token"]
        finally:
            conn.close()
        r = self.http.post(f"/api/operations/undo/{token}", headers=self.h)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("se pasó tal cual", r.json()["detail"])
        self.assertEqual(len(self._sin_ids("Balanz", "MSFT")), 1)
        self.assertEqual(self._sin_ids("Cocos", "MSFT"), [])

        lote = self._lote(broker="Balanz", asset="MSFT")
        r = self.http.delete(f"/api/positions/{lote['id']}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self.assertEqual(self._sin_ids("Balanz", "MSFT"), [])
        self.assertEqual(self._efectivo(), {})

    def _fotos(self):
        conn = main.get_db()
        try:
            return sorted(
                (r["date"], round(float(r["total_value"]), 4), round(float(r["net_deposited"]), 4))
                for r in conn.execute(
                    "SELECT date, total_value, net_deposited FROM snapshots WHERE user_id=? "
                    "AND fx_to_usd_blue IS NOT NULL AND date < ?", (self.uid, main._iso_today())))
        finally:
            conn.close()

    def test_las_fotos_medidas_de_cada_noche_no_cambian(self):
        """La historia diaria de la cuenta sale de las fotos que el cron midió cada noche
        (valor y aportado del TOTAL). Pasar tal cual no cambia el total, así que esas
        fotos tienen que quedar iguales. Hoy nada del camino las toca (el borrado de algo
        cargado a mano no corrige fotos: sólo lo importado, `_MEDICION_KINDS`; medido el
        24/11 con una sonda). Esta prueba fija que siga así: si un día el borrado a mano
        empezara a corregirlas, el «tal cual» tendría que saltearse esa corrección."""
        self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA)
        conn = main.get_db()
        try:
            for d, valor, aportado in (("2025-04-15", 400.0, 371.3733), ("2025-06-30", 420.0, 371.3733),
                                       ("2025-12-31", 450.0, 371.3733)):
                conn.execute(
                    """INSERT INTO snapshots (user_id, date, total_value, total_invested,
                           net_deposited, fx_to_usd_blue, holdings_json, source, base, apto)
                       VALUES (?,?,?,?,?,1200,'[{"asset": "MSFT", "value_usd": 1}]',
                               'cron','mercado',1)""",
                    (self.uid, d, valor, aportado, aportado))
            conn.commit()
        finally:
            conn.close()
        antes = self._fotos()
        self.assertEqual(len(antes), 3)
        self.assertEqual(self._pasar().status_code, 200)
        self.assertEqual(self._fotos(), antes)

    def test_frena_sin_tocar_nada(self):
        """Lo que no se puede pasar tal cual: la vista previa avisa con el mismo texto que
        el confirmar, y el confirmar no escribe nada."""
        lote = self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA)
        self._editar(lote, buy_price=19500.0, invested=390000.0)
        texto = traspaso_a_mano.MSG_TAL_CUAL_CAMBIO.format(asset="MSFT", broker="Cocos")
        self.assertEqual(self._vista_tc().json()["freno"], texto)
        antes = self._tablas()
        r = self._pasar()
        self.assertEqual((r.status_code, r.json()["detail"]), (409, texto))
        self.assertEqual(self._tablas(), antes)

    def test_lo_importado_no_se_pasa_tal_cual(self):
        """Lo que vino del archivo de un broker estaba en ese broker."""
        self._historia()
        texto = traspaso_a_mano.MSG_TAL_CUAL_IMPORTADO.format(asset="NVDA", broker="Cocos")
        self.assertEqual(self._vista_tc(asset="NVDA").json()["freno"], texto)
        antes = self._tablas()
        r = self._pasar(asset="NVDA")
        self.assertEqual((r.status_code, r.json()["detail"]), (409, texto))
        self.assertEqual(self._tablas(), antes)

    def test_interruptor_apagado_y_mismo_broker(self):
        self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA)
        r = self.http.post("/api/positions/tal-cual", json=self._body(destino="Cocos"),
                           headers=self.h)
        self.assertEqual(r.status_code, 400, r.text)
        self._interruptor(False)
        self.assertEqual(self._vista_tc().status_code, 403)
        self.assertEqual(self._pasar().status_code, 403)
