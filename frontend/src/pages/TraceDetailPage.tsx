import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

const API = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ToolCallEntry = { id: string; name: string; arguments: Record<string, unknown> }
type ToolResultEntry = { id: string; result: string }
type Iteration = { n: number; tool_calls: ToolCallEntry[]; tool_results: ToolResultEntry[] }
type TraceJson = {
  user_message: string
  started_at: string
  iterations: Iteration[]
  final_response: string
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
  error: string | null
}
type TraceDetail = {
  id: string
  agent_id: string | null
  agent_name: string | null
  created_at: string
  trace_json: TraceJson
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TraceDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [trace, setTrace] = useState<TraceDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const res = await fetch(`${API}/api/traces/${id}`, { credentials: 'include' })
        if (res.status === 401) { navigate('/login'); return }
        if (res.status === 404) { setError('Trace not found.'); return }
        if (res.ok) setTrace(await res.json())
        else setError('Failed to load trace.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [id, navigate])

  if (loading) return (
    <div className="flex h-screen items-center justify-center bg-background font-mono text-muted-foreground text-sm">
      Loading…
    </div>
  )

  if (error || !trace) return (
    <div className="flex h-screen items-center justify-center bg-background font-mono">
      <div className="text-center space-y-3">
        <p className="text-sm text-destructive">{error || 'Not found.'}</p>
        <button
          onClick={() => navigate('/traces')}
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Back to traces
        </button>
      </div>
    </div>
  )

  const tj = trace.trace_json

  return (
    <div className="min-h-screen bg-background font-mono text-foreground">
      <div className="mx-auto max-w-3xl px-6 py-12 space-y-6">

        {/* Header */}
        <div>
          <button
            onClick={() => navigate(-1)}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            ← Back
          </button>
          <div className="flex items-start justify-between mt-3">
            <div className="space-y-0.5">
              <h1 className="text-lg font-semibold">{trace.agent_name ?? 'Unknown agent'}</h1>
              <p className="text-xs text-muted-foreground">
                {new Date(trace.created_at).toLocaleString()}
              </p>
            </div>
            <div className="text-right text-xs text-muted-foreground shrink-0">
              <p className="font-medium text-foreground">{tj.usage.total_tokens} tokens</p>
              <p>{tj.usage.prompt_tokens}↑ · {tj.usage.completion_tokens}↓</p>
            </div>
          </div>
        </div>

        {/* User message */}
        <div className="animate-fade-in-up rounded-md border border-border px-4 py-3 space-y-1">
          <p className="text-xs text-muted-foreground">User</p>
          <p className="text-sm">{tj.user_message}</p>
        </div>

        {/* Iterations */}
        {tj.iterations.map((it, idx) => (
          <div
            key={it.n}
            className="animate-fade-in-up space-y-2"
            style={{ animationDelay: `${(idx + 1) * 60}ms` }}
          >
            <p className="text-xs text-muted-foreground px-1">
              Iteration {it.n} · {it.tool_calls.length} tool call{it.tool_calls.length !== 1 ? 's' : ''}
            </p>
            {it.tool_calls.map((tc) => {
              const result = it.tool_results.find((r) => r.id === tc.id)
              return (
                <div key={tc.id} className="rounded-md border border-border overflow-hidden">
                  {/* Tool call */}
                  <div className="px-4 py-3 bg-secondary/40">
                    <p className="text-xs font-medium">{tc.name}</p>
                    <pre className="mt-1.5 text-xs text-muted-foreground overflow-x-auto whitespace-pre-wrap break-all">
                      {JSON.stringify(tc.arguments, null, 2)}
                    </pre>
                  </div>
                  {/* Tool result */}
                  {result && (
                    <div className="px-4 py-3 border-t border-border">
                      <p className="text-xs text-muted-foreground mb-1.5">Result</p>
                      <p className="text-xs whitespace-pre-wrap break-all">{result.result}</p>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        ))}

        {/* Final response or error */}
        {tj.error ? (
          <div
            className="animate-fade-in-up rounded-md border border-destructive px-4 py-3 space-y-1"
            style={{ animationDelay: `${(tj.iterations.length + 1) * 60}ms` }}
          >
            <p className="text-xs text-destructive font-medium">Error</p>
            <p className="text-sm text-destructive">{tj.error}</p>
          </div>
        ) : tj.final_response ? (
          <div
            className="animate-fade-in-up rounded-md border border-border px-4 py-3 space-y-1"
            style={{ animationDelay: `${(tj.iterations.length + 1) * 60}ms` }}
          >
            <p className="text-xs text-muted-foreground">Response</p>
            <p className="text-sm whitespace-pre-wrap">{tj.final_response}</p>
          </div>
        ) : null}

      </div>
    </div>
  )
}
