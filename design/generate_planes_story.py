"""
Genera el mockup de historia destacada de Instagram para Rendi — Planes (v2).
Output: 1080x1920 PNG, dark mode, fintech minimal aesthetic.

Refinements en v2 (feedback del user):
- Sin "SWIPE PARA VER MÁS" + chevrons (era distractivo)
- Cada card con índice "01 / 03" en mono uppercase (fintech precision)
- Badge "MÁS POPULAR" integrado dentro del card (no flotando arriba)
- Mejor balance vertical y spacing
- Líneas placeholder más refinadas (anchos variables, alpha sutil)
- Footer más compacto y elegante

Design philosophy: "Nocturnal Precision" (ver rendi_planes_philosophy.md)
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
OUT_PATH = os.path.join(OUT_DIR, "rendi_planes_instagram_story.png")

# ─── Canvas ────────────────────────────────────────────────────────────────
W, H = 1080, 1920

# ─── Color palette (Nocturnal Precision) ───────────────────────────────────
BG = (10, 11, 14)                # deep ink-black
BG_GLOW = (16, 14, 26)           # violet-tinted near horizon
CARD_BG = (15, 17, 23)           # neutral card
CARD_BG_PLUS = (22, 18, 38)      # violet-tinted card bg
INK_0 = (244, 244, 248)
INK_1 = (200, 200, 210)
INK_2 = (130, 132, 142)
INK_3 = (90, 96, 110)
INK_4 = (50, 54, 64)             # divider / hair-line
INK_5 = (40, 44, 54)             # placeholder skeleton
VIOLET = (139, 125, 255)
VIOLET_DIM = (110, 95, 220)

# ─── Fonts ─────────────────────────────────────────────────────────────────
def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS_DIR, name), size)

F_SANS_BOLD = lambda s: font("InstrumentSans-Bold.ttf", s)
F_SANS_REG  = lambda s: font("InstrumentSans-Regular.ttf", s)
F_MONO_BOLD = lambda s: font("GeistMono-Bold.ttf", s)
F_MONO_REG  = lambda s: font("GeistMono-Regular.ttf", s)

# ─── Canvas + atmospheric gradient ─────────────────────────────────────────
img = Image.new("RGB", (W, H), BG)
draw_g = ImageDraw.Draw(img)
for y in range(H):
    # Top: violet horizon fade (first 700px)
    if y < 700:
        t = 1 - (y / 700)
        r = int(BG[0] + (BG_GLOW[0] - BG[0]) * t * 0.5)
        g = int(BG[1] + (BG_GLOW[1] - BG[1]) * t * 0.5)
        b = int(BG[2] + (BG_GLOW[2] - BG[2]) * t * 0.5)
        draw_g.line([(0, y), (W, y)], fill=(r, g, b))
    elif y > H - 500:
        # Bottom: very subtle warm fade
        t = (y - (H - 500)) / 500
        r = int(BG[0] + (BG_GLOW[0] - BG[0]) * t * 0.3)
        g = int(BG[1] + (BG_GLOW[1] - BG[1]) * t * 0.3)
        b = int(BG[2] + (BG_GLOW[2] - BG[2]) * t * 0.3)
        draw_g.line([(0, y), (W, y)], fill=(r, g, b))

# Soft violet glow at Plus card altitude (centered)
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
center_x, center_y = W // 2, 1040
for r in range(450, 0, -10):
    alpha = int((1 - r / 450) * 18)
    gd.ellipse(
        [center_x - r, center_y - r, center_x + r, center_y + r],
        fill=(*VIOLET, alpha),
    )
glow = glow.filter(ImageFilter.GaussianBlur(60))
img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
draw = ImageDraw.Draw(img, "RGBA")


# ─── Helper: text with letter-spacing ──────────────────────────────────────
def draw_spaced_text(text, x, y, font_obj, fill, spacing=4):
    cursor = x
    for ch in text:
        draw.text((cursor, y), ch, font=font_obj, fill=fill)
        cursor += draw.textlength(ch, font=font_obj) + spacing
    return cursor - x

def spaced_width(text, font_obj, spacing=4):
    return sum(draw.textlength(ch, font=font_obj) for ch in text) + spacing * (len(text) - 1)


# ─── HEADER ────────────────────────────────────────────────────────────────
# Sin coordinate markers en el top — el user prefirió un canvas más limpio.
HEADER_TOP = 180

# Logo "rendi"
logo = "rendi"
logo_font = F_SANS_BOLD(64)
logo_w = draw.textlength(logo, font=logo_font)
draw.text((W / 2 - logo_w / 2, HEADER_TOP), logo, font=logo_font, fill=INK_0)

# Mini violet underline accent — sutil firma
ul_w = 40
ul_x = W / 2 - ul_w / 2
ul_y = HEADER_TOP + 90
draw.line([(ul_x, ul_y), (ul_x + ul_w, ul_y)], fill=VIOLET, width=2)

# Eyebrow mono "/ PLANES"
eyebrow_top = HEADER_TOP + 140
eyebrow = "/ PLANES"
eyebrow_font = F_MONO_REG(24)
ey_w = spaced_width(eyebrow, eyebrow_font, spacing=4)
draw_spaced_text(eyebrow, W / 2 - ey_w / 2, eyebrow_top, eyebrow_font, VIOLET, spacing=4)

# Título "Elegí tu plan."
title = "Elegí tu plan."
title_font = F_SANS_BOLD(100)
title_w = draw.textlength(title, font=title_font)
title_y = eyebrow_top + 64
draw.text((W / 2 - title_w / 2, title_y), title, font=title_font, fill=INK_0)

# Subtítulo
sub = "3 opciones según cómo querés usar Rendi."
sub_font = F_SANS_REG(32)
sub_w = draw.textlength(sub, font=sub_font)
sub_y = title_y + 140
draw.text((W / 2 - sub_w / 2, sub_y), sub, font=sub_font, fill=INK_2)


# ─── CARDS ─────────────────────────────────────────────────────────────────
CARDS_TOP = 740
CARD_W = 940
CARD_H = 280
CARD_GAP = 36
CARD_X = (W - CARD_W) // 2


def draw_card(y, index, label, price, period_label, tagline, is_popular=False):
    """Draws one plan card. `index` is the position number "01" - "03"."""
    x0, y0 = CARD_X, y
    x1, y1 = CARD_X + CARD_W, y + CARD_H
    radius = 18

    # Background
    bg = CARD_BG_PLUS if is_popular else CARD_BG
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=bg)

    # Border — popular gets a brighter violet border, others a hair-fine gray
    if is_popular:
        # Doble línea sutil para profundidad — primero violet más sutil exterior
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, outline=(*VIOLET, 110), width=2)
    else:
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, outline=(*INK_4, 200), width=1)

    # ── Top row: index "01/03" + (only for Plus) "MÁS POPULAR" inline label ─
    top_y = y0 + 32
    # Index mono — left
    idx_font = F_MONO_REG(20)
    idx_text = f"{index} / 03"
    idx_color = VIOLET if is_popular else INK_3
    draw_spaced_text(idx_text, x0 + 50, top_y, idx_font, idx_color, spacing=3)

    # "MÁS POPULAR" inline (top right) — sutil, NO floating badge
    if is_popular:
        pop_text = "MÁS POPULAR"
        pop_font = F_MONO_BOLD(20)
        pop_w = spaced_width(pop_text, pop_font, spacing=3)
        # Dot violet + text
        dot_x = x1 - 50 - pop_w - 18
        draw.ellipse(
            [dot_x, top_y + 8, dot_x + 8, top_y + 16],
            fill=VIOLET,
        )
        draw_spaced_text(
            pop_text,
            x1 - 50 - pop_w,
            top_y,
            pop_font,
            VIOLET,
            spacing=3,
        )

    # ── Plan label + price (left center) ───────────────────────────────────
    label_font = F_MONO_BOLD(30)
    label_color = VIOLET if is_popular else INK_2
    label_y = y0 + 78
    draw_spaced_text(label, x0 + 50, label_y, label_font, label_color, spacing=5)

    # Price
    price_font = F_SANS_BOLD(82)
    px = x0 + 50
    py = y0 + 122
    draw.text((px, py), price, font=price_font, fill=INK_0)
    if period_label:
        pw = draw.textlength(price, font=price_font)
        period_font = F_SANS_REG(32)
        draw.text(
            (px + pw + 14, py + 38),
            period_label,
            font=period_font,
            fill=INK_2,
        )

    # Tagline (sub label)
    if tagline:
        tl_font = F_MONO_REG(20)
        draw_spaced_text(tagline, x0 + 50, y0 + 220, tl_font, INK_3, spacing=2)

    # ── Placeholder bullet lines (right column) ────────────────────────────
    bullet_x = x0 + CARD_W - 380
    bullet_y = y0 + 88
    line_color = (*VIOLET, 80) if is_popular else (*INK_5, 220)
    widths = [300, 270, 240, 200]
    for i in range(4):
        w_line = widths[i]
        ly = bullet_y + i * 42
        # Dot marker
        dot_color = VIOLET if is_popular else INK_3
        draw.ellipse(
            [bullet_x - 14, ly + 7, bullet_x - 14 + 6, ly + 13],
            fill=dot_color,
        )
        # Line
        draw.rounded_rectangle(
            [bullet_x, ly + 4, bullet_x + w_line, ly + 16],
            radius=5,
            fill=line_color,
        )


# Render 3 cards
draw_card(CARDS_TOP, "01", "FREE", "$0", "", "para empezar", is_popular=False)
draw_card(CARDS_TOP + (CARD_H + CARD_GAP), "02", "PLUS", "USD 4", "/mes", "para profundizar", is_popular=True)
draw_card(CARDS_TOP + (CARD_H + CARD_GAP) * 2, "03", "PRO", "USD 9", "/mes", "para profesionales", is_popular=False)


# ─── FOOTER ────────────────────────────────────────────────────────────────
# Hair-fine divider + brand + tagline. Sin chevrons ni "swipe" — pediste limpieza.
footer_y = CARDS_TOP + (CARD_H + CARD_GAP) * 3 + 90

# Centered hairline
hairline_w = 80
hx = W / 2 - hairline_w / 2
draw.line([(hx, footer_y), (hx + hairline_w, footer_y)], fill=INK_4, width=1)

# Brand
brand_text = "rendi.finance"
brand_font = F_MONO_REG(32)
brand_w = draw.textlength(brand_text, font=brand_font)
draw.text(
    (W / 2 - brand_w / 2, footer_y + 40),
    brand_text,
    font=brand_font,
    fill=INK_1,
)

# Tagline
tag_text = "Tu portfolio multi-broker, con Coach IA."
tag_font = F_SANS_REG(28)
tag_w = draw.textlength(tag_text, font=tag_font)
draw.text(
    (W / 2 - tag_w / 2, footer_y + 100),
    tag_text,
    font=tag_font,
    fill=INK_3,
)


# ─── Save ──────────────────────────────────────────────────────────────────
os.makedirs(OUT_DIR, exist_ok=True)
img.save(OUT_PATH, "PNG", optimize=True)
print(f"✓ Saved: {OUT_PATH}")
print(f"  Size: {os.path.getsize(OUT_PATH) / 1024:.1f}KB")
