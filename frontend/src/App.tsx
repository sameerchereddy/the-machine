import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'

// Placeholder pages — implemented in later cycles
import LoginPage from '@/pages/LoginPage'
import OnboardingPage from '@/pages/OnboardingPage'
import SetupPage from '@/pages/SetupPage'
import AgentsPage from '@/pages/AgentsPage'
import AgentPage from '@/pages/AgentPage'
import TracesPage from '@/pages/TracesPage'
import TraceDetailPage from '@/pages/TraceDetailPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/onboarding" element={<OnboardingPage />} />
        <Route path="/setup" element={<SetupPage />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/agents/:id" element={<AgentPage />} />
        <Route path="/traces" element={<TracesPage />} />
        <Route path="/traces/:id" element={<TraceDetailPage />} />
        <Route path="/" element={<Navigate to="/agents" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
