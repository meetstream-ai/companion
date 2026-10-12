"""
Provider abstractions for pluggable infrastructure.

Meet Companion does not bind application logic to any single vendor. Each
external capability (LLM inference, vector storage, meeting bots) is expressed
as an interface here, with concrete adapters underneath, so a user can bring
their own infrastructure without the rest of the codebase changing.
"""
