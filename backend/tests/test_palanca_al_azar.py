"""La palanca «mueve efectivo» al EDITAR una operación, con secuencias al azar.

Las pruebas armadas a mano (`test_operaciones_con_receta.py`,
`test_operacion_mueve_efectivo.py`) fijan los casos que se conocen. Ésta mezcla:
arma cuentas, crea operaciones por las puertas reales (formulario, botón de
cupón/amortización, botón Vender), a algunas les borra o les rompe la receta
(= filas de antes del 2026-08-06) o las vincula a un import, y después edita y
borra al azar. Todo por HTTP, como la app.

En cada edición compara, caja por caja, lo que se movió contra lo que TENÍA que
moverse:

  · la palanca sólo vale para las filas cuya receta dice que salieron del
    formulario; a las demás (sin receta, receta rota, importadas, puertas que
    mueven plata solas) el pedido se les ignora: no se mueve nada, la receta no
    cambia, el formulario no la ofrece;
  · una fila sin receta sigue sin poder borrarse, antes y después de editarla;
  · en las del formulario se mueve exactamente la diferencia entre lo que
    tenían acreditado y lo que queda acreditado.

Medido el 2026-10-10 contra lo que estaba publicado (regla vieja: «se ofrece
salvo a las puertas conocidas»): 208 fallas en 120 escenarios — entre ellas una
amortización de $428.775 en un broker en pesos que acreditaba $606.716.625. Con
«sin receta no hay palanca»: 0 en 400. `test_el_instrumento_ve_la_regla_vieja`
deja fijo que esta prueba VE ese error, para que un verde signifique algo.
"""
import json
import os
import random
import sys
import tempfile
import unittest
import uuid
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from fastapi.testclient import TestClient

import main

CAMPOS = ("date", "broker", "asset", "op_type", "entry_price", "exit_price", "quantity",
          "pnl_usd", "pnl_pct", "commissions", "currency", "fx_to_usd")
TIPOS = ("LONG", "SHORT", "Futuros", "Cupón", "Amortización", "Venta", "Dividendo", "", "Scalp")
FECHAS = ("2026-03-10", "2026-05-22", "2026-07-09", "2026-08-01")
BROKERS = (("IBKR", "USD"), ("Cocos", "ARS"))
DEL_FORMULARIO = ("manual_form", "manual_futures")
# Cómo queda una fila vieja o dañada. Todas tienen que leerse como "sin receta".
RECETAS_ROTAS = (None, None, None, "", "{}", "{esto no es una receta", '{"cash": 50}',
                 '{"src": ""}', '{"src": null}')


