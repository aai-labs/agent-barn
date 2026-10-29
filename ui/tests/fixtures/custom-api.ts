export const mockCustomApiConnection = {
  id: "55555555-5555-4555-8555-555555555555",
  slug: "inventory-api",
  name: "Inventory API",
  base_url: "https://api.example.com/v1",
  isolated: false,
  applied_isolated: false,
  pending_apply: false,
  auth_type: "api_key",
  auth_header_name: "X-API-Key",
  auth_token_url: null,
  auth_scope: null,
  headers: [
    { name: "Accept", secret: false, value: "application/json" },
    { name: "X-Private", secret: true, value: null },
  ],
};
