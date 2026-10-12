import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Page, PageHeader } from '../components/AppShell'
import { ChevronDownIcon, ChevronRightIcon, CloseIcon, SearchIcon, SettingsIcon } from '../components/Icons'
import { Badge, Card, EmptyState, ErrorMessage, Spinner } from '../components/ui'
import { getKnowledgeGraph } from '../api'

/**
 * Knowledge graph.
 *
 * A dependency-free force simulation - pairwise repulsion, spring edges and
 * explicit collision separation - with the forces exposed as settings rather
 * than baked in, so the layout can be tuned for a dense or sparse graph.
 */

const NODE_COLOURS = {
  meeting: 'var(--color-brand-500)',
  person: 'var(--color-lavender-400)',
  memory: 'var(--color-peach-500)',
  action_item: 'var(--color-rose-500)',
  project: 'var(--color-brand-700)',
  customer: 'var(--color-brand-300)',
}

const NODE_TYPES = Object.keys(NODE_COLOURS)
const BASE_RADIUS = { meeting: 15, person: 11, customer: 11, project: 11, memory: 7, action_item: 7 }

/** Children sit close to their meeting; looser links keep clusters apart. */
const EDGE_DISTANCE_SCALE = {
  produced: 0.61,
  said: 0.5,
  owns: 0.5,
  participated_in: 1.11,
  for_customer: 1.22,
  for_project: 1.22,
}

const WIDTH = 1000
const HEIGHT = 580
const SETTLE_SPEED = 0.12
const MAX_RUNTIME_MS = 6000
const SETTINGS_KEY = 'meet-companion:graph-settings'

const DEFAULTS = {
  // Filters
  types: Object.fromEntries(NODE_TYPES.map((type) => [type, true])),
  showOrphans: true,
  // Display
  nodeSize: 1,
  linkThickness: 1,
  labelThreshold: 0.75,
  showArrows: false,
  // Forces
  repel: 3200,
  linkDistance: 90,
  linkForce: 0.03,
  centerForce: 1,
}

function loadSettings() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(SETTINGS_KEY) || '{}')
    return { ...DEFAULTS, ...stored, types: { ...DEFAULTS.types, ...(stored.types || {}) } }
  } catch {
    return DEFAULTS
  }
}

function radiusFor(type, degree, scale) {
  return ((BASE_RADIUS[type] || 7) + Math.min(Math.sqrt(degree) * 3, 14)) * scale
}

