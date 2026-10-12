import { useState } from 'react'
import Logo from '../components/Logo'
import { Card, Spinner } from '../components/ui'

/**
 * Signed in, but the workspace this account has open has not let it in yet.
 *
 * Joining by code is a request: an owner of that workspace approves it from
 * their Members page, and until then every workspace endpoint answers 403.
 * There is nothing to show but the fact, a way to re-check, and a way out.
 */
export default function PendingApproval({ user, onCheckAgain, onSignOut }) {
  const [checking, setChecking] = useState(false)
  const workspace = user?.pending_approval?.workspace

  async function check() {
    setChecking(true)
    try {
      await onCheckAgain?.()
    } finally {
      setChecking(false)
    }
  }

  return (
    <div
      className="flex min-h-screen items-center justify-center px-5 py-12"
      style={{ backgroundColor: 'var(--surface-page)' }}
    >
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center text-center">
          <Logo variant="icon" size={64} />
          <h1 className="mt-5 text-2xl font-semibold">Waiting for approval</h1>
        </div>
        <Card>
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
            Your request to join <strong style={{ color: 'var(--text-strong)' }}>{workspace || 'the workspace'}</strong>{' '}
            has been sent. An owner has to approve it from their Members page before you can get in —
            ask them if it is taking a while.
          </p>
          <p className="mt-3 text-xs" style={{ color: 'var(--text-faint)' }}>
            Signed in as {user?.email}
          </p>
          <div className="mt-5 flex gap-2">
            <button type="button" className="mc-btn mc-btn-primary flex-1" onClick={check} disabled={checking}>
              {checking ? <Spinner size={14} /> : null} Check again
            </button>
            <button type="button" className="mc-btn mc-btn-secondary" onClick={onSignOut}>
              Sign out
            </button>
          </div>
        </Card>
      </div>
    </div>
  )
}
