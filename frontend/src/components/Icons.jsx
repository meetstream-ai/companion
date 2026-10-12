/**
 * Interface icons.
 *
 * Deliberately plain line icons: the brand mark is the only piece of identity
 * in the product, and feature areas use neutral iconography so nothing
 * competes with it.
 */

const base = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
}

function Icon({ children, size = 18, ...rest }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true" {...base} {...rest}>
      {children}
    </svg>
  )
}

export const DashboardIcon = (p) => (
  <Icon {...p}>
    <rect x="3" y="3" width="7.5" height="8.5" rx="2" />
    <rect x="13.5" y="3" width="7.5" height="5" rx="2" />
    <rect x="3" y="15" width="7.5" height="6" rx="2" />
    <rect x="13.5" y="11" width="7.5" height="10" rx="2" />
  </Icon>
)

export const MeetingsIcon = (p) => (
  <Icon {...p}>
    <rect x="2.5" y="6" width="13" height="12" rx="3" />
    <path d="M15.5 11l5-2.6v7.2l-5-2.6z" />
  </Icon>
)

export const NotebookIcon = (p) => (
  <Icon {...p}>
    <path d="M6 3h11a2 2 0 012 2v14a2 2 0 01-2 2H6z" />
    <path d="M6 3a2 2 0 00-2 2v14a2 2 0 002 2" />
    <path d="M9 8h6M9 12h6M9 16h4" />
  </Icon>
)

export const AskAiIcon = (p) => (
  <Icon {...p}>
    <path d="M21 11.5a8 8 0 01-8.5 8 8.6 8.6 0 01-3.7-.8L4 20l1.4-4.2A8 8 0 1121 11.5z" />
    <path d="M12 8.5v.01M12 11v3" />
  </Icon>
)

export const SettingsIcon = (p) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.9-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1A1.7 1.7 0 008.5 19a1.7 1.7 0 00-1.9.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.9 1.7 1.7 0 00-1.5-1H2a2 2 0 110-4h.1A1.7 1.7 0 004 8.5a1.7 1.7 0 00-.3-1.9l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.9.3H8.5a1.7 1.7 0 001-1.5V2a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.9-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.9v.1a1.7 1.7 0 001.5 1H22a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" />
  </Icon>
)

export const MembersIcon = (p) => (
  <Icon {...p}>
    <circle cx="9" cy="8" r="3.2" />
    <path d="M3 20a6 6 0 0112 0" />
    <path d="M16.5 5.3a3.2 3.2 0 010 5.9M17.5 14.2A6 6 0 0121 20" />
  </Icon>
)

export const SearchIcon = (p) => (
  <Icon {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="M16.5 16.5L21 21" />
  </Icon>
)

export const PlusIcon = (p) => (
  <Icon {...p}>
    <path d="M12 5v14M5 12h14" />
  </Icon>
)

export const FolderIcon = (p) => (
  <Icon {...p}>
    <path d="M3 7a2 2 0 012-2h3.6a2 2 0 011.5.7L11.5 7H19a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
  </Icon>
)

export const FolderOpenIcon = (p) => (
  <Icon {...p}>
    <path d="M3 7a2 2 0 012-2h3.6a2 2 0 011.5.7L11.5 7H19a2 2 0 012 2v1H3z" />
    <path d="M3 10h18l-1.8 8.2a2 2 0 01-2 1.8H6.8a2 2 0 01-2-1.8z" />
  </Icon>
)

export const NoteIcon = (p) => (
  <Icon {...p}>
    <path d="M6 3h8l5 5v13a1 1 0 01-1 1H6a1 1 0 01-1-1V4a1 1 0 011-1z" />
    <path d="M14 3v5h5" />
  </Icon>
)

export const StarIcon = ({ filled = false, ...p }) => (
  <Icon {...p} fill={filled ? 'currentColor' : 'none'}>
    <path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" />
  </Icon>
)

export const TrashIcon = (p) => (
  <Icon {...p}>
    <path d="M4 7h16M10 11v6M14 11v6" />
    <path d="M6 7l1 12a2 2 0 002 2h6a2 2 0 002-2l1-12" />
    <path d="M9 7V5a2 2 0 012-2h2a2 2 0 012 2v2" />
  </Icon>
)

export const ChevronRightIcon = (p) => (
  <Icon {...p}>
    <path d="M9 5l7 7-7 7" />
  </Icon>
)

export const ChevronDownIcon = (p) => (
  <Icon {...p}>
    <path d="M5 9l7 7 7-7" />
  </Icon>
)

export const CheckIcon = (p) => (
  <Icon {...p}>
    <path d="M4 12.5l5 5L20 6.5" />
  </Icon>
)

export const CloseIcon = (p) => (
  <Icon {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Icon>
)

export const SunIcon = (p) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </Icon>
)

export const MoonIcon = (p) => (
  <Icon {...p}>
    <path d="M20 14.5A8.5 8.5 0 019.5 4a8.5 8.5 0 1010.5 10.5z" />
  </Icon>
)

export const SidebarIcon = (p) => (
  <Icon {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M9.5 4v16" />
  </Icon>
)

export const InboxIcon = (p) => (
  <Icon {...p}>
    <path d="M3 13h5l1.5 3h5L16 13h5" />
    <path d="M4.4 6.6L3 13v5a2 2 0 002 2h14a2 2 0 002-2v-5l-1.4-6.4a2 2 0 00-2-1.6H6.4a2 2 0 00-2 1.6z" />
  </Icon>
)

export const AlertIcon = (p) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7.5v5M12 16v.01" />
  </Icon>
)

export const ChevronLeftIcon = (p) => (
  <Icon {...p}>
    <path d="M15 5l-7 7 7 7" />
  </Icon>
)

export const RobotIcon = (p) => (
  <Icon {...p}>
    <rect x="4" y="7.5" width="16" height="12" rx="4" />
    <path d="M12 3v4.5M9 12.5v1.5M15 12.5v1.5" />
    <path d="M2 13v2M22 13v2" />
  </Icon>
)

export const GraphIcon = (p) => (
  <Icon {...p}>
    <circle cx="6" cy="7" r="2.5" />
    <circle cx="18" cy="6" r="2.5" />
    <circle cx="12" cy="17.5" r="2.5" />
    <path d="M8.2 8.4l2.6 6.9M16.2 8.2l-2.7 7.1M8.4 6.6l7.2-.4" />
  </Icon>
)

export const DownloadIcon = (p) => (
  <Icon {...p}>
    <path d="M12 3v12" />
    <path d="M7 11l5 5 5-5" />
    <path d="M4 20h16" />
  </Icon>
)

export const PencilIcon = (p) => (
  <Icon {...p}>
    <path d="M4 20h4l10.5-10.5a2.1 2.1 0 00-3-3L5 17v3z" />
    <path d="M13.5 6.5l3 3" />
  </Icon>
)
