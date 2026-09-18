"""«¿Esta operación movió la plata de tu broker?» — para CUALQUIER operación.

La pregunta existía sólo para futuros. El pedido (2026-09-18) es que se haga
siempre, porque el desfasaje que arregla no es de los futuros: le pasa a
cualquier operación cuyo resultado ya esté en la cuenta y todavía no figure en
Rendi. El usuario elige, y las dos respuestas son válidas:

    No  → queda en el historial. El P&L cuenta; el efectivo no se toca.
    Sí  → además suma (o resta) el resultado al efectivo de ese broker.

El monto es el P&L, y eso vale para una operación común igual que para un
futuro: en un viaje de ida y vuelta la plata de la compra salió y volvió, así
que el efecto NETO sobre el saldo es exactamente el resultado.

Lo que este archivo vigila, más allá del alta:

  1. EL INTERRUPTOR SE DA VUELTA EN LA EDICIÓN. Antes el backend decidía sólo
     por la foto guardada en el alta: el check en modo edición era un adorno.

  2. PRENDERLO EN LA EDICIÓN TIENE QUE CAMBIAR LA FOTO DE REVERSO. Si no, el
     borrado posterior no devuelve la plata que la edición acreditó y quedan
     dólares fabricados. Es la trampa de siempre: el fix en un solo eslabón.

  3. LA MONEDA (audit 2026-09-18). Al efectivo se le aplica el monto CONVERTIDO
     a la moneda del broker, pero la foto guardaba sólo los dólares. Medido
     antes del fix, en un broker en pesos: el alta de US$100 acreditó 150.250
     pesos y el borrado devolvió 100 — 150.150 pesos fabricados. Con la pregunta
     abierta a todas las operaciones esto deja de ser el caso raro del futuro de
     Rofex y pasa a ser Balanz, IOL y Cocos.
"""
import json
import unittest
import uuid

import main


def _cliente():
    from fastapi.testclient import TestClient
    return TestClient(main.app)


def _usuario(currency="USD", saldo=1000.0, broker="Schwab"):
    conn = main.get_db()
    uid = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
        (f"mv-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
    conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                 (uid, broker, currency))
    conn.execute("""INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity)
                    VALUES (?,?,?,1,?,?)""",
                 (uid, broker, 'ARS' if currency == 'ARS' else 'USD', saldo, saldo))
    conn.commit()
    conn.close()
    return uid, {"Authorization": f"Bearer {main.create_token(uid)}"}


def _cash(uid, broker="Schwab"):
    conn = main.get_db()
    r = conn.execute(
        "SELECT COALESCE(invested,0) c FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
        (uid, broker)).fetchone()
    conn.close()
    return float(r["c"]) if r else 0.0


def _pnl_realizado(uid):
    conn = main.get_db()
    r = conn.execute("SELECT COALESCE(SUM(pnl_realized),0) p FROM monthly_entries "
                     " WHERE user_id=? AND broker='global'", (uid,)).fetchone()
    conn.close()
    return float(r["p"])


def _aportado(uid):
    conn = main.get_db()
    r = conn.execute("SELECT COALESCE(SUM(deposits),0) d FROM monthly_entries "
                     " WHERE user_id=? AND broker='global'", (uid,)).fetchone()
    conn.close()
    return float(r["d"])


def _meta(oid):
    conn = main.get_db()
    r = conn.execute("SELECT undo_meta_json FROM operations WHERE id=?", (oid,)).fetchone()
    conn.close()
    return json.loads(r["undo_meta_json"] or "{}") if r else {}


# Una operación COMÚN: con precios y cantidad, no un resultado suelto de futuros.
# 10 acciones compradas a 100 y vendidas a 120 → +200 de resultado.
def _op_comun(broker="Schwab", pnl=200, **extra):
    cuerpo = {"date": "2026-09-01", "broker": broker, "asset": "AAPL",
              "op_type": "Venta", "entry_price": 100, "exit_price": 120,
              "quantity": 10, "pnl_usd": pnl, "pnl_pct": 20, "commissions": 0}
    cuerpo.update(extra)
    return cuerpo


