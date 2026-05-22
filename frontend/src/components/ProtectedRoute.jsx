import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

/**
 * Gates a child route on authentication. While the auth context is
 * loading (initial /auth/me roundtrip), renders a thin skeleton so we
 * don't flicker-redirect users with a valid token.
 *
 * If a `role` prop is provided (e.g. role="analyst"), the user's role
 * must meet or exceed it. Otherwise we redirect to /unauthorized.
 */
const ROLE_RANK = { viewer: 0, analyst: 1, admin: 2 }

export default function ProtectedRoute({ children, role }) {
  const { isAuthenticated, loading, role: userRole } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        Loading…
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  if (role && (ROLE_RANK[userRole] ?? -1) < (ROLE_RANK[role] ?? 0)) {
    return <Navigate to="/unauthorized" replace />
  }

  return children
}
