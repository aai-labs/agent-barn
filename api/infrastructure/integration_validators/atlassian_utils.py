import httpx

_TIMEOUT = 10
_cloud_id_cache: dict[str, str] = {}


def get_atlassian_cloud_id(site_url: str, token: str) -> tuple[str | None, str | None]:
    """Resolve the Atlassian cloud ID for a given site URL.

    For Service Account tokens, accessible-resources returns 401. Instead, we
    fetch the cloudId from the unauthenticated _edge/tenant_info endpoint
    available on all Atlassian Cloud sites.
    """
    cache_key = site_url
    if cache_key in _cloud_id_cache:
        return _cloud_id_cache[cache_key], None

    try:
        base = site_url.rstrip("/")
        resp = httpx.get(f"{base}/_edge/tenant_info", timeout=_TIMEOUT)

        if resp.status_code != 200:
            return (
                None,
                f"Failed to fetch tenant info. Status {resp.status_code}: {resp.text[:200]}",
            )

        data = resp.json()
        cloud_id = data.get("cloudId")

        if not cloud_id:
            return None, "Site did not return a cloudId in tenant_info."

        _cloud_id_cache[cache_key] = cloud_id
        return cloud_id, None

    except Exception as exc:
        return None, f"Network error fetching cloud ID: {exc}"
