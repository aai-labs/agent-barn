# Authentication and authorization

Personal API keys use the same `Authorization: Bearer` header as session access JWTs. They are opaque values beginning `abk_`; their complete value is shown only when created. Store them in a secret manager. The server stores only a hash and safe display prefix.

Each key belongs to one User, not one Organization. The User's current Membership is required for each Organization route. Organization Owner and Admin roles have implicit Agent Owner authority; Members need Agent Access for a particular Agent. An inaccessible Agent or subordinate record returns 404. A visible resource without an action Permission returns 403. Platform routes require current Platform Administrator privilege. Read-only keys cannot send mutating methods and cannot initiate Google authorization.

Keys have no expiration unless one is set at creation. Revoke a key at any time in Account settings or through `DELETE /api/v1/auth/me/api-keys/{key_id}`. Changing or resetting the password invalidates keys created under the old security stamp. Revocation takes effect on the next request. Rotate by creating a replacement, changing the client, then revoking the old key.

A full-access key can create and revoke other keys belonging to the same User. A read-only key can list key metadata but cannot create or revoke. Key management uses `POST` and `GET /api/v1/auth/me/api-keys`.

An invalid, expired, revoked, or invalidated key returns 401. Authorization failures return 403, and hidden tenant resources return 404. FastAPI request validation returns 422. Follow the response's `detail` field for errors.
