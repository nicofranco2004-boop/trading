"""
social_batch.py — tanda de 10 piezas de contenido social de Rendi.
Alterna tono oscuro/claro pieza por pieza; cada carrusel mantiene un solo tono.
Usa el sistema visual compartido de brand.py.

  01  qué es rendi          imagen única   oscuro
  02  rendimiento real      imagen única   claro
  03  disposition effect    carrusel ×3    oscuro
  04  quiz 3 preguntas      carrusel ×4    claro
  05  coach ia              imagen única   oscuro
  06  centralizá brokers    carrusel ×3    claro
  07  export para AFIP      imagen única   oscuro
  08  origen (founder)      historia       claro
  09  listo en 3 pasos      historia       oscuro
  10  cta final             imagen única   claro

Correr:  python3 social_batch.py            (todas)
         python3 social_batch.py 3 5        (solo esas piezas)
"""

import sys
from PIL import Image, ImageDraw, ImageFilter
import brand as b
from brand import (
    DARK, LIGHT, FEED, STORY, canvas, header, footer, card, cta_pill, chip_row,
    cen, cen_seg, cen_spaced, spaced, wrap, sw, mix, save, montage,
    F_SEMI, F_MED, F_REG, MONO_M, MONO_R,
)

W = 1080


# ─── helpers locales ─────────────────────────────────────────────────────────
def bullet_check(d, t, x, y, r=11):
    d.ellipse([x, y, x + r * 2, y + r * 2], fill=mix(t.green, t.card_fill, 0.18),
              outline=t.green, width=2)
    d.line([(x + r * 0.6, y + r), (x + r * 0.95, y + r * 1.4)], fill=t.green, width=3)
    d.line([(x + r * 0.95, y + r * 1.4), (x + r * 1.45, y + r * 0.55)], fill=t.green, width=3)


def steps_card(img, t, box, steps, num_r=34, t1s=34, t2s=27):
    x0, y0, x1, y1 = box
    d = card(img, t, box, radius=30)
    pad = 52
    ix = x0 + pad
    rh = (y1 - y0 - pad) / len(steps)
    for i, (num, l1, l2) in enumerate(steps):
        ry = y0 + pad / 2 + i * rh + 18
        ccx, ccy = ix + num_r, ry + num_r
        d.ellipse([ccx - num_r, ccy - num_r, ccx + num_r, ccy + num_r],
                  fill=mix(t.violet, t.card_fill, 0.16), outline=t.violet, width=2)
        nf = MONO_M(int(num_r * 0.9))
        nw = d.textlength(num, font=nf)
        d.text((ccx - nw / 2, ccy - num_r * 0.66), num, font=nf, fill=t.accent)
        tx = ix + num_r * 2 + 26
        d.text((tx, ry + 4), l1, font=F_SEMI(t1s), fill=t.title)
        d.text((tx, ry + t1s + 12), l2, font=F_REG(t2s), fill=t.ink1)
        if i < len(steps) - 1:
            for dy in range(0, int(rh - num_r * 2 - 8), 13):
                d.line([(ccx, ccy + num_r + dy), (ccx, ccy + num_r + dy + 5)],
                       fill=t.card_border, width=2)
    return d


def bubble(img, t, text, y, side, maxw=640, fill=None, txt=None, label=None):
    """Burbuja de chat. side='r' usuario (derecha), 'l' coach (izquierda)."""
    d = ImageDraw.Draw(img, "RGBA")
    bf = F_REG(30)
    lines = wrap(d, text, bf, maxw - 64)
    lh = 42
    bh = len(lines) * lh + 48 + (30 if label else 0)
    bw = min(maxw, max(d.textlength(ln, font=bf) for ln in lines) + 64)
    if side == "r":
        x0 = W - 90 - bw
        bgc = fill or t.violet
        tc = txt or (255, 255, 255)
    else:
        x0 = 90
        bgc = fill or (t.card2 if t.name == "dark" else (255, 255, 255))
        tc = txt or t.ink0
    box = [x0, y, x0 + bw, y + bh]
    if t.name == "light" and side == "l":
        card(img, t, box, radius=26, blur=24, dy=10)
        d = ImageDraw.Draw(img, "RGBA")
    else:
        d.rounded_rectangle(box, radius=26, fill=bgc,
                            outline=t.card_border if side == "l" else None,
                            width=1 if side == "l" else 0)
    ty = y + 26
    if label:
        cen_lbl_x = x0 + 30
        d.ellipse([cen_lbl_x, ty + 2, cen_lbl_x + 14, ty + 16], fill=t.violet)
        spaced(d, label.upper(), cen_lbl_x + 24, ty, MONO_R(17), t.accent, sp=2)
        ty += 36
    for ln in lines:
        d.text((x0 + 32, ty), ln, font=bf, fill=tc)
        ty += lh
    return y + bh


