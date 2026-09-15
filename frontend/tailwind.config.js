// Sistema de design tokens — Rendi V2
// ═══════════════════════════════════════════════════════════════════════════
// Pivote de mayo 2026: de editorial cálido → operativo financiero.
// Linear × Vercel × Stripe (cold neutrals, accents quirúrgicos, sin serif).
// La identidad del PRODUCTO no cambia (no operás, no real-time obsession).
// Solo el sistema visual.
//
// Reglas:
// • Verde signal (rendi-pos #21D07A) solo en cifras positivas o estados live.
// • Rojo financiero (rendi-neg #FF5360) solo en pérdidas reales — no naranja.
// • Cyan / Blue / Violet / Amber: solo como tipos de dato secundarios. Nunca
//   como acento decorativo.
// • Spacing system: solo 4·8·12·16·24·32·48·64·96·128.
// • Radii: la escala está DECLARADA COMPLETA abajo, en px. xl (12) es el radio de
//   superficie de la generación nueva — lo usa el átomo Panel y todo el Plan Asesor.
//   Radios arbitrarios rounded-[Npx] prohibidos: si falta un paso, se agrega acá.
// • Sombras: dark mode = sin sombras. Elevación = borde + cambio de fondo.

export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        // Geist = sans-only para UI, headlines, números (con tabular-nums + ss01).
        // JetBrains Mono = SOLO meta técnica literal: bloques de código, atajos de
        // teclado, glifos de ancho fijo, IDs/ordinales del importador y códigos de
        // activo o moneda. NUNCA números del producto (van en Geist + tabular) ni
        // rótulos (van en sans sentence-case). Ver frontend/CLAUDE.md, R1-R3.
        // CERO serif. El `display` queda apuntando a Geist para que componentes
        // viejos que usan `font-display` no se rompan visualmente — ya no es serif.
        sans:    ['Geist', 'system-ui', 'sans-serif'],
        display: ['Geist', 'system-ui', 'sans-serif'],
        mono:    ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      colors: {
        // ── TODO LO QUE CAMBIA ENTRE TEMAS VIVE EN src/index.css ──────────
        // Estos 33 tokens eran hex literales hasta F0 (2026-09-15). Ahora
        // apuntan a variables CSS y el tema las redefine: `:root` claro,
        // `.dark` oscuro. Los VALORES están en index.css, no acá — este
        // archivo sólo dice "andá a buscarlo a la variable".
        //
        // `rgb(var(--x) / <alpha-value>)` NO es adorno: es lo único que
        // deja funcionar los 1.937 usos con opacidad (`bg-bg-2/40`). Con un
        // hex adentro de la variable, ese `/40` se descarta EN SILENCIO.
        // Ver el comentario largo en index.css antes de tocar esto.
        //
        // ── Cold neutrals (superficie · tinta · línea) ─────────────────────
        bg: {
          0: 'rgb(var(--bg-0) / <alpha-value>)',  // ink — fondo de la app
          1: 'rgb(var(--bg-1) / <alpha-value>)',  // charcoal — surface base (Panel default)
          2: 'rgb(var(--bg-2) / <alpha-value>)',  // slate — surface elevada / hover
          3: 'rgb(var(--bg-3) / <alpha-value>)',  // gunmetal — surface más elevada / active
        },
        ink: {
          0: 'rgb(var(--ink-0) / <alpha-value>)',  // texto principal
          1: 'rgb(var(--ink-1) / <alpha-value>)',  // texto secundario (default)
          2: 'rgb(var(--ink-2) / <alpha-value>)',  // texto terciario, captions
          3: 'rgb(var(--ink-3) / <alpha-value>)',  // disabled, hints
        },
        line: {
          DEFAULT: 'rgb(var(--line) / <alpha-value>)',    // bordes y dividers principales
          2: 'rgb(var(--line-2) / <alpha-value>)',        // bordes elevados (modales, dropdowns)
          3: 'rgb(var(--line-3) / <alpha-value>)',        // bordes muy elevados (focus, selección)
        },

        // ── Semánticos — alineados con Brand Kit v1.0 ─────────────────────
        // Source of truth de los valores: src/index.css. El brand kit
        // (public/brand-kit/tokens.css) documenta la versión oscura.
        'rendi-pos':    'rgb(var(--rendi-pos) / <alpha-value>)',     // signal verde — positivo, ganancia
        'rendi-neg':    'rgb(var(--rendi-neg) / <alpha-value>)',     // red financiero sobrio — pérdida, error
        'rendi-warn':   'rgb(var(--rendi-warn) / <alpha-value>)',    // amber — warnings
        'rendi-accent': 'rgb(var(--rendi-accent) / <alpha-value>)',  // sky — información, benchmarks, links

        // ── El verde y el rojo se parten en dos trabajos (F0) ─────────────
        // En oscuro un solo verde alcanzaba para el número Y para la barra
        // del gráfico. Sobre blanco no: el verde vivo como TEXTO da 2,03:1
        // (ilegible), pero como RELLENO de un área grande está perfecto.
        // Por eso son dos tokens. En oscuro valen lo mismo — la diferencia
        // sólo aparece en claro.
        //   -pos / -neg        → números, flechas, texto. Legibles (AA).
        //   -pos-fill / -neg-fill → barras, áreas, celdas de heatmap.
        'rendi-pos-fill': 'rgb(var(--rendi-pos-fill) / <alpha-value>)',
        'rendi-neg-fill': 'rgb(var(--rendi-neg-fill) / <alpha-value>)',

        // ── Data accents (uso restringido) ────────────────────────────────
        // Solo para tipos de dato secundarios (benchmarks, info chips).
        // NUNCA como acento decorativo o de marca.
        'data-cyan':    'rgb(var(--data-cyan) / <alpha-value>)',    // aqua — sync, hints, neutro
        'data-blue':    'rgb(var(--data-blue) / <alpha-value>)',    // sky — info
        'data-violet':  'rgb(var(--data-violet) / <alpha-value>)',  // marca · acción · botones primarios
        'data-amber':   'rgb(var(--data-amber) / <alpha-value>)',   // warnings sobrios

        // ── Brand Kit v1.0 — tokens adicionales (variants violet + surfaces) ─
        'rendi-violet-hover': 'rgb(var(--rendi-violet-hover) / <alpha-value>)',  // :hover de botones violet
        'rendi-violet-deep':  'rgb(var(--rendi-violet-deep) / <alpha-value>)',   // background tintado (profundo en dark, suave en light)
        'rendi-charcoal':     'rgb(var(--rendi-charcoal) / <alpha-value>)',      // paneles (alternativa a bg-1)
        'rendi-slate':        'rgb(var(--rendi-slate) / <alpha-value>)',         // cards elevadas
        'rendi-sky':          'rgb(var(--rendi-sky) / <alpha-value>)',           // alias semántico de rendi-accent

        // ── Polarity scales (9 pasos cada uno — heatmaps + backgrounds tonales)
        // NO son variables a propósito: son rampas de heatmap, y una rampa no
        // se arregla cambiándole los valores — hay que RECORRERLA AL REVÉS.
        // En oscuro, intenso = brillante (arranca casi negra). En claro,
        // intenso = oscuro y saturado (arranca casi blanca). Eso es F2.
        green: {
          50:  '#CFF7DF',
          100: '#9CEDC0',
          200: '#5FE19D',
          300: '#21D07A',  // = rendi-pos
          400: '#14A560',
          500: '#0F5C36',
          600: '#0B4127',
          700: '#072A18',
          800: '#06160E',
        },
        red: {
          50:  '#FFDADD',
          100: '#FFB4BA',
          200: '#FF8A93',
          300: '#FF5360',  // = rendi-neg
          400: '#C8333E',
          500: '#8E2B33',
          600: '#5E1F25',
          700: '#3E1418',
          800: '#1F0A0C',
        },

        // ── Aliases legacy (mantenidos para compatibilidad con componentes
        // que importan `rendi.X` directo). Migrar progresivamente.
        rendi: {
          green: 'rgb(var(--rendi-green) / <alpha-value>)',
          'green-dark': 'rgb(var(--rendi-green-dark) / <alpha-value>)',
          aqua: 'rgb(var(--rendi-aqua) / <alpha-value>)',
          pink: 'rgb(var(--rendi-pink) / <alpha-value>)',
          bg: 'rgb(var(--rendi-bg) / <alpha-value>)',
          card: 'rgb(var(--rendi-card) / <alpha-value>)',
          muted: 'rgb(var(--rendi-muted) / <alpha-value>)',
        },
      },
      borderRadius: {
        // Escala COMPLETA y en px. Antes acá vivían 3 pasos con el comentario
        // "Solo 3 pasos. Nada de 12/20/24px." — pero esto está bajo `extend`, que
        // NO reemplaza la escala default de Tailwind: md/xl/2xl/3xl/full seguían
        // alcanzables y el código los usaba (478 usos fuera de los 3 pasos,
        // empezando por el propio Panel.jsx, que es rounded-xl desde el clean pass).
        // O sea: la escala declarada y la escala real llevaban meses en desacuerdo.
        // Se declara la real. Los valores son idénticos a los defaults de
        // tailwindcss 3.4.19 convertidos a px con root 16px → cambio visual CERO.
        xs: '2px',        // swatches de leyenda (2×3px). Antes eran rounded-[2px].
        sm: '4px',        // badges, chips, inputs, controles chicos
        DEFAULT: '6px',   // cards chicas, dropdowns
        md: '6px',        // DEPRECADO: alias de DEFAULT (0.375rem = 6px, idéntico).
                          // No usar en código nuevo; los 307 usos existentes son deuda
                          // pixel-invisible que se migra a `rounded` cuando se toque el archivo.
        lg: '8px',        // modales grandes, hero containers
        xl: '12px',       // ★ superficie de la generación nueva: Panel, cards del asesor
        '2xl': '16px',    // sheets mobile (rounded-t-2xl) y poco más
        '3xl': '24px',    // sólo halos decorativos de la landing
        full: '9999px',   // dots, avatares, pills redondas
      },
      letterSpacing: {
        // Tracking para rótulos en MAYÚSCULA. La mayúscula NO está prohibida (el
        // Plan Asesor la usa); lo prohibido es la mayúscula EN MONO. Ver R2.
        'label': '0.12em',  // v2: más compacto (0.12, no 0.18)
        'caps': '0.08em',
      },
    },
  },
  plugins: [],
}
