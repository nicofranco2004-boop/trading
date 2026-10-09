"""Prueba al azar de los borrados: ¿cada foto diaria pierde EXACTAMENTE lo que tenía
de lo borrado, y nada más?

Por qué existe. `main._cambio_de_aportado` le saca a cada foto ya escrita sólo lo que
el borrado le cambió, y sólo a las fotos que tenían lo borrado. Las pruebas armadas a
mano (`tests/test_borrar_conserva_el_dia.py`) fijan casos conocidos; ésta mezcla al
azar lo que hace la gente y cuenta cuántas fotos quedan mal. La versión anterior
(`sonda8_azar.py`, sesión xenodochial-allen, 2026-10-08) vivía en una carpeta temporal
y se perdió: ésta vive en el repo.

Cada escenario es una cuenta nueva que vive unos 80-100 días (desde el 1-ene-2026).
Cada día, en orden de hora (hora argentina):
  · 00:00 el cron externo saca la foto del día (el estado al EMPEZAR el día);
  · durante el día, al azar: imports (con su día de confirmación), depósitos y retiros
    a mano por el botón (`POST /api/cash/flow`, con fecha propia, a veces atrasada),
    posiciones a mano en un broker sin saldo (autodepósito), ediciones de /mensual
    (de un broker —es plata a mano— o de la pestaña Global —que el próximo recálculo
    pisa—) y visitas del Dashboard, que pisan el aportado de la foto del día;
  · 23:59 el cron interno, que a veces no corre (Railway dormido).
El último día, a las 15:00, se borra algo al azar (un depósito/retiro importado, el
renglón de depósitos a mano de un mes, o una posición a mano) y, a veces, se deshace.

LA VERDAD la sabe la prueba porque decide ella cuándo entra cada cosa: anota, en cada
escritura de cada foto, qué movimientos estaban en las cuentas que sumó el cron. Una
foto correcta después del borrado = lo que anotó − lo borrado SI lo tenía. Después de
deshacer = lo que anotó. Y se controla a sí misma: si el número que escribió el cron no
es la suma de lo que ella cree que había, el escenario cuenta como "arnés inconsistente"
y no se mide (un error de la prueba no puede pasar por error de la app).

Se miden sólo las fotos DIARIAS (cron o Dashboard) anteriores al día del borrado (la de
hoy la borra la cascada a propósito). El mercado no importa: sólo `net_deposited`.

Uso (desde backend/):
    python3 scripts/prueba_azar_borrados.py --escenarios 1000 --modo distintos --procesos 8
    python3 scripts/prueba_azar_borrados.py --escenarios 1000 --modo repetidos --procesos 8
  --modo distintos: montos al azar con centavos (casi nunca dos iguales).
  --modo repetidos: montos de 1.000 / 2.000 / 3.000 / 5.000 (a propósito iguales).
  --semilla N: corre sólo el escenario N y muestra el detalle (para depurar).
  --salida archivo.json: guarda el resultado de cada escenario.

⚠️ Cada proceso usa su propia base temporal (DB_PATH se fija ANTES de importar main:
`import main` sin eso escribe en backend/trading.db).
"""
import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)

INICIO = date(2026, 1, 1)
BROKER = "IBKR"          # el de los depósitos/retiros (botón e imports)
BROKER_POS = "MANUAL"    # el de las posiciones a mano: sin saldo → autodepósito
ACTIVOS = ["KO", "PEP", "MCD", "JNJ", "PG", "WMT", "XOM", "CVX"]
HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


# ─── la cuenta simulada ──────────────────────────────────────────────────────

