/**
 * API service for backend communication
 */

// Backend URL - based on environment
export const getBackendUrl = () => {
  if (import.meta.env.PROD) {
    return import.meta.env.VITE_BACKEND_URL || 'http://localhost:5000'
  }
  return 'http://localhost:5000'
}

export const BACKEND_URL = getBackendUrl()

// N8N Webhook URL for verified claims
export const N8N_VERIFIED_WEBHOOK = import.meta.env.VITE_N8N_WEBHOOK_URL || "http://localhost:5678/webhook/verified-claims"

// Debug logging - only active in development
export const debug = {
  log: (...args) => { if (import.meta.env.DEV) console.log(...args) },
  warn: (...args) => { if (import.meta.env.DEV) console.warn(...args) },
  error: (...args) => { if (import.meta.env.DEV) console.error(...args) }
}

// Helper: Create fetch headers
export const getFetchHeaders = () => ({
  'Accept': 'application/json',
  'Content-Type': 'application/json'
})

// Helper: Check if response is JSON (not HTML)
export const isJsonResponse = (response) => {
  const contentType = response.headers.get('content-type')
  return contentType && contentType.includes('application/json')
}

// Helper: Safe JSON parsing with error handling
export const safeJsonParse = async (response, errorContext = '') => {
  if (!isJsonResponse(response)) {
    const text = await response.text()
    if (text.trim().startsWith('<!DOCTYPE') || text.includes('<html')) {
      debug.error(`${errorContext}: Backend responds with HTML instead of JSON`)
      debug.error(`   URL: ${response.url}`)
      debug.error(`   Status: ${response.status}`)
      debug.error(`   Response (first 200 chars): ${text.substring(0, 200)}`)
      throw new Error('Backend responds with HTML instead of JSON. Check if backend is running.')
    }
  }
  try {
    return await response.json()
  } catch (error) {
    debug.error(`${errorContext}: Error parsing JSON response`)
    debug.error(`   URL: ${response.url}`)
    debug.error(`   Error: ${error.message}`)
    throw error
  }
}
