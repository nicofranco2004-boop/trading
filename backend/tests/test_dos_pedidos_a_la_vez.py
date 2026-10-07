"""Dos pedidos IGUALES a la vez no pueden mover la plata dos veces.

LA CAUSA, UNA SOLA PARA TODOS LOS CASOS DE ABAJO (medida el 2026-10-03).
sqlite3 abre la transacción recién en la PRIMERA escritura. Todo lo que un
pedido lee antes —"¿la operación ya movía plata?", "¿el plazo fijo sigue
abierto?", "¿cuánto queda del lote?", "¿la importación está pendiente?"— se lee
sin ningún bloqueo. Producción corre en un solo proceso, pero los pedidos se
atienden en hilos en paralelo: con un doble click los dos pedidos leen la misma
foto, los dos deciden "hay que acreditar", y la plata se mueve dos veces.

EL ARREGLO, también uno solo: el "reclamo" que ya usaba el borrado. La primera
escritura repite en su WHERE lo que se leyó y se cuenta cuántas filas tocó. Esa
escritura es la que toma la base: el segundo pedido espera, y cuando le toca
encuentra la foto cambiada, no toca nada y no mueve plata. Donde la cuenta
necesita el saldo vigente (chequeo de saldo insuficiente, promedio del TC) se
toma el saldo para escribir ANTES de leerlo.

CÓMO SE PRUEBA. No se espera a que los hilos coincidan por casualidad (el test
viejo de esto fallaba 3 de 100 veces). `_Cruce` hace que los dos pedidos tengan
que haber hecho LA LECTURA QUE DECIDE antes de que cualquiera de los dos siga:
es el orden real de un doble click, forzado. Si el código no los deja coincidir
(porque uno espera al otro), la espera se vence sola y el pedido sigue.

Cada test pasa por el endpoint de verdad, con la base de verdad.
"""
import io
import sqlite3
import threading
import time
import unittest
import uuid
from unittest import mock

import main
from fastapi.testclient import TestClient


# ── la herramienta: forzar que dos pedidos lean antes de que nadie escriba ────

class _Leido:
    """Las filas de un SELECT ya leídas (para no esperar con la lectura abierta)."""
    def __init__(self, filas):
        self._filas = list(filas)

    def fetchone(self):
        return self._filas[0] if self._filas else None

    def fetchall(self):
        return list(self._filas)

    def __iter__(self):
        return iter(self._filas)


class _Cruce:
    """Los primeros `partes` pedidos que ejecutan una lectura que contiene
    `fragmento` (o alguno de ellos, si son varios) se esperan entre sí."""

    def __init__(self, fragmento, partes=2, espera=2.0, y_despues=None, saltear=None):
        fragmentos = (fragmento,) if isinstance(fragmento, str) else tuple(fragmento)
        self.fragmentos = [" ".join(f.split()).upper() for f in fragmentos]
        self._barrera = threading.Barrier(partes, timeout=espera)
        self._quedan = partes
        self._candado = threading.Lock()
        self.se_juntaron = False
        # {fragmento: Event}: el que leyó ESE fragmento, además de juntarse con el
        # otro, espera a que el Event se prenda. Sirve para fijar QUIÉN escribe
        # primero cuando el orden peligroso es uno solo.
        self._y_despues = {" ".join(k.split()).upper(): v for k, v in (y_despues or {}).items()}
        # {fragmento: n}: las primeras n lecturas de ese fragmento pasan de largo
        # (cuando la que DECIDE no es la primera vez que se lee lo mismo).
        self._saltear = {" ".join(k.split()).upper(): v for k, v in (saltear or {}).items()}

    def toca(self, sql):
        s = " ".join(str(sql).split()).upper()
        if not s.startswith("SELECT"):
            return None
        cual = next((f for f in self.fragmentos if f in s), None)
        if cual is None:
            return None
        with self._candado:
            if self._saltear.get(cual, 0) > 0:
                self._saltear[cual] -= 1
                return None
            if self._quedan <= 0:
                return None
            self._quedan -= 1
            return cual

    def esperar(self, cual):
        try:
            self._barrera.wait()
            self.se_juntaron = True
        except threading.BrokenBarrierError:
            pass
        if cual in self._y_despues:
            self._y_despues[cual].wait(timeout=20)