function useForceLayout(nodes, edges, forces) {
  const positions = useRef(new Map())
  const draggingId = useRef(null)
  const settledOnce = useRef(false)
  const [, setTick] = useState(0)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const pos = positions.current
    for (const node of nodes) {
      if (!pos.has(node.id)) {
        pos.set(node.id, {
          x: WIDTH / 2 + (Math.random() - 0.5) * 320,
          y: HEIGHT / 2 + (Math.random() - 0.5) * 320,
          vx: 0,
          vy: 0,
        })
      }
    }
    for (const id of [...pos.keys()]) {
      if (!nodes.some((node) => node.id === id)) pos.delete(id)
    }

    const degree = new Map(nodes.map((node) => [node.id, 0]))
    for (const edge of edges) {
      degree.set(edge.source, (degree.get(edge.source) || 0) + 1)
      degree.set(edge.target, (degree.get(edge.target) || 0) + 1)
    }
    const radius = new Map(
      nodes.map((n) => [n.id, radiusFor(n.type, degree.get(n.id) || 0, forces.nodeSize)]),
    )
    const ids = nodes.map((node) => node.id)
    const deadline = performance.now() + MAX_RUNTIME_MS

    let frame = 0
    function step() {
      for (let i = 0; i < ids.length; i++) {
        const a = pos.get(ids[i])
        const ra = radius.get(ids[i])
        for (let j = i + 1; j < ids.length; j++) {
          const b = pos.get(ids[j])
          const dx = a.x - b.x
          const dy = a.y - b.y
          const distSq = Math.max(dx * dx + dy * dy, 1)
          const dist = Math.sqrt(distSq)

          let fx = (dx / dist) * (forces.repel / distSq)
          let fy = (dy / dist) * (forces.repel / distSq)

          // Without explicit separation, dense clusters render as blobs no
          // matter how the rest of the layout settles.
          const minDist = ra + radius.get(ids[j]) + 6
          if (dist < minDist) {
            const push = (minDist - dist) * 0.5
            fx += (dx / dist) * push
            fy += (dy / dist) * push
          }
          a.vx += fx; a.vy += fy
          b.vx -= fx; b.vy -= fy
        }
      }

      for (const edge of edges) {
        const a = pos.get(edge.source)
        const b = pos.get(edge.target)
        if (!a || !b) continue
        const dx = b.x - a.x
        const dy = b.y - a.y
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
        const target = forces.linkDistance * (EDGE_DISTANCE_SCALE[edge.type] ?? 1)
        const force = (dist - target) * forces.linkForce
        const fx = (dx / dist) * force
        const fy = (dy / dist) * force
        a.vx += fx; a.vy += fy
        b.vx -= fx; b.vy -= fy
      }

      // Gravity eases off as the graph grows, or it fights the repulsion that
      // separates clusters.
      const gravity = (0.001 * forces.centerForce) / Math.max(1, Math.sqrt(ids.length / 20))
      let totalSpeed = 0
      for (const id of ids) {
        if (id === draggingId.current) continue
        const p = pos.get(id)
        p.vx = (p.vx + (WIDTH / 2 - p.x) * gravity) * 0.82
        p.vy = (p.vy + (HEIGHT / 2 - p.y) * gravity) * 0.82
        p.x = Math.max(24, Math.min(WIDTH - 24, p.x + p.vx))
        p.y = Math.max(24, Math.min(HEIGHT - 24, p.y + p.vy))
        totalSpeed += Math.abs(p.vx) + Math.abs(p.vy)
      }

      setTick((t) => t + 1)

      const calm = ids.length > 0 && totalSpeed / ids.length < SETTLE_SPEED
      if (calm || performance.now() > deadline) {
        // The "arranging" overlay is only for the very first layout. Adjusting
        // a force afterwards re-settles in place rather than hiding the graph.
        settledOnce.current = true
        setReady(true)
        if (performance.now() > deadline) return
      }
      frame = requestAnimationFrame(step)
    }

    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [nodes, edges, forces])

  return {
    positions: positions.current,
    draggingId,
    ready: ready || settledOnce.current,
    bump: () => setTick((t) => t + 1),
  }
}

function Slider({ label, value, min, max, step, onChange, format }) {
  return (
    <label className="mb-3 block">
      <div className="mb-1 flex items-center justify-between text-xs">
        <span style={{ color: 'var(--text-muted)' }}>{label}</span>
        <span className="font-mono" style={{ color: 'var(--text-faint)' }}>
          {format ? format(value) : value}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full"
        style={{ accentColor: 'var(--brand-solid)' }}
      />
    </label>
  )
}

function Toggle({ label, checked, onChange }) {
  return (
    <label className="mb-2 flex cursor-pointer items-center gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        style={{ accentColor: 'var(--brand-solid)' }}
      />
      {label}
    </label>
  )
}

function Section({ title, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-b last:border-b-0" style={{ borderColor: 'var(--border-subtle)' }}>
      <button
        type="button"
        className="flex w-full items-center gap-1.5 px-4 py-2.5 text-[0.65rem] font-semibold uppercase tracking-[0.12em]"
        style={{ color: 'var(--text-faint)' }}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? <ChevronDownIcon size={13} /> : <ChevronRightIcon size={13} />}
        {title}
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  )
}

