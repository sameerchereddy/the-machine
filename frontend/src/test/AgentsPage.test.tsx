import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi, describe, it, expect, beforeEach } from 'vitest'

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => mockNavigate }
})

// Import after mock setup
const { default: AgentsPage } = await import('@/pages/AgentsPage')

describe('AgentsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('redirects to /login on 401', async () => {
    global.fetch = vi.fn().mockResolvedValue({ status: 401, ok: false })

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/login')
    })
  })

  it('does not loop — navigate called exactly once on 401', async () => {
    global.fetch = vi.fn().mockResolvedValue({ status: 401, ok: false })

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/login')
    })

    await new Promise((r) => setTimeout(r, 150))
    expect(mockNavigate).toHaveBeenCalledTimes(1)
  })

  it('renders agent list on success', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
      json: () =>
        Promise.resolve([
          {
            id: 'abc',
            name: 'My Agent',
            llm_config_id: null,
            updated_at: new Date().toISOString(),
          },
        ]),
    })

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('My Agent')).toBeInTheDocument()
    })
  })

  it('shows empty state when no agents', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
      json: () => Promise.resolve([]),
    })

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('No agents yet.')).toBeInTheDocument()
    })
  })
})
