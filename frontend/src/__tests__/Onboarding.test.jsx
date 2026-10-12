import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({
  addMember: vi.fn(),
  completeSetup: vi.fn(),
  getProviderCatalog: vi.fn(),
  login: vi.fn(),
  setMeetstreamApiKey: vi.fn(),
  testLlmProvider: vi.fn(),
  testDatabase: vi.fn(),
  checkJoin: vi.fn(),
}))
import { addMember, checkJoin, completeSetup, getProviderCatalog, login, setMeetstreamApiKey } from '../api'
import Onboarding from '../pages/Onboarding'

const catalog = {
  llm: [
    { name: 'ollama', label: 'Ollama (local)', summary: 'local', local: true, fields: [{ key: 'model', label: 'Model', type: 'text', required: true, default: 'llama3.1' }] },
    { name: 'groq', label: 'Groq', summary: 'fast', local: false, fields: [{ key: 'model', label: 'Model', type: 'text', required: true, default: 'm' }, { key: 'api_key', label: 'API key', type: 'password', required: true }] },
  ],
  databases: [
    { name: 'sqlite', label: 'Local SQLite', summary: 's', available: true, recommended: true, badge: 'DB', fields: [] },
    { name: 'postgres-url', label: 'Other PostgreSQL', summary: 'p', available: true, recommended: false, badge: 'URL', fields: [{ key: 'url', label: 'Connection string', type: 'text', required: true }] },
  ],
}

async function fillAccount(key = '') {
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Ada' } })
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ada@x.test' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct-horse-battery' } })
  if (key) fireEvent.change(screen.getByLabelText('MeetStream API key'), { target: { value: key } })
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
}

