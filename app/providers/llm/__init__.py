"""
LLM provider registry.

Adding support for a new service means writing one adapter and registering it
here; nothing in the application layer changes. The descriptor metadata also
drives the onboarding and settings forms, so each provider declares exactly
which configuration fields are relevant to it and no others are shown.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Type

from app.providers.llm.anthropic import AnthropicProvider
from app.providers.llm.base import (
    ChatMessage,
    LLMConfig,
    LLMConfigError,
    LLMError,
    LLMProvider,
    ProviderStatus,
)
from app.providers.llm.gemini import GeminiProvider
from app.providers.llm.ollama import OllamaProvider
from app.providers.llm.openai_compatible import (
    GroqProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    XAIProvider,
)

__all__ = [
    "ChatMessage",
    "LLMConfig",
    "LLMConfigError",
    "LLMError",
    "LLMProvider",
    "ProviderStatus",
    "create_llm_provider",
    "describe_providers",
    "list_provider_names",
]

PROVIDERS: Dict[str, Type[LLMProvider]] = {
    provider.name: provider
    for provider in (
        OpenAIProvider,
        AnthropicProvider,
        GeminiProvider,
        OllamaProvider,
        GroqProvider,
        XAIProvider,
        OpenAICompatibleProvider,
    )
}


@dataclass(slots=True)
class ProviderField:
    key: str
    label: str
    type: str = "text"
    required: bool = False
    placeholder: str = ""
    help: str = ""
    default: Any = None
    # Hidden behind an "Advanced" disclosure in the forms: most people only
    # need an API key and a model, and a stray host from another provider is
    # the most common way to end up with a confusing 404.
    advanced: bool = False


@dataclass(slots=True)
class ProviderDescriptor:
    name: str
    label: str
    summary: str
    local: bool = False
    fields: List[ProviderField] = field(default_factory=list)
    suggested_models: List[str] = field(default_factory=list)


def _model_field(placeholder: str, default: str) -> ProviderField:
    return ProviderField(
        key="model",
        label="Model",
        type="text",
        required=True,
        placeholder=placeholder,
        default=default,
    )


def _api_key_field(label: str, help_text: str) -> ProviderField:
    return ProviderField(
        key="api_key",
        label=label,
        type="password",
        required=True,
        help=help_text,
    )


def _base_url_field(placeholder: str, required: bool = False) -> ProviderField:
    return ProviderField(
        key="base_url",
        label="Base URL",
        type="url",
        required=required,
        placeholder=placeholder,
        help="Override only if you route through a proxy or gateway."
        if not required
        else "",
        advanced=not required,
    )


_TEMPERATURE_FIELD = ProviderField(
    key="temperature",
    label="Temperature",
    type="number",
    default=0.2,
    help="Lower values produce more consistent extraction results.",
    advanced=True,
)


DESCRIPTORS: Dict[str, ProviderDescriptor] = {
    "openai": ProviderDescriptor(
        name="openai",
        label="OpenAI",
        summary="GPT models via the OpenAI API.",
        fields=[
            _api_key_field("API key", "Created at platform.openai.com."),
            _model_field("gpt-4.1-mini", "gpt-4.1-mini"),
            _base_url_field("https://api.openai.com/v1"),
            _TEMPERATURE_FIELD,
        ],
        suggested_models=["gpt-4.1-mini", "gpt-4.1", "gpt-4.1-nano", "gpt-4o-mini", "gpt-4o"],
    ),
    "anthropic": ProviderDescriptor(
        name="anthropic",
        label="Anthropic",
        summary="Claude models via the Anthropic API.",
        fields=[
            _api_key_field("API key", "Created at console.anthropic.com."),
            _model_field("claude-sonnet-4-5", "claude-sonnet-4-5"),
            _base_url_field("https://api.anthropic.com"),
            _TEMPERATURE_FIELD,
        ],
        suggested_models=["claude-sonnet-4-5", "claude-haiku-4-5", "claude-opus-4-1"],
    ),
    "gemini": ProviderDescriptor(
        name="gemini",
        label="Google Gemini",
        summary="Gemini models via Google AI Studio.",
        fields=[
            _api_key_field("API key", "Created at aistudio.google.com."),
            _model_field("gemini-2.5-flash", "gemini-2.5-flash"),
            _base_url_field("https://generativelanguage.googleapis.com"),
            _TEMPERATURE_FIELD,
        ],
        suggested_models=["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"],
    ),
    "ollama": ProviderDescriptor(
        name="ollama",
        label="Ollama (local)",
        summary="Runs models on this computer. Ollama is a separate install from ollama.com; no API key, nothing leaves your machine.",
        local=True,
        fields=[
            ProviderField(
                key="base_url",
                label="Host",
                type="url",
                required=True,
                placeholder="http://localhost:11434",
                default="http://localhost:11434",
                help="Where Ollama is listening. Leave as is unless you changed its port or run it on another machine.",
            ),
            _model_field("llama3.1", "llama3.1"),
            _TEMPERATURE_FIELD,
        ],
        suggested_models=["llama3.1", "llama3.2", "qwen2.5", "mistral", "gemma3"],
    ),
    "groq": ProviderDescriptor(
        name="groq",
        label="Groq",
        summary="Fast inference for open models.",
        fields=[
            _api_key_field("API key", "Created at console.groq.com."),
            _model_field("openai/gpt-oss-120b", "openai/gpt-oss-120b"),
            _base_url_field("https://api.groq.com/openai/v1"),
            _TEMPERATURE_FIELD,
        ],
        suggested_models=["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b", "groq/compound"],
    ),
    "xai": ProviderDescriptor(
        name="xai",
        label="xAI (Grok)",
        summary="Grok models from xAI. (Different company from Groq.)",
        fields=[
            _api_key_field("API key", "Created at console.x.ai."),
            _model_field("grok-3-mini", "grok-3-mini"),
            _base_url_field("https://api.x.ai/v1"),
            _TEMPERATURE_FIELD,
        ],
        suggested_models=["grok-4", "grok-3", "grok-3-mini", "grok-2-1212"],
    ),
    "openai_compatible": ProviderDescriptor(
        name="openai_compatible",
        label="OpenAI-compatible API",
        summary="Any endpoint speaking the OpenAI format — vLLM, LM Studio, OpenRouter, together.ai.",
        fields=[
            _base_url_field("http://localhost:8000/v1", required=True),
            _model_field("your-model-name", ""),
            ProviderField(
                key="api_key",
                label="API key",
                type="password",
                help="Leave blank if your endpoint does not require authentication.",
            ),
            _TEMPERATURE_FIELD,
        ],
    ),
}


def list_provider_names() -> List[str]:
    return list(DESCRIPTORS.keys())


def describe_providers() -> List[Dict[str, Any]]:
    """Serializable provider metadata for the onboarding and settings forms."""
    return [asdict(DESCRIPTORS[name]) for name in DESCRIPTORS]


def create_llm_provider(config: LLMConfig) -> LLMProvider:
    """Instantiate the adapter for `config.provider`."""
    provider_cls = PROVIDERS.get(config.provider)
    if provider_cls is None:
        supported = ", ".join(sorted(PROVIDERS))
        raise LLMConfigError(
            f"Unknown LLM provider '{config.provider}'. Supported providers: {supported}."
        )
    return provider_cls(config)


def default_config_for(provider_name: str) -> Optional[LLMConfig]:
    """A starting configuration with the provider's documented defaults filled in."""
    descriptor = DESCRIPTORS.get(provider_name)
    if descriptor is None:
        return None

    values: Dict[str, Any] = {f.key: f.default for f in descriptor.fields if f.default is not None}
    provider_cls = PROVIDERS[provider_name]
    return LLMConfig(
        provider=provider_name,
        model=values.get("model", ""),
        base_url=values.get("base_url") or provider_cls.default_base_url,
        temperature=values.get("temperature", 0.2),
    )
