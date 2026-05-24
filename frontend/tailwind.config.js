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
// • Radii: solo rounded-sm (4) / rounded (6) / rounded-lg (8). Cero curvas grandes.
// • Sombras: dark mode = sin sombras. Elevación = borde + cambio de fondo.

export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        // Geist = sans-only para UI, headlines, números (con tabular-nums + ss01).
        // JetBrains Mono = solo para meta técnica (timestamps, kbd, labels uppercase).
        // CERO serif. El `display` queda apuntando a Geist para que componentes
        // viejos que usan `font-display` no se rompan visualmente — ya no es serif.
        sans:    ['Geist', 'system-ui', 'sans-serif'],
        display: ['Geist', 'system-ui', 'sans-serif'],
        mono:    ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      colors: {
        // ── Cold neutrals (9 pasos del ink al text-50) ─────────────────────
        bg: {
          0: '#07090C',  // ink — fondo de la app
          1: '#0E1218',  // charcoal — surface base (Panel default)
          2: '#141923',  // slate — surface elevada / hover
          3: '#1B2230',  // gunmetal — surface más elevada / active
        },
        ink: {
          0: '#E6EAF2',  // texto principal
          1: '#C3CAD8',  // texto secundario (default)
          2: '#9CA3B5',  // texto terciario, captions
          3: '#5A6478',  // disabled, hints
        },
        line: {
          DEFAULT: '#1B2230',  // bordes y dividers principales
          2: '#262E40',         // bordes elevados (modales, dropdowns)
          3: '#3A4256',         // bordes muy elevados (focus, selección)
        },

        // ── Semánticos — alineados con Brand Kit v1.0 ─────────────────────
        // Source of truth: public/brand-kit/tokens.css. Ver tokens.json para
        // mapping completo de los tokens del manual de marca.
        'rendi-pos':    '#21D07A',  // signal verde — positivo, ganancia
        'rendi-neg':    '#FF5360',  // red financiero sobrio — pérdida, error
        'rendi-warn':   '#E8B14A',  // amber — warnings (alias de --rendi-amber)
        'rendi-accent': '#5B9DF9',  // sky — información, benchmarks, links
                                    // (antes #4E83FF; alineado con Brand Kit v1.0)

        // ── Data accents (uso restringido) ────────────────────────────────
        // Solo para tipos de dato secundarios (benchmarks, info chips).
        // NUNCA como acento decorativo o de marca.
        'data-cyan':    '#46C6E0',  // aqua — sync, hints, neutro
        'data-blue':    '#5B9DF9',  // sky — info (alineado con --rendi-sky)
        'data-violet':  '#8B7DFF',  // marca · acción · botones primarios
        'data-amber':   '#E8B14A',  // warnings sobrios

        // ── Brand Kit v1.0 — tokens adicionales (variants violet + surfaces) ─
        // Estos NO existían antes; provienen del brand kit oficial.
        // Usar para nuevos componentes que necesiten estados o capas
        // específicas (hover violet, charcoal panel, etc.). Code legacy
        // sigue usando los tokens viejos (bg-1, bg-2, line — sin cambios).
        'rendi-violet-hover': '#6E5FF0',  // :hover de botones violet
        'rendi-violet-deep':  '#1E1840',  // background tintado profundo
        'rendi-charcoal':     '#0D1015',  // paneles (alternativa a bg-1)
        'rendi-slate':        '#141923',  // cards elevadas
        'rendi-sky':          '#5B9DF9',  // alias semántico de rendi-accent

        // ── Polarity scales (9 pasos cada uno — heatmaps + backgrounds tonales)
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
          green: '#21D07A',
          'green-dark': '#14A560',
          aqua: '#46C6E0',
          pink: '#FF5360',
          bg: '#07090C',
          card: '#0E1218',
          muted: '#9CA3B5',
        },
      },
      borderRadius: {
        // Solo 3 pasos. Nada de 12/20/24px.
        sm: '4px',    // badges, chips, inputs, controles chicos
        DEFAULT: '6px',   // cards, modales chicos, dropdowns (v2: 6, no 10)
        lg: '8px',    // modales grandes, hero containers (v2: 8, no 16)
      },
      letterSpacing: {
        // Para labels uppercase mono — el "specimen sheet" look
        'label': '0.12em',  // v2: más compacto (0.12, no 0.18)
        'caps': '0.08em',
      },
    },
  },
  plugins: [],
}
