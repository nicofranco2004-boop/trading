"""Renombrar un broker tiene que cambiar el nombre también ADENTRO de lo guardado.

Bug (reproducido por HTTP el 2026-10-09): `PUT /api/brokers/{bid}` reescribía el
nombre en las tablas que lo tienen como columna, pero no:
  · adentro de las RECETAS de borrado (`undo_meta_json` de operations y positions):
    `cash_broker`, `broker`, `lot.broker` y la receta del lote guardada como texto
    adentro de la de la venta;
  · en `futures_positions` (los futuros ABIERTOS), que no estaba en la lista;
  · en las secciones archivadas (`archived_positions.payload`);
  · en el registro de borrados (`deleted_ops_journal`: la columna y lo de adentro).
Resultado medido: borrar una venta después de renombrar decía "borrado", dejaba el
efectivo visible igual (+$60.000 de más), devolvía el lote a nombre del broker viejo
(no se ve) y creaba una caja escondida de −$60.000. Cerrar un futuro mandaba la
ganancia al broker viejo. Restaurar bonos archivados los dejaba invisibles. Borrar
una posición a mano frenaba con 409 para siempre.

Cómo se prueba (todo por las mismas puertas que usa la app):
  1. DIFERENCIAL — cada escenario corre dos veces con usuarios nuevos: con renombre
     en el medio y sin renombre. Las respuestas y el estado final (efectivo por
     broker, tenencias, operaciones, meses, futuros) tienen que ser IDÉNTICOS,
     salvo el nombre. Y ninguna fila puede quedar a nombre de un broker que no existe.
  2. GUARDIÁN POR VALOR — después de renombrar, el nombre viejo no puede aparecer en
     NINGUNA columna de texto de la cuenta (decodificando los JSON, también los que
     van como texto adentro de otros: así el "·" guardado como \\u00b7 no se esconde).
     Si aparece en un lugar nuevo, el test dice dónde.
  3. COBERTURA — cada tipo de receta (`"src": ...`) y cada tipo de registro de
     borrado que exista en el código tiene que tener su escenario acá. Una receta
     nueva sin escenario hace fallar el test (con el mensaje de qué hacer).
  4. ESQUEMA — toda tabla con una columna de broker tiene que estar en la lista del
     renombre o en la de excepciones, con su motivo.
"""
import io
import json
import os
import re
import unittest
import uuid
from unittest import mock

from fastapi.testclient import TestClient

import main

# Con tilde y eñe a propósito: `json.dumps` los guarda escapados (Ñ, ú), y el
# sub-broker agrega el "·" (·). Buscar el nombre crudo en el texto no los encuentra.
VIEJO = "Zorzal Ñandú"
NUEVO = "Zorzal Capital"
SUB = " · USD"

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"

# Columnas donde el nombre viejo PUEDE quedar, con el motivo. Todo lo demás, no.
_PUEDE_QUEDAR = {
    # Analítica de uso: anota lo que pasó, con el nombre que tenía en ese momento.
    ("plan_events", "props_json"),
    # Lo que decía el ARCHIVO importado. No se reescribe (hay cuentas con medio millón
    # de filas: trababa la base); "Editar y rehacer" lo traduce al leer, y el
    # escenario `rehacer_import` mide que ande.
    ("import_raw_rows", "raw_json"),
}


def _csv(*filas: str) -> bytes:
    return (HDR + "".join(f + "\n" for f in filas)).encode("utf-8")


def _textos(valor):
    """Todos los textos de un valor, bajando a JSON (también al guardado como texto
    adentro de otro JSON) y a las claves de los diccionarios."""
    if isinstance(valor, dict):
        for k, v in valor.items():
            yield str(k)
            yield from _textos(v)
    elif isinstance(valor, list):
        for v in valor:
            yield from _textos(v)
    elif isinstance(valor, str):
        yield valor
        if valor[:1] in "{[":
            try:
                yield from _textos(json.loads(valor))
            except ValueError:
                pass


def _apariciones(uid: int, nombre: str) -> list:
    """Dónde aparece `nombre` en la cuenta: toda tabla con user_id (o con batch_id de
    un import del usuario), toda columna de texto, JSON decodificado."""
    conn = main.get_db()
    out = []
    try:
        tablas = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for t in tablas:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
            if "user_id" in cols:
                filas = conn.execute(f"SELECT * FROM {t} WHERE user_id=?", (uid,)).fetchall()
            elif "batch_id" in cols:
                filas = conn.execute(
                    f"SELECT * FROM {t} WHERE batch_id IN "
                    f"(SELECT id FROM import_batches WHERE user_id=?)", (uid,)).fetchall()
            else:
                continue
            for f in filas:
                for c in cols:
                    if (t, c) in _PUEDE_QUEDAR:
                        continue
                    v = f[c]
                    if isinstance(v, str) and any(nombre in s for s in _textos(v)):
                        out.append(f"{t}.{c} (id {f['id'] if 'id' in cols else '?'}): {v[:160]}")
    finally:
        conn.close()
    return out


def _recetas_y_registros(uid: int) -> tuple:
    """(tipos de receta, tipos de registro de borrado) presentes en la cuenta."""
    conn = main.get_db()
    srcs, kinds = set(), set()
    try:
        for t, c in (("operations", "undo_meta_json"), ("positions", "undo_meta_json"),
                     ("archived_positions", "payload"), ("deleted_ops_journal", "payload_json"),
                     ("dividendos_reemplazados", "op_json")):
            for (v,) in conn.execute(f"SELECT {c} FROM {t} WHERE user_id=? AND {c} IS NOT NULL",
                                     (uid,)):
                for s in _textos(v):
                    if s[:1] == "{":
                        try:
                            d = json.loads(s)
                        except ValueError:
                            continue
                        if isinstance(d, dict) and isinstance(d.get("src"), str):
                            srcs.add(d["src"])
        kinds = {r[0] for r in conn.execute(
            "SELECT kind FROM deleted_ops_journal WHERE user_id=?", (uid,))}
    finally:
        conn.close()
    return srcs, kinds


