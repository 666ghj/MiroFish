/**
 * Marketing waitlist (mirofish.ai). Requires VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY at build time.
 * UI should map WAITLIST_SERVICE_UNAVAILABLE to i18n — never render result.error as raw HTML.
 */

export const WAITLIST_SERVICE_UNAVAILABLE = 'service_unavailable'

function getSupabaseConfig() {
  const url = import.meta.env.VITE_SUPABASE_URL?.trim()
  const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY?.trim()
  if (!url || !anonKey) {
    return null
  }
  return { url, anonKey }
}

export function sanitizeWaitlistApiError(body, status) {
  if (!body) {
    return status ? `HTTP ${status}` : WAITLIST_SERVICE_UNAVAILABLE
  }
  const trimmed = body.trim()
  if (/^<!doctype html/i.test(trimmed) || /^<html/i.test(trimmed) || trimmed.length > 240) {
    return WAITLIST_SERVICE_UNAVAILABLE
  }
  return trimmed
}

function supabaseAuthHeaders(anonKey) {
  return {
    'Content-Type': 'application/json',
    apikey: anonKey,
    Authorization: `Bearer ${anonKey}`
  }
}

async function verifyWaitlistEmail(email, config) {
  try {
    const response = await fetch(`${config.url}/functions/v1/verify-email`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${config.anonKey}`
      },
      body: JSON.stringify({ email })
    })
    if (!response.ok && response.status === 429) {
      return { valid: false, error: 'rate_limited' }
    }
    if (response.ok) {
      return await response.json()
    }
    return { valid: true }
  } catch {
    return { valid: true }
  }
}

async function registerWaitlistEmail(email, source, config) {
  const response = await fetch(`${config.url}/rest/v1/waitlist_emails`, {
    method: 'POST',
    headers: {
      ...supabaseAuthHeaders(config.anonKey),
      Prefer: 'return=minimal'
    },
    body: JSON.stringify({ email, source })
  })

  if (response.status === 201) {
    return { success: true }
  }
  if (response.status === 409) {
    return { success: false, duplicate: true }
  }

  const body = await response.text()
  if (body.includes('duplicate') || body.includes('unique')) {
    return { success: false, duplicate: true }
  }

  return {
    success: false,
    error: sanitizeWaitlistApiError(body, response.status)
  }
}

export async function submitWaitlist(email, source = 'unknown') {
  const config = getSupabaseConfig()
  if (!config) {
    return { success: false, error: WAITLIST_SERVICE_UNAVAILABLE }
  }

  const normalized = email.trim().toLowerCase()

  try {
    const verification = await verifyWaitlistEmail(normalized, config)
    if (!verification.valid) {
      if (verification.error === 'rate_limited') {
        return { success: false, error: 'rate_limited' }
      }
      return { success: false, error: 'invalid_email_domain' }
    }
    return await registerWaitlistEmail(normalized, source, config)
  } catch (err) {
    return { success: false, error: err?.message || 'network_error' }
  }
}
