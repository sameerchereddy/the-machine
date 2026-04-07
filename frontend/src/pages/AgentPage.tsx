import { useEffect, useRef, useState, useCallback } from 'react'
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
  kb_chunk_size: number
  kb_chunk_overlap: number
  max_iterations: number
  on_max_iterations: string
  max_tool_calls_per_run: number
  max_tokens_per_run: number
  allow_clarifying_questions: boolean
  pii_detection: boolean
  safe_tool_mode: boolean
}

type LLMConfig = { id: string; name: string; provider: string; model: string }

type KnowledgeSource = {
  id: string
  name: string
  source_type: string
  file_size_bytes: number | null
  chunk_count: number
  status: 'pending' | 'indexing' | 'ready' | 'error'
  error_message: string | null
  created_at: string
}

type Memory = {
  id: string
  content: string
  memory_type: string
  created_at: string
  expires_at: string | null
}

type ToolActivity = {
  id: string
  name: string
  input: Record<string, unknown>
  result?: string
}

type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
  tools: ToolActivity[]
  traceId?: string
  streaming?: boolean
}

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

  // Knowledge base state
  const [sources, setSources] = useState<KnowledgeSource[]>([])
  const [uploading, setUploading] = useState(false)
  const [embeddingKey, setEmbeddingKey] = useState('')
  const [savingEmbKey, setSavingEmbKey] = useState(false)
  const [embKeySaved, setEmbKeySaved] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [dragOver, setDragOver] = useState(false)

  // Memory state
  const [memories, setMemories] = useState<Memory[]>([])

  // Chat state
  const [launched, setLaunched] = useState(false)
  const [running, setRunning] = useState(false)
  const [chatInput, setChatInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const chatScrollRef = useRef<HTMLDivElement | null>(null)

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
    await Promise.all([loadSources(), loadMemories()])
  }

  async function loadSources() {
    const res = await fetch(`${API}/api/agents/${id}/knowledge`, { credentials: 'include' })
    if (res.ok) {
      const data: KnowledgeSource[] = await res.json()
      setSources(data)
      // Poll while any source is still processing
      if (data.some((s) => s.status === 'pending' || s.status === 'indexing')) {
        if (!pollRef.current) {
          pollRef.current = setInterval(async () => {
            const r = await fetch(`${API}/api/agents/${id}/knowledge`, { credentials: 'include' })
            if (r.ok) {
              const updated: KnowledgeSource[] = await r.json()
              setSources(updated)
              if (!updated.some((s) => s.status === 'pending' || s.status === 'indexing')) {
                clearInterval(pollRef.current!)
                pollRef.current = null
              }
            }
          }, 3000)
        }
      }
    }
  }

  async function loadMemories() {
    const res = await fetch(`${API}/api/agents/${id}/memories`, { credentials: 'include' })
    if (res.ok) setMemories(await res.json())
  }

  async function handleUpload(files: FileList) {
    if (!files.length) return
    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        const form = new FormData()
        form.append('file', file)
        const res = await fetch(`${API}/api/agents/${id}/knowledge/upload`, {
          method: 'POST',
          credentials: 'include',
          body: form,
        })
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          setError((body as { detail?: string }).detail ?? 'Upload failed.')
        }
      }
    } finally {
      setUploading(false)
      await loadSources()
    }
  }

  async function deleteSource(sourceId: string) {
    const res = await fetch(`${API}/api/agents/${id}/knowledge/${sourceId}`, {
      method: 'DELETE',
      credentials: 'include',
    })
    if (res.ok) {
      setSources((prev) => prev.filter((s) => s.id !== sourceId))
    } else {
      setError('Failed to delete source. Please try again.')
    }
  }

  async function deleteMemory(memId: string) {
    const res = await fetch(`${API}/api/agents/${id}/memories/${memId}`, {
      method: 'DELETE',
      credentials: 'include',
    })
    if (res.ok) {
      setMemories((prev) => prev.filter((m) => m.id !== memId))
    } else {
      setError('Failed to delete memory. Please try again.')
    }
  }

  async function saveEmbeddingKey() {
    if (!embeddingKey.trim()) return
    setSavingEmbKey(true)
    try {
      const res = await fetch(`${API}/api/agents/${id}/knowledge/embedding-key`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: embeddingKey }),
      })
      if (res.ok) {
        setEmbeddingKey('')
        setEmbKeySaved(true)
        setTimeout(() => setEmbKeySaved(false), 2000)
      } else {
        const body = await res.json().catch(() => ({}))
        setError((body as { detail?: string }).detail ?? 'Failed to save key.')
      }
    } finally {
      setSavingEmbKey(false)
    }
  }

  // Clean up poll interval on unmount
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

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

  // ── Chat ──────────────────────────────────────────────────────────────────

  function scrollToBottom() {
    chatScrollRef.current?.scrollTo({ top: chatScrollRef.current.scrollHeight, behavior: 'smooth' })
  }

  const handleLaunch = useCallback(() => {
    const ws = new WebSocket(`${API.replace(/^http/, 'ws')}/api/agents/${id}/run`)

    ws.onopen = () => setLaunched(true)

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data as string) as Record<string, unknown>

      if (msg.type === 'iteration') {
        // New turn starting — no UI update needed
      } else if (msg.type === 'tool_start') {
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last?.role === 'assistant' && last.streaming) {
            const updated = { ...last, tools: [...last.tools, { id: msg.tool_id as string, name: msg.tool_name as string, input: msg.input as Record<string, unknown> }] }
            return [...prev.slice(0, -1), updated]
          }
          return [...prev, { role: 'assistant', content: '', tools: [{ id: msg.tool_id as string, name: msg.tool_name as string, input: msg.input as Record<string, unknown> }], streaming: true }]
        })
        scrollToBottom()
      } else if (msg.type === 'tool_end') {
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last?.role === 'assistant') {
            const tools = last.tools.map((t) =>
              t.id === msg.tool_id ? { ...t, result: msg.result as string } : t,
            )
            return [...prev.slice(0, -1), { ...last, tools }]
          }
          return prev
        })
      } else if (msg.type === 'delta') {
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last?.role === 'assistant' && last.streaming) {
            return [...prev.slice(0, -1), { ...last, content: last.content + (msg.content as string) }]
          }
          return [...prev, { role: 'assistant', content: msg.content as string, tools: [], streaming: true }]
        })
        scrollToBottom()
      } else if (msg.type === 'done') {
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last?.role === 'assistant') {
            return [...prev.slice(0, -1), { ...last, streaming: false, traceId: msg.trace_id as string }]
          }
          return prev
        })
        setRunning(false)
      } else if (msg.type === 'stopped') {
        setRunning(false)
      } else if (msg.type === 'error') {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: `Error: ${msg.message as string}`, tools: [], streaming: false },
        ])
        setRunning(false)
      }
    }

    ws.onerror = () => {
      setRunning(false)
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Error: WebSocket connection failed.', tools: [], streaming: false },
      ])
    }

    ws.onclose = () => {
      setLaunched(false)
      setRunning(false)
      setMessages([])
      wsRef.current = null
    }

    wsRef.current = ws
  }, [id])

  function handleSend() {
    if (!chatInput.trim() || !wsRef.current || running) return
    const content = chatInput.trim()
    setMessages((prev) => [...prev, { role: 'user', content, tools: [] }])
    setChatInput('')
    setRunning(true)
    wsRef.current.send(JSON.stringify({ type: 'message', content }))
    scrollToBottom()
  }

  function handleStop() {
    wsRef.current?.send(JSON.stringify({ type: 'stop' }))
    // running stays true until the server sends "stopped" or "error"
  }

  function handleDisconnect() {
    wsRef.current?.close()
    // messages are cleared in ws.onclose to avoid clearing while user is still reading
  }

  // ── Divider drag
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
                    className={`${inputCls} w-28 shrink-0`}
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

          {/* Knowledge Base */}
          <Block title="Knowledge Base">
            {/* Embedding key — only shown for non-OpenAI providers */}
            {(() => {
              const provider = llmConfigs.find((c) => c.id === agent.llm_config_id)?.provider
              if (!provider) return (
                <p className="text-xs text-muted-foreground">Configure an LLM above to enable the Knowledge Base.</p>
              )
              if (provider === 'openai') return (
                <p className="text-xs text-muted-foreground">Embeddings: using your configured OpenAI key.</p>
              )
              return (
                <Field label="OpenAI API key for embeddings (text-embedding-3-small)">
                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={embeddingKey}
                      onChange={(e) => setEmbeddingKey(e.target.value)}
                      className={`${inputCls} flex-1`}
                      placeholder="sk-… (write-only, never displayed)"
                    />
                    <button
                      onClick={saveEmbeddingKey}
                      disabled={savingEmbKey || !embeddingKey.trim()}
                      className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-40 shrink-0"
                    >
                      {embKeySaved ? 'Saved ✓' : savingEmbKey ? 'Saving…' : 'Save key'}
                    </button>
                  </div>
                </Field>
              )
            })()}

            {/* Chunk settings */}
            <div className="grid grid-cols-2 gap-3">
              <Field label="Chunk size (tokens)">
                <input
                  type="number"
                  value={agent.kb_chunk_size}
                  onChange={(e) => update({ kb_chunk_size: Number(e.target.value) })}
                  className={inputCls}
                  min={64}
                />
              </Field>
              <Field label="Chunk overlap (tokens)">
                <input
                  type="number"
                  value={agent.kb_chunk_overlap}
                  onChange={(e) => update({ kb_chunk_overlap: Number(e.target.value) })}
                  className={inputCls}
                  min={0}
                />
              </Field>
              <Field label="Top-K results">
                <input
                  type="number"
                  value={agent.kb_top_k}
                  onChange={(e) => update({ kb_top_k: Number(e.target.value) })}
                  className={inputCls}
                  min={1}
                  max={20}
                />
              </Field>
              <Field label="Similarity threshold">
                <input
                  type="number"
                  value={agent.kb_similarity_threshold}
                  onChange={(e) => update({ kb_similarity_threshold: Number(e.target.value) })}
                  className={inputCls}
                  min={0}
                  max={1}
                  step={0.05}
                />
              </Field>
            </div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={agent.kb_show_sources}
                onChange={(e) => update({ kb_show_sources: e.target.checked })}
                className="h-4 w-4"
              />
              <span className="text-xs">Show source attribution in results</span>
            </label>

            {/* Drop zone */}
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => { e.preventDefault(); setDragOver(false); handleUpload(e.dataTransfer.files) }}
              onClick={() => fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-md p-5 text-center cursor-pointer text-xs text-muted-foreground transition-colors
                ${dragOver ? 'border-ring bg-secondary' : 'border-border hover:border-ring'}`}
            >
              {uploading ? 'Uploading…' : 'Drop PDF, TXT, DOCX, or MD — or click to browse'}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.txt,.md,.docx"
              multiple
              className="hidden"
              onChange={(e) => e.target.files && handleUpload(e.target.files)}
            />

            {/* Source list */}
            {sources.length > 0 && (
              <div className="space-y-1.5">
                {sources.map((src) => (
                  <div key={src.id} className="space-y-0.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs truncate flex-1">{src.name}</span>
                      <div className="flex items-center gap-2 shrink-0">
                        {(src.status === 'pending' || src.status === 'indexing') && (
                          <span className="text-xs text-yellow-400 animate-pulse">indexing…</span>
                        )}
                        {src.status === 'ready' && (
                          <span className="text-xs text-green-400">{src.chunk_count} chunks</span>
                        )}
                        {src.status === 'error' && (
                          <span className="text-xs text-destructive">error</span>
                        )}
                        <button
                          onClick={() => deleteSource(src.id)}
                          className="text-xs text-muted-foreground hover:text-destructive"
                        >
                          ✕
                        </button>
                      </div>
                    </div>
                    {src.status === 'error' && src.error_message && (
                      <p className="text-xs text-destructive pl-1">{src.error_message}</p>
                    )}
                  </div>
                ))}
              </div>
            )}
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
              <Field label="Retention (days)">
                <input
                  type="number"
                  value={agent.retention_days}
                  onChange={(e) => update({ retention_days: Number(e.target.value) })}
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

            {/* Stored memories — visible only when long-term is enabled */}
            {agent.long_term_enabled && (
              <div className="space-y-2 pt-1">
                <p className="text-xs text-muted-foreground border-t border-border pt-2">Stored memories</p>
                {memories.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No memories stored yet.</p>
                ) : (
                  <div className="space-y-1">
                    {memories.map((m) => (
                      <div key={m.id} className="flex items-start justify-between gap-2">
                        <span className="text-xs flex-1">
                          <span className="text-muted-foreground">[{m.memory_type}]</span>{' '}
                          {m.content.length > 80 ? m.content.slice(0, 80) + '…' : m.content}
                        </span>
                        <button
                          onClick={() => deleteMemory(m.id)}
                          className="text-xs text-muted-foreground hover:text-destructive shrink-0"
                        >
                          ✕
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
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

        {/* Chat toolbar */}
        <div className="flex items-center justify-between border-b border-border px-4 py-2 shrink-0">
          <span className="text-xs text-muted-foreground">
            {launched ? 'Chat console' : 'Chat console — not started'}
          </span>
          <div className="flex items-center gap-3">
            {launched && running && (
              <button onClick={handleStop} className="text-xs text-destructive hover:opacity-80">
                ■ Stop
              </button>
            )}
            {launched && (
              <button
                onClick={handleDisconnect}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                Disconnect
              </button>
            )}
          </div>
        </div>

        {!launched ? (
          /* Launch state */
          <div className="flex flex-1 items-center justify-center text-center px-8">
            <div className="space-y-3 max-w-xs">
              <p className="text-sm text-muted-foreground">
                {agent.llm_config_id
                  ? 'Agent configured. Ready to launch.'
                  : 'Select an LLM in the builder before launching.'}
              </p>
              <button
                onClick={handleLaunch}
                disabled={!agent.llm_config_id}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                ▶ Launch agent
              </button>
            </div>
          </div>
        ) : (
          <>
            {/* Message list */}
            <div
              ref={chatScrollRef}
              className="flex-1 overflow-y-auto px-4 py-4 space-y-4 select-text"
            >
              {messages.length === 0 && (
                <p className="text-xs text-muted-foreground text-center pt-8">
                  Session started. Send a message to begin.
                </p>
              )}
              {messages.map((msg, i) => (
                <div key={i} className={msg.role === 'user' ? 'flex justify-end' : ''}>
                  {msg.role === 'user' ? (
                    <span className="inline-block bg-secondary px-3 py-1.5 rounded-md text-sm max-w-[80%]">
                      {msg.content}
                    </span>
                  ) : (
                    <div className="space-y-1.5 max-w-[90%]">
                      {/* Tool activity */}
                      {msg.tools.map((t) => (
                        <div key={t.id} className="text-xs font-mono text-muted-foreground">
                          <span className="text-primary">[{t.name}]</span>
                          {t.result !== undefined
                            ? ` → ${t.result.slice(0, 100)}${t.result.length > 100 ? '…' : ''}`
                            : ' running…'}
                        </div>
                      ))}
                      {/* Response text */}
                      {(msg.content || msg.streaming) && (
                        <p className="text-sm whitespace-pre-wrap">
                          {msg.content}
                          {msg.streaming && <span className="animate-pulse">▋</span>}
                        </p>
                      )}
                      {/* Trace link */}
                      {msg.traceId && (
                        <button
                          onClick={() => navigate(`/traces/${msg.traceId}`)}
                          className="text-xs text-muted-foreground hover:text-foreground underline"
                        >
                          [trace]
                        </button>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* Input area */}
            <div className="border-t border-border px-4 py-3 shrink-0">
              <div className="flex gap-2">
                <input
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      handleSend()
                    }
                  }}
                  placeholder="Type a message…"
                  disabled={running}
                  className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
                />
                <button
                  onClick={running ? handleStop : handleSend}
                  disabled={!running && !chatInput.trim()}
                  className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-40"
                >
                  {running ? '■' : 'Send'}
                </button>
              </div>
            </div>
          </>
        )}

      </div>

    </div>
  )
}
