import { renderHook, act } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { AuthProvider, useAuth } from '@/context/AuthContext'

vi.mock('@/lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: vi.fn(),
      onAuthStateChange: vi.fn(() => ({
        data: { subscription: { unsubscribe: vi.fn() } },
      })),
    },
  },
}))

const mockFetch = vi.fn()
global.fetch = mockFetch

describe('AuthContext', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockFetch.mockResolvedValue({ ok: true })
  })

  it('calls syncCookie when getSession returns a session', async () => {
    const { supabase } = await import('@/lib/supabase')
    vi.mocked(supabase.auth.getSession).mockResolvedValue({
      data: {
        session: {
          access_token: 'tok-123',
          user: { id: '1', email: 'a@b.com' },
        } as never,
      },
      error: null,
    })

    renderHook(() => useAuth(), { wrapper: AuthProvider })
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/auth/login',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ access_token: 'tok-123' }),
      }),
    )
  })

  it('sets loading to false even when syncCookie throws', async () => {
    const { supabase } = await import('@/lib/supabase')
    vi.mocked(supabase.auth.getSession).mockResolvedValue({
      data: {
        session: {
          access_token: 'tok',
          user: { id: '1' },
        } as never,
      },
      error: null,
    })
    mockFetch.mockRejectedValue(new Error('network error'))

    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider })
    await act(async () => { await new Promise((r) => setTimeout(r, 50)) })

    expect(result.current.loading).toBe(false)
  })

  it('does not call syncCookie when there is no session', async () => {
    const { supabase } = await import('@/lib/supabase')
    vi.mocked(supabase.auth.getSession).mockResolvedValue({
      data: { session: null },
      error: null,
    })

    renderHook(() => useAuth(), { wrapper: AuthProvider })
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })

    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('calls syncCookie on onAuthStateChange SIGNED_IN event', async () => {
    const { supabase } = await import('@/lib/supabase')
    vi.mocked(supabase.auth.getSession).mockResolvedValue({
      data: { session: null },
      error: null,
    })

    let stateChangeCb: (event: string, session: unknown) => void = () => {}
    vi.mocked(supabase.auth.onAuthStateChange).mockImplementation((cb) => {
      stateChangeCb = cb as typeof stateChangeCb
      return { data: { subscription: { unsubscribe: vi.fn() } } } as never
    })

    renderHook(() => useAuth(), { wrapper: AuthProvider })
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })

    mockFetch.mockClear()

    await act(async () => {
      stateChangeCb('SIGNED_IN', { access_token: 'new-tok', user: { id: '2' } })
      await new Promise((r) => setTimeout(r, 0))
    })

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/auth/login',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('setUser is called even when onAuthStateChange syncCookie throws', async () => {
    const { supabase } = await import('@/lib/supabase')
    vi.mocked(supabase.auth.getSession).mockResolvedValue({
      data: { session: null },
      error: null,
    })

    let stateChangeCb: (event: string, session: unknown) => void = () => {}
    vi.mocked(supabase.auth.onAuthStateChange).mockImplementation((cb) => {
      stateChangeCb = cb as typeof stateChangeCb
      return { data: { subscription: { unsubscribe: vi.fn() } } } as never
    })

    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider })
    await act(async () => { await new Promise((r) => setTimeout(r, 0)) })

    mockFetch.mockRejectedValue(new Error('cookie sync failed'))

    await act(async () => {
      stateChangeCb('SIGNED_IN', { access_token: 'tok', user: { id: '3', email: 'x@y.com' } })
      await new Promise((r) => setTimeout(r, 50))
    })

    // user should be set despite syncCookie failure
    expect(result.current.user).not.toBeNull()
  })
})
