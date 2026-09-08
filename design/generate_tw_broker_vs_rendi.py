"""
Mockup para X/Twitter: "lo que ves en tu broker" vs "lo que ves en Rendi".

Izquierda: la tenencia típica de un broker AR (mockup) — un total en pesos y
nada más. Cero color = cero información.
Derecha: CAPTURA REAL del Dashboard de la app (`_caps/app_dashboard.png`), con
los montos ofuscados por `_caps/obfuscate_dashboard.py` (factor único: los
porcentajes y las sumas siguen cerrando entre sí).

Estética Nocturnal Precision (brand.py). Los datos del broker son ilustrativos.
Salida: outputs/social/rendi_tw_broker_vs_rendi.png (1600×900).
"""

from PIL import Image, ImageDraw, ImageFilter
import os
import brand as b
from brand import DARK as T, F_SEMI, F_MED, F_REG, MONO_M, MONO_R, mix, spaced, sw

W, H = 1600, 900
BG = T.bg
PANEL_L = (13, 15, 21)
BAR = (19, 22, 30)
LINE = (34, 39, 51)
LINE_R = (52, 48, 84)
INK0, INK1, INK2, INK3 = T.ink0, T.ink1, T.ink2, T.ink3
FAINT = T.ink_faint
VIOLET = T.violet

CAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_caps/app_dashboard.png")

# ── geometría: el panel que sabe más ocupa más ──────────────────────────────
PT = 204
CAP_CUT = 1370                  # corte limpio de la captura: justo debajo de los chips
LX0, LX1 = 56, 520              # broker (angosto)
RX0, RX1 = 568, 1544            # captura real (ancha)


def rtext(d, x_right, y, txt, f, fill):
    d.text((x_right - d.textlength(txt, font=f), y), txt, font=f, fill=fill)


