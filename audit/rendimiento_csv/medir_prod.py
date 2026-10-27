"""Mide los hallazgos de AUDIT_rendimiento_desde_csv_2026-10-27.md sobre una copia de PRODUCCIÓN.

SÓLO LECTURA: abre la base con `?immutable=1`; nada de lo que hace puede escribir.

    cd backend && python3 ../audit/rendimiento_csv/medir_prod.py ~/Downloads/trading-AAAA-MM-DD.db [salida.json] [--max N]

Por usuario, en los dos modos: número publicado, ventana, motivo; y las señales de cada
hallazgo (H1 cobros que anulan cobertura, H2 serie partida, H4 contable descartada tras
una foto apta reconstruida, H5 costura que la guarda no ve, H6 cadena 'costo' mezclada,
H7 Certero que publica contable). Al final imprime la tabla de cobertura por modo y la
distribución Estimado − Certero sobre la MISMA ventana.
"""
import json
import os
import sqlite3
import statistics
import sys
import contextlib
import io

AQUI = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(AQUI, "..", "..", "backend"))
sys.path.insert(0, BACKEND)

ruta = os.path.expanduser(sys.argv[1])
salida = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
maximo = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else None

# `twr` no abre la base por su cuenta; se le pasa la conexión inmutable.
os.environ.setdefault("DB_PATH", "/nonexistent-para-que-nadie-abra-otra.db")
with contextlib.redirect_stdout(io.StringIO()):
    import twr  # noqa: E402

conn = sqlite3.connect(f"file:{ruta}?immutable=1", uri=True)
conn.row_factory = sqlite3.Row
COBROS = ("Dividendo", "Amortización", "Interés")


def _cols(t):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}


SNAP_COLS = _cols("snapshots")
TIENE_BASE = "base" in SNAP_COLS


def uno(uid):
    r = {"uid": uid}
    for modo in ("certero", "estimado"):
        try:
            c = twr.curva_indexada(conn, uid, modo=modo)
            r[modo] = {"pct": None if c.get("twr") is None else round(c["twr"] * 100, 2),
                       "desde": c.get("ventana_desde"), "hasta": c.get("ventana_hasta"),
                       "motivo": c.get("motivo"), "partida": bool(c.get("serie_partida")),
                       "contable_superado": c.get("contable_superado") or 0}
        except Exception as ex:
            r[modo] = {"error": repr(ex)[:160]}
    try:
        rp = twr.rendimiento_publicable(conn, uid, modo="certero")
        r["h7_certero_publica_contable"] = (rp.get("base") == "contable" and rp.get("pct") is not None)
        r["h7_pct"] = rp.get("pct")
    except Exception as ex:
        r["h7_error"] = repr(ex)[:120]
    # misma ventana: el Estimado medido entre las puntas del Certero
    ce = r.get("certero", {})
    if ce.get("pct") is not None and ce.get("desde"):
        try:
            hasta = None if ce["hasta"] == "hoy" else ce["hasta"]
            e2 = twr.curva_indexada(conn, uid, ce["desde"], hasta, modo="estimado")
            if e2.get("twr") is not None:
                r["est_misma_ventana"] = round(e2["twr"] * 100, 2)
                r["dif_est_menos_cert_pp"] = round(r["est_misma_ventana"] - ce["pct"], 2)
        except Exception as ex:
            r["misma_ventana_error"] = repr(ex)[:120]
    # señales en las fotos
    q = ("SELECT date, source, total_value v, net_deposited nd, mtm_coverage cob"
         + (", base, apto" if TIENE_BASE else "") + " FROM snapshots WHERE user_id=? ORDER BY date")
    fotos = [dict(x) for x in conn.execute(q, (uid,))]
    mtm = [f for f in fotos if f["source"] == "mtm_backfill"]
    r["mtm_n"] = len(mtm)
    r["mtm_cob_null"] = sum(1 for f in mtm if f["cob"] is None)
    r["mtm_cob_baja"] = sum(1 for f in mtm if f["cob"] is not None and f["cob"] < twr.COBERTURA_MEDICION)
    r["mtm_apta"] = sum(1 for f in mtm if f["cob"] is not None and f["cob"] >= twr.COBERTURA_MEDICION)
    # H6: la cadena 'costo' del Estimado mezcla filas contables (cob NULL → realineadas
    # a capital_final) con reconstrucciones parciales (cob < 0,90, valor con no realizado).
    r["h6_mezcla"] = r["mtm_cob_null"] > 0 and r["mtm_cob_baja"] > 0
    # H1: cobros en `operations` sin entry_date (los que anulan cobertura)
    try:
        r["h1_cobros_sin_entry"] = conn.execute(
            f"SELECT COUNT(*) FROM operations WHERE user_id=? AND entry_date IS NULL "
            f"AND op_type IN ({','.join('?' * len(COBROS))})", (uid, *COBROS)).fetchone()[0]
    except Exception:
        r["h1_cobros_sin_entry"] = None
    # H5: la costura reconstrucción → primer cron
    cron = [f for f in fotos if f["source"] == "cron"]
    if mtm and cron:
        primero = cron[0]
        antes = [f for f in mtm if f["date"] < primero["date"]]
        if antes:
            a = antes[-1]
            v0, v1 = float(a["v"] or 0), float(primero["v"] or 0)
            fl = float(primero["nd"] or 0) - float(a["nd"] or 0)
            base = v0 + fl
            r["h5_costura"] = {"desde": a["date"], "hasta": primero["date"], "v0": round(v0, 2), "v1": round(v1, 2),
                               "flujo": round(fl, 2),
                               "ratio_guarda": round(v1 / base, 3) if base > 0 else None,
                               "ratio_sin_flujo": round((v1 - fl) / v0, 3) if v0 > 0 else None,
                               "dietz_pct": round(100 * (v1 - v0 - fl) / (v0 + fl / 2), 2) if (v0 + fl / 2) > 0 else None}
            t = twr.RECONSTRUIDO_VS_MEDICION_MAX_VECES
            rg, rs = r["h5_costura"]["ratio_guarda"], r["h5_costura"]["ratio_sin_flujo"]
            r["h5_guarda_ciega"] = bool(rg and rs and (1 / t <= rg <= t) and not (1 / t <= rs <= t))
    # H4: la primera foto apta es una RECONSTRUCCIÓN y hay contabilidad descartada después
    r["h4_contable_descartada"] = (r.get("estimado", {}).get("contable_superado") or 0) > 0 and \
        bool(mtm and cron and any(f["cob"] is not None and f["cob"] >= twr.COBERTURA_MEDICION
                                  and f["date"] < cron[0]["date"] for f in mtm))
    return r


