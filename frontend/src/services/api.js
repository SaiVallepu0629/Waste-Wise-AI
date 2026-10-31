const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, '') ||
  (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '')

let accessToken = null
let unauthorizedHandler = null

export function setAccessToken(token) {
  accessToken = token
}

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler
}

async function getJson(path, options) {
  let response
  try {
    const headers = new Headers(options?.headers || {})
    if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
    response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers })
  } catch {
    throw new Error(
      'Could not connect to the WasteWise-AI API. Check your connection and API configuration, then try again.',
    )
  }

  if (!response.ok) {
    if (response.status === 401 && accessToken) unauthorizedHandler?.()
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      detail = Array.isArray(body.detail)
        ? body.detail.map((item) => item.msg).join(' ')
        : body.detail || detail
    } catch {
      // Keep the HTTP status message when the server does not return JSON.
    }
    throw new Error(detail)
  }

  if (response.status === 204) return null
  return response.json()
}

function jsonOptions(method, payload) {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }
}

export function registerUser(payload) {
  return getJson('/auth/register', jsonOptions('POST', payload))
}

export function loginUser(payload) {
  return getJson('/auth/login', jsonOptions('POST', payload))
}

export function logoutUser() {
  return getJson('/auth/logout', { method: 'POST' })
}

export function fetchCurrentUser() {
  return getJson('/auth/me')
}

export async function fetchInventoryItems({ limit = 25, offset = 0, search = '' } = {}) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (search.trim()) params.set('search', search.trim())
  return getJson(`/inventory/items?${params}`)
}

export async function createInventoryItem(payload) {
  return getJson('/inventory/items', jsonOptions('POST', payload))
}

export async function updateInventoryItem(itemId, payload) {
  return getJson(`/inventory/items/${itemId}`, jsonOptions('PUT', payload))
}

export async function deleteInventoryItem(itemId) {
  return getJson(`/inventory/items/${itemId}`, { method: 'DELETE' })
}

export async function fetchRuleBasedRecommendations() {
  return getJson('/inventory/recommendations')
}

export async function fetchDashboardData() {
  const [inventory, expiryRisk, recommendations, liveRecommendations] = await Promise.all([
    getJson('/inventory'),
    getJson('/expiry-risk'),
    getJson('/discount-recommendations'),
    fetchRuleBasedRecommendations(),
  ])

  return { inventory, expiryRisk, recommendations, liveRecommendations }
}

export async function fetchForecastSummary() {
  return getJson('/forecast/summary')
}

export async function fetchForecastProducts() {
  return getJson('/forecast/products')
}

export async function fetchProductForecast(productId) {
  return getJson(`/forecast/product/${encodeURIComponent(productId)}`)
}
