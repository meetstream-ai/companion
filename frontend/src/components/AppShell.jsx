import { activateConnection, addConnection, activateWorkspace, checkJoin, createWorkspace, joinWorkspace, listConnections, listMyWorkspaces } from '../api'
import { PENDING_JOIN_KEY } from '../pendingJoin'
import { useEffect, useRef, useState } from 'react'
import { NavLink } from 'react-router-dom'
import Logo from './Logo'
import WorkspaceSwitchOverlay from './WorkspaceSwitchOverlay'
import {
  AskAiIcon,
  ChevronDownIcon,
  DashboardIcon,
  MeetingsIcon,
  MembersIcon,
  MoonIcon,
  GraphIcon,
  NotebookIcon,
  RobotIcon,
  SettingsIcon,
  SidebarIcon,
  SunIcon,
} from './Icons'

const PRIMARY_NAV = [
  { to: '/', label: 'Dashboard', Icon: DashboardIcon, end: true },
  { to: '/meetings', label: 'Meetings', Icon: MeetingsIcon },
  { to: '/notebook', label: 'Notebook', Icon: NotebookIcon },
  { to: '/graph', label: 'Knowledge graph', Icon: GraphIcon },
  { to: '/ask', label: 'Ask AI', Icon: AskAiIcon },
]

const SECONDARY_NAV = [
  { to: '/agent', label: 'Agent', Icon: RobotIcon },
  { to: '/members', label: 'Members', Icon: MembersIcon },
  { to: '/settings', label: 'Settings', Icon: SettingsIcon },
]

const THEME_KEY = 'meet-companion:theme'
const COLLAPSE_KEY = 'meet-companion:sidebar-collapsed'

export function useTheme() {
  const [theme, setTheme] = useState(() => {
    if (typeof window === 'undefined') return 'light'
    const stored = window.localStorage.getItem(THEME_KEY)
    if (stored) return stored
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    try {
      window.localStorage.setItem(THEME_KEY, theme)
    } catch {
      // Private browsing can reject writes; the theme still applies this session.
    }
  }, [theme])

  return [theme, () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))]
}

function initialsOf(user) {
  const source = user?.name || user?.email || '?'
  return source
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join('')
}

