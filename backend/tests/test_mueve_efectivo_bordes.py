"""AUDIT ADVERSARIAL de "¿esta operación movió la plata?".

No repite los casos felices (eso ya lo cubre test_operacion_mueve_efectivo.py).
Acá se ataca lo que quedó en los bordes:

  A) Las filas VIEJAS, que tienen `cash` en dólares y no tienen `cash_native`.
  B) Los journals de borrado VIEJOS, escritos antes de que existiera cash_native.
  C) Cambiar de broker cruzando monedas (pesos ↔ dólares) con el efectivo prendido.
  D) Idempotencia: mandar el mismo PUT dos veces no puede mover plata dos veces.
  E) El cliente VIEJO (kind='futures') editando filas nuevas y viejas.
  F) Dos PUT en PARALELO sobre la misma operación.
  G) Prender el efectivo sobre una operación que no existe / no es mía.
"""
import json
import threading
import unittest
import uuid

import main


def _cliente():
    from fastapi.testclient import TestClient
    return TestClient(main.app)


def _usuario(brokers=(("Schwab", "USD", 1000.0),)):
    conn = main.get_db()
    uid = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
        (f"adv-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
    for nombre, ccy, saldo in brokers:
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (uid, nombre, ccy))
        conn.execute("""INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity)
                        VALUES (?,?,?,1,?,?)""",
                     (uid, nombre, 'ARS' if ccy == 'ARS' else 'USD', saldo, saldo))
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


def _meta(oid):
    conn = main.get_db()
    r = conn.execute("SELECT undo_meta_json FROM operations WHERE id=?", (oid,)).fetchone()
    conn.close()
    return json.loads(r["undo_meta_json"] or "{}") if r else {}


def _set_meta(oid, meta):
    conn = main.get_db()
    conn.execute("UPDATE operations SET undo_meta_json=? WHERE id=?", (json.dumps(meta), oid))
    conn.commit()
    conn.close()


def _op(broker="Schwab", pnl=200, **extra):
    c = {"date": "2026-09-01", "broker": broker, "asset": "AAPL", "op_type": "Venta",
         "entry_price": 100, "exit_price": 120, "quantity": 10, "pnl_usd": pnl,
         "pnl_pct": 20, "commissions": 0}
    c.update(extra)
    return c


# ═════════════════════════════════════════════════════════════════════════════
class A_FilasViejasSinCashNative(unittest.TestCase):
    """Las que ya viven en la base: `cash` en dólares, sin `cash_native`.
    Son las que hoy están rotas en un broker en pesos."""

    SALDO = 1_000_000.0

    def setUp(self):
        self.client = _cliente()
        self.uid, self.h = _usuario([("Balanz", "ARS", self.SALDO)])

    def _fila_vieja(self, pnl=200):
        """Reproduce EXACTAMENTE lo que dejaba el código anterior: acredita
        convertido pero guarda la foto en dólares y sin cash_native."""
        r = self.client.post("/api/operations", headers=self.h,
                             json=_op(broker="Balanz", pnl=pnl, mueve_efectivo=True))
        oid = r.json()["id"]
        m = _meta(oid)
        self.acreditado = _cash(self.uid, "Balanz") - self.SALDO
        _set_meta(oid, {"src": "manual_futures", "cash": pnl})   # foto vieja
        return oid

    def test_el_borrado_de_una_fila_VIEJA_devuelve_los_pesos_no_los_dolares(self):
        oid = self._fila_vieja()
        r = self.client.delete(f"/api/operations/{oid}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(_cash(self.uid, "Balanz"), self.SALDO, places=2,
                               msg="la fila vieja se reconvirtió mal al borrar")

    def test_editar_una_fila_VIEJA_no_fabrica_ni_destruye_plata(self):
        oid = self._fila_vieja()
        antes = _cash(self.uid, "Balanz")
        r = self.client.put(f"/api/operations/{oid}", headers=self.h,
                            json=_op(broker="Balanz", pnl=200))   # mismo pnl, sin tocar el flag
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(_cash(self.uid, "Balanz"), antes, places=2,
                               msg="un PUT que no cambia nada movió el saldo")

    def test_y_despues_de_editarla_queda_con_cash_native(self):
        oid = self._fila_vieja()
        self.client.put(f"/api/operations/{oid}", headers=self.h, json=_op(broker="Balanz", pnl=200))
        self.assertIsNotNone(_meta(oid).get("cash_native"),
                             "la edición no migró la foto vieja")

    def test_apagarla_desde_una_fila_VIEJA_devuelve_exacto(self):
        oid = self._fila_vieja()
        self.client.put(f"/api/operations/{oid}", headers=self.h,
                        json=_op(broker="Balanz", pnl=200, mueve_efectivo=False))
        self.assertAlmostEqual(_cash(self.uid, "Balanz"), self.SALDO, places=2)


