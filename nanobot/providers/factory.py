"""Factory for instantiating LLM providers from configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from nanobot.config.schema import Config
from nanobot.providers.base import GenerationSettings, LLMClient
from nanobot.providers.registry import find_by_name

if TYPE_CHECKING:
    from nanobot.agent.runner import AgentRunner


class AgentRegistry:
    """Registry for caching and managing LLM providers and runners."""

    def __init__(self, config: Config):
        self.config = config
        self._providers: dict[str, LLMClient] = {}
        self._runners: dict[str, AgentRunner] = {}

    def get_provider(self, agent_name: str) -> LLMClient:
        """Get a cached LLMClient for the specified agent profile."""
        if agent_name not in self._providers:
            logger.debug(f"Building provider for agent '{agent_name}'")
            self._providers[agent_name] = build_provider(self.config, agent_name)
        return self._providers[agent_name]

    def get_runner(self, agent_name: str) -> AgentRunner:
        """Get a cached AgentRunner for the specified agent profile."""
        if agent_name not in self._runners:
            # Lazy import to break circular dependency:
            # factory -> agent.runner -> agent.loop -> agent.subagent -> factory
            from nanobot.agent.runner import AgentRunner

            provider = self.get_provider(agent_name)
            logger.debug(f"Building runner for agent '{agent_name}'")
            self._runners[agent_name] = AgentRunner(provider)
        return self._runners[agent_name]


# Module-level cache for backward compatibility and simple usage
_GLOBAL_REGISTRY: dict[int, AgentRegistry] = {}


def get_runner(config: Config, agent_name: str = "defaults") -> AgentRunner:
    """Get a cached AgentRunner for the specified agent profile (backward compat)."""
    # Use config id to ensure different configs get different registries
    cfg_id = id(config)
    if cfg_id not in _GLOBAL_REGISTRY:
        _GLOBAL_REGISTRY[cfg_id] = AgentRegistry(config)
    return _GLOBAL_REGISTRY[cfg_id].get_runner(agent_name)


def build_provider(config: Config, agent_name: str = "defaults") -> LLMClient:
    """Create the appropriate LLM provider from config.

    Two modes:

    **Single provider** — ``fallback_models`` is empty.  Uses ``model`` and
    ``provider`` directly.  If ``model`` is a key in the top-level ``models``
    dict the corresponding ``ModelConfig`` entry is used instead (same path as
    fallback chain, single slot).

    **Fallback chain** — ``fallback_models`` is a non-empty ordered list of
    keys into the top-level ``models`` dict.  Wraps the resulting providers in
    a ``FallbackClient`` that advances to the next slot on quota/429 errors.

    Provider resolution cascade (per slot):
      1. ``ModelConfig.provider`` if explicitly set (not ``"auto"``).
      2. ``AgentDefaults.provider`` if explicitly set — acts as a routing
         *gateway* policy that applies to every slot whose ``ModelConfig``
         leaves provider as ``"auto"`` (e.g. route everything through OpenRouter).
      3. Keyword / prefix auto-detection against the model string.

    Model string prefix handling:
      Model names are stored with their routing prefix (``"anthropic/claude-opus-4"``).
      Each provider backend handles stripping independently:
      - Direct providers (Anthropic, Gemini) always strip the prefix before the
        wire call because their APIs only accept bare names.
      - OpenAI-compat providers strip only when ``spec.strip_model_prefix=True``
        (e.g. AiHubMix); gateways like OpenRouter keep the full string because
        the prefix is how they route to the correct upstream.
    """
    try:
        agent_config = config.agents.get_agent(agent_name)
    except ValueError as e:
        raise ValueError(f"Failed to load agent '{agent_name}': {e}") from e

    model_str = agent_config.model
    fallback_keys = agent_config.fallback_models

    # If the model is a key in the models dict, treat it as a single-entry fallback
    # to ensure resolution and model-specific settings are applied.
    if not fallback_keys and model_str in config.models:
        fallback_keys = [model_str]

    if not fallback_keys:
        # Legacy path — no fallback chain and not a known model key.
        return _build_single_provider(config, agent_name, model_str, agent_config.provider)

    # Validate all keys exist in config.models.
    unknown = [k for k in fallback_keys if k not in config.models]
    if unknown:
        raise ValueError(
            f"fallback_models references unknown model key(s): {', '.join(unknown)}\n"
            f"Each entry must be a key in the top-level 'models' dict."
        )

    # Build one provider per slot.
    slots: list[tuple[LLMClient, str, str, str]] = []
    for key in fallback_keys:
        mc = config.models[key]
        slot_provider = _build_single_provider(config, agent_name, mc.model, mc.provider)

        explicit_agent_fields = agent_config.model_fields_set

        # Agent config takes precedence over model config only if explicitly specified
        temp = (
            agent_config.temperature
            if "temperature" in explicit_agent_fields
            else (mc.temperature if mc.temperature is not None else agent_config.temperature)
        )
        max_tok = (
            agent_config.max_tokens
            if "max_tokens" in explicit_agent_fields
            else (mc.max_tokens if mc.max_tokens is not None else agent_config.max_tokens)
        )
        reason = (
            agent_config.reasoning_effort
            if "reasoning_effort" in explicit_agent_fields
            else (
                mc.reasoning_effort
                if mc.reasoning_effort is not None
                else agent_config.reasoning_effort
            )
        )

        # Apply per-model overrides to GenerationSettings.
        slot_provider.generation = GenerationSettings(
            temperature=temp,
            max_tokens=max_tok,
            reasoning_effort=reason,
            context_max=mc.context_max,
        )

        # Apply prefill override if the provider supports it.
        if mc.prefill is not None and hasattr(slot_provider, "prefill"):
            slot_provider.prefill = mc.prefill

        # Determine the provider name for this slot to get its reset timezone.
        # Pass mc.provider so the lookup uses the slot's own provider, not the
        # agent-level provider field (which may differ for multi-provider chains).
        slot_provider_name = config.get_provider_name(
            mc.model, agent_name=agent_name, provider_override=mc.provider
        )
        slot_reset_timezone = (
            getattr(config.providers, slot_provider_name).quota_reset_timezone
            if slot_provider_name
            else "UTC"
        )

        slots.append((slot_provider, mc.model, key, slot_reset_timezone))

    if len(slots) == 1:
        # Single-entry chain — no wrapper needed.
        return slots[0][0]

    from nanobot.providers.fallback import FallbackClient

    return FallbackClient(slots)


def _build_single_provider(
    config: Config, agent_name: str, model: str, provider_override: str = "auto"
) -> LLMClient:
    """Instantiate a single LLM provider for *model* using *config*."""
    agent_config = config.agents.get_agent(agent_name)

    provider_name = config.get_provider_name(
        model, agent_name=agent_name, provider_override=provider_override
    )
    p = config.get_provider(model, agent_name=agent_name, provider_override=provider_override)
    spec = find_by_name(provider_name) if provider_name else None
    backend = spec.backend if spec else "openai_compat"
    logger.debug(
        f"Building provider for agent '{agent_name}': model='{model}', provider='{provider_name}', backend='{backend}'"
    )

    # --- validation ---
    if backend == "azure_openai":
        if not p or not p.api_key or not p.api_base:
            raise ValueError(
                "Azure OpenAI requires api_key and api_base.\n"
                "Set them in config.json under providers.azure_openai section.\n"
                "Use the model field to specify the deployment name."
            )
    elif backend == "openai_compat" and not model.startswith("bedrock/"):
        needs_key = not (p and p.api_key)
        exempt = spec and (spec.is_oauth or spec.is_local or spec.is_direct)
        if needs_key and not exempt:
            logger.warning(
                f"No API key found for provider '{provider_name or 'auto-detected'}': "
                f"{vars(p) if p else 'No provider config found'}"
            )
            raise ValueError(
                f"No API key configured for {provider_name or 'the selected provider'}.\n"
                "Set one in config.json under the appropriate providers section."
            )

    # --- instantiation by backend ---
    if backend == "openai_codex":
        from nanobot.providers.openai_codex_provider import OpenAICodexClient

        provider = OpenAICodexClient(default_model=model)
    elif backend == "azure_openai":
        from nanobot.providers.azure_openai_provider import AzureOpenAIClient

        provider = AzureOpenAIClient(
            api_key=p.api_key,  # type: ignore
            api_base=p.api_base,  # type: ignore
            default_model=model,
        )
    elif backend == "anthropic":
        from nanobot.providers.anthropic_provider import AnthropicClient

        provider = AnthropicClient(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(
                model, agent_name=agent_name, provider_override=provider_override
            ),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
        )
    elif backend == "gemini_native":
        from nanobot.providers.gemini_provider import GeminiNativeClient

        provider = GeminiNativeClient(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(
                model, agent_name=agent_name, provider_override=provider_override
            ),
            default_model=model,
            grounding=agent_config.grounding,
        )
    else:
        from nanobot.providers.openai_compat_provider import OpenAICompatClient

        provider = OpenAICompatClient(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(
                model, agent_name=agent_name, provider_override=provider_override
            ),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            spec=spec,
        )

    # For single providers, try to lookup context_max if it's a known model key
    context_max = None
    if model in config.models:
        context_max = config.models[model].context_max

    provider.generation = GenerationSettings(
        temperature=agent_config.temperature,
        max_tokens=agent_config.max_tokens,
        reasoning_effort=agent_config.reasoning_effort,
        context_max=context_max,
    )
    provider.debug = config.debug_llm
    provider.dump_dir = config.workspace_path / "logs"
    return provider
