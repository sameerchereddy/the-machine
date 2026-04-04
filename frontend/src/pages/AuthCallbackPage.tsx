import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { supabase } from '@/lib/supabase'

export default function AuthCallbackPage() {
  const navigate = useNavigate()

  useEffect(() => {
    supabase.auth.getSession().then(async ({ data }) => {
      if (data.session) {
        await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ access_token: data.session.access_token }),
          credentials: 'include',
        })
        // New users → onboarding, returning users → agents
        const isNew = data.session.user.created_at === data.session.user.last_sign_in_at
        navigate(isNew ? '/onboarding' : '/agents', { replace: true })
      } else {
        navigate('/login', { replace: true })
      }
    })
  }, [navigate])

  return (
    <div className="flex h-screen items-center justify-center bg-background">
      <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
    </div>
  )
}
