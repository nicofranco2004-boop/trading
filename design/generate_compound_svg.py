"""
Versión SVG editable del post de interés compuesto (mismo diseño que el PNG).
Self-contained: embebe Geist + JetBrains Mono como @font-face base64, así
renderiza idéntico en navegador / Figma / Illustrator sin tener las fuentes
instaladas. viewBox 1080×1350. Hex exactos del brand kit.

Nota: en esta Mac no hay renderer de SVG, así que el PNG (PIL) es el verificado;
este SVG es la fuente vectorial editable (abrir en navegador/Figma para QA).
"""

import os, base64

FONTS = "/Users/nicolaspussetto/Documents/trading/design/fonts"
OUT = "/Users/nicolaspussetto/Documents/trading/design/outputs/rendi_interes_compuesto.svg"

# ─── Finanzas + curva (misma fórmula que el PNG) ─────────────────────────────
PMT, RATE, YEARS = 200, 0.10, 30
i = RATE / 12
N = YEARS * 12
FV = PMT * (((1 + i) ** N - 1) / i)
APORTE = PMT * N
INTERES = FV - APORTE
F_APORTE = APORTE / FV
ar = lambda n: f"{int(round(n)):,}".replace(",", ".")

X0, X1 = 80, 1000
CY_BASE, CY_TOP = 720, 580
pts = []
for k in range(101):
    t = YEARS * k / 100
    val = PMT * (((1 + i) ** (12 * t) - 1) / i) if t > 0 else 0
    x = X0 + (X1 - X0) * (k / 100)
    y = CY_BASE - (val / FV) * (CY_BASE - CY_TOP)
    pts.append((round(x, 2), round(y, 2)))
line_path = "M" + " L".join(f"{x},{y}" for x, y in pts)
area_path = line_path + f" L{X1},{CY_BASE} L{X0},{CY_BASE} Z"
endx, endy = pts[-1]

# ─── Fuentes embebidas ───────────────────────────────────────────────────────
def b64(name):
    with open(os.path.join(FONTS, name), "rb") as f:
        return base64.b64encode(f.read()).decode()

faces = "".join(
    f"@font-face{{font-family:'{fam}';src:url(data:font/ttf;base64,{b64(fn)}) format('truetype');}}"
    for fam, fn in [
        ("GeistRG", "Geist-Regular.ttf"), ("GeistMD", "Geist-Medium.ttf"),
        ("GeistSB", "Geist-SemiBold.ttf"),
        ("JBRG", "JetBrainsMono-Regular.ttf"), ("JBMD", "JetBrainsMono-Medium.ttf"),
    ]
)

# ─── Ticks de edad ───────────────────────────────────────────────────────────
ticks = ""
for age in (20, 30, 40, 50):
    x = X0 + (X1 - X0) * (age - 20) / YEARS
    anchor = "start" if age == 20 else "end" if age == 50 else "middle"
    ticks += (f'<text x="{x:.1f}" y="744" font-family="JBRG" font-size="15" '
              f'fill="#5A6478" text-anchor="{anchor}">{age}</text>')

split = X0 + (X1 - X0) * F_APORTE + 6
pct_ap, pct_in = round(F_APORTE * 100), round((1 - F_APORTE) * 100)

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1350" width="1080" height="1350">
<style>{faces}
text{{font-feature-settings:'tnum' 1;}}</style>
<rect width="1080" height="1350" fill="#07090C"/>
<line x1="80" y1="72" x2="1000" y2="72" stroke="#1B2030" stroke-width="1"/>
<text x="80" y="114" font-family="JBMD" font-size="18" fill="#8B7DFF" letter-spacing="1.44">— EL PODER DEL INTERÉS COMPUESTO</text>
<text x="80" y="200" font-family="GeistMD" font-size="54" fill="#E6EAF2">Lo que el tiempo le hace</text>
<text x="80" y="262" font-family="GeistMD" font-size="54" fill="#E6EAF2">a US$ 200 por mes.</text>
<text x="80" y="322" font-family="GeistRG" font-size="28" fill="#9CA3B5">De los 20 a los 50 años, al 10% anual promedio.</text>
<text x="80" y="405" font-family="JBRG" font-size="17" fill="#5A6478" letter-spacing="1.36">RESULTADO A LOS 50</text>
<text x="80" y="500" font-family="GeistSB" font-size="100" fill="#E6EAF2">US$ {ar(FV)}</text>
<path d="{area_path}" fill="#1E1840"/>
<path d="{line_path}" fill="none" stroke="#8B7DFF" stroke-width="3" stroke-linejoin="round"/>
<circle cx="{endx}" cy="{endy}" r="5" fill="#8B7DFF"/>
<line x1="80" y1="720" x2="1000" y2="720" stroke="#1B2030" stroke-width="1"/>
{ticks}
<text x="80" y="860" font-family="JBRG" font-size="16" fill="#5A6478" letter-spacing="1.28">APORTASTE</text>
<text x="1000" y="860" font-family="JBRG" font-size="16" fill="#5A6478" letter-spacing="1.28" text-anchor="end">GENERÓ EL INTERÉS</text>
<text x="80" y="902" font-family="GeistMD" font-size="36" fill="#E6EAF2">US$ {ar(APORTE)}</text>
<text x="1000" y="902" font-family="GeistMD" font-size="36" fill="#21D07A" text-anchor="end">US$ {ar(INTERES)}</text>
<rect x="80" y="944" width="920" height="12" rx="6" fill="#21D07A"/>
<rect x="80" y="944" width="{split - 80:.1f}" height="12" rx="6" fill="#8B7DFF"/>
<text x="80" y="1007" font-family="GeistRG" font-size="29" fill="#9CA3B5">— Vos ponés el {pct_ap}%. El interés compuesto pone el {pct_in}%.</text>
<rect x="80" y="1196" width="56" height="56" rx="8" fill="#8B7DFF"/>
<text x="108" y="1237" font-family="GeistSB" font-size="34" fill="#07090C" text-anchor="middle">R</text>
<text x="156" y="1226" font-family="GeistMD" font-size="30" fill="#E6EAF2">Rendi</text>
<text x="156" y="1250" font-family="JBRG" font-size="16" fill="#5A6478" letter-spacing="1.28">RENDI.FINANCE</text>
<text x="1000" y="1250" font-family="JBRG" font-size="14" fill="#5A6478" letter-spacing="0.84" text-anchor="end">SIMULACIÓN · 10% ANUAL · CAP. MENSUAL</text>
</svg>'''

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(svg)

# Validación de buen formato XML
import xml.dom.minidom as M
M.parseString(svg.encode("utf-8"))
print(f"✓ SVG OK ({os.path.getsize(OUT)/1024:.0f}KB) → {OUT}")
