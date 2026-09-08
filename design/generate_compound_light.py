"""
Post feed 4:5 (1080×1350) — Interés compuesto, VERSIÓN CLARA (tono Frost).
Mismo contenido y fuentes reales (Geist + JetBrains Mono) que la versión dark,
pero sobre fondo claro #F4F2FB — más cálido, menos oscuro. Hex del brand kit.

Escenario: US$ 200/mes · 10% anual (cap. mensual) · de los 20 a los 50 (360 aportes).
"""

import os
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
SS = 2
MARGIN = 80
X0, X1 = MARGIN, W - MARGIN

# ─── Paleta clara (brand kit) ────────────────────────────────────────────────
FROST       = (0xF5, 0xF3, 0xFB)
INK         = (0x07, 0x09, 0x0C)
INK_STRONG  = (0x11, 0x13, 0x1A)
INK_BODY    = (0x34, 0x38, 0x44)
INK_MUTE    = (0x78, 0x7C, 0x8C)
INK_FAINT   = (0xB6, 0xB8, 0xC6)
CARD_BORDER = (0xE4, 0xE0, 0xF0)
VIOLET      = (0x8B, 0x7D, 0xFF)   # primario (iso, barra)
VIOLET_H    = (0x6E, 0x5F, 0xF0)   # hover/deep — para texto y línea sobre claro
GREEN       = (0x14, 0xA8, 0x5C)   # ganancia legible sobre claro

def mix(fg, bg, a):
    return tuple(int(bg[i] + (fg[i] - bg[i]) * a) for i in range(3))
AREA = mix(VIOLET, FROST, 0.18)    # relleno claro bajo la curva

FONTS = "/Users/nicolaspussetto/Documents/trading/design/fonts"
def _f(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), int(size * SS))
GEIST_RG = lambda s: _f("Geist-Regular.ttf", s)
GEIST_MD = lambda s: _f("Geist-Medium.ttf", s)
GEIST_SB = lambda s: _f("Geist-SemiBold.ttf", s)
JB_RG    = lambda s: _f("JetBrainsMono-Regular.ttf", s)
JB_MD    = lambda s: _f("JetBrainsMono-Medium.ttf", s)
def S(v): return int(round(v * SS))

# ─── Helpers ─────────────────────────────────────────────────────────────────
def text(d, x, y, s, font, fill): d.text((S(x), S(y)), s, font=font, fill=fill)
def text_right(d, xr, y, s, font, fill):
    d.text((S(xr) - d.textlength(s, font=font), S(y)), s, font=font, fill=fill)

def mono_spaced(d, x, y, s, size, fill, weight="rg", ls=0.08, align="left", xr=None):
    f = JB_MD(size) if weight == "md" else JB_RG(size)
    sp = size * ls * SS
    total = sum(d.textlength(c, font=f) for c in s) + sp * (len(s) - 1)
    cx = (S(xr) - total) if align == "right" else S(x)
    for c in s:
        d.text((cx, S(y)), c, font=f, fill=fill); cx += d.textlength(c, font=f) + sp
    return total / SS

def fit(d, s, factory, max_w, start, lo=40):
    size = start
    while size > lo:
        f = factory(size)
        if d.textlength(s, font=f) / SS <= max_w: return f, size
        size -= 2
    return factory(lo), lo

def ar(n): return f"{int(round(n)):,}".replace(",", ".")

# ─── Finanzas ────────────────────────────────────────────────────────────────
PMT, RATE, YEARS = 200, 0.10, 30
i = RATE / 12; N = YEARS * 12
FV = PMT * (((1 + i) ** N - 1) / i)
APORTE = PMT * N; INTERES = FV - APORTE
F_APORTE = APORTE / FV; F_INTERES = INTERES / FV

# ─── Lienzo ──────────────────────────────────────────────────────────────────
img = Image.new("RGB", (W * SS, H * SS), FROST)
d = ImageDraw.Draw(img)

d.line([(S(X0), S(72)), (S(X1), S(72))], fill=CARD_BORDER, width=max(1, SS))
mono_spaced(d, X0, 100, "— EL PODER DEL INTERÉS COMPUESTO", 18, VIOLET_H, weight="md")
text(d, X0, 158, "Lo que el tiempo le hace", GEIST_MD(54), INK_STRONG)
text(d, X0, 220, "a US$ 200 por mes.", GEIST_MD(54), INK_STRONG)
text(d, X0, 300, "De los 20 a los 50 años, al 10% anual promedio.", GEIST_RG(28), INK_BODY)

