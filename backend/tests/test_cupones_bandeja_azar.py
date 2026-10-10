"""Cobros de bonos AL AZAR: confirmar, borrar, deshacer e importar mezclados.

Las pruebas armadas a mano (test_cupones_bandeja.py) cubren los caminos que uno
se imagina. Ésta tira secuencias al azar de las cuatro puertas que tocan un cobro
de bono —confirmar desde la bandeja (/api/bonds/cashflow/pago), borrar desde
Movimientos, deshacer el borrado, importar el archivo del broker con el mismo
pago— sobre cuentas al azar (bono importado o cargado a mano, en la cuenta en
pesos con cobro en dólares, o en una cuenta en dólares) y después de CADA paso
verifica que la contabilidad cierre:

  · nada devuelve 500;
  · un pago no queda anotado dos veces (a mano + importado, o dos confirmados);
  · el efectivo de cada cuenta y los nominales de cada bono son los que dice EL
    LIBRO DE LA PRUEBA: una cuenta aparte, que se lleva con lo que la prueba mandó
    y con las reglas escritas acá — no con lo que el programa dejó anotado en sus
    filas. (Hasta 2026-10-10 se comparaba contra el `cash` y el `qty_decremented`
    que el propio cobro guardaba: si el programa anotaba mal, la prueba le creía.)
  · la ganancia realizada del mes = la suma de las operaciones, SIN que la prueba
    llame al recálculo (cada puerta tiene que haber recalculado);
  · en cada cobro a mano, ganancia = cobrado − costo, y el costo es de verdad
    (0,60 por nominal en los lotes de esta prueba);
  · borrar y deshacer deja todo como estaba;
  · los nominales originales que ve la bandeja no cambian.

Tres cuentas posibles: AL30 (el barrido de amortizaciones lleva sus nominales si
es importado), GD35 (no amortiza todavía) y GD46 importado (el servidor no tiene
su cronograma: los nominales los baja el cobro, y el archivo trae la
amortización como una VENTA, al estilo Balanz).

RENDI_AZAR=500 corre 500 escenarios (por defecto 40, para que la suite no tarde).
"""
import io
import json
import os
import random
import unittest

from fastapi.testclient import TestClient

import main
import realized_pnl

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"
N = int(os.environ.get("RENDI_AZAR", "40"))
SEMILLA = int(os.environ.get("RENDI_AZAR_SEMILLA", "20261009"))

# Pagos del cronograma (cupón, amortización) por 10.000 nominales originales.
PAGOS = {
    "AL30": {"2025-07-09": (33.0, 800.0), "2026-01-09": (30.0, 800.0), "2026-07-09": (27.0, 800.0)},
    "GD35": {"2025-07-09": (75.0, 0.0), "2026-01-09": (75.0, 0.0), "2026-07-09": (75.0, 0.0)},
    "GD46": {"2025-07-09": (201.0, 227.27), "2026-01-09": (197.0, 227.27), "2026-07-09": (192.0, 227.27)},
}
BONOS = tuple(PAGOS)
# Cuánto pueden diferir lo anotado y el archivo para ser el mismo cobro (la regla
# del importador, escrita acá de nuevo a propósito: es lo que se prueba).
TOLERANCIA = 0.25


def _csv(*rows):
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


