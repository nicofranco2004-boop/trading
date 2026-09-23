"""generate-og-image — genera el og-image.png 1200x630 de Rendi.
═══════════════════════════════════════════════════════════════════════════
Es la imagen que se ve cuando alguien pega rendi.finance en WhatsApp, X,
LinkedIn, Slack o Discord. Correr:

    python3 frontend/scripts/generate-og-image.py

Especificaciones:
  · 1200 × 630 px (el ratio 1.91:1 de las tarjetas de FB/X)
  · Tiene que leerse REDUCIDA a ~360×189 (el preview del celular). Por eso
    manda el título grande, la cápsula violeta y el número; el resto es
    textura. Todo lo que no se lea a un tercio, sobra.

Qué cambió respecto de la versión anterior, y por qué:
  🔴 El pie decía "Free · Plus $4 · Pro $9 USD/mes": ofrecía un plan gratis
     que ya no es la puerta de entrada y precios en DÓLARES VIEJOS. Se cobra
     en pesos. Ahora dice los dos, con "≈" en el dólar porque el equivalente
     se mueve con el tipo de cambio.
  · Lo que se vende arriba es la PRUEBA (20 días, sin tarjeta), no la
     descripción del producto.
  · A la derecha va el VEREDICTO ("¿le estás ganando?"), que es lo único que
     no muestra ningún competidor, y no una lista de posiciones. Una de las
     tres filas va en ROJO a propósito: una tarjeta donde todo está verde se
     lee como publicidad, una que admite que el S&P te gana se lee como una
     herramienta.
  · Los logos de los activos (los del propio repo) van al pie de la tarjeta,
     chicos: dicen "es una cartera real" sin robarle la atención al veredicto.

⚠️ Los PRECIOS y los DÍAS de este archivo están a mano porque es un script de
diseño que corre a pedido. Los compara `backend/tests/test_promesas_vs_producto.py`
contra `billing/pricing.py` y `billing/trial.py`: si se desfasan, sale en rojo.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ─── Lienzo y paleta (los tokens del design system) ─────────────────────
W, H = 1200, 630
BG        = (7, 9, 12)        # #07090C  bg-0
PANEL     = (13, 16, 21)      # #0D1015  bg-1
LINE      = (27, 32, 48)      # #1B2030
INK_0     = (230, 234, 242)   # #E6EAF2
INK_2     = (156, 163, 181)   # #9CA3B5
INK_3     = (90, 100, 120)    # #5A6478
VIOLET    = (139, 125, 255)   # #8B7DFF  data-violet
VERDE     = (33, 208, 122)    # #21D07A  rendi-pos
ROJO      = (255, 83, 96)     # #FF5360  rendi-neg

AQUI   = Path(__file__).parent
FUENTES = AQUI.parent.parent / 'design' / 'fonts'
LOGOS   = AQUI.parent / 'public' / 'logos'
OUT     = AQUI.parent / 'public' / 'og-image.png'

# Los números que se muestran. Una cartera de ejemplo, coherente entre sí.
CARTERA_USD   = 'US$ 24.180'
CARTERA_VAR   = '+18,4%'
CARTERA_PESOS = '$36.270.000 al dólar de hoy'
VEREDICTOS = [
    ('Inflación argentina', '+14,7%', 'le ganás', VERDE),
    ('Dólar MEP',           '+9,2%',  'le ganás', VERDE),
    ('S&P 500',             '+21,1%', 'te gana',  ROJO),
]
BROKERS = ['Cocos', 'Balanz', 'IOL', 'Bull Market', 'Binance', '+9 más']
TICKERS = ['NVDA', 'GGAL', 'BTC', 'MELI']
DIAS_DE_PRUEBA = 20
PIE_PRECIOS = 'Después de la prueba: Plus $5.990 (≈US$4) · Pro $13.990 (≈US$9) por mes'


def fuente(px: int, peso: str = 'regular') -> ImageFont.FreeTypeFont:
    """Geist, la tipografía de Rendi, desde `design/fonts`.

    Está en el repo, así que NO hace falta red ni que esté instalada — la
    versión anterior caía a Helvetica del sistema y la imagen no era la marca.
    Si el archivo no estuviera, se avisa y se sigue con la del sistema antes
    que reventar."""
    archivos = {'regular': 'Geist-Regular.ttf',
                'medium': 'Geist-Medium.ttf',
                'bold': 'Geist-SemiBold.ttf'}
    ruta = FUENTES / archivos[peso]
    if ruta.exists():
        return ImageFont.truetype(str(ruta), px)
    print(f'  ⚠️  falta {ruta.name}; uso la del sistema')
    for alt in ('/System/Library/Fonts/Helvetica.ttc',
                '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf'):
        if Path(alt).exists():
            return ImageFont.truetype(alt, px)
    return ImageFont.load_default()


def ancho(draw, texto, f) -> int:
    caja = draw.textbbox((0, 0), texto, font=f)
    return caja[2] - caja[0]


def resplandor(img: Image.Image) -> Image.Image:
    """El halo violeta arriba a la derecha. Se dibuja como un degradado radial
    real (un canal alfa por radio) y no con rectángulos translúcidos, que era
    lo que hacía antes y se veía como bandas."""
    cx, cy, r = 1010, 40, 420
    capa = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    px = capa.load()
    for y in range(max(0, cy - r), min(H, cy + r)):
        for x in range(max(0, cx - r), min(W, cx + r)):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if d < r:
                t = 1 - d / r
                px[x, y] = (*VIOLET, int(46 * t * t))
    return Image.alpha_composite(img.convert('RGBA'), capa).convert('RGB')


def caja_redondeada(draw, xy, radio, relleno=None, borde=None, grosor=1):
    draw.rounded_rectangle(xy, radius=radio, fill=relleno, outline=borde, width=grosor)


def logo_circular(img: Image.Image, ticker: str, x: int, y: int, lado: int):
    """Pega el logo del activo recortado en círculo. Si falta el archivo, deja
    un círculo con la inicial: nunca un hueco."""
    ruta = LOGOS / f'{ticker}.png'
    if not ruta.exists():
        d = ImageDraw.Draw(img)
        d.ellipse([x, y, x + lado, y + lado], fill=(27, 32, 48))
        return
    logo = Image.open(ruta).convert('RGBA').resize((lado, lado), Image.LANCZOS)
    mascara = Image.new('L', (lado, lado), 0)
    ImageDraw.Draw(mascara).ellipse([0, 0, lado - 1, lado - 1], fill=255)
    fondo = Image.new('RGBA', (lado, lado), (255, 255, 255, 255))
    fondo.alpha_composite(logo)
    img.paste(fondo, (x, y), mascara)


def main():
    img = Image.new('RGB', (W, H), BG)
    img = resplandor(img)
    d = ImageDraw.Draw(img)

    # ══ IZQUIERDA ══════════════════════════════════════════════════════
    X = 56

    # Marca: cuadradito violeta con la R + wordmark
    caja_redondeada(d, (X, 46, X + 40, 86), 11, relleno=VIOLET)
    f_r = fuente(24, 'bold')
    d.text((X + 20, 66), 'R', font=f_r, fill=BG, anchor='mm')
    d.text((X + 54, 66), 'rendi', font=fuente(29, 'bold'), fill=INK_0, anchor='lm')

    # La cápsula de la prueba: lo primero que se lee, y lo que se vende
    f_pill = fuente(17, 'bold')
    texto_pill = f'{DIAS_DE_PRUEBA} días gratis · sin tarjeta'
    w_pill = ancho(d, texto_pill, f_pill) + 54
    caja_redondeada(d, (X, 126, X + w_pill, 170), 22,
                    relleno=(23, 22, 45), borde=(66, 60, 120), grosor=1)
    d.ellipse([X + 20, 145, X + 27, 152], fill=VIOLET)
    d.text((X + 36, 148), texto_pill, font=f_pill, fill=VIOLET, anchor='lm')

    # Titular: dos líneas, el gancho
    f_t = fuente(54, 'bold')
    d.text((X, 196), 'Todos tus brokers,', font=f_t, fill=INK_0)
    d.text((X, 256), 'una sola respuesta', font=f_t, fill=INK_0)

    # Bajada: la pregunta que Rendi contesta
    f_s = fuente(20)
    d.text((X, 334), '¿Le estás ganando a la inflación,', font=f_s, fill=INK_2)
    d.text((X, 362), 'al dólar y al S&P? Rendi te lo dice.', font=f_s, fill=INK_2)

    # Los brokers, por NOMBRE (no tenemos sus logos y usarlos pide permiso)
    f_b = fuente(15)
    bx, by = X, 418
    for i, nombre in enumerate(BROKERS):
        w = ancho(d, nombre, f_b) + 26
        if bx + w > 600:                      # segunda fila
            bx, by = X, by + 40
        ultimo = i == len(BROKERS) - 1        # el "+9 más" va violeta
        caja_redondeada(d, (bx, by, bx + w, by + 32), 16,
                        relleno=(19, 18, 34) if ultimo else PANEL,
                        borde=(60, 55, 105) if ultimo else LINE)
        d.text((bx + w // 2, by + 16), nombre, font=f_b,
               fill=VIOLET if ultimo else INK_2, anchor='mm')
        bx += w + 8

    # Pie: dominio + los precios en las dos monedas
    d.text((X, H - 74), 'rendi.finance', font=fuente(21, 'bold'), fill=INK_0)
    d.text((X, H - 42), PIE_PRECIOS, font=fuente(14), fill=INK_3)

    # ══ DERECHA: la tarjeta del veredicto ══════════════════════════════
    # El alto sale del CONTENIDO, no al revés: con 438 quedaba una banda
    # muerta de 72 px entre el último veredicto y los logos. Y centrada
    # verticalmente en el lienzo, que con CY=96 quedaba corrida para arriba.
    CX, CY, CW, CH = 660, 126, 484, 378
    caja_redondeada(d, (CX, CY, CX + CW, CY + CH), 18,
                    relleno=PANEL, borde=LINE)
    px = CX + 26

    d.text((px, CY + 28), 'TU CARTERA · 4 BROKERS',
           font=fuente(12, 'bold'), fill=INK_3, anchor='lm')
    f_vivo = fuente(12, 'bold')
    t_vivo = 'En vivo'
    w_vivo = ancho(d, t_vivo, f_vivo)
    d.ellipse([CX + CW - 26 - w_vivo - 14, CY + 25, CX + CW - 26 - w_vivo - 8, CY + 31],
              fill=VERDE)
    d.text((CX + CW - 26, CY + 28), t_vivo, font=f_vivo, fill=VERDE, anchor='rm')

    # El número, lo más grande de la tarjeta
    f_num = fuente(44, 'bold')
    d.text((px, CY + 74), CARTERA_USD, font=f_num, fill=INK_0, anchor='lm')
    d.text((px + ancho(d, CARTERA_USD, f_num) + 14, CY + 78), CARTERA_VAR,
           font=fuente(19, 'bold'), fill=VERDE, anchor='lm')
    d.text((px, CY + 106), f'en el año · {CARTERA_PESOS}',
           font=fuente(13), fill=INK_3, anchor='lm')

    d.line([(px, CY + 134), (CX + CW - 26, CY + 134)], fill=LINE, width=1)

    # ESTO es Rendi: el veredicto, no el dato
    d.text((px, CY + 158), '¿LE ESTÁS GANANDO?',
           font=fuente(12, 'bold'), fill=INK_3, anchor='lm')

    y = CY + 192
    f_fila = fuente(15)
    f_chip = fuente(12, 'bold')
    for etiqueta, valor, veredicto, color in VEREDICTOS:
        d.text((px, y), etiqueta, font=f_fila, fill=INK_2, anchor='lm')
        # el chip del veredicto, pegado al borde derecho
        w_chip = 86
        x_chip = CX + CW - 26 - w_chip
        caja_redondeada(d, (x_chip, y - 12, x_chip + w_chip, y + 12), 12,
                        relleno=(18, 46, 34) if color == VERDE else (52, 22, 27))
        d.text((x_chip + w_chip // 2, y), veredicto, font=f_chip,
               fill=color, anchor='mm')
        d.text((x_chip - 16, y), valor, font=f_fila, fill=INK_3, anchor='rm')
        y += 38

    # Los logos, de textura al pie
    d.line([(px, CY + 300), (CX + CW - 26, CY + 300)], fill=LINE, width=1)
    lx = px
    for t in TICKERS:
        logo_circular(img, t, lx, CY + 320, 28)
        lx += 36
    d = ImageDraw.Draw(img)      # el paste invalida el draw anterior
    d.text((lx + 6, CY + 334), '+ 23 posiciones',
           font=fuente(13), fill=INK_3, anchor='lm')

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, 'PNG', optimize=True)
    print(f'✓ OG image generada: {OUT}')
    print(f'   {W}×{H} · {OUT.stat().st_size / 1024:.1f} KB')


if __name__ == '__main__':
    main()
