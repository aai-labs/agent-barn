"""Bank cost attribution bridge for the pinned Hindsight 0.10.2 OpenAI provider.

Run as the API entrypoint, so an incompatible provider fails startup rather than
quietly dropping attribution. ContextVars cover foreground and background calls.
"""

from uuid import UUID


def install():
    from hindsight_api.engine.llm_trace import current_trace_context
    from hindsight_api.engine.providers.openai_compatible_llm import OpenAICompatibleLLM

    original = OpenAICompatibleLLM._apply_provider_extra_body_defaults
    if getattr(original, "_agentbarn_attribution", False):
        return

    def apply_defaults(self, extra_body):
        original(self, extra_body)
        if self.provider != "openai":
            raise RuntimeError("Agent Barn memory cost attribution requires the pinned OpenAI provider.")
        extra_body.pop("user", None)
        context = current_trace_context()
        bank = context.bank_id if context else None
        if bank is None:
            return  # Server verification calls have no Organization to charge.
        try:
            organization_id = UUID(bank.removeprefix("org-"))
        except (ValueError, AttributeError):
            raise RuntimeError("Agent Barn memory operation has no canonical Organization bank.") from None
        if bank != f"org-{organization_id}":
            raise RuntimeError("Agent Barn memory operation has no canonical Organization bank.")
        extra_body["user"] = bank

    apply_defaults._agentbarn_attribution = True
    OpenAICompatibleLLM._apply_provider_extra_body_defaults = apply_defaults


if __name__ == "__main__":
    install()
    from hindsight_api.main import main

    main()