# ═════════════════════════════════════════════════════════════════════════════
class B_JournalsViejos(unittest.TestCase):
    """Un borrado hecho ANTES del deploy y deshecho DESPUÉS: el journal sólo
    tiene `cash` (dólares)."""

    SALDO = 1_000_000.0

    def setUp(self):
        self.client = _cliente()
        self.uid, self.h = _usuario([("Balanz", "ARS", self.SALDO)])

    def test_el_undo_de_un_journal_VIEJO_sigue_funcionando(self):
        r = self.client.post("/api/operations", headers=self.h,
                             json=_op(broker="Balanz", pnl=200, mueve_efectivo=True))
        oid = r.json()["id"]
        d = self.client.delete(f"/api/operations/{oid}", headers=self.h)
        token = d.json()["undo_token"]
        # degradamos el journal a la forma vieja (sin cash_native)
        conn = main.get_db()
        row = conn.execute("SELECT payload_json FROM deleted_ops_journal WHERE token=?",
                           (token,)).fetchone()
        p = json.loads(row["payload_json"])
        nativo = p.pop("cash_native", None)
        conn.execute("UPDATE deleted_ops_journal SET payload_json=? WHERE token=?",
                     (json.dumps(p), token))
        conn.commit()
        conn.close()
        self.assertIsNotNone(nativo, "el journal nuevo no traía cash_native")
        r2 = self.client.post(f"/api/operations/undo/{token}", headers=self.h)
        self.assertEqual(r2.status_code, 200, r2.text)
        # Con el journal viejo re-acredita los DÓLARES (200) en vez de los pesos.
        # No es exacto —es lo que ese journal sabía— pero no puede explotar ni
        # dejar el saldo en un disparate.
        self.assertGreater(_cash(self.uid, "Balanz"), self.SALDO - 1)


# ═════════════════════════════════════════════════════════════════════════════
class C_CambioDeBrokerCruzandoMonedas(unittest.TestCase):
    ARS0, USD0 = 1_000_000.0, 1000.0

    def setUp(self):
        self.client = _cliente()
        self.uid, self.h = _usuario([("Balanz", "ARS", self.ARS0), ("Schwab", "USD", self.USD0)])

    def test_de_PESOS_a_DOLARES_devuelve_pesos_y_acredita_dolares(self):
        r = self.client.post("/api/operations", headers=self.h,
                             json=_op(broker="Balanz", pnl=200, mueve_efectivo=True))
        oid = r.json()["id"]
        self.assertGreater(_cash(self.uid, "Balanz"), self.ARS0 + 200 * 100)
        self.client.put(f"/api/operations/{oid}", headers=self.h,
                        json=_op(broker="Schwab", pnl=200, mueve_efectivo=True))
        self.assertAlmostEqual(_cash(self.uid, "Balanz"), self.ARS0, places=2,
                               msg="no devolvió los PESOS al broker viejo")
        self.assertAlmostEqual(_cash(self.uid, "Schwab"), self.USD0 + 200, places=2,
                               msg="no acreditó DÓLARES en el broker nuevo")

    def test_de_DOLARES_a_PESOS_tambien(self):
        r = self.client.post("/api/operations", headers=self.h,
                             json=_op(broker="Schwab", pnl=200, mueve_efectivo=True))
        oid = r.json()["id"]
        self.client.put(f"/api/operations/{oid}", headers=self.h,
                        json=_op(broker="Balanz", pnl=200, mueve_efectivo=True))
        self.assertAlmostEqual(_cash(self.uid, "Schwab"), self.USD0, places=2)
        self.assertGreater(_cash(self.uid, "Balanz"), self.ARS0 + 200 * 100)

    def test_y_el_borrado_posterior_cierra_en_cero_de_los_dos_lados(self):
        r = self.client.post("/api/operations", headers=self.h,
                             json=_op(broker="Balanz", pnl=200, mueve_efectivo=True))
        oid = r.json()["id"]
        self.client.put(f"/api/operations/{oid}", headers=self.h,
                        json=_op(broker="Schwab", pnl=200, mueve_efectivo=True))
        self.client.delete(f"/api/operations/{oid}", headers=self.h)
        self.assertAlmostEqual(_cash(self.uid, "Balanz"), self.ARS0, places=2)
        self.assertAlmostEqual(_cash(self.uid, "Schwab"), self.USD0, places=2)


