/**
 * A join code carried across a database switch.
 *
 * Joining a workspace on another database means creating an account there
 * first - the code was typed in the picker, and re-typing it on the
 * sign-in screen would be the app forgetting something it was just told.
 * Session storage, so it does not outlive the window.
 */
export const PENDING_JOIN_KEY = 'meet-companion:pending-join'

export function takePendingJoin() {
  try {
    const code = window.sessionStorage.getItem(PENDING_JOIN_KEY)
    if (code) window.sessionStorage.removeItem(PENDING_JOIN_KEY)
    return code || ''
  } catch {
    return ''
  }
}