class _Cuenta:
    """Un usuario nuevo con un broker, manejado por HTTP como lo maneja la app."""

    def __init__(self, moneda="ARS", sub_usd=False):
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, is_admin) VALUES (?, 'x', 1, 0)",
            (f"ren-{uuid.uuid4().hex[:12]}@rendi.test",)).lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.c = TestClient(main.app)
        self.moneda = moneda
        self.bid = self.ok("post", "/api/brokers", json={"name": VIEJO, "currency": moneda})["id"]
        self.nombre = VIEJO
        self.sub = None
        if sub_usd:
            self.sub = self.ok("post", f"/api/brokers/{self.bid}/usd-sibling")["name"]

    def pedir(self, metodo, url, **kw):
        return getattr(self.c, metodo)(url, headers=self.h, **kw)

    def ok(self, metodo, url, **kw):
        r = self.pedir(metodo, url, **kw)
        assert r.status_code == 200, f"{metodo.upper()} {url} → {r.status_code} {r.text[:300]}"
        return r.json()

    def renombrar(self):
        self.ok("put", f"/api/brokers/{self.bid}", json={"name": NUEVO, "currency": self.moneda})
        self.nombre = NUEVO
        if self.sub:
            self.sub = NUEVO + SUB

    def depositar(self, monto, broker=None, fecha="2026-08-01"):
        self.ok("post", "/api/cash/flow", json={"broker_name": broker or self.nombre,
                                                "amount": monto, "date": fecha,
                                                "direction": "deposit"})

    def posicion(self, asset, qty, precio, broker=None, **extra):
        cuerpo = {"broker": broker or self.nombre, "asset": asset, "quantity": qty,
                  "buy_price": precio, "invested": qty * precio, "entry_date": "2026-08-02"}
        cuerpo.update(extra)
        return self.ok("post", "/api/positions", json=cuerpo)["id"]

    def vender(self, asset, qty, precio, broker=None, **extra):
        cuerpo = {"broker": broker or self.nombre, "asset": asset, "quantity": qty,
                  "exit_price": precio, "date": "2026-08-10"}
        cuerpo.update(extra)
        self.ok("post", "/api/positions/sell", json=cuerpo)
        return self.ultima_operacion()

    def ultima_operacion(self):
        conn = main.get_db()
        try:
            return conn.execute("SELECT id FROM operations WHERE user_id=? ORDER BY id DESC",
                                (self.uid,)).fetchone()["id"]
        finally:
            conn.close()

    def lote(self, asset):
        conn = main.get_db()
        try:
            r = conn.execute("SELECT id FROM positions WHERE user_id=? AND asset=? AND is_cash=0 "
                             "ORDER BY id DESC", (self.uid, asset)).fetchone()
            return r["id"] if r else None
        finally:
            conn.close()

    def importar(self, *filas):
        """Import por las puertas reales (`/api/imports/preview` + `/confirm`)."""
        r = self.ok("post", "/api/imports/preview",
                    files=[("files", ("x.csv", io.BytesIO(_csv(*filas)), "text/csv"))],
                    data={"format": "rendi_generic", "broker": self.nombre})
        self.ok("post", "/api/imports/confirm", json={"session_id": r["session_id"]})

    def _papeles(self, conn) -> dict:
        """{nombre de hoy: papel} de cada broker de la cuenta."""
        return {r["name"]: ("USD" if r["parent_broker_id"] else "padre")
                for r in conn.execute("SELECT name, parent_broker_id FROM brokers "
                                      "WHERE user_id=?", (self.uid,))}

    def estado(self) -> dict:
        """Lo que importa de la cuenta, con cada broker por su PAPEL (padre / USD) y no
        por su nombre: así la corrida con renombre y la sin renombre se comparan."""
        conn = main.get_db()
        try:
            papel = self._papeles(conn)
            papel["global"] = "global"

            def p(n):
                return papel.get(n, f"HUÉRFANO «{n}»")

            def r4(x):
                return None if x is None else round(float(x), 4)
            uid = (self.uid,)
            return {
                "brokers": sorted(v for k, v in papel.items() if k != "global"),
                "efectivo": sorted((p(r["broker"]), r4(r["invested"])) for r in conn.execute(
                    "SELECT broker, invested FROM positions WHERE user_id=? AND is_cash=1", uid)),
                "tenencias": sorted((p(r["broker"]), r["asset"], r4(r["quantity"]), r4(r["invested"]),
                                     r4(r["price_override"])) for r in conn.execute(
                    "SELECT broker, asset, quantity, invested, price_override FROM positions "
                    "WHERE user_id=? AND is_cash=0", uid)),
                "operaciones": sorted((p(r["broker"]), r["asset"], r["op_type"] or "",
                                       r4(r["pnl_usd"])) for r in conn.execute(
                    "SELECT broker, asset, op_type, pnl_usd FROM operations WHERE user_id=?", uid)),
                "meses": sorted((p(r["broker"]), r["year"], r["month"], r4(r["deposits"]),
                                 r4(r["withdrawals"]), r4(r["pnl_realized"]), r4(r["capital_final"]))
                                for r in conn.execute(
                    "SELECT broker, year, month, deposits, withdrawals, pnl_realized, capital_final "
                    "FROM monthly_entries WHERE user_id=?", uid)),
                "futuros": sorted((p(r["broker"]), r["symbol"], r["closed_at"] or "")
                                  for r in conn.execute(
                    "SELECT broker, symbol, closed_at FROM futures_positions WHERE user_id=?", uid)),
                "no_lo_cobre": sorted((p(r["broker"]), r["asset"], r["ex_date"])
                                      for r in conn.execute(
                    "SELECT broker, asset, ex_date FROM dividendos_salteados WHERE user_id=?", uid)),
                "huerfanos": sorted(
                    f"{t}: «{r[0]}»" for t in ("positions", "operations", "monthly_entries",
                                               "futures_positions", "flujos_a_mano",
                                               "dividendos_salteados")
                    for r in conn.execute(f"SELECT broker FROM {t} WHERE user_id=?", uid)
                    if r[0] not in papel),
            }
        finally:
            conn.close()


