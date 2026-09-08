"""
Post feed 4:5 (1080×1350) — El poder del interés compuesto.
Estética Rendi dark premium (Bloomberg moderno). Brand kit al 100%:
hex exactos, Geist (sans) + JetBrains Mono (labels MAYÚSCULA / números técnicos),
jerarquía extrema, whitespace, radius ≤8, borde 1px, sin glow ni pastel.

Escenario: US$ 250/mes · 10% anual (cap. mensual) · de los 20 a los 70 (600 aportes).
Render: PIL con las .ttf reales (design/fonts/), supersampling 2x → 1080×1350.
"""

import os
from PIL import Image, ImageDraw, ImageFont

# ─── Geometría ───────────────────────────────────────────────────────────────
W, H = 1080, 1350
SS = 2                      # supersampling para bordes/curvas nítidas
MARGIN = 80
X0, X1 = MARGIN, W - MARGIN  # 80 … 1000  (ancho útil 920)

# ─── Paleta (hex exactos del brand kit) ──────────────────────────────────────
INK         = (0x07, 0x09, 0x0C)
CHARCOAL    = (0x0D, 0x10, 0x15)
SLATE       = (0x14, 0x19, 0x23)
LINE        = (0x1B, 0x20, 0x30)
TXT0        = (0xE6, 0xEA, 0xF2)   # primario
TXT1        = (0x9C, 0xA3, 0xB5)   # secundario
TXT2        = (0x5A, 0x64, 0x78)   # tertiary / dim
VIOLET      = (0x8B, 0x7D, 0xFF)
VIOLET_DEEP = (0x1E, 0x18, 0x40)
POS         = (0x21, 0xD0, 0x7A)
NEG         = (0xFF, 0x53, 0x60)

FONTS = "/Users/nicolaspussetto/Documents/trading/design/fonts"

def _f(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), int(size * SS))

GEIST_RG = lambda s: _f("Geist-Regular.ttf", s)
GEIST_MD = lambda s: _f("Geist-Medium.ttf", s)
GEIST_SB = lambda s: _f("Geist-SemiBold.ttf", s)
JB_RG    = lambda s: _f("JetBrainsMono-Regular.ttf", s)
JB_MD    = lambda s: _f("JetBrainsMono-Medium.ttf", s)

def S(v):           # escala una coordenada de diseño (1080-space) → canvas 2x
    return int(round(v * SS))

# ─── Helpers ─────────────────────────────────────────────────────────────────
def text(d, x, y, s, font, fill):
    d.text((S(x), S(y)), s, font=font, fill=fill)

def tw(d, s, font):
    return d.textlength(s, font=font) / SS      # ancho en design-space

def text_right(d, xr, y, s, font, fill):
    d.text((S(xr) - d.textlength(s, font=font), S(y)), s, font=font, fill=fill)

def mono_spaced(d, x, y, s, size, fill, weight="rg", ls=0.08, align="left", xr=None):
    """Texto mono con letter-spacing (em). align='right' usa xr como borde derecho."""
    f = JB_MD(size) if weight == "md" else JB_RG(size)
    sp = size * ls * SS
    total = sum(d.textlength(c, font=f) for c in s) + sp * (len(s) - 1)
    sx = S(xr) - total if align == "right" else S(x)
    cx = sx
    for c in s:
        d.text((cx, S(y)), c, font=f, fill=fill)
        cx += d.textlength(c, font=f) + sp
    return total / SS

def fit(d, s, factory, max_w, start, lo=40):
    """Mayor tamaño ≤ start cuyo ancho entre en max_w (design-space)."""
    size = start
    while size > lo:
        f = factory(size)
        if d.textlength(s, font=f) / SS <= max_w:
            return f, size
        size -= 2
    return factory(lo), lo

def ar(n):
    return f"{int(round(n)):,}".replace(",", ".")     # 4331482 → 4.331.482

# ─── Finanzas ────────────────────────────────────────────────────────────────
PMT, RATE, YEARS = 200, 0.10, 30
i = RATE / 12
N = YEARS * 12
FV = PMT * (((1 + i) ** N - 1) / i)
APORTE = PMT * N
INTERES = FV - APORTE
F_APORTE = APORTE / FV
F_INTERES = INTERES / FV

# ─── Lienzo ──────────────────────────────────────────────────────────────────
img = Image.new("RGB", (W * SS, H * SS), INK)
d = ImageDraw.Draw(img)

# Hairline superior
d.line([(S(X0), S(72)), (S(X1), S(72))], fill=LINE, width=max(1, SS))

# Label superior (mono violeta, formato "— NOMBRE")
mono_spaced(d, X0, 100, "— EL PODER DEL INTERÉS COMPUESTO", 18, VIOLET, weight="md", ls=0.08)

# Titular (Geist Medium)
text(d, X0, 158, "Lo que el tiempo le hace", GEIST_MD(54), TXT0)
text(d, X0, 220, "a US$ 200 por mes.", GEIST_MD(54), TXT0)

# Subtítulo (Geist Regular, secundario)
text(d, X0, 300, "De los 20 a los 50 años, al 10% anual promedio.", GEIST_RG(28), TXT1)

