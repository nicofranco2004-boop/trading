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

    # ── compras VIEJAS: cargadas antes del 06/08/2026, sin receta ────────────────
    # El 24/11 el usuario del caso no pudo pasar NINGUNA («En todas sale lo mismo»):
    # había cargado todo antes de esa fecha y el «tal cual» las frenaba como el tacho.
    # No se sabe con qué plata se pagaron, así que la plata pasa con ellas.

    def _hacer_vieja(self, lote):
        """Deja una compra como las de antes del 06/08/2026: sin receta, y su depósito
        automático sin renglón propio (el detalle de cada carga existe desde el 08/10):
        sólo en la suma del mes. Ninguna puerta las crea ya: se siembran."""
        conn = main.get_db()
        try:
            conn.execute("UPDATE positions SET undo_meta_json=NULL WHERE id=? AND user_id=?",
                         (lote["id"], self.uid))
            conn.execute("DELETE FROM flujos_a_mano WHERE user_id=? AND ref=?",
                         (self.uid, f"pos:{lote['id']}"))
            conn.commit()
        finally:
            conn.close()

    def _aportado(self, broker):
        """Depósitos menos retiros de todos los meses de un broker, en dólares, como los
        da /mensual."""
        return round(sum(float(f["deposits"] or 0) - float(f["withdrawals"] or 0)
                         for (b, _, _), f in self._mensual().items() if b == broker), 4)

    def _flujos(self, **donde):
        conn = main.get_db()
        try:
            q = "SELECT * FROM flujos_a_mano WHERE user_id=? AND anulado_at IS NULL"
            args = [self.uid]
            for k, v in donde.items():
                q += f" AND {k}=?"
                args.append(v)
            return [dict(r) for r in conn.execute(q + " ORDER BY id", args)]
        finally:
            conn.close()

    def _hecho_con_plata(self, origen="Cocos", destino="Balanz", cantidad="20"):
        return (traspaso_a_mano.MSG_TAL_CUAL_HECHO.format(
                    cantidad=cantidad, asset="MSFT", origen=origen, destino=destino)
                + " " + traspaso_a_mano.MSG_TAL_CUAL_PLATA.format(origen=origen, destino=destino))

    def test_compra_vieja_pasa_con_su_plata(self):
        """El caso del usuario: 20 MSFT cargadas en Cocos antes del 06/08 (Rendi anotó
        solo el depósito que las pagó). Pasan a Balanz igual que si las hubiera cargado
        ahí —el lote, el efectivo y el mes de Balanz quedan como en la gemela—; la plata
        sale de Cocos el día de compra (Cocos: sin compra, sin plata, sin pérdida) y el
        total aportado de la cuenta no cambia."""
        gemela = self._como_gemela(
            lambda: self._lote_a_mano("Balanz", "MSFT", 20, 19200.0, FECHA))
        self._hacer_vieja(self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA))
        total = self._aportado("global")
        self.assertGreater(total, 300)

        v = self._vista_tc()
        self.assertEqual(v.status_code, 200, v.text)
        self.assertEqual((v.json()["freno"], v.json()["plata_viaja"]), (None, True))
        r = self._pasar()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["mensaje"], self._hecho_con_plata())

        e = self._estado()
        self.assertEqual(e["Cocos"], [])
        self.assertEqual(e["Balanz"], gemela["Balanz"])
        self.assertEqual(e["efectivo"], gemela["efectivo"])
        self.assertEqual(e["mensual"][("Balanz", 2025, 3)], gemela["mensual"][("Balanz", 2025, 3)])
        self.assertEqual(self._aportado("Cocos"), 0)
        self.assertAlmostEqual(self._aportado("global"), total, places=4)
        # En Movimientos, la salida de Cocos con su motivo y el día de compra.
        retiro, = self._flujos(origen="tal_cual")
        self.assertEqual((retiro["broker"], retiro["direction"], retiro["fecha"],
                          retiro["monto_nativo"]), ("Cocos", "withdraw", FECHA, 384000.0))
        self.assertTrue(any("Se fue con una compra que pasaste «tal cual»" in repr(m)
                            for m in e["movimientos"]), e["movimientos"])
        # El aporte de Balanz quedó en la receta de la compra nueva: se va con ella.
        lote = self._lote(broker="Balanz", asset="MSFT")
        dep, = self._flujos(broker="Balanz")
        self.assertEqual((dep["origen"], dep["ref"], dep["fecha"]),
                         ("autodeposito", f"pos:{lote['id']}", FECHA))
        self.assertEqual(main.json.loads(lote["undo_meta_json"])["autodep"]["flujo_id"], dep["id"])

    def test_compra_vieja_ida_y_vuelta(self):
        """Volver con «tal cual» de Balanz a Cocos deja la compra en Cocos, Balanz limpio
        y lo aportado de cada broker como estaba."""
        self._hacer_vieja(self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA))
        lotes = self._sin_ids("Cocos", "MSFT")
        aportado = {b: self._aportado(b) for b in ("Cocos", "Balanz", "global")}
        self.assertEqual(self._pasar().status_code, 200)
        r = self._pasar(origen="Balanz", destino="Cocos")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._sin_ids("Cocos", "MSFT"), lotes)
        self.assertEqual((self._sin_ids("Balanz", "MSFT"), self._efectivo()), ([], {}))
        for b, antes in aportado.items():
            self.assertAlmostEqual(self._aportado(b), antes, places=4, msg=b)

    def test_una_vieja_y_una_nueva_del_mismo_activo(self):
        """Quien cargó antes y después del 06/08 tiene las dos clases en la misma fila de
        Cartera: pasan juntas, cada una con su regla, y ningún broker queda con plata
        suelta."""
        self._hacer_vieja(self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA))
        self._lote_a_mano("Cocos", "MSFT", 5, 21000.0, "2025-05-02")
        lotes = self._sin_ids("Cocos", "MSFT")
        total = self._aportado("global")
        r = self._pasar()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["mensaje"], self._hecho_con_plata(cantidad="25"))
        self.assertEqual(self._sin_ids("Balanz", "MSFT"), lotes)
        self.assertEqual((self._sin_ids("Cocos", "MSFT"), self._efectivo()), ([], {}))
        self.assertEqual(self._aportado("Cocos"), 0)
        self.assertAlmostEqual(self._aportado("global"), total, places=4)

    def test_compra_vieja_borrada_despues_se_lleva_su_plata(self):
        """Ya pasada, la compra tiene receta: el tacho de Balanz la borra y se lleva el
        aporte que la pagaba. No queda plata que no respalde nada en ningún broker."""
        self._hacer_vieja(self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA))
        self.assertEqual(self._pasar().status_code, 200)
        lote = self._lote(broker="Balanz", asset="MSFT")
        r = self.http.delete(f"/api/positions/{lote['id']}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion()
        self.assertEqual(self._efectivo(), {})
        self.assertEqual((self._aportado("Balanz"), self._aportado("Cocos")), (0, 0))

    def test_compra_vieja_no_usa_la_plata_que_ya_habia_en_el_destino(self):
        """La compra se paga con la plata que llega con ella, no con la que la persona
        ya tenía en Balanz."""
        r = self.http.post("/api/cash/flow", headers=self.h, json={
            "broker_name": "Balanz", "direction": "deposit", "amount": 500000,
            "currency": "ARS", "date": "2025-03-01", "tc_blue": 1100})
        self.assertEqual(r.status_code, 200, r.text)
        self._hacer_vieja(self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA))
        self.assertEqual(self._pasar().status_code, 200)
        self.assertEqual(self._efectivo(), {"Balanz": 500000.0})

    def test_compra_vieja_con_la_caja_del_destino_en_rojo(self):
        """Si la caja de Balanz está en rojo (pasa en un broker importado), entra además
        lo que falta, como lo anotaría el alta: un solo aporte, atado a la compra."""
        self._hacer_vieja(self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA))
        conn = main.get_db()
        try:
            conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity) "
                         "VALUES (?, 'Balanz', 'ARS', 1, -1000, 0)", (self.uid,))
            conn.commit()
        finally:
            conn.close()
        r = self._pasar()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._efectivo(), {})
        dep, = self._flujos(broker="Balanz")
        self.assertEqual(dep["monto_nativo"], 385000.0)
        lote = self._lote(broker="Balanz", asset="MSFT")
        self.assertEqual(main.json.loads(lote["undo_meta_json"])["autodep"]["native"], 385000.0)

    def test_la_salida_del_tal_cual_no_se_borra_suelta(self):
        """Borrar desde Movimientos la plata que salió de Cocos se la devolvería a Cocos
        mientras sigue en Balanz pagando la compra: la cuenta la tendría dos veces."""
        self._hacer_vieja(self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA))
        self.assertEqual(self._pasar().status_code, 200)
        retiro, = self._flujos(origen="tal_cual")
        antes = self._tablas()
        r = self.http.delete(f"/api/movements/mf-{retiro['id']}", headers=self.h)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("pasaste «tal cual»", r.json()["detail"])
        self.assertEqual(self._tablas(), antes)

    def test_el_tacho_sigue_sin_borrar_una_compra_vieja(self):
        """Lo nuevo es sólo del «tal cual»: el tacho no sabe con qué plata se pagó."""
        lote = self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA)
        self._hacer_vieja(lote)
        r = self.http.delete(f"/api/positions/{lote['id']}", headers=self.h)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(r.json()["detail"], main._MANUAL_LEGACY_MSG)

    def test_interruptor_apagado_y_mismo_broker(self):
        self._lote_a_mano("Cocos", "MSFT", 20, 19200.0, FECHA)
        r = self.http.post("/api/positions/tal-cual", json=self._body(destino="Cocos"),
                           headers=self.h)
        self.assertEqual(r.status_code, 400, r.text)
        self._interruptor(False)
        self.assertEqual(self._vista_tc().status_code, 403)
        self.assertEqual(self._pasar().status_code, 403)
