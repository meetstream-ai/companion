import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({
  addMember: vi.fn(),
  getWorkspace: vi.fn(),
  listMembers: vi.fn(),
  removeMember: vi.fn(),
  resetMemberPassword: vi.fn(),
  setMemberRole: vi.fn(),
  setWorkspacePermissions: vi.fn(),
  renameWorkspace: vi.fn(),
  regenerateJoinCode: vi.fn(),
  deleteWorkspace: vi.fn(),
  approveMember: vi.fn(),
  getProviderCatalog: vi.fn(),
  setWorkspaceAI: vi.fn(),
  testWorkspaceAI: vi.fn(),
}))
import { approveMember, deleteWorkspace, getProviderCatalog, getWorkspace, listMembers, regenerateJoinCode, removeMember, renameWorkspace, setWorkspaceAI, setWorkspacePermissions, testWorkspaceAI } from '../api'
import Members from '../pages/Members'
import { UserContext } from '../user'

const permissions = [
  { key: 'create_content', label: 'Add content', description: 'd', default: true },
  { key: 'delete_content', label: 'Delete content', description: 'd', default: false },
]
const members = { members: [
  { id: 'u-owner', name: 'Owner', email: 'owner@x.test', role: 'owner' },
  { id: 'u-member', name: 'Member', email: 'member@x.test', role: 'member' },
] }

function renderAs(user) {
  return render(
    <UserContext.Provider value={user}>
      <Members />
    </UserContext.Provider>,
  )
}

describe('Members page permissions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listMembers.mockResolvedValue(members)
  })

  it('lets an owner see the join code, the panel, and flip a permission that saves', async () => {
    getWorkspace.mockResolvedValue({
      name: 'Acme', join_code: 'abc123', permissions,
      member_permissions: { create_content: true, delete_content: false },
    })
    setWorkspacePermissions.mockResolvedValue({ member_permissions: { create_content: true, delete_content: true } })
    renderAs({ id: 'u-owner', role: 'owner', permissions: { invite_members: true } })

    expect(await screen.findByText('abc123')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add member' })).toBeInTheDocument()
    const del = await screen.findByRole('switch', { name: 'Delete content' })
    expect(del).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByRole('switch', { name: 'Add content' })).toHaveAttribute('aria-checked', 'true')

    fireEvent.click(del)
    await waitFor(() => expect(setWorkspacePermissions).toHaveBeenCalledWith({ delete_content: true }))
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Delete content' })).toHaveAttribute('aria-checked', 'true'))
  })

  it('shows a member neither the panel, the join code, nor Add member - only Leave on themselves', async () => {
    getWorkspace.mockResolvedValue({ name: 'Acme', join_code: null, permissions, member_permissions: { create_content: true, delete_content: false } })
    renderAs({ id: 'u-member', role: 'member', permissions: { invite_members: false } })

    await screen.findByText('member@x.test')
    expect(screen.queryByRole('switch')).toBeNull()
    expect(screen.queryByText('What members can do')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Add member' })).toBeNull()
    expect(screen.queryByRole('button', { name: /Make owner|Make member|Reset password|^Remove$/ })).toBeNull()
    const me = screen.getByText('member@x.test').closest('li')
    expect(within(me).getByRole('button', { name: 'Leave' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Rename|New code|Delete workspace/ })).toBeNull()
  })
})

