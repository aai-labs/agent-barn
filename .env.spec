POSTGRES_USER=your_postgres_user
POSTGRES_PASSWORD=your_postgres_password
POSTGRES_DB=your_database_name
POSTGRES_PORT=5432

API_PORT=8000
ENVIRONMENT=local
UI_APP_URL=http://localhost:3000

# Optional: Redis is only needed to run the event delivery worker/reconciler
# locally (`make redis-up`, `make dev-worker`); defaults to localhost:6379.
REDIS_PORT=6379
REDIS_URL=redis://localhost:6379/0

SECRET_SIGNING_KEY=replace_with_a_secure_random_value
PLATFORM_ADMIN_CREDENTIALS=admin@example.com:replace_with_secure_password

# Optional: if unset, email delivery is disabled and send attempts are logged. All three
# are required for delivery. Transactional mail goes through Cloudflare Email Sending.
# The token needs the "Email Sending: Edit" permission on the account below, and
# SENDER_EMAIL's domain must be onboarded and Verified there or Cloudflare rejects sends.
# Each environment sends from its own `mail.`-style subdomain to keep sending reputation
# off the root domain. Example: noreply@mail.agentbarn.dev
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_API_TOKEN=
SENDER_EMAIL=

# Optional: shared Google OAuth 2.0 "Web application" client for the Gmail
# "Authenticate with Google" flow. If unset, the flow is disabled. Register
# "<WEB_APP_URL>/api/v1/integrations/google/callback" as an authorized redirect URI.
GOOGLE_CLOUD_CLIENT_ID=
GOOGLE_CLOUD_CLIENT_SECRET=

# Kubernetes client
# Path to kubeconfig file. If unset, tries in-cluster auth then ~/.kube/config.
K8S_KUBECONFIG_PATH=
K8S_NAMESPACE=agent-farm
# StorageClass for PVCs (Postgres + agent pods). Empty falls through to the
# cluster's default StorageClass. aai-labs default is local-path; set to a
# network-replicated class (e.g. rook-ceph-block-main, GKE premium-rwo) for
# node-loss durability. Note: changing this on an existing Postgres deployment
# requires a data migration (StatefulSet volumeClaimTemplates are immutable).
STORAGE_CLASS=

# Agents
# Full image ref for agent pods, e.g. {REGISTRY_URL}/agentfarm-openclaw-base:{VERSION}
AGENT_IMAGE=
# Fernet key for encrypting Slack tokens at rest. Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
AGENT_TOKEN_ENCRYPTION_KEY=
# Name of the k8s imagePullSecret for the agent container image registry.
# Example: registry-pull-secret
AGENT_IMAGE_PULL_SECRET=
# LiteLLM proxy URL used by the API for key generation. Example: http://localhost:4000 (local port-forward)
LITELLM_BASE_URL=
# LiteLLM proxy URL injected into agent pods as LITELLM_BASE_URL. Example: http://litellm:4000
AGENT_LITELLM_BASE_URL=
# Name of the k8s Secret containing LITELLM_MASTER_KEY. Defaults to "litellm".
LITELLM_SECRET_NAME=litellm
# Default model for openclaw agents when agent.model is not set. Format: litellm/openrouter/<slug>
AGENT_DEFAULT_MODEL=litellm/openrouter/z-ai/glm-5.2
# OpenRouter API key used to fetch the model catalogue for the picker. Optional —
# the public catalogue endpoint works unauthenticated.
OPENROUTER_API_KEY=
# Comma-separated fnmatch globs limiting which OpenRouter models the picker offers,
# e.g. "z-ai/glm-5.2,openai/gpt-5*". Empty offers the full catalogue.
AGENT_MODEL_ALLOWLIST=