class _Conexion:
    """La conexión real; sólo que después de la lectura marcada espera al otro."""

    def __init__(self, conn, cruce):
        self._c = conn
        self._cruce = cruce

    def execute(self, sql, params=()):
        cur = self._c.execute(sql, params)
        cual = self._cruce.toca(sql)
        if cual:
            filas = cur.fetchall()
            self._cruce.esperar(cual)
            return _Leido(filas)
        return cur

    def __enter__(self):
        self._c.__enter__()
        return self

    def __exit__(self, *exc):
        return self._c.__exit__(*exc)

    def __getattr__(self, nombre):
        return getattr(self._c, nombre)


class _Base(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)

    def usuario(self, brokers=(("Schwab", "USD", 1000.0),)):
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
            (f"dpv-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
        for nombre, ccy, saldo in brokers:
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                         (self.uid, nombre, ccy))
            if saldo is not None:
                conn.execute("""INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity)
                                VALUES (?,?,?,1,?,?)""",
                             (self.uid, nombre, 'ARS' if ccy == 'ARS' else 'USD', saldo, saldo))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def cash(self, broker="Schwab"):
        conn = main.get_db()
        r = conn.execute(
            "SELECT SUM(COALESCE(invested,0)) c FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
            (self.uid, broker)).fetchone()
        conn.close()
        return float(r["c"] or 0)

    def sin_turno(self):
        """Los borrados toman el turno de escritura al entrar (`main._tomar_turno`,
        2026-10): en SQLite —producción— eso pone en fila a todos los que escriben,
        así que dos pedidos ya no pueden leer a la par y los reclamos no llegan a
        competir. Esto saca SÓLO el turno, para que los reclamos sigan probados:
          · editar/vender contra borrar es lo que pasaría en Postgres, donde el
            turno traba sólo la fila del usuario y la otra acción no la toma;
          · dos borrados a la vez, en cambio, en Postgres también se ponen en fila
            (los dos toman la fila): ahí el reclamo es la segunda protección, la
            que queda si alguna vez una puerta llega sin turno."""
        p = mock.patch.object(main, "_tomar_turno", side_effect=lambda conn, uid: None)
        p.start()
        self.addCleanup(p.stop)

    def cruzar(self, fragmento, y_despues=None, saltear=None):
        """A partir de acá, cada conexión que abra la app pasa por el cruce."""
        cruce = _Cruce(fragmento, y_despues=y_despues, saltear=saltear)
        real = main.get_db
        main.get_db = lambda: _Conexion(real(), cruce)
        self.addCleanup(setattr, main, "get_db", real)
        return cruce

    def dos_a_la_vez(self, hacer):
        """Corre `hacer()` en dos hilos a la vez y devuelve los dos resultados."""
        resultados, errores = [], []

        def uno():
            try:
                resultados.append(hacer())
            except Exception as ex:      # pragma: no cover
                errores.append(ex)
        hilos = [threading.Thread(target=uno) for _ in range(2)]
        [t.start() for t in hilos]
        [t.join(timeout=60) for t in hilos]
        self.assertFalse(errores, errores)
        self.assertEqual(len(resultados), 2, "un pedido no terminó")
        return resultados


# ═════════════════════════════════════════════════════════════════════════════
class CobrarPlazoFijo(_Base):

    def test_doble_click_en_cobrar_acredita_capital_e_interes_UNA_vez(self):
        self.usuario([("Balanz", "ARS", 1_000_000.0)])
        r = self.client.post("/api/plazos-fijos", headers=self.h, json={
            "banco": "Galicia", "capital": 100_000, "moneda": "ARS", "tasa": 0.3,
            "fecha_inicio": "2026-08-01", "plazo_dias": 30})
        self.assertEqual(r.status_code, 200, r.text)
        pid = r.json()["id"]
        antes = self.cash("Balanz")
        cruce = self.cruzar("FROM plazos_fijos WHERE id=? AND user_id=? AND closed_at IS NULL")

        rs = self.dos_a_la_vez(lambda: self.client.post(
            f"/api/plazos-fijos/{pid}/cobrar", headers=self.h, json={"broker": "Balanz"}))

        self.assertTrue(cruce.se_juntaron, "el test no llegó a forzar el choque")
        self.assertEqual(sorted(x.status_code for x in rs), [200, 409], [x.text for x in rs])
        monto = next(x.json()["monto"] for x in rs if x.status_code == 200)
        self.assertAlmostEqual(self.cash("Balanz"), antes + monto, places=2,
                               msg="el doble click acreditó el plazo fijo dos veces")
        conn = main.get_db()
        n = conn.execute("SELECT COUNT(*) c FROM operations WHERE user_id=? AND op_type='Interés PF'",
                         (self.uid,)).fetchone()["c"]
        conn.close()
        self.assertEqual(n, 1, "quedaron dos intereses cobrados")


