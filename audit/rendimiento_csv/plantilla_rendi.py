"""La PLANTILLA de Rendi (formato `rendi_generic`): qué pasa con el rendimiento cuando la
persona carga su historia a mano, con la plantilla que se descarga del importador.

  python3 plantilla_rendi.py <salida.json> [--solo movimientos|escenarios]

Dos partes, por el camino de producción (vista previa y confirm HTTP, reconstrucción,
cron real) con el mercado inventado de la auditoría:

  1. MOVIMIENTOS — cada tipo de movimiento escrito como lo escribiría una persona, en una
     cuenta chica propia (depósito + el movimiento). Se lee lo que dejó el importador:
     filas de la vista previa, errores, tenencia, caja por sub-cuenta y operaciones.
  2. ESCENARIOS — el inversor inventado de la auditoría escrito en la plantilla, con las
     variantes que aparecen al cargarla a mano (sin depósitos, sin el dólar MEP, sin
     cupones, arrancando en 2025, con números a la argentina…), contra el rendimiento
     VERDADERO de la misma ventana. Con y sin la foto de tenencia del broker.
"""
import csv
import io
import json
import sys
from datetime import date, timedelta

import arnes
import correr_escenarios as ce
from mercado import Mercado
from historia import historia_base
import generadores as g

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas"
DEP = "2026-01-05,DEPOSITO,MiBroker,,,,1000000,,,,ARS,"

# (nombre, qué se espera en castellano, filas además del depósito inicial)
MOVIMIENTOS = [
    ("compra_ars_con_comision", "tenencia 100 GGAL a costo 150.010; caja −150.010",
     ["2026-01-07,COMPRA,MiBroker,GGAL,100,1500,,,,10,ARS,"]),
    ("compra_con_monto_sin_precio", "100 GGAL a costo 150.000",
     ["2026-01-07,COMPRA,MiBroker,GGAL,100,,150000,,,,ARS,"]),
    ("venta_ars_con_comision", "venta 60 GGAL a 1.900 − 8 de comisión: caja +113.992",
     ["2026-01-07,COMPRA,MiBroker,GGAL,100,1500,,,,0,ARS,",
      "2026-02-09,VENTA,MiBroker,GGAL,60,1900,,,,8,ARS,"]),
    ("venta_sin_compra", "vende algo que la plantilla no dice que compró (H5-a)",
     ["2026-02-09,VENTA,MiBroker,YPFD,10,30000,,,,0,ARS,"]),
    ("deposito_usd", "500 US$ en la sub-cuenta en dólares",
     ["2026-01-06,DEPOSITO,MiBroker,,,,500,,,,USD,"]),
    ("compra_cedear_en_dolares", "10 AAPL pagados en dólares (MEP): sale de la caja en dólares",
     ["2026-01-06,DEPOSITO,MiBroker,,,,500,,,,USD,",
      "2026-01-07,COMPRA,MiBroker,AAPL,10,13.5,,,,,USD,"]),
    ("dividendo_usd_de_cedear", "1,25 US$ a la caja en dólares",
     ["2026-01-07,COMPRA,MiBroker,AAPL,10,20000,,,,,ARS,",
      "2026-03-11,DIVIDENDO,MiBroker,AAPL,,,1.25,,,,USD,"]),
    ("cupon_escrito_CUPON", "cupón de un bono escrito 'CUPON' (castellano)",
     ["2026-01-07,COMPRA,MiBroker,GD38,100,0.6,,,,,USD,",
      "2026-07-09,CUPON,MiBroker,GD38,,,2.13,,,,USD,"]),
    ("cupon_escrito_RENTA", "cupón escrito 'RENTA'",
     ["2026-01-07,COMPRA,MiBroker,GD38,100,0.6,,,,,USD,",
      "2026-07-09,RENTA,MiBroker,GD38,,,2.13,,,,USD,"]),
    ("amortizacion", "amortización de 8 VN: entra la plata Y baja el nominal",
     ["2026-01-07,COMPRA,MiBroker,GD38,100,0.6,,,,,USD,",
      "2026-07-09,AMORTIZACION,MiBroker,GD38,8,1,8,,,,USD,"]),
    ("mep_conversion_completa", "1.200.000 ARS → 1.000 US$ (como el ejemplo de la plantilla)",
     ["2026-01-08,CONVERSION_ARS_USD,MiBroker,,,,1200000,1000,1200,,,"]),
    ("mep_sin_monto_usd", "MEP escrito con monto en pesos y tc, sin monto_usd",
     ["2026-01-08,MEP,MiBroker,,,,1200000,,1200,,,"]),
    ("mep_con_bono_puente", "MEP como lo muestra el broker: compra AL30 en pesos, vende AL30D en dólares",
     ["2026-01-08,COMPRA,MiBroker,AL30,1000,750,,,,,ARS,",
      "2026-01-08,VENTA,MiBroker,AL30D,1000,0.5,,,,,USD,"]),
    ("comision_suelta", "comisión de mantenimiento: caja −500",
     ["2026-01-20,COMISION,MiBroker,,,,500,,,,ARS,"]),
    ("impuesto", "retención: caja −300",
     ["2026-01-20,IMPUESTO,MiBroker,,,,300,,,,ARS,"]),
    ("titulos_de_otro_broker", "60 VIST que llegan de otro broker (no es una compra)",
     ["2026-01-10,TRANSFERENCIA,MiBroker,VIST,60,,,,,,ARS,traspaso desde IOL"]),
    ("fci_suscripcion_y_rescate", "suscribe 100.000 a un FCI y rescata 50.000",
     ["2026-01-10,SUSCRIPCION,MiBroker,FCI:BALANZ-AHORRO,,,100000,,,,ARS,",
      "2026-02-10,RESCATE,MiBroker,FCI:BALANZ-AHORRO,,,50000,,,,ARS,"]),
    ("moneda_vacia", "compra sin moneda escrita",
     ["2026-01-07,COMPRA,MiBroker,GGAL,100,1500,,,,,,"]),
]