function NodeDetail({ node, nodes, edges }) {
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])
  const related = useMemo(() => {
    if (!node) return []
    const out = []
    for (const edge of edges) {
      if (edge.source === node.id) out.push(byId.get(edge.target))
      else if (edge.target === node.id) out.push(byId.get(edge.source))
    }
    return out.filter(Boolean)
  }, [node, edges, byId])

  if (!node) {
    return <EmptyState title="Select a node" description="Click anything in the graph to see what it connects to." />
  }

  return (
    <div className="p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge tone="brand">{node.type.replace('_', ' ')}</Badge>
        {node.date && (
          <span className="text-xs" style={{ color: 'var(--text-faint)' }}>
            {new Date(node.date).toLocaleDateString()}
          </span>
        )}
      </div>

      <h3 className="text-base font-semibold">{node.label}</h3>

      {node.summary && (
        <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--text-muted)' }}>
          {node.summary.slice(0, 320)}
        </p>
      )}
      {node.content && (
        <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--text-muted)' }}>
          {node.content}
        </p>
      )}
      {node.task && <p className="mt-2 text-sm">{node.task}</p>}

      <div className="mt-3 flex flex-wrap gap-1.5">
        {node.speaker && <Badge>{node.speaker}</Badge>}
        {node.owner && <Badge>{node.owner}</Badge>}
        {node.status && <Badge>{node.status}</Badge>}
        {node.platform && <Badge>{node.platform}</Badge>}
      </div>

      {node.meeting_id && (
        <Link to={`/meetings/${node.meeting_id}`} className="mc-btn mc-btn-secondary mt-4 w-full">
          Open meeting
        </Link>
      )}

      <div className="mt-5">
        <div
          className="mb-2 text-[0.65rem] font-semibold uppercase tracking-[0.14em]"
          style={{ color: 'var(--text-faint)' }}
        >
          Connected ({related.length})
        </div>
        <ul className="mc-scroll max-h-56 space-y-1 overflow-y-auto">
          {related.slice(0, 40).map((item) => (
            <li
              key={item.id}
              className="truncate rounded-lg px-2 py-1.5 text-xs"
              style={{ backgroundColor: 'var(--surface-raised)', color: 'var(--text-default)' }}
            >
              <span
                className="mr-2 inline-block h-2 w-2 rounded-full align-middle"
                style={{ backgroundColor: NODE_COLOURS[item.type] || 'var(--text-faint)' }}
              />
              {item.label}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

export default function Graph() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState(null)
  const [view, setView] = useState({ x: 0, y: 0, k: 1 })
  const [showSettings, setShowSettings] = useState(false)
  const [settings, setSettings] = useState(loadSettings)

  const svgRef = useRef(null)
  const panRef = useRef(null)
  const dragRef = useRef(null)

  useEffect(() => {
    getKnowledgeGraph().then(setData).catch((err) => setError(err.message))
  }, [])

  useEffect(() => {
    try {
      window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings))
    } catch {
      // Preferences only; the graph works fine without them persisting.
    }
  }, [settings])

  function update(patch) {
    setSettings((current) => ({ ...current, ...patch }))
  }

  function toggleType(type) {
    setSettings((current) => ({ ...current, types: { ...current.types, [type]: !current.types[type] } }))
  }

  const filtersActive =
    Boolean(query.trim()) ||
    !settings.showOrphans ||
    NODE_TYPES.some((type) => !settings.types[type])

  function clearFilters() {
    setQuery('')
    update({ types: { ...DEFAULTS.types }, showOrphans: DEFAULTS.showOrphans })
  }

  const allNodes = data?.nodes || []
  const allEdges = data?.edges || []

  // Memoised on stable inputs: rebuilding these arrays every render would
  // restart the simulation on every animation frame.
  const nodes = useMemo(() => {
    const byType = allNodes.filter((node) => settings.types[node.type] !== false)
    if (settings.showOrphans) return byType

    const connected = new Set()
    const visible = new Set(byType.map((node) => node.id))
    for (const edge of allEdges) {
      if (visible.has(edge.source) && visible.has(edge.target)) {
        connected.add(edge.source)
        connected.add(edge.target)
      }
    }
    return byType.filter((node) => connected.has(node.id))
  }, [allNodes, allEdges, settings.types, settings.showOrphans])

  const edges = useMemo(() => {
    const ids = new Set(nodes.map((node) => node.id))
    return allEdges.filter((edge) => ids.has(edge.source) && ids.has(edge.target))
  }, [allEdges, nodes])

  const degrees = useMemo(() => {
    const counts = new Map(nodes.map((node) => [node.id, 0]))
    for (const edge of edges) {
      counts.set(edge.source, (counts.get(edge.source) || 0) + 1)
      counts.set(edge.target, (counts.get(edge.target) || 0) + 1)
    }
    return counts
  }, [nodes, edges])

  // Only the values the simulation reads, so tweaking a display setting does
  // not re-run the layout.
  const forces = useMemo(
    () => ({
      repel: settings.repel,
      linkDistance: settings.linkDistance,
      linkForce: settings.linkForce,
      centerForce: settings.centerForce,
      nodeSize: settings.nodeSize,
    }),
    [settings.repel, settings.linkDistance, settings.linkForce, settings.centerForce, settings.nodeSize],
  )

  const { positions, draggingId, ready, bump } = useForceLayout(nodes, edges, forces)

  /** Plain substring matching over labels - distinct from semantic search. */
  const matches = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (!term) return null
    const found = new Set()
    for (const node of nodes) {
      const haystack = [node.label, node.content, node.task, node.summary, node.speaker, node.owner]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      if (haystack.includes(term)) found.add(node.id)
    }
    return found
  }, [query, nodes])

  const selected = allNodes.find((node) => node.id === selectedId) || null
  const neighbours = useMemo(() => {
    if (!selectedId) return null
    const ids = new Set([selectedId])
    for (const edge of edges) {
      if (edge.source === selectedId) ids.add(edge.target)
      if (edge.target === selectedId) ids.add(edge.source)
    }
    return ids
  }, [selectedId, edges])

  function toGraphSpace(clientX, clientY) {
    const rect = svgRef.current.getBoundingClientRect()
    const x = ((clientX - rect.left) / rect.width) * WIDTH
    const y = ((clientY - rect.top) / rect.height) * HEIGHT
    return { x: (x - view.x) / view.k, y: (y - view.y) / view.k }
  }

  const handleWheel = useCallback((event) => {
    const rect = svgRef.current.getBoundingClientRect()
    const cx = ((event.clientX - rect.left) / rect.width) * WIDTH
    const cy = ((event.clientY - rect.top) / rect.height) * HEIGHT
    const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12
    setView((current) => {
      const k = Math.max(0.3, Math.min(3, current.k * factor))
      return {
        k,
        x: cx - ((cx - current.x) / current.k) * k,
        y: cy - ((cy - current.y) / current.k) * k,
      }
    })
  }, [])

  // React attaches onWheel passively, so preventDefault() inside it is ignored
  // and the page scrolls while the graph zooms. A native listener is the only
  // way to stop that.
  useEffect(() => {
    const element = svgRef.current
    if (!element) return undefined
    function onWheel(event) {
      event.preventDefault()
      handleWheel(event)
    }
    element.addEventListener('wheel', onWheel, { passive: false })
    return () => element.removeEventListener('wheel', onWheel)
  }, [handleWheel, ready, nodes.length])

  function onNodeMouseDown(event, node) {
    event.stopPropagation()
    const point = toGraphSpace(event.clientX, event.clientY)
    const position = positions.get(node.id)
    dragRef.current = {
      id: node.id,
      moved: false,
      offsetX: point.x - position.x,
      offsetY: point.y - position.y,
    }
    draggingId.current = node.id
  }

  function onMouseMove(event) {
    if (dragRef.current) {
      const point = toGraphSpace(event.clientX, event.clientY)
      const position = positions.get(dragRef.current.id)
      if (position) {
        position.x = point.x - dragRef.current.offsetX
        position.y = point.y - dragRef.current.offsetY
        position.vx = 0
        position.vy = 0
        // The simulation stops driving re-renders once settled, so a drag has
        // to request its own.
        bump()
      }
      dragRef.current.moved = true
      return
    }
    if (panRef.current) {
      const start = panRef.current
      setView({
        ...start.origin,
        x: start.origin.x + (event.clientX - start.startX),
        y: start.origin.y + (event.clientY - start.startY),
      })
    }
  }

  function onMouseUp(event, node) {
    if (dragRef.current) {
      const wasClick = !dragRef.current.moved
      draggingId.current = null
      dragRef.current = null
      if (wasClick && node) setSelectedId((current) => (current === node.id ? null : node.id))
    }
    panRef.current = null
  }

  if (error) {
    return (
      <Page>
        <ErrorMessage title="Could not load the graph" detail={error} onRetry={() => window.location.reload()} />
      </Page>
    )
  }

  const hiddenCount = allNodes.length - nodes.length

  return (
    <Page>
      <PageHeader
        title="Knowledge graph"
        description="How your meetings, people, decisions and action items connect."
        actions={
          <>
            <div className="mc-search w-56">
              <SearchIcon size={16} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Find a node…"
                aria-label="Find a node in the graph"
              />
              {query && (
                <button type="button" onClick={() => setQuery('')} aria-label="Clear search">
                  <CloseIcon size={14} />
                </button>
              )}
            </div>
            {filtersActive && (
              <button type="button" className="mc-btn mc-btn-secondary" onClick={clearFilters}>
                Clear filters
              </button>
            )}
            <button
              type="button"
              className={`mc-btn ${showSettings ? 'mc-btn-primary' : 'mc-btn-secondary'}`}
              onClick={() => setShowSettings((value) => !value)}
              aria-pressed={showSettings}
            >
              <SettingsIcon size={16} /> Settings
            </button>
          </>
        }
      />

      <div className="grid gap-5 lg:grid-cols-[1fr_20rem] items-start">
        <Card padded={false} className="relative overflow-hidden">
          {data === null ? (
            <div className="flex h-[520px] items-center justify-center gap-3" style={{ color: 'var(--text-muted)' }}>
              <Spinner /> <span className="text-sm">Loading graph…</span>
            </div>
          ) : nodes.length === 0 ? (
            <EmptyState
              title={filtersActive ? 'Everything is filtered out' : 'Nothing to show'}
              description={
                filtersActive
                  ? 'No nodes match the current filters.'
                  : 'Meetings need participants, memories or action items before they appear here.'
              }
              action={
                filtersActive ? (
                  <button type="button" className="mc-btn mc-btn-secondary" onClick={clearFilters}>
                    Clear filters
                  </button>
                ) : null
              }
            />
          ) : !ready ? (
            <div className="flex h-[520px] flex-col items-center justify-center gap-3" style={{ color: 'var(--text-muted)' }}>
              <Spinner size={26} />
              <span className="text-sm">Arranging graph…</span>
            </div>
          ) : (
            <svg
              ref={svgRef}
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              className="block w-full touch-none select-none"
              style={{ backgroundColor: 'var(--surface-sunken)', cursor: 'grab' }}
              onMouseDown={(event) => {
                panRef.current = { startX: event.clientX, startY: event.clientY, origin: { ...view } }
              }}
              onMouseMove={onMouseMove}
              onMouseUp={() => onMouseUp()}
              onMouseLeave={() => onMouseUp()}
            >
              <defs>
                <marker
                  id="graph-arrow"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="5"
                  markerHeight="5"
                  orient="auto-start-reverse"
                >
                  <path d="M0 0 L10 5 L0 10 z" fill="var(--border-strong)" />
                </marker>
              </defs>

              <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
                {edges.map((edge, index) => {
                  const a = positions.get(edge.source)
                  const b = positions.get(edge.target)
                  if (!a || !b) return null
                  const dimmed =
                    (neighbours && !(neighbours.has(edge.source) && neighbours.has(edge.target))) ||
                    (matches && !(matches.has(edge.source) && matches.has(edge.target)))
                  return (
                    <line
                      key={index}
                      x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                      stroke="var(--border-strong)"
                      strokeWidth={settings.linkThickness}
                      opacity={dimmed ? 0.08 : 0.5}
                      markerEnd={settings.showArrows ? 'url(#graph-arrow)' : undefined}
                    />
                  )
                })}

                {nodes.map((node) => {
                  const position = positions.get(node.id)
                  if (!position) return null
                  const dimmed =
                    (neighbours && !neighbours.has(node.id)) || (matches && !matches.has(node.id))
                  const isMatch = matches?.has(node.id)
                  const r = radiusFor(node.type, degrees.get(node.id) || 0, settings.nodeSize)
                  const showLabel = view.k > settings.labelThreshold || selectedId === node.id || isMatch

                  return (
                    <g
                      key={node.id}
                      opacity={dimmed ? 0.12 : 1}
                      style={{ cursor: 'pointer' }}
                      onMouseDown={(event) => onNodeMouseDown(event, node)}
                      onMouseUp={(event) => { event.stopPropagation(); onMouseUp(event, node) }}
                    >
                      <circle
                        cx={position.x}
                        cy={position.y}
                        r={r}
                        fill={NODE_COLOURS[node.type] || 'var(--text-faint)'}
                        stroke={selectedId === node.id || isMatch ? 'var(--text-strong)' : 'transparent'}
                        strokeWidth={2}
                      />
                      {showLabel && (
                        <text
                          x={position.x}
                          y={position.y + r + 11}
                          textAnchor="middle"
                          fontSize="9"
                          fill="var(--text-muted)"
                        >
                          {node.label.length > 26 ? `${node.label.slice(0, 26)}…` : node.label}
                        </text>
                      )}
                    </g>
                  )
                })}
              </g>
            </svg>
          )}

          {showSettings && (
            <div
              className="mc-scroll absolute right-3 top-3 z-10 max-h-[calc(100%-1.5rem)] w-64 overflow-y-auto rounded-xl"
              style={{
                backgroundColor: 'var(--surface-panel)',
                border: '1px solid var(--border-default)',
                boxShadow: 'var(--elevation-raised)',
              }}
            >
              <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <span className="text-sm font-semibold">Graph settings</span>
                <button type="button" onClick={() => setShowSettings(false)} aria-label="Close settings">
                  <CloseIcon size={16} />
                </button>
              </div>

              <Section title="Filters">
                <div className="mb-3 flex flex-wrap gap-1.5">
                  {NODE_TYPES.map((type) => (
                    <button
                      key={type}
                      type="button"
                      onClick={() => toggleType(type)}
                      className="mc-badge"
                      style={{
                        opacity: settings.types[type] ? 1 : 0.4,
                        borderColor: settings.types[type] ? NODE_COLOURS[type] : 'var(--border-subtle)',
                      }}
                      aria-pressed={settings.types[type]}
                    >
                      <span
                        className="inline-block h-2 w-2 rounded-full"
                        style={{ backgroundColor: NODE_COLOURS[type] }}
                      />
                      {type.replace('_', ' ')}
                    </button>
                  ))}
                </div>
                <Toggle
                  label="Show unconnected nodes"
                  checked={settings.showOrphans}
                  onChange={(value) => update({ showOrphans: value })}
                />
                <button type="button" className="mc-btn mc-btn-secondary mt-1 w-full" onClick={clearFilters}>
                  Clear filters
                </button>
              </Section>

              <Section title="Display">
                <Slider
                  label="Node size" value={settings.nodeSize} min={0.4} max={2.5} step={0.1}
                  onChange={(value) => update({ nodeSize: value })} format={(v) => `${v.toFixed(1)}×`}
                />
                <Slider
                  label="Link thickness" value={settings.linkThickness} min={0.5} max={4} step={0.5}
                  onChange={(value) => update({ linkThickness: value })} format={(v) => `${v}px`}
                />
                <Slider
                  label="Label visibility" value={settings.labelThreshold} min={0.3} max={3} step={0.05}
                  onChange={(value) => update({ labelThreshold: value })}
                  format={(v) => (v <= 0.3 ? 'always' : `zoom > ${v.toFixed(2)}`)}
                />
                <Toggle
                  label="Show link arrows"
                  checked={settings.showArrows}
                  onChange={(value) => update({ showArrows: value })}
                />
              </Section>

              <Section title="Forces" defaultOpen={false}>
                <Slider
                  label="Repel force" value={settings.repel} min={500} max={9000} step={100}
                  onChange={(value) => update({ repel: value })}
                />
                <Slider
                  label="Link distance" value={settings.linkDistance} min={30} max={220} step={5}
                  onChange={(value) => update({ linkDistance: value })}
                />
                <Slider
                  label="Link force" value={settings.linkForce} min={0.005} max={0.12} step={0.005}
                  onChange={(value) => update({ linkForce: value })} format={(v) => v.toFixed(3)}
                />
                <Slider
                  label="Centre force" value={settings.centerForce} min={0} max={4} step={0.1}
                  onChange={(value) => update({ centerForce: value })} format={(v) => `${v.toFixed(1)}×`}
                />
              </Section>

              <div className="p-4">
                <button
                  type="button"
                  className="mc-btn mc-btn-secondary w-full"
                  onClick={() => {
                    setQuery('')
                    setSettings({ ...DEFAULTS, types: { ...DEFAULTS.types } })
                  }}
                >
                  Restore defaults
                </button>
              </div>
            </div>
          )}

          <div
            className="flex flex-wrap items-center gap-3 px-5 py-3 text-xs"
            style={{ borderTop: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}
          >
            {NODE_TYPES.map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => toggleType(type)}
                className="flex items-center gap-1.5"
                style={{ opacity: settings.types[type] ? 1 : 0.35 }}
                title={settings.types[type] ? `Hide ${type}` : `Show ${type}`}
              >
                <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: NODE_COLOURS[type] }} />
                {type.replace('_', ' ')}
              </button>
            ))}
            <span className="ml-auto" style={{ color: 'var(--text-faint)' }}>
              {nodes.length} nodes · {edges.length} links
              {hiddenCount > 0 ? ` · ${hiddenCount} hidden` : ''}
            </span>
          </div>
        </Card>

        <Card padded={false} className="lg:sticky lg:top-24">
          <NodeDetail node={selected} nodes={allNodes} edges={allEdges} />
        </Card>
      </div>
    </Page>
  )
}
