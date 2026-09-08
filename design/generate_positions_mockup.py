"""
Mockup de la propuesta para la vista de Posiciones (feedback de cmbroca):
  A. Columna "Activo" FIJA al scrollear (sticky horizontal) — no perdés referencia.
  B. Modo COMPACTO (densidad) — entran más columnas.
  C. Selector de COLUMNAS (qué ver, se guarda).

No es el producto real: es un render de propuesta, fiel al estilo dark de Rendi
(label-mono en headers, verde/rojo en P&L, jerarquía ink). Datos ilustrativos.
Salida: rendi_posiciones_mockup.png (1600×1000).
"""

from PIL import Image, ImageDraw, ImageFilter
import os
import brand as b
from brand import F_SEMI, F_MED, F_REG, MONO_M, MONO_R, mix

W, H = 1600, 1000
FONTS = b.FONTS_DIR

BG = (10, 12, 17)
PANEL = (15, 17, 24)
BAR = (22, 25, 33)
LINE = (38, 43, 56)
LINE2 = (28, 32, 42)
INK0, INK1, INK2, INK3 = (236, 238, 244), (198, 204, 218), (150, 158, 176), (110, 118, 138)
GREEN, RED = (33, 208, 122), (255, 83, 96)
VIOLET, ACCENT = (139, 125, 255), (91, 157, 249)


def logo_chip(d, x, y, s, asset, kind):
    col = {'stock': (54, 60, 78), 'bono': mix(ACCENT, BG, 0.5), 'cash': (44, 50, 64)}[kind]
    d.rounded_rectangle([x, y, x + s, y + s], radius=8, fill=col)
    txt = asset[:2].upper()
    f = F_SEMI(int(s * 0.42))
    tw = d.textlength(txt, font=f)
    d.text((x + (s - tw) / 2, y + s * 0.26), txt, font=f, fill=INK0)


def rtext(d, x_right, y, txt, f, fill):
    d.text((x_right - d.textlength(txt, font=f), y), txt, font=f, fill=fill)


def callout(img, anchor, text, box_xy, color=VIOLET):
    """Etiqueta de anotación con línea al punto anchor."""
    d = ImageDraw.Draw(img, "RGBA")
    f = F_MED(21)
    lines = text.split("\n")
    tw = max(d.textlength(l, font=f) for l in lines)
    pad = 16
    bw, bh = tw + pad * 2, len(lines) * 30 + pad * 2 - 6
    bx, by = box_xy
    # línea conectora
    d.line([(bx + bw / 2, by + bh / 2), anchor], fill=mix(color, BG, 0.75), width=2)
    d.ellipse([anchor[0] - 5, anchor[1] - 5, anchor[0] + 5, anchor[1] + 5], fill=color)
    # caja
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=12,
                        fill=mix(color, BG, 0.12), outline=mix(color, BG, 0.5), width=2)
    ty = by + pad - 3
    for l in lines:
        d.text((bx + pad, ty), l, font=f, fill=mix(color, (255, 255, 255), 0.35))
        ty += 30


