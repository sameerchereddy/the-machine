import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'

const STEPS = [
  {
    n: '01',
    title: 'Connect your LLM',
    body: 'Bring your own API key — OpenAI, Anthropic, Gemini, Grok, Bedrock, Azure, or Ollama. Keys are encrypted per-user with AES-256-GCM and never logged.',
  },
  {
    n: '02',
    title: 'Build an agent',
    body: 'Compose blocks on a visual canvas: Instructions, Context, Knowledge Base, Memory, Tools, and Guardrails. Every block is live-editable mid-session.',
  },
  {
    n: '03',
    title: 'Run and trace',
    body: 'Launch the agent and watch the ReAct loop — Reason → Act → Observe — unfold in real time. Every run is stored as a full trace you can inspect later.',
  },
]

export default function OnboardingPage() {
  const { user } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background font-mono px-6 py-16">
      <div className="w-full max-w-lg space-y-10">

        {/* Header */}
        <div className="space-y-3 text-center">
          <p className="text-xs text-muted-foreground tracking-widest uppercase">◈ The Machine ◈</p>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            Think. Act. Observe.
          </h1>
          <p className="text-sm text-muted-foreground">
            Welcome{user?.email ? `, ${user.email.split('@')[0]}` : ''}. Here's how it works.
          </p>
        </div>

        {/* Steps */}
        <div className="space-y-0 divide-y divide-border rounded-md border border-border">
          {STEPS.map((step, i) => (
            <div
              key={step.n}
              className="animate-fade-in-up flex gap-4 px-5 py-4"
              style={{ animationDelay: `${i * 80}ms` }}
            >
              <span className="shrink-0 text-xs text-muted-foreground/50 pt-0.5 w-5">{step.n}</span>
              <div className="space-y-1">
                <p className="text-sm font-medium text-foreground">{step.title}</p>
                <p className="text-xs text-muted-foreground leading-relaxed">{step.body}</p>
              </div>
            </div>
          ))}
        </div>

        {/* CTA */}
        <div
          className="animate-fade-in-up flex flex-col items-center gap-3"
          style={{ animationDelay: '280ms' }}
        >
          <button
            onClick={() => navigate('/setup')}
            className="w-full rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:opacity-90 transition-opacity"
          >
            Connect your LLM →
          </button>
          <button
            onClick={() => navigate('/agents')}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            Skip for now
          </button>
        </div>

      </div>
    </div>
  )
}
