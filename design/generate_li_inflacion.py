"""
Imagen para LinkedIn + Twitter del post de INFLACIÓN (build-in-public, founder).
Reproduce FIEL el gráfico real de Rendi (Insights → Performance en modo pesos):
tu cartera (verde #21D07A) vs la inflación acumulada (violeta #8B7DFF), con el
frame de producto (barra tipo navegador + url real) y el banner real de
BenchmarksLine en su estado negativo ("Tu cartera rindió X% menos que ...").

No es un mockup genérico: colores, líneas, copy del banner y layout salen del
componente real (frontend/src/pages/Insights.jsx + components/BenchmarksLine.jsx).

Salidas:
  rendi_li_inflacion_45.png    1080×1350 (4:5)  — óptimo LinkedIn
  rendi_li_inflacion_169.png   1600×900 (16:9)  — óptimo Twitter/X
"""

from PIL import Image, ImageDraw, ImageFilter
import os
import brand as b
from brand import (DARK, canvas, header, footer, save, mix,
                   F_SEMI, F_MED, F_REG, MONO_M, MONO_R,
                   cen, cen_seg, spaced, sw)

t = DARK

# Colores EXACTOS del componente real
C_CARTERA = (33, 208, 122)   # #21D07A — P/L total (Insights.jsx:1898)
C_INFLA = (139, 125, 255)    # #8B7DFF — benchmark inflación en ARS (Insights.jsx:1900)
C_SP = (70, 198, 224)        # #46C6E0 — S&P (modo USD)
NEG = (255, 83, 96)          # #FF5360 — rendi-neg (BenchmarksLine tono negativo)
D_BG = (13, 15, 21)
D_BAR = (22, 25, 33)
D_CARD = (18, 21, 28)
D_LINE = (38, 43, 56)
D_INK1, D_INK3 = (188, 195, 210), (110, 118, 138)

# Datos ilustrativos (un año, en pesos): la cartera arranca adelante y la
# inflación la pasa — termina abajo → pérdida de poder de compra.
MONTHS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
CARTERA = [0, 6, 11, 16, 19, 23, 26, 28, 31, 34, 37, 40]
INFLA = [0, 4, 8, 12, 17, 22, 28, 33, 39, 44, 48, 52]
YMAX = 56


def pts(vals, x0, x1, y0, y1, ymax):
    n = len(vals)
    return [(x0 + (x1 - x0) * i / (n - 1), y1 - (v / ymax) * (y1 - y0)) for i, v in enumerate(vals)]


