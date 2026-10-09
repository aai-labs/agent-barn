# Platform administration and API compatibility

A User with current Platform Administrator privilege can use their personal API key on `/api/v1/platform/...` routes. These include user provisioning and privilege management, Organization oversight, Platform Templates and Skills, summary statistics, and Event Delivery monitoring. Platform authority does not create Organization Membership or allow tenant content access through an Organization route.

The `/api/v1` OpenAPI schema is the supported product contract. Additive operations and fields may appear in v1. Incompatible request or response changes require a new major API version. Use the machine-readable [OpenAPI schema](/api/v1/openapi.json) or [operation discovery](/api/v1/discovery) to inspect the current deployment.

API writes are not generally idempotent. If a network error leaves a write's result uncertain, read the resource state before retrying. A 409 indicates a conflict or invalid transition; a 503 means a dependency is unavailable. Avoid logging Bearer credentials or raw request bodies containing Secrets.
