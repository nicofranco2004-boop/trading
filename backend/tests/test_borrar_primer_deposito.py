"""Borrar el PRIMER depósito de una cuenta tiene que bajar lo aportado.

EL BUG (auditoría del 2026-10-03, escenario "03b"). Una cuenta cuyo primer
depósito (100.000 en noviembre) es lo único de su mes. Al borrarlo:

  1. `_recalc_pnl_realized_from_ops` deja la fila de noviembre toda en cero y la
     BORRA (limpieza de filas sin respaldo).
  2. Diciembre pasa a ser la primera fila, y su `capital_inicio` seguía en
     100.000: lo había heredado de la cadena de meses (`capital_inicio[N] =
     capital_final[N−1]`) cuando noviembre todavía tenía el depósito. La cadena se
     reparaba DESPUÉS de borrar noviembre, y la primera fila no la toca nadie.
  3. Todos los lectores toman el `capital_inicio` de la primera fila como el
     capital que la persona ya tenía antes de empezar (el "baseline" que se puede
     declarar a mano en /mensual): el cron, el anclado de las fotos, la
     reconstrucción, Reportes, el Dashboard. Los 100.000 borrados seguían
     contando como aportados — en la contabilidad y en cada foto.

Un baseline cargado a mano es legítimo y tiene que sobrevivir: lo que se corrige
es que el dinero de un mes borrado no se convierta en baseline.

Entra por las MISMAS puertas HTTP que la app (importar, borrar un movimiento,
revertir un import, borrar un broker, cargar y borrar un depósito a mano); lo
único reemplazado es el login (`dependency_overrides`). Mercado QUIETO: cada foto
vale exactamente lo aportado ese día.
"""
import io
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
import snapshots_job
import twr
from reporting import builder
from snapshots_job import compute_net_deposited_db

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


DIAS = (_dias(2025, 11, 5, 30) + _dias(2025, 12, 1, 31)
        + _dias(2026, 1, 1, 31) + _dias(2026, 2, 1, 28))


def _aportado(con_noviembre: bool, baseline: float = 0.0) -> dict:
    """Lo que la foto de cada noche anota como aportado.
         2025-11-05  depósito 100.000   ← el que se borra
         2025-12-02  depósito   5.000
         2026-02-20  depósito   2.000"""
    nov = 100000.0 if con_noviembre else 0.0
    out = {}
    for d in DIAS:
        v = baseline + nov
        if d >= "2025-12-02":
            v += 5000.0
        if d >= "2026-02-20":
            v += 2000.0
        out[d] = v
    return out


