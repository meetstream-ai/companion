import { useEffect, useRef, useState } from 'react'
import Logo from '../components/Logo'
import { ChevronDownIcon } from '../components/Icons'
import DatabasePicker, { isDatabaseFormComplete } from '../components/DatabasePicker'
import { Card, ErrorMessage, Field, Loading, Spinner } from '../components/ui'
import {
  activateConnection, addConnection, addMember, checkJoin, getProviderCatalog, joinWorkspace, listConnections, login,
} from '../api'
import { takePendingJoin } from '../pendingJoin'

/**
 * Which database this sign-in goes against.
 *
 * Everything else that switches database - the header's workspace switcher,
 * Settings - is behind the sign-in wall, so someone who signed out while the
 * app pointed at one database and whose account is on another had no way
 * back: they could not sign in (no account here) and could not switch (no
 * session). Activating is device-gated, not session-gated, and already signs
 * this machine's person in when the database it switches to knows them, so
 * choosing one here either lands them straight in the app or returns this
 * same page pointed at the right database.
 */
function DatabaseSwitch({ connections, disabled, onConnectNew }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const box = useRef(null)

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

  const active = connections.find((conn) => conn.active)

  async function choose(conn) {
    if (busy) return
    if (conn.active) {
      setOpen(false)
      return
    }
    setBusy(true)
    setError(null)
    try {
      await activateConnection(conn.id, null)
      // The database changed underneath the app: reload rather than patch
      // this page's state. Signed in on it already? The reload lands in the
      // app; otherwise here, now asking for an account on that database.
      window.location.reload()
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <div className="mb-4">
      <div className="relative flex justify-center" ref={box}>
        <button
          type="button"
          className="mc-btn mc-btn-ghost text-xs"
          onClick={() => setOpen((v) => !v)}
          disabled={disabled || busy}
          aria-haspopup="menu"
          aria-expanded={open}
        >
          {busy ? <Spinner size={13} /> : null}
          <span className="max-w-[14rem] truncate">Database: {active?.label || 'This computer'}</span>
          <ChevronDownIcon size={14} />
        </button>
        {open && (
          <div role="menu" className="mc-panel absolute top-full z-40 mt-1 min-w-[15rem] overflow-hidden p-1">
            {connections.map((conn) => (
              <button
                key={conn.id}
                type="button"
                role="menuitemradio"
                aria-checked={Boolean(conn.active)}
                disabled={busy || conn.reachable === false}
                className="mc-nav-item flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm"
                onClick={() => choose(conn)}
              >
                <span className="truncate">{conn.label}</span>
                <span className="text-xs" style={{ color: 'var(--text-faint)' }}>
                  {conn.active ? 'Current' : conn.reachable === false ? 'Unreachable' : conn.signed_in ? 'Signs you in' : 'Switch'}
                </span>
              </button>
            ))}
            <div style={{ borderTop: '1px solid var(--border-subtle)' }} className="mt-1 pt-1">
              <button
                type="button"
                role="menuitem"
                className="mc-nav-item w-full px-3 py-2 text-left text-sm"
                disabled={busy}
                onClick={() => {
                  setOpen(false)
                  onConnectNew()
                }}
              >
                Connect another database…
              </button>
            </div>
          </div>
        )}
      </div>
      {error && (
        <p className="mt-2 text-center text-xs" style={{ color: 'var(--danger-fg)' }}>
          {error}
        </p>
      )}
    </div>
  )
}

/**
 * Point this machine at a database it has never seen - the same thing the
 * onboarding wizard's "connect to your team's database" step does, for
 * someone who is already past onboarding and signed out.
 *
 * Saving tests the connection server-side (POST /api/connections refuses a
 * URL it cannot reach), so there is no separate Test button here: this page
 * has no session, and /setup/test-database needs an owner's one.
 */
function ConnectDatabase({ onCancel }) {
  const [catalog, setCatalog] = useState(null)
  const [provider, setProvider] = useState(null)
  const [values, setValues] = useState({})
  const [busy, setBusy] = useState(false)
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

  // A database that already holds your account is a shared one; a local
  // SQLite file is what this machine starts with, not something to connect
  // to. Onboarding's own "connect to your team's database" step hides it too.
  const databases = (catalog?.databases || []).filter((entry) => entry.name !== 'sqlite')
  const entry = databases.find((item) => item.name === provider) || null

  async function connect() {
    setBusy(true)
    setError(null)
    try {
      const conn = await addConnection({ provider, values })
      await activateConnection(conn.id, null)
      // Signed in on it already? The reload lands in the app. Otherwise it
      // returns this page, now pointed at the database just connected.
      window.location.reload()
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <Card>
      <h2 className="text-lg font-semibold">Connect to another database</h2>
      <p className="mt-1 mb-5 text-sm" style={{ color: 'var(--text-muted)' }}>
        Your account and your workspace live in a database. Paste the connection string for the
        one you want to sign in to — it is saved on this computer, so you only do this once.
      </p>

      {error && <ErrorMessage title="Could not connect" detail={error} />}

      {catalog ? (
        <DatabasePicker
          catalog={databases}
          provider={provider}
          values={values}
          onProviderChange={setProvider}
          onValuesChange={setValues}
          showTest={false}
        />
      ) : (
        !error && <Loading label="Loading database options…" />
      )}

      <div className="mt-6 flex items-center justify-between gap-3 border-t pt-5" style={{ borderColor: 'var(--border-subtle)' }}>
        <button type="button" className="mc-btn mc-btn-ghost" onClick={onCancel} disabled={busy}>
          Back to sign in
        </button>
        <button
          type="button"
          className="mc-btn mc-btn-primary"
          onClick={connect}
          disabled={busy || !isDatabaseFormComplete(entry, values)}
        >
          {busy ? <Spinner size={14} /> : null} Connect
        </button>
      </div>
    </Card>
  )
}


export default function SignIn({ onSignedIn, hasMembers = true }) {
  // A join code carried over from the workspace picker: the person asked to
  // join a workspace on another database, we switched to it, and they have no
  // account here yet. Read once, so a later visit is an ordinary sign-in.
  const [carriedJoinCode] = useState(takePendingJoin)
  // Fresh install (no account yet), or arriving with a join code: open on
  // Create account, not a sign-in form nobody can use.
  const [mode, setMode] = useState(hasMembers && !carriedJoinCode ? 'signin' : 'create')
  // Creating an account either starts a workspace or joins one - never
  // "leave a field blank to mean the other". With a code in hand, or other
  // accounts already here, joining is the likely reason to be on this form.
  const [intent, setIntent] = useState(carriedJoinCode || hasMembers ? 'join' : 'new')
  const [form, setForm] = useState({
    name: '',
    email: '',
    password: '',
    workspace_name: '',
    join_code: carriedJoinCode,
    dburl: '',
  })
  // Desktop app only (the endpoint is 404 anywhere else): the workspace a
  // code names lives in one database, and on the desktop that is not
  // necessarily the one this app is on, so joining asks which. On a shared
  // server everyone is on the same database and a code is enough.
  const [desktop, setDesktop] = useState(false)
  // The databases this machine knows, for DatabaseSwitch. Only worth showing
  // when there is somewhere else to go.
  const [connections, setConnections] = useState([])
  const [connectingDb, setConnectingDb] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    listConnections()
      .then((data) => {
        if (cancelled) return
        setDesktop(true)
        setConnections(data.connections || [])
      })
      .catch(() => !cancelled && setDesktop(false))
    return () => {
      cancelled = true
    }
  }, [])

  function update(key, value) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'signin') {
        await login(form.email.trim(), form.password)
      } else {
        const joining = intent === 'join'
        const dburl = joining && desktop && !carriedJoinCode ? form.dburl.trim() : ''
        if (dburl) {
          // The workspace is on another database. Confirm the code is on it
          // before anything moves, then save it, switch to it, and create
          // the account there. If this machine already has an account on it,
          // the switch signs us in and the code just adds a membership.
          await checkJoin({ url: dburl, join_code: form.join_code.trim() })
          const conn = await addConnection({ url: dburl })
          const result = await activateConnection(conn.id, null)
          if (result.signed_in) {
            await joinWorkspace(form.join_code.trim())
            window.location.reload()
            return
          }
        }
        await addMember({
          name: form.name.trim(),
          email: form.email.trim(),
          password: form.password,
          workspace_name: joining ? undefined : form.workspace_name.trim(),
          join_code: joining ? form.join_code.trim() : undefined,
        })
        await login(form.email.trim(), form.password)
        if (dburl) {
          // The database changed underneath the app; start clean on it.
          window.location.reload()
          return
        }
      }
      onSignedIn?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="flex min-h-screen items-center justify-center px-5 py-12"
      style={{ backgroundColor: 'var(--surface-page)' }}
    >
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center text-center">
          <Logo variant="icon" size={64} />
          <h1 className="mt-5 text-2xl font-semibold">Meet Companion</h1>
          <p
            className="mt-1.5 text-[0.7rem] font-semibold uppercase tracking-[0.22em]"
            style={{ color: 'var(--text-faint)' }}
          >
            Make meeting data smarter.
          </p>
        </div>

        {desktop && !connectingDb && (
          <DatabaseSwitch
            connections={connections}
            disabled={busy}
            onConnectNew={() => setConnectingDb(true)}
          />
        )}

        {connectingDb ? <ConnectDatabase onCancel={() => setConnectingDb(false)} /> : <Card>
          <div
            className="mb-5 grid grid-cols-2 gap-1 rounded-xl p-1"
            style={{ backgroundColor: 'var(--surface-raised)' }}
          >
            {['signin', 'create'].map((value) => (
              <button
                key={value}
                type="button"
                className="rounded-lg py-1.5 text-sm font-medium transition-colors"
                style={{
                  backgroundColor: mode === value ? 'var(--surface-panel)' : 'transparent',
                  color: mode === value ? 'var(--text-strong)' : 'var(--text-muted)',
                }}
                onClick={() => {
                  setMode(value)
                  setError(null)
                }}
              >
                {value === 'signin' ? 'Sign in' : 'Create account'}
              </button>
            ))}
          </div>

          <form onSubmit={submit}>
            {carriedJoinCode && mode === 'create' && (
              <p
                className="mb-4 rounded-lg px-3 py-2 text-xs"
                style={{ backgroundColor: 'var(--brand-soft)', color: 'var(--brand-soft-text)' }}
              >
                Connected to that database. Create your account on it to join the workspace —
                the join code is filled in below.
              </p>
            )}
            {mode === 'create' && (
              <Field label="Your name" htmlFor="name">
                <input
                  id="name"
                  className="mc-input"
                  value={form.name}
                  onChange={(event) => update('name', event.target.value)}
                  autoComplete="name"
                />
              </Field>
            )}

            <Field label="Email" htmlFor="email">
              <input
                id="email"
                type="email"
                className="mc-input"
                required
                value={form.email}
                onChange={(event) => update('email', event.target.value)}
                autoComplete="email"
              />
            </Field>

            <Field label="Password" htmlFor="password">
              <input
                id="password"
                type="password"
                className="mc-input"
                required
                value={form.password}
                onChange={(event) => update('password', event.target.value)}
                autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
              />
            </Field>

            {mode === 'create' && (
              <>
                <div className="mc-label">Workspace</div>
                <div
                  className="mb-4 grid grid-cols-2 gap-1 rounded-xl p-1"
                  role="radiogroup"
                  aria-label="Workspace"
                  style={{ backgroundColor: 'var(--surface-raised)' }}
                >
                  {[
                    ['new', 'Start a new one'],
                    ['join', "Join my team's workspace"],
                  ].map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      role="radio"
                      aria-checked={intent === value}
                      className="rounded-lg py-1.5 text-sm font-medium transition-colors"
                      style={{
                        backgroundColor: intent === value ? 'var(--surface-panel)' : 'transparent',
                        color: intent === value ? 'var(--text-strong)' : 'var(--text-muted)',
                      }}
                      onClick={() => {
                        setIntent(value)
                        setError(null)
                      }}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                {intent === 'new' ? (
                  <Field label="Workspace name" hint="You will be its owner." htmlFor="workspace">
                    <input
                      id="workspace"
                      className="mc-input"
                      required
                      value={form.workspace_name}
                      onChange={(event) => update('workspace_name', event.target.value)}
                    />
                  </Field>
                ) : (
                  <>
                    {desktop && !carriedJoinCode && (
                      <Field
                        label="Team's database"
                        hint="A workspace lives in one database, and the code only means something there. Paste the connection string your team shared; leave blank only if the workspace is on the database this app already uses."
                        htmlFor="dburl"
                      >
                        <input
                          id="dburl"
                          className="mc-input"
                          placeholder="postgresql://..."
                          autoComplete="off"
                          value={form.dburl}
                          onChange={(event) => update('dburl', event.target.value)}
                        />
                      </Field>
                    )}
                    <Field label="Join code" hint="Ask a workspace owner — it is on their Members page. They approve your request before you can get in." htmlFor="join">
                      <input
                        id="join"
                        className="mc-input"
                        required
                        value={form.join_code}
                        onChange={(event) => update('join_code', event.target.value)}
                      />
                    </Field>
                  </>
                )}
              </>
            )}

            {error && (
              <div className="mb-4">
                <ErrorMessage title={mode === 'signin' ? 'Could not sign you in' : 'Could not create your account'} detail={error} />
              </div>
            )}

            <button type="submit" className="mc-btn mc-btn-primary w-full" disabled={busy}>
              {busy ? <Spinner size={14} /> : null}
              {mode === 'signin' ? 'Sign in' : 'Create account'}
            </button>
          </form>
        </Card>}

        <p className="mt-5 text-center text-xs" style={{ color: 'var(--text-faint)' }}>
          Forgot your password? A workspace owner can reset it from the Members page.
        </p>
      </div>
    </div>
  )
}
