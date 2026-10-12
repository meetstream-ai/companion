import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../api', () => ({
  activateAgent: vi.fn(),
  createAgent: vi.fn(),
  deleteAgent: vi.fn(),
  setAgentMode: vi.fn(),
  getAgent: vi.fn(),
  getAgentCredentials: vi.fn(),
  getAgentTemplate: vi.fn(),
  listAgents: vi.fn(),
  listImportableAgents: vi.fn(),
  updateAgent: vi.fn(),
  updateAgentTemplate: vi.fn(),
  setMeetstreamApiKey: vi.fn(),
}))
import { getAgent, getAgentCredentials, getAgentTemplate, listAgents, setAgentMode } from '../api'
import Agent from '../pages/Agent'
import { UserContext } from '../user'

const config = { AgentConfigID: 'ag-1', AgentName: 'Ada', Mode: 'realtime', InteractionMode: 'voice', Model: { provider: 'openai', model: 'gpt-4.1' }, Agent: { response_modality: 'audio' } }

function renderAs(user) {
  return render(
    <MemoryRouter>
      <UserContext.Provider value={user}>
        <Agent />
      </UserContext.Provider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  listAgents.mockResolvedValue({ agent_configs: [{ ...config, IsActive: true }] })
  getAgent.mockResolvedValue(config)
  getAgentCredentials.mockResolvedValue(null)
  getAgentTemplate.mockResolvedValue({ provider: 'openai' })
})

describe('how the agent answers in a call', () => {
  it('offers voice and chat, voice selected, and a change is saved then re-read', async () => {
    setAgentMode.mockResolvedValue({ agent_config_id: 'ag-1', mode: 'chat', response_modality: 'chat' })
    renderAs({ id: 'u1', role: 'owner', permissions: { manage_agents: true } })
    const voice = await screen.findByRole('radio', { name: /^Voice Answers out loud/ })
    expect(voice).toHaveAttribute('aria-checked', 'true')
    expect(screen.queryByRole('radio', { name: /both/i })).toBeNull()
    // There is no typed-question mode, and the page says so.
    expect(screen.getByText(/typed into the chat cannot be read/)).toBeInTheDocument()
    // The raw modality select belongs to the template, not an agent.
    expect(screen.queryByLabelText('Response modality')).toBeNull()

    getAgent.mockResolvedValue({ ...config, InteractionMode: 'chat', Agent: { response_modality: 'chat' } })
    fireEvent.click(screen.getByRole('radio', { name: /^Chat Stays silent/ }))
    await waitFor(() => expect(setAgentMode).toHaveBeenCalledWith('ag-1', 'chat'))
    await waitFor(() => expect(screen.getByRole('radio', { name: /^Chat Stays silent/ })).toHaveAttribute('aria-checked', 'true'))
    expect(screen.getByText(/appears in the meeting chat instead/)).toBeInTheDocument()
  })

  it('a member without manage_agents can see the mode but not change it', async () => {
    renderAs({ id: 'u2', role: 'member', permissions: { manage_agents: false } })
    const voice = await screen.findByRole('radio', { name: /^Voice Answers out loud/ })
    expect(voice).toBeDisabled()
    fireEvent.click(screen.getByRole('radio', { name: /^Chat Stays silent/ }))
    expect(setAgentMode).not.toHaveBeenCalled()
  })
})
