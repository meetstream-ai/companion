import { LogoMark } from './Logo'

/**
 * Fullscreen transition screen shown when switching between workspaces or
 * databases, so the app doesn't feel frozen during API activation and page reload.
 */
export default function WorkspaceSwitchOverlay({
  name,
  action = 'Switching workspace…',
  subtitle = 'Setting up your meetings, notes, and AI workspace…',
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={action}
      className="fixed inset-0 z-[100] flex flex-col items-center justify-center p-6 select-none animate-in fade-in duration-200"
      style={{
        backgroundColor: 'var(--surface-page)',
        backgroundImage:
          'radial-gradient(circle at 50% 45%, color-mix(in srgb, var(--brand-ring) 14%, var(--surface-page)) 0%, var(--surface-page) 75%)',
      }}
    >
      <div
        className="mc-panel relative flex flex-col items-center max-w-sm w-full mx-4 px-8 py-10 rounded-2xl text-center"
        style={{
          boxShadow: 'var(--elevation-raised)',
        }}
      >
        {/* Animated Brand Mark Container */}
        <div className="relative mb-6 flex items-center justify-center">
          <div
            className="absolute inset-0 rounded-2xl opacity-25 animate-ping pointer-events-none"
            style={{
              backgroundColor: 'var(--brand-ring)',
              animationDuration: '3s',
            }}
          />
          <div
            className="relative flex items-center justify-center w-20 h-20 rounded-2xl border"
            style={{
              backgroundColor: 'var(--surface-raised)',
              borderColor: 'var(--border-subtle)',
              boxShadow: '0 4px 12px rgba(0, 0, 0, 0.06)',
            }}
          >
            <LogoMark size={42} className="drop-shadow-sm" />
          </div>
        </div>

        {/* Action Title */}
        <h2
          className="text-xl font-semibold tracking-tight"
          style={{ color: 'var(--text-strong)' }}
        >
          {action}
        </h2>

        {/* Workspace Target Tag */}
        {name && (
          <div
            className="mt-3 inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full text-xs font-medium border"
            style={{
              backgroundColor: 'var(--brand-soft)',
              color: 'var(--brand-soft-text)',
              borderColor: 'var(--border-subtle)',
            }}
          >
            <span
              className="w-2 h-2 rounded-full animate-pulse"
              style={{ backgroundColor: 'var(--brand-solid)' }}
            />
            <span className="truncate max-w-[220px] font-semibold">{name}</span>
          </div>
        )}

        {/* Subtitle */}
        <p
          className="mt-3.5 text-xs leading-relaxed max-w-xs"
          style={{ color: 'var(--text-muted)' }}
        >
          {subtitle}
        </p>

        {/* Indeterminate Progress Bar */}
        <div
          className="w-52 h-1.5 mt-8 rounded-full overflow-hidden relative"
          style={{ backgroundColor: 'var(--surface-sunken)' }}
        >
          <div
            className="h-full rounded-full mc-progress-bar-indeterminate"
            style={{
              background: 'linear-gradient(90deg, var(--brand-ring), var(--brand-solid))',
            }}
          />
        </div>
      </div>
    </div>
  )
}