class Mundo:
    """Lo que la prueba sabe: cada movimiento (`comps`), si ya está en las cuentas que
    suma el cron (`reflejado`), y qué tenía cada foto cuando se escribió."""

    def __init__(self, main, mods, rnd: random.Random, modo: str):
        self.main, self.mods, self.rnd, self.modo = main, mods, rnd, modo
        self.conn = main.get_db()
        self.comps = {}          # cid -> dict(usd, reflejado, vivo, tipo, ym, ...)
        self.ruido_global = 0.0  # ediciones de la pestaña Global no pisadas todavía
        self.fotos = {}          # 'AAAA-MM-DD' -> dict(valor, tiene)
        self.inconsistencias = []
        self.posiciones = {}     # pid -> cid del autodepósito
        self._n = 0
        self.ahora = None        # datetime argentino simulado
        self.eventos = []

    # ── reloj ──
    def utc_txt(self) -> str:
        return (self.ahora + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")

    def hoy(self) -> str:
        return self.ahora.date().isoformat()

    def parches(self):
        """El día (y la hora) que ve la app mientras corre un evento."""
        from unittest import mock
        ps = [mock.patch.object(self.main, "_iso_today", return_value=self.hoy())]
        # Si la app guarda la hora de carga con un reloj propio (fase 1), que vea la
        # simulada. Antes de esa fase no existe y no se parcha nada.
        for nombre in ("_ahora_utc", "_ahora_utc_txt"):
            if hasattr(self.main, nombre):
                ps.append(mock.patch.object(self.main, nombre, return_value=self.utc_txt()))
        return ps

    def con_reloj(self, fn, *a, **k):
        ps = self.parches()
        for p in ps:
            p.start()
        try:
            return fn(*a, **k)
        finally:
            for p in reversed(ps):
                p.stop()

    # ── montos ──
    def monto(self, lo=100.0, hi=9000.0) -> float:
        if self.modo == "repetidos":
            return float(self.rnd.choice([1000, 2000, 3000, 5000]))
        return round(self.rnd.uniform(lo, hi), 2)

    def nuevo_cid(self, tipo) -> str:
        self._n += 1
        return f"{tipo}{self._n}"

    # ── lo que suma el cron ──
    def modelo(self) -> float:
        return round(sum(c["usd"] for c in self.comps.values()
                         if c["vivo"] and c["reflejado"]) + self.ruido_global, 4)

    def tiene(self) -> frozenset:
        return frozenset(k for k, c in self.comps.items() if c["vivo"] and c["reflejado"])

    def anotar_foto(self, quien: str):
        d = self.hoy()
        r = self.conn.execute("SELECT net_deposited FROM snapshots WHERE user_id=? AND date=?",
                              (self.uid, d)).fetchone()
        if r is None:
            return
        v = float(r["net_deposited"] or 0)
        m = self.modelo()
        if abs(v - m) > 0.01:
            self.inconsistencias.append(f"{d} {quien}: escribió {v:.2f}, la prueba esperaba {m:.2f}")
        self.fotos[d] = {"valor": v, "tiene": self.tiene(), "quien": quien}

    def recalculo(self):
        """Lo que hace el recálculo con las cuentas que suma el cron: lo editado en
        Global desaparece y lo editado en un broker aparece."""
        self.ruido_global = 0.0
        for c in self.comps.values():
            if c["vivo"]:
                c["reflejado"] = True


def _armar_cuenta(main, semilla: int):
    conn = main.get_db()
    # Las tablas que apuntan a `users` no dejan borrar al usuario si se borran en otro
    # orden: durante la limpieza se apaga ese control.
    conn.execute("PRAGMA foreign_keys=OFF")
    tablas = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
    for t in tablas:
        try:
            conn.execute(f"DELETE FROM {t}")
        except Exception:
            pass
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")
    uid = conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                       (f"azar{semilla}@rendi.test", "x")).lastrowid
    for b in (BROKER, BROKER_POS):
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (uid, b, "USDT"))
    conn.commit()
    conn.close()
    return uid


# ─── los eventos ─────────────────────────────────────────────────────────────

