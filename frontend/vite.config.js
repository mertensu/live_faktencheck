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
const backendUrl = env.VITE_BACKEND_URL || (isProduction ? PROD_BACKEND : STAGING_BACKEND)

// Written into the built output so the choice (and the CI env that drove it) can be
// inspected on the deployed preview via /_preview-info.json.
const previewInfo = {
  backendUrl,
  isProduction,
  inCI,
  ciBranch,
  gitBranch,
  builtAt: new Date().toISOString(),
  ciEnvKeys: Object.keys(env)
    .filter((k) => /CI|BRANCH|WORKER|CF_|PAGES|COMMIT|DEPLOY|GITHUB/i.test(k))
    .sort(),
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
  define: {
    'import.meta.env.VITE_BACKEND_URL': JSON.stringify(backendUrl),
  },
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