# ═════════════════════════════════════════════════════════════════════════════
class D_Idempotencia(unittest.TestCase):
    def setUp(self):
        self.client = _cliente()
        self.uid, self.h = _usuario()

    def test_el_mismo_PUT_cinco_veces_no_mueve_plata_cinco_veces(self):
        r = self.client.post("/api/operations", headers=self.h, json=_op(mueve_efectivo=True))
        oid = r.json()["id"]
        for _ in range(5):
            self.client.put(f"/api/operations/{oid}", headers=self.h, json=_op(mueve_efectivo=True))
        self.assertAlmostEqual(_cash(self.uid), 1200, places=2)

    def test_prender_y_apagar_cinco_veces_cierra_donde_empezo(self):
        r = self.client.post("/api/operations", headers=self.h, json=_op(mueve_efectivo=False))
        oid = r.json()["id"]
        for _ in range(5):
            self.client.put(f"/api/operations/{oid}", headers=self.h, json=_op(mueve_efectivo=True))
            self.client.put(f"/api/operations/{oid}", headers=self.h, json=_op(mueve_efectivo=False))
        self.assertAlmostEqual(_cash(self.uid), 1000, places=2)

    def test_vaciar_el_PL_con_el_efectivo_prendido_devuelve_la_plata(self):
        r = self.client.post("/api/operations", headers=self.h, json=_op(mueve_efectivo=True))
        oid = r.json()["id"]
        self.client.put(f"/api/operations/{oid}", headers=self.h,
                        json=_op(pnl=None, mueve_efectivo=True))
        self.assertAlmostEqual(_cash(self.uid), 1000, places=2)


# ═════════════════════════════════════════════════════════════════════════════
class E_ClienteViejo(unittest.TestCase):
    """Los navegadores con el bundle anterior mandan `kind`, no `mueve_efectivo`."""

    def setUp(self):
        self.client = _cliente()
        self.uid, self.h = _usuario()

    def test_el_cliente_viejo_MANTIENE_prendida_una_fila_prendida(self):
        r = self.client.post("/api/operations", headers=self.h, json=_op(mueve_efectivo=True))
        oid = r.json()["id"]
        self.client.put(f"/api/operations/{oid}", headers=self.h, json=_op(kind="futures"))
        self.assertAlmostEqual(_cash(self.uid), 1200, places=2)
        self.assertTrue(_meta(oid).get("cash_on"))

    def test_el_cliente_viejo_MANTIENE_apagada_una_fila_apagada(self):
        r = self.client.post("/api/operations", headers=self.h, json=_op(mueve_efectivo=False))
        oid = r.json()["id"]
        self.client.put(f"/api/operations/{oid}", headers=self.h, json=_op(kind=None))
        self.assertAlmostEqual(_cash(self.uid), 1000, places=2)

    def test_mueve_efectivo_le_gana_a_kind_si_vienen_los_dos(self):
        """Es lo que manda el front nuevo; los dos salen del mismo booleano, pero
        si alguna vez se contradijeran gana el explícito."""
        self.client.post("/api/operations", headers=self.h,
                         json=_op(mueve_efectivo=False, kind="futures"))
        self.assertAlmostEqual(_cash(self.uid), 1000, places=2)


