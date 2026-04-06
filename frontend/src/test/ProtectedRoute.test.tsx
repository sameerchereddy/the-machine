import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import ProtectedRoute from '@/components/ProtectedRoute'

vi.mock('@/context/AuthContext', () => ({
  useAuth: vi.fn(),
}))

async function mockAuth(user: unknown, loading = false) {
  const { useAuth } = await import('@/context/AuthContext')
  vi.mocked(useAuth).mockReturnValue({ user: user as never, loading, signIn: vi.fn(), signInWithGoogle: vi.fn(), signOut: vi.fn() })
}

function renderWithRouter(initialPath = '/protected') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/login" element={<div>Login page</div>} />
        <Route
          path="/protected"
          element={
            <ProtectedRoute>
              <div>Protected content</div>
            </ProtectedRoute>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ProtectedRoute', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders children when user is authenticated', async () => {
    await mockAuth({ id: '1', email: 'a@b.com' })
    renderWithRouter()
    expect(screen.getByText('Protected content')).toBeInTheDocument()
  })

  it('redirects to /login when user is null', async () => {
    await mockAuth(null)
    renderWithRouter()
    expect(screen.queryByText('Protected content')).not.toBeInTheDocument()
    expect(screen.getByText('Login page')).toBeInTheDocument()
  })

  it('shows spinner while loading', async () => {
    await mockAuth(null, true)
    const { container } = renderWithRouter()
    expect(screen.queryByText('Protected content')).not.toBeInTheDocument()
    expect(screen.queryByText('Login page')).not.toBeInTheDocument()
    expect(container.querySelector('.animate-spin')).toBeInTheDocument()
  })

  it('does not redirect while loading even with no user', async () => {
    await mockAuth(null, true)
    renderWithRouter()
    // Loading state — should not be on login page yet
    expect(screen.queryByText('Login page')).not.toBeInTheDocument()
  })
})
