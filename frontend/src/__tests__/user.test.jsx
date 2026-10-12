import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { UserContext, useIsOwner, useUser } from '../user'

describe('user context', () => {
  it('reports owner only for the owner role', () => {
    const wrap = (user) => ({ children }) => <UserContext.Provider value={user}>{children}</UserContext.Provider>
    expect(renderHook(() => useIsOwner(), { wrapper: wrap({ role: 'owner' }) }).result.current).toBe(true)
    expect(renderHook(() => useIsOwner(), { wrapper: wrap({ role: 'member' }) }).result.current).toBe(false)
    expect(renderHook(() => useIsOwner(), { wrapper: wrap(null) }).result.current).toBe(false)
    expect(renderHook(() => useUser(), { wrapper: wrap({ role: 'member', email: 'x' }) }).result.current.email).toBe('x')
  })
})