# ── Escenarios ────────────────────────────────────────────────────────────────
# Cada uno: `armar(cta)` deja la cuenta con lo que el renombre tiene que cuidar y
# devuelve lo que `actuar` necesita; `actuar(cta, ctx)` hace lo que antes rompía y
# devuelve las respuestas (código + cuerpo relevante). `recetas` y `registros` son
# los tipos que el escenario CUBRE (se controla que de verdad estén en la cuenta).

class Escenario:
    def __init__(self, nombre, armar, actuar, recetas=(), registros=(), moneda="ARS",
                 sub_usd=False):
        self.nombre, self.armar, self.actuar = nombre, armar, actuar
        self.recetas, self.registros = set(recetas), set(registros)
        self.moneda, self.sub_usd = moneda, sub_usd


def _codigo(r):
    return r.status_code


# 1. Posición cargada a mano → borrarla.
def _armar_posicion(cta):
    cta.depositar(100000)
    return {"pid": cta.posicion("GGAL", 10, 5000)}


def _actuar_posicion(cta, ctx):
    return [_codigo(cta.pedir("delete", f"/api/positions/{ctx['pid']}"))]


# 2. Posición sin plata cargada (dispara el autodepósito) → borrarla.
def _armar_posicion_autodeposito(cta):
    return {"pid": cta.posicion("GGAL", 10, 5000)}


# 3. Venta TOTAL con "Vender" → borrar la venta → borrar el lote que volvió (su receta
#    viene guardada como texto adentro de la de la venta).
def _armar_venta_total(cta):
    cta.depositar(100000)
    cta.posicion("GGAL", 10, 5000)
    return {"oid": cta.vender("GGAL", 10, 6000)}


def _actuar_venta_y_lote(cta, ctx):
    out = [_codigo(cta.pedir("delete", f"/api/operations/{ctx['oid']}"))]
    out.append(_codigo(cta.pedir("delete", f"/api/positions/{cta.lote('GGAL')}")))
    return out


# 4. Venta PARCIAL (el lote sobrevive) → borrar la venta.
def _armar_venta_parcial(cta):
    cta.depositar(100000)
    cta.posicion("GGAL", 10, 5000)
    return {"oid": cta.vender("GGAL", 4, 6000)}


def _actuar_borrar_op(cta, ctx):
    return [_codigo(cta.pedir("delete", f"/api/operations/{ctx['oid']}"))]


# 5. Venta en el sub-broker "· USD" → renombrar el PADRE → borrar la venta.
def _armar_venta_sub_usd(cta):
    cta.depositar(1000, broker=cta.sub)
    cta.posicion("SPY", 2, 400, broker=cta.sub, currency="USD")
    return {"oid": cta.vender("SPY", 2, 450, broker=cta.sub, currency="USD")}


# 6. Operación a mano que MOVIÓ el efectivo → borrarla.
def _armar_op_mueve_efectivo(cta):
    cta.depositar(1000)
    return {"oid": cta.ok("post", "/api/operations", json={
        "date": "2026-08-05", "broker": cta.nombre, "asset": "BTC", "op_type": "Futuros",
        "pnl_usd": 50, "mueve_efectivo": True})["id"]}


# 7. Operación a mano que NO movió el efectivo → borrarla.
def _armar_op_sin_efectivo(cta):
    cta.depositar(1000)
    return {"oid": cta.ok("post", "/api/operations", json={
        "date": "2026-08-05", "broker": cta.nombre, "asset": "BTC", "op_type": "LONG",
        "pnl_usd": 30})["id"]}


# 8. Cobro de un bono que amortizó (baja el nominal) → borrar el cobro.
def _armar_cobro_bono(cta):
    cta.depositar(1000000)
    cta.posicion("AL30", 1000, 700, asset_type="BOND")
    cta.ok("post", "/api/bonds/cashflow", json={
        "broker": cta.nombre, "asset": "AL30", "flow_type": "amortization", "amount": 70000,
        "date": "2026-08-09", "decrement_quantity": True, "face_amortized": 100})
    return {"oid": cta.ultima_operacion()}


# 9. Futuro ABIERTO → cerrarlo → borrar el cierre (vuelve a quedar abierto).
def _armar_futuro_abierto(cta):
    cta.depositar(1000)
    return {"fid": cta.ok("post", "/api/futures", json={
        "broker": cta.nombre, "symbol": "BTCUSDT", "side": "long", "quantity": 1,
        "entry_price": 60000, "opened_at": "2026-08-05"})["id"]}