# ═════════════════════════════════════════════════════════════════════════════
class F_Concurrencia(unittest.TestCase):
    def setUp(self):
        self.client = _cliente()
        self.uid, self.h = _usuario()

    def test_dos_PUT_en_paralelo_no_acreditan_dos_veces(self):
        r = self.client.post("/api/operations", headers=self.h, json=_op(mueve_efectivo=False))
        oid = r.json()["id"]
        errores = []

        def poner():
            try:
                self.client.put(f"/api/operations/{oid}", headers=self.h,
                                json=_op(mueve_efectivo=True))
            except Exception as ex:      # pragma: no cover
                errores.append(ex)

        hilos = [threading.Thread(target=poner) for _ in range(2)]
        [t.start() for t in hilos]
        [t.join() for t in hilos]
        self.assertFalse(errores, errores)
        self.assertAlmostEqual(_cash(self.uid), 1200, places=2,
                               msg="dos PUT simultáneos acreditaron el resultado dos veces")

    # ── El mismo choque, pero SIEMPRE ────────────────────────────────────────
    # El test de arriba depende de que los hilos coincidan por casualidad: medido
    # el 2026-10-03, falló 3 de 100 corridas. Y lo que sí veía era la punta: en
    # la MITAD de las carreras los dos pedidos decidían acreditar, pero una
    # segunda falla (el saldo se escribía como un número calculado en Python, y
    # el segundo pisaba al primero) se comía una de las dos sumas y el saldo
    # daba bien por accidente.
    #
    # Acá el choque se fuerza: los dos pedidos tienen que haber LEÍDO la foto de
    # la operación antes de que cualquiera de los dos escriba. Es el orden real de
    # un doble click en "Guardar", no uno inventado. Si el código no los deja
    # coincidir (porque uno espera al otro), la barrera se vence sola y sigue.

    def _juntar_los_primeros(self, nombre, partes=2):
        """Los primeros `partes` pasos por `main.<nombre>` se esperan entre sí."""
        original = getattr(main, nombre)
        barrera = threading.Barrier(partes, timeout=3)
        quedan = [partes]
        candado = threading.Lock()

        def esperando(*a, **k):
            r = original(*a, **k)
            with candado:
                toca, quedan[0] = quedan[0] > 0, quedan[0] - 1
            if toca:
                try:
                    barrera.wait()
                except threading.BrokenBarrierError:
                    pass
            return r
        setattr(main, nombre, esperando)
        self.addCleanup(setattr, main, nombre, original)

    def _contar_movimientos(self):
        """Anota cada vez que se mueve plata de este usuario (sólo mira)."""
        original = main._adjust_broker_cash
        movidas = []

        def contando(conn, uid, broker, delta):
            if uid == self.uid and delta:
                movidas.append(delta)
            return original(conn, uid, broker, delta)
        main._adjust_broker_cash = contando
        self.addCleanup(setattr, main, "_adjust_broker_cash", original)
        return movidas

    def _dos_put_a_la_vez(self, oid, cuerpo):
        respuestas, errores = [], []

        def poner():
            try:
                respuestas.append(self.client.put(f"/api/operations/{oid}",
                                                  headers=self.h, json=cuerpo))
            except Exception as ex:      # pragma: no cover
                errores.append(ex)
        hilos = [threading.Thread(target=poner) for _ in range(2)]
        [t.start() for t in hilos]
        [t.join() for t in hilos]
        self.assertFalse(errores, errores)
        return respuestas

    def test_doble_click_que_lee_la_misma_foto_mueve_la_plata_UNA_vez(self):
        oid = self.client.post("/api/operations", headers=self.h,
                               json=_op(mueve_efectivo=False)).json()["id"]
        # `_meta_movio_efectivo` es lo primero que corre después de leer la foto
        # guardada, y antes de cualquier escritura.
        self._juntar_los_primeros("_meta_movio_efectivo")
        movidas = self._contar_movimientos()

        rs = self._dos_put_a_la_vez(oid, _op(mueve_efectivo=True))

        self.assertEqual([r.status_code for r in rs], [200, 200], [r.text for r in rs])
        self.assertEqual(movidas, [200], "los dos pedidos acreditaron el resultado")
        self.assertAlmostEqual(_cash(self.uid), 1200, places=2,
                               msg="el doble click dejó el saldo con el resultado dos veces")
        m = _meta(oid)
        self.assertTrue(m.get("cash_on"))
        self.assertAlmostEqual(m.get("cash_native"), 200, places=2,
                               msg="la foto no coincide con lo que se acreditó: el borrado devolvería otra cifra")

    def test_doble_click_al_APAGAR_devuelve_la_plata_UNA_vez(self):
        oid = self.client.post("/api/operations", headers=self.h,
                               json=_op(mueve_efectivo=True)).json()["id"]
        self.assertAlmostEqual(_cash(self.uid), 1200, places=2)
        self._juntar_los_primeros("_meta_movio_efectivo")
        movidas = self._contar_movimientos()

        self._dos_put_a_la_vez(oid, _op(mueve_efectivo=False))

        self.assertEqual(movidas, [-200], "los dos pedidos devolvieron la plata")
        self.assertAlmostEqual(_cash(self.uid), 1000, places=2)

    def test_y_despues_el_borrado_deja_el_saldo_donde_empezo(self):
        """El recorrido completo: doble click y después borrar. Si la foto y el
        saldo quedaron desparejos, acá aparece la plata fabricada."""
        oid = self.client.post("/api/operations", headers=self.h,
                               json=_op(mueve_efectivo=False)).json()["id"]
        self._juntar_los_primeros("_meta_movio_efectivo")
        self._dos_put_a_la_vez(oid, _op(mueve_efectivo=True))
        r = self.client.delete(f"/api/operations/{oid}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(_cash(self.uid), 1000, places=2,
                               msg="después del doble click y el borrado quedó plata inventada")


