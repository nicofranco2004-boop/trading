"""
Genera 3 historias destacadas para Rendi — una por plan (Free, Plus, Pro).
Cada una lista las features reales del plan (copiadas de Planes.jsx).

Output:
  - rendi_features_free.png
  - rendi_features_plus.png
  - rendi_features_pro.png

Todas en 1080x1920 PNG, dark mode, aesthetic "Nocturnal Precision"
(mismo design philosophy que la portada).
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os
import textwrap

# ─── Paths ─────────────────────────────────────────────────────────────────
FONTS_DIR = (
    "/Users/nicolaspussetto/Library/Application Support/Claude/"
    "local-agent-mode-sessions/skills-plugin/"
    "bcfbadf3-5949-46c4-95ea-f77e7e18d7ad/"
    "6a7d8d68-f39a-4be8-86c7-653fd22de85c/skills/canvas-design/canvas-fonts/"
)
OUT_DIR = "/Users/nicolaspussetto/Documents/trading/design"

# ─── Canvas ────────────────────────────────────────────────────────────────
W, H = 1080, 1920

# ─── Colors ────────────────────────────────────────────────────────────────
BG = (10, 11, 14)
BG_GLOW = (16, 14, 26)
CARD_BG = (15, 17, 23)
CARD_BG_PLUS = (22, 18, 38)
INK_0 = (244, 244, 248)
INK_1 = (200, 200, 210)
INK_2 = (130, 132, 142)
INK_3 = (90, 96, 110)
INK_4 = (50, 54, 64)
INK_5 = (40, 44, 54)
VIOLET = (139, 125, 255)
VIOLET_DIM = (110, 95, 220)

# ─── Fonts ─────────────────────────────────────────────────────────────────
def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS_DIR, name), size)

F_SANS_BOLD = lambda s: font("InstrumentSans-Bold.ttf", s)
F_SANS_REG  = lambda s: font("InstrumentSans-Regular.ttf", s)
F_MONO_BOLD = lambda s: font("GeistMono-Bold.ttf", s)
F_MONO_REG  = lambda s: font("GeistMono-Regular.ttf", s)


# ─── Helpers ───────────────────────────────────────────────────────────────
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


def wrap_text(draw, text, font_obj, max_width):
    """Wrap a string to fit in max_width pixels. Returns list of lines."""
    words = text.split()
    lines = []
    current = []
    for word in words:
        test = ' '.join(current + [word])
        if draw.textlength(test, font=font_obj) <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(' '.join(current))
            current = [word]
    if current:
        lines.append(' '.join(current))
    return lines


def draw_check_icon(draw, x, y, size, color):
    """Dibuja un check minimalista (✓) en posición x,y con tamaño dado."""
    # ✓ shape: línea desde (x, y+s*0.5) → (x+s*0.4, y+s*0.85) → (x+s, y+s*0.1)
    line_w = max(2, size // 8)
    draw.line(
        [
            (x + size * 0.1, y + size * 0.5),
            (x + size * 0.42, y + size * 0.82),
        ],
        fill=color,
        width=line_w,
    )
    draw.line(
        [
            (x + size * 0.42, y + size * 0.82),
            (x + size * 0.92, y + size * 0.18),
        ],
        fill=color,
        width=line_w,
    )


def draw_clock_icon(draw, x, y, size, color):
    """Dibuja un clock minimalista (○ + manecillas) para roadmap items."""
    # Círculo
    draw.ellipse(
        [x, y, x + size, y + size],
        outline=color,
        width=max(2, size // 10),
    )
    # Manecilla vertical (apuntando arriba)
    cx, cy = x + size / 2, y + size / 2
    draw.line(
        [(cx, cy), (cx, y + size * 0.2)],
        fill=color,
        width=max(2, size // 10),
    )
    # Manecilla horizontal (apuntando derecha)
    draw.line(
        [(cx, cy), (x + size * 0.75, cy)],
        fill=color,
        width=max(2, size // 10),
    )


def draw_infinity_symbol(draw, cx, cy, size, color, stroke=5):
    """Dibuja un símbolo ∞ con 2 elipses entrelazadas — más prolijo que
    depender del glifo Unicode (Geist Mono no lo tiene)."""
    # Cada lóbulo: una elipse hueca. Width-stroke variable según size.
    r_x = size * 0.4  # radio horizontal de cada lóbulo
    r_y = size * 0.32  # radio vertical
    offset = size * 0.32  # separación horizontal entre lóbulos
    # Lóbulo izquierdo
    draw.ellipse(
        [cx - offset - r_x, cy - r_y, cx - offset + r_x, cy + r_y],
        outline=color,
        width=stroke,
    )
    # Lóbulo derecho
    draw.ellipse(
        [cx + offset - r_x, cy - r_y, cx + offset + r_x, cy + r_y],
        outline=color,
        width=stroke,
    )


# ─── Plan data (copiado de Planes.jsx) ─────────────────────────────────────
PLANS = {
    'free': {
        'eyebrow': '/ FREE',
        'title': 'Free',
        'price': '$0',
        'period': '',
        'subtitle': 'Gratis para siempre · para empezar a trackear tu cartera.',
        'features': [
            ('Dashboard completo con 4 KPIs + curva de evolución', None),
            ('Posiciones, Operaciones, Wrapped anual y Objetivos', None),
            ('Insights con TWR y benchmarks (S&P, inflación AR, dólar)', None),
            ('3 observaciones diagnósticas + 1 detector de comportamiento', None),
            ('Coach IA con 12 preguntas guiadas', 'taster del asistente'),
            ('Reportes: vista previa del último mes', None),
        ],
        'quotas': [
            ('Análisis IA / sem', '6'),
            ('Chat Coach IA / sem', '3'),
            ('Brokers', '1'),
        ],
        'accent_color': INK_2,  # Free no usa violet
        'is_popular': False,
    },
    'plus': {
        'eyebrow': '/ PLUS',
        'title': 'Plus',
        'price': 'USD 4',
        'period': '/mes',
        'subtitle': 'Para profundizar — más brokers, insights y chat.',
        'features': [
            ('Todo lo del Free', None),
            ('Diagnóstico de Insights completo con 6 observaciones', None),
            ('4 detectores de comportamiento visibles', 'de 12 disponibles'),
            ('Distribución por activo desbloqueada', None),
            ('Reportes históricos completos · todos los meses', None),
            ('Export CSV consolidado para tu contador', 'compras, ventas, depósitos, dividendos'),
            ('3× más Chat Coach IA que Free', '9 consultas/semana'),
        ],
        'quotas': [
            ('Análisis IA / sem', '6'),
            ('Chat Coach IA / sem', '9'),
            ('Brokers', '3'),
        ],
        'accent_color': VIOLET,
        'is_popular': True,
    },
    'pro': {
        'eyebrow': '/ PRO',
        'title': 'Pro',
        'price': 'USD 9',
        'period': '/mes',
        'subtitle': 'Para profesionales — IA libre, memoria y brokers ilimitados.',
        'features': [
            ('Todo lo del Plus', None),
            ('60 análisis IA / semana', '10× más que Free y Plus'),
            ('Chat libre con el Coach IA', '40 consultas/sem · texto libre'),
            ('Respuestas con causalidad y comparaciones', 'modo research-note'),
            ('Follow-ups: profundizá cualquier análisis', None),
            ('Memoria persistente del Coach', 'los hechos que le aclarás se respetan'),
            ('Brokers ilimitados', None),
            ('12 detectores de comportamiento completos', None),
            ('Diagnóstico de Insights ilimitado', None),
        ],
        'quotas': [
            ('Análisis IA / sem', '60'),
            ('Chat Coach IA / sem', '40'),
            ('Brokers', '∞'),
        ],
        'accent_color': VIOLET,
        'is_popular': False,
    },
}


# ─── Generate one mockup per plan ──────────────────────────────────────────
def generate_plan_story(plan_key):
    plan = PLANS[plan_key]
    accent = plan['accent_color']

    # ─── Canvas base ───────────────────────────────────────────────────────
    img = Image.new("RGB", (W, H), BG)
    draw_g = ImageDraw.Draw(img)
    for y in range(H):
        if y < 700:
            t = 1 - (y / 700)
            r = int(BG[0] + (BG_GLOW[0] - BG[0]) * t * 0.5)
            g = int(BG[1] + (BG_GLOW[1] - BG[1]) * t * 0.5)
            b = int(BG[2] + (BG_GLOW[2] - BG[2]) * t * 0.5)
            draw_g.line([(0, y), (W, y)], fill=(r, g, b))
        elif y > H - 500:
            t = (y - (H - 500)) / 500
            r = int(BG[0] + (BG_GLOW[0] - BG[0]) * t * 0.3)
            g = int(BG[1] + (BG_GLOW[1] - BG[1]) * t * 0.3)
            b = int(BG[2] + (BG_GLOW[2] - BG[2]) * t * 0.3)
            draw_g.line([(0, y), (W, y)], fill=(r, g, b))

    # Soft glow (only for plus/pro)
    if plan['is_popular'] or plan_key == 'pro':
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        for r in range(450, 0, -10):
            alpha = int((1 - r / 450) * (22 if plan['is_popular'] else 14))
            gd.ellipse([W // 2 - r, 540 - r, W // 2 + r, 540 + r], fill=(*VIOLET, alpha))
        glow = glow.filter(ImageFilter.GaussianBlur(60))
        img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

    draw = ImageDraw.Draw(img, "RGBA")

    # ─── HEADER ────────────────────────────────────────────────────────────
    HEADER_TOP = 130

    # Logo
    logo = "rendi"
    logo_font = F_SANS_BOLD(56)
    logo_w = draw.textlength(logo, font=logo_font)
    draw.text((W / 2 - logo_w / 2, HEADER_TOP), logo, font=logo_font, fill=INK_0)

    # Micro underline
    ul_w = 36
    ul_y = HEADER_TOP + 84
    draw.line([(W / 2 - ul_w / 2, ul_y), (W / 2 + ul_w / 2, ul_y)], fill=VIOLET, width=2)

    # Eyebrow
    eyebrow_top = HEADER_TOP + 130
    eyebrow_font = F_MONO_REG(24)
    ey_w = spaced_width(draw, plan['eyebrow'], eyebrow_font, spacing=4)
    draw_spaced_text(draw, plan['eyebrow'], W / 2 - ey_w / 2, eyebrow_top, eyebrow_font, VIOLET, spacing=4)

    # ── Plan title + price (centered, large) ──────────────────────────────
    # Title block: "Plus" + price right after, lower baseline
    # Layout: PLAN_NAME (big) — PRICE (medium aligned to bottom)
    title_font = F_SANS_BOLD(108)
    price_font = F_SANS_BOLD(60)
    period_font = F_SANS_REG(36)

    title_text = plan['title']
    price_text = plan['price']
    period_text = plan['period']

    title_w = draw.textlength(title_text, font=title_font)
    price_w = draw.textlength(price_text, font=price_font)
    period_w = draw.textlength(period_text, font=period_font) if period_text else 0

    gap = 36  # gap between title and price
    total_w = title_w + gap + price_w + (8 + period_w if period_text else 0)

    title_y = eyebrow_top + 68
    start_x = (W - total_w) / 2

    # Title
    draw.text((start_x, title_y), title_text, font=title_font, fill=INK_0)
    # Price (baseline-aligned to title)
    price_x = start_x + title_w + gap
    price_y = title_y + 38  # offset to align baseline
    draw.text((price_x, price_y), price_text, font=price_font, fill=accent)
    # Period
    if period_text:
        period_y = price_y + 22
        draw.text((price_x + price_w + 8, period_y), period_text, font=period_font, fill=INK_2)

    # Subtitle
    sub_font = F_SANS_REG(28)
    sub_text = plan['subtitle']
    # Center-aligned, may wrap if too long
    sub_lines = wrap_text(draw, sub_text, sub_font, max_width=900)
    sub_y = title_y + 170
    for line in sub_lines:
        line_w = draw.textlength(line, font=sub_font)
        draw.text((W / 2 - line_w / 2, sub_y), line, font=sub_font, fill=INK_2)
        sub_y += 40

    # ─── QUOTAS STRIP (mini KPI bar) ────────────────────────────────────────
    # 3 mini cells with the plan's quotas. Compact, mono, fintech vibe.
    quotas_y = sub_y + 50
    quotas = plan['quotas']
    cell_w = 280
    cell_gap = 16
    total_qw = cell_w * len(quotas) + cell_gap * (len(quotas) - 1)
    qx = (W - total_qw) / 2
    for i, (q_label, q_value) in enumerate(quotas):
        cx = qx + i * (cell_w + cell_gap)
        # Subtle background
        draw.rounded_rectangle(
            [cx, quotas_y, cx + cell_w, quotas_y + 100],
            radius=12,
            fill=(*CARD_BG, 180) if not plan['is_popular'] else (*CARD_BG_PLUS, 200),
            outline=(*INK_4, 120),
            width=1,
        )
        # Value — si es "∞" lo dibujamos a mano (Geist Mono no tiene el glifo).
        # Sino usamos la font sans bold.
        val_color = accent if (plan['is_popular'] or plan_key == 'pro') else INK_0
        if q_value == '∞':
            # Centro vertical del símbolo en la mitad superior del cell
            sym_cx = cx + cell_w / 2
            sym_cy = quotas_y + 32
            draw_infinity_symbol(draw, sym_cx, sym_cy, size=46, color=val_color, stroke=5)
        else:
            val_font = F_SANS_BOLD(40)
            val_w = draw.textlength(q_value, font=val_font)
            draw.text(
                (cx + cell_w / 2 - val_w / 2, quotas_y + 10),
                q_value,
                font=val_font,
                fill=val_color,
            )
        # Label (small mono)
        lbl_font = F_MONO_REG(15)
        lbl_w = spaced_width(draw, q_label.upper(), lbl_font, spacing=2)
        draw_spaced_text(draw, q_label.upper(), cx + cell_w / 2 - lbl_w / 2, quotas_y + 64, lbl_font, INK_3, spacing=2)

    # ─── FEATURES LIST ─────────────────────────────────────────────────────
    features_y = quotas_y + 160

    # Section header
    sh_font = F_MONO_REG(20)
    sh_text = "// QUÉ INCLUYE"
    sh_w = spaced_width(draw, sh_text, sh_font, spacing=3)
    draw_spaced_text(draw, sh_text, 80, features_y, sh_font, INK_3, spacing=3)

    # Section divider (hair-line)
    draw.line([(80 + sh_w + 30, features_y + 12), (W - 80, features_y + 12)], fill=INK_4, width=1)

    list_y = features_y + 50
    max_text_width = W - 80 - 60 - 80  # margins + icon offset
    feat_font_main = F_SANS_REG(28)
    feat_font_sub = F_MONO_REG(18)
    line_height_main = 38
    line_height_sub = 26
    gap_between_features = 26

    # If too many features, shrink slightly (e.g. Pro tiene 9)
    if len(plan['features']) >= 9:
        feat_font_main = F_SANS_REG(26)
        line_height_main = 34
        gap_between_features = 20

    for label, sub_label in plan['features']:
        icon_x = 80
        icon_y = list_y
        icon_size = 24
        # Icon background circle (subtle)
        icon_bg_color = (*accent, 30) if plan['is_popular'] or plan_key == 'pro' else (*INK_4, 200)
        draw.ellipse(
            [icon_x - 4, icon_y - 4, icon_x + icon_size + 4, icon_y + icon_size + 4],
            fill=icon_bg_color,
        )
        # Check icon
        check_color = accent if plan['is_popular'] or plan_key == 'pro' else INK_1
        draw_check_icon(draw, icon_x, icon_y, icon_size, check_color)

        # Text — main label (with wrap)
        text_x = icon_x + 50
        lines_main = wrap_text(draw, label, feat_font_main, max_text_width)
        ty = list_y
        for ln in lines_main:
            draw.text((text_x, ty), ln, font=feat_font_main, fill=INK_0)
            ty += line_height_main

        # Sub label
        if sub_label:
            lines_sub = wrap_text(draw, sub_label, feat_font_sub, max_text_width)
            for ln in lines_sub:
                draw.text((text_x, ty), ln, font=feat_font_sub, fill=INK_3)
                ty += line_height_sub

        list_y = ty + gap_between_features

    # ─── FOOTER ────────────────────────────────────────────────────────────
    # Hair-line + brand + tagline. Posicionado al fondo.
    footer_y = H - 200

    hairline_w = 80
    draw.line(
        [(W / 2 - hairline_w / 2, footer_y), (W / 2 + hairline_w / 2, footer_y)],
        fill=INK_4,
        width=1,
    )

    brand_text = "rendi.finance"
    brand_font = F_MONO_REG(28)
    brand_w = draw.textlength(brand_text, font=brand_font)
    draw.text((W / 2 - brand_w / 2, footer_y + 30), brand_text, font=brand_font, fill=INK_1)

    tag_text = "Tu portfolio multi-broker, con Coach IA."
    tag_font = F_SANS_REG(24)
    tag_w = draw.textlength(tag_text, font=tag_font)
    draw.text((W / 2 - tag_w / 2, footer_y + 84), tag_text, font=tag_font, fill=INK_3)

    # ─── Save ──────────────────────────────────────────────────────────────
    out_path = os.path.join(OUT_DIR, f"rendi_features_{plan_key}.png")
    img.save(out_path, "PNG", optimize=True)
    print(f"✓ {plan_key}: {out_path} ({os.path.getsize(out_path) / 1024:.1f}KB)")


# Generar los 3
for plan_key in ('free', 'plus', 'pro'):
    generate_plan_story(plan_key)

print("\nDone.")
