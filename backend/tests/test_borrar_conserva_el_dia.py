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
llamaba a `_recompute_snapshots_netdep_for_user` DIRECTO: nunca pasaba por la
cascada, así que certificaba en verde lo contrario de lo que corría en producción
(hoy entra por HTTP). Estos entran por las MISMAS puertas HTTP que usa la app; lo único que se reemplaza es el
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
        # Cada movimiento se importa EL DÍA QUE PASÓ (un import por fila, confirmado
        # ese día): es lo que hace que la foto de esa noche sea la primera que lo
        # tiene. Un solo import confirmado en diciembre sería un mundo imposible: el
        # cron anota lo aportado del MES, así que un depósito de febrero ya cargado
        # figuraría desde el 1-feb.
        for fila in (
            "2025-12-02,DEPOSITO,IBKR,,,,100000,,,0,USD,",
            "2025-12-03,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,",
            # MSFT sin dividendos: la app no deja borrar de a una compra un activo
            # con dividendos enlazados (400), y eso no es lo que se mide acá.
            "2025-12-04,COMPRA,IBKR,MSFT,5,300,1500,,,0,USD,",
            "2025-12-10,DIVIDENDO,IBKR,AAPL,,,50,,,0,USD,",
            "2026-02-20,DEPOSITO,IBKR,,,,10000,,,0,USD,",
            "2026-03-10,RETIRO,IBKR,,,,4000,,,0,USD,",
            "2026-03-15,DIVIDENDO,IBKR,AAPL,,,30,,,0,USD,",
        ):
            self._import(_csv(fila))
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
    def _import(self, csv_bytes: bytes, confirmado: str = None,
                confirmado_utc: str = None) -> None:
        """Importa por el mismo camino que la app y fecha la CONFIRMACIÓN del import:
        `confirmado` (día argentino), o el día del movimiento más viejo del archivo —
        "lo cargó el mismo día que pasó". En producción la escribe `persist_batch`
        con la hora real; acá quedaría "hoy" (octubre de 2026), o sea fotos de marzo
        que tienen movimientos importados meses después: un mundo imposible, y el
        borrado usa ese día para saber desde qué foto estaba lo borrado."""
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
        if confirmado is None:
            confirmado = min(l.split(",")[0] for l in csv_bytes.decode().splitlines()[1:] if l)
        with self.conn:
            # 12:00 en Argentina = 15:00 UTC, que es como lo guarda `datetime('now')`.
            self.conn.execute("UPDATE import_batches SET confirmed_at=? WHERE id=?",
                              (confirmado_utc or f"{confirmado} 15:00:00", sid))

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
        """El borrado no toca fotos anteriores a lo borrado (salvo uno importado antes
        de su fecha: las fotos lo tienen desde que se confirmó el import). Las de
        antes —incluso si tuvieran una estampa vieja— no son asunto de este borrado:
        tocarlas cambiaría meses ya cerrados que el usuario no tocó."""
        self.conn.execute("UPDATE snapshots SET net_deposited=55555 "
                          "WHERE user_id=? AND date LIKE '2026-01-%'", (self.uid,))
        self.conn.commit()
        # Un depósito: borrar un dividendo ya no cambia ninguna foto, y el test no
        # mediría el alcance.
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-20')}")
        self.assertEqual(r.status_code, 200, r.text)
        enero = {row["net_deposited"] for row in self.conn.execute(
            "SELECT net_deposited FROM snapshots WHERE user_id=? AND date LIKE '2026-01-%'",
            (self.uid,))}
        self.assertEqual(enero, {55555.0}, "el borrado de febrero reescribió enero")

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
        """El anclado (y su atajo de error) corre en el botón de reparación del admin,
        la reparación de historial y la migración del arranque. El borrado ya no
        pasa por él (`test_si_el_calculo_falla_no_se_toca_ninguna_foto`)."""
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
        self._import(_csv("2026-03-15,DEPOSITO,IBKR,,,,10000,,,0,USD,"))
        self._import(_csv("2026-03-20,DEPOSITO,IBKR,,,,5000,,,0,USD,"))
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
        self._import(_csv("2025-12-15,DEPOSITO,IBKR,,,,20000,,,0,USD,"), confirmado="2026-03-20")
        self._subir("2026-03-20", "2026-03-31", 20000)
        antes = self._aportado_servido()
        r = self.client.delete(f"/api/movements/tx-{self._tx('DIVIDEND', '2026-03-15')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("estampa vieja + borrar el dividendo del 15-mar", antes)

    def test_un_deposito_importado_tarde_no_hunde_las_fotos_que_no_lo_vieron(self):
        """Un depósito del 25-feb que entró recién con el import del 5-mar (el que
        importa el resumen del mes): las fotos del 25-feb al 4-mar nunca lo tuvieron.
        Borrarlo (era un duplicado) se lo saca sólo a las que lo tenían."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,"), confirmado="2026-03-05")
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
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,copia del resumen"),
                     confirmado="2026-03-05")
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
        contabilidad ANTES de la cascada: el "antes" se tiene que tomar antes de esa
        primera escritura."""
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

    # ── 10. lo que encontraron las auditorías del cambio ─────────────────────
    def test_borrar_el_duplicado_recien_importado_que_ninguna_foto_vio(self):
        """El borrado más común de un depósito: el import trajo uno repetido, el
        usuario lo ve y lo borra enseguida. Ninguna foto lo tuvo —se confirmó
        después de la última—, así que ninguna se mueve. (Buscando "el salto del
        monto", se enganchaba el salto del ORIGINAL y le restaba 7.000 a las fotos
        del 12 en adelante.)"""
        self._import(_csv("2026-03-12,DEPOSITO,IBKR,,,,7000,,,0,USD,original"))
        self._subir("2026-03-12", "2026-03-31", 7000)
        self._import(_csv("2026-03-12,DEPOSITO,IBKR,,,,7000,,,0,USD,repetido"),
                     confirmado="2026-04-02")
        copia = self.conn.execute(
            "SELECT MAX(n.id) AS id FROM import_normalized_tx n JOIN import_batches b "
            "ON b.id=n.batch_id WHERE b.user_id=? AND n.date='2026-03-12' "
            "AND n.operation_type='DEPOSIT'", (self.uid,)).fetchone()["id"]
        r = self.client.delete(f"/api/movements/tx-{copia}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar la copia que ninguna foto vio",
                                    self._con({"2026-03-12": 7000}))

    def test_borrar_un_deposito_que_vino_con_un_retiro_en_el_mismo_import(self):
        """El resumen de febrero se importa el 5-mar con un depósito de 7.000 y un
        retiro de 2.000: las fotos hasta el 4-mar no vieron ninguno de los dos, y
        desde el 5 los ven juntos (+5.000). Borrado el depósito, sólo pierden 7.000
        las que lo tenían. (Comparando la foto de cierre de febrero —le faltaban
        5.000, menos que 7.000— se concluía que "lo tenía" y se restaba desde el 10.)"""
        self._import(_csv("2026-02-10,DEPOSITO,IBKR,,,,7000,,,0,USD,",
                          "2026-02-15,RETIRO,IBKR,,,,2000,,,0,USD,"), confirmado="2026-03-05")
        self._subir("2026-03-05", "2026-03-31", 5000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el depósito del import con un retiro",
                                    self._con({"2026-03-05": -2000}))

    def test_deposito_a_mano_con_un_importado_del_mismo_monto(self):
        """Un depósito importado de 3.000 el 5-feb y uno a mano de 3.000 el 25-feb:
        el salto del 5 lo explica el importado, así que el a mano entró el 25."""
        self._import(_csv("2026-02-05,DEPOSITO,IBKR,,,,3000,,,0,USD,"))
        self._subir("2026-02-05", "2026-03-31", 3000)
        self._depositar_a_mano("2026-02-25", 3000)
        self._subir("2026-02-25", "2026-03-31", 3000)
        r = self.client.delete(f"/api/movements/{self._me_dep(2)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el a mano con un importado del mismo monto",
                                    self._con({"2026-02-05": 3000}))

    def test_una_foto_de_cierre_con_aportado_en_cero_no_cuenta(self):
        """Una foto vieja con aportado 0 (la columna nace en 0) no midió el aportado:
        no se toma como prueba de que al mes "le faltaba" el depósito, y no se corrige.
        Vieja de verdad = sin firma (`source` NULL): la columna `source` llegó en
        agosto de 2026, cuando el aportado ya se medía, así que un 0 con firma es una
        medición (ver `test_un_aportado_en_cero_legitimo_tambien_se_corrige`)."""
        self.conn.execute("UPDATE snapshots SET net_deposited=0, source=NULL "
                          "WHERE user_id=? AND date=?", (self.uid, "2026-02-28"))
        self.conn.commit()
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-20')}")
        self.assertEqual(r.status_code, 200, r.text)
        esperado = self._con({"2026-02-20": -10000})
        esperado["2026-02-28"] = 0.0
        self._assert_dia_conservado("borrar el depósito con un cierre en 0", esperado)

    def test_deshacer_un_borrado_que_no_pudo_corregir_las_fotos(self):
        """Si el borrado no pudo calcular el cambio, las fotos se quedaron con lo
        borrado adentro. El deshacer lo vuelve a sumar a las cuentas, y a las fotos
        NO: nunca lo perdieron."""
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
        con_la_posicion = self._con({"2026-02-15": 2000})

        def _falla(*a, **k):
            raise RuntimeError("simulado: el cambio de aportado no se pudo calcular")
        with mock.patch.object(main, "_cambio_de_aportado", side_effect=_falla):
            r = self.client.delete(f"/api/positions/{pid}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrado sin poder calcular", con_la_posicion)
        r = self.client.post(f"/api/operations/undo/{r.json()['undo_token']}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("deshacer ese borrado", con_la_posicion)

    def test_la_foto_de_antes_espera_su_turno_de_escritura(self):
        """Dos borrados del mismo usuario a la vez: si el segundo leyera las cuentas
        mientras el primero está a mitad de su cascada, se adjudicaría el cambio
        ajeno (medido: 22 fotos sin el retiro descontado). `_foto_contable` toma el
        turno de escritura ANTES de leer: con otra escritura en curso, espera."""
        if getattr(main, "USANDO_PG", False):
            self.skipTest("el turno de SQLite; en Postgres es la fila del usuario")
        import sqlite3
        otro = main.get_db()
        espera = main.get_db()
        try:
            otro.execute("UPDATE users SET id=id WHERE id=?", (self.uid,))  # escribiendo
            espera.execute("PRAGMA busy_timeout=200")
            with self.assertRaises(sqlite3.OperationalError) as cm:
                main._foto_contable(espera, self.uid)
            self.assertIn("locked", str(cm.exception))
        finally:
            otro.rollback()
            espera.rollback()
            otro.close()
            espera.close()
        # Terminada la otra escritura, la lectura pasa.
        self.assertIsNotNone(main._foto_contable(self.conn, self.uid)["canon"])
        self.conn.rollback()

    # ── 11. segunda auditoría ────────────────────────────────────────────────
    def _gemelo(self, cual: str) -> int:
        """El id del depósito de 7.000 del 12-mar importado con la nota `cual`."""
        return self.conn.execute(
            "SELECT n.id FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id "
            "JOIN import_raw_rows r ON r.id=n.raw_row_id WHERE b.user_id=? AND "
            "n.date='2026-03-12' AND r.raw_json LIKE ?", (self.uid, f"%{cual}%")).fetchone()["id"]

    def _triplicar(self, n: int) -> None:
        """El depósito de 7.000 del 12-mar importado `n` veces: el 12, el 18 y el 25."""
        for nota, dia in (("original", "2026-03-12"), ("copia-a", "2026-03-18"),
                          ("copia-b", "2026-03-25"))[:n]:
            self._import(_csv(f"2026-03-12,DEPOSITO,IBKR,,,,7000,,,0,USD,{nota}"), confirmado=dia)
            self._subir(dia, "2026-03-31", 7000)

    def test_duplicado_borrar_el_original_y_despues_la_copia(self):
        """El depósito no existió: se borran las dos filas, primero el original. Cada
        borrado se lleva una capa; no puede llevarse dos veces la misma."""
        self._triplicar(2)
        for cual in ("original", "copia-a"):
            r = self.client.delete(f"/api/movements/tx-{self._gemelo(cual)}")
            self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el original y después la copia")

    def test_triplicado_borrar_dos_en_cualquier_orden(self):
        """Tres filas iguales; se borran la del medio y la primera. Queda una, que las
        fotos tienen desde el 12."""
        self._triplicar(3)
        for cual in ("copia-a", "original"):
            r = self.client.delete(f"/api/movements/tx-{self._gemelo(cual)}")
            self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("triplicado, borrar dos", self._con({"2026-03-12": 7000}))

    def test_deposito_a_mano_con_un_resumen_importado_tarde_en_el_mismo_mes(self):
        """Un depósito a mano del 25-feb y un depósito del 10-feb que entró con el
        resumen importado el 5-mar. A la foto de cierre de febrero le "falta" el
        importado, que no es lo borrado: no puede hacer creer que el a mano no estaba."""
        self._depositar_a_mano("2026-02-25", 3000)
        self._subir("2026-02-25", "2026-03-31", 3000)
        self._import(_csv("2026-02-10,DEPOSITO,IBKR,,,,7000,,,0,USD,"), confirmado="2026-03-05")
        self._subir("2026-03-05", "2026-03-31", 7000)
        r = self.client.delete(f"/api/movements/{self._me_dep(2)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el a mano con un resumen tardío",
                                    self._con({"2026-03-05": 7000}))

    def test_deshacer_devuelve_exactamente_lo_que_saco_el_borrado(self):
        """Dos posiciones a mano cargadas el mismo día: las fotos saltaron 4.000 juntas,
        así que borrar una no encuentra un salto de 2.000 y recorta el mes. El
        deshacer tiene que devolver, foto por foto, lo que el borrado sacó (antes
        recortaba de nuevo con las cuentas de después y le sumaba 2.000 a fotos del
        10 al 14 que nunca lo tuvieron)."""
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "MANUAL", "USDT"))
        self.conn.commit()
        for activo in ("KO", "PEP"):
            r = self.client.post("/api/positions", json={
                "broker": "MANUAL", "asset": activo, "buy_price": 50, "quantity": 40,
                "invested": 2000, "entry_date": "2026-02-10"})
            self.assertEqual(r.status_code, 200, r.text)
        self._subir("2026-02-15", "2026-03-31", 4000)
        pid = self.conn.execute(
            "SELECT id FROM positions WHERE user_id=? AND broker='MANUAL' AND asset='KO'",
            (self.uid,)).fetchone()["id"]
        r = self.client.delete(f"/api/positions/{pid}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar una de las dos", self._con({"2026-02-15": 2000}))
        r = self.client.post(f"/api/operations/undo/{r.json()['undo_token']}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("deshacerlo", self._con({"2026-02-15": 4000}))

    def test_un_movimiento_fechado_despues_de_su_import(self):
        """Un retiro del 21-mar que se importó el 20 (una liquidación a 24 hs): el cron
        anota lo aportado del MES, así que la foto del 20 ya lo tiene."""
        self._import(_csv("2026-03-21,RETIRO,IBKR,,,,1000,,,0,USD,"), confirmado="2026-03-20")
        self._subir("2026-03-20", "2026-03-31", -1000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('WITHDRAW', '2026-03-21')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el retiro fechado después de su import")

    def test_un_movimiento_fechado_el_mes_siguiente_a_su_import(self):
        """Un retiro del 2-abr importado el 27-mar: el cron anota la suma de TODO lo
        cargado, sin mirar fechas, así que las fotos del 27 al 31 de marzo ya lo
        tienen aunque las cuentas de marzo no lo incluyan. Borrado, lo pierden ésas."""
        self._import(_csv("2026-04-02,RETIRO,IBKR,,,,6000,,,0,USD,"), confirmado="2026-03-27")
        self._subir("2026-03-27", "2026-03-31", -6000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('WITHDRAW', '2026-04-02')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el retiro de abril importado en marzo")

    def test_la_foto_de_hoy_no_cuenta_como_cierre_del_mes(self):
        """Hoy es 20-mar. Un depósito a mano del 15 (las fotos lo tienen) y, hoy,
        DESPUÉS de la foto de hoy, se importa un depósito de 7.000 del 2-mar. A la
        foto de hoy le "falta" el importado; tomada como cierre de marzo, hacía
        creer que el a mano tampoco estaba y no se tocaba ninguna foto."""
        hoy = "2026-03-20"
        self._hasta_hoy(hoy, con_foto_de_hoy=True)
        self._depositar_a_mano("2026-03-15", 3000)
        self._subir("2026-03-15", hoy, 3000)
        self._import(_csv("2026-03-02,DEPOSITO,IBKR,,,,7000,,,0,USD,"), confirmado=hoy)
        with mock.patch.object(main, "_iso_today", return_value=hoy):
            r = self.client.delete(f"/api/movements/{self._me_dep(3)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el a mano con un import después de la foto de hoy",
                                    self._con({}, hasta=hoy))

    def test_un_import_con_un_deposito_y_un_retiro_que_se_compensan(self):
        """El resumen de febrero, importado el 5-mar, trae un depósito y un retiro de
        7.000: las fotos no se movieron nunca. Borrado el depósito, sólo las que
        tenían el par (desde el 5-mar) quedan con el retiro solo. La foto de cierre
        de febrero coincide con las cuentas de antes pero NO porque la hayan
        re-estampado: lo que le faltaba suma cero."""
        self._import(_csv("2026-02-10,DEPOSITO,IBKR,,,,7000,,,0,USD,",
                          "2026-02-15,RETIRO,IBKR,,,,7000,,,0,USD,"), confirmado="2026-03-05")
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el depósito del par que se compensa",
                                    self._con({"2026-03-05": -7000}))

    def test_un_mes_re_estampado_despues_del_import_si_lo_tenia(self):
        """Un depósito del 25-feb importado el 5-mar; después algo re-estampó febrero
        (el botón del admin, una versión vieja de la app) y las fotos del 25 al 28
        ya lo tienen en el aportado. Borrado, lo pierden también ésas."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,"), confirmado="2026-03-05")
        self._subir("2026-03-05", "2026-03-31", 7000)
        self.conn.execute("UPDATE snapshots SET net_deposited=net_deposited+7000 WHERE "
                          "user_id=? AND date BETWEEN '2026-02-25' AND '2026-02-28'", (self.uid,))
        self.conn.commit()
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-25')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el depósito re-estampado en febrero")

    def test_deposito_a_mano_con_fecha_vieja_cargado_meses_despues(self):
        """Un depósito a mano con fecha 10-ene, cargado el 5-mar: las fotos de enero y
        febrero nunca lo tuvieron. Borrarlo no las puede hundir."""
        self._depositar_a_mano("2026-01-10", 3000)
        self._subir("2026-03-05", "2026-03-31", 3000)
        r = self.client.delete(f"/api/movements/{self._me_dep(1)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el a mano de enero cargado en marzo")

    def test_un_import_confirmado_de_noche_cuenta_en_la_foto_de_ese_dia(self):
        """Confirmado a las 22:30 del 4-mar en Argentina, que en la base queda
        guardado como 01:30 del 5 (UTC). El cron saca la foto del 4 a las 23:59: ya
        lo tiene."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,"),
                     confirmado_utc="2026-03-05 01:30:00")
        self._subir("2026-03-04", "2026-03-31", 7000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-25')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el import confirmado de noche")

    def test_la_foto_de_antes_ve_lo_que_otro_estaba_escribiendo(self):
        """El ORDEN del turno: primero esperar, después leer. Otra conexión está
        cambiando las cuentas sin confirmar; `_foto_contable` tiene que esperar a que
        confirme y devolver las cuentas NUEVAS. Leyendo antes de tomar el turno
        devolvía las viejas (la carrera de dos borrados)."""
        if getattr(main, "USANDO_PG", False):
            self.skipTest("el turno de SQLite; en Postgres es la fila del usuario")
        import threading
        import time
        otro = main.get_db()
        visto = {}

        def _segunda_puerta():
            # Su propia conexión: sqlite3 no deja usar una conexión de otro hilo.
            espera = main.get_db()
            try:
                espera.execute("PRAGMA busy_timeout=10000")
                visto["v"] = main._foto_contable(espera, self.uid)["canon"]("2026-03-01")
            except Exception as ex:      # que el assert de abajo diga qué pasó
                visto["error"] = repr(ex)
            finally:
                espera.rollback()
                espera.close()
        try:
            antes = main._foto_contable(self.conn, self.uid)["canon"]("2026-03-01")
            self.conn.rollback()
            # Una FUENTE de las cuentas (un depósito a mano en el renglón del broker),
            # no la fila 'global' directo: la foto de antes recompone las cuentas
            # desde sus fuentes, como lo hace la cascada.
            otro.execute("UPDATE monthly_entries SET manual_deposits=COALESCE(manual_deposits, 0)"
                         "+1000, deposits=deposits+1000 WHERE user_id=? AND broker=? "
                         "AND year=2026 AND month=3", (self.uid, self.BROKER))
            hilo = threading.Thread(target=_segunda_puerta)
            hilo.start()
            time.sleep(0.5)
            otro.commit()
            hilo.join(15)
            self.assertEqual(visto.get("v"), antes + 1000,
                             f"leyó las cuentas antes de que la otra escritura confirmara: {visto}")
        finally:
            otro.rollback()
            otro.close()

    # ── 12. tercera auditoría ────────────────────────────────────────────────
    def _cuenta_solo_con_posiciones_a_mano(self):
        """Otra cuenta, nueva: sin depósitos, dos posiciones cargadas a mano en un
        broker sin saldo (cada una dispara su autodepósito): KO 2.000 que las fotos
        ven desde el 5-feb y PEP 3.000 desde el 10-feb."""
        uid2 = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("solo_posiciones@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (uid2, "MANUAL", "USDT"))
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: uid2
        for activo, monto, dia in (("KO", 2000, "2026-02-05"), ("PEP", 3000, "2026-02-10")):
            r = self.client.post("/api/positions", json={
                "broker": "MANUAL", "asset": activo, "buy_price": monto / 10,
                "quantity": 10, "invested": monto, "entry_date": dia})
            self.assertEqual(r.status_code, 200, r.text)
        esperado = {}
        for d in APORTADO_DEL_DIA:
            if d >= "2026-02-05":
                v = 2000.0 if d < "2026-02-10" else 5000.0
                esperado[d] = v
                self.conn.execute(
                    """INSERT INTO snapshots (user_id, date, total_value, total_invested,
                           net_deposited, fx_to_usd_blue, holdings_json, source, base, apto)
                       VALUES (?,?,?,?,?,1200,'[{"a":"KO"}]','cron','mercado',1)""",
                    (uid2, d, v, v, v))
        self.conn.commit()
        pids = {r["asset"]: r["id"] for r in self.conn.execute(
            "SELECT id, asset FROM positions WHERE user_id=? AND is_cash=0", (uid2,))}
        return esperado, pids

    def test_deshacer_devuelve_lo_aportado_a_fotos_que_el_borrado_dejo_en_cero(self):
        """Borrar KO deja las fotos del 5 al 9 en 0 (la cuenta no tenía otra cosa).
        El deshacer tiene que devolverles los 2.000: filtrarlas por "aportado 0 = no
        medida" las dejaba en 0 y la curva publicaba −44 % con el mercado quieto."""
        esperado, pids = self._cuenta_solo_con_posiciones_a_mano()
        r = self.client.delete(f"/api/positions/{pids['KO']}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar KO", {d: v - (2000.0 if v else 0) for d, v in
                                                  esperado.items()})
        r = self.client.post(f"/api/operations/undo/{r.json()['undo_token']}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("deshacer KO", esperado)

    def test_borrar_lo_unico_que_habia_y_deshacerlo(self):
        """Borradas las dos posiciones, las cuentas quedan VACÍAS: eso es "aportado 0",
        no "no sé". Las fotos pierden todo, y los dos deshacer lo devuelven."""
        esperado, pids = self._cuenta_solo_con_posiciones_a_mano()
        tokens = []
        for activo in ("KO", "PEP"):
            r = self.client.delete(f"/api/positions/{pids[activo]}")
            self.assertEqual(r.status_code, 200, r.text)
            tokens.append(r.json()["undo_token"])
        self._assert_dia_conservado("borrar las dos", {d: 0.0 for d in esperado})
        for t in reversed(tokens):
            r = self.client.post(f"/api/operations/undo/{t}")
            self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("deshacer las dos", esperado)

    def test_un_aportado_en_cero_legitimo_tambien_se_corrige(self):
        """El 20-mar se retira todo lo que se había puesto: aportado 0 de verdad, no
        una foto vieja sin medir. Borrado el depósito de febrero, esas fotos quedan
        en −10.000 (se sacó más de lo que se puso). Las fotos en 0 van SIN firma
        (`source` NULL, como las de antes de agosto de 2026): las reconoce que las
        cuentas de ese mes también dan 0. (Con firma, ver
        `test_un_cero_legitimo_a_mitad_de_mes`.)"""
        self._import(_csv("2026-03-20,RETIRO,IBKR,,,,106000,,,0,USD,"))
        self._subir("2026-03-20", "2026-03-31", -106000)
        self.conn.execute("UPDATE snapshots SET source=NULL WHERE user_id=? AND date >= ?",
                          (self.uid, "2026-03-20"))
        self.conn.commit()
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-20')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el depósito con aportado 0 legítimo",
                                    self._con({"2026-02-20": -10000, "2026-03-20": -106000}))

    def test_la_foto_del_dia_del_import_sacada_antes_del_import(self):
        """El cron que corre siempre saca la foto a las 00:00: la del 5-mar es el
        estado al EMPEZAR el 5, y el import se confirmó ese día más tarde. Las fotos
        lo tienen desde el 6: la del 5 no se movió y la del 6 sí."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,"), confirmado="2026-03-05")
        self._subir("2026-03-06", "2026-03-31", 7000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-25')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar lo importado después de la foto del día")

    def test_la_foto_del_dia_del_import_sacada_antes_de_un_resumen(self):
        """Lo mismo con un resumen que trae un depósito y un retiro: la foto del 6
        saltó el import ENTERO (+5.000), no lo borrado."""
        self._import(_csv("2026-02-10,DEPOSITO,IBKR,,,,7000,,,0,USD,",
                          "2026-02-15,RETIRO,IBKR,,,,2000,,,0,USD,"), confirmado="2026-03-05")
        self._subir("2026-03-06", "2026-03-31", 5000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el depósito del resumen después de la foto",
                                    self._con({"2026-03-06": -2000}))

    def test_el_cierre_reconstruido_de_un_mes_sin_fotos_diarias(self):
        """La reconstrucción a mercado escribe, al terminar un import, el cierre de los
        meses pasados que no tienen fotos diarias (`source='mtm_backfill'`), con lo
        importado adentro. Un depósito de diciembre confirmado el 2-abr —después de
        la última foto diaria—: ninguna foto diaria lo tiene, pero el cierre
        reconstruido de diciembre sí. Borrado, lo pierde ése."""
        self._import(_csv("2025-12-15,DEPOSITO,IBKR,,,,7000,,,0,USD,"), confirmado="2026-04-02")
        self.conn.execute(
            """INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited,
                   fx_to_usd_blue, holdings_json, source, base, apto, mtm_coverage)
               VALUES (?, '2025-12-31', 107000, 107000, 107000, 1200, '[{"a":"AAPL"}]',
                       'mtm_backfill', 'mercado', 1, 1.0)
               ON CONFLICT(user_id, date) DO UPDATE SET total_value=excluded.total_value,
                   total_invested=excluded.total_invested, net_deposited=excluded.net_deposited,
                   fx_to_usd_blue=excluded.fx_to_usd_blue, holdings_json=excluded.holdings_json,
                   source=excluded.source, base=excluded.base, apto=excluded.apto,
                   mtm_coverage=excluded.mtm_coverage""", (self.uid,))
        self.conn.commit()
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2025-12-15')}")
        self.assertEqual(r.status_code, 200, r.text)
        dic = self.conn.execute("SELECT net_deposited, source FROM snapshots WHERE user_id=? "
                                "AND date='2025-12-31'", (self.uid,)).fetchone()
        self.assertEqual(dic["source"], "mtm_backfill",
                         "algo reescribió el cierre reconstruido: el test no mide la regla")
        self.assertAlmostEqual(dic["net_deposited"], 100000.0, places=2,
                               msg="el cierre reconstruido de diciembre se quedó con lo borrado")
        self._assert_dia_conservado("borrar el depósito con cierre reconstruido")

    def test_deshacer_un_borrado_de_antes_de_este_cambio(self):
        """Un "Deshacer" cuyo journal se escribió antes de que el borrado anotara qué
        le cambió a cada foto (un token vivo al momento del deploy): vuelve a la
        fecha del borrado con el recorte del mes. Lo de después de que la posición
        entró a las fotos tiene que volver entero; del 10 al 14 (antes de que la
        cargaran) queda dentro de lo que el mes permite — límite conocido."""
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
        token = r.json()["undo_token"]
        import json as _json
        j = self.conn.execute("SELECT id, payload_json FROM deleted_ops_journal WHERE token=?",
                              (token,)).fetchone()
        p = _json.loads(j["payload_json"])
        p.pop("aportado", None)
        self.conn.execute("UPDATE deleted_ops_journal SET payload_json=? WHERE id=?",
                          (_json.dumps(p), j["id"]))
        self.conn.commit()
        r = self.client.post(f"/api/operations/undo/{token}")
        self.assertEqual(r.status_code, 200, r.text)
        servido = self._aportado_servido()
        con = self._con({"2026-02-15": 2000})
        mal = {d: (v, servido.get(d)) for d, v in con.items()
               if d >= "2026-02-15" and servido.get(d) != v}
        self.assertEqual(mal, {}, "el deshacer de un journal viejo no devolvió lo aportado")
        fuera = {d: servido.get(d) for d in _dias(2026, 2, 10, 14)
                 if not (100000.0 <= servido.get(d, 0) <= 102000.0)}
        self.assertEqual(fuera, {})

    # ── 13. cuarta auditoría ─────────────────────────────────────────────────
    def _cierre_reconstruido(self, fecha: str, aportado: float) -> None:
        """El cierre que escribe la reconstrucción a mercado después de un import
        (`source='mtm_backfill'`, con precios): pisa el día si no hay foto real."""
        self.conn.execute(
            """INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited,
                   fx_to_usd_blue, holdings_json, source, base, apto, mtm_coverage)
               VALUES (?, ?, ?, ?, ?, 1200, '[{"a":"AAPL"}]', 'mtm_backfill', 'mercado', 1, 1.0)
               ON CONFLICT(user_id, date) DO UPDATE SET total_value=excluded.total_value,
                   total_invested=excluded.total_invested, net_deposited=excluded.net_deposited,
                   fx_to_usd_blue=excluded.fx_to_usd_blue, holdings_json=excluded.holdings_json,
                   source=excluded.source, base=excluded.base, apto=excluded.apto,
                   mtm_coverage=excluded.mtm_coverage""",
            (self.uid, fecha, aportado, aportado, aportado))
        self.conn.commit()

    def test_un_cierre_reconstruido_no_arrastra_al_mes_con_fotos_diarias(self):
        """Febrero tiene fotos diarias (sacadas antes del import, sin el depósito), y
        su cierre lo reescribió la reconstrucción después del import del 5-mar, con
        el depósito adentro. Borrado, lo pierde el cierre —y las fotos desde el 5-mar—,
        no las diarias de febrero (corregir el mes entero dejaba 18 fotos mal)."""
        self._import(_csv("2026-02-10,DEPOSITO,IBKR,,,,7000,,,0,USD,"), confirmado="2026-03-05")
        self._subir("2026-03-05", "2026-03-31", 7000)
        self._cierre_reconstruido("2026-02-28", 117000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar con el cierre de febrero reconstruido")

    def test_un_cero_legitimo_a_mitad_de_mes(self):
        """El 5-feb se retira todo (aportado 0 hasta el depósito del 20): ceros con
        firma, no fotos viejas sin medir — aunque el mes no cierre en 0. Borrado el
        retiro, esas fotos vuelven a 100.000."""
        self._import(_csv("2026-02-05,RETIRO,IBKR,,,,100000,,,0,USD,"))
        self._subir("2026-02-05", "2026-03-31", -100000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('WITHDRAW', '2026-02-05')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el retiro de todo a mitad de mes")

    def test_dos_imports_el_mismo_dia_con_la_foto_del_dia_previa(self):
        """Dos archivos confirmados el 5-mar; la foto del 5 es la de las 00:00 (sin
        ninguno) y desde el 6 tienen los dos. Borrado uno, sólo desde el 6."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,"), confirmado="2026-03-05")
        self._import(_csv("2026-02-26,DEPOSITO,IBKR,,,,3000,,,0,USD,"), confirmado="2026-03-05")
        self._subir("2026-03-06", "2026-03-31", 10000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-25')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("dos imports el mismo día", self._con({"2026-03-06": 3000}))

    def test_otro_import_igual_al_dia_siguiente_no_mueve_el_comienzo(self):
        """El import A (7.000) entró en la foto del 5; el 6 entra otro import de 7.000.
        La foto del 6 salta 7.000 por B, no por A: se empieza por la del 5."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,"), confirmado="2026-03-05")
        self._subir("2026-03-05", "2026-03-31", 7000)
        self._import(_csv("2026-03-06,DEPOSITO,IBKR,,,,7000,,,0,USD,"))
        self._subir("2026-03-06", "2026-03-31", 7000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-25')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("otro import igual al día siguiente",
                                    self._con({"2026-03-06": 7000}))

    def test_otro_import_igual_al_dia_siguiente_y_otro_movimiento_el_dia_del_import(self):
        """La foto del 5 SÍ tiene el import A (7.000), pero ese día también hubo un
        retiro a mano de 2.000: saltó 5.000, no 7.000. El 6 entra otro import (B) de
        7.000 y la foto del 6 salta justo eso. Ese salto lo explica B, no A: A estaba
        desde el 5."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,"), confirmado="2026-03-05")
        r = self.client.post("/api/cash/flow", json={
            "broker_name": self.BROKER, "direction": "withdraw", "amount": 2000,
            "date": "2026-03-05"})
        self.assertEqual(r.status_code, 200, r.text)
        self._subir("2026-03-05", "2026-03-31", 5000)
        self._import(_csv("2026-03-06,DEPOSITO,IBKR,,,,7000,,,0,USD,"))
        self._subir("2026-03-06", "2026-03-31", 7000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-25')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("otro import igual al día siguiente con movimiento el día",
                                    self._con({"2026-03-05": -2000, "2026-03-06": 7000}))

    def test_la_foto_del_dia_con_otro_movimiento_ese_mismo_dia(self):
        """El import (7.000) y un depósito a mano de 3.000 el mismo 5-mar, la foto del
        5 posterior a los dos (saltó 10.000): esa foto SÍ tenía el import."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,"), confirmado="2026-03-05")
        self._depositar_a_mano("2026-03-05", 3000)
        self._subir("2026-03-05", "2026-03-31", 10000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-25')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("foto del día con otro movimiento",
                                    self._con({"2026-03-05": 3000}))

    def test_gemelo_dentro_de_un_resumen_con_la_foto_del_dia_previa(self):
        """El original (7.000 del 25-feb) entró ese día; la copia vino en el resumen
        del 5-mar con un retiro de 2.000 (neto 5.000), y la foto del 5 es previa. Se
        borra el ORIGINAL: se va la capa del resumen, desde el 6."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,original"))
        self._subir("2026-02-25", "2026-03-31", 7000)
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,copia",
                          "2026-02-27,RETIRO,IBKR,,,,2000,,,0,USD,"), confirmado="2026-03-05")
        self._subir("2026-03-06", "2026-03-31", 5000)
        original = self.conn.execute(
            "SELECT MIN(n.id) AS id FROM import_normalized_tx n JOIN import_batches b "
            "ON b.id=n.batch_id WHERE b.user_id=? AND n.date='2026-02-25' "
            "AND n.operation_type='DEPOSIT'", (self.uid,)).fetchone()["id"]
        r = self.client.delete(f"/api/movements/tx-{original}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("gemelo en un resumen",
                                    self._con({"2026-02-25": 7000, "2026-03-06": -2000}))

    def test_dos_borrados_del_mismo_resumen_con_la_foto_del_dia_previa(self):
        """Un resumen del 5-mar con dos depósitos (7.000 y 3.000), la foto del 5 previa.
        Después del primer borrado la foto del 6 ya no muestra el resumen entero: el
        salto se compara con lo que las fotos muestran HOY (lo vigente más la fila que
        se borra), no con lo que trajo el archivo."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,",
                          "2026-02-26,DEPOSITO,IBKR,,,,3000,,,0,USD,"), confirmado="2026-03-05")
        self._subir("2026-03-06", "2026-03-31", 10000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-26')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("primer borrado del resumen", self._con({"2026-03-06": 7000}))
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-25')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("segundo borrado del resumen")

    def test_deshacer_con_la_foto_de_hoy_en_lo_anotado(self):
        """Lo que anota el borrado incluye la foto de hoy, que la cascada borra después.
        El deshacer la saltea y devuelve el resto (sin eso, no devolvía nada)."""
        hoy = "2026-03-20"
        self._hasta_hoy(hoy, con_foto_de_hoy=True)
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "MANUAL", "USDT"))
        self.conn.commit()
        with mock.patch.object(main, "_iso_today", return_value=hoy):
            r = self.client.post("/api/positions", json={
                "broker": "MANUAL", "asset": "KO", "buy_price": 50, "quantity": 40,
                "invested": 2000, "entry_date": "2026-02-10"})
            self.assertEqual(r.status_code, 200, r.text)
            self._subir("2026-02-15", hoy, 2000)
            pid = self.conn.execute(
                "SELECT id FROM positions WHERE user_id=? AND broker='MANUAL' AND asset='KO'",
                (self.uid,)).fetchone()["id"]
            hoy_id = self.conn.execute("SELECT id FROM snapshots WHERE user_id=? AND date=?",
                                       (self.uid, hoy)).fetchone()["id"]
            r = self.client.delete(f"/api/positions/{pid}")
            self.assertEqual(r.status_code, 200, r.text)
            token = r.json()["undo_token"]
            import json as _json
            plan = _json.loads(self.conn.execute(
                "SELECT payload_json FROM deleted_ops_journal WHERE token=?",
                (token,)).fetchone()["payload_json"]).get("aportado")
            self.assertIn(str(hoy_id), (plan or {}).get("fotos", {}),
                          "lo anotado ya no incluye la foto de hoy: el test no mide el caso")
            r = self.client.post(f"/api/operations/undo/{token}")
            self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("deshacer con la foto de hoy anotada",
                                    self._con({"2026-02-15": 2000}, hasta=hoy))

    def test_cuentas_desfasadas_no_son_lo_borrado(self):
        """Faltan las filas 'global' de la contabilidad (`DELETE /api/monthly/{eid}` las
        borra sin recalcular). Borrar un dividendo no cambia ningún flujo: que el
        recálculo de la cascada las vuelva a armar no es "antes había 0" (le
        adjudicaba al borrado todo lo aportado y duplicaba 90 fotos)."""
        self.conn.execute("DELETE FROM monthly_entries WHERE user_id=? AND broker='global'",
                          (self.uid,))
        self.conn.commit()
        self.assertIsNone(twr.netdep_canonico(self.conn, self.uid))
        r = self.client.delete(f"/api/movements/tx-{self._tx('DIVIDEND', '2025-12-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar un dividendo con la contabilidad desfasada")

    # ── 14. quinta auditoría ─────────────────────────────────────────────────
    def _me_dep_de(self, anio: int, mes: int) -> str:
        me = self.conn.execute(
            "SELECT id FROM monthly_entries WHERE user_id=? AND broker=? AND year=? "
            "AND month=? AND manual_deposits > 0", (self.uid, self.BROKER, anio, mes)).fetchone()
        self.assertIsNotNone(me, f"no hay depósito manual en {anio}-{mes}")
        return f"me-{me['id']}-dep"

    def test_a_mano_con_un_cierre_reconstruido_en_un_mes_sin_fotos_diarias(self):
        """Diciembre no tiene fotos diarias: su cierre lo escribe la reconstrucción a
        mercado. El 5-mar se carga a mano un depósito fechado el 15-dic; las fotos lo
        tienen desde el 5. Un import posterior reescribe el cierre de diciembre con
        él adentro. Borrado: lo pierden ese cierre y las fotos desde el 5-mar — no
        enero ni febrero, que nunca lo tuvieron (antes: 63 fotos mal)."""
        self._depositar_a_mano("2025-12-15", 3000)
        self._subir("2026-03-05", "2026-03-31", 3000)
        self._cierre_reconstruido("2025-12-31", 103000)
        r = self.client.delete(f"/api/movements/{self._me_dep_de(2025, 12)}")
        self.assertEqual(r.status_code, 200, r.text)
        dic = self.conn.execute("SELECT net_deposited FROM snapshots WHERE user_id=? "
                                "AND date='2025-12-31'", (self.uid,)).fetchone()
        self.assertAlmostEqual(dic["net_deposited"], 100000.0, places=2)
        self._assert_dia_conservado("a mano de diciembre con cierre reconstruido")

    def test_a_mano_con_un_cierre_reconstruido_en_un_mes_con_fotos_diarias(self):
        """Febrero tiene fotos diarias salvo el cierre, reconstruido después de que se
        cargó a mano (el 5-mar) un depósito fechado el 15-feb. La prueba es la última
        foto DIARIA de febrero, que no lo tenía."""
        self._depositar_a_mano("2026-02-15", 3000)
        self._subir("2026-03-05", "2026-03-31", 3000)
        self._cierre_reconstruido("2026-02-28", 113000)
        r = self.client.delete(f"/api/movements/{self._me_dep_de(2026, 2)}")
        self.assertEqual(r.status_code, 200, r.text)
        esperado = dict(APORTADO_DEL_DIA)
        esperado["2026-02-28"] = 110000.0
        self._assert_dia_conservado("a mano de febrero con cierre reconstruido", esperado)

    def test_otro_import_al_dia_siguiente_con_el_cron_de_las_cero(self):
        """El cron de las 00:00: el import A (5-mar) aparece en la foto del 6 y el B
        (6-mar) en la del 7. La foto del 6 saltó lo de A: se empieza por ahí, aunque B
        se haya confirmado ese día."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,"), confirmado="2026-03-05")
        self._subir("2026-03-06", "2026-03-31", 7000)
        self._import(_csv("2026-03-06,DEPOSITO,IBKR,,,,1000,,,0,USD,"))
        self._subir("2026-03-07", "2026-03-31", 1000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-25')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("otro import al día siguiente, cron 00:00",
                                    self._con({"2026-03-07": 1000}))

    def test_duplicado_con_fotos_previas_borrar_el_original_y_despues_la_copia(self):
        """El original confirmado el 12-mar y la copia el 18, las fotos de esos días
        sacadas antes de cada import. Se borran los dos (no existió). El segundo
        borrado se lleva la capa del original, que ya figuraba borrado: las fotos
        todavía la muestran y el salto de su import tiene que contarlo."""
        self._import(_csv("2026-03-12,DEPOSITO,IBKR,,,,7000,,,0,USD,original"), confirmado="2026-03-12")
        self._subir("2026-03-13", "2026-03-31", 7000)
        self._import(_csv("2026-03-12,DEPOSITO,IBKR,,,,7000,,,0,USD,copia"), confirmado="2026-03-18")
        self._subir("2026-03-19", "2026-03-31", 7000)
        for cual in ("original", "copia"):
            r = self.client.delete(f"/api/movements/tx-{self._gemelo(cual)}")
            self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("duplicado con fotos previas, borrar los dos")

    def test_un_resumen_con_compras_y_dividendos_y_la_foto_del_dia_previa(self):
        """El salto del import cuenta sólo depósitos y retiros: una compra y un
        dividendo del mismo archivo no mueven lo aportado."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,",
                          "2026-02-26,COMPRA,IBKR,MSFT,2,500,1000,,,0,USD,",
                          "2026-02-27,DIVIDENDO,IBKR,AAPL,,,50,,,0,USD,"), confirmado="2026-03-05")
        self._subir("2026-03-06", "2026-03-31", 7000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-25')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("resumen con compras, foto del día previa")

    def test_dos_imports_confirmados_de_noche_el_mismo_dia(self):
        """Los dos a las 22:30 y 22:45 del 5-mar (01:30 y 01:45 UTC del 6): son del 5
        argentino, y la foto del 5 (00:00) no tiene ninguno."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,"),
                     confirmado_utc="2026-03-06 01:30:00")
        self._import(_csv("2026-02-26,DEPOSITO,IBKR,,,,3000,,,0,USD,"),
                     confirmado_utc="2026-03-06 01:45:00")
        self._subir("2026-03-06", "2026-03-31", 10000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-25')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("dos imports de noche", self._con({"2026-03-06": 3000}))

    def test_la_foto_del_dia_sacada_entre_dos_imports(self):
        """El Dashboard sacó la foto del 5 entre el import A (que la foto tiene) y el B
        (que aparece desde el 6). Borrado B, se empieza el 6."""
        self._import(_csv("2026-02-25,DEPOSITO,IBKR,,,,7000,,,0,USD,"),
                     confirmado_utc="2026-03-05 13:00:00")
        self._subir("2026-03-05", "2026-03-31", 7000)
        self._import(_csv("2026-02-26,DEPOSITO,IBKR,,,,3000,,,0,USD,"),
                     confirmado_utc="2026-03-05 18:00:00")
        self._subir("2026-03-06", "2026-03-31", 3000)
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2026-02-26')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("foto entre dos imports", self._con({"2026-03-05": 7000}))

    def test_deshacer_de_antes_de_este_cambio_en_una_cuenta_vacia(self):
        """Dos posiciones a mano borradas (la cuenta queda vacía) con journals sin lo
        anotado (de antes de este cambio). Deshacer la última: las cuentas de antes
        están vacías, y eso es 0 (no "no sé"): PEP vuelve desde el 10-feb."""
        import json as _json
        esperado, pids = self._cuenta_solo_con_posiciones_a_mano()
        tokens = []
        for activo in ("KO", "PEP"):
            r = self.client.delete(f"/api/positions/{pids[activo]}")
            self.assertEqual(r.status_code, 200, r.text)
            tokens.append(r.json()["undo_token"])
        for t in tokens:
            j = self.conn.execute("SELECT id, payload_json FROM deleted_ops_journal WHERE token=?",
                                  (t,)).fetchone()
            p = _json.loads(j["payload_json"])
            p.pop("aportado", None)
            self.conn.execute("UPDATE deleted_ops_journal SET payload_json=? WHERE id=?",
                              (_json.dumps(p), j["id"]))
        self.conn.commit()
        r = self.client.post(f"/api/operations/undo/{tokens[-1]}")
        self.assertEqual(r.status_code, 200, r.text)
        servido = self._aportado_servido()
        mal = {d: servido.get(d) for d in esperado
               if d >= "2026-02-10" and abs((servido.get(d) or 0) - 3000.0) > 0.01}
        self.assertEqual(mal, {}, "el deshacer viejo en una cuenta vacía no devolvió PEP")

    def test_un_cero_firmado_por_el_navegador(self):
        """Ceros con firma 'browser' (el Dashboard también mide): cuentan como los del
        cron."""
        self._import(_csv("2026-02-05,RETIRO,IBKR,,,,100000,,,0,USD,"))
        self._subir("2026-02-05", "2026-03-31", -100000)
        self.conn.execute("UPDATE snapshots SET source='browser' WHERE user_id=? "
                          "AND net_deposited=0", (self.uid,))
        self.conn.commit()
        r = self.client.delete(f"/api/movements/tx-{self._tx('WITHDRAW', '2026-02-05')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("borrar el retiro con ceros del navegador")

    def test_el_resumen_mensual_editado_a_mano_no_es_lo_borrado(self):
        """Febrero editado a mano en el resumen mensual (pestaña Global): la fila dice
        0 depósitos y lo importado dice 10.000. Borrar un dividendo de diciembre: el
        recálculo de la cascada recompone febrero, y eso no es lo borrado — las cuentas
        de antes se leen recompuestas igual (antes: 59 fotos con 10.000 de más)."""
        r = self.conn.execute("SELECT id FROM monthly_entries WHERE user_id=? AND broker='global' "
                              "AND year=2026 AND month=2", (self.uid,)).fetchone()
        self.conn.execute("UPDATE monthly_entries SET deposits=0 WHERE id=?", (r["id"],))
        self.conn.commit()
        r = self.client.delete(f"/api/movements/tx-{self._tx('DIVIDEND', '2025-12-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("dividendo con febrero editado a mano")

    def test_si_no_se_pueden_recomponer_las_cuentas_de_antes(self):
        """Si recomponer las cuentas de antes falla, se leen como están. Y si así
        FALTAN (las filas 'global' borradas a mano), en un borrado eso no es "antes
        había 0": no se toca ninguna foto (le adjudicaba al borrado de un dividendo
        todo lo aportado)."""
        self.conn.execute("DELETE FROM monthly_entries WHERE user_id=? AND broker='global'",
                          (self.uid,))
        self.conn.commit()
        real = main._recalc_pnl_realized_from_ops
        llamadas = []

        def _falla_la_primera(conn, uid):
            llamadas.append(1)
            if len(llamadas) == 1:      # la de `_foto_contable`; la cascada recalcula bien
                raise RuntimeError("simulado: no se pudieron recomponer las cuentas")
            return real(conn, uid)
        with mock.patch.object(main, "_recalc_pnl_realized_from_ops",
                               side_effect=_falla_la_primera):
            r = self.client.delete(f"/api/movements/tx-{self._tx('DIVIDEND', '2025-12-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertGreaterEqual(len(llamadas), 2, "la foto de antes no intentó recomponer")
        self._assert_dia_conservado("sin poder recomponer, con las filas global faltantes")

    def test_un_mes_del_resumen_borrado_a_mano_no_es_lo_borrado(self):
        """Lo mismo con la fila 'global' de febrero borrada (el tacho del resumen)."""
        self.conn.execute("DELETE FROM monthly_entries WHERE user_id=? AND broker='global' "
                          "AND year=2026 AND month=2", (self.uid,))
        self.conn.commit()
        r = self.client.delete(f"/api/movements/tx-{self._tx('DIVIDEND', '2025-12-10')}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("dividendo con febrero borrado del resumen")

    # ── 15. sexta auditoría ──────────────────────────────────────────────────
    def _editar_mensual(self, broker: str, anio: int, mes: int, **cambios) -> None:
        """Edita un renglón del resumen mensual por la puerta de la app (el lápiz de
        /mensual): `PUT /api/monthly/{id}` escribe ese renglón y NO recalcula ni
        propaga a 'global' — las cuentas quedan desfasadas de sus fuentes."""
        fila = dict(self.conn.execute(
            "SELECT * FROM monthly_entries WHERE user_id=? AND broker=? AND year=? AND month=?",
            (self.uid, broker, anio, mes)).fetchone())
        body = {k: fila[k] or 0 for k in ("year", "month", "deposits", "withdrawals",
                                          "pnl_realized", "pnl_unrealized", "capital_inicio",
                                          "capital_final")}
        body["broker"] = broker
        body.update(cambios)
        r = self.client.put(f"/api/monthly/{fila['id']}", json=body)
        self.assertEqual(r.status_code, 200, r.text)

    def _desfase_de(self, monto: float) -> None:
        """Un depósito a mano de `monto` el 10-ene (las fotos lo tienen) que después se
        saca desde /mensual: 'global' no se entera, así que las cuentas tal cual (y las
        fotos) lo siguen teniendo y recompuestas no."""
        self._depositar_a_mano("2026-01-10", monto)
        self._subir("2026-01-10", "2026-03-31", monto)
        self._editar_mensual(self.BROKER, 2026, 1, deposits=0)

    def test_resumen_mensual_desfasado_y_borrar_algo_a_mano_con_fecha_vieja(self):
        """Con /mensual desfasado en 500, se borra un depósito a mano fechado 15-dic y
        cargado el 5-mar: lo pierden sólo las fotos desde el 5-mar. (Comparando las
        fotos diarias sólo con las cuentas recompuestas, febrero entero "lo tenía":
        54 fotos mal.)"""
        self._desfase_de(500)
        self._depositar_a_mano("2025-12-15", 3000)
        self._subir("2026-03-05", "2026-03-31", 3000)
        r = self.client.delete(f"/api/movements/{self._me_dep_de(2025, 12)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("desfase de 500 + borrar el a mano de diciembre",
                                    self._con({"2026-01-10": 500}))

    def test_un_desfase_de_centavos_y_una_posicion_a_mano_con_fecha_vieja(self):
        """Un desfase de apenas US$ 20 alcanzaba. Posición a mano fechada 15-dic,
        cargada el 5-mar: borrarla y deshacer."""
        self._desfase_de(20)
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "MANUAL", "USDT"))
        self.conn.commit()
        r = self.client.post("/api/positions", json={
            "broker": "MANUAL", "asset": "KO", "buy_price": 50, "quantity": 40,
            "invested": 2000, "entry_date": "2025-12-15"})
        self.assertEqual(r.status_code, 200, r.text)
        self._subir("2026-03-05", "2026-03-31", 2000)
        pid = self.conn.execute(
            "SELECT id FROM positions WHERE user_id=? AND broker='MANUAL' AND asset='KO'",
            (self.uid,)).fetchone()["id"]
        r = self.client.delete(f"/api/positions/{pid}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("desfase de 20 + borrar la posición",
                                    self._con({"2026-01-10": 20}))
        r = self.client.post(f"/api/operations/undo/{r.json()['undo_token']}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("deshacerla", self._con({"2026-01-10": 20, "2026-03-05": 2000}))

    def test_cargado_hoy_y_borrado_hoy_con_el_cierre_reescrito(self):
        """Hoy 20-mar se carga a mano un depósito fechado 15-dic; un import de hoy
        reescribe el cierre reconstruido de diciembre con él; se borra hoy mismo.
        Ninguna foto diaria lo tuvo: sólo el cierre (antes: 78 fotos mal)."""
        hoy = "2026-03-20"
        self._hasta_hoy(hoy, con_foto_de_hoy=True)
        self._depositar_a_mano("2025-12-15", 3000)
        self._cierre_reconstruido("2025-12-31", 103000)
        with mock.patch.object(main, "_iso_today", return_value=hoy):
            r = self.client.delete(f"/api/movements/{self._me_dep_de(2025, 12)}")
        self.assertEqual(r.status_code, 200, r.text)
        dic = self.conn.execute("SELECT net_deposited FROM snapshots WHERE user_id=? "
                                "AND date='2025-12-31'", (self.uid,)).fetchone()
        self.assertAlmostEqual(dic["net_deposited"], 100000.0, places=2)
        self._assert_dia_conservado("cargado y borrado hoy", self._con({}, hasta=hoy))

    def test_posicion_cargada_hoy_y_borrada_hoy_con_el_cierre_reescrito(self):
        """Lo mismo con una posición a mano (el caso típico del alta de una cuenta), y
        su deshacer devuelve exactamente lo que sacó."""
        hoy = "2026-03-20"
        self._hasta_hoy(hoy, con_foto_de_hoy=True)
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "MANUAL", "USDT"))
        self.conn.commit()
        with mock.patch.object(main, "_iso_today", return_value=hoy):
            r = self.client.post("/api/positions", json={
                "broker": "MANUAL", "asset": "KO", "buy_price": 50, "quantity": 40,
                "invested": 2000, "entry_date": "2025-12-15"})
            self.assertEqual(r.status_code, 200, r.text)
            self._cierre_reconstruido("2025-12-31", 102000)
            pid = self.conn.execute(
                "SELECT id FROM positions WHERE user_id=? AND broker='MANUAL' AND asset='KO'",
                (self.uid,)).fetchone()["id"]
            r = self.client.delete(f"/api/positions/{pid}")
            self.assertEqual(r.status_code, 200, r.text)
            dic = self.conn.execute("SELECT net_deposited FROM snapshots WHERE user_id=? "
                                    "AND date='2025-12-31'", (self.uid,)).fetchone()
            self.assertAlmostEqual(dic["net_deposited"], 100000.0, places=2)
            self._assert_dia_conservado("posición cargada y borrada hoy", self._con({}, hasta=hoy))
            r = self.client.post(f"/api/operations/undo/{r.json()['undo_token']}")
            self.assertEqual(r.status_code, 200, r.text)
        dic = self.conn.execute("SELECT net_deposited FROM snapshots WHERE user_id=? "
                                "AND date='2025-12-31'", (self.uid,)).fetchone()
        self.assertAlmostEqual(dic["net_deposited"], 102000.0, places=2)
        self._assert_dia_conservado("deshacerla", self._con({}, hasta=hoy))

    def test_la_prueba_es_la_ultima_foto_diaria_del_mes(self):
        """Depósito a mano fechado 10-feb y cargado el 22-feb (las fotos lo tienen desde
        el 22), y el cierre de febrero reconstruido. La foto diaria que prueba si el
        mes lo tenía es la ÚLTIMA (con la primera, del 1-feb, el mes "no lo tenía" y
        del 22 al 27 se quedaban con lo borrado)."""
        self._depositar_a_mano("2026-02-10", 3000)
        self._subir("2026-02-22", "2026-03-31", 3000)
        self._cierre_reconstruido("2026-02-28", 113000)
        r = self.client.delete(f"/api/movements/{self._me_dep_de(2026, 2)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("a mano de febrero, cierre reconstruido")

    def test_el_resumen_global_editado_y_despues_borrar_algo_a_mano(self):
        """Febrero de la pestaña Global editado a mano (depósitos en 0): las fotos se
        siguen sacando con esas cuentas. Después se borra un depósito a mano del
        5-mar: lo pierden sólo las fotos desde el 5 (antes quedaban 27 con él)."""
        self._editar_mensual("global", 2026, 2, deposits=0)
        self._depositar_a_mano("2026-03-05", 3000)
        self._subir("2026-03-05", "2026-03-31", 3000)
        r = self.client.delete(f"/api/movements/{self._me_dep_de(2026, 3)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("global de febrero editado + borrar el a mano de marzo")

    # ── 16. séptima auditoría ────────────────────────────────────────────────
    def _global_mas(self, anio: int, mes: int, monto: float) -> None:
        """Le suma `monto` a los depósitos de un mes en la pestaña Global de /mensual
        (el lápiz: escribe ese renglón y no recalcula)."""
        fila = self.conn.execute(
            "SELECT deposits FROM monthly_entries WHERE user_id=? AND broker='global' "
            "AND year=? AND month=?", (self.uid, anio, mes)).fetchone()
        self._editar_mensual("global", anio, mes, deposits=float(fila["deposits"] or 0) + monto)

    def test_la_fila_global_agregada_el_dia_del_borrado(self):
        """Hoy se agrega a mano en la pestaña Global un depósito de enero de 5.000
        (ninguna foto lo vio) y se borra un depósito a mano de 3.000 del 5-mar: lo
        pierden las fotos desde el 5. Las cuentas recompuestas dicen que a las fotos
        les falta lo borrado y las tal cual que les sobra lo de Global: decide la que
        cuadra exacto (con "cualquiera de las dos" a secas, 27 fotos se quedaban con
        lo borrado)."""
        r = self.client.post("/api/monthly", json={"year": 2026, "month": 1, "broker": "global",
                                                   "deposits": 5000, "withdrawals": 0})
        self.assertEqual(r.status_code, 200, r.text)
        self._depositar_a_mano("2026-03-05", 3000)
        self._subir("2026-03-05", "2026-03-31", 3000)
        r = self.client.delete(f"/api/movements/{self._me_dep(3)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("global agregada hoy + borrar el a mano de marzo")

    def test_la_fila_global_agregada_dias_antes_del_borrado(self):
        """Lo mismo con la fila Global agregada el 10-mar (las fotos la tienen desde
        ahí) y un depósito a mano del 15-feb que las fotos tienen desde el 15-feb
        (antes: 31 fotos mal)."""
        self._depositar_a_mano("2026-02-15", 3000)
        self._subir("2026-02-15", "2026-03-31", 3000)
        r = self.client.post("/api/monthly", json={"year": 2026, "month": 1, "broker": "global",
                                                   "deposits": 5000, "withdrawals": 0})
        self.assertEqual(r.status_code, 200, r.text)
        self._subir("2026-03-10", "2026-03-31", 5000)
        r = self.client.delete(f"/api/movements/{self._me_dep_de(2026, 2)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("global agregada el 10-mar + borrar el a mano de febrero",
                                    self._con({"2026-03-10": 5000}))

    def test_corregir_la_global_y_despues_borrar_una_posicion_a_mano(self):
        """Posición a mano fechada 15-dic y cargada el 5-feb; el 10-mar se corrige
        febrero en la pestaña Global (+5.000); el 20 se borra la posición y se
        deshace. El ajuste de Global (mayor que lo borrado) hacía creer que ninguna
        foto la tenía: 32 fotos se quedaban con ella."""
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "MANUAL", "USDT"))
        self.conn.commit()
        r = self.client.post("/api/positions", json={
            "broker": "MANUAL", "asset": "KO", "buy_price": 50, "quantity": 40,
            "invested": 2000, "entry_date": "2025-12-15"})
        self.assertEqual(r.status_code, 200, r.text)
        self._subir("2026-02-05", "2026-03-31", 2000)
        self._global_mas(2026, 2, 5000)
        self._subir("2026-03-10", "2026-03-31", 5000)
        pid = self.conn.execute(
            "SELECT id FROM positions WHERE user_id=? AND broker='MANUAL' AND asset='KO'",
            (self.uid,)).fetchone()["id"]
        r = self.client.delete(f"/api/positions/{pid}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("global corregida + borrar la posición",
                                    self._con({"2026-03-10": 5000}))
        r = self.client.post(f"/api/operations/undo/{r.json()['undo_token']}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("deshacerla",
                                    self._con({"2026-02-05": 2000, "2026-03-10": 5000}))

    def test_la_global_bajada_a_cero_y_un_a_mano_viejo_cargado_tarde(self):
        """Febrero de la pestaña Global en 0 (desfase hacia abajo) y un depósito a mano
        fechado 10-ene cargado el 5-mar: lo pierden sólo las fotos desde el 5. Mirando
        sólo las cuentas tal cual, 13 fotos quedaban mal."""
        self._editar_mensual("global", 2026, 2, deposits=0)
        self._depositar_a_mano("2026-01-10", 3000)
        self._subir("2026-03-05", "2026-03-31", 3000)
        r = self.client.delete(f"/api/movements/{self._me_dep(1)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("global de febrero en 0 + borrar el a mano de enero")

    def test_un_desfase_y_un_cierre_reconstruido_con_fotos_diarias(self):
        """Con /mensual desfasado en 500 y el cierre de febrero reconstruido (con lo
        borrado adentro), se borra un depósito a mano del 15-feb cargado el 5-mar: las
        fotos diarias desde el 5-mar y ese cierre lo pierden; las diarias de febrero no
        lo tenían. Juzgando también las diarias de un mes con cierre reconstruido sólo
        con las cuentas recompuestas, 4 fotos de marzo se quedaban con él."""
        self._desfase_de(500)
        self._depositar_a_mano("2026-02-15", 3000)
        self._subir("2026-03-05", "2026-03-31", 3000)
        self._cierre_reconstruido("2026-02-28", 113500)
        r = self.client.delete(f"/api/movements/{self._me_dep_de(2026, 2)}")
        self.assertEqual(r.status_code, 200, r.text)
        esperado = self._con({"2026-01-10": 500})
        esperado["2026-02-28"] = 110500.0
        self._assert_dia_conservado("desfase + cierre de febrero reconstruido", esperado)

    def test_cargado_hoy_con_dos_cierres_reescritos(self):
        """Hoy 20-mar se carga un depósito a mano fechado 15-dic y un import reescribe
        los cierres de diciembre y de enero (enero sin fotos diarias); se borra hoy.
        Ninguna foto diaria lo tuvo: lo pierden LOS DOS cierres (corrigiendo sólo el
        primero, enero quedaba con 3.000 de más)."""
        hoy = "2026-03-20"
        self._hasta_hoy(hoy, con_foto_de_hoy=True)
        self.conn.execute("DELETE FROM snapshots WHERE user_id=? "
                          "AND date BETWEEN '2026-01-01' AND '2026-01-31'", (self.uid,))
        self.conn.commit()
        self._depositar_a_mano("2025-12-15", 3000)
        self._cierre_reconstruido("2025-12-31", 103000)
        self._cierre_reconstruido("2026-01-31", 103000)
        with mock.patch.object(main, "_iso_today", return_value=hoy):
            r = self.client.delete(f"/api/movements/{self._me_dep_de(2025, 12)}")
        self.assertEqual(r.status_code, 200, r.text)
        cierres = {r["date"]: r["net_deposited"] for r in self.conn.execute(
            "SELECT date, net_deposited FROM snapshots WHERE user_id=? "
            "AND date IN ('2025-12-31', '2026-01-31')", (self.uid,))}
        self.assertEqual(cierres, {"2025-12-31": 100000.0, "2026-01-31": 100000.0})
        self._assert_dia_conservado("cargado hoy, dos cierres reescritos, borrado hoy", {
            d: v for d, v in self._con({}, hasta=hoy).items() if not d.startswith("2026-01")})

    def test_un_cierre_reconstruido_se_juzga_con_las_cuentas_recompuestas(self):
        """El cierre de febrero reconstruido con un depósito a mano del 15-feb (cargado
        el 5-mar) adentro, y hoy una fila Global de enero de +5.000 que ninguna foto
        vio: borrar el depósito se lo saca al cierre y a las diarias desde el 5. El
        cierre se estampa justo después de un recálculo: mirarlo también con las
        cuentas tal cual (que traen los 5.000 de hoy) dejaba 28 fotos mal."""
        self._depositar_a_mano("2026-02-15", 3000)
        self._subir("2026-03-05", "2026-03-31", 3000)
        self._cierre_reconstruido("2026-02-28", 113000)
        r = self.client.post("/api/monthly", json={"year": 2026, "month": 1, "broker": "global",
                                                   "deposits": 5000, "withdrawals": 0})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.delete(f"/api/movements/{self._me_dep_de(2026, 2)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("cierre reconstruido + global de hoy + borrar el a mano")

    def test_la_global_bajada_y_las_fotos_que_ya_la_tienen(self):
        """El 1-mar se baja febrero 5.000 en la pestaña Global y las fotos desde ahí
        lo tienen; un depósito a mano del 15-feb cargado el 5-mar se borra. La última
        foto de marzo cuadra exacto con las cuentas tal cual (lo tenía); con las
        recompuestas "le faltan" 5.000. Decidiendo sólo con la recompuesta, ninguna
        foto lo tenía y las de marzo se quedaban con él."""
        self._global_mas(2026, 2, -5000)
        self._subir("2026-03-01", "2026-03-31", -5000)
        self._depositar_a_mano("2026-02-15", 3000)
        self._subir("2026-03-05", "2026-03-31", 3000)
        r = self.client.delete(f"/api/movements/{self._me_dep_de(2026, 2)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("global bajada + borrar el a mano de febrero",
                                    self._con({"2026-03-01": -5000}))

    def _otro_broker_deposita(self, fecha: str, monto: float, cargado: str) -> None:
        """Un depósito a mano en OTRO broker fechado `fecha` y cargado `cargado`:
        las fotos lo tienen desde que se cargó, no desde su fecha."""
        if not self.conn.execute("SELECT 1 FROM brokers WHERE user_id=? AND name='OTRO'",
                                 (self.uid,)).fetchone():
            self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                              (self.uid, "OTRO", "USDT"))
            self.conn.commit()
        self._depositar_a_mano(fecha, monto, broker="OTRO")
        self._subir(cargado, "2026-03-31", monto)

    def test_un_desfase_y_otro_deposito_cargado_despues_del_cierre(self):
        """Con /mensual desfasado 500 hacia arriba, un depósito de 300 de febrero en
        otro broker cargado el 20-mar y uno de 3.000 del 15-feb cargado el 5-mar: se
        borra el de 3.000. Al cierre de febrero no le cuadra exacto ninguna lectura
        (le faltan los dos); con la recompuesta le faltan 2.800 —menos que lo
        borrado— y con la tal cual 3.300. Mirando sólo la recompuesta (o pidiendo que
        lo digan las dos), febrero "lo tenía" y sus fotos lo perdían sin tenerlo."""
        self._desfase_de(500)
        self._otro_broker_deposita("2026-02-12", 300, cargado="2026-03-20")
        self._depositar_a_mano("2026-02-15", 3000)
        self._subir("2026-03-05", "2026-03-31", 3000)
        r = self.client.delete(f"/api/movements/{self._me_dep_de(2026, 2)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("desfase + otro depósito cargado tarde",
                                    self._con({"2026-01-10": 500, "2026-03-20": 300}))

    def test_la_global_editada_sin_fotos_y_otro_deposito_cargado_despues(self):
        """Febrero de la pestaña Global en 0 (ninguna foto lo vio), un depósito de 300
        de febrero en otro broker cargado el 20-mar y uno de 3.000 del 10-ene cargado
        el 5-mar: se borra el de 3.000. Al cierre de febrero le faltan 3.300 con la
        recompuesta (no lo tenía) y le sobran con la tal cual: mirando sólo la tal
        cual, febrero "lo tenía"."""
        self._editar_mensual("global", 2026, 2, deposits=0)
        self._otro_broker_deposita("2026-02-12", 300, cargado="2026-03-20")
        self._depositar_a_mano("2026-01-10", 3000)
        self._subir("2026-03-05", "2026-03-31", 3000)
        r = self.client.delete(f"/api/movements/{self._me_dep(1)}")
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_dia_conservado("global en 0 + otro depósito cargado tarde",
                                    self._con({"2026-03-20": 300}))

    def test_dos_borrados_a_la_vez_ninguno_se_lleva_lo_del_otro(self):
        """El borrado A (depósito importado del 20-feb) está a mitad de su cascada,
        sin confirmar, cuando entra B (depósito a mano de 3.000 del 5-mar) por la
        app. B espera el turno y recién después lee las cuentas —también las tal
        cual—: cada uno saca lo suyo. Leyendo las tal cual antes del turno, B veía el
        depósito de A todavía adentro y 27 fotos quedaban mal."""
        if getattr(main, "USANDO_PG", False):
            self.skipTest("el turno de SQLite; en Postgres es la fila del usuario")
        import threading
        import time
        self._depositar_a_mano("2026-03-05", 3000)
        self._subir("2026-03-05", "2026-03-31", 3000)
        me = self._me_dep(3)
        tx = self._tx("DEPOSIT", "2026-02-20")
        otro = main.get_db()
        res = {}

        def _b():
            res["b"] = self.client.delete(f"/api/movements/{me}")
        try:
            since, brokers, entrada, antes = main._delete_one_movement(otro, self.uid, f"tx-{tx}")
            main._cascade_after_movement_delete(otro, self.uid, since, brokers, antes=antes,
                                                entrada=entrada)
            hilo = threading.Thread(target=_b)
            hilo.start()
            time.sleep(1.0)          # B ya entró y espera el turno
            otro.commit()
            hilo.join(30)
        finally:
            otro.rollback()
            otro.close()
        self.assertEqual(res["b"].status_code, 200, res["b"].text)
        self._assert_dia_conservado("dos borrados a la vez", {
            d: v - (10000 if d >= "2026-02-20" else 0) for d, v in APORTADO_DEL_DIA.items()})

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
        foto = main._foto_contable(self.conn, self.uid)
        with self.conn:
            main._cascade_after_movement_delete(self.conn, self.uid, None, {self.BROKER},
                                                antes=foto)
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
        for d, nd in aportado_del_dia.items():
            v = nd + (ganancia_desde_el_2 if d >= "2026-09-02" else 0.0)
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
                (self.uid, d, v, nd, nd))
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
        # Primero lo que ve el usuario; después la causa: una compra no cambia lo
        # aportado, así que ni una foto del cron se puede haber movido.
        self._assert_publica(esperado, "después de borrar la compra del 2/9")
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
