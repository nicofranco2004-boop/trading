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

⚠️ El test que decía vigilar esto (`test_audit_ronda5.ReEstampadoPorMesEsInocuoTest`)
llama a `_recompute_snapshots_netdep_for_user` DIRECTO: nunca pasa por la cascada,
así que certificaba en verde lo contrario de lo que corría en producción. Estos
entran por las MISMAS puertas HTTP que usa la app; lo único que se reemplaza es el
login (`dependency_overrides`), que no toca nada de lo que se mide.

La cuenta de laboratorio tiene el mercado QUIETO: cada foto vale exactamente lo
aportado ese día. Cualquier ganancia o pérdida que aparezca es inventada.
"""
import json
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
    for n in ("_adjust_broker_cash", "_update_monthly_pnl_realized",
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
        # El import, confirmado ANTES de las fotos (así existen en la vida real: una
        # foto no ve un import confirmado después de su fecha).
        self.conn.execute("UPDATE import_batches SET confirmed_at='2025-01-01 00:00:00' "
                          "WHERE user_id=?", (self.uid,))
        # Las fotos del cron, con el mismo UPSERT que `snapshots_job` (pisa la
        # sintética de fin de mes que el import dejó en esa fecha). La composición
        # con el formato del cron (valor por activo): el mercado está quieto, así que
        # AAPL vale lo que costó y MSFT también. Borrar una compra corrige la foto con
        # esa composición (`_corregir_mediciones`): sale el activo, vuelve la plata,
        # y a precio quieto el total queda igual.
        _comp = json.dumps([{"asset": "AAPL", "value_usd": 1500.0},
                            {"asset": "MSFT", "value_usd": 1500.0}])
        for d, nd in APORTADO_DEL_DIA.items():
            self.conn.execute(
                f"""INSERT INTO snapshots (user_id, date, total_value, total_invested,
                       net_deposited, fx_to_usd_blue, holdings_json, source, base, apto)
                   VALUES (?,?,?,?,?,1200,'{_comp}','cron','mercado',1)
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

    # ── 5. si el cálculo anclado falla, no se cae a la fórmula mensual ───────
    def test_si_el_calculo_anclado_falla_no_se_aplana(self):
        """`_recompute_snapshots_netdep_for_user` caía —sin avisar— a
        `compute_net_deposited_db(as_of_date=<fecha>)`, que trunca la fecha a MES:
        el mismo aplanado, escondido en el camino de error. Dejar la estampa como
        estaba es inofensivo para los lectores que anclan; aplanarla no tiene vuelta."""
        def _falla(*a, **k):
            raise RuntimeError("simulado: el aportado anclado no se pudo calcular")
        with mock.patch.object(twr, "_aportado_por_punto", side_effect=_falla) as m:
            r = self.client.delete(
                f"/api/movements/tx-{self._tx('DIVIDEND', '2025-12-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("con el cálculo anclado fallando")
        # Sin esto el verde no dice nada: si el arreglo llegara al cálculo por otro
        # nombre, la falla simulada no lo alcanzaría y el test pasaría sin probarla.
        self.assertTrue(m.called, "la cascada no pasó por el cálculo anclado")

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
        with self.conn:
            main._cascade_after_movement_delete(self.conn, self.uid, None, {self.BROKER})
        despues = {r["date"]: r["net_deposited"] for r in self.conn.execute(
            "SELECT date, net_deposited FROM snapshots WHERE user_id=?", (self.uid,))}
        cambiadas = {d: (antes[d], despues.get(d)) for d in antes
                     if d in APORTADO_DEL_DIA and despues.get(d) != antes[d]}
        self.assertEqual(cambiadas, {})


class LaSemanaDespuesDeBorrar(unittest.TestCase):
    """La tarjeta de la SEMANA y la curva, antes y después de borrar una compra.

    La semana resta las estampas de sus dos fotos tal cual (sin anclar), así que es
    la pantalla que primero muestra un aportado mal re-estampado. Hallazgo del
    2026-10-02 sobre una copia anterior al arreglo de la cascada: cuenta nueva con
    10.000 el 1/9, aporte de 3.000 el 15/9, borra una compra del 2/9 → la foto del
    6/9 pasaba a "aportado 13.000" y la semana 31/8–6/9 publicaba "perdiste US$
    2.750 · Aportaste US$ 13.000" (real: +250). Con el arreglo de la cascada ese
    caso ya daba bien — pero con un RETIRO en vez del aporte seguía publicando
    "ganaste US$ 4.250 · Aportaste US$ 6.000", porque el anclado no veía como
    movimiento la plata que entró antes de la primera foto del mes. Ese mismo
    anclado lo usa la curva al LEER: sin borrar nada, la cuenta nueva con retiro
    mostraba −37,5 % y −39 % de peor caída, y la vieja que deposita el 1 y retira el
    15, −26,5 % de peor caída.

    Mercado quieto salvo una ganancia chica desde el 2/9 (+250 la cuenta nueva,
    +70 la vieja). Entra por las mismas puertas HTTP que la app; el benchmark se
    apaga porque baja de internet y no es lo que se mide."""
    BROKER = "IBKR"
    SEMANA = "2026-W36"          # lunes 31/8 a domingo 6/9
    _import = BorrarConservaElDia._import
    _tx = BorrarConservaElDia._tx

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
            ("semana_borrar@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, self.BROKER, "USDT"))
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.client = TestClient(main.app)
        self._sin_benchmark = [mock.patch.object(main, "_bench_para_reportes",
                                                 return_value={}),
                               mock.patch.object(main, "_benchmarks_fetch_and_cache",
                                                 return_value={})]
        for p in self._sin_benchmark:
            p.start()

    def tearDown(self):
        for p in self._sin_benchmark:
            p.stop()
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        self.conn.close()

    def _cuenta(self, filas_csv, aportado_del_dia, ganancia_desde_el_2):
        """Importa el historial y escribe las fotos del cron: cada noche anota lo
        aportado de ese día y la cartera vale eso más la ganancia desde el 2/9."""
        self._import(_csv(*filas_csv))
        self.conn.execute("UPDATE import_batches SET confirmed_at='2025-01-01 00:00:00' "
                          "WHERE user_id=?", (self.uid,))
        for d, nd in aportado_del_dia.items():
            v = nd + (ganancia_desde_el_2 if d >= "2026-09-02" else 0.0)
            # Composición con el formato del cron: desde el 2/9, las 10 AAPL valen lo
            # que costaron (1.500) más la ganancia; antes, todo efectivo.
            comp = (json.dumps([{"asset": "AAPL", "value_usd": 1500.0 + ganancia_desde_el_2}])
                    if d >= "2026-09-02" else "[]")
            self.conn.execute(
                """INSERT INTO snapshots (user_id, date, total_value, total_invested,
                       net_deposited, fx_to_usd_blue, holdings_json, source, base, apto)
                   VALUES (?,?,?,?,?,1200,?,'cron','mercado',1)
                   ON CONFLICT(user_id, date) DO UPDATE SET
                       total_value=excluded.total_value,
                       total_invested=excluded.total_invested,
                       net_deposited=excluded.net_deposited,
                       fx_to_usd_blue=excluded.fx_to_usd_blue,
                       holdings_json=excluded.holdings_json,
                       source='cron', base='mercado', apto=1""",
                (self.uid, d, v, nd, nd, comp))
        self.conn.commit()

    def _lo_que_publica(self) -> dict:
        r = self.client.get(f"/api/reports/period/week/{self.SEMANA}")
        self.assertEqual(r.status_code, 200, r.text)
        m = r.json()["metrics"]
        p = self.client.get("/api/insights/performance")
        self.assertEqual(p.status_code, 200, p.text)
        p = p.json()
        # Con ventana, como el chip de 30 días: la ganancia fue el 2/9, así que
        # desde el 10/9 no hay nada que publicar. La ventana arranca después del
        # aporte del 1/9 y antes del retiro del 15/9: el movimiento de antes de la
        # ventana tiene que seguir contando.
        v = self.client.get("/api/insights/performance", params={"desde": "2026-09-10"})
        self.assertEqual(v.status_code, 200, v.text)
        v = v.json()
        return {"semana": (round(m["delta_usd"] or 0, 2), round(m["deposits"] or 0, 2),
                           round(m["withdrawals"] or 0, 2), bool(m["basis_incomparable"])),
                "acumulado": round(p["twr"] or 0, 6),
                "peor_caida": round(p["drawdown_maximo"] or 0, 6),
                "desde_el_10": (round(v["twr"] or 0, 6), round(v["drawdown_maximo"] or 0, 6))}

    def _assert_publica(self, esperado: dict, cuando: str):
        self.assertEqual(self._lo_que_publica(), esperado,
                         f"{cuando} — semana = (resultado, aportes, retiros, sin base)")

    def _borrar_la_compra_del_2(self):
        r = self.client.delete(
            f"/api/movements/tx-{self._tx('BUY', '2026-09-02')}")
        self.assertEqual(r.status_code, 200, r.text)

    def _caso(self, filas_csv, aportado_del_dia, ganancia, esperado):
        self._cuenta(filas_csv, aportado_del_dia, ganancia)
        antes = {r["date"]: r["net_deposited"] for r in self.conn.execute(
            "SELECT date, net_deposited FROM snapshots WHERE user_id=?", (self.uid,))}
        self._assert_publica(esperado, "antes de borrar")
        self._borrar_la_compra_del_2()
        # ⚠️ ESTO CAMBIÓ EL 2026-10-07, A PROPÓSITO. Antes este test pedía que después
        # de borrar la compra del 2/9 se siguiera publicando la ganancia de esa compra
        # (+250 / +70): era la regla "las fotos del cron no se tocan". Nico decidió
        # que una compra o venta borrada SÍ sale de las fotos medidas (opción A de
        # `main._corregir_mediciones`): con la composición de cada foto se saca AAPL
        # y vuelve la plata de la compra, así que la ganancia que sólo existía por
        # esa compra desaparece. Lo que sigue valiendo, y se verifica abajo: una
        # compra no es un aporte, así que lo aportado de cada día no se mueve.
        sin_la_compra = {"semana": (0.0,) + tuple(esperado["semana"][1:]),
                         "acumulado": 0.0, "peor_caida": 0.0, "desde_el_10": (0.0, 0.0)}
        self._assert_publica(sin_la_compra, "después de borrar la compra del 2/9")
        despues = {r["date"]: r["net_deposited"] for r in self.conn.execute(
            "SELECT date, net_deposited FROM snapshots WHERE user_id=?", (self.uid,))}
        movidas = {d: (antes[d], despues.get(d)) for d in aportado_del_dia
                   if despues.get(d) != antes[d]}
        self.assertEqual(movidas, {}, "fotos del cron con el aportado cambiado "
                                      "(fecha: (antes, después))")

    @staticmethod
    def _septiembre(antes_del_15, desde_el_15):
        return {d: (antes_del_15 if d < "2026-09-15" else desde_el_15)
                for d in _dias(2026, 9, 1, 30)}

    # ── cuenta NUEVA: no hay foto antes de la semana ─────────────────────────
    def test_cuenta_nueva_con_aporte_el_15(self):
        self._caso(["2026-09-01,DEPOSITO,IBKR,,,,10000,,,0,USD,",
                    "2026-09-02,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,",
                    "2026-09-15,DEPOSITO,IBKR,,,,3000,,,0,USD,"],
                   self._septiembre(10000.0, 13000.0), 250.0,
                   {"semana": (250.0, 10000.0, 0.0, False),
                    "acumulado": 0.025, "peor_caida": 0.0,
                    "desde_el_10": (0.0, 0.0)})

    def test_cuenta_nueva_con_retiro_el_15(self):
        self._caso(["2026-09-01,DEPOSITO,IBKR,,,,10000,,,0,USD,",
                    "2026-09-02,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,",
                    "2026-09-15,RETIRO,IBKR,,,,4000,,,0,USD,"],
                   self._septiembre(10000.0, 6000.0), 250.0,
                   {"semana": (250.0, 10000.0, 0.0, False),
                    "acumulado": 0.025, "peor_caida": 0.0,
                    "desde_el_10": (0.0, 0.0)})

    # ── cuenta VIEJA: la semana arranca en una foto del cron (rama normal) ───
    def _vieja(self, flujos_de_septiembre, antes_del_15, desde_el_15, esperado):
        aportado = {d: 10000.0 for d in _dias(2026, 7, 1, 31) + _dias(2026, 8, 1, 31)}
        aportado.update(self._septiembre(antes_del_15, desde_el_15))
        self._caso(["2026-07-01,DEPOSITO,IBKR,,,,10000,,,0,USD,",
                    "2026-09-02,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,"]
                   + flujos_de_septiembre, aportado, 70.0, esperado)

    def test_cuenta_vieja_con_aporte_el_15(self):
        self._vieja(["2026-09-15,DEPOSITO,IBKR,,,,3000,,,0,USD,"], 10000.0, 13000.0,
                    {"semana": (70.0, 0.0, 0.0, False),
                     "acumulado": 0.007, "peor_caida": 0.0,
                     "desde_el_10": (0.0, 0.0)})

    def test_cuenta_vieja_con_retiro_el_15(self):
        self._vieja(["2026-09-15,RETIRO,IBKR,,,,4000,,,0,USD,"], 10000.0, 6000.0,
                    {"semana": (70.0, 0.0, 0.0, False),
                     "acumulado": 0.007, "peor_caida": 0.0,
                     "desde_el_10": (0.0, 0.0)})

    def test_cuenta_vieja_que_aporta_el_1_y_retira_el_15(self):
        """La plata del 1/9 ya está en la PRIMERA foto de septiembre: entre fotos del
        mismo mes la estampa no se mueve. El anclado tiene que verla igual."""
        self._vieja(["2026-09-01,DEPOSITO,IBKR,,,,5000,,,0,USD,",
                     "2026-09-15,RETIRO,IBKR,,,,4000,,,0,USD,"], 15000.0, 11000.0,
                    {"semana": (70.0, 5000.0, 0.0, False),
                     "acumulado": round(70.0 / 15000.0, 6), "peor_caida": 0.0,
                     "desde_el_10": (0.0, 0.0)})


if __name__ == "__main__":
    unittest.main()
