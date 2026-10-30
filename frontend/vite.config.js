import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // 3200 K, tungsten: the board is the stage. The API is on 5600 (daylight).
  // LAN_HOSTS (comma-separated) are names this machine is reached by on the
  // network; Vite refuses other host names (IP addresses are always allowed).
  server: {
    port: 3200,
    strictPort: true,
    allowedHosts: (process.env.LAN_HOSTS ?? '')
      .split(',')
      .map((h) => h.trim())
      .filter(Boolean),
  },
})
