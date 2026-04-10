import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

const API = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

type AgentSummary = {
  id: string
  name: string
  llm_config_id: string | null
  updated_at: string
}

export default function AgentsPage() {
  const navigate = useNavigate()
  const [agents, setAgents] = useState<AgentSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fetchAgents() }, [])

  async function fetchAgents() {
    setLoading(true)
    try {
      const res = await fetch(`${API}/api/agents`, { credentials: 'include' })
      if (res.status === 401) { navigate('/login'); return }
      if (res.ok) setAgents(await res.json())
    } finally {
      setLoading(false)
    }
  }

  async function handleDelete(e: React.MouseEvent, agentId: string) {
    e.stopPropagation()
    if (!window.confirm('Delete this agent? This cannot be undone.')) return
    setDeletingId(agentId)
    try {
      const res = await fetch(`${API}/api/agents/${agentId}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (res.ok) {
        setAgents((prev) => prev.filter((a) => a.id !== agentId))
      }
    } finally {
      setDeletingId(null)
    }
  }

  async function handleNew() {
    setCreating(true)
    try {
      const res = await fetch(`${API}/api/agents`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'Untitled Agent' }),
      })
      if (res.ok) {
        const agent: { id: string } = await res.json()
        navigate(`/agents/${agent.id}`)
      }
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="min-h-screen bg-background font-mono text-foreground">
      <div className="mx-auto max-w-3xl px-6 py-12 space-y-8">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <h1 className="text-xl font-semibold tracking-tight">Agents</h1>
            <p className="text-sm text-muted-foreground">
              Your saved agents. Each agent has its own LLM, instructions, and tools.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/traces')}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Traces
            </button>
            <button
              onClick={handleNew}
              disabled={creating}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
            >
              {creating ? 'Creating…' : '+ New agent'}
            </button>
          </div>
        </div>

        {/* List */}
        {loading ? (
          <div className="divide-y divide-border rounded-md border border-border">
            {[1, 2, 3].map((i) => (
              <div key={i} className="px-5 py-4 space-y-1.5">
                <div className="h-4 w-48 rounded bg-muted animate-pulse" />
                <div className="h-3 w-32 rounded bg-muted animate-pulse" />
              </div>
            ))}
          </div>
        ) : agents.length === 0 ? (
          <div className="rounded-md border border-dashed border-border px-6 py-16 text-center">
            <p className="text-sm text-muted-foreground">No agents yet.</p>
            <button
              onClick={handleNew}
              className="mt-3 text-sm text-primary hover:underline"
            >
              Create your first agent →
            </button>
          </div>
        ) : (
          <div className="divide-y divide-border rounded-md border border-border">
            {agents.map((agent) => (
              <div
                key={agent.id}
                onClick={() => navigate(`/agents/${agent.id}`)}
                className="flex items-center justify-between px-5 py-4 cursor-pointer hover:bg-secondary transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3">
                    <p className="text-sm font-medium text-foreground truncate">{agent.name}</p>
                    <p className="text-xs text-muted-foreground shrink-0">
                      {new Date(agent.updated_at).toLocaleDateString()}
                    </p>
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {agent.llm_config_id ? 'LLM configured' : 'No LLM — click to configure'}
                  </p>
                </div>
                <button
                  onClick={(e) => handleDelete(e, agent.id)}
                  disabled={deletingId === agent.id}
                  className="ml-4 shrink-0 text-xs text-muted-foreground hover:text-destructive disabled:opacity-40"
                >
                  {deletingId === agent.id ? '…' : 'Delete'}
                </button>
              </div>
            ))}
          </div>
        )}

        <p className="text-xs text-muted-foreground">
          Need to add an LLM?{' '}
          <button onClick={() => navigate('/setup')} className="underline hover:text-foreground">
            Go to setup
          </button>
        </p>
      </div>
    </div>
  )
}