# Mismas filas con el formato que deja Excel en Argentina: ; · dd/mm/aaaa · 1.234,56
AR = [
    ("formato_argentino", "100 GGAL a 1.500,50 (costo 150.050) y depósito de 1.000.000",
     "fecha;tipo;broker;activo;cantidad;precio;monto;monto_usd;tc;comisiones;moneda;notas\n"
     "05/01/2026;DEPOSITO;MiBroker;;;;1.000.000;;;;ARS;\n"
     "07/01/2026;COMPRA;MiBroker;GGAL;100;1.500,50;;;;0;ARS;\n"),
]


def _cuenta(a, nombre, cuerpo, broker="MiBroker"):
    a.usuario(f"plantilla_{nombre}@rendi.test")
    prev, conf = a.subir([("mi_plantilla.csv", cuerpo.encode("utf-8"))], broker=broker,
                         fmt="rendi_generic")
    pos = a.q("SELECT broker, asset, ROUND(quantity,4) q, ROUND(invested,2) costo, is_cash, currency "
              "FROM positions WHERE user_id=? ORDER BY is_cash, broker, asset", a.uid)
    ops = a.q("SELECT date, broker, asset, op_type, ROUND(quantity,4) q, ROUND(pnl_usd,2) pnl "
              "FROM operations WHERE user_id=? ORDER BY date", a.uid)
    flujo = a.q("SELECT year, month, broker, ROUND(deposits,2) dep, ROUND(withdrawals,2) wd, "
                "ROUND(capital_final,2) cf FROM monthly_entries WHERE user_id=? "
                "AND broker='global' ORDER BY year, month", a.uid)
    return {
        "preview": prev.get("detail") or "ok",
        "errores": [{k: e.get(k) for k in ("row_index", "code", "message")}
                    for e in (prev.get("errors") or [])],
        "filas": [{k: r.get(k) for k in ("date", "operation_type", "asset_symbol", "quantity",
                                         "unit_price", "gross_amount", "fees", "currency", "broker",
                                         "status", "transfer_in", "transfer_out")}
                  for r in (prev.get("rows_preview") or [])],
        "confirm": (conf or {}).get("ok") if conf else None,
        "tenencia": [p for p in pos if not p["is_cash"]],
        "caja": [p for p in pos if p["is_cash"]],
        "operaciones": ops,
        "aportes_por_mes": flujo,
    }


