import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { login, getMeeting } from '../api'

function reply(status, body) {
  return Promise.resolve({
    status,
    ok: status < 400,
    statusText: 'x',
    text: () => Promise.resolve(typeof body === 'string' ? body : JSON.stringify(body)),
    json: () => Promise.resolve(body),
  })
}

describe('api error mapping', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('surfaces the server message for a wrong password instead of "session expired"', async () => {
    fetch.mockReturnValue(reply(401, { detail: 'Incorrect email or password.' }))
    await expect(login('a@b.c', 'nope')).rejects.toThrow('Incorrect email or password.')
  })

  it('treats a 401 elsewhere as a lost session and tells the app', async () => {
    const heard = vi.fn()
    window.addEventListener('hub:unauthorized', heard)
    fetch.mockReturnValue(reply(401, { detail: 'Sign in required.' }))
    await expect(getMeeting('m1')).rejects.toThrow(/session has expired/)
    expect(heard).toHaveBeenCalled()
  })

  it('unwraps FastAPI validation errors and nested provider errors', async () => {
    fetch.mockReturnValueOnce(reply(422, { detail: [{ loc: ['body', 'question'], msg: 'String should have at most 4000 characters' }] }))
    await expect(getMeeting('m1')).rejects.toThrow('question: String should have at most 4000 characters')
    fetch.mockReturnValueOnce(reply(502, { detail: 'Provider failed: {"error": {"message": "model not found"}}' }))
    await expect(getMeeting('m1')).rejects.toThrow('Provider failed: model not found')
  })
})
