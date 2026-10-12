import { useMemo, useState } from 'react'
import { ChevronDownIcon, ChevronRightIcon } from './Icons'
import { Field } from './ui'

/**
 * The form for one LLM provider, driven by its descriptor.
 *
 * Most people only need to paste an API key and pick a model, so that is all
 * they see: the model is a drop-down of known names (plus whatever a
 * connection test reported, and a "Custom" escape hatch), and fields the
 * descriptor marks `advanced` - base URL overrides, temperature - sit behind
 * a disclosure.
 */
const CUSTOM = '__custom__'

export default function ProviderFields({ descriptor, values, onChange, discoveredModels = [], keyHint }) {
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [customModel, setCustomModel] = useState(false)

  const basic = descriptor.fields.filter((field) => !field.advanced)
  const advanced = descriptor.fields.filter((field) => field.advanced)

  const modelOptions = useMemo(() => {
    const seen = new Set()
    return [...(descriptor.suggested_models || []), ...discoveredModels].filter((name) => {
      if (!name || seen.has(name)) return false
      seen.add(name)
      return true
    })
  }, [descriptor, discoveredModels])

  const currentModel = values.model ?? ''
  const showCustom = customModel || (currentModel && !modelOptions.includes(currentModel)) || modelOptions.length === 0

  function renderInput(field) {
    const id = `field-${field.key}`
    const value = values[field.key] ?? ''

    if (field.key === 'model' && !showCustom) {
      return (
        <select
          id={id}
          className="mc-input"
          value={currentModel}
          onChange={(event) => {
            if (event.target.value === CUSTOM) {
              setCustomModel(true)
              onChange('model', '')
              return
            }
            onChange('model', event.target.value)
          }}
        >
          {!currentModel && <option value="">Choose a model…</option>}
          {modelOptions.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
          <option value={CUSTOM}>Custom…</option>
        </select>
      )
    }

    return (
      <input
        id={id}
        className="mc-input"
        type={field.type === 'password' ? 'password' : field.type === 'number' ? 'number' : 'text'}
        step={field.type === 'number' ? '0.1' : undefined}
        placeholder={field.placeholder || ''}
        value={value}
        onChange={(event) => onChange(field.key, event.target.value)}
        autoComplete={field.type === 'password' ? 'off' : undefined}
      />
    )
  }

  function renderField(field) {
    const hint = field.key === 'api_key' && keyHint ? keyHint : field.help
    return (
      <Field key={field.key} label={field.label} hint={hint} htmlFor={`field-${field.key}`}>
        {renderInput(field)}
        {field.key === 'model' && showCustom && modelOptions.length > 0 && (
          <button
            type="button"
            className="mt-1 text-xs hover:underline"
            style={{ color: 'var(--text-faint)' }}
            onClick={() => {
              setCustomModel(false)
              onChange('model', modelOptions[0])
            }}
          >
            Choose from the list instead
          </button>
        )}
      </Field>
    )
  }

  return (
    <>
      {descriptor.local && (
        <div
          className="mb-4 rounded-lg px-3 py-2.5 text-xs leading-relaxed"
          style={{ backgroundColor: 'var(--brand-soft)', color: 'var(--brand-soft-text)' }}
        >
          <strong>{descriptor.label.replace(/\s*\(local\)$/, '')} is installed separately.</strong> Meet Companion
          does not include it. Install it from{' '}
          <a href="https://ollama.com/download" target="_blank" rel="noreferrer" className="underline">ollama.com</a>,
          then pull a model, for example <code>ollama pull {values.model || descriptor.suggested_models?.[0] || 'llama3.1'}</code>.
          Test connection checks that it is running.
        </div>
      )}
      {basic.map(renderField)}

      {advanced.length > 0 && (
        <div className="mb-4">
          <button
            type="button"
            className="flex items-center gap-1 text-xs font-medium"
            style={{ color: 'var(--text-muted)' }}
            onClick={() => setAdvancedOpen((open) => !open)}
            aria-expanded={advancedOpen}
          >
            {advancedOpen ? <ChevronDownIcon size={14} /> : <ChevronRightIcon size={14} />}
            Advanced
          </button>
          {advancedOpen && (
            <div
              className="mt-3 rounded-lg px-4 pt-4"
              style={{ backgroundColor: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)' }}
            >
              {advanced.map(renderField)}
            </div>
          )}
        </div>
      )}
    </>
  )
}
