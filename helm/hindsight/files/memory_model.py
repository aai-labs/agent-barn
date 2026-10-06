"""Freeze the platform model and Organization team credential per operation."""
import asyncio
import inspect
import os
import time
from collections import OrderedDict
from contextvars import ContextVar

import httpx


startup_verification = ContextVar("agentbarn_startup_verification", default=False)


class ModelSelection:
    def __init__(self, url, key):
        self.url, self.key = url, key
        # Bounded stripes avoid serializing unrelated Organizations or retaining a lock per bank.
        self.locks = [asyncio.Lock() for _ in range(64)]
        self.profiles = OrderedDict()
        self.operations = OrderedDict()

    async def resolve(self, fallback, operation, bank=None):
        if bank is None and not startup_verification.get():
            raise RuntimeError("Memory processing requires an Organization bank outside startup verification")
        operation_key = (bank, operation)
        if operation and operation_key in self.operations:
            return self.operations[operation_key]
        async with self.locks[hash(bank) % len(self.locks)]:
            profile, expires = self.profiles.get(bank, (None, 0))
            if time.monotonic() >= expires:
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=2), trust_env=False, follow_redirects=False) as client:
                        response = await client.get(
                            self.url, params={"bank": bank} if bank else None,
                            headers={"Authorization": f"Bearer {self.key}"},
                        )
                        response.raise_for_status()
                        payload = response.json()
                        model, api_key = payload["model"], payload.get("api_key")
                        if not isinstance(model, str) or not model.startswith("openrouter/"):
                            raise ValueError("Unexpected memory model")
                        if bank and (not isinstance(api_key, str) or not api_key):
                            raise ValueError("Organization memory credential unavailable")
                        profile = (model, api_key)
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    if bank:
                        self.profiles[bank] = (None, time.monotonic() + 1)
                        self.profiles.move_to_end(bank)
                        if len(self.profiles) > 256:
                            self.profiles.popitem(last=False)
                        # Falling back to the bootstrap key bypasses the Organization cap.
                        raise RuntimeError("Organization memory processing settings unavailable") from None
                    profile = profile or (fallback, None)
                self.profiles[bank] = (profile, time.monotonic() + 5)
                self.profiles.move_to_end(bank)
                if len(self.profiles) > 256:
                    self.profiles.popitem(last=False)
        if profile is None:
            raise RuntimeError("Organization memory processing settings unavailable")
        if operation:
            self.operations[operation_key] = profile
            if len(self.operations) > 1024:
                self.operations.popitem(last=False)
        return profile


def install_model_selection():
    url = os.environ.get("AGENTBARN_MEMORY_SETTINGS_URL")
    if not url:
        return  # Operator-run images may not use platform settings.
    key = os.environ.get("AGENTBARN_MEMORY_SETTINGS_KEY")
    if not key or key == os.environ.get("HINDSIGHT_API_TENANT_API_KEY"):
        raise RuntimeError("Memory settings require a dedicated service credential.")
    from hindsight_api.engine.llm_trace import current_trace_context
    from hindsight_api.engine.providers.openai_compatible_llm import OpenAICompatibleLLM

    cls = OpenAICompatibleLLM
    original_init = cls.__init__
    signature = inspect.signature(original_init)
    selection = ModelSelection(url, key)
    original_call, original_tools, original_cleanup = cls.call, cls.call_with_tools, cls.cleanup

    def initialize(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        bound.apply_defaults()
        parameters = dict(bound.arguments)
        parameters.pop("self")
        parameters.update(parameters.pop("kwargs", {}))
        original_init(self, *args, **kwargs)
        self._agentbarn_model_parameters = parameters

    async def invoke(self, method, args, kwargs):
        trace = current_trace_context()
        model, api_key = await selection.resolve(
            self.model, trace.trace_id if trace else None, trace.bank_id if trace else None
        )
        parameters = {**self._agentbarn_model_parameters, "model": model}
        if api_key:
            parameters["api_key"] = api_key
        provider = cls(**parameters)
        try:
            return await method(provider, *args, **kwargs)
        finally:
            # Bound client lifetime; no permanent provider pool per Organization.
            await original_cleanup(provider)

    async def call(self, *args, **kwargs):
        return await invoke(self, original_call, args, kwargs)

    async def tools(self, *args, **kwargs):
        return await invoke(self, original_tools, args, kwargs)

    cls.__init__, cls.call, cls.call_with_tools = initialize, call, tools
