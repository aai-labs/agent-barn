/**
 * Reduce a SharePoint URL to its site root, or return null if it isn't one.
 *
 * Access is granted per site, but an address pasted from the browser usually points
 * somewhere inside one (a document library, a list view). Must stay in step with
 * `normalize_site_url` in api/domains/agents/sharepoint_sites.py: https only, a
 * `*.sharepoint.com` host lowercased, and `/sites/<name>` or `/teams/<name>` kept with the
 * name's case; anything deeper is dropped.
 */
export function normalizeSiteUrl(raw: string): string | null {
  let url: URL;
  try {
    url = new URL(raw.trim());
  } catch {
    return null;
  }
  const host = url.host.toLowerCase();
  if (url.protocol !== "https:" || !host.endsWith(".sharepoint.com")) return null;

  let path = url.pathname;
  try {
    path = decodeURIComponent(path);
  } catch {
    // Keep the raw path; a malformed escape shouldn't hide an otherwise valid site.
  }
  const segments = path.split("/").filter(Boolean);
  if (segments.length > 0 && ["sites", "teams"].includes(segments[0].toLowerCase())) {
    if (segments.length < 2) return null;
    return `https://${host}/${segments[0].toLowerCase()}/${segments[1]}`;
  }
  return `https://${host}`;
}