class ElAltaDeUnaOperacionComun(unittest.TestCase):
    """Lo que pidió el usuario: que no sea sólo para futuros."""

    def setUp(self):
        self.client = _cliente()
        self.uid, self.h = _usuario(saldo=1000.0)

    def _crear(self, **extra):
        r = self.client.post("/api/operations", headers=self.h, json=_op_comun(**extra))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_con_SI_el_resultado_entra_al_efectivo(self):
        self._crear(mueve_efectivo=True)
        self.assertAlmostEqual(_cash(self.uid), 1200, places=2)
        self.assertAlmostEqual(_pnl_realizado(self.uid), 200, places=2)

    def test_una_PERDIDA_con_SI_lo_descuenta(self):
        self._crear(pnl=-80, mueve_efectivo=True)
        self.assertAlmostEqual(_cash(self.uid), 920, places=2)
        self.assertAlmostEqual(_pnl_realizado(self.uid), -80, places=2)

    def test_y_NO_ensucia_el_capital_aportado(self):
        """Es la razón de ser de todo esto: cargarlo de depósito —el workaround
        obvio— mete el resultado dos veces en el capital del mes y encima infla
        el aportado, que es el denominador del rendimiento."""
        self._crear(mueve_efectivo=True)
        self.assertAlmostEqual(_aportado(self.uid), 0, places=2)

    def test_con_NO_queda_solo_en_el_historial(self):
        self._crear(mueve_efectivo=False)
        self.assertAlmostEqual(_cash(self.uid), 1000, places=2)
        self.assertAlmostEqual(_pnl_realizado(self.uid), 200, places=2)

    def test_si_el_cliente_no_dice_nada_NO_mueve_plata(self):
        """El default es el comportamiento de siempre. Si esto cambiara, cada
        operación cargada por un cliente viejo empezaría a mover plata sola."""
        self._crear()
        self.assertAlmostEqual(_cash(self.uid), 1000, places=2)

    def test_el_nombre_viejo_del_pedido_sigue_valiendo(self):
        """`kind='futures'` es como lo pedía el bundle anterior. Hay navegadores
        con esa versión cacheada: si dejara de mover plata, el usuario cargaría
        una operación creyendo que acredita y no acreditaría."""
        self._crear(kind="futures")
        self.assertAlmostEqual(_cash(self.uid), 1200, places=2)

    def test_el_texto_libre_del_tipo_NO_mueve_plata(self):
        """El campo "Tipo" es libre. Si la plata dependiera de lo que se escribe
        ahí, una grafía movería el saldo y otra no."""
        for texto in ("Futuros", "FUTUROS", "futuro", "LONG"):
            antes = _cash(self.uid)
            self._crear(op_type=texto, asset=f"X{texto}")
            self.assertAlmostEqual(_cash(self.uid), antes, places=2,
                                   msg=f'op_type="{texto}" movió el efectivo')