# ═════════════════════════════════════════════════════════════════════════════
class BorrarDepositoManualDelMes(_Base):

    def test_doble_click_en_borrar_devuelve_el_deposito_UNA_vez(self):
        self.usuario()
        r = self.client.post("/api/cash/flow", headers=self.h,
                             json={"broker_name": "Schwab", "direction": "deposit", "amount": 500})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self.cash(), 1500, places=2)
        conn = main.get_db()
        me = conn.execute("SELECT id FROM monthly_entries WHERE user_id=? AND broker='Schwab' "
                          "AND manual_deposits > 0", (self.uid,)).fetchone()["id"]
        conn.close()
        cruce = self.cruzar("SELECT * FROM monthly_entries WHERE id=? AND user_id=?")

        rs = self.dos_a_la_vez(lambda: self.client.delete(
            f"/api/movements/me-{me}-dep", headers=self.h))

        # ⚠️ ESTA PUERTA YA NO DEJA QUE LOS DOS LEAN A LA PAR (2026-10). Toma el
        # turno de escritura ANTES de leer nada (`main._foto_contable`: el borrado
        # necesita las cuentas de antes sin que otro las esté cambiando), así que el
        # segundo pedido espera en la puerta y, cuando entra, el depósito ya no está
        # (404). El cruce que este test forzaba —los dos leen 500 y el reclamo de
        # `_delete_one_movement` frena al segundo con 409— no puede pasar en SQLite;
        # el reclamo lo prueba el test de abajo, sin turno (la segunda protección).
        self.assertFalse(cruce.se_juntaron,
                         "los dos pedidos leyeron el depósito a la vez: la puerta no "
                         "tomó el turno de escritura antes de leer")
        codigos = sorted(x.status_code for x in rs)
        self.assertEqual(codigos[0], 200, [x.text for x in rs])
        self.assertIn(codigos[1], (404, 409), [x.text for x in rs])
        self.assertAlmostEqual(self.cash(), 1000, places=2,
                               msg="el doble click devolvió el depósito dos veces")

    def test_sin_turno_el_reclamo_frena_el_segundo_borrado(self):
        """Sin el turno (la segunda protección, ver `sin_turno`): los dos leen 500,
        y el reclamo del segundo (que repite lo leído en el WHERE) no toca la fila:
        409, sin plata.
        Con un retiro en el mismo mes, para que el renglón del mes SOBREVIVA al
        borrado: si queda todo en cero el recálculo lo elimina y el segundo pedido
        no lo encuentra con o sin reclamo (el test no distinguiría)."""
        self.sin_turno()
        self.usuario()
        for direccion, monto in (("deposit", 500), ("withdraw", 100)):
            r = self.client.post("/api/cash/flow", headers=self.h,
                                 json={"broker_name": "Schwab", "direction": direccion,
                                       "amount": monto})
            self.assertEqual(r.status_code, 200, r.text)
        conn = main.get_db()
        me = conn.execute("SELECT id FROM monthly_entries WHERE user_id=? AND broker='Schwab' "
                          "AND manual_deposits > 0", (self.uid,)).fetchone()["id"]
        conn.close()
        cruce = self.cruzar("SELECT * FROM monthly_entries WHERE id=? AND user_id=?")
        rs = self.dos_a_la_vez(lambda: self.client.delete(
            f"/api/movements/me-{me}-dep", headers=self.h))
        self.assertTrue(cruce.se_juntaron, "el test no llegó a forzar el choque")
        self.assertEqual(sorted(x.status_code for x in rs), [200, 409], [x.text for x in rs])
        self.assertAlmostEqual(self.cash(), 900, places=2,
                               msg="el doble click devolvió el depósito dos veces")


