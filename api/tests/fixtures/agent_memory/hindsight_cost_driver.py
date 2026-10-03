"""Exercise real bank-bound foreground/background calls in Hindsight 0.10.2."""

import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, "/opt/agentbarn")
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
    await provider.cleanup()
    print("HINDSIGHT_COST_CONTRACT=ok")


asyncio.run(main())
