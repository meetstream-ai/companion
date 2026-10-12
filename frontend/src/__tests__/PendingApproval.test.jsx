import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import PendingApproval from '../pages/PendingApproval'

describe('waiting for approval', () => {
  it('names the workspace, re-checks on demand, and offers a way out', async () => {
    const onCheckAgain = vi.fn().mockResolvedValue(undefined)
    const onSignOut = vi.fn()
    render(
      <PendingApproval
        user={{ email: 'asker@x.test', pending_approval: { workspace: 'Acme' } }}
        onCheckAgain={onCheckAgain}
        onSignOut={onSignOut}
      />,
    )
    expect(screen.getByRole('heading', { name: 'Waiting for approval' })).toBeInTheDocument()
    expect(screen.getByText('Acme')).toBeInTheDocument()
    expect(screen.getByText(/Signed in as asker@x.test/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Check again/ }))
    await waitFor(() => expect(onCheckAgain).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(onSignOut).toHaveBeenCalled()
  })
})
