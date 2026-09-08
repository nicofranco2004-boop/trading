"""Reemplaza los montos reales del screenshot por valores ilustrativos.

Factor único k=0.732406 sobre TODOS los montos → los porcentajes, las sumas y
la conversión al blue siguen cerrando entre sí. Se repinta con Geist, la misma
fuente que usa la app, ajustando tamaño y peso por medición del original.
"""
from PIL import Image, ImageDraw, ImageFont
import numpy as np

SRC = 'dash2.png'
OFF_X, OFF_Y = 820, 264                      # origen del crop dentro del screenshot
FONTS = '/Users/nicolaspussetto/Documents/trading/design/fonts/'
WEIGHTS = ['Geist-Regular.ttf', 'Geist-Medium.ttf', 'Geist-SemiBold.ttf']

# (x0, x1, y_top, y_bot, original, nuevo, color_texto, color_fondo, peso, criterio)
#   peso: None = elegir por medición | criterio: 'h' prioriza alto, 'w' ancho
S, M, R = 'Geist-SemiBold.ttf', 'Geist-Medium.ttf', 'Geist-Regular.ttf'
REPS = [
    (238, 515, 308, 368, '9,202.85',   '6,740.20',   (231, 234, 241), (15, 18, 23), S, 'h'),
    (387, 464, 412, 430, '823.51',     '603.14',     (99, 205, 130),  (24, 37, 34), None, 'h'),
    (694, 819, 412, 430, '14.015.027', '10.264.552', (157, 163, 179), (21, 25, 34), None, 'w'),
    (1217, 1314, 412, 433, '8,379.35', '6,137.06',   (157, 163, 179), (21, 25, 34), None, 'w'),
    (741, 819, 519, 538, '823.51',     '603.14',     (157, 163, 179), (15, 18, 23), None, 'h'),
    (147, 297, 808, 841, '8,379.35',   '6,137.06',   (231, 234, 241), (15, 18, 23), M, 'h'),
    (727, 875, 808, 841, '1,189.48',   '871.15',     (99, 205, 130),  (15, 18, 23), M, 'h'),
    (1282, 1356, 808, 836, '3.10',     '2.27',       (236, 96, 101),  (15, 18, 23), M, 'h'),
    (132, 205, 1170, 1188, '177.62',   '130.09',     (82, 168, 109),  (15, 18, 23), None, 'h'),
    (522, 596, 1170, 1188, '444.01',   '325.19',     (82, 168, 109),  (15, 18, 23), None, 'h'),
    (611, 679, 1206, 1222, '439.38',   '321.80',     (92, 100, 118),  (15, 18, 23), None, 'h'),
]

img = Image.open(SRC).convert('RGB')
d = ImageDraw.Draw(img)
probe = Image.new('RGB', (10, 10))
pd = ImageDraw.Draw(probe)


def fit(orig, h_target, w_target, force=None, mode='h'):
    """Elige peso y tamaño de Geist que reproducen el alto y ancho medidos."""
    best = None
    kh, kw = (3, 1) if mode == 'h' else (1, 3)
    for wname in ([force] if force else WEIGHTS):
        for size in range(8, 110):
            f = ImageFont.truetype(FONTS + wname, size)
            bb = pd.textbbox((0, 0), orig, font=f)
            h, w = bb[3] - bb[1], bb[2] - bb[0]
            err = abs(h - h_target) * kh + abs(w - w_target) * kw
            if best is None or err < best[0]:
                best = (err, wname, size, h, w)
    return best


for x0, x1, yt, yb, orig, new, col, bg, force, mode in REPS:
    h_t, w_t = yb - yt + 1, x1 - x0 + 1
    # mode 'w': el ancho manda (hay texto pegado a la derecha) → medir el string NUEVO,
    # porque los dígitos no tienen todos el mismo ancho en Geist proporcional.
    err, wname, size, h, w = fit(new if mode == 'w' else orig, h_t, w_t, force, mode)
    f = ImageFont.truetype(FONTS + wname, size)
    # tapar el original (con margen; los fondos son planos)
    d.rectangle([OFF_X + x0 - 4, OFF_Y + yt - 6, OFF_X + x1 + 4, OFF_Y + yb + 6], fill=bg)
    # alinear por el tope de los dígitos (no por el bbox, que cambia con la coma)
    dig = pd.textbbox((0, 0), '0', font=f)
    nb = pd.textbbox((0, 0), new, font=f)
    d.text((OFF_X + x0 - nb[0], OFF_Y + yt - dig[1]), new, font=f, fill=col)
    print(f'{orig:>12} → {new:<12} {wname[6:-4]:>9} {size}px  err={err}')

img.crop((OFF_X, OFF_Y, 3080, 1844)).save('app_clean.png')
print('✓ app_clean.png', Image.open('app_clean.png').size)