def _importar(w: Mundo, fecha: str, tipo: str, monto: float):
    """Importa una fila por el mismo camino que la app y fecha la confirmación con la
    hora simulada (en producción la escribe `persist_batch` con `datetime('now')`)."""
    main, (pl, ps, rb) = w.main, w.mods
    csv = (HDR + f"{fecha},{tipo},{BROKER},,,,{monto:.2f},,,0,USD,\n").encode()

    def _go():
        with w.conn:
            payload = pl.run_preview(w.conn, uid=w.uid, file_bytes=csv, file_name="x.csv",
                                     broker_hint=BROKER, parser_format="rendi_generic")
        sid = payload["session_id"]
        h = main._ImportHelpers()
        for n in ("_adjust_broker_cash", "_update_monthly_pnl_realized",
                  "_update_monthly_flow", "_repair_monthly_chain", "_ensure_usd_sibling",
                  "_recalc_pnl_realized_from_ops"):
            setattr(h, n, getattr(main, n))
        with w.conn:
            txs, raw = pl.load_session_for_confirm(w.conn, uid=w.uid, session_id=sid)
            ps.persist_batch(w.conn, uid=w.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=h)
            rb.rebuild_fifo_after_import(w.conn, w.uid, sid,
                                         tc_blue=ps._read_tc_blue(w.conn, uid=w.uid))
            main._recalc_pnl_realized_from_ops(w.conn, w.uid)
        with w.conn:
            w.conn.execute("UPDATE import_batches SET confirmed_at=? WHERE id=?",
                           (w.utc_txt(), sid))
        return sid
    sid = w.con_reloj(_go)
    filas = w.conn.execute(
        f"SELECT n.id, n.operation_type FROM {main.TX_VIVAS} WHERE n.batch_id=? AND b.user_id=?",
        (sid, w.uid)).fetchall()
    w.recalculo()     # el import recalcula: lo editado en Global se va
    for f in filas:
        if f["operation_type"] in ("DEPOSIT", "WITHDRAW"):
            cid = f"tx-{f['id']}"
            signo = 1 if f["operation_type"] == "DEPOSIT" else -1
            w.comps[cid] = {"usd": signo * monto, "reflejado": True, "vivo": True,
                            "tipo": "imp", "ym": fecha[:7], "fecha": fecha}
    return bool(filas)


def _fecha_mov(w: Mundo, atraso_max=40, p_atraso=0.25) -> str:
    d = w.ahora.date()
    if w.rnd.random() < p_atraso:
        d = max(date(2025, 12, 1), d - timedelta(days=w.rnd.randint(1, atraso_max)))
    return d.isoformat()


def ev_deposito_importado(w: Mundo):
    r = w.rnd.random()
    d = w.ahora.date()
    if r < 0.2:      # un resumen que llega tarde
        d = max(date(2025, 12, 1), d - timedelta(days=w.rnd.randint(1, 40)))
    elif r < 0.3:    # liquidación: fechado días después de importarlo
        d = d + timedelta(days=w.rnd.randint(1, 3))
    tipo = "DEPOSITO" if w.rnd.random() < 0.75 else "RETIRO"
    m = w.monto()
    if _importar(w, d.isoformat(), tipo, m):
        w.eventos.append(f"{w.ahora:%m-%d %H:%M} import {tipo} {m} fechado {d}")


def ev_flujo_a_mano(w: Mundo, direccion: str):
    fecha = _fecha_mov(w)
    m = w.monto()
    r = w.con_reloj(w.client.post, "/api/cash/flow", json={
        "broker_name": BROKER, "direction": direccion, "amount": m, "date": fecha})
    if r.status_code != 200:
        return    # retiro sin saldo: la app lo rechaza y no pasó nada
    cid = w.nuevo_cid("mano")
    w.comps[cid] = {"usd": m if direccion == "deposit" else -m, "reflejado": True,
                    "vivo": True, "tipo": "mano", "ym": fecha[:7], "fecha": fecha,
                    "dir": "dep" if direccion == "deposit" else "wit", "broker": BROKER,
                    # su renglón propio en Movimientos (desde 2026-10-09), si lo tiene
                    "flujo_id": (r.json() or {}).get("flujo_id")}
    w.eventos.append(f"{w.ahora:%m-%d %H:%M} a mano {direccion} {m} fechado {fecha}")


def ev_posicion_a_mano(w: Mundo):
    fecha = _fecha_mov(w, atraso_max=30, p_atraso=0.3)
    m = w.monto(200, 6000)
    activo = w.rnd.choice(ACTIVOS)
    r = w.con_reloj(w.client.post, "/api/positions", json={
        "broker": BROKER_POS, "asset": activo, "buy_price": 50.0,
        "quantity": round(m / 50.0, 6), "invested": m, "entry_date": fecha})
    if r.status_code != 200:
        return
    pid = r.json()["id"]
    meta = w.conn.execute("SELECT undo_meta_json FROM positions WHERE id=?", (pid,)).fetchone()
    ad = (json.loads(meta["undo_meta_json"] or "{}").get("autodep") or {})
    usd = float(ad.get("usd") or 0)
    if usd <= 0:
        return
    cid = w.nuevo_cid("pos")
    w.comps[cid] = {"usd": usd, "reflejado": True, "vivo": True, "tipo": "autodep",
                    "ym": fecha[:7], "fecha": fecha, "broker": BROKER_POS}
    w.posiciones[pid] = cid
    w.eventos.append(f"{w.ahora:%m-%d %H:%M} posición a mano {activo} {usd} fechada {fecha}")


