/**
 * Dashboard shell layout.
 *
 * Responsive: sidebar collapses to a top strip on small screens.
 * Sidebar links: Players / Leaders / Streaks / Compare.
 * Header: app name, user info with role badge, sign-out button.
 * <Outlet/> renders the active child route.
 */
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

const NAV = [
  { to: '/players', label: 'Players' },
  { to: '/leaders', label: 'Leaders' },
  { to: '/streaks', label: 'Streaks' },
  { to: '/compare', label: 'Compare' },
  { to: '/odds', label: 'Odds' },
  { to: '/picks', label: 'Daily Picks' },
]

const ROLE_BADGE = {
  admin: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
  analyst: 'bg-blue-500/20 text-blue-300 ring-blue-500/30',
  viewer: 'bg-slate-500/20 text-slate-300 ring-slate-500/30',
}

export default function Dashboard() {
  const { user, logout } = useAuth()

  return (
    <div className="flex min-h-screen flex-col bg-slate-900 text-slate-100 md:flex-row">
      {/* Sidebar */}
      <aside className="border-b border-slate-800 bg-slate-950 md:w-60 md:border-b-0 md:border-r">
        <div className="px-6 py-5">
          <h1 className="text-xl font-semibold tracking-tight text-white">
            SecureStats
          </h1>
          <p className="mt-0.5 text-xs text-slate-400">MLB analytics</p>
        </div>

        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:gap-0.5 md:px-3 md:pb-6">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                [
                  'whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-slate-800 text-white'
                    : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-100',
                ].join(' ')
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-800 bg-slate-900/95 px-6 py-3 backdrop-blur">
          <div className="text-sm text-slate-400">
            Signed in as{' '}
            <span className="font-medium text-slate-100">{user?.username}</span>
          </div>
          <div className="flex items-center gap-3">
            <span
              className={[
                'rounded-full px-2.5 py-0.5 text-xs font-medium ring-1',
                ROLE_BADGE[user?.role] ?? ROLE_BADGE.viewer,
              ].join(' ')}
            >
              {user?.role}
            </span>
            <button
              onClick={logout}
              className="rounded-md border border-slate-700 bg-slate-800 px-3 py-1 text-sm font-medium text-slate-200 hover:bg-slate-700"
            >
              Sign out
            </button>
          </div>
        </header>

        <main className="min-w-0 flex-1 overflow-x-auto px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
