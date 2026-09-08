"""
Anuncio Story (1080×1920, 9:16) — ángulo "la IA que entiende tu cartera".
Pieza pensada para Meta Ads (IG/FB Stories).

Estructura (de arriba hacia abajo):
  1. Hook / problema      — "Tenés los datos. Te faltan las respuestas."
  2. Chat simulado        — el usuario le pregunta a la IA de Rendi sobre su
                            cartera y la IA responde con insights reales.
  3. CTA                  — "La IA que entiende tu cartera." + rendi.finance

El contenido del chat está anclado en respuestas REALES del feature /ai/analyze
(ver DEMO_AI_RESULTS en frontend/src/utils/demo.js): outperformance vs dólar,
ilusión de diversificación (60% del P&L en 2 tickers) y riesgo de concentración
en NVDA (28% del peso, ~7 pts de TWR si cae 25%). Nada inventado.

Voz del manual: dato primero, voseo profesional, sentence case, cero emoji,
cero motivacional. Violeta = acción/IA. Bold = la cifra que importa.
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

# ─── Paths ───────────────────────────────────────────────────────────────────
FONTS_DIR = (
    "/Users/nicolaspussetto/Library/Application Support/Claude/"
    "local-agent-mode-sessions/skills-plugin/"
    "bcfbadf3-5949-46c4-95ea-f77e7e18d7ad/"
    "6a7d8d68-f39a-4be8-86c7-653fd22de85c/skills/canvas-design/canvas-fonts/"
)
OUT_DIR = "/Users/nicolaspussetto/Documents/trading/design"

# ─── Format ──────────────────────────────────────────────────────────────────
SW, SH = 1080, 1920

# ─── Colors (alineados con tailwind del producto) ────────────────────────────
BG = (10, 11, 14)
BG_GLOW = (16, 14, 26)
INK_0 = (230, 234, 242)
INK_1 = (196, 203, 217)
INK_2 = (150, 156, 172)
INK_3 = (96, 106, 126)
INK_4 = (40, 46, 60)
VIOLET = (139, 125, 255)
RENDI_POS = (54, 211, 153)
RENDI_NEG = (231, 92, 92)
AMBER = (230, 180, 70)
SKY = (91, 157, 249)

AI_FILL = (16, 18, 25)
AI_BORDER = (52, 58, 76)
USER_FILL = (30, 26, 52)
USER_BORDER = (104, 92, 192)

# panel "snapshot de cartera" (look del producto)
CARD_FILL = (15, 17, 23)
CARD_BORDER = (44, 50, 66)
LINE = (32, 37, 50)


# ─── Fonts ───────────────────────────────────────────────────────────────────
def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS_DIR, name), size)

F_SANS_BOLD = lambda s: font("InstrumentSans-Bold.ttf", s)
F_SANS_REG  = lambda s: font("InstrumentSans-Regular.ttf", s)
F_MONO_REG  = lambda s: font("GeistMono-Regular.ttf", s)
F_MONO_BOLD = lambda s: font("GeistMono-Bold.ttf", s)


# ─── Low-level helpers ───────────────────────────────────────────────────────
def spaced_width(draw, text, font_obj, spacing=3):
    if not text:
        return 0
    return sum(draw.textlength(c, font=font_obj) for c in text) + spacing * (len(text) - 1)

def draw_spaced(draw, text, x, y, font_obj, fill, spacing=3):
    cx = x
    for ch in text:
        draw.text((cx, y), ch, font=font_obj, fill=fill)
        cx += draw.textlength(ch, font=font_obj) + spacing

def center(draw, text, y, font_obj, fill):
    w = draw.textlength(text, font=font_obj)
    draw.text((SW / 2 - w / 2, y), text, font=font_obj, fill=fill)
    return w

def glyph_h(draw, font_obj):
    b = draw.textbbox((0, 0), "ÁgjpqÑ", font=font_obj)
    return b[3] - b[1]


def build_canvas():
    img = Image.new("RGB", (SW, SH), BG)
    d = ImageDraw.Draw(img)
    # gradiente sutil arriba y abajo
    for y in range(SH):
        t = 0
        if y < 620:
            t = (1 - y / 620) * 0.55
        elif y > SH - 520:
            t = ((y - (SH - 520)) / 520) * 0.30
        if t:
            r = int(BG[0] + (BG_GLOW[0] - BG[0]) * t)
            g = int(BG[1] + (BG_GLOW[1] - BG[1]) * t)
            b = int(BG[2] + (BG_GLOW[2] - BG[2]) * t)
            d.line([(0, y), (SW, y)], fill=(r, g, b))
    # glow violeta radial detrás del chat
    glow = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = SW // 2, 1020
    for r in range(520, 0, -12):
        a = int((1 - r / 520) * 14)
        gd.ellipse([cx - r, cy - r, cx + int(r * 0.9), cy + int(r * 0.9)], fill=(*VIOLET, a))
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    return Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")


def draw_sparkle(draw, cx, cy, r, color):
    ri = r * 0.34
    pts = [
        (cx, cy - r), (cx + ri, cy - ri), (cx + r, cy), (cx + ri, cy + ri),
        (cx, cy + r), (cx - ri, cy + ri), (cx - r, cy), (cx - ri, cy - ri),
    ]
    draw.polygon(pts, fill=color)


def draw_tri(draw, cx, cy, s, color, up=True):
    """Triángulo lleno (▲ / ▼) — señal de variación al instante."""
    if up:
        pts = [(cx, cy - s), (cx - s * 0.92, cy + s * 0.7), (cx + s * 0.92, cy + s * 0.7)]
    else:
        pts = [(cx, cy + s), (cx - s * 0.92, cy - s * 0.7), (cx + s * 0.92, cy - s * 0.7)]
    draw.polygon(pts, fill=color)


def draw_sparkline(draw, x, y, w, h, color, pts_norm):
    """Mini-curva ascendente con relleno suave — 'esto es un gráfico de mercado'."""
    n = len(pts_norm)
    coords = [(x + w * i / (n - 1), y + h * (1 - v)) for i, v in enumerate(pts_norm)]
    # relleno de área
    area = coords + [(x + w, y + h), (x, y + h)]
    draw.polygon(area, fill=(*color, 26))
    # línea
    draw.line(coords, fill=color, width=3, joint="curve")
    # punto final
    ex, ey = coords[-1]
    draw.ellipse([ex - 5, ey - 5, ex + 5, ey + 5], fill=color)


def bench_chip(draw, right_x, top, label, value):
    """Chip de benchmark, alineado a la derecha. label=sky (benchmark), valor=verde."""
    lf, vf = F_MONO_REG(19), F_SANS_BOLD(22)
    lw = draw.textlength(label, font=lf)
    vw = draw.textlength(value, font=vf)
    gap, padx, h = 14, 16, 40
    cw = padx * 2 + lw + gap + vw
    x0 = right_x - cw
    draw.rounded_rectangle([x0, top, x0 + cw, top + h], radius=10,
                           fill=(255, 255, 255, 6), outline=(*SKY, 70), width=2)
    cy = top + h / 2
    draw.text((x0 + padx, cy - glyph_h(draw, lf) / 2 - 2), label, font=lf, fill=SKY)
    draw.text((x0 + padx + lw + gap, cy - glyph_h(draw, vf) / 2 - 2), value, font=vf, fill=RENDI_POS)
    return cw


def holdings_panel(draw, top):
    """Snapshot de cartera estilo producto: total + benchmark + tickers con P&L.

    Es el bloque que hace que se lea 'app de inversiones en acciones' al instante:
    valor de cartera, comparación vs S&P 500, mini-gráfico y tickers en verde/rojo.
    """
    x0, x1 = M, SW - M
    pad = 32
    H = 268
    # tarjeta
    draw.rounded_rectangle([x0, top, x1, top + H], radius=26,
                           fill=CARD_FILL, outline=CARD_BORDER, width=2)

    # ── header: etiqueta + total + sparkline ──
    lf = F_MONO_REG(19)
    draw_spaced(draw, "TU CARTERA · 12 ACTIVOS", x0 + pad, top + 26, lf, INK_3, 2)
    tf = F_SANS_BOLD(48)
    total = "US$ 22.300"
    draw.text((x0 + pad, top + 54), total, font=tf, fill=INK_0)
    tw = draw.textlength(total, font=tf)
    # sparkline a la derecha del total
    spk = [0.10, 0.18, 0.12, 0.30, 0.26, 0.45, 0.52, 0.48, 0.66, 0.74, 0.70, 0.92]
    draw_sparkline(draw, x0 + pad + tw + 34, top + 56, 150, 50, RENDI_POS, spk)

    # ── benchmark chips (arriba a la derecha) ──
    bench_chip(draw, x1 - pad, top + 28, "vs S&P 500", "+48.9%")
    bench_chip(draw, x1 - pad, top + 76, "vs dólar", "+75.8%")

    # ── divisor ──
    dy = top + 150
    draw.line([(x0 + pad, dy), (x1 - pad, dy)], fill=LINE, width=2)

    # ── fila de tickers con P&L (verde/rojo) ──
    tickers = [
        ("NVDA", "+29%", True),
        ("AAPL", "+18%", True),
        ("BTC",  "+16%", True),
        ("SOL",  "−14%", False),
    ]
    inner = (x1 - x0) - pad * 2
    cw = inner / len(tickers)
    sym_f = F_MONO_BOLD(29)
    pnl_f = F_SANS_BOLD(25)
    ty = top + 176
    for i, (sym, pnl, up) in enumerate(tickers):
        cx = x0 + pad + i * cw
        draw.text((cx, ty), sym, font=sym_f, fill=INK_0)
        col = RENDI_POS if up else RENDI_NEG
        tri_x = cx + 9
        tri_y = ty + 50
        draw_tri(draw, tri_x, tri_y, 8, col, up=up)
        draw.text((cx + 22, ty + 38), pnl, font=pnl_f, fill=col)
    return top + H


# ─── Rich (negrita inline con **) ────────────────────────────────────────────
def parse_rich(text):
    out = []
    for i, seg in enumerate(text.split("**")):
        bold = (i % 2 == 1)
        for w in seg.split(" "):
            if w:
                out.append((w, bold))
    return out

def layout_rich(draw, tokens, fr, fb, max_w):
    space_w = draw.textlength(" ", font=fr)
    lines, cur, cur_w = [], [], 0
    for word, bold in tokens:
        f = fb if bold else fr
        ww = draw.textlength(word, font=f)
        add = ww if not cur else space_w + ww
        if cur and cur_w + add > max_w:
            lines.append(cur)
            cur, cur_w = [(word, bold, ww)], ww
        else:
            cur.append((word, bold, ww))
            cur_w += add
    if cur:
        lines.append(cur)
    widths = [sum(t[2] for t in ln) + space_w * (len(ln) - 1) for ln in lines]
    return lines, (max(widths) if widths else 0)

def draw_rich(draw, lines, x, y, fr, fb, color, bold_color, lh):
    space_w = draw.textlength(" ", font=fr)
    for ln in lines:
        cx = x
        for word, bold, ww in ln:
            f = fb if bold else fr
            draw.text((cx, y), word, font=f, fill=(bold_color if bold else color))
            cx += ww + space_w
        y += lh
    return y


# ─── Chat bubbles ────────────────────────────────────────────────────────────
M = 72
AVA = 56
PAD = 26
LH = 44
AI_TEXT_MAXW = 650
USER_TEXT_MAXW = 540

def ai_bubble(draw, text, top, label="Rendi · IA", show_avatar=True, maxw=AI_TEXT_MAXW):
    bx = M + AVA + 20
    if show_avatar:
        # avatar + etiqueta (primer mensaje de la IA)
        ax, ay = M, top
        draw.rounded_rectangle([ax, ay, ax + AVA, ay + AVA], radius=16, fill=VIOLET)
        draw_sparkle(draw, ax + AVA / 2, ay + AVA / 2, AVA * 0.30, (246, 247, 252))
        draw.text((bx, top + 3), label, font=F_MONO_REG(20), fill=VIOLET)
        btop = top + 40
    else:
        # mensaje consecutivo de la IA — sin avatar, alineado al mismo margen
        btop = top
    fr, fb = F_SANS_REG(30), F_SANS_BOLD(30)
    # soporta saltos de línea explícitos ("\n") para listas; cada párrafo wrappea solo
    lines, mw = [], 0
    for para in text.split("\n"):
        plines, pmw = layout_rich(draw, parse_rich(para), fr, fb, maxw)
        lines.extend(plines)
        mw = max(mw, pmw)
    gh = glyph_h(draw, fr)
    bw = mw + PAD * 2
    bh = (len(lines) - 1) * LH + gh + PAD * 2
    draw.rounded_rectangle([bx, btop, bx + bw, btop + bh], radius=24,
                           fill=AI_FILL, outline=AI_BORDER, width=2)
    draw_rich(draw, lines, bx + PAD, btop + PAD, fr, fb, INK_1, INK_0, LH)
    return btop + bh

def user_bubble(draw, text, top):
    fr, fb = F_SANS_REG(32), F_SANS_BOLD(32)
    lines, maxw = layout_rich(draw, parse_rich(text), fr, fb, USER_TEXT_MAXW)
    gh = glyph_h(draw, fr)
    bw = maxw + PAD * 2
    bh = (len(lines) - 1) * LH + gh + PAD * 2
    bx = (SW - M) - bw
    draw.rounded_rectangle([bx, top, bx + bw, top + bh], radius=24,
                           fill=USER_FILL, outline=USER_BORDER, width=2)
    # etiqueta "VOS" mono chiquita arriba a la derecha
    lf = F_MONO_REG(18)
    lw = spaced_width(draw, "VOS", lf, 3)
    draw_spaced(draw, "VOS", (SW - M) - lw, top - 28, lf, INK_3, 3)
    draw_rich(draw, lines, bx + PAD, top + PAD, fr, fb, INK_0, INK_0, LH)
    return top + bh


def ghost_chip(draw, text, top):
    """Chip fantasma de follow-up sugerido (UX real: el chat sigue)."""
    f = F_SANS_REG(25)
    spark_w = 30
    tw = draw.textlength(text, font=f)
    pad_x, h = 26, 60
    cw = spark_w + tw + pad_x * 2
    cx = M + AVA + 20
    draw.rounded_rectangle([cx, top, cx + cw, top + h], radius=h // 2,
                           fill=(*VIOLET, 16), outline=(*VIOLET, 150), width=2)
    draw_sparkle(draw, cx + pad_x + 7, top + h / 2, 9, VIOLET)
    draw.text((cx + pad_x + spark_w, top + (h - glyph_h(draw, f)) / 2 - 4),
              text, font=f, fill=VIOLET)
    return top + h


# ─── Compose ─────────────────────────────────────────────────────────────────
def generate():
    img = build_canvas()
    draw = ImageDraw.Draw(img, "RGBA")

    eb = F_MONO_REG(22)

    # ── Marca (top) ──
    center(draw, "rendi", 96, F_SANS_BOLD(44), INK_0)
    draw.line([(SW / 2 - 15, 160), (SW / 2 + 15, 160)], fill=VIOLET, width=3)

    # ── Hook / problema ──
    ew = spaced_width(draw, "EL PROBLEMA", eb, 4)
    draw_spaced(draw, "EL PROBLEMA", SW / 2 - ew / 2, 212, eb, INK_3, 4)
    hf = F_SANS_BOLD(58)
    center(draw, "Tenés los datos.", 262, hf, INK_0)
    center(draw, "Te faltan las respuestas.", 330, hf, VIOLET)

    # ── Snapshot de cartera: hace que se lea "inversiones en acciones" al instante ──
    holdings_panel(draw, 432)

    # ── Bridge eyebrow ──
    bridge = "VOS PREGUNTÁS · LA IA RESPONDE"
    bw = spaced_width(draw, bridge, eb, 3)
    draw_spaced(draw, bridge, SW / 2 - bw / 2, 748, eb, INK_2, 3)

    # ── Chat: la IA detecta sesgos de comportamiento (feature estrella) ──
    y = user_bubble(draw, "¿Detectás algún sesgo en mi forma de operar?", 812)
    y = ai_bubble(draw,
                  "Detecté cuatro:\n"
                  "**1. Falsa diversificación:** si una cae, caen todas.\n"
                  "**2. Operás para recuperar:** entrás de más tras perder.\n"
                  "**3. Horizontes mezclados:** corto y largo se pisan.\n"
                  "**4. Comisiones** que erosionan tu edge.",
                  y + 34, show_avatar=True, maxw=790)
    y = ai_bubble(draw,
                  "Empezá por **las comisiones:** es el más fácil de corregir "
                  "y se nota rápido en tu rendimiento.",
                  y + 16, show_avatar=False, maxw=790)

    # ── CTA (dentro de la safe-zone; abajo Meta superpone su botón) ──
    vf = F_SANS_BOLD(40)
    center(draw, "La IA que entiende tu cartera.", 1532, vf, INK_0)

    cta = "Probalo en rendi.finance"
    cf = F_SANS_BOLD(34)
    cw = draw.textlength(cta, font=cf)
    px, py = 40, 24
    btn_w, btn_h = cw + px * 2, cf.size + py * 2
    bx = (SW - btn_w) / 2
    by = 1608
    draw.rounded_rectangle([bx, by, bx + btn_w, by + btn_h], radius=btn_h // 2, fill=VIOLET)
    draw.text((bx + px, by + py - 4), cta, font=cf, fill=(15, 12, 30))

    out = os.path.join(OUT_DIR, "rendi_ad_story_ia.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ ad story IA: {out} ({os.path.getsize(out)/1024:.1f}KB)")


if __name__ == "__main__":
    generate()
