# Configuration for ./deploy.sh (helmfile sync).
# Copy to .env.deploy and fill in. .env.deploy is gitignored.

# ── Cluster access ───────────────────────────────────────────────────────────
# Kubeconfig on THIS machine that helm/helmfile use to reach the cluster.
# For k3s: copy /etc/rancher/k3s/k3s.yaml somewhere readable and point here.
KUBECONFIG=$HOME/.kube/config

# ── Container registry ───────────────────────────────────────────────────────
REGISTRY_PREFIX=registry.k8s.aai-labs.com
REGISTRY_SERVER=registry.k8s.aai-labs.com
REGISTRY_USERNAME=
REGISTRY_PASSWORD=

# Image repository names under REGISTRY_PREFIX. Defaults match the internal
# registry. The client release bundle ships these set to api/ui/hermes-base/
# openclaw-base under REGISTRY_PREFIX=clients.registry.k8s.aai-labs.com/agent-farm.
API_IMAGE_REPOSITORY=agentfarm-api
UI_IMAGE_REPOSITORY=agentfarm-ui
HERMES_IMAGE_REPOSITORY=agentfarm-hermes-base
OPENCLAW_IMAGE_REPOSITORY=agentfarm-openclaw-base

# ── Image tags (pin to specific versions for a real deploy) ──────────────────
API_IMAGE_TAG=0.13.0
UI_IMAGE_TAG=0.13.0
OPENCLAW_IMAGE_TAG=0.4.0
HERMES_IMAGE_TAG=0.1.0

# ── Postgres (app DB) ────────────────────────────────────────────────────────
POSTGRES_APP_USER=agentfarm
POSTGRES_APP_PASSWORD=
POSTGRES_APP_DB=agentfarm

# ── Postgres (LiteLLM DB) ────────────────────────────────────────────────────
POSTGRES_LITELLM_USER=litellm
POSTGRES_LITELLM_PASSWORD=
POSTGRES_LITELLM_DB=litellm

# ── LiteLLM + OpenRouter ─────────────────────────────────────────────────────
# Any strong secret prefixed with sk-; LiteLLM uses it to mint agent-scoped
# virtual keys. Pick once and keep it stable. Generate with:
#   echo "sk-$(openssl rand -hex 24)"
LITELLM_MASTER_KEY=
# Real key from your OpenRouter dashboard (sk-or-...), not generated locally.
OPENROUTER_API_KEY=

# ── API secrets ──────────────────────────────────────────────────────────────
SECRET_SIGNING_KEY=
# Fernet key. Generate once and keep it stable, or stored tokens can't decrypt:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
AGENT_TOKEN_ENCRYPTION_KEY=
# Format: email:password
SUPER_USER_CREDENTIALS=admin@example.com:
SUPER_USER_FULL_NAME=
ENVIRONMENT=local

# ── URLs / ingress hosts ─────────────────────────────────────────────────────
# Hostnames the ingress serves. Point DNS (or /etc/hosts) at the cluster.
API_HOST=api.agentfarm.local
UI_HOST=agentfarm.local
WEB_APP_URL=http://agentfarm.local

# ── Gmail OAuth (AF-153) ─────────────────────────────────────────────────────
# Shared Google OAuth 2.0 "Web application" client for the Gmail "Authenticate
# with Google" flow. Leave blank to disable. Register
# "<WEB_APP_URL>/api/v1/integrations/google/callback" as an authorized redirect URI.
GOOGLE_CLOUD_CLIENT_ID=
GOOGLE_CLOUD_CLIENT_SECRET=

# ── Ingress TLS ──────────────────────────────────────────────────────────────
# cert-manager ClusterIssuer that signs the api/ui ingress certs. cert-manager
# is required. letsencrypt-http01 needs a publicly reachable host, so for a
# local cluster install cert-manager and create a self-signed/CA ClusterIssuer,
# then set its name here.
INGRESS_CLUSTER_ISSUER=letsencrypt-http01

# ── Storage ──────────────────────────────────────────────────────────────────
# Empty falls through to the cluster's default StorageClass. k3s default is
# local-path. Set to a network-replicated class for node-loss durability.
STORAGE_CLASS=local-path

# ── Model picker (AF-128) ────────────────────────────────────────────────────
# Comma-separated fnmatch globs limiting OpenRouter models, e.g. z-ai/glm-5.2,openai/gpt-5*
# Empty offers the full catalogue.
AGENT_MODEL_ALLOWLIST=
# Default model. Format: litellm/openrouter/<slug>
# e.g. litellm/openrouter/z-ai/glm-5.2. Empty uses the API's built-in default.
AGENT_DEFAULT_MODEL=

# ── Optional ─────────────────────────────────────────────────────────────────
# Kubeconfig the API pod uses to manage agent workloads. Defaults to base64 of
# $KUBECONFIG (deploy.sh derives it). Set only if the API pod must use a
# different identity or cluster than this deploy.
# POD_KUBECONFIG_B64=
