import type { User } from '../types'

const tokenKey = 'voidswitch.token'

export function useApi() {
  const config = useRuntimeConfig()
  const base = config.public.apiBase || (import.meta.client ? location.origin : 'http://localhost:8080')

  async function request<T>(path: string, options: { method?: string, body?: unknown, query?: Record<string, string | number | boolean | undefined> } = {}): Promise<T> {
    const url = new URL(path, base)
    for (const [key, value] of Object.entries(options.query || {})) {
      if (value !== undefined) url.searchParams.set(key, String(value))
    }
    const token = import.meta.client ? localStorage.getItem(tokenKey) : null
    const response = await fetch(url, {
      method: options.method || 'GET',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: 'no-store'
    })
    if (response.status === 401 && !path.startsWith('/api/auth/')) {
      localStorage.removeItem(tokenKey)
      if (path !== '/api/me' && !location.pathname.startsWith('/login')) await navigateTo('/login')
    }
    if (!response.ok) {
      const error = await response.json().catch(() => ({}))
      throw new Error(error.detail || error.error?.message || `HTTP ${response.status}`)
    }
    return response.status === 204 ? undefined as T : response.json() as Promise<T>
  }
  return {
    base,
    get: <T>(path: string, query?: Record<string, string | number | boolean | undefined>) => request<T>(path, { query }),
    post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
    put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body }),
    patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
    del: <T>(path: string) => request<T>(path, { method: 'DELETE' })
  }
}

export function useSession() {
  const user = useState<User | null>('session-user', () => null)
  const loaded = useState('session-loaded', () => false)
  const isStaff = computed(() => ['owner', 'co-owner', 'admin'].includes(user.value?.role || ''))
  const isOwner = computed(() => ['owner', 'co-owner'].includes(user.value?.role || ''))
  const isObserver = computed(() => !!user.value?.managed_group_ids?.length)
  async function refresh() {
    const token = localStorage.getItem(tokenKey)
    try { user.value = token ? await useApi().get<User>('/api/me') : null } catch { user.value = null }
    loaded.value = true
  }
  function logout() { localStorage.removeItem(tokenKey); user.value = null; return navigateTo('/login') }
  return { user, loaded, isStaff, isOwner, isObserver, refresh, logout }
}
