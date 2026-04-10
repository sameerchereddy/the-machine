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
  role: 'user' | 'assistant' | 'system'
  content: string
  tools: ToolActivity[]
  traceId?: string
  streaming?: boolean
}

type Tool = {
  id: string
  agent_id: string
  tool_key: string
  name: string
  description: string
  parameters: Record<string, unknown>
  enabled: boolean
  timeout_seconds: number
  max_calls_per_run: number
  retry_on_failure: boolean
  show_result_in_chat: boolean
  result_truncation_chars: number
  has_credentials: boolean
  endpoint_url: string | null
  sort_order: number
}

// ---------------------------------------------------------------------------
// Node layout constants
// ---------------------------------------------------------------------------

const BLOCK_POS = {
  instructions: { cx: 26, cy: 16 },
  context:      { cx: 50, cy: 16 },
  knowledge:    { cx: 74, cy: 16 },
  llm:          { cx: 10, cy: 50 },
  agent:        { cx: 50, cy: 50 },
  memory:       { cx: 90, cy: 50 },
  guardrails:   { cx: 74, cy: 82 },
} as const

function toolPositions(count: number): Array<{cx: number; cy: number}> {
  if (count === 0) return []
  const positions: Array<{cx: number; cy: number}> = []
  const startX = 10, endX = 50
  const step = count === 1 ? 0 : (endX - startX) / (count - 1)
  for (let i = 0; i < count; i++) {
    positions.push({ cx: startX + i * step, cy: 82 })
  }
  return positions
}

// ---------------------------------------------------------------------------
// Field helpers
// ---------------------------------------------------------------------------

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</label>
      {children}
    </div>
  )
}

const inputCls = 'w-full rounded border border-input bg-background px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring'
const selectCls = 'w-full rounded border border-input bg-background px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring'

// ---------------------------------------------------------------------------
// SVG Connection Lines
// ---------------------------------------------------------------------------

// Map block keys to the tool names the WS emits for them
const BLOCK_ACTIVE_KEY: Record<string, string> = {
  llm:          'llm',
  instructions: 'instructions',
  context:      'context',
  knowledge:    'knowledge_search',
  memory:       'save_memory',
  guardrails:   'guardrails',
}

/**
 * Routed bezier path from a block (bx,by) to the agent (ax,ay).
 * Signals exit vertically from top/bottom blocks and horizontally
 * from left/right blocks, then curve to the agent — like a proper
 * block-diagram connector, not a straight radial spoke.
 */
function routedPath(bx: number, by: number, ax: number, ay: number): string {
  const dx = bx - ax   // +: block is right of agent
  const dy = by - ay   // +: block is below agent
  const s = 0.5        // bezier stretch (0–1)

  // Bias toward vertical routing for diagonally-placed blocks
  const useVertical = Math.abs(dy) > Math.abs(dx) * 0.55

  if (useVertical) {
    // Exit straight up/down from block, curve to agent's horizontal centre
    const cy1 = by - dy * s   // control pt 1: same x as block, toward midpoint
    const cy2 = ay + dy * s   // control pt 2: same x as agent, toward midpoint
    return `M ${bx} ${by} C ${bx} ${cy1}, ${ax} ${cy2}, ${ax} ${ay}`
  } else {
    // Exit straight left/right from block, curve to agent's vertical centre
    const cx1 = bx - dx * s
    const cx2 = ax + dx * s
    return `M ${bx} ${by} C ${cx1} ${by}, ${cx2} ${ay}, ${ax} ${ay}`
  }
}