def comp_bars(d, t, ix, iw, ry, rows, vf_size=28, lh=92):
    """Barras de comparación etiqueta + valor + barra. rows=[(name,val,frac,col,emph)]"""
    for name, val, frac, col, emph in rows:
        d.text((ix, ry), name, font=F_MED(29), fill=t.ink0 if emph else t.ink1)
        vf = MONO_M(vf_size)
        d.text((ix + iw - d.textlength(val, font=vf), ry - 1), val, font=vf,
               fill=col if emph else t.ink2)
        by = ry + 44
        d.rounded_rectangle([ix, by, ix + iw, by + 12], radius=6, fill=t.track)
        d.rounded_rectangle([ix, by, ix + int(iw * frac), by + 12], radius=6, fill=col)
        ry += lh
    return ry


# ════════════════════════════════════════════════════════════════════════════
# 01 — QUÉ ES RENDI · imagen única · OSCURO
# ════════════════════════════════════════════════════════════════════════════
def piece_01():
    t = DARK
    img = canvas(t, FEED)
    d = header(img, t, "/ qué es rendi")

    cen(d, "Toda tu plata invertida,", 250, F_SEMI(64), t.title)
    cen(d, "en una sola cartera.", 332, F_SEMI(64), t.title)

    cen(d, "Rendi junta lo que tenés en cada broker y te muestra", 452, F_REG(29), t.ink2)
    cen(d, "el rendimiento real, en dólares.", 494, F_REG(29), t.ink2)

    # hero card — el número consolidado
    cx, cy, cw, ch = 130, 600, 820, 320
    d = card(img, t, [cx, cy, cx + cw, cy + ch], radius=30)
    spaced(d, "TU CARTERA HOY", cx + 50, cy + 44, MONO_R(20), t.ink3, sp=2)
    cen(d, "USD 24.873", cy + 96, F_SEMI(86), t.title)
    cen_seg(d, [("+18,2%", t.green), ("  este año", t.ink2)], cy + 206, MONO_M(30))
    cen(d, "vs S&P 500 +12,4%  ·  inflación +4,1%", cy + 258, MONO_R(20), t.ink3)

    chip_row(img, t, ["COCOS", "IOL", "BINANCE", "SCHWAB"], 1000)
    footer(img, t, W, FEED[1])
    save(img, "p01_que_es.png")


# ════════════════════════════════════════════════════════════════════════════
# 02 — RENDIMIENTO REAL vs INFLACIÓN · imagen única · CLARO
# ════════════════════════════════════════════════════════════════════════════
def piece_02():
    t = LIGHT
    img = canvas(t, FEED)
    d = header(img, t, "/ tu rendimiento real")

    cen(d, "Tu broker dice +40%.", 248, F_SEMI(66), t.ink0)
    cen(d, "La inflación dice otra cosa.", 330, F_SEMI(66), t.ink0)

    cx, cy, cw, ch = 120, 470, 840, 470
    d = card(img, t, [cx, cy, cx + cw, cy + ch], radius=30)
    ix, iw = cx + 50, cw - 100
    spaced(d, "TU AÑO · MEDIDO EN PESOS", ix, cy + 38, MONO_R(19), t.ink2, sp=2)
    ry = comp_bars(d, t, ix, iw, cy + 96, [
        ("Tu cartera", "+40,0%", 0.77, t.green_bar, False),
        ("Inflación del período", "+52,0%", 1.00, t.ink_faint, False),
    ])
    # separador + resultado real
    d.line([(ix, ry + 2), (ix + iw, ry + 2)], fill=t.card_border, width=1)
    d.text((ix, ry + 30), "En poder de compra", font=F_MED(30), fill=t.ink0)
    rf = F_SEMI(46)
    d.text((ix + iw - d.textlength("−7,9%", font=rf), ry + 18), "−7,9%", font=rf, fill=t.red)

    cen(d, "Ejemplo ilustrativo", cy + ch + 30, F_REG(20), t.ink_faint)
    cen(d, "El número nominal en pesos miente cuando hay inflación.", cy + ch + 70, F_REG(28), t.ink1)
    cen(d, "Rendi te muestra el real.", cy + ch + 110, F_SEMI(28), t.ink0)

    footer(img, t, W, FEED[1])
    save(img, "p02_real.png")


