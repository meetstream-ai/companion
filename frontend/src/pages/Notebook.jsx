import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  FolderIcon,
  FolderOpenIcon,
  NoteIcon,
  PlusIcon,
  SearchIcon,
  StarIcon,
  TrashIcon,
} from '../components/Icons'
import { Badge, EmptyState, ErrorMessage, ExportMenu, Loading, Modal, Spinner } from '../components/ui'
import Markdown, { toggleTaskInMarkdown } from '../components/Markdown'
import {
  createFolder,
  createNote,
  deleteFolder,
  deleteNote,
  getNote,
  listFolders,
  listNoteTags,
  listNotes,
  syncMeetingNotes,
  updateNote,
  exportNoteUrl,
} from '../api'
import { useCan } from '../user'

const SORTS = [
  { value: 'updated', label: 'Last updated' },
  { value: 'created', label: 'Date created' },
  { value: 'title', label: 'Title' },
]

const NOTE_TYPES = ['note', 'meeting', 'idea', 'research']

const SAVE_DEBOUNCE_MS = 800

function FolderRow({ node, depth, selectedId, onSelect, onContextMenu }) {
  const [open, setOpen] = useState(depth < 1)
  const hasChildren = node.children?.length > 0
  const selected = selectedId === node.id

  return (
    <div>
      <div
        className="mc-nav-item group cursor-pointer"
        style={{ paddingLeft: `${0.5 + depth * 0.85}rem` }}
        aria-current={selected ? 'page' : undefined}
        onClick={() => onSelect(node.id)}
      >
        <button
          type="button"
          className="shrink-0"
          style={{ visibility: hasChildren ? 'visible' : 'hidden' }}
          onClick={(event) => {
            event.stopPropagation()
            setOpen((v) => !v)
          }}
          aria-label={open ? 'Collapse folder' : 'Expand folder'}
        >
          {open ? <ChevronDownIcon size={14} /> : <ChevronRightIcon size={14} />}
        </button>
        {open && hasChildren ? <FolderOpenIcon size={16} /> : <FolderIcon size={16} />}
        <span className="flex-1 truncate">{node.name}</span>
        {node.note_count > 0 && (
          <span className="text-[0.7rem]" style={{ color: 'var(--text-faint)' }}>
            {node.note_count}
          </span>
        )}
        {onContextMenu && (
          <button
            type="button"
            className="opacity-0 transition-opacity group-hover:opacity-100"
            onClick={(event) => {
              event.stopPropagation()
              onContextMenu(node)
            }}
            aria-label={`Manage folder ${node.name}`}
          >
            <TrashIcon size={14} />
          </button>
        )}
      </div>

      {open &&
        node.children?.map((child) => (
          <FolderRow
            key={child.id}
            node={child}
            depth={depth + 1}
            selectedId={selectedId}
            onSelect={onSelect}
            onContextMenu={onContextMenu}
          />
        ))}
    </div>
  )
}

/**
 * Scopes and the folder tree. Lives in the sidebar on wide screens and in a
 * collapsible panel above the note list on narrower ones, so folders are
 * reachable everywhere instead of only past the lg breakpoint.
 */
function FolderNav({ scope, setScope, counts, tree, onDeleteFolder, className = '' }) {
  return (
  <div className={`mc-scroll px-2 pb-4 ${className}`}>
    <div
      className="mc-nav-item cursor-pointer"
      aria-current={scope.kind === 'all' ? 'page' : undefined}
      onClick={() => setScope({ kind: 'all' })}
    >
      <NoteIcon size={16} />
      <span className="flex-1">All notes</span>
      <span className="text-[0.7rem]" style={{ color: 'var(--text-faint)' }}>{counts.total ?? 0}</span>
    </div>
    <div
      className="mc-nav-item cursor-pointer"
      aria-current={scope.kind === 'favorites' ? 'page' : undefined}
      onClick={() => setScope({ kind: 'favorites' })}
    >
      <StarIcon size={16} />
      <span className="flex-1">Favourites</span>
      <span className="text-[0.7rem]" style={{ color: 'var(--text-faint)' }}>{counts.favorites ?? 0}</span>
    </div>
    <div
      className="mc-nav-item cursor-pointer"
      aria-current={scope.kind === 'unfiled' ? 'page' : undefined}
      onClick={() => setScope({ kind: 'unfiled' })}
    >
      <FolderIcon size={16} />
      <span className="flex-1">Unfiled</span>
      <span className="text-[0.7rem]" style={{ color: 'var(--text-faint)' }}>{counts.unfiled ?? 0}</span>
    </div>

    <div
      className="mt-4 mb-1 px-3 text-[0.65rem] font-semibold uppercase tracking-[0.14em]"
      style={{ color: 'var(--text-faint)' }}
    >
      Folders
    </div>

    {tree === null ? (
      <div className="px-3 py-2"><Spinner size={14} /></div>
    ) : tree.length === 0 ? (
      <p className="px-3 py-2 text-xs" style={{ color: 'var(--text-faint)' }}>
        No folders yet.
      </p>
    ) : (
      tree.map((node) => (
        <FolderRow
          key={node.id}
          node={node}
          depth={0}
          selectedId={scope.kind === 'folder' ? scope.id : null}
          onSelect={(id) => setScope({ kind: 'folder', id })}
          onContextMenu={onDeleteFolder}
        />
      ))
    )}
  </div>
  )
}

