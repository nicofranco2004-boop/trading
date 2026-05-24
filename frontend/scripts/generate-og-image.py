"""generate-og-image — genera el og-image.png 1200x630 de Rendi.
═══════════════════════════════════════════════════════════════════════════
Imagen que se muestra cuando alguien comparte rendi.finance en WhatsApp,
Twitter, LinkedIn, Slack, Discord, etc.

Especificaciones (recomendaciones oficiales 2026):
  - 1200 × 630 px (ratio 1.91:1 — el que usan FB/Twitter cards)
  - Texto legible incluso reducido a 360×189 (preview en mobile)
  - Brand de Rendi: fondo oscuro #07090c, accent violet #8b7dff,
    texto principal #e6eaf2

Correr: python3 frontend/scripts/generate-og-image.py
Output: frontend/public/og-image.png
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ─── Config ─────────────────────────────────────────────────────────────
W, H = 1200, 630
BG = (7, 9, 12)              # #07090c — bg-bg-0 del design system
INK_0 = (230, 234, 242)      # #e6eaf2 — text principal
INK_2 = (157, 168, 187)      # gray text secundario
VIOLET = (139, 125, 255)     # #8b7dff — data-violet accent
POS = (87, 201, 138)         # #57c98a — rendi-pos green
LINE = (40, 46, 56)          # borders

OUT = Path(__file__).parent.parent / 'public' / 'og-image.png'


def _load_font(size: int, weight: str = 'regular') -> ImageFont.FreeTypeFont:
    """Carga una fuente system. Fallback a default si no encuentra Manrope.

    En macOS suelen estar SF Pro / Helvetica disponibles. En Linux Liberation.
    No usamos Manrope (la del site) porque el script corre en CI sin acceso
    a Google Fonts — el fallback a sans system queda decente para OG image."""
    candidates = {
        'bold':    ['/System/Library/Fonts/Helvetica.ttc',
                    '/System/Library/Fonts/HelveticaNeue.ttc',
                    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
                    '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf'],
        'regular': ['/System/Library/Fonts/Helvetica.ttc',
                    '/System/Library/Fonts/HelveticaNeue.ttc',
                    '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
                    '/usr/share/fonts/TTF/DejaVuSans.ttf'],
    }
    for p in candidates.get(weight, candidates['regular']):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    # último recurso: default bitmap font (peor calidad pero funciona)
    return ImageFont.load_default()


def main():
    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)

    # ─── Background gradient sutil (rectángulos translúcidos) ───
    # Banda diagonal violeta arriba-izquierda
    for i in range(80):
        alpha = int(40 * (1 - i / 80))
        overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        ovr_draw = ImageDraw.Draw(overlay)
        ovr_draw.rectangle([(0, i * 4), (W, i * 4 + 4)], fill=(*VIOLET, alpha))
        img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
        draw = ImageDraw.Draw(img)
        if i > 5: break  # solo unas pocas líneas para no recargar

    # ─── Logo dot (placeholder simple — círculo violet) ────────
    dot_x, dot_y, dot_r = 80, 80, 26
    draw.ellipse([dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r],
                 fill=VIOLET)
    # "R" en el centro del dot — pero más visualmente coherente sería el wordmark
    # Por simplicidad, dejamos solo el dot + texto "rendi" al lado

    # Wordmark
    f_brand = _load_font(48, 'bold')
    draw.text((dot_x + dot_r + 18, dot_y - 30), 'rendi',
              font=f_brand, fill=INK_0)

    # ─── Headline (centrado vertical, alineado izq) ─────────────
    f_title = _load_font(82, 'bold')
    f_sub = _load_font(34, 'regular')

    title_lines = [
        ('Tu portfolio multi-broker,', INK_0),
        ('con Coach IA.', VIOLET),
    ]
    y = 230
    for line, color in title_lines:
        draw.text((80, y), line, font=f_title, fill=color)
        y += 95

    # Subtitle — corto para que entre en una línea a 34px
    sub = 'Multi-broker · P&L real en USD blue · Coach IA con memoria'
    draw.text((80, y + 30), sub, font=f_sub, fill=INK_2)

    # ─── Footer right: dominio + tag ──────────────────────────
    f_domain = _load_font(28, 'bold')
    draw.text((80, H - 80), 'rendi.finance', font=f_domain, fill=INK_0)

    # Tagline derecha (planes)
    f_tag = _load_font(22, 'regular')
    tag = 'Free · Plus $4 · Pro $9 USD/mes'
    # medir ancho para alinear a la derecha
    bbox = draw.textbbox((0, 0), tag, font=f_tag)
    tw = bbox[2] - bbox[0]
    draw.text((W - 80 - tw, H - 72), tag, font=f_tag, fill=INK_2)

    # ─── Líneas decorativas (mock gráfico abajo a la derecha) ─
    # Pequeño chart-line ascendente que evoca el dashboard
    chart_x, chart_y, chart_w, chart_h = W - 380, 200, 280, 160
    # Sample data ascendente
    pts = [(0, 120), (40, 100), (80, 110), (120, 70), (160, 85), (200, 50), (240, 60), (280, 25)]
    pts = [(chart_x + x, chart_y + y) for (x, y) in pts]
    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i + 1]], fill=POS, width=3)
    # dot final
    last = pts[-1]
    draw.ellipse([last[0] - 6, last[1] - 6, last[0] + 6, last[1] + 6], fill=POS)
    # label "P&L"
    f_chart = _load_font(18, 'regular')
    draw.text((chart_x, chart_y + chart_h + 8), 'P&L USD · últimos 30d',
              font=f_chart, fill=INK_2)

    # ─── Guardar ───────────────────────────────────────────────
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, 'PNG', optimize=True)
    print(f'✓ OG image generada: {OUT}')
    print(f'   Tamaño: {W}x{H}')
    sz_kb = OUT.stat().st_size / 1024
    print(f'   Peso: {sz_kb:.1f} KB')


if __name__ == '__main__':
    main()