def ev_editar_mensual(w: Mundo, broker: str):
    """Sumarle a mano un depósito a un renglón de /mensual del mes en curso."""
    y, mth = w.ahora.year, w.ahora.month
    row = w.conn.execute(
        "SELECT * FROM monthly_entries WHERE user_id=? AND broker=? AND year=? AND month=?",
        (w.uid, broker, y, mth)).fetchone()
    if not row:
        return
    m = w.monto(100, 3000)
    body = {"year": y, "month": mth, "broker": broker,
            "deposits": float(row["deposits"] or 0) + m,
            "withdrawals": float(row["withdrawals"] or 0),
            "pnl_realized": float(row["pnl_realized"] or 0),
            "pnl_unrealized": max(0.0, float(row["pnl_unrealized"] or 0)),
            "capital_inicio": max(0.0, float(row["capital_inicio"] or 0)),
            "capital_final": max(0.0, float(row["capital_final"] or 0) + m)}
    import snapshots_job
    vio_antes = snapshots_job.compute_net_deposited_db(w.conn, w.uid)
    r = w.con_reloj(w.client.put, f"/api/monthly/{row['id']}", json=body)
    if r.status_code != 200:
        return
    # ¿Lo ve ya el cron? (Antes de 2026-10-09 la edición de un broker llegaba a
    # Global recién con el próximo recálculo; desde entonces, en el momento.) Se mide
    # en vez de suponerlo: así la prueba sirve con las dos versiones.
    vio = abs(snapshots_job.compute_net_deposited_db(w.conn, w.uid) - vio_antes - m) <= 0.01
    if broker == "global":
        w.ruido_global += m      # lo ve el cron hasta el próximo recálculo
        w.eventos.append(f"{w.ahora:%m-%d %H:%M} /mensual Global +{m}")
    else:
        cid = w.nuevo_cid("mens")
        # Plata a mano del broker: el cron (que suma Global) la ve recién cuando un
        # recálculo rearma Global con la suma de los brokers.
        w.comps[cid] = {"usd": m, "reflejado": vio, "vivo": True, "tipo": "mano",
                        "ym": f"{y:04d}-{mth:02d}", "fecha": None, "dir": "dep",
                        "broker": broker}
        w.eventos.append(f"{w.ahora:%m-%d %H:%M} /mensual {broker} +{m}")


def ev_visita_dashboard(w: Mundo):
    import snapshots_job
    nd = snapshots_job.compute_net_deposited_db(w.conn, w.uid)
    r = w.con_reloj(w.client.post, "/api/snapshots", json={
        "total_value": max(nd, 0.0), "total_invested": max(nd, 0.0), "net_deposited": nd})
    if r.status_code == 200:
        w.anotar_foto("dashboard")


def ev_cron(w: Mundo, quien: str):
    import snapshots_job
    from unittest import mock
    with mock.patch.object(snapshots_job, "fetch_prices_for_symbols",
                           side_effect=lambda syms, cy, *a, **k: {s: 50.0 for s in syms}):
        with w.conn:
            res = snapshots_job.take_snapshot_for_user(w.conn, w.uid, 1200, {}, w.hoy(),
                                                       tc_mep=1200)
    if res.get("ok"):
        w.anotar_foto(quien)


# ─── el borrado y la medición ────────────────────────────────────────────────

def _fotos_servidas(w: Mundo, hasta: str) -> dict:
    return {r["date"]: float(r["net_deposited"] or 0) for r in w.conn.execute(
        "SELECT date, net_deposited, source FROM snapshots WHERE user_id=? AND date < ? "
        "AND source IN ('cron', 'browser')", (w.uid, hasta)).fetchall()}


def _contar_mal(w: Mundo, esperado: dict, servido: dict):
    mal = []
    for d, e in sorted(esperado.items()):
        s = servido.get(d)
        if s is None or abs(s - e) > 0.01:
            mal.append((d, round(e, 2), None if s is None else round(s, 2)))
    return mal