# ════════════════════════════════════════════════════════════════════════════
# 03 — DISPOSITION EFFECT · carrusel ×3 · OSCURO
# ════════════════════════════════════════════════════════════════════════════
def piece_03():
    t = DARK
    H = FEED[1]
    # slide 1 — hook
    img = canvas(t, FEED)
    d = header(img, t, "/ un sesgo caro")
    cen(d, "Vendés tus ganadoras", 360, F_SEMI(62), t.title)
    cen_seg(d, [("rápido", t.green), (".", t.title)], 440, F_SEMI(62))
    cen(d, "Te aferrás a tus", 560, F_SEMI(62), t.title)
    cen_seg(d, [("perdedoras", t.red), (".", t.title)], 640, F_SEMI(62))
    cen(d, "Tiene nombre, y te cuesta plata.", 800, F_REG(30), t.ink2)
    footer(img, t, W, H, current=0, total=3)
    save(img, "p03_disposition_1.png")

    # slide 2 — la asimetría
    img = canvas(t, FEED)
    d = header(img, t, "/ disposition effect")
    cen(d, "El mismo inversor,", 232, F_SEMI(56), t.title)
    cen(d, "dos criterios opuestos.", 304, F_SEMI(56), t.title)
    # dos tarjetas
    gap = 36
    cw = (820 - gap) / 2
    cx1, cy, ch = 130, 440, 360
    for cx, head, big, sub, col in [
        (cx1, "GANADORA", "+18%", "vendida en 3 semanas", t.green),
        (cx1 + cw + gap, "PERDEDORA", "−40%", "sostenida 11 meses", t.red),
    ]:
        d = card(img, t, [cx, cy, cx + cw, cy + ch], radius=26)
        spaced(d, head, cx + 36, cy + 38, MONO_R(19), t.ink3, sp=2)
        d.text((cx + 36, cy + 110), big, font=F_SEMI(72), fill=col)
        for j, ln in enumerate(wrap(d, sub, F_REG(27), cw - 72)):
            d.text((cx + 36, cy + 210 + j * 36), ln, font=F_REG(27), fill=t.ink1)
    cen(d, "De a una, cada venta tiene su excusa.", cy + ch + 56, F_REG(29), t.ink2)
    cen(d, "En promedio, el patrón queda expuesto.", cy + ch + 98, F_REG(29), t.ink2)
    footer(img, t, W, H, current=1, total=3)
    save(img, "p03_disposition_2.png")

    # slide 3 — Rendi detecta + CTA
    img = canvas(t, FEED)
    d = header(img, t, "/ rendi lo detecta")
    cen(d, "Rendi te muestra el patrón", 300, F_SEMI(58), t.title)
    cen(d, "en tus operaciones reales.", 376, F_SEMI(58), t.title)
    cx, cy, cw2, ch2 = 160, 520, 760, 250
    d = card(img, t, [cx, cy, cx + cw2, cy + ch2], radius=28)
    cen(d, "13", cy + 50, F_SEMI(92), t.accent)
    cen(d, "detectores de sesgos de comportamiento", cy + 168, F_REG(27), t.ink1)
    cen(d, "Análisis de comportamiento — plan Plus", 840, MONO_R(20), t.ink3)
    cta_pill(img, t, "Probalo en rendi.finance", 920, W)
    footer(img, t, W, H, current=2, total=3)
    save(img, "p03_disposition_3.png")

    montage(["p03_disposition_1.png", "p03_disposition_2.png", "p03_disposition_3.png"],
            "_preview_03.png")


