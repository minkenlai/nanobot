"""Factory for instantiating LLM providers from configuration."""

from nanobot.config.schema import Config
from nanobot.providers.base import GenerationSettings, LLMProvider
from nanobot.providers.registry import find_by_name


def build_provider(config: Config, agent_name: str = "defaults") -> LLMProvider:
    """Create the appropriate LLM provider from config.

    Two modes:
    - **Single Provider:** fallback_models is empty. Uses the configured
      model and provider fields.
    - **Fallback Chain:** fallback_models is a non-empty ordered list
      of keys into the top-level models dict. Builds a FallbackProvider
      that tries each slot in order on quota errors. The agent's base
      'model' and 'provider' fields are ignored.
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
    slots: list[tuple[LLMProvider, str]] = []
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
        )

        # Apply prefill override if the provider supports it.
        if mc.prefill is not None and hasattr(slot_provider, "prefill"):
            slot_provider.prefill = mc.prefill

        slots.append((slot_provider, mc.model))

    if len(slots) == 1:
        # Single-entry chain — no wrapper needed.
        return slots[0][0]

    from nanobot.providers.fallback import FallbackProvider

    return FallbackProvider(slots)


def _build_single_provider(
    config: Config, agent_name: str, model: str, provider_override: str = "auto"
) -> LLMProvider:
    """Instantiate a single LLM provider for *model* using *config*."""
    agent_config = config.agents.get_agent(agent_name)

    # Temporarily override the provider field so _match_provider picks the right one.
    original_provider = agent_config.provider
    if provider_override != "auto":
        agent_config.provider = provider_override

    try:
        provider_name = config.get_provider_name(model, agent_name=agent_name)
        p = config.get_provider(model, agent_name=agent_name)
        spec = find_by_name(provider_name) if provider_name else None
        backend = spec.backend if spec else "openai_compat"
    finally:
        agent_config.provider = original_provider

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
            raise ValueError(
                f"No API key configured for {provider_name or 'the selected provider'}.\n"
                "Set one in config.json under the appropriate providers section."
            )

    # --- instantiation by backend ---
    if backend == "openai_codex":
        from nanobot.providers.openai_codex_provider import OpenAICodexProvider

        provider = OpenAICodexProvider(default_model=model)
    elif backend == "azure_openai":
        from nanobot.providers.azure_openai_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider(
            api_key=p.api_key,  # type: ignore
            api_base=p.api_base,  # type: ignore
            default_model=model,
        )
    elif backend == "anthropic":
        from nanobot.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model, agent_name=agent_name),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
        )
    elif backend == "gemini_native":
        from nanobot.providers.gemini_provider import GeminiNativeProvider

        provider = GeminiNativeProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model, agent_name=agent_name),
            default_model=model,
            grounding=agent_config.grounding,
        )
    else:
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model, agent_name=agent_name),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            spec=spec,
        )

    provider.generation = GenerationSettings(
        temperature=agent_config.temperature,
        max_tokens=agent_config.max_tokens,
        reasoning_effort=agent_config.reasoning_effort,
    )
    return provider