def rounded_paste(img, src, box, radius=14):
    """Pega la captura con esquinas redondeadas."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    im = src.resize((w, h), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    im.putalpha(mask)
    img.alpha_composite(im, (x0, y0))


# ── canvas ──────────────────────────────────────────────────────────────────
img = Image.new("RGBA", (W, H), (*BG, 255))
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
for r in range(600, 0, -12):
    gd.ellipse([1080 - r, 300 - r, 1080 + r, 300 + r], fill=(*VIOLET, 7))
img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(120)))
d = ImageDraw.Draw(img, "RGBA")

# ── header ──────────────────────────────────────────────────────────────────
mark = b.logo(T, 28)
img.alpha_composite(mark, (56, 40))
d = ImageDraw.Draw(img, "RGBA")
d.text((56 + mark.width + 10, 41), "rendi", font=F_SEMI(26), fill=INK0)

f_h = F_SEMI(36)
d.text((56, 80), "Tu broker te dice cuánta plata tenés.", font=f_h, fill=INK3)
d.text((56, 120), "Rendi te dice cómo te fue.", font=f_h, fill=INK0)

fl = MONO_R(15)
spaced(d, "EN TU BROKER", LX0 + 2, PT - 26, fl, INK3, sp=3)
x_lbl = spaced(d, "EN RENDI", RX0 + 2, PT - 26, fl, VIOLET, sp=3)
spaced(d, "· PANTALLA REAL DE LA APP", RX0 + 2 + x_lbl + 14, PT - 26, fl, FAINT, sp=3)

# ── captura real (define el alto de la fila) ────────────────────────────────
cap = Image.open(CAP).crop((0, 0, 2260, CAP_CUT))
cap_w = RX1 - RX0
cap_h = int(cap.height * cap_w / cap.width)
PB = PT + cap_h

sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
ImageDraw.Draw(sh).rounded_rectangle([RX0 - 10, PT - 10, RX1 + 10, PB + 10],
                                     radius=22, fill=(*VIOLET, 40))
img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(46)))
rounded_paste(img, cap, [RX0, PT, RX1, PB], radius=14)
d = ImageDraw.Draw(img, "RGBA")
d.rounded_rectangle([RX0, PT, RX1 - 1, PB - 1], radius=14, outline=LINE_R, width=1)

# ════════════════════════════════════════════════════════════════════════════
# IZQUIERDA — la tenencia del broker (mockup)
# ════════════════════════════════════════════════════════════════════════════
d.rounded_rectangle([LX0, PT, LX1, PB], radius=14, fill=PANEL_L, outline=LINE, width=1)
d.rounded_rectangle([LX0, PT, LX1, PT + 44], radius=14, fill=BAR)
d.rectangle([LX0, PT + 26, LX1, PT + 44], fill=BAR)
d.line([(LX0, PT + 44), (LX1, PT + 44)], fill=LINE, width=1)
for i in range(3):
    cx = LX0 + 20 + i * 14
    d.ellipse([cx, PT + 18, cx + 7, PT + 25], fill=(46, 51, 64))
spaced(d, "TENENCIA", LX0 + 72, PT + 14, MONO_R(13), INK3, sp=2)
rtext(d, LX1 - 20, PT + 14, "18/08", MONO_R(13), FAINT)

C_ESP, C_VAL = LX0 + 22, LX1 - 22
fh = MONO_R(12)
y = PT + 74
spaced(d, "ESPECIE", C_ESP, y, fh, FAINT, sp=2)
spaced(d, "VALORIZADO", C_VAL - sw(d, "VALORIZADO", fh, 2), y, fh, FAINT, sp=2)
d.line([(C_ESP, y + 24), (C_VAL, y + 24)], fill=LINE, width=1)

# La tenencia del broker es la MISMA plata que muestra la captura de Rendi:
# suma $10.264.552, que es el equivalente en pesos de US$ 6.740,20 al blue 1522,9
# que aparece en el chip de la derecha. Si no cierra, el chiste no funciona.
rows = [("AL30", "4.059.176"), ("GGAL", "1.759.782"), ("NVDA", "1.647.622"),
        ("FCI Pesos", "1.681.106"), ("Dólares", "1.116.866")]
f_esp, f_num = F_MED(20), MONO_R(18)
y = PT + 116
for esp, val in rows:
    d.text((C_ESP, y), esp, font=f_esp, fill=INK1)
    rtext(d, C_VAL, y + 2, val, f_num, INK1)
    y += 52

d.line([(C_ESP, y + 10), (C_VAL, y + 10)], fill=LINE, width=1)
spaced(d, "TOTAL EN PESOS", C_ESP, y + 36, MONO_R(13), INK3, sp=2)
d.text((C_ESP, y + 62), "$10.264.552", font=F_SEMI(34), fill=INK0)

f_note = F_REG(18)
d.text((C_ESP, PB - 76), "Un número, en pesos,", font=f_note, fill=INK3)
d.text((C_ESP, PB - 52), "de un solo broker.", font=f_note, fill=INK3)

# ── flecha entre paneles ────────────────────────────────────────────────────
cx, cy = (LX1 + RX0) / 2, (PT + PB) / 2
d.ellipse([cx - 19, cy - 19, cx + 19, cy + 19], fill=(18, 19, 28), outline=LINE_R, width=1)
d.line([(cx - 7, cy), (cx + 3, cy)], fill=T.violet_soft, width=2)
d.polygon([(cx + 8, cy), (cx + 1, cy - 5), (cx + 1, cy + 5)], fill=T.violet_soft)

# ── footer ──────────────────────────────────────────────────────────────────
f_f, uf = F_REG(21), MONO_M(21)
foot, url = "Importás el export de tu broker. El resto lo hace Rendi.", "rendi.finance"
fw, uw = d.textlength(foot, font=f_f), d.textlength(url, font=uf)
x = (W - (fw + 22 + uw)) / 2
y_f = PB + 40
d.text((x, y_f), foot, font=f_f, fill=INK2)
d.text((x + fw + 22, y_f + 1), url, font=uf, fill=VIOLET)

b.save(img, "rendi_tw_broker_vs_rendi.png")
