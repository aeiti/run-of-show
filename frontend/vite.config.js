import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // 3200 K, tungsten: the board is the stage. The API is on 5600 (daylight).
  server: { port: 3200, strictPort: true },
})