class Sonda:
    """Corre escenarios al azar y junta las fallas (no corta en la primera)."""

    def __init__(self, semilla):
        self.rng = random.Random(semilla)
        self.http = TestClient(main.app)
        self.fallas = []
        self.cuenta = {"ediciones": 0, "ediciones_de_filas_sin_receta": 0,
                       "pidieron_la_palanca_sin_ser_del_formulario": 0,
                       "ediciones_del_formulario_que_movieron_plata": 0,
                       "borrados_frenados": 0}

    # ── lectura directa (lo que se mide) ──
    def _cajas(self):
        c = main.get_db()
        r = {b: 0.0 for b, _ in BROKERS}
        for f in c.execute("SELECT broker, COALESCE(SUM(invested),0) s FROM positions "
                           "WHERE user_id=? AND is_cash=1 GROUP BY broker", (self.uid,)):
            r[f["broker"]] = round(float(f["s"]), 4)
        c.close()
        return r

    def _fila(self, oid):
        c = main.get_db()
        r = c.execute("SELECT * FROM operations WHERE id=? AND user_id=?", (oid, self.uid)).fetchone()
        c.close()
        return dict(r) if r else None

    def _ids(self):
        c = main.get_db()
        r = [f["id"] for f in c.execute("SELECT id FROM operations WHERE user_id=? ORDER BY id",
                                        (self.uid,))]
        c.close()
        return r

    def _sql(self, consulta, args):
        c = main.get_db()
        c.execute(consulta, args)
        c.commit()
        c.close()

    @staticmethod
    def _receta(fila):
        try:
            m = json.loads(fila["undo_meta_json"] or "{}") or {}
            return m if isinstance(m, dict) else {}
        except (ValueError, TypeError):
            return {}

    def _clase(self, fila):
        c = main.get_db()
        importada = c.execute("SELECT 1 FROM import_op_links WHERE operation_id=? LIMIT 1",
                              (fila["id"],)).fetchone() is not None
        c.close()
        if importada:
            return "importada"
        src = self._receta(fila).get("src")
        if not src:
            return "sin receta"
        return "del formulario" if src in DEL_FORMULARIO else "de otra puerta"

    def _en_moneda_del_broker(self, broker, usd, fecha):
        """La conversión no es lo que se audita: se usa la del sistema."""
        if not usd:
            return 0.0
        c = main.get_db()
        v = main._pnl_en_moneda_del_broker(c, self.uid, broker, float(usd), fecha)
        c.close()
        return float(v)

    def _la_ofrece(self, oid):
        r = self.http.get("/api/operations")
        assert r.status_code == 200, r.text
        return [o for o in r.json() if o["id"] == oid][0]["mueve_efectivo_editable"]

    def _falla(self, texto):
        self.fallas.append(f"escenario {self.esc} paso {self.paso}: {texto}")

    # ── las puertas ──
    def _ok(self, r):
        assert r.status_code == 200, r.text

    def crear_en_el_formulario(self):
        rng = self.rng
        cuerpo = {"date": rng.choice(FECHAS), "broker": rng.choice(BROKERS)[0], "asset": "KO",
                  "op_type": rng.choice(TIPOS),
                  "pnl_usd": rng.choice((None, 0, 50.0, -120.5, 300.0, 7.25))}
        modo = rng.choice(("nada", "si", "no", "kind"))
        if modo == "si":
            cuerpo["mueve_efectivo"] = True
        elif modo == "no":
            cuerpo["mueve_efectivo"] = False
        elif modo == "kind":
            cuerpo["kind"] = "futures"
        if rng.random() < 0.3:
            cuerpo.update(entry_price=100, exit_price=150, quantity=rng.choice((1, 10, 12.5)))
        self._ok(self.http.post("/api/operations", json=cuerpo))

    def cobrar_del_bono(self):
        rng = self.rng
        broker, moneda = rng.choice(BROKERS)
        self._ok(self.http.post("/api/bonds/cashflow", json={
            "broker": broker, "asset": "AL30",
            "flow_type": rng.choice(("coupon", "amortization")),
            "amount": rng.choice((100.0, 26.31, 4287.75)) * (1 if moneda == "USD" else 100),
            "date": rng.choice(FECHAS), "commissions": 0, "decrement_quantity": False,
            "notes": rng.choice((None, "Estimado por cronograma — ajustá monto si difiere"))}))

    def vender_con_el_boton(self):
        rng = self.rng
        self.activos += 1
        activo = f"T{self.esc}X{self.activos}"
        self._ok(self.http.post("/api/positions", json={
            "broker": "IBKR", "asset": activo, "quantity": 10, "buy_price": 100,
            "invested": 1000, "entry_date": "2026-01-15"}))
        self._ok(self.http.post("/api/positions/sell", json={
            "broker": "IBKR", "asset": activo, "quantity": rng.choice((4, 10)),
            "exit_price": rng.choice((80, 150)), "date": "2026-06-10"}))

    def envejecer_o_romper_la_receta(self):
        ids = self._ids()
        if ids:
            self._sql("UPDATE operations SET undo_meta_json=? WHERE id=?",
                      (self.rng.choice(RECETAS_ROTAS), self.rng.choice(ids)))

    def vincular_a_un_import(self):
        ids = self._ids()
        if not ids:
            return
        lote = uuid.uuid4().hex
        self._sql("INSERT INTO import_batches (id, user_id, broker, parser_format, file_name, "
                  "file_hash, status) VALUES (?,?,?,?,?,?,?)",
                  (lote, self.uid, "IBKR", "test", "x.csv", uuid.uuid4().hex, "confirmed"))
        self._sql("INSERT INTO import_op_links (batch_id, operation_id) VALUES (?,?)",
                  (lote, self.rng.choice(ids)))

    def editar(self):
        rng = self.rng
        ids = self._ids()
        if not ids:
            return
        oid = rng.choice(ids)
        antes = self._fila(oid)
        clase = self._clase(antes)
        receta = self._receta(antes)
        cuerpo = {k: antes[k] for k in CAMPOS}
        cuerpo["commissions"] = cuerpo["commissions"] or 0
        if rng.random() < 0.5:
            cuerpo["pnl_usd"] = rng.choice((None, 0, 80.0, -40.0, 999.99))
        if rng.random() < 0.25:
            cuerpo["broker"] = rng.choice(BROKERS)[0]
        if rng.random() < 0.3:
            cuerpo["op_type"] = rng.choice(TIPOS)
        if rng.random() < 0.2:
            cuerpo["date"] = rng.choice(FECHAS)
        if cuerpo["broker"] != antes["broker"]:      # la moneda la resuelve el servidor
            cuerpo["currency"] = cuerpo["fx_to_usd"] = None
        modo = rng.choice(("nada", "si", "si", "no", "kind", "kind_null"))
        pedido = {"si": True, "no": False, "kind": True, "kind_null": False}.get(modo)
        if modo in ("si", "no"):
            cuerpo["mueve_efectivo"] = pedido
        elif modo == "kind":
            cuerpo["kind"] = "futures"
        elif modo == "kind_null":
            cuerpo["kind"] = None

        cajas_antes = self._cajas()
        r = self.http.put(f"/api/operations/{oid}", json=cuerpo)
        cajas_despues = self._cajas()
        despues = self._fila(oid)
        movido = {b: round(cajas_despues[b] - cajas_antes[b], 4) for b in cajas_antes}
        se_movio = any(abs(v) > 1e-6 for v in movido.values())
        self.cuenta["ediciones"] += 1
        self.cuenta["ediciones_de_filas_sin_receta"] += clase == "sin receta"
        que = f"{clase} (receta={antes['undo_meta_json']!r}, tipo={antes['op_type']!r}, pedido={modo})"

        if r.status_code != 200:
            # El único rechazo esperado es el del tipo que puso el sistema (400).
            if r.status_code != 400:
                self._falla(f"{que}: el PUT dio {r.status_code}")
            if se_movio or despues != antes:
                self._falla(f"{que}: rechazado con {r.status_code} pero cambió algo ({movido})")
            return

        acepta = clase == "del formulario"
        if pedido is True and not acepta:
            self.cuenta["pidieron_la_palanca_sin_ser_del_formulario"] += 1
        pedido_que_vale = pedido if acepta else None
        # Si YA movía plata, la edición la sigue por la diferencia (eso no cambió).
        movia = bool(receta["cash_on"]) if "cash_on" in receta else receta.get("src") == "manual_futures"
        mueve = movia if pedido_que_vale is None else pedido_que_vale
        broker_antes = receta.get("cash_broker") or antes["broker"]
        if movia:
            habia = (float(receta["cash_native"] or 0) if receta.get("cash_native") is not None
                     else self._en_moneda_del_broker(broker_antes, receta.get("cash") or 0,
                                                     antes["date"]))
        else:
            habia = 0.0
        queda = (self._en_moneda_del_broker(cuerpo["broker"], cuerpo["pnl_usd"] or 0, cuerpo["date"])
                 if mueve else 0.0)
        debia = {b: 0.0 for b in cajas_antes}
        if movia or mueve:
            if broker_antes != cuerpo["broker"]:
                debia[broker_antes] -= habia
                debia[cuerpo["broker"]] += queda
            else:
                debia[cuerpo["broker"]] += queda - habia
        for b in debia:
            if abs(debia[b] - movido[b]) > 0.01:
                self._falla(f"{que}: en {b} se movió {movido[b]} y debía {round(debia[b], 4)}")
        if se_movio and acepta:
            self.cuenta["ediciones_del_formulario_que_movieron_plata"] += 1
        if self._la_ofrece(oid) is not acepta:
            self._falla(f"{que}: el formulario {'NO ' if acepta else ''}ofrece la palanca")
        if not acepta and not movia and despues["undo_meta_json"] != antes["undo_meta_json"]:
            self._falla(f"{que}: la receta pasó a {despues['undo_meta_json']!r}")

    def borrar_una_sin_receta(self):
        ids = self._ids()
        if not ids:
            return
        oid = self.rng.choice(ids)
        antes = self._fila(oid)
        if self._clase(antes) != "sin receta":
            return                       # los otros borrados tienen sus propias pruebas
        cajas_antes = self._cajas()
        r = self.http.delete(f"/api/operations/{oid}")
        if r.status_code != 400:
            self._falla(f"una fila sin receta ({antes['undo_meta_json']!r}) se pudo borrar: {r.status_code}")
        if self._cajas() != cajas_antes or self._fila(oid) != antes:
            self._falla("el borrado frenado cambió algo")
        self.cuenta["borrados_frenados"] += 1

    # ── un escenario ──
    def escenario(self, esc):
        self.esc, self.paso, self.activos = esc, -1, 0
        c = main.get_db()
        self.uid = c.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
            (f"azar-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
        for broker, moneda in BROKERS:
            c.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                      (self.uid, broker, moneda))
            c.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested) "
                      "VALUES (?,?,?,1,?)",
                      (self.uid, broker, "ARS" if moneda == "ARS" else "USD", 50_000_000.0))
        c.commit()
        c.close()
        uid = self.uid
        main.app.dependency_overrides[main.get_effective_user] = lambda: uid
        bolsa = ([self.crear_en_el_formulario] * 5 + [self.cobrar_del_bono] * 3
                 + [self.vender_con_el_boton] * 2 + [self.envejecer_o_romper_la_receta] * 4
                 + [self.vincular_a_un_import] + [self.editar] * 12
                 + [self.borrar_una_sin_receta] * 2)
        for accion in (self.crear_en_el_formulario, self.cobrar_del_bono, self.vender_con_el_boton):
            accion()
        for self.paso in range(self.rng.randint(10, 22)):
            self.rng.choice(bolsa)()

    def correr(self, escenarios):
        try:
            for esc in range(escenarios):
                self.escenario(esc)
        finally:
            main.app.dependency_overrides.pop(main.get_effective_user, None)
        return self


