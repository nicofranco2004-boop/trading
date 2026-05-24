"""generate-favicons — genera todos los favicons desde brand/rendi-mark.png.
═══════════════════════════════════════════════════════════════════════════
Output (todos en /public/):
  - favicon.ico              ICO multi-tamaño embedded (browsers viejos + Windows)
  - favicon-16x16.png        tab del browser, tamaño chico
  - favicon-32x32.png        tab del browser, retina
  - apple-touch-icon.png     180×180 para iOS home screen
  - android-chrome-192.png   192×192 para Android home screen
  - android-chrome-512.png   512×512 para PWA splash

Source: public/brand/rendi-mark.png (1254×1254 PNG con el ícono violeta oficial).
Re-correr cada vez que cambie el branding.

Nota: NO generamos favicon.svg porque el SVG legacy en brand/rendi-icon.svg
era el verde fluo deprecated. El branding actual es violeta (rendi-mark.png).
Cuando exista un SVG vectorial violeta, agregar aquí la copia + el link en
index.html.

Uso: python3 frontend/scripts/generate-favicons.py
"""
from pathlib import Path
from PIL import Image

PUBLIC = Path(__file__).parent.parent / 'public'
SOURCE_PNG = PUBLIC / 'brand' / 'rendi-mark.png'

# Tamaños a generar (estándar de la industria 2026)
SIZES = {
    'favicon-16x16.png':       16,
    'favicon-32x32.png':       32,
    'apple-touch-icon.png':    180,
    'android-chrome-192.png':  192,
    'android-chrome-512.png':  512,
}


def main():
    if not SOURCE_PNG.exists():
        print(f"✗ No se encontró {SOURCE_PNG}")
        return

    # Generar PNGs en varios tamaños desde rendi-mark.png (R violeta oficial).
    src = Image.open(SOURCE_PNG).convert('RGBA')
    print(f"  source: {SOURCE_PNG.name} ({src.width}×{src.height})")

    for filename, size in SIZES.items():
        out_path = PUBLIC / filename
        # LANCZOS para downscale de alta calidad
        resized = src.resize((size, size), Image.LANCZOS)
        resized.save(out_path, 'PNG', optimize=True)
        sz_kb = out_path.stat().st_size / 1024
        print(f"✓ {filename} ({size}×{size}, {sz_kb:.1f} KB)")

    # 3. favicon.ico — multi-size embedded para browsers viejos + Windows tiles
    ico_sizes = [(16, 16), (32, 32), (48, 48)]
    ico_imgs = [src.resize(s, Image.LANCZOS) for s in ico_sizes]
    ico_path = PUBLIC / 'favicon.ico'
    ico_imgs[0].save(
        ico_path,
        format='ICO',
        sizes=ico_sizes,
        append_images=ico_imgs[1:],
    )
    sz_kb = ico_path.stat().st_size / 1024
    print(f"✓ favicon.ico (multi-size 16/32/48, {sz_kb:.1f} KB)")

    print("\n✓ Listo. Próximo paso: update index.html con los links + cache bust.")


if __name__ == '__main__':
    main()
