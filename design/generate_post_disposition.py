"""
Post 2 — Disposition effect (insight conductual).
Carousel de 3 slides en 1080×1350 (4:5 feed IG), aesthetic "Nocturnal Precision".

Slides:
  - rendi_post_disposition_1.png — HOOK + card real de Rendi (collapsed)
  - rendi_post_disposition_2.png — EVIDENCIA: el modal real (holding, ratio, samples)
  - rendi_post_disposition_3.png — CTA: "Rendi lo mide."

Las slides 1 y 2 recrean fielmente la UI del producto (página Comportamiento
+ modal de detalle del detector disposition_effect). Copy y data tomados de
backend/behavioral.py y frontend/src/pages/Behavioral.jsx.

Voz del manual: dato primero, voseo profesional, sentence case, cero emoji.
Verde/rojo solo en datos con polaridad. Violeta solo en acción/énfasis.
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

# ─── Paths ─────────────────────────────────────────────────────────────────
FONTS_DIR = (
    "/Users/nicolaspussetto/Library/Application Support/Claude/"
    "local-agent-mode-sessions/skills-plugin/"
    "bcfbadf3-5949-46c4-95ea-f77e7e18d7ad/"
    "6a7d8d68-f39a-4be8-86c7-653fd22de85c/skills/canvas-design/canvas-fonts/"
)
OUT_DIR = "/Users/nicolaspussetto/Documents/trading/design"
W, H = 1080, 1350

# ─── Colors (alineados con el producto: tailwind.config.js) ──────────────────
BG = (10, 11, 14)            # bg-0 ink
BG_GLOW = (16, 14, 26)
CARD_BG = (15, 17, 23)       # bg-1 charcoal — superficie de card
CARD_BG_2 = (20, 25, 35)     # bg-2 slate — superficie elevada (sample panels)
CARD_BG_PLUS = (22, 18, 38)  # violet deep tint
INK_0 = (230, 234, 242)      # texto principal
INK_1 = (195, 202, 216)      # texto secundario
INK_2 = (150, 156, 172)      # terciario / captions
INK_3 = (90, 100, 120)       # hints
INK_4 = (40, 46, 60)         # líneas / bordes
VIOLET = (139, 125, 255)
RENDI_POS = (54, 211, 153)
RENDI_NEG = (231, 92, 92)
AMBER = (230, 180, 70)


# ─── Fonts ─────────────────────────────────────────────────────────────────
def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS_DIR, name), size)

F_SANS_BOLD = lambda s: font("InstrumentSans-Bold.ttf", s)
F_SANS_REG  = lambda s: font("InstrumentSans-Regular.ttf", s)
F_MONO_BOLD = lambda s: font("GeistMono-Bold.ttf", s)
F_MONO_REG  = lambda s: font("GeistMono-Regular.ttf", s)


# ─── Helpers de texto ────────────────────────────────────────────────────────
def draw_spaced_text(draw, text, x, y, font_obj, fill, spacing=4):
    cursor = x
    for ch in text:
        draw.text((cursor, y), ch, font=font_obj, fill=fill)
        cursor += draw.textlength(ch, font=font_obj) + spacing
    return cursor - x

def spaced_width(draw, text, font_obj, spacing=4):
    if not text:
        return 0
    return sum(draw.textlength(ch, font=font_obj) for ch in text) + spacing * (len(text) - 1)

def draw_centered_segments(draw, segments, y, font_obj):
    """Dibuja una línea centrada compuesta por (texto, color)."""
    total = sum(draw.textlength(t, font=font_obj) for t, _ in segments)
    x = (W - total) / 2
    for t, c in segments:
        draw.text((x, y), t, font=font_obj, fill=c)
        x += draw.textlength(t, font=font_obj)

def wrap_text(draw, text, font_obj, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font_obj) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ─── Iconografía (aprox. lucide, trazo fino) ─────────────────────────────────
def icon_trending_down(draw, x, y, size, color, w=3):
    """lucide trending-down — línea quebrada hacia abajo-derecha + esquina."""
    pts = [
        (x, y + size * 0.30),
        (x + size * 0.36, y + size * 0.60),
        (x + size * 0.56, y + size * 0.42),
        (x + size, y + size * 0.74),
    ]
    draw.line(pts, fill=color, width=w, joint="curve")
    ex, ey = x + size, y + size * 0.74
    al = size * 0.30
    draw.line([(ex - al, ey), (ex, ey)], fill=color, width=w)
    draw.line([(ex, ey - al), (ex, ey)], fill=color, width=w)

def icon_chevron_right(draw, x, y, size, color, w=2):
    draw.line([(x, y), (x + size * 0.55, y + size * 0.5)], fill=color, width=w)
    draw.line([(x + size * 0.55, y + size * 0.5), (x, y + size)], fill=color, width=w)


# ─── Pill (chip de severidad) ────────────────────────────────────────────────
def pill_width(draw, text, dot=True):
    f = F_MONO_BOLD(17)
    tw = spaced_width(draw, text, f, spacing=1)
    return (16 if dot else 0) + tw + 28

def draw_pill(draw, x, y, text, color, dot=True):
    f = F_MONO_BOLD(17)
    tw = spaced_width(draw, text, f, spacing=1)
    h = 32
    w = (16 if dot else 0) + tw + 28
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2,
                           fill=(*color, 26), outline=(*color, 95), width=1)
    cx = x + 14
    if dot:
        dr = 4
        dcy = y + h / 2
        draw.ellipse([cx, dcy - dr, cx + dr * 2, dcy + dr], fill=color)
        cx += 16
    draw_spaced_text(draw, text, cx, y + (h - 19) / 2, f, color, spacing=1)
    return w


# ─── Base canvas ─────────────────────────────────────────────────────────────
def build_base_canvas():
    img = Image.new("RGB", (W, H), BG)
    dg = ImageDraw.Draw(img)
    for y in range(H):
        if y < 500:
            t = 1 - (y / 500)
            r = int(BG[0] + (BG_GLOW[0] - BG[0]) * t * 0.5)
            g = int(BG[1] + (BG_GLOW[1] - BG[1]) * t * 0.5)
            b = int(BG[2] + (BG_GLOW[2] - BG[2]) * t * 0.5)
            dg.line([(0, y), (W, y)], fill=(r, g, b))
        elif y > H - 350:
            t = (y - (H - 350)) / 350
            r = int(BG[0] + (BG_GLOW[0] - BG[0]) * t * 0.3)
            g = int(BG[1] + (BG_GLOW[1] - BG[1]) * t * 0.3)
            b = int(BG[2] + (BG_GLOW[2] - BG[2]) * t * 0.3)
            dg.line([(0, y), (W, y)], fill=(r, g, b))

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r in range(380, 0, -10):
        alpha = int((1 - r / 380) * 16)
        gd.ellipse([W // 2 - r, H // 2 - r, W // 2 + r, H // 2 + r], fill=(*VIOLET, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    return img


def draw_header(draw, eyebrow_text):
    HEADER_TOP = 80
    logo_font = F_SANS_BOLD(44)
    logo_w = draw.textlength("rendi", font=logo_font)
    draw.text((W / 2 - logo_w / 2, HEADER_TOP), "rendi", font=logo_font, fill=INK_0)
    ul_y = HEADER_TOP + 64
    draw.line([(W / 2 - 14, ul_y), (W / 2 + 14, ul_y)], fill=VIOLET, width=2)

    eyebrow_font = F_MONO_REG(20)
    ey_w = spaced_width(draw, eyebrow_text, eyebrow_font, spacing=3)
    draw_spaced_text(draw, eyebrow_text, W / 2 - ey_w / 2, HEADER_TOP + 100, eyebrow_font, VIOLET, spacing=3)


def draw_footer(draw, current, total=3):
    dot_size, gap = 8, 14
    total_w = (dot_size * total) + (gap * (total - 1))
    start_x = (W - total_w) / 2
    y = H - 120
    for i in range(total):
        cx = start_x + i * (dot_size + gap)
        draw.ellipse([cx, y, cx + dot_size, y + dot_size], fill=VIOLET if i == current else INK_4)
    brand_font = F_MONO_REG(22)
    brand_w = draw.textlength("rendi.finance", font=brand_font)
    draw.text((W / 2 - brand_w / 2, H - 75), "rendi.finance", font=brand_font, fill=INK_2)


# ─── Datos del detector (representativos, formato real del backend) ──────────
WIN_AVG, LOSS_AVG = 16, 71          # días
WIN_N, LOSS_N = 24, 11
RATIO = WIN_AVG / LOSS_AVG          # 0.23 (winners/losers)
INV = LOSS_AVG / WIN_AVG            # 4.4× más tiempo
TITLE = "Vendés ganadoras mucho más rápido que perdedoras"
ONE_LINER = (f"Mantenés tus perdedoras {INV:.1f}× más tiempo que tus ganadoras. "
             "Es el patrón clásico del disposition effect.")
VALUE_LABEL = f"{RATIO:.2f}× (WINNERS/LOSERS)"
SAMPLE_WINNERS = [("NVDA", 6, 412), ("MELI", 11, 188), ("AAPL", 14, 96)]
SAMPLE_LOSERS  = [("GGAL", 138, -540), ("PAMP", 102, -310), ("TSLA", 88, -224)]


def fmt_money(v):
    sign = "+" if v >= 0 else "−"
    return f"{sign}${abs(v)}"


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 1 — HOOK + card real de Rendi
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_1():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ SESGO #1 · DETECTADO POR RENDI")

    # ─── Hero headline ───────────────────────────────────────────────────────
    hero_font = F_SANS_BOLD(64)
    hero_top = 290
    draw_centered_segments(draw, [("Vendés tus ", INK_0), ("ganadoras.", RENDI_POS)], hero_top, hero_font)
    draw_centered_segments(draw, [("Aguantás tus ", INK_0), ("perdedoras.", RENDI_NEG)], hero_top + 84, hero_font)

    # ─── Card real (collapsed) — réplica de BehavioralCard severity=high ──────
    card_w = 880
    card_x = (W - card_w) / 2
    card_y = 510
    pad = 38
    inner_w = card_w - pad * 2

    title_font = F_SANS_BOLD(36)
    ol_font = F_SANS_REG(25)
    title_lines = wrap_text(draw, TITLE, title_font, inner_w)
    ol_lines = wrap_text(draw, ONE_LINER, ol_font, inner_w)

    title_lh, ol_lh = 46, 35
    header_h = 34
    body_top_gap, mid_gap, footer_gap = 34, 20, 30
    footer_h = 30
    card_h = (pad + header_h + body_top_gap
              + len(title_lines) * title_lh + mid_gap
              + len(ol_lines) * ol_lh + footer_gap
              + 1 + footer_h + pad)

    # Card container — borde rojo (severity alta) sobre bg-1
    draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h],
                           radius=14, fill=CARD_BG, outline=(*RENDI_NEG, 95), width=1)

    # Header row: icono + label  ·  pill "ALTA"
    hx = card_x + pad
    hy = card_y + pad
    icon_trending_down(draw, hx, hy + 2, 24, RENDI_NEG, w=3)
    lbl_font = F_MONO_REG(20)
    draw_spaced_text(draw, "DISPOSITION EFFECT", hx + 40, hy + 4, lbl_font, INK_3, spacing=2)
    pw = pill_width(draw, "ALTA")
    draw_pill(draw, card_x + card_w - pad - pw, hy - 2, "ALTA", RENDI_NEG)

    # Title (ink-0)
    ty = hy + header_h + body_top_gap
    for ln in title_lines:
        draw.text((hx, ty), ln, font=title_font, fill=INK_0)
        ty += title_lh

    # One-liner (ink-2)
    oy = ty + mid_gap - 6
    for ln in ol_lines:
        draw.text((hx, oy), ln, font=ol_font, fill=INK_2)
        oy += ol_lh

    # Footer divider + value_label · "Ver detalle ›"
    fy = card_y + card_h - pad - footer_h
    draw.line([(hx, fy - footer_gap + 12), (card_x + card_w - pad, fy - footer_gap + 12)],
              fill=(*INK_4, 160), width=1)
    draw_spaced_text(draw, VALUE_LABEL, hx, fy + 4, F_MONO_REG(20), INK_1, spacing=1)
    vd_font = F_SANS_REG(22)
    vd_txt = "Ver detalle"
    vd_w = draw.textlength(vd_txt, font=vd_font)
    chev_x = card_x + card_w - pad - 16
    draw.text((chev_x - vd_w - 6, fy + 2), vd_txt, font=vd_font, fill=INK_3)
    icon_chevron_right(draw, chev_x + 2, fy + 6, 14, INK_3, w=2)

    # ─── Sub ──────────────────────────────────────────────────────────────────
    sub_y = card_y + card_h + 52
    sub_font = F_SANS_REG(28)
    for line in ["El sesgo más común del inversor.", "Tu broker no te lo muestra. Rendi sí."]:
        lw = draw.textlength(line, font=sub_font)
        draw.text((W / 2 - lw / 2, sub_y), line, font=sub_font, fill=INK_2)
        sub_y += 42

    draw_footer(draw, current=0)
    out = os.path.join(OUT_DIR, "rendi_post_disposition_1.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ disposition 1: {out} ({os.path.getsize(out)/1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 2 — EVIDENCIA (réplica del modal de detalle)
# ─────────────────────────────────────────────────────────────────────────────
def evidence_row(draw, x, y, w, label, value, value_color, count=None):
    lf = F_SANS_REG(24)
    draw.text((x, y), label, font=lf, fill=INK_2)
    vf = F_MONO_REG(24)
    cf = F_MONO_REG(20)
    ctext = f" · {count}" if count is not None else ""
    cw = draw.textlength(ctext, font=cf) if count is not None else 0
    vw = draw.textlength(value, font=vf)
    draw.text((x + w - vw - cw, y), value, font=vf, fill=value_color)
    if count is not None:
        draw.text((x + w - cw, y + 3), ctext, font=cf, fill=INK_3)


def sample_panel(draw, x, y, w, h, title, items, color):
    draw.rounded_rectangle([x, y, x + w, y + h], radius=10,
                           fill=(*CARD_BG_2, 150), outline=(*INK_4, 150), width=1)
    tf = F_MONO_REG(15)
    draw_spaced_text(draw, title, x + 18, y + 16, tf, INK_3, spacing=1)
    iy = y + 52
    af = F_MONO_REG(21)
    pf = F_MONO_BOLD(21)
    df = F_MONO_REG(19)
    for asset, days, pnl in items:
        draw.text((x + 18, iy), asset, font=af, fill=INK_1)
        ptxt = fmt_money(pnl)
        pw = draw.textlength(ptxt, font=pf)
        draw.text((x + w - 18 - pw, iy), ptxt, font=pf, fill=color)
        dtxt = f"{days}d"
        dw = draw.textlength(dtxt, font=df)
        draw.text((x + w - 18 - pw - 18 - dw, iy + 1), dtxt, font=df, fill=INK_3)
        iy += 42


def generate_slide_2():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ LA EVIDENCIA · TUS NÚMEROS")

    # ─── Panel modal ──────────────────────────────────────────────────────────
    panel_w = 900
    panel_x = (W - panel_w) / 2
    panel_y = 270
    pad = 40
    inner_x = panel_x + pad
    inner_w = panel_w - pad * 2

    panel_h = 700
    draw.rounded_rectangle([panel_x, panel_y, panel_x + panel_w, panel_y + panel_h],
                           radius=16, fill=CARD_BG, outline=(*RENDI_NEG, 80), width=1)

    # Header del modal: icono + label + pill
    hy = panel_y + pad
    icon_trending_down(draw, inner_x, hy + 2, 24, RENDI_NEG, w=3)
    draw_spaced_text(draw, "DISPOSITION EFFECT", inner_x + 40, hy + 4, F_MONO_REG(20), INK_3, spacing=2)
    pw = pill_width(draw, "ALTA")
    draw_pill(draw, panel_x + panel_w - pad - pw, hy - 2, "ALTA", RENDI_NEG)

    # Título del modal
    mt_font = F_SANS_BOLD(34)
    mt_lines = wrap_text(draw, TITLE, mt_font, inner_w)
    ty = hy + 48
    for ln in mt_lines:
        draw.text((inner_x, ty), ln, font=mt_font, fill=INK_0)
        ty += 44

    # Divider
    dv_y = ty + 18
    draw.line([(inner_x, dv_y), (inner_x + inner_w, dv_y)], fill=(*INK_4, 150), width=1)

    # Evidence rows
    ry = dv_y + 32
    evidence_row(draw, inner_x, ry, inner_w, "Ganadoras (avg holding)",
                 f"{WIN_AVG} días", RENDI_POS, count=WIN_N)
    ry += 50
    evidence_row(draw, inner_x, ry, inner_w, "Perdedoras (avg holding)",
                 f"{LOSS_AVG} días", RENDI_NEG, count=LOSS_N)
    ry += 50
    evidence_row(draw, inner_x, ry, inner_w, "Ratio",
                 f"{RATIO:.2f}× (winners/losers)", INK_0)

    # Divider 2
    dv2_y = ry + 52
    draw.line([(inner_x, dv2_y), (inner_x + inner_w, dv2_y)], fill=(*INK_4, 150), width=1)

    # Sample panels (winners / losers)
    sp_y = dv2_y + 26
    sp_gap = 24
    sp_w = (inner_w - sp_gap) / 2
    sp_h = 220
    sample_panel(draw, inner_x, sp_y, sp_w, sp_h,
                 "TOP WINNERS MÁS RÁPIDOS", SAMPLE_WINNERS, RENDI_POS)
    sample_panel(draw, inner_x + sp_w + sp_gap, sp_y, sp_w, sp_h,
                 "TOP LOSERS MÁS AGUANTADOS", SAMPLE_LOSERS, RENDI_NEG)

    # ─── Highlight strip ────────────────────────────────────────────────────
    strip_y = panel_y + panel_h + 36
    strip_w, strip_h = 900, 96
    strip_x = (W - strip_w) / 2
    draw.rounded_rectangle([strip_x, strip_y, strip_x + strip_w, strip_y + strip_h],
                           radius=16, fill=CARD_BG_PLUS, outline=(*VIOLET, 120), width=2)
    draw_centered_segments(draw, [("Aguantás tus perdedoras ", INK_1),
                                  (f"{INV:.1f}×", VIOLET), (" más tiempo.", INK_1)],
                           strip_y + 28, F_SANS_BOLD(34))

    draw_footer(draw, current=1)
    out = os.path.join(OUT_DIR, "rendi_post_disposition_2.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ disposition 2: {out} ({os.path.getsize(out)/1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 3 — CTA
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_3():
    img = build_base_canvas()
    draw = ImageDraw.Draw(img, "RGBA")
    draw_header(draw, "/ LO QUE HACE RENDI")

    hero_top = 320
    f1 = F_SANS_BOLD(92)
    lw1 = draw.textlength("Rendi lo mide.", font=f1)
    draw.text((W / 2 - lw1 / 2, hero_top), "Rendi lo mide.", font=f1, fill=INK_0)
    f2 = F_SANS_BOLD(60)
    lw2 = draw.textlength("Con tus operaciones.", font=f2)
    draw.text((W / 2 - lw2 / 2, hero_top + 110), "Con tus operaciones.", font=f2, fill=VIOLET)

    # ─── Bullets ────────────────────────────────────────────────────────────
    list_y = hero_top + 300
    bullets = [
        "Mide cuánto aguantás ganadoras vs perdedoras",
        "Te muestra el ratio y las operaciones exactas",
        "13 detectores de comportamiento más",
    ]
    bullet_font = F_SANS_REG(30)
    for b in bullets:
        ix = W / 2 - 320
        iy = list_y + 10
        s = 20
        draw.line([(ix + s * 0.1, iy + s * 0.5), (ix + s * 0.42, iy + s * 0.82)], fill=VIOLET, width=4)
        draw.line([(ix + s * 0.42, iy + s * 0.82), (ix + s * 0.92, iy + s * 0.18)], fill=VIOLET, width=4)
        draw.text((ix + 42, list_y), b, font=bullet_font, fill=INK_0)
        list_y += 58

    # ─── CTA pill ───────────────────────────────────────────────────────────
    cta_y = list_y + 70
    cta_text = "Probalo en rendi.finance"
    cta_font = F_SANS_BOLD(30)
    cta_w = draw.textlength(cta_text, font=cta_font)
    pad_x, pad_y = 36, 20
    btn_w = cta_w + pad_x * 2
    btn_h = cta_font.size + pad_y * 2
    btn_x = (W - btn_w) / 2
    draw.rounded_rectangle([btn_x, cta_y, btn_x + btn_w, cta_y + btn_h],
                           radius=btn_h // 2, fill=VIOLET)
    draw.text((btn_x + pad_x, cta_y + pad_y - 4), cta_text, font=cta_font, fill=(15, 12, 30))

    draw_footer(draw, current=2)
    out = os.path.join(OUT_DIR, "rendi_post_disposition_3.png")
    img.save(out, "PNG", optimize=True)
    print(f"✓ disposition 3: {out} ({os.path.getsize(out)/1024:.1f}KB)")


if __name__ == "__main__":
    generate_slide_1()
    generate_slide_2()
    generate_slide_3()
    print("\nDone.")
