"""Borrar algo NO puede aplanar el día en que entró la plata.

El aportado de cada foto diaria tiene resolución de DÍA por una sola razón: la
foto de esa noche lo anotó con lo que estaba cargado en ese momento. Los totales
de `monthly_entries` no dicen en qué día del mes entró un depósito, así que
ninguna fórmula puede volver a generarlo después. Si algo lo pisa con un valor
por mes, se pierde para siempre.

`_cascade_after_movement_delete` corre al borrar un movimiento, una operación, una
posición o el historial de un activo, y al deshacer esos borrados. Re-estampaba
`net_deposited` con `compute_net_deposited_db(as_of_date=<AAAA-MM>)` —UN valor
por mes— sobre todas las fotos desde la fecha de lo borrado, incluidas las del
cron. Un depósito del día 20 pasaba a figurar desde el día 1: del 1 al 19 la
pantalla publicaba una pérdida del tamaño del depósito, y el 20 la "ganancia" de
vuelta. Pasaba aunque lo borrado no tuviera nada que ver con depósitos (borrar una
compra de hace dos años aplanaba todos los meses con flujos desde entonces).

Después re-anclaba el mes a su última foto (`_recompute_snapshots_netdep_for_user`),
que conserva el día mientras esa foto sepa todos los flujos del mes. Cuando no los
sabía —un depósito cargado hoy después de la foto de hoy, un import a mitad de
mes— el mes se reescribía mal igual. Hoy aplica sólo el cambio del borrado y sólo
a las fotos que tenían lo borrado (`_cambio_de_aportado`); la sección 9 fija esos
casos.

⚠️ El test que decía vigilar esto (`test_audit_ronda5.ReEstampadoPorMesEsInocuoTest`)
llama a `_recompute_snapshots_netdep_for_user` DIRECTO: nunca pasa por la cascada,
así que certificaba en verde lo contrario de lo que corría en producción. Estos
entran por las MISMAS puertas HTTP que usa la app; lo único que se reemplaza es el
login (`dependency_overrides`), que no toca nada de lo que se mide.

La cuenta de laboratorio tiene el mercado QUIETO: cada foto vale exactamente lo
aportado ese día. Cualquier ganancia o pérdida que aparezca es inventada.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from fastapi.testclient import TestClient

from importing import pipeline as pl
from importing import persister as ps
from importing import rebuild as rb
import main
import twr
from reporting import builder

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


def _csv(*rows: str) -> bytes:
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


def _helpers():
    h = main._ImportHelpers()
    for n in ("_adjust_broker_cash", "_adjust_cash", "_update_monthly_pnl_realized",
              "_update_monthly_flow", "_repair_monthly_chain", "_ensure_usd_sibling",
              "_recalc_pnl_realized_from_ops"):
        setattr(h, n, getattr(main, n))
    return h


def _dias(y, m, d0, d1):
    return [f"{y:04d}-{m:02d}-{d:02d}" for d in range(d0, d1 + 1)]


# Lo que la foto de cada noche habría anotado como aportado ese día.
#   2025-12-02  depósito 100.000      2026-02-20  depósito 10.000
#   2026-03-10  retiro 4.000
APORTADO_DEL_DIA = {}
for _d in _dias(2026, 1, 1, 31):
    APORTADO_DEL_DIA[_d] = 100000.0
for _d in _dias(2026, 2, 1, 19):
    APORTADO_DEL_DIA[_d] = 100000.0
for _d in _dias(2026, 2, 20, 28):
    APORTADO_DEL_DIA[_d] = 110000.0
for _d in _dias(2026, 3, 1, 9):
    APORTADO_DEL_DIA[_d] = 110000.0
for _d in _dias(2026, 3, 10, 31):
    APORTADO_DEL_DIA[_d] = 106000.0


class BorrarConservaElDia(unittest.TestCase):
    BROKER = "IBKR"

    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "deleted_ops_journal", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("borrar_dia@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, self.BROKER, "USDT"))
        self.conn.commit()
        self._import(_csv(
            "2025-12-02,DEPOSITO,IBKR,,,,100000,,,0,USD,",
            "2025-12-03,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,",
            # MSFT sin dividendos: la app no deja borrar de a una compra un activo
            # con dividendos enlazados (400), y eso no es lo que se mide acá.
            "2025-12-04,COMPRA,IBKR,MSFT,5,300,1500,,,0,USD,",
            "2025-12-10,DIVIDENDO,IBKR,AAPL,,,50,,,0,USD,",
            "2026-02-20,DEPOSITO,IBKR,,,,10000,,,0,USD,",
            "2026-03-10,RETIRO,IBKR,,,,4000,,,0,USD,",
            "2026-03-15,DIVIDENDO,IBKR,AAPL,,,30,,,0,USD,",
        ))
        # Las fotos del cron, con el mismo UPSERT que `snapshots_job` (pisa la
        # sintética de fin de mes que el import dejó en esa fecha).
        for d, nd in APORTADO_DEL_DIA.items():
            self.conn.execute(
                """INSERT INTO snapshots (user_id, date, total_value, total_invested,
                       net_deposited, fx_to_usd_blue, holdings_json, source, base, apto)
                   VALUES (?,?,?,?,?,1200,'[{"a":"AAPL"}]','cron','mercado',1)
                   ON CONFLICT(user_id, date) DO UPDATE SET
                       total_value=excluded.total_value,
                       total_invested=excluded.total_invested,
                       net_deposited=excluded.net_deposited,
                       fx_to_usd_blue=excluded.fx_to_usd_blue,
                       holdings_json=excluded.holdings_json,
                       source='cron', base='mercado', apto=1""",
                (self.uid, d, nd, nd, nd))
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.client = TestClient(main.app)
        # Control del fixture: ANTES de borrar nada la cuenta ya publica 0. Si esto
        # falla, el rojo de abajo no diría nada sobre el borrado.
        self.assertEqual(self._aportado_servido(), APORTADO_DEL_DIA)
        self._assert_pantalla_en_cero("antes de borrar")

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        self.conn.close()

    # ── infra ────────────────────────────────────────────────────────────────
    def _import(self, csv_bytes: bytes) -> None:
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=csv_bytes, file_name="x.csv",
                broker_hint=self.BROKER, parser_format="rendi_generic")
        sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid,
                                         tc_blue=ps._read_tc_blue(self.conn, uid=self.uid))
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)

    def _tx(self, op_type: str, fecha: str) -> int:
        r = self.conn.execute(
            "SELECT n.id FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id "
            "WHERE b.user_id=? AND n.operation_type=? AND n.date=? AND n.excluded_at IS NULL",
            (self.uid, op_type, fecha)).fetchone()
        self.assertIsNotNone(r, f"no encontré el {op_type} del {fecha}")
        return r["id"]

    def _aportado_servido(self) -> dict:
        """Lo que recibe el Dashboard: `GET /api/snapshots`, fotos del cron."""
        r = self.client.get("/api/snapshots", params={"days": 3650})
        self.assertEqual(r.status_code, 200, r.text)
        return {p["date"]: float(p["net_deposited"]) for p in r.json()
                if p["date"] in APORTADO_DEL_DIA}

    def _assert_pantalla_en_cero(self, cuando: str):
        """Con el mercado quieto, todo lo que publica rendimiento tiene que dar 0.
        Junta TODOS los números que se apartan antes de fallar: el mensaje es el
        inventario de qué pantalla miente y por cuánto."""
        mal = []
        fotos = {p["date"]: p for p in self.client.get(
            "/api/snapshots", params={"days": 3650}).json()}

        # 1) El chip del Dashboard: Δ(valor − aportado) entre dos fotos servidas.
        for a, b in (("2026-02-01", "2026-02-28"),     # "desde el 1 del mes"
                     ("2026-02-01", "2026-02-19"),
                     ("2026-02-19", "2026-02-20"),     # el día del depósito
                     ("2026-03-01", "2026-03-31"),
                     ("2026-02-15", "2026-03-15")):
            pa, pb = fotos[a], fotos[b]
            res = ((pb["total_value"] - pb["net_deposited"])
                   - (pa["total_value"] - pa["net_deposited"]))
            if abs(res) > 0.005:
                mal.append(f"chip del Dashboard {a}→{b}: US$ {res:+,.2f}")

        # 2) La versión del servidor del mismo chip (Reportes, el chat, el ✦).
        for hasta, dias in (("2026-03-31", 30), ("2026-02-28", 27), ("2026-02-25", 7)):
            nd = APORTADO_DEL_DIA[hasta]
            d = main._snapshot_delta(self.conn, self.uid, nd, hasta, dias, latest_netdep=nd)
            # `usd`, no `delta_usd`: con la clave equivocada este chequeo no medía
            # nada (pasaba igual con el chip publicando +10.000). Y None no es 0.
            if d is None:
                mal.append(f"chip del servidor Δ{dias}d al {hasta}: no devolvió nada")
            elif abs(d["usd"]) > 0.005:
                mal.append(f"chip del servidor Δ{dias}d al {hasta}: "
                           f"US$ {d['usd']:+,.2f} ({d['pct']:+}%)")

        # 3) La curva: rendimiento acumulado y peor caída.
        c = twr.curva_indexada(self.conn, self.uid)
        if abs(c["twr"]) > 1e-6:
            mal.append(f"curva: rendimiento acumulado {c['twr']:+.4%}")
        if abs(c["drawdown_maximo"]) > 1e-6:
            mal.append(f"curva: peor caída {c['drawdown_maximo']:+.4%} "
                       f"el {c.get('drawdown_maximo_fecha')}")

        # 4) Reportes: el resultado de cada mes y de un tramo dentro del mes.
        for desde, hasta in (("2026-02-01", "2026-02-28"), ("2026-03-01", "2026-03-31"),
                             ("2026-02-05", "2026-02-25")):
            m, _ = builder.compute_metrics_for_period(
                self.conn, self.uid, "custom", desde, hasta, "global", None)
            # Igual que el chip: None no es 0, y un período "sin base para medir"
            # (`basis_incomparable`) publica 0 a la fuerza sin haber medido nada.
            if m.delta_usd is None or m.basis_incomparable:
                mal.append(f"Reportes {desde}→{hasta}: no midió "
                           f"(delta_usd={m.delta_usd}, sin base={m.basis_incomparable})")
            elif abs(m.delta_usd) > 0.005:
                mal.append(f"Reportes {desde}→{hasta}: US$ {m.delta_usd:+,.2f} "
                           f"({m.delta_pct}%)")
        self.assertEqual(mal, [], f"{cuando}, con el mercado quieto:\n  " + "\n  ".join(mal))

    def _assert_dia_conservado(self, cuando: str, esperado: dict = None):
        """El aportado de cada foto del cron, día por día, es exactamente `esperado`
        (por defecto: lo que el cron anotó, o sea que el borrado no lo tocó)."""
        esperado = esperado or APORTADO_DEL_DIA
        servido = self._aportado_servido()
        rotos = {d: (esperado[d], servido.get(d))
                 for d in esperado if servido.get(d) != esperado[d]}
        self.assertEqual(rotos, {},
                         f"{cuando}: {len(rotos)} fotos del cron con el aportado mal "
                         f"(fecha: (esperado, servido)) — primeras: "
                         f"{dict(list(sorted(rotos.items()))[:4])}")

    # ── 1. borrar un movimiento que no es un depósito ───────────────────────
    def test_borrar_un_dividendo_viejo_no_aplana_los_meses(self):
        r = self.client.delete(f"/api/movements/tx-{self._tx('DIVIDEND', '2025-12-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("después de borrar el dividendo de 2025-12")

    def test_con_el_mercado_quieto_la_pantalla_sigue_en_cero(self):
        r = self.client.delete(f"/api/movements/tx-{self._tx('DIVIDEND', '2025-12-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_pantalla_en_cero("después de borrar el dividendo de 2025-12")

    # ── 2. borrar una compra (otra cascada, misma cola) ──────────────────────
    def test_borrar_una_compra_vieja_no_toca_el_aportado(self):
        r = self.client.delete(f"/api/movements/tx-{self._tx('BUY', '2025-12-04')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("después de borrar la compra de MSFT de 2025-12")
        self._assert_pantalla_en_cero("después de borrar la compra de MSFT de 2025-12")

    def test_borrar_la_posicion_desde_cartera(self):
        pid = self.conn.execute(
            "SELECT id FROM positions WHERE user_id=? AND asset='MSFT' AND is_cash=0",
            (self.uid,)).fetchone()["id"]
        r = self.client.delete(f"/api/positions/{pid}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("después de borrar la posición desde Cartera")

    # ── 3. borrar todo el historial de un activo, y deshacerlo ───────────────
    def test_borrar_el_historial_de_un_activo_y_deshacer(self):
        r = self.client.delete("/api/assets/history", params={"asset": "AAPL"})
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("después de borrar el historial de AAPL")
        token = r.json().get("undo_token")
        self.assertTrue(token, f"el borrado no devolvió con qué deshacer: {r.json()}")
        r = self.client.post(f"/api/assets/undo/{token}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("después de deshacer el borrado de AAPL")
        self._assert_pantalla_en_cero("después de deshacer el borrado de AAPL")

    # ── 4. el alcance: lo anterior a lo borrado no se toca ───────────────────
    def test_no_reescribe_lo_anterior_a_lo_borrado(self):
        """Hoy la cascada sólo re-estampa desde la fecha de lo borrado. Las fotos de
        antes —incluso si tuvieran una estampa vieja— no son asunto de este borrado:
        tocarlas cambiaría meses ya cerrados que el usuario no tocó."""
        self.conn.execute("UPDATE snapshots SET net_deposited=55555 "
                          "WHERE user_id=? AND date LIKE '2026-01-%'", (self.uid,))
        self.conn.commit()
        r = self.client.delete(f"/api/movements/tx-{self._tx('DIVIDEND', '2026-03-15')}")
        self.assertEqual(r.status_code, 200, r.text)
        enero = {row["net_deposited"] for row in self.conn.execute(
            "SELECT net_deposited FROM snapshots WHERE user_id=? AND date LIKE '2026-01-%'",
            (self.uid,))}
        self.assertEqual(enero, {55555.0}, "el borrado de marzo reescribió enero")

    # ── 5. si el cálculo falla, no se toca ninguna foto ─────────────────────
    def test_si_el_calculo_falla_no_se_toca_ninguna_foto(self):
        """Si el cálculo del cambio de aportado falla, ninguna foto se toca. Una
        estampa que quedó con lo borrado adentro se nota y se repara (botón del
        admin); una reescrita mal no tiene vuelta — el anclado, por ejemplo, caía
        sin avisar a `compute_net_deposited_db(as_of_date=<fecha>)`, que trunca a
        MES. Se borra un DEPÓSITO a propósito: con un dividendo no habría nada que
        cambiar y el test pasaría sin probar nada."""
        def _falla(*a, **k):
            raise RuntimeError("simulado: el cambio de aportado no se pudo calcular")
        with mock.patch.object(main, "_cambio_de_aportado", side_effect=_falla) as m:
            r = self.client.delete(
                f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-20')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("con el cálculo fallando")
        # Sin esto el verde no dice nada: si la cascada llegara al cálculo por otro
        # nombre, la falla simulada no lo alcanzaría y el test pasaría sin probarla.
        self.assertTrue(m.called, "la cascada no pasó por el cálculo del cambio")

    def test_el_boton_del_admin_tampoco_aplana_si_el_calculo_falla(self):
        """El mismo atajo corre en el botón de reparación del admin, la reparación de
        historial y la migración del arranque — no sólo en el borrado."""
        def _falla(*a, **k):
            raise RuntimeError("simulado: el aportado anclado no se pudo calcular")
        main.app.dependency_overrides[main.get_admin_user] = lambda: self.uid
        try:
            with mock.patch.object(twr, "_aportado_por_punto", side_effect=_falla) as m:
                r = self.client.post("/api/admin/recompute-snapshots-netdep")
        finally:
            main.app.dependency_overrides.pop(main.get_admin_user, None)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(m.called, "el botón no pasó por el cálculo anclado")
        self._assert_dia_conservado("botón del admin con el cálculo anclado fallando")

    # ── 6. borrar algo que SÍ cambia el aportado ─────────────────────────────
    # Sin estos, "no re-estampar nunca" pasaba todos los tests de arriba: ninguno
    # borraba algo que cambiara lo aportado (auditoría 1, H1).
    def test_borrar_el_deposito_lo_saca_desde_su_dia(self):
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-20')}")
        self.assertEqual(r.status_code, 200, r.text)
        esperado = dict(APORTADO_DEL_DIA)
        for d in _dias(2026, 2, 20, 28) + _dias(2026, 3, 1, 9):
            esperado[d] = 100000.0
        for d in _dias(2026, 3, 10, 31):
            esperado[d] = 96000.0
        self._assert_dia_conservado("después de borrar el depósito del 20-feb", esperado)

    def test_borrar_el_retiro_lo_saca_desde_su_dia(self):
        r = self.client.delete(f"/api/movements/tx-{self._tx('WITHDRAW', '2026-03-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        esperado = dict(APORTADO_DEL_DIA)
        for d in _dias(2026, 3, 10, 31):
            esperado[d] = 110000.0
        self._assert_dia_conservado("después de borrar el retiro del 10-mar", esperado)

    def test_borrar_un_deposito_cargado_a_mano(self):
        """`me-{id}-dep` arranca la cascada el DÍA 1 del mes (no el del movimiento:
        `monthly_entries` no guarda el día), y sí cambia lo aportado."""
        r = self.client.post("/api/cash/flow", json={
            "broker_name": self.BROKER, "direction": "deposit", "amount": 3000,
            "date": "2026-01-15"})
        self.assertEqual(r.status_code, 200, r.text)
        # Lo que el cron habría anotado desde esa noche: +3.000 en adelante.
        for d, nd in APORTADO_DEL_DIA.items():
            if d >= "2026-01-15":
                self.conn.execute(
                    "UPDATE snapshots SET net_deposited=?, total_value=? "
                    "WHERE user_id=? AND date=?", (nd + 3000, nd + 3000, self.uid, d))
        self.conn.commit()
        me = self.conn.execute(
            "SELECT id FROM monthly_entries WHERE user_id=? AND broker=? AND year=2026 "
            "AND month=1 AND manual_deposits > 0", (self.uid, self.BROKER)).fetchone()
        self.assertIsNotNone(me, "el depósito manual no quedó en monthly_entries")
        r = self.client.delete(f"/api/movements/me-{me['id']}-dep")
        self.assertEqual(r.status_code, 200, r.text)
        # Sin el depósito manual, cada foto vuelve a lo que era antes de cargarlo.
        self._assert_dia_conservado("después de borrar el depósito manual del 15-ene")

    # ── 6b. el mes en curso: la foto de HOY es la que sabe lo último ─────────
    def test_depositar_hoy_y_borrar_un_deposito_anterior_del_mes(self):
        """Hoy es 20-mar. El 15 entró un depósito de 10.000 que estaba mal cargado, y
        hoy otro de 5.000 que está bien. La foto de hoy (la guardó el Dashboard
        después de cargar el de hoy) es la única que sabe en qué día entró ESE.
        Borrado el del 15, del 15 al 19 el aportado vuelve a 106.000: el depósito
        de hoy no puede aparecer antes de hoy.

        Fija el ORDEN: la foto de hoy tiene que participar del anclado y borrarse
        recién después. Borrada antes, el ancla del mes pasa a ser la de ayer —que
        no sabe nada del depósito de hoy— y los 5.000 se corren al día 15."""
        hoy = "2026-03-20"
        self.conn.execute("DELETE FROM snapshots WHERE user_id=? AND date > ?",
                          (self.uid, hoy))
        self._import(_csv("2026-03-15,DEPOSITO,IBKR,,,,10000,,,0,USD,",
                          "2026-03-20,DEPOSITO,IBKR,,,,5000,,,0,USD,"))
        for d in _dias(2026, 3, 15, 19):
            self.conn.execute("UPDATE snapshots SET net_deposited=116000, total_value=116000 "
                              "WHERE user_id=? AND date=?", (self.uid, d))
        self.conn.execute(
            "UPDATE snapshots SET net_deposited=121000, total_value=121000, source='browser', "
            "apto=0, holdings_json=NULL WHERE user_id=? AND date=?", (self.uid, hoy))
        self.conn.commit()
        with mock.patch.object(main, "_iso_today", return_value=hoy):
            r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-03-15')}")
        self.assertEqual(r.status_code, 200, r.text)
        marzo = {r["date"]: r["net_deposited"] for r in self.conn.execute(
            "SELECT date, net_deposited FROM snapshots WHERE user_id=? AND date BETWEEN "
            "'2026-03-01' AND '2026-03-19'", (self.uid,))}
        esperado = {d: (110000.0 if d < "2026-03-10" else 106000.0)
                    for d in _dias(2026, 3, 1, 19)}
        mal = {d: (esperado[d], marzo.get(d)) for d in esperado if marzo.get(d) != esperado[d]}
        self.assertEqual(mal, {}, "marzo (fecha: (esperado, servido))")

    # ── 6c. borrar una venta desde Operaciones, y deshacerla ─────────────────
    def test_borrar_una_operacion_y_deshacer(self):
        self._import(_csv("2026-01-12,VENTA,IBKR,MSFT,5,320,1600,,,0,USD,"))
        oid = self.conn.execute(
            "SELECT id FROM operations WHERE user_id=? AND asset='MSFT' AND op_type='Venta'",
            (self.uid,)).fetchone()["id"]
        r = self.client.delete(f"/api/operations/{oid}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("después de borrar la venta de MSFT")
        token = r.json().get("undo_token")
        self.assertTrue(token, f"el borrado no devolvió con qué deshacer: {r.json()}")
        r = self.client.post(f"/api/operations/undo/{token}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("después de deshacer el borrado de la venta")

    # ── 6d. cuenta que arranca con plata ya invertida (baseline) ─────────────
    def test_con_baseline_el_boton_despues_de_borrar_no_cambia_nada(self):
        """El fin de mes que fabrica `_backfill_snapshots_from_monthly` se estampaba
        SIN el baseline (`capital_inicio` del primer mes), mientras el cron, el
        anclado y la reconstrucción MtM lo incluyen. Dos escritores con dos cuentas:
        tras cada borrado el backfill bajaba la sintética y el botón del admin la
        volvía a subir, y nunca quedaba quieto. Es el mismo arreglo que
        `scripts/backfill_historical_mtm.py` ya tenía ("MISMA CONVENCIÓN QUE EL
        CRON"), sin propagar al persister."""
        B = 5000.0
        prim = self.conn.execute(
            "SELECT id FROM monthly_entries WHERE user_id=? AND broker='global' "
            "ORDER BY year, month LIMIT 1", (self.uid,)).fetchone()
        self.conn.execute("UPDATE monthly_entries SET capital_inicio=? WHERE id=?",
                          (B, prim["id"]))
        main._repair_monthly_chain(self.conn, self.uid, "global")
        # Lo que el cron habría estampado: la misma cuenta, con el baseline adentro.
        self.conn.execute("UPDATE snapshots SET net_deposited=net_deposited+?, "
                          "total_value=total_value+? WHERE user_id=? AND source='cron'",
                          (B, B, self.uid))
        self.conn.commit()
        r = self.client.delete(f"/api/movements/tx-{self._tx('DIVIDEND', '2025-12-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        from snapshots_job import compute_net_deposited_db
        sint = self.conn.execute(
            "SELECT net_deposited, source FROM snapshots WHERE user_id=? AND date='2025-12-31'",
            (self.uid,)).fetchone()
        self.assertIsNotNone(sint, "el backfill no recreó el fin de diciembre")
        self.assertEqual(sint["source"], "import")
        self.assertAlmostEqual(
            sint["net_deposited"],
            compute_net_deposited_db(self.conn, self.uid, as_of_date="2025-12"), places=2,
            msg="la sintética de fin de mes no usa la convención del cron (falta el baseline)")
        main.app.dependency_overrides[main.get_admin_user] = lambda: self.uid
        try:
            r = self.client.post("/api/admin/recompute-snapshots-netdep")
        finally:
            main.app.dependency_overrides.pop(main.get_admin_user, None)
        self.assertEqual(r.status_code, 200, r.text)
        cambio = [d for d in r.json()["details"] if abs(d["delta"]) > 0.01]
        self.assertEqual(cambio, [], "el botón del admin corrigió algo que el borrado "
                                     "acababa de dejar: dos escritores, dos cuentas")

    # ── 8. el recorrido entero, en el orden en que lo haría una persona ──────
    def test_recorrido_completo(self):
        """Sellar los meses → borrar un dividendo viejo → borrar el historial de un
        activo y deshacerlo → borrar una compra → la foto del cron de la noche
        siguiente → el botón del admin → volver a sellar. En cada paso el aportado
        del cron queda igual, y al final: el botón no tiene nada que corregir, la
        pantalla sigue en 0 y ningún mes cerrado cambió de revisión."""
        from unittest.mock import patch
        import snapshots_job
        sello = twr.sellar(self.conn, self.uid, "2026-03")
        self.conn.commit()
        self.assertGreater(sello["sellados"], 0, f"no selló ningún mes: {sello}")

        r = self.client.delete(f"/api/movements/tx-{self._tx('DIVIDEND', '2025-12-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("paso 1: borrar el dividendo viejo")

        r = self.client.delete("/api/assets/history", params={"asset": "AAPL"})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post(f"/api/assets/undo/{r.json()['undo_token']}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("paso 2: borrar y deshacer el historial de AAPL")

        r = self.client.delete(f"/api/movements/tx-{self._tx('BUY', '2025-12-04')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("paso 3: borrar la compra de MSFT")

        # La noche siguiente: el cron escribe SU fecha y no toca las anteriores.
        with patch.object(snapshots_job, "fetch_prices_for_symbols",
                          side_effect=lambda syms, cy: {s: 150.0 for s in syms}):
            with self.conn:
                res = snapshots_job.take_snapshot_for_user(
                    self.conn, self.uid, 1200, {}, "2026-04-01")
        self.assertTrue(res.get("ok"), f"el cron no escribió: {res}")
        self._assert_dia_conservado("paso 4: después de la foto del cron del 1-abr")
        # Su valor depende del precio simulado, no de lo que se mide acá.
        self.conn.execute("DELETE FROM snapshots WHERE user_id=? AND date='2026-04-01'",
                          (self.uid,))
        self.conn.commit()

        main.app.dependency_overrides[main.get_admin_user] = lambda: self.uid
        try:
            r = self.client.post("/api/admin/recompute-snapshots-netdep")
        finally:
            main.app.dependency_overrides.pop(main.get_admin_user, None)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([d for d in r.json()["details"] if abs(d["delta"]) > 0.01], [],
                         "paso 5: el botón del admin encontró algo que corregir")
        self._assert_dia_conservado("paso 5: después del botón del admin")
        self._assert_pantalla_en_cero("al final del recorrido")

        resello = twr.sellar(self.conn, self.uid, "2026-03")
        self.assertEqual(resello["revisados"], 0,
                         f"un borrado que no tocó lo aportado cambió meses cerrados: {resello}")

    # ── 9. aplicar SÓLO el cambio que produjo el borrado ─────────────────────
    # Re-anclar el mes usa la ÚLTIMA foto del mes como la que sabe todos sus flujos.
    # Cuando esa foto no vio algo —un depósito cargado hoy después de la foto de hoy,
    # un import a mitad de mes que reescribió la contabilidad hacia atrás— el mes
    # se reescribía mal, y eso no tiene vuelta. Estos escenarios fijan lo que tiene
    # que pasar: el borrado le saca a cada foto exactamente lo que esa foto tenía de
    # lo borrado, y nada más.
    def _subir(self, desde: str, hasta: str, monto: float) -> None:
        """Lo que el cron habría anotado desde la noche en que la plata ENTRÓ a la
        cuenta: más aportado y, con el mercado quieto, el mismo valor de más."""
        for d in APORTADO_DEL_DIA:
            if desde <= d <= hasta:
                self.conn.execute(
                    "UPDATE snapshots SET net_deposited=net_deposited+?, "
                    "total_value=total_value+? WHERE user_id=? AND date=?",
                    (monto, monto, self.uid, d))
        self.conn.commit()

    def _hasta_hoy(self, hoy: str, con_foto_de_hoy: bool) -> None:
        """El mes en curso: no hay fotos después de hoy (y quizá tampoco la de hoy)."""
        op = ">" if con_foto_de_hoy else ">="
        self.conn.execute(f"DELETE FROM snapshots WHERE user_id=? AND date {op} ?",
                          (self.uid, hoy))
        self.conn.commit()

    def _depositar_a_mano(self, fecha: str, monto: float, broker: str = None) -> None:
        r = self.client.post("/api/cash/flow", json={
            "broker_name": broker or self.BROKER, "direction": "deposit",
            "amount": monto, "date": fecha})
        self.assertEqual(r.status_code, 200, r.text)

    def _me_dep(self, mes: int) -> str:
        me = self.conn.execute(
            "SELECT id FROM monthly_entries WHERE user_id=? AND broker=? AND year=2026 "
            "AND month=? AND manual_deposits > 0", (self.uid, self.BROKER, mes)).fetchone()
        self.assertIsNotNone(me, f"no hay depósito manual en el mes {mes}")
        return f"me-{me['id']}-dep"

    def _con(self, cambios: dict, hasta: str = None) -> dict:
        """APORTADO_DEL_DIA más `cambios` = {desde: monto} acumulados por fecha."""
        out = {}
        for d, v in APORTADO_DEL_DIA.items():
            if hasta and d >= hasta:
                continue
            out[d] = v + sum(m for desde, m in cambios.items() if d >= desde)
        return out

    def test_a_deposito_de_hoy_despues_de_la_foto_y_borrar_algo_viejo(self):
        """Hoy es 20-mar. La foto de hoy ya se sacó; después se carga un depósito de
        5.000 y, en la misma sesión, se borra un dividendo de diciembre. El borrado no
        cambia ningún flujo: ninguna foto se tiene que mover. (Re-anclando, marzo
        quedaba plano: el depósito de hoy figuraba desde el día 1 y el retiro del 10
        desaparecía — 19 fotos, US$ 59.000.)"""
        hoy = "2026-03-20"
        self._hasta_hoy(hoy, con_foto_de_hoy=True)
        with mock.patch.object(main, "_iso_today", return_value=hoy):
            self._depositar_a_mano(hoy, 5000)
            r = self.client.delete(f"/api/movements/tx-{self._tx('DIVIDEND', '2025-12-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("depósito de hoy + borrar el dividendo viejo",
                                    self._con({}, hasta=hoy))

    def test_a_deposito_de_hoy_sin_foto_de_hoy_y_borrar_algo_viejo(self):
        hoy = "2026-03-20"
        self._hasta_hoy(hoy, con_foto_de_hoy=False)
        with mock.patch.object(main, "_iso_today", return_value=hoy):
            self._depositar_a_mano(hoy, 5000)
            r = self.client.delete(f"/api/movements/tx-{self._tx('DIVIDEND', '2025-12-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("depósito de hoy sin foto de hoy + borrar el dividendo",
                                    self._con({}, hasta=hoy))

    def test_a_deposito_de_hoy_y_borrar_el_deposito_de_febrero(self):
        """El borrado SÍ cambia lo aportado: el depósito de febrero sale desde el 20-feb,
        y el de hoy —que ninguna foto vio todavía— no aparece en ninguna."""
        hoy = "2026-03-20"
        self._hasta_hoy(hoy, con_foto_de_hoy=True)
        with mock.patch.object(main, "_iso_today", return_value=hoy):
            self._depositar_a_mano(hoy, 5000)
            r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-20')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("depósito de hoy + borrar el depósito del 20-feb",
                                    self._con({"2026-02-20": -10000}, hasta=hoy))

    def test_b_la_estampa_vieja_de_un_import_no_se_muda(self):
        """El 20-mar se importa un depósito de diciembre: las fotos desde el 20 lo ven
        (en el aportado y en el valor), las de antes no. Borrar el dividendo del 15-mar
        no cambia ningún flujo, así que ninguna foto se mueve. (Re-anclando desde el
        15, el escalón del import se mudaba al día 15: 5 fotos, US$ 100.000.)"""
        self._import(_csv("2025-12-15,DEPOSITO,IBKR,,,,20000,,,0,USD,"))
        self._subir("2026-03-20", "2026-03-31", 20000)
        antes = self._aportado_servido()
        r = self.client.delete(f"/api/movements/tx-{self._tx('DIVIDEND', '2026-03-15')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("estampa vieja + borrar el dividendo del 15-mar", antes)

    def test_un_deposito_importado_tarde_no_hunde_las_fotos_que_no_lo_vieron(self):
        """Un depósito del 25-feb que entró recién con el import del 5-mar (el que
        importa el resumen del mes): las fotos del 25-feb al 4-mar nunca lo tuvieron.
        Borrarlo (era un duplicado) se lo saca sólo a las que lo tenían."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,"))
        self._subir("2026-03-05", "2026-03-31", 7000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-25')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el depósito importado tarde")

    def test_borrar_el_original_de_un_deposito_duplicado(self):
        """El mismo depósito del 25-feb entró dos veces: el original con su día, y una
        copia con el import del 5-mar. Se borra el ORIGINAL. Queda uno solo, que las
        fotos tienen desde el 25-feb: sólo pierden el monto las que tenían los dos."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,original"))
        self._subir("2026-02-25", "2026-03-31", 7000)
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,copia del resumen"))
        n = self.conn.execute(
            "SELECT COUNT(*) AS n FROM import_normalized_tx n JOIN import_batches b "
            "ON b.id=n.batch_id WHERE b.user_id=? AND n.date='2026-02-25' "
            "AND n.operation_type='DEPOSIT' AND n.excluded_at IS NULL", (self.uid,)).fetchone()["n"]
        self.assertEqual(n, 2, "el import no dejó entrar la copia: el escenario no se armó")
        self._subir("2026-03-05", "2026-03-31", 7000)
        original = self.conn.execute(
            "SELECT MIN(n.id) AS id FROM import_normalized_tx n JOIN import_batches b "
            "ON b.id=n.batch_id WHERE b.user_id=? AND n.date='2026-02-25' "
            "AND n.operation_type='DEPOSIT'", (self.uid,)).fetchone()["id"]
        r = self.client.delete(f"/api/movements/tx-{original}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el original del duplicado",
                                    self._con({"2026-02-25": 7000}))

    def test_deposito_a_mano_en_un_mes_con_otro_deposito(self):
        """`me-` no guarda el día (la cascada arranca el 1 del mes). Febrero ya tiene
        el depósito importado del 20: del 20 al 24 el aportado sigue en 110.000."""
        self._depositar_a_mano("2026-02-25", 3000)
        self._subir("2026-02-25", "2026-03-31", 3000)
        r = self.client.delete(f"/api/movements/{self._me_dep(2)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el depósito a mano del 25-feb")

    def test_deposito_a_mano_en_un_mes_con_un_retiro(self):
        self._depositar_a_mano("2026-03-20", 3000)
        self._subir("2026-03-20", "2026-03-31", 3000)
        r = self.client.delete(f"/api/movements/{self._me_dep(3)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el depósito a mano del 20-mar")

    def test_varios_depositos_a_mano_del_mes_en_un_renglon(self):
        """LÍMITE CONOCIDO, fijado acá para que no empeore sin que nadie se entere.
        Dos depósitos a mano del mismo mes (1.000 el 5-feb y 2.000 el 25-feb) viven
        sumados en UN renglón de `monthly_entries`, y `me-` los borra juntos. Ninguna
        foto saltó 3.000, así que no hay un día que encontrar: del 20 al 24 —entre el
        depósito importado y el segundo a mano— no se puede saber cuánto de lo borrado
        tenía cada foto. Todo lo demás tiene que quedar exacto, y esos días dentro de
        lo que el mes permite (entre lo de antes del mes y lo de antes más los
        depósitos del mes)."""
        self._depositar_a_mano("2026-02-05", 1000)
        self._depositar_a_mano("2026-02-25", 2000)
        self._subir("2026-02-05", "2026-03-31", 1000)
        self._subir("2026-02-25", "2026-03-31", 2000)
        r = self.client.delete(f"/api/movements/{self._me_dep(2)}")
        self.assertEqual(r.status_code, 200, r.text)
        servido = self._aportado_servido()
        dudosos = set(_dias(2026, 2, 20, 24))
        mal = {d: (v, servido.get(d)) for d, v in APORTADO_DEL_DIA.items()
               if d not in dudosos and servido.get(d) != v}
        self.assertEqual(mal, {}, "fotos fuera de la zona dudosa con el aportado mal")
        fuera = {d: servido.get(d) for d in dudosos
                 if not (100000.0 <= servido.get(d, 0) <= 110000.0)}
        self.assertEqual(fuera, {}, "la zona dudosa se salió de lo que el mes permite")

    def test_posicion_a_mano_con_autodeposito_borrar_y_deshacer(self):
        """Una posición cargada a mano en un broker sin saldo dispara un AUTODEPÓSITO:
        cuenta como plata aportada. Se cargó el 15-feb con fecha de compra 10-feb, así
        que las fotos la ven desde el 15. Esta puerta (y su deshacer) tocan la
        contabilidad ANTES de la cascada: el "antes" se tiene que tomar al entrar."""
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "MANUAL", "USDT"))
        self.conn.commit()
        r = self.client.post("/api/positions", json={
            "broker": "MANUAL", "asset": "KO", "buy_price": 50, "quantity": 40,
            "invested": 2000, "entry_date": "2026-02-10"})
        self.assertEqual(r.status_code, 200, r.text)
        self._subir("2026-02-15", "2026-03-31", 2000)
        pid = self.conn.execute(
            "SELECT id FROM positions WHERE user_id=? AND broker='MANUAL' AND asset='KO'",
            (self.uid,)).fetchone()["id"]
        r = self.client.delete(f"/api/positions/{pid}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar la posición a mano con autodepósito")
        token = r.json().get("undo_token")
        self.assertTrue(token, f"el borrado no devolvió con qué deshacer: {r.json()}")
        r = self.client.post(f"/api/operations/undo/{token}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("deshacer el borrado de la posición a mano",
                                    self._con({"2026-02-15": 2000}))

    def test_operacion_a_mano_borrar_y_deshacer(self):
        """La puerta de las operaciones cargadas a mano: no cambia lo aportado."""
        r = self.client.post("/api/operations", json={
            "date": "2026-01-20", "broker": self.BROKER, "asset": "TSLA",
            "op_type": "Venta", "pnl_usd": 120})
        self.assertEqual(r.status_code, 200, r.text)
        oid = self.conn.execute(
            "SELECT id FROM operations WHERE user_id=? AND asset='TSLA'",
            (self.uid,)).fetchone()["id"]
        r = self.client.delete(f"/api/operations/{oid}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar la operación a mano")
        token = r.json().get("undo_token")
        self.assertTrue(token, f"el borrado no devolvió con qué deshacer: {r.json()}")
        r = self.client.post(f"/api/operations/undo/{token}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("deshacer el borrado de la operación a mano")

    # ── 7. sin fecha de arranque no se re-estampa nada ───────────────────────
    def test_sin_fecha_de_arranque_no_reescribe_nada(self):
        """Cuatro cascadas pasan `since_date=None` cuando la fila no tiene fecha. Hoy
        eso saltea el re-estampado; el arreglo no puede leerlo como "todas las
        fotos", porque reescribiría meses cerrados (incluso las estampas viejas)."""
        self.conn.execute("UPDATE snapshots SET net_deposited=55555 "
                          "WHERE user_id=? AND date LIKE '2026-01-%'", (self.uid,))
        self.conn.commit()
        antes = {r["date"]: r["net_deposited"] for r in self.conn.execute(
            "SELECT date, net_deposited FROM snapshots WHERE user_id=?", (self.uid,))}
        antes = main._foto_contable(self.conn, self.uid)
        with self.conn:
            main._cascade_after_movement_delete(self.conn, self.uid, None, {self.BROKER},
                                                antes=antes)
        despues = {r["date"]: r["net_deposited"] for r in self.conn.execute(
            "SELECT date, net_deposited FROM snapshots WHERE user_id=?", (self.uid,))}
        cambiadas = {d: (antes[d], despues.get(d)) for d in antes
                     if d in APORTADO_DEL_DIA and despues.get(d) != antes[d]}
        self.assertEqual(cambiadas, {})


if __name__ == "__main__":
    unittest.main()
