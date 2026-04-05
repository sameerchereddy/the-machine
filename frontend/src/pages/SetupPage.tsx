import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

const API = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// ---------------------------------------------------------------------------
// Provider metadata
// ---------------------------------------------------------------------------

type Provider = {
  id: string
  label: string
  fields: FieldDef[]
  defaultModels: string[]
}

type FieldDef = {
  key: string
  label: string
  type: 'text' | 'password' | 'url'
  placeholder?: string
  required?: boolean
}

const PROVIDERS: Provider[] = [
  {
    id: 'openai',
    label: 'OpenAI',
    fields: [{ key: 'api_key', label: 'API Key', type: 'password', placeholder: 'sk-…', required: true }],
    defaultModels: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'],
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    fields: [{ key: 'api_key', label: 'API Key', type: 'password', placeholder: 'sk-ant-…', required: true }],
    defaultModels: ['claude-opus-4-6', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001'],
  },
  {
    id: 'gemini',
    label: 'Google Gemini',
    fields: [{ key: 'api_key', label: 'API Key', type: 'password', required: true }],
    defaultModels: ['gemini-2.5-pro', 'gemini-2.0-flash', 'gemini-1.5-pro'],
  },
  {
    id: 'grok',
    label: 'xAI Grok',
    fields: [{ key: 'api_key', label: 'API Key', type: 'password', required: true }],
    defaultModels: ['grok-3', 'grok-3-mini', 'grok-2'],
  },
  {
    id: 'azure',
    label: 'Azure OpenAI',
    fields: [
      { key: 'api_key', label: 'API Key', type: 'password', required: true },
      { key: 'base_url', label: 'Endpoint URL', type: 'url', placeholder: 'https://…openai.azure.com', required: true },
      { key: 'api_version', label: 'API Version', type: 'text', placeholder: '2024-02-01' },
    ],
    defaultModels: ['gpt-4o', 'gpt-4-turbo', 'gpt-35-turbo'],
  },
  {
    id: 'bedrock',
    label: 'AWS Bedrock',
    fields: [
      { key: 'access_key_id', label: 'Access Key ID', type: 'text', required: true },
      { key: 'secret_access_key', label: 'Secret Access Key', type: 'password', required: true },
      { key: 'region', label: 'Region', type: 'text', placeholder: 'us-east-1' },
    ],
    defaultModels: ['anthropic.claude-3-5-sonnet-20241022-v2:0', 'anthropic.claude-3-haiku-20240307-v1:0'],
  },
  {
    id: 'ollama',
    label: 'Ollama (local)',
    fields: [
      { key: 'base_url', label: 'Base URL', type: 'url', placeholder: 'http://127.0.0.1:11434' },
    ],
    defaultModels: ['llama3.2', 'mistral', 'phi4', 'qwen2.5'],
  },
  {
    id: 'custom',
    label: 'Custom (OpenAI-compatible)',
    fields: [
      { key: 'api_key', label: 'API Key', type: 'password' },
      { key: 'base_url', label: 'Base URL', type: 'url', placeholder: 'https://…/v1', required: true },
    ],
    defaultModels: [],
  },
]

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type LLMConfig = {
  id: string
  name: string
  provider: string
  model: string
  is_default: boolean
  supports_tool_calls: boolean
  context_window: number | null
  config: Record<string, string>
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SetupPage() {
  const navigate = useNavigate()

  // Existing configs
  const [configs, setConfigs] = useState<LLMConfig[]>([])
  const [loadingConfigs, setLoadingConfigs] = useState(true)

  // Form state
  const [selectedProvider, setSelectedProvider] = useState<Provider | null>(null)
  const [configName, setConfigName] = useState('')
  const [model, setModel] = useState('')
  const [customModel, setCustomModel] = useState('')
  const [isDefault, setIsDefault] = useState(false)
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({})

  // Status
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [pingResult, setPingResult] = useState<{ ok: boolean; latency_ms?: number; error?: string } | null>(null)
  const [saveError, setSaveError] = useState('')
  const [listError, setListError] = useState('')

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fetchConfigs() }, [])

  async function fetchConfigs() {
    setLoadingConfigs(true)
    try {
      const res = await fetch(`${API}/api/llm-configs`, { credentials: 'include' })
      if (res.status === 401) { navigate('/login'); return }
      if (res.ok) setConfigs(await res.json())
    } finally {
      setLoadingConfigs(false)
    }
  }

  function selectProvider(p: Provider) {
    setSelectedProvider(p)
    setFieldValues({})
    setModel(p.defaultModels[0] ?? '')
    setCustomModel('')
    setConfigName(p.label)
    setPingResult(null)
    setSaveError('')
  }

  function resetForm() {
    setSelectedProvider(null)
    setFieldValues({})
    setModel('')
    setCustomModel('')
    setConfigName('')
    setIsDefault(false)
    setPingResult(null)
    setSaveError('')
  }

  function buildConfig(): Record<string, string> {
    const result: Record<string, string> = {}
    for (const f of selectedProvider?.fields ?? []) {
      if (fieldValues[f.key]) result[f.key] = fieldValues[f.key]
    }
    return result
  }

  function activeModel() {
    return model === '__custom__' ? customModel : model
  }

  async function handleSave() {
    if (!selectedProvider) return
    setSaveError('')
    setSaving(true)
    try {
      const res = await fetch(`${API}/api/llm-configs`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: configName || selectedProvider.label,
          provider: selectedProvider.id,
          model: activeModel(),
          is_default: isDefault,
          config: buildConfig(),
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setSaveError(body.detail ?? 'Failed to save config.')
        return
      }
      await fetchConfigs()
      resetForm()
    } finally {
      setSaving(false)
    }
  }

  async function handleTestConnection() {
    if (!selectedProvider) return
    setTesting(true)
    setPingResult(null)
    try {
      const res = await fetch(`${API}/api/llm-configs/ping`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: selectedProvider.id,
          model: activeModel(),
          config: buildConfig(),
        }),
      })
      setPingResult(await res.json())
    } finally {
      setTesting(false)
    }
  }

  async function handleSetDefault(id: string) {
    setListError('')
    const res = await fetch(`${API}/api/llm-configs/${id}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_default: true }),
    })
    if (!res.ok) { setListError('Failed to update default. Please try again.'); return }
    await fetchConfigs()
  }

  async function handleDelete(id: string) {
    setListError('')
    const res = await fetch(`${API}/api/llm-configs/${id}`, {
      method: 'DELETE',
      credentials: 'include',
    })
    if (!res.ok) { setListError('Failed to delete config. Please try again.'); return }
    await fetchConfigs()
  }

  const isFormValid =
    !!selectedProvider &&
    !!activeModel() &&
    selectedProvider.fields
      .filter((f) => f.required)
      .every((f) => !!fieldValues[f.key])

  return (
    <div className="min-h-screen bg-background font-mono text-foreground">
      <div className="mx-auto max-w-2xl px-6 py-12 space-y-10">

        {/* Header */}
        <div className="space-y-1">
          <h1 className="text-xl font-semibold tracking-tight">LLM Configuration</h1>
          <p className="text-sm text-muted-foreground">
            Connect an LLM provider to power your agents.
          </p>
        </div>

        {listError && <p className="text-sm text-destructive">{listError}</p>}

        {/* Existing configs */}
        {loadingConfigs && (
          <div className="space-y-2">
            <p className="text-xs uppercase tracking-widest text-muted-foreground">Saved configs</p>
            <div className="divide-y divide-border rounded-md border border-border">
              {[1, 2].map((i) => (
                <div key={i} className="flex items-center justify-between px-4 py-3">
                  <div className="space-y-1.5">
                    <div className="h-3.5 w-32 rounded bg-muted animate-pulse" />
                    <div className="h-3 w-48 rounded bg-muted animate-pulse" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {!loadingConfigs && configs.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs uppercase tracking-widest text-muted-foreground">Saved configs</p>
            <div className="divide-y divide-border rounded-md border border-border">
              {configs.map((c) => (
                <div key={c.id} className="flex items-center justify-between px-4 py-3">
                  <div className="space-y-0.5">
                    <p className="text-sm font-medium">
                      {c.name}
                      {c.is_default && (
                        <span className="ml-2 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                          default
                        </span>
                      )}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {c.provider} · {c.model}
                      {c.config.api_key && (
                        <span className="ml-2 text-muted-foreground">{c.config.api_key}</span>
                      )}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {!c.is_default && (
                      <button
                        onClick={() => handleSetDefault(c.id)}
                        className="text-xs text-muted-foreground hover:text-foreground"
                      >
                        set default
                      </button>
                    )}
                    <button
                      onClick={() => handleDelete(c.id)}
                      className="text-xs text-destructive hover:opacity-80"
                    >
                      delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Add new */}
        {!selectedProvider ? (
          <div className="space-y-3">
            <p className="text-xs uppercase tracking-widest text-muted-foreground">Add provider</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {PROVIDERS.map((p) => (
                <button
                  key={p.id}
                  onClick={() => selectProvider(p)}
                  className="rounded-md border border-border px-3 py-3 text-sm hover:border-ring hover:bg-secondary text-left"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-5">
            <div className="flex items-center justify-between">
              <p className="text-xs uppercase tracking-widest text-muted-foreground">
                {selectedProvider.label}
              </p>
              <button
                onClick={resetForm}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                ← back
              </button>
            </div>

            {/* Config name */}
            <div className="space-y-1.5">
              <label className="text-sm text-foreground" htmlFor="config-name">
                Name
              </label>
              <input
                id="config-name"
                type="text"
                value={configName}
                onChange={(e) => setConfigName(e.target.value)}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                placeholder={selectedProvider.label}
              />
            </div>

            {/* Provider-specific fields */}
            {selectedProvider.fields.map((f) => (
              <div key={f.key} className="space-y-1.5">
                <label className="text-sm text-foreground" htmlFor={f.key}>
                  {f.label}
                  {f.required && <span className="ml-1 text-destructive">*</span>}
                </label>
                <input
                  id={f.key}
                  type={f.type === 'password' ? 'password' : 'text'}
                  value={fieldValues[f.key] ?? ''}
                  onChange={(e) => setFieldValues((v) => ({ ...v, [f.key]: e.target.value }))}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-ring"
                  placeholder={f.placeholder}
                />
              </div>
            ))}

            {/* Model */}
            <div className="space-y-1.5">
              <label className="text-sm text-foreground" htmlFor="model">
                Model <span className="text-destructive">*</span>
              </label>
              {selectedProvider.defaultModels.length > 0 ? (
                <>
                  <select
                    id="model"
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    {selectedProvider.defaultModels.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                    <option value="__custom__">Custom…</option>
                  </select>
                  {model === '__custom__' && (
                    <input
                      type="text"
                      value={customModel}
                      onChange={(e) => setCustomModel(e.target.value)}
                      className="mt-1.5 w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-ring"
                      placeholder="model-id"
                    />
                  )}
                </>
              ) : (
                <input
                  id="model"
                  type="text"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-ring"
                  placeholder="model-id"
                />
              )}
            </div>

            {/* Set as default */}
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={isDefault}
                onChange={(e) => setIsDefault(e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              <span className="text-sm text-foreground">Set as default for new agents</span>
            </label>

            {/* Ping result */}
            {pingResult && (
              <div
                className={`rounded-md px-3 py-2 text-sm ${
                  pingResult.ok
                    ? 'bg-green-500/10 text-green-400'
                    : 'bg-destructive/10 text-destructive'
                }`}
              >
                {pingResult.ok
                  ? `Connection successful · ${pingResult.latency_ms}ms`
                  : `Connection failed: ${pingResult.error}`}
              </div>
            )}

            {saveError && (
              <p className="text-sm text-destructive">{saveError}</p>
            )}

            {/* Actions */}
            <div className="flex gap-2 pt-1">
              <button
                onClick={handleTestConnection}
                disabled={!isFormValid || testing}
                className="rounded-md border border-input px-4 py-2 text-sm hover:bg-secondary disabled:opacity-50"
              >
                {testing ? 'Testing…' : 'Test connection'}
              </button>
              <button
                onClick={handleSave}
                disabled={!isFormValid || saving}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        )}

        {/* Skip / continue */}
        {configs.length > 0 && (
          <div className="pt-2">
            <button
              onClick={() => navigate('/agents')}
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              Continue to agents →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
