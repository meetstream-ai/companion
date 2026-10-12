import { useEffect, useMemo, useState } from 'react'
import Logo from '../components/Logo'
import { CheckIcon, ChevronRightIcon } from '../components/Icons'
import { Card, ErrorMessage, Field, Loading, Spinner } from '../components/ui'
import { addMember, checkJoin, completeSetup, getProviderCatalog, login, setMeetstreamApiKey, testLlmProvider } from '../api'
import DatabasePicker, { isDatabaseFormComplete } from '../components/DatabasePicker'
import ProviderFields from '../components/ProviderFields'

/**
 * First-run setup. Everything is asked up front and applied at the end, in
 * the only order that works: the database first, so the account is created
 * *in* that database - for someone joining a team that is the shared
 * PostgreSQL where the join code lives - then the account, then their
 * MeetStream key, which belongs to the account.
 */
const DEFAULT_STEPS = ['Workspace', 'Account', 'Storage', 'AI model', 'Review']
const RECONNECT_STEPS = ['Connection', 'Account', 'Storage', 'AI model', 'Review']

function StepRail({ current, steps }) {
  return (
    <ol className="flex flex-wrap items-center justify-center gap-2 text-xs font-medium" aria-label="Setup progress">
      {steps.map((label, index) => {
        const done = index < current
        const active = index === current
        return (
          <li key={label} className="flex items-center gap-2">
            <span
              className="flex h-6 w-6 items-center justify-center rounded-full text-[0.7rem]"
              style={{
                backgroundColor: done || active ? 'var(--brand-solid)' : 'var(--surface-raised)',
                color: done || active ? 'var(--text-on-brand)' : 'var(--text-faint)',
              }}
            >
              {done ? <CheckIcon size={13} /> : index + 1}
            </span>
            <span style={{ color: active ? 'var(--text-strong)' : 'var(--text-faint)' }}>{label}</span>
            {index < steps.length - 1 && (
              <ChevronRightIcon size={14} style={{ color: 'var(--text-faint)' }} />
            )}
          </li>
        )
      })}
    </ol>
  )
}

function OptionCard({ selected, onSelect, title, children, badge }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="w-full rounded-xl p-4 text-left transition-colors"
      style={{
        border: `1px solid ${selected ? 'var(--brand-ring)' : 'var(--border-subtle)'}`,
        backgroundColor: selected ? 'var(--brand-soft)' : 'var(--surface-panel)',
        boxShadow: selected ? '0 0 0 3px color-mix(in srgb, var(--brand-ring) 20%, transparent)' : 'none',
      }}
      aria-pressed={selected}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium" style={{ color: 'var(--text-strong)' }}>{title}</span>
        {badge && (
          <span
            className="mc-badge"
            style={{ backgroundColor: 'var(--color-peach-200)', color: 'var(--color-peach-700)', borderColor: 'transparent' }}
          >
            {badge}
          </span>
        )}
      </div>
      <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>{children}</p>
    </button>
  )
}

function ProviderOption({ descriptor, selected, onSelect }) {
  return (
    <OptionCard
      selected={selected}
      onSelect={() => onSelect(descriptor.name)}
      title={descriptor.label}
      badge={descriptor.local ? 'Runs locally' : null}
    >
      {descriptor.summary}
    </OptionCard>
  )
}

function StepButtons({ onBack, onNext, nextLabel = 'Continue', nextDisabled = false, busy = false }) {
  return (
    <div className="mt-6 flex justify-between">
      {onBack ? (
        <button type="button" className="mc-btn mc-btn-ghost" onClick={onBack} disabled={busy}>
          Back
        </button>
      ) : <span />}
      <button type="button" className="mc-btn mc-btn-primary" onClick={onNext} disabled={nextDisabled || busy}>
        {busy ? <Spinner size={14} /> : null}
        {nextLabel}
        {!busy && <ChevronRightIcon size={16} />}
      </button>
    </div>
  )
}

function Row({ label, children }) {
  return (
    <div className="flex justify-between gap-4 py-3">
      <dt className="text-sm" style={{ color: 'var(--text-muted)' }}>{label}</dt>
      <dd className="truncate text-sm font-medium">{children}</dd>
    </div>
  )
}