def _elegir_borrado(w: Mundo):
    """(tipo, id para la app, componentes que se lleva)."""
    opciones = []
    imp = [k for k, c in w.comps.items() if c["vivo"] and c["tipo"] == "imp"]
    if imp:
        k = w.rnd.choice(imp)
        opciones.append((0.35, ("importado", k, [k])))
    meses = {}
    for k, c in w.comps.items():
        if c["vivo"] and c["tipo"] == "mano" and c.get("broker") == BROKER:
            meses.setdefault((c["ym"], c["dir"]), []).append(k)
    if meses:
        (ym, d), ks = w.rnd.choice(sorted(meses.items()))
        row = w.conn.execute(
            "SELECT id FROM monthly_entries WHERE user_id=? AND broker=? AND year=? AND month=?",
            (w.uid, BROKER, int(ym[:4]), int(ym[5:7]))).fetchone()
        if row:
            opciones.append((0.40, ("a mano (mes)", f"me-{row['id']}-{d}", ks)))
    sueltas = [k for k, c in w.comps.items() if c["vivo"] and c.get("flujo_id")]
    if sueltas:
        k = w.rnd.choice(sueltas)
        opciones.append((0.30, ("una carga a mano", f"mf-{w.comps[k]['flujo_id']}", [k])))
    vivas = [p for p, cid in w.posiciones.items() if w.comps[cid]["vivo"]]
    if vivas:
        p = w.rnd.choice(vivas)
        opciones.append((0.25, ("posición a mano", f"pos:{p}", [w.posiciones[p]])))
    if not opciones:
        return None
    tot = sum(p for p, _ in opciones)
    x = w.rnd.random() * tot
    for p, o in opciones:
        x -= p
        if x <= 0:
            return o
    return opciones[-1][1]


