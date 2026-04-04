/**
 * API service for backend communication
 */

export const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:5000'

// N8N Webhook URL for verified claims
export const N8N_VERIFIED_WEBHOOK = import.meta.env.VITE_N8N_WEBHOOK_URL || "http://localhost:5678/webhook/verified-claims"

// Static mode: production build not running on localhost
const isLocalhost = window.location.hostname === 'localhost' ||
  window.location.hostname === '127.0.0.1' ||
  window.location.hostname.startsWith('192.168.')
export const isStaticMode = import.meta.env.PROD && !isLocalhost

// Debug logging - only active in development
export const debug = {
  log: (...args) => { if (import.meta.env.DEV) console.log(...args) },
  warn: (...args) => { if (import.meta.env.DEV) console.warn(...args) },
  error: (...args) => { if (import.meta.env.DEV) console.error(...args) }
}

export const FETCH_HEADERS = {
  'Accept': 'application/json',
  'Content-Type': 'application/json'
}

const isJsonResponse = (response) => {
  const contentType = response.headers.get('content-type')
  return contentType && contentType.includes('application/json')
}

// Helper: Safe JSON parsing with error handling
export const safeJsonParse = async (response, errorContext = '') => {
  const text = await response.text()
  if (!isJsonResponse(response) && (text.trim().startsWith('<!DOCTYPE') || text.includes('<html'))) {
    debug.error(`${errorContext}: Backend responds with HTML instead of JSON`)
    debug.error(`   URL: ${response.url}`)
    debug.error(`   Status: ${response.status}`)
    debug.error(`   Response (first 200 chars): ${text.substring(0, 200)}`)
    throw new Error('Backend responds with HTML instead of JSON. Check if backend is running.')
  }
  try {
    return JSON.parse(text)
  } catch (error) {
    debug.error(`${errorContext}: Error parsing JSON response`)
    debug.error(`   URL: ${response.url}`)
    debug.error(`   Error: ${error.message}`)
    throw error
  }
}
