import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

const API = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

type TraceSummary = {
  id: string
  agent_id: string | null
  agent_name: string | null
  user_message: string
  total_tokens: number
  has_error: boolean
  created_at: string
}

export default function TracesPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const agentIdFilter = searchParams.get('agent_id')

  const [traces, setTraces] = useState<TraceSummary[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const url = agentIdFilter
          ? `${API}/api/traces?agent_id=${agentIdFilter}`
          : `${API}/api/traces`
        const res = await fetch(url, { credentials: 'include' })
        if (res.status === 401) { navigate('/login'); return }
        if (res.ok) setTraces(await res.json())
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [agentIdFilter, navigate])

  return (
    <div className="min-h-screen bg-background font-mono text-foreground">
      <div className="mx-auto max-w-3xl px-6 py-12 space-y-8">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <h1 className="text-xl font-semibold tracking-tight">Traces</h1>
            <p className="text-sm text-muted-foreground">
              {agentIdFilter
                ? 'Runs for this agent — click any trace to inspect the full ReAct loop.'
                : 'All agent runs — click any trace to inspect the full ReAct loop.'}
            </p>
          </div>
          <button
            onClick={() => navigate('/agents')}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            ← Agents
          </button>
        </div>

        {/* List */}
        {loading ? (
          <div className="divide-y divide-border rounded-md border border-border">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="px-5 py-4 space-y-1.5">
                <div className="h-3 w-48 rounded bg-muted animate-pulse" />
                <div className="h-4 w-72 rounded bg-muted animate-pulse" />
              </div>
            ))}
          </div>
        ) : traces.length === 0 ? (
          <div className="rounded-md border border-dashed border-border px-6 py-16 text-center space-y-2">
            <p className="text-sm text-muted-foreground">No traces yet.</p>
            <p className="text-xs text-muted-foreground">Run an agent to record its first trace.</p>
            <button
              onClick={() => navigate('/agents')}
              className="mt-2 text-sm text-primary hover:underline"
            >
              Go to agents →
            </button>
          </div>
        ) : (
          <div className="divide-y divide-border rounded-md border border-border">
            {traces.map((trace, i) => (
              <div
                key={trace.id}
                onClick={() => navigate(`/traces/${trace.id}`)}
                className="animate-fade-in-up flex items-center justify-between px-5 py-4 cursor-pointer hover:bg-secondary transition-colors"
                style={{ animationDelay: `${i * 30}ms` }}
              >
                <div className="flex-1 min-w-0 space-y-0.5">
                  <p className="text-xs text-muted-foreground">
                    {trace.agent_name ?? 'Unknown agent'}
                    {' · '}
                    {new Date(trace.created_at).toLocaleString()}
                  </p>
                  <p className="text-sm text-foreground truncate">{trace.user_message}</p>
                </div>
                <div className="ml-4 shrink-0 flex items-center gap-3">
                  {trace.has_error ? (
                    <span className="text-xs text-destructive">error</span>
                  ) : (
                    <span className="text-xs text-muted-foreground">{trace.total_tokens} tok</span>
                  )}
                  <span className="text-xs text-muted-foreground">→</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