def correr_escenario(main, mods, semilla: int, modo: str, detalle=False) -> dict:
    rnd = random.Random(semilla * 7919 + (1 if modo == "repetidos" else 0))
    uid = _armar_cuenta(main, semilla)
    w = Mundo(main, mods, rnd, modo)
    w.uid = uid
    from fastapi.testclient import TestClient
    main.app.dependency_overrides[main.get_effective_user] = lambda: uid
    w.client = TestClient(main.app)
    out = {"semilla": semilla, "modo": modo}
    try:
        dias = rnd.randint(75, 105)
        fin = INICIO + timedelta(days=dias)
        # Día 1: el depósito inicial, importado a las 9.
        w.ahora = datetime(2026, 1, 1, 9, 0)
        _importar(w, "2026-01-01", "DEPOSITO", w.monto(20000, 80000) if modo == "distintos"
                  else 50000.0)
        # Los eventos del período, a horas al azar.
        n_ev = rnd.randint(8, 18)
        tipos = ([ev_deposito_importado] * 22 + [lambda w: ev_flujo_a_mano(w, "deposit")] * 26
                 + [lambda w: ev_flujo_a_mano(w, "withdraw")] * 10 + [ev_posicion_a_mano] * 12
                 + [lambda w: ev_editar_mensual(w, BROKER)] * 4
                 + [lambda w: ev_editar_mensual(w, "global")] * 4)
        agenda = []
        for _ in range(n_ev):
            d = INICIO + timedelta(days=rnd.randint(1, dias))
            if d == fin:
                h = rnd.randint(8, 14)        # el último día, antes del borrado
            else:
                h = rnd.randint(8, 23)
            agenda.append((datetime(d.year, d.month, d.day, h, rnd.randint(0, 59)),
                           0, rnd.choice(tipos)))
        dia = INICIO
        while dia <= fin:
            if dia > INICIO:
                agenda.append((datetime(dia.year, dia.month, dia.day, 0, 0), -1,
                               lambda w: ev_cron(w, "cron 00:00")))
            if rnd.random() < 0.35:
                hv = rnd.randint(8, 23 if dia < fin else 14)
                agenda.append((datetime(dia.year, dia.month, dia.day, hv, rnd.randint(0, 59)), 1,
                               ev_visita_dashboard))
            if dia < fin and rnd.random() < 0.75:
                agenda.append((datetime(dia.year, dia.month, dia.day, 23, 59), 2,
                               lambda w: ev_cron(w, "cron 23:59")))
            dia += timedelta(days=1)
        agenda.sort(key=lambda t: (t[0], t[1]))
        for cuando, _, fn in agenda:
            w.ahora = cuando
            fn(w)

        # El borrado, el último día a las 15.
        w.ahora = datetime(fin.year, fin.month, fin.day, 15, 0)
        hoy = w.hoy()
        elegido = _elegir_borrado(w)
        if elegido is None:
            out["saltado"] = "nada para borrar"
            return out
        tipo, mid, ks = elegido
        out["tipo"] = tipo
        out["inconsistencias"] = len(w.inconsistencias)
        if w.inconsistencias:
            out["saltado"] = "arnés inconsistente"
            out["inconsistencias_detalle"] = w.inconsistencias[:5]
            return out
        if mid.startswith("pos:"):
            r = w.con_reloj(w.client.delete, f"/api/positions/{mid[4:]}")
        else:
            r = w.con_reloj(w.client.delete, f"/api/movements/{mid}")
        if r.status_code != 200:
            out["saltado"] = f"la app no dejó borrar: {r.status_code} {r.text[:120]}"
            return out
        token = (r.json() or {}).get("undo_token")
        quita = {k: w.comps[k]["usd"] for k in ks}
        # Control de la CONTABILIDAD (no de las fotos): después del borrado, lo que
        # suma el cron tiene que ser todo lo vivo menos lo borrado. Si no da, el
        # problema está en las cuentas (p. ej. un capital de arranque heredado de un
        # renglón borrado), no en cómo se corrigieron las fotos: se cuenta aparte.
        import snapshots_job
        for k in ks:
            w.comps[k]["vivo"] = False
        cuentas = snapshots_job.compute_net_deposited_db(w.conn, w.uid)
        debia = sum(c["usd"] for c in w.comps.values() if c["vivo"])
        for k in ks:
            w.comps[k]["vivo"] = True
        if abs(cuentas - debia) > 0.01:
            out["contabilidad_distinta"] = round(cuentas - debia, 2)
        esperado = {d: f["valor"] - sum(u for k, u in quita.items() if k in f["tiene"])
                    for d, f in w.fotos.items() if d < hoy}
        servido = _fotos_servidas(w, hoy)
        mal = _contar_mal(w, esperado, servido)
        # Rasgos del escenario, para separar los errores por causa.
        dias_carga = {}
        for e in w.eventos:
            if " a mano " in e or "posición a mano" in e:
                dias_carga[e[:5]] = dias_carga.get(e[:5], 0) + 1
        out["rasgos"] = {
            "componentes": len(ks),
            "con_mensual": any(k.startswith("mens") for k in ks),
            "nunca_visto": any(not any(k in f["tiene"] for f in w.fotos.values()) for k in ks),
            "global_editado": any("/mensual Global" in e for e in w.eventos),
            "dos_cargas_mismo_dia": any(v > 1 for v in dias_carga.values()),
        }
        out.update({"fotos": len(esperado), "mal_borrar": len(mal),
                    "toca": sum(1 for d, f in w.fotos.items() if d < hoy
                                and any(k in f["tiene"] for k in ks)),
                    "ejemplos": mal[:4]})
        if token and rnd.random() < 0.5:
            r = w.con_reloj(w.client.post, f"/api/operations/undo/{token}")
            if r.status_code == 200:
                esperado2 = {d: f["valor"] for d, f in w.fotos.items() if d < hoy}
                mal2 = _contar_mal(w, esperado2, _fotos_servidas(w, hoy))
                out.update({"mal_deshacer": len(mal2), "ejemplos_deshacer": mal2[:4]})
            else:
                out["deshacer_rechazado"] = r.status_code
        if detalle:
            out["eventos"] = w.eventos
            out["borrado"] = {"mid": mid, "quita": quita}
        return out
    except Exception as ex:   # un escenario roto no tumba la tanda: se cuenta aparte
        import traceback
        out["error"] = f"{type(ex).__name__}: {ex}"
        out["traza"] = traceback.format_exc()[-1500:]
        return out
    finally:
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        w.conn.close()


# ─── tanda en un proceso / en varios ─────────────────────────────────────────

