"""Exercise real bank-bound foreground/background calls in Hindsight 0.10.2."""

import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, "/opt/agentbarn")
if os.environ.get("CONTRACT_SETTINGS_URL"):
    os.environ["AGENTBARN_MEMORY_SETTINGS_URL"] = os.environ["CONTRACT_SETTINGS_URL"]
    os.environ["AGENTBARN_MEMORY_SETTINGS_KEY"] = "memory-settings-contract-key"
    os.environ["HINDSIGHT_API_TENANT_API_KEY"] = "backend-model-test-key"

from start_hindsight import install  # ty: ignore[unresolved-import]

install()
install()  # Loading twice must not wrap twice.

from hindsight_api.engine.llm_wrapper import LLMProvider  # ty: ignore[unresolved-import]

BANKS = ["org-11111111-2222-3333-4444-555555555555", "org-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]


async def main():
    provider = LLMProvider(
        provider="openai",
        api_key="memory-cost-contract-key",
        base_url=os.environ["CONTRACT_URL"],
        model="memory-cost-contract-model",
        extra_body={"user": "forged-static-bank"},
    )
    config = SimpleNamespace(llm_gemini_safety_settings=None)

    async def call(bank, operation):
        bound = provider.with_config(config, bank_id=bank, operation=operation)
        await bound.call(
            messages=[{"role": "user", "content": operation}],
            scope=operation,
            max_retries=0,
        )

    await asyncio.gather(
        call(BANKS[0], "retain"),
        call(BANKS[1], "reflect"),
        asyncio.create_task(call(BANKS[0], "consolidation")),
    )
    await provider.call(messages=[{"role": "user", "content": "startup"}], max_retries=0)
    if os.environ.get("CONTRACT_SETTINGS_URL"):
        import httpx

        held = provider.with_config(config, bank_id=BANKS[0], operation="held")
        await held.call(messages=[{"role": "user", "content": "held-before"}], max_retries=0)
        async with httpx.AsyncClient() as client:
            await client.post(os.environ["CONTRACT_SETTINGS_URL"], json={"model": "openrouter/contract/second"})
        await asyncio.sleep(5.1)
        await call(BANKS[1], "updated-model")
        await held.call(messages=[{"role": "user", "content": "held-after"}], max_retries=0)
        await provider.with_config(config, bank_id=BANKS[0], operation="tools").call_with_tools(
            messages=[{"role": "user", "content": "updated-tools"}],
            tools=[
                {"type": "function", "function": {"name": "lookup", "parameters": {"type": "object", "properties": {}}}}
            ],
            max_retries=0,
        )
        async with httpx.AsyncClient() as client:
            await client.post(os.environ["CONTRACT_SETTINGS_URL"], json={"unavailable": True})
        await asyncio.sleep(5.1)
        try:
            await call(BANKS[1], "unavailable-settings")
        except Exception as exc:
            assert "settings unavailable" in str(exc), str(exc)
        else:
            raise AssertionError("Bank processing fell back to the bootstrap key")
    await provider.cleanup()
    print("HINDSIGHT_COST_CONTRACT=ok")


asyncio.run(main())
