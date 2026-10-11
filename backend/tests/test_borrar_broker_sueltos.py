"""Borrar un broker se lleva TODO lo que cuelga de su nombre — futuros y secciones
archivadas incluidos — y ninguna puerta escribe en un broker que no existe.

EL BUG (reproducido por HTTP el 2026-10-09). Los datos se atan al broker por su
NOMBRE, no por un id. `delete_broker` y `_wipe_broker_data` ("Limpiar broker")
tenían cada uno su lista de tablas escrita a mano, y `archived_positions`
(06/2026) y `futures_positions` (08/2026) nacieron después y no entraron a
ninguna. Entonces:

  · futuro abierto → borrar el broker → el futuro seguía en GET /api/futures →
    cerrarlo creaba la operación, el mes y +1.000 de efectivo bajo el nombre del
    broker borrado. La ganancia aparecía en "ganancia del mes" y en Movimientos,
    y la plata en ningún lado: el patrimonio recorre la lista de brokers.
  · sección archivada → borrar el broker → restaurar: los bonos volvían a
    `positions` bajo un broker que no existe.
  · re-crear un broker con el mismo nombre "resucitaba" esa plata, con dos cajas.

En la copia de prod del 16/08 había 70 posiciones archivadas así (2 usuarios).

EL ARREGLO, en tres capas, y cada clase de acá fija una:
  1. `BorrarSeLlevaTodo` — una sola función (`_borrar_datos_de_brokers`) para los
     dos caminos de borrado, y el aviso de confirmación cuenta futuros y archivadas.
  2. `NingunaPuertaEscribeEnUnBrokerQueNoExiste` — abrir/editar/cerrar un futuro,
     restaurar una sección, mover una posición, cargar en 'global'.
  3. `UnaSolaLista` — `main.BROKER_POR_NOMBRE` es LA lista; este test recorre el
     esquema y falla si aparece una tabla con columna `broker` que no esté ahí.
     Es lo que habría avisado cuando nacieron las dos tablas.

Todo por HTTP: el borrado pasa por el endpoint, con su recálculo y su limpieza de
fotos, igual que en producción.

Corre con: cd backend && python3 -m pytest tests/test_borrar_broker_sueltos.py
"""
import json
import unittest
import uuid

