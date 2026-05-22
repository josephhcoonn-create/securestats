import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { AuthProvider } from './hooks/useAuth'
import ProtectedRoute from './components/ProtectedRoute'
import Dashboard from './components/Dashboard'
import LoginPage from './pages/LoginPage'
import PlayersPage from './pages/PlayersPage'
import PlaceholderPage from './pages/PlaceholderPage'
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
              <Route
                path="/leaders"
                element={
                  <PlaceholderPage
                    title="Batting Leaders"
                    subtitle="Charts and rankings land in Task 5.3."
                  />
                }
              />
              <Route
                path="/streaks"
                element={
                  <PlaceholderPage
                    title="Hot & Cold Streaks"
                    subtitle="Streak detection UI lands in Task 5.3."
                  />
                }
              />
              <Route
                path="/compare"
                element={
                  <PlaceholderPage
                    title="Player Comparison"
                    subtitle="Side-by-side comparison lands in Task 5.4."
                  />
                }
              />
            </Route>

            {/* Catch-all */}
            <Route path="*" element={<Navigate to="/players" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
