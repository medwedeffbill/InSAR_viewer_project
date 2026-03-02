import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': '/src',
    },
  },
  // Allow zarr and geotiff to work in browser
  optimizeDeps: {
    include: ['zarr', 'geotiff'],
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          maplibre: ['maplibre-gl'],
          charts:   ['recharts'],
          zarr:     ['zarr'],
        },
      },
    },
  },
})