class LaPalancaAlAzar(unittest.TestCase):
    ESCENARIOS = 40
    SEMILLA = 20261010

    def setUp(self):
        # La reconstrucción a mercado en otro hilo no es lo que se mide.
        for nombre in ("_reconstruir_mtm_post_import", "_reconstruir_en_fila"):
            p = mock.patch.object(main, nombre, side_effect=lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)

    def test_cuarenta_cuentas_al_azar(self):
        sonda = Sonda(self.SEMILLA).correr(self.ESCENARIOS)
        self.assertEqual(sonda.fallas, [], "\n".join(sonda.fallas[:15]))
        # Que el verde no sea por no haber probado nada.
        self.assertGreater(sonda.cuenta["ediciones"], 200, sonda.cuenta)
        self.assertGreater(sonda.cuenta["ediciones_de_filas_sin_receta"], 15, sonda.cuenta)
        self.assertGreater(sonda.cuenta["pidieron_la_palanca_sin_ser_del_formulario"], 50, sonda.cuenta)
        self.assertGreater(sonda.cuenta["ediciones_del_formulario_que_movieron_plata"], 20, sonda.cuenta)
        self.assertGreater(sonda.cuenta["borrados_frenados"], 3, sonda.cuenta)

    def test_el_instrumento_ve_la_regla_vieja(self):
        """Control: con la regla de antes (se ofrece salvo a las puertas conocidas)
        esta misma prueba tiene que encontrar plata movida y recetas regaladas."""
        def regla_vieja(importada, meta):
            return (not importada) and (meta or {}).get("src") not in main._SRC_CON_EFECTIVO_PROPIO
        with mock.patch.object(main, "_acepta_interruptor_de_efectivo", regla_vieja):
            sonda = Sonda(self.SEMILLA).correr(self.ESCENARIOS)
        texto = "\n".join(sonda.fallas)
        self.assertIn("ofrece la palanca", texto)
        self.assertIn("la receta pasó a", texto)
        self.assertRegex(texto, r"se movió [\d.]+ y debía 0\.0")


if __name__ == "__main__":
    unittest.main()
