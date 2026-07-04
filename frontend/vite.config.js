import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8010'
    }
  },
  build: {
    // Code-split por librería pesada para mejorar tiempo de carga inicial.
    // Recharts pesa ~150KB gzipped, lucide-react ~30KB. Separarlos del bundle
    // principal permite que Home carga sin Recharts (lo necesita Dashboard /
    // Insights / Reportes que son lazy igual via React.lazy si quisiéramos).
    rollupOptions: {
      output: {
        manualChunks: {
          recharts: ['recharts'],
          lucide: ['lucide-react'],
          react: ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
    // Subimos el warning límit (recharts solo ya es ~500KB sin gzip).
    chunkSizeWarningLimit: 700,
  },
  test: {
    environment: 'node',
  },
})
