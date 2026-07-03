import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react()],
  build: {
    // Output to the parent dashboard dir so FastAPI serves it directly
    outDir: path.resolve(__dirname, '..'),
    emptyOutDir: false, // Don't wipe react-src itself
    rollupOptions: {
      output: {
        // Flatten asset names so FastAPI static mount works
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/ws': {
        target: 'ws://localhost:8765',
        ws: true,
      },
      '/static': 'http://localhost:8765',
    },
  },
  base: '/',
})