# ═════════════════════════════════════════════════════════════════════════════
class VenderLaTenencia(_Base):

    def setUp(self):
        super().setUp()
        self.usuario([("Schwab", "USD", 10_000.0)])
        r = self.client.post("/api/positions", headers=self.h, json={
            "broker": "Schwab", "asset": "AAPL", "buy_price": 100, "quantity": 10,
            "invested": 1000, "entry_date": "2026-08-01"})
        self.assertEqual(r.status_code, 200, r.text)
        self.antes = self.cash()

    def _ventas(self):
        conn = main.get_db()
        n = conn.execute("SELECT COUNT(*) c FROM operations WHERE user_id=? AND op_type='Venta'",
                         (self.uid,)).fetchone()["c"]
        conn.close()
        return n

    def _vender(self, qty):
        return lambda: self.client.post("/api/positions/sell", headers=self.h, json={
            "broker": "Schwab", "asset": "AAPL", "quantity": qty, "exit_price": 120,
            "date": "2026-09-01", "currency": "USD"})

    def test_doble_click_en_vender_TODO_acredita_la_venta_UNA_vez(self):
        cruce = self.cruzar("AND is_cash=0 AND quantity > 0")
        rs = self.dos_a_la_vez(self._vender(10))
        self.assertTrue(cruce.se_juntaron, "el test no llegó a forzar el choque")
        self.assertEqual(sorted(x.status_code for x in rs), [200, 409], [x.text for x in rs])
        self.assertAlmostEqual(self.cash(), self.antes + 1200, places=2,
                               msg="la plata de la venta entró dos veces")
        self.assertEqual(self._ventas(), 1, "quedaron dos ventas de las mismas acciones")

    def test_dos_ventas_PARCIALES_a_la_vez_no_pierden_un_descuento(self):
        """6 + 6 de 10: si las dos pasaran, el lote quedaría en 4 (la segunda pisa a
        la primera) habiendo vendido 12. Una tiene que rebotar."""
        cruce = self.cruzar("AND is_cash=0 AND quantity > 0")
        rs = self.dos_a_la_vez(self._vender(6))
        self.assertTrue(cruce.se_juntaron, "el test no llegó a forzar el choque")
        self.assertEqual(sorted(x.status_code for x in rs), [200, 409], [x.text for x in rs])
        conn = main.get_db()
        q = conn.execute("SELECT SUM(quantity) q FROM positions WHERE user_id=? AND asset='AAPL' "
                         "AND is_cash=0", (self.uid,)).fetchone()["q"]
        conn.close()
        self.assertAlmostEqual(float(q or 0), 4, places=6)
        self.assertAlmostEqual(self.cash(), self.antes + 720, places=2)
        self.assertEqual(self._ventas(), 1)


