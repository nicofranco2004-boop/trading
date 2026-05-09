// Sistema de design tokens — Rendi
// ═══════════════════════════════════════════════════════════════════════════
// Basado en la auditoría visual de mayo 2026. La idea: un sistema cálido,
// editorial y semánticamente estricto. Nada de azules ni verde decorativo.
//
// Reglas:
// • Verde (rendi-pos) SOLO aparece en cifras positivas o CTAs principales.
//   Nunca en logo permanente, nav decorativo, badges genéricos.
// • Rojo (rendi-neg) SOLO en pérdidas reales.
// • Ámbar (rendi-warn) SOLO para alertas accionables.
// • Indigo (rendi-accent) para selección, links, identificadores.
// • Spacing: solo 4·8·12·16·24·32·48·64·96·128. Nada ad-hoc.
// • Radii: solo rounded-sm (4) / rounded (10) / rounded-lg (16).
// • Sombras: en dark mode no se usan. Elevación = borde + cambio de fondo.

export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        // Display = Instrument Serif (italic en hero, regular en headings)
        // Sans   = Manrope (UI body, headings, data hero tabular)
        // Mono   = JetBrains Mono (labels uppercase, metadata, data secundaria)
        display: ['Instrument Serif', 'Georgia', 'serif'],
        sans: ['Manrope', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      colors: {
        // ── Tokens nuevos (audit) ──────────────────────────────────────────
        // Neutrales cálidos, no navy. 8 pasos del fondo al texto.
        bg: {
          0: '#0A0B0E',  // fondo app
          1: '#101218',  // surface, cards
          2: '#161922',  // surface elevada / hover
          3: '#1D2130',  // surface más elevada / active
        },
        ink: {
          0: '#F4F4F0',  // texto principal (off-white, casi papel)
          1: '#CFD0C8',  // texto secundario
          2: '#8B8D8A',  // texto terciario, captions
          3: '#5A5C5B',  // texto deshabilitado, hints
        },
        line: {
          DEFAULT: '#222636',  // bordes y dividers principales
          2: '#2C3142',         // bordes elevados (modales, dropdowns)
        },
        // Semánticos — solo 4. Cualquier otro color es ruido.
        'rendi-pos':    '#6FE3A3',  // ganancia (refinado, menos neón que el verde original)
        'rendi-neg':    '#F17A7A',  // pérdida
        'rendi-warn':   '#E9B876',  // alertas accionables (sync pendiente, datos faltantes)
        'rendi-accent': '#7D8CFF',  // selección, links, identificadores

        // ── Aliases legacy (mantenidos para no romper componentes en uso) ──
        // Migrar progresivamente a los tokens nuevos.
        rendi: {
          green: '#6FE3A3',         // alias → rendi-pos (compatibilidad)
          'green-dark': '#5DC68A',  // hover de rendi-pos
          aqua: '#7D8CFF',          // alias → rendi-accent
          pink: '#F17A7A',          // alias → rendi-neg
          bg: '#0A0B0E',            // alias → bg-0
          card: '#101218',          // alias → bg-1
          muted: '#8B8D8A',         // alias → ink-2
        },
      },
      borderRadius: {
        // Solo 3 pasos. Nada de 12/20/24px.
        sm: '4px',    // badges, chips, inputs, controles chicos
        DEFAULT: '10px',  // cards, modales chicos, dropdowns
        lg: '16px',   // modales grandes, hero containers
      },
      letterSpacing: {
        // Para labels uppercase mono — el "specimen sheet" look
        'label': '0.18em',
        'caps': '0.12em',
      },
    },
  },
  plugins: [],
}