def _actuar_cerrar_futuro(cta, ctx):
    r = cta.pedir("post", f"/api/futures/{ctx['fid']}/close",
                  json={"exit_price": 61000, "closed_at": "2026-08-20"})
    out = [_codigo(r)]
    if r.status_code == 200:
        out.append(_codigo(cta.pedir("delete", f"/api/operations/{r.json()['operation_id']}")))
    return out


# 10. Sección de bonos archivada → restaurarla → borrar la posición que volvió.
def _armar_seccion_archivada(cta):
    cta.depositar(1000000)
    cta.posicion("AL30", 1000, 700, asset_type="BOND")
    cta.ok("post", "/api/sections/archive", json={"section": "BONO|ARS"})
    return {}


def _actuar_restaurar(cta, ctx):
    arch = cta.ok("get", "/api/sections/archived")["archived"]
    out = [_codigo(cta.pedir("post", "/api/sections/restore", json={"archive_id": arch[0]["id"]}))]
    out.append(_codigo(cta.pedir("delete", f"/api/positions/{cta.lote('AL30')}")))
    return out


# ── El registro de borrados ("Deshacer"): borrar ANTES de renombrar, deshacer después.
def _armar_borrado_op_mano(cta):
    ctx = _armar_venta_total(cta)
    return {"tok": cta.ok("delete", f"/api/operations/{ctx['oid']}")["undo_token"]}


def _actuar_deshacer_op(cta, ctx):
    return [_codigo(cta.pedir("post", f"/api/operations/undo/{ctx['tok']}"))]


def _armar_borrado_posicion_mano(cta):
    ctx = _armar_posicion_autodeposito(cta)
    return {"tok": cta.ok("delete", f"/api/positions/{ctx['pid']}")["undo_token"]}


_FILAS_IMPORT = ("2026-08-01,DEPOSITO,{b},,,,100000,,,0,USD,",
                 "2026-08-03,COMPRA,{b},AAPL,10,150,1500,,,0,USD,",
                 "2026-08-04,COMPRA,{b},MSFT,5,300,1500,,,0,USD,",
                 "2026-08-12,VENTA,{b},AAPL,4,170,680,,,0,USD,")


def _importar(cta):
    cta.importar(*(f.format(b=cta.nombre) for f in _FILAS_IMPORT))


def _armar_borrado_venta_importada(cta):
    _importar(cta)
    conn = main.get_db()
    try:
        oid = conn.execute("SELECT id FROM operations WHERE user_id=? AND asset='AAPL'",
                           (cta.uid,)).fetchone()["id"]
    finally:
        conn.close()
    return {"tok": cta.ok("delete", f"/api/operations/{oid}")["undo_token"]}


def _armar_borrado_compra_importada(cta):
    _importar(cta)
    return {"tok": cta.ok("delete", f"/api/positions/{cta.lote('MSFT')}")["undo_token"]}


def _armar_borrado_historial(cta):
    _importar(cta)
    return {"tok": cta.ok("delete", "/api/assets/history", params={"asset": "AAPL"})["undo_token"]}


def _actuar_deshacer_historial(cta, ctx):
    return [_codigo(cta.pedir("post", f"/api/assets/undo/{ctx['tok']}"))]


# "Editar y rehacer" un import: vuelve a leer las filas CRUDAS del archivo, que
# también traen el nombre del broker. Con el viejo ahí, el rehacer creaba de nuevo
# un broker con el nombre viejo y metía todo el import en él.
def _armar_import_para_rehacer(cta):
    _importar(cta)
    conn = main.get_db()
    try:
        return {"batch": conn.execute(
            "SELECT id FROM import_batches WHERE user_id=? AND status='confirmed'",
            (cta.uid,)).fetchone()["id"]}
    finally:
        conn.close()


def _actuar_rehacer(cta, ctx):
    r = cta.pedir("post", f"/api/imports/{ctx['batch']}/redo")
    out = [_codigo(r)]
    if r.status_code == 200:
        sid = r.json()["preview"]["session_id"]
        out.append(_codigo(cta.pedir("post", "/api/imports/confirm", json={"session_id": sid})))
    return out


# El precio por cuotaparte que fija una foto de tenencia de Balanz (la ÚNICA puerta que
# escribe `fund_price_overrides`; un test no puede subir una foto real de Balanz, así
# que se planta lo que esa foto deja: el JSON en el batch y el precio en el fondo).
# Revertir el import tiene que limpiar ese precio — buscándolo por broker.
def _armar_precio_de_fondo(cta):
    cta.importar(f"2026-08-01,DEPOSITO,{cta.nombre},,,,100000,,,0,USD,",
                 f"2026-08-03,COMPRA,{cta.nombre},AAPL,10,150,1500,,,0,USD,")
    pid = cta.posicion("FCIX", 100, 1, asset_type="FUND")
    conn = main.get_db()
    try:
        batch = conn.execute("SELECT id FROM import_batches WHERE user_id=? AND status='confirmed'",
                             (cta.uid,)).fetchone()["id"]
        conn.execute("UPDATE import_batches SET fund_price_overrides=? WHERE id=?",
                     (json.dumps([{"asset": "FCIX", "broker": cta.nombre, "po": 2.0}]), batch))
        conn.execute("UPDATE positions SET price_override=2.0 WHERE id=?", (pid,))
        conn.commit()
    finally:
        conn.close()
    return {"batch": batch}


def _actuar_revertir_import(cta, ctx):
    return [_codigo(cta.pedir("post", f"/api/imports/{ctx['batch']}/revert"))]


