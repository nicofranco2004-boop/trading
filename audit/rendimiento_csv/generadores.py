"""La historia (historia.py) escrita en el formato de cada broker, + su foto de tenencia.

Formatos tomados de los archivos reales del dueño (Balanz movimientos, IEB actividad y
portafolio) y de los `template_csv()` de cada parser. Donde el formato real de un tipo
de movimiento no se conoce, se dice en el comentario (`SUPUESTO`).

`omitir(e) -> bool` saca eventos del archivo de movimientos (para simular una ventana
parcial o un movimiento que el broker no exportó). La foto SIEMPRE sale de la historia
VERDADERA a la fecha de la foto — es lo que el broker mostraría.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

import openpyxl

from historia import Historia
from mercado import BONOS

_INST_BALANZ = {"CEDEAR": "Cedears", "ACCION": "Acciones", "BONO": "Bonos"}
CONDUCTO = "AL30"   # bono puente del dólar MEP


def _xlsx(sheets):
    wb = openpyxl.Workbook()
    first = True
    for name, rows in sheets:
        ws = wb.active if first else wb.create_sheet(name)
        ws.title = name
        first = False
        for r in rows:
            ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _eventos(h: Historia, omitir=None, hasta=None):
    evs = [e for e in h.estado() if not (omitir and omitir(e))]
    return [e for e in evs if not hasta or e.fecha <= hasta]


# ─── Balanz · Movimientos (xlsx) ─────────────────────────────────────────────
def balanz_mov(h: Historia, omitir=None, hasta=None) -> bytes:
    rows, n = [], 1000
    for e in _eventos(h, omitir, hasta):
        n += 1
        d = e.fecha
        inst = _INST_BALANZ.get(e.clase)
        if e.tipo == "DEP":
            rows.append((f"Recibo de Cobro / {n}", None, None, d, 0, -1, d,
                         "Pesos" if e.moneda == "ARS" else "Dólares", e.monto))
        elif e.tipo == "WD":
            rows.append((f"Comprobante de Pago / {n}", None, None, d, 0, -1, d,
                         "Pesos" if e.moneda == "ARS" else "Dólares", -e.monto))
        elif e.tipo in ("BUY", "SELL"):
            mon = "$" if e.moneda == "ARS" else "usd"
            op = "COMPRA" if e.tipo == "BUY" else "VENTA"
            q = e.qty if e.tipo == "BUY" else -e.qty
            imp = -e.neto if e.tipo == "BUY" else e.neto
            rows.append((f"Boleto / {n} / {op} / 1 / {e.tk} / {mon}", e.tk, inst, d, q, e.px, d,
                         "Pesos" if e.moneda == "ARS" else "Dólares", imp))
        elif e.tipo == "DIV":
            rows.append((f"Dividendo en efectivo / {e.tk}", e.tk, inst, d, 0, -1, d,
                         "Pesos" if e.moneda == "ARS" else "Dólares C.V. 7000", e.monto))
        elif e.tipo == "CUPON":
            rows.append((f"Renta / {e.tk}", e.tk, "Bonos", d, 0, -1, d, "Dólares", e.monto))
        elif e.tipo == "MEP":
            px_ars = round(h.m.ars(CONDUCTO, d), 4)
            vn = round(e.monto / px_ars)
            px_usd = round(e.usd_recibidos / vn, 6)
            rows.append((f"Boleto / {n} / COMPRA / 1 / {CONDUCTO} / $", CONDUCTO, "Bonos", d, vn, px_ars, d,
                         "Pesos", -round(vn * px_ars, 2)))
            rows.append((f"Boleto / {n + 1} / VENTA / 1 / {CONDUCTO} / usd", CONDUCTO, "Bonos", d, -vn, px_usd, d,
                         "Dólares", round(vn * px_usd, 2)))
            n += 1
        elif e.tipo == "TIN":
            rows.append(("Transferencia Externa (Crédito)", e.tk, inst, d, e.qty, -1, d, None, 0))
    rows.sort(key=lambda r: r[3], reverse=True)          # el export real viene descendente
    hdr = ("Descripcion", "Ticker", "Tipo de Instrumento", "Concertacion", "Cantidad", "Precio",
           "Liquidacion", "Moneda", "Importe")
    return _xlsx([("movimientos", [hdr] + rows)])


def _ar(x, dec=2):
    s = f"{x:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def balanz_foto(h: Historia, fecha: str, ajustar=None) -> bytes:
    """Resumen de Cuenta (texto que el endpoint extrae del PDF). Todo en pesos."""
    f = h.foto(fecha)
    if ajustar:
        f = ajustar(f)
    d = date.fromisoformat(fecha)
    tot = {}
    secciones = {"Acciones": [], "Bonos": [], "Cedears": []}
    for (tk, _), q in sorted(f["hold"].items()):
        px = h.m.ars(tk, d)
        cls = "Bonos" if tk in BONOS else ("Cedears" if tk not in ("GGAL", "YPFD", "PAMP", "TGNO4", "BBAR", "SUPV", "ALUA", "AUSO") else "Acciones")
        secciones[cls].append(f"{tk} {tk} DESCRIPCION {_ar(q)} 0.00 $ {_ar(px)} $ {_ar(q * px, 0)}")
        tot[cls] = tot.get(cls, 0) + q * px
    lines = ["BALANZ", "Posición consolidada por concertación FULL INVESTMENT HOUSE",
             "Información de cuenta | Tenencias",
             f"Cuenta TEST USER Fecha resumen {d:%d/%m/%Y}",
             f"N° Comitente 111 Fecha de emisión {d:%d/%m/%Y}",
             f"Total $ {_ar(sum(tot.values()), 0)}", "Instrumentos Monedas",
             f"Acciones $ {_ar(tot.get('Acciones', 0), 0)} Pesos $ {_ar(f['cash']['ARS'])}",
             f"Bonos $ {_ar(tot.get('Bonos', 0), 0)} Dólares USD {_ar(f['cash']['USD'])}",
             f"Cedears $ {_ar(tot.get('Cedears', 0), 0)} US Dollar (Cable) USD 0,00",
             "BALANZ CAPITAL | Av. Corrientes 316 | CABA | www.balanz.com", "BALANZ",
             "Posición consolidada por concertación FULL INVESTMENT HOUSE", "Distribución por tipo de activos"]
    for sec, filas in secciones.items():
        if not filas:
            continue
        lines += [sec, "Especie Descripción Cantidad Garantía Precio Valor Actual"] + filas
    lines += ["BALANZ CAPITAL | Av. Corrientes 316 | CABA | www.balanz.com"]
    return pdf_de_texto(lines)


def pdf_de_texto(lines) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for ln in lines:
        if y < 40:
            c.showPage()
            y = 800
        c.setFont("Helvetica", 7)
        c.drawString(20, y, ln)
        y -= 11
    c.save()
    return buf.getvalue()


# ─── IEB · Toda la actividad (xlsx) + Portafolio (xlsx) ───────────────────────
def ieb_mov(h: Historia, omitir=None, hasta=None) -> bytes:
    rows, n = [], 5000
    for e in _eventos(h, omitir, hasta):
        n += 1
        d = datetime.fromisoformat(e.fecha + "T03:00:00")
        if e.tipo == "DEP":
            rows.append(("-", "RECIBO DE COBRO", d, d, n, "-", "-", e.monto, "-", "ARS") if e.moneda == "ARS"
                        else ("DOLAR", "RECIBO DE COBRO USD WEB", d, d, n, "-", "-", "-", e.monto, "USD"))
        elif e.tipo == "WD":
            rows.append(("-", "O.PAGO ", d, d, n, "-", "-", -e.monto, "-", "ARS") if e.moneda == "ARS"
                        else ("DOLAR", "ORDEN DE PAGO USD WEB", d, d, n, "-", "-", "-", -e.monto, "USD"))
        elif e.tipo in ("BUY", "SELL"):
            # IEB cotiza los bonos por 100 VN (causa R3 del HANDOFF_reconstructor).
            px = e.px * 100 if e.clase == "BONO" else e.px
            q = e.qty if e.tipo == "BUY" else -e.qty
            imp = -e.neto if e.tipo == "BUY" else e.neto
            if e.moneda == "ARS":
                rows.append((e.tk, "COMPRA NORMAL" if e.tipo == "BUY" else "VENTA", d, d, n, q, px, imp, "-", "ARS"))
            else:
                rows.append((e.tk, "COMPRA PARIDAD" if e.tipo == "BUY" else "VENTA  PARIDAD", d, d, n, q, px, "-", imp, "USD"))
        elif e.tipo == "DIV":
            # Real: el dividendo en dólares viene en la columna de PESOS con divisa 'OTHER'.
            rows.append((e.tk, "DIVIDENDOS", d, d, n, "-", "-", e.monto, "-", "ARS" if e.moneda == "ARS" else "OTHER"))
        elif e.tipo == "CUPON":
            # SUPUESTO: el archivo real no trae cupones; se usa la columna de divisas.
            rows.append((e.tk, "RENTA", d, d, n, "-", "-", "-", e.monto, "USD"))
        elif e.tipo == "MEP":
            px_ars = round(h.m.ars(CONDUCTO, d.date()), 4)
            vn = round(e.monto / px_ars)
            px_usd = round(e.usd_recibidos / vn, 6)
            rows.append((CONDUCTO, "COMPRA NORMAL", d, d, n, vn, px_ars * 100, -round(vn * px_ars, 2), "-", "ARS"))
            rows.append((CONDUCTO, "VENTA  PARIDAD", d, d, n + 1, -vn, px_usd * 100, "-", round(vn * px_usd, 2), "USD"))
            n += 1
        elif e.tipo == "TIN":
            px = h.m.ars(e.tk, d.date())
            rows.append((e.tk, "DEPOSITO TITULOS TRANSF.", d, d, n, e.qty, px, round(e.qty * px, 2), "-", "ARS"))
    rows.sort(key=lambda r: r[2])
    hdr = ("Referencia", "Operación", "Fecha emisión", "Fecha liquidación", "Nro. de operación", "Cantidad",
           "Precio", "Importe ARS", "Importe divisas", "Divisa")
    return _xlsx([("Export", [hdr] + rows)])


def ieb_foto(h: Historia, fecha: str, ajustar=None) -> bytes:
    f = h.foto(fecha)
    if ajustar:
        f = ajustar(f)
    d = date.fromisoformat(fecha)
    hdr = ["Especie", "Moneda de emisión", "Cantidad", "Precio", "% del total", "PPP", "Var%",
           "Resultado", "Actualizado", "Posición total"]
    pat = [["Fecha:", datetime(d.year, d.month, d.day, 3, 0)], ["Patrimonio total", 0], [], [],
           ["Tenencia Mercado Argentino"], []]
    for sec, pred in (("Cedears", lambda t: t not in BONOS and t not in ("GGAL", "YPFD")),
                      ("Acciones", lambda t: t in ("GGAL", "YPFD")), ("Bonos", lambda t: t in BONOS)):
        filas = [(tk, m, q) for (tk, m), q in sorted(f["hold"].items()) if pred(tk)]
        if not filas:
            continue
        pat += [[sec], hdr]
        for tk, mon, q in filas:
            if tk in BONOS:
                px = h.m.usd(tk, d) * 100 if mon == "USD" else h.m.ars(tk, d) * 100   # por 100 VN
                val = q * px / 100
            else:
                px = h.m.ars(tk, d) / (h.m.mep(d) if mon == "USD" else 1)
                val = q * px
            pat.append([f"{tk} - {tk} DESCRIPCION", mon, q, round(px, 4), 1.0, round(px, 4), 0, 0,
                        datetime(d.year, d.month, d.day, 8, 0), round(val, 2)])
        pat.append(["Subtotal", "-", "-", None, "-", "-", "0", "-", "0", None])
    sal = [["ARS "], ["Plazo", "Fecha", "Saldo"], ["Hoy", datetime(d.year, d.month, d.day, 11, 0), round(f["cash"]["ARS"], 2)],
           ["Total", "-", round(f["cash"]["ARS"], 2)], [], ["USD "], ["Plazo", "Fecha", "Saldo"],
           ["Hoy", datetime(d.year, d.month, d.day, 11, 0), round(f["cash"]["USD"], 2)], ["Total", "-", round(f["cash"]["USD"], 2)]]
    return _xlsx([("Patrimonio", pat), ("Saldos", sal)])


# ─── Rendi genérico (CSV) — la referencia "datos perfectos" ──────────────────
def generico(h: Historia, broker="Generico", omitir=None, hasta=None) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["fecha", "tipo", "broker", "activo", "cantidad", "precio", "monto", "monto_usd", "tc",
                "comisiones", "moneda", "notas"])
    for e in _eventos(h, omitir, hasta):
        if e.tipo == "DEP":
            w.writerow([e.fecha, "DEPOSITO", broker, "", "", "", e.monto, "", "", "", e.moneda, ""])
        elif e.tipo == "WD":
            w.writerow([e.fecha, "RETIRO", broker, "", "", "", e.monto, "", "", "", e.moneda, ""])
        elif e.tipo in ("BUY", "SELL"):
            com = round(abs(e.neto - e.qty * e.px), 2)
            w.writerow([e.fecha, "COMPRA" if e.tipo == "BUY" else "VENTA", broker, e.tk, e.qty, e.px, "", "", "",
                        com, e.moneda, ""])
        elif e.tipo in ("DIV", "CUPON"):
            w.writerow([e.fecha, "DIVIDENDO", broker, e.tk, "", "", e.monto, "", "", "", e.moneda, ""])
        elif e.tipo == "MEP":
            w.writerow([e.fecha, "CONVERSION_ARS_USD", broker, "", "", "", e.monto, e.usd_recibidos,
                        round(e.monto / e.usd_recibidos, 4), "", "", "Compra MEP"])
    return out.getvalue().encode()
