import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import WorkspaceSwitchOverlay from '../components/WorkspaceSwitchOverlay'

describe('WorkspaceSwitchOverlay', () => {
  it('renders default action and subtitle with brand logo and progress', () => {
    render(<WorkspaceSwitchOverlay />)

    expect(screen.getByRole('dialog', { name: 'Switching workspace…' })).toBeInTheDocument()
    expect(screen.getByText('Switching workspace…')).toBeInTheDocument()
    expect(screen.getByText(/Setting up your meetings, notes, and AI workspace/)).toBeInTheDocument()
    expect(screen.getByAltText('Meet Companion')).toBeInTheDocument()
  })

  it('renders custom workspace name, action, and custom subtitle', () => {
    render(
      <WorkspaceSwitchOverlay
        name="Product Engineering"
        action="Opening workspace…"
        subtitle="Loading your meetings, notes, and workspace data…"
      />,
    )

    expect(screen.getByRole('dialog', { name: 'Opening workspace…' })).toBeInTheDocument()
    expect(screen.getByText('Opening workspace…')).toBeInTheDocument()
    expect(screen.getByText('Product Engineering')).toBeInTheDocument()
    expect(screen.getByText(/Loading your meetings, notes, and workspace data/)).toBeInTheDocument()
  })
})