# ── La bandeja de dividendos (Cartera) ───────────────────────────────────────
# El cobro confirmado acredita dólares en la cuenta "· USD" y cobra la comisión en
# pesos en el padre; su receta guarda las tres cuentas. "No lo cobré" guarda el
# broker en su propia tabla. Y si un import trae el mismo dividendo, el confirmado
# queda guardado aparte (con su broker) para volver si ese import se revierte.
_KO = dict(asset="KO", ex_date="2026-09-15", fecha="2026-10-06", bruto=15.90,
           impuesto=4.77, otros=0.80, comision_pesos=62.0, cedears=150)


def _dolar_del_dia():
    """La bandeja pasa la comisión en pesos a dólares con el dólar del día del cobro
    (`fx_rates_daily`, tabla GLOBAL: se siembra, no se pisa lo que haya)."""
    conn = main.get_db()
    try:
        for d in ("2026-09-15", "2026-10-06", "2026-10-07"):
            if not conn.execute("SELECT 1 FROM fx_rates_daily WHERE date=?", (d,)).fetchone():
                conn.execute(
                    "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source, fetched_at) "
                    "VALUES (?,?,?,?,datetime('now'))", (d, 1450.0, 1450.0, "test"))
        conn.commit()
    finally:
        conn.close()


def _cuenta_con_cedear(cta):
    _dolar_del_dia()
    cta.depositar(3000000)
    cta.depositar(1000, broker=cta.sub)
    cta.posicion("KO", 150, 14000, asset_type="CEDEAR", currency="ARS")


def _armar_dividendo(cta):
    _cuenta_con_cedear(cta)
    return {"oid": cta.ok("post", "/api/dividendos/cobro",
                          json={"broker": cta.nombre, **_KO})["operation_id"]}


def _actuar_dividendo(cta, ctx):
    # Confirmarlo otra vez tiene que seguir frenando (lo reconoce por su receta, que
    # el renombre reescribe: si cambiara el formato del texto dejaría de encontrarlo).
    otra_vez = cta.pedir("post", "/api/dividendos/cobro", json={"broker": cta.nombre, **_KO})
    borrar = cta.pedir("delete", f"/api/operations/{ctx['oid']}")
    return [200 if otra_vez.status_code == 409 else f"confirmó dos veces: {otra_vez.status_code}",
            _codigo(borrar)]


def _armar_borrado_de_dividendo(cta):
    ctx = _armar_dividendo(cta)
    return {"tok": cta.ok("delete", f"/api/operations/{ctx['oid']}")["undo_token"]}


def _armar_no_lo_cobre(cta):
    _cuenta_con_cedear(cta)
    cta.ok("post", "/api/dividendos/saltear", json={
        "broker": cta.nombre, "asset": "KO", "ex_date": _KO["ex_date"]})
    return {}


def _actuar_quitar_no_lo_cobre(cta, ctx):
    lista = cta.ok("get", "/api/dividendos/salteados")
    lista = lista if isinstance(lista, list) else (lista.get("salteados") or [])
    return [200 if [x["broker"] for x in lista] == [cta.nombre]
            else f"la lista trae {[x['broker'] for x in lista]}",
            _codigo(cta.pedir("delete", "/api/dividendos/saltear", params={
                "broker": cta.nombre, "asset": "KO", "ex_date": _KO["ex_date"]}))]


def _armar_dividendo_reemplazado(cta):
    _armar_dividendo(cta)
    # El archivo del broker trae el mismo dividendo: reemplaza al confirmado.
    cta.importar(f"2026-10-07,DIVIDENDO,{cta.nombre},KO,,,10.33,,,0,USD,")
    conn = main.get_db()
    try:
        guardados = conn.execute("SELECT COUNT(*) FROM dividendos_reemplazados WHERE user_id=?",
                                 (cta.uid,)).fetchone()[0]
        assert guardados == 1, f"el import no reemplazó al confirmado ({guardados})"
        return {"batch": conn.execute(
            "SELECT id FROM import_batches WHERE user_id=? AND status='confirmed'",
            (cta.uid,)).fetchone()["id"]}
    finally:
        conn.close()


def _armar_edicion_grupo(cta):
    cta.depositar(100000)
    cta.posicion("GGAL", 10, 5000)
    cta.vender("GGAL", 4, 6000)
    return {"tok": cta.ok("patch", "/api/positions/group", json={
        "broker": cta.nombre, "asset": "GGAL", "new_asset": "GGAL2"})["undo_token"]}


def _actuar_deshacer_grupo(cta, ctx):
    return [_codigo(cta.pedir("post", f"/api/positions/group/undo/{ctx['tok']}"))]


