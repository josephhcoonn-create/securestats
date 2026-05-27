import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { AuthProvider } from './hooks/useAuth'
import ProtectedRoute from './components/ProtectedRoute'
import Dashboard from './components/Dashboard'
import LoginPage from './pages/LoginPage'
import PlayersPage from './pages/PlayersPage'
import LeadersPage from './pages/LeadersPage'
import StreaksPage from './pages/StreaksPage'
import ComparePage from './pages/ComparePage'
import OddsPage from './pages/OddsPage'
import DailyPicksPage from './pages/DailyPicksPage'
import UnauthorizedPage from './pages/UnauthorizedPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            {/* Public */}
            <Route path="/login" element={<LoginPage />} />
            <Route path="/unauthorized" element={<UnauthorizedPage />} />

            {/* Protected — shared Dashboard shell */}
            <Route
              element={
                <ProtectedRoute>
                  <Dashboard />
                </ProtectedRoute>
              }
            >
              <Route index element={<Navigate to="/players" replace />} />
              <Route path="/players" element={<PlayersPage />} />
              <Route path="/leaders" element={<LeadersPage />} />
              <Route path="/streaks" element={<StreaksPage />} />
              <Route path="/compare" element={<ComparePage />} />
              <Route path="/odds" element={<OddsPage />} />
              <Route path="/picks" element={<DailyPicksPage />} />
            </Route>

            {/* Catch-all */}
            <Route path="*" element={<Navigate to="/players" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