export default function Onboarding({ onComplete }) {
  const [step, setStep] = useState(0)
  const [catalog, setCatalog] = useState(null)
  const [loadError, setLoadError] = useState(null)

  // Step 0 - workspace
  const [mode, setMode] = useState('start') // 'start' | 'join' | 'reconnect'
  const [workspaceName, setWorkspaceName] = useState('')
  const [joinCode, setJoinCode] = useState('')

  // Step 1 - account
  const [account, setAccount] = useState({ name: '', email: '', password: '', meetstream_api_key: '' })

  // Step 2 - storage
  const [storage, setStorage] = useState('sqlite') // the Recommended default
  const [dbValues, setDbValues] = useState({})
  const [dbTest, setDbTest] = useState(null)
  // Join path: the code is checked against the database *with* it, before
  // either is applied, so "wrong code" or "wrong database" is caught here
  // rather than after the app has already been pointed at that database.
  const [joinCheck, setJoinCheck] = useState({ busy: false, error: null, workspace: null })

  // Step 3 - AI
  const [provider, setProvider] = useState('ollama')
  const [values, setValues] = useState({})
  const [llmTest, setLlmTest] = useState(null)
  const [testing, setTesting] = useState(false)

  // Step 4 - finish
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  // Server-wide setup is accepted exactly once (it closes first-run); if a
  // later step fails, a retry must not send it again.
  const [progress, setProgress] = useState({ setup: false, account: false })
  const [keyWarning, setKeyWarning] = useState(null)

  useEffect(() => {
    getProviderCatalog()
      .then(setCatalog)
      .catch((error) => setLoadError(error.message))
  }, [])

  const descriptor = useMemo(
    () => catalog?.llm.find((item) => item.name === provider) || null,
    [catalog, provider],
  )

  // Reset to the newly chosen provider's defaults, so switching never leaves
  // a stale key or host from the previous one behind.
  useEffect(() => {
    if (!descriptor) return
    const defaults = {}
    descriptor.fields.forEach((field) => {
      if (field.default !== null && field.default !== undefined) defaults[field.key] = field.default
    })
    setValues(defaults)
    setLlmTest(null)
  }, [descriptor])

  // Joining a team means sharing its database: a private SQLite file could
  // never contain the workspace the join code refers to.
  const databases = useMemo(() => {
    if (!catalog) return []
    // Reconnecting to an existing account or joining a team: a local SQLite
    // could never contain the workspace the user refers to.
    return mode === 'join' || mode === 'reconnect' ? catalog.databases.filter((d) => d.name !== 'sqlite') : catalog.databases
  }, [catalog, mode])

  function chooseMode(next) {
    setMode(next)
    if ((next === 'join' || next === 'reconnect') && storage === 'sqlite') {
      setStorage('postgres-url')
      setDbValues({})
      setDbTest(null)
    }
  }

  function updateValue(key, value) {
    setValues((current) => ({ ...current, [key]: value }))
    setLlmTest(null)
  }

  function buildLlmPayload() {
    return {
      provider,
      model: values.model || null,
      api_key: values.api_key || null,
      base_url: values.base_url || null,
      temperature: values.temperature ? Number(values.temperature) : null,
    }
  }

  async function runLlmTest() {
    setTesting(true)
    setLlmTest(null)
    try {
      setLlmTest(await testLlmProvider(buildLlmPayload()))
    } catch (error) {
      setLlmTest({ ok: false, detail: error.message })
    } finally {
      setTesting(false)
    }
  }

  async function finish() {
    setSaving(true)
    setSaveError(null)
    setKeyWarning(null)
    const email = account.email.trim()
    try {
      if (!progress.setup) {
        await completeSetup({
          llm: buildLlmPayload(),
          database: { provider: storage, values: dbValues },
        })
        setProgress((p) => ({ ...p, setup: true }))
      }
      // Reconnect mode: the account already exists on the target database;
      // skip creation and sign in directly.
      if (mode !== 'reconnect' && !progress.account) {
        await addMember({
          name: account.name.trim(),
          email,
          password: account.password,
          workspace_name: mode === 'start' ? workspaceName.trim() : undefined,
          join_code: mode === 'join' ? joinCode.trim() : undefined,
        })
        setProgress((p) => ({ ...p, account: true }))
      }
      await login(email, account.password)
      const key = account.meetstream_api_key.trim()
      if (key) {
        try {
          const result = await setMeetstreamApiKey(key)
          if (!result.connected) {
            setKeyWarning(result.connection_error || 'Saved, but MeetStream did not accept the key.')
            return
          }
        } catch (error) {
          setKeyWarning(`Your account is ready, but the MeetStream key was not saved: ${error.message}`)
          return
        }
      }
      onComplete?.()
    } catch (error) {
      // In the join flow the code is looked up in the database just
      // connected to. "Not found" is at least as likely to mean the wrong
      // database as a mistyped code, so say both.
      const notFound = mode === 'join' && /No workspace found with that join code/i.test(error.message)
      setSaveError(
        notFound
          ? 'No workspace with that join code exists in the database you connected to. Check the code, and that the connection string is the one your workspace owner shared — a workspace lives in one database, and every member must use that one.'
          : error.message,
      )
    } finally {
      setSaving(false)
    }
  }

  if (loadError) {
    return (
      <div className="mx-auto max-w-lg px-5 py-20">
        <ErrorMessage
          title="Could not reach the Meet Companion server"
          detail={loadError}
          onRetry={() => window.location.reload()}
        />
      </div>
    )
  }

  if (!catalog) {
    return <Loading label="Preparing setup…" />
  }

  const steps = mode === 'reconnect' ? RECONNECT_STEPS : DEFAULT_STEPS
  const canLeaveWorkspace = mode === 'start' ? workspaceName.trim().length > 0 : true
  const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(account.email.trim())
  const canLeaveAccount = mode === 'reconnect'
    ? emailOk && account.password.length >= 8
    : account.name.trim().length > 0 && emailOk && account.password.length >= 8
  const dbEntry = databases.find((item) => item.name === storage)
  const canLeaveStorage =
    Boolean(dbEntry) && isDatabaseFormComplete(dbEntry, dbValues) && (mode === 'start' || mode === 'reconnect' || joinCode.trim().length > 0)

  async function leaveStorage() {
    if (mode !== 'join') {
      // 'start' and 'reconnect' have nothing to check against the database.
      setStep(3)
      return
    }
    setJoinCheck({ busy: true, error: null, workspace: null })
    try {
      const result = await checkJoin({ provider: storage, values: dbValues, join_code: joinCode.trim() })
      setJoinCheck({ busy: false, error: null, workspace: result.workspace })
      setStep(3)
    } catch (error) {
      setJoinCheck({ busy: false, error: error.message, workspace: null })
    }
  }
  const canLeaveProvider =
    Boolean(values.model) &&
    Boolean(descriptor) &&
    descriptor.fields
      .filter((field) => field.required)
      .every((field) => String(values[field.key] ?? '').trim().length > 0)

  const muted = { color: 'var(--text-muted)' }

  return (
    <div className="min-h-screen" style={{ backgroundColor: 'var(--surface-page)' }}>
      <div className="mx-auto w-full max-w-2xl px-5 py-12">
        <div className="mb-8 flex justify-center">
          <StepRail current={step} steps={steps} />
        </div>

        {step === 0 && (
          <Card>
            <div className="flex flex-col items-center pb-6 text-center">
              <Logo variant="icon" size={64} />
              <h1 className="mt-4 text-2xl font-semibold">Welcome to Meet Companion</h1>
              <p className="mt-2 max-w-md text-sm leading-relaxed" style={muted}>
                Your own AI meeting companion — your models, your storage, your data. First: is
                this a workspace of your own, or are you joining one?
              </p>
            </div>

            <div className="grid gap-2 sm:grid-cols-2">
              <OptionCard selected={mode === 'start'} onSelect={() => chooseMode('start')} title="Start a workspace" badge="Most people">
                Just you, or you are setting it up for your team. You will be its owner.
              </OptionCard>
              <OptionCard selected={mode === 'join'} onSelect={() => chooseMode('join')} title="Join my team's workspace">
                Someone gave you a join code. Next you connect to the team's database and enter the code there.
              </OptionCard>
            </div>

            <div className="mt-2">
              <OptionCard selected={mode === 'reconnect'} onSelect={() => chooseMode('reconnect')} title="Already have an account?">
                You set up Meet Companion before and already have an account on a database — this system just needs to be pointed at it.
              </OptionCard>
            </div>

            <div className="mt-6">
              {mode === 'start' ? (
                <Field label="Workspace name" htmlFor="ob-workspace" hint="Your team or company — shown in the top bar. You can rename it later.">
                  <input
                    id="ob-workspace"
                    className="mc-input"
                    value={workspaceName}
                    onChange={(e) => setWorkspaceName(e.target.value)}
                    placeholder="e.g. Acme"
                    autoFocus
                  />
                </Field>
              ) : (
                <p className="text-sm" style={muted}>
                  You will need two things from your workspace owner: the connection string of the
                  team's database, and the join code from their Members page. An owner approves your
                  request before you can get in.
                </p>
              )}
            </div>

            <StepButtons onNext={() => setStep(1)} nextDisabled={!canLeaveWorkspace} />
          </Card>
        )}

        {step === 1 && (
          <Card>
            <h2 className="text-lg font-semibold">
              {mode === 'reconnect' ? 'Sign in to your existing account' : 'Your account'}
            </h2>
            <p className="mt-1 mb-5 text-sm" style={muted}>
              {mode === 'reconnect'
                ? 'Enter the credentials of the account you already have on the database you will connect to next.'
                : mode === 'start'
                  ? 'This account owns the workspace: it configures the server and invites others.'
                  : 'This is you inside the team workspace.'}
            </p>

            {mode !== 'reconnect' && (
              <Field label="Name" htmlFor="ob-name">
                <input id="ob-name" className="mc-input" autoComplete="name" value={account.name}
                  onChange={(e) => setAccount({ ...account, name: e.target.value })} autoFocus />
              </Field>
            )}
            <Field label="Email" htmlFor="ob-email">
              <input id="ob-email" type="email" className="mc-input" autoComplete="email" value={account.email}
                onChange={(e) => setAccount({ ...account, email: e.target.value })} autoFocus={mode === 'reconnect'} />
            </Field>
            <Field label="Password" htmlFor="ob-password" hint={mode === 'reconnect' ? 'The password for your existing account.' : 'At least 8 characters.'}>
              <input id="ob-password" type="password" className="mc-input" autoComplete={mode === 'reconnect' ? 'current-password' : 'new-password'} value={account.password}
                onChange={(e) => setAccount({ ...account, password: e.target.value })} />
            </Field>

            {mode !== 'reconnect' && (
              <div className="mt-6 border-t pt-5" style={{ borderColor: 'var(--border-subtle)' }}>
                <Field
                  label="MeetStream API key"
                  htmlFor="ob-meetstream"
                  hint="Lets Meet Companion send a bot into your calls. Optional — skip it if you only upload transcripts; you can add it any time in Settings → Meetings."
                >
                  <input id="ob-meetstream" type="password" className="mc-input font-mono" autoComplete="off"
                    value={account.meetstream_api_key}
                    onChange={(e) => setAccount({ ...account, meetstream_api_key: e.target.value })}
                    placeholder="ms_…" />
                </Field>
              </div>
            )}

            <StepButtons onBack={() => setStep(0)} onNext={() => setStep(2)} nextDisabled={!canLeaveAccount} />
          </Card>
        )}

        {step === 2 && (
          <Card>
            <h2 className="text-lg font-semibold">
              {mode === 'join' ? "Connect to your team's database" : mode === 'reconnect' ? 'Connect to your database' : 'Where should Meet Companion store your data?'}
            </h2>
            <p className="mt-1 mb-5 text-sm" style={muted}>
              {mode === 'reconnect'
                ? 'Point this system at the database where your account and data live.'
                : mode === 'join'
                  ? 'Meetings, notes and memory are shared through it. Paste the connection string your workspace owner gave you.'
                  : 'Meetings, notes and memory all live here. Local SQLite needs nothing installed; pick a hosted Postgres to share the workspace with others.'}
            </p>

            <DatabasePicker
              catalog={databases}
              provider={storage}
              values={dbValues}
              onProviderChange={setStorage}
              onValuesChange={setDbValues}
              testResult={dbTest}
              onTestResult={setDbTest}
            />

            {mode === 'join' && (
              <div className="mt-6 border-t pt-5" style={{ borderColor: 'var(--border-subtle)' }}>
                <Field
                  label="Join code"
                  htmlFor="ob-join"
                  hint="From your workspace owner's Members page. It is checked against this database when you continue."
                  error={joinCheck.error}
                >
                  <input
                    id="ob-join"
                    className="mc-input font-mono"
                    value={joinCode}
                    onChange={(e) => {
                      setJoinCode(e.target.value)
                      if (joinCheck.error) setJoinCheck({ busy: false, error: null, workspace: null })
                    }}
                    placeholder="e.g. 646f1536"
                  />
                </Field>
              </div>
            )}

            <StepButtons onBack={() => setStep(1)} onNext={leaveStorage} nextDisabled={!canLeaveStorage} busy={joinCheck.busy} />
          </Card>
        )}

        {step === 3 && (
          <Card>
            <h2 className="text-lg font-semibold">Choose your AI model</h2>
            <p className="mt-1 mb-5 text-sm" style={muted}>
              Used to extract decisions and action items from meetings, and to answer questions
              about your notes. You can change this later in Settings.
            </p>

            <div className="grid gap-2 sm:grid-cols-2">
              {catalog.llm.map((item) => (
                <ProviderOption key={item.name} descriptor={item} selected={item.name === provider} onSelect={setProvider} />
              ))}
            </div>

            {descriptor && (
              <div className="mt-6 border-t pt-5" style={{ borderColor: 'var(--border-subtle)' }}>
                <ProviderFields
                  descriptor={descriptor}
                  values={values}
                  onChange={updateValue}
                  discoveredModels={llmTest?.models || []}
                />

                <div className="flex items-center gap-3">
                  <button type="button" className="mc-btn mc-btn-secondary" onClick={runLlmTest} disabled={testing}>
                    {testing ? <Spinner size={14} /> : null}
                    Test connection
                  </button>
                  {llmTest && (
                    <span className="text-sm" style={{ color: llmTest.ok ? 'var(--color-brand-600)' : 'var(--color-rose-700)' }}>
                      {llmTest.ok ? 'Connected.' : llmTest.detail}
                    </span>
                  )}
                </div>
              </div>
            )}

            <StepButtons onBack={() => setStep(2)} onNext={() => setStep(4)} nextDisabled={!canLeaveProvider} />
          </Card>
        )}

        {step === 4 && (
          <Card>
            <h2 className="text-lg font-semibold">Review</h2>
            <p className="mt-1 mb-5 text-sm" style={muted}>
              You can change any of this later in Settings.
            </p>

            <dl className="divide-y" style={{ borderColor: 'var(--border-subtle)' }}>
              <Row label="Workspace">{mode === 'start' ? `${workspaceName.trim()} (new — you own it)` : mode === 'reconnect' ? 'Signing in to existing account' : `Joining ${joinCheck.workspace || 'with code ' + joinCode.trim()} - an owner approves your request`}</Row>
              <Row label="Account">{account.name.trim()} · {account.email.trim()}</Row>
              {mode !== 'reconnect' && <Row label="MeetStream">{account.meetstream_api_key.trim() ? 'API key provided' : 'Not now'}</Row>}
              <Row label="Storage">{dbEntry?.label || storage}</Row>
              <Row label="AI provider">{descriptor?.label}</Row>
              <Row label="Model">{values.model || '—'}</Row>
              {values.base_url && <Row label="Endpoint">{values.base_url}</Row>}
            </dl>

            {saveError && (
              <div className="mt-4">
                <ErrorMessage title="Could not finish setup" detail={saveError} />
              </div>
            )}
            {keyWarning && (
              <div className="mt-4">
                <ErrorMessage title="Set up, with one thing to fix" detail={`${keyWarning} You can enter the key again in Settings → Meetings.`} />
                <button type="button" className="mc-btn mc-btn-primary mt-3" onClick={() => onComplete?.()}>
                  Continue to the app
                </button>
              </div>
            )}

            {!keyWarning && (
              <StepButtons onBack={() => setStep(3)} onNext={finish} nextLabel="Finish setup" busy={saving} />
            )}
          </Card>
        )}
      </div>
    </div>
  )
}
