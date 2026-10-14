"""SharePoint site URL handling for the selected-sites mode.

A grant under ``Sites.Selected`` is per site, but a URL pasted from the browser usually points
somewhere inside one — a document library, a list view — so it is reduced to the site root
before it is granted, stored or shown. Mirrors merkys' ``normalize_site_url``; the UI's
``normalizeSiteUrl`` must stay in step with it.
"""

from urllib.parse import quote, unquote, urlparse

_SITE_COLLECTION_SEGMENTS = ("sites", "teams")


def normalize_site_url(url: str) -> str:
    """Return the canonical ``https://<tenant>.sharepoint.com[/sites|/teams/<name>]`` form.

    Raises ValueError for anything that is not an https SharePoint Online URL.
    """
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if parsed.scheme != "https" or not host.endswith(".sharepoint.com"):
        raise ValueError(f"not a SharePoint Online site URL: {url}")

    segments = [segment for segment in unquote(parsed.path).split("/") if segment]
    if segments and segments[0].lower() in _SITE_COLLECTION_SEGMENTS:
        if len(segments) < 2:
            raise ValueError(f"missing site name in URL: {url}")
        return f"https://{host}/{segments[0].lower()}/{segments[1]}"
    return f"https://{host}"


def site_graph_path(site_url: str) -> str:
    """Graph's ``{hostname}:/{server-relative-path}`` addressing for a normalised site URL.

    The tenant's root site is addressed by hostname alone.
    """
    parsed = urlparse(site_url)
    segments = [quote(segment, safe="") for segment in parsed.path.split("/") if segment]
    return f"{parsed.netloc}:/{'/'.join(segments)}" if segments else parsed.netloc
