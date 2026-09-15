// Picks VITE_BACKEND_URL by branch during Cloudflare Workers Builds, so preview
// deployments (any non-main branch) talk to the staging backend while production
// (main) talks to the live backend. Vite bakes VITE_BACKEND_URL at build time, so
// the choice has to be made here, before `vite build` runs.
//
// It writes .env.production.local, which Vite loads at a higher priority than the
// committed .env.production, and which .gitignore already excludes via `*.local`.
//
// Local `bun run build` is intentionally left untouched: with no Cloudflare branch
// env present we do nothing, so the committed .env.production (production URL)
// applies exactly as before.
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const PROD = 'https://api.live-faktencheck.de'
const STAGING = 'https://staging-api.live-faktencheck.de'

// Workers Builds sets WORKERS_CI_BRANCH; CF_PAGES_BRANCH is the Pages equivalent, kept
// as a fallback in case the frontend ever moves back to Pages.
const branch = process.env.WORKERS_CI_BRANCH || process.env.CF_PAGES_BRANCH || ''
const inCloudflareCI = Boolean(process.env.WORKERS_CI || process.env.CF_PAGES || branch)

if (!inCloudflareCI) {
  console.log('[resolve-backend-url] not a Cloudflare build — keeping committed .env.production')
  process.exit(0)
}

// An explicit VITE_BACKEND_URL in the build environment always wins — a dashboard escape hatch.
const url = process.env.VITE_BACKEND_URL || (branch === 'main' ? PROD : STAGING)

const target = join(dirname(fileURLToPath(import.meta.url)), '..', '.env.production.local')
writeFileSync(target, `VITE_BACKEND_URL=${url}\n`)
console.log(`[resolve-backend-url] branch="${branch}" -> VITE_BACKEND_URL=${url}`)
