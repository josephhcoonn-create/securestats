/**
 * Auth context.
 *
 * Provides:
 *   - user             — { username, email, role } or null
 *   - role             — 'viewer' | 'analyst' | 'admin' | null
 *   - isAuthenticated  — boolean derived from user
 *   - loading          — true while we're checking /auth/me on mount
 *   - login(u, p)      — POST /auth/login, store token, fetch /auth/me
 *   - logout()         — clear token and user
 *
 * The token is persisted in localStorage by api/client.js. On mount we
 * try /auth/me to rehydrate the user when a token already exists.
 */
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import api, { clearToken, getToken, setToken } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  // Rehydrate on mount
  useEffect(() => {
    let cancelled = false
    const init = async () => {
      const token = getToken()
      if (!token) {
        setLoading(false)
        return
      }
      try {
        const { data } = await api.get('/auth/me')
        if (!cancelled) setUser(data)
      } catch {
        if (!cancelled) {
          clearToken()
          setUser(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    init()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (username, password) => {
    const { data } = await api.post('/auth/login', { username, password })
    setToken(data.access_token)
    const me = await api.get('/auth/me')
    setUser(me.data)
    return me.data
  }, [])

  const logout = useCallback(() => {
    clearToken()
    setUser(null)
  }, [])

  const value = {
    user,
    role: user?.role ?? null,
    isAuthenticated: !!user,
    loading,
    login,
    logout,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used inside <AuthProvider>')
  }
  return ctx
}