# ════════════════════════════════════════════════════════════════════════════
# 04 — QUIZ 3 PREGUNTAS · carrusel ×4 · CLARO
# ════════════════════════════════════════════════════════════════════════════
def piece_04():
    t = LIGHT
    H = FEED[1]

    def question_slide(n, idx, q_lines, hint):
        img = canvas(t, FEED)
        d = header(img, t, f"/ pregunta {idx}")
        cx, cy, cw, ch = 130, 430, 820, 380
        d = card(img, t, [cx, cy, cx + cw, cy + ch], radius=30)
        nf = F_SEMI(120)
        d.text((cx + 56, cy + 36), f"0{idx}", font=nf, fill=mix(t.violet_soft, t.card_fill, 0.7))
        yy = cy + 210
        for ln in q_lines:
            d.text((cx + 56, yy), ln, font=F_SEMI(44), fill=t.ink0)
            yy += 56
        cen(d, hint, cy + ch + 60, F_REG(27), t.ink2)
        return img

    # slide 1 — hook
    img = canvas(t, FEED)
    d = header(img, t, "/ quiz rápido")
    cen(d, "3 preguntas sobre", 360, F_SEMI(66), t.ink0)
    cen(d, "tu cartera que hoy", 442, F_SEMI(66), t.ink0)
    cen_seg(d, [("no podés responder", t.accent), (".", t.ink0)], 524, F_SEMI(66))
    cen(d, "¿Cuántas sabés de memoria? Deslizá.", 700, F_REG(30), t.ink1)
    footer(img, t, W, H, current=0, total=4)
    save(img, "p04_quiz_1.png")

    img = question_slide(2, 1, ["¿Le estás ganando", "a la inflación?"],
                         "El número nominal no alcanza para saberlo.")
    footer(img, t, W, H, current=1, total=4)
    save(img, "p04_quiz_2.png")

    img = question_slide(3, 2, ["¿Cuánto pesa tu", "activo más grande?"],
                         "Si pasa el 30%, una mala noticia te mueve todo.")
    footer(img, t, W, H, current=2, total=4)
    save(img, "p04_quiz_3.png")

    # slide 4 — Q3 + CTA
    img = canvas(t, FEED)
    d = header(img, t, "/ pregunta 3")
    cx, cy, cw, ch = 130, 360, 820, 360
    d = card(img, t, [cx, cy, cx + cw, cy + ch], radius=30)
    d.text((cx + 56, cy + 32), "03", font=F_SEMI(120), fill=mix(t.violet_soft, t.card_fill, 0.7))
    yy = cy + 200
    for ln in ["¿Cuánto te llevaron", "las comisiones?"]:
        d.text((cx + 56, yy), ln, font=F_SEMI(44), fill=t.ink0)
        yy += 56
    cen(d, "Rendi te responde las tres, con tus datos.", cy + ch + 56, F_REG(29), t.ink1)
    cta_pill(img, t, "Empezá gratis en rendi.finance", cy + ch + 120, W)
    footer(img, t, W, H, current=3, total=4)
    save(img, "p04_quiz_4.png")

    montage(["p04_quiz_1.png", "p04_quiz_2.png", "p04_quiz_3.png", "p04_quiz_4.png"],
            "_preview_04.png")


# ════════════════════════════════════════════════════════════════════════════
# 05 — COACH IA · imagen única · OSCURO
# ════════════════════════════════════════════════════════════════════════════
def piece_05():
    t = DARK
    img = canvas(t, FEED)
    d = header(img, t, "/ coach ia")
    cen(d, "Preguntale a tu cartera.", 244, F_SEMI(64), t.title)

    y = 380
    y = bubble(img, t, "¿Estoy muy concentrado en un activo?", y, "r", maxw=560) + 28
    bubble(img, t,
           "El 41% de tu cartera está en una sola acción. Es tu mayor riesgo: "
           "si una posición pesa más del 25–30%, un mal trimestre de ese activo "
           "te mueve toda la cartera.",
           y, "l", maxw=700, label="coach ia")

    d = ImageDraw.Draw(img, "RGBA")
    cen(d, "Lee tu cartera real y te responde en tus números.", 1015, F_REG(28), t.ink2)
    cta_pill(img, t, "Probalo en rendi.finance", 1080, W, size=30)
    footer(img, t, W, FEED[1])
    save(img, "p05_coach.png")


