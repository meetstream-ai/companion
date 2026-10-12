import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({
  addMember: vi.fn(),
  login: vi.fn(),
  listConnections: vi.fn(),
  addConnection: vi.fn(),
  activateConnection: vi.fn(),
  joinWorkspace: vi.fn(),
  checkJoin: vi.fn(),
  getProviderCatalog: vi.fn(),
  testDatabase: vi.fn(),
}))
import {
  activateConnection, addConnection, addMember, checkJoin, getProviderCatalog, joinWorkspace, listConnections, login,
} from '../api'
import SignIn from '../pages/SignIn'

/** Both the mode tabs and the submit button carry these names; we want the submit. */
function submitButton(name) {
  return screen.getAllByRole('button', { name }).find((b) => b.getAttribute('type') === 'submit')
}

const KEY = 'meet-companion:pending-join'

function fillAccount() {
  fireEvent.change(screen.getByLabelText('Your name'), { target: { value: 'Ada' } })
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ada@x.test' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct-horse-battery' } })
}

beforeEach(() => {
  vi.clearAllMocks()
  window.sessionStorage.clear()
  addMember.mockResolvedValue({ id: 'u1', role: 'member' })
  login.mockResolvedValue({ authenticated: true })
  // Shared server by default: the connections endpoint does not exist.
  listConnections.mockRejectedValue(new Error('Not found'))
  addConnection.mockResolvedValue({ id: 'c2' })
  activateConnection.mockResolvedValue({ switched: true, signed_in: false })
  joinWorkspace.mockResolvedValue({ joined: true })
  checkJoin.mockResolvedValue({ workspace: 'Team Co', same_database: false })
  getProviderCatalog.mockResolvedValue({
    llm: [],
    databases: [
      { name: 'sqlite', label: 'Local file (SQLite)', summary: 'On this computer', available: true, fields: [] },
      {
        name: 'postgres',
        label: 'PostgreSQL',
        summary: 'Shared with your team',
        available: true,
        fields: [{ key: 'url', label: 'Connection string', required: true }],
      },
    ],
  })
  Object.defineProperty(window, 'location', { value: { reload: vi.fn(), pathname: '/' }, writable: true })
})

describe('sign-in', () => {
  it('opens on sign-in for an install that already has accounts', () => {
    render(<SignIn onSignedIn={vi.fn()} hasMembers />)
    expect(submitButton('Sign in')).toBeTruthy()
    expect(screen.queryByLabelText('Your name')).toBeNull()
  })

  it('a join code carried from the picker opens account creation with it filled in', async () => {
    window.sessionStorage.setItem(KEY, 'abc123')
    const onSignedIn = vi.fn()
    render(<SignIn onSignedIn={onSignedIn} hasMembers />)

    expect(await screen.findByText(/Connected to that database/)).toBeInTheDocument()
    expect(screen.getByLabelText('Your name')).toBeInTheDocument()
    const code = screen.getByLabelText(/Join code/i)
    expect(code).toHaveValue('abc123')
    // Taken once: a reload must not resurrect it.
    expect(window.sessionStorage.getItem(KEY)).toBeNull()

    fillAccount()
    fireEvent.click(submitButton('Create account'))

    await waitFor(() => expect(addMember).toHaveBeenCalledWith(expect.objectContaining({
      email: 'ada@x.test', join_code: 'abc123',
    })))
    await waitFor(() => expect(onSignedIn).toHaveBeenCalled())
  })
})