def chart_card(img, box, label_size=18, title_size=18, end_size=22, dot_r=5,
               line_w_main=5, line_w_bench=3):
    """Reproduce el card del chart real de Rendi. box=(x,y,w,h)."""
    cx, cy, cw, ch = box
    # sombra + card
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([cx, cy + 16, cx + cw, cy + ch + 16], radius=24, fill=(0, 0, 0, 110))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(34)))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=24, fill=D_BG, outline=D_LINE, width=1)

    # barra superior tipo navegador (3 dots + url real)
    bar_h = 56
    d.rounded_rectangle([cx, cy, cx + cw, cy + bar_h + 16], radius=24, fill=D_BAR)
    d.rectangle([cx, cy + bar_h, cx + cw, cy + bar_h + 16], fill=D_BG)
    for i, col in enumerate([(255, 95, 109), (255, 189, 68), (40, 206, 124)]):
        d.ellipse([cx + 30 + i * 28, cy + 21, cx + 30 + i * 28 + 13, cy + 34], fill=col)
    url = "rendi.finance/insights"
    uf = MONO_R(20)
    uw = d.textlength(url, font=uf)
    px = cx + (cw - (uw + 48)) / 2
    d.rounded_rectangle([px, cy + 14, px + uw + 48, cy + 44], radius=14, fill=D_CARD)
    d.text((px + 24, cy + 17), url, font=uf, fill=D_INK3)

    # título + leyenda
    ix = cx + 44
    spaced(d, "PERFORMANCE · TU CARTERA vs INFLACIÓN", ix, cy + bar_h + 30, MONO_R(title_size), D_INK3, sp=1)
    lf = MONO_R(title_size)
    lx = cx + cw - 44
    for name, col in reversed([("Tu cartera", C_CARTERA), ("Inflación", C_INFLA)]):
        tw = d.textlength(name, font=lf)
        lx -= tw
        d.text((lx, cy + bar_h + 30), name, font=lf, fill=D_INK1)
        lx -= 12
        d.ellipse([lx - 12, cy + bar_h + 32, lx, cy + bar_h + 44], fill=col)
        lx -= 30

    # área del chart
    px0, px1 = ix + 56, cx + cw - 118
    py0, py1 = cy + bar_h + 92, cy + ch - 64
    yl = MONO_R(16)
    for v in (0, 10, 20, 30, 40, 50):
        gy = py1 - (v / YMAX) * (py1 - py0)
        d.line([(px0, gy), (px1 + 98, gy)], fill=D_LINE, width=1)
        d.text((ix, gy - 10), f"{v}%", font=yl, fill=D_INK3)

    p_inf = pts(INFLA, px0, px1, py0, py1, YMAX)
    p_ca = pts(CARTERA, px0, px1, py0, py1, YMAX)
    # área suave bajo la cartera
    d.polygon(p_ca + [(px1, py1), (px0, py1)], fill=mix(C_CARTERA, D_BG, 0.10))
    d.line(p_inf, fill=C_INFLA, width=line_w_bench, joint="curve")
    d.line(p_ca, fill=C_CARTERA, width=line_w_main, joint="curve")
    for x, y in p_ca:
        d.ellipse([x - dot_r, y - dot_r, x + dot_r, y + dot_r], fill=C_CARTERA)
    # labels de fin
    ef = MONO_M(end_size)
    for vals, p, col in [(INFLA, p_inf, C_INFLA), (CARTERA, p_ca, C_CARTERA)]:
        x, y = p[-1]
        d.text((px1 + 14, y - 12), f"+{vals[-1]:.1f}%".replace(".", ","), font=ef, fill=col)
    # meses
    mf = MONO_R(15)
    for i, m in enumerate(MONTHS):
        x = px0 + (px1 - px0) * i / (len(MONTHS) - 1)
        d.text((x - d.textlength(m, font=mf) / 2, py1 + 16), m, font=mf, fill=D_INK3)
    return d


def insight_banner(img, d, cx, cy, cw, txt_pct="7,9%", size=27):
    """Banner real de BenchmarksLine en tono NEGATIVO (rojo)."""
    bf = F_REG(size)
    # construir la línea: "Tu cartera rindió {7,9% menos} que la inflación."
    seg_a = "Tu cartera rindió "
    seg_b = f"{txt_pct} menos"
    seg_c = " que la inflación"
    bold = F_SEMI(size)
    wa = d.textlength(seg_a, font=bf)
    wb = d.textlength(seg_b, font=bold)
    wc = d.textlength(seg_c, font=bf)
    icon_w = 34
    total = icon_w + wa + wb + wc
    pad = 28
    bw = total + pad * 2
    bx = cx + (cw - bw) / 2
    bh = size + 34
    # bg/borde rojo tenue (como bg-rendi-neg/[0.05] border-rendi-neg/30)
    d.rounded_rectangle([bx, cy, bx + bw, cy + bh], radius=14,
                        fill=mix(NEG, D_BG, 0.08), outline=mix(NEG, D_BG, 0.45), width=1)
    tx = bx + pad
    ty = cy + (bh - size) / 2
    # icono trending-down (flechita)
    d.line([(tx, ty + 6), (tx + 18, ty + 22)], fill=NEG, width=3)
    d.line([(tx + 18, ty + 22), (tx + 18, ty + 12)], fill=NEG, width=3)
    d.line([(tx + 18, ty + 22), (tx + 8, ty + 22)], fill=NEG, width=3)
    tx += icon_w
    d.text((tx, ty), seg_a, font=bf, fill=NEG); tx += wa
    d.text((tx, ty), seg_b, font=bold, fill=NEG); tx += wb
    d.text((tx, ty), seg_c, font=bf, fill=NEG)
    return cy + bh


