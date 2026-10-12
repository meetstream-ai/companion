import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import Markdown, { toggleTaskInMarkdown } from '../components/Markdown'

describe('Markdown', () => {
  it('renders Markdown and strips script and event handlers', () => {
    const { container } = render(
      <Markdown source={'# Title\n\n<img src=x onerror="alert(1)"><script>alert(2)</script>**bold**'} />,
    )
    expect(container.querySelector('h1')).toHaveTextContent('Title')
    expect(container.querySelector('strong')).toHaveTextContent('bold')
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')?.getAttribute('onerror')).toBeFalsy()
  })

  it('makes task checkboxes live and reports which one was clicked', () => {
    const onToggle = vi.fn()
    render(<Markdown source={'- [ ] first\n- [x] second\n- [ ] third'} onToggleTask={onToggle} />)
    const boxes = screen.getAllByRole('checkbox')
    expect(boxes).toHaveLength(3)
    expect(boxes.every((box) => !box.disabled)).toBe(true)
    fireEvent.click(boxes[2])
    expect(onToggle).toHaveBeenCalledWith(2, true)
  })
})

describe('toggleTaskInMarkdown', () => {
  it('flips only the n-th task and leaves everything else byte-identical', () => {
    const source = 'intro\n- [ ] a\n  - [x] nested\n1. [ ] numbered\n- not a task [ ]'
    expect(toggleTaskInMarkdown(source, 1, false)).toBe('intro\n- [ ] a\n  - [ ] nested\n1. [ ] numbered\n- not a task [ ]')
    expect(toggleTaskInMarkdown(source, 2, true)).toBe('intro\n- [ ] a\n  - [x] nested\n1. [x] numbered\n- not a task [ ]')
    expect(toggleTaskInMarkdown(source, 99, true)).toBe(source)
  })
})
