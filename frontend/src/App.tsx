import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from '@/context/AuthContext'
import ProtectedRoute from '@/components/ProtectedRoute'
import LoginPage from '@/pages/LoginPage'
import OnboardingPage from '@/pages/OnboardingPage'
import AuthCallbackPage from '@/pages/AuthCallbackPage'
import SetupPage from '@/pages/SetupPage'
import AgentsPage from '@/pages/AgentsPage'
import AgentPage from '@/pages/AgentPage'
import TracesPage from '@/pages/TracesPage'
import TraceDetailPage from '@/pages/TraceDetailPage'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/auth/callback" element={<AuthCallbackPage />} />

          {/* Protected */}
          <Route path="/onboarding" element={<ProtectedRoute><OnboardingPage /></ProtectedRoute>} />
          <Route path="/setup" element={<ProtectedRoute><SetupPage /></ProtectedRoute>} />
          <Route path="/agents" element={<ProtectedRoute><AgentsPage /></ProtectedRoute>} />
          <Route path="/agents/:id" element={<ProtectedRoute><AgentPage /></ProtectedRoute>} />
          <Route path="/traces" element={<ProtectedRoute><TracesPage /></ProtectedRoute>} />
          <Route path="/traces/:id" element={<ProtectedRoute><TraceDetailPage /></ProtectedRoute>} />

          <Route path="/" element={<Navigate to="/agents" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
