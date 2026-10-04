"""Live platform model selection for the pinned OpenAI-compatible provider.

Models are bound to separate provider instances and frozen per operation. Updating
settings cannot mutate an in-flight call or change its bank attribution.
"""
import asyncio
import inspect
import logging
import os
import time
from collections import OrderedDict

import httpx

logger = logging.getLogger(__name__)


class ModelSelection:
    def __init__(self, url, key):
        self.url, self.key = url, key
        self.model = None
        self.expires = 0
        self.lock = asyncio.Lock()
        self.operations = OrderedDict()

    async def resolve(self, fallback, operation):
        if operation and operation in self.operations:
            return self.operations[operation]
        async with self.lock:
            if time.monotonic() >= self.expires:
                try:
                    async with httpx.AsyncClient(timeout=1, trust_env=False, follow_redirects=False) as client:
                        response = await client.get(self.url, headers={"Authorization": f"Bearer {self.key}"})
                        response.raise_for_status()
                        model = response.json()["model"]
                        if not isinstance(model, str) or not model.startswith("openrouter/"):
                            raise ValueError("Unexpected memory model")
                        self.model = model
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    logger.warning("Memory model settings unavailable; retaining the last known model.")
                self.expires = time.monotonic() + 5
            model = self.model or fallback
        if operation:
            self.operations[operation] = model
            if len(self.operations) > 1024:
                self.operations.popitem(last=False)
        return model


def install_model_selection():
    url = os.environ.get("AGENTBARN_MEMORY_SETTINGS_URL")
    if not url:
        return  # Compatibility with operator-run images not using platform settings.
    key = os.environ.get("HINDSIGHT_API_TENANT_API_KEY")
    if not key:
        raise RuntimeError("Memory settings require Hindsight's service credential.")
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
        self._agentbarn_model_providers = {}

    async def target(self):
        trace = current_trace_context()
        model = await selection.resolve(self.model, trace.trace_id if trace else None)
        if model == self.model:
            return self
        if model not in self._agentbarn_model_providers:
            parameters = {**self._agentbarn_model_parameters, "model": model}
            self._agentbarn_model_providers[model] = cls(**parameters)
        return self._agentbarn_model_providers[model]

    async def call(self, *args, **kwargs):
        return await original_call(await target(self), *args, **kwargs)

    async def tools(self, *args, **kwargs):
        return await original_tools(await target(self), *args, **kwargs)

    async def cleanup(self):
        for provider in self._agentbarn_model_providers.values():
            await original_cleanup(provider)
        await original_cleanup(self)

    cls.__init__, cls.call, cls.call_with_tools, cls.cleanup = initialize, call, tools, cleanup
