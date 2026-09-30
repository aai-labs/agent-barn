from html import escape
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from markdown_it import MarkdownIt
from pydantic import BaseModel

router = APIRouter(tags=["developer-documentation"])
DOCS = Path(__file__).resolve().parents[2] / "developer_docs"
GUIDES = ("quickstart", "authentication", "agents", "resources", "platform")


class OperationRead(BaseModel):
    operation_id: str
    method: str
    path: str
    summary: str
    tags: list[str]
    security: list[dict[str, list[str]]]
    api_key_access_mode: str | None
    scope: str


class DiscoveryRead(BaseModel):
    api_version: str
    base_url: str
    openapi_url: str
    reference_url: str
    guides_url: str
    llms_url: str
    operations: list[OperationRead]


def _guide(slug: str) -> str:
    if slug not in GUIDES:
        raise HTTPException(status_code=404, detail="Guide not found")
    return (DOCS / f"{slug}.md").read_text(encoding="utf-8")


@router.get("/discovery", response_model=DiscoveryRead)
def discover(request: Request):
    paths = request.app.openapi()["paths"]
    operations = [
        {
            "operation_id": operation["operationId"],
            "method": method.upper(),
            "path": path,
            "summary": operation.get("summary", ""),
            "tags": operation.get("tags", []),
            "security": operation.get("security", []),
            "api_key_access_mode": (
                None
                if not operation.get("security")
                else "FULL"
                if method != "get" or path == "/integrations/google/authorize-url"
                else "READ_ONLY"
            ),
            "scope": (
                "platform"
                if path.startswith("/platform/")
                else "organization"
                if "{organization_id}" in path
                else "user_or_public"
            ),
        }
        for path, methods in paths.items()
        for method, operation in methods.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    return {
        "api_version": "v1",
        "base_url": "/api/v1",
        "openapi_url": "/api/v1/openapi.json",
        "reference_url": "/api/v1/docs",
        "guides_url": "/api/v1/developer",
        "llms_url": "/api/v1/llms.txt",
        "operations": operations,
    }


@router.get("/reference", include_in_schema=False)
def reference():
    return RedirectResponse("/api/v1/docs")


@router.get("/developer", response_class=HTMLResponse)
def developer_index():
    links = "".join(f'<li><a href="/api/v1/developer/{slug}">{escape(slug.title())}</a></li>' for slug in GUIDES)
    return HTMLResponse(
        "<!doctype html><html lang='en'><meta charset='utf-8'><title>AgentBarn API</title>"
        "<body style='font:16px system-ui;max-width:850px;margin:48px auto;line-height:1.6'>"
        "<h1>AgentBarn API</h1><p>Use a personal API key to call the existing v1 API.</p>"
        f"<ul>{links}</ul><p><a href='/api/v1/docs'>Interactive reference</a> · "
        "<a href='/api/v1/openapi.json'>OpenAPI</a></p></body></html>"
    )


@router.get("/developer/{slug}.md", response_class=PlainTextResponse)
def guide_markdown(slug: str):
    return PlainTextResponse(_guide(slug), media_type="text/markdown; charset=utf-8")


@router.get("/developer/{slug}", response_class=HTMLResponse)
def guide_html(slug: str):
    title = escape(slug.title())
    rendered = MarkdownIt("commonmark", {"html": False}).render(_guide(slug))
    return HTMLResponse(
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        f"<title>{title} · AgentBarn API</title>"
        f"<link rel='alternate' type='text/markdown' href='/api/v1/developer/{slug}.md'>"
        "<body style='font:16px system-ui;max-width:850px;margin:48px auto;line-height:1.6'>"
        "<p><a href='/api/v1/developer'>← API guides</a></p>"
        f"<article>{rendered}</article></body></html>"
    )


@router.get("/llms.txt", response_class=PlainTextResponse)
def llms_txt():
    guides = "\n".join(f"- [{slug.title()}](/api/v1/developer/{slug}.md): {slug.title()} guide." for slug in GUIDES)
    return PlainTextResponse(
        "# AgentBarn API\n\n> Organization-owned AI agent platform with a versioned HTTP API.\n\n"
        "Use an API key as a Bearer token. Call /api/v1/auth/context first to discover your user and Organizations. "
        "Organization resources use /api/v1/organizations/{organization_id}/...; platform routes require Platform Administrator authority.\n\n"
        f"## Guides\n{guides}\n\n## Reference\n"
        "- [OpenAPI](/api/v1/openapi.json): Complete machine-readable endpoint contract.\n"
        "- [Interactive reference](/api/v1/docs): Explore all product API operations.\n"
        "- [Operation discovery](/api/v1/discovery): Compact JSON catalog.\n",
        media_type="text/markdown; charset=utf-8",
    )


@router.get("/llms-full.txt", response_class=PlainTextResponse)
def llms_full_txt():
    return PlainTextResponse(
        "\n\n".join(_guide(slug) for slug in GUIDES),
        media_type="text/markdown; charset=utf-8",
    )
