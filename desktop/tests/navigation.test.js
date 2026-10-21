// node --test desktop/tests
const assert = require('node:assert/strict')
const test = require('node:test')

const { isAppUrl, isSafeExternal } = require('../navigation')

const APP = 'http://127.0.0.1:5123'

test('only the app origin itself counts as the app', () => {
  assert.equal(isAppUrl('http://127.0.0.1:5123/meetings', APP), true)
  assert.equal(isAppUrl('http://127.0.0.1:5123', APP), true)
  // A prefix match accepted these.
  assert.equal(isAppUrl('http://127.0.0.1:5123.attacker.tld/', APP), false)
  assert.equal(isAppUrl('http://127.0.0.1:51234/', APP), false)
  assert.equal(isAppUrl('http://127.0.0.1:5123@attacker.tld/', APP), false)
  assert.equal(isAppUrl('https://127.0.0.1:5123/', APP), false)
  assert.equal(isAppUrl('not a url', APP), false)
})

test('only web and mail links are opened outside the app', () => {
  assert.equal(isSafeExternal('https://example.com/x'), true)
  assert.equal(isSafeExternal('http://example.com/x'), true)
  assert.equal(isSafeExternal('mailto:someone@example.com'), true)
  assert.equal(isSafeExternal('file:///etc/passwd'), false)
  assert.equal(isSafeExternal('javascript:alert(1)'), false)
  assert.equal(isSafeExternal('smb://host/share'), false)
  assert.equal(isSafeExternal('nonsense'), false)
})