ESCENARIOS = [
    Escenario("posicion_a_mano", _armar_posicion, _actuar_posicion,
              recetas={"manual_position"}),
    Escenario("posicion_con_autodeposito", _armar_posicion_autodeposito, _actuar_posicion,
              recetas={"manual_position"}),
    Escenario("venta_total_y_su_lote", _armar_venta_total, _actuar_venta_y_lote,
              recetas={"fifo_sell", "manual_position"}),
    Escenario("venta_parcial", _armar_venta_parcial, _actuar_borrar_op,
              recetas={"fifo_sell"}),
    Escenario("venta_en_el_sub_broker_usd", _armar_venta_sub_usd, _actuar_borrar_op,
              recetas={"fifo_sell"}, sub_usd=True),
    Escenario("operacion_que_movio_efectivo", _armar_op_mueve_efectivo, _actuar_borrar_op,
              recetas={"manual_futures"}, moneda="USDT"),
    Escenario("operacion_sin_efectivo", _armar_op_sin_efectivo, _actuar_borrar_op,
              recetas={"manual_form"}, moneda="USDT"),
    Escenario("cobro_de_bono_que_amortizo", _armar_cobro_bono, _actuar_borrar_op,
              recetas={"bond_cashflow"}),
    Escenario("futuro_abierto", _armar_futuro_abierto, _actuar_cerrar_futuro, moneda="USDT"),
    Escenario("seccion_archivada", _armar_seccion_archivada, _actuar_restaurar,
              recetas={"manual_position"}),
    Escenario("deshacer_borrado_de_venta_a_mano", _armar_borrado_op_mano, _actuar_deshacer_op,
              recetas={"fifo_sell", "manual_position"}, registros={"manual_op"}),
    Escenario("deshacer_borrado_de_posicion_a_mano", _armar_borrado_posicion_mano,
              _actuar_deshacer_op, recetas={"manual_position"}, registros={"manual_position"}),
    Escenario("deshacer_borrado_de_venta_importada", _armar_borrado_venta_importada,
              _actuar_deshacer_op, registros={"imported"}, moneda="USD"),
    Escenario("deshacer_borrado_de_compra_importada", _armar_borrado_compra_importada,
              _actuar_deshacer_op, registros={"imported"}, moneda="USD"),
    Escenario("deshacer_borrado_de_historial", _armar_borrado_historial,
              _actuar_deshacer_historial, registros={"imported_asset"}, moneda="USD"),
    Escenario("rehacer_import", _armar_import_para_rehacer, _actuar_rehacer, moneda="USD"),
    Escenario("revertir_foto_con_precio_de_fondo", _armar_precio_de_fondo,
              _actuar_revertir_import, recetas={"manual_position"}, moneda="USD"),
    Escenario("dividendo_confirmado", _armar_dividendo, _actuar_dividendo,
              recetas={"dividendo_bandeja", "manual_position"}, sub_usd=True),
    Escenario("deshacer_borrado_de_dividendo", _armar_borrado_de_dividendo, _actuar_deshacer_op,
              registros={"manual_op"}, sub_usd=True),
    Escenario("dividendo_no_lo_cobre", _armar_no_lo_cobre, _actuar_quitar_no_lo_cobre,
              sub_usd=True),
    Escenario("dividendo_reemplazado_por_un_import_que_se_revierte",
              _armar_dividendo_reemplazado, _actuar_revertir_import, sub_usd=True),
    Escenario("deshacer_edicion_de_posicion", _armar_edicion_grupo, _actuar_deshacer_grupo,
              recetas={"manual_position", "fifo_sell"}, registros={"position_group_edit"}),
]


def _sin_reconstruccion_de_fondo(test) -> None:
    """Cada pedido que toca la contabilidad lanza la reconstrucción de la historia en
    otro hilo; acá corría a destiempo entre una cuenta y la siguiente. Se apaga: lo
    que se mide es la contabilidad, no las fotos (ver test_borrar_conserva_el_dia)."""
    for nombre in ("_reconstruir_mtm_post_import", "_reconstruir_en_fila"):
        p = mock.patch.object(main, nombre, side_effect=lambda *a, **k: None)
        p.start()
        test.addCleanup(p.stop)


class RenombrarYDespuesBorrar(unittest.TestCase):
    """El diferencial: con renombre en el medio tiene que dar EXACTAMENTE lo mismo
    que sin renombre. Un test por escenario (se generan abajo)."""

    def setUp(self):
        _sin_reconstruccion_de_fondo(self)

    def _correr(self, esc: Escenario, renombrar: bool):
        cta = _Cuenta(moneda=esc.moneda, sub_usd=esc.sub_usd)
        ctx = esc.armar(cta)
        srcs, kinds = _recetas_y_registros(cta.uid)
        # Control del fixture: el escenario tiene que tener de verdad lo que dice cubrir.
        self.assertTrue(esc.recetas <= srcs, f"{esc.nombre}: dice cubrir las recetas "
                        f"{sorted(esc.recetas)} pero en la cuenta hay {sorted(srcs)}")
        self.assertTrue(esc.registros <= kinds, f"{esc.nombre}: dice cubrir los registros "
                        f"{sorted(esc.registros)} pero en la cuenta hay {sorted(kinds)}")
        if renombrar:
            cta.renombrar()
            quedan = _apariciones(cta.uid, VIEJO)
            self.assertEqual(quedan, [], f"{esc.nombre}: después de renombrar, el nombre "
                             f"viejo sigue guardado en {len(quedan)} lugar(es):\n  "
                             + "\n  ".join(quedan))
        codigos = esc.actuar(cta, ctx)
        return codigos, cta.estado()

    def _diferencial(self, esc: Escenario):
        codigos_sin, estado_sin = self._correr(esc, renombrar=False)
        # Control del fixture: sin renombre, lo que se hace después tiene que andar.
        self.assertEqual(codigos_sin, [200] * len(codigos_sin),
                         f"{esc.nombre}: sin renombrar ya falla: {codigos_sin}")
        self.assertEqual(estado_sin["huerfanos"], [], f"{esc.nombre}: sin renombrar ya deja "
                         f"filas sin broker: {estado_sin['huerfanos']}")
        codigos_con, estado_con = self._correr(esc, renombrar=True)
        self.assertEqual(codigos_con, codigos_sin,
                         f"{esc.nombre}: con renombre las respuestas cambian")
        for clave in estado_sin:
            self.assertEqual(estado_con[clave], estado_sin[clave],
                             f"{esc.nombre}: con renombre cambia «{clave}»")