def _cargar_app():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["DB_PATH"] = tmp.name
    sys.path.insert(0, BACKEND)
    import logging
    logging.disable(logging.CRITICAL)
    import main
    from importing import pipeline as pl, persister as ps, rebuild as rb
    from unittest import mock
    # Igual que los tests: la reconstrucción a mercado en otro hilo se apaga (sólo
    # reescribe cierres reconstruidos, nunca una foto del cron).
    for nombre in ("_reconstruir_mtm_post_import", "_reconstruir_en_fila"):
        if hasattr(main, nombre):
            mock.patch.object(main, nombre, side_effect=lambda *a, **k: None).start()
    return main, (pl, ps, rb), tmp.name


def _resumen(res: list) -> str:
    medidos = [r for r in res if "mal_borrar" in r]
    lineas = [f"escenarios: {len(res)} · medidos: {len(medidos)} · "
              f"saltados: {sum(1 for r in res if 'saltado' in r)} · "
              f"rotos (excepción): {sum(1 for r in res if 'error' in r)}"]
    inc = sum(1 for r in res if r.get("saltado") == "arnés inconsistente")
    lineas.append(f"  arnés inconsistente: {inc}")
    cd = [r for r in medidos if "contabilidad_distinta" in r]
    lineas.append(f"  contabilidad distinta después del borrado (aparte, no se miden): {len(cd)}")
    medidos = [r for r in medidos if "contabilidad_distinta" not in r]
    for tipo in ("importado", "a mano (mes)", "una carga a mano", "posición a mano", None):
        rs = [r for r in medidos if tipo is None or r["tipo"] == tipo]
        if not rs:
            continue
        nombre = tipo or "TOTAL"
        con_err = sum(1 for r in rs if r["mal_borrar"] > 0)
        lineas.append(f"  {nombre:16s} escenarios {len(rs):4d} · con alguna foto mal "
                      f"{con_err:4d} · fotos mal {sum(r['mal_borrar'] for r in rs):6d} "
                      f"de {sum(r['fotos'] for r in rs)} "
                      f"(tenían lo borrado: {sum(r['toca'] for r in rs)})")
    des = [r for r in medidos if "mal_deshacer" in r]
    if des:
        lineas.append(f"  deshacer: {len(des)} · con alguna foto mal "
                      f"{sum(1 for r in des if r['mal_deshacer'] > 0)} · fotos mal "
                      f"{sum(r['mal_deshacer'] for r in des)}")
    return "\n".join(lineas)


def main_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--escenarios", type=int, default=100)
    ap.add_argument("--desde", type=int, default=0)
    ap.add_argument("--modo", choices=("distintos", "repetidos"), default="distintos")
    ap.add_argument("--procesos", type=int, default=1)
    ap.add_argument("--semilla", type=int, default=None)
    ap.add_argument("--salida", default=None)
    a = ap.parse_args()

    if a.semilla is not None:
        main, mods, db = _cargar_app()
        r = correr_escenario(main, mods, a.semilla, a.modo, detalle=True)
        print(json.dumps(r, indent=1, ensure_ascii=False, default=str))
        return

    if a.procesos > 1:
        t0 = time.time()
        por = -(-a.escenarios // a.procesos)
        hijos, archivos = [], []
        for i in range(a.procesos):
            d = a.desde + i * por
            n = min(por, a.desde + a.escenarios - d)
            if n <= 0:
                break
            f = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name
            archivos.append(f)
            hijos.append(subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), "--escenarios", str(n),
                 "--desde", str(d), "--modo", a.modo, "--salida", f], cwd=BACKEND))
        for h in hijos:
            h.wait()
        res = []
        for f in archivos:
            try:
                res += json.load(open(f))
            except (OSError, ValueError):
                print(f"⚠️ un proceso no dejó resultado: {f}")
        res.sort(key=lambda r: r["semilla"])
    else:
        t0 = time.time()
        main, mods, db = _cargar_app()
        res = [correr_escenario(main, mods, s, a.modo)
               for s in range(a.desde, a.desde + a.escenarios)]
    if a.salida:
        json.dump(res, open(a.salida, "w"), ensure_ascii=False, default=str)
    if a.procesos > 1 or not a.salida:
        print(f"modo {a.modo} · {time.time() - t0:.0f} s")
        print(_resumen(res))


if __name__ == "__main__":
    main_cli()
