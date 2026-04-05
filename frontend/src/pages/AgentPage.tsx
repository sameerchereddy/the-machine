import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

const API = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Agent = {
  id: string
  name: string
  llm_config_id: string | null
  instructions: string
  persona_name: string | null
  response_style: string
  output_format: string
  response_language: string
  show_reasoning: boolean
  context_entries: { key: string; value: string }[]
  auto_inject_datetime: boolean
  auto_inject_user_profile: boolean
  context_render_as: string
  history_window: number
  summarise_old_messages: boolean
  long_term_enabled: boolean
  max_memories: number
  retention_days: number
  kb_top_k: number
  kb_similarity_threshold: number
  kb_reranking: boolean
  kb_show_sources: boolean
  max_iterations: number
  on_max_iterations: string
  max_tool_calls_per_run: number
  max_tokens_per_run: number
  allow_clarifying_questions: boolean
  pii_detection: boolean
  safe_tool_mode: boolean
}

type LLMConfig = { id: string; name: string; provider: string; model: string }

// ---------------------------------------------------------------------------
// Block component
// ---------------------------------------------------------------------------

function Block({
  title,
  children,
  defaultOpen = false,
}: {
  title: string
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="rounded-md border border-border">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium hover:bg-secondary"
      >
        <span>{title}</span>
        <span className="text-muted-foreground text-xs">{open ? '▲' : '▼'}</span>
      </button>
      {open && <div className="border-t border-border px-4 py-4 space-y-4">{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Field helpers
// ---------------------------------------------------------------------------

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs text-muted-foreground">{label}</label>
      {children}
    </div>
  )
}

const inputCls =
  'w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring'

const selectCls =
  'w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring'

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AgentPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const [agent, setAgent] = useState<Agent | null>(null)
  const [llmConfigs, setLlmConfigs] = useState<LLMConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')

  // Draggable divider
  const [splitPct, setSplitPct] = useState(60)
  const dragging = useRef(false)
  const dividerMoveRef = useRef<((e: MouseEvent) => void) | null>(null)
  const dividerUpRef = useRef<(() => void) | null>(null)

  // Clean up divider listeners if component unmounts mid-drag
  useEffect(() => {
    return () => {
      if (dividerMoveRef.current) window.removeEventListener('mousemove', dividerMoveRef.current)
      if (dividerUpRef.current) window.removeEventListener('mouseup', dividerUpRef.current)
    }
  }, [])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load() }, [id])

  async function load() {
    setLoading(true)
    try {
      const [agentRes, configsRes] = await Promise.all([
        fetch(`${API}/api/agents/${id}`, { credentials: 'include' }),
        fetch(`${API}/api/llm-configs`, { credentials: 'include' }),
      ])
      if (agentRes.status === 401) { navigate('/login'); return }
      if (!agentRes.ok) { setError('Agent not found.'); return }
      setAgent(await agentRes.json())
      if (configsRes.ok) setLlmConfigs(await configsRes.json())
    } finally {
      setLoading(false)
    }
  }

  function update(patch: Partial<Agent>) {
    setAgent((a) => a ? { ...a, ...patch } : a)
    setSaved(false)
  }

  async function save() {
    if (!agent) return
    setSaving(true)
    setError('')
    try {
      const res = await fetch(`${API}/api/agents/${agent.id}`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(agent),
      })
      if (res.ok) {
        setAgent(await res.json())
        setSaved(true)
        setTimeout(() => setSaved(false), 2000)
      } else {
        setError('Save failed. Please try again.')
      }
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!agent) return
    if (!window.confirm(`Delete "${agent.name}"? This cannot be undone.`)) return
    setDeleting(true)
    try {
      const res = await fetch(`${API}/api/agents/${agent.id}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (res.ok) navigate('/agents')
      else setError('Delete failed.')
    } finally {
      setDeleting(false)
    }
  }

  // Divider drag
  function onDividerMouseDown() {
    dragging.current = true
    function onMove(e: MouseEvent) {
      if (!dragging.current) return
      const pct = Math.round((e.clientX / window.innerWidth) * 100)
      setSplitPct(Math.min(70, Math.max(30, pct)))
    }
    function onUp() {
      dragging.current = false
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      dividerMoveRef.current = null
      dividerUpRef.current = null
    }
    dividerMoveRef.current = onMove
    dividerUpRef.current = onUp
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background font-mono text-muted-foreground text-sm">
        Loading…
      </div>
    )
  }

  if (error && !agent) {
    return (
      <div className="flex h-screen items-center justify-center bg-background font-mono">
        <div className="text-center space-y-3">
          <p className="text-sm text-destructive">{error}</p>
          <button onClick={() => navigate('/agents')} className="text-sm text-muted-foreground hover:text-foreground">
            ← Back to agents
          </button>
        </div>
      </div>
    )
  }

  if (!agent) return null

  return (
    <div className="flex h-screen bg-background font-mono text-foreground select-none">

      {/* ── Builder panel ───────────────────────────────────────── */}
      <div
        className="flex flex-col overflow-hidden border-r border-border"
        style={{ width: `${splitPct}%` }}
      >
        {/* Toolbar */}
        <div className="flex items-center justify-between border-b border-border px-4 py-2 shrink-0">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/agents')}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              ← Agents
            </button>
            <input
              value={agent.name}
              onChange={(e) => update({ name: e.target.value })}
              className="bg-transparent text-sm font-medium focus:outline-none border-b border-transparent focus:border-border"
            />
          </div>
          <div className="flex items-center gap-2">
            {error && <span className="text-xs text-destructive">{error}</span>}
            {saved && <span className="text-xs text-green-400">Saved</span>}
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="text-xs text-muted-foreground hover:text-destructive disabled:opacity-40"
            >
              {deleting ? 'Deleting…' : 'Delete'}
            </button>
            <button
              onClick={save}
              disabled={saving}
              className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>

        {/* Blocks */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3 select-text">

          {/* LLM */}
          <Block title="LLM" defaultOpen>
            <Field label="Provider config">
              <select
                value={agent.llm_config_id ?? ''}
                onChange={(e) => update({ llm_config_id: e.target.value || null })}
                className={selectCls}
              >
                <option value="">— none —</option>
                {llmConfigs.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.provider} · {c.model})
                  </option>
                ))}
              </select>
            </Field>
            {llmConfigs.length === 0 && (
              <p className="text-xs text-muted-foreground">
                No LLM configs saved.{' '}
                <button onClick={() => navigate('/setup')} className="underline hover:text-foreground">
                  Add one →
                </button>
              </p>
            )}
          </Block>

          {/* Instructions */}
          <Block title="Instructions" defaultOpen>
            <Field label="System prompt">
              <textarea
                rows={6}
                value={agent.instructions}
                onChange={(e) => update({ instructions: e.target.value })}
                className={`${inputCls} resize-y`}
                placeholder="You are a helpful assistant…"
              />
            </Field>
            <Field label="Persona name (optional)">
              <input
                type="text"
                value={agent.persona_name ?? ''}
                onChange={(e) => update({ persona_name: e.target.value || null })}
                className={inputCls}
                placeholder="e.g. Aria"
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Response style">
                <select
                  value={agent.response_style}
                  onChange={(e) => update({ response_style: e.target.value })}
                  className={selectCls}
                >
                  <option value="concise">Concise</option>
                  <option value="balanced">Balanced</option>
                  <option value="verbose">Verbose</option>
                </select>
              </Field>
              <Field label="Output format">
                <select
                  value={agent.output_format}
                  onChange={(e) => update({ output_format: e.target.value })}
                  className={selectCls}
                >
                  <option value="markdown">Markdown</option>
                  <option value="plain_text">Plain text</option>
                  <option value="json">JSON</option>
                </select>
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Language">
                <input
                  type="text"
                  value={agent.response_language}
                  onChange={(e) => update({ response_language: e.target.value })}
                  className={inputCls}
                  placeholder="en"
                />
              </Field>
              <Field label="Show reasoning">
                <label className="flex items-center gap-2 pt-1 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={agent.show_reasoning}
                    onChange={(e) => update({ show_reasoning: e.target.checked })}
                    className="h-4 w-4"
                  />
                  <span className="text-sm">Enabled</span>
                </label>
              </Field>
            </div>
          </Block>

          {/* Context */}
          <Block title="Context">
            <div className="space-y-2">
              {agent.context_entries.map((entry, i) => (
                <div key={i} className="flex gap-2">
                  <input
                    type="text"
                    value={entry.key}
                    onChange={(e) => {
                      const entries = [...agent.context_entries]
                      entries[i] = { ...entries[i], key: e.target.value }
                      update({ context_entries: entries })
                    }}
                    className={`${inputCls} w-1/3`}
                    placeholder="key"
                  />
                  <input
                    type="text"
                    value={entry.value}
                    onChange={(e) => {
                      const entries = [...agent.context_entries]
                      entries[i] = { ...entries[i], value: e.target.value }
                      update({ context_entries: entries })
                    }}
                    className={`${inputCls} flex-1`}
                    placeholder="value"
                  />
                  <button
                    onClick={() => update({ context_entries: agent.context_entries.filter((_, j) => j !== i) })}
                    className="text-xs text-destructive hover:opacity-80 px-1"
                  >
                    ✕
                  </button>
                </div>
              ))}
              <button
                onClick={() => update({ context_entries: [...agent.context_entries, { key: '', value: '' }] })}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                + Add entry
              </button>
            </div>
            <div className="flex gap-4 pt-1">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agent.auto_inject_datetime}
                  onChange={(e) => update({ auto_inject_datetime: e.target.checked })}
                  className="h-4 w-4"
                />
                <span className="text-xs">Inject date/time</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agent.auto_inject_user_profile}
                  onChange={(e) => update({ auto_inject_user_profile: e.target.checked })}
                  className="h-4 w-4"
                />
                <span className="text-xs">Inject user profile</span>
              </label>
            </div>
          </Block>

          {/* Memory */}
          <Block title="Memory">
            <div className="grid grid-cols-2 gap-3">
              <Field label="History window (turns)">
                <input
                  type="number"
                  value={agent.history_window}
                  onChange={(e) => update({ history_window: Number(e.target.value) })}
                  className={inputCls}
                  min={1}
                />
              </Field>
              <Field label="Max memories">
                <input
                  type="number"
                  value={agent.max_memories}
                  onChange={(e) => update({ max_memories: Number(e.target.value) })}
                  className={inputCls}
                  min={1}
                />
              </Field>
            </div>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agent.summarise_old_messages}
                  onChange={(e) => update({ summarise_old_messages: e.target.checked })}
                  className="h-4 w-4"
                />
                <span className="text-xs">Summarise old messages</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agent.long_term_enabled}
                  onChange={(e) => update({ long_term_enabled: e.target.checked })}
                  className="h-4 w-4"
                />
                <span className="text-xs">Long-term memory</span>
              </label>
            </div>
          </Block>

          {/* Guardrails */}
          <Block title="Guardrails">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Max iterations">
                <input
                  type="number"
                  value={agent.max_iterations}
                  onChange={(e) => update({ max_iterations: Number(e.target.value) })}
                  className={inputCls}
                  min={1}
                />
              </Field>
              <Field label="On max iterations">
                <select
                  value={agent.on_max_iterations}
                  onChange={(e) => update({ on_max_iterations: e.target.value })}
                  className={selectCls}
                >
                  <option value="return_partial">Return partial</option>
                  <option value="fail_with_message">Fail with message</option>
                  <option value="ask_user">Ask user</option>
                </select>
              </Field>
              <Field label="Max tool calls/run">
                <input
                  type="number"
                  value={agent.max_tool_calls_per_run}
                  onChange={(e) => update({ max_tool_calls_per_run: Number(e.target.value) })}
                  className={inputCls}
                  min={1}
                />
              </Field>
              <Field label="Max tokens/run">
                <input
                  type="number"
                  value={agent.max_tokens_per_run}
                  onChange={(e) => update({ max_tokens_per_run: Number(e.target.value) })}
                  className={inputCls}
                  min={1}
                />
              </Field>
            </div>
            <div className="flex gap-4 flex-wrap">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agent.allow_clarifying_questions}
                  onChange={(e) => update({ allow_clarifying_questions: e.target.checked })}
                  className="h-4 w-4"
                />
                <span className="text-xs">Allow clarifying questions</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agent.pii_detection}
                  onChange={(e) => update({ pii_detection: e.target.checked })}
                  className="h-4 w-4"
                />
                <span className="text-xs">PII detection</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agent.safe_tool_mode}
                  onChange={(e) => update({ safe_tool_mode: e.target.checked })}
                  className="h-4 w-4"
                />
                <span className="text-xs">Safe tool mode</span>
              </label>
            </div>
          </Block>

        </div>
      </div>

      {/* ── Drag handle ─────────────────────────────────────────── */}
      <div
        onMouseDown={onDividerMouseDown}
        className="w-1 cursor-col-resize bg-border hover:bg-ring transition-colors shrink-0"
      />

      {/* ── Chat panel ──────────────────────────────────────────── */}
      <div className="flex flex-col flex-1 overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-4 py-2 shrink-0">
          <span className="text-xs text-muted-foreground">Chat console</span>
        </div>
        <div className="flex flex-1 items-center justify-center text-center px-8">
          <div className="space-y-3 max-w-xs">
            <p className="text-sm text-muted-foreground">
              Configure your agent in the builder, then launch a session here.
            </p>
            <button
              disabled
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground opacity-40 cursor-not-allowed"
            >
              ▶ Launch agent
            </button>
            <p className="text-xs text-muted-foreground">Coming in a future cycle</p>
          </div>
        </div>
      </div>

    </div>
  )
}