describe('Onboarding wizard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getProviderCatalog.mockResolvedValue(catalog)
    completeSetup.mockResolvedValue({})
    addMember.mockResolvedValue({ id: 'u1', role: 'owner' })
    login.mockResolvedValue({ authenticated: true })
  })

  it('Start: applies database first, then the account, then signs in', async () => {
    const onComplete = vi.fn()
    render(<Onboarding onComplete={onComplete} />)
    expect(await screen.findByText('Welcome to Meet Companion')).toBeInTheDocument()

    const next = () => screen.getByRole('button', { name: 'Continue' })
    expect(next()).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Workspace name'), { target: { value: 'Acme' } })
    fireEvent.click(next())

    await screen.findByText('Your account')
    expect(next()).toBeDisabled()
    await fillAccount()

    await screen.findByText('Where should Meet Companion store your data?')
    expect(screen.getByText('Local SQLite')).toBeInTheDocument()
    fireEvent.click(next())

    await screen.findByText('Choose your AI model')
    fireEvent.click(next())

    await screen.findByRole('heading', { name: 'Review' })
    expect(screen.getByText('Acme (new — you own it)')).toBeInTheDocument()
    expect(screen.getByText('Not now')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Finish setup' }))

    await waitFor(() => expect(onComplete).toHaveBeenCalled())
    expect(completeSetup).toHaveBeenCalledWith({
      llm: { provider: 'ollama', model: 'llama3.1', api_key: null, base_url: null, temperature: null },
      database: { provider: 'sqlite', values: {} },
    })
    expect(addMember).toHaveBeenCalledWith({ name: 'Ada', email: 'ada@x.test', password: 'correct-horse-battery', workspace_name: 'Acme', join_code: undefined })
    expect(login).toHaveBeenCalledWith('ada@x.test', 'correct-horse-battery')
    expect(setMeetstreamApiKey).not.toHaveBeenCalled()
    // Order: database before account, account before sign-in.
    const order = [completeSetup, addMember, login].map((f) => f.mock.invocationCallOrder[0])
    expect(order).toEqual([...order].sort((a, b) => a - b))
  })

  it('Join: hides SQLite, checks the code against the database before moving on, and does not resend setup after a failed account step', async () => {
    addMember.mockRejectedValueOnce(new Error('No workspace found with that join code.'))
    render(<Onboarding onComplete={vi.fn()} />)
    await screen.findByText('Welcome to Meet Companion')
    fireEvent.click(screen.getByText("Join my team's workspace"))
    // The code is not asked for here: it only means something on a database.
    expect(screen.queryByLabelText('Join code')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    await screen.findByText('Your account')
    await fillAccount()

    await screen.findByText("Connect to your team's database")
    expect(screen.queryByText('Local SQLite')).toBeNull()
    fireEvent.click(screen.getByText('Other PostgreSQL'))
    fireEvent.change(await screen.findByLabelText('Connection string'), { target: { value: 'postgresql://u:p@h/db' } })
    // Database filled in, but no code yet: cannot continue.
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()

    // A wrong code is caught right here, against that database, before anything is applied.
    checkJoin.mockRejectedValueOnce(new Error('No workspace with that join code exists on that database.'))
    fireEvent.change(screen.getByLabelText('Join code'), { target: { value: 'bad' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByText(/No workspace with that join code exists on that database/)).toBeInTheDocument()
    expect(checkJoin).toHaveBeenCalledWith({ provider: 'postgres-url', values: { url: 'postgresql://u:p@h/db' }, join_code: 'bad' })
    expect(completeSetup).not.toHaveBeenCalled()
    expect(screen.getByText("Connect to your team's database")).toBeInTheDocument()

    checkJoin.mockResolvedValueOnce({ workspace: 'Team Co', same_database: false })
    fireEvent.change(screen.getByLabelText('Join code'), { target: { value: 'zzz' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    await screen.findByText('Choose your AI model')
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await screen.findByRole('heading', { name: 'Review' })
    expect(screen.getByText(/Joining Team Co/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Finish setup' }))
    expect(await screen.findByText(/No workspace with that join code exists in the database you connected to/)).toBeInTheDocument()
    expect(addMember).toHaveBeenCalledWith(expect.objectContaining({ join_code: 'zzz', workspace_name: undefined }))
    expect(completeSetup).toHaveBeenCalledTimes(1)

    // Retry: server-wide setup is not sent again (it is closed once saved).
    addMember.mockResolvedValueOnce({ id: 'u2', role: 'member' })
    fireEvent.click(screen.getByRole('button', { name: 'Finish setup' }))
    await waitFor(() => expect(addMember).toHaveBeenCalledTimes(2))
    expect(completeSetup).toHaveBeenCalledTimes(1)
  })

  it('a rejected MeetStream key does not block: the account is made and the app can be entered', async () => {
    setMeetstreamApiKey.mockRejectedValue(new Error('MeetStream rejected this API key.'))
    const onComplete = vi.fn()
    render(<Onboarding onComplete={onComplete} />)
    await screen.findByText('Welcome to Meet Companion')
    fireEvent.change(screen.getByLabelText('Workspace name'), { target: { value: 'Acme' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await screen.findByText('Your account')
    await fillAccount('ms_bad')
    await screen.findByText('Where should Meet Companion store your data?')
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await screen.findByText('Choose your AI model')
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await screen.findByRole('heading', { name: 'Review' })
    expect(screen.getByText('API key provided')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Finish setup' }))

    expect(await screen.findByText(/MeetStream rejected this API key/)).toBeInTheDocument()
    expect(addMember).toHaveBeenCalledTimes(1)
    expect(onComplete).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Continue to the app' }))
    expect(onComplete).toHaveBeenCalled()
  })

  it('Reconnect: skips addMember and signs in with existing credentials after configuring the server', async () => {
    const onComplete = vi.fn()
    render(<Onboarding onComplete={onComplete} />)
    await screen.findByText('Welcome to Meet Companion')

    // Step 0: choose reconnect
    fireEvent.click(screen.getByText('Already have an account?'))
    // No workspace name required - can proceed immediately.
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    // Step 1: only email + password, no Name or MeetStream key
    await screen.findByText('Sign in to your existing account')
    expect(screen.queryByLabelText('Name')).toBeNull()
    expect(screen.queryByLabelText('MeetStream API key')).toBeNull()
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ada@x.test' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct-horse-battery' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    // Step 2: SQLite is hidden, pick Postgres
    await screen.findByText('Connect to your database')
    expect(screen.queryByText('Local SQLite')).toBeNull()
    fireEvent.click(screen.getByText('Other PostgreSQL'))
    fireEvent.change(await screen.findByLabelText('Connection string'), { target: { value: 'postgresql://u:p@h/db' } })
    // No join code field in reconnect mode.
    expect(screen.queryByLabelText('Join code')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    // Step 3: AI model
    await screen.findByText('Choose your AI model')
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))

    // Step 4: Review
    await screen.findByRole('heading', { name: 'Review' })
    expect(screen.getByText('Signing in to existing account')).toBeInTheDocument()
    // MeetStream row is hidden in reconnect mode.
    expect(screen.queryByText('Not now')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Finish setup' }))

    await waitFor(() => expect(onComplete).toHaveBeenCalled())
    expect(completeSetup).toHaveBeenCalledWith({
      llm: { provider: 'ollama', model: 'llama3.1', api_key: null, base_url: null, temperature: null },
      database: { provider: 'postgres-url', values: { url: 'postgresql://u:p@h/db' } },
    })
    // The key assertion: addMember is never called in reconnect mode.
    expect(addMember).not.toHaveBeenCalled()
    expect(login).toHaveBeenCalledWith('ada@x.test', 'correct-horse-battery')
  })
})
