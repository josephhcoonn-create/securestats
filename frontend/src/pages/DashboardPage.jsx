import { useAuth } from '../hooks/useAuth'

export default function DashboardPage() {
  const { user, logout } = useAuth()

  return (
    <div className="min-h-full bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
          <h1 className="text-lg font-semibold text-slate-900">SecureStats</h1>
          <div className="flex items-center gap-3 text-sm text-slate-600">
            <span>
              {user?.username}{' '}
              <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
                {user?.role}
              </span>
            </span>
            <button
              onClick={logout}
              className="rounded-md border border-slate-300 bg-white px-3 py-1 text-sm font-medium text-slate-700 hover:bg-slate-100"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-10">
        <div className="rounded-xl bg-white p-8 shadow-sm ring-1 ring-slate-200">
          <h2 className="text-xl font-semibold text-slate-900">Welcome, {user?.username}.</h2>
          <p className="mt-2 text-sm text-slate-600">
            Frontend scaffolding is online. Charts and leaderboards land in Task 5.2.
          </p>
        </div>
      </main>
    </div>
  )
}
