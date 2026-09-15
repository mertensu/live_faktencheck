import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { execSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

// --- Preview backend switch -------------------------------------------------
// Vite bakes the backend URL at build time. On Cloudflare, non-`main` branches are
// preview deployments and must talk to the staging backend; `main` is production.
// This lives in vite.config.js (not a wrapper npm script) so it runs on every
// `vite build`, whatever build command Cloudflare is configured with.
const PROD_BACKEND = 'https://api.live-faktencheck.de'
const STAGING_BACKEND = 'https://staging-api.live-faktencheck.de'

const env = process.env
const ciBranch =
  env.WORKERS_CI_BRANCH || env.CF_PAGES_BRANCH || env.BRANCH ||
  env.GITHUB_HEAD_REF || env.GITHUB_REF_NAME || ''

let gitBranch = ''
try { gitBranch = execSync('git rev-parse --abbrev-ref HEAD').toString().trim() } catch { /* not a git checkout */ }

// Only switch to staging when we can see we're on a CI preview build; a local
// `bun run build` (no CI signal) stays on production, as before.
const inCI = Boolean(env.WORKERS_CI || env.CF_PAGES || env.CI || ciBranch)
const branch = ciBranch || gitBranch
const isProduction = !inCI || branch === 'main' || branch === 'HEAD' || branch === ''
// Compute purely from the branch — do NOT honour an incoming VITE_BACKEND_URL. Cloudflare
// injects a VITE_BACKEND_URL build variable (= production), and in Vite a real process.env
// VITE_* var outranks .env files, so honouring it forced every preview onto production.
const backendUrl = isProduction ? PROD_BACKEND : STAGING_BACKEND
// Overwrite the env var Vite will read, so our choice wins over that build variable.
process.env.VITE_BACKEND_URL = backendUrl

// Written into the built output so the resolved choice can be inspected on any
// deployed build via /_preview-info.json — a small build-provenance marker.
const previewInfo = {
  backendUrl,
  isProduction,
  inCI,
  ciBranch,
  builtAt: new Date().toISOString(),
}

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'preview-info',
      closeBundle() {
        try {
          writeFileSync(resolve(__dirname, 'dist/_preview-info.json'), JSON.stringify(previewInfo, null, 2))
        } catch { /* best effort */ }
      },
    },
  ],
  base: '/',
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  }
})
