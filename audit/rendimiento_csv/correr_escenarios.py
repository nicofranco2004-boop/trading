"""Matriz broker × escenario de discrepancia, por el camino de producción, contra la verdad.

  python3 correr_escenarios.py <salida.json> [broker ...] [--esc S0,S1,...]
"""
import json, sys
from datetime import date, timedelta
import arnes
from mercado import Mercado
from historia import historia_base
import generadores as g

FOTO = "2026-08-03"
HOY = date.today().isoformat()


def escenarios(m):
    """nombre → (historia verdadera, omitir del archivo, ajustar foto, hasta)"""
    base = historia_base(m)
    con_tin = historia_base(m); con_tin.tin("2024-03-05", "VIST", 60)
    post = historia_base(m, post_foto=True); post.dep("2026-09-01", 500_000)
    return {
        "S0_completo": (base, None, None, None),
        "S1_ventana_desde_2025": (base, lambda e: e.fecha < "2025-01-01", None, None),
        "S2_falta_una_venta": (base, lambda e: e.tipo == "SELL" and e.tk == "GGAL", None, None),
        "S3_titulos_de_otro_broker": (con_tin, lambda e: e.tipo == "TIN", None, None),
        "S4_faltan_cupones": (base, lambda e: e.tipo == "CUPON", None, None),
        "S5_movimientos_despues_de_la_foto": (post, None, None, None),
    }


MOV = {"balanz": (g.balanz_mov, "Balanz", "balanz_movimientos", "mov.xlsx"),
       "ieb": (g.ieb_mov, "IEB", "ieb", "actividad.xlsx"),
       "generico": (g.generico, "Generico", "rendi_generic", "mov.csv")}
FOTOS = {"balanz": (g.balanz_foto, "balanz_tenencia", "ResumenDeCuenta.pdf"),
         "ieb": (g.ieb_foto, "ieb_tenencia", "portafolio.xlsx")}


def medir_contra_verdad(h, mot):
    out = {}
    for modo, r in mot.items():
        vd, vh = r["ventana"]
        fila = {"rendi": r["twr_pct"], "ventana": [vd, vh], "motivo": r["motivo"],
                "publicable": r["publicable"]}
        if r["twr_pct"] is not None and vd:
            vh2 = HOY if (vh in (None, "hoy")) else vh
            fila["verdad_twr"] = round(h.twr_verdad(vd, vh2), 2)
            fila["error_pp"] = round(r["twr_pct"] - fila["verdad_twr"], 2)
            cv = h.contable_verdad(desde_mes=vd[:7], hasta_mes=vh2[:7])
            fila["verdad_contable"] = round(list(cv.values())[-1], 2) if cv else None
        out[modo] = fila
    return out


def main():
    salida = sys.argv[1]
    args = sys.argv[2:]
    esc_sel = None
    if "--esc" in args:
        i = args.index("--esc"); esc_sel = args[i + 1].split(","); args = args[:i] + args[i + 2:]
    brokers = args or list(MOV)
    m = Mercado()
    a = arnes.Arnes(m)
    import os
    res = json.load(open(salida)) if os.path.exists(salida) else {}
    for br in brokers:
        gen, broker, fmt, nombre = MOV[br]
        for esc, (h, omitir, ajustar, hasta) in escenarios(m).items():
            if esc_sel and not any(esc.startswith(x) for x in esc_sel):
                continue
            if br == "generico" and esc not in ("S0_completo",):
                continue
            if f"{br}|{esc}" in res:
                continue
            h.simular()
            uid = a.usuario(f"{br}_{esc}@rendi.test")
            extra = {"route_by_currency": "1"} if br == "generico" else None
            prev, conf = a.subir([(nombre, gen(h, omitir=omitir, hasta=hasta))], broker=broker, fmt=fmt, extra=extra)
            fila = {"uid": uid, "preview_status": prev.get("detail") or "ok",
                    "preview_summary": (prev.get("summary") or {}).get("by_operation_type"),
                    "errors": prev.get("errors"),
                    "confirm": {k: (conf or {}).get(k) for k in ("ok", "post_proceso")}}
            fila["sin_foto"] = medir_contra_verdad(h, a.motor())
            if br in FOTOS:
                fgen, ffmt, fname = FOTOS[br]
                pv, cf = a.subir_foto(fname, fgen(h, FOTO, ajustar), broker, ffmt)
                fila["foto"] = {k: pv.get(k) for k in ("override", "foto_completa", "warnings", "fecha_usada",
                                                       "matched", "nothing_to_do", "message", "detail", "avisos_escala")}
                fila["foto"]["confirm_ok"] = (cf or {}).get("ok")
                fila["foto"]["sinteticas"] = a.q(
                    "SELECT n.date, n.broker, n.operation_type t, n.asset_symbol a, ROUND(n.quantity,4) q, "
                    "ROUND(n.gross_amount,2) g, n.currency c, n.transfer_out tout, substr(n.notes,1,50) nota "
                    "FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id "
                    "WHERE b.user_id=? AND b.parser_format LIKE '%tenencia%'", uid)
            ult = a.q("SELECT MAX(n.date) d FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id "
                      "WHERE b.user_id=? AND b.status='confirmed'", uid)[0]["d"]
            d0 = max(date.fromisoformat(ult[:10]), date.fromisoformat(FOTO)) + timedelta(days=1)
            fila["cron_dias"] = a.cron(d0, date.today())
            a.reconstruir()
            fila["final"] = medir_contra_verdad(h, a.motor())
            fila["snaps_por_origen"] = arnes.resumen(a)["snaps_por_origen"]
            fila["capital"] = a.q("SELECT year, month, ROUND(capital_final,2) cf, ROUND(deposits,2) dep, "
                                  "ROUND(withdrawals,2) wd, ROUND(pnl_realized,2) pnl FROM monthly_entries "
                                  "WHERE user_id=? AND broker='global' ORDER BY year, month", uid)
            fila["cf_sin_cobros"] = medir_contra_verdad(h, {k: v for k, v in arnes.contrafactico_sin_cobros(a).items()
                                                            if k in ("certero", "estimado")})
            res[f"{br}|{esc}"] = fila
            fc, fe = fila["final"]["certero"], fila["final"]["estimado"]
            print(f"{br:8s} {esc:34s} CERT {fc['rendi']} vs {fc.get('verdad_twr')} [{fc['ventana'][0]}] {fc['motivo'] or ''} | "
                  f"EST {fe['rendi']} vs twr {fe.get('verdad_twr')} / cont {fe.get('verdad_contable')} [{fe['ventana'][0]}] {fe['motivo'] or ''}",
                  flush=True)
            json.dump(res, open(salida, "w"), ensure_ascii=False, default=str, indent=1)
    print("red bloqueada:", sorted(set(arnes.RED_BLOQUEADA))[:10])


if __name__ == "__main__":
    main()
