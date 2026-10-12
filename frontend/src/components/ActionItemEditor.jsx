import { useEffect, useState } from 'react'
import { ErrorMessage, Field, Modal, Spinner } from './ui'
import { updateActionItem } from '../api'

export const PRIORITIES = ['low', 'medium', 'high', 'critical']

/**
 * Edit what the extractor guessed: the task text, who owns it, when it is
 * due and how urgent it is. Extraction resolves "by Friday" against the
 * meeting date and credits whoever spoke - both are wrong often enough that
 * they must be fixable by hand. A blank due date clears it.
 */
export default function ActionItemEditor({ item, onClose, onSaved }) {
  const [form, setForm] = useState(() => toForm(item))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    setForm(toForm(item))
    setError(null)
  }, [item])

  const set = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }))

  async function save(event) {
    event.preventDefault()
    if (!item) return
    setSaving(true)
    setError(null)
    try {
      const patch = {
        task: form.task.trim(),
        owner: form.owner.trim() || null,
        due_date: form.due_date || null,
        priority: form.priority,
      }
      const updated = await updateActionItem(item.id, patch)
      onSaved?.({ ...item, ...patch, ...pick(updated) })
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal open={Boolean(item)} onClose={onClose} title="Edit action item" width="30rem">
      <form onSubmit={save} className="grid gap-1">
        {error && (
          <div className="mb-3">
            <ErrorMessage title="Could not save" detail={error} />
          </div>
        )}
        <Field label="Task" htmlFor="ai-task">
          <textarea id="ai-task" className="mc-input min-h-20" required value={form.task} onChange={set('task')} />
        </Field>
        <Field label="Owner" htmlFor="ai-owner" hint="Who is doing it. Leave blank if nobody has picked it up.">
          <input id="ai-owner" className="mc-input" value={form.owner} onChange={set('owner')} placeholder="e.g. Dana" />
        </Field>
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Field label="Due date" htmlFor="ai-due" hint="Clear it if there is no deadline.">
            <input id="ai-due" type="date" className="mc-input" value={form.due_date} onChange={set('due_date')} />
          </Field>
          <Field label="Priority" htmlFor="ai-priority">
            <select id="ai-priority" className="mc-input" value={form.priority} onChange={set('priority')}>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </Field>
        </div>
        <div className="mt-2 flex justify-end gap-2">
          <button type="button" className="mc-btn mc-btn-secondary" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="submit" className="mc-btn mc-btn-primary" disabled={saving || !form.task.trim()}>
            {saving ? <Spinner size={14} /> : null} Save
          </button>
        </div>
      </form>
    </Modal>
  )
}

function toForm(item) {
  return {
    task: item?.task || '',
    owner: item?.owner || '',
    due_date: item?.due_date || '',
    priority: item?.priority || 'medium',
  }
}

function pick(updated) {
  if (!updated || typeof updated !== 'object') return {}
  const out = {}
  for (const key of ['task', 'owner', 'due_date', 'priority', 'status']) {
    if (key in updated) out[key] = updated[key]
  }
  return out
}
