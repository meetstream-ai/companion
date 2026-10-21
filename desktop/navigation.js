// Which URLs the app window may show, and which may leave for the system
// browser. Kept apart from main.js so it can be tested without Electron.

/** Whether url is a page of the app itself (same scheme, host and port). */
function isAppUrl(url, appOrigin) {
  try {
    return new URL(url).origin === new URL(appOrigin).origin
  } catch {
    return false
  }
}

// Anything else (file:, javascript:, custom protocol handlers) could run or
// open something on this machine.
const EXTERNAL_PROTOCOLS = new Set(['https:', 'http:', 'mailto:'])

/** Whether url is safe to hand to the operating system to open. */
function isSafeExternal(url) {
  try {
    return EXTERNAL_PROTOCOLS.has(new URL(url).protocol)
  } catch {
    return false
  }
}

module.exports = { isAppUrl, isSafeExternal }
