"""
brand.py — sistema visual compartido de Rendi para contenido social (PIL/Pillow).

Consolida la estética "Nocturnal Precision" en DOS temas (oscuro/claro) y DOS
formatos (feed 4:5 = 1080×1350, story 9:16 = 1080×1920), para que toda la tanda
de posts salga consistente. Fuentes de marca reales (Geist + JetBrains Mono).
Voz visual: dato-first, voseo, sentence case, CERO emoji. Violeta SOLO en
acción/CTA; verde/rojo SOLO en datos con polaridad; cielo para benchmark.

Lo usan los generadores de social_batch.py. Cada función recibe un Theme (DARK
o LIGHT) para no duplicar lógica por tono.
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

FONTS_DIR = "/Users/nicolaspussetto/Documents/trading/design/fonts"
LOGO_DIR = "/Users/nicolaspussetto/Documents/rendi 2/brand-kit/logos"
OUT_DIR = "/Users/nicolaspussetto/Documents/trading/design/outputs/social"

# ─── Formatos ────────────────────────────────────────────────────────────────
FEED = (1080, 1350)    # 4:5 — post de feed (Instagram orgánico)
STORY = (1080, 1920)   # 9:16 — historia
SQUARE = (1080, 1080)  # 1:1 — por si hace falta

# ─── Fuentes (marca real) ────────────────────────────────────────────────────
def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS_DIR, name), size)

F_SEMI = lambda s: font("Geist-SemiBold.ttf", s)
F_MED = lambda s: font("Geist-Medium.ttf", s)
F_REG = lambda s: font("Geist-Regular.ttf", s)
MONO_M = lambda s: font("JetBrainsMono-Medium.ttf", s)
MONO_R = lambda s: font("JetBrainsMono-Regular.ttf", s)


# ─── Temas ───────────────────────────────────────────────────────────────────
class Theme:
    def __init__(self, name, **kw):
        self.name = name
        self.__dict__.update(kw)


# Oscuro — Ink #07090C con glow violeta. Logo violet.
DARK = Theme(
    "dark",
    bg=(7, 9, 12), bg_glow=(16, 14, 26), glow_y=0.30, glow_a=15, glow_r=420,
    card=(14, 16, 22), card2=(19, 17, 33), card_border=(38, 44, 58),
    ink0=(236, 238, 244), ink1=(198, 204, 218), ink2=(150, 158, 176),
    ink3=(96, 104, 124), ink_faint=(60, 66, 82),
    track=(30, 34, 44),
    violet=(139, 125, 255), violet_soft=(176, 165, 250), accent=(168, 156, 255),
    green=(33, 208, 122), green_bar=(33, 208, 122), red=(255, 83, 96), sky=(70, 198, 224),
    title=(236, 238, 244), eyebrow=(168, 156, 255), card_fill=(14, 16, 22),
    shadow=(0, 0, 0, 0), logo_file="rendi-mark-violet.png", cta_text=(255, 255, 255),
)

# Claro — Frost con tarjetas blancas y sombra violeta suave. Logo ink.
LIGHT = Theme(
    "light",
    bg=(245, 243, 251), bg_glow=(250, 248, 252), glow_y=0.11, glow_a=9, glow_r=480,
    card=(255, 255, 255), card2=(250, 248, 252), card_border=(228, 224, 240),
    ink0=(17, 19, 26), ink1=(52, 56, 68), ink2=(120, 124, 140),
    ink3=(150, 158, 176), ink_faint=(182, 184, 198),
    track=(232, 229, 244),
    violet=(139, 125, 255), violet_soft=(176, 165, 250), accent=(96, 80, 222),
    green=(20, 168, 92), green_bar=(38, 190, 110), red=(224, 64, 78), sky=(70, 140, 235),
    title=(17, 19, 26), eyebrow=(96, 80, 222), card_fill=(255, 255, 255),
    shadow=(74, 62, 128, 42), logo_file="rendi-mark-ink.png", cta_text=(255, 255, 255),
)


def mix(fg, bg, a):
    return tuple(int(bg[i] + (fg[i] - bg[i]) * a) for i in range(3))


# ─── Helpers de texto ────────────────────────────────────────────────────────
def sw(d, t, f, sp=4):
    return sum(d.textlength(c, font=f) for c in t) + sp * (len(t) - 1) if t else 0

def spaced(d, t, x, y, f, fill, sp=4):
    cx = x
    for c in t:
        d.text((cx, y), c, font=f, fill=fill)
        cx += d.textlength(c, font=f) + sp
    return cx - x

def cen(d, t, y, f, fill, W=1080):
    w = d.textlength(t, font=f)
    d.text((W / 2 - w / 2, y), t, font=f, fill=fill)
    return w

def cen_spaced(d, t, y, f, fill, W=1080, sp=4):
    w = sw(d, t, f, sp)
    spaced(d, t, W / 2 - w / 2, y, f, fill, sp)
    return w

def cen_seg(d, segs, y, f, W=1080):
    """segs = [(texto, color), ...] centrado como una sola línea multicolor."""
    total = sum(d.textlength(t, font=f) for t, _ in segs)
    x = (W - total) / 2
    for t, c in segs:
        d.text((x, y), t, font=f, fill=c)
        x += d.textlength(t, font=f)

def wrap(d, text, f, mw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if d.textlength(test, font=f) <= mw:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ─── Canvas + glow ───────────────────────────────────────────────────────────
def canvas(t, size):
    W, H = size
    img = Image.new("RGBA", (W, H), (*t.bg, 255))
    dg = ImageDraw.Draw(img)
    if t.name == "dark":
        top = H * 0.34
        for y in range(H):
            if y < top:
                k = 1 - (y / top)
                col = mix(t.bg_glow, t.bg, k * 0.55)
            elif y > H - 320:
                k = (y - (H - 320)) / 320
                col = mix(t.bg_glow, t.bg, k * 0.32)
            else:
                continue
            dg.line([(0, y), (W, y)], fill=(*col, 255))
    else:
        for y in range(H):
            k = max(0.0, 1 - y / (H * 0.7))
            dg.line([(0, y), (W, y)], fill=(*mix(t.bg_glow, t.bg, k), 255))
    # glow violeta
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cyc = int(H * t.glow_y)
    R = t.glow_r
    for r in range(R, 0, -10):
        a = int((1 - r / R) * t.glow_a)
        gd.ellipse([W // 2 - r, cyc - r, W // 2 + r, cyc + r], fill=(*t.violet, a))
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    return Image.alpha_composite(img, glow)


# ─── Logo ────────────────────────────────────────────────────────────────────
_logo_cache = {}
def logo(t, h):
    key = (t.logo_file, h)
    if key not in _logo_cache:
        m = Image.open(os.path.join(LOGO_DIR, t.logo_file)).convert("RGBA")
        _logo_cache[key] = m.resize((int(m.width * h / m.height), h), Image.LANCZOS)
    return _logo_cache[key]


# ─── Chrome: header / footer ─────────────────────────────────────────────────
def header(img, t, eyebrow, W=1080, y=74, mark_h=38):
    """Logo + 'rendi' centrado, con eyebrow MAYÚSCULA mono debajo."""
    d = ImageDraw.Draw(img, "RGBA")
    mark = logo(t, mark_h)
    wf = F_SEMI(int(mark_h * 0.95))
    ww = d.textlength("rendi", font=wf)
    gap = 13
    x0 = (W - (mark.width + gap + ww)) / 2
    img.alpha_composite(mark, (int(x0), y))
    d.text((x0 + mark.width + gap, y + 1), "rendi", font=wf, fill=t.title)
    if eyebrow:
        cen_spaced(d, eyebrow.upper(), y + mark_h + 26, MONO_R(19), t.eyebrow, W, sp=3)
    return d


def footer(img, t, W=1080, H=1350, current=None, total=None, url=True):
    """Dots de paginación (si current/total) + rendi.finance."""
    d = ImageDraw.Draw(img, "RGBA")
    y_url = H - 78
    if current is not None and total:
        dot, gap = 8, 14
        sx = (W - (dot * total + gap * (total - 1))) / 2
        yd = H - 118
        for i in range(total):
            cx = sx + i * (dot + gap)
            d.ellipse([cx, yd, cx + dot, yd + dot],
                      fill=t.violet if i == current else t.ink_faint)
    if url:
        cen(d, "rendi.finance", y_url, MONO_R(21), t.ink2, W)
    return d


# ─── Tarjetas ────────────────────────────────────────────────────────────────
def card(img, t, box, radius=28, fill=None, border=None, blur=34, dy=16):
    """Tarjeta con sombra (violeta suave en claro, negra sutil en oscuro)."""
    x0, y0, x1, y1 = box
    sh_col = t.shadow if t.name == "light" else (0, 0, 0, 70)
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x0, y0 + dy, x1, y1 + dy], radius=radius, fill=sh_col)
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle(box, radius=radius, fill=fill or t.card_fill,
                        outline=border or t.card_border, width=1)
    return d


# ─── CTA pill ────────────────────────────────────────────────────────────────
def cta_pill(img, t, text, y, W=1080, size=32):
    d = ImageDraw.Draw(img, "RGBA")
    cf = F_SEMI(size)
    cwd = d.textlength(text, font=cf)
    px, py = 40, 22
    bw, bh = cwd + px * 2, cf.size + py * 2
    bx = (W - bw) / 2
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([bx, y + 9, bx + bw, y + bh + 9],
                                         radius=bh // 2, fill=(*t.violet, 75))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(22)))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=bh // 2, fill=t.violet)
    d.text((bx + px, y + py - 3), text, font=cf, fill=t.cta_text)
    return y + bh


# ─── Chips (brokers, etc.) ───────────────────────────────────────────────────
def chip_row(img, t, chips, y, W=1080, size=20):
    d = ImageDraw.Draw(img, "RGBA")
    cf = MONO_R(size)
    pad = 20
    widths = [d.textlength(c, font=cf) + pad * 2 + 23 for c in chips]
    gap = 14
    x = (W - (sum(widths) + gap * (len(chips) - 1))) / 2
    h = size + 28
    for c, wd in zip(chips, widths):
        d.rounded_rectangle([x, y, x + wd, y + h], radius=h // 2,
                            fill=t.card2 if t.name == "dark" else (255, 255, 255),
                            outline=t.card_border, width=1)
        d.ellipse([x + pad, y + h / 2 - 6, x + pad + 12, y + h / 2 + 6], fill=t.violet_soft)
        d.text((x + pad + 23, y + (h - size) / 2 - 3), c, font=cf, fill=t.ink1)
        x += wd + gap
    return y + h


# ─── Guardar ─────────────────────────────────────────────────────────────────
def save(img, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, name)
    img.convert("RGB").save(out, "PNG", optimize=True)
    print(f"  ✓ {name} ({os.path.getsize(out) / 1024:.0f}KB)")
    return out


def montage(names, out_name, cols=None, pad=24, bg=(20, 20, 24)):
    """Une varios PNG (mismo alto) en una tira horizontal para previsualizar."""
    imgs = [Image.open(os.path.join(OUT_DIR, n)).convert("RGB") for n in names]
    cols = cols or len(imgs)
    th = 720
    scaled = [im.resize((int(im.width * th / im.height), th)) for im in imgs]
    tw = sum(im.width for im in scaled) + pad * (len(scaled) + 1)
    canvas_img = Image.new("RGB", (tw, th + pad * 2), bg)
    x = pad
    for im in scaled:
        canvas_img.paste(im, (x, pad))
        x += im.width + pad
    out = os.path.join(OUT_DIR, out_name)
    canvas_img.save(out, "PNG")
    print(f"  ▦ montage {out_name}")
    return out
