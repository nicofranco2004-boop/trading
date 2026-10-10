"""Renombrar un broker en el medio de CUALQUIER secuencia de acciones no cambia nada.

Los escenarios armados de `test_renombre_broker_recetas.py` prueban cada receta por
separado. Esto mezcla: una secuencia al azar de acciones reales por HTTP (depositar,
cargar posiciones, vender, operaciones a mano, futuros, cobros de bonos, dividendos,
"No lo cobré", archivar y restaurar bonos, editar una posición, importar archivos que
se pisan, "Editar y rehacer" un import, borrar, deshacer)
sobre una cuenta con tres brokers (uno en pesos con su "· USD" y otro aparte), y la
corre DOS veces con la misma semilla: una con renombres metidos en pasos al azar y
otra sin renombrar. Las respuestas de cada paso y el estado final (por PAPEL de cada
broker, no por nombre) tienen que ser idénticos, y nada puede quedar a nombre de un
broker que no existe.

Los renombres también se mezclan: uno solo, dos seguidos, ida y vuelta al nombre
original, y el broker de al lado tomando el nombre que el primero dejó libre (el
caso que rompería una regla que confunda "el nombre viejo" con "el broker viejo").

Por defecto corre pocas semillas (entra en la suite). Para una pasada larga:
    cd backend && SEMILLAS_RENOMBRE=1-300 PASOS_RENOMBRE=40 \\
        python3 -m pytest tests/test_renombre_broker_azar.py -q -p no:cacheprovider
"""
import os
import random
import unittest

import main

try:
    from tests import test_renombre_broker_recetas as base
except ImportError:                                  # corrido suelto desde tests/
    import test_renombre_broker_recetas as base


def _semillas():
    crudo = os.environ.get("SEMILLAS_RENOMBRE", "1,2,3,4,5,6")
    out = []
    for parte in crudo.split(","):
        if "-" in parte:
            a, b = parte.split("-")
            out.extend(range(int(a), int(b) + 1))
        elif parte.strip():
            out.append(int(parte))
    return out


SEMILLAS = _semillas()
PASOS = int(os.environ.get("PASOS_RENOMBRE", "30"))

OTRO = "Hornero Ágil"
NOMBRES_NUEVOS = ("Zorzal Capital", "Zorzal «2» \\ cía", "Calandria")

# Activos por papel: (ticker, precio, extras del alta)
ACTIVOS = {
    "padre": (("GGAL", 5000, {}), ("YPFD", 30000, {}),
              ("AL30", 700, {"asset_type": "BOND"}), ("GD30", 800, {"asset_type": "BOND"}),
              ("KO", 14000, {"asset_type": "CEDEAR", "currency": "ARS"})),
    "USD": (("SPY", 400, {"currency": "USD"}), ("AAPL", 150, {"currency": "USD"})),
    "otro": (("BTC", 60000, {}), ("ETH", 3000, {})),
}
# (día de corte, día del cobro): el cobro tiene que caer dentro de los 45 días.
CORTES = (("2026-08-14", "2026-08-28"), ("2026-09-15", "2026-09-30"))


class _CuentaAzar(base._Cuenta):
    """Tres brokers: el padre en pesos, su "· USD" y otro aparte (USDT)."""

    def __init__(self):
        super().__init__(moneda="ARS", sub_usd=True)
        conn = main.get_db()
        try:                      # el plan gratis permite un solo broker
            conn.execute("UPDATE users SET tier='pro' WHERE id=?", (self.uid,))
            conn.commit()
        finally:
            conn.close()
        self.otro_id = self.ok("post", "/api/brokers", json={"name": OTRO, "currency": "USDT"})["id"]
        conn = main.get_db()
        try:
            self.sub_id = conn.execute("SELECT id FROM brokers WHERE user_id=? AND parent_broker_id=?",
                                       (self.uid, self.bid)).fetchone()["id"]
        finally:
            conn.close()
        self.tokens = []          # [(ruta de deshacer, token)]
        base._dolar_del_dia()
        conn = main.get_db()
        try:                      # el dólar de los cobros de agosto (tabla global)
            if not conn.execute("SELECT 1 FROM fx_rates_daily WHERE date='2026-08-14'").fetchone():
                for d in ("2026-08-14", "2026-08-28", "2026-09-30"):
                    conn.execute(
                        "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source, fetched_at) "
                        "VALUES (?,?,?,?,datetime('now'))", (d, 1450.0, 1450.0, "test"))
                conn.commit()
        finally:
            conn.close()

    def _papeles(self, conn) -> dict:
        por_id = {self.bid: "padre", self.sub_id: "USD", self.otro_id: "otro"}
        return {r["name"]: por_id.get(r["id"], f"BROKER DE MÁS «{r['name']}»")
                for r in conn.execute("SELECT id, name FROM brokers WHERE user_id=?", (self.uid,))}

    def nombre_de(self, papel: str) -> str:
        conn = main.get_db()
        try:
            return {v: k for k, v in self._papeles(conn).items()}[papel]
        finally:
            conn.close()

    def renombrar_a(self, papel: str, nuevo: str):
        bid = {"padre": self.bid, "otro": self.otro_id}[papel]
        viejo = self.nombre_de(papel)
        r = self.pedir("put", f"/api/brokers/{bid}",
                       json={"name": nuevo, "currency": "ARS" if papel == "padre" else "USDT"})
        return viejo, r

    def filas(self, sql: str):
        conn = main.get_db()
        try:
            return [dict(r) for r in conn.execute(sql, (self.uid,)).fetchall()]
        finally:
            conn.close()