class CobrosDeBonosAlAzarTest(unittest.TestCase):
    conteo = {}          # acción → [ejecutadas, rechazadas o salteadas]

    def _limpiar(self):
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "bond_cashflow_skips", "deleted_ops_journal",
                  "dividendos_reemplazados", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()

    def setUp(self):
        self.conn = main.get_db()

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        self.conn.close()

    def _cuenta(self, que, hizo):
        self.conteo.setdefault(que, [0, 0])[0 if hizo else 1] += 1
        self.traza[-1] += " → " + ("hecho" if hizo else "no")

    # ── la cuenta ────────────────────────────────────────────────────────────
    def _armar(self, rng):
        self._limpiar()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("azar_bonos@rendi.test", "x")).lastrowid
        for name, ccy, parent in (("Cocos", "ARS", None), ("Cocos · USD", "USDT", "Cocos"),
                                  ("IOL", "USDT", None), ("Balanz", "USDT", None)):
            pid = None
            if parent:
                pid = self.conn.execute("SELECT id FROM brokers WHERE user_id=? AND name=?",
                                        (self.uid, parent)).fetchone()["id"]
            self.conn.execute("INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
                              "VALUES (?,?,?,?)", (self.uid, name, ccy, pid))
        # El dólar del día de la compra: de ahí sale el costo en dólares de un lote
        # en pesos (0,60 por nominal en todos los lotes de esta prueba).
        self.conn.execute("DELETE FROM fx_rates_daily WHERE date='2024-01-15'")
        self.conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
                          "VALUES ('2024-01-15', 1000, 1000, 'manual')")
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.c = TestClient(main.app)
        # asset → (cuenta del bono, cuenta del cobro, ¿los nominales los baja el cobro?)
        self.bonos = {}
        if rng.random() < 0.5:
            self._importar("Cocos", "2024-01-02,DEPOSITO,Cocos,,,,20000000,,,0,ARS,",
                           "2024-01-15,COMPRA,Cocos,AL30,10000,600,6000000,,,0,ARS,")
            self.bonos["AL30"] = ("Cocos", "Cocos · USD", False)      # los lleva el barrido
        else:
            # Cargado a mano: ya registró las amortizaciones hasta enero 2025 (vivo 88 %).
            self.conn.execute(
                """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                       invested, tc_compra, entry_date, commissions, asset_type, currency)
                   VALUES (?, 'Cocos', 'AL30', 0, 600, 8800, 5280000, 1000, '2024-01-15', 0, 'BOND', 'ARS')""",
                (self.uid,))
            self.conn.commit()
            self.bonos["AL30"] = ("Cocos", "Cocos · USD", True)
        if rng.random() < 0.6:
            self._importar("IOL", "2024-01-02,DEPOSITO,IOL,,,,10000,,,0,USD,",
                           "2024-01-15,COMPRA,IOL,GD35,10000,0.5,5000,,,0,USD,")
            self.bonos["GD35"] = ("IOL", "IOL", False)                # no amortiza todavía
        if rng.random() < 0.6:
            self._importar("Balanz", "2024-01-02,DEPOSITO,Balanz,,,,10000,,,0,USD,",
                           "2024-01-15,COMPRA,Balanz,GD46,10000,0.6,6000,,,0,USD,")
            self.bonos["GD46"] = ("Balanz", "Balanz", True)           # importado SIN barrido
        # EL LIBRO DE LA PRUEBA: lo que tiene que haber, llevado aparte.
        self.caja = {}          # cuenta → lo que entró por cobros
        self.bajado = {}        # bono → nominales que le bajaron los cobros
        self.vivos = {}         # id de operación a mano → lo que la prueba mandó
        self.importado = set()  # (bono, fecha) que ya vino en un archivo

    def _importar(self, broker, *rows):
        r = self.c.post("/api/imports/preview",
                        files=[("files", ("x.csv", io.BytesIO(_csv(*rows)), "text/csv"))],
                        data={"format": "rendi_generic", "broker": broker})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.c.post("/api/imports/confirm", json={"session_id": r.json()["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)

    # ── la foto de la contabilidad ───────────────────────────────────────────
    def _foto(self):
        caja = {r["broker"]: round(float(r["invested"] or 0), 4) for r in self.conn.execute(
            "SELECT broker, invested FROM positions WHERE user_id=? AND is_cash=1", (self.uid,))}
        lotes = {r["asset"]: round(float(r["q"] or 0), 4) for r in self.conn.execute(
            "SELECT asset, SUM(quantity) q FROM positions WHERE user_id=? AND is_cash=0 "
            "GROUP BY asset", (self.uid,))}
        ops = sorted((r["date"], r["broker"], r["asset"], r["op_type"], round(float(r["quantity"] or 0), 4),
                      round(float(r["pnl_usd"] or 0), 4)) for r in self.conn.execute(
            "SELECT * FROM operations WHERE user_id=?", (self.uid,)))
        return {"caja": caja, "lotes": lotes, "ops": ops}

    def _originales(self):
        """{bono: nominales originales según /api/positions} (se suman los lotes,
        que es lo que hace la pantalla con cada grupo)."""
        out = {}
        for p in self.c.get("/api/positions").json():
            if p.get("is_cash") or p["asset"] not in PAGOS:
                continue
            v = p.get("nominal_original", p.get("nominal_al_cargar"))
            out[p["asset"]] = round(out.get(p["asset"], 0) + float(v), 4)
        return out

    def _cobros(self):
        ph = ",".join("?" * len(BONOS))
        out = []
        for r in self.conn.execute(
                f"SELECT o.* FROM operations o WHERE o.user_id=? AND o.asset IN ({ph})",
                (self.uid, *BONOS)):
            d = dict(r)
            d["meta"] = json.loads(d["undo_meta_json"] or "{}") if d.get("undo_meta_json") else {}
            d["a_mano"] = d["meta"].get("src") == "bond_cashflow"
            out.append(d)
        return out

    def _del_pago(self, asset, fecha):
        """Lo que la prueba tiene anotado a mano para ese pago: {tipo: (id, datos)}."""
        return {v["tipo"]: (k, v) for k, v in self.vivos.items()
                if v["asset"] == asset and v["fecha"] == fecha}

    # ── los invariantes ──────────────────────────────────────────────────────
    def _verificar(self, base, paso):
        cobros = self._cobros()
        # 0. Lo que hay a mano en la base es lo que la prueba cree que hay.
        self.assertEqual(sorted(o["id"] for o in cobros if o["a_mano"]), sorted(self.vivos),
                         f"{paso}: los cobros a mano no son los que la prueba mandó")
        # 1. Nada anotado dos veces: por bono y pago, o a mano o importado.
        for asset, pagos in PAGOS.items():
            for fecha in pagos:
                cerca = [o for o in cobros if o["asset"] == asset
                         and abs((_d(o["date"]) - _d(fecha)).days) <= 14]
                a_mano = {o["date"] for o in cerca if o["a_mano"]}
                importados = [o for o in cerca if not o["a_mano"]]
                self.assertFalse(a_mano and importados, f"{paso}: {asset} {fecha} a mano + importado")
                self.assertLessEqual(len(a_mano), 1, f"{paso}: {asset} {fecha} confirmado dos veces")
                tipos = [o["op_type"] for o in cerca if o["a_mano"]]
                self.assertEqual(len(tipos), len(set(tipos)), f"{paso}: {asset} {fecha} mismo tipo dos veces")
                self.assertLessEqual(len(importados), 1, f"{paso}: {asset} {fecha} importado dos veces")
        # 2. Efectivo = el de antes + lo que dice EL LIBRO DE LA PRUEBA.
        real = self._foto()
        for cuenta in set(base["caja"]) | set(self.caja) | set(real["caja"]):
            self.assertAlmostEqual(
                real["caja"].get(cuenta, 0), base["caja"].get(cuenta, 0) + self.caja.get(cuenta, 0),
                places=2, msg=f"{paso}: efectivo de {cuenta}")
        # 3. Nominales = los de antes − lo que dice el libro que bajaron los cobros.
        for asset in self.bonos:
            self.assertAlmostEqual(
                real["lotes"].get(asset, 0), base["lotes"].get(asset, 0) - self.bajado.get(asset, 0),
                places=2, msg=f"{paso}: nominales de {asset}")
        # 4. La ganancia realizada del mes cierra con las operaciones — SIN recalcular
        #    acá: cada puerta tiene que haber dejado el mes al día.
        mensual = float(self.conn.execute(
            "SELECT COALESCE(SUM(pnl_realized),0) FROM monthly_entries WHERE user_id=? AND broker='global'",
            (self.uid,)).fetchone()[0])
        ops = float(self.conn.execute(
            f"SELECT COALESCE(SUM({realized_pnl.realized_usd_sql()}),0) FROM operations "
            f"WHERE user_id=? AND pnl_usd IS NOT NULL AND {realized_pnl.no_es_conversion_sql()}",
            (self.uid,)).fetchone()[0])
        self.assertAlmostEqual(mensual, ops, places=2, msg=f"{paso}: ganancia realizada")
        # 5. Cada cobro a mano: lo cobrado es lo que la prueba mandó, y la ganancia
        #    es eso menos el costo de verdad (0,60 por nominal amortizado).
        for o in cobros:
            if not o["a_mano"]:
                continue
            mio = self.vivos[o["id"]]
            self.assertAlmostEqual(float(o["quantity"]), mio["monto"], places=2, msg=f"{paso}: lo cobrado")
            self.assertEqual(o["broker"], mio["cuenta"], f"{paso}: la cuenta del cobro")
            if mio["tipo"] == "Cupón":
                self.assertAlmostEqual(float(o["pnl_usd"]), mio["monto"], places=2, msg=f"{paso}: cupón")
            else:
                costo = mio["face"] * 0.60
                self.assertAlmostEqual(float(o["cost_basis_consumed"] or 0), costo, delta=0.02,
                                       msg=f"{paso}: costo de la amortización de {o['asset']}")
                self.assertAlmostEqual(float(o["pnl_usd"]), mio["monto"] - costo, delta=0.02,
                                       msg=f"{paso}: ganancia de la amortización de {o['asset']}")
        # 6. Los nominales ORIGINALES que ve la bandeja no cambian por confirmar,
        #    borrar, deshacer ni importar cobros: el pago que propone no depende del
        #    orden en que se hayan anotado los demás.
        orig = self._originales()
        self.assertEqual(set(orig), set(base["originales"]), f"{paso}: lotes de bonos")
        for k, v in base["originales"].items():
            self.assertAlmostEqual(orig[k], v, places=2, msg=f"{paso}: nominal original de {k}")

    # ── el libro ─────────────────────────────────────────────────────────────
    def _anotar(self, op_id, asset, fecha, tipo, cuenta, monto, face=0.0):
        baja = face if (tipo == "Amortización" and self.bonos[asset][2]) else 0.0
        self.vivos[op_id] = {"asset": asset, "fecha": fecha, "tipo": tipo, "cuenta": cuenta,
                             "monto": monto, "face": face, "baja": baja}
        self.caja[cuenta] = self.caja.get(cuenta, 0) + monto
        self.bajado[asset] = self.bajado.get(asset, 0) + baja

    def _sacar(self, op_id):
        v = self.vivos.pop(op_id)
        self.caja[v["cuenta"]] -= v["monto"]
        self.bajado[v["asset"]] -= v["baja"]
        return v

    # ── las acciones ─────────────────────────────────────────────────────────
    def _accion(self, rng, pendiente, paso):
        """`pendiente`: el "Deshacer" del último borrado = (token, foto de antes,
        lo borrado, ¿nada cambió desde entonces?). Se CONSERVA mientras se hacen
        otras cosas (antes cualquier acción lo tiraba, y deshacer corría el 8 % de
        las veces): deshacer tarde es justo lo que puede anotar un pago dos veces."""
        asset = rng.choice(sorted(self.bonos))
        broker, cuenta, _ = self.bonos[asset]
        fecha = rng.choice(sorted(PAGOS[asset]))
        cup, amo = PAGOS[asset][fecha]
        mios = self._del_pago(asset, fecha)
        self.traza.append("")
        viejo = (pendiente[0], pendiente[1], pendiente[2], False) if pendiente else None
        que = rng.choice(["pago", "pago", "formulario", "borrar", "borrar", "deshacer",
                          "deshacer", "importar"])
        self.traza[-1] = f"{que} {asset} {fecha}"
        if que == "formulario":
            # El formulario viejo carga cupón y amortización POR SEPARADO: se frena
            # lo del mismo tipo ya cargado a mano, o cualquier cobro importado.
            flujo = rng.choice(["coupon", "amortization"]) if amo else "coupon"
            tipo = "Cupón" if flujo == "coupon" else "Amortización"
            monto = cup if flujo == "coupon" else amo
            choca = (asset, fecha) in self.importado or tipo in mios
            r = self.c.post("/api/bonds/cashflow", json={
                "broker": broker, "asset": asset, "date": fecha, "flow_type": flujo,
                "amount": monto, "cash_broker": cuenta,
                "decrement_quantity": flujo == "amortization"})
            self.assertEqual(r.status_code, 409 if choca else 200, f"{paso}: {r.text}")
            self._cuenta(que, not choca)
            if not choca:
                self._anotar(r.json()["operation_id"], asset, fecha, tipo, cuenta, monto,
                             face=monto if tipo == "Amortización" else 0.0)
            return viejo
        if que == "pago":
            habia = (asset, fecha) in self.importado or bool(mios)
            com = rng.choice([0, 0, 1.5])
            cuerpo = {"broker": broker, "asset": asset, "date": fecha, "coupon_amount": cup,
                      "amort_amount": amo, "cash_broker": cuenta, "commissions": com}
            if amo:      # como la pantalla: el nominal amortizado viaja aparte
                cuerpo["face_amortized"] = amo
            r = self.c.post("/api/bonds/cashflow/pago", json=cuerpo)
            self.assertEqual(r.status_code, 409 if habia else 200, f"{paso}: {r.text}")
            self._cuenta(que, not habia)
            if not habia:
                for pt in r.json()["partes"]:
                    if pt["op_type"] == "Cupón":       # la comisión (menor al cupón) sale del cupón
                        self._anotar(pt["operation_id"], asset, fecha, "Cupón", cuenta, cup - com)
                    else:
                        self._anotar(pt["operation_id"], asset, fecha, "Amortización", cuenta, amo, face=amo)
            return viejo
        if que == "borrar":
            if not self.vivos:
                self._cuenta(que, False)
                return viejo
            op_id = rng.choice(sorted(self.vivos))
            antes = self._foto()
            r = self.c.delete(f"/api/movements/op-{op_id}-cobro")
            self.assertEqual(r.status_code, 200, f"{paso}: {r.text}")
            self._cuenta(que, True)
            borrado = self._sacar(op_id)
            return (r.json().get("undo_token"), antes, borrado, True)
        if que == "deshacer":
            if not pendiente or not pendiente[0]:
                self._cuenta(que, False)
                return None
            token, antes, borrado, intacto = pendiente
            r = self.c.post(f"/api/operations/undo/{token}")
            self.assertIn(r.status_code, (200, 409, 410), f"{paso}: {r.text}")
            self._cuenta(que, r.status_code == 200)
            if r.status_code == 200:
                # Vuelve el cobro borrado (con otro id): al libro, por lo que era.
                nuevo = [o["id"] for o in self._cobros() if o["a_mano"] and o["id"] not in self.vivos]
                self.assertEqual(len(nuevo), 1, f"{paso}: deshacer no trajo UN cobro")
                self._anotar(nuevo[0], borrado["asset"], borrado["fecha"], borrado["tipo"],
                             borrado["cuenta"], borrado["monto"], face=borrado["face"])
                if intacto:
                    ahora = self._foto()
                    self.assertEqual(ahora["caja"], antes["caja"], f"{paso}: deshacer no devolvió el efectivo")
                    self.assertEqual(ahora["lotes"], antes["lotes"], f"{paso}: deshacer no devolvió el nominal")
                    self.assertEqual(ahora["ops"], antes["ops"], f"{paso}: deshacer no devolvió la operación")
            return None
        # importar el archivo con el mismo pago (el broker acredita al día siguiente)
        if (asset, fecha) in self.importado:
            self._cuenta(que, False)
            return viejo                 # ya importado: un segundo archivo igual es otro tema
        dia = fecha[:8] + "10"
        del_archivo = cup + amo
        if asset == "AL30":
            self._importar("Cocos", f"{dia},RENTA Y AMORTIZACION,Cocos,AL30,,,{del_archivo},,,0,USD,")
        elif asset == "GD35":
            self._importar("IOL", f"{dia},RENTA,IOL,GD35,,,{del_archivo},,,0,USD,")
        else:   # GD46: la amortización como VENTA de los nominales (Balanz)
            self._importar("Balanz", f"{dia},VENTA,Balanz,GD46,{amo},{round(del_archivo / amo, 6)},"
                                     f"{del_archivo},,,0,USD,Renta y Amortizacion")
        # Qué tiene que haber pasado (la regla del importador, escrita acá):
        #   · nada a mano                       → entra el renglón;
        #   · lo anotado se parece al renglón   → se saltea (no entra nada);
        #   · a mano sólo un cupón, otro monto  → manda el broker: reemplaza;
        #   · si no (hay una amortización que ya bajó nominales, o las dos partes)
        #                                       → se saltea.
        montos = {t: v["monto"] for t, (_, v) in mios.items()}
        parecido = lambda a: abs(a - del_archivo) <= TOLERANCIA * max(a, del_archivo)
        grupos = [montos.get("Cupón"), montos.get("Amortización"), sum(montos.values()) if montos else None]
        if not mios:
            entra, reemplaza = True, False
        elif any(g and parecido(g) for g in grupos):
            entra, reemplaza = False, False
        elif set(mios) == {"Cupón"}:
            entra, reemplaza = True, True
        elif set(mios) == {"Amortización"} and not mios["Amortización"][1]["baja"]:
            # una amortización a mano que no le bajó nominales a nadie (el lote lo
            # lleva el barrido) tampoco ata: manda el broker
            entra, reemplaza = True, True
        else:
            entra, reemplaza = False, False
        self._cuenta(que, entra)
        if reemplaza:
            for op_id, _ in mios.values():
                self._sacar(op_id)
        if entra:
            self.importado.add((asset, fecha))
            self.caja[cuenta] = self.caja.get(cuenta, 0) + del_archivo
            if asset == "GD46":          # la venta del archivo baja esos nominales
                self.bajado[asset] = self.bajado.get(asset, 0) + amo
        return viejo

    def test_al_azar(self):
        rng = random.Random(SEMILLA)
        type(self).conteo = {}
        for n in range(N):
            self._armar(rng)
            base = self._foto()
            base["originales"] = self._originales()
            pendiente = None
            self.traza = [f"cuenta: {self.bonos}"]
            for k in range(rng.randint(4, 12)):
                paso = f"escenario {n} paso {k}"
                try:
                    pendiente = self._accion(rng, pendiente, paso)
                    self._verificar(base, paso)
                except AssertionError as ex:
                    # La secuencia que llevó hasta acá: sin esto un rojo no se puede repetir a mano.
                    raise AssertionError(f"{ex}\n\nSecuencia:\n  " + "\n  ".join(self.traza)) from None
        # Que la prueba pruebe: cada acción tiene que haberse EJECUTADO de verdad
        # (no sólo rechazado) una parte razonable de las veces.
        for que, (si, no) in sorted(self.conteo.items()):
            self.assertGreater(si, (si + no) * 0.15, f"«{que}» casi nunca se ejecuta: {si} de {si + no}")
        if os.environ.get("RENDI_AZAR_CONTEO"):
            print("\n" + ", ".join(f"{q}: {s} sí / {n} no" for q, (s, n) in sorted(self.conteo.items())))


def _d(iso):
    from datetime import date
    return date.fromisoformat(str(iso)[:10])


if __name__ == "__main__":
    unittest.main()
