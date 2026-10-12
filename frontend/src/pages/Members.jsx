import { useEffect, useState } from 'react'
import { Page, PageHeader } from '../components/AppShell'
import { MembersIcon } from '../components/Icons'
import { Badge, Card, EmptyState, ErrorMessage, Field, Loading, Modal, Spinner } from '../components/ui'
import { addMember, approveMember, deleteWorkspace, getProviderCatalog, getWorkspace, listMembers, regenerateJoinCode, removeMember, renameWorkspace, resetMemberPassword, setMemberRole, setWorkspaceAI, setWorkspacePermissions, testWorkspaceAI } from '../api'
import ProviderFields from '../components/ProviderFields'
import { useCan, useIsOwner, useUser } from '../user'

export default function Members() {
  const me = useUser()
  const isOwner = useIsOwner()
  const canInvite = useCan('invite_members')
  const [members, setMembers] = useState(null)
  const [pending, setPending] = useState([])
  const [workspace, setWorkspace] = useState(null)
  const [error, setError] = useState(null)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [resetting, setResetting] = useState(null)
  const [newPassword, setNewPassword] = useState('')
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [busy, setBusy] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [newName, setNewName] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState('')

  async function load() {
    try {
      const [memberList, workspaceData] = await Promise.all([
        listMembers(),
        getWorkspace().catch(() => null),
      ])
      setMembers(memberList.members || memberList || [])
      setPending(memberList.pending || [])
      setWorkspace(workspaceData)
    } catch (err) {
      setError(err.message)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function invite(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await addMember({ ...form, join_code: workspace?.join_code })
      setForm({ name: '', email: '', password: '' })
      setInviteOpen(false)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function handleApprove(person) {
    setError(null)
    await approveMember(person.id).catch((err) => setError(err.message))
    await load()
  }

  async function handleDecline(person) {
    if (!window.confirm(`Decline ${person.name || person.email}? They will need to ask again with the join code.`)) return
    setError(null)
    await removeMember(person.id).catch((err) => setError(err.message))
    await load()
  }

  async function handleRemove(member) {
    if (!window.confirm(`Remove ${member.name || member.email} from this workspace?`)) return
    await removeMember(member.id).catch((err) => setError(err.message))
    await load()
  }

  async function handleRename(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await renameWorkspace(newName)
      setRenaming(false)
      // The name also sits in the workspace picker up top; a reload is the
      // simplest way to get every copy of it in step.
      window.location.reload()
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  async function handleNewCode() {
    if (!window.confirm('Issue a new join code? The current one stops working immediately. People already in the workspace are not affected.')) return
    setError(null)
    try {
      const result = await regenerateJoinCode()
      setWorkspace({ ...workspace, join_code: result.join_code })
    } catch (err) {
      setError(err.message)
    }
  }

  async function handleDelete(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await deleteWorkspace()
      // The server has already moved us to another workspace.
      window.location.reload()
    } catch (err) {
      setError(err.message)
      setDeleting(false)
      setBusy(false)
    }
  }

  async function handleResetPassword(event) {
    event.preventDefault()
    setBusy(true)
    try {
      await resetMemberPassword(resetting.id, newPassword)
      setResetting(null)
      setNewPassword('')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (members === null && !error) return <Page><Loading /></Page>

  return (
    <Page>
      <PageHeader
        title="Members"
        description="People who share this workspace's meetings, notes and memory."
        actions={
          canInvite && (
            <button type="button" className="mc-btn mc-btn-primary" onClick={() => setInviteOpen(true)}>
              Add member
            </button>
          )
        }
      />

      {error && <div className="mb-4"><ErrorMessage title="Something went wrong" detail={error} /></div>}

      {workspace?.join_code && (
        <Card className="mb-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="truncate text-sm font-semibold">{workspace.name || 'Workspace'}</h2>
                {isOwner && (
                  <button
                    type="button"
                    className="text-xs underline-offset-2 hover:underline"
                    style={{ color: 'var(--text-muted)' }}
                    onClick={() => { setNewName(workspace.name || ''); setRenaming(true) }}
                  >
                    Rename
                  </button>
                )}
              </div>
              <p className="mt-0.5 text-sm" style={{ color: 'var(--text-muted)' }}>
                Share this join code so a teammate can ask to join. You approve each request here;
                {' '}the code keeps working until it is replaced.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <code
                className="rounded-lg px-3 py-1.5 text-sm font-semibold"
                style={{ backgroundColor: 'var(--surface-raised)', color: 'var(--text-strong)' }}
              >
                {workspace.join_code}
              </code>
              {isOwner && (
                <button type="button" className="mc-btn mc-btn-secondary" onClick={handleNewCode} title="Replace the join code">
                  New code
                </button>
              )}
            </div>
          </div>
        </Card>
      )}

      {isOwner && pending.length > 0 && (
        <Card className="mb-4" padded={false}>
          <div className="px-5 pt-4 pb-2">
            <h2 className="text-sm font-semibold">Requests to join</h2>
            <p className="mt-0.5 text-sm" style={{ color: 'var(--text-muted)' }}>
              People who used the join code. They cannot see anything here until you let them in.
            </p>
          </div>
          <ul className="divide-y" style={{ borderColor: 'var(--border-subtle)' }}>
            {pending.map((person) => (
              <li key={person.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium" style={{ color: 'var(--text-strong)' }}>
                    {person.name || person.email}
                  </div>
                  <div className="truncate text-xs" style={{ color: 'var(--text-faint)' }}>
                    {person.email}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button type="button" className="mc-btn mc-btn-primary" onClick={() => handleApprove(person)}>
                    Approve
                  </button>
                  <button type="button" className="mc-btn mc-btn-secondary" onClick={() => handleDecline(person)}>
                    Decline
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {isOwner && workspace?.permissions && (
        <PermissionsPanel workspace={workspace} onSaved={(member_permissions) => setWorkspace({ ...workspace, member_permissions })} />
      )}

      {workspace?.ai && (isOwner ? (
        <WorkspaceAIPanel workspace={workspace} onSaved={(ai) => setWorkspace({ ...workspace, ai })} />
      ) : (
        <Card className="mb-4">
          <h2 className="text-sm font-semibold">AI provider</h2>
          <p className="mt-0.5 text-sm" style={{ color: 'var(--text-muted)' }}>
            {workspace.ai.mode === 'workspace'
              ? `Everyone in this workspace uses ${workspace.ai.provider}${workspace.ai.model ? ` (${workspace.ai.model})` : ''}, chosen by an owner. Your own AI settings apply to your other workspaces.`
              : 'Each member uses the AI provider from their own Settings.'}
          </p>
        </Card>
      ))}

      <Card padded={false}>
        {(members || []).length === 0 ? (
          <EmptyState icon={<MembersIcon size={22} />} title="No members yet" />
        ) : (
          <ul className="divide-y" style={{ borderColor: 'var(--border-subtle)' }}>
            {members.map((member) => (
              <li key={member.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium" style={{ color: 'var(--text-strong)' }}>
                    {member.name || member.email}
                  </div>
                  <div className="truncate text-xs" style={{ color: 'var(--text-faint)' }}>
                    {member.email}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {member.role && <Badge tone={member.role === 'owner' ? 'brand' : 'neutral'}>{member.role}</Badge>}
                  {isOwner && (
                    <>
                      <button
                        type="button"
                        className="mc-btn mc-btn-secondary"
                        title={member.role === 'owner' ? 'Demote to member' : 'Make owner'}
                        onClick={async () => {
                          setError(null)
                          await setMemberRole(member.id, member.role === 'owner' ? 'member' : 'owner').catch((err) =>
                            setError(err.message),
                          )
                          await load()
                        }}
                      >
                        {member.role === 'owner' ? 'Make member' : 'Make owner'}
                      </button>
                      <button
                        type="button"
                        className="mc-btn mc-btn-secondary"
                        onClick={() => setResetting(member)}
                      >
                        Reset password
                      </button>
                    </>
                  )}
                  {(isOwner || member.id === me?.id) && (
                    <button type="button" className="mc-btn mc-btn-danger" onClick={() => handleRemove(member)}>
                      {member.id === me?.id ? 'Leave' : 'Remove'}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {isOwner && workspace && (
        <Card className="mt-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">Delete this workspace</h2>
              <p className="mt-0.5 text-sm" style={{ color: 'var(--text-muted)' }}>
                Removes every meeting, note, document and memory in it. Cannot be undone.
                Remove the other members first, and keep another workspace to land in.
              </p>
            </div>
            <button type="button" className="mc-btn mc-btn-danger" onClick={() => { setDeleteConfirm(''); setDeleting(true) }}>
              Delete workspace
            </button>
          </div>
        </Card>
      )}

      <Modal open={renaming} onClose={() => setRenaming(false)} title="Rename workspace">
        <form onSubmit={handleRename}>
          <Field label="Workspace name" htmlFor="workspace-name">
            <input
              id="workspace-name"
              className="mc-input"
              required
              maxLength={255}
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
            />
          </Field>
          <button type="submit" className="mc-btn mc-btn-primary w-full" disabled={busy || !newName.trim()}>
            {busy ? <Spinner size={14} /> : null} Save name
          </button>
        </form>
      </Modal>

      <Modal open={deleting} onClose={() => setDeleting(false)} title={`Delete ${workspace?.name || 'this workspace'}?`}>
        <form onSubmit={handleDelete}>
          <p className="mb-4 text-sm" style={{ color: 'var(--text-muted)' }}>
            Everything in this workspace is deleted permanently. Type the workspace name to confirm.
          </p>
          <Field label="Workspace name" htmlFor="delete-confirm">
            <input
              id="delete-confirm"
              className="mc-input"
              autoComplete="off"
              value={deleteConfirm}
              onChange={(event) => setDeleteConfirm(event.target.value)}
            />
          </Field>
          <button
            type="submit"
            className="mc-btn mc-btn-danger w-full"
            disabled={busy || deleteConfirm.trim() !== (workspace?.name || '').trim()}
          >
            {busy ? <Spinner size={14} /> : null} Delete permanently
          </button>
        </form>
      </Modal>

      <Modal open={inviteOpen} onClose={() => setInviteOpen(false)} title="Add a member">
        <form onSubmit={invite}>
          <Field label="Name" htmlFor="member-name">
            <input
              id="member-name"
              className="mc-input"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
          </Field>
          <Field label="Email" htmlFor="member-email">
            <input
              id="member-email"
              type="email"
              required
              className="mc-input"
              value={form.email}
              onChange={(event) => setForm({ ...form, email: event.target.value })}
            />
          </Field>
          <Field label="Temporary password" htmlFor="member-password">
            <input
              id="member-password"
              type="password"
              required
              className="mc-input"
              value={form.password}
              onChange={(event) => setForm({ ...form, password: event.target.value })}
            />
          </Field>
          <button type="submit" className="mc-btn mc-btn-primary w-full" disabled={busy}>
            {busy ? <Spinner size={14} /> : null} Add member
          </button>
        </form>
      </Modal>

      <Modal
        open={Boolean(resetting)}
        onClose={() => setResetting(null)}
        title={`Reset password for ${resetting?.name || resetting?.email || ''}`}
      >
        <form onSubmit={handleResetPassword}>
          <Field label="New password" htmlFor="new-password">
            <input
              id="new-password"
              type="password"
              required
              className="mc-input"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
            />
          </Field>
          <button type="submit" className="mc-btn mc-btn-primary w-full" disabled={busy}>
            {busy ? <Spinner size={14} /> : null} Set password
          </button>
        </form>
      </Modal>
    </Page>
  )
}


/**
 * Who chooses the AI for this workspace. Owner-only.
 *
 * "member": every member's own install uses its own Settings - their key,
 * their bill. "workspace": the owner sets one provider here and every
 * member's app uses it in this workspace, so summaries read the same
 * whoever imported the meeting. The key is stored with the workspace and
 * never shown back; a blank key box on save keeps the stored one.
 */
function WorkspaceAIPanel({ workspace, onSaved }) {
  const stored = workspace.ai
  const [mode, setMode] = useState(stored.mode)
  const [catalog, setCatalog] = useState(null)
  const [provider, setProvider] = useState(stored.provider || 'openai')
  const [values, setValues] = useState({ model: stored.model || '', base_url: stored.base_url || '', api_key: '' })
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    getProviderCatalog()
      .then((data) => !cancelled && setCatalog(data))
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [])

  // A local provider runs on each member's own machine, so it cannot be the
  // one everyone shares; only hosted providers are offered here.
  const hosted = catalog?.llm.filter((item) => !item.local) || []
  const descriptor = hosted.find((item) => item.name === provider) || null

  function payload() {
    return {
      mode,
      provider,
      model: values.model || null,
      base_url: values.base_url || null,
      api_key: values.api_key || null,
    }
  }

  async function chooseMode(next) {
    setMode(next)
    setSaved(false)
    setError(null)
    if (next === 'member') {
      // Nothing else to fill in: save straight away.
      setBusy(true)
      try {
        onSaved(await setWorkspaceAI({ mode: 'member' }))
        setSaved(true)
      } catch (err) {
        setError(err.message)
      } finally {
        setBusy(false)
      }
    }
  }

  async function save() {
    setBusy(true)
    setSaved(false)
    setError(null)
    try {
      onSaved(await setWorkspaceAI(payload()))
      setValues((current) => ({ ...current, api_key: '' }))
      setSaved(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function runTest() {
    setBusy(true)
    setTestResult(null)
    try {
      setTestResult(await testWorkspaceAI(payload()))
    } catch (err) {
      setTestResult({ ok: false, detail: err.message })
    } finally {
      setBusy(false)
    }
  }

  const choices = [
    ['member', 'Each member uses their own', 'Whatever each person set in their Settings — their key, their bill, their model.'],
    ['workspace', 'One provider for everyone', 'Set it here; every member uses it in this workspace, so summaries read the same whoever imported the meeting.'],
  ]

  return (
    <Card className="mb-4">
      <h2 className="text-sm font-semibold">AI provider</h2>
      <p className="mt-0.5 mb-3 text-sm" style={{ color: 'var(--text-muted)' }}>
        Used for meeting summaries, memory extraction and Ask AI in this workspace.
      </p>
      {error && <div className="mb-3"><ErrorMessage title="Could not save" detail={error} /></div>}
      <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="AI provider">
        {choices.map(([value, title, blurb]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={mode === value}
            disabled={busy}
            onClick={() => chooseMode(value)}
            className="rounded-xl border p-3 text-left"
            style={{
              borderColor: mode === value ? 'var(--brand-ring)' : 'var(--border-subtle)',
              backgroundColor: mode === value ? 'var(--brand-soft)' : 'transparent',
            }}
          >
            <div className="text-sm font-medium" style={{ color: 'var(--text-strong)' }}>{title}</div>
            <p className="mt-0.5 text-xs" style={{ color: 'var(--text-muted)' }}>{blurb}</p>
          </button>
        ))}
      </div>

      {mode === 'workspace' && catalog && (
        <div className="mt-4 border-t pt-4" style={{ borderColor: 'var(--border-subtle)' }}>
          <Field label="Provider" htmlFor="ws-ai-provider">
            <select
              id="ws-ai-provider"
              className="mc-input"
              value={provider}
              disabled={busy}
              onChange={(event) => {
                const next = hosted.find((item) => item.name === event.target.value)
                setProvider(event.target.value)
                setTestResult(null)
                setSaved(false)
                const defaults = {}
                next?.fields.forEach((field) => {
                  if (field.default !== null && field.default !== undefined) defaults[field.key] = field.default
                })
                setValues({ model: '', base_url: '', api_key: '', ...defaults })
              }}
            >
              {hosted.map((item) => (
                <option key={item.name} value={item.name}>{item.label}</option>
              ))}
            </select>
          </Field>
          <p className="-mt-2 mb-4 text-xs" style={{ color: 'var(--text-faint)' }}>
            Hosted providers only: a local one such as Ollama runs on each person's own machine, so it cannot be shared.
          </p>
          {descriptor && (
            <ProviderFields
              descriptor={descriptor}
              values={values}
              onChange={(key, value) => {
                setValues((current) => ({ ...current, [key]: value }))
                setSaved(false)
              }}
              discoveredModels={testResult?.models || []}
              keyHint={
                stored.api_key && stored.provider === provider
                  ? `Currently set (${stored.api_key}). Leave blank to keep it.`
                  : undefined
              }
            />
          )}
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className="mc-btn mc-btn-primary" onClick={save} disabled={busy}>
              {busy ? <Spinner size={14} /> : null} Save for everyone
            </button>
            <button type="button" className="mc-btn mc-btn-secondary" onClick={runTest} disabled={busy}>
              Test connection
            </button>
            {saved && <span className="text-sm" style={{ color: 'var(--color-brand-600)' }}>Saved.</span>}
            {testResult && (
              <span className="text-sm" style={{ color: testResult.ok ? 'var(--color-brand-600)' : 'var(--color-rose-700)' }}>
                {testResult.ok ? 'Connected.' : testResult.detail}
              </span>
            )}
          </div>
        </div>
      )}
      {mode === 'member' && saved && <p className="mt-3 text-sm" style={{ color: 'var(--color-brand-600)' }}>Saved.</p>}
    </Card>
  )
}


/**
 * What members of this workspace may do. Owner-only; each switch saves on
 * change. Owners themselves are never restricted, which the copy says.
 */
function PermissionsPanel({ workspace, onSaved }) {
  const [saving, setSaving] = useState(null)
  const [error, setError] = useState(null)
  const current = workspace.member_permissions || {}

  async function toggle(key) {
    setSaving(key)
    setError(null)
    try {
      const result = await setWorkspacePermissions({ [key]: !current[key] })
      onSaved(result.member_permissions)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(null)
    }
  }

  return (
    <Card className="mb-4">
      <h2 className="text-sm font-semibold">What members can do</h2>
      <p className="mt-0.5 mb-3 text-sm" style={{ color: 'var(--text-muted)' }}>
        Applies to everyone in this workspace who is not an owner. Owners can always do everything.
      </p>
      {error && <div className="mb-3"><ErrorMessage title="Could not save" detail={error} /></div>}
      <ul className="divide-y" style={{ borderColor: 'var(--border-subtle)' }}>
        {workspace.permissions.map((perm) => {
          const on = Boolean(current[perm.key])
          return (
            <li key={perm.key} className="flex items-start justify-between gap-4 py-3">
              <div className="min-w-0">
                <div className="text-sm font-medium" style={{ color: 'var(--text-strong)' }}>{perm.label}</div>
                <p className="mt-0.5 text-xs" style={{ color: 'var(--text-muted)' }}>{perm.description}</p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={on}
                aria-label={perm.label}
                disabled={saving !== null}
                onClick={() => toggle(perm.key)}
                className="relative mt-0.5 inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors"
                style={{ backgroundColor: on ? 'var(--brand-ring)' : 'var(--surface-raised)', border: '1px solid var(--border-subtle)' }}
              >
                <span
                  className="inline-block h-4 w-4 rounded-full transition-transform"
                  style={{ backgroundColor: on ? 'white' : 'var(--text-faint)', transform: on ? 'translateX(1.4rem)' : 'translateX(0.2rem)' }}
                />
                {saving === perm.key && <span className="sr-only">Saving</span>}
              </button>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
