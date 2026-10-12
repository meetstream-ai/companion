/**
 * The Meet Companion brand mark: a video camera combined with a brain,
 * meaning meetings + intelligence.
 *
 * One component for the whole product. Feature areas use ordinary UI icons and
 * never get marks of their own, so the identity stays singular.
 *
 * The artwork is the approved mark from assets/branding, served from
 * public/logo-icon.png with a transparent background so it sits correctly on
 * both light and dark surfaces. It is never recoloured, stretched or rotated.
 *
 * Variants:
 *   icon - the mark alone, for collapsed navigation and tight spaces
 *   full - mark plus the "Meet Companion" wordmark
 */

export function LogoMark({ size = 32, className = '' }) {
  return (
    <img
      src="/logo-icon.png"
      width={size}
      height={size}
      className={className}
      alt="Meet Companion"
      // Keeps the mark's proportions no matter what box it is given.
      style={{ width: size, height: size, objectFit: 'contain', display: 'block' }}
      draggable="false"
    />
  )
}

export default function Logo({ variant = 'full', size = 32, showTagline = false, className = '' }) {
  if (variant === 'icon') {
    return <LogoMark size={size} className={className} />
  }

  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <LogoMark size={size} />
      <div className="leading-tight">
        <div
          className="font-semibold tracking-tight"
          style={{ color: 'var(--text-strong)', fontSize: size * 0.5 }}
        >
          Meet Companion
        </div>
        {showTagline && (
          <div
            className="uppercase tracking-[0.18em]"
            style={{ color: 'var(--text-faint)', fontSize: Math.max(9, size * 0.22) }}
          >
            Make meeting data smarter.
          </div>
        )}
      </div>
    </div>
  )
}
