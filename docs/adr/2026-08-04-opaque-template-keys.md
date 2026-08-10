# Opaque immutable template keys

Status: Accepted
Date: 2026-08-04
Origin: Template slug-to-key migration

Template names are display labels rather than identifiers. New template lineages therefore receive an opaque server-generated `tpl-<12 lowercase hex>` key, which remains stable through versions, drafts, restores, publishes, and organization forks. Opaque keys avoid name-derived collisions and keep future label changes from affecting URLs or API references.

## Decision

- Generate keys with `secrets.token_hex(6)` and the `tpl-` prefix.
- Serialize generated-key allocation with a transaction advisory lock, check all template tables, and retry random-key conflicts during creation; existing lineage/version constraints remain in place.
- Rename the persisted/API concept from `template_slug` to `template_key` without rewriting existing values.
- Keep existing Agent foreign-key pins unchanged; resolve their key from the pinned template row.
- Treat `template_name` as a non-unique display label and keep its existing immutability across versions.
- Make `template_key` the sole Agent create/repin API field after the migration; no deprecated slug alias is retained.

The UI does not ask authors to provide, preview, or edit a key; it uses the key internally for navigation and API requests.
