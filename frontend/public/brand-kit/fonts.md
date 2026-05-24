# Tipografías · Rendi

Rendi usa dos familias tipográficas. Ambas son **gratuitas** y de código abierto.

## Geist (primaria · 95% del uso)

Diseñada por Vercel. Se usa para todo lo que se lee: titulares, párrafos, UI, números grandes.

**Google Fonts** (más rápido):
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&display=swap" rel="stylesheet">
```

**CSS**:
```css
font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
```

**Descarga directa**: https://vercel.com/font

---

## JetBrains Mono (secundaria · 5% del uso)

Solo para datos técnicos: tickers, timestamps, etiquetas MAYÚSCULA, atajos de teclado, columnas de números en tablas.

**Google Fonts**:
```html
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```

**CSS**:
```css
font-family: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
```

**Descarga directa**: https://www.jetbrains.com/lp/mono/

---

## Setup completo en una línea

Para tu proyecto, copiá esto en el `<head>`:

```html
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```

## Reglas de uso

- Geist 500 (medium) para titulares y números importantes
- Geist 400 (regular) para cuerpos
- JetBrains Mono solo para datos técnicos · `letter-spacing: 0.04em`
- Activá `font-feature-settings: 'tnum'` en TODOS los números
- Cero serif, cero italic