mono_spaced(d, X0, 392, "RESULTADO A LOS 50", 17, INK_MUTE)
hero = f"US$ {ar(FV)}"
hf, _ = fit(d, hero, GEIST_SB, max_w=X1 - X0, start=104, lo=70)
text(d, X0, 420, hero, hf, INK_STRONG)

# Curva
cx0, cx1 = X0, X1
cy_base, cy_top = 720, 580
pts = []
for k in range(101):
    t = YEARS * k / 100
    val = PMT * (((1 + i) ** (12 * t) - 1) / i) if t > 0 else 0
    pts.append((S(cx0 + (cx1 - cx0) * (k / 100)), S(cy_base - (val / FV) * (cy_base - cy_top))))
d.polygon(pts + [(S(cx1), S(cy_base)), (S(cx0), S(cy_base))], fill=AREA)
d.line(pts, fill=VIOLET_H, width=3 * SS, joint="curve")
ex, ey = pts[-1]
d.ellipse([ex - 6 * SS, ey - 6 * SS, ex + 6 * SS, ey + 6 * SS], fill=VIOLET_H)
d.line([(S(cx0), S(cy_base)), (S(cx1), S(cy_base))], fill=CARD_BORDER, width=max(1, SS))
for age in (20, 30, 40, 50):
    x = cx0 + (cx1 - cx0) * ((age - 20) / YEARS)
    f = JB_RG(15); wl = d.textlength(str(age), font=f)
    xpos = S(x) - wl / 2
    if age == 20: xpos = S(x)
    if age == 50: xpos = S(x) - wl
    d.text((xpos, S(cy_base + 12)), str(age), font=f, fill=INK_MUTE)

# Contraste
row_y = 848
mono_spaced(d, X0, row_y, "APORTASTE", 16, INK_MUTE)
mono_spaced(d, 0, row_y, "GENERÓ EL INTERÉS", 16, INK_MUTE, align="right", xr=X1)
text(d, X0, row_y + 26, f"US$ {ar(APORTE)}", GEIST_MD(36), INK_STRONG)
text_right(d, X1, row_y + 26, f"US$ {ar(INTERES)}", GEIST_MD(36), GREEN)

bar_y, bar_h = row_y + 96, 12
split = X0 + (X1 - X0) * F_APORTE
d.rounded_rectangle([S(X0), S(bar_y), S(X1), S(bar_y + bar_h)], radius=S(6), fill=GREEN)
d.rounded_rectangle([S(X0), S(bar_y), S(split + 6), S(bar_y + bar_h)], radius=S(6), fill=VIOLET)

text(d, X0, bar_y + 40,
     f"— Vos ponés el {round(F_APORTE*100)}%. El interés compuesto pone el {round(F_INTERES*100)}%.",
     GEIST_RG(29), INK_BODY)

# Footer — logo REAL de Rendi (mark ink sobre fondo claro, ver brand-kit/logos)
iso_y = 1194
LOGO = "/Users/nicolaspussetto/Documents/rendi 2/brand-kit/logos/rendi-mark-ink.png"
logo = Image.open(LOGO).convert("RGBA")
logo = logo.crop(logo.getchannel("A").getbbox())     # recorta el padding transparente
mark_h = 56
mark_w = round(logo.width * mark_h / logo.height)
logo = logo.resize((S(mark_w), S(mark_h)), Image.LANCZOS)
img.paste(logo, (S(X0), S(iso_y)), logo)              # alpha como máscara
tx = X0 + mark_w + 22
text(d, tx, iso_y + 6, "Rendi", GEIST_MD(30), INK_STRONG)
mono_spaced(d, tx, iso_y + 36, "RENDI.FINANCE", 16, INK_MUTE)
mono_spaced(d, 0, iso_y + 40, "SIMULACIÓN · 10% ANUAL · CAP. MENSUAL", 14, INK_MUTE, ls=0.06, align="right", xr=X1)

# Export
out_dir = "/Users/nicolaspussetto/Documents/trading/design/outputs"
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, "rendi_interes_compuesto_claro.png")
img.resize((W, H), Image.LANCZOS).save(out, "PNG", optimize=True)
print(f"FV={ar(FV)} aporte={ar(APORTE)} interes={ar(INTERES)} ({round(F_APORTE*100)}/{round(F_INTERES*100)})")
print(f"✓ {out} ({os.path.getsize(out)/1024:.1f}KB)")
