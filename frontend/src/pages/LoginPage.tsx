import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'

export default function LoginPage() {
  const { user, loading, signIn, signInWithGoogle } = useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (!loading && user) return <Navigate to="/agents" replace />

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await signIn(email, password)
      navigate('/agents', { replace: true })
    } catch {
      setError('Invalid email or password.')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleGoogle() {
    setError('')
    try {
      await signInWithGoogle()
    } catch {
      setError('Google sign-in failed. Please try again.')
    }
  }

  return (
    <div className="flex h-screen items-center justify-center bg-background font-mono">
      <div className="w-full max-w-sm space-y-6 px-6">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold tracking-tight text-foreground">
            The Machine
          </h1>
          <p className="text-sm text-muted-foreground">Sign in to your account</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm text-foreground" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              placeholder="you@example.com"
            />
          </div>

          <div className="space-y-2">
            <label className="text-sm text-foreground" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              placeholder="••••••••"
            />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-border" />
          </div>
          <div className="relative flex justify-center text-xs">
            <span className="bg-background px-2 text-muted-foreground">or</span>
          </div>
        </div>

        <button
          type="button"
          onClick={handleGoogle}
          className="w-full rounded-md border border-input bg-background px-4 py-2 text-sm text-foreground hover:bg-secondary"
        >
          Continue with Google
        </button>

        <p className="text-center text-xs text-muted-foreground">
          Don't have an account?{' '}
          <a href="https://your-signup-url" className="underline underline-offset-4 hover:text-foreground">
            Contact us
          </a>
        </p>
      </div>
    </div>
  )
}
