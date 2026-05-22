/**
 * Axios API client for the SecureStats backend.
 *
 * - Base URL is taken from VITE_API_URL (see frontend/.env), defaulting
 *   to http://localhost:8000/api/v1.
 * - Request interceptor attaches the JWT from localStorage as a Bearer
 *   token on every request.
 * - Response interceptor redirects to /login on 401 (token missing or
 *   expired) and surfaces the rest as a normal axios error.
 */
import axios from 'axios'

const TOKEN_KEY = 'securestats.token'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (token) => localStorage.setItem(TOKEN_KEY, token)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1',
  headers: { 'Content-Type': 'application/json' },
  timeout: 15000,
})

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      clearToken()
      // Avoid redirect loops if we're already on /login
      if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
        window.location.assign('/login')
      }
    }
    return Promise.reject(error)
  },
)

export default api