def movimientos(a):
    out = {}
    for nombre, espera, filas in MOVIMIENTOS:
        out[nombre] = {"espera": espera, **_cuenta(a, nombre, "\n".join([HDR, DEP] + filas) + "\n")}
        print("mov", nombre, out[nombre]["preview"], len(out[nombre]["errores"]), "errores", flush=True)
    for nombre, espera, cuerpo in AR:
        out[nombre] = {"espera": espera, **_cuenta(a, nombre, cuerpo)}
        print("mov", nombre, out[nombre]["preview"], len(out[nombre]["errores"]), "errores", flush=True)
    # La plantilla tal cual se descarga (con sus filas de ejemplo).
    tpl = a.http.get("/api/imports/template?format=rendi_generic", headers=a.h).text
    out["plantilla_descargada_tal_cual"] = {
        "espera": "las filas de ejemplo no deberían entrar como operaciones reales",
        "texto": tpl, **_cuenta(a, "ejemplo", tpl, broker=None)}
    return out


def _a_formato_argentino(csv_bytes):
    """La misma plantilla guardada por Excel en Argentina: ; · dd/mm/aaaa · coma decimal."""
    filas = list(csv.reader(io.StringIO(csv_bytes.decode())))
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(filas[0])
    for f in filas[1:]:
        f = list(f)
        y, mth, d = f[0].split("-")
        f[0] = f"{d}/{mth}/{y}"
        for i in (4, 5, 6, 7, 8, 9):
            if f[i]:
                v = float(f[i])
                ent, dec = f"{v:.6f}".rstrip("0").rstrip(".").partition(".")[::2]
                ent = f"{int(ent):,}".replace(",", ".")
                f[i] = ent + ("," + dec if dec else "")
        w.writerow(f)
    return out.getvalue().encode()


def escenarios(a, m):
    """El inversor de la auditoría, escrito en la plantilla por alguien que la completa
    a mano. `broker`: lo que la persona escribe en la columna broker (y el de la foto).

    Cada caso corre dos veces: con el broker creado por la importación (lo que pasa hoy
    si no existía: la moneda sale de la mayoría de filas) y con el broker ya creado en
    pesos antes de subir la plantilla."""
    base = historia_base(m)
    con_tin = historia_base(m); con_tin.tin("2024-03-05", "VIST", 60)
    casos = {
        "P0_completa": (base, None, False, "MiBroker"),
        "P0_formato_argentino": (base, None, False, "MiBroker"),
        "P1_sin_depositos_ni_retiros": (base, lambda e: e.tipo in ("DEP", "WD"), False, "MiBroker"),
        "P2_sin_el_dolar_mep": (base, lambda e: e.tipo == "MEP", False, "MiBroker"),
        "P3_sin_dividendos_ni_cupones": (base, lambda e: e.tipo in ("DIV", "CUPON"), False, "MiBroker"),
        "P4_arranca_en_2025": (base, lambda e: e.fecha < "2025-01-01", False, "MiBroker"),
        "P5_falta_una_venta": (base, lambda e: e.tipo == "SELL" and e.tk == "GGAL", False, "MiBroker"),
        "P6_titulos_de_otro_broker": (con_tin, lambda e: e.tipo == "TIN", False, "MiBroker"),
        "P4_arranca_en_2025_con_foto_Balanz": (base, lambda e: e.fecha < "2025-01-01", True, "Balanz"),
        "P5_falta_una_venta_con_foto_Balanz": (base, lambda e: e.tipo == "SELL" and e.tk == "GGAL", True, "Balanz"),
    }
    out = {}
    for caso, (h, omitir, con_foto, broker) in casos.items():
        for previo in (False, True):
            nombre = caso + ("·ya_creado_en_pesos" if previo else "·broker_nuevo")
            out[nombre] = _escenario(a, h, omitir, con_foto, broker, previo,
                                     argentino=(caso == "P0_formato_argentino"))
            fc, fe = out[nombre]["final"]["certero"], out[nombre]["final"]["estimado"]
            print(f"{nombre:58s} CERT {fc['rendi']} vs {fc.get('verdad_twr')} [{fc['ventana'][0]}] "
                  f"{fc['motivo'] or ''} | EST {fe['rendi']} vs {fe.get('verdad_twr')} "
                  f"[{fe['ventana'][0]}] {fe['motivo'] or ''}", flush=True)
    return out


