from fastapi import FastAPI, Request
from injector import Injector

from api.core.utils import create_injector
from api.domains.memory_proxy.proxy import MemoryProxy

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def create_memory_proxy_app(injector: Injector | None = None, proxy: MemoryProxy | None = None) -> FastAPI:
    """The memory proxy Agents call instead of Honcho (AF-338)."""
    if proxy is None:
        proxy = (injector or create_injector()).get(MemoryProxy)

    app = FastAPI()

    # Declared before the catch-all so it is matched first.
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # Mounted at the root: Honcho's own paths (`/v3/...`) arrive unchanged, since
    # the Agent is named by its key, not its address.
    @app.api_route("/{path:path}", methods=_METHODS, include_in_schema=False)
    async def forward(request: Request, path: str):
        return await proxy.forward(request, path)

    return app