# ── Las acciones. Cada una devuelve lo que pasó (código HTTP o un texto). ────────
def _depositar(c, rng):
    papel = rng.choice(("padre", "USD", "otro"))
    monto = rng.choice((1000, 50000, 2000000))
    return c.pedir("post", "/api/cash/flow", json={
        "broker_name": c.nombre_de(papel), "amount": monto,
        "date": rng.choice(("2026-08-01", "2026-09-03")), "direction": "deposit"}).status_code


def _comprar(c, rng):
    papel = rng.choice(("padre", "padre", "USD", "otro"))
    asset, precio, extra = rng.choice(ACTIVOS[papel])
    qty = rng.choice((1, 4, 10, 150))
    return c.pedir("post", "/api/positions", json={
        "broker": c.nombre_de(papel), "asset": asset, "quantity": qty, "buy_price": precio,
        "invested": qty * precio, "entry_date": rng.choice(("2026-08-02", "2026-08-20")),
        **extra}).status_code


def _vender(c, rng):
    lotes = c.filas("SELECT id, broker, asset, quantity, buy_price, currency FROM positions "
                    "WHERE user_id=? AND is_cash=0 AND quantity>0 ORDER BY id")
    if not lotes:
        return "nada para vender"
    l = rng.choice(lotes)
    qty = l["quantity"] if rng.random() < 0.5 else max(1, int(l["quantity"] // 2))
    cuerpo = {"broker": l["broker"], "asset": l["asset"], "quantity": qty,
              "exit_price": round(float(l["buy_price"] or 1) * rng.choice((0.9, 1.2)), 2),
              "date": rng.choice(("2026-09-01", "2026-09-10"))}
    if (l["currency"] or "").upper() == "USD":
        cuerpo["currency"] = "USD"
    return c.pedir("post", "/api/positions/sell", json=cuerpo).status_code


def _operacion_a_mano(c, rng):
    papel = rng.choice(("padre", "USD", "otro"))
    return c.pedir("post", "/api/operations", json={
        "date": "2026-09-05", "broker": c.nombre_de(papel), "asset": "BTC",
        "op_type": rng.choice(("Futuros", "LONG")), "pnl_usd": rng.choice((50, -20, 300)),
        "mueve_efectivo": rng.random() < 0.6}).status_code


def _abrir_futuro(c, rng):
    return c.pedir("post", "/api/futures", json={
        "broker": c.nombre_de(rng.choice(("otro", "USD"))), "symbol": rng.choice(("BTCUSDT", "ETHUSDT")),
        "side": rng.choice(("long", "short")), "quantity": 1, "entry_price": 60000,
        "opened_at": "2026-09-05"}).status_code


def _cerrar_futuro(c, rng):
    abiertos = c.filas("SELECT id FROM futures_positions WHERE user_id=? AND closed_at IS NULL ORDER BY id")
    if not abiertos:
        return "sin futuros"
    return c.pedir("post", f"/api/futures/{rng.choice(abiertos)['id']}/close",
                   json={"exit_price": rng.choice((59000, 61000)), "closed_at": "2026-09-20"}).status_code


def _cobro_de_bono(c, rng):
    return c.pedir("post", "/api/bonds/cashflow", json={
        "broker": c.nombre_de("padre"), "asset": "AL30",
        "flow_type": rng.choice(("coupon", "amortization")), "amount": 7000, "date": "2026-09-09",
        "decrement_quantity": True, "face_amortized": 10}).status_code


def _dividendo(c, rng):
    corte, cobro = rng.choice(CORTES)
    return c.pedir("post", "/api/dividendos/cobro", json={
        "broker": c.nombre_de("padre"), "asset": "KO", "ex_date": corte,
        "fecha": cobro, "bruto": 15.90, "impuesto": 4.77, "otros": 0.80,
        "comision_pesos": rng.choice((0.0, 62.0)), "cedears": 150}).status_code


def _no_lo_cobre(c, rng):
    cuerpo = {"broker": c.nombre_de("padre"), "asset": "KO", "ex_date": rng.choice(CORTES)[0]}
    if rng.random() < 0.6:
        return c.pedir("post", "/api/dividendos/saltear", json=cuerpo).status_code
    return c.pedir("delete", "/api/dividendos/saltear", params=cuerpo).status_code


def _archivar_bonos(c, rng):
    return c.pedir("post", "/api/sections/archive", json={"section": "BONO|ARS"}).status_code


def _restaurar_bonos(c, rng):
    arch = c.ok("get", "/api/sections/archived")["archived"]
    if not arch:
        return "nada archivado"
    return c.pedir("post", "/api/sections/restore",
                   json={"archive_id": sorted(a["id"] for a in arch)[0]}).status_code


def _editar_posicion(c, rng):
    # Por orden de CREACIÓN, no por nombre de broker: ordenar por nombre hacía que la
    # corrida con renombre eligiera otra posición (3 semillas de 300 fallaban por eso).
    lotes = c.filas("SELECT broker, asset, MIN(id) AS primero FROM positions WHERE user_id=? "
                    "AND is_cash=0 AND asset IN ('GGAL','YPFD','BTC') "
                    "GROUP BY broker, asset ORDER BY primero")
    if not lotes:
        return "nada para editar"
    l = rng.choice(lotes)
    r = c.pedir("patch", "/api/positions/group", json={
        "broker": l["broker"], "asset": l["asset"], "avg_price": rng.choice((4000, 6500))})
    if r.status_code == 200 and r.json().get("undo_token"):
        c.tokens.append(("/api/positions/group/undo", r.json()["undo_token"]))
    return r.status_code


def _borrar_operacion(c, rng):
    ops = c.filas("SELECT id FROM operations WHERE user_id=? ORDER BY id")
    if not ops:
        return "sin operaciones"
    r = c.pedir("delete", f"/api/operations/{rng.choice(ops)['id']}")
    if r.status_code == 200 and r.json().get("undo_token"):
        c.tokens.append(("/api/operations/undo", r.json()["undo_token"]))
    return r.status_code


def _borrar_posicion(c, rng):
    lotes = c.filas("SELECT id FROM positions WHERE user_id=? AND is_cash=0 ORDER BY id")
    if not lotes:
        return "sin posiciones"
    r = c.pedir("delete", f"/api/positions/{rng.choice(lotes)['id']}")
    if r.status_code == 200 and (r.json() or {}).get("undo_token"):
        c.tokens.append(("/api/operations/undo", r.json()["undo_token"]))
    return r.status_code


# Dos archivos por broker que se pisan entre sí (el segundo repite filas del primero).
ARCHIVOS = {
    "padre": (("2026-08-03,DEPOSITO,{b},,,,900000,,,0,ARS,",
               "2026-08-04,COMPRA,{b},PAMP,10,3000,30000,,,0,ARS,",
               "2026-08-06,COMPRA,{b},TXAR,5,800,4000,,,0,ARS,"),
              ("2026-08-04,COMPRA,{b},PAMP,10,3000,30000,,,0,ARS,",
               "2026-08-06,COMPRA,{b},TXAR,5,800,4000,,,0,ARS,",
               "2026-08-25,VENTA,{b},PAMP,4,3500,14000,,,0,ARS,")),
    "otro": (("2026-08-03,DEPOSITO,{b},,,,50000,,,0,USD,",
              "2026-08-04,COMPRA,{b},NVDA,10,100,1000,,,0,USD,"),
             ("2026-08-04,COMPRA,{b},NVDA,10,100,1000,,,0,USD,",
              "2026-08-26,VENTA,{b},NVDA,3,120,360,,,0,USD,",
              "2026-08-27,COMPRA,{b},AMD,4,150,600,,,0,USD,")),
}


def _confirmar_vista_previa(c, r):
    if r.status_code != 200:
        return r.status_code
    cuerpo = r.json()
    cuerpo = cuerpo.get("preview") or cuerpo
    if not cuerpo.get("session_id"):
        return "sin nada para confirmar"
    repetidas = len(cuerpo.get("duplicate_row_indices") or [])
    conf = c.pedir("post", "/api/imports/confirm", json={"session_id": cuerpo["session_id"]})
    return f"{conf.status_code}, {repetidas} repetidas"


def _importar_archivo(c, rng):
    papel = rng.choice(("padre", "otro"))
    nombre = c.nombre_de(papel)
    filas = [f.format(b=nombre) for f in rng.choice(ARCHIVOS[papel])]
    return _confirmar_vista_previa(c, c.pedir(
        "post", "/api/imports/preview",
        files=[("files", ("x.csv", base.io.BytesIO(base._csv(*filas)), "text/csv"))],
        data={"format": "rendi_generic", "broker": nombre}))


def _rehacer_import(c, rng):
    # Por orden de creación (rowid): el id del lote es un texto al azar.
    lotes = c.filas("SELECT id FROM import_batches WHERE user_id=? AND status='confirmed' "
                    "AND parser_format='rendi_generic' ORDER BY rowid")
    if not lotes:
        return "sin imports"
    return _confirmar_vista_previa(c, c.pedir("post", f"/api/imports/{rng.choice(lotes)['id']}/redo"))


def _deshacer(c, rng):
    if not c.tokens:
        return "nada que deshacer"
    ruta, tok = c.tokens.pop(rng.randrange(len(c.tokens)))
    return c.pedir("post", f"{ruta}/{tok}").status_code


ACCIONES = ((_depositar, 3), (_comprar, 5), (_vender, 4), (_operacion_a_mano, 2),
            (_abrir_futuro, 1), (_cerrar_futuro, 2), (_cobro_de_bono, 1), (_dividendo, 2),
            (_no_lo_cobre, 1), (_archivar_bonos, 2), (_restaurar_bonos, 2),
            (_editar_posicion, 1), (_borrar_operacion, 4), (_borrar_posicion, 3), (_deshacer, 4),
            (_importar_archivo, 3), (_rehacer_import, 1))


def _plan_de_renombres(rng) -> list:
    """[(paso, papel, nombre nuevo)] — cuándo y qué se renombra en la corrida CON."""
    a, b = sorted(rng.sample(range(3, PASOS - 1), 2))
    return rng.choice((
        [(a, "padre", NOMBRES_NUEVOS[0])],
        [(a, "padre", NOMBRES_NUEVOS[0]), (b, "padre", NOMBRES_NUEVOS[1])],
        [(a, "padre", NOMBRES_NUEVOS[1]), (b, "padre", base.VIEJO)],            # ida y vuelta
        [(a, "padre", NOMBRES_NUEVOS[0]), (b, "otro", base.VIEJO)],             # el vecino toma el nombre libre
        [(a, "otro", NOMBRES_NUEVOS[2])],
        [(a, "otro", NOMBRES_NUEVOS[2]), (b, "padre", NOMBRES_NUEVOS[1])],
    ))


class RenombrarEnElMedioDeCualquierCosa(unittest.TestCase):
    def setUp(self):
        base._sin_reconstruccion_de_fondo(self)

    def _correr(self, semilla: int, con_renombres: bool):
        rng = random.Random(semilla)
        plan = _plan_de_renombres(rng)
        acciones = [f for f, peso in ACCIONES for _ in range(peso)]
        c = _CuentaAzar()
        hecho = []
        for paso in range(PASOS):
            if con_renombres:
                for cuando, papel, nuevo in plan:
                    if cuando != paso:
                        continue
                    viejo, r = c.renombrar_a(papel, nuevo)
                    self.assertEqual(r.status_code, 200, f"semilla {semilla}, paso {paso}: no "
                                     f"dejó renombrar «{viejo}» → «{nuevo}»: {r.text[:200]}")
                    # En ese mismo instante, el nombre que se dejó no puede quedar
                    # guardado en ningún lado (después puede volver: ida y vuelta).
                    quedan = base._apariciones(c.uid, viejo)
                    self.assertEqual(quedan, [], f"semilla {semilla}, paso {paso}: tras "
                                     f"renombrar «{viejo}» → «{nuevo}» sigue guardado en:\n  "
                                     + "\n  ".join(quedan[:8]))
            accion = rng.choice(acciones)
            hecho.append((paso, accion.__name__, accion(c, rng)))
        return hecho, c.estado(), plan

    def _una_semilla(self, semilla: int):
        hecho_sin, estado_sin, plan = self._correr(semilla, con_renombres=False)
        self.assertEqual(estado_sin["huerfanos"], [],
                         f"semilla {semilla}: SIN renombrar ya quedan filas sin broker")
        hecho_con, estado_con, _ = self._correr(semilla, con_renombres=True)
        pista = f"semilla {semilla}, renombres {plan}"
        for a, b in zip(hecho_sin, hecho_con):
            self.assertEqual(b, a, f"{pista}: el paso {a[0]} ({a[1]}) respondió {a[2]} sin "
                                   f"renombrar y {b[2]} con renombre")
        for clave in estado_sin:
            self.assertEqual(estado_con[clave], estado_sin[clave],
                             f"{pista}: con renombre cambia «{clave}»")


for _s in SEMILLAS:
    setattr(RenombrarEnElMedioDeCualquierCosa, f"test_semilla_{_s:04d}",
            (lambda s: lambda self: self._una_semilla(s))(_s))


if __name__ == "__main__":
    unittest.main()