describe('Members page workspace controls (owner)', () => {
  const owner = { id: 'u-owner', role: 'owner', permissions: { invite_members: true } }

  beforeEach(() => {
    vi.clearAllMocks()
    listMembers.mockResolvedValue(members)
    getWorkspace.mockResolvedValue({
      name: 'Acme', join_code: 'abc123', permissions,
      member_permissions: { create_content: true, delete_content: false },
    })
    Object.defineProperty(window, 'location', { value: { reload: vi.fn(), pathname: '/' }, writable: true })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('issues a new join code in place', async () => {
    regenerateJoinCode.mockResolvedValue({ join_code: 'zzz999' })
    renderAs(owner)
    await screen.findByText('abc123')
    fireEvent.click(screen.getByRole('button', { name: 'New code' }))
    expect(await screen.findByText('zzz999')).toBeInTheDocument()
    expect(screen.queryByText('abc123')).toBeNull()
  })

  it('renames the workspace and reloads so the picker follows', async () => {
    renameWorkspace.mockResolvedValue({ id: 'o1', name: 'Acme Corp' })
    renderAs(owner)
    await screen.findByText('abc123')
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }))
    const input = screen.getByLabelText('Workspace name')
    expect(input).toHaveValue('Acme')
    fireEvent.change(input, { target: { value: 'Acme Corp' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save name' }))
    await waitFor(() => expect(renameWorkspace).toHaveBeenCalledWith('Acme Corp'))
    await waitFor(() => expect(window.location.reload).toHaveBeenCalled())
  })

  it('deletion needs the name typed back, and a refusal is shown rather than swallowed', async () => {
    deleteWorkspace.mockRejectedValue(new Error('Remove the other members from this workspace before deleting it.'))
    renderAs(owner)
    await screen.findByText('abc123')
    fireEvent.click(screen.getByRole('button', { name: 'Delete workspace' }))
    const confirm = screen.getByRole('button', { name: 'Delete permanently' })
    expect(confirm).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Workspace name'), { target: { value: 'Acme' } })
    expect(confirm).toBeEnabled()
    fireEvent.click(confirm)
    expect(await screen.findByText('Remove the other members from this workspace before deleting it.')).toBeInTheDocument()
    expect(window.location.reload).not.toHaveBeenCalled()

    deleteWorkspace.mockResolvedValue({ deleted: true, active_workspace_id: 'o2' })
    fireEvent.click(screen.getByRole('button', { name: 'Delete workspace' }))
    fireEvent.change(screen.getByLabelText('Workspace name'), { target: { value: 'Acme' } })
    fireEvent.click(screen.getByRole('button', { name: 'Delete permanently' }))
    await waitFor(() => expect(window.location.reload).toHaveBeenCalled())
  })
})


describe('Members page join requests', () => {
  const owner = { id: 'u-owner', role: 'owner', permissions: { invite_members: true } }
  const withRequest = { ...members, pending: [
    { id: 'u-ask', name: 'Asker', email: 'asker@x.test', role: 'member', status: 'pending', requested_at: '2026-09-17T10:00:00+00:00' },
  ] }

  beforeEach(() => {
    vi.clearAllMocks()
    getWorkspace.mockResolvedValue({
      name: 'Acme', join_code: 'abc123', permissions,
      member_permissions: { create_content: true, delete_content: false },
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('shows an owner the people waiting, and approves one', async () => {
    listMembers.mockResolvedValueOnce(withRequest).mockResolvedValueOnce({ ...members, pending: [] })
    approveMember.mockResolvedValue({ id: 'u-ask', role: 'member' })
    renderAs(owner)
    expect(await screen.findByText('Requests to join')).toBeInTheDocument()
    const row = screen.getByText('asker@x.test').closest('li')
    fireEvent.click(within(row).getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(approveMember).toHaveBeenCalledWith('u-ask'))
    await waitFor(() => expect(screen.queryByText('Requests to join')).toBeNull())
  })

  it('declining goes through removal, after a confirm', async () => {
    listMembers.mockResolvedValueOnce(withRequest).mockResolvedValueOnce({ ...members, pending: [] })
    removeMember.mockResolvedValue({ removed: true, account_deleted: true })
    renderAs(owner)
    const row = (await screen.findByText('asker@x.test')).closest('li')
    fireEvent.click(within(row).getByRole('button', { name: 'Decline' }))
    await waitFor(() => expect(removeMember).toHaveBeenCalledWith('u-ask'))
    expect(window.confirm).toHaveBeenCalled()
    expect(approveMember).not.toHaveBeenCalled()
  })

  it('a member sees no requests card even if the payload carried one', async () => {
    listMembers.mockResolvedValue(withRequest)
    renderAs({ id: 'u-member', role: 'member', permissions: { invite_members: false } })
    await screen.findByText('member@x.test')
    expect(screen.queryByText('Requests to join')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
  })
})

describe('Members page AI provider', () => {
  const owner = { id: 'u-owner', role: 'owner', permissions: { invite_members: true } }
  const catalog = { llm: [
    { name: 'ollama', label: 'Ollama (local)', local: true, fields: [{ key: 'model', label: 'Model', type: 'text', required: true, default: 'llama3.1' }], suggested_models: ['llama3.1'] },
    { name: 'openai', label: 'OpenAI', fields: [{ key: 'model', label: 'Model', type: 'text', required: true }, { key: 'api_key', label: 'API key', type: 'password', required: true }], suggested_models: ['gpt-4.1-mini'] },
    { name: 'groq', label: 'Groq', fields: [{ key: 'model', label: 'Model', type: 'text', required: true }, { key: 'api_key', label: 'API key', type: 'password', required: true }], suggested_models: ['llama-3.3-70b'] },
  ] }
  const base = { name: 'Acme', join_code: 'abc123', permissions, member_permissions: { create_content: true, delete_content: false } }

  beforeEach(() => {
    vi.clearAllMocks()
    listMembers.mockResolvedValue({ ...members, pending: [] })
    getProviderCatalog.mockResolvedValue(catalog)
  })

  it('owner: "each member uses their own" by default; switching to one provider shows the form and saves for everyone', async () => {
    getWorkspace.mockResolvedValue({ ...base, ai: { mode: 'member', provider: null, model: null, api_key: null } })
    setWorkspaceAI.mockResolvedValue({ mode: 'workspace', provider: 'groq', model: 'llama-3.3-70b', api_key: '****cret' })
    testWorkspaceAI.mockResolvedValue({ ok: true, detail: 'Connected.', models: [] })
    renderAs(owner)

    const own = await screen.findByRole('radio', { name: /Each member uses their own/ })
    expect(own).toHaveAttribute('aria-checked', 'true')
    expect(screen.queryByLabelText('Provider')).toBeNull()

    fireEvent.click(screen.getByRole('radio', { name: /One provider for everyone/ }))
    const select = await screen.findByLabelText('Provider')
    // Local providers are not offered: localhost is a different machine for every member.
    expect(Array.from(select.options).map((o) => o.value)).toEqual(['openai', 'groq'])
    fireEvent.change(select, { target: { value: 'groq' } })
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'gsk-secret' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    await waitFor(() => expect(testWorkspaceAI).toHaveBeenCalledWith(expect.objectContaining({ mode: 'workspace', provider: 'groq', api_key: 'gsk-secret' })))
    expect(await screen.findByText('Connected.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Save for everyone' }))
    await waitFor(() => expect(setWorkspaceAI).toHaveBeenCalledWith(expect.objectContaining({ mode: 'workspace', provider: 'groq', api_key: 'gsk-secret' })))
    expect(await screen.findByText('Saved.')).toBeInTheDocument()
    // The key box is cleared after saving; the masked preview says one is set.
    expect(screen.getByLabelText('API key')).toHaveValue('')
    expect(screen.getByText(/Currently set \(\*\*\*\*cret\)/)).toBeInTheDocument()
  })

  it('owner: choosing "each member" saves immediately', async () => {
    getWorkspace.mockResolvedValue({ ...base, ai: { mode: 'workspace', provider: 'groq', model: 'llama-3.3-70b', api_key: '****cret' } })
    setWorkspaceAI.mockResolvedValue({ mode: 'member', provider: 'groq', model: 'llama-3.3-70b', api_key: '****cret' })
    renderAs(owner)
    expect(await screen.findByLabelText('Provider')).toHaveValue('groq')
    fireEvent.click(screen.getByRole('radio', { name: /Each member uses their own/ }))
    await waitFor(() => expect(setWorkspaceAI).toHaveBeenCalledWith({ mode: 'member' }))
    await waitFor(() => expect(screen.queryByLabelText('Provider')).toBeNull())
  })

  it('member: sees which applies, and no controls', async () => {
    getWorkspace.mockResolvedValue({ ...base, join_code: null, ai: { mode: 'workspace', provider: 'groq', model: 'llama-3.3-70b', api_key: null } })
    renderAs({ id: 'u-member', role: 'member', permissions: { invite_members: false } })
    expect(await screen.findByText(/Everyone in this workspace uses groq \(llama-3.3-70b\), chosen by an owner/)).toBeInTheDocument()
    expect(screen.queryByRole('radio')).toBeNull()
    expect(getProviderCatalog).not.toHaveBeenCalled()
  })
})