import main
from fastapi.testclient import TestClient


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        conn = main.get_db()
        # is_admin=1: sin tope de brokers del plan Free (hace falta padre + sub-cuentas
        # y más de un broker). No cambia nada de lo que se prueba acá.
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, is_admin) "
            "VALUES (?, 'x', 1, 1, 1)",
            (f"bbs-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    # ── acciones, siempre por HTTP ───────────────────────────────────────────
    def _broker(self, name, currency="USDT", parent=None):
        body = {"name": name, "currency": currency}
        if parent is not None:
            body["parent_broker_id"] = parent
        r = self.client.post("/api/brokers", headers=self.h, json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def _depositar(self, broker, monto=1000):
        r = self.client.post("/api/cash/flow", headers=self.h, json={
            "broker_name": broker, "direction": "deposit", "amount": monto,
            "date": "2026-08-15"})
        self.assertEqual(r.status_code, 200, r.text)

    def _futuro(self, broker, symbol="BTCUSDT", esperado=200):
        r = self.client.post("/api/futures", headers=self.h, json={
            "broker": broker, "symbol": symbol, "side": "long", "quantity": 0.1,
            "entry_price": 60000, "opened_at": "2026-09-01"})
        self.assertEqual(r.status_code, esperado, r.text)
        return r.json().get("id") if r.status_code == 200 else None

    def _cerrar(self, fid, precio=70000):
        return self.client.post(f"/api/futures/{fid}/close", headers=self.h,
                                json={"exit_price": precio, "closed_at": "2026-10-01"})

    def _bono(self, broker, asset="AL30"):
        r = self.client.post("/api/positions", headers=self.h, json={
            "broker": broker, "asset": asset, "asset_type": "BOND", "currency": "USD",
            "quantity": 100, "buy_price": 0.6, "invested": 60})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _archivar(self, section="BONO|USD"):
        r = self.client.post("/api/sections/archive", headers=self.h, json={"section": section})
        self.assertEqual(r.status_code, 200, r.text)

    def _archivadas(self):
        return self.client.get("/api/sections/archived", headers=self.h).json()["archived"]

    def _borrar(self, bid):
        """Como el frontend: primero sin confirmar (409 con el resumen), después
        con `force=true`. Devuelve el resumen que vio el usuario."""
        r = self.client.delete(f"/api/brokers/{bid}", headers=self.h)
        self.assertEqual(r.status_code, 409, r.text)
        counts = r.json()["detail"]["counts"]
        r = self.client.delete(f"/api/brokers/{bid}?force=true", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return counts

    # ── lo que se mira ───────────────────────────────────────────────────────
    def _q(self, sql, *args):
        conn = main.get_db()
        try:
            return [dict(r) for r in conn.execute(sql, (self.uid, *args)).fetchall()]
        finally:
            conn.close()

    def _sueltas(self):
        """Filas VIVAS bajo un nombre que hoy no es un broker del usuario. Recorre
        `main.BROKER_POR_NOMBRE`: una tabla nueva en la lista queda vigilada sola."""
        conn = main.get_db()
        try:
            brokers = {r["name"] for r in conn.execute(
                "SELECT name FROM brokers WHERE user_id=?", (self.uid,))}
            out = {}
            for tabla, (_ren, al_borrar) in main.BROKER_POR_NOMBRE.items():
                if al_borrar == "borrar":
                    filas = conn.execute(
                        f"SELECT broker, COUNT(*) n FROM {tabla} WHERE user_id=? GROUP BY broker",
                        (self.uid,)).fetchall()
                elif al_borrar == "anular":
                    filas = conn.execute(
                        f"SELECT broker, COUNT(*) n FROM {tabla} "
                        " WHERE user_id=? AND anulado_at IS NULL GROUP BY broker",
                        (self.uid,)).fetchall()
                elif al_borrar == "payload":
                    cuenta = {}
                    for a in conn.execute(
                            f"SELECT payload FROM {tabla} WHERE user_id=?", (self.uid,)):
                        for it in json.loads(a["payload"]):
                            cuenta[it.get("broker")] = cuenta.get(it.get("broker"), 0) + 1
                    filas = [{"broker": b, "n": n} for b, n in cuenta.items()]
                else:
                    continue
                malas = {f["broker"]: f["n"] for f in filas
                         if f["broker"] not in brokers and f["broker"] != "global"}
                if malas:
                    out[tabla] = malas
            return out
        finally:
            conn.close()

    def _cajas(self):
        return self._q("SELECT broker, invested FROM positions WHERE user_id=? AND is_cash=1")


# ═════════════════════════════════════════════════════════════════════════════
class BorrarSeLlevaTodo(_Base):

    def test_futuro_abierto_se_va_con_el_broker(self):
        """REGRESIÓN. Antes: el futuro quedaba, y cerrarlo daba 200 con +1.000 a una
        caja 'Binance' que ya no era un broker."""
        bid = self._broker("Binance")
        self._depositar("Binance")
        fid = self._futuro("Binance")

        counts = self._borrar(bid)
        self.assertEqual(counts["futures"], 1, "el aviso tiene que nombrar el futuro abierto")

        self.assertEqual(self.client.get("/api/futures", headers=self.h).json(), [])
        self.assertEqual(self._cerrar(fid).status_code, 404)
        self.assertEqual(self._sueltas(), {})
        self.assertEqual(self._cajas(), [], "no puede quedar efectivo de un broker borrado")
        self.assertEqual(self.client.get("/api/operations", headers=self.h).json(), [])
        self.assertEqual(
            self._q("SELECT pnl_realized FROM monthly_entries WHERE user_id=? "
                    "AND broker='global' AND COALESCE(pnl_realized,0)!=0"), [],
            "la ganancia de un futuro que ya no existe no puede figurar en el mes")

    def test_recrear_el_broker_no_resucita_nada(self):
        """Antes: el 'Binance' nuevo nacía con la caja fantasma del viejo (dos cajas)."""
        bid = self._broker("Binance")
        self._depositar("Binance")
        fid = self._futuro("Binance")
        self._borrar(bid)
        self._cerrar(fid)
        self._broker("Binance")
        self.assertEqual(self._cajas(), [{"broker": "Binance", "invested": 0.0}])
        self.assertEqual(self.client.get("/api/futures", headers=self.h).json(), [])

    def test_futuro_cerrado_tambien_se_va(self):
        """Un futuro cerrado es historia de un broker que se borra entero: su
        operación se va con el broker, su fila en futures_positions también."""
        bid = self._broker("Binance")
        self._depositar("Binance")
        fid = self._futuro("Binance")
        self.assertEqual(self._cerrar(fid).status_code, 200)
        counts = self._borrar(bid)
        self.assertEqual(counts["futures"], 0, "el cerrado no se anuncia como abierto")
        self.assertEqual(
            self.client.get("/api/futures?include_closed=true", headers=self.h).json(), [])
        self.assertEqual(self._sueltas(), {})

    def test_futuro_en_la_subcuenta_se_va_al_borrar_el_padre(self):
        bid = self._broker("Cocos", "ARS")
        self._broker("Cocos · USD", "USD", parent=bid)
        fid = self._futuro("Cocos · USD", "DLR/OCT26")
        counts = self._borrar(bid)
        self.assertEqual(counts["futures"], 1)
        self.assertEqual(self.client.get("/api/futures", headers=self.h).json(), [])
        self.assertEqual(self._cerrar(fid).status_code, 404)
        self.assertEqual(self._sueltas(), {})

    def test_el_futuro_de_OTRO_broker_no_se_toca(self):
        """Control: el borrado es por nombre de broker, no por usuario."""
        bid = self._broker("Binance")
        self._broker("Bybit")
        self._depositar("Binance")
        self._futuro("Binance")
        otro = self._futuro("Bybit", "ETHUSDT")
        self._borrar(bid)
        vivos = self.client.get("/api/futures", headers=self.h).json()
        self.assertEqual([(f["id"], f["broker"]) for f in vivos], [(otro, "Bybit")])
        self.assertEqual(self._cerrar(otro).status_code, 200)
        self.assertEqual(self._sueltas(), {})

    def test_seccion_archivada_se_va_con_el_broker(self):
        """REGRESIÓN. Antes: seguía ofrecida, y restaurarla re-insertaba los bonos
        bajo un broker inexistente."""
        bid = self._broker("IEB", "USD")
        self._depositar("IEB", 500)
        self._bono("IEB")
        self._archivar()
        self.assertEqual(len(self._archivadas()), 1)

        counts = self._borrar(bid)
        self.assertEqual(counts["archived"], 1, "el aviso tiene que contar lo archivado")
        self.assertEqual(self._archivadas(), [])
        self.assertEqual(self._sueltas(), {})

    def test_seccion_con_dos_brokers_conserva_lo_del_otro(self):
        """'Bonos USD' se archiva entera: puede mezclar brokers. Al borrar uno se
        van SUS bonos; los del otro siguen restaurables, con el conteo corregido."""
        a = self._broker("IEB", "USD")
        self._broker("Balanz", "USD")
        self._depositar("IEB", 500)
        self._depositar("Balanz", 500)
        self._bono("IEB", "AL30")
        self._bono("Balanz", "GD30")
        self._archivar()
        self.assertEqual(self._archivadas()[0]["count"], 2)

        counts = self._borrar(a)
        self.assertEqual(counts["archived"], 1)
        arch = self._archivadas()
        self.assertEqual([x["count"] for x in arch], [1])

        r = self.client.post("/api/sections/restore", headers=self.h,
                             json={"archive_id": arch[0]["id"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["restored"], 1)
        vueltas = self._q("SELECT broker, asset FROM positions WHERE user_id=? AND is_cash=0")
        self.assertEqual(vueltas, [{"broker": "Balanz", "asset": "GD30"}])
        self.assertEqual(self._sueltas(), {})

    def test_cupones_y_dividendos_salteados_se_van(self):
        """Marcas "no lo cobré" atadas al nombre: si quedaban, un broker nuevo con
        el mismo nombre heredaba cobros escondidos sin que nadie lo decidiera."""
        bid = self._broker("IEB", "USD")
        r = self.client.post("/api/bonds/cashflow/skip", headers=self.h, json={
            "broker": "IEB", "asset": "AL30", "date": "2026-07-09"})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/dividendos/saltear", headers=self.h, json={
            "broker": "IEB", "asset": "KO", "ex_date": "2026-06-13"})
        self.assertEqual(r.status_code, 200, r.text)
        self._borrar(bid)
        self.assertEqual(self._q("SELECT * FROM bond_cashflow_skips WHERE user_id=?"), [])
        self.assertEqual(self._q("SELECT * FROM dividendos_salteados WHERE user_id=?"), [])

    def test_renombrar_y_despues_borrar_no_deja_nada(self):
        """Los dos arreglos juntos. El renombre reescribe el nombre adentro del
        futuro y del payload archivado; el borrado, que busca por el nombre de HOY,
        tiene que encontrarlos. (Antes de juntarlos, cada uno por separado dejaba
        el futuro y la sección bajo el nombre viejo.)"""
        bid = self._broker("Cocos", "USD")
        self._depositar("Cocos", 500)
        self._bono("Cocos")
        self._archivar()
        fid = self._futuro("Cocos")
        r = self.client.put(f"/api/brokers/{bid}", headers=self.h,
                            json={"name": "Cocos Capital", "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)

        counts = self._borrar(bid)
        self.assertEqual((counts["futures"], counts["archived"]), (1, 1))
        self.assertEqual(self.client.get("/api/futures", headers=self.h).json(), [])
        self.assertEqual(self._archivadas(), [])
        self.assertEqual(self._cerrar(fid).status_code, 404)
        self.assertEqual(self._sueltas(), {})

    # ── el OTRO camino que borra brokers ─────────────────────────────────────
    def test_limpiar_broker_hace_lo_mismo(self):
        """`POST /api/imports/wipe-broker` borra el broker por su cuenta. Era una
        segunda copia de la lista de tablas, con los mismos dos huecos."""
        self._broker("Binance", "USD")
        self._depositar("Binance")
        fid = self._futuro("Binance")
        self._bono("Binance")
        self._archivar()

        r = self.client.post("/api/imports/wipe-broker?broker=Binance", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["futures_deleted"], 1)
        self.assertEqual(r.json()["archived_deleted"], 1)

        self.assertEqual(self.client.get("/api/brokers", headers=self.h).json(), [])
        self.assertEqual(self.client.get("/api/futures", headers=self.h).json(), [])
        self.assertEqual(self._archivadas(), [])
        self.assertEqual(self._cerrar(fid).status_code, 404)
        self.assertEqual(self._sueltas(), {})

    def test_limpiar_broker_con_dos_subcuentas(self):
        """`delete_broker` ya juntaba TODAS las sub-cuentas (fetchall); la copia de
        "Limpiar broker" seguía con fetchone y dejaba huérfana la segunda."""
        bid = self._broker("Cocos", "ARS")
        self._broker("Cocos · USD", "USD", parent=bid)
        self._broker("Cocos · Cable", "USD", parent=bid)
        self._depositar("Cocos · USD", 100)
        self._depositar("Cocos · Cable", 100)

        r = self.client.post("/api/imports/wipe-broker?broker=Cocos", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        # No se afirma `brokers_deleted`: en una base nueva la FK borra las
        # sub-cuentas en cascada y no las cuenta. Lo que importa son sus DATOS.
        self.assertEqual(self.client.get("/api/brokers", headers=self.h).json(), [])
        self.assertEqual(self._sueltas(), {})
        self.assertEqual(self._cajas(), [])

    # ── guardián por VALOR ───────────────────────────────────────────────────
    def test_el_nombre_no_queda_en_ninguna_tabla_de_cartera(self):
        """Después de borrar, el nombre del broker no puede aparecer en NINGUNA
        columna de texto de las tablas del usuario — salvo en las que la lista
        declara que se conservan como historia (y no mueven ningún número).

        Mira TODAS las tablas con user_id, no sólo las de la lista: si mañana una
        tabla guarda el nombre adentro de un JSON y nadie la declara, esto la ve."""
        nombre = "Zeta Único 7731"
        bid = self._broker(nombre, "USD")
        self._depositar(nombre, 500)
        self._bono(nombre, "AL30")
        self._bono(nombre, "GD30")
        self._archivar()
        self._bono(nombre, "AE38")
        self._futuro(nombre)
        self._cerrar(self._futuro(nombre, "ETHUSDT"), precio=61000)
        self.client.post("/api/bonds/cashflow/skip", headers=self.h, json={
            "broker": nombre, "asset": "AE38", "date": "2026-07-09"})
        self.client.post("/api/dividendos/saltear", headers=self.h, json={
            "broker": nombre, "asset": "KO", "ex_date": "2026-06-13"})
        self._borrar(bid)

        conn = main.get_db()
        try:
            apariciones = {}
            tablas = [r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
            for t in tablas:
                cols = [c["name"] for c in conn.execute(f"PRAGMA table_info({t})")]
                if "user_id" not in cols:
                    continue
                for fila in conn.execute(f"SELECT * FROM {t} WHERE user_id=?", (self.uid,)):
                    if any(isinstance(v, str) and nombre in v for v in tuple(fila)):
                        apariciones[t] = apariciones.get(t, 0) + 1
        finally:
            conn.close()

        se_conservan = {t for t, (_r, al_borrar) in main.BROKER_POR_NOMBRE.items()
                        if al_borrar in ("conservar", "anular", "revertir")}
        self.assertEqual(set(apariciones) - se_conservan, set(),
                         f"el nombre del broker borrado sigue vivo en: {apariciones}")
        # Y las anuladas están anuladas de verdad, no vivas.
        self.assertEqual(self._sueltas(), {})


# ═════════════════════════════════════════════════════════════════════════════
class NingunaPuertaEscribeEnUnBrokerQueNoExiste(_Base):

    def test_no_se_abre_un_futuro_en_un_broker_que_no_existe(self):
        self._futuro("NoExiste", esperado=400)
        self.assertEqual(self._q("SELECT id FROM futures_positions WHERE user_id=?"), [])

    def test_no_se_abre_un_futuro_en_global(self):
        """'global' es la fila de totales, no un broker."""
        self._futuro("global", esperado=400)

    def test_no_se_edita_un_futuro_hacia_un_broker_que_no_existe(self):
        self._broker("Binance")
        fid = self._futuro("Binance")
        r = self.client.put(f"/api/futures/{fid}", headers=self.h, json={
            "broker": "NoExiste", "symbol": "BTCUSDT", "side": "long", "quantity": 0.1,
            "entry_price": 60000, "opened_at": "2026-09-01"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self._q("SELECT broker FROM futures_positions WHERE user_id=?"),
                         [{"broker": "Binance"}])

    def test_editar_un_futuro_sin_cambiarle_el_broker_sigue_andando(self):
        self._broker("Binance")
        fid = self._futuro("Binance")
        r = self.client.put(f"/api/futures/{fid}", headers=self.h, json={
            "broker": "Binance", "symbol": "BTCUSDT", "side": "long", "quantity": 0.2,
            "entry_price": 61000, "opened_at": "2026-09-01"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["quantity"], 0.2)

    def test_cerrar_un_futuro_de_un_broker_que_ya_no_existe_no_escribe_nada(self):
        """El futuro que quedó suelto ANTES de este arreglo (o de un renombre): el
        estado viejo se planta por SQL porque ya no hay camino HTTP que lo cree."""
        conn = main.get_db()
        fid = conn.execute(
            """INSERT INTO futures_positions
                 (user_id, broker, symbol, base_asset, side, quantity, entry_price, opened_at)
               VALUES (?, 'Borrado', 'BTCUSDT', 'BTC', 'long', 0.1, 60000, '2026-09-01')""",
            (self.uid,)).lastrowid
        conn.commit()
        conn.close()

        r = self._cerrar(fid)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("Borrado", r.json()["detail"])
        self.assertEqual(
            self._q("SELECT closed_at FROM futures_positions WHERE user_id=?"),
            [{"closed_at": None}], "un cierre rechazado no puede dejarlo cerrado")
        self.assertEqual(self._q("SELECT id FROM operations WHERE user_id=?"), [])
        self.assertEqual(self._q("SELECT id FROM positions WHERE user_id=?"), [])
        self.assertEqual(self._q("SELECT id FROM monthly_entries WHERE user_id=?"), [])
        # Y se puede sacar de la lista.
        self.assertEqual(
            self.client.delete(f"/api/futures/{fid}", headers=self.h).status_code, 200)

    def test_el_futuro_sano_se_sigue_cerrando(self):
        """Control del freno: con el broker vivo, el cierre acredita como siempre."""
        self._broker("Binance")
        self._depositar("Binance")
        fid = self._futuro("Binance")
        r = self._cerrar(fid)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["pnl_usd"], 1000.0)
        self.assertEqual(self._cajas(), [{"broker": "Binance", "invested": 2000.0}])

    def test_renombrar_no_dispara_los_frenos(self):
        """Control: después de renombrar, el broker guardado en el futuro y en la
        sección archivada SÍ existe (el renombre lo reescribe). Cerrar y restaurar
        tienen que andar, y la plata tiene que caer en el nombre de hoy."""
        bid = self._broker("Cocos", "USD")
        self._depositar("Cocos", 500)
        self._bono("Cocos")
        self._archivar()
        fid = self._futuro("Cocos")
        r = self.client.put(f"/api/brokers/{bid}", headers=self.h,
                            json={"name": "Cocos Capital", "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)

        self.assertEqual(self._cerrar(fid).status_code, 200)
        r = self.client.post("/api/sections/restore", headers=self.h,
                             json={"archive_id": self._archivadas()[0]["id"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._sueltas(), {})
        self.assertEqual({c["broker"] for c in self._cajas()}, {"Cocos Capital"})

    def test_el_turno_se_toma_antes_de_mirar_si_el_broker_existe(self):
        """sqlite3 abre la transacción en la primera ESCRITURA. Si la puerta mira
        "¿existe el broker?" antes de escribir algo, un renombre o un borrado en ese
        mismo instante (otra pestaña) entra entre la mirada y la escritura, y la
        fila queda bajo el nombre que acaba de dejar de existir. Por eso cada
        puerta toma el turno de escritura (`_tomar_turno`) ANTES de mirar.

        Se mide el ORDEN de las dos llamadas dentro de cada pedido HTTP."""
        self._broker("IEB", "USD")
        self._broker("Balanz", "USD")
        self._depositar("IEB", 500)
        p = self._bono("IEB")
        self._archivar()
        aid = self._archivadas()[0]["id"]
        p2 = self._bono("IEB", "GD30")
        fid = self._futuro("IEB")
        fut = {"broker": "IEB", "symbol": "BTCUSDT", "side": "long", "quantity": 0.1,
               "entry_price": 60000, "opened_at": "2026-09-01"}
        pos = {"asset": "GD30", "quantity": 100, "buy_price": 0.6, "invested": 60}

        puertas = {
            "cargar posición": lambda: self.client.post(
                "/api/positions", headers=self.h, json={**pos, "broker": "IEB", "asset": "AE38",
                                                        "asset_type": "BOND", "currency": "USD"}),
            "mover posición": lambda: self.client.put(
                f"/api/positions/{p2['id']}", headers=self.h, json={**pos, "broker": "Balanz"}),
            "abrir futuro": lambda: self.client.post("/api/futures", headers=self.h, json=fut),
            "editar futuro": lambda: self.client.put(
                f"/api/futures/{fid}", headers=self.h, json={**fut, "quantity": 0.2}),
            "cerrar futuro": lambda: self._cerrar(fid),
            "restaurar sección": lambda: self.client.post(
                "/api/sections/restore", headers=self.h, json={"archive_id": aid}),
        }
        turno, existe = main._tomar_turno, main._broker_existe
        try:
            for nombre, pedir in puertas.items():
                orden = []
                main._tomar_turno = lambda c, u, _o=orden: (_o.append("turno"), turno(c, u))[1]
                main._broker_existe = lambda c, u, b, _o=orden: (_o.append("mira"), existe(c, u, b))[1]
                r = pedir()
                self.assertEqual(r.status_code, 200, f"{nombre}: {r.text}")
                self.assertIn("mira", orden, f"{nombre}: no chequea que el broker exista")
                self.assertIn("turno", orden, f"{nombre}: no toma el turno")
                self.assertLess(orden.index("turno"), orden.index("mira"),
                                f"{nombre}: mira si el broker existe ANTES de tomar el turno")
        finally:
            main._tomar_turno, main._broker_existe = turno, existe

    def test_restaurar_una_seccion_de_un_broker_que_ya_no_existe(self):
        """Las 70 posiciones archivadas de prod: su broker se borró cuando el
        borrado todavía no limpiaba las archivadas. Se planta sacando el broker por
        SQL (el camino HTTP ya no deja este estado)."""
        self._broker("Cocos", "USD")
        self._depositar("Cocos", 500)
        self._bono("Cocos")
        self._archivar()
        conn = main.get_db()
        conn.execute("DELETE FROM positions WHERE user_id=?", (self.uid,))
        conn.execute("DELETE FROM brokers WHERE user_id=?", (self.uid,))
        conn.commit()
        conn.close()
        aid = self._archivadas()[0]["id"]

        r = self.client.post("/api/sections/restore", headers=self.h, json={"archive_id": aid})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("«Cocos»", r.json()["detail"])
        self.assertEqual(self._q("SELECT id FROM positions WHERE user_id=?"), [],
                         "no puede volver nada bajo un broker que no existe")
        self.assertEqual(len(self._archivadas()), 1, "la sección no se pierde")

        # El mensaje promete una salida: crear un broker con ese nombre y reintentar.
        self._broker("Cocos", "USD")
        r = self.client.post("/api/sections/restore", headers=self.h, json={"archive_id": aid})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(
            self._q("SELECT broker, asset FROM positions WHERE user_id=? AND is_cash=0"),
            [{"broker": "Cocos", "asset": "AL30"}])
        self.assertEqual(self._sueltas(), {})

    def test_la_seccion_sana_se_sigue_restaurando(self):
        self._broker("IEB", "USD")
        self._depositar("IEB", 500)
        self._bono("IEB")
        self._archivar()
        r = self.client.post("/api/sections/restore", headers=self.h,
                             json={"archive_id": self._archivadas()[0]["id"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._archivadas(), [])

    def test_no_se_mueve_una_posicion_a_un_broker_que_no_existe(self):
        self._broker("IEB", "USD")
        self._broker("Balanz", "USD")
        self._depositar("IEB", 500)
        p = self._bono("IEB")
        cuerpo = {"broker": "Inventado", "asset": "AL30", "quantity": 100,
                  "buy_price": 0.6, "invested": 60}
        r = self.client.put(f"/api/positions/{p['id']}", headers=self.h, json=cuerpo)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self._q("SELECT broker FROM positions WHERE user_id=? AND id=?", p["id"]),
                         [{"broker": "IEB"}])
        # Sin cambiar de broker, la edición sigue andando…
        r = self.client.put(f"/api/positions/{p['id']}", headers=self.h,
                            json={**cuerpo, "broker": "IEB", "quantity": 150})
        self.assertEqual(r.status_code, 200, r.text)
        # …y moverla a un broker que SÍ existe, también.
        r = self.client.put(f"/api/positions/{p['id']}", headers=self.h,
                            json={**cuerpo, "broker": "Balanz"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._sueltas(), {})

    def test_no_se_carga_una_posicion_en_global(self):
        """El control del alta dejaba pasar 'global' (copiado de /api/monthly, donde
        sí es legítimo): entraba la posición y su caja bajo un nombre sin pantalla."""
        self._broker("IEB", "USD")
        r = self.client.post("/api/positions", headers=self.h, json={
            "broker": "global", "asset": "AAPL", "quantity": 1, "buy_price": 100,
            "invested": 100})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self._q("SELECT id FROM positions WHERE user_id=? AND broker='global'"), [])


# ═════════════════════════════════════════════════════════════════════════════
class UnaSolaLista(unittest.TestCase):
    """`main.BROKER_POR_NOMBRE` es la única lista de tablas atadas al nombre de un
    broker. El renombre y los dos borrados salen de ahí."""

    def _columnas(self):
        conn = main.get_db()
        try:
            return {t["name"]: [c["name"] for c in conn.execute(f"PRAGMA table_info({t['name']})")]
                    for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()

    def test_todo_lo_que_el_renombre_toca_tiene_politica_de_borrado(self):
        """El renombre reescribe el nombre en columnas (`NAME_KEYED_TABLES`) y adentro
        de JSON (`renombre_broker.COLUMNAS_JSON`). Todo lugar donde el nombre VIVE
        tiene que decir también qué le pasa cuando el broker se BORRA: si esto
        falla, alguien enseñó al renombre una tabla nueva y el borrado no la conoce
        — así nacieron los futuros y las secciones archivadas sueltos.

        Que ninguna tabla con columna `broker` quede fuera de `NAME_KEYED_TABLES` lo
        vigila `test_renombre_broker_recetas.py::CadaColumnaDeBrokerSeRenombra`
        recorriendo el esquema; como esa tupla sale de `BROKER_POR_NOMBRE`, una
        tabla nueva entra por un solo lugar y queda cubierta de los dos lados."""
        import renombre_broker
        donde_vive = set(main.NAME_KEYED_TABLES) | {t for t, _col in renombre_broker.COLUMNAS_JSON}
        faltan = donde_vive - set(main.BROKER_POR_NOMBRE)
        self.assertEqual(faltan, set(),
                         f"el renombre conoce estas tablas y el borrado no: {faltan}")
        # Y al revés: lo que la lista dice que se renombra "por json" lo hace alguien.
        con_json = {t for t, _col in renombre_broker.COLUMNAS_JSON}
        for tabla, (al_renombrar, _b) in main.BROKER_POR_NOMBRE.items():
            if al_renombrar == "json":
                self.assertIn(tabla, con_json, f"{tabla}: nadie le reescribe el JSON")

    def test_la_lista_no_nombra_tablas_ni_columnas_que_no_existen(self):
        cols = self._columnas()
        for tabla, (al_renombrar, al_borrar) in main.BROKER_POR_NOMBRE.items():
            self.assertIn(tabla, cols, f"{tabla} no existe")
            if al_renombrar == "columna":
                self.assertIn("broker", cols[tabla], f"{tabla} no tiene columna broker")
            if al_borrar in ("borrar", "anular", "revertir", "payload"):
                self.assertIn("user_id", cols[tabla],
                              f"{tabla} se toca por user_id y no tiene esa columna")
            if al_borrar == "borrar":
                self.assertIn("broker", cols[tabla],
                              f"{tabla} se borra por columna broker y no la tiene")

    def test_politicas_conocidas(self):
        """Tres políticas tienen código propio atado a UNA tabla. Usarlas en otra
        no haría nada sobre esa otra tabla (y parecería cubierta)."""
        propias = {"anular": "flujos_a_mano", "revertir": "import_batches",
                   "payload": "archived_positions"}
        for tabla, (al_renombrar, al_borrar) in main.BROKER_POR_NOMBRE.items():
            self.assertIn(al_renombrar, ("columna", "json"), tabla)
            self.assertIn(al_borrar, ("borrar", "conservar", *propias), tabla)
            if al_borrar in propias:
                self.assertEqual(tabla, propias[al_borrar])

    def test_el_renombre_sale_de_la_misma_lista(self):
        self.assertEqual(
            main.NAME_KEYED_TABLES,
            tuple(t for t, (ren, _b) in main.BROKER_POR_NOMBRE.items() if ren == "columna"))
        # Las que ya se renombraban antes de unificar: ninguna se puede caer.
        for t in ("positions", "operations", "monthly_entries", "import_batches",
                  "import_normalized_tx", "bond_cashflow_skips", "dividendos_salteados",
                  "flujos_a_mano", "futures_positions", "deleted_ops_journal"):
            self.assertIn(t, main.NAME_KEYED_TABLES)

    def test_empezar_de_cero_tambien_las_cubre(self):
        """La tercera lista (el reset) es un allowlist aparte a propósito. Esto la
        ata a la lista única: lo que cuelga de un broker tiene que irse con el
        reset. Las de import van por su propio paso del reset (por batch)."""
        por_su_cuenta = {"import_batches", "import_normalized_tx"}
        faltan = set(main.BROKER_POR_NOMBRE) - set(main._RESET_PORTFOLIO_TABLES) - por_su_cuenta
        self.assertEqual(faltan, set())


if __name__ == "__main__":
    unittest.main()
