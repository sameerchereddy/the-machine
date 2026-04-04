import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'

export default function OnboardingPage() {
  const { user } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="flex h-screen items-center justify-center bg-background font-mono">
      <div className="w-full max-w-sm space-y-4 px-6 text-center">
        <h1 className="text-xl font-semibold text-foreground">Welcome to The Machine</h1>
        <p className="text-sm text-muted-foreground">
          {user?.email}
        </p>
        <p className="text-sm text-muted-foreground">
          Next: configure your LLM provider to get started.
        </p>
        <button
          onClick={() => navigate('/setup')}
          className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          Set up my LLM →
        </button>
      </div>
    </div>
  )
}
