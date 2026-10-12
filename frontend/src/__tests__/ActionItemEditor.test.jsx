import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({ updateActionItem: vi.fn() }))
import { updateActionItem } from '../api'
import ActionItemEditor from '../components/ActionItemEditor'

const item = { id: 'ai-1', task: 'Write the runbook', owner: 'MeetStream Companion', due_date: '2026-09-16', priority: 'medium' }

describe('ActionItemEditor', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows the item and sends only the edited fields, clearing a blank due date', async () => {
    updateActionItem.mockResolvedValue({ ...item, owner: 'Dana', due_date: null, priority: 'high' })
    const onSaved = vi.fn()
    const onClose = vi.fn()
    render(<ActionItemEditor item={item} onClose={onClose} onSaved={onSaved} />)

    expect(screen.getByLabelText('Task')).toHaveValue('Write the runbook')
    expect(screen.getByLabelText('Owner')).toHaveValue('MeetStream Companion')
    expect(screen.getByLabelText('Due date')).toHaveValue('2026-09-16')

    fireEvent.change(screen.getByLabelText('Owner'), { target: { value: 'Dana' } })
    fireEvent.change(screen.getByLabelText('Due date'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Priority'), { target: { value: 'high' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(updateActionItem).toHaveBeenCalledWith('ai-1', {
      task: 'Write the runbook', owner: 'Dana', due_date: null, priority: 'high',
    }))
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ id: 'ai-1', owner: 'Dana', due_date: null, priority: 'high' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('keeps the dialog open and shows the server message when saving fails', async () => {
    updateActionItem.mockRejectedValue(new Error('Members of this workspace cannot edit content.'))
    const onClose = vi.fn()
    render(<ActionItemEditor item={item} onClose={onClose} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText(/cannot edit content/)).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('will not save an empty task', () => {
    render(<ActionItemEditor item={item} onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Task'), { target: { value: '   ' } })
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })
})