# ════════════════════════════════════════════════════════════════════════════
# 06 — CENTRALIZÁ BROKERS · carrusel ×3 · CLARO
# ════════════════════════════════════════════════════════════════════════════
def piece_06():
    t = LIGHT
    H = FEED[1]
    # slide 1 — el problema
    img = canvas(t, FEED)
    d = header(img, t, "/ una sola cartera")
    cen(d, "Tu cartera está", 320, F_SEMI(66), t.ink0)
    cen(d, "partida en 4 apps.", 402, F_SEMI(66), t.ink0)
    cen(d, "Ninguna te da la foto completa.", 560, F_REG(30), t.ink1)
    chip_row(img, t, ["COCOS", "IOL", "BINANCE", "SCHWAB"], 700, size=22)
    footer(img, t, W, H, current=0, total=3)
    save(img, "p06_brokers_1.png")

    # slide 2 — el merge
    img = canvas(t, FEED)
    d = header(img, t, "/ todo junto")
    cen(d, "Rendi los junta a todos.", 280, F_SEMI(60), t.ink0)
    chip_row(img, t, ["COCOS", "IOL"], 430, size=22)
    chip_row(img, t, ["BINANCE", "SCHWAB"], 510, size=22)
    # flecha hacia abajo
    cen(d, "↓", 600, F_SEMI(60), t.accent)
    cx, cy, cw, ch = 200, 700, 680, 230
    d = card(img, t, [cx, cy, cx + cw, cy + ch], radius=28)
    spaced(d, "TU CARTERA · EN USD", cx + 44, cy + 38, MONO_R(19), t.ink2, sp=2)
    cen(d, "USD 24.873", cy + 92, F_SEMI(72), t.ink0)
    cen_seg(d, [("+18,2%", t.green), ("  este año", t.ink2)], cy + 178, MONO_M(26))
    footer(img, t, W, H, current=1, total=3)
    save(img, "p06_brokers_2.png")

    # slide 3 — cómo + CTA
    img = canvas(t, FEED)
    d = header(img, t, "/ así de fácil")
    cen(d, "Importás un CSV", 300, F_SEMI(64), t.ink0)
    cen(d, "y listo.", 382, F_SEMI(64), t.ink0)
    cen(d, "Sin planillas. Sin cargar nada a mano.", 520, F_REG(30), t.ink1)
    cta_pill(img, t, "Empezá gratis en rendi.finance", 660, W)
    footer(img, t, W, H, current=2, total=3)
    save(img, "p06_brokers_3.png")

    montage(["p06_brokers_1.png", "p06_brokers_2.png", "p06_brokers_3.png"],
            "_preview_06.png")


# ════════════════════════════════════════════════════════════════════════════
# 07 — EXPORT PARA AFIP · imagen única · OSCURO
# ════════════════════════════════════════════════════════════════════════════
def piece_07():
    t = DARK
    img = canvas(t, FEED)
    d = header(img, t, "/ para tu contador")
    cen(d, "Todo listo para AFIP,", 250, F_SEMI(64), t.title)
    cen(d, "en un click.", 332, F_SEMI(64), t.title)

    cx, cy, cw, ch = 150, 470, 780, 420
    d = card(img, t, [cx, cy, cx + cw, cy + ch], radius=30)
    spaced(d, "MOVIMIENTOS DEL AÑO", cx + 48, cy + 40, MONO_R(19), t.ink3, sp=2)
    items = ["Compras y ventas", "Dividendos e intereses", "Depósitos y retiros", "Resultado por activo"]
    iy = cy + 96
    for it in items:
        bullet_check(d, t, cx + 48, iy + 2, r=11)
        d.text((cx + 90, iy - 4), it, font=F_REG(29), fill=t.ink1)
        iy += 58
    # chip de descarga
    chip = "rendi-afip-2025.csv"
    cf = MONO_M(24)
    cwd = d.textlength(chip, font=cf) + 90
    bx = cx + (cw - cwd) / 2
    by = cy + ch - 90
    d.rounded_rectangle([bx, by, bx + cwd, by + 56], radius=14,
                        fill=mix(t.violet, t.card_fill, 0.16), outline=t.violet, width=1)
    d.text((bx + 28, by + 13), chip, font=cf, fill=t.accent)
    d.text((bx + cwd - 40, by + 12), "↓", font=F_SEMI(28), fill=t.accent)

    cen(d, "Exportás el año entero en un CSV listo para mandar.", 960, F_REG(28), t.ink2)
    cen(d, "Sin armar la planilla a mano.", 1004, F_SEMI(28), t.ink0)
    footer(img, t, W, FEED[1])
    save(img, "p07_afip.png")