function ConnectionLines({
  tools, running, activeNodeKey,
}: {
  tools: Tool[]
  running: boolean
  activeNodeKey: string | null
}) {
  const ax = BLOCK_POS.agent.cx
  const ay = BLOCK_POS.agent.cy

  const blockKeys = ['llm', 'instructions', 'context', 'knowledge', 'memory', 'guardrails'] as const
  const tPositions = toolPositions(tools.length)

  type Conn = { id: string; activeKey: string; d: string; disabled?: boolean }

  const conns: Conn[] = [
    ...blockKeys.map(key => ({
      id: `b-${key}`,
      activeKey: BLOCK_ACTIVE_KEY[key],
      d: routedPath(BLOCK_POS[key].cx, BLOCK_POS[key].cy, ax, ay),
    })),
    ...tPositions.map((pos, i) => ({
      id: `t-${tools[i]?.id ?? i}`,
      activeKey: tools[i]?.tool_key ?? '',
      d: routedPath(pos.cx, pos.cy, ax, ay),
      disabled: !tools[i]?.enabled,
    })),
  ]

  return (
    <svg
      className="absolute inset-0 w-full h-full pointer-events-none"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      style={{ zIndex: 0 }}
    >
      <defs>
        {/* Path shapes used by animateMotion dots */}
        {conns.map(c => <path key={c.id} id={c.id} d={c.d} />)}
      </defs>

      {/* Connector paths — always visible, routed bezier curves */}
      {conns.map(c => {
        const isActive = running && activeNodeKey === c.activeKey
        return (
          <path
            key={c.id}
            d={c.d}
            fill="none"
            vectorEffect="non-scaling-stroke"
            style={{
              stroke: isActive
                ? 'hsl(var(--primary))'
                : running
                  ? 'hsl(var(--primary) / 0.35)'
                  : 'hsl(var(--foreground) / 0.3)',
              strokeWidth: isActive ? 2 : 1.5,
              strokeDasharray: c.disabled ? '5 5' : undefined,
              transition: 'stroke 0.3s, stroke-width 0.3s',
            }}
          />
        )
      })}

      {/* Signal dots travel along each connector when the agent is running */}
      {running && conns.map(c => {
        if (c.disabled) return null
        const isActive = activeNodeKey === c.activeKey
        return (
          <circle
            key={`dot-${c.id}`}
            r={isActive ? 1.3 : 0.7}
            style={{ fill: isActive ? 'hsl(var(--primary))' : 'hsl(var(--primary) / 0.45)' }}
          >
            <animateMotion dur={isActive ? '0.65s' : '3s'} repeatCount="indefinite">
              <mpath href={`#${c.id}`} />
            </animateMotion>
          </circle>
        )
      })}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Block node card
// ---------------------------------------------------------------------------

function BlockNode({
  cx, cy, label, summary, selected, active, animClass, delay, onClick,
}: {
  cx: number; cy: number; label: string; summary: string
  selected: boolean; active: boolean; animClass: string; delay: number
  onClick: () => void
}) {
  return (
    <div
      style={{ left: `${cx}%`, top: `${cy}%`, transform: 'translate(-50%,-50%)', animationDelay: `${delay}ms`, zIndex: 1 }}
      className={[
        'absolute w-24 cursor-pointer rounded border px-2.5 py-2 text-center select-none transition-all duration-200',
        animClass,
        selected
          ? 'border-primary bg-primary/10 ring-1 ring-primary'
          : 'border-border bg-background hover:border-ring',
        active
          ? 'border-primary bg-primary/10 ring-2 ring-primary animate-node-glow'
          : '',
      ].filter(Boolean).join(' ')}
      onClick={onClick}
    >
      <p className="text-[11px] font-semibold leading-tight">{label}</p>
      <p className="mt-0.5 text-[10px] text-muted-foreground truncate max-w-[80px]">{summary}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Agent center node
// ---------------------------------------------------------------------------

function AgentCenterNode({ name, running, active }: { name: string; running: boolean; active: boolean }) {
  return (
    <div
      style={{ left: '50%', top: '50%', transform: 'translate(-50%,-50%)', animationDelay: '0ms', zIndex: 1 }}
      className={[
        'absolute w-32 cursor-default rounded-lg border-2 px-3 py-2.5 text-center select-none transition-all duration-200 animate-scale-in',
        running || active
          ? 'border-primary bg-primary/5 shadow-[0_0_32px_hsl(var(--primary)/0.3)]'
          : 'border-primary/40 bg-background',
        active ? 'animate-node-glow' : '',
      ].filter(Boolean).join(' ')}
    >
      <p className="text-[10px] text-muted-foreground tracking-widest">◈ AGENT ◈</p>
      <p className="mt-0.5 text-sm font-semibold truncate max-w-[100px]">{name}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tool node
// ---------------------------------------------------------------------------

function ToolNode({
  tool, cx, cy, selected, active, delay, onClick, onToggle,
}: {
  tool: Tool; cx: number; cy: number
  selected: boolean; active: boolean; delay: number
  onClick: () => void; onToggle: () => void
}) {
  return (
    <div
      style={{ left: `${cx}%`, top: `${cy}%`, transform: 'translate(-50%,-50%)', animationDelay: `${delay}ms`, zIndex: 1 }}
      className={[
        'absolute w-20 cursor-pointer rounded border px-2 py-1.5 text-center select-none transition-all duration-200 animate-slide-from-bottom',
        tool.enabled
          ? selected
            ? 'border-primary bg-primary/10 ring-1 ring-primary'
            : 'border-border bg-background hover:border-ring'
          : 'border-dashed border-border/40 bg-background opacity-50',
        active ? 'border-primary bg-primary/10 ring-2 ring-primary animate-node-glow' : '',
      ].filter(Boolean).join(' ')}
      onClick={onClick}
    >
      <p className="text-[10px] font-medium leading-tight truncate">{tool.name}</p>
      <button
        onClick={(e) => { e.stopPropagation(); onToggle() }}
        className={`mt-1 text-[10px] transition-colors ${tool.enabled ? 'text-primary hover:text-primary/70' : 'text-muted-foreground hover:text-foreground'}`}
      >
        {tool.enabled ? '⚡ on' : '○ off'}
      </button>
    </div>
  )
}

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

  // Tools state
  const [tools, setTools] = useState<Tool[]>([])
  const [selectedBlock, setSelectedBlock] = useState<string | null>(null)
  const [showToolPicker, setShowToolPicker] = useState(false)

  // Canvas (no canvasRef/canvasSize — SVG uses viewBox="0 0 100 100" with % coords directly)

  // Chat state
  const [launched, setLaunched] = useState(false)
  const [running, setRunning] = useState(false)
  const [chatInput, setChatInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [activityText, setActivityText] = useState('')
  const [expandedToolCalls, setExpandedToolCalls] = useState<Set<string>>(new Set())
  const wsRef = useRef<WebSocket | null>(null)
  const chatScrollRef = useRef<HTMLDivElement | null>(null)

  // Mobile layout
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 768)
  const [mobileTab, setMobileTab] = useState<'builder' | 'chat'>('builder')

  // Active node tracking (which block is currently processing)
  const [activeNodeKey, setActiveNodeKey] = useState<string | null>(null)

  // Mid-session edit banner
  const [showEditBanner, setShowEditBanner] = useState(false)

  // Draggable divider
  const [splitPct, setSplitPct] = useState(55)
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

  useEffect(() => {
    function handleResize() { setIsMobile(window.innerWidth < 768) }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  useEffect(() => {
    if (saved && launched) setShowEditBanner(true)
  }, [saved, launched])


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
    await Promise.all([loadSources(), loadMemories(), loadTools()])
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

  async function loadTools() {
    const res = await fetch(`${API}/api/agents/${id}/tools`, { credentials: 'include' })
    if (res.ok) {
      const data: Tool[] = await res.json()
      if (data.length === 0) {
        // Seed defaults for old agents
        await fetch(`${API}/api/agents/${id}/tools/seed-defaults`, { method: 'POST', credentials: 'include' })
        const res2 = await fetch(`${API}/api/agents/${id}/tools`, { credentials: 'include' })
        if (res2.ok) setTools(await res2.json())
      } else {
        setTools(data)
      }
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

  async function toggleTool(tool: Tool) {
    const res = await fetch(`${API}/api/agents/${id}/tools/${tool.id}`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !tool.enabled }),
    })
    if (res.ok) {
      const updated: Tool = await res.json()
      setTools(prev => prev.map(t => t.id === tool.id ? updated : t))
    }
  }

  async function updateTool(toolId: string, patch: Partial<Tool>) {
    const res = await fetch(`${API}/api/agents/${id}/tools/${toolId}`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (res.ok) {
      const updated: Tool = await res.json()
      setTools(prev => prev.map(t => t.id === toolId ? updated : t))
    }
  }

  async function deleteTool(toolId: string) {
    const res = await fetch(`${API}/api/agents/${id}/tools/${toolId}`, {
      method: 'DELETE',
      credentials: 'include',
    })
    if (res.ok) {
      setTools(prev => prev.filter(t => t.id !== toolId))
      setSelectedBlock(null)
    }
  }

  const TOOL_DEFAULTS: Record<string, { name: string; description: string }> = {
    calculator:       { name: 'Calculator',  description: 'Evaluates a mathematical expression and returns the result.' },
    current_datetime: { name: 'Date & Time', description: 'Returns the current UTC date and time.' },
    url_reader:       { name: 'URL Reader',  description: 'Fetches a URL and extracts clean readable text.' },
    wikipedia_search: { name: 'Wikipedia',   description: 'Searches Wikipedia and returns the top article summary.' },
    web_search:       { name: 'Web Search',  description: 'Searches the web for real-time information.' },
  }

  async function handleAddTool(toolKey: string) {
    const defaults = TOOL_DEFAULTS[toolKey] ?? { name: toolKey, description: '' }
    const res = await fetch(`${API}/api/agents/${id}/tools`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool_key: toolKey, ...defaults, sort_order: tools.length }),
    })
    if (res.ok) {
      const newTool: Tool = await res.json()
      setTools(prev => [...prev, newTool])
      setShowToolPicker(false)
    }
  }

  // ── Chat ──────────────────────────────────────────────────────────────────

  function scrollToBottom() {
    chatScrollRef.current?.scrollTo({ top: chatScrollRef.current.scrollHeight, behavior: 'smooth' })
  }

  const handleLaunch = useCallback(() => {
    const ws = new WebSocket(`${API.replace(/^http/, 'ws')}/api/agents/${id}/run`)

    ws.onopen = () => {
      setLaunched(true)
      setActiveNodeKey(null)
      setMessages(prev => {
        const modelLabel = llmConfigs.find(c => c.id === agent?.llm_config_id)?.model ?? ''
        const time = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
        return [...prev, { role: 'system', content: `── session started · ${agent?.name ?? ''} · ${modelLabel} · ${time} ──`, tools: [], streaming: false }]
      })
    }

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data as string) as Record<string, unknown>

      if (msg.type === 'iteration') {
        setActivityText('thinking...')
        setActiveNodeKey('llm')
      } else if (msg.type === 'tool_start') {
        setActivityText(`calling ${msg.tool_name as string}...`)
        setActiveNodeKey(msg.tool_name as string)
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
        setActiveNodeKey('llm')
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last?.role === 'assistant') {
            const updatedTools = last.tools.map((t) =>
              t.id === msg.tool_id ? { ...t, result: msg.result as string } : t,
            )
            return [...prev.slice(0, -1), { ...last, tools: updatedTools }]
          }
          return prev
        })
      } else if (msg.type === 'delta') {
        setActiveNodeKey('llm')
        if (activityText.startsWith('calling')) setActivityText('synthesising...')
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last?.role === 'assistant' && last.streaming) {
            return [...prev.slice(0, -1), { ...last, content: last.content + (msg.content as string) }]
          }
          return [...prev, { role: 'assistant', content: msg.content as string, tools: [], streaming: true }]
        })
        scrollToBottom()
      } else if (msg.type === 'done') {
        setActivityText('')
        setActiveNodeKey(null)
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last?.role === 'assistant') {
            return [...prev.slice(0, -1), { ...last, streaming: false, traceId: msg.trace_id as string }]
          }
          return prev
        })
        setRunning(false)
      } else if (msg.type === 'stopped') {
        setActivityText('')
        setActiveNodeKey(null)
        setRunning(false)
      } else if (msg.type === 'error') {
        setActivityText('')
        setActiveNodeKey(null)
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: `Error: ${msg.message as string}`, tools: [], streaming: false },
        ])
        setRunning(false)
      }
    }

    ws.onerror = () => {
      setActivityText('')
      setRunning(false)
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Error: WebSocket connection failed.', tools: [], streaming: false },
      ])
    }

    ws.onclose = () => {
      setLaunched(false)
      setRunning(false)
      setActiveNodeKey(null)
      setActivityText('')
      setMessages([])
      wsRef.current = null
    }

    wsRef.current = ws
  }, [id, activityText])

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
  }

  function handleDisconnect() {
    wsRef.current?.close()
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

  // ── Config panel helpers

  function getBlockLabel(block: string): string {
    if (block === 'llm') return 'LLM'
    if (block === 'instructions') return 'Instructions'
    if (block === 'context') return 'Context'
    if (block === 'knowledge') return 'Knowledge'
    if (block === 'memory') return 'Memory'
    if (block === 'guardrails') return 'Guardrails'
    const tool = tools.find(t => t.id === block)
    return tool ? tool.name : 'Config'
  }

  function renderConfigPanel() {
    if (!agent) return null

    if (selectedBlock === 'llm') {
      return (
        <div className="space-y-3">
          <Field label="Provider config">
            <select value={agent.llm_config_id ?? ''} onChange={(e) => update({ llm_config_id: e.target.value || null })} className={selectCls}>
              <option value="">— none —</option>
              {llmConfigs.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.provider} · {c.model})</option>)}
            </select>
          </Field>
          {llmConfigs.length === 0 && (
            <p className="text-xs text-muted-foreground">No LLM configs. <button onClick={() => navigate('/setup')} className="underline">Add one →</button></p>
          )}
        </div>
      )
    }

    if (selectedBlock === 'instructions') {
      return (
        <div className="space-y-3">
          <Field label="System prompt">
            <textarea
              rows={3}
              value={agent.instructions}
              onChange={(e) => update({ instructions: e.target.value })}
              className={`${inputCls} resize-none`}
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
          <div className="grid grid-cols-2 gap-2">
            <Field label="Response style">
              <select value={agent.response_style} onChange={(e) => update({ response_style: e.target.value })} className={selectCls}>
                <option value="concise">Concise</option>
                <option value="balanced">Balanced</option>
                <option value="verbose">Verbose</option>
              </select>
            </Field>
            <Field label="Output format">
              <select value={agent.output_format} onChange={(e) => update({ output_format: e.target.value })} className={selectCls}>
                <option value="markdown">Markdown</option>
                <option value="plain_text">Plain text</option>
                <option value="json">JSON</option>
              </select>
            </Field>
            <Field label="Language">
              <input type="text" value={agent.response_language} onChange={(e) => update({ response_language: e.target.value })} className={inputCls} placeholder="en" />
            </Field>
            <Field label="Show reasoning">
              <label className="flex items-center gap-2 pt-1 cursor-pointer">
                <input type="checkbox" checked={agent.show_reasoning} onChange={(e) => update({ show_reasoning: e.target.checked })} className="h-3.5 w-3.5" />
                <span className="text-xs">Enabled</span>
              </label>
            </Field>
          </div>
        </div>
      )
    }

    if (selectedBlock === 'context') {
      return (
        <div className="space-y-3">
          <div className="space-y-1.5">
            {agent.context_entries.map((entry, i) => (
              <div key={i} className="flex gap-1.5">
                <input
                  type="text"
                  value={entry.key}
                  onChange={(e) => {
                    const entries = [...agent.context_entries]
                    entries[i] = { ...entries[i], key: e.target.value }
                    update({ context_entries: entries })
                  }}
                  className={`${inputCls} w-24 shrink-0`}
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
          <div className="flex gap-3">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={agent.auto_inject_datetime} onChange={(e) => update({ auto_inject_datetime: e.target.checked })} className="h-3.5 w-3.5" />
              <span className="text-xs">Inject date/time</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={agent.auto_inject_user_profile} onChange={(e) => update({ auto_inject_user_profile: e.target.checked })} className="h-3.5 w-3.5" />
              <span className="text-xs">Inject user profile</span>
            </label>
          </div>
        </div>
      )
    }

    if (selectedBlock === 'knowledge') {
      const provider = llmConfigs.find((c) => c.id === agent.llm_config_id)?.provider
      return (
        <div className="space-y-3">
          {!provider && (
            <p className="text-xs text-muted-foreground">Configure an LLM to enable Knowledge Base.</p>
          )}
          {provider && provider !== 'openai' && (
            <Field label="OpenAI API key for embeddings">
              <div className="flex gap-1.5">
                <input
                  type="password"
                  value={embeddingKey}
                  onChange={(e) => setEmbeddingKey(e.target.value)}
                  className={`${inputCls} flex-1`}
                  placeholder="sk-…"
                />
                <button
                  onClick={saveEmbeddingKey}
                  disabled={savingEmbKey || !embeddingKey.trim()}
                  className="rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-40 shrink-0"
                >
                  {embKeySaved ? 'Saved ✓' : savingEmbKey ? 'Saving…' : 'Save'}
                </button>
              </div>
            </Field>
          )}
          {provider === 'openai' && (
            <p className="text-xs text-muted-foreground">Embeddings: using your OpenAI key.</p>
          )}
          <div className="grid grid-cols-2 gap-2">
            <Field label="Chunk size (tokens)">
              <input type="number" value={agent.kb_chunk_size} onChange={(e) => update({ kb_chunk_size: Number(e.target.value) })} className={inputCls} min={64} />
            </Field>
            <Field label="Chunk overlap">
              <input type="number" value={agent.kb_chunk_overlap} onChange={(e) => update({ kb_chunk_overlap: Number(e.target.value) })} className={inputCls} min={0} />
            </Field>
            <Field label="Top-K results">
              <input type="number" value={agent.kb_top_k} onChange={(e) => update({ kb_top_k: Number(e.target.value) })} className={inputCls} min={1} max={20} />
            </Field>
            <Field label="Similarity threshold">
              <input type="number" value={agent.kb_similarity_threshold} onChange={(e) => update({ kb_similarity_threshold: Number(e.target.value) })} className={inputCls} min={0} max={1} step={0.05} />
            </Field>
          </div>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={agent.kb_show_sources} onChange={(e) => update({ kb_show_sources: e.target.checked })} className="h-3.5 w-3.5" />
            <span className="text-xs">Show source attribution</span>
          </label>
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); handleUpload(e.dataTransfer.files) }}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded p-3 text-center cursor-pointer text-xs text-muted-foreground transition-colors
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
          {sources.length > 0 && (
            <div className="space-y-1">
              {sources.map((src) => (
                <div key={src.id} className="space-y-0.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs truncate flex-1">{src.name}</span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {(src.status === 'pending' || src.status === 'indexing') && (
                        <span className="text-[10px] text-yellow-400 animate-pulse">indexing…</span>
                      )}
                      {src.status === 'ready' && (
                        <span className="text-[10px] text-green-400">{src.chunk_count} chunks</span>
                      )}
                      {src.status === 'error' && (
                        <span className="text-[10px] text-destructive">error</span>
                      )}
                      <button onClick={() => deleteSource(src.id)} className="text-[10px] text-muted-foreground hover:text-destructive">✕</button>
                    </div>
                  </div>
                  {src.status === 'error' && src.error_message && (
                    <p className="text-[10px] text-destructive pl-1">{src.error_message}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )
    }

    if (selectedBlock === 'memory') {
      return (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <Field label="History window (turns)">
              <input type="number" value={agent.history_window} onChange={(e) => update({ history_window: Number(e.target.value) })} className={inputCls} min={1} />
            </Field>
            <Field label="Max memories">
              <input type="number" value={agent.max_memories} onChange={(e) => update({ max_memories: Number(e.target.value) })} className={inputCls} min={1} />
            </Field>
            <Field label="Retention (days)">
              <input type="number" value={agent.retention_days} onChange={(e) => update({ retention_days: Number(e.target.value) })} className={inputCls} min={1} />
            </Field>
          </div>
          <div className="flex gap-3">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={agent.summarise_old_messages} onChange={(e) => update({ summarise_old_messages: e.target.checked })} className="h-3.5 w-3.5" />
              <span className="text-xs">Summarise old messages</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={agent.long_term_enabled} onChange={(e) => update({ long_term_enabled: e.target.checked })} className="h-3.5 w-3.5" />
              <span className="text-xs">Long-term memory</span>
            </label>
          </div>
          {agent.long_term_enabled && (
            <div className="space-y-1 pt-1 border-t border-border">
              <p className="text-[10px] text-muted-foreground">Stored memories</p>
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
                      <button onClick={() => deleteMemory(m.id)} className="text-xs text-muted-foreground hover:text-destructive shrink-0">✕</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )
    }

    if (selectedBlock === 'guardrails') {
      return (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <Field label="Max iterations">
              <input type="number" value={agent.max_iterations} onChange={(e) => update({ max_iterations: Number(e.target.value) })} className={inputCls} min={1} />
            </Field>
            <Field label="On max iterations">
              <select value={agent.on_max_iterations} onChange={(e) => update({ on_max_iterations: e.target.value })} className={selectCls}>
                <option value="return_partial">Return partial</option>
                <option value="fail_with_message">Fail with message</option>
                <option value="ask_user">Ask user</option>
              </select>
            </Field>
            <Field label="Max tool calls/run">
              <input type="number" value={agent.max_tool_calls_per_run} onChange={(e) => update({ max_tool_calls_per_run: Number(e.target.value) })} className={inputCls} min={1} />
            </Field>
            <Field label="Max tokens/run">
              <input type="number" value={agent.max_tokens_per_run} onChange={(e) => update({ max_tokens_per_run: Number(e.target.value) })} className={inputCls} min={1} />
            </Field>
          </div>
          <div className="flex gap-3 flex-wrap">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={agent.allow_clarifying_questions} onChange={(e) => update({ allow_clarifying_questions: e.target.checked })} className="h-3.5 w-3.5" />
              <span className="text-xs">Allow clarifying questions</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={agent.pii_detection} onChange={(e) => update({ pii_detection: e.target.checked })} className="h-3.5 w-3.5" />
              <span className="text-xs">PII detection</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={agent.safe_tool_mode} onChange={(e) => update({ safe_tool_mode: e.target.checked })} className="h-3.5 w-3.5" />
              <span className="text-xs">Safe tool mode</span>
            </label>
          </div>
        </div>
      )
    }

    // Tool panel
    const tool = tools.find(t => t.id === selectedBlock)
    if (tool) {
      return (
        <div className="space-y-3">
          <Field label="Name">
            <input
              type="text"
              value={tool.name}
              onChange={(e) => updateTool(tool.id, { name: e.target.value })}
              className={inputCls}
            />
          </Field>
          <Field label="Description">
            <textarea
              rows={2}
              value={tool.description}
              onChange={(e) => updateTool(tool.id, { description: e.target.value })}
              className={`${inputCls} resize-none`}
            />
          </Field>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={tool.enabled}
                onChange={() => toggleTool(tool)}
                className="h-3.5 w-3.5"
              />
              <span className="text-xs">Enabled</span>
            </label>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Timeout (s)">
              <input type="number" value={tool.timeout_seconds} onChange={(e) => updateTool(tool.id, { timeout_seconds: Number(e.target.value) })} className={inputCls} min={1} />
            </Field>
            <Field label="Max calls/run">
              <input type="number" value={tool.max_calls_per_run} onChange={(e) => updateTool(tool.id, { max_calls_per_run: Number(e.target.value) })} className={inputCls} min={1} />
            </Field>
          </div>
          <div className="flex gap-3">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={tool.retry_on_failure} onChange={(e) => updateTool(tool.id, { retry_on_failure: e.target.checked })} className="h-3.5 w-3.5" />
              <span className="text-xs">Retry on failure</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={tool.show_result_in_chat} onChange={(e) => updateTool(tool.id, { show_result_in_chat: e.target.checked })} className="h-3.5 w-3.5" />
              <span className="text-xs">Show result in chat</span>
            </label>
          </div>
          <button
            onClick={() => {
              if (window.confirm(`Remove tool "${tool.name}"?`)) deleteTool(tool.id)
            }}
            className="text-xs text-destructive hover:opacity-80"
          >
            Delete tool
          </button>
        </div>
      )
    }

    return null
  }

  // ── Render

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
        className={`flex flex-col overflow-hidden border-r border-border${isMobile && mobileTab !== 'builder' ? ' hidden' : ''}`}
        style={isMobile ? { width: '100%' } : { width: `${splitPct}%` }}
      >
        {/* Toolbar */}
        <div className="flex items-center justify-between border-b border-border px-4 py-2 shrink-0">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/agents')} className="text-xs text-muted-foreground hover:text-foreground">← Agents</button>
            <input
              value={agent.name}
              onChange={(e) => update({ name: e.target.value })}
              className="bg-transparent text-sm font-medium focus:outline-none border-b border-transparent focus:border-border w-40"
            />
          </div>
          <div className="flex items-center gap-2">
            {error && <span className="text-xs text-destructive max-w-[120px] truncate">{error}</span>}
            {saved && <span className="text-xs text-green-400">Saved</span>}
            <button onClick={handleDelete} disabled={deleting} className="text-xs text-muted-foreground hover:text-destructive disabled:opacity-40">{deleting ? 'Deleting…' : 'Delete'}</button>
            <button onClick={save} disabled={saving} className="rounded bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50">{saving ? 'Saving…' : 'Save'}</button>
          </div>
        </div>

        {/* Canvas area */}
        <div className="relative flex-1 min-h-0 overflow-hidden">
          {/* SVG connection lines */}
          <ConnectionLines tools={tools} running={running} activeNodeKey={activeNodeKey} />

          {/* Block nodes */}
          <BlockNode cx={BLOCK_POS.llm.cx} cy={BLOCK_POS.llm.cy} label="LLM"
            summary={llmConfigs.find(c => c.id === agent.llm_config_id)?.model ?? 'not set'}
            selected={selectedBlock === 'llm'} active={activeNodeKey === 'llm'}
            animClass="animate-slide-from-left" delay={40}
            onClick={() => setSelectedBlock(selectedBlock === 'llm' ? null : 'llm')} />

          <BlockNode cx={BLOCK_POS.instructions.cx} cy={BLOCK_POS.instructions.cy} label="Instructions"
            summary={agent.instructions ? agent.instructions.slice(0, 24) + '…' : 'empty'}
            selected={selectedBlock === 'instructions'} active={activeNodeKey === 'instructions'}
            animClass="animate-slide-from-top" delay={80}
            onClick={() => setSelectedBlock(selectedBlock === 'instructions' ? null : 'instructions')} />

          <BlockNode cx={BLOCK_POS.context.cx} cy={BLOCK_POS.context.cy} label="Context"
            summary={`${agent.context_entries.length} entries`}
            selected={selectedBlock === 'context'} active={activeNodeKey === 'context'}
            animClass="animate-slide-from-top" delay={120}
            onClick={() => setSelectedBlock(selectedBlock === 'context' ? null : 'context')} />

          <BlockNode cx={BLOCK_POS.knowledge.cx} cy={BLOCK_POS.knowledge.cy} label="Knowledge"
            summary={`${sources.length} source${sources.length !== 1 ? 's' : ''}`}
            selected={selectedBlock === 'knowledge'} active={activeNodeKey === 'knowledge_search'}
            animClass="animate-slide-from-top" delay={160}
            onClick={() => setSelectedBlock(selectedBlock === 'knowledge' ? null : 'knowledge')} />

          <AgentCenterNode name={agent.name} running={running} active={activeNodeKey === 'llm'} />

          <BlockNode cx={BLOCK_POS.memory.cx} cy={BLOCK_POS.memory.cy} label="Memory"
            summary={agent.long_term_enabled ? `${memories.length} stored` : 'short-term only'}
            selected={selectedBlock === 'memory'} active={activeNodeKey === 'save_memory'}
            animClass="animate-slide-from-right" delay={200}
            onClick={() => setSelectedBlock(selectedBlock === 'memory' ? null : 'memory')} />

          <BlockNode cx={BLOCK_POS.guardrails.cx} cy={BLOCK_POS.guardrails.cy} label="Guardrails"
            summary={`${agent.max_iterations} iter max`}
            selected={selectedBlock === 'guardrails'} active={false}
            animClass="animate-slide-from-bottom" delay={240}
            onClick={() => setSelectedBlock(selectedBlock === 'guardrails' ? null : 'guardrails')} />

          {/* Tool nodes */}
          {toolPositions(tools.length).map((pos, i) => {
            const tool = tools[i]
            return (
              <ToolNode
                key={tool.id}
                tool={tool}
                cx={pos.cx} cy={pos.cy}
                selected={selectedBlock === tool.id}
                active={activeNodeKey === tool.tool_key}
                delay={260 + i * 20}
                onClick={() => setSelectedBlock(selectedBlock === tool.id ? null : tool.id)}
                onToggle={() => toggleTool(tool)}
              />
            )
          })}

          {/* Add tool button */}
          <button
            style={{ left: '62%', top: '82%', transform: 'translate(-50%,-50%)', animationDelay: '320ms', zIndex: 1 }}
            className="absolute w-16 animate-fade-in-up cursor-pointer rounded border border-dashed border-border/40 px-2 py-1.5 text-center text-[10px] text-muted-foreground transition-all hover:border-ring hover:text-foreground"
            onClick={() => setShowToolPicker(true)}
          >
            + add
          </button>

          {/* Tool picker */}
          {showToolPicker && (() => {
            const BUILTIN_KEYS = ['calculator','current_datetime','url_reader','wikipedia_search','web_search']
            const addableKeys = BUILTIN_KEYS.filter(k => !tools.some(t => t.tool_key === k))
            return (
              <div
                className="absolute rounded-md border border-border bg-background p-3 shadow-lg"
                style={{ left: '60%', top: '60%', transform: 'translate(-50%,-50%)', zIndex: 10, minWidth: '160px' }}
              >
                <div className="flex items-center justify-between mb-2">
                  <p className="text-[11px] font-semibold">Add tool</p>
                  <button onClick={() => setShowToolPicker(false)} className="text-[10px] text-muted-foreground hover:text-foreground">✕</button>
                </div>
                {addableKeys.length === 0 ? (
                  <p className="text-[10px] text-muted-foreground">All tools added</p>
                ) : (
                  <div className="space-y-1">
                    {addableKeys.map(key => (
                      <button
                        key={key}
                        onClick={() => handleAddTool(key)}
                        className="block w-full rounded px-2 py-1 text-left text-[11px] text-muted-foreground hover:bg-secondary hover:text-foreground"
                      >
                        {key.replace(/_/g, ' ')}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )
          })()}

          {/* Launch / Disconnect button */}
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2" style={{ zIndex: 1 }}>
            {!launched ? (
              <button
                onClick={handleLaunch}
                disabled={!agent.llm_config_id}
                className="animate-fade-in-up rounded-md bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                ▶ Launch
              </button>
            ) : (
              <button
                onClick={handleDisconnect}
                className="animate-fade-in-up rounded-md border border-border px-5 py-2 text-sm text-muted-foreground hover:text-foreground hover:border-ring"
              >
                ■ Disconnect
              </button>
            )}
          </div>
        </div>

        {/* Config panel */}
        {selectedBlock && (
          <div className="h-56 border-t border-border flex flex-col shrink-0">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-border shrink-0">
              <p className="text-xs font-semibold">{getBlockLabel(selectedBlock)}</p>
              <button onClick={() => setSelectedBlock(null)} className="text-xs text-muted-foreground hover:text-foreground">✕</button>
            </div>
            {/* Content */}
            <div className="flex-1 overflow-y-auto px-4 py-3 select-text">
              {renderConfigPanel()}
            </div>
          </div>
        )}

      </div>

      {/* ── Drag handle ─────────────────────────────────────────── */}
      {!isMobile && (
        <div
          onMouseDown={onDividerMouseDown}
          className="w-1 cursor-col-resize bg-border hover:bg-ring transition-colors shrink-0"
        />
      )}

      {/* ── Chat panel (terminal) ────────────────────────────────── */}
      <div className={`flex flex-col flex-1 overflow-hidden bg-[#0a0a0a]${isMobile && mobileTab !== 'chat' ? ' hidden' : ''}`}>

        {/* Chat toolbar */}
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-2 shrink-0">
          <span className="text-[11px] font-mono text-white/30">
            {launched ? '● session active' : '○ not started'}
          </span>
          <div className="flex items-center gap-4">
            {launched && (
              <button onClick={handleDisconnect} className="text-[11px] font-mono text-white/30 hover:text-white/60">disconnect</button>
            )}
            <button onClick={() => navigate(`/traces?agent_id=${id}`)} className="text-[11px] font-mono text-white/30 hover:text-white/60">traces</button>
          </div>
        </div>

        {/* Mid-session edit banner */}
        {showEditBanner && launched && (
          <div className="flex items-center justify-between border-b border-yellow-400/20 bg-yellow-400/5 px-4 py-1.5 shrink-0">
            <p className="text-[11px] font-mono text-yellow-400/60">config changed — takes effect next message</p>
            <button onClick={() => setShowEditBanner(false)} className="text-[11px] text-yellow-400/40 hover:text-yellow-400/70">✕</button>
          </div>
        )}

        {!launched ? (
          <div className="flex flex-1 items-center justify-center">
            <div className="space-y-1 text-center font-mono">
              <p className="text-[11px] text-white/20">agent not running</p>
              <p className="text-[11px] text-white/10">
                {agent.llm_config_id ? 'configure blocks and click ▶ Launch' : 'add an LLM config to begin'}
              </p>
            </div>
          </div>
        ) : (
          <>
            {/* Message list */}
            <div ref={chatScrollRef} className="flex-1 overflow-y-auto py-4 select-text">
              {messages.length === 0 && (
                <p className="px-5 text-[11px] font-mono text-white/20">session started · send a message to begin</p>
              )}
              {messages.map((msg, i) => (
                <div key={i} className="px-5 py-1.5">
                  {msg.role === 'system' ? (
                    <p className="text-[10px] font-mono text-white/15 text-center py-1">{msg.content}</p>
                  ) : msg.role === 'user' ? (
                    <div className="flex items-start gap-3">
                      <span className="w-12 shrink-0 text-right text-[11px] font-mono text-white/30 pt-px">you</span>
                      <p className="flex-1 text-[13px] font-mono text-white/80 leading-relaxed">{msg.content}</p>
                    </div>
                  ) : (
                    <div className="flex items-start gap-3">
                      <span className="w-12 shrink-0 text-right text-[11px] font-mono text-white/30 pt-px">agent</span>
                      <div className="flex-1 space-y-1.5">
                        {/* Tool calls */}
                        {msg.tools.map((t) => {
                          const isExpanded = expandedToolCalls.has(t.id)
                          const argStr = Object.values(t.input).map(v =>
                            typeof v === 'string' ? `"${v.slice(0, 50)}"` : String(v)
                          ).join(', ')
                          return (
                            <div key={t.id} className="font-mono">
                              <div className="text-[11px] text-white/25">
                                <span className="text-primary/40 mr-1">tool</span>
                                <span className="text-white/35">{t.name}({argStr})</span>
                              </div>
                              {t.result === undefined ? (
                                <div className="pl-8 text-[10px] text-white/20 animate-pulse">↳ running…</div>
                              ) : (
                                <div className="pl-8">
                                  <button
                                    onClick={() => setExpandedToolCalls(prev => {
                                      const next = new Set(prev)
                                      isExpanded ? next.delete(t.id) : next.add(t.id)
                                      return next
                                    })}
                                    className="flex items-center gap-1.5 text-[10px] text-white/20 hover:text-white/40"
                                  >
                                    <span>↳</span>
                                    <span className="truncate max-w-[240px]">
                                      {t.result.slice(0, 70)}{t.result.length > 70 ? '…' : ''}
                                    </span>
                                    <span className="text-white/15 shrink-0">[{isExpanded ? 'collapse' : 'expand'}]</span>
                                  </button>
                                  {isExpanded && (
                                    <pre className="mt-1 text-[10px] text-white/25 whitespace-pre-wrap break-all leading-relaxed max-h-40 overflow-y-auto">
                                      {t.result}
                                    </pre>
                                  )}
                                </div>
                              )}
                            </div>
                          )
                        })}
                        {/* Response text */}
                        {(msg.content || msg.streaming) && (
                          <p className="text-[13px] font-mono text-white/80 leading-relaxed whitespace-pre-wrap">
                            {msg.content}
                            {msg.streaming && <span className="animate-pulse">█</span>}
                          </p>
                        )}
                        {/* Trace link */}
                        {msg.traceId && (
                          <button
                            onClick={() => navigate(`/traces/${msg.traceId}`)}
                            className="text-[11px] font-mono text-white/20 hover:text-white/40"
                          >
                            [trace ↗]
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* Activity strip */}
            {running && activityText && (
              <div className="border-t border-white/5 px-5 py-1.5 flex items-center gap-2 shrink-0">
                <span className="text-[11px] text-primary animate-pulse">●</span>
                <span className="text-[11px] font-mono text-white/30">{activityText}</span>
              </div>
            )}

            {/* Input area */}
            <div className="border-t border-white/10 px-4 py-3 flex items-center gap-2 shrink-0">
              <span className={`font-mono text-sm ${!launched || running ? 'text-white/20' : 'text-white/40'}`}>›</span>
              <input
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
                placeholder="message agent..."
                disabled={!launched || running}
                className="flex-1 bg-transparent text-[13px] font-mono text-white/80 placeholder:text-white/20 focus:outline-none disabled:opacity-30"
              />
              {running && (
                <button onClick={handleStop} className="text-[11px] font-mono text-destructive hover:opacity-80">■</button>
              )}
            </div>
          </>
        )}

      </div>

      {/* ── Mobile tab bar ──────────────────────────────────────── */}
      {isMobile && (
        <div className="flex border-t border-border shrink-0 absolute bottom-0 inset-x-0 bg-background">
          <button onClick={() => setMobileTab('builder')} className={`flex-1 py-3 text-xs font-medium transition-colors ${mobileTab === 'builder' ? 'text-foreground' : 'text-muted-foreground'}`}>Builder</button>
          <button onClick={() => setMobileTab('chat')} className={`flex-1 py-3 text-xs font-medium transition-colors ${mobileTab === 'chat' ? 'text-foreground' : 'text-muted-foreground'}`}>Chat</button>
        </div>
      )}

    </div>
  )
}
