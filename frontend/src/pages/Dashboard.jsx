import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Page, PageHeader } from '../components/AppShell'
import {
  AskAiIcon,
  CheckIcon,
  MeetingsIcon,
  NotebookIcon,
  PencilIcon,
  PlusIcon,
  StarIcon,
} from '../components/Icons'
import {
  Badge,
  Card,
  EmptyState,
  ErrorMessage,
  IconChip,
  Loading,
  SectionCard,
  StatTile,
} from '../components/ui'
import { listActionItems, listFolders, listMeetings, listNotes, updateActionItem } from '../api'
import ActionItemEditor from '../components/ActionItemEditor'
import { useCan } from '../user'
import { isLiveMeeting } from '../meetingStatus'

function today() {
  return new Date().toISOString().slice(0, 10)
}

function dueLabel(dueDate) {
  if (!dueDate) return null
  const due = new Date(`${dueDate}T00:00:00`)
  const days = Math.round((due - new Date(today())) / 86400000)
  if (days < 0) return { text: `${Math.abs(days)}d overdue`, tone: 'danger' }
  if (days === 0) return { text: 'Due today', tone: 'warning' }
  if (days === 1) return { text: 'Due tomorrow', tone: 'warning' }
  return { text: `Due in ${days}d`, tone: 'neutral' }
}

const PRIORITY_TONE = { critical: 'danger', high: 'warning', medium: 'neutral', low: 'neutral' }