# ════════════════════════════════════════════════════════════════════════════
# 08 — ORIGEN (FOUNDER) · historia · CLARO
# ════════════════════════════════════════════════════════════════════════════
def piece_08():
    t = LIGHT
    H = STORY[1]
    img = canvas(t, STORY)
    d = header(img, t, "/ por qué lo armé", y=300, mark_h=42)

    cen(d, "Tenía la plata en cuatro", 560, F_SEMI(60), t.ink0)
    cen(d, "brokers y no sabía cuánto", 636, F_SEMI(60), t.ink0)
    cen(d, "había ganado de verdad.", 712, F_SEMI(60), t.ink0)

    body = ("Las apps me mostraban un número en pesos que la inflación se comía. "
            "Para tener la foto real armaba una planilla a mano cada mes.")
    yy = 880
    for ln in wrap(d, body, F_REG(34), 860):
        cen(d, ln, yy, F_REG(34), t.ink1)
        yy += 50
    yy += 24
    cen(d, "No encontré la herramienta que", yy, F_MED(34), t.ink0); yy += 50
    cen(d, "necesitaba, así que la construí.", yy, F_MED(34), t.ink0)

    # marca + hint de link sticker
    cen(d, "— el que armó Rendi", yy + 130, F_REG(28), t.ink2)
    cen_spaced(d, "DESLIZÁ PARA PROBARLO", 1500, MONO_R(22), t.accent, W, sp=3)
    footer(img, t, W, H)
    save(img, "p08_origen_story.png")


# ════════════════════════════════════════════════════════════════════════════
# 09 — LISTO EN 3 PASOS · historia · OSCURO
# ════════════════════════════════════════════════════════════════════════════
def piece_09():
    t = DARK
    H = STORY[1]
    img = canvas(t, STORY)
    d = header(img, t, "/ así de fácil", y=300, mark_h=42)

    cen(d, "Listo en 3 pasos.", 540, F_SEMI(80), t.title)
    steps = [
        ("1", "Creás tu cuenta", "gratis, en rendi.finance."),
        ("2", "Importás el CSV", "de movimientos de tu broker."),
        ("3", "Listo.", "Ves tu cartera entera, en dólares."),
    ]
    steps_card(img, t, [100, 720, 980, 1320], steps, num_r=38, t1s=38, t2s=30)
    cen(d, "Sin planillas. Sin cargar nada a mano.", 1380, F_REG(30), t.ink2)
    cta_pill(img, t, "Empezá gratis en rendi.finance", 1460, W, size=34)
    footer(img, t, W, H)
    save(img, "p09_pasos_story.png")


# ════════════════════════════════════════════════════════════════════════════
# 10 — CTA FINAL · imagen única · CLARO
# ════════════════════════════════════════════════════════════════════════════
def piece_10():
    t = LIGHT
    img = canvas(t, FEED)
    d = header(img, t, "/ empezá hoy")

    cen(d, "Mirá tu plata", 330, F_SEMI(82), t.ink0)
    cen(d, "como nunca la viste.", 426, F_SEMI(82), t.ink0)

    cen(d, "Todos tus brokers, tu rendimiento real en dólares", 590, F_REG(30), t.ink1)
    cen(d, "y los sesgos que te cuestan plata. En un solo lugar.", 632, F_REG(30), t.ink1)

    chip_row(img, t, ["MULTI-BROKER", "USD REAL", "COACH IA"], 760, size=20)
    cta_pill(img, t, "Empezá gratis en rendi.finance", 900, W)
    footer(img, t, W, FEED[1])
    save(img, "p10_cta.png")


PIECES = {1: piece_01, 2: piece_02, 3: piece_03, 4: piece_04, 5: piece_05,
          6: piece_06, 7: piece_07, 8: piece_08, 9: piece_09, 10: piece_10}

if __name__ == "__main__":
    sel = [int(a) for a in sys.argv[1:]] or list(PIECES)
    for n in sel:
        print(f"\n[{n:02d}]")
        PIECES[n]()
    print("\nDone.")
