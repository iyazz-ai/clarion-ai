import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  // A production build without an API URL would ship a site that tries to
  // talk to the visitor's own localhost. Fail the build instead.
  if (command === 'build' && !env.VITE_API_URL && !process.env.VITE_API_URL) {
    throw new Error(
      'VITE_API_URL is not set. Production builds need your backend URL, e.g.\n' +
        '  PowerShell:  $env:VITE_API_URL="https://api.example.com"; npm run build\n' +
        '  or put VITE_API_URL=... in frontend/.env.production'
    )
  }

  return { plugins: [react()] }
})