def build():
    img = Image.new("RGBA", (W, H), (*BG, 255))
    d = ImageDraw.Draw(img, "RGBA")

    # ── header de propuesta ──
    mark = b.logo(b.DARK, 30)
    img.alpha_composite(mark, (50, 44))
    d.text((50 + mark.width + 11, 45), "rendi", font=F_SEMI(28), fill=INK0)
    b.spaced(d, "PROPUESTA · VISTA DE POSICIONES", 54, 84, MONO_R(16), mix(VIOLET, BG, 0.85), sp=2)
    d.text((W - 50 - d.textlength("Cartera › Posiciones", font=MONO_R(18)), 56),
           "Cartera › Posiciones", font=MONO_R(18), fill=INK3)

    # ── toolbar ──
    ty = 150
    d.text((50, ty + 8), "Cocos", font=F_SEMI(26), fill=INK0)
    d.text((50 + d.textlength("Cocos", font=F_SEMI(26)) + 14, ty + 14), "· 5 activos",
           font=F_REG(19), fill=INK3)

    # density toggle [Cómodo | Compacto]
    dt_x = 960
    d.rounded_rectangle([dt_x, ty, dt_x + 230, ty + 44], radius=10, fill=BAR, outline=LINE, width=1)
    d.text((dt_x + 22, ty + 12), "Cómodo", font=F_MED(19), fill=INK3)
    d.rounded_rectangle([dt_x + 118, ty + 4, dt_x + 226, ty + 40], radius=8, fill=mix(VIOLET, BG, 0.22))
    d.text((dt_x + 138, ty + 12), "Compacto", font=F_SEMI(19), fill=INK0)

    # Columnas ▾ button
    cb_x = 1220
    d.rounded_rectangle([cb_x, ty, cb_x + 168, ty + 44], radius=10,
                        fill=mix(VIOLET, BG, 0.18), outline=mix(VIOLET, BG, 0.5), width=1)
    d.text((cb_x + 20, ty + 12), "Columnas", font=F_SEMI(19), fill=mix(VIOLET, (255, 255, 255), 0.4))
    _tc = mix(VIOLET, (255, 255, 255), 0.4)
    _tx, _tyy = cb_x + 128, ty + 19
    d.polygon([(_tx, _tyy), (_tx + 14, _tyy), (_tx + 7, _tyy + 9)], fill=_tc)

    # ── tabla ──
    tx0, tx1 = 50, 1180          # panel visible (recortado a la derecha → scroll)
    ty0 = 224
    rowh = 60                     # compacto
    head_h = 40
    asset_w = 290                 # columna Activo (fija)
    d.rounded_rectangle([tx0, ty0, tx1, ty0 + head_h + rowh * 5 + 8], radius=14,
                        fill=PANEL, outline=LINE, width=1)

    cols = [("Cantidad", 360), ("Precio prom.", 488), ("Precio actual", 624),
            ("Invertido", 770), ("Valor", 906), ("P&L", 1042), ("P&L %", 1150)]
    # header de columnas
    hy = ty0 + 12
    d.text((tx0 + 70, hy), "ACTIVO", font=MONO_R(15), fill=INK3)
    for name, cx in cols:
        rtext(d, cx, hy, name.upper(), MONO_R(15), INK3)
    d.line([(tx0, ty0 + head_h), (tx1, ty0 + head_h)], fill=LINE, width=1)

    rows = [
        ("AAPL", "stock", "Apple", "40", "182,30", "224,10", "7.292", "8.964", "+1.672", "+22,9%", 1),
        ("NVDA", "stock", "Nvidia", "25", "98,40", "121,80", "2.460", "3.045", "+585", "+23,8%", 1),
        ("KO", "stock", "Coca-Cola", "60", "58,20", "57,10", "3.492", "3.426", "−66", "−1,9%", -1),
        ("AL30", "bono", "Bonar 2030", "1.500", "58,10", "61,40", "871", "921", "+50", "+5,7%", 1),
        ("USD", "cash", "Efectivo", "3.200", "—", "—", "3.200", "3.200", "—", "—", 0),
    ]
    yy = ty0 + head_h + 4
    for asset, kind, full, qty, prom, act, inv, val, pnl, pnlpct, sign in rows:
        rowbg = (20, 23, 31) if kind != 'cash' else (18, 21, 28)
        d.rectangle([tx0 + 1, yy, tx1 - 1, yy + rowh], fill=rowbg)
        # celdas numéricas (scrollables)
        nf = MONO_R(20)
        pnlcol = GREEN if sign > 0 else RED if sign < 0 else INK3
        for (name, cx), v, isp in [
            (cols[0], qty, 0), (cols[1], prom, 0), (cols[2], act, 0),
            (cols[3], inv, 0), (cols[4], val, 0)]:
            rtext(d, cx, yy + 19, v, nf, INK1)
        # P&L con tinte
        if sign != 0:
            d.rectangle([cols[5][1] - 96, yy, cols[5][1] + 8, yy + rowh],
                        fill=mix(pnlcol, rowbg, 0.10))
        rtext(d, cols[5][1], yy + 19, pnl, MONO_M(20), pnlcol)
        rtext(d, cols[6][1], yy + 19, pnlpct, MONO_R(20), pnlcol)
        d.line([(tx0, yy + rowh), (tx1, yy + rowh)], fill=LINE2, width=1)
        yy += rowh

    # ── columna ACTIVO fija (se dibuja ENCIMA de las scrollables) ──
    ax1 = tx0 + asset_w
    # sombra a la derecha de la columna fija (indica que está elevada)
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle([ax1, ty0, ax1 + 34, ty0 + head_h + rowh * 5 + 8], fill=(0, 0, 0, 150))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    d = ImageDraw.Draw(img, "RGBA")
    # fondo opaco de la columna fija
    d.rounded_rectangle([tx0, ty0, ax1, ty0 + head_h + rowh * 5 + 8], radius=14, fill=PANEL)
    d.rectangle([ax1 - 14, ty0, ax1, ty0 + head_h + rowh * 5 + 8], fill=PANEL)
    d.line([(ax1, ty0), (ax1, ty0 + head_h + rowh * 5 + 8)], fill=mix(VIOLET, BG, 0.5), width=2)
    d.text((tx0 + 70, hy), "ACTIVO", font=MONO_R(15), fill=INK3)
    # mini-candado: marca que la columna está fija
    _lx = tx0 + 70 + d.textlength("ACTIVO", font=MONO_R(15)) + 10
    d.rounded_rectangle([_lx, hy + 1, _lx + 11, hy + 9], radius=2, fill=mix(VIOLET, BG, 0.8))
    d.arc([_lx + 2, hy - 4, _lx + 9, hy + 4], start=180, end=360, fill=mix(VIOLET, BG, 0.8), width=2)
    d.line([(tx0, ty0 + head_h), (ax1, ty0 + head_h)], fill=LINE, width=1)
    yy = ty0 + head_h + 4
    for asset, kind, full, *_rest, sign in rows:
        rowbg = (20, 23, 31) if kind != 'cash' else (18, 21, 28)
        d.rectangle([tx0 + 1, yy, ax1 - 14, yy + rowh], fill=rowbg)
        logo_chip(d, tx0 + 18, yy + 13, 34, asset, kind)
        d.text((tx0 + 64, yy + 12), asset, font=F_SEMI(21), fill=INK0)
        badge = {'cash': ('CASH', INK2), 'bono': ('BONO', ACCENT)}.get(kind)
        nx = tx0 + 64 + d.textlength(asset, font=F_SEMI(21)) + 8
        if badge:
            bf = MONO_R(12)
            bw = d.textlength(badge[0], font=bf) + 12
            d.rounded_rectangle([nx, yy + 14, nx + bw, yy + 32], radius=4,
                                fill=mix(badge[1], rowbg, 0.15), outline=mix(badge[1], rowbg, 0.4), width=1)
            d.text((nx + 6, yy + 15), badge[0], font=bf, fill=badge[1])
        d.text((tx0 + 64, yy + 36), full, font=MONO_R(14), fill=INK3)
        d.line([(tx0, yy + rowh), (ax1, yy + rowh)], fill=LINE2, width=1)
        yy += rowh

    # ── scrollbar horizontal (muestra que hay más columnas) ──
    sby = ty0 + head_h + rowh * 5 + 20
    d.rounded_rectangle([tx0, sby, tx1, sby + 8], radius=4, fill=LINE2)
    d.rounded_rectangle([tx0 + 300, sby, tx0 + 820, sby + 8], radius=4, fill=mix(INK3, BG, 0.7))

    # ── selector de columnas (dropdown abierto) ──
    dx0, dy0 = 1220, 210
    dw = 330
    colopts = [("30 D", 0), ("Cantidad", 1), ("Precio prom.", 0), ("Precio actual", 1),
               ("Invertido", 1), ("Valor", 1), ("P&L", 1), ("P&L %", 1),
               ("Var. día", 1), ("TC compra", 0), ("Inv. USD", 0), ("P&L USD", 0)]
    dh = 56 + len(colopts) * 38 + 16
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([dx0, dy0 + 12, dx0 + dw, dy0 + dh + 12], radius=14, fill=(0, 0, 0, 150))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(26)))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([dx0, dy0, dx0 + dw, dy0 + dh], radius=14, fill=(20, 23, 31), outline=LINE, width=1)
    d.text((dx0 + 20, dy0 + 16), "Mostrar columnas", font=F_SEMI(20), fill=INK0)
    d.text((dx0 + 20, dy0 + 42), "Se guarda para la próxima vez", font=F_REG(15), fill=INK3)
    oy = dy0 + 76
    for name, on in colopts:
        bx = dx0 + 20
        if on:
            d.rounded_rectangle([bx, oy, bx + 24, oy + 24], radius=6, fill=mix(VIOLET, BG, 0.85))
            d.line([(bx + 6, oy + 12), (bx + 10, oy + 17)], fill=(255, 255, 255), width=2)
            d.line([(bx + 10, oy + 17), (bx + 18, oy + 7)], fill=(255, 255, 255), width=2)
        else:
            d.rounded_rectangle([bx, oy, bx + 24, oy + 24], radius=6, fill=(28, 32, 42), outline=LINE, width=1)
        d.text((bx + 38, oy + 1), name, font=F_MED(19), fill=INK1 if on else INK3)
        oy += 38

    # ── anotaciones ──
    callout(img, (ax1 + 6, 470), "La columna Activo queda fija al\nscrollear → nunca perdés referencia\nde qué activo estás viendo", (130, 560))
    callout(img, (1075, 172), "Modo compacto:\nentran más columnas", (790, 700))
    callout(img, (dx0 + 30, dy0 + 250), "Elegí qué columnas ver.\nLos Pro arman su vista a medida", (1190, 700), color=ACCENT)

    out = os.path.join(b.OUT_DIR, "rendi_posiciones_mockup.png")
    os.makedirs(b.OUT_DIR, exist_ok=True)
    img.convert("RGB").save(out, "PNG")
    print(f"  ✓ rendi_posiciones_mockup.png ({os.path.getsize(out)/1024:.0f}KB)")


if __name__ == "__main__":
    build()