# ═════════════════════════════════════════════════════════════════════════════
class DosAccionesDistintasSobreLoMismo(_Base):
    """No es un doble click: son dos acciones distintas a la vez (editar y borrar,
    vender y borrar). Los borrados reclamaban sólo por el número de fila, así que
    devolvían lo que habían leído ANTES de que la otra acción lo cambiara.

    Se verifica el invariante y no un orden: gane quien gane, el saldo tiene que
    cerrar con lo que quedó en la base.

    ⚠️ SIN EL TURNO (`sin_turno`). Con el turno que los borrados toman al entrar
    (2026-10) el orden peligroso no puede pasar en SQLite: el borrado tiene la base
    tomada y la otra acción no escribe hasta que termina (forzarlo trababa el test
    20 s). Así que estos corren como en Postgres, donde los reclamos son la única
    protección; `DosAccionesDistintasConElTurno` corre lo mismo como en producción."""

    def setUp(self):
        super().setUp()
        self.sin_turno()

    def test_editar_y_borrar_la_misma_operacion_a_la_vez_no_fabrica_plata(self):
        self.usuario()
        oid = self.client.post("/api/operations", headers=self.h, json={
            "date": "2026-09-01", "broker": "Schwab", "asset": "AAPL", "op_type": "Venta",
            "pnl_usd": 200, "mueve_efectivo": True}).json()["id"]
        self.assertAlmostEqual(self.cash(), 1200, places=2)
        # El orden peligroso: la edición escribe y termina ENTRE la lectura y la
        # escritura del borrado. (Al revés —borrado primero— la edición da 404.)
        # El borrado lee la operación dos veces: la primera para ver si es
        # importada o cargada a mano; la SEGUNDA es la que decide cuánto devolver.
        edito = threading.Event()
        del_lee = "SELECT * FROM operations WHERE id=? AND user_id=?"
        cruce = self.cruzar(("SELECT broker, date, undo_meta_json FROM operations WHERE id=? AND user_id=?",
                             del_lee),
                            y_despues={del_lee: edito}, saltear={del_lee: 1})
        hechos = iter(["editar", "borrar"])
        candado = threading.Lock()

        def accion():
            with candado:
                que = next(hechos)
            if que == "editar":
                try:
                    return self.client.put(f"/api/operations/{oid}", headers=self.h, json={
                        "date": "2026-09-01", "broker": "Schwab", "asset": "AAPL",
                        "op_type": "Venta", "pnl_usd": 300, "mueve_efectivo": True})
                finally:
                    edito.set()
            return self.client.delete(f"/api/operations/{oid}", headers=self.h)
        rs = self.dos_a_la_vez(accion)

        self.assertTrue(cruce.se_juntaron, "el test no llegó a forzar el choque")
        conn = main.get_db()
        fila = conn.execute("SELECT pnl_usd FROM operations WHERE id=?", (oid,)).fetchone()
        conn.close()
        sigue = float(fila["pnl_usd"]) if fila else 0.0
        self.assertAlmostEqual(self.cash(), 1000 + sigue, places=2,
                               msg=f"el saldo no cierra con la operación que quedó ({[x.status_code for x in rs]})")

    def test_vender_parte_y_borrar_el_lote_a_la_vez_no_fabrica_plata(self):
        self.usuario([("Schwab", "USD", 10_000.0)])
        r = self.client.post("/api/positions", headers=self.h, json={
            "broker": "Schwab", "asset": "AAPL", "buy_price": 100, "quantity": 10,
            "invested": 1000, "entry_date": "2026-08-01"})
        self.assertEqual(r.status_code, 200, r.text)
        pid = r.json()["id"]
        self.assertAlmostEqual(self.cash(), 9000, places=2)
        # El orden peligroso: la venta escribe y termina ENTRE la lectura y la
        # escritura del borrado.
        vendio = threading.Event()
        cruce = self.cruzar(("AND is_cash=0 AND quantity > 0",
                             "SELECT * FROM positions WHERE id=? AND user_id=? AND is_cash=0"),
                            y_despues={"SELECT * FROM positions WHERE id=? AND user_id=? AND is_cash=0": vendio})
        hechos = iter(["vender", "borrar"])
        candado = threading.Lock()

        def accion():
            with candado:
                que = next(hechos)
            if que == "vender":
                try:
                    return self.client.post("/api/positions/sell", headers=self.h, json={
                        "broker": "Schwab", "asset": "AAPL", "quantity": 6, "exit_price": 120,
                        "date": "2026-09-01", "currency": "USD"})
                finally:
                    vendio.set()
            return self.client.delete(f"/api/positions/{pid}", headers=self.h)
        rs = self.dos_a_la_vez(accion)

        self.assertTrue(cruce.se_juntaron, "el test no llegó a forzar el choque")
        conn = main.get_db()
        lote = conn.execute("SELECT quantity FROM positions WHERE id=?", (pid,)).fetchone()
        ventas = conn.execute("SELECT COUNT(*) c FROM operations WHERE user_id=? AND op_type='Venta'",
                              (self.uid,)).fetchone()["c"]
        conn.close()
        # Los dos finales posibles y coherentes:
        #   ganó la venta  → quedan 4 y la plata de la venta (9000 + 720)
        #   ganó el borrado → no hay lote ni venta, y volvió el costo (10000)
        estado = (round(self.cash(), 2), float(lote["quantity"]) if lote else None, ventas)
        self.assertIn(estado, [(9720.0, 4.0, 1), (10000.0, None, 0)],
                      f"saldo/lote/ventas incoherentes: {estado} ({[x.status_code for x in rs]})")