export default function Dashboard() {
  const [live, setLive] = useState([])
  const [meetingCount, setMeetingCount] = useState(0)
  const [notes, setNotes] = useState([])
  const [actionItems, setActionItems] = useState(null)
  const [counts, setCounts] = useState(null)
  const [error, setError] = useState(null)
  const [completing, setCompleting] = useState(null)

  const load = useCallback(async () => {
    try {
      const [meetingList, noteList, folderData, actions] = await Promise.all([
        listMeetings(today()).catch(() => []),
        listNotes({ limit: 5, sort: 'updated' }).catch(() => ({ notes: [], total: 0 })),
        listFolders().catch(() => ({ counts: {} })),
        listActionItems({ status: 'open', limit: 8 }).catch(() => ({ action_items: [] })),
      ])

      const meetings = Array.isArray(meetingList) ? meetingList : meetingList?.meetings || []
      setMeetingCount(meetings.length)
      // A bot is only "in a call" once MeetStream has accepted it; a
      // meeting that never got a bot (no key, bad link) is not live.
      setLive(meetings.filter(isLiveMeeting))
      setNotes(noteList.notes || [])
      setCounts({ ...(folderData.counts || {}), notes: noteList.total || 0 })
      setActionItems(actions.action_items || [])
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const canEdit = useCan('edit_content')
  const [editing, setEditing] = useState(null)

  async function complete(item) {
    setCompleting(item.id)
    try {
      await updateActionItem(item.id, { status: 'completed' })
      setActionItems((current) => current.filter((candidate) => candidate.id !== item.id))
    } catch (err) {
      setError(err.message)
    } finally {
      setCompleting(null)
    }
  }

  const overdue = useMemo(
    () => (actionItems || []).filter((item) => item.due_date && new Date(`${item.due_date}T00:00:00`) < new Date(today())),
    [actionItems],
  )

  if (error && actionItems === null) {
    return <Page><ErrorMessage title="Could not load your workspace" detail={error} onRetry={load} /></Page>
  }
  if (actionItems === null) return <Page><Loading /></Page>

  return (
    <Page>
      <PageHeader
        title="Dashboard"
        description="Everything waiting on you, pulled from your meetings and notes."
        actions={
          <>
            <Link to="/notebook" className="mc-btn mc-btn-secondary">
              <PlusIcon size={16} /> New note
            </Link>
            <Link to="/ask" className="mc-btn mc-btn-primary">
              <AskAiIcon size={16} /> Ask AI
            </Link>
          </>
        }
      />

      {error && <div className="mb-4"><ErrorMessage title="Something went wrong" detail={error} /></div>}

      {/* Live calls get a dedicated strip: it is the only thing here that is
          time-critical, and burying it in a list would hide it. */}
      {live.length > 0 && (
        <Card className="mb-5 flex flex-wrap items-center gap-4">
          <IconChip icon={<MeetingsIcon size={19} />} tone="peach" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold" style={{ color: 'var(--text-strong)' }}>
              {live.length} bot{live.length === 1 ? '' : 's'} in a call right now
            </div>
            <div className="truncate text-xs" style={{ color: 'var(--text-muted)' }}>
              {live.map((meeting) => meeting.title || 'Untitled meeting').join(' · ')}
            </div>
          </div>
          <Link to="/meetings" className="mc-btn mc-btn-secondary">Open meetings</Link>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Open action items"
          value={actionItems.length}
          tone="brand"
          icon={<CheckIcon size={19} />}
          hint={overdue.length ? `${overdue.length} overdue` : 'Nothing overdue'}
        />
        <StatTile
          label="Meetings today"
          value={meetingCount}
          tone="peach"
          icon={<MeetingsIcon size={19} />}
          hint={live.length ? `${live.length} live now` : 'None active'}
        />
        <StatTile
          label="Notes"
          value={counts?.notes ?? 0}
          tone="lavender"
          icon={<NotebookIcon size={19} />}
          hint="Across your notebook"
        />
        <StatTile
          label="Favourites"
          value={counts?.favorites ?? 0}
          tone="rose"
          icon={<StarIcon size={19} />}
          hint="Starred for quick access"
        />
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[1.4fr_1fr] items-start">
        <SectionCard
          title="Outstanding action items"
          action={
            <Link to="/meetings" className="text-xs font-medium" style={{ color: 'var(--brand-soft-text)' }}>
              From your meetings
            </Link>
          }
        >
          {actionItems.length === 0 ? (
            <EmptyState
              icon={<CheckIcon size={22} />}
              title="Nothing outstanding"
              description="Action items extracted from your meetings show up here until they are done."
            />
          ) : (
            <ul className="divide-y" style={{ borderColor: 'var(--border-subtle)' }}>
              {actionItems.map((item) => {
                const due = dueLabel(item.due_date)
                return (
                  <li key={item.id} className="flex items-start gap-3 px-5 py-3.5">
                    <button
                      type="button"
                      className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md transition-colors"
                      style={{ border: '1.5px solid var(--border-strong)', color: 'var(--text-faint)' }}
                      onClick={() => complete(item)}
                      disabled={completing === item.id}
                      aria-label={`Mark "${item.task}" complete`}
                      title="Mark complete"
                    >
                      {completing === item.id ? '·' : <CheckIcon size={13} />}
                    </button>

                    <div className="min-w-0 flex-1">
                      <p className="text-sm" style={{ color: 'var(--text-strong)' }}>{item.task}</p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        {item.owner && <Badge>{item.owner}</Badge>}
                        {item.priority && item.priority !== 'medium' && (
                          <Badge tone={PRIORITY_TONE[item.priority] || 'neutral'}>{item.priority}</Badge>
                        )}
                        {due && <Badge tone={due.tone}>{due.text}</Badge>}
                        {item.meeting_id ? (
                          <Link
                            to={`/meetings/${item.meeting_id}`}
                            className="text-[0.7rem] hover:underline"
                            style={{ color: 'var(--text-faint)' }}
                          >
                            {item.meeting_title || 'View meeting'}
                          </Link>
                        ) : item.note_id ? (
                          <Link
                            to={`/notebook/${item.note_id}`}
                            className="text-[0.7rem] hover:underline"
                            style={{ color: 'var(--text-faint)' }}
                          >
                            {item.note_title || 'View note'}
                          </Link>
                        ) : null}
                      </div>
                    </div>
                    {canEdit && (
                      <button
                        type="button"
                        className="mc-btn mc-btn-ghost shrink-0 px-2"
                        onClick={() => setEditing(item)}
                        aria-label={`Edit "${item.task}"`}
                        title="Edit owner, due date, priority"
                      >
                        <PencilIcon size={15} />
                      </button>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </SectionCard>

        <SectionCard
          title="Recent notes"
          action={
            <Link to="/notebook" className="text-xs font-medium" style={{ color: 'var(--brand-soft-text)' }}>
              Open notebook
            </Link>
          }
        >
          {notes.length === 0 ? (
            <EmptyState
              icon={<NotebookIcon size={22} />}
              title="Your notebook is empty"
              description="Capture a thought, or let a meeting write one for you."
              action={
                <Link to="/notebook" className="mc-btn mc-btn-secondary">Create a note</Link>
              }
            />
          ) : (
            <ul className="divide-y" style={{ borderColor: 'var(--border-subtle)' }}>
              {notes.map((note) => (
                <li key={note.id}>
                  <Link
                    to={`/notebook/${note.id}`}
                    className="block px-5 py-3 transition-colors hover:bg-[var(--surface-raised)]"
                  >
                    <div className="truncate text-sm font-medium" style={{ color: 'var(--text-strong)' }}>
                      {note.title}
                    </div>
                    {note.excerpt && (
                      <div className="mt-0.5 line-clamp-2 text-xs" style={{ color: 'var(--text-muted)' }}>
                        {note.excerpt}
                      </div>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>
      </div>
      <ActionItemEditor
        item={editing}
        onClose={() => setEditing(null)}
        onSaved={(updated) => setActionItems((current) => current.map((c) => (c.id === updated.id ? { ...c, ...updated } : c)))}
      />
    </Page>
  )
}