# ─── Héroe: resultado ────────────────────────────────────────────────────────
mono_spaced(d, X0, 392, "RESULTADO A LOS 50", 17, TXT2, ls=0.08)
hero = f"US$ {ar(FV)}"
hf, _ = fit(d, hero, GEIST_SB, max_w=X1 - X0, start=104, lo=70)
text(d, X0, 420, hero, hf, TXT0)

# ─── Curva exponencial (sparkline) ───────────────────────────────────────────
cx0, cx1 = X0, X1
cy_base, cy_top = 720, 580           # baseline / tope del área de la curva
pts = []
steps = 100
for k in range(steps + 1):
    t = YEARS * k / steps
    val = PMT * (((1 + i) ** (12 * t) - 1) / i) if t > 0 else 0
    x = cx0 + (cx1 - cx0) * (k / steps)
    y = cy_base - (val / FV) * (cy_base - cy_top)
    pts.append((S(x), S(y)))

# Área bajo la curva (violeta deep)
poly = pts + [(S(cx1), S(cy_base)), (S(cx0), S(cy_base))]
d.polygon(poly, fill=VIOLET_DEEP)
# Línea de la curva
d.line(pts, fill=VIOLET, width=3 * SS, joint="curve")
# Punto final
ex, ey = pts[-1]
d.ellipse([ex - 6 * SS, ey - 6 * SS, ex + 6 * SS, ey + 6 * SS], fill=VIOLET)
# Baseline
d.line([(S(cx0), S(cy_base)), (S(cx1), S(cy_base))], fill=LINE, width=max(1, SS))
# Ticks de edad
for age in (20, 30, 40, 50):
    t = age - 20
    x = cx0 + (cx1 - cx0) * (t / YEARS)
    lbl = str(age)
    f = JB_RG(15)
    wlbl = d.textlength(lbl, font=f)
    xpos = S(x) - wlbl / 2
    if age == 20:
        xpos = S(x)
    if age == 50:
        xpos = S(x) - wlbl
    d.text((xpos, S(cy_base + 12)), lbl, font=f, fill=TXT2)

# ─── Contraste aporte vs interés ─────────────────────────────────────────────
row_y = 848
mono_spaced(d, X0, row_y, "APORTASTE", 16, TXT2, ls=0.08)
mono_spaced(d, 0, row_y, "GENERÓ EL INTERÉS", 16, TXT2, ls=0.08, align="right", xr=X1)
text(d, X0, row_y + 26, f"US$ {ar(APORTE)}", GEIST_MD(36), TXT0)
text_right(d, X1, row_y + 26, f"US$ {ar(INTERES)}", GEIST_MD(36), POS)

# Barra apilada (aporte violeta · interés verde)
bar_y, bar_h = row_y + 96, 12
split = X0 + (X1 - X0) * F_APORTE
d.rounded_rectangle([S(X0), S(bar_y), S(X1), S(bar_y + bar_h)], radius=S(6), fill=POS)
d.rounded_rectangle([S(X0), S(bar_y), S(split + 6), S(bar_y + bar_h)], radius=S(6), fill=VIOLET)

# Insight
pct_ap = round(F_APORTE * 100)
pct_in = round(F_INTERES * 100)
text(d, X0, bar_y + 40, f"— Vos ponés el {pct_ap}%. El interés compuesto pone el {pct_in}%.",
     GEIST_RG(29), TXT1)

# ─── Footer ──────────────────────────────────────────────────────────────────
iso_y = 1194
LOGO = "/Users/nicolaspussetto/Documents/rendi 2/brand-kit/logos/rendi-mark-violet.png"
logo = Image.open(LOGO).convert("RGBA")
logo = logo.crop(logo.getchannel("A").getbbox())     # recorta el padding transparente
mark_h = 56
mark_w = round(logo.width * mark_h / logo.height)
logo = logo.resize((S(mark_w), S(mark_h)), Image.LANCZOS)
img.paste(logo, (S(X0), S(iso_y)), logo)              # alpha como máscara
tx = X0 + mark_w + 22
text(d, tx, iso_y + 6, "Rendi", GEIST_MD(30), TXT0)
mono_spaced(d, tx, iso_y + 36, "RENDI.FINANCE", 16, TXT2, ls=0.08)
# Fine print (supuestos)
mono_spaced(d, 0, iso_y + 40, "SIMULACIÓN · 10% ANUAL · CAP. MENSUAL", 14, TXT2,
            ls=0.06, align="right", xr=X1)

# ─── Export ──────────────────────────────────────────────────────────────────
out_dir = "/Users/nicolaspussetto/Documents/trading/design/outputs"
os.makedirs(out_dir, exist_ok=True)
final = img.resize((W, H), Image.LANCZOS)
out = os.path.join(out_dir, "rendi_interes_compuesto.png")
final.save(out, "PNG", optimize=True)
print(f"FV={ar(FV)}  aporte={ar(APORTE)}  interes={ar(INTERES)}  ({pct_ap}/{pct_in})")
print(f"✓ {out} ({os.path.getsize(out)/1024:.1f}KB)")