def _escenario(a, h, omitir, con_foto, broker, previo, argentino=False):
    import main as _main
    h.simular()
    a.usuario(f"plantilla_{id(h)}_{broker}_{previo}_{argentino}_{len(a.q('SELECT id FROM users'))}@rendi.test")
    if previo:
        _c = _main.get_db()
        with _c:
            _c.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,'ARS')",
                       (a.uid, broker))
        _c.close()
    cuerpo = g.generico(h, broker=broker, omitir=omitir)
    if argentino:
        cuerpo = _a_formato_argentino(cuerpo)
    prev, _conf = a.subir([("mi_plantilla.csv", cuerpo)], broker=broker, fmt="rendi_generic")
    fila = {"preview": prev.get("detail") or "ok",
            "brokers_nuevos": prev.get("new_brokers_created"),
            "errores": len(prev.get("errors") or []),
            "errores_ej": [(e.get("code"), (e.get("message") or "")[:120])
                           for e in (prev.get("errors") or [])][:5],
            "sin_foto": ce.medir_contra_verdad(h, a.motor())}
    if con_foto:
        pv, _ = a.subir_foto("ResumenDeCuenta.pdf", g.balanz_foto(h, ce.FOTO), broker,
                             "balanz_tenencia")
        fila["foto"] = {"ok": pv.get("session_id") is not None, "detail": pv.get("detail")}
    ult = a.q("SELECT MAX(n.date) d FROM import_normalized_tx n JOIN import_batches b "
              "ON b.id=n.batch_id WHERE b.user_id=? AND b.status='confirmed'", a.uid)[0]["d"]
    d0 = max(date.fromisoformat((ult or ce.FOTO)[:10]), date.fromisoformat(ce.FOTO)) + timedelta(days=1)
    a.cron(d0, date.today())
    a.reconstruir()
    fila["final"] = ce.medir_contra_verdad(h, a.motor())
    fila["brokers"] = a.q("SELECT name, currency FROM brokers WHERE user_id=?", a.uid)
    fila["caja_hoy"] = a.q("SELECT broker, ROUND(invested,2) v FROM positions WHERE user_id=? "
                           "AND is_cash=1", a.uid)
    fila["aportado"] = a.q("SELECT ROUND(SUM(deposits),2) dep, ROUND(SUM(withdrawals),2) wd "
                           "FROM monthly_entries WHERE user_id=? AND broker='global'", a.uid)[0]
    return fila


def main():
    salida = sys.argv[1]
    solo = sys.argv[sys.argv.index("--solo") + 1] if "--solo" in sys.argv else None
    m = Mercado()
    a = arnes.Arnes(m)
    res = {}
    if solo in (None, "movimientos"):
        res["movimientos"] = movimientos(a)
    if solo in (None, "escenarios"):
        res["escenarios"] = escenarios(a, m)
    json.dump(res, open(salida, "w"), ensure_ascii=False, default=str, indent=1)


if __name__ == "__main__":
    main()