describe('creating an account', () => {
  it('is an explicit choice between starting a workspace and joining one', async () => {
    render(<SignIn onSignedIn={vi.fn()} hasMembers={false} />)
    // Fresh install: nothing to join, so it opens on starting one.
    expect(screen.getByRole('radio', { name: 'Start a new one' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByLabelText('Workspace name')).toBeInTheDocument()
    expect(screen.queryByLabelText(/Join code/i)).toBeNull()

    fillAccount()
    fireEvent.change(screen.getByLabelText('Workspace name'), { target: { value: 'Acme' } })
    fireEvent.click(submitButton('Create account'))
    await waitFor(() => expect(addMember).toHaveBeenCalledWith(expect.objectContaining({
      workspace_name: 'Acme', join_code: undefined,
    })))

    fireEvent.click(screen.getByRole('radio', { name: "Join my team's workspace" }))
    expect(screen.getByLabelText(/Join code/i)).toBeInTheDocument()
    expect(screen.queryByLabelText('Workspace name')).toBeNull()
  })

  it('on a shared server a code is enough - there is no database to name', async () => {
    render(<SignIn onSignedIn={vi.fn()} hasMembers />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Create account' })[0])
    expect(screen.getByLabelText(/Join code/i)).toBeInTheDocument()
    // listConnections has settled (rejected) by now; still no database field.
    await waitFor(() => expect(listConnections).toHaveBeenCalled())
    expect(screen.queryByLabelText(/Team's database/i)).toBeNull()
  })

  it('on the desktop, joining asks for the database and creates the account there', async () => {
    listConnections.mockResolvedValue({ connections: [{ id: 'c1', active: true }] })
    const onSignedIn = vi.fn()
    render(<SignIn onSignedIn={onSignedIn} hasMembers />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Create account' })[0])

    const dburl = await screen.findByLabelText(/Team's database/i)
    fillAccount()
    fireEvent.change(screen.getByLabelText(/Join code/i), { target: { value: 'abc123' } })
    fireEvent.change(dburl, { target: { value: 'postgresql://team@db.example/app' } })
    fireEvent.click(submitButton('Create account'))

    await waitFor(() => expect(window.location.reload).toHaveBeenCalled())
    // Checked, then switched, then the account was created on the new database.
    expect(checkJoin).toHaveBeenCalledWith({ url: 'postgresql://team@db.example/app', join_code: 'abc123' })
    expect(checkJoin.mock.invocationCallOrder[0]).toBeLessThan(addConnection.mock.invocationCallOrder[0])
    expect(addConnection).toHaveBeenCalledWith({ url: 'postgresql://team@db.example/app' })
    expect(activateConnection).toHaveBeenCalledWith('c2', null)
    expect(addMember).toHaveBeenCalledWith(expect.objectContaining({ join_code: 'abc123', workspace_name: undefined }))
    expect(login).toHaveBeenCalledWith('ada@x.test', 'correct-horse-battery')
    expect(joinWorkspace).not.toHaveBeenCalled()
    expect(addConnection.mock.invocationCallOrder[0]).toBeLessThan(addMember.mock.invocationCallOrder[0])
  })

  it('on the desktop, an account that already exists on that database just joins', async () => {
    listConnections.mockResolvedValue({ connections: [{ id: 'c1', active: true }] })
    activateConnection.mockResolvedValue({ switched: true, signed_in: true })
    render(<SignIn onSignedIn={vi.fn()} hasMembers />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Create account' })[0])

    const dburl = await screen.findByLabelText(/Team's database/i)
    fillAccount()
    fireEvent.change(screen.getByLabelText(/Join code/i), { target: { value: 'abc123' } })
    fireEvent.change(dburl, { target: { value: 'postgresql://team@db.example/app' } })
    fireEvent.click(submitButton('Create account'))

    await waitFor(() => expect(window.location.reload).toHaveBeenCalled())
    expect(joinWorkspace).toHaveBeenCalledWith('abc123')
    expect(addMember).not.toHaveBeenCalled()
  })

  it('on the desktop, a blank database field means the one this app is on', async () => {
    listConnections.mockResolvedValue({ connections: [{ id: 'c1', active: true }] })
    const onSignedIn = vi.fn()
    render(<SignIn onSignedIn={onSignedIn} hasMembers />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Create account' })[0])
    await screen.findByLabelText(/Team's database/i)
    fillAccount()
    fireEvent.change(screen.getByLabelText(/Join code/i), { target: { value: 'abc123' } })
    fireEvent.click(submitButton('Create account'))

    await waitFor(() => expect(onSignedIn).toHaveBeenCalled())
    expect(addConnection).not.toHaveBeenCalled()
    expect(addMember).toHaveBeenCalledWith(expect.objectContaining({ join_code: 'abc123' }))
    expect(window.location.reload).not.toHaveBeenCalled()
  })

  it('a code that is not on that database is refused before anything is switched', async () => {
    listConnections.mockResolvedValue({ connections: [{ id: 'c1', active: true }] })
    checkJoin.mockRejectedValue(new Error('No workspace with that join code exists on that database.'))
    render(<SignIn onSignedIn={vi.fn()} hasMembers />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Create account' })[0])
    const dburl = await screen.findByLabelText(/Team's database/i)
    fillAccount()
    fireEvent.change(screen.getByLabelText(/Join code/i), { target: { value: 'nope' } })
    fireEvent.change(dburl, { target: { value: 'postgresql://team@db.example/app' } })
    fireEvent.click(submitButton('Create account'))

    expect(await screen.findByText(/No workspace with that join code exists on that database/)).toBeInTheDocument()
    expect(addConnection).not.toHaveBeenCalled()
    expect(activateConnection).not.toHaveBeenCalled()
    expect(addMember).not.toHaveBeenCalled()
    expect(window.location.reload).not.toHaveBeenCalled()
  })

  it('a failed join on another database shows the error and stays on the form', async () => {
    listConnections.mockResolvedValue({ connections: [{ id: 'c1', active: true }] })
    addMember.mockRejectedValue(new Error('No workspace found with that join code.'))
    render(<SignIn onSignedIn={vi.fn()} hasMembers />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Create account' })[0])
    const dburl = await screen.findByLabelText(/Team's database/i)
    fillAccount()
    fireEvent.change(screen.getByLabelText(/Join code/i), { target: { value: 'nope' } })
    fireEvent.change(dburl, { target: { value: 'postgresql://team@db.example/app' } })
    fireEvent.click(submitButton('Create account'))

    expect(await screen.findByText('No workspace found with that join code.')).toBeInTheDocument()
    expect(window.location.reload).not.toHaveBeenCalled()
    expect(screen.getByLabelText(/Join code/i)).toHaveValue('nope')
  })
})

describe('choosing the database from the sign-in page', () => {
  // Signing out while the app points at one database, with your account on
  // another, used to be a dead end: no account to sign in with here, and
  // every database switcher was behind the sign-in wall.
  const TWO = {
    connections: [
      { id: 'c1', label: 'Local (SQLite)', active: true, signed_in: true, reachable: true, workspaces: [] },
      { id: 'c2', label: 'Team Postgres', active: false, signed_in: true, reachable: true, workspaces: [] },
    ],
  }

  it('is absent on a shared server, and present on a desktop with only one database', async () => {
    render(<SignIn onSignedIn={vi.fn()} hasMembers />)
    await waitFor(() => expect(listConnections).toHaveBeenCalled())
    expect(screen.queryByText(/^Database:/)).toBeNull()

    // One saved database is still worth the control: it is the way to reach
    // "Connect another database".
    listConnections.mockResolvedValue({ connections: [TWO.connections[0]] })
    render(<SignIn onSignedIn={vi.fn()} hasMembers />)
    expect(await screen.findByText('Database: Local (SQLite)')).toBeInTheDocument()
  })

  it('names the live database and switches to the one picked', async () => {
    listConnections.mockResolvedValue(TWO)
    render(<SignIn onSignedIn={vi.fn()} hasMembers />)

    fireEvent.click(await screen.findByText('Database: Local (SQLite)'))
    // The one it is already on says so rather than offering a pointless switch.
    expect(screen.getByRole('menuitemradio', { name: /Local \(SQLite\)/ })).toHaveAttribute('aria-checked', 'true')

    fireEvent.click(screen.getByRole('menuitemradio', { name: /Team Postgres/ }))
    await waitFor(() => expect(activateConnection).toHaveBeenCalledWith('c2', null))
    // Activating signs this machine in where the database knows them, so the
    // reload lands either in the app or back here on the right database.
    await waitFor(() => expect(window.location.reload).toHaveBeenCalled())
  })

  it('keeps you here and says why when the database cannot be switched to', async () => {
    listConnections.mockResolvedValue(TWO)
    activateConnection.mockRejectedValue(new Error('Could not switch to Team Postgres: connection refused'))
    render(<SignIn onSignedIn={vi.fn()} hasMembers />)

    fireEvent.click(await screen.findByText('Database: Local (SQLite)'))
    fireEvent.click(screen.getByRole('menuitemradio', { name: /Team Postgres/ }))

    expect(await screen.findByText(/connection refused/)).toBeInTheDocument()
    expect(window.location.reload).not.toHaveBeenCalled()
    // Still usable: the form was never taken away.
    expect(submitButton('Sign in')).toBeTruthy()
  })

  it('does not offer a database it cannot reach', async () => {
    listConnections.mockResolvedValue({
      connections: [TWO.connections[0], { ...TWO.connections[1], reachable: false }],
    })
    render(<SignIn onSignedIn={vi.fn()} hasMembers />)

    fireEvent.click(await screen.findByText('Database: Local (SQLite)'))
    const unreachable = screen.getByRole('menuitemradio', { name: /Team Postgres/ })
    expect(unreachable).toBeDisabled()
    expect(unreachable).toHaveTextContent('Unreachable')
  })
})

describe('connecting a database the machine has never seen', () => {
  const ONE = {
    connections: [
      { id: 'c1', label: 'Local (SQLite)', active: true, signed_in: true, reachable: true, workspaces: [] },
    ],
  }

  async function openConnectForm() {
    listConnections.mockResolvedValue(ONE)
    render(<SignIn onSignedIn={vi.fn()} hasMembers />)
    fireEvent.click(await screen.findByText('Database: Local (SQLite)'))
    fireEvent.click(screen.getByRole('menuitem', { name: /Connect another database/ }))
    return screen.findByRole('heading', { name: 'Connect to another database' })
  }

  it('offers the shared providers, not a local file, and hides the owner-only test', async () => {
    await openConnectForm()
    // The sign-in form is out of the way while connecting.
    expect(screen.queryByLabelText('Password')).toBeNull()
    expect(await screen.findByText('PostgreSQL')).toBeInTheDocument()
    // A local SQLite file is what this machine starts on, not somewhere to
    // connect to - onboarding's own join step hides it the same way.
    expect(screen.queryByText('Local file (SQLite)')).toBeNull()
    // /setup/test-database needs an owner's session, which this page lacks.
    expect(screen.queryByRole('button', { name: /Test connection/ })).toBeNull()
  })

  it('saves the connection, switches to it, and reloads', async () => {
    addConnection.mockResolvedValue({ id: 'c9' })
    await openConnectForm()

    fireEvent.click(await screen.findByText('PostgreSQL'))
    fireEvent.change(await screen.findByLabelText(/Connection string/), {
      target: { value: 'postgresql://user:pw@host/db' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^Connect$/ }))

    await waitFor(() =>
      expect(addConnection).toHaveBeenCalledWith({
        provider: 'postgres',
        values: { url: 'postgresql://user:pw@host/db' },
      }),
    )
    await waitFor(() => expect(activateConnection).toHaveBeenCalledWith('c9', null))
    await waitFor(() => expect(window.location.reload).toHaveBeenCalled())
  })

  it('reports a database it cannot reach and stays on the form', async () => {
    addConnection.mockRejectedValue(new Error('could not connect to server: timed out'))
    await openConnectForm()

    fireEvent.click(await screen.findByText('PostgreSQL'))
    fireEvent.change(await screen.findByLabelText(/Connection string/), { target: { value: 'postgresql://nope/db' } })
    fireEvent.click(screen.getByRole('button', { name: /^Connect$/ }))

    expect(await screen.findByText(/timed out/)).toBeInTheDocument()
    expect(activateConnection).not.toHaveBeenCalled()
    expect(window.location.reload).not.toHaveBeenCalled()
  })

  it('goes back to the sign-in form', async () => {
    await openConnectForm()
    fireEvent.click(screen.getByRole('button', { name: /Back to sign in/ }))
    expect(await screen.findByLabelText('Password')).toBeInTheDocument()
  })
})
