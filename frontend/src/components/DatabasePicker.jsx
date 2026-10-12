import { useMemo, useState } from 'react'
import { ChevronLeftIcon, ChevronRightIcon } from './Icons'
import { ConnectionBadge, Field, Spinner } from './ui'
import { testDatabase } from '../api'

/**
 * Pick a database provider, fill in its form, and test the connection.
 *
 * Two screens: a list of provider cards, then that provider's fields. The
 * caller owns `provider` and `values` so onboarding can carry the choice
 * to the summary step and Settings can save it; this component only
 * decides how it looks and runs the connection test.
 */

const BADGE_TONES = {
  sqlite: { bg: 'var(--color-brand-600)', fg: '#fff' },
  postgresql: { bg: '#336791', fg: '#fff' },
  supabase: { bg: '#3ecf8e', fg: '#0b1f17' },
  neon: { bg: '#00e599', fg: '#0b1f17' },
  railway: { bg: '#8b5cf6', fg: '#fff' },
  'postgres-url': { bg: 'var(--surface-sunken)', fg: 'var(--text-strong)' },
}

function ProviderBadge({ entry }) {
  const tone = entry.available
    ? BADGE_TONES[entry.name] || BADGE_TONES['postgres-url']
    : { bg: 'var(--surface-sunken)', fg: 'var(--text-faint)' }
  return (
    <span
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-[0.7rem] font-bold"
      style={{ backgroundColor: tone.bg, color: tone.fg }}
      aria-hidden="true"
    >
      {entry.badge}
    </span>
  )
}

function ProviderCard({ entry, selected, current, connected, onSelect }) {
  const disabled = !entry.available
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onSelect(entry.name)}
      className="flex w-full items-center gap-4 rounded-xl p-4 text-left transition-colors"
      style={{
        border: `1px solid ${selected ? 'var(--brand-ring)' : 'var(--border-subtle)'}`,
        backgroundColor: selected ? 'var(--brand-soft)' : 'var(--surface-panel)',
        opacity: disabled ? 0.6 : 1,
        cursor: disabled ? 'default' : 'pointer',
      }}
      aria-pressed={selected}
    >
      <ProviderBadge entry={entry} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium" style={{ color: 'var(--text-strong)' }}>
            {entry.label}
          </span>
          {current ? (
            // The one the app is running on right now, and whether it answers.
            <ConnectionBadge connected={connected} />
          ) : (
            entry.recommended && (
              <span
                className="mc-badge"
                style={{ backgroundColor: 'var(--color-peach-200)', color: 'var(--color-peach-700)', borderColor: 'transparent' }}
              >
                Recommended
              </span>
            )
          )}
        </div>
        <p className="mt-0.5 text-sm" style={{ color: 'var(--text-muted)' }}>
          {entry.summary}
        </p>
      </div>
      {disabled ? (
        <span className="mc-badge shrink-0" style={{ color: 'var(--text-faint)' }}>
          Coming soon
        </span>
      ) : (
        <ChevronRightIcon size={16} style={{ color: 'var(--text-faint)' }} />
      )}
    </button>
  )
}

function ProviderFields({ fields, values, onChange }) {
  return (
    <div className="grid gap-x-4 sm:grid-cols-2">
      {fields.map((field) => {
        const id = `db-${field.key}`
        const wide = field.key === 'url' || field.key === 'path'
        const value = values[field.key] ?? field.default ?? ''
        return (
          <div key={field.key} className={wide ? 'sm:col-span-2' : ''}>
            <Field label={field.label} hint={field.help} htmlFor={id}>
              {field.type === 'select' ? (
                <select id={id} className="mc-input" value={value} onChange={(e) => onChange(field.key, e.target.value)}>
                  {field.options.map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
              ) : (
                <input
                  id={id}
                  className="mc-input"
                  type={field.type === 'password' ? 'password' : 'text'}
                  autoComplete="off"
                  required={field.required}
                  placeholder={field.placeholder}
                  value={value}
                  onChange={(e) => onChange(field.key, e.target.value)}
                />
              )}
            </Field>
          </div>
        )
      })}
    </div>
  )
}

export function isDatabaseFormComplete(entry, values) {
  if (!entry) return false
  return (entry.fields || [])
    .filter((field) => field.required)
    .every((field) => String(values[field.key] ?? field.default ?? '').trim().length > 0)
}

export default function DatabasePicker({
  catalog,
  provider,
  values,
  onProviderChange,
  onValuesChange,
  testResult,
  onTestResult,
  current = null,
  connected = null,
  // Testing a connection needs an owner's session (/setup/test-database);
  // the sign-in page has none, and there the Connect button tests the URL
  // server-side anyway, so it asks for the button to be left out.
  showTest = true,
}) {
  const [choosing, setChoosing] = useState(true)
  const entry = useMemo(() => catalog.find((item) => item.name === provider) || null, [catalog, provider])
  const [testing, setTesting] = useState(false)

  function choose(name) {
    onProviderChange(name)
    onValuesChange({})
    onTestResult?.(null)
    setChoosing(false)
  }

  function setValue(key, value) {
    onValuesChange({ ...values, [key]: value })
    onTestResult?.(null)
  }

  async function runTest() {
    setTesting(true)
    onTestResult?.(null)
    try {
      onTestResult?.(await testDatabase({ provider, values }))
    } catch (error) {
      onTestResult?.({ ok: false, detail: error.message })
    } finally {
      setTesting(false)
    }
  }

  if (choosing || !entry) {
    return (
      <div className="grid gap-2">
        {catalog.map((item) => (
          <ProviderCard
            key={item.name}
            entry={item}
            selected={item.name === provider}
            current={item.name === current}
            connected={connected}
            onSelect={choose}
          />
        ))}
      </div>
    )
  }

  const complete = isDatabaseFormComplete(entry, values)

  return (
    <div>
      <div className="mb-5 flex items-center gap-3">
        <button
          type="button"
          className="mc-btn mc-btn-ghost px-2"
          onClick={() => setChoosing(true)}
          aria-label="Choose a different provider"
        >
          <ChevronLeftIcon size={16} />
        </button>
        <ProviderBadge entry={entry} />
        <div className="min-w-0">
          <div className="font-medium" style={{ color: 'var(--text-strong)' }}>{entry.label}</div>
          <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{entry.summary}</div>
        </div>
      </div>

      <ProviderFields fields={entry.fields || []} values={values} onChange={setValue} />

      <div className="flex flex-wrap items-center gap-3">
        {showTest && (
          <button type="button" className="mc-btn mc-btn-secondary" onClick={runTest} disabled={testing || !complete}>
            {testing ? <Spinner size={14} /> : null}
            Test connection
          </button>
        )}
        {testResult && (
          <span
            className="text-sm"
            style={{ color: testResult.ok ? 'var(--color-brand-600)' : 'var(--danger-fg)' }}
          >
            {testResult.ok ? 'Connected.' : testResult.detail}
          </span>
        )}
      </div>
    </div>
  )
}
