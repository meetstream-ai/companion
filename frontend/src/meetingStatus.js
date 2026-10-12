/**
 * A meeting's `status` as the server records it, for display. The server
 * moves a launched bot through joining → in_meeting → recording → stopped →
 * completed (or failed), from MeetStream's webhooks or by asking MeetStream.
 */

// The bot is, or may still be, in the call.
export const LIVE_STATUSES = ['joining', 'in_meeting', 'recording']
// Stop bot only makes sense once there is a bot to stop.
export const STOPPABLE_STATUSES = LIVE_STATUSES

const LABELS = {
  pending: 'Not started',
  joining: 'Joining',
  in_meeting: 'In the call',
  recording: 'Recording',
  stopped: 'Left the call',
  completed: 'Completed',
  done: 'Completed',
  failed: 'Failed',
  error: 'Failed',
}

export function statusLabel(status) {
  if (!status) return ''
  return LABELS[status] || String(status).replace(/_/g, ' ')
}

export function statusTone(status) {
  if (['completed', 'done'].includes(status)) return 'success'
  if (['failed', 'error'].includes(status)) return 'danger'
  if (['pending', 'stopped', ...LIVE_STATUSES].includes(status)) return 'warning'
  return 'neutral'
}

export function isLiveMeeting(meeting) {
  return LIVE_STATUSES.includes(meeting?.status) && Boolean(meeting?.meetstream_bot_id)
}