class DarleVueltaAlInterruptorEditando(unittest.TestCase):
    """El check en modo edición era un adorno: el backend decidía por la foto."""

    def setUp(self):
        self.client = _cliente()
        self.uid, self.h = _usuario(saldo=1000.0)

    def _crear(self, **extra):
        r = self.client.post("/api/operations", headers=self.h, json=_op_comun(**extra))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _editar(self, oid, **extra):
        r = self.client.put(f"/api/operations/{oid}", headers=self.h, json=_op_comun(**extra))
        self.assertEqual(r.status_code, 200, r.text)

    def _borrar(self, oid):
        r = self.client.delete(f"/api/operations/{oid}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_prenderlo_acredita_en_ese_momento(self):
        op = self._crear(mueve_efectivo=False)
        self.assertAlmostEqual(_cash(self.uid), 1000, places=2)
        self._editar(op["id"], mueve_efectivo=True)
        self.assertAlmostEqual(_cash(self.uid), 1200, places=2)

    def test_apagarlo_devuelve_la_plata(self):
        op = self._crear(mueve_efectivo=True)
        self.assertAlmostEqual(_cash(self.uid), 1200, places=2)
        self._editar(op["id"], mueve_efectivo=False)
        self.assertAlmostEqual(_cash(self.uid), 1000, places=2)

    def test_BORRAR_despues_de_prenderlo_devuelve_la_plata(self):
        """LA TRAMPA. Prender el interruptor editando tiene que reescribir la
        foto de reverso, no sólo mover el saldo: si la foto sigue diciendo "esta
        no tocó plata", el borrado no devuelve nada y quedan 200 dólares
        fabricados en la cuenta."""
        op = self._crear(mueve_efectivo=False)
        self._editar(op["id"], mueve_efectivo=True)
        self.assertAlmostEqual(_cash(self.uid), 1200, places=2)
        self._borrar(op["id"])
        self.assertAlmostEqual(_cash(self.uid), 1000, places=2)

    def test_BORRAR_despues_de_apagarlo_no_devuelve_de_mas(self):
        """El reverso del anterior: si la foto conservara los 200 viejos, el
        borrado los descontaría de un saldo al que ya se los habíamos sacado."""
        op = self._crear(mueve_efectivo=True)
        self._editar(op["id"], mueve_efectivo=False)
        self.assertAlmostEqual(_cash(self.uid), 1000, places=2)
        self._borrar(op["id"])
        self.assertAlmostEqual(_cash(self.uid), 1000, places=2)

    def test_un_PUT_que_no_menciona_el_tema_no_cambia_el_tratamiento(self):
        """Corregir un precio no puede apagar el movimiento de efectivo: le
        cambiaría el saldo al usuario sin que él lo haya tocado."""
        op = self._crear(mueve_efectivo=True)
        self._editar(op["id"], entry_price=101)     # sin `mueve_efectivo`
        self.assertAlmostEqual(_cash(self.uid), 1200, places=2)
        self.assertTrue(_meta(op["id"]).get("cash_on"))

    def test_editar_el_resultado_mueve_el_efectivo_por_la_diferencia(self):
        op = self._crear(mueve_efectivo=True)
        self._editar(op["id"], pnl=500, mueve_efectivo=True)
        self.assertAlmostEqual(_cash(self.uid), 1500, places=2)

    def test_el_ciclo_alta_borrar_deshacer_borrar_no_deja_deriva(self):
        op = self._crear(mueve_efectivo=True)
        token = self._borrar(op["id"])["undo_token"]
        r = self.client.post(f"/api/operations/undo/{token}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(_cash(self.uid), 1200, places=2)

        conn = main.get_db()
        viva = conn.execute("SELECT id FROM operations WHERE user_id=? ORDER BY id DESC LIMIT 1",
                            (self.uid,)).fetchone()["id"]
        conn.close()
        self._borrar(viva)
        self.assertAlmostEqual(_cash(self.uid), 1000, places=2)
        self.assertAlmostEqual(_pnl_realizado(self.uid), 0, places=2)


class EnUnBrokerEnPesos(unittest.TestCase):
    """AUDIT 2026-09-18. El efectivo se mueve en la moneda del broker; la foto
    de reverso guardaba sólo los dólares. Medido antes del fix: alta +150.250
    pesos, borrado −100 pesos, 150.150 pesos fabricados."""

    SALDO = 1_000_000.0

    def setUp(self):
        self.client = _cliente()
        self.uid, self.h = _usuario(currency="ARS", saldo=self.SALDO, broker="Balanz")

    def _crear(self, **extra):
        r = self.client.post("/api/operations", headers=self.h,
                             json=_op_comun(broker="Balanz", **extra))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _editar(self, oid, **extra):
        r = self.client.put(f"/api/operations/{oid}", headers=self.h,
                            json=_op_comun(broker="Balanz", **extra))
        self.assertEqual(r.status_code, 200, r.text)

    def _saldo(self):
        return _cash(self.uid, "Balanz")

    def test_el_alta_acredita_al_tipo_de_cambio_y_no_los_dolares_pelados(self):
        self._crear(mueve_efectivo=True)
        acreditado = self._saldo() - self.SALDO
        self.assertGreater(acreditado, 200 * 100,
                           "200 dólares entraron como ~200 pesos: falta convertir")

    def test_el_borrado_devuelve_EXACTAMENTE_lo_que_acredito(self):
        op = self._crear(mueve_efectivo=True)
        r = self.client.delete(f"/api/operations/{op['id']}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._saldo(), self.SALDO, places=2)

    def test_el_deshacer_vuelve_a_acreditar_EXACTAMENTE_lo_mismo(self):
        op = self._crear(mueve_efectivo=True)
        con_la_op = self._saldo()
        r = self.client.delete(f"/api/operations/{op['id']}", headers=self.h)
        self.client.post(f"/api/operations/undo/{r.json()['undo_token']}", headers=self.h)
        self.assertAlmostEqual(self._saldo(), con_la_op, places=2)

    def test_doblar_el_resultado_dobla_lo_acreditado(self):
        op = self._crear(mueve_efectivo=True)
        una_vez = self._saldo() - self.SALDO
        self._editar(op["id"], pnl=400, mueve_efectivo=True)
        self.assertAlmostEqual(self._saldo() - self.SALDO, 2 * una_vez, places=2)

    def test_apagarlo_devuelve_los_PESOS_que_habia_acreditado(self):
        op = self._crear(mueve_efectivo=True)
        self._editar(op["id"], mueve_efectivo=False)
        self.assertAlmostEqual(self._saldo(), self.SALDO, places=2)

    def test_el_PL_realizado_sigue_en_DOLARES(self):
        """Sólo la pata de efectivo se convierte. `operations.pnl_usd` y
        `monthly_entries` son dólares y sus consumidores cuentan con eso."""
        self._crear(mueve_efectivo=True)
        self.assertAlmostEqual(_pnl_realizado(self.uid), 200, places=2)


class DondeElInterruptorNoSeOfrece(unittest.TestCase):
    """No a todas. Hay operaciones cuyo efectivo lo mueve OTRO mecanismo, y
    prender éste encima contaría la misma plata dos veces:

      • Importadas — el importador ya acreditó, y su borrado lo resuelve el
        rebuild del import (la fila de `import_op_links` manda sobre la foto de
        reverso). Un efectivo prendido a mano acá no se revertiría NUNCA.
      • Ventas FIFO y cobros de bonos — acreditan por su propio camino.

    El formulario no se los ofrece (`mueve_efectivo_editable` viene en la fila) y
    el backend lo hace valer igual, porque un cliente viejo puede mandarlo lo mismo."""

    def setUp(self):
        self.client = _cliente()
        self.uid, self.h = _usuario(saldo=1000.0)

    def _fila(self, oid):
        r = self.client.get("/api/operations", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return next(f for f in r.json() if f["id"] == oid)

    def _marcar_importada(self, oid):
        """Lo que deja un import: la fila de `import_op_links`. Es la que hace que
        el borrado lo resuelva el rebuild y no la foto de reverso."""
        conn = main.get_db()
        bid = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO import_batches (id, user_id, broker, parser_format,
                 file_name, file_hash, status) VALUES (?,?,?,?,?,?,?)""",
            (bid, self.uid, "Schwab", "test", "x.csv", uuid.uuid4().hex, "confirmed"))
        conn.execute(
            "INSERT INTO import_op_links (batch_id, operation_id) VALUES (?,?)",
            (bid, oid))
        conn.commit()
        conn.close()

    def test_una_operacion_a_mano_SI_lo_admite(self):
        op = self.client.post("/api/operations", headers=self.h,
                              json=_op_comun()).json()
        self.assertTrue(self._fila(op["id"])["mueve_efectivo_editable"])

    def test_una_IMPORTADA_no_lo_admite_y_el_formulario_se_entera(self):
        op = self.client.post("/api/operations", headers=self.h,
                              json=_op_comun()).json()
        self._marcar_importada(op["id"])
        self.assertFalse(self._fila(op["id"])["mueve_efectivo_editable"])

    def test_y_mandarlo_igual_NO_mueve_plata(self):
        """Lo que pasaría si sólo lo escondiéramos en la pantalla: el efectivo se
        acreditaría y el borrado —que en las importadas lo resuelve el rebuild—
        no lo devolvería nunca."""
        op = self.client.post("/api/operations", headers=self.h,
                              json=_op_comun()).json()
        self._marcar_importada(op["id"])
        antes = _cash(self.uid)
        r = self.client.put(f"/api/operations/{op['id']}", headers=self.h,
                            json=_op_comun(mueve_efectivo=True))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(_cash(self.uid), antes, places=2)

    def test_la_lista_no_duplica_una_operacion_con_dos_links(self):
        """`_importada` sale de una subconsulta y no de un JOIN justamente por esto."""
        op = self.client.post("/api/operations", headers=self.h,
                              json=_op_comun()).json()
        self._marcar_importada(op["id"])
        self._marcar_importada(op["id"])
        filas = self.client.get("/api/operations", headers=self.h).json()
        self.assertEqual(len([f for f in filas if f["id"] == op["id"]]), 1)


class LaFotoDeReversoNoSePierde(unittest.TestCase):
    """Editar reescribía la foto ENTERA. Eso borraba `futuro_id`, y sin él el
    borrado ya no reabría la posición de futuros que había generado la
    operación: desaparecía de la lista de abiertas y su resultado no quedaba en
    ningún lado. Se perdía en silencio."""

    def setUp(self):
        self.client = _cliente()
        self.uid, self.h = _usuario(currency="USDT", saldo=1000.0, broker="Binance")

    def _futuro_cerrado(self):
        r = self.client.post("/api/futures", headers=self.h, json={
            "broker": "Binance", "symbol": "BTCUSDT", "side": "long",
            "quantity": 1, "entry_price": 100, "opened_at": "2026-09-01"})
        self.assertEqual(r.status_code, 200, r.text)
        fid = r.json()["id"]
        r2 = self.client.post(f"/api/futures/{fid}/close", headers=self.h, json={
            "exit_price": 150, "commissions": 0, "closed_at": "2026-09-05"})
        self.assertEqual(r2.status_code, 200, r2.text)
        return fid, r2.json()["operation_id"]

    def _abierta(self, fid):
        conn = main.get_db()
        r = conn.execute("SELECT closed_at FROM futures_positions WHERE id=? AND user_id=?",
                         (fid, self.uid)).fetchone()
        conn.close()
        return r is not None and r["closed_at"] is None

    def test_editar_no_pierde_el_vinculo_con_la_posicion_de_futuros(self):
        fid, oid = self._futuro_cerrado()
        self.assertFalse(self._abierta(fid))
        r = self.client.put(f"/api/operations/{oid}", headers=self.h, json={
            "date": "2026-09-05", "broker": "Binance", "asset": "BTCUSDT",
            "op_type": "Futuros", "pnl_usd": 50, "commissions": 0})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(_meta(oid).get("futuro_id"), fid,
                         "la edición se comió el futuro_id de la foto de reverso")

        self.client.delete(f"/api/operations/{oid}", headers=self.h)
        self.assertTrue(self._abierta(fid),
                        "borrar la operación editada ya no reabrió la posición")


if __name__ == "__main__":
    unittest.main()
