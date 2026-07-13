import { computed, reactive } from 'vue'

export type UserRole = 'admin' | 'hr' | 'manager'
export type CurrentUser = {
  id: number
  username: string
  email: string
  display_name: string
  role: UserRole
  department_id: number | null
}

type TokenPair = {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
}

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
const ACCESS_KEY = 'talenthub.access_token'
const REFRESH_KEY = 'talenthub.refresh_token'

const state = reactive({
  accessToken: sessionStorage.getItem(ACCESS_KEY),
  refreshToken: sessionStorage.getItem(REFRESH_KEY),
  user: null as CurrentUser | null,
  initialized: false,
})

let refreshPromise: Promise<string> | null = null

async function authFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, init)
  } catch {
    throw new Error('無法連線至後端 API')
  }
  if (!response.ok) {
    let detail = response.statusText || '請求失敗'
    try {
      const body = await response.json() as { detail?: string }
      if (body.detail) detail = body.detail
    } catch { /* non-JSON error */ }
    throw new Error(`${response.status}：${detail}`)
  }
  return await response.json() as T
}

function storeTokens(tokens: TokenPair) {
  state.accessToken = tokens.access_token
  state.refreshToken = tokens.refresh_token
  sessionStorage.setItem(ACCESS_KEY, tokens.access_token)
  sessionStorage.setItem(REFRESH_KEY, tokens.refresh_token)
}

function clear() {
  state.accessToken = null
  state.refreshToken = null
  state.user = null
  sessionStorage.removeItem(ACCESS_KEY)
  sessionStorage.removeItem(REFRESH_KEY)
}

async function loadCurrentUser(): Promise<CurrentUser> {
  if (!state.accessToken) throw new Error('尚未登入')
  const user = await authFetch<CurrentUser>('/auth/me', {
    headers: { Authorization: `Bearer ${state.accessToken}` },
  })
  state.user = user
  return user
}

async function refreshAccess(failedAccessToken?: string | null): Promise<string> {
  if (failedAccessToken && state.accessToken && failedAccessToken !== state.accessToken) {
    return state.accessToken
  }
  if (refreshPromise) return refreshPromise
  if (!state.refreshToken) {
    clear()
    throw new Error('登入已過期，請重新登入')
  }
  refreshPromise = (async () => {
    try {
      const tokens = await authFetch<TokenPair>('/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: state.refreshToken }),
      })
      storeTokens(tokens)
      return tokens.access_token
    } catch (error) {
      clear()
      throw error
    } finally {
      refreshPromise = null
    }
  })()
  return refreshPromise
}

async function initialize() {
  if (state.initialized) return
  try {
    if (state.accessToken) {
      try {
        await loadCurrentUser()
      } catch {
        await refreshAccess(state.accessToken)
        await loadCurrentUser()
      }
    } else if (state.refreshToken) {
      await refreshAccess()
      await loadCurrentUser()
    }
  } catch {
    clear()
  } finally {
    state.initialized = true
  }
}

async function login(username: string, password: string) {
  const tokens = await authFetch<TokenPair>('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  storeTokens(tokens)
  await loadCurrentUser()
}

export const authSession = {
  state,
  authenticated: computed(() => Boolean(state.accessToken && state.user)),
  initialize,
  login,
  logout: clear,
  refreshAccess,
}
