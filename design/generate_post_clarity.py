"""
Post — "¿Estás ganando o perdiendo?" (enfoque 1 + 2: pregunta honesta + claridad).
Carrusel de 3 slides en 1080×1350 (4:5 feed IG), versión CLARA y cálida
(no la estética Nocturnal oscura): fondo Frost, tarjetas blancas con sombra
suave, acentos serif, casi sin mono.

Slides:
  - rendi_post_clarity_1.png — HOOK: "¿Estás ganando o perdiendo?" + chips dispersos
  - rendi_post_clarity_2.png — LA IDEA: tarjeta de cartera limpia, todo en una pantalla
  - rendi_post_clarity_3.png — INSIGHT: ganancia real en dólares (sin CTA, informativo)

Voz: cálida pero sobria. Voseo, sentence case, cero emoji. Verde/rojo solo en
datos con polaridad (ganando/perdiendo, +%). Violeta solo en la acción/CTA.
Flex deliberado del manual: fondo claro + arranca por la emoción (no el dato),
acento serif para calidez.
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

# ─── Colores (versión clara) ─────────────────────────────────────────────────
FROST      = (245, 243, 251)     # fondo claro de marca
FROST_WARM = (250, 248, 252)     # tinte superior, apenas más cálido
INK_STRONG = (17, 19, 26)        # titulares
INK_BODY   = (52, 56, 68)        # cuerpo
INK_MUTE   = (120, 124, 140)     # secundario / labels
INK_FAINT  = (182, 184, 198)     # hints / dots inactivos
WHITE      = (255, 255, 255)
CARD_BORDER = (228, 224, 240)
TRACK      = (232, 229, 244)     # pista de barras
VIOLET     = (139, 125, 255)     # marca / CTA (relleno)
VIOLET_INK = (96, 80, 222)       # violeta legible para texto/acentos sobre claro
VIOLET_SOFT = (176, 165, 250)    # relleno de barras
GREEN      = (20, 168, 92)       # ganancia (legible sobre claro)
RED        = (224, 64, 78)       # pérdida (legible sobre claro)
SKY        = (70, 140, 235)      # referencia / neutro


# ─── Fonts ─────────────────────────────────────────────────────────────────
def mix(fg, bg, a):
    """Premezcla fg sobre bg con factor a (0..1) → RGB sólido.
    Necesario porque el canvas es RGBA: los fills con alpha no compositan,
    se escriben directo y .convert('RGB') los deja opacos."""
    return tuple(int(bg[i] + (fg[i] - bg[i]) * a) for i in range(3))


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS_DIR, name), size)

# Tipografía Rendi: Geist (sans, 95%) + mono (labels MAYÚSCULA, columnas de
# números, URLs/timestamps). Sin serif, sin itálica (regla del manual).
# Geist no está en canvas-fonts → InstrumentSans como sustituto (igual que el
# resto de los generadores); GeistMono para los datos técnicos.
F_SANS_BOLD = lambda s: font("InstrumentSans-Bold.ttf", s)
F_SANS_REG  = lambda s: font("InstrumentSans-Regular.ttf", s)
F_MONO_REG  = lambda s: font("GeistMono-Regular.ttf", s)
F_MONO_BOLD = lambda s: font("GeistMono-Bold.ttf", s)


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

def text_w(draw, text, font_obj):
    return draw.textlength(text, font=font_obj)

def draw_centered(draw, text, y, font_obj, fill):
    w = draw.textlength(text, font=font_obj)
    draw.text((W / 2 - w / 2, y), text, font=font_obj, fill=fill)
    return w

def draw_centered_segments(draw, segments, y, font_obj):
    """Línea centrada compuesta por (texto, color)."""
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


# ─── Canvas base claro ───────────────────────────────────────────────────────
def build_light_canvas():
    img = Image.new("RGBA", (W, H), (*FROST, 255))
    d = ImageDraw.Draw(img)
    # Tinte vertical sutil: un poco más cálido arriba, frost abajo.
    for y in range(H):
        t = max(0.0, 1 - y / (H * 0.7))
        r = int(FROST[0] + (FROST_WARM[0] - FROST[0]) * t)
        g = int(FROST[1] + (FROST_WARM[1] - FROST[1]) * t)
        b = int(FROST[2] + (FROST_WARM[2] - FROST[2]) * t)
        d.line([(0, y), (W, y)], fill=(r, g, b, 255))
    # Glow violeta MUY tenue arriba-centro (da profundidad sin oscurecer).
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = W // 2, 180
    for r in range(520, 0, -12):
        alpha = int((1 - r / 520) * 10)
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*VIOLET, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    img = Image.alpha_composite(img, glow)
    return img


def soft_card(img, box, radius=26, fill=WHITE, border=CARD_BORDER,
              shadow_alpha=42, shadow_blur=34, shadow_dy=16):
    """Dibuja una tarjeta blanca con sombra suave sobre img (RGBA). Devuelve draw."""
    x0, y0, x1, y1 = box
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle([x0, y0 + shadow_dy, x1, y1 + shadow_dy],
                         radius=radius, fill=(74, 62, 128, shadow_alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
    img.alpha_composite(shadow)
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=border, width=1)
    return d


def draw_header(img, eyebrow):
    d = ImageDraw.Draw(img, "RGBA")
    logo_font = F_SANS_BOLD(46)
    logo_w = d.textlength("rendi", font=logo_font)
    d.text((W / 2 - logo_w / 2, 78), "rendi", font=logo_font, fill=INK_STRONG)
    d.line([(W / 2 - 15, 144), (W / 2 + 15, 144)], fill=VIOLET, width=3)
    ef = F_MONO_REG(19)
    ew = spaced_width(d, eyebrow.upper(), ef, spacing=3)
    draw_spaced_text(d, eyebrow.upper(), W / 2 - ew / 2, 168, ef, VIOLET_INK, spacing=3)
    return d


def draw_footer(img, current, total=3):
    d = ImageDraw.Draw(img, "RGBA")
    dot, gap = 9, 15
    total_w = dot * total + gap * (total - 1)
    sx = (W - total_w) / 2
    y = H - 118
    for i in range(total):
        cx = sx + i * (dot + gap)
        d.ellipse([cx, y, cx + dot, y + dot], fill=VIOLET if i == current else INK_FAINT)
    bf = F_MONO_REG(22)
    bw = d.textlength("rendi.finance", font=bf)
    d.text((W / 2 - bw / 2, H - 78), "rendi.finance", font=bf, fill=INK_MUTE)


def check_icon(draw, x, y, s, color, w=5):
    draw.line([(x + s * 0.10, y + s * 0.52), (x + s * 0.40, y + s * 0.82)], fill=color, width=w)
    draw.line([(x + s * 0.40, y + s * 0.82), (x + s * 0.92, y + s * 0.16)], fill=color, width=w)


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 1 — HOOK
# ─────────────────────────────────────────────────────────────────────────────
def make_chip(label, amount, dot_color, draw_ref):
    """Tarjetita 'dispersa' (broker/instrumento suelto). Devuelve imagen RGBA."""
    cw, ch, pad = 264, 96, 26
    chip = Image.new("RGBA", (cw + pad * 2, ch + pad * 2), (0, 0, 0, 0))
    # sombra propia
    sh = Image.new("RGBA", chip.size, (0, 0, 0, 0))
    shd = ImageDraw.Draw(sh)
    shd.rounded_rectangle([pad, pad + 10, pad + cw, pad + ch + 10], radius=22,
                          fill=(74, 62, 128, 40))
    sh = sh.filter(ImageFilter.GaussianBlur(16))
    chip.alpha_composite(sh)
    d = ImageDraw.Draw(chip, "RGBA")
    d.rounded_rectangle([pad, pad, pad + cw, pad + ch], radius=22,
                        fill=(*WHITE, 255), outline=(*CARD_BORDER, 255), width=1)
    d.ellipse([pad + 24, pad + 28, pad + 24 + 14, pad + 28 + 14], fill=dot_color)
    d.text((pad + 50, pad + 22), label, font=F_SANS_BOLD(27), fill=INK_STRONG)
    d.text((pad + 50, pad + 58), amount, font=F_MONO_REG(20), fill=INK_MUTE)
    return chip


def generate_slide_1():
    img = build_light_canvas()
    draw = draw_header(img, "Una pregunta incómoda")

    # Hero — pregunta, con ganando(verde)/perdiendo(rojo) como único color de dato
    hero = F_SANS_BOLD(82)
    draw_centered_segments(draw, [("¿Estás ", INK_STRONG), ("ganando", GREEN)], 300, hero)
    draw_centered_segments(draw, [("o ", INK_STRONG), ("perdiendo", RED), ("?", INK_STRONG)], 392, hero)

    # Sub relatable (sans)
    sub = F_SANS_REG(31)
    sub_lines = [
        "Unos pesos en un plazo fijo. Unos dólares",
        "guardados. Unas acciones que casi no mirás.",
    ]
    sy = 530
    for ln in sub_lines:
        draw_centered(draw, ln, sy, sub, INK_BODY)
        sy += 44

    # Remate (Geist, sin serif/itálica; énfasis por peso, no por color)
    draw_centered(draw, "La verdad, para la mayoría: ni idea.", 650, F_SANS_BOLD(34), INK_STRONG)

    # Chips dispersos (plata en varios lados)
    chips = [
        (make_chip("Plazo fijo", "$ 1.500.000", GREEN, draw), -7, 70, markpos := 792),
        (make_chip("Dólares", "US$ 3.250", SKY, draw), 5, 470, 832),
        (make_chip("Acciones", "US$ 3.600", VIOLET, draw), -4, 250, 980),
    ]
    # (x base, y) elegidos para que se sientan sueltos/superpuestos
    placements = [(70, 792), (455, 838), (300, 980)]
    for (chip, angle, _, _), (px, py) in zip(chips, placements):
        rot = chip.rotate(angle, expand=True, resample=Image.BICUBIC)
        img.alpha_composite(rot, (px, py))

    draw_footer(img, current=0)
    out = os.path.join(OUT_DIR, "rendi_post_clarity_1.png")
    img.convert("RGB").save(out, "PNG", optimize=True)
    print(f"✓ clarity 1: {out} ({os.path.getsize(out)/1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 2 — LA IDEA (tarjeta de cartera limpia)
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_2():
    img = build_light_canvas()
    draw = draw_header(img, "La idea")

    # Titular
    h = F_SANS_BOLD(64)
    draw_centered(draw, "Toda tu plata", 272, h, INK_STRONG)
    draw_centered(draw, "en una sola pantalla.", 352, h, INK_STRONG)

    # ─── Tarjeta de cartera ───────────────────────────────────────────────────
    card_x, card_y, card_w = 110, 470, 860
    card_h = 600
    pad = 48
    inner_x = card_x + pad
    inner_w = card_w - pad * 2
    draw = soft_card(img, [card_x, card_y, card_x + card_w, card_y + card_h], radius=30)

    # Label + total
    draw_spaced_text(draw, "TU CARTERA", inner_x, card_y + pad, F_MONO_REG(20), INK_MUTE, spacing=2)
    total_f = F_SANS_BOLD(78)
    draw.text((inner_x, card_y + pad + 34), "US$ 12.480", font=total_f, fill=INK_STRONG)
    # Chip de variación (verde, dato con polaridad)
    chg_f = F_SANS_BOLD(26)
    chg_txt = "+3,2% este mes"
    chg_w = draw.textlength(chg_txt, font=chg_f)
    chip_pad = 18
    chip_x = inner_x
    chip_y = card_y + pad + 134
    draw.rounded_rectangle([chip_x, chip_y, chip_x + chg_w + chip_pad * 2, chip_y + 46],
                           radius=23, fill=mix(GREEN, WHITE, 0.16))
    draw.text((chip_x + chip_pad, chip_y + 8), chg_txt, font=chg_f, fill=GREEN)

    # Divider
    dv_y = chip_y + 86
    draw.line([(inner_x, dv_y), (inner_x + inner_w, dv_y)], fill=(*CARD_BORDER, 255), width=1)

    # Filas (nombre · barra proporción · monto)
    rows = [
        ("Plazo fijo", "US$ 4.100", 0.33),
        ("Dólares", "US$ 3.250", 0.26),
        ("Acciones y CEDEARs", "US$ 3.600", 0.29),
        ("Cripto", "US$ 1.530", 0.12),
    ]
    nf = F_SANS_REG(29)
    vf = F_MONO_BOLD(26)
    ry = dv_y + 34
    row_h = 80
    bar_max = inner_w
    for name, val, frac in rows:
        draw.text((inner_x, ry), name, font=nf, fill=INK_BODY)
        vw = draw.textlength(val, font=vf)
        draw.text((inner_x + inner_w - vw, ry), val, font=vf, fill=INK_STRONG)
        # barra
        by = ry + 44
        draw.rounded_rectangle([inner_x, by, inner_x + bar_max, by + 9], radius=5, fill=TRACK)
        draw.rounded_rectangle([inner_x, by, inner_x + int(bar_max * frac), by + 9],
                               radius=5, fill=VIOLET_SOFT)
        ry += row_h

    # Sub bajo la tarjeta
    s = F_SANS_REG(28)
    draw_centered(draw, "Cargás lo que tenés y ves tu ganancia real en", 1108, s, INK_BODY)
    draw_centered(draw, "dólares. Sin planillas, sin hacer cuentas a mano.", 1146, s, INK_BODY)

    draw_footer(img, current=1)
    out = os.path.join(OUT_DIR, "rendi_post_clarity_2.png")
    img.convert("RGB").save(out, "PNG", optimize=True)
    print(f"✓ clarity 2: {out} ({os.path.getsize(out)/1024:.1f}KB)")


# ─────────────────────────────────────────────────────────────────────────────
# SLIDE 3 — CTA
# ─────────────────────────────────────────────────────────────────────────────
def generate_slide_3():
    img = build_light_canvas()
    draw = draw_header(img, "Lo que importa")

    # Titular — el insight (no CTA)
    h = F_SANS_BOLD(66)
    draw_centered(draw, "Subir en pesos", 296, h, INK_STRONG)
    draw_centered(draw, "no siempre es ganar.", 380, h, INK_STRONG)

    # Bajada (Geist regular, tinta)
    draw_centered(draw, "Lo que cuenta es cuánto vale tu plata en dólares.",
                  510, F_SANS_REG(31), INK_BODY)

    # Explicación breve, con aire
    para = ("Entre la inflación y el dólar, tu cartera puede crecer en pesos "
            "y achicarse en serio. Rendi la mide en dólar blue para mostrarte "
            "tu ganancia real.")
    pf = F_SANS_REG(29)
    py = 596
    for ln in wrap_text(draw, para, pf, 800):
        draw_centered(draw, ln, py, pf, INK_BODY)
        py += 42

    # Comparación tranquila (el concepto, en un ejemplo)
    col = 190
    lx, rx = W / 2 - col, W / 2 + col
    label = "UN PLAZO FIJO, EN UN AÑO"
    lf = F_MONO_REG(19)
    lw = spaced_width(draw, label, lf, spacing=2)
    cy = 812
    draw_spaced_text(draw, label, W / 2 - lw / 2, cy, lf, INK_MUTE, spacing=2)
    draw.line([(lx, cy + 46), (rx, cy + 46)], fill=CARD_BORDER, width=1)

    rf = F_SANS_REG(31)
    vf = F_MONO_BOLD(30)
    # En pesos — nominal, atenuado (el espejismo)
    ry = cy + 74
    draw.text((lx, ry), "En pesos", font=rf, fill=INK_MUTE)
    t1 = "+48%"
    draw.text((rx - draw.textlength(t1, font=vf), ry - 2), t1, font=vf, fill=INK_MUTE)
    # En dólares — lo real (verde)
    ry += 60
    draw.text((lx, ry), "En dólares", font=rf, fill=INK_STRONG)
    t2 = "+3%"
    draw.text((rx - draw.textlength(t2, font=vf), ry - 2), t2, font=vf, fill=GREEN)

    draw_centered(draw, "Ejemplo ilustrativo", ry + 70, F_SANS_REG(20), INK_FAINT)

    draw_footer(img, current=2)
    out = os.path.join(OUT_DIR, "rendi_post_clarity_3.png")
    img.convert("RGB").save(out, "PNG", optimize=True)
    print(f"✓ clarity 3: {out} ({os.path.getsize(out)/1024:.1f}KB)")


if __name__ == "__main__":
    generate_slide_1()
    generate_slide_2()
    generate_slide_3()
    print("\nDone.")
