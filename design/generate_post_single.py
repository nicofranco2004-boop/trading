"""
Post de UNA sola slide (no carrusel) — versión clara y cálida.
1080×1350 (4:5 feed IG). Reúne el gancho + la prueba + el cierre en una imagen,
con info reducida para que respire.

  gancho:  ¿Estás ganando o perdiendo?  (ganando verde / perdiendo rojo)
  prueba:  tarjeta de cartera limpia (todo en una pantalla)
  cierre:  tu ganancia real, en dólar blue   ·  sin CTA

Reusa helpers/paleta de generate_post_clarity.py.
"""

import os
from generate_post_clarity import (
    W, H, OUT_DIR,
    build_light_canvas, draw_header, soft_card, mix,
    draw_centered, draw_centered_segments, draw_spaced_text,
    F_SANS_BOLD, F_SANS_REG, F_MONO_REG, F_MONO_BOLD,
    INK_STRONG, INK_BODY, INK_MUTE, WHITE, CARD_BORDER, TRACK,
    VIOLET_SOFT, GREEN, RED,
)


def generate_single():
    img = build_light_canvas()
    draw = draw_header(img, "Una pregunta simple")

    # ─── Gancho ───────────────────────────────────────────────────────────────
    hero = F_SANS_BOLD(64)
    draw_centered_segments(draw, [("¿Estás ", INK_STRONG), ("ganando", GREEN)], 258, hero)
    draw_centered_segments(draw, [("o ", INK_STRONG), ("perdiendo", RED), ("?", INK_STRONG)], 344, hero)

    # ─── Tarjeta de cartera (la prueba) ───────────────────────────────────────
    card_x, card_y, card_w, card_h = 110, 472, 860, 560
    pad = 46
    inner_x = card_x + pad
    inner_w = card_w - pad * 2
    draw = soft_card(img, [card_x, card_y, card_x + card_w, card_y + card_h], radius=30)

    draw_spaced_text(draw, "TU CARTERA", inner_x, card_y + pad, F_MONO_REG(20), INK_MUTE, spacing=2)
    draw.text((inner_x, card_y + pad + 32), "US$ 12.480", font=F_SANS_BOLD(72), fill=INK_STRONG)

    chg, cf = "+3,2% este mes", F_SANS_BOLD(25)
    cw = draw.textlength(chg, font=cf)
    cpad, cx, cyy = 18, inner_x, card_y + pad + 124
    draw.rounded_rectangle([cx, cyy, cx + cw + cpad * 2, cyy + 44], radius=22,
                           fill=mix(GREEN, WHITE, 0.16))
    draw.text((cx + cpad, cyy + 8), chg, font=cf, fill=GREEN)

    dv = cyy + 80
    draw.line([(inner_x, dv), (inner_x + inner_w, dv)], fill=CARD_BORDER, width=1)

    rows = [
        ("Plazo fijo", "US$ 4.100", 0.33),
        ("Dólares", "US$ 3.250", 0.26),
        ("Acciones y CEDEARs", "US$ 3.600", 0.29),
        ("Cripto", "US$ 1.530", 0.12),
    ]
    nf, vf = F_SANS_REG(28), F_MONO_BOLD(25)
    ry, row_h = dv + 30, 72
    for name, val, frac in rows:
        draw.text((inner_x, ry), name, font=nf, fill=INK_BODY)
        vw = draw.textlength(val, font=vf)
        draw.text((inner_x + inner_w - vw, ry), val, font=vf, fill=INK_STRONG)
        by = ry + 40
        draw.rounded_rectangle([inner_x, by, inner_x + inner_w, by + 8], radius=4, fill=TRACK)
        draw.rounded_rectangle([inner_x, by, inner_x + int(inner_w * frac), by + 8],
                               radius=4, fill=VIOLET_SOFT)
        ry += row_h

    # ─── Cierre (Geist regular, sin serif/itálica, sin CTA) ───────────────────
    draw_centered(draw, "Toda tu plata en una pantalla,", card_y + card_h + 52, F_SANS_REG(30), INK_BODY)
    draw_centered(draw, "con tu ganancia real en dólar blue.", card_y + card_h + 96, F_SANS_REG(30), INK_BODY)

    # Marca de agua (mono, no es CTA)
    bf = F_MONO_REG(22)
    bw = draw.textlength("rendi.finance", font=bf)
    draw.text((W / 2 - bw / 2, H - 76), "rendi.finance", font=bf, fill=INK_MUTE)

    out = os.path.join(OUT_DIR, "rendi_post_single.png")
    img.convert("RGB").save(out, "PNG", optimize=True)
    print(f"✓ single: {out} ({os.path.getsize(out)/1024:.1f}KB)")


if __name__ == "__main__":
    generate_single()
    print("Done.")
