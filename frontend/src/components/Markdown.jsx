import { useMemo } from 'react'
import DOMPurify from 'dompurify'
import { marked } from 'marked'

marked.setOptions({ gfm: true, breaks: true })

/**
 * Rendered Markdown, sanitised.
 *
 * Task-list checkboxes are live: clicking one calls `onToggleTask(index,
 * checked)` with the position of that checkbox among all task items in the
 * document, so the caller can flip `- [ ]` / `- [x]` in the source text.
 */
export default function Markdown({ source, onToggleTask, className = '' }) {
  const html = useMemo(() => {
    const rendered = marked.parse(source || '')
    // Task checkboxes come out disabled by default; enable them so they
    // read as something you can tick.
    const enabled = rendered.replace(/<input((?:\s+checked="")?)\s+disabled=""(\s+type="checkbox")/g, '<input$1$2')
    return DOMPurify.sanitize(enabled, { USE_PROFILES: { html: true } })
  }, [source])

  function handleClick(event) {
    const target = event.target
    if (!(target instanceof HTMLInputElement) || target.type !== 'checkbox') return
    if (!onToggleTask) {
      event.preventDefault()
      return
    }
    const boxes = Array.from(event.currentTarget.querySelectorAll('input[type="checkbox"]'))
    onToggleTask(boxes.indexOf(target), target.checked)
  }

  return (
    <div
      className={`mc-prose ${className}`}
      onClick={handleClick}
      // Sanitised above; nothing reaches here that DOMPurify did not allow.
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

/** Flip the n-th task checkbox in a Markdown document. */
export function toggleTaskInMarkdown(source, index, checked) {
  let seen = -1
  return (source || '')
    .split('\n')
    .map((line) => {
      const match = line.match(/^(\s*(?:[-*+]|\d+[.)])\s+)\[( |x|X)\](.*)$/)
      if (!match) return line
      seen += 1
      if (seen !== index) return line
      return `${match[1]}[${checked ? 'x' : ' '}]${match[3]}`
    })
    .join('\n')
}
