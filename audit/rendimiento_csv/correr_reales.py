"""Corre los archivos REALES que subió el dueño por el arnés. Salidas a la carpeta
que se pase (NO al repo: son datos personales)."""
import json, os, sys
from datetime import date, timedelta
import arnes
from mercado import Mercado

DATOS, SALIDA = sys.argv[1], sys.argv[2]
os.makedirs(SALIDA, exist_ok=True)
CASOS = {
    "balanzA": {"mov": [("balanzA/movimientos_balanz.xlsx", "Balanz", "balanz_movimientos")]},
    "balanzB": {"mov": [("balanzB/movimientos_balanzB.xlsx", "Balanz", "balanz_movimientos")]},
    "ieb": {"mov": [("ieb/actividad.xlsx", "IEB", "ieb")],
            "foto": ("ieb/portafolio.xlsx", "IEB", "ieb_tenencia")},
}
solo = sys.argv[3:] or list(CASOS)
a = arnes.Arnes(Mercado())
for nombre in solo:
    caso = CASOS[nombre]
    uid = a.usuario(f"{nombre}@rendi.test")
    out = {"uploads": []}
    for rel, broker, fmt in caso["mov"]:
        b = open(os.path.join(DATOS, rel), "rb").read()
        prev, _ = a.subir([(os.path.basename(rel), b)], broker=broker, fmt=fmt, confirmar=False)
        txs = arnes.tx_confirmadas(a)  # aún vacío: el preview no confirma
        # precios observados en ESTE archivo (filas del preview)
        rows = a.q("SELECT n.* FROM import_normalized_tx n WHERE n.batch_id=?", prev["session_id"])
        if not rows:
            rows = [dict(date=r.get("date"), operation_type=r.get("operation_type"),
                         asset_symbol=r.get("asset_symbol"), unit_price=r.get("unit_price"),
                         quantity=r.get("quantity"), currency=r.get("currency"))
                    for r in prev.get("rows_preview", [])]
        m = arnes.mercado_de_archivo(rows)
        a.m = m; arnes._YahooFalso.mercado = m; arnes.bf._HIST_CACHE.clear()
        c = a.http.post("/api/imports/confirm", headers=a.h, json={"session_id": prev["session_id"]})
        a._esperar_mtm(uid)
        cj = arnes._json(c)
        out["uploads"].append({"archivo": rel, "status": c.status_code,
                               "preview_summary": prev.get("summary"),
                               "cash_warnings": len(prev.get("cash_warnings") or []),
                               "errors": prev.get("errors"),
                               "confirm": {k: cj.get(k) for k in ("ok", "post_proceso", "mtm_reconstruccion",
                                                                   "fx_migracion", "auto_skipped_duplicates")}})
    out["antes_de_foto"] = arnes.resumen(a)
    if caso.get("foto"):
        rel, broker, fmt = caso["foto"]
        pv, cf = a.subir_foto(os.path.basename(rel), open(os.path.join(DATOS, rel), "rb").read(), broker, fmt)
        out["foto"] = {"preview": {k: pv.get(k) for k in ("override", "foto_completa", "warnings", "fecha_usada",
                                                          "fecha_origen", "to_seed", "matched", "over",
                                                          "not_in_snapshot", "cash_trueup", "seed_total")},
                       "preview_keys": sorted(pv), "confirm_ok": (cf or {}).get("ok")}
        out["despues_de_foto"] = arnes.resumen(a)
    # cron desde el día siguiente al último movimiento hasta hoy
    ult = a.q("SELECT MAX(n.date) d FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id WHERE b.user_id=?", uid)[0]["d"]
    d0 = date.fromisoformat(ult[:10]) + timedelta(days=1)
    out["cron_dias"] = a.cron(d0, date.today())
    out["reconstruccion_post_cron"] = {k: v for k, v in a.reconstruir().items() if k != "months"}
    out["final"] = arnes.resumen(a)
    out["cf_sin_cobros"] = arnes.contrafactico_sin_cobros(a)
    json.dump(out, open(os.path.join(SALIDA, f"{nombre}.json"), "w"), ensure_ascii=False, default=str, indent=1)
    f = out["final"]["motor"]
    print(nombre, "uid", uid, "| certero", f["certero"]["twr_pct"], f["certero"]["ventana"], f["certero"]["motivo"],
          "| estimado", f["estimado"]["twr_pct"], f["estimado"]["ventana"], f["estimado"]["motivo"])
    print("   publicable certero", f["certero"]["publicable"], "\n   publicable estimado", f["estimado"]["publicable"])
    print("   snaps", out["final"]["snaps_por_origen"])
    cf = out["cf_sin_cobros"]
    print("   CF sin cobros: certero", cf["certero"]["twr_pct"], cf["certero"]["ventana"], "| estimado", cf["estimado"]["twr_pct"], cf["estimado"]["ventana"], "| mtm aptas", cf["mtm_aptas"])
print("red bloqueada:", sorted(set(arnes.RED_BLOQUEADA))[:15])