for _esc in ESCENARIOS:
    setattr(RenombrarYDespuesBorrar, f"test_{_esc.nombre}",
            (lambda e: lambda self: self._diferencial(e))(_esc))


class DosRenombresALaVez(unittest.TestCase):
    """Todo lo que reescribe el renombre busca "donde dice el nombre viejo". Si otro
    renombre del mismo broker se confirma entre que éste lee el nombre y toma el
    turno, el viejo ya no está en ningún lado: el broker quedaba con un nombre y sus
    filas y recetas con otro. Se simula exactamente ese orden: lo que dejó el otro
    pedido aparece justo cuando éste toma el turno."""

    def setUp(self):
        _sin_reconstruccion_de_fondo(self)

    def test_si_otro_renombre_entro_en_el_medio_frena_sin_tocar_nada(self):
        cta = _Cuenta()
        cta.depositar(1000)
        cta.posicion("GGAL", 1, 500)
        de_verdad = main._tomar_turno

        def el_otro_llego_antes(conn, uid):
            de_verdad(conn, uid)
            conn.execute("UPDATE brokers SET name='Otro nombre' WHERE id=?", (cta.bid,))
            conn.execute("UPDATE positions SET broker='Otro nombre' WHERE user_id=?", (cta.uid,))

        with mock.patch.object(main, "_tomar_turno", side_effect=el_otro_llego_antes):
            r = cta.pedir("put", f"/api/brokers/{cta.bid}", json={"name": NUEVO, "currency": "ARS"})
        self.assertEqual(r.status_code, 409, r.text)
        # Nada a medias: todo sigue como estaba (lo simulado vuelve atrás con el resto).
        self.assertEqual(cta.estado()["huerfanos"], [])
        self.assertEqual([b["name"] for b in cta.ok("get", "/api/brokers")], [VIEJO])

    def test_si_en_el_medio_aparecio_el_sub_broker_usd_tambien_frena(self):
        """Sin esto, el "· USD" creado entre la lectura y el turno quedaba con el
        nombre viejo del padre (y sus filas también)."""
        cta = _Cuenta()
        de_verdad = main._tomar_turno

        def crearon_el_usd(conn, uid):
            de_verdad(conn, uid)
            conn.execute("INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
                         "VALUES (?,?,?,?)", (cta.uid, VIEJO + SUB, "USDT", cta.bid))

        with mock.patch.object(main, "_tomar_turno", side_effect=crearon_el_usd):
            r = cta.pedir("put", f"/api/brokers/{cta.bid}", json={"name": NUEVO, "currency": "ARS"})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual([b["name"] for b in cta.ok("get", "/api/brokers")], [VIEJO])


class LaMedicionDeLoQueQuedoDeAntes(unittest.TestCase):
    """El chequeo del panel de admin (`/api/admin/check-invariantes`) que cuenta las
    recetas que quedaron con un nombre viejo ANTES de este arreglo. Se valida el
    instrumento con un caso plantado: el renombre como lo hacía antes (sólo las
    columnas) tiene que aparecer; el de ahora, no."""

    def setUp(self):
        _sin_reconstruccion_de_fondo(self)

    def _cuenta_con_receta_y_futuro(self):
        cta = _Cuenta()
        cta.depositar(100000)
        cta.posicion("GGAL", 10, 5000)
        cta.ok("post", "/api/futures", json={
            "broker": cta.nombre, "symbol": "BTCUSDT", "side": "long", "quantity": 1,
            "entry_price": 60000, "opened_at": "2026-08-05"})
        return cta

    def _chequeos(self, uid):
        from importing import invariantes as inv
        conn = main.get_db()
        try:
            return (inv.check_receta_con_broker_inexistente(conn, uid),
                    inv.check_futuro_abierto_sin_broker(conn, uid))
        finally:
            conn.close()

    def test_el_renombre_de_antes_aparece(self):
        cta = self._cuenta_con_receta_y_futuro()
        conn = main.get_db()
        try:
            conn.execute("UPDATE brokers SET name=? WHERE id=?", (NUEVO, cta.bid))
            for t in ("positions", "operations", "monthly_entries", "flujos_a_mano"):
                conn.execute(f"UPDATE {t} SET broker=? WHERE user_id=? AND broker=?",
                             (NUEVO, cta.uid, VIEJO))
            conn.commit()
        finally:
            conn.close()
        recetas, futuros = self._chequeos(cta.uid)
        self.assertEqual([(v["detalle"]["src"], v["detalle"]["nombres"],
                           v["detalle"]["fila_en_broker_vivo"]) for v in recetas],
                         [("manual_position", [VIEJO], True)])
        self.assertEqual([v["detalle"]["broker"] for v in futuros], [VIEJO])

    def test_el_renombre_de_ahora_no_deja_nada(self):
        cta = self._cuenta_con_receta_y_futuro()
        cta.renombrar()
        self.assertEqual(self._chequeos(cta.uid), ([], []))


# ── Cobertura: cada receta y cada registro de borrado del código tiene escenario ──
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# `"src": "..."` que NO son recetas de borrado (mismo nombre de clave, otra cosa).
_SRC_QUE_NO_SON_RECETAS = {
    "fci": "procedencia del precio de un fondo (fci_meta), no se guarda en ninguna fila",
}


