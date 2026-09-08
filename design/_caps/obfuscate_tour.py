"""Ofusca los montos de las capturas del tour y las recorta para social.

Mismo criterio que `obfuscate_dashboard.py`: un factor único k=0.7324 sobre TODO
importe, así los porcentajes, las sumas y las conversiones siguen cerrando entre
sí. Los porcentajes, conteos y datos públicos (EPS, dividendo por acción) quedan
intactos porque no revelan tamaño de cartera.

Entrada:  capturas crudas de Safari (screencapture -x, retina 2×)
Salida:   _caps/app_<vista>.png ya recortadas y listas para componer
"""
from PIL import Image, ImageDraw, ImageFont
import os
import sys

FONTS = '/Users/nicolaspussetto/Documents/trading/design/fonts/'
S, M, R = 'Geist-SemiBold.ttf', 'Geist-Medium.ttf', 'Geist-Regular.ttf'
WEIGHTS = [R, M, S]
OUT = os.path.dirname(os.path.abspath(__file__))

probe = Image.new('RGB', (10, 10))
pd = ImageDraw.Draw(probe)


def fit(txt, h_target, w_target, force=None, mode='h'):
    best, kh, kw = None, (3, 1) if mode == 'h' else (1, 3), None
    kh, kw = (3, 1) if mode == 'h' else (1, 3)
    for wname in ([force] if force else WEIGHTS):
        for size in range(8, 130):
            f = ImageFont.truetype(FONTS + wname, size)
            bb = pd.textbbox((0, 0), txt, font=f)
            err = abs((bb[3] - bb[1]) - h_target) * kh + abs((bb[2] - bb[0]) - w_target) * kw
            if best is None or err < best[0]:
                best = (err, wname, size)
    return best


def process(src, crop, reps, out_name):
    img = Image.open(src).convert('RGB')
    d = ImageDraw.Draw(img)
    for x0, x1, yt, yb, orig, new, col, bg, force, mode in reps:
        err, wname, size = fit(new if mode == 'w' else orig,
                               yb - yt + 1, x1 - x0 + 1, force, mode)
        f = ImageFont.truetype(FONTS + wname, size)
        # margen chico: el bbox medido ya es el extremo exacto de la tinta y un
        # margen grande se come la etiqueta de arriba (pasó con "Tu cobro est.")
        d.rectangle([x0 - 4, yt - 3, x1 + 4, yb + 3], fill=bg)
        dig = pd.textbbox((0, 0), '0', font=f)
        nb = pd.textbbox((0, 0), new, font=f)
        d.text((x0 - nb[0], yt - dig[1]), new, font=f, fill=col)
        print(f'   {orig:>12} → {new:<12} {wname[6:-4]:>9} {size}px')
    out = os.path.join(OUT, out_name)
    img.crop(crop).save(out)
    print(f'✓ {out_name} {Image.open(out).size}')


TOUR = sys.argv[1] if len(sys.argv) > 1 else '.'
p = lambda n: os.path.join(TOUR, n)

# ── Cartera en vivo ─────────────────────────────────────────────────────────
print('CARTERA')
process(p('cartera.png'), (540, 424, 3360, 1244), [
    (770, 1048, 706, 766, '9,173.58',   '6,718.72',  (231, 234, 241), (15, 18, 23), S, 'h'),
    (738, 802, 810, 828,  '31.94',      '23.40',     (236, 96, 101),  (21, 25, 34), None, 'w'),
    (1118, 1215, 810, 831, '9,205.52',  '6,742.12',  (157, 163, 179), (21, 25, 34), None, 'w'),
    (664, 785, 1128, 1154, '2,259.33',  '1,654.75',  (231, 234, 241), (15, 18, 23), M, 'h'),
    (1064, 1222, 1128, 1150, '10.541.482', '7.720.581', (231, 234, 241), (15, 18, 23), M, 'h'),
    (1445, 1504, 1128, 1150, '2.03',    '1.49',      (231, 234, 241), (15, 18, 23), M, 'h'),
    (1059, 1145, 1175, 1192, '366.416', '268.363',   (99, 205, 130),  (15, 18, 23), None, 'w'),
], 'app_cartera.png')

# ── Performance histórica (calendario) ──────────────────────────────────────
print('REPORTES')
process(p('reportes.png'), (748, 650, 3150, 1552), [
    (804, 1040, 887, 931, '+US$1.045', '+US$765', (99, 204, 130), (15, 18, 23), S, 'h'),
], 'app_reportes.png')

# ── Comportamiento (sin montos que ofuscar) ─────────────────────────────────
print('COMPORTAMIENTO')
process(p('comportamiento.png'), (836, 656, 3070, 1776), [], 'app_comportamiento.png')

# ── Novedades (evento sobre tenencia real) ──────────────────────────────────
print('NOVEDADES')
process(p('novedades.png'), (700, 260, 3200, 1320), [
    (3019, 3146, 926, 961, '+$4.21', '+$3.09', (99, 205, 130), (15, 18, 23), S, 'h'),
    (1193, 1252, 979, 997, '86.00',  '63.00',  (157, 163, 179), (15, 18, 23), None, 'w'),
], 'app_novedades.png')