class _Base(unittest.TestCase):
    BROKER = "IBKR"
    BASELINE = 0.0                 # lo que la persona declaró a mano en /mensual

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
            ("primer_deposito@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, self.BROKER, "USDT"))
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        self.conn.close()

    # ── infra ────────────────────────────────────────────────────────────────
    def _import(self, csv_bytes: bytes, broker: str = None) -> str:
        """El import por las puertas reales (`/api/imports/preview` + `/confirm`)."""
        broker = broker or self.BROKER
        r = self.client.post(
            "/api/imports/preview",
            files=[("files", ("x.csv", io.BytesIO(csv_bytes), "text/csv"))],
            data={"format": "rendi_generic", "broker": broker})
        self.assertEqual(r.status_code, 200, r.text)
        sid = r.json()["session_id"]
        r = self.client.post("/api/imports/confirm", json={"session_id": sid})
        self.assertEqual(r.status_code, 200, r.text)
        return sid

    def _cuenta(self):
        self._import(_csv(
            "2025-11-05,DEPOSITO,IBKR,,,,100000,,,0,USD,",
            "2025-12-02,DEPOSITO,IBKR,,,,5000,,,0,USD,",
            "2025-12-03,COMPRA,IBKR,AAPL,10,150,1500,,,0,USD,",
            "2026-01-10,DIVIDENDO,IBKR,AAPL,,,30,,,0,USD,",
            "2026-02-20,DEPOSITO,IBKR,,,,2000,,,0,USD,",
        ))
        if self.BASELINE:
            self._declarar_baseline(self.BASELINE)
        self._fotos_del_cron(_aportado(True, self.BASELINE))

    def _declarar_baseline(self, monto: float):
        """Lo que hace la persona en /mensual: edita la PRIMERA fila (la del broker
        y la total) y escribe cuánto tenía antes de empezar. PUT /api/monthly."""
        for b in (self.BROKER, "global"):
            fila = dict(self.conn.execute(
                "SELECT * FROM monthly_entries WHERE user_id=? AND broker=? "
                "ORDER BY year, month LIMIT 1", (self.uid, b)).fetchone())
            cuerpo = {k: fila[k] for k in ("year", "month", "broker", "deposits",
                                           "withdrawals", "pnl_realized",
                                           "pnl_unrealized")}
            cuerpo["capital_inicio"] = monto
            cuerpo["capital_final"] = (monto + fila["deposits"] - fila["withdrawals"]
                                       + fila["pnl_realized"])
            r = self.client.put(f"/api/monthly/{fila['id']}", json=cuerpo)
            self.assertEqual(r.status_code, 200, r.text)

    def _fotos_del_cron(self, aportado_del_dia: dict):
        """Las fotos de cada noche, con el UPSERT de `snapshots_job`."""
        for d, nd in aportado_del_dia.items():
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

    def _tx(self, op_type: str, fecha: str) -> int:
        r = self.conn.execute(
            "SELECT n.id FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id "
            "WHERE b.user_id=? AND n.operation_type=? AND n.date=? AND n.excluded_at IS NULL",
            (self.uid, op_type, fecha)).fetchone()
        self.assertIsNotNone(r, f"no encontré el {op_type} del {fecha}")
        return r["id"]

    def _borrar_el_deposito_de_noviembre(self):
        r = self.client.delete(f"/api/movements/tx-{self._tx('DEPOSIT', '2025-11-05')}")
        self.assertEqual(r.status_code, 200, r.text)

    # ── lo que se mide ───────────────────────────────────────────────────────
    def _contabilidad(self) -> dict:
        """Lo que reciben el Dashboard y /mensual (`GET /api/monthly`) y lo que
        leen los cálculos del servidor sobre esa misma tabla."""
        r = self.client.get("/api/monthly")
        self.assertEqual(r.status_code, 200, r.text)
        filas = sorted(r.json(), key=lambda f: (f["year"], f["month"]))
        out = {}
        for b in (self.BROKER, "global"):
            fb = [f for f in filas if f["broker"] == b]
            out[f"baseline {b}"] = round(fb[0]["capital_inicio"], 2) if fb else None
            out[f"aportado {b}"] = round(
                (fb[0]["capital_inicio"] if fb else 0)
                + sum(f["deposits"] - f["withdrawals"] for f in fb), 2)
        out["compute_net_deposited_db"] = round(
            compute_net_deposited_db(self.conn, self.uid), 2)
        canon = twr.netdep_canonico(self.conn, self.uid)
        out["canónico 2026-02-28"] = round(canon("2026-02-28"), 2) if canon else None
        out["canónico 2025-11-30"] = round(canon("2025-11-30"), 2) if canon else None
        return out

    def _contabilidad_esperada(self, con_noviembre: bool) -> dict:
        b = self.BASELINE
        nov = 100000.0 if con_noviembre else 0.0
        return {f"baseline {self.BROKER}": b, f"aportado {self.BROKER}": b + nov + 7000,
                "baseline global": b, "aportado global": b + nov + 7000,
                "compute_net_deposited_db": b + nov + 7000,
                "canónico 2026-02-28": b + nov + 7000,
                "canónico 2025-11-30": b + nov}

    def _fotos(self) -> dict:
        """El aportado de cada foto del cron, como lo sirve `GET /api/snapshots`."""
        r = self.client.get("/api/snapshots", params={"days": 3650})
        self.assertEqual(r.status_code, 200, r.text)
        return {p["date"]: float(p["net_deposited"]) for p in r.json() if p["date"] in DIAS}

    def _assert_fotos(self, esperado: dict, cuando: str):
        servido = self._fotos()
        mal = {d: (esperado[d], servido.get(d)) for d in esperado
               if servido.get(d) is None or abs(servido[d] - esperado[d]) > 0.005}
        self.assertEqual(mal, {}, f"{cuando}: {len(mal)} fotos con el aportado mal "
                                  "(fecha: (esperado, servido))")


class BorrarElPrimerDeposito(_Base):

    def setUp(self):
        super().setUp()
        self._cuenta()
        # Control: ANTES de borrar, la contabilidad y las fotos dicen lo que se cargó.
        self.assertEqual(self._contabilidad(), self._contabilidad_esperada(True))
        self._assert_fotos(_aportado(True, self.BASELINE), "antes de borrar")

    def test_la_contabilidad_baja_lo_aportado(self):
        self._borrar_el_deposito_de_noviembre()
        self.assertEqual(self._contabilidad(), self._contabilidad_esperada(False))

    def test_las_fotos_bajan_lo_aportado_desde_su_dia(self):
        self._borrar_el_deposito_de_noviembre()
        self._assert_fotos(_aportado(False, self.BASELINE),
                           "después de borrar el primer depósito")

    def test_el_boton_del_admin_no_encuentra_nada_que_corregir(self):
        """Si el borrado dejó la contabilidad bien, el botón de reparación del admin
        (que re-estampa desde la contabilidad) coincide foto por foto."""
        self._borrar_el_deposito_de_noviembre()
        main.app.dependency_overrides[main.get_admin_user] = lambda: self.uid
        try:
            r = self.client.post("/api/admin/recompute-snapshots-netdep")
        finally:
            main.app.dependency_overrides.pop(main.get_admin_user, None)
        self.assertEqual(r.status_code, 200, r.text)
        self._assert_fotos(_aportado(False, self.BASELINE), "después del botón del admin")

    def test_la_foto_del_cron_de_la_noche_siguiente(self):
        """El cron estampa con `compute_net_deposited` sobre las filas de hoy."""
        self._borrar_el_deposito_de_noviembre()
        with mock.patch.object(snapshots_job, "fetch_prices_for_symbols",
                               side_effect=lambda syms, cy: {s: 150.0 for s in syms}):
            with self.conn:
                res = snapshots_job.take_snapshot_for_user(
                    self.conn, self.uid, 1200, {}, "2026-03-01")
        self.assertTrue(res.get("ok"), f"el cron no escribió: {res}")
        nd = self.conn.execute(
            "SELECT net_deposited FROM snapshots WHERE user_id=? AND date='2026-03-01'",
            (self.uid,)).fetchone()["net_deposited"]
        self.assertAlmostEqual(nd, self.BASELINE + 7000, places=2)

    def test_reportes_no_arranca_diciembre_con_la_plata_borrada(self):
        """Reportes (mes/año/día/semana sin cierre medido) arranca del capital de la
        cadena al empezar el mes: diciembre no puede empezar con 100.000 que ya no
        existen."""
        self._borrar_el_deposito_de_noviembre()
        self.assertAlmostEqual(builder._capital_al_arrancar_el_mes(
            self.conn, self.uid, 2025, 12), self.BASELINE, places=2)

    def test_cargar_el_deposito_correcto_lo_devuelve(self):
        """El camino inverso: la persona borró el depósito mal cargado e importa el
        bueno (otro día de noviembre; reimportar la MISMA fila no resucita lo
        borrado, a propósito). La cuenta queda como al principio: el capital
        inicial no se suma dos veces."""
        self._borrar_el_deposito_de_noviembre()
        self._import(_csv("2025-11-07,DEPOSITO,IBKR,,,,100000,,,0,USD,"))
        self.assertEqual(self._contabilidad(), self._contabilidad_esperada(True))


class ConBaselineCargadoAMano(BorrarElPrimerDeposito):
    """La persona declaró en /mensual que ya tenía 20.000 antes de empezar. Eso no
    sale de ningún import y tiene que sobrevivir al borrado: lo que se va son los
    100.000 del depósito, no lo que ella escribió."""
    BASELINE = 20000.0

    @unittest.expectedFailure
    def test_cargar_el_deposito_correcto_lo_devuelve(self):
        """LÍMITE CONOCIDO, anterior a este arreglo y aparte de él. Borrado el
        depósito, el capital declarado pasa a diciembre (la primera fila que
        queda). Al importar otro depósito de noviembre se crea una fila ANTES de
        la que lo tiene, arranca en 0 (`_capital_inicio_de_fila_nueva`: lo
        estrictamente anterior, y no hay nada) y la cadena pisa el declarado. Es
        lo mismo que ya pasa con cualquier depósito o ganancia fechados antes del
        primer mes de alguien que declaró su capital: el historial importado
        reemplaza a lo declarado. Si eso se decide distinto (guardar lo declarado
        aparte de la cadena), este test pasa a verde y hay que sacarle la marca."""
        super().test_cargar_el_deposito_correcto_lo_devuelve()


class LasOtrasPuertas(_Base):
    """Las otras puertas que dejan vacío el primer mes y pasan por la misma
    limpieza de filas (`_recalc_pnl_realized_from_ops`)."""

    def test_revertir_el_import_del_primer_deposito(self):
        sid = self._import(_csv("2025-11-05,DEPOSITO,IBKR,,,,100000,,,0,USD,"))
        self._import(_csv("2025-12-02,DEPOSITO,IBKR,,,,5000,,,0,USD,",
                          "2026-02-20,DEPOSITO,IBKR,,,,2000,,,0,USD,"))
        r = self.client.post(f"/api/imports/{sid}/revert")
        self.assertEqual(r.status_code, 200, r.text)
        c = self._contabilidad()
        self.assertEqual((c["baseline global"], c["aportado global"],
                          c[f"baseline {self.BROKER}"], c[f"aportado {self.BROKER}"]),
                         (0.0, 7000.0, 0.0, 7000.0))

    def test_borrar_el_broker_que_tenia_el_primer_deposito(self):
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Cocos", "USDT"))
        self.conn.commit()
        self._import(_csv("2025-11-05,DEPOSITO,IBKR,,,,100000,,,0,USD,"))
        self._import(_csv("2025-12-02,DEPOSITO,Cocos,,,,5000,,,0,USD,",
                          "2026-02-20,DEPOSITO,Cocos,,,,2000,,,0,USD,"), broker="Cocos")
        bid = self.conn.execute("SELECT id FROM brokers WHERE user_id=? AND name=?",
                                (self.uid, self.BROKER)).fetchone()["id"]
        r = self.client.delete(f"/api/brokers/{bid}", params={"force": "true"})
        self.assertEqual(r.status_code, 200, r.text)
        c = self._contabilidad()
        self.assertEqual((c["baseline global"], c["aportado global"],
                          c["compute_net_deposited_db"]), (0.0, 7000.0, 7000.0))

    def test_borrar_un_deposito_cargado_a_mano(self):
        """Sin import: la persona cargó el primer depósito con el botón de efectivo
        (`me-`), después otro, y borra el primero."""
        for fecha, monto in (("2025-11-05", 100000), ("2025-12-02", 5000),
                             ("2026-02-20", 2000)):
            r = self.client.post("/api/cash/flow", json={
                "broker_name": self.BROKER, "direction": "deposit", "amount": monto,
                "date": fecha})
            self.assertEqual(r.status_code, 200, r.text)
        me = self.conn.execute(
            "SELECT id FROM monthly_entries WHERE user_id=? AND broker=? AND year=2025 "
            "AND month=11", (self.uid, self.BROKER)).fetchone()
        r = self.client.delete(f"/api/movements/me-{me['id']}-dep")
        self.assertEqual(r.status_code, 200, r.text)
        c = self._contabilidad()
        self.assertEqual((c["baseline global"], c["aportado global"],
                          c[f"baseline {self.BROKER}"], c[f"aportado {self.BROKER}"]),
                         (0.0, 7000.0, 0.0, 7000.0))


class BorrarLaPrimeraFilaEnMensual(_Base):
    """La misma cadena, borrada a mano: en /mensual la persona borra el primer mes
    (`DELETE /api/monthly/{id}`). Borrar un mes del MEDIO siempre sacó su plata
    (la cadena engancha el siguiente con el anterior); el primero dejaba su
    `capital_final` como capital inicial del siguiente."""

    def _cargar(self, capital_inicio=0.0):
        ids = {}
        for mes, dep in ((11, 100000.0), (12, 5000.0)):
            r = self.client.post("/api/monthly", json={
                "year": 2025, "month": mes, "broker": self.BROKER, "deposits": dep,
                "capital_inicio": capital_inicio if mes == 11 else 0,
                "capital_final": 0})
            self.assertEqual(r.status_code, 200, r.text)
            ids[mes] = r.json()["id"]
        return ids

    def test_borrar_el_primer_mes_saca_su_plata(self):
        ids = self._cargar()
        r = self.client.delete(f"/api/monthly/{ids[11]}")
        self.assertEqual(r.status_code, 200, r.text)
        c = self._contabilidad()
        self.assertEqual((c[f"baseline {self.BROKER}"], c[f"aportado {self.BROKER}"]),
                         (0.0, 5000.0))

    def test_lo_declarado_se_queda(self):
        ids = self._cargar(capital_inicio=20000.0)
        r = self.client.delete(f"/api/monthly/{ids[11]}")
        self.assertEqual(r.status_code, 200, r.text)
        c = self._contabilidad()
        self.assertEqual((c[f"baseline {self.BROKER}"], c[f"aportado {self.BROKER}"]),
                         (20000.0, 25000.0))

    def test_borrar_un_mes_del_medio_no_cambia(self):
        """Control: el comportamiento que ya era correcto sigue igual."""
        ids = self._cargar(capital_inicio=20000.0)
        r = self.client.post("/api/monthly", json={
            "year": 2026, "month": 1, "broker": self.BROKER, "deposits": 700,
            "capital_inicio": 0, "capital_final": 0})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.delete(f"/api/monthly/{ids[12]}")
        self.assertEqual(r.status_code, 200, r.text)
        c = self._contabilidad()
        self.assertEqual((c[f"baseline {self.BROKER}"], c[f"aportado {self.BROKER}"]),
                         (20000.0, 120700.0))


class UnaGananciaAntesDelPrimerMes(_Base):
    """El mismo síntoma por la puerta de al lado: una fila NUEVA que queda primera.

    `_update_monthly_pnl_realized` creaba la fila de un mes sin fila con el
    `capital_final` de la ÚLTIMA fila del broker —un mes POSTERIOR—. Si ese mes
    quedaba primero (un dividendo o una venta fechados antes de todo lo cargado),
    el capital de la cuenta entera pasaba a ser capital inicial: lo aportado se
    contaba dos veces. `_update_monthly_flow` ya miraba sólo hacia atrás (review
    cash-chat) y la otra copia no se había enterado."""

    def _con_febrero(self):
        self._import(_csv("2026-02-05,DEPOSITO,IBKR,,,,1000,,,0,USD,",
                          "2026-02-06,COMPRA,IBKR,AAPL,5,100,500,,,0,USD,"))

    def _assert_aportado(self, esperado):
        c = self._contabilidad()
        self.assertEqual((c["baseline global"], c["aportado global"],
                          c[f"baseline {self.BROKER}"], c[f"aportado {self.BROKER}"],
                          c["compute_net_deposited_db"]),
                         (0.0, esperado, 0.0, esperado, esperado))

    def test_un_dividendo_de_un_mes_anterior(self):
        self._con_febrero()
        self._import(_csv("2026-01-10,DIVIDENDO,IBKR,AAPL,,,40,,,0,USD,"))
        self._assert_aportado(1000.0)

    def test_una_venta_con_ganancia_de_un_mes_anterior(self):
        self._con_febrero()
        self._import(_csv("2026-01-10,COMPRA,IBKR,MSFT,1,100,100,,,0,USD,",
                          "2026-01-12,VENTA,IBKR,MSFT,1,130,130,,,0,USD,"))
        self._assert_aportado(1000.0)

    def test_una_compraventa_sin_ganancia_de_un_mes_anterior(self):
        """El mes nuevo queda vacío y la limpieza lo borra: igual no puede dejar su
        arranque (el de febrero) como capital inicial."""
        self._con_febrero()
        self._import(_csv("2026-01-10,COMPRA,IBKR,MSFT,1,100,100,,,0,USD,",
                          "2026-01-12,VENTA,IBKR,MSFT,1,100,100,,,0,USD,"))
        self._assert_aportado(1000.0)


class ElBaselineSoloSigueVivo(_Base):
    """La limpieza borra también una primera fila que SÓLO tiene el baseline (sin
    movimientos). Ese baseline tiene que seguir en la fila que queda primera —
    como antes del arreglo— y no perderse."""

    def _declarado_en_febrero(self):
        for b in (self.BROKER, "global"):
            r = self.client.post("/api/monthly", json={
                "year": 2026, "month": 2, "broker": b, "capital_inicio": 50000,
                "deposits": 1000, "capital_final": 51000})
            self.assertEqual(r.status_code, 200, r.text)

    def _assert_declarado(self, baseline, aportado):
        c = self._contabilidad()
        self.assertEqual((c["baseline global"], c["aportado global"],
                          c[f"baseline {self.BROKER}"], c[f"aportado {self.BROKER}"]),
                         (baseline, aportado, baseline, aportado))

    def test_un_mes_vacio_que_aparece_antes_no_lo_pisa(self):
        """La persona declaró 50.000 en febrero. Un import trae de enero sólo una
        compraventa sin ganancia: el recálculo crea enero (hay operaciones), queda
        vacío y la limpieza lo borra en la misma pasada. Febrero no estaba
        enganchado a ese enero —su arranque es el declarado—, así que sigue en
        50.000. Antes del arreglo quedaba en 51.000 (la fila de la venta heredaba
        el cierre de febrero)."""
        self._declarado_en_febrero()
        self._import(_csv("2026-01-10,COMPRA,IBKR,MSFT,1,100,100,,,0,USD,",
                          "2026-01-12,VENTA,IBKR,MSFT,1,100,100,,,0,USD,"))
        self._assert_declarado(50000.0, 51000.0)

    @unittest.expectedFailure
    def test_historial_anterior_al_mes_declarado(self):
        """LÍMITE CONOCIDO (el mismo de `ConBaselineCargadoAMano`): un dividendo de
        enero crea una fila ANTES de la declarada, arranca en 0 y la cadena pisa lo
        declarado — igual que ya pasaba con un depósito de enero. La regla hoy es
        "el historial importado reemplaza a lo declarado", y es la misma para
        flujos y ganancias (antes, con la ganancia, la cuenta entera posterior se
        sumaba como capital inicial). Que lo declarado sobreviva necesita guardarlo
        aparte de la cadena y decidir qué pasa con el historial viejo que lo
        compone: es una decisión de producto, no de este arreglo."""
        self._declarado_en_febrero()
        self._import(_csv("2026-01-10,DIVIDENDO,IBKR,AAPL,,,40,,,0,USD,"))
        self._assert_declarado(50000.0, 51000.0)

    def test_baseline_en_un_mes_sin_movimientos(self):
        r = self.client.post("/api/monthly", json={
            "year": 2025, "month": 10, "broker": self.BROKER, "capital_inicio": 30000,
            "capital_final": 30000})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/monthly", json={
            "year": 2025, "month": 10, "broker": "global", "capital_inicio": 30000,
            "capital_final": 30000})
        self.assertEqual(r.status_code, 200, r.text)
        self._import(_csv("2025-12-02,DEPOSITO,IBKR,,,,5000,,,0,USD,",
                          "2026-02-20,DEPOSITO,IBKR,,,,2000,,,0,USD,"))
        c = self._contabilidad()
        self.assertEqual((c["baseline global"], c["aportado global"],
                          c[f"baseline {self.BROKER}"], c[f"aportado {self.BROKER}"]),
                         (30000.0, 37000.0, 30000.0, 37000.0))


if __name__ == "__main__":
    unittest.main()