def _fuentes_del_backend():
    for raiz, dirs, archivos in os.walk(_BACKEND):
        dirs[:] = [d for d in dirs if d not in ("tests", "scripts", "__pycache__", ".venv",
                                                 "venv", "node_modules")]
        for a in archivos:
            if a.endswith(".py"):
                with open(os.path.join(raiz, a), encoding="utf-8") as fh:
                    yield os.path.relpath(os.path.join(raiz, a), _BACKEND), fh.read()


# `"src": <variable>` (el tipo no es un texto fijo). Si la variable es una constante
# del módulo (dividendos.SRC) se resuelve importándolo; estas otras NO son recetas.
_SRC_VARIABLES_QUE_NO_SON_RECETAS = {
    ("main.py", "src"): "procedencia del precio de un activo (se sirve, no se guarda)",
    ("main.py", "snap_src"): "las filas del import que tocó una edición de posición "
                             "(clave `src` del registro, no un tipo de receta)",
    (os.path.join("importing", "invariantes.py"), "src"): "detalle de un chequeo de admin",
}


class CadaRecetaTieneSuEscenario(unittest.TestCase):
    def test_cada_tipo_de_receta_del_codigo_tiene_escenario(self):
        import importlib
        en_codigo, sin_leer = set(), []
        for ruta, texto in _fuentes_del_backend():
            en_codigo |= set(re.findall(r"""["']src["']\s*:\s*["'](\w+)["']""", texto))
            # El tipo escrito con una VARIABLE: la bandeja de dividendos usa
            # `"src": SRC` y la primera versión de este control no la vio.
            for nombre in set(re.findall(r"""["']src["']\s*:\s*([A-Za-z_]\w*)""", texto)):
                if (ruta, nombre) in _SRC_VARIABLES_QUE_NO_SON_RECETAS:
                    continue
                try:
                    valor = getattr(importlib.import_module(
                        ruta[:-3].replace(os.sep, ".")), nombre)
                except Exception:
                    valor = None
                if isinstance(valor, str):
                    en_codigo.add(valor)
                else:
                    sin_leer.append(f"{ruta}: \"src\": {nombre}")
        self.assertEqual(sin_leer, [], "Hay recetas cuyo tipo no pude leer (no es un texto "
                         "fijo ni una constante del módulo). Si es una receta de borrado, "
                         "dejá el tipo en una constante y agregá su Escenario; si no lo es, "
                         "sumala a _SRC_VARIABLES_QUE_NO_SON_RECETAS con el motivo.")
        en_codigo -= set(_SRC_QUE_NO_SON_RECETAS)
        cubiertas = set().union(*(e.recetas for e in ESCENARIOS))
        faltan = sorted(en_codigo - cubiertas)
        self.assertEqual(faltan, [],
                         f"Hay recetas de borrado sin escenario de renombre: {faltan}. "
                         "Si guardan un nombre de broker, el renombre lo tiene que cambiar: "
                         "agregá un Escenario que la cree, renombre y la use (y si la clave "
                         "no dice 'broker', sumala a renombre_broker.py).")

    def test_cada_tipo_de_registro_de_borrado_tiene_escenario(self):
        inserts = kinds = 0
        en_codigo = set()
        for _ruta, texto in _fuentes_del_backend():
            for m in re.finditer(r"INSERT INTO deleted_ops_journal", texto):
                inserts += 1
                k = re.search(r"""\(\s*uid\s*,\s*token\s*,\s*["'](\w+)["']""",
                              texto[m.end():m.end() + 400])
                if k:
                    kinds += 1
                    en_codigo.add(k.group(1))
        self.assertGreater(inserts, 0, "no encontré ningún registro de borrado: ¿cambió el SQL?")
        self.assertEqual(kinds, inserts, "hay un registro de borrado cuyo tipo no pude leer "
                         "(¿no es un texto fijo?): este control no sabe si tiene escenario")
        cubiertos = set().union(*(e.registros for e in ESCENARIOS))
        faltan = sorted(en_codigo - cubiertos)
        self.assertEqual(faltan, [],
                         f"Hay tipos de registro de borrado sin escenario de renombre: {faltan}")


# ── Esquema: toda columna de broker la cuida el renombre (o tiene su excepción) ──
_TABLAS_CON_BROKER_QUE_NO_SE_RENOMBRAN = {
    # El PROVEEDOR de la conexión automática ('wallbit'), no el nombre que puso el usuario.
    "user_broker_credentials",
}


class CadaColumnaDeBrokerSeRenombra(unittest.TestCase):
    def test_toda_tabla_con_columna_de_broker_esta_en_la_lista(self):
        conn = main.get_db()
        try:
            tablas = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            con_broker = {}
            for t in tablas:
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")
                        if "broker" in r[1].lower() and r[1] != "parent_broker_id"]
                if cols:
                    con_broker[t] = cols
        finally:
            conn.close()
        sueltas = sorted(t for t in con_broker
                         if t not in main.NAME_KEYED_TABLES
                         and t not in _TABLAS_CON_BROKER_QUE_NO_SE_RENOMBRAN
                         and t != "brokers")
        self.assertEqual(sueltas, [],
                         f"Tablas con columna de broker que el renombre no cambia: "
                         f"{ {t: con_broker[t] for t in sueltas} }. Sumalas a "
                         "NAME_KEYED_TABLES (main.py) o, si no guardan el nombre del broker "
                         "del usuario, a la lista de excepciones de este test con el motivo.")
        for t in main.NAME_KEYED_TABLES:
            self.assertEqual(con_broker.get(t), ["broker"],
                             f"{t} está en NAME_KEYED_TABLES pero su columna de broker no es "
                             f"'broker': {con_broker.get(t)}")


if __name__ == "__main__":
    unittest.main()