# ───────────────────────── 4:5 (LinkedIn) ──────────────────────────────────
def render_45():
    W, H = 1080, 1350
    img = canvas(t, (W, H))
    header(img, t, "/ tu rendimiento real", W)
    d = ImageDraw.Draw(img, "RGBA")

    cen(d, "Tu cartera aumentó un 40%.", 232, F_SEMI(56), t.title, W)
    cen_seg(d, [("Contra la inflación, ", t.title), ("perdiste", NEG), (".", t.title)], 308, F_SEMI(56), W)
    cen(d, "El número nominal en pesos casi nunca descuenta la inflación.", 410, F_REG(27), t.ink2, W)

    chart_card(img, (70, 480, 940, 560))
    d = ImageDraw.Draw(img, "RGBA")
    insight_banner(img, d, 70, 1080, 940, "7,9%", size=27)
    cen(d, "Ejemplo ilustrativo — en tu cuenta son tus datos reales", 1168, F_REG(20), t.ink_faint, W)

    footer(img, t, W, H)
    save(img, "rendi_li_inflacion_45.png")


# ───────────────────────── 16:9 (Twitter/X) ────────────────────────────────
def render_169():
    W, H = 1600, 900
    img = canvas(t, (W, H))
    # header manual (compacto, arriba a la izq) para landscape
    d = ImageDraw.Draw(img, "RGBA")
    mark = b.logo(t, 34)
    img.alpha_composite(mark, (80, 70))
    d.text((80 + mark.width + 12, 71), "rendi", font=F_SEMI(33), fill=t.title)
    spaced(d, "TU RENDIMIENTO REAL", 84, 118, MONO_R(17), t.eyebrow, sp=3)

    # headline a la izquierda
    d.text((80, 244), "Tu cartera", font=F_SEMI(62), fill=t.title)
    d.text((80, 318), "aumentó un 40%.", font=F_SEMI(62), fill=t.title)
    d.text((80, 430), "Contra la inflación,", font=F_SEMI(46), fill=t.title)
    d.text((80, 488), "perdiste.", font=F_SEMI(46), fill=NEG)
    for i, ln in enumerate(["El número nominal en pesos", "casi nunca descuenta la inflación."]):
        d.text((80, 600 + i * 38), ln, font=F_REG(26), fill=t.ink2)
    d.text((80, 800), "rendi.finance", font=MONO_R(22), fill=t.ink3)

    # chart a la derecha
    chart_card(img, (700, 150, 820, 600), title_size=17, end_size=21)
    d = ImageDraw.Draw(img, "RGBA")
    insight_banner(img, d, 700, 778, 820, "7,9%", size=24)

    save(img, "rendi_li_inflacion_169.png")


# ───────────────────────── 9:16 (Historias / Reels) ────────────────────────
def render_916():
    W, H = 1080, 1920
    img = canvas(t, (W, H))
    header(img, t, "/ tu rendimiento real", W, y=300, mark_h=42)
    d = ImageDraw.Draw(img, "RGBA")
    cen(d, "Tu cartera aumentó un 40%.", 560, F_SEMI(54), t.title, W)
    cen_seg(d, [("Contra la inflación, ", t.title), ("perdiste", NEG), (".", t.title)], 632, F_SEMI(54), W)
    cen(d, "El número nominal en pesos casi", 748, F_REG(28), t.ink2, W)
    cen(d, "nunca descuenta la inflación.", 788, F_REG(28), t.ink2, W)
    chart_card(img, (70, 900, 940, 560))
    d = ImageDraw.Draw(img, "RGBA")
    insight_banner(img, d, 70, 1500, 940, "7,9%", size=27)
    cen(d, "Ejemplo ilustrativo — en tu cuenta son tus datos reales", 1590, F_REG(20), t.ink_faint, W)
    cen(d, "rendi.finance", 1636, MONO_R(24), t.ink2, W)
    save(img, "rendi_li_inflacion_916.png")


if __name__ == "__main__":
    render_45()
    render_916()
    render_169()
    print("\nDone — 4:5 + 9:16 + 16:9.")