uids = [x[0] for x in conn.execute(
    "SELECT DISTINCT user_id FROM monthly_entries WHERE broker='global' ORDER BY user_id")]
if maximo:
    uids = uids[:maximo]
filas = []
for i, u in enumerate(uids):
    filas.append(uno(u))
    if (i + 1) % 50 == 0:
        print(f"... {i + 1}/{len(uids)}", file=sys.stderr, flush=True)


def _cuenta(pred):
    return sum(1 for f in filas if pred(f))


print(f"\nusuarios con contabilidad: {len(filas)}")
for modo in ("certero", "estimado"):
    con = _cuenta(lambda f: f.get(modo, {}).get("pct") is not None)
    err = _cuenta(lambda f: "error" in f.get(modo, {}))
    mot = {}
    for f in filas:
        x = f.get(modo, {})
        if x.get("pct") is None and "error" not in x:
            mot[x.get("motivo")] = mot.get(x.get("motivo"), 0) + 1
    print(f"[{modo}] con número: {con} · sin número: {len(filas) - con - err} · error: {err}")
    for k, v in sorted(mot.items(), key=lambda kv: -kv[1]):
        print(f"     {v:5d}  {k}")
difs = [f["dif_est_menos_cert_pp"] for f in filas if f.get("dif_est_menos_cert_pp") is not None]
if difs:
    difs.sort()
    print(f"\nEstimado − Certero, MISMA ventana ({len(difs)} usuarios): mediana {statistics.median(difs):.2f} pp · "
          f"p10 {difs[len(difs) // 10]:.2f} · p90 {difs[(9 * len(difs)) // 10]:.2f} · min {difs[0]:.2f} · max {difs[-1]:.2f}")
    print(f"   Estimado ARRIBA del Certero (contra el diseño, > +1 pp): {sum(1 for d in difs if d > 1)}")
print("\nseñales por hallazgo (usuarios):")
print(f"   H1 con cobros sin entry_date en operations:      {_cuenta(lambda f: (f.get('h1_cobros_sin_entry') or 0) > 0)}")
print(f"      y con fotos reconstruidas de cobertura NULL:  {_cuenta(lambda f: (f.get('h1_cobros_sin_entry') or 0) > 0 and f['mtm_cob_null'] > 0)}")
print(f"   H2 Certero sin número por serie partida:         {_cuenta(lambda f: f.get('certero', {}).get('motivo') == 'serie_partida' and f['certero'].get('pct') is None)}")
print(f"   H4 Estimado descarta contabilidad tras foto apta reconstruida: {_cuenta(lambda f: f.get('h4_contable_descartada'))}")
print(f"   H5 costura que la guarda no ve:                  {_cuenta(lambda f: f.get('h5_guarda_ciega'))}")
print(f"   H6 cadena 'costo' mezclada (NULL + parcial):     {_cuenta(lambda f: f.get('h6_mezcla'))}")
print(f"   H7 Certero que publica contable:                 {_cuenta(lambda f: f.get('h7_certero_publica_contable'))}")
if salida:
    json.dump(filas, open(salida, "w"), ensure_ascii=False, default=str, indent=1)
    print(f"\ndetalle por usuario → {salida}")
