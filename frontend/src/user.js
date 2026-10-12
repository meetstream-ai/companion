import { createContext, useContext } from 'react'

/**
 * The signed-in member, as returned by /api/auth/check.
 *
 * Only used for presentation - hiding owner-only controls from members who
 * cannot use them. Every check is enforced again by the server.
 */
export const UserContext = createContext(null)

export function useUser() {
  return useContext(UserContext)
}

export function useIsOwner() {
  return useUser()?.role === 'owner'
}

/**
 * Whether the signed-in member may do this in their workspace (see
 * app/permissions.py for the keys). Owners always may. Presentation only -
 * the server decides for real.
 */
export function useCan(permission) {
  const user = useUser()
  if (!user) return false
  if (user.role === 'owner') return true
  return Boolean(user.permissions?.[permission])
}