const VIEW_KEY = 'meet-companion:note-view'

function NoteEditor({ note, onChange, onDelete, onBack, saving }) {
  const canDelete = useCan('delete_content')
  const canExport = useCan('export_workspace')
  const [draft, setDraft] = useState(note)
  const timer = useRef(null)
  // Preview by default for notes that already have content (the generated
  // meeting notes in particular); an empty note opens ready to type.
  const preferredMode = () => {
    try {
      return window.localStorage.getItem(VIEW_KEY) || 'preview'
    } catch {
      return 'preview'
    }
  }
  const [mode, setMode] = useState(() => (note.content ? preferredMode() : 'edit'))
  // Decided when a note is opened, not on every keystroke - otherwise the
  // first character typed into an empty note would flip it to preview.
  useEffect(() => {
    setMode(note.content ? preferredMode() : 'edit')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [note.id])
  const effectiveMode = mode

  function switchMode(next) {
    setMode(next)
    try {
      window.localStorage.setItem(VIEW_KEY, next)
    } catch {
      // Preference only.
    }
  }

  // Only reset the draft when a different note is opened. Re-syncing on every
  // prop change would overwrite what the user is typing each time a save
  // returns the freshly persisted record.
  useEffect(() => {
    setDraft(note)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [note.id])

  // After a save, follow the server for the timestamp - and for the content
  // when the server rewrote it (hand-written tasks get an action-item marker
  // appended) and the user has not typed anything since that save went out.
  const lastSent = useRef(null)
  useEffect(() => {
    setDraft((current) => {
      const next = { ...current, updated_at: note.updated_at }
      if (note.content !== current.content && current.content === lastSent.current) {
        next.content = note.content
      }
      return next.updated_at === current.updated_at && next.content === current.content ? current : next
    })
  }, [note.updated_at, note.content])

  // Debounced autosave: typing should not fire a request per keystroke, but
  // the user should never have to remember to press save.
  const queueSave = useCallback(
    (patch) => {
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => {
        if ('content' in patch) lastSent.current = patch.content
        onChange(patch)
      }, SAVE_DEBOUNCE_MS)
    },
    [onChange],
  )

  useEffect(() => () => timer.current && clearTimeout(timer.current), [])

  function edit(key, value) {
    setDraft((current) => ({ ...current, [key]: value }))
    queueSave({ [key]: value })
  }

  return (
    <div className="flex h-full flex-col">
      <div
        className="flex items-center gap-2 px-5 py-3"
        style={{ borderBottom: '1px solid var(--border-subtle)' }}
      >
        <button
          type="button"
          className="mc-btn mc-btn-ghost px-2 md:hidden"
          onClick={onBack}
          aria-label="Back to notes"
        >
          <ChevronLeftIcon size={18} />
        </button>
        <input
          className="mc-input border-transparent bg-transparent px-0 text-lg font-semibold"
          value={draft.title}
          onChange={(event) => edit('title', event.target.value)}
          placeholder="Untitled"
          aria-label="Note title"
        />
        <div
          className="flex rounded-lg p-0.5 text-xs"
          style={{ backgroundColor: 'var(--surface-sunken)' }}
          role="tablist"
          aria-label="Note view"
        >
          {['preview', 'edit'].map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={effectiveMode === value}
              className="rounded-md px-2.5 py-1 font-medium capitalize transition-colors"
              style={{
                backgroundColor: effectiveMode === value ? 'var(--surface-panel)' : 'transparent',
                color: effectiveMode === value ? 'var(--text-strong)' : 'var(--text-muted)',
                boxShadow: effectiveMode === value ? 'var(--elevation-card)' : 'none',
              }}
              onClick={() => switchMode(value)}
            >
              {value}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="mc-btn mc-btn-ghost px-2"
          onClick={() => onChange({ is_favorite: !draft.is_favorite })}
          aria-label={draft.is_favorite ? 'Remove from favourites' : 'Add to favourites'}
          title={draft.is_favorite ? 'Remove from favourites' : 'Add to favourites'}
          style={{ color: draft.is_favorite ? 'var(--color-peach-500)' : undefined }}
        >
          <StarIcon size={17} filled={draft.is_favorite} />
        </button>
        {canExport && (
          <ExportMenu
            compact
            label="Export note"
            options={[
              { href: exportNoteUrl(draft.id, 'md'), label: 'Markdown (.md)' },
              { href: exportNoteUrl(draft.id, 'json'), label: 'JSON (.json)' },
            ]}
          />
        )}
        {canDelete && (
          <button
            type="button"
            className="mc-btn mc-btn-ghost px-2"
            onClick={onDelete}
            aria-label="Delete note"
            title="Delete note"
          >
            <TrashIcon size={17} />
          </button>
        )}
      </div>

      <div
        className="flex flex-wrap items-center gap-2 px-5 py-2.5 text-xs"
        style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}
      >
        <select
          className="mc-input w-auto py-1 text-xs"
          value={draft.note_type}
          onChange={(event) => edit('note_type', event.target.value)}
          aria-label="Note type"
        >
          {NOTE_TYPES.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>

        <input
          className="mc-input w-auto flex-1 py-1 text-xs"
          placeholder="Tags, comma separated"
          value={(draft.tags || []).join(', ')}
          onChange={(event) =>
            edit(
              'tags',
              event.target.value
                .split(',')
                .map((tag) => tag.trim())
                .filter(Boolean),
            )
          }
          aria-label="Tags"
        />

        <span style={{ color: 'var(--text-faint)' }}>
          {saving ? 'Saving…' : draft.updated_at ? `Saved ${new Date(draft.updated_at).toLocaleString()}` : ''}
        </span>
      </div>

      {effectiveMode === 'preview' ? (
        <div className="mc-scroll flex-1 overflow-y-auto px-6 py-5" onDoubleClick={() => switchMode('edit')}>
          <Markdown
            source={draft.content}
            onToggleTask={(index, checked) => edit('content', toggleTaskInMarkdown(draft.content, index, checked))}
          />
        </div>
      ) : (
        <textarea
          className="mc-scroll flex-1 resize-none bg-transparent px-5 py-4 font-mono text-[0.85rem] leading-relaxed outline-none"
          style={{ color: 'var(--text-default)' }}
          value={draft.content || ''}
          onChange={(event) => edit('content', event.target.value)}
          placeholder="Start writing… Markdown is supported."
          aria-label="Note content"
          autoFocus
        />
      )}
    </div>
  )
}

export default function Notebook() {
  const canCreate = useCan('create_content')
  const canDelete = useCan('delete_content')
  const { noteId } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const [tree, setTree] = useState(null)
  const [counts, setCounts] = useState({})
  const [notes, setNotes] = useState([])
  const [total, setTotal] = useState(0)
  const [tags, setTags] = useState([])
  const [active, setActive] = useState(null)
  const [error, setError] = useState(null)
  const [loadingList, setLoadingList] = useState(true)
  const [saving, setSaving] = useState(false)

  const [scope, setScope] = useState({ kind: 'all' })
  const [foldersOpen, setFoldersOpen] = useState(false)
  // Seeded from ?q= so the header search actually lands somewhere, and so a
  // filtered view can be linked to or reloaded.
  const [query, setQuery] = useState(() => searchParams.get('q') || '')
  const [sort, setSort] = useState('updated')
  const [tagFilter, setTagFilter] = useState('')
  const [newFolderOpen, setNewFolderOpen] = useState(false)
  const [newFolderName, setNewFolderName] = useState('')
  const [folderToDelete, setFolderToDelete] = useState(null)

  // Keep the search box and ?q= in step in both directions: the header search
  // writes the URL, typing here writes it back. Each side only acts when the
  // values actually differ, so they converge rather than ping-pong.
  const urlQuery = searchParams.get('q') || ''

  useEffect(() => {
    setQuery((current) => (current === urlQuery ? current : urlQuery))
  }, [urlQuery])

  useEffect(() => {
    if (urlQuery === query) return
    const next = new URLSearchParams(searchParams)
    if (query) next.set('q', query)
    else next.delete('q')
    setSearchParams(next, { replace: true })
  }, [query, urlQuery, searchParams, setSearchParams])

  const refreshFolders = useCallback(async () => {
    const data = await listFolders()
    setTree(data.folders)
    setCounts(data.counts || {})
  }, [])

  const refreshNotes = useCallback(async () => {
    setLoadingList(true)
    try {
      const params = { sort, limit: 200 }
      if (query.trim()) params.q = query.trim()
      if (tagFilter) params.tag = tagFilter
      if (scope.kind === 'folder') params.folder_id = scope.id
      if (scope.kind === 'unfiled') params.unfiled = true
      if (scope.kind === 'favorites') params.favorites_only = true

      const data = await listNotes(params)
      setNotes(data.notes)
      setTotal(data.total)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingList(false)
    }
  }, [query, sort, tagFilter, scope])

  useEffect(() => {
    refreshFolders().catch((err) => setError(err.message))
    listNoteTags()
      .then((data) => setTags(data.tags))
      .catch(() => {})
  }, [refreshFolders])

  // Debounced so typing in search does not fire a request per keystroke.
  useEffect(() => {
    const handle = setTimeout(() => {
      refreshNotes()
    }, 220)
    return () => clearTimeout(handle)
  }, [refreshNotes])

  useEffect(() => {
    if (!noteId) {
      setActive(null)
      return
    }
    getNote(noteId)
      .then(setActive)
      .catch(() => navigate('/notebook', { replace: true }))
  }, [noteId, navigate])

  const [syncing, setSyncing] = useState(false)

  // New meetings are filed automatically when processing finishes; this
  // catches up meetings that predate the notebook or were imported.
  async function handleSyncMeetings() {
    setSyncing(true)
    try {
      await syncMeetingNotes()
      await Promise.all([refreshNotes(), refreshFolders()])
      listNoteTags().then((data) => setTags(data.tags)).catch(() => {})
    } catch (err) {
      setError(err.message)
    } finally {
      setSyncing(false)
    }
  }

  async function handleCreateNote() {
    const payload = { title: 'Untitled', content: '' }
    if (scope.kind === 'folder') payload.folder_id = scope.id
    const created = await createNote(payload)
    await Promise.all([refreshNotes(), refreshFolders()])
    navigate(`/notebook/${created.id}`)
  }

  async function handleUpdateNote(patch) {
    if (!active) return
    setSaving(true)
    try {
      const updated = await updateNote(active.id, patch)
      setActive(updated)
      await Promise.all([refreshNotes(), refreshFolders()])
      listNoteTags().then((data) => setTags(data.tags)).catch(() => {})
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleDeleteNote() {
    if (!active) return
    await deleteNote(active.id)
    navigate('/notebook')
    await Promise.all([refreshNotes(), refreshFolders()])
  }

  async function handleCreateFolder() {
    if (!newFolderName.trim()) return
    await createFolder({
      name: newFolderName.trim(),
      parent_id: scope.kind === 'folder' ? scope.id : null,
    })
    setNewFolderName('')
    setNewFolderOpen(false)
    await refreshFolders()
  }

  async function handleDeleteFolder(cascade) {
    await deleteFolder(folderToDelete.id, { cascade })
    setFolderToDelete(null)
    if (scope.kind === 'folder' && scope.id === folderToDelete.id) setScope({ kind: 'all' })
    await Promise.all([refreshFolders(), refreshNotes()])
  }

  const scopeLabel = useMemo(() => {
    if (scope.kind === 'favorites') return 'Favourites'
    if (scope.kind === 'unfiled') return 'Unfiled'
    if (scope.kind === 'folder') return 'Folder'
    return 'All notes'
  }, [scope])

  if (error) {
    return (
      <div className="p-8">
        <ErrorMessage title="Notebook unavailable" detail={error} onRetry={() => window.location.reload()} />
      </div>
    )
  }

  return (
    <div className="flex h-screen">
      {/* Folder tree */}
      <div
        className="hidden w-60 shrink-0 flex-col lg:flex"
        style={{ borderRight: '1px solid var(--border-subtle)', backgroundColor: 'var(--surface-nav)' }}
      >
        <div className="flex items-center justify-between px-4 py-4">
          <h2 className="text-sm font-semibold">Notebook</h2>
          {canCreate && (
            <button
              type="button"
              className="mc-btn mc-btn-ghost px-2"
              onClick={() => setNewFolderOpen(true)}
              title="New folder"
              aria-label="New folder"
            >
              <PlusIcon size={16} />
            </button>
          )}
        </div>

        <FolderNav
          scope={scope}
          setScope={setScope}
          counts={counts}
          tree={tree}
          onDeleteFolder={canDelete ? setFolderToDelete : undefined}
          className="flex-1 overflow-y-auto"
        />
      </div>

      {/* Note list. On small screens the list and the editor share the width:
          opening a note replaces the list, and the editor offers a way back. */}
      <div
        className={`${noteId ? 'hidden md:flex' : 'flex'} w-full shrink-0 flex-col md:w-80`}
        style={{ borderRight: '1px solid var(--border-subtle)', backgroundColor: 'var(--surface-panel)' }}
      >
        <div className="px-4 py-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
          <div className="mb-2 flex items-center justify-between">
            <button
              type="button"
              className="flex items-center gap-1 text-sm font-semibold lg:pointer-events-none"
              onClick={() => setFoldersOpen((open) => !open)}
              aria-expanded={foldersOpen}
              aria-controls="notebook-folder-panel"
            >
              {scopeLabel}
              <span className="lg:hidden" style={{ color: 'var(--text-faint)' }}>
                {foldersOpen ? <ChevronDownIcon size={14} /> : <ChevronRightIcon size={14} />}
              </span>
            </button>
            {canCreate && (
              <button type="button" className="mc-btn mc-btn-primary px-2 py-1" onClick={handleCreateNote}>
                <PlusIcon size={15} /> New
              </button>
            )}
          </div>

          {/* Below lg the sidebar is gone; the same navigation folds out here. */}
          {foldersOpen && (
            <div
              id="notebook-folder-panel"
              className="mb-3 rounded-lg lg:hidden"
              style={{ backgroundColor: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)' }}
            >
              <div className="flex items-center justify-between px-3 pt-2">
                <span className="text-[0.65rem] font-semibold uppercase tracking-[0.14em]" style={{ color: 'var(--text-faint)' }}>
                  Browse
                </span>
                {canCreate && (
                  <button
                    type="button"
                    className="mc-btn mc-btn-ghost px-1.5 py-0.5"
                    onClick={() => setNewFolderOpen(true)}
                    title="New folder"
                    aria-label="New folder"
                  >
                    <PlusIcon size={14} />
                  </button>
                )}
              </div>
              <FolderNav
                scope={scope}
                setScope={(next) => {
                  setScope(next)
                  setFoldersOpen(false)
                }}
                counts={counts}
                tree={tree}
                onDeleteFolder={canDelete ? setFolderToDelete : undefined}
                className="max-h-64 overflow-y-auto"
              />
            </div>
          )}

          <div className="relative">
            <span className="absolute left-2.5 top-2.5" style={{ color: 'var(--text-faint)' }}>
              <SearchIcon size={15} />
            </span>
            <input
              className="mc-input pl-8 text-sm"
              placeholder="Search notes…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label="Search notes"
            />
          </div>

          <div className="mt-2 flex gap-1.5">
            <select
              className="mc-input py-1 text-xs"
              value={sort}
              onChange={(event) => setSort(event.target.value)}
              aria-label="Sort notes"
            >
              {SORTS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
            <select
              className="mc-input py-1 text-xs"
              value={tagFilter}
              onChange={(event) => setTagFilter(event.target.value)}
              aria-label="Filter by tag"
            >
              <option value="">All tags</option>
              {tags.map((tag) => (
                <option key={tag} value={tag}>{tag}</option>
              ))}
            </select>
          </div>

          {(query || tagFilter || scope.kind !== 'all') && (
            <button
              type="button"
              className="mt-2 text-xs"
              style={{ color: 'var(--brand-soft-text)' }}
              onClick={() => {
                setQuery('')
                setTagFilter('')
                setScope({ kind: 'all' })
              }}
            >
              Clear filters · {total} match{total === 1 ? '' : 'es'}
            </button>
          )}
        </div>

        <div className="mc-scroll flex-1 overflow-y-auto">
          {loadingList ? (
            <Loading />
          ) : notes.length === 0 ? (
            <EmptyState
              icon={<NoteIcon size={22} />}
              title={query || tagFilter ? 'No matching notes' : 'No notes yet'}
              description={
                query || tagFilter
                  ? 'Try a different search or clear your filters.'
                  : 'Every processed meeting is filed here automatically. Create a note, or bring in the meetings you already have.'
              }
              action={
                !query && !tagFilter && canCreate ? (
                  <div className="flex flex-wrap justify-center gap-2">
                    <button type="button" className="mc-btn mc-btn-primary" onClick={handleSyncMeetings} disabled={syncing}>
                      {syncing ? <Spinner size={14} /> : null} Generate from meetings
                    </button>
                    <button type="button" className="mc-btn mc-btn-secondary" onClick={handleCreateNote}>
                      New note
                    </button>
                  </div>
                ) : null
              }
            />
          ) : (
            <ul className="divide-y" style={{ borderColor: 'var(--border-subtle)' }}>
              {notes.map((note) => (
                <li key={note.id}>
                  <button
                    type="button"
                    className="w-full px-4 py-3 text-left transition-colors hover:bg-[var(--surface-raised)]"
                    style={{
                      backgroundColor: note.id === noteId ? 'var(--brand-soft)' : undefined,
                    }}
                    onClick={() => navigate(`/notebook/${note.id}`)}
                  >
                    <div className="flex items-start gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm font-medium" style={{ color: 'var(--text-strong)' }}>
                        {note.title}
                      </span>
                      {note.is_favorite && (
                        <StarIcon size={13} filled style={{ color: 'var(--color-peach-500)' }} />
                      )}
                    </div>
                    {note.excerpt && (
                      <p className="mt-0.5 line-clamp-2 text-xs" style={{ color: 'var(--text-muted)' }}>
                        {note.excerpt}
                      </p>
                    )}
                    <div className="mt-1.5 flex flex-wrap items-center gap-1">
                      {(note.tags || []).slice(0, 3).map((tag) => (
                        <Badge key={tag}>{tag}</Badge>
                      ))}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Editor */}
      <div
        className={`${noteId ? 'block' : 'hidden'} min-w-0 flex-1 md:block`}
        style={{ backgroundColor: 'var(--surface-panel)' }}
      >
        {active ? (
          <NoteEditor
            key={active.id}
            note={active}
            onChange={handleUpdateNote}
            onDelete={handleDeleteNote}
            onBack={() => navigate('/notebook')}
            saving={saving}
          />
        ) : (
          <EmptyState
            icon={<NoteIcon size={22} />}
            title="Select a note"
            description="Choose a note from the list, or create a new one."
          />
        )}
      </div>

      <Modal
        open={newFolderOpen}
        onClose={() => setNewFolderOpen(false)}
        title="New folder"
        footer={
          <>
            <button type="button" className="mc-btn mc-btn-secondary" onClick={() => setNewFolderOpen(false)}>
              Cancel
            </button>
            <button type="button" className="mc-btn mc-btn-primary" onClick={handleCreateFolder}>
              Create
            </button>
          </>
        }
      >
        <input
          className="mc-input"
          autoFocus
          placeholder="Folder name"
          value={newFolderName}
          onChange={(event) => setNewFolderName(event.target.value)}
          onKeyDown={(event) => event.key === 'Enter' && handleCreateFolder()}
          aria-label="Folder name"
        />
      </Modal>

      <Modal
        open={Boolean(folderToDelete)}
        onClose={() => setFolderToDelete(null)}
        title={`Delete "${folderToDelete?.name || ''}"`}
        footer={
          <>
            <button type="button" className="mc-btn mc-btn-secondary" onClick={() => setFolderToDelete(null)}>
              Cancel
            </button>
            <button type="button" className="mc-btn mc-btn-secondary" onClick={() => handleDeleteFolder(false)}>
              Keep notes
            </button>
            <button type="button" className="mc-btn mc-btn-danger" onClick={() => handleDeleteFolder(true)}>
              Delete everything
            </button>
          </>
        }
      >
        <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
          <strong>Keep notes</strong> moves this folder's notes and subfolders up one level.{' '}
          <strong>Delete everything</strong> permanently removes the folder and all of its contents.
        </p>
      </Modal>
    </div>
  )
}