# ═════════════════════════════════════════════════════════════════════════════
class H_DosSumasAlMismoSaldo(unittest.TestCase):
    """`_adjust_broker_cash` es la ÚNICA puerta por la que se mueve el efectivo
    (34 llamadores: altas, ediciones, borrados, deshacer, plazos fijos, bonos,
    conversiones, el importador). Si dos movimientos del mismo broker se cruzan,
    tienen que contar los dos.

    Antes leía el saldo, sumaba en Python y escribía el resultado: el segundo en
    escribir pisaba al primero con una cuenta hecha sobre el saldo viejo.

    Se prueba la función y no un endpoint porque el hueco estaba ADENTRO de ella,
    entre su lectura y su escritura: no hay ningún paso de por medio donde un
    endpoint deje meter la espera. Las dos conexiones son reales y commitean de
    verdad, como dos pedidos del threadpool."""

    def setUp(self):
        self.uid, _ = _usuario()

    def test_dos_movimientos_que_se_cruzan_cuentan_los_dos(self):
        barrera = threading.Barrier(2, timeout=3)

        class _Leido:
            def __init__(self, filas):
                self._filas = filas

            def fetchone(self):
                return self._filas[0] if self._filas else None

            def fetchall(self):
                return list(self._filas)

        class ConexionQueSeCruza:
            """Igual que la conexión real; sólo que después de LEER el saldo de
            efectivo espera a que la otra también lo haya leído."""
            def __init__(self, conn):
                self._c = conn

            def execute(self, sql, params=()):
                cur = self._c.execute(sql, params)
                s = " ".join(sql.split()).upper()
                if s.startswith("SELECT") and "FROM POSITIONS" in s and "IS_CASH=1" in s:
                    filas = cur.fetchall()
                    try:
                        barrera.wait()
                    except threading.BrokenBarrierError:
                        pass
                    return _Leido(filas)
                return cur

            def __getattr__(self, nombre):
                return getattr(self._c, nombre)

        errores = []

        def mover(delta):
            conn = main.get_db()
            try:
                main._adjust_broker_cash(ConexionQueSeCruza(conn), self.uid, "Schwab", delta)
                conn.commit()
            except Exception as ex:      # pragma: no cover
                errores.append(ex)
            finally:
                conn.close()

        hilos = [threading.Thread(target=mover, args=(d,)) for d in (200, 300)]
        [t.start() for t in hilos]
        [t.join() for t in hilos]
        self.assertFalse(errores, errores)
        self.assertAlmostEqual(_cash(self.uid), 1500, places=2,
                               msg="dos movimientos simultáneos y uno se perdió")


# ═════════════════════════════════════════════════════════════════════════════
class G_OperacionesQueNoSonMias(unittest.TestCase):
    def setUp(self):
        self.client = _cliente()
        self.uid, self.h = _usuario()
        self.otro_uid, self.otro_h = _usuario()

    def test_prender_el_efectivo_sobre_una_operacion_inexistente_no_crea_plata(self):
        antes = _cash(self.uid)
        r = self.client.put("/api/operations/99999999", headers=self.h,
                            json=_op(mueve_efectivo=True))
        self.assertEqual(r.status_code, 404, r.text)
        self.assertAlmostEqual(_cash(self.uid), antes, places=2,
                               msg="movió plata por una operación que no existe")

    def test_prender_el_efectivo_sobre_la_operacion_de_OTRO_no_toca_nada(self):
        r = self.client.post("/api/operations", headers=self.otro_h, json=_op(mueve_efectivo=False))
        ajena = r.json()["id"]
        mi_saldo, su_saldo = _cash(self.uid), _cash(self.otro_uid)
        r2 = self.client.put(f"/api/operations/{ajena}", headers=self.h,
                             json=_op(mueve_efectivo=True))
        self.assertEqual(r2.status_code, 404, r2.text)
        self.assertAlmostEqual(_cash(self.uid), mi_saldo, places=2)
        self.assertAlmostEqual(_cash(self.otro_uid), su_saldo, places=2)
        self.assertFalse(_meta(ajena).get("cash_on"),
                         "un tercero le prendió el efectivo a una operación ajena")


if __name__ == "__main__":
    unittest.main()