class DosAccionesDistintasConElTurno(_Base):
    """Las mismas dos acciones a la vez, como en producción (SQLite, con el turno que
    el borrado toma al entrar). No se fuerza un orden: el que entra primero termina
    y el otro escribe después. Se exige el invariante, como arriba.

    ⚠️ ES UN TEST DE HUMO: que con el turno nada se trabe ni dé 500 y el saldo
    cierre. No prueba ni el turno ni los reclamos (sin forzar el orden, casi siempre
    pasa con cualquiera de los dos): ésos los prueban la clase de arriba y
    `test_la_foto_de_antes_ve_lo_que_otro_estaba_escribiendo`."""

    def _a_la_vez(self, primero, segundo):
        hechos = iter([primero, segundo])
        candado = threading.Lock()

        def accion():
            with candado:
                f = next(hechos)
            return f()
        return self.dos_a_la_vez(accion)

    def test_editar_y_borrar_la_misma_operacion(self):
        self.usuario()
        oid = self.client.post("/api/operations", headers=self.h, json={
            "date": "2026-09-01", "broker": "Schwab", "asset": "AAPL", "op_type": "Venta",
            "pnl_usd": 200, "mueve_efectivo": True}).json()["id"]
        rs = self._a_la_vez(
            lambda: self.client.put(f"/api/operations/{oid}", headers=self.h, json={
                "date": "2026-09-01", "broker": "Schwab", "asset": "AAPL",
                "op_type": "Venta", "pnl_usd": 300, "mueve_efectivo": True}),
            lambda: self.client.delete(f"/api/operations/{oid}", headers=self.h))
        conn = main.get_db()
        fila = conn.execute("SELECT pnl_usd FROM operations WHERE id=?", (oid,)).fetchone()
        conn.close()
        sigue = float(fila["pnl_usd"]) if fila else 0.0
        self.assertAlmostEqual(self.cash(), 1000 + sigue, places=2,
                               msg=f"el saldo no cierra ({[x.status_code for x in rs]})")

    def test_vender_parte_y_borrar_el_lote(self):
        self.usuario([("Schwab", "USD", 10_000.0)])
        r = self.client.post("/api/positions", headers=self.h, json={
            "broker": "Schwab", "asset": "AAPL", "buy_price": 100, "quantity": 10,
            "invested": 1000, "entry_date": "2026-08-01"})
        self.assertEqual(r.status_code, 200, r.text)
        pid = r.json()["id"]
        rs = self._a_la_vez(
            lambda: self.client.post("/api/positions/sell", headers=self.h, json={
                "broker": "Schwab", "asset": "AAPL", "quantity": 6, "exit_price": 120,
                "date": "2026-09-01", "currency": "USD"}),
            lambda: self.client.delete(f"/api/positions/{pid}", headers=self.h))
        conn = main.get_db()
        lote = conn.execute("SELECT quantity FROM positions WHERE id=?", (pid,)).fetchone()
        ventas = conn.execute("SELECT COUNT(*) c FROM operations WHERE user_id=? AND op_type='Venta'",
                              (self.uid,)).fetchone()["c"]
        conn.close()
        estado = (round(self.cash(), 2), float(lote["quantity"]) if lote else None, ventas)
        # Además de los dos finales de arriba, acá puede ganar el borrado DESPUÉS de
        # la venta: el lote cambió y el borrado rebota (409) → queda la venta.
        self.assertIn(estado, [(9720.0, 4.0, 1), (10000.0, None, 0)],
                      f"saldo/lote/ventas incoherentes: {estado} ({[x.status_code for x in rs]})")


# ═════════════════════════════════════════════════════════════════════════════
_H = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;instrumento;"
      "moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total")
_DEP = "1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;1.000.000;0;0;0;0;1.000.000"


