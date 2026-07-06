import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'

// Identidad del build. En prod: el SHA del commit (Vercel lo inyecta como
// VERCEL_GIT_COMMIT_SHA) o un timestamp de respaldo. En dev: 'dev', que
// deshabilita el auto-update (no queremos recargas en desarrollo). Se inyecta
// en el bundle como __BUILD_ID__ (lo que "corro") y se escribe en
// dist/version.json (lo "último publicado") para que el cliente los compare.
function resolveBuildId(mode) {
  if (mode !== 'production') return 'dev'
  return (
    process.env.VERCEL_GIT_COMMIT_SHA ||
    process.env.COMMIT_REF ||
    String(Date.now())
  )
}

export default defineConfig(({ mode }) => {
  const buildId = resolveBuildId(mode)
  return {
    plugins: [
      react(),
      {
        // Emite dist/version.json = { version: <buildId> } al final del build.
        // Es la "última versión publicada" que el cliente pollea (no-store).
        name: 'rendi-emit-version-json',
        apply: 'build',
        writeBundle(options) {
          try {
            const dir = options.dir || 'dist'
            fs.writeFileSync(
              path.join(dir, 'version.json'),
              JSON.stringify({ version: buildId }),
            )
          } catch (e) {
            this.warn(`No pude escribir version.json: ${e.message}`)
          }
        },
      },
    ],
    define: {
      __BUILD_ID__: JSON.stringify(buildId),
    },
    server: {
      proxy: {
        '/api': 'http://localhost:8000',
      },
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
  }
})
