export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Manrope', 'system-ui', 'sans-serif'],
      },
      colors: {
        rendi: {
          green: '#37FF68',
          'green-dark': '#25D957',
          aqua: '#10EFEC',
          pink: '#FF46F6',
          bg: '#0B0F0E',
          card: '#1E2624',
          muted: '#AAB3B0',
        },
      },
    },
  },
  plugins: [],
}