class ConfirmarYDeshacerUnaImportacion(_Base):

    def setUp(self):
        super().setUp()
        self.usuario(brokers=())

    def _preview(self):
        csv = ("\n".join([_H, _DEP]) + "\n").encode()
        p = self.client.post("/api/imports/preview",
                             files=[("files", ("mov.csv", io.BytesIO(csv), "text/csv"))],
                             data={"format": "cocos"}, headers=self.h)
        self.assertEqual(p.status_code, 200, p.text)
        return p.json()["session_id"]

    def _confirmar(self, sid):
        return self.client.post("/api/imports/confirm", headers=self.h, json={
            "session_id": sid, "skip_row_indices": [], "aprobar_tickers": []})

    def test_doble_click_en_confirmar_aplica_el_archivo_UNA_vez(self):
        sid = self._preview()
        cruce = self.cruzar("SELECT * FROM import_batches WHERE id=? AND user_id=?")
        rs = self.dos_a_la_vez(lambda: self._confirmar(sid))
        self.assertTrue(cruce.se_juntaron, "el test no llegó a forzar el choque")
        self.assertEqual(sorted(x.status_code for x in rs), [200, 409], [x.text for x in rs])
        self.assertAlmostEqual(self.cash("Cocos"), 1_000_000, places=2,
                               msg="el depósito del archivo entró dos veces")

    def test_doble_click_en_deshacer_lo_devuelve_UNA_vez(self):
        sid = self._preview()
        self.assertEqual(self._confirmar(sid).status_code, 200)
        self.assertAlmostEqual(self.cash("Cocos"), 1_000_000, places=2)
        cruce = self.cruzar("SELECT * FROM import_batches WHERE id=? AND user_id=?")
        rs = self.dos_a_la_vez(lambda: self.client.post(f"/api/imports/{sid}/revert",
                                                        headers=self.h))
        self.assertTrue(cruce.se_juntaron, "el test no llegó a forzar el choque")
        self.assertEqual(sorted(x.status_code for x in rs), [200, 400], [x.text for x in rs])
        self.assertAlmostEqual(self.cash("Cocos"), 0, places=2,
                               msg="deshacer dos veces sacó el depósito dos veces")

    def test_una_escritura_AJENA_en_el_medio_no_hace_perder_filas(self):
        """No es un doble click. Otra parte de Rendi (los precios, la foto diaria,
        otro usuario: la base es una sola) escribe mientras se confirma un archivo.

        Antes, sin ninguna escritura previa, cada fila del archivo era su propia
        transacción: leía, y si alguien commiteaba antes de que escribiera, SQLite
        la rechazaba con "database is locked" y el importador la salteaba — la
        confirmación respondía OK con una fila menos (la pantalla final la listaba
        como fila con problema). Ahora el reclamo abre la transacción al empezar y
        el otro espera su turno. Medido sin el arreglo: falla 10 de 10."""
        sid = self._preview()
        lee_caja = "SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1"
        escribio = threading.Event()
        cruce = self.cruzar(lee_caja, y_despues={lee_caja: escribio})

        def otro():
            try:
                cruce._barrera.wait()          # la fila ya leyó; ahora escribe otro
            except threading.BrokenBarrierError:
                pass
            c = sqlite3.connect(main.DB_PATH, timeout=0.5)
            try:
                # Un cambio DE VERDAD: uno que deja todo igual no cuenta como
                # escritura para SQLite y no dispara el choque.
                c.execute("UPDATE users SET password_hash=? WHERE id=?",
                          (uuid.uuid4().hex, self.uid))
                c.commit()
            except sqlite3.OperationalError:
                pass   # la importación tiene la base tomada: el otro espera, como corresponde
            finally:
                c.close()
                escribio.set()
        t = threading.Thread(target=otro)
        t.start()
        r = self._confirmar(sid)
        t.join(timeout=30)

        self.assertTrue(cruce.se_juntaron, "el test no llegó a forzar el cruce")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json().get("skipped_rows"), [], "se salteó una fila del archivo")
        self.assertAlmostEqual(self.cash("Cocos"), 1_000_000, places=2,
                               msg="el depósito del archivo no entró")


# ═════════════════════════════════════════════════════════════════════════════
class ConciliarElSaldo(_Base):

    def test_doble_click_anota_la_diferencia_en_el_capital_UNA_vez(self):
        self.usuario()
        cruce = self.cruzar("SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1")
        rs = self.dos_a_la_vez(lambda: self.client.post(
            "/api/brokers/reconcile-cash", headers=self.h,
            json={"broker_name": "Schwab", "target_cash": 1500}))
        self.assertTrue(cruce.se_juntaron, "el test no llegó a forzar el choque")
        self.assertEqual([x.status_code for x in rs], [200, 200], [x.text for x in rs])
        self.assertAlmostEqual(self.cash(), 1500, places=2)
        conn = main.get_db()
        dep = conn.execute("SELECT SUM(COALESCE(manual_deposits,0)) d FROM monthly_entries "
                           "WHERE user_id=? AND broker='Schwab'", (self.uid,)).fetchone()["d"]
        conn.close()
        self.assertAlmostEqual(float(dep or 0), 500, places=2,
                               msg="el ajuste se anotó dos veces en el capital aportado")