function NavSection({ items, collapsed }) {
  return (
    <nav className="flex flex-col gap-1">
      {items.map(({ to, label, Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={`mc-nav-item ${collapsed ? 'justify-center px-0' : ''}`}
          title={collapsed ? label : undefined}
        >
          <Icon size={18} />
          {!collapsed && <span>{label}</span>}
        </NavLink>
      ))}
    </nav>
  )
}

function Avatar({ user, size = 34 }) {
  return (
    <div
      className="flex items-center justify-center rounded-full text-xs font-semibold"
      style={{
        width: size,
        height: size,
        background: 'linear-gradient(135deg, var(--color-brand-400), var(--color-brand-700))',
        color: '#fff',
      }}
      aria-hidden="true"
    >
      {initialsOf(user)}
    </div>
  )
}


/**
 * Workspace switcher.
 *
 * Only rendered when the account belongs to more than one workspace - with a
 * single one there is nothing to switch to and the control is just noise.
 * Switching reloads, because every page's data is scoped to the active
 * workspace and stale panels would otherwise show the previous one's content.
 */
function WorkspaceSwitcher() {
  const [workspaces, setWorkspaces] = useState(null)
  // Present only on the desktop app: the databases this machine knows, each
  // with the workspaces this person has on it. null = single-database mode.
  const [connections, setConnections] = useState(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [switchingTo, setSwitchingTo] = useState(null)
  const [mode, setMode] = useState(null)  // 'join' | 'create'
  const [error, setError] = useState(null)
  // "Request sent" after a join: nothing switches until an owner approves,
  // so a reload would look like nothing happened.
  const [notice, setNotice] = useState(null)
  const box = useRef(null)

  useEffect(() => {
    let cancelled = false
    listMyWorkspaces()
      .then((data) => !cancelled && setWorkspaces(data.workspaces || []))
      .catch(() => !cancelled && setWorkspaces([]))
    // Endpoint is 404 unless this is the desktop app; the catch keeps us in
    // single-database mode there.
    listConnections()
      .then((data) => !cancelled && setConnections(data.connections || null))
      .catch(() => !cancelled && setConnections(null))
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!open) return undefined
    const close = (event) => !box.current?.contains(event.target) && setOpen(false)
    const onKey = (event) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  // An empty list (an account with no membership row) must not take the
  // whole shell down with it - the rest of the app still works.
  if (!workspaces || workspaces.length === 0) {
    return switchingTo ? (
      <WorkspaceSwitchOverlay
        name={switchingTo.name}
        action={switchingTo.action}
        subtitle={switchingTo.subtitle}
      />
    ) : null
  }
  const active = workspaces.find((w) => w.is_active) || workspaces[0]

  async function choose(workspace, connectionId) {
    if (busy || workspace.status === 'pending') return
    if (!connectionId && workspace.is_active) {
      setOpen(false)
      return
    }
    const targetName = workspace.name || 'Workspace'
    setBusy(true)
    setSwitchingTo({
      name: targetName,
      action: connectionId ? 'Connecting database & workspace…' : 'Switching workspace…',
    })
    try {
      window.sessionStorage.setItem('mc_switching_workspace', targetName)
    } catch {
      // Non-critical session preference.
    }
    try {
      if (connectionId) {
        await activateConnection(connectionId, workspace.id)
      } else {
        await activateWorkspace(workspace.id)
      }
      window.location.reload()
    } catch (err) {
      try {
        window.sessionStorage.removeItem('mc_switching_workspace')
      } catch {}
      setSwitchingTo(null)
      setError(err.message)
      setBusy(false)
    }
  }

  // Desktop app with more than one database, or any workspace on a
  // non-active database: show the grouped, cross-connection picker.
  const multiDb = Array.isArray(connections) && (connections.length > 1 || connections.some((c) => !c.active && c.workspaces.length))

  return (
    <>
      {switchingTo && (
        <WorkspaceSwitchOverlay
          name={switchingTo.name}
          action={switchingTo.action}
          subtitle={switchingTo.subtitle}
        />
      )}
      <div className="relative" ref={box}>
      <button
        type="button"
        className="mc-btn mc-btn-ghost"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title="Switch workspace"
      >
        <span className="max-w-[10rem] truncate">{active.name}</span>
        <ChevronDownIcon size={15} />
      </button>
      {open && (
        <div
          role="menu"
          className="mc-panel absolute right-0 z-40 mt-1 min-w-[14rem] overflow-hidden p-1"
        >
          {multiDb
            ? connections.map((conn) => (
                <div key={conn.id} className="mb-1">
                  <div className="flex items-center justify-between px-3 py-1 text-[0.65rem] font-semibold uppercase tracking-wide" style={{ color: 'var(--text-faint)' }}>
                    <span className="truncate">{conn.label}</span>
                    {!conn.reachable && conn.reachable !== null && <span title="Not reachable">⚠</span>}
                  </div>
                  {conn.signed_in && conn.workspaces.length
                    ? conn.workspaces.map((workspace) => (
                        <button
                          key={workspace.id}
                          type="button"
                          role="menuitemradio"
                          aria-checked={conn.active && workspace.is_active}
                          aria-disabled={workspace.status === 'pending' || undefined}
                          disabled={busy}
                          className="mc-nav-item flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm"
                          style={workspace.status === 'pending' ? { color: 'var(--text-muted)', cursor: 'default' } : undefined}
                          title={workspace.status === 'pending' ? 'Waiting for an owner to approve your request' : undefined}
                          onClick={() => choose(workspace, conn.active ? null : conn.id)}
                        >
                          <span className="truncate">{workspace.name}</span>
                          <span className="text-xs" style={{ color: 'var(--text-faint)' }}>
                            {workspace.status === 'pending' ? 'Pending approval' : conn.active && workspace.is_active ? 'Current' : workspace.role}
                          </span>
                        </button>
                      ))
                    : (
                      <button
                        type="button"
                        disabled={busy || conn.reachable === false}
                        className="mc-nav-item w-full px-3 py-2 text-left text-sm"
                        style={{ color: 'var(--text-muted)' }}
                        onClick={() => choose({ id: null, name: conn.label }, conn.id)}
                      >
                        {conn.reachable === false ? 'Unreachable' : 'Sign in on this database…'}
                      </button>
                    )}
                </div>
              ))
            : workspaces.map((workspace) => (
                <button
                  key={workspace.id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={workspace.is_active}
                  aria-disabled={workspace.status === 'pending' || undefined}
                  disabled={busy}
                  className="mc-nav-item flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm"
                  style={workspace.status === 'pending' ? { color: 'var(--text-muted)', cursor: 'default' } : undefined}
                  title={workspace.status === 'pending' ? 'Waiting for an owner to approve your request' : undefined}
                  onClick={() => choose(workspace)}
                >
                  <span className="truncate">{workspace.name}</span>
                  <span className="text-xs" style={{ color: 'var(--text-faint)' }}>
                    {workspace.status === 'pending' ? 'Pending approval' : workspace.is_active ? 'Current' : workspace.role}
                  </span>
                </button>
              ))}
          <div style={{ borderTop: '1px solid var(--border-subtle)' }} className="mt-1 pt-1">
            {mode ? (
              <form
                className="flex flex-col gap-1 p-1"
                onSubmit={async (event) => {
                  event.preventDefault()
                  const value = event.target.elements.value.value.trim()
                  if (!value) return
                  const dburl = (event.target.elements.dburl?.value || '').trim()
                  setBusy(true)
                  setError(null)
                  setNotice(null)
                  try {
                    if (mode === 'create') {
                      setSwitchingTo({
                        name: value,
                        action: 'Creating workspace…',
                      })
                      try {
                        window.sessionStorage.setItem('mc_switching_workspace', value)
                      } catch {}
                      await createWorkspace(value)
                    } else if (!dburl) {
                      // A workspace on the database we are already on: the
                      // code is looked up here and becomes a request, which
                      // an owner of that workspace has to approve.
                      const result = await joinWorkspace(value)
                      if (result.pending) {
                        const data = await listMyWorkspaces().catch(() => null)
                        if (data) setWorkspaces(data.workspaces || [])
                        setNotice(`Request sent. An owner of ${result.name} has to approve it before you can open it.`)
                        setMode(null)
                        setBusy(false)
                        return
                      }
                      setSwitchingTo({
                        name: result.name || value,
                        action: 'Joining workspace…',
                      })
                      try {
                        window.sessionStorage.setItem('mc_switching_workspace', result.name || value)
                      } catch {}
                    } else {
                      // Another database. Make sure the code is actually on
                      // it *before* switching - a wrong code used to leave
                      // the app pointed at a database with no account on it.
                      // Then save it, switch to it, and either join straight
                      // away (we already have an account there) or hand the
                      // code to account creation, which is where a first
                      // visit to someone else's database goes.
                      await checkJoin({ url: dburl, join_code: value })
                      const conn = await addConnection({ url: dburl })
                      setSwitchingTo({
                        name: value,
                        action: 'Connecting database…',
                      })
                      try {
                        window.sessionStorage.setItem('mc_switching_workspace', value)
                      } catch {}
                      const result = await activateConnection(conn.id, null)
                      if (result.signed_in) {
                        await joinWorkspace(value)
                      } else {
                        try {
                          window.sessionStorage.setItem(PENDING_JOIN_KEY, value)
                        } catch {
                          // Private mode: the code just has to be typed again.
                        }
                      }
                    }
                    window.location.reload()
                  } catch (err) {
                    try {
                      window.sessionStorage.removeItem('mc_switching_workspace')
                    } catch {}
                    setSwitchingTo(null)
                    setError(err.message)
                    setBusy(false)
                  }
                }}
              >
                {mode === 'join' && Array.isArray(connections) && (
                  <>
                    {/* The database comes first: a code only means something on one. */}
                    <input
                      name="dburl"
                      className="mc-input py-1 text-xs"
                      placeholder="Team's database connection string"
                      aria-label="Database connection string"
                      autoFocus
                      disabled={busy}
                    />
                    <p className="px-1 text-[0.65rem]" style={{ color: 'var(--text-faint)' }}>
                      A workspace lives in one database. Paste the connection string your team
                      shared, or leave blank for a workspace on this database.
                    </p>
                  </>
                )}
                <input
                  name="value"
                  className="mc-input py-1 text-xs"
                  placeholder={mode === 'join' ? 'Join code' : 'Workspace name'}
                  aria-label={mode === 'join' ? 'Workspace join code' : 'New workspace name'}
                  autoFocus={mode !== 'join' || !Array.isArray(connections)}
                  disabled={busy}
                />
                <div className="flex items-center justify-end gap-1.5 pt-1">
                  <button
                    type="button"
                    className="mc-btn mc-btn-ghost px-2.5 py-1 text-xs"
                    disabled={busy}
                    onClick={() => {
                      setMode(null)
                      setError(null)
                      setNotice(null)
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="mc-btn mc-btn-primary px-3 py-1 text-xs"
                    disabled={busy}
                  >
                    {mode === 'join' ? 'Join' : 'Create'}
                  </button>
                </div>
              </form>
            ) : (
              <>
                <button
                  type="button"
                  className="mc-nav-item w-full px-3 py-2 text-left text-sm"
                  onClick={() => setMode('create')}
                >
                  Create a workspace…
                </button>
                <button
                  type="button"
                  className="mc-nav-item w-full px-3 py-2 text-left text-sm"
                  onClick={() => setMode('join')}
                >
                  Join a workspace…
                </button>
              </>
            )}
            {error && (
              <div className="px-3 py-1 text-xs" style={{ color: 'var(--color-danger-500, #e5484d)' }}>
                {error}
              </div>
            )}
            {notice && (
              <div role="status" className="px-3 py-1 text-xs" style={{ color: 'var(--text-muted)' }}>
                {notice}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
    </>
  )
}

export default function AppShell({ user, onSignOut, children }) {
  const [theme, toggleTheme] = useTheme()
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem(COLLAPSE_KEY) === 'true'
    } catch {
      return false
    }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSE_KEY, String(collapsed))
    } catch {
      // Non-critical preference.
    }
  }, [collapsed])

  return (
    <div className="flex min-h-screen" style={{ backgroundColor: 'var(--surface-page)' }}>
      <aside
        // Sticky and viewport-high: the collapse button at the bottom must stay
        // reachable on pages taller than the window, and the nav should not
        // scroll away with the page.
        className="sticky top-0 hidden h-screen md:flex flex-col shrink-0 transition-[width] duration-200"
        style={{
          width: collapsed ? '5rem' : '16rem',
          backgroundColor: 'var(--surface-nav)',
          borderRight: '1px solid var(--border-subtle)',
        }}
      >
        <div className={`flex items-center h-[4.5rem] px-5 ${collapsed ? 'justify-center px-0' : ''}`}>
          {collapsed ? <Logo variant="icon" size={32} /> : <Logo size={32} />}
        </div>

        <div className="flex-1 overflow-y-auto mc-scroll px-3 py-2">
          {!collapsed && (
            <div
              className="px-3 pb-2 text-[0.65rem] font-semibold uppercase tracking-[0.14em]"
              style={{ color: 'var(--text-faint)' }}
            >
              Workspace
            </div>
          )}
          <NavSection items={PRIMARY_NAV} collapsed={collapsed} />

          {!collapsed && (
            <div
              className="mt-6 px-3 pb-2 text-[0.65rem] font-semibold uppercase tracking-[0.14em]"
              style={{ color: 'var(--text-faint)' }}
            >
              Manage
            </div>
          )}
          <div className={collapsed ? 'mt-4' : ''}>
            <NavSection items={SECONDARY_NAV} collapsed={collapsed} />
          </div>
        </div>

        <div className="p-3">
          <button
            type="button"
            className={`mc-btn mc-btn-ghost w-full ${collapsed ? 'px-0' : ''}`}
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <SidebarIcon size={17} />
            {!collapsed && <span>Collapse</span>}
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="sticky top-0 z-30 flex h-[4.5rem] items-center gap-3 px-5 md:px-8"
          style={{
            backgroundColor: 'var(--surface-nav)',
            borderBottom: '1px solid var(--border-subtle)',
          }}
        >
          <div className="md:hidden">
            <Logo variant="icon" size={30} />
          </div>


          <div className="ml-auto flex items-center gap-2">
            {user && <WorkspaceSwitcher />}
            <button
              type="button"
              className="mc-btn mc-btn-ghost px-2.5"
              onClick={toggleTheme}
              title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            >
              {theme === 'dark' ? <SunIcon size={18} /> : <MoonIcon size={18} />}
            </button>

            {user && (
              <div className="flex items-center gap-3 pl-1">
                <div className="hidden text-right leading-tight lg:block">
                  <div className="text-sm font-semibold" style={{ color: 'var(--text-strong)' }}>
                    {user.name || user.email}
                  </div>
                  <button
                    type="button"
                    className="text-xs hover:underline"
                    style={{ color: 'var(--text-faint)' }}
                    onClick={onSignOut}
                  >
                    Sign out
                  </button>
                </div>
                <Avatar user={user} />
              </div>
            )}
          </div>
        </header>

        <main className="min-w-0 flex-1 pb-24 md:pb-0">{children}</main>
      </div>

      {/* Small screens swap the sidebar for a bottom bar. It scrolls rather
          than truncating, because dropping the overflow made Agent and Members
          unreachable on a phone entirely. */}
      <nav
        className="mc-scroll md:hidden fixed bottom-0 inset-x-0 z-40 flex gap-1 overflow-x-auto px-2 py-2"
        style={{
          backgroundColor: 'var(--surface-nav)',
          borderTop: '1px solid var(--border-subtle)',
        }}
      >
        {PRIMARY_NAV.concat(SECONDARY_NAV).map(({ to, label, Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className="mc-nav-item shrink-0 flex-col gap-0.5 px-3 py-1.5 text-[0.65rem]"
            aria-label={label}
          >
            <Icon size={19} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

export function PageHeader({ title, description, actions }) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4 mb-6">
      <div className="min-w-0">
        <h1 className="text-[1.6rem] font-semibold leading-tight">{title}</h1>
        {description && (
          <p className="mt-1.5 text-sm" style={{ color: 'var(--text-muted)' }}>
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}

export function Page({ children }) {
  return <div className="mx-auto w-full max-w-[1500px] px-5 py-6 md:px-8 md:py-7">{children}</div>
}