# ═════════════════════════════════════════════════════════════════════════════
class DeshacerDelChat(_Base):

    def test_dos_deshace_a_la_vez_devuelven_el_costo_UNA_vez(self):
        self.usuario([("Schwab", "USD", 0.0)])
        conn = main.get_db()
        broker_id = conn.execute("SELECT id FROM brokers WHERE user_id=? AND name='Schwab'",
                                 (self.uid,)).fetchone()["id"]
        pid = conn.execute("""INSERT INTO positions (user_id, broker, asset, is_cash, quantity,
                                buy_price, invested) VALUES (?, 'Schwab', 'AAPL', 0, 10, 100, 1000)""",
                           (self.uid,)).lastrowid
        conn.commit()
        conn.close()
        # Lo que deja anotado una compra por chat de 10 AAPL que debitó 1000.
        main._LAST_CHAT_TRADE[self.uid] = {
            "kind": "buy", "position_id": pid, "cash_debited": 1000, "autodeposit": False,
            "broker_id": broker_id, "asset": "AAPL", "quantity": 10,
            "summary": "compra de 10 AAPL", "ts": time.time()}
        self.addCleanup(main._LAST_CHAT_TRADE.pop, self.uid, None)
        cruce = self.cruzar("SELECT quantity FROM positions WHERE id=? AND user_id=?")

        rs = self.dos_a_la_vez(lambda: main._undo_last_trade_handler(self.uid))

        self.assertTrue(cruce.se_juntaron, "el test no llegó a forzar el choque")
        self.assertEqual(sum(1 for x in rs if x.get("status") == "undone"), 1, rs)
        self.assertAlmostEqual(self.cash(), 1000, places=2,
                               msg="el costo de la compra se devolvió dos veces")


# ═════════════════════════════════════════════════════════════════════════════
class DepositosYRetirosManuales(_Base):
    """Acá no hay una decisión que se repita: el saldo se escribía como un número
    calculado con una lectura sin bloqueo, y el segundo pisaba al primero."""

    def _flujo(self, direction, amount):
        return lambda: self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": "Schwab", "direction": direction, "amount": amount})

    def test_dos_depositos_a_la_vez_cuentan_los_dos(self):
        self.usuario()
        self.cruzar("SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1")
        hechos = iter([300, 200])
        candado = threading.Lock()

        def depositar():
            with candado:
                monto = next(hechos)
            return self._flujo("deposit", monto)()
        rs = self.dos_a_la_vez(depositar)
        self.assertEqual([x.status_code for x in rs], [200, 200], [x.text for x in rs])
        self.assertAlmostEqual(self.cash(), 1500, places=2, msg="un depósito se perdió")

    def test_dos_retiros_que_juntos_no_alcanzan_rebota_uno(self):
        self.usuario()
        self.cruzar("SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1")
        rs = self.dos_a_la_vez(self._flujo("withdraw", 700))
        self.assertEqual(sorted(x.status_code for x in rs), [200, 400], [x.text for x in rs])
        self.assertAlmostEqual(self.cash(), 300, places=2)


# ═════════════════════════════════════════════════════════════════════════════
class ComprarDolaresDentroDelBroker(_Base):

    def test_dos_compras_de_dolares_a_la_vez_descuentan_los_pesos_de_las_dos(self):
        self.usuario([("Balanz", "ARS", 2_000_000.0)])
        compra = {"from_broker": "Balanz", "direction": "ars_to_usd",
                  "ars_amount": 100_000, "usd_amount": 100, "tc": 1000}
        # La primera, sola: crea la subcuenta en dólares (eso ya es una escritura).
        r = self.client.post("/api/conversions", headers=self.h, json=compra)
        self.assertEqual(r.status_code, 200, r.text)
        self.cruzar("SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1")
        rs = self.dos_a_la_vez(lambda: self.client.post("/api/conversions", headers=self.h,
                                                        json=compra))
        self.assertEqual([x.status_code for x in rs], [200, 200], [x.text for x in rs])
        self.assertAlmostEqual(self.cash("Balanz"), 1_700_000, places=2,
                               msg="una de las compras no descontó los pesos")


if __name__ == "__main__":
    unittest.main()
